"""
Simulation Metrics and Risk Guardrail Audit Calculator (Phase 2 Task 07 - Ticket 03 / Issue #97).
Tracks NAV trajectories, computes Sharpe Ratio with zero-volatility protection,
maximum drawdown (MDD), capital conservation verification, and non-physical order audits.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
import logging
import math
from typing import Any, Dict, List, Optional

from src.bankroll.bankroll_manager import FourBucketBalance, to_usdc_decimal

logger = logging.getLogger(__name__)

DEFAULT_ZOMBIE_NAV_MULTIPLIER = Decimal("0.90")  # ADR-0012 §D4: 10% haircut on zombie margin
EPSILON_VOLATILITY = 1e-7


@dataclass
class SimulationMetricsSnapshot:
    """Point-in-time financial and risk telemetry snapshot."""
    timestamp: datetime
    free_usdc: Decimal
    active_locked: Decimal
    zombie_margin: Decimal
    disputed_margin: Decimal
    total_bankroll: Decimal
    nav: Decimal

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "free_usdc": float(self.free_usdc),
            "active_locked": float(self.active_locked),
            "zombie_margin": float(self.zombie_margin),
            "disputed_margin": float(self.disputed_margin),
            "total_bankroll": float(self.total_bankroll),
            "nav": float(self.nav),
        }


@dataclass
class SimulationMetricsReport:
    """Comprehensive performance and regulatory audit report."""
    initial_capital: Decimal
    final_nav: Decimal
    total_return_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    zero_non_physical_orders_violated: int
    capital_conservation_passed: bool
    num_snapshots: int
    total_trades_count: int = 0
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "initial_capital": float(self.initial_capital),
            "final_nav": float(self.final_nav),
            "total_return_pct": self.total_return_pct,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "zero_non_physical_orders_violated": self.zero_non_physical_orders_violated,
            "capital_conservation_passed": self.capital_conservation_passed,
            "num_snapshots": self.num_snapshots,
            "total_trades_count": self.total_trades_count,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass(frozen=True)
class SimulationMetricsConfig:
    """Configuration for metrics calculation."""
    annualization_factor: float = 365.0 * 24.0  # Hourly intervals annualized
    epsilon_volatility: float = EPSILON_VOLATILITY


class SimulationMetricsCalculator:
    """
    Computes performance metrics and executes financial audit checks.
    """

    def __init__(
        self,
        initial_capital: Decimal,
        config: Optional[SimulationMetricsConfig] = None,
    ):
        self.initial_capital = to_usdc_decimal(initial_capital)
        self.config = config or SimulationMetricsConfig()
        self.snapshots: List[SimulationMetricsSnapshot] = []

    def record_snapshot(
        self,
        timestamp: datetime,
        balance: FourBucketBalance,
    ) -> SimulationMetricsSnapshot:
        """
        Record a financial snapshot from current four-bucket balance.
        NAV evaluates Zombie Margin at 0.90x according to ADR-0012 §D4.
        """
        zombie_nav = (balance.zombie_margin * DEFAULT_ZOMBIE_NAV_MULTIPLIER).quantize(
            Decimal("0.000001"), rounding=ROUND_DOWN
        )
        nav = balance.free_usdc + balance.active_locked + zombie_nav + balance.disputed_margin

        snap = SimulationMetricsSnapshot(
            timestamp=timestamp,
            free_usdc=balance.free_usdc,
            active_locked=balance.active_locked,
            zombie_margin=balance.zombie_margin,
            disputed_margin=balance.disputed_margin,
            total_bankroll=balance.total_bankroll,
            nav=nav,
        )
        self.snapshots.append(snap)
        return snap

    def compute_max_drawdown(self) -> float:
        """Compute maximum peak-to-trough percentage drawdown."""
        if not self.snapshots:
            return 0.0

        peak = float(self.snapshots[0].nav)
        max_dd = 0.0

        for s in self.snapshots:
            val = float(s.nav)
            if val > peak:
                peak = val
            elif peak > 0:
                dd = (peak - val) / peak * 100.0
                if dd > max_dd:
                    max_dd = dd

        return max_dd

    def compute_sharpe_ratio(self) -> float:
        """
        Compute Sharpe Ratio from periodic return series.
        Implements numerical stability and zero-volatility protection:
        - If series length < 2 or variance near zero:
          - If mean return <= 0: return 0.0
          - If mean return > 0: return smoothed positive estimate
        """
        if len(self.snapshots) < 2:
            return 0.0

        returns: List[float] = []
        for i in range(1, len(self.snapshots)):
            prev = float(self.snapshots[i - 1].nav)
            curr = float(self.snapshots[i].nav)
            if prev > 0.0:
                ret = (curr - prev) / prev
                returns.append(ret)

        if not returns:
            return 0.0

        n = len(returns)
        mean_ret = sum(returns) / n

        # Sample variance
        var = sum((r - mean_ret) ** 2 for r in returns) / (n - 1) if n > 1 else 0.0
        std_dev = math.sqrt(var)

        # Zero / near-zero volatility guardrail
        if std_dev < self.config.epsilon_volatility:
            if mean_ret <= 0.0:
                return 0.0
            else:
                # Steady upward return without downward fluctuation: assign high confidence Sharpe (> 2.0)
                return min(10.0, (mean_ret / self.config.epsilon_volatility) * math.sqrt(min(n, 24)))

        # Standard annualized / scaled Sharpe ratio
        scaling = math.sqrt(min(n, 24))
        sharpe = (mean_ret / std_dev) * scaling
        return sharpe

    def verify_capital_conservation(self) -> bool:
        """
        Verify no untracked leaking of funds.
        Free + Active + Zombie + Disputed must match recorded Total Bankroll at every step.
        """
        for s in self.snapshots:
            calc_total = s.free_usdc + s.active_locked + s.zombie_margin + s.disputed_margin
            if abs(calc_total - s.total_bankroll) > Decimal("0.000010"):
                logger.error(f"Capital conservation violation at {s.timestamp}: {calc_total} != {s.total_bankroll}")
                return False
        return True

    def generate_report(
        self,
        non_physical_violations: int = 0,
        total_trades: int = 0,
    ) -> SimulationMetricsReport:
        """Compile final simulation audit report."""
        if not self.snapshots:
            return SimulationMetricsReport(
                initial_capital=self.initial_capital,
                final_nav=self.initial_capital,
                total_return_pct=0.0,
                max_drawdown_pct=0.0,
                sharpe_ratio=0.0,
                zero_non_physical_orders_violated=non_physical_violations,
                capital_conservation_passed=True,
                num_snapshots=0,
                total_trades_count=total_trades,
            )

        final_nav = self.snapshots[-1].nav
        init_nav = float(self.initial_capital)
        final_nav_f = float(final_nav)

        total_return_pct = ((final_nav_f - init_nav) / init_nav * 100.0) if init_nav > 0 else 0.0
        mdd_pct = self.compute_max_drawdown()
        sharpe = self.compute_sharpe_ratio()
        conservation_passed = self.verify_capital_conservation()

        return SimulationMetricsReport(
            initial_capital=self.initial_capital,
            final_nav=final_nav,
            total_return_pct=total_return_pct,
            max_drawdown_pct=mdd_pct,
            sharpe_ratio=sharpe,
            zero_non_physical_orders_violated=non_physical_violations,
            capital_conservation_passed=conservation_passed,
            num_snapshots=len(self.snapshots),
            total_trades_count=total_trades,
        )
