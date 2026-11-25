"""WattWise — Devices & Homes Router."""

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Home, Device
from app.schemas import HomeCreate, HomeResponse, DeviceCreate, DeviceResponse

router = APIRouter(prefix="/api", tags=["Homes & Devices"])


def _get_user_id(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id


# ── Homes ─────────────────────────────────────────────────────

@router.post("/homes", response_model=HomeResponse, status_code=201)
async def create_home(body: HomeCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    home = Home(user_id=user_id, **body.model_dump())
    db.add(home)
    await db.commit()
    await db.refresh(home)
    return home


@router.get("/homes", response_model=list[HomeResponse])
async def list_homes(request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(select(Home).where(Home.user_id == user_id, Home.is_active == True))
    return result.scalars().all()


@router.get("/homes/{home_id}", response_model=HomeResponse)
async def get_home(home_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(select(Home).where(Home.id == home_id, Home.user_id == user_id))
    home = result.scalar_one_or_none()
    if not home:
        raise HTTPException(status_code=404, detail="Home not found")
    return home


_ALLOWED_HOME_FIELDS = {"home_name", "address", "location_desc", "num_occupants", "home_type"}


@router.patch("/homes/{home_id}", response_model=HomeResponse)
async def update_home(home_id: int, body: HomeCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(select(Home).where(Home.id == home_id, Home.user_id == user_id))
    home = result.scalar_one_or_none()
    if not home:
        raise HTTPException(status_code=404, detail="Home not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k in _ALLOWED_HOME_FIELDS:
            setattr(home, k, v)
    await db.commit()
    await db.refresh(home)
    return home


@router.delete("/homes/{home_id}", status_code=204)
async def deactivate_home(home_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(select(Home).where(Home.id == home_id, Home.user_id == user_id))
    home = result.scalar_one_or_none()
    if not home:
        raise HTTPException(status_code=404, detail="Home not found")
    home.is_active = False
    await db.commit()


# ── Devices ───────────────────────────────────────────────────

# Known appliance → canonical entity_id base mapping
# Ported from old generateEntityIds() in user-controller.js
_APPLIANCE_ENTITY_BASE = {
    "kettle": "kettle",
    "microwave": "microwave",
    "dishwasher": "dishwasher",
    "washing_machine": "washing_machine",
    "washingmachine": "washing_machine",
    "toaster": "toaster",
    "dryer": "dryer",
    "coffeemachine": "coffeemachine",
    "airfryer": "airfryer",
    "cooker": "cooker",
    "water_purifier": "water_purifier",
    "waterpurifier": "water_purifier",
    "gaming_console": "gaming_console",
    "xbox": "gaming_console",
    "tv": "tv",
}


MAX_DEVICE_NAME = 60
_SENSOR_ID_OK = re.compile(r"^[A-Za-z0-9_.:\-]{1,128}$")


def _entity_base(name: str | None, appliance_key: str | None) -> str:
    """The stem of a device's sensor ID: the appliance's canonical name, else the device name."""
    base = _APPLIANCE_ENTITY_BASE.get((appliance_key or "").lower())
    if not base:
        base = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_") or "device"
    return base


def unique_entity_ids(name: str | None, appliance_key: str | None, taken: set[str]) -> dict:
    """
    Sensor IDs for a new device that do not clash with any the home already has.

    A home may have two kettles. The first is "kettle_current_consumption" (the
    convention the Raspberry Pi publisher uses); the next becomes
    "kettle_2_current_consumption", and so on. `taken` is every entity_id already
    used in the home, including removed devices (the database keeps their rows).
    """
    base = _entity_base(name, appliance_key)
    candidate, n = base, 1
    while f"{candidate}_current_consumption" in taken:
        n += 1
        candidate = f"{base}_{n}"
    return {
        "entity_id": f"{candidate}_current_consumption",
        "power_entity_id": f"{candidate}_current_consumption",
        "switch_entity_id": f"{candidate}_switch_state",
    }


def _derive_entity_ids(name: str, appliance_key: str | None) -> dict:
    """Sensor IDs for the first device of its kind (kept for callers that have no home context)."""
    return unique_entity_ids(name, appliance_key, set())


@router.post("/homes/{home_id}/devices", response_model=DeviceResponse, status_code=201)
async def add_device(home_id: int, body: DeviceCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """
    Add a device to the caller's home.

    Only a name and an appliance type are needed: the sensor ID is generated, unique
    within the home. A sensor ID may be given (an installer linking a specific smart
    plug); a clash with a device the home already has is answered with 409 and a
    plain message. Before this, a second device of the same type, or a sensor ID
    already in use, hit the database's unique key and came back as a bare 500.
    """
    user_id = _get_user_id(request)
    # Verify home belongs to user
    home_result = await db.execute(select(Home).where(Home.id == home_id, Home.user_id == user_id))
    if not home_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Home not found")

    name = (body.name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Give the device a name.")
    if len(name) > MAX_DEVICE_NAME:
        raise HTTPException(status_code=422, detail=f"The name can be at most {MAX_DEVICE_NAME} characters.")
    appliance_key = (body.appliance_key or "").strip().lower() or "other"
    location = (body.location or "").strip() or None

    existing = (await db.execute(select(Device).where(Device.home_id == home_id))).scalars().all()
    by_entity = {d.entity_id: d for d in existing if d.entity_id}

    payload = body.model_dump()
    payload.update(name=name, appliance_key=appliance_key, location=location)

    wanted = (body.entity_id or "").strip()
    if wanted:
        if not _SENSOR_ID_OK.match(wanted):
            raise HTTPException(
                status_code=422,
                detail="A sensor ID can only contain letters, numbers, dots, underscores, colons and hyphens.",
            )
        clash = by_entity.get(wanted)
        if clash is not None and clash.is_active:
            raise HTTPException(
                status_code=409,
                detail=f"This home already has a device with that sensor ID ({clash.name}).",
            )
        if clash is not None:
            # A device that was removed earlier: bring it back (its history comes with it)
            # instead of failing on the unique key.
            clash.is_active = True
            clash.name, clash.appliance_key, clash.location = name, appliance_key, location
            await db.commit()
            await db.refresh(clash)
            return clash
        derived = unique_entity_ids(name, appliance_key, set(by_entity))
        payload["entity_id"] = wanted
        payload["power_entity_id"] = (body.power_entity_id or "").strip() or wanted
        payload["switch_entity_id"] = (body.switch_entity_id or "").strip() or derived["switch_entity_id"]
    else:
        payload.update(unique_entity_ids(name, appliance_key, set(by_entity)))

    device = Device(home_id=home_id, **payload)
    db.add(device)
    try:
        await db.commit()
    except IntegrityError:
        # Two requests at once for the same sensor ID: the second one loses cleanly.
        await db.rollback()
        raise HTTPException(status_code=409, detail="This home already has a device with that sensor ID.")
    await db.refresh(device)
    return device


@router.get("/homes/{home_id}/devices", response_model=list[DeviceResponse])
async def list_devices(home_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    home_result = await db.execute(select(Home).where(Home.id == home_id, Home.user_id == user_id))
    if not home_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Home not found")
    result = await db.execute(select(Device).where(Device.home_id == home_id, Device.is_active == True))
    return result.scalars().all()


_ALLOWED_DEVICE_FIELDS = {"name", "appliance_key", "location", "entity_id", "power_entity_id", "switch_entity_id", "device_type", "rated_wattage"}


@router.patch("/devices/{device_id}", response_model=DeviceResponse)
async def update_device(device_id: int, body: DeviceCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(Device).join(Home, Device.home_id == Home.id)
        .where(Device.id == device_id, Home.user_id == user_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    for k, v in body.model_dump(exclude_unset=True).items():
        if k in _ALLOWED_DEVICE_FIELDS:
            setattr(device, k, v)
    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/devices/{device_id}", status_code=204)
async def deactivate_device(device_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    result = await db.execute(
        select(Device).join(Home, Device.home_id == Home.id)
        .where(Device.id == device_id, Home.user_id == user_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    device.is_active = False
    await db.commit()
