"""
WattWise Notification Engine
=============================
Generates, sends, and manages notifications for the WattWise platform.

Notification types:
- Automated energy alerts (scheduler-driven)
- Admin broadcasts (manual or template-based)
- Achievement notifications (goal met, streak achieved)
- Daily/weekly/monthly reports

Push delivery: Expo Push API (compatible with React Native / Expo apps)
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
import httpx

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.health_tips import HEALTH_TIP_LABEL, pick_health_tip, with_health_tip
from app.models import (
    User, Notification, Device, Home, DailySummary, HomeDailyTotal, EnergyGoal, NotificationCampaign,
)

logger = logging.getLogger("notification_engine")

# Deduplication window: don't send same notification type to same user within this period
DEDUP_WINDOW_HOURS = 12


def default_dedup_key(notification_type: str, device_id: Optional[int]) -> str:
    """One alert of a given type per device (or per home-level slot) per dedup window."""
    return f"{notification_type}:{device_id if device_id is not None else 'home'}"


class NotificationEngine:

    # ── Create & Send ─────────────────────────────────────────

    @staticmethod
    async def create_notification(
        db: AsyncSession,
        user_id: int,
        title: str,
        message: str,
        notification_type: str,
        severity: str = "INFO",
        home_id: Optional[int] = None,
        device_id: Optional[int] = None,
        action_hint: Optional[str] = None,
        action_button_text: Optional[str] = None,
        requires_user_action: bool = False,
        metadata: Optional[dict] = None,
        expires_hours: int = 48,
        send_push: bool = True,
        source: str = "AUTOMATED",
        rule_key: Optional[str] = None,
        campaign_id: Optional[int] = None,
        dedup_key: Optional[str] = None,
        dedup: bool = True,
    ) -> Optional[Notification]:
        """
        Create a notification record and optionally deliver via push.

        Deduplication (dedup=True): at most one notification per user per `dedup_key`
        within DEDUP_WINDOW_HOURS. The default key is "<type>:<device_id>", i.e. the
        historical behaviour. Callers that have their own idempotency (goal
        milestones) or must never be dropped (admin sends) pass dedup=False.
        Returns None when the notification was suppressed as a duplicate.
        """
        dedup_key = dedup_key or default_dedup_key(notification_type, device_id)
        if dedup:
            dedup_since = datetime.utcnow() - timedelta(hours=DEDUP_WINDOW_HOURS)
            duplicate = (await db.execute(
                select(Notification.id).where(
                    Notification.user_id == user_id,
                    Notification.dedup_key == dedup_key,
                    Notification.created_at >= dedup_since,
                ).limit(1)
            )).scalar_one_or_none()
            if duplicate is None:
                # Rows created before dedup_key existed: fall back to the old match.
                duplicate = (await db.execute(
                    select(Notification.id).where(
                        Notification.user_id == user_id,
                        Notification.dedup_key.is_(None),
                        Notification.notification_type == notification_type,
                        Notification.device_id == device_id,
                        Notification.created_at >= dedup_since,
                    ).limit(1)
                )).scalar_one_or_none()
            if duplicate is not None:
                logger.debug(f"Skipping duplicate {dedup_key} for user {user_id}")
                return None

        # Health tip: every automated alert about a device ends with one, as in the
        # original app. Scenario alerts arrive with the tip for their scenario already in
        # the text; the others (unusual usage, device goals, standby) get a general tip
        # for the appliance here, rotated daily. The two parts are also kept separately.
        if (source == "AUTOMATED" and device_id is not None
                and not (metadata or {}).get("health_tip") and HEALTH_TIP_LABEL not in message):
            try:
                appliance_key = (metadata or {}).get("appliance_key")
                if not appliance_key:
                    appliance_key = (await db.execute(
                        select(Device.appliance_key).where(Device.id == device_id)
                    )).scalar_one_or_none()
                if isinstance(appliance_key, str) and appliance_key:
                    seed = datetime.utcnow().timetuple().tm_yday + int(device_id)
                    tip = pick_health_tip(appliance_key, seed)
                    metadata = {**(metadata or {}), "health_tip": tip, "energy_message": message}
                    message = with_health_tip(message, tip)
            except Exception as e:  # a tip must never stop an alert from being delivered
                logger.warning("Health tip not attached to alert for device %s: %s", device_id, e)

        # Create notification record
        notif = Notification(
            user_id=user_id,
            home_id=home_id,
            device_id=device_id,
            notification_type=notification_type,
            severity=severity,
            title=title,
            message=message,
            action_hint=action_hint,
            action_button_text=action_button_text,
            requires_user_action=requires_user_action,
            metadata_json=metadata,
            expires_at=datetime.utcnow() + timedelta(hours=expires_hours),
            source=source,
            rule_key=rule_key,
            campaign_id=campaign_id,
            dedup_key=dedup_key,
        )
        db.add(notif)
        await db.commit()
        await db.refresh(notif)

        # Send push notification if user has a token
        if send_push:
            user_result = await db.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()
            if user and user.push_token and user.notifications_enabled:
                receipt_id = await NotificationEngine._send_expo_push(
                    push_token=user.push_token,
                    title=title,
                    body=message,
                    data={
                        "notification_id": notif.id,
                        "notification_type": notification_type,
                        "device_id": device_id,
                        "requires_action": requires_user_action,
                        "severity": severity,
                    }
                )
                notif.sent_via_push = receipt_id is not None
                notif.push_receipt_id = receipt_id
                notif.sent_at = datetime.utcnow()
                await db.commit()

        return notif

    @staticmethod
    async def _send_expo_push(
        push_token: str, title: str, body: str, data: dict = {}
    ) -> Optional[str]:
        """Send a single push notification via Expo Push API. Returns receipt ID or None."""
        receipts = await NotificationEngine._send_expo_push_bulk(
            [{"push_token": push_token, "title": title, "body": body, "data": data}]
        )
        return receipts[0] if receipts else None

    @staticmethod
    async def _send_expo_push_bulk(messages: list[dict]) -> list[Optional[str]]:
        """
        Send multiple push notifications in one Expo Push API call.

        Each message dict should contain: push_token, title, body, data.
        Returns a list of receipt IDs aligned positionally with the input
        (None entries for failed deliveries). Expo accepts up to 100 messages
        per request, so this method automatically chunks larger batches.

        Ported from old PushNotificationService.sendBulkNotifications —
        cuts 50× round-trip overhead vs sending one-at-a-time.
        """
        if not messages:
            return []

        receipts: list[Optional[str]] = []

        def _build_payload(m: dict) -> dict:
            data = m.get("data") or {}
            severity = data.get("severity")
            channel = "energy-alerts" if severity in ("ALERT", "CRITICAL") else "energy-info"
            unique_tag = f"{data.get('applianceKey') or data.get('notification_type') or 'wattwise'}-{int(datetime.utcnow().timestamp() * 1000)}"
            data_with_id = {**data, "notificationId": unique_tag}
            return {
                "to": m["push_token"],
                "sound": "default",
                "title": m["title"],
                "body": m["body"],
                "data": data_with_id,
                "priority": "high",
                "channelId": channel,
                "android": {"channelId": channel, "priority": "high", "tag": unique_tag},
                "ios": {"_displayInForeground": True},
            }

        # Expo Push API accepts up to 100 messages per call
        chunk_size = 100
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                for i in range(0, len(messages), chunk_size):
                    chunk = messages[i:i + chunk_size]
                    payload = [_build_payload(m) for m in chunk]
                    try:
                        resp = await client.post(
                            settings.EXPO_PUSH_URL,
                            json=payload,
                            headers={"Content-Type": "application/json", "Accept": "application/json"},
                        )
                        resp.raise_for_status()
                        result = resp.json()
                        # Expo bulk responses come back as { "data": [ {status, id|message}, ... ] }
                        items = result.get("data", []) if isinstance(result, dict) else []
                        for item in items:
                            if isinstance(item, dict) and item.get("status") == "ok":
                                receipts.append(item.get("id"))
                            else:
                                receipts.append(None)
                        # Pad with None if Expo returned fewer entries than expected
                        while len(receipts) < (i + len(chunk)):
                            receipts.append(None)
                    except Exception as exc:
                        logger.warning("Bulk push chunk failed (i=%s, n=%s): %s", i, len(chunk), exc)
                        receipts.extend([None] * len(chunk))
        except Exception as exc:
            logger.warning("Bulk push failed entirely: %s", exc)
            return [None] * len(messages)

        return receipts

    # ── Automated Notification Generators ────────────────────

    @staticmethod
    async def check_daily_goal_notifications(db: AsyncSession):
        """
        Hourly goal check. Two independent rules:

        1. Whole-home daily ceiling — the user's `daily_energy_goal_kwh` (or the
           system ENERGY_DAILY_WARNING_KWH default) against today's home total.
        2. Goals the user created in the app (energy_goals: daily / weekly /
           monthly, per device or whole home). For the current goal period:
             • >= GOAL_WARNING_PERCENT of target  → GOAL_WARNING (once per period)
             • >= 100 % of target                → ENERGY_ALERT  (once per period)
             • previous period finished under target → GOAL_MET (once per period)

        Notifications are in-app first; push is attempted only when the user
        has registered a push token (see create_notification).
        """
        logger.info("Checking goal notifications...")
        today = datetime.utcnow().date()

        users_result = await db.execute(select(User).where(User.notifications_enabled.is_(True)))
        users = users_result.scalars().all()

        for user in users:
            try:
                homes_result = await db.execute(select(Home).where(Home.user_id == user.id, Home.is_active.is_(True)))
                homes = homes_result.scalars().all()

                # ── Rule 1: whole-home daily ceiling ────────────────────
                for home in homes:
                    total_result = await db.execute(
                        select(HomeDailyTotal).where(HomeDailyTotal.home_id == home.id, HomeDailyTotal.day_date == today)
                    )
                    today_total = total_result.scalar_one_or_none()
                    today_kwh = today_total.total_kwh if today_total else 0.0
                    daily_goal = user.daily_energy_goal_kwh or settings.ENERGY_DAILY_WARNING_KWH

                    if daily_goal * 1.0 <= today_kwh < daily_goal * 1.2:
                        await NotificationEngine.create_notification(
                            db, user.id,
                            title="⚡ Daily Energy Goal Reached",
                            message=f"You've used {today_kwh:.1f} kWh today — you've hit your daily target of {daily_goal:.1f} kWh. Try to keep usage steady for the rest of the day.",
                            notification_type="GOAL_WARNING",
                            severity="WARNING",
                            home_id=home.id,
                            rule_key="daily_ceiling", dedup_key=f"daily_ceiling:{home.id}:reached",
                            action_hint="Consider turning off non-essential devices",
                            action_button_text="View Usage",
                            requires_user_action=True,
                        )
                    elif today_kwh >= daily_goal * 1.2:
                        await NotificationEngine.create_notification(
                            db, user.id,
                            title="🚨 Daily Energy Goal Exceeded",
                            message=f"You've used {today_kwh:.1f} kWh today — {((today_kwh/daily_goal - 1)*100):.0f}% over your target. Act now to reduce usage!",
                            notification_type="ENERGY_ALERT",
                            severity="ALERT",
                            home_id=home.id,
                            rule_key="daily_ceiling", dedup_key=f"daily_ceiling:{home.id}:exceeded",
                            action_hint="Turn off high-consumption appliances",
                            action_button_text="Take Action",
                            requires_user_action=True,
                        )

                # ── Rule 2: user-created goals (energy_goals) ───────────
                goals = (await db.execute(
                    select(EnergyGoal).where(
                        EnergyGoal.user_id == user.id,
                        EnergyGoal.is_active.is_(True),
                        EnergyGoal.start_date <= today,
                    )
                )).scalars().all()

                for goal in goals:
                    if goal.end_date and goal.end_date < today:
                        continue
                    if not goal.target_kwh or goal.target_kwh <= 0:
                        continue
                    await NotificationEngine._notify_goal_milestones(db, user, goal, today)
            except Exception as e:
                logger.error(f"Error in goal notifications for user {user.id}: {e}")

    @staticmethod
    async def _goal_milestone_already_sent(db: AsyncSession, user_id: int, goal_id: int, milestone: str, period_start) -> bool:
        """True if a notification for this goal/milestone/period already exists (hourly runs must be idempotent)."""
        rows = (await db.execute(
            select(Notification.metadata_json).where(
                Notification.user_id == user_id,
                Notification.notification_type.in_(("GOAL_WARNING", "ENERGY_ALERT", "GOAL_MET")),
                Notification.created_at >= datetime.combine(period_start, datetime.min.time()) - timedelta(days=1),
            )
        )).all()
        for (meta,) in rows:
            if not meta:
                continue
            if (meta.get("goal_id") == goal_id and meta.get("milestone") == milestone
                    and meta.get("period_start") == str(period_start)):
                return True
        return False

    @staticmethod
    async def _notify_goal_milestones(db: AsyncSession, user, goal, today):
        from app.goal_tracker import evaluate_goal, previous_period_bounds, consumption_between

        device_name = None
        if goal.device_id:
            device = (await db.execute(select(Device).where(Device.id == goal.device_id))).scalar_one_or_none()
            device_name = device.name if device else "device"
        label = f"{goal.goal_type} {device_name} goal" if device_name else f"{goal.goal_type} home goal"
        period_word = {"daily": "today", "weekly": "this week", "monthly": "this month"}.get(goal.goal_type, "this period")

        progress = await evaluate_goal(db, goal, today)
        pct = progress["percentage_used"]
        period_start = progress["period_start"]
        target = progress["target_kwh"]
        used = progress["current_kwh"]
        days_left = progress["days_remaining"]
        base_meta = {
            "goal_id": goal.id, "device_id": goal.device_id,
            "period_start": str(period_start), "period_end": str(progress["period_end"]),
            "target_kwh": target, "current_kwh": used, "percentage_used": pct,
        }

        if pct >= 100:
            if not await NotificationEngine._goal_milestone_already_sent(db, user.id, goal.id, "exceeded", period_start):
                await NotificationEngine.create_notification(
                    db, user.id,
                    title=f"🚨 {label.capitalize()} exceeded",
                    message=(
                        f"You've used {used:.2f} kWh {period_word} against a target of {target:.2f} kWh "
                        f"({pct:.0f}%). {days_left} day(s) left in this period — reducing use now still "
                        f"counts towards your streak."
                    ),
                    notification_type="ENERGY_ALERT",
                    severity="ALERT",
                    device_id=goal.device_id,
                    action_hint="Open Goals to review this target",
                    action_button_text="View Goal",
                    requires_user_action=True,
                    metadata={**base_meta, "milestone": "exceeded"},
                    rule_key="goal_exceeded", dedup_key=f"goal:{goal.id}:exceeded:{period_start}", dedup=False,
                )
        elif pct >= settings.GOAL_WARNING_PERCENT:
            if not await NotificationEngine._goal_milestone_already_sent(db, user.id, goal.id, "warning", period_start):
                if progress["on_track"] or progress["projected_kwh"] is None:
                    outlook = "You're on track."
                else:
                    outlook = f"At this rate you'll reach about {progress['projected_kwh']:.2f} kWh — ease off to stay under target."
                await NotificationEngine.create_notification(
                    db, user.id,
                    title=f"⚡ {pct:.0f}% of your {label} used",
                    message=f"{used:.2f} of {target:.2f} kWh used {period_word}, with {days_left} day(s) to go. {outlook}",
                    notification_type="GOAL_WARNING",
                    severity="WARNING",
                    device_id=goal.device_id,
                    action_hint="Shift or shorten the next use of this appliance",
                    action_button_text="View Goal",
                    requires_user_action=True,
                    metadata={**base_meta, "milestone": "warning"},
                    rule_key="goal_warning", dedup_key=f"goal:{goal.id}:warning:{period_start}", dedup=False,
                )

        # Did the previous period finish under target? Celebrate once, within 2 days of it ending.
        prev = previous_period_bounds(goal.goal_type, goal.start_date, today)
        if prev and (today - prev[1]).days <= 2:
            prev_kwh, _ = await consumption_between(db, goal, prev[0], prev[1])
            if prev_kwh <= target and not await NotificationEngine._goal_milestone_already_sent(db, user.id, goal.id, "met", prev[0]):
                await NotificationEngine.create_notification(
                    db, user.id,
                    title=f"🏆 {label.capitalize()} achieved",
                    message=(
                        f"You finished {prev[0]:%d %b}–{prev[1]:%d %b} on {prev_kwh:.2f} kWh, under your "
                        f"{target:.2f} kWh target. Nice work — a new period has started."
                    ),
                    notification_type="GOAL_MET",
                    severity="INFO",
                    device_id=goal.device_id,
                    action_button_text="View Goals",
                    rule_key="goal_met", dedup_key=f"goal:{goal.id}:met:{prev[0]}", dedup=False,
                    metadata={
                        "goal_id": goal.id, "device_id": goal.device_id,
                        "period_start": str(prev[0]), "period_end": str(prev[1]),
                        "target_kwh": target, "current_kwh": round(prev_kwh, 3), "milestone": "met",
                    },
                )

    @staticmethod
    async def send_peak_tariff_reminder(db: AsyncSession):
        """
        Send peak tariff reminder 15 minutes before peak hours start (3:45 PM UK time).
        """
        logger.info("Sending peak tariff reminders...")
        users_result = await db.execute(select(User).where(User.notifications_enabled == True))
        users = users_result.scalars().all()

        for user in users:
            await NotificationEngine.create_notification(
                db, user.id,
                title="⏰ Peak Electricity in 15 Minutes",
                message="UK peak tariff starts at 4 PM (32p/kWh). Consider finishing high-energy tasks now and waiting until after 7 PM for non-urgent appliances.",
                notification_type="PEAK_TARIFF_REMINDER",
                severity="INFO",
                action_hint="Delay laundry, dishwasher, or dryer until after 7 PM",
                action_button_text="Set a Reminder",
                requires_user_action=False,
            )

    @staticmethod
    async def send_daily_summary(db: AsyncSession):
        """
        Send yesterday's energy summary to all users. Called daily at 7 AM.
        """
        yesterday = (datetime.utcnow() - timedelta(days=1)).date()

        users_result = await db.execute(select(User).where(User.notifications_enabled == True))
        users = users_result.scalars().all()

        for user in users:
            try:
                homes_result = await db.execute(select(Home).where(Home.user_id == user.id, Home.is_active == True))
                homes = homes_result.scalars().all()

                for home in homes:
                    total_result = await db.execute(
                        select(HomeDailyTotal).where(HomeDailyTotal.home_id == home.id, HomeDailyTotal.day_date == yesterday)
                    )
                    total = total_result.scalar_one_or_none()
                    if not total:
                        continue

                    kwh = total.total_kwh
                    cost = total.total_cost_gbp
                    goal = user.daily_energy_goal_kwh
                    goal_text = f" (goal: {goal:.1f} kWh)" if goal else ""

                    await NotificationEngine.create_notification(
                        db, user.id,
                        title="📊 Yesterday's Energy Summary",
                        message=f"You used {kwh:.2f} kWh{goal_text} costing £{cost:.2f}. Open the app for a full breakdown.",
                        notification_type="DAILY_SUMMARY",
                        severity="INFO",
                        home_id=home.id,
                        metadata={"kwh": kwh, "cost_gbp": cost, "date": str(yesterday)},
                        expires_hours=24,
                    )
            except Exception as e:
                logger.error(f"Error sending daily summary for user {user.id}: {e}")

    # ── Admin Broadcast ───────────────────────────────────────

    @staticmethod
    async def resolve_campaign_recipients(
        db: AsyncSession,
        user_ids: Optional[list[int]] = None,
        home_ids: Optional[list[int]] = None,
        target_persona_id: Optional[int] = None,
        cohort: str = "all",
    ) -> list[User]:
        """
        Who an admin send goes to. Precedence: user_ids > home_ids > persona > everyone.
        Admin accounts never receive campaigns. `cohort` narrows persona/everyone sends
        to real or synthetic users.
        """
        q = select(User).where(User.is_admin.is_(False))
        if user_ids:
            q = q.where(User.id.in_(user_ids))
        elif home_ids:
            q = q.where(User.id.in_(select(Home.user_id).where(Home.id.in_(home_ids))))
        else:
            if target_persona_id is not None:
                q = q.where(User.persona_id == target_persona_id)
            if cohort == "real":
                q = q.where(User.is_synthetic.is_(False))
            elif cohort == "synthetic":
                q = q.where(User.is_synthetic.is_(True))
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def send_campaign(db: AsyncSession, campaign: NotificationCampaign) -> int:
        """
        Deliver a campaign: one notification per recipient, never deduplicated (an admin
        send must arrive), tagged with the campaign so responses can be traced back.
        Returns the number of notifications actually created.
        """
        target = campaign.target_json or {}
        users = await NotificationEngine.resolve_campaign_recipients(
            db,
            user_ids=target.get("user_ids"),
            home_ids=target.get("home_ids"),
            target_persona_id=target.get("target_persona_id"),
            cohort=target.get("cohort", "all"),
        )
        appliance_key = target.get("appliance_key")
        home_filter = target.get("home_ids")

        created = 0
        for user in users:
            homes_q = select(Home).where(Home.user_id == user.id, Home.is_active.is_(True)).order_by(Home.id)
            if home_filter:
                homes_q = homes_q.where(Home.id.in_(home_filter))
            home = (await db.execute(homes_q.limit(1))).scalar_one_or_none()

            # Attach a device so the response's energy impact is measurable on it.
            device_id = None
            if appliance_key and home:
                device_id = (await db.execute(
                    select(Device.id).where(
                        Device.home_id == home.id, Device.appliance_key == appliance_key, Device.is_active.is_(True)
                    ).order_by(Device.id).limit(1)
                )).scalar_one_or_none()
                if device_id is None:
                    continue  # this home has no such appliance — the alert would not apply

            notif = await NotificationEngine.create_notification(
                db, user.id,
                title=campaign.title,
                message=campaign.message,
                notification_type=campaign.notification_type,
                severity=campaign.severity,
                home_id=home.id if home else None,
                device_id=device_id,
                action_hint=campaign.action_hint,
                action_button_text=campaign.action_button_text,
                requires_user_action=campaign.requires_user_action,
                metadata={"campaign_id": campaign.id},
                expires_hours=7 * 24,
                send_push=True,
                source="ADMIN",
                rule_key="admin_campaign",
                campaign_id=campaign.id,
                dedup_key=f"campaign:{campaign.id}",
                dedup=False,
            )
            if notif:
                created += 1

        campaign.status = "SENT"
        campaign.sent_at = datetime.utcnow()
        campaign.recipients_targeted = len(users)
        campaign.notifications_created = created
        await db.commit()
        logger.info("Campaign %s '%s': %d targeted, %d created", campaign.id, campaign.title, len(users), created)
        return created

    @staticmethod
    async def admin_broadcast(
        db: AsyncSession,
        title: str,
        message: str,
        notification_type: str = "ADMIN_BROADCAST",
        severity: str = "INFO",
        action_hint: Optional[str] = None,
        action_button_text: Optional[str] = None,
        requires_user_action: bool = False,
        user_ids: Optional[list[int]] = None,
        target_persona_id: Optional[int] = None,
        home_ids: Optional[list[int]] = None,
        cohort: str = "all",
        appliance_key: Optional[str] = None,
        send_at: Optional[datetime] = None,
        created_by: Optional[int] = None,
    ) -> NotificationCampaign:
        """
        Record an admin send as a campaign and deliver it (or leave it SCHEDULED when
        send_at is in the future — the scheduler's campaign job delivers it then).
        Returns the campaign; `notifications_created` is the true number delivered.
        """
        scheduled = bool(send_at and send_at > datetime.utcnow() + timedelta(seconds=30))
        campaign = NotificationCampaign(
            created_by=created_by,
            title=title,
            message=message,
            notification_type=notification_type,
            severity=severity,
            requires_user_action=requires_user_action,
            action_hint=action_hint,
            action_button_text=action_button_text,
            target_json={
                "user_ids": user_ids or None,
                "home_ids": home_ids or None,
                "target_persona_id": target_persona_id,
                "cohort": cohort,
                "appliance_key": appliance_key or None,
            },
            status="SCHEDULED" if scheduled else "SENT",
            send_at=send_at if scheduled else None,
        )
        db.add(campaign)
        await db.commit()
        await db.refresh(campaign)
        if not scheduled:
            await NotificationEngine.send_campaign(db, campaign)
            await db.refresh(campaign)
        return campaign

    @staticmethod
    async def dispatch_due_campaigns(db: AsyncSession) -> int:
        """Send every SCHEDULED campaign whose send_at has passed. Called every minute."""
        due = (await db.execute(
            select(NotificationCampaign).where(
                NotificationCampaign.status == "SCHEDULED",
                NotificationCampaign.send_at <= datetime.utcnow(),
            ).order_by(NotificationCampaign.send_at)
        )).scalars().all()
        for campaign in due:
            try:
                await NotificationEngine.send_campaign(db, campaign)
            except Exception as e:
                logger.error("Scheduled campaign %s failed: %s", campaign.id, e)
        return len(due)

    # ── Smart Device Scenario Notifications ───────────────────

    @staticmethod
    async def check_device_scenario_notifications(db: AsyncSession):
        """
        Called every 2 hours by the scheduler.
        Runs the appliance scenarios engine for all active users and their devices.
        Fetches real room environmental conditions from InfluxDB where available.
        Only sends CRITICAL and WARNING alerts to prevent notification fatigue.
        Deduplication (12-hour window) is handled by create_notification().
        """
        from datetime import date
        from app.models import Home, Room
        from app.appliance_scenarios import calculate_optimization
        from influxdb import InfluxDBClient

        logger.info("Running smart device scenario notification check...")

        influx = InfluxDBClient(
            host=settings.INFLUX_HOST,
            port=settings.INFLUX_PORT,
            username=settings.INFLUX_USER,
            password=settings.INFLUX_PASS,
            database=settings.INFLUX_DB,
        )

        import asyncio

        def _query_latest(measurement: str, entity_id: str) -> Optional[float]:
            try:
                result = influx.query(
                    f'SELECT * FROM "{measurement}" WHERE entity_id = \'{entity_id}\' '
                    f"ORDER BY time DESC LIMIT 1"
                )
                pts = list(result.get_points())
                return float(pts[0]["value"]) if pts else None
            except Exception:
                return None

        # Blocking InfluxDB I/O — keep it off the event loop so the scheduler
        # (and the whole API) isn't stalled while this 2-hourly job runs.
        async def _latest_sensor(measurement: str, entity_id: str) -> Optional[float]:
            return await asyncio.to_thread(_query_latest, measurement, entity_id)

        today = date.today()
        users_result = await db.execute(select(User).where(User.notifications_enabled == True))
        users = users_result.scalars().all()

        for user in users:
            try:
                homes_result = await db.execute(
                    select(Home).where(Home.user_id == user.id, Home.is_active == True)
                )
                homes = homes_result.scalars().all()

                for home in homes:
                    # Build room conditions lookup
                    rooms_result = await db.execute(
                        select(Room).where(Room.home_id == home.id)
                    )
                    rooms = rooms_result.scalars().all()
                    room_conditions: dict[str, dict] = {}
                    for room in rooms:
                        base = room.entity_id or room.name.lower().replace(" ", "")
                        temp = await _latest_sensor("°C", f"{base}_temperature")
                        hum = await _latest_sensor("%", f"{base}_humidity")
                        pres = await _latest_sensor("hPa", f"{base}_pressure")
                        room_conditions[room.name.lower()] = {
                            "temperature": temp or 20.0,
                            "humidity": hum or 50.0,
                            "pressure": pres or 101.3,
                        }

                    default_cond = (
                        list(room_conditions.values())[0]
                        if room_conditions
                        else {"temperature": 20.0, "humidity": 50.0, "pressure": 101.3}
                    )

                    devices_result = await db.execute(
                        select(Device).where(Device.home_id == home.id, Device.is_active == True)
                    )
                    devices = devices_result.scalars().all()

                    for device in devices:
                        if not device.appliance_key:
                            continue

                        daily_result = await db.execute(
                            select(DailySummary).where(
                                DailySummary.device_id == device.id,
                                DailySummary.day_date == today,
                            )
                        )
                        daily = daily_result.scalar_one_or_none()

                        location_key = (device.location or "").lower()
                        cond = room_conditions.get(location_key, default_cond)

                        usage_data = {
                            "N": daily.usage_cycles or 0 if daily else 0,
                            "eaec": (daily.total_kwh / max(daily.usage_cycles, 1))
                                    if daily and daily.usage_cycles else 0,
                            "dailyEAEC": daily.total_kwh or 0 if daily else 0,
                            "duration": daily.active_minutes or 0 if daily else 0,
                            "avgPower": daily.avg_watts or 0 if daily else 0,
                            "isPeakTime": settings.is_peak_time(),
                            "standbyTime": 0, "standbyPower": 0,
                            "lateNightHours": 0, "keepWarmTime": 0, "shortUseCount": 0,
                        }

                        optimization = calculate_optimization(
                            appliance_key=device.appliance_key,
                            temperature=cond["temperature"],
                            humidity=cond["humidity"],
                            pressure=cond["pressure"],
                            usage_data=usage_data,
                        )

                        for alert in optimization["alerts"]:
                            if alert["priority"] not in ("critical", "warning"):
                                continue

                            severity = "CRITICAL" if alert["priority"] == "critical" else "WARNING"
                            notif_type = "ENERGY_ALERT" if severity == "CRITICAL" else "RECOMMENDATION"

                            await NotificationEngine.create_notification(
                                db=db,
                                user_id=user.id,
                                title=f"{alert['level']} {device.name}: {alert['scenario']}",
                                message=alert["message"],
                                notification_type=notif_type,
                                severity=severity,
                                home_id=home.id,
                                device_id=device.id,
                                action_hint=f"View {device.name} analytics",
                                action_button_text="View Device",
                                requires_user_action=severity == "CRITICAL",
                                metadata={
                                    "appliance_key": device.appliance_key,
                                    "priority": alert["priority"],
                                    "scenario": alert["scenario"],
                                    "health_tip": alert.get("health_tip"),
                                    "energy_message": alert.get("energy_message"),
                                    "efficiency_score": optimization["efficiency_score"],
                                },
                                send_push=True,
                            )
            except Exception as e:
                logger.error(f"Error in smart device check for user {user.id}: {e}")

        logger.info("Smart device scenario notification check complete")
