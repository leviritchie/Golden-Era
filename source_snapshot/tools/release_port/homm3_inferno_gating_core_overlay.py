"""Inferno Gating (reserved-slot reinforcements) Core overlay rows.

Design (owner, 2026-11-13):
- A hero with Gating reserves army slots as gated reinforcements (1 slot; +1 Wider Gate, +1 Efficient Gate).
- Gating is always open (2026-11-14: the spellbook toggle was dropped; releasing every slot turns it off).
- Reserved stacks skip the opening deployment and enter in round 2: Basic on a random open hex, Advanced/Expert
  on a random open hex in the opponent's half; Expert delays the entry until the stack's own turn in round 2.
- Rapid Gate: entering stacks get 1 round of Haste (level 1). Shielded Arrival: barrier on entry.
- Open Gate (expert subskill): 2-Focus hero action that gates every pending stack immediately.

Every gameplay rule above is owned by the plugin runtime (Homm3InfernoGatingRuntime*.cs). These rows only provide
the native carriers: the toggle spell (a Necromancer Will clone, like Captives/Elite Strategem), hidden hero-buff
bits that persist the toggle and reserved-slot mask in the save, the subskill rows, the Open Gate hero ability and
the barrier battle buff. Proof: generated-artifact only until the owner tests in game.
"""

from __future__ import annotations

import copy
from typing import Any, Callable

SKILL_SID = "skill_faction_homm3_inferno"

# Adventure-map toggle spell (Necromancer Will clone; the runtime intercepts mode "homm3_inferno_gating_toggle").
GATING_MAGIC_PATH = "DB/magics/world_neutral_magics.json"
GATING_TOGGLE_MAGIC_SID = "homm3_inferno_gating_toggle"
GATING_TOGGLE_MODE = "homm3_inferno_gating_toggle"
GATING_TOGGLE_ICON = "sub_skill_summoner_6_icon"

# Hero buffs persisted with the hero (Data.Hero.buffs): one visible "open" state buff + one hidden bit per army slot.
GATING_HERO_BUFFS_PATH = "DB/heroes_buffs/heroes_buffs.json"
GATING_OPEN_BUFF_SID = "homm3_inferno_gating_open"
GATING_SLOT_BIT_PREFIX = "homm3_inferno_gating_slot_"
GATING_ARMY_SLOTS = 7
GATING_BUFF_ICON = "sub_skill_summoner_6_icon"

# Expert subskill hero action.
OPEN_GATE_ABILITY_SID = "skill_faction_homm3_inferno_ability_open_gate"
OPEN_GATE_FOCUS_COST = 2
OPEN_GATE_CAST_VFX = "magic/Prefabs_vfx/Heroes/hero_demon_hex"

# Shielded Arrival battle buff (applied by the runtime when a gated stack enters).
BARRIER_BUFFS_PATH = "DB/buffs/sub_skills_battle_hero_buffs.json"
BARRIER_BUFF_SID = "homm3_inferno_gating_barrier_bonus"
BARRIER_INFO_SID = "sub_skill_faction_homm3_inferno_gating_barrier_bonus"
BARRIER_INFOS_PATH = "DB/side_buffs/bonus_buff_infos/buff_infos.json"

# Subskill ids are kept from the previous summon design so saved heroes keep their picks; their meaning changed.
SUBSKILL_WIDER_GATE = "sub_skill_faction_homm3_inferno_gating_more_units"
SUBSKILL_RAPID_GATE = "sub_skill_faction_homm3_inferno_gating_fast_gate"
SUBSKILL_LAVA_ADVANTAGE = "sub_skill_faction_homm3_inferno_gating_native_terrain"
SUBSKILL_EFFICIENT_GATE = "sub_skill_faction_homm3_inferno_gating_focus_efficiency"
SUBSKILL_OPEN_GATE = "sub_skill_faction_homm3_inferno_gating_any_tile"
SUBSKILL_SHIELDED_ARRIVAL = "sub_skill_faction_homm3_inferno_gating_barrier"

SUBSKILLS_BY_LEVEL = {
    2: (SUBSKILL_WIDER_GATE, SUBSKILL_RAPID_GATE, SUBSKILL_LAVA_ADVANTAGE),
    3: (SUBSKILL_EFFICIENT_GATE, SUBSKILL_OPEN_GATE, SUBSKILL_SHIELDED_ARRIVAL),
}

