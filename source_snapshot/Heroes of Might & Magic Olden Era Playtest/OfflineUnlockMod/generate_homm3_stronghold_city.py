"""
HoMM3 Stronghold-style faction (placeholder visuals): clone Dungeon town, units,
laws, and fraction wiring into Core.zip.

* New fraction id: homm3_stronghold
* City: homm3_stronghold_city (cloned from dungeon_city), sceneName cityDungeon
* Units: h3_goblin, h3_wolf_rider, ... (logic/view copied from dungeon tiers; mesh paths use isolated HoMM3 import triggers)
* Laws: fractions_laws_table_homm3_stronghold.json (clone of dungeon table + remaps)
* All Lang locales under StreamingAssets/Lang/*/texts/: cities.json, factionLaws.json, args/cities.json,
  args/factionLaws.json (once),
  unitsAbility.json + unitsBuff.json (clone trogl/assassin/... tokens for each h3_* unit sid), mapObjects.json (town tooltip).
  English also gets explicit Homm3Stronghold_Build_* tier strings; other locales mirror Dungeon_* from the same locale.
* data.json: append homm3_stronghold to fractions + availableFractions
* DB/map/objects/4_interactables.json — register homm3_stronghold_city (clone of dungeon_city;
  prefs stay interactive/dungeon_city so the adventure map has a placeable prefab).
* DB/map_objects_sounds.json, DB/city_ambient_sounds.json, DB/city_music_sounds.json — clone dungeon entries.
* DB/objects_logic/hires/barracks.json — clone Dungeon barracks rows for homm3_stronghold;
  startup/city session code expects faction-tier hire rows outside the city config itself.
* DB/buildings_bans/M{2,10}_banlists.json + DB/buildings_constructions/M{2,10}_buildings_presets.json — clone each
  `*_dungeon_city` preset row to `*_homm3_stronghold_city` (same building lists; city uses same generic Build_* sids as Dungeon).
* DB/squads/squads_homm3_stronghold/** — clone of squads_dungeon (squad ids + unit SIDs + fraction);
  required for session/neutral squads; missing it breaks adventure UI for the new fraction.
* Orphan unit id **goblin_rogue** (referenced in unit_sets / rewards / campaign JSON, no unit config in Core):
  remapped to **halfling** so mapgen/session stops spamming `[Config] Config with id "goblin_rogue" was not found`.

City UI: Optional 2D backdrop for fraction ``homm3_stronghold`` is loaded by ``Plugin.cs``
next to the DLL: ``BepInEx/plugins/OfflineUnlockMod/homm3_runtime_assets/town_scene_refs/homm3_stronghold/mockups/``
(fallback: ``<game>/OfflineUnlockMod/homm3_runtime_assets/...``). Replace the tiny placeholder PNG when you have real art.

Lock parity after changes (read-only check of Core.zip):
  python verify_homm3_stronghold_core_parity.py

Run from anywhere:
  python generate_homm3_stronghold_city.py
  python generate_homm3_stronghold_city.py --orphan-units-only   # only goblin_rogue remap + write Core.zip
  python generate_homm3_stronghold_city.py --m2-m10-building-presets-only   # only M2/M10 banlists+presets rows for homm3_stronghold_city

Then regenerate heroes (separate Core pass + Lang):
  python generate_homm3_stronghold_heroes.py
  python verify_homm3_stronghold_core_parity.py
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import zipfile
from pathlib import Path

CORE = Path(
    r"V:\Games\Olden Era Playtest Tweak\Heroes of Might & Magic Olden Era Playtest"
    r"\HeroesOE_Data\StreamingAssets\Core.zip"
)
PLAYTEST_ROOT = CORE.parents[2]

FRACTION_ID = "homm3_stronghold"
CITY_ID = "homm3_stronghold_city"
FRACTION_JSON_PATH = "DB/fractions/7_homm3_stronghold.json"
LAWS_JSON_PATH = "DB/fractions_laws/fractions_laws_table_homm3_stronghold.json"
CITY_JSON_PATH = f"DB/objects_logic/cities/{CITY_ID}.json"
UNITS_LOGIC_DIR = f"DB/units/units_logics/{FRACTION_ID}"
UNITS_VIEW_DIR = f"DB/units/units_views/{FRACTION_ID}"
STRONGHOLD_BUFFS_PATH = f"DB/buffs/units_buffs_{FRACTION_ID}.json"
CLAIM_DIRT_BIOME = False

LANG_ROOT = PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang"
ARGS_FACTION_LAWS_PATH = (
    PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "args" / "factionLaws.json"
)
ARGS_CITIES_PATH = (
    PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "args" / "cities.json"
)
ARGS_UNITS_ABILITY_PATH = (
    PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "args" / "unitsAbility.json"
)
ARGS_UNITS_BUFF_PATH = (
    PLAYTEST_ROOT / "HeroesOE_Data" / "StreamingAssets" / "Lang" / "args" / "unitsBuff.json"
)

# Dungeon tier bases -> HoMM3 Stronghold names (new unit SIDs).
BASE_TO_H3: dict[str, str] = {
    "trogl": "h3_goblin",
    "assassin": "h3_wolf_rider",
    "blade_dancer": "h3_orc",
    "minos": "h3_ogre",
    "medusa": "h3_roc",
    "hydra": "h3_cyclops",
    "black_dragon": "h3_behemoth",
}


def full_sid_map() -> dict[str, str]:
    m: dict[str, str] = {}
    for d_base, h3_base in BASE_TO_H3.items():
        for suf in ("", "_upg", "_upg_alt"):
            m[d_base + suf] = h3_base + suf
    return m


SID_MAP = full_sid_map()

# UnitView mesh/mapMesh values are runtime import keys, not vanilla donor prefab paths.
# Keeping both under a private namespace prevents vanilla Dungeon/Undead enemies from
# matching HoMM3 bundle swaps just because they share an original donor mesh. The runtime
# import table still carries real map shell donor paths so fog/sorting use native shells.
HOMM3_IMPORT_VIEW_ROOT = "homm3_import/stronghold"

# These units use different vanilla map shell donors from their cloned Dungeon tier so
# their native adventure-map shell matches the movement/placement family chosen for battle.
MAP_DONOR_OVERRIDES: dict[str, str] = {
    "h3_wolf_rider": "Undead/1Prefabs/pet_map",
    "h3_wolf_rider_upg": "Undead/1Prefabs/pet_upg_map",
    "h3_wolf_rider_upg_alt": "Undead/1Prefabs/pet_upg_alt_map",
}


# Moved after helper functions are defined — see UNIT_LOGIC_OVERRIDES_BUILD at bottom of file
UNIT_LOGIC_OVERRIDES: dict[str, dict] = {}


def single_attack_target_params() -> dict:
    return {
        "targetTags": ["unit", "attackable_object"],
        "castTarget_": "enemy",
        "targetCondition_": "alive",
        "selection": "object",
    }


def make_basic_melee_attack(stat_mult: float = 1.0, trigger_counter: bool = True) -> dict:
    damage_dealer = {
        "tags": ["melee_attack", "normal_damage", "basic_attack"],
        "triggerCounter": trigger_counter,
        "attackPatternSid": "attack_single_x100",
        "castTargetParams": single_attack_target_params(),
        "affectTargetParams": single_attack_target_params(),
        "damageTarget_": "enemy",
        "damageType_": "normal",
        "statDmgMult": stat_mult,
        "targetMechanics": [],
    }
    return {
        "attackType_": "melee",
        "selfMechanics": [],
        "damageDealer": damage_dealer,
    }


def make_ranged_default_attacks() -> list[dict]:
    damage_dealer = {
        "shootRange": -1,
        "shootThreshold": 4,
        "shootRedCount": 5,
        "shootDmgBuff": -0.1,
        "tags": ["shoot_attack", "normal_damage", "basic_attack"],
        "attackPatternSid": "attack_single_x100",
        "castTargetParams": single_attack_target_params(),
        "affectTargetParams": single_attack_target_params(),
        "damageTarget_": "enemy",
        "damageType_": "normal",
        "statDmgMult": 1.0,
        "targetMechanics": [],
    }
    return [{
        "attackType_": "shoot",
        "selfMechanics": [],
        "damageDealer": damage_dealer,
    }]


def make_ranged_alternative_attacks() -> list[dict]:
    melee = make_basic_melee_attack(stat_mult=0.5, trigger_counter=True)
    melee["dontUseEnergy"] = True
    melee["cd"] = -1
    return [melee]


def make_focus_return_strike(*, unit_sid: str, rank: int = 2, energy_level: int = 2,
                             cd: int = 1, stat_mult: float = 1.0) -> dict:
    """Build an active melee strike that returns to its starting hex after attacking."""
    attack = make_active_ability(
        attack_type="melee",
        rank=rank,
        energy_level=energy_level,
        action_cost=0,
        cd=cd,
        tags=[
            "ability",
            "melee_attack",
            "normal_damage",
            "armed_ability",
            f"armed_ability_{unit_sid}",
            "attack_and_return",
        ],
        attack_pattern_sid="attack_single_x100",
        cast_target="enemy",
        affect_target="enemy",
        stat_dmg_mult=stat_mult,
        trigger_counter=True,
    )
    attack["returnToStartAfterAttack"] = True
    return attack


def make_return_after_strike_alt(*, unit_sid: str, stat_mult: float = 1.0) -> dict:
    attack = make_active_ability(
        attack_type="melee",
        rank=1,
        cd=-1,
        dont_use_energy=True,
        tags=[
            "range_attack",
            "normal_damage",
            "basic_attack",
            "armed_ability",
            f"armed_ability_{unit_sid}",
        ],
        attack_pattern_sid="attack_single_x100",
        cast_target="enemy",
        affect_target="enemy",
        stat_dmg_mult=stat_mult,
        trigger_counter=True,
    )
    attack["returnToStartAfterAttack"] = True
    return attack


HOMM3_PROJECTILE_BY_UNIT_SID = {
    "h3_orc": "effects/projectiles/Blade_dancer_upg_hit_distance_projectile",
    "h3_orc_upg": "effects/projectiles/Blade_dancer_alt_hit_distance_projectile",
    "h3_cyclops": "effects/projectiles/Blade_dancer_upg_hit_distance_projectile",
    "h3_cyclops_upg": "effects/projectiles/Blade_dancer_alt_hit_distance_projectile",
    "h3_cyclops_upg_alt": "effects/projectiles/Blade_dancer_alt_hit_distance_projectile",
}

HOMM3_PROJECTILE_VIEW_BY_UNIT_SID = {
    "h3_orc": {"projectileSpeed": 35, "trajectory": "linear"},
    "h3_orc_upg": {"projectileSpeed": 35, "trajectory": "linear"},
    "h3_cyclops": {"projectileSpeed": 35, "trajectory": "linear"},
    "h3_cyclops_upg": {"projectileSpeed": 35, "trajectory": "linear"},
    "h3_cyclops_upg_alt": {"projectileSpeed": 35, "trajectory": "linear"},
}


def apply_homm3_projectile_view(view: dict, sid: str) -> None:
    projectile = HOMM3_PROJECTILE_BY_UNIT_SID.get(sid)
    if not projectile:
        return
    attacks = view.setdefault("defaultAttacks", [])
    if not isinstance(attacks, list):
        attacks = []
        view["defaultAttacks"] = attacks
    if not attacks:
        attacks.append({})
    attack = attacks[0]
    if not isinstance(attack, dict):
        attack = {}
        attacks[0] = attack
    attack["projectile"] = projectile
    attack.update(HOMM3_PROJECTILE_VIEW_BY_UNIT_SID.get(sid, {"projectileSpeed": 45, "trajectory": "linear"}))
    if attack.get("trajectory") != "Parabolic":
        attack.pop("maxHeight", None)


def view_config(name: str, description: str, **extra) -> dict:
    cfg = {
        "name": name,
        "description": description,
        "useExpandTooltip": "false",
    }
    cfg.update(extra)
    return cfg


# Vanilla icon keys used as donor art for custom HoMM3 Stronghold creature rows.
# The game already knows these keys, so generated unit-view configs can use them
# directly instead of relying on the runtime custom icon fallback.
STRONGHOLD_ABILITY_DONOR_ICONS: dict[str, str] = {
    "double_attack": "pet_blood_icon",
    "bloodlust": "magic_sharp_edge_effect_icon",
    "frenzied_charge": "minos_buff_icon",
    "return_after_strike": "assassin_buff_icon",
    "hamstring": "wasp_debuff_icon",
    "trap": "wasp_debuff_icon",
    "lightning_strike": "primal_1_magic_thunderbolt",
    "ferocity": "dragon_hunter_blood_icon",
    "no_distance_penalty": "crossbowman_buff_icon",
    "defense_reduction": "sub_skill_units_attackPen_icon",
}


def passive_view(name: str, description: str) -> dict:
    return view_config(name, description)


def base_attack_view_passives(kind: str, *, flyer: bool = False) -> list[dict]:
    if kind == "ranged":
        rows = [passive_view("base_passive_ranged_attack_name", "base_passive_ranged_attack_description")]
    elif kind == "ranged_no_range":
        rows = [passive_view("base_passive_ranged_attack_no_range_name", "base_passive_ranged_attack_no_range_description")]
    else:
        rows = [passive_view("base_passive_melee_attack_name", "base_passive_melee_attack_description")]
    if flyer:
        rows.append(passive_view("base_passive_flyer_name", "base_passive_flyer_description"))
    return rows


# === Ability builder helpers for Stronghold Green Match abilities ===

def make_active_ability(*, attack_type: str, rank: int = 1, energy_level: int = 0,
                       action_cost: int = 0, cd: int = -1, dont_use_energy: bool = False,
                       tags: list[str], attack_pattern_sid: str = "attack_single_x100",
                       cast_target: str = "enemy", stat_dmg_mult: float = 1.0,
                       damage_type: str = "normal", target_tags: list[str] | None = None,
                       shoot_range: int | None = None, shoot_threshold: int = 4,
                       shoot_red_count: int = 5, shoot_dmg_buff: float = -0.1,
                       self_mechanics: list[dict] | None = None,
                       target_mechanics: list[dict] | None = None,
                       trigger_counter: bool = False, no_counter: bool = False,
                       affect_target: str = "enemy", affect_selection: str = "object",
                       damage_target: str = "enemy",
                       extra: dict | None = None) -> dict:
    """Build an active ability with Focus Point (Energy) cost mechanics."""
    if target_tags is None:
        target_tags = ["unit", "attackable_object"]
    cast_params = {
        "targetTags": target_tags,
        "castTarget_": cast_target,
        "targetCondition_": "alive",
        "selection": "object",
    }
    affect_params = {
        "targetTags": target_tags,
        "castTarget_": affect_target,
        "targetCondition_": "alive",
        "selection": affect_selection,
    }
    dd = {
        "tags": tags,
        "triggerCounter": trigger_counter,
        "attackPatternSid": attack_pattern_sid,
        "castTargetParams": cast_params,
        "affectTargetParams": affect_params,
        "damageTarget_": damage_target,
        "damageType_": damage_type,
        "statDmgMult": stat_dmg_mult,
        "targetMechanics": target_mechanics or [],
    }
    if shoot_range is not None:
        dd["shootRange"] = shoot_range
        dd["shootThreshold"] = shoot_threshold
        dd["shootRedCount"] = shoot_red_count
        dd["shootDmgBuff"] = shoot_dmg_buff
    if no_counter:
        trigger_counter_tag = "no_counter"
        if trigger_counter_tag not in dd["tags"]:
            dd["tags"].append(trigger_counter_tag)

    ability: dict = {
        "attackType_": attack_type,
        "rank": rank,
        "selfMechanics": self_mechanics or [],
        "damageDealer": dd,
    }
    if cd != -1:
        ability["cd"] = cd
    if action_cost:
        ability["actionCost"] = action_cost
    if energy_level:
        ability["energyLevel"] = energy_level
    if dont_use_energy:
        ability["dontUseEnergy"] = True
    if extra:
        ability.update(extra)
    return ability


def make_active_magic_ability(*, rank: int = 1, energy_level: int = 1,
                              action_cost: int = 0, cd: int = 0,
                              tags: list[str], stat_dmg_mult: float = 1.0,
                              target_mechanics: list[dict] | None = None,
                              **kwargs) -> dict:
    """Build an active ability that deals Magic Damage."""
    full_tags = ["ability", "magic_attack", "ability_damage"] + tags
    return make_active_ability(
        attack_type="abilityCast",
        rank=rank,
        energy_level=energy_level,
        action_cost=action_cost,
        cd=cd,
        tags=full_tags,
        damage_type="magic",
        stat_dmg_mult=stat_dmg_mult,
        target_mechanics=target_mechanics,
        **kwargs,
    )


def make_active_buff_ability(*, rank: int = 1, energy_level: int = 1,
                             action_cost: int = 0, cd: int = 0,
                             tags: list[str], cast_target: str = "noself",
                             target_tags: list[str] | None = None,
                             self_mechanics: list[dict] | None = None,
                             target_mechanics: list[dict] | None = None,
                             affect_target: str = "noself",
                             **kwargs) -> dict:
    """Build an active buff ability targeting friendly units."""
    if target_tags is None:
        target_tags = ["unit"]
    full_tags = ["ability", "buff"] + tags
    return make_active_ability(
        attack_type="abilityCast",
        rank=rank,
        energy_level=energy_level,
        action_cost=action_cost,
        cd=cd,
        tags=full_tags,
        attack_pattern_sid="attack_single_buff",
        cast_target=cast_target,
        affect_target=affect_target,
        damage_target="none",
        target_tags=target_tags,
        self_mechanics=self_mechanics,
        target_mechanics=target_mechanics,
        **kwargs,
    )


def make_blink_ability(energy_level: int = 1, cd: int = 1,
                       tags: list[str] | None = None) -> dict:
    """Build a blink/teleport movement ability."""
    full_tags = ["ability", "movement_ability", "blink_ability"] + (tags or [])
    params = {
        "targetTags": [],
        "castTarget_": "none",
        "selection": "hex",
    }
    dd = {
        "tags": full_tags,
        "useSpeedAsShootRange": True,
        "triggerCounter": False,
        "attackPatternSid": "attack_single_buff",
        "castTargetParams": params,
        "affectTargetParams": {
            "targetTags": ["unit"],
            "castTarget_": "noself",
            "selection": "object",
        },
        "damageTarget_": "none",
        "targetMechanics": [],
    }
    return {
        "attackType_": "move",
        "moveType": "blink",
        "rank": 1,
        "selfMechanics": [],
        "cd": cd,
        "actionCost": 0,
        "energyLevel": energy_level,
        "damageDealer": dd,
    }


def make_melee_counterattack(stat_mult: float = 1.0) -> dict:
    """Build a counterattack definition matching OE patterns."""
    dd = {
        "tags": ["melee_attack", "normal_damage", "basic_attack", "counter_attack"],
        "triggerCounter": False,
        "attackPatternSid": "attack_single_x100",
        "castTargetParams": single_attack_target_params(),
        "affectTargetParams": single_attack_target_params(),
        "damageTarget_": "enemy",
        "damageType_": "normal",
        "statDmgMult": stat_mult,
        "targetMechanics": [],
    }
    return {
        "attackType_": "melee",
        "selfMechanics": [],
        "damageDealer": dd,
    }


def make_long_reach_alternative(stat_mult: float = 0.5, unit_sid: str = "",
                                target_mechanics: list[dict] | None = None,
                                no_counter: bool = True) -> dict:
    """Build a Long Reach alternative attack (like troglodyte armed_ability)."""
    tags = ["range_attack", "normal_damage", "basic_attack", "armed_ability"]
    if unit_sid:
        tags.append(f"armed_ability_{unit_sid}")
    dd = {
        "tags": tags,
        "triggerCounter": False,
        "attackPatternSid": "attack_single_x100",
        "castTargetParams": single_attack_target_params(),
        "affectTargetParams": single_attack_target_params(),
        "damageTarget_": "enemy",
        "damageType_": "normal",
        "statDmgMult": stat_mult,
        "targetMechanics": target_mechanics or [],
    }
    result = {
        "attackType_": "range",
        "rank": 1,
        "dontUseEnergy": True,
        "cd": -1,
        "selfMechanics": [],
        "damageDealer": dd,
    }
    if no_counter:
        dd["tags"].append("no_counter")
    return result


def make_whirlwind_attack(stat_mult: float = 1.0, unit_sid: str = "",
                          trigger_counter: bool = True) -> dict:
    """Build a Whirlwind Strike attack that hits all adjacent enemies."""
    tags = ["melee_attack", "normal_damage", "basic_attack", "armed_ability"]
    if unit_sid:
        tags.append(f"armed_ability_{unit_sid}")
    dd = {
        "tags": tags,
        "triggerCounter": trigger_counter,
        "attackPatternSid": "attack_swirl_x1_x100",
        "castTargetParams": single_attack_target_params(),
        "affectTargetParams": single_attack_target_params(),
        "damageTarget_": "enemy",
        "damageType_": "normal",
        "statDmgMult": stat_mult,
        "targetMechanics": [],
    }
    return {
        "attackType_": "melee",
        "rank": 1,
        "dontUseEnergy": True,
        "cd": -1,
        "selfMechanics": [],
        "damageDealer": dd,
    }


def make_poison_mechanics(damage_per_turn: float, duration: int) -> list[dict]:
    """Apply a poison DoT via targetMechanics (start-of-turn Magic Damage)."""
    return [{
        "type": "startTurnDamage",
        "damageType_": "magic",
        "level": damage_per_turn,
        "duration": duration,
        "stackable": True,
    }]


def make_debuff_mechanic(stat: str, value: float, duration: int = 1) -> dict:
    """Apply a stat debuff to target."""
    return {
        "type": "modifyStat",
        "stat": stat,
        "value": value,
        "duration": duration,
    }


def make_hamstring_ability(*, unit_sid: str, buff_sid: str, stat_dmg_mult: float = 0.5) -> dict:
    """Build a committing ranged attack that applies the custom Hamstring debuff."""
    return make_active_ability(
        attack_type="shoot",
        rank=1,
        energy_level=1,
        cd=1,
        tags=["normal_damage", "ability", "debuff_ability", "armed_ability", f"armed_ability_{unit_sid}", "hamstring"],
        stat_dmg_mult=stat_dmg_mult,
        shoot_range=-1,
        extra={
            "damageDealer": {
                "shootRange": -1,
                "shootThreshold": 4,
                "shootRedCount": 5,
                "shootDmgBuff": -0.1,
                "tags": ["normal_damage", "ability", "debuff_ability", "armed_ability", f"armed_ability_{unit_sid}", "hamstring"],
                "triggerCounter": False,
                "attackPatternSid": "attack_single_x100",
                "castTargetParams": single_attack_target_params(),
                "affectTargetParams": single_attack_target_params(),
                "damageTarget_": "enemy",
                "damageType_": "normal",
                "statDmgMult": stat_dmg_mult,
                "buffTarget_": "enemy",
                "buff": {"sid": buff_sid, "duration": 1},
                "targetMechanics": [],
            }
        },
    )


def make_boar_rider_charge_ability() -> dict:
    """Build a committing melee attack that applies the Boar Rider Charge debuff."""
    return make_active_ability(
        attack_type="melee",
        rank=1,
        energy_level=1,
        cd=1,
        tags=[
            "melee_attack",
            "normal_damage",
            "ability",
            "debuff_ability",
            "armed_ability",
            "armed_ability_h3_wolf_rider_upg_alt",
            "charge",
        ],
        trigger_counter=True,
        stat_dmg_mult=1.0,
        extra={
            "damageDealer": {
                "tags": [
                    "melee_attack",
                    "normal_damage",
                    "ability",
                    "debuff_ability",
                    "armed_ability",
                    "armed_ability_h3_wolf_rider_upg_alt",
                    "charge",
                ],
                "triggerCounter": True,
                "attackPatternSid": "attack_single_x100",
                "castTargetParams": single_attack_target_params(),
                "affectTargetParams": single_attack_target_params(),
                "damageTarget_": "enemy",
                "damageType_": "normal",
                "statDmgMult": 1.0,
                "buffTarget_": "enemy",
                "buff": {"sid": "h3_wolf_rider_upg_alt_charge_debuff", "duration": 1},
                "targetMechanics": [],
            }
        },
    )


def make_goblin_trap_ability() -> dict:
    """Build a hex-target unit ability that spawns an existing native trap object."""
    return {
        "attackType_": "cast",
        "rank": 1,
        "selfMechanics": [],
        "cd": 1,
        "energyLevel": 1,
        "damageDealer": {
            "tags": ["ability", "trap_ability"],
            "triggerCounter": False,
            "castTargetParams": {
                "targetTags": [],
                "castTarget_": "all",
                "selection": "hex",
            },
            "affectTargetParams": {
                "targetTags": [],
                "castTarget_": "all",
                "selection": "hex",
            },
            "attackPatternSid": "attack_single_x100",
            "damageTarget_": "none",
            "damageType_": "none",
            "targetMechanics": [{
                "mech": "spawn_object",
                "values": [
                    "trap",
                    "magic_space_trap_snare_summon",
                    "1",
                    "7",
                    "1",
                    "true",
                ],
            }],
        },
    }


def passive_double_melee_strike() -> dict:
    return {"data": {"sequenceEffect": "add_attack_after_counter_melee"}}


def passive_armor_penetration(percent: float) -> dict:
    return {"data": {"stats": {"armorPen": percent}}}


def remove_ranged_distance_penalty(unit: dict) -> None:
    for attack in unit.get("defaultAttacks", []) or []:
        damage_dealer = attack.get("damageDealer")
        if isinstance(damage_dealer, dict) and attack.get("attackType_") == "shoot":
            damage_dealer["shootDmgBuff"] = -0.0


def make_unit_buff_ability(*, buff_sid: str, rank: int, energy_level: int, cd: int,
                           cast_target: str, buff_target: str, duration: int = 2) -> dict:
    return {
        "attackType_": "cast",
        "rank": rank,
        "selfMechanics": [],
        "cd": cd,
        "actionCost": 0,
        "energyLevel": energy_level,
        "damageDealer": {
            "instacast": True,
            "multitargetType": "simultaneous",
            "tags": ["ability", "buff_ability"],
            "triggerCounter": False,
            "attackPatternSid": "attack_single_buff",
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
            "damageTarget_": "none",
            "buffTarget_": buff_target,
            "buff": {"sid": buff_sid, "duration": duration},
            "targetMechanics": [],
        },
    }


STRONGHOLD_UNIT_BUFFS: list[dict] = [
    {
        "id": "h3_wolf_rider_upg_alt_charge_debuff",
        "aiValue": 3000,
        "aiValuePerDuration": 300,
        "icon": STRONGHOLD_ABILITY_DONOR_ICONS["frenzied_charge"],
        "name_": "h3_wolf_rider_upg_alt_charge_debuff_name",
        "description_": "h3_wolf_rider_upg_alt_charge_debuff_description",
        "tags": ["negative"],
        "isPositive": False,
        "addition": "duration",
        "data": {"stats": {"luck": -5}},
    },
    {
        "id": "h3_orc_hamstring_debuff",
        "aiValue": 2500,
        "aiValuePerDuration": 250,
        "icon": STRONGHOLD_ABILITY_DONOR_ICONS["hamstring"],
        "name_": "h3_orc_hamstring_debuff_name",
        "description_": "h3_orc_hamstring_debuff_description",
        "tags": ["negative"],
        "isPositive": False,
        "addition": "duration",
        "data": {"stats": {"speed": -2}},
    },
    {
        "id": "h3_orc_upg_hamstring_debuff",
        "aiValue": 3500,
        "aiValuePerDuration": 350,
        "icon": STRONGHOLD_ABILITY_DONOR_ICONS["hamstring"],
        "name_": "h3_orc_upg_hamstring_debuff_name",
        "description_": "h3_orc_upg_hamstring_debuff_description",
        "tags": ["negative"],
        "isPositive": False,
        "addition": "duration",
        "data": {"stats": {"speed": -3}},
    },
    {
        "id": "h3_ogre_upg_bloodlust",
        "aiValue": 5560,
        "aiValuePerDuration": 556,
        "icon": "blade_dancer_buff_icon",
        "name_": "h3_ogre_upg_ability_1_name",
        "description_": "h3_ogre_upg_bloodlust_description",
        "tags": ["positive"],
        "isPositive": True,
        "addition": "duration",
        "data": {"stats": {"offence": 6}},
    },
]


def patch_stronghold_unit_buffs(all_data: dict[str, bytes]) -> None:
    all_data[STRONGHOLD_BUFFS_PATH] = json.dumps(
        {"array": copy.deepcopy(STRONGHOLD_UNIT_BUFFS)},
        ensure_ascii=False,
        indent="\t",
    ).encode("utf-8")


# === Populate UNIT_LOGIC_OVERRIDES after all helpers are defined ===
# SAFE PATTERNS ONLY — verified against vanilla Dungeon donor schemas.
# Each unit receives ONLY what its Dungeon donor already has working.
UNIT_LOGIC_OVERRIDES.update({
    # ====================
    # Tier 1 — Goblin / Hobgoblin / Goblin Trapper.
    # HoMM3 Goblin/Hobgoblin have no specials. ToA Goblin Trapper casts Land Mine;
    # OE has a native trap-spawn mechanic, so the alt upgrade gets a 1-Focus snare trap.
    # ====================
    "h3_goblin": {
        "squadValue": 60, "expBonus": 5,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 40}]},
        "stats": {"hp": 5, "offence": 4, "defence": 2, "damageMin": 1, "damageMax": 2, "initiative": 5, "speed": 5, "luck": 0},
        "alternativeAttacks": [], "abilities": [], "passives": [],
    },
    "h3_goblin_upg": {
        "squadValue": 90, "expBonus": 5,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 50}]},
        "stats": {"hp": 5, "offence": 6, "defence": 3, "damageMin": 1, "damageMax": 2, "initiative": 7, "speed": 7, "luck": 0, "numCounters": 2},
        "alternativeAttacks": [], "abilities": [], "passives": [],
    },
    "h3_goblin_upg_alt": {
        "squadValue": 85, "expBonus": 5,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 60}]},
        "stats": {"hp": 5, "offence": 4, "defence": 4, "damageMin": 1, "damageMax": 2, "initiative": 7, "speed": 7, "luck": 0, "numCounters": 1},
        "alternativeAttacks": [], "abilities": [make_goblin_trap_ability()], "passives": [],
    },

    # ====================
    # Tier 2 — Wolf Rider / Wolf Raider / Boar Rider.
    # Wolf Raider double attack is implemented through the native extra-strike passive.
    # Boar Rider gets a simple Charge analogue until true distance-scaling jousting is mapped.
    # ====================
    "h3_wolf_rider": {
        "squadValue": 130, "expBonus": 10,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 100}]},
        "stats": {"hp": 10, "offence": 7, "defence": 5, "damageMin": 2, "damageMax": 4, "initiative": 6, "speed": 6, "luck": 0},
        "alternativeAttacks": [], "abilities": [], "passives": [],
    },
    "h3_wolf_rider_upg": {
        "squadValue": 203, "expBonus": 12,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 140}]},
        "stats": {"hp": 10, "offence": 8, "defence": 5, "damageMin": 3, "damageMax": 4, "initiative": 8, "speed": 8, "luck": 0},
        "alternativeAttacks": [], "abilities": [], "passives": [passive_double_melee_strike()],
    },
    "h3_wolf_rider_upg_alt": {
        "squadValue": 203, "expBonus": 12,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 140}]},
        "stats": {"hp": 15, "offence": 9, "defence": 5, "damageMin": 3, "damageMax": 5, "initiative": 7, "speed": 7, "luck": 0},
        "alternativeAttacks": [], "abilities": [make_boar_rider_charge_ability()], "passives": [],
    },

    # ====================
    # Tier 3 — Orc / Orc Chieftain / Orc Berserker.
    # ====================
    "h3_orc": {
        "ai": "range_type", "squadValue": 192, "expBonus": 15,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 150}]},
        "stats": {"hp": 15, "offence": 8, "defence": 4, "damageMin": 2, "damageMax": 5, "initiative": 4, "speed": 4, "luck": 0},
        "attackProfile": "ranged", "passives": [], "abilities": [make_hamstring_ability(
            unit_sid="h3_orc",
            buff_sid="h3_orc_hamstring_debuff",
            stat_dmg_mult=0.5,
        )],
    },
    "h3_orc_upg": {
        "ai": "range_type", "squadValue": 240, "expBonus": 20,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 165}]},
        "stats": {"hp": 20, "offence": 8, "defence": 4, "damageMin": 2, "damageMax": 5, "initiative": 5, "speed": 5, "luck": 0},
        "attackProfile": "ranged", "passives": [], "abilities": [make_hamstring_ability(
            unit_sid="h3_orc_upg",
            buff_sid="h3_orc_upg_hamstring_debuff",
            stat_dmg_mult=1.0,
        )],
    },
    "h3_orc_upg_alt": {
        "ai": "melee_type", "squadValue": 300, "expBonus": 20,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 180}]},
        "stats": {"hp": 20, "offence": 8, "defence": 8, "damageMin": 2, "damageMax": 5, "initiative": 7, "speed": 7, "luck": 0},
        "attackProfile": "melee", "passives": [], "abilities": [],
        "alternativeAttacks": [make_return_after_strike_alt(unit_sid="h3_orc_upg_alt")],
    },

    # ====================
    # Tier 4 — Ogre / Ogre Mage / Ogre Brute.
    # ====================
    "h3_ogre": {
        "squadValue": 416, "expBonus": 40,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 300}]},
        "stats": {"hp": 40, "offence": 13, "defence": 7, "damageMin": 6, "damageMax": 12, "initiative": 4, "speed": 4, "luck": 0},
        "alternativeAttacks": [], "abilities": [], "passives": [],
    },
    "h3_ogre_upg": {
        "squadValue": 672, "expBonus": 60,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 400}]},
        "stats": {"hp": 60, "offence": 13, "defence": 7, "damageMin": 6, "damageMax": 12, "initiative": 5, "speed": 5, "luck": 0},
        "alternativeAttacks": [], "passives": [],
        "abilities": [make_unit_buff_ability(
            buff_sid="h3_ogre_upg_bloodlust",
            rank=2,
            energy_level=2,
            cd=2,
            cast_target="ally",
            buff_target="ally",
            duration=2,
        )],
    },
    "h3_ogre_upg_alt": {
        "squadValue": 700, "expBonus": 60,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 400}]},
        "stats": {"hp": 50, "offence": 15, "defence": 8, "damageMin": 6, "damageMax": 12, "initiative": 7, "speed": 7, "luck": 0},
        "alternativeAttacks": [], "passives": [],
        "abilities": [make_focus_return_strike(unit_sid="h3_ogre_upg_alt")],
    },

    # ====================
    # Tier 5 — Roc / Thunderbird / Shahrokh.
    # Roc flies. Thunderbird has HoMM3 Lightning Strike. ToA Shahrokh flies and
    # has Ferocity; no safe data-only Ferocity mapping is applied here.
    # ====================
    "h3_roc": {
        "squadValue": 1027, "expBonus": 60,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 600}]},
        "stats": {"hp": 60, "offence": 13, "defence": 11, "damageMin": 11, "damageMax": 15, "initiative": 7, "speed": 7, "luck": 0, "moveType": "fly"},
        "attackProfile": "melee", "alternativeAttacks": [],
        "abilities": [], "passives": [],
    },
    "h3_roc_upg": {
        "squadValue": 1106, "expBonus": 60,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 700}]},
        "stats": {"hp": 60, "offence": 13, "defence": 11, "damageMin": 11, "damageMax": 15, "initiative": 11, "speed": 11, "luck": 0, "moveType": "fly"},
        "attackProfile": "melee", "alternativeAttacks": [],
        "passives": [],
        "abilities": [
            # Lightning Strike: melee ability dealing Normal Damage with +20% power (engine rejects melee+magic)
            {
                "attackType_": "melee", "rank": 2, "selfMechanics": [],
                "cd": 2, "actionCost": 0, "energyLevel": 2,
                "damageDealer": {
                    "tags": ["ability", "armed_ability_h3_roc", "lightning_strike", "dragon_immunities", "embodiment_immunities"],
                    "triggerCounter": False,
                    "attackPatternSid": "attack_single_x100",
                    "castTargetParams": {"targetTags": ["unit"], "castTarget_": "enemy", "targetCondition_": "alive", "selection": "object"},
                    "affectTargetParams": {"targetTags": ["unit"], "castTarget_": "enemy", "targetCondition_": "alive", "selection": "object"},
                    "damageTarget_": "enemy", "damageType_": "normal", "statDmgMult": 1.2,
                    "targetMechanics": [],
                },
            },
        ],
    },
    "h3_roc_upg_alt": {
        "squadValue": 1150, "expBonus": 60,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 700}]},
        "stats": {"hp": 50, "offence": 16, "defence": 10, "damageMin": 10, "damageMax": 15, "initiative": 10, "speed": 10, "luck": 0, "moveType": "fly"},
        "attackProfile": "melee", "alternativeAttacks": [],
        "abilities": [], "passives": [passive_double_melee_strike()],
    },

    # ====================
    # Tier 6 — Cyclops / Cyclops King / Blood-Eyed Cyclops.
    # Keep shooter behavior. Siege-wall and no-range/no-wall-penalty mechanics are
    # not safely mapped as data-only OE unit abilities yet.
    # ====================
    "h3_cyclops": {
        "ai": "range_type", "squadValue": 1266, "expBonus": 70,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 750}]},
        "stats": {"hp": 70, "offence": 15, "defence": 12, "damageMin": 16, "damageMax": 20, "initiative": 6, "speed": 6, "luck": 0},
        "attackProfile": "ranged",
        "passives": [], "abilities": [],
    },
    "h3_cyclops_upg": {
        "ai": "range_type", "squadValue": 1443, "expBonus": 70,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 1100}]},
        "stats": {"hp": 70, "offence": 17, "defence": 13, "damageMin": 16, "damageMax": 20, "initiative": 8, "speed": 8, "luck": 0},
        "attackProfile": "ranged",
        "passives": [], "abilities": [],
    },
    "h3_cyclops_upg_alt": {
        "ai": "range_type", "squadValue": 1544, "expBonus": 70,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 1000}]},
        "stats": {"hp": 70, "offence": 16, "defence": 14, "damageMin": 16, "damageMax": 20, "initiative": 7, "speed": 7, "luck": 0},
        "attackProfile": "ranged",
        "passives": [], "abilities": [],
        "_builders": [lambda u, sid: remove_ranged_distance_penalty(u)],
    },

    # ====================
    # Tier 7 — Behemoth / Ancient Behemoth / Ghost Behemoth.
    # HoMM3/ToA defense reduction still needs a real mechanic mapping; do not
    # advertise Black Dragon donor abilities as Behemoth abilities.
    # ====================
    "h3_behemoth": {
        "squadValue": 3162, "expBonus": 160,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 1500}]},
        "stats": {"hp": 160, "offence": 17, "defence": 17, "damageMin": 30, "damageMax": 50, "initiative": 6, "speed": 6, "luck": 0},
        "statsRemove": ["moveType"],
        "alternativeAttacks": [], "abilities": [], "passives": [passive_armor_penetration(0.4)],
    },
    "h3_behemoth_upg": {
        "squadValue": 6168, "expBonus": 300,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 3000}, {"name": "crystal", "cost": 1}]},
        "stats": {"hp": 300, "offence": 19, "defence": 19, "damageMin": 30, "damageMax": 50, "initiative": 9, "speed": 9, "luck": 0},
        "statsRemove": ["moveType"],
        "alternativeAttacks": [], "abilities": [], "passives": [passive_armor_penetration(0.8)],
    },
    "h3_behemoth_upg_alt": {
        "squadValue": 6250, "expBonus": 300,
        "unitCost": {"costResArray": [{"name": "gold", "cost": 3000}, {"name": "crystal", "cost": 2}]},
        "stats": {"hp": 240, "offence": 22, "defence": 18, "damageMin": 30, "damageMax": 50, "initiative": 11, "speed": 11, "luck": 0, "moveType": "fly"},
        "alternativeAttacks": [], "abilities": [], "passives": [passive_armor_penetration(0.6)],
    },
})


def morph_unit_logic(data: dict, new_sid: str) -> None:
    a = data["array"][0]
    a["id"] = new_sid
    a["fraction"] = FRACTION_ID
    usid = a.get("upgradeSid")
    if isinstance(usid, str) and usid in SID_MAP:
        a["upgradeSid"] = SID_MAP[usid]
    tags = a.get("tags")
    if isinstance(tags, list):
        a["tags"] = [FRACTION_ID if t == "dungeon" else t for t in tags]
    apply_unit_logic_override(a, new_sid)


def apply_unit_logic_override(unit: dict, new_sid: str) -> None:
    override = UNIT_LOGIC_OVERRIDES.get(new_sid)
    if not override:
        return
    builders = override.get("_builders")

    for key, value in override.items():
        if key == "_builders":
            continue
        if key == "stats":
            stats = unit.setdefault("stats", {})
            if isinstance(stats, dict):
                stats.update(copy.deepcopy(value))
                if "moveType" not in value:
                    stats.pop("moveType", None)
            continue
        if key == "statsRemove":
            stats = unit.setdefault("stats", {})
            if isinstance(stats, dict):
                for stat_key in value:
                    stats.pop(stat_key, None)
            continue
        if key == "attackProfile":
            if value == "ranged":
                unit["ai"] = "range_type"
                unit["defaultAttacks"] = make_ranged_default_attacks()
                unit["alternativeAttacks"] = make_ranged_alternative_attacks()
            elif value == "melee":
                unit["ai"] = "melee_type"
                unit["defaultAttacks"] = [make_basic_melee_attack()]
                unit["alternativeAttacks"] = []
            continue
        if key == "passivesAppend":
            passives = unit.setdefault("passives", [])
            if isinstance(passives, list) and isinstance(value, list):
                passives.extend(copy.deepcopy(value))
            continue
        unit[key] = copy.deepcopy(value)

    # Builders run after structural overrides so attackProfile-generated arrays can
    # be amended without being overwritten by the ranged/melee profile helpers.
    if isinstance(builders, list):
        for fn in builders:
            fn(unit, new_sid)


def morph_unit_view(data: dict, new_sid: str) -> None:
    a = data["array"][0]
    a["id"] = new_sid
    # Dungeon donor view scales range from tiny decimals to 40+ because they were authored
    # for very different prefab hierarchies. HoMM3 billboard bundles carry their own quad
    # size, so keep the view root scale neutral. Mesh paths below are synthetic import
    # triggers; real native shell donors live in homm3_import.json as mapShellResPath.
    a["scale"] = 1
    a["mesh"] = f"{HOMM3_IMPORT_VIEW_ROOT}/{new_sid}"
    a["mapMesh"] = f"{HOMM3_IMPORT_VIEW_ROOT}/{new_sid}_map"
    apply_unit_view_override(a, new_sid)


def apply_unit_view_override(view: dict, new_sid: str) -> None:
    """Keep visible ability/passive circles aligned with custom h3_* logic arrays.

    The game draws unit-window and hire-screen circles from UnitViewConfig. If
    logic arrays are longer than view arrays, the engine creates empty stubs;
    those stubs have no name/description and hover as blank circles.
    """
    base = base_h3_sid(new_sid)
    if not base:
        return

    for key in ("passives", "alternativeAttacks", "abilities", "baseClass", "magicClass"):
        remap_view_token_sids(view.get(key), new_sid)

    is_flyer = base == "h3_roc" or new_sid == "h3_behemoth_upg_alt"
    attack_kind = "ranged" if base in ("h3_orc", "h3_cyclops") else "melee"
    if new_sid == "h3_orc_upg_alt":
        attack_kind = "melee"
    view["passives"] = base_attack_view_passives(attack_kind, flyer=is_flyer)

    if base == "h3_goblin":
        view["alternativeAttacks"] = []
        view["abilities"] = []
        if new_sid == "h3_goblin_upg":
            view["passives"].append(passive_view(
                "base_passive_aware_1_name",
                "base_passive_aware_1_description",
            ))
        if new_sid == "h3_goblin_upg_alt":
            view["abilities"].append(view_config(
                "h3_goblin_ability_2_name",
                "h3_goblin_ability_2_description",
                abilityType="Ability_type_debuff",
                animationIndex=2,
                icon=STRONGHOLD_ABILITY_DONOR_ICONS["trap"],
            ))
    elif base in ("h3_wolf_rider", "h3_ogre"):
        view["alternativeAttacks"] = []
        view["abilities"] = []
        if new_sid == "h3_wolf_rider_upg":
            view["passives"].append(view_config(
                f"{new_sid}_passive_1_name",
                f"{new_sid}_passive_1_description",
                icon=STRONGHOLD_ABILITY_DONOR_ICONS["double_attack"],
            ))
        elif new_sid == "h3_wolf_rider_upg_alt":
            view["abilities"].append(view_config(
                f"{new_sid}_ability_1_name",
                f"{new_sid}_ability_1_description",
                abilityType="Ability_type_debuff",
                animationIndex=1,
                icon=STRONGHOLD_ABILITY_DONOR_ICONS["frenzied_charge"],
            ))
        elif new_sid == "h3_ogre_upg":
            view["abilities"].append(view_config(
                f"{new_sid}_ability_1_name",
                f"{new_sid}_ability_1_description",
                abilityType="Ability_type_buff",
                infoDescription="ability_no_turn",
                animationIndex=2,
                icon=STRONGHOLD_ABILITY_DONOR_ICONS["bloodlust"],
            ))
        elif new_sid == "h3_ogre_upg_alt":
            view["abilities"].append(view_config(
                f"{new_sid}_ability_1_name",
                f"{new_sid}_ability_1_description",
                abilityType="Ability_type_attack",
                infoDescription="ability_no_turn",
                animationIndex=2,
                icon=STRONGHOLD_ABILITY_DONOR_ICONS["frenzied_charge"],
            ))
    elif base == "h3_orc":
        view["alternativeAttacks"] = []
        view["abilities"] = []
        if new_sid != "h3_orc_upg_alt":
            apply_homm3_projectile_view(view, new_sid)
            view["alternativeAttacks"] = [view_config(
                "common_attack_1_name",
                "common_attack_1_description",
                abilityType="Ability_type_attack_alt",
                infoDescription="ability_no_energy",
                animationIndex=1,
            )]
            if new_sid in ("h3_orc", "h3_orc_upg"):
                name_prefix = "h3_orc_upg" if new_sid == "h3_orc_upg" else "h3_orc"
                hamstring_view = view_config(
                    f"{name_prefix}_hamstring_name",
                    f"{name_prefix}_hamstring_description",
                    abilityType="Ability_type_debuff",
                    animationIndex=0,
                    icon=STRONGHOLD_ABILITY_DONOR_ICONS["hamstring"],
                )
                projectile = HOMM3_PROJECTILE_BY_UNIT_SID.get(new_sid)
                if projectile:
                    hamstring_view["projectile"] = projectile
                    hamstring_view.update(HOMM3_PROJECTILE_VIEW_BY_UNIT_SID.get(new_sid, {"projectileSpeed": 45, "trajectory": "linear"}))
                view["abilities"].append(hamstring_view)
        else:
            view["defaultAttacks"] = [{"animationIndex": 0}]
            view["alternativeAttacks"] = [view_config(
                f"{new_sid}_ability_1_name",
                f"{new_sid}_ability_1_description",
                abilityType="Ability_type_attack_alt",
                infoDescription="ability_no_energy",
                animationIndex=1,
                canShowOnUI=True,
                icon=STRONGHOLD_ABILITY_DONOR_ICONS["return_after_strike"],
            )]
    elif base == "h3_roc":
        view["alternativeAttacks"] = []
        view["abilities"] = []
        if new_sid == "h3_roc_upg":
            view["abilities"].append(view_config(
                f"{new_sid}_ability_1_name",
                f"{new_sid}_ability_1_description",
                abilityType="Ability_type_damage",
                infoDescription="ability_no_turn",
                animationIndex=3,
                icon=STRONGHOLD_ABILITY_DONOR_ICONS["lightning_strike"],
            ))
        elif new_sid == "h3_roc_upg_alt":
            view["passives"].append(view_config(
                f"{new_sid}_passive_1_name",
                f"{new_sid}_passive_1_description",
                icon=STRONGHOLD_ABILITY_DONOR_ICONS["ferocity"],
            ))
    elif base == "h3_cyclops":
        apply_homm3_projectile_view(view, new_sid)
        if new_sid == "h3_cyclops_upg_alt":
            view["passives"] = base_attack_view_passives("ranged_no_range")
        view["alternativeAttacks"] = [view_config(
            "common_attack_1_name",
            "common_attack_1_description",
            abilityType="Ability_type_attack_alt",
            infoDescription="ability_no_energy",
            animationIndex=1,
        )]
        view["abilities"] = []
        if new_sid == "h3_cyclops_upg_alt":
            view["passives"].append(view_config(
                f"{new_sid}_passive_1_name",
                f"{new_sid}_passive_1_description",
                icon=STRONGHOLD_ABILITY_DONOR_ICONS["no_distance_penalty"],
            ))
    elif base == "h3_behemoth":
        view["alternativeAttacks"] = []
        view["abilities"] = []
        view["passives"].append(view_config(
            f"{new_sid}_passive_1_name",
            f"{new_sid}_passive_1_description",
            icon=STRONGHOLD_ABILITY_DONOR_ICONS["defense_reduction"],
        ))


def base_h3_sid(sid: str) -> str | None:
    for base in BASE_TO_H3.values():
        if sid == base or sid == base + "_upg" or sid == base + "_upg_alt":
            return base
    return None


def remap_view_token_sids(value, new_sid: str) -> None:
    """Rewrite donor token references where a direct SID_MAP replacement exists."""
    if isinstance(value, list):
        for item in value:
            remap_view_token_sids(item, new_sid)
        return
    if not isinstance(value, dict):
        return
    for key, old_value in list(value.items()):
        if isinstance(old_value, str):
            value[key] = remap_token_sid(old_value, new_sid)
        elif isinstance(old_value, (dict, list)):
            remap_view_token_sids(old_value, new_sid)


def remap_token_sid(token_sid: str, new_sid: str) -> str:
    for donor_sid, h3_sid in sorted(SID_MAP.items(), key=lambda kv: len(kv[0]), reverse=True):
        if h3_sid != new_sid:
            continue
        if token_sid == donor_sid or token_sid.startswith(donor_sid + "_"):
            return h3_sid + token_sid[len(donor_sid):]
    return token_sid


def copy_all_units(all_data: dict) -> None:
    for old_sid, new_sid in SID_MAP.items():
        l_path = f"DB/units/units_logics/dungeon/{old_sid}_l.json"
        v_path = f"DB/units/units_views/dungeon/{old_sid}_v.json"
        logic = json.loads(all_data[l_path].decode("utf-8-sig"))
        view = json.loads(all_data[v_path].decode("utf-8-sig"))
        morph_unit_logic(logic, new_sid)
        morph_unit_view(view, new_sid)
        all_data[f"{UNITS_LOGIC_DIR}/{new_sid}_l.json"] = json.dumps(
            logic, ensure_ascii=False, indent="\t"
        ).encode("utf-8")
        all_data[f"{UNITS_VIEW_DIR}/{new_sid}_v.json"] = json.dumps(
            view, ensure_ascii=False, indent="\t"
        ).encode("utf-8")


def write_core_zip(entries: dict[str, zipfile.ZipInfo], all_data: dict[str, bytes]) -> None:
    tmp = CORE.with_name(CORE.name + ".tmp")
    if tmp.exists():
        tmp.unlink()
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for name, blob in sorted(all_data.items()):
            zi = entries.get(name)
            if zi is not None:
                zout.writestr(zi, blob)
            else:
                zout.writestr(name, blob)
    tmp.replace(CORE)


def patch_city_hires(city: dict) -> None:
    for hire in city.get("hires") or []:
        uh = hire.get("unitsHire")
        if not uh or not isinstance(uh.get("units"), list):
            continue
        for block in uh["units"]:
            sids = block.get("sids")
            if not isinstance(sids, list):
                continue
            block["sids"] = [SID_MAP.get(s, s) for s in sids]


def morph_city_strings(city: dict) -> None:
    """Replace Dungeon_* UI keys with Homm3Stronghold_* for English patching."""

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("names", "descriptions", "narrativeDescriptions") and isinstance(v, list):
                    obj[k] = [
                        (
                            s.replace("Dungeon_", "Homm3Stronghold_").replace("dungeon_city", CITY_ID)
                            if isinstance(s, str)
                            else s
                        )
                        for s in v
                    ]
                else:
                    walk(v)
        elif isinstance(obj, list):
            for it in obj:
                walk(it)

    walk(city)


RESOURCE_SID_MAP = {
    "gold": "gold",
    "wood": "wood",
    "ore": "ore",
    "mercury": "mercury",
    # Olden Era has no sulfur resource. Fold HoMM3 sulfur into mercury.
    "sulfur": "mercury",
    "crystal": "crystals",
    "gems": "gemstones",
    "dust": "dust",
}


def homm3_costs(**resources: int) -> list[dict]:
    folded: dict[str, int] = {}
    for h3_name, amount in resources.items():
        if not amount:
            continue
        oe_name = RESOURCE_SID_MAP[h3_name]
        folded[oe_name] = folded.get(oe_name, 0) + amount
    return [{"name": name, "cost": folded[name]} for name in ("gold", "wood", "ore", "mercury", "crystals", "gemstones", "dust") if name in folded]


def prev_buildings(*requirements: tuple[str, int]) -> list[dict]:
    return [{"sid": sid, "level": level} for sid, level in requirements]


HOMM3_STRONGHOLD_HIRE_TREE: dict[str, list[dict]] = {
    # HoMM3 Complete / SoD Stronghold creature dwellings. Costs use Olden Era
    # resource ids; HoMM3 sulfur, if present, is folded into mercury above.
    # Upgrade levels also keep OE's standard alchemical dust tier ladder:
    # T1..T7 = 10, 20, 30, 40, 50, 75, 100.
    "Build_Tier_1": [
        {
            "prevBuildings": prev_buildings(),
            "costs": homm3_costs(gold=200, wood=5, ore=5),
        },
        {
            "prevBuildings": prev_buildings(("Build_Tier_1", 1)),
            "costs": homm3_costs(gold=1000, wood=5, ore=5, dust=10),
        },
    ],
    "Build_Tier_2": [
        {
            "prevBuildings": prev_buildings(("Build_Tier_1", 1)),
            "costs": homm3_costs(gold=1000, wood=10, ore=5),
        },
        {
            "prevBuildings": prev_buildings(("Build_Tier_2", 1)),
            "costs": homm3_costs(gold=1000, wood=5, ore=5, dust=20),
        },
    ],
    "Build_Tier_3": [
        {
            "prevBuildings": prev_buildings(("Build_Tier_1", 1)),
            "costs": homm3_costs(gold=1000, wood=5, ore=5),
        },
        {
            # HoMM3 also requires the Blacksmith. Olden Era has no blacksmith
            # building SID in city configs, so keep the enforceable dwelling edge.
            "prevBuildings": prev_buildings(("Build_Tier_3", 1)),
            "costs": homm3_costs(gold=1000, wood=2, ore=2, dust=30),
        },
    ],
    "Build_Tier_4": [
        {
            "prevBuildings": prev_buildings(("Build_Tier_3", 1)),
            "costs": homm3_costs(gold=2000, wood=20),
        },
        {
            "prevBuildings": prev_buildings(("Build_Tier_4", 1), ("Build_Magic_Guild", 1)),
            "costs": homm3_costs(gold=2000, wood=5, ore=5, gems=5, dust=40),
        },
    ],
    "Build_Tier_5": [
        {
            "prevBuildings": prev_buildings(("Build_Tier_2", 1)),
            "costs": homm3_costs(gold=2500, ore=10),
        },
        {
            "prevBuildings": prev_buildings(("Build_Tier_5", 1)),
            "costs": homm3_costs(gold=2000, wood=5, ore=5, dust=50),
        },
    ],
    "Build_Tier_6": [
        {
            "prevBuildings": prev_buildings(("Build_Tier_4", 1)),
            "costs": homm3_costs(gold=3500, ore=20, crystal=20),
        },
        {
            "prevBuildings": prev_buildings(("Build_Tier_6", 1)),
            "costs": homm3_costs(gold=3000, wood=5, ore=5, crystal=10, dust=75),
        },
    ],
    "Build_Tier_7": [
        {
            "prevBuildings": prev_buildings(("Build_Tier_5", 1)),
            "costs": homm3_costs(gold=10000, wood=10, ore=10, crystal=10),
        },
        {
            "prevBuildings": prev_buildings(("Build_Tier_7", 1)),
            "costs": homm3_costs(gold=15000, wood=10, ore=10, crystal=20, dust=100),
        },
    ],
}


def stronghold_building_icon_key(sid: str, level: int) -> str:
    return f"homm3_stronghold_building_{sid}_level_{level}"


STRONGHOLD_BUILDING_ICON_LEVELS: dict[str, int] = {
    "Build_Main": 3,
    "Build_Tavern": 1,
    "Build_Market": 1,
    "Build_Artifact_Market": 1,
    "Build_Tier_1": 2,
    "Build_Tier_2": 2,
    "Build_Tier_3": 2,
    "Build_Tier_4": 2,
    "Build_Tier_5": 2,
    "Build_Tier_6": 2,
    "Build_Tier_7": 2,
    "Build_Magic_Guild": 3,
    "Build_Bank": 1,
    "Build_Treasury": 1,
    "Build_Resource_Depot": 1,
    "Build_Resource_Depot_level_2": 1,
    "Build_Wall": 3,
    "Build_Gymnasium": 1,
    "Build_Lyceum": 1,
    "Build_Spy_Network": 1,
}


def apply_homm3_stronghold_building_icons(city: dict) -> None:
    """Replace Dungeon building portrait icon keys with Stronghold-specific runtime-resolved keys."""
    for group in city.values():
        if not isinstance(group, list):
            continue
        for building in group:
            if not isinstance(building, dict):
                continue
            sid = building.get("sid")
            icons = building.get("icons")
            if not isinstance(sid, str) or not isinstance(icons, list):
                continue
            level_count = STRONGHOLD_BUILDING_ICON_LEVELS.get(sid)
            if not level_count:
                continue
            building["icons"] = [
                stronghold_building_icon_key(sid, min(i + 1, level_count))
                for i in range(len(icons))
            ]


def cap_homm3_stronghold_magic_guild(city: dict) -> None:
    """Stronghold follows HoMM3's Mage Guild level 3 cap."""
    for building in city.get("magicGuilds") or []:
        if not isinstance(building, dict) or building.get("sid") != "Build_Magic_Guild":
            continue
        for key in (
            "icons",
            "names",
            "descriptions",
            "narrativeDescriptions",
            "backgroundImages",
            "parametersPerLevel",
        ):
            value = building.get(key)
            if isinstance(value, list) and len(value) > 3:
                building[key] = value[:3]


