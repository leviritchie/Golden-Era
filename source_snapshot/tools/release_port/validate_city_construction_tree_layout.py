#!/usr/bin/env python3
"""Fail-closed layout gate for city construction trees (``parametersPerLevel[].nodePos``).

The town build screen draws every constructible building level at its ``nodePos``
cell and draws an arrow from each ``prevBuildings`` entry to the level that needs
it. ``yPos`` grows downward (``Build_Main`` L1 is y=0, L2 is y=1), so a readable
tree needs every prerequisite on a row strictly above its dependent.

Native grid capacity (source/static evidence, Golden Era):
- ``BhUIBuildingSession.Init`` indexes ``buildingsUIs[yPos * 10 + xPos]``
  (Cpp2IL ISIL: ``lea eax,[rdx+rdx*4]; lea edx,[r8+rax*2]`` with xPos at +0x10 and
  yPos at +0x14 of ``NodePosition``; class const ``bzgp = 10``), see
  ``experiments/cpp2il_readable_csharp/samples/latest_refresh/town_BhUIBuildingSession_Init_dossier.md``.
- The ``BUILDING VIEW PANEL`` in scene ``level53`` carries exactly 50 pre-placed
  ``BuidingPrefab`` cells under ``BUIDLING VIEWS`` (10 columns x 5 rows).
So a node outside x 0..9 / y 0..4 has no view cell, and a tree whose prerequisite
chain is deeper than 5 rows cannot keep every prerequisite strictly above.

Clickable range (installed-data evidence, 2026-10-02): column 9 has a view cell but is
covered by other build-screen UI, so a building drawn there cannot be clicked (user
report 2026-10-02: Bulwark, Conflux, Cove, Dungeon, Fortress, Inferno and Rampart cells
at x=9). Every stock OE city (``human``, ``demon``, ``dungeon``, ``nature``, ``undead``,
``unfrozen``) in both the Steam and the Golden Era ``Core.zip`` uses columns 0..8 only,
so ``VANILLA_MAX_COLUMN`` = 8 is the contract.

Rules (every city in ``DB/objects_logic/cities/``):
1. every nodePos is inside the native 10x5 grid and within the vanilla clickable
   columns 0..VANILLA_MAX_COLUMN;
2. no two constructible levels share a cell;
3. every prerequisite sits on a strictly smaller yPos than its dependent;
4. the only relaxation of (3): when the city's prerequisite chain is deeper than
   the 5 native rows (impossible to lay out strictly without changing
   ``prevBuildings``), an upgrade level may sit on the *same* row as the level of
   the same building directly before it, in an adjacent column. Nothing may ever
   sit below its dependent, and vanilla cities (depth <= 5) get no relaxation.

``homm3_landon_*`` cities are derived clones of ``homm3_castle_city`` /
``homm3_dungeon_city`` re-emitted by the campaign installer
(``experiments/campaign_port_poc/approach_cell/surface_emit.py``); they are checked
only with ``--include-derived`` because a Core overlay candidate still carries the
clones emitted from the previous overlay.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

GRID_COLUMNS = 10
GRID_ROWS = 5
# Highest column any stock OE city draws a building on; column 9 is occluded.
VANILLA_MAX_COLUMN = 8
CLICKABLE_COLUMNS = VANILLA_MAX_COLUMN + 1
CITY_PREFIX = "DB/objects_logic/cities/"
DERIVED_CITY_PREFIX = "homm3_landon_"

DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)

Key = tuple[str, int]


def city_nodes(city: dict[str, Any]) -> tuple[dict[Key, tuple[int, int]], dict[Key, list[Key]], list[str]]:
    """Return (nodePos by (sid, level), prevBuildings by (sid, level), shape errors)."""
    pos: dict[Key, tuple[int, int]] = {}
    prev: dict[Key, list[Key]] = {}
    errors: list[str] = []
    for items in city.values():
        if not isinstance(items, list):
            continue
        for row in items:
            if not isinstance(row, dict) or not isinstance(row.get("sid"), str):
                continue
            levels = row.get("parametersPerLevel")
            if not isinstance(levels, list):
                continue
            for level_index, level in enumerate(levels, start=1):
                if not isinstance(level, dict):
                    continue
                key = (row["sid"], level_index)
                node = level.get("nodePos")
                if node is not None:
                    try:
                        pos[key] = (int(node["xPos"]), int(node["yPos"]))
                    except (KeyError, TypeError, ValueError):
                        errors.append(f"{row['sid']}@{level_index} has invalid nodePos {node!r}")
                reqs: list[Key] = []
                for item in level.get("prevBuildings") or []:
                    if isinstance(item, dict) and isinstance(item.get("sid"), str):
                        lvl = item.get("level", 1)
                        reqs.append((item["sid"], int(lvl) if isinstance(lvl, int) else 1))
                prev[key] = reqs
    return pos, prev, errors


def prerequisite_depth(pos: dict[Key, tuple[int, int]], prev: dict[Key, list[Key]]) -> int:
    """Longest prerequisite chain (in nodes) among positioned levels."""

    memo: dict[Key, int] = {}
    visiting: set[Key] = set()

    def depth(key: Key) -> int:
        if key in memo:
            return memo[key]
        if key in visiting:
            raise ValueError(f"prerequisite cycle through {key[0]}@{key[1]}")
        visiting.add(key)
        reqs = [q for q in prev.get(key, []) if q in pos]
        memo[key] = 1 + max((depth(q) for q in reqs), default=0)
        visiting.discard(key)
        return memo[key]

    return max((depth(k) for k in pos), default=0)


def construction_tree_layout_errors(city: dict[str, Any]) -> list[str]:
    pos, prev, errors = city_nodes(city)
    for key, (x, y) in sorted(pos.items()):
        if not (0 <= x < GRID_COLUMNS and 0 <= y < GRID_ROWS):
            errors.append(
                f"{key[0]}@{key[1]} nodePos ({x},{y}) is outside the native "
                f"{GRID_COLUMNS}x{GRID_ROWS} build-tree grid"
            )
        elif x > VANILLA_MAX_COLUMN:
            errors.append(
                f"{key[0]}@{key[1]} nodePos ({x},{y}) is beyond the vanilla clickable column "
                f"range 0..{VANILLA_MAX_COLUMN} (column {x} is covered by other build-screen UI)"
            )
    occupied: dict[tuple[int, int], Key] = {}
    for key, cell in sorted(pos.items()):
        prior = occupied.get(cell)
        if prior is not None:
            errors.append(f"nodePos collision at {cell}: {prior[0]}@{prior[1]} and {key[0]}@{key[1]}")
        else:
            occupied[cell] = key
    try:
        over_capacity = prerequisite_depth(pos, prev) > GRID_ROWS
    except ValueError as ex:
        return errors + [str(ex)]
    for key, reqs in sorted(prev.items()):
        if key not in pos:
            continue
        x, y = pos[key]
        for req in reqs:
            if req not in pos:
                continue
            rx, ry = pos[req]
            if ry < y:
                continue
            side_upgrade = (
                over_capacity
                and req[0] == key[0]
                and req[1] == key[1] - 1
                and ry == y
                and abs(rx - x) == 1
            )
            if side_upgrade:
                continue
            where = "below" if ry > y else "on the same row as"
            errors.append(
                f"{key[0]}@{key[1]} at ({x},{y}) needs {req[0]}@{req[1]} at ({rx},{ry}), "
                f"which is {where} it"
            )
    return errors


def city_documents(zf: zipfile.ZipFile) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for name in sorted(zf.namelist()):
        if not (name.startswith(CITY_PREFIX) and name.endswith(".json")):
            continue
        doc = json.loads(zf.read(name).decode("utf-8-sig"))
        for city in doc.get("array", []) if isinstance(doc, dict) else []:
            if isinstance(city, dict):
                out.append((str(city.get("id") or name), city))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument(
        "--include-derived",
        action="store_true",
        help="Also check homm3_landon_* campaign clones (re-emitted by the campaign installer).",
    )
    args = parser.parse_args()
    failures = 0
    checked = 0
    with zipfile.ZipFile(args.core) as zf:
        for city_id, city in city_documents(zf):
            if city_id.startswith(DERIVED_CITY_PREFIX) and not args.include_derived:
                print(f"skip derived campaign clone {city_id} (use --include-derived)")
                continue
            checked += 1
            errors = construction_tree_layout_errors(city)
            if errors:
                failures += 1
                for message in errors:
                    print(f"ERROR: {city_id}: {message}")
    print(f"city construction-tree layout: cities={checked} failing={failures}")
    if checked == 0:
        print("ERROR: no city documents found under " + CITY_PREFIX)
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
