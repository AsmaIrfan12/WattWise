"""WattWise — Analysis & Rankings Router."""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
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
    rankings = result.scalars().all()

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
        for r in rankings
    ]


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
        .options(joinedload(EnergyRanking.home))
        .where(EnergyRanking.period_type == period, EnergyRanking.period_start == target_date)
        .order_by(EnergyRanking.rank_position.asc())
        .limit(50)
    )
    rankings = result.scalars().all()

    return {
        "period": period,
        "date": target_date.isoformat(),
        "leaderboard": [
            {
                "rank": r.rank_position,
                "home_name": r.home.home_name if r.home else "Home",
                "overall_score": r.overall_score,
                "efficiency_score": r.efficiency_score,
                "total_kwh": r.total_kwh,
                "percentile": r.percentile,
                "period": target_date.isoformat(),
            }
            for r in rankings
        ],
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
