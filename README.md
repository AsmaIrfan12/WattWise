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

