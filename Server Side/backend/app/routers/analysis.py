"""WattWise — Analysis & Rankings Router."""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnergyRanking, HomeDailyTotal, Home, DailySummary, Device, HourlySummary

router = APIRouter(prefix="/api", tags=["Analysis & Rankings"])


def _get_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


def _build_community_benchmark_payload(
    *,
    target_date: Optional[date],
    registered_home_count: int,
    user_rows: list[dict],
    community_rows: list[dict],
):
    user_home_ids = {row["home_id"] for row in user_rows}
    peer_rows = [row for row in community_rows if row["home_id"] not in user_home_ids]

    user_total_kwh = sum(float(row.get("total_kwh") or 0) for row in user_rows)
    user_total_cost = sum(float(row.get("total_cost_gbp") or 0) for row in user_rows)
    homes_with_data = len(user_rows)
    user_avg_home_kwh = user_total_kwh / homes_with_data if homes_with_data else 0.0
    user_avg_home_cost = user_total_cost / homes_with_data if homes_with_data else 0.0

    peer_avg_kwh = (
        sum(float(row.get("total_kwh") or 0) for row in peer_rows) / len(peer_rows)
        if peer_rows
        else 0.0
    )
    peer_avg_cost = (
        sum(float(row.get("total_cost_gbp") or 0) for row in peer_rows) / len(peer_rows)
        if peer_rows
        else 0.0
    )
    peer_min_kwh = min((float(row.get("total_kwh") or 0) for row in peer_rows), default=0.0)
    peer_max_kwh = max((float(row.get("total_kwh") or 0) for row in peer_rows), default=0.0)

    better_than_count = sum(1 for row in peer_rows if float(row.get("total_kwh") or 0) > user_avg_home_kwh)
    better_than_percent = (better_than_count / len(peer_rows) * 100.0) if peer_rows else 0.0

    delta_kwh = user_avg_home_kwh - peer_avg_kwh
    delta_cost = user_avg_home_cost - peer_avg_cost
    percent_vs_average = (delta_kwh / peer_avg_kwh * 100.0) if peer_avg_kwh else 0.0

    if abs(delta_kwh) < 0.01:
        status = "at_average"
    elif delta_kwh < 0:
        status = "below_average"
    else:
        status = "above_average"

    return {
        "has_data": bool(user_rows and community_rows),
        "date": target_date.isoformat() if target_date else None,
        "user": {
            "registered_homes": registered_home_count,
            "homes_with_data": homes_with_data,
            "total_kwh": round(user_total_kwh, 3),
            "total_cost_gbp": round(user_total_cost, 2),
            "avg_home_kwh": round(user_avg_home_kwh, 3),
            "avg_home_cost_gbp": round(user_avg_home_cost, 2),
        },
        "community": {
            "peer_homes_compared": len(peer_rows),
            "avg_home_kwh": round(peer_avg_kwh, 3),
            "avg_home_cost_gbp": round(peer_avg_cost, 2),
            "min_home_kwh": round(peer_min_kwh, 3),
            "max_home_kwh": round(peer_max_kwh, 3),
        },
        "comparison": {
            "status": status,
            "delta_kwh": round(delta_kwh, 3),
            "delta_cost_gbp": round(delta_cost, 2),
            "percent_vs_average": round(percent_vs_average, 1),
            "better_than_percent": round(better_than_percent, 1),
        },
    }


# ── User Rankings ─────────────────────────────────────────────

@router.get("/rankings/me")
async def get_my_rankings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="DAILY", pattern="^(DAILY|WEEKLY|MONTHLY)$"),
    limit: int = Query(default=30, ge=1, le=90),
):
    """Get the current user's ranking history."""
    user_id = _get_user_id(request)
    result = await db.execute(
        select(EnergyRanking)
        .options(joinedload(EnergyRanking.home))
        .where(EnergyRanking.user_id == user_id, EnergyRanking.period_type == period)
        .order_by(EnergyRanking.period_start.desc())
        .limit(limit)
    )
    ranking_rows = result.scalars().all()

    return [
        {
            "user_id": r.user_id,
            "home_id": r.home_id,
            "home_name": r.home.home_name if r.home else "Unknown",
            "period_type": r.period_type,
            "period_start": r.period_start,
            "overall_score": r.overall_score,
            "rank_position": r.rank_position,
            "total_users": r.total_users,
            "percentile": r.percentile,
            "efficiency_score": r.efficiency_score,
            "goal_adherence_score": r.goal_adherence_score,
            "decision_response_score": r.decision_response_score,
            "total_kwh": r.total_kwh,
            "total_cost_gbp": r.total_cost_gbp,
        }
        for r in ranking_rows
    ]


