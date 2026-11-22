"""Bulwark kit keywords (custom_factions/unit_designs/homm3_bulwark.json).

Trade axis Tempo vs Bastion: the Tempo side wants many small actions and extra retaliations, the Bastion side
wants to Defend and to be hit. Every keyword here is a passive (one card each) built from vanilla Core rows:

  bulwark_duelist         shooter with full melee damage (shared skirmisher) plus the plain ranged marker card
  bulwark_free_shooting   stats.ignoreShootingBlock (vanilla buff stat; aqualotl wisp, Light and Shade Cloak)
  bulwark_ice_immunity    the Ram line's Ice Bolt / Avalanche immunity block, on any unit
  bulwark_on_defend_buff  self buff when the unit Defends: trigger unit_skip, as hero skill Formation uses it
                          (sub_skill_formation_2_unit_bonus), here on a unit passive (hydra's self-buff action)
  bulwark_on_attack_buff  self buff on each own basic attack and counterattack (assassin_upg Sharper Blade)
  bulwark_regeneration    hydra_upg Regeneration (start_turn heal_percent, no revive)
  bulwark_countershot     medusa_upg_alt Countershot: a shoot counterattack ahead of the melee one
  bulwark_overwatch       qilin_upg_alt Opportunity Attack: stats.maxOverwatchStrikes
  bulwark_extra_turn      godslayer_upg_alt Murderous Glee: add_action_points on an own-turn kill, once per round

2026-11-21 ability variety pass:

  bulwark_self_trigger_buff  hydra's self action on any trigger, optional triggerConditions, a buff or a dispel
  bulwark_stat               plain unit stats (ignoreObstacles, energyPerTakeDamage, energyPerRound)
  bulwark_pierce_attack      basic attacks and counterattacks on attack_reach_x1_x100_x50 (the hex behind at 50%)
  bulwark_focus_gift         free single-ally cast with add_energy (godslayer_upg's value layout)
  bulwark_grant_turn         unspeakable_upg ability 1 (free add_action_points + AP-cap buff) aimed at another ally
"""
from __future__ import annotations

import copy

import homm3_unit_design_table as dt

ACTIVE: set[str] = {"bulwark_focus_gift", "bulwark_grant_turn"}

RANGED_MARKER = {"name": "h3_common_ranged_attack_name", "description": "h3_common_ranged_attack_description", "icon": "sub_skill_siege_1_icon"}
ICE_IMMUNITIES = [
    {"type": "damage", "tags": ["primal_6_magic_ice_bolt_damage", "primal_13_magic_avalanche_damage"]},
    {"type": "effect", "tags": ["primal_6_magic_ice_bolt_effect"]},
]


def kw_bulwark_duelist(ctx, sid, logic, view, entry):
    # The Elf line's old marker (base_passive_ranged_attack_no_close) is not a kept marker row; use the plain one.
    # ignoreShootingBlock is kit-owned on this line: cleared here, set again by bulwark_free_shooting.
    logic["stats"].pop("ignoreShootingBlock", None)
    if not any(p.get("name") == RANGED_MARKER["name"] for p in view["passives"]):
        view["passives"].insert(0, dict(RANGED_MARKER))
    dt.kw_skirmisher(ctx, sid, logic, view, entry)


def kw_bulwark_free_shooting(ctx, sid, logic, view, entry):
    logic["stats"]["ignoreShootingBlock"] = True
    view["passives"].append(dt._card(sid, entry, "crossbowman_buff_icon"))


def kw_bulwark_ice_immunity(ctx, sid, logic, view, entry):
    has = any(
        immunity.get("type") == "damage" and "primal_6_magic_ice_bolt_damage" in immunity.get("tags", [])
        for passive in logic["passives"] for immunity in passive.get("data", {}).get("immunities", [])
    )
    if not has:
        logic["passives"].append({"data": {"immunities": copy.deepcopy(ICE_IMMUNITIES)}})
    view["passives"].append(dt._card(sid, entry, "magic_ice_bolt_effect_icon"))


