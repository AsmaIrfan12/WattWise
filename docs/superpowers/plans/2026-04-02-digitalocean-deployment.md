# WattWise DigitalOcean Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make WattWise fully deployable on a DigitalOcean droplet at a reserved IP (placeholder `YOUR_DROPLET_IP`) via `docker compose -f docker-compose.yml -f docker-compose.production.yml up -d`, while keeping laptop dev unchanged.

**Architecture:** Base `docker-compose.yml` handles dev; `docker-compose.production.yml` is a minimal prod signal file (DigitalOcean external firewall blocks ports 3307/8086, not compose overrides). A new `backup.py` router adds on-demand mysqldump download and auto-backup toggle via a flag file in a shared `backups_data` Docker named volume.

**Tech Stack:** Docker Compose v2, nginx 1.27, FastAPI/Python 3.12, MySQL 8.0, InfluxDB 1.8, Mosquitto 2, Paho MQTT, asyncio.to_thread (Python 3.12)

---

## File Map

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `Server Side/nginx-proxy/nginx.conf` | Catch-all server_name, add /admin/ route, HTTP-only with HTTPS stub |
| Modify | `Server Side/docker-compose.yml` | Change backups to named volume, add volume to backend service |
| Create | `Server Side/docker-compose.production.yml` | Prod signal file (DO firewall handles port blocking) |
| Modify | `Server Side/owner-frontend/static/js/api-client.js` | Add backup API methods (getBackupSettings, setBackupSettings, listBackups) |
| Modify | `Server Side/backend/Dockerfile` | Add `default-mysql-client` apt package |
| Create | `Server Side/backend/app/routers/backup.py` | Admin backup API (settings GET/POST, list, download) |
| Modify | `Server Side/backend/app/main.py` | Register backup router |
| Modify | `Server Side/owner-frontend/static/index.html` | Fix absolute `/js/app.js` path → relative; add Backup nav item + section |
| Modify | `Server Side/owner-frontend/static/js/app.js` | Add backup section JS (toggle, list, download) |
| Modify | `Server Side/.env.production.template` | Update ALLOWED_ORIGINS, add STRICT_SECURITY=true note |
| Modify | `Sensing Layer/rpi_publisher_config.yaml` | Add DO IP connection options (commented) |
| Create | `Server Side/scripts/deploy.sh` | One-shot DigitalOcean setup script |

---

## Task 1: Fix Admin Dashboard Asset Path

**Why first:** The `/admin/` nginx proxy strips the path prefix. With `src="/js/app.js"` (absolute), the browser requests `/js/app.js` which nginx routes to the user-dashboard — wrong file. Must be relative before nginx routing works.

**Files:**
- Modify: `Server Side/owner-frontend/static/index.html:159`

- [ ] **Step 1: Verify the problem**

```bash
grep -n 'src=\|href=' "Server Side/owner-frontend/static/index.html" | grep -v "http\|data:"
```

Expected output includes:
```
159:<script type="module" src="/js/app.js"></script>
```

- [ ] **Step 2: Fix the absolute path to relative**

In `Server Side/owner-frontend/static/index.html`, change line 159:

```html
<!-- BEFORE -->
<script type="module" src="/js/app.js"></script>

<!-- AFTER -->
<script type="module" src="js/app.js"></script>
```

Remove the leading `/`. The module import inside `app.js` (`import { AdminApiClient } from "./api-client.js"`) is already relative — no change needed there.

- [ ] **Step 3: Commit**

```bash
git add "Server Side/owner-frontend/static/index.html"
git commit -m "fix: use relative path for admin dashboard JS module"
```

---

## Task 2: Update nginx.conf

**Files:**
- Modify: `Server Side/nginx-proxy/nginx.conf`

- [ ] **Step 1: Write the new nginx.conf**

Replace the entire contents of `Server Side/nginx-proxy/nginx.conf` with:

```nginx
worker_processes auto;
error_log /var/log/nginx/error.log warn;

events {
    worker_connections 2048;
    multi_accept on;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    sendfile on;
    tcp_nopush on;
    keepalive_timeout 65;
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml;

    # ── Security headers ─────────────────────────────────────────
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer-when-downgrade" always;

    # ── Rate limiting ────────────────────────────────────────────
    limit_req_zone $binary_remote_addr zone=api:10m rate=60r/m;
    limit_req_zone $binary_remote_addr zone=auth:10m rate=10r/m;

    # ── Upstream services ────────────────────────────────────────
    upstream fastapi_backend {
        server wattwise-backend:8000;
        keepalive 32;
    }
    upstream admin_frontend {
        server wattwise-admin-frontend:3000;
    }
    upstream user_frontend {
        server wattwise-user-frontend:3001;
    }

    # ── Main server block (HTTP — works for localhost and any IP) ─
    # server_name _ is a catch-all: works on localhost, 129.212.x.x,
    # and any future domain without changing this file.
    server {
        listen 80;
        server_name _;

        # ── Admin dashboard (strip /admin prefix before forwarding) ─
        # Trailing slash on proxy_pass strips the /admin/ prefix so the
        # admin container receives requests at its own root /.
        location = /admin {
            return 301 /admin/;
        }
        location /admin/ {
            proxy_pass http://admin_frontend/;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_read_timeout 60s;
        }

        # ── Auth endpoints (tighter rate limit) ──────────────────
        location /api/auth/ {
            limit_req zone=auth burst=10 nodelay;
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }

        # ── All other API calls ───────────────────────────────────
        location /api/ {
            limit_req zone=api burst=30 nodelay;
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_read_timeout 60s;
        }

        # ── Health check (no rate limit) ─────────────────────────
        location /health {
            proxy_pass http://fastapi_backend;
            proxy_set_header Host $host;
        }

        # ── WebSocket (real-time updates) ────────────────────────
        location /ws/ {
            proxy_pass http://fastapi_backend;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_read_timeout 3600s;
        }

        # ── MQTT over WebSocket (RPi publishers via port 80) ─────
        # RPi connects via ws://YOUR_DROPLET_IP/mqtt  OR
        #               via ws://localhost/mqtt  (dev)
        location /mqtt {
            proxy_pass http://wattwise-mosquitto:9001;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }

        # ── User Dashboard ────────────────────────────────────────
        location / {
            proxy_pass http://user_frontend;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        }
    }

    # ── HTTPS server block (uncomment when domain + certbot ready) ─
    # server {
    #     listen 443 ssl;
    #     server_name YOUR_DOMAIN;
    #     ssl_certificate /etc/letsencrypt/live/YOUR_DOMAIN/fullchain.pem;
    #     ssl_certificate_key /etc/letsencrypt/live/YOUR_DOMAIN/privkey.pem;
    #     include /etc/letsencrypt/options-ssl-nginx.conf;
    #     ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
    #     # Copy all location blocks from the HTTP server above
    # }

    # ── Catch-all: silently drop requests with unknown hostnames ─
    server {
        listen 80 default_server;
        server_name _;
        return 444;
    }
}
```

