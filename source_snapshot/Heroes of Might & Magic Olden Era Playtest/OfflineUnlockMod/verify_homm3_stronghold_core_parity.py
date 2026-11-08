"""
Read-only checks that Core.zip has full homm3_stronghold parity with the generator
(generate_homm3_stronghold_city.py + generate_homm3_stronghold_heroes.py).

Exit 0 = all checks passed. Exit 1 = missing or mismatched data (stdout explains).

  python verify_homm3_stronghold_core_parity.py
  python verify_homm3_stronghold_core_parity.py --core "C:/path/to/Core.zip"
  set HEROESOE_CORE_ZIP=...  (optional override for default path)
"""

from __future__ import annotations

import json
import os
import re
import sys
import zipfile
from pathlib import Path

# Keep in sync with generate_homm3_stronghold_city.py
FRACTION_ID = "homm3_stronghold"
CITY_ID = "homm3_stronghold_city"
FRACTION_JSON_PATH = "DB/fractions/7_homm3_stronghold.json"
LAWS_JSON_PATH = "DB/fractions_laws/fractions_laws_table_homm3_stronghold.json"
CITY_JSON_PATH = f"DB/objects_logic/cities/{CITY_ID}.json"
UNITS_LOGIC_DIR = f"DB/units/units_logics/{FRACTION_ID}"
UNITS_VIEW_DIR = f"DB/units/units_views/{FRACTION_ID}"
SQUADS_DUNGEON_PREFIX = "DB/squads/squads_dungeon/"
SQUADS_STRONGHOLD_PREFIX = "DB/squads/squads_homm3_stronghold/"

BASE_TO_H3: dict[str, str] = {
    "trogl": "h3_goblin",
    "assassin": "h3_wolf_rider",
    "blade_dancer": "h3_orc",
    "minos": "h3_ogre",
    "medusa": "h3_roc",
    "hydra": "h3_cyclops",
    "black_dragon": "h3_behemoth",
}

STRONGHOLD_UNIT_LAW_IDS = {
    "fraction_law_homm3_stronghold_4",
    "fraction_law_homm3_stronghold_10",
    "fraction_law_homm3_stronghold_11",
    "fraction_law_homm3_stronghold_18",
    "fraction_law_homm3_stronghold_19",
    "fraction_law_homm3_stronghold_25",
    "fraction_law_homm3_stronghold_31",
}

EXPECTED_STRONGHOLD_LAW_ICONS = {
    "fraction_law_homm3_stronghold_4": "fraction_law_homm3_stronghold_4_icon",
    "fraction_law_homm3_stronghold_10": "fraction_law_homm3_stronghold_10_icon",
    "fraction_law_homm3_stronghold_11": "fraction_law_homm3_stronghold_11_icon",
    "fraction_law_homm3_stronghold_14": "fraction_law_nature_13_icon",
    "fraction_law_homm3_stronghold_18": "fraction_law_homm3_stronghold_18_icon",
    "fraction_law_homm3_stronghold_19": "fraction_law_homm3_stronghold_19_icon",
    "fraction_law_homm3_stronghold_25": "fraction_law_homm3_stronghold_25_icon",
    "fraction_law_homm3_stronghold_31": "fraction_law_homm3_stronghold_31_icon",
}

EXPECTED_STRONGHOLD_ABILITY_DONOR_ICONS = {
    ("h3_goblin_upg_alt", "abilities", "h3_goblin_ability_2_name"): "wasp_debuff_icon",
    ("h3_wolf_rider_upg", "passives", "h3_wolf_rider_upg_passive_1_name"): "pet_blood_icon",
    ("h3_wolf_rider_upg_alt", "abilities", "h3_wolf_rider_upg_alt_ability_1_name"): "minos_buff_icon",
    ("h3_ogre_upg", "abilities", "h3_ogre_upg_ability_1_name"): "magic_sharp_edge_effect_icon",
    ("h3_ogre_upg_alt", "abilities", "h3_ogre_upg_alt_ability_1_name"): "minos_buff_icon",
    ("h3_orc", "abilities", "h3_orc_hamstring_name"): "wasp_debuff_icon",
    ("h3_orc_upg", "abilities", "h3_orc_upg_hamstring_name"): "wasp_debuff_icon",
    ("h3_orc_upg_alt", "alternativeAttacks", "h3_orc_upg_alt_ability_1_name"): "assassin_buff_icon",
    ("h3_roc_upg", "abilities", "h3_roc_upg_ability_1_name"): "primal_1_magic_thunderbolt",
    ("h3_roc_upg_alt", "passives", "h3_roc_upg_alt_passive_1_name"): "dragon_hunter_blood_icon",
    ("h3_cyclops_upg_alt", "passives", "h3_cyclops_upg_alt_passive_1_name"): "crossbowman_buff_icon",
    ("h3_behemoth", "passives", "h3_behemoth_passive_1_name"): "sub_skill_units_attackPen_icon",
    ("h3_behemoth_upg", "passives", "h3_behemoth_upg_passive_1_name"): "sub_skill_units_attackPen_icon",
    ("h3_behemoth_upg_alt", "passives", "h3_behemoth_upg_alt_passive_1_name"): "sub_skill_units_attackPen_icon",
}


