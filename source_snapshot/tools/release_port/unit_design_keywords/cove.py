"""Cove unit design keywords (custom_factions/unit_designs/homm3_cove.json).

Trade axis: boarding (melee rush) against broadside (gunpowder and Focus-fed shots). The broadside side of a
melee line gets its shot as a Focus ability (cove_focus_shot); the pirate and sea witch lines are shooters whose
boarding side gets full, unanswered melee (cove_duelist) and melee actives.

Every keyword adds exactly one card.
"""
from __future__ import annotations

import copy
from typing import Any

import homm3_unit_design_table as dt

ACTIVE = {"cove_focus_shot", "cove_debuff_cast", "cove_reposition", "cove_pull", "cove_pierce_shot", "cove_whirlpool"}

RANGED_MARKER = {"name": "h3_common_ranged_attack_name", "description": "h3_common_ranged_attack_description", "icon": "sub_skill_siege_1_icon"}


def _is_shooter(logic: dict[str, Any]) -> bool:
    return logic["defaultAttacks"][0].get("attackType_") == "shoot"


def _ensure_ranged_marker(view: dict[str, Any]) -> None:
    """Shooters keep one attack-type line; the generator's falloff variant is not a marker and is dropped by the rebuild."""
    if not any(p.get("name") == RANGED_MARKER["name"] for p in view["passives"]):
        view["passives"].insert(0, dict(RANGED_MARKER))


def kw_cove_duelist(ctx, sid, logic, view, entry):  # donors: halfling / trick_demon unpenalised melee; dragon_upg triggerCounter false
    """Shooter with a full-damage melee attack. noCounter: its melee attack is not counterattacked (Corsair).

    Also owns the row's typed outgoing damage list (the June contract left +10% shots on Pirate and Corsair
    with no card): the list is reset, and set again from entry["outMods"] when the card states a bonus.
    """
    if not _is_shooter(logic):
        raise RuntimeError(f"{sid}: cove_duelist is for shooters")
    for bucket in ("alternativeAttacks", "counterAttacks"):
        for attack in logic.get(bucket, []):
            dealer = attack["damageDealer"]
            dealer["statDmgMult"] = 1.0
            dealer["tags"] = [tag for tag in dealer.get("tags", []) if tag != dt.MELEE_PENALTY_TAG]
    for attack in logic.get("alternativeAttacks", []):
        attack["damageDealer"]["triggerCounter"] = not entry.get("noCounter", False)
    logic["stats"]["outDmgMods"] = {"list": [{"t": mod["t"], "v": mod["v"]} for mod in entry.get("outMods", [])]}
    _ensure_ranged_marker(view)
    card = dt._card(sid, entry, "sub_skill_assault_1_icon")
    view["passives"].append(card)
    for alt in view.get("alternativeAttacks", []):
        alt["description"] = card["description"]


def kw_cove_shot_buff(ctx, sid, logic, view, entry):  # donor: crossbowman_upg_alt debuff on a shot; here on the basic shot only
    """The basic shot applies a buff to its target (not the melee attack, not the counterattack)."""
    if not _is_shooter(logic):
        raise RuntimeError(f"{sid}: cove_shot_buff is for shooters")
    ctx.require_buff(entry["buff"], sid)
    dt._set_buff(logic["defaultAttacks"][0]["damageDealer"], entry, "enemy")
    _ensure_ranged_marker(view)
    view["passives"].append(dt._card(sid, entry, "magic_vulnerability_effect_icon"))


def kw_cove_focus_shot(ctx, sid, logic, view, entry):  # donor: crossbowman basic shot as a Focus ability on a melee unit
    """A ranged attack a melee unit pays Focus for. Shot rules (falloff, blocked when an enemy is adjacent) are the
    donor's. The projectile comes from entry["projectileFrom"] (any shooter's view row)."""
    if _is_shooter(logic):
        raise RuntimeError(f"{sid}: cove_focus_shot is for melee units; a shooter uses the shared 'shot' keyword")
    donor = ctx.donor("crossbowman")["defaultAttacks"][0]
    if donor.get("attackType_") != "shoot":
        raise RuntimeError("crossbowman default attack is no longer a shot")
    dealer = donor["damageDealer"]
    dealer["tags"] = list(dict.fromkeys([*dealer.get("tags", []), "ability", "debuff_ability" if "buff" in entry else "armed_ability"]))
    dealer["statDmgMult"] = entry["mult"]
    dealer["triggerCounter"] = False
    dealer["targetMechanics"] = []
    if "buff" in entry:
        ctx.require_buff(entry["buff"], sid)
    dt._set_buff(dealer, entry, "enemy")
    ability = {"attackType_": "shoot", "damageDealer": dealer}
    dt._envelope(ability, entry)
    logic["abilities"].append(ability)
    shot_view = ctx.donor(entry.get("projectileFrom", "crossbowman"), "v")["defaultAttacks"][0]
    extra = {key: shot_view[key] for key in ("projectile", "projectileSpeed", "trajectory") if key in shot_view}
    if "projectile" not in extra:
        raise RuntimeError(f"{sid}: projectile donor {entry.get('projectileFrom')!r} has no projectile on its basic attack")
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_attack_mod", "sub_skill_siege_2_icon", entry.get("anim", 0), **extra))


