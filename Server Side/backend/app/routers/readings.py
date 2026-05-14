"""WattWise — Energy Readings Router."""

from datetime import date, datetime, timedelta
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
        .where(Device.id == device_id, Home.user_id == user_id, Device.is_active)
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
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
):
    user_id = _get_user_id(request)
    await _verify_device_access(db, device_id, user_id)
    if start_date and end_date:
        since = start_date
        until = end_date
    else:
        until = date.today()
        since = until - timedelta(days=days)
    result = await db.execute(
        select(DailySummary)
        .where(
            DailySummary.device_id == device_id,
            DailySummary.day_date >= since,
            DailySummary.day_date <= until,
        )
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
    devices_result = await db.execute(select(Device).where(Device.home_id == home_id, Device.is_active))
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


@router.get("/{device_id}/live")
async def get_live_reading(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    points: int = Query(default=20, ge=1, le=120),
):
    """
    Latest power readings for a single device, returned as a sparkline-friendly
    list. Suitable for a 2–3 s polling loop driving a live wattage gauge.

    Each entry: {recorded_at, power_watts, switch_state}
    """
    user_id = _get_user_id(request)
    await _verify_device_access(db, device_id, user_id)

    result = await db.execute(
        select(EnergyReading.recorded_at, EnergyReading.power_watts, EnergyReading.switch_state)
        .where(EnergyReading.device_id == device_id)
        .order_by(EnergyReading.recorded_at.desc())
        .limit(points)
    )
    rows = result.all()
    if not rows:
        return {"device_id": device_id, "current_watts": 0.0, "points": []}

    # Reverse so points are chronological
    rows = list(reversed(rows))
    current_w = float(rows[-1].power_watts or 0)
    avg_w = sum(float(r.power_watts or 0) for r in rows) / len(rows)
    peak_w = max(float(r.power_watts or 0) for r in rows)

    return {
        "device_id": device_id,
        "current_watts": round(current_w, 1),
        "avg_watts_window": round(avg_w, 1),
        "peak_watts_window": round(peak_w, 1),
        "switch_state": rows[-1].switch_state,
        "last_seen": rows[-1].recorded_at.isoformat(),
        "points": [
            {
                "ts": r.recorded_at.isoformat(),
                "w": round(float(r.power_watts or 0), 1),
                "state": r.switch_state,
            }
            for r in rows
        ],
    }


@router.get("/{device_id}/standby")
async def get_standby_analysis(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=7, ge=1, le=90),
):
    """
    Vampire-drain / standby-power analysis for a single device.

    Walks raw energy_readings over the requested window, identifies time spent
    below the active threshold but above zero (standby state), totals the
    standby kWh, and projects an annualised cost. Useful for prompting
    "unplug it overnight" decisions.

    The standby/active classification reuses EnergyAnalysisEngine.detect_usage_cycles.
    """
    user_id = _get_user_id(request)
    device = await _verify_device_access(db, device_id, user_id)

    since = datetime.utcnow() - timedelta(days=days)
    readings = await EnergyAnalysisEngine.get_device_readings_range(
        db, device_id, since, datetime.utcnow()
    )
    if not readings:
        return {
            "device": {"id": device.id, "name": device.name, "appliance_key": device.appliance_key},
            "window_days": days,
            "message": "No readings in this period",
        }

    stats = EnergyAnalysisEngine.detect_usage_cycles(readings)
    standby_kwh = stats.get("standby_kwh", 0.0)
    total_kwh = stats.get("total_kwh", 0.0)
    standby_share = (standby_kwh / total_kwh * 100) if total_kwh > 0 else 0.0

    avg_daily_standby_kwh = standby_kwh / max(days, 1)
    annual_standby_kwh = avg_daily_standby_kwh * 365
    annual_standby_cost_gbp = EnergyAnalysisEngine.calculate_cost(annual_standby_kwh)

    severity = (
        "critical" if avg_daily_standby_kwh > 0.3 else
        "warning" if avg_daily_standby_kwh > 0.1 else
        "ok"
    )
    advice = {
        "critical": "Significant vampire drain — unplug or use a smart plug timer when not in use.",
        "warning": "Moderate standby draw — consider unplugging overnight.",
        "ok": "Standby draw is within expected range.",
    }[severity]

    return {
        "device": {"id": device.id, "name": device.name, "appliance_key": device.appliance_key},
        "window_days": days,
        "since": since.isoformat(),
        "standby_kwh": round(standby_kwh, 4),
        "total_kwh": round(total_kwh, 4),
        "standby_share_pct": round(standby_share, 1),
        "avg_daily_standby_kwh": round(avg_daily_standby_kwh, 4),
        "annualised_standby_kwh": round(annual_standby_kwh, 2),
        "annualised_standby_cost_gbp": round(annual_standby_cost_gbp, 2),
        "severity": severity,
        "advice": advice,
    }


