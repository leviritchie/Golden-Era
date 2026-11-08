"""
Build DB/objects_logic/cities/demon_city.json from dungeon_city.json, add
DB/fractions/4_demon.json (FractionConfig id demon), create a dedicated Hive
law table, and patch English Hive law strings.

City interior uses the shipped Hive sceneName city_hive.

Run from anywhere:
  python generate_demon_city.py
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

DEMON_FRACTION_PATH = "DB/fractions/4_demon.json"
DEMON_LAWS_PATH = "DB/fractions_laws/fractions_laws_table_demon.json"

ENGLISH_FACTION_LAWS_PATH = (
    PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "factionLaws.json"
)
ENGLISH_UNITS_BUFF_PATH = (
    PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "unitsBuff.json"
)
ENGLISH_CITIES_PATH = (
    PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "english" / "texts" / "cities.json"
)

DEMON_HIRE_SIDS = [
    ["trick_demon", "trick_demon_upg", "trick_demon_upg_alt"],
    ["locust", "locust_upg", "locust_upg_alt"],
    ["wasp", "wasp_upg", "wasp_upg_alt"],
    ["jaw", "jaw_upg", "jaw_upg_alt"],
    ["godslayer", "godslayer_upg", "godslayer_upg_alt"],
    ["olgoi", "olgoi_upg", "olgoi_upg_alt"],
    ["hive_queen", "hive_queen_upg", "hive_queen_upg_alt"],
]

PARASITE_RECEIVERS = DEMON_HIRE_SIDS[0]
LOCUST_RECEIVERS = DEMON_HIRE_SIDS[1]
HORNET_RECEIVERS = DEMON_HIRE_SIDS[2]
SCORPION_RECEIVERS = DEMON_HIRE_SIDS[3]
REAVER_RECEIVERS = DEMON_HIRE_SIDS[4]
WORM_RECEIVERS = DEMON_HIRE_SIDS[5]
QUEEN_RECEIVERS = DEMON_HIRE_SIDS[6]
LARVA_RECEIVERS = ["lava_larva"]


def b(bonus_type: str, parameters: list[str] | None = None, **extra) -> dict:
    out = {"type": bonus_type}
    if parameters is not None:
        out["parameters"] = parameters
    out.update(extra)
    return out


def side_one_time_add_res(name: str, cost: int) -> dict:
    return b("sideOneTimeAddRes", [name, str(cost)])


def side_res(name: str, amount: int) -> dict:
    return b("sideRes", [name, str(amount)])


def city_units_increment(unit_id: str, amount: int) -> dict:
    return b("cityUnitsIncrement", [unit_id, str(amount)])


def hero_stat(name: str, value: str, **extra) -> dict:
    return b("heroStat", [name, value], **extra)


def hero_bool(name: str, value: bool = True, **extra) -> dict:
    return b("heroStat", [name, str(value).lower()], **extra)


def unit_stat(receivers: list[str] | None, parameters: list[str], **extra) -> dict:
    bonus = b("unitStat", parameters, **extra)
    if receivers is not None:
        bonus["receivers"] = receivers
    return bonus


def law(law_id: str, icon: str, levels: list[tuple[int, list[dict]]]) -> dict:
    return {
        "id": law_id,
        "icon": icon,
        "name": f"{law_id}_name",
        "desc": f"{law_id}_desc",
        "parametersPerLevel": [{"cost": cost, "bonuses": bonuses} for cost, bonuses in levels],
    }


DEMON_LAW_TEXT = {
    "fraction_law_demon_1_name": "Resource Riches I",
    "fraction_law_demon_1_desc": (
        "Provides a one-time bonus of 2500 Gold, 5 Wood, and 5 Ore when enacted."
    ),
    "fraction_law_demon_2_name": "Laws of the Hive",
    "fraction_law_demon_2_desc": (
        "Each level reduces the Law Point cost to unlock the next law tier by 2."
    ),
    "fraction_law_demon_3_name": "Mana Devour",
    "fraction_law_demon_3_desc": (
        "Each level reduces the mana cost of your Hive heroes' spells by 1."
    ),
    "fraction_law_demon_4_name": "Prey Appraisal",
    "fraction_law_demon_4_desc": "Your Hive heroes see exact information about neutral squads.",
    "fraction_law_demon_5_name": "Tax Collectors",
    "fraction_law_demon_5_desc": "Produces Gold each day.",
    "fraction_law_demon_6_name": "Mining: Crystals",
    "fraction_law_demon_6_desc": "Produces Crystals each day.",
    "fraction_law_demon_7_name": "Focus Reserves",
    "fraction_law_demon_7_desc": "Your Hive heroes start battles with 1 additional Focus Charge.",
    "fraction_law_demon_8_name": "Ancient Power",
    "fraction_law_demon_8_desc": "Primal spells of your heroes gain 1 level.",
    "fraction_law_demon_9_name": "Adapt and Overcome",
    "fraction_law_demon_9_desc": (
        "Hive buildings cost 10% less Gold to construct, and Hive creatures cost 10% less Gold to recruit."
    ),
    "fraction_law_demon_10_name": "Natural Selection",
    "fraction_law_demon_10_desc": (
        "External dwellings under your control offer upgraded creatures."
    ),
    "fraction_law_demon_11_name": "Beelzebub's Gaze",
    "fraction_law_demon_11_desc": (
        "Your Hive heroes see exact information about enemy heroes and cities from farther away."
    ),
    "fraction_law_demon_12_name": "Resource Riches II",
    "fraction_law_demon_12_desc": (
        "Provides a one-time bonus of 5000 Gold, 10 Wood, and 10 Ore when enacted."
    ),
    "fraction_law_demon_13_name": "Prosper and Flourish",
    "fraction_law_demon_13_desc": (
        "Each level increases the city growth contributed by external dwellings."
    ),
    "fraction_law_demon_14_name": "Hive Magic",
    "fraction_law_demon_14_desc": (
        "Each level increases the power of your heroes' Primal spells."
    ),
    "fraction_law_demon_15_name": "Resource Riches III",
    "fraction_law_demon_15_desc": (
        "Provides a one-time bonus of 7500 Gold, 15 Wood, and 15 Ore when enacted."
    ),
    "fraction_law_demon_16_name": "Predatory Instincts",
    "fraction_law_demon_16_desc": "Each level increases friendly creatures' Attack by 1.",
    "fraction_law_demon_17_name": "Hardened Carapaces",
    "fraction_law_demon_17_desc": "Each level increases friendly creatures' Defense by 1.",
    "fraction_law_demon_18_name": "Great Conquest",
    "fraction_law_demon_18_desc": (
        "Each level increases the Attack and Defense of friendly creatures by 1."
    ),
    "fraction_law_demon_19_name": "Volatile Larvae",
    "fraction_law_demon_19_desc": (
        "Summoned lava larvae deal 100% more damage when they explode on death."
    ),
    "fraction_law_demon_20_name": "Elite Parasites",
    "fraction_law_demon_20_desc": "Parasite growth in your cities increases by 4. They gain +1 HP.",
    "fraction_law_demon_21_name": "Elite Locusts",
    "fraction_law_demon_21_desc": "Locust growth in your cities increases by 4. They gain +1 Speed.",
    "fraction_law_demon_22_name": "Elite Hornets",
    "fraction_law_demon_22_desc": "Hornet growth in your cities increases by 2. They gain +2 Initiative.",
    "fraction_law_demon_23_name": "Elite Scorpions",
    "fraction_law_demon_23_desc": "Scorpion growth in your cities increases by 2. They gain +1 Morale and +1 Luck.",
    "fraction_law_demon_24_name": "Elite Reavers",
    "fraction_law_demon_24_desc": "Reaver growth in your cities increases by 1. They gain +1 Morale and +1 Luck.",
    "fraction_law_demon_25_name": "Elite Worms",
    "fraction_law_demon_25_desc": "Worm growth in your cities increases by 1. They gain +1 Morale and +1 Luck.",
    "fraction_law_demon_26_name": "Brood Assault",
    "fraction_law_demon_26_desc": "Summoned lava larvae can act one additional time each round.",
    "fraction_law_demon_27_name": "Elite Hive Queens",
    "fraction_law_demon_27_desc": "Hive Queen growth in your cities increases by 1. They gain +10 HP and +2 Damage.",
    "fraction_law_demon_28_name": "Infernal Rage",
    "fraction_law_demon_28_desc": "Each level increases the Damage of friendly creatures.",
    "fraction_law_demon_29_name": "No Compassion",
    "fraction_law_demon_29_desc": (
        "Each level increases the trigger chance of Morale and Luck by 1% per point for friendly creatures."
    ),
    "fraction_law_demon_30_name": "Brood Provocation",
    "fraction_law_demon_30_desc": (
        "Summoned lava larvae provoke adjacent enemies, forcing them to target the larvae."
    ),
}

DEMON_UNIT_BUFF_TEXT = {
    "fraction_law_demon_19_unit_bonus_description": "Upon death, deals 100% more Damage.",
    "fraction_law_demon_26_unit_bonus_description": "Can act one additional time each round.",
    "fraction_law_demon_30_unit_bonus_description": "Adjacent enemy creatures can target only this creature.",
}

DEMON_CITY_TEXT = {
    "Demon_Build_Wall_name_level_1": "Fortifications",
    "Demon_Build_Wall_name_level_2": "Fortifications II",
    "Demon_Build_Wall_name_level_3": "Fortifications III",
    "Demon_Build_Tier_1_name_level_1": "Neglected Housing",
    "Demon_Build_Tier_1_description_level_1": "Allows to recruit Parasites.",
    "Demon_Build_Tier_1_name_level_2": "Neglected Housing II",
    "Demon_Build_Tier_1_description_level_2": "Allows to recruit Warden Parasites and Ravager Parasites.",
    "Demon_Build_Tier_2_name_level_1": "Carrion Lair",
    "Demon_Build_Tier_2_description_level_1": "Allows to recruit Locusts.",
    "Demon_Build_Tier_2_name_level_2": "Carrion Lair II",
    "Demon_Build_Tier_2_description_level_2": "Allows to recruit Overgrown Locusts and Harvester Locusts.",
    "Demon_Build_Tier_3_name_level_1": "Paper Nest",
    "Demon_Build_Tier_3_description_level_1": "Allows to recruit Hornets.",
    "Demon_Build_Tier_3_name_level_2": "Paper Nest II",
    "Demon_Build_Tier_3_description_level_2": "Allows to recruit Chanters and Stingers.",
    "Demon_Build_Tier_4_name_level_1": "Chitinous Ziggurat",
    "Demon_Build_Tier_4_description_level_1": "Allows to recruit Scorpions.",
    "Demon_Build_Tier_4_name_level_2": "Chitinous Ziggurat II",
    "Demon_Build_Tier_4_description_level_2": "Allows to recruit Volcanic Scorpions and Spelaean Scorpions.",
    "Demon_Build_Tier_5_name_level_1": "Apex",
    "Demon_Build_Tier_5_description_level_1": "Allows to recruit Reavers.",
    "Demon_Build_Tier_5_name_level_2": "Apex II",
    "Demon_Build_Tier_5_description_level_2": "Allows to recruit Menacing Reavers and Maniacal Reavers.",
    "Demon_Build_Tier_6_name_level_1": "Burning Soul Burrows",
    "Demon_Build_Tier_6_description_level_1": "Allows to recruit Waurms.",
    "Demon_Build_Tier_6_name_level_2": "Burning Soul Burrows II",
    "Demon_Build_Tier_6_description_level_2": "Allows to recruit Devourers and Pyroboroses.",
    "Demon_Build_Tier_7_name_level_1": "Tower of Love",
    "Demon_Build_Tier_7_description_level_1": "Allows to recruit Hive Queens.",
    "Demon_Build_Tier_7_name_level_2": "Tower of Love II",
    "Demon_Build_Tier_7_description_level_2": "Allows to recruit Hive Mothers and Hive Huntresses.",
}

DEMON_FRACTION = {
    "array": [
        {
            "id": "demon",
            "name": "demon_name",
            "desc": "demon_desc",
            "narrativeDesc": "demon_desc",
            "icon": "fraction_dungeon",
            "iconFractionLaws": "Scroll_Faction_Dungeon",
            "biome": "Lava",
            "resourceName": "gemstones",
            "fractionLawsLines": [
                {
                    "groups": [
                        {
                            "laws": [
                                "fraction_law_demon_1",
                                "fraction_law_demon_2",
                                "fraction_law_demon_3",
                                "fraction_law_demon_4",
                            ]
                        },
                        {
                            "laws": [
                                "fraction_law_demon_16",
                                "fraction_law_demon_17",
                                "fraction_law_demon_19",
                            ]
                        },
                    ],
                    "countToUnlock": 0,
                },
                {
                    "groups": [
                        {
                            "laws": [
                                "fraction_law_demon_5",
                                "fraction_law_demon_6",
                                "fraction_law_demon_7",
                            ]
                        },
                        {
                            "laws": [
                                "fraction_law_demon_21",
                                "fraction_law_demon_22",
                                "fraction_law_demon_20",
                            ]
                        },
                    ],
                    "countToUnlock": 5,
                },
                {
                    "groups": [
                        {"laws": ["fraction_law_demon_12", "fraction_law_demon_8"]},
                        {
                            "laws": [
                                "fraction_law_demon_23",
                                "fraction_law_demon_24",
                                "fraction_law_demon_25",
                                "fraction_law_demon_26",
                            ]
                        },
                    ],
                    "countToUnlock": 15,
                },
                {
                    "groups": [
                        {
                            "laws": [
                                "fraction_law_demon_10",
                                "fraction_law_demon_13",
                                "fraction_law_demon_11",
                            ]
                        },
                        {"laws": ["fraction_law_demon_27", "fraction_law_demon_18"]},
                    ],
                    "countToUnlock": 30,
                },
                {
                    "groups": [
                        {
                            "laws": [
                                "fraction_law_demon_15",
                                "fraction_law_demon_14",
                                "fraction_law_demon_9",
                            ]
                        },
                        {
                            "laws": [
                                "fraction_law_demon_28",
                                "fraction_law_demon_29",
                                "fraction_law_demon_30",
                            ]
                        },
                    ],
                    "countToUnlock": 50,
                },
            ],
            "cityNames": [f"demon_city_name_{i}" for i in range(1, 21)],
        }
    ]
}

DEMON_LAWS = {
    "array": [
        law(
            "fraction_law_demon_1",
            "fraction_law_dungeon_3_icon",
            [(1, [side_one_time_add_res("gold", 2500), side_one_time_add_res("wood", 5), side_one_time_add_res("ore", 5)])],
        ),
        law(
            "fraction_law_demon_2",
            "fraction_law_undead_8_icon",
            [
                (1, [b("sideStat", ["decreaseLawPointsOpenLine", "2"])]),
                (1, [b("sideStat", ["decreaseLawPointsOpenLine", "4"])]),
            ],
        ),
        law(
            "fraction_law_demon_3",
            "fraction_law_dungeon_28_icon",
            [
                (2, [hero_stat("manaCostBonus", "-1")]),
                (2, [hero_stat("manaCostBonus", "-2")]),
                (2, [hero_stat("manaCostBonus", "-3")]),
            ],
        ),
        law(
            "fraction_law_demon_4",
            "fraction_law_dungeon_15_icon",
            [(3, [hero_bool("enableSquadCounts")])],
        ),
        law(
            "fraction_law_demon_5",
            "fraction_law_dungeon_1_icon",
            [(2, [side_res("gold", 250)]), (2, [side_res("gold", 500)])],
        ),
        law(
            "fraction_law_demon_6",
            "fraction_law_dungeon_14_icon",
            [(2, [side_res("crystals", 1)]), (2, [side_res("crystals", 2)])],
        ),
        law(
            "fraction_law_demon_7",
            "fraction_law_dungeon_29_icon",
            [(4, [hero_stat("startEnergyLevelsBonus", "1")])],
        ),
        law(
            "fraction_law_demon_8",
            "fraction_law_unfrozen_15_icon",
            [(3, [b("heroStat", ["magicSchoolSet", "primal", "0", "1"])])],
        ),
        law(
            "fraction_law_demon_9",
            "fraction_law_dungeon_7_icon",
            [
                (
                    3,
                    [
                        b("constructionDiscount", ["gold", "-0.10"]),
                        b("unitHiringDiscount", ["-0.10"], fraction="demon"),
                    ],
                )
            ],
        ),
        law(
            "fraction_law_demon_10",
            "fraction_law_unfrozen_16_icon",
            [(5, [b("barrackUpgradeUnitsHiring")])],
        ),
        law(
            "fraction_law_demon_11",
            "fraction_law_dungeon_16_icon",
            [
                (
                    3,
                    [
                        hero_bool("enableEnemyHeroInfo"),
                        hero_bool("enableEnemyCityInfo"),
                        hero_stat("viewRadius", "3"),
                    ],
                )
            ],
        ),
        law(
            "fraction_law_demon_12",
            "fraction_law_dungeon_17_icon",
            [(2, [side_one_time_add_res("gold", 5000), side_one_time_add_res("wood", 10), side_one_time_add_res("ore", 10)])],
        ),
        law(
            "fraction_law_demon_13",
            "fraction_law_human_21_icon",
            [
                (4, [b("sideStat", ["unitsFromBarracksIncrementPerBonus", "0.50"])]),
                (4, [b("sideStat", ["unitsFromBarracksIncrementPerBonus", "1.00"])]),
            ],
        ),
        law(
            "fraction_law_demon_14",
            "fraction_law_human_15_icon",
            [
                (3, [b("heroStat", ["spellPowerSchoolSet", "primal", "1"])]),
                (3, [b("heroStat", ["spellPowerSchoolSet", "primal", "2"])]),
                (3, [b("heroStat", ["spellPowerSchoolSet", "primal", "3"])]),
            ],
        ),
        law(
            "fraction_law_demon_15",
            "fraction_law_dungeon_30_icon",
            [(3, [side_one_time_add_res("gold", 7500), side_one_time_add_res("wood", 15), side_one_time_add_res("ore", 15)])],
        ),
        law(
            "fraction_law_demon_16",
            "fraction_law_human_6_icon",
            [
                (2, [unit_stat(None, ["offence", "1"])]),
                (2, [unit_stat(None, ["offence", "2"])]),
                (2, [unit_stat(None, ["offence", "3"])]),
            ],
        ),
        law(
            "fraction_law_demon_17",
            "fraction_law_human_7_icon",
            [
                (2, [unit_stat(None, ["defence", "1"])]),
                (2, [unit_stat(None, ["defence", "2"])]),
                (2, [unit_stat(None, ["defence", "3"])]),
            ],
        ),
        law(
            "fraction_law_demon_18",
            "fraction_law_human_26_icon",
            [
                (2, [unit_stat(None, ["offence", "1"]), unit_stat(None, ["defence", "1"])]),
                (2, [unit_stat(None, ["offence", "2"]), unit_stat(None, ["defence", "2"])]),
                (2, [unit_stat(None, ["offence", "3"]), unit_stat(None, ["defence", "3"])]),
            ],
        ),
        law(
            "fraction_law_demon_19",
            "fraction_law_undead_26_icon",
            [
                (
                    3,
                    [
                        unit_stat(
                            LARVA_RECEIVERS,
                            ["outDmgMultipliersSet", "lava_larva_damage", "true", "1.0"],
                        )
                    ],
                )
            ],
        ),
        law(
            "fraction_law_demon_20",
            "fraction_law_undead_23_icon",
            [(3, [city_units_increment("trick_demon", 4), unit_stat(PARASITE_RECEIVERS, ["hp", "1"])])],
        ),
        law(
            "fraction_law_demon_21",
            "fraction_law_dungeon_25_icon",
            [(3, [city_units_increment("locust", 4), unit_stat(LOCUST_RECEIVERS, ["speed", "1"])])],
        ),
        law(
            "fraction_law_demon_22",
            "fraction_law_undead_10_icon",
            [(3, [city_units_increment("wasp", 2), unit_stat(HORNET_RECEIVERS, ["initiative", "2"])])],
        ),
        law(
            "fraction_law_demon_23",
            "fraction_law_undead_12_icon",
            [
                (
                    3,
                    [
                        city_units_increment("jaw", 2),
                        unit_stat(SCORPION_RECEIVERS, ["moral", "1"]),
                        unit_stat(SCORPION_RECEIVERS, ["luck", "1"]),
                    ],
                )
            ],
        ),
        law(
            "fraction_law_demon_24",
            "fraction_law_undead_12_icon",
            [
                (
                    3,
                    [
                        city_units_increment("godslayer", 1),
                        unit_stat(REAVER_RECEIVERS, ["moral", "1"]),
                        unit_stat(REAVER_RECEIVERS, ["luck", "1"]),
                    ],
                )
            ],
        ),
        law(
            "fraction_law_demon_25",
            "fraction_law_undead_12_icon",
            [
                (
                    3,
                    [
                        city_units_increment("olgoi", 1),
                        unit_stat(WORM_RECEIVERS, ["moral", "1"]),
                        unit_stat(WORM_RECEIVERS, ["luck", "1"]),
                    ],
                )
            ],
        ),
        law(
            "fraction_law_demon_26",
            "fraction_law_undead_30_icon",
            [(4, [unit_stat(LARVA_RECEIVERS, ["actionPoints", "1"])])],
        ),
        law(
            "fraction_law_demon_27",
            "fraction_law_dungeon_31_icon",
            [
                (
                    3,
                    [
                        city_units_increment("hive_queen", 1),
                        unit_stat(QUEEN_RECEIVERS, ["hp", "10"]),
                        unit_stat(QUEEN_RECEIVERS, ["damageMin", "2"]),
                        unit_stat(QUEEN_RECEIVERS, ["damageMax", "2"]),
                    ],
                )
            ],
        ),
        law(
            "fraction_law_demon_28",
            "fraction_law_human_13_icon",
            [
                (4, [unit_stat(None, ["outAllDmgMod", "0.05"])]),
                (4, [unit_stat(None, ["outAllDmgMod", "0.10"])]),
            ],
        ),
        law(
            "fraction_law_demon_29",
            "fraction_law_human_25_icon",
            [
                (
                    3,
                    [
                        unit_stat(None, ["additionalActionChanceModifier", "0.01"]),
                        unit_stat(None, ["critChanceModifier", "0.01"]),
                    ],
                ),
                (
                    3,
                    [
                        unit_stat(None, ["additionalActionChanceModifier", "0.02"]),
                        unit_stat(None, ["critChanceModifier", "0.02"]),
                    ],
                ),
                (
                    3,
                    [
                        unit_stat(None, ["additionalActionChanceModifier", "0.03"]),
                        unit_stat(None, ["critChanceModifier", "0.03"]),
                    ],
                ),
            ],
        ),
        law(
            "fraction_law_demon_30",
            "fraction_law_dungeon_20_icon",
            [(5, [unit_stat(LARVA_RECEIVERS, ["tauntRadius", "1"])])],
        ),
    ]
}


def deep_replace_sid(obj, old_sid: str, new_sid: str):
    """Replace JSON string tokens that exactly match building sid references."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "sid" and v == old_sid:
                obj[k] = new_sid
            else:
                deep_replace_sid(v, old_sid, new_sid)
    elif isinstance(obj, list):
        for item in obj:
            deep_replace_sid(item, old_sid, new_sid)