@router.get("/rankings/leaderboard")
async def get_leaderboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="DAILY", pattern="^(DAILY|WEEKLY|MONTHLY)$"),
    date_str: Optional[str] = Query(default=None),
):
    """
    Community leaderboard for a period.

    Privacy: requires auth (no longer a public path) and is fully
    anonymised — peers appear only as "Home #<rank>" with their score and
    percentile. Other households' names and raw kWh are NEVER returned; a
    user may see only their *position* relative to the community plus their
    own row (flagged is_me, and surfaced as `you` even if outside the top).
    """
    user_id = _get_user_id(request)

    if date_str:
        target_date = date.fromisoformat(date_str)
    else:
        target_date = date.today() - timedelta(days=1)

    result = await db.execute(
        select(EnergyRanking)
        .where(EnergyRanking.period_type == period, EnergyRanking.period_start == target_date)
        .order_by(EnergyRanking.rank_position.asc())
        .limit(50)
    )
    ranking_rows = result.scalars().all()

    def _row(r):
        is_me = (r.user_id == user_id)
        return {
            "rank": r.rank_position,
            "label": "You" if is_me else f"Home #{r.rank_position}",
            "overall_score": r.overall_score,
            "efficiency_score": r.efficiency_score,
            "percentile": r.percentile,
            "is_me": is_me,
            "period": target_date.isoformat(),
        }

    leaderboard = [_row(r) for r in ranking_rows]

    # The caller's own standing for this period, even if outside the top 50.
    me_row = next((row for row in leaderboard if row["is_me"]), None)
    if me_row is None:
        own = (await db.execute(
            select(EnergyRanking).where(
                EnergyRanking.user_id == user_id,
                EnergyRanking.period_type == period,
                EnergyRanking.period_start == target_date,
            )
        )).scalar_one_or_none()
        me_row = _row(own) if own else None

    return {
        "period": period,
        "date": target_date.isoformat(),
        "leaderboard": leaderboard,
        "you": me_row,
    }


@router.get("/rankings/community-benchmark")
async def get_community_benchmark(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Compare the current household's latest daily total against the wider community."""
    user_id = _get_user_id(request)

    homes_result = await db.execute(
        select(Home.id)
        .where(Home.user_id == user_id, Home.is_active == True)
        .order_by(Home.id.asc())
    )
    home_ids = list(homes_result.scalars().all())

    if not home_ids:
        return _build_community_benchmark_payload(
            target_date=None,
            registered_home_count=0,
            user_rows=[],
            community_rows=[],
        )

    target_date_result = await db.execute(
        select(func.max(HomeDailyTotal.day_date))
        .join(Home, HomeDailyTotal.home_id == Home.id)
        .where(Home.user_id == user_id, Home.is_active == True)
    )
    target_date = target_date_result.scalar_one_or_none()

    if target_date is None:
        target_date_result = await db.execute(select(func.max(HomeDailyTotal.day_date)))
        target_date = target_date_result.scalar_one_or_none()

    if target_date is None:
        return _build_community_benchmark_payload(
            target_date=None,
            registered_home_count=len(home_ids),
            user_rows=[],
            community_rows=[],
        )

    totals_result = await db.execute(
        select(
            HomeDailyTotal.home_id,
            HomeDailyTotal.total_kwh,
            HomeDailyTotal.total_cost_gbp,
        )
        .join(Home, HomeDailyTotal.home_id == Home.id)
        .where(HomeDailyTotal.day_date == target_date, Home.is_active == True)
    )
    community_rows = [
        {
            "home_id": row.home_id,
            "total_kwh": float(row.total_kwh or 0),
            "total_cost_gbp": float(row.total_cost_gbp or 0),
        }
        for row in totals_result.all()
    ]
    user_rows = [row for row in community_rows if row["home_id"] in home_ids]

    return _build_community_benchmark_payload(
        target_date=target_date,
        registered_home_count=len(home_ids),
        user_rows=user_rows,
        community_rows=community_rows,
    )


# ── Energy Report ─────────────────────────────────────────────

@router.get("/analysis/report")
async def get_energy_report(
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=7, ge=1, le=90),
):
    """Full energy report: per-device breakdown for N days."""
    user_id = _get_user_id(request)
    since = (date.today() - timedelta(days=days))

    homes_result = await db.execute(select(Home).where(Home.user_id == user_id, Home.is_active == True))
    homes = homes_result.scalars().all()

    report_data = []
    for home in homes:
        devices_result = await db.execute(select(Device).where(Device.home_id == home.id, Device.is_active == True))
        devices = devices_result.scalars().all()

        devices_report = []
        for device in devices:
            ds_result = await db.execute(
                select(
                    func.sum(DailySummary.total_kwh).label("total_kwh"),
                    func.sum(DailySummary.estimated_cost_gbp).label("total_cost"),
                    func.avg(DailySummary.efficiency_score).label("avg_eff"),
                    func.sum(DailySummary.usage_cycles).label("total_cycles"),
                )
                .where(DailySummary.device_id == device.id, DailySummary.day_date >= since)
            )
            row = ds_result.one()
            devices_report.append({
                "device_id": device.id,
                "name": device.name,
                "appliance_key": device.appliance_key,
                "location": device.location,
                "total_kwh": round(float(row.total_kwh or 0), 3),
                "total_cost_gbp": round(float(row.total_cost or 0), 2),
                "avg_efficiency_score": round(float(row.avg_eff or 70), 1),
                "total_usage_cycles": int(row.total_cycles or 0),
            })

        devices_report.sort(key=lambda x: x["total_kwh"], reverse=True)
        home_total = sum(d["total_kwh"] for d in devices_report)

        report_data.append({
            "home": {"id": home.id, "name": home.home_name},
            "period_days": days,
            "total_kwh": round(home_total, 3),
            "total_cost_gbp": round(sum(d["total_cost_gbp"] for d in devices_report), 2),
            "devices": devices_report,
        })

    return {"user_id": user_id, "since": since.isoformat(), "homes": report_data}


