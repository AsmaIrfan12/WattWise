# Changelog

All notable changes to WattWise are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Security
- Replaced bulk in-memory notification load with single SQL UPDATE in mark-all-read endpoint
- Added field allowlists to all PATCH endpoints (prevents overwriting id/user_id via setattr)
- Added token denylist for logout (in-memory; resets on restart)
- Strengthened password validation: min 8 chars, requires uppercase + digit
- Added 50kW upper bound on power_watts field (energy sanity check)
- Fixed scheduler shutdown to wait=True (prevents mid-job data corruption)

### Performance
- Increased uvicorn workers from 1 to 4
- Added curl-based HEALTHCHECK to backend Dockerfile

### Infrastructure
- Added resource limits (CPU + memory) to all Docker services
- Added health checks to influxdb, admin-dashboard, user-dashboard containers
- Added mysql-backup service (daily dumps, 30-day retention)
- Added JSON-file logging with rotation to all containers
- Added backups/ directory and .gitkeep

### Documentation
- Rewrote Server Side/README.md (previously described wrong project — IAA air quality)
- Added LICENSE (MIT)
- Added CONTRIBUTING.md
- Added CHANGELOG.md
- Added deprecation notice to architecture_analysis1.md

---

## [4.0.0] — 2026-03-30

### Added
- Community release with 15-home production deployment
- Android app v4.0.0 (Kotlin + Jetpack Compose + Hilt) replacing web-only interface
- Expo push notifications for energy decision prompts
- Community leaderboard and energy rankings (efficiency + goal adherence + decision score)
- PhD research data collection: `user_decisions`, `user_interaction_logs` tables
- Decision effectiveness tracking (energy_before_kwh vs energy_after_kwh in 2-hour windows)
- Peak tariff detection and real-time alerts (16:00–19:00 UK peak, £0.32/kWh)
- PWA support on user dashboard (Service Worker, offline.html, manifest.json)
- Automated daily/weekly email reports via SMTP
- Data export endpoints (CSV) for research data extraction
- APScheduler with 8 background jobs
- Full Docker Compose orchestration (7 services)
- `/health`, `/health/dependencies`, `/health/slo`, `/metrics` observability endpoints
- In-memory metrics store (request counts, scheduler run history, auth failures)
- Sliding window rate limiter for login attempts

### Changed
- Migrated from polling to MQTT-based real-time sensor ingestion (30s publish cycle)
- Switched from single InfluxDB to dual-write (MySQL + InfluxDB) for relational + time-series
- Rebranded Android package from `com.iaa.userapp` → `com.wattwise.userapp`
- nginx now HTTP-only on port 80 — Cloudflare terminates external TLS
- CORS restricted to explicit methods and headers (no wildcard)

### Fixed
- MQTT reconnection handling on RPi publisher (graceful SIGTERM/SIGINT)
- Async SQLAlchemy session management (proper AsyncSessionLocal usage)
- Scheduler startup warnings for insecure default credentials

## [3.0.0] — 2025-12-01

### Added
- Multi-home support (one user → many homes)
- InfluxDB 1.8 time-series storage
- FastAPI backend replacing Flask

## [2.0.0] — 2025-09-01

### Added
- Raspberry Pi MQTT publisher (rpi_mqtt_publisher.py)
- Home Assistant integration for Tapo P110 smart plug readings
- MySQL database schema for energy monitoring

## [1.0.0] — 2025-06-01

### Added
- Initial prototype: Flask backend, single home, manual CSV import
