#!/usr/bin/env python3
"""
Active 10 Stations 48-Hour Paper Trading Simulation Runner (Phase 2 Task 07 - Ticket 05 / Issue #99).
Executes high-fidelity concurrent paper trading across Active 10 stations,
tracks NAV trajectories, enforces zero non-physical orders and capital conservation,
and exports comprehensive JSON audit reports.
"""

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json
import logging
import math
import os
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Ensure project root in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.bankroll.bankroll_manager import BankrollManager
from src.data_processing.constants import ACTIVE_10_STATIONS
from src.execution.clob_client import MockCLOBClient
from src.pricing.ev_engine import OrderBookLevel, OrderBookSnapshot
from src.risk.central_arbiter import CentralExceptionArbiter
from src.risk.two_dimensional_risk import TwoDimensionalRiskController
from src.simulation.clock import SimulationClock, SimulationClockMode
from src.simulation.metrics import SimulationMetricsCalculator, SimulationMetricsReport
from src.simulation.models import PaperPosition
from src.simulation.paper_engine import PaperSimulationConfig, PaperTradingSimulator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("PaperTradingRunner")

# Baseline representative temperatures (°F) for Active 10 stations in autumn
STATION_BASE_TEMPS: Dict[str, float] = {
    "KORD": 68.0,  # Chicago O'Hare
    "KLGA": 70.0,  # New York LaGuardia
    "KATL": 74.0,  # Atlanta Hartsfield-Jackson
    "KDAL": 78.0,  # Dallas Love Field
    "KSEA": 62.0,  # Seattle-Tacoma
    "KLAX": 73.0,  # Los Angeles
    "KHOU": 80.0,  # Houston Hobby
    "KMIA": 84.0,  # Miami International
    "KSFO": 65.0,  # San Francisco
    "KAUS": 79.0,  # Austin-Bergstrom
}


@dataclass
class PaperRunnerConfig:
    """Simulation runner configuration parameters."""
    duration_hours: float = 48.0
    step_minutes: int = 60
    stations: List[str] = field(default_factory=lambda: list(ACTIVE_10_STATIONS))
    initial_capital: Decimal = Decimal("20000.000000")
    output_report_path: str = "data/reports/paper_trading_48h_report.json"
    events_log_path: Optional[str] = "data/reports/paper_trading_events.jsonl"
    fractional_multiplier: Decimal = Decimal("0.5")  # Half-Kelly
    min_edge: float = 0.02


def setup_market_definitions(station_id: str, day_str: str) -> Dict[str, Any]:
    """Define 4-bin discrete market structure around base station climate."""
    base_t = STATION_BASE_TEMPS.get(station_id, 70.0)
    market_id = f"{station_id}-{day_str}-TMAX"

    bin_labels = {
        0: f"<={int(base_t - 3)}°F",
        1: f"{int(base_t - 2)}-{int(base_t)}°F",
        2: f"{int(base_t + 1)}-{int(base_t + 3)}°F",
        3: f">={int(base_t + 4)}°F",
    }
    bin_centers = {
        0: base_t - 5.0,
        1: base_t - 1.0,
        2: base_t + 2.0,
        3: base_t + 5.0,
    }
    return {
        "market_id": market_id,
        "base_t": base_t,
        "bin_labels": bin_labels,
        "bin_centers": bin_centers,
    }


