#!/usr/bin/env python3
"""Crop single_layer 80x80 Homecoming into a standalone exact-72 minimap probe.

Read-only input: generated h3_roe_castle_homecoming_single_layer.map.
Does not mutate that artifact, does not call single_layer emit, and does not
wire boat-travel / water-bridge profile resolvers.

Proof boundary after this script: generated artifact only. Installed/runtime
minimap bounds remain unproven until the probe is loaded and SID-tagged logs
are observed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc

MAP_SID = "h3_roe_castle_homecoming_exact72_probe"
SOURCE_MAP_SID = "h3_roe_castle_homecoming_single_layer"
TITLE = "Homecoming Exact72 Minimap Probe"
POLICY_ID = "crop_80_envelope_to_exact72_offset_4_4_mapview_ceil_5x5"

INPUT_WIDTH = 80
INPUT_HEIGHT = 80
CROP_OFFSET_X = 4
CROP_OFFSET_Y = 4
OUT_WIDTH = 72
OUT_HEIGHT = 72
VIEW_SECTOR_SIZE = 16
MAP_VIEW_SEC_SIZE = (OUT_WIDTH + VIEW_SECTOR_SIZE - 1) // VIEW_SECTOR_SIZE  # 5 overhang
ENVELOPE_PADDING_BLOCKER_SID = "homm3_envelope_padding_blocker"

SCHEMA = "homm3.olden_exact72_probe_map.v1"
DEFAULT_INPUT_MAP = (
    Path(poc.ROOT)
    / "artifacts"
    / "campaign_port_poc"
    / "homecoming_poc"
    / "single_layer_map"
    / "maps"
    / f"{SOURCE_MAP_SID}.map"
)
DEFAULT_OUT_ROOT = (
    Path(poc.ROOT) / "artifacts" / "campaign_port_poc" / "homecoming_poc" / "exact72_probe_map"
)

ARRAY_KEYS = (
    "tilesMap",
    "roadsMap",
    "waterMap",
    "levelsMap",
    "climbsMap",
    "customAreasPainting",
)


def fail(message: str) -> None:
    raise SystemExit(f"exact72 probe build failed: {message}")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def crop_array(values: list[Any], *, width: int, height: int, ox: int, oy: int, out_w: int, out_h: int) -> list[Any]:
    if len(values) != width * height:
        fail(f"array length {len(values)} != {width}x{height}")
    out: list[Any] = []
    for y in range(oy, oy + out_h):
        row_start = y * width + ox
        out.extend(values[row_start : row_start + out_w])
    if len(out) != out_w * out_h:
        fail(f"cropped array length {len(out)} != {out_w}x{out_h}")
    return out


def remap_node(node: int) -> int | None:
    x = node % INPUT_WIDTH
    y = node // INPUT_WIDTH
    nx = x - CROP_OFFSET_X
    ny = y - CROP_OFFSET_Y
    if not (0 <= nx < OUT_WIDTH and 0 <= ny < OUT_HEIGHT):
        return None
    return ny * OUT_WIDTH + nx


def assert_no_envelope_blockers(objects: list[dict[str, Any]]) -> None:
    blockers = [g for g in objects if isinstance(g, dict) and g.get("sid") == ENVELOPE_PADDING_BLOCKER_SID]
    if blockers:
        fail(
            f"input contains {len(blockers)} {ENVELOPE_PADDING_BLOCKER_SID!r} group(s); "
            "exact72 probe requires single_layer-style envelope (array padding only)"
        )


def crop_object_group(group: dict[str, Any]) -> dict[str, Any] | None:
    nodes = group.get("nodes")
    if not isinstance(nodes, list):
        fail(f"object group {group.get('sid')!r} missing nodes list")
    kept_indices: list[int] = []
    new_nodes: list[int] = []
    for index, node in enumerate(nodes):
        if not isinstance(node, int):
            fail(f"object group {group.get('sid')!r} has non-integer node {node!r}")
        remapped = remap_node(node)
        if remapped is None:
            continue
        kept_indices.append(index)
        new_nodes.append(remapped)
    if not new_nodes:
        return None

    out = dict(group)
    out["nodes"] = new_nodes
    for parallel_key in ("ids", "levels", "rotations"):
        values = group.get(parallel_key)
        if values is None:
            continue
        if not isinstance(values, list):
            fail(f"object group {group.get('sid')!r} {parallel_key} must be a list")
        if len(values) != len(nodes):
            fail(
                f"object group {group.get('sid')!r} {parallel_key} length {len(values)} "
                f"!= nodes length {len(nodes)}"
            )
        out[parallel_key] = [values[i] for i in kept_indices]
    return out


def crop_map_data(map_data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    size_x = map_data.get("sizeX_")
    size_z = map_data.get("sizeZ_")
    if size_x != INPUT_WIDTH or size_z != INPUT_HEIGHT:
        fail(f"input MapData must be {INPUT_WIDTH}x{INPUT_HEIGHT}, found {size_x}x{size_z}")

    objects = map_data.get("objects")
    if not isinstance(objects, list):
        fail("input MapData.objects must be a list")
    assert_no_envelope_blockers(objects)

    out = dict(map_data)
    out["sizeX_"] = OUT_WIDTH
    out["sizeZ_"] = OUT_HEIGHT
    for key in ARRAY_KEYS:
        values = map_data.get(key)
        if not isinstance(values, list):
            fail(f"input MapData.{key} must be a list")
        out[key] = crop_array(
            values,
            width=INPUT_WIDTH,
            height=INPUT_HEIGHT,
            ox=CROP_OFFSET_X,
            oy=CROP_OFFSET_Y,
            out_w=OUT_WIDTH,
            out_h=OUT_HEIGHT,
        )

    cropped_objects: list[dict[str, Any]] = []
    dropped_node_refs = 0
    dropped_empty_groups = 0
    for group in objects:
        if not isinstance(group, dict):
            fail("object group must be an object")
        before = len(group.get("nodes") or [])
        cropped = crop_object_group(group)
        if cropped is None:
            dropped_empty_groups += 1
            dropped_node_refs += before
            continue
        dropped_node_refs += before - len(cropped["nodes"])
        cropped_objects.append(cropped)
    out["objects"] = cropped_objects

    out["views"] = [
        {
            "name": "surface",
            "minSecX": 0,
            "minSecZ": 0,
            "secSizeX": MAP_VIEW_SEC_SIZE,
            "secSizeZ": MAP_VIEW_SEC_SIZE,
            "isUnderground": False,
            "stack": -1,
        }
    ]
    out["areas"] = [{"id": 0, "nodes": list(range(OUT_WIDTH * OUT_HEIGHT))}]

    evidence = {
        "policyId": POLICY_ID,
        "inputSize": {"width": INPUT_WIDTH, "height": INPUT_HEIGHT},
        "cropOffset": {"x": CROP_OFFSET_X, "y": CROP_OFFSET_Y},
        "outputSize": {"width": OUT_WIDTH, "height": OUT_HEIGHT},
        "mapView": out["views"][0],
        "mapViewSectorPixels": MAP_VIEW_SEC_SIZE * VIEW_SECTOR_SIZE,
        "mapViewOverhangTiles": (MAP_VIEW_SEC_SIZE * VIEW_SECTOR_SIZE) - OUT_WIDTH,
        "objectGroupCountIn": len(objects),
        "objectGroupCountOut": len(cropped_objects),
        "droppedEmptyGroups": dropped_empty_groups,
        "droppedPaddingNodeRefs": dropped_node_refs,
        "envelopeBlockersPresent": False,
    }
    return out, evidence


def crop_meta(meta: dict[str, Any], map_hash: str) -> dict[str, Any]:
    out = dict(meta)
    out["title"] = TITLE
    out["nameFromLocalization"] = False
    out["descFromLocalization"] = False
    out["sizeX"] = OUT_WIDTH
    out["sizeZ"] = OUT_HEIGHT
    out["hashSum"] = map_hash
    return out


def build(input_map: Path, out_root: Path) -> dict[str, Any]:
    if not input_map.is_file():
        fail(
            f"missing input map {input_map}. Regenerate {SOURCE_MAP_SID} separately first; "
            "exact72 probe does not auto-emit single_layer."
        )
    input_script = input_map.with_suffix(".json")
    if not input_script.is_file():
        fail(f"missing companion script {input_script}")

    container = poc.read_olden_map_container(input_map)
    if len(container.chunks) < 2:
        fail("input map has too few chunks")

    map_hash = hashlib.md5(MAP_SID.encode("utf-8")).hexdigest()
    meta = crop_meta(container.chunks[0], map_hash)
    map_data, crop_evidence = crop_map_data(container.chunks[1])
    chunks = [meta, map_data, *container.chunks[2:]]

    maps_dir = out_root / "maps"
    maps_dir.mkdir(parents=True, exist_ok=True)
    out_map = maps_dir / f"{MAP_SID}.map"
    out_script = maps_dir / f"{MAP_SID}.json"
    poc.write_olden_map_container(
        out_map,
        poc.OldenMapContainer(version=container.version, prefix_suffix=container.prefix_suffix, chunks=chunks),
        map_hash,
    )
    shutil.copy2(input_script, out_script)

    manifest = {
        "schema": SCHEMA,
        "mapSid": MAP_SID,
        "sourceMapSid": SOURCE_MAP_SID,
        "title": TITLE,
        "policyId": POLICY_ID,
        "proofBoundary": "generated_artifact_only_until_installed_and_runtime_bounds_logs",
        "homecomingMapProfileRegistered": False,
        "installLane": "maps_root_custom_only",
        "inputMap": str(input_map),
        "outputMap": str(out_map),
        "outputScript": str(out_script),
        "mapHash": map_hash,
        "crop": crop_evidence,
        "knownGaps": [
            "Runtime minimap RectInt vs sizeX_/sizeZ_ overhang is unproven until SID-tagged bounds probe logs are observed.",
            "Production 80x80 Homecoming lanes are intentionally unchanged.",
        ],
    }
    write_json(out_root / "install_manifest.json", manifest)
    write_json(out_root / "EXACT72_PROBE_REPORT.json", manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-map", type=Path, default=DEFAULT_INPUT_MAP)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    args = parser.parse_args(argv)
    manifest = build(args.input_map.resolve(), args.out_root.resolve())
    print(json.dumps({"status": "ok", "mapSid": manifest["mapSid"], "policyId": POLICY_ID}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
