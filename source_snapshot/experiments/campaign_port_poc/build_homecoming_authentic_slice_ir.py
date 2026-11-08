#!/usr/bin/env python3
"""Build an authentic Terraneus-layer Homecoming slice IR.

This is stricter than the earlier reduced slice: it preserves the complete H3M
underground terrain layer and accounts for every decoded object on that layer.
It intentionally does not emit an Olden .map because Olden terrain value
semantics and true two-layer loading are not yet proven.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc

OUT_ROOT = poc.OUT_ROOT / "layered_ir"
LAYERED_IR_PATH = OUT_ROOT / "homecoming.layered_map_ir.json"
MANIFEST_PATH = OUT_ROOT / "homecoming.object_port_manifest.json"
SLICE_PATH = OUT_ROOT / "homecoming.authentic_terraneus_layer_slice_ir.json"
VALIDATION_PATH = OUT_ROOT / "homecoming.authentic_terraneus_layer_slice_validation_report.json"
REPORT_PATH = OUT_ROOT / "AUTHENTIC_TERRANEUS_LAYER_SLICE_REPORT.md"

TARGET_LAYER = 1
TARGET_LAYER_SID = "underground"
TERRANEUS_KEY = "1:35:35"
SURFACE_GUARDHOUSE_EVENT_KEY = "0:18:35"
REQUIRED_CAVE_EDGE_COORDS = {(14, 41), (49, 3)}

PORTABLE_CATEGORIES = {
    "town",
    "map_event",
    "travel_link_candidate",
    "readable_sign_or_bottle",
    "monster_stack",
    "artifact_pickup",
    "resource_pickup",
    "mine",
    "interactive_reward_object",
    "boat_or_water_travel_object",
    "hero_or_prison",
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_key(key: str) -> tuple[int, int, int]:
    layer, x, y = key.split(":")
    return int(layer), int(x), int(y)


def load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    if not LAYERED_IR_PATH.exists():
        raise FileNotFoundError(f"missing layered IR: {LAYERED_IR_PATH}")
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"missing object manifest: {MANIFEST_PATH}")
    layered_ir = json.loads(LAYERED_IR_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    if (manifest.get("validation") or {}).get("result") != "PASS":
        raise ValueError("object manifest must pass before authentic slice generation")
    if layered_ir.get("silentFallbacksUsed") is not False:
        raise ValueError("layered IR reports silentFallbacksUsed != false")
    return layered_ir, manifest


def classify_disposition(record: dict[str, Any]) -> str:
    category = record.get("category")
    if record.get("sourceKey") == TERRANEUS_KEY:
        return "emit_required_objective_proxy_pending_olden_mapping"
    if category == "travel_link_candidate":
        return "preserve_as_blocked_layer_travel_requirement"
    if category in PORTABLE_CATEGORIES:
        return "defer_pending_explicit_olden_object_mapping"
    if category == "payloadless_object_unclassified_for_current_scope":
        return "blocked_requires_per_object_id_policy"
    raise ValueError(f"unknown object category for authentic slice: {category!r}")


def layer_records(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in manifest["records"]:
        layer, x, y = parse_key(record["sourceKey"])
        if layer != TARGET_LAYER:
            continue
        projected = dict(record)
        projected["position"] = {"layer": layer, "x": x, "y": y}
        projected["authenticSliceDisposition"] = classify_disposition(record)
        records.append(projected)
    return sorted(records, key=lambda item: item["sourceIndex"])


def build_travel_requirements(manifest: dict[str, Any]) -> dict[str, Any]:
    caves: dict[tuple[int, int], dict[int, str]] = {}
    whirlpools: list[str] = []
    for record in manifest["records"]:
        oid = record.get("templateObjectId")
        layer, x, y = parse_key(record["sourceKey"])
        if oid == 103:
            caves.setdefault((x, y), {})[layer] = record["sourceKey"]
        elif oid == 111:
            whirlpools.append(record["sourceKey"])
    cave_edges = []
    unresolved_caves = []
    for (x, y), by_layer in sorted(caves.items()):
        if set(by_layer) == {0, 1}:
            cave_edges.append({
                "kind": "subterranean_gate_pair_by_exact_xy",
                "x": x,
                "y": y,
                "surface": by_layer[0],
                "underground": by_layer[1],
                "bidirectional": True,
                "authenticSliceStatus": "blocked_until_two_layer_runtime_or_explicit_travel_substitution",
            })
        else:
            unresolved_caves.append({"x": x, "y": y, "sourceKeys": sorted(by_layer.values())})
    return {
        "caveEdges": cave_edges,
        "unresolvedCaves": unresolved_caves,
        "unresolvedWhirlpools": sorted(whirlpools),
    }


def validate_slice(slice_ir: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    terrain = slice_ir["terrain"]
    objects = slice_ir["objects"]
    expected_layer_records = [record for record in manifest["records"] if parse_key(record["sourceKey"])[0] == TARGET_LAYER]
    if terrain.get("index") != TARGET_LAYER or terrain.get("sid") != TARGET_LAYER_SID:
        errors.append("terrain target layer metadata does not match the Terraneus underground layer")
    if terrain.get("width") != 72 or terrain.get("height") != 72 or len(terrain.get("tiles", [])) != 72 * 72:
        errors.append("terrain slice must preserve exactly one complete 72x72 H3M layer")
    if len(objects) != len(expected_layer_records):
        errors.append(f"object count {len(objects)} does not match layer-{TARGET_LAYER} manifest count {len(expected_layer_records)}")
    object_indices = {item["sourceIndex"] for item in objects}
    expected_indices = {item["sourceIndex"] for item in expected_layer_records}
    if object_indices != expected_indices:
        missing = sorted(expected_indices - object_indices)[:10]
        extra = sorted(object_indices - expected_indices)[:10]
        errors.append(f"layer object sourceIndex coverage mismatch; missing={missing} extra={extra}")
    terraneus = [item for item in objects if item.get("sourceKey") == TERRANEUS_KEY]
    if len(terraneus) != 1:
        errors.append(f"expected exactly one Terraneus object in authentic slice, found {len(terraneus)}")
    else:
        target = terraneus[0]
        if target.get("name") != "Terraneus" or target.get("templateObjectId") != 98:
            errors.append("Terraneus object identity does not match decoded H3M town record")
        if target.get("authenticSliceDisposition") != "emit_required_objective_proxy_pending_olden_mapping":
            errors.append("Terraneus object disposition must remain explicitly required for objective emission")
    dispositions = Counter(item.get("authenticSliceDisposition") for item in objects)
    if dispositions.get("blocked_requires_per_object_id_policy", 0) == 0:
        warnings.append("no payloadless blocked records were present on the target layer; recheck source if this changes")
    cave_edge_coords = {(edge["x"], edge["y"]) for edge in slice_ir["travelRequirements"]["caveEdges"]}
    if cave_edge_coords != REQUIRED_CAVE_EDGE_COORDS:
        errors.append(f"cave edge coords {sorted(cave_edge_coords)} do not match required {sorted(REQUIRED_CAVE_EDGE_COORDS)}")
    if SURFACE_GUARDHOUSE_EVENT_KEY not in slice_ir["excludedBySingleLayerScope"]["surfaceEventKeys"]:
        errors.append("single-layer scope must explicitly exclude the surface Guardhouse event")
    if slice_ir.get("emitsOldenMap") is not False:
        errors.append("authentic slice IR must not claim to emit an Olden map")
    if slice_ir.get("silentFallbacksUsed") is not False:
        errors.append("silentFallbacksUsed must be false")
    return {
        "schema": "homm3.homecoming_authentic_terraneus_layer_slice.validation.v0",
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "checkedInvariants": {
            "terrainTiles": len(terrain.get("tiles", [])),
            "targetLayerObjects": len(objects),
            "manifestLayerObjects": len(expected_layer_records),
            "dispositions": dict(sorted(dispositions.items())),
            "caveEdges": len(slice_ir["travelRequirements"]["caveEdges"]),
            "unresolvedWhirlpools": len(slice_ir["travelRequirements"]["unresolvedWhirlpools"]),
        },
    }


def update_layered_ir(layered_ir: dict[str, Any], validation: dict[str, Any]) -> None:
    layered_ir.setdefault("objectInstances", {})["authenticTerraneusLayerSlice"] = {
        "artifact": str(SLICE_PATH),
        "validationArtifact": str(VALIDATION_PATH),
        "validationResult": validation["result"],
        "targetLayer": TARGET_LAYER,
        "emitsOldenMap": False,
        "primaryBlockingFeature": "unproven_olden_terrain_value_semantics_and_missing_two_layer_runtime",
    }
    write_json(LAYERED_IR_PATH, layered_ir)


def write_report(slice_ir: dict[str, Any], validation: dict[str, Any]) -> None:
    lines = [
        "# Homecoming Authentic Terraneus-Layer Slice IR",
        "",
        f"Validation: {validation['result']}",
        f"Target layer: {TARGET_LAYER} ({TARGET_LAYER_SID})",
        f"Terrain tiles preserved: {validation['checkedInvariants']['terrainTiles']}",
        f"Layer objects accounted: {validation['checkedInvariants']['targetLayerObjects']}",
        "",
        "## What This Proves",
        "",
        "- The full H3M underground terrain layer is preserved as source data.",
        "- Every decoded underground object record is accounted for exactly once.",
        "- Terraneus remains pinned to the decoded underground town at `1:35:35`.",
        "- Cave pairs preserve exact same-x/y surface-to-underground requirements.",
        "",
        "## Why This Is Not Yet An Olden Map",
        "",
        "- Olden terrain array value semantics are not proven enough to write H3 terrain values into `tilesMap`.",
        "- The surface Guardhouse event is outside this single-layer slice and requires two-layer scope or an explicit substitution.",
        "- Caves and whirlpools require layer-aware travel behavior or a validated replacement design.",
        "- Most objects still need explicit Olden object SID mappings before emission.",
        "",
        "## Object Dispositions",
        "",
    ]
    for key, count in validation["checkedInvariants"]["dispositions"].items():
        lines.append(f"- `{key}`: {count}")
    lines.extend(["", "## Required Objective", ""])
    for item in slice_ir["objects"]:
        if item["sourceKey"] == TERRANEUS_KEY:
            lines.append(f"- `{item['sourceKey']}` {item.get('name')} objectId={item.get('templateObjectId')} disposition={item.get('authenticSliceDisposition')}")
    lines.extend(["", "## Travel Requirements", ""])
    for edge in slice_ir["travelRequirements"]["caveEdges"]:
        lines.append(f"- `{edge['surface']}` <-> `{edge['underground']}` exact cave x/y ({edge['x']}, {edge['y']})")
    lines.extend(["", "## Validation Gaps", ""])
    if validation["warnings"]:
        lines.extend(f"- warning: {warning}" for warning in validation["warnings"])
    if validation["errors"]:
        lines.extend(f"- error: {error}" for error in validation["errors"])
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    layered_ir, manifest = load_inputs()
    target_layers = [layer for layer in layered_ir["layers"] if layer.get("index") == TARGET_LAYER]
    if len(target_layers) != 1:
        raise ValueError(f"expected exactly one layer {TARGET_LAYER}, found {len(target_layers)}")
    terrain_layer = target_layers[0]
    objects = layer_records(manifest)
    slice_ir = {
        "schema": "homm3.homecoming_authentic_terraneus_layer_slice.v0",
        "source": layered_ir["source"],
        "mission": layered_ir["mission"],
        "target": {
            "kind": "single_h3m_layer_authentic_slice",
            "layer": TARGET_LAYER,
            "sid": TARGET_LAYER_SID,
            "reason": "Terraneus, the victory target, is on the underground layer.",
        },
        "terrain": terrain_layer,
        "objects": objects,
        "travelRequirements": build_travel_requirements(manifest),
        "excludedBySingleLayerScope": {
            "surfaceEventKeys": [SURFACE_GUARDHOUSE_EVENT_KEY],
            "reason": "The decoded Guardhouse/Pikemen map event is on layer 0 and cannot be faithfully included in a layer-1-only map without two-layer support or explicit relocation/substitution.",
        },
        "emitsOldenMap": False,
        "notPlayableReason": "unproven_olden_terrain_value_semantics_and_missing_two_layer_runtime",
        "silentFallbacksUsed": False,
    }
    validation = validate_slice(slice_ir, manifest)
    slice_ir["validation"] = validation
    write_json(SLICE_PATH, slice_ir)
    write_json(VALIDATION_PATH, validation)
    update_layered_ir(layered_ir, validation)
    write_report(slice_ir, validation)
    print(
        f"validation={validation['result']} terrainTiles={validation['checkedInvariants']['terrainTiles']} "
        f"objects={validation['checkedInvariants']['targetLayerObjects']} caveEdges={validation['checkedInvariants']['caveEdges']}"
    )
    return 0 if validation["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
