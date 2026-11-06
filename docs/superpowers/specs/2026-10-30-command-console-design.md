# Web command console — proposal for approval

Status: proposed, October 30, 2026. Product code and live sessions are unchanged. All defaults below are recommendations, not previously approved decisions.

## Outcome

From Gempy's web console, send one command to one logged-in character, a chosen set, or all eligible logged-in characters. Support ordinary game input and Lich commands through the same input path the client uses. Show exactly who was targeted and what delivery was confirmed.

Examples: `look` on Dartwen, `;pause all` on three hunters, or `;invokerhour` on all selected characters. Text is sent literally once per target; Gempy does not interpret a game command as a shell command, expand templates, or split semicolons.

## Existing implementation and constraints

- `static/index.html` owns Live cards and the existing client/disconnect actions; `static/workspace.js` and `static/workspace.css` provide the shared workspace and responsive layout. Preserve the charcoal/gold styling, vitals, Invoker header, and client selector.
- `gempy_service.py` discovers local sessions, assigns `pid:process_start` IDs, validates realm/listener ownership, and serializes lifecycle operations. A running process or an attached frontend does not by itself establish that the game connection is ready for commands.
- `web_app.py` already enforces administrator login, mutation CSRF tokens, and origin checks. Its operation map is memory-only; command receipts need persistent storage to resolve an interrupted browser request.
- `scripts/gempy_reporter.lic` periodically posts telemetry and performs quiet data queries. Its loop can block on those queries or back off during failures; it should not become the command delivery loop.
- `scripts/gempy_checkin_ownership.rb` establishes a precedent for a private local control socket bound to process identity. Daily Check-in owns its temporary sessions until the existing takeover flow succeeds.
- Read-only inspection of `C:/Ruby4Lich5/Lich5/lib/global_defs.rb` found `dispatch_client_input`, the shared `ClientInputDispatcher`, upstream hooks, and native Lich/script routing. Detachable client handling separately handles user-exit dispatch before normal input. The active-session API is discovery/lifecycle infrastructure, not a general command API.
- The configured WSL Lich path could not be traversed from this host. The Windows Lich source above is evidence for the adapter design, not proof that every running session has the same capabilities. The adapter must probe its actual runtime and refuse unsupported versions.
- There are existing uncommitted changes across Gempy. Implementation must preserve them and integrate with the current Daily Check-in ownership rules.

## Approaches considered

| Approach | Benefit | Cost / limitation |
| --- | --- | --- |
| **Command panel inside Live — recommended** | Select the characters whose condition you can already see; reuse their client links; quick single and bulk actions | Needs careful selection preservation during polling |
| Separate Commands page | More space for extensive history and future scripting | Adds navigation and duplicates a live roster for a small initial feature |
| Per-card input plus a broadcast dialog | Small local changes | Many repeated inputs; bulk targeting feels separate from single-character use |

For transport, recommend a small local Lich control bridge, independent of the frontend and reporter loop. Vellum WebSocket delivery would depend on a particular frontend; attaching a temporary detachable client may change attachment/ownership and cannot by itself acknowledge command processing. Reporter polling would add latency and couple control to telemetry refresh. Do not silently fall back between transports after an ambiguous send.

## Proposed UI

### Entry and targeting

1. Add a **Commands** toggle to the Live toolbar. Opening it reveals selection checkboxes on cards and the command panel. An explicit **Send command** action on a card opens the same panel with only that session selected; if a draft already targets other sessions, it shows the target change before sending.
2. The panel sits above the cards, keeping the action close to the roster. At desktop widths it has a composer on the left and the latest delivery on the right; on phones these stack. The panel is collapsible and does not replace Live.
3. Show **All online (N)**, **Clear**, a selected count, and expandable recipient names with realm badges. All online selects a snapshot of all command-ready sessions across the Live roster, including Prime and Test, independent of any visual search/filter. Its name/count are explicit; it never silently means only the visible cards.
4. Offline sessions cannot be selected. Online sessions lacking control support remain visible with **Control unavailable** and an explanation. Daily Check-in sessions show **Check-in controlled** with a link to the existing takeover action. All online excludes both categories and shows the excluded count/reasons.
5. Selection stores the session ID and the selected bridge/connection generation, not name, PID alone, card order, or DOM position. New logins are not added automatically. A disconnected or replaced selected session stays in the draft as **Unavailable** until removed, so a later login cannot inherit its commands. Polling must never silently update the generation bound to a selected recipient.
6. Single-target and multi-target use the same composer. The primary button reads **Send to Dartwen** or **Send to 3 characters**, always with the recipient list immediately above it. No second confirmation dialog for routine bulk commands: choosing recipients, seeing the command, and clicking the explicit send button is the action.

