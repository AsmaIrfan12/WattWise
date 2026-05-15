"""
WattWise Persona Classifier — Unsupervised Behavioural Segmentation
===================================================================

Each home (one per user) is segmented into one of five behavioural personas.

Method (PhD-grade)
------------------
Rather than slicing a single hand-weighted score into fixed percentile bands,
engaged users are clustered with K-means over a *standardised behavioural
feature vector*:

  - efficiency            — 30-day mean EnergyRanking.efficiency_score
  - goal_adherence        — 30-day mean goal_adherence_score
  - decision_response     — 30-day mean decision_response_score
  - peak_share            — fraction of kWh used in the UK peak window
  - load_volatility       — coefficient of variation of daily home kWh
  - decision_acceptance   — accepted / total decisions
  - response_latency_log  — log1p(mean notification response time, seconds)
  - efficiency_trend      — OLS slope of daily efficiency over 30 days

Cluster quality is recorded every run (silhouette + Davies–Bouldin) and the
full per-user feature vector is frozen into `persona_cluster_assignments`
so the research analysis can reconstruct and validate every decision.

Clusters are mapped to the four engaged personas deterministically by ranking
each cluster's centroid on a composite "good-behaviour" axis, so persona names
stay interpretable across runs even though the clustering itself is data-driven.

Robustness
----------
- "Disengaged" is a *rule-based pre-filter* (data sufficiency / recency), never
  clustered — clustering noise must not hide a re-engagement need.
- If scikit-learn is unavailable, or the engaged cohort is too small for
  meaningful clusters (common right after a fresh bootstrap with synthetic
  data), the engine falls back to the original percentile-band method. The
  run is still recorded, tagged `percentile_fallback`.

Called weekly by the scheduler (Sun 02:00 Europe/London) and on every
`docker compose up` bootstrap. Admins can still override via the API.
"""

import logging
import math
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import (
    User, EnergyRanking, UserDecision, Persona,
    Home, EnergyReading, Device, HourlySummary, HomeDailyTotal,
    PersonaClusterAssignment,
)

logger = logging.getLogger("persona_classifier")

# ── Persona definitions (seeded to DB on first run) ───────────
DEFAULT_PERSONAS = [
    {
        "name": "Eco Champion",
        "description": "Cluster of the most efficient households: low peak-time usage, strong goal adherence, and high responsiveness to energy-saving prompts.",
        "criteria": {"cluster_rank": 0},
    },
    {
        "name": "Active Improver",
        "description": "Engaged households on a statistically improving efficiency trend — responsive to nudges and moving toward the Eco Champion cluster.",
        "criteria": {"cluster_rank": 1, "improving_trend": True},
    },
    {
        "name": "Steady User",
        "description": "Mid-range households with stable, average behaviour — neither notably efficient nor wasteful.",
        "criteria": {"cluster_rank": 2},
    },
    {
        "name": "High Consumer",
        "description": "Cluster with the highest normalised consumption and peak-time usage. Best target for personalised interventions.",
        "criteria": {"cluster_rank": 3},
    },
    {
        "name": "Disengaged",
        "description": "Insufficient recent data or no platform interaction. Rule-based, never clustered — flagged for re-engagement outreach.",
        "criteria": {"min_ranking_days": 2, "max_inactive_days": 14},
    },
]

# Ordered persona names for the four engaged clusters, best → worst.
ENGAGED_PERSONA_ORDER = ["Eco Champion", "Active Improver", "Steady User", "High Consumer"]
N_CLUSTERS = 4

# Disengagement gates
MIN_RANKING_DAYS = 2
INACTIVE_DAYS_THRESHOLD = 14

# Minimum engaged cohort before clustering is meaningful; below this we fall
# back to percentile banding (keeps fresh/synthetic bootstraps sensible).
MIN_COHORT_FOR_CLUSTERING = 12

# Feature order is fixed — it defines the matrix column layout.
FEATURE_KEYS = [
    "efficiency", "goal_adherence", "decision_response",
    "peak_share", "load_volatility", "decision_acceptance",
    "response_latency_log", "efficiency_trend",
]

# Legacy percentile bands (fallback only)
PCT_ECO_CHAMPION = 80
PCT_ACTIVE_IMPROVER_LOW = 55
PCT_HIGH_CONSUMER_MAX = 24
WEIGHT_EFFICIENCY = 0.50
WEIGHT_ADHERENCE = 0.30
WEIGHT_DECISION = 0.20


# ── Persona Seeder ─────────────────────────────────────────────

