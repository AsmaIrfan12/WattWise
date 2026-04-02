# WattWise Full Project Inspection Report

**Date:** 2026-03-30
**Version Inspected:** v4.0.0 (Community Release)
**Inspector:** Claude Code (Opus 4.6) - Deep automated audit across all layers

---

## Executive Summary

WattWise is a **well-architected PhD research platform** with solid foundations across all three layers (Sensing, Backend, Mobile). The codebase demonstrates good design decisions — MVVM on Android, async FastAPI backend, dual-write database strategy, Docker containerization.

However, the project currently reads as a **functional research prototype** rather than a **professional production platform**. There are critical gaps in security hardening, observability, frontend polish, testing coverage, and Play Store readiness that must be addressed to reach the "advanced high-tech team" standard.

### Overall Scores by Layer

| Layer | Architecture | Security | Code Quality | Testing | Polish | Overall |
|-------|-------------|----------|-------------|---------|--------|---------|
| **Backend API** | 8/10 | 4/10 | 7/10 | 2/10 | 5/10 | **5.2/10** |
| **Android App** | 9/10 | 4/10 | 8/10 | 2/10 | 7/10 | **6.0/10** |
| **Admin Dashboard** | 5/10 | 5/10 | 5/10 | 0/10 | 4/10 | **3.8/10** |
| **User Dashboard** | 6/10 | 5/10 | 5/10 | 0/10 | 5/10 | **4.2/10** |
| **DevOps/Infra** | 5/10 | 3/10 | 5/10 | 4/10 | 3/10 | **4.0/10** |
| **Sensing Layer** | 7/10 | 5/10 | 6/10 | 0/10 | 5/10 | **4.6/10** |
| **Documentation** | 7/10 | N/A | N/A | N/A | 6/10 | **6.5/10** |

**Composite Score: 4.9/10** (Functional prototype, not production-grade)

---

## PART 1: WHAT'S GOOD (Strengths)

### 1.1 Architecture & Design Decisions
- **Dual-write pattern** (MySQL + InfluxDB) is smart — relational for queries, time-series for charts
- **MQTT-based IoT pipeline** is industry-standard for sensor data ingestion
- **Android MVVM + Hilt + Compose** is modern best-practice architecture
- **FastAPI async backend** with SQLAlchemy 2.x is performant and well-structured
- **Docker Compose** orchestration covers all 7 services cleanly
- **Cloudflare Tunnel** avoids opening ports directly — good security posture
- **APScheduler** for 8 background jobs (aggregation, rankings, notifications) is well-organized

### 1.2 Backend API
- Clean router separation (9 modules covering auth, devices, readings, goals, decisions, analysis, admin, export, notifications)
- 15 SQLAlchemy ORM models with proper foreign key relationships
- Pydantic settings for configuration management
- JWT authentication middleware with public path exclusions
- Rate limiting on auth endpoints (10/min) and API (60/min)
- PhD research tables (`user_decisions`, `user_interaction_logs`, `energy_rankings`) are well-designed for behavioral analytics

### 1.3 Android App
- Excellent MVVM adherence with clean layer separation (data/domain/ui/di)
- Reactive data flow using Kotlin Flows and StateFlow
- Proper Hilt dependency injection throughout
- Dynamic server URL with runtime switching (no rebuild required)
- Good error handling with visual feedback (error banners, loading spinners, retry buttons)
- Smooth entrance animations on auth screens
- Pull-to-refresh on WebView
- Network connectivity observer with real-time status

### 1.4 User Dashboard
- PWA-capable with Service Worker, manifest.json, and offline fallback page
- Device-level energy tracking with per-device cost calculations
- Peak tariff detection and display
- Notification action system (Accept/Defer/Reject decisions for PhD research)
- Goal progress tracking with color-coded visual bars
- Community leaderboard with score breakdown

### 1.5 Sensing Layer
- YAML-based configuration separates deployment from code
- Graceful shutdown with SIGTERM/SIGINT handlers
- Publishes offline status before exit
- Multi-device support per home
- Systemd service file for reliable startup

