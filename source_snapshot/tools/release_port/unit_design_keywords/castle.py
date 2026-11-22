"""Castle unit-design keywords (Cleave vs Lance axis). Loaded by homm3_unit_design_table._load_extensions.

Every keyword adds exactly one card. Donors are named per keyword; all are vanilla rows or vanilla data keys.
"""

from __future__ import annotations

import copy

import homm3_unit_design_table as dt

ACTIVE = {"castle_strike", "castle_shot", "castle_ally_buff", "castle_guillotine", "castle_keep_from", "castle_free_ally_buff",
          "castle_steal_area"}

MELEE_SHAPES = {
    "attack_swipe_x100_x50",        # target, plus the two hexes beside it at half damage
    "attack_swipe_x100_x100",       # hydra / phoenix default attack
    "attack_swirl_with_target_x100_x50",
    "attack_swirl_with_target_x100",
    "attack_reach_x1_x100_x50",     # target, plus the hex behind it at half damage
    "attack_reach_x2_x100_x100_x100",
    "attack_single_x100",
}
SHOT_SHAPES = {
    "attack_rumble_x1_x100_x50",    # star_child default shot: target hex, adjacent hexes at half damage
    "attack_rumble_x1_x100_x25",
    "attack_single_x100",
}


def _enemy_only(dealer: dict) -> None:
    """Shapes land on enemies only (hydra swipe / lich_upg cloud form), never on friendly stacks."""
    for key in ("castTargetParams", "affectTargetParams"):
        dealer[key]["castTarget_"] = "enemy"
    dealer["damageTarget_"] = "enemy"


def _add_unit_tag(logic: dict, tag: str) -> None:
    tags = logic.setdefault("tags", [])
    if tag not in tags:
        tags.append(tag)


def kw_castle_cleave(ctx, sid, logic, view, entry):
    """Shaped basic attack. Donors: hydra / lesser_eldritch_upg_alt (swipe on default + counter attack),
    star_child / lich_upg (area shape on a default shot). entry: pattern, buckets (default: defaultAttacks and,
    for melee units, counterAttacks)."""
    pattern = entry["pattern"]
    shooter = logic["defaultAttacks"][0].get("attackType_") == "shoot"
    if pattern not in (SHOT_SHAPES if shooter else MELEE_SHAPES):
        raise RuntimeError(f"{sid}: castle_cleave pattern {pattern!r} is not a listed {'shot' if shooter else 'melee'} shape")
    if "buckets" in entry:
        if shooter or not entry["buckets"] or not set(entry["buckets"]) <= {"defaultAttacks", "counterAttacks"}:
            raise RuntimeError(f"{sid}: castle_cleave buckets {entry['buckets']!r} must be melee defaultAttacks/counterAttacks")
        targets = [attack for bucket in entry["buckets"] for attack in logic[bucket]]
    elif shooter:
        targets = [logic["defaultAttacks"][0]]
    else:
        targets = list(logic["defaultAttacks"])
        if entry.get("counter", True):
            targets += list(logic["counterAttacks"])
    for attack in targets:
        dealer = attack["damageDealer"]
        dealer["attackPatternSid"] = pattern
        _enemy_only(dealer)
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_2_icon"))


def kw_castle_stat(ctx, sid, logic, view, entry):
    """Plain stat-key passive. Donors: assassin_selfbuff (armorPen), snow-elf style ignoreShootingBlock,
    crossbowman_buff_1 (outDmgMods typed bonus). entry: stats {key: value}; outDmgMods given as a list."""
    allowed = {"armorPen", "attackPen", "ignoreShootingBlock", "outDmgMods", "outDmgModsByTargetTags"}
    for key, value in entry["stats"].items():
        if key not in allowed:
            raise RuntimeError(f"{sid}: castle_stat does not own stat key {key!r}")
        if key == "outDmgMods":
            logic["stats"]["outDmgMods"] = {"list": [{"t": mod["t"], "v": mod["v"]} for mod in value]}
        elif key == "outDmgModsByTargetTags":  # dragon_hunter's tag-keyed slot; appends so Hatred cards keep theirs
            mods = logic["stats"].setdefault("outDmgModsByTargetTags", {"list": []})
            mods.setdefault("list", []).extend({"t": mod["t"], "v": mod["v"]} for mod in value)
        else:
            logic["stats"][key] = copy.deepcopy(value)
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_1_icon"))


