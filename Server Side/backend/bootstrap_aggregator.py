"""
WattWise Bootstrap Aggregator
=============================
One-shot startup job that ensures the dashboard is populated with all
available history on every `docker compose up`.

Steps (idempotent):
1. aggregate_all_history — hourly + daily summaries + home_daily_totals
   over the full range of recorded energy_readings
2. compute_rankings — fills energy_rankings for the most recent day
3. classify_all_users — assigns each user to a persona based on history

Designed to run as a one-shot container after the backend is healthy and
the db-seed job has completed.
"""

import asyncio
import logging
import sys

from app.scheduler import aggregate_all_history, compute_rankings_for_range
from app.persona_classifier import classify_all_users, seed_default_personas
from app.database import AsyncSessionLocal

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
        summary = await aggregate_all_history()
        log.info("Aggregation summary: %s", summary)
    except Exception:
        log.exception("aggregate_all_history failed")
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
