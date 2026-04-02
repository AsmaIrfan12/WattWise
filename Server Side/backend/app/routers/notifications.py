"""WattWise — Notifications Router."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select, func, update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Notification, UserInteractionLog
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
        q = q.where(Notification.is_read == False)
    elif filter == "critical":
        q = q.where(Notification.severity == "CRITICAL")
    elif filter == "dismissed":
        q = q.where(Notification.dismissed == True)
    elif filter == "action_required":
        q = q.where(Notification.requires_user_action == True, Notification.dismissed == False)
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
    unread = await count(Notification.is_read == False)
    critical = await count(Notification.severity == "CRITICAL")
    today_count = await count(Notification.created_at >= today)
    requires_action = await count(
        (Notification.requires_user_action == True) & (Notification.dismissed == False)
    )

    return NotificationStatsResponse(
        total=total, unread=unread, critical=critical,
        today=today_count, requires_action=requires_action
    )


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


@router.patch("/read-all", status_code=204)
async def mark_all_read(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    now = datetime.utcnow()
    await db.execute(
        sql_update(Notification)
        .where(Notification.user_id == user_id, Notification.is_read == False)
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
