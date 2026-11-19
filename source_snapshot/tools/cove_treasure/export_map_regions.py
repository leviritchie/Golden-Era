#!/usr/bin/env python3
"""Export a finished Olden Era .map's regions for the Cove treasure plan harness.

Usage: python export_map_regions.py <map file> <out.json>
Writes {name, width, height, seed, areas:[{id, nodes, holders:[node], dig:[node]}], catalog}.
Holders = interactable map objects (Core DB/map/objects isInteractable) plus squads; dig tiles = area tiles with no
object, no road, no water. This is an offline approximation of the runtime candidate rules, good for spacing,
determinism and timing checks.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))
import port_homecoming_poc as poc  # noqa: E402


def load_json(z: zipfile.ZipFile, name: str):
    return json.loads(z.read(name).decode("utf-8-sig"))


def main() -> int:
    src, out = Path(sys.argv[1]), Path(sys.argv[2])
    container = poc.read_olden_map_container(src)
    m = container.chunks[1]
    width, height = m["sizeX_"], m["sizeZ_"]

    interactable: set[str] = set()
    artifacts, units = [], []
    with zipfile.ZipFile(poc.OLDEN_CORE_ZIP) as z:
        for name in z.namelist():
            if name.startswith("DB/map/objects/") and name.endswith(".json"):
                for row in load_json(z, name).get("array", []):
                    if row.get("isInteractable"):
                        interactable.add(row.get("id"))
            elif name.startswith("DB/items/items/") and name.endswith(".json"):
                for row in load_json(z, name).get("array", []):
                    if row.get("goodsValue") and not row.get("isSpecialItem"):
                        artifacts.append({"sid": row["id"], "value": int(row["goodsValue"])})
        whitelist = ["skeleton", "h3_skeleton", "h3_gargoyle", "h3_golem", "h3_wight", "h3_air", "h3_automaton",
                     "h3_vampire", "h3_lich", "avatar_of_war", "h3_black_knight", "mech_guard"]
        for name in z.namelist():
            match = re.search(r"DB/units/units_logics/.*/([^/]+)_l\.json$", name)
            if match and match.group(1) in whitelist:
                data = load_json(z, name)
                row = data["array"][0] if "array" in data else data
                if row.get("squadValue"):
                    units.append({"sid": match.group(1), "squadValue": int(row["squadValue"]),
                                  "tier": int(row.get("tier", 1))})

    occupied: set[int] = set()
    holder_nodes: set[int] = set()
    for group in m["objects"]:
        nodes = group.get("nodes", [])
        occupied.update(nodes)
        if group.get("sid") in interactable:
            holder_nodes.update(nodes)
    for squad in m.get("squads", []):
        node = squad.get("node")
        if isinstance(node, int):
            occupied.add(node)
            holder_nodes.add(node)
    roads, water = m["roadsMap"], m["waterMap"]

    def flat(value):
        return value if isinstance(value, list) else list(value)

    roads, water = flat(roads), flat(water)
    areas = []
    for area in m["areas"]:
        nodes = area["nodes"]
        areas.append({
            "id": area["id"],
            "nodes": nodes,
            "holders": sorted(n for n in nodes if n in holder_nodes),
            "dig": [n for n in nodes if n not in occupied and not roads[n] and not water[n]],
        })
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "name": src.stem, "width": width, "height": height, "seed": int(m.get("cliffRandomSeed", 0)),
        "areas": areas, "catalog": {"artifacts": artifacts, "units": units},
    }), encoding="utf-8")
    print(f"{src.stem}: {width}x{height}, {len(areas)} areas, {len(artifacts)} artifacts, {len(units)} units")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
