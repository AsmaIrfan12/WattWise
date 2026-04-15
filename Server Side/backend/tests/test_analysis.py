from datetime import date

from app.routers.analysis import _build_community_benchmark_payload


def test_build_community_benchmark_payload_marks_below_average_usage():
    payload = _build_community_benchmark_payload(
        target_date=date(2026, 4, 13),
        registered_home_count=1,
        user_rows=[{"home_id": 1, "total_kwh": 4.2, "total_cost_gbp": 1.15}],
        community_rows=[
            {"home_id": 1, "total_kwh": 4.2, "total_cost_gbp": 1.15},
            {"home_id": 2, "total_kwh": 5.1, "total_cost_gbp": 1.42},
            {"home_id": 3, "total_kwh": 6.3, "total_cost_gbp": 1.75},
        ],
    )

    assert payload["has_data"] is True
    assert payload["comparison"]["status"] == "below_average"
    assert payload["community"]["peer_homes_compared"] == 2
    assert payload["comparison"]["better_than_percent"] == 100.0
    assert payload["community"]["avg_home_kwh"] == 5.7


def test_build_community_benchmark_payload_handles_missing_peer_data():
    payload = _build_community_benchmark_payload(
        target_date=None,
        registered_home_count=2,
        user_rows=[],
        community_rows=[],
    )

    assert payload["has_data"] is False
    assert payload["date"] is None
    assert payload["user"]["registered_homes"] == 2
    assert payload["community"]["peer_homes_compared"] == 0
    assert payload["comparison"]["status"] == "at_average"