def apply_homm3_stronghold_building_tree(city: dict) -> None:
    """Patch custom Stronghold buildings to HoMM3 costs/prereqs without touching OE-standard structures."""
    for hire in city.get("hires") or []:
        sid = hire.get("sid")
        overrides = HOMM3_STRONGHOLD_HIRE_TREE.get(sid)
        params = hire.get("parametersPerLevel")
        if not overrides or not isinstance(params, list):
            continue
        if len(params) != len(overrides):
            raise RuntimeError(f"{sid}: expected {len(overrides)} level parameter rows, found {len(params)}")
        for row, override in zip(params, overrides):
            row["prevBuildings"] = copy.deepcopy(override["prevBuildings"])
            row["costs"] = copy.deepcopy(override["costs"])

    # Local Dungeon donor analogue for HoMM3 Hall of Valhalla. Do not alter
    # shared grail/palace/wall/mage-guild costs or other Olden Era-standard rows.
    for building in city.get("heroBonusBanks") or []:
        if building.get("sid") != "Build_Gymnasium":
            continue
        params = building.get("parametersPerLevel")
        if isinstance(params, list) and params:
            params[0]["prevBuildings"] = prev_buildings(("Build_Wall", 1))
            params[0]["costs"] = homm3_costs(gold=1000)
        building["bonuses"] = [
            {
                "type": "heroStat",
                "parameters": ["offence", "2"],
            },
        ]

    # Stronghold Resource Silo analogue. Olden Era represents per-day city
    # income with bank bonuses; use the two Dungeon resource depot rows for
    # HoMM3's wood/ore economy instead of inherited gemstones/dust.
    for building in city.get("banks") or []:
        sid = building.get("sid")
        if sid == "Build_Resource_Depot":
            building["bonuses"] = [
                {
                    "type": "sideRes",
                    "parameters": ["crystals", 1],
                },
            ]
        elif sid == "Build_Resource_Depot_level_2":
            building["bonuses"] = [
                {
                    "type": "sideRes",
                    "parameters": ["ore", 1],
                },
            ]

    # HoMM3 Stronghold Mess Hall: +8 Goblin growth. Dungeon's Lyceum slot is
    # an artifact changer, which cannot carry city bonuses, so move that
    # Stronghold-only row into cityBonusBanks while keeping the same SID,
    # scene slot, icons, build costs, and localization keys.
    artifact_changers = city.get("artifactChangers") or []
    mess_hall = None
    remaining_artifact_changers = []
    for building in artifact_changers:
        if isinstance(building, dict) and building.get("sid") == "Build_Lyceum":
            mess_hall = copy.deepcopy(building)
        else:
            remaining_artifact_changers.append(building)
    if mess_hall is not None:
        mess_hall.pop("artifacts", None)
        mess_hall["bonuses"] = [
            {
                "type": "cityUnitsIncrement",
                "parameters": ["h3_goblin", "8"],
            },
        ]
        city["artifactChangers"] = remaining_artifact_changers
        city.setdefault("cityBonusBanks", [])
        city["cityBonusBanks"] = [
            b for b in city["cityBonusBanks"]
            if not (isinstance(b, dict) and b.get("sid") == "Build_Lyceum")
        ]
        city["cityBonusBanks"].append(mess_hall)


