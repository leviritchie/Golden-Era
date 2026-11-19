"""Fortress Predator Instinct (predator/prey pairing) Core overlay rows.

Design (owner, 2026-11-14):
- At the start of each battle, each melee stack of a Fortress hero's army is randomly paired 1-to-1 with an enemy
  stack: its prey. Surplus stacks on either side stay unpaired.
- Hovering a Fortress stack draws a wavy, glowing blood-red line from that predator to its prey.
- Predators deal +33/66/100% damage to their prey (Basic/Advanced/Expert) and, while that prey is alive, 17/33/50% less
  damage to every other target (owner, 2026-11-17: half the bonus; 16.5 rounds to 17). Counterattacks count too.
- Advanced: Swamp Tactics (+10% damage on native terrain), Intimidation (prey hit by its predator gets Ice Bolt's -3 Initiative),
  Endurance Hunting (ranged stacks can be predators too).
- Expert: Frenzy (1-Focus hero action: every predator gains Haste and is taunted by its prey), Cautious (predators
  parry their prey: they retaliate before the prey's attack), Pounce (prey never retaliates against its predator).

Every pairing rule is owned by the plugin runtime (Homm3FortressPredatorInstinctRuntime*.cs). These rows only provide
the native carriers: the faction-skill ranks, the subskill rows, the Frenzy hero ability and the visible
predator/prey marker battle buffs. Swamp Tactics is plain native-terrain data. Proof: generated-artifact only until the
owner tests in game.
"""

from __future__ import annotations

from typing import Any, Callable

FACTION_SID = "homm3_fortress"
SKILL_SID = "skill_faction_homm3_fortress"
SKILL_NAME = "Predator Instinct"
BONUS_PERCENT_BY_RANK = (33, 66, 100)
# Off-prey penalty while the prey lives: half the bonus, 16.5 rounded away from zero (the runtime sums whole percents).
PENALTY_PERCENT_BY_RANK = (17, 33, 50)

# Subskill ids are kept from the retired Hunting Grounds design so saved heroes keep their picks; their meaning changed.
SUBSKILL_SWAMP_TACTICS = "sub_skill_faction_homm3_fortress_swamp_advantage"
SUBSKILL_INTIMIDATION = "sub_skill_faction_homm3_fortress_mire_grip"
SUBSKILL_ENDURANCE_HUNTING = "sub_skill_faction_homm3_fortress_thick_hides"
SUBSKILL_FRENZY = "sub_skill_faction_homm3_fortress_bog_ambush"
SUBSKILL_CAUTIOUS = "sub_skill_faction_homm3_fortress_stagnant_air"
SUBSKILL_POUNCE = "sub_skill_faction_homm3_fortress_poisoned_mire"

SUBSKILLS_BY_LEVEL = {
    2: (SUBSKILL_SWAMP_TACTICS, SUBSKILL_INTIMIDATION, SUBSKILL_ENDURANCE_HUNTING),
    3: (SUBSKILL_FRENZY, SUBSKILL_CAUTIOUS, SUBSKILL_POUNCE),
}

# Native carriers the runtime adds (must match Homm3FortressPredatorInstinctRuntime constants).
INTIMIDATION_SLOW_BUFF_SID = "magic_ice_bolt_effect_0"  # Ice Bolt level 1: -3 Initiative
FRENZY_HASTE_BUFF_SID = "magic_haste_effect_1"  # same Haste carrier as Inferno Rapid Gate
CAUTIOUS_PARRY_BUFF_SID = "magic_masterful_parry_effect_0"  # sequenceEffect counter_before_attack

# Expert subskill hero action.
FRENZY_ABILITY_SID = "skill_faction_homm3_fortress_ability_frenzy"
FRENZY_FOCUS_COST = 1
FRENZY_ICON = "magic_berserker_effect_icon"
FRENZY_CAST_VFX = "magic/Prefabs_vfx/Heroes/hero_demon_hex"

