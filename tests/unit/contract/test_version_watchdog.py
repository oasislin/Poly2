"""
Unit tests for Physical Model Version Watchdog (Ticket 02 / Phase 2 Task 08).

Validates ADR-0019 §二.6 specifications:
- Fail-closed startup-time verification of physical model binaries and manifest.json.
- Full 22 statutory grid cell coverage check.
- 6h lead WARN-only skipping (non-blocking).
- Canonical manifest SHA256 computation and contract anchor verification.
- Defense-in-depth: production bypass rejection with SecurityViolationError.
- Controlled test bypass in non-production with CRITICAL logging.
- Uses strictly isolated tmp_path fixtures (never touches real data/models/).
"""

import hashlib
import json
import logging
from pathlib import Path
import pickle
from typing import Dict, List, Optional, Tuple

import pytest

from src.contract.parameter_contract import (
    AUTHORIZED_LEAD_HOURS,
    AUTHORIZED_STATIONS,
    TOTAL_AUTHORIZED_CELLS,
    CellCalibrationRecord,
    PhysicalParamContract,
)
from src.contract.version_watchdog import (
    AUTHORIZED_LEADS_FOR_GUARD,
    CONTRACT_VERSION,
    ContractGuardrailError,
    ContractVersionWatchdog,
    ManifestIntegrityError,
    PickleCorruptionError,
    SecurityViolationError,
    StaleModelParametersError,
    WatchdogVerificationReport,
)


def _make_dummy_cell_record(station: str, lead: int) -> CellCalibrationRecord:
    """Helper to generate a valid dummy calibration record."""
    return CellCalibrationRecord(
        station=station,
        lead_hours=lead,
        variable="tmax",
        s_oos=1.0,
        fstd_lo=0.8,
        fstd_hi=1.2,
        fstd_in=True,
        ece_2f=0.01,
        v1_coverage_90=0.90,
        v1_coverage_90_pass=True,
        pit_mean=0.5,
        pit_var=0.0833,
        reject_uniform=False,
        neff=300.0,
        cvm_stat=0.05,
        cvm_p=0.8,
        ece_range=0.008,
    )


def _setup_synthetic_environment(
    tmp_path: Path,
    *,
    tamper_sha_cell: Optional[Tuple[str, int]] = None,
    delete_pkl_cell: Optional[Tuple[str, int]] = None,
    zero_byte_cell: Optional[Tuple[str, int]] = None,
    corrupt_pickle_cell: Optional[Tuple[str, int]] = None,
    omit_cells: Optional[List[Tuple[str, int]]] = None,
    include_6h: bool = False,
    include_other_station: bool = False,
) -> Tuple[Path, PhysicalParamContract]:
    """
    Create a self-contained synthetic directory with manifest.json and .pkl files.
    Returns (manifest_path, contract).
    """
    models_meta: Dict[str, dict] = {}
    model_weights_sha256: Dict[str, str] = {}
    cells_dict: Dict[Tuple[str, int], CellCalibrationRecord] = {}

    omit_set = set(omit_cells or [])

    # Create 22 statutory cells
    for station in AUTHORIZED_STATIONS:
        for lead in AUTHORIZED_LEAD_HOURS:
            if (station, lead) in omit_set:
                continue

            fname = f"{station}_Winter_Max_lead{lead}h.pkl"
            fpath = tmp_path / fname
            cell_key = f"{station}_{lead}h"

            # Prepare content
            if (station, lead) == zero_byte_cell:
                content = b""
            elif (station, lead) == corrupt_pickle_cell:
                content = b"corrupt-non-pickle-content-12345"
            else:
                content = pickle.dumps({"station": station, "lead": lead, "w": 42})

            fpath.write_bytes(content)

            actual_sha = hashlib.sha256(content).hexdigest()

            # Tamper if requested
            declared_sha = (
                "0" * 64 if (station, lead) == tamper_sha_cell else actual_sha
            )

            models_meta[fname] = {
                "station": station,
                "lead_hours": lead,
                "sha256": declared_sha,
            }
            model_weights_sha256[cell_key] = actual_sha
            cells_dict[(station, lead)] = _make_dummy_cell_record(station, lead)

            if (station, lead) == delete_pkl_cell:
                fpath.unlink()

    # Optional 6h lead entry (for T8)
    if include_6h:
        fname_6h = "KORD_Winter_Max_lead6h.pkl"
        fpath_6h = tmp_path / fname_6h
        content_6h = pickle.dumps({"station": "KORD", "lead": 6})
        fpath_6h.write_bytes(content_6h)
        models_meta[fname_6h] = {
            "station": "KORD",
            "lead_hours": 6,
            "sha256": hashlib.sha256(content_6h).hexdigest(),
        }

    # Optional non-authorized station entry
    if include_other_station:
        fname_atl = "KATL_Winter_Max_lead12h.pkl"
        fpath_atl = tmp_path / fname_atl
        content_atl = pickle.dumps({"station": "KATL", "lead": 12})
        fpath_atl.write_bytes(content_atl)
        models_meta[fname_atl] = {
            "station": "KATL",
            "lead_hours": 12,
            "sha256": hashlib.sha256(content_atl).hexdigest(),
        }

    manifest_dict = {
        "manifest_version": "2.2.0-phase",
        "station_universe": list(AUTHORIZED_STATIONS),
        "total_models": len(models_meta),
        "models": models_meta,
    }

    manifest_path = tmp_path / "manifest.json"
    manifest_bytes = json.dumps(
        manifest_dict, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    manifest_path.write_text(json.dumps(manifest_dict, indent=2), encoding="utf-8")

    canonical_manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

    contract = PhysicalParamContract(
        contract_version=CONTRACT_VERSION,
        manifest_sha256=canonical_manifest_sha,
        model_weights_sha256=model_weights_sha256,
        created_at="2026-10-26T00:00:00Z",
        cells=cells_dict,
    )

    return manifest_path, contract


def test_t1_normal_all_pass(tmp_path: Path):
    """T1: 22 statutory cells valid .pkl + matching manifest + matching contract."""
    manifest_path, contract = _setup_synthetic_environment(tmp_path)
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)

    report = watchdog.check()

    assert isinstance(report, WatchdogVerificationReport)
    assert report.is_valid is True
    assert report.verified_cells_count == TOTAL_AUTHORIZED_CELLS  # 22
    assert report.failed_entries == 0
    assert report.skipped_6h_entries == 0
    assert report.bypassed is False
    assert report.checked_at != ""


