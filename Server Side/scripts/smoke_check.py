#!/usr/bin/env python3
"""Post-deploy smoke checks for WattWise services."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _get_json(url: str, timeout: int) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned status {response.status}")
        raw = response.read().decode("utf-8")
        return json.loads(raw)


def _check_status_code(url: str, timeout: int) -> None:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned status {response.status}")


def main() -> int:
    parser = argparse.ArgumentParser(description="WattWise post-deploy smoke checks")
    parser.add_argument("--api-base", default="http://localhost:8000")
    parser.add_argument("--admin-url", default="http://localhost:3000")
    parser.add_argument("--user-url", default="http://localhost:3001")
    parser.add_argument("--timeout", type=int, default=5)
    parser.add_argument("--require-slo-ok", action="store_true")
    args = parser.parse_args()

    checks = [
        ("api_health", lambda: _get_json(f"{args.api_base}/health", args.timeout)),
        ("api_dependencies", lambda: _get_json(f"{args.api_base}/health/dependencies", args.timeout)),
        ("api_slo", lambda: _get_json(f"{args.api_base}/health/slo", args.timeout)),
        ("admin_frontend", lambda: _check_status_code(args.admin_url, args.timeout)),
        ("user_frontend", lambda: _check_status_code(args.user_url, args.timeout)),
    ]

    failures: list[str] = []

    for name, fn in checks:
        try:
            result = fn()
            if name == "api_health" and result.get("status") != "ok":
                failures.append("api /health status is not ok")
            elif name == "api_dependencies" and result.get("status") != "ok":
                failures.append("api /health/dependencies status is not ok")
            elif name == "api_slo" and result.get("status") != "ok":
                if args.require_slo_ok:
                    breaches = result.get("breaches", {})
                    if breaches.get("errors", False):
                        failures.append("api /health/slo reports 5xx error-rate breach")
                    else:
                        print("[WARN] api_slo non-error breach detected (continuing)")
                else:
                    print("[WARN] api_slo indicates breach (continuing)")
            print(f"[OK] {name}")
        except (urllib.error.URLError, RuntimeError, json.JSONDecodeError) as exc:
            failures.append(f"{name} failed: {exc}")
            print(f"[FAIL] {name}: {exc}")

    if failures:
        print("\nSmoke checks failed:")
        for failure in failures:
            print(f" - {failure}")
        return 1

    print("\nAll smoke checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
