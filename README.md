# ⚡ WattWise — Smart Home Energy Monitoring

> **Developer:** Mr. Suhas Devmane · Cardiff University, Wales, UK  
> **Research:** PhD — Community-Level Energy Decision-Making & Behaviour Change  
> **Version:** 4.0.0 (Community Release)

A community-scale, cloud-hosted energy monitoring platform. Each household's Raspberry Pi + Tapo smart plugs publish telemetry to a central cloud backend. Users receive intelligent energy alerts, compete in community rankings, set consumption goals, and make data-driven decisions — supporting PhD research in energy behaviour change.

---

## 📘 Operations Docs

- [WATTWISE_SETUP_GUIDE.md](WATTWISE_SETUP_GUIDE.md) — full setup and operations guide.
- [QUICK_START.md](QUICK_START.md) — 5 to 10 minute bring-up and smoke checks.
- [DEPLOY_CHECKLIST.md](DEPLOY_CHECKLIST.md) — pre-deploy and post-deploy validation.

---

## 🏗️ Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full system diagram, database strategy, and community migration plan.

```
Tapo Plugs → Home Assistant (RPi) → InfluxDB (local)
  → rpi_mqtt_publisher.py → Cloud MQTT (Mosquitto)
    → FastAPI Backend (Docker) → MySQL + InfluxDB Cloud
      → User Dashboard (Nginx :3001) ← Android App (WebView)
      → Admin Dashboard (Nginx :3000)
      → Expo Push Notifications → Android
```

---

## 🚀 Quick Start (Development)

```bash
cd "Server Side"

# 1. Copy and fill in environment
cp .env.production.template .env
# Edit .env with your credentials

# 2. Generate admin password hash
python3 scripts/generate_admin_hash.py
# Paste hash into mysql/init/01-schema.sql

# 3. Set up MQTT passwords
docker compose exec mosquitto bash /mosquitto/scripts/setup_mqtt_passwords.sh

# 4. Start all services
docker compose up --build
```

Services available:
| Service | URL |
|---------|-----|
| FastAPI backend | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Admin Dashboard | http://localhost:3000 |
| User Dashboard | http://localhost:3001 |

---

## 📁 Repository Structure

```
WattWise/
├── ARCHITECTURE.md         ← Full architecture & migration plan
├── app.js                  ← Legacy Node.js API (Render.com)
├── model/ routes/ services/ controllers/  ← Node.js modules
├── Dockerfile.nodejs
│
├── Sensing Layer/          ← Raspberry Pi MQTT publisher
│   ├── rpi_mqtt_publisher.py
│   ├── rpi_publisher_config.yaml
│   ├── wattwise-publisher.service  (systemd)
│   └── install_publisher.sh
│
├── Server Side/            ← Cloud backend (Docker Compose)
│   ├── docker-compose.yml
│   ├── .env.production.template
│   ├── backend/            ← FastAPI (Python 3.12)
│   ├── mysql/init/         ← MySQL 8.0 schema (14 tables)
│   ├── mosquitto/          ← MQTT broker + auth
│   ├── nginx-proxy/        ← HTTPS reverse proxy (Let's Encrypt)
│   ├── owner-frontend/     ← Admin dashboard (Nginx :3000)
│   ├── user-frontend/      ← User dashboard (Nginx :3001)
│   └── scripts/
│       └── generate_admin_hash.py
│
├── User Apps/Android/      ← Android app (Kotlin + Compose)
│   └── WattWiseUserApp/    ← com.wattwise.userapp v4.x
│
└── .github/workflows/
    └── ci-cd.yml           ← GitHub Actions CI/CD pipeline
```

---

## ⚠️ Before Going Live

1. Replace `PLACEHOLDER_CHANGE_THIS_HASH` in `mysql/init/01-schema.sql`  
   → Run `python3 Server Side/scripts/generate_admin_hash.py`
2. Fill in all `REPLACE_*` values in `Server Side/.env`
3. Set up MQTT passwords via `setup_mqtt_passwords.sh`
4. Update `Constants.kt` → `DEFAULT_SERVER_URL = "https://app.wattwiser.org"`
5. Configure GitHub secrets: `PROD_HOST`, `PROD_USER`, `PROD_SSH_KEY`

