"""Factory (homm3_factory) kit keywords for the unit design table.

Trade axis: crewed (Repair, buffs and marks for the rest of the army) against automated (self-contained bodies
with their own immunities, self buffs and sustain). Every keyword adds exactly one card.
"""
from __future__ import annotations

import copy

import homm3_unit_design_table as dt

ACTIVE = {"factory_repair", "factory_cast_buff", "factory_pattern_strike", "factory_pattern_shot", "factory_rally_dispel"}

# Class tags of everything that is not a construct: a cast carrying them is refused by units whose class profile
# holds the matching `cast` immunity, the same way vanilla heals carry construct_immunities to skip constructs.
NON_CONSTRUCT_TAGS = ["living_immunities", "undead_immunities", "embodiment_immunities", "demon_immunities",
                      "dragon_immunities", "magic_creature_immunities", "avatar_immunities"]


def kw_factory_repair(ctx, sid, logic, view, entry):  # donor: lich ability 0 (Rewind Death), refused by every non-construct class
    ability = ctx.donor("lich")["abilities"][0]
    dealer = ability["damageDealer"]
    if dealer["castTargetParams"].get("castTarget_") != "allynoself" or [m.get("mech") for m in dealer["targetMechanics"]] != ["revive"]:
        raise RuntimeError("lich ability 0 is no longer the single-ally revive cast")
    if len(entry["values"]) != 4:
        raise RuntimeError(f"{sid}: factory_repair needs the four revive values")
    dt._envelope(ability, entry)
    ability["charges"] = entry["charges"]
    dealer["targetMechanics"] = [{"mech": "revive", "values": list(entry["values"])}]
    dealer["tags"] = ["ability", "heal_ability", "revive_ability", *NON_CONSTRUCT_TAGS]
    # Constructs only: the cast and its effect accept just the rows apply_design_tags marks as constructs.
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["targetTags"] = [dt.CONSTRUCT_TAG]
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_special", "magic_healing_water_effect_icon", 2))


def kw_factory_cast_buff(ctx, sid, logic, view, entry):  # donor: lightweaver_upg ability 0 (buff cast on one ally)
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("lightweaver_upg")["abilities"][0]
    dealer = ability["damageDealer"]
    if dealer.get("buffTarget_") != "ally" or dealer.get("damageTarget_") != "none":
        raise RuntimeError("lightweaver_upg ability 0 is no longer the single-ally buff cast")
    dt._envelope(ability, entry)
    target = entry["target"]  # ally | allynoself | enemy
    enemy = target == "enemy"
    dealer["tags"] = ["ability", "debuff_ability" if enemy else "buff_ability"]
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["castTarget_"] = target
        dealer[key]["selection"] = "object"
    dt._set_buff(dealer, entry, "enemy" if enemy else "ally")
    if "range" in entry:  # the donor cast reaches the whole field; shootRange limits it (as on kw_cleanse)
        dealer["shootRange"] = entry["range"]
    if entry.get("free"):
        ability["actionCost"] = 0
    else:
        ability.pop("actionCost", None)
    extra = {"infoDescription": "ability_no_turn"} if entry.get("free") else {}
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_debuff" if enemy else "Ability_type_buff", "skill_tactics", 2, **extra))
    logic["abilities"].append(ability)


def kw_factory_pattern_strike(ctx, sid, logic, view, entry):  # godslayer's Focus strike with another attack shape (hydra sweep, wave)
    ability = ctx.donor("godslayer")["abilities"][0]
    dt._envelope(ability, entry)
    dealer = ability["damageDealer"]
    dealer["attackPatternSid"] = entry["pattern"]
    dealer["statDmgMult"] = entry.get("mult", 1.0)
    dealer["triggerCounter"] = entry.get("counter", False)
    if "buff" in entry:
        ctx.require_buff(entry["buff"], sid)
    dt._set_buff(dealer, entry, "enemy")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_attack_mod", "sub_skill_assault_2_icon", 0))


def kw_factory_pattern_shot(ctx, sid, logic, view, entry):  # the unit's own shot with an area shape (lich_upg shoots a rumble)
    dt.kw_shot(ctx, sid, logic, view, entry)
    logic["abilities"][-1]["damageDealer"]["attackPatternSid"] = entry["pattern"]


def kw_factory_stat(ctx, sid, logic, view, entry):  # plain stat keys the shared library has no keyword for (armorPen)
    allowed = {"armorPen", "ignoreShootingBlock"}
    if set(entry["stats"]) - allowed:
        raise RuntimeError(f"{sid}: factory_stat only sets {sorted(allowed)}")
    logic["stats"].update(copy.deepcopy(entry["stats"]))
    view["passives"].append(dt._card(sid, entry, "sub_skill_units_attackPen_icon"))


def kw_factory_first_strike(ctx, sid, logic, view, entry):  # donor: vanilla counter_before_attack sequence effect (Parry)
    logic["passives"].append({"data": {"sequenceEffect": "counter_before_attack"}})
    view["passives"].append({"name": "base_passive_alert_name", "description": "base_passive_alert_description", "icon": "skill_tactics"})