def test_t2_sha256_tamper_fails_closed(tmp_path: Path):
    """T2: SHA256 tampered in manifest -> StaleModelParametersError with expected & actual."""
    manifest_path, contract = _setup_synthetic_environment(
        tmp_path, tamper_sha_cell=("KORD", 12)
    )
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)

    with pytest.raises(
        StaleModelParametersError, match=r"expected=.*actual="
    ) as exc_info:
        watchdog.check()

    assert "Model SHA256 mismatch for 'KORD_Winter_Max_lead12h.pkl'" in str(
        exc_info.value
    )


def test_t3_missing_pkl_file_raises_corruption(tmp_path: Path):
    """T3: .pkl file missing -> PickleCorruptionError mentioning missing and declared in manifest."""
    manifest_path, contract = _setup_synthetic_environment(
        tmp_path, delete_pkl_cell=("KMIA", 24)
    )
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)

    with pytest.raises(PickleCorruptionError) as exc_info:
        watchdog.check()

    err_msg = str(exc_info.value)
    assert "Missing model parameter file declared in manifest" in err_msg
    assert "KMIA_Winter_Max_lead24h.pkl" in err_msg


def test_t4_zero_byte_pkl_file_raises_corruption(tmp_path: Path):
    """T4: .pkl file is 0 bytes -> PickleCorruptionError mentioning 0 bytes and corrupt."""
    manifest_path, contract = _setup_synthetic_environment(
        tmp_path, zero_byte_cell=("KORD", 36)
    )
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)

    with pytest.raises(PickleCorruptionError) as exc_info:
        watchdog.check()

    err_msg = str(exc_info.value)
    assert "0 bytes corrupt" in err_msg


def test_t5_production_bypass_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """T5: POLY_ENV=production -> SecurityViolationError mentioning production and bypass."""
    manifest_path, contract = _setup_synthetic_environment(tmp_path)
    monkeypatch.setenv("POLY_ENV", "production")
    monkeypatch.setenv("SKIP_ME", "1")

    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)

    with pytest.raises(SecurityViolationError) as exc_info:
        watchdog.check(skip_when_env="SKIP_ME")

    err_msg = str(exc_info.value)
    assert "production" in err_msg.lower()
    assert "bypass" in err_msg.lower()


