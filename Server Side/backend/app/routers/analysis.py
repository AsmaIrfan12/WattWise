"""WattWise — Analysis & Rankings Router."""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnergyRanking, HomeDailyTotal, Home, DailySummary, Device
from app.schemas import RankingResponse

router = APIRouter(prefix="/api", tags=["Analysis & Rankings"])


def _get_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


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
        .where(EnergyRanking.user_id == user_id, EnergyRanking.period_type == period)
        .order_by(EnergyRanking.period_start.desc())
        .limit(limit)
    )
    rankings = result.scalars().all()

    # Add home name
    enriched = []
    for r in rankings:
        home_result = await db.execute(select(Home).where(Home.id == r.home_id))
        home = home_result.scalar_one_or_none()
        enriched.append({
            "user_id": r.user_id,
            "home_id": r.home_id,
            "home_name": home.home_name if home else "Unknown",
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
        })
    return enriched


@router.get("/rankings/leaderboard")
async def get_leaderboard(
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="DAILY", pattern="^(DAILY|WEEKLY|MONTHLY)$"),
    date_str: Optional[str] = Query(default=None),
):
    """Get the community leaderboard for a given period."""
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
    rankings = result.scalars().all()

    # Anonymise non-essential user details (just rank + score)
    leaderboard = []
    for r in rankings:
        home_result = await db.execute(select(Home).where(Home.id == r.home_id))
        home = home_result.scalar_one_or_none()
        leaderboard.append({
            "rank": r.rank_position,
            "home_name": home.home_name if home else "Home",
            "overall_score": r.overall_score,
            "efficiency_score": r.efficiency_score,
            "total_kwh": r.total_kwh,
            "percentile": r.percentile,
            "period": target_date.isoformat(),
        })
    return {"period": period, "date": target_date.isoformat(), "leaderboard": leaderboard}


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
