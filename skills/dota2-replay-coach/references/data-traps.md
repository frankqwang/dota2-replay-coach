# Data traps and forensic recipes (gem-dota parsed replays)

Accumulated from real analysis sessions. Read before trusting any derived metric.
These apply to the parsed JSON shape used by `extract_match_facts.py`.

## Traps (things that produce wrong conclusions if used naively)

1. **`gold_t` is all zeros** in current versions. Use `net_worth_t` (per-minute array); index it
   with the `times` array plus `game_start_tick` when exact seconds matter. Economy comparisons
   must go through net worth, never gold_t.

2. **`item_ward_dispenser` in `purchase_log` is NOT a purchase event.** It is the automatic merge
   of observer + sentry wards into one inventory slot. Summing it as gold produces a wildly
   inflated "vision spending" number. Patch-dependent prices: observers are free (stock-limited),
   sentries and smoke are cheap consumables. Count consumables by item name, do not price them
   from the log's `value` field (it is 0).

3. **`PURCHASE` events have `game_time_s = null`; they are tick-based.** Convert with
   `game_start_tick` before comparing to combat events. DEATH/DAMAGE events carry `game_time_s`.

4. **`lane_gold_adv` / `lane_xp_adv` pair lanes ACROSS teams by `lane_role` digit** (1=safe,
   2=mid, 3=off), i.e. "Radiant offlane vs Dire offlane", NOT the actual same-lane matchup.
   Never use them to decide who laned against whom. The `lane_role` field itself IS reliable.
   To learn who actually stood in a lane: position_log co-occurrence (pairs within 1500 units,
   first 8 minutes). Coordinate geometry is only needed when lane_role is missing.

5. **`position_log` ticks do not start at 0 and have offsets.** Match by tick intersection, and
   for "who was near X at time T" use tolerance matching (±60–120 ticks, nearest sample),
   not exact tick lookup.

6. **Reincarnation heroes emit fake DEATH events.** `will_reincarnate: true` means the death was
   prevented by Reincarnation-type ultimates (Wraith King, etc.): the scoreboard does not count
   it, and the player keeps items. `will_reincarnate: false` is a real death (dropped items for
   Rapier holders). Always filter or flag before comparing "deaths in combat_log" vs scoreboard.

7. **OpenDota side files (`od_*.json`) players[] order is NOT the parsed players[] order.** Align
   by slot/hero_id. OpenDota has no `hero_name`; the parsed file is the source for hero identity.
   `kills_log`/`deaths_log` in OpenDota data are frequently `None` — attribute kills via the
   parsed DEATH event's `damage_source_name` instead.

8. **DAMAGE events have `ability_level` = 0 always.** To infer skill builds, use ABILITY cast
   events (their `ability_level` is real) and take per-minute level peaks.

9. **Item actives are invisible in DAMAGE logs.** Reconstruct BKB / Blade Mail / Silver Edge /
   Phase usage from `MODIFIER_ADD` / `MODIFIER_REMOVE` events (e.g. inflictor
   `modifier_black_king_bar_immune`). Filtering by `attacker` misses some applications — filter
   by `inflictor_name` on MODIFIER_ADD instead.

10. **`combat_log` has no item-pickup events** (e.g. dropped Rapiers). Track drops/pickups via
    net-worth jumps (a +4000+ spike on a player within seconds) and position_log proximity to the
    death location.

## Forensic recipes (proven analysis patterns)

- **Duel-like ultimate win/loss ledger**: pair each ABILITY cast event of the ultimate
  (inflictor filter) with DEATH events of either participant within ~7s → WIN / LOSE / no-result.
- **Teamfight reconstruction**: cluster DEATH events into 60s windows; count deaths per side and
  chain killer→victim to describe each exchange. Complement with `opendota_teamfights` /
  `teamfights` player sub-objects (damage dealt/taken, gold/xp delta, item uses).
- **Death scene forensics**: for a death at tick T, tolerance-match all ten position_logs near T
  (±120 ticks) to list who was present; aggregate incoming DAMAGE by attacker + inflictor in
  2-second buckets for the last 30s to show "was he fighting or pushing".
- **Rapier / drop tracking**: DEATH with `will_reincarnate: false` on an item holder → items
  dropped at death location; scan all players' `net_worth_t` per second for +4000-ish jumps to
  find the picker; confirm with position_log proximity. Kills on the picker repeat the process.
- **Counter-purchase audit (do this BEFORE judging item choices)**: scan every enemy player's
  purchase_log for sentries (`item_ward_sentry`), dust (`item_dust`), and gem
  (`item_gem`). An invisibility item (Shadow Blade / Silver Edge) bought against 0 detection
  stays at full value all game; the same item against 6 dusts + 40 sentries was wasted gold.
- **Attack-damage audit for duel-reward heroes**: permanent bonus damage comes from ultimate
  wins (e.g. Legion Commander +18 per win at max level). Total = base stats + items +
  (wins × bonus). Cite wins from the duel ledger, not the final damage number alone.
