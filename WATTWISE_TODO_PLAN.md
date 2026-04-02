# WattWise TODO Action Plan

**Generated:** 2026-03-30 | **Target:** Transform from research prototype to professional-grade platform

---

## Phase 0: CRITICAL SECURITY FIXES (Do First)
*Estimated: 1-2 days | Impact: Prevents data breach and Play Store rejection*

- [ ] **0.1** Disable MQTT anonymous access — uncomment `password_file` and `acl_file` in `mosquitto/config/mosquitto.conf:26-32`, set `allow_anonymous false`
- [ ] **0.2** Remove hardcoded admin password hash from `mysql/init/01-schema.sql:299-307` — generate at runtime via startup script
- [ ] **0.3** Replace all "changeme" defaults in `backend/app/config.py` with required env vars (fail on startup if missing)
- [ ] **0.4** Android: Set `cleartextTrafficPermitted="false"` in `network_security_config.xml:16`, allow cleartext only for localhost/10.0.2.2
- [ ] **0.5** Android: Remove `android:usesCleartextTraffic="true"` from `AndroidManifest.xml:27`
- [ ] **0.6** Android: Set `android:allowBackup="false"` in `AndroidManifest.xml:20`
- [ ] **0.7** Fix CORS — restrict `allow_headers` and `allow_methods` to explicit lists in `main.py:153-160`
- [ ] **0.8** Add DOMPurify to both frontends to sanitize all user-rendered content (prevents XSS)
- [ ] **0.9** Replace `threading.Lock` with `asyncio.Lock` in `security.py:14-48`
- [ ] **0.10** Add energy value sanity check — `le=50000` on power_watts in `schemas.py:92`

---

## Phase 1: BACKEND HARDENING
*Estimated: 3-4 days | Impact: Production stability and performance*

### Performance Fixes
- [ ] **1.1** Fix N+1 queries in `scheduler.py:299-325` — use JOIN to load homes+users+decisions in single query for rankings
- [ ] **1.2** Fix N+1 in `routers/analysis.py:79-100` — pre-load Home with `.outerjoin()` for leaderboard
- [ ] **1.3** Cache `is_admin` flag in JWT claims instead of DB query per request (`main.py:239`)
- [ ] **1.4** Replace blocking InfluxDB writes with async — use `run_in_executor()` or `aioinflux` in `mqtt_client.py:89-118`
- [ ] **1.5** Fix `mark_all_read` — use bulk `UPDATE...WHERE` instead of loading all notifications in `routers/notifications.py:92-101`
- [ ] **1.6** Increase uvicorn workers to 4 in `Dockerfile:19`

### Database Improvements
- [ ] **1.7** Add missing indexes: `notifications.user_id`, `devices.home_id`, `user_decisions.user_id`, `home_daily_totals.day_date`
- [ ] **1.8** Add unique constraint on `energy_readings(device_id, recorded_at)` to prevent duplicates
- [ ] **1.9** Add unique constraint on `energy_goals` to prevent duplicate goals per user/device
- [ ] **1.10** Add `CHECK` constraints: `energy_readings.power_watts >= 0`, `daily_summary.total_kwh >= 0`
- [ ] **1.11** Replace `func.IF()` with SQLAlchemy `case()` in `decision_tracker.py:189`
- [ ] **1.12** Add `deleted_at` soft-delete column to `notifications`, `user_decisions` for research audit trail

### API Quality
- [ ] **1.13** Implement token blacklist for logout (Redis or DB table with TTL) — fix no-op in `routers/auth.py:188-192`
- [ ] **1.14** Add pagination metadata to all list endpoints: `{"data": [...], "total": N, "page": P, "has_more": bool}`
- [ ] **1.15** Add API versioning — prefix all routes with `/api/v1/`
- [ ] **1.16** Strengthen password validation — require 8+ chars, uppercase, number in `routers/auth.py:13`
- [ ] **1.17** Add `setattr()` field allowlists in `routers/devices.py:57` and `routers/goals.py:131`
- [ ] **1.18** Add `HEALTHCHECK` instruction to `backend/Dockerfile`
- [ ] **1.19** Change `scheduler.shutdown(wait=False)` to `shutdown(wait=True)` with timeout in `main.py:137`

---