# Visible marker battle buffs (added by the runtime at battle start; infinite, not dispellable).
BATTLE_BUFFS_PATH = "DB/buffs/sub_skills_battle_hero_buffs.json"
PREDATOR_BUFF_PREFIX = "homm3_fortress_predator_"  # + rank 1..3
PREY_BUFF_SID = "homm3_fortress_prey"
PREDATOR_BUFF_ICON = "dragon_hunter_buff_icon"
PREY_BUFF_ICON = "dragon_hunter_blood_icon"

ABILITY_PATH = "DB/heroes_abilities/heroes_abilities_base/hero_abilities.json"
SUBSKILLS_PATH = "DB/heroes_skills/sub_skills/sub_skills.json"
SKILLS_PATH = "DB/heroes_skills/skills/skills.json"

# Retired Hunting Grounds trophy hero buffs (homm3_fortress_trophies_<rank>_<n>). Saved heroes can still carry them,
# so the rows stay defined as hidden no-ops (no enemy penalty) instead of being removed.
RETIRED_HERO_BUFFS_PATH = "DB/heroes_buffs/heroes_buffs.json"
RETIRED_TROPHY_CAPS = {1: 8, 2: 7, 3: 6}
RETIRED_HERO_BUFF_SIDS = tuple(
    f"homm3_fortress_trophies_{level}_{trophies}"
    for level, cap in RETIRED_TROPHY_CAPS.items()
    for trophies in range(1, cap + 1)
)

SKILL_DESC = (
    "At the start of each battle, each melee stack in this hero's army is paired with a random enemy stack: its prey. "
    "Each predator has one prey and each enemy has at most one predator. Hover a stack to see its prey."
)
RANK_DESCS = tuple(
    f"Predators deal +{bonus}% damage to their prey. While its prey lives, a predator deals {penalty}% less damage to other targets."
    for bonus, penalty in zip(BONUS_PERCENT_BY_RANK, PENALTY_PERCENT_BY_RANK)
)

IMPLEMENTED = (
    "Predator Instinct: Homm3FortressPredatorInstinctRuntime pairs Fortress-hero melee stacks 1-to-1 with random enemy "
    "stacks at BattleLogic.Init, adds visible predator/prey marker buffs, scales committed predator-to-prey damage by "
    "+33/66/100% and a predator's damage to other targets by -17/33/50% while its prey lives, inside the single "
    "committed-damage owner (counter hits included), and draws the hover blood line. Subskills: Swamp Tactics "
    "(native-terrain outAllDmgMod data), Intimidation (native Ice Bolt initiative-down on hit), Endurance Hunting (ranged predators), "
    "Frenzy (1-Focus hero action: native Haste + taunt-by-prey), Cautious (native parry vs prey), Pounce (no retaliation "
    "from prey)."
)
SOURCE_DIFFERENCE = (
    "Replaces Hunting Grounds (trophy meter + weekly restock). Subskill rows reuse the Hunting Grounds subskill SIDs so "
    "saved picks still resolve; their effects changed. The native attack forecast does not show the predator bonus."
)


def faction_skill_levels() -> list[list[dict[str, Any]]]:
    # Ranks keep the runtime-owned faction-skill load shape (ignoreFractionsCount), like Dungeon/Factory/Bulwark:
    # native HeroSkill apply needs non-empty bonuses; the predator bonus itself is runtime-owned.
    return [[{"type": "unitBoolStat", "parameters": ["ignoreFractionsCount", "true"]}] for _ in range(3)]


def make_skill_row() -> dict[str, Any]:
    return {
        "id": SKILL_SID,
        "name": f"{SKILL_SID}_name",
        "desc": f"{SKILL_SID}_desc",
        "skillType": "Faction",
        "parametersPerLevel": [
            {
                "icon": SKILL_SID if index == 1 else f"{SKILL_SID}_{index}",
                "name": f"{SKILL_SID}_name_{index}",
                "desc": f"{SKILL_SID}_desc_{index}",
                "bonuses": bonuses,
                "subSkills": list(SUBSKILLS_BY_LEVEL.get(index, ())),
            }
            for index, bonuses in enumerate(faction_skill_levels(), start=1)
        ],
        "xHomm3ImplementedMechanics": IMPLEMENTED,
    }


