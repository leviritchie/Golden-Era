"""
Clone Playtest Dungeon heroes + specializations into homm3_stronghold, remap
creature SIDs to h3_* units, and duplicate English heroInfo tokens from dungeon.

Also ensures DB/heroes_sub_classes/sub_classes_homm3_stronghold.json exists (clone of
dungeon sub-classes with homm3_stronghold ids/fraction) so heroes resolve sub_class_config.
Single-player configured launches run as quick games; quick/arena hero tables must also
know the cloned hero SIDs or processing kills the configured start hero.

Run:
  python generate_homm3_stronghold_heroes.py
  python generate_homm3_stronghold_heroes.py --dungeon-start-squads  # bisect: keep hero starting armies vanilla

Verify Core.zip (after city + heroes steps):
  python verify_homm3_stronghold_core_parity.py
"""

from __future__ import annotations

import copy
import json
import sys
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "tools" / "ability_editor") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "tools" / "ability_editor"))
from prefill_homm3_hero_overrides import (  # noqa: E402
    BASE_HOTA_START_ARMIES,
    FALLBACK_HERO_NAMES,
    h3_army_rows_to_start_squad,
    read_jsonc,
)

PLAYTEST_CORE = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Core.zip"
)
PLAYTEST_HEROINFO_EN = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Lang\english\texts\heroInfo.json"
)
PLAYTEST_LANG_ROOT = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Lang"
)

FRACTION_ID = "homm3_stronghold"
HERO_PREFIX = "homm3_stronghold_hero"
USE_DUNGEON_START_SQUADS = False
STRONGHOLD_MANIFEST_PATH = _REPO_ROOT / "custom_factions" / "homm3_stronghold.json"
_STRONGHOLD_MANIFEST: dict | None = None

# Do NOT add a second top-level skill_faction_* clone that reuses sub_skill_faction_dungeon_*:
# session load registers sub-skills in a global dict → ArgumentException duplicate key.
REMOVED_BAD_FACTION_SKILL_SID = "skill_faction_homm3_stronghold"
SKILLS_JSON_PATH = "DB/heroes_skills/skills/skills.json"
ARENA_SKILLS_JSON_PATH = "DB/heroes_skills/skills/skills_arena.json"
SUB_SKILLS_JSON_PATH = "DB/heroes_skills/sub_skills/sub_skills.json"
ARENA_SUB_SKILLS_JSON_PATH = "DB/heroes_skills/sub_skills/sub_skills_arena.json"
HERO_ABILITIES_PATH = "DB/heroes_abilities/heroes_abilities_base/hero_abilities.json"
HERO_ABILITY_BONUSES_PATH = "DB/heroes_abilities/heroes_abilities_bonuses/hero_abilities_bonuses.json"
HERO_ABILITY_INFOS_PATH = "DB/heroes_abilities/heroes_abilities_infos/hero_abilities_infos.json"
SIDE_BUFFS_PATH = "DB/side_buffs/side_buff_base/side_buffs.json"
SIDE_BUFF_INFOS_PATH = "DB/side_buffs/side_buff_infos/side_buff_infos.json"
SUB_SKILL_UNIT_BUFFS_PATH = "DB/buffs/sub_skills_battle_hero_buffs.json"
SUB_SKILL_ABILITY_UNIT_BUFFS_PATH = "DB/buffs/sub_skills_battle_hero_ability_buffs.json"
SPACE_MAGIC_BUFFS_PATH = "DB/buffs/buffs_space_magics.json"
DUNGEON_MIGHT_TABLE_PATH = "DB/heroes_skills/skills_by_level_tables/dungeon_might_skills_table.json"
DUNGEON_MAGIC_TABLE_PATH = "DB/heroes_skills/skills_by_level_tables/dungeon_magic_skills_table.json"
STRONGHOLD_MIGHT_TABLE_PATH = "DB/heroes_skills/skills_by_level_tables/homm3_stronghold_might_skills_table.json"
STRONGHOLD_MAGIC_TABLE_PATH = "DB/heroes_skills/skills_by_level_tables/homm3_stronghold_magic_skills_table.json"
DUNGEON_ARENA_MIGHT_TABLE_PATH = "DB/heroes_skills/skills_by_level_tables/arenaGame_dungeon_might_skills_table.json"
DUNGEON_ARENA_MAGIC_TABLE_PATH = "DB/heroes_skills/skills_by_level_tables/arenaGame_dungeon_magic_skills_table.json"
STRONGHOLD_ARENA_MIGHT_TABLE_PATH = "DB/heroes_skills/skills_by_level_tables/arenaGame_homm3_stronghold_might_skills_table.json"
STRONGHOLD_ARENA_MAGIC_TABLE_PATH = "DB/heroes_skills/skills_by_level_tables/arenaGame_homm3_stronghold_magic_skills_table.json"
DUNGEON_SUB_CLASSES_PATH = "DB/heroes_sub_classes/sub_classes_dungeon.json"
DEMON_SUB_CLASSES_PATH = "DB/heroes_sub_classes/sub_classes_demon.json"
NATURE_SUB_CLASSES_PATH = "DB/heroes_sub_classes/sub_classes_nature.json"
STRONGHOLD_SUB_CLASSES_PATH = "DB/heroes_sub_classes/sub_classes_homm3_stronghold.json"
ARENA_GAME_PATH = "DB/arenaGame.json"
ARENA_PICK_CONTENT_PATH = "DB/ai_pick/arena_pick_content.json"
ARENA_PICK_MODS_PATH = "DB/ai_pick/arena_pick_mods.json"
SKILLS_BY_LEVEL_REPLACE_PATH = "DB/heroes_skills/skills_by_level_replace_tables/skills_by_level_replace_table.json"

STRONGHOLD_CLASS_NAME_TOKENS: dict[str, str] = {
    "sub_class_homm3_stronghold_might_name": "Barbarian",
    "sub_class_homm3_stronghold_magic_name": "Battle Mage",
    "sub_class_homm3_stronghold_might_1_name": "Barbarian",
    "sub_class_homm3_stronghold_might_2_name": "Barbarian",
    "sub_class_homm3_stronghold_magic_1_name": "Battle Mage",
    "sub_class_homm3_stronghold_magic_2_name": "Battle Mage",
    "stronghold_might_hero": "Barbarian",
    "stronghold_magic_hero": "Battle Mage",
    "homm3_stronghold_might_hero": "Barbarian",
    "homm3_stronghold_magic_hero": "Battle Mage",
    "might_homm3_stronghold_name": "Barbarian",
    "magic_homm3_stronghold_name": "Battle Mage",
}

WARCRIES_HERO_SKILL_TOKENS: dict[str, str] = {
    "skill_faction_homm3_stronghold_name": "Warcries",
    "skill_faction_homm3_stronghold_name_1": "Basic Warcries",
    "skill_faction_homm3_stronghold_name_2": "Advanced Warcries",
    "skill_faction_homm3_stronghold_name_3": "Expert Warcries",
    "skill_faction_homm3_stronghold_desc": "Once per round, the hero can activate one of three Warcries. Only one Warcry can be active at a time.",
    "skill_faction_homm3_stronghold_ability_moral_name": "Rallying Cry",
    "skill_faction_homm3_stronghold_ability_moral_description": "Increases allied Morale by 1/2/3 based on Warcries rank. Only one Warcry can be active at a time.",
    "skill_faction_homm3_stronghold_ability_luck_name": "Fortune Cry",
    "skill_faction_homm3_stronghold_ability_luck_description": "Increases allied Luck by 1/2/3 based on Warcries rank. Only one Warcry can be active at a time.",
    "skill_faction_homm3_stronghold_ability_initiative_name": "Tempo Cry",
    "skill_faction_homm3_stronghold_ability_initiative_description": "Increases allied creatures' Initiative by 1/2/3 based on Warcries rank. Only one Warcry can be active at a time.",
    "sub_skill_faction_homm3_stronghold_1_name": "Native Drums",
    "sub_skill_faction_homm3_stronghold_1_desc": "Friendly Stronghold creatures deal +10% and take -10% Damage on Native Terrain.",
    "sub_skill_faction_homm3_stronghold_2_name": "Intimidating Chorus",
    "sub_skill_faction_homm3_stronghold_2_desc": "When selecting a Warcry, the enemy side suffers a matching penalty while the Warcry is active.",
    "sub_skill_faction_homm3_stronghold_3_name": "Blood-Fired Blows",
    "sub_skill_faction_homm3_stronghold_3_desc": "Friendly creatures gain +15% Attack.",
    "sub_skill_faction_homm3_stronghold_4_name": "Deafening Call",
    "sub_skill_faction_homm3_stronghold_4_desc": "The selected Warcry's bonus increases by an additional +1.",
    "sub_skill_faction_homm3_stronghold_5_name": "Battle Rhythm",
    "sub_skill_faction_homm3_stronghold_5_desc": "Generate 1 Focus Charge each time the hero selects a Warcry.",
    "sub_skill_faction_homm3_stronghold_6_name": "Adrenal Chant",
    "sub_skill_faction_homm3_stronghold_6_desc": "When selecting a Warcry, the hero restores 3 temporary mana.",
}