def test_t6_test_env_controlled_bypass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """T6: Non-production + skip_when_env active -> bypassed=True & CRITICAL log captured."""
    manifest_path, contract = _setup_synthetic_environment(tmp_path)
    monkeypatch.setenv("POLY_ENV", "development")
    monkeypatch.setenv("ALLOW_TEST_BYPASS", "1")

    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)

    with caplog.at_level(logging.CRITICAL):
        report = watchdog.check(skip_when_env="ALLOW_TEST_BYPASS")

    assert report.is_valid is False
    assert report.bypassed is True
    assert report.verified_cells_count == 0
    assert "TEST BYPASS ACTIVATED" in caplog.text


def test_t7_incomplete_statutory_cells_coverage(tmp_path: Path):
    """T7: Manifest missing KORD_72h -> ContractGuardrailError with 'missing 1 cells'."""
    manifest_path, contract = _setup_synthetic_environment(
        tmp_path, omit_cells=[("KORD", 72)]
    )
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)

    with pytest.raises(ContractGuardrailError, match=r"missing 1 cells") as exc_info:
        watchdog.check()

    assert "Incomplete statutory cell coverage" in str(exc_info.value)


def test_t8_6h_lead_warn_only(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
):
    """T8: Manifest contains KORD 6h -> skipped_6h_entries >= 1, no exception, WARNING log."""
    manifest_path, contract = _setup_synthetic_environment(tmp_path, include_6h=True)
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)

    with caplog.at_level(logging.WARNING):
        report = watchdog.check()

    assert report.is_valid is True
    assert report.skipped_6h_entries >= 1
    assert report.verified_cells_count == TOTAL_AUTHORIZED_CELLS  # 22
    assert "6h lead model SKIPPED" in caplog.text


def test_manifest_file_not_found(tmp_path: Path):
    """Boundary: Nonexistent manifest file raises ManifestIntegrityError."""
    watchdog = ContractVersionWatchdog(manifest_path=tmp_path / "nonexistent.json")
    with pytest.raises(ManifestIntegrityError, match=r"Manifest file not found"):
        watchdog.check()


def test_manifest_invalid_json(tmp_path: Path):
    """Boundary: Corrupted JSON in manifest.json raises ManifestIntegrityError."""
    bad_manifest = tmp_path / "manifest.json"
    bad_manifest.write_text("{invalid json", encoding="utf-8")

    watchdog = ContractVersionWatchdog(manifest_path=bad_manifest)
    with pytest.raises(ManifestIntegrityError, match=r"Failed to parse manifest JSON"):
        watchdog.check()


def test_contract_manifest_sha256_mismatch(tmp_path: Path):
    """Boundary: Injected contract manifest anchor does not match actual canonical SHA."""
    manifest_path, contract = _setup_synthetic_environment(tmp_path)
    tampered_contract = PhysicalParamContract(
        contract_version=contract.contract_version,
        manifest_sha256="bad_sha_anchor_9999",
        model_weights_sha256=contract.model_weights_sha256,
        created_at=contract.created_at,
        cells=contract.cells,
    )

    watchdog = ContractVersionWatchdog(
        manifest_path=manifest_path, contract=tampered_contract
    )
    with pytest.raises(
        StaleModelParametersError, match=r"Contract manifest_sha256 mismatch"
    ):
        watchdog.check()


def test_contract_model_weight_sha256_mismatch(tmp_path: Path):
    """Boundary: Injected contract model weights sha mismatch triggers StaleModelParametersError."""
    manifest_path, contract = _setup_synthetic_environment(tmp_path)
    tampered_weights = dict(contract.model_weights_sha256)
    tampered_weights["KORD_12h"] = "bad_contract_cell_sha"

    tampered_contract = PhysicalParamContract(
        contract_version=contract.contract_version,
        manifest_sha256=contract.manifest_sha256,
        model_weights_sha256=tampered_weights,
        created_at=contract.created_at,
        cells=contract.cells,
    )

    watchdog = ContractVersionWatchdog(
        manifest_path=manifest_path, contract=tampered_contract
    )
    with pytest.raises(
        StaleModelParametersError,
        match=r"Contract model_weights_sha256 mismatch for cell 'KORD_12h'",
    ):
        watchdog.check()


