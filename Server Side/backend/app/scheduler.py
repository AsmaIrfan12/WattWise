"""
WattWise Scheduler
==================
APScheduler jobs for automated energy aggregation, goal checking,
notification delivery, ranking computation, and decision impact tracking.
"""

import logging
from datetime import datetime, timedelta, date

from sqlalchemy import select, func, text

from app.database import AsyncSessionLocal
from app.models import (
    Device, EnergyReading, HourlySummary, DailySummary,
    HomeDailyTotal, Home, User, EnergyGoal, EnergyRanking,
)
from app.energy_analysis import EnergyAnalysisEngine

logger = logging.getLogger("scheduler")


# ── Hourly Aggregation ────────────────────────────────────────

async def aggregate_hourly(target_time: datetime = None):
    """
    Called every 30 minutes (or manually).
    Aggregates energy readings into hourly summaries per device.
    """
    logger.info("Running hourly aggregation...")
    now = target_time or datetime.utcnow()
    # Round down to current hour boundary
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    prev_hour = current_hour - timedelta(hours=1)

    async with AsyncSessionLocal() as db:
        # Get all active devices
        devs_result = await db.execute(select(Device).where(Device.is_active == True))
        devices = devs_result.scalars().all()

        for device in devices:
            try:
                # Fetch readings for the previous hour
                readings_result = await db.execute(
                    select(EnergyReading).where(
                        EnergyReading.device_id == device.id,
                        EnergyReading.recorded_at >= prev_hour,
                        EnergyReading.recorded_at < current_hour,
                    ).order_by(EnergyReading.recorded_at.asc())
                )
                readings = readings_result.scalars().all()

                if not readings:
                    continue

                reading_dicts = [{"recorded_at": r.recorded_at, "power_watts": r.power_watts, "energy_kwh": r.energy_kwh} for r in readings]
                stats = EnergyAnalysisEngine.detect_usage_cycles(reading_dicts)

                # Upsert hourly summary
                existing = await db.execute(
                    select(HourlySummary).where(
                        HourlySummary.device_id == device.id,
                        HourlySummary.hour_start == prev_hour
                    )
                )
                summary = existing.scalar_one_or_none()

                if summary:
                    summary.avg_watts = stats["avg_watts"]
                    summary.max_watts = stats["peak_watts"]
                    summary.total_kwh = stats["total_kwh"]
                    summary.usage_cycles = stats["cycles"]
                    summary.active_minutes = stats["active_minutes"]
                    summary.reading_count = len(readings)
                else:
                    summary = HourlySummary(
                        device_id=device.id,
                        hour_start=prev_hour,
                        avg_watts=stats["avg_watts"],
                        max_watts=stats["peak_watts"],
                        min_watts=min((r.power_watts for r in readings), default=0),
                        total_kwh=stats["total_kwh"],
                        usage_cycles=stats["cycles"],
                        active_minutes=stats["active_minutes"],
                        reading_count=len(readings),
                    )
                    db.add(summary)

            except Exception as e:
                logger.error(f"Hourly aggregation error for device {device.id}: {e}")

        await db.commit()
    logger.info("Hourly aggregation complete")


# ── Daily Aggregation ─────────────────────────────────────────

