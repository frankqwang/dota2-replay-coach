# Querying the parsed replay (SQLite)

`scripts/index_parsed.py` turns a gem-dota parsed JSON (50–140 MB, too big to read
into context) into a **SQLite database you write SQL against**. This replaces the
old fixed-subcommand helper: instead of getting pre-chewed metrics, you compose the
query the decision actually needs.

```
python scripts/index_parsed.py <parsed.json> [out.db] [--info] [--keep-json] [--force]
```

- Default output is `<parsed>.db` next to the JSON. `--info` prints the schema and
  row counts — **run it first and read the output**; that dump is your map.
- The JSON is never modified; delete and rebuild the `.db` any time.
- Conversion takes ~3 s and roughly halves the size (141 MB JSON → ~107 MB db).

Query it however you like: `sqlite3 file.db "SELECT ..."`, Python's `sqlite3`,
DB Browser, etc. `json_extract()` works on the `*_json` columns.

---

## The one thing to get right: time

**Every time column is on the same clock — the in-game clock in seconds, pauses
excluded.** That includes:

- `combat_log.game_time_s` (and `minute`, `minute10` for bucketing)
- `player_series.t`
- `player_events.t`

Negative values are legitimate: they are the pre-game shopping phase (typically
about −90 s). `duration` in `meta` is the horn-to-end length, so the last rows of a
series sit near `t = duration`.

Why this matters: raw demo ticks keep counting during a pause while the real clock
does not, so a naive `tick/30` drifts by the total pause time (observed: a ~46 s
pause shifted everything after it by 46 s). `index_parsed.py` subtracts
pauses from `game_clock.pauses`. Do **not** re-derive times from `tick` yourself.

> If you need a tick, use `combat_log.tick` and convert with the same rule:
> `t = (tick − game_start_tick)/30 − paused_ticks_before(tick)/30`.
> **Never add `pre_game_duration`** — it is already accounted for.

---

## Tables

### `meta` — match header, one row per key

Everything top-level that was not a list. Read it first.

```
SELECT value FROM meta WHERE key='match_id';
SELECT value FROM meta WHERE key IN ('radiant_win','radiant_score','dire_score','duration');
```

Useful keys: `match_id`, `game_mode` (22 = all-pick, **no draft**), `radiant_win`,
`radiant_score`, `dire_score`, `duration`, `first_blood_time`, `game_start_tick`,
`game_end_tick`, `pre_game_duration`. `game_clock` is stored as JSON — it holds
`pauses` and `game_start_time_s`.

### `players` — 10 rows, one per player

Scalar columns only, so comparing players is a single `GROUP BY`-free scan.
`player_id` 0–4 = Radiant, 5–9 = Dire (also `is_radiant`, `team`; team 2 = Radiant,
3 = Dire).

Key columns: `hero_name` (`npc_dota_hero_*` — the stable join key), `hero_id`,
`player_name`, `account_id`, `kills`/`deaths`/`assists`/`kda`, `net_worth`,
`last_hits`, `denies`, `gold_per_min`, `xp_per_min`, `hero_damage`, `tower_damage`,
`level`, `lane_role` (1=safe, 2=mid, 3=off — **reliable**), `lane_efficiency_pct`,
`obs_placed`, `sen_placed`, `camps_stacked`, `rune_pickups`, `tower_kills`,
`roshan_kills`, `buyback_count`, `win`.

```
-- 10-player overview
SELECT player_id, hero_name, is_radiant, lane_role, kills, deaths, assists,
       net_worth, last_hits, gold_per_min
FROM players ORDER BY is_radiant DESC, player_id;
```

### `combat_log` — 79k rows, the event firehose

One row per game event. All the original JSON fields are real columns (plus any
extra as `x_<field>`), so you filter with plain SQL instead of parsing JSON.

