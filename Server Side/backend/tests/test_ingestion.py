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