def clone_city_from_dungeon(all_data: dict) -> dict:
    raw = all_data["DB/objects_logic/cities/dungeon_city.json"].decode("utf-8-sig")
    root = json.loads(raw)
    city = copy.deepcopy(root["array"][0])
    city["id"] = CITY_ID
    city["fraction"] = FRACTION_ID
    city["sceneName"] = "cityDungeon"
    patch_city_hires(city)
    morph_city_strings(city)
    apply_homm3_stronghold_building_tree(city)
    cap_homm3_stronghold_magic_guild(city)
    apply_homm3_stronghold_building_icons(city)
    s = json.dumps(city, ensure_ascii=False)
    s = s.replace("dungeon_city", CITY_ID).replace('"fraction": "dungeon"', f'"fraction": "{FRACTION_ID}"')
    return json.loads(s)


def remap_law_bonus(obj: object, sid_map: dict[str, str]) -> None:
    if isinstance(obj, dict):
        if obj.get("fraction") == "dungeon":
            obj["fraction"] = FRACTION_ID
        if isinstance(obj.get("receivers"), list):
            obj["receivers"] = [sid_map.get(x, x) for x in obj["receivers"]]
        if obj.get("type") == "cityUnitsIncrement" and isinstance(obj.get("parameters"), list) and obj["parameters"]:
            p0 = obj["parameters"][0]
            if isinstance(p0, str) and p0 in sid_map:
                obj["parameters"][0] = sid_map[p0]
        for v in obj.values():
            remap_law_bonus(v, sid_map)
    elif isinstance(obj, list):
        for it in obj:
            remap_law_bonus(it, sid_map)


