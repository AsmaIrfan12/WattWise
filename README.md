# ⚡ WattWise — Community Smart-Home Energy Monitoring

> **Developer:** Mr. Suhas Devmane · Cardiff University, Wales, UK
> **Research:** PhD — Community-Level Energy Decision-Making & Behaviour Change
> **Version:** 4.0.0 (Community Release)

Each household's Raspberry Pi + Tapo smart plugs publish energy telemetry to a central
cloud backend. Users get intelligent alerts, community rankings, goals and data-driven
decisions; researchers get behavioural personas and analytics.

> 🔒 **SECURITY NOTICE.** This README and `wattwise_cardiff_participants_*.csv` contain
> **real plaintext credentials** for a private research deployment. **Keep this
> repository PRIVATE.** Rotate every secret before any public release, and prefer the
> gitignored `*.secrets.local` files / `.env` (never committed) for production secrets.

---

## 1. Architecture

```
Tapo P110 plugs → Home Assistant (RPi) → local InfluxDB
   → rpi_mqtt_publisher.py  → Cloud MQTT (Mosquitto, TCP 1883 / WS 9001)
      → FastAPI backend (Docker) → MySQL (relational) + InfluxDB (time-series)
         → nginx → User dashboard (:3001, "/") + Admin dashboard (:3000, "/admin/")
         → Android app (WebView) · Expo push notifications
```
Full detail: [ARCHITECTURE.md](ARCHITECTURE.md). Codebase guide: [CLAUDE.md](CLAUDE.md).

| Layer | Tech | Location |
|---|---|---|
| Sensing | Python, paho-mqtt, InfluxDB | `Sensing Layer/` |
| Backend | FastAPI, SQLAlchemy 2, aiomysql | `Server Side/backend/app/` |
| Databases | MySQL 8 + InfluxDB 1.8 | Docker volumes |
| MQTT | Mosquitto 2 (1883 TCP, 9001 WS) | `Server Side/mosquitto/` |
| Proxy | nginx (HTTP) | `Server Side/nginx-proxy/` |
| Admin UI | Node, `:3000` | `Server Side/owner-frontend/` |
| User UI | Node, `:3001` | `Server Side/user-frontend/` |
| Android | Kotlin, Compose, Hilt, WebView | `User Apps/Android/WattWiseUserApp/` |

---

## ✨ Improved system (admin, analytics & alerts)

Recent work made the platform real-time, self-healing and research-grade. Full plan:
[docs/IMPROVEMENT_PLAN.md](docs/IMPROVEMENT_PLAN.md).

**Dashboards & data**
- **Never-empty charts** — the community-energy and live-telemetry endpoints fall back to
  raw readings, and a **self-healing aggregation** job backfills the last 8 days on boot
  and heals gaps every 30 min, so a fresh deploy populates with no manual steps.
- **Real-time auto-refresh** — admin dashboard every 10 s, analytics every 60 s (only on
  the visible tab, paused when hidden).
- **Pipeline-health strip** on the dashboard shows the freshness of each stage (ingest →
  hourly → daily → rankings → personas) so "everything is 0" is diagnosable at a glance.

**Personas**
- Re-classified **every 6 hours** (was weekly) for near-real-time segmentation.
- New **radar visualization** of each persona's behavioural profile (efficiency, goal
  adherence, decision response, low-consumption) — groups look distinct even at similar counts.

**Analytics**
- **Single-device deep-dive** — inspect any registered user's device (daily usage + peak,
  hour-of-day load profile, window totals).
- **Advanced compare** — device-vs-device across the same or different users, plus
  **community-average**, **persona-average** and **period-over-period** overlays.

**Alerts vs Notifications** (now distinct)
- **Alerts** = system-generated from time-series analysis (peak, spike, standby, goal) —
  interactive and decision-tracked.
- **Notifications** = admin broadcasts (offers/messages).
- The user app splits them via an Alerts/Notifications toggle, and push taps deep-link to
  the right tab.

