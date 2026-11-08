#!/usr/bin/env python3
"""HoMM3 spell id → Olden magic SID by combat/adventure mechanics (not names).

Used for campaign SPELL_SCROLL → ``magic_scroll_artifact_<magicSid>`` grants and
SPELL → ``AddSpellHero``. Each mapping records the mechanic rationale.

Proof boundary: source/static. Runtime scroll cast behavior remains unvalidated.
"""

from __future__ import annotations

from typing import Any

# VCMI SpellID index → English identifier (Complete / RoE+AB+SoD).
H3_SPELL_ID_TO_NAME: dict[int, str] = {
    0: "summonBoat",
    1: "scuttleBoat",
    2: "visions",
    3: "viewEarth",
    4: "disguise",
    5: "viewAir",
    6: "fly",
    7: "waterWalk",
    8: "dimensionDoor",
    9: "townPortal",
    10: "quicksand",
    11: "landMine",
    12: "forceField",
    13: "fireWall",
    14: "earthquake",
    15: "magicArrow",
    16: "iceBolt",
    17: "lightningBolt",
    18: "implosion",
    19: "chainLightning",
    20: "frostRing",
    21: "fireball",
    22: "inferno",
    23: "meteorShower",
    24: "deathRipple",
    25: "destroyUndead",
    26: "armageddon",
    27: "shield",
    28: "airShield",
    29: "fireShield",
    30: "protectAir",
    31: "protectFire",
    32: "protectWater",
    33: "protectEarth",
    34: "antiMagic",
    35: "dispel",
    36: "magicMirror",
    37: "cure",
    38: "resurrection",
    39: "animateDead",
    40: "sacrifice",
    41: "bless",
    42: "curse",
    43: "bloodlust",
    44: "precision",
    45: "weakness",
    46: "stoneSkin",
    47: "disruptingRay",
    48: "prayer",
    49: "mirth",
    50: "sorrow",
    51: "fortune",
    52: "misfortune",
    53: "haste",
    54: "slow",
    55: "slayer",
    56: "frenzy",
    57: "titanBolt",
    58: "counterstrike",
    59: "berserk",
    60: "hypnotize",
    61: "forgetfulness",
    62: "blind",
    63: "teleport",
    64: "removeObstacle",
    65: "clone",
    66: "fireElemental",
    67: "earthElemental",
    68: "waterElemental",
    69: "airElemental",
}

