# WattWise Setup Guide (Production + Research Operations)

Version: 2026-03-30
Project: WattWise (Cardiff University PhD Platform)
Primary Production URL: https://www.talk2futurebuildings.systems
API Docs: https://www.talk2futurebuildings.systems/docs

---

## 1. What This Guide Covers

This guide is the source of truth for setting up, running, validating, and operating the full WattWise system after the latest reliability and authentication improvements.

It covers:
- Fresh server bring-up with Docker Compose.
- Existing deployment updates (safe rebuild and restart flow).
- Authentication behavior for API, web dashboard, and Android WebView.
- Raspberry Pi publisher onboarding for single and multiple homes.
- Admin operations and troubleshooting.

---

## Runbook Index (Fast Path)

Use this section when you are handling an incident and need the shortest route to the right procedure.

| Incident / Task | Go To | Outcome |
|---|---|---|
| First-time environment bring-up | [Section 5](#5-fresh-deployment-server) | Full stack starts and health endpoint returns ok |
| Code deployed but UI/API looks stale | [Section 6](#6-update-existing-deployment-safely) | Services rebuilt, recreated, and parity revalidated |
| Login or token issues across web/mobile | [Section 7](#7-authentication-model-final-working-state) | Confirm final auth behavior and token handoff model |
| Admin account cannot sign in | [Section 8](#8-admin-bootstrap-and-seed-account) | Admin seed email and DB alignment corrected |
| New home onboarding | [Section 9](#9-household-onboarding-single-home) | User, home, and devices provisioned correctly |
| Scaling to multiple homes | [Section 10](#10-multi-home-scaling-workflow) | Standardized multi-home rollout and data quality |
| Raspberry Pi publisher not sending data | [Section 11](#11-raspberry-pi-publisher-setup) | Publisher install/test/service verification completed |
| Need release confidence after deploy | [Section 12](#12-verification-checklist-post-deploy) | Post-deploy checks completed end-to-end |
| Scheduler or analytics timing concerns | [Section 13](#13-key-scheduled-jobs) | Confirm expected job coverage and cadence |
| Active production troubleshooting | [Section 14](#14-troubleshooting-quick-reference) | Fast diagnosis for common failure modes |
| Hardening and production safety review | [Section 15](#15-security-and-production-notes) | Baseline security posture confirmed |
| Daily/weekly operational routine | [Section 16](#16-recommended-operational-routine) | Ongoing operations rhythm standardized |

Escalation path when unresolved after first pass:
1. Repeat [Section 12](#12-verification-checklist-post-deploy) in order.
2. Recheck container/runtime parity from [Section 6](#6-update-existing-deployment-safely).
3. Use [Section 14](#14-troubleshooting-quick-reference) and compare backend plus publisher logs.

---

## 2. Current Working Architecture

WattWise runs across three layers:

1. Sensing Layer (home)
- Tapo P110 devices report to Home Assistant.
- Home Assistant writes to local InfluxDB.
- Raspberry Pi publisher sends normalized readings to cloud MQTT.

2. Cloud Platform
- Cloudflare terminates TLS and forwards traffic to Nginx.
- Nginx routes API, MQTT WebSocket, and dashboards.
- FastAPI backend handles auth, homes, devices, readings, goals, notifications, rankings, and exports.
- MySQL stores relational research and product data.
- InfluxDB stores high-resolution time-series telemetry.

3. User Layer
- Android app authenticates users and displays dashboard in WebView.
- User dashboard is served by Nginx static site container.
- Admin dashboard is served separately for owner/research workflows.

### Core Data Flow

Tapo plugs -> Home Assistant -> local InfluxDB -> RPi publisher -> MQTT WebSocket (/mqtt) -> FastAPI MQTT consumer -> MySQL + InfluxDB -> API + notifications + dashboards.

---

## 3. Service Map and Ports

From Server Side/docker-compose.yml:

- mosquitto
  - 1883 (MQTT)
  - 9001 (WebSocket MQTT)
- mysql
  - host 3307 -> container 3306
- influxdb
  - host 8086
- backend
  - host 8000
- admin-dashboard
  - host 3000
- user-dashboard
  - host 3001
- nginx-proxy
  - host 80 and 443

Production users normally access the platform through:
- https://www.talk2futurebuildings.systems/
- https://www.talk2futurebuildings.systems/api/*
- https://www.talk2futurebuildings.systems/mqtt (WebSocket endpoint)

---

## 4. Prerequisites

Server host requirements:
- Docker Engine + Docker Compose plugin.
- Working Cloudflare tunnel mapping public HTTPS to local Nginx (port 80 upstream).
- Correct Server Side/.env values for MySQL, InfluxDB, JWT secret, and app settings.

Android requirements:
- Android Studio (for local builds).
- JDK configured (JAVA_HOME) if you run Gradle locally.

Raspberry Pi / Home Assistant requirements:
- Python 3.
- Access to local HA InfluxDB (homeassistant database).
- Network reachability to production MQTT endpoint.

---

## 5. Fresh Deployment (Server)

Run from the Server Side directory.

```bash
cd "Server Side"
docker compose up -d --build
```

Check service state:

```bash
docker compose ps
```

Check backend health:

```bash
curl https://www.talk2futurebuildings.systems/health
```

Expected response:

```json
{"status":"ok"}
```

---

## 6. Update Existing Deployment Safely

Use this flow when code has changed and containers must be refreshed.

1. Rebuild and restart only changed services:

```bash
cd "Server Side"
docker compose build backend user-dashboard admin-dashboard nginx-proxy
docker compose up -d --force-recreate backend user-dashboard admin-dashboard nginx-proxy
```

2. Confirm running state:

```bash
docker compose ps
```

3. Verify backend auth routes are active:

- GET /api/auth/me
- POST /api/auth/push-token
- POST /api/auth/logout

4. Verify dashboard static asset parity after rebuild (important):

```powershell
$src='C:\path\to\WattWise\Server Side\user-frontend\static\index.html'
$srcHash=(Get-FileHash -Algorithm SHA256 $src).Hash.ToLower()
Set-Location 'C:\path\to\WattWise\Server Side'
$cid=(docker compose ps -q user-dashboard)
$ctrHash=(docker exec $cid sh -lc "sha256sum /usr/share/nginx/html/index.html | cut -d ' ' -f1").Trim().ToLower()
"SOURCE=$srcHash"
"CONTAINER=$ctrHash"
if($srcHash -eq $ctrHash){'PARITY=YES'} else {'PARITY=NO'}
```

A successful update should return PARITY=YES.

---

## 7. Authentication Model (Final Working State)

### 7.1 API Auth

- JWT bearer token is required for protected routes.
- Login endpoint applies rate limiting.
- Implemented and working endpoints:
  - POST /api/auth/signup
  - POST /api/auth/login
  - GET /api/auth/me
  - POST /api/auth/push-token
  - POST /api/auth/logout

### 7.2 User Web Dashboard Auth

User dashboard now supports two entry paths:

1. Direct web login
- Overlay prompts for email/password.
- On success token is stored in localStorage key ww_token.

2. Android token bootstrap
- Android app appends JWT as URL fragment: #ww_token=...
- Dashboard reads fragment, stores ww_token, then removes fragment from URL.
- URL fragment is client-side only and not sent to server.

### 7.3 Android-WebView Bridge

- MainViewModel generates webUrl from base URL + token fragment.
- MainScreen loads webUrl into WebView.
- This ensures a signed-in Android user can open dashboard without re-entering credentials.

### 7.4 Logout Behavior

- Frontend clears local token and returns to sign-in overlay.
- API logout is stateless success response (JWT remains stateless by design).

---

## 8. Admin Bootstrap and Seed Account

Default SQL seed now uses:
- admin@wattwise.co.uk

If your database was initialized before this change, update existing admin email manually:

```sql
UPDATE users
SET email = 'admin@wattwise.co.uk'
WHERE is_admin = 1;
```

Run inside MySQL container if needed:

```bash
docker exec -it wattwise-mysql mysql -u root -p
```

---

## 9. Household Onboarding (Single Home)

### 9.1 Create User Account

```bash
curl -X POST https://www.talk2futurebuildings.systems/api/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"name":"Home User","email":"home.user@example.com","password":"SecurePass123!"}'
```

### 9.2 Login and Capture Token

```bash
curl -X POST https://www.talk2futurebuildings.systems/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"home.user@example.com","password":"SecurePass123!"}'
```

Store access_token from response for subsequent calls.

### 9.3 Create Home

```bash
curl -X POST https://www.talk2futurebuildings.systems/api/homes \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"home_name":"Home A","address":"Cardiff","num_occupants":3,"home_type":"terraced"}'
```

### 9.4 Register Devices

Register each appliance with correct HA entity IDs.

```bash
curl -X POST https://www.talk2futurebuildings.systems/api/homes/<HOME_ID>/devices \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "name":"Kettle",
    "appliance_key":"kettle",
    "entity_id":"sensor.tapo_p110_kettle_current_consumption",
    "power_entity_id":"sensor.tapo_p110_kettle_current_consumption",
    "switch_entity_id":"switch.tapo_p110_kettle",
    "device_type":"appliance",
    "rated_wattage":3000,
    "location":"Kitchen"
  }'
```

---

## 10. Multi-Home Scaling Workflow

Repeat this sequence per home:

1. Create user account.
2. Create home record.
3. Register all mapped devices.
4. Deploy/update publisher config on that home's Raspberry Pi with correct home.id and entity IDs.
5. Validate MQTT ingestion for that home.
6. Validate dashboard data and rankings.

Recommended governance for research quality:
- Keep a strict mapping sheet: user_email, home_id, entity_id, appliance_key.
- Use consistent naming conventions for location and appliance keys.
- Perform a 24-hour data completeness check after each onboarding.

---

## 11. Raspberry Pi Publisher Setup

From Sensing Layer/ files:
- rpi_mqtt_publisher.py
- rpi_publisher_config.yaml
- wattwise-publisher.service

Install dependencies (on RPi):

```bash
pip3 install paho-mqtt influxdb pyyaml
```

Run test manually:

```bash
python3 rpi_mqtt_publisher.py --config /etc/wattwise/publisher.yaml
```

Install service:

```bash
sudo bash install_publisher.sh
sudo systemctl enable wattwise-publisher
sudo systemctl start wattwise-publisher
```

Check logs:

```bash
journalctl -u wattwise-publisher -f
tail -f /var/log/wattwise-publisher.log
```

---

## 12. Verification Checklist (Post-Deploy)

Run these after every major change.

### 12.1 Infrastructure

- docker compose ps shows all core services running.
- backend health endpoint returns ok.
- nginx routes /api, /mqtt, and / to expected services.

### 12.2 Authentication

- signup returns token.
- login returns token with 200.
- auth/me returns current user with bearer token.
- auth/push-token returns success.
- auth/logout returns success.

### 12.3 Web + Android

- Web dashboard allows login via overlay.
- Android app opens WebView and dashboard is authenticated through token fragment bootstrap.
- Logout clears local session and requires login again.

### 12.4 Data Path

- MQTT messages are received by backend subscriber.
- New readings appear in MySQL energy_readings.
- Time-series is written to InfluxDB.
- Dashboard updates for today usage and device cards.

---

## 13. Key Scheduled Jobs

Backend scheduler runs automated research and product jobs, including:
- Hourly aggregation.
- Daily aggregation.
- Goal checks.
- Peak reminders.
- Daily reports.
- Decision impact calculations.
- Rankings calculation.
- Weekly email reports.

Operational note:
- If scheduler behavior appears incorrect, check backend logs and server time zone assumptions first.

---

## 14. Troubleshooting Quick Reference

### Problem: login fails with 401

Check:
- Correct email/password.
- Account exists in MySQL users table.
- No stale frontend token in localStorage.

### Problem: dashboard still shows old UI after deploy

Check:
- user-dashboard rebuilt and recreated.
- container file hash matches source file hash (parity check in section 6).

### Problem: /api/auth/me returns 401

Check:
- Authorization header format is exactly Bearer <token>.
- Token not expired.
- SECRET_KEY unchanged since token issuance.

### Problem: no incoming energy data

Check:
- Raspberry Pi publisher is running.
- MQTT credentials and /mqtt websocket path are correct.
- Home Assistant entity IDs exactly match device registration.

### Problem: Android WebView opens unauthenticated

Check:
- App has valid token in TokenDataStore.
- MainScreen is loading webUrl, not fullUrl.
- Dashboard bootstrapTokenFromFragment logic exists in deployed container content.

---

## 15. Security and Production Notes

- Keep strong, non-placeholder JWT secret in Server Side/.env.
- Rotate admin credentials before public demos.
- Restrict admin portal exposure at network layer.
- Keep backup snapshots of MySQL and InfluxDB volumes.
- Avoid using debug SSL bypass in Android production builds.

---

## 16. Recommended Operational Routine

Daily:
- Check docker compose ps.
- Check backend and publisher logs for errors.
- Spot-check one household dashboard.

Weekly:
- Validate scheduler outputs.
- Audit notification success and failed pushes.
- Review ranking consistency and decision impact records.

Before each field onboarding:
- Validate APIs and auth flow in staging or low-risk window.
- Confirm latest user-dashboard container matches source.
- Confirm account and home provisioning templates are ready.

---

## 17. Important Paths

- Cloud stack root: Server Side/
- Backend app: Server Side/backend/app/
- User dashboard static app: Server Side/user-frontend/static/index.html
- Admin dashboard static app: Server Side/owner-frontend/static/
- SQL init scripts: Server Side/mysql/init/
- RPi publisher: Sensing Layer/
- Android app: User Apps/Android/WattWiseUserApp/

---

## 18. Final Status Summary

The system is now aligned to the latest stable working state with:
- Completed auth endpoints for mobile and web integrations.
- Corrected admin seed email domain for production-style login usage.
- Working user dashboard login overlay and token bootstrap behavior.
- Working Android to WebView authentication handoff via URL fragment.
- Verified deployment parity strategy for static dashboard container content.

Use this document as the operational baseline for future setup, onboarding, and release validation.
