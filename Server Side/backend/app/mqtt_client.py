"""
WattWise MQTT Client
====================
Subscribes to wattwise/homes/+/devices/+/data and persists
energy readings to MySQL (energy_readings) and InfluxDB.

A reading is stored only when the home named in its topic is registered
(homes.mqtt_username) and the device belongs to that home — see _write_reading_to_db.

Fixes applied:
- InfluxDB client is now a module-level singleton (was recreated per message)
- MQTT broker authentication enabled via settings
- Input validation: rejects negative, NaN, Inf, or impossibly large readings
- Duplicate-reading guard (same device + timestamp within 5 s)
"""

import asyncio
import json
import logging
import math
import re
import time
from datetime import datetime, timedelta, timezone

import paho.mqtt.client as mqtt
from sqlalchemy import and_, select, update

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Device, EnergyReading, Home

logger = logging.getLogger("mqtt_client")

_mqtt_client: mqtt.Client | None = None
_mqtt_connected: bool = False

# The asyncio loop running the FastAPI app. paho's on_message fires on the MQTT
# network thread, NOT this loop's thread — so MySQL writes must be handed back
# via run_coroutine_threadsafe. Captured in start_mqtt() (called inside the
# async lifespan, i.e. on the loop thread).
_loop: asyncio.AbstractEventLoop | None = None

# ── $SYS broker stats cache ───────────────────────────────────
# Mosquitto publishes broker telemetry on $SYS/broker/* topics. We subscribe
# at startup and cache the latest value per topic so the admin panel can
# query a snapshot without opening a fresh MQTT connection per request.
_broker_stats: dict[str, dict] = {}

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


def _sanitize_entity_id(entity_id: str) -> str:
    """Allow only safe entity-id characters and normalize to lowercase."""
    return re.sub(r"[^a-zA-Z0-9_\.\-]", "", str(entity_id or "")).lower()


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

# ── Ingestion bookkeeping ─────────────────────────────────────
# Why each message was accepted or dropped. Surfaced in the admin panel (per worker)
# and logged — a dropped reading must never be silent again.
_ingest_stats: dict[str, int] = {}
_last_reject_logged: dict[str, float] = {}
_home_cache: dict[str, tuple[int | None, float]] = {}
_HOME_CACHE_TTL = 60.0
_last_seen_written: dict[int, float] = {}
_home_seen_written: dict[int, float] = {}


def _count(outcome: str, detail: str = "") -> None:
    _ingest_stats[outcome] = _ingest_stats.get(outcome, 0) + 1
    if outcome in ("accepted", "duplicate"):
        return
    # At most one log line per distinct problem every 5 minutes.
    key = f"{outcome}:{detail}"
    now = time.monotonic()
    if now - _last_reject_logged.get(key, -1e9) >= 300:
        _last_reject_logged[key] = now
        logger.warning("MQTT reading not stored (%s): %s", outcome, detail)
        if len(_last_reject_logged) > 500:
            _last_reject_logged.clear()


def get_ingest_stats() -> dict:
    """This process's counters, or — in an API process — the worker's last report."""
    if _role == "api":
        return dict(_remote_ingest_stats)
    return dict(_ingest_stats)


def publish_ingest_stats() -> None:
    """Worker only: publish the counters (retained) for the API processes to show."""
    if _mqtt_client is not None and _mqtt_connected:
        _mqtt_client.publish(
            INGEST_STATS_TOPIC,
            json.dumps({**_ingest_stats, "reported_at": datetime.utcnow().isoformat(), "process": "worker"}),
            qos=0, retain=True,
        )


def parse_topic(topic: str, prefix: str) -> tuple[str | None, str | None, str | None]:
    """
    Split an MQTT topic into (kind, home, device):

        <prefix>/<home>/devices/<device>/data  → ("data", home, device)
        <prefix>/<home>/status                 → ("status", home, None)

    Anything else → (None, None, None).
    """
    parts = topic.split("/")
    head = prefix.strip("/").split("/")
    if parts[:len(head)] != head:
        return None, None, None
    rest = parts[len(head):]
    if len(rest) == 4 and rest[1] == "devices" and rest[3] == "data" and rest[0] and rest[2]:
        return "data", rest[0], rest[2]
    if len(rest) == 2 and rest[1] == "status" and rest[0]:
        return "status", rest[0], None
    return None, None, None


MAX_FUTURE_SKEW = timedelta(minutes=5)
MAX_READING_AGE = timedelta(days=30)


