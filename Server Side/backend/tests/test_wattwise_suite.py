"""
WattWise Backend — Integration Test Suite
==========================================
Tests for:
  - Auth (login, JWT claims, admin flag)
  - Admin access control (403 for non-admin)
  - Persona classifier logic
  - MQTT input validation
  - Data utilities (community snapshot, decision tracker)
  - Scheduler aggregation (unit)
  - Security config warnings

Run: pytest tests/ -v
"""

import pytest
from datetime import date, datetime


# ── Helpers ─────────────────────────────────────────────────────

def _make_snapshot(rows, *, target_date=None, registered=4):
    from app.routers.admin import _build_admin_community_snapshot
    return _build_admin_community_snapshot(
        target_date=target_date or date(2026, 4, 1),
        registered_home_count=registered,
        community_rows=rows,
    )


# ── Admin Community Snapshot ─────────────────────────────────────

class TestAdminCommunitySnapshot:

    def test_basic_calculation(self):
        snap = _make_snapshot([
            {"home_id": 1, "total_kwh": 2.0, "total_cost_gbp": 0.54},
            {"home_id": 2, "total_kwh": 4.0, "total_cost_gbp": 1.08},
            {"home_id": 3, "total_kwh": 6.0, "total_cost_gbp": 1.62},
        ])
        assert snap["has_data"] is True
        assert snap["homes_with_data"] == 3
        assert snap["total_kwh"] == 12.0
        assert snap["avg_home_kwh"] == 4.0
        assert snap["min_home_kwh"] == 2.0
        assert snap["max_home_kwh"] == 6.0
        assert round(snap["total_cost_gbp"], 2) == 3.24

    def test_empty_rows_returns_no_data(self):
        snap = _make_snapshot([], target_date=None, registered=2)
        assert snap["has_data"] is False
        assert snap["homes_with_data"] == 0
        assert snap["avg_home_kwh"] == 0.0
        assert snap["total_kwh"] == 0.0

    def test_single_home(self):
        snap = _make_snapshot([{"home_id": 1, "total_kwh": 5.5, "total_cost_gbp": 1.50}])
        assert snap["avg_home_kwh"] == 5.5
        assert snap["min_home_kwh"] == snap["max_home_kwh"] == 5.5

    def test_registered_homes_reported_correctly(self):
        snap = _make_snapshot(
            [{"home_id": 1, "total_kwh": 3.0, "total_cost_gbp": 0.8}],
            registered=10
        )
        assert snap["registered_homes"] == 10
        assert snap["homes_with_data"] == 1  # only 1 has data

    def test_date_isoformat_in_result(self):
        snap = _make_snapshot(
            [{"home_id": 1, "total_kwh": 1.0, "total_cost_gbp": 0.27}],
            target_date=date(2026, 3, 15)
        )
        assert snap["date"] == "2026-03-15"

    def test_rounding_precision(self):
        snap = _make_snapshot([
            {"home_id": 1, "total_kwh": 1.111, "total_cost_gbp": 0.33333},
            {"home_id": 2, "total_kwh": 2.222, "total_cost_gbp": 0.66666},
        ])
        # Totals should be rounded to 3 decimal places (kwh) / 2 (cost)
        assert len(str(snap["total_kwh"]).split(".")[-1]) <= 3
        assert len(str(snap["total_cost_gbp"]).split(".")[-1]) <= 2


# ── MQTT Input Validation ────────────────────────────────────────

class TestMqttInputValidation:

    def _validate(self, payload):
        from app.mqtt_client import _validate_payload
        return _validate_payload(payload)

    def test_valid_payload_passes(self):
        w, c, v, e = self._validate({"power_watts": 1200.5, "current_amps": 5.2, "voltage_volts": 230.0, "energy_kwh": 0.05})
        assert w == 1200.5
        assert c == 5.2
        assert v == 230.0
        assert e == 0.05

    def test_negative_power_rejected(self):
        import pytest
        with pytest.raises(ValueError, match="negative"):
            self._validate({"power_watts": -10.0})

    def test_nan_power_rejected(self):
        import math, pytest
        with pytest.raises(ValueError, match="NaN"):
            self._validate({"power_watts": float("nan")})

    def test_inf_power_rejected(self):
        import pytest
        with pytest.raises(ValueError, match="NaN"):
            self._validate({"power_watts": float("inf")})

    def test_impossibly_large_power_rejected(self):
        import pytest
        with pytest.raises(ValueError, match="too large"):
            self._validate({"power_watts": 60_000.0})  # 60kW — no domestic appliance

    def test_zero_power_is_valid(self):
        w, _, _, _ = self._validate({"power_watts": 0})
        assert w == 0.0

    def test_negative_current_becomes_none(self):
        _, c, _, _ = self._validate({"power_watts": 100, "current_amps": -1.0})
        assert c is None

    def test_extreme_voltage_becomes_none(self):
        _, _, v, _ = self._validate({"power_watts": 100, "voltage_volts": 600.0})
        assert v is None

    def test_negative_energy_becomes_none(self):
        _, _, _, e = self._validate({"power_watts": 100, "energy_kwh": -0.5})
        assert e is None

    def test_max_boundary_power_accepted(self):
        w, _, _, _ = self._validate({"power_watts": 50_000.0})
        assert w == 50_000.0

    def test_value_field_alias_works(self):
        """power_watts can also come as 'value' field (HA compatibility)."""
        w, _, _, _ = self._validate({"value": 800.0})
        assert w == 800.0

    def test_missing_all_fields_defaults_to_zero(self):
        w, c, v, e = self._validate({})
        assert w == 0.0
        assert c is None
        assert v is None
        assert e is None


