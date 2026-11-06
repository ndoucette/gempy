# Command Console Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans for integration and superpowers:subagent-driven-development for the isolated bridge task. Preserve the existing dirty working tree; do not commit unrelated edits.

**Goal:** Implement the approved Live command console with identity-bound delivery and durable, honest receipts.
**Architecture:** A private Linux Unix-socket bridge wraps native Lich input serialization. Python journals batches before bounded dispatch through the existing lifecycle/account locks. The Live panel binds drafts to immutable target tuples and resolves ambiguous submissions by receipt lookup only.
**Tech Stack:** Existing Python/FastAPI/SQLite, Ruby/Lich, vanilla JavaScript/CSS.
**Spec:** docs/superpowers/specs/2026-10-30-command-console-design.md (approved by user despite stale proposal header).

## Global Constraints

- Preserve existing uncommitted changes. Use fake sessions and temporary state; do not install/start bridges or send commands to live characters.
- Literal single-line commands, maximum 1,024 UTF-8 bytes; at most 100 explicit distinct targets.
- Target tuple: session_id, bridge_generation, character, realm. Never retarget by name.
- Admission tokens last 60 seconds, are bound to administrator session and server epoch; persist intent before bridge contact.
- Four workers; five-second deadline from acceptance, checked inside Lich serialization before processing. No automatic replay.
- Private 0700 directory, 0600 record/socket/database. Linux/WSL same user only.
- Retain 7 days or newest 1,000 batches, whichever is smaller; keep admission tombstones through expiry.
- States: sending, sent, not_sent, unconfirmed. User labels: Sending, Sent to Lich, Not sent, Unconfirmed.
- Pacific date/time includes PST/PDT. Recent commands: 20 distinct literal lines.

## Review Focus

- Same process reconnect and bridge restart must invalidate selected generations.
- Timeout while waiting for the native input mutex must never admit expired work.
- Lost HTTP acknowledgment/restart/pruning must not cause replay.
- Check-in reservation and lifecycle races must fail closed.
- Polling, logout and navigation must preserve/clear draft state at the appropriate boundary.

### Task 1: Native bridge and transport contract

**Files:** scripts/gempy_control.lic, test_command_bridge.rb; optional test fixtures under tests/fixtures.
**Interfaces:** newline JSON protocol 1. Discovery `<pid>.json` in GEMPY_CONTROL_DIR or default state/control directory, socket basename `<pid>-<generation>.sock`; record fields pid, process_start (Linux ticks), session_id (`pid:start`), bridge_generation, character, realm, protocol=1, features. Requests action ping/dispatch/receipt plus entire target tuple and pid/process_start. Dispatch adds request_id, command, deadline (Unix seconds). Replies echo identity/protocol and contain state/reason; ping readiness as ready boolean. Terminal states sent/not_sent/unconfirmed; in-flight sending. Receipt lookup never dispatches.

- [x] Write failing Ruby harness tests for literal game/Lich input, prefix/exit routing, wrong identity/user, duplicate/changed payload, full cache, expiration under blocked input lock, blocked dispatch with responsive receipt queries, reconnect generation and runtime refusal.
- [x] Run `ruby test_command_bridge.rb`; expected failing missing bridge behavior.
- [x] Implement adapter against actual local Lich source without modifying/installing Lich. Use existing serialization block directly to avoid nested lock; call normal processing and orderly exit within admission boundary. Runtime capability probes must fail closed. Retain bounded IDs for the generation. Help documents runtime support and shared directory; background flags survive pause/kill all.
- [x] Run `ruby test_command_bridge.rb`; expected all pass. Record native source evidence and limitations.

### Task 2: Durable batch service and authenticated APIs

**Files:** command_service.py, command_transport.py, command_api.py, web_app.py; test_command_service.py, test_command_api.py, test_command_transport.py.
**Interfaces:** CommandService(service, directory, transport=None); targets(), prepare(admin), submit(body, admin), get(request_id), recent(limit=20), close(). Transport target(session) -> readiness record; exchange(target, request) -> validated bridge reply. APIs as spec; JSON batches contain request_id, command, accepted_at, targets with tuple/state/reason.

- [x] Write failing tests for validation atomically rejecting entire batch; same-ID dedupe/conflict; token expiry/session/restart; mixed results and no retry; restart recovery before/after intent; retention/tombstones; same-session lock/account reservation; private discovery/peer/identity checks.
- [x] Run `.venv/bin/python -m unittest test_command_service test_command_transport test_command_api`; expected fail for missing implementation.
- [x] Implement private journal, bounded workers, durable per-target intent and recovery. Query-only reconciliation may resolve unconfirmed. API integrates existing auth/CSRF/origin and bounded request streaming; downloadable bridge uses existing script distribution pattern.
- [x] Run targeted Python suites plus existing web/lifecycle/check-in regressions; expected all pass.

