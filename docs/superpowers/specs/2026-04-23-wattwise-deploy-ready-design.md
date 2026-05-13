# WattWise Deploy-Ready — Design Spec
**Date:** 2026-04-23  
**Author:** Mr. Suhas Devmane, Cardiff University  
**Approach:** B — Full Deploy-Ready  
**Target:** Local `docker compose up` from repo root → live real-time dashboard

---

## Goal

A single `docker compose up --build` from the repo root produces a fully functional WattWise stack:
- All services start healthy
- Test accounts and devices are seeded automatically
- Dummy data flows every 30 seconds (when the dummy-sender service is uncommented)
- The user dashboard auto-refreshes and shows live energy readings
- Admin can send notifications manually or trigger the smart notification engine on demand
- Automated smart notifications fire on the scheduler (every 2 hours) using the ported energy-calculator logic

---

## Section 1 — Critical Bug Fixes

### 1a. Notifications mark-read endpoint mismatch

**File:** `Server Side/backend/app/routers/notifications.py`

The frontend JavaScript calls `POST /api/notifications/{id}/read` but the router only defines `PATCH`. This silently fails — unread notifications are never marked as read.

**Fix:** Add a `@router.post("/{notification_id}/read")` handler that calls the same logic as the existing PATCH handler. Both methods accepted; no frontend change needed.

### 1b. Mosquitto passwd file missing

**Files:** root `docker-compose.yml`, `Server Side/mosquitto/config/mosquitto.conf`

`Server Side/mosquitto/config/passwd` is untracked and absent. Without it the broker rejects all MQTT connections (backend and RPi publishers).

**Fix:** Add a `mosquitto-init` service in `docker-compose.yml`:
- Image: `eclipse-mosquitto:2`
- `restart: "no"` — runs once then exits
- Writes `passwd` into a named volume `mosquitto_passwd_vol` using `mosquitto_passwd -b -c`
- Creates two entries: `$MQTT_USERNAME / $MQTT_PASSWORD` (backend) and `wattwise_rpi / $MQTT_PI_PASSWORD` (RPi publishers; defaults to a dev value)
- Main `mosquitto` service gains `depends_on: mosquitto-init: service_completed_successfully`
- `mosquitto.conf` password_file path updated to match the volume mount point

### 1c. Device type dropdown missing toaster + airfryer

**File:** `Server Side/user-frontend/static/index.html`

`<select id="dev-type">` is missing `toaster` and `airfryer`. Both exist in the dummy data sender profiles and the appliance scenarios engine, so devices registered with those keys receive smart notifications — but users can't currently register them from the UI.

**Fix:** Add two `<option>` elements to the select.

### 1d. Bill prediction uses today-only cost

**File:** `Server Side/user-frontend/static/index.html` (JS)

`buildBillPrediction(data)` multiplies today's single-day cost by days-in-month. On a light-usage day this wildly underestimates; on a heavy day it overestimates.

**Fix:** In `loadHome()`, after fetching today's data, also fetch `GET /api/readings/{device_id}/daily?days=7` for each device. Sum costs across all devices per day, compute the 7-day average daily cost, then extrapolate to month. Fall back to today's cost if fewer than 2 days of history exist.

### 1e. Custom date range silently does nothing

**Files:**
- `Server Side/backend/app/routers/readings.py` — daily endpoint
- `Server Side/user-frontend/static/index.html` — `loadEnergy()`

`GET /api/readings/{device_id}/daily` only accepts `?days=N`. The frontend custom range inputs (`range-start`, `range-end`) are never passed to the API — clicking "Apply" just re-runs with the previous period.

**Fix:**
1. Add optional `start_date: date` and `end_date: date` query params to the daily endpoint. When present, filter `day_date BETWEEN start_date AND end_date` instead of using the `days` count.
2. In `loadEnergy()`, when `_energyPeriod === 'custom'`, pass `?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` from the input values.

---

## Section 2 — Docker Compose Changes

### 2a. `db-seed` service (one-shot, auto-exits)

Added to root `docker-compose.yml`:

```yaml
db-seed:
  build:
    context: ./Server Side/backend
    dockerfile: Dockerfile
  container_name: wattwise-db-seed
  restart: "no"
  env_file:
    - ./Server Side/.env
  working_dir: /app
  command: python seed_participants.py
  depends_on:
    backend:
      condition: service_healthy
  networks:
    - wattwise-network
```

`seed_participants.py` is already in the backend image. It reads `participants.csv` (also in the backend context). It:
- Upserts the admin account from `.env`
- Creates/syncs all Cardiff participant accounts with hashed passwords
- Creates one home per user (if absent)
- Registers 3–6 devices per home from the `APPLIANCE_KEYS` list
- Exits 0 on success

### 2b. `Dockerfile.dummy` + `dummy-data-sender` service

**New file:** `Dockerfile.dummy` (repo root)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY dummy_data_sender.py .
COPY Server\ Side/backend/participants.csv participants.csv
RUN pip install --no-cache-dir requests
CMD ["python", "dummy_data_sender.py", \
     "--url", "http://wattwise-backend:8000", \
     "--interval", "30", \
     "--no-backfill", \
     "--csv", "participants.csv"]
