#!/usr/bin/env python3
"""Generate OfflineUnlockMod/Homm3UnitKitRules.g.cs from the unit design tables.

    python tools/release_port/build_unit_kit_runtime_table.py [--check]

Kit entries with `"k": "runtime"` (custom_factions/unit_designs/*.json) are mechanics Core data cannot express;
the plugin applies them per unit SID (Homm3UnitKitRuntime.cs, Homm3UnitKitBattleHooks.cs). The full contract, with
every kind, parameter and meaning, is docs/unit_ability_pass_20261121/RUNTIME_CONTRACT.md. In short:

  every rule        {"percent": N (positive int; 1 when the rule has no number), "name": ...}
  filters           "attack": any|melee|ranged, "abilityOnly": bool (damage-step rules flagged in RULE_PARAMS)
  damage dealt      damage_vs_buff {buffs}, grudge, loss_fury {cap}, death_toll {cap}, turn_state {fact},
                    counter_state {state}, adjacency {mode}, crowd {cap}, hit_this_round {cap}, first_hit {side},
                    damage_vs_hp {below}, bounty, retribution, same_target_streak {cap}, stored_fury {cap},
                    quarry {buff}, wall_slam
  damage taken      adjacent_ally_ward {cap}, hit_cap, bodyguard
  queued attacks    guard_strike {perRound}, zone_shot {radius, perRound}, spell_echo {perRound}
  hooks             arrival_buff {buff, radius}, kill_extra_action {buff, abilityIndex?}, ability_feedback {radius},
                    brand_splash {buff}, charge_no_counter {hexes}, scatter {hexes}

Buff rewrites the plugin makes when a buff is added (any kit entry with "buff"; at most one per buff):

  "rotate": [sid, ...]      each use of that buff becomes the next listed buff in turn
  "escalate": {"to": sid, "unless": sid?}   a repeat application to a target that still has the buff becomes `to`,
                            unless the target has the `unless` buff
  "escalate": {"chain": [sid, ...]}  a repeat application adds the first chain buff the target lacks (stacking)
  "scale_by_caster": {"percent": P, "tiers": [[damage, sid], ...]}  adds the tier whose damage is the largest not
                            above P% of the caster's basic attack damage (stack x average damage)

A `self_buff` kit entry with `"runtime": "covering_fire"` names the armed buff of the reaction shot; one buff SID
serves every unit that has it.

--check exits 1 when the generated file on disk differs (no write). Runtime: under a second, CPU only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import homm3_unit_design_table as design  # noqa: E402

OUTPUT = REPO_ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3UnitKitRules.g.cs"

FACTS = ("stood_ground", "unacted_target", "moved_target", "waited_target")
COUNTER_STATES = ("left0", "used")
ADJACENCY_MODES = ("flank", "isolated")
SIDES = ("attacker", "defender")
ATTACKS = ("any", "melee", "ranged")
FILTERS = ("attack", "abilityOnly")
# rule -> (C# enum member, parameters beyond percent/name, damage filters allowed)
RULE_PARAMS: dict[str, tuple[str, tuple[str, ...], bool]] = {
    "damage_vs_buff": ("DamageVsBuff", ("buffs",), True),
    "grudge": ("Grudge", (), False),
    "adjacent_ally_ward": ("AdjacentAllyWard", ("cap",), False),
    "hit_cap": ("HitCap", (), False),
    "loss_fury": ("LossFury", ("cap",), False),
    "death_toll": ("DeathToll", ("cap",), False),
    "turn_state": ("TurnState", ("fact",), True),
    "counter_state": ("CounterState", ("state",), True),
    "adjacency": ("Adjacency", ("mode",), True),
    "crowd": ("Crowd", ("cap",), True),
    "hit_this_round": ("HitThisRound", ("cap",), True),
    "first_hit": ("FirstHit", ("side",), False),
    "damage_vs_hp": ("DamageVsHp", ("below",), True),
    "bounty": ("Bounty", (), True),
    "retribution": ("Retribution", (), True),
    "same_target_streak": ("SameTargetStreak", ("cap",), True),
    "stored_fury": ("StoredFury", ("cap",), False),
    "quarry": ("Quarry", ("buff",), True),
    "wall_slam": ("WallSlam", (), True),
    "bodyguard": ("Bodyguard", (), False),
    "guard_strike": ("GuardStrike", ("perRound",), False),
    "zone_shot": ("ZoneShot", ("radius", "perRound"), False),
    "spell_echo": ("SpellEcho", ("perRound",), False),
    "arrival_buff": ("ArrivalBuff", ("buff", "radius"), False),
    "kill_extra_action": ("KillExtraAction", ("buff", "abilityIndex"), False),
    "ability_feedback": ("AbilityFeedback", ("radius",), False),
    "brand_splash": ("BrandSplash", ("buff",), False),
    "charge_no_counter": ("ChargeNoCounter", ("hexes",), False),
    "scatter": ("Scatter", ("hexes",), False),
}
RULE_KINDS = {rule: spec[0] for rule, spec in RULE_PARAMS.items()}
WITHDRAWN = {
    "overkill_carry": "withdrawn by owner decision 4",
    "kill_refund": "owner decision 4 restored kill_extra_action",
    "vs_buff_tag": "Cripple and Siege Breaker are native",
    "vs_debuffed": "Cripple is native",
    "vs_buffed": "Siege Breaker is native",
    "unhurt": "Deadly Sting is native",
    "outnumbered": "Smite is native",
    "duel_mark": "Challenge is native",
    "raise_by_hp": "the plugin hook is not built; use the draft fallback",
    "stood_ground": "use turn_state fact stood_ground",
    "unacted_target": "use turn_state fact unacted_target",
    "target_not_acted": "use turn_state fact unacted_target",
    "moved_target": "use turn_state fact moved_target",
    "waited_target": "use turn_state fact waited_target",
    "allies_acted": "withdrawn (the boar Gore is native)",
    "no_counter_left": "use counter_state state left0",
    "spent_counter": "use counter_state state used",
    "flank": "use adjacency mode flank",
    "isolated": "use adjacency mode isolated",
    "crowd_nova": "use crowd",
    "focus_fire": "use hit_this_round",
    "first_hit_ward": "use first_hit side defender",
    "overwatch": "use zone_shot",
}
# card / power-model metadata any runtime entry may carry (plus any "*Mult" power key)
COMMON_KEYS = {"k", "rule", "percent", "name", "text", "icon", "nameSid", "descSid", "why", "note", "power"}
CAPPED_RULES = ("adjacent_ally_ward", "death_toll", "crowd", "hit_this_round", "same_target_streak", "stored_fury")
CONTRACT = "docs/unit_ability_pass_20261121/RUNTIME_CONTRACT.md"


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def collect_swaps(designs: dict[str, dict]):
    """Buff rotations, escalations, escalation chains and caster scales, keyed by the buff the kit entry applies."""
    rotations: dict[str, list[str]] = {}
    escalations: dict[str, tuple[str, str]] = {}
    chains: dict[str, list[str]] = {}
    scales: dict[str, tuple[int, list[tuple[int, str]]]] = {}
    for doc in designs.values():
        for sid, unit in doc["units"].items():
            for entry in unit["kit"]:
                keys = [key for key in ("rotate", "escalate", "scale_by_caster") if key in entry]
                if not keys:
                    continue
                if len(keys) > 1:
                    raise RuntimeError(f"{sid}: a buff may carry only one of rotate/escalate/scale_by_caster, found {keys}")
                buff = entry.get("buff")
                if not isinstance(buff, str) or not buff:
                    raise RuntimeError(f"{sid}: {keys[0]} needs the entry's own \"buff\"")
                if "rotate" in entry:
                    rotate = list(entry["rotate"])
                    if len(rotate) < 2 or buff in rotate:
                        raise RuntimeError(f"{sid}: rotate needs two or more buffs and must not list the entry's own buff")
                    if rotations.setdefault(buff, rotate) != rotate:
                        raise RuntimeError(f"{sid}: buff {buff} already rotates through another list")
                elif "escalate" in entry:
                    esc = entry["escalate"]
                    if not isinstance(esc, dict):
                        raise RuntimeError(f"{sid}: escalate must be an object")
                    if "chain" in esc:
                        chain = esc["chain"]
                        if set(esc) != {"chain"} or not isinstance(chain, list) or not chain or buff in chain \
                                or len(set(chain)) != len(chain) or not all(isinstance(c, str) and c for c in chain):
                            raise RuntimeError(f"{sid}: escalate.chain must be a non-empty list of distinct SIDs without the entry's own buff, and nothing else")
                        if chains.setdefault(buff, list(chain)) != list(chain):
                            raise RuntimeError(f"{sid}: buff {buff} already escalates through another chain")
                    else:
                        if not isinstance(esc.get("to"), str) or set(esc) - {"to", "unless"}:
                            raise RuntimeError(f"{sid}: escalate needs \"to\" (and optional \"unless\") or \"chain\"")
                        pair = (esc["to"], esc.get("unless", ""))
                        if pair[0] == buff:
                            raise RuntimeError(f"{sid}: escalate.to must differ from the entry's own buff")
                        if escalations.setdefault(buff, pair) != pair:
                            raise RuntimeError(f"{sid}: buff {buff} already escalates to another buff")
                else:
                    scale = entry["scale_by_caster"]
                    tiers = scale.get("tiers") if isinstance(scale, dict) else None
                    if not isinstance(scale, dict) or set(scale) != {"percent", "tiers"} or not _int(scale["percent"]) \
                            or scale["percent"] <= 0 or not isinstance(tiers, list) or not tiers:
                        raise RuntimeError(f"{sid}: scale_by_caster needs {{\"percent\": positive int, \"tiers\": [[damage, sid], ...]}}")
                    parsed: list[tuple[int, str]] = []
                    for tier in tiers:
                        if not (isinstance(tier, list) and len(tier) == 2 and _int(tier[0]) and tier[0] > 0
                                and isinstance(tier[1], str) and tier[1]):
                            raise RuntimeError(f"{sid}: scale_by_caster tier {tier!r} must be [positive int damage, buff sid]")
                        parsed.append((tier[0], tier[1]))
                    damages = [t[0] for t in parsed]
                    if damages != sorted(set(damages)):
                        raise RuntimeError(f"{sid}: scale_by_caster tiers must be strictly ascending by damage")
                    value = (scale["percent"], parsed)
                    if scales.setdefault(buff, value) != value:
                        raise RuntimeError(f"{sid}: buff {buff} already scales with other tiers")
    seen: dict[str, str] = {}
    for name, table in (("rotate", rotations), ("escalate", escalations), ("escalate.chain", chains), ("scale_by_caster", scales)):
        for buff in table:
            if buff in seen:
                raise RuntimeError(f"buff {buff} is both {seen[buff]} and {name}")
            seen[buff] = name
    return rotations, escalations, chains, scales


def validate_rule(sid: str, entry: dict) -> None:
    rule = entry.get("rule")
    if rule in WITHDRAWN:
        raise RuntimeError(f"{sid}: runtime rule {rule!r} is not available: {WITHDRAWN[rule]} ({CONTRACT})")
    if rule not in RULE_PARAMS:
        raise RuntimeError(f"{sid}: unknown runtime rule {rule!r} ({CONTRACT})")
    _, params, filters = RULE_PARAMS[rule]
    own = set(params) | (set(FILTERS) if filters else set())
    extra = sorted(key for key in entry if key not in COMMON_KEYS and key not in own and not key.endswith("Mult"))
    if extra:
        raise RuntimeError(f"{sid}: runtime rule {rule} does not take {extra} (it takes {sorted(own)}; {CONTRACT})")
    if not isinstance(entry.get("name"), str) or not entry["name"]:
        raise RuntimeError(f"{sid}: runtime rule {rule} needs a name")
    percent = entry.get("percent")
    if not _int(percent) or percent <= 0:
        raise RuntimeError(f"{sid}: runtime rule {rule} needs a positive integer percent")
    if entry.get("attack", "any") not in ATTACKS:
        raise RuntimeError(f"{sid}: {rule} attack must be one of {ATTACKS}")
    if not isinstance(entry.get("abilityOnly", False), bool):
        raise RuntimeError(f"{sid}: {rule} abilityOnly must be true or false")
    if rule in CAPPED_RULES and not (_int(entry.get("cap")) and entry["cap"] >= percent):
        raise RuntimeError(f"{sid}: {rule} needs an integer cap >= percent")
    if rule == "loss_fury" and not (_int(entry.get("cap")) and 0 < entry["cap"] <= percent):
        raise RuntimeError(f"{sid}: loss_fury needs an integer cap in 1..percent")
    if rule in ("hit_cap", "bodyguard") and percent >= 100:
        raise RuntimeError(f"{sid}: {rule} percent must be below 100")
    if rule == "damage_vs_buff" and not (isinstance(entry.get("buffs"), list) and entry["buffs"]
                                         and all(isinstance(b, str) and b for b in entry["buffs"])):
        raise RuntimeError(f"{sid}: damage_vs_buff needs a buffs list")
    for key, values in (("fact", FACTS), ("state", COUNTER_STATES), ("mode", ADJACENCY_MODES), ("side", SIDES)):
        if key in params and entry.get(key) not in values:
            raise RuntimeError(f"{sid}: {rule} {key} must be one of {values}")
    if rule == "damage_vs_hp" and not (_int(entry.get("below")) and 0 < entry["below"] < 100):
        raise RuntimeError(f"{sid}: damage_vs_hp needs below in 1..99")
    if "buff" in params and not (isinstance(entry.get("buff"), str) and entry["buff"]):
        raise RuntimeError(f"{sid}: {rule} needs a buff SID")
    if rule in ("zone_shot", "ability_feedback") and "radius" not in entry:
        raise RuntimeError(f"{sid}: {rule} needs radius >= 1")
    for key in ("radius", "perRound"):
        if key in entry and not (_int(entry[key]) and entry[key] >= 1):
            raise RuntimeError(f"{sid}: {rule} {key} must be an integer >= 1")
    if rule == "charge_no_counter" and not (_int(entry.get("hexes")) and entry["hexes"] >= 1):
        raise RuntimeError(f"{sid}: charge_no_counter needs hexes >= 1")
    if rule == "scatter" and not (_int(entry.get("hexes")) and 1 <= entry["hexes"] <= 3):
        raise RuntimeError(f"{sid}: scatter needs hexes in 1..3")
    if "abilityIndex" in entry and not (_int(entry["abilityIndex"]) and entry["abilityIndex"] >= 0):
        raise RuntimeError(f"{sid}: kill_extra_action abilityIndex must be an integer >= 0")


def collect(designs: dict[str, dict]) -> tuple[dict[str, list[dict]], str]:
    rules: dict[str, list[dict]] = {}
    covering: set[str] = set()
    for doc in designs.values():
        for sid, unit in doc["units"].items():
            for entry in unit["kit"]:
                if entry["k"] == "runtime":
                    validate_rule(sid, entry)
                    rules.setdefault(sid, []).append(entry)
                elif entry.get("runtime") == "covering_fire":
                    covering.add(entry["buff"])
                elif "runtime" in entry:
                    raise RuntimeError(f"{sid}: unknown runtime marker {entry['runtime']!r}")
    if len(covering) > 1:
        raise RuntimeError(f"covering_fire must use one armed buff SID, found {sorted(covering)}")
    return rules, next(iter(covering), "")


def _choice(entry: dict) -> int:
    """The rule's enumerated choice (fact / state / mode / side) as its index, 0 when the rule has none."""
    for key, values in (("fact", FACTS), ("state", COUNTER_STATES), ("mode", ADJACENCY_MODES), ("side", SIDES)):
        if key in entry:
            return values.index(entry[key])
    return 0


