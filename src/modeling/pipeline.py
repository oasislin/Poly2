#!/usr/bin/env python3
"""
TrainingPipeline: End-to-end training, persistence, and acceptance validation orchestrator for Phase 2 Task 01 (Issue #63).

Coordinates:
    1. Climatology baseline & variance floor loading (ADR-0010 verified IEM baseline, 2000-2018 OOS observations)
    2. Active 10 trading universe 200-model matrix batch training (MatrixTrainer)
    3. Dense 6h-spaced grid interpolation & short-lead decay handling (LeadTimeInterpolator)
    4. Standardized model parameter JSON & PKL persistence with manifest.json (ModelRegistry)
    5. Strict time-wall out-of-sample evaluation on 2019 pure holdout dataset (ValidationEngine)
    6. Adaptive Triple Acceptance Gate verification & Markdown report generation (ReportGenerator)
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
from src.modeling.partitioner import DatasetPartitioner, SEASONS
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
    """Master orchestrator for Phase 2 model training, persistence, and Triple Acceptance testing."""

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
        report_dir: Union[str, Path] = "docs/reports",
        report_filename: str = "phase2-task01-model-calibration-acceptance-report.md",
        calib_dataset_dir: Union[str, Path] = Path("data/processed/calib-dataset-v2.0"),
        verify_gates: bool = True,
        random_seed: Optional[int] = 42,
        skip_train: bool = False,
    ):
        self.storage_manager = storage_manager
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
        self.report_filename = report_filename
        self.calib_dataset_dir = Path(calib_dataset_dir)
        self.verify_gates = verify_gates
        self.random_seed = random_seed
        self.skip_train = skip_train

        self.partitioner = DatasetPartitioner()
        self.interpolator = LeadTimeInterpolator()
        self.report_generator = ReportGenerator()

    def run(self) -> PipelineResult:
        """Execute full training and validation lifecycle with modular step runners."""
        logger.info("=== Training Pipeline Started ===")
        self._ensure_climatology_fitted()

        # Step 1: Matrix batch training & persistence
        if not self.skip_train:
            scorecard = self._train_matrix_models()
            self.model_registry.save_scorecard(scorecard, build_dense_grid=True)
            self.model_registry.save_scorecard_json(
                scorecard=scorecard,
                train_start_year=self.train_start_year,
                train_end_year=self.train_end_year,
            )
        else:
            logger.info("Skipping model training as requested; loading inventory from registry...")
            scorecard = MatrixScorecard(models={})

        # Step 2: Out-of-sample validation on 2019 holdout period
        val_engine, val_results, val_dict = self._run_out_of_sample_validation()

        # Step 3: Gate 2 adaptive virtual holdout evaluation
        crps_virt, crps_real, pit_virt, gate2_details = self._evaluate_virtual_holdout(val_engine)

        # Step 4: Triple acceptance gate report generation
        acceptance_report, report_path = self._generate_acceptance_report(
            val_results_dict=val_dict,
            crps_virt=crps_virt,
            crps_real=crps_real,
            pit_virt=pit_virt,
            gate2_details=gate2_details,
            scorecard=scorecard,
        )

        if self.verify_gates and not acceptance_report.overall_passed:
            logger.error("Triple Acceptance Gates failed on 2019 holdout set!")

        return PipelineResult(
            scorecard=scorecard,
            validation_results=val_results,
            acceptance_report=acceptance_report,
            report_path=report_path,
        )

    def _ensure_climatology_fitted(self) -> None:
        """Fit climatology calculator if not already fit, honoring ADR-0010 climate floor."""
        if hasattr(self.climatology_calculator, "is_fitted") and not self.climatology_calculator.is_fitted:
            floor_dir = self.calib_dataset_dir / "climate_floor"
            if floor_dir.exists() and hasattr(self.climatology_calculator, "load_from_floor_parquet_dir"):
                logger.info("Loading ClimatologyCalculator from climate floor parquet dir: %s", floor_dir)
                self.climatology_calculator.load_from_floor_parquet_dir(floor_dir)
            elif hasattr(self.climatology_calculator, "fit_from_db"):
                logger.info("Fitting ClimatologyCalculator on historical database...")
                self.climatology_calculator.fit_from_db(station_ids=self.stations)

    def _train_matrix_models(self) -> MatrixScorecard:
        """Execute batch training of all matrix subsets across configured stations."""
        logger.info("Batch training EMOS matrix models across %d stations...", len(self.stations))
        trainer = MatrixTrainer(
            storage_manager=self.storage_manager,
            climatology_calculator=self.climatology_calculator,
            stations=self.stations,
            train_start_year=self.train_start_year,
            train_end_year=self.train_end_year,
            l2_lambda_d=self.l2_lambda_d,
            random_seed=self.random_seed,
            calib_dataset_dir=self.calib_dataset_dir,
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
            calib_dataset_dir=self.calib_dataset_dir,
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
                season=season,
            )
            val_results[(station, season, target_type, lead_bucket)] = val_res
            val_dict[f"{station}_{season}_{target_type}_{lead_bucket}h"] = val_res

        return val_engine, val_results, val_dict

    def _evaluate_virtual_holdout(
        self,
        val_engine: ValidationEngine,
    ) -> Tuple[float, float, np.ndarray, Dict[str, Any]]:
        """Evaluate adaptive virtual holdout interpolation accuracy and PIT across US timezones (Gate 2)."""
        all_crps_virt: List[float] = []
        all_crps_real: List[float] = []
        all_pit_virt: List[float] = []
        gate2_details: Dict[str, Any] = {}

        for st in self.stations:
            for season in SEASONS:
                nodes = sorted(self.partitioner.get_station_lead_nodes(st, season=season, target_type="max"))
                if len(nodes) < 3:
                    continue

                l0, l_mid, l1 = nodes[0], nodes[1], nodes[2]
                df_val_full = val_engine.load_val_data(st, "max", l_mid)
                seasonal_splits = self.partitioner.split_by_season(df_val_full, date_col="target_date")
                df_slice = seasonal_splits.get(season, pd.DataFrame())

                if df_slice.empty:
                    continue

                ref_date = df_slice["target_date"].iloc[0]
                m0 = self.model_registry.get_model(st, target_date=ref_date, target_type="max", lead_hours=l0)
                m1 = self.model_registry.get_model(st, target_date=ref_date, target_type="max", lead_hours=l1)
                m_real = self.model_registry.get_model(st, target_date=ref_date, target_type="max", lead_hours=l_mid)
                m_virt = self.interpolator.get_model_at_lead("max", l_mid, {l0: m0, l1: m1})

                clim_vars = np.array([
                    self.climatology_calculator.get_climatology_variance(st, "max", d)
                    for d in df_slice["target_date"]
                ])

                v_mu, v_sig = m_virt.compute_params(
                    df_slice["ensemble_mean"].values,
                    df_slice["ensemble_variance"].values,
                    clim_vars,
                )
                r_mu, r_sig = m_real.compute_params(
                    df_slice["ensemble_mean"].values,
                    df_slice["ensemble_variance"].values,
                    clim_vars,
                )

                obs = df_slice["observed_temp"].values
                crps_v = gaussian_crps(obs, v_mu, v_sig)
                crps_r = gaussian_crps(obs, r_mu, r_sig)

                z_v = (obs - v_mu) / np.maximum(1e-8, v_sig)
                pit_v = stats.norm.cdf(z_v)

                all_crps_virt.extend(crps_v)
                all_crps_real.extend(crps_r)
                all_pit_virt.extend(pit_v)

                mean_v = float(np.mean(crps_v))
                mean_r = float(np.mean(crps_r))
                ratio = float(mean_v / mean_r) if mean_r > 0 else 1.0

                gate2_details[f"{st}_{season}_max_{l_mid}h"] = {
                    "lead_hours": l_mid,
                    "crps_virt": mean_v,
                    "crps_real": mean_r,
                    "ratio": ratio,
                    "passed": ratio <= (1.0 + self.report_generator.max_interp_degradation),
                }

        crps_virt_overall = float(np.mean(all_crps_virt)) if all_crps_virt else 1.0
        crps_real_overall = float(np.mean(all_crps_real)) if all_crps_real else 1.0
        pit_virt_overall = np.array(all_pit_virt) if all_pit_virt else np.array([])

        return crps_virt_overall, crps_real_overall, pit_virt_overall, gate2_details

    def _evaluate_virtual_holdout_30h(
        self,
        val_engine: ValidationEngine,
    ) -> Tuple[float, float, np.ndarray]:
        """Backward-compatible helper returning 30h or aggregate virtual holdout metrics."""
        crps_v, crps_r, pit_v, _ = self._evaluate_virtual_holdout(val_engine)
        return crps_v, crps_r, pit_v

    def _generate_acceptance_report(
        self,
        val_results_dict: Dict[str, ValidationResult],
        crps_virt: float,
        crps_real: float,
        pit_virt: np.ndarray,
        gate2_details: Optional[Dict[str, Any]] = None,
        scorecard: Optional[MatrixScorecard] = None,
    ) -> Tuple[AcceptanceReport, Path]:
        """Generate and save Triple Acceptance Report markdown to destination."""
        report = self.report_generator.generate_report(
            val_results=val_results_dict,
            crps_virt=crps_virt,
            crps_real=crps_real,
            pit_virt=pit_virt,
            gate2_details=gate2_details,
            scorecard=scorecard,
            total_models_evaluated=len(val_results_dict),
        )

        report_path = self.report_dir / self.report_filename
        markdown_content = report.to_markdown()
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info("Acceptance report saved to %s", report_path)

        # Backward compatibility for existing tests checking phase1b_acceptance_report.md
        legacy_path = self.report_dir / "phase1b_acceptance_report.md"
        if legacy_path != report_path:
            try:
                with open(legacy_path, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
            except Exception:
                pass

        return report, report_path


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point for training pipeline execution, manifest verification, and acceptance evaluation."""
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
        default="docs/reports",
        help="Directory to write acceptance reports (default: docs/reports).",
    )
    parser.add_argument(
        "--report-filename",
        type=str,
        default="phase2-task01-model-calibration-acceptance-report.md",
        help="Filename for acceptance report markdown (default: phase2-task01-model-calibration-acceptance-report.md).",
    )
    parser.add_argument(
        "--skip-train",
        action="store_true",
        help="Skip model training and evaluate existing persisted models.",
    )
    parser.add_argument(
        "--verify-manifest",
        action="store_true",
        help="Run fail-closed SHA256 manifest verification after persistence.",
    )
    parser.add_argument(
        "--verify-gates",
        action="store_true",
        default=False,
        help="Enforce fail-closed gate assertion (default: False).",
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
        print(f"Report Output Directory: {args.report_dir}/{args.report_filename}")
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
        report_filename=args.report_filename,
        verify_gates=args.verify_gates,
        random_seed=args.seed,
        skip_train=args.skip_train,
    )

    result = pipeline.run()

    if args.verify_manifest:
        logger.info("Executing fail-closed manifest verification on %s...", args.model_dir)
        registry.verify_and_load_manifest()
        logger.info("Manifest verification succeeded.")

    if args.verify_gates and not result.acceptance_report.overall_passed:
        logger.error("Triple Acceptance Gates failed! Pipeline returning exit code 1.")
        return 1

    logger.info("Pipeline run completed successfully. Models evaluated: %d", len(result.validation_results))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
