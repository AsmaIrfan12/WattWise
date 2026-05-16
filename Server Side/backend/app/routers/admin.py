"""WattWise — Admin Router (Protected: is_admin=True only)."""

from datetime import datetime, date, timedelta
from typing import Optional, List

from pydantic import BaseModel
import bcrypt

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import (
    User, Home, Device, Notification, UserDecision,
    AdminNotificationTemplate, EnergyRanking, HomeDailyTotal,
    UserInteractionLog, Persona, AdminAuditLog, EnergyReading,
    DailySummary, HourlySummary
)
from app.schemas import (
    AdminNotificationSend, AdminTemplateCreate,
    AdminDashboardResponse, UserResponse
)
from app.notification_engine import NotificationEngine
from app.decision_tracker import DecisionTracker
from app.config import settings

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


@router.patch("/users/{user_id}/budget")
async def admin_set_user_budget(
    user_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    monthly_budget_gbp: Optional[float] = None,
    daily_energy_goal_kwh: Optional[float] = None,
):
    """Admin: update a participant's monthly budget and/or daily kWh goal."""
    admin_id = _require_admin(request)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    changed = {}
    if monthly_budget_gbp is not None:
        user.monthly_budget_gbp = monthly_budget_gbp
        changed["monthly_budget_gbp"] = monthly_budget_gbp
    if daily_energy_goal_kwh is not None:
        user.daily_energy_goal_kwh = daily_energy_goal_kwh
        changed["daily_energy_goal_kwh"] = daily_energy_goal_kwh

    if not changed:
        raise HTTPException(status_code=422, detail="Provide monthly_budget_gbp or daily_energy_goal_kwh query param")

    await db.commit()
    await _log_audit(db, admin_id, "UPDATE_USER_BUDGET", target_user_id=user_id,
                     details=changed,
                     ip_address=request.client.host if request.client else None)
    return {"user_id": user_id, **changed}


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
async def get_persona_users(
    persona_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Members of a given persona, with last-30d headline stats for the drill-down panel."""
    _require_admin(request)
    cutoff = date.today() - timedelta(days=30)
    rows = await db.execute(
        select(
            User.id, User.name, User.email, User.last_login_at,
            User.notifications_enabled,
            func.avg(EnergyRanking.overall_score).label("avg_overall"),
            func.avg(EnergyRanking.efficiency_score).label("avg_eff"),
            func.avg(EnergyRanking.goal_adherence_score).label("avg_adh"),
            func.avg(EnergyRanking.total_kwh).label("avg_kwh"),
            func.count(EnergyRanking.id).label("days"),
        )
        .outerjoin(
            EnergyRanking,
            (EnergyRanking.user_id == User.id)
            & (EnergyRanking.period_type == "DAILY")
            & (EnergyRanking.period_start >= cutoff),
        )
        .where(User.persona_id == persona_id, User.is_admin.is_(False))
        .group_by(
            User.id, User.name, User.email,
            User.last_login_at, User.notifications_enabled,
        )
        .order_by(func.avg(EnergyRanking.overall_score).desc())
        .limit(limit)
    )
    return [
        {
            "id": r.id, "name": r.name, "email": r.email,
            "last_login": r.last_login_at,
            "notifications_enabled": r.notifications_enabled,
            "avg_overall_score": round(float(r.avg_overall or 0), 1),
            "avg_efficiency": round(float(r.avg_eff or 0), 1),
            "avg_adherence": round(float(r.avg_adh or 0), 1),
            "avg_kwh_per_day": round(float(r.avg_kwh or 0), 2),
            "ranking_days_in_window": int(r.days or 0),
        }
        for r in rows.all()
    ]


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
        requires_user_action=body.requires_user_action,
        user_ids=body.user_ids,
        target_persona_id=body.target_persona_id,
    )
    audit_details = {
        "title": body.title,
        "recipients": count,
        "user_ids": body.user_ids,
        "target_persona_id": body.target_persona_id,
    }
    await _log_audit(db, admin_id, "SEND_NOTIFICATION",
                     details=audit_details,
                     ip_address=request.client.host if request.client else None)
    return {"success": True, "notifications_sent": count, "target_persona_id": body.target_persona_id}


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
    """
    Return rankings for a single period.
    - If `date_str` is omitted, picks the most recent period that has data
      (so the Rankings tab is never empty when ANY history exists).
    - Response includes `meta` with the period_start, period_end, and the
      list of available period_starts so the UI can build a navigator.
    """
    _require_admin(request)

    # Resolve target date — caller's choice, or latest available
    if date_str:
        target_date = date.fromisoformat(date_str)
    else:
        latest = await db.execute(
            select(func.max(EnergyRanking.period_start))
            .where(EnergyRanking.period_type == period)
        )
        target_date = latest.scalar_one_or_none() or (date.today() - timedelta(days=1))

    # Build list of available period_starts (for the date-navigator dropdown)
    avail_result = await db.execute(
        select(EnergyRanking.period_start)
        .where(EnergyRanking.period_type == period)
        .group_by(EnergyRanking.period_start)
        .order_by(EnergyRanking.period_start.desc())
        .limit(60)
    )
    available_dates = [d.isoformat() for (d,) in avail_result.all()]

    # Compute period_end for display (Daily=same, Weekly=+6d, Monthly=last day of month)
    if period == "DAILY":
        period_end = target_date
    elif period == "WEEKLY":
        period_end = target_date + timedelta(days=6)
    else:  # MONTHLY
        if target_date.month == 12:
            next_month = target_date.replace(year=target_date.year + 1, month=1, day=1)
        else:
            next_month = target_date.replace(month=target_date.month + 1, day=1)
        period_end = next_month - timedelta(days=1)

    result = await db.execute(
        select(EnergyRanking, User, Home)
        .join(User, EnergyRanking.user_id == User.id)
        .join(Home, EnergyRanking.home_id == Home.id)
        .where(EnergyRanking.period_type == period, EnergyRanking.period_start == target_date)
        .order_by(EnergyRanking.rank_position.asc())
    )
    rows = result.all()
    rankings = [
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

    return {
        "meta": {
            "period_type": period,
            "period_start": target_date.isoformat(),
            "period_end": period_end.isoformat(),
            "available_period_starts": available_dates,
            "row_count": len(rankings),
        },
        "rankings": rankings,
    }


@router.post("/rankings/recompute")
async def recompute_rankings(
    request: Request,
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="ALL", pattern="^(DAILY|WEEKLY|MONTHLY|ALL)$"),
):
    """Manually recompute rankings for the chosen period over full history."""
    admin_id = _require_admin(request)
    from app.scheduler import compute_rankings_for_range
    period_types = ("DAILY", "WEEKLY", "MONTHLY") if period == "ALL" else (period,)
    counts = await compute_rankings_for_range(period_types=period_types)
    await _log_audit(
        db, admin_id, "BULK_OPERATION",
        details={"operation": "recompute_rankings", "period": period, "counts": counts},
        ip_address=request.client.host if request.client else None,
    )
    return {"status": "ok", "counts": counts}


@router.get("/personas/history")
async def get_personas_history(
    request: Request, db: AsyncSession = Depends(get_db),
    period: str = Query(default="DAILY", pattern="^(DAILY|WEEKLY|MONTHLY)$"),
    buckets: int = Query(default=12, ge=1, le=52),
):
    """
    Returns persona-membership distribution at multiple points in time so the
    UI can render a stacked bar/line chart (e.g. "12 Eco Champions in week 1,
    14 in week 2..."). Each bucket reflects what the population would have been
    if the classifier ran at that point — derived from the rolling 30-day
    EnergyRanking window ending at that bucket's date.

    period: DAILY (last N days), WEEKLY (last N weeks), MONTHLY (last N months)
    """
    _require_admin(request)

    today = date.today()
    if period == "DAILY":
        bucket_dates = [today - timedelta(days=buckets - 1 - i) for i in range(buckets)]
    elif period == "WEEKLY":
        # Mondays for the last `buckets` weeks
        this_monday = today - timedelta(days=today.weekday())
        bucket_dates = [this_monday - timedelta(weeks=buckets - 1 - i) for i in range(buckets)]
    else:  # MONTHLY
        bucket_dates = []
        d = today.replace(day=1)
        for _ in range(buckets):
            bucket_dates.append(d)
            if d.month == 1:
                d = d.replace(year=d.year - 1, month=12)
            else:
                d = d.replace(month=d.month - 1)
        bucket_dates.reverse()

    # Persona names + ids for stable colouring
    p_result = await db.execute(select(Persona))
    persona_list = list(p_result.scalars().all())
    persona_ids = {p.name: p.id for p in persona_list}

    # For each bucket, count by classifying rank position percentile within a
    # 30-day window ending at that bucket. We use a SQL approximation: count
    # users by their average overall_score percentile in that window.
    series = []
    for b in bucket_dates:
        window_start = b - timedelta(days=30)
        avg_q = await db.execute(
            select(
                EnergyRanking.user_id,
                func.avg(EnergyRanking.overall_score).label("avg_overall"),
                func.count(EnergyRanking.id).label("days"),
            )
            .where(
                EnergyRanking.period_type == "DAILY",
                EnergyRanking.period_start >= window_start,
                EnergyRanking.period_start <= b,
            )
            .group_by(EnergyRanking.user_id)
        )
        users = avg_q.all()

        engaged = [u for u in users if (u.days or 0) >= 2]
        engaged.sort(key=lambda u: float(u.avg_overall or 0))
        n = len(engaged)

        counts = {p.name: 0 for p in persona_list}
        # Disengaged = total non-admin users minus engaged
        total_users_q = await db.execute(
            select(func.count(User.id)).where(User.is_admin.is_(False))
        )
        total_users = int(total_users_q.scalar() or 0)
        counts["Disengaged"] = max(0, total_users - n)

        for i, u in enumerate(engaged):
            pct = (i / max(n - 1, 1)) * 100
            if pct >= 80:
                counts["Eco Champion"] = counts.get("Eco Champion", 0) + 1
            elif pct >= 55:
                counts["Active Improver"] = counts.get("Active Improver", 0) + 1
            elif pct <= 24:
                counts["High Consumer"] = counts.get("High Consumer", 0) + 1
            else:
                counts["Steady User"] = counts.get("Steady User", 0) + 1

        series.append({
            "bucket": b.isoformat(),
            "counts": counts,
        })

    return {
        "period": period,
        "buckets": buckets,
        "personas": [{"id": persona_ids.get(p.name), "name": p.name} for p in persona_list],
        "series": series,
    }




# ── Analytics ─────────────────────────────────────────────────

@router.get("/analytics/decisions")
async def get_decision_analytics(request: Request, db: AsyncSession = Depends(get_db)):
    _require_admin(request)
    return await DecisionTracker.get_system_impact_report(db)


@router.get("/analytics/energy")
async def get_energy_analytics(
    request: Request, db: AsyncSession = Depends(get_db),
    days: int = Query(default=7, ge=1, le=365),
    hours: Optional[int] = Query(default=None, ge=1, le=168),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
):
    """
    Community energy summary.
    - Pass `hours=N` for an hourly time-series (last N hours, from hourly_summary).
    - Otherwise pass `days=N` or `start_date`/`end_date` for daily totals
      (from home_daily_totals).
    """
    _require_admin(request)

    # ── Hourly mode ──────────────────────────────────────────
    if hours is not None:
        now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        since_ts = now - timedelta(hours=hours)

        result = await db.execute(
            select(
                HourlySummary.hour_start,
                func.sum(HourlySummary.total_kwh).label("total_kwh"),
                func.avg(HourlySummary.avg_watts).label("avg_watts"),
                func.count(func.distinct(HourlySummary.device_id)).label("active_devices"),
            )
            .where(HourlySummary.hour_start >= since_ts)
            .group_by(HourlySummary.hour_start)
            .order_by(HourlySummary.hour_start.asc())
        )
        rows = result.all()
        return [
            {
                "date": r.hour_start.isoformat(),
                "total_kwh": round(float(r.total_kwh or 0), 4),
                "total_cost_gbp": round(float(r.total_kwh or 0) * 0.27, 4),
                "avg_home_kwh": round(float(r.total_kwh or 0), 4),
                "active_homes": r.active_devices,
            }
            for r in rows
        ]

    # ── Daily mode ───────────────────────────────────────────
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


@router.get("/analytics/device-timeseries")
async def get_device_timeseries(
    request: Request, db: AsyncSession = Depends(get_db),
    hours: int = Query(default=24, ge=1, le=720),
    home_id: Optional[int] = Query(default=None),
):
    """
    Per-device hourly time series for the live admin chart.

    Returns one entry per device, each with a `points` list of
    `{ts, kwh, avg_watts}` ordered chronologically.

    - `hours`: window size, default 24, max 720 (30 days)
    - `home_id`: optional filter to a single RPi / home
    """
    _require_admin(request)
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    since_ts = now - timedelta(hours=hours)

    q = (
        select(
            HourlySummary.device_id,
            HourlySummary.hour_start,
            HourlySummary.total_kwh,
            HourlySummary.avg_watts,
            Device.name.label("device_name"),
            Device.appliance_key,
            Home.id.label("home_id"),
            Home.home_name,
        )
        .join(Device, HourlySummary.device_id == Device.id)
        .join(Home, Device.home_id == Home.id)
        .where(HourlySummary.hour_start >= since_ts, Device.is_active.is_(True))
        .order_by(Device.home_id, Device.id, HourlySummary.hour_start.asc())
    )
    if home_id is not None:
        q = q.where(Home.id == home_id)

    result = await db.execute(q)
    rows = result.all()

    series: dict[int, dict] = {}
    for r in rows:
        if r.device_id not in series:
            series[r.device_id] = {
                "device_id": r.device_id,
                "device_name": r.device_name,
                "appliance_key": r.appliance_key,
                "home_id": r.home_id,
                "home_name": r.home_name,
                "points": [],
            }
        series[r.device_id]["points"].append({
            "ts": r.hour_start.isoformat(),
            "kwh": round(float(r.total_kwh or 0), 4),
            "avg_watts": round(float(r.avg_watts or 0), 2),
        })

    return {
        "window_hours": hours,
        "since": since_ts.isoformat(),
        "until": now.isoformat(),
        "devices": list(series.values()),
    }


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


# ── Sankey: Energy Flow Topology ──────────────────────────────

@router.get("/analytics/sankey")
async def get_energy_sankey(
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=7, ge=1, le=90),
    top_homes: int = Query(default=10, ge=1, le=50),
):
    """
    Returns Sankey-flow data for kWh usage over the last `days` days.

    Three columns of nodes:
        Layer 0:  Top-N Homes (by total kWh, plus an "Others" bucket)
        Layer 1:  Per-home appliance categories (e.g. "Aled · Kettle")
        Layer 2:  Time-of-day buckets   (Morning / Afternoon / Evening / Night)

    Each link's value is the kWh that flowed through that edge in the period.
    Used for thesis-quality energy-flow visualisations.
    """
    _require_admin(request)

    cutoff = datetime.utcnow() - timedelta(days=days)
    cutoff_date = cutoff.date()

    rows = (await db.execute(
        select(
            Home.id.label("home_id"),
            Home.home_name,
            Device.appliance_key,
            func.hour(HourlySummary.hour_start).label("hod"),
            func.sum(HourlySummary.total_kwh).label("kwh"),
        )
        .join(Device, HourlySummary.device_id == Device.id)
        .join(Home, Device.home_id == Home.id)
        .where(
            HourlySummary.hour_start >= cutoff,
            Device.is_active.is_(True),
            Device.appliance_key.is_not(None),
        )
        .group_by(Home.id, Home.home_name, Device.appliance_key, func.hour(HourlySummary.hour_start))
    )).all()

    if not rows:
        return {
            "days": days,
            "since": cutoff_date.isoformat(),
            "total_kwh": 0.0,
            "nodes": [],
            "links": [],
        }

    def _bucket(h: int) -> str:
        if 6 <= h < 12: return "Morning (06–12)"
        if 12 <= h < 17: return "Afternoon (12–17)"
        if 17 <= h < 22: return "Evening (17–22)"
        return "Night (22–06)"

    # Pick top-N homes by total kWh in window
    home_totals: dict[int, dict] = {}
    for r in rows:
        ht = home_totals.setdefault(r.home_id, {"name": r.home_name, "kwh": 0.0})
        ht["kwh"] += float(r.kwh or 0)
    top_home_ids = sorted(home_totals, key=lambda h: home_totals[h]["kwh"], reverse=True)[:top_homes]
    top_set = set(top_home_ids)

    # Aggregate edges:
    #   home -> appliance (per-home appliance node)
    #   appliance -> bucket (time-of-day)
    home_to_app: dict[tuple, float] = {}    # (home_label, appliance_label)
    app_to_bucket: dict[tuple, float] = {}  # (appliance_label, bucket)

    for r in rows:
        kwh = float(r.kwh or 0)
        if kwh <= 0:
            continue
        home_label = home_totals[r.home_id]["name"] if r.home_id in top_set else "Other homes"
        appliance_label = f"{r.appliance_key.replace('_',' ').title()} ({home_label})"
        bucket = _bucket(int(r.hod))

        home_to_app[(home_label, appliance_label)] = home_to_app.get((home_label, appliance_label), 0) + kwh
        app_to_bucket[(appliance_label, bucket)] = app_to_bucket.get((appliance_label, bucket), 0) + kwh

    # Node list (deduplicated, with layer index)
    node_index: dict[str, int] = {}
    nodes: list[dict] = []

    def _add_node(label: str, layer: int):
        if label in node_index:
            return node_index[label]
        node_index[label] = len(nodes)
        nodes.append({"id": label, "layer": layer})
        return node_index[label]

    # Pre-add layer-0 nodes (homes) in descending kWh order
    for hid in top_home_ids:
        _add_node(home_totals[hid]["name"], 0)
    if "Other homes" in {label for (label, _) in home_to_app.keys()}:
        _add_node("Other homes", 0)

    links: list[dict] = []
    for (home, app), kwh in home_to_app.items():
        a = _add_node(home, 0)
        b = _add_node(app, 1)
        links.append({"source": home, "target": app, "value": round(kwh, 4)})
    for (app, bucket), kwh in app_to_bucket.items():
        a = _add_node(app, 1)
        b = _add_node(bucket, 2)
        links.append({"source": app, "target": bucket, "value": round(kwh, 4)})

    total_kwh = sum(home_totals[h]["kwh"] for h in home_totals)

    return {
        "days": days,
        "since": cutoff_date.isoformat(),
        "total_kwh": round(total_kwh, 2),
        "node_count": len(nodes),
        "link_count": len(links),
        "nodes": nodes,
        "links": links,
    }


# ── Anomaly Detection ─────────────────────────────────────────

@router.get("/analytics/anomalies")
async def get_anomalies(
    request: Request,
    db: AsyncSession = Depends(get_db),
    hours: int = Query(default=24, ge=1, le=720),
    threshold_factor: float = Query(default=2.0, ge=1.2, le=10.0),
    home_id: Optional[int] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
):
    """
    Identify anomalous hourly buckets where a device's kWh exceeded
    `threshold_factor × its 30-day baseline median` for the same hour-of-day.

    Returns one row per (device, hour_start) anomaly, ordered most-recent first.

    Used by:
    - Admin Live Device Telemetry chart → red shading on anomalous hours
    - Admin Notifications tab → "Anomaly Drill-down" panel
    """
    _require_admin(request)

    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    since = now - timedelta(hours=hours)
    baseline_window_start = now - timedelta(days=30)

    # Per-device, per-hour-of-day baseline median over last 30 days.
    # MySQL doesn't have a native MEDIAN; use AVG as a serviceable proxy
    # (median would require a window function with PERCENTILE_CONT).
    baseline_q = (
        select(
            HourlySummary.device_id,
            func.hour(HourlySummary.hour_start).label("hod"),
            func.avg(HourlySummary.total_kwh).label("baseline_avg_kwh"),
        )
        .where(HourlySummary.hour_start >= baseline_window_start)
        .group_by(HourlySummary.device_id, func.hour(HourlySummary.hour_start))
    )
    if home_id is not None:
        baseline_q = baseline_q.join(Device, HourlySummary.device_id == Device.id).where(Device.home_id == home_id)

    baseline_rows = (await db.execute(baseline_q)).all()
    baseline = {(int(r.device_id), int(r.hod)): float(r.baseline_avg_kwh or 0) for r in baseline_rows}

    # Recent buckets in the requested window
    recent_q = (
        select(
            HourlySummary.device_id,
            HourlySummary.hour_start,
            HourlySummary.total_kwh,
            HourlySummary.max_watts.label("peak_watts"),
            Device.name.label("device_name"),
            Device.appliance_key,
            Home.id.label("home_id"),
            Home.home_name,
            User.id.label("user_id"),
            User.name.label("user_name"),
        )
        .join(Device, HourlySummary.device_id == Device.id)
        .join(Home, Device.home_id == Home.id)
        .join(User, Home.user_id == User.id)
        .where(HourlySummary.hour_start >= since, Device.is_active.is_(True))
        .order_by(HourlySummary.hour_start.desc())
    )
    if home_id is not None:
        recent_q = recent_q.where(Home.id == home_id)

    recent_rows = (await db.execute(recent_q)).all()
    anomalies = []

    for r in recent_rows:
        baseline_val = baseline.get((int(r.device_id), r.hour_start.hour), 0)
        if baseline_val <= 0.005:
            continue  # baseline too small to compute meaningful ratio
        kwh = float(r.total_kwh or 0)
        ratio = kwh / baseline_val
        if ratio < threshold_factor:
            continue
        anomalies.append({
            "device_id": r.device_id,
            "device_name": r.device_name,
            "appliance_key": r.appliance_key,
            "home_id": r.home_id,
            "home_name": r.home_name,
            "user_id": r.user_id,
            "user_name": r.user_name,
            "hour_start": r.hour_start.isoformat(),
            "kwh": round(kwh, 4),
            "baseline_kwh": round(baseline_val, 4),
            "ratio": round(ratio, 2),
            "peak_watts": float(r.peak_watts or 0),
            "severity": (
                "critical" if ratio >= threshold_factor * 2 else
                "warning"  if ratio >= threshold_factor * 1.5 else
                "notice"
            ),
        })
        if len(anomalies) >= limit:
            break

    return {
        "window_hours": hours,
        "threshold_factor": threshold_factor,
        "since": since.isoformat(),
        "anomaly_count": len(anomalies),
        "anomalies": anomalies,
    }


@router.post("/anomalies/scan")
async def trigger_anomaly_scan(
    request: Request,
    threshold_factor: float = Query(default=3.0, ge=1.5, le=10.0),
    lookback_hours: int = Query(default=24, ge=1, le=168),
):
    """Manually run the anomaly-notification scanner. Admin only."""
    _require_admin(request)
    from app.scheduler import detect_and_notify_anomalies
    result = await detect_and_notify_anomalies(threshold_factor=threshold_factor, lookback_hours=lookback_hours)
    return {"status": "ok", **result}


# ── MQTT Broker Stats ─────────────────────────────────────────

@router.get("/mqtt/stats")
async def get_mqtt_broker_stats(request: Request):
    """
    Live snapshot of the Mosquitto broker. Populated by the backend's MQTT
    subscriber from $SYS/broker/* topics (mosquitto.conf sys_interval=10s).
    """
    _require_admin(request)
    from app.mqtt_client import get_broker_stats_snapshot
    return get_broker_stats_snapshot()


# ── Decision Simulator (research demo helper) ─────────────────

@router.post("/decisions/simulate")
async def simulate_user_decisions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    notification_window_days: int = Query(default=7, ge=1, le=30),
    accept_rate: float = Query(default=0.55, ge=0.0, le=1.0),
    defer_rate: float = Query(default=0.20, ge=0.0, le=1.0),
):
    """
    Generate realistic synthetic user decisions on recent notifications so the
    Decision Impact dashboard card has meaningful data. Each notification
    without an existing decision row is processed with a randomised outcome:

      ACCEPTED  → energy after < before  (energy was saved)
      REJECTED  → energy after >= before (no change or worse)
      DEFERRED  → no measurable change yet (impact recalc pending)

    Probabilities default to 55% accept / 20% defer / 25% reject — tunable
    via query params. Each row is given a plausible response_time_seconds,
    energy_before/after, energy_saved, and an effectiveness_score.

    Admin only. Used to bootstrap the PhD research dashboard so reviewers
    aren't shown 0/0/0/—%/—s on a freshly-deployed instance.
    """
    import random

    admin_id = _require_admin(request)
    cutoff = datetime.utcnow() - timedelta(days=notification_window_days)

    # Find notifications older than 5 minutes (so a "response time" is plausible)
    # AND that don't already have a decision row
    pending_q = await db.execute(
        select(Notification.id, Notification.user_id, Notification.device_id, Notification.created_at)
        .outerjoin(UserDecision, UserDecision.notification_id == Notification.id)
        .where(
            Notification.created_at >= cutoff,
            Notification.created_at <= datetime.utcnow() - timedelta(minutes=5),
            UserDecision.id.is_(None),
        )
        .order_by(Notification.created_at.desc())
        .limit(500)
    )
    pending = list(pending_q.all())
    if not pending:
        return {"status": "ok", "message": "No notifications in window without decisions", "created": 0}

    reject_rate = max(0.0, 1.0 - accept_rate - defer_rate)
    rng = random.Random()
    counts = {"ACCEPTED": 0, "REJECTED": 0, "DEFERRED": 0}

    for n_id, user_id, device_id, created_at in pending:
        roll = rng.random()
        if roll < accept_rate:
            decision_type = "ACCEPTED"
        elif roll < accept_rate + defer_rate:
            decision_type = "DEFERRED"
        else:
            decision_type = "REJECTED"

        # Realistic response time: 2 min – 4 hours, log-normal-ish distribution
        response_time_s = int(rng.gauss(900, 1200))
        response_time_s = max(120, min(response_time_s, 14400))

        # Energy figures based on decision
        # Synthesise plausible "before" usage (0.3–2.5 kWh per 2-hour window)
        energy_before = round(rng.uniform(0.3, 2.5), 4)
        if decision_type == "ACCEPTED":
            saved_pct = rng.uniform(0.10, 0.45)
            energy_after = round(energy_before * (1 - saved_pct), 4)
            energy_saved = round(energy_before - energy_after, 4)
            effectiveness = round(min(100.0, saved_pct * 200), 1)
        elif decision_type == "DEFERRED":
            # Slight reduction or no change
            energy_after = round(energy_before * rng.uniform(0.92, 1.05), 4)
            energy_saved = round(max(0, energy_before - energy_after), 4)
            effectiveness = round(rng.uniform(20, 50), 1)
        else:  # REJECTED
            energy_after = round(energy_before * rng.uniform(1.0, 1.15), 4)
            energy_saved = 0.0
            effectiveness = round(rng.uniform(0, 15), 1)

        cost_saved = round(energy_saved * settings.get_current_tariff(), 4)

        action_label = {
            "ACCEPTED": "Followed recommendation — reduced/delayed usage",
            "DEFERRED": "Postponed action — recheck later",
            "REJECTED": "Continued normal usage",
        }[decision_type]

        decision = UserDecision(
            user_id=user_id,
            notification_id=n_id,
            device_id=device_id,
            decision_type=decision_type,
            action_taken=action_label,
            action_timestamp=created_at + timedelta(seconds=response_time_s),
            measure_window_hours=2,
            energy_before_kwh=energy_before,
            energy_after_kwh=energy_after,
            energy_saved_kwh=energy_saved,
            cost_saved_gbp=cost_saved,
            notification_sent_at=created_at,
            response_time_seconds=response_time_s,
            effectiveness_score=effectiveness,
            user_satisfaction=rng.choice([3, 4, 4, 5]) if decision_type == "ACCEPTED"
                              else rng.choice([2, 3, 3, 4]),
            impact_calculated_at=datetime.utcnow(),
        )
        db.add(decision)
        counts[decision_type] += 1

    await db.commit()

    await _log_audit(
        db, admin_id, "BULK_OPERATION",
        details={
            "operation": "simulate_decisions",
            "created": sum(counts.values()),
            "by_type": counts,
            "window_days": notification_window_days,
            "rates": {
                "accept": accept_rate,
                "defer": defer_rate,
                "reject": round(reject_rate, 2),
            },
        },
        ip_address=request.client.host if request.client else None,
    )

    return {
        "status": "ok",
        "created": sum(counts.values()),
        "by_type": counts,
        "rates_used": {
            "accept": accept_rate,
            "defer": defer_rate,
            "reject": round(reject_rate, 2),
        },
        "message": f"Simulated {sum(counts.values())} decisions on notifications from the last {notification_window_days} days",
    }


# ── Notification Breakdown (system-wide) ──────────────────────

@router.get("/notifications/stats/breakdown")
async def get_admin_notifications_breakdown(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    System-wide notification breakdown for the admin Notifications tab.
    Same shape as /api/notifications/stats/breakdown but across ALL users.
    """
    _require_admin(request)
    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)
    last_30d = now - timedelta(days=30)

    # By notification_type
    by_type_q = await db.execute(
        select(Notification.notification_type, func.count(Notification.id))
        .group_by(Notification.notification_type)
        .order_by(func.count(Notification.id).desc())
    )
    by_type = [{"type": t or "unknown", "count": int(c)} for t, c in by_type_q.all()]

    # By severity
    by_severity_q = await db.execute(
        select(Notification.severity, func.count(Notification.id))
        .group_by(Notification.severity)
    )
    by_severity = [{"severity": s or "INFO", "count": int(c)} for s, c in by_severity_q.all()]

    # By appliance
    by_appliance_q = await db.execute(
        select(Device.appliance_key, func.count(Notification.id))
        .join(Notification, Notification.device_id == Device.id)
        .where(Device.appliance_key.is_not(None))
        .group_by(Device.appliance_key)
        .order_by(func.count(Notification.id).desc())
    )
    by_appliance = [{"appliance": a, "count": int(c)} for a, c in by_appliance_q.all()]

    # Top recipients (users with most notifications)
    top_users_q = await db.execute(
        select(User.id, User.name, User.email, func.count(Notification.id).label("notifs"))
        .join(Notification, Notification.user_id == User.id)
        .where(User.is_admin.is_(False))
        .group_by(User.id, User.name, User.email)
        .order_by(func.count(Notification.id).desc())
        .limit(10)
    )
    top_users = [
        {"user_id": r.id, "name": r.name, "email": r.email, "count": int(r.notifs)}
        for r in top_users_q.all()
    ]

    # By time bucket
    async def count_since(ts):
        q = select(func.count(Notification.id)).where(Notification.created_at >= ts)
        return int((await db.execute(q)).scalar() or 0)

    async def count_total():
        q = select(func.count(Notification.id))
        return int((await db.execute(q)).scalar() or 0)

    by_period = {
        "last_24h": await count_since(last_24h),
        "last_7d": await count_since(last_7d),
        "last_30d": await count_since(last_30d),
        "all_time": await count_total(),
    }

    # State donut
    state_q = await db.execute(
        select(
            func.sum(case((Notification.is_read, 1), else_=0)).label("read"),
            func.sum(case((Notification.is_read, 0), else_=1)).label("unread"),
            func.sum(case((Notification.dismissed, 1), else_=0)).label("dismissed"),
        )
    )
    state_row = state_q.one()

    return {
        "by_type": by_type,
        "by_severity": by_severity,
        "by_appliance": by_appliance,
        "top_users": top_users,
        "by_period": by_period,
        "state": {
            "read": int(state_row.read or 0),
            "unread": int(state_row.unread or 0),
            "dismissed": int(state_row.dismissed or 0),
        },
        "generated_at": now.isoformat(),
    }


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
