#!/usr/bin/env python3
"""Generate synthetic community energy data for Cardiff participants."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib import error, request

SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
BACKEND_ROOT = SCRIPT_PATH.parents[1] / "backend"

if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.synthetic_data import (  # noqa: E402
    DEVICE_CATALOGUE,
    build_row_seed,
    generate_appliance_reading,
    household_factor,
    iter_timestamps,
    parse_cardiff_participants_csv,
    planned_device_keys,
)


DEFAULT_PARTICIPANTS_CSV = REPO_ROOT / "wattwise_cardiff_participants_20260403-105251.csv"
DEFAULT_OUTPUT_DIR = REPO_ROOT / "Server Side" / "backups"


class WattWiseApiClient:
    def __init__(self, base_url: str, timeout_seconds: int = 15):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _request(self, method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, Any]:
        payload = None if body is None else json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        req = request.Request(
            f"{self.base_url}{path}",
            data=payload,
            headers=headers,
            method=method,
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                return response.status, json.loads(raw) if raw else None
        except error.HTTPError as exc:
            raw = exc.read().decode("utf-8") if exc.fp else ""
            parsed = raw
            if raw:
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    parsed = raw
            return exc.code, parsed

    def login(self, email: str, password: str) -> tuple[str | None, int | None]:
        status, data = self._request(
            "POST",
            "/api/auth/login",
            {"email": email, "password": password},
        )
        if status != 200 or not isinstance(data, dict):
            return None, status
        return data.get("access_token"), status

    def list_homes(self, token: str) -> list[dict]:
        status, data = self._request("GET", "/api/homes", token=token)
        if status != 200 or not isinstance(data, list):
            return []
        return data

    def list_devices(self, token: str, home_id: int) -> list[dict]:
        status, data = self._request("GET", f"/api/homes/{home_id}/devices", token=token)
        if status != 200 or not isinstance(data, list):
            return []
        return data

    def submit_reading(self, token: str, payload: dict) -> tuple[bool, int | None]:
        status, _ = self._request("POST", "/api/readings/", payload, token=token)
        return status == 201, status


def default_output_path(output_dir: Path) -> Path:
    timestamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    return output_dir / f"cardiff_synthetic_readings_{timestamp}.csv"


def participant_rows(args: argparse.Namespace) -> list[dict]:
    rows = parse_cardiff_participants_csv(args.participants_csv)
    if args.participant_limit > 0:
        rows = rows[: args.participant_limit]
    return rows


def resolve_live_devices(client: WattWiseApiClient, participant: dict) -> tuple[str | None, list[dict]]:
    token, _ = client.login(participant["email"], participant["password"])
    if not token:
        return None, []

    homes = client.list_homes(token)
    if not homes:
        return token, []

    preferred_home_id = participant.get("home_id") or 0
    home = next((item for item in homes if item.get("id") == preferred_home_id), homes[0])
    return token, client.list_devices(token, int(home["id"]))


def planned_devices(participant: dict) -> list[dict]:
    devices = []
    for device_key in planned_device_keys(participant["device_count"], participant["participant_index"]):
        device = DEVICE_CATALOGUE[device_key].copy()
        device["id"] = None
        devices.append(device)
    return devices


def build_export_rows(args: argparse.Namespace, client: WattWiseApiClient | None = None) -> list[dict]:
    participants = participant_rows(args)
    end_at = datetime.utcnow().replace(second=0, microsecond=0)
    start_at = end_at - timedelta(days=args.days)
    rows: list[dict] = []

    for participant in participants:
        factor = household_factor(
            participant["occupants"],
            participant["home_type"],
            participant["participant_index"],
        )

        devices: list[dict]
        live_mode = bool(client and args.resolve_live_devices)
        if live_mode:
            _, devices = resolve_live_devices(client, participant)
        else:
            devices = planned_devices(participant)

        for device in devices:
            appliance_key = device.get("appliance_key") or device.get("entity_id") or "unknown"
            participant_key = participant["email"] or str(participant["number"])

            for recorded_at in iter_timestamps(start_at, end_at, args.interval_minutes):
                row_rng = __import__("random").Random(
                    build_row_seed(args.seed, participant_key, appliance_key, recorded_at)
                )
                reading = generate_appliance_reading(
                    appliance_key,
                    recorded_at,
                    factor=factor,
                    interval_minutes=args.interval_minutes,
                    rng=row_rng,
                )
                rows.append(
                    {
                        "participant_number": participant["number"],
                        "email": participant["email"],
                        "home_id": participant["home_id"],
                        "device_id": device.get("id") or "",
                        "device_name": device.get("name") or "",
                        "appliance_key": appliance_key,
                        "entity_id": device.get("entity_id") or "",
                        "recorded_at": recorded_at.isoformat(),
                        "power_watts": reading["power_watts"],
                        "current_amps": reading["current_amps"],
                        "voltage_volts": reading["voltage_volts"],
                        "energy_kwh": reading["energy_kwh"],
                        "switch_state": reading["switch_state"],
                        "household_factor": factor,
                        "device_source": "live" if live_mode else "planned",
                    }
                )

    return rows


def export_csv(args: argparse.Namespace) -> int:
    client = WattWiseApiClient(args.base_url) if args.base_url and args.resolve_live_devices else None
    rows = build_export_rows(args, client=client)
    output_path = Path(args.output_csv) if args.output_csv else default_output_path(DEFAULT_OUTPUT_DIR)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        print("No rows generated.")
        return 1

    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"Exported {len(rows)} synthetic readings to {output_path}")
    return 0


def post_readings(args: argparse.Namespace) -> int:
    if not args.base_url:
        raise SystemExit("--base-url is required for post mode")

    client = WattWiseApiClient(args.base_url)
    participants = participant_rows(args)
    end_at = datetime.utcnow().replace(second=0, microsecond=0)
    start_at = end_at - timedelta(days=args.days)

    sent = 0
    failed = 0

    for participant in participants:
        factor = household_factor(
            participant["occupants"],
            participant["home_type"],
            participant["participant_index"],
        )
        token, devices = resolve_live_devices(client, participant)
        if not token or not devices:
            failed += 1
            print(f"Skipping {participant['email']} (login/devices unavailable)")
            continue

        participant_key = participant["email"] or str(participant["number"])
        for device in devices:
            appliance_key = device.get("appliance_key") or "unknown"
            device_id = device.get("id")
            if not device_id:
                continue

            for recorded_at in iter_timestamps(start_at, end_at, args.interval_minutes):
                row_rng = __import__("random").Random(
                    build_row_seed(args.seed, participant_key, appliance_key, recorded_at)
                )
                reading = generate_appliance_reading(
                    appliance_key,
                    recorded_at,
                    factor=factor,
                    interval_minutes=args.interval_minutes,
                    rng=row_rng,
                )
                ok, status = client.submit_reading(
                    token,
                    {
                        "device_id": device_id,
                        "recorded_at": recorded_at.isoformat(),
                        **reading,
                    },
                )
                if ok:
                    sent += 1
                else:
                    failed += 1
                    print(
                        f"Failed reading post for {participant['email']} / {appliance_key} "
                        f"at {recorded_at.isoformat()} (status={status})"
                    )

    print(f"Posted {sent} readings, {failed} failed")
    return 0 if failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("export", "post"), default="export")
    parser.add_argument("--participants-csv", default=str(DEFAULT_PARTICIPANTS_CSV))
    parser.add_argument("--base-url", default="")
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--interval-minutes", type=int, default=30)
    parser.add_argument("--participant-limit", type=int, default=0)
    parser.add_argument("--seed", type=int, default=20260414)
    parser.add_argument("--output-csv", default="")
    parser.add_argument(
        "--resolve-live-devices",
        action="store_true",
        help="In export mode, login and use actual device IDs/metadata instead of planned device templates.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.mode == "export":
        return export_csv(args)
    return post_readings(args)


if __name__ == "__main__":
    raise SystemExit(main())