def kw_cove_ferocity(ctx, sid, logic, view, entry):  # donor: godslayer_upg_alt passive 0 (Murderous Glee)
    """Killing an enemy stack on its own turn gives this unit one more turn, at most once per round."""
    passive = ctx.donor("godslayer_upg_alt")["passives"][0]
    actions = passive.get("actions") or []
    mechs = [m.get("mech") for a in actions for m in a.get("damageDealer", {}).get("targetMechanics", [])]
    if len(actions) != 1 or actions[0].get("trigger") != "unit_died" or mechs != ["add_action_points"] \
            or passive.get("data", {}).get("stats", {}).get("maxAddedApPerRound") != 1:
        raise RuntimeError("godslayer_upg_alt passive layout changed; Murderous Glee not at passives[0]")
    logic["passives"].append(passive)
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_2_icon"))


def kw_cove_attack_ignore(ctx, sid, logic, view, entry):  # donor: inquisitor passive 0 (data.stats.attackPen)
    """Attackers count only part of their Attack against this unit. Stored as vanilla stores it (a passive's stats),
    which the power model does not read: trim the body with powerTarget."""
    donor = ctx.donor("inquisitor")["passives"][0]
    if "attackPen" not in donor.get("data", {}).get("stats", {}):
        raise RuntimeError("inquisitor passive 0 no longer carries attackPen")
    logic["passives"].append({"data": {"stats": {"attackPen": entry["v"]}}})
    view["passives"].append(dt._card(sid, entry, "sub_skill_units_attackPen_icon"))


def kw_cove_debuff_cast(ctx, sid, logic, view, entry):  # donor: aqualotl_upg_alt ability 1 (debuff cast on one enemy, any range)
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("aqualotl_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if ability.get("attackType_") != "cast" or dealer.get("buffTarget_") != "enemy" or dealer.get("damageTarget_") != "none":
        raise RuntimeError("aqualotl_upg_alt ability 1 is no longer the single-enemy debuff cast")
    dt._envelope(ability, entry)
    dt._set_buff(dealer, entry, "enemy")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_debuff", "wasp_debuff_icon", entry.get("anim", 2)))


def kw_cove_reposition(ctx, sid, logic, view, entry):  # donor: arbitrator ability 0 (Command: Reposition)
    """Free cast: move a friendly creature to a free hex within entry["range"] hexes of where it stands."""
    ability = ctx.donor("arbitrator")["abilities"][0]
    dealer = ability["damageDealer"]
    if [m.get("mech") for m in dealer.get("targetMechanics", [])] != ["teleport"] or len(dealer.get("orderedCastParams", [])) != 1:
        raise RuntimeError("arbitrator ability 0 is no longer the ally reposition cast")
    dt._envelope(ability, entry)
    ability["actionCost"] = 0
    for key in ("orderedCastParams", "orderedAffectParams"):
        dealer[key][0]["distanceFromFirst"] = entry["range"]
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_special", "magic_favorable_wind_effect_icon", 2,
                                              infoDescription="ability_no_turn"))


def kw_cove_scrappers(ctx, sid, logic, view, entry):  # donor: locust / h3_swordsman_upg data.sequenceEffect
    """If the target counterattacks, this unit attacks it again after the counterattack."""
    logic["passives"].append({"data": {"sequenceEffect": "add_attack_after_counter_melee"}})
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_1_icon"))


def kw_cove_pull(ctx, sid, logic, view, entry):  # donor: giant_frog ability 1 (Sticky Tongue)
    """Free cast on an adjacent empty hex: the enemy directly behind it is pulled into that hex."""
    ability = ctx.donor("giant_frog")["abilities"][1]
    dealer = ability["damageDealer"]
    if [m.get("mech") for m in dealer.get("targetMechanics", [])] != ["push_unit"]:
        raise RuntimeError("giant_frog ability 1 is no longer the pull cast")
    dt._envelope(ability, entry)
    ability["actionCost"] = 0
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_special", "crossbowman_debuff_icon", entry.get("anim", 2),
                                              infoDescription="ability_no_turn"))


