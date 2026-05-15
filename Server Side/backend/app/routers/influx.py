"""
WattWise — InfluxDB Entity-Based Query Router
==============================================

Direct time-series access to InfluxDB for device power / current / switch-state
streams collected by the RaspberryPi MQTT bridge.

Security model
--------------
- All routes require a valid JWT.
- A regular user may ONLY query entity_ids that belong to one of their own
  active devices (entity_id / power_entity_id / switch_entity_id). Any other
  entity_id returns 404 — a user can never read another household's telemetry.
- An admin (is_admin=True) may query any entity_id (full-fleet visibility is a
  product requirement for the research operator).
- entity_id is additionally validated against a strict character whitelist and
  is only ever passed to InfluxQL after being confirmed to exist in the owned
  set, eliminating InfluxQL injection.

Base URL: /api/influx/
"""

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.concurrency import run_in_threadpool
from influxdb import InfluxDBClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import Device, Home

logger = logging.getLogger("influx_router")

router = APIRouter(prefix="/api/influx", tags=["InfluxDB (Entity)"])

# entity_ids are Home Assistant identifiers: letters, digits, _ . : -
_ENTITY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")

# Reused across requests — opening a new InfluxDBClient per call adds TCP/handshake
# latency and leaks sockets under load.
_influx_client: Optional[InfluxDBClient] = None


def _get_influx() -> InfluxDBClient:
    global _influx_client
    if _influx_client is None:
        _influx_client = InfluxDBClient(
            host=settings.INFLUX_HOST,
            port=settings.INFLUX_PORT,
            username=settings.INFLUX_USER,
            password=settings.INFLUX_PASS,
            database=settings.INFLUX_DB,
        )
    return _influx_client


def _get_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


def _is_admin(request: Request) -> bool:
    return bool(getattr(request.state, "is_admin", False))


async def _owned_entity_ids(db: AsyncSession, user_id: int) -> set[str]:
    """All entity_ids (data / power / switch) for the user's active devices."""
    result = await db.execute(
        select(
            Device.entity_id, Device.power_entity_id, Device.switch_entity_id
        )
        .join(Home, Device.home_id == Home.id)
        .where(Home.user_id == user_id, Device.is_active)
    )
    owned: set[str] = set()
    for data_id, power_id, switch_id in result.all():
        for eid in (data_id, power_id, switch_id):
            if eid:
                owned.add(eid)
    return owned


async def _assert_entity_access(
    db: AsyncSession, request: Request, entity_id: str
) -> None:
    """404 unless the caller owns this entity_id (admins bypass)."""
    if not _ENTITY_RE.match(entity_id):
        raise HTTPException(status_code=404, detail="Entity not found")
    if _is_admin(request):
        return
    user_id = _get_user_id(request)
    if entity_id not in await _owned_entity_ids(db, user_id):
        raise HTTPException(status_code=404, detail="Entity not found")


def _run_query(query: str) -> list[dict]:
    """Execute an InfluxQL query (blocking — call via run_in_threadpool)."""
    try:
        result = _get_influx().query(query)
        return list(result.get_points())
    except Exception as e:
        logger.error(f"InfluxDB query error: {e} — query: {query[:200]}")
        raise HTTPException(status_code=503, detail="InfluxDB query failed")


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/entities")
async def list_entities(request: Request, db: AsyncSession = Depends(get_db)):
    """List entity_ids the caller is allowed to see (own devices; admin = all)."""
    user_id = _get_user_id(request)
    if _is_admin(request):
        rows = await run_in_threadpool(
            _run_query, 'SHOW TAG VALUES FROM "state" WITH KEY = "entity_id"'
        )
        entity_ids = sorted({(r.get("value") or "") for r in rows if r.get("value")})
    else:
        entity_ids = sorted(await _owned_entity_ids(db, user_id))
    return {
        "message": "Available entities",
        "count": len(entity_ids),
        "entities": entity_ids,
    }


@router.get("/entity/{entity_id}")
async def get_entity_data(
    entity_id: str,
    request: Request,
    hours: Optional[int] = Query(default=None, ge=1, le=720),
    days: Optional[int] = Query(default=None, ge=1, le=90),
    limit: int = Query(default=200, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
):
    """Time-ranged raw data for an entity_id the caller owns."""
    await _assert_entity_access(db, request, entity_id)

    if days:
        time_range = f"time > now() - {int(days)}d"
    elif hours:
        time_range = f"time > now() - {int(hours)}h"
    else:
        time_range = "time > now() - 24h"

    query = (
        f'SELECT * FROM "state" '
        f"WHERE entity_id = '{entity_id}' AND {time_range} "
        f"ORDER BY time DESC LIMIT {int(limit)}"
    )
    data = await run_in_threadpool(_run_query, query)
    return {
        "entity_id": entity_id,
        "time_range": time_range,
        "count": len(data),
        "data": data,
    }


async def _measurement_series(
    db: AsyncSession,
    request: Request,
    entity_id: str,
    measurement: str,
    hours: int,
    limit: int,
) -> dict:
    await _assert_entity_access(db, request, entity_id)
    query = (
        f'SELECT * FROM "{measurement}" '
        f"WHERE entity_id = '{entity_id}' AND time > now() - {int(hours)}h "
        f"ORDER BY time DESC LIMIT {int(limit)}"
    )
    data = await run_in_threadpool(_run_query, query)
    return {
        "entity_id": entity_id,
        "measurement": measurement,
        "count": len(data),
        "data": data,
    }


@router.get("/device/{entity_id}/power")
async def get_entity_power(
    entity_id: str,
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
):
    """Watts (W) for an owned entity_id."""
    return await _measurement_series(db, request, entity_id, "W", hours, limit)


@router.get("/device/{entity_id}/current")
async def get_entity_current(
    entity_id: str,
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
):
    """Amps (A) for an owned entity_id."""
    return await _measurement_series(db, request, entity_id, "A", hours, limit)


@router.get("/device/{entity_id}/switch")
async def get_entity_switch(
    entity_id: str,
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
):
    """Switch state for an owned entity_id."""
    return await _measurement_series(db, request, entity_id, "state", hours, limit)


@router.get("/measurements")
async def list_measurements(request: Request):
    """List InfluxDB measurement names (schema metadata, admin only)."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Admin only")
    try:
        result = await run_in_threadpool(_get_influx().get_list_measurements)
        measurements = [m["name"] for m in result]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"InfluxDB error: {e}")
    return {"count": len(measurements), "measurements": measurements}


@router.get("/health")
async def influx_health(request: Request):
    """InfluxDB connectivity check (admin only — exposes server internals)."""
    if not _is_admin(request):
        raise HTTPException(status_code=403, detail="Admin only")
    try:
        client = _get_influx()
        pong = await run_in_threadpool(client.ping)
        dbs = await run_in_threadpool(client.get_list_database)
        return {
            "status": "connected",
            "influx_version": pong,
            "database": settings.INFLUX_DB,
            "host": settings.INFLUX_HOST,
            "databases": [d["name"] for d in dbs],
        }
    except Exception as e:
        return {"status": "error", "detail": str(e), "host": settings.INFLUX_HOST}