def run_simulation(config: PaperRunnerConfig) -> SimulationMetricsReport:
    """
    Execute multi-station concurrent paper trading simulation.
    """
    logger.info(
        f"Starting Paper Trading Simulation: Duration={config.duration_hours}h, "
        f"Step={config.step_minutes}m, Stations={len(config.stations)}, "
        f"Initial Capital={config.initial_capital} USDC"
    )

    start_time = datetime(2026, 10, 15, 0, 0, 0, tzinfo=timezone.utc)
    clock = SimulationClock(mode=SimulationClockMode.REPLAY, initial_time=start_time)
    bankroll = BankrollManager(initial_free_usdc=config.initial_capital)
    clob = MockCLOBClient()
    arbiter = CentralExceptionArbiter()
    risk_ctrl = TwoDimensionalRiskController()
    metrics = SimulationMetricsCalculator(initial_capital=config.initial_capital)

    simulator = PaperTradingSimulator(
        clock=clock,
        bankroll_manager=bankroll,
        clob_client=clob,
        arbiter=arbiter,
        risk_controller=risk_ctrl,
        config=PaperSimulationConfig(
            fractional_multiplier=config.fractional_multiplier,
            single_market_cap_ratio=Decimal("0.10"),
            global_utilization_cap_ratio=Decimal("0.70"),
            min_edge=config.min_edge,
        ),
    )

    # Track daily extrema per station
    station_daily_max: Dict[str, float] = {st: -999.0 for st in config.stations}
    active_days = ["2026-10-15", "2026-10-16"]
    current_day_idx = 0

    total_steps = int(config.duration_hours * 60 / config.step_minutes)

    # Initial baseline snapshot
    metrics.record_snapshot(clock.now(), bankroll.get_balance())

    for step in range(1, total_steps + 1):
        clock.advance(timedelta(minutes=config.step_minutes))
        now = clock.now()
        hour_of_sim = step * (config.step_minutes / 60.0)

        # Check day rollover
        if hour_of_sim > 24.0 and current_day_idx == 0:
            # Settle Day 1 markets
            logger.info("--- Rolling over and settling Day 1 markets across stations ---")
            day1_str = active_days[0]
            for st in config.stations:
                m_info = setup_market_definitions(st, day1_str)
                m_id = m_info["market_id"]
                actual_max = station_daily_max[st]
                base_t = m_info["base_t"]

                # Determine winning bin
                if actual_max <= base_t - 3:
                    win_bin = 0
                elif actual_max <= base_t:
                    win_bin = 1
                elif actual_max <= base_t + 3:
                    win_bin = 2
                else:
                    win_bin = 3

                simulator.settle_market(market_id=m_id, winning_bin_index=win_bin)
                station_daily_max[st] = -999.0  # Reset for Day 2

            current_day_idx = 1
            metrics.record_snapshot(now, bankroll.get_balance())

        current_day_str = active_days[min(current_day_idx, len(active_days) - 1)]
        hour_of_day = (now.hour) % 24

        # Simulate diurnal cycle: peak around 15:00 LT (19:00 UTC), minimum around 05:00 LT
        diurnal_factor = math.sin((hour_of_day - 9.0) / 24.0 * 2.0 * math.pi)

        # Multi-station execution cycle
        for st in config.stations:
            m_info = setup_market_definitions(st, current_day_str)
            m_id = m_info["market_id"]
            base_t = m_info["base_t"]

            # Simulated instantaneous temperature
            # Mild diurnal swing of 2.0°F around base climate
            inst_temp = base_t + (diurnal_factor * 2.0) + ((step % 3) * 0.1)
            if inst_temp > station_daily_max[st]:
                station_daily_max[st] = inst_temp

            simulator.on_weather_observation(st, current_temp_f=inst_temp, obs_time=now)

            # Construct simulated discrete orderbooks for 4 bins
            # Bins with mispriced liquidity offers opportunities
            book_asks = [
                OrderBookLevel(price=0.15, size=200.0),
                OrderBookLevel(price=0.25, size=500.0),
                OrderBookLevel(price=0.40, size=1000.0),
                OrderBookLevel(price=0.20, size=300.0),
            ]
            for b_idx, lvl in enumerate(book_asks):
                clob.set_orderbook(
                    market_id=m_id,
                    bin_index=b_idx,
                    snapshot=OrderBookSnapshot(
                        station_id=st,
                        bin_index=b_idx,
                        bin_label=m_info["bin_labels"][b_idx],
                        asks=[lvl],
                    ),
                )

            # EMOS Model prediction favoring Bin 2 (mild afternoon heating)
            # Probability mass concentrated in bin 2 (0.65) and bin 1 (0.25)
            # Physical truncation: bins below current max with 0 prob are strictly 0.0
            model_probs = {0: 0.02, 1: 0.25, 2: 0.65, 3: 0.08}
            if inst_temp > base_t + 1.0:
                # Bin 0 is physically impossible
                model_probs[0] = 0.0
                model_probs[2] = 0.67

            # Calculate remaining hours in trading session
            t_remain_hours = max(0.5, 24.0 - hour_of_day)

            # Evaluate strategy and issue protected IOC orders
            simulator.evaluate_and_execute(
                station_id=st,
                market_id=m_id,
                model_probs=model_probs,
                bin_labels=m_info["bin_labels"],
                bin_centers=m_info["bin_centers"],
                t_remain_hours=t_remain_hours,
                current_temp_f=inst_temp,
            )

        # Periodic NAV snapshot
        metrics.record_snapshot(now, bankroll.get_balance())

    # Terminal settlement at 48h for Day 2
    logger.info("--- Terminal settlement of Day 2 markets at hour 48 ---")
    day2_str = active_days[1]
    for st in config.stations:
        m_info = setup_market_definitions(st, day2_str)
        m_id = m_info["market_id"]
        actual_max = station_daily_max[st]
        base_t = m_info["base_t"]

        if actual_max <= base_t - 3:
            win_bin = 0
        elif actual_max <= base_t:
            win_bin = 1
        elif actual_max <= base_t + 3:
            win_bin = 2
        else:
            win_bin = 3

        simulator.settle_market(market_id=m_id, winning_bin_index=win_bin)

    # Final telemetry snapshot
    metrics.record_snapshot(clock.now(), bankroll.get_balance())

    report = metrics.generate_report(
        non_physical_violations=simulator.non_physical_orders_count,
        total_trades=len(simulator.trade_history),
    )

    # Export report JSON
    out_dir = Path(config.output_report_path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(config.output_report_path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2)
    logger.info(f"Saved Simulation Report to: {config.output_report_path}")

    # Export events JSONL
    if config.events_log_path:
        ev_dir = Path(config.events_log_path).parent
        ev_dir.mkdir(parents=True, exist_ok=True)
        with open(config.events_log_path, "w", encoding="utf-8") as f:
            for ev in simulator.events:
                f.write(json.dumps(ev.to_dict()) + "\n")
        logger.info(f"Saved {len(simulator.events)} simulation events to: {config.events_log_path}")

    print("\n" + "=" * 70)
    print("  ACTIVE 10 STATIONS 48H PAPER TRADING REPORT (TIER 1 ENGINEERING SMOKE)")
    print("=" * 70)
    print(f" Initial Bankroll:            {float(report.initial_capital):>15.2f} USDC")
    print(f" Final NAV:                   {float(report.final_nav):>15.2f} USDC")
    print(f" Total Filled Trades:         {report.total_trades_count:>15d}")
    print(f" Non-physical Violations:     {report.zero_non_physical_orders_violated:>15d} (Zero-tolerance)")
    print(f" Capital Conservation Passed: {str(report.capital_conservation_passed):>15}")
    print(f" Solvency Gate (NAV > 0):     {'PASS' if report.final_nav > Decimal('0') else 'FAIL':>15}")
    print("----------------------------------------------------------------------")
    print(" Note: Tier 1 Engineering Smoke test only.")
    print(" Refer to data/reports/historical_backtest_2019_report.json for")
    print(" authentic 2019 out-of-sample quantitative financial Sharpe ratio and MDD.")
    print("=" * 70 + "\n")

    return report


def main():
    parser = argparse.ArgumentParser(description="Active 10 Stations 48h Paper Trading Simulator")
    parser.add_argument("--duration-hours", type=float, default=48.0, help="Simulation length in hours")
    parser.add_argument("--step-minutes", type=int, default=60, help="Clock step resolution in minutes")
    parser.add_argument("--initial-capital", type=float, default=20000.0, help="Starting USDC deposit")
    parser.add_argument("--output-report", type=str, default="data/reports/paper_trading_48h_report.json")
    parser.add_argument("--log-events", type=str, default="data/reports/paper_trading_events.jsonl")

    args = parser.parse_args()

    config = PaperRunnerConfig(
        duration_hours=args.duration_hours,
        step_minutes=args.step_minutes,
        stations=list(ACTIVE_10_STATIONS),
        initial_capital=Decimal(str(args.initial_capital)),
        output_report_path=args.output_report,
        events_log_path=args.log_events,
    )

    report = run_simulation(config)
    if not report.capital_conservation_passed or report.zero_non_physical_orders_violated > 0:
        logger.error("Simulation failed regulatory safety gatechecks.")
        sys.exit(1)


if __name__ == "__main__":
    main()
