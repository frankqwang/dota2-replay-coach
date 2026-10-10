#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""index_parsed.py -- load a gem-dota parsed JSON into SQLite so it can be queried.

Why this exists
---------------
A 40-minute parsed replay is ~135 MB / ~33M tokens. That is far too large to read
into a model's context, and unpleasant even for `grep`/`jq` (one giant
pretty-printed object; every query re-parses the whole file).

So convert it ONCE into a SQLite database. After that the model writes ordinary
SQL -- which is cheaper, faster, and far more flexible than a fixed set of helper
subcommands. The schema is deliberately a thin, transparent mapping of the JSON,
so nothing is hidden and no judgment is baked in.

  python index_parsed.py <parsed.json> [out.db] [--info] [--force]

Design notes
------------
- The source JSON is never modified; regenerate the .db any time.
- One table per top-level list; top-level scalars go into `meta`.
- Per-player data is split four ways so each is queryable the natural way:
    players        one row per player, scalar columns
    player_series  long format (hero, series, sample_idx, t, value) for curves
    player_events  long format (hero, event, t, key, value) for timestamped lists
    player_json    leftover nested maps, reachable via json_extract()
- `combat_log` keeps every JSON field as its own column (extra_hit_* prefixed)
  plus `minute` / `minute10` for cheap bucketing.
- A `game_time_s` backfill: only some log types carry it; the rest are derived
  from `tick` via `game_start_tick`. The raw value is kept in `game_time_s_raw`.

Run `--info` afterwards: that dump is the map you hand to the model.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path


def flatten(value):
    """SQLite stores scalars. Dict/list -> JSON text; bool -> 0/1; None -> NULL."""
    if value is None or isinstance(value, (int, float, str)):
        return value
    if isinstance(value, bool):
        return int(value)
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


# combat_log columns promoted to real columns. Order = the order you read them in.
COMBAT_COLUMNS = [
    "tick", "timestamp_s", "log_type", "value",
    "attacker_name", "target_name", "inflictor_name", "damage_source_name", "value_name",
    "damage_type", "stun_duration", "gold_reason", "xp_reason",
    "attacker_team", "target_team", "location_x", "location_y",
    "modifier_duration_s", "modifier_elapsed_duration_s",
    "aura_modifier", "neutral_camp_type", "rune_type",
    "will_reincarnate", "ability_level",
    "attacker_is_hero", "target_is_hero",
    "attacker_is_illusion", "target_is_illusion",
    "visible_radiant", "visible_dire",
]

# Per-player scalar columns (long per-minute arrays go into player_series instead).
PLAYER_SCALAR_HINTS = (
    "player_id", "hero_name", "hero_id", "player_name", "steam_id", "account_id",
    "team", "is_radiant", "kills", "deaths", "assists", "kda", "kills_per_min",
    "net_worth", "last_hits", "denies", "gold_per_min", "xp_per_min",
    "hero_damage", "tower_damage", "hero_healing", "level", "lane", "lane_role",
    "lane_efficiency_pct", "lane_gold_adv", "lane_xp_adv", "lane_last_hits", "lane_denies",
    "lane_total_gold", "lane_total_xp", "is_roaming",
    "obs_placed", "sen_placed", "observers_placed", "observer_uses", "sentry_uses",
    "camps_stacked", "creeps_stacked", "rune_pickups", "tower_kills", "roshan_kills",
    "buyback_count", "gold", "gold_spent", "total_gold", "total_xp",
    "stuns_dealt", "teamfight_participation", "win", "firstblood_claimed",
    "life_state_dead", "neutral_kills", "lane_kills", "ancient_kills",
    "courier_kills", "observer_kills", "sentry_kills",
    "purchase_tpscroll", "purchase_ward_observer", "purchase_ward_sentry",
    "aghanims_scepter", "aghanims_shard", "moonshard",
)

# Per-player list columns that are time series but do NOT end in _t / _t_min.
# The value is the axis name in the player dict, or None if there is no axis
# (then the list index IS the sample index).
EXTRA_SERIES = {
    "position_log": None,        # [[tick, x, y], ...] -- handled specially below
    "ability_upgrades_arr": None,  # ordered by level, not time
    "_ability_snapshots": None,    # [[tick, {ability: level}], ...]
}