Common columns: `tick`, `game_time_s`, `minute`, `minute10`, `log_type`, `value`,
`attacker_name`, `target_name`, `inflictor_name`, `damage_source_name`,
`value_name`, `damage_type`, `stun_duration`, `gold_reason`, `xp_reason`,
`attacker_team`, `target_team`, `location_x`, `location_y`,
`modifier_duration_s`, `aura_modifier`, `rune_type`, `will_reincarnate`,
`ability_level`, `attacker_is_hero`, `target_is_hero`, `attacker_is_illusion`,
`target_is_illusion`, `visible_radiant`, `visible_dire`.

`log_type` values and counts (this match): `DAMAGE` 28k, `UNKNOWN` 12k,
`MODIFIER_ADD` 10k, `MODIFIER_REMOVE` 10k, `XP` 4.6k, `DEATH` 4.2k, `HEAL` 4.0k,
`GOLD` 3.0k, `ABILITY` 1.5k, `ITEM` 792, `PURCHASE` 540, `PICKUP_RUNE` 48,
`KILLSTREAK` 22, `MULTIKILL` 8.

Field-level traps (see [data-traps.md](data-traps.md) for the full list):

| Field | Trap |
|---|---|
| `ability_level` on `DAMAGE` | **always 0**. Real levels only on `ABILITY` casts. |
| `location_x/y` on `DAMAGE` | **always NULL** in this dataset. Coordinates come from `player_series` or `wards`/`objectives`, not combat rows. |
| `game_time_s` on `PURCHASE`/`GOLD`/`MODIFIER` | NULL in the JSON; **backfilled** here from `tick`, so it IS usable — but it is derived, not observed. |
| `value` on `PURCHASE` | **0 for most items**. Count purchases by `value_name`; never price them from `value`. |
| `value_name = 'item_ward_dispenser'` | **not a purchase** — it is the observer+sentry merge into one slot. Always exclude it. |
| `will_reincarnate` | `true` = the death was prevented by Reincarnation (scoreboard does not count it). Filter these out when reconciling with the scoreboard. |
| `target_name` for PURCHASE | the **buyer**; may not equal the `players.hero_name` spelling (e.g. `anti_mage` vs `antimage`) — build the map from observed values. |
| DAMAGE `value` | post-mitigation. Summing across source gives damage taken, not raw. |

```
-- what killed a hero in the last 8 s before a death
SELECT round(game_time_s,1) t, damage_source_name, round(SUM(value)) dmg, COUNT(*) hits
FROM combat_log
WHERE log_type='DAMAGE' AND target_name='npc_dota_hero_legion_commander'
  AND game_time_s BETWEEN 441 AND 449.5
GROUP BY damage_source_name ORDER BY dmg DESC;
```

### `player_series` — 444k rows, every curve (long format)

One row per `(hero, series, sample)`. This is where all the numbers live.

```
player_id, hero_name, series, sample_idx, t, value
```

`series` names:

- per-tick (indexed by `times`, ~0.33 s): `net_worth_t`, `gold_t` (**all zeros — do not use**),
  `lh_t`, `dn_t`, `xp_t`, `total_earned_gold_t`, `total_earned_xp_t`
- per-minute (indexed by `game_times_min`): the `_t_min` twins above, plus
  `total_hero_damage_t_min`, `total_hero_healing_t_min`, `total_deaths_t_min`,
  `total_stuns_t_min`
- **`pos_x` / `pos_y`** — true per-tick hero coordinates (see below)
- **`ability::<ability_name>`** — ability level over time, one series per ability

```
-- net worth of every player at 10 / 20 / 30 min, richest first
SELECT hero_name, t, value AS net_worth FROM player_series
WHERE series='net_worth_t_min' AND t IN (600,1200,1800)
ORDER BY t, value DESC;
```

