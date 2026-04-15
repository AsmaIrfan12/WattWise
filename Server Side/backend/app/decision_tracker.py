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
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import UserDecision, Notification, EnergyReading, Device
from app.energy_analysis import EnergyAnalysisEngine

logger = logging.getLogger("decision_tracker")


class DecisionTracker:

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
    ) -> UserDecision:
        """
        Create a new UserDecision record.
        The energy impact is calculated later by calculate_impact_for_pending_decisions().
        """
        # Look up when the notification was sent
        notif_result = await db.execute(
            select(Notification).where(Notification.id == notification_id)
        )
        notification = notif_result.scalar_one_or_none()
        notification_sent_at = notification.created_at if notification else None

        # Calculate response time
        response_time_seconds = None
        if notification_sent_at:
            delta = datetime.utcnow() - notification_sent_at
            response_time_seconds = int(delta.total_seconds())

        # Capture "before" energy immediately
        energy_before = None
        if device_id:
            window_hours = settings.DECISION_MEASURE_WINDOW_HOURS
            window_start = datetime.utcnow() - timedelta(hours=window_hours)
            readings = await EnergyAnalysisEngine.get_device_readings_range(
                db, device_id, window_start, datetime.utcnow()
            )
            if readings:
                stats = EnergyAnalysisEngine.detect_usage_cycles(readings)
                energy_before = stats["total_kwh"]

        decision = UserDecision(
            user_id=user_id,
            notification_id=notification_id,
            device_id=device_id,
            decision_type=decision_type,
            action_taken=action_taken,
            action_timestamp=datetime.utcnow(),
            measure_window_hours=settings.DECISION_MEASURE_WINDOW_HOURS,
            energy_before_kwh=energy_before,
            notification_sent_at=notification_sent_at,
            response_time_seconds=response_time_seconds,
            user_feedback_text=user_feedback_text,
            user_satisfaction=user_satisfaction,
        )
        db.add(decision)
        await db.commit()
        await db.refresh(decision)

        logger.info(f"Decision recorded: user={user_id}, type={decision_type}, notification={notification_id}")
        return decision

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
        cutoff = datetime.utcnow()

        result = await db.execute(
            select(UserDecision).where(
                UserDecision.impact_calculated_at.is_(None),
                UserDecision.energy_before_kwh.isnot(None),
                # Window elapsed: action_time + window_hours < now
                UserDecision.action_timestamp < cutoff - timedelta(hours=settings.DECISION_MEASURE_WINDOW_HOURS)
            ).limit(50)
        )
        decisions = result.scalars().all()

        for decision in decisions:
            try:
                await DecisionTracker._calculate_single_impact(db, decision)
                processed += 1
            except Exception as e:
                logger.error(f"Error calculating impact for decision {decision.id}: {e}")

        if processed:
            logger.info(f"Calculated impact for {processed} decisions")
        return processed

    @staticmethod
    async def _calculate_single_impact(db: AsyncSession, decision: UserDecision):
        """Calculate and persist energy impact for a single decision."""
        if not decision.device_id:
            # No device → can't measure impact
            decision.impact_calculated_at = datetime.utcnow()
            decision.effectiveness_score = None
            await db.commit()
            return

        window_hours = decision.measure_window_hours or settings.DECISION_MEASURE_WINDOW_HOURS
        action_time = decision.action_timestamp
        window_end = action_time + timedelta(hours=window_hours)

        # Fetch "after" readings
        after_readings = await EnergyAnalysisEngine.get_device_readings_range(
            db, decision.device_id, action_time, min(window_end, datetime.utcnow())
        )

        energy_after = 0.0
        if after_readings:
            after_stats = EnergyAnalysisEngine.detect_usage_cycles(after_readings)
            energy_after = after_stats["total_kwh"]

        energy_before = decision.energy_before_kwh or 0.0
        energy_saved = energy_before - energy_after
        cost_saved = energy_saved * settings.ENERGY_STANDARD_PRICE_PER_KWH

        # Effectiveness score: 0-100
        # 100 = saved all energy from before, 0 = no change, can go negative
        effectiveness = 0.0
        if energy_before > 0:
            effectiveness = max(0.0, min(100.0, (energy_saved / energy_before) * 100))

        # Bonus for fast response
        if decision.response_time_seconds is not None:
            if decision.response_time_seconds < 300:  # < 5 min
                effectiveness = min(100.0, effectiveness + 10)
            elif decision.response_time_seconds < 1800:  # < 30 min
                effectiveness = min(100.0, effectiveness + 5)

        decision.energy_after_kwh = round(energy_after, 4)
        decision.energy_saved_kwh = round(energy_saved, 4)
        decision.cost_saved_gbp = round(cost_saved, 4)
        decision.effectiveness_score = round(effectiveness, 1)
        decision.impact_calculated_at = datetime.utcnow()

        await db.commit()
        logger.debug(
            f"Impact for decision {decision.id}: saved={energy_saved:.4f} kWh, "
            f"effectiveness={effectiveness:.1f}%"
        )

    # ── Aggregate Statistics ──────────────────────────────────

    @staticmethod
    async def get_user_impact_report(db: AsyncSession, user_id: int) -> dict:
        """Return aggregate decision impact statistics for a user."""

        result = await db.execute(
            select(
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
        )
        row = result.one()

        return {
            "total_decisions": row.total or 0,
            "accepted": row.accepted or 0,
            "rejected": row.rejected or 0,
            "deferred": row.deferred or 0,
            "avg_response_time_seconds": round(float(row.avg_response), 1) if row.avg_response else None,
            "total_energy_saved_kwh": round(float(row.total_saved_kwh), 3) if row.total_saved_kwh else 0.0,
            "total_cost_saved_gbp": round(float(row.total_saved_gbp), 2) if row.total_saved_gbp else 0.0,
            "avg_effectiveness_score": round(float(row.avg_effectiveness), 1) if row.avg_effectiveness else None,
            "avg_satisfaction": round(float(row.avg_satisfaction), 1) if row.avg_satisfaction else None,
        }

    @staticmethod
    async def get_system_impact_report(db: AsyncSession) -> dict:
        """Return system-wide decision impact statistics for admin."""
        result = await db.execute(
            select(
                func.count(UserDecision.id).label("total"),
                func.sum(UserDecision.energy_saved_kwh).label("total_saved_kwh"),
                func.sum(UserDecision.cost_saved_gbp).label("total_saved_gbp"),
                func.avg(UserDecision.effectiveness_score).label("avg_effectiveness"),
                func.avg(UserDecision.response_time_seconds).label("avg_response"),
            )
        )
        row = result.one()

        return {
            "total_decisions": row.total or 0,
            "total_energy_saved_kwh": round(float(row.total_saved_kwh), 3) if row.total_saved_kwh else 0.0,
            "total_cost_saved_gbp": round(float(row.total_saved_gbp), 2) if row.total_saved_gbp else 0.0,
            "avg_effectiveness_score": round(float(row.avg_effectiveness), 1) if row.avg_effectiveness else None,
            "avg_response_time_seconds": round(float(row.avg_response), 1) if row.avg_response else None,
        }
