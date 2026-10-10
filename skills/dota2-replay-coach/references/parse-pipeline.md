# Replay parsing pipeline

Turn a **match ID** or a **`.dem` file** into data the coaching layer can use. There is no single
"the parser" — pick a path by what the question needs.

## Which path? (decision table)

| Path | Output | Per-tick coordinates? | Cost / time | Use when |
|---|---|---|---|---|
| **A. OpenDota API** | OpenDota match JSON (per-minute arrays, teamfights, purchase log, `lane_pos` grid) | No — `lane_pos` is ~5 s-aggregated and loses time | free, no download | quick pass; or when local parsers can't read the replay build |
| **B. gem-dota** | full event JSON (every game event: combat log, purchases, ability casts) | has `position_log`, but tick-based with offsets | ~2–3 min for a 40-min game | deep event forensics (duel ledgers, exact cast order, damage attribution) |
| **C. clarity** | **per-tick hero CSV** (x, y, hp, level, every ~0.5 s × 10 heroes) | **Yes — true per-tick** | ~2 s parse after a one-time ~20 s build | lane positioning, split-push, "how far was my nearest ally when I died" |

**Rule of thumb:** B answers *what happened* (events). C answers *where everyone was* (geometry).
They are complementary — run B for the event story and C when a positioning/lane/split-push claim
needs proof. A and C/B disagree only in resolution, not in facts; when they agree (they should),
you can state the finding with confidence.

---

## Step 0 — resolve the match

If the user gives a fuzzy reference ("my last game"), list their recent matches rather than asking:

```
GET https://api.opendota.com/api/players/<account_id>/recentMatches   # last 20: hero/KDA/GPM/result
GET https://api.opendota.com/api/matches/<match_id>                   # 10-player detail
GET https://api.opendota.com/api/constants/items                      # item id -> name
GET https://www.dota2.com/datafeed/herolist?language=schinese         # hero id -> localized name
```

Cache hero-id→Chinese-name and item-id→name maps once in the workspace; reuse across games.

## Step 1 — get the `.dem`

**Prefer a local copy already on disk.** The Dota client keeps every downloaded replay under
`<steam-lib>/steamapps/common/dota 2 beta/game/dota/replays/<match_id>.dem` (uncompressed,
`PBDEMS2`). Steam library roots are listed in `libraryfolders.vdf` — check **all** libraries, not
just `C:`.

Otherwise fetch from Valve CDN using the `replay_url` in the OpenDota match JSON:

```
python scripts/fetch_replay.py <match_id> <out_dir>
```

`fetch_replay.py` does: OpenDota metadata → `replay_url` (cache hit, else `POST /api/request/{id}`
and poll) → download → detect compression **by magic bytes** → decompress → verify `PBDEMS2`.
It skips work if `<match_id>.dem` already exists.

> **The `.dem.bz2` extension lies.** Valve now serves **zstd**-compressed replays under a `.bz2`
> name. Detect the format by magic bytes (`28 b5 2f fd` = zstd, `BZh` = bzip2), never by extension.

---

## Path A — OpenDota API (no local parser needed)

`POST https://api.opendota.com/api/request/{match_id}` triggers a server-side parse; poll
`GET https://api.opendota.com/api/matches/{match_id}` until a `version` field appears. Then read it
directly. This is the only path that works when the replay build is newer than every local parser.
Its ceiling: **no sub-second positions**, so it cannot answer "where exactly was I standing".

## Path B — gem-dota (full event JSON)

1. Install into an isolated venv: `pip install gem-dota` (verify `python -m gem --help`).
2. Parse once, to JSON, in the background (a 40-min game ≈ 1m40s):

```
python -m gem parse <replay.dem> --format json --output <out_dir>/parsed_<id>.json --no-banner
```

3. Verify the output is real before trusting it: `players` non-empty, `combat_log` large,
   `game_end_tick` near the expected end. A few KB of JSON means parsing aborted.
4. Query it with `scripts/query_parsed.py` (`players` / `kills` / `items` / `nw`) and extract the
   fact bundle with `scripts/extract_match_facts.py`.

