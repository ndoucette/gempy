# Migrating KoboldMonitor and Saga progress to Gempy

Gempy provides Live, Progress, Characters and Settings views. Its bundled Lich reporter works with custom clients, Saga and headless sessions. Reporter configuration, game login configuration and browser authentication are separate.

## Install and pilot

1. Start Gempy's web service and sign in. In Settings, select the desired history timezone and day rollover (default America/Los_Angeles, 5 AM). Weeks follow ISO Monday boundaries.
2. Generate a reporter token in Settings. The server stores its hash; the token is displayed once. Rotating it invalidates the previous token for every reporter.
3. Download `gempy_reporter.lic` from Settings, or copy `scripts/gempy_reporter.lic` into each relevant Lich installation's `scripts/custom` directory. Do not replace `kmon.lic` yet.
4. In one logged-in character's Lich session run:

   ```text
   ;gempy_reporter --url=http://127.0.0.1:8080/api/telemetry/update --token=YOUR_TOKEN --interval=3 --command-interval=120
   ```

   Use a Gempy address reachable from the Lich process. With Windows Lich and WSL Gempy, verify reachability rather than assuming localhost works. Use HTTPS when traffic crosses an untrusted network. The token is a credential: do not share terminal logs containing the setup command.
5. Confirm character, realm, room, vitals and reporting age in Live. Open the character details and compare normal/ascension lifetime XP, training points, injuries, effects, resources and bonuses against the game.
6. Repeat token setup for the remaining characters. Configuration is saved in each character's `CharSettings[:gempy_reporter]`; restart with just `;gempy_reporter` to reuse it. `kmon` and `exp_sagapanel` settings are untouched.

Add `gempy_reporter` through your normal Lich autostart manager once the pilot passes. Configure each Prime/Test character separately. No installed scripts, running sessions or autostart lists are changed by updating the Gempy repository.

## Compare and cut over

For temporary dual reporting from one collector:

```text
;gempy_reporter --legacy-url=http://OLD_HOST:5000/api/character/update
```

The optional endpoint receives the original KoboldMonitor groups without the Gempy token. Stop the old `kmon` collector during this comparison to avoid redundant game commands. Remove dual reporting with:

```text
;gempy_reporter --clear-legacy
```

Compare a normal play session, capped characters, Prime/Test, headless operation, logout/relogin, reporter restart, Gempy restart and temporary network interruption. A stale reporter does not imply logout. Existing session launch and attachment controls remain independent of telemetry.

Once all expected characters report reliably, replace `kmon` with `gempy_reporter` in autostart and stop the KoboldMonitor server. Keep the old script/settings for rollback. Rollback consists of removing/stopping `gempy_reporter`, restoring `kmon` autostart and restarting the old server; game sessions need not be disconnected.

## Import existing progress

Use Settings → Import Saga history. Gempy searches the configured `paths.lich_bin` installation's sibling `data` directory for `exp_sagapanel_history.yaml`. Ensure that this path points to the installation containing your history; Windows paths must be reachable from Gempy. Imports are repeatable and preserve their source. Weekly/monthly totals do not imply daily detail, so daily charts may have gaps even when a period total is available.

Normal XP, ascension XP and combined XP remain distinct. ATP equivalents are ascension XP divided by 50,000, not a record of points actually awarded. New live history is persisted by Gempy in SQLite. Download a consistent database backup from Settings before major maintenance. Period settings affect new sample dates; choose them before relying on period comparisons. Imported and already-recorded daily buckets retain their original dates. Custom ranges use available daily records rather than inventing a daily breakdown from aggregate-only imports.

Each imported character/period becomes a fixed migration baseline. Re-importing an existing period skips it, including an updated copy, to avoid overlap with live Gempy gains. New gains after the first import are added to that baseline. Import before making Gempy the authoritative tracker. Mirrored Linux/Windows copies do not add the same period twice. Import errors appear in Settings and leave that file's records unchanged.

## Collection behavior and limits

Cached vitals, room, status, injuries, effects, lifetime XP and resources are sent every three seconds by default. A passive hook observes native experience XML and game text without altering game traffic. `experience`, `lumnis info`, and `resource` rotate every 120 seconds by default, using Lich’s quiet capture with a five-second timeout. Increase `--command-interval` if you prefer fewer commands (minimum 30 seconds). Background report output is suppressed; unknown or missed output remains unavailable until a later refresh. The Settings refresh cadence controls browser polling; reporter cadence is configured separately with `--interval`.

Experience rates use lifetime counters, so level transitions do not become large artificial gains. Session rates reset when the reporter restarts. Last-hour gains cover the available reporter session and are incomplete during its first hour. The reporter keeps a bounded rolling sample window; Gempy owns durable period history. Gains across a reporting outage can establish a total without identifying the exact day they occurred.

Missing optional data is null rather than a fabricated zero. Daily silver and bounty points still depend on Ledger/BountyHUD or existing bank UserVars. Bonus text and observed timestamps are retained; an RPA activation is an observation, not proof it remains active indefinitely. Scroll expiration is kept in the game's stated elven time rather than guessed into a local timestamp. Lumnis narrative is displayed as received.

HTTP connect/read/write timeouts are bounded, failures back off to at most 60 seconds, and error messages are limited to once a minute. Only the newest snapshot is sent after recovery; an unbounded backlog is never replayed. Reporter restarts create a new identity, and each snapshot includes realm, Lich PID, sequence number and collection time.

## Verification

```bash
./.venv/bin/python -m unittest discover -v
ruby -c scripts/gempy_reporter.lic
ruby test_reporter.rb
```

The reporter checks use isolated Lich stubs, including native XML parsing and a capped character with an unavailable room. They do not log into the game. Browser verification uses a temporary service and synthetic snapshots, keeping real sessions and history untouched.

With Playwright and its Chromium browser available, run the dashboard integration check:

```bash
./.venv/bin/python examples/dashboard_browser_check.py
```

It exercises desktop/mobile navigation, live details and pins, imports, settings, backups, custom ranges, roster edits and logout, and writes screenshots under `/tmp/gempy-*.png`.
