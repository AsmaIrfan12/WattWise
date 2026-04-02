"""
CSV Import Script
==================
Imports historical CSV files from the Sensing layer output/ folder
into the MySQL database via the backend's bulk API.

Usage — import all CSVs from Sensing layer:
    python import_csv.py --folder "../../Sensing layer/output" --device-id 00000000db5b17e8

Usage — import CSVs to the test device table:
    python import_csv.py --folder "../../Sensing layer/output" --device-id a4f19c7e2b8d6a31

Usage — single file:
    python import_csv.py --folder "../../Sensing layer/output" --device-id 00000000db5b17e8 --file 20260306-Output_00000000db5b17e8.csv

It reads each YYYYMMDD-Output_*.csv file and POSTs rows in batches.
"""

import argparse
import csv
import os
import sys
from datetime import datetime

import requests

BATCH_SIZE = 5000


def parse_csv_row(row_text: str, device_id: str) -> dict | None:
    """Parse a single CSV data row (not header/unit rows)."""
    parts = row_text.strip().split(",")
    if len(parts) < 8:
        return None

    try:
        dt = datetime.strptime(parts[0], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    try:
        return {
            "device_id": device_id,
            "recorded_at": dt.isoformat(),
            "pm1": float(parts[2]) if parts[2] else None,
            "pm25": float(parts[3]) if parts[3] else None,
            "pm10": float(parts[4]) if parts[4] else None,
            "co2": float(parts[5]) if parts[5] else None,
            "temperature": float(parts[6]) if parts[6] else None,
            "humidity": float(parts[7]) if parts[7] else None,
        }
    except (ValueError, IndexError):
        return None


def import_file(filepath: str, device_id: str, api_url: str) -> int:
    """Import one CSV file, return count of rows sent."""
    batch = []
    total = 0

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("datetime") or line.startswith(",,"):
                continue
            row = parse_csv_row(line, device_id)
            if row:
                batch.append(row)

            if len(batch) >= BATCH_SIZE:
                resp = requests.post(f"{api_url}/api/readings/bulk", json=batch, timeout=120)
                if resp.status_code == 201:
                    total += resp.json().get("inserted", 0)
                else:
                    print(f"  ERROR: {resp.status_code} — {resp.text[:200]}")
                batch = []

    # Remaining batch
    if batch:
        resp = requests.post(f"{api_url}/api/readings/bulk", json=batch, timeout=120)
        if resp.status_code == 201:
            total += resp.json().get("inserted", 0)
        else:
            print(f"  ERROR: {resp.status_code} — {resp.text[:200]}")

    return total


def ensure_device(api_url: str, device_id: str, home_name: str = None,
                  lat: float = None, lng: float = None):
    """Register the device if it doesn't exist yet."""
    resp = requests.get(f"{api_url}/api/homes/{device_id}", timeout=10)
    if resp.status_code == 200:
        print(f"Device {device_id} already registered.")
        return True

    name = home_name or f"Home-{device_id[-8:]}"
    payload = {"device_id": device_id, "home_name": name}
    if lat is not None:
        payload["latitude"] = lat
    if lng is not None:
        payload["longitude"] = lng

    print(f"Registering device {device_id} as '{name}'...")
    resp = requests.post(f"{api_url}/api/homes/", json=payload, timeout=10)
    if resp.status_code == 201:
        print(f"  Registered — table readings_{device_id} created.")
        return True
    else:
        print(f"  Failed to register: {resp.status_code} — {resp.text[:200]}")
        return False


def trigger_analysis(api_url: str, device_id: str):
    """Trigger a mould risk assessment so dashboards show data immediately."""
    print(f"\nTriggering mould analysis for {device_id}...")
    try:
        resp = requests.post(f"{api_url}/api/analysis/{device_id}/mould-risk?hours=720", timeout=60)
        if resp.status_code == 200:
            data = resp.json()
            print(f"  Risk Score: {data.get('risk_score', '?')} — {data.get('risk_level', '?')}")
        else:
            print(f"  Analysis returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"  Analysis request failed: {e}")


def main():
    parser = argparse.ArgumentParser(description="Import sensor CSV files into IAA database")
    parser.add_argument("--folder", required=True, help="Path to output/ folder with CSV files")
    parser.add_argument("--device-id", required=True, help="Target device ID (e.g. 00000000db5b17e8)")
    parser.add_argument("--api", default="http://localhost:8000", help="Backend API base URL")
    parser.add_argument("--file", default=None, help="Import a single file only")
    parser.add_argument("--home-name", default=None, help="Home name for new device registration")
    parser.add_argument("--lat", type=float, default=None, help="Latitude for device location")
    parser.add_argument("--lng", type=float, default=None, help="Longitude for device location")
    parser.add_argument("--skip-analysis", action="store_true", help="Skip post-import mould analysis")
    args = parser.parse_args()

    print("=" * 56)
    print("  IAA CSV Import Tool")
    print("=" * 56)
    print(f"  Device ID : {args.device_id}")
    print(f"  Folder    : {os.path.abspath(args.folder)}")
    print(f"  API       : {args.api}")
    print("=" * 56)
    print()

    # Ensure the device is registered
    if not ensure_device(args.api, args.device_id, args.home_name,
                         args.lat, args.lng):
        sys.exit(1)

    if args.file:
        filepath = os.path.join(args.folder, args.file)
        if not os.path.isfile(filepath):
            print(f"File not found: {filepath}")
            sys.exit(1)
        print(f"\nImporting {filepath} ...")
        count = import_file(filepath, args.device_id, args.api)
        print(f"  Imported {count} rows")
        grand_total = count
    else:
        # Import all CSV files sorted by date
        files = sorted([
            f for f in os.listdir(args.folder)
            if f.endswith(".csv") and f[0].isdigit()
        ])
        print(f"\nFound {len(files)} CSV files to import\n")
        grand_total = 0
        for i, fname in enumerate(files, 1):
            filepath = os.path.join(args.folder, fname)
            print(f"  [{i:3d}/{len(files)}] {fname} ...", end=" ", flush=True)
            count = import_file(filepath, args.device_id, args.api)
            print(f"{count:,} rows")
            grand_total += count

        # Also import send_this.csv if it exists
        send_file = os.path.join(args.folder, "send_this.csv")
        if os.path.isfile(send_file):
            print(f"  [extra] send_this.csv ...", end=" ", flush=True)
            count = import_file(send_file, args.device_id, args.api)
            print(f"{count:,} rows")
            grand_total += count

    print(f"\n{'=' * 56}")
    print(f"  Total imported: {grand_total:,} rows")
    print(f"{'=' * 56}")

    # Trigger mould analysis so dashboards have data right away
    if not args.skip_analysis and grand_total > 0:
        trigger_analysis(args.api, args.device_id)

    print(f"\n  Check the dashboards:")
    print(f"  • User app : http://localhost:3001")
    print(f"  • Admin    : http://localhost:3000")
    print(f"  • API docs : http://localhost:8000/docs")


if __name__ == "__main__":
    main()