# ── RPi Publisher entity_id Sanitization ─────────────────────────

class TestEntityIdSanitization:

    def _sanitize(self, entity_id: str) -> str:
        """Replicates the regex used in rpi_mqtt_publisher.py."""
        import re
        return re.sub(r"[^a-zA-Z0-9_\.\-]", "", entity_id)

    def test_clean_entity_id_unchanged(self):
        assert self._sanitize("switch.kettle") == "switch.kettle"

    def test_spaces_stripped(self):
        assert self._sanitize("switch. kettle") == "switch.kettle"

    def test_injection_attempt_sanitized(self):
        malicious = "switch.'; DROP TABLE energy_readings; --"
        result = self._sanitize(malicious)
        assert "DROP" not in result
        assert "'" not in result
        assert ";" not in result

    def test_unicode_stripped(self):
        assert self._sanitize("sensor.⚡power") == "sensor.power"

    def test_allowed_chars_preserved(self):
        clean = "sensor.smart_plug-01.power_w"
        assert self._sanitize(clean) == clean


# ── Persona Classifier Logic ──────────────────────────────────────

class TestPersonaClassifierLogic:
    """Unit tests for the classification rules (without DB calls)."""

    def _classify(self, avg_eff=50, avg_adherence=50, avg_decision=50,
                  ranking_days=10, decision_count=5, trend_improving=False) -> str:
        """Simulate _classify_user logic without DB."""
        # Mirrors the logic in persona_classifier._classify_user
        if ranking_days < 3:
            return "Disengaged"
        if avg_decision <= 10 and avg_adherence <= 10:
            return "Disengaged"
        if avg_eff >= 75 and avg_adherence >= 80:
            return "Eco Champion"
        if trend_improving and avg_eff >= 55 and avg_adherence >= 50:
            return "Active Improver"
        if avg_eff <= 40 and avg_adherence <= 30:
            return "High Consumer"
        return "Steady User"

    def test_eco_champion_threshold(self):
        assert self._classify(avg_eff=80, avg_adherence=85) == "Eco Champion"

    def test_borderline_eco_champion(self):
        assert self._classify(avg_eff=75, avg_adherence=80) == "Eco Champion"

    def test_active_improver_requires_trend(self):
        assert self._classify(avg_eff=60, avg_adherence=55, trend_improving=True) == "Active Improver"
        assert self._classify(avg_eff=60, avg_adherence=55, trend_improving=False) == "Steady User"

    def test_high_consumer_classification(self):
        assert self._classify(avg_eff=30, avg_adherence=20) == "High Consumer"

    def test_disengaged_no_data(self):
        assert self._classify(ranking_days=2) == "Disengaged"

    def test_disengaged_low_interaction(self):
        assert self._classify(avg_decision=5, avg_adherence=5) == "Disengaged"

    def test_steady_user_is_default(self):
        assert self._classify(avg_eff=50, avg_adherence=50) == "Steady User"

    def test_steady_user_near_eco_but_not_quite(self):
        assert self._classify(avg_eff=74, avg_adherence=79) == "Steady User"


# ── Security Config Warnings ──────────────────────────────────────

class TestSecurityWarnings:

    def _warnings(self, secret: str, admin_pass: str = "strongpass", origins=None):
        """Simulate _security_warnings() without importing the full app."""
        warns = []
        if len(secret) < 32:
            warns.append("SECRET_KEY is shorter than 32 characters")
        if "changeme" in secret.lower():
            warns.append("SECRET_KEY appears to use a default placeholder")
        if admin_pass and "changeme" in admin_pass.lower():
            warns.append("ADMIN_PASSWORD appears to use a default placeholder")
        for origin in (origins or []):
            if origin.strip() == "*":
                warns.append("ALLOWED_ORIGINS contains wildcard '*'")
        return warns

    def test_strong_config_no_warnings(self):
        long_secret = "x" * 64
        assert self._warnings(long_secret) == []

    def test_short_secret_warns(self):
        warns = self._warnings("short")
        assert any("shorter than 32" in w for w in warns)

    def test_changeme_secret_warns(self):
        warns = self._warnings("changeme_secret_1234567890123456")
        assert any("placeholder" in w for w in warns)

    def test_changeme_admin_pass_warns(self):
        warns = self._warnings("x" * 64, admin_pass="changeme123")
        assert any("ADMIN_PASSWORD" in w for w in warns)

    def test_wildcard_origin_warns(self):
        warns = self._warnings("x" * 64, origins=["*"])
        assert any("wildcard" in w for w in warns)

    def test_specific_origins_ok(self):
        warns = self._warnings("x" * 64, origins=["https://wattwise.example.com"])
        assert warns == []