def kw_cove_steal_on_hit(ctx, sid, logic, view, entry):  # donor: angel_upg steal_buffs layout
    """The unit's own melee attacks (a shooter's melee alternative attack, or a melee unit's basic attack) steal
    positive effects from the target (target mechanic steal_buffs, angel_upg values)."""
    bucket = "alternativeAttacks" if _is_shooter(logic) else "defaultAttacks"
    rows = [a for a in logic.get(bucket, []) if a.get("attackType_") == "melee"]
    if not rows:
        raise RuntimeError(f"{sid}: cove_steal_on_hit found no melee attack row")
    for attack in rows:
        mechs = attack["damageDealer"].setdefault("targetMechanics", [])
        mechs.append({"mech": "steal_buffs", "values": list(entry.get("values", ["true"]))})
    view["passives"].append(dt._card(sid, entry, "angel_buff_icon"))


def kw_cove_pierce_shot(ctx, sid, logic, view, entry):  # the row's own shot as a Focus ability with a pierce pattern
    """A shooter's Focus shot whose pattern also hits the hex behind the target (attack_reach_x1_x100_x50)."""
    dt.kw_shot(ctx, sid, logic, view, entry)
    logic["abilities"][-1]["damageDealer"]["attackPatternSid"] = entry["pattern"]


def kw_cove_push_on_hit(ctx, sid, logic, view, entry):  # donor: minos ability 0 push_unit_from_caster ["false"]
    """Push the target 1 hex away after the hit: on basic attacks (bucket defaultAttacks) or counterattacks."""
    bucket = entry["bucket"]
    if bucket not in ("defaultAttacks", "counterAttacks"):
        raise RuntimeError(f"{sid}: cove_push_on_hit bucket must be defaultAttacks or counterAttacks")
    donor = ctx.donor("minos")["abilities"][0]["damageDealer"]["targetMechanics"]
    if [m.get("mech") for m in donor] != ["push_unit_from_caster"]:
        raise RuntimeError("minos ability 0 no longer pushes the target")
    for attack in logic[bucket]:
        attack["damageDealer"].setdefault("targetMechanics", []).extend(copy.deepcopy(donor))
    view["passives"].append(dt._card(sid, entry, "magic_favorable_wind_effect_icon"))


def kw_cove_overwatch(ctx, sid, logic, view, entry):  # donor: qilin_upg_alt / sub_skill_formation_4 stats.maxOverwatchStrikes
    logic["stats"]["maxOverwatchStrikes"] = 999
    view["passives"].append(dt._card(sid, entry, "sub_skill_formation_4_overwatch_buff_icon"))


def kw_cove_whirlpool(ctx, sid, logic, view, entry):  # donor: aqualotl_upg ability 2 (Whirlpool pull toward a hex)
    """Pulls every stack within 2 hexes of the chosen hex toward it, and deals entry["mult"] of the stack's basic
    attack Damage as Magic Damage to each enemy in that area."""
    ability = ctx.donor("aqualotl_upg")["abilities"][2]
    dealer = ability["damageDealer"]
    if dealer.get("attackPatternSid") != "attack_rumble_x2_star_x100" or [m.get("mech") for m in dealer.get("targetMechanics", [])] != ["push_unit"]:
        raise RuntimeError("aqualotl_upg ability 2 is no longer the whirlpool pull")
    dt._envelope(ability, entry)
    ability.pop("actionCost", None)
    dealer["tags"] = ["ability", "magic_damage"]
    dealer["damageTarget_"] = "enemy"
    dealer["damageType_"] = "magic_pure"
    dealer["statDmgMult"] = entry["mult"]
    _drop_effect_immunity(logic, entry)  # Abyss Serpent: the removed Fearsome effect's stale immunity
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_special", "aqualotl_debuff_1_icon", 4))


def kw_cove_hide(ctx, sid, logic, view, entry):  # resist card that also retires a stale, uncarded effect immunity
    """Typed damage resistance like the shared 'resist', and drops effect immunities named in
    entry["dropEffectImmunity"] (Abyss Serpent's immunity to the removed Fearsome effect)."""
    mods = dt._in_dmg_list(logic)
    for mod in [entry, *entry.get("also", [])]:
        mods.append({"t": mod["t"], "v": mod["v"]})
    _drop_effect_immunity(logic, entry)
    view["passives"].append(dt._card(sid, entry, "sub_skill_resistance_1_icon"))


def _drop_effect_immunity(logic: dict[str, Any], entry: dict[str, Any]) -> None:
    """Drop effect immunities named in entry["dropEffectImmunity"] (stale, uncarded rows on the base Core row)."""
    drop = set(entry.get("dropEffectImmunity", []))
    if not drop:
        return
    kept = []
    for passive in logic["passives"]:
        immunities = passive.get("data", {}).get("immunities")
        if immunities is not None:
            left = [i for i in immunities if not (i.get("type") == "effect" and set(i.get("tags", [])) <= drop)]
            if not left and set(passive["data"]) == {"immunities"} and "actions" not in passive:
                continue
            passive = copy.deepcopy(passive)
            passive["data"]["immunities"] = left
        kept.append(passive)
    logic["passives"] = kept
