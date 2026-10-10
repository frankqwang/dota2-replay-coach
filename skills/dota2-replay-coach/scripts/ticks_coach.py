#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ticks_coach.py -- hero-agnostic analysis of the per-tick coordinate CSV.

The CSV comes from the bundled clarity parser (scripts/clarity/ReplayDump.java):
  gametime,tick,index,dtname,team,heroid,x,y,hp,maxhp,level,lifestate

Everything match-specific is derived from the file, never hard-coded:
  * hero names      <- the `dtname` column (CDOTA_Unit_Hero_Legion_Commander -> legion_commander)
  * ally grouping   <- the `team` column
  * playable body   <- the smallest `index` per hero per team (illusions share the class)
  * clock offset    <- solved by aligning the CSV's lifesteate transitions with death times
                       you supply from the scoreboard / OpenDota (see --death-times)

Two time bases are in play and must not be confused:
  raw   = the CSV `gametime` column, which is tick/30 (NOT the in-game clock)
  real  = raw - offset, i.e. the in-game clock

Usage
-----
  python ticks_coach.py <csv> [--me <hero>] [--offset 229]
                              [--death-times 87,720,1005,...]
                              [--lane-minutes 8] [--sample-every 30]
                              [--list-heroes]

  # let the script solve the offset for you:
  python ticks_coach.py ticks_9036564967.csv --me legion_commander \
      --death-times 87,721,1005,1512,1922,2093,2612,3302

If --me is omitted, the hero with the most samples that is not a creep is used and
reported. If --offset is omitted and --death-times is given, the offset is solved and
verified (all death moments must land within --tolerance seconds; otherwise the script
refuses to print derived numbers rather than printing lies).
"""
from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from collections import defaultdict

# A hero entity's DT class name looks like CDOTA_Unit_Hero_Legion_Commander.
HERO_PREFIX = "CDOTA_Unit_Hero_"

# Distance reference points, in game units (map is roughly 0-32768 on each axis).
ATTACK_RANGE = 600
TOWER_RANGE = 700
XP_RANGE = 1300
DISCONNECTED = 2000  # "the team is not here" threshold


def prettify(hero_key: str) -> str:
    """legion_commander -> Legion Commander. Keeps the raw key usable and readable."""
    return " ".join(part.capitalize() for part in hero_key.split("_") if part)


def fmt(seconds: float) -> str:
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    return f"{sign}{int(seconds) // 60}:{int(seconds) % 60:02d}"


def load(csv_path: str):
    """Return (samples, heroes, teams, samples_per_hero).

    samples: {raw_time: {index: (x, y, hp, level, lifesteate)}}
    heroes:  {index: hero_key}
    teams:   {index: team}
    """
    samples: dict[float, dict[int, tuple]] = defaultdict(dict)
    heroes: dict[int, str] = {}
    teams: dict[int, int] = {}
    counts: dict[int, int] = defaultdict(int)
    try:
        fh = open(csv_path, encoding="utf-8", newline="")
    except OSError as exc:
        sys.exit(f"cannot open {csv_path}: {exc}")
    with fh:
        for row in csv.DictReader(fh):
            try:
                idx = int(row["index"])
            except (KeyError, ValueError):
                continue
            dtname = row.get("dtname") or ""
            if not dtname.startswith(HERO_PREFIX):
                continue
            key = dtname[len(HERO_PREFIX):].lower()
            heroes.setdefault(idx, key)
            try:
                teams[idx] = int(row["team"])
            except (KeyError, ValueError):
                teams[idx] = 0
            try:
                t = round(float(row["gametime"]), 1)
                samples[t][idx] = (
                    float(row["x"]), float(row["y"]),
                    int(row["hp"]), int(row["level"]), int(row["lifestate"]),
                )
            except (KeyError, ValueError):
                continue
            counts[idx] += 1
    if not heroes:
        sys.exit(f"{csv_path} has no hero rows — is this a ReplayDump CSV? "
                 f"(expected a `dtname` column with CDOTA_Unit_Hero_* values)")
    return samples, heroes, teams, counts


def pick_bodies(heroes, teams, counts):
    """Collapse illusion/clone entities: keep the smallest index per (team, hero)."""
    bodies: dict[tuple, int] = {}
    for idx, key in heroes.items():
        ident = (teams.get(idx, 0), key)
        if ident not in bodies or idx < bodies[ident]:
            bodies[ident] = idx
    return bodies


def resolve_me(heroes, counts, given: str | None):
    """Find the player's entity index. Never assume a hero or a role."""
    if given:
        want = given.lower().replace("npc_dota_hero_", "").replace(" ", "_")
        candidates = [i for i, k in heroes.items() if k == want or k.startswith(want)]
        if not candidates:
            available = ", ".join(sorted({k for k in heroes.values()}))
            sys.exit(f"hero '{given}' not found in this CSV. Available: {available}")
        # The real body is the smallest index among the matches.
        return min(candidates)
    # No hint: use the entity that exists for the longest, which is a real body
    # rather than a short-lived illusion.
    return max(counts, key=lambda i: counts[i])


