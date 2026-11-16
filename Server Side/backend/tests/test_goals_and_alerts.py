"""
Pure-function tests for the goal period logic and the unusual-usage (HIGH_CONSUMPTION)
rule — the two pieces behind the user-facing alerts.
"""
from datetime import date

import pytest

from app.goal_tracker import period_bounds, previous_period_bounds
from app.scheduler import is_anomalous_hour


class TestGoalPeriods:
    def test_daily_is_today(self):
        assert period_bounds("daily", date(2026, 11, 5), date(2026, 11, 16)) == (date(2026, 11, 16), date(2026, 11, 16))

    def test_weekly_first_period(self):
        assert period_bounds("weekly", date(2026, 11, 5), date(2026, 11, 9)) == (date(2026, 11, 5), date(2026, 11, 11))

    def test_weekly_rolls_over_aligned_to_start(self):
        # 16 Nov is in the second week of a goal that started 5 Nov (12–18 Nov)
        assert period_bounds("weekly", date(2026, 11, 5), date(2026, 11, 16)) == (date(2026, 11, 12), date(2026, 11, 18))

    def test_weekly_period_boundary_day(self):
        assert period_bounds("weekly", date(2026, 11, 5), date(2026, 11, 12))[0] == date(2026, 11, 12)
        assert period_bounds("weekly", date(2026, 11, 5), date(2026, 11, 11))[0] == date(2026, 11, 5)

    def test_monthly_clips_first_period_to_start_date(self):
        assert period_bounds("monthly", date(2026, 11, 5), date(2026, 11, 16)) == (date(2026, 11, 5), date(2026, 11, 30))

    def test_monthly_following_month_is_whole_month(self):
        assert period_bounds("monthly", date(2026, 11, 5), date(2026, 12, 3)) == (date(2026, 12, 1), date(2026, 12, 31))

    def test_before_start_uses_first_period(self):
        assert period_bounds("weekly", date(2026, 11, 5), date(2026, 11, 1)) == (date(2026, 11, 5), date(2026, 11, 11))

    def test_previous_period_none_in_first_period(self):
        assert previous_period_bounds("weekly", date(2026, 11, 5), date(2026, 11, 9)) is None

    def test_previous_period_weekly(self):
        assert previous_period_bounds("weekly", date(2026, 11, 5), date(2026, 11, 16)) == (date(2026, 11, 5), date(2026, 11, 11))

    def test_previous_period_monthly(self):
        assert previous_period_bounds("monthly", date(2026, 11, 5), date(2026, 12, 2)) == (date(2026, 11, 5), date(2026, 11, 30))


class TestAnomalyRule:
    DEFAULTS = dict(threshold_factor=3.0, min_kwh=0.25, min_baseline_kwh=0.02, min_baseline_samples=7)

    def test_single_kettle_boil_is_not_an_anomaly(self):
        # 0.07 kWh against a 0.008 kWh baseline was reported as "9× usual" before the floors
        assert is_anomalous_hour(0.07, 0.008, 30, **self.DEFAULTS) is False

    def test_genuine_spike_flagged(self):
        assert is_anomalous_hour(1.5, 0.3, 30, **self.DEFAULTS) is True

    def test_below_factor_not_flagged(self):
        assert is_anomalous_hour(0.8, 0.3, 30, **self.DEFAULTS) is False

    def test_too_little_history_not_flagged(self):
        assert is_anomalous_hour(1.5, 0.3, 3, **self.DEFAULTS) is False

    def test_tiny_baseline_not_flagged_even_if_large_ratio(self):
        assert is_anomalous_hour(0.3, 0.01, 30, **self.DEFAULTS) is False

    @pytest.mark.parametrize("kwh", [0.249, 0.0])
    def test_absolute_floor(self, kwh):
        assert is_anomalous_hour(kwh, 0.05, 30, **self.DEFAULTS) is False

    def test_exactly_at_factor_is_flagged(self):
        assert is_anomalous_hour(0.9, 0.3, 7, **self.DEFAULTS) is True
