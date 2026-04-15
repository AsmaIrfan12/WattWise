# WattWise Improvement Plan

**Date:** 2026-04-15
**Scope:** Whole-platform improvement plan for the sensing layer, backend, dashboards, Android app, and deployment stack.
**Intent:** Move WattWise from a capable research prototype to a secure, reliable, pilot-ready platform that can support community deployment and PhD research outputs.

## 1. Target Outcome

Over the next 8 to 12 weeks, WattWise should reach a state where it is:

- secure enough for external users and Play Store review
- reliable enough to survive common network, device, and deployment failures
- polished enough to look like a professional energy platform rather than a lab prototype
- measurable enough to support research claims with reproducible data and test evidence

## 2. Current State Summary

Based on the existing audit and action-plan documents, the highest-risk weaknesses are concentrated in five areas:

1. Security gaps in MQTT, secrets, Android traffic rules, token handling, and input validation.
2. Reliability gaps in ingestion, retries, backups, health checks, and observability.
3. Product quality gaps in dashboard UX, charting, responsiveness, and real-time updates.
4. Release-readiness gaps in the Android app, especially signing, privacy, crash reporting, and auth flows.
5. Verification gaps caused by low test coverage and incomplete operational documentation.

## 3. Prioritization Rules

Work should be sequenced with this order of importance:

1. Fix anything that can leak data, break trust, or block external release.
2. Fix anything that can silently lose readings or corrupt research data.
3. Improve the main user journeys before building advanced features.
4. Add tests and observability around stabilized behavior, not around unstable code.
5. Delay differentiating features until the platform is operationally credible.

## 4. Phased Plan

## Phase 1: Secure The Platform
**Window:** Week 1-2
**Goal:** Remove the issues most likely to cause data exposure, account compromise, or release rejection.

### Focus

- Disable anonymous MQTT access and enable authenticated ACL-based access.
- Remove hardcoded secrets and fail startup when required env vars are missing.
- Lock down Android cleartext traffic and backup behavior.
- Stop exposing JWTs in URL fragments and improve token storage.
- Restrict CORS, add input sanity checks, and tighten password rules.

### Deliverables

- MQTT broker requires authentication for all clients.
- Backend starts only with valid secrets and configuration.
- Android network policy is Play Store safe.
- Tokens are no longer exposed through URLs or easy device extraction paths.
- Basic XSS and unsafe mass-assignment risks are reduced.

### Exit Criteria

- No critical or high-severity issue from the current audit remains open in auth, MQTT, or Android networking.
- Backend and Android security checks pass without manual workarounds.

## Phase 2: Make Data Collection And Operations Reliable
**Window:** Week 2-4
**Goal:** Ensure WattWise can ingest, persist, and expose energy data consistently under normal failure conditions.

### Focus

- Add retry and backoff logic to the Raspberry Pi publisher.
- Add local buffering when MQTT or cloud connectivity is unavailable.
- Prevent duplicate readings with constraints and validation.
- Improve backend performance on hot paths and remove obvious N+1 patterns.
- Add container health checks, backups, resource limits, and basic metrics.

### Deliverables

- Sensor outages no longer cause immediate publisher failure or silent data loss.
- Duplicate or impossible readings are rejected or contained.
- Backend endpoints for analysis, notifications, and rankings perform predictably.
- Daily database backup and restore workflow exists and is documented.
- Deployments have health signals instead of relying on manual inspection.

### Exit Criteria

- A simulated broker outage does not lose readings permanently.
- Restore from backup is demonstrated.
- Core backend services expose health status and basic operational telemetry.

## Phase 3: Improve The Core User Experience
**Window:** Week 4-6
**Goal:** Upgrade the dashboards so they communicate value clearly and feel production-grade.

### Focus

- Replace improvised chart visuals with a real charting library.
- Add date-range selection and more useful historical views.
- Add real-time updates for readings and notifications where infrastructure already supports it.
- Fix mobile responsiveness, especially on the admin dashboard.
- Replace raw loading text with skeleton states, toasts, and stronger empty/error handling.

### Deliverables

- User dashboard shows interactive historical energy views.
- Admin dashboard is usable on tablet and mobile.
- Real-time or near-real-time feedback exists for active readings and alerts.
- UX states are consistent across loading, success, error, and empty scenarios.

