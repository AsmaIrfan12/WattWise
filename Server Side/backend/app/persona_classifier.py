"""
WattWise Persona Classifier
============================
Differentiates each home (one home per user) into one of five behavioural
personas based on energy usage relative to the rest of the community.

Personas:
  1. Eco Champion    — top-quintile combined performer
  2. Active Improver — above-median performer with an improving trend
  3. Steady User     — mid-range community member
  4. High Consumer   — bottom-quintile performer (most consumption per occupant)
  5. Disengaged      — insufficient data or no recent platform interaction

Strategy
--------
Each user's "combined score" is a weighted blend of:
  - efficiency_score       (50%)  — kWh/occupant signal from EnergyRanking
  - goal_adherence_score   (30%)  — goal_kwh / actual_kwh
  - decision_response_score(20%)  — average effectiveness of accepted decisions

The score is averaged over the most recent 30 days (or however many ranking
rows exist). Each user is then placed at a percentile within the cohort, and
the persona is assigned based on percentile band — this guarantees a sensible
distribution regardless of the absolute scale of the synthetic data.

Disengaged check runs first: <2 ranking rows OR no readings in 14 days.

Called weekly by scheduler (Sunday 02:00 UTC) and on every `docker compose up`
by the bootstrap aggregator. Admins can override classification via the API.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    User, EnergyRanking, UserDecision, Persona,
    Home, EnergyReading, Device,
)

logger = logging.getLogger("persona_classifier")

# ── Persona definitions (seeded to DB on first run) ───────────
DEFAULT_PERSONAS = [
    {
        "name": "Eco Champion",
        "description": "Top performers with high efficiency scores and excellent goal adherence. These users consistently use energy wisely.",
        "criteria": {"percentile_min": 80},
    },
    {
        "name": "Active Improver",
        "description": "Users showing a positive energy reduction trend. Engaged with the platform and working to improve their efficiency.",
        "criteria": {"percentile_min": 55, "percentile_max": 79, "improving_trend": True},
    },
    {
        "name": "Steady User",
        "description": "Consistent users with average community performance. Neither high nor low consumers.",
        "criteria": {"percentile_min": 25, "percentile_max": 79},
    },
    {
        "name": "High Consumer",
        "description": "Users with above-average energy consumption. May benefit from targeted interventions and personalised recommendations.",
        "criteria": {"percentile_max": 24},
    },
    {
        "name": "Disengaged",
        "description": "Users with minimal platform interaction, very low goal adherence, or no recent data. May need re-engagement outreach.",
        "criteria": {"min_ranking_days": 2, "max_inactive_days": 14},
    },
]


# Weights used by the combined score
WEIGHT_EFFICIENCY = 0.50
WEIGHT_ADHERENCE = 0.30
WEIGHT_DECISION = 0.20

# Disengagement gates
MIN_RANKING_DAYS = 2
INACTIVE_DAYS_THRESHOLD = 14

# Percentile bands
PCT_ECO_CHAMPION = 80
PCT_ACTIVE_IMPROVER_LOW = 55
PCT_HIGH_CONSUMER_MAX = 24


# ── Persona Seeder ─────────────────────────────────────────────

async def seed_default_personas(db: AsyncSession) -> None:
    """Insert default personas if they don't exist yet; refresh criteria."""
    for pdef in DEFAULT_PERSONAS:
        existing = await db.execute(select(Persona).where(Persona.name == pdef["name"]))
        persona = existing.scalar_one_or_none()
        if persona is None:
            db.add(Persona(
                name=pdef["name"],
                description=pdef["description"],
                criteria=pdef["criteria"],
            ))
        else:
            # Keep description + criteria in sync with the latest definition
            persona.description = pdef["description"]
            persona.criteria = pdef["criteria"]
    await db.commit()
    logger.info("Default personas seeded / refreshed")


# ── Classification Engine ──────────────────────────────────────