**Backup & reliability**
- **Per-user and multi-user data export** (JSON research bundles) on the admin Backup tab,
  alongside the nightly full-DB dump.
- **Single scheduler owner** — with 4 uvicorn workers, a MySQL advisory lock elects one
  worker to run scheduled jobs, eliminating duplicate alerts/notifications.
- **RPi publisher** surfaces InfluxDB query errors (throttled) instead of a silent
  "0 published".

> Fresh deploy note: give the aggregation ~30 min and the persona classifier one 6-hour
> cycle to populate, then the community-energy, live-telemetry, persona-radar and analytics
> views fill out with real data.

---

## 2. Deploy to a DigitalOcean droplet (production)

Full guide with every command: **[DEPLOY_DIGITALOCEAN.md](DEPLOY_DIGITALOCEAN.md)**. Summary:

**Current droplet:** Reserved IP `159.65.213.183` (use this — it's stable). Recommended
size **2 vCPU / 4 GB** (a 1 vCPU / 2 GB box works only *with swap* — see below).

```bash
# On the droplet (Docker + Compose already installed):
cd ~ && git clone https://github.com/AsmaIrfan12/WattWise.git wattwise && cd wattwise

# Firewall
sudo ufw allow OpenSSH && sudo ufw allow 80/tcp && sudo ufw allow 3000/tcp \
  && sudo ufw allow 1883/tcp && sudo ufw --force enable

# Swap (REQUIRED on 2 GB — stops MySQL/InfluxDB being OOM-killed)
sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile \
  && sudo swapon /swapfile && echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Secrets — the .env files are gitignored, so copy them from a working machine (LAPTOP):
#   scp .env             "root@159.65.213.183:~/wattwise/.env"
#   scp "Server Side/.env" "root@159.65.213.183:~/wattwise/Server Side/.env"

docker compose up -d --build      # first boot ~2-3 min (schema + seed + bootstrap)
docker compose ps                 # all Up/healthy
curl -s http://localhost/health   # {"status":"healthy"}
```

Then:
- **Admin portal:** `http://159.65.213.183:3000`
- **User dashboard / API:** `http://159.65.213.183`

The stack is **IP-agnostic** (nginx `server_name _`, relative API paths) — only the
**clients** (Android app + RPis) need the address; the server needs no domain to run.

### Add a domain + HTTPS later
Point a domain's A record at the droplet, issue a Let's Encrypt cert (nginx already has a
`:443` block + certbot volumes), then switch the app to `https://your.domain` and RPis
back to `wss` on 443.

---

## 3. Local development

```bash
# From the repo ROOT (compose lives here, not in "Server Side"):
docker compose up -d --build
docker compose ps
```
The **dummy data sender** auto-starts and posts synthetic readings for the 50 participant
homes every **5 minutes**. It does **not** touch real RPi homes (e.g. Asma / home_001).

| Service | URL |
|---|---|
| User dashboard | http://localhost/ (or `:3001`) |
| Admin dashboard | http://localhost:3000 |
| API + Swagger | http://localhost:8000 · http://localhost:8000/docs |
| Health | http://localhost/health → `{"status":"healthy"}` |

---

## 4. Credentials

> 🔒 Real secrets — keep the repo private and rotate before any public release.

### Admin
| Field | Value |
|---|---|
| Email | `admin@wattwise.co.uk` |
| Password | `WattWise_Admin_Sys_Production_2026!` |

### 🏠 Asma Irfan — REAL RPi home (`home_001`)
The one live sensing node. Her RPi runs Home Assistant + InfluxDB and publishes real Tapo
data. Bundle: [`Sensing Layer/deployments/asma-irfan/`](Sensing%20Layer/deployments/asma-irfan/).

| Purpose | Field | Value |
|---|---|---|
| **App / web login** | Email | `IrfanA1@cardiff.ac.uk` |
| | Password | `WattWise2024!` |
| **Cloud MQTT** (broker) | Username | `home_001` |
| | Password | `WW_Home001_RPi_2026!` |
| | Broker (droplet) | `159.65.213.183:1883` · transport **tcp** · tls **false** |
| | Broker (domain+TLS) | `<domain>:443` · transport websockets · path `/mqtt` · tls true |
| **Local InfluxDB** (on her RPi) | Host | `localhost:8086`, db `homeassistant`, ssl false |
| | Username | `homeassistant` |
| | Password | `Nabira2012!`  *(from her HA `secrets.yaml: influxdb_password`)* |

**Her 4 devices** — `entity_id` is the cloud-match string (keep exact); `power_entity_id`
is the HA InfluxDB tag the publisher reads:

| Appliance | entity_id (cloud) | power_entity_id (HA InfluxDB) |
|---|---|---|
| Airfryer | `sensor.airfryer_04d1f4` | `airfryer_current_consumption` |
| Dishwasher | `sensor.dishwasher_aebe90` | `dishwasher_current_consumption` |
| Microwave | `sensor.microwave_821ec2` | `microwave_current_consumption` |
| Washing Machine | `sensor.washing_machine_b612c5` | `washing_machine_current_consumption` |

**RPi config for the droplet** — set the `mqtt:` block in her
`rpi_publisher_config.yaml` (or the add-on's `/config/wattwise_publisher.yaml`) to:
```yaml
mqtt:
  host: "159.65.213.183"
  port: 1883
  transport: "tcp"
  ws_path: ""
  username: "home_001"
  password: "WW_Home001_RPi_2026!"
  tls: false
```
Home Assistant OS runtime = the **WattWise Publisher add-on**
([`Sensing Layer/hass-addon/wattwise-publisher/`](Sensing%20Layer/hass-addon/wattwise-publisher/)).

### Synthetic participants (50 seeded homes)
Full list + passwords: [`wattwise_cardiff_participants_20260403-105251.csv`](wattwise_cardiff_participants_20260403-105251.csv).
Pattern: email `firstname.lastname.N@wattwise-cardiff.co.uk`, password `CardiffWW2026!NN`
(e.g. `aled.morgan.1@wattwise-cardiff.co.uk` / `CardiffWW2026!01`). These are
dummy-data-fed and have no RPi.

### Per-home MQTT accounts (RPi provisioning)
Each RPi may only publish to `wattwise/homes/home_NNN/#`. **`home_001` = Asma (real).**
`home_002`–`home_015` are pre-provisioned for future real RPis; password pattern
`WW_HomeNNN_RPi_2026!`. Full set lives in `.env` (`MQTT_HOME_0NN_PASS`).

### Direct DB / broker access (dev, bound to 127.0.0.1)
| Service | Host:Port | User | Password | DB |
|---|---|---|---|---|
| MySQL | `127.0.0.1:3307` | `wattwise_app` | `WattWise_App_Db_2026!` | `wattwise_db` |
| InfluxDB (cloud) | `127.0.0.1:8086` | `wattwise_influx` | `WattWise_Influx_2026!` | `wattwise_energy` |
| MQTT TCP | `localhost:1883` | `wattwise_backend` | `WattWise_MQTT_Backend_2026!` | — |

---

## 5. Android app

- Package `com.wattwise.userapp` · v4.0.0 · min SDK 26 · Compose + Hilt + WebView.
- **Default server is the droplet** (`http://159.65.213.183`, port 80, HTTP) — a fresh
  install connects with no setup. Users can change it in Settings.
- Build an installable APK:
  ```bash
  cd "User Apps/Android/WattWiseUserApp"
  ./gradlew assembleRelease   # -> app/build/outputs/apk/release/app-release.apk
  ```
  (Release falls back to the debug signing key when there's no `keystore.properties`, so
  the APK is installable for sideloading.)
- To move to a domain later: edit `util/Constants.kt` (`DEFAULT_SERVER_URL`, `DEFAULT_PORT`)
  and add the host to `res/xml/network_security_config.xml`, then rebuild.

---

## 6. RPi publisher (real homes)

Bundle: [`Sensing Layer/deployments/asma-irfan/`](Sensing%20Layer/deployments/asma-irfan/)
(copy per home). Deploy guide: that folder's `README.md`. On Home Assistant OS use the
**add-on** (no host `systemctl`); on Raspberry Pi OS use `install_publisher.sh` (systemd).
New home = copy the bundle, set `home.id` / MQTT creds / device `entity_id`s / InfluxDB
creds. Device entity_ids come from the admin DB; InfluxDB tags from `SHOW TAG VALUES FROM
"W" WITH KEY = "entity_id"` in the RPi's InfluxDB add-on.

---

## 7. Operations & troubleshooting

```bash
docker compose logs -f backend                 # tail a service
docker compose run --rm bootstrap-aggregator   # rebuild summaries + rankings + personas
docker compose restart backend                 # restart one service
docker compose pull && docker compose up -d --build   # update after git pull
```

**On a fresh deploy, expect a warm-up period** — the aggregation/ranking jobs and the
persona classifier need data first:

| Symptom | Cause | Resolution |
|---|---|---|
| Energy total `0 kWh` / `£0.00`, "home always 0" | summaries empty until the 30-min hourly-agg job runs | wait ~30–60 min after data flows |
| "Persona = None / only Disengaged", empty compare | classifier needs ≥2 days of daily rankings + ≥12 engaged homes | let data run ~2 days, then **⚙ Run Classifier** (admin) or `bootstrap-aggregator` |
| Home not in rankings | rankings built by the daily job (01:30) | next day |
| "Service temporarily unavailable" / "analytics failed" | backend/MySQL OOM on a 2 GB droplet | ensure **4 GB swap**; resize to 2 vCPU / 4 GB |
| Devices "on" but shown offline | online = reported in last 15 min | confirm the RPi/dummy is publishing |
| Asma's home 0 / offline | her RPi isn't publishing to the droplet | set her `mqtt` to `159.65.213.183:1883` tcp (§4) |
| `MQTT connect failed (rc=5)` | wrong MQTT user/pass, or `home.id` ≠ MQTT username | check §4 |
| RPi "0 published" but MQTT + ping OK | InfluxDB add-on auth missing | set `influxdb.username/password` (§4) |

Personas auto-classify on every `docker compose up` (bootstrap), weekly (Sun 02:00), and
via the admin **⚙ Run Classifier** button.

---

## 8. Key API endpoints

Swagger (`/docs`) is the live reference. Highlights:

**Public:** `POST /api/auth/login`, `POST /api/auth/signup`, `GET /api/rankings/leaderboard`, `GET /health`.
**Participant (JWT):** `GET /api/homes`, `GET /api/readings/{device_id}/live|hourly|daily|standby`, `GET /api/rankings/me`, `GET /api/goals/`, `GET /api/decisions/`.
**Admin (JWT):** `GET /api/admin/dashboard|users|devices/status`, `POST /api/admin/personas/run-classifier`, `POST /api/admin/anomalies/scan`, `GET /api/admin/analytics/*`, `GET /api/admin/export/*`.

### Smoke test (bash)
```bash
curl -s http://localhost/health
T=$(curl -s -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" \
  -d '{"email":"admin@wattwise.co.uk","password":"WattWise_Admin_Sys_Production_2026!"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s http://localhost:8000/api/admin/dashboard -H "Authorization: Bearer $T"
curl -s "http://localhost:8000/api/rankings/leaderboard?limit=5"
```

---

## 9. Repository layout
```
WattWise/
├── docker-compose.yml            ← full stack (run from repo root)
├── .env / .env.example           ← compose secrets (.env gitignored)
├── DEPLOY_DIGITALOCEAN.md        ← droplet deploy guide
├── Sensing Layer/                ← RPi publisher + per-home bundles + HA add-on
├── Server Side/                  ← backend, frontends, mysql, mosquitto, nginx
│   └── .env                      ← backend secrets (gitignored)
└── User Apps/Android/            ← Kotlin app (com.wattwise.userapp)
```
