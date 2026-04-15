"""
WattWise Persona Classifier
=============================
Automatically classifies users into energy behaviour personas
based on their efficiency scores, goal adherence, and decision responses.

Personas:
  1. Eco Champion    — Top performers: high efficiency, high adherence
  2. Active Improver — Improving trend, moderate adherence
  3. Steady User     — Consistent average-range usage
  4. High Consumer   — Above-average consumption, declining efficiency
  5. Disengaged      — Low interaction, poor adherence or no data

Called weekly by scheduler (Sunday 02:00 UTC).
Admin can override persona classification manually via the admin API.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Home, HomeDailyTotal, EnergyRanking, UserDecision, Persona

logger = logging.getLogger("persona_classifier")

# ── Persona definitions (seeded to DB on first run) ───────────
DEFAULT_PERSONAS = [
    {
        "name": "Eco Champion",
        "description": "Top performers with high efficiency scores and excellent goal adherence. These users consistently use energy wisely.",
        "criteria": {"min_efficiency": 75, "min_adherence": 80, "min_decision_rate": 60},
    },
    {
        "name": "Active Improver",
        "description": "Users showing a positive energy reduction trend. Engaged with the platform and working to improve their efficiency.",
        "criteria": {"min_efficiency": 55, "min_adherence": 50, "min_decision_rate": 40, "improving_trend": True},
    },
    {
        "name": "Steady User",
        "description": "Consistent users with average community performance. Neither high nor low consumers.",
        "criteria": {"min_efficiency": 40, "max_efficiency": 74, "min_adherence": 30, "max_adherence": 79},
    },
    {
        "name": "High Consumer",
        "description": "Users with above-average energy consumption. May benefit from targeted interventions and personalised recommendations.",
        "criteria": {"max_efficiency": 40, "max_adherence": 30},
    },
    {
        "name": "Disengaged",
        "description": "Users with minimal platform interaction, very low goal adherence, or no recent data. May need re-engagement outreach.",
        "criteria": {"max_decision_rate": 10, "max_adherence": 10},
    },
]


# ── Persona Seeder ─────────────────────────────────────────────

async def seed_default_personas(db: AsyncSession) -> None:
    """Insert default personas if they don't exist yet."""
    for pdef in DEFAULT_PERSONAS:
        existing = await db.execute(select(Persona).where(Persona.name == pdef["name"]))
        if not existing.scalar_one_or_none():
            persona = Persona(
                name=pdef["name"],
                description=pdef["description"],
                criteria=pdef["criteria"],
            )
            db.add(persona)
    await db.commit()
    logger.info("Default personas seeded")


# ── Classification Engine ──────────────────────────────────────

async def classify_all_users(db: AsyncSession) -> dict:
    """
    Classify all non-admin users into personas based on 30-day history.
    Returns a summary: {persona_name: count}.
    """
    logger.info("Starting persona classification run...")

    # Load all personas
    personas_result = await db.execute(select(Persona))
    personas = {p.name: p for p in personas_result.scalars().all()}

    if not personas:
        logger.warning("No personas found — seed first")
        return {}

    # Load all non-admin users who haven't been manually locked
    users_result = await db.execute(
        select(User).where(User.is_admin == False)
    )
    users = users_result.scalars().all()

    summary: dict[str, int] = {}
    cutoff = (datetime.utcnow() - timedelta(days=30)).date()

    for user in users:
        try:
            persona_name = await _classify_user(db, user, cutoff)
            persona = personas.get(persona_name)
            if persona and user.persona_id != persona.id:
                user.persona_id = persona.id
                summary[persona_name] = summary.get(persona_name, 0) + 1
        except Exception as e:
            logger.error("Persona classification failed for user %s: %s", user.id, e)

    await db.commit()
    logger.info("Persona classification complete: %s", summary)
    return summary


async def _classify_user(db: AsyncSession, user: User, since_date) -> str:
    """Compute metrics for a user and return their persona name."""

    # 1. Get recent ranking data (30-day average)
    ranking_result = await db.execute(
        select(
            func.avg(EnergyRanking.efficiency_score).label("avg_eff"),
            func.avg(EnergyRanking.goal_adherence_score).label("avg_adherence"),
            func.avg(EnergyRanking.decision_response_score).label("avg_decision"),
            func.count(EnergyRanking.id).label("ranking_days"),
        )
        .where(
            EnergyRanking.user_id == user.id,
            EnergyRanking.period_start >= since_date,
        )
    )
    row = ranking_result.one()

    avg_eff = float(row.avg_eff or 50.0)
    avg_adherence = float(row.avg_adherence or 50.0)
    avg_decision = float(row.avg_decision or 50.0)
    ranking_days = int(row.ranking_days or 0)

    # 2. Check if user has any decisions recorded
    decision_result = await db.execute(
        select(func.count(UserDecision.id)).where(
            UserDecision.user_id == user.id,
            UserDecision.created_at >= datetime.utcnow() - timedelta(days=30),
        )
    )
    decision_count = int(decision_result.scalar() or 0)

    # 3. Check improving trend (compare last 7 days vs previous 7 days)
    trend_improving = await _check_improving_trend(db, user.id)

    # 4. Apply classification rules (ordered by priority)
    if ranking_days < 3:
        return "Disengaged"  # Not enough data

    if avg_decision <= 10 and avg_adherence <= 10:
        return "Disengaged"

    if avg_eff >= 75 and avg_adherence >= 80:
        return "Eco Champion"

    if trend_improving and avg_eff >= 55 and avg_adherence >= 50:
        return "Active Improver"

    if avg_eff <= 40 and avg_adherence <= 30:
        return "High Consumer"

    # Default: Steady User
    return "Steady User"


async def _check_improving_trend(db: AsyncSession, user_id: int) -> bool:
    """True if average efficiency improved from week 2→1 (last 14 days)."""
    now = datetime.utcnow().date()
    week1_start = now - timedelta(days=7)
    week2_start = now - timedelta(days=14)

    async def avg_eff(start, end):
        result = await db.execute(
            select(func.avg(EnergyRanking.efficiency_score))
            .where(
                EnergyRanking.user_id == user_id,
                EnergyRanking.period_start >= start,
                EnergyRanking.period_start < end,
            )
        )
        return float(result.scalar() or 0)

    week1_avg = await avg_eff(week1_start, now)
    week2_avg = await avg_eff(week2_start, week1_start)

    return week1_avg > week2_avg + 2.0  # At least 2% improvement to count
