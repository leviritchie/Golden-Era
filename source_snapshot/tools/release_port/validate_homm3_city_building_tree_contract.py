#!/usr/bin/env python3
"""Fail-closed contract: every HoMM3 city ships the canonical HoMM3 building tree.

Owner: tools/release_port/homm3_city_building_tree.py (applied by
apply_release_core_overlay.py ``apply_homm3_city_building_tree``). Doc:
docs/homm3_city_building_tree.md.

Static checks (always): the canonical table is acyclic, every dwelling above tier 1
is gated on a lower dwelling, and the HoMM3 hall/economy gates are present.

Core checks (``--core``, default the Golden Era install): for every ``homm3_*_city``
and every ``homm3_landon_*_city`` clone present -
  * each level's prevBuildings equals the canonical table exactly (no extra, no
    missing, no leftover donor gates);
  * every level that is not a declared root has at least one prerequisite, and every
    prerequisite names a building level the city has;
  * the prerequisite graph is acyclic;
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
)
from validate_city_construction_tree_layout import construction_tree_layout_errors  # noqa: E402

DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)


def _parse(key: str) -> tuple[str, int]:
    sid, level = key.rsplit(":", 1)
    return sid, int(level)


def static_errors() -> list[str]:
    errors: list[str] = []
    common = {_parse(k): v for k, v in COMMON_LEVEL_REQS.items()}
    if ("Build_Tavern", 1) not in common[("Build_Main", 2)]:
        errors.append("table: Town Hall (Build_Main@2) must require the Tavern")
    for req in (("Build_Magic_Guild", 1), ("Build_Market", 1)):
        if req not in common[("Build_Main", 3)]:
            errors.append(f"table: City Hall (Build_Main@3) must require {req[0]}@{req[1]}")
    # The Blacksmith is the vanilla OE Treasury (user decision 2026-10-01): it requires
    # exactly the vanilla Bank + Fort and, like the vanilla Treasury, gates nothing.
    if tuple(common[("Build_Treasury", 1)]) != (("Build_Bank", 1), ("Build_Wall", 1)):
        errors.append(f"table: Blacksmith (Build_Treasury@1) must require exactly Bank@1 + Wall@1, has {common[('Build_Treasury', 1)]}")
    for faction_name, entries in [("*", COMMON_LEVEL_REQS)] + list(FACTION_LEVEL_REQS.items()):
        for key, reqs in entries.items():
            if ("Build_Treasury", 1) in reqs:
                errors.append(f"table {faction_name}: {key} requires the Blacksmith; the OE Treasury gates nothing")
    for faction in HOMM3_TREE_FACTIONS:
        table = dict(common)
        table.update({_parse(k): v for k, v in FACTION_LEVEL_REQS[faction].items()})
        for tier in range(2, 8):
            reqs = table.get((f"Build_Tier_{tier}", 1))
            if reqs is None:
                errors.append(f"table {faction}: Build_Tier_{tier}@1 has no entry")
            elif not any(sid.startswith("Build_Tier_") or sid == "Build_Bank" for sid, _ in reqs):
                # Castle Training Grounds hangs off the Stables (Build_Bank), itself gated on Barracks.
                errors.append(f"table {faction}: Build_Tier_{tier}@1 is not gated on a dwelling ({reqs})")
        graph: dict[tuple[str, int], tuple[tuple[str, int], ...]] = {}
        for (sid, level), reqs in table.items():
            graph[(sid, level)] = tuple(reqs) + (((sid, level - 1),) if level > 1 else ())
        cycle = find_cycle(graph)
        if cycle:
            errors.append(f"table {faction}: cycle " + " -> ".join(f"{s}@{l}" for s, l in cycle))
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
