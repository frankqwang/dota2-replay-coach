# Data traps and forensic recipes

Accumulated from real analysis sessions. Read before trusting any derived metric.

Three data shapes are covered:

- **§Traps / §Forensic recipes** (traps 1–10) — the parsed **event JSON** (gem-dota path, OpenDota's
  `teamfights`/`kills_log`). These apply equally when you query the **SQLite index**
  (`index_parsed.py`) built from that JSON — the columns carry the same names and traps.
- **§Per-tick coordinate CSV** (traps 11–18) — the **clarity path** output, which has its own
  failure modes.
- **Trap 19** (pause-aware time) is the one that spans both: it explains why tick-based event data
  must subtract pauses per-event, and why the coordinate CSV can get away with a single constant.

## Traps (things that produce wrong conclusions if used naively)

1. **`gold_t` is all zeros** in current versions. Use `net_worth_t` (per-minute array); index it
   with the `times` array plus `game_start_tick` when exact seconds matter. Economy comparisons
   must go through net worth, never gold_t.

2. **`item_ward_dispenser` in `purchase_log` is NOT a purchase event.** It is the automatic merge
   of observer + sentry wards into one inventory slot. Summing it as gold produces a wildly
   inflated "vision spending" number. Patch-dependent prices: observers are free (stock-limited),
   sentries and smoke are cheap consumables. Count consumables by item name, do not price them
   from the log's `value` field (it is 0).

3. **`PURCHASE` and `GOLD`/`XP`/`MODIFIER` events have `game_time_s = null`; they are tick-based.**
   Convert with `game_start_tick` before comparing to combat events. DEATH/DAMAGE/ABILITY events
   carry `game_time_s` directly. **The conversion must subtract paused time** — see trap 19.
   `index_parsed.py` does this for you and writes the result into `game_time_s`.

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

## Traps specific to the per-tick coordinate CSV (clarity path)

11. **`gametime` is `tick/30`, not the in-game clock.** `m_pGameRules.m_fGameTime` is frequently
    unreadable, so the column is raw demo time. **Calibrate per match**: match the hero's death
    moments to scoreboard/OpenDota deaths and solve `real_seconds = csv_gametime − k`. Verify `k`
    reproduces *every* death to ≤1 s before computing anything. (Observed offset in one match: 229 s.)
    The offset is per-match and absorbs that match's pause time into a single constant — which is
    exactly why it must be re-solved per replay, and why it must be a *constant* fit verified
    against all deaths (a bad fit shows up as some deaths aligning and others not — see trap 17).

12. **A hero is not one entity.** Illusions/clones share the same DT class
    (`CDOTA_Unit_Hero_*`). Take the real body as the smallest/first `index` per hero per team, or
    match against the team — otherwise you will plot illusion ghosts.

13. **Pre-game rows exist and start negative-ish.** Heroes can appear before the horn; filter to the
    laning window explicitly, and do not treat the first CSV row as 0:00.

14. **0.5 s sampling can miss the death instant.** `lifestate≥1` marks the dying window; a hero can
    go from full HP to dead between samples. Use the death window's start position as "where he was
    when caught", and cross-check the exact second against the scoreboard.

15. **Coordinates are `cell × 128 + vec`, map ≈ 0–32768.** Distances are in game units: attack range
    ≈ 600, tower range ≈ 700, XP range ≈ 1300. "Team disconnected" ≈ > 2000 between the player and
    the nearest ally. State the unit basis when you cite a distance — a raw number means nothing to
    the reader without it.

16. **Death-cause must come from the event log, not the CSV.** The coordinate CSV shows *where* and
    *when*, never *who* or *what killed you*. Pair it with the parsed JSON's DEATH events (or OpenDota
    `killed_by`) to name the killer; do not infer the killer from proximity alone.

17. **A sampled death window can miss the real death second.** `lifestate >= 1` marks the *dying*
    window, so the first transition is at or after the true death. In one verified match every
    window aligned within 0.5 s except one that was ~8 s off — an illusion body or a revive inside
    the sampling gap. **Solve the clock offset by median, not mean**, and treat the odd window as an
    outlier instead of letting it shift the offset for the whole match (`ticks_coach.py` does this).

18. **Never hard-code a hero index, team roster, or offset into an analysis script.** Hero entity
    indices differ every match, and the clock offset differs by game-start time. Both must be read
    from the CSV (`dtname` / `team`) or passed as arguments. A script that only works on one match
    is not reusable and silently mislabels any other match.

19. **Raw ticks do not stop during a pause; `game_time_s` does.** Converting `tick → seconds` with
    a flat `tick/30 − constant` therefore **drifts by the total paused time** for every event after
    the pause. Verified in one match: `game_clock.pauses` held 3 pauses (~46 s total), and a naive
    conversion was off by exactly that amount from the first pause onward while matching perfectly
    before it — which is why the error is easy to miss if you only calibrate early. The correct
    conversion is
    `t = (tick − game_start_tick)/30 − paused_ticks_before(tick)/30`,
    and it reproduces the `game_time_s` of 4,213 DEATH and 9,941 MODIFIER_ADD events to within
    0.5 s with zero mean bias. **Do not add `pre_game_duration`** — that injects a constant ~90 s
    error. Pause windows live in `game_clock.pauses`; `index_parsed.py` applies this to every
    `combat_log`, `player_series`, and `player_events` time column.

    **Why trap 11 survives this:** the coordinate CSV has no `game_clock` and no per-event
    `game_time_s`, so there is nothing to subtract pause-by-pause against — but the *aggregate*
    pause time is still a constant for a given match, and it is absorbed into the single solved
    offset `k`. Fitting `k` against **all** deaths is what makes that safe: a wrong constant shows
    up as deaths that align before the first pause and drift after it. Trap 19's formula is for
    data that *has* tick + `game_clock`; trap 11's constant is for data that does not.