STRONGHOLD_HEROINFO_OVERRIDES: dict[str, str] = {
    "homm3_stronghold_hero_1_spec_description": (
        "Creatures under his command deal +10% basic attack damage. "
        "Melee, ranged, and shoot attack damage each gain an additional +1% every 2 hero levels, starting at level 2."
    ),
    "homm3_stronghold_hero_2_spec_name": "Heroic Strike",
    "homm3_stronghold_hero_2_motto": "A well-timed strike can do what a siege engine cannot.",
    "homm3_stronghold_hero_2_description": (
        "Gurnisson turns battlefield timing into a punishing Heroic Strike. His blows follow the Olden Era Warrior specialist path, "
        "growing stronger at fixed hero levels instead of using a war machine.\n\n"
        "Gurnisson was orphaned as a child and raised by Dwarven engineers who taught him the art of siege warfare. "
        "He returned to his barbarian kin with knowledge that few of them possessed, earning both fear and respect for his mechanical prowess."
    ),
    "homm3_stronghold_hero_2_spec_description": (
        "His Heroic Strike follows the Olden Era Warrior specialist scaling path: "
        "it gains the base Heroic Strike specialist bonus, then another level bonus at levels 7, 13, 19, 25, 31, 37, 43, and 49."
    ),
    "homm3_stronghold_hero_3_spec_description": (
        "Wolf Rider growth in your cities increases by 1. Under his command, Wolf Riders, Wolf Raiders, and Boar Riders gain "
        "+1 Speed, +1 Initiative, and +20% HP. Their Attack and Defense increase by +1 for every 3 hero levels, "
        "and enemy Wolf Rider-line creatures lose the same amount of Attack and Defense."
    ),
    "homm3_stronghold_hero_4_spec_description": (
        "Roc growth in your cities increases by 1. Under her command, Rocs, Thunderbirds, and Stormbirds gain "
        "+1 Speed, +1 Initiative, and +20% HP. Their Attack and Defense increase by +1 for every 3 hero levels, "
        "and enemy Roc-line creatures lose the same amount of Attack and Defense."
    ),
    "homm3_stronghold_hero_5_spec_description": (
        "Starts with Chain Lightning and replaces it with the Masterful Chain Lightning variant. "
        "Effective Spell Power for that spell increases by +1 for every 3 hero levels."
    ),
    "homm3_stronghold_hero_6_spec_description": (
        "Ogre growth in your cities increases by 1. Under his command, Ogres, Ogre Magi, and Ogre Leaders gain "
        "+1 Speed, +1 Initiative, and +20% HP. Their Attack and Defense increase by +1 for every 3 hero levels, "
        "and enemy Ogre-line creatures lose the same amount of Attack and Defense."
    ),
    "homm3_stronghold_hero_7_spec_description": (
        "Creatures under his command deal +10% basic attack damage. "
        "Melee, ranged, and shoot attack damage each gain an additional +1% every 2 hero levels, starting at level 2."
    ),
    "homm3_stronghold_hero_8_spec_description": (
        "Cyclops growth in your cities increases by 1. Under his command, Cyclopes, Cyclops Kings, and Blood-Eyed Cyclopes gain "
        "+1 Speed, +1 Initiative, and +20% HP. Their Attack and Defense increase by +1 for every 3 hero levels, "
        "and enemy Cyclops-line creatures lose the same amount of Attack and Defense."
    ),
    "homm3_stronghold_hero_8_description": (
        "Krellion's expertise in commanding Cyclopes and other massive creatures is unmatched. He has an almost supernatural ability "
        "to drive the largest and slowest beasts into disciplined battle lines.\n\n"
        "Krellion was the runt of his ogre-blooded clan, smaller than his peers but twice as loud. To prove himself, he challenged "
        "and tamed a wild Behemoth with nothing but a length of chain and his indomitable will. The Behemoth, whom he named Gorm, "
        "now follows him into every battle."
    ),
    "homm3_stronghold_hero_9_spec_description": (
        "Wolf Rider growth in your cities increases by 1. Under his command, Wolf Riders, Wolf Raiders, and Boar Riders gain "
        "+1 Speed, +1 Initiative, and +20% HP. Their Attack and Defense increase by +1 for every 3 hero levels, "
        "and enemy Wolf Rider-line creatures lose the same amount of Attack and Defense."
    ),
    "homm3_stronghold_hero_10_spec_description": (
        "He deals +10% damage with spells, plus another +1% every 2 hero levels. "
        "Enemy hero spell damage is reduced by the same value."
    ),
    "homm3_stronghold_hero_11_spec_name": "Pathfinding",
    "homm3_stronghold_hero_11_description": (
        "Vey's borrowed Olden Era specialty is Pathfinding rather than true Eagle Eye spell learning. He scouts farther than most heroes "
        "and guides armies across hostile terrain without movement penalties.\n\n"
        "Vey was once a scribe for a powerful Warlock, copying spell scrolls and secretly memorizing their contents. When the Warlock "
        "discovered this, he sent assassins after Vey, but the barbarian fled to Krewlod where his stolen knowledge found a new and dangerous purpose."
    ),
    "homm3_stronghold_hero_11_spec_description": (
        "Olden Era replacement for Eagle Eye: his movement takes no terrain penalties. "
        "He also has +1 Sight Radius, plus another +1 for every 5 hero levels."
    ),
    "homm3_stronghold_hero_12_spec_description": (
        "Creatures under her command deal +10% basic attack damage. "
        "Melee, ranged, and shoot attack damage each gain an additional +1% every 2 hero levels, starting at level 2."
    ),
    "homm3_stronghold_hero_13_spec_name": "Favorable Wind",
    "homm3_stronghold_hero_13_description": (
        "Zubin's borrowed specialty is Favorable Wind. Under his guidance, ranged and long-reaching attackers benefit from a spell "
        "that scales with his level instead of the original HoMM3 Precision spell.\n\n"
        "Zubin lost his left arm in a Behemoth hunt, yet refused to retire from combat. Instead, he honed his magic to compensate, "
        "developing a unique one-handed casting style. He now teaches his warriors that precision of mind matters more than strength of body."
    ),
    "homm3_stronghold_hero_13_spec_description": (
        "Starts with Favorable Wind. Effective Spell Power for that spell increases by +1 for every 3 hero levels."
    ),
    "homm3_stronghold_hero_14_spec_description": (
        "Starts with Haste and replaces it with the Masterful Haste variant. "
        "Effective Spell Power for that spell increases by +1 for every 3 hero levels."
    ),
    "homm3_stronghold_hero_15_spec_description": (
        "Starting at level 8, increases land movement by +5%, plus another +5% every 8 hero levels. "
        "Road movement is also improved by 33%."
    ),
    "homm3_stronghold_hero_16_spec_name": "Enlarge Shadow",
    "homm3_stronghold_hero_16_description": (
        "Saurug's borrowed specialty is Enlarge Shadow. His magic strengthens allied Attack and Defense and scales with his level, "
        "standing in for the original HoMM3 Bloodlust specialty.\n\n"
        "Saurug was born during a battle, his mother fighting until the moment of his birth and returning to combat moments after. "
        "Violence runs in his blood more than blood itself. His battle chants awaken a primal rage in his troops that no enemy has ever withstood."
    ),
    "homm3_stronghold_hero_16_spec_description": (
        "Starts with Enlarge Shadow. Effective Spell Power for that spell increases by +1 for every 3 hero levels."
    ),
    "homm3_stronghold_hero_17_spec_name": "Goblins",
    "homm3_stronghold_hero_17_description": (
        "Drakon is a bonus slot using Goblin specialist mechanics. Under his command, Goblins, Hobgoblins, and Goblin Trappers become "
        "faster, tougher, and better in direct combat as he gains levels.\n\n"
        "Drakon was raised by Gnolls after being abandoned in the marshes as a child. He learned their ways of ambush and pack hunting, "
        "eventually becoming the alpha of his pack. Now he applies these same tactics to the barbarian warbands, with devastating effect "
        "on anyone foolish enough to underestimate him."
    ),
    "homm3_stronghold_hero_17_spec_description": (
        "Bonus slot: Goblin growth in your cities increases by 1. Under his command, Goblins, Hobgoblins, and Goblin Trappers gain "
        "+1 Speed, +1 Initiative, and +20% HP. Their Attack and Defense increase by +1 for every 3 hero levels, "
        "and enemy Goblin-line creatures lose the same amount of Attack and Defense."
    ),
    "homm3_stronghold_hero_18_spec_description": (
        "His movement takes no terrain penalties. He also has +1 Sight Radius, plus another +1 for every 5 hero levels."
    ),
}


def stronghold_heroinfo_override_items() -> dict[str, str]:
    out = dict(STRONGHOLD_HEROINFO_OVERRIDES)
    for sid, text in STRONGHOLD_HEROINFO_OVERRIDES.items():
        if not sid.endswith("_spec_description"):
            continue
        out[sid.replace("_spec_description", "_raw_spec_description")] = text
        out[sid.replace("_spec_description", "_raw_raw_spec_description")] = text
    return out


# Same tier mapping as generate_homm3_stronghold_city.py
UNIT_MAP: dict[str, str] = {
    "trogl": "h3_goblin",
    "trogl_upg": "h3_goblin_upg",
    "trogl_upg_alt": "h3_goblin_upg_alt",
    "assassin": "h3_wolf_rider",
    "assassin_upg": "h3_wolf_rider_upg",
    "assassin_upg_alt": "h3_wolf_rider_upg_alt",
    "blade_dancer": "h3_orc",
    "blade_dancer_upg": "h3_orc_upg",
    "blade_dancer_upg_alt": "h3_orc_upg_alt",
    "minos": "h3_ogre",
    "minos_upg": "h3_ogre_upg",
    "minos_upg_alt": "h3_ogre_upg_alt",
    "medusa": "h3_roc",
    "medusa_upg": "h3_roc_upg",
    "medusa_upg_alt": "h3_roc_upg_alt",
    "hydra": "h3_cyclops",
    "hydra_upg": "h3_cyclops_upg",
    "hydra_upg_alt": "h3_cyclops_upg_alt",
    "black_dragon": "h3_behemoth",
    "black_dragon_upg": "h3_behemoth_upg",
    "black_dragon_upg_alt": "h3_behemoth_upg_alt",
}

