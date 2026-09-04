#!/usr/bin/env python3
"""
CLI tool to probe IEM ASOS historical coverage for stations.
Usage:
  python scripts/probe_iem_coverage.py --station KLGA
  python scripts/probe_iem_coverage.py --batch-stations KLGA KORD KBKF KMIA KDEN
"""

import argparse
import json
from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from src.data_acquisition.iem_coverage_prober import IemCoverageProber


def main():
    parser = argparse.ArgumentParser(description="Probe IEM historical coverage")
    parser.add_argument("--station", help="Station ICAO code")
    parser.add_argument("--batch-stations", nargs="+", help="List of station ICAO codes")
    parser.add_argument("--start-year", type=int, default=2000, help="Start year (default: 2000)")
    parser.add_argument("--end-year", type=int, default=2018, help="End year (default: 2018)")
    args = parser.parse_args()

    prober = IemCoverageProber()

    if args.batch_stations:
        res = prober.probe_batch(args.batch_stations, start_year=args.start_year, end_year=args.end_year)
        for stid, r in res.items():
            print(f"[{stid}] Coverage: {r.coverage_pct:.1f}% ({r.status}) - Passed: {r.passed_gate}")
    elif args.station:
        r = prober.probe_station_coverage(args.station, start_year=args.start_year, end_year=args.end_year)
        print(json.dumps({
            "station": r.station,
            "network": r.network,
            "period": f"{r.start_year}-{r.end_year}",
            "coverage_pct": r.coverage_pct,
            "passed_gate": r.passed_gate,
            "status": r.status,
        }, indent=2))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
