"""Inferno keywords for the unit design tables (custom_factions/unit_designs/homm3_inferno.json).

Each keyword clones a mechanic that ships in the vanilla Core (donor named per keyword) and adds exactly one
card. Loaded by homm3_unit_design_table._load_extensions.
"""

from __future__ import annotations

import copy

import homm3_unit_design_table as dt

ACTIVE = {"inferno_nova"}

_SHAPE_KEYS = ("attackPatternSid", "castTargetParams", "affectTargetParams", "damageTarget_")


def kw_inferno_attack_shape(ctx, sid, logic, view, entry):
    """Basic attack shape taken from a vanilla unit's default attack (targets and damage side come with it).

    donors: hydra (swipe, enemies), twinkle_upg (target plus all adjacent enemies), dragon (breath, any creature),
    lich_upg (area shot, enemies). "pattern" picks a weaker or stronger variant of the same shape family.
    """
    donor = ctx.donor(entry["donor"])["defaultAttacks"][0]
    dealer = donor["damageDealer"]
    if dealer.get("attackPatternSid") != entry["donorPattern"]:
        raise RuntimeError(f"{sid}: {entry['donor']} default attack is no longer {entry['donorPattern']}")
    own = logic["defaultAttacks"][0]
    if own.get("attackType_") != donor.get("attackType_"):
        raise RuntimeError(f"{sid}: attack shape donor {entry['donor']} attacks by {donor.get('attackType_')}, the unit by {own.get('attackType_')}")
    for key in _SHAPE_KEYS:
        own["damageDealer"][key] = copy.deepcopy(dealer[key])
    if "pattern" in entry:
        own["damageDealer"]["attackPatternSid"] = entry["pattern"]
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_2_icon"))


def kw_inferno_first_strike(ctx, sid, logic, view, entry):  # donors: locust_upg, minos_upg passive sequenceEffect
    logic["passives"].append({"data": {"sequenceEffect": "counter_before_attack"}})
    view["passives"].append(dt._card(sid, entry, "skill_tactics"))


def kw_inferno_point_blank(ctx, sid, logic, view, entry):  # donor: succubus stats.ignoreShootingBlock
    logic["stats"]["ignoreShootingBlock"] = True
    view["passives"].append(dt._card(sid, entry, "sub_skill_siege_2_icon"))


def kw_inferno_magic_channel(ctx, sid, logic, view, entry):  # donor: druid passive sideModifiers (own hero's spells cost less)
    logic["passives"].append({"data": {"sideModifiers": [
        {"tag": "h3_kit_inferno_magic_channel", "power": entry["v"], "heroStat": {"manaCostBonus": -entry["v"]}, "target": "ally"}]}})
    view["passives"].append(dt._card(sid, entry, "magic_nairas_kiss_effect_icon"))


def kw_inferno_ill_omen(ctx, sid, logic, view, entry):  # donor: olgoi globalPassives (enemy Luck, strongest only)
    logic["globalPassives"] = [
        {"tag": "h3_kit_inferno_ill_omen", "target": "enemy", "power": entry["v"], "data": {"stats": {"luck": -entry["v"]}}}]
    view["passives"].append(dt._card(sid, entry, "magic_shorten_shadow_effect_icon"))


def kw_inferno_nova(ctx, sid, logic, view, entry):
    """Burst around the unit itself: lava_larva ability 0 (Blow Up) without the self-destruct, enemies only,
    damage as a share of the basic attack instead of the larva's flat value."""
    ability = ctx.donor("lava_larva")["abilities"][0]
    dealer = ability["damageDealer"]
    cast = dealer.get("castTargetParams", {})
    if ability.get("attackType_") != "cast" or cast.get("castTarget_") != "self" or dealer.get("attackPatternSid") != "attack_rumble_x1_x100":
        raise RuntimeError("lava_larva ability 0 is no longer the burst-around-self cast")
    ability["selfMechanics"] = []
    dt._envelope(ability, entry)
    dealer["tags"] = ["ability", "magic_damage"]
    dealer["affectTargetParams"]["castTarget_"] = "enemy"
    dealer["damageTarget_"] = "enemy"
    dealer["damageType_"] = "magic_pure"
    dealer["statDmgMult"] = entry["mult"]
    dealer["targetMechanics"] = []
    for key in ("minBaseDmg", "maxBaseDmg", "damageMultiplerPerHeroLevel"):
        dealer.pop(key, None)
    if "buff" in entry:
        ctx.require_buff(entry["buff"], sid)
    dt._set_buff(dealer, entry, "enemy")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_attack", "magic_vengeance_effect_icon", 2))


# --- unit ability variety pass (2026-11-21): mana, whip, flay and swap keywords ---

ACTIVE |= {"inferno_drive", "inferno_flay", "inferno_exchange"}


def kw_inferno_mana_echo(ctx, sid, logic, view, entry):
    """Whenever the enemy hero casts a spell, this side's hero gains mana: the cast_magic / allegiance enemy action
    of sub_skill_tactics_3_unit_bonus (a hero buff action) as a unit passive, add_energy swapped for change_mana
    (value form of the hero bonuses, ["add", "ally", N, "0", "0", "true"])."""
    donor = ctx.buffs.get("sub_skill_tactics_3_unit_bonus")
    action = copy.deepcopy((donor or {}).get("actions", [None])[0])
    if not action or action.get("trigger") != "cast_magic" or action["triggerConditions"][0]["values"] != ["enemy"]:
        raise RuntimeError("sub_skill_tactics_3_unit_bonus no longer carries the enemy cast_magic action")
    action["damageDealer"]["targetMechanics"] = [{"mech": "change_mana", "values": ["add", "ally", str(entry["mana"]), "0", "0", "true"]}]
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "base_passive_caster_name"))