# Rows of the retired summon design that must not survive in an overlaid Core.
RETIRED_ABILITY_SIDS = {
    "skill_faction_homm3_inferno_ability_gating",
    "skill_faction_homm3_inferno_ability_gating_gogs",
    "skill_faction_homm3_inferno_ability_gating_hell_hounds",
}
RETIRED_DELTA_ABILITY_SIDS = {
    f"{ability}_{key}_delta"
    for ability in RETIRED_ABILITY_SIDS
    for key in ("fast_gate", "any_tile", "focus_efficiency")
}
RETIRED_ABILITY_INFO_SIDS = {
    f"sub_skill_faction_homm3_inferno_gating_{key}_{ability}"
    for ability in RETIRED_ABILITY_SIDS
    for key in ("fast_gate", "any_tile", "focus_efficiency")
}
RETIRED_SUBSKILL_IDS = {"sub_skill_faction_homm3_inferno_gating_higher_tier"}
RETIRED_OBSTACLE_IDS = {
    "homm3_inferno_gating_gate_h3_imp",
    "homm3_inferno_gating_gate_h3_gog",
    "homm3_inferno_gating_gate_h3_hell_hound",
}

ABILITY_PATH = "DB/heroes_abilities/heroes_abilities_base/hero_abilities.json"
ABILITY_BONUSES_PATH = "DB/heroes_abilities/heroes_abilities_bonuses/hero_abilities_bonuses.json"
ABILITY_INFOS_PATH = "DB/heroes_abilities/heroes_abilities_infos/hero_abilities_infos.json"
OBSTACLES_PATH = "DB/field_objects/obstacles/obstacles_hero.json"
SUBSKILLS_PATH = "DB/heroes_skills/sub_skills/sub_skills.json"

SKILL_NAME = "Gating"
SKILL_DESC = (
    "Reserve army slots as gated reinforcements and toggle Gating in the spellbook. While Gating is open, "
    "reserved stacks skip the opening deployment and step through a hellgate in round 2."
)
RANK_DESCS = (
    "Reserve 1 army slot. Its stack enters in round 2 on a random open hex.",
    "Gated stacks enter in round 2 on a random open hex in the enemy's half of the battlefield.",
    "Gated stacks enter in the enemy's half of the battlefield when they would take their turn in round 2.",
)
GENERIC_TEXT = (
    SKILL_NAME,
    SKILL_DESC,
    [
        "Gain Gating: reserve 1 army slot as a gated reinforcement. Its stack skips deployment and enters in round 2 on a random open hex.",
        "Gated stacks enter in round 2 on a random open hex in the enemy's half of the battlefield.",
        "Gated stacks enter in the enemy's half when they would take their turn in round 2.",
    ],
)


def faction_skill_levels() -> list[list[dict[str, Any]]]:
    # Gating is always open (owner, 2026-11-14): no spellbook toggle is granted. The toggle magic row stays in
    # world_neutral_magics so saves whose heroes already learned it still load.
    return [[], [], []]


IMPLEMENTED = (
    "Gating: reserved army slots skip deployment (BattleLogic.Init TransferSide edit) and re-enter through the native "
    "FieldObject factory as return-to-army stacks in round 2 (random open hex; enemy half at Advanced+; on the stack's "
    "own turn at Expert); always open, slots reserved from the army strip; state in hidden hero-buff bits."
)
SOURCE_DIFFERENCE = (
    "Gating no longer summons temporary Imps/Gogs/Hell Hounds; it delays chosen permanent stacks of the hero's own army."
)


