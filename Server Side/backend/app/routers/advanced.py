"""
WattWise — Advanced Analytics Router (Phase 10)
================================================
Endpoints:
  GET  /api/advanced/anomalies              — Detect usage spikes / anomalous readings
  GET  /api/advanced/bill-prediction        — Monthly bill projection (rolling 7-day average)
  GET  /api/advanced/carbon-footprint       — kWh → CO₂e conversion for a home
  GET  /api/advanced/community-anomalies    — Admin: anomalous homes across the community

All endpoints require authentication. The /community-anomalies endpoint requires is_admin.

Developer: Mr. Suhas Devmane, Cardiff University, UK
"""

import logging
from datetime import date, timedelta, datetime
from typing import Optional
from statistics import mean, stdev

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Home, DailyAggregate, User
from app.security import get_current_user

logger = logging.getLogger("advanced")

router = APIRouter(prefix="/api/advanced", tags=["advanced-analytics"])

# ── UK Grid Carbon Intensity (gCO₂/kWh) ─────────────────────────────────────
# Source: National Grid ESO (https://carbonintensity.org.uk/)
# Average UK grid intensity (2024): ~233 gCO₂e/kWh
# Peak (gas-heavy): ~350 gCO₂e/kWh
# Off-peak / renewable-rich: ~150 gCO₂e/kWh
UK_GRID_CARBON_G_PER_KWH_AVERAGE = 233.0
UK_GRID_CARBON_G_PER_KWH_PEAK    = 350.0
UK_GRID_CARBON_G_PER_KWH_OFFPEAK = 150.0

# ── Constants ─────────────────────────────────────────────────────────────────
ANOMALY_Z_SCORE_THRESHOLD = 2.0     # > 2 std devs from mean = anomalous
MIN_DAYS_FOR_ANOMALY     = 5        # need at least 5 data points for z-score
BILL_PREDICTION_WINDOW   = 7        # 7-day rolling average for projection


# ═════════════════════════════════════════════════════════════════════════════
# Helper functions (also importable for unit tests)
# ═════════════════════════════════════════════════════════════════════════════

def _z_score_anomalies(readings: list[dict], kwh_field: str = "total_kwh") -> list[dict]:
    """
    Identify anomalous readings using z-score method.

    Args:
        readings: List of dicts with at least `day_date` and `total_kwh` fields.
        kwh_field: Key name for the kWh value.

    Returns:
        List of anomalous reading dicts, each enriched with `z_score`, `mean_kwh`,
        `std_kwh`, and `anomaly_type` keys.
    """
    if len(readings) < MIN_DAYS_FOR_ANOMALY:
        return []

    values = [r[kwh_field] for r in readings if r.get(kwh_field) is not None]
    if len(values) < MIN_DAYS_FOR_ANOMALY:
        return []

    mu  = mean(values)
    sd  = stdev(values) if len(values) > 1 else 0.0

    if sd == 0:
        return []

    anomalies = []
    for r in readings:
        val = r.get(kwh_field)
        if val is None:
            continue
        z = (val - mu) / sd
        if abs(z) >= ANOMALY_Z_SCORE_THRESHOLD:
            anomaly_type = "spike" if z > 0 else "drop"
            anomalies.append({
                **r,
                "z_score":      round(z, 2),
                "mean_kwh":     round(mu, 3),
                "std_kwh":      round(sd, 3),
                "anomaly_type": anomaly_type,
                "severity":     "HIGH" if abs(z) >= 3.0 else "MEDIUM",
            })

    return sorted(anomalies, key=lambda x: abs(x["z_score"]), reverse=True)