# Per-player list columns whose elements are timestamped event dicts:
# {tick, log_type, ...} -> player_events rows.
EVENT_LIST_COLUMNS = ("kills_log", "purchase_log", "runes_log", "buyback_log", "buybacks")

SERIES_SUFFIXES = ("_t", "_t_min")


def build_meta(conn, data):
    """Top-level scalars and small nested dicts -> key/value rows."""
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value)")
    n = 0
    for k, v in data.items():
        if isinstance(v, list):
            continue
        conn.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (k, flatten(v)))
        n += 1
    return n


def build_generic_table(conn, key, rows):
    """One table per top-level list of dicts (or of scalars)."""
    if not rows:
        return 0

    if not isinstance(rows[0], dict):
        conn.execute(f'CREATE TABLE IF NOT EXISTS "{key}" (idx INTEGER PRIMARY KEY, value)')
        conn.executemany(f'INSERT OR REPLACE INTO "{key}" VALUES (?, ?)',
                         [(i, flatten(v)) for i, v in enumerate(rows)])
        return len(rows)

    cols, seen = [], set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k)
                cols.append(k)
    if key == "combat_log":
        header = [c for c in COMBAT_COLUMNS if c in seen]
        header += ["game_time_s", "minute", "minute10"]  # derived
        header += [f"x_{c}" for c in cols if c not in header]  # extras, namespaced
    else:
        header = cols

    quoted = ", ".join(f'"{c}"' for c in header)
    conn.execute(f'CREATE TABLE IF NOT EXISTS "{key}" (row_id INTEGER PRIMARY KEY, {quoted})')

    # combat_log needs tick -> game_time_s conversion; others copy through.
    if key == "combat_log":
        gst = None  # resolved lazily below by caller via conn
    placeholders = ", ".join("?" * (len(header) + 1))
    sql = f'INSERT INTO "{key}" (row_id, {quoted}) VALUES ({placeholders})'
    batch = []
    for i, r in enumerate(rows):
        vals = []
        for c in header:
            if c in ("game_time_s", "minute", "minute10"):
                vals.append(None)
            elif c.startswith("x_"):
                vals.append(flatten(r.get(c[2:])))
            else:
                vals.append(flatten(r.get(c)))
        batch.append([i] + vals)
        if len(batch) >= 5000:
            conn.executemany(sql, batch)
            batch = []
    if batch:
        conn.executemany(sql, batch)
    return len(rows)


def backfill_combat_times(conn, data):
    """Fill game_time_s / minute for combat_log rows that lack it.

    Only some log types (DEATH / DAMAGE / ABILITY / MODIFIER_ADD) carry
    `game_time_s` in the JSON. PURCHASE / GOLD / XP rows are tick-only. Derive
    from tick:

        game_time_s = (tick - game_start_tick) / 30 - paused_ticks_before(tick) / 30

    The pause term is essential: raw demo ticks keep counting while the game is
    paused, but `game_time_s` is the in-game clock, which does not. A 46-second
    pause mid-game otherwise shifts every later event by 46 s.

    Verified against this dataset: applying the formula to all 4,213 DEATH and
    9,941 MODIFIER_ADD events that DO carry `game_time_s` reproduces it to within
    0.5 s (max abs residual), with zero mean bias. `pre_game_duration` must NOT be
    added -- doing so injects a constant ~90 s error.
    """
    gst = data.get("game_start_tick")
    if gst is None:
        return
    pauses = (data.get("game_clock") or {}).get("pauses") or []

    conn.execute("CREATE TEMP TABLE _pauses (start_tick INTEGER, end_tick INTEGER)")
    if pauses:
        conn.executemany("INSERT INTO _pauses VALUES (?, ?)",
                         [(p["start_tick"], p["end_tick"]) for p in pauses])

    # Per-row: seconds = (tick - gst)/30 - sum(overlap of tick with each pause)/30
    conn.execute("""
        UPDATE combat_log SET
          game_time_s = COALESCE(
              game_time_s,
              (tick - :gst) / 30.0
              - (SELECT COALESCE(SUM(MAX(0, MIN(combat_log.tick, end_tick) - start_tick)), 0)
                 FROM _pauses) / 30.0
          ),
          minute   = CAST((COALESCE(game_time_s,
                        (tick - :gst) / 30.0
                        - (SELECT COALESCE(SUM(MAX(0, MIN(combat_log.tick, end_tick) - start_tick)), 0)
                           FROM _pauses) / 30.0)) / 60 AS INTEGER),
          minute10 = CAST((COALESCE(game_time_s,
                        (tick - :gst) / 30.0
                        - (SELECT COALESCE(SUM(MAX(0, MIN(combat_log.tick, end_tick) - start_tick)), 0)
                           FROM _pauses) / 30.0)) / 600 AS INTEGER)
    """, {"gst": gst})
    conn.execute("DROP TABLE _pauses")

    conn.execute("CREATE INDEX IF NOT EXISTS ix_combat_time ON combat_log (game_time_s)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_combat_type ON combat_log (log_type, game_time_s)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_combat_target ON combat_log (target_name, log_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_combat_attacker ON combat_log (attacker_name, log_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_combat_inflictor ON combat_log (inflictor_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_combat_tick ON combat_log (tick)")


