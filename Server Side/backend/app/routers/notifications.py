"""WattWise — Notifications Router."""

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func, update as sql_update, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Notification, UserInteractionLog, Device
from app.schemas import NotificationResponse, NotificationStatsResponse

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


def _get_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


@router.get("/", response_model=list[NotificationResponse])
async def list_notifications(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    filter: Optional[str] = Query(default="all"),
):
    user_id = _get_user_id(request)
    q = select(Notification).where(Notification.user_id == user_id)
    if filter == "unread":
        q = q.where(~Notification.is_read)
    elif filter == "critical":
        q = q.where(Notification.severity == "CRITICAL")
    elif filter == "dismissed":
        q = q.where(Notification.dismissed)
    elif filter == "action_required":
        q = q.where(Notification.requires_user_action, ~Notification.dismissed)
    q = q.order_by(Notification.created_at.desc()).offset((page - 1) * limit).limit(limit)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/stats", response_model=NotificationStatsResponse)
async def get_stats(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    async def count(extra_where=None):
        q = select(func.count(Notification.id)).where(Notification.user_id == user_id)
        if extra_where is not None:
            q = q.where(extra_where)
        r = await db.execute(q)
        return r.scalar() or 0

    total = await count()
    unread = await count(~Notification.is_read)
    critical = await count(Notification.severity == "CRITICAL")
    today_count = await count(Notification.created_at >= today)
    requires_action = await count(
        Notification.requires_user_action & ~Notification.dismissed
    )

    return NotificationStatsResponse(
        total=total, unread=unread, critical=critical,
        today=today_count, requires_action=requires_action
    )


@router.get("/stats/breakdown")
async def get_stats_breakdown(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Detailed breakdown of this user's notifications:
      - by notification_type
      - by severity
      - by appliance (resolved via device_id)
      - by time bucket: last 24h, last 7d, last 30d, all-time
    Ported from old getNotificationStats endpoint with richer dimensions.
    """
    user_id = _get_user_id(request)
    now = datetime.utcnow()
    last_24h = now - timedelta(hours=24)
    last_7d = now - timedelta(days=7)
    last_30d = now - timedelta(days=30)

    # By notification_type
    by_type_q = await db.execute(
        select(Notification.notification_type, func.count(Notification.id))
        .where(Notification.user_id == user_id)
        .group_by(Notification.notification_type)
        .order_by(func.count(Notification.id).desc())
    )
    by_type = [{"type": t or "unknown", "count": int(c)} for t, c in by_type_q.all()]

    # By severity
    by_severity_q = await db.execute(
        select(Notification.severity, func.count(Notification.id))
        .where(Notification.user_id == user_id)
        .group_by(Notification.severity)
    )
    by_severity = [{"severity": s or "INFO", "count": int(c)} for s, c in by_severity_q.all()]

    # By appliance (joined via Device)
    by_appliance_q = await db.execute(
        select(Device.appliance_key, func.count(Notification.id))
        .join(Notification, Notification.device_id == Device.id)
        .where(Notification.user_id == user_id, Device.appliance_key.is_not(None))
        .group_by(Device.appliance_key)
        .order_by(func.count(Notification.id).desc())
    )
    by_appliance = [{"appliance": a, "count": int(c)} for a, c in by_appliance_q.all()]

    # By time bucket
    async def count_since(ts):
        q = select(func.count(Notification.id)).where(
            Notification.user_id == user_id,
            Notification.created_at >= ts,
        )
        return int((await db.execute(q)).scalar() or 0)

    async def count_total():
        q = select(func.count(Notification.id)).where(Notification.user_id == user_id)
        return int((await db.execute(q)).scalar() or 0)

    by_period = {
        "last_24h": await count_since(last_24h),
        "last_7d": await count_since(last_7d),
        "last_30d": await count_since(last_30d),
        "all_time": await count_total(),
    }

    # Read/unread/dismissed split (handy for the bell-badge donut)
    state_q = await db.execute(
        select(
            func.sum(case((Notification.is_read, 1), else_=0)).label("read"),
            func.sum(case((Notification.is_read, 0), else_=1)).label("unread"),
            func.sum(case((Notification.dismissed, 1), else_=0)).label("dismissed"),
        ).where(Notification.user_id == user_id)
    )
    state_row = state_q.one()
    state = {
        "read": int(state_row.read or 0),
        "unread": int(state_row.unread or 0),
        "dismissed": int(state_row.dismissed or 0),
    }

    return {
        "by_type": by_type,
        "by_severity": by_severity,
        "by_appliance": by_appliance,
        "by_period": by_period,
        "state": state,
        "generated_at": now.isoformat(),
    }


@router.patch("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read(notification_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.is_read = True
    notif.read_at = datetime.utcnow()
    await db.commit()
    # Log interaction
    log = UserInteractionLog(user_id=user_id, interaction_type="VIEW_NOTIFICATION", notification_id=notification_id)
    db.add(log)
    await db.commit()
    return notif


@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read_post(
    notification_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    """POST alias for PATCH /{id}/read used by the frontend."""
    return await mark_read(notification_id, request, db)


@router.patch("/read-all", status_code=204)
async def mark_all_read(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    now = datetime.utcnow()
    await db.execute(
        sql_update(Notification)
        .where(Notification.user_id == user_id, ~Notification.is_read)
        .values(is_read=True, read_at=now)
    )
    await db.commit()


@router.patch("/{notification_id}/dismiss", response_model=NotificationResponse)
async def dismiss_notification(notification_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    notif.dismissed = True
    notif.dismissed_at = datetime.utcnow()
    notif.is_read = True
    notif.read_at = datetime.utcnow()
    await db.commit()
    return notif


@router.delete("/{notification_id}", status_code=204)
async def delete_notification(notification_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    notif = result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    await db.delete(notif)
    await db.commit()
