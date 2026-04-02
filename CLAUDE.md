# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WattWise is a PhD research platform by Mr. Suhas Devmane (Cardiff University, COMSC) for community-level energy monitoring and decision-making. It spans three physical layers: Raspberry Pi sensing nodes → cloud backend → Android mobile app.

Live production server: `https://www.talk2futurebuildings.systems` (Cloudflare Tunnel on port 443)

---

## Commands

### Backend (Server Side/backend)

```bash
# Start full stack (from Server Side/)
docker compose up --build

# Start detached
docker compose up -d --build

# View logs
docker compose logs -f backend
docker compose logs -f

# Restart single service
docker compose restart backend

# Run backend tests
cd "Server Side/backend"
pip install -r requirements.txt
pytest tests/ -v

# Lint (ruff, configured to ignore E501)
ruff check app/

# Database migrations (Alembic)
alembic upgrade head          # Apply all migrations
alembic revision --autogenerate -m "description"  # Generate new migration
alembic downgrade -1          # Roll back one step

# Generate admin password hash
python3 scripts/generate_admin_hash.py

# Import CSV data
python3 scripts/import_csv.py
```

### Android App (User Apps/Android/WattWiseUserApp)

```bash
# Debug build
./gradlew assembleDebug

# Release build
./gradlew assembleRelease

# Run unit tests
./gradlew test

# Run a single test class
./gradlew test --tests "com.wattwise.userapp.ui.settings.SettingsViewModelTest"

# Clean build
./gradlew clean assembleDebug
```

### Sensing Layer (Sensing Layer/)

```bash
# Install RPi publisher as systemd service
sudo bash install_publisher.sh

# Run manually (on RPi)
python3 rpi_mqtt_publisher.py --config /etc/wattwise/publisher.yaml

# Check publisher logs
journalctl -u wattwise-publisher -f
tail -f /var/log/wattwise-publisher.log
```

### Account Provisioning

```powershell
# Create 15 test accounts on live server (PowerShell)
.\create_test_accounts.ps1

# Export accounts to Excel
.\export_accounts_excel.ps1
```

---

## Architecture

### Data Flow

```
Tapo P110 plugs (10s readings)
  → Home Assistant on RPi (local InfluxDB v1.x, database: homeassistant)
    → rpi_mqtt_publisher.py (polls every 30s)
      → Cloud MQTT (Mosquitto via WebSocket, wss://…/mqtt on port 443)
        → FastAPI mqtt_client.py subscriber
          → MySQL (relational: users, homes, goals, decisions, rankings)
          → InfluxDB (time-series: energy_readings bucket)
          → Expo Push → Android app notifications
              → Android WebView loads user dashboard from :3001
```

### Component Map

| Layer | Technology | Location |
|-------|-----------|----------|
| Sensing | Python 3, paho-mqtt (WebSocket), InfluxDB client | `Sensing Layer/` |
| Backend API | FastAPI (async), SQLAlchemy 2.x, aiomysql | `Server Side/backend/app/` |
| Databases | MySQL 8.0 (relational) + InfluxDB 1.8 (time-series) | Docker volumes |
| MQTT broker | Mosquitto 2, port 9001 WebSocket | `Server Side/mosquitto/` |
| Reverse proxy | nginx (HTTP-only — Cloudflare terminates TLS) | `Server Side/nginx-proxy/` |
| Admin dashboard | Node.js, served on :3000 | `Server Side/owner-frontend/` |
| User dashboard | Node.js, served on :3001 (loaded in WebView) | `Server Side/user-frontend/` |
| Android app | Kotlin, Jetpack Compose, Hilt, Retrofit, WebView | `User Apps/Android/WattWiseUserApp/` |

### Backend Structure (`Server Side/backend/app/`)