---

## 📱 Android App

- **Package:** `com.wattwise.userapp`
- **Version:** 4.0.0 (Community Release)  
- **Min SDK:** 26 (Android 8.0+)
- **Architecture:** Jetpack Compose + Hilt DI + WebView + Expo Push

The app displays the user dashboard as a WebView — no Play Store release needed for UI updates. Only infrastructure changes (new API routes, push notification format changes) require an app update.

---

## 🧪 Local Testing — Endpoints & Credentials

All 9 containers must be running (`docker compose up -d` from repo root). The dummy data sender posts live readings every 5 s so dashboards show charts immediately.

### Test Credentials

#### Admin account (full access to all admin routes)
| Field | Value |
|-------|-------|
| Email | `admin@wattwise.co.uk` |
| Password | `WattWise_Admin_Sys_Production_2026!` |

#### Participant accounts (15 seeded users, one per home)

| # | Name | Email | Password | Home |
|---|------|-------|----------|------|
| 1 | Aled Morgan | `aled.morgan.1@wattwise-cardiff.co.uk` | `CardiffWW2026!01` | home_001 |
| 2 | Bethan Hughes | `bethan.hughes.2@wattwise-cardiff.co.uk` | `CardiffWW2026!02` | home_002 |
| 3 | Carys Evans | `carys.evans.3@wattwise-cardiff.co.uk` | `CardiffWW2026!03` | home_003 |
| 4 | Dylan Price | `dylan.price.4@wattwise-cardiff.co.uk` | `CardiffWW2026!04` | home_004 |
| 5 | Elen Jones | `elen.jones.5@wattwise-cardiff.co.uk` | `CardiffWW2026!05` | home_005 |
| 6 | Ffion Roberts | `ffion.roberts.6@wattwise-cardiff.co.uk` | `CardiffWW2026!06` | home_006 |
| 7 | Gareth Thomas | `gareth.thomas.7@wattwise-cardiff.co.uk` | `CardiffWW2026!07` | home_007 |
| 8 | Hannah Williams | `hannah.williams.8@wattwise-cardiff.co.uk` | `CardiffWW2026!08` | home_008 |
| 9 | Iwan Davies | `iwan.davies.9@wattwise-cardiff.co.uk` | `CardiffWW2026!09` | home_009 |
| 10 | Jasmine Patel | `jasmine.patel.10@wattwise-cardiff.co.uk` | `CardiffWW2026!10` | home_010 |
| 11 | Kieran Lewis | `kieran.lewis.11@wattwise-cardiff.co.uk` | `CardiffWW2026!11` | home_011 |
| 12 | Lowri Jenkins | `lowri.jenkins.12@wattwise-cardiff.co.uk` | `CardiffWW2026!12` | home_012 |
| 13 | Megan Rees | `megan.rees.13@wattwise-cardiff.co.uk` | `CardiffWW2026!13` | home_013 |
| 14 | Nia Griffiths | `nia.griffiths.14@wattwise-cardiff.co.uk` | `CardiffWW2026!14` | home_014 |
| 15 | Owain Pritchard | `owain.pritchard.15@wattwise-cardiff.co.uk` | `CardiffWW2026!15` | home_015 |

---

### Get an API Token (PowerShell)

#### Admin token
```powershell
$TOKEN = (curl -s -X POST http://localhost:8000/api/auth/login `
  -H "Content-Type: application/json" `
  -d '{"email":"admin@wattwise.co.uk","password":"WattWise_Admin_Sys_Production_2026!"}' `
  | ConvertFrom-Json).access_token
```

#### Participant token (use any seeded user from the table above)
```powershell
$USER_TOKEN = (curl -s -X POST http://localhost:8000/api/auth/login `
  -H "Content-Type: application/json" `
  -d '{"email":"aled.morgan.1@wattwise-cardiff.co.uk","password":"CardiffWW2026!01"}' `
  | ConvertFrom-Json).access_token