def kw_castle_first_strike(ctx, sid, logic, view, entry):
    """Counterattacks land before the attacker's blow (sequence effect counter_before_attack: vanilla Alert
    passive / Masterful Parry buff)."""
    logic["passives"].append({"data": {"sequenceEffect": "counter_before_attack"}})
    view["passives"].append(dt._card(sid, entry, "skill_tactics"))


def kw_castle_set_pikes(ctx, sid, logic, view, entry):
    """Counterattacks strike first while the stack has not acted this round; Wait and Defend do not count.

    The buff (entry["buff"]: counter_before_attack, cloned from assassin_buff_start) is granted at round start
    (assassin_upg_alt's start_round passive) and dispels itself when the stack's turn starts. Waiting or Defending
    grants it again for the rest of the round (unit_wait / unit_skip self triggers, as formation_5 preparation does),
    so only a move, an attack or an ability leaves the stack without it.
    """
    ctx.require_buff(entry["buff"], sid)
    grant = ctx.donor("assassin_upg_alt")["passives"][0]["actions"][0]
    if grant.get("trigger") != "start_round" or grant["damageDealer"].get("buff", {}).get("sid") != "assassin_buff_start":
        raise RuntimeError("assassin_upg_alt passive layout changed; start_round grant not at passives[0].actions[0]")
    grant["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": 1}
    actions = [grant]
    for trigger in ("unit_wait", "unit_skip"):
        regrant = copy.deepcopy(grant)
        regrant["trigger"] = trigger
        regrant["triggerConditions"] = [{"checkFunction": "allegiance", "values": ["self"]}]
        actions.append(regrant)
    logic["passives"].append({"actions": actions})
    view["passives"].append(dt._card(sid, entry, "skill_tactics"))


def kw_castle_guillotine(ctx, sid, logic, view, entry):
    """Focus melee execution: the Decimate dealer (space_11_magic_decimate level 1: Pure Damage from 30% of the
    target creature's maximum Health, magic_decimate_effect stacking +100% per recast) on godslayer's melee ability
    envelope. entry: focus, cd, [pct]."""
    doc = ctx.read(ctx.release_zip, ctx.output, "DB/magics/battle_space_magics.json")
    spell = next((row for row in doc["array"] if row.get("id") == "space_11_magic_decimate"), None)
    if spell is None:
        raise RuntimeError("castle_guillotine: space_11_magic_decimate spell row not found")
    dealer = copy.deepcopy(spell["battleMagic"]["magicDealers"][0])
    if dealer.get("percentDamage") != "max_unit" or dealer.get("buff", {}).get("sid") != "magic_decimate_effect":
        raise RuntimeError("space_11_magic_decimate level 1 dealer is no longer the max_unit decimate")
    pct = entry.get("pct", dealer["minPercentDmg"])
    dealer["minPercentDmg"] = dealer["maxPercentDmg"] = pct
    dealer["tags"] = list(dict.fromkeys(["ability", *dealer["tags"]]))
    dealer["triggerCounter"] = entry.get("counter", False)
    ability = ctx.donor("godslayer")["abilities"][0]
    if ability.get("attackType_") != "melee":
        raise RuntimeError("godslayer ability 0 is no longer a melee ability")
    dt._envelope(ability, entry)
    ability["damageDealer"] = dealer
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_debuff", "sub_skill_assault_2_icon", 0))


