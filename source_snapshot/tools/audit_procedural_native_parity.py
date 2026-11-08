#!/usr/bin/env python3
"""Read-only structural audit for procedural maps versus native maps.

This intentionally stays below gameplay proof.  It measures the serialized
surface that the loader receives: occupancy, terrain, elevation, native
property families, spawn/city/guard counts, and the typed quest graph.  It is
useful for catching a map that passes schema validation but is visibly much
sparser or mechanically thinner than the maps it is intended to resemble.

Example::

    python tools/audit_procedural_native_parity.py \
      --generated build/parity_after_all/maps/proc_exploration_1_6a55c06f.map \
      --reference "<Golden Era>\\HeroesOldenEra_Data\\StreamingAssets\\maps\\Gorges_of_Discord.map" \
      --reference "<Golden Era>\\HeroesOldenEra_Data\\StreamingAssets\\maps\\Thirst_for_Power.map" \
      --output build/procedural_native_parity.json
"""

from __future__ import annotations

import argparse
import collections
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
POC_ROOT = REPO_ROOT / "experiments" / "campaign_port_poc"
if str(POC_ROOT) not in sys.path:
    sys.path.insert(0, str(POC_ROOT))

from procedural_scenarios.emitter import parse_container_bytes  # noqa: E402


PROCEDURAL_HELPER_SIDS = frozenset(
    {
        'fx_map_object_blocked',
        'fx_map_smoke',
        'homm3_envelope_padding_blocker',
        'homm3_landon_map_event_marker',
        'homm3_pathing_blocker',
    }
)


def _count_event_graph(value: Any) -> dict[str, Any]:
    actions: collections.Counter[str] = collections.Counter()
    conditions: collections.Counter[str] = collections.Counter()
    counts = {"topQuests": 0, "subQuests": 0, "triggers": 0}

    def visit(node: Any, depth: int = 0) -> None:
        if isinstance(node, Mapping):
            triggers = node.get("triggers")
            if isinstance(triggers, list):
                counts["triggers"] += len(triggers)
                for trigger in triggers:
                    if not isinstance(trigger, Mapping):
                        continue
                    for action in trigger.get("actions", ()):
                        if isinstance(action, Mapping):
                            actions[str(action.get("a", action.get("action", "?")))] += 1
                    for condition in trigger.get("conditions", ()):
                        if isinstance(condition, Mapping):
                            conditions[str(condition.get("c", condition.get("type", "?")))] += 1
            sub_quests = node.get("subQuests")
            if isinstance(sub_quests, list):
                if depth == 0:
                    counts["topQuests"] += 1
                counts["subQuests"] += len(sub_quests)
            for child in node.values():
                visit(child, depth + 1)
        elif isinstance(node, list):
            for child in node:
                visit(child, depth)

    visit(value)
    return {
        **counts,
        "actions": dict(sorted(actions.items())),
        "conditions": dict(sorted(conditions.items())),
    }