```

Use the token in all subsequent requests:
```powershell
curl -s http://localhost:8000/api/auth/me -H "Authorization: Bearer $TOKEN"
```

---

### Dashboards (open in browser — no token needed)

| URL | What you see |
|-----|-------------|
| `http://localhost/` | User energy dashboard |
| `http://localhost:3001/` | Same (direct, bypasses nginx) |
| `http://localhost:3000/` | Admin dashboard |
| `http://localhost:8000/docs` | Full Swagger UI — try every endpoint interactively |

---

### Health Checks

| URL | Expected response |
|-----|------------------|
| `http://localhost/health` | `{"status":"ok"}` |
| `http://localhost:8000/health` | `{"status":"ok"}` |
| `http://localhost:8000/health/dependencies` | `{"status":"ok","checks":{"database":true,"mqtt":true,"influxdb":true}}` |
| `http://localhost:8000/health/slo` | `{"status":"ok","breaches":{"errors":false,"auth_failures":false}}` |
| `http://localhost:8000/metrics` | JSON counters: requests, 2xx/4xx/5xx, readings ingested |

---

### API Endpoints — Admin token required

| Method + Endpoint | What it returns |
|-------------------|----------------|
| `GET /api/auth/me` | Your profile (`is_admin: true` for admin) |
| `GET /api/admin/dashboard` | Totals: users, homes, devices, energy today, notifications sent |
| `GET /api/admin/users` | Full user list with persona, home, and goal info |
| `GET /api/admin/users/{user_id}/details` | Deep profile for one user |
| `GET /api/admin/devices/status` | Online/offline/wattage for every device |
| `GET /api/admin/mqtt/stats` | Mosquitto broker stats (connected clients, messages) |
| `GET /api/admin/rankings` | Admin view of community rankings |
| `POST /api/admin/rankings/recompute` | Force-recompute all rankings now |
| `POST /api/admin/trigger-aggregations` | Run hourly + daily aggregation immediately |
| `POST /api/admin/anomalies/scan` | Run anomaly detection scan now |
| `POST /api/admin/personas/run-classifier` | Run k-means persona classifier |
| `GET /api/admin/personas` | All personas and their descriptions |
| `GET /api/admin/personas/history` | History of classifier runs |
| `POST /api/admin/notifications/send` | Send a notification to one or all users |
| `GET /api/admin/audit-log` | Admin action audit trail |
| `GET /api/admin/analytics/energy` | Community energy analytics |
| `GET /api/admin/analytics/decisions` | Decision acceptance/rejection analytics |
| `GET /api/admin/analytics/anomalies` | Anomaly analytics |
| `GET /api/admin/analytics/sankey` | Energy flow Sankey data |
| `GET /api/admin/export/energy` | Export energy CSV |
| `GET /api/admin/export/decisions` | Export decisions CSV |
| `GET /api/admin/export/rankings` | Export rankings CSV |
| `GET /api/admin/backup/list` | List available MySQL backups |

### API Endpoints — Participant token required

| Method + Endpoint | What it returns |
|-------------------|----------------|
| `GET /api/homes` | Participant's home info |
| `GET /api/homes/{home_id}/devices` | Devices in their home |
| `GET /api/readings/{device_id}/live` | Live wattage (last reading) |
| `GET /api/readings/{device_id}/hourly` | Hourly usage history |
| `GET /api/readings/{device_id}/daily` | Daily usage history |
| `GET /api/readings/{device_id}/analysis` | Smart usage analysis |
| `GET /api/notifications/` | User's notifications (unread first) |
| `POST /api/notifications/{id}/read` | Mark notification as read |
| `GET /api/goals/` | User's energy goals |
| `POST /api/goals/` | Create a new goal |
| `GET /api/goals/{goal_id}/progress` | Goal progress vs. actuals |
| `GET /api/decisions/` | User's decision history |
| `POST /api/decisions/` | Record a decision (accept/reject/defer) |
| `GET /api/decisions/impact-report` | Energy saved vs. promised |
| `GET /api/rankings/me` | User's rank and score |
| `GET /api/influx/measurements` | InfluxDB measurement names |
| `GET /api/influx/device/{entity_id}/current` | Current power draw from InfluxDB |

### Public Endpoints (no token)

