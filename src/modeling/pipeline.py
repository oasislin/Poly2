#!/usr/bin/env python3
"""
TrainingPipeline: End-to-end training and validation orchestrator for Phase 1B (Ticket 2.3-03 / Issue #22).

Coordinates:
    1. Climatology baseline fitting (2000-2018 OOS observations)
    2. 40-model matrix batch training (MatrixTrainer)
    3. Dense 6h-spaced grid interpolation (LeadTimeInterpolator)
    4. Standardized model persistence (ModelRegistry)
    5. Strict time-wall out-of-sample evaluation (ValidationEngine)
    6. Triple Acceptance Gate verification & Markdown report generation (ReportGenerator)
"""

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union
import numpy as np
import pandas as pd
from scipy import stats

from src.data_processing.constants import ACTIVE_10_STATIONS
from src.data_processing.storage_manager import StorageManager
from src.modeling.climatology import ClimatologyCalculator
from src.modeling.crps import gaussian_crps
from src.modeling.degradation import DegradationHandler
from src.modeling.emos_trainer import EMOSOptimizer
from src.modeling.gaussian_emos import GaussianEMOS
from src.modeling.interpolator import LeadTimeInterpolator
from src.modeling.matrix_trainer import MatrixScorecard, MatrixTrainer
from src.modeling.partitioner import DatasetPartitioner
from src.modeling.registry import ModelRegistry
from src.modeling.report_generator import AcceptanceReport, ReportGenerator
from src.modeling.validation_engine import ValidationEngine, ValidationResult

