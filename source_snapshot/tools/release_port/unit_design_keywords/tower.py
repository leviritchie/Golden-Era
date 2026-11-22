"""Tower keywords for the unit design table (custom_factions/unit_designs/homm3_tower.json).

Each keyword edits the unit's logic and view rows in place and adds exactly one card.
"""

from __future__ import annotations

import copy

import homm3_unit_design_table as dt

ACTIVE = {"tower_ally_buff", "tower_lodestone_draw"}


def kw_tower_battle_caster(ctx, sid, logic, view, entry):
    """Shooter that is not blocked by adjacent enemies and strikes at full damage in melee.

    Native keys: stats.ignoreShootingBlock (aqualotl_wisp_buff_1, already on the Mage and Titan rows) and the
    unpenalised melee alternative attack (halfling, trick_demon; same edit as the shared 'skirmisher').
    The Mage and Titan shots carry no range falloff in their rows (shootDmgBuff 0), which the card states.
    """
    default = logic["defaultAttacks"][0]
    if default.get("attackType_") != "shoot":
        raise RuntimeError(f"{sid}: 'tower_battle_caster' on a unit whose default attack does not shoot")
    default["damageDealer"]["shootDmgBuff"] = 0.0
    logic["stats"]["ignoreShootingBlock"] = True
    for bucket in ("alternativeAttacks", "counterAttacks"):
        for attack in logic.get(bucket, []):
            dealer = attack["damageDealer"]
            dealer["statDmgMult"] = 1.0
            dealer["tags"] = [tag for tag in dealer.get("tags", []) if tag != dt.MELEE_PENALTY_TAG]
    card = dt._card(sid, entry, "crossbowman_buff_icon")
    view["passives"].append(card)
    for alt in view.get("alternativeAttacks", []):
        alt["description"] = card["description"]


def kw_tower_channeler(ctx, sid, logic, view, entry):
    """Friendly hero's spells cost less mana (the Mage row's own sideModifiers passive; mirror of succubus)."""
    value = entry["v"]
    logic["passives"].append({"data": {"sideModifiers": [
        {"tag": "homm3_tower_magic_channeler", "power": value, "heroStat": {"manaCostBonus": -value}, "target": "ally"}]}})
    view["passives"].append(dt._card(sid, entry, "magic_nairas_kiss_effect_icon"))


def kw_tower_ally_buff(ctx, sid, logic, view, entry):
    """Free action: put a buff on one friendly creature (sunlight_cavalry_upg ability 0, own buff and numbers)."""
    ctx.require_buff(entry["buff"], sid)
    for rotated in entry.get("rotate", []):  # the plugin swaps entry["buff"] for these in turn (Homm3UnitKitRuntime)
        ctx.require_buff(rotated, sid)
    ability = ctx.donor("sunlight_cavalry_upg")["abilities"][0]
    dealer = ability["damageDealer"]
    if ability.get("attackType_") != "cast" or dealer.get("buffTarget_") != "ally" or ability.get("actionCost") != 0:
        raise RuntimeError("sunlight_cavalry_upg ability 0 is no longer the free single-ally buff cast")
    dt._envelope(ability, entry)
    target = "allynoself" if entry.get("noSelf", True) else "ally"
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["castTarget_"] = target
    dt._set_buff(dealer, entry, "ally")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_buff", "skill_tactics", 2, infoDescription="ability_no_turn"))


def kw_tower_wait_buff(ctx, sid, logic, view, entry):
    """Waiting or Defending buffs this creature: assassin_upg_alt's self-buff grant (passives[0].actions[0]) moved to
    the unit_wait / unit_skip self triggers (the castle Set Pikes re-grant shape). entry: buff, duration."""
    ctx.require_buff(entry["buff"], sid)
    grant = ctx.donor("assassin_upg_alt")["passives"][0]["actions"][0]
    if grant.get("trigger") != "start_round" or "buff" not in grant["damageDealer"]:
        raise RuntimeError("assassin_upg_alt passive layout changed; start_round grant not at passives[0].actions[0]")
    grant["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    actions = []
    for trigger in ("unit_wait", "unit_skip"):
        regrant = copy.deepcopy(grant)
        regrant["trigger"] = trigger
        regrant["triggerConditions"] = [{"checkFunction": "allegiance", "values": ["self"]}]
        actions.append(regrant)
    logic["passives"].append({"actions": actions})
    view["passives"].append(dt._card(sid, entry, "skill_tactics"))


def kw_tower_round_ramp(ctx, sid, logic, view, entry):
    """At every round start this creature gains a buff (assassin_upg_alt passives[0].actions[0], start_round +
    owner_alive). A cap comes from the plugin's escalate chain on the entry. entry: buff, duration, [escalate]."""
    ctx.require_buff(entry["buff"], sid)
    for chained in entry.get("escalate", {}).get("chain", []):
        ctx.require_buff(chained, sid)
    grant = ctx.donor("assassin_upg_alt")["passives"][0]["actions"][0]
    if grant.get("trigger") != "start_round" or "buff" not in grant["damageDealer"]:
        raise RuntimeError("assassin_upg_alt passive layout changed; start_round grant not at passives[0].actions[0]")
    grant["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["passives"].append({"actions": [grant]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_1_icon"))


def kw_tower_counter_buff(ctx, sid, logic, view, entry):
    """on_hit_buff on counterattacks only (ent counter-attack buff slot). entry: buff, duration."""
    ctx.require_buff(entry["buff"], sid)
    for attack in logic["counterAttacks"]:
        dt._set_buff(attack["damageDealer"], entry, "enemy")
    view["passives"].append(dt._card(sid, entry, "skill_tactics"))


def kw_tower_lodestone_draw(ctx, sid, logic, view, entry):
    """Free action: take every negative effect off friendly stacks around this creature onto itself.
    minos_upg_alt ability 1 (instacast rumble from self, actionCost 0) aimed at allies, with steal_buffs ["false"]
    (MechStealBuffs: values[0] false = non-positive buffs, dispelled from the target and added to the caster).
    entry: focus, cd, [pattern] (default attack_rumble_x2_x100: 2-hex radius)."""
    ability = ctx.donor("minos_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if dealer.get("attackPatternSid") != "attack_rumble_x1_x100" or ability.get("actionCost") != 0 \
            or dealer["castTargetParams"].get("castTarget_") != "self":
        raise RuntimeError("minos_upg_alt ability 1 is no longer the free rumble-from-self cast")
    dt._envelope(ability, entry)
    dealer["attackPatternSid"] = entry.get("pattern", "attack_rumble_x2_x100")
    dealer["tags"] = ["ability", "buff_ability", "dispel_ability"]
    dealer["affectTargetParams"]["castTarget_"] = "allynoself"
    dealer["damageTarget_"] = "none"
    dt._set_buff(dealer, {}, "ally")
    dealer["targetMechanics"] = [{"mech": "steal_buffs", "values": ["false"]}]
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_buff", "skill_tactics", 2, infoDescription="ability_no_turn"))
