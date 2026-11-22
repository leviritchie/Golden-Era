"""Conflux keywords for the unit design tables (custom_factions/unit_designs/homm3_conflux.json).

The 15 elementals are the parents of the 142 fusion units, which copy the host's attack rows, stat keys and
aura, and merge both parents' logic passives, attack riders, typed resistances and actives. So the keywords
here keep to those row pieces: immunity passives, the unit_died rebirth passive, attack pattern on the
attack rows, plain stat keys and cast abilities.
"""

from __future__ import annotations

import copy

import homm3_unit_design_table as dt

ACTIVE = {"conflux_spell", "conflux_dot_cast"}

SWIPE_PATTERN = "attack_swipe_x100_x100"
SWIPE_CARD = {"name": "base_passive_strike_swipe_1_name", "description": "base_passive_strike_swipe_1_description_alt", "icon": "skill_tactics"}
STAT_KEYS_ALLOWED = {"armorPen", "attackPen"}


def _is_element_immunity(passive: dict) -> bool:
    rows = (passive.get("data") or {}).get("immunities") or []
    return bool(rows) and set(passive) == {"data"} and set(passive["data"]) == {"immunities"} and all(
        row.get("type") in ("damage", "effect") and all(str(tag).startswith("primal_") for tag in row.get("tags") or [])
        for row in rows
    )


def kw_conflux_immunity(ctx, sid, logic, view, entry):
    """Immunity to named spells' damage and effects (the rows Water and Fire Elementals already carry).

    entry: damage [spell damage tags], effect [spell effect tags]. Replaces any earlier element immunity row.
    """
    logic["passives"] = [p for p in logic.get("passives", []) if not _is_element_immunity(p)]
    rows = []
    if entry.get("damage"):
        rows.append({"type": "damage", "tags": list(entry["damage"])})
    for tag in entry.get("effect", []):
        rows.append({"type": "effect", "tags": [tag]})
    if not rows:
        raise RuntimeError(f"{sid}: conflux_immunity needs damage or effect tags")
    logic["passives"].append({"data": {"immunities": rows}})
    kw_conflux_weakness(ctx, sid, logic, view, entry)
    view["passives"].append(dt._card(sid, entry, "sub_skill_resistance_1_icon"))


def kw_conflux_weakness(ctx, sid, logic, view, entry):
    """Opposed element: the named spells' damage tags as positive inDmgMods (entry weak [tags], weakV share)."""
    mods = dt._in_dmg_list(logic)
    for tag in entry.get("weak", []):
        mods[:] = [m for m in mods if m.get("t") != tag]
        mods.append({"t": tag, "v": entry.get("weakV", 1.0)})


def kw_conflux_weak_card(ctx, sid, logic, view, entry):  # a weakness with its own card (units without an immunity card)
    kw_conflux_weakness(ctx, sid, logic, view, entry)
    view["passives"].append(dt._card(sid, entry, "sub_skill_resistance_1_icon"))


def kw_conflux_rebirth(ctx, sid, logic, view, entry):
    """Phoenix rebirth: on death the stack leaves its phoenix heart, which revives half of it next round.

    The heart obstacle row <sid>_phoenix_heart ships in DB/field_objects (clone of vanilla phoenix_heart).
    """
    heart = f"{sid}_phoenix_heart"
    target = {"targetTags": ["unit"], "castTarget_": "self", "selection": "hexOrObject", "targetCondition_": "self"}
    logic["passives"].append({"actions": [{
        "trigger": "unit_died",
        "triggerConditions": [{"checkFunction": "allegiance", "values": ["self"]}],
        "damageDealer": {
            "attackPatternSid": "attack_single_x100",
            "castTargetParams": copy.deepcopy(target),
            "affectTargetParams": copy.deepcopy(target),
            "targetMechanics": [{"mech": "spawn_object", "values": ["obstacle", heart, "1", "1", "0", "false", "true"]}],
        },
    }]})
    view["passives"].append(dt._card(sid, entry, "magic_early_start_effect_icon"))


