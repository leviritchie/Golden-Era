from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TOOLS_ROOT = ROOT / "tools"
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))
from homm3_specialization_icon_keys import specialization_icon_key_for_kind
CUSTOM_FACTIONS = ROOT / "custom_factions"
OUTPUT_DIR = CUSTOM_FACTIONS / "hero_overrides"

VCMI_ROOTS = (
    Path(r"C:\Users\<user>\AppData\Roaming\VCMI"),
    ROOT / "vcmi",
)

PORTRAIT_MANIFEST_PATH = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_hero_portraits"
    / "manifest.json"
)

# Backup only when homm3_hero_portraits/manifest.json is missing. Must match portrait slot order
# in tools/extract_homm3_hero_portraits.py (LOD index = homm3_<faction>_hero_N).
FALLBACK_HERO_NAMES = {
    "homm3_stronghold": [
        "Crag Hack",
        "Gurnisson",
        "Jabarkas",
        "Shiva",
        "Yog",
        "Boragus",
        "Oris",
        "Krellion",
        "Tyraxor",
        "Gird",
        "Vey",
        "Gundula",
        "Zubin",
        "Terek",
        "Dessa",
        "Saurug",
        "Kilgor",
        "Zog",
    ],
    "homm3_tower": [
        "Piquedram",
        "Thane",
        "Josephine",
        "Neela",
        "Torosar",
        "Fafner",
        "Rissa",
        "Iona",
        "Astral",
        "Halon",
        "Serena",
        "Daremyth",
        "Theodorus",
        "Solmyr",
        "Cyra",
        "Aine",
        "Dracon",
        "Yog the Wizard",
    ],
}

H3_CLASS_TO_CUSTOM_CLASS = {
    "knight": ("might", "Knight"),
    "cleric": ("magic", "Cleric"),
    "ranger": ("might", "Ranger"),
    "druid": ("magic", "Druid"),
    "alchemist": ("might", "Alchemist"),
    "wizard": ("magic", "Wizard"),
    "demoniac": ("might", "Demoniac"),
    "heretic": ("magic", "Heretic"),
    "deathknight": ("might", "Death Knight"),
    "necromancer": ("magic", "Necromancer"),
    "overlord": ("might", "Overlord"),
    "warlock": ("magic", "Warlock"),
    "barbarian": ("might", "Barbarian"),
    "battlemage": ("magic", "Battle Mage"),
    "beastmaster": ("might", "Beastmaster"),
    "witch": ("magic", "Witch"),
    "planeswalker": ("might", "Planeswalker"),
    "elementalist": ("magic", "Elementalist"),
    "captain": ("might", "Captain"),
    "navigator": ("magic", "Navigator"),
}

H3_SKILL_TO_OLDEN_ERA = {
    "airMagic": "skill_magic_space",
    "archery": "skill_assault",
    "armorer": "skill_protection",
    "artillery": "skill_siege",
    "ballistics": "skill_siege",
    "diplomacy": "skill_diplomacy",
    "eagleEye": "skill_mastery",
    "earthMagic": "skill_magic_primal",
    "estates": "skill_economy",
    "fireMagic": "skill_magic_day",
    "firstAid": "skill_trainer",
    "intelligence": "skill_wisdom",
    "leadership": "skill_leadership",
    "learning": "skill_enlightenment",
    "logistics": "skill_logistic",
    "luck": "skill_luck",
    "mysticism": "skill_wisdom",
    "navigation": "skill_scouting",
    "necromancy": "skill_faction_homm3_necropolis",
    "offence": "skill_assault",
    "pathfinding": "skill_logistic",
    "resistance": "skill_resistance",
    "scholar": "skill_wisdom",
    "scouting": "skill_scouting",
    "sorcery": "skill_sorcery",
    "tactics": "skill_tactics",
    "waterMagic": "skill_magic_night",
    "wisdom": "skill_wisdom",
}

SKILL_LEVELS = {
    "basic": 1,
    "advanced": 2,
    "expert": 3,
}

MASTERFUL_MAGIC_VARIANTS: dict[str, dict[str, str]] = {
    "day_1_magic_healing_water": {"specializationName": "Masterful Healing Water", "specializationDescription": "Starts with Masterful Healing Water."},
    "day_2_magic_sharp_edge": {"specializationName": "Masterful Blessing", "specializationDescription": "Starts with Masterful Blessing."},
    "day_3_magic_haste": {"specializationName": "Masterful Haste", "specializationDescription": "Starts with Masterful Haste."},
    "day_4_magic_favorable_wind": {"specializationName": "Masterful Favorable Winds", "specializationDescription": "Starts with Masterful Favorable Winds."},
    "day_12_magic_radiant_armor": {"specializationName": "Masterful Radiant Armor", "specializationDescription": "Starts with Masterful Radiant Armor. This version costs less mana."},
    "night_1_magic_unnatural_calm": {"specializationName": "Masterful Unnatural Calm", "specializationDescription": "Starts with Masterful Unnatural Calm."},
    "night_2_magic_web": {"specializationName": "Masterful Web", "specializationDescription": "Starts with Masterful Web."},
    "night_3_magic_enlarge_shadow": {"specializationName": "Masterful Enlarge Shadow", "specializationDescription": "Starts with Masterful Enlarge Shadow."},
    "night_7_magic_fatal_decay": {"specializationName": "Masterful Fatal Decay", "specializationDescription": "Starts with Masterful Fatal Decay. This version lasts 5 additional rounds."},
    "night_8_magic_sleep": {"specializationName": "Masterful Sleep", "specializationDescription": "Starts with Masterful Sleep. This version ignores creature-type immunity restrictions."},
    "night_9_magic_twilight": {"specializationName": "Masterful Twilight", "specializationDescription": "Starts with Masterful Twilight."},
    "night_11_magic_vulnerability": {"specializationName": "Masterful Vulnerability", "specializationDescription": "Starts with Masterful Vulnerability."},
    "night_13_magic_berserker": {"specializationName": "Masterful Berserk", "specializationDescription": "Starts with Masterful Berserk."},
    "primal_1_magic_thunderbolt": {"specializationName": "Masterful Lightning Bolt", "specializationDescription": "Starts with Masterful Lightning Bolt. This version can strike up to 2 enemy targets."},
    "primal_2_magic_thick_hide": {"specializationName": "Masterful Thick Hide", "specializationDescription": "Starts with Masterful Thick Hide. This version also reduces ranged damage taken by 10%."},
    "primal_4_magic_fire_globe": {"specializationName": "Masterful Fireball", "specializationDescription": "Starts with Masterful Fireball."},
    "primal_7_magic_wall_of_flame": {"specializationName": "Masterful Firewall", "specializationDescription": "Starts with Masterful Firewall."},
    "primal_12_magic_chain_lightning": {"specializationName": "Masterful Chain Lightning", "specializationDescription": "Starts with Masterful Chain Lightning."},
    "primal_13_magic_avalanche": {"specializationName": "Masterful Circle of Winter", "specializationDescription": "Starts with Masterful Circle of Winter."},
    "space_2_magic_energy_explosion": {"specializationName": "Masterful Energy Explosion", "specializationDescription": "Starts with Masterful Energy Explosion. This version uses a larger blast area based on Focus Charges."},
    "space_3_magic_energyze": {"specializationName": "Masterful Energize", "specializationDescription": "Starts with Masterful Energize. This version grants Focus Charges for less mana."},
    "space_4_magic_optical_illusion": {"specializationName": "Masterful Optical Illusion", "specializationDescription": "Starts with Masterful Optical Illusion. This version also gives the target 25% spell-damage resistance."},
    "space_5_magic_trap_jaws": {"specializationName": "Masterful Temporal Spheres", "specializationDescription": "Starts with Masterful Temporal Spheres. This version places one additional trap."},
    "space_7_magic_shackles": {"specializationName": "Masterful Shackles", "specializationDescription": "Starts with Masterful Shackles. This version costs less mana."},
    "space_10_magic_mirror_copy": {"specializationName": "Masterful Mirror Copy", "specializationDescription": "Starts with Masterful Mirror Copy."},
    "space_12_magic_rewind": {"specializationName": "Masterful Rewind Life", "specializationDescription": "Starts with Masterful Rewind Life."},
    "space_13_magic_black_hole": {"specializationName": "Masterful Black Hole", "specializationDescription": "Starts with Masterful Black Hole."},
    "space_14_magic_doreaths_tide": {"specializationName": "Masterful Doreath's Tide", "specializationDescription": "Starts with Masterful Doreath's Tide."},
}

