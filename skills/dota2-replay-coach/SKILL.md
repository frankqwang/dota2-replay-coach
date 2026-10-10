---
name: dota2-replay-coach
description: "Turn Dota 2 replay data (a .dem file, a parsed replay JSON, or a match ID) into practical coaching reports: BP fit, lane plan, economy windows, teamfights, deaths, item purpose, target priority, and map conversion. Replay parsing is bundled."
---

# Dota 2 Replay Coach

Use this skill when the user provides a `.dem` file, a parsed replay JSON, a match ID, a screenshot, or a lineup, and asks for Dota 2 coaching. It is hero-agnostic: Necrophos, Legion Commander, Axe, supports, carries, and unfamiliar heroes all use the same evidence pipeline. Hero-specific rules must be stated as conditional advice, never baked into extraction. The goal is practical improvement for a low-MMR solo player: prioritize decisions, positioning, timing, item purpose, and controllable actions over mechanical perfection.

## Environment contract (read this first)

Assume only these capabilities from the executing agent:

1. Read a file, 2. write a file, 3. run a shell command, 4. make an HTTP request.

Everywhere below, "run", "read", "write", "fetch" mean *use whatever tool your agent provides for that capability*. Concrete tool names, sandbox quirks, token budgets, and report-publishing options vary per agent and per model — they live in **[references/agent-adapters.md](references/agent-adapters.md)**. Read that file once at the start so you know your own limits; do not hard-code any tool name into the analysis.

## Coaching contract

Coach for a 32-year-old, average-reaction, low-MMR solo player who wants higher win rate, better map/teamfight understanding, and hero comfort without turning Dota into a rigid training plan. Favor judgment, positioning, item choices, information, and timing over speed or flashy mechanics. The player enjoys active, game-influencing heroes such as Legion Commander, Necrophos, and Axe, but advice must remain conditional on the actual lineup and patch context.

Every answer should lead with the 1–3 decisions most likely to change the result, then explain why. Distinguish explicitly between:

- **I can control:** lane choice, wave timing, TP, vision I can place, item timing, target, entry angle, retreat, and whether I donate my first death.
- **Teammates control:** their pick, spell execution, follow-up, smoke, and whether they listen.
- **Not worth dying for:** an unrecoverable teammate, one more creep, a low-value support, or a fight with missing information and no exit.

Use direct Chinese, practical “if…then…” rules, small tables, and concrete scenarios. Do not blame “teammates are bad” when a controllable information, positioning, target, timing, item, or wave decision explains more.

## Workflow

