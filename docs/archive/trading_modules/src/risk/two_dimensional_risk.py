"""
Two-Dimensional Ladder Risk Controller (Phase 2 Task 06 - Ticket 04 / Issue #92).
Implements ADR-0011 and Phase 2 Execution Document v2.0 §5.3:
- Critical Regime: T_remain < 1.0h and delta_T > 3.0°F -> 0.20 position sizing multiplier
- Certain Regime: delta_T <= 0.5°F and T_remain < 0.5h -> Lock winnings, forbid opposite speculative orders
- Normal Regime: Full allocation headroom
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class RiskRegime(str, Enum):
    """Regime zones defined by distance-to-close and residual temperature difference."""
    NORMAL = "NORMAL"
    CRITICAL = "CRITICAL"
    CERTAIN = "CERTAIN"


@dataclass(frozen=True)
class TwoDimensionalRiskConfig:
    """Configurable thresholds for two-dimensional ladder risk."""
    critical_time_hours: float = 1.0
    critical_temp_diff_f: float = 3.0
    critical_haircut: Decimal = Decimal("0.20")
    certain_time_hours: float = 0.5
    certain_temp_diff_f: float = 0.5


@dataclass(frozen=True)
class RiskRegimeDecision:
    """Risk verdict controlling position sizing and order filtering."""
    regime: RiskRegime
    sizing_multiplier: Decimal
    forbid_opposite_speculation: bool
    reason: str


class TwoDimensionalRiskController:
    """
    Evaluates market proximity and temperature residual to govern ladder risk.
    """

    def __init__(self, config: Optional[TwoDimensionalRiskConfig] = None):
        self.config = config or TwoDimensionalRiskConfig()

    def evaluate_regime(
        self,
        t_remain_hours: float,
        delta_temp_f: float,
    ) -> RiskRegimeDecision:
        """
        Assess risk zone from time remaining (hours) and residual temperature delta (°F).
        """
        # Check Critical Regime: Close to settlement but temperature significantly away
        if (
            t_remain_hours < self.config.critical_time_hours
            and delta_temp_f > self.config.critical_temp_diff_f
        ):
            return RiskRegimeDecision(
                regime=RiskRegime.CRITICAL,
                sizing_multiplier=self.config.critical_haircut,
                forbid_opposite_speculation=False,
                reason=(
                    f"CRITICAL ZONE: T_remain {t_remain_hours:.2f}h < {self.config.critical_time_hours}h "
                    f"and delta_T {delta_temp_f:.2f}°F > {self.config.critical_temp_diff_f}°F. "
                    f"Enforcing {self.config.critical_haircut}x haircut."
                ),
            )

        # Check Certain Regime: Imminent settlement and temperature virtually pinned
        if (
            t_remain_hours < self.config.certain_time_hours
            and delta_temp_f <= self.config.certain_temp_diff_f
        ):
            return RiskRegimeDecision(
                regime=RiskRegime.CERTAIN,
                sizing_multiplier=Decimal("1.00"),
                forbid_opposite_speculation=True,
                reason=(
                    f"CERTAIN ZONE: T_remain {t_remain_hours:.2f}h < {self.config.certain_time_hours}h "
                    f"and delta_T {delta_temp_f:.2f}°F <= {self.config.certain_temp_diff_f}°F. "
                    f"Locking victories, forbidding opposite speculative orders."
                ),
            )

        # Normal Regime
        return RiskRegimeDecision(
            regime=RiskRegime.NORMAL,
            sizing_multiplier=Decimal("1.00"),
            forbid_opposite_speculation=False,
            reason="NORMAL ZONE: Market operating within standard risk boundaries.",
        )
