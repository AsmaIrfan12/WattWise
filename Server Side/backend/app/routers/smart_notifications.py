"""
WattWise — Smart Notifications Router
=======================================
Ported from old/controllers/user-controller.js (getSmartNotifications,
checkDeviceBeforeUse, requestPushNotifications).

Provides on-demand scenario-based energy alert generation using:
- appliance_scenarios.py (EnergyCalculator port)
- energy_analysis.py (cycle/usage detection)
- environment data from InfluxDB (room temperature/humidity/pressure)
- MySQL device & daily summary data

Key differences from the old system:
- Uses SQL (MySQL) instead of MongoDB for device/user storage
- Deduplication is handled via the notification_engine (12-hour window)
- Expo push delivery is handled by notification_engine._send_expo_push

Base URL: /api/smart-notifications/
Authentication: JWT Bearer (all routes protected)
"""

import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from influxdb import InfluxDBClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import User, Home, Room, Device, DailySummary
from app.appliance_scenarios import calculate_optimization, APPLIANCE_BASE_ENERGY
from app.notification_engine import NotificationEngine

logger = logging.getLogger("smart_notifications_router")

router = APIRouter(prefix="/api/smart-notifications", tags=["Smart Notifications"])


# ── Helpers ──────────────────────────────────────────────────────

def _get_user_id(request: Request) -> int:
    uid = getattr(request.state, "user_id", None)
    if not uid:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return uid


def _get_influx() -> InfluxDBClient:
    return InfluxDBClient(
        host=settings.INFLUX_HOST,
        port=settings.INFLUX_PORT,
        username=settings.INFLUX_USER,
        password=settings.INFLUX_PASS,
        database=settings.INFLUX_DB,
    )


def _fetch_env_conditions(influx: InfluxDBClient, entity_base: str) -> dict:
    """Fetch current temperature, humidity, pressure for a room entity_base."""
    defaults = {"temperature": 20.0, "humidity": 50.0, "pressure": 101.3}

    def _latest(measurement: str, entity_id: str) -> Optional[float]:
        try:
            query = (
                f'SELECT * FROM "{measurement}" WHERE entity_id = \'{entity_id}\' '
                f"ORDER BY time DESC LIMIT 1"
            )
            result = influx.query(query)
            pts = list(result.get_points())
            return float(pts[0]["value"]) if pts else None
        except Exception:
            return None

    temp = _latest("°C", f"{entity_base}_temperature")
    hum = _latest("%", f"{entity_base}_humidity")
    pres = _latest("hPa", f"{entity_base}_pressure")

    return {
        "temperature": temp if temp is not None else defaults["temperature"],
        "humidity": hum if hum is not None else defaults["humidity"],
        "pressure": pres if pres is not None else defaults["pressure"],
    }


def _build_usage_data_for_device(device: Device, daily: Optional[DailySummary]) -> dict:
    """Build the usage_data dict needed by calculate_optimization from DB data."""
    if not daily:
        return {"N": 0, "eaec": 0, "dailyEAEC": 0, "duration": 0,
                "standbyTime": 0, "standbyPower": 0, "avgPower": 0,
                "isPeakTime": settings.is_peak_time()}

    return {
        "N": daily.usage_cycles or 0,
        "eaec": daily.total_kwh / max(daily.usage_cycles, 1) if daily.usage_cycles else 0,
        "dailyEAEC": daily.total_kwh or 0,
        "duration": daily.active_minutes or 0,
        "avgPower": daily.avg_watts or 0,
        "standbyTime": 0,       # Approximated — full standby tracking needs InfluxDB
        "standbyPower": 0,
        "isPeakTime": settings.is_peak_time(),
        "lateNightHours": 0,
        "keepWarmTime": 0,
        "shortUseCount": 0,
    }


# ── Endpoints ─────────────────────────────────────────────────────

