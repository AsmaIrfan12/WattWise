#!/usr/bin/env python3
"""
WattWise Dummy Data Sender
==========================
Sends realistic energy readings for 14 dummy test households.

On startup  → backfills 2 days of historical readings (5-min intervals)
             using parallel threads — completes in ~2-3 minutes
Then runs   → sends live readings every 5 minutes indefinitely

Usage:
    pip install requests
    python dummy_data_sender.py
    python dummy_data_sender.py --no-backfill
    python dummy_data_sender.py --backfill-days 7
    python dummy_data_sender.py --url http://localhost:8000
    python dummy_data_sender.py --live-cycles 1 --interval 2
    python dummy_data_sender.py --admin-email admin@wattwise.co.uk --admin-password admin
"""

import argparse
import logging
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta

import requests

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("wattwise-dummy")

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_BASE_URL    = "http://localhost:8000"
SEND_INTERVAL_SEC   = 300       # 5 minutes between live readings
BACKFILL_DAYS       = 2         # days of historical data to seed
BACKFILL_INTERVAL   = 5         # minutes between backfill readings
REQUEST_TIMEOUT     = 5         # seconds per HTTP request
BACKFILL_WORKERS    = 8         # parallel threads for backfill
LIVE_WORKERS        = 8         # parallel threads for live sends
MAX_RETRIES         = 3         # retries per reading on transient failures

# ── Dummy credentials ─────────────────────────────────────────────────────────
DUMMY_ACCOUNTS = [
    {"email": "liam.jenkins@wattwise-test.co.uk",    "password": "WattTest2024!"},
    {"email": "priya.sharma@wattwise-test.co.uk",    "password": "WattTest2024!"},
    {"email": "owen.davies@wattwise-test.co.uk",     "password": "WattTest2024!"},
    {"email": "sophie.williams@wattwise-test.co.uk", "password": "WattTest2024!"},
    {"email": "m.hassan@wattwise-test.co.uk",        "password": "WattTest2024!"},
    {"email": "emma.thomas@wattwise-test.co.uk",     "password": "WattTest2024!"},
    {"email": "c.murphy@wattwise-test.co.uk",        "password": "WattTest2024!"},
    {"email": "aisha.patel@wattwise-test.co.uk",     "password": "WattTest2024!"},
    {"email": "j.roberts@wattwise-test.co.uk",       "password": "WattTest2024!"},
    {"email": "f.alrashid@wattwise-test.co.uk",      "password": "WattTest2024!"},
    {"email": "r.evans@wattwise-test.co.uk",         "password": "WattTest2024!"},
    {"email": "n.kowalski@wattwise-test.co.uk",      "password": "WattTest2024!"},
    {"email": "t.hughes@wattwise-test.co.uk",        "password": "WattTest2024!"},
    {"email": "m.lin@wattwise-test.co.uk",           "password": "WattTest2024!"},
]

# ── Appliance profiles (UK 230V, realistic usage patterns) ───────────────────
PROFILES = {
    "kettle": {
        "on": (1800, 2500), "standby": (0, 1),
        "peak_hours": {7, 8, 10, 12, 15, 16, 20, 21},
        "p_peak": 0.30, "p_base": 0.05,
        "amps": (7.8, 10.9), "volts": (228, 234),
    },
    "microwave": {
        "on": (600, 950), "standby": (2, 4),
        "peak_hours": {12, 13, 18, 19, 20},
        "p_peak": 0.18, "p_base": 0.03,
        "amps": (2.6, 4.1), "volts": (228, 234),
    },
    "washing_machine": {
        "on": (300, 2100), "standby": (0, 2),
        "peak_hours": {9, 10, 11, 14, 15, 19},
        "p_peak": 0.15, "p_base": 0.07,
        "amps": (1.3, 9.1), "volts": (228, 234),
    },
    "dishwasher": {
        "on": (700, 1900), "standby": (1, 3),
        "peak_hours": {13, 14, 20, 21, 22},
        "p_peak": 0.18, "p_base": 0.03,
        "amps": (3.0, 8.3), "volts": (228, 234),
    },
    "toaster": {
        "on": (700, 900), "standby": (0, 1),
        "peak_hours": {7, 8, 9, 12, 13},
        "p_peak": 0.22, "p_base": 0.02,
        "amps": (3.0, 3.9), "volts": (228, 234),
    },
    "airfryer": {
        "on": (900, 1600), "standby": (0, 1),
        "peak_hours": {12, 13, 17, 18, 19, 20},
        "p_peak": 0.14, "p_base": 0.02,
        "amps": (3.9, 7.0), "volts": (228, 234),
    },
}