def parse_reading_time(raw, now: datetime) -> datetime | None:
    """
    The reading's own time as naive UTC.

    • Missing or unparseable → `now`.
    • An offset is converted to UTC (it used to be dropped, shifting e.g. +01:00 readings by an hour).
    • More than 5 minutes in the future (a wrong RPi clock) → `now`.
    • Older than 30 days → None (rejected: it would silently rewrite old summaries).
    """
    if not raw:
        return now
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return now
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    if parsed > now + MAX_FUTURE_SKEW:
        return now
    if parsed < now - MAX_READING_AGE:
        return None
    return parsed


# All backend workers join this group; the broker delivers each reading once per group.
_SHARED_GROUP = "wattwise-ingest"
# The worker process is the only ingester, with a FIXED client id and a persistent
# session: while it is down (a deploy, a crash) the broker queues QoS-1 readings for
# that client id and hands them over when it reconnects, so nothing is lost.
WORKER_CLIENT_ID = "wattwise-ingest-worker"
# The worker reports why readings were accepted/dropped here (retained), so the API
# processes — which no longer see telemetry — can still show it in the admin panel.
INGEST_STATS_TOPIC = "wattwise/system/ingest-stats"
_role: str = "all"
_remote_ingest_stats: dict = {}


def subscriptions_for(role: str, prefix: str) -> list[tuple[str, int]]:
    """(topic, qos) pairs a process of this role subscribes to."""
    data, status = f"{prefix}/+/devices/+/data", f"{prefix}/+/status"
    if role == "worker":
        return [(data, 1), (status, 1), ("$SYS/broker/#", 0)]
    if role == "api":
        # No telemetry: only broker health and the worker's ingest report.
        return [("$SYS/broker/#", 0), (INGEST_STATS_TOPIC, 0)]
    # "all": several uvicorn workers share one process role, so use a shared
    # subscription — the broker delivers each message to ONE of them.
    return [(f"$share/{_SHARED_GROUP}/{data}", 1), (f"$share/{_SHARED_GROUP}/{status}", 0), ("$SYS/broker/#", 0)]


def on_connect(client, userdata, flags, rc):
    global _mqtt_connected
    if rc == 0:
        _mqtt_connected = True
        logger.info("MQTT connected successfully (role=%s)", _role)
        for topic, qos in subscriptions_for(_role, settings.MQTT_TOPIC_PREFIX):
            client.subscribe(topic, qos=qos)
            logger.info("Subscribed to: %s", topic)
        return
    logger.error("MQTT connection failed with code %s", rc)


def on_disconnect(client, userdata, rc):
    global _mqtt_connected
    _mqtt_connected = False
    if rc != 0:
        logger.warning("MQTT unexpected disconnect (rc=%s) — auto-reconnect will trigger", rc)


def on_message(client, userdata, msg):
    """Process incoming MQTT messages — telemetry, broker stats, or other."""
    # Route broker telemetry to the stats cache and bail out
    if msg.topic.startswith("$SYS/broker/"):
        try:
            raw = msg.payload.decode("utf-8", errors="ignore").strip()
            value = float(raw) if raw.replace(".", "", 1).replace("-", "", 1).isdigit() else raw
            _broker_stats[msg.topic] = {"value": value, "ts": datetime.utcnow().isoformat()}
        except Exception as exc:
            logger.debug("Failed to cache broker stat %s: %s", msg.topic, exc)
        return

    if msg.topic == INGEST_STATS_TOPIC:
        try:
            _remote_ingest_stats.clear()
            _remote_ingest_stats.update(json.loads(msg.payload.decode("utf-8")))
        except ValueError:
            pass
        return

    """Process incoming energy telemetry from smart plugs."""
    kind, home_key, topic_device = parse_topic(msg.topic, settings.MQTT_TOPIC_PREFIX)
    if kind == "status":
        _handle_status(home_key, msg.payload)
        return
    if kind != "data":
        return
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
        logger.debug("MQTT message on %s", msg.topic)

        entity_id = _sanitize_entity_id(payload.get("entity_id") or topic_device)
        if not entity_id:
            _count("invalid", f"no entity_id on {msg.topic}")
            return

        recorded_at = parse_reading_time(payload.get("timestamp"), datetime.utcnow())
        if recorded_at is None:
            _count("bad_timestamp", f"{home_key}/{entity_id}: {payload.get('timestamp')!r}")
            return

        # Validate fields — skip malformed readings
        try:
            power_watts, current_amps, voltage_volts, energy_kwh = _validate_payload(payload)
        except ValueError as ve:
            _count("invalid", f"{home_key}/{entity_id}: {ve}")
            return

        switch_state = payload.get("switch_state", "unknown")
        if switch_state not in ("on", "off", "unknown"):
            switch_state = "unknown"

        # Hand the write to the app's event loop. on_message runs on paho's network
        # thread, so this must be threadsafe. The device is matched there, and only a
        # matched reading reaches MySQL or InfluxDB.
        if _loop is not None and not _loop.is_closed():
            asyncio.run_coroutine_threadsafe(
                _write_reading_to_db(
                    home_key, entity_id, power_watts, current_amps,
                    voltage_volts, energy_kwh, switch_state, recorded_at
                ),
                _loop,
            )
        else:
            _count("db_error", "event loop unavailable")

    except Exception as e:
        _count("invalid", f"unparseable message on {msg.topic}: {e}")


