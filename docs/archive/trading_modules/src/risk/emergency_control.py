"""
Emergency File Sentinel and Kill-Switch Controller (Phase 2 Task 03 - Ticket 04 / Issue #74).
Implements ADR-0014 §2 and Phase 2 Execution Document v2.0 §3.4 emergency stop protocol.
Monitors root directory for EMERGENCY_STOP_<STATION> and EMERGENCY_STOP_ALL trigger files.
"""

import logging
from pathlib import Path
from typing import Dict, List, Optional, Set

from src.data_processing.constants import ACTIVE_10_STATIONS
from src.risk.central_arbiter import CentralExceptionArbiter
from src.risk.pre_buy_gate import LocalHardValve

logger = logging.getLogger(__name__)

ALL_TARGETS: Set[str] = set(ACTIVE_10_STATIONS) | {"ALL", "GLOBAL"}


class EmergencyFileSentinel:
    """
    Monitors the filesystem for emergency stop trigger files.
    - EMERGENCY_STOP_<STATION>: e.g. EMERGENCY_STOP_KORD
    - EMERGENCY_STOP_ALL: Halts all stations globally
    """

    def __init__(
        self,
        root_dir: Optional[Path] = None,
        arbiter: Optional[CentralExceptionArbiter] = None,
        valve: Optional[LocalHardValve] = None,
    ):
        self.root_dir = Path(root_dir) if root_dir else Path.cwd()
        self.arbiter = arbiter
        self.valve = valve

    def _get_station_sentinel_path(self, station_id: str) -> Path:
        target = "ALL" if station_id == "GLOBAL" else station_id
        return self.root_dir / f"EMERGENCY_STOP_{target}"

    def create_sentinel(self, target: str) -> Path:
        """Create an emergency stop trigger file."""
        path = self._get_station_sentinel_path(target)
        path.touch()
        logger.critical(f"EMERGENCY SENTINEL CREATED: {path}")
        return path

    def remove_sentinel(self, target: str) -> bool:
        """Remove an emergency stop trigger file if it exists."""
        path = self._get_station_sentinel_path(target)
        if path.exists():
            path.unlink()
            logger.info(f"EMERGENCY SENTINEL REMOVED: {path}")
            return True
        return False

    def list_active_sentinels(self) -> List[str]:
        """List all active sentinel markers found in root_dir."""
        active = []
        global_path = self.root_dir / "EMERGENCY_STOP_ALL"
        if global_path.exists():
            active.append("EMERGENCY_STOP_ALL")

        for st in ACTIVE_10_STATIONS:
            p = self.root_dir / f"EMERGENCY_STOP_{st}"
            if p.exists():
                active.append(f"EMERGENCY_STOP_{st}")
        return active

    def check_sentinels(self) -> Set[str]:
        """
        Scan directory for emergency stop files and synchronously trigger halts and valve closures.
        Returns the set of halted targets ('GLOBAL' or individual station_ids).
        """
        halted = set()

        # 1. Global Sentinel Check
        global_path = self.root_dir / "EMERGENCY_STOP_ALL"
        if global_path.exists():
            halted.add("GLOBAL")
            if self.arbiter:
                self.arbiter.set_emergency_halt("GLOBAL", reason="SENTINEL_EMERGENCY_STOP_ALL")
            if self.valve:
                self.valve.close_valve("GLOBAL", reason="SENTINEL_EMERGENCY_STOP_ALL")
            return halted

        # 2. Per-Station Sentinel Check
        for st in ACTIVE_10_STATIONS:
            p = self.root_dir / f"EMERGENCY_STOP_{st}"
            if p.exists():
                halted.add(st)
                if self.arbiter:
                    self.arbiter.set_emergency_halt(st, reason=f"SENTINEL_EMERGENCY_STOP_{st}")
                if self.valve:
                    self.valve.close_valve(st, reason=f"SENTINEL_EMERGENCY_STOP_{st}")

        return halted