async def aggregate_daily(target_date: date = None):
    """
    Called daily at 00:15 (or manually).
    Aggregates hourly summaries into daily summaries and updates home daily totals.
    """
    yesterday = target_date or (datetime.utcnow() - timedelta(days=1)).date()
    logger.info(f"Running daily aggregation for {yesterday}...")

    async with AsyncSessionLocal() as db:
        devs_result = await db.execute(select(Device).where(Device.is_active == True))
        devices = devs_result.scalars().all()

        home_totals: dict[int, dict] = {}

        for device in devices:
            try:
                # Aggregate from hourly summaries
                result = await db.execute(
                    select(
                        func.sum(HourlySummary.total_kwh).label("total_kwh"),
                        func.avg(HourlySummary.avg_watts).label("avg_watts"),
                        func.max(HourlySummary.max_watts).label("peak_watts"),
                        func.sum(HourlySummary.usage_cycles).label("cycles"),
                        func.sum(HourlySummary.active_minutes).label("active_min"),
                        func.sum(HourlySummary.reading_count).label("readings"),
                    ).where(
                        HourlySummary.device_id == device.id,
                        func.date(HourlySummary.hour_start) == yesterday,
                    )
                )
                row = result.one()
                if not row.total_kwh:
                    continue

                total_kwh = float(row.total_kwh or 0)
                avg_watts = float(row.avg_watts or 0)
                peak_watts = float(row.peak_watts or 0)
                estimated_cost = EnergyAnalysisEngine.calculate_daily_cost(total_kwh)

                # Check active goal for this device
                home_user_id_subquery = (
                    select(Home.user_id)
                    .where(Home.id == device.home_id)
                    .scalar_subquery()
                )

                goal_result = await db.execute(
                    select(EnergyGoal).where(
                        EnergyGoal.user_id == home_user_id_subquery,
                        EnergyGoal.is_active == True,
                        EnergyGoal.goal_type == "daily",
                        EnergyGoal.device_id == device.id,
                        EnergyGoal.start_date <= yesterday,
                    ).limit(1)
                )
                goal = goal_result.scalar_one_or_none()
                goal_kwh = goal.target_kwh if goal else None
                goal_met = (total_kwh <= goal_kwh) if goal_kwh else None

                eff_score = EnergyAnalysisEngine.calculate_efficiency_score(
                    appliance_key=device.appliance_key,
                    total_kwh=total_kwh,
                    cycles=int(row.cycles or 0),
                    active_minutes=int(row.active_min or 0),
                    goal_kwh=goal_kwh,
                )

                # Upsert daily summary
                existing = await db.execute(
                    select(DailySummary).where(
                        DailySummary.device_id == device.id,
                        DailySummary.day_date == yesterday
                    )
                )
                ds = existing.scalar_one_or_none()
                if ds:
                    ds.total_kwh = total_kwh
                    ds.avg_watts = avg_watts
                    ds.peak_watts = peak_watts
                    ds.usage_cycles = int(row.cycles or 0)
                    ds.active_minutes = int(row.active_min or 0)
                    ds.estimated_cost_gbp = estimated_cost
                    ds.efficiency_score = eff_score
                    ds.goal_kwh = goal_kwh
                    ds.goal_met = goal_met
                    ds.reading_count = int(row.readings or 0)
                else:
                    ds = DailySummary(
                        device_id=device.id,
                        home_id=device.home_id,
                        day_date=yesterday,
                        total_kwh=total_kwh,
                        avg_watts=avg_watts,
                        peak_watts=peak_watts,
                        usage_cycles=int(row.cycles or 0),
                        active_minutes=int(row.active_min or 0),
                        estimated_cost_gbp=estimated_cost,
                        efficiency_score=eff_score,
                        goal_kwh=goal_kwh,
                        goal_met=goal_met,
                        reading_count=int(row.readings or 0),
                    )
                    db.add(ds)

                # Accumulate for home totals
                home_id = device.home_id
                if home_id not in home_totals:
                    home_totals[home_id] = {"kwh": 0.0, "cost": 0.0, "devices": 0, "peak": 0.0}
                home_totals[home_id]["kwh"] += total_kwh
                home_totals[home_id]["cost"] += estimated_cost
                home_totals[home_id]["devices"] += 1
                home_totals[home_id]["peak"] = max(home_totals[home_id]["peak"], peak_watts)

            except Exception as e:
                logger.error(f"Daily agg error for device {device.id}: {e}")

        # Write home daily totals
        for home_id, totals in home_totals.items():
            existing = await db.execute(
                select(HomeDailyTotal).where(HomeDailyTotal.home_id == home_id, HomeDailyTotal.day_date == yesterday)
            )
            hdt = existing.scalar_one_or_none()
            if hdt:
                hdt.total_kwh = round(totals["kwh"], 4)
                hdt.total_cost_gbp = round(totals["cost"], 4)
                hdt.active_devices = totals["devices"]
                hdt.peak_watts = totals["peak"]
            else:
                hdt = HomeDailyTotal(
                    home_id=home_id,
                    day_date=yesterday,
                    total_kwh=round(totals["kwh"], 4),
                    total_cost_gbp=round(totals["cost"], 4),
                    active_devices=totals["devices"],
                    peak_watts=totals["peak"],
                )
                db.add(hdt)

        await db.commit()
    logger.info("Daily aggregation complete")


