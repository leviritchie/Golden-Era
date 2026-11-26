#!/usr/bin/env python3
"""Fail-closed contract: every HoMM3 city ships the canonical HoMM3 building tree.

Owner: tools/release_port/homm3_city_building_tree.py (applied by
apply_release_core_overlay.py ``apply_homm3_city_building_tree``). Doc:
docs/homm3_city_building_tree.md.

Static checks (always): the canonical table is acyclic and follows the vanilla OE
conventions (building pass 2026-11-22, docs/building_pass_20261122/BRIEF.md Part B):
  * the shared economy is exactly the vanilla template (Town Hall L2/L3 need only the
    previous level, Market <- Tavern, Artifact Market <- Market, Bank <- Town Hall L2,
    Treasury <- Bank + Fort, Resource Depot <- Market + Bank) and no faction overrides it;
  * nothing requires the Blacksmith (OE Treasury) or an upgraded dwelling/special;
  * dwelling upgrades need only their own L1 (a T7 upgrade may take one Mage Guild level);
  * a dwelling L1 takes at most 2 dwellings plus one Mage Guild level (MG1/MG2), and sits
    at most 4 deep;
  * a special building takes at most one prerequisite.

Core checks (``--core``, default the Golden Era install): for every ``homm3_*_city``
and every ``homm3_landon_*_city`` clone present -
  * each level's prevBuildings equals the canonical table exactly (no extra, no
    missing, no leftover donor gates);
  * every level that is not a declared root has at least one prerequisite, and every
    prerequisite names a building level the city has;
  * the prerequisite graph is acyclic and at most 5 levels deep (strict rows, as vanilla);
  * the construction-tree layout passes validate_city_construction_tree_layout
    (grid bounds, no stacked cells, every prerequisite drawn above its dependent);
  * every AI buildOrders entry exists and comes after its prerequisites;
  * a landon clone equals its stock city except for ``id``.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

from homm3_city_building_tree import (  # noqa: E402
    COMMON_LEVEL_REQS,
    DERIVED_CITY_DONORS,
    FACTION_LEVEL_REQS,
    HOMM3_TREE_FACTIONS,
    build_order_errors,
    canonical_prereqs,
    city_level_keys,
    find_cycle,
    strict_depth,
)
from validate_city_construction_tree_layout import GRID_ROWS, construction_tree_layout_errors  # noqa: E402

DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)


def _parse(key: str) -> tuple[str, int]:
    sid, level = key.rsplit(":", 1)
    return sid, int(level)


SHARED_ECONOMY: dict[tuple[str, int], tuple[tuple[str, int], ...]] = {
    # The vanilla OE template, identical in all 6 stock cities (building pass 2026-11-22).
    ("Build_Main", 1): (),
    ("Build_Main", 2): (),
    ("Build_Main", 3): (),
    ("Build_Tavern", 1): (),
    ("Build_Market", 1): (("Build_Tavern", 1),),
    ("Build_Artifact_Market", 1): (("Build_Market", 1),),
    ("Build_Bank", 1): (("Build_Main", 2),),
    ("Build_Treasury", 1): (("Build_Bank", 1), ("Build_Wall", 1)),
    ("Build_Resource_Depot", 1): (("Build_Market", 1), ("Build_Bank", 1)),
    ("Build_Wall", 1): (),
    ("Build_Magic_Guild", 1): (),
    ("Build_Tier_1", 1): (),
}
SHARED_SIDS = {sid for sid, _ in SHARED_ECONOMY}
# A faction may re-point a shared slot SID only where that SID holds another building.
SHARED_SLOT_EXCEPTIONS = {("homm3_inferno", "Build_Resource_Depot")}  # Birthing Pools (Imp horde)
# The only non-dwelling prerequisite a dwelling L1 may take besides one Mage Guild level.
DWELLING_SPECIAL_GATES = {("homm3_castle", "Build_Tier_6"): {"Build_Stables"}}  # Training Grounds <- Stables
# Requirements on an upgraded level (L2+) are allowed only for these chains (vanilla:
# Town Hall L2 for the Bank, Mage Guild L2/L3, Wall L2 for the Mycelium Roots).
UPGRADED_PREREQ_SIDS = {"Build_Main", "Build_Magic_Guild", "Build_Wall"}
MAX_DWELLING_L1_DEPTH = 4  # every vanilla city: a dwelling L1 is at most 4 deep


def is_dwelling(sid: str) -> bool:
    return sid.startswith("Build_Tier_") or sid == "Build_Factory_Gantry"


def faction_table(faction: str) -> dict[tuple[str, int], tuple[tuple[str, int], ...]]:
    table = {_parse(k): tuple(v) for k, v in COMMON_LEVEL_REQS.items()}
    table.update({_parse(k): tuple(v) for k, v in FACTION_LEVEL_REQS[faction].items()})
    return table


def static_errors() -> list[str]:
    errors: list[str] = []
    common = {_parse(k): tuple(v) for k, v in COMMON_LEVEL_REQS.items()}
    for key, want in SHARED_ECONOMY.items():
        have = common.get(key)
        if have is None or sorted(have) != sorted(want):
            errors.append(f"table: shared {key[0]}@{key[1]} must require exactly {list(want)} (vanilla template), has {have}")
    for faction_name, entries in [("*", COMMON_LEVEL_REQS)] + list(FACTION_LEVEL_REQS.items()):
        for key, reqs in entries.items():
            if ("Build_Treasury", 1) in reqs:
                errors.append(f"table {faction_name}: {key} requires the Blacksmith; the OE Treasury gates nothing")
    for faction in HOMM3_TREE_FACTIONS:
        for key in FACTION_LEVEL_REQS[faction]:
            sid = _parse(key)[0]
            if sid in SHARED_SIDS and not is_dwelling(sid) and (faction, sid) not in SHARED_SLOT_EXCEPTIONS:
                errors.append(f"table {faction}: {key} overrides the shared economy template")
        table = faction_table(faction)
        for (sid, level), reqs in sorted(table.items()):
            where = f"table {faction}: {sid}@{level}"
            for rsid, rlevel in reqs:
                if rlevel > 1 and rsid not in UPGRADED_PREREQ_SIDS:
                    errors.append(f"{where} requires the upgraded level {rsid}@{rlevel}; vanilla never gates on an upgraded dwelling or special")
            if not is_dwelling(sid) or (sid, level) in SHARED_ECONOMY:
                if level == 1 and sid not in SHARED_SIDS and len(reqs) > 1:
                    errors.append(f"{where} is a special with {len(reqs)} prerequisites; vanilla specials take at most one")
                continue
            if level > 1:
                extra = [r for r in reqs if r != (sid, level - 1)]
                t7_mage = sid == "Build_Tier_7" and len(extra) == 1 and extra[0][0] == "Build_Magic_Guild"
                if extra and not t7_mage:
                    errors.append(f"{where} needs {extra}; a dwelling upgrade needs only its own L1 (a T7 upgrade may take one Mage Guild level)")
                continue
            dwellings = [r for r in reqs if is_dwelling(r[0])]
            guilds = [r for r in reqs if r[0] == "Build_Magic_Guild"]
            others = [r for r in reqs if r not in dwellings and r not in guilds]
            allowed = DWELLING_SPECIAL_GATES.get((faction, sid), set())
            if len(dwellings) > 2:
                errors.append(f"{where} needs {len(dwellings)} dwellings; vanilla takes at most 2")
            if len(guilds) > 1 or any(lvl > 2 for _, lvl in guilds):
                errors.append(f"{where} Mage Guild gate {guilds} exceeds one level up to MG2")
            if any(r[0] not in allowed for r in others):
                errors.append(f"{where} needs non-dwelling {others}; a dwelling L1 takes dwellings and at most one Mage Guild level")
        graph: dict[tuple[str, int], tuple[tuple[str, int], ...]] = {}
        for (sid, level), reqs in table.items():
            graph[(sid, level)] = tuple(reqs) + (((sid, level - 1),) if level > 1 else ())
        cycle = find_cycle(graph)
        if cycle:
            errors.append(f"table {faction}: cycle " + " -> ".join(f"{s}@{l}" for s, l in cycle))
            continue
        memo: dict[tuple[str, int], int] = {}

        def depth(key: tuple[str, int]) -> int:
            if key not in memo:
                memo[key] = 1 + max((depth(r) for r in graph.get(key, ()) if r in graph), default=0)
            return memo[key]

        for key in graph:
            if is_dwelling(key[0]) and key[1] == 1 and depth(key) > MAX_DWELLING_L1_DEPTH:
                errors.append(f"table {faction}: {key[0]}@1 sits {depth(key)} deep; vanilla dwellings sit at most {MAX_DWELLING_L1_DEPTH} deep")
    return errors


def city_rows(city: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for section in city.values()
        if isinstance(section, list)
        for row in section
        if isinstance(row, dict) and isinstance(row.get("sid"), str) and isinstance(row.get("parametersPerLevel"), list)
    ]


def live_prereqs(city: dict[str, Any]) -> dict[tuple[str, int], tuple[tuple[str, int], ...]]:
    out: dict[tuple[str, int], tuple[tuple[str, int], ...]] = {}
    for row in city_rows(city):
        for index, level in enumerate(row["parametersPerLevel"], start=1):
            prev = level.get("prevBuildings") if isinstance(level, dict) else None
            out[(row["sid"], index)] = tuple(
                (str(p.get("sid")), int(p.get("level", 1)))
                for p in (prev if isinstance(prev, list) else [])
                if isinstance(p, dict)
            )
    return out


def city_errors(city_sid: str, faction: str, city: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    try:
        expected = canonical_prereqs(faction, city_level_keys(city))
    except (KeyError, ValueError) as ex:
        return [f"{city_sid}: {ex}"]
    live = live_prereqs(city)
    for key in sorted(set(expected) | set(live)):
        sid, level = key
        if key not in live:
            errors.append(f"{city_sid}: {sid}@{level} missing from city")
            continue
        if sorted(live[key]) != sorted(expected.get(key, ())):
            errors.append(f"{city_sid}: {sid}@{level} prevBuildings {list(live[key])} != canonical {list(expected.get(key, ()))}")
        if not live[key] and expected.get(key):
            errors.append(f"{city_sid}: {sid}@{level} is not a declared root but has no prerequisite")
        for req in live[key]:
            if req not in live:
                errors.append(f"{city_sid}: {sid}@{level} requires {req[0]}@{req[1]}, which the city does not have")
    cycle = find_cycle(live)
    if cycle:
        errors.append(f"{city_sid}: prerequisite cycle " + " -> ".join(f"{s}@{l}" for s, l in cycle))
    elif strict_depth(live, live) > GRID_ROWS:
        # Every vanilla city draws strictly in the 5 native rows (building pass 2026-11-22).
        errors.append(f"{city_sid}: prerequisite chain is {strict_depth(live, live)} deep; vanilla cities fit {GRID_ROWS} rows strictly")
    errors.extend(f"{city_sid}: layout: {message}" for message in construction_tree_layout_errors(city))
    for build_order in city.get("buildOrders") or []:
        tag = build_order.get("buildTag") if isinstance(build_order, dict) else None
        order = build_order.get("order") if isinstance(build_order, dict) else None
        if not isinstance(order, list):
            errors.append(f"{city_sid}: buildOrders {tag!r} has no order list")
            continue
        errors.extend(f"{city_sid}: buildOrders {tag!r}: {message}" for message in build_order_errors(order, live))
    return errors


def read_city(zf: zipfile.ZipFile, city_sid: str) -> dict[str, Any] | None:
    member = f"DB/objects_logic/cities/{city_sid}.json"
    if member not in zf.namelist():
        return None
    doc = json.loads(zf.read(member).decode("utf-8-sig"))
    array = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(array, list) or not array or not isinstance(array[0], dict):
        raise ValueError(f"{member}: no array row")
    return array[0]


def core_errors(core: Path) -> list[str]:
    errors: list[str] = []
    with zipfile.ZipFile(core) as zf:
        stock: dict[str, dict[str, Any]] = {}
        for faction in HOMM3_TREE_FACTIONS:
            city_sid = f"{faction}_city"
            city = read_city(zf, city_sid)
            if city is None:
                errors.append(f"{city_sid}: missing from {core}")
                continue
            stock[city_sid] = city
            errors.extend(city_errors(city_sid, faction, city))
        for clone_sid, donor_sid in sorted(DERIVED_CITY_DONORS.items()):
            clone = read_city(zf, clone_sid)
            if clone is None:
                continue
            donor = stock.get(donor_sid)
            if donor is None:
                errors.append(f"{clone_sid}: stock donor {donor_sid} missing")
                continue
            errors.extend(city_errors(clone_sid, donor_sid[: -len("_city")], clone))
            if {**clone, "id": donor_sid} != donor:
                differing = sorted(k for k in set(clone) | set(donor) if k != "id" and clone.get(k) != donor.get(k))
                errors.append(f"{clone_sid}: differs from {donor_sid} beyond id in {differing}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--static-only", action="store_true", help="check the canonical table only")
    args = parser.parse_args()
    errors = static_errors()
    if not args.static_only:
        if not args.core.is_file():
            errors.append(f"Core.zip not found: {args.core}")
        else:
            errors.extend(core_errors(args.core))
    for message in errors:
        print(f"ERROR: {message}")
    scope = "table" if args.static_only else str(args.core)
    print(f"homm3 city building tree contract ({scope}): errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
