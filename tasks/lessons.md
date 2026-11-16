# Lessons

Rules written after corrections from the user. Review at session start.

## 2026-11-16 — Do not use `Asma_PAPER3_06_JUNE_V1/` as a source of truth
- **What happened:** when answering how the system works, I compared the code against
  claims in the paper folder (Faker/SDV, Z-score alerts) and reported the mismatches as
  findings.
- **Correction (Suhas):** "do not consider anything from the asma paper folder" — that
  folder is a paper *based on* WattWise, not a specification for it.
- **Rule:** the system's intent comes from Suhas's own description and the code/docs
  outside that folder. Never read, cite, or reconcile against `Asma_PAPER3_06_JUNE_V1/`
  (or `docs/` paper drafts) unless he explicitly asks. Exclude it from searches and from
  subagent briefs.

## System intent (stated by Suhas, 2026-11-16) — design against this
Community-level energy monitoring: an RPi running a smart-home OS in each home, many
devices per RPi sending data to this server → automated alerts (and manual admin
alerts) go to user accounts → the user opens the alert, takes an action and reports
it → the decision is recorded and visible in the admin portal → the system analyses
usage based on those interactions.

## 2026-11-16 — Verify through the PUBLIC entry point after every deploy
- **What happened:** I redeployed single services (`docker compose up -d --build user-dashboard`)
  and checked them on their own ports. The public proxy on port 80 still held the old
  container address and served 502 for the dashboard for about 20 minutes before I noticed.
- **Rule:** after any deploy, check the routes users actually hit — `http://<server>/`,
  `/health`, `/admin/`, and `:3000/api/...` — not just the container's own port or
  `docker compose ps`. (The nginx configs now re-resolve upstreams, but the check stays.)
- **Rule:** files copied into a container with `docker cp` vanish when it is recreated;
  re-copy before re-running a check, and never read "no output" as "passed".
