# Gempy usability audit

Release audit, 17 October 2026. Primary methods: `ux-ui-audit` and `dashboard-redesign`. Inspection covers the existing FastAPI application, real DOM interactions in Playwright Chromium, and isolated realistic game observations. Desktop: 1440×1000; mobile: 390×844 and 320×844. No production sessions or credentials were used. Frequency below describes repeatability of the interaction, not measured population usage.

## Executive diagnosis

- Character identity is shared by the data model but fragmented in the interface. Profiles require repeated closing, finding, and reopening; refresh and browser navigation do not preserve the investigation.
- Roster entries repeat monitoring detail instead of prioritizing finding, opening, and comparing characters. This consumes space without creating aligned comparisons.
- Useful distinctions already exist: weekly versus stored resources, observation times, realms, live versus durable data, and current-cycle completion. Preserve them.

## Application and workflow inventory

The frontend is plain JavaScript and CSS: `static/index.html` contains shell, authentication, session actions, progress, settings and roster editing; `profiles.js` decorates roster/live and renders persistent profiles; `rotation.js` provides the weekly hunting workflow. There is one HTML route (`/`) and no client-side URL state. Feature modules wrap shared rendering/navigation functions.

| Surface | Existing tasks and features | Data and endpoints |
|---|---|---|
| Live | Find/filter by account and realm; sort attention/name; change density; inspect vitals, mind, location, XP, wounds, effects, bonuses, resources; pin XP metrics; hide/show unavailable sessions; attach client; disconnect and separately force-disconnect | `/api/sessions`, `/api/launch`, session action and operation endpoints; volatile telemetry keyed by process/session |
| Rotation | Prioritize hunting by completion/reset; separate main characters; filter/group by account; inspect offline reports; account occupancy; launch or add unregistered members | `/api/rotation`; `weekly_rotation.py`; configured membership plus cycle-qualified profile observations |
| Characters | Search roster/account; select Prime/Test; add/edit character, rename account; launch/open client; inspect offline profile | `/api/characters`, `/api/accounts`, `/api/profiles`; config membership independent of saved game credentials |
| Profile | Overview with exact resource balances, Lumnis/donations/Tutelage; expandable live status, XP/training and other bonuses; base/normal/enhanced stats and bonuses; trained/untrained skills and search; history | `/api/profiles/{realm}/{character}`; `character_profiles.py`; SQLite section and field observation timestamps, missing values retained as unknown |
| Progress | Today/week/month/year/custom ranges; realm/account/name filters; sortable normal/ascension/combined XP, ATP equivalent and coverage; daily chart; character drilldown | `/api/progress`; SQLite observed/imported history, timezone and day boundary |
| Settings | Timezone/day rollover; browser refresh/staleness/expiry; default view/client/density; reporter download/token rotation; Saga import; history backup | `/api/settings`, `/api/telemetry/token`, `/api/reporter/script`, `/api/history/*` |
| Shell | Login/logout; client choice shared by launch/attach; operation feedback and confirmations | Cookie authentication and CSRF; process lifetimes independent of browser |

Primary jobs inferred from this functionality and the request: monitor running characters, decide whom to hunt next, inspect and compare builds/balances across online and offline characters, review earned XP, and maintain roster/reporting. Desktop expert use is the working assumption; mobile supports the same tasks. No interviews, usage analytics, or time-on-task population data were supplied.

## Critical journeys

Observed profile comparison path: Characters → Aster → Stats → remember values → Close → find Cinder → open Cinder → Stats → mentally compare. Side-by-side comparison is unavailable. Each subsequent character takes three button activations, excluding search/scroll.

Observed progress path: Progress → This year → Briar → History opens with This month. Observed recovery path: filtered Characters → browser refresh → Live with cleared roster search.

| Step | User goal | Friction | Consequence | Severity |
|---|---|---|---|---|
| Find | Locate an offline character | Repeated expanded balances, cycles and Tutelage | Extra scrolling through unrelated data | S2 |
| Inspect another | Keep the same statistic in view | Close/open/select tab | Repeated navigation and memory work | S2 |
| Investigate history | Explain a yearly total | Drilldown defaults to month | Wrong comparison period | S2 |
| Resume | Return after refresh or Back | No URL or restored filters | Investigation has to be reconstructed | S2 |
| Navigate on phone | Reach Settings | Controls extend beyond available row | Destination partly clipped | S2 |

## Prioritized findings

### S2 | High confidence | Profile navigation
**Comparing builds requires closing the current character and rebuilding the same view.**

**Evidence:** [Before profile](screenshots/before-profile.png); Playwright found zero character selectors in the open dialog. Closing Aster Stats and opening Cinder selects Overview. `showDetails` resets `detailSection`; profile wrapper also resets skill filters.

**Frequency and impact:** Every cross-character build inspection. Experienced players must remember values and repeat three activations plus locating the next entry. Directly relevant to the requested primary task.

**Root cause:** Profiles are isolated leaf dialogs instead of a shared character investigation workspace.

**Recommendation:** Add direct character/realm selection, preserve the section and skill search when switching, and expose a comparison target in the same workspace. Keep close/return context.

**Acceptance criteria:** Aster Stats → Cinder Stats takes one selection; skills filters persist; Prime and Test are distinct; aligned comparison can show both offline and running characters and distinguish zero from missing.

### S2 | High confidence | Progress drilldown
**A character’s history can silently use a different period from the total just selected.**

**Evidence:** Playwright selected This year in Progress and opened Briar; Character history period was `month`. `detailHistoryPeriod` is initialized independently of `progressPeriod`; custom dates are not passed.

**Frequency and impact:** Any drilldown whose period differs from the previously used profile period. Users may attribute differences to game progress instead of scope.

