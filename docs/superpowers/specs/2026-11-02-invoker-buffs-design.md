# Per-character invoker buffs

Approved in conversation: a compact strip immediately below each Live character's level, with a prominent renewal timer, coverage color and short status. Click for marker spells and individual times. Only the invoker's 4h 10m spells participate; no manual selection is required. The existing global invoker countdown supplies the schedule.

Choose up to five markers automatically, preferring Natural Colors and other ranger, wizard and minor mental buffs. Exclude learned spells using the reporter's existing spell-circle ranks; use conservative profession exclusions if ranks are unavailable. Selection is independent of which effects happen to be active, so missing markers cannot disappear from the denominator. At least three active markers are required to detect a spellup; a lone outside buff is not enough. For a detected spellup, the earliest active marker is the timer. Three or more active markers provide a renewal estimate even if other markers were deliberately dropped for spellburst; fewer than three produces Missing; unavailable/stale effects produce Unknown. These are estimates of protection, not proof of who cast it.

Green means the detected spellup's surviving markers remain through the next reachable scheduled visit plus five minutes. Amber means a timing gap; red means insufficient markers to detect a spellup; gray means unknown. A current scheduled visit is reachable only if at least five minutes remain. Detail explains the estimate, selected spells, missing spells, mixed durations, and schedule/buffer. Color is always accompanied by text. Minutes suffice; under one minute reads <1m.

Approaches considered: a single Natural Colors timer is simpler but misses dispels and self-casting; a full spell checklist adds noise and unwanted two-hour alerts. Selected approach is several automatically chosen markers with the earliest expiry.

Implementation choices: reuse existing skills telemetry without reporter deployment; frontend module plus stylesheet; preserve existing schedule while clearly identifying it as scheduled rather than observed. No automatic pill use or game commands. Work in the current checkout to preserve the substantial existing uncommitted UI work; do not commit unrelated changes.

Refinement from Cragstone: remove the Partial state. The strip answers when to renew retained buffs; it does not require a complete spellup. Inactive markers appear neutrally as Not active in details. Keep the three-marker detection threshold that prevents lone Mass Blur from qualifying.
