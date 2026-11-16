"""WattWise — User Decisions Router (Research Core)."""

import hmac
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query, Header
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import (
    UserDecision, Notification, UserInteractionLog,
    DecisionObservedAction, Device, Home,
)
from app.schemas import DecisionCreate, DecisionUpdate, DecisionResponse, DecisionImpactReport
from app.decision_tracker import DecisionTracker, DEFAULT_REMIND_MINUTES

router = APIRouter(prefix="/api/decisions", tags=["User Decisions"])


def _get_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


async def _owned_device_id(db: AsyncSession, device_id: Optional[int], user_id: int) -> Optional[int]:
    """Return device_id if it belongs to one of the user's homes, else raise 404."""
    if device_id is None:
        return None
    owned = (await db.execute(
        select(Device.id).join(Home, Home.id == Device.home_id)
        .where(Device.id == device_id, Home.user_id == user_id)
    )).scalar_one_or_none()
    if owned is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return owned


async def _with_context(db: AsyncSession, decisions: list[UserDecision]) -> list[DecisionResponse]:
    """Add the alert title/type and device name so a decision can be shown on its own."""
    notif_ids = {d.notification_id for d in decisions if d.notification_id}
    device_ids = {d.device_id for d in decisions if d.device_id}
    notifs, devices = {}, {}
    if notif_ids:
        notifs = {n.id: n for n in (await db.execute(
            select(Notification).where(Notification.id.in_(notif_ids))
        )).scalars().all()}
    if device_ids:
        devices = {dv.id: dv for dv in (await db.execute(
            select(Device).where(Device.id.in_(device_ids))
        )).scalars().all()}
    out = []
    for d in decisions:
        resp = DecisionResponse.model_validate(d, from_attributes=True)
        n = notifs.get(d.notification_id)
        if n:
            resp.notification_title = n.title
            resp.notification_type = n.notification_type
        dv = devices.get(d.device_id)
        if dv:
            resp.device_name = dv.name
        out.append(resp)
    return out


