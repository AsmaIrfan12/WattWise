"""
WattWise Scheduler
==================
APScheduler jobs for automated energy aggregation, goal checking,
notification delivery, ranking computation, and decision impact tracking.
"""

import logging
from datetime import datetime, timedelta, date

from sqlalchemy import select, func

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

async def compute_rankings():
    """Called daily at 01:30. Computes energy efficiency rankings for all users."""
    logger.info("Computing community rankings...")
    yesterday = (datetime.utcnow() - timedelta(days=1)).date()

    async with AsyncSessionLocal() as db:
        # Get all homes with data yesterday
        result = await db.execute(
            select(HomeDailyTotal, Home).join(Home, HomeDailyTotal.home_id == Home.id)
            .where(HomeDailyTotal.day_date == yesterday)
            .order_by(HomeDailyTotal.total_kwh.asc())  # Lower usage = better
        )
        rows = result.all()
        total_users = len(rows)

        for rank, (hdt, home) in enumerate(rows, start=1):
            try:
                # Efficiency score: based on kWh per occupant
                home_result = await db.execute(select(Home).where(Home.id == home.id))
                home_obj = home_result.scalar_one_or_none()
                occupants = max(home_obj.num_occupants or 1, 1)
                kwh_per_person = hdt.total_kwh / occupants

                # Score: 100 for 0 kWh/person, drops linearly per 5 kWh/person
                eff_score = max(0.0, 100.0 - (kwh_per_person * 10))

                # Goal adherence score
                user_result = await db.execute(select(User).where(User.id == home.user_id))
                user = user_result.scalar_one_or_none()
                daily_goal = user.daily_energy_goal_kwh if user else None
                if daily_goal and daily_goal > 0:
                    adherence = max(0.0, min(100.0, (daily_goal / max(hdt.total_kwh, 0.001)) * 100))
                else:
                    adherence = 70.0  # Default if no goal set

                # Decision response score (from yesterday's decisions)
                from app.models import UserDecision
                dec_result = await db.execute(
                    select(func.avg(UserDecision.effectiveness_score)).where(
                        UserDecision.user_id == home.user_id,
                        func.date(UserDecision.created_at) == yesterday,
                    )
                )
                avg_decision_score = dec_result.scalar() or 70.0

                overall = (eff_score * 0.4 + adherence * 0.35 + float(avg_decision_score) * 0.25)
                percentile = ((total_users - rank) / max(total_users - 1, 1)) * 100

                # Upsert ranking
                existing = await db.execute(
                    select(EnergyRanking).where(
                        EnergyRanking.user_id == home.user_id,
                        EnergyRanking.period_type == "DAILY",
                        EnergyRanking.period_start == yesterday,
                    )
                )
                ranking = existing.scalar_one_or_none()
                if ranking:
                    ranking.overall_score = round(overall, 1)
                    ranking.rank_position = rank
                    ranking.total_users = total_users
                    ranking.percentile = round(percentile, 1)
                    ranking.efficiency_score = round(eff_score, 1)
                    ranking.goal_adherence_score = round(adherence, 1)
                    ranking.decision_response_score = round(float(avg_decision_score), 1)
                    ranking.total_kwh = hdt.total_kwh
                    ranking.total_cost_gbp = hdt.total_cost_gbp
                else:
                    ranking = EnergyRanking(
                        user_id=home.user_id,
                        home_id=home.id,
                        period_type="DAILY",
                        period_start=yesterday,
                        overall_score=round(overall, 1),
                        rank_position=rank,
                        total_users=total_users,
                        percentile=round(percentile, 1),
                        efficiency_score=round(eff_score, 1),
                        goal_adherence_score=round(adherence, 1),
                        decision_response_score=round(float(avg_decision_score), 1),
                        total_kwh=hdt.total_kwh,
                        total_cost_gbp=hdt.total_cost_gbp,
                    )
                    db.add(ranking)

            except Exception as e:
                logger.error(f"Ranking error for home {home.id}: {e}")

        await db.commit()
    logger.info(f"Rankings computed for {total_users} homes")


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
