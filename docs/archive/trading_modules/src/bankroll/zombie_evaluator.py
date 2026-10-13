"""
Zombie Position Evaluator and Tiered Liquidity Circuit Breaker (Phase 2 Task 05 - Ticket 02 / Issue #84).
Implements ADR-0012 §D2 and §D4:
- 12h physical deadline post-midnight settlement trigger
- Dual-book accounting: Sizing Book (0.0x exclusion) vs Financial NAV Book (10% haircut)
- Tiered nominal zombie ratio (R_z) circuit breakers (15% haircut, 30% halt, 50% safe-mode)
"""

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta, date, time
from decimal import Decimal
from enum import Enum
import logging
from typing import Any, Dict, List, Optional
import zoneinfo

from src.bankroll.bankroll_manager import BankrollManager, to_usdc_decimal
from src.data_processing.constants import ACTIVE_10_STATIONS, STATION_METADATA

logger = logging.getLogger(__name__)


class LiquidityTier(str, Enum):
    """Tiered liquidity risk rating based on nominal zombie + disputed ratio (ADR-0012 §D4)."""
    HEALTHY = "HEALTHY"                      # R_z <= 15% -> 1.0x sizing
    WARNING_HAIRCUT = "WARNING_HAIRCUT"      # 15% < R_z <= 30% -> 0.5x sizing haircut
    HALT_NEW_POSITIONS = "HALT_NEW_POSITIONS"  # 30% < R_z <= 50% -> 0.0x sizing (halt new)
    CRITICAL_SAFE_MODE = "CRITICAL_SAFE_MODE"  # R_z > 50% -> SAFE_MODE read-only halt


@dataclass
class PositionRecord:
    """Detailed record of an open or un-settled trading position."""
    position_id: str
    station_id: str
    market_date: str  # YYYY-MM-DD
    cost_basis: Decimal
    shares: Decimal
    expected_payout: Decimal
    is_zombie: bool = False
    is_disputed: bool = False
    is_settled: bool = False


@dataclass(frozen=True)
class LiquidityStatus:
    """Snapshot verdict of account liquidity tier."""
    tier: LiquidityTier
    nominal_zombie_ratio: float
    sizing_multiplier: float
    details: str


@dataclass(frozen=True)
class ZombieEvaluatorConfig:
    """Configurable thresholds for zombie evaluation and liquidity watchdog."""
    grace_period_hours: float = 12.0
    zombie_haircut: float = 0.10
    tier_haircut_threshold: float = 0.15
    tier_halt_threshold: float = 0.30
    tier_safe_mode_threshold: float = 0.50


