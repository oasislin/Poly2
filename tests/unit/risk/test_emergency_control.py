"""
Unit tests for EmergencyFileSentinel and risk operations CLI (Phase 2 Task 03 - Ticket 04 / Issue #74).
Implements ADR-0014 §2 emergency stop file sentinel and CLI kill-switch.
"""

from pathlib import Path
import pytest
from unittest.mock import MagicMock

from src.risk.central_arbiter import CentralExceptionArbiter, StationLifeCycleState
from src.risk.emergency_control import EmergencyFileSentinel
from src.risk.pre_buy_gate import LocalHardValve
from src.risk.cli import run_cli


class TestEmergencyFileSentinel:
    """Test suite for file-based emergency stop sentinel detection."""

    @pytest.fixture
    def workspace(self, tmp_path):
        return tmp_path

    @pytest.fixture
    def arbiter(self):
        return CentralExceptionArbiter()

    @pytest.fixture
    def valve(self, arbiter):
        return LocalHardValve(arbiter=arbiter)

    def test_station_sentinel_file_detection(self, workspace, arbiter, valve):
        """Verify detecting EMERGENCY_STOP_<STATION> halts station and shuts valve."""
        sentinel = EmergencyFileSentinel(root_dir=workspace, arbiter=arbiter, valve=valve)

        # Create sentinel file for KORD
        sentinel_file = workspace / "EMERGENCY_STOP_KORD"
        sentinel_file.touch()

        halted = sentinel.check_sentinels()

        assert "KORD" in halted
        assert arbiter.get_station_state("KORD") == StationLifeCycleState.EMERGENCY_HALT
        assert valve.is_open("KORD") is False
        assert arbiter.get_station_state("KLGA") == StationLifeCycleState.ACTIVE

    def test_global_sentinel_file_detection(self, workspace, arbiter, valve):
        """Verify detecting EMERGENCY_STOP_ALL halts all stations globally."""
        sentinel = EmergencyFileSentinel(root_dir=workspace, arbiter=arbiter, valve=valve)

        sentinel_file = workspace / "EMERGENCY_STOP_ALL"
        sentinel_file.touch()

        halted = sentinel.check_sentinels()

        assert "GLOBAL" in halted
        assert arbiter.get_station_state("KORD") == StationLifeCycleState.EMERGENCY_HALT
        assert arbiter.get_station_state("KLGA") == StationLifeCycleState.EMERGENCY_HALT
        assert valve.is_open("KORD") is False
        assert valve.is_open("KLGA") is False

    def test_create_and_remove_sentinel_helper(self, workspace, arbiter, valve):
        """Verify create_sentinel and remove_sentinel file lifecycle."""
        sentinel = EmergencyFileSentinel(root_dir=workspace, arbiter=arbiter, valve=valve)

        sentinel.create_sentinel("KDAL")
        assert (workspace / "EMERGENCY_STOP_KDAL").exists()
        sentinel.check_sentinels()
        assert arbiter.get_station_state("KDAL") == StationLifeCycleState.EMERGENCY_HALT

        sentinel.remove_sentinel("KDAL")
        assert not (workspace / "EMERGENCY_STOP_KDAL").exists()
        arbiter.reset_emergency_halt("KDAL")
        valve.open_valve("KDAL")
        assert arbiter.get_station_state("KDAL") == StationLifeCycleState.ACTIVE
        assert valve.is_open("KDAL") is True


class TestRiskCLI:
    """Test suite for command-line kill switch operations."""

    def test_cli_stop_and_resume_station(self, tmp_path, capsys):
        """Verify 'stop' and 'resume' CLI commands."""
        # Run CLI stop KORD
        exit_code = run_cli(["stop", "KORD", "--root-dir", str(tmp_path)])
        assert exit_code == 0
        assert (tmp_path / "EMERGENCY_STOP_KORD").exists()
        captured = capsys.readouterr()
        assert "EMERGENCY STOP initiated for station 'KORD'" in captured.out

        # Run CLI status
        exit_code_status = run_cli(["status", "--root-dir", str(tmp_path)])
        assert exit_code_status == 0
        captured_status = capsys.readouterr()
        assert "EMERGENCY_STOP_KORD" in captured_status.out

        # Run CLI resume KORD
        exit_code_resume = run_cli(["resume", "KORD", "--root-dir", str(tmp_path)])
        assert exit_code_resume == 0
        assert not (tmp_path / "EMERGENCY_STOP_KORD").exists()
        captured_resume = capsys.readouterr()
        assert "Resumed station 'KORD'" in captured_resume.out

    def test_cli_invalid_station_rejected(self, tmp_path, capsys):
        """Verify non-active station in CLI is rejected with exit code 1."""
        exit_code = run_cli(["stop", "KDCA", "--root-dir", str(tmp_path)])
        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Invalid target 'KDCA'" in captured.err