- [ ] **Step 2: Commit**

```bash
git add "Server Side/nginx-proxy/nginx.conf"
git commit -m "feat(nginx): catch-all server_name, add /admin/ route, HTTP-only with HTTPS stub"
```

---

## Task 3: Update docker-compose.yml (Named Backup Volume)

**Why:** Replace `./backups` bind mount with a named volume `backups_data`. Named volumes persist across restarts without needing the directory to exist. Also mount the volume in `backend` so the backup toggle API can write the flag file.

**Files:**
- Modify: `Server Side/docker-compose.yml`

- [ ] **Step 1: Add backups_data to top-level volumes section**

In `Server Side/docker-compose.yml`, find the `volumes:` section at the bottom and add `backups_data:`:

```yaml
volumes:
  mysql_data:
  mosquitto_data:
  mosquitto_log:
  influxdb_data:
  letsencrypt:
  certbot_webroot:
  backups_data:
```

- [ ] **Step 2: Update mysql-backup service volumes**

In the `mysql-backup` service, change the volumes entry from:
```yaml
    volumes:
      - ./backups:/backups
```
to:
```yaml
    volumes:
      - backups_data:/backups
```

- [ ] **Step 3: Add toggle flag check to mysql-backup entrypoint**

In the `mysql-backup` service, replace the `entrypoint:` block:

```yaml
    entrypoint: >
      bash -c "
        echo 'WattWise backup service started';
        while true; do
          sleep 86400;
          if [ -f /backups/.backup_disabled ]; then
            echo 'Auto-backup disabled by admin flag — skipping';
          else
            BACKUP_FILE=/backups/wattwise-$$(date +%Y%m%d-%H%M%S).sql.gz;
            mysqldump -h mysql -u$$MYSQL_USER -p$$MYSQL_PASSWORD $$MYSQL_DATABASE | gzip > $$BACKUP_FILE;
            echo \"Backup created: $$BACKUP_FILE\";
            find /backups -name '*.sql.gz' -mtime +30 -delete;
            echo 'Old backups (>30 days) cleaned';
          fi;
        done
      "
```

- [ ] **Step 4: Add backups_data volume to backend service**

In the `backend` service, add the volumes key (it currently has none). Add after the `depends_on` block:

```yaml
    volumes:
      - backups_data:/backups
```

- [ ] **Step 5: Verify the final docker-compose.yml is valid**

```bash
cd "Server Side"
docker compose config --quiet && echo "VALID" || echo "INVALID"
```

Expected: `VALID`

- [ ] **Step 6: Commit**

```bash
git add "Server Side/docker-compose.yml"
git commit -m "feat(compose): named backups_data volume, backup toggle flag, mount in backend"
```

---

## Task 4: Create docker-compose.production.yml

**Why `ports: []` is NOT used:** Docker Compose merges (appends) lists across files — it cannot clear the base file's ports via an override. Instead, the DigitalOcean external firewall (applied at the network level before traffic reaches the droplet) is the correct mechanism for blocking ports 3307 and 8086 from public access.

**What this file does:** Acts as the production signal (you run a different command on DO vs. dev) and is the right place to add future prod-only services (certbot, monitoring).

**Files:**
- Create: `Server Side/docker-compose.production.yml`

- [ ] **Step 1: Create the production override file**

Create `Server Side/docker-compose.production.yml` with:

```yaml
# WattWise — DigitalOcean Production Override
# ============================================
# Usage:
#   docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
#
# Port security note:
#   MySQL (3307) and InfluxDB (8086) are exposed in the base docker-compose.yml
#   for developer convenience (direct DB access from laptop tools).
#   On DigitalOcean, block these ports at the DO external firewall level —
#   do NOT add 3307 or 8086 as inbound rules. The firewall blocks them before
#   they reach the droplet, regardless of docker-compose port bindings.
#
# Required DO firewall inbound rules:
#   TCP 22   — SSH
#   TCP 80   — nginx (web, API, /admin, MQTT WebSocket)
#   TCP 1883 — MQTT direct TCP from RPi
#   (all others: no inbound rule = blocked)
#
# To add HTTPS later:
#   1. Uncomment the certbot service below
#   2. Uncomment the HTTPS server block in nginx.conf
#   3. Add TCP 443 to DO firewall inbound rules

services: {}

# Uncomment when adding certbot for HTTPS:
# services:
#   certbot:
#     image: certbot/certbot
#     volumes:
#       - letsencrypt:/etc/letsencrypt
#       - certbot_webroot:/var/www/certbot
#     entrypoint: >
#       sh -c "trap exit TERM; while :; do
#         certbot renew --webroot -w /var/www/certbot --quiet;
#         sleep 12h & wait $${!};
#       done"
```

