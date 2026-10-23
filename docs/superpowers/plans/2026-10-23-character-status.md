# Character Status Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** All configured characters in a filterable and sortable status table, including durable resource and bank/deed observations.
**Architecture:** Reuse `/api/profiles` and the SQLite ProfileRepository. Add a focused Status JS/CSS module and reporter parsing extensions. Filter configured membership in the UI so historical-only profiles do not add unwanted rows.
**Tech Stack:** Python/FastAPI/SQLite, vanilla JavaScript, Ruby/Lich.
**Spec:** `docs/superpowers/specs/2026-10-23-character-status-design.md`

## Global constraints

- Account third, Tutelage after weekly progress; preserve all 12 columns.
- No Rotation changes or online/offline indicators; missing is not zero.
- Latest observed values survive session expiry and restart. Default Prime; realm selector keeps Test separate.
- No new production dependencies. Existing local modifications are preserved.

## Review focus

- Partial reports must not erase balances or refresh their observation timestamps (task 1).
- Unrelated `Total:` lines and failed bank queries must not create balances (task 1).
- Unknown values sort last in both directions, including zero balances (task 2).
- Expired reset timestamps must not retain an obsolete active multiplier (task 2).
- Realm changes and delayed poll responses must not mix profiles (task 2).

## Task 1: Reporter and durable fields

Files: `scripts/gempy_reporter.lic`, `character_profiles.py`, `test_reporter_status.rb`, `test_status_profiles.py`.
Interface: `resources.suffused` and `suffused_observed_at`; new `wealth` section with `bank_balance`, `deeds`, and per-field `*_observed_at`.
- [ ] Add failing parser tests from installed Lich `Infomon::Pattern::Suffused`, `LTE`, and `Bank::Pattern::ACCOUNT_TOTAL` formats. Assert zero, independent timestamps, no partial/unrelated bank total, failed access preserving old data.
- [ ] Run `ruby test_reporter_status.rb` and `python -m unittest test_status_profiles` to observe failure.
- [ ] Parse suffused/deeds from existing resource/experience refreshes. Capture only a complete all-bank report, and refresh `bank account` only when at a bank to avoid consuming remote bank-runner uses.
- [ ] Validate and persist new numeric fields with independent observation times; older reporters remain compatible.
- [ ] Run new tests plus reporter/profile regressions.

## Task 2: Status table and navigation

Files: new `static/status.js`, `static/status.css`, `test_status.js`; modify `static/index.html`, `static/workspace.js`, `web_app.py`, `telemetry.py`.
Interface: `characterStatus.rows(accounts, profiles, realm, now)` produces flat row values and observation metadata; `characterStatus.select(rows, filters, sort, direction)` filters/sorts without mutation. Browser mount uses existing `api`, `text`, `actionButton`, navigation and polling.
- [ ] Add failing Node tests for configured/unreported membership, realm isolation, zero vs unknown, Lumnis countdown/ready, Tutelage presence and missing-last sorts.
- [ ] Implement pure row projection/filter/sort and semantic table with sticky Name, accessible status squares, weekly progress, all 12 clickable sort headers, search and account/profession/Lumnis/Tutelage filters.
- [ ] Add Status navigation, default-view setting, route support and asset allowlist; preserve filters/sort in sessionStorage. Keep stale data with an error on failed refresh and discard old-realm responses.
- [ ] Run Node and API checks; inspect desktop/mobile UI using fixture data with no live game commands.

## Task 3: Review and handoff

- [ ] Review whole diff, run focused Python/Ruby/Node regressions, and record runtime-specific limitations.
- [ ] Document reporter update/restart requirement and data collection behavior in readme.

## Execution ledger

- Ruling: work in current checkout because Git metadata is read-only; do not commit or alter unrelated `run.sh` changes.
- Corrected design omission: Tutelage restored to the requested eighth column.
- Verified installed Lich sources under `C:/Ruby4Lich5/Lich5/lib`: suffused format, experience deeds format, bank total format. No remote paid bank queries; refresh bank data only at a bank, also observe reports issued by other scripts.
- Task 1: reporter parsing and persistence implemented. SQLite persistence/validation tests failed before implementation and passed afterward. Ruby tests written but runtime exits with Windows access-denied status 0xC0000022 before running them.
- Task 2: implemented all 12 columns, numeric/categorical filters, sort, navigation, realm isolation, saved filters, default view and polling. Node tests failed before implementation and passed afterward.
- Final review: fresh reviewer identified obsolete reset dates after newer active reports and polling starvation under slow responses. Both reproduced with failing tests and fixed; requests now coalesce per scope. Added optional numeric range filtering following review.
- Verification: 15 Node tests pass; status persistence tests pass; modified Python modules compile and JavaScript syntax checks pass. Existing telemetry logic checks run using local YAML/timezone data; one existing backup test fails during Windows cleanup of an open SQLite handle. FastAPI suite unavailable in host Python; dependency installation blocked by DNS, WSL execution denied. Ruby runtime denied before execution.
- Visual verification blocked: sandbox fixture server was unreachable from the browser (loopback timeout), then browser attachment timed out. No claim of rendered visual verification or live deployment.
- Activation: restart GemPy web process and install/restart reporter 1.3.0 in the active Lich installation. This session changes repository sources only; it cannot execute WSL or write the external Lich scripts directory.
