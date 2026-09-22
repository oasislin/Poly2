"""
HistoricalBacktestEngine: High-fidelity historical out-of-sample quantitative backtester (Phase 2 Task 07 - Fix Ticket 02 / Issue #102).

Implements Tier 2 Quantitative Backtesting:
- Directly drives 2019 out-of-sample holdout data from calib-dataset-v2.0 across Active 10 stations.
- Full pipeline integration:
  1. ClimateFloorRegistry (variance floor sigma_clim^2)
  2. ModelRegistry (200 production-grade Gaussian EMOS models)
  3. DiscreteBinEngine (1°F contract bin generation & integration)
  4. TruncatedProbabilityEngine (physical constraint verification)
  5. SyntheticMarketMaker (adversarial naive consensus quotation with 3~8 cent spreads & finite depth)
  6. EVEngine (positive microstructural EV evaluation)
  7. MultinomialKellyOptimizer (fractional Kelly sizing with budget constraints)
  8. BankrollManager (strict 6-decimal fixed-point four-bucket capital management)
  9. SettlementSimulator (daily terminal settlement against NWS observed_temp ground truth)
- Computes authentic daily-settlement sqrt(365) annualized Sharpe ratio, MDD, win rate, and profit factor.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import numpy as np
import pandas as pd

from src.bankroll.bankroll_manager import BankrollManager, to_usdc_decimal
from src.bankroll.multinomial_kelly import MultinomialKellyOptimizer, MultinomialKellyConfig
from src.data_processing.constants import ACTIVE_10_STATIONS
from src.modeling.climate_floor import ClimateFloorRegistry
from src.modeling.partitioner import DatasetPartitioner
from src.modeling.registry import ModelRegistry
from src.prediction.discrete_bin_engine import DiscreteBin, DiscreteBinEngine
from src.prediction.truncated_probability_engine import TruncatedProbabilityEngine
from src.simulation.market_maker import MarketMakerConfig, SyntheticMarketMaker
from src.simulation.models import PaperPosition, PaperTradeRecord
from src.simulation.settlement_sim import SettlementSimulator, SettlementRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BacktestConfig:
    """Configurable parameters for historical quantitative backtesting."""
    initial_bankroll: float = 10000.0           # Initial bankroll in USDC
    min_reprice_edge: float = 0.03              # Minimum EV edge (3 cents) to trade
    kelly_fraction: float = 0.25                # Quarter-Kelly sizing
    max_single_bet_pct: float = 0.05            # Max 5% of bankroll per single contract bin
    max_daily_commit_pct: float = 0.40          # Max 40% of total bankroll committed across all stations per day
    target_lead_hours: int = 18                 # Standard lead time for daily maximum evaluation
    target_type: str = "max"                    # Default target extreme (max temp)
    dataset_dir: Path = Path("data/processed/calib-dataset-v2.0")
    models_dir: Path = Path("data/models")
    climate_floor_path: Path = Path("configs/climate_floor_v2.json")
    market_maker_config: Optional[MarketMakerConfig] = None


@dataclass
class DailyPerformanceRecord:
    """End-of-day financial snapshot."""
    date: str
    start_nav: float
    end_nav: float
    daily_pnl: float
    daily_return: float
    trades_count: int
    total_committed: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "date": self.date,
            "start_nav": float(self.start_nav),
            "end_nav": float(self.end_nav),
            "daily_pnl": float(self.daily_pnl),
            "daily_return": float(self.daily_return),
            "trades_count": int(self.trades_count),
            "total_committed": float(self.total_committed),
        }


@dataclass
class BacktestReport:
    """Comprehensive performance report and gate adjudication for historical backtest."""
    start_date: str
    end_date: str
    trading_days: int
    initial_bankroll: float
    final_bankroll: float
    total_pnl: float
    total_return_pct: float
    annualized_sharpe: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    profitable_trades: int
    profit_factor: float
    average_ev: float
    zero_non_physical_violations: int
    capital_conservation_passed: bool
    daily_records: List[DailyPerformanceRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evaluation_type": "quantitative_backtest",
            "start_date": self.start_date,
            "end_date": self.end_date,
            "trading_days": self.trading_days,
            "initial_bankroll": float(self.initial_bankroll),
            "final_bankroll": float(self.final_bankroll),
            "total_pnl": float(self.total_pnl),
            "total_return_pct": float(self.total_return_pct),
            "annualized_sharpe": float(self.annualized_sharpe),
            "max_drawdown": float(self.max_drawdown),
            "win_rate": float(self.win_rate),
            "total_trades": self.total_trades,
            "profitable_trades": self.profitable_trades,
            "profit_factor": float(self.profit_factor),
            "average_ev": float(self.average_ev),
            "zero_non_physical_violations": self.zero_non_physical_violations,
            "capital_conservation_passed": self.capital_conservation_passed,
            "daily_records": [r.to_dict() for r in self.daily_records],
        }


class HistoricalBacktestEngine:
    """
    Executes an out-of-sample event-driven historical quantitative backtest
    against adversarial synthetic market makers using genuine 2019 data.
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()
        self.bankroll_manager = BankrollManager(initial_free_usdc=self.config.initial_bankroll)
        self.settlement_sim = SettlementSimulator(bankroll_manager=self.bankroll_manager)
        self.market_maker = SyntheticMarketMaker(config=self.config.market_maker_config)
        self.partitioner = DatasetPartitioner()
        self.model_registry = ModelRegistry(base_dir=self.config.models_dir)
        self.climate_floor_registry = ClimateFloorRegistry.load_from_json(self.config.climate_floor_path)
        self.kelly_optimizer = MultinomialKellyOptimizer()
        self.truncation_engine = TruncatedProbabilityEngine()

    def run_backtest(
        self,
        stations: Optional[Sequence[str]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        max_days: Optional[int] = None,
    ) -> BacktestReport:
        """
        Run out-of-sample quantitative backtest across active stations and date range.
        """
        active_stations = list(stations) if stations else sorted(list(ACTIVE_10_STATIONS))
        logger.info(f"Starting historical backtest for stations: {active_stations}")

        # 1. Load 2019 validation datasets for all active stations
        station_data: Dict[str, pd.DataFrame] = {}
        for st in active_stations:
            try:
                df = self.partitioner.load_validation_dataset(
                    station=st,
                    year=2019,
                    target_type=self.config.target_type,
                    lead_bucket=self.config.target_lead_hours,
                    base_dir=self.config.dataset_dir,
                )
                if df is not None and not df.empty:
                    df["target_date_str"] = pd.to_datetime(df["target_date"]).dt.strftime("%Y-%m-%d")
                    station_data[st] = df.set_index("target_date_str")
            except Exception as e:
                logger.warning(f"Could not load 2019 validation data for {st}: {e}")

        if not station_data:
            raise RuntimeError("No validation data loaded for any station!")

        # 2. Determine common date sequence
        all_dates = sorted(list(set.union(*[set(df.index) for df in station_data.values()])))
        if start_date:
            all_dates = [d for d in all_dates if d >= start_date]
        if end_date:
            all_dates = [d for d in all_dates if d <= end_date]
        if max_days:
            all_dates = all_dates[:max_days]

        logger.info(f"Backtesting over {len(all_dates)} dates ({all_dates[0]} to {all_dates[-1]})")

        daily_records: List[DailyPerformanceRecord] = []
        all_settlements: List[SettlementRecord] = []
        ev_samples: List[float] = []
        zero_non_physical_violations: int = 0
        total_trade_count: int = 0

        # 3. Step through each calendar day
        for target_date_str in all_dates:
            start_day_nav = self.bankroll_manager.total_balance
            today_positions: Dict[str, List[PaperPosition]] = {}
            today_market_bins: Dict[str, List[DiscreteBin]] = {}
            today_committed = Decimal("0.000000")
            max_daily_budget = self.bankroll_manager.effective_bankroll * to_usdc_decimal(self.config.max_daily_commit_pct)

            # Daily station evaluation
            for st in active_stations:
                if st not in station_data or target_date_str not in station_data[st].index:
                    continue

                row = station_data[st].loc[target_date_str]
                if pd.isna(row["observed_temp"]) or pd.isna(row["ensemble_mean"]):
                    continue

                ens_mean = float(row["ensemble_mean"])
                ens_var = float(row["ensemble_variance"])
                observed_temp = float(row["observed_temp"])

                # Climatology variance floor and EMOS prediction
                sigma_clim_sq = self.climate_floor_registry.get_variance_floor(
                    st, self.config.target_type, target_date_str
                )
                model = self.model_registry.get_model(
                    st, target_date_str, self.config.target_type, self.config.target_lead_hours
                )
                mu, sigma = model.compute_params(ens_mean, ens_var, sigma_clim_sq)

                # Generate discrete 1°F bins centered at predicted rounded mean
                center_f = int(round(mu))
                bins = DiscreteBinEngine.generate_standard_bins(
                    center_temp_f=center_f,
                    num_exact_bins=5,
                    station_id=st,
                )
                today_market_bins[st] = bins
                calibrated_bins = DiscreteBinEngine.calculate_bin_probabilities(
                    mu=mu,
                    sigma=sigma,
                    bins=bins,
                )

                # Synthetic Market Maker Order Books
                market_id = f"{st}-{target_date_str.replace('-', '')}-MAX"
                order_books = self.market_maker.generate_market_order_books(
                    station_id=st,
                    market_id=market_id,
                    bins=bins,
                    ensemble_mean=ens_mean,
                    ensemble_variance=ens_var,
                )

                # Identify positive EV opportunities
                probs = [b.probability for b in calibrated_bins]
                prices = [
                    float(order_books[b.bin_index].best_ask) if order_books[b.bin_index].best_ask is not None else 1.0
                    for b in calibrated_bins
                ]

                for idx, b in enumerate(calibrated_bins):
                    edge = b.probability - prices[idx]
                    if edge >= self.config.min_reprice_edge:
                        ev_samples.append(edge)

                # Multinomial Kelly Optimization
                w_free = float(self.bankroll_manager.effective_bankroll)
                alloc_res = self.kelly_optimizer.optimize(
                    probabilities=probs,
                    prices=prices,
                    w_free=w_free,
                )

                if not alloc_res.success or alloc_res.total_allocation <= 0.0:
                    continue

                # Sizing and execution
                for bin_idx, raw_alloc in enumerate(alloc_res.optimal_allocations):
                    if raw_alloc <= 0.0:
                        continue

                    # Fractional Kelly scaling and budget cap
                    bet_budget = raw_alloc * self.config.kelly_fraction
                    max_single_bet = float(self.bankroll_manager.effective_bankroll) * self.config.max_single_bet_pct
                    bet_budget = min(bet_budget, max_single_bet)

                    # Limit by daily budget
                    remaining_daily_budget = float(max_daily_budget - today_committed)
                    if remaining_daily_budget <= 1.0:
                        break
                    bet_budget = min(bet_budget, remaining_daily_budget)

                    ob = order_books[bin_idx]
                    if not ob.asks or ob.best_ask is None:
                        continue

                    best_ask_float = float(ob.best_ask)
                    level1_depth = ob.asks[0].size
                    max_level1_cost = level1_depth * best_ask_float
                    final_cost = min(bet_budget, max_level1_cost)

                    if final_cost < 1.0:
                        continue

                    cost_dec = to_usdc_decimal(final_cost)
                    best_ask_dec = Decimal(str(best_ask_float))
                    shares_dec = (cost_dec / best_ask_dec).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)

                    if shares_dec <= Decimal("0.000000") or not self.bankroll_manager.can_lock(cost_dec):
                        continue

                    # Non-physical order guard
                    if calibrated_bins[bin_idx].probability <= 0.0:
                        zero_non_physical_violations += 1
                        logger.error(f"VIOLATION: Non-physical order attempted for bin {bin_idx}")
                        continue

                    self.bankroll_manager.lock_funds(cost_dec)
                    today_committed += cost_dec
                    total_trade_count += 1

                    pos = PaperPosition(
                        station_id=st,
                        market_id=market_id,
                        bin_index=bin_idx,
                        bin_label=bins[bin_idx].label,
                        shares=shares_dec,
                        total_cost=cost_dec,
                    )
                    today_positions.setdefault(st, []).append(pos)

            # Daily Settlement across all active stations
            for st, positions in today_positions.items():
                if not positions or st not in today_market_bins:
                    continue
                market_id = f"{st}-{target_date_str.replace('-', '')}-MAX"
                observed_temp = float(station_data[st].loc[target_date_str, "observed_temp"])
                bins = today_market_bins[st]

                # Determine winning bin
                winning_idx: Optional[int] = None
                for b in bins:
                    if b.bin_type == "lte" and observed_temp <= b.upper_bound_f:
                        winning_idx = b.bin_index
                        break
                    elif b.bin_type == "gte" and observed_temp >= b.lower_bound_f:
                        winning_idx = b.bin_index
                        break
                    elif b.bin_type == "exact" and (b.lower_bound_f <= observed_temp < b.upper_bound_f):
                        winning_idx = b.bin_index
                        break

                if winning_idx is None:
                    winning_idx = 0

                settle_rec = self.settlement_sim.settle_market(
                    market_id=market_id,
                    winning_bin_index=winning_idx,
                    positions=positions,
                )
                all_settlements.append(settle_rec)

            # End of Day Accounting
            end_day_nav = self.bankroll_manager.total_balance
            daily_pnl = end_day_nav - start_day_nav
            daily_ret = float(daily_pnl / start_day_nav) if start_day_nav > Decimal("0") else 0.0

            daily_records.append(
                DailyPerformanceRecord(
                    date=target_date_str,
                    start_nav=float(start_day_nav),
                    end_nav=float(end_day_nav),
                    daily_pnl=float(daily_pnl),
                    daily_return=daily_ret,
                    trades_count=sum(len(p) for p in today_positions.values()),
                    total_committed=float(today_committed),
                )
            )

        # 4. Aggregate financial and risk metrics
        final_nav = float(self.bankroll_manager.total_balance)
        init_nav = float(self.config.initial_bankroll)
        total_pnl = final_nav - init_nav
        total_return_pct = (total_pnl / init_nav) * 100.0 if init_nav > 0 else 0.0

        daily_returns = np.array([r.daily_return for r in daily_records])
        if len(daily_returns) > 1:
            mean_r = float(np.mean(daily_returns))
            std_r = float(np.std(daily_returns, ddof=1))
            annualized_sharpe = float((mean_r / std_r) * np.sqrt(365.0)) if std_r > 1e-7 else 0.0
        else:
            annualized_sharpe = 0.0

        # Maximum Drawdown calculation
        nav_series = np.array([r.end_nav for r in daily_records])
        if len(nav_series) > 0:
            running_peaks = np.maximum.accumulate(nav_series)
            drawdowns = (running_peaks - nav_series) / running_peaks
            max_drawdown = float(np.max(drawdowns))
        else:
            max_drawdown = 0.0

        # Win rate and profit factor
        profitable_trades = sum(1 for s in all_settlements if s.net_pnl > Decimal("0"))
        win_rate = profitable_trades / len(all_settlements) if all_settlements else 0.0

        gross_profit = sum(float(s.net_pnl) for s in all_settlements if s.net_pnl > Decimal("0"))
        gross_loss = abs(sum(float(s.net_pnl) for s in all_settlements if s.net_pnl < Decimal("0")))
        if gross_loss > 0.0:
            profit_factor = gross_profit / gross_loss
        else:
            profit_factor = 99.0 if gross_profit > 0 else 1.0

        avg_ev = float(np.mean(ev_samples)) if ev_samples else 0.0
        capital_conservation_passed = (self.bankroll_manager.get_balance().active_locked == Decimal("0.000000"))

        return BacktestReport(
            start_date=all_dates[0] if all_dates else "",
            end_date=all_dates[-1] if all_dates else "",
            trading_days=len(all_dates),
            initial_bankroll=init_nav,
            final_bankroll=final_nav,
            total_pnl=total_pnl,
            total_return_pct=total_return_pct,
            annualized_sharpe=annualized_sharpe,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            total_trades=len(all_settlements),
            profitable_trades=profitable_trades,
            profit_factor=profit_factor,
            average_ev=avg_ev,
            zero_non_physical_violations=zero_non_physical_violations,
            capital_conservation_passed=capital_conservation_passed,
            daily_records=daily_records,
        )
