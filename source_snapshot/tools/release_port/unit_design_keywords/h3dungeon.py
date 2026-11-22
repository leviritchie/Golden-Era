"""Unit design keywords for homm3_dungeon (trade axis Reckless vs Sustained).

Loaded by homm3_unit_design_table._load_extensions. Every keyword adds exactly one card.
All mechanics are native Core data keys cloned from vanilla rows; no plugin rule is needed.
"""
from __future__ import annotations

import copy

import homm3_unit_design_table as dt

ACTIVE: set[str] = set()


def _replace_mod(stats: dict, key: str, tag: str, value: float) -> None:
    mods = stats.setdefault(key, {"list": []}).setdefault("list", [])
    mods[:] = [mod for mod in mods if mod.get("t") != tag]
    mods.append({"t": tag, "v": value})


def kw_h3dungeon_reckless(ctx, sid, logic, view, entry):
    """Deals more with its own attack type, takes more from basic attacks.

    Typed damage lists on the unit stat block: inDmgMods as esquire / animated_armor use it, outDmgMods in the
    form crossbowman_buff_1 carries it ({"t": "shoot_attack", "v": 0.2}). entry: outType, out, taken.
    """
    stats = logic["stats"]
    _replace_mod(stats, "outDmgMods", entry["outType"], entry["out"])
    stats.setdefault("inDmgMods", {"list": []}).setdefault("list", []).append({"t": "basic_attack", "v": entry["taken"]})
    view["passives"].append(dt._card(sid, entry, "hydra_selfbuff_icon"))


def kw_h3dungeon_first_strike(ctx, sid, logic, view, entry):
    """Counterattacks before the attacker's blow lands (elf_tracker / minos_upg sequence effect)."""
    logic["passives"].append({"data": {"sequenceEffect": "counter_before_attack"}})
    view["passives"].append(dt._card(sid, entry, "skill_tactics"))


def kw_h3dungeon_life_drain(ctx, sid, logic, view, entry):
    """Attacks and counterattacks restore a share of the damage dealt and can revive (vampire self mechanic)."""
    donor = ctx.donor("vampire")["defaultAttacks"][0]["selfMechanics"]
    if len(donor) != 1 or donor[0].get("mech") != "vampirism" or len(donor[0].get("values") or []) != 4:
        raise RuntimeError("vampire default attack no longer carries the four-value vampirism self mechanic")
    for bucket in ("defaultAttacks", "counterAttacks", "alternativeAttacks"):
        for attack in logic.get(bucket) or []:
            mech = copy.deepcopy(donor[0])
            mech["values"][1] = str(entry["v"])
            kept = [m for m in attack.get("selfMechanics") or [] if m.get("mech") != "vampirism"]
            attack["selfMechanics"] = [*kept, mech]
    view["passives"].append(dt._card(sid, entry, "magic_healing_water_effect_icon"))


def kw_h3dungeon_regeneration(ctx, sid, logic, view, entry):
    """Start of own turn: the wounded top creature is healed to full, no revive (hydra_upg Regeneration)."""
    action = ctx.donor("hydra_upg")["passives"][0]["actions"][1]
    mechs = action["damageDealer"].get("targetMechanics") or []
    if action.get("trigger") != "start_turn" or [m.get("mech") for m in mechs] != ["heal_percent"]:
        raise RuntimeError("hydra_upg passive layout changed; Regeneration action not at passives[0].actions[1]")
    logic["passives"].append({"actions": [action]})
    view["passives"].append(dt._card(sid, entry, "magic_healing_water_effect_icon"))


def kw_h3dungeon_bravery(ctx, sid, logic, view, entry):
    """Morale floor on the stat block (moralMin is a per-unit stat; vanilla rows range from -5 to +1)."""
    stats = logic["stats"]
    stats["moralMin"] = entry["min"]
    stats["moral"] = max(stats.get("moral", 0) or 0, entry["min"])
    view["passives"].append(dt._card(sid, entry, "skill_tactics"))


# --- unit ability variety pass (2026-11-21) ---

ACTIVE |= {"h3dungeon_cave_in", "h3dungeon_ray_barrage", "h3dungeon_bull_rush", "h3dungeon_venom_burst"}


def kw_h3dungeon_exposed(ctx, sid, logic, view, entry):
    """Takes more from basic attacks (the taken half of h3dungeon_reckless) under its own card.

    Ambush: the card for the reckless taken penalty; the +Damage half is the paired turn_state runtime entry."""
    _in = logic["stats"].setdefault("inDmgMods", {"list": []}).setdefault("list", [])
    _in.append({"t": "basic_attack", "v": entry["taken"]})
    view["passives"].append(dt._card(sid, entry, "hydra_selfbuff_icon"))