# ── Goal Notifications ────────────────────────────────────────

async def check_goals():
    """Called every hour. Checks goal progress and sends alert notifications."""
    from app.notification_engine import NotificationEngine
    async with AsyncSessionLocal() as db:
        await NotificationEngine.check_daily_goal_notifications(db)


# ── Peak Tariff Reminder ──────────────────────────────────────

async def send_peak_reminder():
    """Called daily at 15:45 (3:45 PM). Warns users about peak tariff at 4 PM."""
    from app.notification_engine import NotificationEngine
    async with AsyncSessionLocal() as db:
        await NotificationEngine.send_peak_tariff_reminder(db)


# ── Daily Summary Notification ────────────────────────────────

async def send_daily_report():
    """Called daily at 07:00. Sends yesterday's usage summary to all users."""
    from app.notification_engine import NotificationEngine
    async with AsyncSessionLocal() as db:
        await NotificationEngine.send_daily_summary(db)


# ── Decision Impact Calculation ───────────────────────────────

async def calculate_decision_impacts():
    """Called every 2 hours. Calculates energy impact for pending user decisions."""
    from app.decision_tracker import DecisionTracker
    async with AsyncSessionLocal() as db:
        count = await DecisionTracker.calculate_impact_for_pending_decisions(db)
        if count:
            logger.info(f"Decision impacts calculated: {count}")


# ── Community Rankings ────────────────────────────────────────

