"""
Pre-Buy Gatekeeper, Local Hard Valve, and Position Insulation Policy (Phase 2 Task 03 - Ticket 03 / Issue #73).
Implements ADR-0014 §2:
- Principle 1: Pre-Buy Gate Check (Data Freshness <= 7.0m + Confirmed Connectivity)
- Principle 2: Local Hard Valve Shutdown & Best-Effort Cancel (Zero-Emission Theorem)
- Principle 4: Position Insulation and Settlement Grace Escape Hatch (<= 30m window)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any, Callable, Dict, Optional

from src.data_processing.constants import ACTIVE_10_STATIONS
from src.risk.central_arbiter import CentralExceptionArbiter, StationLifeCycleState

logger = logging.getLogger(__name__)


class HardValveClosedError(Exception):
    """Raised when an emission attempt occurs while the local hard valve is closed."""
    pass


@dataclass(frozen=True)
class OrderIntent:
    """Pre-flight trading intent descriptor."""
    station_id: str
    price: float
    size: float
    target_bin: Optional[str] = None
    side: str = "BUY"


@dataclass(frozen=True)
class PreBuyGateConfig:
    """Configurable thresholds for PreBuyGate (ADR-0014 §2 Principle 1)."""
    max_observation_age_minutes: float = 7.0  # 5-min ASOS reporting cycle + 2-min network grace


@dataclass(frozen=True)
class PreBuyDecision:
    """Verdict from the pre-buy gate check."""
    allowed: bool
    reason: str
    age_seconds: Optional[float] = None


@dataclass(frozen=True)
class InsulationAction:
    """Action decision for filled positions under anomalous states (ADR-0014 §2 Principle 4)."""
    allow_market_sell: bool
    action_type: str
    requires_manual_intervention: bool = False
    details: Optional[str] = None


class LocalHardValve:
    """
    Local Zero-Emission Hard Valve (ADR-0014 §2 Principle 2).
    Instantly closes in-memory emission switch upon anomaly, preventing any buy-order byte emission.
    Concurrently triggers Best-Effort Cancel to external CLOB orderbooks.
    """

    def __init__(
        self,
        arbiter: Optional[CentralExceptionArbiter] = None,
        cancel_callback: Optional[Callable[[str], None]] = None,
    ):
        self.arbiter = arbiter
        self.cancel_callback = cancel_callback
        # station_id -> bool (True = Open/Can Emit, False = Closed/Zero-Emission)
        self._valve_open: Dict[str, bool] = {st: True for st in ACTIVE_10_STATIONS}
        self._global_open: bool = True

    def is_open(self, station_id: str) -> bool:
        """Check whether local valve is open for a station."""
        if not self._global_open:
            return False
        # If arbiter is attached, enforce that station must be in ACTIVE state
        if self.arbiter and not self.arbiter.is_station_tradable(station_id):
            return False
        return self._valve_open.get(station_id, False)

    def assert_can_emit(self, station_id: str) -> None:
        """Enforce zero-emission check before transmitting bytes to gateway."""
        if not self.is_open(station_id):
            raise HardValveClosedError(
                f"Local hard valve is closed for station '{station_id}'. Emission blocked by Zero-Emission Theorem."
            )

    def close_valve(self, station_id: str, reason: Optional[str] = None) -> None:
        """
        Close local valve 0ms and trigger Best-Effort Cancel concurrently.
        Failures in external cancel callbacks are logged but do not disrupt local shutdown.
        """
        logger.critical(f"LOCAL HARD VALVE CLOSED for '{station_id}'! Reason: {reason}")
        if station_id == "GLOBAL":
            self._global_open = False
            for st in self._valve_open:
                self._valve_open[st] = False
        else:
            self._valve_open[station_id] = False

        # Concurrently trigger best-effort cancel if callback registered
        if self.cancel_callback:
            try:
                self.cancel_callback(station_id)
            except Exception as e:
                logger.error(
                    f"Best-effort cancel failed for station '{station_id}' (local valve remains firmly closed): {e}",
                    exc_info=True,
                )

    def open_valve(self, station_id: str) -> None:
        """Reopen local valve for a station."""
        if station_id == "GLOBAL":
            self._global_open = True
            for st in self._valve_open:
                self._valve_open[st] = True
        else:
            self._valve_open[station_id] = True
        logger.info(f"Local hard valve reopened for '{station_id}'.")


class PreBuyGateKeeper:
    """
    Synchronous In-Memory Pre-Buy Gatekeeper (ADR-0014 §2 Principle 1).
    Performs pure in-memory validation in the final second before order dispatch:
    1. Observation Physical Freshness (<= 7.0 minutes)
    2. Confirmed Network Connectivity (data stream + gateway connected)
    3. Arbiter State == ACTIVE & Local Valve == Open
    """

    def __init__(
        self,
        arbiter: CentralExceptionArbiter,
        valve: Optional[LocalHardValve] = None,
        config: Optional[PreBuyGateConfig] = None,
    ):
        self.arbiter = arbiter
        self.valve = valve or LocalHardValve(arbiter=arbiter)
        self.config = config or PreBuyGateConfig()

    def verify_pre_buy(
        self,
        intent: OrderIntent,
        latest_observation_time: Optional[datetime],
        data_stream_connected: bool,
        gateway_connected: bool,
        current_wall_time: Optional[datetime] = None,
    ) -> PreBuyDecision:
        """
        Evaluate pre-buy hard gate conditions synchronously in memory.
        """
        now = current_wall_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # 1. Connectivity Gate
        if not data_stream_connected or not gateway_connected:
            return PreBuyDecision(
                allowed=False,
                reason="REJECTED_NETWORK_DISCONNECTED",
            )

        # 2. Arbiter & Valve Gate
        if not self.arbiter.is_station_tradable(intent.station_id):
            return PreBuyDecision(
                allowed=False,
                reason="REJECTED_STATION_NOT_ACTIVE",
            )

        if not self.valve.is_open(intent.station_id):
            return PreBuyDecision(
                allowed=False,
                reason="REJECTED_VALVE_CLOSED",
            )

        # 3. Observation Freshness Gate
        if latest_observation_time is None:
            return PreBuyDecision(
                allowed=False,
                reason="REJECTED_MISSING_OBSERVATION",
            )

        obs_time = latest_observation_time
        if obs_time.tzinfo is None:
            obs_time = obs_time.replace(tzinfo=timezone.utc)

        age_seconds = (now - obs_time).total_seconds()
        max_age_seconds = self.config.max_observation_age_minutes * 60.0

        if age_seconds > max_age_seconds:
            return PreBuyDecision(
                allowed=False,
                reason="REJECTED_STALE_DATA",
                age_seconds=age_seconds,
            )

        return PreBuyDecision(
            allowed=True,
            reason="APPROVED",
            age_seconds=age_seconds,
        )


class PositionInsulationPolicy:
    """
    Position Insulation and Settlement Escape Hatch (ADR-0014 §2 Principle 4).
    Enforces that filled positions are NEVER dumped at market price during halt/anomalies.
    Within 30 minutes of settlement, transfers authority to manual / risk escape hatch.
    """

    def __init__(self, escape_hatch_window_minutes: float = 30.0):
        self.escape_hatch_window_minutes = escape_hatch_window_minutes

    def evaluate_action(
        self,
        station_id: str,
        station_state: StationLifeCycleState,
        minutes_to_settlement: float,
    ) -> InsulationAction:
        """
        Evaluate the policy for existing filled positions.
        """
        # If in abnormal / halted state
        if station_state != StationLifeCycleState.ACTIVE:
            if minutes_to_settlement <= self.escape_hatch_window_minutes:
                return InsulationAction(
                    allow_market_sell=False,
                    action_type="TRANSFER_TO_SETTLEMENT_ESCAPE_HATCH",
                    requires_manual_intervention=True,
                    details=f"Station {station_id} is {station_state.value} within {minutes_to_settlement:.1f}m of settlement. Transferred to risk escape hatch.",
                )
            return InsulationAction(
                allow_market_sell=False,
                action_type="HOLD_TO_SETTLEMENT",
                requires_manual_intervention=False,
                details=f"Station {station_id} is {station_state.value}. Position insulated, holding to settlement.",
            )

        # Normal active state
        return InsulationAction(
            allow_market_sell=True,
            action_type="NORMAL_POSITION_MANAGEMENT",
            requires_manual_intervention=False,
        )