MASTERFUL_MAGIC_HERO_ASSIGNMENTS: dict[tuple[str, int], str] = {
    ("homm3_castle", 10): "day_2_magic_sharp_edge",
    ("homm3_castle", 9): "day_1_magic_healing_water",
    ("homm3_castle", 11): "night_1_magic_unnatural_calm",
    ("homm3_castle", 12): "primal_13_magic_avalanche",
    ("homm3_castle", 15): "space_14_magic_doreaths_tide",
    ("homm3_conflux", 9): "primal_7_magic_wall_of_flame",
    ("homm3_conflux", 10): "day_3_magic_haste",
    ("homm3_conflux", 11): "primal_1_magic_thunderbolt",
    ("homm3_conflux", 12): "night_3_magic_enlarge_shadow",
    ("homm3_conflux", 13): "day_2_magic_sharp_edge",
    ("homm3_conflux", 14): "night_11_magic_vulnerability",
    ("homm3_cove", 10): "space_10_magic_mirror_copy",
    ("homm3_cove", 13): "primal_4_magic_fire_globe",
    ("homm3_cove", 14): "night_9_magic_twilight",
    ("homm3_cove", 15): "day_1_magic_healing_water",
    ("homm3_cove", 16): "space_4_magic_optical_illusion",
    ("homm3_cove", 17): "night_9_magic_twilight",
    ("homm3_dungeon", 9): "space_12_magic_rewind",
    ("homm3_dungeon", 12): "space_12_magic_rewind",
    ("homm3_dungeon", 14): "space_13_magic_black_hole",
    ("homm3_fortress", 9): "night_1_magic_unnatural_calm",
    ("homm3_fortress", 12): "day_1_magic_healing_water",
    ("homm3_fortress", 13): "night_3_magic_enlarge_shadow",
    ("homm3_inferno", 10): "space_2_magic_energy_explosion",
    ("homm3_inferno", 12): "night_1_magic_unnatural_calm",
    ("homm3_inferno", 14): "day_2_magic_sharp_edge",
    ("homm3_inferno", 16): "primal_4_magic_fire_globe",
    ("homm3_inferno", 18): "space_12_magic_rewind",
    ("homm3_necropolis", 9): "night_7_magic_fatal_decay",
    ("homm3_necropolis", 10): "space_13_magic_black_hole",
    ("homm3_necropolis", 13): "space_12_magic_rewind",
    ("homm3_rampart", 10): "day_1_magic_healing_water",
    ("homm3_rampart", 12): "day_1_magic_healing_water",
    ("homm3_rampart", 15): "primal_13_magic_avalanche",
    ("homm3_stronghold", 14): "day_3_magic_haste",
    ("homm3_tower", 9): "night_13_magic_berserker",
    ("homm3_tower", 14): "primal_12_magic_chain_lightning",
    ("homm3_tower", 15): "day_3_magic_haste",
    ("homm3_tower", 16): "space_3_magic_energyze",
}

MASTERFUL_MAGIC_SOURCE_KEYS: dict[tuple[str, int], str] = {
    ("homm3_castle", 9): "skill:firstAid",
    ("homm3_cove", 17): "spell:forgetfulness",
    ("homm3_fortress", 12): "skill:firstAid",
    ("homm3_rampart", 12): "skill:firstAid",
    ("homm3_stronghold", 13): "spell:precision",
}

H3_HERO_SPECIALTIES: dict[tuple[str, int], tuple[str, str]] = {
    ("homm3_castle", 1): ("skill", "archery"), ("homm3_castle", 2): ("creature", "h3_archer"), ("homm3_castle", 3): ("creature", "h3_griffin"), ("homm3_castle", 4): ("skill", "navigation"), ("homm3_castle", 5): ("skill", "estates"), ("homm3_castle", 6): ("creature", "h3_swordsman"), ("homm3_castle", 7): ("skill", "ballista"), ("homm3_castle", 8): ("creature", "h3_cavalier"), ("homm3_castle", 9): ("skill", "firstAid"), ("homm3_castle", 13): ("creature", "h3_monk"), ("homm3_castle", 14): ("skill", "eagleEye"), ("homm3_castle", 16): ("skill", "gold"), ("homm3_castle", 17): ("creature", "h3_swordsman"), ("homm3_castle", 18): ("creature", "h3_swordsman"),
    ("homm3_conflux", 1): ("creature", "h3_psychic_elemental"), ("homm3_conflux", 2): ("creature", "h3_earth_elemental"), ("homm3_conflux", 3): ("creature", "h3_fire_elemental"), ("homm3_conflux", 4): ("creature", "h3_water_elemental"), ("homm3_conflux", 5): ("creature", "h3_psychic_elemental"), ("homm3_conflux", 6): ("creature", "h3_earth_elemental"), ("homm3_conflux", 7): ("creature", "h3_fire_elemental"), ("homm3_conflux", 8): ("creature", "h3_water_elemental"), ("homm3_conflux", 15): ("skill", "gold"), ("homm3_conflux", 16): ("skill", "gold"),
    ("homm3_cove", 1): ("skill", "offence"), ("homm3_cove", 2): ("skill", "artillery"), ("homm3_cove", 3): ("creature", "h3_stormbird"), ("homm3_cove", 4): ("skill", "navigation"), ("homm3_cove", 5): ("creature", "h3_crew_mate"), ("homm3_cove", 6): ("skill", "gold"), ("homm3_cove", 7): ("creature", "h3_pirate"), ("homm3_cove", 8): ("creature", "h3_nymph"), ("homm3_cove", 9): ("creature", "h3_sea_witch"), ("homm3_cove", 11): ("skill", "sorcery"), ("homm3_cove", 12): ("skill", "crystal"), ("homm3_cove", 18): ("skill", "scouting"),
    ("homm3_dungeon", 1): ("creature", "h3_harpy"), ("homm3_dungeon", 2): ("skill", "ballista"), ("homm3_dungeon", 3): ("creature", "h3_minotaur"), ("homm3_dungeon", 4): ("creature", "h3_beholder"), ("homm3_dungeon", 5): ("skill", "gold"), ("homm3_dungeon", 6): ("skill", "logistics"), ("homm3_dungeon", 7): ("creature", "h3_manticore"), ("homm3_dungeon", 8): ("creature", "h3_troglodyte"), ("homm3_dungeon", 10): ("skill", "mysticism"), ("homm3_dungeon", 11): ("skill", "sorcery"), ("homm3_dungeon", 13): ("skill", "eagleEye"), ("homm3_dungeon", 15): ("skill", "crystal"), ("homm3_dungeon", 16): ("skill", "stone"), ("homm3_dungeon", 17): ("creature", "h3_red_dragon"), ("homm3_dungeon", 18): ("creature", "h3_red_dragon"),
    ("homm3_fortress", 1): ("creature", "h3_basilisk"), ("homm3_fortress", 2): ("creature", "h3_gnoll"), ("homm3_fortress", 3): ("creature", "h3_lizardman"), ("homm3_fortress", 4): ("skill", "armorer"), ("homm3_fortress", 5): ("creature", "h3_gorgon"), ("homm3_fortress", 6): ("creature", "h3_serpent_fly"), ("homm3_fortress", 7): ("skill", "ballista"), ("homm3_fortress", 8): ("creature", "h3_wyvern"), ("homm3_fortress", 10): ("skill", "mysticism"), ("homm3_fortress", 11): ("skill", "navigation"), ("homm3_fortress", 12): ("skill", "firstAid"), ("homm3_fortress", 14): ("skill", "sorcery"), ("homm3_fortress", 15): ("skill", "intelligence"), ("homm3_fortress", 16): ("skill", "eagleEye"), ("homm3_fortress", 17): ("skill", "sorcery"), ("homm3_fortress", 18): ("skill", "mysticism"),
    ("homm3_inferno", 1): ("creature", "h3_hell_hound"), ("homm3_inferno", 2): ("creature", "h3_efreeti"), ("homm3_inferno", 3): ("creature", "h3_demon"), ("homm3_inferno", 4): ("creature", "h3_imp"), ("homm3_inferno", 5): ("skill", "gold"), ("homm3_inferno", 6): ("creature", "h3_gog"), ("homm3_inferno", 7): ("skill", "ballista"), ("homm3_inferno", 8): ("creature", "h3_pit_fiend"), ("homm3_inferno", 9): ("skill", "intelligence"), ("homm3_inferno", 11): ("skill", "mysticism"), ("homm3_inferno", 13): ("skill", "sulfur"), ("homm3_inferno", 15): ("skill", "sorcery"), ("homm3_inferno", 17): ("creature", "h3_devil"),
    ("homm3_necropolis", 1): ("creature", "h3_walking_dead"), ("homm3_necropolis", 2): ("creature", "h3_vampire"), ("homm3_necropolis", 3): ("creature", "h3_lich"), ("homm3_necropolis", 4): ("creature", "h3_wight"), ("homm3_necropolis", 5): ("creature", "h3_black_knight"), ("homm3_necropolis", 6): ("skill", "necromancy"), ("homm3_necropolis", 7): ("skill", "gold"), ("homm3_necropolis", 8): ("creature", "h3_skeleton"), ("homm3_necropolis", 11): ("skill", "sorcery"), ("homm3_necropolis", 12): ("skill", "eagleEye"), ("homm3_necropolis", 14): ("skill", "stone"), ("homm3_necropolis", 15): ("skill", "necromancy"), ("homm3_necropolis", 16): ("skill", "mysticism"), ("homm3_necropolis", 17): ("creature", "h3_lich"), ("homm3_necropolis", 18): ("creature", "h3_black_knight"),
    ("homm3_rampart", 1): ("skill", "armorer"), ("homm3_rampart", 2): ("creature", "h3_dwarf"), ("homm3_rampart", 3): ("skill", "gold"), ("homm3_rampart", 4): ("creature", "h3_dendroid_guard"), ("homm3_rampart", 5): ("skill", "resistance"), ("homm3_rampart", 6): ("creature", "h3_wood_elf"), ("homm3_rampart", 7): ("creature", "h3_unicorn"), ("homm3_rampart", 8): ("skill", "logistics"), ("homm3_rampart", 9): ("skill", "slayer"), ("homm3_rampart", 11): ("skill", "intelligence"), ("homm3_rampart", 12): ("skill", "firstAid"), ("homm3_rampart", 13): ("skill", "eagleEye"), ("homm3_rampart", 14): ("skill", "fortune"), ("homm3_rampart", 16): ("creature", "h3_pegasus"), ("homm3_rampart", 17): ("creature", "h3_wood_elf"), ("homm3_rampart", 18): ("creature", "h3_unicorn"),
    ("homm3_stronghold", 1): ("skill", "offence"),
    ("homm3_stronghold", 2): ("skill", "ballista"),
    ("homm3_stronghold", 3): ("creature", "h3_orc"),
    ("homm3_stronghold", 4): ("creature", "h3_roc"),
    ("homm3_stronghold", 5): ("creature", "h3_cyclops"),
    ("homm3_stronghold", 6): ("creature", "h3_ogre"),
    ("homm3_stronghold", 7): ("skill", "eagleEye"),
    ("homm3_stronghold", 8): ("creature", "h3_ogre"),
    ("homm3_stronghold", 9): ("creature", "h3_wolf_rider"),
    ("homm3_stronghold", 10): ("skill", "sorcery"),
    ("homm3_stronghold", 11): ("creature", "h3_ogre"),
    ("homm3_stronghold", 12): ("skill", "offence"),
    ("homm3_stronghold", 13): ("skill", "artillery"),
    ("homm3_stronghold", 14): ("skill", "learning"),
    ("homm3_stronghold", 15): ("skill", "logistics"),
    ("homm3_stronghold", 16): ("skill", "gem"),
    ("homm3_stronghold", 17): ("creature", "h3_behemoth"),
    ("homm3_stronghold", 18): ("creature", "h3_ogre"),
    ("homm3_tower", 1): ("creature", "h3_gargoyle"), ("homm3_tower", 2): ("creature", "h3_genie"), ("homm3_tower", 3): ("creature", "h3_golem"), ("homm3_tower", 4): ("skill", "armorer"), ("homm3_tower", 5): ("skill", "ballista"), ("homm3_tower", 6): ("creature", "h3_naga"), ("homm3_tower", 7): ("skill", "mercury"), ("homm3_tower", 8): ("creature", "h3_genie"), ("homm3_tower", 10): ("skill", "mysticism"), ("homm3_tower", 11): ("skill", "eagleEye"), ("homm3_tower", 12): ("skill", "fortune"), ("homm3_tower", 13): ("creature", "h3_mage"), ("homm3_tower", 17): ("creature", "h3_mage"), ("homm3_tower", 18): ("skill", "intelligence"),
}