def law_unit_stat(receivers: list[str], parameter: str, value: str) -> dict:
    return {
        "type": "unitStat",
        "receivers": receivers,
        "parameters": [parameter, value],
    }


def law_city_units_increment(unit_sid: str, value: str) -> dict:
    return {
        "type": "cityUnitsIncrement",
        "parameters": [unit_sid, value],
    }


def law_side_res(resource: str, value: int) -> dict:
    return {
        "type": "sideRes",
        "parameters": [resource, value],
    }


def law_receivers(base_sid: str) -> list[str]:
    return [base_sid, f"{base_sid}_upg", f"{base_sid}_upg_alt"]


STRONGHOLD_LAW_BONUS_OVERRIDES: dict[int, list[dict]] = {
    4: [
        {
            "cost": 3,
            "bonuses": [
                law_city_units_increment("h3_goblin", "4"),
                law_unit_stat(law_receivers("h3_goblin"), "hp", "1"),
            ],
        },
        {
            "cost": 2,
            "bonuses": [
                law_city_units_increment("h3_goblin", "4"),
                law_unit_stat(law_receivers("h3_goblin"), "hp", "2"),
            ],
        },
    ],
    10: [
        {
            "cost": 3,
            "bonuses": [
                law_unit_stat(law_receivers("h3_wolf_rider"), "hp", "2"),
                law_unit_stat(law_receivers("h3_wolf_rider"), "initiative", "1"),
            ],
        },
        {
            "cost": 2,
            "bonuses": [
                law_unit_stat(law_receivers("h3_wolf_rider"), "hp", "4"),
                law_unit_stat(law_receivers("h3_wolf_rider"), "initiative", "1"),
            ],
        },
    ],
    11: [
        {
            "cost": 3,
            "bonuses": [
                law_unit_stat(law_receivers("h3_orc"), "offence", "2"),
                law_unit_stat(law_receivers("h3_orc"), "damageMax", "1"),
            ],
        },
        {
            "cost": 2,
            "bonuses": [
                law_unit_stat(law_receivers("h3_orc"), "offence", "4"),
                law_unit_stat(law_receivers("h3_orc"), "damageMax", "2"),
            ],
        },
    ],
    14: [
        {"cost": 2, "bonuses": [law_side_res("crystals", 1)]},
        {"cost": 2, "bonuses": [law_side_res("crystals", 2)]},
    ],
    18: [
        {
            "cost": 3,
            "bonuses": [
                law_unit_stat(law_receivers("h3_ogre"), "damageMin", "2"),
                law_unit_stat(law_receivers("h3_ogre"), "damageMax", "2"),
                law_unit_stat(law_receivers("h3_ogre"), "hp", "10"),
            ],
        },
        {
            "cost": 2,
            "bonuses": [
                law_unit_stat(law_receivers("h3_ogre"), "damageMin", "4"),
                law_unit_stat(law_receivers("h3_ogre"), "damageMax", "4"),
                law_unit_stat(law_receivers("h3_ogre"), "hp", "20"),
            ],
        },
    ],
    19: [
        {
            "cost": 3,
            "bonuses": [
                law_unit_stat(law_receivers("h3_roc"), "offence", "4"),
                law_unit_stat(law_receivers("h3_roc"), "initiative", "1"),
            ],
        },
        {
            "cost": 2,
            "bonuses": [
                law_unit_stat(law_receivers("h3_roc"), "offence", "4"),
                law_unit_stat(law_receivers("h3_roc"), "initiative", "2"),
            ],
        },
    ],
    25: [
        {
            "cost": 3,
            "bonuses": [
                law_unit_stat(law_receivers("h3_cyclops"), "hp", "20"),
                law_unit_stat(law_receivers("h3_cyclops"), "offence", "3"),
            ],
        },
        {
            "cost": 2,
            "bonuses": [
                law_unit_stat(law_receivers("h3_cyclops"), "hp", "40"),
                law_unit_stat(law_receivers("h3_cyclops"), "offence", "3"),
            ],
        },
    ],
    31: [
        {
            "cost": 3,
            "bonuses": [
                law_unit_stat(law_receivers("h3_behemoth"), "offence", "4"),
                law_unit_stat(law_receivers("h3_behemoth"), "defence", "4"),
                law_unit_stat(law_receivers("h3_behemoth"), "speed", "1"),
            ],
        },
        {
            "cost": 2,
            "bonuses": [
                law_unit_stat(law_receivers("h3_behemoth"), "offence", "8"),
                law_unit_stat(law_receivers("h3_behemoth"), "defence", "8"),
                law_unit_stat(law_receivers("h3_behemoth"), "speed", "2"),
            ],
        },
    ],
}