def full_sid_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for d_base, h3_base in BASE_TO_H3.items():
        for suf in ("", "_upg", "_upg_alt"):
            m[d_base + suf] = h3_base + suf
    return m


SID_MAP = full_sid_map()
HERO_PREFIX = "homm3_stronghold_hero"
STRONGHOLD_SUB_CLASSES_PATH = "DB/heroes_sub_classes/sub_classes_homm3_stronghold.json"
SPECS_PATH = f"DB/heroes_specializations/specializations_{FRACTION_ID}.json"
ARENA_GAME_PATH = "DB/arenaGame.json"
ARENA_PICK_CONTENT_PATH = "DB/ai_pick/arena_pick_content.json"
ARENA_PICK_MODS_PATH = "DB/ai_pick/arena_pick_mods.json"
SKILLS_BY_LEVEL_REPLACE_PATH = "DB/heroes_skills/skills_by_level_replace_tables/skills_by_level_replace_table.json"
SPACE_MAGIC_BUFFS_PATH = "DB/buffs/buffs_space_magics.json"
M2_M10_PATHS = (
    "DB/buildings_bans/M10_banlists.json",
    "DB/buildings_bans/M2_banlists.json",
    "DB/buildings_constructions/M10_buildings_presets.json",
    "DB/buildings_constructions/M2_buildings_presets.json",
)

EXPECTED_STRONGHOLD_BUILDING_TREE = {
    ("Build_Tier_1", 1): {"req": (), "cost": (("gold", 200), ("wood", 5), ("ore", 5))},
    ("Build_Tier_1", 2): {"req": (("Build_Tier_1", 1),), "cost": (("gold", 1000), ("wood", 5), ("ore", 5), ("dust", 10))},
    ("Build_Tier_2", 1): {"req": (("Build_Tier_1", 1),), "cost": (("gold", 1000), ("wood", 10), ("ore", 5))},
    ("Build_Tier_2", 2): {"req": (("Build_Tier_2", 1),), "cost": (("gold", 1000), ("wood", 5), ("ore", 5), ("dust", 20))},
    ("Build_Tier_3", 1): {"req": (("Build_Tier_1", 1),), "cost": (("gold", 1000), ("wood", 5), ("ore", 5))},
    ("Build_Tier_3", 2): {"req": (("Build_Tier_3", 1),), "cost": (("gold", 1000), ("wood", 2), ("ore", 2), ("dust", 30))},
    ("Build_Tier_4", 1): {"req": (("Build_Tier_3", 1),), "cost": (("gold", 2000), ("wood", 20))},
    ("Build_Tier_4", 2): {"req": (("Build_Tier_4", 1), ("Build_Magic_Guild", 1)), "cost": (("gold", 2000), ("wood", 5), ("ore", 5), ("gemstones", 5), ("dust", 40))},
    ("Build_Tier_5", 1): {"req": (("Build_Tier_2", 1),), "cost": (("gold", 2500), ("ore", 10))},
    ("Build_Tier_5", 2): {"req": (("Build_Tier_5", 1),), "cost": (("gold", 2000), ("wood", 5), ("ore", 5), ("dust", 50))},
    ("Build_Tier_6", 1): {"req": (("Build_Tier_4", 1),), "cost": (("gold", 3500), ("ore", 20), ("crystals", 20))},
    ("Build_Tier_6", 2): {"req": (("Build_Tier_6", 1),), "cost": (("gold", 3000), ("wood", 5), ("ore", 5), ("crystals", 10), ("dust", 75))},
    ("Build_Tier_7", 1): {"req": (("Build_Tier_5", 1),), "cost": (("gold", 10000), ("wood", 10), ("ore", 10), ("crystals", 10))},
    ("Build_Tier_7", 2): {"req": (("Build_Tier_7", 1),), "cost": (("gold", 15000), ("wood", 10), ("ore", 10), ("crystals", 20), ("dust", 100))},
    ("Build_Gymnasium", 1): {"req": (("Build_Wall", 1),), "cost": (("gold", 1000),)},
}

