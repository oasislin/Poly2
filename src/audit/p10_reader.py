"""Read-Only `P10` (`M7 -> M10`) Query Contract & Degraded Integrity Reader.

Anchors:
- `P8-T2-M7-LOGGING v1.1 §3.2`: zero independent DB, concurrent EOF tail skip
  (`tail_status = "CONCURRENT_TAIL_SKIPPED"`), explicit corrupt SHA256 accounting,
  missing/empty view (`"NO_AUDIT_RECORDS"`), `"PENDING_P9"` settlement,
  `P1/P3/P17/P19/P13` cross-stream drilldown, and zero-writeback (`open(..., "r")`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
from pathlib import Path
from typing import Any, Dict, List, Literal, Mapping, Optional, Tuple

from src.audit.audit_logger import STREAM_FILENAMES, AuditStreamName
from src.audit.p19_events import ExecutionMode
from src.utils.causal_utils import verify_record_sha256_line

RenderStatus = Literal["OK", "NO_AUDIT_RECORDS", "DEGRADED_CORRUPT_LINES"]
TailStatus = Literal["NONE", "CONCURRENT_TAIL_SKIPPED"]


@dataclass(frozen=True)
class P10Query:
    """Filter specification for read-only `M7 -> M10` views."""

    execution_mode: ExecutionMode
    date_range: Optional[Tuple[date, date]] = None
    session_id: Optional[str] = None
    station_id: Optional[str] = None
    target_date: Optional[str] = None


@dataclass(frozen=True)
class CorruptLineRecord:
    """Quarantined integrity/JSON failure detected while scanning JSONL logs."""

    file_path: str
    line_number: int
    reason: str


@dataclass(frozen=True)
class JsonlStreamReadResult:
    """Verified JSONL records plus integrity and tail-skip counters."""

    records: Tuple[Dict[str, Any], ...]
    valid_lines: int
    corrupt_lines: Tuple[CorruptLineRecord, ...]
    partial_tail_skipped_lines: int


@dataclass(frozen=True)
class DecisionJoinChain:
    """Joined trace linking `P1 -> P17`, `P1 -> P13`, `P3`, and `P19` records."""

    decision_id: str
    p1_record: Dict[str, Any]
    p17_record: Optional[Dict[str, Any]]
    p13_record: Optional[Dict[str, Any]]
    p3_records: Tuple[Dict[str, Any], ...]
    p19_records: Tuple[Dict[str, Any], ...]


@dataclass(frozen=True)
class P10SessionView:
    """Degradation-safe `P10` view bundle emitted by `M7` read-only queries."""

    execution_mode: ExecutionMode
    render_status: RenderStatus
    tail_status: TailStatus
    settlement_status: Literal["PENDING_P9", "READY"]
    p1_events: Tuple[Dict[str, Any], ...]
    p3_events: Tuple[Dict[str, Any], ...]
    p12_ledgers: Tuple[Dict[str, Any], ...]
    p17_snapshots: Tuple[Dict[str, Any], ...]
    p19_events: Tuple[Dict[str, Any], ...]
    joined_chains: Tuple[DecisionJoinChain, ...]
    valid_lines: int
    corrupt_lines: Tuple[CorruptLineRecord, ...]
    partial_tail_skipped_lines: int
    missing_forecast_fk_count: int


def read_verified_jsonl_file(path: Path, *, verify_sha256: bool = True) -> JsonlStreamReadResult:
    """Strictly read-only JSONL scanner skipping unterminated tails and quarantining corrupt lines."""
    records: List[Dict[str, Any]] = []
    corrupt: List[CorruptLineRecord] = []
    skipped_tail = 0
    if not path.exists():
        return JsonlStreamReadResult((), 0, (), 0)

    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            if not raw.endswith("\n"):
                skipped_tail += 1
                continue
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                obj = json.loads(stripped)
            except Exception as exc:
                corrupt.append(CorruptLineRecord(str(path), line_no, f"JSON_ERROR:{type(exc).__name__}"))
                continue
            if verify_sha256 and not verify_record_sha256_line(stripped):
                corrupt.append(CorruptLineRecord(str(path), line_no, "SHA256_MISMATCH"))
                continue
            records.append(obj)
    return JsonlStreamReadResult(tuple(records), len(records), tuple(corrupt), skipped_tail)


def _matches_query(record: Mapping[str, Any], query: P10Query) -> bool:
    if record.get("execution_mode") != query.execution_mode:
        return False
    if query.session_id is not None and record.get("session_id") != query.session_id:
        return False
    if query.station_id is not None and record.get("station_id") != query.station_id:
        return False
    if query.target_date is not None and record.get("target_date") != query.target_date:
        return False
    return True


def _iter_date_dirs(mode_root: Path, query: P10Query) -> List[Path]:
    if not mode_root.exists():
        return []
    start_d, end_d = query.date_range if query.date_range is not None else (None, None)
    out: List[Path] = []
    for child in sorted(mode_root.iterdir()):
        if not child.is_dir():
            continue
        try:
            d = date.fromisoformat(child.name)
        except ValueError:
            continue
        if (start_d is not None and d < start_d) or (end_d is not None and d > end_d):
            continue
        out.append(child)
    return out


def _read_all_mode_streams(
    date_dirs: List[Path], query: P10Query
) -> Tuple[Dict[AuditStreamName, Tuple[Dict[str, Any], ...]], Tuple[CorruptLineRecord, ...], int]:
    by_stream: Dict[AuditStreamName, Tuple[Dict[str, Any], ...]] = {}
    corrupts: List[CorruptLineRecord] = []
    tail_cnt = 0
    for stream, fname in STREAM_FILENAMES.items():
        matched: List[Dict[str, Any]] = []
        for ddir in date_dirs:
            res = read_verified_jsonl_file(ddir / fname, verify_sha256=True)
            tail_cnt += res.partial_tail_skipped_lines
            corrupts.extend(res.corrupt_lines)
            matched.extend(r for r in res.records if _matches_query(r, query))
        by_stream[stream] = tuple(matched)
    return by_stream, tuple(corrupts), tail_cnt


def _index_p13_frames(p13_root: Optional[Path]) -> Dict[Tuple[str, str, int], Dict[str, Any]]:
    if p13_root is None or not Path(p13_root).exists():
        return {}
    index: Dict[Tuple[str, str, int], Dict[str, Any]] = {}
    for path in sorted(Path(p13_root).rglob("p13_book_stream_*.jsonl")):
        res = read_verified_jsonl_file(path, verify_sha256=True)
        for rec in res.records:
            payload = rec.get("payload")
            if not isinstance(payload, Mapping):
                continue
            sid, tok, fseq = rec.get("session_id"), payload.get("token_id"), payload.get("frame_seq")
            if isinstance(sid, str) and isinstance(tok, str) and isinstance(fseq, int):
                index[(sid, tok, fseq)] = rec
    return index


def _build_join_chains(
    by_stream: Mapping[AuditStreamName, Tuple[Dict[str, Any], ...]],
    p13_index: Mapping[Tuple[str, str, int], Dict[str, Any]],
) -> Tuple[Tuple[DecisionJoinChain, ...], int]:
    fc_by_id = {r.get("forecast_id"): r for r in by_stream["p17"] if r.get("forecast_id")}
    p3_by_dec: Dict[str, List[Dict[str, Any]]] = {}
    for r in by_stream["p3"]:
        p3_by_dec.setdefault(str(r.get("decision_id")), []).append(r)
    p19_by_ref: Dict[str, List[Dict[str, Any]]] = {}
    for r in by_stream["p19"]:
        if r.get("related_ref_id"):
            p19_by_ref.setdefault(str(r["related_ref_id"]), []).append(r)

    chains: List[DecisionJoinChain] = []
    missing_fk = 0
    for r1 in by_stream["p1"]:
        dec_id = str(r1["decision_id"])
        fc_id = r1.get("forecast_id")
        fc_rec = fc_by_id.get(fc_id) if isinstance(fc_id, str) else None
        if isinstance(fc_id, str) and not fc_id.startswith("MISSING") and fc_rec is None:
            missing_fk += 1
        p13_rec = _lookup_p13_for_p1(r1, p13_index)
        linked_p3 = p3_by_dec.get(dec_id, [])
        refs = [dec_id] + [str(r3.get("attempt_id")) for r3 in linked_p3 if r3.get("attempt_id")]
        linked_p19 = [ev for ref in refs for ev in p19_by_ref.get(ref, [])]
        chains.append(DecisionJoinChain(dec_id, r1, fc_rec, p13_rec, tuple(linked_p3), tuple(linked_p19)))
    return tuple(chains), missing_fk


def _lookup_p13_for_p1(
    r1: Mapping[str, Any], p13_index: Mapping[Tuple[str, str, int], Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    sid, tok, fref = r1.get("session_id"), r1.get("token_id"), r1.get("book_frame_ref")
    if isinstance(sid, str) and isinstance(tok, str) and isinstance(fref, int) and fref > 0:
        return p13_index.get((sid, tok, fref))
    return None


def query_p10_session_view(
    audit_root: Path,
    query: P10Query,
    *,
    p13_root: Optional[Path] = None,
) -> P10SessionView:
    """Strictly read-only query building a joined, fault-tolerant `P10` view."""
    date_dirs = _iter_date_dirs(Path(audit_root) / query.execution_mode, query)
    if not date_dirs:
        return P10SessionView(
            query.execution_mode, "NO_AUDIT_RECORDS", "NONE", "PENDING_P9", (), (), (), (), (), (), 0, (), 0, 0
        )
    by_stream, corrupt, tail_cnt = _read_all_mode_streams(date_dirs, query)
    matched_valid = sum(len(rows) for rows in by_stream.values())
    chains, missing_fk = _build_join_chains(by_stream, _index_p13_frames(p13_root))
    status: RenderStatus = (
        "DEGRADED_CORRUPT_LINES"
        if corrupt
        else ("NO_AUDIT_RECORDS" if matched_valid == 0 else "OK")
    )
    tail_status: TailStatus = "CONCURRENT_TAIL_SKIPPED" if tail_cnt > 0 else "NONE"
    return P10SessionView(
        execution_mode=query.execution_mode,
        render_status=status,
        tail_status=tail_status,
        settlement_status="PENDING_P9",
        p1_events=by_stream["p1"],
        p3_events=by_stream["p3"],
        p12_ledgers=by_stream["p12"],
        p17_snapshots=by_stream["p17"],
        p19_events=by_stream["p19"],
        joined_chains=chains,
        valid_lines=matched_valid,
        corrupt_lines=corrupt,
        partial_tail_skipped_lines=tail_cnt,
        missing_forecast_fk_count=missing_fk,
    )


__all__ = [
    "CorruptLineRecord",
    "DecisionJoinChain",
    "JsonlStreamReadResult",
    "P10Query",
    "P10SessionView",
    "RenderStatus",
    "TailStatus",
    "query_p10_session_view",
    "read_verified_jsonl_file",
]