- **main.py** — App entry point, JWT auth middleware, scheduler setup (8 cron jobs), router registration. Public paths (no auth): `/`, `/health`, `/docs`, `/api/auth/signup`, `/api/auth/login`, `/api/rankings/leaderboard`
- **models.py** — 15 SQLAlchemy ORM models. Core tables: `users → homes → devices → energy_readings → hourly_summary → daily_summary`. PhD research tables: `notifications → user_decisions` (tracks decision type, response time, energy impact, effectiveness score). `user_interaction_logs` for behavioral analytics.
- **scheduler.py** — APScheduler jobs: hourly aggregation (30 min), daily aggregation (00:15), goal checks (hourly), peak reminder (15:45), daily report (07:00), decision impact calc (2 hourly), rankings (01:30), weekly email (Mon 08:00).
- **mqtt_client.py** — Subscribes to `wattwise/homes/+/+/+/data`, writes to both MySQL and InfluxDB.
- **notification_engine.py** — Expo Push API integration.
- **routers/** — 9 modules: `auth`, `devices`, `readings`, `notifications`, `goals`, `decisions`, `analysis`, `admin`, `export`.
- **alembic/** — Database migrations. Run `alembic upgrade head` inside `Server Side/backend/`.

### Android App Structure (`com.wattwise.userapp`)

**Package:** `com.wattwise.userapp` (rebranded from `com.iaa.userapp` — no backward-compat aliases remain except in git history)

- **Single Activity** (`MainActivity`) — Jetpack Compose Navigation hosts all screens
- **Screens:** Splash → Login/Signup (auth) → Main (WebView) → Settings / About
- **Dynamic server URL** — User can change server address in Settings. `ServerPreferencesDataStore` persists it; `ServerConfig` singleton holds the live value; OkHttp `dynamicUrlInterceptor` in `AppModule.kt` rewrites every Retrofit request URL at call time (avoids Retrofit rebuild).
- **WebView** (`MainScreen.kt`) — Loads `{serverUrl}:{port}` (the user-facing dashboard). Geolocation auto-granted, SSL errors currently proceeded (dev mode). Pull-to-refresh supported.
- **Notifications** — `WattWiseNotificationRouter` parses Expo push payloads and builds deep-link intents into the WebView.

### Key Config Files

- `Server Side/.env` — Live secrets (not committed). Template at `Server Side/.env.production.template`
- `Server Side/backend/app/config.py` — Pydantic settings; UK tariff rates (peak 16:00–19:00, £0.32/kWh), energy thresholds, JWT expiry (7 days)
- `Server Side/mysql/init/` — SQL schema applied on first MySQL container start
- `User Apps/Android/.../util/Constants.kt` — Default server URL, port (443), API paths, notification channel IDs
- `Sensing Layer/rpi_publisher_config.yaml` — Per-home device entity_id → MQTT mapping; MQTT host/port/transport

### MQTT Topic Convention

```
wattwise/homes/{home_id}/devices/{entity_id}/data
```

Entity IDs match InfluxDB measurement names: `airfryer_current_consumption`, `dishwasher_current_consumption`, `kettle_current_consumption`, `microwave_current_consumption`, `toaster_current_consumption`, `washing_machine_current_consumption`

### Database Dual-Write Pattern

All MQTT ingestion writes to both:
1. **MySQL** `energy_readings` table — relational queries, aggregation, goal-tracking. External port 3307 (not 3306) for direct dev access.
2. **InfluxDB 1.8** `energy_readings` measurement — time-series queries using InfluxQL (not Flux). External port 8086.

Aggregation jobs (scheduler) populate `hourly_summary`, `daily_summary`, `home_daily_totals` from the MySQL raw table.

### nginx Routing

Cloudflare terminates TLS; nginx receives plain HTTP on port 80.

| Path | Upstream |
|------|----------|
| `/api/*` | FastAPI :8000 (rate limited: 60/min) |
| `/api/auth/*` | FastAPI :8000 (rate limited: 10/min) |
| `/mqtt` | Mosquitto :9001 (WebSocket) |
| `/ws/*` | FastAPI :8000 (WebSocket, 3600s timeout) |
| `/` | user-frontend :3001 |

### CI/CD (`.github/workflows/ci-cd.yml`)

Three jobs: `test-backend` (pytest + ruff) → `build-android` (assembleDebug, artifact upload) → `build-docker` + `deploy` (SSH to prod, `docker compose up -d`, only on `main`). Deploy requires `PROD_HOST`, `PROD_USER`, `PROD_SSH_KEY` secrets and a `production` environment.

---

## PhD Research Context

The `user_decisions` table is the research core — it records when users accept/reject/defer energy-saving notifications. `decision_tracker.py` measures effectiveness by comparing `energy_before_kwh` vs `energy_after_kwh` in 2-hour windows. `energy_rankings` enables community-scale behaviour comparison (leaderboard). `user_interaction_logs` captures 13 interaction types for behavioral analytics.


## Workflow Orchestration

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP and re-plan immediately - don't keep pushing
- Use plan mode for verification steps, not just building
- Write detailed specs upfront to reduce ambiguity

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One task per subagent for focused execution

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project

### 4. Verification Before Done
- Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness

### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it

### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests - then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how