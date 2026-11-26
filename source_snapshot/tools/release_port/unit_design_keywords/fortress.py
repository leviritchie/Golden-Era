"""Fortress keywords for the unit design tables (custom_factions/unit_designs/homm3_fortress.json).

Loaded by homm3_unit_design_table._load_extensions. Each keyword adds exactly one card.
"""

from __future__ import annotations

import copy

import homm3_unit_design_table as dt

ACTIVE: set[str] = {"fortress_scavenge", "fortress_stone_gaze", "fortress_quarry_mark", "fortress_venom_burst", "fortress_drain_strike"}


def kw_fortress_regeneration(ctx, sid, logic, view, entry):  # donor: hydra_upg passive 0 action 1 (start_turn heal_percent)
    """At the start of its own turn the top creature heals `percent` of one creature's maximum health (no revive)."""
    action = ctx.donor("hydra_upg")["passives"][0]["actions"][1]
    mechanics = action["damageDealer"].get("targetMechanics") or []
    if action.get("trigger") != "start_turn" or [m.get("mech") for m in mechanics] != ["heal_percent"]:
        raise RuntimeError("hydra_upg passive layout changed; start_turn heal_percent not at passives[0].actions[1]")
    values = mechanics[0]["values"]
    if values[:2] != ["without respawn", "max_unit"]:
        raise RuntimeError("hydra_upg regeneration no longer heals a share of one creature without reviving")
    values[2] = f"{entry['percent'] / 100.0:.2f}"
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "magic_healing_water_effect_icon"))


# --- 2026-11-21 ability variety pass -------------------------------------------------------------

def _hydra_regen_values(ctx, percent, revive=False, stack=False):
    """hydra_upg's heal_percent values at `percent` of one creature. `revive` swaps the mode to "until start amount"
    (raises fallen creatures up to the stack's starting size) and `stack` the basis to "max_squad" (percent of the
    stack's full Health); both as h3_walking_dead_upg's corpse eating uses them."""
    mechanics = ctx.donor("hydra_upg")["passives"][0]["actions"][1]["damageDealer"].get("targetMechanics") or []
    if [m.get("mech") for m in mechanics] != ["heal_percent"] or mechanics[0]["values"][:2] != ["without respawn", "max_unit"]:
        raise RuntimeError("hydra_upg regeneration layout changed")
    values = list(mechanics[0]["values"])
    values[2] = f"{percent / 100.0:.2f}"
    if revive:
        values[0] = "until start amount"
    if stack:
        values[1] = "max_squad"
    return values


def _require_escalate(ctx, sid, entry):
    esc = entry.get("escalate")
    if not esc:
        return
    for buff in [esc.get("to"), esc.get("unless"), *esc.get("chain", [])]:
        if buff:
            ctx.require_buff(buff, sid)