def kw_castle_strike(ctx, sid, logic, view, entry):
    """Focus melee strike with a shape. Donors: godslayer ability 0 (armed melee ability), inquisitor ability 1 /
    avatar_of_war_upg_alt ability 0 (shaped melee ability). entry: focus, cd, mult, pattern, counter, [buff, duration]."""
    pattern = entry.get("pattern", "attack_single_x100")
    if pattern not in MELEE_SHAPES:
        raise RuntimeError(f"{sid}: castle_strike pattern {pattern!r} is not a listed melee shape")
    ability = ctx.donor("godslayer")["abilities"][0]
    dt._envelope(ability, entry)
    dealer = ability["damageDealer"]
    dealer["attackPatternSid"] = pattern
    dealer["statDmgMult"] = entry.get("mult", 1.0)
    dealer["triggerCounter"] = entry["counter"]
    _enemy_only(dealer)
    if "buff" in entry:
        ctx.require_buff(entry["buff"], sid)
    dt._set_buff(dealer, entry, "enemy")
    if "unitTag" in entry:  # the buff's tag-keyed exemption reads this unit tag (Challenge)
        _add_unit_tag(logic, entry["unitTag"])
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_attack_mod", "sub_skill_assault_2_icon", 0))


def kw_castle_shot(ctx, sid, logic, view, entry):
    """Focus shot built from the unit's own shot, optionally with an area shape (star_child default shot shape;
    medusa_upg_alt ability 1 is the vanilla shaped Focus shot). entry: focus, cd, mult, pattern, [buff, duration]."""
    default = logic["defaultAttacks"][0]
    if default.get("attackType_") != "shoot":
        raise RuntimeError(f"{sid}: castle_shot on a unit whose default attack does not shoot")
    pattern = entry.get("pattern", "attack_single_x100")
    if pattern not in SHOT_SHAPES:
        raise RuntimeError(f"{sid}: castle_shot pattern {pattern!r} is not a listed shot shape")
    dealer = copy.deepcopy(default["damageDealer"])
    dealer["tags"] = list(dict.fromkeys([*dealer.get("tags", []), "ability", "debuff_ability" if "buff" in entry else "armed_ability"]))
    dealer["attackPatternSid"] = pattern
    dealer["statDmgMult"] = entry["mult"]
    dealer["triggerCounter"] = False
    _enemy_only(dealer)
    if "buff" in entry:
        ctx.require_buff(entry["buff"], sid)
    dt._set_buff(dealer, entry, "enemy")
    ability = {"attackType_": "shoot", "damageDealer": dealer}
    dt._envelope(ability, entry)
    logic["abilities"].append(ability)
    shot_view = view["defaultAttacks"][0]
    extra = {key: shot_view[key] for key in ("projectile", "projectileSpeed", "trajectory") if key in shot_view}
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_attack_mod", "sub_skill_siege_2_icon", 1, **extra))


def kw_castle_ally_buff(ctx, sid, logic, view, entry):
    """Buff one friendly stack (lightweaver ability 0: single-target ally buff cast). entry: focus, cd, buff, duration."""
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("lightweaver")["abilities"][0]
    dealer = ability["damageDealer"]
    if dealer.get("buffTarget_") != "ally" or dealer.get("attackPatternSid") != "attack_single_buff":
        raise RuntimeError("lightweaver ability 0 is no longer the single-target ally buff cast")
    dt._envelope(ability, entry)
    dt._set_buff(dealer, entry, "ally")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_buff", "skill_tactics", 2))


def kw_castle_pinning_talons(ctx, sid, logic, view, entry):
    """Basic attacks and counterattacks remove counterattacks: target mechanic reduce_counters (unfrozen_cultist_upg
    ability 1) on the default and counter dealers. entry: [n] (default 1)."""
    mech = None
    for ability in ctx.donor("unfrozen_cultist_upg")["abilities"]:
        for candidate in ability["damageDealer"].get("targetMechanics", []):
            if candidate.get("mech") == "reduce_counters":
                mech = copy.deepcopy(candidate)
    if mech is None:
        raise RuntimeError("unfrozen_cultist_upg no longer carries reduce_counters")
    mech["values"] = [str(entry.get("n", 1))]
    for bucket in ("defaultAttacks", "counterAttacks"):
        for attack in logic[bucket]:
            attack["damageDealer"].setdefault("targetMechanics", []).append(copy.deepcopy(mech))
    view["passives"].append(dt._card(sid, entry, "skill_tactics"))


