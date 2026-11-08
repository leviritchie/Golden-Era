#!/usr/bin/env python3
"""Normalize generated Tower overlay rows against the release-quality Tower spec.

This is intentionally conservative: it fixes data fields and obvious donor
behavior leaks in the generated overlay, while leaving static-trace debts
marked as metadata instead of pretending unsupported mechanics are complete.
"""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
UNIT_ROOT = ROOT / "experiments" / "homm3_tower" / "generated_core_overlay" / "DB" / "units" / "units_logics" / "homm3_tower"
VIEW_ROOT = ROOT / "experiments" / "homm3_tower" / "generated_core_overlay" / "DB" / "units" / "units_views" / "homm3_tower"
ABILITY_LANG = ROOT / "experiments" / "homm3_tower" / "generated_core_overlay" / "Lang" / "english" / "texts" / "unitsAbility.json"
UNIT_LANG = ROOT / "experiments" / "homm3_tower" / "generated_core_overlay" / "Lang" / "english" / "texts" / "units.json"
CORE_ZIP = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "HeroesOE_Data" / "StreamingAssets" / "Core.zip"
TOWER_MANIFEST = ROOT / "custom_factions" / "homm3_tower.json"


def tower_native_biome() -> str:
    with TOWER_MANIFEST.open("r", encoding="utf-8-sig") as f:
        manifest = json.load(f)
    identity = manifest.get("identity") or {}
    native_biome = identity.get("nativeBiome")
    if not isinstance(native_biome, str) or not native_biome:
        raise ValueError(f"{TOWER_MANIFEST}: identity.nativeBiome is required")
    return native_biome


TOWER_NATIVE_BIOME = tower_native_biome()

TOWER_DONOR_TO_H3_UNIT_BASE = {
    "esquire": "h3_gremlin",
    "crossbowman": "h3_gargoyle",
    "griffin": "h3_golem",
    "lightweaver": "h3_mage",
    "sunlight_cavalry": "h3_genie",
    "inquisitor": "h3_naga",
    "angel": "h3_giant",
}

UNIT_VIEW_DONOR_FIELDS = (
    "mesh",
    "mapMesh",
    "scale",
    "modelHeight",
    "defaultHeight",
    "flipMesh",
    "meshVariants",
    "switchSoundToFly",
    "takeoffPrepareTime",
    "ascentTime",
    "descentTime",
    "startTpTime",
    "endTpTime",
)

H3_TO_DONOR_UNIT_BASE = {h3: donor for donor, h3 in TOWER_DONOR_TO_H3_UNIT_BASE.items()}

TOWER_VANILLA_PROJECTILES: dict[str, dict[str, Any]] = {
    "h3_gremlin_upg": {"projectile": "effects/projectiles/Halfling_projectile", "projectileSpeed": 45, "trajectory": "linear"},
    "h3_mage": {"projectile": "effects/rays/LightWeaver_hit_ray", "projectileSpeed": 200, "trajectory": "ray"},
    "h3_mage_upg": {"projectile": "effects/rays/LightWeaver_upg_hit_ray", "projectileSpeed": 200, "trajectory": "ray"},
    "h3_mage_upg_alt": {"projectile": "effects/rays/Lightweaver_alt_hit_ray", "projectileSpeed": 200, "trajectory": "ray"},
    "h3_giant_upg": {"projectile": "effects/rays/WorldWatcher_ray_vfx", "projectileSpeed": 100, "trajectory": "ray"},
}

STANDARD_TARGETS: dict[str, dict[str, Any]] = {
    "h3_gremlin": dict(offence=3, defence=3, damageMin=1, damageMax=2, hp=4, initiative=4, speed=4, cost=[("gold", 30)], squadValue=44, ai="melee_type", attack="melee", debt=[]),
    "h3_gremlin_upg": dict(offence=4, defence=4, damageMin=1, damageMax=2, hp=4, initiative=5, speed=5, cost=[("gold", 40)], squadValue=66, ai="range_type", attack="shoot", debt=["shots_8_not_modeled"]),
    "h3_gargoyle": dict(offence=6, defence=6, damageMin=2, damageMax=3, hp=16, initiative=6, speed=6, cost=[("gold", 130)], squadValue=165, ai="melee_type", attack="melee", moveType="fly", debt=["bloodless_rules_static_trace"]),
    "h3_gargoyle_upg": dict(offence=7, defence=7, damageMin=2, damageMax=3, hp=16, initiative=9, speed=9, cost=[("gold", 160)], squadValue=201, ai="melee_type", attack="melee", moveType="fly", debt=["bloodless_rules_static_trace"]),
    "h3_golem": dict(offence=7, defence=10, damageMin=4, damageMax=5, hp=30, initiative=3, speed=3, cost=[("gold", 150)], squadValue=250, ai="melee_type", attack="melee", magicDamageReduction=0.5, debt=[]),
    "h3_golem_upg": dict(offence=9, defence=10, damageMin=4, damageMax=5, hp=35, initiative=5, speed=5, cost=[("gold", 200)], squadValue=412, ai="melee_type", attack="melee", magicDamageReduction=0.75, debt=[]),
    "h3_mage": dict(offence=11, defence=8, damageMin=7, damageMax=9, hp=25, initiative=5, speed=5, cost=[("gold", 350)], squadValue=570, ai="range_type", attack="shoot", debt=["shots_24_not_modeled", "magic_channeler_battle_start_persistence_static_trace"]),
    "h3_mage_upg": dict(offence=12, defence=9, damageMin=7, damageMax=9, hp=30, initiative=7, speed=7, cost=[("gold", 450)], squadValue=680, ai="range_type", attack="shoot", debt=["shots_24_not_modeled", "magic_channeler_battle_start_persistence_static_trace"]),
    "h3_genie": dict(offence=12, defence=12, damageMin=13, damageMax=16, hp=40, initiative=7, speed=7, cost=[("gold", 550)], squadValue=884, ai="melee_type", attack="melee", moveType="fly", debt=["efreet_hate_static_trace"]),
    "h3_genie_upg": dict(offence=12, defence=12, damageMin=13, damageMax=16, hp=40, initiative=11, speed=11, cost=[("gold", 600)], squadValue=942, ai="melee_type", attack="melee", moveType="fly", debt=["efreet_hate_static_trace", "master_genie_spellcaster_static_trace"]),
    "h3_naga": dict(offence=16, defence=13, damageMin=20, damageMax=20, hp=110, initiative=5, speed=5, cost=[("gold", 1100)], squadValue=2016, ai="melee_type", attack="melee_no_retaliation", debt=["two_hex_size_static_trace"]),
    "h3_naga_upg": dict(offence=16, defence=13, damageMin=30, damageMax=30, hp=110, initiative=7, speed=7, cost=[("gold", 1600)], squadValue=2840, ai="melee_type", attack="melee_no_retaliation", debt=["two_hex_size_static_trace"]),
    "h3_giant": dict(offence=19, defence=16, damageMin=40, damageMax=60, hp=150, initiative=7, speed=7, cost=[("gold", 2000), ("gemstones", 1)], squadValue=3718, ai="melee_type", attack="melee", debt=["mind_spell_immunity_needs_named_filter_static_trace"]),
    "h3_giant_upg": dict(offence=24, defence=24, damageMin=40, damageMax=60, hp=300, initiative=11, speed=11, cost=[("gold", 5000), ("gemstones", 2)], squadValue=7500, ai="range_type", attack="shoot", debt=["shots_24_not_modeled", "mind_spell_immunity_needs_named_filter_static_trace", "black_dragon_hate_static_trace"]),
}