```

**Change to `dummy_data_sender.py`:** Add `--csv` CLI argument (default: existing hardcoded filename for backwards compat). `load_dummy_accounts()` reads from `args.csv`.

**New service block in `docker-compose.yml` (commented out by default):**

```yaml
  # ── Dummy Data Sender ── uncomment for local testing ─────────
  # dummy-data-sender:
  #   build:
  #     context: .
  #     dockerfile: Dockerfile.dummy
  #   container_name: wattwise-dummy-sender
  #   restart: unless-stopped
  #   depends_on:
  #     backend:
  #       condition: service_healthy
  #     db-seed:
  #       condition: service_completed_successfully
  #   networks:
  #     - wattwise-network
```

Uncomment to activate. Comment out before pushing to production.

---

## Section 3 — User Dashboard Fixes

### 3a. Home tab auto-refresh every 30 seconds

**File:** `Server Side/user-frontend/static/index.html` (JS)

Add a module-level `_activeSection = 'home'` variable. Update it in `goSection()`. Add one `setInterval` at startup:

```javascript
setInterval(() => {
  if (_activeSection === 'home' && token) loadHome();
}, 30_000);
```

This means the Home tab silently refreshes every 30s while the user is on it. No refresh occurs on other tabs.

### 3b. Persona chip in topbar

**File:** `Server Side/user-frontend/static/index.html` (JS)

`populatePersonaChip()` currently builds the `colours` map but never sets anything on the DOM. After fetching `/api/analysis/personas`, match `userData.persona_id`, then:

```javascript
const chip = document.getElementById('persona-chip');
chip.textContent = p.name;
chip.style.background = colours[p.name]?.[1] || 'rgba(139,92,246,.15)';
chip.style.color = colours[p.name]?.[0] || '#8b5cf6';
chip.style.display = 'inline-flex';
```

---

## Section 4 — Admin Portal: Smart Notification Trigger

### 4a. New backend endpoint

**File:** `Server Side/backend/app/routers/admin.py`

`POST /api/admin/trigger-smart-notifications-all` — admin only.

Logic (mirrors the old Node.js `checkAndSendNotifications`):
1. Fetch all users with `notifications_enabled=True` and at least one active home
2. For each user, for each home, for each active device:
   - Query today's `DailySummary` from MySQL
   - Fetch room conditions from InfluxDB (temperature, humidity, pressure) — default to 20°C/50%/101.3 if no sensor data
   - Call `calculate_optimization(appliance_key, temp, humidity, pressure, usage_data)`
   - For each alert with priority `critical` or `warning`, call `NotificationEngine.create_notification()` (12h dedup built in)
3. Return `{"users_processed": N, "notifications_created": M, "skipped_dedup": K}`

The `DEDUP_WINDOW_HOURS = 12` constant in `notification_engine.py` ensures the same device alert can't spam the same user within 12 hours — matching the old Node.js deduplication window.

### 4b. Admin portal button

**File:** `Server Side/owner-frontend/static/js/admin.js`

In the Notifications section, add a "🔔 Run Smart Notifications Now" button. On click:
- Calls `POST /api/admin/trigger-smart-notifications-all`
- Shows a toast: `"Smart notifications sent: {M} new, {K} skipped (dedup)"`

---

## Section 5 — End-to-End Data Flow (post-implementation)

```
docker compose up --build
  ├─ mosquitto-init → generates passwd file (once, exits 0)
  ├─ mysql, influxdb, mosquitto start (mosquitto waits for passwd)
  ├─ backend starts → DB tables created
  ├─ db-seed → accounts + homes + devices seeded (once, exits 0)
  ├─ admin-dashboard (:3000 via /admin/), user-dashboard (:3001), nginx (:80) start
  └─ [uncomment dummy-data-sender] → 30s readings via HTTP to /api/readings/

User opens http://localhost in browser or Android app:
  → Logs in with participant credentials (e.g. from participants.csv)
  → Home tab loads instantly, auto-refreshes every 30s
  → Sees live kWh, cost, device breakdown, bill prediction (7-day avg)
  → Notifications appear as scheduler fires (every 2h)
     OR admin clicks "Run Smart Notifications Now" for instant test
  → Admin portal at http://localhost/admin/ for manual broadcasts + smart trigger
```

---

## Files Changed

| File | Change |
|------|--------|
| `Server Side/backend/app/routers/notifications.py` | Add POST alias for mark-read |
| `Server Side/backend/app/routers/readings.py` | Add `start_date`/`end_date` params to daily endpoint |
| `Server Side/backend/app/routers/admin.py` | Add `POST /trigger-smart-notifications-all` |
| `Server Side/user-frontend/static/index.html` | Auto-refresh, persona chip, bill prediction, custom date range, device dropdown |
| `Server Side/owner-frontend/static/js/admin.js` | "Run Smart Notifications Now" button |
| `docker-compose.yml` (root) | Add `mosquitto-init`, `db-seed`, commented `dummy-data-sender` |
| `Dockerfile.dummy` (root, new) | Slim Python image for dummy sender |
| `dummy_data_sender.py` | Add `--csv` CLI arg |
| `Server Side/mosquitto/config/mosquitto.conf` | Update `password_file` path to volume mount |

---

## Out of Scope (Approach B)

- HTTPS / Cloudflare tunnel setup (production only)
- SMTP email weekly reports (no credentials configured)
- Real-time WebSocket push (polling at 30s is sufficient for local testing)
- Raspberry Pi physical deployment and sensor wiring
- Android APK rebuild (existing APK points to production; use browser for local testing)