H3_UNIT_UPGRADES: dict[str, list[str]] = {
    "h3_goblin": ["h3_goblin", "h3_goblin_upg", "h3_goblin_upg_alt"],
    "h3_wolf_rider": ["h3_wolf_rider", "h3_wolf_rider_upg", "h3_wolf_rider_upg_alt"],
    "h3_orc": ["h3_orc", "h3_orc_upg", "h3_orc_upg_alt"],
    "h3_ogre": ["h3_ogre", "h3_ogre_upg", "h3_ogre_upg_alt"],
    "h3_roc": ["h3_roc", "h3_roc_upg", "h3_roc_upg_alt"],
    "h3_cyclops": ["h3_cyclops", "h3_cyclops_upg", "h3_cyclops_upg_alt"],
    "h3_behemoth": ["h3_behemoth", "h3_behemoth_upg", "h3_behemoth_upg_alt"],
}

HERO_START_PATCHES: dict[int, tuple[str | None, str | None]] = {
    # (secondary skill, starting spell). Keep skill_faction_dungeon for now: the
    # attempted homm3 faction skill clone is intentionally removed elsewhere.
    2: ("skill_battle_artistry", None),
    5: ("skill_magic_primal", "primal_12_magic_chain_lightning"),
    10: ("skill_sorcery", None),
    11: ("skill_scouting", None),
    13: ("skill_magic_day", "day_4_magic_favorable_wind"),
    14: ("skill_magic_day", "day_3_magic_haste"),
    15: ("skill_logistic", None),
    16: ("skill_magic_night", "night_3_magic_enlarge_shadow"),
    18: ("skill_scouting", None),
}


def hero_battle_unlocks(ability_sid: str) -> list[dict]:
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


def make_unit_specialist(unit_sid: str, ability_sid: str) -> list[dict]:
    receivers = H3_UNIT_UPGRADES[unit_sid]
    return [
        {"type": "cityUnitsIncrement", "parameters": [unit_sid, "1"]},
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
        {
            "type": "unitStat",
            "receiverAllegiance": "enemy",
            "receivers": receivers,
            "parameters": ["offence", "0"],
            "upgrade": {"increment": -1, "levelStep": 3},
        },
        {
            "type": "unitStat",
            "receiverAllegiance": "enemy",
            "receivers": receivers,
            "parameters": ["defence", "0"],
            "upgrade": {"increment": -1, "levelStep": 3},
        },
        *hero_battle_unlocks(ability_sid),
    ]


def make_offense_specialist(ability_sid: str) -> list[dict]:
    return [
        {
            "type": "unitStat",
            "parameters": ["modifierSet", "outDmgMods", "basic_attack", "0.10"],
            "upgrade": {"increment": 0.01, "levelStep": 2},
        },
        {
            "activationLevel": 2,
            "type": "unitStat",
            "parameters": ["modifierSet", "outDmgMods", "melee_attack", "0.01"],
            "upgrade": {"increment": 0.01, "levelStep": 2},
        },
        {
            "activationLevel": 2,
            "type": "unitStat",
            "parameters": ["modifierSet", "outDmgMods", "range_attack", "0.01"],
            "upgrade": {"increment": 0.01, "levelStep": 2},
        },
        {
            "activationLevel": 2,
            "type": "unitStat",
            "parameters": ["modifierSet", "outDmgMods", "shoot_attack", "0.01"],
            "upgrade": {"increment": 0.01, "levelStep": 2},
        },
        *hero_battle_unlocks(ability_sid),
    ]


def make_spell_specialist(normal_sid: str, special_sid: str | None, ability_sid: str) -> list[dict]:
    effective_sid = special_sid or normal_sid
    bonuses = []
    if special_sid:
        bonuses.append({"type": "heroMagicReplace", "parameters": [normal_sid, special_sid]})
    bonuses.extend(
        [
            {
                "type": "heroStat",
                "parameters": ["spellPowerSidSet", effective_sid, "0"],
                "upgrade": {"increment": 1, "levelStep": 3},
            },
            *hero_battle_unlocks(ability_sid),
        ]
    )
    return bonuses


def make_sorcery_specialist(ability_sid: str) -> list[dict]:
    return [
        {
            "type": "heroStat",
            "parameters": ["magicAttackPerBonus", "0.10"],
            "upgrade": {"increment": 0.01, "levelStep": 2},
        },
        {
            "type": "heroStatBattle",
            "receiverAllegiance": "enemy",
            "parameters": ["magicAttackPerBonus", "-0.10"],
            "upgrade": {"increment": -0.01, "levelStep": 2},
        },
        *hero_battle_unlocks(ability_sid),
    ]


def make_logistics_specialist(ability_sid: str) -> list[dict]:
    return [
        {
            "activationLevel": 8,
            "type": "heroStat",
            "parameters": ["movementPerBonus", "0.05"],
            "upgrade": {"increment": 0.05, "levelStep": 8},
        },
        {"type": "heroStat", "parameters": ["roadPerBonus", "0.33333334"]},
        *hero_battle_unlocks(ability_sid),
    ]


def make_pathfinding_specialist(ability_sid: str) -> list[dict]:
    return [
        {
            "type": "heroStat",
            "parameters": ["viewRadius", "1"],
            "upgrade": {"increment": 1, "levelStep": 5},
        },
        {"type": "heroStat", "parameters": ["landscapePenaltyPerBonus", "-1.0"]},
        *hero_battle_unlocks(ability_sid),
    ]


def make_heroic_strike_specialist(ability_sid: str) -> list[dict]:
    bonuses = [
        {
            "type": "battleSubskillBonus",
            "parameters": ["hero_ability", "specializations_skill_warrior_ability_base_bonus"],
        }
    ]
    for level in range(7, 50, 6):
        bonuses.append(
            {
                "activationLevel": level,
                "type": "battleSubskillBonus",
                "parameters": ["hero_ability", "specializations_skill_warrior_ability_level_bonus"],
            }
        )
    bonuses.extend(
        [
            {
                "type": "battleSubskillBonus",
                "parameters": ["hero_ability", "skill_warrior_and_mage_skill_dungeon_hero_3_warrior"],
            },
            *hero_battle_unlocks(ability_sid),
        ]
    )
    return bonuses


def make_scouting_pathfinder_specialist(ability_sid: str) -> list[dict]:
    return make_pathfinding_specialist(ability_sid)


def make_homm3_stronghold_specialization_bonuses(hero_idx: int, ability_sid: str) -> list[dict] | None:
    mapping = {
        1: lambda: make_offense_specialist(ability_sid),
        2: lambda: make_heroic_strike_specialist(ability_sid),
        3: lambda: make_unit_specialist("h3_wolf_rider", ability_sid),
        4: lambda: make_unit_specialist("h3_roc", ability_sid),
        5: lambda: make_spell_specialist(
            "primal_12_magic_chain_lightning",
            "primal_12_magic_chain_lightning_special",
            ability_sid,
        ),
        6: lambda: make_unit_specialist("h3_ogre", ability_sid),
        7: lambda: make_offense_specialist(ability_sid),
        8: lambda: make_unit_specialist("h3_cyclops", ability_sid),
        9: lambda: make_unit_specialist("h3_wolf_rider", ability_sid),
        10: lambda: make_sorcery_specialist(ability_sid),
        11: lambda: make_scouting_pathfinder_specialist(ability_sid),
        12: lambda: make_offense_specialist(ability_sid),
        13: lambda: make_spell_specialist(
            "day_4_magic_favorable_wind",
            None,
            ability_sid,
        ),
        14: lambda: make_spell_specialist("day_3_magic_haste", "day_3_magic_haste_special", ability_sid),
        15: lambda: make_logistics_specialist(ability_sid),
        16: lambda: make_spell_specialist(
            "night_3_magic_enlarge_shadow",
            None,
            ability_sid,
        ),
        # Bonus/non-Stronghold slots: keep deterministic, supported mechanics.
        17: lambda: make_unit_specialist("h3_goblin", ability_sid),
        18: lambda: make_pathfinding_specialist(ability_sid),
    }
    maker = mapping.get(hero_idx)
    return maker() if maker is not None else None


def remap_unit_strings(obj: object) -> None:
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k == "sid" and isinstance(v, str) and v in UNIT_MAP:
                obj[k] = UNIT_MAP[v]
            else:
                remap_unit_strings(v)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str) and item in UNIT_MAP:
                obj[i] = UNIT_MAP[item]
            else:
                remap_unit_strings(item)


def cleanup_broken_homm3_faction_skill_clone(all_data: dict[str, bytes]) -> None:
    """Remove skill_faction_homm3_stronghold + roll tables (Player.log duplicate sub_skill key crash)."""
    skills = json.loads(all_data[SKILLS_JSON_PATH].decode("utf-8-sig"))
    before = len(skills["array"])
    skills["array"] = [
        x for x in skills["array"] if x.get("id") != REMOVED_BAD_FACTION_SKILL_SID
    ]
    if len(skills["array"]) != before:
        all_data[SKILLS_JSON_PATH] = json.dumps(
            skills, ensure_ascii=False, indent="\t"
        ).encode("utf-8")
    all_data.pop(STRONGHOLD_MIGHT_TABLE_PATH, None)
    all_data.pop(STRONGHOLD_MAGIC_TABLE_PATH, None)


def array_root(all_data: dict[str, bytes], path: str) -> dict:
    root = json.loads(all_data[path].decode("utf-8-sig"))
    if not isinstance(root.get("array"), list):
        raise RuntimeError(f"{path}: expected top-level array")
    return root


def upsert_by_id(root: dict, row: dict) -> None:
    arr = root["array"]
    rid = row["id"]
    arr[:] = [existing for existing in arr if not (isinstance(existing, dict) and existing.get("id") == rid)]
    arr.append(row)