ALT_TARGETS: dict[str, dict[str, Any]] = {
    "h3_gremlin_upg_alt": dict(offence=3, defence=3, damageMin=1, damageMax=2, hp=6, initiative=5, speed=5, cost=[("gold", 40)], squadValue=74, ai="melee_type", attack="melee", debt=["repair_spellcaster_static_trace"]),
    "h3_gargoyle_upg_alt": dict(offence=6, defence=8, damageMin=2, damageMax=3, hp=20, initiative=7, speed=7, cost=[("gold", 160)], squadValue=230, ai="melee_type", attack="melee", moveType="fly", debt=["gargoyle_profile_static_trace", "elemental_spell_reduction_static_trace"]),
    "h3_golem_upg_alt": dict(offence=7, defence=12, damageMin=4, damageMax=5, hp=35, initiative=5, speed=5, cost=[("gold", 200)], squadValue=460, ai="melee_type", attack="melee", debt=["spell_immunity_static_trace"]),
    "h3_mage_upg_alt": dict(offence=14, defence=8, damageMin=8, damageMax=10, hp=30, initiative=6, speed=6, cost=[("gold", 500)], squadValue=760, ai="range_type", attack="shoot", debt=["shots_24_not_modeled", "battle_mage_shared_charge_pool_static_trace", "magic_channeler_battle_start_persistence_static_trace"]),
    "h3_genie_upg_alt": dict(offence=14, defence=12, damageMin=13, damageMax=16, hp=50, initiative=10, speed=10, cost=[("gold", 650)], squadValue=1050, ai="melee_type", attack="melee", moveType="fly", debt=["air_spell_reduction_static_trace", "efreet_hate_static_trace"]),
    "h3_naga_upg_alt": dict(offence=16, defence=14, damageMin=25, damageMax=25, hp=110, initiative=8, speed=8, cost=[("gold", 1600)], squadValue=3000, ai="melee_type", attack="melee_no_retaliation", debt=["two_hex_size_static_trace"]),
    "h3_giant_upg_alt": dict(offence=26, defence=22, damageMin=40, damageMax=60, hp=330, initiative=12, speed=12, cost=[("gold", 5000), ("gemstones", 2)], squadValue=8200, ai="melee_type", attack="melee", debt=["thunderbolt_after_attack_static_trace", "mind_immunity_static_trace", "dragon_hate_static_trace"]),
}

