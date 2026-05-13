"""
WattWise — Advanced Analytics Router (Phase 10)
================================================
Endpoints:
  GET  /api/advanced/anomalies              — Detect usage spikes / anomalous readings
  GET  /api/advanced/bill-prediction        — Monthly bill projection (rolling 7-day average)
  GET  /api/advanced/carbon-footprint       — kWh → CO₂e conversion for a home
  GET  /api/advanced/community-anomalies    — Admin: anomalous homes across the community

Auth: Uses request.state.user_id set by the JWT middleware in main.py
      (same pattern as analysis.py and admin.py).

Developer: Mr. Suhas Devmane, Cardiff University, UK
"""

import logging
from datetime import date, timedelta, datetime
from statistics import mean, stdev

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Home, HomeDailyTotal

logger = logging.getLogger("advanced")

router = APIRouter(prefix="/api/advanced", tags=["Advanced Analytics"])

# ── UK Grid Carbon Intensity (gCO₂/kWh) ─────────────────────────────────────
UK_GRID_CARBON_G_PER_KWH_AVERAGE = 233.0   # National Grid ESO 2024 average
UK_GRID_CARBON_G_PER_KWH_PEAK    = 350.0   # Gas-heavy peak demand
UK_GRID_CARBON_G_PER_KWH_OFFPEAK = 150.0   # Renewable-rich off-peak

ANOMALY_Z_SCORE_THRESHOLD = 2.0
MIN_DAYS_FOR_ANOMALY      = 5
BILL_PREDICTION_WINDOW    = 7


# ─── Auth helpers ────────────────────────────────────────────────────────────

def _get_user_id(request: Request) -> int:
    """Extract user_id from JWT middleware state. Raises 401 if missing."""
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


def _require_admin(request: Request) -> int:
    """Require is_admin from JWT middleware state. Raises 403 if not admin."""
    user_id = _get_user_id(request)
    is_admin = getattr(request.state, "is_admin", False)
    if not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user_id


# ─── Pure helpers (no DB — easily unit-testable) ─────────────────────────────

def _z_score_anomalies(readings: list[dict], kwh_field: str = "total_kwh") -> list[dict]:
    """Identify anomalous readings using z-score method (> ANOMALY_Z_SCORE_THRESHOLD σ)."""
    if len(readings) < MIN_DAYS_FOR_ANOMALY:
        return []

    values = [r[kwh_field] for r in readings if r.get(kwh_field) is not None]
    if len(values) < MIN_DAYS_FOR_ANOMALY:
        return []

    mu = mean(values)
    sd = stdev(values) if len(values) > 1 else 0.0
    if sd == 0:
        return []

    anomalies = []
    for r in readings:
        val = r.get(kwh_field)
        if val is None:
            continue
        z = (val - mu) / sd
        if abs(z) >= ANOMALY_Z_SCORE_THRESHOLD:
            anomalies.append({
                **r,
                "z_score":      round(z, 2),
                "mean_kwh":     round(mu, 3),
                "std_kwh":      round(sd, 3),
                "anomaly_type": "spike" if z > 0 else "drop",
                "severity":     "HIGH" if abs(z) >= 3.0 else "MEDIUM",
            })

    return sorted(anomalies, key=lambda x: abs(x["z_score"]), reverse=True)


def _bill_projection(daily_values: list[float], tariff_per_kwh: float = 0.2740) -> dict:
    """Project monthly bill from rolling window of daily kWh values."""
    if not daily_values:
        return {"has_data": False}

    window        = daily_values[-BILL_PREDICTION_WINDOW:]
    avg_daily_kwh = mean(window)
    now           = datetime.utcnow()
    days_in_month = 30

    return {
        "has_data":              True,
        "avg_daily_kwh":         round(avg_daily_kwh, 3),
        "projected_monthly_kwh": round(avg_daily_kwh * days_in_month, 2),
        "projected_monthly_gbp": round(avg_daily_kwh * days_in_month * tariff_per_kwh, 2),
        "spent_kwh_this_month":  round(avg_daily_kwh * now.day, 2),
        "spent_gbp_this_month":  round(avg_daily_kwh * now.day * tariff_per_kwh, 2),
        "remaining_days":        days_in_month - now.day,
        "tariff_per_kwh":        tariff_per_kwh,
        "window_days":           len(window),
        "confidence":            "HIGH" if len(window) >= 7 else "LOW",
    }