# Per-household usage multiplier (busier families use more power)
HOUSEHOLD_FACTORS = [
    0.70, 1.10, 1.30, 0.65, 1.40,
    1.05, 0.60, 1.20, 0.85, 1.45,
    0.75, 0.90, 1.25, 0.95,
]


# ── Reading generator ─────────────────────────────────────────────────────────

def generate_reading(appliance_key: str, at: datetime, factor: float = 1.0) -> dict:
    profile = PROFILES.get(appliance_key)
    if not profile:
        w = random.uniform(1, 5)
        return {"power_watts": round(w, 2), "current_amps": round(w / 230, 3),
                "voltage_volts": 230.0, "energy_kwh": round(w / 1000 / 12, 6), "switch_state": "on"}

    is_peak = at.hour in profile["peak_hours"]
    p_on    = min(0.95, (profile["p_peak"] if is_peak else profile["p_base"]) * factor)
    is_on   = random.random() < p_on

    if is_on:
        watts = random.uniform(*profile["on"]) * factor
        amps  = random.uniform(*profile["amps"])
        state = "on"
    else:
        watts = random.uniform(*profile["standby"])
        amps  = watts / 230
        # Backend enum currently supports: on/off/unknown.
        state = "off" if watts < 2 else "unknown"

    volts = random.uniform(*profile["volts"]) * random.uniform(0.98, 1.02)
    kwh   = round((watts / 1000) * (BACKFILL_INTERVAL / 60), 6)

    return {
        "power_watts":   round(watts, 2),
        "current_amps":  round(amps, 3),
        "voltage_volts": round(volts, 1),
        "energy_kwh":    kwh,
        "switch_state":  state,
    }


# ── API client ────────────────────────────────────────────────────────────────

class WattWiseClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def _session(self) -> requests.Session:
        """Each thread gets its own session (not thread-safe to share)."""
        s = requests.Session()
        s.headers["Content-Type"] = "application/json"
        return s

    def login(self, email: str, password: str) -> str | None:
        try:
            r = self._session().post(
                f"{self.base}/api/auth/login",
                json={"email": email, "password": password},
                timeout=REQUEST_TIMEOUT,
            )
            return r.json().get("access_token") if r.status_code == 200 else None
        except Exception as e:
            log.error("Login error %s: %s", email, e)
            return None

    def get_homes(self, token: str) -> list:
        try:
            r = requests.get(
                f"{self.base}/api/homes",
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def get_devices(self, token: str, home_id: int) -> list:
        try:
            r = requests.get(
                f"{self.base}/api/homes/{home_id}/devices",
                headers={"Authorization": f"Bearer {token}"},
                timeout=REQUEST_TIMEOUT,
            )
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def post_reading(self, token: str, device_id: int, reading: dict,
                     recorded_at: datetime | None = None,
                     session: requests.Session | None = None) -> bool:
        payload = {"device_id": device_id, **reading}
        if recorded_at:
            payload["recorded_at"] = recorded_at.isoformat()
        sess = session or self._session()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = sess.post(
                    f"{self.base}/api/readings/",
                    json=payload,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=REQUEST_TIMEOUT,
                )
                if r.status_code == 201:
                    return True
                if r.status_code in (401, 403, 404):
                    return False
            except Exception:
                pass
            time.sleep(0.1 * attempt)
        return False


# ── Session builder ───────────────────────────────────────────────────────────

def build_sessions(client: WattWiseClient) -> list[dict]:
    sessions = []
    for idx, creds in enumerate(DUMMY_ACCOUNTS):
        email = creds["email"]
        log.info("Logging in %s ...", email)
        token = client.login(email, creds["password"])
        if not token:
            log.warning("Skipping %s — login failed", email)
            continue

        homes = client.get_homes(token)
        if not homes:
            log.warning("No homes for %s", email)
            continue

        home    = homes[0]
        devices = client.get_devices(token, home["id"])
        if not devices:
            log.warning("No devices for %s", email)
            continue

        factor = HOUSEHOLD_FACTORS[idx] if idx < len(HOUSEHOLD_FACTORS) else 1.0
        sessions.append({
            "email":    email,
            "password": creds["password"],
            "token":    token,
            "home_id":  home["id"],
            "devices":  devices,
            "factor":   factor,
        })
        log.info("  ✅ %-42s home_id=%-3s devices=%d factor=%.2f",
                 email, home["id"], len(devices), factor)

    log.info("Sessions ready: %d/%d accounts", len(sessions), len(DUMMY_ACCOUNTS))
    return sessions


# ── Backfill (parallel) ───────────────────────────────────────────────────────

def _backfill_task(args: tuple) -> tuple[int, int]:
    """Worker: send all backfill readings for one device. Returns (sent, failed)."""
    base_url, token, device_id, appliance_key, factor, timestamps = args
    client = WattWiseClient(base_url)
    session = client._session()
    sent = failed = 0
    for ts in timestamps:
        reading = generate_reading(appliance_key, ts, factor)
        if client.post_reading(token, device_id, reading, recorded_at=ts, session=session):
            sent += 1
        else:
            failed += 1
    return sent, failed


def backfill(client: WattWiseClient, sessions: list[dict], days: int,
             admin_email: str | None, admin_password: str | None):
    now   = datetime.utcnow()
    start = now - timedelta(days=days)

    timestamps = []
    t = start
    while t <= now:
        timestamps.append(t)
        t += timedelta(minutes=BACKFILL_INTERVAL)

    total_slots = len(timestamps)

    # Build task list: one task per device across all sessions
    tasks = []
    for sess in sessions:
        for dev in sess["devices"]:
            tasks.append((
                client.base, sess["token"],
                dev["id"], dev.get("appliance_key", ""),
                sess["factor"], timestamps,
            ))

    total_devices = len(tasks)
    total_readings = total_devices * total_slots
    log.info("Backfilling %d days → %d slots, %d devices, ~%d total readings",
             days, total_slots, total_devices, total_readings)
    log.info("Running %d parallel workers — this will take ~1-3 minutes...", BACKFILL_WORKERS)

    sent_total = failed_total = 0
    completed = 0

    with ThreadPoolExecutor(max_workers=BACKFILL_WORKERS) as pool:
        futures = {pool.submit(_backfill_task, t): t for t in tasks}
        for future in as_completed(futures):
            sent, failed = future.result()
            sent_total   += sent
            failed_total += failed
            completed    += 1
            log.info("  [%d/%d devices] sent=%d failed=%d (running total)",
                     completed, total_devices, sent_total, failed_total)

    log.info("Backfill complete — sent=%d failed=%d", sent_total, failed_total)

    # Trigger backend aggregations so data shows up in summaries/charts instantly
    if admin_email and admin_password:
        log.info("Triggering backend data aggregations for the past %d days...", days)
        admin_token = client.login(admin_email, admin_password)
        if admin_token:
            try:
                r = requests.post(
                    f"{client.base}/api/admin/trigger-aggregations?days={days}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    timeout=30,
                )
                if r.status_code == 200:
                    log.info("✅ Core aggregations updated successfully!")
                else:
                    log.warning("⚠️ Aggregation trigger failed: %s", r.text)
            except Exception as e:
                log.warning("⚠️ Could not reach aggregation endpoint: %s", e)
        else:
            log.warning("⚠️ Could not login as admin to trigger aggregations.")
    else:
        log.info("Skipping auto-aggregation trigger (no admin credentials provided).")


# ── Live loop (parallel) ──────────────────────────────────────────────────────

def _live_task(args: tuple) -> bool:
    """Worker: send one live reading for one device."""
    base_url, token, device_id, appliance_key, factor, now, interval_min = args
    client  = WattWiseClient(base_url)
    session = client._session()
    reading = generate_reading(appliance_key, now, factor)
    reading["energy_kwh"] = round((reading["power_watts"] / 1000) * (interval_min / 60), 6)
    return client.post_reading(token, device_id, reading, session=session)


def live_loop(client: WattWiseClient, sessions: list[dict], interval_sec: int, max_cycles: int = 0):
    log.info("Starting live loop — sending every %ds (%d min)", interval_sec, interval_sec // 60)
    cycle = 0

    while True:
        cycle += 1
        now   = datetime.utcnow()
        log.info("── Cycle %d @ %s UTC ──", cycle, now.strftime("%Y-%m-%d %H:%M"))

        # Re-login any sessions with expired tokens (7-day JWT, refresh proactively)
        for sess in sessions:
            if cycle % 500 == 0:   # refresh roughly every ~41 hours
                new_token = client.login(sess["email"], sess["password"])
                if new_token:
                    sess["token"] = new_token

        # Build tasks for all devices
        tasks = [
            (client.base, sess["token"], dev["id"],
             dev.get("appliance_key", ""), sess["factor"], now, interval_sec / 60)
            for sess in sessions
            for dev in sess["devices"]
        ]

        sent = failed = 0
        with ThreadPoolExecutor(max_workers=LIVE_WORKERS) as pool:
            for ok in pool.map(_live_task, tasks):
                if ok:
                    sent += 1
                else:
                    failed += 1

        log.info("Cycle %d done — sent=%d failed=%d | sleeping %ds",
                 cycle, sent, failed, interval_sec)
        if max_cycles > 0 and cycle >= max_cycles:
            log.info("Reached max live cycles (%d). Exiting cleanly.", max_cycles)
            return
        time.sleep(interval_sec)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="WattWise dummy data sender")
    parser.add_argument("--url",           default=DEFAULT_BASE_URL)
    parser.add_argument("--no-backfill",   action="store_true")
    parser.add_argument("--backfill-days", type=int, default=BACKFILL_DAYS)
    parser.add_argument("--interval",      type=int, default=SEND_INTERVAL_SEC)
    parser.add_argument("--live-cycles",   type=int, default=0,
                        help="Number of live cycles to run (0 = infinite)")
    parser.add_argument("--admin-email",   default=os.getenv("ADMIN_EMAIL", ""))
    parser.add_argument("--admin-password", default=os.getenv("ADMIN_PASSWORD", ""))
    args = parser.parse_args()

    if args.interval <= 0:
        log.error("--interval must be greater than 0")
        sys.exit(2)

    if args.live_cycles < 0:
        log.error("--live-cycles cannot be negative")
        sys.exit(2)

    log.info("WattWise Dummy Data Sender  |  API: %s", args.url)

    client   = WattWiseClient(args.url)
    sessions = build_sessions(client)

    if not sessions:
        log.error("No sessions — check server is running and accounts exist")
        sys.exit(1)

    if not args.no_backfill:
        backfill(client, sessions, args.backfill_days, args.admin_email or None, args.admin_password or None)

    live_loop(client, sessions, args.interval, max_cycles=args.live_cycles)


if __name__ == "__main__":
    main()
