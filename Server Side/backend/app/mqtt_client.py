"""
WattWise MQTT Client
====================
Subscribes to wattwise/homes/+/devices/+/data and persists
energy readings to MySQL (energy_readings) and InfluxDB.
"""

import json
import logging
from datetime import datetime

import paho.mqtt.client as mqtt
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Device, EnergyReading

logger = logging.getLogger("mqtt_client")

_mqtt_client: mqtt.Client | None = None
_mqtt_connected: bool = False


# ── MQTT Callbacks ────────────────────────────────────────────

def on_connect(client, userdata, flags, rc):
    global _mqtt_connected
    if rc == 0:
        _mqtt_connected = True
        logger.info("MQTT connected successfully")
        topic = f"{settings.MQTT_TOPIC_PREFIX}/+/devices/+/data"
        client.subscribe(topic, qos=1)
        logger.info(f"Subscribed to: {topic}")
    else:
        logger.error(f"MQTT connection failed with code {rc}")


def on_disconnect(client, userdata, rc):
    global _mqtt_connected
    _mqtt_connected = False
    if rc != 0:
        logger.warning(f"MQTT unexpected disconnect (rc={rc}) — auto-reconnect will trigger")


def on_message(client, userdata, msg):
    """Process incoming energy telemetry from smart plugs."""
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        logger.debug(f"MQTT message on {msg.topic}: {payload}")

        # Parse topic: wattwise/homes/<home_id>/devices/<device_entity>/data
        parts = msg.topic.split("/")
        topic_home_id = parts[2] if len(parts) >= 5 else None
        topic_device_entity = parts[4] if len(parts) >= 5 else None

        # Extract fields from payload
        entity_id = payload.get("entity_id") or topic_device_entity
        recorded_at_raw = payload.get("timestamp")
        recorded_at = (
            datetime.fromisoformat(recorded_at_raw)
            if recorded_at_raw
            else datetime.utcnow()
        )
        power_watts = float(payload.get("power_watts", payload.get("value", 0)))
        current_amps = payload.get("current_amps")
        voltage_volts = payload.get("voltage_volts")
        energy_kwh = payload.get("energy_kwh")
        switch_state = payload.get("switch_state", "unknown")

        # Write to InfluxDB for time-series storage
        _write_to_influx(entity_id, power_watts, current_amps, voltage_volts, energy_kwh, recorded_at)

        # Schedule MySQL write (since MQTT callback is sync, use thread-safe approach)
        import asyncio
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    _write_reading_to_db(entity_id, power_watts, current_amps, voltage_volts, energy_kwh, switch_state, recorded_at)
                )
        except RuntimeError:
            pass

    except Exception as e:
        logger.error(f"Error processing MQTT message: {e}", exc_info=True)


def _write_to_influx(entity_id: str, power_watts: float, current_amps, voltage_volts, energy_kwh, recorded_at: datetime):
    """Write energy reading to InfluxDB for time-series queries."""
    try:
        from influxdb import InfluxDBClient
        from app.config import settings

        client = InfluxDBClient(
            host=settings.INFLUX_HOST,
            port=settings.INFLUX_PORT,
            username=settings.INFLUX_USER,
            password=settings.INFLUX_PASS,
            database=settings.INFLUX_DB
        )

        fields = {"value": power_watts}
        if current_amps is not None:
            fields["current"] = current_amps
        if voltage_volts is not None:
            fields["voltage"] = voltage_volts
        if energy_kwh is not None:
            fields["energy_kwh"] = energy_kwh

        client.write_points([{
            "measurement": "W",
            "tags": {"entity_id": entity_id},
            "fields": fields,
            "time": recorded_at.isoformat()
        }])
    except Exception as e:
        logger.warning(f"InfluxDB write failed for {entity_id}: {e}")


async def _write_reading_to_db(entity_id: str, power_watts: float, current_amps, voltage_volts, energy_kwh, switch_state: str, recorded_at: datetime):
    """Persist energy reading to MySQL."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Device).where(Device.entity_id == entity_id, Device.is_active == True)
            )
            device = result.scalar_one_or_none()

            if not device:
                logger.debug(f"Device not found for entity_id: {entity_id} — skipping MySQL write")
                return

            reading = EnergyReading(
                device_id=device.id,
                recorded_at=recorded_at,
                power_watts=power_watts,
                current_amps=current_amps,
                voltage_volts=voltage_volts,
                energy_kwh=energy_kwh,
                switch_state=switch_state
            )
            session.add(reading)
            await session.commit()
            logger.debug(f"Saved reading for device {device.name}: {power_watts}W")
    except Exception as e:
        logger.error(f"MySQL write error for {entity_id}: {e}", exc_info=True)


# ── Lifecycle ─────────────────────────────────────────────────

def start_mqtt():
    global _mqtt_client
    _mqtt_client = mqtt.Client(client_id="wattwise-backend", clean_session=True)
    _mqtt_client.on_connect = on_connect
    _mqtt_client.on_disconnect = on_disconnect
    _mqtt_client.on_message = on_message
    _mqtt_client.reconnect_delay_set(min_delay=1, max_delay=30)
    _mqtt_client.connect_async(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=60)
    _mqtt_client.loop_start()
    logger.info(f"MQTT client started → {settings.MQTT_BROKER_HOST}:{settings.MQTT_BROKER_PORT}")


def stop_mqtt():
    global _mqtt_client
    if _mqtt_client:
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()
        logger.info("MQTT client stopped")


def is_mqtt_connected() -> bool:
    return _mqtt_connected
