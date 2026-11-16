"""
WattWise — broker account management (Mosquitto Dynamic Security).

The broker authenticates two kinds of account:

  • legacy accounts in the password file (the backend itself, home_001…home_015) —
    created by the `mosquitto-init` compose job and never touched from here;
  • accounts for homes provisioned from the admin portal — created here, at runtime,
    through the Dynamic Security plugin's control topic. No file edits, no restart.

Each provisioned home gets one client and one role named after it; the role's only
permission is to publish under wattwise/homes/<username>/#, so a home can never write
another home's topic.
"""
import json
import logging
import re
import secrets
import threading
import uuid
from typing import Optional

import paho.mqtt.client as mqtt

from app.config import settings

logger = logging.getLogger("broker_admin")

CONTROL_TOPIC = "$CONTROL/dynamic-security/v1"
RESPONSE_TOPIC = "$CONTROL/dynamic-security/v1/response"
USERNAME_RE = re.compile(r"^home_[0-9]{3,6}$")
# home_001…home_015 live in the password file (see docker-compose mosquitto-init).
LEGACY_MAX_HOME_NUMBER = 15


class BrokerAdminError(RuntimeError):
    pass


def generate_mqtt_password() -> str:
    """A random broker password that is safe to paste into YAML and shell (no quotes/specials)."""
    return secrets.token_urlsafe(24)


def is_legacy_username(username: Optional[str]) -> bool:
    """True for the accounts that live in the password file and cannot be managed here."""
    if not username or not USERNAME_RE.match(username):
        return False
    return int(username.split("_")[1]) <= LEGACY_MAX_HOME_NUMBER


def next_home_username(existing: list[str]) -> str:
    """Next free home_NNN after every existing one and after the legacy block."""
    highest = LEGACY_MAX_HOME_NUMBER
    for name in existing:
        if name and USERNAME_RE.match(name):
            highest = max(highest, int(name.split("_")[1]))
    return f"home_{highest + 1:03d}"


def home_topic(username: str) -> str:
    return f"{settings.MQTT_TOPIC_PREFIX}/{username}/#"


def provision_commands(username: str, password: str) -> list[dict]:
    """Control commands that create a home's role and client (see module docstring)."""
    if not USERNAME_RE.match(username):
        raise BrokerAdminError(f"Invalid MQTT username: {username!r}")
    return [
        {"command": "createRole", "rolename": username, "textdescription": f"Publish for {username}",
         "acls": [{"acltype": "publishClientSend", "topic": home_topic(username), "priority": 5, "allow": True}]},
        {"command": "createClient", "username": username, "password": password,
         "textdescription": "WattWise home publisher", "roles": [{"rolename": username, "priority": 5}]},
    ]


def _run(commands: list[dict], tolerate: tuple[str, ...] = (), timeout: float = 10.0) -> list[dict]:
    """
    Send control commands as the provisioning account and wait for the broker's reply.
    Blocking (network) — call via asyncio.to_thread. Errors containing any `tolerate`
    fragment are accepted (used to make "already exists" idempotent).
    """
    if not settings.MQTT_DYNSEC_USER or not settings.MQTT_DYNSEC_PASS:
        raise BrokerAdminError("Broker provisioning is not configured (MQTT_DYNSEC_USER / MQTT_DYNSEC_PASS)")

    correlation = uuid.uuid4().hex
    for c in commands:
        c["correlationData"] = correlation
    done = threading.Event()
    result: dict = {}

    client = mqtt.Client(client_id=f"wattwise-provisioner-{correlation[:8]}", clean_session=True)
    client.username_pw_set(settings.MQTT_DYNSEC_USER, settings.MQTT_DYNSEC_PASS)

    def on_connect(c, userdata, flags, rc):
        if rc != 0:
            result["error"] = f"broker refused the provisioning account (rc={rc})"
            done.set()
            return
        c.subscribe(RESPONSE_TOPIC, qos=1)

    def on_subscribe(c, userdata, mid, granted_qos):
        c.publish(CONTROL_TOPIC, json.dumps({"commands": commands}), qos=1)

    def on_message(c, userdata, msg):
        try:
            responses = json.loads(msg.payload.decode("utf-8")).get("responses", [])
        except ValueError:
            return
        mine = [r for r in responses if r.get("correlationData") == correlation]
        if mine:
            result["responses"] = mine
            done.set()

    client.on_connect, client.on_subscribe, client.on_message = on_connect, on_subscribe, on_message
    try:
        client.connect(settings.MQTT_BROKER_HOST, settings.MQTT_BROKER_PORT, keepalive=15)
    except OSError as e:
        raise BrokerAdminError(f"Cannot reach the MQTT broker: {e}") from e
    client.loop_start()
    try:
        if not done.wait(timeout):
            raise BrokerAdminError(
                "No reply from the broker's dynamic-security plugin — is it enabled in mosquitto.conf?"
            )
    finally:
        client.loop_stop()
        client.disconnect()

    if "error" in result:
        raise BrokerAdminError(result["error"])
    for r in result["responses"]:
        err = r.get("error")
        if err and not any(fragment in err.lower() for fragment in tolerate):
            raise BrokerAdminError(f"{r.get('command')}: {err}")
    return result["responses"]


def provision_home(username: str, password: str) -> None:
    """Create (or reset) the broker account for a home. Idempotent."""
    responses = _run(provision_commands(username, password), tolerate=("already exists",))
    client_existed = any(r.get("command") == "createClient" and r.get("error") for r in responses)
    if client_existed:
        # A previous attempt left the account behind: make it match what was asked for.
        # (The broker answers "Internal error" when the role is already attached.)
        _run([{"command": "addClientRole", "username": username, "rolename": username, "priority": 5}],
             tolerate=("already", "internal error"))
        _run([
            {"command": "setClientPassword", "username": username, "password": password},
            {"command": "enableClient", "username": username},
        ])
    logger.info("Broker account ready for %s (%s)", username, "reset" if client_existed else "created")


def set_password(username: str, password: str) -> None:
    _run([{"command": "setClientPassword", "username": username, "password": password}])
    # Drop the current connection so the old password stops working immediately.
    _run([{"command": "disableClient", "username": username}, {"command": "enableClient", "username": username}])


def set_enabled(username: str, enabled: bool) -> None:
    _run([{"command": "enableClient" if enabled else "disableClient", "username": username}])


def delete_home(username: str) -> None:
    _run([{"command": "deleteClient", "username": username}, {"command": "deleteRole", "rolename": username}],
         tolerate=("not found",))
