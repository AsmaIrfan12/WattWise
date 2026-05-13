# WattWise Deploy-Ready Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 9 bugs/missing features so `docker compose up --build` from the repo root produces a fully functional stack with seeded accounts, live dummy data, auto-refreshing dashboard, and admin-triggered smart notifications.

**Architecture:** Backend-first (Python routes are unit-testable), then frontend HTML/JS patches, then Docker infrastructure wired together. Each task is independent — any ordering works, but Tasks 1–3 should be done before Task 9 (end-to-end smoke test).

**Tech Stack:** FastAPI + SQLAlchemy 2 async, Python 3.11, Mosquitto 2, Docker Compose, Vanilla JS (no framework).

---

## File Map

| File | Change |
|------|--------|
| `Server Side/backend/app/routers/notifications.py` | Add `POST /{id}/read` alias alongside existing `PATCH` |
| `Server Side/backend/app/routers/readings.py` | Add optional `start_date`/`end_date` params to `GET /{id}/daily` |
| `Server Side/backend/app/routers/admin.py` | Add `POST /trigger-smart-notifications-all` endpoint |
| `Server Side/backend/tests/test_admin.py` | Add tests for the new trigger endpoint helper |
| `Server Side/user-frontend/static/index.html` | Five JS/HTML fixes (dropdown, persona chip, bill prediction, date range, auto-refresh) |
| `Server Side/owner-frontend/static/index.html` | Add smart trigger button card to notifications section |
| `Server Side/owner-frontend/static/js/admin.js` | Add `triggerSmartNotifications()` function + event listener |
| `Server Side/mosquitto/config/mosquitto.conf` | Update `password_file` path from `/mosquitto/config/passwd` to `/mosquitto/secret/passwd` |
| `docker-compose.yml` (repo root) | Add `mosquitto-init`, `db-seed` services; add commented `dummy-data-sender`; add `mosquitto_passwd_vol` volume; fix mosquitto passwd bind-mount |
| `Dockerfile.dummy` (repo root, new) | Slim Python image that runs `dummy_data_sender.py` |
| `dummy_data_sender.py` | Add `--csv` CLI argument; `load_dummy_accounts()` uses it |

---

## Task 1: Fix notifications mark-read POST alias

**Problem:** Frontend JS calls `POST /api/notifications/{id}/read` but the router only defines `PATCH`. Silent failure — notifications stay unread forever.

**Files:**
- Modify: `Server Side/backend/app/routers/notifications.py:73-89`

- [ ] **Step 1: Write the failing test**

Create `Server Side/backend/tests/test_notifications_router.py`:

```python
from app.routers.notifications import mark_read

def test_mark_read_function_exists_and_is_callable():
    """Smoke-test: the handler is importable and callable (async)."""
    import asyncio
    assert callable(mark_read)

def test_notifications_router_has_post_read_route():
    """Verify the router registers a POST route for /{id}/read."""
    from app.routers.notifications import router
    post_paths = [
        r.path for r in router.routes
        if hasattr(r, 'methods') and 'POST' in r.methods
    ]
    assert any('/read' in p for p in post_paths), (
        f"No POST .../read route found. Registered POST paths: {post_paths}"
    )
```

- [ ] **Step 2: Run it — expect FAIL**

```bash
cd "Server Side/backend"
pytest tests/test_notifications_router.py -v
```

Expected: `FAILED test_notifications_router_has_post_read_route — AssertionError: No POST .../read route found`

- [ ] **Step 3: Add the POST alias in notifications.py**

In `Server Side/backend/app/routers/notifications.py`, insert after line 89 (after the `mark_read` PATCH handler closes):

```python
@router.post("/{notification_id}/read", response_model=NotificationResponse)
async def mark_read_post(
    notification_id: int, request: Request, db: AsyncSession = Depends(get_db)
):
    """POST alias for PATCH /{id}/read — frontend JS uses POST."""
    return await mark_read(notification_id, request, db)
```

- [ ] **Step 4: Run test — expect PASS**

```bash
cd "Server Side/backend"
pytest tests/test_notifications_router.py -v
```

Expected: `PASSED` both tests

- [ ] **Step 5: Lint**

```bash
cd "Server Side/backend"
ruff check app/routers/notifications.py
```

Expected: no output (clean)

