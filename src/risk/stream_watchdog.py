"""
Two-Tier Stream Risk Watchdog and Hysteresis Recovery (Phase 2 Task 02 - Ticket 04 / Issue #68).
Implements ADR-0011 §D3 CancelAll quotes protocol (15m arrival heartbeat) and
Tier 2 observation staleness (35m physical staleness) with 3-frame hysteresis recovery.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
import logging
from typing import Dict, Optional

from src.data_acquisition.observation_stream import ObservationPacket

logger = logging.getLogger(__name__)


class RiskLevel(str, Enum):
    """Tiered risk levels for observation stream health."""
    HEALTHY = "HEALTHY"
    WARNING = "WARNING"  # Arrival heartbeat timeout (>15m) -> Cancel resting Maker quotes
    DATA_STALENESS = "DATA_STALENESS"  # Physical staleness (>35m) -> SAFE_MODE circuit breaker


@dataclass(frozen=True)
class WatchdogConfig:
    """Configurable thresholds for two-tier stream risk watchdog (ADR-0011)."""
    arrival_heartbeat_timeout_minutes: float = 15.0
    physical_staleness_timeout_minutes: float = 35.0
    recovery_staleness_threshold_minutes: float = 20.0
    consecutive_healthy_frames_required: int = 3


@dataclass(frozen=True)
class RiskStatus:
    """Evaluation snapshot for station's stream risk status."""
    station_id: str
    level: RiskLevel
    cancel_all_quotes: bool
    safe_mode: bool
    arrival_lag_seconds: float
    physical_staleness_seconds: float
    consecutive_healthy_frames: int
    reason: str


