"""
WattWise MQTT Client
====================
Subscribes to wattwise/homes/+/devices/+/data and persists
energy readings to MySQL (energy_readings) and InfluxDB.

Fixes applied:
- InfluxDB client is now a module-level singleton (was recreated per message)
- MQTT broker authentication enabled via settings
- Input validation: rejects negative, NaN, Inf, or impossibly large readings
- Duplicate-reading guard (same device + timestamp within 5 s)
"""

import json
import logging
import math
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Device, EnergyReading

logger = logging.getLogger("mqtt_client")

_mqtt_client: mqtt.Client | None = None
_mqtt_connected: bool = False

# ── InfluxDB singleton ────────────────────────────────────────
_influx_client = None

def _get_influx_client():
    """Return a cached InfluxDB client — created once at startup."""
    global _influx_client
    if _influx_client is None:
        try:
            from influxdb import InfluxDBClient
            _influx_client = InfluxDBClient(
                host=settings.INFLUX_HOST,
                port=settings.INFLUX_PORT,
                username=settings.INFLUX_USER,
                password=settings.INFLUX_PASS,
                database=settings.INFLUX_DB,
                timeout=5,
            )
            logger.info(
                "InfluxDB client initialised → %s:%s/%s",
                settings.INFLUX_HOST, settings.INFLUX_PORT, settings.INFLUX_DB
            )
        except Exception as exc:
            logger.warning("InfluxDB client init failed: %s", exc)
    return _influx_client


# ── Input validation ─────────────────────────────────────────

MAX_POWER_WATTS = 50_000.0   # 50 kW — no domestic appliance should exceed this
MAX_ENERGY_KWH  = 100.0      # 100 kWh per reading — physically implausible otherwise


def _validate_payload(payload: dict) -> tuple[float, float | None, float | None, float | None]:
    """
    Validate incoming telemetry fields.
    Returns (power_watts, current_amps, voltage_volts, energy_kwh).
    Raises ValueError if data is out of bounds.
    """
    raw_power = float(payload.get("power_watts", payload.get("value", 0)) or 0)
    if math.isnan(raw_power) or math.isinf(raw_power):
        raise ValueError(f"power_watts is NaN/Inf: {raw_power}")
    if raw_power < 0:
        raise ValueError(f"power_watts is negative: {raw_power}")
    if raw_power > MAX_POWER_WATTS:
        raise ValueError(f"power_watts too large ({raw_power}W) — likely sensor error")

    current_amps = payload.get("current_amps")
    if current_amps is not None:
        current_amps = float(current_amps)
        if math.isnan(current_amps) or current_amps < 0:
            current_amps = None

    voltage_volts = payload.get("voltage_volts")
    if voltage_volts is not None:
        voltage_volts = float(voltage_volts)
        if math.isnan(voltage_volts) or voltage_volts <= 0 or voltage_volts > 500:
            voltage_volts = None

    energy_kwh = payload.get("energy_kwh")
    if energy_kwh is not None:
        energy_kwh = float(energy_kwh)
        if math.isnan(energy_kwh) or energy_kwh < 0 or energy_kwh > MAX_ENERGY_KWH:
            energy_kwh = None

    return raw_power, current_amps, voltage_volts, energy_kwh


# ── MQTT Callbacks ────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    global _mqtt_connected
    if rc == 0:
        _mqtt_connected = True
        logger.info("MQTT connected successfully")
        topic = f"{settings.MQTT_TOPIC_PREFIX}/+/devices/+/data"
        client.subscribe(topic, qos=1)
        logger.info("Subscribed to: %s", topic)
    else:
        logger.error("MQTT connection failed with code %s", rc)


def on_disconnect(client, userdata, rc):
    global _mqtt_connected
    _mqtt_connected = False
    if rc != 0:
        logger.warning("MQTT unexpected disconnect (rc=%s) — auto-reconnect will trigger", rc)