**Root cause:** Aggregate and detail history own unrelated scope state.

**Recommendation:** Carry period and custom dates into the profile, show period boundaries/timezone, and retain them across character switching and comparisons.

**Acceptance criteria:** Year and custom-range drilldowns issue equivalent scoped queries; profile heading/controls expose that scope; returning preserves the originating filters.

### S2 | High confidence | Navigation and recovery
**Refresh and browser Back do not recover the current investigation.**

**Evidence:** After filtering Characters to Cinder, refresh returned to Live and cleared the search. All views and profiles use the unchanged `/` URL. `setTab` only changes hidden attributes.

**Frequency and impact:** Every refresh/deep-link attempt; Back cannot traverse app views. Repeated setup is particularly costly across multiple characters and periods.

**Root cause:** Navigation and scope exist only in mutable in-memory UI state.

**Recommendation:** Use validated URL fragment state for view, character, realm, profile section and comparison. Preserve per-view filters in browser session storage; restore the origin on close and Back. URL state wins over saved/default state.

**Acceptance criteria:** Refresh restores filtered character Stats; Back/Forward traverses views and profile identities; copied profile/comparison URLs reopen the same scope after login; malformed state falls back safely.

### S2 | High confidence | Roster hierarchy
**Finding characters requires scanning repeated monitoring detail.**

**Evidence:** [Desktop roster](screenshots/before-roster.png) and [mobile roster](screenshots/before-roster-mobile.png). Each reported character repeats Lumnis phase, points, donations, renewal, Tutelage and balances. First mobile entry measured 395.45 CSS pixels at 390px width. On desktop the identity, edit, class, details and launch control are far apart within a tall row.

**Frequency and impact:** Every roster scan, increasing with roster size. Scrolling burden is measured; the effect on real-player task time remains a hypothesis.

**Root cause:** Roster combines directory and monitoring-detail responsibilities with no disclosure boundary.

**Recommendation:** Keep identity, profession/level, online/offline state, exact weekly/stored resource summary and launch visible; place the existing full cycle/Tutelage breakdown behind an explicitly named expandable control. Preserve all fields in place and in the profile. Add a clear-filters recovery action.

**Acceptance criteria:** The same fixture fits substantially more entries in one viewport; full old summaries remain reachable in one expansion; expansion survives polling; account edit/rename/add/client operations remain accessible.

### S2 | High confidence | Mobile global navigation
**Settings competes with other navigation controls and is clipped on narrow screens.**

**Evidence:** Before mobile screenshot shows the truncated Settings label. At 320px, its measured rectangle starts at x=285.53 and ends at x=344.55. The single fixed-height header fits branding, five destinations and logout in one row.

**Frequency and impact:** Narrow phone viewports; discovering and activating the destination is harder even though the document overflow check alone passes.

**Root cause:** A desktop navigation row is compressed beyond its content capacity.

**Recommendation:** Keep all five destinations in a separate wrapping/scrollable navigation region with visible labels; position branding/logout separately. Validate control rectangles and keyboard access, not just document width.

**Acceptance criteria:** At 320 and 390px every destination can be reached and read without overlap/clipping; visible focus remains available; desktop navigation is retained.

### S2 | Medium confidence | Scope and empty states
**View-specific filters and empty results require users to reconstruct what is included.**

**Evidence:** Live and Progress offer All realms; Characters and Rotation independently default to Prime. Roster empty state says “Try another search or account” with no reset action. Progress filtered-empty rendering uses the same “No progress recorded” explanation as a genuinely empty dataset (`renderProgress`).

**Frequency and impact:** Switching scoped views or searching/filtering to zero results. Wrong-scope interpretation is inferred, not observed in user research.

**Root cause:** Scope is local but not consistently explained; no-result and no-data conditions share feedback.

**Recommendation:** Keep useful local scopes, label their reach, preserve them through drilldown, and distinguish filtered-empty results with an explicit reset. Avoid forcing a global realm filter that hides legitimate cross-realm monitoring.

**Acceptance criteria:** Profile and comparison headings always include realm; no-match states explain active filtering and offer reset; stored local filters do not silently change another view.

## Opportunities, preservation and verification

An aligned comparison table is an opportunity supporting the explicitly requested cross-character job, beyond repairing the switch workflow. Prefer precise tables over invented scores, rankings, targets or decorative charts. Do not aggregate Essence with Necrotic Energy or compare observation ages as simultaneous live states.

Preserve: (1) complete expert stats, skill ranks/bonuses, effect/injury details and XP pins; (2) distinct resource counters, realms, freshness and coverage; (3) session lifecycle controls, confirmation boundaries, roster management, reporting and backup.

Accessibility evidence: DOM uses named buttons, native dialogs and semantic profile tables. Narrow-screen navigation clipping is measured. Keyboard switching, focus restoration under polling, screen-reader announcements, contrast and zoom require validation; this is not a conformance audit. The new workflow checks will cover keyboard operation, control bounds and return focus. Actual screen-reader/browser combinations and contrast auditing remain separate follow-up work.

Now: repair period continuity and navigation recovery. Next: shared switching/comparison, progressive roster disclosure and mobile navigation. Later: representative-player task sessions and larger-roster testing. Test players on “compare two builds”, “explain a yearly XP total”, and “find the next wizard to hunt”; measure interpretation correctness, actions, lost context and successful return. Do not convert scripted checks into claims of user satisfaction or time saved.

Baseline automated evidence: 98 Python tests passed. Browser measurements above used `examples/ux_fixture.py`; existing browser regression scripts will run after implementation. Audit and the companion redesign proposal were completed before production interface changes.
