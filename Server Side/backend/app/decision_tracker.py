"""
WattWise Decision Tracker
==========================
Tracks the energy impact of user decisions made after receiving notifications.
This is the core research contribution of the WattWise PhD project.

For each user decision recorded:
1. Capture energy usage BEFORE the decision (in a configurable time window)
2. After the window period, capture usage AFTER the decision
3. Calculate energy_saved_kwh, cost_saved_gbp, and effectiveness_score
4. Compute aggregate impact statistics for research analysis

What the window is measured on (`impact_scope`):
  device — the alert was about one device: that device's readings.
  home   — the alert was home-level (daily ceiling, admin message…): the sum over
           every active device of the user's home.
  none   — nothing to measure (no home/devices, or no readings in the window).

Simulated decisions (`is_simulated`) are never measured and are excluded from
every report unless a cohort that includes them is requested.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import UserDecision, Notification, Device, Home, User
from app.energy_analysis import EnergyAnalysisEngine

logger = logging.getLogger("decision_tracker")

DEFAULT_REMIND_MINUTES = 120
# Decision types that represent the user doing something (eligible for the fast-response bonus).
ACTION_TYPES = ("ACCEPTED", "CUSTOM_ACTION")


def effectiveness_score(
    energy_before: float,
    energy_saved: float,
    decision_type: str,
    response_time_seconds: Optional[int],
) -> float:
    """
    0–100. Share of the "before" energy that was saved, plus a small bonus for acting
    quickly. The bonus only applies when the user actually acted and energy fell — a
    fast "Skip" earns nothing.
    """
    score = 0.0
    if energy_before > 0:
        score = max(0.0, min(100.0, (energy_saved / energy_before) * 100))
    if decision_type in ACTION_TYPES and energy_saved > 0 and response_time_seconds is not None:
        if response_time_seconds < 300:
            score = min(100.0, score + 10)
        elif response_time_seconds < 1800:
            score = min(100.0, score + 5)
    return round(score, 1)


class DecisionTracker:

    # ── Energy windows ────────────────────────────────────────

    @staticmethod
    async def _home_for(db: AsyncSession, user_id: int, notification: Optional[Notification]) -> Optional[int]:
        """The home a home-level decision is measured on: the alert's home, else the user's first active home."""
        if notification is not None and notification.home_id:
            return notification.home_id
        return (await db.execute(
            select(Home.id).where(Home.user_id == user_id, Home.is_active.is_(True)).order_by(Home.id).limit(1)
        )).scalar_one_or_none()

    @staticmethod
    async def _window_kwh(
        db: AsyncSession, scope: str, device_id: Optional[int], home_id: Optional[int],
        start: datetime, end: datetime,
    ) -> Optional[float]:
        """kWh in [start, end] for a device or a whole home. None when there are no readings at all."""
        if scope == "device" and device_id:
            device_ids = [device_id]
        elif scope == "home" and home_id:
            device_ids = list((await db.execute(
                select(Device.id).where(Device.home_id == home_id, Device.is_active.is_(True))
            )).scalars().all())
        else:
            return None

        total, seen = 0.0, False
        for did in device_ids:
            readings = await EnergyAnalysisEngine.get_device_readings_range(db, did, start, end)
            if readings:
                seen = True
                total += EnergyAnalysisEngine.detect_usage_cycles(readings)["total_kwh"]
        return round(total, 4) if seen else None

    # ── Record a New Decision ─────────────────────────────────

    @staticmethod
    async def record_decision(
        db: AsyncSession,
        user_id: int,
        notification_id: int,
        decision_type: str,
        action_taken: Optional[str] = None,
        device_id: Optional[int] = None,
        user_feedback_text: Optional[str] = None,
        user_satisfaction: Optional[int] = None,
        remind_in_minutes: Optional[int] = None,
    ) -> UserDecision:
        """
        Create a new UserDecision record.
        The energy impact is calculated later by calculate_impact_for_pending_decisions().
        """
        now = datetime.utcnow()
        notification = (await db.execute(
            select(Notification).where(Notification.id == notification_id)
        )).scalar_one_or_none()
        notification_sent_at = notification.created_at if notification else None
        response_time_seconds = int((now - notification_sent_at).total_seconds()) if notification_sent_at else None

        scope, energy_before = await DecisionTracker._measure_before(db, user_id, notification, device_id, now)

        decision = UserDecision(
            user_id=user_id,
            notification_id=notification_id,
            device_id=device_id,
            decision_type=decision_type,
            action_taken=action_taken,
            action_timestamp=now,
            measure_window_hours=settings.DECISION_MEASURE_WINDOW_HOURS,
            energy_before_kwh=energy_before,
            notification_sent_at=notification_sent_at,
            response_time_seconds=response_time_seconds,
            user_feedback_text=user_feedback_text,
            user_satisfaction=user_satisfaction,
            impact_scope=scope,
            remind_at=(now + timedelta(minutes=remind_in_minutes or DEFAULT_REMIND_MINUTES))
            if decision_type == "DEFERRED" else None,
        )
        db.add(decision)
        await db.commit()
        await db.refresh(decision)

        logger.info(f"Decision recorded: user={user_id}, type={decision_type}, notification={notification_id}")
        return decision

    @staticmethod
    async def _measure_before(
        db: AsyncSession, user_id: int, notification: Optional[Notification],
        device_id: Optional[int], at: datetime,
    ) -> tuple[str, Optional[float]]:
        """Pick the measurement scope and capture the "before" window ending at `at`."""
        window_start = at - timedelta(hours=settings.DECISION_MEASURE_WINDOW_HOURS)
        if device_id:
            scope, home_id = "device", None
        else:
            home_id = await DecisionTracker._home_for(db, user_id, notification)
            scope = "home" if home_id else "none"
        if scope == "none":
            return "none", None
        before = await DecisionTracker._window_kwh(db, scope, device_id, home_id, window_start, at)
        if before is None:
            return "none", None
        return scope, before

    @staticmethod
    async def restart_measurement(db: AsyncSession, decision: UserDecision) -> None:
        """
        The user has now actually acted (e.g. a deferred alert marked done): the
        before/after window restarts at this moment and any earlier result is discarded.
        Does not commit.
        """
        now = datetime.utcnow()
        notification = None
        if decision.notification_id:
            notification = (await db.execute(
                select(Notification).where(Notification.id == decision.notification_id)
            )).scalar_one_or_none()
        scope, before = await DecisionTracker._measure_before(db, decision.user_id, notification, decision.device_id, now)
        decision.action_timestamp = now
        decision.impact_scope = scope
        decision.energy_before_kwh = before
        decision.energy_after_kwh = None
        decision.energy_saved_kwh = None
        decision.cost_saved_gbp = None
        decision.effectiveness_score = None
        decision.impact_calculated_at = None
        if decision.notification_sent_at:
            decision.response_time_seconds = int((now - decision.notification_sent_at).total_seconds())

    # ── Calculate Impact for Pending Decisions ────────────────

    @staticmethod
    async def calculate_impact_for_pending_decisions(db: AsyncSession) -> int:
        """
        Called by scheduler every 2 hours.
        Looks for decisions where the measurement window has elapsed
        but impact hasn't been calculated yet.
        Returns count of decisions processed.
        """
        processed = 0
        cutoff = datetime.utcnow() - timedelta(hours=settings.DECISION_MEASURE_WINDOW_HOURS)

        result = await db.execute(
            select(UserDecision).where(
                UserDecision.impact_calculated_at.is_(None),
                UserDecision.is_simulated.is_(False),
                UserDecision.action_timestamp < cutoff,
            ).order_by(UserDecision.action_timestamp).limit(100)
        )
        for decision in result.scalars().all():
            try:
                await DecisionTracker._calculate_single_impact(db, decision)
                processed += 1
            except Exception as e:
                await db.rollback()
                logger.error(f"Error calculating impact for decision {decision.id}: {e}")

        if processed:
            logger.info(f"Calculated impact for {processed} decisions")
        return processed

    @staticmethod
    async def _calculate_single_impact(db: AsyncSession, decision: UserDecision):
        """Calculate and persist energy impact for a single decision."""
        now = datetime.utcnow()
        scope = decision.impact_scope or ("device" if decision.device_id else "none")

        if scope == "none" or decision.energy_before_kwh is None:
            # Nothing measurable: close it so it is not re-examined every run.
            decision.impact_scope = "none"
            decision.impact_calculated_at = now
            await db.commit()
            return

        window_hours = decision.measure_window_hours or settings.DECISION_MEASURE_WINDOW_HOURS
        action_time = decision.action_timestamp
        window_end = min(action_time + timedelta(hours=window_hours), now)

        home_id = None
        if scope == "home":
            notification = None
            if decision.notification_id:
                notification = (await db.execute(
                    select(Notification).where(Notification.id == decision.notification_id)
                )).scalar_one_or_none()
            home_id = await DecisionTracker._home_for(db, decision.user_id, notification)

        after = await DecisionTracker._window_kwh(db, scope, decision.device_id, home_id, action_time, window_end)
        energy_after = after or 0.0
        energy_before = decision.energy_before_kwh or 0.0
        energy_saved = energy_before - energy_after

        decision.impact_scope = scope
        decision.energy_after_kwh = round(energy_after, 4)
        decision.energy_saved_kwh = round(energy_saved, 4)
        decision.cost_saved_gbp = round(energy_saved * settings.ENERGY_STANDARD_PRICE_PER_KWH, 4)
        decision.effectiveness_score = effectiveness_score(
            energy_before, energy_saved, decision.decision_type, decision.response_time_seconds
        )
        decision.impact_calculated_at = now
        await db.commit()
        logger.debug(
            f"Impact for decision {decision.id} ({scope}): saved={energy_saved:.4f} kWh, "
            f"effectiveness={decision.effectiveness_score:.1f}%"
        )

    # ── Reminders for deferred alerts ─────────────────────────

    @staticmethod
    async def send_due_reminders(db: AsyncSession) -> int:
        """
        "Later" means later: when remind_at passes and the decision is still DEFERRED,
        put a reminder in front of the user that links back to the original alert.
        """
        from app.notification_engine import NotificationEngine

        now = datetime.utcnow()
        due = (await db.execute(
            select(UserDecision, Notification)
            .join(Notification, Notification.id == UserDecision.notification_id)
            .where(
                UserDecision.decision_type == "DEFERRED",
                UserDecision.is_simulated.is_(False),
                UserDecision.remind_at.isnot(None),
                UserDecision.remind_at <= now,
                UserDecision.reminded_at.is_(None),
            ).limit(200)
        )).all()

        sent = 0
        for decision, notif in due:
            await NotificationEngine.create_notification(
                db, decision.user_id,
                title=f"⏰ Reminder: {notif.title}"[:256],
                message=f"You asked to be reminded about this alert. {notif.message}",
                notification_type="RECOMMENDATION",
                severity="INFO",
                home_id=notif.home_id,
                device_id=notif.device_id,
                action_hint="Open the original alert and mark it done or skip it",
                action_button_text="Open alert",
                requires_user_action=False,
                metadata={"reminder_for_notification_id": notif.id, "decision_id": decision.id},
                rule_key="decision_reminder",
                dedup_key=f"reminder:{decision.id}",
                dedup=False,
            )
            decision.reminded_at = now
            sent += 1
        if sent:
            await db.commit()
            logger.info("Sent %d deferred-alert reminders", sent)
        return sent

    # ── Aggregate Statistics ──────────────────────────────────

    @staticmethod
    async def get_user_impact_report(db: AsyncSession, user_id: int, include_simulated: bool = False) -> dict:
        """Return aggregate decision impact statistics for a user (real decisions only by default)."""
        q = select(
            func.count(UserDecision.id).label("total"),
            func.sum(case((UserDecision.decision_type == "ACCEPTED", 1), else_=0)).label("accepted"),
            func.sum(case((UserDecision.decision_type == "REJECTED", 1), else_=0)).label("rejected"),
            func.sum(case((UserDecision.decision_type == "DEFERRED", 1), else_=0)).label("deferred"),
            func.avg(UserDecision.response_time_seconds).label("avg_response"),
            func.sum(UserDecision.energy_saved_kwh).label("total_saved_kwh"),
            func.sum(UserDecision.cost_saved_gbp).label("total_saved_gbp"),
            func.avg(UserDecision.effectiveness_score).label("avg_effectiveness"),
            func.avg(UserDecision.user_satisfaction).label("avg_satisfaction"),
        ).where(UserDecision.user_id == user_id)
        if not include_simulated:
            q = q.where(UserDecision.is_simulated.is_(False))
        row = (await db.execute(q)).one()

        return {
            "total_decisions": row.total or 0,
            "accepted": int(row.accepted or 0),
            "rejected": int(row.rejected or 0),
            "deferred": int(row.deferred or 0),
            "avg_response_time_seconds": round(float(row.avg_response), 1) if row.avg_response is not None else None,
            "total_energy_saved_kwh": round(float(row.total_saved_kwh), 3) if row.total_saved_kwh else 0.0,
            "total_cost_saved_gbp": round(float(row.total_saved_gbp), 2) if row.total_saved_gbp else 0.0,
            "avg_effectiveness_score": round(float(row.avg_effectiveness), 1) if row.avg_effectiveness is not None else None,
            "avg_satisfaction": round(float(row.avg_satisfaction), 1) if row.avg_satisfaction is not None else None,
        }

    @staticmethod
    async def get_system_impact_report(db: AsyncSession, cohort: str = "real") -> dict:
        """System-wide decision impact statistics for admin, for one cohort (see app.cohorts)."""
        from app.cohorts import user_cohort_clause, decision_cohort_clause

        q = select(
            func.count(UserDecision.id).label("total"),
            func.sum(case((UserDecision.decision_type == "ACCEPTED", 1), else_=0)).label("accepted"),
            func.sum(case((UserDecision.decision_type == "REJECTED", 1), else_=0)).label("rejected"),
            func.sum(case((UserDecision.decision_type == "DEFERRED", 1), else_=0)).label("deferred"),
            func.sum(case((UserDecision.decision_type == "CUSTOM_ACTION", 1), else_=0)).label("custom"),
            func.sum(case((UserDecision.impact_calculated_at.isnot(None), 1), else_=0)).label("measured"),
            func.sum(case((UserDecision.is_simulated.is_(True), 1), else_=0)).label("simulated"),
            func.sum(UserDecision.energy_saved_kwh).label("total_saved_kwh"),
            func.sum(UserDecision.cost_saved_gbp).label("total_saved_gbp"),
            func.avg(UserDecision.effectiveness_score).label("avg_effectiveness"),
            func.avg(UserDecision.response_time_seconds).label("avg_response"),
            func.avg(UserDecision.user_satisfaction).label("avg_satisfaction"),
            func.count(func.distinct(UserDecision.user_id)).label("users"),
        ).join(User, User.id == UserDecision.user_id)
        for clause in (user_cohort_clause(cohort), decision_cohort_clause(cohort)):
            if clause is not None:
                q = q.where(clause)
        row = (await db.execute(q)).one()

        return {
            "cohort": cohort,
            "total_decisions": row.total or 0,
            "accepted": int(row.accepted or 0),
            "rejected": int(row.rejected or 0),
            "deferred": int(row.deferred or 0),
            "custom_action": int(row.custom or 0),
            "measured": int(row.measured or 0),
            "simulated": int(row.simulated or 0),
            "users_with_decisions": int(row.users or 0),
            "total_energy_saved_kwh": round(float(row.total_saved_kwh), 3) if row.total_saved_kwh else 0.0,
            "total_cost_saved_gbp": round(float(row.total_saved_gbp), 2) if row.total_saved_gbp else 0.0,
            "avg_effectiveness_score": round(float(row.avg_effectiveness), 1) if row.avg_effectiveness is not None else None,
            "avg_response_time_seconds": round(float(row.avg_response), 1) if row.avg_response is not None else None,
            "avg_satisfaction": round(float(row.avg_satisfaction), 1) if row.avg_satisfaction is not None else None,
        }
