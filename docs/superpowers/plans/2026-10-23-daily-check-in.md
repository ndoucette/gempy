# Daily Check-in Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans. Track steps below.

**Goal:** Implement the approved Daily Check-in UI and durable per-account login/capture/logout coordinator, with live execution disabled pending a user-authorized pilot.

**Architecture:** Existing FastAPI process owns scheduling; SQLite persists settings, runs, jobs, events and capture receipts. Session services share account exclusion. Reporter responses carry narrowly scoped capture requests; receipts are correlated with the validated session and committed before cleanup.

**Tech Stack:** Python, SQLite, FastAPI, Ruby/Lich, vanilla JavaScript/CSS.

**Spec:** ../specs/2026-10-23-daily-check-in-proposal.md

## Global constraints
- Original session forbade live operations. **Current authorization:** user logged out and authorized a supervised login/logout pilot, beginning with one character. Check sessions first; recurring scheduling stays disabled. See continuation results below.
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
- **Pre-pilot activation blocker (resolved in continuation below):** external clients do not participate in
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

## Authorized pilot continuation (2026-10-23)

- User now explicitly authorizes live login/logout testing after logging out.
  This supersedes the earlier no-live-session constraint for this supervised
  pilot only. Preserve checkout; recurring scheduling remains disabled.
- Initial host discovery: no Linux Lich sessions; Windows game/Ruby process
  query returned none; GemPy discovery returned `[]`. Old disconnected Vellum
  processes remain and were not stopped. No existing runs/reservations; schedule
  defaults false; persisted config has no live opt-in.
- Cleanup uses a Ruby preload before Lich initialization and a private UNIX
  control socket. Client registration, takeover, and logout share one Lich-side
  ownership lock. Any external attachment permanently revokes automation;
  logout fences subsequent registration. Exact capture ID and process identity
  are required. There is no fallback to sending `exit` via a frontend.
- Takeover waits for Lich acknowledgment before releasing its reservation.
- Ruling: run one temporary loopback pilot server using the normal durable DB
  and a runtime-only Prepotente scope. The full roster stays available for
  account exclusion; neither config live opt-in nor recurrence is enabled.
- Ruling: installed Lich exposes `completed_successfully?`; track actual script
  objects, including ExecScript/SubScript, and require successful completion of
  finite startup scripts. Only inspected background scripts are exempt.
- Fresh review identified premature logout acknowledgment ordering and a child
  startup snapshot race. Both reproduced RED and fixed GREEN. A real local
  Ruby socket fixture confirms identity refusal, acknowledgment, and closure.
- Offline evidence so far: 43 Python coordinator/adapter/API/profile tests,
  10 Ruby ownership/startup tests (26 assertions), reporter parser fixtures,
  and the local Ruby socket integration test pass. Live pilot pending.


### One-character live result — PASS

- **Prepotente only**, Prime, run `552aff9d63f97b7bb0d4ce43`.
  Started 2026-10-23 16:07:58 PDT; complete at 16:08:35 PDT (~37 seconds).
- Authenticated login confirmed by Lich at 16:08:06. Startup readiness used
  actual successful results for autostart, repository, alias, and lumnismon;
  log, keepalive, bank, and gempy_reporter remained expected background scripts.
- Fresh correlated captures: identity, all ten stats, skills, Lumnis/bonuses,
  XP, Bard resources, deeds, and login rewards. Observed streak **15 days**.
  Optional bank data remained unavailable outside a bank; no runner use.
- Capture committed before logout. Lich logged orderly shutdown complete at
  16:08:33. Coordinator confirmed exact process closure and released reservation.
- Reopened SQLite after stopping the pilot server: **one durable capture and six
  profile sections**. Final independent host inspection: sessions `[]`, zero
  reservations, run complete, persisted live gate false, schedule default false.
- Reporter deployed with backup at
  `/home/nick/gs4/Lich5/scripts/custom/gempy_reporter.lic.before-checkin-pilot-20261023.bak`.
  Regular GemPy daemon was not restarted. Pilot server was stopped.
- Evidence: `/tmp/gempy-one-pilot.log`,
  `/tmp/gempy-pilot-552aff9d63f97b7bb0d4ce43.json`, and pre-pilot SQLite backup
  `/tmp/gempy-before-pilot-1792796878.sqlite3`. Temporary supervised runner retained
  at `/tmp/gempy-run-one-pilot.py`; it is not an installed scheduler.
- Follow-up verification exposed two pre-existing stale lifecycle tests, both
  reproduced against HEAD before this work. Updated their discovery sequence and
  cross-realm expectation to match existing account exclusion. Also covered and
  fixed a session appearing between account preflight and backend reuse; it can
  no longer be adopted as automation-owned. Suppressed the control listener's
  expected socket-close exception during normal process teardown.
- Final verification: **70 Python tests**, **10 Ruby ownership/startup tests
  (26 assertions)**, reporter parser/capture fixtures, **5 Node test files**, and
  `git diff --check` pass. Local Ruby socket integration includes normal process
  shutdown, identity rejection, and acknowledgment ordering. No new live test
  was needed for the post-pilot preflight refusal and socket teardown fixes.

### Remaining pilot work

- No account or roster expansion performed in this continuation. Two-account
  concurrency, other characters' startup compatibility, and restart-mid-run
  inspection remain before considering scheduled operation.
- Daemon-outage watchdog remains deferred; uncertain sessions retain account
  reservations and require inspection. Browser-rendered UI QA remains deferred.
