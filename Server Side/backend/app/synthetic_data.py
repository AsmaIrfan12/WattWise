"""Synthetic community data helpers for Cardiff participant simulations."""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterator


DEVICE_CATALOGUE = {
    "airfryer": {
        "name": "Air Fryer",
        "appliance_key": "airfryer",
        "entity_id": "airfryer_current_consumption",
        "rated_wattage": 1500,
    },
    "dishwasher": {
        "name": "Dishwasher",
        "appliance_key": "dishwasher",
        "entity_id": "dishwasher_current_consumption",
        "rated_wattage": 1800,
    },
    "kettle": {
        "name": "Kettle",
        "appliance_key": "kettle",
        "entity_id": "kettle_current_consumption",
        "rated_wattage": 2200,
    },
    "microwave": {
        "name": "Microwave",
        "appliance_key": "microwave",
        "entity_id": "microwave_current_consumption",
        "rated_wattage": 900,
    },
    "toaster": {
        "name": "Toaster",
        "appliance_key": "toaster",
        "entity_id": "toaster_current_consumption",
        "rated_wattage": 800,
    },
    "washing_machine": {
        "name": "Washing Machine",
        "appliance_key": "washing_machine",
        "entity_id": "washing_machine_current_consumption",
        "rated_wattage": 2000,
    },
}

DEVICE_KEYS = tuple(DEVICE_CATALOGUE.keys())

HOME_TYPE_FACTORS = {
    "flat": 0.88,
    "terraced": 0.98,
    "semi-detached": 1.05,
    "detached": 1.14,
    "other": 1.0,
}

APPLIANCE_PROFILES = {
    "kettle": {
        "on": (1800, 2500),
        "standby": (0, 1),
        "peak_hours": {7, 8, 10, 12, 15, 16, 20, 21},
        "p_peak": 0.30,
        "p_base": 0.05,
        "amps": (7.8, 10.9),
        "volts": (228, 234),
    },
    "microwave": {
        "on": (600, 950),
        "standby": (2, 4),
        "peak_hours": {12, 13, 18, 19, 20},
        "p_peak": 0.18,
        "p_base": 0.03,
        "amps": (2.6, 4.1),
        "volts": (228, 234),
    },
    "washing_machine": {
        "on": (300, 2100),
        "standby": (0, 2),
        "peak_hours": {9, 10, 11, 14, 15, 19},
        "p_peak": 0.15,
        "p_base": 0.07,
        "amps": (1.3, 9.1),
        "volts": (228, 234),
    },
    "dishwasher": {
        "on": (700, 1900),
        "standby": (1, 3),
        "peak_hours": {13, 14, 20, 21, 22},
        "p_peak": 0.18,
        "p_base": 0.03,
        "amps": (3.0, 8.3),
        "volts": (228, 234),
    },
    "toaster": {
        "on": (700, 900),
        "standby": (0, 1),
        "peak_hours": {7, 8, 9, 12, 13},
        "p_peak": 0.22,
        "p_base": 0.02,
        "amps": (3.0, 3.9),
        "volts": (228, 234),
    },
    "airfryer": {
        "on": (900, 1600),
        "standby": (0, 1),
        "peak_hours": {12, 13, 17, 18, 19, 20},
        "p_peak": 0.14,
        "p_base": 0.02,
        "amps": (3.9, 7.0),
        "volts": (228, 234),
    },
}


def _coerce_int(value: str | int | None, default: int = 0) -> int:
    if value in (None, "", "FAILED"):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def parse_cardiff_participants_csv(
    csv_path: str | Path,
    allowed_statuses: tuple[str, ...] = ("OK",),
) -> list[dict]:
    """Load participant export rows used by the Cardiff provisioning script."""
    rows: list[dict] = []
    path = Path(csv_path)

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for participant_index, row in enumerate(csv.DictReader(handle)):
            status = (row.get("Status") or "").strip()
            if allowed_statuses and status not in allowed_statuses:
                continue

            rows.append(
                {
                    "participant_index": participant_index,
                    "number": _coerce_int(row.get("Number"), participant_index + 1),
                    "name": (row.get("Name") or "").strip(),
                    "email": (row.get("Email") or "").strip(),
                    "password": row.get("Password") or "",
                    "home_id": _coerce_int(row.get("HomeID"), 0),
                    "user_id": _coerce_int(row.get("UserID"), 0),
                    "location": row.get("Location") or "",
                    "home_type": (row.get("HomeType") or "other").strip().lower(),
                    "occupants": _coerce_int(row.get("Occupants"), 1),
                    "device_count": _coerce_int(row.get("Devices"), 0),
                    "status": status,
                }
            )

    return rows


