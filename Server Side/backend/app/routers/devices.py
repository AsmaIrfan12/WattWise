"""WattWise — Devices & Homes Router."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
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


def _derive_entity_ids(name: str, appliance_key: str | None) -> dict:
    """
    Derive (entity_id, power_entity_id, switch_entity_id) from a device name
    or appliance_key. Mirrors the old Node generateEntityIds() helper so that
    existing MQTT topic conventions keep working.
    """
    import re
    # Prefer the canonical appliance_key mapping when available
    base = _APPLIANCE_ENTITY_BASE.get((appliance_key or "").lower())
    if not base:
        # Fallback: slugify the device name
        slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")
        base = slug or "device"
    return {
        "entity_id": f"{base}_current_consumption",
        "power_entity_id": f"{base}_current_consumption",
        "switch_entity_id": f"{base}_switch_state",
    }


@router.post("/homes/{home_id}/devices", response_model=DeviceResponse, status_code=201)
async def add_device(home_id: int, body: DeviceCreate, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _get_user_id(request)
    # Verify home belongs to user
    home_result = await db.execute(select(Home).where(Home.id == home_id, Home.user_id == user_id))
    if not home_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Home not found")

    payload = body.model_dump()

    # Auto-derive entity IDs if the caller didn't supply them
    if not payload.get("entity_id") or not payload.get("power_entity_id"):
        derived = _derive_entity_ids(payload.get("name"), payload.get("appliance_key"))
        for k, v in derived.items():
            if not payload.get(k):
                payload[k] = v

    device = Device(home_id=home_id, **payload)
    db.add(device)
    await db.commit()
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