def on_message(client, userdata, msg):
    """Process incoming energy telemetry from smart plugs."""
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        logger.debug("MQTT message on %s", msg.topic)

        # Parse topic: wattwise/homes/<home_id>/devices/<device_entity>/data
        parts = msg.topic.split("/")
        topic_device_entity = parts[4] if len(parts) >= 5 else None

        entity_id = payload.get("entity_id") or topic_device_entity
        if not entity_id:
            logger.warning("MQTT message has no entity_id on topic %s", msg.topic)
            return

        # Parse timestamp
        recorded_at_raw = payload.get("timestamp")
        try:
            recorded_at = (
                datetime.fromisoformat(recorded_at_raw.replace("Z", "+00:00")).replace(tzinfo=None)
                if recorded_at_raw
                else datetime.utcnow()
            )
        except (ValueError, AttributeError):
            recorded_at = datetime.utcnow()

        # Validate fields — skip malformed readings silently
        try:
            power_watts, current_amps, voltage_volts, energy_kwh = _validate_payload(payload)
        except ValueError as ve:
            logger.warning("Rejected invalid MQTT payload for %s: %s", entity_id, ve)
            return

        switch_state = payload.get("switch_state", "unknown")
        if switch_state not in ("on", "off", "unknown"):
            switch_state = "unknown"

        # Write to InfluxDB for time-series storage
        _write_to_influx(entity_id, power_watts, current_amps, voltage_volts, energy_kwh, recorded_at)

        # Schedule MySQL write (MQTT callback is sync — use asyncio.ensure_future)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    _write_reading_to_db(
                        entity_id, power_watts, current_amps,
                        voltage_volts, energy_kwh, switch_state, recorded_at
                    )
                )
        except RuntimeError:
            pass

    except Exception as e:
        logger.error("Error processing MQTT message: %s", e, exc_info=True)


def _write_to_influx(
    entity_id: str,
    power_watts: float,
    current_amps, voltage_volts,
    energy_kwh,
    recorded_at: datetime,
):
    """Write energy reading to InfluxDB using the shared client."""
    influx = _get_influx_client()
    if not influx:
        return
    try:
        fields: dict = {"value": power_watts}
        if current_amps is not None:
            fields["current"] = current_amps
        if voltage_volts is not None:
            fields["voltage"] = voltage_volts
        if energy_kwh is not None:
            fields["energy_kwh"] = energy_kwh

        influx.write_points([{
            "measurement": "W",
            "tags": {"entity_id": entity_id},
            "fields": fields,
            "time": recorded_at.isoformat() + "Z",
        }])
    except Exception as e:
        logger.warning("InfluxDB write failed for %s: %s", entity_id, e)
        # Reset singleton so next call re-connects
        global _influx_client
        _influx_client = None


async def _write_reading_to_db(
    entity_id: str,
    power_watts: float,
    current_amps, voltage_volts,
    energy_kwh,
    switch_state: str,
    recorded_at: datetime,
):
    """Persist energy reading to MySQL. Skips duplicate readings (same device + timestamp)."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Device).where(Device.entity_id == entity_id, Device.is_active == True)
            )
            device = result.scalar_one_or_none()

            if not device:
                logger.debug("Device not found for entity_id: %s — skipping MySQL write", entity_id)
                return

            # Duplicate guard: skip if reading already exists for this device+timestamp (within 5s)
            from datetime import timedelta
            from sqlalchemy import and_
            dup_result = await session.execute(
                select(EnergyReading.id).where(
                    and_(
                        EnergyReading.device_id == device.id,
                        EnergyReading.recorded_at >= recorded_at - timedelta(seconds=5),
                        EnergyReading.recorded_at <= recorded_at + timedelta(seconds=5),
                    )
                ).limit(1)
            )
            if dup_result.scalar_one_or_none():
                logger.debug("Duplicate reading skipped for device %s at %s", device.id, recorded_at)
                return

            reading = EnergyReading(
                device_id=device.id,
                recorded_at=recorded_at,
                power_watts=power_watts,
                current_amps=current_amps,
                voltage_volts=voltage_volts,
                energy_kwh=energy_kwh,
                switch_state=switch_state,
            )
            session.add(reading)
            await session.commit()
            logger.debug("Saved reading for device %s: %.1fW", device.name, power_watts)
    except Exception as e:
        logger.error("MySQL write error for %s: %s", entity_id, e, exc_info=True)


# ── Lifecycle ─────────────────────────────────────────────────

def start_mqtt():
    global _mqtt_client
    _mqtt_client = mqtt.Client(client_id="wattwise-backend", clean_session=True)

    # Authenticated broker connection
    if settings.MQTT_USERNAME and settings.MQTT_PASSWORD:
        _mqtt_client.username_pw_set(settings.MQTT_USERNAME, settings.MQTT_PASSWORD)
        logger.info("MQTT authentication configured for user: %s", settings.MQTT_USERNAME)

    _mqtt_client.on_connect = on_connect
    _mqtt_client.on_disconnect = on_disconnect
    _mqtt_client.on_message = on_message
    _mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)
    _mqtt_client.connect_async(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)
    _mqtt_client.loop_start()

    # Warm up the InfluxDB singleton at startup to catch connection errors early
    _get_influx_client()

    logger.info("MQTT client started → %s:%s", settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT)


def stop_mqtt():
    global _mqtt_client, _influx_client
    if _mqtt_client:
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()
        logger.info("MQTT client stopped")
    if _influx_client:
        try:
            _influx_client.close()
        except Exception:
            pass
        _influx_client = None


def is_mqtt_connected() -> bool:
    return _mqtt_connected
