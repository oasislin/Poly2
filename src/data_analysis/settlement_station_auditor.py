"""
Settlement Station Auditor and Precedent Verifier (Ticket 02 of M0').
Audits declared rule stations against historical settlement precedents,
adjudicating disputed stations (e.g. KBKF vs KDEN) and flagging discrepancies.
"""

from dataclasses import dataclass, field
from enum import Enum
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AuditVerdict(str, Enum):
    """Enumeration of precedent verification verdict."""
    CONFIRMED = "CONFIRMED"
    CONFLICT = "CONFLICT"
    INCONCLUSIVE = "INCONCLUSIVE"
    UNVERIFIED = "UNVERIFIED"


@dataclass
class PrecedentAuditRecord:
    """Individual settlement precedent audit result."""
    target_date: str
    event_title: str
    event_slug: str
    winning_bracket: str
    declared_station: str
    candidate_observations: Dict[str, Optional[float]] = field(default_factory=dict)
    matched_candidate: Optional[str] = None
    audit_verdict: AuditVerdict = AuditVerdict.UNVERIFIED
    notes: str = ""


@dataclass
class StationAuditResult:
    """Consolidated audit result for a city/market."""
    city: str
    declared_station: str
    final_adjudicated_station: str
    dispute_adjudication: Optional[str] = None  # e.g. 'KBKF vs KDEN: KBKF CONFIRMED'
    total_precedents_audited: int = 0
    confirmed_precedents_count: int = 0
    red_flag: bool = False
    red_flag_reason: Optional[str] = None
    precedents: List[PrecedentAuditRecord] = field(default_factory=list)


class SettlementStationAuditor:
    """Audits and adjudicates settlement station identities across markets."""

    DISPUTED_STATIONS = {
        "Denver": ["KBKF", "KDEN"],
        "NYC": ["KLGA", "KNYC", "KJFK"],
        "Chicago": ["KORD", "KMDW"],
    }

    @staticmethod
    def check_bracket_match(bracket_str: str, temp_value: Optional[float], unit: str = "Fahrenheit") -> bool:
        """
        Check if an observed temperature matches a winning bracket string.
        Examples: '88-89°F', '66°F or higher', '44°F or below', '25-26°C'
        """
        if temp_value is None or not bracket_str:
            return False

        b = bracket_str.replace("°F", "").replace("°C", "").strip()
        t = round(temp_value)  # Polymarket resolves to nearest whole degree

        if "or higher" in b:
            try:
                lower = float(b.replace("or higher", "").strip())
                return t >= lower
            except ValueError:
                return False
        elif "or below" in b or "or lower" in b:
            try:
                upper = float(b.replace("or below", "").replace("or lower", "").strip())
                return t <= upper
            except ValueError:
                return False
        elif "-" in b:
            parts = b.split("-")
            try:
                low = float(parts[0].strip())
                high = float(parts[1].strip())
                return low <= t <= high
            except ValueError:
                return False

        return False

    def audit_precedent(
        self,
        target_date: str,
        event_title: str,
        event_slug: str,
        winning_bracket: str,
        declared_station: str,
        candidate_max_temps: Dict[str, Optional[float]],
        unit: str = "Fahrenheit",
    ) -> PrecedentAuditRecord:
        """Audit a single settlement precedent against candidate station observations."""
        matches = [
            cand for cand, val in candidate_max_temps.items()
            if self.check_bracket_match(winning_bracket, val, unit=unit)
        ]

        if len(matches) == 1:
            matched = matches[0]
            if matched == declared_station:
                verdict = AuditVerdict.CONFIRMED
                notes = f"Observation {candidate_max_temps[matched]} matches bracket '{winning_bracket}'."
            else:
                verdict = AuditVerdict.CONFLICT
                notes = (
                    f"Conflict: Declared station {declared_station} observed "
                    f"{candidate_max_temps.get(declared_station)}, but matched {matched} "
                    f"with {candidate_max_temps.get(matched)} in bracket '{winning_bracket}'."
                )
        elif len(matches) > 1:
            if declared_station in matches:
                matched = declared_station
                verdict = AuditVerdict.CONFIRMED
                notes = f"Multiple candidates ({matches}) matched bracket '{winning_bracket}'. Declared station matches."
            else:
                matched = matches[0]
                verdict = AuditVerdict.CONFLICT
                notes = f"Multiple non-declared candidates ({matches}) matched bracket."
        else:
            matched = None
            verdict = AuditVerdict.INCONCLUSIVE
            notes = f"No candidate observations ({candidate_max_temps}) matched winning bracket '{winning_bracket}'."

        return PrecedentAuditRecord(
            target_date=target_date,
            event_title=event_title,
            event_slug=event_slug,
            winning_bracket=winning_bracket,
            declared_station=declared_station,
            candidate_observations=candidate_max_temps,
            matched_candidate=matched,
            audit_verdict=verdict,
            notes=notes,
        )

    def consolidate_city_audit(
        self,
        city: str,
        declared_station: str,
        precedents: List[PrecedentAuditRecord],
    ) -> StationAuditResult:
        """Consolidate audit findings for a city across all its precedents."""
        total = len(precedents)
        confirmed = sum(1 for p in precedents if p.audit_verdict == AuditVerdict.CONFIRMED)
        conflicts = sum(1 for p in precedents if p.audit_verdict == AuditVerdict.CONFLICT)

        red_flag = False
        red_flag_reason = None
        final_station = declared_station

        if total < 3:
            red_flag = True
            red_flag_reason = f"未满足硬门禁：历史判例数不足 3 个（当前仅 {total} 个），处于待补充取证状态。"
        elif conflicts > 0 and conflicts >= confirmed:
            red_flag = True
            matched_counts: Dict[str, int] = {}
            for p in precedents:
                if p.matched_candidate:
                    matched_counts[p.matched_candidate] = matched_counts.get(p.matched_candidate, 0) + 1
            if matched_counts:
                best_cand = max(matched_counts, key=matched_counts.get)
                final_station = best_cand
                red_flag_reason = (
                    f"规则与判例严重冲突：真实结算使用 {best_cand}，而非声明站 {declared_station}。"
                )
            else:
                red_flag_reason = f"判例与声明站 {declared_station} 冲突。"

        dispute_note = None
        if city in self.DISPUTED_STATIONS:
            candidates_str = " vs ".join(self.DISPUTED_STATIONS[city])
            dispute_note = f"{city} candidate set ({candidates_str}) -> Adjudicated as {final_station}"

        return StationAuditResult(
            city=city,
            declared_station=declared_station,
            final_adjudicated_station=final_station,
            dispute_adjudication=dispute_note,
            total_precedents_audited=total,
            confirmed_precedents_count=confirmed,
            red_flag=red_flag,
            red_flag_reason=red_flag_reason,
            precedents=precedents,
        )