def player_facing_specialization_description(description: str) -> str:
    """Keep generated localization text in gameplay terms, not design-rationale terms."""
    text = description.strip()
    replacements = (
        ("Proxies the source war-machine specialty through Olden Era Heroic Strike scaling.", "Improves Heroic Strike at battle start and as the hero gains levels."),
        ("Proxies the source Ballista specialty through Olden Era Heroic Strike scaling.", "Improves Heroic Strike at battle start and as the hero gains levels."),
        ("Proxies the source First Aid specialty through Masterful Healing Water.", "Starts with Masterful Healing Water."),
        ("Improves movement and scouting reach, preserving the source water-mobility specialty as an Olden Era travel specialty.", "Increases adventure movement and view radius as the hero gains levels."),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    rationale_patterns = (
        r"\s*This preserves the hero's HoMM3 source creature specialty as an explicit changed Olden Era design\.",
        r"\s*This preserves the hero's HoMM3 source specialty as an explicit changed Olden Era design\.",
        r"\s*This is an explicit changed design, not a claim of exact HoMM3 source-specialty parity\.",
        r"\s*This is the Olden Era masterful equivalent for [^.]+\.",
        r"\s*and is the Olden Era masterful equivalent for [^.]+\.",
    )
    for pattern in rationale_patterns:
        text = re.sub(pattern, ".", text)
    text = re.sub(r"\s+", " ", text)
    text = text.replace("..", ".")
    return text.strip()


def masterful_magic_special_sid(base_sid: str) -> str:
    return base_sid + "_special"


def masterful_spell_specialization_description(variant: dict[str, str]) -> str:
    name = variant["specializationName"]
    description = player_facing_specialization_description(variant["specializationDescription"])
    base_text = f"Starts with {name}. It casts as one tier stronger."
    starts_with = f"Starts with {name}."
    if description.startswith(starts_with):
        suffix = description[len(starts_with):].strip()
        return base_text + (" " + suffix if suffix else "")
    return base_text


def masterful_spell_specialization_override(faction_sid: str, hero_sid: str, index: int) -> dict[str, Any] | None:
    spell_sid = MASTERFUL_MAGIC_HERO_ASSIGNMENTS.get((faction_sid, index))
    if not spell_sid:
        return None
    variant = MASTERFUL_MAGIC_VARIANTS[spell_sid]
    special_sid = masterful_magic_special_sid(spell_sid)
    return {
        "mode": "changed",
        "sourceSpecId": f"{hero_sid}_olden_era_masterful_{spell_sid}",
        "nameText": variant["specializationName"],
        "descriptionText": masterful_spell_specialization_description(variant),
        "iconKey": spell_sid,
        "bonuses": [{"type": "heroMagicReplace", "parameters": [spell_sid, special_sid]}],
        "changeDisposition": "explicit_masterful_spell_variant",
        "sourceSpecialtyKey": MASTERFUL_MAGIC_SOURCE_KEYS.get((faction_sid, index), f"spell:{spell_sid}"),
        "masterfulSpellBaseSid": spell_sid,
        "masterfulSpellSpecialSid": special_sid,
    }


H3_CREATURE_TO_CUSTOM_SID = {
    "airElemental": "h3_air_elemental",
    "archer": "h3_archer",
    "basilisk": "h3_basilisk",
    "centaur": "h3_centaur",
    "corsair": "h3_corsair",
    "crewmate": "h3_crew_mate",
    "dwarf": "h3_dwarf",
    "earthElemental": "h3_earth_elemental",
    "evilEye": "h3_beholder",
    "fireElemental": "h3_fire_elemental",
    "gargoyle": "h3_gargoyle",
    "gnoll": "h3_gnoll",
    "gremlin": "h3_gremlin",
    "goblin": "h3_goblin",
    "goblinWolfRider": "h3_wolf_rider",
    "gog": "h3_gog",
    "golem": "h3_golem",
    "griffin": "h3_griffin",
    "harpy": "h3_harpy",
    "hellHound": "h3_hell_hound",
    "imp": "h3_imp",
    "lizardman": "h3_lizardman",
    "nix": "h3_nix",
    "nymph": "h3_nymph",
    "ogre": "h3_ogre",
    "orc": "h3_orc",
    "pikeman": "h3_pikeman",
    "pirate": "h3_pirate",
    "pixie": "h3_pixie",
    "seadog": "h3_sea_dog",
    "serpentFly": "h3_serpent_fly",
    "skeleton": "h3_skeleton",
    "stoneGargoyle": "h3_gargoyle",
    "stormbird": "h3_stormbird",
    "troglodyte": "h3_troglodyte",
    "walkingDead": "h3_walking_dead",
    "waterElemental": "h3_water_elemental",
    "wight": "h3_wight",
    "woodElf": "h3_wood_elf",
}

# Base HoMM3/HotA starter-army rows. VCMI's base hero JSON carries classes and
# skills but usually omits army rows, while Cove and some HotA-added heroes do
# include exact `army` rows locally. Keep this table as the no-fallback source
# for base-faction heroes whose VCMI row has no explicit army. War machines are
# intentionally omitted because HeroConfig.startSquad only carries unit stacks.
BASE_HOTA_START_ARMIES: dict[str, dict[str, list[dict[str, int | str]]]] = {
    "homm3_castle": {
        **{name: [{"creature": "pikeman", "min": 10, "max": 20}, {"creature": "archer", "min": 4, "max": 7}, {"creature": "griffin", "min": 2, "max": 3}] for name in ["Orrin", "Lord Haart", "Sorsha", "Sylvia", "Tyris", "Catherine", "Roland", "Adela", "Cuthbert", "Adelaide", "Ingham", "Sanya", "Loynis", "Caitlin"]},
        "Valeska": [{"creature": "archer", "min": 4, "max": 7}] * 3,
        "Edric": [{"creature": "pikeman", "min": 10, "max": 20}, {"creature": "griffin", "min": 2, "max": 3}, {"creature": "griffin", "min": 2, "max": 3}],
        "Christian": [{"creature": "pikeman", "min": 10, "max": 20}, {"creature": "griffin", "min": 2, "max": 3}],
        "Rion": [{"creature": "pikeman", "min": 10, "max": 20}, {"creature": "griffin", "min": 2, "max": 3}],
    },
    "homm3_rampart": {
        **{name: [{"creature": "centaur", "min": 12, "max": 24}, {"creature": "dwarf", "min": 3, "max": 5}, {"creature": "woodElf", "min": 3, "max": 6}] for name in ["Mephala", "Jenova", "Ryland", "Thorgrim", "Clancy", "Kyrre", "Coronius", "Uland", "Elleshar", "Malcom", "Melodia", "Agar", "Alagar", "Aeris", "Ordwald"]},
        "Ufretin": [{"creature": "dwarf", "min": 3, "max": 5}] * 3,
        "Ivor": [{"creature": "centaur", "min": 12, "max": 24}, {"creature": "woodElf", "min": 3, "max": 6}, {"creature": "woodElf", "min": 3, "max": 6}],
        "Gem": [{"creature": "centaur", "min": 12, "max": 24}, {"creature": "woodElf", "min": 3, "max": 6}],
        "Gelu": [{"creature": "centaur", "min": 12, "max": 24}, {"creature": "woodElf", "min": 3, "max": 6}, {"creature": "woodElf", "min": 3, "max": 6}],
    },
    "homm3_tower": {
        **{name: [{"creature": "gremlin", "min": 30, "max": 40}, {"creature": "stoneGargoyle", "min": 3, "max": 5}, {"creature": "golem", "min": 2, "max": 3}] for name in ["Thane", "Neela", "Fafner", "Rissa", "Iona", "Astral", "Halon", "Serena", "Daremyth", "Theodorus", "Solmyr", "Cyra", "Aine", "Dracon", "Yog the Wizard"]},
        "Piquedram": [{"creature": "stoneGargoyle", "min": 3, "max": 5}] * 3,
        "Josephine": [{"creature": "gremlin", "min": 30, "max": 40}, {"creature": "golem", "min": 2, "max": 3}, {"creature": "golem", "min": 2, "max": 3}],
        "Torosar": [{"creature": "gremlin", "min": 30, "max": 40}, {"creature": "golem", "min": 2, "max": 3}],
    },
    "homm3_inferno": {
        **{name: [{"creature": "imp", "min": 15, "max": 25}, {"creature": "gog", "min": 4, "max": 7}, {"creature": "hellHound", "min": 3, "max": 4}] for name in ["Rashka", "Marius", "Octavia", "Nymus", "Ayden", "Xyron", "Axsis", "Olema", "Calid", "Ash", "Zydar", "Xarfax", "Xeron", "Miseria"]},
        "Ignatius": [{"creature": "imp", "min": 15, "max": 25}] * 3,
        "Calh": [{"creature": "gog", "min": 4, "max": 7}] * 3,
        "Fiona": [{"creature": "imp", "min": 15, "max": 25}, {"creature": "hellHound", "min": 3, "max": 4}, {"creature": "hellHound", "min": 3, "max": 4}],
        "Pyre": [{"creature": "imp", "min": 15, "max": 25}, {"creature": "hellHound", "min": 3, "max": 4}],
    },
    "homm3_necropolis": {
        **{name: [{"creature": "skeleton", "min": 20, "max": 30}, {"creature": "walkingDead", "min": 4, "max": 6}, {"creature": "wight", "min": 4, "max": 6}] for name in ["Vokial", "Moandor", "Tamika", "Isra", "Clavius", "Septienna", "Aislinn", "Sandro", "Nimbus", "Thant", "Xsi", "Vidomina", "Nagash", "Finneas", "Haart Lich"]},
        "Galthran": [{"creature": "skeleton", "min": 20, "max": 30}] * 3,
        "Straker": [{"creature": "walkingDead", "min": 4, "max": 6}] * 3,
        "Charna": [{"creature": "skeleton", "min": 20, "max": 30}, {"creature": "wight", "min": 4, "max": 6}, {"creature": "wight", "min": 4, "max": 6}],
    },
    "homm3_dungeon": {
        **{name: [{"creature": "troglodyte", "min": 30, "max": 40}, {"creature": "harpy", "min": 4, "max": 6}, {"creature": "evilEye", "min": 3, "max": 4}] for name in ["Dace", "Damacon", "Gunnar", "Synca", "Alamar", "Jaegar", "Malekith", "Jeddite", "Geon", "Deemer", "Sephinroth", "Darkstorn", "Mutare", "Mutare Drake"]},
        "Shakti": [{"creature": "troglodyte", "min": 30, "max": 40}] * 3,
        "Lorelei": [{"creature": "harpy", "min": 4, "max": 6}] * 3,
        "Ajit": [{"creature": "troglodyte", "min": 30, "max": 40}, {"creature": "evilEye", "min": 3, "max": 4}, {"creature": "evilEye", "min": 3, "max": 4}],
        "Arlach": [{"creature": "troglodyte", "min": 30, "max": 40}, {"creature": "evilEye", "min": 3, "max": 4}],
    },
    "homm3_stronghold": {
        **{name: [{"creature": "goblin", "min": 15, "max": 25}, {"creature": "goblinWolfRider", "min": 5, "max": 7}, {"creature": "orc", "min": 4, "max": 6}] for name in ["Yog", "Shiva", "Krellion", "Crag Hack", "Gird", "Vey", "Dessa", "Terek", "Zubin", "Gundula", "Oris", "Saurug", "Kilgor", "Zog"]},
        "Gretchin": [{"creature": "goblin", "min": 15, "max": 25}] * 3,
        "Tyraxor": [{"creature": "goblinWolfRider", "min": 5, "max": 7}] * 3,
        "Jabarkas": [{"creature": "goblin", "min": 15, "max": 25}, {"creature": "orc", "min": 4, "max": 6}, {"creature": "orc", "min": 4, "max": 6}],
        "Gurnisson": [{"creature": "goblin", "min": 15, "max": 25}, {"creature": "orc", "min": 4, "max": 6}],
    },
    "homm3_fortress": {
        **{name: [{"creature": "gnoll", "min": 10, "max": 20}, {"creature": "lizardman", "min": 4, "max": 7}, {"creature": "serpentFly", "min": 2, "max": 4}] for name in ["Tazar", "Alkin", "Broghild", "Mirlanda", "Rosic", "Voy", "Merist", "Styg", "Andra", "Tiva", "Adrienne", "Kinkeria"]},
        "Drakon": [{"creature": "gnoll", "min": 10, "max": 20}] * 3,
        "Wystan": [{"creature": "lizardman", "min": 4, "max": 7}] * 3,
        "Korbac": [{"creature": "gnoll", "min": 10, "max": 20}, {"creature": "serpentFly", "min": 2, "max": 4}, {"creature": "serpentFly", "min": 2, "max": 4}],
        "Bron": [{"creature": "gnoll", "min": 10, "max": 20}, {"creature": "serpentFly", "min": 2, "max": 4}, {"creature": "basilisk", "min": 4, "max": 7}],
        "Gerwulf": [{"creature": "gnoll", "min": 10, "max": 20}, {"creature": "serpentFly", "min": 2, "max": 4}],
        "Verdish": [{"creature": "gnoll", "min": 10, "max": 20}, {"creature": "serpentFly", "min": 2, "max": 4}],
    },
    "homm3_conflux": {
        **{name: [{"creature": "pixie", "min": 15, "max": 25}, {"creature": "airElemental", "min": 3, "max": 5}, {"creature": "waterElemental", "min": 2, "max": 3}] for name in ["Thunar", "Ignissa", "Erdamon", "Fiur", "Luna", "Brissa", "Labetha", "Ciele", "Inteus", "Aenain", "Gelare", "Grindan"]},
        "Pasis": [{"creature": "pixie", "min": 15, "max": 25}, {"creature": "airElemental", "min": 3, "max": 5}, {"creature": "airElemental", "min": 2, "max": 3}],
        "Monere": [{"creature": "pixie", "min": 15, "max": 25}, {"creature": "airElemental", "min": 3, "max": 5}, {"creature": "airElemental", "min": 2, "max": 3}],
        "Lacus": [{"creature": "pixie", "min": 15, "max": 25}, {"creature": "waterElemental", "min": 3, "max": 5}, {"creature": "waterElemental", "min": 1, "max": 2}],
        "Kalt": [{"creature": "pixie", "min": 15, "max": 25}, {"creature": "waterElemental", "min": 3, "max": 5}, {"creature": "waterElemental", "min": 1, "max": 2}],
    },
}


def strip_json_comments(text: str) -> str:
    text = re.sub(r"//.*", "", text)
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def read_jsonc(path: Path) -> Any:
    return json.loads(strip_json_comments(path.read_text(encoding="utf-8-sig")))


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def load_vcmi_heroes() -> dict[str, dict[str, Any]]:
    heroes: dict[str, dict[str, Any]] = {}
    for root in VCMI_ROOTS:
        if not root.exists():
            continue
        candidates = list((root / "config" / "heroes").glob("*.json")) if (root / "config" / "heroes").exists() else []
        candidates += list(root.glob("Mods/hota/mods/cove/Content/config/hota/cove/heroes/*.json"))
        candidates += list(root.glob("Mods/hota/mods/heroes/Content/config/*/heroes/*.json"))
        candidates += list(root.glob("Mods/third-upgrades/Mods/tow-comp/content/config/heroes/*.json"))
        candidates += list(root.glob("Mods/third-upgrades/Mods/tow-comp/content/config/heroes/*/*.json"))
        for path in candidates:
            if path.name.startswith("portraits"):
                continue
            try:
                data = read_jsonc(path)
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            if "class" in data and ("skills" in data or "army" in data):
                heroes.setdefault(normalize_name(path.stem), data)
                text_name = ((data.get("texts") or {}).get("name") if isinstance(data.get("texts"), dict) else None)
                if isinstance(text_name, str) and text_name.strip():
                    heroes.setdefault(normalize_name(text_name), data)
                continue
            for key, value in data.items():
                if isinstance(value, dict) and ("class" in value or "skills" in value):
                    heroes.setdefault(normalize_name(key), value)
                    text_name = ((value.get("texts") or {}).get("name") if isinstance(value.get("texts"), dict) else None)
                    if isinstance(text_name, str) and text_name.strip():
                        heroes.setdefault(normalize_name(text_name), value)
    return heroes


def portrait_manifest_hero_names(faction_sid: str) -> list[str] | None:
    if not PORTRAIT_MANIFEST_PATH.exists():
        return None
    entries = json.loads(PORTRAIT_MANIFEST_PATH.read_text(encoding="utf-8-sig")).get("entries") or {}
    names: list[str] = []
    index = 1
    while True:
        row = entries.get(f"{faction_sid}_hero_{index}")
        if not isinstance(row, dict):
            break
        names.append(str(row.get("name") or f"Hero {index}"))
        index += 1
    return names or None


def manifest_hero_names(manifest: dict[str, Any], faction_sid: str) -> list[str]:
    heroes = manifest.get("heroes") or {}
    names = heroes.get("names")
    if isinstance(names, list) and names:
        return [str(name) for name in names]
    portrait_names = portrait_manifest_hero_names(faction_sid)
    if portrait_names:
        return portrait_names
    fallback = FALLBACK_HERO_NAMES.get(faction_sid)
    if fallback:
        return list(fallback)
    count = int(heroes.get("count") or 18)
    return [f"Hero {index}" for index in range(1, count + 1)]


def manifest_unit_base_sids(manifest: dict[str, Any]) -> list[str]:
    return [str(line.get("baseSid")) for line in manifest.get("unitLines", []) if isinstance(line, dict) and line.get("baseSid")]


def default_start_squad(manifest: dict[str, Any]) -> list[dict[str, int | str]]:
    units = manifest_unit_base_sids(manifest)
    if len(units) < 3:
        return []
    return [
        {"sid": units[0], "min": 14, "max": 20},
        {"sid": units[1], "min": 8, "max": 12},
        {"sid": units[2], "min": 3, "max": 5},
    ]


def manifest_unit_variants(manifest: dict[str, Any]) -> list[str]:
    variants = manifest.get("unitVariants")
    if isinstance(variants, list) and variants:
        return [str(value) for value in variants]
    return ["", "_upg", "_upg_alt"]


def manifest_unit_sid_for_variant(line: dict[str, Any], suffix: str) -> str:
    return f"{line['baseSid']}{suffix}"


def manifest_unit_line_name(line: dict[str, Any]) -> str:
    names = line.get("names")
    if isinstance(names, list) and names and isinstance(names[0], str):
        return names[0]
    return str(line.get("baseSid") or "Unit").replace("_", " ").title()


def creature_specialization_bonuses(manifest: dict[str, Any], line: dict[str, Any]) -> list[dict[str, Any]]:
    variants = manifest_unit_variants(manifest)
    receivers = [manifest_unit_sid_for_variant(line, suffix) for suffix in variants]
    base_sid = manifest_unit_sid_for_variant(line, variants[0] if variants else "")
    return [
        {"type": "cityUnitsIncrement", "parameters": [base_sid, "1"]},
        {"type": "unitStat", "receivers": receivers, "parameters": ["speed", "1"]},
        {"type": "unitStat", "receivers": receivers, "parameters": ["initiative", "1"]},
        {"type": "unitStat", "receivers": receivers, "parameters": ["hpPerc", "0.2"]},
        {
            "type": "unitStat",
            "receivers": receivers,
            "parameters": ["offence", "0"],
            "upgrade": {"increment": 1, "levelStep": 3},
        },
        {
            "type": "unitStat",
            "receivers": receivers,
            "parameters": ["defence", "0"],
            "upgrade": {"increment": 1, "levelStep": 3},
        },
    ]


def hero_profile_pattern(index: int) -> tuple[str, int | None]:
    patterns: tuple[tuple[str, int | None], ...] = (
        ("logistics", None),
        ("scouting", None),
        ("creature", 0),
        ("creature", 1),
        ("leadership", None),
        ("estates", None),
        ("creature", 2),
        ("fortune", None),
        ("sorcery", None),
        ("mysticism", None),
        ("creature", 3),
        ("offense", None),
        ("creature", 4),
        ("pathfinding", None),
        ("creature", 5),
        ("armorer", None),
        ("creature", 6),
        ("tactics", None),
    )
    return patterns[(index - 1) % len(patterns)]


def source_creature_specialization_override(manifest: dict[str, Any], hero_sid: str, index: int, base_sid: str) -> dict[str, Any]:
    unit_lines = [line for line in manifest.get("unitLines", []) if isinstance(line, dict) and line.get("baseSid")]
    line = next((line for line in unit_lines if line.get("baseSid") == base_sid), None)
    if line is None:
        raise ValueError(f"{hero_sid}: source creature specialty {base_sid!r} has no custom unit line")
    unit_name = manifest_unit_line_name(line)
    return {
        "mode": "changed",
        "sourceSpecId": f"{hero_sid}_source_{base_sid}_specialist",
        "nameText": f"{unit_name} Specialist",
        "descriptionText": f"{unit_name} creatures and their upgrades gain extra weekly growth, Speed, Initiative, Health, Attack, and Defense while this hero leads them.",
        "iconKey": base_sid,
        "bonuses": creature_specialization_bonuses(manifest, line),
        "changeDisposition": "explicit_changed_olden_era_specialist",
        "sourceSpecialtyKey": f"creature:{base_sid}",
    }


def skill_specialization_profiles(kind: str) -> tuple[str, str, list[dict[str, Any]]]:
    profiles: dict[str, tuple[str, str, list[dict[str, Any]]]] = {
        "archery": ("Archery", "Improves ranged and shooting attack damage for the hero's army.", [{"type": "unitStat", "parameters": ["modifierSet", "outDmgMods", "range_attack", "0.10"], "upgrade": {"increment": 0.01, "levelStep": 2}}, {"type": "unitStat", "parameters": ["modifierSet", "outDmgMods", "shoot_attack", "0.10"], "upgrade": {"increment": 0.01, "levelStep": 2}}]),
        "armorer": ("Armorer", "Reduces incoming basic and ranged attack damage for the hero's army.", [{"type": "unitStat", "parameters": ["modifierSet", "inDmgMods", "basic_attack", "-0.10"], "upgrade": {"increment": -0.01, "levelStep": 2}}]),
        "artillery": ("Artillery", "Improves ranged and shooting attack damage for the hero's army.", [{"type": "unitStat", "parameters": ["modifierSet", "outDmgMods", "range_attack", "0.10"], "upgrade": {"increment": 0.01, "levelStep": 2}}, {"type": "unitStat", "parameters": ["modifierSet", "outDmgMods", "shoot_attack", "0.10"], "upgrade": {"increment": 0.01, "levelStep": 2}}]),
        "ballista": ("Ballista", "Improves Heroic Strike at battle start and as the hero gains levels.", [{"type": "battleSubskillBonus", "parameters": ["hero_ability", "specializations_skill_warrior_ability_base_bonus"]}, {"activationLevel": 5, "type": "battleSubskillBonus", "parameters": ["hero_ability", "specializations_skill_warrior_ability_level_bonus"]}, {"activationLevel": 10, "type": "battleSubskillBonus", "parameters": ["hero_ability", "specializations_skill_warrior_ability_level_bonus"]}]),
        "crystal": ("Crystal", "Generates additional crystals each day.", [{"type": "sideRes", "parameters": ["crystals", "1"], "upgrade": {"increment": 1, "levelStep": 7}}]),
        "eagleEye": ("Eagle Eye", "Improves spell pressure and magical awareness in combat.", [{"type": "heroStat", "parameters": ["magicAttackPerBonus", "0.06"], "upgrade": {"increment": 0.01, "levelStep": 3}}, {"type": "heroStat", "parameters": ["viewRadius", "1"]}]),
        "estates": ("Estates", "Generates additional gold each day, increasing as the hero gains levels.", [{"type": "sideRes", "parameters": ["gold", "500"], "upgrade": {"increment": 100, "levelStep": 3}}]),
        "firstAid": ("First Aid", "Starts with Masterful Healing Water.", [{"type": "heroMagicReplace", "parameters": ["day_1_magic_healing_water", "day_1_magic_healing_water_special"]}]),
        "fortune": ("Fortune", "Improves army Luck and increases the chance of critical hits as the hero gains levels.", [{"type": "heroStat", "parameters": ["luck", "1"]}, {"type": "unitStat", "parameters": ["critChanceModifier", "0.02"], "upgrade": {"increment": 0.01, "levelStep": 4}}]),
        "gem": ("Gems", "Generates additional gemstones each day.", [{"type": "sideRes", "parameters": ["gemstones", "1"], "upgrade": {"increment": 1, "levelStep": 7}}]),
        "gold": ("Gold", "Generates additional gold each day.", [{"type": "sideRes", "parameters": ["gold", "350"], "upgrade": {"increment": 50, "levelStep": 5}}]),
        "intelligence": ("Intelligence", "Increases the hero's mana reserves and allows one additional spell use each round.", [{"type": "heroStat", "parameters": ["manaBonusPercent", "0.20"], "upgrade": {"increment": 0.05, "levelStep": 5}}, {"type": "heroStat", "parameters": ["magicUsageLimitBonus", "1"]}]),
        "learning": ("Learning", "Improves hero development through a broader mana reserve and battlefield spell capacity.", [{"type": "heroStat", "parameters": ["manaBonusPercent", "0.15"], "upgrade": {"increment": 0.05, "levelStep": 5}}, {"type": "heroStat", "parameters": ["magicUsageLimitBonus", "1"]}]),
        "logistics": ("Logistics", "Increases movement on the adventure map and improves travel on roads.", [{"activationLevel": 8, "type": "heroStat", "parameters": ["movementPerBonus", "0.05"], "upgrade": {"increment": 0.05, "levelStep": 8}}, {"type": "heroStat", "parameters": ["roadPerBonus", "0.33333334"]}]),
        "mercury": ("Mercury", "Generates additional mercury each day.", [{"type": "sideRes", "parameters": ["mercury", "1"], "upgrade": {"increment": 1, "levelStep": 7}}]),
        "mysticism": ("Mysticism", "Increases the hero's mana reserves and allows one additional spell use each round.", [{"type": "heroStat", "parameters": ["manaBonusPercent", "0.10"], "upgrade": {"increment": 0.05, "levelStep": 5}}, {"type": "heroStat", "parameters": ["magicUsageLimitBonus", "1"]}]),
        "navigation": ("Navigation", "Increases adventure movement and view radius as the hero gains levels.", [{"type": "heroStat", "parameters": ["movementPerBonus", "0.04"], "upgrade": {"increment": 0.02, "levelStep": 6}}, {"type": "heroStat", "parameters": ["viewRadius", "1"]}]),
        "necromancy": ("Necromancy", "Represents a HoMM3 Necromancy specialist under the current post-battle Skeleton recovery design.", [{"type": "unitStat", "parameters": ["maxHealth", "0"], "upgrade": {"increment": 1, "levelStep": 4}}, {"type": "unitStat", "parameters": ["initiative", "0"], "upgrade": {"increment": 1, "levelStep": 8}}]),
        "offence": ("Offense", "Increases basic attack damage for the hero's army.", [{"type": "unitStat", "parameters": ["modifierSet", "outDmgMods", "basic_attack", "0.10"], "upgrade": {"increment": 0.01, "levelStep": 2}}]),
        "resistance": ("Resistance", "Reduces incoming spell damage for the hero's army.", [{"type": "unitStat", "parameters": ["modifierSet", "inDmgMods", "magic_damage", "-0.10"], "upgrade": {"increment": -0.01, "levelStep": 2}}]),
        "scouting": ("Scouting", "Reveals a wider area of the adventure map and exposes enemy hero and army information.", [{"type": "heroStat", "parameters": ["viewRadius", "2"], "upgrade": {"increment": 1, "levelStep": 6}}, {"type": "heroStat", "parameters": ["enableEnemyHeroInfo", "true"]}, {"type": "heroStat", "parameters": ["enableSquadCounts", "true"]}]),
        "slayer": ("Slayer", "Improves direct combat damage against hardened targets.", [{"type": "unitStat", "parameters": ["modifierSet", "outDmgMods", "basic_attack", "0.06"], "upgrade": {"increment": 0.01, "levelStep": 4}}, {"type": "unitStat", "parameters": ["modifierSet", "outDmgMods", "magic_damage", "0.03"], "upgrade": {"increment": 0.01, "levelStep": 6}}]),
        "sorcery": ("Sorcery", "Increases spell damage and weakens enemy spell pressure as the hero gains levels.", [{"type": "heroStat", "parameters": ["magicAttackPerBonus", "0.10"], "upgrade": {"increment": 0.01, "levelStep": 2}}, {"type": "heroStatBattle", "receiverAllegiance": "enemy", "parameters": ["magicAttackPerBonus", "-0.10"], "upgrade": {"increment": -0.01, "levelStep": 2}}]),
        "speed": ("Speed", "Increases Speed for the hero's army.", [{"type": "unitStat", "parameters": ["speed", "1"], "upgrade": {"increment": 1, "levelStep": 12}}]),
        "stone": ("Stone", "Generates additional stone each day.", [{"type": "sideRes", "parameters": ["stone", "1"], "upgrade": {"increment": 1, "levelStep": 7}}]),
        "sulfur": ("Sulfur", "Generates additional sulfur each day.", [{"type": "sideRes", "parameters": ["sulfur", "1"], "upgrade": {"increment": 1, "levelStep": 7}}]),
        "tactics": ("Tactics", "Improves pre-battle deployment and constricts the enemy deployment zone.", [{"type": "heroStat", "parameters": ["enableTactics", "true"]}, {"type": "heroStat", "parameters": ["tacticsPlacementSize", "2"]}, {"type": "heroStatBattle", "receiverAllegiance": "enemy", "parameters": ["tacticsPlacementSize", "-1"]}]),
    }
    return profiles[kind]


def source_skill_specialization_override(hero_sid: str, index: int, kind: str) -> dict[str, Any]:
    name, description, bonuses = skill_specialization_profiles(kind)
    return {
        "mode": "changed",
        "sourceSpecId": f"{hero_sid}_source_{kind}_specialist",
        "nameText": name,
        "descriptionText": player_facing_specialization_description(description),
        "iconKey": specialization_icon_key_for_kind(kind),
        "bonuses": bonuses,
        "changeDisposition": "explicit_changed_olden_era_specialist",
        "sourceSpecialtyKey": f"skill:{kind}",
    }


def changed_specialization_override(manifest: dict[str, Any], hero_sid: str, index: int) -> dict[str, Any]:
    faction_sid = str(manifest.get("identity", {}).get("factionSid") or "")
    masterful_override = masterful_spell_specialization_override(faction_sid, hero_sid, index)
    if masterful_override is not None:
        return masterful_override
    source_specialty = H3_HERO_SPECIALTIES.get((faction_sid, index))
    if source_specialty is not None:
        source_kind, source_value = source_specialty
        if source_kind == "creature":
            return source_creature_specialization_override(manifest, hero_sid, index, source_value)
        if source_kind == "skill":
            return source_skill_specialization_override(hero_sid, index, source_value)
    unit_lines = [line for line in manifest.get("unitLines", []) if isinstance(line, dict) and line.get("baseSid")]
    kind, unit_line_index = hero_profile_pattern(index)
    if kind == "creature" and unit_lines:
        line = unit_lines[(unit_line_index or 0) % len(unit_lines)]
        unit_name = manifest_unit_line_name(line)
        variants = manifest_unit_variants(manifest)
        return {
            "mode": "changed",
            "sourceSpecId": f"{hero_sid}_olden_era_{line['baseSid']}_specialist",
            "nameText": f"{unit_name} Specialist",
            "descriptionText": f"{unit_name} creatures and their upgrades gain extra weekly growth, Speed, Initiative, Health, Attack, and Defense while this hero leads them.",
            "iconKey": manifest_unit_sid_for_variant(line, variants[0] if variants else ""),
            "bonuses": creature_specialization_bonuses(manifest, line),
            "changeDisposition": "explicit_changed_olden_era_specialist",
        }
    profiles: dict[str, tuple[str, str, str, list[dict[str, Any]]]] = {
        "logistics": (
            "Logistics",
            "Increases movement on the adventure map and improves travel on roads.",
            "skill_logistic",
            [
                {
                    "activationLevel": 8,
                    "type": "heroStat",
                    "parameters": ["movementPerBonus", "0.05"],
                    "upgrade": {"increment": 0.05, "levelStep": 8},
                },
                {"type": "heroStat", "parameters": ["roadPerBonus", "0.33333334"]},
            ],
        ),
        "pathfinding": (
            "Pathfinding",
            "Ignores rough-terrain movement penalties and restores movement after battles.",
            "skill_logistic",
            [
                {"type": "heroStat", "parameters": ["landscapePenaltyPerBonus", "-1.0"]},
                {"type": "heroStat", "parameters": ["movementAfterBattleBonus", "5"]},
            ],
        ),
        "scouting": (
            "Scouting",
            "Reveals a wider area of the adventure map and exposes enemy hero and army information.",
            "skill_scouting",
            [
                {"type": "heroStat", "parameters": ["viewRadius", "2"], "upgrade": {"increment": 1, "levelStep": 6}},
                {"type": "heroStat", "parameters": ["enableEnemyHeroInfo", "true"]},
                {"type": "heroStat", "parameters": ["enableSquadCounts", "true"]},
            ],
        ),
        "tactics": (
            "Tactics",
            "Improves pre-battle deployment and constricts the enemy deployment zone.",
            "skill_tactics",
            [
                {"type": "heroStat", "parameters": ["enableTactics", "true"]},
                {"type": "heroStat", "parameters": ["tacticsPlacementSize", "2"]},
                {"type": "heroStatBattle", "receiverAllegiance": "enemy", "parameters": ["tacticsPlacementSize", "-1"]},
            ],
        ),
        "leadership": (
            "Leadership",
            "Improves army Morale and gives troops a growing chance to act again.",
            "skill_leadership",
            [
                {"type": "heroStat", "parameters": ["moral", "1"]},
                {"type": "unitStat", "parameters": ["additionalActionChanceModifier", "0.02"], "upgrade": {"increment": 0.01, "levelStep": 4}},
            ],
        ),
        "estates": (
            "Estates",
            "Generates additional gold each day, increasing as the hero gains levels.",
            "skill_economy",
            [{"type": "sideRes", "parameters": ["gold", "500"], "upgrade": {"increment": 100, "levelStep": 3}}],
        ),
        "fortune": (
            "Fortune",
            "Improves army Luck and increases the chance of critical hits as the hero gains levels.",
            "skill_luck",
            [
                {"type": "heroStat", "parameters": ["luck", "1"]},
                {"type": "unitStat", "parameters": ["critChanceModifier", "0.02"], "upgrade": {"increment": 0.01, "levelStep": 4}},
            ],
        ),
        "sorcery": (
            "Sorcery",
            "Increases spell damage and weakens enemy spell pressure as the hero gains levels.",
            "skill_sorcery",
            [
                {"type": "heroStat", "parameters": ["magicAttackPerBonus", "0.10"], "upgrade": {"increment": 0.01, "levelStep": 2}},
                {
                    "type": "heroStatBattle",
                    "receiverAllegiance": "enemy",
                    "parameters": ["magicAttackPerBonus", "-0.10"],
                    "upgrade": {"increment": -0.01, "levelStep": 2},
                },
            ],
        ),
        "mysticism": (
            "Mysticism",
            "Increases the hero's mana reserves and allows one additional spell use each round.",
            "skill_wisdom",
            [
                {"type": "heroStat", "parameters": ["manaBonusPercent", "0.10"], "upgrade": {"increment": 0.05, "levelStep": 5}},
                {"type": "heroStat", "parameters": ["magicUsageLimitBonus", "1"]},
            ],
        ),
        "offense": (
            "Offense",
            "Increases basic attack damage for the hero's army, with stronger gains at higher levels.",
            "skill_assault",
            [{"type": "unitStat", "parameters": ["modifierSet", "outDmgMods", "basic_attack", "0.10"], "upgrade": {"increment": 0.01, "levelStep": 2}}],
        ),
        "armorer": (
            "Armorer",
            "Reduces incoming basic and ranged attack damage for the hero's army, with stronger gains at higher levels.",
            "skill_protection",
            [{"type": "unitStat", "parameters": ["modifierSet", "inDmgMods", "basic_attack", "-0.10"], "upgrade": {"increment": -0.01, "levelStep": 2}}],
        ),
    }
    name, description, _profile_icon, bonuses = profiles.get(kind, profiles["armorer"])
    return {
        "mode": "changed",
        "sourceSpecId": f"{hero_sid}_olden_era_{kind}",
        "nameText": name,
        "descriptionText": player_facing_specialization_description(description),
        "iconKey": specialization_icon_key_for_kind(kind),
        "bonuses": bonuses,
        "changeDisposition": "explicit_changed_olden_era_specialist",
    }


def h3_army_rows_to_start_squad(manifest: dict[str, Any], army: list[Any]) -> list[dict[str, int | str]] | None:
    valid_units = set(manifest_unit_base_sids(manifest))
    rows: list[dict[str, int | str]] = []
    for item in army:
        if not isinstance(item, dict):
            continue
        creature = str(item.get("creature") or "").split(":")[-1]
        sid = H3_CREATURE_TO_CUSTOM_SID.get(creature)
        if not sid or sid not in valid_units:
            continue
        rows.append({"sid": sid, "min": int(item.get("min") or 1), "max": int(item.get("max") or item.get("min") or 1)})
    return rows or None


def source_start_squad(manifest: dict[str, Any], source: dict[str, Any] | None) -> list[dict[str, int | str]] | None:
    if not isinstance(source, dict):
        return None
    return h3_army_rows_to_start_squad(manifest, source.get("army") or [])


def table_start_squad(manifest: dict[str, Any], faction_sid: str, hero_name: str) -> list[dict[str, int | str]] | None:
    source_rows = (BASE_HOTA_START_ARMIES.get(faction_sid) or {}).get(hero_name)
    if not source_rows:
        return None
    return h3_army_rows_to_start_squad(manifest, source_rows)


def skill_rows(manifest: dict[str, Any], source: dict[str, Any] | None) -> list[dict[str, int | str]]:
    """Emit override startSkills as at most one Basic HoMM3 secondary.

    Core overlay prepends the unique faction skill. Do not emit faction skills here,
    do not preserve VCMI Advanced/Expert ranks (they add a free subskill and read as
    three starting skills), and do not keep a second VCMI secondary.
    """
    del manifest  # faction skill is derived later by the Core overlay
    rows: list[dict[str, int | str]] = []
    seen: set[str] = set()
    for item in (source or {}).get("skills") or []:
        if not isinstance(item, dict):
            continue
        mapped = H3_SKILL_TO_OLDEN_ERA.get(str(item.get("skill") or ""))
        if not mapped or mapped.startswith("skill_faction_") or mapped in seen:
            continue
        rows.append({"sid": mapped, "skillLevel": 1})
        break
    return rows


def merge_entry(existing: dict[str, Any], generated: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged.update(
        {
            "enabled": True,
            "nameText": generated["nameText"],
            "classType": generated["classType"],
            "className": generated["className"],
            "startSquad": generated["startSquad"],
            "startSquadAlt": generated["startSquadAlt"],
            "startSkills": generated["startSkills"],
        }
    )
    merged.setdefault("descriptionText", "")
    merged.setdefault("mottoText", "")
    merged.setdefault("iconKey", generated["iconKey"])
    old_spec = merged.get("specialization")
    if not isinstance(old_spec, dict):
        merged["specialization"] = generated["specialization"]
    else:
        mode = old_spec.get("mode")
        has_source = isinstance(old_spec.get("sourceSpecId"), str) and bool(old_spec["sourceSpecId"].strip())
        has_text = isinstance(old_spec.get("nameText"), str) and bool(old_spec["nameText"].strip()) and isinstance(old_spec.get("descriptionText"), str) and bool(old_spec["descriptionText"].strip())
        has_icon = isinstance(old_spec.get("iconKey"), str) and bool(old_spec["iconKey"].strip())
        has_bonuses = isinstance(old_spec.get("bonuses"), list) and bool(old_spec["bonuses"])
        old_generated = old_spec.get("changeDisposition") in {"explicit_changed_olden_era_specialist", "explicit_masterful_spell_variant"}
        new_generated = (generated.get("specialization") or {}).get("changeDisposition") in {"explicit_changed_olden_era_specialist", "explicit_masterful_spell_variant"}
        if old_generated and new_generated and old_spec != generated["specialization"]:
            merged["specialization"] = generated["specialization"]
        elif not (mode in {"custom", "copy", "changed", "blocked"} and has_source and has_text and has_icon and (has_bonuses or mode == "blocked")):
            merged["specialization"] = generated["specialization"]
    if not merged.get("notes") or str(merged.get("notes")).startswith("Prefilled from local VCMI HoMM3 hero skills"):
        merged["notes"] = generated["notes"]
    return merged


def build_override(faction_path: Path, vcmi_heroes: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], int, list[str]]:
    manifest = read_jsonc(faction_path)
    faction_sid = manifest["identity"]["factionSid"]
    names = manifest_hero_names(manifest, faction_sid)
    existing_path = OUTPUT_DIR / f"{faction_sid}.json"
    existing = read_jsonc(existing_path) if existing_path.exists() else {"schemaVersion": 1, "factionSid": faction_sid, "heroOverrides": {}}
    overrides = existing.setdefault("heroOverrides", {})
    warnings: list[str] = []
    fallback_squad = default_start_squad(manifest)
    count = int((manifest.get("heroes") or {}).get("count") or len(names))
    for index in range(1, count + 1):
        hero_sid = f"{faction_sid}_hero_{index}"
        name = names[index - 1] if index <= len(names) else f"Hero {index}"
        source = vcmi_heroes.get(normalize_name(name))
        if source is None:
            warnings.append(f"{faction_sid}:{name}: no VCMI hero source; used class fallback")
        class_type, class_name = H3_CLASS_TO_CUSTOM_CLASS.get(
            str((source or {}).get("class") or ""),
            ("might" if index <= 8 else "magic", (manifest.get("heroes") or {}).get("mightClassName" if index <= 8 else "magicClassName") or "Hero"),
        )
        squad = source_start_squad(manifest, source)
        note_army_source = "army uses exact local VCMI/HotA hero army row."
        if not squad:
            squad = table_start_squad(manifest, faction_sid, name)
            note_army_source = "army uses the checked HoMM3/HotA starter table in prefill_homm3_hero_overrides.py."
        if not squad:
            squad = fallback_squad
            note_army_source = "army uses this faction's HoMM3 tier-1/tier-2/tier-3 starter template because no exact source row is available."
            warnings.append(f"{faction_sid}:{name}: no exact starter army source; used faction template")
        squad_alt = [{"sid": squad[0]["sid"], "min": 1, "max": 1}] if squad else []
        generated = {
            "enabled": True,
            "nameText": name,
            "descriptionText": "",
            "mottoText": "",
            "iconKey": f"hero_{faction_sid}_{index}",
            "classType": class_type,
            "className": class_name,
            "startSquad": squad,
            "startSquadAlt": squad_alt,
            "startSkills": skill_rows(manifest, source),
            "specialization": {
                **changed_specialization_override(manifest, hero_sid, index),
            },
            "notes": f"Prefilled from local VCMI HoMM3 hero skills; {note_army_source}",
        }
        old_entry = overrides.get(hero_sid) if isinstance(overrides.get(hero_sid), dict) else {}
        overrides[hero_sid] = merge_entry(old_entry, generated)
    stale_prefix = f"{faction_sid}_hero_"
    for hero_sid in list(overrides.keys()):
        if not isinstance(hero_sid, str) or not hero_sid.startswith(stale_prefix):
            continue
        suffix = hero_sid[len(stale_prefix):]
        if suffix.isdigit() and int(suffix) > count:
            del overrides[hero_sid]
    return existing, count, warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-specializations", action="store_true", help="Fail if any enabled hero would still have an empty or blocked specialization.")
    args = parser.parse_args()
    vcmi_heroes = load_vcmi_heroes()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total = 0
    warnings: list[str] = []
    for faction_path in sorted(CUSTOM_FACTIONS.glob("homm3_*.json")):
        override, count, faction_warnings = build_override(faction_path, vcmi_heroes)
        faction_sid = override["factionSid"]
        output_path = OUTPUT_DIR / f"{faction_sid}.json"
        output_path.write_text(json.dumps(override, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        total += count
        warnings.extend(faction_warnings)
        print(f"wrote {output_path} ({count} heroes)")
    print(f"prefilled {total} heroes from {len(vcmi_heroes)} VCMI hero source rows")
    missing_specializations = []
    for path in sorted(OUTPUT_DIR.glob("homm3_*.json")):
        data = read_jsonc(path)
        for hero_sid, entry in (data.get("heroOverrides") or {}).items():
            if not isinstance(entry, dict) or entry.get("enabled") is False:
                continue
            spec = entry.get("specialization")
            if not isinstance(spec, dict):
                missing_specializations.append(f"{data.get('factionSid')}:{hero_sid}: missing specialization object")
                continue
            mode = spec.get("mode")
            if mode == "blocked":
                missing_specializations.append(f"{data.get('factionSid')}:{hero_sid}: blocked specialization")
                continue
            if not all(isinstance(spec.get(key), str) and spec[key].strip() for key in ("sourceSpecId", "nameText", "descriptionText", "iconKey")):
                missing_specializations.append(f"{data.get('factionSid')}:{hero_sid}: incomplete specialization fields")
            if not isinstance(spec.get("bonuses"), list) or not spec["bonuses"]:
                missing_specializations.append(f"{data.get('factionSid')}:{hero_sid}: empty specialization bonuses")
    for warning in warnings:
        print(f"WARN: {warning}")
    for warning in missing_specializations:
        print(f"WARN: {warning}")
    if args.require_specializations and missing_specializations:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
