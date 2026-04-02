#!/usr/bin/env python3
"""
WattWise RPi MQTT Publisher
============================
Runs on each Raspberry Pi (Home Assistant host).
Reads energy telemetry from local InfluxDB and publishes to
the WattWise cloud MQTT broker every 30 seconds.

Replaces Tailscale tunnelling for community-scale deployments.

Author : Mr. Suhas Devmane, Cardiff University, UK
Version: 1.0.0
"""

import json
import logging
import signal
import sys
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import yaml
from influxdb import InfluxDBClient

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("/var/log/wattwise-publisher.log", mode="a"),
    ],
)
logger = logging.getLogger("wattwise.publisher")


# ── Config Loader ──────────────────────────────────────────────────────────────
def load_config(path: str = "/etc/wattwise/publisher.yaml") -> dict:
    """Load YAML config file."""
    try:
        with open(path, "r") as f:
            cfg = yaml.safe_load(f)
        logger.info(f"✅ Config loaded from {path}")
        return cfg
    except FileNotFoundError:
        logger.error(f"Config file not found: {path}")
        logger.info("Copy rpi_publisher_config.yaml to /etc/wattwise/publisher.yaml")
        sys.exit(1)


# ── InfluxDB Reader ────────────────────────────────────────────────────────────
class InfluxReader:
    """Reads latest sensor readings from local InfluxDB v1.x (Home Assistant)."""

    def __init__(self, cfg: dict):
        self.client = InfluxDBClient(
            host=cfg.get("host", "localhost"),
            port=cfg.get("port", 8086),
            username=cfg.get("username", ""),
            password=cfg.get("password", ""),
            database=cfg.get("database", "homeassistant"),
            ssl=cfg.get("ssl", False),
            timeout=10,
        )
        logger.info(
            f"📊 InfluxDB reader initialised: "
            f"{cfg.get('host')}:{cfg.get('port')}/{cfg.get('database')}"
        )

    def get_latest(self, entity_id: str, measurement: str = "state") -> dict | None:
        """Get most recent value for an entity_id."""
        query = (
            f"SELECT value, state FROM \"{measurement}\" "
            f"WHERE entity_id = '{entity_id}' "
            f"ORDER BY time DESC LIMIT 1"
        )
        try:
            result = list(self.client.query(query).get_points())
            if result:
                return result[0]
        except Exception as e:
            logger.warning(f"InfluxDB query error for {entity_id}: {e}")
        return None

    def get_energy_kwh(self, entity_id: str) -> dict | None:
        """Fetch latest energy kWh reading (uses 'kWh' measurement in HA)."""
        for measurement in ["kWh", "W", "state"]:
            try:
                query = (
                    f"SELECT value FROM \"{measurement}\" "
                    f"WHERE entity_id = '{entity_id}' "
                    f"ORDER BY time DESC LIMIT 1"
                )
                result = list(self.client.query(query).get_points())
                if result:
                    return {"value": float(result[0].get("value", 0)), "measurement": measurement}
            except Exception:
                continue
        return None

    def ping(self) -> bool:
        try:
            self.client.ping()
            return True
        except Exception:
            return False


# ── MQTT Publisher ─────────────────────────────────────────────────────────────
class MQTTPublisher:
    """Authenticated MQTT client for the WattWise cloud broker."""

    def __init__(self, cfg: dict, home_id: str):
        self.home_id = home_id
        self.cfg = cfg
        self.connected = False

        transport = cfg.get("transport", "tcp")   # "tcp" or "websockets"
        self.client = mqtt.Client(
            client_id=f"wattwise-rpi-{home_id}",
            protocol=mqtt.MQTTv5,
            transport=transport,
        )

        # WebSocket path (only used when transport="websockets")
        if transport == "websockets":
            self.client.ws_set_options(path=cfg.get("ws_path", "/mqtt"))

        # Authentication
        if cfg.get("username") and cfg.get("password"):
            self.client.username_pw_set(cfg["username"], cfg["password"])

        # TLS/SSL — required for WSS (Cloudflare) or explicit tls:true
        if cfg.get("tls", False) or transport == "websockets":
            self.client.tls_set()  # uses system CA bundle (trusts Cloudflare cert)

        # Callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_publish = self._on_publish

    def _on_connect(self, client, userdata, flags, rc, props=None):
        if rc == 0:
            self.connected = True
            logger.info(f"✅ MQTT connected to {self.cfg['host']}:{self.cfg.get('port', 1883)}")
        else:
            logger.error(f"❌ MQTT connect failed (rc={rc}): {mqtt.connack_string(rc)}")

    def _on_disconnect(self, client, userdata, rc, props=None):
        self.connected = False
        if rc != 0:
            logger.warning(f"MQTT unexpected disconnect (rc={rc}), will reconnect...")

    def _on_publish(self, client, userdata, mid):
        logger.debug(f"📤 MQTT message published (mid={mid})")

    def connect(self):
        try:
            self.client.connect(
                self.cfg["host"],
                self.cfg.get("port", 1883),
                keepalive=60,
            )
            self.client.loop_start()
            time.sleep(2)  # Allow connection to establish
        except Exception as e:
            logger.error(f"MQTT connection error: {e}")
            raise

    def publish_device(self, device_id: str, payload: dict) -> bool:
        """Publish device telemetry to wattwise/homes/{home_id}/devices/{device_id}/data"""
        topic = f"wattwise/homes/{self.home_id}/devices/{device_id}/data"
        payload_str = json.dumps(payload)

        result = self.client.publish(topic, payload_str, qos=1, retain=False)
        if result.rc == mqtt.MQTT_ERR_SUCCESS:
            logger.debug(f"📤 Published {device_id}: {payload_str[:80]}")
            return True
        else:
            logger.error(f"Publish failed for {device_id}: rc={result.rc}")
            return False

    def publish_home_status(self, status: dict):
        """Publish RPi heartbeat to wattwise/homes/{home_id}/status"""
        topic = f"wattwise/homes/{self.home_id}/status"
        self.client.publish(topic, json.dumps(status), qos=0, retain=True)

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()