def kw_factory_countershot(ctx, sid, logic, view, entry):  # the row's own ranged counterattack, at full damage
    shots = [attack for attack in logic.get("counterAttacks", []) if attack.get("attackType_") == "shoot"]
    if not shots:
        raise RuntimeError(f"{sid}: factory_countershot needs a ranged counterattack on the row")
    for attack in shots:
        dealer = attack["damageDealer"]
        dealer["statDmgMult"] = 1.0
        dealer["tags"] = [tag for tag in dealer.get("tags", []) if tag != dt.MELEE_PENALTY_TAG]
    view["passives"].append({"name": "base_passive_countershot_name", "description": "base_passive_countershot_description", "icon": "sub_skill_siege_2_icon"})


def kw_factory_reach_attack(ctx, sid, logic, view, entry):  # donor: h3_mechanic's reach basic attack and counterattack pattern
    """Basic attack and counterattack also hit the creature on the hex directly behind the target."""
    pattern = ctx.donor("h3_mechanic")["defaultAttacks"][0]["damageDealer"]["attackPatternSid"]
    if not pattern.startswith("attack_reach_"):
        raise RuntimeError("h3_mechanic's basic attack is no longer a reach pattern")
    for bucket in ("defaultAttacks", "counterAttacks"):
        for attack in logic.get(bucket, []):
            if attack.get("attackType_") != "melee":
                raise RuntimeError(f"{sid}: factory_reach_attack on a non-melee attack row")
            attack["damageDealer"]["attackPatternSid"] = pattern
    view["passives"].append(dt._card(sid, entry, "skill_tactics"))


def _hydra_self_action(ctx) -> dict:  # hydra passive 0 action 0: self buff from a self-triggered passive action
    action = ctx.donor("hydra")["passives"][0]["actions"][0]
    if action.get("trigger") != "unit_took_damage" or action["damageDealer"].get("damageTarget_") != "none":
        raise RuntimeError("hydra passive 0 action 0 is no longer the self buff on damage taken")
    return action


def kw_factory_defend_pulse(ctx, sid, logic, view, entry):  # donor: hydra passive 0 action 0, trigger unit_skip (Defend)
    """When this unit Defends, friendly creatures adjacent to it get entry["buff"] (rumble x1 around self)."""
    ctx.require_buff(entry["buff"], sid)
    action = _hydra_self_action(ctx)
    action["trigger"] = "unit_skip"
    dealer = action["damageDealer"]
    dealer["attackPatternSid"] = "attack_rumble_x1_x100"
    dealer["affectTargetParams"]["castTarget_"] = "allynoself"
    dealer["affectTargetParams"]["targetCondition_"] = "alive"
    dealer["affectTargetParams"].pop("selection", None)
    dt._set_buff(dealer, entry, "ally")
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_tactics_4_defence_buff_icon"))


def kw_factory_wait_burrow(ctx, sid, logic, view, entry):  # donor: hydra passive 0 action 0, trigger unit_wait
    """When this unit Waits it gets entry["buff"] (the untargetable burrow buff)."""
    ctx.require_buff(entry["buff"], sid)
    action = _hydra_self_action(ctx)
    action["trigger"] = "unit_wait"
    dt._set_buff(action["damageDealer"], entry, "all")
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "magic_shade_cloak_effect_icon"))


def kw_factory_rally_dispel(ctx, sid, logic, view, entry):  # kw_rally envelope (minos_upg_alt ability 1) + inquisitor's tag dispel
    """Free action: removes every effect tagged entry["tag"] (movementNegative) from adjacent friendly creatures."""
    ability = ctx.donor("minos_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if dealer.get("attackPatternSid") != "attack_rumble_x1_x100":
        raise RuntimeError("minos_upg_alt ability 1 is no longer the rumble-from-self cast")
    dt._envelope(ability, entry)
    ability["actionCost"] = 0
    dealer["tags"] = ["ability", "buff_ability", "dispel_ability"]
    dealer["affectTargetParams"]["castTarget_"] = "allynoself"
    dt._set_buff(dealer, {}, "ally")
    dealer["targetMechanics"] = [{"mech": "dispel", "values": [entry["tag"]]}]
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_buff", "skill_tactics", 2, infoDescription="ability_no_turn"))


def kw_factory_death_blast(ctx, sid, logic, view, entry):  # donor: lava_larva passive 0 (explodes on death)
    action = ctx.donor("lava_larva")["passives"][0]["actions"][0]
    dealer = action["damageDealer"]
    if action.get("trigger") != "unit_died" or dealer.get("attackPatternSid") != "attack_rumble_x1_x100":
        raise RuntimeError("lava_larva passive 0 is no longer the death explosion")
    dealer["tags"] = ["passive", "magic_damage"]
    dealer["minBaseDmg"] = dealer["maxBaseDmg"] = entry["damage"]
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_2_icon"))