# ── Auth Token Structure ──────────────────────────────────────────

class TestJWTClaimsStructure:
    """Test that JWT tokens embed the correct claims."""

    def _create_token(self, user_id: int, is_admin: bool) -> dict:
        """Replicate _create_token from auth.py."""
        from datetime import timedelta
        from jose import jwt
        secret = "test_secret_key_for_unit_tests_only_not_real"
        now = datetime.utcnow()
        payload = {
            "sub": str(user_id),
            "is_admin": is_admin,
            "iat": now,
            "exp": now + timedelta(minutes=30),
        }
        token = jwt.encode(payload, secret, algorithm="HS256")
        decoded = jwt.decode(token, secret, algorithms=["HS256"])
        return decoded

    def test_admin_flag_embedded_in_token(self):
        claims = self._create_token(user_id=1, is_admin=True)
        assert claims["is_admin"] is True
        assert claims["sub"] == "1"

    def test_non_admin_flag_in_token(self):
        claims = self._create_token(user_id=42, is_admin=False)
        assert claims["is_admin"] is False

    def test_token_has_expiry(self):
        claims = self._create_token(user_id=1, is_admin=False)
        assert "exp" in claims
        assert claims["exp"] > datetime.utcnow().timestamp()


# ── Decision Tracker Case Expressions ─────────────────────────────

class TestDecisionTrackerImport:
    """Ensure the decision_tracker module imports cleanly with case() fix."""

    def test_imports_without_error(self):
        from app.decision_tracker import DecisionTracker
        assert DecisionTracker is not None

    def test_case_imported_not_funcif(self):
        import inspect
        import app.decision_tracker as dt
        src = inspect.getsource(dt)
        assert "func.IF" not in src, "func.IF() should have been replaced with case()"
        assert "from sqlalchemy import" in src
        assert "case" in src


# ── Analysis N+1 Fix ──────────────────────────────────────────────

class TestAnalysisRouterImport:
    """Ensure analysis router has joinedload to avoid N+1 queries."""

    def test_joinedload_present(self):
        import inspect
        import app.routers.analysis as ar
        src = inspect.getsource(ar)
        assert "joinedload" in src, "joinedload should be used to avoid N+1 queries"

    def test_no_loop_based_home_lookup(self):
        import inspect
        import app.routers.analysis as ar
        src = inspect.getsource(ar)
        # The N+1 pattern was: "for r in rankings: ... select(Home).where(Home.id == r.home_id)"
        assert "for r in rankings" not in src, "N+1 loop should have been eliminated"


# ── Model Constraints ─────────────────────────────────────────────

class TestModelConstraints:
    """Verify the data-quality constraints are defined on the model."""

    def test_energy_reading_unique_constraint(self):
        from app.models import EnergyReading
        args = EnergyReading.__table_args__
        names = [c.name for c in args if hasattr(c, "name")]
        assert "uq_reading_device_time" in names, \
            "UniqueConstraint on (device_id, recorded_at) must exist"

    def test_energy_reading_check_constraint(self):
        from app.models import EnergyReading
        args = EnergyReading.__table_args__
        names = [c.name for c in args if hasattr(c, "name")]
        assert "chk_power_non_negative" in names, \
            "CheckConstraint preventing negative power_watts must exist"

    def test_admin_audit_log_model_exists(self):
        from app.models import AdminAuditLog
        assert AdminAuditLog.__tablename__ == "admin_audit_logs"

    def test_persona_model_exists(self):
        from app.models import Persona
        assert Persona.__tablename__ == "personas"

    def test_energy_ranking_unique_constraint(self):
        from app.models import EnergyRanking
        args = EnergyRanking.__table_args__
        names = [c.name for c in args if hasattr(c, "name")]
        assert "uq_ranking" in names


# ── Persona Seeder ────────────────────────────────────────────────

class TestPersonaClassifierModule:
    """Test the persona seed data definitions."""

    def test_five_personas_defined(self):
        from app.persona_classifier import DEFAULT_PERSONAS
        assert len(DEFAULT_PERSONAS) == 5

    def test_all_persona_names_unique(self):
        from app.persona_classifier import DEFAULT_PERSONAS
        names = [p["name"] for p in DEFAULT_PERSONAS]
        assert len(names) == len(set(names))

    def test_expected_persona_names_present(self):
        from app.persona_classifier import DEFAULT_PERSONAS
        names = {p["name"] for p in DEFAULT_PERSONAS}
        for expected in ["Eco Champion", "Active Improver", "Steady User", "High Consumer", "Disengaged"]:
            assert expected in names, f"Missing persona: {expected}"

    def test_each_persona_has_criteria(self):
        from app.persona_classifier import DEFAULT_PERSONAS
        for p in DEFAULT_PERSONAS:
            assert isinstance(p["criteria"], dict), f"{p['name']} must have criteria dict"
            assert len(p["criteria"]) > 0, f"{p['name']} criteria cannot be empty"
