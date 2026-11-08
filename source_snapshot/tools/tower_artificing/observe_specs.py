"""Observation specs for Tower Artificing (docs/homm3_tower_artificing.md, "Observation replaces Transcribe").

A graftable schematic enters the book when a native unit's passive is *observed*: it changed the outcome
of a combat event. Each graftable row gets a list of specs naming the event that proves it. Most specs are
derived from the curated payload and the source units' native Core logic; policy `observeOverrides` replaces
the derivation for rows whose native mechanic is not where the payload came from (auras and hero-mana cards
from laws/buff tables, attack-sourced kills, map cards).

Kinds:
- passive_action  native passive action `passives[i].actions[j]` of a source unit fired and produced an effect
                  (attribution scope: the native buff-action runner, ejh.befp; config identity)
- buff_applied    a native buff sid stuck on a unit, applied by a source unit
- attack_mech     damage from a source unit's attack mech (kill_stacks, damage) landed
- damage_stat     a damage event where the stat applies to a source unit (attacker or receiver)
- immunity        a cast, effect or buff aimed at a source unit was blocked
- attack_sequence counter suppressed / extra counter / extra strike by a source unit
- drain_heal      a source unit's drain healed more than 0
- morale_roll     morale roll the stat caused or prevented (moralMin)
- luck_roll       luck roll the stat caused or prevented (luckMin, luckMax)
- energy          extra energy / action points / extra action used by a source unit
- ability_cast    a source unit's ability cast hit something
- synergy         a source unit's synergy buff took part in an event
- aura            a native aura / global passive tag (logic `aura`, `globalPassives`) of a source unit took part
                  in an event: its buff on a unit, or a roll / damage the aura stat changed
- side_modifier   a source unit's side modifier (hero mana cost, spell power) applied to its hero's cast
- map_proxy       out-of-battle card: xp award, max mana / spell level when the hero casts, else presence
"""
from __future__ import annotations

import re
from typing import Any

OBSERVE_KINDS = {
    "passive_action", "buff_applied", "attack_mech", "damage_stat", "immunity", "attack_sequence", "drain_heal",
    "morale_roll", "luck_roll", "energy", "ability_cast", "synergy", "aura", "side_modifier", "map_proxy",
}
MAP_PROXIES = {"xp", "max_mana", "spell_level", "presence"}
ATTACK_MECHS = {"damage", "kill_stacks"}
MORALE_STATS = {"moral", "moralMin", "moralMax"}
LUCK_STATS = {"luck", "luckMin", "luckMax"}
ENERGY_STATS = {"energyPerTakeDamage", "energyPerRound", "energyPerCast", "maxAddedApPerRound", "additionalActionChanceModifier"}
_AURA_HELPER = re.compile(r"homm3_tower_graft_\d+_[a-z_]+")


def _canonical(value: Any, canonical: Any) -> str:
    return _AURA_HELPER.sub("HELPER", canonical(value))


