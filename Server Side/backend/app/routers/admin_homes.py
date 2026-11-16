"""
WattWise — Admin: homes and their RPi publishers.

A real home is one with an MQTT identity (homes.mqtt_username): an RPi in the house
publishes its devices' readings as that broker account. This router shows which homes
are reporting and which have gone quiet.
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cohorts import apply_user_cohort, normalise_cohort
from app.config import settings
from app.database import get_db
from app.models import Device, Home, User

router = APIRouter(prefix="/api/admin/homes", tags=["Admin — Homes"])


def _require_admin(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id or not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


def home_state(last_seen_at, mqtt_username, now: datetime, offline_after_minutes: int) -> str:
    """
    never_seen — no reading has ever arrived
    online     — a reading arrived within the offline threshold
    offline    — it has been quiet for longer than that
    """
    if last_seen_at is None:
        return "never_seen"
    if now - last_seen_at <= timedelta(minutes=offline_after_minutes):
        return "online"
    return "offline"


@router.get("/status")
async def homes_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
    cohort: str = Query(default="real"),
):
    """Every home with its owner, broker identity, device count and when it was last heard from."""
    _require_admin(request)
    cohort = normalise_cohort(cohort)
    now = datetime.utcnow()

    q = (
        select(
            Home, User.name, User.email, User.is_synthetic,
            func.count(Device.id).label("devices"),
            func.sum(func.if_(Device.last_seen_at >= now - timedelta(minutes=settings.HOME_OFFLINE_AFTER_MINUTES), 1, 0))
            .label("devices_reporting"),
        )
        .join(User, User.id == Home.user_id)
        .outerjoin(Device, (Device.home_id == Home.id) & Device.is_active)
        .where(User.is_admin.is_(False), Home.is_active)
        .group_by(Home.id, User.name, User.email, User.is_synthetic)
        .order_by(User.is_synthetic, Home.id)
    )
    q = apply_user_cohort(q, cohort)
    rows = (await db.execute(q)).all()

    homes = []
    for home, user_name, user_email, is_synthetic, devices, reporting in rows:
        state = home_state(home.last_seen_at, home.mqtt_username, now, settings.HOME_OFFLINE_AFTER_MINUTES)
        homes.append({
            "home_id": home.id, "home_name": home.home_name,
            "user_id": home.user_id, "user_name": user_name, "user_email": user_email,
            "is_synthetic": bool(is_synthetic),
            "mqtt_username": home.mqtt_username,
            "feed": "rpi" if home.mqtt_username else ("generator" if is_synthetic else "none"),
            "devices": int(devices or 0), "devices_reporting": int(reporting or 0),
            "state": state,
            "last_seen_at": home.last_seen_at.isoformat() if home.last_seen_at else None,
            "minutes_since_seen": round((now - home.last_seen_at).total_seconds() / 60, 1) if home.last_seen_at else None,
            "publisher_status": home.publisher_status,
            "publisher_seen_at": home.publisher_seen_at.isoformat() if home.publisher_seen_at else None,
        })

    rpi_homes = [h for h in homes if h["feed"] == "rpi"]
    return {
        "cohort": cohort,
        "offline_after_minutes": settings.HOME_OFFLINE_AFTER_MINUTES,
        "summary": {
            "homes": len(homes),
            "rpi_homes": len(rpi_homes),
            "rpi_online": sum(1 for h in rpi_homes if h["state"] == "online"),
            "rpi_offline": sum(1 for h in rpi_homes if h["state"] != "online"),
        },
        "homes": homes,
    }
