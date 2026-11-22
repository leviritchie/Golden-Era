"""Necropolis unit design keywords (custom_factions/unit_designs/homm3_necropolis.json).

Trade axis: Reaper (drains, feeds on corpses) versus Gravekeeper (curses, raises the fallen). Every keyword clones a
row piece that ships in the vanilla Core (donor named per keyword) and adds exactly one card.
"""
from __future__ import annotations

import homm3_unit_design_table as dt

ACTIVE = {
    "necropolis_shot",
    "necropolis_drain_strike",
    "necropolis_corpse_cast",
    "necropolis_hex",
    "necropolis_wail",
    "necropolis_animate_dead",
}
UNDEAD_NOTE = "description_effect_undead_embodiment_construct_immunities"
NON_LIVING_IMMUNITIES = ("undead_immunities", "construct_immunities", "embodiment_immunities")


def _standard_shot(sid, logic):
    """Plain shooter profile: range falloff and melee block as on vanilla shooters (some rows carried a built-in
    Sharpshooter without a card: shootDmgBuff 0 and ignoreShootingBlock)."""
    default = logic["defaultAttacks"][0]
    if default.get("attackType_") != "shoot":
        raise RuntimeError(f"{sid}: shooter keyword on a unit whose default attack does not shoot")
    dealer = default["damageDealer"]
    dealer["shootThreshold"], dealer["shootRedCount"], dealer["shootDmgBuff"] = 4, 5, -0.1
    logic["stats"].pop("ignoreShootingBlock", None)


def _vampirism(value, target, revive, overflow=False):
    # "with temp stacks" (native, flicker) also raises past the starting number; the extra units are temporary
    mode = "with temp stacks" if overflow else ("until start amount" if revive else "without respawn")
    return {"mech": "vampirism", "values": ["0", str(value), target, mode], "afterAttack": True}


def kw_necropolis_shot(ctx, sid, logic, view, entry):  # shared 'shot' on a normalised shooter profile
    _standard_shot(sid, logic)
    dt.KEYWORDS["shot"](ctx, sid, logic, view, entry)


def kw_necropolis_death_cloud(ctx, sid, logic, view, entry):  # card for the row's own area shot (lich_upg pattern)
    _standard_shot(sid, logic)
    if logic["defaultAttacks"][0]["damageDealer"].get("attackPatternSid") != "attack_rumble_x1_x100":
        raise RuntimeError(f"{sid}: Death Cloud card on a unit without the area shot")
    dealer = logic["defaultAttacks"][0]["damageDealer"]
    dealer["statDmgMult"] = float(entry.get("mult", 1.0))
    if entry.get("friendlyFire"):  # the cloud hits friend and foe; the kw_revive immunity tags spare non-living rows
        dealer["damageTarget_"] = "all"
        dealer["affectTargetParams"]["castTarget_"] = "all"
        dealer["tags"] = list(dict.fromkeys([*dealer["tags"], *NON_LIVING_IMMUNITIES]))
    view["passives"].append(dt._card(sid, entry, "sub_skill_siege_2_icon"))


def kw_necropolis_regeneration(ctx, sid, logic, view, entry):  # donor: hydra_upg start_turn full heal, no revive
    action = ctx.donor("hydra_upg")["passives"][0]["actions"][1]
    mechs = action["damageDealer"].get("targetMechanics") or []
    if action.get("trigger") != "start_turn" or [m.get("mech") for m in mechs] != ["heal_percent"]:
        raise RuntimeError("hydra_upg passive layout changed; start_turn heal not at passives[0].actions[1]")
    mechs[0]["values"][2] = str(entry.get("v", 1.0))
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "magic_healing_water_effect_icon"))


def kw_necropolis_vampirism(ctx, sid, logic, view, entry):  # donors: vampire (self, revives), lich_upg_alt (allies, no revive)
    for bucket in ("defaultAttacks", "counterAttacks"):
        for attack in logic[bucket]:
            attack["selfMechanics"] = [_vampirism(entry["v"], entry["target"], entry["revive"], entry.get("overflow", False))]
    card = dt._card(sid, entry, "magic_healing_water_effect_icon")
    card["excaptionInTooltip"] = UNDEAD_NOTE
    view["passives"].append(card)


def kw_necropolis_drain_strike(ctx, sid, logic, view, entry):  # shared melee_strike plus vampirism on the strike
    dt.KEYWORDS["melee_strike"](ctx, sid, logic, view, entry)
    logic["abilities"][-1]["selfMechanics"] = [_vampirism(entry["drain"], "self", True)]
    view["abilities"][-1]["excaptionInTooltip"] = UNDEAD_NOTE


