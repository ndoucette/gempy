# Daily Check-in — design proposal

Status: proposed for review; no runtime changes or game logins performed.

## Intent

Log every configured character in once per game day, allow their login scripts and character-data capture to finish, persist the results, and log out the sessions created for this purpose. Run different accounts concurrently while allowing only one character per underlying account at a time. Keep routine character observations under 24 hours old, with explicit exceptions when refresh is blocked or unavailable.

This is a separate Daily Check-in page. It supplies fresh observations to Status and profiles and does not rework weekly Rotation.

## Recommended approach and alternatives

Recommended: a durable coordinator in the existing Python/FastAPI service, with SQLite jobs and bounded account workers. Reuse Lich saved credentials, headless session launch, reporter ingestion, persistent profiles, and orderly disconnect. The proposed default is four active accounts, configurable up to the number of available accounts. This is a proposed default, not a user-approved setting.

A timed login/sleep/logout loop is smaller but cannot prove that scripts or data capture completed, recover reliably after restart, or explain partial success. A separate queue service such as Redis/Celery offers distributed workers but adds operations and coordination that this single-host application does not currently need.

## What exists today

- `gempy_service.py`: `ensure_backend()` starts/reuses headless Lich; `start_backend()` uses saved `--login` credentials with `--without-frontend`. `disconnect()` sends orderly exit and waits up to 70 seconds. Discovery and validation include process identity. Headless listener readiness does not prove an authenticated game session or completed startup.
- Launch locking currently keys on character and realm. It does not provide the required account-wide lifecycle exclusion. `launch()` additionally serializes client launch, so the new worker should use the backend path, not launch a browser/client for every character.
- `web_app.py`: existing actions use an in-memory operation map. This is insufficient as the durable daily queue. Existing authentication, CSRF checks and operation patterns can be reused.
- `telemetry.py`: ingests authenticated reporter data, validates live process/reporter/sequence identity, and persists profile observations in SQLite.
- `scripts/gempy_reporter.lic`: issues bounded startup queries, then continues indefinitely. It has no explicit complete-capture acknowledgment or login reward collector yet. Waiting for all Lich scripts to stop would never finish because reporter/background scripts remain running.
- `character_profiles.py`: preserves known observations and field freshness. The current code already includes bank, deeds and suffused-resource fields; some earlier design documentation predates those additions.
- Account names in configuration are display/group labels, not authenticated account IDs. Add stable account identifiers and validate aliases to avoid treating two labels for the same login as independent accounts.

## Page design

Use the existing quiet GemPy styling: restrained warm accent, compact navigation, thin dividers, readable numbers. Place Daily Check-in near Status/Characters.

1. Header: Daily Check-in, game day, schedule, and Run now when idle. During a run show Pause queue and Stop run. Keep full scheduling configuration in a compact disclosure.
2. One run summary: completed/total, active, waiting, and needs attention. Progress counts fully satisfied characters; blocked and failed jobs never count as completed. Provide elapsed time; show an estimated remaining duration only after sufficient run history, excluding unbounded account waits.
3. Account lanes: account name, completed/total, current character, current stage, and remaining characters. Progress marks correspond to characters, not arbitrary time percentages. Distinct text accompanies color. One active character per lane makes the concurrency rule visible.
4. Expand an account to see its character queue. Character rows show stage, today's login credit, current 30-day reward cycle when observed, core-data freshness, and optional capture gaps. Use “Unknown” when there is no evidence; do not invent streaks or estimate rewards.
5. Selecting a character shows a compact step timeline: logged in, startup scripts ready, required fields captured, persisted, disconnected. Include script names/status, field observation times, current wait reason, and concise sanitized event history. Raw game output is secondary.
6. Completed state: “Complete” only when every target is satisfied and all owned sessions are closed. Otherwise “Finished with attention” identifies pending outcomes. Retry failed/partial characters without redoing successful jobs. Run history allows reviewing prior days.
7. Mobile: account lanes stack, active stage stays visible, secondary details expand below the row. Keyboard access and textual status labels are required.

The accompanying preview uses illustrative character/account assignments and outcomes, not live account data. It shows the recommended account-lane layout with local account selection, pause/stop states, and concurrency controls. The preview is an active-run view; the idle, history and full character-queue views remain specified above for implementation.

## Daily credit and freshness are independent

Game documentation says daily credit follows midnight Eastern and is per character. A reward message appears at login or midnight for a connected character. `BOOST INFO` reports the current streak and reward balances; it does not itself prove which calendar day was credited. A 30-day cycle wraps to day one normally, which must not be labeled a broken streak.

Sources checked October 23, 2026:
- https://gswiki.play.net/Login_Rewards
- https://gswiki.play.net/BOOST