async def compute_rankings(target_date: date = None, period_type: str = "DAILY"):
    """
    Compute energy-efficiency rankings for all homes for a given period.

    period_type:
      DAILY   — rankings for `target_date` (one day)
      WEEKLY  — rankings for the ISO week containing `target_date`,
                period_start = Monday of that week
      MONTHLY — rankings for the calendar month of `target_date`,
                period_start = 1st of that month
    """
    if period_type not in ("DAILY", "WEEKLY", "MONTHLY"):
        raise ValueError(f"Unsupported period_type: {period_type}")

    target_date = target_date or (datetime.utcnow() - timedelta(days=1)).date()

    if period_type == "DAILY":
        period_start = target_date
        period_end = target_date
    elif period_type == "WEEKLY":
        # Monday of target_date's week
        period_start = target_date - timedelta(days=target_date.weekday())
        period_end = period_start + timedelta(days=6)
    else:  # MONTHLY
        period_start = target_date.replace(day=1)
        # Last day of month: jump to next month's day=1, subtract 1 day
        if period_start.month == 12:
            next_month_first = period_start.replace(year=period_start.year + 1, month=1)
        else:
            next_month_first = period_start.replace(month=period_start.month + 1)
        period_end = next_month_first - timedelta(days=1)

    logger.info(
        "Computing %s rankings for period %s -> %s",
        period_type, period_start, period_end,
    )

    async with AsyncSessionLocal() as db:
        # Aggregate home_daily_totals across the period for each home
        result = await db.execute(
            select(
                Home.id.label("home_id"),
                Home.user_id,
                Home.home_name,
                Home.num_occupants,
                func.sum(HomeDailyTotal.total_kwh).label("total_kwh"),
                func.sum(HomeDailyTotal.total_cost_gbp).label("total_cost"),
            )
            .join(HomeDailyTotal, HomeDailyTotal.home_id == Home.id)
            .where(
                HomeDailyTotal.day_date >= period_start,
                HomeDailyTotal.day_date <= period_end,
            )
            .group_by(Home.id, Home.user_id, Home.home_name, Home.num_occupants)
            .order_by(func.sum(HomeDailyTotal.total_kwh).asc())  # Lower usage = better
        )
        rows = result.all()
        total_users = len(rows)

        # Period length in days — used to scale per-day goals up to the period
        period_days = (period_end - period_start).days + 1

        # Batch the per-home lookups that used to be N+1 queries inside the loop
        # (goal, decision score, existing ranking) into one query each.
        from app.models import UserDecision
        user_ids = [r.user_id for r in rows]

        goal_rows = await db.execute(
            select(User.id, User.daily_energy_goal_kwh).where(User.id.in_(user_ids))
        )
        goal_by_user = {uid: goal for uid, goal in goal_rows.all()}

        dec_rows = await db.execute(
            select(
                UserDecision.user_id,
                func.avg(UserDecision.effectiveness_score),
            )
            .where(
                UserDecision.user_id.in_(user_ids),
                func.date(UserDecision.created_at) >= period_start,
                func.date(UserDecision.created_at) <= period_end,
            )
            .group_by(UserDecision.user_id)
        )
        decision_by_user = {uid: score for uid, score in dec_rows.all()}

        existing_rows = await db.execute(
            select(EnergyRanking).where(
                EnergyRanking.period_type == period_type,
                EnergyRanking.period_start == period_start,
                EnergyRanking.user_id.in_(user_ids),
            )
        )
        ranking_by_user = {r.user_id: r for r in existing_rows.scalars().all()}

        for rank, hdt in enumerate(rows, start=1):
            try:
                occupants = max((hdt.num_occupants or 1), 1)
                # Per-occupant per-day usage normalises across home size + period length
                kwh_per_person_per_day = float(hdt.total_kwh) / occupants / max(period_days, 1)

                # Score: 100 at 0 kWh/person/day, drops 10pts per kWh/person/day
                eff_score = max(0.0, min(100.0, 100.0 - (kwh_per_person_per_day * 10.0)))

                daily_goal = goal_by_user.get(hdt.user_id)
                if daily_goal and daily_goal > 0:
                    period_goal = daily_goal * period_days
                    adherence = max(0.0, min(100.0, (period_goal / max(float(hdt.total_kwh), 0.001)) * 100.0))
                else:
                    adherence = 70.0  # Default when no goal set

                avg_decision_score = decision_by_user.get(hdt.user_id) or 70.0

                overall = (eff_score * 0.4 + adherence * 0.35 + float(avg_decision_score) * 0.25)
                percentile = ((total_users - rank) / max(total_users - 1, 1)) * 100

                ranking = ranking_by_user.get(hdt.user_id)
                if ranking:
                    ranking.overall_score = round(overall, 1)
                    ranking.rank_position = rank
                    ranking.total_users = total_users
                    ranking.percentile = round(percentile, 1)
                    ranking.efficiency_score = round(eff_score, 1)
                    ranking.goal_adherence_score = round(adherence, 1)
                    ranking.decision_response_score = round(float(avg_decision_score), 1)
                    ranking.total_kwh = float(hdt.total_kwh)
                    ranking.total_cost_gbp = float(hdt.total_cost or 0)
                else:
                    ranking = EnergyRanking(
                        user_id=hdt.user_id,
                        home_id=hdt.home_id,
                        period_type=period_type,
                        period_start=period_start,
                        overall_score=round(overall, 1),
                        rank_position=rank,
                        total_users=total_users,
                        percentile=round(percentile, 1),
                        efficiency_score=round(eff_score, 1),
                        goal_adherence_score=round(adherence, 1),
                        decision_response_score=round(float(avg_decision_score), 1),
                        total_kwh=float(hdt.total_kwh),
                        total_cost_gbp=float(hdt.total_cost or 0),
                    )
                    db.add(ranking)

            except Exception as e:
                logger.error("Ranking error for home %s: %s", hdt.home_id, e)

        await db.commit()
    logger.info("Rankings computed: %s homes for %s %s", total_users, period_type, period_start)