def _bill_projection(daily_values: list[float], tariff_per_kwh: float = 0.2740) -> dict:
    """
    Project monthly bill from a rolling window of daily kWh values.

    Uses the last N days' average, then extrapolates to 30 days.
    Returns dict with projection details.
    """
    if not daily_values:
        return {"has_data": False}

    window = daily_values[-BILL_PREDICTION_WINDOW:]
    avg_daily_kwh = mean(window)

    now = datetime.utcnow()
    days_in_month = 30  # approximate
    remaining_days = days_in_month - now.day

    projected_kwh   = avg_daily_kwh * days_in_month
    projected_cost  = projected_kwh * tariff_per_kwh
    spent_kwh       = avg_daily_kwh * now.day
    spent_cost      = spent_kwh * tariff_per_kwh

    return {
        "has_data":             True,
        "avg_daily_kwh":        round(avg_daily_kwh, 3),
        "projected_monthly_kwh":round(projected_kwh, 2),
        "projected_monthly_gbp":round(projected_cost, 2),
        "spent_kwh_this_month": round(spent_kwh, 2),
        "spent_gbp_this_month": round(spent_cost, 2),
        "remaining_days":       remaining_days,
        "tariff_per_kwh":       tariff_per_kwh,
        "window_days":          len(window),
        "confidence":           "HIGH" if len(window) >= 7 else "LOW",
    }


def _kwh_to_co2(kwh: float, intensity: float = UK_GRID_CARBON_G_PER_KWH_AVERAGE) -> dict:
    """Convert kWh usage to CO₂ equivalent using UK grid carbon intensity."""
    grams  = kwh * intensity
    kg     = grams / 1000
    tonnes = kg / 1000

    # Equivalents (for user context)
    km_driven    = round(grams / 180, 1)   # avg petrol car: 180g CO₂/km
    trees_offset = round(kg / 21.77, 2)    # avg tree: 21.77 kg CO₂/year

    return {
        "kwh":                    round(kwh, 3),
        "carbon_grams":           round(grams, 1),
        "carbon_kg":              round(kg, 3),
        "carbon_tonnes":          round(tonnes, 5),
        "grid_intensity_g_per_kwh": intensity,
        "equivalent_km_driving":  km_driven,
        "trees_to_offset_annual": trees_offset,
        "intensity_source":       "National Grid ESO (UK 2024 average)",
    }


