#!/usr/bin/env python3
"""Read-only M3 passive recording status & quality inspector (`P8-WO-20261121-REC-OPS`).

Scans `<output_root>` (including `latest_session.json` and `p13_book_stream_*.jsonl` streams)
without modifying any data files or `P13` schema. Safely skips unterminated EOF trailing
lines per `P8-T2-M7-LOGGING v1.0 §3.2 #3` while counting genuine corrupt/bad-hash lines.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.run_passive_book_recorder_daily import resolve_output_root_from_config
from src.utils.causal_utils import compute_record_sha256


def _format_bytes(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.2f} KiB"
    if num_bytes < 1024 * 1024 * 1024:
        return f"{num_bytes / (1024 * 1024):.2f} MiB"
    return f"{num_bytes / (1024 * 1024 * 1024):.2f} GiB"


def load_latest_session(output_root: Path) -> Optional[Dict[str, Any]]:
    """Read `<output_root>/latest_session.json` if present; never raises on missing/bad JSON."""
    pointer_path = output_root / "latest_session.json"
    if not pointer_path.exists():
        return None
    try:
        data = json.loads(pointer_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"raw": data}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "path": str(pointer_path)}


def _empty_bucket(*, is_session: bool = False) -> Dict[str, Any]:
    bucket: Dict[str, Any] = {
        "frames": 0,
        "corrupt_lines": 0,
        "incomplete_trailing_lines": 0,
        "gap_count": 0,
        "gap_reasons": Counter(),
        "single_side": Counter(),
        "fee_rate_provenance": Counter(),
        "fee_rate": Counter(),
        "tokens": set(),
        "yes_tokens": set(),
        "no_tokens": set(),
        "first_recorded_ts_utc": None,
        "last_recorded_ts_utc": None,
        "last_recv_ts_utc": None,
        "disk_bytes": 0,
        "files": 0,
    }
    if is_session:
        bucket["capture_modes"] = set()
        bucket["stations"] = set()
    return bucket


def _update_ts_bounds(bucket: Dict[str, Any], rec_ts: Optional[str], recv_ts: Optional[str]) -> None:
    if rec_ts:
        cur_first = bucket["first_recorded_ts_utc"]
        cur_last = bucket["last_recorded_ts_utc"]
        if cur_first is None or rec_ts < cur_first:
            bucket["first_recorded_ts_utc"] = rec_ts
        if cur_last is None or rec_ts > cur_last:
            bucket["last_recorded_ts_utc"] = rec_ts
    if recv_ts:
        cur_recv = bucket["last_recv_ts_utc"]
        if cur_recv is None or recv_ts > cur_recv:
            bucket["last_recv_ts_utc"] = recv_ts


def _finalize_bucket(bucket: Dict[str, Any]) -> Dict[str, Any]:
    frames = bucket["frames"]
    ss = bucket["single_side"]
    bid_only = int(ss.get("bid_only", 0))
    ask_only = int(ss.get("ask_only", 0))
    two_sided = int(ss.get("two_sided", 0))
    denom = frames if frames > 0 else 1
    return {
        "frames": frames,
        "corrupt_lines": bucket["corrupt_lines"],
        "incomplete_trailing_lines": bucket["incomplete_trailing_lines"],
        "files": bucket["files"],
        "disk_bytes": bucket["disk_bytes"],
        "disk_human": _format_bytes(bucket["disk_bytes"]),
        "first_recorded_ts_utc": bucket["first_recorded_ts_utc"],
        "last_recorded_ts_utc": bucket["last_recorded_ts_utc"],
        "last_recv_ts_utc": bucket["last_recv_ts_utc"],
        "gap_count": bucket["gap_count"],
        "gap_reasons": dict(sorted(bucket["gap_reasons"].items())),
        "single_side_counts": {"two_sided": two_sided, "bid_only": bid_only, "ask_only": ask_only},
        "single_side_ratios": {
            "two_sided_pct": round(100.0 * two_sided / denom, 2) if frames else 0.0,
            "bid_only_pct": round(100.0 * bid_only / denom, 2) if frames else 0.0,
            "ask_only_pct": round(100.0 * ask_only / denom, 2) if frames else 0.0,
            "single_side_total_pct": round(100.0 * (bid_only + ask_only) / denom, 2) if frames else 0.0,
        },
        "fee_rate_provenance": dict(sorted(bucket["fee_rate_provenance"].items())),
        "fee_rates": dict(sorted(bucket["fee_rate"].items())),
        "token_coverage": {
            "total": len(bucket["tokens"]),
            "YES": len(bucket["yes_tokens"]),
            "NO": len(bucket["no_tokens"]),
        },
    }


def _parse_valid_envelope(stripped: str, verify_sha256: bool) -> Dict[str, Any]:
    obj = json.loads(stripped)
    if not isinstance(obj, dict):
        raise ValueError("JSONL row is not a dict")
    if verify_sha256:
        rec_hash = obj.get("record_sha256")
        without_hash = {k: v for k, v in obj.items() if k != "record_sha256"}
        if not isinstance(rec_hash, str) or compute_record_sha256(without_hash) != rec_hash:
            raise ValueError("SHA256 mismatch")
    if not isinstance(obj.get("payload"), dict):
        raise ValueError("Missing payload dict")
    return obj


def _record_frame_into_bucket(b: Dict[str, Any], obj: Mapping[str, Any]) -> None:
    payload = obj["payload"]
    b["frames"] += 1
    if obj.get("gap_detected"):
        b["gap_count"] += 1
        b["gap_reasons"][str(obj.get("gap_reason") or "UNSPECIFIED")] += 1
    ss_raw = payload.get("single_side")
    b["single_side"][ss_raw if ss_raw in ("bid_only", "ask_only") else "two_sided"] += 1
    b["fee_rate_provenance"][str(payload.get("fee_rate_provenance") or "UNKNOWN")] += 1
    fee_val = payload.get("fee_rate")
    b["fee_rate"][f"{float(fee_val):.4g}" if fee_val is not None else "None"] += 1
    tok_id = str(payload.get("token_id") or "")
    outcome = str(payload.get("outcome") or "YES").upper()
    if tok_id:
        b["tokens"].add(tok_id)
        if outcome == "YES":
            b["yes_tokens"].add(tok_id)
        elif outcome == "NO":
            b["no_tokens"].add(tok_id)
    _update_ts_bounds(b, obj.get("recorded_ts_utc"), payload.get("recv_ts_utc"))


def _scan_jsonl_file(
    path: Path,
    output_root: Path,
    *,
    verify_sha256: bool,
    overall: Dict[str, Any],
    sessions: Dict[str, Dict[str, Any]],
    stations: Dict[str, Dict[str, Any]],
) -> None:
    file_bytes = path.stat().st_size
    overall["disk_bytes"] += file_bytes
    overall["files"] += 1
    rel_parts = path.relative_to(output_root).parts
    fb_mode = rel_parts[0] if len(rel_parts) >= 4 else None
    fb_sid = rel_parts[-2] if len(rel_parts) >= 2 else "unknown"
    fb_station = path.stem.removeprefix("p13_book_stream_") or "UNKNOWN"
    sess_seen: set[str] = set()
    st_seen: set[str] = set()

    with path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                obj = _parse_valid_envelope(stripped, verify_sha256)
            except Exception:
                # Per M7-LOGGING §3.2 #3: skip unterminated EOF lines silently without flagging corruption.
                counter_key = (
                    "incomplete_trailing_lines" if not raw_line.endswith("\n") else "corrupt_lines"
                )
                overall[counter_key] += 1
                sessions.setdefault(fb_sid, _empty_bucket(is_session=True))[counter_key] += 1
                stations.setdefault(fb_station, _empty_bucket())[counter_key] += 1
                continue

            sid = str(obj.get("session_id") or fb_sid)
            st_id = str(obj.get("station_id") or fb_station)
            cap_mode = str(obj.get("capture_mode") or fb_mode or "UNKNOWN")
            sess_b = sessions.setdefault(sid, _empty_bucket(is_session=True))
            sess_b["capture_modes"].add(cap_mode)
            sess_b["stations"].add(st_id)
            if sid not in sess_seen:
                sess_b["files"] += 1
                sess_b["disk_bytes"] += file_bytes
                sess_seen.add(sid)
            st_b = stations.setdefault(st_id, _empty_bucket())
            if st_id not in st_seen:
                st_b["files"] += 1
                st_b["disk_bytes"] += file_bytes
                st_seen.add(st_id)
            for b in (overall, sess_b, st_b):
                _record_frame_into_bucket(b, obj)

    if not sess_seen:
        sess_b = sessions.setdefault(fb_sid, _empty_bucket(is_session=True))
        if fb_mode:
            sess_b["capture_modes"].add(fb_mode)
        sess_b["stations"].add(fb_station)
        sess_b["files"] += 1
        sess_b["disk_bytes"] += file_bytes
    if not st_seen:
        st_b = stations.setdefault(fb_station, _empty_bucket())
        st_b["files"] += 1
        st_b["disk_bytes"] += file_bytes


def inspect_recording_status(output_root: Path, verify_sha256: bool = True) -> Dict[str, Any]:
    """Scan `<output_root>` read-only and aggregate session & station health metrics."""
    latest = load_latest_session(output_root)
    latest_sid = (
        latest.get("session_id") if isinstance(latest, Mapping) and "error" not in latest else None
    )
    overall = _empty_bucket()
    sessions: Dict[str, Dict[str, Any]] = {}
    stations: Dict[str, Dict[str, Any]] = {}
    jsonl_paths = sorted(output_root.rglob("p13_book_stream_*.jsonl")) if output_root.exists() else []
    for path in jsonl_paths:
        _scan_jsonl_file(
            path, output_root, verify_sha256=verify_sha256,
            overall=overall, sessions=sessions, stations=stations,
        )

    session_list = []
    for sid, sb in sorted(sessions.items(), key=lambda item: (item[1]["first_recorded_ts_utc"] or "", item[0])):
        final = _finalize_bucket(sb)
        final["session_id"] = sid
        final["is_latest_session"] = sid == latest_sid
        final["capture_modes"] = sorted(sb["capture_modes"])
        final["stations"] = sorted(sb["stations"])
        session_list.append(final)

    return {
        "output_root": str(output_root),
        "output_root_exists": output_root.exists(),
        "sha256_verified": verify_sha256,
        "latest_session": latest,
        "overall": _finalize_bucket(overall),
        "sessions": session_list,
        "stations": {st_id: _finalize_bucket(sb) for st_id, sb in sorted(stations.items())},
    }


def _format_header_and_overall(summary: Mapping[str, Any]) -> List[str]:
    lines = [f"=== M3 Passive Book Recorder Status ({summary['output_root']}) ==="]
    if not summary["output_root_exists"]:
        lines.append("Output root does not exist yet (no recordings).")
    latest = summary.get("latest_session")
    if latest is None:
        lines.append("Latest Session Pointer : (none — latest_session.json not present)")
    elif "error" in latest:
        lines.append(f"Latest Session Pointer : ERROR ({latest['error']})")
    else:
        lines.append(
            f"Latest Session Pointer : session_id={latest.get('session_id')} started_at={latest.get('started_at_utc')} "
            f"next_cutover={latest.get('next_cutover_utc')} child_pid={latest.get('child_pid')} "
            f"supervisor_pid={latest.get('supervisor_pid')}"
        )
    ov = summary["overall"]
    cov, ss_c, ss_r = ov["token_coverage"], ov["single_side_counts"], ov["single_side_ratios"]
    lines.extend([
        f"Overall                : files={ov['files']} frames={ov['frames']} corrupt_lines={ov['corrupt_lines']} "
        f"incomplete_eof={ov['incomplete_trailing_lines']} disk={ov['disk_human']} ({ov['disk_bytes']} B) gaps={ov['gap_count']}",
        f"Range & Tokens         : {ov['first_recorded_ts_utc']} .. {ov['last_recorded_ts_utc']} | "
        f"tokens={cov['total']} (YES={cov['YES']}, NO={cov['NO']})",
        f"Single-Side Mix        : two_sided={ss_c['two_sided']} ({ss_r['two_sided_pct']}%), "
        f"bid_only={ss_c['bid_only']} ({ss_r['bid_only_pct']}%), ask_only={ss_c['ask_only']} ({ss_r['ask_only_pct']}%) "
        f"[single_side_total={ss_r['single_side_total_pct']}%]",
        f"Fee Provenance / Rates : provenance={ov['fee_rate_provenance']} | rates={ov['fee_rates']}",
    ])
    return lines


def format_status_report(summary: Mapping[str, Any]) -> str:
    """Format a concise human-readable CLI status report."""
    lines = _format_header_and_overall(summary)
    sessions = summary["sessions"]
    lines.append(f"\n--- Sessions ({len(sessions)}) ---")
    if not sessions:
        lines.append("  (no sessions found)")
    for s in sessions:
        mark = "*ACTIVE " if s["is_latest_session"] else ""
        lines.append(
            f"  {mark}{s['session_id']} | mode={','.join(s['capture_modes'])} | stations={','.join(s['stations'])} | "
            f"frames={s['frames']} gaps={s['gap_count']} tokens={s['token_coverage']['total']} disk={s['disk_human']} | "
            f"{s['first_recorded_ts_utc']} -> {s['last_recorded_ts_utc']}"
        )
    stations = summary["stations"]
    lines.append(f"\n--- Stations ({len(stations)}) ---")
    if not stations:
        lines.append("  (no station streams found)")
    for st_id, st in stations.items():
        st_ss, st_sr, st_cov = st["single_side_counts"], st["single_side_ratios"], st["token_coverage"]
        lines.append(
            f"  {st_id}: frames={st['frames']} last_ts={st['last_recorded_ts_utc']} gaps={st['gap_count']} "
            f"single_side={{bid_only:{st_ss['bid_only']}({st_sr['bid_only_pct']}%), ask_only:{st_ss['ask_only']}({st_sr['ask_only_pct']}%)}} "
            f"fee_prov={st['fee_rate_provenance']} tokens={st_cov['total']}(Y={st_cov['YES']}/N={st_cov['NO']}) disk={st['disk_human']}"
        )
    return "\n".join(lines)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only status inspector for M3 P13 passive book recordings")
    parser.add_argument("--output-root", type=Path, default=None, help="Recording output root")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/passive_book_recorder.example.yaml"),
        help="Optional YAML config used to locate recording.output_root when --output-root is omitted",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--no-verify-sha256", action="store_true", help="Skip SHA256 verification")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    output_root = args.output_root if args.output_root is not None else resolve_output_root_from_config(args.config)
    summary = inspect_recording_status(output_root=output_root, verify_sha256=not args.no_verify_sha256)
    print(json.dumps(summary, indent=2, ensure_ascii=False) if args.json else format_status_report(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