def make_frenzy_ability() -> dict[str, Any]:
    # Untargeted: instacast + untargetedCast with an all-alive-units fanout, the vanilla-proven warcry shape
    # (skill_faction_homm3_stronghold_ability_moral). eqa.bhnv reads damageDealer.instacast when the ability is
    # selected and queues the cast at once instead of raising ChangeHeroAbility (targeting mode). Mechanics stay empty
    # (no direct-buff payload, so the 0.1.288 Tempo Cry untargetedCast caveat does not apply).
    target = {"targetTags": ["unit"], "castTarget_": "all", "targetCondition_": "alive", "selection": "object"}
    return {
        "id": FRENZY_ABILITY_SID,
        "levels": [
            {
                "aiValue": 0,
                "name": f"{FRENZY_ABILITY_SID}_name",
                "description": f"{FRENZY_ABILITY_SID}_description",
                "icon": FRENZY_ICON,
                "casterEffect": FRENZY_CAST_VFX,
                "attackTimeBefore": 0.3,
                "attackTimeAfter": 0.6,
                "cd": 0,
                "charges": 1,
                "energyLevel": FRENZY_FOCUS_COST,
                "useExpandTooltip": "false",
                "attackType_": "cast",
                "damageDealer": {
                    "tags": ["ability"],
                    "instacast": True,
                    "untargetedCast": True,
                    "multitargetType": "simultaneous",
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
            "Frenzy is a no-op untargeted instacast; Homm3FortressPredatorInstinctRuntime sees the cast (eov.bhav postfix), gives every living "
            "predator native Haste and taunts it toward its prey. The runtime keeps it unavailable while no predator lives."
        ),
    }


def make_battle_buff_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank in (1, 2, 3):
        sid = f"{PREDATOR_BUFF_PREFIX}{rank}"
        rows.append(
            {
                "id": sid,
                "aiValue": 0,
                "aiValuePerDuration": 0,
                "infinite": True,
                "hidden": False,
                "canDispel": False,
                "dontMimic": True,
                "dontTriggerAction": True,
                "keepOnDeath": False,
                "icon": PREDATOR_BUFF_ICON,
                "name_": f"{sid}_name",
                "description_": f"{sid}_description",
                "tags": ["positive", "homm3_fortress_predator"],
                "isPositive": True,
                "addition": "data",
            }
        )
    rows.append(
        {
            "id": PREY_BUFF_SID,
            "aiValue": 0,
            "aiValuePerDuration": 0,
            "infinite": True,
            "hidden": False,
            "canDispel": False,
            "dontMimic": True,
            "dontTriggerAction": True,
            "keepOnDeath": False,
            "icon": PREY_BUFF_ICON,
            "name_": f"{PREY_BUFF_SID}_name",
            "description_": f"{PREY_BUFF_SID}_description",
            "tags": ["negative", "homm3_fortress_prey"],
            "isPositive": False,
            "addition": "data",
        }
    )
    return rows


def make_subskills() -> list[dict[str, Any]]:
    return [
        {
            "id": SUBSKILL_SWAMP_TACTICS,
            "name": f"{SUBSKILL_SWAMP_TACTICS}_name",
            "desc": f"{SUBSKILL_SWAMP_TACTICS}_desc",
            "icon": "sub_skill_faction_nature_1_icon",
            "bonuses": [
                {"type": "unitStat", "biomeType": "native", "fraction": FACTION_SID, "parameters": ["outAllDmgMod", "0.1"]},
            ],
        },
        {
            "id": SUBSKILL_INTIMIDATION,
            "name": f"{SUBSKILL_INTIMIDATION}_name",
            "desc": f"{SUBSKILL_INTIMIDATION}_desc",
            "icon": "sub_skill_faction_dungeon_2_icon",
            "bonuses": [],
        },
        {
            "id": SUBSKILL_ENDURANCE_HUNTING,
            "name": f"{SUBSKILL_ENDURANCE_HUNTING}_name",
            "desc": f"{SUBSKILL_ENDURANCE_HUNTING}_desc",
            "icon": "sub_skill_faction_nature_3_icon",
            "bonuses": [],
        },
        {
            "id": SUBSKILL_FRENZY,
            "name": f"{SUBSKILL_FRENZY}_name",
            "desc": f"{SUBSKILL_FRENZY}_desc",
            "icon": FRENZY_ICON,
            "bonuses": [{"type": "heroBattleAbility", "parameters": [FRENZY_ABILITY_SID, "0"]}],
        },
        {
            "id": SUBSKILL_CAUTIOUS,
            "name": f"{SUBSKILL_CAUTIOUS}_name",
            "desc": f"{SUBSKILL_CAUTIOUS}_desc",
            "icon": "magic_masterful_parry_effect_icon",
            "bonuses": [],
        },
        {
            "id": SUBSKILL_POUNCE,
            "name": f"{SUBSKILL_POUNCE}_name",
            "desc": f"{SUBSKILL_POUNCE}_desc",
            "icon": "sub_skill_assault_2_icon",
            "bonuses": [],
        },
    ]


def make_retired_trophy_hero_buff_rows() -> list[dict[str, Any]]:
    return [
        {
            "id": sid,
            "icon": "skill_faction_homm3_fortress",
            "name": "homm3_fortress_trophies_buff_name",
            "description": "homm3_fortress_trophies_buff_description",
            "additionType": "LeftNew",
            "isPositive": True,
            "hidden": True,
            "isDispellable": True,
            "bonuses": [],
        }
        for sid in RETIRED_HERO_BUFF_SIDS
    ]


def map_object_lang_rows() -> list[dict[str, str]]:
    return [
        {"sid": "homm3_fortress_trophies_buff_name", "text": "Retired Fortress Trophy"},
        {"sid": "homm3_fortress_trophies_buff_description", "text": "Retired. Has no effect."},
    ]


def hero_skill_lang_rows() -> list[dict[str, str]]:
    rows = [
        {"sid": f"{SKILL_SID}_name", "text": SKILL_NAME},
        {"sid": f"{SKILL_SID}_name_1", "text": f"Basic {SKILL_NAME}"},
        {"sid": f"{SKILL_SID}_name_2", "text": f"Advanced {SKILL_NAME}"},
        {"sid": f"{SKILL_SID}_name_3", "text": f"Expert {SKILL_NAME}"},
        {"sid": f"{SKILL_SID}_desc", "text": SKILL_DESC},
    ]
    rows += [{"sid": f"{SKILL_SID}_desc_{index}", "text": text} for index, text in enumerate(RANK_DESCS, start=1)]
    rows += [
        {"sid": f"{FRENZY_ABILITY_SID}_name", "text": "Frenzy"},
        {
            "sid": f"{FRENZY_ABILITY_SID}_description",
            "text": "Spend 1 Focus: every predator gains Haste this round, but is taunted by its prey and must attack it. Click anywhere on the battlefield.",
        },
        {"sid": f"{SUBSKILL_SWAMP_TACTICS}_name", "text": "Swamp Tactics"},
        {"sid": f"{SUBSKILL_SWAMP_TACTICS}_desc", "text": "Fortress creatures on native terrain deal 10% more damage."},
        {"sid": f"{SUBSKILL_INTIMIDATION}_name", "text": "Intimidation"},
        {"sid": f"{SUBSKILL_INTIMIDATION}_desc", "text": "Prey attacked by its predator loses 3 Initiative for 2 rounds (Ice Bolt)."},
        {"sid": f"{SUBSKILL_ENDURANCE_HUNTING}_name", "text": "Endurance Hunting"},
        {"sid": f"{SUBSKILL_ENDURANCE_HUNTING}_desc", "text": "Ranged stacks can also be predators."},
        {"sid": f"{SUBSKILL_FRENZY}_name", "text": "Frenzy"},
        {
            "sid": f"{SUBSKILL_FRENZY}_desc",
            "text": "Gain the Frenzy action: spend 1 Focus to give every predator Haste this round. Frenzied predators are taunted by their prey.",
        },
        {"sid": f"{SUBSKILL_CAUTIOUS}_name", "text": "Cautious"},
        {"sid": f"{SUBSKILL_CAUTIOUS}_desc", "text": "Predators parry their prey: when attacked by their prey, they retaliate before the attack lands."},
        {"sid": f"{SUBSKILL_POUNCE}_name", "text": "Pounce"},
        {"sid": f"{SUBSKILL_POUNCE}_desc", "text": "Prey cannot retaliate against its predator."},
    ]
    return rows


def battle_buff_lang_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for rank, percent, penalty in zip((1, 2, 3), BONUS_PERCENT_BY_RANK, PENALTY_PERCENT_BY_RANK):
        sid = f"{PREDATOR_BUFF_PREFIX}{rank}"
        rows.append({"sid": f"{sid}_name", "text": "Predator"})
        rows.append(
            {
                "sid": f"{sid}_description",
                "text": f"Deals +{percent}% damage to its prey and {penalty}% less damage to other targets while its prey lives. Hover this stack to see its prey.",
            }
        )
    rows.append({"sid": f"{PREY_BUFF_SID}_name", "text": "Hunted"})
    rows.append(
        {
            "sid": f"{PREY_BUFF_SID}_description",
            "text": "A Fortress predator has marked this stack as its prey and deals extra damage to it.",
        }
    )
    return rows


def merge_fortress_predator_instinct_into_overlay(
    *,
    read_doc: Callable[[str], Any],
    write_doc: Callable[[str, Any], None],
    upsert_array_row: Callable[[dict[str, Any], dict[str, Any]], bool],
    remove_array_rows_by_id: Callable[[dict[str, Any], set[str]], bool],
    dedupe_array_rows_by_id: Callable[[dict[str, Any]], bool],
    source_mechanic: dict[str, Any] | None,
    notes: list[str],
) -> None:
    """Merge every Predator Instinct carrier row. Fail closed: the runtime depends on all of them."""

    def edit(path: str, label: str, upserts: list[dict[str, Any]], removals: set[str] | None = None) -> None:
        doc = read_doc(path)
        if not isinstance(doc, dict) or not isinstance(doc.get("array"), list):
            raise RuntimeError(f"malformed homm3_fortress Predator Instinct target {path}")
        changed = remove_array_rows_by_id(doc, removals) if removals else False
        for row in upserts:
            changed = upsert_array_row(doc, row) or changed
        changed = dedupe_array_rows_by_id(doc) or changed
        if changed:
            write_doc(path, doc)
            notes.append(f"merge homm3_fortress Predator Instinct {label}")

    skill_row = make_skill_row()
    if source_mechanic is not None:
        skill_row["xHomm3SourceMechanic"] = source_mechanic.get("id")
        skill_row["xHomm3MechanicsStatus"] = source_mechanic.get("status")
    edit(SKILLS_PATH, "faction skill", [skill_row])
    edit(SUBSKILLS_PATH, "subskills", make_subskills())
    edit(ABILITY_PATH, "Frenzy hero ability", [make_frenzy_ability()])
    edit(BATTLE_BUFFS_PATH, "predator/prey marker buffs", make_battle_buff_rows())
    edit(RETIRED_HERO_BUFFS_PATH, "retired Hunting Grounds trophy buffs (hidden no-op)", make_retired_trophy_hero_buff_rows())
