"""
WattWise — client interaction events.

The dashboard (and the Android shell around it) report what the user looked at, so
engagement can be analysed alongside decisions. Server-side events (LOGIN,
VIEW_NOTIFICATION on open, RECORD_DECISION, SET_GOAL…) are logged where they happen;
this endpoint is only for things the server cannot see.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Device, Home, Notification, UserInteractionLog
from app.schemas import InteractionCreate

router = APIRouter(prefix="/api/interactions", tags=["Interactions"])


@router.post("/", status_code=201)
async def record_interaction(body: InteractionCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    # References are kept only when they are the caller's own; otherwise dropped silently
    # (an analytics beacon should never fail the page).
    device_id = None
    if body.device_id is not None:
        device_id = (await db.execute(
            select(Device.id).join(Home, Home.id == Device.home_id)
            .where(Device.id == body.device_id, Home.user_id == user_id)
        )).scalar_one_or_none()
    notification_id = None
    if body.notification_id is not None:
        notification_id = (await db.execute(
            select(Notification.id).where(Notification.id == body.notification_id, Notification.user_id == user_id)
        )).scalar_one_or_none()

    db.add(UserInteractionLog(
        user_id=user_id,
        interaction_type=body.interaction_type,
        screen_name=body.screen_name,
        device_id=device_id,
        notification_id=notification_id,
        session_id=body.session_id,
        metadata_json=body.metadata,
    ))
    await db.commit()
    return {"recorded": True}
