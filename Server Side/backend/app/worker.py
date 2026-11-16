"""
WattWise worker — the single ingestion + scheduling process.

    python -m app.worker

One instance runs alongside the API. It is the only MQTT telemetry consumer and the
only scheduler, which removes two problems the multi-worker API had:

  • Readings were lost whenever the API restarted (clean sessions on a shared
    subscription). The worker keeps a persistent session under a fixed client id, so
    the broker queues QoS-1 readings while it is down and delivers them afterwards.
  • "Exactly one scheduler" depended on a MySQL advisory lock held by whichever uvicorn
    worker won a race. Here there is simply one process. The lock is still taken, so a
    second worker started by mistake waits instead of doubling every job.

A heartbeat file is touched every 30 s for the container healthcheck.
"""
import asyncio
import logging
import signal
from pathlib import Path

from sqlalchemy import text

from app.config import settings
from app.database import AsyncSessionLocal, engine, init_db
from app.main import _job_backfill_startup, _security_warnings, register_jobs, scheduler
from app.mqtt_client import publish_ingest_stats, start_mqtt, stop_mqtt
from app.persona_classifier import seed_default_personas

logger = logging.getLogger("worker")

HEARTBEAT_FILE = Path("/tmp/wattwise-worker-alive")
HEARTBEAT_SECONDS = 30
LOCK_NAME = "ww_scheduler"


async def _acquire_scheduler_lock(stop: asyncio.Event):
    """Hold the scheduler lock for this process's lifetime; wait if another process has it."""
    conn = await engine.connect()
    waited = False
    while not stop.is_set():
        if (await conn.execute(text("SELECT GET_LOCK(:n, 10)"), {"n": LOCK_NAME})).scalar():
            return conn
        if not waited:
            logger.info("Another process holds the scheduler lock — waiting for it to exit…")
            waited = True
    await conn.close()
    return None


async def _heartbeat(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            HEARTBEAT_FILE.touch()
            publish_ingest_stats()
        except Exception as e:  # never let bookkeeping stop the worker
            logger.debug("heartbeat: %s", e)
        try:
            await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            pass


async def main() -> int:
    logger.info("🔧 WattWise worker starting (ingestion + scheduler)…")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows event loops
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

    await init_db()
    for warning in _security_warnings():
        logger.warning("Security posture: %s", warning)
    async with AsyncSessionLocal() as db:
        await seed_default_personas(db)

    start_mqtt("worker")
    heartbeat = asyncio.create_task(_heartbeat(stop))

    lock_conn = await _acquire_scheduler_lock(stop)
    if lock_conn is not None:
        register_jobs()
        scheduler.start()
        logger.info("✅ Worker owns the scheduler — %d jobs registered", len(scheduler.get_jobs()))
        asyncio.create_task(_job_backfill_startup())

    await stop.wait()
    logger.info("Worker stopping…")

    if scheduler.running:
        scheduler.shutdown(wait=False)
    stop_mqtt()   # disconnects but KEEPS the broker session, so readings queue until the next start
    heartbeat.cancel()
    if lock_conn is not None:
        try:
            await lock_conn.execute(text("SELECT RELEASE_LOCK(:n)"), {"n": LOCK_NAME})
        finally:
            await lock_conn.close()
    await engine.dispose()
    logger.info("Worker stopped cleanly")
    return 0


if __name__ == "__main__":
    if settings.PROCESS_ROLE not in ("worker", "all"):
        logger.warning("PROCESS_ROLE=%s but app.worker was started — running as worker", settings.PROCESS_ROLE)
    raise SystemExit(asyncio.run(main()))
