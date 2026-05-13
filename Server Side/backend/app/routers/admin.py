"""WattWise — Admin Router (Protected: is_admin=True only)."""

from datetime import datetime, date, timedelta
from typing import Optional, List

from pydantic import BaseModel
import bcrypt

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    User, Home, Device, Notification, UserDecision,
    AdminNotificationTemplate, EnergyRanking, HomeDailyTotal,
    UserInteractionLog, Persona, AdminAuditLog, EnergyReading,
    DailySummary
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


def _build_admin_community_snapshot(*, target_date, registered_home_count, community_rows):
    homes_with_data = len(community_rows)
    total_kwh = sum(float(row.get("total_kwh") or 0) for row in community_rows)
    total_cost = sum(float(row.get("total_cost_gbp") or 0) for row in community_rows)
    avg_home_kwh = total_kwh / homes_with_data if homes_with_data else 0.0
    avg_home_cost = total_cost / homes_with_data if homes_with_data else 0.0
    min_home_kwh = min((float(row.get("total_kwh") or 0) for row in community_rows), default=0.0)
    max_home_kwh = max((float(row.get("total_kwh") or 0) for row in community_rows), default=0.0)
    return {
        "has_data": bool(target_date and community_rows),
        "date": target_date.isoformat() if target_date else None,
        "registered_homes": registered_home_count,
        "homes_with_data": homes_with_data,
        "total_kwh": round(total_kwh, 3),
        "total_cost_gbp": round(total_cost, 2),
        "avg_home_kwh": round(avg_home_kwh, 3),
        "avg_home_cost_gbp": round(avg_home_cost, 2),
        "min_home_kwh": round(min_home_kwh, 3),
        "max_home_kwh": round(max_home_kwh, 3),
        "peer_homes_compared": homes_with_data,
    }


async def _log_audit(db, admin_user_id, action_type, target_user_id=None, details=None, ip_address=None):
    """Record an admin action in the audit log."""
    log = AdminAuditLog(
        admin_user_id=admin_user_id, action_type=action_type,
        target_user_id=target_user_id, details_json=details, ip_address=ip_address,
    )
    db.add(log)
    await db.commit()


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
async def list_users(
    request: Request, db: AsyncSession = Depends(get_db),
    page: int = 1, limit: int = 50,
    persona_id: Optional[int] = Query(default=None),
    search: Optional[str] = Query(default=None),
):
    _require_admin(request)
    q = select(User).where(User.is_admin == False)
    if persona_id is not None:
        q = q.where(User.persona_id == persona_id)
    if search:
        q = q.where(User.name.ilike(f"%{search}%") | User.email.ilike(f"%{search}%"))
    result = await db.execute(q.offset((page - 1) * limit).limit(limit))
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

    notifs_result = await db.execute(
        select(Notification).where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc()).limit(10)
    )
    notifs = notifs_result.scalars().all()

    persona_name = None
    if user.persona_id:
        p_result = await db.execute(select(Persona).where(Persona.id == user.persona_id))
        p = p_result.scalar_one_or_none()
        persona_name = p.name if p else None

    energy_result = await db.execute(
        select(HomeDailyTotal.day_date, func.sum(HomeDailyTotal.total_kwh).label("kwh"))
        .join(Home, HomeDailyTotal.home_id == Home.id)
        .where(Home.user_id == user_id, HomeDailyTotal.day_date >= date.today() - timedelta(days=7))
        .group_by(HomeDailyTotal.day_date)
        .order_by(HomeDailyTotal.day_date.asc())
    )
    energy_timeline = [{"date": r.day_date.isoformat(), "kwh": round(float(r.kwh or 0), 3)}
                       for r in energy_result.all()]

    return {
        "user": {
            "id": user.id, "name": user.name, "email": user.email,
            "created_at": user.created_at, "last_login": user.last_login_at,
            "push_token_set": bool(user.push_token),
            "notifications_enabled": user.notifications_enabled,
            "persona": persona_name, "persona_id": user.persona_id,
            "daily_goal_kwh": user.daily_energy_goal_kwh,
            "weekly_goal_kwh": user.weekly_energy_goal_kwh,
            "monthly_budget_gbp": user.monthly_budget_gbp,
        },
        "homes": [{"id": h.id, "name": h.home_name, "home_type": h.home_type,
                   "num_occupants": h.num_occupants, "is_active": h.is_active} for h in homes],
        "decision_impact": impact,
        "energy_timeline_7d": energy_timeline,
        "recent_notifications": [{"id": n.id, "type": n.notification_type, "title": n.title,
                                   "read": n.is_read, "created_at": n.created_at} for n in notifs],
    }