def _kwh_to_co2(kwh: float, intensity: float = UK_GRID_CARBON_G_PER_KWH_AVERAGE) -> dict:
    """Convert kWh usage to CO₂ equivalent using UK grid carbon intensity."""
    grams  = kwh * intensity
    kg     = grams / 1000
    tonnes = kg / 1000
    return {
        "kwh":                      round(kwh, 3),
        "carbon_grams":             round(grams, 1),
        "carbon_kg":                round(kg, 3),
        "carbon_tonnes":            round(tonnes, 5),
        "grid_intensity_g_per_kwh": intensity,
        "equivalent_km_driving":    round(grams / 180, 1),   # avg petrol car: 180 gCO₂/km
        "trees_to_offset_annual":   round(kg / 21.77, 2),    # avg tree: 21.77 kg CO₂/year
        "intensity_source":         "National Grid ESO (UK 2024 average)",
    }


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/anomalies")
async def get_anomalies(
    request: Request,
    days: int = Query(default=30, ge=7, le=90),
    db: AsyncSession = Depends(get_db),
):
    """
    Detect anomalous energy usage days for the current user's homes.
    Uses z-score analysis: days > 2σ from mean are flagged.
    """
    user_id = _get_user_id(request)

    homes_result = await db.execute(select(Home).where(Home.user_id == user_id))
    homes = homes_result.scalars().all()

    if not homes:
        return {"has_data": False, "anomalies": [], "summary": "No homes registered."}

    cutoff = date.today() - timedelta(days=days)
    all_anomalies: list[dict] = []
    all_readings:  list[dict] = []

    for home in homes:
        rows_result = await db.execute(
            select(HomeDailyTotal)
            .where(HomeDailyTotal.home_id == home.id)
            .where(HomeDailyTotal.day_date >= cutoff)
            .order_by(HomeDailyTotal.day_date)
        )
        rows = rows_result.scalars().all()
        if not rows:
            continue

        readings = [
            {
                "home_id":        home.id,
                "home_name":      home.name,
                "day_date":       str(row.day_date),
                "total_kwh":      float(row.total_kwh or 0),
                "total_cost_gbp": float(row.total_cost_gbp or 0),
                "peak_watts":     float(row.peak_watts or 0),
            }
            for row in rows
        ]
        all_readings.extend(readings)
        all_anomalies.extend(_z_score_anomalies(readings))

    return {
        "has_data":             bool(all_readings),
        "analysis_window_days": days,
        "total_days_analysed":  len(all_readings),
        "anomalies_found":      len(all_anomalies),
        "anomalies":            all_anomalies[:20],
        "threshold_z_score":    ANOMALY_Z_SCORE_THRESHOLD,
        "summary": (
            f"Found {len(all_anomalies)} anomalous day(s) across "
            f"{len(homes)} home(s) in the last {days} days."
        ),
    }


@router.get("/bill-prediction")
async def get_bill_prediction(
    request: Request,
    tariff_per_kwh: float = Query(default=0.2740, ge=0.01, le=5.0,
                                   description="Electricity tariff in £/kWh"),
    db: AsyncSession = Depends(get_db),
):
    """
    Project the current month's electricity bill based on rolling 7-day usage average.
    Default tariff: £0.274/kWh (UK Ofgem 2024 Q4 cap).
    """
    user_id = _get_user_id(request)

    homes_result = await db.execute(select(Home).where(Home.user_id == user_id))
    homes = homes_result.scalars().all()

    if not homes:
        return {"has_data": False, "message": "No homes registered."}

    cutoff = date.today() - timedelta(days=30)
    all_daily_kwh: list[float] = []

    for home in homes:
        rows_result = await db.execute(
            select(HomeDailyTotal)
            .where(HomeDailyTotal.home_id == home.id)
            .where(HomeDailyTotal.day_date >= cutoff)
            .order_by(HomeDailyTotal.day_date)
        )
        all_daily_kwh.extend(float(r.total_kwh or 0) for r in rows_result.scalars())

    projection = _bill_projection(all_daily_kwh, tariff_per_kwh)
    projection.update({"homes_count": len(homes), "currency": "GBP"})
    return projection


