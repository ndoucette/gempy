# Development baseline — 2026-11-06

This record belongs to the baseline commit containing it, based on `49c21c7`.
The `develop` integration branch starts at that baseline. No feature fixes were
made during baseline capture, and the running installation was not restarted.

## Included scope

Command console and local bridge; check-in ownership, tracked startup, and live
session status; Invoker buff display; combined bank balances and zero-resource
reporting; associated tests, fixtures, design/implementation notes, and README
updates. Housekeeping adds runtime ignore rules and `docs/development.md`.

Excluded and left in place: `config.yaml` and its backups, `.venv`, logs, private
application state, generated browser screenshots, `.superpowers`,
`docs/guild-director/`, `docs/guild-director-handoff-2026-10-28.zip`, and
`docs/superpowers/specs/2026-10-28-guild-director-one-pager.md`.
Previously tracked UX screenshots remain unchanged.

## Test environment

Tests ran in an allowlisted disposable source copy at
`/tmp/gempy-baseline-rwaljr7p/source`, with a separate Python environment,
synthetic services, temporary configuration/state, and loopback fixture servers.
Python 3.14.4; Node 22.22.1; Ruby 4.0.3; Playwright 1.63.0;
Chromium 153.0.8010.12. Ruby native integration read `/home/nick/gs4/Lich5/lib`
without booting Lich; no native tests were skipped.

Python packages were pinned to the installed application's required dependency
versions in a new environment. The system lacks `ensurepip`; the existing pip
was used with `--python` targeting the new environment, without changing the live
environment. An initial attempt to replicate the entire system package list
failed on the OS-only `command-not-found` package; installing the required
application/test dependency closure succeeded.

## Results

| Check | Result |
| --- | --- |
| `python -m unittest discover -v` | 170 passed, exit 0, 8.067 seconds |
| Each `test_*.js` with Node | 55 tests across 7 files passed; all exit 0 |
| Each `test_*.rb` with Ruby | All 6 files exit 0 |
| `test_checkin_ownership.rb` | 11 runs, 30 assertions, no failures/errors/skips |
| `test_command_bridge.rb` | 27 runs, 159 assertions, no failures/errors/skips |
| Reporter Ruby scripts | All parser/profile/status/check-in assertions passed |
| Browser checks | 7 passed, 3 failed; details below |
| `git diff --check` | Passed |

Python emits existing SQLite `ResourceWarning` messages for unclosed fixture
connections and a Starlette deprecation warning about the httpx TestClient
backend. They are not test failures.

The first Python run used a global `GEMPY_CONTROL_DIR` and reported 4 failures:
the two `EndToEndTests` in `test_command_integration.py`, plus
`test_private_identity_bound_round_trip` and
`test_wrong_reply_identity_is_ambiguous_after_dispatch` in
`test_command_transport.py`. That override superseded the fixtures' private
control directories. Unsetting it while retaining isolated `GEMPY_STATE_DIR`
produced the 170-pass baseline above with no source changes. These four failures
were introduced by the initial test environment, not recorded as product defects.

Each browser script ran as `python examples/<filename>` with Playwright Chromium,
a fake service, and a 120-second process timeout. No script timed out.

| Browser script | Exit | Result |
| --- | --- | --- |
| `checkin_browser_check.py` | 0 | Passed |
| `command_browser_check.py` | 0 | Passed |
| `invoker_browser_check.py` | 0 | Passed |
| `status_bank_browser_check.py` | 0 | Passed |
| `dashboard_browser_check.py` | 0 | Passed |
| `rotation_browser_check.py` | 0 | Passed |
| `ux_browser_check.py` | 0 | Passed |
| `profile_browser_check.py` | 1 | Line 64: `.live-card .resource-weekly` text did not equal `32,450` |
| `monitor_design_check.py` | 1 | Line 91: `.row-identity .live-sub + .row-cycle` count did not equal 1 |
| `ux_resilience_check.py` | 1 | Line 33: progress period expected `year`, actual `day` |

These three browser failures exist in the captured code and are intentionally
preserved. Each script stops at its first failing assertion; later assertions in
those scripts are unverified. Root causes and fixes remain future work.

Full local test output and initial/corrected Python runs are retained under
`/tmp/gempy-baseline-rwaljr7p/` for this session, outside version control. That
location is temporary; this committed record is the durable summary.

## Review and isolation

CodeRabbit reviewed all 53 staged changed files (including newly added source)
and raised 0 issues. The final test-result record and removal of one trailing blank line in
`command_api.py` followed the review; executable code was unchanged. The review
ran in the isolated copy; no runtime configuration or unrelated files were sent.
Candidate files were checked for credential-bearing configuration, runtime data,
private key/token patterns, and accidental artifacts; no secret-pattern matches
were found. Only explicitly selected source and documentation are staged.

The live service remained active with PID `131480` and activation time
`2026-11-05 01:43:24 PST`. After testing/review, hashes of `config.yaml`, the
installed service unit, and private `auth.json` were unchanged. Runtime
databases and logs may naturally change while the installation remains active.
Development uses a separate worktree and configuration. Normal `Service` scans
host Lich processes, so development must use fake services/read-only fixtures;
separate state alone does not isolate live game sessions. See
[development isolation](../development.md).

## Python dependency versions

```text
PyYAML==6.0.3
annotated-doc==0.0.5
annotated-types==0.8.0
anyio==4.15.1
certifi==2026.1.4
click==8.1.8
fastapi==0.142.2
greenlet==3.5.6
h11==0.16.0
httpcore==1.0.9
httpx==0.28.1
idna==3.11
opentelemetry-api==1.45.0
playwright==1.63.0
pydantic==2.13.5
pydantic_core==2.46.5
pyee==13.0.1
starlette==1.7.0
typing-inspection==0.4.4
typing_extensions==4.16.0
uvicorn==0.54.0
websocket-client==1.9.2
```