def _rule_line(entry: dict) -> str:
    buffs = ", ".join(_quote(b) for b in entry.get("buffs", []))
    buff_array = f"new[] {{ {buffs} }}" if buffs else "Array.Empty<string>()"
    parts = [
        f"Kind = RuleKind.{RULE_KINDS[entry['rule']]}",
        f"Name = {_quote(entry['name'])}",
        f"Percent = {entry['percent']}",
        f"Cap = {entry.get('cap', 0)}",
        f"BuffSids = {buff_array}",
    ]
    if _choice(entry):
        parts.append(f"Choice = {_choice(entry)}")
    attack = ATTACKS.index(entry.get("attack", "any"))
    if attack:
        parts.append(f"Attack = {attack}")
    if entry.get("abilityOnly"):
        parts.append("AbilityOnly = true")
    for key, field in (("below", "Below"), ("radius", "Radius"), ("perRound", "PerRound"), ("hexes", "Hexes"), ("abilityIndex", "AbilityIndex")):
        if key in entry:
            parts.append(f"{field} = {entry[key]}")
    if "buff" in entry and entry["rule"] in ("quarry", "arrival_buff", "kill_extra_action", "brand_splash"):
        parts.append(f"Buff = {_quote(entry['buff'])}")
    return "\t\t\tnew Rule { " + ", ".join(parts) + " },"