def kw_necropolis_bone_harvest(ctx, sid, logic, view, entry):  # donor: olgoi passive 0 (devour the corpse on the destination hex)
    action = ctx.donor("olgoi")["passives"][0]["actions"][0]
    mechs = action["damageDealer"].get("targetMechanics") or []
    if action.get("trigger") != "unit_end_move" or [m.get("mech") for m in mechs] != ["destroy_corpse_and_heal"]:
        raise RuntimeError("olgoi passive layout changed; corpse devour not at passives[0].actions[0]")
    mechs[0]["values"] = ["one", str(entry["hp"]), "1", str(entry["perStack"]), "until start amount"]
    logic["passives"].append({"actions": [action]})
    card = dt._card(sid, entry, "magic_healing_water_effect_icon")
    card["excaptionInTooltip"] = UNDEAD_NOTE
    view["passives"].append(card)


def kw_necropolis_corpse_eater(ctx, sid, logic, view, entry):  # donor: lich_dragon passive 0 (absorb corpses at and around the destination)
    ctx.require_buff(entry["buff"], sid)
    action = ctx.donor("lich_dragon")["passives"][0]["actions"][0]
    mechs = action["damageDealer"].get("targetMechanics") or []
    if action.get("trigger") != "unit_end_move" or [m.get("mech") for m in mechs] != ["destroy_corpse_with_buff"]:
        raise RuntimeError("lich_dragon passive layout changed; corpse absorb not at passives[0].actions[0]")
    mechs[0]["values"] = ["true", "1", entry["buff"]]
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "lich_dragon_corpse_buff_icon"))


