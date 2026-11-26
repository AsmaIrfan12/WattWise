"""
The admin "Show" filter (all / real / synthetic accounts) works on every tab, and
generated decisions never feed a ranking or a persona.
"""
import inspect

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects import mysql

from app import persona_classifier, scheduler
from app.cohorts import CohortScope
from app.models import Device, EnergyRanking, Home, HourlySummary, HomeDailyTotal, Notification, User
from app.routers import admin, admin_decisions, admin_homes


def sql(query) -> str:
    return str(query.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))


class TestCohortScope:

    def test_all_accounts_adds_no_condition(self):
        scope = CohortScope("all")
        assert scope.active is False
        assert scope.user_rows() == scope.users(Notification.user_id) == []
        assert scope.homes(HomeDailyTotal.home_id) == scope.devices(HourlySummary.device_id) == []
        q = select(HourlySummary.total_kwh).where(HourlySummary.total_kwh > 0, *scope.devices(HourlySummary.device_id))
        assert "is_synthetic" not in sql(q)

    def test_default_is_all(self):
        assert CohortScope(None).cohort == "all"

    @pytest.mark.parametrize("cohort,flag", [("real", "false"), ("synthetic", "true")])
    def test_users_are_filtered_by_the_flag(self, cohort, flag):
        scope = CohortScope(cohort)
        text = sql(select(Notification.id).where(*scope.users(Notification.user_id))).lower()
        assert "notifications.user_id in (select users.id" in text
        assert f"users.is_synthetic is {flag}" in text

    def test_homes_are_reached_through_their_owner(self):
        text = sql(select(HomeDailyTotal.total_kwh).where(*CohortScope("real").homes(HomeDailyTotal.home_id))).lower()
        assert "home_daily_totals.home_id in (select homes.id" in text
        assert "join users on users.id = homes.user_id" in text and "users.is_synthetic is false" in text

    def test_devices_are_reached_through_home_and_owner(self):
        text = sql(select(HourlySummary.total_kwh).where(*CohortScope("synthetic").devices(HourlySummary.device_id))).lower()
        assert "hourly_summary.device_id in (select devices.id" in text
        assert "join homes on devices.home_id = homes.id" in text and "users.is_synthetic is true" in text

    def test_a_query_that_already_has_users_gets_a_plain_condition(self):
        scope = CohortScope("real")
        q = select(Device.id).join(Home, Device.home_id == Home.id).join(User, User.id == Home.user_id).where(*scope.user_rows())
        assert sql(q).lower().count("select") == 1          # no sub-select needed

    def test_unknown_choice_is_refused(self):
        with pytest.raises(HTTPException) as err:
            CohortScope("everyone")
        assert err.value.status_code == 422


# Every admin view that shows account data. A view missing here ignored the filter:
# choosing "Real" or "Synthetic" changed nothing on that tab.
FILTERED_VIEWS = [
    admin.get_dashboard, admin.list_users, admin.list_personas, admin.get_persona_users,
    admin.get_personas_history, admin.get_rankings, admin.get_decision_analytics,
    admin.get_energy_analytics, admin.get_device_timeseries, admin.get_persona_comparison,
    admin.get_user_interaction_stats, admin.get_device_status, admin.get_energy_sankey,
    admin.get_anomalies, admin.get_admin_notifications_breakdown,
    admin_decisions.list_decisions, admin_decisions.notification_funnel, admin_decisions.list_campaigns,
    admin_decisions.get_campaign, admin_homes.homes_status,
]


class TestEveryTabHonoursTheFilter:

    @pytest.mark.parametrize("view", FILTERED_VIEWS, ids=lambda f: f.__name__)
    def test_view_takes_the_choice_and_defaults_to_all(self, view):
        params = inspect.signature(view).parameters
        assert "cohort" in params, f"{view.__name__} ignores the account filter"
        assert params["cohort"].default.default == "all"

    @pytest.mark.parametrize("view", [
        admin.get_dashboard, admin.list_personas, admin.get_persona_users, admin.get_personas_history,
        admin.get_energy_analytics, admin.get_device_timeseries, admin.get_persona_comparison,
        admin.get_user_interaction_stats, admin.get_device_status, admin.get_energy_sankey,
        admin.get_anomalies, admin.get_admin_notifications_breakdown,
    ], ids=lambda f: f.__name__)
    def test_every_query_in_the_view_is_scoped(self, view):
        """Accepting the parameter is not enough: each data query must use it."""
        src = inspect.getsource(view)
        assert "scope = CohortScope(cohort)" in src
        queries = src.count("select(")
        scoped = src.count("*scope.")
        assert scoped >= 1
        # Sub-selects, lookups of the personas table and the join-back in device status
        # need no scope of their own; everything else does.
        unscoped_allowed = {"list_personas": 1, "get_personas_history": 1, "get_device_status": 2}.get(view.__name__, 0)
        assert scoped >= queries - unscoped_allowed, f"{view.__name__}: {queries} queries, only {scoped} scoped"


class TestGeneratedDecisionsStayOutOfTheScores:

    def test_persona_features_ignore_generated_decisions_for_every_account(self):
        src = inspect.getsource(persona_classifier._extract_features)
        assert "UserDecision.is_simulated.is_(False)" in src
        assert "is_synthetic" not in inspect.getsource(persona_classifier)   # one rule for all accounts

    def test_rankings_ignore_generated_decisions(self):
        src = inspect.getsource(scheduler.compute_rankings)
        assert "if simulated:" in src and "continue" in src
        assert "is_synthetic" not in src

    def test_a_test_send_can_be_flagged(self):
        src = inspect.getsource(admin_decisions.mark_campaign_as_test)
        assert "_require_admin" in src and "d.is_simulated = True" in src
        assert EnergyRanking is not None
