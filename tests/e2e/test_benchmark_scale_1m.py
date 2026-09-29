"""
tests/e2e/test_benchmark_scale_1m.py: E2E Test Wrapper for GATE-L2-05 Benchmark.
Specification: specs/p5_layer2_scenarios.md §2.5 (GATE-L2-05: 规模压测与数值确定性)
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
BENCHMARK_SCRIPT = PROJECT_ROOT / "scripts" / "benchmark_scale_1m.py"


def test_gate_l2_05_scale_1m_benchmark():
    """Execute benchmark_scale_1m.py and assert exit code 0."""
    res = subprocess.run(
        [sys.executable, str(BENCHMARK_SCRIPT)],
        capture_output=True,
        text=True,
        check=False,
    )
    print(res.stdout)
    assert res.returncode == 0, f"Benchmark script failed:\n{res.stdout}\n{res.stderr}"
    assert "OVERALL GATE-L2-05:     PASS" in res.stdout