@router.get("/{device_id}/hourly-profile")
async def get_hourly_profile(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=14, ge=1, le=90),
):
    """
    24-bucket hour-of-day profile: average kWh consumed at each hour of the day
    over the last `days` days. Pivots `hourly_summary` rows so the same hour
    across multiple days is averaged together.

    Useful for spotting habitual peak-hour usage and for "shift this load to
    off-peak" advice. Ported from the old getDeviceHourlyBreakdown controller.
    """
    user_id = _get_user_id(request)
    await _verify_device_access(db, device_id, user_id)

    since = datetime.utcnow() - timedelta(days=days)

    result = await db.execute(
        select(
            func.hour(HourlySummary.hour_start).label("hour_of_day"),
            func.avg(HourlySummary.total_kwh).label("avg_kwh"),
            func.avg(HourlySummary.avg_watts).label("avg_watts"),
            func.max(HourlySummary.max_watts).label("peak_watts"),
            func.sum(HourlySummary.usage_cycles).label("total_cycles"),
            func.count(HourlySummary.id).label("samples"),
        )
        .where(HourlySummary.device_id == device_id, HourlySummary.hour_start >= since)
        .group_by(func.hour(HourlySummary.hour_start))
        .order_by(func.hour(HourlySummary.hour_start).asc())
    )
    rows = result.all()

    # Build a fully-populated 24-bucket profile (zero-fill missing hours)
    by_hour = {int(r.hour_of_day): r for r in rows}
    tariff_peak_start = settings.ENERGY_PEAK_START_HOUR
    tariff_peak_end = settings.ENERGY_PEAK_END_HOUR

    profile = []
    total_avg_kwh = 0.0
    for h in range(24):
        r = by_hour.get(h)
        avg_kwh = round(float(r.avg_kwh or 0), 4) if r else 0.0
        total_avg_kwh += avg_kwh
        profile.append({
            "hour": h,
            "label": f"{h:02d}:00",
            "avg_kwh": avg_kwh,
            "avg_watts": round(float(r.avg_watts or 0), 1) if r else 0.0,
            "peak_watts": round(float(r.peak_watts or 0), 1) if r else 0.0,
            "total_cycles": int(r.total_cycles or 0) if r else 0,
            "samples": int(r.samples or 0) if r else 0,
            "is_peak_tariff": tariff_peak_start <= h < tariff_peak_end,
        })

    # Identify the user's personal peak hours (top 3 by avg kWh)
    sorted_by_kwh = sorted(profile, key=lambda x: x["avg_kwh"], reverse=True)
    personal_peak_hours = [p["hour"] for p in sorted_by_kwh[:3] if p["avg_kwh"] > 0]
    for p in profile:
        p["is_personal_peak"] = p["hour"] in personal_peak_hours

    # Tariff-peak vs off-peak split
    peak_tariff_kwh = sum(p["avg_kwh"] for p in profile if p["is_peak_tariff"])
    off_peak_kwh = total_avg_kwh - peak_tariff_kwh
    peak_share_pct = (peak_tariff_kwh / total_avg_kwh * 100) if total_avg_kwh > 0 else 0.0

    return {
        "device_id": device_id,
        "window_days": days,
        "since": since.isoformat(),
        "summary": {
            "avg_daily_kwh": round(total_avg_kwh, 3),
            "peak_tariff_kwh_share_pct": round(peak_share_pct, 1),
            "peak_tariff_kwh": round(peak_tariff_kwh, 3),
            "off_peak_kwh": round(off_peak_kwh, 3),
            "personal_peak_hours": personal_peak_hours,
            "tariff_peak_window": f"{tariff_peak_start:02d}:00–{tariff_peak_end:02d}:00",
        },
        "profile": profile,
    }