STRONGHOLD_LAW_ICON_OVERRIDES: dict[int, str] = {
    4: "fraction_law_homm3_stronghold_4_icon",
    10: "fraction_law_homm3_stronghold_10_icon",
    11: "fraction_law_homm3_stronghold_11_icon",
    14: "fraction_law_nature_13_icon",    # crystal resource law
    18: "fraction_law_homm3_stronghold_18_icon",
    19: "fraction_law_homm3_stronghold_19_icon",
    25: "fraction_law_homm3_stronghold_25_icon",
    31: "fraction_law_homm3_stronghold_31_icon",
}


def clone_dungeon_laws(all_data: dict) -> dict:
    laws = json.loads(all_data["DB/fractions_laws/fractions_laws_table_dungeon.json"].decode("utf-8-sig"))
    out = copy.deepcopy(laws)
    for law in out["array"]:
        old_id = law["id"]
        m = re.match(r"^fraction_law_dungeon_(\d+)$", old_id)
        if not m:
            raise RuntimeError(f"Unexpected law id: {old_id}")
        n = m.group(1)
        new_id = f"fraction_law_homm3_stronghold_{n}"
        law["id"] = new_id
        law["name"] = f"fraction_law_homm3_stronghold_{n}_name"
        law["desc"] = f"fraction_law_homm3_stronghold_{n}_desc"
        remap_law_bonus(law, SID_MAP)
        icon_override = STRONGHOLD_LAW_ICON_OVERRIDES.get(int(n))
        if icon_override is not None:
            law["icon"] = icon_override
        override = STRONGHOLD_LAW_BONUS_OVERRIDES.get(int(n))
        if override is not None:
            law["parametersPerLevel"] = copy.deepcopy(override)
    return out


def clone_fraction_config(all_data: dict) -> dict:
    d = json.loads(all_data["DB/fractions/3_dungeon.json"].decode("utf-8-sig"))
    frac = copy.deepcopy(d["array"][0])
    frac["id"] = FRACTION_ID
    frac["name"] = f"{FRACTION_ID}_name"
    frac["desc"] = f"{FRACTION_ID}_desc"
    frac["narrativeDesc"] = f"{FRACTION_ID}_desc"
    # Custom map/HUD city button icon. Runtime fallback resolves this from
    # homm3_runtime_assets/map_object_refs/homm3_stronghold_city/avcstrc0.dir/00_00.png.
    frac["icon"] = "homm3_stronghold_city_icon"
    frac["iconFractionLaws"] = "Scroll_Faction_Dungeon"
    frac["cityNames"] = [f"{CITY_ID}_name_{i}" for i in range(1, 21)]

    def remap_law_line_refs(obj: object) -> None:
        if isinstance(obj, str):
            return
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == "laws" and isinstance(v, list):
                    obj[k] = [
                        re.sub(
                            r"^fraction_law_dungeon_",
                            "fraction_law_homm3_stronghold_",
                            x,
                        )
                        if isinstance(x, str)
                        else x
                        for x in v
                    ]
                else:
                    remap_law_line_refs(v)
        elif isinstance(obj, list):
            for it in obj:
                remap_law_line_refs(it)

    remap_law_line_refs(frac.get("fractionLawsLines"))
    return {"array": [frac]}


STRONGHOLD_CITY_TEXT: dict[str, str] = {
    "Homm3Stronghold_Build_Gymnasium_name": "Hall of Valhalla",
    "Homm3Stronghold_Build_Gymnasium_description": "Increases the visiting hero's Attack by 2.",
    "Homm3Stronghold_Build_Gymnasium_narrativeDescription": "The Hall of Valhalla honors the strongest warlords of Krewlod. A visiting hero gains +2 Attack.",
    "Homm3Stronghold_Build_Lyceum_name": "Mess Hall",
    "Homm3Stronghold_Build_Lyceum_description": "Increases Goblin growth by 8.",
    "Homm3Stronghold_Build_Lyceum_narrativeDescription": "The Mess Hall keeps the goblin tribes fed, armed, and ready for war. Goblin growth increases by 8.",
    "Homm3Stronghold_Build_Resource_Depot_name": "Resource Silo",
    "Homm3Stronghold_Build_Resource_Depot_description": "Produces 1 Crystal daily.",
    "Homm3Stronghold_Build_Resource_Depot_name_level_2": "Resource Silo II",
    "Homm3Stronghold_Build_Resource_Depot_description_level_2": "Produces 1 Ore daily.",
    "Homm3Stronghold_Build_Resource_Depot_narrativeDescription": "The Stronghold Resource Silo supplies the minerals needed for Cyclopes and Behemoths.",
    "Homm3Stronghold_Build_Tier_1_name_level_1": "Goblin Hut",
    "Homm3Stronghold_Build_Tier_1_description_level_1": "Allows recruitment of Goblins.",
    "Homm3Stronghold_Build_Tier_1_name_level_2": "Goblin Hut II",
    "Homm3Stronghold_Build_Tier_1_description_level_2": "Allows recruitment of Hobgoblins and Goblin Trappers.",
    "Homm3Stronghold_Build_Tier_2_name_level_1": "Wolf Pen",
    "Homm3Stronghold_Build_Tier_2_description_level_1": "Allows recruitment of Wolf Riders.",
    "Homm3Stronghold_Build_Tier_2_name_level_2": "Wolf Pen II",
    "Homm3Stronghold_Build_Tier_2_description_level_2": "Allows recruitment of Wolf Raiders.",
    "Homm3Stronghold_Build_Tier_3_name_level_1": "Orc Tower",
    "Homm3Stronghold_Build_Tier_3_description_level_1": "Allows recruitment of Orcs.",
    "Homm3Stronghold_Build_Tier_3_name_level_2": "Orc Tower II",
    "Homm3Stronghold_Build_Tier_3_description_level_2": "Allows recruitment of Orc Chieftains.",
    "Homm3Stronghold_Build_Tier_4_name_level_1": "Ogre Fort",
    "Homm3Stronghold_Build_Tier_4_description_level_1": "Allows recruitment of Ogres.",
    "Homm3Stronghold_Build_Tier_4_name_level_2": "Ogre Fort II",
    "Homm3Stronghold_Build_Tier_4_description_level_2": "Allows recruitment of Ogre Magi.",
    "Homm3Stronghold_Build_Tier_5_name_level_1": "Cliff Nest",
    "Homm3Stronghold_Build_Tier_5_description_level_1": "Allows recruitment of Rocs.",
    "Homm3Stronghold_Build_Tier_5_name_level_2": "Cliff Nest II",
    "Homm3Stronghold_Build_Tier_5_description_level_2": "Allows recruitment of Thunderbirds.",
    "Homm3Stronghold_Build_Tier_6_name_level_1": "Cyclops Cave",
    "Homm3Stronghold_Build_Tier_6_description_level_1": "Allows recruitment of Cyclopes.",
    "Homm3Stronghold_Build_Tier_6_name_level_2": "Cyclops Cave II",
    "Homm3Stronghold_Build_Tier_6_description_level_2": "Allows recruitment of Cyclops Kings.",
    "Homm3Stronghold_Build_Tier_7_name_level_1": "Behemoth Crag",
    "Homm3Stronghold_Build_Tier_7_description_level_1": "Allows recruitment of Behemoths.",
    "Homm3Stronghold_Build_Tier_7_name_level_2": "Behemoth Crag II",
    "Homm3Stronghold_Build_Tier_7_description_level_2": "Allows recruitment of Ancient Behemoths.",
}


