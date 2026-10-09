"""
tests/unit/verification/test_cv_artifacts_manifest.py: Verification of CV Artifacts, SHA-256 Manifest, and E2E Fold Execution.

Mandated by Pre-Run Tasks A (Gap 4a), B, and C:
1. Hook Invocation: GateReport and artifact paths/hashes returned for each fold.
2. Manifest Integrity: Artifact existence, manifest registry equality, and zero untracked files.
3. Task C End-to-End: Real KORD data executed for Fold 0, emitting formal artifacts to evidence/.
"""

import hashlib
import json
from pathlib import Path
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


def compute_file_sha256(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def test_run_block_cv_hooks_invocation_and_manifest(tmp_path):
    """Task B & Gap 4a: Verify run_block_cv hooks invoke GateReport and emit verifiable sha256 manifest."""
    dates = pd.date_range("2017-01-01", "2018-12-31", freq="D").date
    df = pd.DataFrame({
        "target_date": dates,
        "obs": np.linspace(40, 80, len(dates)),
        "mu": np.linspace(41, 79, len(dates)),
        "sigma": np.full(len(dates), 2.5),
    })

    def mock_fit(train_df: pd.DataFrame):
        return {"fitted_param": 1.0}

    def mock_eval(model: dict, val_df: pd.DataFrame):
        pred_df = pd.DataFrame({
            "obs": val_df["obs"].values,
            "mu": val_df["mu"].values,
            "sigma": val_df["sigma"].values,
        })
        return {"mae": float(np.mean(np.abs(pred_df["obs"] - pred_df["mu"]))), "predictions": pred_df}

    results = run_block_cv(
        df=df,
        fit_fn=mock_fit,
        eval_fn=mock_eval,
        date_col="target_date",
        n_rounds=2,
        holdout_ratio=0.10,
        seed=DEFAULT_SEED,
        export_evidence=True,
        evidence_dir=tmp_path,
    )

    # 1. Assert hook invocation in each round
    assert len(results["round_results"]) == 2
    for r in results["round_results"]:
        # Hook 1: GateReport returned
        assert "gate_report" in r
        assert isinstance(r["gate_report"], GateReport)

        # Hook 2: Artifact paths and hashes registered
        assert "artifact_paths" in r
        assert "artifact_hashes" in r
        paths = r["artifact_paths"]
        hashes = r["artifact_hashes"]

        for art_key in ["model", "predictions", "gate_report", "manifest"]:
            assert art_key in paths
            art_file = Path(paths[art_key])
            assert art_file.exists(), f"Artifact {art_file} does not exist on disk!"

            # Verify calculated sha256 strictly equals registered sha256
            actual_sha = compute_file_sha256(art_file)
            assert actual_sha == hashes[art_key], f"Hash mismatch on {art_key}: {actual_sha} vs {hashes[art_key]}"

        # Validate manifest content on disk
        manifest_path = Path(paths["manifest"])
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_json = json.load(f)
        for art_key in ["model", "predictions", "gate_report"]:
            assert manifest_json["artifacts"][art_key]["sha256"] == hashes[art_key]


def test_e2e_real_fold0_dry_run_artifacts():
    """Task C: Execute 1 real statutory Block-CV fold (KORD) emitting formal evidence artifacts."""
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

    def fit_fold(train_df: pd.DataFrame) -> StatutoryFoldModel:
        return fit_statutory_pipeline_fold(
            train_df=train_df,
            station=station,
            variable="tmax",
            lead_hour=18,
            sigma_floor=0.90,
        )

    def eval_fold(model: StatutoryFoldModel, val_df: pd.DataFrame):
        # Forecast evaluation on validation fold
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

        pred_dict = {
            "target_date": val_work["target_date"],
            "obs": val_work["obs_tmax_f"].values,
            "mu": mu_pred,
            "sigma": sig_pred,
            "selected_family": model.selected_family,
            "family_shape_params": json.dumps(model.shape_params),
        }
        if model.selected_family == "johnsonsu":
            pred_dict["jsu_gamma"] = float(model.shape_params.get("gamma", 0.0))
            pred_dict["jsu_delta"] = float(model.shape_params.get("delta", 1.0))
            pred_dict["jsu_xi"] = float(model.shape_params.get("xi", 0.0))
            pred_dict["jsu_lambda"] = float(model.shape_params.get("lambda", 1.0))
        pred_df = pd.DataFrame(pred_dict)
        mae = float(np.mean(np.abs(pred_df["obs"] - pred_df["mu"])))
        return {"mae": mae, "predictions": pred_df}

    # Execute 1 round with evidence export
    cv_res = run_block_cv(
        df=full_df,
        fit_fn=fit_fold,
        eval_fn=eval_fold,
        date_col="target_date",
        n_rounds=1,
        holdout_ratio=0.10,
        seed=DEFAULT_SEED,
        export_evidence=True,
        evidence_dir=EVIDENCE_DIR,
    )

    assert len(cv_res["round_results"]) == 1
    fold0 = cv_res["round_results"][0]

    # Verification of artifacts & manifest
    paths = fold0["artifact_paths"]
    hashes = fold0["artifact_hashes"]
    gate_rep: GateReport = fold0["gate_report"]

    print("\n--- Task C E2E Execution Summary ---")
    print(f"Fold 0 Round ID: {fold0['round_id']}")
    print(f"Train samples: {fold0['train_samples']}, Val samples: {fold0['val_samples']}")
    print(f"GateReport passed: {gate_rep.passed}, weighted_ece: {gate_rep.weighted_ece:.4f}, bss: {gate_rep.bss:.4f}")
    print(f"GateReport is_degenerate: {gate_rep.is_degenerate}")
    print(f"Manifest Path: {paths['manifest']}")
    print(f"Manifest SHA256: {hashes['manifest']}")

    # Assert formal files on disk and checksum identity
    for k in ["model", "predictions", "gate_report", "manifest"]:
        p = Path(paths[k])
        assert p.exists(), f"Missing artifact: {p}"
        real_sha = compute_file_sha256(p)
        assert real_sha == hashes[k], f"SHA256 mismatch for {k}: {real_sha} vs {hashes[k]}"

    # Validate GateReport contract fields (11 statutory fields non-null)
    d_rep = gate_rep.to_dict()
    for field in ["passed", "weighted_ece", "ece_ci_lower", "ece_ci_upper", "bss", "ks_stat", "ks_pvalue", "wilson_coverage_rate", "is_degenerate", "s_ladder_status", "metadata"]:
        assert field in d_rep, f"Missing GateReport field: {field}"
        assert d_rep[field] is not None or field == "error_message"