async def compute_rankings_for_range(
    start_date: date = None,
    end_date: date = None,
    period_types: tuple = ("DAILY", "WEEKLY", "MONTHLY"),
):
    """
    Compute rankings for every period that intersects [start_date, end_date].
    If dates are omitted, the range derives from the available HomeDailyTotal data.
    Idempotent — safe to re-run.
    """
    async with AsyncSessionLocal() as db:
        bounds = await db.execute(
            select(func.min(HomeDailyTotal.day_date), func.max(HomeDailyTotal.day_date))
        )
        min_d, max_d = bounds.one()
    if not min_d or not max_d:
        logger.info("compute_rankings_for_range: no HomeDailyTotal rows yet — skipping")
        return {"daily": 0, "weekly": 0, "monthly": 0}

    start_date = start_date or min_d
    end_date = end_date or max_d

    counts = {"daily": 0, "weekly": 0, "monthly": 0}

    if "DAILY" in period_types:
        d = start_date
        while d <= end_date:
            await compute_rankings(d, "DAILY")
            counts["daily"] += 1
            d += timedelta(days=1)

    if "WEEKLY" in period_types:
        # Snap to Monday of the week that contains start_date
        wk_cursor = start_date - timedelta(days=start_date.weekday())
        seen_weeks: set = set()
        while wk_cursor <= end_date:
            if wk_cursor not in seen_weeks:
                await compute_rankings(wk_cursor, "WEEKLY")
                seen_weeks.add(wk_cursor)
                counts["weekly"] += 1
            wk_cursor += timedelta(days=7)

    if "MONTHLY" in period_types:
        m_cursor = start_date.replace(day=1)
        seen_months: set = set()
        while m_cursor <= end_date:
            if m_cursor not in seen_months:
                await compute_rankings(m_cursor, "MONTHLY")
                seen_months.add(m_cursor)
                counts["monthly"] += 1
            # Advance to first of next month
            if m_cursor.month == 12:
                m_cursor = m_cursor.replace(year=m_cursor.year + 1, month=1)
            else:
                m_cursor = m_cursor.replace(month=m_cursor.month + 1)

    logger.info(
        "Rankings range computed (%s -> %s): %s",
        start_date, end_date, counts,
    )
    return counts


# ── Automated Analytics Thresholds ──────────────────────────────

async def evaluate_analytics_thresholds():
    """
    Called daily after aggregation. Evaluates comparison metrics and triggers
    automated alerts (HIGH_CONSUMPTION, STANDBY_ALERT, RECOMMENDATION).
    """
    logger.info("Evaluating analytics thresholds for automated alerts...")
    from app.notification_engine import NotificationEngine
    yesterday = date.today() - timedelta(days=1)

    async with AsyncSessionLocal() as db:
        # 1. High Consumption Alert (Users)
        # Compare users' daily total against the 95th percentile.
        totals_result = await db.execute(
            select(HomeDailyTotal.home_id, HomeDailyTotal.total_kwh, Home.user_id)
            .join(Home, HomeDailyTotal.home_id == Home.id)
            .where(HomeDailyTotal.day_date == yesterday)
        )
        totals = totals_result.all()
        
        if totals and len(totals) > 5:
            kwh_values = sorted([float(row.total_kwh or 0) for row in totals])
            p95_index = int(len(kwh_values) * 0.95)
            p95_threshold = max(kwh_values[p95_index], 5.0) # ignore if overall usage is low
            
            for row in totals:
                if row.total_kwh > p95_threshold:
                    await NotificationEngine.create_notification(
                        db=db,
                        user_id=row.user_id,
                        home_id=row.home_id,
                        title="High Energy Consumption Detected",
                        message=f"Your energy usage yesterday ({row.total_kwh:.1f} kWh) was significantly above the community average. Consider turning off unused appliances.",
                        notification_type="HIGH_CONSUMPTION",
                        severity="WARNING",
                        action_button_text="Review Analytics"
                    )

        # 2. Standby / Offline Anomaly (Devices)
        # Look for devices with 0 active minutes but >0 energy consumed (vampire drain).
        dev_result = await db.execute(
            select(DailySummary.device_id, DailySummary.total_kwh, Device.name, Home.user_id)
            .join(Device, DailySummary.device_id == Device.id)
            .join(Home, Device.home_id == Home.id)
            .where(DailySummary.day_date == yesterday, DailySummary.active_minutes == 0, DailySummary.total_kwh > 0.1)
        )
        standby_devices = dev_result.all()

        for row in standby_devices:
            await NotificationEngine.create_notification(
                db=db,
                user_id=row.user_id,
                device_id=row.device_id,
                title="Vampire Drain Detected",
                message=f"Your {row.name} was not actively used yesterday but consumed {row.total_kwh:.2f} kWh in standby. Consider unplugging it.",
                notification_type="STANDBY_ALERT",
                severity="INFO",
                action_button_text="Turn Off Device"
            )
            
    logger.info("Analytics thresholds evaluation complete")