def _self_buff_action(ctx, sid, entry):
    ctx.require_buff(entry["buff"], sid)
    action = ctx.donor("hydra")["passives"][0]["actions"][0]
    dealer = action["damageDealer"]
    if action.get("trigger") != "unit_took_damage" or dealer.get("castTargetParams", {}).get("castTarget_") != "self":
        raise RuntimeError("hydra passive layout changed; self-buff action not at passives[0].actions[0]")
    dealer["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    return action


def kw_bulwark_on_defend_buff(ctx, sid, logic, view, entry):
    action = _self_buff_action(ctx, sid, entry)
    action["trigger"] = "unit_skip"
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_tactics_4_defence_buff_icon"))


def kw_bulwark_on_attack_buff(ctx, sid, logic, view, entry):
    ctx.require_buff(entry["buff"], sid)
    actions = ctx.donor("assassin_upg")["passives"][0]["actions"][:2]
    kinds = [(a.get("trigger"), (a.get("triggerConditions") or [{}])[0].get("values")) for a in actions]
    if kinds != [("unit_cast_ability", ["self", "default_attack"]), ("unit_cast_ability", ["self", "counter_attack"])]:
        raise RuntimeError("assassin_upg passive layout changed; own attack / counterattack triggers not at passives[0]")
    for action in actions:
        action["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["passives"].append({"actions": actions})
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_1_icon"))


def kw_bulwark_regeneration(ctx, sid, logic, view, entry):
    action = ctx.donor("hydra_upg")["passives"][0]["actions"][1]
    mechs = [m.get("mech") for m in action["damageDealer"].get("targetMechanics", [])]
    if action.get("trigger") != "start_turn" or mechs != ["heal_percent"]:
        raise RuntimeError("hydra_upg passive layout changed; Regeneration not at passives[0].actions[1]")
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "magic_healing_water_effect_icon"))


def kw_bulwark_countershot(ctx, sid, logic, view, entry):
    default = logic["defaultAttacks"][0]
    if default.get("attackType_") != "shoot":
        raise RuntimeError(f"{sid}: 'bulwark_countershot' on a unit whose default attack does not shoot")
    donor = ctx.donor("medusa_upg_alt")["counterAttacks"][0]
    if donor.get("attackType_") != "shoot":
        raise RuntimeError("medusa_upg_alt counterAttacks[0] is no longer the Countershot")
    dealer = copy.deepcopy(default["damageDealer"])
    dealer["triggerCounter"] = False
    shot = {"attackType_": "shoot", "selfMechanics": [], "damageDealer": dealer}
    shot_view = {key: value for key, value in view["defaultAttacks"][0].items() if key in ("animationIndex", "projectile", "projectileSpeed", "trajectory")}
    if logic["counterAttacks"] and logic["counterAttacks"][0].get("attackType_") == "shoot":
        logic["counterAttacks"][0] = shot
        view["counterAttacks"][0] = shot_view
    else:
        logic["counterAttacks"].insert(0, shot)
        view["counterAttacks"].insert(0, shot_view)
    view["passives"].append({"name": "base_passive_countershot_name", "description": "base_passive_countershot_description", "icon": "crossbowman_buff_icon"})


def kw_bulwark_overwatch(ctx, sid, logic, view, entry):
    logic["stats"]["maxOverwatchStrikes"] = 999
    view["passives"].append(dt._card(sid, entry, "sub_skill_formation_4_overwatch_buff_icon"))


def kw_bulwark_extra_turn(ctx, sid, logic, view, entry):
    passive = ctx.donor("godslayer_upg_alt")["passives"][0]
    actions = passive.get("actions") or []
    mechs = [m.get("mech") for m in actions[0]["damageDealer"].get("targetMechanics", [])] if actions else []
    if passive.get("data", {}).get("stats", {}).get("maxAddedApPerRound") != 1 or mechs != ["add_action_points"]:
        raise RuntimeError("godslayer_upg_alt passive layout changed; Murderous Glee not at passives[0]")
    logic["passives"].append(passive)
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_2_icon"))


# --- 2026-11-21 ability variety pass -------------------------------------------------------------

