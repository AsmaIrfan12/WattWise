# WattWise Server-Side — Production Deployment Guide

> **Author:** Mr. Suhas Devmane, Cardiff University, UK  
> **Supervisor:** Prof. Reza Sahandi, Cardiff University  
> **Version:** 2.1.0 | Community Energy Management Platform

---

## Architecture Overview

```
Internet / RPi
     │
     ▼
┌────────────────────────────────────────────────────┐
│  Nginx Reverse Proxy  (Port 80 / 443)               │
│  ├─ /          → user-frontend  (nginx:3001)        │
│  ├─ /admin/    → owner-frontend (nginx:3000)        │
│  ├─ /api/      → FastAPI backend (uvicorn:8000)     │
│  ├─ /ws/       → FastAPI WebSocket                  │
│  └─ /mqtt      → Mosquitto WebSocket (9001)         │
└────────────────────────────────────────────────────┘
     │               │                │
     ▼               ▼                ▼
 FastAPI          MySQL DB        InfluxDB
 (Async)       (Relational)   (Time-series)
     │
     ▼
 Mosquitto (MQTT broker, port 1883 + WS 9001)
     ▲
     │
 RPi Smart Home Assistant → publishes readings via MQTT/HTTPS
```

---

## Quick Start

```bash
# 1. Clone and configure
cp .env.production.template .env
# Edit .env — set all secrets

# 2. Configure MQTT authentication
bash mosquitto/scripts/setup_mqtt_passwords.sh

# 3. Start all services
docker compose up -d

# 4. Apply database migrations
docker exec wattwise-backend alembic upgrade head

# 5. Verify health
curl http://localhost/health
```

---

## Environment Variables (`.env`)

| Variable | Description | Example |
|----------|-------------|---------|
| `SECRET_KEY` | JWT signing secret (≥32 chars) | `openssl rand -hex 32` |
| `DATABASE_URL` | MySQL async connection string | `mysql+aiomysql://user:pass@mysql/wattwise` |
| `INFLUX_HOST` | InfluxDB hostname | `wattwise-influxdb` |
| `INFLUX_PORT` | InfluxDB port | `8086` |
| `INFLUX_USER` | InfluxDB username | `wattwise` |
| `INFLUX_PASS` | InfluxDB password | `strong_pass` |
| `INFLUX_DB` | InfluxDB database name | `wattwise` |
| `MQTT_BROKER_HOST` | Mosquitto container name | `wattwise-mosquitto` |
| `MQTT_BROKER_PORT` | MQTT port | `1883` |
| `MQTT_USERNAME` | Backend MQTT client username | `wattwise_backend` |
| `MQTT_PASSWORD` | Backend MQTT client password | `strong_mqtt_pass` |
| `MQTT_TOPIC_PREFIX` | Base topic prefix | `wattwise/homes` |
| `ADMIN_EMAIL` | Initial admin account email | `admin@wattwise.io` |
| `ADMIN_PASSWORD` | Initial admin password | `change_immediately` |
| `ALLOWED_ORIGINS` | CORS allowed origins (comma-sep) | `https://wattwise.io,https://admin.wattwise.io` |
| `LOG_FORMAT` | `text` or `json` (production: use `json`) | `json` |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING` | `INFO` |
| `STRICT_SECURITY` | `true` = block startup on config warnings | `true` |

---

## Services

| Service | Container | Port | Purpose |
|---------|-----------|------|---------|
| FastAPI Backend | `wattwise-backend` | 8000 (internal) | Main API, MQTT ingestion |
| MySQL | `wattwise-mysql` | 3306 (internal) | Relational data store |
| InfluxDB | `wattwise-influxdb` | 8086 (internal) | Time-series energy readings |
| Mosquitto | `wattwise-mosquitto` | 1883 + 9001 | MQTT broker |
| Admin Frontend | `wattwise-admin-frontend` | 3000 (internal) | Owner admin portal |
| User Frontend | `wattwise-user-frontend` | 3001 (internal) | User energy dashboard |
| Nginx Proxy | `wattwise-nginx` | 80, 443 | Reverse proxy + TLS termination |

---

## Database Migrations

```bash
# Run migrations inside backend container
docker exec wattwise-backend alembic upgrade head

# Generate a new migration after model changes
docker exec wattwise-backend alembic revision --autogenerate -m "your description"
```

### Manual Migration (if Alembic not used)

Schema changes to apply:
```sql
-- UniqueConstraint on energy readings (prevents duplicate RPi data)
ALTER TABLE energy_readings ADD UNIQUE INDEX uq_reading_device_time (device_id, recorded_at);

-- CheckConstraint (non-negative power)
ALTER TABLE energy_readings ADD CONSTRAINT chk_power_non_negative CHECK (power_watts >= 0);