## Phase 2: FRONTEND TRANSFORMATION
*Estimated: 5-7 days | Impact: "Professional team" appearance*

### Charting & Data Visualization
- [ ] **2.1** Add Chart.js (or ApexCharts) to both frontends — replace DIV-based bar charts
- [ ] **2.2** Admin dashboard: Add line charts for 7/14/30-day energy trends
- [ ] **2.3** Admin dashboard: Add pie chart for energy breakdown by device type
- [ ] **2.4** User dashboard: Add interactive line chart with zoom/pan for usage history
- [ ] **2.5** User dashboard: Add device consumption pie/donut chart
- [ ] **2.6** Add date range picker to all analytics views (replace hardcoded 7-day window)

### Real-Time Updates
- [ ] **2.7** Implement WebSocket connection on user dashboard (nginx already has `/ws/*` route)
- [ ] **2.8** Push live energy readings to dashboard charts (no manual refresh needed)
- [ ] **2.9** Add real-time notification badge counter

### UI Polish
- [ ] **2.10** Admin dashboard: Add responsive hamburger menu for mobile (currently fixed 220px sidebar)
- [ ] **2.11** Add skeleton loaders / shimmer effects for all loading states (replace "Loading..." text)
- [ ] **2.12** Add proper 404 error page to both frontends
- [ ] **2.13** Add toast notifications for success/error feedback
- [ ] **2.14** Add dark/light theme toggle
- [ ] **2.15** Add data export buttons (CSV download) on admin analytics and user dashboard

### Professional Features
- [ ] **2.16** Admin: Add filtering, sorting, and search on users table
- [ ] **2.17** Admin: Add date range picker for analytics
- [ ] **2.18** Admin: Add audit log / admin activity log
- [ ] **2.19** User: Add comparative analytics ("Your usage vs community average")
- [ ] **2.20** User: Add bill prediction ("Estimated monthly cost: X")
- [ ] **2.21** User: Add notification preferences (mute types, quiet hours)

### Code Quality
- [ ] **2.22** Extract user frontend JavaScript into separate modules (currently 571 lines inline)
- [ ] **2.23** Add ARIA labels and semantic HTML for accessibility
- [ ] **2.24** Add CSRF tokens to all frontend forms

---

## Phase 3: ANDROID APP — PLAY STORE READY
*Estimated: 3-4 days | Impact: Professional distribution*

### Play Store Blockers (Must Fix)
- [ ] **3.1** Configure app signing in `build.gradle.kts` (generate keystore, add signingConfigs block)
- [ ] **3.2** Integrate Firebase Crashlytics (dependency already in BOM — connect and enable)
- [ ] **3.3** Integrate Firebase Analytics (dependency already in BOM — add event tracking)
- [ ] **3.4** Add privacy policy screen/link and GDPR consent flow
- [ ] **3.5** Remove JWT token from URL fragment — inject via JavaScript `evaluateJavascript()` after page load
- [ ] **3.6** Create Play Store assets: feature graphic (1024x500), screenshots (5+), descriptions

### Essential Features
- [ ] **3.7** Add logout button to MainScreen or Settings
- [ ] **3.8** Add "Forgot Password?" flow on LoginScreen
- [ ] **3.9** Add email format validation on LoginScreen before submit
- [ ] **3.10** Preserve WebView state on rotation (use savedInstanceState)
- [ ] **3.11** Use `rememberSaveable()` for form fields to survive rotation
- [ ] **3.12** Add in-app update check (Play Core library `AppUpdateManager`)

### Code Quality
- [ ] **3.13** Apply ktlint and detekt plugins in build.gradle.kts (already declared in libs.versions.toml)
- [ ] **3.14** Add `contentDescription` to all icons and images for accessibility
- [ ] **3.15** Move hardcoded error strings to `strings.xml` for i18n readiness
- [ ] **3.16** Use EncryptedSharedPreferences for JWT token storage (replace plain DataStore)

### Testing
- [ ] **3.17** Add AuthViewModel tests (login success, login failure, signup, validation)
- [ ] **3.18** Add AuthRepository tests (API responses, error mapping)
- [ ] **3.19** Add ServerRepository tests (connectivity, URL validation)
- [ ] **3.20** Add Compose UI tests for LoginScreen and SignupScreen
- [ ] **3.21** Target: 60%+ code coverage

