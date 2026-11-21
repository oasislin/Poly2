"""Async M7 Append-Only JSONL Audit Logger (`P1 / P3 / P12 / P17 / P19`).

Anchors:
- `P8-T2-M7-LOGGING v1.1 §1 & §3.1`: physical folder isolation `<root>/<execution_mode>/<YYYY-MM-DD>/p*.jsonl`,
  non-blocking background writer queue, zero feedback writeback into M1/M2/M6/M8.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import queue
import threading
from typing import Dict, Literal, Optional, Tuple

from src.audit.p19_events import CapitalEventLog, ExecutionMode
from src.data_acquisition.settlement_metar_stream import CoverageLedgerEntry
from src.decision.engine import ScanDecisionEvent
from src.execution.executor import ExecutionAttemptLog
from src.prediction.forecast_distribution_engine import ForecastDistributionSnapshotV11
from src.utils.causal_utils import ensure_utc_datetime

AuditStreamName = Literal["p1", "p3", "p12", "p17", "p19"]
STREAM_FILENAMES: Dict[AuditStreamName, str] = {
    "p1": "p1_scan_decisions.jsonl",
    "p3": "p3_execution_attempts.jsonl",
    "p12": "p12_weather_coverage.jsonl",
    "p17": "p17_forecast_snapshots.jsonl",
    "p19": "p19_capital_events.jsonl",
}


@dataclass(frozen=True)
class AuditWriteStats:
    """Snapshot of asynchronously flushed M7 audit counts and writer errors."""

    written_by_stream: Dict[str, int]
    error_count: int
    last_error: Optional[str]


class AsyncAuditLogger:
    """Non-blocking thread-backed append-only JSONL writer partitioned by mode and UTC date."""

    def __init__(self, root_dir: Path, *, execution_mode: ExecutionMode) -> None:
        if execution_mode not in ("PAPER", "LIVE"):
            raise ValueError(f"Unsupported execution_mode={execution_mode!r}")
        self.root_dir = Path(root_dir)
        self.execution_mode: ExecutionMode = execution_mode
        self._queue: queue.Queue[Optional[Tuple[AuditStreamName, str, str, Optional[threading.Event]]]] = queue.Queue()
        self._lock = threading.Lock()
        self._written: Dict[str, int] = {k: 0 for k in STREAM_FILENAMES}
        self._error_count = 0
        self._last_error: Optional[str] = None
        self._closed = False
        self._thread = threading.Thread(target=self._worker_loop, name=f"m7-audit-{execution_mode}", daemon=True)
        self._thread.start()

    def _target_path(self, stream: AuditStreamName, utc_date_str: str) -> Path:
        return self.root_dir / self.execution_mode / utc_date_str / STREAM_FILENAMES[stream]

    def _append_line(self, stream: AuditStreamName, utc_date_str: str, line: str) -> None:
        path = self._target_path(stream, utc_date_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        with self._lock:
            self._written[stream] = self._written.get(stream, 0) + 1

    def _worker_loop(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is None:
                    return
                stream, utc_date_str, line, marker = item
                if marker is not None:
                    marker.set()
                    continue
                self._append_line(stream, utc_date_str, line)
            except Exception as exc:  # pragma: no cover - defensive writer guard
                with self._lock:
                    self._error_count += 1
                    self._last_error = f"{type(exc).__name__}: {exc}"
            finally:
                self._queue.task_done()

    def _enqueue(self, stream: AuditStreamName, ts: datetime, mode: ExecutionMode, line: str) -> None:
        if self._closed:
            raise RuntimeError("Cannot log to a closed AsyncAuditLogger")
        if mode != self.execution_mode:
            raise ValueError(f"Mode isolation breach: logger={self.execution_mode!r}, event={mode!r}")
        utc_date_str = ensure_utc_datetime(ts, field_name="audit.event_ts_utc").date().isoformat()
        self._queue.put((stream, utc_date_str, line, None))

    def log_p1_scan_decision(self, event: ScanDecisionEvent) -> None:
        """Enqueue a `P1 ScanDecisionEvent` asynchronously."""
        self._enqueue("p1", event.scan_ts_utc, event.execution_mode, event.to_json_line())

    def log_p3_execution_attempt(self, attempt: ExecutionAttemptLog) -> None:
        """Enqueue a `P3 ExecutionAttemptLog` asynchronously."""
        self._enqueue("p3", attempt.decision_ts_utc, attempt.execution_mode, attempt.to_json_line())

    def log_p12_coverage_ledger(self, ledger: CoverageLedgerEntry) -> None:
        """Enqueue a `P12 CoverageLedgerEntry` asynchronously."""
        self._enqueue("p12", ledger.run_ts_utc, ledger.execution_mode, ledger.to_json_line())

    def log_p17_forecast_snapshot(
        self,
        snapshot: ForecastDistributionSnapshotV11,
        *,
        session_id: str,
        config_hash: str,
    ) -> None:
        """Enqueue a `P17 ForecastSnapshotLog` derived from `P5 v1.1` asynchronously."""
        line = snapshot.to_p17_json_line(
            session_id=session_id,
            execution_mode=self.execution_mode,
            config_hash=config_hash,
        )
        self._enqueue("p17", snapshot.issue_ts_utc, self.execution_mode, line)

    def log_p19_capital_event(self, event: CapitalEventLog) -> None:
        """Enqueue a `P19 CapitalEventLog` asynchronously."""
        self._enqueue("p19", event.event_ts_utc, event.execution_mode, event.to_json_line())

    def flush(self, timeout_sec: float = 5.0) -> None:
        """Wait until all currently queued JSONL lines have been flushed to disk."""
        if self._closed:
            return
        marker = threading.Event()
        self._queue.put(("p1", "1970-01-01", "", marker))
        if not marker.wait(timeout=timeout_sec):
            raise TimeoutError(f"AsyncAuditLogger flush timed out after {timeout_sec}s")

    def close(self, timeout_sec: float = 5.0) -> None:
        """Flush pending records and stop the background writer thread cleanly."""
        if self._closed:
            return
        self.flush(timeout_sec=timeout_sec)
        self._closed = True
        self._queue.put(None)
        self._thread.join(timeout=timeout_sec)

    def stats(self) -> AuditWriteStats:
        """Return written counts and writer error status."""
        with self._lock:
            return AuditWriteStats(
                written_by_stream=dict(self._written),
                error_count=self._error_count,
                last_error=self._last_error,
            )

    def __enter__(self) -> "AsyncAuditLogger":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


__all__ = [
    "AsyncAuditLogger",
    "AuditStreamName",
    "AuditWriteStats",
    "STREAM_FILENAMES",
]
