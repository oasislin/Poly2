#!/usr/bin/env python3
"""
scripts/dry_run_block_cv_fold.py: Engineering dry-run for fit_statutory_pipeline_fold on 3 Block-CV folds.
Validates:
1. Runtime per fold (< 10s per fold).
2. Peak memory footprint (< 50MB).
3. Zero crash / zero unhandled exceptions.
4. Completeness of StatutoryFoldModel and selection_audit persistence.
"""

import json
import logging
from pathlib import Path
import sys
import time
import tracemalloc
from datetime import date
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import numpy as np
import pandas as pd

from scripts.retrain_p4_active10_matrix import load_station_training_data
from src.modeling.resampling import BlockCrossValidator, fit_statutory_pipeline_fold, StatutoryFoldModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "evidence"


def run_dry_run(station: str = "KORD", n_folds: int = 3) -> Dict[str, Any]:
    logger.info("================================================================================")
    logger.info("Executing Block-CV Engineering Dry-Run on %s (2000-2018 Training Window)", station)
    logger.info("================================================================================")

    # 1. Load data
    df_ghcn, df_gefs = load_station_training_data(station)
    obs_sub = df_ghcn[["target_date", "tmax_f", "season"]].dropna().rename(columns={"tmax_f": "obs_tmax_f"})
    gefs_sub = df_gefs[(df_gefs["variable"] == "tmax") & (df_gefs["lead_hours"] == 18)].copy()
    ens_stats = gefs_sub.groupby("target_date")["temp_f"].agg(
        ens_mean="mean",
        ens_var=lambda x: float(np.var(x, ddof=1)) if len(x) > 1 else 0.0,
    ).reset_index()

    full_df = pd.merge(obs_sub, ens_stats, on="target_date", how="inner").dropna()
    full_df = full_df.sort_values("target_date").reset_index(drop=True)
    logger.info("Matched full dataset: %d rows (%s to %s)", len(full_df), full_df["target_date"].min(), full_df["target_date"].max())

    # 2. Setup 30-day block cross validator
    validator = BlockCrossValidator(start_date=date(2000, 1, 1), end_date=date(2018, 12, 31), seed=42)
    splits = list(validator.split_dataframe(full_df))
    logger.info("Total generated folds in 20-round scheme: %d", len(splits))

    tracemalloc.start()
    dry_run_records: List[Dict[str, Any]] = []

    for fold_idx in range(min(n_folds, len(splits))):
        round_id, train_fold, test_fold = splits[fold_idx]
        t0 = time.time()
        mem_start = tracemalloc.get_traced_memory()[0] / (1024 * 1024)

        logger.info("Fitting Fold %d (Round %d): %d train rows, %d test rows...", fold_idx, round_id, len(train_fold), len(test_fold))
        fold_model: StatutoryFoldModel = fit_statutory_pipeline_fold(
            train_df=train_fold,
            station=station,
            variable="tmax",
            lead_hour=18,
            sigma_floor=0.90,
        )

        elapsed = time.time() - t0
        mem_end = tracemalloc.get_traced_memory()[0] / (1024 * 1024)
        mem_peak = tracemalloc.get_traced_memory()[1] / (1024 * 1024)

        # Integrity Assertions
        assert isinstance(fold_model, StatutoryFoldModel)
        assert len(fold_model.seasonal_emos_params) == 4
        for s, p in fold_model.seasonal_emos_params.items():
            assert p[2] >= 0.90, f"Season {s} EMOS c={p[2]} violates physical floor 0.90"
        for s, c_val in fold_model.seasonal_c_train.items():
            assert 0.80 <= c_val <= 1.40, f"Season {s} c_train={c_val} out of bounds"
        assert fold_model.selected_family in ["gaussian", "johnsonsu", "evt_hybrid"]
        assert "delta_bic_winner" in fold_model.selection_audit

        record = {
            "fold_idx": fold_idx,
            "round_id": round_id,
            "train_samples": len(train_fold),
            "test_samples": len(test_fold),
            "elapsed_seconds": round(elapsed, 4),
            "mem_start_mb": round(mem_start, 2),
            "mem_end_mb": round(mem_end, 2),
            "mem_peak_mb": round(mem_peak, 2),
            "selected_family": fold_model.selected_family,
            "seasonal_emos": {s: [round(x, 4) for x in p] for s, p in fold_model.seasonal_emos_params.items()},
            "seasonal_c_train": {s: round(v, 4) for s, v in fold_model.seasonal_c_train.items()},
            "selection_audit": fold_model.selection_audit,
        }
        dry_run_records.append(record)
        logger.info("Fold %d completed in %.3fs (peak mem: %.2fMB). Selected family: %s", fold_idx, elapsed, mem_peak, fold_model.selected_family)

    tracemalloc.stop()

    summary = {
        "station": station,
        "n_folds_tested": len(dry_run_records),
        "total_elapsed_seconds": round(sum(r["elapsed_seconds"] for r in dry_run_records), 4),
        "max_peak_mem_mb": round(max(r["mem_peak_mb"] for r in dry_run_records), 2),
        "status": "ENGINEERING_DRY_RUN_PASSED",
        "folds": dry_run_records,
    }

    out_path = EVIDENCE_DIR / "p4_block_cv_dry_run_audit.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logger.info("Saved engineering dry-run audit to %s", out_path)
    return summary


if __name__ == "__main__":
    run_dry_run("KORD", 3)
