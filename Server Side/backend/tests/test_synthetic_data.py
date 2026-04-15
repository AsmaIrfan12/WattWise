import random
from datetime import datetime

from app.synthetic_data import (
    build_row_seed,
    generate_appliance_reading,
    household_factor,
    planned_device_keys,
)


def test_planned_device_keys_are_rotated_and_clamped():
    assert planned_device_keys(0, participant_index=0) == []
    assert planned_device_keys(2, participant_index=0) == ["airfryer", "dishwasher"]
    assert planned_device_keys(3, participant_index=2) == ["kettle", "microwave", "toaster"]
    assert len(planned_device_keys(99, participant_index=1)) == 6


def test_household_factor_scales_with_home_size_and_occupants():
    compact = household_factor(2, "flat", participant_index=0)
    family = household_factor(5, "detached", participant_index=0)

    assert compact < family
    assert compact >= 0.55
    assert family <= 1.85


def test_generate_appliance_reading_is_deterministic_for_same_seed():
    recorded_at = datetime(2026, 4, 14, 18, 0, 0)
    seed = build_row_seed(20260414, "aled@example.com", "kettle", recorded_at)

    reading_one = generate_appliance_reading(
        "kettle",
        recorded_at,
        factor=1.2,
        interval_minutes=30,
        rng=random.Random(seed),
    )
    reading_two = generate_appliance_reading(
        "kettle",
        recorded_at,
        factor=1.2,
        interval_minutes=30,
        rng=random.Random(seed),
    )

    assert reading_one == reading_two
    assert reading_one["switch_state"] in {"on", "off", "unknown"}
    assert reading_one["power_watts"] >= 0
    assert reading_one["energy_kwh"] == round((reading_one["power_watts"] / 1000) * 0.5, 6)