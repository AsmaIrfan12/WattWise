"""
WattWise — Admin: homes and their RPi publishers.

A real home is one with an MQTT identity (homes.mqtt_username): an RPi in the house
publishes its devices' readings as that broker account. This router shows which homes
are reporting and which have gone quiet.
"""
import asyncio
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import broker_admin
from app.broker_admin import BrokerAdminError, generate_mqtt_password, is_legacy_username, next_home_username
from app.cohorts import apply_user_cohort, normalise_cohort
from app.config import settings
from app.database import get_db
from app.models import AdminAuditLog, Device, Home, User
from app.publisher_config import build_publisher_yaml, slug
from app.routers.auth import _hash_password

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
            "managed": bool(home.mqtt_username) and not is_legacy_username(home.mqtt_username),
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


# ── Provisioning: participant + home + devices + broker account in one step ──

class ProvisionDevice(BaseModel):
    name: str = Field(..., min_length=1, max_length=128)
    appliance_key: str = Field(..., min_length=1, max_length=64, pattern="^[a-z0-9_]+$")
    power_entity_id: Optional[str] = Field(default=None, max_length=128)
    rated_wattage: Optional[float] = Field(default=None, ge=0, le=50000)


class ProvisionHomeRequest(BaseModel):
    participant_name: str = Field(..., min_length=2, max_length=128)
    participant_email: EmailStr
    # Leave empty to have a temporary password generated (shown once in the response).
    participant_password: Optional[str] = Field(default=None, min_length=8, max_length=128)
    home_name: Optional[str] = Field(default=None, max_length=128)
    address: Optional[str] = Field(default=None, max_length=256)
    num_occupants: int = Field(default=1, ge=1, le=20)
    home_type: str = Field(default="other", pattern="^(flat|terraced|semi-detached|detached|other)$")
    devices: list[ProvisionDevice] = Field(..., min_length=1, max_length=40)


def _new_entity_id(appliance_key: str) -> str:
    return f"sensor.{slug(appliance_key)}_{secrets.token_hex(3)}"


def _mqtt_host(request: Request) -> str:
    return settings.PUBLIC_MQTT_HOST or (request.url.hostname or "localhost")


async def _publisher_yaml(db: AsyncSession, home: Home, request: Request, mqtt_password: Optional[str]) -> str:
    devices = (await db.execute(
        select(Device).where(Device.home_id == home.id, Device.is_active).order_by(Device.id)
    )).scalars().all()
    return build_publisher_yaml(
        mqtt_username=home.mqtt_username, mqtt_password=mqtt_password, home_name=home.home_name,
        devices=[{"name": d.name, "appliance_key": d.appliance_key, "entity_id": d.entity_id,
                  "power_entity_id": d.power_entity_id} for d in devices],
        mqtt_host=_mqtt_host(request), mqtt_port=settings.PUBLIC_MQTT_PORT,
    )


async def _home_or_404(db: AsyncSession, home_id: int) -> Home:
    home = (await db.execute(select(Home).where(Home.id == home_id))).scalar_one_or_none()
    if not home:
        raise HTTPException(status_code=404, detail="Home not found")
    return home


