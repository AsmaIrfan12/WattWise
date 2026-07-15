# WattWise — System Improvement & Implementation Plan

**Author:** engineering review for Mr. Suhas Devmane · **Scope:** admin dashboard, analytics,
personas, alerts/notifications, devices, backup, data pipeline. **Goal:** a high-end,
real-time admin-controlled smart-home alerts platform ready for real homes.

This plan is grounded in a code review of the running system (all 28 core API endpoints
return 200; the issues below are architecture/data-flow gaps, not crashes).

---

## A. Code-review findings — how components connect today

```
RPi → MQTT(mqtt_client) → MySQL energy_readings + InfluxDB "W"
     → scheduler: hourly_agg(30m) → hourly_summary
                  daily_agg(00:15) → daily_summary + home_daily_totals
                  rankings(01:30) → energy_rankings
                  classify_personas(Sun 02:00) → users.persona_id
     → admin/user dashboards read the *summary* tables (NOT raw readings)
```

**Root-cause themes found:**
1. **Dashboards read summary tables, which are sparse/stale.** `/analytics/energy?days=7`
   returned a **single** day; `device-timeseries` returned **one** hourly point. So the
   community-energy and live-telemetry charts look "empty / flat / cost-only" — there is
   only 1 point to plot. The pipeline works; coverage/backfill and a raw-data fallback are missing.
2. **Aggregation never backfills gaps.** The 30-min hourly job only aggregates the current
   window; if the stack was down (or fresh), earlier hours stay missing forever unless
   `bootstrap-aggregator` is re-run. There is no rolling catch-up.
3. **Persona cadence is weekly** (`classify_personas` cron Sun 02:00) and the small-cohort
   **percentile fallback** produces near-equal bands → "distribution looks the same".
4. **No auto-refresh on the main dashboard/analytics.** Only the MQTT panel (10 s) and the
   device chart (30 s) refresh; everything else is manual.
5. **Alerts and notifications are one table** (`Notification`); there is no separation of
   *system-generated usage alerts* (interactive, decision-tracked) from *admin broadcasts*
   (offers/messages).
6. **Backup is whole-DB only** (`mysql-backup` service); no per-user / multi-user export.
7. **Drill-down, compare, device-timeseries already exist** (`openUserPanel` →
   `/users/{id}/details`, `POST /analytics/compare`, `/analytics/device-timeseries`) — these
   are enhancement targets, not new builds.
8. **Real vs synthetic homes are not distinguished** in the UI. Asma (home_001) is the only
   real RPi; an offline gap there is expected, the 50 others are demo.

---

## B. Workstreams (with implementation detail)

### WS1 — Reliable data so charts are never empty  *(unblocks the most symptoms)*
- **Raw-data fallback:** when a summary series has < N points for the requested window,
  have `/analytics/energy`, `device-timeseries`, and the user dashboards fall back to
  aggregating raw `energy_readings` on the fly (bounded query) so charts always render.
- **Rolling catch-up aggregation:** add a startup + hourly "backfill last 48 h of missing
  hourly/daily summaries" step (reuse `aggregate_all_history` logic, bounded window) so gaps
  self-heal without a manual `bootstrap-aggregator`.
- **Indexes:** verify composite indexes on `energy_readings(device_id, recorded_at)`,
  `hourly_summary(device_id, hour_start)`, `home_daily_totals(home_id, day_date)`,
  `energy_rankings(user_id, period_type, period_start)` for fast range scans.
- *Files:* `routers/admin.py` (energy/device-timeseries), `routers/readings.py`,
  `scheduler.py` (backfill), `mysql/init` (indexes).