def kw_conflux_spell(ctx, sid, logic, view, entry):
    """One of the unit's existing cast abilities (matched by view name), re-costed and, for damage casts,
    re-scaled from a fixed per-creature number to a share of the stack's own basic damage.

    entry: view (existing ability view name), from (unit sid, default this unit), focus, cd,
           mult (optional: statDmgMult of the cast, pure Magic Damage), free (optional bool: actionCost 0),
           buff + duration (optional: replaces the buff the cast applies).
    """
    source = entry.get("from", sid)
    donor_logic, donor_view = ctx.donor(source), ctx.donor(source, "v")
    pairs = [(a, v) for a, v in zip(donor_logic.get("abilities", []), donor_view.get("abilities", [])) if v.get("name") == entry["view"]]
    if len(pairs) != 1:
        raise RuntimeError(f"{sid}: conflux_spell {entry['view']!r} matched {len(pairs)} abilities on {source}")
    ability, old_card = pairs[0]
    for key in ("xHomm3SpellEffectSelection", "xHomm3AbilityOverride"):
        ability.pop(key, None)
    dt._envelope(ability, entry)
    if "free" in entry:
        if entry["free"]:
            ability["actionCost"] = 0
        else:
            ability.pop("actionCost", None)
    dealer = ability["damageDealer"]
    if "mult" in entry:
        if dealer.get("damageTarget_") not in ("enemy", "all"):
            raise RuntimeError(f"{sid}: conflux_spell mult on {entry['view']!r}, which deals no damage")
        for key in ("minBaseDmg", "maxBaseDmg", "minStackDmg", "maxStackDmg"):
            dealer.pop(key, None)
        dealer["statDmgMult"] = entry["mult"]
        dealer["tags"] = list(dict.fromkeys([*dealer.get("tags", []), "ability"]))
        dealer["triggerCounter"] = False
    if "buff" in entry:
        ctx.require_buff(entry["buff"], sid)
        dealer["buff"] = {"sid": entry["buff"], "duration": entry["duration"]}
    logic["abilities"].append(ability)
    extra = {}
    if ability.get("actionCost") == 0:
        extra["infoDescription"] = "ability_no_turn"
    view["abilities"].append(dt._ability_card(
        sid, entry, old_card.get("abilityType", "Ability_type_attack"), old_card.get("icon", "skill_tactics"),
        old_card.get("animationIndex", 2), **extra))


def kw_conflux_swipe(ctx, sid, logic, view, entry):
    """Basic attack and counterattack hit the target and the two enemies to its sides (Psychic Elemental's
    attack rows use this pattern with the same targeting block as a single-target melee attack)."""
    for bucket in ("defaultAttacks", "counterAttacks"):
        for attack in logic[bucket]:
            if attack.get("attackType_") != "melee":
                raise RuntimeError(f"{sid}: conflux_swipe on a non-melee attack row")
            attack["damageDealer"]["attackPatternSid"] = SWIPE_PATTERN
    view["passives"].append(copy.deepcopy(SWIPE_CARD))


def kw_conflux_bedrock(ctx, sid, logic, view, entry):  # donor slot: dragon_hunter stats.inDmgModsByCasterTags
    """Less damage taken from rows the builder tags as flyers (apply_design_tags adds dt.FLYER_TAG).

    Note for fusions: the composer copies the host's stats (so a host keeps this) but merges only
    inDmgMods/outDmgMods from a guest, so a guest Earth half does not pass it on yet."""
    mods = logic["stats"].setdefault("inDmgModsByCasterTags", {"list": []})
    mods.setdefault("list", []).append({"t": dt.FLYER_TAG, "v": entry["v"]})
    view["passives"].append(dt._card(sid, entry, "sub_skill_resistance_1_icon"))