@router.post("/", response_model=DecisionResponse, status_code=201)
async def record_decision(body: DecisionCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Record a user's decision/action taken after receiving an energy notification."""
    user_id = _get_user_id(request)

    # Verify notification belongs to user
    notif_result = await db.execute(
        select(Notification).where(Notification.id == body.notification_id, Notification.user_id == user_id)
    )
    notif = notif_result.scalar_one_or_none()
    if not notif:
        raise HTTPException(status_code=404, detail="Notification not found")
    # The dashboard/app buttons send only {notification_id, decision_type}; without a
    # device the tracker cannot measure energy_before/after, so inherit the device
    # the notification was about. A device sent by the client must be the user's own.
    device_id = await _owned_device_id(db, body.device_id, user_id) or notif.device_id

    # Check no duplicate decision for same notification
    existing = await db.execute(
        select(UserDecision).where(
            UserDecision.user_id == user_id,
            UserDecision.notification_id == body.notification_id
        ).limit(1)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=409,
            detail="Decision already recorded for this notification — use PATCH /api/decisions/{id} to change it",
        )

    try:
        decision = await DecisionTracker.record_decision(
            db=db,
            user_id=user_id,
            notification_id=body.notification_id,
            decision_type=body.decision_type,
            action_taken=body.action_taken,
            device_id=device_id,
            user_feedback_text=body.user_feedback_text,
            user_satisfaction=body.user_satisfaction,
            remind_in_minutes=body.remind_in_minutes,
        )
    except IntegrityError:
        # Two taps raced past the check above; the unique key kept exactly one row.
        await db.rollback()
        raise HTTPException(status_code=409, detail="Decision already recorded for this notification")

    # Responding to an alert implies it was opened and read.
    now = datetime.utcnow()
    if notif.opened_at is None:
        notif.opened_at = now
    if not notif.is_read:
        notif.is_read = True
        notif.read_at = now

    db.add(UserInteractionLog(
        user_id=user_id,
        interaction_type="RECORD_DECISION",
        notification_id=body.notification_id,
        device_id=device_id,
        metadata_json={"decision_type": body.decision_type, "has_action": bool(body.action_taken)},
    ))
    await db.commit()

    return (await _with_context(db, [decision]))[0]


@router.patch("/{decision_id}", response_model=DecisionResponse)
async def update_decision(
    decision_id: int, body: DecisionUpdate, request: Request, db: AsyncSession = Depends(get_db)
):
    """
    Change a decision: complete a deferred alert ("Later" → "Done"), correct a
    choice, or add what was done / feedback / a rating afterwards.

    Moving to ACCEPTED or CUSTOM_ACTION means the user has acted *now*, so the
    before/after energy window restarts at this moment.
    """
    user_id = _get_user_id(request)
    decision = (await db.execute(
        select(UserDecision).where(UserDecision.id == decision_id, UserDecision.user_id == user_id)
    )).scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")
    if decision.is_simulated:
        raise HTTPException(status_code=409, detail="Simulated decisions cannot be edited")

    changed: dict = {}
    previous_type = decision.decision_type
    if body.decision_type and body.decision_type != previous_type:
        decision.decision_type = body.decision_type
        changed["decision_type"] = {"from": previous_type, "to": body.decision_type}
        if body.decision_type in ("ACCEPTED", "CUSTOM_ACTION"):
            await DecisionTracker.restart_measurement(db, decision)
        if body.decision_type != "DEFERRED":
            decision.remind_at = None
    if body.action_taken is not None:
        decision.action_taken = body.action_taken
        changed["action_taken"] = True
    if body.user_feedback_text is not None:
        decision.user_feedback_text = body.user_feedback_text
        changed["feedback"] = True
    if body.user_satisfaction is not None:
        decision.user_satisfaction = body.user_satisfaction
        changed["satisfaction"] = body.user_satisfaction
    if decision.decision_type == "DEFERRED" and (body.remind_in_minutes or "decision_type" in changed):
        decision.remind_at = datetime.utcnow() + timedelta(minutes=body.remind_in_minutes or DEFAULT_REMIND_MINUTES)
        decision.reminded_at = None
        changed["remind_at"] = decision.remind_at.isoformat()

    if not changed:
        raise HTTPException(status_code=422, detail="Nothing to update")

    decision.updated_at = datetime.utcnow()
    db.add(UserInteractionLog(
        user_id=user_id,
        interaction_type="RECORD_DECISION",
        notification_id=decision.notification_id,
        device_id=decision.device_id,
        metadata_json={"update": True, **changed},
    ))
    await db.commit()
    await db.refresh(decision)
    return (await _with_context(db, [decision]))[0]


@router.get("/", response_model=list[DecisionResponse])
async def list_decisions(
    request: Request,
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
):
    """The user's own decisions (simulated demo rows are never shown to users)."""
    user_id = _get_user_id(request)
    result = await db.execute(
        select(UserDecision)
        .where(UserDecision.user_id == user_id, UserDecision.is_simulated.is_(False))
        .order_by(UserDecision.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return await _with_context(db, list(result.scalars().all()))


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

    # Resolve the device strictly inside the notified user's own homes — a report
    # may never attach another household's device to this user's decision.
    owned = select(Device.id).join(Home, Home.id == Device.home_id).where(Home.user_id == user_id)
    device_id = None
    if body.device_id is not None:
        device_id = (await db.execute(owned.where(Device.id == body.device_id))).scalar_one_or_none()
    elif body.entity_id:
        device_id = (await db.execute(
            owned.where(Device.entity_id == body.entity_id, Device.is_active).order_by(Device.id).limit(1)
        )).scalar_one_or_none()
    if (body.device_id is not None or body.entity_id) and device_id is None:
        raise HTTPException(status_code=404, detail="Device not found for this notification's user")

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
            device_id=device_id or notif.device_id,
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
    return (await _with_context(db, [decision]))[0]