STANDARD_VIEW_PASSIVES: dict[str, list[tuple[str, str]]] = {
    "h3_gremlin_upg": [("h3_gremlin_upg_ability_1_name", "h3_gremlin_upg_ability_1_description")],
    "h3_gargoyle": [("h3_gargoyle_ability_1_name", "h3_gargoyle_ability_1_description"), ("h3_gargoyle_ability_2_name", "h3_gargoyle_ability_2_description")],
    "h3_gargoyle_upg": [("h3_gargoyle_ability_1_name", "h3_gargoyle_ability_1_description"), ("h3_gargoyle_ability_2_name", "h3_gargoyle_ability_2_description")],
    "h3_golem": [("h3_golem_ability_1_name", "h3_golem_ability_1_description"), ("h3_golem_ability_2_name", "h3_golem_ability_2_description")],
    "h3_golem_upg": [("h3_golem_upg_ability_1_name", "h3_golem_upg_ability_1_description"), ("h3_golem_ability_2_name", "h3_golem_ability_2_description")],
    "h3_mage": [("h3_mage_ability_1_name", "h3_mage_ability_1_description"), ("h3_mage_ability_2_name", "h3_mage_ability_2_description"), ("h3_mage_ability_3_name", "h3_mage_ability_3_description")],
    "h3_mage_upg": [("h3_mage_ability_1_name", "h3_mage_ability_1_description"), ("h3_mage_ability_2_name", "h3_mage_ability_2_description"), ("h3_mage_ability_3_name", "h3_mage_ability_3_description")],
    "h3_genie": [("h3_genie_ability_1_name", "h3_genie_ability_1_description"), ("h3_genie_ability_2_name", "h3_genie_ability_2_description")],
    "h3_genie_upg": [("h3_genie_ability_1_name", "h3_genie_ability_1_description"), ("h3_genie_ability_2_name", "h3_genie_ability_2_description"), ("h3_genie_upg_ability_1_name", "h3_genie_upg_ability_1_description")],
    "h3_naga": [("h3_naga_ability_1_name", "h3_naga_ability_1_description"), ("h3_naga_ability_2_name", "h3_naga_ability_2_description")],
    "h3_naga_upg": [("h3_naga_ability_1_name", "h3_naga_ability_1_description"), ("h3_naga_ability_2_name", "h3_naga_ability_2_description")],
    "h3_giant": [("h3_giant_ability_1_name", "h3_giant_ability_1_description")],
    "h3_giant_upg": [("h3_giant_upg_ability_1_name", "h3_giant_upg_ability_1_description"), ("h3_giant_ability_1_name", "h3_giant_ability_1_description"), ("h3_giant_upg_ability_2_name", "h3_giant_upg_ability_2_description")],
}

ALT_VIEW_PASSIVES: dict[str, list[tuple[str, str]]] = {
    "h3_gremlin_upg_alt": [("h3_gremlin_upg_alt_ability_name", "h3_gremlin_upg_alt_ability_description")],
    "h3_gargoyle_upg_alt": [("h3_gargoyle_upg_alt_ability_name", "h3_gargoyle_upg_alt_ability_description")],
    "h3_golem_upg_alt": [("h3_golem_upg_alt_ability_name", "h3_golem_upg_alt_ability_description")],
    "h3_mage_upg_alt": [("h3_mage_upg_alt_ability_name", "h3_mage_upg_alt_ability_description")],
    "h3_genie_upg_alt": [("h3_genie_upg_alt_ability_name", "h3_genie_upg_alt_ability_description")],
    "h3_naga_upg_alt": [("h3_naga_upg_alt_ability_name", "h3_naga_upg_alt_ability_description")],
    "h3_giant_upg_alt": [("h3_giant_upg_alt_ability_name", "h3_giant_upg_alt_ability_description"), ("h3_giant_ability_1_name", "h3_giant_ability_1_description")],
}

ABILITY_TEXT: dict[str, str] = {
    "h3_gremlin_upg_ability_1_name": "Ranged Attack",
    "h3_gremlin_upg_ability_1_description": "Shoots at enemy units. Master Gremlins have 8 shots in the Heroes III baseline.",
    "h3_gargoyle_ability_1_name": "Flying",
    "h3_gargoyle_ability_1_description": "Can fly over obstacles and units when moving.",
    "h3_gargoyle_ability_2_name": "Bloodless",
    "h3_gargoyle_ability_2_description": "Treated as non-living for living-only effects such as life drain, poison, disease, and resurrection restrictions. This still needs native effect-flag tracing.",
    "h3_golem_ability_1_name": "Spell Damage Reduction",
    "h3_golem_ability_1_description": "Takes 50% less magic damage.",
    "h3_golem_upg_ability_1_name": "Spell Damage Reduction",
    "h3_golem_upg_ability_1_description": "Takes 75% less magic damage.",
    "h3_golem_ability_2_name": "Golem",
    "h3_golem_ability_2_description": "Uses the native construct profile: neutral Morale/Luck, Necromancy/life-drain exclusions, and poison/blood/curse restrictions.",
    "h3_mage_ability_1_name": "Ranged Attack",
    "h3_mage_ability_1_description": "Shoots at enemy units. Mages and Arch Mages have 24 shots in the Heroes III baseline.",
    "h3_mage_ability_2_name": "No Melee or Obstacle Penalty",
    "h3_mage_ability_2_description": "Ranged attacks are not penalized in melee or by range/obstacle falloff.",
    "h3_mage_ability_3_name": "Magic Channeler",
    "h3_mage_ability_3_description": "Reduces allied hero combat spell costs by 2 using the native spell-cost side modifier. Battle-start persistence after stack death still needs runtime validation.",
    "h3_genie_ability_1_name": "Flying",
    "h3_genie_ability_1_description": "Can fly over obstacles and units when moving.",
    "h3_genie_ability_2_name": "Efreet Hate",
    "h3_genie_ability_2_description": "Deals 150% damage to Efreet-line enemies in the Heroes III baseline. Target-family detection still needs native tracing.",
    "h3_genie_upg_ability_1_name": "Spellcaster",
    "h3_genie_upg_ability_1_description": "Master Genies can cast a copied native beneficial spell up to 3 times per battle. Exact random spell selection and school-level/power mapping still need validation.",
    "h3_naga_ability_1_name": "No Retaliation",
    "h3_naga_ability_1_description": "Enemy units do not retaliate against this unit's melee attacks.",
    "h3_naga_ability_2_name": "Fixed Damage",
    "h3_naga_ability_2_description": "Always deals fixed damage instead of rolling a damage range.",
    "h3_giant_ability_1_name": "Mind Spell Immunity",
    "h3_giant_ability_1_description": "Immune to mind spells in the Heroes III baseline. Exact named mind-spell filtering still needs native effect-tag tracing.",
    "h3_giant_upg_ability_1_name": "Ranged Attack",
    "h3_giant_upg_ability_1_description": "Shoots at enemy units. Titans have 24 shots and no melee penalty in the Heroes III baseline.",
    "h3_giant_upg_ability_2_name": "Black Dragon Hate",
    "h3_giant_upg_ability_2_description": "Deals 150% damage to Black Dragons in the Heroes III baseline. Target-family detection still needs native tracing.",
    "h3_gremlin_upg_alt_ability_name": "Repair",
    "h3_gremlin_upg_alt_ability_description": "Can cast a two-charge Repair action using the native revive/heal contract. Exact siege/Golem/Gargoyle/Giant target filtering still needs validation.",
    "h3_gargoyle_upg_alt_ability_name": "Elemental Carapace",
    "h3_gargoyle_upg_alt_ability_description": "Has the Gargoyle construct profile, flies, takes 50% less Air, Earth, Fire, and Water spell damage, and is immune to Stone Gaze. Native resistance flags still need implementation.",
    "h3_golem_upg_alt_ability_name": "Magnetic Slow",
    "h3_golem_upg_alt_ability_description": "Can cast a focus-costing Slow action using the native Web slow contract. Spell/Stone Gaze immunity still needs exact effect filters.",
    "h3_mage_upg_alt_ability_name": "Battle Mage Spells",
    "h3_mage_upg_alt_ability_description": "Shoots with 24 shots, reduces allied spell costs by 2, and has copied native bolt spell actions. A shared three-cast pool still needs validation.",
    "h3_genie_upg_alt_ability_name": "Vizier's Misfortune",
    "h3_genie_upg_alt_ability_description": "Flies, hates Efreet-family enemies, takes 50% less Air spell damage, and can cast a focus-costing Misfortune-style debuff. Exact Air reduction and hate still need tracing.",
    "h3_naga_upg_alt_ability_name": "Three-Headed Attack",
    "h3_naga_upg_alt_ability_description": "Deals fixed no-retaliation melee damage and uses the native Hydra-style three-headed attack pattern.",
    "h3_giant_upg_alt_ability_name": "Thunderbolt",
    "h3_giant_upg_alt_ability_description": "Has a 40% chance to cast Thunderbolt after attacking, dealing 25 damage per Colossus. Native after-attack spell hooks still need implementation.",
}