def _handle_status(home_key: str, raw: bytes):
    """Publisher heartbeat / last-will on wattwise/homes/<home>/status."""
    try:
        text_payload = raw.decode("utf-8", errors="ignore").strip()
        try:
            status = str(json.loads(text_payload).get("status", "")).lower()
        except (ValueError, AttributeError):
            status = text_payload.lower()
        if status not in ("online", "offline", "stale"):
            return
        if _loop is not None and not _loop.is_closed():
            asyncio.run_coroutine_threadsafe(_save_publisher_status(home_key, status), _loop)
    except Exception as e:
        logger.debug("Bad status message for %s: %s", home_key, e)


async def _save_publisher_status(home_key: str, status: str):
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Home).where(Home.mqtt_username == home_key)
                .values(publisher_status=status, publisher_seen_at=datetime.utcnow())
            )
            await session.commit()
    except Exception as e:
        logger.warning("Could not save publisher status for %s: %s", home_key, e)


def _write_to_influx(
    entity_id: str,
    power_watts: float,
    current_amps, voltage_volts,
    energy_kwh,
    recorded_at: datetime,
    home_id: int | None = None,
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

        tags = {"entity_id": entity_id}
        if home_id is not None:
            # Lets series be told apart per home even if two homes share an entity_id.
            tags["home_id"] = str(home_id)
        influx.write_points([{
            "measurement": "W",
            "tags": tags,
            "fields": fields,
            "time": recorded_at.isoformat() + "Z",
        }])
    except Exception as e:
        logger.warning("InfluxDB write failed for %s: %s", entity_id, e)
        # Reset singleton so next call re-connects
        global _influx_client
        _influx_client = None


async def _touch_liveness(device_id: int, home_id: int) -> None:
    """
    Record "last heard from", at most once a minute per device and per home.

    Deliberately NOT part of the reading's transaction: a home's devices report in the
    same instant, and six concurrent transactions each updating the one `homes` row
    deadlocked and cost readings. Here each row is claimed (check-and-set with no
    await in between, so only one coroutine wins) and updated in its own tiny
    transaction; a failure only delays the liveness display.
    """
    mono = time.monotonic()
    touch_device = mono - _last_seen_written.get(device_id, 0.0) >= 60
    touch_home = mono - _home_seen_written.get(home_id, 0.0) >= 60
    if touch_device:
        _last_seen_written[device_id] = mono
    if touch_home:
        _home_seen_written[home_id] = mono
    if not (touch_device or touch_home):
        return
    seen = datetime.utcnow()
    try:
        async with AsyncSessionLocal() as session:
            if touch_device:
                await session.execute(update(Device).where(Device.id == device_id).values(last_seen_at=seen))
                await session.commit()
            if touch_home:
                await session.execute(update(Home).where(Home.id == home_id).values(last_seen_at=seen))
                await session.commit()
    except Exception as e:
        logger.debug("liveness update skipped: %s", e)


async def _resolve_home_id(session, home_key: str) -> int | None:
    """Home id for an MQTT username, cached briefly (homes are provisioned rarely)."""
    now = time.monotonic()
    cached = _home_cache.get(home_key)
    if cached and now - cached[1] < _HOME_CACHE_TTL:
        return cached[0]
    home_id = (await session.execute(
        select(Home.id).where(Home.mqtt_username == home_key, Home.is_active)
    )).scalar_one_or_none()
    _home_cache[home_key] = (home_id, now)
    return home_id


async def _write_reading_to_db(
    home_key: str,
    entity_id: str,
    power_watts: float,
    current_amps, voltage_volts,
    energy_kwh,
    switch_state: str,
    recorded_at: datetime,
):
    """
    Persist one reading. The device is found inside the home named by the topic — the
    broker's ACL guarantees a publisher can only use its own home's topic, so a home
    can never write into another home's devices, and two homes may reuse an entity_id.
    """
    try:
        async with AsyncSessionLocal() as session:
            home_id = await _resolve_home_id(session, home_key)
            if home_id is not None:
                device = (await session.execute(
                    select(Device).where(
                        Device.home_id == home_id, Device.entity_id == entity_id, Device.is_active
                    ).order_by(Device.id).limit(1)
                )).scalar_one_or_none()
            elif settings.MQTT_STRICT_HOME_BINDING:
                _count("unknown_home", f"no registered home publishes as '{home_key}'")
                return
            else:
                device = (await session.execute(
                    select(Device).where(Device.entity_id == entity_id, Device.is_active).order_by(Device.id).limit(1)
                )).scalar_one_or_none()

            if not device:
                _count("unknown_device", f"{home_key}: no active device with entity_id '{entity_id}'")
                return

            # Duplicate guard: skip if reading already exists for this device+timestamp (within 5s)
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
                _count("duplicate")
                return

            session.add(EnergyReading(
                device_id=device.id,
                recorded_at=recorded_at,
                power_watts=power_watts,
                current_amps=current_amps,
                voltage_volts=voltage_volts,
                energy_kwh=energy_kwh,
                switch_state=switch_state,
            ))
            await session.commit()
            _count("accepted")
            device_id, device_home_id = device.id, device.home_id

        await _touch_liveness(device_id, device_home_id)

        # Time-series copy, off the event loop (the client is synchronous).
        await asyncio.to_thread(
            _write_to_influx, entity_id, power_watts, current_amps, voltage_volts, energy_kwh, recorded_at, device_home_id
        )
    except Exception as e:
        _count("db_error", f"{home_key}/{entity_id}: {e}")


# ── Lifecycle ─────────────────────────────────────────────────

def start_mqtt(role: str = "all"):
    global _mqtt_client, _loop, _role
    _role = role
    try:
        _loop = asyncio.get_running_loop()
    except RuntimeError:
        _loop = asyncio.get_event_loop()
    import uuid
    if role == "worker":
        _mqtt_client = mqtt.Client(client_id=WORKER_CLIENT_ID, clean_session=False)
    else:
        _mqtt_client = mqtt.Client(client_id=f"wattwise-backend-{uuid.uuid4().hex[:8]}", clean_session=True)

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


def get_broker_stats_snapshot() -> dict:
    """
    Return a tidy snapshot of the most useful $SYS/broker/* metrics.

    Mosquitto publishes these on a sys_interval (default 10s). The values are
    populated by on_message and live in the _broker_stats module-level dict.
    """
    def _val(topic):
        entry = _broker_stats.get(topic)
        return entry["value"] if entry else None

    def _ts(topic):
        entry = _broker_stats.get(topic)
        return entry["ts"] if entry else None

    interesting = {
        "uptime":              "$SYS/broker/uptime",
        "version":             "$SYS/broker/version",
        "clients_connected":   "$SYS/broker/clients/connected",
        "clients_active":      "$SYS/broker/clients/active",
        "clients_total":       "$SYS/broker/clients/total",
        "clients_maximum":     "$SYS/broker/clients/maximum",
        "messages_received":   "$SYS/broker/messages/received",
        "messages_sent":       "$SYS/broker/messages/sent",
        "messages_stored":     "$SYS/broker/messages/stored",
        "retained_count":      "$SYS/broker/retained messages/count",
        "subscriptions_count": "$SYS/broker/subscriptions/count",
        "bytes_received":      "$SYS/broker/bytes/received",
        "bytes_sent":          "$SYS/broker/bytes/sent",
        "load_msg_in_1min":    "$SYS/broker/load/messages/received/1min",
        "load_msg_out_1min":   "$SYS/broker/load/messages/sent/1min",
        "load_publish_in_1min":  "$SYS/broker/load/publish/received/1min",
        "load_publish_out_1min": "$SYS/broker/load/publish/sent/1min",
    }

    metrics = {k: _val(t) for k, t in interesting.items()}
    last_update = max(
        (entry["ts"] for entry in _broker_stats.values()),
        default=None,
    )

    return {
        "broker_connected": _mqtt_connected,
        # Counts since this worker started (each of the API workers keeps its own).
        "ingest": get_ingest_stats(),
        "topics_cached": len(_broker_stats),
        "last_update": last_update,
        "metrics": metrics,
    }
