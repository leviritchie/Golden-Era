"""Stronghold keywords for the unit design table (custom_factions/unit_designs/homm3_stronghold.json).

Loaded by homm3_unit_design_table._load_extensions. Each keyword adds exactly one card.
"""
from __future__ import annotations

import copy

import homm3_unit_design_table as dt

ACTIVE = {"stronghold_bloodlust", "stronghold_area_shot", "stronghold_strike", "stronghold_shot", "stronghold_push_burst",
          "stronghold_phase_step"}


def _require_escalate(ctx, sid, entry):
    esc = entry.get("escalate")
    if not esc:
        return
    for buff in [esc.get("to"), esc.get("unless"), *esc.get("chain", [])]:
        if buff:
            ctx.require_buff(buff, sid)


def _self_action(ctx, trigger):
    """hydra passive 0 action 0 (self buff when damaged), retriggered."""
    action = ctx.donor("hydra")["passives"][0]["actions"][0]
    dealer = action["damageDealer"]
    if action.get("trigger") != "unit_took_damage" or dealer.get("castTargetParams", {}).get("castTarget_") != "self":
        raise RuntimeError("hydra passive layout changed; self-buff action not at passives[0].actions[0]")
    action["trigger"] = trigger
    return action


def kw_stronghold_armor_rend(ctx, sid, logic, view, entry):  # donor: sunlight_cavalry armorPen (there on a passive's stats)
    # Written on the unit's own stat block (the same stat the human law "unitStat armorPen" raises) so the
    # power model prices it.
    logic["stats"]["armorPen"] = entry["v"]
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_2_icon"))


def kw_stronghold_out_dmg(ctx, sid, logic, view, entry):  # typed outgoing damage bonus (stats.outDmgMods)
    # The rebuild does not reset outDmgMods, so this keyword replaces the whole list.
    logic["stats"]["outDmgMods"] = {"list": [{"t": entry["t"], "v": entry["v"]}]}
    view["passives"].append(dt._card(sid, entry, "sub_skill_siege_2_icon"))


def kw_stronghold_bloodlust(ctx, sid, logic, view, entry):  # donor: lightweaver ability 0 (ally buff cast that takes the turn)
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("lightweaver")["abilities"][0]
    dealer = ability["damageDealer"]
    if ability.get("attackType_") != "cast" or dealer.get("buffTarget_") != "ally" or "actionCost" in ability:
        raise RuntimeError("lightweaver ability 0 is no longer the turn-ending ally buff cast")
    dt._envelope(ability, entry)
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["castTarget_"] = "allynoself"
    dt._set_buff(dealer, entry, "ally")
    extra = {}
    if entry.get("free"):  # as kw_rally: a free action that does not end the turn
        ability["actionCost"] = 0
        extra["infoDescription"] = "ability_no_turn"
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_buff", "blade_dancer_buff_icon", 2, **extra))


def kw_stronghold_area_shot(ctx, sid, logic, view, entry):  # the unit's own shot with star_child's splash shape, enemies only
    default = logic["defaultAttacks"][0]
    if default.get("attackType_") != "shoot":
        raise RuntimeError(f"{sid}: 'stronghold_area_shot' on a unit whose default attack does not shoot")
    dealer = copy.deepcopy(default["damageDealer"])
    dealer["tags"] = list(dict.fromkeys([*dealer.get("tags", []), "ability", "armed_ability"]))
    dealer["attackPatternSid"] = entry.get("pattern", "attack_rumble_x1_x100_x50")
    dealer["affectTargetParams"]["castTarget_"] = "enemy"
    dealer["damageTarget_"] = "enemy"
    dealer["statDmgMult"] = entry["mult"]
    dealer["triggerCounter"] = False
    dt._set_buff(dealer, {}, "enemy")
    ability = {"attackType_": "shoot", "damageDealer": dealer}
    dt._envelope(ability, entry)
    logic["abilities"].append(ability)
    shot_view = view["defaultAttacks"][0]
    extra = {key: shot_view[key] for key in ("projectile", "projectileSpeed", "trajectory") if key in shot_view}
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_attack", "sub_skill_siege_2_icon", 1, **extra))


# --- 2026-11-21 ability variety pass -------------------------------------------------------------

