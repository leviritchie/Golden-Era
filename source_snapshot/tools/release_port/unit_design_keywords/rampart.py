"""Rampart unit-design keywords (Striker vs Ward). Loaded by homm3_unit_design_table._load_extensions.

Every keyword adds exactly one card. Donors are named per keyword; all are vanilla rows or vanilla data keys.
"""

from __future__ import annotations

import copy

import homm3_unit_design_table as dt

ACTIVE = {"rampart_overgrowth"}


def _add_unit_tag(logic: dict, tag: str) -> None:
    tags = logic.setdefault("tags", [])
    if tag not in tags:
        tags.append(tag)


def kw_rampart_stat(ctx, sid, logic, view, entry):
    """Plain stat-key passive. Donors: assassin_selfbuff (armorPen), dragon_hunter (outDmgModsByTargetTags, appended so
    other tag-keyed cards keep theirs). entry: stats {key: value}; outDmgModsByTargetTags given as a list."""
    for key, value in entry["stats"].items():
        if key == "armorPen":
            logic["stats"]["armorPen"] = value
        elif key == "outDmgModsByTargetTags":
            mods = logic["stats"].setdefault("outDmgModsByTargetTags", {"list": []})
            mods.setdefault("list", []).extend({"t": mod["t"], "v": mod["v"]} for mod in value)
        else:
            raise RuntimeError(f"{sid}: rampart_stat does not own stat key {key!r}")
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_1_icon"))


def kw_rampart_grudge(ctx, sid, logic, view, entry):
    """when_damaged_adjacent_debuff (hydra_upg Poisonous Blood shape: unit_took_damage self -> swirl on adjacent
    enemies) whose buff carries inDmgModsByCasterTags keyed on a tag this unit wears. entry: buff, duration, unitTag."""
    dt.kw_when_damaged_adjacent_debuff(ctx, sid, logic, view, entry)
    _add_unit_tag(logic, entry["unitTag"])


def kw_rampart_tag_card(ctx, sid, logic, view, entry):
    """A passive card whose effect lives in another card's buff (inDmgModsByCasterTags keyed on this unit's tag):
    Strangle reads the Dendroids' bound buff. entry: unitTag."""
    _add_unit_tag(logic, entry["unitTag"])
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_1_icon"))


def kw_rampart_overgrowth(ctx, sid, logic, view, entry):
    """Free action: debuff every adjacent enemy. minos_upg_alt ability 1 (instacast rumble from self on enemies,
    damageTarget none, actionCost 0) with its own buff. entry: focus, cd, buff, duration."""
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("minos_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if dealer.get("attackPatternSid") != "attack_rumble_x1_x100" or dealer["affectTargetParams"].get("castTarget_") != "enemy" \
            or ability.get("actionCost") != 0 or dealer.get("damageTarget_") != "none":
        raise RuntimeError("minos_upg_alt ability 1 is no longer the free rumble-from-self enemy debuff")
    dt._envelope(ability, entry)
    dealer["tags"] = ["ability", "debuff_ability"]
    dt._set_buff(dealer, entry, "enemy")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_debuff", "skill_tactics", 2, infoDescription="ability_no_turn"))


def kw_rampart_shepherd(ctx, sid, logic, view, entry):
    """Adds add_energy (graverobber_upg_alt Smell of the Hunt: values energy/ally/n/0/1, n Focus Points to the caster's
    side, once per cast) to the unit's swap_units ability (kw_swap must come first in the kit). entry: [n] (default 1)."""
    mech = None
    for passive in ctx.donor("graverobber_upg_alt").get("passives", []):
        for action in passive.get("actions", []):
            for candidate in action["damageDealer"].get("targetMechanics", []):
                if candidate.get("mech") == "add_energy":
                    mech = copy.deepcopy(candidate)
    if mech is None:
        raise RuntimeError("graverobber_upg_alt no longer carries add_energy")
    mech["values"][2] = str(entry.get("n", 1))
    swaps = [a for a in logic["abilities"]
             if any(m.get("mech") == "swap_units" for m in a["damageDealer"].get("targetMechanics", []))]
    if len(swaps) != 1:
        raise RuntimeError(f"{sid}: rampart_shepherd needs exactly one swap_units ability before it in the kit, found {len(swaps)}")
    swaps[0]["damageDealer"]["targetMechanics"].append(mech)
    view["passives"].append(dt._card(sid, entry, "skill_tactics"))