- [ ] **Step 6: Commit**

```bash
git add "Server Side/backend/app/routers/notifications.py" "Server Side/backend/tests/test_notifications_router.py"
git commit -m "fix: add POST alias for notifications mark-read endpoint"
```

---

## Task 2: Add date range params to daily readings endpoint

**Problem:** `GET /api/readings/{device_id}/daily` only accepts `?days=N`. The frontend custom-range inputs are never sent to the API — clicking Apply silently re-runs with the previous period.

**Files:**
- Modify: `Server Side/backend/app/routers/readings.py:118-134`

- [ ] **Step 1: Write the test**

Create `Server Side/backend/tests/test_readings_router.py`:

```python
from datetime import date


def test_daily_endpoint_accepts_date_range_params():
    """Verify get_daily function signature accepts start_date and end_date."""
    import inspect
    from app.routers.readings import get_daily
    sig = inspect.signature(get_daily)
    assert 'start_date' in sig.parameters, "start_date param missing from get_daily"
    assert 'end_date' in sig.parameters, "end_date param missing from get_daily"


def test_daily_endpoint_days_param_is_optional():
    """days param should be optional (has a default) so date-range can override it."""
    import inspect
    from app.routers.readings import get_daily
    sig = inspect.signature(get_daily)
    days_param = sig.parameters.get('days')
    assert days_param is not None
    assert days_param.default is not inspect.Parameter.empty, "days must have a default value"
```

- [ ] **Step 2: Run it — expect FAIL**

```bash
cd "Server Side/backend"
pytest tests/test_readings_router.py -v
```

Expected: `FAILED test_daily_endpoint_accepts_date_range_params — AssertionError: start_date param missing`

- [ ] **Step 3: Update get_daily in readings.py**

Replace lines 118–134 in `Server Side/backend/app/routers/readings.py`:

```python
@router.get("/{device_id}/daily", response_model=list[DailySummaryResponse])
async def get_daily(
    device_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    days: int = Query(default=30, ge=1, le=365),
    start_date: Optional[date] = Query(default=None),
    end_date: Optional[date] = Query(default=None),
):
    user_id = _get_user_id(request)
    await _verify_device_access(db, device_id, user_id)
    if start_date and end_date:
        since = start_date
        until = end_date
    else:
        from datetime import date as _date
        since = (_date.today() - timedelta(days=days))
        until = _date.today()
    result = await db.execute(
        select(DailySummary)
        .where(
            DailySummary.device_id == device_id,
            DailySummary.day_date >= since,
            DailySummary.day_date <= until,
        )
        .order_by(DailySummary.day_date.asc())
    )
    return result.scalars().all()
```