async def classify_all_users(db: AsyncSession) -> dict:
    """
    Classify all non-admin users into personas.

    Strategy:
      1. Compute combined score for every user from the last 30 days of
         EnergyRanking rows.
      2. Mark users with insufficient data (< MIN_RANKING_DAYS rows or no
         recent readings) as Disengaged.
      3. Rank the remaining users by combined score and assign personas
         based on percentile bands (Eco Champion = top 20%, etc.).

    Returns a summary dict {persona_name: count_changed}.
    """
    logger.info("Starting persona classification run...")

    personas_result = await db.execute(select(Persona))
    personas = {p.name: p for p in personas_result.scalars().all()}
    if not personas:
        logger.warning("No personas seeded — run seed_default_personas first")
        return {}

    cutoff_30d = (datetime.utcnow() - timedelta(days=30)).date()
    inactive_cutoff = datetime.utcnow() - timedelta(days=INACTIVE_DAYS_THRESHOLD)

    # ── Step 1: gather all users + their stats ───────────────
    users_result = await db.execute(select(User).where(User.is_admin.is_(False)))
    users = users_result.scalars().all()

    user_stats: list[dict] = []
    disengaged_user_ids: set[int] = set()

    for user in users:
        # Pull ranking metrics (30-day average)
        rk = await db.execute(
            select(
                func.avg(EnergyRanking.efficiency_score).label("avg_eff"),
                func.avg(EnergyRanking.goal_adherence_score).label("avg_adh"),
                func.avg(EnergyRanking.decision_response_score).label("avg_dec"),
                func.count(EnergyRanking.id).label("days"),
            ).where(
                EnergyRanking.user_id == user.id,
                EnergyRanking.period_type == "DAILY",
                EnergyRanking.period_start >= cutoff_30d,
            )
        )
        rk_row = rk.one()
        days = int(rk_row.days or 0)

        # Recent activity check — any reading from this user's homes in the last 14 days?
        last_reading = await db.execute(
            select(func.max(EnergyReading.recorded_at))
            .join(Device, EnergyReading.device_id == Device.id)
            .join(Home, Device.home_id == Home.id)
            .where(Home.user_id == user.id)
        )
        last_seen = last_reading.scalar_one_or_none()
        is_inactive = (last_seen is None) or (last_seen < inactive_cutoff)

        if days < MIN_RANKING_DAYS or is_inactive:
            disengaged_user_ids.add(user.id)
            continue

        avg_eff = float(rk_row.avg_eff or 0)
        avg_adh = float(rk_row.avg_adh or 0)
        avg_dec = float(rk_row.avg_dec or 0)

        combined = (
            avg_eff * WEIGHT_EFFICIENCY
            + avg_adh * WEIGHT_ADHERENCE
            + avg_dec * WEIGHT_DECISION
        )

        improving = await _check_improving_trend(db, user.id)

        user_stats.append({
            "user_id": user.id,
            "user": user,
            "combined": combined,
            "improving": improving,
            "days": days,
        })

    # ── Step 2: percentile ranking among engaged users ───────
    if user_stats:
        user_stats.sort(key=lambda u: u["combined"])
        n = len(user_stats)
        for i, entry in enumerate(user_stats):
            # Percentile: 0 = worst, 100 = best
            entry["percentile"] = (i / max(n - 1, 1)) * 100.0

    # ── Step 3: assignment ───────────────────────────────────
    summary: dict[str, int] = {}

    # First, every disengaged user
    disengaged_persona = personas.get("Disengaged")
    if disengaged_persona:
        for u in users:
            if u.id in disengaged_user_ids and u.persona_id != disengaged_persona.id:
                u.persona_id = disengaged_persona.id
                summary["Disengaged"] = summary.get("Disengaged", 0) + 1

    # Then engaged users by percentile
    for entry in user_stats:
        u = entry["user"]
        pct = entry["percentile"]
        improving = entry["improving"]

        if pct >= PCT_ECO_CHAMPION:
            target_name = "Eco Champion"
        elif pct >= PCT_ACTIVE_IMPROVER_LOW and improving:
            target_name = "Active Improver"
        elif pct <= PCT_HIGH_CONSUMER_MAX:
            target_name = "High Consumer"
        else:
            target_name = "Steady User"

        target = personas.get(target_name)
        if target and u.persona_id != target.id:
            u.persona_id = target.id
            summary[target_name] = summary.get(target_name, 0) + 1

    await db.commit()

    # Always log the final population per persona, even if nothing changed,
    # so operators can see the live distribution.
    final = await _persona_population(db)
    logger.info(
        "Persona classification complete — changes=%s, current population=%s",
        summary, final,
    )
    return {"changed": summary, "population": final}


async def _persona_population(db: AsyncSession) -> dict:
    rows = await db.execute(
        select(Persona.name, func.count(User.id))
        .outerjoin(User, User.persona_id == Persona.id)
        .group_by(Persona.id, Persona.name)
    )
    return {name: int(count) for name, count in rows.all()}


async def _check_improving_trend(db: AsyncSession, user_id: int) -> bool:
    """True if this week's average efficiency is at least 2pts above last week's."""
    now = datetime.utcnow().date()
    week1_start = now - timedelta(days=7)
    week2_start = now - timedelta(days=14)

    async def avg_eff(start, end):
        result = await db.execute(
            select(func.avg(EnergyRanking.efficiency_score))
            .where(
                EnergyRanking.user_id == user_id,
                EnergyRanking.period_type == "DAILY",
                EnergyRanking.period_start >= start,
                EnergyRanking.period_start < end,
            )
        )
        return float(result.scalar() or 0)

    week1_avg = await avg_eff(week1_start, now)
    week2_avg = await avg_eff(week2_start, week1_start)
    return week1_avg > week2_avg + 2.0