def dump_root(all_data: dict[str, bytes], path: str, root: dict) -> None:
    all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")


WARCRY_UNIT_STATS = {
    "moral": "moral",
    "luck": "luck",
    "initiative": "initiative",
}

WARCRY_UNIT_STAT_LABELS = {
    "moral": "Morale",
    "luck": "Luck",
    "initiative": "Initiative",
}


def warcry_unit_buff_id(mode: str, rank: int | None = None, *, negative: bool = False, subskill4: bool = False) -> str:
    if subskill4:
        return f"homm3_stronghold_warcry_{mode}_effect_sub_skill_4"
    if rank is None:
        raise ValueError("rank is required for rank-scaled Warcry unit buffs")
    if rank not in (1, 2, 3):
        raise ValueError(f"unsupported Warcry unit buff rank: {rank}")
    base = f"homm3_stronghold_warcry_{mode}_effect"
    if negative:
        base += "_negative"
    return base if rank == 1 else f"{base}_{rank - 1}"


def warcry_unit_buff_description_id(mode: str, *, negative: bool = False) -> str:
    suffix = "_negative" if negative else ""
    return f"homm3_stronghold_warcry_{mode}_effect{suffix}_description"


def warcry_global_buff_base_id(mode: str, *, negative: bool = False) -> str:
    base = f"homm3_stronghold_warcry_{mode}_effect"
    return f"{base}_negative" if negative else base


def warcry_global_buff_mechanic(allegiance: str, mode: str, rank: int | None = None, *, negative: bool = False, subskill4: bool = False) -> dict:
    buff_sid = warcry_unit_buff_id(mode, subskill4=True) if subskill4 else warcry_global_buff_base_id(mode, negative=negative)
    buff_rank = 1 if rank is None else rank
    return {
        "mech": "global_buff",
        "values": [allegiance, buff_sid, str(buff_rank), "1", "9999", "1"],
    }


def warcry_global_unit_dealer(mechanics: list[dict]) -> dict:
    return {
        "instacast": True,
        "untargetedCast": True,
        "multitargetType": "simultaneous",
        "tags": ["ability", "buff_ability"],
        "attackPatternSid": "attack_single_x100",
        "castTargetParams": {
            "targetTags": ["unit"],
            "castTarget_": "all",
            "targetCondition_": "alive",
            "selection": "object",
        },
        "affectTargetParams": {
            "targetTags": ["unit"],
            "castTarget_": "all",
            "targetCondition_": "alive",
            "selection": "object",
        },
        "damageTarget_": "none",
        "damageType_": "none",
        "buffTarget_": "none",
        "targetMechanics": mechanics,
    }


def warcry_direct_unit_buff_dealer(allegiance: str, buff_sid: str, mechanics: list[dict]) -> dict:
    dealer = warcry_global_unit_dealer(mechanics)
    # Working all-unit spell fanout (Doreath's Tide) keeps simultaneous targeting
    # but does not use untargetedCast; direct buff payloads need real receivers.
    dealer.pop("untargetedCast", None)
    dealer["buffTarget_"] = allegiance
    dealer["buff"] = {"sid": buff_sid, "duration": 1}
    return dealer


def warcry_mode_effect_mechanics(mode: str, rank: int) -> list[dict]:
    mechanics = [warcry_global_buff_mechanic("ally", mode, rank)]
    if mode in ("moral", "luck"):
        mechanics.insert(0, {"mech": "side_buff", "values": [f"side_buff_homm3_stronghold_warcry_{mode}_{rank}", "true"]})
    return mechanics


def warcry_force_sibling_cooldowns(mode: str) -> list[dict]:
    return [
        {
            "mech": "force_side_cd",
            "values": [f"skill_faction_homm3_stronghold_ability_{other}", "ally", "1"],
        }
        for other in ("moral", "luck", "initiative")
        if other != mode
    ]


def warcry_common_dispels() -> list[dict]:
    mechanics = [
        {
            "mech": "side_dispel",
            "values": [
                "ally",
                "side_buff_homm3_stronghold_warcry_moral_effect",
                "side_buff_homm3_stronghold_warcry_luck_effect",
            ],
        },
        {
            "mech": "side_dispel",
            "values": [
                "enemy",
                "side_buff_homm3_stronghold_warcry_moral_effect_negative",
                "side_buff_homm3_stronghold_warcry_luck_effect_negative",
            ],
        },
    ]
    for mode in WARCRY_UNIT_STATS:
        mechanics.append({"mech": "global_dispel", "values": ["ally", f"homm3_stronghold_warcry_{mode}_effect"]})
        mechanics.append({"mech": "global_dispel", "values": ["enemy", f"homm3_stronghold_warcry_{mode}_effect_negative"]})
    return mechanics


def make_warcry_unit_buff_rows() -> list[dict]:
    rows = []
    for mode, stat in WARCRY_UNIT_STATS.items():
        positive_tags = ["positive", f"homm3_stronghold_warcry_{mode}_effect"]
        negative_tags = ["negative", f"homm3_stronghold_warcry_{mode}_effect_negative"]
        icon = "skill_faction_dungeon_ability_offence"
        if mode == "initiative":
            positive_tags.append("movementPositive")
            negative_tags.append("movementNegative")
            icon = "magic_early_start_effect_icon"
        for rank in (1, 2, 3):
            rows.append({
                "id": warcry_unit_buff_id(mode, rank),
                "aiValue": 4000,
                "aiValuePerDuration": 400,
                "icon": icon,
                "name_": f"skill_faction_homm3_stronghold_ability_{mode}_name",
                "description_": warcry_unit_buff_description_id(mode),
                "tags": positive_tags,
                "isPositive": True,
                "addition": "duration",
                "data": {"stats": {stat: rank}},
            })
            rows.append({
                "id": warcry_unit_buff_id(mode, rank, negative=True),
                "aiValue": 4000,
                "aiValuePerDuration": 400,
                "icon": icon,
                "name_": f"skill_faction_homm3_stronghold_ability_{mode}_name",
                "description_": warcry_unit_buff_description_id(mode, negative=True),
                "tags": negative_tags,
                "isPositive": False,
                "addition": "duration",
                "data": {"stats": {stat: -rank}},
            })
        rows.append({
            "id": warcry_unit_buff_id(mode, subskill4=True),
            "aiValue": 4000,
            "aiValuePerDuration": 400,
            "icon": icon,
            "name_": "sub_skill_faction_homm3_stronghold_4_name",
            "description_": warcry_unit_buff_description_id(mode),
            "tags": positive_tags,
            "isPositive": True,
            "addition": "duration",
            "data": {"stats": {stat: 1}},
        })
    return rows


def make_warcry_ability(mode: str, effect: str, icon: str) -> dict:
    levels = []
    for rank in (1, 2, 3):
        levels.append({
            "aiValue": 4000,
            "name": f"skill_faction_homm3_stronghold_ability_{mode}_name",
            "description": f"skill_faction_homm3_stronghold_ability_{mode}_description",
            "icon": icon,
            "casterEffect": effect,
            "attackTimeBefore": 0.3,
            "attackTimeAfter": 1.5,
            "useExpandTooltip": "false",
            "cd": 1,
            "charges": 1,
            "attackType_": "cast",
            "damageDealer": (
                warcry_direct_unit_buff_dealer(
                    "ally",
                    warcry_unit_buff_id(mode, rank),
                    [
                        *warcry_common_dispels(),
                        *warcry_force_sibling_cooldowns(mode),
                    ],
                )
                if mode == "initiative"
                else warcry_global_unit_dealer([
                    *warcry_common_dispels(),
                    *warcry_mode_effect_mechanics(mode, rank),
                    *warcry_force_sibling_cooldowns(mode),
                ])
            ),
        })
    return {"id": f"skill_faction_homm3_stronghold_ability_{mode}", "levels": levels}


def make_warcry_delta_ability(mode: str, subskill: int) -> dict:
    levels = []
    for rank in (1, 2, 3):
        if subskill == 2:
            mechanics = []
            if mode == "initiative":
                dealer = warcry_direct_unit_buff_dealer(
                    "enemy",
                    warcry_unit_buff_id(mode, rank, negative=True),
                    mechanics,
                )
            else:
                mechanics.append(warcry_global_buff_mechanic("enemy", mode, rank, negative=True))
                dealer = warcry_global_unit_dealer(mechanics)
            if mode in ("moral", "luck"):
                mechanics.insert(0, {
                    "mech": "side_buff",
                    "values": [f"side_buff_homm3_stronghold_warcry_{mode}_{rank}_sub_skill_2", "true"],
                })
        elif subskill == 4:
            mechanics = []
            if mode == "initiative":
                dealer = warcry_direct_unit_buff_dealer(
                    "ally",
                    warcry_unit_buff_id(mode, subskill4=True),
                    mechanics,
                )
            else:
                mechanics.append(warcry_global_buff_mechanic("ally", mode, subskill4=True))
                dealer = warcry_global_unit_dealer(mechanics)
            if mode in ("moral", "luck"):
                mechanics.insert(0, {
                    "mech": "side_buff",
                    "values": [f"side_buff_homm3_stronghold_warcry_{mode}_sub_skill_4", "true"],
                })
        elif subskill == 5:
            mechanics = [{"mech": "add_energy", "values": ["levels", "ally", "1", "0", "1"]}]
            dealer = warcry_global_unit_dealer(mechanics)
        elif subskill == 6:
            mechanics = [{"mech": "change_mana", "values": ["add", "ally", "3", "0", "0", "true"]}]
            dealer = warcry_global_unit_dealer(mechanics)
        else:
            raise ValueError(subskill)
        levels.append({
            "charges": 0,
            "cd": 0,
            "energyLevel": 0,
            "damageDealer": dealer,
        })
    return {"id": f"skill_faction_homm3_stronghold_ability_{mode}_sub_skill_{subskill}", "levels": levels}