def kw_castle_extra_turn(ctx, sid, logic, view, entry):
    """Destroying a stack on its own turn grants one more action, once per round: godslayer_upg_alt passives[0]
    (unit_died + allegiance_both [self, enemy] + is_active_unit -> add_action_points, maxAddedApPerRound 1).
    Same donor and guard as bulwark_extra_turn."""
    passive = ctx.donor("godslayer_upg_alt")["passives"][0]
    actions = passive.get("actions") or []
    mechs = [m.get("mech") for m in actions[0]["damageDealer"].get("targetMechanics", [])] if actions else []
    if passive.get("data", {}).get("stats", {}).get("maxAddedApPerRound") != 1 or mechs != ["add_action_points"]:
        raise RuntimeError("godslayer_upg_alt passive layout changed; Murderous Glee not at passives[0]")
    logic["passives"].append(passive)
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_2_icon"))


def kw_castle_keep_from(ctx, sid, logic, view, entry):
    """Copy another unit's ability (logic + view card) by its view card name. entry: from, view.
    The source row is read as the overlay has it (Champion takes the Cavalier's Cavalry Press)."""
    src_logic, src_view = ctx.donor(entry["from"]), ctx.donor(entry["from"], "v")
    pairs = [(l, v) for l, v in zip(src_logic.get("abilities", []), src_view.get("abilities", [])) if v.get("name") == entry["view"]]
    if len(src_logic.get("abilities", [])) != len(src_view.get("abilities", [])) or len(pairs) != 1:
        raise RuntimeError(f"{sid}: castle_keep_from {entry['from']}/{entry['view']} matched {len(pairs)} abilities")
    logic["abilities"].append(copy.deepcopy(pairs[0][0]))
    view["abilities"].append(copy.deepcopy(pairs[0][1]))


def kw_castle_free_ally_buff(ctx, sid, logic, view, entry):
    """Free (no action) buff on one friendly stack within range: sunlight_cavalry_upg ability 0 (instacast single ally
    buff, actionCost 0) with a cast range. entry: focus, cd, buff, duration, range."""
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("sunlight_cavalry_upg")["abilities"][0]
    dealer = ability["damageDealer"]
    if ability.get("actionCost") != 0 or dealer.get("attackPatternSid") != "attack_single_buff" or dealer.get("buffTarget_") != "ally":
        raise RuntimeError("sunlight_cavalry_upg ability 0 is no longer the free single-ally buff cast")
    dt._envelope(ability, entry)
    dealer["shootRange"] = entry["range"]
    dt._set_buff(dealer, entry, "ally")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_buff", "skill_tactics", 2, infoDescription="ability_no_turn"))


def kw_castle_ally_death_buff(ctx, sid, logic, view, entry):
    """Whenever a friendly stack dies, buff this creature: avatar_of_war_upg_alt passives[0].actions[0] (unit_died,
    allegiance ally, self buff). Stacking comes from the buff row (addition data). entry: buff, duration."""
    ctx.require_buff(entry["buff"], sid)
    action = ctx.donor("avatar_of_war_upg_alt")["passives"][0]["actions"][0]
    if action.get("trigger") != "unit_died" or action["triggerConditions"][0].get("values") != ["ally"]:
        raise RuntimeError("avatar_of_war_upg_alt passive layout changed; ally-death self buff not at passives[0].actions[0]")
    action["damageDealer"]["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_1_icon"))


def kw_castle_steal_area(ctx, sid, logic, view, entry):
    """Steal positive effects from enemies around a chosen hex: angel_upg ability 1 (Devouring Chalice, steal_buffs
    ["true"], rumble x1 on any hex; vanilla keeps it off the AI). entry: focus, cd."""
    ability = ctx.donor("angel_upg")["abilities"][1]
    dealer = ability["damageDealer"]
    if [m.get("mech") for m in dealer.get("targetMechanics", [])] != ["steal_buffs"] or dealer.get("attackPatternSid") != "attack_rumble_x1_x100":
        raise RuntimeError("angel_upg ability 1 is no longer the area steal_buffs cast")
    dt._envelope(ability, entry)
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_debuff", "skill_tactics", 2))