Persist `game_day` using `America/New_York`, with UTC event timestamps and the configured display timezone (Pacific for this user). Do not use the app's XP reporting rollover for reward days. Default proposed schedule: 00:15 Eastern daily, displayed as 9:15 PM Pacific on the preceding local date under current aligned DST rules; render conversions dynamically.

Also wake the scheduler periodically and prioritize required data reaching 22 hours old. This gives retry margin; a once-daily timer alone cannot ensure every observation remains less than 24 hours old. Treat 24 hours as the freshness objective and expose breaches, not as an unconditional guarantee during outages, occupied accounts, or unavailable commands. Optional bank data may remain older and must say so.

If today's credit AND sufficiently fresh required fields are already evidenced, satisfy that character without an unnecessary reconnect. Freshness-only refreshes are allowed later in the same game day. A manual Run now refreshes due/pending work; a separate explicit Refresh all can force fresh captures without duplicating daily credit.

At midnight, create new game-day obligations. An old job finishing after midnight records the actual credited day; it cannot repair the missed day. Older unmet daily credit becomes missed/unknown according to evidence, not silently successful. Restart coalesces missed schedules into current-day work rather than replaying many past logins.

## Account coordination and active play

- Resolve every character to a stable underlying account ID. Labels can be renamed without changing lock identity. Assume one occupied character per account across configured realms until verified otherwise. The first release targets the existing production realm mapping; Test can be used for parser/lifecycle checks but never satisfies production daily credit.
- Use atomic database reservation plus a host-local interprocess account lock shared by every GemPy launch path (web, terminal, scheduler). Hold the account reservation from before login until confirmed logout. Never let manual and scheduled launches bypass each other's exclusion.
- Proposed ownership choice: route terminal launch requests through the persistent GemPy coordinator as well. The terminal remains usable as a UI but starting a new session requires that coordinator; do not retain a second independent terminal spawning path. A surviving session remains protected by its durable reservation and startup reconciliation if the coordinator restarts. This is a deliberate change to the current standalone terminal launch behavior.
- Recheck discovered account occupancy after acquiring the lock and immediately before spawning. If another character is playing, defer that account; run other accounts. Show who is occupying it and next retry time.
- A preexisting session belongs to the user, not the check-in. Read its existing observations and, where supported, request the bounded capture through the reporter. Never log it out automatically. Its same-account alternates remain deferred until it leaves.
- An unknown account/session mapping is blocked with a visible reason. Other-machine sessions are not discoverable through Linux `/proc`; confirm the installed Lich login flow rejects account collisions without force-taking the connection. If that cannot be established, unattended operation must be scoped to accounts managed exclusively here or supplied with an authoritative external occupancy feed. Do not claim global exclusion from local process discovery alone.
- If the user attaches to a job-owned session, require an explicit Keep session / Take over action that transfers ownership and suppresses scheduled logout. Recheck ownership before sending exit. External attachments detected without an explicit transfer pause cleanup and flag attention rather than exiting underneath the user.

## Per-character lifecycle and completion contract

`queued -> waiting_for_account -> logging_in -> startup -> capturing -> persisting -> logging_out -> complete`

Waiting releases worker capacity and retries later; it does not consume an active-account slot. Failures can branch to retry_wait, partial, needs_attention, cancelled, or interrupted. Partial capture still enters cleanup for an owned session. Store login-credit outcome, capture outcome and cleanup outcome separately; a failed capture does not erase valid daily credit.

