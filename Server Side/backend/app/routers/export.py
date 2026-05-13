"""WattWise — Admin Data Export Router (CSV/JSON for research)."""

import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import UserDecision, EnergyRanking, HomeDailyTotal, User, Home

router = APIRouter(prefix="/api/admin/export", tags=["Admin Export"])


def _require_admin(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    is_admin = getattr(request.state, "is_admin", False)
    if not user_id or not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


@router.get("/decisions")
async def export_decisions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    fmt: str = Query(default="csv", pattern="^(csv|json)$"),
    days: int = Query(default=90, ge=1, le=365),
):
    """Export all user decisions with energy impact data for research analysis."""
    _require_admin(request)
    since = date.today() - timedelta(days=days)

    result = await db.execute(
        select(UserDecision, User)
        .join(User, UserDecision.user_id == User.id)
        .where(func.date(UserDecision.created_at) >= since)
        .order_by(UserDecision.created_at.asc())
    )
    rows = result.all()

    if fmt == "json":
        import json
        data = [
            {
                "id": d.id, "user_id": d.user_id, "user_email": u.email,
                "notification_id": d.notification_id, "device_id": d.device_id,
                "decision_type": d.decision_type, "action_taken": d.action_taken,
                "action_timestamp": d.action_timestamp.isoformat() if d.action_timestamp else None,
                "energy_before_kwh": float(d.energy_before_kwh) if d.energy_before_kwh else None,
                "energy_after_kwh": float(d.energy_after_kwh) if d.energy_after_kwh else None,
                "energy_saved_kwh": float(d.energy_saved_kwh) if d.energy_saved_kwh else None,
                "cost_saved_gbp": float(d.cost_saved_gbp) if d.cost_saved_gbp else None,
                "effectiveness_score": float(d.effectiveness_score) if d.effectiveness_score else None,
                "response_time_seconds": d.response_time_seconds,
                "user_satisfaction": d.user_satisfaction,
                "user_feedback_text": d.user_feedback_text,
                "created_at": d.created_at.isoformat(),
            }
            for d, u in rows
        ]
        return StreamingResponse(
            iter([json.dumps(data, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=wattwise_decisions_{date.today()}.json"}
        )

    # CSV
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "user_id", "user_email", "notification_id", "device_id",
        "decision_type", "action_taken", "action_timestamp",
        "energy_before_kwh", "energy_after_kwh", "energy_saved_kwh",
        "cost_saved_gbp", "effectiveness_score", "response_time_seconds",
        "user_satisfaction", "user_feedback_text", "created_at"
    ])
    for d, u in rows:
        writer.writerow([
            d.id, d.user_id, u.email, d.notification_id, d.device_id,
            d.decision_type, d.action_taken,
            d.action_timestamp.isoformat() if d.action_timestamp else "",
            d.energy_before_kwh, d.energy_after_kwh, d.energy_saved_kwh,
            d.cost_saved_gbp, d.effectiveness_score, d.response_time_seconds,
            d.user_satisfaction, d.user_feedback_text, d.created_at.isoformat()
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=wattwise_decisions_{date.today()}.csv"}
    )


@router.get("/rankings")
async def export_rankings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    fmt: str = Query(default="csv", pattern="^(csv|json)$"),
    period: str = Query(default="DAILY", pattern="^(DAILY|WEEKLY|MONTHLY)$"),
    days: int = Query(default=30, ge=1, le=365),
):
    """Export community rankings data for research."""
    _require_admin(request)
    since = date.today() - timedelta(days=days)

    result = await db.execute(
        select(EnergyRanking, User, Home)
        .join(User, EnergyRanking.user_id == User.id)
        .join(Home, EnergyRanking.home_id == Home.id)
        .where(EnergyRanking.period_type == period, EnergyRanking.period_start >= since)
        .order_by(EnergyRanking.period_start.desc(), EnergyRanking.rank_position.asc())
    )
    rows = result.all()

    if fmt == "json":
        import json
        data = [
            {
                "period_start": r.period_start.isoformat(), "rank": r.rank_position,
                "total_users": r.total_users, "percentile": float(r.percentile or 0),
                "user_id": r.user_id, "home_id": r.home_id, "home_type": h.home_type,
                "num_occupants": h.num_occupants,
                "overall_score": float(r.overall_score or 0),
                "efficiency_score": float(r.efficiency_score or 0),
                "goal_adherence_score": float(r.goal_adherence_score or 0),
                "decision_response_score": float(r.decision_response_score or 0),
                "total_kwh": float(r.total_kwh or 0),
                "total_cost_gbp": float(r.total_cost_gbp or 0),
            }
            for r, u, h in rows
        ]
        return StreamingResponse(
            iter([json.dumps(data, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=wattwise_rankings_{date.today()}.json"}
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "period_start", "rank", "total_users", "percentile", "user_id", "home_id",
        "home_type", "num_occupants", "overall_score", "efficiency_score",
        "goal_adherence_score", "decision_response_score", "total_kwh", "total_cost_gbp"
    ])
    for r, u, h in rows:
        writer.writerow([
            r.period_start, r.rank_position, r.total_users, r.percentile,
            r.user_id, r.home_id, h.home_type, h.num_occupants,
            r.overall_score, r.efficiency_score, r.goal_adherence_score,
            r.decision_response_score, r.total_kwh, r.total_cost_gbp
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=wattwise_rankings_{date.today()}.csv"}
    )


@router.get("/energy")
async def export_energy(
    request: Request,
    db: AsyncSession = Depends(get_db),
    fmt: str = Query(default="csv", pattern="^(csv|json)$"),
    days: int = Query(default=30, ge=1, le=365),
):
    """Export system-wide daily energy totals per home."""
    _require_admin(request)
    since = date.today() - timedelta(days=days)

    result = await db.execute(
        select(HomeDailyTotal, Home, User)
        .join(Home, HomeDailyTotal.home_id == Home.id)
        .join(User, Home.user_id == User.id)
        .where(HomeDailyTotal.day_date >= since)
        .order_by(HomeDailyTotal.day_date.asc(), HomeDailyTotal.home_id.asc())
    )
    rows = result.all()

    if fmt == "json":
        import json
        data = [
            {
                "date": t.day_date.isoformat(), "home_id": t.home_id,
                "home_type": h.home_type, "num_occupants": h.num_occupants,
                "total_kwh": float(t.total_kwh or 0),
                "total_cost_gbp": float(t.total_cost_gbp or 0),
                "active_devices": t.active_devices,
                "kwh_per_person": round(float(t.total_kwh or 0) / max(h.num_occupants or 1, 1), 4),
            }
            for t, h, u in rows
        ]
        return StreamingResponse(
            iter([json.dumps(data, indent=2)]),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename=wattwise_energy_{date.today()}.json"}
        )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "date", "home_id", "home_type", "num_occupants",
        "total_kwh", "total_cost_gbp", "active_devices", "kwh_per_person"
    ])
    for t, h, u in rows:
        occupants = max(h.num_occupants or 1, 1)
        writer.writerow([
            t.day_date, t.home_id, h.home_type, h.num_occupants,
            t.total_kwh, t.total_cost_gbp, t.active_devices,
            round(float(t.total_kwh or 0) / float(occupants), 4)
        ])
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=wattwise_energy_{date.today()}.csv"}
    )
