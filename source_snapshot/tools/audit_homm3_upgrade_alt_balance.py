#!/usr/bin/env python3
"""Audit h3_* _upg vs _upg_alt for cost parity, identical kits, and strict dominance."""
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path

STAT_KEYS = [
    "hp",
    "offence",
    "defence",
    "damageMin",
    "damageMax",
    "initiative",
    "speed",
    "actionPoints",
    "numCounters",
]
EXTRA_KEYS = ["moveType", "ignoreShootingBlock", "ignoreShootDmgBuff", "ammo"]


def cost_map(unit: dict) -> dict[str, int]:
    return {
        e["name"]: int(e["cost"])
        for e in (unit.get("unitCost") or {}).get("costResArray") or []
        if isinstance(e, dict) and isinstance(e.get("name"), str)
    }


def canonical_attack(atk: dict) -> dict:
    dealer = atk.get("damageDealer") or {}
    mechs = []
    for m in dealer.get("targetMechanics") or []:
        if isinstance(m, dict):
            mechs.append((m.get("mech"), json.dumps(m.get("values"), sort_keys=True)))
    buff = dealer.get("buff") or {}
    return {
        "type": atk.get("attackType_"),
        "pattern": dealer.get("attackPatternSid"),
        "statDmgMult": dealer.get("statDmgMult"),
        "buff": buff.get("sid"),
        "cd": atk.get("cd"),
        "charges": atk.get("charges"),
        "energyLevel": atk.get("energyLevel"),
        "triggerCounter": dealer.get("triggerCounter"),
        "multitarget": dealer.get("multitargetType"),
        "numTargets": dealer.get("numTargets"),
        "tags": sorted(dealer.get("tags") or []),
        "mechs": sorted(mechs),
    }


def kit_fingerprint(unit: dict) -> dict:
    stats = unit.get("stats") or {}
    return {
        "extra": {k: stats.get(k) for k in EXTRA_KEYS},
        "default": [canonical_attack(a) for a in (unit.get("defaultAttacks") or []) if isinstance(a, dict)],
        "counter": [canonical_attack(a) for a in (unit.get("counterAttacks") or []) if isinstance(a, dict)],
        "alternative": [canonical_attack(a) for a in (unit.get("alternativeAttacks") or []) if isinstance(a, dict)],
        "abilities": [canonical_attack(a) for a in (unit.get("abilities") or []) if isinstance(a, dict)],
        "passives": sorted(json.dumps(p, sort_keys=True) for p in (unit.get("passives") or [])),
        "immunities": sorted(json.dumps(p, sort_keys=True) for p in (unit.get("immunities") or [])),
        "disablers": sorted(json.dumps(p, sort_keys=True) for p in (unit.get("disablers") or [])),
    }


def load_units(core: Path) -> dict[str, dict]:
    units: dict[str, dict] = {}
    with zipfile.ZipFile(core) as archive:
        for name in archive.namelist():
            if "/units/units_logics/" not in name or not name.endswith(".json"):
                continue
            for unit in json.loads(archive.read(name)).get("array") or []:
                units[unit["id"]] = unit
    return units


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--core-zip",
        type=Path,
        default=Path(
            r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
            r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
        ),
    )
    args = parser.parse_args()
    units = load_units(args.core_zip)

    cost_mismatches = []
    identical_kits = []
    strict_better_equal_cost = []

    for alt_id, alt in sorted(units.items()):
        if not alt_id.startswith("h3_") or not alt_id.endswith("_upg_alt"):
            continue
        upg_id = alt_id[: -len("_alt")]
        upg = units.get(upg_id)
        if upg is None:
            continue
        cu, ca = cost_map(upg), cost_map(alt)
        if cu != ca:
            cost_mismatches.append((upg_id, alt_id, cu, ca))

        same_kit = kit_fingerprint(upg) == kit_fingerprint(alt)
        if same_kit:
            identical_kits.append((upg_id, alt_id, cu, ca))

        su, sa = upg.get("stats") or {}, alt.get("stats") or {}
        better = worse = False
        deltas = {}
        for key in STAT_KEYS:
            a, b = su.get(key), sa.get(key)
            if a is None or b is None:
                continue
            d = b - a
            if d:
                deltas[key] = d
            if d > 0:
                better = True
            elif d < 0:
                worse = True
        if better and not worse and cu == ca:
            # only flag if kit is not a clear role-swap (shoot->melee)
            upg_types = {(a.get("attackType_") if isinstance(a, dict) else None) for a in (upg.get("defaultAttacks") or [])}
            alt_types = {(a.get("attackType_") if isinstance(a, dict) else None) for a in (alt.get("defaultAttacks") or [])}
            role_swap = ("shoot" in upg_types and "melee" in alt_types and "shoot" not in alt_types)
            if not role_swap:
                strict_better_equal_cost.append((upg_id, alt_id, deltas, same_kit))

    print(f"core={args.core_zip}")
    print(f"cost_mismatches={len(cost_mismatches)}")
    for row in cost_mismatches:
        print("  COST", row)
    print(f"identical_kits={len(identical_kits)}")
    for row in identical_kits:
        print("  SAME_KIT", row)
    print(f"strict_better_equal_cost_no_roleswap={len(strict_better_equal_cost)}")
    for row in strict_better_equal_cost:
        print("  STRICT", row)

    failed = bool(cost_mismatches or identical_kits or strict_better_equal_cost)
    if failed:
        print("AUDIT_FAILED")
        return 1
    print("AUDIT_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
