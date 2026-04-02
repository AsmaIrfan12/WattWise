"""WattWise — User Decisions Router (Research Core)."""

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import UserDecision, Notification, UserInteractionLog
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
