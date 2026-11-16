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


# ── Phase 1: the alert → decision → analysis loop (pure parts) ────────────────
import math

from app.decision_tracker import effectiveness_score
from app.notification_engine import default_dedup_key
from app.persona_classifier import response_latency_feature, NO_RESPONSE_LATENCY_SECONDS
from app.scheduler import decision_response_score, NEUTRAL_DECISION_SCORE


class TestEffectivenessScore:
    def test_share_of_before_energy_saved(self):
        assert effectiveness_score(2.0, 1.0, "ACCEPTED", None) == 50.0

    def test_fast_action_earns_a_bonus(self):
        assert effectiveness_score(2.0, 1.0, "ACCEPTED", 120) == 60.0
        assert effectiveness_score(2.0, 1.0, "CUSTOM_ACTION", 900) == 55.0

    def test_fast_skip_earns_nothing(self):
        # Before the fix a REJECTED decision answered within 5 min scored 10 with no saving.
        assert effectiveness_score(2.0, 0.0, "REJECTED", 60) == 0.0

    def test_no_bonus_without_a_saving(self):
        assert effectiveness_score(2.0, -0.5, "ACCEPTED", 60) == 0.0

    def test_capped_at_100_and_floored_at_0(self):
        assert effectiveness_score(1.0, 1.0, "ACCEPTED", 10) == 100.0
        assert effectiveness_score(1.0, -3.0, "ACCEPTED", None) == 0.0

    def test_zero_before_energy(self):
        assert effectiveness_score(0.0, 0.0, "ACCEPTED", 10) == 0.0


class TestDecisionResponseScore:
    def test_no_actionable_alerts_is_neutral(self):
        assert decision_response_score(0, 0, None) == NEUTRAL_DECISION_SCORE

    def test_ignoring_every_alert_is_penalised(self):
        assert decision_response_score(4, 0, None) == 25.0

    def test_answering_everything_with_unmeasured_impact(self):
        assert decision_response_score(4, 4, None) == 75.0

    def test_genuine_zero_effectiveness_is_not_replaced_by_a_default(self):
        assert decision_response_score(2, 2, 0.0) == 50.0

    def test_full_marks(self):
        assert decision_response_score(3, 3, 100.0) == 100.0

    def test_more_decisions_than_alerts_does_not_exceed_100(self):
        assert decision_response_score(1, 5, 100.0) == 100.0


class TestDedupKeyAndLatency:
    def test_device_and_home_slots_differ(self):
        assert default_dedup_key("HIGH_CONSUMPTION", 7) == "HIGH_CONSUMPTION:7"
        assert default_dedup_key("ENERGY_ALERT", None) == "ENERGY_ALERT:home"

    def test_never_responded_is_slowest_not_fastest(self):
        never = response_latency_feature(None)
        assert never == math.log1p(NO_RESPONSE_LATENCY_SECONDS)
        assert never > response_latency_feature(600) > response_latency_feature(0)
