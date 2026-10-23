# Daily Check-in Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Track steps below.

**Goal:** Implement the approved Daily Check-in UI and durable per-account login/capture/logout coordinator, with live execution disabled pending a user-authorized pilot.

**Architecture:** Existing FastAPI process owns scheduling; SQLite persists settings, runs, jobs, events and capture receipts. Session services share account exclusion. Reporter responses carry narrowly scoped capture requests; receipts are correlated with the validated session and committed before cleanup.

**Tech Stack:** Python, SQLite, FastAPI, Ruby/Lich, vanilla JavaScript/CSS.

**Spec:** ../specs/2026-10-23-daily-check-in-proposal.md

## Global constraints
- User explicitly forbids testing real logins/logouts while characters are online. No live service restart, reporter deployment, game commands, or scheduled activation this session.
- Existing dirty working-tree changes must be preserved; .git is read-only in the current sandbox. Work in place without commits or worktree mutations.
- `daily_checkin.allow_live_operations` defaults false independently of the persisted schedule setting. No background launch without both runtime permission and an explicitly enabled schedule.
- Tests use temporary state and fake sessions only. Existing characters are never automatically disconnected.

## Review focus
- Restart after launch before PID persisted: uncertain ownership blocks account, never duplicates login.
- Manual attachment and cleanup race: explicit takeover disables cleanup; attachments defer cleanup.
- Cached telemetry cannot satisfy a fresh capture; exact capture ID and session required.
- Stop/pause changes must survive restart and not accidentally restart the queue.
- Cross-account failure must not stop other accounts; same-account logout failure blocks successors.

## Tasks
1. Durable coordinator (`daily_checkin.py`, `test_daily_checkin.py`): tests first for default disabled, account serialization/parallelism, occupied accounts, partial capture, stop/pause, retries, persistence and midnight. Implement `CheckinCoordinator(config, service, telemetry, clock=time.time)`, `snapshot()`, `start_run(mode='due')`, `control(run_id, action)`, `tick()`, `report(data, session_id)` and `update_settings(data)`.
2. Session adapter (`gempy_service.py`, `account_guard.py`, `test_checkin_service.py`): tests first for occupied account rejection and ownership-safe headless startup. Add account reservation enforcement to all backend starts, with interprocess launch locking and persisted job reservations.
3. Reporter (`scripts/gempy_reporter.lic`, `test_reporter_checkin.rb`): fixture-test correlated capture requests, finite startup barrier, reward streak, field timestamps and no cached-field success. Add bounded command queue; response is parsed only for check-in requests targeted to this reporter. No script installation/restart.
4. Web API (`web_app.py`, `test_checkin_api.py`): fake-service tests for authentication/CSRF, disabled run rejection, settings, state and controls; wire coordinator into lifecycle and committed telemetry response. Add asset routes.
5. UI (`static/checkin.js`, `static/checkin.css`, existing navigation, `test_checkin.js`): account lanes and selected character timeline matching approved mockup, idle/disabled/error/paused/completed states, schedule dialog, retry and history, explicit sample preview. Poll only when active; restore navigation route.
6. Verify static/simulated behavior, independent review, fix material findings, document activation and deferred live pilot.

## Verification commands
- `python -m unittest test_daily_checkin test_checkin_api test_checkin_service` with temporary Windows-only test dependencies if needed.
- `ruby test_reporter_checkin.rb`, existing reporter parser checks.
- `node --test test_checkin.js`, existing status/tutelage/connection checks.
- Fake-service browser fixture only, no connection to running GemPy.

## Execution ledger
- Plan approved by user's “MAKE IT SO”; implementation continues inline without another approval handoff.
- Ruling: preserve dirty checkout and make narrow edits in place; git metadata is read-only and unrelated Status work is uncommitted.
- Ruling: retain standalone terminal support using shared interprocess account launch locks and durable check-in reservations instead of requiring terminal launches to call the web daemon. Process discovery protects already-running sessions after the launch lock releases.
- Ruling: autonomous outage watchdog deferred until installed Lich attachment arbitration can be verified in the later live pilot. Interrupted/uncertain sessions remain blocked for inspection; no speculative exit commands.
- Ruling: scripted startup must explicitly acknowledge a check-in barrier (`GempyReporter.checkin_ready!`) when configured finite startup scripts cannot be proven complete; time alone never implies script success.
- No real backend session operations have been performed.

## Staged implementation result

- Tasks 1–5 implemented in source: durable coordinator and receipts, account locks
  and reservations, reporter capture handshake, authenticated API, and the approved
  account-lane UI with a browser-local sample preview.
- Runtime configuration and live processes were not changed. The default live
  gate and schedule remain disabled. Reporter source was not deployed.
- Added explicit roster-edit exclusion during active/reserved work, previous-day
  queue expiration, historical reservation recovery, parsed-value validation,
  and bounded daily freshness scheduling during review.
- Ruling: failed captures/operations use explicit manual retry. Automatic failure
  retries are deferred; uncertain ownership always retains the reservation.
- Ruling: an already-online character blocks its account. This version does not
  retroactively certify existing user sessions from ordinary telemetry; it does
  not command or adopt them. Freshness is a target, not guaranteed while blocked.
- Independent source review completed. Fixed deeds capture (EXPERIENCE), receipt
  validation, historical recovery controls, and unrelated/repeated freshness
  scheduling. Automatic cleanup now refuses the attached-client branch and
  checks that its socket is the only observed client connection.
- **Remaining activation blocker:** external clients do not participate in
  GemPy's lock. The final socket check cannot eliminate an attachment immediately
  before the exit command. Lich-side ownership arbitration is required before
  enabling real automation; do not treat the disabled implementation as ready for
  live activation. The outage watchdog remains deferred for the same reason.

## Verification evidence (2026-10-23)

- **30 passed:** `test_daily_checkin`, `test_checkin_service`,
  `test_status_profiles`; fake sessions and temporary SQLite only. Windows tests
  used the writable temp directory and system Eastern-time zoneinfo data.
- **25 passed:** Node check-in, Status, Tutelage, Connections, and Invoker tests.
- Python compilation, JavaScript syntax checks, and `git diff --check` passed.
- FastAPI route tests could not run: Windows Python lacks FastAPI and dependency
  installation/network access is unavailable. Ruby fixtures (including positive
  complete command output) are written but could not run: installed Ruby fails
  to start and WSL execution is unavailable in this sandbox.
- Browser inspection could not run: isolated localhost fixture was inaccessible
  and browser policy rejects file URLs. No policy bypass was attempted. The
  synthetic fixture server was stopped; the real service was never contacted.
- Broader telemetry regression attempt encountered an existing Windows SQLite
  backup-handle cleanup error; weekly rotation tests also require missing
  FastAPI. These are not reported as passing. No unrelated implementation was
  changed to accommodate the test environment.
- Deferred: rendered browser QA, API integration, Ruby fixtures, Lich arbitration,
  and the explicitly user-deferred supervised real login/logout pilot.