def kw_stronghold_strike(ctx, sid, logic, view, entry):
    """melee_strike plus optional extras: `mech` (target mechanics), `selfMech` (self mechanics, e.g. a dispel),
    `magic` (the hit is magic_pure: hive_queen's magic dealer, Defence does not reduce it)."""
    dt.kw_melee_strike(ctx, sid, logic, view, entry)
    ability = logic["abilities"][-1]
    dealer = ability["damageDealer"]
    dealer.setdefault("targetMechanics", []).extend(copy.deepcopy(entry.get("mech", [])))
    ability.setdefault("selfMechanics", []).extend(copy.deepcopy(entry.get("selfMech", [])))
    if entry.get("magic"):
        dealer["damageType_"] = "magic_pure"
        dealer["tags"] = list(dict.fromkeys(["magic_damage" if t == "normal_damage" else t for t in dealer["tags"]]))


def kw_stronghold_shot(ctx, sid, logic, view, entry):  # the shared shot plus target mechanics (h3_nix reduce_counters)
    dt.kw_shot(ctx, sid, logic, view, entry)
    logic["abilities"][-1]["damageDealer"].setdefault("targetMechanics", []).extend(copy.deepcopy(entry.get("mech", [])))


def kw_stronghold_push_burst(ctx, sid, logic, view, entry):  # minos_upg_alt rumble (free), push instead of a buff
    ability = ctx.donor("minos_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if dealer.get("attackPatternSid") != "attack_rumble_x1_x100":
        raise RuntimeError("minos_upg_alt ability 1 is no longer the rumble-from-self cast")
    dt._envelope(ability, entry)
    ability["actionCost"] = 0
    dealer["affectTargetParams"]["castTarget_"] = "enemy"
    dt._set_buff(dealer, {}, "enemy")
    dealer["targetMechanics"] = [{"mech": "push_unit_from_caster", "values": ["false"]}]  # minos ability 0
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_special", "magic_favorable_wind_effect_icon", 2, infoDescription="ability_no_turn"))


def kw_stronghold_phase_step(ctx, sid, logic, view, entry):  # arbitrator ability 0 (free teleport), first pick = this unit
    ability = ctx.donor("arbitrator")["abilities"][0]
    dealer = ability["damageDealer"]
    if [m.get("mech") for m in dealer.get("targetMechanics", [])] != ["teleport"] or dealer.get("multitargetType") != "ordered":
        raise RuntimeError("arbitrator ability 0 is no longer the ordered teleport")
    dt._envelope(ability, entry)
    ability["actionCost"] = 0
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["castTarget_"] = "self"
    for key in ("orderedCastParams", "orderedAffectParams"):
        dealer[key][0]["distanceFromFirst"] = entry.get("range", 99)
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_movement", "magic_favorable_wind_effect_icon", 2, infoDescription="ability_no_turn"))


def kw_stronghold_attack_rider(ctx, sid, logic, view, entry):
    """Basic attacks (default attacks only, not counterattacks) put a buff on the target; optional `escalate`
    (to / chain) is the plugin's buff-add rewrite (stacking by distinct SIDs)."""
    ctx.require_buff(entry["buff"], sid)
    _require_escalate(ctx, sid, entry)
    for attack in logic["defaultAttacks"]:
        dt._set_buff(attack["damageDealer"], entry, "enemy")
    view["passives"].append(dt._card(sid, entry, "magic_shorten_shadow_effect_icon"))


def kw_stronghold_self_trigger_buff(ctx, sid, logic, view, entry):
    """Self buff on a trigger (`trigger`: unit_skip = Defend, start_round, unit_wait, unit_end_move ...); optional
    `escalate` chain for stacking."""
    ctx.require_buff(entry["buff"], sid)
    _require_escalate(ctx, sid, entry)
    action = _self_action(ctx, entry["trigger"])
    action["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_tactics_4_defence_buff_icon"))


def kw_stronghold_opening_buff(ctx, sid, logic, view, entry):  # qilin start_battle self buff with a finite duration
    ctx.require_buff(entry["buff"], sid)
    action = ctx.donor("qilin")["passives"][1]["actions"][0]
    if action.get("trigger") != "start_battle":
        raise RuntimeError("qilin passive layout changed; start_battle action not at passives[1]")
    action["damageDealer"]["buffTarget_"] = "self"
    action["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_tactics_2_initiative_buff_icon"))