def patch_hires(hires: list) -> None:
    for i, h in enumerate(hires):
        if i >= len(DEMON_HIRE_SIDS):
            break
        uh = h.get("unitsHire") or {}
        units = uh.get("units") or []
        if not units:
            continue
        u0 = units[0]
        u0["sids"] = DEMON_HIRE_SIDS[i]
        uh["units"] = units
        h["unitsHire"] = uh


def morph_artifact_changer_to_rebirth(city: dict) -> None:
    ac = city.get("artifactChangers") or []
    if not ac:
        city["rebirthShrines"] = []
        return
    cfg = copy.deepcopy(ac[0])
    cfg.pop("artifacts", None)
    cfg["sid"] = "Build_Rebirth_Of_Shrine"
    cfg["sceneSlot"] = "Build_Lyceum"
    cfg["icons"] = ["Demon_Build_Rebirth_Of_Shrine_icon"]
    cfg["names"] = ["Demon_Build_Rebirth_Of_Shrine_name"]
    cfg["descriptions"] = ["Demon_Build_Rebirth_Of_Shrine_description"]
    cfg["narrativeDescriptions"] = ["Demon_Build_Rebirth_Of_Shrine_description"]
    lyceum_cost = 2500
    for pl in cfg.get("parametersPerLevel") or []:
        for c in pl.get("costs") or []:
            if c.get("name") == "gold":
                lyceum_cost = c.get("cost", lyceum_cost)
    cfg["resArr"] = [{"name": "gold", "cost": lyceum_cost}]
    cfg["levelStep"] = 1
    city["artifactChangers"] = []
    city["rebirthShrines"] = [cfg]
    deep_replace_sid(city, "Build_Lyceum", "Build_Rebirth_Of_Shrine")


