from datetime import date

from app.routers.admin import _build_admin_community_snapshot


def test_build_admin_community_snapshot_calculates_latest_totals():
    payload = _build_admin_community_snapshot(
        target_date=date(2026, 4, 13),
        registered_home_count=4,
        community_rows=[
            {"home_id": 1, "total_kwh": 3.8, "total_cost_gbp": 1.02},
            {"home_id": 2, "total_kwh": 4.4, "total_cost_gbp": 1.19},
            {"home_id": 3, "total_kwh": 5.0, "total_cost_gbp": 1.32},
        ],
    )

    assert payload["has_data"] is True
    assert payload["date"] == "2026-04-13"
    assert payload["registered_homes"] == 4
    assert payload["homes_with_data"] == 3
    assert payload["avg_home_kwh"] == 4.4
    assert payload["min_home_kwh"] == 3.8
    assert payload["max_home_kwh"] == 5.0
    assert payload["total_cost_gbp"] == 3.53


def test_build_admin_community_snapshot_handles_empty_state():
    payload = _build_admin_community_snapshot(
        target_date=None,
        registered_home_count=2,
        community_rows=[],
    )

    assert payload["has_data"] is False
    assert payload["date"] is None
    assert payload["registered_homes"] == 2
    assert payload["homes_with_data"] == 0
    assert payload["avg_home_kwh"] == 0.0