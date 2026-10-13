"""
Unit tests for HistoricalBacktestEngine (Phase 2 Task 07 - Fix Ticket 02 / Issue #102).
"""

from decimal import Decimal
import pytest

from src.simulation.backtest_engine import BacktestConfig, HistoricalBacktestEngine


def test_historical_backtest_initialization():
    """Test engine initialization and components wiring."""
    engine = HistoricalBacktestEngine()
    assert engine.bankroll_manager.total_balance == Decimal("10000.000000")
    assert engine.model_registry is not None
    assert engine.climate_floor_registry is not None
    assert engine.market_maker is not None


def test_historical_backtest_fast_run():
    """Test running a fast multi-day backtest across sample stations."""
    cfg = BacktestConfig(
        initial_bankroll=10000.0,
        min_reprice_edge=0.02,
        kelly_fraction=0.25,
        max_single_bet_pct=0.05,
    )
    engine = HistoricalBacktestEngine(config=cfg)

    # Run for 7 days on 2 stations
    report = engine.run_backtest(
        stations=["KORD", "KLGA"],
        start_date="2019-01-01",
        end_date="2019-01-07",
    )

    assert report.trading_days == 7
    assert report.start_date == "2019-01-01"
    assert report.end_date == "2019-01-07"
    assert report.initial_bankroll == 10000.0
    assert report.final_bankroll > 0.0
    assert report.zero_non_physical_violations == 0
    assert report.capital_conservation_passed is True
    assert len(report.daily_records) == 7

    # Check serialization
    d = report.to_dict()
    assert d["evaluation_type"] == "quantitative_backtest"
    assert "annualized_sharpe" in d
    assert "max_drawdown" in d
    assert "profit_factor" in d