# ── Main Publisher Loop ────────────────────────────────────────────────────────
class WattWisePublisher:
    """Main orchestrator: reads InfluxDB → publishes to MQTT cloud."""

    def __init__(self, config_path: str = "/etc/wattwise/publisher.yaml"):
        self.cfg = load_config(config_path)
        self.home_id = self.cfg["home"]["id"]
        self.devices = self.cfg["home"]["devices"]
        self.interval = self.cfg.get("publish_interval_seconds", 30)
        self.running = True

        self.influx = InfluxReader(self.cfg["influxdb"])
        self.mqtt = MQTTPublisher(self.cfg["mqtt"], self.home_id)

        # Graceful shutdown
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        self.running = False

    def _build_payload(self, device: dict) -> dict | None:
        """Read all entity IDs for a device and build telemetry payload."""
        entity_id = device["entity_id"]
        power_entity = device.get("power_entity_id", entity_id)
        switch_entity = device.get("switch_entity_id")

        # Power reading (Watts)
        power_data = self.influx.get_energy_kwh(power_entity)
        power_w = power_data["value"] if power_data else None

        # Current reading (Amps) — optional
        current_entity = device.get("current_entity_id")
        current_a = None
        if current_entity:
            c = self.influx.get_latest(current_entity)
            if c:
                try:
                    current_a = float(c.get("value", 0))
                except (TypeError, ValueError):
                    pass

        # Switch state — optional
        switch_state = None
        if switch_entity:
            sw = self.influx.get_latest(switch_entity)
            if sw:
                switch_state = sw.get("state", "unknown")

        if power_w is None:
            logger.debug(f"No power data for {entity_id}, skipping")
            return None

        # Estimate: energy_kwh = power_W / 1000 * interval_h
        interval_hours = self.interval / 3600
        energy_kwh = (power_w / 1000.0) * interval_hours

        # Estimate voltage (UK standard 230V)
        voltage_v = 230.0
        current_a = current_a or (power_w / voltage_v if power_w > 0 else 0.0)

        return {
            "home_id": self.home_id,
            "device_id": device["id"],
            "entity_id": entity_id,
            "device_name": device.get("name", entity_id),
            "appliance_key": device.get("appliance_key", device["id"]),
            "power_watts": round(power_w, 2),
            "current_amps": round(current_a, 3),
            "voltage_volts": voltage_v,
            "energy_kwh": round(energy_kwh, 6),
            "switch_state": switch_state,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def run(self):
        """Main publishing loop."""
        logger.info(f"🚀 WattWise Publisher starting for home_id={self.home_id}")
        logger.info(f"   Devices: {[d['id'] for d in self.devices]}")
        logger.info(f"   Publish interval: {self.interval}s")

        # Connect MQTT
        self.mqtt.connect()

        if not self.flux_check():
            logger.error("InfluxDB not reachable — check local InfluxDB service")

        loop_count = 0
        while self.running:
            loop_count += 1
            published = 0
            errors = 0

            for device in self.devices:
                try:
                    payload = self._build_payload(device)
                    if payload:
                        success = self.mqtt.publish_device(device["id"], payload)
                        if success:
                            published += 1
                        else:
                            errors += 1
                except Exception as e:
                    logger.error(f"Error processing device {device.get('id')}: {e}")
                    errors += 1

            # Heartbeat every 10 loops
            if loop_count % 10 == 0:
                self.mqtt.publish_home_status({
                    "home_id": self.home_id,
                    "status": "online",
                    "devices_active": published,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "publisher_version": "1.0.0",
                })
                logger.info(
                    f"💚 Heartbeat #{loop_count}: {published} published, {errors} errors"
                )
            else:
                logger.info(f"🔄 Loop #{loop_count}: {published} published, {errors} errors")

            # Wait for next interval
            for _ in range(self.interval):
                if not self.running:
                    break
                time.sleep(1)

        # Cleanup
        self.mqtt.publish_home_status({
            "home_id": self.home_id,
            "status": "offline",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.mqtt.disconnect()
        logger.info("WattWise Publisher stopped cleanly.")

    def flux_check(self) -> bool:
        ok = self.influx.ping()
        logger.info(f"InfluxDB ping: {'✅ OK' if ok else '❌ FAIL'}")
        return ok


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="WattWise RPi MQTT Publisher")
    parser.add_argument(
        "--config",
        default="/etc/wattwise/publisher.yaml",
        help="Path to publisher.yaml config",
    )
    args = parser.parse_args()

    publisher = WattWisePublisher(config_path=args.config)
    publisher.run()
