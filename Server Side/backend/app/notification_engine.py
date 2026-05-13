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
from app.models import User, Notification, Device, Home, DailySummary, HomeDailyTotal

logger = logging.getLogger("notification_engine")

# Deduplication window: don't send same notification type to same user within this period
DEDUP_WINDOW_HOURS = 12


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
    ) -> Optional[Notification]:
        """
        Create a notification record and optionally deliver via push.
        Includes deduplication to prevent notification spam.
        """
        # Deduplication check
        dedup_since = datetime.utcnow() - timedelta(hours=DEDUP_WINDOW_HOURS)
        existing = await db.execute(
            select(Notification).where(
                Notification.user_id == user_id,
                Notification.notification_type == notification_type,
                Notification.device_id == device_id,
                Notification.created_at >= dedup_since
            ).limit(1)
        )
        if existing.scalar_one_or_none():
            logger.debug(f"Skipping duplicate {notification_type} for user {user_id}")
            return None

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
        """Send a push notification via Expo Push API. Returns receipt ID or None."""
        payload = {
            "to": push_token,
            "sound": "default",
            "title": title,
            "body": body,
            "data": data,
            "priority": "high",
            "channelId": "energy-alerts" if data.get("severity") in ("ALERT", "CRITICAL") else "energy-info",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    settings.EXPO_PUSH_URL,
                    json=payload,
                    headers={"Content-Type": "application/json", "Accept": "application/json"}
                )
                resp.raise_for_status()
                result = resp.json()
                if isinstance(result, dict) and result.get("data", {}).get("status") == "ok":
                    return result["data"].get("id")
                return None
        except Exception as e:
            logger.warning(f"Push notification failed for token {push_token[:20]}...: {e}")
            return None

    # ── Automated Notification Generators ────────────────────

    @staticmethod
    async def check_daily_goal_notifications(db: AsyncSession):
        """
        For each user with an active daily goal, check progress and send alerts.
        Called hourly by scheduler.
        """
        logger.info("Checking daily goal notifications...")
        today = datetime.utcnow().date()

        users_result = await db.execute(
            select(User).where(User.notifications_enabled == True, User.push_token.isnot(None))
        )
        users = users_result.scalars().all()

        for user in users:
            try:
                # Get user's homes
                homes_result = await db.execute(select(Home).where(Home.user_id == user.id, Home.is_active == True))
                homes = homes_result.scalars().all()

                for home in homes:
                    # Get today's home total
                    total_result = await db.execute(
                        select(HomeDailyTotal).where(HomeDailyTotal.home_id == home.id, HomeDailyTotal.day_date == today)
                    )
                    today_total = total_result.scalar_one_or_none()
                    today_kwh = today_total.total_kwh if today_total else 0.0

                    # Check against user's daily goal or system threshold
                    daily_goal = user.daily_energy_goal_kwh or settings.ENERGY_DAILY_WARNING_KWH

                    if today_kwh >= daily_goal * 1.0 and today_kwh < daily_goal * 1.2:
                        await NotificationEngine.create_notification(
                            db, user.id,
                            title="⚡ Daily Energy Goal Reached",
                            message=f"You've used {today_kwh:.1f} kWh today — you've hit your daily target of {daily_goal:.1f} kWh. Try to keep usage steady for the rest of the day.",
                            notification_type="GOAL_WARNING",
                            severity="WARNING",
                            home_id=home.id,
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
                            action_hint="Turn off high-consumption appliances",
                            action_button_text="Take Action",
                            requires_user_action=True,
                        )
            except Exception as e:
                logger.error(f"Error in goal notifications for user {user.id}: {e}")

    @staticmethod
    async def send_peak_tariff_reminder(db: AsyncSession):
        """
        Send peak tariff reminder 15 minutes before peak hours start (3:45 PM UK time).
        """
        logger.info("Sending peak tariff reminders...")
        users_result = await db.execute(
            select(User).where(User.notifications_enabled == True, User.push_token.isnot(None))
        )
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

        users_result = await db.execute(
            select(User).where(User.notifications_enabled == True, User.push_token.isnot(None))
        )
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
    ) -> int:
        """
        Send a notification from admin to specified users (or all users if user_ids is None).
        Returns the count of notifications created.
        """
        if user_ids:
            users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
        else:
            users_result = await db.execute(select(User).where(User.is_admin == False))

        users = users_result.scalars().all()
        count = 0

        for user in users:
            notif = await db.execute(
                select(Notification).where(
                    Notification.user_id == user.id,
                    Notification.notification_type == notification_type,
                    Notification.title == title,
                    Notification.created_at >= datetime.utcnow() - timedelta(hours=1)
                ).limit(1)
            )
            if notif.scalar_one_or_none():
                continue  # Don't spam identical admin notifications

            await NotificationEngine.create_notification(
                db, user.id,
                title=title,
                message=message,
                notification_type=notification_type,
                severity=severity,
                action_hint=action_hint,
                action_button_text=action_button_text,
                requires_user_action=requires_user_action,
                send_push=True,
            )
            count += 1

        logger.info(f"Admin broadcast '{title}' sent to {count} users")
        return count

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

        def _latest_sensor(measurement: str, entity_id: str) -> Optional[float]:
            try:
                result = influx.query(
                    f'SELECT * FROM "{measurement}" WHERE entity_id = \'{entity_id}\' '
                    f"ORDER BY time DESC LIMIT 1"
                )
                pts = list(result.get_points())
                return float(pts[0]["value"]) if pts else None
            except Exception:
                return None

        today = date.today()
        users_result = await db.execute(
            select(User).where(User.notifications_enabled == True, User.push_token.isnot(None))
        )
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
                        temp = _latest_sensor("°C", f"{base}_temperature")
                        hum = _latest_sensor("%", f"{base}_humidity")
                        pres = _latest_sensor("hPa", f"{base}_pressure")
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
                                    "efficiency_score": optimization["efficiency_score"],
                                },
                                send_push=True,
                            )
            except Exception as e:
                logger.error(f"Error in smart device check for user {user.id}: {e}")

        logger.info("Smart device scenario notification check complete")