### WS2 — Real-time auto-refresh + dashboard performance
- **Configurable auto-refresh** (client): dashboard **10 s**, analytics **60 s**, devices
  **30 s** (exists), persona panel driven by the 6 h server run. Single shared scheduler in
  `admin.js` with visibility-pause (don't poll a hidden tab).
- **Faster first paint:** cache the heavy `/admin/dashboard` + `/analytics/energy` responses
  server-side with a short TTL (e.g. 10–30 s) so 10 s polling is cheap; lazy-load non-visible
  tabs; keep `Promise.all` batching.
- **Consider a WebSocket/SSE push** for live KPIs instead of polling (nginx `/ws/` already
  proxied) — Phase 2.
- *Files:* `owner-frontend/static/js/admin.js`, `routers/admin.py` (cache layer).

### WS3 — Personas: 6-hourly + honest visualization
- **Cadence:** change `classify_personas` to `interval, hours=6` (or `cron hour="*/6"`).
- **Small-cohort handling:** lower `MIN_COHORT_FOR_CLUSTERING` sensibly and/or always run
  K-means when ≥ k*2 engaged; record why (already stored in `persona_cluster_assignments`).
- **New visualization** (fix "all bars look equal"): replace the flat bar with (a) a donut of
  counts + %, (b) a **radar chart per persona** over the 8 standardised features, and (c) a
  **scatter of the 2 top PCA components** coloured by persona so clusters are visually
  distinct. Add silhouette/DB score badges (already computed).
- *Files:* `main.py` (schedule), `persona_classifier.py` (thresholds + optional PCA coords),
  `admin.js` + `index.html` (personas tab).

### WS4 — Analytics tab overhaul (single-device + rich compare)
- **Auto-refresh 60 s**, "use all data" (date range defaulting to full history with a cap).
- **Single-device analysis for any user:** admin picks *user → device → metric*; render load
  curve, hourly profile, standby, cost, peak-share, anomalies overlay (endpoints exist:
  `/readings/{id}/hourly|daily|standby|analysis`, `/analytics/anomalies`).
- **Compare modes** (extend `POST /analytics/compare`): device-vs-device (same or different
  user), device-vs-persona-average, device-vs-community-average, period-over-period
  (this week vs last), and appliance-class benchmark. Add a mode selector + multi-series
  `renderComparisonChart`.
- *Files:* `routers/admin.py` (`/analytics/compare`, new `/analytics/device/{id}`),
  `admin.js` (`initAdvancedComparison`, `loadAnalytics`).

### WS5 — Separate **Alerts** (system) from **Notifications** (admin)  *(semantic model change)*
- **Definition to implement:**
  - **Alert** = auto-generated from time-series analysis (peak warning, spike, standby, goal
    breach). Interactive; the user's response feeds `user_decisions` (the research core).
    Shows in the app's **Alerts** tab.
  - **Notification** = admin custom broadcast (offer / message / info). Non-decision. Shows in
    the app's **Notifications** tab.
- **Implementation:** add `category` (enum `SYSTEM_ALERT` | `ADMIN_MESSAGE`) to the
  `Notification` model (migration), tag existing rows, and split delivery: the alert engine
  (`notification_engine` + a new `alert_engine` cron driven by anomaly/peak/goal analysis)
  emits `SYSTEM_ALERT`; `POST /admin/notifications/send` emits `ADMIN_MESSAGE`. Expose
  `/api/alerts` vs `/api/notifications`; update the app WebView tabs + Expo push `type`.
  Link `user_decisions.notification_id` to the alert so effectiveness scoring stays intact.
- *Files:* `models.py`, Alembic migration, `notification_engine.py`, new `alert_engine.py`,
  `routers/notifications.py`, `routers/admin.py`, user-frontend tabs, Android router.

### WS6 — Devices / RPi visualization + real-vs-synthetic
- Add an `is_real`/`source` flag on homes (or derive from an allowlist incl. Asma) and a UI
  badge ("Real RPi" vs "Demo"). Treat a real-home offline gap as informational, not error.
- Per-device live gauge + 24 h sparkline using the WS1 raw fallback so it's never empty.
- *Files:* `models.py` (flag), `routers/admin.py` (`/devices/status`), `admin.js` devices tab.

### WS7 — Per-user & multi-user backup/export
- New endpoints: `GET /admin/export/user/{id}` (full bundle: profile, home, devices, readings,
  decisions, rankings, persona history as a zip/JSON) and `POST /admin/export/users` (multi-
  select). Keep the nightly full-DB dump.
- *Files:* `routers/export.py` or `admin.py`, `admin.js` backup tab (user picker).

### WS8 — System connectivity hardening (review items)
- **entity_id collision risk:** `mqtt_client` matches readings to a device by `entity_id`
  only; guarantee global uniqueness (seed already uses unique ids) and log/skip on ambiguity.
- **Surface InfluxDB/aggregation errors** instead of silent `0 published` / empty charts.
- **Health/observability:** ensure `/health/dependencies` covers MySQL+MQTT+InfluxDB; add a
  "last aggregation ran at" and "last classifier ran at" admin widget.

---

## C. Prioritized TODO list

### Phase 0 — deploy hygiene (do first, already identified)
- [ ] Push pending commits (`cdd771d` online-window, `a0c6e86` README) — needs write creds.
- [ ] Droplet: 4 GB swap + resize to 2 vCPU / 4 GB (fixes "service unavailable/analytics failed").
- [ ] Point Asma's RPi at `159.65.213.183:1883`; run `bootstrap-aggregator` after ~2 days.

### Phase 1 — "never empty, always fresh" (highest visible impact)
- [ ] WS1 raw-data fallback for energy + device-timeseries + user dashboards.
- [ ] WS1 rolling catch-up aggregation (self-healing gaps) + verify indexes.
- [ ] WS2 client auto-refresh (dashboard 10 s / analytics 60 s) with hidden-tab pause.
- [ ] WS2 short-TTL server cache for dashboard + energy endpoints.
- [ ] WS3 persona cadence → every 6 h.

### Phase 2 — analytics & personas depth
- [ ] WS4 single-device analysis for any user (admin picker).
- [ ] WS4 extended compare modes (cross-user, persona/community avg, period-over-period).
- [ ] WS3 new persona visualization (donut + radar + PCA scatter + quality badges).
- [ ] WS6 real-vs-synthetic home badge; never-empty device charts.

### Phase 3 — alerts/notifications split (research-grade)
- [ ] WS5 model migration (`category`) + alert engine + `/api/alerts` vs `/api/notifications`.
- [ ] WS5 app tabs (Alerts = interactive/decision-tracked; Notifications = admin messages).
- [ ] WS5 Expo push `type` routing + deep links.

### Phase 4 — backup & hardening
- [ ] WS7 single-user + multi-user export.
- [ ] WS8 connectivity hardening (error surfacing, aggregation/classifier "last run" widgets).

---

## D. Recommendation to proceed
Start with **Phase 1** — it clears the majority of the reported symptoms (empty community
energy, flat live telemetry, slow/stale dashboard, "personas look equal") with contained,
low-risk changes and no schema migration. **Phase 3 (alerts/notifications split)** is the one
architectural change (DB migration + app tabs) and should be scoped as its own effort.

Suggested execution: I implement **Phase 1** end-to-end (backend fallback + aggregation
catch-up + client auto-refresh + 6 h personas), you verify on the droplet, then we proceed to
Phase 2. Say the word and I'll begin Phase 1.