async def seed_default_personas(db: AsyncSession) -> None:
    """Insert default personas if missing; keep description/criteria current."""
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
            persona.description = pdef["description"]
            persona.criteria = pdef["criteria"]
    await db.commit()
    logger.info("Default personas seeded / refreshed")


# ── Feature extraction ─────────────────────────────────────────

async def _extract_features(db: AsyncSession, user: User, cutoff_30d, inactive_cutoff):
    """
    Returns (features: dict, engaged: bool).

    When engaged is False the user is Disengaged (rule-based) and `features`
    holds whatever partial signals we have for the research record.
    """
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

    last_reading = await db.execute(
        select(func.max(EnergyReading.recorded_at))
        .join(Device, EnergyReading.device_id == Device.id)
        .join(Home, Device.home_id == Home.id)
        .where(Home.user_id == user.id)
    )
    last_seen = last_reading.scalar_one_or_none()
    is_inactive = (last_seen is None) or (last_seen < inactive_cutoff)

    if days < MIN_RANKING_DAYS or is_inactive:
        return ({"ranking_days": days, "inactive": bool(is_inactive)}, False)

    avg_eff = float(rk_row.avg_eff or 0)
    avg_adh = float(rk_row.avg_adh or 0)
    avg_dec = float(rk_row.avg_dec or 0)

    # Peak-time share — kWh in the UK peak window vs total (last 30d).
    # Grouped by hour-of-day so it's 24 rows/user max. NOTE: hour_start is
    # stored UTC; we apply the configured peak hours directly. The ~1h BST
    # skew is a known, documented approximation — the relative peak-share
    # signal across users is still discriminative for clustering.
    hour_rows = await db.execute(
        select(
            func.hour(HourlySummary.hour_start).label("h"),
            func.sum(HourlySummary.total_kwh).label("kwh"),
        )
        .join(Device, HourlySummary.device_id == Device.id)
        .join(Home, Device.home_id == Home.id)
        .where(
            Home.user_id == user.id,
            HourlySummary.hour_start >= datetime.combine(cutoff_30d, datetime.min.time()),
        )
        .group_by(func.hour(HourlySummary.hour_start))
    )
    peak_kwh = 0.0
    total_kwh = 0.0
    for h, kwh in hour_rows.all():
        kwh = float(kwh or 0)
        total_kwh += kwh
        if settings.ENERGY_PEAK_START_HOUR <= int(h) < settings.ENERGY_PEAK_END_HOUR:
            peak_kwh += kwh
    peak_share = (peak_kwh / total_kwh) if total_kwh > 0 else 0.0

    # Load volatility — coefficient of variation of daily home kWh (30d).
    daily_rows = await db.execute(
        select(HomeDailyTotal.total_kwh)
        .join(Home, HomeDailyTotal.home_id == Home.id)
        .where(
            Home.user_id == user.id,
            HomeDailyTotal.day_date >= cutoff_30d,
        )
    )
    daily_vals = [float(v or 0) for (v,) in daily_rows.all()]
    if len(daily_vals) >= 2:
        mean_d = sum(daily_vals) / len(daily_vals)
        var_d = sum((x - mean_d) ** 2 for x in daily_vals) / len(daily_vals)
        load_volatility = (math.sqrt(var_d) / mean_d) if mean_d > 0 else 0.0
    else:
        load_volatility = 0.0

    # Decision behaviour — acceptance rate + response latency (30d).
    dec_row = (await db.execute(
        select(
            func.count(UserDecision.id).label("total"),
            func.sum(
                case((UserDecision.decision_type == "ACCEPTED", 1), else_=0)
            ).label("accepted"),
            func.avg(UserDecision.response_time_seconds).label("avg_latency"),
        ).where(
            UserDecision.user_id == user.id,
            UserDecision.created_at >= datetime.combine(cutoff_30d, datetime.min.time()),
        )
    )).one()
    total_dec = int(dec_row.total or 0)
    accepted_dec = int(dec_row.accepted or 0)
    decision_acceptance = (accepted_dec / total_dec) if total_dec > 0 else 0.0
    response_latency_log = math.log1p(float(dec_row.avg_latency or 0.0))

    efficiency_trend = await _efficiency_trend_slope(db, user.id, cutoff_30d)

    features = {
        "efficiency": avg_eff,
        "goal_adherence": avg_adh,
        "decision_response": avg_dec,
        "peak_share": peak_share,
        "load_volatility": load_volatility,
        "decision_acceptance": decision_acceptance,
        "response_latency_log": response_latency_log,
        "efficiency_trend": efficiency_trend,
        "ranking_days": days,
    }
    return (features, True)


