"""
Best-effort rebuild for Grove/Nature heroes.

The current playtest ships `nature_hero_*` presentation text, but their
specializations are still Human placeholders. This script rewrites the live
Nature specializations and a few obvious starting spell/skill mismatches so the
roster better matches the restored Grove descriptions.

Run:
  python generate_nature_heroes.py
"""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path

PLAYTEST_CORE = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Core.zip"
)


def load_json_from_zip(zpath: Path, inner_path: str) -> dict:
    with zipfile.ZipFile(zpath, "r") as z:
        return json.loads(z.read(inner_path).decode("utf-8-sig"))


def rebuild_zip(core_path: Path, updates: dict[str, bytes]) -> None:
    backup = core_path.with_suffix(".zip.bak_before_nature_heroes")
    if not backup.exists():
        backup.write_bytes(core_path.read_bytes())

    with zipfile.ZipFile(core_path, "r") as zin:
        entries = {i.filename: i for i in zin.infolist()}
        all_data = {name: zin.read(name) for name in zin.namelist()}

    all_data.update(updates)

    with zipfile.ZipFile(core_path, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, blob in sorted(all_data.items()):
            zi = entries.get(name)
            if zi is not None:
                zout.writestr(zi, blob)
            else:
                zout.writestr(name, blob)


def replace_unit_ids(obj, mapping: dict[str, str]) -> None:
    if isinstance(obj, dict):
        for key, value in list(obj.items()):
            if key == "sid" and isinstance(value, str) and value in mapping:
                obj[key] = mapping[value]
            elif key == "receivers" and isinstance(value, list):
                obj[key] = [mapping.get(v, v) for v in value]
            elif key == "parameters" and isinstance(value, list):
                obj[key] = [mapping.get(v, v) if isinstance(v, str) else v for v in value]
            else:
                replace_unit_ids(value, mapping)
    elif isinstance(obj, list):
        for item in obj:
            replace_unit_ids(item, mapping)


def standard_magic_unlocks(ability_sid: str) -> list[dict]:
    return [
        {"type": "heroBattleAbility", "parameters": [ability_sid, "0"]},
        {
            "type": "heroBattleAbility",
            "battleType": "forCity",
            "receiverRole": "attacker",
            "parameters": ["attack_siege_ability", "0"],
        },
        {"type": "heroStat", "parameters": ["magicSchoolSet", "neutral", "1", "0"]},
        {
            "activationLevel": 4,
            "type": "heroStat",
            "parameters": ["magicSchoolSet", "neutral", "2", "0"],
        },
        {
            "activationLevel": 8,
            "type": "heroStat",
            "parameters": ["magicSchoolSet", "neutral", "3", "0"],
        },
        {
            "activationLevel": 12,
            "type": "heroStat",
            "parameters": ["magicSchoolSet", "neutral", "4", "0"],
        },
    ]


def make_spell_specialist(normal_sid: str, special_sid: str, ability_sid: str) -> list[dict]:
    return [
        {"type": "heroMagicReplace", "parameters": [normal_sid, special_sid]},
        {
            "type": "heroStat",
            "parameters": ["spellPowerSidSet", special_sid, "0"],
            "upgrade": {"increment": 1, "levelStep": 3},
        },
        *standard_magic_unlocks(ability_sid),
    ]


def make_avatar_specialist(ability_sid: str) -> list[dict]:
    bonuses: list[dict] = []
    for level in range(1, 6):
        normal = f"bonus_magic_astral_summon_{level}"
        special = f"bonus_magic_astral_summon_nature_{level}"
        bonuses.append({"type": "heroMagicReplace", "parameters": [normal, special]})
        bonuses.append(
            {
                "type": "heroStat",
                "parameters": ["spellPowerSidSet", special, "0"],
                "upgrade": {"increment": 1, "levelStep": 3},
            }
        )
    bonuses.extend(standard_magic_unlocks(ability_sid))
    return bonuses


def make_focus_specialist(ability_sid: str) -> list[dict]:
    return [
        {
            "type": "heroStat",
            "parameters": ["energyLevelsPerRoundBonus", "1"],
            "upgrade": {"increment": 1, "levelStep": 3},
        },
        {
            "type": "heroStatBattle",
            "receiverAllegiance": "enemy",
            "parameters": ["energyLevelsPerRoundBonus", "-1"],
            "upgrade": {"increment": -1, "levelStep": 3},
        },
        *standard_magic_unlocks(ability_sid),
    ]


def patch_nature_specializations(core_path: Path) -> dict:
    spec_files = {
        "human": load_json_from_zip(core_path, "DB/heroes_specializations/specializations_human.json"),
        "demon": load_json_from_zip(core_path, "DB/heroes_specializations/specializations_demon.json"),
        "dungeon": load_json_from_zip(core_path, "DB/heroes_specializations/specializations_dungeon.json"),
        "necro": load_json_from_zip(core_path, "DB/heroes_specializations/specializations_necro.json"),
        "unfrozen": load_json_from_zip(core_path, "DB/heroes_specializations/specializations_unfrozen.json"),
        "nature": load_json_from_zip(core_path, "DB/heroes_specializations/specializations_nature.json"),
    }
    specs = spec_files["nature"]

    templates: dict[str, dict] = {}
    for payload in spec_files.values():
        for item in payload.get("array") or []:
            templates[item["id"]] = item

    spec_map = {item["id"]: item for item in specs.get("array") or []}

    def set_bonuses(target_id: str, source_bonuses: list[dict]) -> None:
        spec_map[target_id]["bonuses"] = copy.deepcopy(source_bonuses)

    # Straight template swaps.
    set_bonuses("nature_hero_1_specialization", templates["human_hero_2_specialization"]["bonuses"])
    set_bonuses("nature_hero_2_specialization", templates["demon_hero_1_specialization"]["bonuses"])
    set_bonuses("nature_hero_5_specialization", templates["dungeon_hero_8_specialization"]["bonuses"])
    set_bonuses("nature_hero_8_specialization", templates["necro_hero_2_specialization"]["bonuses"])
    set_bonuses("nature_hero_9_specialization", templates["human_hero_9_specialization"]["bonuses"])
    set_bonuses("nature_hero_10_specialization", templates["human_hero_10_specialization"]["bonuses"])

    # Unit specialists.
    faun = copy.deepcopy(templates["human_hero_3_specialization"]["bonuses"])
    replace_unit_ids(
        faun,
        {
            "esquire": "elf_tracker",
            "esquire_upg": "elf_tracker_upg",
            "esquire_upg_alt": "elf_tracker_upg_alt",
        },
    )
    set_bonuses("nature_hero_3_specialization", faun)

    herbomancer = copy.deepcopy(templates["human_hero_12_specialization"]["bonuses"])
    replace_unit_ids(
        herbomancer,
        {
            "lightweaver": "druid",
            "lightweaver_upg": "druid_upg",
            "lightweaver_upg_alt": "druid_upg_alt",
        },
    )
    set_bonuses("nature_hero_11_specialization", herbomancer)

    # Crystal economy hero.
    crystals = copy.deepcopy(templates["human_hero_6_specialization"]["bonuses"])
    replace_unit_ids(crystals, {"gemstones": "crystals"})
    set_bonuses("nature_hero_6_specialization", crystals)

    # Spell specialists.
    set_bonuses(
        "nature_hero_4_specialization",
        make_spell_specialist("space_11_magic_decimate", "space_11_magic_decimate_special", "skill_warrior_ability"),
    )
    set_bonuses(
        "nature_hero_7_specialization",
        make_spell_specialist("primal_4_magic_fire_globe", "primal_4_magic_fire_globe_special", "skill_warrior_ability"),
    )
    set_bonuses(
        "nature_hero_12_specialization",
        make_spell_specialist(
            "primal_7_magic_wall_of_flame",
            "primal_7_magic_wall_of_flame_special",
            "skill_mage_ability",
        ),
    )
    set_bonuses(
        "nature_hero_13_specialization",
        make_spell_specialist("primal_6_magic_ice_bolt", "primal_6_magic_ice_bolt_special", "skill_mage_ability"),
    )
    set_bonuses(
        "nature_hero_14_specialization",
        make_spell_specialist("primal_8_magic_cave_in", "primal_8_magic_cave_in_special", "skill_mage_ability"),
    )
    set_bonuses(
        "nature_hero_15_specialization",
        make_spell_specialist(
            "primal_12_magic_chain_lightning",
            "primal_12_magic_chain_lightning_special",
            "skill_mage_ability",
        ),
    )
    set_bonuses(
        "nature_hero_16_specialization",
        make_spell_specialist(
            "space_10_magic_mirror_copy",
            "space_10_magic_mirror_copy_special",
            "skill_mage_ability",
        ),
    )

    # Avatar / focus specialists.
    set_bonuses("nature_hero_17_specialization", make_avatar_specialist("skill_mage_ability"))
    set_bonuses("nature_hero_18_specialization", make_focus_specialist("skill_mage_ability"))

    return specs


def patch_nature_heroes(core_path: Path) -> dict[str, bytes]:
    updates: dict[str, bytes] = {}

    def write_hero(hero_id: int, patch_fn) -> None:
        inner = f"DB/heroes/nature/nature_hero_{hero_id}.json"
        data = load_json_from_zip(core_path, inner)
        hero = copy.deepcopy(data["array"][0])
        patch_fn(hero)
        updates[inner] = json.dumps({"array": [hero]}, ensure_ascii=False, indent="\t").encode("utf-8")

    def set_secondary_skill(hero: dict, sid: str | None) -> None:
        skills = [{"sid": "skill_faction_nature", "skillLevel": 1}]
        if sid:
            skills.append({"sid": sid, "skillLevel": 1})
        hero["startSkills"] = skills

    def set_start_magic(hero: dict, sid: str | None) -> None:
        hero["startMagics"] = [] if sid is None else [{"sidConfig": sid, "level": 1, "isLearned": True}]

    write_hero(4, lambda h: (set_secondary_skill(h, "skill_magic_space"), set_start_magic(h, "space_11_magic_decimate")))
    write_hero(7, lambda h: (set_secondary_skill(h, "skill_magic_primal"), set_start_magic(h, "primal_4_magic_fire_globe")))
    write_hero(8, lambda h: set_secondary_skill(h, "skill_diplomacy"))
    write_hero(12, lambda h: (set_secondary_skill(h, "skill_magic_primal"), set_start_magic(h, "primal_7_magic_wall_of_flame")))
    write_hero(13, lambda h: (set_secondary_skill(h, "skill_magic_primal"), set_start_magic(h, "primal_6_magic_ice_bolt")))
    write_hero(14, lambda h: (set_secondary_skill(h, "skill_magic_primal"), set_start_magic(h, "primal_8_magic_cave_in")))
    write_hero(15, lambda h: (set_secondary_skill(h, "skill_magic_primal"), set_start_magic(h, "primal_12_magic_chain_lightning")))
    write_hero(16, lambda h: (set_secondary_skill(h, "skill_magic_space"), set_start_magic(h, "space_10_magic_mirror_copy")))
    write_hero(17, lambda h: (set_secondary_skill(h, "skill_summoner"), set_start_magic(h, None)))

    return updates


def main() -> None:
    if not PLAYTEST_CORE.exists():
        raise SystemExit(f"Missing Playtest Core.zip: {PLAYTEST_CORE}")

    updates = patch_nature_heroes(PLAYTEST_CORE)
    specs = patch_nature_specializations(PLAYTEST_CORE)
    updates["DB/heroes_specializations/specializations_nature.json"] = json.dumps(
        specs, ensure_ascii=False, indent="\t"
    ).encode("utf-8")

    rebuild_zip(PLAYTEST_CORE, updates)

    print(f"Patched {PLAYTEST_CORE}: Grove hero specializations + starting spell fixes")
    print(f"Backup (if created): {PLAYTEST_CORE.with_suffix('.zip.bak_before_nature_heroes')}")


if __name__ == "__main__":
    main()