def kw_necropolis_corpse_cast(ctx, sid, logic, view, entry):  # donor: lich_upg_alt ability 1 (cast on a corpse, destroy it)
    ability = ctx.donor("lich_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if [m.get("mech") for m in dealer.get("targetMechanics") or []] != ["change_mana", "destroy_corpse"] or dealer["castTargetParams"].get("targetCondition_") != "dead":
        raise RuntimeError("lich_upg_alt ability 1 is no longer the corpse-to-mana cast")
    dt._envelope(ability, entry)
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["selection"] = "object"
    if "range" in entry:
        dealer["shootRange"] = entry["range"]
    if entry.get("free"):
        ability["actionCost"] = 0
    effect = entry["effect"]
    destroy = dealer["targetMechanics"][1]
    icon = "magic_healing_water_effect_icon"
    if effect == "mana":  # the donor's own effect with another amount
        dealer["targetMechanics"][0]["values"][2] = str(entry["mana"])
        icon = "sub_skill_faction_unfrozen_2_ability"
    elif effect == "heal":  # the caster feeds: lich_dragon ability 1 carries heal_percent as a self mechanic
        dealer["targetMechanics"] = [destroy]
        dealer["tags"] = ["ability", "heal_ability", "embodiment_immunities", "construct_immunities"]
        dealer["damageType_"] = "none"
        ability["selfMechanics"] = [{"mech": "heal_percent", "values": ["until start amount", "max_squad", str(entry["percent"]), "0.00", "true"]}]
    elif effect == "explode":  # area damage around the corpse; every corpse in the area is destroyed
        dealer["targetMechanics"] = [destroy]
        dealer["tags"] = ["ability", "armed_ability", "normal_damage", "embodiment_immunities", "construct_immunities"]
        dealer["attackPatternSid"] = "attack_rumble_x1_x100"
        dealer["affectTargetParams"] = {"targetTags": ["unit"], "castTarget_": "all", "targetCondition_": "all", "selection": "object"}
        dealer["damageTarget_"] = "enemy"
        dealer["damageType_"] = "normal"
        dealer["statDmgMult"] = entry["mult"]
        icon = "sub_skill_siege_2_icon"
    else:
        raise RuntimeError(f"{sid}: unknown corpse cast effect {effect!r}")
    logic["abilities"].append(ability)
    extra = {"excaptionInTooltip": "description_effect_embodiment_construct_immunities"}
    if entry.get("free"):
        extra["infoDescription"] = "ability_no_turn"
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_special", icon, entry.get("anim", 2), **extra))


def kw_necropolis_hex(ctx, sid, logic, view, entry):  # donor: graverobber_upg_alt ability 1 (cast a debuff on one enemy)
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("graverobber_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if ability.get("attackType_") != "cast" or dealer.get("buffTarget_") != "enemy":
        raise RuntimeError("graverobber_upg_alt ability 1 is no longer the single-enemy debuff cast")
    dt._envelope(ability, entry)
    dt._set_buff(dealer, entry, "enemy")
    if "range" in entry:
        dealer["shootRange"] = entry["range"]
    extra = {}
    if entry.get("free"):
        ability["actionCost"] = 0
        extra["infoDescription"] = "ability_no_turn"
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_debuff", "magic_unnatural_calm_effect_icon", entry.get("anim", 2), **extra))


def kw_necropolis_wail(ctx, sid, logic, view, entry):  # donor: minos_upg_alt ability 1 (debuff every adjacent enemy, free action)
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("minos_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if dealer.get("attackPatternSid") != "attack_rumble_x1_x100" or dealer.get("buffTarget_") != "enemy" or ability.get("actionCost") != 0:
        raise RuntimeError("minos_upg_alt ability 1 is no longer the free rumble-from-self debuff")
    dt._envelope(ability, entry)
    dt._set_buff(dealer, entry, "enemy")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_debuff", "magic_shorten_shadow_effect_icon", entry.get("anim", 2), infoDescription="ability_no_turn"))


def kw_necropolis_animate_dead(ctx, sid, logic, view, entry):  # donor: lich ability 0 (Rewind Death), works on the undead
    ability = ctx.donor("lich")["abilities"][0]
    dealer = ability["damageDealer"]
    if [m.get("mech") for m in dealer.get("targetMechanics") or []] != ["revive"]:
        raise RuntimeError("lich ability 0 no longer carries exactly one revive mechanic")
    dt._envelope(ability, entry)
    ability["charges"] = entry["charges"]
    dealer["targetMechanics"][0]["values"] = list(entry["values"])
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["selection"] = "object"
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_special", "magic_healing_water_effect_icon", entry.get("anim", 2)))


def kw_necropolis_on_death(ctx, sid, logic, view, entry):
    """When a stack of the given side dies: a buff on this unit (donor avatar_of_war_upg_alt passive 0) or Focus
    (donor graverobber_upg_alt passive 0)."""
    if entry["effect"] == "buff":
        ctx.require_buff(entry["buff"], sid)
        action = ctx.donor("avatar_of_war_upg_alt")["passives"][0]["actions"][0]
        if action.get("trigger") != "unit_died" or "buff" not in action["damageDealer"]:
            raise RuntimeError("avatar_of_war_upg_alt passive layout changed; death buff not at passives[0]")
        action["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": entry.get("duration", 1)}  # -1: until the end of the battle
        icon = "avatar_of_war_additionbuff_icon"
    elif entry["effect"] == "focus":
        action = ctx.donor("graverobber_upg_alt")["passives"][0]["actions"][0]
        mechs = action["damageDealer"].get("targetMechanics") or []
        if action.get("trigger") != "unit_died" or [m.get("mech") for m in mechs] != ["add_energy"]:
            raise RuntimeError("graverobber_upg_alt passive layout changed; death Focus not at passives[0]")
        mechs[0]["values"][2] = str(entry["n"])
        icon = "skill_tactics"
    else:
        raise RuntimeError(f"{sid}: unknown on_death effect {entry['effect']!r}")
    who = entry["who"] if isinstance(entry["who"], list) else [entry["who"]]
    # two sides: godslayer_upg_alt's unit_died condition (allegiance_both ["self", "enemy"])
    action["triggerConditions"] = [{"checkFunction": "allegiance_both" if len(who) > 1 else "allegiance", "values": who}]
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, icon))


def kw_necropolis_dread(ctx, sid, logic, view, entry):  # donor: avatar_of_war globalPassives (enemy Morale, strongest only)
    logic["globalPassives"] = [{"tag": "h3_kit_necropolis_dread", "target": "enemy", "power": entry["n"], "data": {"stats": {"moral": -entry["n"]}}}]
    view["passives"].append(dt._card(sid, entry, "magic_unnatural_calm_effect_icon"))


# --- unit ability variety pass (2026-11-21) ---

def _start_turn_heal(ctx):
    action = ctx.donor("hydra_upg")["passives"][0]["actions"][1]
    mechs = action["damageDealer"].get("targetMechanics") or []
    if action.get("trigger") != "start_turn" or [m.get("mech") for m in mechs] != ["heal_percent"]:
        raise RuntimeError("hydra_upg passive layout changed; start_turn heal not at passives[0].actions[1]")
    return action


def kw_necropolis_reassemble(ctx, sid, logic, view, entry):
    """At the end of each round the stack heals a share of its full Health and raises its fallen: hydra_upg's
    start_turn heal_percent moved to the round-level end_round trigger (no condition, as
    magic_reality_distortion_effect_1's end_round action), max_squad and "until start amount" (it revives)."""
    action = _start_turn_heal(ctx)
    action["trigger"] = "end_round"
    action.pop("triggerConditions", None)
    action["damageDealer"]["targetMechanics"][0]["values"] = ["until start amount", "max_squad", str(entry["percent"]), "0.00", "true"]
    logic["passives"].append({"actions": [action]})
    card = dt._card(sid, entry, "magic_healing_water_effect_icon")
    card["excaptionInTooltip"] = UNDEAD_NOTE
    view["passives"].append(card)


def kw_necropolis_mana_drain(ctx, sid, logic, view, entry):
    """At the start of its turn, moves mana from the enemy hero to this side's hero: hydra_upg's start_turn self
    action carrying change_mana transfer (the twinkle / Leeching Hop value form, min = max = amount)."""
    action = _start_turn_heal(ctx)
    dealer = action["damageDealer"]
    dealer["tags"] = ["passive"]
    amount = str(entry["mana"])
    dealer["targetMechanics"] = [{"mech": "change_mana", "values": ["transfer", "ally", amount, amount, "1", "false"]}]
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_faction_unfrozen_2_ability"))