def kw_inferno_death_mana(ctx, sid, logic, view, entry):
    """When this stack is destroyed its hero gains mana: peasant passive 0 (unit_died, allegiance self) with only a
    change_mana mechanic. The corpse is kept (no destroy_corpse), so corpse users can still take it."""
    action = ctx.donor("peasant")["passives"][0]["actions"][0]
    if action.get("trigger") != "unit_died" or action["triggerConditions"][0]["values"] != ["self"]:
        raise RuntimeError("peasant passive layout changed; own death action not at passives[0].actions[0]")
    action["damageDealer"]["targetMechanics"] = [{"mech": "change_mana", "values": ["add", "ally", str(entry["mana"]), "0", "0", "true"]}]
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "lava_larva_passive_1_name"))


def kw_inferno_tag_card(ctx, sid, logic, view, entry):
    """A unit row tag that buff-carried tag mods read (inDmgModsByCasterTags on the target's buff, the
    homm3_tower_graft_716 shape): "+X% Damage to creatures carrying buff B" stays visible native data."""
    tags = logic.setdefault("tags", [])
    if entry["tag"] not in tags:
        tags.append(entry["tag"])
    for buff in entry.get("buffs", []):
        ctx.require_buff(buff, sid)
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_2_icon"))


def kw_inferno_drive(ctx, sid, logic, view, entry):
    """Free buff cast on one other friendly stack in range: graverobber_upg_alt ability 1 (single-target cast)
    retargeted from an enemy to an ally (allynoself), actionCost 0."""
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("graverobber_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if ability.get("attackType_") != "cast" or dealer.get("buffTarget_") != "enemy":
        raise RuntimeError("graverobber_upg_alt ability 1 is no longer the single-target debuff cast")
    dt._envelope(ability, entry)
    ability["actionCost"] = 0
    dealer["tags"] = ["ability", "buff_ability"]
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["castTarget_"] = "allynoself"
    dealer["shootRange"] = entry["range"]
    dt._set_buff(dealer, entry, "ally")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_buff", "skill_tactics", 2, infoDescription="ability_no_turn"))


def kw_inferno_flay(ctx, sid, logic, view, entry):
    """Shared melee_strike that also strips the target's positive effects (dispel ["positive"], the value form of
    lightweaver_upg's dispel with the other tag)."""
    dt.KEYWORDS["melee_strike"](ctx, sid, logic, view, entry)
    dealer = logic["abilities"][-1]["damageDealer"]
    dealer["targetMechanics"] = [{"mech": "dispel", "values": ["positive"]}, *dealer.get("targetMechanics", [])]


def kw_inferno_exchange(ctx, sid, logic, view, entry):
    """Swap places with an enemy stack: the shared swap (arbitrator_upg_alt swap_units, first pick this unit) with the
    ordered second pick on an enemy, plus a buff on that pick (its counterattack disabler)."""
    ctx.require_buff(entry["buff"], sid)
    dt.KEYWORDS["swap"](ctx, sid, logic, view, entry)
    dealer = logic["abilities"][-1]["damageDealer"]
    for key in ("orderedCastParams", "orderedAffectParams"):
        dealer[key][0]["castTarget_"] = "enemy"
        dealer[key][0]["targetCondition_"] = "alive"
    dealer["buffTarget_"] = "enemy"
    dealer["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}


ACTIVE |= {"inferno_raise_demons"}


def kw_inferno_raise_demons(ctx, sid, logic, view, entry):
    """Raise Demons, the draft's native fallback (raise_by_hp is not implemented): lich_upg_alt ability 1 corpse cast
    with peasant passive 0's summon_percent row form; the count is native (factor x the corpse stack's start squad)."""
    ability = ctx.donor("lich_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if [m.get("mech") for m in dealer.get("targetMechanics") or []] != ["change_mana", "destroy_corpse"] or dealer["castTargetParams"].get("targetCondition_") != "dead":
        raise RuntimeError("lich_upg_alt ability 1 is no longer the corpse cast")
    summon = ctx.donor("peasant")["passives"][0]["actions"][0]["damageDealer"]["targetMechanics"][0]
    if summon.get("mech") != "summon_percent" or summon["values"][3] != "start_squad":
        raise RuntimeError("peasant passive 0 no longer carries the start_squad summon_percent")
    summon["values"][1] = entry["unit"]
    summon["values"][4] = float(entry["factor"])
    dt._envelope(ability, entry)
    ability.pop("disableForAi", None)
    ability["charges"] = entry["charges"]
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["selection"] = "object"
    dealer["shootRange"] = entry.get("range", 3)
    dealer["tags"] = ["ability", "embodiment_immunities", "construct_immunities"]
    dealer["targetMechanics"] = [summon, dealer["targetMechanics"][1]]
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_special", "magic_healing_water_effect_icon", entry.get("anim", 2),
                                              excaptionInTooltip="description_effect_embodiment_construct_immunities"))