def test_check_without_contract_injection(tmp_path: Path):
    """Boundary: watchdog with contract=None verifies manifest & pkl files without error."""
    manifest_path, _ = _setup_synthetic_environment(tmp_path)
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=None)

    report = watchdog.check()
    assert report.is_valid is True
    assert report.verified_cells_count == TOTAL_AUTHORIZED_CELLS  # 22


def test_corrupted_pickle_content(tmp_path: Path):
    """Boundary: Corrupted unpickling raises PickleCorruptionError."""
    manifest_path, contract = _setup_synthetic_environment(
        tmp_path, corrupt_pickle_cell=("KMIA", 30)
    )
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)

    with pytest.raises(PickleCorruptionError, match=r"Failed to unpickle model file"):
        watchdog.check()


def test_exception_inheritance_hierarchy():
    """Verify clean zero cross-layer exception inheritance."""
    assert issubclass(ManifestIntegrityError, ContractGuardrailError)
    assert issubclass(StaleModelParametersError, ContractGuardrailError)
    assert issubclass(PickleCorruptionError, ContractGuardrailError)
    assert issubclass(SecurityViolationError, ContractGuardrailError)
    assert issubclass(ContractGuardrailError, Exception)


def test_contract_version_and_guard_constants():
    """Verify constants definition and 6h exclusion."""
    assert CONTRACT_VERSION == "ADR-0019-Ticket01-v1"
    assert 6 not in AUTHORIZED_LEADS_FOR_GUARD
    assert len(AUTHORIZED_LEADS_FOR_GUARD) == 11


def test_contract_version_mismatch_raises_stale_model_parameters_error(tmp_path: Path):
    """Verify mismatch between injected contract version and CONTRACT_VERSION raises StaleModelParametersError."""
    manifest_path, contract = _setup_synthetic_environment(tmp_path)
    tampered_contract = PhysicalParamContract(
        contract_version="OUTDATED-SCHEMA-v0",
        manifest_sha256=contract.manifest_sha256,
        model_weights_sha256=contract.model_weights_sha256,
        created_at=contract.created_at,
        cells=contract.cells,
    )
    watchdog = ContractVersionWatchdog(
        manifest_path=manifest_path, contract=tampered_contract
    )
    with pytest.raises(
        StaleModelParametersError,
        match=r"Contract contract_version mismatch: expected='ADR-0019-Ticket01-v1', actual='OUTDATED-SCHEMA-v0'",
    ):
        watchdog.check()


def test_non_authorized_station_in_manifest_ignored(tmp_path: Path):
    """Verify models for non-authorized stations (e.g. KATL) are silently skipped."""
    manifest_path, contract = _setup_synthetic_environment(
        tmp_path, include_other_station=True
    )
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)
    report = watchdog.check()
    assert report.is_valid is True
    assert report.verified_cells_count == TOTAL_AUTHORIZED_CELLS  # 22


def test_real_repo_manifest_read_only_smoke():
    """Integration smoke test: read-only verification against actual data/models/manifest.json."""
    manifest_path = Path("data/models/manifest.json")
    if not manifest_path.exists():
        pytest.skip("data/models/manifest.json not found in repository")

    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=None)
    report = watchdog.check()

    assert report.is_valid is True
    assert report.verified_cells_count == TOTAL_AUTHORIZED_CELLS  # 22
    assert report.failed_entries == 0
    assert report.skipped_6h_entries == 64
    assert report.bypassed is False
    assert report.checked_at != ""


def test_bypass_report_is_not_valid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    R-1 Regression: Ensure bypass report explicitly sets is_valid=False.
    Protects downstream consumers (e.g. `if report.is_valid:`) from treating
    an unverified bypass state as a valid verification pass.
    """
    manifest_path, contract = _setup_synthetic_environment(tmp_path)
    monkeypatch.setenv("POLY_ENV", "test")
    monkeypatch.setenv("ALLOW_BYPASS", "1")
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)
    report = watchdog.check(skip_when_env="ALLOW_BYPASS")
    assert report.bypassed is True
    assert report.is_valid is False
    assert report.verified_cells_count == 0


def test_production_param_without_envvar_runs_full_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    R-2: In production, passing skip_when_env without setting the env var to '1'
    must ignore the parameter and run the full check normally.
    """
    manifest_path, contract = _setup_synthetic_environment(tmp_path)
    monkeypatch.setenv("POLY_ENV", "production")
    monkeypatch.delenv("UNSET_BYPASS_VAR", raising=False)
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)
    report = watchdog.check(skip_when_env="UNSET_BYPASS_VAR")
    assert report.is_valid is True
    assert report.verified_cells_count == TOTAL_AUTHORIZED_CELLS
    assert report.bypassed is False


