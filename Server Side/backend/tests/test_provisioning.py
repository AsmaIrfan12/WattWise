"""Pure-function tests for home provisioning: broker usernames, control commands, publisher YAML."""
import pytest
import yaml

from app.broker_admin import (
    BrokerAdminError, is_legacy_username, next_home_username, provision_commands, generate_mqtt_password,
)
from app.publisher_config import build_publisher_yaml, slug, suggested_power_entity


class TestHomeUsernames:
    def test_first_provisioned_home_follows_the_legacy_block(self):
        assert next_home_username([]) == "home_016"
        assert next_home_username(["home_001"]) == "home_016"

    def test_continues_after_the_highest(self):
        assert next_home_username(["home_001", "home_016", "home_042"]) == "home_043"

    def test_ignores_malformed_names(self):
        assert next_home_username(["asma", "home_x", None, "home_017"]) == "home_018"

    def test_legacy_accounts_are_recognised(self):
        assert is_legacy_username("home_001") and is_legacy_username("home_015")
        assert not is_legacy_username("home_016")
        assert not is_legacy_username(None) and not is_legacy_username("wattwise_backend")


class TestProvisionCommands:
    def test_role_only_allows_the_homes_own_topic(self):
        role, client = provision_commands("home_016", "pw")
        assert role["command"] == "createRole" and role["rolename"] == "home_016"
        assert role["acls"] == [
            {"acltype": "publishClientSend", "topic": "wattwise/homes/home_016/#", "priority": 5, "allow": True}
        ]
        assert client["command"] == "createClient" and client["roles"] == [{"rolename": "home_016", "priority": 5}]

    @pytest.mark.parametrize("bad", ["home_1/#", "../home_016", "home_016 ", "admin", "home_", "+"])
    def test_rejects_anything_that_is_not_a_home_username(self, bad):
        with pytest.raises(BrokerAdminError):
            provision_commands(bad, "pw")

    def test_generated_passwords_are_long_and_yaml_safe(self):
        pw = generate_mqtt_password()
        assert len(pw) >= 30 and not set(pw) & set("\"'\ :#")
        assert pw != generate_mqtt_password()


class TestPublisherYaml:
    DEVICES = [
        {"name": "Kettle", "appliance_key": "kettle", "entity_id": "sensor.kettle_ab12cd", "power_entity_id": None},
        {"name": "Second \"big\" kettle", "appliance_key": "kettle", "entity_id": "sensor.kettle_ff00aa",
         "power_entity_id": "kettle_2_power"},
    ]

    def _load(self, **kw):
        text = build_publisher_yaml(mqtt_username="home_016", mqtt_password="s3cret-pw", home_name="Sam's Home",
                                    devices=self.DEVICES, mqtt_host="67.207.68.22", **kw)
        return yaml.safe_load(text), text

    def test_is_valid_yaml_with_the_fields_the_publisher_reads(self):
        cfg, _ = self._load()
        assert cfg["home"]["id"] == "home_016" and cfg["home"]["name"] == "Sam's Home"
        assert cfg["mqtt"] == {"host": "67.207.68.22", "port": 1883, "transport": "tcp", "ws_path": "",
                               "username": "home_016", "password": "s3cret-pw", "tls": False}
        assert cfg["influxdb"]["database"] == "homeassistant"
        assert cfg["publish_interval_seconds"] == 30

    def test_devices_keep_server_entity_ids_and_get_unique_topic_ids(self):
        cfg, _ = self._load()
        devs = cfg["home"]["devices"]
        assert [d["entity_id"] for d in devs] == ["sensor.kettle_ab12cd", "sensor.kettle_ff00aa"]
        assert [d["id"] for d in devs] == ["kettle", "kettle_2"]
        assert devs[0]["power_entity_id"] == "kettle_current_consumption"   # suggested
        assert devs[1]["power_entity_id"] == "kettle_2_power"               # as registered
        assert devs[1]["name"] == 'Second "big" kettle'                     # quoting survives

    def test_password_is_a_placeholder_when_not_supplied(self):
        text = build_publisher_yaml(mqtt_username="home_016", mqtt_password=None, home_name="H", devices=[],
                                    mqtt_host="h")
        cfg = yaml.safe_load(text)
        assert cfg["mqtt"]["password"].startswith("PASTE_") and cfg["home"]["devices"] == []

    def test_helpers(self):
        assert slug("Washing Machine!") == "washing_machine" and slug("") == "device"
        assert suggested_power_entity("washing_machine") == "washing_machine_current_consumption"


# ── The RPi publisher itself (Sensing Layer/) ────────────────────────────────
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

SENSING = Path(__file__).resolve().parents[3] / "Sensing Layer"
PUBLISHER_COPIES = [
    SENSING / "rpi_mqtt_publisher.py",
    SENSING / "deployments" / "asma-irfan" / "rpi_mqtt_publisher.py",
    SENSING / "hass-addon" / "wattwise-publisher" / "rpi_mqtt_publisher.py",
]
needs_sensing = pytest.mark.skipif(not PUBLISHER_COPIES[0].exists(), reason="Sensing Layer not present (image build)")


def _publisher():
    spec = importlib.util.spec_from_file_location("rpi_mqtt_publisher", PUBLISHER_COPIES[0])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@needs_sensing
class TestPublisher:
    def test_the_three_copies_are_identical(self):
        # The add-on and deployment bundle carry copies of the canonical file; they must not drift.
        contents = {p.read_bytes() for p in PUBLISHER_COPIES}
        assert len(contents) == 1

    def test_idle_plug_is_never_stale(self):
        pub = _publisher()
        assert pub.is_stale(0.0, 36000, 900, 5.0) is False     # 0 W for 10 h: an idle plug
        assert pub.is_stale(2.5, 36000, 900, 5.0) is False     # standby draw

    def test_unchanged_load_becomes_stale(self):
        pub = _publisher()
        assert pub.is_stale(2000.0, 899, 900, 5.0) is False
        assert pub.is_stale(2000.0, 901, 900, 5.0) is True     # "2 kW" frozen for 15 min: plug offline

    def test_stale_check_can_be_disabled_and_tolerates_unknown_age(self):
        pub = _publisher()
        assert pub.is_stale(2000.0, 99999, 0, 5.0) is False
        assert pub.is_stale(2000.0, None, 900, 5.0) is False

    def test_reading_age(self):
        pub = _publisher()
        now = datetime(2026, 11, 16, 12, 0, 0, tzinfo=timezone.utc)
        iso, age = pub.reading_age("2026-11-16T11:58:00Z", now)
        assert age == 120 and iso.startswith("2026-11-16T11:58:00")
        assert pub.reading_age(None, now) == (None, None)
        assert pub.reading_age("garbage", now) == (None, None)

    def test_default_addon_config_is_a_placeholder_not_a_real_home(self):
        cfg = yaml.safe_load((SENSING / "hass-addon" / "wattwise-publisher" / "publisher.default.yaml").read_text("utf-8"))
        assert cfg["home"]["id"].startswith("REPLACE_") and cfg["home"]["devices"] == []
        assert cfg["mqtt"]["username"].startswith("REPLACE_")