def kw_bulwark_self_trigger_buff(ctx, sid, logic, view, entry):
    """hydra passive 0 action 0 (self action) on `trigger`; `conditions` replaces its triggerConditions; then either
    `buff` + `duration` or `dispel` (a list of buff tags, one dispel mechanic each, no buff)."""
    action = ctx.donor("hydra")["passives"][0]["actions"][0]
    dealer = action["damageDealer"]
    if action.get("trigger") != "unit_took_damage" or dealer.get("castTargetParams", {}).get("castTarget_") != "self":
        raise RuntimeError("hydra passive layout changed; self-buff action not at passives[0].actions[0]")
    action["trigger"] = entry["trigger"]
    if "conditions" in entry:
        action["triggerConditions"] = copy.deepcopy(entry["conditions"])
    if "dispel" in entry:
        dealer.pop("buff", None)
        dealer["targetMechanics"] = [{"mech": "dispel", "values": [tag]} for tag in entry["dispel"]]
    else:
        ctx.require_buff(entry["buff"], sid)
        dealer["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_tactics_4_defence_buff_icon"))


def kw_bulwark_stat(ctx, sid, logic, view, entry):  # stat keys on the unit block (qilin_selfbuff ignoreObstacles; native energy stats)
    for key, value in entry["stats"].items():
        logic["stats"][key] = copy.deepcopy(value)
    view["passives"].append(dt._card(sid, entry, "sub_skill_tactics_2_initiative_buff_icon"))


def kw_bulwark_pierce_attack(ctx, sid, logic, view, entry):  # Core pattern attack_reach_x1_x100_x50 on basic attacks
    for bucket in ("defaultAttacks", "counterAttacks"):
        for attack in logic[bucket]:
            dealer = attack["damageDealer"]
            dealer["attackPatternSid"] = "attack_reach_x1_x100_x50"
            dealer["affectTargetParams"]["castTarget_"] = "enemy"
            dealer["damageTarget_"] = "enemy"
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_2_icon"))


def _ally_cast(ctx, entry):
    """lightweaver ability 0 (single-ally buff cast) aimed at another friendly stack, free."""
    ability = ctx.donor("lightweaver")["abilities"][0]
    dealer = ability["damageDealer"]
    if ability.get("attackType_") != "cast" or dealer.get("attackPatternSid") != "attack_single_buff":
        raise RuntimeError("lightweaver ability 0 is no longer the single-target buff cast")
    dt._envelope(ability, entry)
    ability["actionCost"] = 0
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["castTarget_"] = "allynoself"
    return ability, dealer


def kw_bulwark_focus_gift(ctx, sid, logic, view, entry):
    """Another friendly stack gains Focus: add_energy with godslayer_upg's value layout ("energy", "ally", n, 0, 1)."""
    ability, dealer = _ally_cast(ctx, entry)
    dt._set_buff(dealer, {}, "ally")
    dealer["tags"] = ["ability", "buff_ability"]
    dealer["shootRange"] = entry["range"]
    dealer["targetMechanics"] = [{"mech": "add_energy", "values": ["energy", "ally", str(entry["focusGain"]), "0", "1"]}]
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_buff", "magic_energyze_effect_icon", 2, infoDescription="ability_no_turn"))


def kw_bulwark_grant_turn(ctx, sid, logic, view, entry):
    """unspeakable_upg ability 1 (free: add_action_points ["1"] + unspeakable_buff, whose maxAddedApPerRound 1 opens the
    cap), aimed at another friendly stack instead of itself, with `buff` (an unspeakable_buff clone)."""
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("unspeakable_upg")["abilities"][1]
    dealer = ability["damageDealer"]
    if [m.get("mech") for m in dealer.get("targetMechanics", [])] != ["add_action_points"] or ability.get("actionCost") != 0:
        raise RuntimeError("unspeakable_upg ability 1 is no longer the free add_action_points cast")
    dt._envelope(ability, entry)
    dealer.pop("instacast", None)
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["castTarget_"] = "allynoself"
        dealer[key]["selection"] = "object"
    dt._set_buff(dealer, entry, "ally")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_buff", "unspeakable_buff_icon", 2, infoDescription="ability_no_turn"))
