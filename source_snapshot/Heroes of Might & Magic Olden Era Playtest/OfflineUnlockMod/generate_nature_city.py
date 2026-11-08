"""
Build a dedicated Grove/Nature law table for the playtest and repoint the shipped
Nature faction to use it.

The playtest already contains a Grove city config with proper building icons and
most Grove city text, but its fraction config still points at human laws and the
English Nature law strings are missing. This script:

* creates `DB/fractions_laws/fractions_laws_table_nature.json`
* updates `DB/fractions/5_nature.json` to use Grove laws and the Nature law scroll
* keeps the shipped Grove city config, only normalizing a few Grove-specific fields
* imports demo Grove law text as the baseline, then applies playtest overrides
* fixes/extends Nature law args, including the missing laws 30 and 31

Run from anywhere:
  python generate_nature_city.py
"""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path

CORE = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Core.zip"
)
PLAYTEST_ROOT = CORE.parents[2]
DEMO_ENGLISH_FACTION_LAWS_PATH = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might & Magic Olden Era Demo"
    r"\HeroesOE_Data\StreamingAssets\Lang\english\texts\factionLaws.json"
)

NATURE_FRACTION_PATH = "DB/fractions/5_nature.json"
NATURE_CITY_PATH = "DB/objects_logic/cities/nature_city.json"
NATURE_LAWS_PATH = "DB/fractions_laws/fractions_laws_table_nature.json"

ENGLISH_FACTION_LAWS_PATH = (
    PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "factionLaws.json"
)
ARGS_FACTION_LAWS_PATH = (
    PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "args" / "factionLaws.json"
)

NATURE_HIRE_SIDS = [
    ["elf_tracker", "elf_tracker_upg", "elf_tracker_upg_alt"],
    ["twinkle", "twinkle_upg", "twinkle_upg_alt"],
    ["ent", "ent_upg", "ent_upg_alt"],
    ["aqualotl", "aqualotl_upg", "aqualotl_upg_alt"],
    ["druid", "druid_upg", "druid_upg_alt"],
    ["qilin", "qilin_upg", "qilin_upg_alt"],
    ["phoenix", "phoenix_upg", "phoenix_upg_alt"],
]

FAUN_RECEIVERS = NATURE_HIRE_SIDS[0]
HOPLET_RECEIVERS = NATURE_HIRE_SIDS[1]
IRIYAD_RECEIVERS = NATURE_HIRE_SIDS[2]
AQUALOTL_RECEIVERS = NATURE_HIRE_SIDS[3]
HERBOMANCER_RECEIVERS = NATURE_HIRE_SIDS[4]
QILIN_RECEIVERS = NATURE_HIRE_SIDS[5]
PHOENIX_RECEIVERS = NATURE_HIRE_SIDS[6]
FAIRY_TALE_RECEIVERS = FAUN_RECEIVERS + HOPLET_RECEIVERS + HERBOMANCER_RECEIVERS

NATURE_FRACTION_LINES = [
    {
        "groups": [
            {"laws": ["fraction_law_nature_1", "fraction_law_nature_2", "fraction_law_nature_3", "fraction_law_nature_4"]},
            {"laws": ["fraction_law_nature_5", "fraction_law_nature_6"]},
        ],
        "countToUnlock": 0,
    },
    {
        "groups": [
            {"laws": ["fraction_law_nature_7", "fraction_law_nature_8", "fraction_law_nature_9"]},
            {"laws": ["fraction_law_nature_10", "fraction_law_nature_11", "fraction_law_nature_12", "fraction_law_nature_13"]},
        ],
        "countToUnlock": 5,
    },
    {
        "groups": [
            {"laws": ["fraction_law_nature_14", "fraction_law_nature_15"]},
            {"laws": ["fraction_law_nature_16", "fraction_law_nature_17", "fraction_law_nature_18", "fraction_law_nature_19"]},
        ],
        "countToUnlock": 15,
    },
    {
        "groups": [
            {"laws": ["fraction_law_nature_20", "fraction_law_nature_21"]},
            {"laws": ["fraction_law_nature_22", "fraction_law_nature_23", "fraction_law_nature_24", "fraction_law_nature_25"]},
        ],
        "countToUnlock": 30,
    },
    {
        "groups": [
            {"laws": ["fraction_law_nature_26", "fraction_law_nature_27"]},
            {"laws": ["fraction_law_nature_28", "fraction_law_nature_29", "fraction_law_nature_30", "fraction_law_nature_31"]},
        ],
        "countToUnlock": 50,
    },
]

