"""
Health suggestions on every alert, and one community for every account.

Both are behaviours the owner asked for explicitly:
  * each appliance alert carries a health/wellbeing suggestion (a signature feature of
    the original single-home app), for ALL appliances;
  * real and synthetic homes are ranked and analysed together, by the same rules.
"""
import inspect

import pytest

from app import cohorts, decision_tracker, persona_classifier, scheduler
from app.appliance_scenarios import APPLIANCE_SCENARIOS, calculate_optimization, generate_alerts
from app.health_tips import (
    DEFAULT_HEALTH_TIPS,
    GENERAL_HEALTH_TIPS,
    SCENARIO_HEALTH_TIPS,
    canonical_appliance,
    general_health_tips,
    health_tips_for,
    pick_health_tip,
    scenario_health_tip,
    with_health_tip,
)
from app.routers import admin, admin_decisions, admin_homes, analysis
from app.routers.smart_notifications import _health_tip_of_the_day
from app.scheduler import community_rank

# Appliance types a user can pick when adding a device in the dashboard.
DEVICE_TYPES = ["kettle", "washing_machine", "dishwasher", "dryer", "microwave", "toaster",
                "airfryer", "gaming_console", "tv", "other"]

# Usage that trips every scenario of every appliance at least once across the two sets.
_HEAVY = {"N": 20, "eaec": 9.0, "dailyEAEC": 30.0, "duration": 600, "shortUseCount": 9,
          "standbyTime": 900, "standbyPower": 30, "avgPower": 3000, "lateNightHours": 4,
          "isPeakTime": True, "keepWarmTime": 300}


class TestEveryAlertHasAHealthTip:

    def test_every_scenario_of_every_appliance_has_a_tip(self):
        missing = [
            f"{appliance}/{scenario['scenario']}"
            for appliance, scenarios in APPLIANCE_SCENARIOS.items()
            for scenario in scenarios
            if not scenario_health_tip(appliance, scenario["scenario"])
        ]
        assert missing == [], f"scenarios without a health tip: {missing}"

    def test_no_tip_is_orphaned(self):
        """A tip keyed to a scenario name that no longer exists would never be shown."""
        for appliance, tips in SCENARIO_HEALTH_TIPS.items():
            names = {s["scenario"] for s in APPLIANCE_SCENARIOS[appliance]}
            assert set(tips) <= names, f"{appliance}: tips for unknown scenarios {set(tips) - names}"

    @pytest.mark.parametrize("appliance", sorted(APPLIANCE_SCENARIOS))
    def test_every_notification_is_energy_advice_followed_by_its_health_tip(self, appliance):
        """The structure of the original app's notifications, for every appliance."""
        opt = calculate_optimization(appliance, temperature=5.0, humidity=90.0, pressure=101.3, usage_data=dict(_HEAVY))
        assert opt["alerts"], f"{appliance}: heavy usage should trigger at least one alert"
        for alert in opt["alerts"]:
            where = f"{appliance}/{alert['scenario']}"
            assert alert["health_tip"], f"{where} has no health tip"
            assert alert["message"].startswith(alert["energy_message"]), where
            assert alert["message"].endswith(alert["health_tip"]), where
            assert alert["message"].count(alert["health_tip"]) == 1, where     # said once
            assert alert["health_tip"] not in alert["energy_message"], where
        assert opt["health_tip"] == opt["alerts"][0]["health_tip"]  # most relevant first

    def test_the_four_original_dryer_notifications_read_exactly_as_in_the_old_app(self):
        """old/services/energy-calculator.js, APPLIANCE_SCENARIOS.dryer — word for word."""
        data = {"N": 3, "eaec": 4.8, "dailyEAEC": 7.5, "fH": 1.2, "fT": 1.0, "fP": 1.0}
        messages = {a["scenario"]: a["message"] for a in generate_alerts("dryer", data)}
        assert messages == {
            "High energy per cycle":
                "⚠️ Your dryer used 4.80 kWh this cycle — that's higher than normal. Try using a shorter or eco "
                "cycle to save energy. 💚 Health tip: Line-drying clothes in fresh air naturally sanitizes them "
                "and is better for sensitive skin!",
            "Daily consumption high":
                "💡 You've used the dryer 7.5 kWh today. That's quite a bit! Consider air drying some items to "
                "save money. 🌿 Fresh air drying reduces static and chemical exposure from dryer sheets.",
            "Humidity spike adjustment":
                "💧 High humidity is making your dryer work 20% harder. Wait for a drier day or use a "
                "dehumidifier to save energy. 🏠 Lower humidity also reduces mold growth and improves "
                "respiratory health!",
            "Multiple cycles per day":
                "⚡ You've run the dryer 3 times today. Try combining your laundry loads to save energy and "
                "money. 🧺 Fewer laundry sessions means less dust circulation in your home.",
        }

    def test_other_appliances_use_the_same_structure(self):
        alert = generate_alerts("kettle", {"N": 13, "fT": 1.0, "fH": 1.0, "fP": 1.0, "temperature": 20})[0]
        assert alert["message"] == (
            "☕ You've boiled the kettle 13 times today — that's a lot! Only boil the water you need and "
            "consider a flask to keep it hot. 💚 Health tip: Aim for 6 to 8 cups of fluid a day, and try "
            "swapping some teas and coffees for water or caffeine-free drinks.")

    def test_with_health_tip_leaves_text_alone_when_there_is_no_tip(self):
        assert with_health_tip("Energy advice.", None) == "Energy advice."
        assert with_health_tip("Energy advice. ", "Drink water.") == "Energy advice. 💚 Health tip: Drink water."

    def test_the_original_dryer_tips_are_restored_word_for_word(self):
        tips = SCENARIO_HEALTH_TIPS["dryer"]
        assert tips["High energy per cycle"] == (
            "Line-drying clothes in fresh air naturally sanitizes them and is better for sensitive skin!")
        assert tips["Daily consumption high"] == (
            "Fresh air drying reduces static and chemical exposure from dryer sheets.")
        assert tips["Humidity spike adjustment"] == (
            "Lower humidity also reduces mold growth and improves respiratory health!")
        assert tips["Multiple cycles per day"] == (
            "Fewer laundry sessions means less dust circulation in your home.")

    @pytest.mark.parametrize("device_type", DEVICE_TYPES)
    def test_every_device_type_has_tips_even_with_no_alert(self, device_type):
        opt = calculate_optimization(device_type, temperature=20.0, humidity=50.0, pressure=101.3, usage_data={})
        assert opt["health_tips"], f"{device_type}: no health tips"
        assert opt["health_tip"] == opt["health_tips"][0]
        assert all(isinstance(t, str) and len(t) > 20 for t in opt["health_tips"])

    def test_aliases_share_tips(self):
        assert canonical_appliance("washing_machine") == "washingmachine"
        assert canonical_appliance("Gaming Console") == "xbox"
        assert general_health_tips("washing_machine") == general_health_tips("washingmachine")
        assert generate_alerts("washing_machine", {**_HEAVY, "fT": 1, "fH": 1.3, "fP": 1, "humidity": 90, "temperature": 5})[0]["health_tip"]

    def test_unknown_appliance_falls_back_to_home_tips(self):
        assert general_health_tips("fridge_freezer") == DEFAULT_HEALTH_TIPS
        assert general_health_tips(None) == DEFAULT_HEALTH_TIPS
        assert pick_health_tip("other", 7) in DEFAULT_HEALTH_TIPS

    def test_general_tip_rotates_and_is_deterministic(self):
        tips = GENERAL_HEALTH_TIPS["kettle"]
        assert [pick_health_tip("kettle", i) for i in range(len(tips))] == tips
        assert pick_health_tip("kettle", 4) == pick_health_tip("kettle", 4 + len(tips))

    def test_triggered_tips_come_before_general_ones_without_repeats(self):
        alerts = [{"scenario": "Late night usage"}, {"scenario": "Late night usage"}]
        tips = health_tips_for("kettle", alerts)
        assert tips[0] == SCENARIO_HEALTH_TIPS["kettle"]["Late night usage"]
        assert len(tips) == len(set(tips))
        assert set(GENERAL_HEALTH_TIPS["kettle"]) <= set(tips)