def make_warcries_skill_row(arena: bool = False) -> dict:
    modes = ("moral", "luck", "initiative")
    skill_id = "arena_skill_faction_homm3_stronghold" if arena else "skill_faction_homm3_stronghold"
    subskill_prefix = "arena_sub_skill_faction_homm3_stronghold" if arena else "sub_skill_faction_homm3_stronghold"
    return {
        "id": skill_id,
        "name": "skill_faction_homm3_stronghold_name",
        "desc": "skill_faction_homm3_stronghold_desc",
        "skillType": "Faction",
        "parametersPerLevel": [
            {
                "icon": "skill_faction_homm3_stronghold",
                "name": "skill_faction_homm3_stronghold_name_1",
                "desc": "skill_faction_homm3_stronghold_desc",
                "bonuses": [{"type": "heroBattleAbility", "parameters": [f"skill_faction_homm3_stronghold_ability_{m}", "0"]} for m in modes],
                "subSkills": [],
            },
            {
                "icon": "skill_faction_homm3_stronghold_2",
                "name": "skill_faction_homm3_stronghold_name_2",
                "desc": "skill_faction_homm3_stronghold_desc",
                "bonuses": [{"type": "heroBattleAbility", "parameters": [f"skill_faction_homm3_stronghold_ability_{m}", "1"]} for m in modes],
                "subSkills": [f"{subskill_prefix}_1", f"{subskill_prefix}_2", f"{subskill_prefix}_6"],
            },
            {
                "icon": "skill_faction_homm3_stronghold_3",
                "name": "skill_faction_homm3_stronghold_name_3",
                "desc": "skill_faction_homm3_stronghold_desc",
                "bonuses": [{"type": "heroBattleAbility", "parameters": [f"skill_faction_homm3_stronghold_ability_{m}", "2"]} for m in modes],
                "subSkills": [f"{subskill_prefix}_4", f"{subskill_prefix}_5", f"{subskill_prefix}_3"],
            },
        ],
    }


def make_warcries_subskills(arena: bool = False) -> list[dict]:
    id_prefix = "arena_sub_skill_faction_homm3_stronghold" if arena else "sub_skill_faction_homm3_stronghold"
    rows = [
        {
            "id": f"{id_prefix}_1",
            "name": "sub_skill_faction_homm3_stronghold_1_name",
            "desc": "sub_skill_faction_homm3_stronghold_1_desc",
            "icon": "sub_skill_faction_dungeon_1_icon",
            "bonuses": [
                {"type": "unitStat", "biomeType": "native", "fraction": FRACTION_ID, "parameters": ["outAllDmgMod", "0.1"]},
                {"type": "unitStat", "biomeType": "native", "fraction": FRACTION_ID, "parameters": ["inAllDmgMod", "-0.1"]},
            ],
        },
        {
            "id": f"{id_prefix}_3",
            "name": "sub_skill_faction_homm3_stronghold_3_name",
            "desc": "sub_skill_faction_homm3_stronghold_3_desc",
            "icon": "sub_skill_faction_dungeon_3_icon",
            "bonuses": [{"type": "unitStat", "parameters": ["offencePerc", "0.15"]}],
        },
    ]
    modes = ("moral", "luck", "initiative")
    for subskill, icon in ((2, "sub_skill_faction_dungeon_2_icon"), (4, "sub_skill_faction_dungeon_4_icon"), (5, "sub_skill_faction_dungeon_5_icon"), (6, "sub_skill_faction_dungeon_6_icon")):
        rows.append({
            "id": f"{id_prefix}_{subskill}",
            "name": f"sub_skill_faction_homm3_stronghold_{subskill}_name",
            "desc": f"sub_skill_faction_homm3_stronghold_{subskill}_desc",
            "icon": icon,
            "bonuses": [
                {
                    "type": "battleSubskillBonus",
                    "parameters": ["hero_ability", f"sub_skill_faction_homm3_stronghold_{subskill}_{mode}"],
                }
                for mode in modes
            ],
        })
    return rows


def patch_skill_roll_table(
    all_data: dict[str, bytes],
    src_path: str,
    out_path: str,
    out_id: str,
    src_skill_sid: str = "skill_faction_dungeon",
    out_skill_sid: str = "skill_faction_homm3_stronghold",
) -> None:
    root = copy.deepcopy(array_root(all_data, src_path))
    def replace_faction_skill(obj: object) -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                if value == src_skill_sid:
                    obj[key] = out_skill_sid
                else:
                    replace_faction_skill(value)
        elif isinstance(obj, list):
            for item in obj:
                replace_faction_skill(item)
    for row in root["array"]:
        if isinstance(row, dict):
            row["id"] = out_id
            replace_faction_skill(row)
    dump_root(all_data, out_path, root)


def patch_homm3_stronghold_warcries_skill(all_data: dict[str, bytes]) -> None:
    skills = array_root(all_data, SKILLS_JSON_PATH)
    upsert_by_id(skills, make_warcries_skill_row())
    dump_root(all_data, SKILLS_JSON_PATH, skills)

    arena_skills = array_root(all_data, ARENA_SKILLS_JSON_PATH)
    upsert_by_id(arena_skills, make_warcries_skill_row(arena=True))
    dump_root(all_data, ARENA_SKILLS_JSON_PATH, arena_skills)

    subskills = array_root(all_data, SUB_SKILLS_JSON_PATH)
    for row in make_warcries_subskills():
        upsert_by_id(subskills, row)
    dump_root(all_data, SUB_SKILLS_JSON_PATH, subskills)

    arena_subskills = array_root(all_data, ARENA_SUB_SKILLS_JSON_PATH)
    for row in make_warcries_subskills(arena=True):
        upsert_by_id(arena_subskills, row)
    dump_root(all_data, ARENA_SUB_SKILLS_JSON_PATH, arena_subskills)

    hero_abilities = array_root(all_data, HERO_ABILITIES_PATH)
    upsert_by_id(hero_abilities, make_warcry_ability("moral", "magic/Prefabs_vfx/Heroes/hero_dungeon_defense_hex", "skill_leadership"))
    upsert_by_id(hero_abilities, make_warcry_ability("luck", "magic/Prefabs_vfx/Heroes/hero_dungeon_magic_ability_hex", "skill_luck"))
    upsert_by_id(hero_abilities, make_warcry_ability("initiative", "magic/Prefabs_vfx/Heroes/hero_dungeon_attack_ability_unit", "skill_tactics"))
    dump_root(all_data, HERO_ABILITIES_PATH, hero_abilities)

    ability_bonuses = array_root(all_data, HERO_ABILITY_BONUSES_PATH)
    for mode in ("moral", "luck", "initiative"):
        for subskill in (2, 4, 5, 6):
            upsert_by_id(ability_bonuses, make_warcry_delta_ability(mode, subskill))
    dump_root(all_data, HERO_ABILITY_BONUSES_PATH, ability_bonuses)

    ability_infos = array_root(all_data, HERO_ABILITY_INFOS_PATH)
    for mode in ("moral", "luck", "initiative"):
        for subskill in (2, 4, 5, 6):
            upsert_by_id(ability_infos, {
                "id": f"sub_skill_faction_homm3_stronghold_{subskill}_{mode}",
                "targetAbilitySid": f"skill_faction_homm3_stronghold_ability_{mode}",
                "deltaAbilitySid": f"skill_faction_homm3_stronghold_ability_{mode}_sub_skill_{subskill}",
            })
    dump_root(all_data, HERO_ABILITY_INFOS_PATH, ability_infos)

    side_buffs = array_root(all_data, SIDE_BUFFS_PATH)
    side_infos = array_root(all_data, SIDE_BUFF_INFOS_PATH)
    for mode, stat in (("moral", "moral"), ("luck", "luck")):
        for rank in (1, 2, 3):
            upsert_by_id(side_buffs, {
                "id": f"side_buff_homm3_stronghold_warcry_{mode}_effect_{rank}",
                "infinite": True,
                "canDispel": True,
                "tags": [f"side_buff_homm3_stronghold_warcry_{mode}_effect"],
                "heroStat": {stat: rank},
            })
            upsert_by_id(side_infos, {
                "id": f"side_buff_homm3_stronghold_warcry_{mode}_{rank}",
                "sid": f"side_buff_homm3_stronghold_warcry_{mode}_effect_{rank}",
                "allegiance": "ally",
                "duration": 9999,
                "durationPerStack": 0,
            })
            upsert_by_id(side_buffs, {
                "id": f"side_buff_homm3_stronghold_warcry_{mode}_effect_{rank}_sub_skill_2",
                "infinite": True,
                "canDispel": True,
                "tags": [f"side_buff_homm3_stronghold_warcry_{mode}_effect_negative"],
                "heroStat": {stat: -rank},
            })
            upsert_by_id(side_infos, {
                "id": f"side_buff_homm3_stronghold_warcry_{mode}_{rank}_sub_skill_2",
                "sid": f"side_buff_homm3_stronghold_warcry_{mode}_effect_{rank}_sub_skill_2",
                "allegiance": "enemy",
                "duration": 9999,
                "durationPerStack": 0,
            })
        upsert_by_id(side_buffs, {
            "id": f"side_buff_homm3_stronghold_warcry_{mode}_effect_sub_skill_4",
            "infinite": True,
            "canDispel": True,
            "tags": [f"side_buff_homm3_stronghold_warcry_{mode}_effect"],
            "heroStat": {stat: 1},
        })
        upsert_by_id(side_infos, {
            "id": f"side_buff_homm3_stronghold_warcry_{mode}_sub_skill_4",
            "sid": f"side_buff_homm3_stronghold_warcry_{mode}_effect_sub_skill_4",
            "allegiance": "ally",
            "duration": 9999,
            "durationPerStack": 0,
        })
    dump_root(all_data, SIDE_BUFFS_PATH, side_buffs)
    dump_root(all_data, SIDE_BUFF_INFOS_PATH, side_infos)

    warcry_unit_buff_rows = make_warcry_unit_buff_rows()
    for path in (SUB_SKILL_UNIT_BUFFS_PATH, SUB_SKILL_ABILITY_UNIT_BUFFS_PATH, SPACE_MAGIC_BUFFS_PATH):
        unit_buffs = array_root(all_data, path)
        for row in warcry_unit_buff_rows:
            upsert_by_id(unit_buffs, row)
        dump_root(all_data, path, unit_buffs)

    patch_warcry_unit_buff_lang(all_data)

    patch_skill_roll_table(all_data, DUNGEON_MIGHT_TABLE_PATH, STRONGHOLD_MIGHT_TABLE_PATH, "homm3_stronghold_might_skills_table")
    patch_skill_roll_table(all_data, DUNGEON_MAGIC_TABLE_PATH, STRONGHOLD_MAGIC_TABLE_PATH, "homm3_stronghold_magic_skills_table")
    patch_skill_roll_table(
        all_data,
        DUNGEON_ARENA_MIGHT_TABLE_PATH,
        STRONGHOLD_ARENA_MIGHT_TABLE_PATH,
        "arenaGame_homm3_stronghold_might_skills_table",
        "arena_skill_faction_dungeon",
        "arena_skill_faction_homm3_stronghold",
    )
    patch_skill_roll_table(
        all_data,
        DUNGEON_ARENA_MAGIC_TABLE_PATH,
        STRONGHOLD_ARENA_MAGIC_TABLE_PATH,
        "arenaGame_homm3_stronghold_magic_skills_table",
        "arena_skill_faction_dungeon",
        "arena_skill_faction_homm3_stronghold",
    )