EXPECTED_STRONGHOLD_BUILDING_BONUSES = {
    ("heroBonusBanks", "Build_Gymnasium"): (
        {"type": "heroStat", "parameters": ["offence", "2"]},
    ),
    ("banks", "Build_Resource_Depot"): (
        {"type": "sideRes", "parameters": ["crystals", 1]},
    ),
    ("banks", "Build_Resource_Depot_level_2"): (
        {"type": "sideRes", "parameters": ["ore", 1]},
    ),
    ("cityBonusBanks", "Build_Lyceum"): (
        {"type": "cityUnitsIncrement", "parameters": ["h3_goblin", "8"]},
    ),
}

EXPECTED_ENGLISH_CITY_TEXT = {
    "Homm3Stronghold_Build_Gymnasium_name": "Hall of Valhalla",
    "Homm3Stronghold_Build_Gymnasium_description": "Increases the visiting hero's Attack by 2.",
    "Homm3Stronghold_Build_Lyceum_name": "Mess Hall",
    "Homm3Stronghold_Build_Lyceum_description": "Increases Goblin growth by 8.",
    "Homm3Stronghold_Build_Resource_Depot_name": "Resource Silo",
    "Homm3Stronghold_Build_Resource_Depot_description": "Produces 1 Crystal daily.",
    "Homm3Stronghold_Build_Resource_Depot_name_level_2": "Resource Silo II",
    "Homm3Stronghold_Build_Resource_Depot_description_level_2": "Produces 1 Ore daily.",
}

EXPECTED_CITY_ARG_OVERRIDES = {
    "Homm3Stronghold_Build_Gymnasium_description": [],
    "Homm3Stronghold_Build_Lyceum_description": [],
    "Homm3Stronghold_Build_Resource_Depot_description": [],
    "Homm3Stronghold_Build_Resource_Depot_description_level_2": [],
}

EXPECTED_ENGLISH_HERO_TEXT = {
    "homm3_stronghold_hero_1": "Crag Hack",
}

_DEFAULT_CORE = (
    Path(__file__).resolve().parent.parent
    / "HeroesOE_Data"
    / "StreamingAssets"
    / "Core.zip"
)


def resolve_core_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get("HEROESOE_CORE_ZIP", "").strip()
    if env:
        return Path(env)
    return _DEFAULT_CORE


def err(msg: str) -> None:
    print(f"PARITY FAIL: {msg}", file=sys.stderr)


def load_json_member(z: zipfile.ZipFile, path: str) -> dict:
    raw = z.read(path).decode("utf-8-sig")
    return json.loads(raw)


def token_text_by_sid(payload: dict) -> dict[str, str]:
    return {
        t.get("sid"): t.get("text", "")
        for t in payload.get("tokens") or []
        if isinstance(t, dict)
    }


def token_args_by_sid(payload: dict) -> dict[str, list]:
    return {
        t.get("sid"): t.get("args", [])
        for t in payload.get("tokensArgs") or []
        if isinstance(t, dict)
    }


