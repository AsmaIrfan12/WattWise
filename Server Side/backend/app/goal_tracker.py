"""
WattWise — Energy goal evaluation
=================================
Shared by the goals API (progress endpoint) and the hourly goal-check job so
that what the user sees and what triggers an alert are the same numbers.

A goal row (energy_goals) is a *recurring* target: a weekly goal that started
on 5 Nov covers 5–11 Nov, then 12–18 Nov, and so on, until end_date (if set)
or until the goal is deactivated. Consumption is measured from daily_summary
(per-device goals) or home_daily_totals (whole-home goals).
"""
import calendar
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EnergyGoal, DailySummary, HomeDailyTotal, Home


def period_bounds(goal_type: str, start_date: date, today: date) -> tuple[date, date]:
    """
    Return (period_start, period_end) of the goal period that contains `today`.

    daily    → today only
    weekly   → the 7-day window, aligned to start_date, that contains today
    monthly  → the calendar month containing today (first period starts on start_date)
    per_device / anything else → cumulative from start_date to today
    """
    if today < start_date:
        today = start_date
    if goal_type == "daily":
        return today, today
    if goal_type == "weekly":
        offset = (today - start_date).days % 7
        period_start = today - timedelta(days=offset)
        return period_start, period_start + timedelta(days=6)
    if goal_type == "monthly":
        first = date(today.year, today.month, 1)
        last = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
        return max(first, start_date), last
    return start_date, today


def previous_period_bounds(goal_type: str, start_date: date, today: date) -> Optional[tuple[date, date]]:
    """Bounds of the period immediately before the one containing `today`, or None if there is none."""
    cur_start, _ = period_bounds(goal_type, start_date, today)
    if cur_start <= start_date:
        return None
    prev_end = cur_start - timedelta(days=1)
    return period_bounds(goal_type, start_date, prev_end)


async def consumption_between(
    db: AsyncSession, goal: EnergyGoal, start: date, end: date
) -> tuple[float, float]:
    """(kWh, £) consumed by the goal's device — or all the user's homes — between two dates inclusive."""
    if goal.device_id:
        row = (await db.execute(
            select(func.sum(DailySummary.total_kwh), func.sum(DailySummary.estimated_cost_gbp)).where(
                DailySummary.device_id == goal.device_id,
                DailySummary.day_date >= start,
                DailySummary.day_date <= end,
            )
        )).one()
    else:
        home_ids = [
            h.id for h in (await db.execute(
                select(Home).where(Home.user_id == goal.user_id, Home.is_active.is_(True))
            )).scalars().all()
        ]
        if not home_ids:
            return 0.0, 0.0
        row = (await db.execute(
            select(func.sum(HomeDailyTotal.total_kwh), func.sum(HomeDailyTotal.total_cost_gbp)).where(
                HomeDailyTotal.home_id.in_(home_ids),
                HomeDailyTotal.day_date >= start,
                HomeDailyTotal.day_date <= end,
            )
        )).one()
    return float(row[0] or 0), float(row[1] or 0)


async def evaluate_goal(db: AsyncSession, goal: EnergyGoal, today: Optional[date] = None) -> dict:
    """
    Progress of `goal` in its current period.

    Returns: period_start, period_end, days_remaining, current_kwh, current_cost_gbp,
    target_kwh, percentage_used, projected_kwh, on_track.
    """
    today = today or date.today()
    period_start, period_end = period_bounds(goal.goal_type, goal.start_date, today)
    if goal.end_date and period_end > goal.end_date:
        period_end = goal.end_date
    current_kwh, current_cost = await consumption_between(db, goal, period_start, period_end)

    target_kwh = float(goal.target_kwh or 0)
    pct = (current_kwh / target_kwh * 100) if target_kwh > 0 else 0.0
    days_remaining = max((period_end - today).days, 0)
    days_elapsed = (today - period_start).days + 1
    projected = None
    if goal.goal_type in ("weekly", "monthly") and days_elapsed > 0:
        projected = current_kwh + (current_kwh / days_elapsed) * days_remaining
    on_track = pct <= 100 and (projected is None or target_kwh <= 0 or projected <= target_kwh)

    return {
        "period_start": period_start,
        "period_end": period_end,
        "days_remaining": days_remaining,
        "current_kwh": round(current_kwh, 3),
        "current_cost_gbp": round(current_cost, 2),
        "target_kwh": target_kwh,
        "percentage_used": round(pct, 1),
        "projected_kwh": round(projected, 3) if projected is not None else None,
        "on_track": on_track,
    }
