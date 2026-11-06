# Invoker Buffs Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make each character's long invoker spellup duration and coverage visible in Live.
**Architecture:** A pure JavaScript model derives markers from existing skill ranks and evaluates current effects against the shared schedule. A small browser adapter adds accessible strips and a live detail dialog.
**Tech Stack:** Vanilla JavaScript/CSS, Node tests, Python Playwright fixture.
**Spec:** docs/superpowers/specs/2026-11-02-invoker-buffs-design.md

## Global Constraints
- Only 4h 10m spells; no manual selection, reporter changes, or game commands.
- Five-minute travel buffer; use the existing header schedule.
- Preserve unrelated local changes; implement inline under the user's approval to proceed.

## Review Focus
- Missing/null effects are unknown, whereas a successfully reported empty list is missing.
- Learned spell exclusions must not change when buffs expire.
- No green indication from stale data or fewer than three active markers.
- Recompute expiry and coverage while the page is open, including failed polling.
- Keyboard focus and open details survive polling; mobile stays within the card.

### Task 1: Marker model
- [x] Add failing tests in test_invoker_buffs.js for ranks/profession exclusions, earliest expiry, 2h exclusion, missing/partial/stale/invalid data, mixed timers, and current-visit/buffer boundaries.
- [x] Implement static/invoker-buffs.js: markers(data), evaluate(session,timing,options), duration(seconds).
- [x] Run node --test test_invoker_buffs.js test_invoker.js.

### Task 2: Live UI
- [x] Add strips and detail dialog in static/invoker-buffs.js, style static/invoker-buffs.css, and load both in static/index.html.
- [x] Add examples/invoker_browser_check.py using the isolated dashboard fixture; verify states, detail selection, polling focus, ticking, freshness and mobile overflow.
- [x] Run browser checks and existing JS/Python tests; inspect screenshots and review the changed files.

## Progress
- Planning: approved conversation captured; existing reporter already supplies spell-circle ranks. No reporter rollout needed.

- Completed: marker model and accessible Live strips, detail dialog, and asset allowlist in `web_app.py`.
- Verified: 52 Node tests and 170 Python tests pass. Python suite emits ResourceWarnings from existing SQLite fixture cleanup.
- Browser verification: invoker states/details, screen-reader descriptions, keyboard focus through polling, live expiry/staleness, 768/390/320px layouts; existing command-console browser checks also pass.
- Independent review: one accessibility finding fixed and verified by a failing-then-passing browser assertion. No outstanding findings.
- Activated: restarted `gempy.service`; homepage and both assets return HTTP 200. All 29 pre-existing Ruby/Vellum processes retained their original process identities.
- Schedule assumption: uses the existing header schedule; the previously noted discrepancy with current wiki scheduling remains outside this change.

- Follow-up correction: Prepotente's attached client reported Mass Blur plus bard songs and Divine Shield, with only Mass Blur matching a marker. Require three active markers before assigning a spellup timer or Partial; individual marker timers remain in details. Regression and boundary tests pass (54 Node tests), isolated browser check passes, and the live asset matches the corrected file.

- Spellburst refinement: Cragstone retained four selected markers with the same expiry and had dropped Mass Blur. Removed Partial; three or more active markers now determine only renewal timing, with inactive markers listed neutrally in details. Prepotente regression retained. Verified 55 Node tests, the isolated browser check, Cragstone's captured effects, and both assets served by the running dashboard.
