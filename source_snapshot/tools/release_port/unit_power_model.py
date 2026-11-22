#!/usr/bin/env python3
"""Effective-output score for battle units, read from built Core rows (vanilla and custom alike).

Why: the 2026-11-20 pilot placed stats in the vanilla tier band and counted cards, but never priced what a card
does. Double Shot and a -10% resist card both counted as "one passive". This model scores what a unit actually
puts out and absorbs over a standard three-round fight with its whole kit applied, so a strong card has to be
paid for in the body, the way vanilla pays for it (plan: docs/unit_rebalance_plan_20261120.md, section 4b).

Per creature:
  offence   expected damage over three rounds against the tier's median vanilla Defence: basic attacks (range
            falloff, melee block, time to contact from Speed, charge bonus, area shape, Double Strike/Shot,
            armour penetration, typed damage bonuses), counterattacks, and what each active adds per use;
  toughness HP as effective HP against the tier's median vanilla Attack, with resistances weighted by how
            often each damage type lands, caps and wards;
  power     sqrt(offence * toughness), times a small credit for abilities the model cannot price (control,
            dispels, heals), times weekly growth for the stack-level figure the gates use.

The reader is generic: it knows stat keys, sequence effects, attack patterns, ability dealers and buff rows,
not unit names. What it cannot read gets the flat utility credit, the same for vanilla and custom units, so the
comparison stays fair. Plugin-side rules (Homm3UnitKitRules) are passed in as `extras`.

Assumed damage rule (classic, not read from the game): +5% per point of Attack over Defence up to +300%,
-2.5% per point under down to -70%. Both sides of every comparison go through the same function.

    python tools/release_port/unit_power_model.py calibrate --core <vanilla Core.zip>   # writes unit_power_bands.json
    python tools/release_port/unit_power_model.py score --core <Core.zip> [--faction homm3_rampart] [--sid h3_x]
"""
from __future__ import annotations

import argparse
import copy
import json
import math
import statistics
import sys
import zipfile
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
BANDS_PATH = HERE / "unit_power_bands.json"
ROUNDS = 3.0
# Share of incoming damage by type for an average stack (melee, shots, reach attacks, spells).
INCOMING = {"melee_attack": 0.45, "shoot_attack": 0.22, "range_attack": 0.08, "magic_damage": 0.25}
BASIC_TYPES = ("melee_attack", "shoot_attack", "range_attack")
EXTRA_TARGET_OCCUPANCY = 0.15  # chance that one more hex of an area shape holds an enemy stack
SHOOTER_EXPOSURE = 0.7         # share of the usual incoming damage a shooter takes (it is reached late)
UTILITY_CREDIT = 0.03          # power credit per unpriced ability, capped
UTILITY_CAP = 0.15
STAT_NUMERIC = ("hp", "offence", "defence", "damageMin", "damageMax", "speed", "initiative", "numCounters",
                "damagePerHex", "armorPen", "attackPen", "inAllDmgMod", "outAllDmgMod")


def load_json(zf: zipfile.ZipFile, name: str) -> Any:
    return json.loads(zf.read(name).decode("utf-8-sig"))


def ad_mult(attack: float, defence: float) -> float:
    delta = attack - defence
    return min(4.0, 1.0 + 0.05 * delta) if delta >= 0 else max(0.3, 1.0 + 0.025 * delta)