-- Admin audit log table
CREATE TABLE admin_audit_logs (
  id INT AUTO_INCREMENT PRIMARY KEY,
  admin_user_id INT NOT NULL,
  action_type VARCHAR(64) NOT NULL,
  target_user_id INT NULL,
  details_json JSON NULL,
  ip_address VARCHAR(45) NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## MQTT Setup

### RPi Publisher Configuration

Each RPi home hub publishes readings to:
```
Topic: wattwise/homes/{home_id}/{entity_id}
Payload: {"power_watts": 1200.5, "current_amps": 5.2, "voltage_volts": 230.0, "energy_kwh": 0.05}
```

### Adding a New Home's RPi Credentials

```bash
# On the host (not inside container):
docker exec -it wattwise-mosquitto mosquitto_passwd /etc/mosquitto/passwd rpi_home_X
# Then restart mosquitto:
docker restart wattwise-mosquitto
```

---

## Admin Portal

Access at: `http://<server-ip>/admin/`

| Feature | Description |
|---------|-------------|
| **Dashboard** | Live KPIs, community energy, decision impact, top rankings |
| **User Management** | Search, filter by persona, toggle notifications, reset passwords |
| **Personas** | View/manage 5 behavioral groups; run the classifier manually |
| **Rankings** | Full leaderboard for daily/weekly/monthly periods |
| **Analytics** | Custom date-range energy trends + CSV export |
| **Devices/RPi** | Online/offline status, last-seen, last power reading |
| **Notifications** | Send broadcasts to all/specific/persona-filtered users |
| **Audit Log** | Full record of all admin actions with IP and timestamps |
| **Backups** | Trigger, list, and download database backups |

---

## User Dashboard

Access at: `http://<server-ip>/`

| Feature | Description |
|---------|-------------|
| **Home** | KPIs, bill prediction, device breakdown, community benchmark |
| **Energy Analytics** | Period selector (today/7d/30d/custom), CSV export, device pie chart |
| **Devices** | Register and manage smart home devices |
| **Alerts** | View/action notifications with ACCEPTED/DEFERRED/REJECTED decisions |
| **Goals** | Set daily/weekly/monthly energy goals; track progress |
| **Ranking** | Community leaderboard, score ring, ranking history chart |
| **Settings** | Toggle notifications, set goals/budget, export data |

---

## Persona Classification

Users are automatically classified weekly (Sunday 02:00 UTC):

| Persona | Criteria |
|---------|----------|
| **Eco Champion** | Efficiency ≥ 75%, Goal Adherence ≥ 80% |
| **Active Improver** | Improving trend + Efficiency ≥ 55% + Adherence ≥ 50% |
| **Steady User** | Default — moderate usage, no strong trend |
| **High Consumer** | Efficiency ≤ 40%, Goal Adherence ≤ 30% |
| **Disengaged** | < 3 ranking days or very low interaction |

Admin can also trigger classification manually or override individual users.

---

## Scheduled Jobs

| Job | Schedule | Description |
|-----|----------|-------------|
| Hourly aggregation | Every hour | Aggregate InfluxDB readings → MySQL |
| Daily aggregation | 1:00 AM | Compute daily totals and device summaries |
| Goal checks | Every 2 hours | Check goal progress, send alerts |
| Rankings compute | 2:30 AM | Calculate daily efficiency + leaderboard |
| Weekly email report | Sunday 8:00 AM | Community summary via SMTP |
| Persona classifier | Sunday 2:00 AM | Re-classify all users |
| Peak-time reminder | 5:00 PM | Alert users during peak tariff hours |

---

## Backup & Recovery

```bash
# Create a backup
curl -X POST http://localhost/api/backup/create \
  -H "Authorization: Bearer <admin_token>"

# List backups
curl http://localhost/api/backup/list \
  -H "Authorization: Bearer <admin_token>"

# Download backup
curl http://localhost/api/backup/download/<filename> \
  -H "Authorization: Bearer <admin_token>" -o backup.sql.gz
```

---

## Testing

```bash
cd backend
python -m pytest tests/ -v
```

Test coverage:
- MQTT input validation (NaN, negative, implausible values)
- Admin community snapshot calculations
- Persona classification logic
- JWT claims structure
- Security config warnings
- DB constraint verification
- N+1 query regression tests

---

## Security Features

- ✅ JWT claims contain `is_admin` flag (no per-request DB lookup)
- ✅ Content-Security-Policy on all frontends
- ✅ MQTT broker authentication (username/password per client)
- ✅ Input validation on all MQTT readings (reject NaN/negative/implausible)
- ✅ Duplicate reading guard (5-second window)
- ✅ Entity ID sanitization (regex, prevents injection)
- ✅ Admin audit log (all sensitive actions recorded)
- ✅ Rate limiting (Nginx — 10 req/min auth, 60 req/min API)
- ✅ DB constraints (UniqueConstraint + CheckConstraint on energy_readings)
- ✅ Startup security warning system

---

## Research Note

> This platform was developed as part of an MSc/PhD research project in community energy
> monitoring at Cardiff University. The system is designed to support community-scale
> energy behavioural studies with full data provenance and audit capabilities.
>
> For academic collaboration, contact: devmanes@cardiff.ac.uk
