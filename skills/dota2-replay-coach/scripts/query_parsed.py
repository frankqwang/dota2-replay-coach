#!/usr/bin/env python
"""query_parsed.py -- targeted queries against a parsed replay JSON.

Keeps a 100 MB+ parsed JSON on disk instead of in the conversation.

  python query_parsed.py <parsed.json> <subcommand> ...

Subcommands:
  players                     ten-player overview (hero / side / lane_role / KDA / economy)
  kills   --hero <hero_key>   that hero's kill and death timeline (creeps filtered out)
  items   --hero <hero_key>   purchase timeline (value_name + game_time_s, None skipped)
  nw      --min 5             net-worth curve per player, sampled every --min minutes
"""
import argparse
import json
import sys


def fmt_t(t):
    return f"{int(t)//60}:{int(t)%60:02d}"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_hero(name):
    return isinstance(name, str) and name.startswith("npc_dota_hero_")


def short(name):
    return name.replace("npc_dota_hero_", "") if isinstance(name, str) else name


def find_player(d, hero_key):
    for p in d["players"]:
        if p.get("hero_name") == f"npc_dota_hero_{hero_key}":
            return p
    names = ", ".join(short(p["hero_name"]) for p in d["players"])
    sys.exit(f"找不到英雄 {hero_key}，可选：{names}")


def cmd_players(d):
    print(f"match_id={d.get('match_id')} duration={fmt_t(d.get('duration', 0))}")
    print(f"{'hero':18s} side  lane  kda      LH  gpm  NW      laneGoldAdv laneXpAdv")
    for p in d["players"]:
        side = "R" if p.get("is_radiant") else "D"
        print(f"{short(p['hero_name']):18s} {side}    {str(p.get('lane_role')):4s} "
              f"{p['kills']}/{p['deaths']}/{p['assists']:2d}  {str(p.get('last_hits')):3s} "
              f"{str(p.get('gold_per_min')):4s} {str(p.get('net_worth')):6s} "
              f"{str(p.get('lane_gold_adv')):11s} {str(p.get('lane_xp_adv'))}")


def cmd_kills(d, hero_key):
    me = f"npc_dota_hero_{hero_key}"
    kills, deaths = [], []
    for e in d.get("combat_log", []):
        if e.get("log_type") != "DEATH" or not e.get("game_time_s"):
            continue
        atk, tgt = e.get("attacker_name"), e.get("target_name")
        if atk == me and is_hero(tgt):
            kills.append((int(e["game_time_s"]), short(tgt)))
        if tgt == me and is_hero(atk):
            deaths.append((int(e["game_time_s"]), short(atk)))
    for t, k in sorted(kills):
        print(f"{fmt_t(t)} 击杀 {k}")
    print("---")
    for t, k in sorted(deaths):
        print(f"{fmt_t(t)} 死于 {k}")


def cmd_items(d, hero_key):
    p = find_player(d, hero_key)
    for e in p.get("purchase_log", []):
        t = e.get("game_time_s")
        if t is None:
            continue
        print(f"{fmt_t(t)} {e.get('value_name')}")


def cmd_nw(d, step):
    for p in d["players"]:
        nw = p.get("net_worth_t_min") or []
        pts = ", ".join(f"{nw[i]}" for i in range(0, len(nw), step))
        print(f"{short(p['hero_name']):18s} {pts}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("parsed")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("players")
    k = sub.add_parser("kills"); k.add_argument("--hero", required=True)
    i = sub.add_parser("items"); i.add_argument("--hero", required=True)
    n = sub.add_parser("nw"); n.add_argument("--min", type=int, default=5)
    a = ap.parse_args()

    d = load(a.parsed)
    if a.cmd == "players":
        cmd_players(d)
    elif a.cmd == "kills":
        cmd_kills(d, a.hero)
    elif a.cmd == "items":
        cmd_items(d, a.hero)
    elif a.cmd == "nw":
        cmd_nw(d, a.min)


if __name__ == "__main__":
    main()