1. Reserve the account and persist an attempt ID/launch intent before spawning. Record created-versus-reused ownership, realm/character, PID plus process start/boot identity, and reporter incarnation.
2. Start headless Lich with existing login scripts enabled. Verify authenticated game identity and game-ready output; an open local port is insufficient. Install/register a narrowly scoped check-in helper early enough to observe startup and the login reward message. Validate this bootstrap against the installed Lich version before choosing launch flags; do not invent a supported flag.
3. Give this launch a check-in context before autostart. Define finite startup prerequisites per character; distinguish them from permanent background scripts. Preserve normal startup behavior by default. For autostart that begins hunting or otherwise never finishes, configure an explicit check-in mode in that script/profile. Show such incompatibility during preflight instead of silently suppressing scripts or timing out every night. Completion of a required script means its explicit success acknowledgment or a verified normal successful exit, not merely absence from a process list. Include delayed child scripts in the same startup barrier.
4. Request a capture with a unique `capture_id`. The reporter serializes its own command queue, lets required startup scripts finish, and collects identity/level/profession, stats, skills, Lumnis/Tutelage, XP, applicable profession resource data, deeds, and reward info. Profession fields explicitly not applicable are acceptable; unsupported or unobserved required data is incomplete. Reuse existing parsers and preserve their true per-field observation timestamps.
5. Require login credit evidence for the current game day. Prefer observed award messages; an authenticated game session freshly observed during the day is documented presence evidence and can be labeled as such. Keep explicit reward-confirmation evidence separate from presence evidence. Do not infer current-day credit from a recent Lich process, heartbeat, or unchanged `BOOST INFO` streak alone. When historical award text might be replayed, only a positively identified live login event qualifies. Surface “Reward confirmation unavailable” when no reliable evidence is available.
6. Require every required field to have been observed within this capture after its request baseline, using capture ID plus session/reporter identity and sequence. Fresh heartbeats containing cached fields do not satisfy this barrier. Persist explicit per-field result: captured, not applicable, unavailable, timeout, or failed.
7. Optional fields (notably bank balance outside a bank) are recorded independently. The existing reporter avoids remote `BANK ACCOUNT` because it can spend a bank-runner use. Preserve that behavior; do not travel or spend boosts just to refresh this page. Show the original age and reason for a gap.
8. Persist fields and capture outcome, commit the transaction, and acknowledge the exact capture ID/sequence. Only then request orderly exit for a session still owned by the run. Confirm process/session termination before releasing the account or reporting full success. Logout failure blocks further characters on that account and offers inspection/manual force disconnect using the existing separately confirmed flow.

The completion invariant is: qualifying current-day presence/credit evidence + successful finite startup barrier + all applicable required observations durably committed + owned session confirmed closed (or an explicitly non-owned existing session left running). Optional gaps do not become fresh simply because the run is complete.

## Reporter protocol and durable state

Extend the existing authenticated reporter flow with a narrow check-in control protocol. Let the reporter poll/receive only a capture request for its validated session, not arbitrary shell or game commands. Use a per-attempt nonce tied to the process and capture. Include protocol capability/version, capture ID, request baseline, script barrier results, field observations, and reward/presence evidence. The capture request must be idempotent on replay. Preflight an older reporter as upgrade-required instead of repeatedly launching it.

Proposed SQLite records (in existing backed-up application state):

| Record | Important fields |
| --- | --- |
| checkin_settings | enabled, schedule/timezone, concurrency, freshness target, timeouts, account/character inclusion |
| checkin_runs | ID, trigger, game day, roster snapshot, status, start/end, cancellation/pause intent |
| checkin_jobs | ID, run, stable account, character/realm, reason, phase, separate credit/capture/cleanup results, next attempt |
| checkin_attempts | job, attempt, nonce/capture ID, session process identity, ownership, deadlines, error category |
| checkin_account_reservations | unique account ID, owner attempt, coordinator generation, heartbeat |
| checkin_events | monotonic event ID, run/job/attempt, UTC timestamp, type, sanitized payload |
| login_day_observations | character/realm/game day, evidence kind, observed time, optional streak/award |

Use unique identities and transactional transitions to prevent duplicate active jobs for the same character/realm and duplicate active reservations for an account. Daily-credit observations are idempotent, but jobs can repeat for freshness. Separate attempts preserve failures rather than overwriting history. Persist changes before emitting progress. Include all check-in tables in the existing SQLite backup.

Single coordinator ownership is enforced with a host-local leader lock. A lease/heartbeat timeout alone never authorizes another login: reconcile process identity and occupancy before replacing a stale reservation. If ownership of a surviving session is ambiguous, leave it running, block the account, and ask for inspection. Handle the crash between spawn and recording PID with the durable launch intent and tagged child/session identity; avoid blind duplicate launch. PID identity must include host boot identity across reboots.

No exactly-once claim is made about the external game's award. The system provides idempotent orchestration, durable evidence, and conservative reconciliation.

## Retry, pause, stop, and recovery

- Proposed defaults: login deadline 120 seconds (matching current service), finite startup/capture deadline 180 seconds per stage, existing 70-second graceful logout, up to two automatic retries for transient failures with bounded backoff. Tune against real startup durations.
- Failed authentication or unsupported reporter: needs attention, no repeated login storm. Temporary connectivity or command timeout: bounded retry after cleanup. Account occupied: deferred, not failed, checked periodically and on session changes. Near rollover/freshness expiry, show at risk.
- Pause queue stops new logins while current work captures and logs out. Stop run cancels pending work and asks owned sessions to finish bounded cleanup; no automatic force kill. Both actions persist across web refresh/restart.
- On restart, reconcile every nonterminal attempt against session identity, persisted capture acknowledgment and ownership before resuming, cleaning up, or requeuing. Completed captures are not recaptured just because the browser disconnected.
- A backend outage must not leave automation-owned sessions indefinitely. The startup helper needs a bounded local session watchdog that exits only its owned session after its configured overall deadline, with an explicit takeover signal disabling the watchdog. If that behavior cannot be implemented reliably in the installed Lich, expose the limitation and require startup reconciliation; do not claim automatic cleanup during daemon downtime.
- Ownership arbitration for takeover and watchdog exit lives in the Lich-side helper. Both the coordinator and a local in-session takeover command request a serialized ownership transition there. A takeover is successful only after acknowledgment that automatic exit is disarmed; only then attach through GemPy. The helper checks ownership immediately before accepting logout. If logout has already begun, takeover returns too late instead of falsely confirming ownership. Unexpected external attachment, lost ownership certainty, or unavailable reliable attachment detection suspends automatic exit and blocks further account work. Prefer an orphaned session needing inspection over disconnecting a potentially user-owned session. Startup reconciliation resolves that condition after service recovery.

