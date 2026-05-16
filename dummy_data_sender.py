#!/usr/bin/env python3
"""
WattWise Dummy Data Sender  v2.0
=================================
Sends realistic energy readings for 15 households with distinct lifestyle
profiles — producing the spread needed for persona classification, anomaly
detection, and community ranking research.

Each household has:
  • Named lifestyle persona (maps to research taxonomy)
  • Wake / sleep schedule
  • Weekday-home flag (commuters are absent 09-17 Mon-Fri)
  • Per-device affinity multipliers
  • Peak-hour avoidance probability (16:00-19:00 UK tariff window)
  • Weekend usage boost
  • Usage-noise level (predictable retirees vs erratic students)

On startup  → backfills historical readings (5-min intervals)
Then runs   → sends live readings at --interval seconds indefinitely
"""

import argparse
import csv
import logging
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

import requests

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("wattwise-dummy")

# ── Config ────────────────────────────────────────────────────────────────────
DEFAULT_BASE_URL   = "http://localhost:8000"
SEND_INTERVAL_SEC  = 0.1
BACKFILL_DAYS      = 2
BACKFILL_INTERVAL  = 5       # minutes between backfill slots
REQUEST_TIMEOUT    = 5
BACKFILL_WORKERS   = 8
LIVE_WORKERS       = 8
MAX_RETRIES        = 3

DUMMY_ACCOUNTS: list = []