- [ ] **Step 2: Verify the combined config is valid**

```bash
cd "Server Side"
docker compose -f docker-compose.yml -f docker-compose.production.yml config --quiet && echo "VALID"
```

Expected: `VALID`

- [ ] **Step 3: Commit**

```bash
git add "Server Side/docker-compose.production.yml"
git commit -m "feat(compose): add production override file with DO firewall guidance and HTTPS stub"
```

---

## Task 5: Update Backend Dockerfile

**Why:** The backup download endpoint runs `mysqldump` via subprocess. The `default-mysql-client` package provides the `mysqldump` binary.

**Files:**
- Modify: `Server Side/backend/Dockerfile`

- [ ] **Step 1: Add default-mysql-client to apt install**

In `Server Side/backend/Dockerfile`, change the `apt-get install` line from:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc default-libmysqlclient-dev pkg-config curl \
    && rm -rf /var/lib/apt/lists/*
```

to:

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc default-libmysqlclient-dev default-mysql-client pkg-config curl \
    && rm -rf /var/lib/apt/lists/*
```

- [ ] **Step 2: Commit**

```bash
git add "Server Side/backend/Dockerfile"
git commit -m "feat(backend): add default-mysql-client for mysqldump in backup endpoint"
```

---

## Task 6: Create backup.py Router

**Files:**
- Create: `Server Side/backend/app/routers/backup.py`
- Test: `Server Side/backend/tests/test_backup.py`

- [ ] **Step 1: Write the failing tests first**

Create `Server Side/backend/tests/test_backup.py`:

```python
"""Tests for the admin backup router."""
import os
import gzip
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient


# ── Helpers ────────────────────────────────────────────────────

def _admin_state(app):
    """Inject admin user into request state for all requests."""
    from fastapi import Request

    @app.middleware("http")
    async def _inject_admin(request: Request, call_next):
        request.state.user_id = 1
        request.state.is_admin = True
        return await call_next(request)


# ── Tests ───────────────────────────────────────────────────────

class TestBackupSettings:
    def test_get_settings_returns_enabled_when_no_flag(self, tmp_path):
        """When .backup_disabled does not exist, enabled=True."""
        from app.routers.backup import _backup_settings
        result = _backup_settings(backups_dir=str(tmp_path))
        assert result["enabled"] is True
        assert result["backup_count"] == 0
        assert result["last_backup_file"] is None

    def test_get_settings_returns_disabled_when_flag_exists(self, tmp_path):
        """When .backup_disabled exists, enabled=False."""
        (tmp_path / ".backup_disabled").touch()
        from app.routers.backup import _backup_settings
        result = _backup_settings(backups_dir=str(tmp_path))
        assert result["enabled"] is False

    def test_get_settings_counts_sql_gz_files(self, tmp_path):
        """backup_count reflects number of .sql.gz files."""
        (tmp_path / "wattwise-20260101.sql.gz").write_bytes(b"fake")
        (tmp_path / "wattwise-20260102.sql.gz").write_bytes(b"fake")
        from app.routers.backup import _backup_settings
        result = _backup_settings(backups_dir=str(tmp_path))
        assert result["backup_count"] == 2

    def test_get_settings_reports_last_backup(self, tmp_path):
        """last_backup_file is the most recently modified .sql.gz."""
        import time
        f1 = tmp_path / "wattwise-20260101.sql.gz"
        f1.write_bytes(b"a")
        time.sleep(0.01)
        f2 = tmp_path / "wattwise-20260102.sql.gz"
        f2.write_bytes(b"b")
        from app.routers.backup import _backup_settings
        result = _backup_settings(backups_dir=str(tmp_path))
        assert result["last_backup_file"] == "wattwise-20260102.sql.gz"


class TestBackupToggle:
    def test_enable_backup_removes_flag_file(self, tmp_path):
        """Setting enabled=True removes .backup_disabled flag."""
        flag = tmp_path / ".backup_disabled"
        flag.touch()
        from app.routers.backup import _set_backup_enabled
        _set_backup_enabled(enabled=True, backups_dir=str(tmp_path))
        assert not flag.exists()

    def test_disable_backup_creates_flag_file(self, tmp_path):
        """Setting enabled=False creates .backup_disabled flag."""
        from app.routers.backup import _set_backup_enabled
        _set_backup_enabled(enabled=False, backups_dir=str(tmp_path))
        assert (tmp_path / ".backup_disabled").exists()

    def test_enable_when_already_enabled_is_idempotent(self, tmp_path):
        """Enabling when already enabled causes no error."""
        from app.routers.backup import _set_backup_enabled
        _set_backup_enabled(enabled=True, backups_dir=str(tmp_path))  # no flag exists
        _set_backup_enabled(enabled=True, backups_dir=str(tmp_path))  # still no flag
        assert not (tmp_path / ".backup_disabled").exists()


class TestBackupList:
    def test_list_returns_files_sorted_newest_first(self, tmp_path):
        """list endpoint returns .sql.gz files sorted newest first."""
        import time
        f1 = tmp_path / "wattwise-20260101.sql.gz"
        f1.write_bytes(b"aaaa")
        time.sleep(0.01)
        f2 = tmp_path / "wattwise-20260102.sql.gz"
        f2.write_bytes(b"bb")
        from app.routers.backup import _list_backups
        result = _list_backups(backups_dir=str(tmp_path))
        assert result[0]["name"] == "wattwise-20260102.sql.gz"
        assert result[1]["name"] == "wattwise-20260101.sql.gz"
        assert result[0]["size_bytes"] == 2
        assert result[1]["size_bytes"] == 4
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd "Server Side/backend"
python -m pytest tests/test_backup.py -v 2>&1 | head -30
```

Expected: `ImportError` or `ModuleNotFoundError` for `app.routers.backup` — the module doesn't exist yet.

- [ ] **Step 3: Create the backup router**

Create `Server Side/backend/app/routers/backup.py`:

```python
"""WattWise — Admin Backup Router.

Provides on-demand mysqldump download and auto-backup toggle.
The toggle works via a flag file /backups/.backup_disabled in the
backups_data Docker volume shared with the mysql-backup service.

Endpoints (all require is_admin=True):
  GET  /api/admin/backup/settings   — current enabled state + stats
  POST /api/admin/backup/settings   — toggle enabled/disabled
  GET  /api/admin/backup/list       — list all .sql.gz archives
  GET  /api/admin/backup/download   — stream a fresh mysqldump as .sql.gz
"""

import asyncio
import gzip
import io
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger("backup")
router = APIRouter(prefix="/api/admin/backup", tags=["Backup"])

BACKUPS_DIR = "/backups"


# ── Auth helper (same pattern as admin.py) ────────────────────

def _require_admin(request: Request) -> int:
    user_id = getattr(request.state, "user_id", None)
    is_admin = getattr(request.state, "is_admin", False)
    if not user_id or not is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user_id


# ── Pure helper functions (no FastAPI deps — testable standalone) ─

def _backup_settings(backups_dir: str = BACKUPS_DIR) -> dict:
    """Return backup status dict. Uses backups_dir for testability."""
    d = Path(backups_dir)
    enabled = not (d / ".backup_disabled").exists()

    gz_files = sorted(d.glob("*.sql.gz"), key=lambda f: f.stat().st_mtime, reverse=True)
    last_file = gz_files[0] if gz_files else None

    return {
        "enabled": enabled,
        "backup_count": len(gz_files),
        "last_backup_file": last_file.name if last_file else None,
        "last_backup_size_mb": round(last_file.stat().st_size / 1_048_576, 2) if last_file else None,
    }


def _set_backup_enabled(enabled: bool, backups_dir: str = BACKUPS_DIR) -> None:
    """Create or remove the .backup_disabled flag file."""
    flag = Path(backups_dir) / ".backup_disabled"
    if enabled:
        flag.unlink(missing_ok=True)
    else:
        flag.touch()


def _list_backups(backups_dir: str = BACKUPS_DIR) -> list[dict]:
    """Return list of backup files sorted newest first."""
    d = Path(backups_dir)
    gz_files = sorted(d.glob("*.sql.gz"), key=lambda f: f.stat().st_mtime, reverse=True)
    return [
        {
            "name": f.name,
            "size_bytes": f.stat().st_size,
            "size_mb": round(f.stat().st_size / 1_048_576, 2),
            "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }
        for f in gz_files
    ]


def _run_mysqldump_sync() -> bytes:
    """Run mysqldump and return gzipped bytes. Runs in a thread via asyncio.to_thread."""
    # Parse connection details from DATABASE_URL
    # URL format: mysql+aiomysql://user:pass@host:port/database
    raw_url = settings.DATABASE_URL.replace("mysql+aiomysql://", "mysql://")
    parsed = urlparse(raw_url)
    db_user = parsed.username
    db_host = parsed.hostname or "mysql"
    db_name = parsed.path.lstrip("/")
    db_pass = parsed.password or ""

    result = subprocess.run(
        ["mysqldump", "-h", db_host, "-u", db_user, db_name],
        env={**os.environ, "MYSQL_PWD": db_pass},
        capture_output=True,
    )
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"mysqldump failed: {err}")

    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb") as gz:
        gz.write(result.stdout)
    return buf.getvalue()


# ── Request/Response schemas ──────────────────────────────────

class BackupSettingsUpdate(BaseModel):
    enabled: bool


# ── Endpoints ────────────────────────────────────────────────

@router.get("/settings")
async def get_backup_settings(request: Request):
    """Return current auto-backup state and last backup stats."""
    _require_admin(request)
    d = Path(BACKUPS_DIR)
    if not d.exists():
        return {
            "enabled": False,
            "backup_count": 0,
            "last_backup_file": None,
            "last_backup_size_mb": None,
            "warning": "Backup volume not mounted — run with docker-compose.production.yml",
        }
    return _backup_settings()


@router.post("/settings")
async def update_backup_settings(body: BackupSettingsUpdate, request: Request):
    """Enable or disable the automatic daily backup."""
    _require_admin(request)
    d = Path(BACKUPS_DIR)
    if not d.exists():
        raise HTTPException(
            status_code=503,
            detail="Backup volume not mounted — run with docker-compose.production.yml",
        )
    _set_backup_enabled(body.enabled)
    logger.info("Auto-backup %s by admin user_id=%s", "enabled" if body.enabled else "disabled",
                request.state.user_id)
    return {"enabled": body.enabled, "message": f"Auto-backup {'enabled' if body.enabled else 'disabled'}"}


@router.get("/list")
async def list_backups(request: Request):
    """List all backup archives with name, size, and timestamp."""
    _require_admin(request)
    d = Path(BACKUPS_DIR)
    if not d.exists():
        return []
    return _list_backups()


@router.get("/download")
async def download_backup(request: Request):
    """Run a fresh mysqldump and stream it as a .sql.gz download.

    Runs in a thread pool so it does not block the async event loop.
    """
    _require_admin(request)
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    filename = f"wattwise-ondemand-{ts}.sql.gz"

    try:
        data = await asyncio.to_thread(_run_mysqldump_sync)
    except RuntimeError as exc:
        logger.error("On-demand backup failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/gzip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
```

- [ ] **Step 4: Run the tests — they should pass now**

```bash
cd "Server Side/backend"
python -m pytest tests/test_backup.py -v
```

Expected output:
```
tests/test_backup.py::TestBackupSettings::test_get_settings_returns_enabled_when_no_flag PASSED
tests/test_backup.py::TestBackupSettings::test_get_settings_returns_disabled_when_flag_exists PASSED
tests/test_backup.py::TestBackupSettings::test_get_settings_counts_sql_gz_files PASSED
tests/test_backup.py::TestBackupSettings::test_get_settings_reports_last_backup PASSED
tests/test_backup.py::TestBackupToggle::test_enable_backup_removes_flag_file PASSED
tests/test_backup.py::TestBackupToggle::test_disable_backup_creates_flag_file PASSED
tests/test_backup.py::TestBackupToggle::test_enable_when_already_enabled_is_idempotent PASSED
tests/test_backup.py::TestBackupList::test_list_returns_files_sorted_newest_first PASSED

8 passed
```

- [ ] **Step 5: Commit**

```bash
git add "Server Side/backend/app/routers/backup.py" "Server Side/backend/tests/test_backup.py"
git commit -m "feat(backend): add admin backup router with toggle and on-demand download"
```

---

## Task 7: Register Backup Router in main.py

**Files:**
- Modify: `Server Side/backend/app/main.py:29` (import line) and `Server Side/backend/app/main.py:267` (include_router line)

- [ ] **Step 1: Add import**

In `Server Side/backend/app/main.py`, find line 29:
```python
from app.routers import auth, devices, readings, goals, decisions, notifications, analysis, admin, export
```
Change to:
```python
from app.routers import auth, devices, readings, goals, decisions, notifications, analysis, admin, export, backup
```

- [ ] **Step 2: Register router**

In `Server Side/backend/app/main.py`, find the routers section (after line 267):
```python
app.include_router(export.router)
```
Add after it:
```python
app.include_router(backup.router)
```

- [ ] **Step 3: Commit**

```bash
git add "Server Side/backend/app/main.py"
git commit -m "feat(backend): register backup router"
```

---

## Task 8: Add Backup Methods to api-client.js

**Why:** `AdminApiClient` has no generic `get()`/`post()` — it uses named methods. Adding named backup methods follows the existing pattern.

**Files:**
- Modify: `Server Side/owner-frontend/static/js/api-client.js`

- [ ] **Step 1: Add backup methods to AdminApiClient**

In `Server Side/owner-frontend/static/js/api-client.js`, add these three methods inside the `AdminApiClient` class, after the `sendNotification` method (before the closing `}`):

```javascript
  /** @returns {Promise<{enabled: boolean, backup_count: number, last_backup_file: string|null, last_backup_size_mb: number|null, warning?: string}>} */
  getBackupSettings() {
    return this.request("/admin/backup/settings");
  }

  /** @param {{enabled: boolean}} payload @returns {Promise<{enabled: boolean, message: string}>} */
  setBackupSettings(payload) {
    return this.request("/admin/backup/settings", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  }

  /** @returns {Promise<Array<{name: string, size_bytes: number, size_mb: number, created_at: string}>>} */
  listBackups() {
    return this.request("/admin/backup/list");
  }
```

- [ ] **Step 2: Commit**

```bash
git add "Server Side/owner-frontend/static/js/api-client.js"
git commit -m "feat(admin): add backup API methods to AdminApiClient"
```

---

## Task 9: Add Backup Section to Admin Dashboard HTML + JS

**Notes on existing patterns:**
- Section IDs use `s-` prefix: `s-dashboard`, `s-users`, etc. (from `document.getElementById(\`s-${section}\`)` in `setupNavigation`)
- The `loaders` object at line 253 of `app.js` maps section names → load functions
- `showToast(msg, isError)` is the existing toast helper

**Files:**
- Modify: `Server Side/owner-frontend/static/index.html`
- Modify: `Server Side/owner-frontend/static/js/app.js`

- [ ] **Step 1: Add Backup nav item to sidebar in index.html**

In `Server Side/owner-frontend/static/index.html` line 79, find:
```html
    <a href="#" data-section="decisions">🎯 Decisions</a>
```
Add after it:
```html
    <a href="#" data-section="backup">💾 Backup</a>
```

- [ ] **Step 2: Add backup section HTML to index.html**

In `Server Side/owner-frontend/static/index.html`, find the line just before `<script type="module" src="js/app.js"></script>` (line 159, now shifted by 1 due to the nav item). Add the backup section HTML:

```html
<!-- ── Backup Section ──────────────────────────────────── -->
<section id="s-backup">
  <div class="topbar"><h2>Backup Management</h2></div>

  <div class="grid2" style="margin-bottom:20px">
    <div class="card">
      <div class="card-title">Auto-Backup (Daily)</div>
      <div style="display:flex;align-items:center;gap:16px;margin-bottom:12px">
        <label style="display:flex;align-items:center;gap:10px;cursor:pointer">
          <input type="checkbox" id="backup-toggle" style="width:auto">
          <span id="backup-toggle-label" style="font-size:.875rem;color:var(--muted)">Loading…</span>
        </label>
      </div>
      <div id="backup-stats" style="font-size:.8rem;color:var(--muted)">—</div>
    </div>
    <div class="card">
      <div class="card-title">On-Demand Backup</div>
      <p style="font-size:.82rem;color:var(--muted);margin-bottom:14px">Download a fresh mysqldump of all WattWise data as a compressed .sql.gz archive.</p>
      <button class="btn btn-primary" id="backup-download-btn">Download Backup Now</button>
      <div id="backup-download-status" style="margin-top:10px;font-size:.8rem;color:var(--muted)"></div>
    </div>
  </div>

  <div class="card">
    <div class="card-title">Stored Backups</div>
    <table>
      <thead><tr><th>Filename</th><th>Size</th><th>Created</th></tr></thead>
      <tbody id="backup-list-body"><tr><td colspan="3" style="color:var(--muted)">Loading…</td></tr></tbody>
    </table>
  </div>
</section>
```

- [ ] **Step 3: Add backup JS to app.js**

In `Server Side/owner-frontend/static/js/app.js`, append the following at the very end of the file:

```javascript
// ── Backup Section ────────────────────────────────────────────

async function loadBackupSection() {
  try {
    const s = await api.getBackupSettings();
    const toggle = document.getElementById("backup-toggle");
    const label = document.getElementById("backup-toggle-label");
    const stats = document.getElementById("backup-stats");
    toggle.checked = s.enabled;
    label.textContent = s.enabled ? "Enabled" : "Disabled";
    const lastFile = s.last_backup_file
      ? `Last: ${s.last_backup_file} (${s.last_backup_size_mb ?? "?"} MB)`
      : "No backups yet";
    stats.textContent = `${s.backup_count} archive(s) stored. ${lastFile}`;
    if (s.warning) stats.textContent += ` — ${s.warning}`;

    // Remove old listener before adding new one to avoid stacking on repeated nav
    const newToggle = toggle.cloneNode(true);
    newToggle.checked = s.enabled;
    toggle.parentNode.replaceChild(newToggle, toggle);
    newToggle.addEventListener("change", async () => {
      try {
        const res = await api.setBackupSettings({ enabled: newToggle.checked });
        label.textContent = res.enabled ? "Enabled" : "Disabled";
        showToast(res.message);
      } catch (e) {
        showToast(`Failed: ${e.message}`, true);
        newToggle.checked = !newToggle.checked;
      }
    });
  } catch (e) {
    document.getElementById("backup-stats").textContent = `Error: ${e.message}`;
  }

  try {
    const files = await api.listBackups();
    const tbody = document.getElementById("backup-list-body");
    if (!files.length) {
      tbody.innerHTML = '<tr><td colspan="3" style="color:var(--muted)">No backups stored yet.</td></tr>';
      return;
    }
    tbody.innerHTML = files.map(f => `
      <tr>
        <td style="font-family:monospace;font-size:.78rem">${sanitize(f.name)}</td>
        <td>${f.size_mb} MB</td>
        <td>${new Date(f.created_at).toLocaleString()}</td>
      </tr>
    `).join("");
  } catch (e) {
    document.getElementById("backup-list-body").innerHTML =
      `<tr><td colspan="3" style="color:var(--muted)">Error: ${sanitize(e.message)}</td></tr>`;
  }

  document.getElementById("backup-download-btn").onclick = downloadBackupNow;
}

async function downloadBackupNow() {
  const btn = document.getElementById("backup-download-btn");
  const status = document.getElementById("backup-download-status");
  btn.disabled = true;
  btn.textContent = "Generating…";
  status.textContent = "Running mysqldump — this may take a moment…";
  try {
    const res = await fetch("/api/admin/backup/download", {
      headers: { Authorization: `Bearer ${api.token}` },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      throw new Error(err.detail || "Download failed");
    }
    const blob = await res.blob();
    const cd = res.headers.get("Content-Disposition") || "";
    const match = cd.match(/filename="?([^"]+)"?/);
    const fname = match ? match[1] : `wattwise-backup-${Date.now()}.sql.gz`;
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = fname;
    a.click();
    URL.revokeObjectURL(url);
    status.textContent = `Downloaded: ${sanitize(fname)}`;
    showToast("Backup downloaded successfully");
    loadBackupSection();
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
    showToast(`Backup failed: ${e.message}`, true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Download Backup Now";
  }
}
```

- [ ] **Step 4: Add backup to the loaders object in app.js**

In `Server Side/owner-frontend/static/js/app.js`, find lines 253–259:
```javascript
const loaders = {
  dashboard: loadDashboard,
  users: loadUsers,
  rankings: loadRankings,
  analytics: loadAnalytics,
  decisions: loadDecisions,
};
```
Change to:
```javascript
const loaders = {
  dashboard: loadDashboard,
  users: loadUsers,
  rankings: loadRankings,
  analytics: loadAnalytics,
  decisions: loadDecisions,
  backup: loadBackupSection,
};
```

- [ ] **Step 5: Commit**

```bash
git add "Server Side/owner-frontend/static/index.html" \
        "Server Side/owner-frontend/static/js/app.js"
git commit -m "feat(admin): add backup management section with toggle and on-demand download"
```

---

## Task 10: Update .env.production.template

**Files:**
- Modify: `Server Side/.env.production.template`

- [ ] **Step 1: Replace the file with the DO-ready template**

Replace the entire contents of `Server Side/.env.production.template` with:

```bash
# WattWise — Production Environment Template for DigitalOcean
# ===========================================================
# 1. Copy this file:  cp .env.production.template .env
# 2. Replace every REPLACE_* value below
# 3. Never commit the filled-in .env to git
#
# Generate SECRET_KEY with:
#   python3 -c "import secrets; print(secrets.token_urlsafe(64))"

# ── MySQL ──────────────────────────────────────────────────────
MYSQL_ROOT_PASSWORD=REPLACE_STRONG_ROOT_PASSWORD
MYSQL_DATABASE=wattwise_db
MYSQL_USER=wattwise_app
MYSQL_PASSWORD=REPLACE_STRONG_APP_PASSWORD
DATABASE_URL=mysql+aiomysql://wattwise_app:REPLACE_STRONG_APP_PASSWORD@mysql:3306/wattwise_db

# ── InfluxDB ───────────────────────────────────────────────────
INFLUX_HOST=influxdb
INFLUX_PORT=8086
INFLUX_DB=wattwise_energy
INFLUX_USER=wattwise_influx
INFLUX_PASS=REPLACE_STRONG_INFLUX_PASSWORD
INFLUX_PROTOCOL=http

# ── MQTT ───────────────────────────────────────────────────────
MQTT_BROKER_HOST=mosquitto
MQTT_BROKER_PORT=1883
MQTT_TOPIC_PREFIX=wattwise/homes

# ── Backend Security ───────────────────────────────────────────
# STRICT_SECURITY=true will refuse to start if SECRET_KEY contains 'changeme'
SECRET_KEY=REPLACE_WITH_64_CHAR_RANDOM_STRING
ACCESS_TOKEN_EXPIRE_MINUTES=10080
STRICT_SECURITY=true
LOGIN_RATE_LIMIT_WINDOW_SECONDS=300
LOGIN_RATE_LIMIT_MAX_ATTEMPTS=10

# ── Admin Account ──────────────────────────────────────────────
ADMIN_EMAIL=REPLACE_YOUR_ADMIN_EMAIL
ADMIN_PASSWORD=REPLACE_STRONG_ADMIN_PASSWORD

# ── CORS — replace YOUR_DROPLET_IP with actual reserved IP ─────
# Add your domain here too once it points to the droplet:
#   ALLOWED_ORIGINS=http://YOUR_DROPLET_IP,https://yourdomain.com
ALLOWED_ORIGINS=http://YOUR_DROPLET_IP

# ── UK Energy Tariffs (£/kWh) ──────────────────────────────────
ENERGY_STANDARD_PRICE_PER_KWH=0.2700
ENERGY_PEAK_PRICE_PER_KWH=0.3200
ENERGY_OFFPEAK_PRICE_PER_KWH=0.1300
ENERGY_PEAK_START_HOUR=16
ENERGY_PEAK_END_HOUR=19

# ── Alert Thresholds ───────────────────────────────────────────
ENERGY_DAILY_WARNING_KWH=15
ENERGY_DAILY_HIGH_KWH=25
ENERGY_DEVICE_STANDBY_WATTS=5
ENERGY_USAGE_SPIKE_MULTIPLIER=2.0
DECISION_MEASURE_WINDOW_HOURS=2

# ── Expo Push Notifications ────────────────────────────────────
EXPO_PUSH_URL=https://exp.host/--/api/v2/push/send

# ── Weekly Email Reports (optional — leave SMTP_USER blank to disable) ─
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=WattWise <noreply@wattwise.local>
```

- [ ] **Step 2: Commit**

```bash
git add "Server Side/.env.production.template"
git commit -m "docs: update production .env template for DigitalOcean deployment"
```

---

## Task 11: Update RPi Publisher Config

**Files:**
- Modify: `Sensing Layer/rpi_publisher_config.yaml`

- [ ] **Step 1: Add DigitalOcean connection options**

In `Sensing Layer/rpi_publisher_config.yaml`, replace the `mqtt:` section:

```yaml
# ── WattWise Cloud MQTT Broker ────────────────────────────────────────────────
# Choose ONE connection method and comment out the other.
#
# Option A — WebSocket via nginx on port 80 (same port as the web app):
#   Works through most firewalls. Replace YOUR_DROPLET_IP with your DO reserved IP.
mqtt:
  host: "YOUR_DROPLET_IP"
  port: 80
  transport: "websockets"
  ws_path: "/mqtt"
  username: ""
  password: ""
  tls: false

# Option B — Direct MQTT TCP on port 1883 (simpler protocol):
#   Uncomment this block and comment out Option A to use it.
# mqtt:
#   host: "YOUR_DROPLET_IP"
#   port: 1883
#   transport: "tcp"
#   username: ""
#   password: ""
#   tls: false

# ── Localhost / dev (original Cloudflare config preserved as reference) ───────
# mqtt:
#   host: "talk2futurebuildings.systems"
#   port: 443
#   transport: "websockets"
#   ws_path: "/mqtt"
#   tls: false
```

- [ ] **Step 2: Commit**

```bash
git add "Sensing Layer/rpi_publisher_config.yaml"
git commit -m "config(rpi): add DigitalOcean MQTT connection options (WebSocket + TCP)"
```

---

## Task 12: Create deploy.sh

**Files:**
- Create: `Server Side/scripts/deploy.sh`

- [ ] **Step 1: Create the deployment script**

Create `Server Side/scripts/deploy.sh`:

```bash
#!/usr/bin/env bash
# =============================================================================
# WattWise — DigitalOcean Droplet Setup Script
# =============================================================================
# Run this ONCE on a fresh Ubuntu 22.04 droplet as root or sudo user.
# After this script completes:
#   1. Edit Server Side/.env with your actual credentials
#   2. Run:  cd "Server Side" && docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build
#
# Usage (from repo root on the droplet):
#   bash "Server Side/scripts/deploy.sh"
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVER_DIR="$(dirname "$SCRIPT_DIR")"

echo "===> WattWise DigitalOcean Setup"
echo "      Server directory: $SERVER_DIR"
echo ""

# ── 1. Install Docker ─────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "---> Installing Docker..."
  apt-get update -qq
  apt-get install -y ca-certificates curl gnupg lsb-release
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
    | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
  chmod a+r /etc/apt/keyrings/docker.gpg
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) stable" \
    | tee /etc/apt/sources.list.d/docker.list > /dev/null
  apt-get update -qq
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
  echo "    Docker installed: $(docker --version)"
else
  echo "---> Docker already installed: $(docker --version)"
fi

# ── 2. Install git (if missing) ───────────────────────────────────────────────
if ! command -v git &>/dev/null; then
  apt-get install -y git
fi

# ── 3. Set up .env from template ─────────────────────────────────────────────
ENV_FILE="$SERVER_DIR/.env"
TEMPLATE_FILE="$SERVER_DIR/.env.production.template"

if [ -f "$ENV_FILE" ]; then
  echo "---> .env already exists — skipping template copy. Review it before starting."
else
  if [ -f "$TEMPLATE_FILE" ]; then
    cp "$TEMPLATE_FILE" "$ENV_FILE"
    echo "---> Copied .env.production.template → .env"
    echo "     !! IMPORTANT: Edit $ENV_FILE and replace all REPLACE_* values before starting !!"
  else
    echo "    WARNING: $TEMPLATE_FILE not found. Create $ENV_FILE manually."
  fi
fi

# ── 4. Generate a SECRET_KEY suggestion ───────────────────────────────────────
echo ""
echo "---> Suggested SECRET_KEY (copy into .env):"
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(64))"

# ── 5. Enable Docker service ──────────────────────────────────────────────────
systemctl enable docker
systemctl start docker
echo "---> Docker service enabled and started"

# ── 6. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo " Setup complete. Next steps:"
echo ""
echo " 1. Edit Server Side/.env — replace ALL REPLACE_* values"
echo "    especially: SECRET_KEY, MYSQL_ROOT_PASSWORD,"
echo "                MYSQL_PASSWORD, INFLUX_PASS, ADMIN_PASSWORD"
echo "    and set:    ALLOWED_ORIGINS=http://YOUR_DROPLET_IP"
echo ""
echo " 2. Configure DigitalOcean Firewall (inbound rules):"
echo "    - TCP 22   (SSH)"
echo "    - TCP 80   (HTTP — nginx, API, /admin, MQTT WebSocket)"
echo "    - TCP 1883 (MQTT TCP direct from RPi)"
echo ""
echo " 3. Start the stack:"
echo "    cd \"Server Side\""
echo "    docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build"
echo ""
echo " 4. Verify:"
echo "    docker compose ps"
echo "    curl http://YOUR_DROPLET_IP/health"
echo "    curl http://YOUR_DROPLET_IP/admin/   (admin dashboard)"
echo ""
echo " 5. Update RPi publisher config:"
echo "    Set mqtt.host = YOUR_DROPLET_IP in rpi_publisher_config.yaml"
echo "============================================================"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x "Server Side/scripts/deploy.sh"
```

- [ ] **Step 3: Commit**

```bash
git add "Server Side/scripts/deploy.sh"
git commit -m "feat(deploy): add DigitalOcean one-shot setup script with firewall guide"
```

---

## Task 13: Smoke Test on Laptop

Verify laptop dev still works unchanged before declaring done.

- [ ] **Step 1: Start the dev stack**

```bash
cd "Server Side"
docker compose up -d --build 2>&1 | tail -20
```

- [ ] **Step 2: Wait for healthy status**

```bash
docker compose ps
```

Expected: All services show `healthy` or `running`. mysql may take 30–60s to initialise.

- [ ] **Step 3: Test all routes**

```bash
curl -s http://localhost/health
# Expected: {"status":"ok"}

curl -s -o /dev/null -w "%{http_code}" http://localhost/
# Expected: 200

curl -s -o /dev/null -w "%{http_code}" http://localhost/admin/
# Expected: 200

curl -s -o /dev/null -w "%{http_code}" http://localhost/api/auth/login \
  -X POST -H "Content-Type: application/json" \
  -d '{"email":"test@x.com","password":"wrong"}'
# Expected: 401 (not 502/504 — backend is reachable)
```

- [ ] **Step 4: Test backup API returns degraded warning on dev (no production volume)**

```bash
# Login first to get token
TOKEN=$(curl -s -X POST http://localhost/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@wattwise.co.uk","password":"wattwise_admin"}' | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))")

curl -s -H "Authorization: Bearer $TOKEN" http://localhost/api/admin/backup/settings
# Expected: {"enabled":false,...,"warning":"Backup volume not mounted — run with docker-compose.production.yml"}
```

- [ ] **Step 5: Run backend unit tests**

```bash
cd "Server Side/backend"
python -m pytest tests/test_backup.py -v
# Expected: 8 passed
```

- [ ] **Step 6: Commit final state if any cleanup needed**

```bash
cd "Server Side"
docker compose down
git status
# If clean: nothing to commit
```

---

## DigitalOcean Deployment Checklist (Post-plan reference)

Once the droplet is created and the repo is cloned:

```bash
# On the droplet:
git clone <repo-url>
cd WattWise
bash "Server Side/scripts/deploy.sh"

# Fill in .env:
nano "Server Side/.env"
# Set: SECRET_KEY, MYSQL_ROOT_PASSWORD, MYSQL_PASSWORD, INFLUX_PASS,
#      ADMIN_EMAIL, ADMIN_PASSWORD, ALLOWED_ORIGINS=http://YOUR_DROPLET_IP

# Start production stack:
cd "Server Side"
docker compose -f docker-compose.yml -f docker-compose.production.yml up -d --build

# Verify:
docker compose ps
curl http://YOUR_DROPLET_IP/health
curl http://YOUR_DROPLET_IP/admin/

# Update RPi:
# Edit Sensing Layer/rpi_publisher_config.yaml
# Set mqtt.host = YOUR_DROPLET_IP
```

**DigitalOcean Firewall rules (inbound):**

| Port | Protocol | Source |
|------|----------|--------|
| 22 | TCP | Your IP (SSH) |
| 80 | TCP | All IPv4, All IPv6 |
| 1883 | TCP | All IPv4, All IPv6 |
