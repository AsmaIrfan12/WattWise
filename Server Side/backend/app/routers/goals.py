"""WattWise — Energy Goals Router."""


from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import EnergyGoal, DailySummary, HomeDailyTotal, Home, UserInteractionLog
from app.schemas import GoalCreate, GoalResponse, GoalProgressResponse
from app.energy_analysis import EnergyAnalysisEngine

router = APIRouter(prefix="/api/goals", tags=["Energy Goals"])


def _get_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


@router.post("/", response_model=GoalResponse, status_code=201)
async def create_goal(body: GoalCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    goal = EnergyGoal(user_id=user_id, **body.model_dump())
    db.add(goal)
    log = UserInteractionLog(user_id=user_id, interaction_type="SET_GOAL")
    db.add(log)
    await db.commit()
    await db.refresh(goal)
    return goal


@router.get("/", response_model=list[GoalResponse])
async def list_goals(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(EnergyGoal).where(EnergyGoal.user_id == user_id, EnergyGoal.is_active == True)
    )
    return result.scalars().all()


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(goal_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(EnergyGoal).where(EnergyGoal.id == goal_id, EnergyGoal.user_id == user_id)
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


@router.get("/{goal_id}/progress", response_model=GoalProgressResponse)
async def get_goal_progress(goal_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(EnergyGoal).where(EnergyGoal.id == goal_id, EnergyGoal.user_id == user_id)
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    # Calculate current consumption since goal start
    from datetime import date
    today = date.today()

    if goal.device_id:
        # Per-device goal
        cost_result = await db.execute(
            select(func.sum(DailySummary.total_kwh), func.sum(DailySummary.estimated_cost_gbp))
            .where(
                DailySummary.device_id == goal.device_id,
                DailySummary.day_date >= goal.start_date,
                DailySummary.day_date <= today,
            )
        )
    else:
        # Whole-home goal — use home daily totals
        homes_result = await db.execute(select(Home).where(Home.user_id == user_id, Home.is_active == True))
        home_ids = [h.id for h in homes_result.scalars().all()]
        cost_result = await db.execute(
            select(func.sum(HomeDailyTotal.total_kwh), func.sum(HomeDailyTotal.total_cost_gbp))
            .where(
                HomeDailyTotal.home_id.in_(home_ids),
                HomeDailyTotal.day_date >= goal.start_date,
                HomeDailyTotal.day_date <= today,
            )
        )

    row = cost_result.one()
    current_kwh = float(row[0] or 0)
    current_cost = float(row[1] or 0)

    target_kwh = goal.target_kwh or 0
    progress = EnergyAnalysisEngine.evaluate_goal_progress(
        goal_type=goal.goal_type,
        target_kwh=target_kwh,
        current_kwh=current_kwh,
        start_date=goal.start_date,
        end_date=goal.end_date,
        today=today,
    )
    days_remaining = progress.get("days_remaining")

    return GoalProgressResponse(
        goal=goal,
        current_kwh=current_kwh,
        current_cost_gbp=current_cost,
        percentage_used=progress["percentage_used"],
        days_remaining=days_remaining,
        on_track=progress["on_track"],
        projected_kwh=progress.get("projected_kwh"),
    )


_ALLOWED_GOAL_FIELDS = {"device_id", "goal_type", "target_kwh", "target_cost_gbp", "start_date", "end_date"}


@router.patch("/{goal_id}", response_model=GoalResponse)
async def update_goal(goal_id: int, body: GoalCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(EnergyGoal).where(EnergyGoal.id == goal_id, EnergyGoal.user_id == user_id)
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k in _ALLOWED_GOAL_FIELDS:
            setattr(goal, k, v)
    log = UserInteractionLog(user_id=user_id, interaction_type="UPDATE_GOAL")
    db.add(log)
    await db.commit()
    await db.refresh(goal)
    return goal


@router.delete("/{goal_id}", status_code=204)
async def deactivate_goal(goal_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(EnergyGoal).where(EnergyGoal.id == goal_id, EnergyGoal.user_id == user_id)
    )
    goal = result.scalar_one_or_none()
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal.is_active = False
    await db.commit()