# ── Bootstrap: aggregate ALL history on demand ────────────────

async def detect_and_notify_anomalies(
    threshold_factor: float = 3.0,
    lookback_hours: int = 24,
) -> dict:
    """
    Scan recent hourly_summary rows for any device that exceeded
    `threshold_factor × its 30-day baseline` for the same hour-of-day, and
    create a per-user notification about each anomaly found.

    Idempotent — uses NotificationEngine's 12-hour dedup so re-running won't
    spam the same user about the same anomaly.

    Designed to run hourly via APScheduler.
    """
    from app.notification_engine import NotificationEngine

    logger.info("Scanning for anomalous device usage (factor=%s, lookback=%sh)…", threshold_factor, lookback_hours)
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
    since = now - timedelta(hours=lookback_hours)
    baseline_window_start = now - timedelta(days=30)

    async with AsyncSessionLocal() as db:
        # 30-day baseline per (device, hour-of-day)
        baseline_rows = (await db.execute(
            select(
                HourlySummary.device_id,
                func.hour(HourlySummary.hour_start).label("hod"),
                func.avg(HourlySummary.total_kwh).label("baseline_avg_kwh"),
            )
            .where(HourlySummary.hour_start >= baseline_window_start)
            .group_by(HourlySummary.device_id, func.hour(HourlySummary.hour_start))
        )).all()
        baseline = {(int(r.device_id), int(r.hod)): float(r.baseline_avg_kwh or 0) for r in baseline_rows}

        # Recent hourly buckets to evaluate
        from app.models import Notification
        recent_rows = (await db.execute(
            select(
                HourlySummary.device_id,
                HourlySummary.hour_start,
                HourlySummary.total_kwh,
                Device.name.label("device_name"),
                Device.appliance_key,
                Home.user_id,
                Home.id.label("home_id"),
            )
            .join(Device, HourlySummary.device_id == Device.id)
            .join(Home, Device.home_id == Home.id)
            .where(HourlySummary.hour_start >= since, Device.is_active.is_(True))
        )).all()

        created = 0
        skipped_dedup = 0
        skipped_below = 0

        for r in recent_rows:
            baseline_val = baseline.get((int(r.device_id), r.hour_start.hour), 0)
            if baseline_val <= 0.005:
                continue
            kwh = float(r.total_kwh or 0)
            ratio = kwh / baseline_val
            if ratio < threshold_factor:
                skipped_below += 1
                continue

            severity = "CRITICAL" if ratio >= threshold_factor * 2 else "WARNING"
            hour_label = r.hour_start.strftime("%H:%M")
            title = f"⚠️ Unusual {r.device_name} usage at {hour_label}"
            message = (
                f"Your {r.device_name} used {kwh:.3f} kWh between "
                f"{hour_label} and {(r.hour_start + timedelta(hours=1)).strftime('%H:%M')} — "
                f"that's {ratio:.1f}× your usual amount for this hour. "
                f"Check whether the appliance was left running, or if a high-energy cycle was used."
            )

            notif = await NotificationEngine.create_notification(
                db=db,
                user_id=r.user_id,
                title=title,
                message=message,
                notification_type="HIGH_CONSUMPTION",
                severity=severity,
                home_id=r.home_id,
                device_id=r.device_id,
                requires_user_action=True,
                action_hint="Investigate this device's usage.",
                action_button_text="View device",
            )
            if notif:
                created += 1
            else:
                skipped_dedup += 1

    logger.info(
        "Anomaly notification scan complete: created=%d, skipped_dedup=%d, skipped_below=%d, threshold=%sx",
        created, skipped_dedup, skipped_below, threshold_factor,
    )
    return {
        "created": created,
        "skipped_dedup": skipped_dedup,
        "skipped_below": skipped_below,
        "threshold_factor": threshold_factor,
        "lookback_hours": lookback_hours,
    }