class StreamRiskWatchdog:
    """
    Evaluates observation stream health per station across arrival heartbeat and physical age.
    Triggers CancelAll on 15m heart-beat timeout, and SAFE_MODE on 35m physical staleness.
    Requires 3 consecutive healthy frames to recover from degraded states.
    """

    def __init__(self, config: Optional[WatchdogConfig] = None):
        self.config = config or WatchdogConfig()
        # station_id -> state dict
        self._states: Dict[str, Dict] = {}

    def record_packet(
        self,
        packet: ObservationPacket,
        arrival_wall_time: Optional[datetime] = None,
    ) -> None:
        """Record an incoming observation packet arrival."""
        station = packet.station_id
        wall_now = arrival_wall_time or datetime.now(timezone.utc)
        if wall_now.tzinfo is None:
            wall_now = wall_now.replace(tzinfo=timezone.utc)

        obs_ts = packet.timestamp_utc
        if obs_ts.tzinfo is None:
            obs_ts = obs_ts.replace(tzinfo=timezone.utc)

        if station not in self._states:
            self._states[station] = {
                "last_arrival_time": wall_now,
                "last_observation_time": obs_ts,
                "current_level": RiskLevel.HEALTHY,
                "consecutive_healthy_frames": 1,
            }
            return

        st = self._states[station]
        st["last_arrival_time"] = wall_now
        st["last_observation_time"] = obs_ts

        # Check if incoming packet is fresh enough to count toward recovery
        physical_staleness_min = (wall_now - obs_ts).total_seconds() / 60.0
        if physical_staleness_min <= self.config.recovery_staleness_threshold_minutes:
            st["consecutive_healthy_frames"] += 1
        else:
            st["consecutive_healthy_frames"] = 0

    def evaluate(
        self,
        station_id: str,
        current_wall_time: Optional[datetime] = None,
    ) -> RiskStatus:
        """
        Evaluate the risk status of a station at current wall clock time.
        """
        wall_now = current_wall_time or datetime.now(timezone.utc)
        if wall_now.tzinfo is None:
            wall_now = wall_now.replace(tzinfo=timezone.utc)

        st = self._states.get(station_id)
        if not st:
            return RiskStatus(
                station_id=station_id,
                level=RiskLevel.DATA_STALENESS,
                cancel_all_quotes=True,
                safe_mode=True,
                arrival_lag_seconds=float("inf"),
                physical_staleness_seconds=float("inf"),
                consecutive_healthy_frames=0,
                reason=f"Station {station_id} has no recorded observation packets.",
            )

        arrival_lag_sec = max(0.0, (wall_now - st["last_arrival_time"]).total_seconds())
        physical_age_sec = max(0.0, (wall_now - st["last_observation_time"]).total_seconds())

        arrival_timeout_sec = self.config.arrival_heartbeat_timeout_minutes * 60.0
        staleness_timeout_sec = self.config.physical_staleness_timeout_minutes * 60.0

        current_level = st["current_level"]

        # 1. Tier 2 Check: Physical Staleness Timeout (>35m)
        if physical_age_sec > staleness_timeout_sec:
            st["current_level"] = RiskLevel.DATA_STALENESS
            st["consecutive_healthy_frames"] = 0
            return RiskStatus(
                station_id=station_id,
                level=RiskLevel.DATA_STALENESS,
                cancel_all_quotes=True,
                safe_mode=True,
                arrival_lag_seconds=arrival_lag_sec,
                physical_staleness_seconds=physical_age_sec,
                consecutive_healthy_frames=0,
                reason=(
                    f"Physical staleness timeout: age={physical_age_sec / 60.0:.1f}m > "
                    f"{self.config.physical_staleness_timeout_minutes}m"
                ),
            )

        # 2. Tier 1 Check: Arrival Heartbeat Timeout (>15m)
        if arrival_lag_sec > arrival_timeout_sec:
            st["current_level"] = RiskLevel.WARNING
            st["consecutive_healthy_frames"] = 0
            return RiskStatus(
                station_id=station_id,
                level=RiskLevel.WARNING,
                cancel_all_quotes=True,
                safe_mode=False,
                arrival_lag_seconds=arrival_lag_sec,
                physical_staleness_seconds=physical_age_sec,
                consecutive_healthy_frames=0,
                reason=(
                    f"Arrival heartbeat timeout: lag={arrival_lag_sec / 60.0:.1f}m > "
                    f"{self.config.arrival_heartbeat_timeout_minutes}m"
                ),
            )

        # 3. Check Hysteresis Recovery if currently in degraded level
        if current_level in (RiskLevel.WARNING, RiskLevel.DATA_STALENESS):
            # Recovery condition:
            # - Physical staleness <= recovery_threshold (20m)
            # - Consecutive healthy frames >= 3
            recovery_threshold_sec = self.config.recovery_staleness_threshold_minutes * 60.0
            if (
                physical_age_sec <= recovery_threshold_sec
                and st["consecutive_healthy_frames"] >= self.config.consecutive_healthy_frames_required
            ):
                logger.info(
                    "Station %s successfully recovered to HEALTHY after %d healthy frames (age=%.1fm)",
                    station_id,
                    st["consecutive_healthy_frames"],
                    physical_age_sec / 60.0,
                )
                st["current_level"] = RiskLevel.HEALTHY
            else:
                # Retain previous degraded level
                return RiskStatus(
                    station_id=station_id,
                    level=current_level,
                    cancel_all_quotes=True,
                    safe_mode=(current_level == RiskLevel.DATA_STALENESS),
                    arrival_lag_seconds=arrival_lag_sec,
                    physical_staleness_seconds=physical_age_sec,
                    consecutive_healthy_frames=st["consecutive_healthy_frames"],
                    reason=(
                        f"In recovery: consecutive_frames={st['consecutive_healthy_frames']}/"
                        f"{self.config.consecutive_healthy_frames_required}, age={physical_age_sec / 60.0:.1f}m"
                    ),
                )

        # 4. Healthy State
        return RiskStatus(
            station_id=station_id,
            level=RiskLevel.HEALTHY,
            cancel_all_quotes=False,
            safe_mode=False,
            arrival_lag_seconds=arrival_lag_sec,
            physical_staleness_seconds=physical_age_sec,
            consecutive_healthy_frames=st["consecutive_healthy_frames"],
            reason="Stream feeds healthy and timely.",
        )