# Use the demo Nature block as the primary English source, then patch the entries
# that are still placeholder-like or that no longer match the mechanics we can wire
# up safely in the playtest data.
NATURE_LAW_TEXT_OVERRIDES = {
    "fraction_law_nature_4_desc": (
        "Provides a one-time bonus of {0} Gold, {1} Wood, and {2} Ore when enacted."
    ),
    "fraction_law_nature_5_desc": (
        "Fauns growth in your cities increases by {0}. They deal +{1}% Damage."
    ),
    "fraction_law_nature_6_desc": (
        "Hoplets growth in your cities increases by {0}. Their min. Damage increases by {1}."
    ),
    "fraction_law_nature_11_desc": "Friendly creatures deal {0}% more Damage.",
    "fraction_law_nature_14_desc": "Primal spells of your heroes gain {0} level(s).",
    "fraction_law_nature_15_desc": (
        "Provides a one-time bonus of {0} Gold, {1} Wood, and {2} Ore when enacted."
    ),
    "fraction_law_nature_17_desc": (
        "On native terrain, Attack and Defence of friendly creatures increase by {0}."
    ),
    "fraction_law_nature_22_desc": (
        "Herbomancers growth in your cities increases by {0}. Their Damage increases by {1}%."
    ),
    "fraction_law_nature_24_desc": "Friendly creatures gain +{0}% Lucky Strike chance.",
    "fraction_law_nature_25_desc": (
        "Each level increases the basic Damage of your heroes' Heroic Strike."
    ),
    "fraction_law_nature_26_desc": (
        "Provides a one-time bonus of {0} Gold, {1} Wood, and {2} Ore when enacted."
    ),
    "fraction_law_nature_29_desc": "Friendly Grove abilities cost –{0} Focus Charge(s).",
    "fraction_law_nature_30_name": "Stars Between Boughs",
    "fraction_law_nature_30_desc": "Gain {0} Astrology experience.",
    "fraction_law_nature_31_name": "Murmuring",
    "fraction_law_nature_31_desc": (
        "Friendly heroes gain {0} Focus Charge(s) at the start of each round."
    ),
}

NATURE_LAW_ARGS_OVERRIDES = {
    "fraction_law_nature_4_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modInt_bonuses_1_parameters_1",
        "current_law_modInt_bonuses_2_parameters_1",
    ],
    "fraction_law_nature_5_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modPercent_bonuses_1_parameters_1",
    ],
    "fraction_law_nature_6_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modInt_bonuses_1_parameters_1",
    ],
    "fraction_law_nature_9_desc": [],
    "fraction_law_nature_11_desc": ["current_law_modPercent_bonuses_0_parameters_1"],
    "fraction_law_nature_14_desc": ["current_law_modInt_bonuses_0_parameters_3"],
    "fraction_law_nature_15_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modInt_bonuses_1_parameters_1",
        "current_law_modInt_bonuses_2_parameters_1",
    ],
    "fraction_law_nature_17_desc": ["current_law_modInt_bonuses_0_parameters_1"],
    "fraction_law_nature_22_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modPercent_bonuses_1_parameters_1",
    ],
    "fraction_law_nature_24_desc": ["current_law_modPercent_bonuses_0_parameters_1"],
    "fraction_law_nature_25_desc": [],
    "fraction_law_nature_26_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modInt_bonuses_1_parameters_1",
        "current_law_modInt_bonuses_2_parameters_1",
    ],
    "fraction_law_nature_29_desc": ["current_law_modInt_bonuses_0_parameters_1"],
    "fraction_law_nature_30_desc": ["current_law_modInt_bonuses_0_parameters_0"],
    "fraction_law_nature_31_desc": ["current_law_modInt_bonuses_0_parameters_1"],
}


