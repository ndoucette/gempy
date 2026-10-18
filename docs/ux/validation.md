# Gempy usability validation

17 October 2026. The [audit](audit.md) and [redesign](redesign.md) were completed before production UI changes. Implementation followed with browser regressions, screenshot inspection, an independent code review and fixes. All data used for browser work came from isolated fixtures; no real game sessions were launched, disconnected or edited.

## Measured workflow changes

| Task | Before | Implemented and verified |
|---|---|---|
| Switch from one character’s Stats to another | Close → find/open next character → Stats; three activations, plus search/scroll | One native character selection; Stats stays selected |
| Compare builds | Memorize values across separate profiles | Two explicit character/realm columns; base/normal/enhanced basis; ranks and bonuses; exact balances; shared History period |
| Resume an investigation | Refresh returns to default view and loses filters | URL restores view, character, section, comparison and History scope; per-view filters persist in browser session storage |
| Explain yearly/custom XP totals | History defaults independently to month | Drilldown carries the original period and custom dates; range survives changing sections and refreshing |
| Scan roster on a phone | First fixture entry is 395.45px tall at 390px width | 214.8px, approximately 46% shorter; full cycle/resource/Tutelage summary remains expandable |
| Use navigation on a narrow phone | Settings extends past the 320px viewport | All five destinations remain within the viewport at 320/390/768/1024/1440/1920px |
| Recover from no matching characters | Instruction to try another search/account | Explicit clear-filter controls for roster and filtered Progress |

These are deterministic interaction/layout measurements, not estimates of player time saved. No metric definitions, completion thresholds, database schema, or game-session lifecycle rules changed.

## Screenshots

| Surface | Before | After |
|---|---|---|
| Desktop roster | [Before](screenshots/before-roster.png) | [After](screenshots/after-roster.png) |
| Mobile roster and navigation | [Before](screenshots/before-roster-mobile.png) | [After](screenshots/after-roster-mobile.png) |
| Stats investigation | [Single profile before](screenshots/before-profile.png) | [Comparison after](screenshots/after-comparison.png) |
| Mobile comparison | Previously unavailable | [Both character columns](screenshots/after-comparison-mobile.png) |
| Existing monitoring/planning evidence | [Live](screenshots/before-live.png), [Rotation](screenshots/before-rotation.png) | Existing monitoring and rotation regression scripts pass |

Screenshot iteration moved roster identity/class information together, removed redundant comparison receipt timestamps while retaining section observation times, and fit both comparison columns on phones. Detailed single-character Stats continue to preserve all base/normal/enhanced values and bonuses together.

## Automated verification

All commands completed successfully against the final implementation:

| Command | Coverage/result |
|---|---|
| `.venv/bin/python -m unittest discover -v` | 98 tests passed; baseline was also 98 passing |
| `ruby test_reporter.rb` | Parser, capped/null collection and quiet command capture passed |
| `ruby test_reporter_profiles.rb` | Reporter checks plus profile stats, skills, essence and cycle transitions passed |
| `.venv/bin/python examples/dashboard_browser_check.py` | Navigation, live/details, pins, imports, settings, backup, custom progress, roster editing, responsive layout, logout |
| `.venv/bin/python examples/profile_browser_check.py` | Exact balances, all stats, skill filtering, donations, live updates, offline access, realm isolation, responsive layouts |
| `.venv/bin/python examples/rotation_browser_check.py` | Eight-wizard fixture, mains, exact balances, deadlines, account occupancy, grouping/filters, profiles and mobile |
| `.venv/bin/python examples/monitor_design_check.py` | Live columns, critical vitals, zero balances, freshness, pinned XP, disclosures, profile tabs, focus under polling and viewports |
| `.venv/bin/python examples/ux_browser_check.py` | New switching/comparison journey, unknown versus zero, Prime/Test identity, stat basis, URL refresh, local filters, history/custom ranges, Back/Forward, disclosure persistence, keyboard close, navigation bounds |
| `.venv/bin/python examples/ux_resilience_check.py` | Late Progress/comparison responses, scope across refresh, Rotation account persistence, failed comparison retry, skill focus during polling, keyboard return, empty results, invalid/unknown profile URLs |
| `git diff --check` | No whitespace errors |

The Python suite reports unclosed SQLite `ResourceWarning`s from test teardown while still passing. Database lifecycle cleanup in the existing unit-test fixtures remains follow-up work; this result is not a claim of warning-free execution.

The Playwright connector lacked its expected Chrome binary, so validation used the repository’s installed Python Playwright with Chromium 153.0.8010.12. The browser scripts run against the real FastAPI/SQLite implementation and replace only the game-session service with fixtures. Delayed-response and error tests deliberately control fetch timing and one profile response.

## Review findings and repairs

The independent review reproduced a late default Today response overwriting restored Year data, History scope disappearing after refreshing Stats, and Rotation account restoration preceding option loading. All three were repaired and included in the resilience script. Browser checks also caught a delayed close event leaving a stale profile URL, focus restoration racing the next action, and older event handlers bypassing profile decorators during filtering. Final tests cover these affected paths.

Changes are confined to shared navigation, profile rendering, comparison tables, frontend layouts, static asset registration and documentation/test fixtures. Existing uncommitted profile/rotation/reporter work was preserved. The original full summaries, client operations, roster add/edit/rename, Settings, token confirmation, import and backup remain available.

## Practical limits and next validation

This release uses a native character selector with account and realm labels. It supports keyboard type-ahead; a very large roster may justify a searchable picker after observing actual usage. View filters remain local intentionally, so a Test profile does not change a Prime launch context. Per-view filters persist within the browser tab; copied profile URLs carry profile/comparison scope, not all originating view filters.

Keyboard operation, focus under polling, semantic controls/tables, explicit missing-data states and responsive bounds were exercised. Screen-reader/browser combinations, measured contrast, 200% text scaling, Firefox/WebKit and real-player comprehension were not audited for conformance. Next, ask experienced players to compare two builds, explain a yearly XP total and choose the next wizard to hunt. Observe interpretation accuracy, unnecessary actions, lost context and successful return before changing the density further.

To load the new asset routes, restart the Gempy web process and reload the browser. Deployment and restarting the user’s running service were not performed.
