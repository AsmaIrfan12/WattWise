# WattWise — DigitalOcean Production Deployment Design

**Date:** 2026-04-02
**Author:** Mr. Suhas Devmane, Cardiff University
**Status:** Approved

---

## 1. Goal

Make WattWise deployable on a DigitalOcean droplet at reserved IP `129.212.163.88` using HTTP (HTTPS/Let's Encrypt added later when a domain is attached), while keeping the existing setup working on the dev laptop unchanged. RPi publishers must be able to send data to the cloud server. Admin must be able to view, compare, and back up all user data.

---

## 2. Deployment Strategy

**Pattern:** Docker Compose base + production override.

| Environment | Command |
|-------------|---------|
| Laptop (dev) | `docker compose up -d --build` |
| DigitalOcean | `docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build` |

The base `docker-compose.yml` is untouched for dev. The production override applies only DO-specific differences.

---

## 3. Services (unchanged)

All 8 existing services remain. No services added or removed.

| Service | Container | Internal Port |
|---------|-----------|--------------|
| mosquitto | wattwise-mosquitto | 1883 (TCP), 9001 (WebSocket) |
| mysql | wattwise-mysql | 3306 |
| influxdb | wattwise-influxdb | 8086 |
| backend | wattwise-backend | 8000 |
| admin-dashboard | wattwise-admin-frontend | 3000 |
| user-dashboard | wattwise-user-frontend | 3001 |
| nginx-proxy | wattwise-nginx-proxy | 80 |
| mysql-backup | wattwise-mysql-backup | — |

---

## 4. nginx Routing (Updated)

`server_name _` catch-all replaces the Cloudflare-specific hostname. Works on both `localhost` and `129.212.163.88`.

| Path | Upstream | Notes |
|------|----------|-------|
| `/` | user-dashboard:3001 | User web dashboard |
| `/api/` | backend:8000 | Rate limited 60/min |
| `/api/auth/` | backend:8000 | Rate limited 10/min |
| `/health` | backend:8000 | No rate limit |
| `/ws/` | backend:8000 | WebSocket upgrade |
| `/mqtt` | mosquitto:9001 | WebSocket upgrade (RPi via WS) |
| `/admin/` | admin-dashboard:3000 | Prefix stripped before forwarding |
| `/admin` | — | 301 redirect → `/admin/` |

HTTPS server block is included but commented out — uncomment when certbot is configured.

---

## 5. Firewall Rules (DigitalOcean)

| Port | Protocol | Direction | Purpose |
|------|----------|-----------|---------|
| 22 | TCP | Inbound | SSH admin access |
| 80 | TCP | Inbound | nginx — all web traffic + MQTT WS |
| 1883 | TCP | Inbound | MQTT direct TCP from RPi |
| All | All | Outbound | Allow all outbound |

**Blocked externally:** 3307 (MySQL), 8086 (InfluxDB), 8000 (FastAPI), 3000, 3001 — Docker-internal only on DO.

---

## 6. Production Override (`docker-compose.production.yml`)

Four changes from base:

1. **MySQL**: remove external port `3307:3306` (not safe to expose publicly)
2. **InfluxDB**: remove external port `8086:8086` (not safe to expose publicly)
3. **mysql-backup**: change `./backups` bind mount → named volume `backups_data`
4. **backend**: add `backups_data` volume mount at `/backups` (for flag file sharing with mysql-backup)

---

## 7. Persistent Volumes

All volumes are Docker named volumes — persist across `docker compose restart` and `docker compose down` (NOT `docker compose down -v`).

| Volume | Contents |
|--------|----------|
| `mysql_data` | All relational data (users, decisions, rankings, etc.) |
| `influxdb_data` | Time-series energy readings |
| `mosquitto_data` | MQTT persistence file |
| `mosquitto_log` | MQTT logs |
| `backups_data` | mysqldump `.sql.gz` archives + backup toggle flag |
| `letsencrypt` | TLS certs (empty now, used when HTTPS added) |
| `certbot_webroot` | Certbot challenge files (empty now) |

---

## 8. Backup System

### Auto-backup toggle
- A flag file `/backups/.backup_disabled` in the `backups_data` volume controls auto-backup.
- If the file **exists** → mysql-backup service skips the dump and logs "skipped".
- If the file **does not exist** → dump runs normally.
- The backend API creates/deletes this file.

### mysql-backup service (updated entrypoint logic)
```
loop every 24 hours:
  if /backups/.backup_disabled exists:
    log "Auto-backup disabled — skipping"
    continue
  run: mysqldump -h mysql -u$MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE | gzip > /backups/wattwise-YYYYMMDD-HHMMSS.sql.gz
  log "Backup created: <filename>"
  delete dumps older than 30 days
```

### Backend: `routers/backup.py` (admin-only, all require `is_admin=True`)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/backup/settings` | GET | Returns `{ enabled, last_backup_file, last_backup_size_mb, backup_count }` |
| `/api/admin/backup/settings` | POST | Body `{ enabled: bool }` — creates/deletes flag file |
| `/api/admin/backup/list` | GET | Lists all `.sql.gz` files with name, size, timestamp |
| `/api/admin/backup/download` | GET | Runs `mysqldump` via subprocess, streams `.sql.gz` as download |

`mysqldump` is available in the backend container via `default-mysql-client` added to the Dockerfile.

---

## 9. Files Changed

### New files
| File | Purpose |
|------|---------|
| `Server Side/docker-compose.production.yml` | DO-specific overrides |
| `Server Side/backend/app/routers/backup.py` | Backup API router |
| `Server Side/scripts/deploy.sh` | One-shot DO setup script |

### Modified files
| File | Change |
|------|--------|
| `Server Side/nginx-proxy/nginx.conf` | catch-all server_name, /admin route, HTTP-only |
| `Server Side/docker-compose.yml` | backups_data volume declaration (used by override) |
| `Server Side/backend/Dockerfile` | Add `default-mysql-client` to apt installs |
| `Server Side/backend/app/main.py` | Register backup router |
| `Server Side/.env.production.template` | Update ALLOWED_ORIGINS, STRICT_SECURITY note |
| `Sensing Layer/rpi_publisher_config.yaml` | Add DO IP connection options (commented) |

---

## 10. RPi Publisher Configuration

Two connection options documented in `rpi_publisher_config.yaml`:

```yaml
# Option A — WebSocket via nginx (port 80):
host: "129.212.163.88"
port: 80
transport: "websockets"
ws_path: "/mqtt"

# Option B — Direct MQTT TCP (port 1883):
# host: "129.212.163.88"
# port: 1883
# transport: "tcp"
```

---

## 11. Environment Configuration

### Dev `.env` (existing, unchanged)
- `ALLOWED_ORIGINS=http://localhost:3000,http://localhost:3001,http://localhost:8000`
- `STRICT_SECURITY=false` (weak dev secrets are acceptable)

### Production `.env` (filled from `.env.production.template`)
- `ALLOWED_ORIGINS=http://129.212.163.88,http://129.212.163.88:80`
- `SECRET_KEY=<64-char random string>`
- `MYSQL_ROOT_PASSWORD=<strong password>`
- `MYSQL_PASSWORD=<strong password>`
- `INFLUX_PASS=<strong password>`
- `ADMIN_EMAIL=<your email>`
- `ADMIN_PASSWORD=<strong password>`
- `STRICT_SECURITY=true`

---

## 12. HTTPS Upgrade Path (future)

When a domain is attached:
1. Add domain A record → `129.212.163.88`
2. Add a `certbot` service to `docker-compose.production.yml`
3. Uncomment the HTTPS server block in `nginx.conf`
4. Update `ALLOWED_ORIGINS` in `.env` to use `https://`
5. Update `server_name` in nginx to the real domain

No structural changes required — the architecture is already prepared.

---

## 13. Success Criteria

- `docker compose -f docker-compose.yml -f docker-compose.production.yml up -d` starts all 8 services healthy
- `http://129.212.163.88/` loads user dashboard
- `http://129.212.163.88/admin/` loads admin dashboard
- `http://129.212.163.88/health` returns `{"status": "ok"}`
- `http://129.212.163.88/api/auth/login` accepts admin credentials
- RPi publisher connects to `129.212.163.88:1883` (TCP) or port 80 (WebSocket) and data appears in DB
- Admin can download a backup `.sql.gz` from `/api/admin/backup/download`
- Admin can toggle auto-backup on/off via `/api/admin/backup/settings`
- All named volumes persist across `docker compose restart`
- Laptop dev (`docker compose up -d`) still works unchanged
