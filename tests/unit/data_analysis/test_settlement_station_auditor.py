"""
Unit tests for SettlementStationAuditor (Ticket 02 of M0').
"""

import pytest
from src.data_analysis.settlement_station_auditor import (
    SettlementStationAuditor,
    PrecedentAuditRecord,
    StationAuditResult,
)


def test_check_bracket_match_range():
    auditor = SettlementStationAuditor()
    assert auditor.check_bracket_match("88-89°F", 88.2) is True
    assert auditor.check_bracket_match("88-89°F", 89.0) is True
    assert auditor.check_bracket_match("88-89°F", 89.4) is True
    assert auditor.check_bracket_match("88-89°F", 87.4) is False
    assert auditor.check_bracket_match("88-89°F", 90.0) is False


def test_check_bracket_match_or_higher():
    auditor = SettlementStationAuditor()
    assert auditor.check_bracket_match("66°F or higher", 66.0) is True
    assert auditor.check_bracket_match("66°F or higher", 75.2) is True
    assert auditor.check_bracket_match("66°F or higher", 65.4) is False


def test_check_bracket_match_or_below():
    auditor = SettlementStationAuditor()
    assert auditor.check_bracket_match("44°F or below", 43.8) is True
    assert auditor.check_bracket_match("44°F or below", 44.0) is True
    assert auditor.check_bracket_match("44°F or below", 45.1) is False


def test_audit_precedent_confirmed():
    auditor = SettlementStationAuditor()
    prec = auditor.audit_precedent(
        target_date="2026-09-02",
        event_title="Highest temperature in Denver on September 2?",
        event_slug="highest-temperature-in-denver-on-september-2-2026",
        winning_bracket="88-89°F",
        declared_station="KBKF",
        candidate_max_temps={"KBKF": 88.88, "KDEN": 87.4},
    )
    assert prec.audit_verdict == "CONFIRMED"
    assert prec.matched_candidate == "KBKF"


def test_audit_precedent_conflict_red_flag():
    auditor = SettlementStationAuditor()
    # Assume declared was KDEN, but actual settlement matches KBKF
    prec = auditor.audit_precedent(
        target_date="2026-09-02",
        event_title="Highest temperature in Denver on September 2?",
        event_slug="highest-temperature-in-denver-on-september-2-2026",
        winning_bracket="88-89°F",
        declared_station="KDEN",
        candidate_max_temps={"KBKF": 88.88, "KDEN": 82.0},
    )
    assert prec.audit_verdict == "CONFLICT"
    assert prec.matched_candidate == "KBKF"


def test_consolidate_city_audit():
    auditor = SettlementStationAuditor()
    precedents = [
        PrecedentAuditRecord(
            target_date="2026-09-02",
            event_title="Denver Sep 2",
            event_slug="slug1",
            winning_bracket="88-89°F",
            declared_station="KBKF",
            candidate_observations={"KBKF": 88.8, "KDEN": 85.0},
            matched_candidate="KBKF",
            audit_verdict="CONFIRMED",
        ),
        PrecedentAuditRecord(
            target_date="2026-03-29",
            event_title="Denver Mar 29",
            event_slug="slug2",
            winning_bracket="76-77°F",
            declared_station="KBKF",
            candidate_observations={"KBKF": 76.5, "KDEN": 72.0},
            matched_candidate="KBKF",
            audit_verdict="CONFIRMED",
        ),
        PrecedentAuditRecord(
            target_date="2026-04-15",
            event_title="Denver Apr 15",
            event_slug="slug3",
            winning_bracket="68-69°F",
            declared_station="KBKF",
            candidate_observations={"KBKF": 68.2, "KDEN": 65.0},
            matched_candidate="KBKF",
            audit_verdict="CONFIRMED",
        ),
    ]

    res = auditor.consolidate_city_audit("Denver", "KBKF", precedents)
    assert res.final_adjudicated_station == "KBKF"
    assert res.confirmed_precedents_count == 3
    assert res.red_flag is False
    assert "KBKF vs KDEN" in str(res.dispute_adjudication)


def test_consolidate_city_audit_under_3_precedents_red_flag():
    auditor = SettlementStationAuditor()
    # When precedents count is < 3, must trigger red flag as per Spec line 31-32 & 37
    res = auditor.consolidate_city_audit("Miami", "KMIA", [])
    assert res.red_flag is True
    assert res.total_precedents_audited == 0
    assert "不足 3 个" in str(res.red_flag_reason)

