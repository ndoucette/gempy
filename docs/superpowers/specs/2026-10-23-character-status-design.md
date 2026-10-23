# Character status overview design

## Intent

Add a 40,000-foot status view across every character configured in GemPy. It should make it easy to scan, filter and sort character progression, Lumnis, weekly resource progress, stored resources and bank/deed balances. Rotation is explicitly outside this change and will be reworked separately later.

## Goals

- Include every configured character, including characters that are not currently online or reporting.
- Show columns in this order: Name, Level, Account, Profession, Lumnis Reset, Lumnis Active, Weekly Resource Cap Progress, Tutelage, Total Resource, Suffused Resource, Bank Balance, Deeds.
- Support filtering and sorting across the roster.
- Use each character's latest stored reporter data; represent unreported values as unknown, never as zero.
- Keep this overview separate from the existing Rotation workflow and controls.

## Non-goals

- Reworking Rotation or changing its meaning, membership, or controls.
- Showing online/offline status.
- Adding detailed per-character analysis or historical charts to this overview.
- Inferring missing or stale values.

## Approaches considered

1. **Standalone Status view (selected):** a dedicated table over configured accounts and persistent latest profile snapshots. This matches the all-character overview and keeps Rotation independent.
2. **Expand Rotation:** reuse its existing page and controls. Rejected because Rotation is scheduled for a separate rework and its weekly planning concepts would muddy this general roster.

## Data and behavior

- Build roster identities from `config.yaml`'s account-to-character mapping, with account name in the third column. Include configured names even before their first report.
- Use existing persisted profile section storage for the latest known snapshot, rather than session-only live telemetry. Level/profession, Lumnis, and resource fields should retain the existing observed-at metadata where available.
- Weekly resource progress should be a compact progress indication plus its current/maximum values. Do not add a resource-type label to the column; preserve access to the reported values and avoid claiming unlike resource types are equivalent.
- Lumnis Reset displays a countdown when a reset timestamp is known and `Ready` when the reporter says it is ready. Unknown remains distinct from ready.
- Lumnis Active displays an accessible green/red square for active/inactive; when active, include the current multiplier (for example ×2 or ×3) if reported. Unknown/unavailable should be visually distinct from both states.
- Tutelage is a simple present/absent indicator; state and duration are intentionally omitted.
- Total Resource and Suffused Resource are shown as separate values. Bank Balance represents the character's combined bank balance as reported by the game client. Deeds is a count.
- Fields that have not been collected remain unknown. A tooltip or compact detail can expose field observation age when needed to assess old snapshots, without adding an online/offline column.
- Search should match name/account/profession; filters should include account and profession (and realm if the configured roster supports multiple realms). Column headers sort values naturally, with missing values grouped consistently at the end.
- The view should follow existing GemPy dark styling, remain keyboard accessible, and use a horizontally scrollable table on narrow screens rather than crushing numeric columns.

## Data collection investigation

The existing reporter already captures character name, level, profession, Lumnis reset/stage/multiplier, Tutelage, and resource weekly/total/max values. GemPy has persisted profile-section storage and a profile API, which can provide values after a character goes offline. Account membership is available from configuration.

The current reporter snapshot does not contain a suffused-resource field or bank-balance/deed fields; its `silver_today` value is daily earned silver and is not a bank balance. Before implementation, inspect the installed Lich/game APIs and existing local scripts for authoritative sources for suffused resource, bank totals and deeds. Add reporter fields only when the source and semantics can be verified; otherwise show unknown for those cells. Do not reinterpret daily silver or substitute a related counter.

## Builder decisions

- Whether the configured roster should be scoped to Prime or include each supported realm will follow GemPy's existing realm model and avoid duplicate character rows where the configuration is realm-agnostic.
- Exact cell formatting, responsive breakpoints, and the most reliable verified Lich accessors are implementation choices, provided missing data stays explicit and the requested column order is preserved.

## Acceptance

1. Every configured character appears when there is no live session.
2. Account is the third table column; all requested columns appear in the specified order.
3. Search, account/profession filters and sorting work without replacing unknown values with zero.
4. Persisted last-reported values remain visible after a session closes or the service restarts; observation age can be inspected.
5. Lumnis states distinguish ready, active with multiplier, inactive and unknown; Tutelage is presence-only.
6. Weekly progress uses each reporter's reported cap and does not label the resource type in the table.
7. Suffused resource, combined bank balance and deeds use verified sources or display unknown.
8. Existing Rotation behavior and API remain unchanged.
9. Existing backend and UI checks pass, and table behavior is checked at desktop and narrow viewport widths with keyboard navigation.