> **Build-compatibility warning.** Source 2 replays embed the entity schema, and Valve changes it
> between client builds. A parser that works on build `N` can hard-fail on build `N+1` with a
> `Replay stream ended early … BufferReadError` at a fixed early tick, producing an empty shell.
> Observed instance: a Sept build parsed fine; after a client update the same parser died at
> tick ~4500 on *every* new replay while old replays still parsed. **Diagnose by parsing a known-good
> older replay with the same tool** — if the old one works and the new one doesn't, it is a
> build/protocol mismatch, not a corrupt download. Fix = update the parser, or use Path A/C.

## Path C — clarity (per-tick coordinates) — build once, then ~2 s per game

This is the only bundled path that yields true per-tick positions. It is a Java library (the same
one OpenDota's own parser uses), so it tends to be the first to support new builds.

### C.1 Build once

`scripts/clarity/` ships a minimal Maven project (`pom.xml` + `ReplayDump.java`).

```
cd scripts/clarity
mvn -s <settings.xml> -B -DskipTests package      # produces target/dota-lc-parse.jar (fat jar)
```

Dependencies come from Maven Central: `com.skadistats:clarity:5.0.1` +
`com.skadistats:clarity-protobuf:7.x`. See [agent-adapters.md](agent-adapters.md) §4 for the
"mirror missing a jar → fetch from `repo1.maven.org`" workaround.

### C.2 Run

```
java -Xmx3g -jar target/dota-lc-parse.jar <replay.dem> <out.csv> [sampleEveryTicks]
```

`sampleEveryTicks` defaults to 15 (~0.5 s). Output columns:
`gametime,tick,index,dtname,team,heroid,x,y,hp,maxhp,level,lifestate`.

### C.3 Hero identity & coordinates

- Hero entity DT class names are `CDOTA_Unit_Hero_Legion_Commander` style — **note the underscores**
  (`Legion_Commander`, not `LegionCommander`). Capture every entity whose class starts with
  `CDOTA_Unit_Hero_`.
- Position is `CBodyComponent.m_cellX × 128 + CBodyComponent.m_vecX` (same for Y/Z). A cell is 128
  units. Attack range ≈ 600 units, tower ≈ 700, map ≈ 0–32768.
- The same hero may appear as several entities (illusions/clones). Identify the real body by the
  smallest/first `index` per hero, or by matching the team.

### C.4 Calibrate the clock (required)

`gametime` is exported as raw `tick/30`, **not** the in-game clock (`m_pGameRules.m_fGameTime` is
not readable through clarity on current builds). Align it against known events: find the hero's death
moments in the CSV and match them to the scoreboard/OpenDota death times. The constant offset `k`
satisfies `real_seconds = csv_gametime − k`.

`scripts/ticks_coach.py` automates this and is **hero-agnostic** — no hero index, roster, or offset
is hard-coded:

```
python scripts/ticks_coach.py <out.csv> --me legion_commander --death-times 87,1085,1972,...
python scripts/ticks_coach.py <out.csv> --list-heroes        # what is in this CSV?
python scripts/ticks_coach.py <out.csv> --me <hero> --offset 229   # skip solving
```

It derives hero names from `dtname`, sides from `team`, collapses illusion entities to the smallest
`index` per hero, solves `k` by **median** (so one bad death time cannot skew the clock), reports
each window's residual, and prints an explicit "team present / adjacent / alone" verdict per death
from the nearest-ally distance. If a clear majority of deaths fail to align, it suppresses the
derived timings rather than printing numbers it cannot stand behind.

---

## Common traps (all paths)

- Do not paste the 50–80 MB parsed JSON into the model — always go through `extract_match_facts.py`.
- Time source: use each event's own timestamp. Do **not** linearly convert ticks → seconds; demos
  with pauses are non-linear (a real observed case drifted by ~20 min mid-game).
- `game_mode 22` (all-pick) has **no draft data** — write the BP section conditionally, don't invent
  pick order.
- Chinese-team clusters may serve replays from `replay<cluster>.dota2.com.cn`; Valve originals
  occasionally 502 — just retry.
- See [data-traps.md](data-traps.md) for field-level traps in the parsed JSON.
