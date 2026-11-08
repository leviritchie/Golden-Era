"""Native ObjectConfig property contracts used by procedural map emission."""

from __future__ import annotations

from typing import Any

HOMM3_CUSTOM_TOWN_BUILDINGS_CONSTRUCTION_SID = "homm3_custom_town_buildings_construction"


def construction_sid_for_faction(faction_sid: str, default_sid: str) -> str:
    """Select the native starting-building preset for a generated town."""
    if not isinstance(faction_sid, str) or not faction_sid.strip():
        raise ValueError("town faction SID must be a non-empty string")
    if not isinstance(default_sid, str) or not default_sid.strip():
        raise ValueError("town default construction SID must be a non-empty string")
    if faction_sid.startswith("homm3_"):
        return HOMM3_CUSTOM_TOWN_BUILDINGS_CONSTRUCTION_SID
    return default_sid


RESOURCE_SIDS = frozenset(
    {
        "resource_gold",
        "resource_wood",
        "resource_ore",
        "resource_crystals",
        "resource_dust",
        "resource_gemstones",
        "resource_mercury",
    }
)

REWARD_PARAMETER_SIDS = frozenset(
    {
        "altar_of_magic_1",
        "armory_automaton",
        "college_of_wonder",
        "crystal_trail",
        "dragon_utopia",
        "fort",
        "knowledge_garden",
        "learning_stone",
        "lost_library",
        "magic_wheel",
        "mana_well",
        "maze",
        "mereas_shrine",
        "mysterious_stone",
        "orb_observatory",
        "quixs_path",
        "research_laboratory",
        "shady_den",
        "stables",
        "stinging_sword",
        "storage_crystals",
        "storage_gemstones",
        "storage_ore",
        "trial_scales",
        "tree_of_knowledge",
        "twilight_bloom",
        "university",
        "unstable_ruins",
        "watchtower",
        "windmill",
        "wise_owl",
    }
)

VARIANT_SIDS = frozenset(
    {
        "camp_fire",
        "chest",
        "dragon_utopia",
        "enchanted_scroll_box",
        "lost_library",
        "mereas_shrine",
        "mythic_scroll_box",
        "research_laboratory",
        "scroll_box",
        "shady_den",
        "storage_crystals",
        "storage_gemstones",
        "storage_ore",
        "tree_of_knowledge",
        "twilight_bloom",
        "unstable_ruins",
        "windmill",
        "wise_owl",
    }
)

AI_IGNORE_SIDS = frozenset({"resource_mercury"})
ACTIVATION_SIDS = frozenset(
    {"fx_map_light", "fx_quest_mark_gold_01", "fx_quest_mark_silver_01"}
)


def property_rows(content_sid: str, object_id: int) -> dict[str, dict[str, Any]]:
    """Return only property families proven for this native ObjectConfig SID."""
    rows: dict[str, dict[str, Any]] = {}
    if content_sid in RESOURCE_SIDS:
        # Native scenarios use zero to request ObjectConfig/logic amount rolling.
        rows["propResParams"] = {"type": 0, "id": object_id, "value": 0}
    if content_sid in REWARD_PARAMETER_SIDS:
        rows["propRewardParams"] = {
            "type": 0,
            "id": object_id,
            "parameters": [],
        }
    if content_sid in VARIANT_SIDS:
        rows["propVariants"] = {
            "type": 0,
            "id": object_id,
            "selectedVar": -1,
            "typeVariant": 0,
            "fraction": 0,
            "unitVersion": 0,
        }
    if content_sid in ACTIVATION_SIDS:
        rows["propActivations"] = {
            "type": 0,
            "id": object_id,
            "isActive": True,
        }
    if content_sid in AI_IGNORE_SIDS:        rows["propAiIntetactions"] = {
            "type": 0,
            "id": object_id,
            "aiIgnore": True,
        }
    return rows