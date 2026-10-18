# Gempy character workspace redesign

Design completed before implementation, 17 October 2026. Gempy is an operational monitor plus an analytical character workspace. The redesign changes how users move between characters and evidence while retaining the existing visual language and backend semantics.

## Approaches considered

1. **Shared character workspace, recommended:** keep task destinations, provide a direct character selector everywhere, preserve investigation scope in URLs, and add comparison inside profiles. Incremental, compatible with current modules and existing workflows.
2. **Merge everything into Characters:** a master/detail page could unify scope but would subordinate multi-character live monitoring and weekly planning to one selected character. Larger rewrite and greater regression risk.
3. **Keep dialogs and only condense roster rows:** reduces scrolling but does not solve context loss or cross-character comparison.

## Decision architecture

| Decision | Signal | Comparison | Grain | Freshness | Action | Failure cost |
|---|---|---|---|---|---|---|
| Which session needs attention? | Vitals, wounds, effects, reporter state | Existing attention ordering | Session + realm | Live telemetry age | Inspect, attach, disconnect | Delayed intervention |
| Who should hunt next? | Lumnis remaining, weekly essence, reset, occupancy | Existing cycle/cap rules | Character + realm + reported cycle | Field observations | Open profile or launch | Wrong rotation choice |
| How do builds differ? | Base/normal/enhanced stats, bonuses, skill ranks | Two explicitly selected identities | Character + realm | Section observation times | Switch/compare/inspect | Misread build or missing data |
| Which balances are available? | Resource type, weekly earned, stored, reported caps | Same labeled counters, never cross-resource sum | Character + realm | Field observation times | Inspect cycle/reporting details | Confusing earnings with spendable balance |
| How much XP was earned? | Normal/ascension/combined XP, coverage | Same period and timezone | Character + realm + period | History coverage | Drill down and compare | Wrong period attribution |
| Which character should I open? | Name, account, profession, level, running state | Directory scan/search | Configured character + realm | Live state / last profile report | Open profile or client | Repeated search/navigation |

No new game thresholds, conversion factors, or completion rules. Existing game meanings remain as implemented. Differences in resource type are labeled and never treated as comparable units. Observation timestamps describe stored evidence rather than asserting that offline values are current.

## Navigation and layouts

```text
Workspace navigation: Live | Rotation | Progress | Characters | Settings
Shared header: current destination | Open character [name · realm · account] | Client

Characters
  Scope: Prime/Test, account, search, clear filters, Add character
  Account heading + Rename
    Name + level/profession + online/offline   Exact weekly/stored   Open/Launch + Edit
    [>] Cycle & resource details for Name

Character workspace (from any view)
  Name + explicit realm/account/status                         Close / return
  Character [selector]        Compare with [None / character · realm]
  Overview | Stats | Skills | History
  Single: existing full profile with progressive detail
  Compare: aligned rows, two named realm columns, observation times and unknowns
```

Desktop retains dense aligned data; mobile puts navigation on its own row and wraps scope controls. Comparisons keep two columns adjacent inside a labeled, keyboard-focusable horizontal scroll region rather than stacking one whole character below the other.

## Component specification

| Region | Purpose/content | Representation/interaction | States | Responsive rule | Accessibility |
|---|---|---|---|---|---|
| Shared character entry | Direct access to configured and observed characters | Native selector grouped by realm; account in option label; selection opens profile | Available, unreported, offline; no implicit launch | Wrap below heading as needed | Visible label; native keyboard selection |
| Profile scope | Identity, realm, current section, optional comparison target | Persistent character selector; compare selector excludes primary identity | Loading/error with retry; unknown character; partial/no data | Controls wrap; dialog scrolls | Named controls, status messages, close restores entry focus |
| Comparison | Two profiles on the same question | Semantic table; Overview balances/bonuses; Stats basis selector; Skills search/untrained; History period totals/coverage | Missing shown as dash; zero preserved; section/field timestamps; offline explicit | Local horizontal scroll; no page overflow | Caption, row/column headers, keyboard scroll |
| Roster | Find/open/manage character | Compact summary plus native disclosure containing existing detailed summary | Empty roster vs filtered-empty; clear filters | Stacked identity and actions, concise balances | Named disclosure and selection, stable focus after polling |
| Navigation | Recover investigation | Validated fragment route + per-tab browser-session filter state | Invalid route falls back; login restores intended URL | All labels visible on phone | Native controls, no body scroll lock beyond existing dialog |
| Progress drilldown | Preserve comparison basis | Carry period/custom dates to History; show period boundary/timezone context | Invalid range stays recoverable; loading/error/empty | Dates wrap | Explicit labels, unchanged keyboard input behavior |