class Core:
    """Unit logic rows, attack patterns, buffs and weekly growth of one Core.zip."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            self.units: dict[str, dict[str, Any]] = {}
            self.patterns: dict[str, float] = {}
            self.buffs: dict[str, dict[str, Any]] = {}
            self.growth: dict[str, int] = {}
            for name in names:
                if not name.endswith(".json"):
                    continue
                if name.startswith("DB/units/units_logics/"):
                    for row in load_json(zf, name).get("array", []):
                        if isinstance(row, dict) and "stats" in row and "id" in row:
                            self.units[row["id"]] = row
                elif name.startswith("DB/attack_patterns/"):
                    for row in load_json(zf, name).get("array", []):
                        self.patterns[row["id"]] = pattern_value(row)
                elif name.startswith("DB/buffs/"):
                    doc = load_json(zf, name)
                    for row in (doc.get("array") or []) if isinstance(doc, dict) else []:
                        if isinstance(row, dict) and isinstance(row.get("id"), str):
                            self.buffs[row["id"]] = row
                elif name.startswith("DB/objects_logic/cities/"):
                    _walk_growth(load_json(zf, name), self.growth)

    def replace_units(self, rows: dict[str, dict[str, Any]], buffs: dict[str, dict[str, Any]] | None = None) -> None:
        self.units.update(rows)
        if buffs:
            self.buffs.update(buffs)


def _walk_growth(node: Any, growth: dict[str, int]) -> None:
    if isinstance(node, dict):
        if isinstance(node.get("sids"), list) and isinstance(node.get("weeklyIncrement"), int):
            for sid in node["sids"]:
                growth.setdefault(sid, node["weeklyIncrement"])
        for value in node.values():
            _walk_growth(value, growth)
    elif isinstance(node, list):
        for value in node:
            _walk_growth(value, growth)


def pattern_value(row: dict[str, Any]) -> float:
    """Expected damage multiple of an attack shape: the main cell plus every other cell at the occupancy rate."""
    best = 1.0
    for rot in row.get("rotations") or []:
        cells = sorted((c for c in rot.get("damagePattern") or [] if c), reverse=True)
        if cells:
            extra = sum(cells[1:])
            # Large shapes cannot all be full: saturate the extra-cell credit.
            best = cells[0] + EXTRA_TARGET_OCCUPANCY * min(extra, 4.0) + 0.05 * max(0.0, extra - 4.0)
            break
    return best


def _mods(stats: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = stats.get(key)
    return list(value.get("list") or []) if isinstance(value, dict) else []


def _sequence_effects(row: dict[str, Any]) -> set[str]:
    return {p["data"]["sequenceEffect"] for p in row.get("passives", []) if isinstance(p, dict) and "sequenceEffect" in p.get("data", {})}


def _apply_buff_stats(row: dict[str, Any], buff: dict[str, Any], sign: float = 1.0) -> dict[str, Any]:
    out = copy.deepcopy(row)
    stats = out["stats"]
    data = buff.get("data") or {}
    for key, value in (data.get("stats") or {}).items():
        if key in ("inDmgMods", "outDmgMods") and isinstance(value, dict):
            stats.setdefault(key, {"list": []}).setdefault("list", []).extend(
                {"t": m["t"], "v": sign * m["v"]} for m in value.get("list") or [])
        elif isinstance(value, bool):
            stats[key] = value
        elif isinstance(value, (int, float)):
            stats[key] = stats.get(key, 0) + sign * value
    if "sequenceEffect" in data:
        out.setdefault("passives", []).append({"data": {"sequenceEffect": data["sequenceEffect"]}})
    return out


def _dealer_value(core: Core, row: dict[str, Any], dealer: dict[str, Any], ref: dict[str, float]) -> float:
    stats = row["stats"]
    avg = (stats["damageMin"] + stats["damageMax"]) / 2.0
    mult = dealer.get("statDmgMult", 1.0)
    if mult is None or mult <= 0:
        return 0.0
    tags = set(dealer.get("tags") or [])
    out = stats.get("outAllDmgMod", 0.0) or 0.0
    for mod in _mods(stats, "outDmgMods"):
        if mod.get("t") in tags or (mod.get("t") == "basic_attack" and tags & set(BASIC_TYPES)):
            out += mod.get("v", 0.0)
    pen = min(0.9, stats.get("armorPen", 0.0) or 0.0)
    pattern = core.patterns.get(dealer.get("attackPatternSid", ""), 1.0)
    return avg * ad_mult(stats["offence"], ref["defence"] * (1.0 - pen)) * mult * pattern * (1.0 + out)


def _uses(ability: dict[str, Any]) -> float:
    cd = max(0, ability.get("cd") or 0)
    energy = max(1, ability.get("energyLevel") or 1)
    uses = min(ROUNDS / (cd + 1.0) if cd else ROUNDS, 4.5 / energy)
    charges = ability.get("charges")
    if isinstance(charges, int) and charges > 0:
        uses = min(uses, charges)
    return max(0.0, min(uses, ROUNDS))


def _base_score(core: Core, row: dict[str, Any], ref: dict[str, float]) -> tuple[float, float, dict[str, float]]:
    """Offence and toughness of the stat block with passives, without actives or buffs."""
    stats = row["stats"]
    seq = _sequence_effects(row)
    main = row["defaultAttacks"][0]
    dealer = main["damageDealer"]
    shooter = main.get("attackType_") == "shoot"
    value = _dealer_value(core, row, dealer, ref)
    parts: dict[str, float] = {}
    if shooter:
        falloff = 0.0 if stats.get("ignoreShootDmgBuff") else min(0.9, -(dealer.get("shootDmgBuff") or 0.0) * (dealer.get("shootRedCount") or 0))
        alt = row.get("alternativeAttacks") or []
        melee = _dealer_value(core, row, alt[0]["damageDealer"], ref) if alt else value * 0.5
        blocked = 0.0 if stats.get("ignoreShootingBlock") else 0.4
        rounds = (1.0 - 0.8 * falloff) + (1.0 - 0.3 * falloff) + ((1.0 - blocked) + blocked * (melee / value if value else 0.0))
        basic = value * rounds * (2.0 if "add_attack_after_counter_shoot" in seq else 1.0)
    else:
        speed = stats["speed"] * (1.15 if stats.get("moveType") in ("fly", "teleport") else 1.0)
        rounds = max(1.0, min(ROUNDS, 3.3 - 14.0 / (speed + ref["speed"])))
        charge = (stats.get("damagePerHex", 0.0) or 0.0) * min(stats["speed"], 7) * 1.0
        basic = value * rounds * (1.0 + charge) * (1.85 if "add_attack_after_counter_melee" in seq else 1.0)
    parts["basic"] = basic
    counters = row.get("counterAttacks") or []
    n = stats.get("numCounters", 1) or 0
    counter_value = _dealer_value(core, row, counters[0]["damageDealer"], ref) if counters and n > 0 else 0.0
    attacked = 0.8 if shooter else 1.8   # melee attacks received over the three rounds
    counter = counter_value * min(attacked, {0: 0.0, 1: 1.0}.get(n, 1.35 if n == 2 else 1.6))
    parts["counter"] = counter
    initiative = max(0.85, min(1.2, 1.0 + 0.02 * (stats["initiative"] - ref["initiative"])))
    offence = (basic + counter) * initiative
    weighted = 0.0
    for mod in _mods(stats, "inDmgMods"):
        kind, v = mod.get("t"), mod.get("v", 0.0)
        if kind == "basic_attack":
            weighted += v * sum(INCOMING[k] for k in BASIC_TYPES)
        elif kind in INCOMING:
            weighted += v * INCOMING[kind]
    weighted += stats.get("inAllDmgMod", 0.0) or 0.0
    taken = max(0.2, 1.0 + weighted)
    if dealer.get("triggerCounter") is False and not shooter:
        taken *= 0.95   # strikes without taking the counterattack
    if "counter_before_attack" in seq:
        taken *= 0.8
    if stats.get("alwaysTakeMinDmg"):
        taken *= 0.85
    if stats.get("overkillProtection") or stats.get("maxInDmg"):
        taken *= 0.9
    if shooter:
        taken *= SHOOTER_EXPOSURE
    attack_pen = min(0.9, stats.get("attackPen", 0.0) or 0.0)
    toughness = stats["hp"] / (ad_mult(ref["offence"] * (1.0 - attack_pen), stats["defence"]) * taken)
    return offence, toughness, parts


def score_unit(core: Core, row: dict[str, Any], refs: dict[str, dict[str, float]], extras: dict[str, dict[str, float]] | None = None) -> dict[str, Any]:
    ref = refs[str(row["tier"])]
    offence, toughness, parts = _base_score(core, row, ref)
    round_basic = parts["basic"] / ROUNDS
    notes: list[str] = []
    utility = 0.0
    off_mult = tough_mult = 1.0

    def buff_effect(buff_sid: str, target: str, uptime: float, label: str) -> bool:
        nonlocal off_mult, tough_mult
        buff = core.buffs.get(buff_sid)
        if not buff or not (buff.get("data") or {}).get("stats") and "sequenceEffect" not in (buff.get("data") or {}):
            return False
        enemy = target in ("enemy", "noself_enemy")
        o2, t2, _ = _base_score(core, _apply_buff_stats(row, buff, -1.0 if enemy else 1.0), ref)
        d_off, d_tough = o2 / offence - 1.0, t2 / toughness - 1.0
        if enemy:
            # A debuff on one enemy stack: its lost output is our toughness, its lost toughness our output.
            d_off, d_tough = d_tough, d_off
            scope = 0.5
        else:
            scope = 1.0 if target == "self" else 0.8
        if abs(d_off) < 1e-6 and abs(d_tough) < 1e-6:
            return False
        off_mult += d_off * uptime * scope
        tough_mult += d_tough * uptime * scope
        notes.append(f"{label}: {buff_sid} off {d_off * uptime * scope:+.0%} tough {d_tough * uptime * scope:+.0%}")
        return True

    added = 0.0
    for ability in row.get("abilities") or []:
        dealer = ability.get("damageDealer") or {}
        uses = _uses(ability)
        free = ability.get("actionCost") == 0
        value = _dealer_value(core, row, dealer, ref) if dealer.get("damageTarget_") in ("enemy", "all", "noself") else 0.0
        priced = False
        if value > 0:
            gain = value if free else max(0.0, value - round_basic)
            if dealer.get("triggerCounter") is False and row["defaultAttacks"][0].get("attackType_") != "shoot":
                gain += 0.05 * value
            added += gain * uses
            notes.append(f"active dmg x{uses:.1f}: +{gain * uses:.1f}")
            priced = True
        buff = dealer.get("buff") or {}
        if buff.get("sid"):
            duration = buff.get("duration", 1)
            uptime = min(1.0, uses * (ROUNDS if duration is None or duration < 0 else min(duration, ROUNDS)) / ROUNDS)
            # A buff that costs the unit's action gives up a round of attacks for each use.
            cost = 0.0 if free or value > 0 else uses * round_basic
            if buff_effect(buff["sid"], dealer.get("buffTarget_", "self"), uptime, "active buff"):
                added -= cost
                priced = True
        if not priced or dealer.get("targetMechanics"):
            utility += 1.0 if not priced else 0.5
    for passive in row.get("passives") or []:
        if not isinstance(passive, dict):
            continue
        for action in passive.get("actions") or []:
            dealer = action.get("damageDealer") or {}
            buff = dealer.get("buff") or {}
            if not (buff.get("sid") and buff_effect(buff["sid"], dealer.get("buffTarget_", "self"), 0.5, f"on {action.get('trigger')}")):
                utility += 0.5
        if (passive.get("data") or {}).get("sideModifiers"):
            utility += 1.0
    aura = row.get("aura")
    if isinstance(aura, dict):
        reach = 0.35 if (aura.get("radius") or 1) <= 1 else 0.6
        fake = {"data": aura.get("data") or {}}
        core.buffs["__aura__"] = fake
        target = "enemy" if aura.get("target") == "enemy" else ("self" if aura.get("target") == "ally" else "ally")
        scale = reach * (2.0 if target != "enemy" else 2.0)   # an aura reaches about two stacks
        if not buff_effect("__aura__", target, min(1.0, scale), "aura"):
            utility += 1.0
        core.buffs.pop("__aura__", None)
    utility += 0.5 * len(row.get("globalPassives") or []) + 0.5 * len(row.get("conditionalPassives") or [])
    extra = (extras or {}).get(row["id"]) or {}
    off_mult *= extra.get("off", 1.0)
    tough_mult *= extra.get("tough", 1.0)
    offence = max(0.01, (offence + added * max(0.85, min(1.2, 1.0 + 0.02 * (row["stats"]["initiative"] - ref["initiative"])))) * max(0.3, off_mult))
    toughness = toughness * max(0.3, tough_mult)
    credit = 1.0 + min(UTILITY_CAP, UTILITY_CREDIT * utility)
    growth = core.growth.get(row["id"], 0)
    power = math.sqrt(offence * toughness) * credit
    return {
        "sid": row["id"], "tier": row["tier"], "variant": "upg" if row.get("baseSid") else "base",
        "offence": offence, "toughness": toughness, "power": power, "utility": utility, "growth": growth,
        "weeklyPower": power * growth, "weeklyOffence": offence * growth, "weeklyToughness": toughness * growth,
        "notes": notes, "parts": parts,
    }


def runtime_extras(designs: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    """Plugin-side kit rules (not in Core rows) as offence / toughness multipliers."""
    extras: dict[str, dict[str, float]] = {}
    for doc in designs.values():
        for sid, unit in doc["units"].items():
            off = tough = 1.0
            for entry in unit["kit"]:
                # offMult / toughMult price what the built rows cannot show (plugin rules, buff swaps) on any entry.
                pct = entry.get("percent", 0) / 100.0
                rule = entry.get("rule") if entry.get("k") == "runtime" else None
                if rule == "adjacent_ally_ward":
                    tough *= 1.0 / (1.0 - min(entry.get("cap", 0) / 100.0, pct * 1.5))
                elif rule == "hit_cap":
                    tough *= 1.0 + 0.25 * (0.5 - pct) / 0.3 if pct < 0.5 else 1.0
                elif rule == "grudge":
                    off *= 1.0 + pct * 0.45
                elif rule == "damage_vs_buff":
                    off *= 1.0 + pct * 0.5
                elif rule == "loss_fury":  # ramps as the stack dies: about a third of the cap over a fight
                    off *= 1.0 + entry.get("cap", 0) / 100.0 * 0.3
                elif rule == "death_toll":  # two to three stacks fall over the standard fight
                    off *= 1.0 + min(entry.get("cap", 0) / 100.0, pct * 2.5) * 0.6
                off *= entry.get("offMult", 1.0)
                tough *= entry.get("toughMult", 1.0)
            if off != 1.0 or tough != 1.0:
                extras[sid] = {"off": off, "tough": tough}
    return extras


def faction_rows(core: Core) -> list[dict[str, Any]]:
    rows = []
    for row in core.units.values():
        if row["id"] in core.growth and isinstance(row.get("tier"), int) and 1 <= row["tier"] <= 7:
            rows.append(row)
    return rows


def calibrate(core_path: str) -> dict[str, Any]:
    core = Core(core_path)
    rows = [r for r in faction_rows(core) if not r["id"].startswith("h3_")]
    refs: dict[str, dict[str, float]] = {}
    for tier in range(1, 8):
        upg = [r["stats"] for r in rows if r["tier"] == tier and r.get("baseSid")]
        refs[str(tier)] = {k: statistics.median(s[k] for s in upg) for k in ("offence", "defence", "speed", "initiative", "hp")}
    scores = [score_unit(core, r, refs) for r in rows]
    bands: dict[str, Any] = {}
    for tier in range(1, 8):
        for variant in ("base", "upg"):
            group = [s for s in scores if s["tier"] == tier and s["variant"] == variant]
            entry: dict[str, Any] = {"n": len(group), "units": {s["sid"]: round(s["weeklyPower"], 1) for s in group}}
            for key in ("weeklyPower", "weeklyOffence", "weeklyToughness"):
                values = sorted(s[key] for s in group)
                entry[key] = {"min": round(values[0], 2), "median": round(statistics.median(values), 2), "max": round(values[-1], 2)}
            entry["squadValuePerPower"] = round(statistics.median(core.units[s["sid"]]["squadValue"] / s["power"] for s in group), 4)
            bands[f"{tier}:{variant}"] = entry
    return {"schemaVersion": 1, "source": core_path, "refs": refs, "bands": bands}


def load_bands() -> dict[str, Any]:
    return json.loads(BANDS_PATH.read_text(encoding="utf-8"))


# Gate: a unit's weekly power sits between LOW and HIGH times the vanilla median of its tier and class, and its
# weekly offence and toughness stay under the vanilla maximum of the group (with a little headroom).
POWER_LOW, POWER_HIGH = 0.85, 1.15
PEAK_HEADROOM = 1.05


def gate(score: dict[str, Any], bands: dict[str, Any]) -> list[str]:
    band = bands["bands"][f"{score['tier']}:{score['variant']}"]
    median = band["weeklyPower"]["median"]
    errors = []
    ratio = score["weeklyPower"] / median
    if not POWER_LOW <= ratio <= POWER_HIGH:
        errors.append(f"{score['sid']}: weekly power {score['weeklyPower']:.0f} is {ratio:.2f}x the vanilla tier {score['tier']} {score['variant']} median {median:.0f} (allowed {POWER_LOW}..{POWER_HIGH})")
    for key, label in (("weeklyOffence", "offence"), ("weeklyToughness", "toughness")):
        top = band[key]["max"] * PEAK_HEADROOM
        if score[key] > top:
            errors.append(f"{score['sid']}: weekly {label} {score[key]:.0f} above the vanilla tier {score['tier']} {score['variant']} maximum {band[key]['max']:.0f}")
    return errors


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("calibrate", "score"))
    parser.add_argument("--core", required=True)
    parser.add_argument("--faction")
    parser.add_argument("--sid")
    parser.add_argument("--notes", action="store_true")
    args = parser.parse_args()
    if args.mode == "calibrate":
        data = calibrate(args.core)
        BANDS_PATH.write_text(json.dumps(data, indent=1) + "\n", encoding="utf-8")
        for key, band in data["bands"].items():
            print(key, band["n"], band["weeklyPower"], "off", band["weeklyOffence"], "tough", band["weeklyToughness"])
        return 0
    bands = load_bands()
    core = Core(args.core)
    sys.path.insert(0, str(HERE))
    import homm3_unit_design_table as design  # noqa: E402
    extras = runtime_extras(design.load_designs())
    failed = 0
    for row in sorted(faction_rows(core), key=lambda r: (r.get("fraction", ""), r["tier"], r["id"])):
        if args.faction and row.get("fraction") != args.faction or args.sid and row["id"] != args.sid:
            continue
        s = score_unit(core, row, bands["refs"], extras)
        median = bands["bands"][f"{s['tier']}:{s['variant']}"]["weeklyPower"]["median"]
        errors = gate(s, bands)
        failed += bool(errors)
        print(f"{s['sid']:38} T{s['tier']} {s['variant']:4} off {s['offence']:8.1f} tough {s['toughness']:8.1f} x{s['growth']:<3} power {s['weeklyPower']:8.0f} = {s['weeklyPower'] / median:4.2f}x {'FAIL' if errors else ''}")
        if args.notes:
            for note in s["notes"]:
                print("      ", note)
    print("failed", failed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
