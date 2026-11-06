# Development isolation

The running installation uses `/home/nick/gs4/gempy` on `main`. Keep feature
development in the separate `develop` worktree. Committing the baseline does not
deploy it: do not restart `gempy.service`, install reporter/control scripts, edit
Lich autostart, or replace the running installation's configuration or state as
part of development.

## Configuration and state

Each checkout needs its own ignored `config.yaml` and Python environment. Start
from `config-sample.yaml`, never from the running installation's configuration.
Use synthetic accounts and leave `daily_checkin.allow_live_operations: false`.
Keep the web password, reporter credentials, databases, command receipts, control
sockets, and active-session records separate for every instance.

Set `GEMPY_STATE_DIR` explicitly for every development server. If a development
bridge is needed later, give it a separate `GEMPY_CONTROL_DIR` shared only with its
designated development Lich process. A configured `command_control.directory`
overrides that environment variable. Never point either setting at live state.
Keep Unix socket directory paths short enough for the 108-byte Linux limit.
Use loopback and a port other than production's 8080.

Separate state alone does **not** isolate game sessions: the production `Service`
discovers host Lich processes through `/proc`. Use the existing fake services and
fixtures for local development. Do not run `./run.sh --web` beside production
merely with a different state directory and assume it cannot affect live games.

For a read-only development UI with synthetic data:

```bash
# Run in the develop worktree, using its own environment.
.venv/bin/python examples/checkin_preview_server.py
# http://127.0.0.1:18767/?view=checkin
```

For interactive checks, the browser scripts create authenticated applications
with fake services, temporary state/configuration, and ephemeral loopback ports.
They never need a running game. `examples/ux_fixture.py` also supplies the shared
synthetic dashboard fixture for further development.

## Baseline checks

Install `requirements-dev.txt` in the development environment. Browser checks
also require Playwright and Chromium. The dated baseline record lists the exact
versions used and the existing failures.

```bash
# Run only from the development worktree or another isolated source copy.
# Keep launcher.py's import-time gempy.log away from the live checkout.
gempy_test_state=$(mktemp -d /tmp/gempy-test-XXXXXX)
env -u GEMPY_CONTROL_DIR -u GEMPY_CHECKIN_CONTEXT \
  GEMPY_STATE_DIR="$gempy_test_state" PYTHONDONTWRITEBYTECODE=1 \
  .venv/bin/python -m unittest discover -v
node --test test_*.js
for test_file in test_*.rb; do ruby "$test_file" || break; done
```

Unset `GEMPY_CONTROL_DIR` for the Python suite: its transport/integration fixtures
create their own private control directories, and a global override takes
precedence over those fixtures. The Ruby integration tests read native Lich
source from `GEMPY_TEST_LICH_LIB` (default `/home/nick/gs4/Lich5/lib`) without
booting Lich. If absent, native integration cases are explicitly skipped.

Run the `examples/*browser_check.py`, `examples/monitor_design_check.py`, and
`examples/ux_resilience_check.py` checks individually and retain each exit code.
`ux_browser_check.py` regenerates tracked screenshots, so run it in a disposable
source copy or review and exclude those generated changes from commits.

Do not commit local configuration, secrets, databases, logs, generated browser
screenshots, or unrelated handoff archives. Stage the intended files explicitly.