def tick_to_seconds(tick, game_start_tick, pauses):
    """Same conversion as backfill_combat_times, usable from Python."""
    if tick is None or game_start_tick is None:
        return None
    paused = sum(max(0, min(tick, p["end_tick"]) - p["start_tick"]) for p in pauses)
    return (tick - game_start_tick) / 30.0 - paused / 30.0


def build_player_tables(conn, players, game_start_tick=None, pauses=None):
    """Split per-player data into scalars / series / events / json.

    See the module docstring for the rationale. Every sub-table carries
    `hero_name` so you never have to join through `players` for a quick filter.

    `t` on every series and event is in **seconds on the in-game clock**, i.e. the
    same axis as `combat_log.game_time_s` (pauses excluded). Raw demo ticks are
    converted with tick_to_seconds() so the two are directly comparable.
    """
    pauses = pauses or []

    def t_of(tick):
        return tick_to_seconds(tick, game_start_tick, pauses)
    scalar_cols, seen = [], {"player_id"}
    for p in players:
        for k, v in p.items():
            if (k in PLAYER_SCALAR_HINTS and k not in seen
                    and not isinstance(v, (list, dict))):
                seen.add(k)
                scalar_cols.append(k)

    quoted = ", ".join(f'"{c}"' for c in scalar_cols)
    conn.execute(f'CREATE TABLE IF NOT EXISTS players (player_id INTEGER PRIMARY KEY, {quoted})')
    sql = (f'INSERT OR REPLACE INTO players (player_id, {quoted}) '
           f'VALUES ({", ".join("?" * (len(scalar_cols) + 1))})')
    for p in players:
        conn.execute(sql, [p.get("player_id")] + [flatten(p.get(c)) for c in scalar_cols])

    # hero_name is denormalized into every sub-table: hero_name -> player_id is
    # 1:1 within a match, but joins are noisy in ad-hoc queries.
    conn.execute("CREATE TABLE IF NOT EXISTS player_series ("
                 "player_id INTEGER, hero_name TEXT, series TEXT, "
                 "sample_idx INTEGER, t REAL, value REAL)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_series ON player_series (hero_name, series)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_series_idx ON player_series (series, sample_idx)")

    conn.execute("CREATE TABLE IF NOT EXISTS player_events ("
                 "player_id INTEGER, hero_name TEXT, event TEXT, "
                 "t_tick INTEGER, t REAL, log_type TEXT, key TEXT, value REAL, extra_json TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_pevent ON player_events (hero_name, event)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_pevent_t ON player_events (event, t)")

    conn.execute("CREATE TABLE IF NOT EXISTS player_json ("
                 "player_id INTEGER, hero_name TEXT, key TEXT, value_json TEXT)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_pjson ON player_json (hero_name, key)")

    n_series = n_events = n_json = 0
    for p in players:
        pid, hero = p.get("player_id"), p.get("hero_name")
        tick_axis = p.get("times") or []          # raw demo ticks
        min_axis = p.get("game_times_min") or []  # ALREADY seconds since horn

        for k, v in p.items():
            if k in scalar_cols or k in ("times", "times_min", "game_times_min"):
                continue

            if isinstance(v, list) and v:
                # --- (a) timestamped event list: [{tick, log_type, ...}, ...] ---
                if k in EVENT_LIST_COLUMNS and isinstance(v[0], dict):
                    rows = []
                    for e in v:
                        tick = e.get("tick")
                        t = t_of(tick)
                        key = e.get("value_name") or e.get("inflictor_name") or ""
                        extra = {x: y for x, y in e.items()
                                 if x not in ("tick", "log_type", "value", "value_name",
                                              "inflictor_name", "target_name")}
                        rows.append((pid, hero, k, tick, t, e.get("log_type"),
                                     key, e.get("value"),
                                     json.dumps(extra, ensure_ascii=False,
                                                separators=(",", ":")) if extra else None))
                    conn.executemany(
                        "INSERT INTO player_events VALUES (?,?,?,?,?,?,?,?,?)", rows)
                    n_events += len(rows)
                    continue

                # --- (b) position_log: [[tick, x, y], ...] -> x / y series ---
                if k == "position_log" and isinstance(v[0], list):
                    xs, ys = [], []
                    for i, row in enumerate(v):
                        if len(row) < 3:
                            continue
                        t = t_of(row[0])
                        xs.append((pid, hero, "pos_x", i, t, row[1]))
                        ys.append((pid, hero, "pos_y", i, t, row[2]))
                    conn.executemany("INSERT INTO player_series VALUES (?,?,?,?,?,?)", xs)
                    conn.executemany("INSERT INTO player_series VALUES (?,?,?,?,?,?)", ys)
                    n_series += len(xs) + len(ys)
                    continue

                # --- (c) _ability_snapshots: [[tick, {ability: level}], ...] ---
                if k == "_ability_snapshots" and isinstance(v[0], list):
                    rows = []
                    for i, row in enumerate(v):
                        if len(row) >= 2 and isinstance(row[1], dict):
                            t = t_of(row[0])
                            for ability, lvl in row[1].items():
                                rows.append((pid, hero, f"ability::{ability}", i, t, lvl))
                    conn.executemany("INSERT INTO player_series VALUES (?,?,?,?,?,?)", rows)
                    n_series += len(rows)
                    continue

                # --- (d) numeric curve aligned to a time axis ---
                if isinstance(v[0], (int, float)):
                    # `_t_min` arrays are indexed by `game_times_min`, which is
                    # ALREADY "seconds since the horn" (0, 60, 120, ...).
                    # `_t` arrays are indexed by `times`, a raw demo-tick axis.
                    if k.endswith("_t_min"):
                        axis, is_seconds = min_axis, True
                    else:
                        axis, is_seconds = tick_axis, False
                    rows = []
                    for i, val in enumerate(v):
                        if i < len(axis):
                            t = axis[i] if is_seconds else t_of(axis[i])
                        else:
                            t = None
                        rows.append((pid, hero, k, i, t,
                                     val if isinstance(val, (int, float)) else None))
                    conn.executemany("INSERT INTO player_series VALUES (?,?,?,?,?,?)", rows)
                    n_series += len(rows)
                    continue

            # --- (e) everything else (nested maps, string lists) ---
            conn.execute("INSERT INTO player_json VALUES (?,?,?,?)",
                         (pid, hero, k, flatten(v)))
            n_json += 1

    return len(players), n_series, n_events, n_json