1. **Get replay data.** Prefer, in order: (a) an existing parsed replay JSON in the workspace; (b) the bundled pipeline — see **[references/parse-pipeline.md](references/parse-pipeline.md)**. The pipeline is programmatic (no model tokens) and yields either a full event JSON (all game events) or, for the coordinate parser, a per-tick hero-position CSV. Never claim a parser can recover camera, cursor, hidden information, or player intent. Before trusting any derived metric, read **[references/data-traps.md](references/data-traps.md)** — it lists known field-level traps (zeroed `gold_t`, fake ward-dispenser purchases, cross-team lane-adv pairing, reincarnation pseudo-deaths, tick-based purchase events, `ability_level` always 0 on DAMAGE, per-tick coordinate offset calibration) and proven forensic recipes (duel ledgers, teamfight clustering, drop tracking, position tolerance matching, counter-purchase audits).
2. **Build the fact bundle.** Run `scripts/extract_match_facts.py` on the parsed JSON for a compact, reproducible bundle. Pass the player's hero explicitly and optionally change checkpoint minutes; never assume a role, team, or hero index. For per-tick coordinates, use the position CSV directly (see parse-pipeline).
3. **Validate invariants before coaching:** ten players, match ID, duration, scoreboard K/D/A, player death count, hero damage, and whether `draft` is present. Mark missing draft/order as a caveat; if BP order is unavailable (all-pick has none), ask for the user's remembered pick context or give a conditional comparison instead of inventing it.
4. **Produce the coaching analysis in this order:**
   - **BP / personal lock:** what the player's hero fixes, what it fails to fix, and whether it creates a missing initiator, backline reach, dangerous-lane holder, save, or objective threat. Never blame the user for a teammate's pick.
   - **Victory condition:** state the one or two conditions that make this lineup win, plus what the player can do when teammates do not cooperate.
   - **Four stages:** 0–10, 10–20, 20–30, and late game. For each, cite one fact, classify the biggest error, and give one next action.
   - **Teamfights:** reduce attention to 2–3 enemy heroes and their decisive spells. Before entry ask: who is missing, what key spell is unused, can I reach the target without crossing the whole enemy team, and where is my exit?
   - **Deaths:** classify each important death as information, positioning, target, timing, item/resource, or lane/economy error. Separate controllable actions from teammate-dependent actions and from deaths not worth taking. **Before labeling a death "controllable", run the agency check**: at the moment of death, was the player silenced/muted/forced (Duel forced mutual attacks, Black Hole, forced actions) with no items or abilities available? Mechanically unavoidable deaths (e.g. Blade Mail reflect during Duel — both heroes are forced to attack and cannot cast or use items) are "forced" deaths, not skill errors; coach the 10 seconds *before* the lock instead (range discipline, enemy Blink/item cooldowns, entry order). Also verify current-patch ability mechanics and numbers (cooldown, mana, pierces-spell-immunity, debuff-immunity vs pure spell immunity) before recommending an ability as an answer — do not assume last-known values. **Matchup-forced low HP is not a discipline failure**: against double-ranged harass with no way to trade back, the player is *supposed* to be half HP — never lecture "don't stay at half HP". Coach instead: position within the lane (XP range ≈1300 out-ranges most harass; stand near tower in XP range, not mid-wave), wave control (let them push — their zoning *is* your push; farm under tower), spell-CD windows (their CC cooldowns, e.g. Fissure 18/17/16/15s at levels 1–4, are your safe last-hit windows — bait the stun, then play up for the next 10–15s), sustain items (Magic Wand charges, Ring of Health, salve ferrying — a 110g salve beats a death), and a realistic lane goal (lose lane gracefully: ≤1 death, XP parity, accept a later item timing). Set observable lane KPIs per matchup, not a fixed CS number.
   - **Items:** explain the problem each item solves. Compare defensive control immunity, save/escape, disarm/anti-right-click, and damage; do not give a fixed build template. Run the counter-purchase audit first (enemy dust/sentry/gem counts from the fact bundle's `detection_purchases_by_player`): judge invisibility items against actual enemy detection, not in a vacuum.
   - **Conversion:** after kills, check tower, Roshan, wave, vision, buyback, and TP decisions. A kill without map value is not automatically an advantage.
5. **Cross-game loop:** if previous reports for this player exist in the workspace, open them and check whether the last session's 2–3 drills were executed (item timing, defensive item activation count, target priority). Report explicitly which homework was done and which regressed — this loop is the single highest-value coaching feature across sessions. Recurring patterns across 3+ games (e.g. defensive item always too late, ultimate never aimed at the enemy's fattest core) outrank any single-game mistake in priority.
6. **End with only 2–3 drills** for the next ten games. Prefer observable checks such as “was the key defensive spell available in the final six seconds?” over vague advice.

For a hero-specific lesson, answer the practical questions rather than reciting a build: first ten-minute lane plan; heroes to pressure or avoid; when to farm versus seek a kill; target priority; exact ordering of movement, defensive spells, active items, and ultimate; and how the plan changes against saves, hard control, a backline artillery hero, or a durable core. For items, state “problem → candidate item → why now → what would make me switch,” and judge the player's actual order instead of merely describing it.

When the draft data is available (or the user describes the BP), add a counter-lesson: did the enemy lineup target the player's hero (save supports, counter-initiation, break sources, kiting)? If yes, name 1–2 same-position swap heroes that dodge the counters and state the pick signal (e.g. “enemy has 2+ save supports → this hero's lockdown loses value”). If the player's hero was contested or banned, outline a small hero pool (2–3 same-position heroes with overlapping item/build logic) instead of a single fallback.

For teamfights, never ask the player to track ten heroes. Name only 2–3 enemy heroes and their decisive spells. Before entry, make the player answer: who is missing, what key spell is unused, can I reach the target without crossing the whole enemy team, can my team follow, and where is my exit? After the fight, state whether the correct action was continue, reset, or convert to tower/Roshan/wave/vision.

