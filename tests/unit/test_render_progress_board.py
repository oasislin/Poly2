"""Tests for scripts/render_progress_board.py single-source parser & offline HTML generator."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.render_progress_board import (
    ALGORITHM_PROTECTED_IDS,
    EXPECTED_MODULE_IDS,
    LedgerValidationError,
    load_task_ledger,
    main,
    render_html,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
REAL_LEDGER = REPO_ROOT / "docs/audit/P8-PROJECT-TASKS_全量任务分解台账_v1.0.md"
REAL_BOARD = REPO_ROOT / "docs/audit/progress_board.html"


def test_real_ledger_covers_all_modules_slices_and_guardrails() -> None:
    data = load_task_ledger(REAL_LEDGER)
    assert tuple(m["id"] for m in data["modules"]) == EXPECTED_MODULE_IDS
    assert len(data["tasks"]) == 29
    assert {t["slice"] for t in data["tasks"]} == {"切片 1", "切片 2", "切片 3", "切片 4"}

    by_id = {t["id"]: t for t in data["tasks"]}
    assert by_id["S3-05b"]["status"] == "PENDING_APPROVAL"
    assert "S3-05b" in by_id["S3-11"]["depends_on"]
    assert "S3-05b" in by_id["S3-12"]["depends_on"]
    assert "风险参数面板" in by_id["S3-10"]["acceptance"]
    for tid in ("S3-01", "S3-02", "S3-03", "S3-04", "S3-05", "S3-06", "S3-07", "S2-03", "S2-04", "S2-05"):
        assert by_id[tid]["status"] == "DONE"
    for tid in ALGORITHM_PROTECTED_IDS:
        assert by_id[tid]["acceptance"] != "待架构侧供给"

    assert by_id["S2-01"]["status"] == "READY_TO_LAUNCH"
    assert "待用户按开关" in by_id["S2-01"]["dependencies_label"]
    assert by_id["S2-07"]["status"] == "READY"
    assert "2019-SEALED-003" in by_id["S3-03"]["acceptance"]
    assert "2019-12-30T23:55:00Z" in by_id["S3-03"]["acceptance"]
    assert by_id["S3-08"]["status"] == "BLOCKED"
    assert by_id["S3-13"]["status"] == "PLANNED"

    assert len(data["mainline_reviews"]) == 1
    assert data["mainline_reviews"][0]["date"] == "2026-11-19"
    assert "算法四单设计" in data["mainline_reviews"][0]["priority"]

    # Zero external CDN or network asset dependencies inside rendered HTML
    html_text = render_html(data)
    assert "主线审视记录" in html_text
    assert "<script src=" not in html_text
    assert "<link rel=\"stylesheet\"" not in html_text
    assert "cdn." not in html_text.lower()


def test_real_board_matches_ledger_via_check_cli() -> None:
    rc = main(["--ledger", str(REAL_LEDGER), "--output", str(REAL_BOARD), "--check"])
    assert rc == 0


def test_cycle_detection_and_algo_guardrail(tmp_path: Path) -> None:
    raw = REAL_LEDGER.read_text(encoding="utf-8")

    # 1. Blocked algorithm task without placeholder must fail unless --allow-arch-supplied
    tampered_algo = raw.replace(
        "| 假盘 `M_now` 与结算口径逐帧一致 | `DONE` |",
        "| 擅自拟定阈值 | `BLOCKED` |",
        1,
    )
    p1 = tmp_path / "tampered_algo.md"
    p1.write_text(tampered_algo, encoding="utf-8")
    with pytest.raises(LedgerValidationError, match="待架构侧供给"):
        load_task_ledger(p1)

    # 2. Dependency cycle S1-01 -> S1-03 -> S1-01 must fail
    cycled = raw.replace("| 无 | 五组调研实证归档", "| `S1-03` | 五组调研实证归档", 1)
    p2 = tmp_path / "cycled.md"
    p2.write_text(cycled, encoding="utf-8")
    with pytest.raises(LedgerValidationError, match="Cycle detected"):
        load_task_ledger(p2)


def test_check_fails_when_html_stale(tmp_path: Path) -> None:
    stale_html = tmp_path / "board.html"
    stale_html.write_text("<html>stale</html>", encoding="utf-8")
    rc = main(["--ledger", str(REAL_LEDGER), "--output", str(stale_html), "--check"])
    assert rc == 1