def render(designs: dict[str, dict]) -> str:
    rules, covering = collect(designs)
    rotations, escalations, chains, scales = collect_swaps(designs)
    enum = ", ".join(spec[0] for spec in RULE_PARAMS.values())
    lines = [
        "// <auto-generated>",
        "// Generated by tools/release_port/build_unit_kit_runtime_table.py from custom_factions/unit_designs/*.json.",
        "// Do not edit; change the design table and regenerate.",
        "// </auto-generated>",
        "using System;",
        "using System.Collections.Generic;",
        "",
        "namespace OfflineUnlockMod;",
        "",
        "internal static class Homm3UnitKitRules",
        "{",
        f"\tinternal enum RuleKind {{ {enum} }}",
        "",
        "\t/// <summary>Rule.Choice values (index into the generator's FACTS / COUNTER_STATES / ADJACENCY_MODES / SIDES).</summary>",
        "\tinternal const int FactStoodGround = 0, FactUnactedTarget = 1, FactMovedTarget = 2, FactWaitedTarget = 3;",
        "\tinternal const int CounterLeft0 = 0, CounterUsed = 1;",
        "\tinternal const int AdjacencyFlank = 0, AdjacencyIsolated = 1;",
        "\tinternal const int SideAttacker = 0, SideDefender = 1;",
        "\t/// <summary>Rule.Attack values.</summary>",
        "\tinternal const int AttackAny = 0, AttackMelee = 1, AttackRanged = 2;",
        "",
        "\tinternal sealed class Rule",
        "\t{",
        "\t\tinternal RuleKind Kind;",
        "\t\tinternal string Name;",
        "\t\tinternal int Percent;",
        "\t\tinternal int Cap;",
        "\t\tinternal string[] BuffSids;",
        "\t\tinternal int Choice;",
        "\t\tinternal int Attack;",
        "\t\tinternal bool AbilityOnly;",
        "\t\tinternal int Below;",
        "\t\tinternal int Radius = 1;",
        "\t\tinternal int PerRound = 1;",
        "\t\tinternal int Hexes;",
        "\t\tinternal int AbilityIndex = -1;",
        "\t\tinternal string Buff;",
        "\t}",
        "",
        f"\tinternal const string CoveringFireBuffSid = {_quote(covering)};",
        "",
        "\tinternal static readonly Dictionary<string, Rule[]> Rules = new(StringComparer.Ordinal)",
        "\t{",
    ]
    for sid in sorted(rules):
        lines.append(f"\t\t[{_quote(sid)}] = new[]")
        lines.append("\t\t{")
        for entry in rules[sid]:
            lines.append(_rule_line(entry))
        lines.append("\t\t},")
    lines += ["\t};", "", "\t/// <summary>Applied buff SID to the buffs its uses cycle through.</summary>",
              "\tinternal static readonly Dictionary<string, string[]> BuffRotations = new(StringComparer.Ordinal)", "\t{"]
    for buff in sorted(rotations):
        lines.append(f"\t\t[{_quote(buff)}] = new[] {{ {', '.join(_quote(b) for b in rotations[buff])} }},")
    lines += ["\t};", "", "\t/// <summary>Applied buff SID to { buff a repeat application becomes, buff that blocks the swap or empty }.</summary>",
              "\tinternal static readonly Dictionary<string, string[]> BuffEscalations = new(StringComparer.Ordinal)", "\t{"]
    for buff in sorted(escalations):
        lines.append(f"\t\t[{_quote(buff)}] = new[] {{ {_quote(escalations[buff][0])}, {_quote(escalations[buff][1])} }},")
    lines += ["\t};", "", "\t/// <summary>Applied buff SID to the stacking chain: a repeat adds the first chain buff the target lacks.</summary>",
              "\tinternal static readonly Dictionary<string, string[]> BuffChains = new(StringComparer.Ordinal)", "\t{"]
    for buff in sorted(chains):
        lines.append(f"\t\t[{_quote(buff)}] = new[] {{ {', '.join(_quote(b) for b in chains[buff])} }},")
    lines += ["\t};", "", "\t/// <summary>Applied buff SID to its caster scale: percent of the caster's basic damage picks a tier buff.</summary>",
              "\tinternal static readonly Dictionary<string, (int Percent, int[] Damage, string[] Sids)> BuffScales = new(StringComparer.Ordinal)", "\t{"]
    for buff in sorted(scales):
        percent, tiers = scales[buff]
        damage = ", ".join(str(t[0]) for t in tiers)
        sids = ", ".join(_quote(t[1]) for t in tiers)
        lines.append(f"\t\t[{_quote(buff)}] = ({percent}, new[] {{ {damage} }}, new[] {{ {sids} }}),")
    lines += ["\t};", "}", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = render(design.load_designs())
    current = OUTPUT.read_text(encoding="utf-8").replace("\r\n", "\n") if OUTPUT.is_file() else None
    if args.check:
        if current != text:
            print(f"ERROR: {OUTPUT.name} is stale; run tools/release_port/build_unit_kit_runtime_table.py")
            return 1
        print(f"unit-kit-runtime-table: OK ({OUTPUT.name} matches the design tables)")
        return 0
    if current != text:
        OUTPUT.write_text(text, encoding="utf-8", newline="\n")
        print(f"wrote {OUTPUT}")
    else:
        print(f"unchanged {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
