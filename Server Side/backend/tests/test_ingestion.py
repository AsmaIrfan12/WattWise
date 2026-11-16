"""Pure-function tests for MQTT ingestion: topic parsing, reading timestamps, home liveness."""
from datetime import datetime, timedelta

from app.mqtt_client import parse_topic, parse_reading_time
from app.routers.admin_homes import home_state

PREFIX = "wattwise/homes"
NOW = datetime(2026, 11, 16, 12, 0, 0)


class TestParseTopic:
    def test_data_topic(self):
        assert parse_topic("wattwise/homes/home_001/devices/kettle/data", PREFIX) == ("data", "home_001", "kettle")

    def test_status_topic(self):
        assert parse_topic("wattwise/homes/home_001/status", PREFIX) == ("status", "home_001", None)

    def test_other_topics_are_ignored(self):
        for topic in (
            "wattwise/homes/home_001/commands/kettle",
            "wattwise/homes/home_001/devices/kettle",
            "wattwise/homes//devices/kettle/data",
            "other/homes/home_001/devices/kettle/data",
            "wattwise/homes/home_001/devices/kettle/data/extra",
            "$SYS/broker/uptime",
        ):
            assert parse_topic(topic, PREFIX) == (None, None, None), topic

    def test_prefix_with_slashes(self):
        assert parse_topic("wattwise/homes/h1/status", "/wattwise/homes/")[0] == "status"


class TestParseReadingTime:
    def test_missing_uses_server_time(self):
        assert parse_reading_time(None, NOW) == NOW
        assert parse_reading_time("", NOW) == NOW

    def test_garbage_uses_server_time(self):
        assert parse_reading_time("not-a-date", NOW) == NOW

    def test_utc_z_suffix(self):
        assert parse_reading_time("2026-11-16T11:59:30Z", NOW) == datetime(2026, 11, 16, 11, 59, 30)

    def test_offset_is_converted_not_dropped(self):
        # 12:59:30+01:00 is 11:59:30 UTC. Dropping the offset stored it an hour late.
        assert parse_reading_time("2026-11-16T12:59:30+01:00", NOW) == datetime(2026, 11, 16, 11, 59, 30)

    def test_naive_is_taken_as_utc(self):
        assert parse_reading_time("2026-11-16T11:00:00", NOW) == datetime(2026, 11, 16, 11, 0, 0)

    def test_small_clock_skew_is_kept(self):
        assert parse_reading_time("2026-11-16T12:03:00Z", NOW) == datetime(2026, 11, 16, 12, 3, 0)

    def test_far_future_clock_falls_back_to_server_time(self):
        assert parse_reading_time("2031-01-01T00:00:00Z", NOW) == NOW

    def test_very_old_reading_is_rejected(self):
        assert parse_reading_time("2026-09-01T00:00:00Z", NOW) is None


class TestHomeState:
    def test_never_seen(self):
        assert home_state(None, "home_009", NOW, 15) == "never_seen"

    def test_online_within_threshold(self):
        assert home_state(NOW - timedelta(minutes=14), "home_001", NOW, 15) == "online"

    def test_offline_after_threshold(self):
        assert home_state(NOW - timedelta(minutes=16), "home_001", NOW, 15) == "offline"


class TestProcessRoles:
    from app.mqtt_client import subscriptions_for as _subs

    def test_worker_is_the_only_role_that_consumes_telemetry_directly(self):
        from app.mqtt_client import subscriptions_for
        topics = dict(subscriptions_for("worker", PREFIX))
        assert topics["wattwise/homes/+/devices/+/data"] == 1      # QoS 1, plain subscription
        assert "wattwise/homes/+/status" in topics

    def test_api_role_never_subscribes_to_telemetry(self):
        from app.mqtt_client import subscriptions_for, INGEST_STATS_TOPIC
        topics = [t for t, _ in subscriptions_for("api", PREFIX)]
        assert not any("devices" in t for t in topics)
        assert INGEST_STATS_TOPIC in topics and "$SYS/broker/#" in topics

    def test_all_role_uses_a_shared_subscription(self):
        from app.mqtt_client import subscriptions_for
        topics = [t for t, _ in subscriptions_for("all", PREFIX)]
        assert any(t.startswith("$share/") and t.endswith("/devices/+/data") for t in topics)