def death_windows(series, gap: float = 5.0):
    """Detect death windows from lifesteate transitions.

    Respawns can be immediate in a lost fight; merge windows starting closer than `gap`
    seconds after the previous one ended.
    Returns a list of (start, end) in raw CSV time.
    """
    alive_flags = [(t, p[4] == 0) for t, p in series]
    windows = []
    start = None
    prev_alive = True
    for t, alive in alive_flags:
        if prev_alive and not alive:
            if start is None:
                start = t
        elif not prev_alive and alive and start is not None:
            if windows and start - windows[-1][1] <= gap:
                windows[-1] = (windows[-1][0], t)
            else:
                windows.append((start, t))
            start = None
        prev_alive = alive
    if start is not None:
        windows.append((start, alive_flags[-1][0]))
    return windows


def solve_offset(windows, death_times, tolerance=1.5):
    """Solve raw_time - offset = real_time using the scoreboard death times.

    Uses the median delta rather than the mean so a single mistyped death time cannot
    drag the offset. Windows that disagree with the median by more than `tolerance`
    are reported as outliers (usually a mis-supplied time, or a death that happened
    between two samples).

    Returns (offset, report_lines, ok). `ok` is False only when too few deaths agree
    to trust the offset at all.
    """
    report = []
    if not death_times:
        return None, ["[offset] no --death-times given; timings below are in RAW csv time"], False
    if len(death_times) != len(windows):
        report.append(
            f"[offset] note: {len(windows)} death windows in the CSV vs {len(death_times)} "
            f"times supplied — pairing the first {min(len(windows), len(death_times))}"
        )
    pairs = list(zip(windows, death_times))
    if not pairs:
        return None, report + ["[offset] no death windows detected"], False

    deltas = sorted(w[0] - d for (w, d) in pairs)
    mid = len(deltas) // 2
    offset = round(deltas[mid] if len(deltas) % 2 else (deltas[mid - 1] + deltas[mid]) / 2, 1)

    agree = 0
    for (w, d) in pairs:
        delta = w[0] - d
        ok_pair = abs(delta - offset) <= tolerance
        agree += ok_pair
        report.append(
            f"[offset] csv {fmt(w[0])} -> real {fmt(w[0] - offset)} (supplied {fmt(d)}) "
            f"delta={delta:.1f}s" + ("" if ok_pair else "  <-- OUTLIER (check this time)")
        )

    # Require a clear majority to agree before trusting the clock.
    needed = max(2, (len(pairs) + 1) // 2)
    trusted = agree >= needed
    report.insert(0, f"[offset] solved = {offset}s via median  "
                     f"({agree}/{len(pairs)} deaths agree within {tolerance}s)")
    if not trusted:
        report.append(f"[offset] ✗ only {agree}/{len(pairs)} agree (need {needed}) — "
                      f"offset NOT trustworthy, derived timings suppressed")
    elif agree < len(pairs):
        report.append("[offset] ✓ offset accepted; outliers above are excluded from the solve")
    return offset, report, trusted


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="per-tick CSV produced by ReplayDump.java")
    ap.add_argument("--me", help="hero key of the player, e.g. legion_commander (default: the longest-lived hero)")
    ap.add_argument("--offset", type=float, help="raw = real + offset (skip solving when given)")
    ap.add_argument("--death-times", help="comma-separated REAL death times from the scoreboard, e.g. 87,721,1005")
    ap.add_argument("--tolerance", type=float, default=1.5, help="max residual seconds when solving the offset")
    ap.add_argument("--lane-minutes", type=float, default=8.0, help="how long to treat as the laning phase")
    ap.add_argument("--sample-every", type=float, default=30.0, help="seconds between the lane-timeline rows")
    ap.add_argument("--trace-seconds", type=float, default=90.0, help="how far before a death to trace movement")
    ap.add_argument("--list-heroes", action="store_true", help="print the heroes found in the CSV and exit")
    args = ap.parse_args()

    samples, heroes, teams, counts = load(args.csv)
    if not samples:
        sys.exit(f"no hero rows found in {args.csv} — is this a ReplayDump CSV?")

    bodies = pick_bodies(heroes, teams, counts)
    times = sorted(samples)
    raw_lo, raw_hi = times[0], times[-1]

    if args.list_heroes:
        print(f"CSV spans raw {fmt(raw_lo)}-{fmt(raw_hi)} ({len(times)} sample points)")
        for (team, key), idx in sorted(bodies.items()):
            side = "radiant" if team == 2 else ("dire" if team == 3 else f"team{team}")
            print(f"  {prettify(key):24s} idx={idx:<6d} {side:8s} samples={counts[idx]}")
        return

    me = resolve_me(heroes, {(i): c for i, c in counts.items() if i in bodies.values()}, args.me)
    me_key = heroes.get(me, "unknown")
    me_team = teams.get(me, 0)
    allies = {idx for (team, _), idx in bodies.items() if team == me_team}
    enemies = {idx for (team, _), idx in bodies.items() if team != me_team}
    name_of = {idx: prettify(heroes[idx]) for idx in heroes}

    print(f"match file : {args.csv}")
    print(f"player     : {name_of.get(me, me_key)}  (idx={me}, "
          f"{'radiant' if me_team == 2 else 'dire' if me_team == 3 else me_team})")
    print(f"csv span   : raw {fmt(raw_lo)}-{fmt(raw_hi)}  ({len(times)} samples)")

    series = [(t, samples[t][me]) for t in times if me in samples[t]]
    if not series:
        sys.exit(f"hero idx={me} has no samples")

    windows = death_windows(series)
    death_times = None
    if args.death_times:
        try:
            death_times = [float(x) for x in args.death_times.split(",") if x.strip()]
        except ValueError:
            sys.exit("--death-times must be comma-separated numbers, e.g. 87,721,1005")

    print()
    print("=== clock calibration ===")
    if args.offset is not None:
        offset, ok = args.offset, True
        print(f"[offset] supplied = {offset}s (not verified — pass --death-times to verify)")
    else:
        offset, report, ok = solve_offset(windows, death_times, args.tolerance)
        for line in report:
            print(line)
        if offset is None:
            # Fall back to raw time and label everything as raw.
            offset, ok = 0.0, False

    def clock(raw):
        return fmt(raw - offset) + ("" if ok else " raw")

    print(f"csv clock  : raw {fmt(raw_lo)}-{fmt(raw_hi)}  ->  real {clock(raw_lo)}-{clock(raw_hi)}")

    # ---------------- lane phase ----------------
    lane_end = offset + args.lane_minutes * 60
    print()
    print(f"=== lane phase (real 0:00-{fmt(args.lane_minutes * 60)}) — nearest enemy / ally ===")
    probe = offset
    while probe <= min(lane_end, raw_hi):
        key = min(times, key=lambda x: abs(x - probe))
        snap = samples[key]
        mep = snap.get(me)
        if mep:
            near_e = min(((i, dist(mep, p)) for i, p in snap.items() if i in enemies),
                         key=lambda x: x[1], default=None)
            near_a = min(((i, dist(mep, p)) for i, p in snap.items() if i in allies and i != me),
                         key=lambda x: x[1], default=None)
            print(f"  {clock(key)}  pos=({mep[0]:6.0f},{mep[1]:6.0f}) hp={mep[2]:4d} | "
                  f"enemy {name_of.get(near_e[0], '-'):22s} {near_e[1]:6.0f} | "
                  f"ally {name_of.get(near_a[0], '-'):22s} {near_a[1]:6.0f}"
                  if near_e and near_a else f"  {clock(key)}  (incomplete snapshot)")
        probe += args.sample_every

    # ---------------- deaths ----------------
    print()
    print("=== deaths — who was actually nearby ===")
    if not windows:
        print("  (no lifesteate transition found)")
    for st, en in windows:
        key = min(times, key=lambda x: abs(x - st))
        snap = samples[key]
        mep = snap.get(me)
        if not mep:
            continue
        print(f"\n  death @ real {clock(st)} (csv {fmt(st)})  pos=({mep[0]:6.0f},{mep[1]:6.0f}) "
              f"hp={mep[2]} level={mep[3]}")
        near_e = sorted(((i, dist(mep, p), p) for i, p in snap.items() if i in enemies), key=lambda x: x[1])[:3]
        near_a = sorted(((i, dist(mep, p), p) for i, p in snap.items() if i in allies and i != me),
                        key=lambda x: x[1])[:3]
        for i, dd, p in near_e:
            print(f"      enemy {name_of.get(i, i):22s} d={dd:6.0f}  hp={p[2]}")
        for i, dd, p in near_a:
            print(f"      ally  {name_of.get(i, i):22s} d={dd:6.0f}  hp={p[2]}")
        if near_a:
            nearest = near_a[0][1]
            verdict = ("TEAM PRESENT (normal fight)" if nearest <= TOWER_RANGE
                       else "ADJACENT (delayed follow-up)" if nearest <= DISCONNECTED
                       else "ALONE (team disconnected)")
            print(f"      => nearest ally {nearest:.0f}u -> {verdict}"
                  f"   [attack range ~{ATTACK_RANGE}, tower ~{TOWER_RANGE}, disconnected >{DISCONNECTED}]")

    # ---------------- approach paths ----------------
    print()
    print(f"=== movement in the {args.trace_seconds:.0f}s before each death ===")
    for st, en in windows:
        seg = [(t, samples[t][me]) for t in times if st - args.trace_seconds <= t <= st + 5 and me in samples[t]]
        if not seg:
            continue
        step = max(1, len(seg) // 8)
        path = " -> ".join(f"{clock(t)}:({p[0]:.0f},{p[1]:.0f})" for t, p in seg[::step])
        print(f"  [{clock(st)}] {path}")

    print()
    print("unit reference: attack range ~600, tower ~700, XP range ~1300, "
          f"'team disconnected' >{DISCONNECTED}")


if __name__ == "__main__":
    main()