### 1.6 DevOps
- CI/CD pipeline with 3 jobs: test → build Android → build Docker + deploy
- MySQL health check with proper interval/retry configuration
- nginx security headers (X-Frame-Options, HSTS, X-Content-Type-Options, Referrer-Policy)
- .gitignore properly excludes .env, credentials, node_modules
- Compressed row format on high-volume `energy_readings` table
- Composite indexes on hot query paths

---

## PART 2: WHAT'S BAD (Critical Issues)

### 2.1 SECURITY (22 issues found)

#### CRITICAL
| # | Issue | Location | Risk |
|---|-------|----------|------|
| S1 | **MQTT anonymous access enabled** in production config | `mosquitto/config/mosquitto.conf:29` | Anyone can read/write all sensor data |
| S2 | **Hardcoded admin password hash** in SQL schema | `mysql/init/01-schema.sql:303-307` | Visible in git history forever |
| S3 | **Default "changeme" credentials** for all services | `backend/app/config.py:11,14,21,30,57` | Production deployment with weak secrets |
| S4 | **Cleartext traffic enabled** on Android | `network_security_config.xml:16` + `AndroidManifest.xml:27` | Play Store rejection + MITM attack |
| S5 | **SSL error bypass** in debug builds | `MainScreen.kt:178-190` | Accepts forged certificates |
| S6 | **CORS allows all headers/methods** with credentials | `main.py:153-160` | Cross-origin exploit surface |

#### HIGH
| # | Issue | Location | Risk |
|---|-------|----------|------|
| S7 | JWT token exposed in URL fragment | `MainViewModel.kt:38` `#ww_token=` | Token in logs/history/referrer |
| S8 | No token revocation (logout is a no-op) | `routers/auth.py:188-192` | Stolen tokens valid for 7 days |
| S9 | XSS in both frontends (unsanitized template literals) | `app.js:127`, user `index.html:456` | Injected scripts via user names |
| S10 | `threading.Lock` in async FastAPI code | `security.py:14-48` | Rate limiter bottleneck under load |
| S11 | SQL injection in RPi InfluxDB queries | `rpi_mqtt_publisher.py:86-100` | Malicious entity_id can query anything |
| S12 | Password requires only 6 chars, no complexity | `routers/auth.py:13` | Trivially brute-forceable |
| S13 | `allowBackup="true"` on Android | `AndroidManifest.xml:20` | Attacker can extract tokens via adb |
| S14 | No MQTT TLS (port 8883 commented out) | `mosquitto.conf:15-22` | Sensor data in plaintext |

#### MEDIUM
| # | Issue | Location | Risk |
|---|-------|----------|------|
| S15 | Token stored in plain DataStore (not encrypted) | `TokenDataStore.kt:34-62` | Extractable on rooted device |
| S16 | `setattr()` bulk update without field allowlist | `routers/devices.py:57`, `goals.py:131` | Can overwrite `id`, `user_id` |
| S17 | Admin flag from middleware not re-verified per request | `routers/admin.py:26-31` | Middleware spoofing risk |
| S18 | No CSRF tokens on frontend forms | Both frontends | State-changing via cross-site |
| S19 | No input validation on notification form | Admin frontend | Malicious content injection |
| S20 | Health endpoint publicly exposed without rate limit | `nginx.conf:70-74` | Info disclosure + DDoS vector |
| S21 | `unsafe-inline` in CSP for scripts | Frontend nginx configs | Inline script injection |
| S22 | No data sanity checks on energy values | `schemas.py:92` | Accepts 1 billion watts |

### 2.2 PERFORMANCE (8 issues)

| # | Issue | Location | Impact |
|---|-------|----------|--------|
| P1 | N+1 queries in rankings computation (3 queries per home) | `scheduler.py:299-325` | 1000 homes = 3000+ queries |
| P2 | N+1 queries in leaderboard endpoint | `routers/analysis.py:79-100` | Slow page load |
| P3 | Auth middleware queries DB on EVERY request for is_admin | `main.py:239` | Blocks all request processing |
| P4 | Blocking InfluxDB writes in async MQTT handler | `mqtt_client.py:89-118` | Drops messages under load |
| P5 | `mark_all_read` loads ALL notifications into memory | `routers/notifications.py:92-101` | OOM on 10K+ unread |
| P6 | Single uvicorn worker in Docker | `Dockerfile:19` | Serializes all requests |
| P7 | Missing indexes on `notification.user_id`, `device.home_id`, `user_decision.user_id` | `models.py` | Slow filtered queries |
| P8 | No pagination metadata (total, has_more) | Multiple routers | Client can't implement pagination |