@router.get("/carbon-footprint")
async def get_carbon_footprint(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    intensity: str = Query(default="average",
                           description="Grid intensity: average | peak | offpeak"),
    db: AsyncSession = Depends(get_db),
):
    """
    Calculate the carbon footprint of a user's energy consumption.
    intensity: average (233g), peak (350g), or offpeak (150g) gCO₂/kWh.
    """
    user_id = _get_user_id(request)
    g_per_kwh = {
        "average": UK_GRID_CARBON_G_PER_KWH_AVERAGE,
        "peak":    UK_GRID_CARBON_G_PER_KWH_PEAK,
        "offpeak": UK_GRID_CARBON_G_PER_KWH_OFFPEAK,
    }.get(intensity, UK_GRID_CARBON_G_PER_KWH_AVERAGE)

    homes_result = await db.execute(select(Home).where(Home.user_id == user_id))
    homes = homes_result.scalars().all()

    if not homes:
        return {"has_data": False, "message": "No homes registered."}

    cutoff = date.today() - timedelta(days=days)
    total_kwh = 0.0
    daily_breakdown: list[dict] = []

    for home in homes:
        rows_result = await db.execute(
            select(HomeDailyTotal)
            .where(HomeDailyTotal.home_id == home.id)
            .where(HomeDailyTotal.day_date >= cutoff)
            .order_by(HomeDailyTotal.day_date)
        )
        for row in rows_result.scalars():
            kwh = float(row.total_kwh or 0)
            total_kwh += kwh
            daily_breakdown.append({
                "date":      str(row.day_date),
                "kwh":       round(kwh, 3),
                "carbon_kg": round(kwh * g_per_kwh / 1000, 3),
            })

    carbon = _kwh_to_co2(total_kwh, g_per_kwh)
    return {
        **carbon,
        "period_days":     days,
        "homes_count":     len(homes),
        "intensity_mode":  intensity,
        "daily_breakdown": daily_breakdown[-30:],
    }


@router.get("/community-anomalies")
async def get_community_anomalies(
    request: Request,
    days: int = Query(default=7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only: find anomalous homes across the entire community."""
    _require_admin(request)

    cutoff = date.today() - timedelta(days=days)
    rows_result = await db.execute(
        select(HomeDailyTotal, Home)
        .join(Home, HomeDailyTotal.home_id == Home.id)
        .where(HomeDailyTotal.day_date >= cutoff)
        .order_by(HomeDailyTotal.day_date)
    )
    rows = rows_result.all()

    home_map: dict[int, dict] = {}
    for agg, home in rows:
        if home.id not in home_map:
            home_map[home.id] = {"home_name": home.name, "readings": []}
        home_map[home.id]["readings"].append({
            "home_id":   home.id,
            "home_name": home.name,
            "day_date":  str(agg.day_date),
            "total_kwh": float(agg.total_kwh or 0),
        })

    community_anomalies = []
    for home_id, data in home_map.items():
        anoms = _z_score_anomalies(data["readings"])
        if anoms:
            community_anomalies.append({
                "home_id":   home_id,
                "home_name": data["home_name"],
                "anomalies": anoms,
                "count":     len(anoms),
            })

    return {
        "analysis_window_days": days,
        "homes_analysed":       len(home_map),
        "homes_with_anomalies": len(community_anomalies),
        "results": sorted(community_anomalies, key=lambda x: x["count"], reverse=True),
    }