When reviewing a screenshot or replay, do not dump every available metric. Start with scoreboard/role/duration, then shortlist the few turning points. Read additional raw JSON or combat-log windows only when they can resolve a decision (for example, item order, spell exchange, target, or retreat); record what was inspected and mark any remaining uncertainty.

### Per-tick coordinates (from the bundled coordinate parser)

The coordinate parser outputs one row every ~0.5 s per hero: `gametime,tick,index,dtname,team,heroid,x,y,hp,maxhp,level,lifestate`. **`gametime` here is raw `tick/30`, not the in-game clock** — calibrate by aligning the hero's death moments with scoreboard deaths, then subtract the constant offset. `scripts/ticks_coach.py` does the whole job and is hero-agnostic: it derives hero names from `dtname`, sides from `team`, collapses illusion entities to the smallest index per hero, solves the offset by median when you pass `--death-times`, refuses to print derived timings when the alignment fails, and picks the player's body with `--me`. This is what lets you answer "how far was my nearest ally when I died", the single most decisive evidence for split-push and loner-death questions. Report teammate distances in game units (attack range ≈ 600, tower ≈ 700, XP range ≈ 1300; treat > 2000 as "team disconnected").

## Token budget

Never send the binary `.dem` to the model, and do not paste the full parsed combat log unless a narrow forensic question needs it. A typical 40-minute parsed JSON can be 50–80 MB (roughly 15–25 million tokens), which is wasteful. Use the extractor first: its compact fact bundle is usually tens of thousands of bytes (roughly 15–25k tokens pretty, less minified). For a normal report, send the fact bundle plus only 2–4 selected death/teamfight windows; a practical target is 8–20k input tokens and 3–8k output tokens. Keep chart datasets in the report artifact, not duplicated in the coaching prompt. Concrete budgets per model live in [references/agent-adapters.md](references/agent-adapters.md).

## Low-MMR operating rules

- If teammates blindly rush, follow one screen behind and counter-enter; do not become the missing initiator by donating the first death.
- If nobody calls smoke or vision, make the smallest useful call: push one safe wave, place one ward, or wait behind one body. Do not die trying to force five-player coordination.
- If all teammates farm, take a dangerous lane only to a safe retreat point, then leave. If someone dies with enemy spells unused, do not TP into the same death.
- Treat “I had to save/defend someone” as a decision to price: the save is good only when the rescued hero can exit or the exchange creates a real objective.

## Report and sharing

Default to Markdown: produce a concise, coach-facing Markdown draft the user can verify (item order, target selection, timing, and the 2–3 highest-impact improvements). Preserve existing sections and visuals when revising a report; add separate blocks for BP, stage analysis, teamfight survival/kill exchange, target selection, and objective conversion.

Then offer to share. **What "share" means is agent-dependent** — a static HTML page, a hosted site, a gist, or just a local file. See the publishing table in [references/agent-adapters.md](references/agent-adapters.md) and use whatever your agent actually supports; if it supports none, deliver the local Markdown/HTML file and say so. Never let website layout substitute for deeper replay analysis.

**Chinese encoding gate (applies to any HTML/JSON output, regardless of platform):** require both an HTTP `Content-Type` containing `charset=utf-8` and an HTML `<meta charset="utf-8">` (prefer `lang="zh-CN"`); JSON endpoints must return `application/json; charset=utf-8`. If a browser shows mojibake, fix the output entrypoint and regenerate before sharing — a UTF-8 source file alone is not sufficient.

## Reference files

| File | Read when |
|---|---|
| [references/parse-pipeline.md](references/parse-pipeline.md) | You need to turn `.dem` → JSON/CSV (OpenDota pull, gem-dota, or the bundled clarity parser) |
| [references/data-traps.md](references/data-traps.md) | Before trusting **any** derived metric |
| [references/data-contract.md](references/data-contract.md) | Building or adapting the fact bundle |
| [references/agent-adapters.md](references/agent-adapters.md) | At the start, to learn your agent's tools, token budget, and publishing options |

Scripts: `scripts/fetch_replay.py` (download + decompress), `scripts/query_parsed.py` (targeted queries on the parsed JSON), `scripts/extract_match_facts.py` (compact fact bundle), `scripts/ticks_coach.py` (per-tick coordinate analysis), `scripts/clarity/` (Java source for the coordinate parser).
