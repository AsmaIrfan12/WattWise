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

## 2026-11-16 — Rows shared by concurrent writers must not be updated inside each writer's transaction
- **What happened:** I added "last seen" tracking by updating the `homes` row inside every
  reading's insert transaction. A home's six devices report in the same instant, so six
  transactions fought over one row and MySQL deadlocked; the losing reading was dropped.
  A single-message test could not show it — it appeared only under the real traffic shape.
- **Rule:** when many concurrent units of work touch one shared row (a parent, a counter,
  a "last seen"), update it outside their transactions, throttled and claimed by one
  writer. And test ingestion changes with a realistic burst (all of a home's devices at
  once), not one message.

## Android: "it builds" must mean the release build, and "it works" means run it (2026-11-19)

- I had declared the Android work done after `assembleDebug` + unit tests. The **release**
  build (what Android Studio exports) was broken twice over: launcher icons were JPEGs
  named `.png` (debug does not crunch PNGs, release does), and a lint-vital error on the
  WorkManager manifest entry. Rule: for Android always run `assembleRelease` as well.
- That manifest entry also meant the background alert worker could never be created, so
  "background polling fixed" in Phase 1 was untrue on a device. Unit tests cannot see
  this. Rule: anything involving WorkManager, the WebView, notifications or sign-in is
  verified on the emulator (AVD `Pixel_7`, driver script pattern: adb + uiautomator dump),
  not inferred from a compile.
- Emulator gotchas: `adb shell input text` drops everything after a hyphen (send
  KEYCODE_MINUS); WorkManager jobs live in the `androidx.work.systemjobscheduler`
  namespace and cannot be forced before their period; set `MSYS_NO_PATHCONV=1` in Git Bash.
- A web page without `Cache-Control` is cached heuristically for hours by browsers and the
  WebView, so a dashboard deploy looked like it "did not work" in the app. The dashboard
  now sends `no-cache`. After any frontend deploy, check the header, not only HTTP 200.

## 2026-11-25 — One community: real and synthetic accounts are treated the same
- **Correction from Suhas:** "consider all real or synthetic users equally in the system". In
  Phase 1 I had separated them (rankings per cohort, admin default "Real"), so the one home
  with a Raspberry Pi was ranked "1 of 1" and never appeared with the 50 generated homes.
- **Rule:** every ranking, analytic, alert rule and default view covers ALL accounts.
  `users.is_synthetic` / `user_decisions.is_simulated` stay as labels and optional filters
  only. Never add a code path that branches on them. The only places that still look at the
  flag are the two data generators (readings, decision simulator), which write to synthetic
  accounts only, and the guard that refuses to attach a Raspberry Pi to a synthetic account.
  `tests/test_health_tips_and_community.py::TestOneCommunity` enforces this.
- This supersedes the earlier "keep but flag and separate" decision: keep the flag, drop the
  separation.

## 2026-11-25 — Features of "the previous app" live in `old/`; an unanswered question is still open
- **Correction from Suhas:** the health suggestions on alerts were "one of the distinctive
  features" and I had not carried them over. He had mentioned "health feedback" on 16 Nov; I
  asked what it meant, got no answer, and let it drop for nine days.
- **Rule:** when Suhas refers to something the previous/old/single-user app did, search
  `old/` first (`old/services/energy-calculator.js` holds the notification texts and the
  scenario structure) before asking or guessing. `old/` is NOT the paper folder: it is a
  valid source of intent.
- **Rule:** a clarifying question that gets no answer is not closed. Look for the answer in
  the repo, and if it still matters, raise it again in the next report instead of dropping it.
- When an old file spells out one example and says the rest "follow the same structure"
  (the dryer's four notifications), use the example word for word, build the rest in that
  exact structure, and say plainly which texts are original and which are new.

## 2026-11-25 — A phone WebView is not a narrow desktop browser
- The dashboard's seven tabs were unreachable on a phone (squeezed into a hidden-scrollbar
  strip one tab wide). I had tested the dashboard only at desktop width. **Rule:** every
  dashboard change is checked at 412px wide AND inside the app's WebView.
- Chrome's device emulation passed a layout that broke in the real WebView: a `<canvas>`
  (300px intrinsic width) in a flex item widened the page, and the WebView then stretched the
  fixed tab bar off-screen. **How to see what the WebView really does:** debug builds call
  `WebView.setWebContentsDebuggingEnabled(true)`; then
  `adb forward tcp:9333 localabstract:webview_devtools_remote_<pid>` and Playwright
  `connect_over_cdp("http://127.0.0.1:9333")`. Port 9222 is taken on this machine.
- `position: fixed` is anchored to any ancestor that has `backdrop-filter` (or transform /
  filter). A fixed bar inside the blurred header was pinned to the header, not the screen.
- A periodic "refresh the open section" timer must never redraw under the user: it closed an
  open device panel every 30 s.
- Selectors in UI tests must be scoped to the visible section (`#s-notifications …`,
  `#device-list …`): the same classes exist in hidden sections once real data is present.

## 2026-11-25 — "Fixed" means I watched the exact flow work
- On 19 Nov I reported "changing the server address kept loading the old server" as fixed
  after changing one code path, without doing it on the emulator. It was still broken (the
  WebView was created with a stale address). **Rule:** a user-visible fix is reported as done
  only after performing that exact flow on the emulator and seeing the result.
- Local stand-ins have their own bugs: Python's `http.server` speaks HTTP/1.0 and the
  emulator's NAT truncated its replies ("unexpected end of stream"). Rule out the test
  harness before blaming the app, and say in the report which of the two it was.
- Replacing a container still causes about 20 s of 502 on its public route while the proxy
  re-resolves it. After every deploy, poll the public URL until it returns 200.