@router.post("/provision", status_code=201)
async def provision_home(body: ProvisionHomeRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Onboard a real home in one step: the participant's account, their home, its
    devices, and the home's own MQTT account on the broker. Returns the publisher
    config to paste into the Raspberry Pi — the MQTT password (and a generated
    temporary app password) are shown only in this response.
    """
    admin_id = _require_admin(request)
    email = body.participant_email.strip()

    user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
    temp_password = None
    if user is None:
        temp_password = body.participant_password or secrets.token_urlsafe(9)
        user = User(name=body.participant_name.strip(), email=email, password_hash=_hash_password(temp_password),
                    notifications_enabled=True, is_admin=False, is_synthetic=False)
        db.add(user)
        await db.flush()
        if body.participant_password:
            temp_password = None  # the admin chose it; nothing to reveal
    elif user.is_admin:
        raise HTTPException(status_code=409, detail="That email belongs to an admin account")
    elif user.is_synthetic:
        raise HTTPException(status_code=409, detail="That email belongs to a synthetic demo account")

    existing_usernames = list((await db.execute(
        select(Home.mqtt_username).where(Home.mqtt_username.isnot(None))
    )).scalars().all())
    mqtt_username = next_home_username(existing_usernames)
    mqtt_password = generate_mqtt_password()

    home = Home(
        user_id=user.id,
        home_name=(body.home_name or f"{user.name.split(' ')[0]}'s Home").strip(),
        address=body.address, num_occupants=body.num_occupants, home_type=body.home_type,
        mqtt_username=mqtt_username,
    )
    db.add(home)
    await db.flush()
    for d in body.devices:
        db.add(Device(home_id=home.id, name=d.name.strip(), appliance_key=d.appliance_key,
                      entity_id=_new_entity_id(d.appliance_key), power_entity_id=d.power_entity_id,
                      rated_wattage=d.rated_wattage, device_type="appliance"))

    # Create the broker account before committing: if the broker refuses, nothing is saved.
    try:
        await asyncio.to_thread(broker_admin.provision_home, mqtt_username, mqtt_password)
    except BrokerAdminError as e:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"Could not create the MQTT account: {e}")
    await db.commit()
    await db.refresh(home)

    db.add(AdminAuditLog(
        admin_user_id=admin_id, action_type="PROVISION_HOME", target_user_id=user.id,
        details_json={"home_id": home.id, "mqtt_username": mqtt_username, "devices": len(body.devices)},
        ip_address=request.client.host if request.client else None,
    ))
    await db.commit()

    return {
        "home_id": home.id, "home_name": home.home_name,
        "user_id": user.id, "user_email": user.email,
        "temporary_app_password": temp_password,
        "mqtt_username": mqtt_username, "mqtt_password": mqtt_password,
        "mqtt_host": _mqtt_host(request), "mqtt_port": settings.PUBLIC_MQTT_PORT,
        "publisher_yaml": await _publisher_yaml(db, home, request, mqtt_password),
        "note": "The MQTT password is shown only now. Use 'Rotate credentials' to issue a new one.",
    }


@router.get("/{home_id}/publisher-config")
async def publisher_config(home_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """The home's publisher YAML with a placeholder for the MQTT password (it is never stored in clear)."""
    _require_admin(request)
    home = await _home_or_404(db, home_id)
    if not home.mqtt_username:
        raise HTTPException(status_code=409, detail="This home has no MQTT account (it is not an RPi home)")
    return {"home_id": home.id, "mqtt_username": home.mqtt_username,
            "publisher_yaml": await _publisher_yaml(db, home, request, None)}


@router.post("/{home_id}/rotate-credentials")
async def rotate_credentials(home_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    """Issue a new MQTT password for a provisioned home; the old one stops working immediately."""
    admin_id = _require_admin(request)
    home = await _home_or_404(db, home_id)
    if not home.mqtt_username:
        raise HTTPException(status_code=409, detail="This home has no MQTT account")
    if is_legacy_username(home.mqtt_username):
        raise HTTPException(
            status_code=409,
            detail=f"{home.mqtt_username} is a legacy account from the broker's password file "
                   f"(set MQTT_HOME_{home.mqtt_username.split('_')[1]}_PASS in .env and recreate the mosquitto service)",
        )
    new_password = generate_mqtt_password()
    try:
        await asyncio.to_thread(broker_admin.set_password, home.mqtt_username, new_password)
    except BrokerAdminError as e:
        raise HTTPException(status_code=502, detail=f"Could not rotate the MQTT password: {e}")
    db.add(AdminAuditLog(
        admin_user_id=admin_id, action_type="ROTATE_CREDENTIALS", target_user_id=home.user_id,
        details_json={"home_id": home.id, "mqtt_username": home.mqtt_username},
        ip_address=request.client.host if request.client else None,
    ))
    await db.commit()
    return {"home_id": home.id, "mqtt_username": home.mqtt_username, "mqtt_password": new_password,
            "publisher_yaml": await _publisher_yaml(db, home, request, new_password)}


@router.post("/{home_id}/devices", status_code=201)
async def add_home_device(home_id: int, body: ProvisionDevice, request: Request, db: AsyncSession = Depends(get_db)):
    """Add a device to a home. Returns its server-side entity_id for the Pi's config."""
    admin_id = _require_admin(request)
    home = await _home_or_404(db, home_id)
    device = Device(home_id=home.id, name=body.name.strip(), appliance_key=body.appliance_key,
                    entity_id=_new_entity_id(body.appliance_key), power_entity_id=body.power_entity_id,
                    rated_wattage=body.rated_wattage, device_type="appliance")
    db.add(device)
    db.add(AdminAuditLog(
        admin_user_id=admin_id, action_type="PROVISION_HOME", target_user_id=home.user_id,
        details_json={"home_id": home.id, "added_device": body.name, "appliance_key": body.appliance_key},
        ip_address=request.client.host if request.client else None,
    ))
    await db.commit()
    await db.refresh(device)
    return {"device_id": device.id, "name": device.name, "appliance_key": device.appliance_key,
            "entity_id": device.entity_id,
            "publisher_yaml": await _publisher_yaml(db, home, request, None) if home.mqtt_username else None}