logger = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Encapsulates all artifacts produced by an end-to-end training pipeline run."""

    scorecard: MatrixScorecard
    validation_results: Dict[Tuple[str, str, str, int], ValidationResult]
    acceptance_report: AcceptanceReport
    report_path: Optional[Path] = None


class TrainingPipeline:
    """Master orchestrator for Phase 1B/Phase 2 model training, persistence, and acceptance testing."""

    def __init__(
        self,
        storage_manager: Optional[StorageManager] = None,
        climatology_calculator: Optional[ClimatologyCalculator] = None,
        model_registry: Optional[ModelRegistry] = None,
        stations: Optional[Sequence[str]] = None,
        train_start_year: int = 2000,
        train_end_year: int = 2018,
        val_start_year: int = 2019,
        val_end_year: int = 2019,
        l2_lambda_d: float = 1e-3,
        report_dir: Union[str, Path] = "reports",
        verify_gates: bool = True,
        random_seed: Optional[int] = 42,
    ):
        self.storage_manager = storage_manager or StorageManager()
        self.climatology_calculator = climatology_calculator or ClimatologyCalculator(
            train_start_year=train_start_year,
            train_end_year=train_end_year,
        )
        self.model_registry = model_registry or ModelRegistry(base_dir="data/models")
        self.stations = list(stations if stations is not None else ACTIVE_10_STATIONS)
        self.train_start_year = train_start_year
        self.train_end_year = train_end_year
        self.val_start_year = val_start_year
        self.val_end_year = val_end_year
        self.l2_lambda_d = l2_lambda_d
        self.report_dir = Path(report_dir)
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.verify_gates = verify_gates
        self.random_seed = random_seed

        self.partitioner = DatasetPartitioner()
        self.interpolator = LeadTimeInterpolator()
        self.report_generator = ReportGenerator()

    def run(self) -> PipelineResult:
        """Execute full training and validation lifecycle with modular step runners."""
        logger.info("=== Training Pipeline Started ===")
        self._ensure_climatology_fitted()

        # Step 1: Matrix batch training & persistence
        scorecard = self._train_matrix_models()
        self.model_registry.save_scorecard(scorecard, build_dense_grid=True)
        self.model_registry.save_scorecard_json(
            scorecard=scorecard,
            train_start_year=self.train_start_year,
            train_end_year=self.train_end_year,
        )

        # Step 2: Out-of-sample validation on holdout period
        val_engine, val_results, val_dict = self._run_out_of_sample_validation()

        # Step 3: Gate 2 virtual holdout evaluation (30h)
        crps_virt, crps_real, pit_virt = self._evaluate_virtual_holdout_30h(val_engine)

        # Step 4: Triple acceptance gate report generation
        acceptance_report, report_path = self._generate_acceptance_report(
            val_results_dict=val_dict,
            crps_virt_30h=crps_virt,
            crps_real_30h=crps_real,
            pit_virt_30h=pit_virt,
        )

        return PipelineResult(
            scorecard=scorecard,
            validation_results=val_results,
            acceptance_report=acceptance_report,
            report_path=report_path,
        )

    def _ensure_climatology_fitted(self) -> None:
        """Fit climatology calculator if not already fit."""
        if hasattr(self.climatology_calculator, "is_fitted") and not self.climatology_calculator.is_fitted:
            logger.info("Fitting ClimatologyCalculator on historical database...")
            self.climatology_calculator.fit_from_db(station_ids=self.stations)

    def _train_matrix_models(self) -> MatrixScorecard:
        """Execute batch training of all 40 matrix subsets."""
        logger.info("Batch training 40-model matrix via MatrixTrainer...")
        trainer = MatrixTrainer(
            storage_manager=self.storage_manager,
            climatology_calculator=self.climatology_calculator,
            stations=self.stations,
            train_start_year=self.train_start_year,
            train_end_year=self.train_end_year,
            l2_lambda_d=self.l2_lambda_d,
            random_seed=self.random_seed,
        )
        return trainer.train_all()

    def _run_out_of_sample_validation(
        self,
    ) -> Tuple[ValidationEngine, Dict[Tuple[str, str, str, int], ValidationResult], Dict[str, ValidationResult]]:
        """Run validation engine across all matrix partitions."""
        logger.info("Running out-of-sample validation on [%d, %d]...", self.val_start_year, self.val_end_year)
        val_engine = ValidationEngine(
            storage_manager=self.storage_manager,
            climatology_calculator=self.climatology_calculator,
            model_registry=self.model_registry,
            train_start_year=self.train_start_year,
            train_end_year=self.train_end_year,
            val_start_year=self.val_start_year,
            val_end_year=self.val_end_year,
        )

        val_results: Dict[Tuple[str, str, str, int], ValidationResult] = {}
        val_dict: Dict[str, ValidationResult] = {}

        for (station, season, target_type, lead_bucket) in self.partitioner.get_all_matrix_keys(stations=self.stations):
            df_val_full = val_engine.load_val_data(station, target_type, lead_bucket)
            seasonal_splits = self.partitioner.split_by_season(df_val_full, date_col="target_date")
            df_val_season = seasonal_splits[season]

            val_res = val_engine.evaluate_slice(
                station_id=station,
                target_type=target_type,
                lead_hours=lead_bucket,
                df_val=df_val_season,
            )
            val_results[(station, season, target_type, lead_bucket)] = val_res
            val_dict[f"{station}_{season}_{target_type}_{lead_bucket}h"] = val_res

        return val_engine, val_results, val_dict

    def _evaluate_virtual_holdout_30h(
        self,
        val_engine: ValidationEngine,
    ) -> Tuple[float, float, np.ndarray]:
        """Evaluate 30h virtual holdout interpolation accuracy and PIT (Gate 2)."""
        st_ref = self.stations[0]
        df_30_val = val_engine.load_val_data(st_ref, "max", 30)

        # Retrieve anchor models and interpolate virtual 30h model via LeadTimeInterpolator
        m6 = self.model_registry.get_model(st_ref, target_date="2019-01-01", target_type="max", lead_hours=6)
        m54 = self.model_registry.get_model(st_ref, target_date="2019-01-01", target_type="max", lead_hours=54)
        m30_real = self.model_registry.get_model(st_ref, target_date="2019-01-01", target_type="max", lead_hours=30)
        m30_virt = self.interpolator.get_model_at_lead("max", 30, {6: m6, 54: m54})

        clim_vars_30 = np.array([
            self.climatology_calculator.get_climatology_variance(st_ref, "max", d)
            for d in df_30_val["target_date"]
        ])
        v_mu, v_sig = m30_virt.compute_params(
            df_30_val["ensemble_mean"].values,
            df_30_val["ensemble_variance"].values,
            clim_vars_30,
        )
        r_mu, r_sig = m30_real.compute_params(
            df_30_val["ensemble_mean"].values,
            df_30_val["ensemble_variance"].values,
            clim_vars_30,
        )

        obs = df_30_val["observed_temp"].values
        crps_virt = float(np.mean(gaussian_crps(obs, v_mu, v_sig)))
        crps_real = float(np.mean(gaussian_crps(obs, r_mu, r_sig)))

        z_virt = (obs - v_mu) / np.maximum(1e-8, v_sig)
        pit_virt = stats.norm.cdf(z_virt)

        return crps_virt, crps_real, pit_virt

    def _generate_acceptance_report(
        self,
        val_results_dict: Dict[str, ValidationResult],
        crps_virt_30h: float,
        crps_real_30h: float,
        pit_virt_30h: np.ndarray,
    ) -> Tuple[AcceptanceReport, Path]:
        """Generate and save Triple Acceptance Report markdown."""
        report = self.report_generator.generate_report(
            val_results=val_results_dict,
            crps_virt_30h=crps_virt_30h,
            crps_real_30h=crps_real_30h,
            pit_virt_30h=pit_virt_30h,
        )
        report_path = self.report_dir / "phase1b_acceptance_report.md"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report.to_markdown())
        logger.info("Acceptance report saved to %s", report_path)
        return report, report_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for training pipeline execution and parameter persistence."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m src.modeling.pipeline",
        description="End-to-end training pipeline and parameter persistence for Gaussian EMOS models.",
    )
    parser.add_argument(
        "--stations",
        nargs="+",
        default=list(ACTIVE_10_STATIONS),
        help="List of station IDs to calibrate (default: Active 10 trading universe).",
    )
    parser.add_argument(
        "--train-start-year",
        type=int,
        default=2000,
        help="Start year for training window (default: 2000).",
    )
    parser.add_argument(
        "--train-end-year",
        type=int,
        default=2018,
        help="End year for training window (default: 2018).",
    )
    parser.add_argument(
        "--val-start-year",
        type=int,
        default=2019,
        help="Start year for validation window (default: 2019).",
    )
    parser.add_argument(
        "--val-end-year",
        type=int,
        default=2019,
        help="End year for validation window (default: 2019).",
    )
    parser.add_argument(
        "--model-dir",
        type=str,
        default="data/models",
        help="Directory to persist calibrated models and manifest (default: data/models).",
    )
    parser.add_argument(
        "--report-dir",
        type=str,
        default="reports",
        help="Directory to write acceptance reports (default: reports).",
    )
    parser.add_argument(
        "--verify-manifest",
        action="store_true",
        help="Run fail-closed SHA256 manifest verification after persistence.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned pipeline configuration without executing training.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for optimization reproducibility (default: 42).",
    )

    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    if args.dry_run:
        print("=== Dry Run Mode: Training Pipeline Configuration ===")
        print(f"Stations ({len(args.stations)}): {args.stations}")
        print(f"Training Period: {args.train_start_year}-{args.train_end_year}")
        print(f"Validation Period: {args.val_start_year}-{args.val_end_year}")
        print(f"Model Output Directory: {args.model_dir}")
        print(f"Report Output Directory: {args.report_dir}")
        print(f"Verify Manifest: {args.verify_manifest}")
        return 0

    registry = ModelRegistry(base_dir=args.model_dir)
    pipeline = TrainingPipeline(
        model_registry=registry,
        stations=args.stations,
        train_start_year=args.train_start_year,
        train_end_year=args.train_end_year,
        val_start_year=args.val_start_year,
        val_end_year=args.val_end_year,
        report_dir=args.report_dir,
        random_seed=args.seed,
    )

    result = pipeline.run()

    if args.verify_manifest:
        logger.info("Executing fail-closed manifest verification on %s...", args.model_dir)
        registry.verify_and_load_manifest()
        logger.info("Manifest verification succeeded.")

    logger.info("Pipeline run completed successfully. Models trained: %d", result.scorecard.total_trained)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())