## Backend and API shape

Add `daily_checkin.py` for scheduler/state transitions, and `checkin_store.py` for transactional persistence. Add a shared session/account reservation abstraction used by `gempy_service.py` and terminal callers. Extend reporter/profile ingestion for capture receipts and reward observations. Bind coordinator start/stop to the existing app lifecycle, while keeping game-session reconciliation distinct from web-client lifetime.

Proposed authenticated endpoints:

- `GET /api/checkin`: schedule, day coverage, field freshness, latest run.
- `POST /api/checkin/runs`: create/deduplicate run (mode due or refresh_all), return 202 and durable run ID.
- `GET /api/checkin/runs/{id}`: full consistent snapshot with version/event cursor.
- `GET /api/checkin/runs/{id}/events?after=...`: incremental durable events.
- `POST /api/checkin/runs/{id}/pause|resume|stop` and `POST /api/checkin/jobs/{id}/retry`: idempotent control requests.
- `PUT /api/checkin/settings`: validate schedule, concurrency and capture policy.
- A scoped reporter capture request/ack extension, authenticated under existing reporter controls and validated process identity.

For the first release, reuse the app's three-second polling rhythm, returning versioned state and optionally incremental events; this is sufficient for minute-scale check-ins. SSE is an optional later transport if useful, not a prerequisite. The browser never drives the worker or needs to stay open. Protect mutations with existing auth/CSRF, validate target membership server-side, and never return Lich credentials or pairing tokens in events.

## Implementation sequence and verification

1. Validate installed Lich behavior with a controlled single-character check: headless autostart, live reward text, login rejection on occupied accounts, startup context/ack, and graceful exit. Inspect configuration without copying credentials. Inventory which login scripts need a finite readiness contract.
2. Implement stable account mapping, cross-entry-point account reservation and durable jobs. Test two simultaneous starts on one account, different-account concurrency, manual-launch races, alias renames, unknown mappings, and cancellation.
3. Add correlated reporter capture, reward observations and startup acknowledgments. Fixture-test actual game output, normal 30-to-1 cycle rollover, cached-field rejection, missing/nonapplicable resources, partial bank data, duplicate/out-of-order receipts and reporter restarts. Add durable XP observation storage if profile persistence does not currently retain the necessary latest XP fields.
4. Implement worker lifecycle, cleanup, scheduling and restart reconciliation. Test startup/login/capture/logout failure independently, process identity reuse, crash before/after spawn, crash before/after commit, orphan sessions, takeover, midnight ET, both DST changes, and missed schedules. Use a fake clock/session service rather than live account logins for automated tests.
5. Build the page in existing static assets, with account lanes, expandable queues, details, history and controls. Check desktop/mobile layouts, keyboard use, stale UI reconnect, and that reported counts reconcile with per-character outcomes.
6. Pilot on one account, then two accounts concurrently, then the full roster. Observe representative startup/capture durations and set real deadlines. Verify restart mid-run and confirm Status/profile data persists after logout. Scheduled operation is enabled only after the pilot succeeds.

## Acceptance

- Every configured production character is included, unless an explicit exclusion is visible.
- At most one character per underlying account is logged in through coordinated GemPy paths; different accounts make independent progress.
- Each complete character has qualifying current-day presence/credit evidence, successful required startup, acknowledged persisted required fields, and correct cleanup ownership.
- Cached snapshots, unsupported commands, timeouts, and occupied accounts never masquerade as full success.
- Existing user sessions remain connected. Manual takeover disables automatic cleanup. Failed logout blocks the account.
- Queue state survives browser closure and daemon restart. Missed deadlines and field gaps are visible.
- Status consumes the same persisted observations; Rotation is unchanged.

## Choices proposed for user review

Account lanes as the default layout; four accounts concurrently; 00:15 Eastern daily sweep plus a 22-hour freshness catch-up; defer occupied accounts without interrupting play; optional bank capture gaps remain explicit. These defaults can change without changing the central design.