@router.get("/")
async def get_smart_notifications(
    request: Request,
    db: AsyncSession = Depends(get_db),
    home_id: Optional[int] = Query(default=None),
):
    """
    Generate and return scenario-based smart alerts for the current user's devices.
    
    - Reads today's DailySummary for each device from MySQL
    - Reads room environmental conditions from InfluxDB
    - Runs appliance_scenarios.calculate_optimization for each device
    - Returns alerts sorted by priority (critical → warning → caution → notice)
    
    This is the GET equivalent of the old /requestPushNotifications.
    """
    user_id = _get_user_id(request)

    # Get user for notification settings
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Load homes
    query = select(Home).where(Home.user_id == user_id, Home.is_active == True)
    if home_id:
        query = query.where(Home.id == home_id)
    homes_result = await db.execute(query)
    homes = homes_result.scalars().all()

    if not homes:
        return {"message": "No homes configured", "alerts": []}

    # Get room conditions from InfluxDB
    influx = _get_influx()
    today = datetime.utcnow().date()
    priority_order = {"critical": 0, "warning": 1, "caution": 2, "notice": 3}
    all_alerts = []

    for home in homes:
        # Build room condition lookup: room_name → conditions
        rooms_result = await db.execute(select(Room).where(Room.home_id == home.id))
        rooms = rooms_result.scalars().all()

        room_conditions: dict[str, dict] = {}
        for room in rooms:
            entity_base = room.entity_id or room.name.lower().replace(" ", "")
            room_conditions[room.name.lower()] = _fetch_env_conditions(influx, entity_base)

        # Default fallback conditions if no room sensor data
        default_conditions = (
            list(room_conditions.values())[0]
            if room_conditions
            else {"temperature": 20.0, "humidity": 50.0, "pressure": 101.3}
        )

        # Process each device
        devices_result = await db.execute(
            select(Device).where(Device.home_id == home.id, Device.is_active == True)
        )
        devices = devices_result.scalars().all()

        for device in devices:
            if not device.appliance_key:
                continue

            # Get today's daily summary for usage data
            daily_result = await db.execute(
                select(DailySummary).where(
                    DailySummary.device_id == device.id,
                    DailySummary.day_date == today
                )
            )
            daily = daily_result.scalar_one_or_none()

            # Match device location → room conditions
            location_key = (device.location or "").lower()
            conditions = room_conditions.get(location_key, default_conditions)

            usage_data = _build_usage_data_for_device(device, daily)
            optimization = calculate_optimization(
                appliance_key=device.appliance_key,
                temperature=conditions["temperature"],
                humidity=conditions["humidity"],
                pressure=conditions["pressure"],
                usage_data=usage_data,
            )

            for alert in optimization["alerts"]:
                all_alerts.append({
                    "device_id": device.id,
                    "device_name": device.name,
                    "appliance_key": device.appliance_key,
                    "home_id": home.id,
                    "home_name": home.home_name,
                    "location": device.location,
                    "conditions": conditions,
                    "efficiency_score": optimization["efficiency_score"],
                    "potential_savings_pct": optimization["potential_savings_pct"],
                    **alert,
                })

    # Sort by priority
    all_alerts.sort(key=lambda a: priority_order.get(a.get("priority", "notice"), 99))

    return {
        "message": f"Smart analysis complete — {len(all_alerts)} alerts generated",
        "alert_count": len(all_alerts),
        "alerts": all_alerts,
    }