UNIT_TEXT: dict[str, str] = {
    "h3_gremlin_upg_alt_name": "Gremlin Mechanic",
    "h3_gargoyle_upg_alt_name": "Elemental Gargoyle",
    "h3_golem_upg_alt_name": "Magnetic Golem",
    "h3_mage_upg_alt_name": "Battle Mage",
    "h3_genie_upg_alt_name": "Genie Vizier",
    "h3_naga_upg_alt_name": "Naga Rani",
    "h3_giant_upg_alt_name": "Colossus",
}

ATTACK_TEXT: dict[str, str] = {
    "h3_common_melee_attack_name": "Melee Attack",
    "h3_common_melee_attack_description": "Attacks an adjacent enemy unit.",
    "h3_common_ranged_attack_name": "Ranged Attack",
    "h3_common_ranged_attack_description": "Shoots at enemy units.",
    "h3_common_no_retaliation_attack_name": "No Retaliation Attack",
    "h3_common_no_retaliation_attack_description": "Attacks an adjacent enemy unit without triggering retaliation.",
    "h3_master_genie_boon_ability_name": "Master Genie Boon",
    "h3_master_genie_boon_ability_description": "Casts a copied native beneficial Haste-style spell up to 3 times. Random beneficial spell selection still needs validation.",
    "h3_repair_active_ability_name": "Repair",
    "h3_repair_active_ability_description": "Restores an allied stack using the native revive/heal ability contract.",
    "h3_magnetic_slow_active_ability_name": "Magnetic Slow",
    "h3_magnetic_slow_active_ability_description": "Applies the native Web slow effect to an enemy stack.",
    "h3_battle_mage_magic_arrow_ability_name": "Magic Arrow",
    "h3_battle_mage_magic_arrow_ability_description": "Deals copied native pure bolt damage to an enemy stack.",
    "h3_battle_mage_ice_bolt_ability_name": "Ice Bolt",
    "h3_battle_mage_ice_bolt_ability_description": "Deals copied native Ice Bolt damage and initiative debuff to an enemy stack.",
    "h3_battle_mage_lightning_ability_name": "Lightning Bolt",
    "h3_battle_mage_lightning_ability_description": "Deals copied native Thunderbolt damage to an enemy stack.",
    "h3_vizier_misfortune_active_ability_name": "Vizier's Misfortune",
    "h3_vizier_misfortune_active_ability_description": "Applies a copied native Unnatural Calm debuff as a data-only Misfortune stand-in.",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save(path: Path, doc: dict[str, Any]) -> None:
    path.write_text(json.dumps(doc, indent="\t", ensure_ascii=False) + "\n", encoding="utf-8")


def construct_profile_passives() -> list[dict[str, Any]]:
    return [
        {"data": {"immunities": [{"type": "cast", "tags": ["construct_immunities"]}]}},
        {"data": {"disablers": [{"mech": "vampirism"}, {"mech": "destroy_corpse_and_heal"}]}},
        {
            "data": {
                "immunities": [
                    {"type": "effect", "tags": ["overTime_effect_curse"]},
                    {"type": "effect", "tags": ["overTime_effect_blood"]},
                    {"type": "effect", "tags": ["overTime_effect_poison"]},
                    {"type": "effect", "tags": ["buff_effect_poison"]},
                ]
            }
        },
    ]


def magic_channeler_passive() -> dict[str, Any]:
    return {
        "data": {
            "sideModifiers": [
                {
                    "tag": "homm3_tower_magic_channeler",
                    "power": 2,
                    "heroStat": {"manaCostBonus": -2},
                    "target": "ally",
                }
            ]
        }
    }


def battle_magic_dealer(
    *,
    tags: list[str],
    cast_target: str,
    damage_target: str = "none",
    damage_type: str = "none",
    buff_target: str | None = None,
    buff_sid: str | None = None,
    buff_duration: int = 1,
    min_base_dmg: int | None = None,
    max_base_dmg: int | None = None,
    min_stack_dmg: int | None = None,
    max_stack_dmg: int | None = None,
    target_mechanics: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    dealer: dict[str, Any] = {
        "tags": ["ability", *tags],
        "triggerCounter": False,
        "attackPatternSid": "attack_single_x100",
        "castTargetParams": {
            "targetTags": ["unit"],
            "castTarget_": cast_target,
            "targetCondition_": "alive",
            "selection": "object",
        },
        "affectTargetParams": {
            "targetTags": ["unit"],
            "castTarget_": cast_target,
            "targetCondition_": "alive",
            "selection": "object",
        },
        "damageTarget_": damage_target,
        "damageType_": damage_type,
        "targetMechanics": target_mechanics or [],
    }
    if buff_target and buff_sid:
        dealer["buffTarget_"] = buff_target
        dealer["buff"] = {"sid": buff_sid, "duration": buff_duration}
    for key, value in (
        ("minBaseDmg", min_base_dmg),
        ("maxBaseDmg", max_base_dmg),
        ("minStackDmg", min_stack_dmg),
        ("maxStackDmg", max_stack_dmg),
    ):
        if value is not None:
            dealer[key] = value
    return dealer


def cast_ability(
    dealer: dict[str, Any],
    *,
    rank: int,
    energy_level: int,
    cd: int,
    charges: int | None = None,
    action_cost: int | None = None,
    disable_for_ai: bool | None = None,
) -> dict[str, Any]:
    ability: dict[str, Any] = {
        "attackType_": "cast",
        "rank": rank,
        "selfMechanics": [],
        "cd": cd,
        "energyLevel": energy_level,
        "damageDealer": copy.deepcopy(dealer),
    }
    if charges is not None:
        ability["charges"] = charges
    if action_cost is not None:
        ability["actionCost"] = action_cost
    if disable_for_ai is not None:
        ability["disableForAi"] = disable_for_ai
    return ability


def repair_ability() -> dict[str, Any]:
    dealer = battle_magic_dealer(
        tags=["heal_ability", "revive_ability", "charge_ability"],
        cast_target="ally",
        target_mechanics=[
            {"mech": "heal_percent", "values": ["with respawn", "max_unit", "0.10", "0.00", "true"]}
        ],
    )
    return cast_ability(dealer, rank=2, energy_level=2, cd=2, charges=2, action_cost=0)


def slow_ability() -> dict[str, Any]:
    dealer = battle_magic_dealer(
        tags=["debuff_ability", "slow"],
        cast_target="enemy",
        buff_target="enemy",
        buff_sid="magic_web_effect_0",
        buff_duration=1,
        target_mechanics=[{"mech": "dispel", "values": ["hasteEffect"]}],
    )
    return cast_ability(dealer, rank=2, energy_level=2, cd=2)


def misfortune_ability() -> dict[str, Any]:
    dealer = battle_magic_dealer(
        tags=["debuff_ability"],
        cast_target="enemy",
        buff_target="enemy",
        buff_sid="magic_unnatural_calm_effect_1",
        buff_duration=2,
    )
    return cast_ability(dealer, rank=2, energy_level=2, cd=2)


def master_genie_boon_ability() -> dict[str, Any]:
    dealer = battle_magic_dealer(
        tags=["buff_ability", "charge_ability"],
        cast_target="ally",
        buff_target="ally",
        buff_sid="magic_haste_effect_1",
        buff_duration=1,
    )
    return cast_ability(dealer, rank=2, energy_level=2, cd=1, charges=3, action_cost=0)


def battle_mage_spell_abilities() -> list[dict[str, Any]]:
    pure_bolt = battle_magic_dealer(
        tags=["magic_damage"],
        cast_target="enemy",
        damage_target="enemy",
        damage_type="magic_pure",
        min_base_dmg=25,
        max_base_dmg=25,
        min_stack_dmg=5,
        max_stack_dmg=5,
    )
    ice_bolt = battle_magic_dealer(
        tags=["magic_damage", "primal_6_magic_ice_bolt_damage"],
        cast_target="enemy",
        damage_target="enemy",
        damage_type="magic_pure",
        buff_target="enemy",
        buff_sid="magic_ice_bolt_effect_0",
        buff_duration=2,
        min_base_dmg=75,
        max_base_dmg=75,
        min_stack_dmg=10,
        max_stack_dmg=10,
    )
    thunderbolt = battle_magic_dealer(
        tags=["magic_damage", "primal_1_magic_thunderbolt_damage"],
        cast_target="enemy",
        damage_target="enemy",
        damage_type="magic_pure",
        min_base_dmg=25,
        max_base_dmg=25,
        min_stack_dmg=10,
        max_stack_dmg=10,
    )
    return [
        cast_ability(pure_bolt, rank=1, energy_level=1, cd=1, charges=1, action_cost=0),
        cast_ability(ice_bolt, rank=2, energy_level=2, cd=1, charges=1, action_cost=0),
        cast_ability(thunderbolt, rank=1, energy_level=1, cd=1, charges=1, action_cost=0),
    ]


def first_melee_attack(row: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("defaultAttacks", "alternativeAttacks", "counterAttacks"):
        for attack in row.get(key) or []:
            if attack.get("attackType_") == "melee":
                return copy.deepcopy(attack)
    return None


def first_shoot_attack(row: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("defaultAttacks", "alternativeAttacks"):
        for attack in row.get(key) or []:
            if attack.get("attackType_") == "shoot":
                return copy.deepcopy(attack)
    return None


def set_trigger_counter(attack: dict[str, Any], value: bool) -> None:
    dealer = attack.get("damageDealer")
    if isinstance(dealer, dict):
        dealer["triggerCounter"] = value


def set_stat_dmg_mult(attack: dict[str, Any], value: float) -> None:
    dealer = attack.get("damageDealer")
    if isinstance(dealer, dict):
        dealer["statDmgMult"] = value


def normalize_shoot_dealer(attack: dict[str, Any], *, no_penalty: bool) -> None:
    dealer = attack.get("damageDealer")
    if not isinstance(dealer, dict):
        return
    dealer["shootRange"] = -1
    dealer["triggerCounter"] = True
    dealer["statDmgMult"] = 1
    if no_penalty:
        dealer["shootDmgBuff"] = 0.0


def set_default_attack_pattern(row: dict[str, Any], pattern_sid: str) -> None:
    for attack in row.get("defaultAttacks") or []:
        dealer = attack.get("damageDealer") if isinstance(attack, dict) else None
        if isinstance(dealer, dict):
            dealer["attackPatternSid"] = pattern_sid


def normalize_attacks(row: dict[str, Any], mode: str) -> None:
    melee = first_melee_attack(row)
    shoot = first_shoot_attack(row)
    sid = str(row.get("id", ""))
    no_penalty_shooter = sid in {"h3_mage", "h3_mage_upg", "h3_mage_upg_alt", "h3_giant_upg"}
    if melee is not None:
        set_trigger_counter(melee, mode != "melee_no_retaliation")
        set_stat_dmg_mult(melee, 1 if no_penalty_shooter or mode.startswith("melee") else 0.5)
        dealer = melee.get("damageDealer")
        if isinstance(dealer, dict) and mode.startswith("melee"):
            dealer["attackPatternSid"] = "attack_single_x100"
    if shoot is not None:
        set_trigger_counter(shoot, mode != "shoot_no_retaliation")
        normalize_shoot_dealer(shoot, no_penalty=no_penalty_shooter)
    for counter in row.get("counterAttacks") or []:
        if isinstance(counter, dict) and counter.get("attackType_") == "melee":
            set_trigger_counter(counter, False)
            set_stat_dmg_mult(counter, 1 if no_penalty_shooter or mode.startswith("melee") else 0.5)

    if mode.startswith("melee"):
        if melee is not None:
            row["defaultAttacks"] = [melee]
        row["alternativeAttacks"] = []
        row["abilities"] = []
    elif mode == "shoot":
        if shoot is not None:
            row["defaultAttacks"] = [shoot]
        row["alternativeAttacks"] = [melee] if melee is not None else []
        row["abilities"] = []

    if no_penalty_shooter:
        row.setdefault("stats", {})["ignoreShootDmgBuff"] = True
    elif mode.startswith("melee"):
        row.setdefault("stats", {}).pop("ignoreShootDmgBuff", None)


def view_attack(
    animation_index: int = 0,
    *,
    name: str | None = None,
    description: str | None = None,
    ability_type: str | None = None,
    projectile_sid: str | None = None,
) -> dict[str, Any]:
    attack: dict[str, Any] = {"animationIndex": animation_index}
    if projectile_sid:
        spec = TOWER_VANILLA_PROJECTILES.get(projectile_sid)
        if spec:
            attack.update(copy.deepcopy(spec))
    if name:
        attack["name"] = name
    if description:
        attack["description"] = description
    if ability_type:
        attack["abilityType"] = ability_type
        attack["infoDescription"] = "ability_no_energy"
        attack["canShowOnUI"] = True
        attack["useExpandTooltip"] = "false"
    return attack


def normalize_view_attacks(row: dict[str, Any], mode: str) -> None:
    row["counterAttacks"] = [view_attack(0)]
    sid = str(row.get("id", ""))
    if mode == "shoot":
        row["defaultAttacks"] = [view_attack(0, projectile_sid=sid)]
        row["alternativeAttacks"] = [
            view_attack(
                1,
                name="h3_common_melee_attack_name",
                description="h3_common_melee_attack_description",
                ability_type="Ability_type_attack_alt",
            )
        ]
        return

    if mode == "melee_no_retaliation":
        row["defaultAttacks"] = [
            view_attack(
                0,
                name="h3_common_no_retaliation_attack_name",
                description="h3_common_no_retaliation_attack_description",
            )
        ]
    else:
        row["defaultAttacks"] = [view_attack(0)]
    row["alternativeAttacks"] = []


def logic_passives_for_sid(sid: str) -> list[dict[str, Any]]:
    passives: list[dict[str, Any]] = []
    if sid in {"h3_golem", "h3_golem_upg", "h3_golem_upg_alt"}:
        passives.extend(construct_profile_passives())
    if sid in {"h3_mage", "h3_mage_upg", "h3_mage_upg_alt"}:
        passives.append(magic_channeler_passive())
    return copy.deepcopy(passives)


def logic_abilities_for_sid(sid: str) -> list[dict[str, Any]]:
    if sid == "h3_gremlin_upg_alt":
        return [repair_ability()]
    if sid == "h3_golem_upg_alt":
        return [slow_ability()]
    if sid == "h3_mage_upg_alt":
        return battle_mage_spell_abilities()
    if sid == "h3_genie_upg":
        return [master_genie_boon_ability()]
    if sid == "h3_genie_upg_alt":
        return [misfortune_ability()]
    return []


def implemented_data_for_sid(sid: str) -> str:
    implemented = ["stats", "cost", "squadValue", "faction/nativeBiome", "primary attack role"]
    if sid == "h3_gremlin":
        implemented.append("melee-only guard")
    if sid in {"h3_golem", "h3_golem_upg", "h3_golem_upg_alt"}:
        implemented.append("construct profile")
    if sid in {"h3_golem", "h3_golem_upg"}:
        implemented.append("native magic-damage reduction")
    if sid in {"h3_mage", "h3_mage_upg", "h3_mage_upg_alt", "h3_giant_upg"}:
        implemented.append("no melee/range penalty shooter contract")
    if sid in {"h3_mage", "h3_mage_upg", "h3_mage_upg_alt"}:
        implemented.append("native spell-cost side modifier")
    if sid in {"h3_naga", "h3_naga_upg", "h3_naga_upg_alt"}:
        implemented.append("no-retaliation attack flag")
    if sid == "h3_naga_upg_alt":
        implemented.append("Hydra-style multi-hex attack pattern")
    if sid in {"h3_gremlin_upg_alt", "h3_golem_upg_alt", "h3_mage_upg_alt", "h3_genie_upg", "h3_genie_upg_alt"}:
        implemented.append("native active ability row")
    return ", ".join(implemented)


def append_passive(passives: list[dict[str, str]], name: str, description: str) -> None:
    if not any(item.get("name") == name for item in passives):
        passives.append({"name": name, "description": description})


def view_abilities_for_sid(sid: str) -> list[dict[str, Any]]:
    if sid == "h3_gremlin_upg_alt":
        return [
            {
                "name": "h3_repair_active_ability_name",
                "abilityType": "Ability_type_special",
                "description": "h3_repair_active_ability_description",
                "animationIndex": 2,
                "useExpandTooltip": "false",
            }
        ]
    if sid == "h3_golem_upg_alt":
        return [
            {
                "name": "h3_magnetic_slow_active_ability_name",
                "abilityType": "Ability_type_special",
                "description": "h3_magnetic_slow_active_ability_description",
                "animationIndex": 2,
                "useExpandTooltip": "false",
            }
        ]
    if sid == "h3_mage_upg_alt":
        return [
            {
                "name": "h3_battle_mage_magic_arrow_ability_name",
                "abilityType": "Ability_type_special",
                "description": "h3_battle_mage_magic_arrow_ability_description",
                "animationIndex": 2,
                "useExpandTooltip": "false",
            },
            {
                "name": "h3_battle_mage_ice_bolt_ability_name",
                "abilityType": "Ability_type_special",
                "description": "h3_battle_mage_ice_bolt_ability_description",
                "animationIndex": 3,
                "useExpandTooltip": "false",
            },
            {
                "name": "h3_battle_mage_lightning_ability_name",
                "abilityType": "Ability_type_special",
                "description": "h3_battle_mage_lightning_ability_description",
                "animationIndex": 4,
                "useExpandTooltip": "false",
            },
        ]
    if sid == "h3_genie_upg":
        return [
            {
                "name": "h3_master_genie_boon_ability_name",
                "abilityType": "Ability_type_special",
                "description": "h3_master_genie_boon_ability_description",
                "animationIndex": 2,
                "useExpandTooltip": "false",
            }
        ]
    if sid == "h3_genie_upg_alt":
        return [
            {
                "name": "h3_vizier_misfortune_active_ability_name",
                "abilityType": "Ability_type_special",
                "description": "h3_vizier_misfortune_active_ability_description",
                "animationIndex": 2,
                "useExpandTooltip": "false",
            }
        ]
    return []


def copy_donor_view_fields(row: dict[str, Any], sid: str) -> None:
    if not CORE_ZIP.exists():
        return
    suffix = ""
    base_sid = sid
    for candidate in ("_upg_alt", "_upg"):
        if sid.endswith(candidate):
            base_sid = sid[: -len(candidate)]
            suffix = candidate
            break
    donor_base = H3_TO_DONOR_UNIT_BASE.get(base_sid)
    if donor_base is None:
        return
    donor_name = f"DB/units/units_views/humans/{donor_base}{suffix}_v.json"
    try:
        with zipfile.ZipFile(CORE_ZIP) as zf:
            donor = json.loads(zf.read(donor_name).decode("utf-8-sig"))
    except (KeyError, OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    donor_row = donor.get("array", [{}])[0]
    if not isinstance(donor_row, dict):
        return
    for field in UNIT_VIEW_DONOR_FIELDS:
        if field in donor_row:
            row[field] = copy.deepcopy(donor_row[field])
        else:
            row.pop(field, None)


def normalize_standard(row: dict[str, Any], target: dict[str, Any]) -> None:
    sid = str(row.get("id", ""))
    row["fraction"] = "homm3_tower"
    row["nativeBiome"] = TOWER_NATIVE_BIOME
    row["ai"] = target["ai"]
    row["tags"] = ["unit", "homm3_tower"]
    row["squadValue"] = target["squadValue"]
    row["unitCost"] = {"costResArray": [{"name": name, "cost": cost} for name, cost in target["cost"]]}

    stats = row.setdefault("stats", {})
    for key in ("offence", "defence", "damageMin", "damageMax", "hp", "initiative", "speed"):
        stats[key] = target[key]
    stats["numCounters"] = 1
    in_dmg_mods = stats.setdefault("inDmgMods", {})
    if not isinstance(in_dmg_mods, dict):
        in_dmg_mods = {}
        stats["inDmgMods"] = in_dmg_mods
    mod_list = in_dmg_mods.setdefault("list", [])
    if not isinstance(mod_list, list):
        mod_list = []
        in_dmg_mods["list"] = mod_list
    mod_list[:] = [item for item in mod_list if not (isinstance(item, dict) and item.get("t") == "magic_damage")]
    magic_reduction = target.get("magicDamageReduction")
    if magic_reduction is not None:
        mod_list.append({"t": "magic_damage", "v": -float(magic_reduction)})
    if target.get("moveType") == "fly":
        stats["moveType"] = "fly"
    else:
        stats.pop("moveType", None)

    normalize_attacks(row, target["attack"])
    row["passives"] = logic_passives_for_sid(sid)
    row["abilities"] = logic_abilities_for_sid(sid)
    row.pop("aura", None)
    row.pop("xHomm3TowerDecision", None)
    if sid.endswith("_upg"):
        row["upgradeSid"] = sid + "_alt"
    row["xHomm3ReleaseQuality"] = {
        "source": "docs/homm3_faction_plans/tower.md",
        "status": "standard_hota_baseline",
        "implementedData": implemented_data_for_sid(sid),
    }


def normalize_alt(row: dict[str, Any], target: dict[str, Any]) -> None:
    row["fraction"] = "homm3_tower"
    row["nativeBiome"] = TOWER_NATIVE_BIOME
    row["ai"] = target["ai"]
    row["tags"] = ["unit", "homm3_tower"]
    row["squadValue"] = target["squadValue"]
    row["unitCost"] = {"costResArray": [{"name": name, "cost": cost} for name, cost in target["cost"]]}

    stats = row.setdefault("stats", {})
    for key in ("offence", "defence", "damageMin", "damageMax", "hp", "initiative", "speed"):
        stats[key] = target[key]
    stats["numCounters"] = 1
    if target.get("moveType") == "fly":
        stats["moveType"] = "fly"
    else:
        stats.pop("moveType", None)

    normalize_attacks(row, target["attack"])
    if row.get("id") == "h3_naga_upg_alt":
        set_default_attack_pattern(row, "attack_swirl_x1_x100")
    sid = str(row.get("id", ""))
    row["passives"] = logic_passives_for_sid(sid)
    row["abilities"] = logic_abilities_for_sid(sid)
    row.pop("aura", None)
    row.pop("xHomm3TowerDecision", None)
    row["xHomm3ReleaseQuality"] = {
        "source": "docs/homm3_tears_of_ashan_creature_specs.md",
        "status": "alternate_upgrade_extension",
        "implementedData": implemented_data_for_sid(sid),
    }


def normalize_view(row: dict[str, Any]) -> bool:
    sid = row.get("id") or row.get("sid")
    target = STANDARD_TARGETS.get(sid) or ALT_TARGETS.get(sid)
    if target is None:
        return False
    row["id"] = sid
    row["sid"] = sid
    copy_donor_view_fields(row, sid)
    row["abilities"] = view_abilities_for_sid(sid)
    passives = STANDARD_VIEW_PASSIVES.get(sid, []) or ALT_VIEW_PASSIVES.get(sid, [])
    row["passives"] = [{"name": name, "description": desc} for name, desc in passives]
    if sid in {"h3_golem", "h3_golem_upg", "h3_golem_upg_alt"}:
        row["baseClass"] = {"name": "base_class_construct", "description": "base_class_construct_description"}
    if sid in {"h3_mage", "h3_mage_upg", "h3_mage_upg_alt", "h3_giant_upg"}:
        append_passive(row["passives"], "base_passive_duelist_name", "base_passive_duelist_description")
    if sid in {"h3_naga", "h3_naga_upg", "h3_naga_upg_alt"}:
        append_passive(row["passives"], "base_passive_melee_attack_no_counter_name", "base_passive_melee_attack_no_counter_description")
    normalize_view_attacks(row, target["attack"])
    return True


def normalize_ability_lang() -> None:
    doc = load(ABILITY_LANG) if ABILITY_LANG.exists() else {}
    doc.update(ABILITY_TEXT)
    doc.update(ATTACK_TEXT)
    save(ABILITY_LANG, doc)


def normalize_unit_lang() -> None:
    doc = load(UNIT_LANG) if UNIT_LANG.exists() else {}
    doc.update(UNIT_TEXT)
    save(UNIT_LANG, doc)


def main() -> int:
    changed = 0
    for path in sorted(UNIT_ROOT.glob("*_l.json")):
        doc = load(path)
        row = doc.get("array", [{}])[0]
        sid = row.get("id")
        if sid in STANDARD_TARGETS:
            normalize_standard(row, STANDARD_TARGETS[sid])
        elif sid in ALT_TARGETS:
            normalize_alt(row, ALT_TARGETS[sid])
        else:
            continue
        save(path, doc)
        changed += 1
    view_changed = 0
    for path in sorted(VIEW_ROOT.glob("*_v.json")):
        doc = load(path)
        row = doc.get("array", [{}])[0]
        if not normalize_view(row):
            continue
        save(path, doc)
        view_changed += 1
    normalize_ability_lang()
    normalize_unit_lang()
    print(f"normalized {changed} Tower unit logic row(s), {view_changed} unit view row(s), ability localization, and unit localization")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