def kw_conflux_dot_cast(ctx, sid, logic, view, entry):  # donor: aqualotl_upg_alt ability 1 (debuff cast on one enemy)
    """Free single-enemy cast within entry["range"] hexes that applies a damage-over-time buff and deals no
    direct damage. entry: buff, duration, focus, cd, range. A "scale_by_caster" field ({"percent": n}) is read
    by the plugin's buff-add rewrite: the buff's damage becomes n% of the caster's basic attack Damage."""
    ctx.require_buff(entry["buff"], sid)
    ability = ctx.donor("aqualotl_upg_alt")["abilities"][1]
    dealer = ability["damageDealer"]
    if ability.get("attackType_") != "cast" or dealer.get("buffTarget_") != "enemy" or dealer.get("damageTarget_") != "none":
        raise RuntimeError("aqualotl_upg_alt ability 1 is no longer the single-enemy debuff cast")
    dt._envelope(ability, entry)
    ability["actionCost"] = 0
    dealer["shootRange"] = entry["range"]
    dt._set_buff(dealer, entry, "enemy")
    logic["abilities"].append(ability)
    view["abilities"].append(dt._ability_card(sid, entry, "Ability_type_debuff", "phoenix_ignition_icon", 2,
                                              infoDescription="ability_no_turn"))


def kw_conflux_focus_on_damage(ctx, sid, logic, view, entry):  # donor layout: godslayer_upg passive (add_energy)
    """Whenever this unit takes damage it gains entry["focus"] Focus. A logic passive, so a guest passes it on."""
    donor = None
    for passive in ctx.donor("godslayer_upg")["passives"]:
        for action in passive.get("actions") or []:
            if [m.get("mech") for m in action.get("damageDealer", {}).get("targetMechanics", [])] == ["add_energy"]:
                donor = action
    if donor is None:
        raise RuntimeError("godslayer_upg no longer carries the add_energy passive")
    donor["trigger"] = "unit_took_damage"
    donor["triggerConditions"] = [{"checkFunction": "allegiance", "values": ["self"]}]
    donor["damageDealer"]["targetMechanics"] = [{"mech": "add_energy", "values": ["energy", "self", str(entry["focus"]), "0", "1"]}]
    logic["passives"].append({"actions": [donor]})
    view["passives"].append(dt._card(sid, entry, "magic_energyze_effect_icon"))


def kw_conflux_round_pulse(ctx, sid, logic, view, entry):  # donor: hydra_upg start_turn heal_percent passive action
    """At the start of this unit's turn, friendly creatures adjacent to it restore a share of their stack's full
    Health (entry["share"]), reviving up to the stack's starting size."""
    donor = None
    for passive in ctx.donor("hydra_upg")["passives"]:
        for action in passive.get("actions") or []:
            mechs = action.get("damageDealer", {}).get("targetMechanics", [])
            if action.get("trigger") == "start_turn" and [m.get("mech") for m in mechs] == ["heal_percent"]:
                donor = action
    if donor is None:
        raise RuntimeError("hydra_upg no longer carries the start_turn heal_percent action")
    dealer = donor["damageDealer"]
    dealer["attackPatternSid"] = "attack_rumble_x1_x100"
    dealer["affectTargetParams"]["castTarget_"] = "allynoself"
    dealer["targetMechanics"] = [{"mech": "heal_percent", "values": ["until start amount", "max_squad", f"{entry['share']:.2f}", "0.00", "true"]}]
    logic["passives"].append({"actions": [donor]})
    view["passives"].append(dt._card(sid, entry, "magic_healing_water_effect_icon"))


def kw_conflux_stat(ctx, sid, logic, view, entry):
    """A plain stat key with its own card (armorPen: share of the target's Defence ignored, as Behemoths;
    attackPen: share of attackers' Attack ignored, as Nix)."""
    if entry["stat"] not in STAT_KEYS_ALLOWED:
        raise RuntimeError(f"{sid}: conflux_stat does not own stat {entry['stat']!r}")
    logic["stats"][entry["stat"]] = entry["v"]
    view["passives"].append(dt._card(sid, entry, "sub_skill_assault_2_icon"))