### Composer

- One single-line text input, with the placeholder `Game or Lich command, e.g. look or ;pause all`.
- Preserve leading semicolons, punctuation, case, and internal spacing. Reject blank input, CR/LF/NUL and other control characters, or more than 1,024 UTF-8 bytes. Reject multiline paste with an inline explanation; never silently turn it into multiple commands.
- One click sends. `Ctrl+Enter` / `Cmd+Enter` is the keyboard shortcut for single and bulk sends; bare Enter does not submit. Disable duplicate submission while this request is being accepted. Legitimate repeat commands remain possible as a new explicitly initiated send.
- **Recent commands** provides up to 20 recent distinct lines. Choosing one fills the input; it never sends or restores an old target selection.
- Clear the input after acceptance and retain the exact selected sessions for quick follow-up commands during this visit. On validation failure retain the draft. On an ambiguous HTTP failure retain the draft with **Checking delivery** and query its request ID; do not provide an automatic retry that could duplicate input.
- Collapse/reopen preserves a draft in memory. Leaving Live, a full page reload, or logout clears active targets. Do not persist target selections across browser sessions. History remains available to the authenticated administrator.
- Ordinary hunting scripts continue. Gempy does not automatically pause scripts, wait for roundtime, change stance, or retry a game rejection. If desired, the operator sends normal Lich pause/kill commands explicitly. Client-specific macros/aliases are outside scope; ordinary Lich aliases and hooks retain native behavior.

### Results and history

The newest batch appears beside/below the composer; **Recent deliveries** expands earlier batches. Each batch records literal command text, Pacific time with date and PST/PDT, intended recipients, and individual results. Use `America/Los_Angeles`, including daylight saving changes.

| Display state | Meaning | Operator action |
| --- | --- | --- |
| Sending | Accepted by Gempy; dispatch is being attempted before the deadline | Wait briefly |
| Sent to Lich | The bound bridge confirms the normal input dispatcher completed its handling | Open client to inspect game/script output |
| Not sent | A definitive pre-dispatch rejection: session changed, connection unavailable, check-in ownership, unsupported bridge, busy, or expired | Correct the cause; optionally select only these recipients into a new draft |
| Unconfirmed | Delivery may have happened, but there is no conclusive receipt | Inspect the client; never automatically resend |

Do not label dispatch as **Executed successfully**. Lich may swallow a command through an upstream hook, and the game can reject it due to roundtime or other conditions. A started script can continue long after dispatch returns. An exception after dispatcher entry is potentially ambiguous, not necessarily **Not sent**.

**Open client** uses the existing action and preserves the current frontend preference. A history action **Use command again** fills a new draft only. **Select not-sent characters** includes only definitively unsent sessions still matching their original identities; unconfirmed sessions are excluded. History never retargets a later login by character name.

The initial release does not duplicate a full game terminal or claim that all subsequent game lines are responses to this command. The inline mockup uses sample characters and simulated receipts; it makes no network requests.

### Responsive and accessible behavior

Preserve the two-column Live card layout where space allows. Use a compact full-width composer above it; stack results below the input on narrower screens. Recipient chips wrap. Large target lists collapse behind a named disclosure, not horizontal overflow. Keyboard users can reach each checkbox, the recipient summary, input, send action and client links; use visible focus, meaningful labels and a polite receipt announcement. Polling must preserve input text, selection, cursor/focus, panel state and screen-reader position. Disable controls with a readable reason, not color alone.

## Backend and Lich bridge design

### Thin local adapter

Add `scripts/gempy_control.lic`, installed with Gempy's existing script distribution pattern and run once per Lich session. It is independent of `gempy_reporter` so reporter refresh/restart/failure does not block commands. Give it a help/setup command, make it survive ordinary `;pause all` and `;kill all` using Lich's existing background-script flags, and document explicit stopping with `;kill gempy_control`.

The bridge owns a private Unix socket and a small discovery record in a configurable Gempy control directory (0700 directory, 0600 socket/record). The record includes a random bridge-generation ID, PID, process-start identity, character, realm, protocol version and supported features. Rotate the bridge generation on every game disconnect/reconnect, even if the Lich process remains alive: a replacement game connection must invalidate old selections. The adapter needs a reliable game-connection identity/lifecycle signal; if that cannot be established for a runtime, command readiness is unavailable. Discovery/ping is side-effect-free. Python verifies process ownership and socket/discovery ownership, and the bridge independently verifies the requested identity and same-OS-user peer before dispatch. Do not expose this socket on TCP or reuse the telemetry bearer token as command authorization.

