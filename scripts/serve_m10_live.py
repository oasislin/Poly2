#!/usr/bin/env python3
"""Strictly loopback-only, read-only local HTTP live-refresh server for `M10 v1`."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
from typing import Any, Dict, Optional, Sequence
from urllib.parse import parse_qs, urlparse

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.execution.clob_gateway import DEFAULT_GATEWAY_CONFIG_PATH, ExecutionMode
from src.ui.m10_live_cache import IncrementalAuditCache, render_live_decision_detail_html, render_live_m10_html

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def validate_loopback_host(host: str) -> str:
    """Fail-closed loopback validation: refuse non-loopback bind addresses."""
    norm = host.strip().lower()
    if norm not in _LOOPBACK_HOSTS:
        raise ValueError(f"Refusing non-loopback host {host!r}; only 127.0.0.1 / localhost / ::1 allowed")
    return host.strip()


def _parse_int_param(qs: Dict[str, list[str]], key: str, default: int, *, min_v: int, max_v: int) -> int:
    raw = qs.get(key, [None])[0]
    if raw is None:
        return default
    try:
        return max(min_v, min(max_v, int(raw)))
    except Exception:
        return default


def _parse_enum_param(qs: Dict[str, list[str]], key: str, default: str, allowed: frozenset[str]) -> str:
    raw = str(qs.get(key, [default])[0] or default).strip()
    return raw if raw in allowed else default


def _serve_query_kwargs(qs: Dict[str, list[str]], default_refresh: int, default_limit: int) -> Dict[str, Any]:
    only_act_raw = qs.get("only_actionable", [None])[0]
    action_raw = qs.get("action", [None])[0]
    if action_raw in ("p3", "filled", "actionable", "all"):
        action_filter: Optional[str] = action_raw
        only_act = action_raw != "all"
    elif only_act_raw == "0":
        action_filter, only_act = "all", False
    else:
        action_filter, only_act = "p3", True
    tz_val = _parse_enum_param(qs, "tz", "both", frozenset({"both", "bjt", "station"}))
    return {
        "refresh_sec": _parse_int_param(qs, "refresh", default_refresh, min_v=0, max_v=3600),
        "limit": _parse_int_param(qs, "limit", default_limit, min_v=10, max_v=500),
        "page": _parse_int_param(qs, "page", 1, min_v=1, max_v=9999),
        "only_actionable": only_act,
        "action_filter": action_filter,
        "period": _parse_enum_param(qs, "period", "today", frozenset({"today", "week", "month", "year", "all"})),
        "station_id": qs.get("station", ["ALL"])[0],
        "target_type": _parse_enum_param(qs, "target_type", "ALL", frozenset({"ALL", "TMAX", "TMIN"})),
        "utc_date_str": qs.get("date", ["ALL"])[0],
        "tz_mode": tz_val,
    }


class _BaseReadonlyM10Handler(BaseHTTPRequestHandler):
    cache: IncrementalAuditCache
    lock: threading.Lock
    safety_config: Path
    alerts_status: Optional[Path]
    default_refresh_sec: int
    default_limit: int

    def _reject_write_method(self) -> None:
        self.send_error(405, "Method Not Allowed: M10 live monitor is strictly read-only")

    def do_POST(self) -> None:  # noqa: N802
        self._reject_write_method()

    def do_PUT(self) -> None:  # noqa: N802
        self._reject_write_method()

    def do_DELETE(self) -> None:  # noqa: N802
        self._reject_write_method()

    def do_PATCH(self) -> None:  # noqa: N802
        self._reject_write_method()

    def _serve(self, *, send_body: bool) -> None:
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        kwargs = _serve_query_kwargs(qs, self.default_refresh_sec, self.default_limit)
        if parsed.path in ("/", "/index.html"):
            with self.lock:
                html_text = render_live_m10_html(
                    self.cache, safety_config_path=self.safety_config, alerts_status_path=self.alerts_status, **kwargs,
                )
        elif parsed.path == "/decision":
            dec_id = str(qs.get("id", [""])[0] or "").strip()
            back_q = {k: str(v[0]) for k, v in qs.items() if k != "id" and v}
            with self.lock:
                html_text = render_live_decision_detail_html(
                    self.cache, decision_id=dec_id, safety_config_path=self.safety_config,
                    alerts_status_path=self.alerts_status, utc_date_str=kwargs["utc_date_str"],
                    period=kwargs["period"], station_id=kwargs["station_id"],
                    target_type=kwargs["target_type"], tz_mode=kwargs["tz_mode"], back_query=back_q,
                )
        else:
            self.send_error(404, "Not Found")
            return
        body = html_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if send_body:
            self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        self._serve(send_body=True)

    def do_HEAD(self) -> None:  # noqa: N802
        self._serve(send_body=False)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def make_handler_cls(
    *,
    cache: IncrementalAuditCache,
    lock: threading.Lock,
    safety_config: Path,
    alerts_status: Optional[Path],
    default_refresh_sec: int,
    default_limit: int,
):
    """Create read-only HTTP request handler class bound to shared incremental cache."""

    class _BoundM10Handler(_BaseReadonlyM10Handler):
        pass

    _BoundM10Handler.cache = cache
    _BoundM10Handler.lock = lock
    _BoundM10Handler.safety_config = safety_config
    _BoundM10Handler.alerts_status = alerts_status
    _BoundM10Handler.default_refresh_sec = default_refresh_sec
    _BoundM10Handler.default_limit = default_limit
    return _BoundM10Handler


def create_m10_live_server(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    audit_root: Path = Path("data/audit_logs"),
    execution_mode: ExecutionMode = "PAPER",
    safety_config: Path = DEFAULT_GATEWAY_CONFIG_PATH,
    alerts_status: Optional[Path] = None,
    p13_root: Optional[Path] = None,
    refresh_sec: int = 15,
    default_limit: int = 50,
    p1_window_size: int = 500,
) -> ThreadingHTTPServer:
    """Create configured loopback-only `ThreadingHTTPServer` for M10."""
    safe_host = validate_loopback_host(host)
    cache = IncrementalAuditCache(
        audit_root=audit_root, execution_mode=execution_mode, p1_window_size=p1_window_size, p13_root=p13_root
    )
    handler_cls = make_handler_cls(
        cache=cache,
        lock=threading.Lock(),
        safety_config=safety_config,
        alerts_status=alerts_status,
        default_refresh_sec=refresh_sec,
        default_limit=default_limit,
    )
    return ThreadingHTTPServer((safe_host, int(port)), handler_cls)


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Start strictly loopback-only read-only M10 live monitor.")
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--audit-root", type=Path, default=_REPO_ROOT / "data" / "audit_logs")
    parser.add_argument("--execution-mode", choices=("PAPER", "LIVE"), default="PAPER")
    parser.add_argument("--safety-config", type=Path, default=DEFAULT_GATEWAY_CONFIG_PATH)
    parser.add_argument("--alerts-status", type=Path, default=None)
    parser.add_argument("--p13-root", type=Path, default=None)
    parser.add_argument("--refresh-sec", type=int, default=15)
    parser.add_argument("--default-limit", type=int, default=50)
    parser.add_argument("--p1-window-size", type=int, default=500)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    default_alerts = _REPO_ROOT / "data" / "alerts" / "watchdog_status.json"
    default_p13 = _REPO_ROOT / "data" / "market_recordings"
    alerts = args.alerts_status if args.alerts_status is not None else (default_alerts if default_alerts.exists() else None)
    p13_root = args.p13_root if args.p13_root is not None else (default_p13 if default_p13.exists() else None)
    server = create_m10_live_server(
        host=args.host,
        port=args.port,
        audit_root=args.audit_root,
        execution_mode=args.execution_mode,
        safety_config=args.safety_config,
        alerts_status=alerts,
        p13_root=p13_root,
        refresh_sec=args.refresh_sec,
        default_limit=args.default_limit,
        p1_window_size=args.p1_window_size,
    )
    addr = server.server_address
    print(f"M10 live monitor serving at http://{addr[0]}:{addr[1]}/ (read-only, loopback-only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