async def _efficiency_trend_slope(db: AsyncSession, user_id: int, cutoff_30d) -> float:
    """
    Ordinary-least-squares slope of daily efficiency_score over the last 30
    days (pts per day). Replaces the old fragile 2-point week-vs-week compare
    with a defensible trend estimate over the full series.
    """
    rows = await db.execute(
        select(EnergyRanking.period_start, EnergyRanking.efficiency_score)
        .where(
            EnergyRanking.user_id == user_id,
            EnergyRanking.period_type == "DAILY",
            EnergyRanking.period_start >= cutoff_30d,
        )
        .order_by(EnergyRanking.period_start.asc())
    )
    pts = [(d, float(s or 0)) for d, s in rows.all() if s is not None]
    if len(pts) < 3:
        return 0.0
    base = pts[0][0]
    xs = [(d - base).days for d, _ in pts]
    ys = [s for _, s in pts]
    n = len(xs)
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return 0.0
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom


# ── Classification Engine ──────────────────────────────────────

async def classify_all_users(db: AsyncSession) -> dict:
    """Segment all non-admin users. Returns a summary dict (callers log it)."""
    logger.info("Starting persona classification run...")

    personas_result = await db.execute(select(Persona))
    personas = {p.name: p for p in personas_result.scalars().all()}
    if not personas:
        logger.warning("No personas seeded — run seed_default_personas first")
        return {}

    cutoff_30d = (datetime.utcnow() - timedelta(days=30)).date()
    inactive_cutoff = datetime.utcnow() - timedelta(days=INACTIVE_DAYS_THRESHOLD)

    users_result = await db.execute(select(User).where(User.is_admin.is_(False)))
    users = users_result.scalars().all()

    engaged: list[dict] = []
    disengaged: list[tuple[User, dict]] = []

    for user in users:
        feats, is_engaged = await _extract_features(db, user, cutoff_30d, inactive_cutoff)
        if is_engaged:
            engaged.append({"user": user, "features": feats})
        else:
            disengaged.append((user, feats))

    run_id = str(uuid.uuid4())
    run_at = datetime.utcnow()
    summary: dict[str, int] = {}

    # ── Disengaged: rule-based, never clustered ──────────────
    dis_persona = personas.get("Disengaged")
    for user, feats in disengaged:
        if dis_persona and user.persona_id != dis_persona.id:
            user.persona_id = dis_persona.id
            summary["Disengaged"] = summary.get("Disengaged", 0) + 1
        db.add(PersonaClusterAssignment(
            run_id=run_id, run_at=run_at, user_id=user.id,
            persona_id=dis_persona.id if dis_persona else None,
            cluster_label=-1, algorithm="rule_based_disengaged",
            n_samples=len(engaged), features=feats,
        ))

    # ── Engaged: cluster (or fall back) ──────────────────────
    algorithm, silhouette, davies_bouldin = "percentile_fallback", None, None
    cluster_labels: dict[int, int] = {}      # user_id -> raw cluster label

    use_clustering = len(engaged) >= MIN_COHORT_FOR_CLUSTERING
    if use_clustering:
        try:
            algorithm, silhouette, davies_bouldin, cluster_labels = _kmeans_assign(
                engaged, personas, summary
            )
        except Exception as e:
            logger.warning("Clustering failed (%s) — falling back to percentile", e)
            use_clustering = False

    if not use_clustering:
        _percentile_assign(engaged, personas, summary)

    for entry in engaged:
        user = entry["user"]
        db.add(PersonaClusterAssignment(
            run_id=run_id, run_at=run_at, user_id=user.id,
            persona_id=user.persona_id,
            cluster_label=cluster_labels.get(user.id, -1),
            algorithm=algorithm,
            silhouette=silhouette, davies_bouldin=davies_bouldin,
            n_samples=len(engaged), features=entry["features"],
        ))

    await db.commit()

    final = await _persona_population(db)
    logger.info(
        "Persona classification complete — algo=%s n=%d silhouette=%s db=%s "
        "changes=%s population=%s",
        algorithm, len(engaged),
        round(silhouette, 3) if silhouette is not None else None,
        round(davies_bouldin, 3) if davies_bouldin is not None else None,
        summary, final,
    )
    return {
        "changed": summary,
        "population": final,
        "algorithm": algorithm,
        "n_engaged": len(engaged),
        "silhouette": silhouette,
        "davies_bouldin": davies_bouldin,
        "run_id": run_id,
    }