H3_UNIT_DISPLAY_TEXT: dict[str, str] = {
    # Unit names
    "h3_goblin_name": "Goblin",
    "h3_goblin_upg_name": "Hobgoblin",
    "h3_goblin_upg_alt_name": "Goblin Trapper",
    "h3_wolf_rider_name": "Wolf Rider",
    "h3_wolf_rider_upg_name": "Wolf Raider",
    "h3_wolf_rider_upg_alt_name": "Boar Rider",
    "h3_orc_name": "Orc",
    "h3_orc_upg_name": "Orc Chieftain",
    "h3_orc_upg_alt_name": "Orc Berserker",
    "h3_ogre_name": "Ogre",
    "h3_ogre_upg_name": "Ogre Mage",
    "h3_ogre_upg_alt_name": "Ogre Brute",
    "h3_roc_name": "Roc",
    "h3_roc_upg_name": "Thunderbird",
    "h3_roc_upg_alt_name": "Shahrokh",
    "h3_cyclops_name": "Cyclops",
    "h3_cyclops_upg_name": "Cyclops King",
    "h3_cyclops_upg_alt_name": "Blood-Eyed Cyclops",
    "h3_behemoth_name": "Behemoth",
    "h3_behemoth_upg_name": "Ancient Behemoth",
    "h3_behemoth_upg_alt_name": "Ghost Behemoth",
    # Narrative descriptions
    "h3_goblin_narrativeDescription": "Goblins are cheap Stronghold infantry. They bring numbers and speed, not special battlefield tricks.",
    "h3_goblin_upg_narrativeDescription": "Hobgoblins are faster and tougher than common goblins, but remain straightforward melee troops.",
    "h3_goblin_upg_alt_narrativeDescription": "Goblin Trappers harry the enemy with snares and ambushes before closing in with the rest of the horde.",
    "h3_wolf_rider_narrativeDescription": "Wolf Riders are fast Stronghold melee cavalry.",
    "h3_wolf_rider_upg_narrativeDescription": "Wolf Raiders tear through the front line with repeated strikes and the speed to choose their fights.",
    "h3_wolf_rider_upg_alt_narrativeDescription": "Boar Riders thunder into battle, trusting momentum and brute force to break enemy ranks.",
    "h3_orc_narrativeDescription": "Orcs are Stronghold ranged troops with a basic melee fallback when engaged.",
    "h3_orc_upg_narrativeDescription": "Orc Chieftains are veteran Stronghold shooters, tougher and deadlier than common orcs.",
    "h3_orc_upg_alt_narrativeDescription": "Orc Berserkers rush in with reckless fury, striking hard before the enemy can settle its line.",
    "h3_ogre_narrativeDescription": "Ogres are living engines of destruction, towering over lesser creatures and crushing anything in their path. Their loyalty is bought with promises of carnage.",
    "h3_ogre_upg_narrativeDescription": "Ogre Magi channel primal magic through their blood, using it to ignite the fury of their allies. A bloodlusted ogre is a sight few survive to describe.",
    "h3_ogre_upg_alt_narrativeDescription": "Ogre Brutes throw themselves into combat with enough rage to scatter disciplined troops.",
    "h3_roc_narrativeDescription": "Rocs are swift flying hunters that strike where the enemy line is weakest.",
    "h3_roc_upg_narrativeDescription": "Thunderbirds descend in a storm of talons and lightning.",
    "h3_roc_upg_alt_narrativeDescription": "Shahrokhs are fierce winged predators that overwhelm their prey with relentless attacks.",
    "h3_cyclops_narrativeDescription": "Cyclopes are Stronghold ranged attackers.",
    "h3_cyclops_upg_narrativeDescription": "Cyclops Kings hurl crushing stones with the force to threaten even fortified positions.",
    "h3_cyclops_upg_alt_narrativeDescription": "Blood-Eyed Cyclopes are brutal marksmen whose aim stays dangerous at any distance.",
    "h3_behemoth_narrativeDescription": "Behemoths are elite Stronghold monsters that tear through armor with terrifying ease.",
    "h3_behemoth_upg_narrativeDescription": "Ancient Behemoths are older, stronger, and feared for crushing even the toughest defenders.",
    "h3_behemoth_upg_alt_narrativeDescription": "Ghost Behemoths are spectral horrors that descend on enemies and shred their defenses.",
    # Ability/passive names and descriptions for cloned Dungeon tokens
    # Goblin passives (cloned from trogl)
    "h3_goblin_passive_1_name": "Goblin Spit",
    "h3_goblin_passive_1_description": "Long Reach attack that does not provoke a counterattack. Deals –{0}% Damage.",
    "h3_goblin_passive_2_name": "Toxic Blood",
    "h3_goblin_passive_2_description": "When this creature is Damaged, all adjacent enemies take +{0}% Damage until the end of the next round.",
    # Wolf Rider passives
    "h3_wolf_rider_passive_1_name": "Double Attack",
    "h3_wolf_rider_passive_1_description": "Strikes twice when performing melee attacks.",
    "h3_wolf_rider_upg_passive_1_name": "Double Attack",
    "h3_wolf_rider_upg_passive_1_description": "Strikes twice when performing melee attacks.",
    "h3_wolf_rider_upg_alt_ability_1_name": "Charge",
    "h3_wolf_rider_upg_alt_ability_1_description": "Makes a melee attack at 100% normal damage and reduces the target's Luck by 5 for 1 round. Costs 1 Focus Charge. Cooldown: 1 round.",
    "h3_wolf_rider_upg_alt_passive_1_name": "Jousting",
    "h3_wolf_rider_upg_alt_passive_1_description": "Charges into melee with brute force.",
    "h3_wolf_rider_passive_2_name": "Staggering Bite",
    "h3_wolf_rider_passive_2_description": "Attacks prevent the target from counterattacking until the end of the round.",
    "h3_wolf_rider_passive_3_name": "Blood Scent",
    "h3_wolf_rider_passive_3_description": "Each attack increases this creature's luck by {0}.",
    # Orc passives (cloned from blade_dancer)
    "h3_orc_passive_1_name": "Axes and Anger",
    "h3_orc_passive_1_description": "Each attack reduces the target's Defense by {0} until the end of battle. This effect is stackable.",
    "h3_orc_passive_2_name": "Brutal Throw",
    "h3_orc_passive_2_description": "Ranged attacks deal double Damage.",
    # Ogre passives (cloned from minos)
    "h3_ogre_passive_1_name": "Eager for Battle",
    "h3_ogre_passive_1_description": "This creature always has positive Morale, and its maximum increases to {1}. Chance of Morale triggering increases by {0}% for each total point.",
    "h3_ogre_passive_2_name": "Blood for Blood",
    "h3_ogre_passive_2_description": "Whenever this creature takes Damage, its Morale increases by {0}.",
    "h3_ogre_passive_3_name": "Adrenaline Surge",
    "h3_ogre_passive_3_description": "Whenever this creature's Morale triggers, its Speed increases by {0} and its Attack and Defense increase by {1}. Lasts until the end of the next round.",
    # Roc passives
    "h3_roc_passive_1_name": "Flight",
    "h3_roc_passive_1_description": "Flying movement.",
    "h3_roc_upg_passive_1_name": "Flight",
    "h3_roc_upg_passive_1_description": "Flying movement.",
    "h3_roc_upg_alt_passive_1_name": "Ferocity",
    "h3_roc_upg_alt_passive_1_description": "Strikes twice when performing melee attacks.",
    # Cyclops passives
    "h3_cyclops_passive_1_name": "Ranged Attack",
    "h3_cyclops_passive_1_description": "A heavy ranged attack.",
    "h3_cyclops_upg_passive_1_name": "Siege Wall Attack",
    "h3_cyclops_upg_passive_1_description": "A heavy ranged attack.",
    "h3_cyclops_upg_alt_passive_1_name": "No Distance Penalty",
    "h3_cyclops_upg_alt_passive_1_description": "Ranged attacks deal full damage at any range.",
    "h3_cyclops_passive_2_name": "Regeneration",
    "h3_cyclops_passive_2_description": "Restores to full HP at the start of its turn.",
    "h3_cyclops_passive_3_name": "Toxic Flesh",
    "h3_cyclops_passive_3_description": "Whenever this creature takes Damage, adjacent enemy creatures deal –{0}% Damage until the end of next round.",
    "h3_cyclops_passive_4_name": "Growing Rage",
    "h3_cyclops_passive_4_description": "Whenever this creature takes Damage, it gains {0} Attack until the end of the battle.",
    "h3_cyclops_passive_5_name": "All Out Assault",
    "h3_cyclops_passive_5_description": "This creature's counterattacks use its full Fighting Style effects.",
    # Behemoth passives
    "h3_behemoth_passive_1_name": "Defense Reduction",
    "h3_behemoth_passive_1_description": "Ignores 40% of the target's Defense when attacking.",
    "h3_behemoth_upg_passive_1_name": "Greater Defense Reduction",
    "h3_behemoth_upg_passive_1_description": "Ignores 80% of the target's Defense when attacking.",
    "h3_behemoth_upg_alt_passive_1_name": "Defense Reduction",
    "h3_behemoth_upg_alt_passive_1_description": "Ignores 60% of the target's Defense when attacking.",
    "h3_behemoth_passive_2_name": "Flying",
    "h3_behemoth_passive_2_description": "Flying movement.",
    # Goblin ability (Long Reach)
    "h3_goblin_ability_1_name": "Goblin Spit",
    "h3_goblin_ability_1_description": "Performs a Long Reach attack, dealing –{0}% Damage. Does not provoke counterattacks.",
    "h3_goblin_ability_1_advanced_name": "Vicious Spit",
    "h3_goblin_ability_1_advanced_description": "Performs a Long Reach attack at full power. Does not provoke counterattacks.",
    # Wolf Rider ability
    "h3_wolf_rider_ability_1_name": "Pack Tactics",
    "h3_wolf_rider_ability_1_description": "Returns to original position after attacking, dealing –{0}% Damage.",
    "h3_wolf_rider_ability_1_advanced_name": "Advanced Pack Tactics",
    "h3_wolf_rider_ability_1_advanced_description": "Returns to original position after attacking at full power.",
    "h3_wolf_rider_ability_2_name": "Throat Strike",
    "h3_wolf_rider_ability_2_description": "Deals basic attack Damage to any enemy, ignoring their Defense.",
    "h3_wolf_rider_ability_3_name": "Shadow Pelt",
    "h3_wolf_rider_ability_3_description": "Cannot be targeted until the end of the round.",
    # Orc ability
    "h3_orc_ability_1_name": "Double Axe Throw",
    "h3_orc_ability_1_description": "Choose two targets for this attack, dealing –{0}% Damage to each.",
    "h3_orc_ability_1_advanced_name": "Twin Axe Throw",
    "h3_orc_ability_1_advanced_description": "Choose two targets for this attack at full power.",
    "h3_orc_hamstring_name": "Hamstring",
    "h3_orc_hamstring_description": "Deals 50% basic attack damage and reduces the target's Speed by 2 for 1 round. Costs 1 Focus Charge and ends this creature's turn.",
    "h3_orc_upg_hamstring_name": "Hamstring",
    "h3_orc_upg_hamstring_description": "Deals 100% basic attack damage and reduces the target's Speed by 3 for 1 round. Costs 1 Focus Charge and ends this creature's turn.",
    "h3_orc_upg_alt_ability_1_name": "Return After Strike",
    "h3_orc_upg_alt_ability_1_description": "Performs a melee attack, then returns to the starting hex. Does not spend Focus Charges.",
    # Ogre ability
    "h3_ogre_ability_1_name": "Grand Slam",
    "h3_ogre_ability_1_description": "Hits the target and all creatures within two hexes behind it, dealing –{0}% Damage to each.",
    "h3_ogre_ability_1_advanced_name": "Ogre Grand Slam",
    "h3_ogre_ability_1_advanced_description": "Hits the target and all creatures within two hexes behind it at full power.",
    "h3_ogre_ability_2_name": "Iron Gut",
    "h3_ogre_ability_2_description": "Fully ignores attackers' Attack values until the end of the round.",
    "h3_ogre_upg_ability_1_name": "Bloodlust",
    "h3_ogre_upg_ability_1_description": "Casts Advanced Bloodlust on an allied unit, increasing Offense by 6 for 2 rounds. Costs 2 Focus Charges. Cooldown: 2 rounds.",
    "h3_ogre_upg_alt_ability_1_name": "Frenzied Charge",
    "h3_ogre_upg_alt_ability_1_description": "Spends 2 Focus Charges to attack, then returns to the starting hex without ending the unit's turn. Cooldown: 1 round.",
    # Thunderbird ability. Keep player-facing text focused on the visible effect.
    "h3_roc_upg_ability_1_name": "Lightning Strike",
    "h3_roc_upg_ability_1_description": "Performs a lightning-themed melee attack at 120% damage. Costs 2 Focus Charges. Cooldown: 2 rounds.",
    "h3_roc_ability_1_name": "Flight",
    "h3_roc_ability_1_description": "Flying movement.",
    "h3_roc_ability_1_advanced_name": "Flight",
    "h3_roc_ability_1_advanced_description": "Flying movement.",
    "h3_roc_ability_2_name": "Lightning Strike",
    "h3_roc_ability_2_description": "Calls down lightning during a melee attack.",
    "h3_roc_ability_3_name": "Ferocity",
    "h3_roc_ability_3_description": "Strikes twice when performing melee attacks.",
    # Cyclops ability
    "h3_cyclops_ability_1_name": "Ranged Attack",
    "h3_cyclops_ability_1_description": "A heavy ranged attack.",
    "h3_cyclops_ability_1_advanced_name": "Siege Wall Attack",
    "h3_cyclops_ability_1_advanced_description": "A heavy ranged attack.",
    "h3_cyclops_ability_2_name": "No Distance Penalty",
    "h3_cyclops_ability_2_description": "Ranged attacks deal full damage at any range.",
    "h3_cyclops_ability_3_name": "No Wall Penalty",
    "h3_cyclops_ability_3_description": "A heavy ranged attack.",
    # Behemoth ability
    "h3_behemoth_ability_1_name": "Defense Reduction",
    "h3_behemoth_ability_1_description": "Ignores 40% of the target's Defense when attacking.",
    "h3_behemoth_ability_1_advanced_name": "Greater Defense Reduction",
    "h3_behemoth_ability_1_advanced_description": "Ignores 80% of the target's Defense when attacking.",
    "h3_behemoth_ability_2_name": "Flying",
    "h3_behemoth_ability_2_description": "Flying movement.",
    "h3_behemoth_ability_3_name": "Defense Reduction",
    "h3_behemoth_ability_3_description": "Ignores 60% of the target's Defense when attacking.",
    # Alternate-upgrade concepts that may surface in UI; keep wording player-facing.
    "h3_goblin_ability_2_name": "Land Mine",
    "h3_goblin_ability_2_description": "Places a hidden snare trap on target hex. The first unit that crosses it is stopped and snared for 2 rounds. Costs 1 Focus Charge. Cooldown: 1 round.",
    "h3_wolf_rider_ability_4_name": "Jousting",
    "h3_wolf_rider_ability_4_description": "Charges into melee with brute force.",
    "h3_wolf_rider_ability_5_name": "Double Attack",
    "h3_wolf_rider_ability_5_description": "Strikes twice when performing melee attacks.",
    "h3_orc_ability_2_name": "Berserk Strike",
    "h3_orc_ability_2_description": "Throws the Orc Berserker into a furious attack.",
    "h3_ogre_ability_3_name": "Bloodlust",
    "h3_ogre_ability_3_description": "Whips an allied unit into a bloodlusted rage.",
    "h3_roc_ability_4_name": "Ferocity",
    "h3_roc_ability_4_description": "Strikes twice when performing melee attacks.",
    "h3_cyclops_ability_4_name": "No Range Penalty",
    "h3_cyclops_ability_4_description": "Ranged attacks deal full damage at any range.",
}

STRONGHOLD_CITY_ARG_OVERRIDES: dict[str, list[str]] = {
    "Homm3Stronghold_Build_Gymnasium_description": [],
    "Homm3Stronghold_Build_Gymnasium_narrativeDescription": [],
    "Homm3Stronghold_Build_Lyceum_description": [],
    "Homm3Stronghold_Build_Lyceum_narrativeDescription": [],
    "Homm3Stronghold_Build_Resource_Depot_description": [],
    "Homm3Stronghold_Build_Resource_Depot_description_level_2": [],
    "Homm3Stronghold_Build_Resource_Depot_narrativeDescription": [],
}


H3_UNIT_BUFF_TEXT: dict[str, str] = {
    "h3_orc_hamstring_debuff_name": "Hamstrung",
    "h3_orc_hamstring_debuff_description": "Speed reduced by 2.",
    "h3_orc_upg_hamstring_debuff_name": "Crippled",
    "h3_orc_upg_hamstring_debuff_description": "Speed reduced by 3.",
    "h3_wolf_rider_upg_alt_charge_debuff_name": "Shaken",
    "h3_wolf_rider_upg_alt_charge_debuff_description": "Luck reduced by 5.",
    "h3_ogre_upg_bloodlust_description": "Offense increased by 6.",
}


H3_UNIT_BUFF_ARG_OVERRIDES: dict[str, list[str]] = {
    # The Dungeon donor minos_moral_selfbuff_description has no unitsBuff args
    # row in this build, so the cloned h3_ogre token must be supplied directly.
    "h3_ogre_moral_selfbuff_description": [
        "current_buff_offence_param",
        "current_buff_speed_param",
    ],
}


STRONGHOLD_LAW_TEXT_OVERRIDES: dict[str, str] = {
    "fraction_law_homm3_stronghold_4_name": "Goblin Muster",
    "fraction_law_homm3_stronghold_4_desc": "Your Goblin dwellings produce +{0} creatures. Goblins gain +{1} HP.",
    "fraction_law_homm3_stronghold_10_name": "Wolf Raider Drills",
    "fraction_law_homm3_stronghold_10_desc": "Your Wolf Riders gain +{0} HP and +{1} Initiative.",
    "fraction_law_homm3_stronghold_11_name": "Orcish Fletching",
    "fraction_law_homm3_stronghold_11_desc": "Your Orcs gain +{0} Attack and +{1} max. Damage.",
    "fraction_law_homm3_stronghold_14_name": "Mining: Crystals",
    "fraction_law_homm3_stronghold_14_desc": "Produces {0} Crystal(s) daily.",
    "fraction_law_homm3_stronghold_18_name": "Ogre Warbands",
    "fraction_law_homm3_stronghold_18_desc": "Your Ogres deal +{0} Damage and gain +{1} HP.",
    "fraction_law_homm3_stronghold_19_name": "Roc Aeries",
    "fraction_law_homm3_stronghold_19_desc": "Your Rocs gain +{0} Attack and +{1} Initiative.",
    "fraction_law_homm3_stronghold_22_name": "Stronghold Envoys",
    "fraction_law_homm3_stronghold_22_desc": "Your Stronghold heroes gain {0} to all attributes.",
    "fraction_law_homm3_stronghold_25_name": "Cyclops Siege Crews",
    "fraction_law_homm3_stronghold_25_desc": "Your Cyclopes gain +{0} HP and +{1} Attack.",
    "fraction_law_homm3_stronghold_31_name": "Behemoth Craglords",
    "fraction_law_homm3_stronghold_31_desc": "Your Behemoths gain +{0} Attack and Defense and +{1} Speed.",
}


STRONGHOLD_LAW_ARG_OVERRIDES: dict[str, list[str]] = {
    "fraction_law_homm3_stronghold_4_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modInt_bonuses_1_parameters_1",
    ],
    "fraction_law_homm3_stronghold_10_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modInt_bonuses_1_parameters_1",
    ],
    "fraction_law_homm3_stronghold_11_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modInt_bonuses_1_parameters_1",
    ],
    "fraction_law_homm3_stronghold_18_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modInt_bonuses_2_parameters_1",
    ],
    "fraction_law_homm3_stronghold_19_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modInt_bonuses_1_parameters_1",
    ],
    "fraction_law_homm3_stronghold_25_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modInt_bonuses_1_parameters_1",
    ],
    "fraction_law_homm3_stronghold_31_desc": [
        "current_law_modInt_bonuses_0_parameters_1",
        "current_law_modInt_bonuses_2_parameters_1",
    ],
}


