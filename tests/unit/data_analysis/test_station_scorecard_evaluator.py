"""
Unit tests for StationScorecardEvaluator (Ticket 03 of M0').
"""

import pytest
from src.data_analysis.station_scorecard_evaluator import (
    StationScorecardEvaluator,
    StationScorecard,
)


def test_evaluate_admitted_station_klga():
    evaluator = StationScorecardEvaluator()
    sc = evaluator.evaluate_station("KLGA")
    assert sc.overall_status in ["ADMITTED", "WARNING_ADMITTED"]
    assert sc.hard_gates_passed == 4
    assert sc.hard_gates_total == 4
    assert len(sc.rejection_reasons) == 0


def test_evaluate_admitted_station_kbkf():
    evaluator = StationScorecardEvaluator()
    sc = evaluator.evaluate_station("KBKF")
    # KBKF has high elevation, so warning level triggered on factor 5, but hard gates passed!
    assert sc.hard_gates_passed == 4
    assert sc.overall_status == "WARNING_ADMITTED"
    assert len(sc.warnings) > 0


def test_evaluate_rejected_station_zspd():
    evaluator = StationScorecardEvaluator()
    sc = evaluator.evaluate_station("ZSPD")
    # ZSPD lacks NWS native status and active polymarket daily markets
    assert sc.overall_status == "REJECTED"
    assert sc.hard_gates_passed < 4
    assert any("NWS Native" in r for r in sc.rejection_reasons)
    assert any("Market Presence" in r for r in sc.rejection_reasons)


def test_evaluate_rejected_station_kden():
    evaluator = StationScorecardEvaluator()
    sc = evaluator.evaluate_station("KDEN")
    # KDEN is rejected because Polymarket does not settle on KDEN (settles on KBKF)
    assert sc.overall_status == "REJECTED"
    assert any("Market Presence" in r for r in sc.rejection_reasons)


def test_evaluate_batch():
    evaluator = StationScorecardEvaluator()
    batch = evaluator.evaluate_batch(["KBKF", "KDEN", "KLGA", "KORD", "KMIA", "ZSPD"])
    assert len(batch) == 6
    assert batch["KLGA"].hard_gates_passed == 4
    assert batch["KORD"].hard_gates_passed == 4
    assert batch["ZSPD"].overall_status == "REJECTED"
