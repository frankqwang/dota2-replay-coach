#!/usr/bin/env python3
"""Extract compact, hero-agnostic coaching facts from a parsed Dota replay JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def clock(seconds: int) -> str:
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def short(name: str | None) -> str:
    return (name or "unknown").replace("npc_dota_hero_", "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parsed", type=Path, required=True)
    ap.add_argument("--hero", required=True, help="hero key, e.g. necrolyte, or a full npc_dota_hero_* name")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--checkpoints", default="5,10,15,20,25,30,35,40", help="comma-separated minute checkpoints")
    ap.add_argument("--pretty", action="store_true", help="indent JSON for human inspection; default is compact for lower token use")
    args = ap.parse_args()
    data = json.loads(args.parsed.read_text())
    wanted = args.hero if args.hero.startswith("npc_dota_hero_") else "npc_dota_hero_" + args.hero
    player_index, player = next((i, p) for i, p in enumerate(data["players"]) if p["hero_name"] == wanted)
    combat = [e for e in data.get("combat_log", []) if e.get("game_time_s") is not None]
    deaths = [e for e in combat if e.get("log_type") == "DEATH" and e.get("target_name") == wanted]
    damage = {
        short(hero): value for hero, value in player.get("damage_taken", {}).items()
        if hero.startswith("npc_dota_hero_")
    }
    checkpoints = []
    checkpoint_minutes = [int(x.strip()) for x in args.checkpoints.split(",") if x.strip()]
    for minute in checkpoint_minutes:
        if minute >= len(player.get("net_worth_t_min", [])):
            continue
        checkpoints.append({
            "minute": minute,
            "net_worth": player["net_worth_t_min"][minute],
            "last_hits": player.get("lh_t_min", [None] * (minute + 1))[minute],
        })
    teamfights = []
    for tf in data.get("opendota_teamfights", data.get("teamfights", [])):
        participants = tf.get("players", [])
        if len(participants) < 10:
            continue
        # OpenDota ordering is Radiant slots first, Dire slots second.
        radiant_deaths = sum(x.get("deaths", 0) for x in participants[:5])
        dire_deaths = sum(x.get("deaths", 0) for x in participants[5:10])
        # Parsed player order and OpenDota teamfight order both follow the ten
        # player slots; using the matched index avoids Necro-/role-specific assumptions.
        mine = participants[player_index] if player_index < len(participants) else {}
        teamfights.append({
            "window": f"{clock(tf['start'])}-{clock(tf['end'])}",
            "radiant_kills": dire_deaths,
            "dire_kills": radiant_deaths,
            "my_deaths": mine.get("deaths", 0),
            "my_kills": sum(mine.get("killed", {}).values()),
        })
    real_deaths = [e for e in deaths if not e.get("will_reincarnate")]
    death_context = []
    for death in real_deaths:
        when = death["game_time_s"]
        window = [e for e in combat if when - 6 <= e["game_time_s"] <= when]
        incoming = [e for e in window if e.get("log_type") == "DAMAGE" and e.get("target_name") == wanted]
        actions = [e.get("inflictor_name") or e.get("value_name") for e in window if e.get("attacker_name") == wanted and e.get("log_type") in {"ABILITY", "ITEM"}]
        death_context.append({
            "time": clock(when),
            "killer": short(death.get("attacker_name")),
            "incoming_damage": sum(e.get("value", 0) for e in incoming),
            "top_damage_sources": sorted(((short(e.get("damage_source_name") or e.get("attacker_name")), e.get("value", 0)) for e in incoming), key=lambda x: -x[1])[:3],
            "my_actions_last_6s": actions,
        })
    # Anti-invisibility purchases per player: needed to judge invis-item value
    # (dust/sentry/gem counts; item_ward_dispenser is a merge artifact, not a purchase).
    detection_items = {"item_dust": "dust", "item_ward_sentry": "sentry", "item_gem": "gem"}
    detection = {short(p.get("hero_name")): {"dust": 0, "sentry": 0, "gem": 0} for p in data.get("players", [])}
    for e in data.get("combat_log", []):
        if e.get("log_type") != "PURCHASE":
            continue
        key = detection_items.get(e.get("value_name") or "")
        if key:
            detection[short(e.get("target_name"))][key] += 1
    ability_uses = player.get("ability_uses", {})
    item_uses = player.get("item_uses", {})
    result = {
        "match_id": data.get("match_id"),
        "hero": short(wanted),
        "duration": data.get("duration"),
        "duration_label": clock(data["duration"]) if data.get("duration") is not None else None,
        "draft_available": bool(data.get("draft")),
        "lineup": [{"side": "radiant" if p.get("is_radiant") else "dire", "hero": short(p.get("hero_name")), "lane_role": p.get("lane_role"), "kda": [p.get("kills"), p.get("deaths"), p.get("assists")], "net_worth": p.get("net_worth")} for p in data.get("players", [])],
        "player_summary": {"kills": player.get("kills"), "deaths": player.get("deaths"), "assists": player.get("assists"), "hero_damage": player.get("hero_damage"), "tower_damage": player.get("tower_damage"), "net_worth": player.get("net_worth"), "last_hits": player.get("last_hits"), "lane_efficiency_pct": player.get("lane_efficiency_pct"), "teamfight_participation": player.get("teamfight_participation"), "obs_placed": player.get("obs_placed"), "sen_placed": player.get("sen_placed")},
        "networth_checkpoints": checkpoints,
        "gold_advantage": data.get("radiant_gold_adv", []),
        "damage_taken_by_enemy": dict(sorted(damage.items(), key=lambda x: -x[1])),
        "ability_uses": ability_uses,
        "item_uses": item_uses,
        "purchases": player.get("purchase_log", []),
        "detection_purchases_by_player": detection,
        "deaths": death_context,
        "teamfights": teamfights,
        "objectives": data.get("objectives", []),
        "wards": data.get("wards", []),
        "smokes": data.get("smoke_events", []),
        "data_quality": {"player_count": len(data.get("players", [])), "combat_event_count": len(combat), "scoreboard_deaths_match_events": len(real_deaths) == player.get("deaths"), "reincarnation_pseudo_deaths_ignored": len(deaths) - len(real_deaths)},
    }
    if args.pretty:
        payload = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    args.out.write_text(payload + "\n")


if __name__ == "__main__":
    main()