async def cleanup_old_notifications(retention_days: int = 90) -> dict:
    """
    Delete notifications older than `retention_days` so the table doesn't
    grow forever. Mirrors the MongoDB TTL index that the old system used.

    Default retention: 90 days. Returns counts of deleted notifications +
    user_decisions linked to those notifications (orphaned references are
    preserved via NULL because the FK uses ON DELETE SET NULL).
    """
    from sqlalchemy import delete
    from app.models import Notification

    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    logger.info("Cleaning up notifications older than %s (cutoff=%s)", retention_days, cutoff)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            delete(Notification).where(Notification.created_at < cutoff)
        )
        await db.commit()
        deleted = result.rowcount or 0

    logger.info("Notification cleanup complete: deleted %d rows", deleted)
    return {"deleted": deleted, "retention_days": retention_days, "cutoff": cutoff.isoformat()}


async def aggregate_all_history() -> dict:
    """
    Scan energy_readings for the full available date range, then run
    aggregate_hourly for every completed hour and aggregate_daily for every
    day in that range. Idempotent — re-running is safe.

    Returns a summary dict with row counts and the processed window.
    """
    logger.info("Bootstrap aggregation: scanning available history...")

    async with AsyncSessionLocal() as db:
        bounds = await db.execute(
            select(func.min(EnergyReading.recorded_at), func.max(EnergyReading.recorded_at))
        )
        first_ts, last_ts = bounds.one()

    if not first_ts or not last_ts:
        logger.info("Bootstrap aggregation: no readings found — nothing to do")
        return {"hours_processed": 0, "days_processed": 0, "first_ts": None, "last_ts": None}

    # Aggregate from the hour AFTER first_ts up to and including current_hour.
    # aggregate_hourly(target_time) processes the hour BEFORE target_time, so
    # pass target_time = hour_boundary + 1h to capture hour_boundary itself.
    first_hour = first_ts.replace(minute=0, second=0, microsecond=0)
    now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)

    hours_processed = 0
    t = first_hour + timedelta(hours=1)
    while t <= now + timedelta(hours=1):
        await aggregate_hourly(t)
        hours_processed += 1
        t += timedelta(hours=1)

    days_processed = 0
    d = first_ts.date()
    today = datetime.utcnow().date()
    while d <= today:
        await aggregate_daily(d)
        days_processed += 1
        d += timedelta(days=1)

    logger.info(
        "Bootstrap aggregation complete: %d hours, %d days processed (range %s -> %s)",
        hours_processed, days_processed, first_ts, last_ts,
    )
    return {
        "hours_processed": hours_processed,
        "days_processed": days_processed,
        "first_ts": first_ts.isoformat(),
        "last_ts": last_ts.isoformat(),
    }


async def backfill_recent(hours: int = 192) -> dict:
    """
    Bounded self-healing aggregation: (re)aggregate the last `hours` hours and
    the days they touch. Unlike aggregate_all_history (which scans ALL history
    and is slow), this covers just the recent window that the dashboards chart,
    so it is cheap enough to run at every startup. Idempotent.

    Default 192 h (8 days) covers the 7-day community-energy chart plus margin.

    Guarded by a MySQL advisory lock so that with uvicorn's 4 workers only ONE
    backfill runs at a time (concurrent runs race on the summary unique keys).
    """
    async with AsyncSessionLocal() as lockdb:
        got = (await lockdb.execute(text("SELECT GET_LOCK('ww_backfill', 0)"))).scalar()
        if not got:
            logger.info("Recent backfill skipped — another worker holds the lock")
            return {"skipped": True}
        try:
            now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
            start = now - timedelta(hours=hours)

            hours_processed = 0
            t = start + timedelta(hours=1)
            while t <= now + timedelta(hours=1):
                await aggregate_hourly(t)
                hours_processed += 1
                t += timedelta(hours=1)

            days_processed = 0
            d = start.date()
            today = datetime.utcnow().date()
            while d <= today:
                await aggregate_daily(d)
                days_processed += 1
                d += timedelta(days=1)

            logger.info("Recent backfill complete: %d hours, %d days", hours_processed, days_processed)
            return {"hours_processed": hours_processed, "days_processed": days_processed}
        finally:
            await lockdb.execute(text("SELECT RELEASE_LOCK('ww_backfill')"))
