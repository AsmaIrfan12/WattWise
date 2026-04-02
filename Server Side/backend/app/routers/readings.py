"""WattWise — Energy Readings Router."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Device, Home, EnergyReading, HourlySummary, DailySummary
from app.schemas import EnergyReadingCreate, EnergyReadingResponse, HourlySummaryResponse, DailySummaryResponse
from app.energy_analysis import EnergyAnalysisEngine
from app.config import settings

router = APIRouter(prefix="/api/readings", tags=["Energy Readings"])


def _get_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


async def _verify_device_access(db: AsyncSession, device_id: int, user_id: int) -> Device:
    result = await db.execute(
        select(Device).join(Home, Device.home_id == Home.id)
        .where(Device.id == device_id, Home.user_id == user_id, Device.is_active == True)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device


# ── Ingest ────────────────────────────────────────────────────

@router.post("/", response_model=EnergyReadingResponse, status_code=201)
async def submit_reading(body: EnergyReadingCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """HTTP alternative to MQTT for submitting energy readings."""
    user_id = _get_user_id(request)

    # Resolve device
    device = None
    if body.device_id:
        device = await _verify_device_access(db, body.device_id, user_id)
    elif body.entity_id:
        result = await db.execute(
            select(Device).join(Home, Device.home_id == Home.id)
            .where(Device.entity_id == body.entity_id, Home.user_id == user_id)
        )
        device = result.scalar_one_or_none()
        if not device:
            raise HTTPException(status_code=404, detail=f"No device with entity_id '{body.entity_id}'")
    else:
        raise HTTPException(status_code=400, detail="Provide device_id or entity_id")

    reading = EnergyReading(
        device_id=device.id,
        recorded_at=body.recorded_at or datetime.utcnow(),
        power_watts=body.power_watts,
        current_amps=body.current_amps,
        voltage_volts=body.voltage_volts,
        energy_kwh=body.energy_kwh,
        switch_state=body.switch_state or "unknown",
    )
    db.add(reading)
    await db.commit()
    await db.refresh(reading)
    return reading


# ── Raw Readings ──────────────────────────────────────────────

@router.get("/{device_id}/raw", response_model=list[EnergyReadingResponse])
async def get_raw_readings(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    hours: int = Query(default=24, ge=1, le=720),
    limit: int = Query(default=500, ge=1, le=5000),
):
    user_id = _get_user_id(request)
    await _verify_device_access(db, device_id, user_id)
    since = datetime.utcnow() - timedelta(hours=hours)
    result = await db.execute(
        select(EnergyReading)
        .where(EnergyReading.device_id == device_id, EnergyReading.recorded_at >= since)
        .order_by(EnergyReading.recorded_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


# ── Hourly Summary ────────────────────────────────────────────

@router.get("/{device_id}/hourly", response_model=list[HourlySummaryResponse])
async def get_hourly(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=7, ge=1, le=90),
):
    user_id = _get_user_id(request)
    await _verify_device_access(db, device_id, user_id)
    since = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(HourlySummary)
        .where(HourlySummary.device_id == device_id, HourlySummary.hour_start >= since)
        .order_by(HourlySummary.hour_start.asc())
    )
    return result.scalars().all()


# ── Daily Summary ─────────────────────────────────────────────

@router.get("/{device_id}/daily", response_model=list[DailySummaryResponse])
async def get_daily(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
):
    user_id = _get_user_id(request)
    await _verify_device_access(db, device_id, user_id)
    from datetime import date
    since = (datetime.utcnow() - timedelta(days=days)).date()
    result = await db.execute(
        select(DailySummary)
        .where(DailySummary.device_id == device_id, DailySummary.day_date >= since)
        .order_by(DailySummary.day_date.asc())
    )
    return result.scalars().all()


# ── Live Analysis (on‑demand from raw readings) ───────────────

@router.get("/{device_id}/analysis")
async def get_device_analysis(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    hours: int = Query(default=24, ge=1, le=168),
):
    """On-demand energy analysis including anomaly detection and recommendations."""
    user_id = _get_user_id(request)
    device = await _verify_device_access(db, device_id, user_id)

    since = datetime.utcnow() - timedelta(hours=hours)
    readings = await EnergyAnalysisEngine.get_device_readings_range(db, device_id, since, datetime.utcnow())

    if not readings:
        return {"message": "No readings in this period", "device": device.name, "stats": None}

    stats = EnergyAnalysisEngine.detect_usage_cycles(readings)
    conditions = {
        "is_peak_time": settings.is_peak_time(),
        "current_tariff": settings.get_current_tariff(),
    }
    anomalies = EnergyAnalysisEngine.detect_anomalies(stats, {}, device.appliance_key, conditions)
    recommendations = EnergyAnalysisEngine.generate_recommendations(device.appliance_key, anomalies, stats, conditions)
    cost = EnergyAnalysisEngine.calculate_cost(stats["total_kwh"])

    return {
        "device": {"id": device.id, "name": device.name, "appliance_key": device.appliance_key},
        "period": {"hours": hours, "readings": len(readings)},
        "stats": stats,
        "estimated_cost_gbp": cost,
        "is_peak_time": conditions["is_peak_time"],
        "current_tariff_per_kwh": conditions["current_tariff"],
        "anomalies": anomalies,
        "recommendations": recommendations,
    }


# ── Home-level Summary ────────────────────────────────────────

@router.get("/home/{home_id}/today")
async def get_home_today(home_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Get today's energy picture for all devices in a home."""
    user_id = _get_user_id(request)
    home_result = await db.execute(select(Home).where(Home.id == home_id, Home.user_id == user_id))
    home = home_result.scalar_one_or_none()
    if not home:
        raise HTTPException(status_code=404, detail="Home not found")

    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    devices_result = await db.execute(select(Device).where(Device.home_id == home_id, Device.is_active == True))
    devices = devices_result.scalars().all()

    summary = []
    total_kwh = 0.0

    for device in devices:
        readings = await EnergyAnalysisEngine.get_device_readings_range(db, device.id, today_start, datetime.utcnow())
        if not readings:
            continue
        stats = EnergyAnalysisEngine.detect_usage_cycles(readings)
        cost = EnergyAnalysisEngine.calculate_daily_cost(stats["total_kwh"])
        total_kwh += stats["total_kwh"]
        summary.append({
            "device_id": device.id,
            "name": device.name,
            "appliance_key": device.appliance_key,
            "location": device.location,
            "total_kwh": stats["total_kwh"],
            "avg_watts": stats["avg_watts"],
            "estimated_cost_gbp": cost,
            "cycles": stats["cycles"],
            "active_minutes": stats["active_minutes"],
        })

    summary.sort(key=lambda x: x["total_kwh"], reverse=True)
    return {
        "home": {"id": home.id, "name": home.home_name},
        "date": today_start.date().isoformat(),
        "total_kwh": round(total_kwh, 3),
        "total_cost_gbp": round(EnergyAnalysisEngine.calculate_daily_cost(total_kwh), 2),
        "is_peak_time": settings.is_peak_time(),
        "devices": summary,
    }