class TestHealthTipOfTheDay:

    def _device(self, device_id, key, alerts=None, tip=None):
        return {"device_id": device_id, "device_name": key.title(), "appliance_key": key,
                "alerts": alerts or [], "health_tip": tip}

    def test_none_without_devices(self):
        assert _health_tip_of_the_day([]) is None

    def test_a_device_with_an_alert_comes_first(self):
        devices = [self._device(1, "kettle"),
                   self._device(2, "toaster", alerts=[{"scenario": "High daily cycles"}], tip="Golden, not brown.")]
        picked = _health_tip_of_the_day(devices)
        assert picked["device_id"] == 2 and picked["tip"] == "Golden, not brown."

    def test_otherwise_one_of_the_users_own_appliances(self):
        devices = [self._device(5, "kettle"), self._device(9, "dishwasher")]
        picked = _health_tip_of_the_day(devices)
        assert picked["device_id"] in (5, 9)
        assert picked["tip"] in general_health_tips(picked["appliance_key"])


class TestOneCommunity:
    """No code path may treat an account differently because it is real or synthetic."""

    def test_positions_run_through_one_list(self):
        total = 51                                   # 50 generated homes + 1 home with a Raspberry Pi
        ranks = [community_rank(i, total) for i in range(total)]
        assert [r[0] for r in ranks] == list(range(1, 52))
        assert {r[1] for r in ranks} == {51}         # everyone is "of 51"
        assert ranks[0][2] == 100.0 and ranks[-1][2] == 0.0

    def test_a_single_home_is_first_of_one(self):
        assert community_rank(0, 1) == (1, 1, 0.0)

    def test_all_accounts_is_the_default_everywhere(self):
        assert cohorts.DEFAULT_COHORT == "all"
        assert cohorts.normalise_cohort(None) == "all"
        assert cohorts.user_cohort_clause("all") is None
        assert cohorts.decision_cohort_clause("all") is None
        for fn in (admin.get_rankings, admin_decisions.list_decisions, admin_decisions.notification_funnel,
                   admin_homes.homes_status):
            assert inspect.signature(fn).parameters["cohort"].default.default == "all", fn.__name__
        sig = inspect.signature(decision_tracker.DecisionTracker.get_system_impact_report)
        assert sig.parameters["cohort"].default == "all"
        sig = inspect.signature(decision_tracker.DecisionTracker.get_user_impact_report)
        assert sig.parameters["include_simulated"].default is True

    def test_ranking_and_leaderboard_never_look_at_the_synthetic_flag(self):
        for fn in (scheduler.compute_rankings, analysis.get_leaderboard, analysis.get_my_rankings):
            assert "is_synthetic" not in inspect.getsource(fn), fn.__name__

    def test_persona_classification_uses_the_same_rule_for_every_user(self):
        src = inspect.getsource(persona_classifier)
        assert "is_synthetic" not in src
        # Generated decisions are left out for EVERY account (see test_account_filter.py).
        assert "UserDecision.is_simulated.is_(False)" in src