def test_production_bypass_attempt_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    R-2: In production, setting skip_when_env var to '1' strictly raises SecurityViolationError.
    """
    manifest_path, contract = _setup_synthetic_environment(tmp_path)
    monkeypatch.setenv("POLY_ENV", "production")
    monkeypatch.setenv("ATTEMPT_BYPASS", "1")
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)
    with pytest.raises(SecurityViolationError, match=r"production environment"):
        watchdog.check(skip_when_env="ATTEMPT_BYPASS")


def test_bypass_env_value_must_be_literal_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """
    R-4: Test bypass only activates when the environment variable is strictly literal '1'.
    Values like 'true', 'yes', 'TRUE' do NOT trigger bypass and proceed to full verification.
    """
    manifest_path, contract = _setup_synthetic_environment(tmp_path)
    monkeypatch.setenv("POLY_ENV", "development")
    monkeypatch.setenv("BYPASS_FLAG", "true")
    watchdog = ContractVersionWatchdog(manifest_path=manifest_path, contract=contract)
    report = watchdog.check(skip_when_env="BYPASS_FLAG")
    assert report.bypassed is False
    assert report.is_valid is True
    assert report.verified_cells_count == TOTAL_AUTHORIZED_CELLS


def test_manifest_missing_lead_hours_raises_manifest_integrity_error(tmp_path: Path):
    """R-5: Manifest model entry missing 'lead_hours' raises ManifestIntegrityError (not bare KeyError)."""
    bad_manifest_dict = {
        "models": {
            "KORD_Winter_Max_lead12h.pkl": {
                "station": "KORD",
                "sha256": "abc",
            }
        }
    }
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(bad_manifest_dict), encoding="utf-8")
    watchdog = ContractVersionWatchdog(manifest_path=mpath)
    with pytest.raises(ManifestIntegrityError, match=r"missing required fields") as exc_info:
        watchdog.check()
    assert issubclass(type(exc_info.value), ContractGuardrailError)
    assert not issubclass(type(exc_info.value), KeyError)


def test_manifest_missing_station_raises_manifest_integrity_error(tmp_path: Path):
    """R-5: Manifest model entry missing 'station' raises ManifestIntegrityError (not bare KeyError)."""
    bad_manifest_dict = {
        "models": {
            "KORD_Winter_Max_lead12h.pkl": {
                "lead_hours": 12,
                "sha256": "abc",
            }
        }
    }
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(bad_manifest_dict), encoding="utf-8")
    watchdog = ContractVersionWatchdog(manifest_path=mpath)
    with pytest.raises(ManifestIntegrityError, match=r"missing required fields"):
        watchdog.check()


def test_manifest_entry_not_dict_raises_manifest_integrity_error(tmp_path: Path):
    """R-5: Manifest model entry that is not a dict raises ManifestIntegrityError."""
    bad_manifest_dict = {
        "models": {
            "KORD_Winter_Max_lead12h.pkl": "invalid-string-not-dict"
        }
    }
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(bad_manifest_dict), encoding="utf-8")
    watchdog = ContractVersionWatchdog(manifest_path=mpath)
    with pytest.raises(ManifestIntegrityError, match=r"metadata must be a dictionary"):
        watchdog.check()


def test_manifest_missing_sha256_raises_manifest_integrity_error(tmp_path: Path):
    """R-5: Manifest model entry missing 'sha256' raises ManifestIntegrityError."""
    fname = "KORD_Winter_Max_lead12h.pkl"
    (tmp_path / fname).write_bytes(b"some-bytes")
    bad_manifest_dict = {
        "models": {
            fname: {
                "station": "KORD",
                "lead_hours": 12,
            }
        }
    }
    mpath = tmp_path / "manifest.json"
    mpath.write_text(json.dumps(bad_manifest_dict), encoding="utf-8")
    watchdog = ContractVersionWatchdog(manifest_path=mpath)
    with pytest.raises(ManifestIntegrityError, match=r"missing 'sha256'"):
        watchdog.check()


