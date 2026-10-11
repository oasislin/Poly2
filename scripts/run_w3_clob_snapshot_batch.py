#!/usr/bin/env python3
"""
W3 Polymarket CLOB Snapshot Batch Runner (Time-Insensitive Periodic Batch Processor).
Governed by docs/w3_polymarket_ingestion_preregistration.md Rev.1.1 (Criteria A-1, A-2, A-3, A-5, B-4, E-1, E-2, E-4, E-5).

Execution Discipline (Criterion A-5):
- Single-shot discrete batch execution; strictly NON-DAEMON, NO background persistent loops.
- Intended for execution via external cron:
    * Baseline layer: Every 60 minutes (0 * * * *)
    * Settlement probe layer: Every 15 minutes (*/15 * * * *)
- C5 Boundaries: Strictly zero private keys, zero order submissions, public read-only API calls.
"""

import argparse
from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import sys
from typing import List, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.data_acquisition.polymarket_clob_collector import (
    PolymarketCLOBCollector,
    PolymarketReadOnlyCLOBClient,
    PolymarketTemperatureMarket,
    calculate_snapshot_cadence,
)
from src.prediction.real_emos_pipeline import RealEMOSPipeline
from src.pricing.paper_evaluation_engine import PaperEvaluationEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("w3_clob_batch")


def run_snapshot_batch(
    layer_filter: str = "ALL",
    cities: Optional[List[str]] = None,
    proxy_url: Optional[str] = None,
    save_raw_snapshots: bool = True,
) -> int:
    """
    Execute one complete batch cycle of Polymarket CLOB orderbook ingestion and paper evaluation.
    Returns the count of successfully evaluated markets.
    """
    start_time = datetime.now(timezone.utc)
    logger.info(f"=== Starting W3 CLOB Snapshot Batch Cycle at {start_time.isoformat()} (Filter: {layer_filter}) ===")

    # 1. Initialize Read-Only Client & Collector
    proxy = proxy_url or os.getenv("POLYMARKET_HTTP_PROXY")
    client = PolymarketReadOnlyCLOBClient(proxy=proxy)
    collector = PolymarketCLOBCollector(client=client)

    # 2. Discover Active Markets
    markets = collector.discover_active_temperature_markets(cities=cities)
    logger.info(f"Discovered {len(markets)} active temperature markets across targeted cities.")

    # 3. Initialize Prediction and Evaluation Engines
    pipeline = RealEMOSPipeline()
    engine = PaperEvaluationEngine()

    evaluated_count = 0
    positive_ev_count = 0
    quarantined_count = 0
    suspect_count = 0

    for m in markets:
        cadence = calculate_snapshot_cadence(m.official_settlement_time, start_time)

        # Apply Layer Filter
        if layer_filter == "BASELINE" and cadence != "BASELINE_60M":
            continue
        elif layer_filter == "PROBE" and cadence != "SETTLEMENT_PROBE_15M":
            continue
        elif cadence == "POST_SETTLEMENT":
            logger.info(f"Skipping market {m.slug}: already post-settlement ({m.official_settlement_time.isoformat()}).")
            continue

        logger.info(f"Processing market [{cadence}]: {m.slug} (Station: {m.station_id})")

        try:
            # 4. Ingest Orderbook Snapshot
            snap = collector.collect_market_snapshot(m, now_utc=start_time)
            if save_raw_snapshots:
                collector.save_snapshot_record(snap)

            # 5. Predict Physical EMOS Distribution
            target_dt = datetime.strptime(m.target_date_str, "%Y-%m-%d").date()
            cycle_date = start_time.date()
            diff_days = max(1, (target_dt - cycle_date).days)
            lead_hours = min(72, max(24, diff_days * 24))
            forecast_cycle = datetime(cycle_date.year, cycle_date.month, cycle_date.day, 0, 0, tzinfo=timezone.utc)

            forecast = pipeline.predict(
                station_id=m.station_id,
                target_date=m.target_date_str,
                lead_hours=lead_hours,
                forecast_cycle=forecast_cycle,
            )

            # 6. Evaluate Snapshot
            eval_res = engine.evaluate_market_snapshot(
                market=m,
                snapshot=snap,
                mu=forecast.mu,
                sigma=forecast.sigma,
                prob_source=forecast.prob_source,
            )

            # 7. Persist Full Evaluation Ledger (B-4)
            saved_eval_path = engine.save_evaluation_snapshot(eval_res)

            evaluated_count += 1
            positive_ev_count += eval_res.summary.get("positive_ev_signals", 0)
            quarantined_count += eval_res.summary.get("quarantined_signals", 0)
            if eval_res.summary.get("is_input_suspect", False):
                suspect_count += 1

            logger.info(
                f"Evaluated {m.slug}: Status={eval_res.prob_source}, "
                f"MedianDev={eval_res.summary.get('median_deviation')}°F, "
                f"PosEV={eval_res.summary.get('positive_ev_signals')}, "
                f"Quarantined={eval_res.summary.get('quarantined_signals')} -> {saved_eval_path.name}"
            )

        except Exception as exc:
            logger.error(f"Error processing market {m.slug}: {exc}", exc_info=True)

    duration = (datetime.now(timezone.utc) - start_time).total_seconds()
    logger.info(
        f"=== Batch Complete in {duration:.2f}s: Evaluated={evaluated_count}, "
        f"PosEV={positive_ev_count}, Quarantined={quarantined_count}, Suspect={suspect_count} ==="
    )
    return evaluated_count


def main():
    parser = argparse.ArgumentParser(description="W3 Polymarket CLOB Snapshot Batch Runner")
    parser.add_argument(
        "--layer",
        choices=["ALL", "BASELINE", "PROBE"],
        default="ALL",
        help="Cadence layer to execute (default: ALL)",
    )
    parser.add_argument(
        "--cities",
        nargs="+",
        default=None,
        help="Specific cities to target (e.g. miami chicago)",
    )
    parser.add_argument(
        "--proxy",
        default=None,
        help="HTTP proxy URL (e.g. http://127.0.0.1:7897)",
    )
    args = parser.parse_args()

    count = run_snapshot_batch(
        layer_filter=args.layer,
        cities=args.cities,
        proxy_url=args.proxy,
    )
    sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    main()