### Exit Criteria

- A new user can log in, understand current usage, inspect trends, and interpret goals without explanation.
- An admin can review core metrics and user data comfortably on common screen sizes.

## Phase 4: Finish Android Release Readiness
**Window:** Week 6-8
**Goal:** Bring the Android app to a standard suitable for internal testing and Play Store submission.

### Focus

- Add app signing, Crashlytics, analytics, and release-safe configuration.
- Add logout and forgot-password flows.
- Preserve important state across rotation and process recreation.
- Add privacy-policy access and consent handling.
- Improve accessibility and remove hardcoded strings.

### Deliverables

- Signed debug and release builds.
- Crash reporting and app analytics available.
- Auth flows cover login, signup, logout, and password recovery.
- App has the minimum compliance surface for store review.

### Exit Criteria

- Internal testers can install, authenticate, recover from common failures, and complete daily use without developer help.
- Release build is reproducible and documented.

## Phase 5: Add Quality Gates And Research Readiness
**Window:** Week 8-10
**Goal:** Prove the platform works and support research operations with defensible evidence.

### Focus

- Add backend integration tests for auth, ingestion, aggregation, notifications, and admin access control.
- Add Android unit tests for auth and server configuration flows.
- Add frontend E2E coverage for main dashboard journeys.
- Publish accurate backend, deployment, API, and research documentation.
- Add ethics, data handling, and methodology artifacts needed for academic use.

### Deliverables

- Regression coverage exists for the flows most likely to break pilot deployments.
- Documentation matches the actual WattWise architecture.
- Research-facing documentation is sufficient to support thesis chapters and external review.

### Exit Criteria

- CI blocks regressions on the critical user and ingestion paths.
- Project documents no longer describe outdated or unrelated systems.

## Phase 6: Build Differentiating Features After Stability
**Window:** Post-pilot / Week 10+
**Goal:** Add features that strengthen engagement and research novelty without destabilizing the core platform.

### Candidates

- bill prediction
- anomaly detection
- carbon footprint estimation
- comparative community analytics
- achievement and challenge systems
- configurable smart recommendations

### Rule For This Phase

Only start these after the earlier phases are complete enough that new features are not masking unresolved platform debt.

## 5. Suggested Workstreams

To avoid bottlenecks, the plan can run in three parallel workstreams once Phase 1 starts settling:

- **Platform workstream:** backend, MQTT, DB constraints, Docker, backups, observability
- **Experience workstream:** user dashboard, admin dashboard, charting, UX states, responsiveness
- **Mobile workstream:** Android release hardening, auth UX, app quality, store readiness

Shared cross-cutting tasks should stay centralized:

- security decisions
- schema changes
- test strategy
- release documentation

## 6. Concrete 30-Day Plan

If you want the highest-value start, the next 30 days should look like this:

### Days 1-10

- close critical security findings
- secure MQTT and secrets handling
- harden Android network and token behavior
- add data sanity checks and duplicate prevention

### Days 11-20

- add ingestion retry/buffer behavior
- add health checks, backups, and resource limits
- fix backend hot-path performance issues
- document restore and deployment checks

### Days 21-30

- ship real charting on the user dashboard
- improve admin responsiveness
- add skeleton states and toasts
- prepare Android release pipeline basics

## 7. Success Metrics

Track progress with a small set of measurable outcomes:

- **Security:** zero open critical findings in MQTT, auth, Android transport, or secrets.
- **Reliability:** successful recovery from simulated network outage and backup restore drill.
- **Performance:** dashboard and analysis endpoints stay responsive under representative dataset volume.
- **Quality:** automated coverage exists for critical auth, ingestion, and dashboard flows.
- **Release readiness:** signed Android release build with crash reporting and privacy surface in place.
- **Research readiness:** architecture, ethics, and methodology documents reflect the live system.

## 8. Recommended Immediate Next Actions

1. Convert Phase 1 into a tracked issue list with owners and target dates.
2. Execute one security hardening pass across MQTT, backend config, and Android transport rules.
3. Follow that immediately with a reliability pass on ingestion, health checks, and backups.
4. Start dashboard polish only after the platform stops carrying critical operational risk.