def kw_h3dungeon_counter_buff(ctx, sid, logic, view, entry):
    """on_hit_buff on counterattacks only (Stiffening Glare): the buff rides the counterAttacks dealers alone."""
    ctx.require_buff(entry["buff"], sid)
    for attack in logic["counterAttacks"]:
        dt._set_buff(attack["damageDealer"], entry, "enemy")
    view["passives"].append(dt._card(sid, entry, "magic_shorten_shadow_effect_icon"))


def kw_h3dungeon_cave_in(ctx, sid, logic, view, entry):
    """Donor: the Cave In hero spell (battle_primal_magics primal_8_magic_cave_in, dealer 2): rubble obstacles
    (cave_in_obstacle_1, lifetime 2) fill the free hexes around one enemy stack. The spell damage is dropped."""
    doc = ctx.read(ctx.release_zip, ctx.output, "DB/magics/battle_primal_magics.json")
    spell = next(r for r in doc["array"] if r.get("id") == "primal_8_magic_cave_in")
    dealer = copy.deepcopy(spell["battleMagic"]["magicDealers"][2])
    mechs = dealer.get("targetMechanics") or []
    if [m.get("mech") for m in mechs] != ["summon_in_pattern"] or mechs[0]["values"][:2] != ["obstacle", "cave_in_obstacle_1"]:
        raise RuntimeError("primal_8_magic_cave_in dealer 2 is no longer the cave_in_obstacle_1 summon")
    dealer["tags"] = ["ability", "energy_ability"]  # mummy_l ability 0 cast tags, minus its immunity tags
    dealer["triggerCounter"] = False
    dealer["damageTarget_"] = "none"
    dealer["damageType_"] = "none"
    for key in ("minBaseDmg", "maxBaseDmg", "minStackDmg", "maxStackDmg"):
        dealer.pop(key, None)
    dealer["statDmgMult"] = 0.0
    dealer["shootRange"] = entry.get("range", 4)
    ability = {"attackType_": "cast", "damageDealer": dealer}
    dt._envelope(ability, entry)
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_special", "primal_8_magic_cave_in", entry.get("anim", 2)))


def kw_h3dungeon_ray_barrage(ctx, sid, logic, view, entry):
    """Shared 'shot' plus the multicast block of bonus_magic_pure_bolt / h3_giant_upg_alt (numTargets, ordered
    cast/affect params, autoFillSelection) on the unit's own physical shot."""
    dt.KEYWORDS["shot"](ctx, sid, logic, view, entry)
    dealer = logic["abilities"][-1]["damageDealer"]
    n = int(entry.get("targets", 3))
    params = {key: copy.deepcopy(dealer[key]) for key in ("castTargetParams", "affectTargetParams")}
    for p in params.values():
        p["dmgMultiplierPerMultitarget"] = 1.0
    dealer.update(params)
    dealer.update({"multitargetType": "multicast", "autoFillSelection": True, "numTargets": n,
                   "multicastDelays": [0.0] + [0.3] * (n - 1),
                   "orderedCastParams": [copy.deepcopy(params["castTargetParams"]) for _ in range(n - 1)],
                   "orderedAffectParams": [copy.deepcopy(params["affectTargetParams"]) for _ in range(n - 1)]})


def kw_h3dungeon_bull_rush(ctx, sid, logic, view, entry):
    """Donor: minos ability 0 (vanilla Dungeon minotaur: melee strike with push_unit_from_caster, no counter)."""
    ability = ctx.donor("minos")["abilities"][0]
    dealer = ability["damageDealer"]
    if [m.get("mech") for m in dealer.get("targetMechanics") or []] != ["push_unit_from_caster"]:
        raise RuntimeError("minos ability 0 is no longer the push strike")
    dt._envelope(ability, entry)
    dealer["statDmgMult"] = entry.get("mult", 1.0)
    if "counter" in entry:
        dealer["triggerCounter"] = entry["counter"]
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_attack_mod", "sub_skill_assault_2_icon", entry.get("anim", 0)))


def kw_h3dungeon_venom_burst(ctx, sid, logic, view, entry):
    """Shared melee_strike plus mummy's activate_all_buff_actions ["overTime_effect"] on the strike target."""
    dt.KEYWORDS["melee_strike"](ctx, sid, logic, view, entry)
    dealer = logic["abilities"][-1]["damageDealer"]
    dealer["targetMechanics"] = [*(dealer.get("targetMechanics") or []), {"mech": "activate_all_buff_actions", "values": ["overTime_effect"]}]