def kw_fortress_scavenge(ctx, sid, logic, view, entry):
    """Eat an adjacent corpse and heal `percent` of one creature, or of the stack's full Health with `basis: stack`;
    `revive` (default on) lets the heal raise fallen creatures up to the starting size (owner 2026-11-22: revive, then
    20% of stack). Envelope: lich_upg_alt ability 1 (cast on any corpse +
    destroy_corpse); heal: hydra_upg's regeneration heal_percent values as a self mechanic (the shape
    h3_walking_dead_upg's corpse eating uses)."""
    ability = ctx.donor("lich_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if ability.get("attackType_") != "cast" or "destroy_corpse" not in [m.get("mech") for m in dealer.get("targetMechanics", [])]:
        raise RuntimeError("lich_upg_alt ability 1 is no longer the corpse cast with destroy_corpse")
    dt._envelope(ability, entry)
    dealer["tags"] = ["ability", "heal_ability", "embodiment_immunities", "construct_immunities"]
    dealer["damageType_"] = "none"
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["selection"] = "object"
    dealer["targetMechanics"] = [{"mech": "destroy_corpse", "values": []}]
    dealer["shootRange"] = 1
    ability["selfMechanics"] = [{"mech": "heal_percent", "values": _hydra_regen_values(ctx, entry["percent"], entry.get("revive", True), entry.get("basis") == "stack")}]
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_special", "magic_healing_water_effect_icon", 2))


def kw_fortress_stat(ctx, sid, logic, view, entry):
    """Plain unit stats (damagePerDeltaLevel: trick_demon; outDmgModsByTargetTags appended: dragon_hunter) and
    optional unit row tags (`unitTags`, for buffs keyed by inDmgModsByCasterTags)."""
    for key, value in entry.get("stats", {}).items():
        if key == "outDmgModsByTargetTags":
            mods = logic["stats"].setdefault("outDmgModsByTargetTags", {"list": []})
            mods.setdefault("list", []).extend({"t": mod["t"], "v": mod["v"]} for mod in value)
        else:
            logic["stats"][key] = copy.deepcopy(value)
    tags = logic.setdefault("tags", [])
    for tag in entry.get("unitTags", []):
        if tag not in tags:
            tags.append(tag)
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_1_icon"))


def kw_fortress_stone_gaze(ctx, sid, logic, view, entry):
    """h3_basilisk's Stone Gaze (ability 0, the medusa_stone strike) copied onto another row, with the petrify swapped
    for `buff` (a medusa_stone clone) and its own focus / cooldown."""
    ctx.require_buff(entry["buff"], sid)
    donor = ctx.donor("h3_basilisk")
    matches = [i for i, a in enumerate(donor.get("abilities", [])) if (a["damageDealer"].get("buff") or {}).get("sid") in ("medusa_stone", entry["buff"])]
    if len(matches) != 1:
        raise RuntimeError("h3_basilisk no longer carries exactly one Stone Gaze (medusa_stone) ability")
    ability = donor["abilities"][matches[0]]
    dt._envelope(ability, entry)
    ability["damageDealer"]["buff"]["sid"] = entry["buff"]
    logic["abilities"].append(ability)
    card = copy.deepcopy(ctx.donor("h3_basilisk", "v")["abilities"][matches[0]])
    card.update(dt._card(sid, entry, "medusa_stone_icon"))
    view["abilities"].append(card)


def kw_fortress_quarry_mark(ctx, sid, logic, view, entry):
    """Free mark cast on one enemy: lightweaver ability 0 (single-target buff cast) aimed at an enemy, actionCost 0.
    The plugin rule `quarry` reads the mark (a buff with no stats)."""
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("lightweaver")["abilities"][0]
    dealer = ability["damageDealer"]
    if ability.get("attackType_") != "cast" or dealer.get("attackPatternSid") != "attack_single_buff":
        raise RuntimeError("lightweaver ability 0 is no longer the single-target buff cast")
    dt._envelope(ability, entry)
    ability["actionCost"] = 0
    dealer["tags"] = ["ability", "debuff_ability"]
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["castTarget_"] = "enemy"
    dt._set_buff(dealer, entry, "enemy")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_debuff", "magic_taunt_effect_icon", 2, infoDescription="ability_no_turn"))


def kw_fortress_venom_burst(ctx, sid, logic, view, entry):  # kw_rally's body (minos_upg_alt rumble, free) aimed at enemies
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("minos_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if dealer.get("attackPatternSid") != "attack_rumble_x1_x100":
        raise RuntimeError("minos_upg_alt ability 1 is no longer the rumble-from-self cast")
    dt._envelope(ability, entry)
    ability["actionCost"] = 0
    dealer["tags"] = ["ability", "debuff_ability"]
    dealer["affectTargetParams"]["castTarget_"] = "enemy"
    dt._set_buff(dealer, entry, "enemy")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_debuff", "magic_fatal_decay_effect_icon", 2, infoDescription="ability_no_turn"))


def kw_fortress_drain_strike(ctx, sid, logic, view, entry):
    """melee_strike plus a vampirism self mechanic after the attack (h3_manticore_upg's default attack shape):
    heals `drain` of the damage dealt, up to the stack's starting size."""
    dt.kw_melee_strike(ctx, sid, logic, view, entry)
    ability = logic["abilities"][-1]
    ability.setdefault("selfMechanics", []).append(
        {"mech": "vampirism", "values": ["0", str(entry["drain"]), "self", "until start amount"], "afterAttack": True})


def kw_fortress_counter_kill(ctx, sid, logic, view, entry):
    """Counterattacks also kill creatures: the kill_stacks mechanic of h3_gorgon_upg's Death Stare, copied with its
    values onto the counterattack dealer."""
    kills = [m for a in ctx.donor("h3_gorgon_upg").get("abilities", []) for m in a["damageDealer"].get("targetMechanics", [])
             if m.get("mech") == "kill_stacks"]
    if not kills:
        raise RuntimeError("h3_gorgon_upg no longer carries a kill_stacks mechanic")
    mech = copy.deepcopy(kills[0])
    mech["values"][0] = str(entry["n"])
    for attack in logic["counterAttacks"]:
        attack["damageDealer"].setdefault("targetMechanics", []).append(copy.deepcopy(mech))
    view["passives"].append(dt._card(sid, entry, "medusa_stone_icon"))


def kw_fortress_self_trigger_buff(ctx, sid, logic, view, entry):
    """Self buff on a trigger (`trigger`: unit_wait = Wait, unit_skip = Defend, unit_end_move, start_round ...):
    hydra passive 0 action 0 (self buff when damaged), retriggered."""
    ctx.require_buff(entry["buff"], sid)
    _require_escalate(ctx, sid, entry)
    action = ctx.donor("hydra")["passives"][0]["actions"][0]
    if action.get("trigger") != "unit_took_damage" or action["damageDealer"].get("castTargetParams", {}).get("castTarget_") != "self":
        raise RuntimeError("hydra passive layout changed; self-buff action not at passives[0].actions[0]")
    action["trigger"] = entry["trigger"]
    action["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "magic_favorable_wind_effect_icon"))


def kw_fortress_after_ability_buff(ctx, sid, logic, view, entry):
    """Self buff after this unit uses its active ability: assassin_upg's own-attack trigger with the condition value
    "ability" (as kw_melee_strike's selfBuff)."""
    ctx.require_buff(entry["buff"], sid)
    action = ctx.donor("assassin_upg")["passives"][0]["actions"][0]
    conditions = action.get("triggerConditions") or []
    if action.get("trigger") != "unit_cast_ability" or len(conditions) != 1 or conditions[0].get("checkFunction") != "ability_and_allegiance":
        raise RuntimeError("assassin_upg passive layout changed; own-cast trigger not at passives[0].actions[0]")
    conditions[0]["values"] = ["self", "ability"]
    action["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "magic_favorable_wind_effect_icon"))


def kw_fortress_opening_buff(ctx, sid, logic, view, entry):  # qilin start_battle self buff with a finite duration
    ctx.require_buff(entry["buff"], sid)
    action = ctx.donor("qilin")["passives"][1]["actions"][0]
    if action.get("trigger") != "start_battle":
        raise RuntimeError("qilin passive layout changed; start_battle action not at passives[1]")
    action["damageDealer"]["buffTarget_"] = "self"
    action["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_tactics_2_initiative_buff_icon"))