def morph_hero_bonus_bank(city: dict) -> None:
    hbb = city.get("heroBonusBanks") or []
    if not hbb:
        return
    bnk = hbb[0]
    bnk["sid"] = "Build_Beelzebubs_Hand"
    bnk["sceneSlot"] = "Gymnasium"
    bnk["icons"] = ["Demon_Build_Beelzebubs_Hand_icon"]
    bnk["names"] = ["Demon_Build_Beelzebubs_Hand_name"]
    bnk["descriptions"] = ["Demon_Build_Beelzebubs_Hand_description"]
    bnk["narrativeDescriptions"] = ["Demon_Build_Beelzebubs_Hand_description"]
    bnk["bonuses"] = [{"type": "heroStat", "parameters": ["offence", "2"]}]
    deep_replace_sid(city, "Build_Gymnasium", "Build_Beelzebubs_Hand")


def morph_graal(city: dict) -> None:
    graals = city.get("graals") or []
    if not graals:
        return
    g = graals[0]
    g["sid"] = "Build_Unic_Graal"
    g["sceneSlot"] = "Build_Unic_Graal"
    g["icons"] = ["D_build_Graal"]
    g["names"] = ["Demon_Build_Unic_Graal_name"]
    g["descriptions"] = ["Demon_Build_Unic_Graal_description_alt"]
    g["narrativeDescriptions"] = ["Demon_Build_Unic_Graal_narrativeDescription"]
    g["graalType"] = "DemonGraal"
    deep_replace_sid(city, "Build_Spy_Network", "Build_Unic_Graal")


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


