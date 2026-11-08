#!/usr/bin/env python3
"""Author curated HoMM3 artifact mechanics into homm3_artifact_mechanics.json.

Every catalog sid gets non-empty OE bonus rows and effect-only player text.
Statuses: native_exact | native_substitute.
Player descriptions describe only the resulting effect (no debt/jargon).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "custom_factions" / "artifacts" / "homm3_artifact_catalog.json"
OUT = ROOT / "custom_factions" / "artifacts" / "homm3_artifact_mechanics.json"


def hs(stat: str, value: str | int) -> dict[str, Any]:
    return {"type": "heroStat", "parameters": [stat, str(value)]}


def hsb(stat: str, value: str | int, allegiance: str = "enemy") -> dict[str, Any]:
    return {
        "type": "heroStatBattle",
        "receiverAllegiance": allegiance,
        "parameters": [stat, str(value)],
    }


def us(stat: str, value: str | int, allegiance: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"type": "unitStat", "parameters": [stat, str(value)]}
    if allegiance:
        row["receiverAllegiance"] = allegiance
    else:
        row["receivers"] = []
    return row


def ub(stat: str, value: str = "true") -> dict[str, Any]:
    return {"type": "unitBoolStat", "parameters": [stat, value]}


def side(res: str, value: str | int) -> dict[str, Any]:
    return {"type": "sideRes", "parameters": [res, str(value)]}


def shoot(pct: float) -> list[dict[str, Any]]:
    return [
        {
            "type": "unitStat",
            "parameters": ["modifierSet", "outDmgMods", "shoot_attack", str(pct)],
        },
        {
            "type": "unitStat",
            "parameters": ["modifierSet", "outDmgMods", "range_attack", str(pct)],
        },
    ]


def magic_in(pct: float, allegiance: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "type": "unitStat",
        "parameters": ["modifierSet", "inDmgMods", "magic_damage", str(pct)],
    }
    if allegiance:
        row["receiverAllegiance"] = allegiance
    else:
        row["receivers"] = []
    return row


def magic_out(pct: float) -> dict[str, Any]:
    return {
        "type": "unitStat",
        "receivers": [],
        "parameters": ["modifierSet", "outDmgMods", "magic_damage", str(pct)],
    }


def all_primary(n: int) -> list[dict[str, Any]]:
    return [
        hs("offence", n),
        hs("defence", n),
        hs("spellPower", n),
        hs("intelligence", n),
    ]


def atk_def(n: int) -> list[dict[str, Any]]:
    return [hs("offence", n), hs("defence", n)]


def know_power(n: int) -> list[dict[str, Any]]:
    return [hs("intelligence", n), hs("spellPower", n)]


def entry(
    bonuses: list[dict[str, Any]],
    description: str,
    status: str = "native_exact",
    notes: str = "",
) -> dict[str, Any]:
    if not bonuses:
        raise ValueError("bonuses must be non-empty")
    row: dict[str, Any] = {
        "bonuses": bonuses,
        "description": description.strip(),
        "mechanicsStatus": status,
    }
    if notes:
        row["notes"] = notes
    return row


def build_table(catalog_sids: list[str]) -> dict[str, dict[str, Any]]:
    """Explicit mechanics for every known artifact sid."""
    t: dict[str, dict[str, Any]] = {}

    # --- System / former war-machine / blocked-family substitutes ---
    t["homm3_artifact_000_spell_book"] = entry(
        [hs("manaBonusPercent", "0.15"), hs("magicUsageLimitBonus", "1")],
        "Increases your mana reserve by 15% and lets you cast one additional spell each round.",
        "native_substitute",
        "Spell Book UI not OE; mana/cast capacity stand-in.",
    )
    t["homm3_artifact_001_spell_scroll"] = entry(
        [hs("manaRestoreBonus", "2"), hs("magicAttackPerBonus", "0.05")],
        "Restores 2 extra mana each day and increases your spell damage by 5%.",
        "native_substitute",
        "Dynamic scroll spell grant not OE; mana + spell pressure stand-in.",
    )
    t["homm3_artifact_002_the_grail"] = entry(
        [side("gold", 5000), hs("moral", 2), hs("luck", 2)],
        "Provides 5000 gold per day and +2 Morale and Luck.",
        "native_substitute",
        "Grail town structure claim not OE.",
    )
    t["homm3_artifact_003_catapult"] = entry(
        [
            {
                "type": "unitStat",
                "parameters": ["modifierSet", "outDmgMods", "basic_attack", "0.10"],
            },
            hs("offence", 2),
        ],
        "Increases your Attack by +2 and your army's basic attack damage by 10%.",
        "native_substitute",
        "No siege war-machine path.",
    )
    t["homm3_artifact_004_ballista"] = entry(
        shoot(0.15) + [hs("offence", 1)],
        "Increases your Attack by +1 and your army's ranged and shooting damage by 15%.",
        "native_substitute",
        "No Ballista war-machine path.",
    )
    t["homm3_artifact_005_ammo_cart"] = entry(
        shoot(0.10),
        "Increases your army's ranged and shooting damage by 10%.",
        "native_substitute",
        "No ammo/war-machine path.",
    )
    t["homm3_artifact_006_first_aid_tent"] = entry(
        [us("hp", 2), us("inComingBuffDuration", 1)],
        "Increases the health of all your units by +2 and extends beneficial effects on them by 1.",
        "native_substitute",
        "No First Aid Tent war-machine path.",
    )
    t["homm3_artifact_145_cannon"] = entry(
        shoot(0.20) + [hs("offence", 3)],
        "Increases your Attack by +3 and your army's ranged and shooting damage by 20%.",
        "native_substitute",
        "No Cannon war-machine path.",
    )

    # --- Simple Attack weapons (fix duplicate + tradeoffs) ---
    for sid, atk, desc in [
        ("homm3_artifact_007_centaurs_axe", 2, "Increases your Attack skill by +2."),
        ("homm3_artifact_008_blackshard_of_the_dead_knight", 3, "Increases your Attack skill by +3."),
        ("homm3_artifact_009_greater_gnolls_flail", 4, "Increases your Attack skill by +4."),
        ("homm3_artifact_010_ogres_club_of_havoc", 5, "Increases your Attack skill by +5."),
        ("homm3_artifact_011_sword_of_hellfire", 6, "Increases your Attack skill by +6."),
        ("homm3_artifact_147_trident_of_dominion", 7, "Increases your Attack skill by +7."),
    ]:
        t[sid] = entry([hs("offence", atk)], desc)

    t["homm3_artifact_012_titans_gladius"] = entry(
        [hs("offence", 12), hs("defence", -3)],
        "Increases your Attack skill by +12, but reduces your Defense skill by 3.",
    )

    # --- Defense shields ---
    for sid, val, desc in [
        ("homm3_artifact_013_shield_of_the_dwarven_lords", 2, "Increases your Defense skill by +2."),
        ("homm3_artifact_014_shield_of_the_yawning_dead", 3, "Increases your Defense skill by +3."),
        ("homm3_artifact_015_buckler_of_the_gnoll_king", 4, "Increases your Defense skill by +4."),
        ("homm3_artifact_016_targ_of_the_rampaging_ogre", 5, "Increases your Defense skill by +5."),
        ("homm3_artifact_017_shield_of_the_damned", 6, "Increases your Defense skill by +6."),
        ("homm3_artifact_148_shield_of_naval_glory", 7, "Increases your Defense skill by +7."),
    ]:
        t[sid] = entry([hs("defence", val)], desc)

    t["homm3_artifact_018_sentinels_shield"] = entry(
        [hs("defence", 12), hs("offence", -3)],
        "Increases your Defense skill by +12, but reduces your Attack skill by 3.",
    )

    # --- Knowledge helms ---
    for sid, val, desc in [
        ("homm3_artifact_019_helm_of_the_alabaster_unicorn", 1, "Increases your Knowledge skill by +1."),
        ("homm3_artifact_020_skull_helmet", 2, "Increases your Knowledge skill by +2."),
        ("homm3_artifact_021_helm_of_chaos", 3, "Increases your Knowledge skill by +3."),
        ("homm3_artifact_022_crown_of_the_supreme_magi", 4, "Increases your Knowledge skill by +4."),
        ("homm3_artifact_023_hellstorm_helmet", 5, "Increases your Knowledge skill by +5."),
        ("homm3_artifact_150_crown_of_the_five_seas", 6, "Increases your Knowledge skill by +6."),
    ]:
        t[sid] = entry([hs("intelligence", val)], desc)

    t["homm3_artifact_024_thunder_helmet"] = entry(
        [hs("intelligence", 10), hs("spellPower", -2)],
        "Increases your Knowledge skill by +10, but reduces your Power skill by 2.",
    )

    # --- Power armor ---
    for sid, val, desc in [
        ("homm3_artifact_025_breastplate_of_petrified_wood", 1, "Increases your Power skill by +1."),
        ("homm3_artifact_026_rib_cage", 2, "Increases your Power skill by +2."),
        ("homm3_artifact_027_scales_of_the_greater_basilisk", 3, "Increases your Power skill by +3."),
        ("homm3_artifact_028_tunic_of_the_cyclops_king", 4, "Increases your Power skill by +4."),
        ("homm3_artifact_029_breastplate_of_brimstone", 5, "Increases your Power skill by +5."),
        ("homm3_artifact_149_royal_armor_of_nix", 6, "Increases your Power skill by +6."),
    ]:
        t[sid] = entry([hs("spellPower", val)], desc)

    t["homm3_artifact_030_titans_cuirass"] = entry(
        [hs("spellPower", 10), hs("intelligence", -2)],
        "Increases your Power skill by +10, but reduces your Knowledge skill by 2.",
    )

    # --- Angelic Alliance primary-all ---
    for sid, n in [
        ("homm3_artifact_031_armor_of_wonder", 1),
        ("homm3_artifact_032_sandals_of_the_saint", 2),
        ("homm3_artifact_033_celestial_necklace_of_bliss", 3),
        ("homm3_artifact_034_lions_shield_of_courage", 4),
        ("homm3_artifact_035_sword_of_judgement", 5),
        ("homm3_artifact_036_helm_of_heavenly_enlightenment", 6),
    ]:
        t[sid] = entry(
            all_primary(n),
            f"Increases all four primary skills by +{n}.",
        )

    # --- Dragon Father pairs ---
    for sid, n, kind in [
        ("homm3_artifact_037_quiet_eye_of_the_dragon", 1, "atk"),
        ("homm3_artifact_038_red_dragon_flame_tongue", 2, "atk"),
        ("homm3_artifact_039_dragon_scale_shield", 3, "atk"),
        ("homm3_artifact_040_dragon_scale_armor", 4, "atk"),
        ("homm3_artifact_041_dragonbone_greaves", 1, "kp"),
        ("homm3_artifact_042_dragon_wing_tabard", 2, "kp"),
        ("homm3_artifact_043_necklace_of_dragonteeth", 3, "kp"),
        ("homm3_artifact_044_crown_of_dragontooth", 4, "kp"),
    ]:
        if kind == "atk":
            t[sid] = entry(atk_def(n), f"Increases your Attack and Defense skills by +{n}.")
        else:
            t[sid] = entry(
                know_power(n),
                f"Increases your Knowledge and Power skills by +{n}.",
            )

    t["homm3_artifact_045_still_eye_of_the_dragon"] = entry(
        [hs("luck", 1), hs("moral", 1)],
        "Increases your Luck and Morale by +1.",
    )

    # --- Luck / Morale commons ---
    for sid, desc in [
        ("homm3_artifact_046_clover_of_fortune", "Increases your Luck by +1."),
        ("homm3_artifact_047_cards_of_prophecy", "Increases your Luck by +1."),
        ("homm3_artifact_048_ladybird_of_luck", "Increases your Luck by +1."),
    ]:
        t[sid] = entry([hs("luck", 1)], desc)
    for sid, desc in [
        ("homm3_artifact_049_badge_of_courage", "Increases your Morale by +1."),
        ("homm3_artifact_050_crest_of_valor", "Increases your Morale by +1."),
        ("homm3_artifact_051_glyph_of_gallantry", "Increases your Morale by +1."),
    ]:
        t[sid] = entry([hs("moral", 1)], desc)

    t["homm3_artifact_108_pendant_of_courage"] = entry(
        [hs("luck", 3), hs("moral", 3)],
        "Increases your Luck and Morale by +3.",
    )

    # --- Scouting ---
    t["homm3_artifact_052_speculum"] = entry(
        [hs("viewRadius", 1)], "Increases your scouting radius by +1."
    )
    t["homm3_artifact_053_spyglass"] = entry(
        [hs("viewRadius", 1)], "Increases your scouting radius by +1."
    )

    # --- Necromancy substitutes ---
    t["homm3_artifact_054_amulet_of_the_undertaker"] = entry(
        [us("hp", 1), hs("spellPower", 1)],
        "Increases the health of all your units by +1 and your Power skill by +1.",
        "native_substitute",
        "No Necromancy% donor.",
    )
    t["homm3_artifact_055_vampires_cowl"] = entry(
        [us("hp", 2), hs("spellPower", 1)],
        "Increases the health of all your units by +2 and your Power skill by +1.",
        "native_substitute",
    )
    t["homm3_artifact_056_dead_mans_boots"] = entry(
        [us("hp", 3), hs("spellPower", 2)],
        "Increases the health of all your units by +3 and your Power skill by +2.",
        "native_substitute",
    )

    # --- Magic resistance ---
    t["homm3_artifact_057_garniture_of_interference"] = entry(
        [magic_in(-0.05)],
        "Reduces magic damage taken by your army by 5%.",
    )
    t["homm3_artifact_058_surcoat_of_counterpoise"] = entry(
        [magic_in(-0.10)],
        "Reduces magic damage taken by your army by 10%.",
    )
    t["homm3_artifact_059_boots_of_polarity"] = entry(
        [magic_in(-0.15)],
        "Reduces magic damage taken by your army by 15%.",
    )
    t["homm3_artifact_143_pendant_of_reflection"] = entry(
        [magic_in(-0.20)],
        "Reduces magic damage taken by your army by 20%.",
    )

    # --- Archery ---
    t["homm3_artifact_060_bow_of_elven_cherrywood"] = entry(
        shoot(0.05), "Increases your army's ranged and shooting damage by 5%."
    )
    t["homm3_artifact_061_bowstring_of_the_unicorns_mane"] = entry(
        shoot(0.10), "Increases your army's ranged and shooting damage by 10%."
    )
    t["homm3_artifact_062_angel_feather_arrows"] = entry(
        shoot(0.15), "Increases your army's ranged and shooting damage by 15%."
    )
    t["homm3_artifact_9816_great_battle_bow"] = entry(
        shoot(0.15), "Increases your army's ranged and shooting damage by 15%."
    )
    t["homm3_artifact_091_golden_bow"] = entry(
        shoot(0.25) + [hs("offence", 2)],
        "Increases your Attack by +2 and your army's ranged and shooting damage by 25%.",
        "native_substitute",
        "No obstacle/range-penalty rule donor.",
    )

    # --- Eagle Eye substitutes ---
    t["homm3_artifact_063_bird_of_perception"] = entry(
        [hs("magicAttackPerBonus", "0.05"), hs("viewRadius", 1)],
        "Increases your spell damage by 5% and your scouting radius by +1.",
        "native_substitute",
    )
    t["homm3_artifact_064_stoic_watchman"] = entry(
        [hs("magicAttackPerBonus", "0.10"), hs("viewRadius", 1)],
        "Increases your spell damage by 10% and your scouting radius by +1.",
        "native_substitute",
    )
    t["homm3_artifact_065_emblem_of_cognizance"] = entry(
        [hs("magicAttackPerBonus", "0.15"), hs("viewRadius", 1)],
        "Increases your spell damage by 15% and your scouting radius by +1.",
        "native_substitute",
    )

    # --- Diplomacy ---
    t["homm3_artifact_066_statesmans_medal"] = entry(
        [hs("diplomacyEfficiencyPerBonus", "0.10")],
        "Improves your diplomacy efficiency by 10%.",
    )
    t["homm3_artifact_067_diplomats_ring"] = entry(
        [hs("diplomacyEfficiencyPerBonus", "0.10")],
        "Improves your diplomacy efficiency by 10%.",
    )
    t["homm3_artifact_068_ambassadors_sash"] = entry(
        [hs("diplomacyEfficiencyPerBonus", "0.10")],
        "Improves your diplomacy efficiency by 10%.",
    )
    t["homm3_artifact_142_diplomats_cloak"] = entry(
        [
            hs("diplomacyEfficiencyPerBonus", "0.30"),
            hs("diplomacyCostPerBonus", "-0.5"),
        ],
        "Improves your diplomacy efficiency by 30% and greatly reduces diplomacy costs.",
    )

    # --- Movement ---
    t["homm3_artifact_069_ring_of_the_wayfarer"] = entry(
        [us("speed", 1)],
        "Increases the combat speed of all your units by +1.",
    )
    t["homm3_artifact_070_equestrians_gloves"] = entry(
        [hs("movementBonus", 20)],
        "Increases your land movement by 20.",
    )
    t["homm3_artifact_098_boots_of_speed"] = entry(
        [hs("movementBonus", 30)],
        "Increases your land movement by 30.",
    )
    t["homm3_artifact_071_necklace_of_ocean_guidance"] = entry(
        [hs("movementBonus", 25), hs("viewRadius", 1)],
        "Increases your land movement by 25 and your scouting radius by +1.",
        "native_substitute",
        "No sea movement path.",
    )
    t["homm3_artifact_090_boots_of_levitation"] = entry(
        [hs("movementBonus", 20), hs("landscapePenaltyPerBonus", "-0.5")],
        "Increases your land movement by 20 and reduces terrain movement penalties.",
        "native_substitute",
        "No water-walk path.",
    )
    t["homm3_artifact_123_sea_captains_hat"] = entry(
        [hs("movementBonus", 30), hs("viewRadius", 2), hs("luck", 1)],
        "Increases your land movement by 30, your scouting radius by +2, and your Luck by +1.",
        "native_substitute",
        "No sea/boat path.",
    )
    t["homm3_artifact_151_wayfarers_boots"] = entry(
        [hs("landscapePenaltyPerBonus", "-1")],
        "Removes movement penalties on rough terrain.",
    )
    t["homm3_artifact_072_angel_wings"] = entry(
        [hs("flyMotionPerBonus", "0")],
        "Allows your hero to fly on the adventure map.",
    )

    # --- Mana restore ---
    t["homm3_artifact_073_charm_of_mana"] = entry(
        [hs("manaRestoreBonus", 1)], "Restores 1 extra mana each day."
    )
    t["homm3_artifact_074_talisman_of_mana"] = entry(
        [hs("manaRestoreBonus", 2)], "Restores 2 extra mana each day."
    )
    t["homm3_artifact_075_mystic_orb_of_mana"] = entry(
        [hs("manaRestoreBonus", 3)], "Restores 3 extra mana each day."
    )

    # --- Spell duration ---
    t["homm3_artifact_076_collar_of_conjuring"] = entry(
        [hs("outComingBuffDuration", 1), hs("outComingDebuffDuration", 1)],
        "Increases the duration of your spells by 1.",
    )
    t["homm3_artifact_077_ring_of_conjuring"] = entry(
        [hs("outComingBuffDuration", 2), hs("outComingDebuffDuration", 2)],
        "Increases the duration of your spells by 2.",
    )
    t["homm3_artifact_078_cape_of_conjuring"] = entry(
        [hs("outComingBuffDuration", 3), hs("outComingDebuffDuration", 3)],
        "Increases the duration of your spells by 3.",
    )

    # --- Element orbs -> OE schools ---
    def school_set(school: str) -> dict[str, Any]:
        return {"type": "heroStat", "parameters": ["magicSchoolSet", school, "0", "1"]}

    t["homm3_artifact_079_orb_of_the_firmament"] = entry(
        [magic_out(0.50), school_set("day")],
        "Increases your magic damage by 50% and strengthens Day Magic.",
        "native_substitute",
        "H3 Air -> OE Day Magic.",
    )
    t["homm3_artifact_080_orb_of_silt"] = entry(
        [magic_out(0.50), school_set("primal")],
        "Increases your magic damage by 50% and strengthens Primal Magic.",
        "native_substitute",
        "H3 Earth -> OE Primal Magic.",
    )
    t["homm3_artifact_081_orb_of_tempestuous_fire"] = entry(
        [magic_out(0.50), school_set("night")],
        "Increases your magic damage by 50% and strengthens Night Magic.",
        "native_substitute",
        "H3 Fire -> OE Night Magic.",
    )
    t["homm3_artifact_082_orb_of_driving_rain"] = entry(
        [magic_out(0.50), school_set("space")],
        "Increases your magic damage by 50% and strengthens Space Magic.",
        "native_substitute",
        "H3 Water -> OE Space Magic.",
    )

    # --- Spell rank gates / bans ---
    t["homm3_artifact_083_recanters_cloak"] = entry(
        [
            hs("minAllowedMagicRank", 3),
            hsb("minAllowedMagicRank", 3, "all"),
        ],
        "Neither you nor your opponent may cast high-rank spells in combat.",
        "native_substitute",
    )
    t["homm3_artifact_159_cape_of_silence"] = entry(
        [
            hs("minAllowedMagicRank", 2),
            hsb("minAllowedMagicRank", 2, "all"),
        ],
        "Neither you nor your opponent may cast low-rank spells in combat.",
        "native_substitute",
    )
    t["homm3_artifact_126_orb_of_inhibition"] = entry(
        [
            {"type": "heroStat", "parameters": ["magicCounterSet", "day", "0", "true", "false", "0"]},
            {"type": "heroStat", "parameters": ["magicCounterSet", "night", "0", "true", "false", "0"]},
            {"type": "heroStat", "parameters": ["magicCounterSet", "primal", "0", "true", "false", "0"]},
            {"type": "heroStat", "parameters": ["magicCounterSet", "space", "0", "true", "false", "0"]},
        ],
        "Prevents all spell casting in combat.",
        "native_substitute",
    )

    # --- Morale / luck negation substitutes ---
    t["homm3_artifact_084_spirit_of_oppression"] = entry(
        [us("moral", -2, "enemy"), hs("moral", -1)],
        "Reduces enemy Morale by 2 and your Morale by 1.",
        "native_substitute",
    )
    t["homm3_artifact_085_hourglass_of_the_evil_hour"] = entry(
        [us("luck", -2, "enemy"), hs("luck", -1)],
        "Reduces enemy Luck by 2 and your Luck by 1.",
        "native_substitute",
    )

    # --- Tomes -> OE school mass grants ---
    t["homm3_artifact_086_tome_of_fire_magic"] = entry(
        [{"type": "heroMagicAdditionMass", "parameters": ["night", "any", "any"]}],
        "Grants all Night Magic spells while equipped.",
        "native_substitute",
        "H3 Fire -> OE Night.",
    )
    t["homm3_artifact_087_tome_of_air_magic"] = entry(
        [{"type": "heroMagicAdditionMass", "parameters": ["day", "any", "any"]}],
        "Grants all Day Magic spells while equipped.",
        "native_substitute",
        "H3 Air -> OE Day.",
    )
    t["homm3_artifact_088_tome_of_water_magic"] = entry(
        [{"type": "heroMagicAdditionMass", "parameters": ["space", "any", "any"]}],
        "Grants all Space Magic spells while equipped.",
        "native_substitute",
        "H3 Water -> OE Space.",
    )
    t["homm3_artifact_089_tome_of_earth_magic"] = entry(
        [{"type": "heroMagicAdditionMass", "parameters": ["primal", "any", "any"]}],
        "Grants all Primal Magic spells while equipped.",
        "native_substitute",
        "H3 Earth -> OE Primal.",
    )

    t["homm3_artifact_124_spellbinders_hat"] = entry(
        [{"type": "heroMagicAdditionMass", "parameters": ["any", "any", "5"]}],
        "Grants all rank-5 spells while equipped.",
    )

    # --- Permanence / vulnerability / immunities ---
    t["homm3_artifact_092_sphere_of_permanence"] = entry(
        [ub("immuneToDebuffs"), ub("enableImmuneDebufInMap")],
        "Your units become immune to debuffs.",
        "native_substitute",
    )
    t["homm3_artifact_093_orb_of_vulnerability"] = entry(
        [magic_in(0.25, "all")],
        "All creatures on the battlefield take 25% more magic damage.",
        "native_substitute",
    )
    t["homm3_artifact_165_sleepkeeper"] = entry(
        [ub("immuneToDebuffs")],
        "Your units become immune to debuffs.",
        "native_substitute",
        "Mind-spell immunity approximated as debuff immunity.",
    )

    # Pendants: each gets magic resist slice (honest substitute for single-spell immunity)
    pendant_specs = [
        ("homm3_artifact_100_pendant_of_dispassion", "Reduces magic damage taken by your army by 8%."),
        ("homm3_artifact_101_pendant_of_second_sight", "Reduces magic damage taken by your army by 8%."),
        ("homm3_artifact_102_pendant_of_holiness", "Reduces magic damage taken by your army by 8%."),
        ("homm3_artifact_103_pendant_of_life", "Reduces magic damage taken by your army by 8%."),
        ("homm3_artifact_104_pendant_of_death", "Reduces magic damage taken by your army by 8%."),
        ("homm3_artifact_105_pendant_of_free_will", "Reduces magic damage taken by your army by 8%."),
        ("homm3_artifact_106_pendant_of_negativity", "Reduces magic damage taken by your army by 10%."),
        ("homm3_artifact_107_pendant_of_total_recall", "Reduces magic damage taken by your army by 8%."),
    ]
    for sid, desc in pendant_specs:
        pct = -0.10 if "negativity" in sid else -0.08
        t[sid] = entry(
            [magic_in(pct)],
            desc,
            "native_substitute",
            "Per-spell immunity not OE; magic damage reduction stand-in.",
        )

    # --- Unit health ---
    t["homm3_artifact_094_ring_of_vitality"] = entry(
        [us("hp", 1)], "Increases the health of all your units by +1."
    )
    t["homm3_artifact_095_ring_of_life"] = entry(
        [us("hp", 1)], "Increases the health of all your units by +1."
    )
    t["homm3_artifact_096_vial_of_lifeblood"] = entry(
        [us("hp", 2)], "Increases the health of all your units by +2."
    )

    # --- Speed ---
    t["homm3_artifact_097_necklace_of_swiftness"] = entry(
        [us("speed", 1)], "Increases the combat speed of all your units by +1."
    )
    t["homm3_artifact_099_cape_of_velocity"] = entry(
        [us("speed", 2)], "Increases the combat speed of all your units by +2."
    )

    # --- Resource income ---
    t["homm3_artifact_109_everflowing_crystal_cloak"] = entry(
        [side("crystals", 1)], "Provides +1 crystal per day."
    )
    t["homm3_artifact_110_ring_of_infinite_gems"] = entry(
        [side("gemstones", 1)], "Provides +1 gemstone per day."
    )
    t["homm3_artifact_111_everpouring_vial_of_mercury"] = entry(
        [side("mercury", 1)], "Provides +1 mercury per day."
    )
    t["homm3_artifact_112_inexhaustible_cart_of_ore"] = entry(
        [side("stone", 1)], "Provides +1 stone per day."
    )
    t["homm3_artifact_113_eversmoking_ring_of_sulfur"] = entry(
        [side("sulfur", 1)], "Provides +1 sulfur per day."
    )
    t["homm3_artifact_114_inexhaustible_cart_of_lumber"] = entry(
        [side("wood", 1)], "Provides +1 wood per day."
    )
    t["homm3_artifact_115_endless_sack_of_gold"] = entry(
        [side("gold", 1000)], "Provides 1000 gold per day."
    )
    t["homm3_artifact_116_endless_bag_of_gold"] = entry(
        [side("gold", 750)], "Provides 750 gold per day."
    )
    t["homm3_artifact_117_endless_purse_of_gold"] = entry(
        [side("gold", 500)], "Provides 500 gold per day."
    )
    t["homm3_artifact_160_golden_goose"] = entry(
        [side("gold", 4750)], "Provides 4750 gold per day."
    )

    # --- Legion growth ---
    for sid, frac, label in [
        ("homm3_artifact_118_legs_of_legion", 0.08, "8%"),
        ("homm3_artifact_119_loins_of_legion", 0.07, "7%"),
        ("homm3_artifact_120_torso_of_legion", 0.06, "6%"),
        ("homm3_artifact_121_arms_of_legion", 0.05, "5%"),
        ("homm3_artifact_122_head_of_legion", 0.04, "4%"),
    ]:
        t[sid] = entry(
            [{"type": "cityUnitsIncrementPer", "parameters": ["all", str(frac)]}],
            f"Increases creature growth in the garrisoned town by {label}.",
            "native_substitute",
            "Per-tier growth not OE; all-tier percentage stand-in.",
        )

    # --- Shackles ---
    t["homm3_artifact_125_shackles_of_war"] = entry(
        [
            {
                "type": "heroStatBattle",
                "receiverAllegiance": "all",
                "parameters": ["enableBattleEscapeBan", "true"],
            }
        ],
        "Neither you nor your opponent may retreat or surrender in combat.",
    )

    # --- AB / Dragon Blood ---
    t["homm3_artifact_127_vial_of_dragon_blood"] = entry(
        all_primary(3) + [us("hp", 2)],
        "Increases all four primary skills by +3 and the health of all your units by +2.",
        "native_substitute",
        "Town-claim effect not OE.",
    )
    t["homm3_artifact_128_armageddons_blade"] = entry(
        [
            hs("offence", 12),
            hs("defence", 12),
            hs("spellPower", 12),
            hs("intelligence", 6),
            {"type": "heroMagicAdditionMass", "parameters": ["night", "any", "any"]},
            magic_out(0.25),
        ],
        "Increases Attack, Defense, and Power by +12, Knowledge by +6, increases magic damage by 25%, and grants all Night Magic spells.",
        "native_substitute",
    )

    # --- Ironfist ---
    t["homm3_artifact_144_ironfist_of_the_ogre"] = entry(
        [
            hs("offence", 5),
            hs("defence", 5),
            hs("spellPower", 4),
            hs("intelligence", 4),
            hs("moral", 1),
        ],
        "Increases Attack and Defense by +5, Power and Knowledge by +4, and Morale by +1.",
        "native_substitute",
        "Battle-start expert casts omitted; stats only.",
    )

    # --- Ring of Oblivion ---
    t["homm3_artifact_158_ring_of_oblivion"] = entry(
        [
            us("hp", -1, "enemy"),
            {
                "type": "unitStat",
                "receiverAllegiance": "enemy",
                "parameters": ["modifierSet", "inDmgMods", "basic_attack", "0.10"],
            },
        ],
        "Enemy units have 1 less health and take 10% more basic attack damage.",
        "native_substitute",
        "Irrevocable-loss rule not OE.",
    )

    # --- HotA enemy luck/morale ---
    t["homm3_artifact_152_runes_of_imminency"] = entry(
        [us("luck", -1, "enemy")], "Decreases enemy Luck by 1."
    )
    t["homm3_artifact_153_demons_horseshoe"] = entry(
        [us("luck", -1, "enemy")], "Decreases enemy Luck by 1."
    )
    t["homm3_artifact_154_shamans_puppet"] = entry(
        [us("luck", -2, "enemy")], "Decreases enemy Luck by 2."
    )
    t["homm3_artifact_155_hideous_mask"] = entry(
        [us("moral", -1, "enemy")], "Decreases enemy Morale by 1."
    )
    t["homm3_artifact_156_ring_of_suppression"] = entry(
        [us("moral", -1, "enemy")], "Decreases enemy Morale by 1."
    )
    t["homm3_artifact_157_pendant_of_downfall"] = entry(
        [us("moral", -2, "enemy")], "Decreases enemy Morale by 2."
    )

    # --- Enemy power reduction (fix wrong self-targeting) ---
    t["homm3_artifact_162_charm_of_eclipse"] = entry(
        [hsb("spellPowerPer", "-0.10")],
        "Reduces the enemy hero's Power skill by 10% during combat.",
    )
    t["homm3_artifact_163_seal_of_sunset"] = entry(
        [hsb("spellPowerPer", "-0.10")],
        "Reduces the enemy hero's Power skill by 10% during combat.",
    )
    t["homm3_artifact_164_plate_of_dying_light"] = entry(
        [hsb("spellPowerPer", "-0.25")],
        "Reduces the enemy hero's Power skill by 25% during combat.",
    )

    # --- Partial HotA leftovers ---
    t["homm3_artifact_9025_great_woe_of_the_crawlers"] = entry(
        all_primary(3) + [us("speed", 2)],
        "Increases all four primary skills by +3 and the combat speed of all your units by +2.",
    )
    t["homm3_artifact_9145_fang_of_the_last_scream"] = entry(
        [hs("offence", 5), us("hp", 1)],
        "Increases your Attack skill by +5 and the health of all your units by +1.",
        "native_substitute",
        "Bloodlust specialty omitted.",
    )
    t["homm3_artifact_9747_hollow_eye"] = entry(
        [hs("viewRadius", 2), ub("immuneToDebuffs")],
        "Increases your scouting radius by +2 and makes your units immune to debuffs.",
        "native_substitute",
    )

    # Validate coverage
    missing = [s for s in catalog_sids if s not in t]
    if missing:
        raise RuntimeError(f"mechanics table missing {len(missing)} sids: {missing[:20]}")
    extra = [s for s in t if s not in catalog_sids]
    if extra:
        raise RuntimeError(f"mechanics table has unknown sids: {extra[:20]}")
    for sid, row in t.items():
        if not row.get("bonuses"):
            raise RuntimeError(f"{sid}: empty bonuses")
        if row["mechanicsStatus"] not in {"native_exact", "native_substitute"}:
            raise RuntimeError(f"{sid}: bad status {row['mechanicsStatus']}")
        if not (row.get("description") or "").strip():
            raise RuntimeError(f"{sid}: empty description")
    return t


def main() -> int:
    if not CATALOG.is_file():
        print(f"missing catalog {CATALOG}", file=sys.stderr)
        return 1
    arts = json.loads(CATALOG.read_text(encoding="utf-8")).get("artifacts") or []
    sids = [a["sid"] for a in arts if isinstance(a.get("sid"), str)]
    table = build_table(sids)
    payload = {
        "version": 1,
        "policy": "homm3_artifact_mechanics_curated_v1",
        "proofBoundary": "generated_artifact_validated_runtime_unvalidated",
        "counts": {
            "total": len(table),
            "native_exact": sum(
                1 for r in table.values() if r["mechanicsStatus"] == "native_exact"
            ),
            "native_substitute": sum(
                1 for r in table.values() if r["mechanicsStatus"] == "native_substitute"
            ),
        },
        "artifacts": table,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"wrote {OUT} total={payload['counts']['total']} "
        f"exact={payload['counts']['native_exact']} "
        f"substitute={payload['counts']['native_substitute']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
