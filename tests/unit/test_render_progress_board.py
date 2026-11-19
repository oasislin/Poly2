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
    assert len(data["tasks"]) == 26
    assert {t["slice"] for t in data["tasks"]} == {"切片 1", "切片 2", "切片 3", "切片 4"}

    by_id = {t["id"]: t for t in data["tasks"]}
    for tid in ALGORITHM_PROTECTED_IDS:
        assert by_id[tid]["acceptance"] == "待架构侧供给"
        assert "阻塞于架构侧" in by_id[tid]["dependencies_label"]
        assert by_id[tid]["status"] == "BLOCKED"

    assert by_id["S2-01"]["status"] == "PENDING_APPROVAL"
    assert "待用户批准" in by_id["S2-01"]["dependencies_label"]
    assert by_id["S2-05"]["status"] == "DONE"

    # Zero external CDN or network asset dependencies inside rendered HTML
    html_text = render_html(data)
    assert "<script src=" not in html_text
    assert "<link rel=\"stylesheet\"" not in html_text
    assert "cdn." not in html_text.lower()


def test_real_board_matches_ledger_via_check_cli() -> None:
    rc = main(["--ledger", str(REAL_LEDGER), "--output", str(REAL_BOARD), "--check"])
    assert rc == 0


def test_cycle_detection_and_algo_guardrail(tmp_path: Path) -> None:
    raw = REAL_LEDGER.read_text(encoding="utf-8")

    # 1. Tampering S3-01 acceptance must fail unless --allow-arch-supplied
    tampered_algo = raw.replace("| `S1-06, S2-03, 阻塞于架构侧（待供给算法验收标准）` | 待架构侧供给 | `BLOCKED` |", "| `S1-06, S2-03, 阻塞于架构侧（待供给算法验收标准）` | 擅自拟定阈值 | `BLOCKED` |", 1)
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