def upsert_lang_token(root: dict, sid: str, text: str) -> bool:
    tokens = root.get("tokens")
    if not isinstance(tokens, list):
        return False
    for token in tokens:
        if isinstance(token, dict) and token.get("sid") == sid:
            if token.get("text") != text:
                token["text"] = text
                return True
            return False
    tokens.append({"sid": sid, "text": text})
    return True


def upsert_lang_args(root: dict, sid: str, args: list[str]) -> bool:
    tokens_args = root.get("tokensArgs")
    if not isinstance(tokens_args, list):
        return False
    for token in tokens_args:
        if isinstance(token, dict) and token.get("sid") == sid:
            if token.get("args") != args:
                token["args"] = args
                return True
            return False
    tokens_args.append({"sid": sid, "args": args})
    return True


def patch_warcry_unit_buff_lang(all_data: dict[str, bytes]) -> int:
    if "Lang/args/magic_buff.json" not in all_data:
        return 0
    changed = 0
    arg_by_mode = {
        "moral": "current_buff_moral_param",
        "luck": "current_buff_luck_param",
        "initiative": "current_buff_initiative_param",
    }
    args_path = "Lang/args/magic_buff.json"
    args_root = json.loads(all_data[args_path].decode("utf-8-sig"))

    text_roots: dict[str, dict] = {}
    for path in sorted(p for p in all_data if p.startswith("Lang/") and p.endswith("/texts/magic_buff.json")):
        text_roots[path] = json.loads(all_data[path].decode("utf-8-sig"))

    for mode, label in WARCRY_UNIT_STAT_LABELS.items():
        for negative in (False, True):
            sid = warcry_unit_buff_description_id(mode, negative=negative)
            text = f"{'-' if negative else '+'}" + "{0} " + f"{label}."
            if upsert_lang_args(args_root, sid, [arg_by_mode[mode]]):
                changed += 1
            for root in text_roots.values():
                if upsert_lang_token(root, sid, text):
                    changed += 1

    all_data[args_path] = json.dumps(args_root, ensure_ascii=False, indent="\t").encode("utf-8")
    for path, root in text_roots.items():
        all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")
    return changed


def update_warcry_unit_buff_lang_loose() -> int:
    changed = 0
    arg_by_mode = {
        "moral": "current_buff_moral_param",
        "luck": "current_buff_luck_param",
        "initiative": "current_buff_initiative_param",
    }
    args_path = PLAYTEST_LANG_ROOT / "args" / "magic_buff.json"
    if args_path.exists():
        root = json.loads(args_path.read_text(encoding="utf-8-sig"))
        for mode in WARCRY_UNIT_STAT_LABELS:
            for negative in (False, True):
                sid = warcry_unit_buff_description_id(mode, negative=negative)
                if upsert_lang_args(root, sid, [arg_by_mode[mode]]):
                    changed += 1
        args_path.write_text(json.dumps(root, ensure_ascii=False, indent="\t"), encoding="utf-8")

    for text_path in sorted(PLAYTEST_LANG_ROOT.glob("*/texts/magic_buff.json")):
        root = json.loads(text_path.read_text(encoding="utf-8-sig"))
        for mode, label in WARCRY_UNIT_STAT_LABELS.items():
            for negative in (False, True):
                sid = warcry_unit_buff_description_id(mode, negative=negative)
                text = f"{'-' if negative else '+'}" + "{0} " + f"{label}."
                if upsert_lang_token(root, sid, text):
                    changed += 1
        text_path.write_text(json.dumps(root, ensure_ascii=False, indent="\t"), encoding="utf-8")
    return changed


def clone_sub_classes_for_homm3_stronghold(all_data: dict[str, bytes]) -> None:
    """sub_classes_{fraction}.json — fixes 'Can't find sub_class_config for hero: homm3_stronghold_hero_*'."""
    src = json.loads(all_data[DUNGEON_SUB_CLASSES_PATH].decode("utf-8-sig"))
    out = copy.deepcopy(src)
    for item in out.get("array") or []:
        item["faction"] = FRACTION_ID
        hid = item.get("id")
        if isinstance(hid, str):
            item["id"] = hid.replace("sub_class_dungeon_", "sub_class_homm3_stronghold_")
            if "_might_" in item["id"]:
                item["name"] = "sub_class_homm3_stronghold_might_name"
            elif "_magic_" in item["id"]:
                item["name"] = "sub_class_homm3_stronghold_magic_name"
        # Keep desc/icon sids (sub_class_dungeon_* / icons) so Lang/art still resolve.
    all_data[STRONGHOLD_SUB_CLASSES_PATH] = json.dumps(
        out, ensure_ascii=False, indent="\t"
    ).encode("utf-8")


def ensure_base_sub_classes_files(all_data: dict[str, bytes]) -> int:
    """
    Heal missing vanilla faction subclass files that some prior generators removed.
    Keeps session startup stable by guaranteeing demon/nature hero subclass lookups resolve.
    """
    src = json.loads(all_data[DUNGEON_SUB_CLASSES_PATH].decode("utf-8-sig"))
    restored = 0
    for faction, path in (
        ("demon", DEMON_SUB_CLASSES_PATH),
        ("nature", NATURE_SUB_CLASSES_PATH),
    ):
        if path in all_data:
            continue
        out = copy.deepcopy(src)
        for item in out.get("array") or []:
            hid = item.get("id")
            item["faction"] = faction
            if isinstance(hid, str):
                item["id"] = hid.replace("sub_class_dungeon_", f"sub_class_{faction}_")
        all_data[path] = json.dumps(out, ensure_ascii=False, indent="\t").encode("utf-8")
        restored += 1
    return restored


def fix_hero_id_strings(s: str) -> str:
    """dungeon_hero_N -> homm3_stronghold_hero_N"""
    return s.replace("dungeon_hero_", f"{HERO_PREFIX}_")


def stronghold_manifest() -> dict:
    global _STRONGHOLD_MANIFEST
    if _STRONGHOLD_MANIFEST is None:
        _STRONGHOLD_MANIFEST = read_jsonc(STRONGHOLD_MANIFEST_PATH)
    return _STRONGHOLD_MANIFEST


def apply_homm3_table_start_squad(h: dict, hero_idx: int) -> bool:
    """Replace cloned Dungeon/OE starter armies with the HoMM3/HotA table for this hero slot."""
    names = FALLBACK_HERO_NAMES.get(FRACTION_ID) or []
    if hero_idx < 1 or hero_idx > len(names):
        return False
    hero_name = names[hero_idx - 1]
    source_rows = (BASE_HOTA_START_ARMIES.get(FRACTION_ID) or {}).get(hero_name)
    if not source_rows:
        return False
    squad = h3_army_rows_to_start_squad(stronghold_manifest(), source_rows)
    if not squad:
        return False
    h["startSquad"] = squad
    h["startSquadAlt"] = [{"sid": squad[0]["sid"], "min": 1, "max": 1}]
    return True


