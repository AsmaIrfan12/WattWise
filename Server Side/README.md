# WattWise — Server Side

Cloud backend for the WattWise community energy monitoring platform. Runs as a Docker Compose stack on a single Linux host, exposed to the internet via Cloudflare Tunnel.

---

## Architecture

```
Raspberry Pi (Home Assistant + smart plugs)
  └── rpi_mqtt_publisher.py
        └── MQTT over WebSocket (wss://.../mqtt)
              └── Mosquitto broker (port 9001 WS / 1883 TCP)
                    └── FastAPI mqtt_client.py subscriber
                          ├── MySQL 8.0  — relational data (users, homes, devices, goals, decisions)
                          └── InfluxDB 1.8 — time-series energy readings
                                └── APScheduler (8 cron jobs: aggregation, rankings, notifications)
                                      └── Expo Push API → Android app
```

### Services

| Service | Image | Port | Purpose |
|---------|-------|------|---------|
| `mosquitto` | eclipse-mosquitto:2 | 1883 (TCP), 9001 (WS) | MQTT broker for sensor ingestion |
| `mysql` | mysql:8.0 | 3307 (host) | Relational database |
| `influxdb` | influxdb:1.8 | 8086 | Time-series energy telemetry |
| `backend` | python:3.12-slim (built) | 8000 | FastAPI REST API + MQTT subscriber |
| `admin-dashboard` | nginx:alpine (built) | 3000 | Owner/admin web portal |
| `user-dashboard` | nginx:alpine (built) | 3001 | Resident web portal (loaded in Android WebView) |
| `nginx-proxy` | nginx:alpine (built) | 80, 443 | Reverse proxy (TLS terminated by Cloudflare) |
| `mysql-backup` | mysql:8.0 | — | Daily database backup (30-day retention) |

---

## Quick Start

```bash
# 1. Copy and configure environment
cp .env.production.template .env
# Edit .env — replace all REPLACE_* values with strong secrets

# 2. Start all services
cd "Server Side"
docker compose up -d --build

# 3. Verify all services healthy
docker compose ps
docker compose logs -f backend

# 4. Access dashboards
# Admin:  http://localhost:3000
# User:   http://localhost:3001
# API:    http://localhost:8000/docs
```

---

## Configuration

All configuration is via environment variables in `Server Side/.env`. Template: `.env.production.template`.

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | MySQL connection string |
| `INFLUX_HOST/DB/USER/PASS` | InfluxDB connection |
| `MQTT_BROKER_HOST/PORT` | Mosquitto connection |
| `SECRET_KEY` | JWT signing key (generate: `python -c "import secrets; print(secrets.token_urlsafe(64))"`) |
| `ADMIN_EMAIL/PASSWORD` | Admin account credentials |
| `ALLOWED_ORIGINS` | CORS origins (comma-separated) |
| `ENERGY_PEAK_START_HOUR/END_HOUR` | UK peak tariff window (default 16–19) |
| `SMTP_HOST/USER/PASSWORD` | Email for weekly reports (optional) |

---

## Database Schema

MySQL database (`wattwise_db`) contains 15 tables:

**Core:**
- `users` — accounts with push tokens and energy goals
- `homes` — one or more homes per user
- `devices` — smart plugs mapped to HA entity IDs
- `energy_readings` — raw MQTT-ingested readings (power_watts, energy_kwh, current_amps)
- `hourly_summary` / `daily_summary` — pre-aggregated per-device stats
- `home_daily_totals` — whole-home aggregation for rankings

**Research (PhD):**
- `user_decisions` — accept/reject/defer responses to energy notifications (response time, effectiveness score)
- `user_interaction_logs` — 13 interaction types for behavioural analytics
- `energy_rankings` — daily community leaderboard (efficiency, goal adherence, decision score)
- `notifications` — push + in-app notifications with severity and action hints
- `energy_goals` — per-device and whole-home energy targets
- `notification_templates` — reusable admin broadcast templates

InfluxDB stores the same readings as an `energy_readings` measurement for time-series charting (InfluxQL queries, not Flux).

---

## API Endpoints

Base: `http://localhost:8000/api`
Interactive docs: `http://localhost:8000/docs`

| Router | Prefix | Key Endpoints |
|--------|--------|---------------|
| Auth | `/api/auth` | POST /signup, /login, /logout, GET /me |
| Devices | `/api` | CRUD /homes, /homes/{id}/devices |
| Readings | `/api/readings` | GET historical, POST manual ingest |
| Goals | `/api/goals` | CRUD goals, GET /{id}/progress |
| Decisions | `/api/decisions` | POST record decision, GET impact report |
| Notifications | `/api/notifications` | GET list, PATCH /read-all, PATCH /{id}/dismiss |
| Analysis | `/api/analysis` | GET summary, peak usage, leaderboard |
| Admin | `/api/admin` | GET dashboard, POST send-notification, GET users |
| Export | `/api/export` | GET CSV exports |

Public paths (no auth): `/`, `/health`, `/docs`, `/api/auth/signup`, `/api/auth/login`, `/api/rankings/leaderboard`

---

## MQTT Topic Convention

```
wattwise/homes/{home_id}/devices/{entity_id}/data
```

Payload (JSON):
```json
{
  "home_id": "home_001",
  "entity_id": "kettle_current_consumption",
  "power_watts": 2100.5,
  "energy_kwh": 0.583,
  "current_amps": 9.13,
  "voltage_volts": 230.0,
  "switch_state": "on",
  "timestamp": "2026-03-30T14:23:00Z"
}
```

---

## Scheduled Jobs (APScheduler)

| Job | Schedule | Purpose |
|-----|----------|---------|
| Hourly aggregation | Every 30 min | Roll raw readings → hourly_summary |
| Daily aggregation | 00:15 | Roll hourly → daily_summary + home_daily_totals |
| Goal check | Every hour | Detect goal breaches, send notifications |
| Peak reminder | 15:45 daily | Alert users before peak tariff window |
| Daily report | 07:00 daily | Summary notification to all users |
| Decision impact | Every 2 hours | Calculate energy_before/after for accepted decisions |
| Rankings | 01:30 daily | Recompute community leaderboard |
| Weekly email | Monday 08:00 | Email digest with charts |

---

## Admin Access

Default admin account is bootstrapped via `mysql/init/01-schema.sql`. To reset:

```bash
# Generate new password hash
docker compose exec backend python3 scripts/generate_admin_hash.py

# Update in MySQL
docker compose exec mysql mysql -u root -p wattwise_db \
  -e "UPDATE users SET password_hash='<new_hash>' WHERE email='admin@wattwise.co.uk';"
```

---

## Backups

The `mysql-backup` service runs daily and stores compressed SQL dumps in `./backups/`. Files older than 30 days are automatically removed.

To restore:
```bash
gunzip < backups/wattwise-20260330-020001.sql.gz | \
  docker compose exec -T mysql mysql -u wattwise_app -p wattwise_db
```
