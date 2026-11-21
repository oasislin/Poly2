"""Read-Only `P13` JSONL Stream Reader & `P18` Replay Frame Index (`M7`).

Anchors:
- Strict zero-writeback: opens `p13_book_stream_*.jsonl` strictly read-only (`"r"`).
- Concurrent tail safety: skips trailing partial line missing newline `\\n`.
- Pure indexing separation: contains zero execution matching or slice planning logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from src.audit.p10_reader import CorruptLineRecord, read_verified_jsonl_file
from src.data_acquisition.passive_book_recorder import MarketBookRecordEnvelope
from src.execution.orderbook_views import (
    DualSideBookPair,
    pair_dual_side_books,
    parse_p4_snapshot_from_p13_dict,
)
from src.utils.causal_utils import ensure_utc_datetime

MarketKey = Tuple[str, str, str, str]


@dataclass(frozen=True)
class P13ReadSummary:
    """Integrity & frame summary of a read-only `P13` session scan."""

    session_dir: str
    files_scanned: int
    valid_frames: int
    corrupt_lines: Tuple[CorruptLineRecord, ...]
    partial_tail_skipped_lines: int
    gap_frames_count: int


@dataclass(frozen=True)
class P13SessionLoad:
    """Loaded `MarketBookRecordEnvelope` stream alongside scan summary."""

    summary: P13ReadSummary
    envelopes: Tuple[MarketBookRecordEnvelope, ...]


def load_p13_session_readonly(session_dir: Path, *, verify_sha256: bool = True) -> P13SessionLoad:
    """Read and parse all `p13_book_stream_*.jsonl` files under `session_dir` read-only."""
    sdir = Path(session_dir)
    if not sdir.exists():
        raise FileNotFoundError(f"P13 session directory not found: {sdir}")
    files = sorted(sdir.glob("p13_book_stream_*.jsonl"))
    envelopes: List[MarketBookRecordEnvelope] = []
    corrupt: List[CorruptLineRecord] = []
    skipped_tail = 0

    for path in files:
        res = read_verified_jsonl_file(path, verify_sha256=verify_sha256)
        skipped_tail += res.partial_tail_skipped_lines
        corrupt.extend(res.corrupt_lines)
        for idx, raw_env in enumerate(res.records, start=1):
            try:
                envelopes.append(parse_p4_snapshot_from_p13_dict(raw_env))
            except Exception as exc:
                corrupt.append(CorruptLineRecord(str(path), idx, f"P13_SCHEMA_ERROR:{type(exc).__name__}:{exc}"))

    ordered = tuple(sorted(envelopes, key=lambda e: (e.payload.recv_ts_utc, e.seq_id)))
    gap_cnt = sum(1 for env in ordered if env.gap_detected)
    summary = P13ReadSummary(
        session_dir=str(sdir),
        files_scanned=len(files),
        valid_frames=len(ordered),
        corrupt_lines=tuple(corrupt),
        partial_tail_skipped_lines=skipped_tail,
        gap_frames_count=gap_cnt,
    )
    return P13SessionLoad(summary=summary, envelopes=ordered)


class P18ReplayFrameRetriever:
    """Pure read-only `M7 -> M5 (P18)` frame index over recorded `P13` envelopes."""

    def __init__(self, envelopes: Sequence[MarketBookRecordEnvelope]) -> None:
        self.envelopes: Tuple[MarketBookRecordEnvelope, ...] = tuple(
            sorted(envelopes, key=lambda e: (e.payload.recv_ts_utc, e.seq_id))
        )
        self._by_token: Dict[str, List[MarketBookRecordEnvelope]] = {}
        self._by_market_key: Dict[MarketKey, List[MarketBookRecordEnvelope]] = {}
        for env in self.envelopes:
            self._by_token.setdefault(env.payload.token_id, []).append(env)
            mkey: MarketKey = (env.station_id, env.target_date, env.bin_label, env.payload.market_id)
            self._by_market_key.setdefault(mkey, []).append(env)

    def get_token_stream(self, token_id: str) -> Tuple[MarketBookRecordEnvelope, ...]:
        """Return time-ordered recorded envelopes for `token_id`."""
        return tuple(self._by_token.get(token_id, ()))

    def list_market_keys(self) -> Tuple[MarketKey, ...]:
        """Return distinct `(station_id, target_date, bin_label, market_id)` keys."""
        return tuple(sorted(self._by_market_key.keys()))

    def list_gap_frames(self) -> Tuple[MarketBookRecordEnvelope, ...]:
        """Return all `gap_detected=True` envelopes in causal order."""
        return tuple(e for e in self.envelopes if e.gap_detected)

    def find_latest_seq_before(
        self, token_id: str, as_of_ts_utc: datetime, *, strict_lt_seq: Optional[int] = None
    ) -> int:
        """Find highest `seq_id` on `token_id` strictly matching causal time/seq cutoff."""
        as_of = ensure_utc_datetime(as_of_ts_utc, field_name="retriever.as_of_ts_utc")
        seqs = [
            e.seq_id
            for e in self._by_token.get(token_id, ())
            if ensure_utc_datetime(e.payload.recv_ts_utc, field_name="p13.recv_ts_utc") <= as_of
            and (strict_lt_seq is None or e.seq_id < strict_lt_seq)
        ]
        return max(seqs) if seqs else (max(0, strict_lt_seq - 1) if strict_lt_seq is not None else 0)

    def resolve_companion_yes_token(self, env: MarketBookRecordEnvelope) -> Tuple[str, int]:
        """Locate clean companion `YES` token_id and latest prior `seq_id` for a `NO` envelope."""
        mkey: MarketKey = (env.station_id, env.target_date, env.bin_label, env.payload.market_id)
        for cand in reversed(self._by_market_key.get(mkey, ())):
            if cand.payload.outcome == "YES" and not cand.gap_detected and cand.seq_id <= env.seq_id:
                return cand.payload.token_id, cand.seq_id
        return f"paired-yes-{env.payload.market_id}", max(0, env.seq_id - 1)

    def retrieve_decision_book_pairs(
        self,
        *,
        as_of_ts_utc: datetime,
        max_book_staleness_sec: float,
        pair_max_skew_sec: float,
        allow_gap_frames: bool = False,
    ) -> Dict[MarketKey, DualSideBookPair]:
        """Build causal YES/NO pairs across all markets using only frames `<= as_of_ts_utc`."""
        as_of = ensure_utc_datetime(as_of_ts_utc, field_name="retriever.as_of_ts_utc")
        causal_prefix = [
            e
            for e in self.envelopes
            if ensure_utc_datetime(e.payload.recv_ts_utc, field_name="p13.recv_ts_utc") <= as_of
        ]
        return pair_dual_side_books(
            causal_prefix,
            as_of_ts_utc=as_of,
            max_book_staleness_sec=max_book_staleness_sec,
            pair_max_skew_sec=pair_max_skew_sec,
            allow_gap_frames=allow_gap_frames,
        )


__all__ = [
    "MarketKey",
    "P13ReadSummary",
    "P13SessionLoad",
    "P18ReplayFrameRetriever",
    "load_p13_session_readonly",
]