def make_toggle_magic_row(source_rows: list[Any]) -> dict[str, Any]:
    base_row = next((row for row in source_rows if isinstance(row, dict) and row.get("id") == "change_use_necromancy"), None)
    if not isinstance(base_row, dict):
        raise RuntimeError("missing Gating toggle magic source change_use_necromancy")
    row = copy.deepcopy(base_row)
    sid = GATING_TOGGLE_MAGIC_SID
    row["id"] = sid
    row["name"] = f"{sid}_name"
    row["icon"] = GATING_TOGGLE_ICON
    row["description"] = [f"{sid}_description"] * 4
    row["bonusDescriptions"] = []
    row["upEffectDescription"] = ""
    row["manaCost"] = [0, 0, 0, 0]
    row["upgradeCost"] = [0]
    row["rank"] = 1
    row["school_"] = "neutral"
    row["usedOnMap"] = True
    row["xHomm3RuntimeHook"] = (
        "Inferno Gating reuses the native Necromancer Will world-magic handler; Homm3InfernoGatingRuntime intercepts "
        "mode homm3_inferno_gating_toggle and flips the hero's Gating open buff."
    )
    world_magic = row.get("worldMagic")
    if not isinstance(world_magic, dict):
        raise RuntimeError("malformed Gating worldMagic source change_use_necromancy")
    magic_settings = world_magic.get("magicSettings")
    if not isinstance(magic_settings, list) or not magic_settings:
        raise RuntimeError("malformed Gating magicSettings source change_use_necromancy")
    world_magic["settingPerLevels"] = [0, 0, 0, 0]
    for setting in magic_settings:
        if isinstance(setting, dict):
            setting["mechType"] = "change_use_necromancy"
            setting["parameters"] = [GATING_TOGGLE_MODE, "1"]
            setting["castInfoSid"] = f"{sid}_cast"
    return row


def make_hero_buff_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {
            "id": GATING_OPEN_BUFF_SID,
            "icon": GATING_BUFF_ICON,
            "name": f"{GATING_OPEN_BUFF_SID}_name",
            "description": f"{GATING_OPEN_BUFF_SID}_description",
            "additionType": "LeftNew",
            "isPositive": True,
            "hidden": False,
            "isDispellable": True,
            "bonuses": [],
        }
    ]
    for slot in range(GATING_ARMY_SLOTS):
        rows.append(
            {
                "id": f"{GATING_SLOT_BIT_PREFIX}{slot}",
                "icon": GATING_BUFF_ICON,
                "name": f"{GATING_OPEN_BUFF_SID}_name",
                "description": "homm3_inferno_gating_slot_description",
                "additionType": "LeftNew",
                "isPositive": True,
                "hidden": True,
                "isDispellable": True,
                "bonuses": [],
            }
        )
    return rows


def make_open_gate_ability() -> dict[str, Any]:
    # Same targeting as the vanilla Inferno gate ability (skill_faction_demon_ability): any hex is a valid click.
    # Hero abilities have no untargeted mode; an ally/alive filter with no selection found no valid target at all.
    target = {"castTarget_": "all", "selection": "hex"}
    return {
        "id": OPEN_GATE_ABILITY_SID,
        "levels": [
            {
                "aiValue": 0,
                "name": f"{OPEN_GATE_ABILITY_SID}_name",
                "description": f"{OPEN_GATE_ABILITY_SID}_description",
                "icon": GATING_TOGGLE_ICON,
                "casterEffect": OPEN_GATE_CAST_VFX,
                "attackTimeBefore": 0.3,
                "attackTimeAfter": 0.6,
                "cd": 0,
                "charges": 1,
                "energyLevel": OPEN_GATE_FOCUS_COST,
                "useExpandTooltip": "false",
                "attackType_": "cast",
                "damageDealer": {
                    "tags": ["ability"],
                    "triggerCounter": False,
                    "attackPatternSid": "attack_single_x100",
                    "castTargetParams": dict(target),
                    "affectTargetParams": dict(target),
                    "damageTarget_": "none",
                    "damageType_": "none",
                    "targetMechanics": [],
                },
            }
        ],
        "xHomm3ImplementedMechanics": (
            "Open Gate is a no-op any-hex cast (vanilla demon gate targeting); Homm3InfernoGatingRuntime sees the cast event and gates every pending "
            "reserved stack immediately. The runtime keeps it unavailable while nothing is pending."
        ),
    }


def make_barrier_buff() -> dict[str, Any]:
    return {
        "id": BARRIER_BUFF_SID,
        "infinite": False,
        "hidden": False,
        "canDispel": False,
        "dontMimic": True,
        "dontTriggerAction": True,
        "keepOnDeath": True,
        # Native Carapace barrier: the "bubble" tag negates the next instance of Damage per charge (the runtime adds
        # it with 1 charge, like the Carapace spell and the Angel/Avatar barriers).
        "aiValue": 9400,
        "aiValuePerDuration": 470,
        "vfxList": ["magic/Prefabs_vfx/magic_carapace_unit"],
        "icon": "magic_carapace_effect_icon",
        "name_": f"{SUBSKILL_SHIELDED_ARRIVAL}_name",
        "description_": "magic_carapace_effect_description",
        "tags": ["positive", "bubble"],
        "isPositive": True,
        "maxDuration": 1,
        "addition": "duration",
    }


