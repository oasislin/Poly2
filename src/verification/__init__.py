"""
Verification package for physical weather model validation.
"""


def __getattr__(name: str):
    if name in ("GateReport", "run_reliability_gate"):
        from src.verification.p5_gate import GateReport as _GateReport, run_reliability_gate as _run_gate
        return _GateReport if name == "GateReport" else _run_gate
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = ["GateReport", "run_reliability_gate"]