| Method + Endpoint | What it returns |
|-------------------|----------------|
| `GET /api/rankings/leaderboard` | Community leaderboard (anonymised) |
| `POST /api/auth/login` | Exchange email + password for JWT |
| `POST /api/auth/signup` | Register a new user |
| `POST /api/auth/forgot-password` | Request password reset email |
| `POST /api/auth/reset-password` | Complete password reset with token |

---

### Direct DB & Broker Access (GUI tools / CLI)

| Service | Host:Port | User | Password | DB/Bucket |
|---------|-----------|------|----------|-----------|
| MySQL | `127.0.0.1:3307` | `wattwise_app` | `WattWise_App_Db_2026!` | `wattwise_db` |
| InfluxDB | `http://127.0.0.1:8086` | `wattwise_influx` | `WattWise_Influx_2026!` | `wattwise_energy` |
| MQTT TCP | `localhost:1883` | `wattwise_backend` | `WattWise_MQTT_Backend_2026!` | — |
| MQTT WebSocket | `ws://localhost:9001/mqtt` | same | same | — |

Recommended GUI tools: **TablePlus** or **DBeaver** for MySQL, **InfluxDB UI** at `http://127.0.0.1:8086` for time-series, **MQTT Explorer** for broker inspection.

---

### MQTT Per-Home Credentials (for RPi publisher testing)

Each RPi uses its home's dedicated MQTT account — it can only publish to its own topic (`wattwise/homes/home_NNN/#`).

| Home | MQTT Username | MQTT Password |
|------|--------------|---------------|
| 1 | `home_001` | `WW_Home001_RPi_2026!` |
| 2 | `home_002` | `WW_Home002_RPi_2026!` |
| 3 | `home_003` | `WW_Home003_RPi_2026!` |
| 4 | `home_004` | `WW_Home004_RPi_2026!` |
| 5 | `home_005` | `WW_Home005_RPi_2026!` |
| 6 | `home_006` | `WW_Home006_RPi_2026!` |
| 7 | `home_007` | `WW_Home007_RPi_2026!` |
| 8 | `home_008` | `WW_Home008_RPi_2026!` |
| 9 | `home_009` | `WW_Home009_RPi_2026!` |
| 10 | `home_010` | `WW_Home010_RPi_2026!` |
| 11 | `home_011` | `WW_Home011_RPi_2026!` |
| 12 | `home_012` | `WW_Home012_RPi_2026!` |
| 13 | `home_013` | `WW_Home013_RPi_2026!` |
| 14 | `home_014` | `WW_Home014_RPi_2026!` |
| 15 | `home_015` | `WW_Home015_RPi_2026!` |

Test a home credential manually:
```bash
mosquitto_pub -h localhost -p 1883 \
  -u home_001 -P "WW_Home001_RPi_2026!" \
  -t "wattwise/homes/home_001/devices/kettle/data" \
  -m '{"power_w":1850,"energy_kwh":0.05}'
```

---

### Quick Smoke-Test Sequence (PowerShell)

```powershell
# 1. Health
curl -s http://localhost:8000/health/dependencies | ConvertFrom-Json

# 2. Get admin token
$T = (curl -s -X POST http://localhost:8000/api/auth/login `
  -H "Content-Type: application/json" `
  -d '{"email":"admin@wattwise.co.uk","password":"WattWise_Admin_Sys_Production_2026!"}' `
  | ConvertFrom-Json).access_token

# 3. Confirm admin identity
curl -s http://localhost:8000/api/auth/me -H "Authorization: Bearer $T" | ConvertFrom-Json

# 4. Admin dashboard summary
curl -s http://localhost:8000/api/admin/dashboard -H "Authorization: Bearer $T" | ConvertFrom-Json

# 5. Force aggregation so charts populate
curl -s -X POST http://localhost:8000/api/admin/trigger-aggregations -H "Authorization: Bearer $T"

# 6. Community leaderboard (public)
curl -s "http://localhost:8000/api/rankings/leaderboard?limit=5" | ConvertFrom-Json

# 7. Open dashboards in browser
Start-Process "http://localhost:3000"   # Admin
Start-Process "http://localhost:3001"   # User
Start-Process "http://localhost:8000/docs"  # Swagger
```