# ── Historical Consumption (ported from old user-controller.js) ──────────────

@router.get("/readings/{device_id}/historical")
async def get_device_historical_consumption(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Get daily/weekly/monthly/annual kWh consumption averages for a device.
    Ported from old getDeviceHistoricalConsumption endpoint.
    """
    from datetime import timedelta
    from sqlalchemy import select, func
    from app.models import Device, Home, DailySummary

    user_id = _get_user_id(request)

    # Verify ownership
    result = await db.execute(
        select(Device).join(Home, Device.home_id == Home.id).where(
            Device.id == device_id, Home.user_id == user_id, Device.is_active == True
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    today = date.today()
    results = {}

    async def _agg(start: date, end: date, label: str):
        r = await db.execute(
            select(
                func.sum(DailySummary.total_kwh).label("total_kwh"),
                func.avg(DailySummary.total_kwh).label("avg_kwh"),
                func.count(DailySummary.id).label("days"),
                func.sum(DailySummary.estimated_cost_gbp).label("total_cost"),
                func.sum(DailySummary.usage_cycles).label("cycles"),
            ).where(
                DailySummary.device_id == device_id,
                DailySummary.day_date >= start,
                DailySummary.day_date <= end,
            )
        )
        row = r.one()
        return {
            "period": label,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "total_kwh": round(float(row.total_kwh or 0), 3),
            "avg_daily_kwh": round(float(row.avg_kwh or 0), 3),
            "total_cost_gbp": round(float(row.total_cost or 0), 2),
            "total_cycles": int(row.cycles or 0),
            "days_with_data": int(row.days or 0),
        }

    results["daily"] = await _agg(today, today, "today")
    results["weekly"] = await _agg(today - timedelta(days=6), today, "last_7_days")
    results["monthly"] = await _agg(today.replace(day=1), today, "this_month")

    # Last 3 months average
    three_months_ago = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
    three_months_ago = three_months_ago.replace(day=1) - timedelta(days=30)
    results["quarterly"] = await _agg(three_months_ago, today, "last_90_days")

    # Annual estimate (from available data)
    year_start = today.replace(month=1, day=1)
    results["annual"] = await _agg(year_start, today, "year_to_date")

    return {
        "message": "Historical consumption data",
        "device_id": device_id,
        "device_name": device.name,
        "appliance_key": device.appliance_key,
        "historical": results,
    }


@router.get("/readings/{device_id}/daily-breakdown")
async def get_device_daily_breakdown(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=14, ge=1, le=90),
):
    """
    Get per-day kWh for a device for the past N days.
    Used by the Android app for charts and trends.
    """
    from app.models import Device, Home, DailySummary

    user_id = _get_user_id(request)

    result = await db.execute(
        select(Device).join(Home, Device.home_id == Home.id).where(
            Device.id == device_id, Home.user_id == user_id, Device.is_active == True
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    since = date.today() - timedelta(days=days - 1)
    ds_result = await db.execute(
        select(DailySummary).where(
            DailySummary.device_id == device_id,
            DailySummary.day_date >= since,
        ).order_by(DailySummary.day_date.asc())
    )
    summaries = ds_result.scalars().all()

    return {
        "device_id": device_id,
        "device_name": device.name,
        "appliance_key": device.appliance_key,
        "period_days": days,
        "data": [
            {
                "date": s.day_date.isoformat(),
                "total_kwh": round(s.total_kwh or 0, 3),
                "avg_watts": round(s.avg_watts or 0, 1),
                "peak_watts": round(s.peak_watts or 0, 1),
                "usage_cycles": s.usage_cycles or 0,
                "active_minutes": s.active_minutes or 0,
                "estimated_cost_gbp": round(s.estimated_cost_gbp or 0, 3),
                "efficiency_score": s.efficiency_score,
                "goal_met": s.goal_met,
            }
            for s in summaries
        ],
    }


@router.get("/readings/{device_id}/hourly-breakdown")
async def get_device_hourly_breakdown(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    target_date_str: Optional[str] = Query(default=None),
):
    """
    Get per-hour kWh / average watts for a device on a specific date (default: today).
    Used by the Android app for intraday usage charts.
    """
    from app.models import Device, Home

    user_id = _get_user_id(request)

    result = await db.execute(
        select(Device).join(Home, Device.home_id == Home.id).where(
            Device.id == device_id, Home.user_id == user_id, Device.is_active == True
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    target_date = (
        date.fromisoformat(target_date_str) if target_date_str else date.today()
    )

    from sqlalchemy import func as sqlfunc
    hourly_result = await db.execute(
        select(HourlySummary).where(
            HourlySummary.device_id == device_id,
            sqlfunc.date(HourlySummary.hour_start) == target_date,
        ).order_by(HourlySummary.hour_start.asc())
    )
    hourly = hourly_result.scalars().all()

    return {
        "device_id": device_id,
        "device_name": device.name,
        "appliance_key": device.appliance_key,
        "date": target_date.isoformat(),
        "data": [
            {
                "hour": h.hour_start.strftime("%H:%M"),
                "hour_start": h.hour_start.isoformat(),
                "avg_watts": round(h.avg_watts or 0, 1),
                "max_watts": round(h.max_watts or 0, 1),
                "total_kwh": round(h.total_kwh or 0, 4),
                "usage_cycles": h.usage_cycles or 0,
                "active_minutes": h.active_minutes or 0,
            }
            for h in hourly
        ],
    }


@router.get("/readings/{device_id}/optimize")
async def get_device_optimization(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    temperature: float = Query(default=20.0),
    humidity: float = Query(default=50.0),
    pressure: float = Query(default=101.3),
):
    """
    Run the appliance scenario engine for a specific device on demand.
    Returns efficiency analysis, environmental factor corrections, alerts, and recommendations.
    Used by the Android app device detail screen.
    """
    from app.models import Device, Home, DailySummary
    from app.appliance_scenarios import calculate_optimization
    from app.config import settings

    user_id = _get_user_id(request)

    result = await db.execute(
        select(Device).join(Home, Device.home_id == Home.id).where(
            Device.id == device_id, Home.user_id == user_id, Device.is_active == True
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Get today's usage data from MySQL
    today = date.today()
    daily_result = await db.execute(
        select(DailySummary).where(
            DailySummary.device_id == device_id,
            DailySummary.day_date == today
        )
    )
    daily = daily_result.scalar_one_or_none()

    usage_data = {
        "N": daily.usage_cycles or 0 if daily else 0,
        "eaec": (daily.total_kwh / max(daily.usage_cycles, 1))
                if daily and daily.usage_cycles else 0,
        "dailyEAEC": daily.total_kwh or 0 if daily else 0,
        "duration": daily.active_minutes or 0 if daily else 0,
        "avgPower": daily.avg_watts or 0 if daily else 0,
        "isPeakTime": settings.is_peak_time(),
        "standbyTime": 0, "standbyPower": 0,
        "lateNightHours": 0, "keepWarmTime": 0, "shortUseCount": 0,
    }

    optimization = calculate_optimization(
        appliance_key=device.appliance_key,
        temperature=temperature,
        humidity=humidity,
        pressure=pressure,
        usage_data=usage_data,
    )

    return {
        "device_id": device_id,
        "device_name": device.name,
        **optimization,
    }