**Coordinates.** `pos_x`/`pos_y` are game units, `0 ≤ v ≤ 32768`, one sample per
~0.33 s, and the axes are aligned across all ten heroes (same `sample_idx`/`t`
grid), so you can join a hero to any other at the same `sample_idx`. Reference
distances: attack range ≈ 600, tower range ≈ 700, XP range ≈ 1300; **> 2000 means
the team is effectively disconnected**. Always state the unit basis when quoting a
distance.

```
-- at each of a hero's deaths, how far was the nearest living teammate?
WITH pos AS (
  SELECT x.hero_name, x.t, x.value AS x, y.value AS y
  FROM player_series x
  JOIN player_series y ON y.hero_name=x.hero_name AND y.series='pos_y'
                      AND y.sample_idx=x.sample_idx
  WHERE x.series='pos_x'
),
deaths AS (SELECT game_time_s AS t FROM hero_deaths
           WHERE hero_name='npc_dota_hero_legion_commander')
SELECT round(d.t,1) AS t_s,
  (SELECT round(MIN(SQRT((m.x-a.x)*(m.x-a.x)+(m.y-a.y)*(m.y-a.y))))
   FROM pos m JOIN pos a ON ABS(a.t-m.t) < 1.0
   WHERE m.hero_name='npc_dota_hero_legion_commander' AND ABS(m.t-d.t) < 1.5
     AND a.hero_name IN (SELECT hero_name FROM players WHERE is_radiant=1)) AS nearest_ally
FROM deaths d ORDER BY d.t;
```

The `ABS(...t...) < 1.0` tolerance matters: samples are ~0.33 s apart and rows can
miss each other by one tick, so exact `=` joins drop matches silently.

### `player_events` — 2.9k rows, per-hero timestamped lists

`kills_log`, `purchase_log`, `runes_log`, `buyback_log` flattened to
`(hero_name, event, t_tick, t, log_type, key, value, extra_json)`.

```
SELECT round(t,1), key FROM player_events
WHERE hero_name='npc_dota_hero_legion_commander' AND event='purchase_log'
ORDER BY t;
```

Note `kills_log` is **this hero's own kills** (creeps included), not the match kill feed.

### `player_json` — 340 rows, leftover nested maps

Wrapped dicts, reachable with `json_extract()`. Notable keys: `damage_targets`
(whom I hit, by ability), `damage_taken` (who hit me), `ability_targets` (ability →
victim counts, **useful for what a targeted ult was aimed at**), `damage_by_type`,
`damage_inflictor`, `final_items`, `gold_ledger`, `killed`, `killed_by`,
`gold_reasons`, `xp_reasons`, `lane_pos` (a grid, `{x:{y:count}}`), `multi_kills`.

```
-- a targeted ultimate's victim distribution (ability_targets nests ability -> victim -> count)
SELECT je.key AS ability, je2.key AS victim, je2.value AS casts
FROM player_json AS pj, json_each(pj.value_json) AS je, json_each(je.value) AS je2
WHERE pj.key='ability_targets' AND pj.hero_name='npc_dota_hero_legion_commander'
ORDER BY casts DESC;
```

`json_each` needs aliased table names (`je` in the snippet above) — an unqualified
`key` is ambiguous between the outer table and the JSON function.

### Remaining tables (small, one row per event/object)

| Table | Rows* | What |
|---|---|---|
| `objectives` | 22 | building kills / first blood / roshan, with `time`, `type`, `key`, `unit`, `player_slot` |
| `towers` | 14 | tower kills: `tick`, `team`, `killer`, `tower_name` |
| `barracks` | 6 | rax kills |
| `wards` | 101 | `placer`, `ward_type` (observer/sentry), `x`, `y`, `expires_tick`, `killed_tick`, `killer` |
| `fights` | 57 | auto-clustered teamfights: window, `radiant_kills`, `dire_kills`, `winner`, centroid, per-player `players` JSON |
| `opendota_teamfights` | 8 | OpenDota's own teamfights; `players[i]` has `deaths_pos`, `ability_uses`, `item_uses`, `gold_delta` |
| `entity_visibility_events` | 42.6k | per-tick entity visibility (`radiant_state`/`dire_state`) |
| `hero_visibility_events` | 4.3k | hero-specific visibility transitions |
| `courier_snapshots` | 6.0k | courier position/tick |
| `vision_modifiers` | 83 | dust/sentry reveals with `semantic` and lifecycle |
| `neutral_item_finds` | 38 | neutral item drops (`item_key`, `item_tier`, enhancement) |
| `chat` | 2 | `tick`, `player_slot`, `channel`, `text` |
| `radiant_gold_adv`, `radiant_xp_adv`, `game_times_min` | 46 | plain value lists → `(idx, value)` |

