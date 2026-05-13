"""
WattWise — Room Environmental Data Router
==========================================
Ported from old/controllers/user-controller.js (getRoomEnvironmentalData,
getSpecificRoomData).

Fetches temperature, humidity, and pressure from InfluxDB for
rooms configured on the user's homes.

Room sensors follow the Home Assistant entity naming convention:
  {entity_base}_humidity    → measurement: "%"
  {entity_base}_temperature → measurement: "°C"
  {entity_base}_pressure    → measurement: "hPa"

Example:
  Room entity_id = "livingsensor"
  → livingsensor_humidity, livingsensor_temperature, livingsensor_pressure

Base URL: /api/environment/
Authentication: JWT Bearer (all routes protected)
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, Query
from influxdb import InfluxDBClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import Depends

from app.config import settings
from app.database import get_db
from app.models import Home, Room

logger = logging.getLogger("environment_router")

router = APIRouter(prefix="/api/environment", tags=["Room Environment"])


# ── Helpers ──────────────────────────────────────────────────────

def _get_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


def _get_influx() -> InfluxDBClient:
    return InfluxDBClient(
        host=settings.INFLUX_HOST,
        port=settings.INFLUX_PORT,
        username=settings.INFLUX_USER,
        password=settings.INFLUX_PASS,
        database=settings.INFLUX_DB,
    )


def _query_latest(influx: InfluxDBClient, measurement: str, entity_id: str, limit: int = 50) -> list[dict]:
    """Query latest readings for a specific sensor entity."""
    query = (
        f'SELECT * FROM "{measurement}" '
        f"WHERE entity_id = '{entity_id}' "
        f"ORDER BY time DESC LIMIT {limit}"
    )
    try:
        result = influx.query(query)
        return list(result.get_points())
    except Exception as e:
        logger.warning(f"InfluxDB query failed [{entity_id}]: {e}")
        return []


def _query_range(
    influx: InfluxDBClient,
    measurement: str,
    entity_id: str,
    time_range: str,
    limit: int,
) -> list[dict]:
    """Query sensor data for a time range."""
    query = (
        f'SELECT * FROM "{measurement}" '
        f"WHERE entity_id = '{entity_id}' AND {time_range} "
        f"ORDER BY time DESC LIMIT {limit}"
    )
    try:
        result = influx.query(query)
        return list(result.get_points())
    except Exception as e:
        logger.warning(f"InfluxDB range query failed [{entity_id}]: {e}")
        return []


def _build_room_data(influx: InfluxDBClient, room: Room, time_range: str, limit: int) -> dict:
    """Fetch all environmental sensor data for a single room."""
    entity_base = room.entity_id or room.name.lower().replace(" ", "")
    hum_data = _query_range(influx, "%", f"{entity_base}_humidity", time_range, limit)
    temp_data = _query_range(influx, "°C", f"{entity_base}_temperature", time_range, limit)
    pres_data = _query_range(influx, "hPa", f"{entity_base}_pressure", time_range, limit)

    return {
        "room_name": room.name,
        "entity_id": entity_base,
        "humidity": {
            "current": hum_data[0].get("value") if hum_data else None,
            "unit": "%",
            "data_count": len(hum_data),
            "data": hum_data,
        },
        "temperature": {
            "current": temp_data[0].get("value") if temp_data else None,
            "unit": "°C",
            "data_count": len(temp_data),
            "data": temp_data,
        },
        "pressure": {
            "current": pres_data[0].get("value") if pres_data else None,
            "unit": "hPa",
            "data_count": len(pres_data),
            "data": pres_data,
        },
    }


# ── Endpoints ─────────────────────────────────────────────────────

@router.get("/rooms")
async def get_all_rooms_environmental(
    request: Request,
    db: AsyncSession = Depends(get_db),
    hours: Optional[int] = Query(default=None, ge=1, le=720),
    days: Optional[int] = Query(default=None, ge=1, le=90),
    limit: int = Query(default=50, ge=1, le=500),
):
    """
    Get temperature, humidity, and pressure for all rooms in the user's home(s).
    Reads from InfluxDB using room entity_id patterns.

    Example room entity IDs: livingsensor, kitchensensor, dinningsensor
    """
    user_id = _get_user_id(request)

    # Find all user homes
    homes_result = await db.execute(
        select(Home).where(Home.user_id == user_id, Home.is_active == True)
    )
    homes = homes_result.scalars().all()

    if not homes:
        return {"message": "No homes configured", "rooms": []}

    # Build time range
    if days:
        time_range = f"time > now() - {days}d"
    elif hours:
        time_range = f"time > now() - {hours}h"
    else:
        time_range = "time > now() - 24h"

    influx = _get_influx()
    all_rooms_data = []

    for home in homes:
        rooms_result = await db.execute(
            select(Room).where(Room.home_id == home.id)
        )
        rooms = rooms_result.scalars().all()

        for room in rooms:
            try:
                room_data = _build_room_data(influx, room, time_range, limit)
                room_data["home_id"] = home.id
                room_data["home_name"] = home.home_name
                all_rooms_data.append(room_data)
            except Exception as e:
                logger.error(f"Error fetching data for room {room.name}: {e}")
                all_rooms_data.append({
                    "room_name": room.name,
                    "home_id": home.id,
                    "error": str(e),
                })

    return {
        "message": "Room environmental data fetched successfully",
        "time_range": time_range,
        "room_count": len(all_rooms_data),
        "rooms": all_rooms_data,
    }


@router.get("/rooms/{room_name}")
async def get_specific_room_data(
    room_name: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    hours: Optional[int] = Query(default=None, ge=1, le=720),
    days: Optional[int] = Query(default=None, ge=1, le=90),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """
    Get environmental data for a specific room by name or entity_id.
    Room name matching is case-insensitive.
    """
    user_id = _get_user_id(request)

    # Find home
    homes_result = await db.execute(
        select(Home).where(Home.user_id == user_id, Home.is_active == True)
    )
    homes = homes_result.scalars().all()

    if not homes:
        raise HTTPException(status_code=404, detail="No homes configured")

    # Find the room across all user homes
    target_room = None
    target_home = None
    for home in homes:
        rooms_result = await db.execute(
            select(Room).where(Room.home_id == home.id)
        )
        rooms = rooms_result.scalars().all()
        for room in rooms:
            if (
                room.name.lower() == room_name.lower()
                or (room.entity_id and room.entity_id.lower() == room_name.lower())
            ):
                target_room = room
                target_home = home
                break
        if target_room:
            break

    if not target_room:
        raise HTTPException(
            status_code=404,
            detail=f"Room '{room_name}' not found in your registered homes",
        )

    # Build time range
    if days:
        time_range = f"time > now() - {days}d"
    elif hours:
        time_range = f"time > now() - {hours}h"
    else:
        time_range = "time > now() - 24h"

    influx = _get_influx()
    room_data = _build_room_data(influx, target_room, time_range, limit)
    room_data["home_id"] = target_home.id
    room_data["home_name"] = target_home.home_name

    return {
        "message": f"Environmental data for room '{target_room.name}'",
        "time_range": time_range,
        **room_data,
    }


@router.get("/summary")
async def get_environment_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Get current (latest) readings only for all rooms — a quick dashboard snapshot.
    Returns current temp/humidity/pressure without full data arrays.
    """
    user_id = _get_user_id(request)

    homes_result = await db.execute(
        select(Home).where(Home.user_id == user_id, Home.is_active == True)
    )
    homes = homes_result.scalars().all()

    if not homes:
        return {"rooms": []}

    influx = _get_influx()
    summary = []

    for home in homes:
        rooms_result = await db.execute(
            select(Room).where(Room.home_id == home.id)
        )
        rooms = rooms_result.scalars().all()

        for room in rooms:
            entity_base = room.entity_id or room.name.lower().replace(" ", "")
            hum = _query_latest(influx, "%", f"{entity_base}_humidity", 1)
            temp = _query_latest(influx, "°C", f"{entity_base}_temperature", 1)
            pres = _query_latest(influx, "hPa", f"{entity_base}_pressure", 1)

            entry = {
                "home_id": home.id,
                "home_name": home.home_name,
                "room_name": room.name,
                "entity_id": entity_base,
                "temperature_c": temp[0].get("value") if temp else None,
                "humidity_pct": hum[0].get("value") if hum else None,
                "pressure_hpa": pres[0].get("value") if pres else None,
                "last_reading_time": temp[0].get("time") if temp else None,
                "has_data": bool(temp or hum),
            }
            summary.append(entry)

    return {
        "message": "Environment summary",
        "room_count": len(summary),
        "rooms": summary,
    }