@router.patch("/users/{user_id}/toggle-notifications")
async def toggle_notifications(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin_id = _require_admin(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.notifications_enabled = not user.notifications_enabled
    await db.commit()
    await _log_audit(db, admin_id, "TOGGLE_NOTIFICATIONS", target_user_id=user_id,
                     details={"enabled": user.notifications_enabled},
                     ip_address=request.client.host if request.client else None)
    return {"user_id": user_id, "notifications_enabled": user.notifications_enabled}


@router.post("/users/{user_id}/reset-password")
async def admin_reset_password(user_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin_id = _require_admin(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    import secrets as _secrets
    temp_password = _secrets.token_urlsafe(12)
    user.password_hash = bcrypt.hashpw(temp_password.encode(), bcrypt.gensalt(12)).decode()
    user.reset_token = "ADMIN_RESET"
    user.reset_token_expiry = datetime.utcnow() + timedelta(hours=24)
    await db.commit()

    await _log_audit(db, admin_id, "RESET_PASSWORD", target_user_id=user_id,
                     ip_address=request.client.host if request.client else None)
    return {"user_id": user_id, "temp_password": temp_password,
            "note": "Share securely. User must change on next login."}


@router.patch("/users/{user_id}/assign-persona")
async def assign_persona(user_id: int, persona_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    admin_id = _require_admin(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    p_result = await db.execute(select(Persona).where(Persona.id == persona_id))
    persona = p_result.scalar_one_or_none()
    if not persona:
        raise HTTPException(status_code=404, detail="Persona not found")

    old_persona_id = user.persona_id
    user.persona_id = persona_id
    await db.commit()

    await _log_audit(db, admin_id, "ASSIGN_PERSONA", target_user_id=user_id,
                     details={"old_persona_id": old_persona_id, "new_persona_id": persona_id,
                              "persona_name": persona.name},
                     ip_address=request.client.host if request.client else None)
    return {"user_id": user_id, "persona": persona.name}


@router.post("/users/bulk-operation")
async def bulk_operation(
    request: Request, db: AsyncSession = Depends(get_db),
    user_ids: List[int] = Query(description="List of user IDs to operate on"),
    operation: str = Query(pattern="^(enable_notifications|disable_notifications|assign_persona|send_notification)$"),
    persona_id: Optional[int] = Query(default=None),
    notification_title: Optional[str] = Query(default=None),
    notification_message: Optional[str] = Query(default=None),
):
    admin_id = _require_admin(request)
    if not user_ids:
        raise HTTPException(status_code=400, detail="No user IDs provided")

    affected = 0
    for uid in user_ids:
        res = await db.execute(select(User).where(User.id == uid))
        user = res.scalar_one_or_none()
        if not user:
            continue
        if operation == "enable_notifications":
            user.notifications_enabled = True
            affected += 1
        elif operation == "disable_notifications":
            user.notifications_enabled = False
            affected += 1
        elif operation == "assign_persona" and persona_id:
            user.persona_id = persona_id
            affected += 1
        elif operation == "send_notification" and notification_title and notification_message:
            await NotificationEngine.admin_broadcast(
                db=db, title=notification_title, message=notification_message,
                notification_type="ADMIN_BROADCAST", severity="INFO", user_ids=[uid],
            )
            affected += 1

    await db.commit()
    await _log_audit(db, admin_id, "BULK_OPERATION",
                     details={"operation": operation, "user_ids": user_ids, "affected": affected},
                     ip_address=request.client.host if request.client else None)
    return {"operation": operation, "affected": affected}


# ── Personas ──────────────────────────────────────────────────

@router.get("/personas")
async def list_personas(request: Request, db: AsyncSession = Depends(get_db)):
    _require_admin(request)
    result = await db.execute(select(Persona))
    personas = result.scalars().all()
    output = []
    for p in personas:
        count_result = await db.execute(
            select(func.count(User.id)).where(User.persona_id == p.id, User.is_admin == False)
        )
        output.append({
            "id": p.id, "name": p.name, "description": p.description,
            "criteria": p.criteria, "user_count": count_result.scalar() or 0,
        })
    return output


@router.get("/personas/{persona_id}/users")
async def get_persona_users(persona_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    _require_admin(request)
    result = await db.execute(
        select(User).where(User.persona_id == persona_id, User.is_admin == False)
    )
    users = result.scalars().all()
    return [{"id": u.id, "name": u.name, "email": u.email,
             "last_login": u.last_login_at, "notifications_enabled": u.notifications_enabled}
            for u in users]


@router.post("/personas/run-classifier")
async def run_persona_classifier(request: Request, db: AsyncSession = Depends(get_db)):
    admin_id = _require_admin(request)
    from app.persona_classifier import classify_all_users
    summary = await classify_all_users(db)
    await _log_audit(db, admin_id, "RUN_CLASSIFIER", details={"summary": summary},
                     ip_address=request.client.host if request.client else None)
    return {"success": True, "classification_summary": summary}


# ── Admin Notifications ───────────────────────────────────────

@router.post("/notifications/send")
async def send_notification(body: AdminNotificationSend, request: Request, db: AsyncSession = Depends(get_db)):
    admin_id = _require_admin(request)
    count = await NotificationEngine.admin_broadcast(
        db=db, title=body.title, message=body.message,
        notification_type=body.notification_type, severity=body.severity,
        action_hint=body.action_hint, action_button_text=body.action_button_text,
        requires_user_action=body.requires_user_action, user_ids=body.user_ids,
    )
    await _log_audit(db, admin_id, "SEND_NOTIFICATION",
                     details={"title": body.title, "recipients": count, "user_ids": body.user_ids},
                     ip_address=request.client.host if request.client else None)
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
    request: Request, db: AsyncSession = Depends(get_db),
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
    _require_admin(request)
    return await DecisionTracker.get_system_impact_report(db)


@router.get("/analytics/energy")
async def get_energy_analytics(
    request: Request, db: AsyncSession = Depends(get_db),
    days: int = Query(default=7, ge=1, le=365),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
):
    _require_admin(request)
    if start_date and end_date:
        since = date.fromisoformat(start_date)
        until = date.fromisoformat(end_date)
    else:
        until = date.today()
        since = until - timedelta(days=days)

    result = await db.execute(
        select(
            HomeDailyTotal.day_date,
            func.sum(HomeDailyTotal.total_kwh).label("total_kwh"),
            func.sum(HomeDailyTotal.total_cost_gbp).label("total_cost"),
            func.count(func.distinct(HomeDailyTotal.home_id)).label("active_homes"),
            func.avg(HomeDailyTotal.total_kwh).label("avg_kwh"),
        )
        .where(HomeDailyTotal.day_date >= since, HomeDailyTotal.day_date <= until)
        .group_by(HomeDailyTotal.day_date)
        .order_by(HomeDailyTotal.day_date.asc())
    )
    rows = result.all()
    return [
        {
            "date": r.day_date.isoformat(),
            "total_kwh": round(float(r.total_kwh or 0), 2),
            "total_cost_gbp": round(float(r.total_cost or 0), 2),
            "avg_home_kwh": round(float(r.avg_kwh or 0), 2),
            "active_homes": r.active_homes,
        }
        for r in rows
    ]


@router.get("/analytics/community-benchmark")
async def get_community_benchmark(request: Request, db: AsyncSession = Depends(get_db)):
    _require_admin(request)
    home_ids_result = await db.execute(select(Home.id).where(Home.is_active == True).order_by(Home.id.asc()))
    home_ids = list(home_ids_result.scalars().all())

    target_date_result = await db.execute(select(func.max(HomeDailyTotal.day_date)))
    target_date = target_date_result.scalar_one_or_none()
    if target_date is None:
        return _build_admin_community_snapshot(target_date=None, registered_home_count=len(home_ids), community_rows=[])

    totals_result = await db.execute(
        select(HomeDailyTotal.home_id, HomeDailyTotal.total_kwh, HomeDailyTotal.total_cost_gbp)
        .join(Home, HomeDailyTotal.home_id == Home.id)
        .where(HomeDailyTotal.day_date == target_date, Home.is_active == True)
    )
    community_rows = [{"home_id": row.home_id, "total_kwh": float(row.total_kwh or 0),
                       "total_cost_gbp": float(row.total_cost_gbp or 0)}
                      for row in totals_result.all()]
    return _build_admin_community_snapshot(target_date=target_date,
                                           registered_home_count=len(home_ids),
                                           community_rows=community_rows)


@router.get("/analytics/persona-comparison")
async def get_persona_comparison(request: Request, db: AsyncSession = Depends(get_db),
                                  days: int = Query(default=30, ge=7, le=180)):
    _require_admin(request)
    since = date.today() - timedelta(days=days)
    result = await db.execute(
        select(
            Persona.name,
            func.count(func.distinct(User.id)).label("user_count"),
            func.avg(EnergyRanking.efficiency_score).label("avg_efficiency"),
            func.avg(EnergyRanking.goal_adherence_score).label("avg_adherence"),
            func.avg(EnergyRanking.decision_response_score).label("avg_decision"),
            func.avg(EnergyRanking.total_kwh).label("avg_kwh"),
        )
        .join(User, User.persona_id == Persona.id)
        .join(EnergyRanking, EnergyRanking.user_id == User.id)
        .where(EnergyRanking.period_start >= since)
        .group_by(Persona.id, Persona.name)
        .order_by(func.avg(EnergyRanking.efficiency_score).desc())
    )
    rows = result.all()
    return [
        {
            "persona": r.name, "user_count": r.user_count,
            "avg_efficiency_score": round(float(r.avg_efficiency or 0), 1),
            "avg_goal_adherence": round(float(r.avg_adherence or 0), 1),
            "avg_decision_score": round(float(r.avg_decision or 0), 1),
            "avg_daily_kwh": round(float(r.avg_kwh or 0), 3),
        }
        for r in rows
    ]


@router.get("/analytics/user-interactions")
async def get_user_interaction_stats(
    request: Request, db: AsyncSession = Depends(get_db),
    days: int = Query(default=7, ge=1, le=90),
):
    _require_admin(request)
    since = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        select(
            UserInteractionLog.interaction_type,
            func.count().label("count"),
            func.count(func.distinct(UserInteractionLog.user_id)).label("unique_users"),
        )
        .where(UserInteractionLog.created_at >= since)
        .group_by(UserInteractionLog.interaction_type)
        .order_by(func.count().desc())
    )
    rows = result.all()
    return [{"interaction_type": r.interaction_type, "count": r.count, "unique_users": r.unique_users}
            for r in rows]


class CompareRequest(BaseModel):
    entity_type: str  # "user" or "device"
    entity_ids: List[int]
    start_date: str
    end_date: str
    metrics: List[str]  # e.g., ["total_kwh", "cost_gbp", "active_minutes", "peak_watts", "efficiency_score"]


@router.post("/analytics/compare")
async def compare_analytics(req: CompareRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """Advanced Comparative Analytics endpoint."""
    _require_admin(request)

    since = date.fromisoformat(req.start_date)
    until = date.fromisoformat(req.end_date)
    datasets = []

    if req.entity_type == "user":
        # Group metrics by user across all their homes
        for uid in req.entity_ids:
            user_res = await db.execute(select(User).where(User.id == uid))
            user = user_res.scalar_one_or_none()
            if not user:
                continue

            q = (
                select(
                    HomeDailyTotal.day_date,
                    func.sum(HomeDailyTotal.total_kwh).label("total_kwh"),
                    func.sum(HomeDailyTotal.total_cost_gbp).label("cost_gbp"),
                    func.max(HomeDailyTotal.peak_watts).label("peak_watts"),
                    (func.avg(HomeDailyTotal.total_kwh) * 1000 / 24).label("avg_watts"),
                    func.avg(HomeDailyTotal.efficiency_score).label("efficiency_score"),
                )
                .join(Home, HomeDailyTotal.home_id == Home.id)
                .where(
                    Home.user_id == uid,
                    HomeDailyTotal.day_date >= since,
                    HomeDailyTotal.day_date <= until,
                )
                .group_by(HomeDailyTotal.day_date)
                .order_by(HomeDailyTotal.day_date.asc())
            )
            result = await db.execute(q)
            rows = result.all()

            data_points = []
            for r in rows:
                dp = {"date": r.day_date.isoformat()}
                if "total_kwh" in req.metrics: dp["total_kwh"] = round(float(r.total_kwh or 0), 2)
                if "cost_gbp" in req.metrics: dp["cost_gbp"] = round(float(r.cost_gbp or 0), 2)
                if "peak_watts" in req.metrics: dp["peak_watts"] = round(float(r.peak_watts or 0), 2)
                if "avg_watts" in req.metrics: dp["avg_watts"] = round(float(r.avg_watts or 0), 2)
                if "efficiency_score" in req.metrics: dp["efficiency_score"] = round(float(r.efficiency_score or 0), 2)
                data_points.append(dp)

            datasets.append({
                "entity_id": uid,
                "entity_name": user.name,
                "data": data_points
            })

    elif req.entity_type == "device":
        for did in req.entity_ids:
            dev_res = await db.execute(
                select(Device, Home).join(Home, Device.home_id == Home.id).where(Device.id == did)
            )
            row = dev_res.one_or_none()
            if not row:
                continue
            device, home = row

            q = (
                select(DailySummary)
                .where(
                    DailySummary.device_id == did,
                    DailySummary.day_date >= since,
                    DailySummary.day_date <= until,
                )
                .order_by(DailySummary.day_date.asc())
            )
            result = await db.execute(q)
            rows = result.scalars().all()

            data_points = []
            for r in rows:
                dp = {"date": r.day_date.isoformat()}
                if "total_kwh" in req.metrics: dp["total_kwh"] = round(float(r.total_kwh or 0), 2)
                if "cost_gbp" in req.metrics: dp["cost_gbp"] = round(float(r.estimated_cost_gbp or 0), 2)
                if "peak_watts" in req.metrics: dp["peak_watts"] = round(float(r.peak_watts or 0), 2)
                if "avg_watts" in req.metrics: dp["avg_watts"] = round(float(r.avg_watts or 0), 2)
                if "active_minutes" in req.metrics: dp["active_minutes"] = r.active_minutes or 0
                if "efficiency_score" in req.metrics: dp["efficiency_score"] = round(float(r.efficiency_score or 0), 2)
                data_points.append(dp)

            datasets.append({
                "entity_id": did,
                "target_user_id": home.user_id,
                "entity_name": f"{device.name} ({device.appliance_key})",
                "data": data_points
            })

    return {"datasets": datasets}


# ── Device / RPi Monitoring ───────────────────────────────────

@router.get("/devices/status")
async def get_device_status(request: Request, db: AsyncSession = Depends(get_db)):
    _require_admin(request)
    devices_result = await db.execute(
        select(Device, Home, User)
        .join(Home, Device.home_id == Home.id)
        .join(User, Home.user_id == User.id)
        .where(Device.is_active == True)
        .order_by(Home.home_name.asc(), Device.name.asc())
    )
    devices = devices_result.all()

    output = []
    for device, home, user in devices:
        last_reading_result = await db.execute(
            select(EnergyReading.recorded_at, EnergyReading.power_watts)
            .where(EnergyReading.device_id == device.id)
            .order_by(EnergyReading.recorded_at.desc())
            .limit(1)
        )
        last = last_reading_result.one_or_none()
        last_seen = last.recorded_at if last else None
        last_power = last.power_watts if last else None
        online = False
        if last_seen:
            age_minutes = (datetime.utcnow() - last_seen).total_seconds() / 60
            online = age_minutes <= 5
        output.append({
            "device_id": device.id, "device_name": device.name,
            "appliance_key": device.appliance_key, "entity_id": device.entity_id,
            "home": home.home_name, "user": user.name, "user_id": user.id,
            "online": online, "last_seen": last_seen.isoformat() if last_seen else None,
            "last_power_watts": last_power,
        })
    return output


@router.delete("/devices/{device_id}", status_code=204)
async def admin_delete_device(device_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Admin override to deactivate any device in the system."""
    _require_admin(request)
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    
    device.is_active = False
    await db.commit()


# ── Audit Log ─────────────────────────────────────────────────

@router.get("/audit-log")
async def get_audit_log(
    request: Request, db: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
    action_type: Optional[str] = Query(default=None),
    page: int = 1, limit: int = 50,
):
    _require_admin(request)
    since = datetime.utcnow() - timedelta(days=days)
    q = select(AdminAuditLog).where(AdminAuditLog.created_at >= since)
    if action_type:
        q = q.where(AdminAuditLog.action_type == action_type)
    q = q.order_by(AdminAuditLog.created_at.desc()).offset((page - 1) * limit).limit(limit)
    result = await db.execute(q)
    logs = result.scalars().all()
    return [
        {
            "id": l.id, "admin_user_id": l.admin_user_id,
            "action_type": l.action_type, "target_user_id": l.target_user_id,
            "details": l.details_json, "ip_address": l.ip_address,
            "created_at": l.created_at.isoformat(),
        }
        for l in logs
    ]


# ── System Operations ─────────────────────────────────────────

@router.post("/trigger-aggregations")
async def trigger_aggregations(request: Request, days: int = Query(default=2, ge=1, le=30)):
    _require_admin(request)
    from app.scheduler import aggregate_hourly, aggregate_daily
    now = datetime.utcnow()
    for h in range(days * 24, 0, -1):
        target_time = now - timedelta(hours=h - 1)
        await aggregate_hourly(target_time)
    for d in range(days, -1, -1):
        target_date = (now - timedelta(days=d)).date()
        await aggregate_daily(target_date)
    return {"message": f"Successfully aggregated {days} days of historical data."}


@router.post("/trigger-smart-notifications-all")
async def trigger_smart_notifications_all(
    request: Request, db: AsyncSession = Depends(get_db)
):
    """
    Run smart notifications for every non-admin user with notifications enabled.
    Uses existing notification types so the current DB enum and dedup logic remain valid.
    """
    from app.models import Room
    from app.appliance_scenarios import calculate_optimization
    from app.routers.smart_notifications import (
        _build_usage_data_for_device,
        _fetch_env_conditions,
        _get_influx,
    )

    admin_id = _require_admin(request)

    users_result = await db.execute(
        select(User).where(User.is_admin == False, User.notifications_enabled == True)
    )
    users = users_result.scalars().all()

    users_processed = 0
    notifications_created = 0
    skipped_dedup = 0
    today = date.today()
    influx = _get_influx()

    for user in users:
        homes_result = await db.execute(
            select(Home).where(Home.user_id == user.id, Home.is_active == True)
        )
        homes = homes_result.scalars().all()
        if not homes:
            continue

        users_processed += 1

        for home in homes:
            env = {"temperature": 20.0, "humidity": 50.0, "pressure": 101.3}
            try:
                rooms_result = await db.execute(select(Room).where(Room.home_id == home.id))
                rooms = rooms_result.scalars().all()
                if rooms:
                    room = rooms[0]
                    entity_base = room.entity_id or room.name.lower().replace(" ", "")
                    env = _fetch_env_conditions(influx, entity_base)
            except Exception:
                pass

            devices_result = await db.execute(
                select(Device).where(Device.home_id == home.id, Device.is_active == True)
            )
            devices = devices_result.scalars().all()

            for device in devices:
                if not device.appliance_key:
                    continue

                daily_result = await db.execute(
                    select(DailySummary).where(
                        DailySummary.device_id == device.id,
                        DailySummary.day_date == today,
                    )
                )
                daily = daily_result.scalar_one_or_none()
                usage_data = _build_usage_data_for_device(device, daily)

                try:
                    payload = calculate_optimization(
                        appliance_key=device.appliance_key,
                        temperature=env["temperature"],
                        humidity=env["humidity"],
                        pressure=env["pressure"],
                        usage_data=usage_data,
                    )
                except Exception:
                    continue

                for alert in payload.get("alerts", []):
                    if alert.get("priority") not in ("critical", "warning"):
                        continue

                    severity = "CRITICAL" if alert["priority"] == "critical" else "WARNING"
                    notification_type = "ENERGY_ALERT" if severity == "CRITICAL" else "RECOMMENDATION"

                    notif = await NotificationEngine.create_notification(
                        db=db,
                        user_id=user.id,
                        title=f"⚡ {device.name}: {alert['scenario']}",
                        message=alert.get("message", "Review your appliance usage."),
                        notification_type=notification_type,
                        severity=severity,
                        home_id=home.id,
                        device_id=device.id,
                        requires_user_action=True,
                        metadata={
                            "source": "admin_trigger_all",
                            "appliance_key": device.appliance_key,
                            "priority": alert.get("priority"),
                            "scenario": alert.get("scenario"),
                            "efficiency_score": payload.get("efficiency_score"),
                        },
                    )
                    if notif:
                        notifications_created += 1
                    else:
                        skipped_dedup += 1

    await _log_audit(
        db,
        admin_id,
        "TRIGGER_SMART_NOTIFICATIONS",
        details={
            "users_processed": users_processed,
            "notifications_created": notifications_created,
            "skipped_dedup": skipped_dedup,
        },
        ip_address=request.client.host if request.client else None,
    )

    return {
        "users_processed": users_processed,
        "notifications_created": notifications_created,
        "skipped_dedup": skipped_dedup,
    }