# Mechanic-matched OE magic SIDs for campaign starting bonuses that appear in
# Complete RoE+AB/SoD START_BONUS catalogs (and close relatives kept for reuse).
# Do not key off HoMM3 display names when choosing the OE spell.
H3_SPELL_TO_OE_MAGIC: dict[int, dict[str, str]] = {
    9: {
        "oeMagicSid": "neutral_magic_town_portal",
        "h3Name": "townPortal",
        "mechanics": (
            "adventure cast that relocates the hero to a controlled town; "
            "OE town portal is the same adventure relocation verb"
        ),
        "scrollItemSid": "mythic_magic_scroll_artifact_neutral_magic_town_portal",
    },
    16: {
        "oeMagicSid": "primal_6_magic_ice_bolt",
        "h3Name": "iceBolt",
        "mechanics": (
            "single-target cold magic damage plus initiative/tempo reduction; "
            "OE Ice Bolt deals magic damage and reduces Initiative"
        ),
    },
    17: {
        "oeMagicSid": "primal_1_magic_thunderbolt",
        "h3Name": "lightningBolt",
        "mechanics": (
            "single-target lightning/air magic damage; OE Lightning Bolt is the "
            "direct single-target primal damage spell"
        ),
    },
    19: {
        "oeMagicSid": "primal_12_magic_chain_lightning",
        "h3Name": "chainLightning",
        "mechanics": (
            "lightning strike that chains to additional enemy stacks at reduced "
            "damage; OE primal_12_magic_chain_lightning is the literal same spell — "
            "chains to a second stack within 3 hexes at 0.5 damage multiplier "
            "(DB/magics/battle_primal_magics.json orderedCastParams)"
        ),
    },
    24: {
        "oeMagicSid": "space_9_magic_impending_fate",
        "h3Name": "deathRipple",
        "mechanics": (
            "battlefield-wide damage against opposing living stacks; OE Impending Fate "
            "damages every enemy stack scaled by creature level"
        ),
    },
    25: {
        "oeMagicSid": "day_15_magic_judgement",
        "h3Name": "destroyUndead",
        "mechanics": (
            "offensive magic strike aimed at destroying a stack; OE has no undead-only "
            "annihilator, so Judgement is the closest single-target multi-hit magic nuke"
        ),
    },
    31: {
        "oeMagicSid": "day_12_magic_radiant_armor",
        "h3Name": "protectFire",
        "mechanics": (
            "temporary damage reduction against a school of harm; OE Radiant Armor "
            "reduces damage taken from all sources (broader protection buff)"
        ),
    },
    33: {
        "oeMagicSid": "day_12_magic_radiant_armor",
        "h3Name": "protectEarth",
        "mechanics": (
            "temporary damage reduction against a school of harm; OE Radiant Armor "
            "reduces damage taken from all sources (broader protection buff)"
        ),
    },
    41: {
        "oeMagicSid": "day_2_magic_sharp_edge",
        "h3Name": "bless",
        "mechanics": (
            "friendly damage amplification on basic attacks; OE Blessing raises "
            "basic-attack damage percent"
        ),
    },
    44: {
        "oeMagicSid": "day_4_magic_favorable_wind",
        "h3Name": "precision",
        "mechanics": (
            "friendly ranged damage amplification; OE Favorable Wind raises ranged "
            "and long-reach damage percent"
        ),
    },
    48: {
        "oeMagicSid": "day_9_magic_arinas_hymn",
        "h3Name": "prayer",
        "mechanics": (
            "mass friendly combat buff combining mobility (Speed) with lasting combat "
            "stats; OE Arina's Touch grants Speed + Initiative (+ max HP). Matches the "
            "repo's Prayer stand-in pattern (Speed+Initiative) better than Atk/Def-only "
            "Enlarge Shadow or Speed-only Haste"
        ),
    },
    53: {
        "oeMagicSid": "day_3_magic_haste",
        "h3Name": "haste",
        "mechanics": "friendly Speed increase; OE Haste is the direct Speed buff",
    },
    55: {
        "oeMagicSid": "day_2_magic_sharp_edge",
        "h3Name": "slayer",
        "mechanics": (
            "attack damage increase versus tough/high-tier foes; OE has no level-gated "
            "Slayer, so Blessing's basic-attack damage amp is the closest offensive buff"
        ),
    },
    63: {
        "oeMagicSid": "space_6_magic_blink",
        "h3Name": "teleport",
        "mechanics": (
            "battlefield relocate of a friendly stack to an empty hex; OE Blink is the "
            "combat hex-relocation spell (not adventure Dimension Door)"
        ),
    },
}


def oe_magic_for_h3_spell(spell_id: int) -> dict[str, str]:
    row = H3_SPELL_TO_OE_MAGIC.get(int(spell_id))
    if row is None:
        h3_name = H3_SPELL_ID_TO_NAME.get(int(spell_id), f"id_{spell_id}")
        raise KeyError(
            f"no mechanics-matched OE magic for HoMM3 spell {spell_id} ({h3_name}); "
            "extend H3_SPELL_TO_OE_MAGIC with a mechanic rationale"
        )
    return dict(row)


def scroll_item_sid_for_h3_spell(spell_id: int) -> str:
    """Return the OE scroll item that teaches the mechanic-matched magic."""
    row = oe_magic_for_h3_spell(spell_id)
    explicit = str(row.get("scrollItemSid") or "").strip()
    if explicit:
        return explicit
    magic = str(row["oeMagicSid"]).strip()
    if not magic:
        raise ValueError(f"empty oeMagicSid for spell {spell_id}")
    # Standard day/night/space/primal scrolls use magic_scroll_artifact_<sid>.
    return f"magic_scroll_artifact_{magic}"


def spell_mapping_record(spell_id: int) -> dict[str, Any]:
    row = oe_magic_for_h3_spell(spell_id)
    return {
        "h3SpellId": int(spell_id),
        "h3SpellName": row.get("h3Name") or H3_SPELL_ID_TO_NAME.get(int(spell_id)),
        "oeMagicSid": row["oeMagicSid"],
        "scrollItemSid": scroll_item_sid_for_h3_spell(spell_id),
        "mechanics": row["mechanics"],
    }