def _stats(path: Path) -> dict[str, Any]:
    container = parse_container_bytes(path.read_bytes())
    if len(container.chunks) < 4:
        raise ValueError(f"{path} does not contain the native four-chunk map envelope")
    header, surface, _dialogs, events = container.chunks[:4]
    width = int(surface.get("sizeX_", header.get("sizeX", 0)))
    height = int(surface.get("sizeZ_", header.get("sizeZ", 0)))
    total = width * height
    objects = surface.get("objects")
    if not isinstance(objects, list):
        raise ValueError(f"{path} has no object groups")
    object_instances = sum(len(row.get("ids", ())) for row in objects if isinstance(row, Mapping))
    object_nodes = {
        int(node)
        for row in objects
        if isinstance(row, Mapping)
        for node in row.get("nodes", ())
        if isinstance(node, int)
    }
    properties = surface.get("objectsProperties", {})
    if not isinstance(properties, Mapping):
        properties = {}
    property_counts = {
        str(key): len(value) if isinstance(value, list) else 0
        for key, value in properties.items()
    }
    sid_counts: collections.Counter[str] = collections.Counter()
    sid_by_id: dict[int, str] = {}
    for row in objects:
        if not isinstance(row, Mapping):
            continue
        sid = str(row.get("sid", ""))
        ids = row.get("ids", ())
        for object_id in ids:
            sid_counts[sid] += 1
            if isinstance(object_id, int):
                sid_by_id[object_id] = sid
    def prop_objects(key: str, *, sid: str | None = None) -> int:
        rows = properties.get(key, ())
        if not isinstance(rows, list):
            return 0
        if sid is None:
            return len(rows)
        return sum(1 for row in rows if isinstance(row, Mapping) and sid_by_id.get(row.get("id")) == sid)

    tiles = surface.get("tilesMap", ())
    levels = surface.get("levelsMap", ())
    climbs = surface.get("climbsMap", ())
    roads = surface.get("roadsMap", ())
    water = surface.get("waterMap", ())
    painting = surface.get("customAreasPainting", ())
    levels_count = collections.Counter(int(value) for value in levels)
    tiles_count = collections.Counter(int(value) for value in tiles)
    area_rows = surface.get("areas", ())
    area_sizes = [len(row.get("nodes", ())) for row in area_rows if isinstance(row, Mapping)]
    event_stats = _count_event_graph(events.get("quests", ()) if isinstance(events, Mapping) else ())
    return {
        "path": str(path.resolve()),
        "mapSid": str(surface.get("fileMapName", path.stem)),
        "size": [width, height],
        "objectGroups": len(objects),
        "objectInstances": object_instances,
        "uniqueObjectNodes": len(object_nodes),
        "uniqueObjectNodeFraction": round(len(object_nodes) / total, 6) if total else 0.0,
        "objectInstancesPer100Tiles": round(object_instances / total * 100.0, 4) if total else 0.0,
        "terrain": {
            "tileIds": dict(sorted(tiles_count.items())),
            "levelValues": dict(sorted(levels_count.items())),
            "nonZeroLevelFraction": round(sum(1 for value in levels if value) / total, 6) if total else 0.0,
            "climbCells": sum(1 for value in climbs if value),
            "roadCells": sum(1 for value in roads if value),
            "waterCells": sum(1 for value in water if value),
            "paintedAreaValues": sorted({int(value) for value in painting}),
        },
        "areas": {
            "count": len(area_rows) if isinstance(area_rows, list) else 0,
            "nodeCounts": area_sizes,
            "areasVersion": surface.get("areasVersion"),
        },
        "nativeProperties": {
            "families": property_counts,
            "spawns": prop_objects("propSpawns"),
            "cities": prop_objects("propCities"),
            "neutralCities": prop_objects("propOwners"),
            "heroes": prop_objects("propHeroes"),
            "randomSquads": prop_objects("propRandomSquads"),
            "exactSquads": prop_objects("propSquads"),
            "resources": prop_objects("propResParams"),
            "rewards": prop_objects("propRewardParams"),
            "activations": prop_objects("propActivations"),
            "entities": prop_objects("propEntities"),
        },
        "objectSidCounts": dict(sid_counts.most_common(25)),
        "proceduralHelperObjectInstances": sum(
            sid_counts[sid] for sid in PROCEDURAL_HELPER_SIDS
        ),
        "headerSpawns": len((header.get("spawns") or {}).get("spawns", ()))
        if isinstance(header.get("spawns"), Mapping)
        else 0,
        "events": {
            "counters": len(events.get("counters", ())) if isinstance(events, Mapping) else 0,
            **event_stats,
        },
    }


def _envelope(rows: Iterable[Mapping[str, Any]], key: str) -> dict[str, float] | None:
    values = [float(row[key]) for row in rows if isinstance(row.get(key), (int, float))]
    if not values:
        return None
    return {
        "min": min(values),
        "median": statistics.median(values),
        "max": max(values),
    }


def build_report(generated: list[Path], references: list[Path]) -> dict[str, Any]:
    generated_rows = [_stats(path) for path in generated]
    reference_rows = [_stats(path) for path in references]
    metrics = (
        "uniqueObjectNodeFraction",
        "objectInstancesPer100Tiles",
    )
    reference_envelope = {
        metric: _envelope(reference_rows, metric) for metric in metrics
    }
    terrain_metrics = (
        "nonZeroLevelFraction",
        "climbCells",
        "roadCells",
        "waterCells",
    )
    reference_terrain_envelope = {
        metric: _envelope(
            [row["terrain"] for row in reference_rows], metric
        )
        for metric in terrain_metrics
    }
    return {
        "schema": "homm3.procedural_native_parity_report.v1",
        "generated": generated_rows,
        "references": reference_rows,
        "referenceEnvelope": reference_envelope,
        "referenceTerrainEnvelope": reference_terrain_envelope,
        "proofBoundary": (
            "serialized source comparison only; this does not prove loader startup, "
            "runtime interaction, or user-visible gameplay"
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--generated", action="append", type=Path, required=True)
    parser.add_argument("--reference", action="append", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_report(args.generated, args.reference)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
