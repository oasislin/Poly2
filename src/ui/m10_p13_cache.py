"""Incremental, on-demand read-only P13 orderbook snapshot lookup cache for M10 live view."""

from __future__ import annotations

from dataclasses import dataclass, field
import gzip
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from src.utils.causal_utils import verify_record_sha256_line

P13Key = Tuple[str, str, int]


@dataclass
class _P13PlainCursor:
    inode: int = -1
    offset: int = 0
    frames: Dict[P13Key, Dict[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class _P13GzEntry:
    inode: int
    size: int
    mtime_ns: int
    frames: Dict[P13Key, Dict[str, Any]]


def _slim_p13_record(obj: Mapping[str, Any]) -> Optional[Tuple[P13Key, Dict[str, Any]]]:
    sid = obj.get("session_id")
    pl = obj.get("payload")
    if not isinstance(sid, str) or not isinstance(pl, Mapping):
        return None
    tok, fseq = pl.get("token_id"), pl.get("frame_seq")
    if not isinstance(tok, str) or not isinstance(fseq, int) or fseq <= 0:
        return None
    asks = pl.get("asks") if isinstance(pl.get("asks"), list) else []
    bids = pl.get("bids") if isinstance(pl.get("bids"), list) else []
    if not bids and isinstance(pl.get("bid_top10"), list):
        bids = pl.get("bid_top10")
    slim = {
        "session_id": sid,
        "payload": {
            "token_id": tok,
            "frame_seq": fseq,
            "recv_ts_utc": pl.get("recv_ts_utc"),
            "data_source": pl.get("data_source"),
            "single_side": pl.get("single_side"),
            "best_bid": pl.get("best_bid"),
            "fee_rate": pl.get("fee_rate"),
            "min_order_size_shares": pl.get("min_order_size_shares"),
            "asks": list(asks[:3]),
            "bids": list(bids[:3]),
        },
    }
    return (sid, tok, fseq), slim


def _ingest_p13_line(raw_line: str, frames: Dict[P13Key, Dict[str, Any]]) -> None:
    stripped = raw_line.strip()
    if not stripped:
        return
    try:
        obj = json.loads(stripped)
    except Exception:
        return
    if not verify_record_sha256_line(stripped):
        return
    parsed = _slim_p13_record(obj)
    if parsed is not None:
        key, slim = parsed
        frames[key] = slim


def _update_p13_plain_cursor(path: Path, cur: _P13PlainCursor) -> None:
    st = path.stat()
    if st.st_ino != cur.inode or st.st_size < cur.offset:
        cur.inode, cur.offset = st.st_ino, 0
        cur.frames.clear()
    if st.st_size == cur.offset:
        return
    with path.open("rb") as fb:
        fb.seek(cur.offset)
        chunk = fb.read()
    last_nl = chunk.rfind(b"\n")
    if last_nl < 0:
        return
    complete = chunk[: last_nl + 1]
    cur.offset += len(complete)
    for line in complete.decode("utf-8", errors="replace").splitlines(keepends=True):
        _ingest_p13_line(line, cur.frames)


class IncrementalP13Lookup:
    """Lazy, incremental read-only cache indexing only P13 streams referenced by visible P1 rows."""

    def __init__(self, p13_root: Optional[Path] = None) -> None:
        self.p13_root: Optional[Path] = Path(p13_root) if p13_root is not None else None
        self._plain: Dict[Path, _P13PlainCursor] = {}
        self._gz: Dict[Path, _P13GzEntry] = {}

    def _find_stream_files(self, session_id: str, station_id: str) -> List[Path]:
        if self.p13_root is None or not self.p13_root.exists():
            return []
        fname = f"p13_book_stream_{station_id}.jsonl"
        hits = sorted(self.p13_root.glob(f"*/*/{session_id}/{fname}"))
        if not hits:
            hits = sorted(self.p13_root.glob(f"*/*/{session_id}/{fname}.gz"))
        if not hits:
            hits = sorted(self.p13_root.rglob(f"{fname}*"))
        return [p for p in hits if p.is_file() and (p.name == fname or p.name == f"{fname}.gz")]

    def _load_gz(self, path: Path) -> Dict[P13Key, Dict[str, Any]]:
        st = path.stat()
        prev = self._gz.get(path)
        if prev is not None and (prev.inode, prev.size, prev.mtime_ns) == (st.st_ino, st.st_size, st.st_mtime_ns):
            return prev.frames
        frames: Dict[P13Key, Dict[str, Any]] = {}
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                if line.endswith("\n"):
                    _ingest_p13_line(line, frames)
        self._gz[path] = _P13GzEntry(st.st_ino, st.st_size, st.st_mtime_ns, frames)
        return frames

    def lookup_for_p1(self, p1_records: Iterable[Mapping[str, Any]]) -> Dict[P13Key, Dict[str, Any]]:
        """Incrementally read only `(session_id, station_id)` P13 streams matching `p1_records`."""
        if self.p13_root is None or not self.p13_root.exists():
            return {}
        needed_keys: Set[P13Key] = set()
        sess_stations: Set[Tuple[str, str]] = set()
        for r1 in p1_records:
            sid, st_id, tok, fref = r1.get("session_id"), r1.get("station_id"), r1.get("token_id"), r1.get("book_frame_ref")
            if isinstance(sid, str) and isinstance(st_id, str) and isinstance(tok, str) and isinstance(fref, int) and fref > 0:
                needed_keys.add((sid, tok, fref))
                sess_stations.add((sid, st_id))
        if not needed_keys:
            return {}
        out: Dict[P13Key, Dict[str, Any]] = {}
        for sid, st_id in sorted(sess_stations):
            for path in self._find_stream_files(sid, st_id):
                frames = self._read_file_frames(path)
                for key in needed_keys:
                    if key[0] == sid and key in frames:
                        out[key] = frames[key]
        return out

    def _read_file_frames(self, path: Path) -> Dict[P13Key, Dict[str, Any]]:
        if path.suffix == ".gz":
            return self._load_gz(path)
        cur = self._plain.get(path)
        if cur is None:
            cur = _P13PlainCursor()
            self._plain[path] = cur
        _update_p13_plain_cursor(path, cur)
        return cur.frames