## Interaction and data contract

- `view → profile → another character → comparison → close → originating view`: retain originating search/account/realm/sort, selected detail section, skill query, untrained option and history period. Close returns to the origin; browser Back/Forward traverses profile navigation.
- URL fragment contains only navigation/filter state, never credentials/tokens. Shared profile links encode both identities as realm + name. Invalid/unavailable identities produce a recoverable error without substituting another character’s data.
- Per-view filters stay local, are restored within the browser tab, and expose reset. A caller chooses the realm explicitly; entering a Test profile must not affect a Prime launch control in the roster.
- Polling must not reset selectors, skill input focus, disclosure expansion or comparison state. Async responses must be ignored when identity/scope changes. Refresh failures keep the identity and show retry; missing data cannot become zero.
- Comparison uses existing profile/history APIs and reported timestamps. Stats expose base, normal and enhanced values with bonuses through an explicit basis selector. Skills retain all reported rows, including optional untrained ranks. History comparison uses the same range for both characters and reports coverage.
- All single-profile information remains available by selecting “No comparison”. Roster expansion retains the complete preexisting cycle/resource/Tutelage content. Session actions, Settings, imports, backups, client selection and Rotation remain accessible.

## Acceptance and validation

1. One character selection moves Aster Stats to Cinder Stats; comparisons show both with explicit realms, missing values and observation times.
2. A copied URL or refresh restores view, profile section, primary/secondary identity and history range. Back and Forward follow user navigation.
3. Progress This year and custom range remain identical in character History, including query boundaries; return preserves Progress controls.
4. Roster default rows are materially shorter on the same fixture; opening a disclosure restores the original detailed values, and polling retains it.
5. At 320/390/768/1024/1440/1920px no page overflow; all navigation labels/targets are reachable; comparison scroll is contained.
6. Keyboard users can choose both characters, change section, clear comparison, close with Escape and regain a meaningful focus target. Delayed responses cannot overwrite a newer choice.
7. Existing Python, Ruby reporter and browser workflow suites pass. Add focused Playwright regressions for navigation, comparison, range continuity, no-results recovery, error/retry, stale/unknown data and mobile layouts. Capture before/after screenshots and inspect them.

The baseline counts (three activations per Stats switch, 395px mobile roster entry) are interaction measurements, not representative task timings. After implementation, use the same fixtures to measure changes. Follow with player testing for comparison comprehension, discoverability and any density tradeoffs.

## Implementation sequence

1. Add failing browser checks for profile switching, comparison and period continuity; preserve baseline screenshots and tests.
2. Implement shared profile controls and comparisons in focused frontend code, using durable profile APIs. Carry the History range from Progress.
3. Add URL recovery and per-view filter persistence; compact roster disclosure and fix phone navigation. Keep all original actions accessible.
4. Exercise failures, keyboard, delayed responses, polling, realms and viewports. Run existing suites, inspect screenshots, fix observed issues and record measured results in `validation.md`.

Files: `static/profiles.js` owns profile loading/switching/disclosure; new `static/workspace.js` owns navigation state and shared entry; new `static/comparison.js` owns comparison tables; new `static/workspace.css` contains layout additions; `static/index.html` and `web_app.py` wire assets and History scope. `examples/ux_fixture.py` and `examples/ux_browser_check.py` provide repeatable isolated validation. Backend metric definitions and schema are unchanged.