def _kmeans_assign(engaged: list[dict], personas: dict, summary: dict):
    """
    Standardise features → K-means → map clusters to personas by centroid
    rank on a composite good-behaviour axis. Mutates user.persona_id and
    `summary`. Returns (algorithm, silhouette, davies_bouldin, {uid: label}).
    """
    import numpy as np
    from sklearn.cluster import KMeans
    from sklearn.preprocessing import StandardScaler
    from sklearn.metrics import silhouette_score, davies_bouldin_score

    X = np.array([
        [float(e["features"][k]) for k in FEATURE_KEYS] for e in engaged
    ], dtype=float)
    Xs = StandardScaler().fit_transform(X)

    k = min(N_CLUSTERS, len(engaged))
    km = KMeans(n_clusters=k, n_init=10, random_state=42)
    labels = km.fit_predict(Xs)

    sil = db_idx = None
    if k > 1 and len(set(labels)) > 1:
        sil = float(silhouette_score(Xs, labels))
        db_idx = float(davies_bouldin_score(Xs, labels))

    # Composite "good behaviour" per cluster (standardised space):
    # higher efficiency/adherence/decision/acceptance/trend = better;
    # higher peak_share/volatility/latency = worse.
    sign = np.array([
        +1,  # efficiency
        +1,  # goal_adherence
        +1,  # decision_response
        -1,  # peak_share
        -1,  # load_volatility
        +1,  # decision_acceptance
        -1,  # response_latency_log
        +1,  # efficiency_trend
    ], dtype=float)
    composite = {}
    for c in range(k):
        members = Xs[labels == c]
        composite[c] = float((members.mean(axis=0) * sign).sum())

    # Best composite → Eco Champion, then down the ordered persona list.
    ranked = sorted(composite, key=lambda c: composite[c], reverse=True)
    cluster_to_persona = {}
    for rank, cluster in enumerate(ranked):
        name = ENGAGED_PERSONA_ORDER[min(rank, len(ENGAGED_PERSONA_ORDER) - 1)]
        cluster_to_persona[cluster] = name

    # Rank-1 cluster is only "Active Improver" if it is genuinely improving
    # (mean efficiency_trend > 0); otherwise it is a Steady User cluster.
    trend_idx = FEATURE_KEYS.index("efficiency_trend")
    if len(ranked) >= 2:
        c1 = ranked[1]
        c1_trend = float(X[labels == c1][:, trend_idx].mean()) if (labels == c1).any() else 0.0
        if c1_trend <= 0:
            cluster_to_persona[c1] = "Steady User"

    out_labels: dict[int, int] = {}
    for entry, lbl in zip(engaged, labels):
        user = entry["user"]
        out_labels[user.id] = int(lbl)
        target = personas.get(cluster_to_persona.get(int(lbl), "Steady User"))
        if target and user.persona_id != target.id:
            user.persona_id = target.id
            summary[target.name] = summary.get(target.name, 0) + 1

    return "kmeans", sil, db_idx, out_labels


def _percentile_assign(engaged: list[dict], personas: dict, summary: dict):
    """Legacy weighted-percentile banding — fallback for small cohorts."""
    scored = []
    for e in engaged:
        f = e["features"]
        combined = (
            f["efficiency"] * WEIGHT_EFFICIENCY
            + f["goal_adherence"] * WEIGHT_ADHERENCE
            + f["decision_response"] * WEIGHT_DECISION
        )
        scored.append((e["user"], combined, f.get("efficiency_trend", 0.0)))

    scored.sort(key=lambda t: t[1])
    n = len(scored)
    for i, (user, _combined, trend) in enumerate(scored):
        pct = (i / max(n - 1, 1)) * 100.0
        if pct >= PCT_ECO_CHAMPION:
            name = "Eco Champion"
        elif pct >= PCT_ACTIVE_IMPROVER_LOW and trend > 0:
            name = "Active Improver"
        elif pct <= PCT_HIGH_CONSUMER_MAX:
            name = "High Consumer"
        else:
            name = "Steady User"
        target = personas.get(name)
        if target and user.persona_id != target.id:
            user.persona_id = target.id
            summary[name] = summary.get(name, 0) + 1


async def _persona_population(db: AsyncSession) -> dict:
    rows = await db.execute(
        select(Persona.name, func.count(User.id))
        .outerjoin(User, User.persona_id == Persona.id)
        .group_by(Persona.id, Persona.name)
    )
    return {name: int(count) for name, count in rows.all()}