class ZombieEvaluator:
    """
    Evaluates position settlement deadlines and governs dual-book valuation.
    """

    def __init__(
        self,
        bankroll_manager: BankrollManager,
        config: Optional[ZombieEvaluatorConfig] = None,
    ):
        self.bankroll_manager = bankroll_manager
        self.config = config or ZombieEvaluatorConfig()
        self._positions: Dict[str, PositionRecord] = {}

    def register_position(self, pos: PositionRecord) -> None:
        """Register a new active trading position."""
        self._positions[pos.position_id] = pos

    def get_position(self, position_id: str) -> Optional[PositionRecord]:
        """Retrieve registered position record."""
        return self._positions.get(position_id)

    def _get_station_tz(self, station_id: str) -> zoneinfo.ZoneInfo:
        tz_name = STATION_METADATA.get(station_id, {}).get("timezone", "UTC")
        try:
            return zoneinfo.ZoneInfo(tz_name)
        except Exception:
            return zoneinfo.ZoneInfo("UTC")

    def get_zombie_trigger_utc(self, station_id: str, market_date_str: str) -> datetime:
        """
        Compute UTC timestamp when position crosses 12h deadline (ADR-0012 §D2):
        Expected settle = local midnight at end of market_date
        Zombie trigger = Expected settle + 12 hours (i.e. local noon next day)
        """
        tz = self._get_station_tz(station_id)
        d = date.fromisoformat(market_date_str)
        next_day = d + timedelta(days=1)
        local_midnight = datetime.combine(next_day, time(0, 0), tzinfo=tz)
        expected_settle_utc = local_midnight.astimezone(timezone.utc)
        return expected_settle_utc + timedelta(hours=self.config.grace_period_hours)

    def evaluate_positions(self, current_wall_time: Optional[datetime] = None) -> List[str]:
        """
        Check all active un-settled positions against 12h trigger.
        Transfers overdue positions to Zombie Margin. Returns list of newly transitioned position IDs.
        """
        now = current_wall_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        newly_zombified: List[str] = []

        for p_id, pos in self._positions.items():
            if pos.is_settled or pos.is_zombie or pos.is_disputed:
                continue

            trigger_utc = self.get_zombie_trigger_utc(pos.station_id, pos.market_date)
            if now >= trigger_utc:
                pos.is_zombie = True
                self.bankroll_manager.transfer_to_zombie(pos.cost_basis)
                newly_zombified.append(p_id)
                logger.warning(
                    f"Position {p_id} ({pos.station_id} {pos.market_date}) exceeded 12h grace period "
                    f"({now.isoformat()} >= {trigger_utc.isoformat()}). Moved to Zombie Margin."
                )

        return newly_zombified

    def calculate_financial_nav(self) -> Decimal:
        """
        Calculate total financial NAV according to Financial NAV Book (ADR-0012 §D4 Rule 2):
        NAV = Free USDC + Active Locked + Zombie Value (0.90 * E[V]) + Disputed Value
        """
        bal = self.bankroll_manager.get_balance()
        nav = bal.free_usdc + bal.active_locked

        # Haircut zombie positions by 10% on expected payout
        zombie_nav = Decimal("0.000000")
        for pos in self._positions.values():
            if pos.is_zombie and not pos.is_settled:
                # 0.90 * E[V]
                discount = Decimal(str(1.0 - self.config.zombie_haircut))
                zombie_nav += to_usdc_decimal(pos.expected_payout * discount)

        nav += zombie_nav
        # Disputed margin valued conservatively at 0 for safety in NAV if not specified
        return to_usdc_decimal(nav)

    def evaluate_liquidity_tier(self) -> LiquidityStatus:
        """
        Compute nominal zombie ratio R_z and determine liquidity tier and sizing multiplier.
        R_z = (Zombie Margin + Disputed Margin) / Total Bankroll
        """
        bal = self.bankroll_manager.get_balance()
        tot = bal.total_bankroll

        if tot <= Decimal("0"):
            return LiquidityStatus(
                tier=LiquidityTier.CRITICAL_SAFE_MODE,
                nominal_zombie_ratio=1.0,
                sizing_multiplier=0.0,
                details="Total bankroll is zero or negative.",
            )

        nominal_frozen = bal.zombie_margin + bal.disputed_margin
        r_z = float(nominal_frozen / tot)

        if r_z > self.config.tier_safe_mode_threshold:
            tier = LiquidityTier.CRITICAL_SAFE_MODE
            mult = 0.0
            msg = f"Nominal zombie ratio R_z={r_z:.1%} > {self.config.tier_safe_mode_threshold:.1%}. CRITICAL SAFE_MODE triggered."
        elif r_z > self.config.tier_halt_threshold:
            tier = LiquidityTier.HALT_NEW_POSITIONS
            mult = 0.0
            msg = f"Nominal zombie ratio R_z={r_z:.1%} > {self.config.tier_halt_threshold:.1%}. Halt new positions."
        elif r_z > self.config.tier_haircut_threshold:
            tier = LiquidityTier.WARNING_HAIRCUT
            mult = 0.5
            msg = f"Nominal zombie ratio R_z={r_z:.1%} > {self.config.tier_haircut_threshold:.1%}. 50% sizing haircut applied."
        else:
            tier = LiquidityTier.HEALTHY
            mult = 1.0
            msg = f"Liquidity healthy. R_z={r_z:.1%} <= {self.config.tier_haircut_threshold:.1%}."

        return LiquidityStatus(
            tier=tier,
            nominal_zombie_ratio=r_z,
            sizing_multiplier=mult,
            details=msg,
        )