def morph_hero_record(h: dict) -> None:
    h["id"] = fix_hero_id_strings(h["id"])
    h["specialization"] = fix_hero_id_strings(h["specialization"])
    # Keep Dungeon mesh/mounts; use HoMM3 icon keys for every Stronghold hero slot.
    # Runtime portrait cache aliases 17-18 to existing HoMM3 portraits until real bonus-slot art exists.
    try:
        hero_idx = int(str(h["id"]).rsplit("_", 1)[1])
    except (KeyError, ValueError):
        hero_idx = 0
    if 1 <= hero_idx <= 18:
        h["icon"] = f"hero_homm3_stronghold_{hero_idx}"
    h["fraction"] = FRACTION_ID
    if h.get("classType") == "magic":
        h["skillsRollVariant"] = "homm3_stronghold_magic_skills_table"
    else:
        h["skillsRollVariant"] = "homm3_stronghold_might_skills_table"
    patch = HERO_START_PATCHES.get(hero_idx)
    if patch is not None:
        skill_sid, magic_sid = patch
        h["startSkills"] = [{"sid": "skill_faction_homm3_stronghold", "skillLevel": 1}]
        if skill_sid:
            h["startSkills"].append({"sid": skill_sid, "skillLevel": 1})
        h["startMagics"] = [] if magic_sid is None else [{"sidConfig": magic_sid, "level": 1, "isLearned": True}]
    for skill in h.get("startSkills") or []:
        if isinstance(skill, dict) and skill.get("sid") == "skill_faction_dungeon":
            skill["sid"] = "skill_faction_homm3_stronghold"
    if not USE_DUNGEON_START_SQUADS:
        try:
            hero_idx = int(str(h["id"]).rsplit("_", 1)[1])
        except (KeyError, ValueError):
            hero_idx = 0
        if not apply_homm3_table_start_squad(h, hero_idx):
            remap_unit_strings(h.get("startSquad"))
            remap_unit_strings(h.get("startSquadAlt"))


def morph_specializations(data: dict) -> dict:
    out = copy.deepcopy(data)
    for item in out.get("array") or []:
        for key in ("id", "name", "desc"):
            if key in item and isinstance(item[key], str):
                item[key] = fix_hero_id_strings(item[key])
        remap_unit_strings(item)
        try:
            hero_idx = int(str(item.get("id", "")).split("_hero_", 1)[1].split("_", 1)[0])
        except (IndexError, ValueError):
            hero_idx = 0
        ability_sid = "skill_mage_ability" if hero_idx >= 10 else "skill_warrior_ability"
        bonuses = make_homm3_stronghold_specialization_bonuses(hero_idx, ability_sid)
        if bonuses is not None:
            item["bonuses"] = bonuses
    return out


def maybe_remap_unit_strings(obj: object) -> None:
    if not USE_DUNGEON_START_SQUADS:
        remap_unit_strings(obj)


def patch_arena_game_heroes(all_data: dict[str, bytes]) -> int:
    root = json.loads(all_data[ARENA_GAME_PATH].decode("utf-8-sig"))
    heroes = root.get("heroes")
    if not isinstance(heroes, list):
        raise RuntimeError(f"{ARENA_GAME_PATH}: expected heroes list")

    heroes[:] = [
        item
        for item in heroes
        if not (isinstance(item, dict) and str(item.get("sid", "")).startswith(f"{HERO_PREFIX}_"))
    ]
    dungeon_arena_by_sid = {
        item.get("sid"): item
        for item in heroes
        if isinstance(item, dict) and isinstance(item.get("sid"), str) and item["sid"].startswith("dungeon_hero_")
    }
    existing = {item.get("sid") for item in heroes if isinstance(item, dict)}
    added = 0
    for i in range(1, 19):
        dungeon_sid = f"dungeon_hero_{i}"
        stronghold_sid = f"{HERO_PREFIX}_{i}"
        source = dungeon_arena_by_sid.get(dungeon_sid)
        if source is None:
            hero_path = f"DB/heroes/dungeon/{dungeon_sid}.json"
            hero = json.loads(all_data[hero_path].decode("utf-8-sig"))["array"][0]
            class_type = hero.get("classType") if hero.get("classType") in ("might", "magic") else "might"
            source = {
                "sid": dungeon_sid,
                "skills": f"arenaGame_dungeon_{class_type}_skills_table",
                "chance": 125 if class_type == "magic" else 107,
                "itemsSubgroupModifier": class_type,
                "startSkills": [],
                "startMagics": [],
                "startItems": [],
                "unitsModifier": [],
            }
        clone = copy.deepcopy(source)
        clone["sid"] = stronghold_sid
        skills_table = str(clone.get("skills", ""))
        class_type = "magic" if "_magic_" in skills_table else "might"
        clone["skills"] = f"arenaGame_homm3_stronghold_{class_type}_skills_table"
        maybe_remap_unit_strings(clone.get("unitsModifier"))
        if stronghold_sid in existing:
            continue
        heroes.append(clone)
        existing.add(stronghold_sid)
        added += 1

    if added != 18:
        raise RuntimeError(f"{ARENA_GAME_PATH}: expected to add 18 {HERO_PREFIX} rows, added {added}")
    all_data[ARENA_GAME_PATH] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")
    return added


def patch_arena_pick_content(all_data: dict[str, bytes]) -> int:
    root = json.loads(all_data[ARENA_PICK_CONTENT_PATH].decode("utf-8-sig"))
    content = root.get("content")
    if not isinstance(content, list):
        raise RuntimeError(f"{ARENA_PICK_CONTENT_PATH}: expected content list")

    added = 0
    for block in content:
        if not isinstance(block, dict) or block.get("sid") != "heroes":
            continue
        arr = block.get("array")
        if not isinstance(arr, list):
            raise RuntimeError(f"{ARENA_PICK_CONTENT_PATH}: expected heroes array")
        arr[:] = [
            item
            for item in arr
            if not (isinstance(item, dict) and str(item.get("sid", "")).startswith(f"{HERO_PREFIX}_"))
        ]
        existing = {item.get("sid") for item in arr if isinstance(item, dict)}
        source_count = 0
        for item in list(arr):
            if not isinstance(item, dict):
                continue
            sid = item.get("sid")
            if not isinstance(sid, str) or not sid.startswith("dungeon_hero_"):
                continue
            source_count += 1
            clone = copy.deepcopy(item)
            clone["sid"] = fix_hero_id_strings(sid)
            if clone["sid"] in existing:
                continue
            arr.append(clone)
            existing.add(clone["sid"])
            added += 1
        break

    if added != source_count:
        raise RuntimeError(
            f"{ARENA_PICK_CONTENT_PATH}: expected to add {source_count} {HERO_PREFIX} hero picks, added {added}"
        )
    all_data[ARENA_PICK_CONTENT_PATH] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")
    return added


def patch_arena_pick_mods(all_data: dict[str, bytes]) -> int:
    root = json.loads(all_data[ARENA_PICK_MODS_PATH].decode("utf-8-sig"))
    arr = root.get("array")
    if not isinstance(arr, list):
        raise RuntimeError(f"{ARENA_PICK_MODS_PATH}: expected array list")

    def mentions_stronghold_hero(item: dict) -> bool:
        because = item.get("becauseOf")
        return isinstance(because, list) and any(
            isinstance(s, str) and s.startswith(f"{HERO_PREFIX}_") for s in because
        )

    arr[:] = [item for item in arr if not (isinstance(item, dict) and mentions_stronghold_hero(item))]
    existing = {json.dumps(item, sort_keys=True) for item in arr if isinstance(item, dict)}
    added = 0
    for item in list(arr):
        if not isinstance(item, dict):
            continue
        because = item.get("becauseOf")
        if not isinstance(because, list) or not any(
            isinstance(s, str) and s.startswith("dungeon_hero_") for s in because
        ):
            continue
        clone = copy.deepcopy(item)
        clone["becauseOf"] = [
            fix_hero_id_strings(s) if isinstance(s, str) and s.startswith("dungeon_hero_") else s
            for s in because
        ]
        maybe_remap_unit_strings(clone.get("who"))
        key = json.dumps(clone, sort_keys=True)
        if key in existing:
            continue
        arr.append(clone)
        existing.add(key)
        added += 1

    all_data[ARENA_PICK_MODS_PATH] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")
    return added


def patch_skills_by_level_replace_table(all_data: dict[str, bytes]) -> int:
    root = json.loads(all_data[SKILLS_BY_LEVEL_REPLACE_PATH].decode("utf-8-sig"))
    arr = root.get("array")
    if not isinstance(arr, list):
        raise RuntimeError(f"{SKILLS_BY_LEVEL_REPLACE_PATH}: expected array list")

    arr[:] = [
        item
        for item in arr
        if not (isinstance(item, dict) and str(item.get("id", "")).startswith(f"{HERO_PREFIX}_"))
    ]
    existing = {item.get("id") for item in arr if isinstance(item, dict)}
    added = 0
    for item in list(arr):
        if not isinstance(item, dict):
            continue
        hid = item.get("id")
        if not isinstance(hid, str) or not hid.startswith("dungeon_hero_"):
            continue
        clone = copy.deepcopy(item)
        clone["id"] = fix_hero_id_strings(hid)
        for block in clone.get("defaultList") or []:
            for chance in block.get("rollChances") or []:
                if isinstance(chance, dict) and chance.get("sid") == "skill_faction_dungeon":
                    chance["sid"] = "skill_faction_homm3_stronghold"
        if clone["id"] in existing:
            continue
        arr.append(clone)
        existing.add(clone["id"])
        added += 1

    all_data[SKILLS_BY_LEVEL_REPLACE_PATH] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")
    return added


def patch_quick_game_hero_tables(all_data: dict[str, bytes]) -> tuple[int, int, int, int]:
    return (
        patch_arena_game_heroes(all_data),
        patch_arena_pick_content(all_data),
        patch_arena_pick_mods(all_data),
        patch_skills_by_level_replace_table(all_data),
    )


