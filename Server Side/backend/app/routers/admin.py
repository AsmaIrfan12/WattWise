"""WattWise — Admin Router (Protected: is_admin=True only)."""

from datetime import datetime, date, timedelta
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    User, Home, Device, Notification, UserDecision,
    AdminNotificationTemplate, EnergyRanking, HomeDailyTotal,
    UserInteractionLog
)
from app.schemas import (
    AdminNotificationSend, AdminTemplateCreate,
    AdminDashboardResponse, UserResponse
)
from app.notification_engine import NotificationEngine
from app.decision_tracker import DecisionTracker

router = APIRouter(prefix="/api/admin", tags=["Admin"])


def _require_admin(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    is_admin = getattr(request.state, "is_admin", False)
    if not user_id or not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


# ── Dashboard ─────────────────────────────────────────────────

@router.get("/dashboard", response_model=AdminDashboardResponse)
async def get_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    _require_admin(request)
    today = date.today()
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    total_users = (await db.execute(select(func.count(User.id)).where(User.is_admin == False))).scalar()
    active_today = (await db.execute(
        select(func.count(func.distinct(UserInteractionLog.user_id)))
        .where(UserInteractionLog.created_at >= today_start)
    )).scalar()
    total_homes = (await db.execute(select(func.count(Home.id)).where(Home.is_active == True))).scalar()
    total_devices = (await db.execute(select(func.count(Device.id)).where(Device.is_active == True))).scalar()

    # Today's energy across all homes
    energy_result = await db.execute(
        select(func.sum(HomeDailyTotal.total_kwh), func.sum(HomeDailyTotal.total_cost_gbp))
        .where(HomeDailyTotal.day_date == today)
    )
    erow = energy_result.one()
    energy_kwh = float(erow[0] or 0)
    cost_gbp = float(erow[1] or 0)

    notifs_today = (await db.execute(
        select(func.count(Notification.id)).where(Notification.created_at >= today_start)
    )).scalar()
    decisions_today = (await db.execute(
        select(func.count(UserDecision.id)).where(UserDecision.created_at >= today_start)
    )).scalar()

    # Average goal adherence (from rankings)
    adherence_result = await db.execute(
        select(func.avg(EnergyRanking.goal_adherence_score))
        .where(EnergyRanking.period_start == today - timedelta(days=1))
    )
    avg_adherence = float(adherence_result.scalar() or 70.0)

    return AdminDashboardResponse(
        total_users=total_users or 0,
        active_users_today=active_today or 0,
        total_homes=total_homes or 0,
        total_devices=total_devices or 0,
        energy_today_kwh=round(energy_kwh, 2),
        cost_today_gbp=round(cost_gbp, 2),
        notifications_sent_today=notifs_today or 0,
        decisions_recorded_today=decisions_today or 0,
        avg_goal_adherence_pct=round(avg_adherence, 1),
    )


# ── User Management ───────────────────────────────────────────

@router.get("/users", response_model=list[UserResponse])
async def list_users(request: Request, db: AsyncSession = Depends(get_db),
                     page: int = 1, limit: int = 50):
    _require_admin(request)
    result = await db.execute(
        select(User).where(User.is_admin == False)
        .offset((page - 1) * limit).limit(limit)
    )
    return result.scalars().all()


@router.get("/users/{user_id}/details")
async def get_user_details(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    _require_admin(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    homes_result = await db.execute(select(Home).where(Home.user_id == user_id))
    homes = homes_result.scalars().all()

    impact = await DecisionTracker.get_user_impact_report(db, user_id)

    # Recent notifications
    notifs_result = await db.execute(
        select(Notification).where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc()).limit(10)
    )
    notifs = notifs_result.scalars().all()

    return {
        "user": {"id": user.id, "name": user.name, "email": user.email,
                  "created_at": user.created_at, "last_login": user.last_login_at,
                  "push_token_set": bool(user.push_token),
                  "notifications_enabled": user.notifications_enabled},
        "homes": [{"id": h.id, "name": h.home_name, "home_type": h.home_type} for h in homes],
        "decision_impact": impact,
        "recent_notifications": [
            {"id": n.id, "type": n.notification_type, "title": n.title,
             "read": n.is_read, "created_at": n.created_at}
            for n in notifs
        ],
    }


# ── Admin Notifications ───────────────────────────────────────

@router.post("/notifications/send")
async def send_notification(body: AdminNotificationSend, request: Request, db: AsyncSession = Depends(get_db)):
    """Send a notification to specific users or all users (broadcast)."""
    _require_admin(request)
    count = await NotificationEngine.admin_broadcast(
        db=db,
        title=body.title,
        message=body.message,
        notification_type=body.notification_type,
        severity=body.severity,
        action_hint=body.action_hint,
        action_button_text=body.action_button_text,
        requires_user_action=body.requires_user_action,
        user_ids=body.user_ids,
    )
    return {"success": True, "notifications_sent": count}


@router.get("/notifications/templates")
async def list_templates(request: Request, db: AsyncSession = Depends(get_db)):
    _require_admin(request)
    result = await db.execute(select(AdminNotificationTemplate).where(AdminNotificationTemplate.is_active == True))
    return result.scalars().all()


@router.post("/notifications/templates", status_code=201)
async def create_template(body: AdminTemplateCreate, request: Request, db: AsyncSession = Depends(get_db)):
    admin_id = _require_admin(request)
    tmpl = AdminNotificationTemplate(created_by=admin_id, **body.model_dump())
    db.add(tmpl)
    await db.commit()
    await db.refresh(tmpl)
    return tmpl


# ── Rankings (Admin View) ─────────────────────────────────────

@router.get("/rankings")
async def get_rankings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="DAILY", pattern="^(DAILY|WEEKLY|MONTHLY)$"),
    date_str: Optional[str] = Query(default=None),
):
    _require_admin(request)
    target_date = date.fromisoformat(date_str) if date_str else date.today() - timedelta(days=1)
    result = await db.execute(
        select(EnergyRanking, User, Home)
        .join(User, EnergyRanking.user_id == User.id)
        .join(Home, EnergyRanking.home_id == Home.id)
        .where(EnergyRanking.period_type == period, EnergyRanking.period_start == target_date)
        .order_by(EnergyRanking.rank_position.asc())
    )
    rows = result.all()
    return [
        {
            "rank": r.rank_position, "user_id": u.id, "user_name": u.name,
            "home": h.home_name, "score": r.overall_score,
            "efficiency": r.efficiency_score, "goal_adherence": r.goal_adherence_score,
            "decision_score": r.decision_response_score,
            "total_kwh": r.total_kwh, "cost_gbp": r.total_cost_gbp,
            "percentile": r.percentile,
        }
        for r, u, h in rows
    ]