def make_barrier_info() -> dict[str, Any]:
    return {
        "id": BARRIER_INFO_SID,
        "sid": BARRIER_BUFF_SID,
        "duration": 1,
        "charges": 1,
        "allegiance": "ally",
    }


def make_subskills() -> list[dict[str, Any]]:
    return [
        {
            "id": SUBSKILL_WIDER_GATE,
            "name": f"{SUBSKILL_WIDER_GATE}_name",
            "desc": f"{SUBSKILL_WIDER_GATE}_desc",
            "icon": "h3_imp",
            "bonuses": [],
        },
        {
            "id": SUBSKILL_RAPID_GATE,
            "name": f"{SUBSKILL_RAPID_GATE}_name",
            "desc": f"{SUBSKILL_RAPID_GATE}_desc",
            "icon": "skill_tactics",
            "bonuses": [],
        },
        {
            "id": SUBSKILL_EFFICIENT_GATE,
            "name": f"{SUBSKILL_EFFICIENT_GATE}_name",
            "desc": f"{SUBSKILL_EFFICIENT_GATE}_desc",
            "icon": "sub_skill_faction_demons_2_icon",
            "bonuses": [],
        },
        {
            "id": SUBSKILL_LAVA_ADVANTAGE,
            "name": f"{SUBSKILL_LAVA_ADVANTAGE}_name",
            "desc": f"{SUBSKILL_LAVA_ADVANTAGE}_desc",
            "icon": "sub_skill_faction_demons_1_icon",
            "bonuses": [
                {"type": "unitStat", "biomeType": "native", "fraction": "homm3_inferno", "parameters": ["outAllDmgMod", "0.1"]},
                {"type": "unitStat", "biomeType": "native", "fraction": "homm3_inferno", "parameters": ["inAllDmgMod", "-0.1"]},
            ],
        },
        {
            "id": SUBSKILL_OPEN_GATE,
            "name": f"{SUBSKILL_OPEN_GATE}_name",
            "desc": f"{SUBSKILL_OPEN_GATE}_desc",
            "icon": "sub_skill_summoner_6_icon",
            "bonuses": [{"type": "heroBattleAbility", "parameters": [OPEN_GATE_ABILITY_SID, "0"]}],
        },
        {
            "id": SUBSKILL_SHIELDED_ARRIVAL,
            "name": f"{SUBSKILL_SHIELDED_ARRIVAL}_name",
            "desc": f"{SUBSKILL_SHIELDED_ARRIVAL}_desc",
            "icon": "magic_arinas_chosen_effect_icon",
            "bonuses": [],
        },
    ]


def magic_lang_rows() -> list[dict[str, str]]:
    sid = GATING_TOGGLE_MAGIC_SID
    return [
        {"sid": f"{sid}_name", "text": "Gating"},
        {
            "sid": f"{sid}_description",
            "text": "Open or close the hellgate. While Gating is open, the stacks in this hero's gated army slots skip the opening deployment and enter the battle through the gate in round 2. Click the gate seal on an army slot to reserve it.",
        },
        {"sid": f"{sid}_cast", "text": "The hellgate shifts."},
    ]


def buff_lang_rows() -> list[dict[str, str]]:
    return [
        {"sid": f"{GATING_OPEN_BUFF_SID}_name", "text": "Gating Open"},
        {
            "sid": f"{GATING_OPEN_BUFF_SID}_description",
            "text": "Stacks in gated army slots skip the opening deployment and enter the battle through the hellgate in round 2. Cast Gating again to close the gate.",
        },
        {"sid": "homm3_inferno_gating_slot_description", "text": "Gated army slot."},
    ]