def b(bonus_type: str, parameters: list[str] | None = None, **extra) -> dict:
    out = {"type": bonus_type}
    if parameters is not None:
        out["parameters"] = parameters
    out.update(extra)
    return out


def side_one_time_add_res(name: str, amount: int) -> dict:
    return b("sideOneTimeAddRes", [name, str(amount)])


def side_res(name: str, amount: int) -> dict:
    return b("sideRes", [name, str(amount)])


def city_units_increment(unit_id: str, amount: int) -> dict:
    return b("cityUnitsIncrement", [unit_id, str(amount)])


def hero_stat(name: str, value: str, **extra) -> dict:
    return b("heroStat", [name, value], **extra)


def hero_bool(name: str, value: bool = True, **extra) -> dict:
    return b("heroStat", [name, str(value).lower()], **extra)


def side_stat(name: str, value: str, **extra) -> dict:
    return b("sideStat", [name, value], **extra)


def unit_stat(receivers: list[str] | None, parameters: list[str], **extra) -> dict:
    bonus = b("unitStat", parameters, **extra)
    if receivers is not None:
        bonus["receivers"] = receivers
    return bonus


def battle_subskill_bonus(kind: str, sid: str, **extra) -> dict:
    return b("battleSubskillBonus", [kind, sid], **extra)


def law(law_id: str, levels: list[tuple[int, list[dict]]]) -> dict:
    return {
        "id": law_id,
        "icon": f"{law_id}_icon",
        "name": f"{law_id}_name",
        "desc": f"{law_id}_desc",
        "parametersPerLevel": [{"cost": cost, "bonuses": bonuses} for cost, bonuses in levels],
    }


