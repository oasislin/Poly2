"""
Simulation Clock for Event-Driven Paper Trading (Phase 2 Task 07 - Ticket 01 / Issue #95).
Supports dual-mode execution:
- REPLAY mode: Discrete deterministic step advancement for backtests and simulations.
- REALTIME mode: System wall-clock advancement for live paper trading.
"""

from datetime import datetime, timezone, timedelta
from enum import Enum
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class SimulationClockMode(str, Enum):
    REPLAY = "REPLAY"
    REALTIME = "REALTIME"


class SimulationClock:
    """
    Clock controller for coordinating simulated time across components.
    """

    def __init__(
        self,
        mode: SimulationClockMode = SimulationClockMode.REPLAY,
        initial_time: Optional[datetime] = None,
    ):
        self.mode = mode
        if initial_time is not None:
            if initial_time.tzinfo is None:
                self._current_time = initial_time.replace(tzinfo=timezone.utc)
            else:
                self._current_time = initial_time
        else:
            self._current_time = datetime.now(timezone.utc)

    def now(self) -> datetime:
        """Return the current simulated time."""
        if self.mode == SimulationClockMode.REALTIME:
            return datetime.now(timezone.utc)
        return self._current_time

    def advance(self, delta: timedelta) -> datetime:
        """
        Advance simulated time by the given delta in REPLAY mode.
        Raises ValueError if delta is negative.
        Raises RuntimeError if in REALTIME mode.
        """
        if self.mode == SimulationClockMode.REALTIME:
            raise RuntimeError("Cannot manually advance time in REALTIME mode")

        if delta < timedelta(0):
            raise ValueError(f"Simulation time cannot advance backward: {delta}")

        self._current_time += delta
        return self._current_time

    def set_time(self, new_time: datetime) -> datetime:
        """
        Set simulated time directly to a specific timestamp in REPLAY mode.
        """
        if self.mode == SimulationClockMode.REALTIME:
            raise RuntimeError("Cannot manually set time in REALTIME mode")

        if new_time.tzinfo is None:
            target = new_time.replace(tzinfo=timezone.utc)
        else:
            target = new_time

        if target < self._current_time:
            raise ValueError(f"Simulation time cannot move backward: {target} < {self._current_time}")

        self._current_time = target
        return self._current_time