### Task 3: Live composer and history

**Files:** static/commands.js, static/commands.css, static/index.html; test_commands.js; examples/command_browser_check.py.
**Interfaces:** CommandConsole panel hooks into existing api(), sessions, renderSessions, setTab/showLogin, clientOperation; command-targets refreshed with Live polling, not independent rapid polling. Draft Map stores tuple copies. UI consumes task 2 JSON.

- [x] Write failing JS tests for immutable selection, exclusions, validation, prepare/accept/lookup ambiguity, history recall and not-sent selection, duplicate submission, navigation/logout clearing and Pacific timestamps.
- [x] Run `node --test test_commands.js`; expected fail for missing behavior.
- [x] Build approved charcoal/gold panel and card controls, recipient disclosure, visible disabled reasons, responsive layout and accessible receipts. Preserve focused nodes during polling. History never automatically sends.
- [x] Run JS suite and isolated browser scenario at desktop/mobile; expected passing behavior, no overflow, retained input/cursor and zero real-session requests.

### Task 4: Integration, documentation and review

**Files:** readme.md, config-sample.yaml as necessary; task tests.
- [x] Document installation, explicit startup/stop, same-host requirements, unavailable runtimes, uncertainty and deferred supervised rollout.
- [x] Run all Python unit tests, Node tests, Ruby tests using isolated harnesses; inspect failures and fix regressions.
- [x] Review complete changes against approved spec; fix significant findings with regression tests.
- [x] Verify pre-existing edits remain; leave implementation reviewable in working tree and report evidence. No deployment or live commands.

## Implementation evidence

- Added the independent Ruby bridge, private Python transport, durable batch service/authenticated APIs, and Live composer/history.
- Existing uncommitted files were backed up and all 35 checked byte-for-byte unchanged after implementation. Changes remain uncommitted in the supplied checkout.
- Native runtime harness uses the installed Lich source read-only; Python-to-Ruby integration uses a fake game adapter, temporary sockets and state. Browser tests use a temporary server and fake sessions only.
- Independent review found three important issues: mutable targets during prepare, blocked dispatch exhausting receipt capacity, and receipt rendering removing keyboard focus. Each was reproduced before repair and verified with a regression.
- Bridge concurrency choice: one outstanding native handler per bridge; additional requests receive cached Not sent/busy. This bounds blocked native mutex waiters while keeping ping/receipt RPCs responsive. Python still dispatches different sessions with four workers.
- Added retention regression for receipt lookup by ID, plus newest-1,000 retention, 100-target rejection, and four-worker verification.
- Supervised bridge installation/startup and live-character commands remain deliberately deferred per the user instruction.

Final verification: `python -m unittest discover` — 170 passing; `node --test test_*.js` — 41 passing; all six Ruby harness files pass (bridge: 26 tests / 157 assertions). Desktop/mobile Playwright scenario passes, including prepare freeze, same-node history focus, lost HTTP response, reconnect, navigation/logout, and no horizontal overflow. `git diff --check` passes. Existing FastAPI/httpx deprecation and SQLite resource warnings remain in the Python test harness output.

## Authorized live rollout — November 2, 2026

The user subsequently authorized rollout and session restarts. Installed the
bridge in the configured Lich scripts directory and enabled it through native
`;autostart add --global gempy_control`. The initial Cragstone start exposed
Lich's binary source evaluation: Unicode category regexes needed explicit `/u`.
Added a binary-source compilation regression (RED→GREEN), corrected both regexes,
and reinstalled before retrying the definitively failed startup. Ruby bridge
suite: 27 tests / 159 assertions, zero failures; Python↔Ruby integration: 2 passing.

Cragstone, Dartwen, Prepotente and Celdiseth each confirmed a `look` batch.
Native Lich routing also confirmed `;list` and the autostart setup command.
Gracefully restarted Cragstone and restored its frontend: bridge autostart reached
Ready, its old tuple returned Not sent, and its new tuple confirmed `look`.
Restarted `gempy.service`; all four current session identities and attached
frontends survived. Live HTTP checks: root and command assets 200; command APIs
and script download correctly require authentication (401 without login).
Configuration and auth file hashes remained unchanged. All four bridges Ready.