### 2.3 FRONTEND QUALITY (Both Dashboards)

| # | Issue | Impact |
|---|-------|--------|
| F1 | **No charting library** — bar charts are DIV elements with calculated heights | Looks amateurish, no interactivity |
| F2 | **No real-time updates** — WebSocket infrastructure exists but unused | Data feels stale |
| F3 | **Admin dashboard not mobile responsive** — fixed 220px sidebar, no hamburger menu | Unusable on phone |
| F4 | **No skeleton loaders** — just "Loading..." text and "—" placeholders | Feels unpolished |
| F5 | **All JavaScript inline** in user frontend (571 lines in single HTML file) | Unmaintainable |
| F6 | **No accessibility** — emoji nav icons, no ARIA labels, color-only indicators | Screen reader hostile |
| F7 | **Only 7-day charts** — no date range picker, no historical comparison | Limited analytics |
| F8 | **No data export** from dashboards (CSV, PDF) | Admin can't generate reports |
| F9 | **No dark/light theme toggle** | Fixed dark theme only |
| F10 | **No 404 or proper error pages** | White screen on bad routes |

### 2.4 ANDROID APP GAPS

| # | Issue | Impact |
|---|-------|--------|
| A1 | **No crash reporting** (Crashlytics dependency exists but not integrated) | Silent failures in production |
| A2 | **No analytics** (Firebase Analytics in BOM but unused) | Zero visibility into user behavior |
| A3 | **No app signing configuration** in build.gradle.kts | Can't release to Play Store |
| A4 | **No logout button** anywhere in the app | User trapped in session |
| A5 | **No password reset flow** | "Forgot password?" missing from login |
| A6 | **Only 1 test file** (SettingsViewModelTest with 2 tests) | ~2% code coverage |
| A7 | **WebView state lost on rotation** | Page reloads on orientation change |
| A8 | **No in-app update mechanism** | Users stuck on old versions |
| A9 | **No privacy policy** / GDPR consent in app | Play Store will reject |
| A10 | **ktlint and detekt declared but not applied** in build config | No code quality enforcement |

### 2.5 DEVOPS & INFRASTRUCTURE

| # | Issue | Impact |
|---|-------|--------|
| D1 | **No database backup strategy** | Data loss on crash |
| D2 | **No centralized logging** (logs scattered across 5+ locations) | Can't debug production issues |
| D3 | **No resource limits** on any Docker container | One service can OOM-kill host |
| D4 | **InfluxDB 1.8 is EOL** (end-of-life since Nov 2023) | No security patches |
| D5 | **No Prometheus/metrics endpoint** | Zero observability |
| D6 | **No health checks** on frontend containers or InfluxDB | Can't detect failures |
| D7 | **CI/CD deploys with hard cutover** (no blue-green/canary) | Downtime on every deploy |
| D8 | **No test coverage enforcement** in CI | Tests can silently degrade |
| D9 | **MQTT ACLs are static** (only 2 homes hardcoded) | New homes have no MQTT security |
| D10 | **RPi publisher has no retry/backoff** — crashes on first failure | Lost data during outages |

### 2.6 DOCUMENTATION

| # | Issue | Impact |
|---|-------|--------|
| DOC1 | **Server Side/README.md describes WRONG PROJECT** (IAA air quality, not WattWise) | Catastrophically misleading |
| DOC2 | **No LICENSE file** | IP/legal ambiguity |
| DOC3 | **No API documentation** beyond auto-generated Swagger | Hard for others to integrate |
| DOC4 | **No research methodology document** | Cannot support thesis chapter |
| DOC5 | **No ethics/GDPR compliance docs** | Required for human subjects research |
| DOC6 | **architecture_analysis1.md is a stale duplicate** of ARCHITECTURE.md | Confusing |

### 2.7 TESTING (Project-Wide)