# ── Appliance base profiles (UK 230 V) ────────────────────────────────────────
# on/standby watts, typical active hours, baseline probabilities, electrical params
APPLIANCE_BASE = {
    "kettle": {
        "on": (1800, 2500), "standby": (0, 1),
        "peak_hours": {6, 7, 8, 9, 10, 12, 15, 16, 20, 21},
        "p_peak": 0.30, "p_base": 0.06,
        "amps": (7.8, 10.9), "volts": (228, 234),
    },
    "microwave": {
        "on": (600, 950), "standby": (2, 4),
        "peak_hours": {7, 12, 13, 17, 18, 19, 20},
        "p_peak": 0.18, "p_base": 0.03,
        "amps": (2.6, 4.1), "volts": (228, 234),
    },
    "washing_machine": {
        "on": (300, 2100), "standby": (0, 2),
        "peak_hours": {8, 9, 10, 11, 13, 14, 19},
        "p_peak": 0.15, "p_base": 0.06,
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


# ── Household persona definitions ─────────────────────────────────────────────

@dataclass
class HouseholdProfile:
    """Full lifestyle profile driving reading generation for one household."""
    name: str
    # Overall energy scale (1.0 = average UK home)
    base_factor: float
    # Hour the household typically wakes up (24h)
    wake_hour: int
    # Hour the household typically goes to sleep (24h)
    sleep_hour: int
    # Is someone home on weekdays 09:00-17:00?
    home_weekday_daytime: bool
    # 0.0 = ignores peak tariff; 1.0 = always shifts loads off-peak
    peak_avoidance: float
    # Multiplier applied to each appliance (1.0 = profile default)
    appliance_affinity: Dict[str, float]
    # Boost to base_factor on Sat/Sun
    weekend_boost: float
    # Std-dev of Gaussian noise on watts (0 = very predictable, 0.3 = erratic)
    noise_sigma: float
    # Probability of completely random "anomaly spike" in any 5-min slot
    anomaly_prob: float = 0.008


# 15 named profiles — designed to produce spread across all 5 research personas
HOUSEHOLD_PROFILES: list[HouseholdProfile] = [
    # ── 1: Eco Champion — retired couple, energy-conscious ───────────────────
    HouseholdProfile(
        name="Eco Champion",
        base_factor=0.52,
        wake_hour=6, sleep_hour=21,
        home_weekday_daytime=True,
        peak_avoidance=0.90,
        appliance_affinity={"kettle": 1.1, "microwave": 0.6, "washing_machine": 0.7,
                            "dishwasher": 0.5, "toaster": 1.0, "airfryer": 0.4},
        weekend_boost=1.05,
        noise_sigma=0.08,
    ),
    # ── 2: Single Working Professional — commuter, microwave-heavy ───────────
    HouseholdProfile(
        name="Single Working Professional",
        base_factor=0.72,
        wake_hour=7, sleep_hour=23,
        home_weekday_daytime=False,
        peak_avoidance=0.15,
        appliance_affinity={"kettle": 1.3, "microwave": 1.8, "washing_machine": 0.5,
                            "dishwasher": 0.4, "toaster": 0.9, "airfryer": 1.4},
        weekend_boost=1.60,
        noise_sigma=0.18,
    ),
    # ── 3: Family with Young Children — high washing, morning chaos ──────────
    HouseholdProfile(
        name="Family with Young Children",
        base_factor=1.45,
        wake_hour=6, sleep_hour=22,
        home_weekday_daytime=False,
        peak_avoidance=0.20,
        appliance_affinity={"kettle": 1.4, "microwave": 1.3, "washing_machine": 2.8,
                            "dishwasher": 1.9, "toaster": 1.6, "airfryer": 1.2},
        weekend_boost=1.30,
        noise_sigma=0.25,
        anomaly_prob=0.015,
    ),
    # ── 4: Retired High Consumer — home all day, traditional habits ──────────
    HouseholdProfile(
        name="Retired High Consumer",
        base_factor=1.30,
        wake_hour=7, sleep_hour=21,
        home_weekday_daytime=True,
        peak_avoidance=0.10,
        appliance_affinity={"kettle": 1.8, "microwave": 0.9, "washing_machine": 1.2,
                            "dishwasher": 1.0, "toaster": 1.3, "airfryer": 0.7},
        weekend_boost=1.10,
        noise_sigma=0.10,
    ),
    # ── 5: Night-Owl Student — reversed schedule, peak hours are quiet ────────
    HouseholdProfile(
        name="Night-Owl Student",
        base_factor=0.68,
        wake_hour=11, sleep_hour=3,   # sleeps past midnight
        home_weekday_daytime=True,
        peak_avoidance=0.05,
        appliance_affinity={"kettle": 1.6, "microwave": 2.0, "washing_machine": 0.4,
                            "dishwasher": 0.2, "toaster": 0.5, "airfryer": 1.5},
        weekend_boost=1.20,
        noise_sigma=0.35,
        anomaly_prob=0.020,
    ),
    # ── 6: Active Improver — consciously shifting loads, moderate use ─────────
    HouseholdProfile(
        name="Active Improver",
        base_factor=0.92,
        wake_hour=6, sleep_hour=23,
        home_weekday_daytime=False,
        peak_avoidance=0.65,
        appliance_affinity={"kettle": 1.0, "microwave": 1.1, "washing_machine": 1.2,
                            "dishwasher": 1.1, "toaster": 1.0, "airfryer": 1.0},
        weekend_boost=1.25,
        noise_sigma=0.14,
    ),
    # ── 7: Tech-Savvy Eco Minimalist — very efficient, minimal standby ────────
    HouseholdProfile(
        name="Tech-Savvy Eco",
        base_factor=0.45,
        wake_hour=7, sleep_hour=23,
        home_weekday_daytime=False,
        peak_avoidance=0.85,
        appliance_affinity={"kettle": 0.7, "microwave": 0.8, "washing_machine": 0.6,
                            "dishwasher": 0.7, "toaster": 0.5, "airfryer": 0.6},
        weekend_boost=1.15,
        noise_sigma=0.07,
    ),
    # ── 8: Disengaged High Consumer — no awareness, everything on ────────────
    HouseholdProfile(
        name="Disengaged High Consumer",
        base_factor=1.65,
        wake_hour=8, sleep_hour=0,
        home_weekday_daytime=True,
        peak_avoidance=0.0,
        appliance_affinity={"kettle": 1.5, "microwave": 1.4, "washing_machine": 1.6,
                            "dishwasher": 1.8, "toaster": 1.3, "airfryer": 1.7},
        weekend_boost=1.35,
        noise_sigma=0.30,
        anomaly_prob=0.025,
    ),
    # ── 9: Work-From-Home — spread through the day, regular tea breaks ────────
    HouseholdProfile(
        name="Work-From-Home",
        base_factor=1.05,
        wake_hour=7, sleep_hour=22,
        home_weekday_daytime=True,
        peak_avoidance=0.30,
        appliance_affinity={"kettle": 2.0, "microwave": 1.4, "washing_machine": 1.1,
                            "dishwasher": 0.9, "toaster": 1.2, "airfryer": 1.1},
        weekend_boost=1.10,
        noise_sigma=0.16,
    ),
    # ── 10: Weekend-Heavy — minimal weekdays, high weekend ────────────────────
    HouseholdProfile(
        name="Weekend Heavy",
        base_factor=0.88,
        wake_hour=8, sleep_hour=23,
        home_weekday_daytime=False,
        peak_avoidance=0.25,
        appliance_affinity={"kettle": 1.0, "microwave": 1.0, "washing_machine": 1.5,
                            "dishwasher": 1.3, "toaster": 1.0, "airfryer": 1.3},
        weekend_boost=2.20,
        noise_sigma=0.22,
    ),
    # ── 11: Large Busy Family — highest total, chaotic schedules ─────────────
    HouseholdProfile(
        name="Large Busy Family",
        base_factor=1.80,
        wake_hour=5, sleep_hour=23,
        home_weekday_daytime=False,
        peak_avoidance=0.10,
        appliance_affinity={"kettle": 1.7, "microwave": 1.6, "washing_machine": 3.5,
                            "dishwasher": 2.5, "toaster": 2.0, "airfryer": 1.8},
        weekend_boost=1.40,
        noise_sigma=0.28,
        anomaly_prob=0.020,
    ),
    # ── 12: Energy-Anxious Moderate — lumpy patterns, lots of cycling ─────────
    HouseholdProfile(
        name="Energy-Anxious Moderate",
        base_factor=0.80,
        wake_hour=7, sleep_hour=22,
        home_weekday_daytime=True,
        peak_avoidance=0.55,
        appliance_affinity={"kettle": 1.1, "microwave": 0.9, "washing_machine": 0.8,
                            "dishwasher": 0.6, "toaster": 1.0, "airfryer": 0.7},
        weekend_boost=1.15,
        noise_sigma=0.40,   # anxious = erratic cycling
    ),
    # ── 13: Early Bird Couple — 5am active, quiet afternoons ─────────────────
    HouseholdProfile(
        name="Early Bird Couple",
        base_factor=0.90,
        wake_hour=5, sleep_hour=20,
        home_weekday_daytime=False,
        peak_avoidance=0.70,  # naturally avoids peak — already done by then
        appliance_affinity={"kettle": 1.5, "microwave": 0.7, "washing_machine": 1.3,
                            "dishwasher": 0.9, "toaster": 1.4, "airfryer": 0.8},
        weekend_boost=1.20,
        noise_sigma=0.12,
    ),
    # ── 14: Shift Worker — active 14:00-22:00, quiet mornings ────────────────
    HouseholdProfile(
        name="Shift Worker",
        base_factor=0.78,
        wake_hour=13, sleep_hour=1,
        home_weekday_daytime=False,
        peak_avoidance=0.05,  # arrives home right at peak — no awareness
        appliance_affinity={"kettle": 1.2, "microwave": 1.6, "washing_machine": 0.9,
                            "dishwasher": 0.7, "toaster": 0.6, "airfryer": 1.5},
        weekend_boost=1.30,
        noise_sigma=0.20,
    ),
    # ── 15: Frugal Elderly Single — very low, kettle-centric, predictable ─────
    HouseholdProfile(
        name="Frugal Elderly Single",
        base_factor=0.38,
        wake_hour=7, sleep_hour=20,
        home_weekday_daytime=True,
        peak_avoidance=0.80,
        appliance_affinity={"kettle": 1.4, "microwave": 0.5, "washing_machine": 0.4,
                            "dishwasher": 0.2, "toaster": 0.9, "airfryer": 0.3},
        weekend_boost=1.05,
        noise_sigma=0.06,
    ),
]


# ── Reading generator ─────────────────────────────────────────────────────────

def _is_awake(profile: HouseholdProfile, hour: int) -> bool:
    """True if this household is likely awake at this hour."""
    w, s = profile.wake_hour, profile.sleep_hour
    if s < w:  # wraps midnight (e.g. wake=13, sleep=1)
        return hour >= w or hour < s
    return w <= hour < s


def _occupancy(profile: HouseholdProfile, dt: datetime) -> float:
    """
    Returns a 0-1 occupancy probability.
    Commuter households drop to 0.05 on weekday office hours.
    """
    hour = dt.hour
    is_weekday = dt.weekday() < 5
    if not profile.home_weekday_daytime and is_weekday and 9 <= hour < 17:
        return 0.05
    if not _is_awake(profile, hour):
        return 0.0
    return 1.0


def generate_reading(appliance_key: str, at: datetime,
                     profile: HouseholdProfile,
                     interval_min: float = BACKFILL_INTERVAL) -> dict:
    base = APPLIANCE_BASE.get(appliance_key)
    if not base:
        w = random.uniform(1, 5)
        return {"power_watts": round(w, 2), "current_amps": round(w / 230, 3),
                "voltage_volts": 230.0, "energy_kwh": round(w / 1000 / 12, 6),
                "switch_state": "on"}

    hour = at.hour
    is_weekend = at.weekday() >= 5
    occupancy  = _occupancy(profile, at)
    aff        = profile.appliance_affinity.get(appliance_key, 1.0)
    scale      = profile.base_factor * aff
    if is_weekend:
        scale *= profile.weekend_boost

    # Peak-hour avoidance: some households deliberately don't run appliances 16-19
    UK_PEAK = set(range(16, 19))
    if hour in UK_PEAK and random.random() < profile.peak_avoidance:
        # Treat as standby / off
        watts = random.uniform(*base["standby"])
        amps  = watts / 230
        volts = random.uniform(*base["volts"]) * random.uniform(0.98, 1.02)
        kwh   = round((watts / 1000) * (interval_min / 60), 6)
        return {"power_watts": round(watts, 2), "current_amps": round(amps, 3),
                "voltage_volts": round(volts, 1), "energy_kwh": kwh, "switch_state": "off"}

    is_peak = hour in base["peak_hours"]
    p_on = min(0.95, (base["p_peak"] if is_peak else base["p_base"]) * scale * occupancy)
    is_on = random.random() < p_on

    if is_on:
        # Gaussian noise on the "on" wattage — erratic households vary more
        base_watts = random.uniform(*base["on"]) * scale
        noise = random.gauss(0, profile.noise_sigma * base_watts)
        watts = max(10.0, base_watts + noise)
        amps  = random.uniform(*base["amps"]) * scale
        state = "on"
    else:
        watts = random.uniform(*base["standby"])
        amps  = watts / 230
        state = "off" if watts < 2 else "unknown"

    # Rare anomaly spike
    if random.random() < profile.anomaly_prob:
        watts = random.uniform(*base["on"]) * scale * random.uniform(1.8, 3.0)
        state = "on"

    volts = random.uniform(*base["volts"]) * random.uniform(0.98, 1.02)
    kwh   = round((watts / 1000) * (interval_min / 60), 6)

    return {
        "power_watts":   round(watts, 2),
        "current_amps":  round(max(0.01, amps), 3),
        "voltage_volts": round(volts, 1),
        "energy_kwh":    kwh,
        "switch_state":  state,
    }


# ── CSV loader ────────────────────────────────────────────────────────────────

def load_dummy_accounts(csv_path: str) -> list:
    accounts = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Email", "").strip():
                    accounts.append({
                        "email":    row["Email"].strip(),
                        "password": row["Password"].strip(),
                    })
    except FileNotFoundError:
        log.warning("CSV not found: %s", csv_path)
    return accounts


# ── API client ────────────────────────────────────────────────────────────────

class WattWiseClient:
    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")

    def _session(self) -> requests.Session:
        s = requests.Session()
        s.headers["Content-Type"] = "application/json"
        return s

    def login(self, email: str, password: str) -> Optional[str]:
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
            r = requests.get(f"{self.base}/api/homes",
                             headers={"Authorization": f"Bearer {token}"},
                             timeout=REQUEST_TIMEOUT)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def get_devices(self, token: str, home_id: int) -> list:
        try:
            r = requests.get(f"{self.base}/api/homes/{home_id}/devices",
                             headers={"Authorization": f"Bearer {token}"},
                             timeout=REQUEST_TIMEOUT)
            return r.json() if r.status_code == 200 else []
        except Exception:
            return []

    def post_reading(self, token: str, device_id: int, reading: dict,
                     recorded_at: Optional[datetime] = None,
                     session: Optional[requests.Session] = None) -> bool:
        payload = {"device_id": device_id, **reading}
        if recorded_at:
            payload["recorded_at"] = recorded_at.isoformat()
        sess = session or self._session()
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                r = sess.post(f"{self.base}/api/readings/",
                              json=payload,
                              headers={"Authorization": f"Bearer {token}"},
                              timeout=REQUEST_TIMEOUT)
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

        profile = HOUSEHOLD_PROFILES[idx % len(HOUSEHOLD_PROFILES)]
        sessions.append({
            "email":    email,
            "password": creds["password"],
            "token":    token,
            "home_id":  home["id"],
            "devices":  devices,
            "profile":  profile,
        })
        log.info("  ✅ %-44s home_id=%-3s devices=%d persona='%s'",
                 email, home["id"], len(devices), profile.name)

    log.info("Sessions ready: %d/%d accounts", len(sessions), len(DUMMY_ACCOUNTS))
    return sessions


# ── Backfill ──────────────────────────────────────────────────────────────────

def _backfill_task(args: tuple) -> tuple[int, int]:
    base_url, token, device_id, appliance_key, profile, timestamps = args
    client  = WattWiseClient(base_url)
    session = client._session()
    sent = failed = 0
    for ts in timestamps:
        reading = generate_reading(appliance_key, ts, profile, BACKFILL_INTERVAL)
        if client.post_reading(token, device_id, reading, recorded_at=ts, session=session):
            sent += 1
        else:
            failed += 1
    return sent, failed


def backfill(client: WattWiseClient, sessions: list[dict], days: int,
             admin_email: Optional[str], admin_password: Optional[str]):
    now   = datetime.now(timezone.utc)
    start = now - timedelta(days=days)

    timestamps = []
    t = start
    while t <= now:
        timestamps.append(t)
        t += timedelta(minutes=BACKFILL_INTERVAL)

    tasks = []
    for sess in sessions:
        for dev in sess["devices"]:
            tasks.append((
                client.base, sess["token"],
                dev["id"], dev.get("appliance_key", ""),
                sess["profile"], timestamps,
            ))

    total_readings = len(tasks) * len(timestamps)
    log.info("Backfilling %d days → %d slots × %d devices = ~%d readings",
             days, len(timestamps), len(tasks), total_readings)
    log.info("Running %d parallel workers...", BACKFILL_WORKERS)

    sent_total = failed_total = completed = 0
    with ThreadPoolExecutor(max_workers=BACKFILL_WORKERS) as pool:
        futures = {pool.submit(_backfill_task, t): t for t in tasks}
        for future in as_completed(futures):
            sent, failed = future.result()
            sent_total   += sent
            failed_total += failed
            completed    += 1
            log.info("  [%d/%d devices] sent=%d failed=%d",
                     completed, len(tasks), sent_total, failed_total)

    log.info("Backfill complete — sent=%d failed=%d", sent_total, failed_total)

    if admin_email and admin_password:
        log.info("Triggering backend aggregations for past %d days...", days)
        admin_token = client.login(admin_email, admin_password)
        if admin_token:
            try:
                r = requests.post(
                    f"{client.base}/api/admin/trigger-aggregations?days={days}",
                    headers={"Authorization": f"Bearer {admin_token}"},
                    timeout=30,
                )
                if r.status_code == 200:
                    log.info("✅ Aggregations triggered successfully")
                else:
                    log.warning("⚠️  Aggregation trigger returned %s: %s", r.status_code, r.text)
            except Exception as e:
                log.warning("⚠️  Could not reach aggregation endpoint: %s", e)
        else:
            log.warning("⚠️  Admin login failed — aggregations not triggered")
    else:
        log.info("No admin credentials supplied — skipping auto-aggregation")


# ── Live loop ─────────────────────────────────────────────────────────────────

def _live_task(args: tuple) -> bool:
    base_url, token, device_id, appliance_key, profile, now, interval_min = args
    client  = WattWiseClient(base_url)
    session = client._session()
    reading = generate_reading(appliance_key, now, profile, interval_min)
    return client.post_reading(token, device_id, reading, session=session)


def live_loop(client: WattWiseClient, sessions: list[dict],
              interval_sec: int, max_cycles: int = 0):
    log.info("Starting live loop — interval=%ds", interval_sec)
    cycle = 0

    while True:
        cycle += 1
        now = datetime.now(timezone.utc)
        log.info("── Cycle %d @ %s UTC ──", cycle, now.strftime("%Y-%m-%d %H:%M"))

        # Refresh tokens periodically (JWTs expire after 1 day now)
        for sess in sessions:
            if cycle % 300 == 0:
                new_token = client.login(sess["email"], sess["password"])
                if new_token:
                    sess["token"] = new_token

        tasks = [
            (client.base, sess["token"], dev["id"],
             dev.get("appliance_key", ""), sess["profile"],
             now, interval_sec / 60)
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

        log.info("Cycle %d done — sent=%d failed=%d | sleep=%ds",
                 cycle, sent, failed, interval_sec)

        if max_cycles > 0 and cycle >= max_cycles:
            log.info("Reached max_cycles=%d. Exiting.", max_cycles)
            return
        time.sleep(interval_sec)


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="WattWise dummy data sender v2")
    parser.add_argument("--url",             default=DEFAULT_BASE_URL)
    parser.add_argument("--no-backfill",     action="store_true")
    parser.add_argument("--backfill-days",   type=int, default=BACKFILL_DAYS)
    parser.add_argument("--interval",        type=int, default=SEND_INTERVAL_SEC)
    parser.add_argument("--live-cycles",     type=int, default=0)
    parser.add_argument("--admin-email",     default=os.getenv("ADMIN_EMAIL", ""))
    parser.add_argument("--admin-password",  default=os.getenv("ADMIN_PASSWORD", ""))
    parser.add_argument("--csv",
        default="wattwise_cardiff_participants_20260403-105251.csv")
    args = parser.parse_args()

    if args.interval <= 0:
        log.error("--interval must be > 0")
        sys.exit(2)

    log.info("WattWise Dummy Data Sender v2  |  API: %s", args.url)
    log.info("Household profiles loaded: %d", len(HOUSEHOLD_PROFILES))
    for i, p in enumerate(HOUSEHOLD_PROFILES):
        log.info("  [%2d] %-32s  factor=%.2f  wake=%02d:00  sleep=%02d:00  peak_avoid=%.0f%%",
                 i + 1, p.name, p.base_factor, p.wake_hour, p.sleep_hour,
                 p.peak_avoidance * 100)

    global DUMMY_ACCOUNTS
    DUMMY_ACCOUNTS = load_dummy_accounts(args.csv)
    if not DUMMY_ACCOUNTS:
        log.error("No accounts loaded from: %s", args.csv)
        sys.exit(1)

    client   = WattWiseClient(args.url)
    sessions = build_sessions(client)

    if not sessions:
        log.error("No sessions built — check server is up and accounts exist")
        sys.exit(1)

    if not args.no_backfill:
        backfill(client, sessions, args.backfill_days,
                 args.admin_email or None, args.admin_password or None)

    live_loop(client, sessions, args.interval, max_cycles=args.live_cycles)


if __name__ == "__main__":
    main()