The initial supported deployment is Gempy and Lich on the same Linux/WSL host under the same user. Other hosts or native Windows Lich connections appear unavailable; adding remote command transport is separate work. The script's help/configuration makes the shared control-directory requirement explicit. Updating/installing it is an operational rollout step, not part of this design-only turn.

Before reporting **Ready**, check that this is the expected logged-in character/realm, the game transport is connected, the actual runtime exposes the supported input dispatch/exit interfaces, and the bridge is not shutting down. Repeat those checks just before dispatch; process existence and telemetry freshness alone are insufficient.

Use a small adapter around the normal client input path, including correct `$cmd_prefix` handling, input serialization, upstream hooks, native script control, and the separate orderly-exit handling where required. Do not use `fput`, shell execution, a new raw `eval` endpoint, or send `;` commands directly to the game socket. Native Lich commands retain their existing meaning, including those that evaluate code; this console is an administrator control surface, not a command sandbox. No speculative fallback if a runtime capability is missing. Verify the actual supported Lich version's dispatch and shutdown behavior in an isolated harness before committing to this adapter.

### Request and identity contract

- `GET /api/command-targets` returns ready/unavailable state and reason for each discovered session, plus the bridge generation. Poll with the existing Live refresh; never reset an in-progress draft.
- Before submission, a lightweight authenticated/CSRF-protected `POST /api/command-batches/prepare` issues a random request UUID and a signed admission token, valid for 60 seconds, without executing anything. This can be issued when the operator clicks Send. `POST /api/command-batches` receives that request ID/token, one command, and explicit target tuples (`session_id`, `bridge_generation`, `character`, `realm`). The browser never submits a wildcard such as `all`; it resolves the visible All online snapshot first. An acceptance retry preserves the original request ID, token and payload; it never prepares a new request automatically.
- Authenticate with the existing administrator session, CSRF and origin checks. Reject malformed requests, duplicate target tuples, more than 100 targets, oversized payloads, and unsupported command format before any dispatch. A validation rejection produces no partial send.
- Persist the batch and intended recipients in SQLite before starting work. Same request ID and same normalized payload returns the original receipt; reuse with different input returns a conflict. Only an unseen ID with a valid, unexpired admission token may become a new batch; bind the token to the request ID and issuing administrator session. Preserve the original command text for audit. Keep lightweight accepted-ID tombstones at least until token expiry even if the history limit prunes a batch sooner; then the expired token itself prevents re-admission.
- `GET /api/command-batches/{request_id}` retrieves the existing receipt; `GET /api/command-batches?limit=20` retrieves recent batches. Both require the existing administrator login.
- Revalidate process-start identity, bridge generation, character/realm, actual game readiness and account ownership for every recipient. If any changed since selection, mark that recipient Not sent; do not resolve by name or redirect to a new session.
- Serialize with attach/disconnect/takeover operations using the current session/account coordination model. Recheck Daily Check-in reservation under its account lock. A check-in-owned target is Not sent until explicitly taken over through the existing workflow; sending never performs takeover itself.
- Dispatch different targets concurrently with four workers initially, serialize commands for the same session, and retain independent results. A failed target does not cancel others. 'At once' means one batch with prompt parallel delivery, not synchronized game execution or atomic all-or-nothing game effects.
- Each target has a five-second deadline to enter Lich's input pipeline, measured from batch acceptance. Recheck expiry after acquiring the shared input lock and before entering any upstream hooks or command processing. Reject expired work before that admission. Once admitted, native hooks or scripts may block or run effects later; this is not a guarantee about game-write timing. If handling has not completed by the acknowledgment timeout, show Unconfirmed and never report Not sent or automatically replay it. The adapter must expose this admission check inside the existing serialization boundary without a nested-lock deadlock. Bounded per-session waiting is allowed within the deadline; there is no offline queue or wait-for-roundtime queue.
- Batch delivery history retains 7 days or the newest 1,000 batches, whichever is smaller. Command text is kept in the private database, escaped in the UI and omitted from ordinary access/error logs. No secrets or pairing tokens enter a receipt.

### Duplicate prevention and ambiguous failures

