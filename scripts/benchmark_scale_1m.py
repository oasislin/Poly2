#!/usr/bin/env python3
"""
scripts/benchmark_scale_1m.py: Scale 1,000,000 Row Benchmark & Numerical Determinism Audit.
Specification: specs/p5_layer2_scenarios.md §2.5 (GATE-L2-05: 规模压测与数值确定性)

Gates audited:
1. End-to-end execution time <= 60.0 seconds.
2. Peak RSS memory <= 1.50 GB.
3. Dual-run independent execution output SHA-256 bitwise identical.
"""

import hashlib
from pathlib import Path
import resource
import sys
import tempfile
import time
from typing import Dict, Any, Tuple

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.standalone_reliability_check import (
    build_dual_track_reliability_table,
    check_monotonicity_and_coverage,
)

MAX_WALL_CLOCK_S = 60.0
MAX_PEAK_RSS_GB = 1.50
NUM_ROWS = 1_000_000


def get_peak_memory_gb() -> float:
    """Return peak resident memory (RSS) in gigabytes."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform == "darwin":
        # macOS reports ru_maxrss in bytes
        return float(rss / (1024 ** 3))
    else:
        # Linux reports ru_maxrss in kilobytes
        return float(rss / (1024 ** 2))


def run_benchmark_pass(seed: int, out_csv: Path) -> Tuple[float, Dict[str, Any]]:
    """Execute one full pass over 1,000,000 records, persisting decision output CSV."""
    t0 = time.perf_counter()

    rng = np.random.default_rng(seed)
    p_pred = rng.uniform(0.01, 0.99, size=NUM_ROWS)
    hit = rng.binomial(1, p_pred).astype(np.float64)
    df = pd.DataFrame({"p_pred": p_pred, "hit": hit})

    res = build_dual_track_reliability_table(
        df,
        num_bins=20,
        min_n_per_bin=30,
        bootstrap_samples=1000,
        seed=20260923,
    )
    decision_table = res["decision_table"]
    audit_res = check_monotonicity_and_coverage(decision_table)

    # Persist decision table to CSV for bitwise verification
    decision_table.to_csv(out_csv, index=False, float_format="%.10f")

    elapsed = time.perf_counter() - t0
    return elapsed, {
        "weighted_ece": float(res["weighted_ece"]),
        "audit": audit_res,
    }


def compute_sha256(path: Path) -> str:
    """Compute file SHA-256."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    print("================================================================================")
    print("      GATE-L2-05: SCALE 1M BENCHMARK & DETERMINISM AUDIT                        ")
    print("================================================================================")
    print(f"Dataset Rows:           {NUM_ROWS:,}")

    with tempfile.TemporaryDirectory() as tmpdir:
        out1 = Path(tmpdir) / "run1_output.csv"
        out2 = Path(tmpdir) / "run2_output.csv"

        # Pass 1
        elapsed1, meta1 = run_benchmark_pass(seed=20260923, out_csv=out1)
        sha1 = compute_sha256(out1)
        rss1 = get_peak_memory_gb()

        # Pass 2 (independent pass with identical seed)
        elapsed2, meta2 = run_benchmark_pass(seed=20260923, out_csv=out2)
        sha2 = compute_sha256(out2)
        peak_rss = get_peak_memory_gb()

        pass_time = (elapsed1 <= MAX_WALL_CLOCK_S) and (elapsed2 <= MAX_WALL_CLOCK_S)
        pass_mem = peak_rss <= MAX_PEAK_RSS_GB
        pass_sha = (sha1 == sha2)
        overall_pass = pass_time and pass_mem and pass_sha

        print(f"Run 1 Wall Clock:       {elapsed1:.2f} s (threshold: <= {MAX_WALL_CLOCK_S:.2f} s) -> {'PASS' if elapsed1 <= MAX_WALL_CLOCK_S else 'FAIL'}")
        print(f"Run 2 Wall Clock:       {elapsed2:.2f} s (threshold: <= {MAX_WALL_CLOCK_S:.2f} s) -> {'PASS' if elapsed2 <= MAX_WALL_CLOCK_S else 'FAIL'}")
        print(f"Peak RSS Memory:        {peak_rss:.3f} GB (threshold: <= {MAX_PEAK_RSS_GB:.2f} GB) -> {'PASS' if pass_mem else 'FAIL'}")
        print(f"Run 1 Output SHA-256:   {sha1}")
        print(f"Run 2 Output SHA-256:   {sha2}")
        print(f"SHA-256 Bitwise Match:  {sha1 == sha2} -> {'PASS' if pass_sha else 'FAIL'}")
        print("--------------------------------------------------------------------------------")
        print(f"OVERALL GATE-L2-05:     {'PASS' if overall_pass else 'FAIL'}")
        print("================================================================================")

        return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