def build_convenience_views(conn):
    """Views that pre-join the two most common filters, so the model writes less SQL."""
    conn.execute("""
        CREATE VIEW IF NOT EXISTS hero_deaths AS
        SELECT c.game_time_s, c.tick, c.target_name AS hero_name,
               c.attacker_name AS killer, c.damage_source_name AS damage_source,
               c.attacker_is_illusion, c.will_reincarnate, p.team AS victim_team,
               p.is_radiant AS victim_is_radiant
        FROM combat_log c
        LEFT JOIN players p ON p.hero_name = c.target_name
        WHERE c.log_type = 'DEATH'
          AND c.target_name LIKE 'npc_dota_hero_%'
          AND c.attacker_name LIKE 'npc_dota_hero_%'
    """)
    conn.execute("""
        CREATE VIEW IF NOT EXISTS hero_purchases AS
        SELECT c.game_time_s, c.tick, c.target_name AS hero_name,
               c.value_name AS item, c.value,
               p.team, p.is_radiant
        FROM combat_log c
        LEFT JOIN players p ON p.hero_name = c.target_name
        WHERE c.log_type = 'PURCHASE'
          AND c.value_name NOT IN ('item_ward_dispenser')
    """)
    conn.execute("""
        CREATE VIEW IF NOT EXISTS ability_casts AS
        SELECT c.game_time_s, c.tick, c.attacker_name AS caster,
               c.inflictor_name AS ability, c.ability_level,
               c.target_name AS target
        FROM combat_log c
        WHERE c.log_type = 'ABILITY'
          AND c.attacker_name LIKE 'npc_dota_hero_%'
    """)
    conn.execute("""
        CREATE VIEW IF NOT EXISTS modifier_applied AS
        SELECT c.game_time_s, c.tick, c.attacker_name AS caster,
               c.inflictor_name AS modifier, c.target_name AS target,
               c.modifier_duration_s, c.aura_modifier
        FROM combat_log c
        WHERE c.log_type = 'MODIFIER_ADD'
    """)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parsed", type=Path, help="gem-dota parsed JSON")
    ap.add_argument("out", nargs="?", type=Path, help="output .db (default: <parsed>.db)")
    ap.add_argument("--info", action="store_true",
                    help="after loading, print the schema and row counts")
    ap.add_argument("--keep-json", action="store_true",
                    help="also create json_cols, a (key) list of every JSON field seen")
    ap.add_argument("--force", action="store_true", help="overwrite an existing .db")
    args = ap.parse_args()

    out = args.out or args.parsed.with_suffix(".db")
    if out.exists() and not args.force:
        sys.exit(f"{out} already exists -- pass --force to rebuild")

    print(f"[read] {args.parsed} ...", file=sys.stderr)
    data = json.loads(args.parsed.read_text(encoding="utf-8"))
    print(f"[read] {args.parsed.stat().st_size / 1e6:.0f} MB loaded", file=sys.stderr)

    if out.exists():
        out.unlink()
    conn = sqlite3.connect(out)
    counts = {}
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-200000")

        counts["meta"] = build_meta(conn, data)
        for key, rows in data.items():
            if key == "players" or not isinstance(rows, list):
                continue
            counts[key] = build_generic_table(conn, key, rows)

        gst = data.get("game_start_tick")
        if gst is not None:
            try:
                backfill_combat_times(conn, data)
            except sqlite3.OperationalError:
                # combat_log absent (rare) -- skip silently
                pass

        players = data.get("players") or []
        if players:
            n, ns, nev, nj = build_player_tables(
                conn, players, data.get("game_start_tick"),
                (data.get("game_clock") or {}).get("pauses"))
            counts["players"] = n
            counts["player_series"] = ns
            counts["player_events"] = nev
            counts["player_json"] = nj

        build_convenience_views(conn)

        if args.keep_json:
            conn.execute("CREATE TABLE IF NOT EXISTS json_cols (source TEXT, field TEXT, "
                         "PRIMARY KEY (source, field)) WITHOUT ROWID")
            for key, rows in data.items():
                if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                    for f in rows[0]:
                        conn.execute("INSERT OR IGNORE INTO json_cols VALUES (?, ?)", (key, f))

        conn.commit()
        conn.execute("ANALYZE")
        conn.commit()
    finally:
        conn.close()

    print(f"[done] {out}  ({out.stat().st_size / 1e6:.0f} MB)", file=sys.stderr)

    if args.info:
        print(f"\n# {out.name}\n")
        conn = sqlite3.connect(out)
        for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
            count = conn.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]
            print(f"## {name}  ({count:,} rows)")
            for _cid, cname, ctype, _nn, _dflt, _pk in conn.execute(
                    f'PRAGMA table_info("{name}")'):
                print(f"   {cname} {ctype or ''}")
            print()
        for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view' ORDER BY name"):
            print(f"## VIEW {name}")
        conn.close()


if __name__ == "__main__":
    main()
