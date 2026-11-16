"""Core rows for the Factory Logistics Network faction skill (user design 2026-11-16).

Input: custom_factions/factory_logistics/logistics_config.json (the contract the plugin runtime reads; this module
reads the SIDs from it so both sides cannot drift).

Rows:

- the Logistics Network world spell: a clone of the native Necromancer Will row (change_use_necromancy) with
  parameters [mode], no mana cost and no usage limit (usageLimit -1). The plugin runtime intercepts the cast and
  opens the network viewer. Every rank of skill_faction_homm3_factory grants it (heroMagicAddition);
- the six Advanced/Expert subskills on the SIDs Split Assembly used (kept so saved heroes keep resolving them);
- the hidden, bonus-less side buff homm3_factory_logistics_store (clone of heros_crypt_debuff_none). The runtime
  keeps one per owning human side and stores the network records in its durations;
- six visible hero buffs homm3_factory_logistics_arcane_stats_1..6 (+N to all four primary stats), which the
  runtime applies for the Arcane enhancement.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = REPO_ROOT / "custom_factions" / "factory_logistics" / "logistics_config.json"
CONFIG_SCHEMA = "homm3_factory_logistics_config/1"

FACTION_SID = "homm3_factory"
SPELL_PATH = "DB/magics/world_neutral_magics.json"
SPELL_ICON = "neutral_1_magic_units_replace"
SPELL_MANA_COST = 0
SPELL_USAGE_LIMIT = -1  # native unlimited, like Elemental Fusion
NECROMANCY_MAGIC_SID = "change_use_necromancy"
SIDE_BUFFS_PATH = "DB/logic_side_buffs/logic_side_buffs.json"
CARRIER_SOURCE_SID = "heros_crypt_debuff_none"
HERO_BUFFS_PATH = "DB/heroes_buffs/heroes_buffs.json"
ARCANE_ICON = "sub_skill_faction_humans_3_icon"
SUBSKILLS_PATH = "DB/heroes_skills/sub_skills/sub_skills.json"
MAGIC_LANG_PATHS = ("Lang/english/texts/magic.json", "Lang/english/texts/magics.json")
MAGIC_LANG_ARGS_PATH = "Lang/args/magic.json"
# Hero/side buff names resolve from mapObjects.json (Captives, Gating); the buff tables are kept too.
BUFF_LANG_PATHS = ("Lang/english/texts/mapObjects.json", "Lang/english/texts/magic_buff.json")


def load_config() -> dict[str, Any]:
    doc = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(doc, dict) or doc.get("schema") != CONFIG_SCHEMA:
        raise RuntimeError(f"{CONFIG_PATH}: schema must be {CONFIG_SCHEMA}")
    for key in ("skillSid", "spellSid", "carrierBuffSid", "heroStatBuffPrefix", "heroStatBuffMaxLevel", "maxLevel"):
        if key not in doc:
            raise RuntimeError(f"{CONFIG_PATH}: missing {key}")
    return doc


_CONFIG = load_config()
SKILL_SID = str(_CONFIG["skillSid"])
SPELL_SID = str(_CONFIG["spellSid"])
SPELL_MODE = SPELL_SID
CARRIER_BUFF_SID = str(_CONFIG["carrierBuffSid"])
ARCANE_BUFF_PREFIX = str(_CONFIG["heroStatBuffPrefix"])
ARCANE_BUFF_MAX = int(_CONFIG["heroStatBuffMaxLevel"])

SKILL_NAME = "Logistics Network"
SKILL_DESC = (
    "Links your mines and dwellings into a Logistics Network. Visit an owned mine or dwelling with a hero who has "
    "this skill and build an enhancement there (gold, extra output, more units, or a network bonus). Enhanced "
    "buildings within range of each other link up; range is 1.0 day of travel, and Rail Stations add more. Then "
    "manage the whole network from the free Logistics Network spell: switch enhancements and build remotely."
)
# Every rank text states its maximum "enhancement level N" (validate_factory_logistics_contract.py checks it).
_UPGRADE_CENTER_TEXT = (
    "A visit also leaves an Upgrade Center at the hero's skill level: from the Logistics Network spell you can then "
    "build and upgrade that building's enhancements remotely up to that level, ready the next day."
)
RANK_DESCS = (
    "Grants the free Logistics Network adventure spell. Visit your mines and dwellings to build enhancements up to "
    "enhancement level 1; enhanced buildings within range (1.0 day of travel) link into one network. "
    + _UPGRADE_CENTER_TEXT,
    "Build enhancements up to enhancement level 2. A visit raises the building's Upgrade Center to 2, so it can be "
    "upgraded to level 2 remotely from the Logistics Network spell, ready the next day.",
    "Build enhancements up to enhancement level 3. A visit raises the building's Upgrade Center to 3, so it can be "
    "upgraded to level 3 remotely from the Logistics Network spell, ready the next day.",
)
IMPLEMENTED = (
    "Logistics Network: every rank grants the homm3_factory_logistics_network world spell (Necromancer Will clone, "
    "no mana cost, unlimited uses); skill rank caps the enhancement level a hero can build (1/2/3). The plugin "
    "runtime (Homm3FactoryLogisticsRuntime) intercepts the [mode] cast and opens the network viewer, hooks mine "
    "day start and dwelling week start for enhancement output, and stores the network in the hidden side buff "
    "homm3_factory_logistics_store (custom_factions/factory_logistics/logistics_config.json)."
)
SOURCE_DIFFERENCE = (
    "Replaces Split Assembly (battle-start Natural/Industrial line bonuses). Factory has no HotA faction secondary "
    "skill; the Logistics Network is an original economy mechanic. Subskill SIDs are kept for save compatibility."
)

# Advanced/Expert subskill SIDs are kept from Split Assembly so saved heroes keep resolving them.
SUBSKILL_IDS = {
    "roads": "sub_skill_faction_homm3_factory_sand_advantage",
    "haulers": "sub_skill_faction_homm3_factory_line_discipline",
    "survey": "sub_skill_faction_homm3_factory_field_calibration",
    "night_shift": "sub_skill_faction_homm3_factory_gantry_reserve",
    "depots": "sub_skill_faction_homm3_factory_industrial_tempo",
    "contracts": "sub_skill_faction_homm3_factory_couatl_relay",
}
SUBSKILLS_BY_LEVEL = {
    2: (SUBSKILL_IDS["roads"], SUBSKILL_IDS["haulers"], SUBSKILL_IDS["survey"]),
    3: (SUBSKILL_IDS["night_shift"], SUBSKILL_IDS["depots"], SUBSKILL_IDS["contracts"]),
}
SUBSKILL_TEXT = {
    "roads": (
        "Mobile Command Center",
        "Your mines and dwellings within this hero's range become Command Center N (N = this hero's Logistics "
        "Network level): their enhancements can be built and upgraded remotely from the Logistics Network spell up "
        "to level N, ready the next day, without a visit.",
    ),
    "haulers": ("Freight Haulers", "Landscape movement penalties are removed."),
    "survey": ("Survey Office", "Factory creatures on native terrain deal 10% more damage and take 10% less damage."),
    "night_shift": ("Night Shift", "This hero restores 20 additional mana each day."),
    "depots": ("Supply Caravan", "This hero counts as a level 3 Logistics Hub: network routes passing its tile regain all spent range."),
    "contracts": ("Trade Contracts", "This hero counts as 2 additional Marketplaces when calculating trading prices."),
}
# Subskills whose effect lives in the plugin (no native bonus row).
RUNTIME_SUBSKILLS = {
    "roads": "Homm3FactoryLogisticsFacade.RemoteLevel (Mobile Command Center)",
    "depots": "Homm3FactoryLogisticsEffects.Solve CaravanHubs (Supply Caravan)",
}
SUBSKILL_BONUSES = {
    # Mobile Command Center and Supply Caravan are runtime effects (Homm3FactoryLogisticsRuntime reads the subskill sid).
    "roads": ("sub_skill_logistic_2_icon", []),
    "haulers": ("sub_skill_logistic_1_icon", [{"type": "heroStat", "parameters": ["landscapePenaltyPerBonus", "-1.0"]}]),
    "survey": (
        "sub_skill_faction_humans_1_icon",
        [
            {"type": "unitStat", "biomeType": "native", "fraction": "homm3_factory", "parameters": ["outAllDmgMod", "0.1"]},
            {"type": "unitStat", "biomeType": "native", "fraction": "homm3_factory", "parameters": ["inAllDmgMod", "-0.1"]},
        ],
    ),
    "night_shift": ("sub_skill_logistic_3_icon", [{"type": "heroStat", "parameters": ["manaRestoreBonus", "20"]}]),
    "depots": ("sub_skill_faction_humans_5_icon", []),
    "contracts": ("sub_skill_economy_5_icon", [{"type": "heroStat", "parameters": ["enableMarketsCounting", "true"]}]),
}


# ---------------------------------------------------------------- skill, spell, subskills


def faction_skill_levels() -> list[list[dict[str, Any]]]:
    return [[{"type": "heroMagicAddition", "parameters": [SPELL_SID, "false"]}] for _ in range(3)]


def make_subskills() -> list[dict[str, Any]]:
    rows = []
    for key, sid in SUBSKILL_IDS.items():
        icon, bonuses = SUBSKILL_BONUSES[key]
        row = {"id": sid, "name": f"{sid}_name", "desc": f"{sid}_desc", "icon": icon, "bonuses": copy.deepcopy(bonuses)}
        if key in RUNTIME_SUBSKILLS:
            row["xHomm3RuntimeHook"] = RUNTIME_SUBSKILLS[key]
        rows.append(row)
    return rows


def subskill_lang_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for key, sid in SUBSKILL_IDS.items():
        name, desc = SUBSKILL_TEXT[key]
        rows.append({"sid": f"{sid}_name", "text": name})
        rows.append({"sid": f"{sid}_desc", "text": desc})
    return rows


def make_logistics_magic_row(source_rows: list[Any]) -> dict[str, Any]:
    """Clone of the native Necromancer Will world magic; the runtime intercepts its [mode] parameters."""
    base = next((r for r in source_rows if isinstance(r, dict) and r.get("id") == NECROMANCY_MAGIC_SID), None)
    if not isinstance(base, dict):
        raise RuntimeError(f"missing Logistics Network magic source {NECROMANCY_MAGIC_SID}")
    row = copy.deepcopy(base)
    row.update(
        {
            "id": SPELL_SID,
            "name": f"{SPELL_SID}_name",
            "icon": SPELL_ICON,
            "description": [f"{SPELL_SID}_description"] * 4,
            "bonusDescriptions": [],
            "upEffectDescription": "",
            "manaCost": [SPELL_MANA_COST] * 4,
            "upgradeCost": [0],
            "rank": 1,
            "school_": "neutral",
            "usedOnMap": True,
            "xHomm3RuntimeHook": (
                "Logistics Network reuses the native Necromancer Will world-magic handler; the plugin runtime intercepts "
                "the [mode] parameter row, suppresses the native toggle and opens the network viewer "
                "(custom_factions/factory_logistics/logistics_config.json)."
            ),
        }
    )
    world_magic = row.get("worldMagic")
    settings = world_magic.get("magicSettings") if isinstance(world_magic, dict) else None
    if not isinstance(settings, list) or not settings:
        raise RuntimeError(f"malformed Logistics Network magic source {NECROMANCY_MAGIC_SID}")
    world_magic["settingPerLevels"] = [0, 0, 0, 0]
    for setting in settings:
        if isinstance(setting, dict):
            setting["mechType"] = NECROMANCY_MAGIC_SID
            setting["parameters"] = [SPELL_MODE]
            setting["usageLimit"] = SPELL_USAGE_LIMIT
            setting["castInfoSid"] = f"{SPELL_SID}_cast"
    return row


def magic_lang_rows() -> list[dict[str, str]]:
    return [
        {"sid": f"{SPELL_SID}_name", "text": "Logistics Network"},
        {
            "sid": f"{SPELL_SID}_description",
            "text": (
                "Opens your Logistics Network: your mines, dwellings and towns, the routes that link them within "
                "range (shown in days of travel) and the enemy stacks that cut them. Switch a building's active "
                "enhancement (once a week, from the next day), build or upgrade remotely where an Upgrade Center or "
                "Command Center allows it (ready the next day), and hire creatures by rail. Logistics Network skill "
                "levels raise the highest enhancement level: Basic 1, Advanced 2, Expert 3."
            ),
        },
        {"sid": f"{SPELL_SID}_cast", "text": "The network ledger opens."},
    ]


def make_carrier_side_buff_row(source_rows: list[Any]) -> dict[str, Any]:
    base = next((r for r in source_rows if isinstance(r, dict) and r.get("id") == CARRIER_SOURCE_SID), None)
    if not isinstance(base, dict):
        raise RuntimeError(f"missing Logistics Network carrier source {CARRIER_SOURCE_SID}")
    row = copy.deepcopy(base)
    row.update(
        {
            "id": CARRIER_BUFF_SID,
            "name": f"{CARRIER_BUFF_SID}_name",
            "description": f"{CARRIER_BUFF_SID}_description",
            "hidden": True,
            "bonuses": [],
            "xHomm3RuntimeHook": (
                "Hidden, bonus-less carrier: Homm3FactoryLogisticsState stores the side's network records in this "
                "buff's durations. Without the plugin it does nothing."
            ),
        }
    )
    return row


def make_arcane_hero_buff_rows() -> list[dict[str, Any]]:
    rows = []
    for level in range(1, ARCANE_BUFF_MAX + 1):
        sid = f"{ARCANE_BUFF_PREFIX}{level}"
        rows.append(
            {
                "id": sid,
                "icon": ARCANE_ICON,
                "name": f"{ARCANE_BUFF_PREFIX}name",
                "description": f"{sid}_description",
                "additionType": "LeftNew",
                "isPositive": True,
                "hidden": False,
                "isDispellable": True,
                "bonuses": [
                    {"type": "heroStat", "parameters": [stat, str(level)]}
                    for stat in ("offence", "defence", "spellPower", "intelligence")  # intelligence = Knowledge
                ],
            }
        )
    return rows


def buff_lang_rows() -> list[dict[str, str]]:
    rows = [
        {"sid": f"{CARRIER_BUFF_SID}_name", "text": "Logistics Network"},
        {"sid": f"{CARRIER_BUFF_SID}_description", "text": "Logistics Network records."},
        {"sid": f"{ARCANE_BUFF_PREFIX}name", "text": "Arcane Supply"},
    ]
    for level in range(1, ARCANE_BUFF_MAX + 1):
        rows.append(
            {
                "sid": f"{ARCANE_BUFF_PREFIX}{level}_description",
                "text": f"Arcane enhancements in this hero's network: +{level} Attack, Defense, Spell Power and Knowledge.",
            }
        )
    return rows


def _upsert_rows(read_doc, write_json, upsert, dedupe, release_zip, output, notes, path, rows, label) -> None:
    doc = read_doc(release_zip, output, path)
    if not isinstance(doc, dict) or not isinstance(doc.get("array"), list):
        raise RuntimeError(f"malformed homm3_factory Logistics Network {label} target {path}")
    changed = False
    for row in rows(doc["array"]) if callable(rows) else rows:
        changed = upsert(doc, row) or changed
    changed = dedupe(doc) or changed
    if changed:
        output[path] = write_json(doc)
        notes.append(f"merge homm3_factory Logistics Network {label} into {path}")


def merge_logistics_skill_rows_into_overlay(release_zip, output, notes, helpers) -> None:
    """World spell, subskills, carrier side buff, arcane hero buffs and their lang rows. Fails closed.
    helpers: read_overlay_or_release_json, write_json, upsert_array_row, dedupe_array_rows_by_id,
    add_lang_overlay_rows, add_lang_args_overlay_rows."""
    read_doc = helpers["read_overlay_or_release_json"]
    write_json = helpers["write_json"]
    upsert = helpers["upsert_array_row"]
    dedupe = helpers["dedupe_array_rows_by_id"]
    common = (read_doc, write_json, upsert, dedupe, release_zip, output, notes)

    _upsert_rows(*common, SPELL_PATH, lambda rows: [make_logistics_magic_row(rows)], "world spell")
    _upsert_rows(*common, SUBSKILLS_PATH, make_subskills(), "subskills")
    _upsert_rows(*common, SIDE_BUFFS_PATH, lambda rows: [make_carrier_side_buff_row(rows)], "carrier side buff")
    _upsert_rows(*common, HERO_BUFFS_PATH, make_arcane_hero_buff_rows(), "arcane hero buffs")

    for path in MAGIC_LANG_PATHS:
        helpers["add_lang_overlay_rows"](release_zip, output, path, magic_lang_rows(), notes)
    helpers["add_lang_args_overlay_rows"](
        release_zip, output, MAGIC_LANG_ARGS_PATH, [{"sid": row["sid"], "args": []} for row in magic_lang_rows()], notes
    )
    for path in BUFF_LANG_PATHS:
        helpers["add_lang_overlay_rows"](release_zip, output, path, buff_lang_rows(), notes)