def merge_hero_info_from_dungeon_copies() -> int:
    """
    Add homm3_stronghold heroInfo tokens for all locales by cloning dungeon_hero_* tokens
    from each locale's own heroInfo.json.
    """
    total_added = 0
    for hero_info_path in sorted(PLAYTEST_LANG_ROOT.glob("*/texts/heroInfo.json")):
        pt = json.loads(hero_info_path.read_text(encoding="utf-8-sig"))
        existing = {t["sid"] for t in pt.get("tokens", []) if "sid" in t}

        added = []
        for t in pt.get("tokens", []):
            sid = t.get("sid")
            if not isinstance(sid, str) or not sid.startswith("dungeon_hero_"):
                continue
            new_sid = fix_hero_id_strings(sid)
            if new_sid in existing:
                continue
            new_t = copy.deepcopy(t)
            new_t["sid"] = new_sid
            added.append(new_t)
            existing.add(new_sid)

        if not added:
            continue

        pt["tokens"].extend(added)
        hero_info_path.write_text(
            json.dumps(pt, ensure_ascii=False, indent="\t") + "\n",
            encoding="utf-8",
        )
        total_added += len(added)
        print(f"Merged {len(added)} homm3_stronghold hero token(s) into {hero_info_path}")

    if total_added == 0:
        print("heroInfo.json already contains homm3_stronghold hero tokens in all locales; skipping merge.")
    return total_added


def update_stronghold_hero_info_overrides() -> int:
    """
    Keep visible Stronghold hero specialization text aligned with the generated
    bonus rows. Non-English locales receive English fallback text until proper
    localized copies are chosen.
    """
    total_changed = 0
    for hero_info_path in sorted(PLAYTEST_LANG_ROOT.glob("*/texts/heroInfo.json")):
        pt = json.loads(hero_info_path.read_text(encoding="utf-8-sig"))
        tokens = pt.get("tokens")
        if not isinstance(tokens, list):
            continue

        by_sid = {
            t.get("sid"): t
            for t in tokens
            if isinstance(t, dict) and isinstance(t.get("sid"), str)
        }
        changed = 0
        for sid, text in stronghold_heroinfo_override_items().items():
            existing = by_sid.get(sid)
            if existing is None:
                tokens.append({"sid": sid, "text": text})
                changed += 1
            elif existing.get("text") != text:
                existing["text"] = text
                changed += 1

        if changed == 0:
            continue

        hero_info_path.write_text(
            json.dumps(pt, ensure_ascii=False, indent="\t") + "\n",
            encoding="utf-8",
        )
        total_changed += changed
        print(f"Updated {changed} Stronghold heroInfo override token(s) in {hero_info_path}")

    if total_changed == 0:
        print("heroInfo.json Stronghold specialization overrides are already current in all locales.")
    return total_changed


def merge_stronghold_class_name_tokens() -> int:
    """
    Add HoMM3 Stronghold class names to every locale. The English HoMM3 names are
    intentional fallback text for non-English language packs until real localized
    names are chosen.
    """
    total_changed = 0
    for hero_skills_path in sorted(PLAYTEST_LANG_ROOT.glob("*/texts/heroSkills.json")):
        pt = json.loads(hero_skills_path.read_text(encoding="utf-8-sig"))
        tokens = pt.get("tokens")
        if not isinstance(tokens, list):
            continue

        by_sid = {
            t.get("sid"): t
            for t in tokens
            if isinstance(t, dict) and isinstance(t.get("sid"), str)
        }
        changed = 0
        for sid, text in {**STRONGHOLD_CLASS_NAME_TOKENS, **WARCRIES_HERO_SKILL_TOKENS}.items():
            existing = by_sid.get(sid)
            if existing is None:
                tokens.append({"sid": sid, "text": text})
                changed += 1
            elif existing.get("text") != text:
                existing["text"] = text
                changed += 1

        if changed == 0:
            continue

        hero_skills_path.write_text(
            json.dumps(pt, ensure_ascii=False, indent="\t") + "\n",
            encoding="utf-8",
        )
        total_changed += changed
        print(f"Merged/updated {changed} Stronghold class token(s) into {hero_skills_path}")

    if total_changed == 0:
        print("heroSkills.json already contains Stronghold class name tokens in all locales; skipping merge.")
    return total_changed


def main(core_path: Path | None = None, core_only: bool = False) -> None:
    """Patch ``core_path`` in place.

    ``core_only`` is the vanilla-rebuild seed mode used by
    tools/port_current/rebuild_core_from_vanilla.py: it rewrites only the given
    Core.zip copy. It writes no ``.bak`` beside it and skips the loose playtest
    ``StreamingAssets/Lang`` merges, which target the playtest install, not the
    Core under construction.
    """
    target_core = (core_path or PLAYTEST_CORE).resolve()
    if not target_core.exists():
        raise SystemExit(f"Missing Core.zip: {target_core}")
    if core_only and core_path is None:
        raise SystemExit("--core-only requires an explicit --core")

    backup = target_core.with_suffix(".zip.bak_before_homm3_stronghold_heroes")
    if not core_only and not backup.exists():
        backup.write_bytes(target_core.read_bytes())

    with zipfile.ZipFile(target_core, "r") as zin:
        zip_entries = {i.filename: i for i in zin.infolist()}
        all_data: dict[str, bytes] = {name: zin.read(name) for name in zin.namelist()}

    cleanup_broken_homm3_faction_skill_clone(all_data)
    patch_homm3_stronghold_warcries_skill(all_data)
    restored_base_subclasses = ensure_base_sub_classes_files(all_data)
    clone_sub_classes_for_homm3_stronghold(all_data)

    for i in range(1, 19):
        inner = f"DB/heroes/dungeon/dungeon_hero_{i}.json"
        data = json.loads(all_data[inner].decode("utf-8-sig"))
        hero = copy.deepcopy(data["array"][0])
        morph_hero_record(hero)
        raw = json.dumps({"array": [hero]}, ensure_ascii=False, indent="\t").encode("utf-8")
        all_data[f"DB/heroes/{FRACTION_ID}/{HERO_PREFIX}_{i}.json"] = raw

    specs = json.loads(
        all_data["DB/heroes_specializations/specializations_dungeon.json"].decode("utf-8-sig")
    )
    new_specs = morph_specializations(specs)
    all_data[f"DB/heroes_specializations/specializations_{FRACTION_ID}.json"] = json.dumps(
        new_specs, ensure_ascii=False, indent="\t"
    ).encode("utf-8")
    arena_heroes, pick_heroes, pick_mods, skill_replace = patch_quick_game_hero_tables(all_data)

    with zipfile.ZipFile(target_core, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, blob in sorted(all_data.items()):
            zi = zip_entries.get(name)
            if zi is not None:
                zout.writestr(zi, blob)
            else:
                zout.writestr(name, blob)

    if core_only:
        print(
            f"Patched {target_core} (core-only seed): Warcries skill package, "
            f"sub_classes_homm3_stronghold, 18 {HERO_PREFIX}_* heroes, specializations_{FRACTION_ID}.json, "
            f"quick-game hero tables (arena={arena_heroes}, pick={pick_heroes}, mods={pick_mods}, "
            f"skillReplace={skill_replace}); loose playtest Lang untouched"
        )
        return

    merged_hero_tokens = merge_hero_info_from_dungeon_copies()
    hero_info_overrides = update_stronghold_hero_info_overrides()
    class_name_tokens = merge_stronghold_class_name_tokens()
    warcry_buff_tokens = update_warcry_unit_buff_lang_loose()

    print(
        f"Patched {target_core}: removed {REMOVED_BAD_FACTION_SKILL_SID} if present, "
        f"restored {restored_base_subclasses} missing base sub_classes file(s), "
        f"sub_classes_homm3_stronghold, 18 {HERO_PREFIX}_* heroes, "
        f"specializations_{FRACTION_ID}.json, quick-game hero tables "
        f"(arena={arena_heroes}, pick={pick_heroes}, mods={pick_mods}, skillReplace={skill_replace}), "
        f"merged {merged_hero_tokens} heroInfo token(s), "
        f"updated {hero_info_overrides} Stronghold heroInfo override token(s), "
        f"merged/updated {class_name_tokens} Stronghold class token(s), "
        f"merged/updated {warcry_buff_tokens} Warcry unit-buff token/arg row(s)"
    )
    print(f"Backup (if created): {backup}")


def patch_lang_only() -> None:
    merged_hero_tokens = merge_hero_info_from_dungeon_copies()
    hero_info_overrides = update_stronghold_hero_info_overrides()
    class_name_tokens = merge_stronghold_class_name_tokens()
    warcry_buff_tokens = update_warcry_unit_buff_lang_loose()
    print(
        "Lang-only hero patch applied: "
        f"merged {merged_hero_tokens} heroInfo token(s), "
        f"updated {hero_info_overrides} Stronghold heroInfo override token(s), "
        f"merged/updated {class_name_tokens} Stronghold class token(s), "
        f"merged/updated {warcry_buff_tokens} Warcry unit-buff token/arg row(s)."
    )


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Clone Dungeon heroes for homm3_stronghold.")
    ap.add_argument(
        "--dungeon-start-squads",
        action="store_true",
        help=(
            "Bisect startup death: keep hero startSquad/startSquadAlt on vanilla Dungeon unit SIDs "
            "while still cloning heroes under homm3_stronghold."
        ),
    )
    ap.add_argument(
        "--lang-only",
        action="store_true",
        help="Only update Lang heroInfo/heroSkills JSON; do not rewrite Core.zip.",
    )
    ap.add_argument(
        "--core",
        type=Path,
        default=PLAYTEST_CORE,
        help="Core.zip to patch (defaults to playtest HeroesOE_Data Core.zip).",
    )
    ap.add_argument(
        "--core-only",
        action="store_true",
        help=(
            "Rewrite only the explicit --core archive: no .bak beside it and no loose playtest "
            "Lang writes (vanilla Core rebuild seed layer)."
        ),
    )
    ns = ap.parse_args()
    USE_DUNGEON_START_SQUADS = ns.dungeon_start_squads
    if ns.lang_only and ns.core_only:
        raise SystemExit("--lang-only and --core-only are mutually exclusive")
    if ns.lang_only:
        patch_lang_only()
    else:
        core_arg = ns.core if (ns.core_only or ns.core != PLAYTEST_CORE) else None
        main(core_arg, core_only=ns.core_only)