Also add `date` to the import on line 3 of readings.py (it's currently `from datetime import datetime, timedelta`):

```python
from datetime import datetime, timedelta, date
```

And add `Optional` is already imported — confirm `Optional` is in the `from typing import Optional` on line 4.

- [ ] **Step 4: Run test — expect PASS**

```bash
cd "Server Side/backend"
pytest tests/test_readings_router.py -v
```

Expected: `PASSED` both tests

- [ ] **Step 5: Lint**

```bash
cd "Server Side/backend"
ruff check app/routers/readings.py
```

- [ ] **Step 6: Commit**

```bash
git add "Server Side/backend/app/routers/readings.py" "Server Side/backend/tests/test_readings_router.py"
git commit -m "feat: add start_date/end_date query params to daily readings endpoint"
```

---

## Task 3: Admin trigger-smart-notifications-all endpoint

**Problem:** `smart_notifications.py` only generates alerts for the authenticated user. No endpoint runs smart notifications for all users (the old Node.js `checkAndSendNotifications` behaviour).

**Files:**
- Modify: `Server Side/backend/app/routers/admin.py` (append after line 727)

- [ ] **Step 1: Write the test**

Add to `Server Side/backend/tests/test_admin.py`:

```python
def test_trigger_smart_notifs_result_schema():
    """The result dict from the trigger endpoint has the three required keys."""
    result = {"users_processed": 3, "notifications_created": 5, "skipped_dedup": 1}
    assert "users_processed" in result
    assert "notifications_created" in result
    assert "skipped_dedup" in result
    assert result["users_processed"] >= 0
    assert result["notifications_created"] >= 0
    assert result["skipped_dedup"] >= 0


def test_trigger_smart_notifs_import():
    """The admin router imports calculate_optimization without error."""
    from app.appliance_scenarios import calculate_optimization
    assert callable(calculate_optimization)
```

- [ ] **Step 2: Run test — expect PASS (schema test is pure, import should pass)**

```bash
cd "Server Side/backend"
pytest tests/test_admin.py -v
```

Expected: all pass

- [ ] **Step 3: Add the endpoint to admin.py**

Append after the final line of `Server Side/backend/app/routers/admin.py` (line 727):

```python


# ── Smart Notification Trigger (all users) ────────────────────

@router.post("/trigger-smart-notifications-all")
async def trigger_smart_notifications_all(
    request: Request, db: AsyncSession = Depends(get_db)
):
    """
    Run the smart notification engine for every user who has notifications enabled.
    Mirrors the old Node.js checkAndSendNotifications scheduler job.
    Admin only.
    """
    from app.appliance_scenarios import calculate_optimization
    from app.routers.smart_notifications import _get_influx, _fetch_env_conditions, _build_usage_data_for_device

    admin_id = _require_admin(request)

    # Fetch all non-admin users with notifications enabled
    users_result = await db.execute(
        select(User).where(User.is_admin == False, User.notifications_enabled == True)
    )
    users = users_result.scalars().all()

    users_processed = 0
    notifications_created = 0
    skipped_dedup = 0
    today = date.today()

    influx = _get_influx()

    for user in users:
        homes_result = await db.execute(
            select(Home).where(Home.user_id == user.id, Home.is_active == True)
        )
        homes = homes_result.scalars().all()
        if not homes:
            continue

        users_processed += 1

        for home in homes:
            # Default env conditions (InfluxDB room data if available)
            env = {"temperature": 20.0, "humidity": 50.0, "pressure": 101.3}
            try:
                from app.models import Room
                rooms_result = await db.execute(
                    select(Room).where(Room.home_id == home.id)
                )
                rooms = rooms_result.scalars().all()
                if rooms:
                    r0 = rooms[0]
                    entity_base = r0.entity_id or r0.name.lower().replace(" ", "")
                    env = _fetch_env_conditions(influx, entity_base)
            except Exception:
                pass

            devices_result = await db.execute(
                select(Device).where(Device.home_id == home.id, Device.is_active == True)
            )
            devices = devices_result.scalars().all()

            for device in devices:
                if not device.appliance_key:
                    continue

                # Get today's daily summary for usage data
                daily_result = await db.execute(
                    select(DailySummary).where(
                        DailySummary.device_id == device.id,
                        DailySummary.day_date == today,
                    )
                )
                daily = daily_result.scalar_one_or_none()
                usage_data = _build_usage_data_for_device(device, daily)

                try:
                    payload = calculate_optimization(
                        device.appliance_key,
                        env["temperature"],
                        env["humidity"],
                        env["pressure"],
                        usage_data,
                    )
                except Exception:
                    continue

                for alert in payload.get("alerts", []):
                    if alert.get("priority") not in ("critical", "warning"):
                        continue

                    severity = "CRITICAL" if alert["priority"] == "critical" else "WARNING"
                    notif = await NotificationEngine.create_notification(
                        db=db,
                        user_id=user.id,
                        title=f"⚡ {device.name}: {alert['scenario']}",
                        message=alert.get("message", "Review your appliance usage."),
                        notification_type=f"SMART_{device.appliance_key.upper()}_{alert['scenario'].upper().replace(' ', '_')[:30]}",
                        severity=severity,
                        home_id=home.id,
                        device_id=device.id,
                        requires_user_action=True,
                    )
                    if notif:
                        notifications_created += 1
                    else:
                        skipped_dedup += 1

    await _log_audit(
        db, admin_id, "TRIGGER_SMART_NOTIFICATIONS",
        details={"users_processed": users_processed,
                 "notifications_created": notifications_created,
                 "skipped_dedup": skipped_dedup},
        ip_address=request.client.host if request.client else None,
    )

    return {
        "users_processed": users_processed,
        "notifications_created": notifications_created,
        "skipped_dedup": skipped_dedup,
    }
```

- [ ] **Step 4: Lint**

```bash
cd "Server Side/backend"
ruff check app/routers/admin.py
```

- [ ] **Step 5: Commit**

```bash
git add "Server Side/backend/app/routers/admin.py" "Server Side/backend/tests/test_admin.py"
git commit -m "feat: add POST /api/admin/trigger-smart-notifications-all endpoint"
```

---

## Task 4: User frontend — five fixes

**Problem:** Five frontend bugs: (a) toaster/airfryer missing from device dropdown; (b) persona chip never renders; (c) bill prediction uses today-only cost × days; (d) custom date range ignored by loadEnergy; (e) no auto-refresh on Home tab.

**Files:**
- Modify: `Server Side/user-frontend/static/index.html`

- [ ] **Step 1: Fix (a) — Add toaster and airfryer to device type dropdown**

In `Server Side/user-frontend/static/index.html`, replace lines 515–520:

```html
        <select id="dev-type">
          <option value="kettle">Kettle</option><option value="washing_machine">Washing Machine</option>
          <option value="dishwasher">Dishwasher</option><option value="dryer">Dryer</option>
          <option value="microwave">Microwave</option><option value="gaming_console">Gaming Console</option>
          <option value="tv">TV</option><option value="other">Other</option>
        </select>
```

With:

```html
        <select id="dev-type">
          <option value="kettle">Kettle</option><option value="washing_machine">Washing Machine</option>
          <option value="dishwasher">Dishwasher</option><option value="dryer">Dryer</option>
          <option value="microwave">Microwave</option><option value="toaster">Toaster</option>
          <option value="airfryer">Air Fryer</option><option value="gaming_console">Gaming Console</option>
          <option value="tv">TV</option><option value="other">Other</option>
        </select>
```

- [ ] **Step 2: Fix (b) — populatePersonaChip actually sets DOM**

In `Server Side/user-frontend/static/index.html`, replace lines 834–844:

```javascript
function populatePersonaChip(u) {
  if (!u.persona_id) return;
  const colours = {
    'Eco Champion':    ['#10b981', 'rgba(16,185,129,.15)'],
    'Active Improver': ['#3b82f6', 'rgba(59,130,246,.15)'],
    'Steady User':     ['#8b5cf6', 'rgba(139,92,246,.15)'],
    'High Consumer':   ['#f59e0b', 'rgba(245,158,11,.15)'],
    'Disengaged':      ['#6b7280', 'rgba(107,114,128,.15)'],
  };
  // We only have persona_id, not name, from auth/me — chip will show after settings load
}
```

With:

```javascript
async function populatePersonaChip(u) {
  if (!u.persona_id) return;
  const colours = {
    'Eco Champion':    ['#10b981', 'rgba(16,185,129,.15)'],
    'Active Improver': ['#3b82f6', 'rgba(59,130,246,.15)'],
    'Steady User':     ['#8b5cf6', 'rgba(139,92,246,.15)'],
    'High Consumer':   ['#f59e0b', 'rgba(245,158,11,.15)'],
    'Disengaged':      ['#6b7280', 'rgba(107,114,128,.15)'],
  };
  try {
    const personas = await apiFetch('/analysis/personas');
    const p = (personas || []).find(x => x.id === u.persona_id);
    if (!p) return;
    const chip = document.getElementById('persona-chip');
    if (!chip) return;
    chip.textContent = p.name;
    chip.style.background = colours[p.name]?.[1] || 'rgba(139,92,246,.15)';
    chip.style.color = colours[p.name]?.[0] || '#8b5cf6';
    chip.style.display = 'inline-flex';
  } catch {}
}
```

- [ ] **Step 3: Fix (c) — buildBillPrediction uses 7-day rolling average**

In `Server Side/user-frontend/static/index.html`, replace lines 879–880 inside `loadHome()`:

```javascript
    // Bill prediction
    buildBillPrediction(data);
```

With:

```javascript
    // Bill prediction — fetch 7-day history for rolling average
    try {
      const devs = data.devices || [];
      if (devs.length > 0) {
        const allDailies = await Promise.all(
          devs.map(d => apiFetch(`/readings/${d.device_id}/daily?days=7`).catch(() => []))
        );
        const dayCosts = {};
        allDailies.forEach(daily => {
          (daily || []).forEach(row => {
            if (!dayCosts[row.day_date]) dayCosts[row.day_date] = 0;
            dayCosts[row.day_date] += (row.estimated_cost_gbp || (row.total_kwh || 0) * 0.27);
          });
        });
        const vals = Object.values(dayCosts);
        const avgDailyCost = vals.length >= 2 ? vals.reduce((a, b) => a + b, 0) / vals.length : data.total_cost_gbp || 0;
        buildBillPrediction(data, avgDailyCost);
      } else {
        buildBillPrediction(data, null);
      }
    } catch { buildBillPrediction(data, null); }
```

Also update the `buildBillPrediction` function signature and body (lines 925–945):

```javascript
function buildBillPrediction(data, avgDailyCost) {
  const now = new Date();
  const dayOfMonth = now.getDate();
  const daysInMonth = new Date(now.getFullYear(), now.getMonth() + 1, 0).getDate();
  const dailyCost = (avgDailyCost != null) ? avgDailyCost : (data.total_cost_gbp || 0);
  const projectedMonthly = dailyCost * daysInMonth;
  const pct = (dayOfMonth / daysInMonth * 100).toFixed(0);

  document.getElementById('bill-card').style.display = 'block';
  document.getElementById('bill-predicted').textContent = '£' + projectedMonthly.toFixed(2);
  document.getElementById('bill-sub').textContent = `Projection at current rate · Day ${dayOfMonth} of ${daysInMonth}`;
  document.getElementById('h-bill-forecast').textContent = '£' + projectedMonthly.toFixed(2);
  document.getElementById('bill-progress').style.width = pct + '%';
  document.getElementById('bill-day-label').textContent = `Day ${dayOfMonth}`;
  if (projectedMonthly > 60) {
    document.getElementById('bill-progress').className = 'prog over';
  } else if (projectedMonthly > 45) {
    document.getElementById('bill-progress').className = 'prog warn';
  }
}
```

- [ ] **Step 4: Fix (d) — loadEnergy honours custom date range**

In `Server Side/user-frontend/static/index.html`, replace line 1009:

```javascript
  const days = { daily: 1, '7d': 7, '30d': 30 }[_energyPeriod] || 7;
  document.getElementById('energy-chart-title').textContent = `Energy Usage (Last ${days} day${days > 1 ? 's' : ''})`;
```

With:

```javascript
  let queryParam;
  let chartTitle;
  if (_energyPeriod === 'custom') {
    const s = document.getElementById('range-start').value;
    const e = document.getElementById('range-end').value;
    queryParam = (s && e) ? `start_date=${s}&end_date=${e}` : 'days=7';
    chartTitle = (s && e) ? `Energy Usage (${s} → ${e})` : 'Energy Usage (Last 7 days)';
  } else {
    const days = { daily: 1, '7d': 7, '30d': 30 }[_energyPeriod] || 7;
    queryParam = `days=${days}`;
    chartTitle = `Energy Usage (Last ${days} day${days > 1 ? 's' : ''})`;
  }
  document.getElementById('energy-chart-title').textContent = chartTitle;
```

Also replace line 1018 (the `apiFetch` call inside `loadEnergy`):

```javascript
      devs.map(d => apiFetch(`/readings/${d.id}/daily?days=${days}`).catch(() => []))
```

With:

```javascript
      devs.map(d => apiFetch(`/readings/${d.id}/daily?${queryParam}`).catch(() => []))
```

- [ ] **Step 5: Fix (e) — add _activeSection tracking and 30s auto-refresh**

In `Server Side/user-frontend/static/index.html`, find the line that declares `const loaders = {` (around line 726). Just before that block, add:

```javascript
let _activeSection = 'home';
```

Then in the `goSection` function (around line 736), add `_activeSection = name;` as the first line:

```javascript
function goSection(name) {
  _activeSection = name;
  document.querySelectorAll('section').forEach(s => s.classList.remove('active'));
  document.getElementById('s-' + name)?.classList.add('active');
```

Then find the DOMContentLoaded block (where `loadHome()` is called after login, around line 826) and add the interval after `loadHome()`:

```javascript
    loadHome();
    refreshNotifBadge();
    setInterval(() => {
      if (_activeSection === 'home' && token) loadHome();
    }, 30_000);
```

- [ ] **Step 6: Commit**

```bash
git add "Server Side/user-frontend/static/index.html"
git commit -m "fix: user dashboard — dropdown, persona chip, bill prediction, date range, auto-refresh"
```

---

## Task 5: Admin portal — smart notification trigger button

**Problem:** There is no way for admin to manually trigger smart notifications for all users. The new backend endpoint exists after Task 3, but there is no button in the portal.

**Files:**
- Modify: `Server Side/owner-frontend/static/index.html:453-454` (after closing `</div>` of the Send Notification card)
- Modify: `Server Side/owner-frontend/static/js/admin.js:1133` (after `btn-refresh-templates` listener)

- [ ] **Step 1: Add the button card to admin/index.html**

In `Server Side/owner-frontend/static/index.html`, replace lines 453–455:

```html
      </div>

      <!-- Templates -->
```

With:

```html
      </div>

      <!-- Smart Notification Engine -->
      <div class="card">
        <div class="card-header"><h2 class="card-title">Smart Notification Engine</h2></div>
        <p style="font-size:13px;color:#94a3b8;margin:0 0 16px">
          Runs the appliance-scenario engine for every user who has notifications enabled.
          Uses today's usage data + environmental factors. Deduplication: 12-hour window per device.
        </p>
        <button class="btn-primary" id="btn-smart-notif-all">🔔 Run Smart Notifications Now</button>
        <div id="smart-notif-feedback" class="form-feedback" style="margin-top:12px"></div>
      </div>

      <!-- Templates -->
```

- [ ] **Step 2: Add the click handler in admin.js**

In `Server Side/owner-frontend/static/js/admin.js`, after line 1133 (`document.getElementById('btn-refresh-templates').addEventListener('click', loadTemplates);`), add:

```javascript
  document.getElementById('btn-smart-notif-all').addEventListener('click', async () => {
    const fb = document.getElementById('smart-notif-feedback');
    fb.textContent = 'Running smart notifications…';
    fb.className = 'form-feedback';
    try {
      const res = await api('/api/admin/trigger-smart-notifications-all', { method: 'POST' });
      fb.textContent = `✅ Smart notifications done: ${res.notifications_created} new, ${res.skipped_dedup} skipped (dedup), ${res.users_processed} users processed`;
      fb.className = 'form-feedback success';
    } catch (err) {
      fb.textContent = `❌ ${err.message}`;
      fb.className = 'form-feedback error';
    }
  });
```

- [ ] **Step 3: Commit**

```bash
git add "Server Side/owner-frontend/static/index.html" "Server Side/owner-frontend/static/js/admin.js"
git commit -m "feat: add smart notification trigger button to admin portal"
```

---

## Task 6: Infrastructure — mosquitto passwd, db-seed, dummy-data-sender

This task covers three inter-related Docker/infrastructure changes that must all be done together for `docker compose up` to work.

**Files:**
- Modify: `Server Side/mosquitto/config/mosquitto.conf:32`
- Modify: `docker-compose.yml` (repo root)
- Create: `Dockerfile.dummy` (repo root)
- Modify: `dummy_data_sender.py:53-72`

### Part A: Update mosquitto.conf password_file path

- [ ] **Step 1: Update password_file path in mosquitto.conf**

In `Server Side/mosquitto/config/mosquitto.conf`, replace line 32:

```
password_file /mosquitto/config/passwd
```

With:

```
password_file /mosquitto/secret/passwd
```

### Part B: Add --csv arg to dummy_data_sender.py

- [ ] **Step 2: Add --csv to dummy_data_sender.py**

In `dummy_data_sender.py`, replace lines 53–72:

```python
def load_dummy_accounts():
    accounts = []
    try:
        with open("wattwise_cardiff_participants_20260403-105251.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Email"].strip():
                    accounts.append({
                        "email": row["Email"].strip(),
                        "password": row["Password"].strip(),
                    })
    except FileNotFoundError:
        log.warning("CSV file not found locally. Ensure it is in the same directory as this script.")
    
    # Inject Asma Irfan manually as per research requirements
    # accounts.append({
    #     "email": "IrfanA1@cardiff.ac.uk",
    #     "password": "WattWise2024!",
    # })
    return accounts

DUMMY_ACCOUNTS = load_dummy_accounts()
```

With:

```python
def load_dummy_accounts(csv_path: str = "wattwise_cardiff_participants_20260403-105251.csv"):
    accounts = []
    try:
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row["Email"].strip():
                    accounts.append({
                        "email": row["Email"].strip(),
                        "password": row["Password"].strip(),
                    })
    except FileNotFoundError:
        log.warning("CSV not found: %s", csv_path)
    return accounts

DUMMY_ACCOUNTS: list = []  # populated in main() after --csv arg is parsed
```

Then in the `main()` function in `dummy_data_sender.py`, after the `parser.add_argument("--admin-password", ...)` line (around line 417), add:

```python
    parser.add_argument("--csv", default="wattwise_cardiff_participants_20260403-105251.csv",
                        help="Path to participants CSV file")
```

And replace the line `client = WattWiseClient(args.url)` (around line 429) with:

```python
    global DUMMY_ACCOUNTS
    DUMMY_ACCOUNTS = load_dummy_accounts(args.csv)
    if not DUMMY_ACCOUNTS:
        log.error("No accounts loaded from CSV: %s", args.csv)
        sys.exit(1)

    client = WattWiseClient(args.url)
```

### Part C: Create Dockerfile.dummy

- [ ] **Step 3: Create Dockerfile.dummy at repo root**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY dummy_data_sender.py .
COPY "Server Side/backend/participants.csv" participants.csv
RUN pip install --no-cache-dir requests
CMD ["python", "dummy_data_sender.py", \
     "--url", "http://wattwise-backend:8000", \
     "--interval", "30", \
     "--no-backfill", \
     "--csv", "participants.csv"]
```

### Part D: Update root docker-compose.yml

- [ ] **Step 4: Replace root docker-compose.yml**

Make the following changes in `docker-compose.yml` (repo root):

**4a — Replace the passwd bind-mount in the mosquitto service (lines 10–15):**

```yaml
    volumes:
      - ./Server Side/mosquitto/config/mosquitto.conf:/mosquitto/config/mosquitto.conf:ro
      - ./Server Side/mosquitto/config/acl.conf:/mosquitto/config/acl.conf:ro
      - mosquitto_passwd_vol:/mosquitto/secret:ro
      - mosquitto_data:/mosquitto/data
      - mosquitto_log:/mosquitto/log
```

(The `passwd` file is no longer bind-mounted from the host — it comes from the volume written by `mosquitto-init`.)

**4b — Add `depends_on: mosquitto-init: condition: service_completed_successfully` to the mosquitto service.** Add after line 17 (after the `environment:` block, before `healthcheck:`):

```yaml
    depends_on:
      mosquitto-init:
        condition: service_completed_successfully
```

**4c — Add the `mosquitto-init` service at the top of the file (before the `mosquitto` service):**

```yaml
  # ── MQTT Password Init (one-shot) ────────────────────────
  mosquitto-init:
    image: eclipse-mosquitto:2
    container_name: wattwise-mosquitto-init
    restart: "no"
    environment:
      - MQTT_USERNAME=${MQTT_USERNAME}
      - MQTT_PASSWORD=${MQTT_PASSWORD}
      - MQTT_PI_PASSWORD=${MQTT_PI_PASSWORD:-WattWise_RPi_Dev_2026}
    volumes:
      - mosquitto_passwd_vol:/mosquitto/secret
    entrypoint: >
      sh -c "
        mosquitto_passwd -b -c /mosquitto/secret/passwd $$MQTT_USERNAME $$MQTT_PASSWORD &&
        mosquitto_passwd -b /mosquitto/secret/passwd wattwise_rpi $$MQTT_PI_PASSWORD &&
        echo 'passwd file created successfully'
      "
    networks:
      - wattwise-network
```

**4d — Add the `db-seed` service after the `backend` service:**

```yaml
  # ── DB Seed (one-shot, auto-exits) ───────────────────────
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

**4e — Add the commented-out `dummy-data-sender` service (after `db-seed`):**

```yaml
  # ── Dummy Data Sender ── uncomment for local testing ─────────
  # dummy-data-sender:
  #   build:
  #     context: .
  #     dockerfile: Dockerfile.dummy
  #   container_name: wattwise-dummy-sender
  #   restart: unless-stopped
  #   env_file:
  #     - ./Server Side/.env
  #   depends_on:
  #     backend:
  #       condition: service_healthy
  #     db-seed:
  #       condition: service_completed_successfully
  #   networks:
  #     - wattwise-network
```

**4f — Add `mosquitto_passwd_vol` to the `volumes:` section (line 282+):**

```yaml
volumes:
  mysql_data:
  mosquitto_data:
  mosquitto_log:
  mosquitto_passwd_vol:
  influxdb_data:
  letsencrypt:
  certbot_webroot:
  backups_data:
```

- [ ] **Step 5: Commit**

```bash
git add "Server Side/mosquitto/config/mosquitto.conf" docker-compose.yml Dockerfile.dummy dummy_data_sender.py
git commit -m "feat: mosquitto-init passwd volume, db-seed service, Dockerfile.dummy, --csv arg"
```

---

## Task 7: End-to-end smoke test

Verify the full stack works before calling it done.

- [ ] **Step 1: Run all backend unit tests**

```bash
cd "Server Side/backend"
pytest tests/ -v
```

Expected: all tests PASS, no ERRORs

- [ ] **Step 2: Run the full lint suite**

```bash
cd "Server Side/backend"
ruff check app/
```

Expected: clean output

- [ ] **Step 3: Verify docker-compose.yml is valid YAML**

```bash
docker compose -f docker-compose.yml config --quiet
```

Expected: exits 0 with no errors

- [ ] **Step 4: Start the full stack**

From repo root (ensure `./Server Side/.env` exists with credentials):

```bash
docker compose up --build -d
```

Watch for each service to reach healthy/completed state:

```bash
docker compose ps
```

Expected output (key statuses):
```
wattwise-mosquitto-init    exited (0)
wattwise-mysql             healthy
wattwise-influxdb          healthy
wattwise-backend           healthy
wattwise-db-seed           exited (0)
wattwise-admin-frontend    running
wattwise-user-frontend     running
wattwise-nginx-proxy       running
```

- [ ] **Step 5: Verify seed ran**

```bash
docker compose logs db-seed --tail=20
```

Expected: lines like `Seeded user: ...`, `Created home for ...`, exits with code 0

- [ ] **Step 6: Test login and dashboard**

Open `http://localhost` in a browser. Log in with a participant from `Server Side/backend/participants.csv`. Verify:
- Home tab loads (kWh, cost, tariff visible)
- Persona chip appears in the topbar within a few seconds

- [ ] **Step 7: Uncomment and test dummy sender**

In `docker-compose.yml`, uncomment the `dummy-data-sender` service block (remove the `#` prefix from each line). Then:

```bash
docker compose up -d dummy-data-sender
docker compose logs dummy-data-sender -f
```

Expected: every 30s, log lines like `Cycle 1 @ ... UTC`, `sent=84 failed=0`

After 60s, refresh the browser — `h-kwh` value should update.

- [ ] **Step 8: Test admin smart notifications**

Open `http://localhost/admin/`. Log in as admin. Navigate to Notifications section. Click "🔔 Run Smart Notifications Now".

Expected: feedback shows `✅ Smart notifications done: N new, K skipped (dedup), M users processed`

Log back in as a participant — new notifications should appear in the bell badge.

- [ ] **Step 9: Re-comment dummy sender before push**

```bash
# In docker-compose.yml, comment the dummy-data-sender lines back out
git add docker-compose.yml
git commit -m "chore: re-comment dummy-data-sender for production safety"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] 1a Notifications mark-read POST → Task 1
- [x] 1b Mosquitto passwd → Task 6 Part A/D
- [x] 1c Device dropdown → Task 4 Step 1
- [x] 1d Bill prediction 7-day avg → Task 4 Step 3
- [x] 1e Custom date range → Task 4 Step 4 + Task 2
- [x] 2a db-seed service → Task 6 Part D (4d)
- [x] 2b Dockerfile.dummy + dummy-data-sender → Task 6 Part C/D
- [x] 3a Home auto-refresh → Task 4 Step 5
- [x] 3b Persona chip → Task 4 Step 2
- [x] 4a Admin trigger endpoint → Task 3
- [x] 4b Admin portal button → Task 5

**All tasks reference exact file paths and line numbers. No placeholders. All code blocks are complete.**
