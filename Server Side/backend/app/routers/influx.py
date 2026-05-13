"""
WattWise — InfluxDB Entity-Based Query Router
==============================================
Ported from old/app.js (Node.js).

Exposes direct time-series access to InfluxDB for:
- Listing all entity_ids stored in InfluxDB
- Fetching raw time-ranged data for any entity_id
- Device-specific power / current / switch-state queries

These endpoints complement the MySQL-backed /api/readings/ routes
by providing direct access to the Home Assistant entity streams
stored in InfluxDB by the RaspberryPi MQTT collector.

Base URL: /api/influx/
Authentication: JWT Bearer (all routes protected)
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
from influxdb import InfluxDBClient

from app.config import settings

logger = logging.getLogger("influx_router")

router = APIRouter(prefix="/api/influx", tags=["InfluxDB (Entity)"])


# ── InfluxDB client factory ─────────────────────────────────────

def _get_influx() -> InfluxDBClient:
    """Create a synchronous InfluxDB 1.x client from settings."""
    return InfluxDBClient(
        host=settings.INFLUX_HOST,
        port=settings.INFLUX_PORT,
        username=settings.INFLUX_USER,
        password=settings.INFLUX_PASS,
        database=settings.INFLUX_DB,
    )


def _get_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


def _run_query(influx: InfluxDBClient, query: str) -> list[dict]:
    """Execute an InfluxQL query and return results as a list of dicts."""
    try:
        result = influx.query(query)
        rows = list(result.get_points())
        return rows
    except Exception as e:
        logger.error(f"InfluxDB query error: {e} — query: {query[:200]}")
        raise HTTPException(status_code=503, detail=f"InfluxDB query failed: {e}")


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/entities")
def list_entities(request: Request):
    """
    List all entity_ids recorded in the InfluxDB 'state' measurement.
    These are the Home Assistant entity IDs sent by the RaspberryPi sensor bridge.
    """
    _get_user_id(request)
    influx = _get_influx()
    rows = _run_query(influx, 'SHOW TAG VALUES FROM "state" WITH KEY = "entity_id"')
    entity_ids = [r.get("value") or r for r in rows]
    return {
        "message": "Available entities in InfluxDB",
        "count": len(entity_ids),
        "entities": entity_ids,
    }


@router.get("/entity/{entity_id}")
def get_entity_data(
    entity_id: str,
    request: Request,
    hours: Optional[int] = Query(default=None, ge=1, le=720),
    days: Optional[int] = Query(default=None, ge=1, le=90),
    limit: int = Query(default=200, ge=1, le=5000),
):
    """
    Fetch time-ranged raw data for a specific entity_id from InfluxDB.
    Used for device power, current, switch state, or environmental sensor data.

    Examples:
        GET /api/influx/entity/kettle_current_consumption?hours=24
        GET /api/influx/entity/livingsensor_temperature?days=7
    """
    _get_user_id(request)

    # Build time range
    if days:
        time_range = f"time > now() - {days}d"
    elif hours:
        time_range = f"time > now() - {hours}h"
    else:
        time_range = "time > now() - 24h"

    influx = _get_influx()
    query = (
        f'SELECT * FROM "state" '
        f"WHERE entity_id = '{entity_id}' AND {time_range} "
        f"ORDER BY time DESC LIMIT {limit}"
    )
    data = _run_query(influx, query)

    return {
        "entity_id": entity_id,
        "time_range": time_range,
        "count": len(data),
        "data": data,
    }


@router.get("/device/{entity_id}/power")
def get_entity_power(
    entity_id: str,
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=5000),
):
    """
    Fetch Watts (W measurement) for the given entity_id.
    Used for power consumption time series (from Home Assistant energy sensors).
    """
    _get_user_id(request)
    influx = _get_influx()
    query = (
        f'SELECT * FROM "W" '
        f"WHERE entity_id = '{entity_id}' AND time > now() - {hours}h "
        f"ORDER BY time DESC LIMIT {limit}"
    )
    data = _run_query(influx, query)
    return {"entity_id": entity_id, "measurement": "W", "count": len(data), "data": data}


@router.get("/device/{entity_id}/current")
def get_entity_current(
    entity_id: str,
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=5000),
):
    """
    Fetch Amps (A measurement) for the given entity_id.
    Represents electrical current drawn by a smart plug.
    """
    _get_user_id(request)
    influx = _get_influx()
    query = (
        f'SELECT * FROM "A" '
        f"WHERE entity_id = '{entity_id}' AND time > now() - {hours}h "
        f"ORDER BY time DESC LIMIT {limit}"
    )
    data = _run_query(influx, query)
    return {"entity_id": entity_id, "measurement": "A", "count": len(data), "data": data}


@router.get("/device/{entity_id}/switch")
def get_entity_switch(
    entity_id: str,
    request: Request,
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=5000),
):
    """
    Fetch switch state data (on/off) for the given entity_id from the 'state' measurement.
    """
    _get_user_id(request)
    influx = _get_influx()
    query = (
        f'SELECT * FROM "state" '
        f"WHERE entity_id = '{entity_id}' AND time > now() - {hours}h "
        f"ORDER BY time DESC LIMIT {limit}"
    )
    data = _run_query(influx, query)
    return {"entity_id": entity_id, "measurement": "state", "count": len(data), "data": data}


@router.get("/measurements")
def list_measurements(request: Request):
    """
    List all measurements available in the InfluxDB database.
    Useful for debugging what data has been ingested from Home Assistant.
    """
    _get_user_id(request)
    influx = _get_influx()
    try:
        result = influx.get_list_measurements()
        measurements = [m["name"] for m in result]
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"InfluxDB error: {e}")
    return {"count": len(measurements), "measurements": measurements}


@router.get("/health")
def influx_health(request: Request):
    """
    Check InfluxDB connectivity and return database info.
    Maps to the old https://influx.wattwiser.org/health concept.
    """
    _get_user_id(request)
    influx = _get_influx()
    try:
        pong = influx.ping()
        dbs = influx.get_list_database()
        return {
            "status": "connected",
            "influx_version": pong,
            "database": settings.INFLUX_DB,
            "host": settings.INFLUX_HOST,
            "databases": [d["name"] for d in dbs],
        }
    except Exception as e:
        return {
            "status": "error",
            "detail": str(e),
            "host": settings.INFLUX_HOST,
        }
