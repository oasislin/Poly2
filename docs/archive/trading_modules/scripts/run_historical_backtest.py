#!/usr/bin/env python3
"""
run_historical_backtest.py: Production Historical Quantitative Backtest Runner.
Part of Phase 2 Task 07 Tier 2 Quantitative Architecture (Fix Ticket 03 / Issue #103).

Usage:
    python scripts/run_historical_backtest.py --output-report data/reports/historical_backtest_2019_report.json
    python scripts/run_historical_backtest.py --fast  # Quick 30-day run
"""

import argparse
import json
import logging
from pathlib import Path
import sys
from typing import List, Optional

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.data_processing.constants import ACTIVE_10_STATIONS
from src.simulation.backtest_engine import BacktestConfig, HistoricalBacktestEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("run_historical_backtest")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run Phase 2 Tier 2 Out-of-Sample Quantitative Backtest (2019 Holdout)."
    )
    parser.add_argument(
        "--stations",
        nargs="+",
        default=sorted(list(ACTIVE_10_STATIONS)),
        help="List of station IDs to evaluate (default: Active 10)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default="2019-01-01",
        help="Start date YYYY-MM-DD (default: 2019-01-01)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default="2019-12-31",
        help="End date YYYY-MM-DD (default: 2019-12-31)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Optional max number of trading days to simulate",
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Fast mode: test first 30 days for quick verification",
    )
    parser.add_argument(
        "--initial-bankroll",
        type=float,
        default=10000.0,
        help="Starting capital in USDC (default: 10000.0)",
    )
    parser.add_argument(
        "--kelly-fraction",
        type=float,
        default=0.25,
        help="Fractional Kelly multiplier (default: 0.25 / Quarter-Kelly)",
    )
    parser.add_argument(
        "--min-edge",
        type=float,
        default=0.03,
        help="Minimum required expected edge (default: 0.03 / 3%)",
    )
    parser.add_argument(
        "--output-report",
        type=str,
        default="data/reports/historical_backtest_2019_report.json",
        help="Path to save output JSON report",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    max_days = 30 if args.fast else args.days

    logger.info("================================================================================")
    logger.info("  Phase 2 Task 07: Tier 2 High-Fidelity 2019 Quantitative Backtest Runner")
    logger.info("================================================================================")
    logger.info(f"Target Stations     : {args.stations}")
    logger.info(f"Date Range          : {args.start_date} to {args.end_date} (Max Days: {max_days or 'Full Year'})")
    logger.info(f"Initial Bankroll    : {args.initial_bankroll:,.2f} USDC")
    logger.info(f"Kelly Multiplier    : {args.kelly_fraction}x")
    logger.info(f"Minimum Edge        : {args.min_edge * 100:.1f}%")
    logger.info("--------------------------------------------------------------------------------")

    config = BacktestConfig(
        initial_bankroll=args.initial_bankroll,
        min_reprice_edge=args.min_edge,
        kelly_fraction=args.kelly_fraction,
    )

    engine = HistoricalBacktestEngine(config=config)
    report = engine.run_backtest(
        stations=args.stations,
        start_date=args.start_date,
        end_date=args.end_date,
        max_days=max_days,
    )

    # Save structured JSON report
    out_path = Path(args.output_report)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)
    logger.info(f"Historical backtest report saved to: {out_path.resolve()}")

    # Print Scorecard
    print("\n" + "=" * 80)
    print("  PHASE 2 TIER 2 QUANTITATIVE BACKTEST SCORECARD (2019 OOS)")
    print("=" * 80)
    print(f"  Period                     : {report.start_date} to {report.end_date} ({report.trading_days} days)")
    print(f"  Initial Bankroll           : ${report.initial_bankroll:,.2f} USDC")
    print(f"  Final Bankroll             : ${report.final_bankroll:,.2f} USDC")
    print(f"  Total Net PnL              : ${report.total_pnl:,.2f} USDC ({report.total_return_pct:+.2f}%)")
    print(f"  Annualized Sharpe (sqrt365): {report.annualized_sharpe:.2f}")
    print(f"  Maximum Drawdown (MDD)     : {report.max_drawdown * 100:.2f}%")
    print(f"  Contract Trades Count      : {report.total_trades} (Win: {report.profitable_trades}, Win Rate: {report.win_rate * 100:.1f}%)")
    print(f"  Profit Factor              : {report.profit_factor:.2f}")
    print(f"  Average Trade EV           : {report.average_ev * 100:.2f}%")
    print(f"  Zero Non-physical Orders   : {'PASS (0 violations)' if report.zero_non_physical_violations == 0 else f'FAIL ({report.zero_non_physical_violations} violations)'}")
    print(f"  Decimal Capital Conserved  : {'PASS' if report.capital_conservation_passed else 'FAIL'}")
    print("=" * 80 + "\n")

    # Evaluate Acceptance Gate Criteria
    failures = []
    if report.annualized_sharpe < 1.5:
        failures.append(f"Annualized Sharpe ratio ({report.annualized_sharpe:.2f}) < threshold 1.5")
    if report.max_drawdown > 0.15:
        failures.append(f"Maximum Drawdown ({report.max_drawdown * 100:.2f}%) > threshold 15.0%")
    if report.total_pnl <= 0.0:
        failures.append(f"Total Net PnL (${report.total_pnl:.2f}) <= 0.0")
    if report.zero_non_physical_violations > 0:
        failures.append(f"Zero non-physical orders violated: {report.zero_non_physical_violations}")
    if not report.capital_conservation_passed:
        failures.append("Capital conservation failed (active locked funds remaining)")

    if failures:
        logger.error("❌ QUANTITATIVE ACCEPTANCE GATES FAILED:")
        for fail in failures:
            logger.error(f"  - {fail}")
        return 1

    logger.info("✅ ALL QUANTITATIVE ACCEPTANCE GATES PASSED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
