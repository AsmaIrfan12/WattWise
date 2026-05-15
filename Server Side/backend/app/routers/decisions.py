"""WattWise — User Decisions Router (Research Core)."""

import hmac
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import (
    UserDecision, Notification, UserInteractionLog,
    DecisionObservedAction, Device,
)
from app.schemas import DecisionCreate, DecisionResponse, DecisionImpactReport
from app.decision_tracker import DecisionTracker

router = APIRouter(prefix="/api/decisions", tags=["User Decisions"])


def _get_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


@router.post("/", response_model=DecisionResponse, status_code=201)
async def record_decision(body: DecisionCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Record a user's decision/action taken after receiving an energy notification."""
    user_id = _get_user_id(request)

    # Verify notification belongs to user
    notif_result = await db.execute(
        select(Notification).where(Notification.id == body.notification_id, Notification.user_id == user_id)
    )
    if not notif_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Notification not found")

    # Check no duplicate decision for same notification
    existing = await db.execute(
        select(UserDecision).where(
            UserDecision.user_id == user_id,
            UserDecision.notification_id == body.notification_id
        ).limit(1)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Decision already recorded for this notification")

    decision = await DecisionTracker.record_decision(
        db=db,
        user_id=user_id,
        notification_id=body.notification_id,
        decision_type=body.decision_type,
        action_taken=body.action_taken,
        device_id=body.device_id,
        user_feedback_text=body.user_feedback_text,
        user_satisfaction=body.user_satisfaction,
    )

    # Log interaction
    log = UserInteractionLog(
        user_id=user_id,
        interaction_type="RECORD_DECISION",
        notification_id=body.notification_id,
        device_id=body.device_id,
        metadata_json={"decision_type": body.decision_type},
    )
    db.add(log)
    await db.commit()

    return decision


@router.get("/", response_model=list[DecisionResponse])
async def list_decisions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(UserDecision)
        .where(UserDecision.user_id == user_id)
        .order_by(UserDecision.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/impact-report", response_model=DecisionImpactReport)
async def get_impact_report(request: Request, db: AsyncSession = Depends(get_db)):
    """Aggregate energy impact statistics for the authenticated user."""
    user_id = _get_user_id(request)
    report = await DecisionTracker.get_user_impact_report(db, user_id)
    return DecisionImpactReport(**report)


class ObservedActionIn(BaseModel):
    notification_id: int
    observed_state: str                       # e.g. "off" / "on"
    previous_state: Optional[str] = None
    entity_id: Optional[str] = None
    device_id: Optional[int] = None
    source: str = "rpi_homeassistant"          # or "admin_manual"
    observed_at: Optional[datetime] = None
    raw_payload: Optional[dict] = None


@router.post("/observed-action", status_code=201)
async def record_observed_action(
    body: ObservedActionIn,
    x_wattwise_rpi_key: str = Header(default=""),
    db: AsyncSession = Depends(get_db),
):
    """
    Closed-loop endpoint: the RPi / Home Assistant bridge (or an admin tool)
    reports the *verified* device actuation taken in response to a notification.

    Auth is a shared secret header (the RPi has no JWT). This path is in
    PUBLIC_PATHS so the JWT middleware doesn't reject it; the secret check
    below is the actual gate. On a "save" action with no decision yet
    recorded, a verified UserDecision is auto-created so the existing
    impact pipeline attributes savings to a real physical action.
    """
    if not hmac.compare_digest(x_wattwise_rpi_key, settings.RPI_WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Invalid webhook key")
    if body.source not in ("rpi_homeassistant", "admin_manual"):
        raise HTTPException(status_code=422, detail="Invalid source")

    notif = (await db.execute(
        select(Notification).where(Notification.id == body.notification_id)
    )).scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    user_id = notif.user_id

    # Resolve device — by id (ownership-checked) or by entity_id within the user's homes.
    device_id = None
    if body.device_id is not None:
        dev = (await db.execute(
            select(Device).where(Device.id == body.device_id)
        )).scalar_one_or_none()
        if dev:
            device_id = dev.id
    elif body.entity_id:
        dev = (await db.execute(
            select(Device).where(
                Device.entity_id == body.entity_id, Device.is_active
            )
        )).scalar_one_or_none()
        if dev:
            device_id = dev.id

    # Link to an existing decision for this notification, if any.
    decision = (await db.execute(
        select(UserDecision).where(
            UserDecision.user_id == user_id,
            UserDecision.notification_id == body.notification_id,
        ).limit(1)
    )).scalar_one_or_none()

    # No self-report yet + the prompted save action happened → auto-close
    # the loop with a verified decision so impact gets measured.
    if decision is None and body.observed_state.lower() in ("off", "standby", "unplugged"):
        decision = await DecisionTracker.record_decision(
            db=db,
            user_id=user_id,
            notification_id=body.notification_id,
            decision_type="ACCEPTED",
            action_taken=f"verified:{body.source} switch->{body.observed_state}",
            device_id=device_id,
        )

    obs = DecisionObservedAction(
        notification_id=body.notification_id,
        decision_id=decision.id if decision else None,
        user_id=user_id,
        device_id=device_id,
        entity_id=body.entity_id,
        source=body.source,
        observed_state=body.observed_state,
        previous_state=body.previous_state,
        observed_at=body.observed_at or datetime.utcnow(),
        raw_payload=body.raw_payload,
    )
    db.add(obs)
    db.add(UserInteractionLog(
        user_id=user_id,
        interaction_type="RECORD_DECISION",
        notification_id=body.notification_id,
        device_id=device_id,
        metadata_json={
            "verified_action": True,
            "source": body.source,
            "observed_state": body.observed_state,
        },
    ))
    await db.commit()
    await db.refresh(obs)

    return {
        "observed_action_id": obs.id,
        "decision_id": decision.id if decision else None,
        "verified": True,
        "auto_closed": decision is not None,
    }


@router.get("/{decision_id}", response_model=DecisionResponse)
async def get_decision(decision_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(UserDecision).where(UserDecision.id == decision_id, UserDecision.user_id == user_id)
    )
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    return decision
