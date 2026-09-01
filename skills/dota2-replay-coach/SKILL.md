---
name: dota2-replay-coach
description: "Analyze Dota 2 replay data into practical coaching reports, including the player's hero choice, BP fit, economy windows, teamfights, deaths, items, targets, and map conversion."
---

# Dota 2 Replay Coach

Use this skill when the user provides a `.dem`, parsed replay JSON, match ID, screenshot, lineup, or a specific death/teamfight and asks for Dota 2 coaching. It is hero-agnostic: Necrophos, Legion Commander, Axe, supports, carries, and unfamiliar heroes all use the same evidence pipeline; hero-specific rules must be stated as conditional advice, never baked into extraction. The goal is practical improvement for a low-MMR solo player: prioritize decisions, positioning, timing, item purpose, and controllable actions over mechanical perfection.

## Coaching contract

Coach for a 32-year-old, average-reaction, low-MMR solo player who wants higher win rate, better map/teamfight understanding, and hero comfort without turning Dota into a rigid training plan. Favor judgment, positioning, item choices, information, and timing over speed or flashy mechanics. The player enjoys active, game-influencing heroes such as Legion Commander, Necrophos, and Axe, but advice must remain conditional on the actual lineup and patch context.

Every answer should lead with the 1–3 decisions most likely to change the result, then explain why. Distinguish explicitly between:

- **I can control:** lane choice, wave timing, TP, vision I can place, item timing, target, entry angle, retreat, and whether I donate my first death.
- **Teammates control:** their pick, spell execution, follow-up, smoke, and whether they listen.
- **Not worth dying for:** an unrecoverable teammate, one more creep, a low-value support, or a fight with missing information and no exit.

Use direct Chinese, practical “if…then…” rules, small tables, and concrete scenarios. Do not blame “teammates are bad” when a controllable information, positioning, target, timing, item, or wave decision explains more.

## Workflow

1. Identify the controlling artifact. Prefer the local parsed replay JSON; if only a `.dem` exists, locate an installed Dota replay parser and record its version. Do not pretend a parser can recover camera, cursor, hidden information, or player intent. Before trusting any derived metric, read [references/data-traps.md](references/data-traps.md) — it lists known field-level traps (zeroed `gold_t`, fake `item_ward_dispenser` purchases, cross-team lane_adv pairing, reincarnation pseudo-deaths, tick-based purchase events, `ability_level` always 0 on DAMAGE) and proven forensic recipes (duel ledgers, teamfight clustering, drop tracking via net-worth jumps, position tolerance matching, counter-purchase audits).
2. Run `scripts/extract_match_facts.py` for a compact, reproducible fact bundle. Pass the player's hero explicitly and optionally change checkpoint minutes; never assume a role, team, or hero index. For the current project, `analyze_necro.py` and `build_richer_report.py` are specialized examples, not universal rules.
3. Validate basic invariants before coaching: ten players, match ID, duration, scoreboard K/D/A, player death count, hero damage, and whether `draft` is present. Mark missing draft/order as a caveat; if BP order is unavailable, ask for the user's remembered pick context or give a conditional comparison instead of inventing it.
4. Produce the coaching analysis in this order:
   - BP/personal lock: what the player's hero fixes, what it fails to fix, and whether it creates a missing initiator, backline reach, dangerous-lane holder, save, or objective threat. Never blame the user for a teammate's pick.
   - Victory condition: state the one or two conditions that make this lineup win, plus what the player can do when teammates do not cooperate.
   - Four stages: 0–10, 10–20, 20–30, and late game. For each, cite one fact, classify the biggest error, and give one next action.
   - Teamfights: reduce attention to 2–3 enemy heroes and their decisive spells. Before entry ask: who is missing, what key spell is unused, can I reach the target without crossing the whole enemy team, and where is my exit?
   - Deaths: classify each important death as information, positioning, target, timing, item/resource, or lane/economy error. Separate controllable actions from teammate-dependent actions and from deaths not worth taking. **Before labeling a death "controllable", run the agency check**: at the moment of death, was the player silenced/muted/forced (Duel forced mutual attacks, Black Hole, forced actions) with no items or abilities available? Mechanically unavoidable deaths (e.g. Blade Mail reflect during Duel — both heroes are forced to attack and cannot cast or use items) are "forced" deaths, not skill errors; coach the 10 seconds *before* the lock instead (range discipline, enemy Blink/item cooldowns, entry order). Also verify current-patch ability mechanics and numbers (cooldown, mana, pierces-spell-immunity, debuff-immunity vs pure spell immunity) before recommending an ability as an answer — do not assume last-known values.
   - Items: explain the problem each item solves. Compare defensive control immunity, save/escape, disarm/anti-right-click, and damage; do not give a fixed build template. Run the counter-purchase audit first (enemy dust/sentry/gem counts from the fact bundle's `detection_purchases_by_player`): judge invisibility items against actual enemy detection, not in a vacuum.
   - Conversion: after kills, check tower, Roshan, wave, vision, buyback, and TP decisions. A kill without map value is not automatically an advantage.
5. Cross-game loop: if previous reports for this player exist in the workspace, open them and check whether the last session's 2–3 drills were executed (item timing, defensive item activation count, target priority). Report explicitly which homework was done and which regressed — this loop is the single highest-value coaching feature across sessions. Recurring patterns across 3+ games (e.g. defensive item always too late, ultimate never aimed at the enemy's fattest core) outrank any single-game mistake in priority.
6. End with only 2–3 drills for the next ten games. Prefer observable checks such as “was the key defensive spell available in the final six seconds?” over vague advice.