Persist per-target dispatch intent before contacting the bridge. Send a stable per-target request ID and deadline. The bridge records IDs and payload fingerprints before entering dispatch, returns a cached terminal acknowledgment for a repeated ID, and refuses changed payloads. Keep the bounded cache for the bridge generation; if it fills, reject new work rather than evicting an ID that could be replayed. A bridge restart creates a new generation and invalidates old targets.

Neither a write timeout nor a lost acknowledgment triggers another input dispatch. A receipt-only bridge query may resolve an Unconfirmed result without replaying it. Once a target is terminal **Not sent** due to expiry before admission, workers and bridge must enforce that it cannot later enter Lich's pipeline. A target already admitted can only become Sent to Lich or Unconfirmed, not Not sent. Acknowledgments that arrive later can resolve Unconfirmed to Sent to Lich. Receipt-query handling must remain responsive while a dispatch handler is blocked.

After Gempy restarts, never resume queued command dispatch. Targets with a durable pre-contact state are marked Not sent; targets whose dispatch intent was persisted but whose outcome is not terminal become Unconfirmed and may be reconciled only through receipt queries. Keep the journal private and bounded. A new Lich process or bridge generation never receives old requests. Rotate the admission signing epoch on server restart; existing receipts remain readable, while an old unseen token cannot admit a new batch. After retention, an expired token rejects stale submissions instead of treating them as new sends.

Do not promise exactly-once game effects: there is no atomic transaction spanning SQLite, Lich and the game server. The guarantee is no automatic replay after possible execution, honest uncertainty, and per-session identity binding.

## Delivery plan after approval

| Milestone | Work | Demonstration / acceptance |
| --- | --- | --- |
| 1. Transport contract | Verify the actual Lich adapter in an isolated harness; implement private bridge discovery, readiness, identity binding, deadlines and receipts | Fake session receives a literal game command and a Lich command once; existing frontend stays registered; invalid identities and expired commands do nothing |
| 2. Batch service | Add authenticated APIs, persistent receipts, duplicate protection, session/account coordination and bounded parallel dispatch | Fake batch returns mixed Sent / Not sent / Unconfirmed results; a lost HTTP response can be resolved without a second send |
| 3. Live UI | Checkboxes, All online, shared composer, history and client links using the existing visual language | Select one, a subset and all; inspect names/realms; submit one command; watch each result; exercise narrow screens and polling |
| 4. Integrated verification | Combine the layers, document installation/help and exercise the existing lifecycle regression suites | Restart/disconnect/check-in races and old-bridge errors remain honest; existing attach, disconnect, reporter and check-in behavior pass their relevant tests |
| 5. Supervised rollout | Install/start the bridge on designated sessions, then test `look` on one and two characters | Verify the actual clients received one command each and remained attached; then enable ordinary use |

UI and batch implementation can be developed independently after agreeing the contract; end-to-end delivery depends on the bridge. Actual game-command testing belongs to a later, explicitly authorized pilot, since this request is for design and approval only.

## Focused verification

Use fake sessions and a stub Lich adapter for the automated suite. Cover literal semicolon handling, game/Lich prefixing, orderly-exit dispatch, unsupported capabilities, invalid/multiline text, auth/CSRF, double-click/request replay, batch partial failure, a lost acknowledgment, server/bridge restart, PID reuse, character reconnect, disconnect between selection and send, expired work behind a busy dispatcher, concurrent browser tabs, check-in takeover/logout races, old bridge generations and unavailable game transports. Verify repeated or expired IDs never call dispatch again.

Browser checks exercise one/subset/all selection, cross-realm labels, an all-selection snapshot surviving a new login, recipient disappearance, polling without draft/focus loss, recent-command recall without sending, proper escaping, error messages, history recovery, keyboard-only use, and 320/390/768/1024/1440px widths. Actual game output and game-command success are assessed only during the supervised pilot, not inferred from automated delivery receipts.

## Explicit scope

In: single-line game/Lich input, one/many/all selection, current-session targeting, per-target delivery, bounded recent history and existing client links.

Later: saved character groups, named command favorites, multiline macros/sequences, response-stream capture, schedules, command templates, automatic combat timing and remote-host control. Those can build on this contract without being prerequisites for this feature.

Approval requested for the Live-integrated UI, ordinary game and Lich command support, explicit All online snapshot, no routine bulk confirmation modal, the local independent bridge, and delivery-only receipts. Remaining engineering choices within those constraints include exact module boundaries, the bounded receipt journal implementation and presentation details.
