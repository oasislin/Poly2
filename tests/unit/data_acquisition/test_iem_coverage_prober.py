"""
Unit tests for IemCoverageProber (Ticket 03).
"""

from src.data_acquisition.iem_coverage_prober import IemCoverageProber


def test_probe_station_coverage_klga():
    prober = IemCoverageProber()
    res = prober.probe_station_coverage("KLGA", start_year=2000, end_year=2018)
    assert res.station == "KLGA"
    assert res.network == "NY_ASOS"
    assert res.coverage_pct >= 95.0
    assert res.passed_gate is True
    assert res.status == "COMPLETE"


def test_probe_batch():
    prober = IemCoverageProber()
    batch = prober.probe_batch(["KLGA", "KORD", "KBKF"])
    assert len(batch) == 3
    assert batch["KLGA"].passed_gate is True
    assert batch["KORD"].passed_gate is True
    assert batch["KBKF"].passed_gate is True