def kw_stronghold_opening_rally(ctx, sid, logic, view, entry):  # qilin start_battle action widened to a radius around the unit
    ctx.require_buff(entry["buff"], sid)
    action = ctx.donor("qilin")["passives"][1]["actions"][0]
    if action.get("trigger") != "start_battle":
        raise RuntimeError("qilin passive layout changed; start_battle action not at passives[1]")
    dealer = action["damageDealer"]
    dealer["attackPatternSid"] = entry.get("pattern", "attack_rumble_x2_x100")
    dealer["multitargetType"] = "simultaneous"
    dealer["affectTargetParams"] = {"targetTags": ["unit"], "castTarget_": "allynoself", "targetCondition_": "alive"}
    dealer["buffTarget_"] = "ally"
    dealer["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_tactics_2_initiative_buff_icon"))


def kw_stronghold_death_rally(ctx, sid, logic, view, entry):
    """When this stack is destroyed it buffs adjacent allies: peasant passive 0's unit_died trigger (allegiance self,
    cast from its own hex) with minos_upg_alt's rumble shape aimed at allies."""
    ctx.require_buff(entry["buff"], sid)
    peasant = ctx.donor("peasant")["passives"][0]["actions"][0]
    if peasant.get("trigger") != "unit_died":
        raise RuntimeError("peasant passive 0 is no longer the unit_died action")
    rumble = ctx.donor("minos_upg_alt")["abilities"][1]["damageDealer"]
    if rumble.get("attackPatternSid") != "attack_rumble_x1_x100":
        raise RuntimeError("minos_upg_alt ability 1 is no longer the rumble-from-self cast")
    dealer = {
        "tags": ["passive"],
        "triggerCounter": False,
        "multitargetType": "simultaneous",
        "attackPatternSid": rumble["attackPatternSid"],
        "castTargetParams": copy.deepcopy(peasant["damageDealer"]["castTargetParams"]),
        "affectTargetParams": {"targetTags": ["unit"], "castTarget_": "allynoself", "targetCondition_": "alive"},
        "damageTarget_": "none",
        "statDmgMult": 0.0,
        "buffTarget_": "ally",
        "buff": {"sid": entry["buff"], "duration": entry["duration"]},
        "targetMechanics": [],
    }
    logic["passives"].append({"actions": [{"trigger": "unit_died", "triggerConditions": copy.deepcopy(peasant["triggerConditions"]), "damageDealer": dealer}]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_tactics_4_defence_buff_icon"))


def kw_stronghold_defend_breaker(ctx, sid, logic, view, entry):  # default shot dispels the listed buff tags on the target
    default = logic["defaultAttacks"][0]
    if default.get("attackType_") != "shoot":
        raise RuntimeError(f"{sid}: 'stronghold_defend_breaker' on a unit whose default attack does not shoot")
    for attack in logic["defaultAttacks"]:
        mechs = attack["damageDealer"].setdefault("targetMechanics", [])
        mechs.extend({"mech": "dispel", "values": [tag]} for tag in entry["tags"])
    view["passives"].append(dt._card(sid, entry, "sub_skill_siege_2_icon"))


def kw_stronghold_rampage(ctx, sid, logic, view, entry):
    """Extra turn on an own-turn kill, once per battle. Copy of bulwark_extra_turn's donor (godslayer_upg_alt passive
    0: unit_died + is_active_unit -> add_action_points, maxAddedApPerRound 1), plus a double_turn action that puts a
    hidden infinite buff with maxAddedApPerRound -99 on the unit (unspeakable_debuff's stat), so the cap stays shut."""
    ctx.require_buff(entry["spentBuff"], sid)
    passive = ctx.donor("godslayer_upg_alt")["passives"][0]
    actions = passive.get("actions") or []
    mechs = [m.get("mech") for m in actions[0]["damageDealer"].get("targetMechanics", [])] if actions else []
    if passive.get("data", {}).get("stats", {}).get("maxAddedApPerRound") != 1 or mechs != ["add_action_points"]:
        raise RuntimeError("godslayer_upg_alt passive layout changed; Murderous Glee not at passives[0]")
    spent = _self_action(ctx, "double_turn")
    spent["damageDealer"]["buff"] = {"sid": entry["spentBuff"], "duration": -1}
    passive["actions"].append(spent)
    logic["passives"].append(passive)
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_2_icon"))