- **Recurring scheduling remains disabled.** The one-character success does not
  authorize unattended recurrence or establish full-roster readiness.

## Full-roster activation (2026-10-23)

- User explicitly requested enabling live execution and running the configured
  roster. Updated `config.yaml` with `allow_live_operations: true`, tracked
  startup, and the validated required/background script lists; no pilot scope.
- Backed up config as `config.yaml.before-checkin-live-1792797745.bak` and SQLite
  before queueing. Checked host sessions `[]` and no outstanding reservations.
- Queued manual due run `09033ad978d7972cfa4b112a` through the coordinator while
  the daemon was stopped, then restarted the normal `gempy.service`. This uses
  the normal worker and telemetry API; no temporary pilot server remains.
- All 17 configured characters are included. Prepotente was already fresh from
  the pilot, so 16 new logins are due. Parallelism is two distinct accounts;
  same-account characters remain serialized. Persisted schedule `enabled: false`.
- Tumerok and Liviloo both passed tracked startup and began capture concurrently.
- Full-roster outcome pending below. Live execution intentionally stays enabled;
  future manual runs use **Daily Check-in → Run now**. Recurrence remains off.


### Full-roster run stopped; capture/startup corrections

- User stopped run `09033ad978d7972cfa4b112a`; final status cancelled, with
  5 complete (including already-fresh Prepotente), 4 partial, and 8 cancelled.
  Final discovery: zero sessions and zero reservations. Do not restart this run.
- Liviloo lacked resource capture; Bubbage lacked the fresh identity/stats receipt.
  Zojak and Eggable failed finite startup because `lumnismon` crashed. Those gaps
  remain recorded; they were not converted into successful captures.
- Corrected the mistaken BANK ACCOUNT restriction in the reporter and spec.
  BANK ACCOUNT is read-only; the remote runner cost applies to deposits and
  withdrawals. The location gate was preventing queries for many characters.
  Added failing/passing remote-bank capture tests, including persisted parser
  values; deployed the corrected reporter. No new live run followed this fix.
- Diagnosed `lumnismon` shared-file corruption: valid character hashes plus one
  malformed integer entry `g` triggered `Integer#[]` during startup migration.
  Backed up the YAML, removed only `g`, and preserved all 16 character records.
- Installed a backed-up `lumnismon.lic` fix: process lock, merge only the current
  character, atomic replacement. The old full-file write reproduced a lost
  update in `/tmp/test-lumnismon-persistence.rb`; new stale-snapshot merge and
  two-process concurrent-save checks pass. Backups have suffixes
  `.before-gempy-atomic-save-20261023.bak` (script) and
  `.before-gempy-repair-20261023.bak` (shared YAML).
- Normal successful check-ins observed ~35–45 seconds. Failed finite startup
  waits up to 180 seconds; no timer-based success bypass was introduced.

### Live-session panel addition

- User requested currently logged-in local characters, elapsed seconds, and
  status above the account queues. Added a compact table matching the page.
- The API reads current Service sessions independently of selected run history;
  phase association uses exact session identity. Manual sessions are included.
  Public session start timestamps come from the Lich process start, so the
  displayed seconds measure session elapsed time, including initial connection.
- Active page polling refreshes membership/status at the existing interval;
  elapsed seconds advance locally each second from server time. Logout removes
  rows. Fetch errors mark data stale and freeze counters; no-run/empty states
  remain visible. No new game operations are triggered by viewing the panel.
- Regression coverage: session timestamp sanitization, current/manual sessions,
  exact identity matching, elapsed-time handling, authenticated API, and browser
  desktop/mobile placement, updates, logout, idle login, and outage behavior.
  Independent review found no material issues. Historical-run current-session
  behavior was source-reviewed; its dedicated API regression case is deferred.
- The normal GemPy service was restarted after verifying no active run. Live
  execution remains enabled; recurring scheduling stays disabled; the cancelled
  run remains stopped. No real logins were used to verify this UI addition.

### Empty resources and combined bank balance

- User requested four concurrent accounts; persisted `parallel_accounts` is now
  4. Recurring scheduling remains disabled and live execution remains enabled.
- Liviloo and Gringott logs show RESOURCE returning vitals without profession
  balances. The reporter previously required a numeric weekly/total line and
  therefore marked those captures unavailable. A complete vitals-only RESOURCE
  response now records weekly, total, and suffused resources as zero with fresh
  observation timestamps. Empty, truncated, and malformed responses still fail
  capture; no character-name or level-specific override is used.
- Deployed reporter atomically with backup
  `/home/nick/gs4/Lich5/scripts/custom/gempy_reporter.lic.before-empty-resources-20261023-170309.bak`.
  Existing historical partial results remain unchanged. The next login uses the
  fix; no live login or service restart was performed for this change.
- Status now shows combined bank balances across configured characters in the
  selected realm, independently of table filters. Known zero counts as reported;
  missing balances are excluded and counted visibly. Report coverage and oldest
  observation time accompany the total. Duplicate character names count once.
- Verified 145 Python tests, 31 JavaScript tests, all reporter Ruby fixtures,
  and 10 ownership Ruby tests (26 assertions). Python emitted dependency
  deprecation and test database cleanup warnings; no test failures. Browser
  fixture verified totals, filters, polling, realm isolation, zero resources,
  logout clearing, and mobile layout. Live server serves the updated static asset.
  Final session inspection before deployment found no live game sessions.