def planned_device_keys(device_count: int, participant_index: int) -> list[str]:
    """Pick a reproducible set of appliance keys when live device metadata is unavailable."""
    clamped_count = max(0, min(device_count, len(DEVICE_KEYS)))
    if clamped_count == 0:
        return []

    rotation = participant_index % len(DEVICE_KEYS)
    rotated = DEVICE_KEYS[rotation:] + DEVICE_KEYS[:rotation]
    return list(rotated[:clamped_count])


def household_factor(num_occupants: int, home_type: str, participant_index: int = 0) -> float:
    """Create a stable household-level usage multiplier from participant metadata."""
    normalized_occupants = max(1, min(num_occupants or 1, 6))
    base_factor = 0.72 + (normalized_occupants * 0.08)
    home_factor = HOME_TYPE_FACTORS.get((home_type or "other").lower(), HOME_TYPE_FACTORS["other"])
    variation = ((participant_index % 7) - 3) * 0.03
    return round(max(0.55, min((base_factor * home_factor) + variation, 1.85)), 2)


def build_row_seed(seed: int, participant_key: str, appliance_key: str, recorded_at: datetime) -> str:
    return f"{seed}:{participant_key}:{appliance_key}:{recorded_at.isoformat()}"


def generate_appliance_reading(
    appliance_key: str,
    recorded_at: datetime,
    factor: float = 1.0,
    interval_minutes: int = 5,
    rng: random.Random | None = None,
) -> dict:
    """Generate one realistic reading for a given appliance and timestamp."""
    rng = rng or random.Random()
    profile = APPLIANCE_PROFILES.get(appliance_key)

    if not profile:
        watts = rng.uniform(1, 5)
        volts = rng.uniform(228, 234)
        rounded_watts = round(watts, 2)
        rounded_volts = round(volts, 1)
        return {
            "power_watts": rounded_watts,
            "current_amps": round(rounded_watts / rounded_volts, 3),
            "voltage_volts": rounded_volts,
            "energy_kwh": round((rounded_watts / 1000) * (interval_minutes / 60), 6),
            "switch_state": "unknown",
        }

    is_peak = recorded_at.hour in profile["peak_hours"]
    is_weekend = recorded_at.weekday() >= 5
    daily_bias = 1.12 if is_weekend else 1.0
    p_on = (profile["p_peak"] if is_peak else profile["p_base"]) * factor * daily_bias
    is_on = rng.random() < min(0.95, p_on)

    if is_on:
        watts = rng.uniform(*profile["on"]) * rng.uniform(0.94, 1.08) * factor
        amps = rng.uniform(*profile["amps"])
        switch_state = "on"
    else:
        watts = rng.uniform(*profile["standby"])
        switch_state = "off" if watts < 2 else "unknown"
        amps = 0.0

    volts = rng.uniform(*profile["volts"]) * rng.uniform(0.99, 1.01)
    if is_on:
        amps = watts / volts

    rounded_watts = round(watts, 2)
    rounded_volts = round(volts, 1)
    rounded_amps = round(amps if not is_on else (rounded_watts / rounded_volts), 3)

    return {
        "power_watts": rounded_watts,
        "current_amps": rounded_amps,
        "voltage_volts": rounded_volts,
        "energy_kwh": round((rounded_watts / 1000) * (interval_minutes / 60), 6),
        "switch_state": switch_state,
    }


def iter_timestamps(start_at: datetime, end_at: datetime, interval_minutes: int) -> Iterator[datetime]:
    current = start_at
    step = timedelta(minutes=interval_minutes)
    while current <= end_at:
        yield current
        current += step