| Component | Tests | Coverage | Grade |
|-----------|-------|----------|-------|
| Backend API | 2 files (health + security) | ~5% | F |
| Android App | 1 file (2 tests) | ~2% | F |
| Admin Frontend | 0 | 0% | F |
| User Frontend | 0 | 0% | F |
| Sensing Layer | 0 | 0% | F |
| E2E Integration | 0 | 0% | F |

---

## PART 3: WHAT COMPETITORS HAVE THAT WATTWISE DOESN'T

Professional energy platforms (Octopus Energy, Bulb, British Gas, Sense Home) provide:

| Feature | Competitors | WattWise | Priority |
|---------|------------|----------|----------|
| Real-time consumption dashboard | Yes (live WebSocket) | No (manual refresh) | HIGH |
| Time-series line graphs | Yes (D3/Recharts) | No (DIV bars only) | HIGH |
| Bill/cost prediction | Yes ("You'll spend ~X this month") | No | HIGH |
| Carbon footprint tracking | Yes (CO2 per kWh) | No | MEDIUM |
| Smart recommendations | Yes ("Run dishwasher at 11pm") | No | HIGH |
| Usage comparison vs similar homes | Yes (percentile rank) | Partial (leaderboard) | MEDIUM |
| Historical trend analysis | Yes (month/year views) | 7 days only | HIGH |
| PDF/CSV export | Yes (bills, reports) | No | MEDIUM |
| Push notification customization | Yes (mute types, quiet hours) | No | LOW |
| Device scheduling/automation | Yes (smart plugs control) | No (read-only) | LOW |
| Multi-home management UI | Backend supports it | No UI for it | MEDIUM |
| Gamification (badges, challenges) | Yes | No (leaderboard only) | MEDIUM |
| API versioning | Yes (/api/v1/) | No (breaking changes risk) | MEDIUM |

---

## PART 4: ERRORS FOUND

### Confirmed Bugs

1. **Router count mismatch in CLAUDE.md** — says "11 modules" but only 9 exist (already fixed)
2. **`readings` listed twice** in router list (already fixed)
3. **Logout endpoint does nothing** — `auth.py:188-192` returns success without invalidating token
4. **`mark_all_read` loads entire notification set into memory** instead of bulk UPDATE
5. **MySQL-specific `func.IF()` in decision_tracker.py** — will break on any other database
6. **RPi publisher crashes on first MQTT connection failure** instead of retrying
7. **Heartbeat interval is 5 minutes** — too slow to detect hung publisher
8. **No unique constraint on duplicate energy readings** — concurrent MQTT messages can create duplicates
9. **`energy_goals` table allows duplicate goals** per user for same device (no unique constraint)
10. **Scheduler `shutdown(wait=False)` can corrupt data** if jobs are mid-execution

---

## PART 5: MISSING FEATURES FOR "PROFESSIONAL TEAM" LOOK

### Must-Have for Professional Appearance
1. **Professional charting library** (Chart.js / ApexCharts / Recharts) with interactive tooltips, zoom, and export
2. **Real-time WebSocket updates** on dashboards (infrastructure already exists in nginx)
3. **Proper loading states** (skeleton loaders, shimmer effects, progress bars)
4. **Mobile-responsive admin dashboard** with hamburger nav
5. **Date range picker** on all analytics views
6. **API versioning** (`/api/v1/`) to prevent breaking changes
7. **Structured error responses** with error codes (not just text messages)
8. **Comprehensive test suite** (at least 80% backend coverage)
9. **Firebase Crashlytics + Analytics** on Android
10. **App signing + release build configuration**

### Nice-to-Have for "Wow Factor"
1. Animated data transitions on charts
2. Dark/light theme toggle
3. Carbon footprint calculator (UK grid intensity: ~200g CO2/kWh)
4. Bill prediction with trend extrapolation
5. Device usage heatmap (time-of-day vs day-of-week)
6. Email digest with embedded charts (weekly report)
7. Anomaly detection alerts ("Unusually high consumption detected")
8. Comparative analytics ("Your home vs community average")
9. Achievement badges and challenges
10. In-app feedback mechanism

---

*Report continues in TODO plan below...*