def main() -> int:
    import argparse

    ap = argparse.ArgumentParser(description="Verify homm3_stronghold Core.zip parity.")
    ap.add_argument(
        "--core",
        metavar="PATH",
        help="Core.zip path (default: HEROESOE_CORE_ZIP env or playtest StreamingAssets/Core.zip)",
    )
    args = ap.parse_args()
    core = resolve_core_path(args.core)

    if not core.is_file():
        err(f"Core.zip not found: {core}")
        return 1

    failed = False

    with zipfile.ZipFile(core, "r") as z:
        names = set(z.namelist())

        def need(path: str, label: str | None = None) -> None:
            nonlocal failed
            if path not in names:
                failed = True
                err(f"missing file {label or path}")

        for path in (
            FRACTION_JSON_PATH,
            LAWS_JSON_PATH,
            CITY_JSON_PATH,
            "DB/data.json",
            "DB/map/objects/4_interactables.json",
            "DB/map_objects_sounds.json",
            "DB/city_ambient_sounds.json",
            "DB/city_music_sounds.json",
            "DB/objects_logic/hires/barracks.json",
            ARENA_GAME_PATH,
            ARENA_PICK_CONTENT_PATH,
            ARENA_PICK_MODS_PATH,
            SKILLS_BY_LEVEL_REPLACE_PATH,
        ):
            need(path)

        for sid in sorted(set(SID_MAP.values())):
            need(f"{UNITS_LOGIC_DIR}/{sid}_l.json", f"unit logic {sid}")
            need(f"{UNITS_VIEW_DIR}/{sid}_v.json", f"unit view {sid}")

        for (sid, section, view_name), expected_icon in sorted(EXPECTED_STRONGHOLD_ABILITY_DONOR_ICONS.items()):
            path = f"{UNITS_VIEW_DIR}/{sid}_v.json"
            if path not in names:
                continue
            unit_view_root = load_json_member(z, path)
            rows = unit_view_root.get("array") or []
            row = rows[0] if rows and isinstance(rows[0], dict) else {}
            found = None
            for item in row.get(section) or []:
                if isinstance(item, dict) and item.get("name") == view_name:
                    found = item
                    break
            if not isinstance(found, dict):
                failed = True
                err(f"{path} missing {section} row {view_name!r}")
                continue
            if found.get("icon") != expected_icon:
                failed = True
                err(f"{path} {view_name} icon is {found.get('icon')!r}; expected {expected_icon!r}")

        dungeon_squads = sorted(n for n in names if n.startswith(SQUADS_DUNGEON_PREFIX) and n.endswith(".json"))
        strong_squads = sorted(n for n in names if n.startswith(SQUADS_STRONGHOLD_PREFIX) and n.endswith(".json"))
        if len(dungeon_squads) != len(strong_squads):
            failed = True
            err(
                f"squad file count mismatch: squads_dungeon={len(dungeon_squads)} "
                f"vs squads_homm3_stronghold={len(strong_squads)} (expected equal clone)"
            )
        elif len(strong_squads) == 0:
            failed = True
            err("no files under DB/squads/squads_homm3_stronghold/")
        else:
            print(f"OK: squads clone ({len(strong_squads)} json files)")

        data = load_json_member(z, "DB/data.json")
        fr = data.get("fractions") or []
        af = data.get("availableFractions") or []
        if FRACTION_ID not in fr:
            failed = True
            err(f"DB/data.json fractions does not list '{FRACTION_ID}'")
        if FRACTION_ID not in af:
            failed = True
            err(f"DB/data.json availableFractions does not list '{FRACTION_ID}'")

        interact = load_json_member(z, "DB/map/objects/4_interactables.json")
        ids = {o.get("id") for o in interact.get("array") or [] if isinstance(o, dict)}
        if CITY_ID not in ids:
            failed = True
            err(f"4_interactables.json missing id '{CITY_ID}'")

        mos = load_json_member(z, "DB/map_objects_sounds.json")
        mo_data = (mos.get("objectsArr") or {}).get("data") or []
        mo_keys = {x.get("key") for x in mo_data if isinstance(x, dict)}
        if CITY_ID not in mo_keys:
            failed = True
            err(f"map_objects_sounds.json missing key '{CITY_ID}'")

        for label, path_key in (
            ("city_ambient_sounds", "DB/city_ambient_sounds.json"),
            ("city_music_sounds", "DB/city_music_sounds.json"),
        ):
            root = load_json_member(z, path_key)
            data_rows = root.get("array", {}).get("data") if isinstance(root.get("array"), dict) else None
            if data_rows is None:
                arr = root.get("array")
                data_rows = arr.get("data") if isinstance(arr, dict) else []
            keys = {x.get("key") for x in (data_rows or []) if isinstance(x, dict)}
            if FRACTION_ID not in keys:
                failed = True
                err(f"{path_key} missing fraction key '{FRACTION_ID}'")

        barracks = load_json_member(z, "DB/objects_logic/hires/barracks.json")
        barracks_rows = barracks.get("array") or []
        strong_barracks = [
            row
            for row in barracks_rows
            if isinstance(row, dict) and row.get("fraction") == FRACTION_ID
        ]
        if len(strong_barracks) != 7:
            failed = True
            err(f"barracks.json expected 7 '{FRACTION_ID}' rows, found {len(strong_barracks)}")
        for row in strong_barracks:
            rid = row.get("id")
            if not isinstance(rid, str) or not rid.startswith(f"barracks_{FRACTION_ID}_"):
                failed = True
                err(f"barracks.json row has unexpected id '{rid}'")
            raw = json.dumps(row, ensure_ascii=False)
            for old_sid in SID_MAP:
                if old_sid in raw:
                    failed = True
                    err(f"barracks.json row '{rid}' still contains dungeon unit sid '{old_sid}'")
                    break

        # M2/M10: every *_dungeon_city row must have sibling *_homm3_stronghold_city
        for path in M2_M10_PATHS:
            if path not in names:
                failed = True
                err(f"missing {path}")
                continue
            root = load_json_member(z, path)
            arr = root.get("array")
            if not isinstance(arr, list):
                continue
            dungeon_city_ids = [
                o.get("id")
                for o in arr
                if isinstance(o, dict) and isinstance(o.get("id"), str) and o["id"].endswith("dungeon_city")
            ]
            all_ids = {o.get("id") for o in arr if isinstance(o, dict)}
            for did in dungeon_city_ids:
                counterpart = did[:-len("dungeon_city")] + CITY_ID
                if counterpart not in all_ids:
                    failed = True
                    err(f"{path}: missing preset row id '{counterpart}' (clone of '{did}')")

        city_root = load_json_member(z, CITY_JSON_PATH)
        city_rows = city_root.get("array") or []
        city = city_rows[0] if city_rows and isinstance(city_rows[0], dict) else {}
        building_rows = {}
        building_by_group_sid = {}
        for group in ("hires", "heroBonusBanks", "banks", "cityBonusBanks"):
            for building in city.get(group) or []:
                if not isinstance(building, dict) or not isinstance(building.get("sid"), str):
                    continue
                building_by_group_sid[(group, building["sid"])] = building
                for idx, params in enumerate(building.get("parametersPerLevel") or [], start=1):
                    if isinstance(params, dict):
                        building_rows[(building["sid"], idx)] = params
        for key, expected in EXPECTED_STRONGHOLD_BUILDING_TREE.items():
            params = building_rows.get(key)
            if params is None:
                failed = True
                err(f"{CITY_JSON_PATH}: missing building level params {key[0]} level {key[1]}")
                continue
            got_req = tuple(
                (row.get("sid"), row.get("level"))
                for row in params.get("prevBuildings") or []
                if isinstance(row, dict)
            )
            got_cost = tuple(
                (row.get("name"), row.get("cost"))
                for row in params.get("costs") or []
                if isinstance(row, dict)
            )
            if got_req != expected["req"]:
                failed = True
                err(f"{CITY_JSON_PATH}: {key[0]} level {key[1]} prereqs {got_req} != {expected['req']}")
            if got_cost != expected["cost"]:
                failed = True
                err(f"{CITY_JSON_PATH}: {key[0]} level {key[1]} costs {got_cost} != {expected['cost']}")
        for (sid, level), params in building_rows.items():
            if not sid.startswith("Build_Tier_") or level <= 1:
                continue
            for req in params.get("prevBuildings") or []:
                if not isinstance(req, dict):
                    continue
                req_sid = req.get("sid")
                req_level = req.get("level")
                if (
                    isinstance(req_sid, str)
                    and req_sid.startswith("Build_Tier_")
                    and req_sid != sid
                    and isinstance(req_level, int)
                    and req_level > 1
                ):
                    failed = True
                    err(
                        f"{CITY_JSON_PATH}: {sid} level {level} depends on different dwelling "
                        f"upgrade {req_sid} level {req_level}"
                    )
        for (group, sid), expected_bonuses in EXPECTED_STRONGHOLD_BUILDING_BONUSES.items():
            building = building_by_group_sid.get((group, sid))
            if building is None:
                failed = True
                err(f"{CITY_JSON_PATH}: missing {group} building '{sid}'")
                continue
            got_bonuses = tuple(building.get("bonuses") or [])
            if got_bonuses != expected_bonuses:
                failed = True
                err(f"{CITY_JSON_PATH}: {group}/{sid} bonuses {got_bonuses!r} != {expected_bonuses!r}")
        artifact_changer_sids = {
            b.get("sid")
            for b in city.get("artifactChangers") or []
            if isinstance(b, dict)
        }
        if "Build_Lyceum" in artifact_changer_sids:
            failed = True
            err(f"{CITY_JSON_PATH}: Build_Lyceum still exists as artifactChangers row; expected Mess Hall cityBonusBanks row")
        magic_guild = None
        for building in city.get("magicGuilds") or []:
            if isinstance(building, dict) and building.get("sid") == "Build_Magic_Guild":
                magic_guild = building
                break
        if magic_guild is None:
            failed = True
            err(f"{CITY_JSON_PATH}: missing Build_Magic_Guild")
        else:
            params = magic_guild.get("parametersPerLevel")
            if not isinstance(params, list) or len(params) != 3:
                failed = True
                got = len(params) if isinstance(params, list) else type(params).__name__
                err(f"{CITY_JSON_PATH}: Build_Magic_Guild must be capped at 3 levels, got {got}")

        english_cities = "Lang/english/texts/cities.json"
        if english_cities in names:
            by_sid = token_text_by_sid(load_json_member(z, english_cities))
            for sid, expected_text in EXPECTED_ENGLISH_CITY_TEXT.items():
                got_text = by_sid.get(sid)
                if got_text != expected_text:
                    failed = True
                    err(f"{english_cities}: {sid} Core.zip text {got_text!r} != {expected_text!r}")
        else:
            failed = True
            err(f"missing English cities localization member: {english_cities}")

        args_cities = "Lang/args/cities.json"
        if args_cities in names:
            by_sid = token_args_by_sid(load_json_member(z, args_cities))
            for sid, expected_args in EXPECTED_CITY_ARG_OVERRIDES.items():
                got_args = by_sid.get(sid)
                if got_args != expected_args:
                    failed = True
                    err(f"{args_cities}: {sid} Core.zip args {got_args!r} != {expected_args!r}")
        else:
            failed = True
            err(f"missing city args localization member: {args_cities}")

        english_hero_info = "Lang/english/texts/heroInfo.json"
        if english_hero_info in names:
            by_sid = token_text_by_sid(load_json_member(z, english_hero_info))
            for sid, expected_text in EXPECTED_ENGLISH_HERO_TEXT.items():
                got_text = by_sid.get(sid)
                if got_text != expected_text:
                    failed = True
                    err(f"{english_hero_info}: {sid} Core.zip text {got_text!r} != {expected_text!r}")
        else:
            failed = True
            err(f"missing English hero localization member: {english_hero_info}")

        # Heroes pipeline
        need(STRONGHOLD_SUB_CLASSES_PATH)
        need(SPECS_PATH)
        for i in range(1, 19):
            need(f"DB/heroes/{FRACTION_ID}/{HERO_PREFIX}_{i}.json")

        expected_heroes = {f"{HERO_PREFIX}_{i}" for i in range(1, 19)}
        arena_game = load_json_member(z, ARENA_GAME_PATH)
        arena_heroes = {
            row.get("sid")
            for row in arena_game.get("heroes") or []
            if isinstance(row, dict) and isinstance(row.get("sid"), str)
        }
        missing = expected_heroes - arena_heroes
        if missing:
            failed = True
            err(f"{ARENA_GAME_PATH} missing homm3_stronghold hero rows: {sorted(missing)}")

        pick_content = load_json_member(z, ARENA_PICK_CONTENT_PATH)
        pick_heroes = set()
        for block in pick_content.get("content") or []:
            if isinstance(block, dict) and block.get("sid") == "heroes":
                pick_heroes = {
                    row.get("sid")
                    for row in block.get("array") or []
                    if isinstance(row, dict) and isinstance(row.get("sid"), str)
                }
                break
        missing = expected_heroes - pick_heroes
        if missing:
            failed = True
            err(f"{ARENA_PICK_CONTENT_PATH} heroes pick list missing rows: {sorted(missing)}")

        pick_mods = load_json_member(z, ARENA_PICK_MODS_PATH)
        pick_mod_heroes = set()
        for row in pick_mods.get("array") or []:
            if not isinstance(row, dict):
                continue
            for sid in row.get("becauseOf") or []:
                if isinstance(sid, str) and sid.startswith(f"{HERO_PREFIX}_"):
                    pick_mod_heroes.add(sid)
        missing = expected_heroes - pick_mod_heroes
        if missing:
            failed = True
            err(f"{ARENA_PICK_MODS_PATH} missing hero modifier coverage: {sorted(missing)}")

        skill_replace = load_json_member(z, SKILLS_BY_LEVEL_REPLACE_PATH)
        replace_heroes = {
            row.get("id")
            for row in skill_replace.get("array") or []
            if isinstance(row, dict) and isinstance(row.get("id"), str)
        }
        dungeon_replace_nums = {
            int(row["id"].removeprefix("dungeon_hero_"))
            for row in skill_replace.get("array") or []
            if isinstance(row, dict)
            and isinstance(row.get("id"), str)
            and row["id"].startswith("dungeon_hero_")
            and row["id"].removeprefix("dungeon_hero_").isdigit()
        }
        expected_replace = {f"{HERO_PREFIX}_{i}" for i in dungeon_replace_nums}
        missing = expected_replace - replace_heroes
        if missing:
            failed = True
            err(f"{SKILLS_BY_LEVEL_REPLACE_PATH} missing cloned replace rows: {sorted(missing)}")

        city_raw = z.read(CITY_JSON_PATH).decode("utf-8-sig")
        city_root = json.loads(city_raw)
        acity = city_root.get("array") or []
        if not acity or acity[0].get("id") != CITY_ID:
            failed = True
            err(f"{CITY_JSON_PATH} must have array[0].id == {CITY_ID}")
        elif acity[0].get("fraction") != FRACTION_ID:
            failed = True
            err(f"{CITY_JSON_PATH} array[0].fraction must be {FRACTION_ID}")

        laws = load_json_member(z, LAWS_JSON_PATH)
        laws_by_id = {}
        for law in laws.get("array") or []:
            lid = law.get("id") if isinstance(law, dict) else None
            if isinstance(lid, str):
                laws_by_id[lid] = law
            if isinstance(lid, str) and lid.startswith("fraction_law_dungeon_"):
                failed = True
                err(f"laws table still contains dungeon id {lid!r} (expected homm3_stronghold remaps)")
                break
        for lid in sorted(STRONGHOLD_UNIT_LAW_IDS):
            law = laws_by_id.get(lid)
            if not isinstance(law, dict):
                failed = True
                err(f"laws table missing Stronghold unit law '{lid}'")
                continue
            raw = json.dumps(law, ensure_ascii=False)
            if "armed_ability_" in raw:
                failed = True
                err(f"{lid} still contains Dungeon fighting-style/stance modifier data")
        for lid, expected_icon in sorted(EXPECTED_STRONGHOLD_LAW_ICONS.items()):
            law = laws_by_id.get(lid)
            if isinstance(law, dict) and law.get("icon") != expected_icon:
                failed = True
                err(f"{lid} icon is {law.get('icon')!r}; expected {expected_icon!r}")
        law14 = laws_by_id.get("fraction_law_homm3_stronghold_14")
        if isinstance(law14, dict):
            raw14 = json.dumps(law14, ensure_ascii=False)
            if "gemstones" in raw14 or "mercury" in raw14 or "crystals" not in raw14:
                failed = True
                err("fraction_law_homm3_stronghold_14 must produce crystals, not mercury or gemstones")

        space_magic_buffs = load_json_member(z, SPACE_MAGIC_BUFFS_PATH)
        space_magic_buff_ids = {
            row.get("id")
            for row in (space_magic_buffs.get("array") or [])
            if isinstance(row, dict)
        }
        for mode in ("moral", "luck", "initiative"):
            for suffix in ("", "_1", "_2", "_negative", "_negative_1", "_negative_2", "_sub_skill_4"):
                buff_id = f"homm3_stronghold_warcry_{mode}_effect{suffix}"
                if buff_id not in space_magic_buff_ids:
                    failed = True
                    err(f"{SPACE_MAGIC_BUFFS_PATH} missing global_buff-resolvable Warcry row {buff_id!r}")

    if failed:
        print(f"\nChecked archive: {core}", file=sys.stderr)
        return 1

    print(f"Core parity OK: {core}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
