"""
tests/e2e/test_semantics_unification.py: End-to-End Verification for GATE-L2-04
Specification: specs/p5_layer2_scenarios.md §2.4 (GATE-L2-04: 0.35 语义统一回归)

Validates:
1. Scalar routing: isolated pit = 0.35 legally routes to bin 8 ([0.35, 0.40)) without exception.
2. Stream-level degeneracy: 1,000-row identical stream (stream_identical.csv, var=0) triggers DataAssetError.
3. Multi-value constant generalization: streams of constant 0.50 or 0.80 also trigger DataAssetError.
"""

from pathlib import Path
import tempfile
import pytest

from scripts.standalone_reliability_check import (
    route_pit_value,
    pit_to_bin,
    check_stream_degeneracy,
    route_stream,
    analyze_pit_stream,
    DataAssetError,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
FIX_DIR = PROJECT_ROOT / "tests" / "fixtures" / "p5_selfcheck"


def test_gate_l2_04_scalar_legal_routing():
    """GATE-L2-04 Assertion 1: route_pit_value(0.35) == 8 without exception."""
    assert pit_to_bin(0.35) == 8
    assert route_pit_value(0.35) == 8
    assert route_pit_value("0.35") == 8


def test_gate_l2_04_stream_analysis_collapse_interception():
    """GATE-L2-04 Assertion 2: stream_identical.csv triggers DataAssetError with expected message."""
    identical_csv = FIX_DIR / "stream_identical.csv"
    assert identical_csv.exists()

    with pytest.raises(DataAssetError) as exc_info:
        analyze_pit_stream(str(identical_csv))
    assert "degenerate: zero variance" in str(exc_info.value)

    with pytest.raises(DataAssetError) as exc_info2:
        route_stream(str(identical_csv), check_degeneracy=True)
    assert "degenerate: zero variance" in str(exc_info2.value)


def test_gate_l2_04_constant_stream_generalization():
    """GATE-L2-04 Assertion 3: Any constant stream (e.g. 0.50, 0.80) 100% triggers degeneracy interception."""
    # Test in-memory list
    with pytest.raises(DataAssetError) as exc_50:
        check_stream_degeneracy([0.50] * 500)
    assert "degenerate: zero variance" in str(exc_50.value)

    with pytest.raises(DataAssetError) as exc_80:
        check_stream_degeneracy([0.80] * 500)
    assert "degenerate: zero variance" in str(exc_80.value)

    # Test file-based stream analysis
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_csv = Path(tmpdir) / "stream_constant_50.csv"
        tmp_csv.write_text("pit\n" + "\n".join(["0.50"] * 100))
        with pytest.raises(DataAssetError):
            analyze_pit_stream(str(tmp_csv))


def test_gate_l2_04_mixed_stream_with_035_passes():
    """GATE-L2-04 Invariant: Non-degenerate stream containing 0.35 values passes without error."""
    mixed = [0.1, 0.2, 0.35, 0.35, 0.5, 0.7, 0.9]
    check_stream_degeneracy(mixed)

    uniform_csv = FIX_DIR / "stream_uniform.csv"
    res = analyze_pit_stream(str(uniform_csv))
    assert res["row_count"] == 1000
    assert sum(res["counts"]) == 1000
