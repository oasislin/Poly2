"""
Unit and Integration tests for Paper Trading Runner CLI (Phase 2 Task 07 - Ticket 05 / Issue #99).
Verifies:
- Active 10 station multi-station 48h concurrent simulation.
- Zero non-physical orders gatekeeping.
- Capital conservation and solvency without drift.
- Sharpe Ratio > 2.0 and Maximum Drawdown < 15%.
- Structured JSON report output.
"""

from decimal import Decimal
import json
from pathlib import Path
import pytest

from scripts.run_paper_trading import run_simulation, PaperRunnerConfig
from src.data_processing.constants import ACTIVE_10_STATIONS


class TestPaperTradingRunner:
    def test_paper_trading_48h_active_10_stations(self, tmp_path):
        report_path = tmp_path / "paper_trading_48h_report.json"
        events_path = tmp_path / "paper_trading_events.jsonl"

        config = PaperRunnerConfig(
            duration_hours=48.0,
            step_minutes=60,
            stations=list(ACTIVE_10_STATIONS),
            initial_capital=Decimal("20000.000000"),
            output_report_path=str(report_path),
            events_log_path=str(events_path),
        )

        report = run_simulation(config)

        # 1. Verification of Execution Core Metrics
        assert report.initial_capital == Decimal("20000.000000")
        assert report.final_nav >= report.initial_capital  # Non-negative return in benchmark scenario
        assert report.total_return_pct >= 0.0
        assert report.max_drawdown_pct < 15.0
        assert report.sharpe_ratio > 2.0

        # 2. Hard Regulatory Guardrails
        assert report.zero_non_physical_orders_violated == 0
        assert report.capital_conservation_passed is True
        assert report.total_trades_count > 0

        # 3. Report file existence and structure
        assert report_path.exists()
        with open(report_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        assert "initial_capital" in data
        assert "final_nav" in data
        assert "total_return_pct" in data
        assert "sharpe_ratio" in data
        assert "capital_conservation_passed" in data
        assert data["zero_non_physical_orders_violated"] == 0

        # 4. Events log file exists and contains valid JSON lines
        assert events_path.exists()
        with open(events_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        assert len(lines) > 0
        first_event = json.loads(lines[0])
        assert "event_type" in first_event
        assert "timestamp" in first_event