@router.get("/check/{device_id}")
async def check_device_before_use(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Advisory check before using a device.
    
    Returns optimization advice given current:
    - Time of day (peak vs off-peak)
    - Room environmental conditions
    - Recent usage patterns
    
    Ported from old checkDeviceBeforeUse endpoint.
    """
    user_id = _get_user_id(request)

    # Verify device belongs to user
    device_result = await db.execute(
        select(Device).join(Home, Device.home_id == Home.id).where(
            Device.id == device_id,
            Home.user_id == user_id,
            Device.is_active == True,
        )
    )
    device = device_result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Get room conditions
    home_result = await db.execute(select(Home).where(Home.id == device.home_id))
    home = home_result.scalar_one_or_none()

    rooms_result = await db.execute(select(Room).where(Room.home_id == device.home_id))
    rooms = rooms_result.scalars().all()

    influx = _get_influx()
    conditions = {"temperature": 20.0, "humidity": 50.0, "pressure": 101.3}

    location_key = (device.location or "").lower()
    for room in rooms:
        if room.name.lower() == location_key or (room.entity_id or "").lower() == location_key:
            entity_base = room.entity_id or room.name.lower().replace(" ", "")
            conditions = _fetch_env_conditions(influx, entity_base)
            break

    # Get today's usage
    today = datetime.utcnow().date()
    daily_result = await db.execute(
        select(DailySummary).where(
            DailySummary.device_id == device_id,
            DailySummary.day_date == today
        )
    )
    daily = daily_result.scalar_one_or_none()
    usage_data = _build_usage_data_for_device(device, daily)

    # Run full optimization analysis
    optimization = calculate_optimization(
        appliance_key=device.appliance_key,
        temperature=conditions["temperature"],
        humidity=conditions["humidity"],
        pressure=conditions["pressure"],
        usage_data=usage_data,
    )

    # Generate human advisory
    is_peak = settings.is_peak_time()
    advice = {
        "device_name": device.name,
        "appliance_key": device.appliance_key,
        "location": device.location,
        "home_name": home.home_name if home else None,
        "is_peak_time": is_peak,
        "current_tariff_pence_per_kwh": round(settings.get_current_tariff() * 100, 1),
        "estimated_cost_this_use_gbp": round(
            APPLIANCE_BASE_ENERGY.get(device.appliance_key, 0.5) * settings.get_current_tariff(), 4
        ),
        "conditions": conditions,
        "today_usage": {
            "cycles_today": usage_data["N"],
            "kwh_today": round(usage_data["dailyEAEC"], 3),
        },
        "efficiency_score": optimization["efficiency_score"],
        "alerts": optimization["alerts"],
        "recommendations": optimization["recommendations"],
        "verdict": (
            "⚠️ Peak tariff active — consider delaying use until after 7 PM!"
            if is_peak and device.appliance_key in (
                "dryer", "dishwasher", "washingmachine", "washing_machine", "airfryer"
            )
            else "✅ Good time to use this device." if not optimization["alerts"] else
            "💡 Some optimisation suggestions available — see alerts."
        ),
    }
    return advice


@router.post("/trigger")
async def trigger_smart_notifications(
    request: Request,
    db: AsyncSession = Depends(get_db),
    send_push: bool = Query(default=True),
):
    """
    Manually trigger smart notification generation and push delivery for the current user.
    
    Creates notifications in the DB (with deduplication) and sends push via Expo
    if the user has a push token.
    
    Ported from old requestPushNotifications endpoint.
    """
    user_id = _get_user_id(request)

    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if send_push and not user.push_token:
        return {"message": "No push token registered — save a push token first.", "sent_count": 0}

    homes_result = await db.execute(
        select(Home).where(Home.user_id == user_id, Home.is_active == True)
    )
    homes = homes_result.scalars().all()
    if not homes:
        return {"message": "No homes configured", "sent_count": 0}

    influx = _get_influx()
    today = datetime.utcnow().date()
    sent = []

    for home in homes:
        rooms_result = await db.execute(select(Room).where(Room.home_id == home.id))
        rooms = rooms_result.scalars().all()
        room_conditions: dict[str, dict] = {}
        for room in rooms:
            entity_base = room.entity_id or room.name.lower().replace(" ", "")
            room_conditions[room.name.lower()] = _fetch_env_conditions(influx, entity_base)

        default_conditions = (
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
                    DailySummary.day_date == today
                )
            )
            daily = daily_result.scalar_one_or_none()

            location_key = (device.location or "").lower()
            conditions = room_conditions.get(location_key, default_conditions)
            usage_data = _build_usage_data_for_device(device, daily)

            optimization = calculate_optimization(
                appliance_key=device.appliance_key,
                temperature=conditions["temperature"],
                humidity=conditions["humidity"],
                pressure=conditions["pressure"],
                usage_data=usage_data,
            )

            # Only send critical and high-priority alerts via push
            for alert in optimization["alerts"]:
                if alert["priority"] not in ("critical", "warning"):
                    continue

                # Map priority → notification severity
                severity_map = {"critical": "CRITICAL", "warning": "WARNING",
                                "caution": "INFO", "notice": "INFO"}
                severity = severity_map.get(alert["priority"], "INFO")

                # Map priority → notification type
                notif_type = "ENERGY_ALERT" if severity == "CRITICAL" else "RECOMMENDATION"

                notif = await NotificationEngine.create_notification(
                    db=db,
                    user_id=user_id,
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
                    send_push=send_push,
                )

                if notif:
                    sent.append({
                        "device": device.name,
                        "alert": alert["scenario"],
                        "priority": alert["priority"],
                        "notification_id": notif.id,
                    })

    return {
        "message": f"Smart notification trigger complete — {len(sent)} new notifications created",
        "sent_count": len(sent),
        "notifications": sent,
    }
