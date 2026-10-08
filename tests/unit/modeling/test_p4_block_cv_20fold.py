"""
tests/unit/modeling/test_p4_block_cv_20fold.py: Formal 20-Round 30-Day Block-CV Execution & Gate Monitoring.

Specification: P4-PHASE2-BLOCKCV-20FOLD
Execution Discipline:
1. Python 3.13.5 + pytest 8.3.4 with mandatory header.
2. Strict Tripwire / Stop Rule: If any fold GateReport is failed, stop immediately and report.
3. 2000-2018 window with seed=20260923.
"""

from datetime import date
import json
from pathlib import Path
import time
import numpy as np
import pandas as pd
import pytest

from scripts.retrain_p4_active10_matrix import load_station_training_data
from src.modeling.resampling import (
    BlockCrossValidator,
    DEFAULT_SEED,
    fit_statutory_pipeline_fold,
    run_block_cv,
    StatutoryFoldModel,
)
from src.verification.p5_gate import GateReport

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
EVIDENCE_DIR = REPO_ROOT / "evidence"


def test_execute_p4_block_cv_with_tripwire():
    """Execute formal Block-CV with immediate halt on GateReport failure."""
    station = "KORD"
    df_ghcn, df_gefs = load_station_training_data(station)

    obs_sub = df_ghcn[["target_date", "tmax_f", "season"]].dropna().rename(columns={"tmax_f": "obs_tmax_f"})
    gefs_sub = df_gefs[(df_gefs["variable"] == "tmax") & (df_gefs["lead_hours"] == 18)].copy()
    ens_stats = gefs_sub.groupby("target_date")["temp_f"].agg(
        ens_mean="mean",
        ens_var=lambda x: float(np.var(x, ddof=1)) if len(x) > 1 else 0.0,
    ).reset_index()

    full_df = pd.merge(obs_sub, ens_stats, on="target_date", how="inner").dropna()
    full_df = full_df.sort_values("target_date").reset_index(drop=True)

    cv = BlockCrossValidator(n_rounds=20, holdout_ratio=0.10, seed=DEFAULT_SEED)
    splits = cv.split_blocks()

    print("\n=================== P4 Formal Block-CV Execution ===================")
    print(f"Station: {station} | Date range: {full_df['target_date'].min()} to {full_df['target_date'].max()}")
    print(f"Total samples: {len(full_df)} | Total splits: {len(splits)}")

    halted = False
    halt_reason = None
    executed_folds = []

    for round_id, split in enumerate(splits):
        val_dates = sorted(list(split.val_dates))
        val_start = val_dates[0]
        val_end = val_dates[-1]

        val_mask = full_df["target_date"].isin(split.val_dates)
        train_mask = full_df["target_date"].isin(split.train_dates)
        train_df = full_df[train_mask].copy().reset_index(drop=True)
        val_df = full_df[val_mask].copy().reset_index(drop=True)

        t0 = time.time()
        # 1. In-loop refit
        model = fit_statutory_pipeline_fold(
            train_df=train_df,
            station=station,
            variable="tmax",
            lead_hour=18,
            sigma_floor=0.90,
        )

        # 2. Evaluation & Prediction Generation
        val_work = val_df.copy().reset_index(drop=True)
        mu_pred = np.zeros(len(val_work))
        sig_pred = np.zeros(len(val_work))

        for idx, row in val_work.iterrows():
            s = row["season"]
            a, b, c, d = model.seasonal_emos_params.get(s, (0.0, 1.0, 0.90, 0.1))
            c_factor = model.seasonal_c_train.get(s, 1.0)
            m = a + b * row["ens_mean"]
            v = (c ** 2) + (d ** 2) * row["ens_var"]
            mu_pred[idx] = m
            sig_pred[idx] = max(0.90, np.sqrt(max(0.90 ** 2, v)) * c_factor)

        pred_df = pd.DataFrame({
            "target_date": val_work["target_date"],
            "obs": val_work["obs_tmax_f"].values,
            "mu": mu_pred,
            "sigma": sig_pred,
        })
        mae = float(np.mean(np.abs(pred_df["obs"] - pred_df["mu"])))

        # 3. Direct invocation of single-round cv to trigger formal artifacts and GateReport
        single_res = run_block_cv(
            df=pd.concat([train_df, val_df]).sort_values("target_date").reset_index(drop=True),
            fit_fn=lambda tr: model,
            eval_fn=lambda m, v: {"mae": mae, "predictions": pred_df},
            date_col="target_date",
            n_rounds=1,
            holdout_ratio=0.10,
            seed=DEFAULT_SEED,
            export_evidence=True,
            evidence_dir=EVIDENCE_DIR,
        )

        fold_entry = single_res["round_results"][0]
        gate_rep: GateReport = fold_entry["gate_report"]
        elapsed = time.time() - t0

        record = {
            "round_id": round_id,
            "val_start": str(val_start),
            "val_end": str(val_end),
            "train_samples": len(train_df),
            "val_samples": len(val_df),
            "mae": mae,
            "elapsed_seconds": elapsed,
            "gate_passed": gate_rep.passed,
            "weighted_ece": gate_rep.weighted_ece,
            "bss": gate_rep.bss,
            "s_ladder": gate_rep.s_ladder_status,
            "error_message": gate_rep.error_message,
        }
        executed_folds.append(record)

        print(
            f"fold_{round_id:02d} | {val_start} ~ {val_end} | "
            f"GateReport passed: {gate_rep.passed} | "
            f"ECE: {gate_rep.weighted_ece:.4f} | "
            f"Status: {'passed' if gate_rep.passed else 'failed'}"
        )

        # Enforce Tripwire / Stop Rule
        if not gate_rep.passed:
            halted = True
            halt_reason = f"fold_{round_id:02d} GateReport failed: {gate_rep.error_message} (ECE={gate_rep.weighted_ece:.4f})"
            print(f"\n[STOP-RULE TRIGGERED] Immediately halting execution at fold_{round_id:02d}!")
            print(f"Reason: {halt_reason}")
            break

    # Persist progress report
    progress_file = EVIDENCE_DIR / "p4_block_cv_execution_progress.json"
    with open(progress_file, "w", encoding="utf-8") as f:
        json.dump({
            "station": station,
            "seed": DEFAULT_SEED,
            "total_planned_rounds": 20,
            "executed_rounds_count": len(executed_folds),
            "halted": halted,
            "halt_reason": halt_reason,
            "folds": executed_folds,
        }, f, indent=2)

    if halted:
        # Halt execution as per statutory tripwire
        assert not halted, f"Execution halted by stop rule: {halt_reason}"