def patch_city_build_graph(city: dict) -> None:
    city["artifactMarkets"] = []
    for build_order in city.get("buildOrders", []):
        build_order["order"] = [
            step for step in build_order.get("order", []) if step.get("sid") != "Build_Artifact_Market"
        ]

    set_level(get_building(city, "Build_Tier_1"), 1, x=6, y=0, prev=[])
    set_level(
        get_building(city, "Build_Tier_1"),
        2,
        x=6,
        y=1,
        prev=[{"sid": "Build_Tier_1", "level": 1}],
    )

    set_level(get_building(city, "Build_Tier_2"), 1, x=4, y=0, prev=[])
    set_level(
        get_building(city, "Build_Tier_2"),
        2,
        x=5,
        y=1,
        prev=[{"sid": "Build_Tier_2", "level": 1}],
    )

    set_level(
        get_building(city, "Build_Tier_3"),
        1,
        x=4,
        y=1,
        prev=[{"sid": "Build_Tier_2", "level": 1}],
    )
    set_level(
        get_building(city, "Build_Tier_3"),
        2,
        x=4,
        y=2,
        prev=[{"sid": "Build_Tier_3", "level": 1}],
    )

    set_level(
        get_building(city, "Build_Tier_4"),
        1,
        x=7,
        y=1,
        prev=[{"sid": "Build_Tier_1", "level": 1}],
    )
    set_level(
        get_building(city, "Build_Tier_4"),
        2,
        x=6,
        y=2,
        prev=[{"sid": "Build_Tier_4", "level": 1}],
    )

    set_level(
        get_building(city, "Build_Tier_5"),
        1,
        x=7,
        y=2,
        prev=[{"sid": "Build_Tier_4", "level": 1}],
    )
    set_level(
        get_building(city, "Build_Tier_5"),
        2,
        x=7,
        y=3,
        prev=[{"sid": "Build_Tier_5", "level": 1}],
    )

    set_level(
        get_building(city, "Build_Tier_6"),
        1,
        x=5,
        y=2,
        prev=[{"sid": "Build_Tier_3", "level": 1}],
    )
    set_level(
        get_building(city, "Build_Tier_6"),
        2,
        x=6,
        y=3,
        prev=[{"sid": "Build_Tier_6", "level": 1}],
    )

    set_level(
        get_building(city, "Build_Tier_7"),
        1,
        x=5,
        y=3,
        prev=[{"sid": "Build_Tier_6", "level": 1}],
    )
    set_level(
        get_building(city, "Build_Tier_7"),
        2,
        x=5,
        y=4,
        prev=[{"sid": "Build_Tier_7", "level": 1}],
    )

    set_level(
        get_building(city, "Build_Rebirth_Of_Shrine"),
        1,
        x=4,
        y=3,
        prev=[{"sid": "Build_Wall", "level": 1}],
    )

    # Hive should skew toward crystals rather than inheriting Dungeon's gemstone-heavy costs.
    # Keep globally standardized support buildings alone; only tune the Hive-specific economy.
    set_costs(
        get_building(city, "Build_Tier_1"),
        1,
        [("gold", 1000), ("ore", 5), ("crystals", 1)],
    )
    set_costs(
        get_building(city, "Build_Tier_1"),
        2,
        [("gold", 500), ("ore", 5), ("crystals", 1), ("dust", 10)],
    )
    set_costs(
        get_building(city, "Build_Tier_2"),
        1,
        [("gold", 1250), ("wood", 5), ("crystals", 2), ("mercury", 1)],
    )
    set_costs(
        get_building(city, "Build_Tier_2"),
        2,
        [("gold", 1000), ("wood", 5), ("crystals", 1), ("dust", 20)],
    )
    set_costs(
        get_building(city, "Build_Tier_3"),
        1,
        [("gold", 1000), ("ore", 5), ("crystals", 4), ("mercury", 2)],
    )
    set_costs(
        get_building(city, "Build_Tier_3"),
        2,
        [("gold", 1250), ("ore", 5), ("crystals", 2), ("dust", 30)],
    )
    set_costs(
        get_building(city, "Build_Tier_4"),
        1,
        [("gold", 4250), ("wood", 5), ("ore", 10), ("crystals", 5)],
    )
    set_costs(
        get_building(city, "Build_Tier_4"),
        2,
        [("gold", 3250), ("wood", 5), ("ore", 10), ("crystals", 5), ("dust", 40)],
    )
    set_costs(
        get_building(city, "Build_Tier_5"),
        1,
        [("gold", 2750), ("wood", 5), ("crystals", 6), ("mercury", 3)],
    )
    set_costs(
        get_building(city, "Build_Tier_5"),
        2,
        [("gold", 2250), ("wood", 5), ("crystals", 5), ("dust", 50)],
    )
    set_costs(
        get_building(city, "Build_Tier_6"),
        1,
        [("gold", 5500), ("wood", 10), ("ore", 5), ("crystals", 10)],
    )
    set_costs(
        get_building(city, "Build_Tier_6"),
        2,
        [("gold", 4000), ("wood", 15), ("ore", 10), ("crystals", 10), ("dust", 75)],
    )
    set_costs(
        get_building(city, "Build_Tier_7"),
        1,
        [("gold", 15000), ("wood", 5), ("ore", 5), ("crystals", 15)],
    )
    set_costs(
        get_building(city, "Build_Tier_7"),
        2,
        [("gold", 25000), ("crystals", 20), ("dust", 100)],
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


def bulk_text_pass(city: dict) -> dict:
    """Serialize and apply safe string replacements (order matters)."""
    s = json.dumps(city, ensure_ascii=False, indent="\t")
    reps = [
        ("Dungeon_Build_", "Demon_Build_"),
        ("dungeon_city", "demon_city"),
        ("DungeonGraal", "DemonGraal"),
        ("G_build_", "D_build_"),
        ("G_Build_Gymnasium", "Demon_Build_Beelzebubs_Hand_icon"),
        ("siege_walls_2_dungeon", "siege_walls_2_demon"),
        ("siege_walls_7_dungeon", "siege_walls_7_demon"),
        ("siege_walls_8_dungeon", "siege_walls_8_demon"),
        ("siege_walls_9_dungeon", "siege_walls_9_demon"),
        ("Demon_Build_Main_description_level_1_alt", "Demon_Build_Main_description_level_1"),
        ("Demon_Build_Main_description_level_2_alt", "Demon_Build_Main_description_level_2"),
        ("Demon_Build_Main_description_level_3_alt", "Demon_Build_Main_description_level_3"),
    ]
    for old, new in reps:
        s = s.replace(old, new)
    return json.loads(s)


def load_dungeon(zip_path: Path) -> dict:
    with zipfile.ZipFile(zip_path, "r") as z:
        raw = z.read("DB/objects_logic/cities/dungeon_city.json").decode("utf-8-sig")
        return json.loads(raw)


def upsert_text_tokens(path: Path, updates: dict[str, str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    tokens = payload.get("tokens", [])
    by_sid = {token["sid"]: token for token in tokens}
    for sid, text in updates.items():
        if sid in by_sid:
            by_sid[sid]["text"] = text
        else:
            tokens.append({"sid": sid, "text": text})
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def patch_localization_files() -> None:
    upsert_text_tokens(ENGLISH_FACTION_LAWS_PATH, DEMON_LAW_TEXT)
    upsert_text_tokens(ENGLISH_UNITS_BUFF_PATH, DEMON_UNIT_BUFF_TEXT)
    upsert_text_tokens(ENGLISH_CITIES_PATH, DEMON_CITY_TEXT)


def main() -> None:
    if not CORE.exists():
        raise SystemExit(f"Missing Core.zip: {CORE}")

    data = load_dungeon(CORE)
    city = copy.deepcopy(data["array"][0])

    city["id"] = "demon_city"
    city["sceneName"] = "city_hive"
    city["fraction"] = "demon"

    morph_artifact_changer_to_rebirth(city)
    morph_hero_bonus_bank(city)
    morph_graal(city)
    patch_hires(city["hires"])
    patch_city_build_graph(city)

    city = bulk_text_pass(city)

    out_inner = {"array": [city]}
    city_raw = json.dumps(out_inner, ensure_ascii=False, indent="\t")

    backup = CORE.with_suffix(".zip.bak_before_demon_city")
    if not backup.exists():
        backup.write_bytes(CORE.read_bytes())

    with zipfile.ZipFile(CORE, "r") as zin:
        entries = {i.filename: i for i in zin.infolist()}
        all_data = {name: zin.read(name) for name in zin.namelist()}

    all_data["DB/objects_logic/cities/demon_city.json"] = city_raw.encode("utf-8")
    all_data[DEMON_FRACTION_PATH] = json.dumps(DEMON_FRACTION, ensure_ascii=False, indent="\t").encode(
        "utf-8"
    )
    all_data[DEMON_LAWS_PATH] = json.dumps(DEMON_LAWS, ensure_ascii=False, indent="\t").encode(
        "utf-8"
    )

    data_json = json.loads(all_data["DB/data.json"].decode("utf-8-sig"))
    fr = data_json.setdefault("fractions", [])
    af = data_json.setdefault("availableFractions", [])
    if "demon" not in fr:
        fr.append("demon")
    if "demon" not in af:
        af.append("demon")
    all_data["DB/data.json"] = json.dumps(data_json, ensure_ascii=False, indent="\t").encode(
        "utf-8"
    )

    with zipfile.ZipFile(CORE, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, blob in sorted(all_data.items()):
            zi = entries.get(name)
            if zi is not None:
                zout.writestr(zi, blob)
            else:
                zout.writestr(name, blob)

    patch_localization_files()

    print(
        "Wrote demon city, dedicated Hive law table, fraction config, English law text,"
        f" and patched DB/data.json in {CORE}"
    )
    if backup.exists():
        print(f"Backup: {backup}")


if __name__ == "__main__":
    main()
