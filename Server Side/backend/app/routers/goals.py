"""WattWise — Energy Goals Router."""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Query
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


@router.get("/streak/summary")
async def get_goal_streak(
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
):
    """
    Streak + progress summary for the user's active daily home-level goal.

    Returns:
      - active_streak: consecutive days under goal (most-recent-first count)
      - longest_streak: longest run in the window
      - days_under / days_over / days_no_data
      - history: per-day [{date, kwh, target_kwh, met, pct_of_target}]
      - rolling_avg_kwh: 7-day rolling avg of kwh
    """
    user_id = _get_user_id(request)
    today = date.today()
    since = today - timedelta(days=days - 1)

    # Active daily goal (home-wide, no device)
    goal_q = await db.execute(
        select(EnergyGoal).where(
            EnergyGoal.user_id == user_id,
            EnergyGoal.is_active.is_(True),
            EnergyGoal.goal_type == "daily",
            EnergyGoal.device_id.is_(None),
        ).limit(1)
    )
    goal = goal_q.scalar_one_or_none()
    target_kwh = float(goal.target_kwh) if goal else None

    # Pull total daily kWh per day across the user's homes
    home_ids_q = await db.execute(
        select(Home.id).where(Home.user_id == user_id, Home.is_active.is_(True))
    )
    home_ids = [hid for (hid,) in home_ids_q.all()]
    if not home_ids:
        return {
            "has_active_goal": goal is not None,
            "target_kwh": target_kwh,
            "window_days": days,
            "history": [],
            "active_streak": 0,
            "longest_streak": 0,
            "days_under": 0,
            "days_over": 0,
            "days_no_data": days,
            "rolling_avg_kwh": 0.0,
        }

    daily_q = await db.execute(
        select(
            HomeDailyTotal.day_date,
            func.sum(HomeDailyTotal.total_kwh).label("kwh"),
        )
        .where(
            HomeDailyTotal.home_id.in_(home_ids),
            HomeDailyTotal.day_date >= since,
            HomeDailyTotal.day_date <= today,
        )
        .group_by(HomeDailyTotal.day_date)
    )
    by_day = {r.day_date: float(r.kwh or 0) for r in daily_q.all()}

    history = []
    days_under = 0
    days_over = 0
    days_no_data = 0
    cur_date = since
    while cur_date <= today:
        kwh = by_day.get(cur_date)
        if kwh is None:
            history.append({
                "date": cur_date.isoformat(),
                "kwh": None,
                "target_kwh": target_kwh,
                "met": None,
                "pct_of_target": None,
            })
            days_no_data += 1
        else:
            met = (target_kwh is not None and kwh <= target_kwh)
            pct = (kwh / target_kwh * 100) if target_kwh and target_kwh > 0 else None
            history.append({
                "date": cur_date.isoformat(),
                "kwh": round(kwh, 3),
                "target_kwh": target_kwh,
                "met": met,
                "pct_of_target": round(pct, 1) if pct is not None else None,
            })
            if met:
                days_under += 1
            elif target_kwh is not None:
                days_over += 1
        cur_date += timedelta(days=1)

    # Active streak: walk backwards from today while goal was met
    active_streak = 0
    if target_kwh is not None:
        for entry in reversed(history):
            if entry["met"] is True:
                active_streak += 1
            else:
                break

    # Longest streak in window
    longest_streak = 0
    run = 0
    for entry in history:
        if entry["met"] is True:
            run += 1
            longest_streak = max(longest_streak, run)
        else:
            run = 0

    # 7-day rolling average
    recent = [e["kwh"] for e in history[-7:] if e["kwh"] is not None]
    rolling_avg_kwh = sum(recent) / len(recent) if recent else 0.0

    return {
        "has_active_goal": goal is not None,
        "target_kwh": target_kwh,
        "window_days": days,
        "active_streak": active_streak,
        "longest_streak": longest_streak,
        "days_under": days_under,
        "days_over": days_over,
        "days_no_data": days_no_data,
        "rolling_avg_kwh": round(rolling_avg_kwh, 3),
        "history": history,
    }