def hero_skill_lang_rows() -> list[dict[str, str]]:
    return [
        {"sid": f"{OPEN_GATE_ABILITY_SID}_name", "text": "Open Gate"},
        {
            "sid": f"{OPEN_GATE_ABILITY_SID}_description",
            "text": "Spend 2 Focus to gate every waiting reinforcement now: click anywhere on the battlefield. Usable only while gated stacks are waiting to enter.",
        },
        {"sid": f"{SUBSKILL_WIDER_GATE}_name", "text": "Wider Gate"},
        {"sid": f"{SUBSKILL_WIDER_GATE}_desc", "text": "Reserve 1 additional army slot for Gating. Its stack also enters in round 2."},
        {"sid": f"{SUBSKILL_RAPID_GATE}_name", "text": "Rapid Gate"},
        {"sid": f"{SUBSKILL_RAPID_GATE}_desc", "text": "Gated stacks gain Haste (level 1) for 1 round when they enter."},
        {"sid": f"{SUBSKILL_EFFICIENT_GATE}_name", "text": "Efficient Gate"},
        {"sid": f"{SUBSKILL_EFFICIENT_GATE}_desc", "text": "Reserve 1 additional army slot for Gating. Stacks with Wider Gate."},
        {"sid": f"{SUBSKILL_LAVA_ADVANTAGE}_name", "text": "Lava Advantage"},
        {
            "sid": f"{SUBSKILL_LAVA_ADVANTAGE}_desc",
            "text": "Inferno creatures on native terrain deal 10% more damage and take 10% less damage.",
        },
        {"sid": f"{SUBSKILL_OPEN_GATE}_name", "text": "Open Gate"},
        {
            "sid": f"{SUBSKILL_OPEN_GATE}_desc",
            "text": "Gain the Open Gate action: spend 2 Focus to gate every waiting reinforcement immediately.",
        },
        {"sid": f"{SUBSKILL_SHIELDED_ARRIVAL}_name", "text": "Shielded Arrival"},
        {"sid": f"{SUBSKILL_SHIELDED_ARRIVAL}_desc", "text": "Gated stacks enter with a barrier that negates the next instance of Damage that round."},
    ]


def merge_inferno_gating_into_overlay(
    *,
    read_doc: Callable[[str], Any],
    write_doc: Callable[[str, Any], None],
    upsert_array_row: Callable[[dict[str, Any], dict[str, Any]], bool],
    remove_array_rows_by_id: Callable[[dict[str, Any], set[str]], bool],
    dedupe_array_rows_by_id: Callable[[dict[str, Any]], bool],
    notes: list[str],
) -> None:
    """Merge every Gating carrier row. Fail closed: the runtime depends on all of them."""

    def edit(path: str, label: str, upserts: list[dict[str, Any]], removals: set[str] | None = None) -> None:
        doc = read_doc(path)
        if not isinstance(doc, dict):
            raise RuntimeError(f"malformed homm3_inferno Gating target {path}")
        changed = remove_array_rows_by_id(doc, removals) if removals else False
        for row in upserts:
            changed = upsert_array_row(doc, row) or changed
        changed = dedupe_array_rows_by_id(doc) or changed
        if changed:
            write_doc(path, doc)
            notes.append(f"merge homm3_inferno Gating {label}")

    magic_doc = read_doc(GATING_MAGIC_PATH)
    source_rows = magic_doc.get("array") if isinstance(magic_doc, dict) else None
    if not isinstance(source_rows, list):
        raise RuntimeError(f"malformed Gating magic source {GATING_MAGIC_PATH}")
    edit(GATING_MAGIC_PATH, "toggle world spell", [make_toggle_magic_row(source_rows)])
    edit(GATING_HERO_BUFFS_PATH, "open/slot hero buffs", make_hero_buff_rows())
    edit(ABILITY_PATH, "Open Gate hero ability", [make_open_gate_ability()], RETIRED_ABILITY_SIDS)
    edit(ABILITY_BONUSES_PATH, "retired summon deltas", [], RETIRED_DELTA_ABILITY_SIDS)
    edit(ABILITY_INFOS_PATH, "retired summon ability infos", [], RETIRED_ABILITY_INFO_SIDS)
    edit(OBSTACLES_PATH, "retired gate obstacles", [], RETIRED_OBSTACLE_IDS)
    edit(BARRIER_BUFFS_PATH, "Shielded Arrival barrier buff", [make_barrier_buff()])
    edit(BARRIER_INFOS_PATH, "Shielded Arrival barrier info", [make_barrier_info()])
    edit(SUBSKILLS_PATH, "subskills", make_subskills(), RETIRED_SUBSKILL_IDS)