\* row counts from one 46-minute all-pick match; scale with duration.

### Views

Pre-join the most common filters so you write less SQL. They are conveniences —
read their definition (`SELECT sql FROM sqlite_master WHERE name='hero_deaths'`)
before relying on the subtle parts.

| View | Columns |
|---|---|
| `hero_deaths` | `game_time_s`, `tick`, `hero_name`, `killer`, `damage_source`, `attacker_is_illusion`, `will_reincarnate`, `victim_team`, `victim_is_radiant` — hero-vs-hero deaths only (creeps filtered) |
| `hero_purchases` | `game_time_s`, `hero_name`, `item`, `value`, `team`, `is_radiant` — ward-dispenser already excluded |
| `ability_casts` | `game_time_s`, `caster`, `ability`, `ability_level`, `target` — hero ability casts only |
| `modifier_applied` | `game_time_s`, `caster`, `modifier`, `target`, `modifier_duration_s`, `aura_modifier` — use for item actives (BKB/Blade Mail/Silver Edge) |

```
-- item-activation ledger (item actives are invisible in DAMAGE)
SELECT round(game_time_s), caster, modifier FROM modifier_applied
WHERE modifier LIKE '%black_king_bar%' ORDER BY game_time_s;

-- counter-purchase audit: did the enemy actually buy detection?
SELECT hero_name, COUNT(*) FROM hero_purchases
WHERE item IN ('item_dust','item_ward_sentry','item_gem') GROUP BY hero_name;
```

---

## Recipes

**Scorecard.** `SELECT hero_name, kills, deaths, assists FROM players;`
Cross-check `deaths` against `SELECT COUNT(*) FROM hero_deaths WHERE hero_name=...`
— a mismatch means reincarnation pseudo-deaths or an illusion, investigate before
coaching.

**Duel ledger** (or any targeted ultimate). Pair each cast with deaths within ~7 s:
cast from `ability_casts`, victims from `hero_deaths`, join on
`ABS(cast.t − death.t) < 7`.

**Teamfight reconstruction.** Cluster via `combat_log` `DEATH` rows in 60 s windows
(one query with `minute`), or just read `fights`/`opendota_teamfights`.

**Economy windows.** `net_worth_t_min` for both sides at 10/20/30, or the
minute-over-minute delta (`value − LAG(value) OVER (PARTITION BY hero_name ORDER BY sample_idx)`)
to find when a hero stopped farming.

**Death forensics.** For a death at `t`, pull incoming `DAMAGE` grouped by
`damage_source_name` over `[t−8, t]`, the victim's `pos_x/pos_y` vs each ally's, and
the caster's `modifier_applied` rows — that trio answers *who, with whom, and was
there an escape available*.

---

## Guardrails

- **Do not read the .dem or the raw JSON into context.** Query the `.db`; it is
  already compact and indexed.
- Reconcile before concluding: `players.deaths` vs `hero_deaths` count vs
  `meta.dire_score`/`radiant_score`.
- `game_mode 22` (all-pick) has **no `draft`** — write the BP section conditionally.
- Cite timestamps as `m:ss` derived from `game_time_s`; do not quote `tick`.
- Full field-trap list: [data-traps.md](data-traps.md).