# ═════════════════════════════════════════════════════════════════════════════
# Endpoints
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/anomalies")
async def get_anomalies(
    days: int = Query(default=30, ge=7, le=90, description="Look-back window in days"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Detect anomalous energy usage days for the current user's homes.

    Uses z-score analysis over the requested look-back window.
    Days more than 2 standard deviations from the mean are flagged.
    """
    # Get user's homes
    homes_result = await db.execute(
        select(Home).where(Home.user_id == current_user.id)
    )
    homes = homes_result.scalars().all()

    if not homes:
        return {"has_data": False, "anomalies": [], "summary": "No homes registered."}

    cutoff = date.today() - timedelta(days=days)
    all_anomalies = []
    all_daily_readings = []

    for home in homes:
        agg_result = await db.execute(
            select(DailyAggregate)
            .where(DailyAggregate.home_id == home.id)
            .where(DailyAggregate.agg_date >= cutoff)
            .order_by(DailyAggregate.agg_date)
        )
        agg_rows = agg_result.scalars().all()

        if not agg_rows:
            continue

        readings = [
            {
                "home_id":    home.id,
                "home_name":  home.name,
                "day_date":   str(row.agg_date),
                "total_kwh":  float(row.total_kwh or 0),
                "total_cost_gbp": float(row.total_cost_gbp or 0),
            }
            for row in agg_rows
        ]
        all_daily_readings.extend(readings)

        home_anomalies = _z_score_anomalies(readings)
        all_anomalies.extend(home_anomalies)

    return {
        "has_data":         len(all_daily_readings) > 0,
        "analysis_window_days": days,
        "total_days_analysed":  len(all_daily_readings),
        "anomalies_found":  len(all_anomalies),
        "anomalies":        all_anomalies[:20],  # cap at 20 results
        "threshold_z_score": ANOMALY_Z_SCORE_THRESHOLD,
        "summary":          f"Found {len(all_anomalies)} anomalous day(s) across {len(homes)} home(s) in the last {days} days.",
    }


@router.get("/bill-prediction")
async def get_bill_prediction(
    tariff_per_kwh: float = Query(default=0.2740, ge=0.01, le=5.0, description="Electricity tariff in £/kWh"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Project the current month's electricity bill based on rolling 7-day usage average.

    The projection uses the most recent 7 days of daily totals and extrapolates
    to a 30-day month. Confidence is HIGH if 7+ days of data exist.
    """
    homes_result = await db.execute(
        select(Home).where(Home.user_id == current_user.id)
    )
    homes = homes_result.scalars().all()

    if not homes:
        return {"has_data": False, "message": "No homes registered."}

    cutoff_30d = date.today() - timedelta(days=30)
    all_daily_kwh: list[float] = []

    for home in homes:
        agg_result = await db.execute(
            select(DailyAggregate)
            .where(DailyAggregate.home_id == home.id)
            .where(DailyAggregate.agg_date >= cutoff_30d)
            .order_by(DailyAggregate.agg_date)
        )
        rows = agg_result.scalars().all()
        for row in rows:
            all_daily_kwh.append(float(row.total_kwh or 0))

    projection = _bill_projection(all_daily_kwh, tariff_per_kwh)
    projection["homes_count"] = len(homes)
    projection["currency"] = "GBP"

    return projection


@router.get("/carbon-footprint")
async def get_carbon_footprint(
    days: int = Query(default=30, ge=1, le=365, description="Number of days to calculate footprint for"),
    intensity: str = Query(default="average", description="Grid intensity: average | peak | offpeak"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Calculate the carbon footprint of a user's energy consumption.

    Returns CO₂ equivalent in grams, kg, and tonnes, along with relatable
    equivalents (km driving, trees to offset).

    intensity options:
      - average: UK grid 2024 average (233 gCO₂/kWh) — recommended
      - peak:    Gas-heavy peak hours (350 gCO₂/kWh)
      - offpeak: Renewable-rich off-peak (150 gCO₂/kWh)
    """
    intensity_map = {
        "average": UK_GRID_CARBON_G_PER_KWH_AVERAGE,
        "peak":    UK_GRID_CARBON_G_PER_KWH_PEAK,
        "offpeak": UK_GRID_CARBON_G_PER_KWH_OFFPEAK,
    }
    g_per_kwh = intensity_map.get(intensity, UK_GRID_CARBON_G_PER_KWH_AVERAGE)

    homes_result = await db.execute(
        select(Home).where(Home.user_id == current_user.id)
    )
    homes = homes_result.scalars().all()

    if not homes:
        return {"has_data": False, "message": "No homes registered."}

    cutoff = date.today() - timedelta(days=days)
    total_kwh = 0.0
    daily_breakdown = []

    for home in homes:
        agg_result = await db.execute(
            select(DailyAggregate)
            .where(DailyAggregate.home_id == home.id)
            .where(DailyAggregate.agg_date >= cutoff)
            .order_by(DailyAggregate.agg_date)
        )
        rows = agg_result.scalars().all()
        for row in rows:
            kwh = float(row.total_kwh or 0)
            total_kwh += kwh
            daily_breakdown.append({
                "date":     str(row.agg_date),
                "kwh":      round(kwh, 3),
                "carbon_kg": round(kwh * g_per_kwh / 1000, 3),
            })

    carbon = _kwh_to_co2(total_kwh, g_per_kwh)
    return {
        **carbon,
        "period_days":     days,
        "homes_count":     len(homes),
        "intensity_mode":  intensity,
        "daily_breakdown": daily_breakdown[-30:],  # last 30 days
    }


@router.get("/community-anomalies")
async def get_community_anomalies(
    days: int = Query(default=7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Admin endpoint: find anomalous homes across the entire community.
    Requires is_admin = True.
    """
    if not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required.")

    cutoff = date.today() - timedelta(days=days)
    agg_result = await db.execute(
        select(DailyAggregate, Home)
        .join(Home, DailyAggregate.home_id == Home.id)
        .where(DailyAggregate.agg_date >= cutoff)
        .order_by(DailyAggregate.agg_date)
    )
    rows = agg_result.all()

    # Group by home_id
    home_map: dict[int, dict] = {}
    for agg, home in rows:
        if home.id not in home_map:
            home_map[home.id] = {"home_name": home.name, "readings": []}
        home_map[home.id]["readings"].append({
            "home_id":   home.id,
            "home_name": home.name,
            "day_date":  str(agg.agg_date),
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
        "results":              sorted(community_anomalies, key=lambda x: x["count"], reverse=True),
    }
