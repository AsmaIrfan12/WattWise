"""
WattWise Bootstrap Aggregator
=============================
One-shot startup job that ensures the dashboard is populated with all
available history on every `docker compose up`.

Steps (idempotent):
1. backfill_recent — hourly + daily summaries + home_daily_totals for a bounded
   RECENT window (not the full history: aggregate_all_history is O(all hours) and
   hangs once a deployment accumulates months of readings, which then blocks the
   rankings + classify steps below). The scheduled 30-min job keeps it current after.
2. compute_rankings_for_range — fills energy_rankings for the aggregated range
3. classify_all_users — assigns each user to a persona based on history

Designed to run as a one-shot container after the backend is healthy and
the db-seed job has completed.
"""

import asyncio
import logging
import os
import sys

from app.scheduler import backfill_recent, compute_rankings_for_range
from app.persona_classifier import classify_all_users, seed_default_personas
from app.database import AsyncSessionLocal

# Bounded backfill window (days). Big enough for the 30-day persona/ranking windows
# with margin, small enough to finish quickly. Override via BOOTSTRAP_BACKFILL_DAYS.
BACKFILL_DAYS = int(os.getenv("BOOTSTRAP_BACKFILL_DAYS", "35"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("bootstrap")


async def main() -> int:
    log.info("=" * 60)
    log.info("WattWise bootstrap aggregator starting")
    log.info("=" * 60)

    try:
        summary = await backfill_recent(hours=BACKFILL_DAYS * 24)
        log.info("Recent aggregation summary (%d days): %s", BACKFILL_DAYS, summary)
    except Exception:
        log.exception("backfill_recent failed")
        return 1

    try:
        counts = await compute_rankings_for_range()
        log.info("Rankings computed for full range: %s", counts)
    except Exception:
        log.exception("compute_rankings_for_range failed")
        return 1

    try:
        async with AsyncSessionLocal() as db:
            await seed_default_personas(db)
            classification = await classify_all_users(db)
        log.info("Persona classification: %s", classification)
    except Exception:
        log.exception("classify_all_users failed")
        return 1

    log.info("Bootstrap aggregator finished successfully")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
