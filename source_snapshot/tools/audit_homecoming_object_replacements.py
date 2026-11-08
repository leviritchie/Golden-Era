#!/usr/bin/env python3
"""Audit HoMM3->Olden replacement rules for functional description mismatches."""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CORE_CATALOG_PATH = REPO / "artifacts/campaign_port_poc/olden_entity_catalog/olden_core_map_valid_entity_catalog.json"
CHECKPOINT_PATH = REPO / "experiments/campaign_port_poc/homecoming_mapping_review_checkpoint.json"
POC_DIR = REPO / "experiments/campaign_port_poc"


def load_module(path: Path, name: str):
    if str(POC_DIR) not in sys.path:
        sys.path.insert(0, str(POC_DIR))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load_english_tokens(core_zip: str) -> dict[str, str]:
    tokens: dict[str, str] = {}
    with zipfile.ZipFile(core_zip) as archive:
        for member in ("Lang/english/texts/mapObjects.json", "Lang/english/texts/artifacts.json"):
            payload = json.loads(archive.read(member).decode("utf-8-sig"))
            for row in payload.get("tokens", []):
                if isinstance(row.get("sid"), str) and isinstance(row.get("text"), str):
                    tokens[row["sid"]] = row["text"]
    return tokens


def olden_desc(sid: str, core_catalog: dict, english: dict[str, str]) -> str:
    for row in core_catalog.get("mapObjects", []):
        if row.get("id") != sid:
            continue
        token = row.get("description")
        if isinstance(token, str) and token in english:
            return english[token]
        fallback = f"{sid}_description"
        return english.get(fallback, "")
    return ""