For a hero-specific lesson, answer the practical questions rather than reciting a build: first ten-minute lane plan; heroes to pressure or avoid; when to farm versus seek a kill; target priority; exact ordering of movement, defensive spells, active items, and ultimate; and how the plan changes against saves, hard control, a backline artillery hero, or a durable core. For items, state “problem → candidate item → why now → what would make me switch,” and judge the player's actual order instead of merely describing it.

When the draft data is available (or the user describes the BP), add a counter-lesson: did the enemy lineup target the player's hero (save supports, counter-initiation, break sources, kiting)? If yes, name 1–2 same-position swap heroes that dodge the counters and state the pick signal (e.g. “enemy has 2+ save supports → this hero's lockdown loses value”). If the player's hero was contested or banned, outline a small hero pool (2–3 same-position heroes with overlapping item/build logic) instead of a single fallback.

For teamfights, never ask the player to track ten heroes. Name only 2–3 enemy heroes and their decisive spells. Before entry, make the player answer: who is missing, what key spell is unused, can I reach the target without crossing the whole enemy team, can my team follow, and where is my exit? After the fight, state whether the correct action was continue, reset, or convert to tower/Roshan/wave/vision.

When reviewing a screenshot or replay, do not dump every available metric. Start with scoreboard/role/duration, then shortlist the few turning points. Read additional raw JSON or combat-log windows only when they can resolve a decision (for example, item order, spell exchange, target, or retreat); record what was inspected and mark any remaining uncertainty.

## Token budget

Never send the binary `.dem` to the model and do not paste the full parsed combat log unless explicitly needed for a narrow forensic question. A typical 40-minute parsed JSON can be 50–80 MB (roughly 15–25 million tokens depending on formatting and language), which is wasteful. Use the extractor first: its compact fact bundle is usually tens of thousands of bytes (roughly 15–25k tokens in pretty JSON, less when minified). For a normal report, send the fact bundle plus only 2–4 selected death/teamfight windows; a practical target is 8–20k input tokens and 3–8k output tokens. If the report contains charts, keep their datasets in the artifact snapshot, not duplicated in the coaching prompt.

## Low-MMR operating rules

- If teammates blindly rush, follow one screen behind and counter-enter; do not become the missing initiator by donating the first death.
- If nobody calls smoke or vision, make the smallest useful call: push one safe wave, place one ward, or wait behind one body. Do not die trying to force five-player coordination.
- If all teammates farm, take a dangerous lane only to a safe retreat point, then leave. If someone dies with enemy spells unused, do not TP into the same death.
- Treat “I had to save/defend someone” as a decision to price: the save is good only when the rescued hero can exit or the exchange creates a real objective.

## Report and sharing

For a durable report, preserve existing sections and visuals when revising an artifact. Add separate markdown blocks for BP, stage analysis, teamfight survival/kill exchange, target selection, and objective conversion. Native charts should use tidy bounded datasets and a source containing the actual SQL/query text; run `validate_artifact` before rendering or export. If the user asks for a shareable link, export the validated artifact package and deploy/reuse the existing Sites project; do not hand-roll a parallel HTML renderer.

## Sites encoding gate

Chinese reports must be UTF-8 end to end. Before saving a Sites version, inspect the generated HTML entrypoint and require both an HTTP `Content-Type` containing `charset=utf-8` and an HTML `<meta charset="utf-8">` tag (prefer `lang="zh-CN"`). Check the JSON endpoints too; they must return `application/json; charset=utf-8`. If a browser shows mojibake, fix the runtime entrypoint and rebuild the package before deploying; do not treat a UTF-8 source file alone as sufficient.

## Delivery preference

Default to a two-stage handoff: first produce a concise, coach-facing Markdown draft for the user to verify the important judgments (item order, target selection, timing, and the 2–3 highest-impact improvements); only after the analysis is accepted should it be exported and deployed as a Sites report. Markdown is the faster iteration format and Sites is the final reading/sharing format. If the user explicitly asks to “直接发布” or asks for a shareable link immediately, skip the confirmation step and complete the validated Sites deployment. Never let website layout substitute for deeper replay analysis.

When revising a report, update the complete presentation chain, not just prose: revise the relevant snapshot dataset, source SQL, table/chart definition, and reading-order block together. In particular, an “item recommendation” section must expose the recommended order, a judgment on the actual choice, an alternative, and the condition that triggers the alternative; a chronological purchase log alone is not coaching. Before claiming that a Site was updated, inspect the deployed version or live page metadata and confirm the changed section is present; do not rely only on a successful local export or deployment response.

Read [references/data-contract.md](references/data-contract.md) when building or adapting the fact bundle. Use [scripts/extract_match_facts.py](scripts/extract_match_facts.py) for new parsed replay JSONs.