def upsert_text_tokens(path: Path, updates: dict[str, str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    tokens = payload.setdefault("tokens", [])
    by_sid = {token["sid"]: token for token in tokens if "sid" in token}
    for sid, text in updates.items():
        if sid in by_sid:
            by_sid[sid]["text"] = text
        else:
            tokens.append({"sid": sid, "text": text})
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def upsert_args_tokens(path: Path, new_sids: list[str]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    args_list = payload.setdefault("tokensArgs", [])
    by_sid = {t["sid"]: t for t in args_list}
    for sid in new_sids:
        old = sid.replace("fraction_law_homm3_stronghold_", "fraction_law_dungeon_")
        if old not in by_sid:
            continue
        if sid not in by_sid:
            args_list.append({"sid": sid, "args": copy.deepcopy(by_sid[old]["args"])})
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def override_args_tokens(path: Path, updates: dict[str, list[str]]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    args_list = payload.setdefault("tokensArgs", [])
    by_sid = {t["sid"]: t for t in args_list if isinstance(t.get("sid"), str)}
    for sid, args in updates.items():
        if sid in by_sid:
            by_sid[sid]["args"] = copy.deepcopy(args)
        else:
            args_list.append({"sid": sid, "args": copy.deepcopy(args)})
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def clone_args_tokens_for_sid_map(path: Path, sid_pairs: list[tuple[str, str]]) -> int:
    if not path.is_file():
        return 0
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    args_list = payload.setdefault("tokensArgs", [])
    by_sid = {t["sid"]: t for t in args_list if isinstance(t.get("sid"), str)}
    original = [t for t in args_list if isinstance(t.get("sid"), str)]
    added = 0
    for old_sid, new_sid in sid_pairs:
        for token in original:
            sid = token["sid"]
            if sid == old_sid or sid.startswith(old_sid + "_"):
                mapped = new_sid + sid[len(old_sid):]
                if mapped in by_sid:
                    continue
                clone = copy.deepcopy(token)
                clone["sid"] = mapped
                args_list.append(clone)
                by_sid[mapped] = clone
                added += 1
    if added:
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return added


def build_faction_law_text_from_dungeon(faction_laws_path: Path) -> dict[str, str]:
    eng = json.loads(faction_laws_path.read_text(encoding="utf-8-sig"))
    by_sid = {t["sid"]: t["text"] for t in eng.get("tokens", []) if "sid" in t}
    out: dict[str, str] = {}
    for i in range(1, 34):
        for suffix in ("_name", "_desc"):
            old = f"fraction_law_dungeon_{i}{suffix}"
            new = f"fraction_law_homm3_stronghold_{i}{suffix}"
            if old in by_sid:
                out[new] = by_sid[old]
    out.update(STRONGHOLD_LAW_TEXT_OVERRIDES)
    return out


def list_lang_locales() -> list[str]:
    """Locale folder names under Lang/ that have texts/cities.json (ship layout)."""
    if not LANG_ROOT.is_dir():
        return []
    out: list[str] = []
    for p in sorted(LANG_ROOT.iterdir()):
        if not p.is_dir():
            continue
        if (p / "texts" / "cities.json").is_file():
            out.append(p.name)
    return out


def patch_localization() -> None:
    locales = list_lang_locales()
    if not locales:
        print("Lang: no locales under", LANG_ROOT)
        return

    for locale in locales:
        texts = LANG_ROOT / locale / "texts"
        cities_path = texts / "cities.json"
        dungeon_city_name = collect_dungeon_city_name_templates(cities_path)

        cities_updates: dict[str, str] = {
            f"{FRACTION_ID}_name": "Stronghold (HoMM3)",
            f"{FRACTION_ID}_desc": (
                "Strength rules in the Stronghold. Goblins, orcs, ogres, rocs, cyclopes, and behemoths "
                "win battles with speed, numbers, and brutal force."
            ),
            CITY_ID: "Stronghold Town",
            f"{CITY_ID}_name": "Stronghold Town",
            f"{CITY_ID}_description": "A rugged Stronghold town built for raiders, shamans, and beasts.",
            f"{CITY_ID}_narrativeDescription": (
                "Stronghold towns gather harsh warriors and monstrous allies under one rule: only the strong endure."
            ),
            **dungeon_city_name,
        }
        if locale == "english":
            cities_updates.update(STRONGHOLD_CITY_TEXT)

        upsert_text_tokens(cities_path, cities_updates)

        fl_path = texts / "factionLaws.json"
        if fl_path.is_file():
            law_text = build_faction_law_text_from_dungeon(fl_path)
            upsert_text_tokens(fl_path, law_text)

    new_arg_sids = [f"fraction_law_homm3_stronghold_{i}_desc" for i in range(1, 34)]
    clone_homm3_city_building_args_from_dungeon()
    override_args_tokens(ARGS_CITIES_PATH, STRONGHOLD_CITY_ARG_OVERRIDES)
    upsert_args_tokens(ARGS_FACTION_LAWS_PATH, new_arg_sids)
    override_args_tokens(ARGS_FACTION_LAWS_PATH, STRONGHOLD_LAW_ARG_OVERRIDES)
    pairs = sorted(SID_MAP.items(), key=lambda kv: len(kv[0]), reverse=True)
    clone_args_tokens_for_sid_map(ARGS_UNITS_ABILITY_PATH, pairs)
    clone_args_tokens_for_sid_map(ARGS_UNITS_BUFF_PATH, pairs)
    propagate_base_args_to_upgrades(ARGS_UNITS_ABILITY_PATH)
    propagate_base_args_to_upgrades(ARGS_UNITS_BUFF_PATH)

    for locale in locales:
        texts = LANG_ROOT / locale / "texts"
        cities_path = texts / "cities.json"
        upsert_homm3_city_string_tokens_from_dungeon_and_fallbacks(cities_path)
        ua = texts / "unitsAbility.json"
        ub = texts / "unitsBuff.json"
        if ua.is_file() and ub.is_file():
            patch_homm3_unit_lang_tokens(ua, ub)
        mo = texts / "mapObjects.json"
        if mo.is_file():
            patch_homm3_city_map_object_lang_tokens(mo)

    print(f"Lang: patched locales {', '.join(locales)} under {LANG_ROOT}.")


def clone_lang_tokens_for_sid_map(path: Path, sid_pairs: list[tuple[str, str]]) -> int:
    """For each source token sid == old or old_*, append new_sid with same text. Longest old id wins per token."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    tokens = payload.setdefault("tokens", [])
    by_sid: dict[str, dict] = {t["sid"]: t for t in tokens if isinstance(t.get("sid"), str)}
    original = [t for t in tokens if isinstance(t.get("sid"), str)]
    added = 0
    for token in original:
        sid = token["sid"]
        for old, new in sid_pairs:
            if sid == old or sid.startswith(old + "_"):
                new_sid = new + sid[len(old) :]
                if new_sid in by_sid:
                    break
                clone = {"sid": new_sid, "text": token.get("text", "")}
                tokens.append(clone)
                by_sid[new_sid] = clone
                added += 1
                break
    if added:
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return added


def clone_homm3_city_building_args_from_dungeon() -> None:
    """Mirror Dungeon city-building LocKit args for Stronghold building text SIDs."""
    if not ARGS_CITIES_PATH.is_file():
        return

    payload = json.loads(ARGS_CITIES_PATH.read_text(encoding="utf-8-sig"))
    args_list = payload.setdefault("tokensArgs", [])
    by_sid = {t["sid"]: t for t in args_list if isinstance(t.get("sid"), str)}
    added = 0

    def add_clone(new_sid: str, source_sid: str) -> None:
        nonlocal added
        if new_sid in by_sid:
            return
        source = by_sid.get(source_sid)
        if source is None:
            return
        clone = {"sid": new_sid, "args": copy.deepcopy(source.get("args", []))}
        args_list.append(clone)
        by_sid[new_sid] = clone
        added += 1

    for sid in sorted(list(by_sid)):
        if not sid.startswith("Dungeon_Build_"):
            continue
        add_clone("Homm3Stronghold_" + sid[len("Dungeon_") :], sid)

    # City hover panels can ask for *_narrativeDescription. Those texts are
    # copied from the closest description token, so give them the same args.
    narrative_sources = {
        "Homm3Stronghold_Build_Main_narrativeDescription": "Homm3Stronghold_Build_Main_description_level_1_alt",
        "Homm3Stronghold_Build_Wall_narrativeDescription": "Homm3Stronghold_Build_Wall_description_level_1",
        "Homm3Stronghold_Build_Magic_Guild_narrativeDescription": "Homm3Stronghold_Build_Magic_Guild_description_level_1",
        "Homm3Stronghold_Build_Bank_narrativeDescription": "Homm3Stronghold_Build_Bank_description",
        "Homm3Stronghold_Build_Treasury_narrativeDescription": "Homm3Stronghold_Build_Treasury_description",
        "Homm3Stronghold_Build_Resource_Depot_narrativeDescription": "Homm3Stronghold_Build_Resource_Depot_description",
        "Homm3Stronghold_Build_Unic_Graal_narrativeDescription": "Homm3Stronghold_Build_Unic_Graal_description",
    }
    for new_sid, source_sid in narrative_sources.items():
        add_clone(new_sid, source_sid)

    if added:
        ARGS_CITIES_PATH.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        print(f"args/cities.json: added {added} Homm3Stronghold building arg row(s).")


def propagate_base_args_to_upgrades(path: Path) -> None:
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    args_list = payload.setdefault("tokensArgs", [])
    by_sid = {t["sid"]: t for t in args_list if isinstance(t.get("sid"), str)}
    added = False
    for base in BASE_TO_H3.values():
        base_rows = [
            t
            for t in list(args_list)
            if is_true_h3_base_token_sid(t.get("sid"), base)
        ]
        for token in base_rows:
            sid = token["sid"]
            for suf in ("_upg", "_upg_alt"):
                upgrade_sid = sid.replace(base, base + suf, 1)
                if upgrade_sid in by_sid:
                    continue
                clone = copy.deepcopy(token)
                clone["sid"] = upgrade_sid
                args_list.append(clone)
                by_sid[upgrade_sid] = clone
                added = True
    if added:
        path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def is_true_h3_base_token_sid(sid: object, base: str) -> bool:
    if not isinstance(sid, str) or not sid.startswith(base + "_"):
        return False
    remainder = sid[len(base) + 1:]
    return not (remainder.startswith("upg_") or remainder.startswith("upg_alt_"))


def patch_homm3_unit_lang_tokens(units_ability_path: Path, units_buff_path: Path) -> None:
    """unitsAbility / unitsBuff use unitId_* sids (e.g. trogl_name). Cloned h3_* units need parallel rows or LocKit breaks."""
    pairs = sorted(SID_MAP.items(), key=lambda kv: len(kv[0]), reverse=True)
    a = clone_lang_tokens_for_sid_map(units_ability_path, pairs)
    upsert_text_tokens(units_ability_path, H3_UNIT_DISPLAY_TEXT)
    # Propagate base-token custom names to upgrade variants so info panels show
    # the same Stronghold names for base, upg, and upg_alt.
    propagate_base_tokens_to_upgrades(units_ability_path, H3_UNIT_DISPLAY_TEXT)
    b = clone_lang_tokens_for_sid_map(units_buff_path, pairs)
    upsert_text_tokens(units_buff_path, H3_UNIT_BUFF_TEXT)
    override_args_tokens(ARGS_UNITS_BUFF_PATH, H3_UNIT_BUFF_ARG_OVERRIDES)
    if a or b:
        loc = units_ability_path.parent.parent.name
        print(f"units lang ({loc}): unitsAbility +{a} token(s), unitsBuff +{b} token(s).")


def propagate_base_tokens_to_upgrades(path: Path, base_tokens: dict[str, str]) -> None:
    """For each base token like h3_roc_ability_1_name, also set h3_roc_upg_ability_1_name
    and h3_roc_upg_alt_ability_1_name to the same value, so all variants display
    the same Stronghold ability names in the info panel."""
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    tokens = payload.setdefault("tokens", [])
    by_sid = {t["sid"]: t for t in tokens if "sid" in t}
    updates: dict[str, str] = {}
    for sid, text in base_tokens.items():
        # Only propagate ability/passive tokens, not unit names
        if not any(tag in sid for tag in ("_ability_", "_passive_", "_advanced_")):
            continue
        for base_id, _h3_id in BASE_TO_H3.items():
            h3_base = _h3_id
            if not sid.startswith(h3_base + "_"):
                continue
            remainder = sid[len(h3_base) + 1:]
            if remainder.startswith("upg_") or remainder.startswith("upg_alt_"):
                continue
            for suf in ("_upg", "_upg_alt"):
                upgrade_sid = sid.replace(h3_base, h3_base + suf, 1)
                if upgrade_sid in base_tokens:
                    continue
                if upgrade_sid not in by_sid or by_sid[upgrade_sid].get("text", "") != text:
                    updates[upgrade_sid] = text
    if updates:
        upsert_text_tokens(path, updates)


def patch_homm3_city_map_object_lang_tokens(map_objects_path: Path) -> None:
    """Adventure interactable uses mapObjects-style *_name / *_description like other map features."""
    if not map_objects_path.is_file():
        return
    dwelling_text = {
        1: ("Goblin Hut", "An external dwelling that provides Goblin recruits for Stronghold (HoMM3) armies."),
        2: ("Wolf Pen", "An external dwelling that provides Wolf Rider recruits for Stronghold (HoMM3) armies."),
        3: ("Orc Tower", "An external dwelling that provides Orc recruits for Stronghold (HoMM3) armies."),
        4: ("Ogre Fort", "An external dwelling that provides Ogre recruits for Stronghold (HoMM3) armies."),
        5: ("Cliff Nest", "An external dwelling that provides Roc recruits for Stronghold (HoMM3) armies."),
        6: ("Cyclops Cave", "An external dwelling that provides Cyclops recruits for Stronghold (HoMM3) armies."),
        7: ("Behemoth Crag", "An external dwelling that provides Behemoth recruits for Stronghold (HoMM3) armies."),
    }
    barracks_updates: dict[str, str] = {}
    for tier, (name, desc) in dwelling_text.items():
        new_id = f"barracks_{FRACTION_ID}_{tier}"
        barracks_updates[f"{new_id}_name"] = name
        barracks_updates[f"{new_id}_description"] = desc
        barracks_updates[f"{new_id}_narrativeDescription"] = desc
    upsert_text_tokens(
        map_objects_path,
        {
            f"{CITY_ID}_name": "Stronghold Town",
            f"{CITY_ID}_description": "A Stronghold town with the classic HoMM3 creature chain.",
            f"{CITY_ID}_narrativeDescription": (
                "Recruit Goblins, Wolf Riders, Orcs, Ogres, Rocs, Cyclopes, and Behemoths."
            ),
            **barracks_updates,
        },
    )


def upsert_homm3_city_string_tokens_from_dungeon_and_fallbacks(cities_path: Path) -> None:
    """City JSON references Homm3Stronghold_Build_* Lang sids; mirror Dungeon_Build_* + narrative fallbacks."""
    if not CORE.exists():
        return
    with zipfile.ZipFile(CORE, "r") as z:
        raw = z.read(CITY_JSON_PATH).decode("utf-8-sig")
    wanted = set(re.findall(r'"(Homm3Stronghold_[^"]+)"', raw))
    payload = json.loads(cities_path.read_text(encoding="utf-8-sig"))
    tokens = payload.setdefault("tokens", [])
    by_sid = {t["sid"]: t for t in tokens if "sid" in t}
    dungeon_by = {
        t["sid"]: t
        for t in tokens
        if isinstance(t.get("sid"), str) and t["sid"].startswith("Dungeon_Build_")
    }
    added = 0
    for sid in sorted(wanted):
        if sid in by_sid:
            continue
        d_sid = "Dungeon_" + sid[len("Homm3Stronghold_") :]
        text = None
        if d_sid in dungeon_by:
            text = dungeon_by[d_sid].get("text", "")
        elif sid.endswith("_narrativeDescription"):
            base = sid[: -len("_narrativeDescription")]
            for cand in (
                base + "_description",
                base + "_description_level_1",
                base + "_description_level_1_alt",
                base + "_description_level_2",
                base + "_description_level_2_alt",
                base + "_description_level_3",
                base + "_description_level_3_alt",
            ):
                if cand in by_sid:
                    text = by_sid[cand].get("text", "")
                    break
        if text is None:
            text = ""
        tokens.append({"sid": sid, "text": text})
        by_sid[sid] = tokens[-1]
        added += 1
    if added:
        cities_path.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        loc = cities_path.parent.parent.name
        print(f"cities.json ({loc}): added {added} Homm3Stronghold token(s) from Dungeon mirror / fallbacks.")


def patch_interactables_city(all_data: dict) -> None:
    """Adventure map / RMG need an interactable template id matching ObjCityConfig.id."""
    path = "DB/map/objects/4_interactables.json"
    root = json.loads(all_data[path].decode("utf-8-sig"))
    arr = root["array"]
    ids = {o.get("id") for o in arr if isinstance(o, dict)}
    if CITY_ID in ids:
        added_city = False
    else:
        dungeon_entry = next(o for o in arr if isinstance(o, dict) and o.get("id") == "dungeon_city")
        clone = copy.deepcopy(dungeon_entry)
        clone["id"] = CITY_ID
        # Reuse Dungeon map prefab until Stronghold-specific art exists.
        clone["prefs"] = ["interactive/dungeon_city"]
        arr.append(clone)
        ids.add(CITY_ID)
        added_city = True

    added_barracks = 0
    for tier in range(1, 8):
        source_id = f"barracks_dungeon_{tier}"
        new_id = f"barracks_{FRACTION_ID}_{tier}"
        if new_id in ids:
            continue
        dungeon_entry = next(o for o in arr if isinstance(o, dict) and o.get("id") == source_id)
        clone = copy.deepcopy(dungeon_entry)
        clone["id"] = new_id
        # Keep using Dungeon adventure-map prefabs; this row is the missing logical registration.
        arr.append(clone)
        ids.add(new_id)
        added_barracks += 1
    all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")
    if added_city or added_barracks:
        print(f"{path}: added {int(added_city)} city row(s), {added_barracks} barracks row(s).")


def _clone_kv_data_item(data: list, source_key: str, new_key: str) -> None:
    keys = {item["key"] for item in data if isinstance(item, dict) and "key" in item}
    if new_key in keys:
        return
    src = next((x for x in data if isinstance(x, dict) and x.get("key") == source_key), None)
    if src is None:
        return
    dup = copy.deepcopy(src)
    dup["key"] = new_key
    data.append(dup)


def patch_map_object_sounds(all_data: dict) -> None:
    path = "DB/map_objects_sounds.json"
    root = json.loads(all_data[path].decode("utf-8-sig"))
    data = root["objectsArr"]["data"]
    _clone_kv_data_item(data, "dungeon_city", CITY_ID)
    for tier in range(1, 8):
        _clone_kv_data_item(
            data,
            f"barracks_dungeon_{tier}",
            f"barracks_{FRACTION_ID}_{tier}",
        )
    all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")


def patch_city_audio_tables(all_data: dict) -> None:
    """Clone Dungeon city audio under homm3_stronghold; route music to the HoMM3 sidecar sound set."""
    for path, wrapper in (
        ("DB/city_ambient_sounds.json", "array"),
        ("DB/city_music_sounds.json", "array"),
    ):
        root = json.loads(all_data[path].decode("utf-8-sig"))
        data = root[wrapper]["data"]
        _clone_kv_data_item(data, "dungeon", FRACTION_ID)
        if path == "DB/city_music_sounds.json":
            row = next((item for item in data if item.get("key") == FRACTION_ID), None)
            if row is not None:
                row.setdefault("val", {})["soundSetName"] = "sounds/city/music/homm3_stronghold"
        all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")


def remap_hire_unit_sids(obj: object) -> None:
    if isinstance(obj, dict):
        if obj.get("fraction") == "dungeon":
            obj["fraction"] = FRACTION_ID
        for key, value in obj.items():
            if key == "id" and isinstance(value, str) and value.startswith("barracks_dungeon_"):
                obj[key] = value.replace("barracks_dungeon_", f"barracks_{FRACTION_ID}_", 1)
            elif isinstance(value, str) and value in SID_MAP:
                obj[key] = SID_MAP[value]
            else:
                remap_hire_unit_sids(value)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str) and item in SID_MAP:
                obj[i] = SID_MAP[item]
            else:
                remap_hire_unit_sids(item)


def patch_barracks_hires(all_data: dict) -> None:
    """Clone faction-tier external hire rows; city.hires alone is not enough for session startup."""
    path = "DB/objects_logic/hires/barracks.json"
    root = json.loads(all_data[path].decode("utf-8-sig"))
    arr = root.get("array")
    if not isinstance(arr, list):
        raise RuntimeError(f"{path}: expected array list")

    arr[:] = [
        item
        for item in arr
        if not (isinstance(item, dict) and item.get("fraction") == FRACTION_ID)
    ]
    ids = {item.get("id") for item in arr if isinstance(item, dict)}
    added = 0
    for item in list(arr):
        if not isinstance(item, dict) or item.get("fraction") != "dungeon":
            continue
        clone = copy.deepcopy(item)
        remap_hire_unit_sids(clone)
        cid = clone.get("id")
        if not isinstance(cid, str) or cid in ids:
            continue
        arr.append(clone)
        ids.add(cid)
        added += 1

    if added != 7:
        raise RuntimeError(f"{path}: expected to add 7 {FRACTION_ID} barracks rows, added {added}")
    all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")
    print(f"{path}: added {added} {FRACTION_ID} barracks row(s) cloned from dungeon.")


def patch_map_registration(all_data: dict) -> None:
    patch_interactables_city(all_data)
    patch_map_object_sounds(all_data)
    patch_city_audio_tables(all_data)
    patch_barracks_hires(all_data)


def patch_biomes_info_for_stronghold_test(all_data: dict) -> None:
    """Bisect custom-faction startup: make Dirt resolve to homm3_stronghold instead of Dungeon."""
    if not CLAIM_DIRT_BIOME:
        return
    path = "DB/biomes_info.json"
    root = json.loads(all_data[path].decode("utf-8-sig"))
    data = ((root.get("fractionsByBiome") or {}).get("data") or [])
    for row in data:
        if isinstance(row, dict) and row.get("key") == "Dirt":
            row["val"] = FRACTION_ID
            all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")
            print(f"{path}: TEST override Dirt biome faction -> {FRACTION_ID}.")
            return
    raise RuntimeError(f"{path}: could not find Dirt biome row")


M2_M10_BUILDING_JSON_PATHS = (
    "DB/buildings_bans/M10_banlists.json",
    "DB/buildings_bans/M2_banlists.json",
    "DB/buildings_constructions/M10_buildings_presets.json",
    "DB/buildings_constructions/M2_buildings_presets.json",
)


def patch_m2_m10_building_presets_for_stronghold_city(all_data: dict) -> None:
    """M2/M10 banlists and construction presets use row ids *_dungeon_city; mirror rows for homm3_stronghold_city."""
    suffix = "dungeon_city"
    for path in M2_M10_BUILDING_JSON_PATHS:
        if path not in all_data:
            continue
        root = json.loads(all_data[path].decode("utf-8-sig"))
        arr = root.get("array")
        if not isinstance(arr, list):
            continue
        ids = {o.get("id") for o in arr if isinstance(o, dict) and "id" in o}
        added = 0
        for item in list(arr):
            if not isinstance(item, dict):
                continue
            oid = item.get("id")
            if not isinstance(oid, str) or not oid.endswith(suffix):
                continue
            new_id = oid[: -len(suffix)] + CITY_ID
            if new_id in ids:
                continue
            clone = copy.deepcopy(item)
            clone["id"] = new_id
            arr.append(clone)
            ids.add(new_id)
            added += 1
        if added:
            all_data[path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")
            print(f"{path}: added {added} {CITY_ID} row(s) (clone of *_dungeon_city).")


# Shipped Core references this unit id but does not ship DB/units/**/goblin_rogue*.json — breaks lookups during map/session.
_GOBLIN_ROGUE_REF_PATHS = (
    "DB/unit_sets/unit_sets.json",
    "DB/reward_units_container.json",
    "DB/objects_logic/event_banks/campaign_objects/shady_den_campaign.json",
)
_GOBLIN_ROGUE_FALLBACK_UNIT = "halfling"


def _replace_exact_json_strings(obj: object, old: str, new: str) -> tuple[object, int]:
    """Return (new_tree, replacement_count). Only replaces string leaves equal to old."""
    if isinstance(obj, dict):
        out: dict = {}
        n = 0
        for k, v in obj.items():
            v2, c = _replace_exact_json_strings(v, old, new)
            out[k] = v2
            n += c
        return out, n
    if isinstance(obj, list):
        out_list: list = []
        n = 0
        for v in obj:
            v2, c = _replace_exact_json_strings(v, old, new)
            out_list.append(v2)
            n += c
        return out_list, n
    if isinstance(obj, str) and obj == old:
        return new, 1
    return obj, 0


def patch_orphan_goblin_rogue_unit_refs(all_data: dict) -> int:
    """Remap goblin_rogue to halfling in known JSON blobs. Returns total string replacements."""
    total = 0
    for path in _GOBLIN_ROGUE_REF_PATHS:
        if path not in all_data:
            continue
        root = json.loads(all_data[path].decode("utf-8-sig"))
        new_root, n = _replace_exact_json_strings(root, "goblin_rogue", _GOBLIN_ROGUE_FALLBACK_UNIT)
        if n:
            all_data[path] = json.dumps(new_root, ensure_ascii=False, indent="\t").encode("utf-8")
            total += n
    if total:
        print(
            f"Core: remapped goblin_rogue -> {_GOBLIN_ROGUE_FALLBACK_UNIT} ({total} string leaf(es)) in known JSON."
        )
    return total


SQUADS_DUNGEON_PREFIX = "DB/squads/squads_dungeon/"
SQUADS_STRONGHOLD_PREFIX = "DB/squads/squads_homm3_stronghold/"
SQUAD_ID_PREFIX_DUNGEON = "squad_dungeon_"
SQUAD_ID_PREFIX_STRONGHOLD = "squad_homm3_stronghold_"


def morph_squad_json(obj: object, sid_map: dict[str, str]) -> None:
    """Remap dungeon unit SIDs, squad id prefix, and fraction on squad config trees."""
    if isinstance(obj, dict):
        if obj.get("fraction") == "dungeon":
            obj["fraction"] = FRACTION_ID
        iid = obj.get("id")
        if isinstance(iid, str) and iid.startswith(SQUAD_ID_PREFIX_DUNGEON):
            obj["id"] = SQUAD_ID_PREFIX_STRONGHOLD + iid[len(SQUAD_ID_PREFIX_DUNGEON) :]
        for k, v in obj.items():
            if k in ("id", "fraction"):
                continue
            if k == "s" and isinstance(v, str) and v in sid_map:
                obj[k] = sid_map[v]
            else:
                morph_squad_json(v, sid_map)
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            if isinstance(item, str) and item in sid_map:
                obj[i] = sid_map[item]
            else:
                morph_squad_json(item, sid_map)


INFO_SCRIPT_DUNGEON = "DB/info/info_script_unit/units_dungeon.script"
INFO_SCRIPT_STRONGHOLD = "DB/info/info_script_unit/units_homm3_stronghold.script"

def clone_info_script_for_stronghold(all_data: dict) -> None:
    """Clone units_dungeon.script → units_homm3_stronghold.script with SID remapping.
    The info panel parameter-extraction functions (unic_unit_trogl_passive_1, etc.)
    must exist under the new SIDs or the panel renders blank."""
    if INFO_SCRIPT_DUNGEON not in all_data:
        raise SystemExit(f"Info script: {INFO_SCRIPT_DUNGEON} not found in Core.zip; cannot clone {INFO_SCRIPT_STRONGHOLD}.")
    raw = all_data[INFO_SCRIPT_DUNGEON].decode("utf-8-sig")
    # SID_MAP values like trogl→h3_goblin, assassin→h3_wolf_rider, etc.
    for old_base, new_base in BASE_TO_H3.items():
        raw = raw.replace(f"unic_unit_{old_base}_", f"unic_unit_{new_base}_")
    # Also replace the dungeon-specific alt attack reference
    raw = raw.replace("unic_unit_dungeon_alt_attack", "unic_unit_homm3_stronghold_alt_attack")
    all_data[INFO_SCRIPT_STRONGHOLD] = raw.encode("utf-8")
    print(f"Info script: cloned {INFO_SCRIPT_DUNGEON} -> {INFO_SCRIPT_STRONGHOLD} ({len(raw)} bytes).")


def patch_squads_tree_from_dungeon(all_data: dict) -> None:
    """Session looks up DB/squads/squads_{fraction}/ — clone dungeon squads for homm3_stronghold."""
    stale = [k for k in list(all_data.keys()) if k.startswith(SQUADS_STRONGHOLD_PREFIX)]
    for k in stale:
        del all_data[k]

    for old_path, blob in list(all_data.items()):
        if not old_path.startswith(SQUADS_DUNGEON_PREFIX):
            continue
        new_path = SQUADS_STRONGHOLD_PREFIX + old_path[len(SQUADS_DUNGEON_PREFIX) :].replace(
            SQUAD_ID_PREFIX_DUNGEON, SQUAD_ID_PREFIX_STRONGHOLD
        )
        try:
            root = json.loads(blob.decode("utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            all_data[new_path] = blob
            continue
        morph_squad_json(root, SID_MAP)
        all_data[new_path] = json.dumps(root, ensure_ascii=False, indent="\t").encode("utf-8")


def collect_dungeon_city_name_templates(cities_path: Path) -> dict[str, str]:
    eng = json.loads(cities_path.read_text(encoding="utf-8-sig"))
    by_sid = {t["sid"]: t["text"] for t in eng.get("tokens", []) if "sid" in t}
    out: dict[str, str] = {}
    for i in range(1, 21):
        old = f"dungeon_city_name_{i}"
        new = f"{CITY_ID}_name_{i}"
        if old in by_sid:
            out[new] = by_sid[old]
    return out


def main(core_only: bool = False) -> None:
    """core_only: rewrite only the explicit --core archive (no .bak, no loose playtest Lang).
    Used by tools/port_current/rebuild_core_from_vanilla.py to seed a vanilla Core copy."""
    if not CORE.exists():
        raise SystemExit(f"Missing Core.zip: {CORE}")

    backup = CORE.with_suffix(".zip.bak_before_homm3_stronghold_city")
    if not core_only and not backup.exists():
        backup.write_bytes(CORE.read_bytes())

    with zipfile.ZipFile(CORE, "r") as zin:
        entries = {i.filename: i for i in zin.infolist()}
        all_data = {name: zin.read(name) for name in zin.namelist()}

    copy_all_units(all_data)
    patch_stronghold_unit_buffs(all_data)

    city = clone_city_from_dungeon(all_data)
    all_data[CITY_JSON_PATH] = json.dumps(
        {"array": [city]}, ensure_ascii=False, indent="\t"
    ).encode("utf-8")

    laws_out = clone_dungeon_laws(all_data)
    all_data[LAWS_JSON_PATH] = json.dumps(laws_out, ensure_ascii=False, indent="\t").encode(
        "utf-8"
    )

    frac_out = clone_fraction_config(all_data)
    all_data[FRACTION_JSON_PATH] = json.dumps(frac_out, ensure_ascii=False, indent="\t").encode(
        "utf-8"
    )

    data_json = json.loads(all_data["DB/data.json"].decode("utf-8-sig"))
    fr = data_json.setdefault("fractions", [])
    af = data_json.setdefault("availableFractions", [])
    if FRACTION_ID not in fr:
        fr.append(FRACTION_ID)
    if FRACTION_ID not in af:
        af.append(FRACTION_ID)
    all_data["DB/data.json"] = json.dumps(data_json, ensure_ascii=False, indent="\t").encode(
        "utf-8"
    )

    patch_map_registration(all_data)
    patch_biomes_info_for_stronghold_test(all_data)
    patch_m2_m10_building_presets_for_stronghold_city(all_data)
    patch_squads_tree_from_dungeon(all_data)
    patch_orphan_goblin_rogue_unit_refs(all_data)
    clone_info_script_for_stronghold(all_data)

    write_core_zip(entries, all_data)

    if core_only:
        print(f"Patched {CORE} (core-only): units, city, laws, fraction, data.json, map registration, "
              f"squads, M2/M10 presets, info script, unit buffs; loose Lang not touched.")
        return

    patch_localization()

    print(
        f"Patched {CORE}: units under {FRACTION_ID}/, {CITY_JSON_PATH}, laws, "
        f"{FRACTION_JSON_PATH}, data.json, map interactables + map/city audio + barracks hires, "
        f"squads_homm3_stronghold (from squads_dungeon), M2/M10 building banlists+presets for {CITY_ID}, "
        f"goblin_rogue->{_GOBLIN_ROGUE_FALLBACK_UNIT} orphan remap, "
        f"all Lang locales (cities/factionLaws/unitsAbility/unitsBuff/mapObjects), args/factionLaws."
    )
    if backup.exists():
        print(f"Backup: {backup}")


def patch_lang_only() -> None:
    """Refresh Lang files only (no Core.zip rewrite). Use after pulling script updates."""
    patch_localization()
    print("Lang-only patch applied (cities, factionLaws, args, unitsAbility, unitsBuff, mapObjects).")


def orphan_units_only() -> None:
    """Rewrite Core.zip only to remap orphan unit id goblin_rogue (no generator clone pass)."""
    if not CORE.exists():
        raise SystemExit(f"Missing Core.zip: {CORE}")
    with zipfile.ZipFile(CORE, "r") as zin:
        entries = {i.filename: i for i in zin.infolist()}
        all_data = {name: zin.read(name) for name in zin.namelist()}
    patch_orphan_goblin_rogue_unit_refs(all_data)
    write_core_zip(entries, all_data)
    print(f"Updated {CORE} (orphan unit refs only).")


def m2_m10_building_presets_only() -> None:
    """Rewrite Core.zip only: add *_homm3_stronghold_city rows next to *_dungeon_city in M2/M10 JSON."""
    if not CORE.exists():
        raise SystemExit(f"Missing Core.zip: {CORE}")
    with zipfile.ZipFile(CORE, "r") as zin:
        entries = {i.filename: i for i in zin.infolist()}
        all_data = {name: zin.read(name) for name in zin.namelist()}
    patch_m2_m10_building_presets_for_stronghold_city(all_data)
    write_core_zip(entries, all_data)
    print(f"Updated {CORE} (M2/M10 building banlists + construction presets for {CITY_ID} only).")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="HoMM3 Stronghold-style faction -> Core.zip + all Lang locales.")
    ap.add_argument(
        "--lang-only",
        action="store_true",
        help="Only update Lang JSON (cities, laws args, unitsAbility, unitsBuff, mapObjects); do not touch Core.zip.",
    )
    ap.add_argument(
        "--orphan-units-only",
        action="store_true",
        help="Only patch Core.zip goblin_rogue -> halfling references (fast); no faction clone.",
    )
    ap.add_argument(
        "--m2-m10-building-presets-only",
        action="store_true",
        help=f"Only add {CITY_ID} rows to M2/M10 building banlists + construction presets (fast).",
    )
    ap.add_argument(
        "--claim-dirt-biome",
        action="store_true",
        help="Bisect startup death: make biomes_info Dirt map to homm3_stronghold instead of dungeon.",
    )
    ap.add_argument(
        "--core",
        type=Path,
        default=None,
        help="Core.zip to rewrite instead of the playtest Core (required with --core-only).",
    )
    ap.add_argument(
        "--core-only",
        action="store_true",
        help="Rewrite only --core: no .bak beside it and no loose playtest Lang writes.",
    )
    args = ap.parse_args()
    CLAIM_DIRT_BIOME = args.claim_dirt_biome
    if args.core_only and args.core is None:
        ap.error("--core-only requires an explicit --core")
    if args.core_only and (args.lang_only or args.orphan_units_only or args.m2_m10_building_presets_only):
        ap.error("--core-only is a full Core pass; it cannot combine with the *-only modes")
    if args.core is not None:
        if not args.core_only:
            ap.error("--core is only supported with --core-only (other modes also write the playtest Lang)")
        CORE = args.core.resolve()
    if args.core_only:
        main(core_only=True)
    elif args.lang_only:
        patch_lang_only()
    elif args.orphan_units_only:
        orphan_units_only()
    elif args.m2_m10_building_presets_only:
        m2_m10_building_presets_only()
    else:
        main()