NATURE_LAWS = {
    "array": [
        law("fraction_law_nature_1", [(2, [side_res("gold", 250)]), (2, [side_res("gold", 500)])]),
        law("fraction_law_nature_2", [(3, [hero_stat("intelligence", "1")]), (3, [hero_stat("intelligence", "2")])]),
        law(
            "fraction_law_nature_3",
            [(2, [side_stat("heroCostPerBonus", "-0.10")]), (2, [side_stat("heroCostPerBonus", "-0.20")])],
        ),
        law(
            "fraction_law_nature_4",
            [(1, [side_one_time_add_res("gold", 2500), side_one_time_add_res("wood", 5), side_one_time_add_res("ore", 5)])],
        ),
        law(
            "fraction_law_nature_5",
            [(3, [city_units_increment("elf_tracker", 4), unit_stat(FAUN_RECEIVERS, ["outAllDmgMod", "0.10"])])],
        ),
        law(
            "fraction_law_nature_6",
            [(3, [city_units_increment("twinkle", 4), unit_stat(HOPLET_RECEIVERS, ["damageMin", "1"])])],
        ),
        law(
            "fraction_law_nature_7",
            [(2, [hero_stat("viewRadius", "1"), hero_stat("movementBonus", "10")]), (2, [hero_stat("viewRadius", "2"), hero_stat("movementBonus", "20")])],
        ),
        law(
            "fraction_law_nature_8",
            [(2, [b("constructionDiscount", ["wood", "-0.20"])]), (2, [b("constructionDiscount", ["wood", "-0.40"])])],
        ),
        law("fraction_law_nature_9", [(4, [hero_bool("enableDisguise")])]),
        law(
            "fraction_law_nature_10",
            [(3, [city_units_increment("ent", 4), unit_stat(IRIYAD_RECEIVERS, ["hp", "5"])])],
        ),
        law(
            "fraction_law_nature_11",
            [(3, [unit_stat(None, ["outAllDmgMod", "0.10"])]), (3, [unit_stat(None, ["outAllDmgMod", "0.20"])])],
        ),
        law(
            "fraction_law_nature_12",
            [(3, [unit_stat(None, ["inComingDebuffDuration", "-1"])]), (3, [unit_stat(None, ["inComingDebuffDuration", "-2"])])],
        ),
        law("fraction_law_nature_13", [(2, [side_res("crystals", 1)]), (2, [side_res("crystals", 2)])]),
        law("fraction_law_nature_14", [(3, [b("heroStat", ["magicSchoolSet", "primal", "0", "1"])])]),
        law(
            "fraction_law_nature_15",
            [(2, [side_one_time_add_res("gold", 5000), side_one_time_add_res("wood", 10), side_one_time_add_res("ore", 10)])],
        ),
        law(
            "fraction_law_nature_16",
            [
                (
                    3,
                    [
                        city_units_increment("aqualotl", 2),
                        unit_stat(AQUALOTL_RECEIVERS, ["initiative", "1"]),
                        unit_stat(AQUALOTL_RECEIVERS, ["speed", "1"]),
                    ],
                )
            ],
        ),
        law(
            "fraction_law_nature_17",
            [
                (
                    4,
                    [
                        unit_stat(None, ["offence", "1"], biomeType="native"),
                        unit_stat(None, ["defence", "1"], biomeType="native"),
                    ],
                ),
                (
                    4,
                    [
                        unit_stat(None, ["offence", "2"], biomeType="native"),
                        unit_stat(None, ["defence", "2"], biomeType="native"),
                    ],
                ),
            ],
        ),
        law(
            "fraction_law_nature_18",
            [(3, [side_stat("tempMagicLevelBonus", "1")]), (3, [side_stat("tempMagicLevelBonus", "2")])],
        ),
        law("fraction_law_nature_19", [(4, [hero_stat("maxEnergyLevelsBonus", "1")])]),
        law(
            "fraction_law_nature_20",
            [(4, [side_stat("unitsFromBarracksIncrementPerBonus", "0.50")]), (4, [side_stat("unitsFromBarracksIncrementPerBonus", "1.00")])],
        ),
        law("fraction_law_nature_21", [(5, [hero_bool("enableBattleEscapeBan")])]),
        law(
            "fraction_law_nature_22",
            [(3, [city_units_increment("druid", 1), unit_stat(HERBOMANCER_RECEIVERS, ["outAllDmgMod", "0.10"])])],
        ),
        law(
            "fraction_law_nature_23",
            [
                (
                    3,
                    [
                        city_units_increment("qilin", 1),
                        unit_stat(QILIN_RECEIVERS, ["damageMin", "2"]),
                        unit_stat(QILIN_RECEIVERS, ["damageMax", "2"]),
                    ],
                )
            ],
        ),
        law(
            "fraction_law_nature_24",
            [
                (3, [unit_stat(None, ["critChanceModifier", "0.01"])]),
                (3, [unit_stat(None, ["critChanceModifier", "0.02"])]),
                (3, [unit_stat(None, ["critChanceModifier", "0.03"])]),
            ],
        ),
        law(
            "fraction_law_nature_25",
            [
                (
                    3,
                    [
                        battle_subskill_bonus("hero_ability", "skill_warrior_ability_law_nature_base_1"),
                        battle_subskill_bonus("hero_ability", "skill_mage_ability_law_nature_base_1"),
                    ],
                ),
                (
                    3,
                    [
                        battle_subskill_bonus("hero_ability", "skill_warrior_ability_law_nature_base_2"),
                        battle_subskill_bonus("hero_ability", "skill_mage_ability_law_nature_base_2"),
                    ],
                ),
            ],
        ),
        law(
            "fraction_law_nature_26",
            [(3, [side_one_time_add_res("gold", 7500), side_one_time_add_res("wood", 15), side_one_time_add_res("ore", 15)])],
        ),
        law(
            "fraction_law_nature_27",
            [(3, [city_units_increment("phoenix", 1), unit_stat(PHOENIX_RECEIVERS, ["damageMax", "6"])])],
        ),
        law(
            "fraction_law_nature_28",
            [
                (
                    4,
                    [
                        unit_stat(FAIRY_TALE_RECEIVERS, ["speed", "1"]),
                        unit_stat(FAIRY_TALE_RECEIVERS, ["initiative", "1"]),
                    ],
                )
            ],
        ),
        law("fraction_law_nature_29", [(4, [hero_stat("energyPerLevelDiscount", "1")])]),
        law(
            "fraction_law_nature_30",
            [(2, [b("astrologyExp", ["250", "0.0"])]), (2, [b("astrologyExp", ["500", "0.0"])]), (2, [b("astrologyExp", ["750", "0.0"])])],
        ),
        law("fraction_law_nature_31", [(4, [hero_stat("energyLevelsPerRoundBonus", "1")])]),
    ]
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def get_building(city: dict, sid: str) -> dict:
    for value in city.values():
        if isinstance(value, list):
            for item in value:
                if isinstance(item, dict) and item.get("sid") == sid:
                    return item
    raise KeyError(f"Missing city building: {sid}")


def set_level(building: dict, level: int, *, x: int, y: int, prev: list[dict]) -> None:
    params = building["parametersPerLevel"][level - 1]
    params["nodePos"] = {"xPos": x, "yPos": y}
    params["prevBuildings"] = copy.deepcopy(prev)


def set_costs(building: dict, level: int, costs: list[tuple[str, int]]) -> None:
    building["parametersPerLevel"][level - 1]["costs"] = [
        {"name": name, "cost": cost} for name, cost in costs
    ]


def ensure_nature_magic_guild_level_5(city: dict) -> None:
    magic_guild = city["magicGuilds"][0]
    magic_guild["icons"] = [
        "G_build_Mage_Guild_Level_1",
        "G_build_Mage_Guild_Level_2",
        "G_build_Mage_Guild_Level_3",
        "G_build_Mage_Guild_Level_4",
        "G_build_Mage_Guild_Level_5",
    ]
    magic_guild["names"] = [
        "Nature_Build_Magic_Guild_name_level_1",
        "Nature_Build_Magic_Guild_name_level_2",
        "Nature_Build_Magic_Guild_name_level_3",
        "Nature_Build_Magic_Guild_name_level_4",
        "Nature_Build_Magic_Guild_name_level_5",
    ]
    magic_guild["descriptions"] = [
        "Nature_Build_Magic_Guild_description_level_1",
        "Nature_Build_Magic_Guild_description_level_2",
        "Nature_Build_Magic_Guild_description_level_3",
        "Nature_Build_Magic_Guild_description_level_4",
        "Nature_Build_Magic_Guild_description_level_5",
    ]
    magic_guild["narrativeDescriptions"] = [
        "Nature_Build_Magic_Guild_narrativeDescription",
        "Nature_Build_Magic_Guild_narrativeDescription",
        "Nature_Build_Magic_Guild_narrativeDescription",
        "Nature_Build_Magic_Guild_narrativeDescription",
        "Nature_Build_Magic_Guild_narrativeDescription",
    ]
    magic_guild["backgroundImages"] = [
        "build_fon_magic",
        "build_fon_magic",
        "build_fon_magic",
        "build_fon_magic",
        "build_fon_magic",
    ]
    if len(magic_guild.get("parametersPerLevel", [])) >= 5:
        return

    magic_guild["parametersPerLevel"].append(
        {
            "prevBuildings": [{"sid": "Build_Magic_Guild", "level": 4}],
            "nodePos": {"xPos": 8, "yPos": 4},
            "costs": [
                {"name": "gold", "cost": 5000},
                {"name": "ore", "cost": 5},
                {"name": "wood", "cost": 5},
                {"name": "gemstones", "cost": 5},
                {"name": "crystals", "cost": 5},
                {"name": "mercury", "cost": 5},
            ],
        }
    )


def patch_city_costs(city: dict) -> None:
    # The shipped Nature economy is a straight Human/Temple placeholder pass.
    # Retune the Grove-specific rare-resource pressure toward crystals while
    # leaving globally standardized support buildings like Mage Guild alone.
    set_costs(
        get_building(city, "Build_Tier_4"),
        1,
        [("gold", 3000), ("crystals", 6), ("mercury", 3)],
    )
    set_costs(
        get_building(city, "Build_Tier_4"),
        2,
        [("gold", 3000), ("crystals", 6), ("dust", 40)],
    )
    set_costs(
        get_building(city, "Build_Tier_6"),
        1,
        [("gold", 4250), ("ore", 10), ("crystals", 10)],
    )
    set_costs(
        get_building(city, "Build_Tier_6"),
        2,
        [("gold", 2500), ("ore", 10), ("crystals", 15), ("dust", 75)],
    )
    set_costs(
        get_building(city, "Build_Tier_7"),
        1,
        [("gold", 15000), ("crystals", 15), ("mercury", 5)],
    )
    set_costs(
        get_building(city, "Build_Tier_7"),
        2,
        [("gold", 20000), ("crystals", 20), ("dust", 100)],
    )
    set_costs(
        get_building(city, "Build_Treasury"),
        1,
        [("gold", 5000), ("crystals", 10), ("mercury", 5)],
    )
    set_costs(
        get_building(city, "Build_Resource_Depot_level_2"),
        1,
        [("crystals", 6), ("mercury", 3)],
    )
    set_costs(
        get_building(city, "Build_Training_Range"),
        1,
        [("gold", 2500), ("ore", 5), ("wood", 5), ("crystals", 4), ("mercury", 2)],
    )


def patch_city_build_graph(city: dict) -> None:
    # Left side: palace, economy, unique buildings, fortifications.
    set_level(get_building(city, "Build_Main"), 1, x=1, y=0, prev=[])
    set_level(get_building(city, "Build_Main"), 2, x=1, y=1, prev=[{"sid": "Build_Main", "level": 1}])
    set_level(get_building(city, "Build_Main"), 3, x=1, y=2, prev=[{"sid": "Build_Main", "level": 2}])

    set_level(get_building(city, "Build_Tavern"), 1, x=0, y=1, prev=[])
    set_level(get_building(city, "Build_Market"), 1, x=0, y=2, prev=[{"sid": "Build_Tavern", "level": 1}])
    set_level(
        get_building(city, "Build_Artifact_Market"),
        1,
        x=0,
        y=3,
        prev=[{"sid": "Build_Market", "level": 1}, {"sid": "Build_Main", "level": 3}],
    )

    set_level(
        get_building(city, "Build_Bank"),
        1,
        x=2,
        y=2,
        prev=[{"sid": "Build_Main", "level": 2}],
    )
    set_level(get_building(city, "Build_Treasury"), 1, x=2, y=3, prev=[{"sid": "Build_Bank", "level": 1}])

    set_level(
        get_building(city, "Build_Resource_Depot"),
        1,
        x=1,
        y=3,
        prev=[{"sid": "Build_Market", "level": 1}, {"sid": "Build_Main", "level": 3}],
    )
    set_level(
        get_building(city, "Build_Resource_Depot_level_2"),
        1,
        x=1,
        y=4,
        prev=[{"sid": "Build_Resource_Depot", "level": 1}],
    )

    set_level(get_building(city, "Build_Wall"), 1, x=3, y=2, prev=[])
    set_level(get_building(city, "Build_Wall"), 2, x=3, y=3, prev=[{"sid": "Build_Wall", "level": 1}])
    set_level(get_building(city, "Build_Wall"), 3, x=3, y=4, prev=[{"sid": "Build_Wall", "level": 2}])

    # The screenshot uses the two existing utility placeholders as Grove-specific
    # specials: Mother Nature on the top row and Mycelium Roots on the lower row.
    set_level(get_building(city, "Build_Intelligence_Academy"), 1, x=2, y=0, prev=[])
    set_level(
        get_building(city, "Build_Training_Range"),
        1,
        x=2,
        y=4,
        prev=[{"sid": "Build_Treasury", "level": 1}, {"sid": "Build_Wall", "level": 2}],
    )

    if city.get("graals"):
        city["graals"][0]["parametersPerLevel"][0]["nodePos"] = {"xPos": 0, "yPos": 0}
        city["graals"][0]["parametersPerLevel"][0]["prevBuildings"] = []

    # Right side: dwellings and magic guild.
    set_level(get_building(city, "Build_Tier_1"), 1, x=5, y=0, prev=[])
    set_level(get_building(city, "Build_Tier_1"), 2, x=4, y=1, prev=[{"sid": "Build_Tier_1", "level": 1}])

    set_level(
        get_building(city, "Build_Tier_2"),
        1,
        x=5,
        y=1,
        prev=[{"sid": "Build_Tier_1", "level": 1}],
    )
    set_level(
        get_building(city, "Build_Tier_2"),
        2,
        x=4,
        y=2,
        prev=[{"sid": "Build_Tier_2", "level": 1}],
    )

    set_level(get_building(city, "Build_Tier_3"), 1, x=6, y=0, prev=[])
    set_level(get_building(city, "Build_Tier_3"), 2, x=6, y=1, prev=[{"sid": "Build_Tier_3", "level": 1}])

    set_level(
        get_building(city, "Build_Tier_4"),
        1,
        x=7,
        y=1,
        prev=[{"sid": "Build_Tier_3", "level": 1}],
    )
    set_level(
        get_building(city, "Build_Tier_4"),
        2,
        x=7,
        y=2,
        prev=[{"sid": "Build_Tier_4", "level": 1}],
    )

    set_level(
        get_building(city, "Build_Tier_5"),
        1,
        x=5,
        y=2,
        prev=[{"sid": "Build_Tier_1", "level": 1}, {"sid": "Build_Tier_2", "level": 1}],
    )
    set_level(get_building(city, "Build_Tier_5"), 2, x=5, y=3, prev=[{"sid": "Build_Tier_5", "level": 1}])

    set_level(
        get_building(city, "Build_Tier_6"),
        1,
        x=6,
        y=2,
        prev=[{"sid": "Build_Tier_3", "level": 1}, {"sid": "Build_Tier_4", "level": 1}],
    )
    set_level(get_building(city, "Build_Tier_6"), 2, x=6, y=3, prev=[{"sid": "Build_Tier_6", "level": 1}])

    set_level(
        get_building(city, "Build_Tier_7"),
        1,
        x=7,
        y=3,
        prev=[{"sid": "Build_Tier_6", "level": 1}],
    )
    set_level(get_building(city, "Build_Tier_7"), 2, x=7, y=4, prev=[{"sid": "Build_Tier_7", "level": 1}])

    ensure_nature_magic_guild_level_5(city)
    set_level(get_building(city, "Build_Magic_Guild"), 1, x=8, y=0, prev=[])
    set_level(get_building(city, "Build_Magic_Guild"), 2, x=8, y=1, prev=[{"sid": "Build_Magic_Guild", "level": 1}])
    set_level(get_building(city, "Build_Magic_Guild"), 3, x=8, y=2, prev=[{"sid": "Build_Magic_Guild", "level": 2}])
    set_level(get_building(city, "Build_Magic_Guild"), 4, x=8, y=3, prev=[{"sid": "Build_Magic_Guild", "level": 3}])
    set_level(get_building(city, "Build_Magic_Guild"), 5, x=8, y=4, prev=[{"sid": "Build_Magic_Guild", "level": 4}])

    # Keep build-order helpers in sync with the new Mage Guild V branch.
    for build_order in city.get("buildOrders", []):
        order = build_order.get("order", [])
        has_mg5 = any(step.get("sid") == "Build_Magic_Guild" and step.get("level") == 5 for step in order)
        if has_mg5:
            continue
        insert_at = None
        for i, step in enumerate(order):
            if step.get("sid") == "Build_Magic_Guild" and step.get("level") == 4:
                insert_at = i + 1
        if insert_at is None:
            order.append({"sid": "Build_Magic_Guild", "level": 5})
        else:
            order.insert(insert_at, {"sid": "Build_Magic_Guild", "level": 5})


def load_demo_nature_text() -> dict[str, str]:
    if not DEMO_ENGLISH_FACTION_LAWS_PATH.exists():
        raise SystemExit(f"Missing demo English law text: {DEMO_ENGLISH_FACTION_LAWS_PATH}")
    payload = load_json(DEMO_ENGLISH_FACTION_LAWS_PATH)
    out: dict[str, str] = {}
    for token in payload.get("tokens", []):
        sid = token.get("sid", "")
        if sid.startswith("fraction_law_nature_"):
            out[sid] = token.get("text", "")
    return out


def upsert_text_tokens(path: Path, updates: dict[str, str]) -> None:
    payload = load_json(path)
    tokens = payload.get("tokens", [])
    by_sid = {token["sid"]: token for token in tokens}
    for sid, text in updates.items():
        if sid in by_sid:
            by_sid[sid]["text"] = text
        else:
            tokens.append({"sid": sid, "text": text})
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def upsert_args_tokens(path: Path, updates: dict[str, list[str]]) -> None:
    payload = load_json(path)
    tokens = payload.get("tokensArgs", [])
    by_sid = {token["sid"]: token for token in tokens}
    for sid, args in updates.items():
        if sid in by_sid:
            by_sid[sid]["args"] = args
        else:
            tokens.append({"sid": sid, "args": args})
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def patch_fraction_and_city(core_path: Path) -> tuple[dict, dict]:
    with zipfile.ZipFile(core_path, "r") as z:
        fraction = json.loads(z.read(NATURE_FRACTION_PATH).decode("utf-8-sig"))["array"][0]
        city = json.loads(z.read(NATURE_CITY_PATH).decode("utf-8-sig"))["array"][0]

    fraction = copy.deepcopy(fraction)
    city = copy.deepcopy(city)

    fraction["iconFractionLaws"] = "Scroll_Faction_Nature"
    fraction["biome"] = "Autumn"
    fraction["fractionLawsLines"] = copy.deepcopy(NATURE_FRACTION_LINES)

    # Keep the shipped city as the base, but rewrite its graph to the Grove
    # screenshot and remap the placeholder special-building slots to the Grove
    # names the playtest already ships.
    if city.get("graals"):
        graal = city["graals"][0]
        graal["graalType"] = "NatureGraal"
        graal["names"] = ["Nature_Build_Unic_Graal_name"]
        graal["descriptions"] = ["Nature_Build_Unic_Graal_description_alt"]
        graal["narrativeDescriptions"] = ["Nature_Build_Unic_Graal_narrativeDescription"]

    if city.get("trainingRanges"):
        city["trainingRanges"][0]["names"] = ["Nature_Build_Unic_1_name"]
        city["trainingRanges"][0]["descriptions"] = ["Nature_Build_Unic_1_description"]
        city["trainingRanges"][0]["narrativeDescriptions"] = ["Nature_Build_Training_Range_narrativeDescription"]

    if city.get("intelligences"):
        city["intelligences"][0]["names"] = ["Nature_Build_Unic_2_name"]
        city["intelligences"][0]["descriptions"] = ["Nature_Build_Unic_2_description"]
        city["intelligences"][0]["narrativeDescriptions"] = ["Nature_Build_Intelligence_Academy_narrativeDescription"]

    patch_city_build_graph(city)
    patch_city_costs(city)

    return fraction, city


def patch_localization_files() -> None:
    nature_text = load_demo_nature_text()
    nature_text.update(NATURE_LAW_TEXT_OVERRIDES)
    upsert_text_tokens(ENGLISH_FACTION_LAWS_PATH, nature_text)
    upsert_args_tokens(ARGS_FACTION_LAWS_PATH, NATURE_LAW_ARGS_OVERRIDES)


def main() -> None:
    if not CORE.exists():
        raise SystemExit(f"Missing Core.zip: {CORE}")

    backup = CORE.with_suffix(".zip.bak_before_nature_generator")
    if not backup.exists():
        backup.write_bytes(CORE.read_bytes())

    nature_fraction, nature_city = patch_fraction_and_city(CORE)

    with zipfile.ZipFile(CORE, "r") as zin:
        entries = {info.filename: info for info in zin.infolist()}
        all_data = {name: zin.read(name) for name in zin.namelist()}

    all_data[NATURE_FRACTION_PATH] = json.dumps({"array": [nature_fraction]}, ensure_ascii=False, indent="\t").encode("utf-8")
    all_data[NATURE_CITY_PATH] = json.dumps({"array": [nature_city]}, ensure_ascii=False, indent="\t").encode("utf-8")
    all_data[NATURE_LAWS_PATH] = json.dumps(NATURE_LAWS, ensure_ascii=False, indent="\t").encode("utf-8")

    with zipfile.ZipFile(CORE, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, blob in sorted(all_data.items()):
            zi = entries.get(name)
            if zi is not None:
                zout.writestr(zi, blob)
            else:
                zout.writestr(name, blob)

    patch_localization_files()

    print(
        "Wrote Grove law table, updated the Nature fraction config, rewired the Grove"
        f" city graph, and patched English/args law localization in {CORE}"
    )
    print(f"Backup: {backup}")


if __name__ == "__main__":
    main()