---

## Phase 4: DEVOPS & INFRASTRUCTURE
*Estimated: 3-4 days | Impact: Production reliability*

### Critical Infrastructure
- [ ] **4.1** Add automated MySQL backup — daily mysqldump with 30-day retention
- [ ] **4.2** Add resource limits to all Docker containers (memory + CPU) in docker-compose.yml
- [ ] **4.3** Add health checks to frontend containers and InfluxDB in docker-compose.yml
- [ ] **4.4** Enable MQTT TLS on port 8883 (uncomment in mosquitto.conf, add Let's Encrypt certs)
- [ ] **4.5** Implement dynamic MQTT ACL generation (when new home is created via API, generate ACL entry)

### Observability
- [ ] **4.6** Add Prometheus metrics endpoint to FastAPI backend (`/metrics`)
- [ ] **4.7** Add structured JSON logging to backend (replace scattered logger formats)
- [ ] **4.8** Add Docker logging driver configuration for centralized log collection
- [ ] **4.9** Create Grafana dashboard for: API latency, MQTT throughput, DB connections, error rates
- [ ] **4.10** Add Sentry or equivalent for application error tracking

### CI/CD Improvements
- [ ] **4.11** Add pytest coverage enforcement (`--cov-fail-under=80`) to CI pipeline
- [ ] **4.12** Add Docker image vulnerability scanning (Trivy) to CI
- [ ] **4.13** Add secrets scanning (truffleHog or git-secrets) to CI
- [ ] **4.14** Tag Docker images with git SHA instead of `latest` only
- [ ] **4.15** Add smoke test that verifies DB + MQTT + InfluxDB connectivity post-deploy

### Sensing Layer
- [ ] **4.16** Add exponential backoff retry on MQTT connection failure in `rpi_mqtt_publisher.py`
- [ ] **4.17** Add local SQLite buffer for readings when MQTT broker is unreachable
- [ ] **4.18** Reduce heartbeat interval from 5 minutes to 60 seconds
- [ ] **4.19** Add measurement validation (reject negative watts, >50kW values, NaN/Inf)
- [ ] **4.20** Fix SQL injection in InfluxDB query (`rpi_mqtt_publisher.py:86-100`) — parameterize entity_id

---

## Phase 5: TESTING SUITE
*Estimated: 3-5 days | Impact: Code confidence and regression prevention*

### Backend Tests
- [ ] **5.1** Auth integration tests: signup → login → protected endpoint → logout
- [ ] **5.2** MQTT ingestion tests: mock MQTT message → verify MySQL + InfluxDB writes
- [ ] **5.3** Scheduler tests: verify hourly/daily aggregation accuracy with test fixtures
- [ ] **5.4** Decision tracker tests: verify effectiveness scoring calculation
- [ ] **5.5** Rankings computation tests: verify scoring formula and tie-breaking
- [ ] **5.6** Notification engine tests: mock Expo Push API, verify payload format
- [ ] **5.7** Admin endpoint access control tests: non-admin → 403
- [ ] **5.8** Rate limiter tests: verify burst limits and lockout behavior

### E2E Tests
- [ ] **5.9** Full flow: signup → create home → add device → ingest reading → view dashboard
- [ ] **5.10** Goal tracking: set goal → ingest readings → verify progress calculation
- [ ] **5.11** Decision tracking: send notification → user responds → verify impact calculation
- [ ] **5.12** Rankings: multiple homes → daily aggregation → verify leaderboard order

### Frontend Tests
- [ ] **5.13** Add Playwright/Cypress tests for user dashboard (login → view data → navigate tabs)
- [ ] **5.14** Add Playwright/Cypress tests for admin dashboard (login → view users → send alert)

---

## Phase 6: DOCUMENTATION & ACADEMIC
*Estimated: 2-3 days | Impact: Thesis support and professional credibility*

### Critical Fixes
- [ ] **6.1** **Replace Server Side/README.md** — currently describes wrong project (IAA air quality). Write WattWise-specific content covering FastAPI backend, MySQL schema, Docker services
- [ ] **6.2** Delete `architecture_analysis1.md` (stale duplicate of ARCHITECTURE.md)
- [ ] **6.3** Add `LICENSE` file (MIT or Apache 2.0)
- [ ] **6.4** Add `CONTRIBUTING.md` with code style, PR process, development setup
- [ ] **6.5** Add `CHANGELOG.md` starting from v4.0.0

### API Documentation
- [ ] **6.6** Export OpenAPI spec (`openapi.json`) from FastAPI and commit to repo
- [ ] **6.7** Create Postman collection with example requests for all 9 router modules
- [ ] **6.8** Add API examples with curl commands for common workflows

### PhD/Academic Documentation
- [ ] **6.9** Create `RESEARCH.md` — research questions, hypotheses, evaluation metrics, methodology
- [ ] **6.10** Create `ETHICS.md` — IRB/ethical approval reference, data privacy policy, GDPR compliance, consent procedures
- [ ] **6.11** Create database ER diagram (from MySQL schema) for thesis architecture chapter
- [ ] **6.12** Add screenshots of all dashboards to documentation

---

## Phase 7: POLISH & ADVANCED FEATURES
*Estimated: 5-7 days | Impact: "Wow factor" and research differentiation*

### Smart Features
- [ ] **7.1** Anomaly detection — alert when consumption deviates >2 standard deviations from 7-day average
- [ ] **7.2** Bill prediction — extrapolate monthly cost from current week's usage + UK tariff rates
- [ ] **7.3** Carbon footprint display — multiply kWh by UK grid intensity (~200g CO2/kWh)
- [ ] **7.4** Smart recommendations engine — "Run dishwasher after 7pm to save X"
- [ ] **7.5** Usage heatmap — time-of-day vs day-of-week matrix visualization

### Gamification & Engagement
- [ ] **7.6** Achievement badges system (first goal met, 7-day streak, top 10 rank, etc.)
- [ ] **7.7** Weekly challenges ("Reduce peak usage by 10% this week")
- [ ] **7.8** Community comparisons ("Your home uses X% less than average")

### Administration
- [ ] **7.9** Admin: bulk user operations (enable/disable notifications, reset passwords)
- [ ] **7.10** Admin: RPi device status monitoring (online/offline/last-seen)
- [ ] **7.11** Admin: Data quality dashboard (missing readings, gaps, stale devices)
- [ ] **7.12** Admin: Configurable alert thresholds (instead of hardcoded in config.py)

### Distribution
- [ ] **7.13** Set up Google Play Console account and internal testing track
- [ ] **7.14** Configure Play Store listing (description, screenshots, privacy policy URL)
- [ ] **7.15** Set up Firebase App Distribution for beta testing (alternative to sideloading)
- [ ] **7.16** Add QR code / download link on user dashboard for app installation

---

## Priority Matrix

```
                        HIGH IMPACT
                            |
          Phase 0           |          Phase 2
       (Security)           |       (Frontend TX)
                            |
  LOW EFFORT ---------------+--------------- HIGH EFFORT
                            |
          Phase 1           |          Phase 7
       (Backend)            |        (Advanced)
                            |
                        LOW IMPACT
```

## Recommended Execution Order

1. **Phase 0** (Security) — non-negotiable, do before anything else
2. **Phase 1** (Backend) — stabilize the foundation
3. **Phase 6.1** (Fix wrong README) — quick win, high embarrassment risk
4. **Phase 3.1-3.6** (Play Store blockers) — unblock distribution
5. **Phase 2.1-2.6** (Charts) — biggest visual transformation
6. **Phase 4.1-4.5** (Critical infra) — production reliability
7. **Phase 2.7-2.15** (UI polish) — professional appearance
8. **Phase 5** (Testing) — confidence for future changes
9. **Phase 6** (Documentation) — thesis support
10. **Phase 7** (Advanced) — research differentiation

---

## Success Criteria

When all phases are complete, WattWise should:

- [ ] Pass a security audit with zero CRITICAL findings
- [ ] Have 80%+ backend test coverage
- [ ] Load dashboards in <2 seconds with real-time updates
- [ ] Be installable from Google Play Store (internal track minimum)
- [ ] Have interactive charts with zoom, tooltips, and date range selection
- [ ] Support 50+ concurrent homes without performance degradation
- [ ] Have automated database backups with tested restore procedure
- [ ] Have centralized logging and monitoring with alerting
- [ ] Have complete API documentation with Postman collection
- [ ] Have academic documentation supporting thesis chapters 3-6