# ── Analytics ─────────────────────────────────────────────────

@router.get("/analytics/decisions")
async def get_decision_analytics(request: Request, db: AsyncSession = Depends(get_db)):
    """System-wide user decision impact analytics."""
    _require_admin(request)
    return await DecisionTracker.get_system_impact_report(db)


@router.get("/analytics/energy")
async def get_energy_analytics(request: Request, db: AsyncSession = Depends(get_db),
                                days: int = Query(default=7, ge=1, le=90)):
    """System-wide energy consumption analytics."""
    _require_admin(request)
    since = date.today() - timedelta(days=days)
    result = await db.execute(
        select(
            HomeDailyTotal.day_date,
            func.sum(HomeDailyTotal.total_kwh).label("total_kwh"),
            func.sum(HomeDailyTotal.total_cost_gbp).label("total_cost"),
            func.count(func.distinct(HomeDailyTotal.home_id)).label("active_homes"),
        )
        .where(HomeDailyTotal.day_date >= since)
        .group_by(HomeDailyTotal.day_date)
        .order_by(HomeDailyTotal.day_date.asc())
    )
    rows = result.all()
    return [
        {"date": r.day_date.isoformat(), "total_kwh": round(float(r.total_kwh or 0), 2),
         "total_cost_gbp": round(float(r.total_cost or 0), 2), "active_homes": r.active_homes}
        for r in rows
    ]
@router.post("/trigger-aggregations")
async def trigger_aggregations(request: Request, days: int = Query(default=2, ge=1, le=30)):
    """Manually trigger historical aggregations (useful after backfilling data)."""
    _require_admin(request)
    from app.scheduler import aggregate_hourly, aggregate_daily
    
    now = datetime.utcnow()
    # Trigger hourly aggregations
    # Step hour by hour back
    for h in range(days * 24, 0, -1):
        target_time = now - timedelta(hours=h - 1)
        await aggregate_hourly(target_time)
        
    # Trigger daily aggregations
    for d in range(days, -1, -1):
        target_date = (now - timedelta(days=d)).date()
        await aggregate_daily(target_date)
        
    return {"message": f"Successfully aggregated {days} days of historical data."}
