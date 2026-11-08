#!/usr/bin/env python3
"""Validate the Homecoming authentic Terraneus-layer slice contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED_SCRIPT_TOKENS = [
    "TARGET_LAYER = 1",
    "TERRANEUS_KEY = \"1:35:35\"",
    "SURFACE_GUARDHOUSE_EVENT_KEY = \"0:18:35\"",
    "REQUIRED_CAVE_EDGE_COORDS = {(14, 41), (49, 3)}",
    "emitsOldenMap\": False",
    "unproven_olden_terrain_value_semantics_and_missing_two_layer_runtime",
    "blocked_requires_per_object_id_policy",
    "emit_required_objective_proxy_pending_olden_mapping",
    "preserve_as_blocked_layer_travel_requirement",
    "silentFallbacksUsed",
]

EXPECTED_DISPOSITIONS = {
    "blocked_requires_per_object_id_policy": 390,
    "defer_pending_explicit_olden_object_mapping": 7,
    "emit_required_objective_proxy_pending_olden_mapping": 1,
    "preserve_as_blocked_layer_travel_requirement": 2,
}


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_json(path: Path, errors: list[str]) -> dict:
    if not path.exists():
        errors.append(f"missing JSON artifact: {path}")
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception as ex:
        errors.append(f"could not read JSON artifact {path}: {ex}")
        return {}


def validate_builder_source(repo_root: Path, errors: list[str]) -> None:
    builder = repo_root / "experiments" / "campaign_port_poc" / "build_homecoming_authentic_slice_ir.py"
    require(builder.exists(), f"missing Homecoming authentic slice builder: {builder}", errors)
    if not builder.exists():
        return
    source = builder.read_text(encoding="utf-8-sig")
    for token in REQUIRED_SCRIPT_TOKENS:
        require(token in source, f"Homecoming authentic slice builder missing contract token: {token}", errors)
    forbidden = [
        "write_olden_map_container(",
        "generate_playable_shell(",
        "TERRANEUS_KEY = \"0:",
        "silentFallbacksUsed\": True",
    ]
    for token in forbidden:
        require(token not in source, f"Homecoming authentic slice builder contains forbidden token: {token}", errors)


def validate_artifacts(repo_root: Path, errors: list[str]) -> None:
    root = repo_root / "artifacts" / "campaign_port_poc" / "homecoming_poc" / "layered_ir"
    slice_ir = read_json(root / "homecoming.authentic_terraneus_layer_slice_ir.json", errors)
    validation = read_json(root / "homecoming.authentic_terraneus_layer_slice_validation_report.json", errors)
    layered_ir = read_json(root / "homecoming.layered_map_ir.json", errors)
    manifest = read_json(root / "homecoming.object_port_manifest.json", errors)
    if not slice_ir or not validation:
        return

    require(validation.get("result") == "PASS", f"authentic slice validation result must be PASS, found {validation.get('result')}", errors)
    checked = validation.get("checkedInvariants") or {}
    require(checked.get("terrainTiles") == 72 * 72, f"authentic slice must preserve 5184 terrain tiles, found {checked.get('terrainTiles')}", errors)
    require(checked.get("targetLayerObjects") == 400, f"authentic slice must account for 400 underground objects, found {checked.get('targetLayerObjects')}", errors)
    require(checked.get("manifestLayerObjects") == 400, f"authentic slice manifest layer object count must be 400, found {checked.get('manifestLayerObjects')}", errors)
    require(checked.get("dispositions") == EXPECTED_DISPOSITIONS, f"authentic slice dispositions changed: {checked.get('dispositions')}", errors)
    require(checked.get("caveEdges") == 2, f"authentic slice must preserve 2 cave edges, found {checked.get('caveEdges')}", errors)
    require(checked.get("unresolvedWhirlpools") == 2, f"authentic slice must preserve 2 unresolved whirlpools, found {checked.get('unresolvedWhirlpools')}", errors)

    require(slice_ir.get("schema") == "homm3.homecoming_authentic_terraneus_layer_slice.v0", "authentic slice schema changed", errors)
    require(slice_ir.get("emitsOldenMap") is False, "authentic slice must not claim to emit an Olden map", errors)
    require(slice_ir.get("silentFallbacksUsed") is False, "authentic slice must report silentFallbacksUsed=false", errors)
    require(slice_ir.get("notPlayableReason") == "unproven_olden_terrain_value_semantics_and_missing_two_layer_runtime", "authentic slice notPlayableReason changed", errors)

    terrain = slice_ir.get("terrain") or {}
    require(terrain.get("index") == 1 and terrain.get("sid") == "underground" and terrain.get("isUnderground") is True, "authentic slice terrain must target underground layer 1", errors)
    require(terrain.get("width") == 72 and terrain.get("height") == 72 and len(terrain.get("tiles") or []) == 5184, "authentic slice terrain dimensions changed", errors)
    require(terrain.get("terrainHistogram") == {"6": 1216, "9": 3968}, f"underground terrain histogram changed: {terrain.get('terrainHistogram')}", errors)

    objects = slice_ir.get("objects") or []
    require(len(objects) == 400, f"authentic slice object list length must be 400, found {len(objects)}", errors)
    source_indices = [item.get("sourceIndex") for item in objects if isinstance(item, dict)]
    require(len(set(source_indices)) == 400, f"authentic slice must preserve 400 unique underground sourceIndex values, found {len(set(source_indices))}", errors)
    if manifest:
        expected_indices = {row.get("sourceIndex") for row in manifest.get("records", []) if isinstance(row, dict) and str(row.get("sourceKey", "")).startswith("1:")}
        require(set(source_indices) == expected_indices, "authentic slice sourceIndex coverage must exactly match layer-1 object manifest records", errors)
    keys = {item.get("sourceKey") for item in objects if isinstance(item, dict)}
    require("1:35:35" in keys, "authentic slice missing Terraneus source key", errors)
    terraneus = [item for item in objects if item.get("sourceKey") == "1:35:35"]
    require(len(terraneus) == 1, f"authentic slice expected one Terraneus object, found {len(terraneus)}", errors)
    if terraneus:
        target = terraneus[0]
        require(target.get("name") == "Terraneus", "Terraneus name changed", errors)
        require(target.get("templateObjectId") == 98, "Terraneus object id changed", errors)
        require(target.get("authenticSliceDisposition") == "emit_required_objective_proxy_pending_olden_mapping", "Terraneus disposition changed", errors)

    travel = slice_ir.get("travelRequirements") or {}
    edge_pairs = {(edge.get("surface"), edge.get("underground"), edge.get("x"), edge.get("y")) for edge in travel.get("caveEdges") or []}
    require(edge_pairs == {("0:14:41", "1:14:41", 14, 41), ("0:49:3", "1:49:3", 49, 3)}, f"authentic slice cave edges changed: {edge_pairs}", errors)
    require(travel.get("unresolvedWhirlpools") == ["0:21:62", "0:58:67"], f"authentic slice unresolved whirlpools changed: {travel.get('unresolvedWhirlpools')}", errors)

    excluded = slice_ir.get("excludedBySingleLayerScope") or {}
    require(excluded.get("surfaceEventKeys") == ["0:18:35"], f"authentic slice must explicitly exclude the surface Guardhouse event, found {excluded.get('surfaceEventKeys')}", errors)

    pointer = ((layered_ir.get("objectInstances") or {}).get("authenticTerraneusLayerSlice") or {}) if layered_ir else {}
    require(pointer.get("validationResult") == "PASS", "layered IR missing PASS pointer to authentic Terraneus layer slice", errors)
    require(pointer.get("emitsOldenMap") is False, "layered IR pointer must preserve emitsOldenMap=false", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=Path(__file__).resolve().parents[1], type=Path)
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    errors: list[str] = []
    validate_builder_source(repo_root, errors)
    validate_artifacts(repo_root, errors)
    if errors:
        print("Homecoming authentic Terraneus-layer slice validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("Homecoming authentic Terraneus-layer slice validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