def native_action_links(row: dict[str, Any], actions: list[dict[str, Any]], logics: dict[str, dict[str, Any]], canonical: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Per source unit, the native passives[i].actions[j] equal to each payload action (exactly one each).

    Returns (links, uncovered unit sids). A payload action matching two native actions of one unit fails."""
    links: list[dict[str, Any]] = []
    uncovered: list[str] = []
    wanted = [_canonical(a, canonical) for a in actions]
    for unit in row["sourceUnits"]:
        native = [
            (i, j, a)
            for i, block in enumerate((logics.get(unit["sid"]) or {}).get("passives") or [])
            if isinstance(block, dict)
            for j, a in enumerate(block.get("actions") or [])
        ]
        found = []
        for want in wanted:
            hits = [(i, j, a) for i, j, a in native if _canonical(a, canonical) == want]
            if len(hits) > 1:
                raise SystemExit(f"{row['key']}: payload action matches {len(hits)} native actions of {unit['sid']}")
            if hits:
                found.append(hits[0])
        if not found:
            uncovered.append(unit["sid"])
            continue
        for i, j, a in found:
            links.append({"unit": unit["sid"], "passive": i, "action": j, "trigger": a.get("trigger")})
    return links, uncovered


def derive(row: dict[str, Any], logics: dict[str, dict[str, Any]], canonical: Any) -> tuple[list[dict[str, Any]], str | None]:
    """Specs from the curated payload + native logic, and why an override is needed (None when the specs suffice)."""
    payload = row.get("payload") or {}
    runtime = row.get("runtime") or {}
    data = payload.get("data") or {}
    stats = set((data.get("stats") or {}).keys())
    specs: list[dict[str, Any]] = []
    if "abilities" in runtime:
        specs.append({"kind": "ability_cast", "sourceUnit": runtime["abilities"]["sourceUnit"], "indices": runtime["abilities"]["indices"]})
    if "heroBuff" in runtime or "dailyGold" in runtime:
        return specs, "map card: give a map_proxy"
    if runtime.get("onHit"):
        specs.append({"kind": "buff_applied", "buffs": sorted({h["buff"] for h in runtime["onHit"]})})
    if "vampirism" in runtime:
        specs.append({"kind": "drain_heal"})
    if "battleStart" in runtime:
        specs.append({"kind": "synergy"})
    need = None
    if payload.get("actions"):
        links, uncovered = native_action_links(row, payload["actions"], logics, canonical)
        if links and not uncovered:
            specs.append({"kind": "passive_action", "links": links})
        elif links:
            need = f"native action found for some source units but not {uncovered}"
        else:
            # The payload's actions are a port (aura helper, side buff); the native mechanic lives elsewhere.
            need = "payload actions have no native passive action"
    if data.get("immunities"):
        specs.append({"kind": "immunity", "immunities": data["immunities"]})
    effects = sorted({e if isinstance(e, str) else e.get("effect") or e.get("type") or e.get("mech") for e in data.get("sequenceEffect") or []} - {None})
    overrides = sorted({o.get("stat") or o.get("type") or "override" for o in payload.get("statOverrides") or []})
    if effects or overrides or data.get("disablers"):
        specs.append({"kind": "attack_sequence", "effects": effects, "statOverrides": overrides,
                      "disablers": sorted({d.get("mech") for d in data.get("disablers") or []} - {None})})
    damage = sorted(stats - MORALE_STATS - LUCK_STATS - ENERGY_STATS)
    if damage or data.get("alwaysMinDmg"):
        specs.append({"kind": "damage_stat", "stats": damage + (["alwaysMinDmg"] if data.get("alwaysMinDmg") else [])})
    if stats & MORALE_STATS:
        specs.append({"kind": "morale_roll", "stats": sorted(stats & MORALE_STATS)})
    if stats & LUCK_STATS:
        specs.append({"kind": "luck_roll", "stats": sorted(stats & LUCK_STATS)})
    if stats & ENERGY_STATS:
        specs.append({"kind": "energy", "stats": sorted(stats & ENERGY_STATS)})
    return specs, need if need or specs else "nothing derivable"


def check_override(key: str, specs: Any, logics: dict[str, dict[str, Any]], source_sids: set[str]) -> None:
    def fail(why: str) -> None:
        raise SystemExit(f"observeOverrides[{key}]: {why}")

    if not isinstance(specs, list) or not specs:
        fail("must be a non-empty list of specs")
    for spec in specs:
        kind = spec.get("kind")
        if kind not in OBSERVE_KINDS:
            fail(f"kind {kind!r} not in {sorted(OBSERVE_KINDS)}")
        if kind == "buff_applied" and not (spec.get("buffs") and all(isinstance(b, str) for b in spec["buffs"])):
            fail("buff_applied needs buffs (native buff sids)")
        if kind == "attack_mech" and not set(spec.get("mechs") or []) <= ATTACK_MECHS | {None} or kind == "attack_mech" and not spec.get("mechs"):
            fail(f"attack_mech needs mechs within {sorted(ATTACK_MECHS)}")
        if kind in ("aura", "side_modifier") and not (spec.get("tags") and all(isinstance(t, str) for t in spec["tags"])):
            fail(f"{kind} needs tags (native aura / side modifier tags)")
        if kind == "map_proxy" and spec.get("proxy") not in MAP_PROXIES:
            fail(f"map_proxy needs proxy in {sorted(MAP_PROXIES)}")
        if kind == "passive_action":
            for link in spec.get("links") or fail("passive_action needs links"):
                if link.get("unit") not in source_sids:
                    fail(f"link unit {link.get('unit')} is not a source unit")
                blocks = (logics.get(link["unit"]) or {}).get("passives") or []
                try:
                    blocks[link["passive"]]["actions"][link["action"]]
                except (IndexError, KeyError, TypeError):
                    fail(f"{link['unit']} has no passives[{link.get('passive')}].actions[{link.get('action')}]")