def build_entries(mod, menu, core_catalog: dict, english: dict[str, str]) -> list[dict]:
    entries: list[dict] = []
    h3_desc_by_id = dict(menu.SOURCE_FUNCTION_BY_TEMPLATE_ID)
    for row in menu.HOMM3_BUILDING_CATALOG_EXTENSION:
        if isinstance(row.get("templateObjectId"), int):
            h3_desc_by_id[row["templateObjectId"]] = {
                "sourceName": row["sourceName"],
                "sourceFunction": row["sourceFunction"],
            }

    for tid, (sid, rule) in mod.EXACT_TEMPLATE_RULES.items():
        h3 = h3_desc_by_id.get(tid, {})
        entries.append(
            {
                "kind": "exact_template",
                "h3_id": tid,
                "h3_name": h3.get("sourceName", f"H3 template {tid}"),
                "h3_desc": h3.get("sourceFunction", ""),
                "olden_sid": sid,
                "olden_desc": olden_desc(sid, core_catalog, english),
                "rule": rule,
            }
        )

    for tid, rule in mod.HOMM3_SOURCE_BUILDING_DESCRIPTIONS.items():
        entries.append(
            {
                "kind": "minilm_building",
                "h3_id": tid,
                "h3_name": rule["sourceName"],
                "h3_desc": rule["sourceDescription"],
                "olden_sid": rule["expectedReplacementSid"],
                "olden_desc": olden_desc(rule["expectedReplacementSid"], core_catalog, english),
                "rule": rule["ruleName"],
            }
        )

    dwelling_names = {
        "AVGpike0.def": ("Guardhouse", "Pikeman"),
        "AVGcros0.def": ("Archers' Tower", "Archer"),
        "AVGgrff0.def": ("Griffin Tower", "Griffin"),
        "AVGswor0.def": ("Barracks", "Swordsman"),
        "AVGmonk0.def": ("Monastery", "Monk"),
    }
    for anim, (sid, rule) in mod.CREATURE_GENERATOR_ANIMATION_EXACT_MAP.items():
        name, unit = dwelling_names[anim]
        entries.append(
            {
                "kind": "dwelling",
                "h3_name": f"Castle {name}",
                "h3_desc": f"An external Castle dwelling that provides {unit} recruits.",
                "olden_sid": sid,
                "olden_desc": olden_desc(sid, core_catalog, english),
                "rule": rule,
            }
        )

    seen_mines: set[str] = set()
    for anim, sid in mod.MINE_ANIMATION_MAP.items():
        if sid in seen_mines:
            continue
        seen_mines.add(sid)
        entries.append(
            {
                "kind": "mine",
                "h3_name": f"Mine ({sid})",
                "h3_desc": "Places a capturable resource mine that provides recurring income to its owner.",
                "olden_sid": sid,
                "olden_desc": olden_desc(sid, core_catalog, english),
                "rule": f"mine_animation_token_{anim}",
            }
        )
    for anim, sid in mod.MINE_ANIMATION_EXACT_MAP.items():
        if sid in seen_mines:
            continue
        seen_mines.add(sid)
        entries.append(
            {
                "kind": "mine",
                "h3_name": f"Mine ({anim})",
                "h3_desc": "Places a capturable resource mine that provides recurring income to its owner.",
                "olden_sid": sid,
                "olden_desc": olden_desc(sid, core_catalog, english),
                "rule": f"mine_exact_{anim}",
            }
        )

    res_seen: set[str] = set()
    for anim, sid in mod.RESOURCE_ANIMATION_MAP.items():
        if sid in res_seen:
            continue
        res_seen.add(sid)
        entries.append(
            {
                "kind": "resource",
                "h3_name": f"Resource pile ({anim})",
                "h3_desc": "Places a resource pickup that grants map resources when collected.",
                "olden_sid": sid,
                "olden_desc": olden_desc(sid, core_catalog, english),
                "rule": f"resource_{anim}",
            }
        )

    heuristics = [
        ("Town (Castle)", "Places a capturable town with faction, ownership, garrison, buildings, and campaign objective state.", "homm3_castle_city", "town_animation_castle"),
        ("Town (Dungeon)", "Places a capturable town with faction, ownership, garrison, buildings, and campaign objective state.", "homm3_dungeon_city", "town_animation_dungeon"),
        ("Cave / Subterranean Gate", "Moves or connects the visiting hero through an adventure-map travel object such as a cave entrance or whirlpool.", "portal_1", "cave_to_portal"),
        ("Whirlpool", "Moves or connects the visiting hero through an adventure-map travel object such as a cave entrance or whirlpool.", "portal_magic", "whirlpool_to_magic_portal"),
        ("Boat", "Places a water-travel object; Olden compatibility depends on map water and travel support.", "homm3_boat", "boat_to_homm3_boat"),
        ("Scholar", "Grants the visiting hero a knowledge, skill, spell, or experience-style reward depending on source payload.", "wise_owl", "scholar_to_wise_owl"),
        ("Prison", "Places a hero-related map object, either a hero entry or a prison-style rescue object.", "prison", "prison_visual"),
        ("Hero placeholder", "Places a hero-related map object, either a hero entry or a prison-style rescue object.", "hero-spawner", "hero_to_hero_spawner"),
        ("Map Event", "Runs a scripted map event when its trigger conditions are met.", "fx_quest_mark_gold_01", "event_visible_marker"),
        ("Sign", "Shows map-authored text when visited or inspected.", "grass_1", "sign_to_pathable_scenery"),
        ("Monster stack", "Places a neutral or scripted creature stack that can block movement, guard rewards, or start combat.", "random-squad", "monster_random_squad"),
        ("Random resource", "Places a resource pickup that grants map resources when collected.", "random-res", "resource_random"),
        ("Unmapped mine", "Places a capturable resource mine that provides recurring income to its owner.", "mine_gold", "mine_generic"),
    ]
    for h3_name, h3_desc, sid, rule in heuristics:
        entries.append(
            {
                "kind": "heuristic",
                "h3_name": h3_name,
                "h3_desc": h3_desc,
                "olden_sid": sid,
                "olden_desc": olden_desc(sid, core_catalog, english),
                "rule": rule,
            }
        )

    checkpoint = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
    for mapping in checkpoint.get("mappings", []):
        if mapping.get("reviewStatus") != "accepted":
            continue
        sid = mapping.get("oldenReplacementSid")
        if not sid:
            continue
        entries.append(
            {
                "kind": "checkpoint_accepted",
                "h3_id": mapping.get("templateObjectId"),
                "h3_name": mapping.get("homm3BuildingName"),
                "h3_desc": mapping.get("homm3Function"),
                "olden_sid": sid,
                "olden_desc": mapping.get("oldenEnglishDescription") or olden_desc(sid, core_catalog, english),
                "rule": mapping.get("startingRuleName"),
                "note": "human-reviewed accepted",
            }
        )

    seen: set[tuple] = set()
    unique: list[dict] = []
    for entry in entries:
        key = (entry.get("h3_name"), entry.get("olden_sid"), entry.get("rule"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


KEYWORDS = {
    "gold_cost": re.compile(r"\bgold\b", re.I),
    "free": re.compile(r"\bfree\b|no cost|without cost", re.I),
    "weekly": re.compile(r"week", re.I),
    "once": re.compile(r"once per|one time|single", re.I),
    "permanent": re.compile(r"permanent", re.I),
    "temporary": re.compile(r"temporary|limited time|this turn|this week", re.I),
    "choice": re.compile(r"choose|choice", re.I),
    "random": re.compile(r"random", re.I),
    "teleport": re.compile(r"teleport|portal|travel", re.I),
    "morale": re.compile(r"morale", re.I),
    "luck": re.compile(r"luck", re.I),
    "mana": re.compile(r"mana|spell point", re.I),
    "movement": re.compile(r"movement", re.I),
    "skill": re.compile(r"skill", re.I),
    "level": re.compile(r"level", re.I),
    "xp": re.compile(r"xp|experience", re.I),
    "reveal": re.compile(r"reveal", re.I),
    "quest": re.compile(r"quest|script", re.I),
    "protection": re.compile(r"protect|sanctuary|cannot be attacked", re.I),
    "mine_income": re.compile(r"produce|daily|income", re.I),
    "buy": re.compile(r"buy|purchase|sell|market", re.I),
    "paired": re.compile(r"paired", re.I),
    "all_heroes": re.compile(r"each visiting hero|every hero", re.I),
}


def extract_flags(text: str) -> set[str]:
    if not text:
        return set()
    return {name for name, pattern in KEYWORDS.items() if pattern.search(text)}


def severity(h3_flags: set[str], old_flags: set[str]) -> list[str]:
    only_h3 = h3_flags - old_flags
    only_old = old_flags - h3_flags
    issues: list[str] = []
    if "gold_cost" in only_old and ("free" in only_h3 or "permanent" in only_h3):
        issues.append("HoMM3 free/permanent reward vs Olden gold cost")
    if "weekly" in only_h3 and "once" in only_old:
        issues.append("HoMM3 weekly reward vs Olden one-shot cadence")
    if "weekly" in only_old and "once" in only_h3:
        issues.append("HoMM3 one-shot vs Olden weekly cadence")
    if "temporary" in only_h3 and "permanent" in only_old:
        issues.append("HoMM3 temporary buff vs Olden permanent effect")
    if "permanent" in only_h3 and "temporary" in only_old:
        issues.append("HoMM3 permanent vs Olden temporary/turn-limited effect")
    if "morale" in only_h3 and "morale" not in old_flags and "movement" in only_old:
        issues.append("HoMM3 morale vs Olden movement buff")
    if "luck" in only_h3 and "luck" not in old_flags:
        issues.append("HoMM3 luck mechanic likely absent in Olden replacement")
    if "protection" in only_h3 and "protection" not in old_flags:
        issues.append("HoMM3 protection/sanctuary behavior not represented")
    if "quest" in only_h3 and "quest" not in old_flags:
        issues.append("HoMM3 scripted event/quest vs non-script replacement")
    if "reveal" in only_h3 and "reveal" not in old_flags:
        issues.append("HoMM3 map reveal vs non-reveal replacement")
    if "teleport" in only_h3 and "paired" in only_old:
        issues.append("HoMM3 travel link may not match paired-portal semantics")
    if "buy" in only_h3 and "buy" not in old_flags:
        issues.append("HoMM3 purchasable interaction vs different Olden economy")
    if "choice" in only_h3 and "choice" not in old_flags:
        issues.append("HoMM3 player choice vs fixed Olden reward")
    if "level" in only_h3 and "xp" in only_old and "level" not in only_old:
        issues.append("HoMM3 grants level vs Olden grants XP")
    if "skill" in only_h3 and "random" in only_h3 and "buy" in only_old:
        issues.append("HoMM3 free random skill vs Olden paid skill purchase")
    return issues


def manual_issues(entry: dict) -> list[str]:
    issues: list[str] = []
    h3_desc = (entry.get("h3_desc") or "").lower()
    old_desc = (entry.get("olden_desc") or "").lower()
    rule = entry.get("rule") or ""
    sid = entry.get("olden_sid") or ""
    h3_name = entry.get("h3_name") or ""

    if sid == "alchemy_lab" and "sulf" in rule:
        issues.append("Sulfur mine mapped to Alchemy Lab (converts gems/crystals/mercury to dust, not sulfur production)")
    if rule == "template_gazebo" or h3_name.startswith("Gazebo"):
        if sid == "temporary_camp":
            issues.append("CRITICAL: Generator maps Gazebo->temporary_camp (weekly random resources) but HoMM3 Gazebo grants XP")
    if rule == "template_wind_object" or "Windmill Variant" in h3_name:
        if sid == "wind_rose":
            issues.append("Wind-themed HoMM3 object mapped to wind_rose (weekly random resources), not movement")
    if rule == "redwood_observatory_to_watchtower_reveal":
        issues.append("HoMM3 Redwood Observatory reveals terrain; verify Olden watchtower reveal behavior")
    if sid in {"random-squad", "random-res", "random-city", "hero-spawner", "fx_quest_mark_gold_01", "fx_quest_mark_silver_01", "mine_gold"}:
        issues.append("Lossy placeholder: generic/random/debug marker, not faithful HoMM3 equivalent")
    if rule == "cave_to_portal":
        issues.append("HoMM3 subterranean gate is layer travel; Olden portal_1 is same-layer paired teleport unless mod bridge handles it")
    if rule == "whirlpool_to_magic_portal":
        issues.append("HoMM3 whirlpool is one-way water/layer travel; Olden portal_magic is paired same-layer teleport")
    if h3_name == "Temple" and sid == "quixs_path" and "morale" in h3_desc and "movement" in old_desc:
        issues.append("Temple morale blessing mapped to Quix's Path movement buff")
    if "Fountain of Youth" in h3_name:
        issues.append("Blocked in generator; HoMM3 FoY is morale+movement, not simple fountain")
    if h3_name == "Sanctuary":
        issues.append("Blocked; HoMM3 Sanctuary prevents attacks - no Olden equivalent deployed")
    if h3_name == "Learning Stone" and sid == "learning_stone" and "Gazebo" in h3_name:
        issues.append("Checkpoint corrected gazebo XP mismatch to learning_stone")
    if sid == "fort" and "Attack or Defense" in (entry.get("h3_desc") or "") and "gold" in old_desc:
        issues.append("HoMM3 stat buildings are free; Olden fort charges gold per visit")
    if sid == "university" and "buy" in h3_desc and "random" in old_desc:
        issues.append("HoMM3 University sells offered skills; Olden university teaches random skills for gold")
    if sid == "wise_owl" and "random secondary skill" in h3_desc and "levels it up" in old_desc:
        issues.append("Olden wise_owl can level existing skills; HoMM3 Witch Hut only teaches new random skill")
    if sid == "tree_of_knowledge" and "level" in h3_desc and "one level" in old_desc:
        issues.append("Similar level-up intent, but HoMM3 may charge gold/conditions per map payload")
    if sid == "stables" and "week" in h3_desc and "movement" in old_desc:
        issues.append("Generally aligned, but verify HoMM3 stables +400 until week end vs Olden movement bonus amount")
    if sid == "fountain" and "movement" in old_desc:
        issues.append("HoMM3 Fountain of Vitality gives +1 movement; verify same magnitude in Olden")
    if sid == "knowledge_garden" and "knowledge" in old_desc:
        issues.append("Generally aligned permanent Knowledge gain; HoMM3 Garden of Revelation is +1 Knowledge")
    if rule == "template_den" and sid == "shady_den":
        issues.append("HoMM3 Crypt/Den spawns wandering monsters weekly; Olden shady_den is a weekly random resource reward")
    if rule == "template_mystic_object" and sid == "mysterious_stone":
        issues.append("HoMM3 Mystical Garden gives +1 Luck; Olden mysterious_stone is weekly random resources")
    if rule == "template_altar" and sid == "altar_of_magic_1":
        issues.append("HoMM3 Altar of Magic teaches random spell levels 1-3; verify Olden altar spell-teach contract")
    if rule == "template_plains_shrine" and sid == "altar_of_magic_1":
        issues.append("HoMM3 Shrine teaches specific spell school spells; Olden altar may teach different spell pool")
    if rule == "template_crystal" and sid == "crystal_trail":
        issues.append("HoMM3 Crystal Cavern gives +1 Crystal resource pickup; Olden crystal_trail is movement buff on snow")
    if rule == "template_eye" and sid == "insaras_eye":
        issues.append("HoMM3 Eye of the Magi reveals entire terrain for player; Olden Insara's Eye is a combat-style reveal ability with different scope")
    if rule == "template_sea_chest" and sid == "chest":
        issues.append("HoMM3 Sea Chest is random gold OR artifact; Olden chest is gold OR XP choice")
    if rule == "template_hill" and sid == "snow_grassy_hill_1":
        issues.append("Terrain/scenery only in both; no gameplay mismatch")
    if rule == "template_dungeon_entrance" and sid == "ruins_desert_1":
        issues.append("HoMM3 terrain decoration vs Olden ruins scenery; visual-only")
    return issues


def audit() -> dict:
    mod = load_module(REPO / "experiments/campaign_port_poc/build_homecoming_entity_substitution_map.py", "submap")
    menu = load_module(REPO / "experiments/campaign_port_poc/build_homecoming_mapping_review_menu.py", "menu")
    core_catalog = json.loads(CORE_CATALOG_PATH.read_text(encoding="utf-8"))
    english = load_english_tokens(core_catalog["sourceCoreZip"])
    entries = build_entries(mod, menu, core_catalog, english)

    flagged = []
    clean = []
    for entry in entries:
        h3_flags = extract_flags(entry.get("h3_desc", ""))
        old_flags = extract_flags(entry.get("olden_desc", ""))
        issues = severity(h3_flags, old_flags) + manual_issues(entry)
        issues = list(dict.fromkeys(issues))
        if issues:
            flagged.append({**entry, "issues": issues, "h3_flags": sorted(h3_flags), "old_flags": sorted(old_flags)})
        else:
            clean.append(entry)

    return {
        "total_unique_rules": len(entries),
        "flagged_count": len(flagged),
        "clean_count": len(clean),
        "flagged": flagged,
        "clean": clean,
    }


def main() -> int:
    result = audit()
    print(json.dumps({"total_unique_rules": result["total_unique_rules"], "flagged_count": result["flagged_count"], "clean_count": result["clean_count"]}, indent=2))
    print("=== FLAGGED ===")
    for item in sorted(result["flagged"], key=lambda row: (0 if any("CRITICAL" in issue for issue in row["issues"]) else 1, row.get("h3_name", ""))):
        print(f"\n## {item.get('h3_name')} -> {item.get('olden_sid')} [{item.get('rule')}]")
        print(f"HoMM3: {item.get('h3_desc', '')}")
        print(f"Olden: {item.get('olden_desc', '')}")
        for issue in item["issues"]:
            print(f"  ! {issue}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
