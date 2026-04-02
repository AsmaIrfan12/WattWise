#!/usr/bin/env python3
"""End-to-end UAT verifier for WattWise core user/admin flows."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

import requests


def check(name: str, ok: bool, detail: str, checks: list[dict]) -> None:
    checks.append({"name": name, "ok": ok, "detail": detail})
    prefix = "[PASS]" if ok else "[FAIL]"
    print(f"{prefix} {name}: {detail}")


def login(base_url: str, email: str, password: str, timeout: int) -> dict:
    r = requests.post(
        f"{base_url}/api/auth/login",
        json={"email": email, "password": password},
        timeout=timeout,
    )
    if r.status_code != 200:
        raise RuntimeError(f"login failed ({r.status_code}): {r.text}")
    return r.json()


def main() -> int:
    parser = argparse.ArgumentParser(description="WattWise UAT verifier")
    parser.add_argument("--api-base", default="http://localhost:8000")
    parser.add_argument("--admin-url", default="http://localhost:3000")
    parser.add_argument("--user-url", default="http://localhost:3001")
    parser.add_argument("--admin-email", default="admin@wattwise.co.uk")
    parser.add_argument("--admin-password", default="admin")
    parser.add_argument("--user-email", default="liam.jenkins@wattwise-test.co.uk")
    parser.add_argument("--user-password", default="WattTest2024!")
    parser.add_argument("--timeout", type=int, default=8)
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    checks: list[dict] = []

    # 1) Public health checks
    try:
        h = requests.get(f"{args.api_base}/health", timeout=args.timeout)
        check("api_health", h.status_code == 200 and h.json().get("status") == "ok", f"status={h.status_code}", checks)
    except Exception as exc:
        check("api_health", False, str(exc), checks)

    try:
        dep = requests.get(f"{args.api_base}/health/dependencies", timeout=args.timeout)
        payload = dep.json() if dep.status_code == 200 else {}
        check("api_dependencies", dep.status_code == 200 and payload.get("status") == "ok", f"status={dep.status_code}", checks)
    except Exception as exc:
        check("api_dependencies", False, str(exc), checks)

    # 2) Frontend availability
    for name, url in (("admin_frontend", args.admin_url), ("user_frontend", args.user_url)):
        try:
            r = requests.get(url, timeout=args.timeout)
            check(name, r.status_code == 200, f"status={r.status_code}", checks)
        except Exception as exc:
            check(name, False, str(exc), checks)

    # 3) Admin flow
    admin_token = ""
    try:
        admin = login(args.api_base, args.admin_email, args.admin_password, args.timeout)
        admin_token = admin["access_token"]
        check("admin_login", True, f"user_id={admin.get('user_id')}", checks)
    except Exception as exc:
        check("admin_login", False, str(exc), checks)

    if admin_token:
        try:
            r = requests.get(
                f"{args.api_base}/api/admin/dashboard",
                headers={"Authorization": f"Bearer {admin_token}"},
                timeout=args.timeout,
            )
            ok = r.status_code == 200 and "total_users" in r.json()
            check("admin_dashboard", ok, f"status={r.status_code}", checks)
        except Exception as exc:
            check("admin_dashboard", False, str(exc), checks)

    # 4) User flow + ingestion
    user_token = ""
    home_id = None
    device_id = None

    try:
        user = login(args.api_base, args.user_email, args.user_password, args.timeout)
        user_token = user["access_token"]
        check("user_login", True, f"user_id={user.get('user_id')}", checks)
    except Exception as exc:
        check("user_login", False, str(exc), checks)

    if user_token:
        headers = {"Authorization": f"Bearer {user_token}"}
        try:
            homes = requests.get(f"{args.api_base}/api/homes", headers=headers, timeout=args.timeout)
            homes_payload = homes.json() if homes.status_code == 200 else []
            ok = homes.status_code == 200 and len(homes_payload) > 0
            if ok:
                home_id = homes_payload[0]["id"]
            check("user_homes", ok, f"status={homes.status_code} count={len(homes_payload)}", checks)
        except Exception as exc:
            check("user_homes", False, str(exc), checks)

    if user_token and home_id:
        headers = {"Authorization": f"Bearer {user_token}"}
        try:
            devices = requests.get(
                f"{args.api_base}/api/homes/{home_id}/devices",
                headers=headers,
                timeout=args.timeout,
            )
            devices_payload = devices.json() if devices.status_code == 200 else []
            ok = devices.status_code == 200 and len(devices_payload) > 0
            if ok:
                device_id = devices_payload[0]["id"]
            check("user_devices", ok, f"status={devices.status_code} count={len(devices_payload)}", checks)
        except Exception as exc:
            check("user_devices", False, str(exc), checks)

    if user_token and device_id:
        headers = {"Authorization": f"Bearer {user_token}"}
        try:
            reading = {
                "device_id": device_id,
                "power_watts": 123.45,
                "current_amps": 0.54,
                "voltage_volts": 230.1,
                "energy_kwh": 0.01,
                "switch_state": "on",
                "recorded_at": datetime.utcnow().isoformat(),
            }
            r = requests.post(f"{args.api_base}/api/readings/", headers=headers, json=reading, timeout=args.timeout)
            check("reading_ingest", r.status_code == 201, f"status={r.status_code}", checks)
        except Exception as exc:
            check("reading_ingest", False, str(exc), checks)

    if user_token and home_id:
        headers = {"Authorization": f"Bearer {user_token}"}
        try:
            r = requests.get(
                f"{args.api_base}/api/readings/home/{home_id}/today",
                headers=headers,
                timeout=args.timeout,
            )
            ok = r.status_code == 200 and "total_kwh" in r.json()
            check("home_today_summary", ok, f"status={r.status_code}", checks)
        except Exception as exc:
            check("home_today_summary", False, str(exc), checks)

    failed = [c for c in checks if not c["ok"]]
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "api_base": args.api_base,
        "checks_total": len(checks),
        "checks_failed": len(failed),
        "checks": checks,
        "status": "PASS" if not failed else "FAIL",
    }

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

    print("\nUAT RESULT:", report["status"], f"({report['checks_total'] - report['checks_failed']}/{report['checks_total']})")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
