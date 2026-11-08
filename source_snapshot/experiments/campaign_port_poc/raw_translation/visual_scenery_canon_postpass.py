#!/usr/bin/env python3
"""Separate raw_translation visual postpass: canon terrain + scenery variety.

Dangerous on purpose — keep this module self-contained. Existing emit / substitution
/ gate / landon modules must not absorb this logic.

Terrain: native-first HoMM3→OE remap (Sand/Swamp/Lava/Rough) from H3 source tiles.
Scenery: fingerprint-verified same-OCC diversify, plus careful solid-OCC mountain
merges that never expand onto open cells.

Disable: env RAW_TRANSLATION_SKIP_VISUAL_SCENERY_POSTPASS=1 or skip_flag=True.
Reverse: restore the pre-postpass .map backup written beside the live map.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

_PKG = Path(__file__).resolve().parent
_POC = _PKG.parent
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

import campaign_ocean  # noqa: E402
import functional_emit_reservation as fer  # noqa: E402
import port_homecoming_poc as poc  # noqa: E402

SCHEMA = "homm3.raw_translation.visual_scenery_canon_postpass.v1"
STATUS_APPLIED = "applied"
STATUS_SKIPPED = "skipped_by_flag"
STATUS_REVERTED = "reverted"
PROOF_BOUNDARY = "generated_artifact_runtime_unvalidated"
SKIP_ENV = "RAW_TRANSLATION_SKIP_VISUAL_SCENERY_POSTPASS"
BACKUP_SUFFIX = ".pre_visual_scenery_postpass.map"

# Generator lossy projection (surface_emit.H3_SURFACE_TO_OLDEN_TILE) — do not import
# that table; keep the dangerous remapper isolated and explicit.
LOSSY_H3_TO_OLDEN: dict[int, int] = {
    0: 7,   # Dirt → Dirt
    1: 7,   # Sand → Dirt (lossy)
    2: 1,   # Grass → Grass
    3: 4,   # Snow → Snow
    4: 1,   # Swamp → Grass (lossy)
    5: 1,   # Rough → Grass (lossy)
    6: 15,  # Subterranean → Burrow
    7: 7,   # Lava → Dirt (lossy)
    8: 2,   # Water → ocean basin seabed (untouched by remap; campaign_ocean)
    9: 23,  # Rock → Void (untouched by remap)
}

# Native-first canon targets for the lossy rows; identity elsewhere.
CANON_H3_TO_OLDEN: dict[int, int] = {
    0: 7,   # Dirt
    1: 2,   # Sand (native)
    2: 1,   # Grass
    3: 4,   # Snow
    4: 8,   # Swamp (custom Core row)
    5: 7,   # Rough → Dirt (no perfect Rough tile)
    6: 15,  # Burrow
    7: 6,   # Lava (native)
    8: 2,   # Ocean basin seabed — never rewritten here
    9: 23,  # Void — never rewritten here
}

# H3 ids whose generator projection differs from canon (actual remaps).
REMAP_H3_IDS: frozenset[int] = frozenset(
    h3 for h3, canon in CANON_H3_TO_OLDEN.items() if LOSSY_H3_TO_OLDEN.get(h3) != canon
)

VOID_TILE_ID = 23

# Declared visual families for 1x1 diversify. Membership is filtered by exact
# ObjectConfig fingerprint before use — names alone never authorize a swap.
DIVERSIFY_FAMILY_PREFIXES: tuple[str, ...] = (
    "mountain_dirt_small_",
    "mountain_green_small_",
    "mountain_snow_small_",
    "mountain_dead_small_",
    "mountain_lava_small_",
    "mountain_water_small_",
    "mountain_desert_",
    "pinetree_",
    "pinetree_snow_",
    "tree_dead_",
    "tree_dirt_",
    "tree_lava_",
    "grass_",
    "grass_stones_",
    "dirt_stones_",
    "snow_stones_",
    "mushrooms_",
    "flowers_",
)

# Mountain 1x1 family key → solid merge candidate SIDs by side length.
# Candidates are still fingerprint-verified (must be fully solid side×side OCC).
MOUNTAIN_MERGE_FAMILIES: dict[str, dict[int, tuple[str, ...]]] = {
    "mountain_dirt_small": {
        2: ("mountain_dirt_big_1", "mountain_dirt_big_2"),
        3: ("mountain_dirt_big_3", "mountain_dirt_big_4"),
    },
    "mountain_green_small": {
        2: ("mountain_green_big_1", "mountain_green_big_2"),
        3: ("mountain_green_big_3", "mountain_green_big_4"),
    },
    "mountain_snow_small": {
        2: ("mountain_snow_big_1", "mountain_snow_big_2"),
        3: ("mountain_snow_big_3", "mountain_snow_big_4"),
    },
    "mountain_dead_small": {
        2: ("mountain_dead_big_1", "mountain_dead_big_2"),
        3: ("mountain_dead_big_3", "mountain_dead_big_4"),
    },
    "mountain_lava_small": {
        2: ("mountain_lava_big_1", "mountain_lava_big_2"),
        3: ("mountain_lava_big_3", "mountain_lava_big_4"),
    },
    "mountain_water_small": {
        2: ("mountain_water_big_1", "mountain_water_big_2", "mountain_water_big_3"),
    },
    "mountain_desert": {
        2: ("mountain_desert_3", "mountain_desert_4"),
        3: ("mountain_desert_5", "mountain_desert_6"),
    },
}

# Deterministic fraction of eligible solid squares that become merges (0-100).
MERGE_PERCENT = 35
MERGE_SIDES: tuple[int, ...] = (2, 3)  # prefer 2x2 first (processed in this order)


def skip_requested(*, skip_flag: bool = False) -> bool:
    if skip_flag:
        return True
    raw = (os.environ.get(SKIP_ENV) or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def backup_map_path(live_map_path: Path) -> Path:
    return live_map_path.with_name(live_map_path.stem + BACKUP_SUFFIX)


def config_fingerprint(config: dict[str, Any] | None) -> tuple[int, int, tuple[int, ...]] | None:
    if not isinstance(config, dict):
        return None
    size_x = config.get("sizeX")
    size_z = config.get("sizeZ")
    nodes = config.get("nodes")
    if (
        not isinstance(size_x, int)
        or not isinstance(size_z, int)
        or size_x <= 0
        or size_z <= 0
        or not isinstance(nodes, list)
        or len(nodes) != size_x * size_z
        or not all(isinstance(v, int) for v in nodes)
    ):
        return None
    return (size_x, size_z, tuple(int(v) for v in nodes))


def is_fully_solid_square(config: dict[str, Any] | None) -> bool:
    fp = config_fingerprint(config)
    if fp is None:
        return False
    size_x, size_z, nodes = fp
    if size_x != size_z or size_x not in {1, 2, 3}:
        return False
    return all(v == 1 for v in nodes)


def occupied_nodes_for_anchor(
    *,
    size_x: int,
    size_z: int,
    nodes: tuple[int, ...],
    anchor_node: int,
    width: int,
    height: int,
    rotation: int = 0,
    can_be_mirrored: bool = False,
) -> set[int] | None:
    """Map ObjectConfig OCC (nodes==1) to atlas cells. SW-at-anchor, Z→map-south.

    Mirrors surface_emit.occupied_nodes_for_object_instance placement math.
    Returns None if any OCC cell falls outside the atlas (fail closed).
    """
    mirrored = rotation == 2 and can_be_mirrored
    anchor_x = anchor_node % width
    anchor_y = anchor_node // width
    occupied: set[int] = set()
    for config_z in range(size_z):
        for config_x in range(size_x):
            value = nodes[config_z * size_x + config_x]
            if value != 1:
                continue
            placed_dx = size_x - 1 - config_x if mirrored else config_x
            grid_x = anchor_x + placed_dx
            grid_y = anchor_y + (size_z - 1 - config_z)
            if not (0 <= grid_x < width and 0 <= grid_y < height):
                return None
            occupied.add(grid_y * width + grid_x)
    return occupied


def diversify_family_key(sid: str) -> str | None:
    for prefix in DIVERSIFY_FAMILY_PREFIXES:
        if sid.startswith(prefix):
            # Keep desert mountains under mountain_desert_ (small+big share prefix).
            if prefix == "mountain_desert_":
                # Only 1x1 desert smalls: mountain_desert_1 / _2 (not _3.._6 bigs).
                suffix = sid[len(prefix) :]
                if suffix in {"1", "2"}:
                    return "mountain_desert_small"
                return None
            if prefix == "pinetree_":
                if sid.startswith("pinetree_snow_"):
                    continue
                return "pinetree"
            if prefix == "grass_":
                if sid.startswith("grass_stones_") or sid.startswith("grass_snow_"):
                    continue
                return "grass"
            return prefix.rstrip("_")
    return None


def mountain_merge_family_key(sid: str) -> str | None:
    for key in MOUNTAIN_MERGE_FAMILIES:
        if sid.startswith(key + "_") or (key == "mountain_desert" and sid in {"mountain_desert_1", "mountain_desert_2"}):
            if key == "mountain_desert":
                return key if sid in {"mountain_desert_1", "mountain_desert_2"} else None
            if "big" in sid:
                return None
            return key
    return None


def is_eligible_scenery_sid(sid: str) -> bool:
    if sid in fer.SUPPRESSIBLE_SOURCE_SCENERY_SIDS:
        return True
    # Exact-footprint same-size scenery clones.
    if sid.startswith("homm3_xfp_s_"):
        return True
    return False


def _stable_pick(seed: str, choices: list[str]) -> str:
    if not choices:
        raise ValueError("empty choices")
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return choices[int(digest[:12], 16) % len(choices)]


def _merge_gate(seed: str, percent: int = MERGE_PERCENT) -> bool:
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return (int(digest[:8], 16) % 100) < percent


def remap_terrain_from_h3_source(
    *,
    tiles_map: list[int],
    water_map: list[int],
    layered_map_data: list[dict[str, Any]],
    layer_target_node,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Rewrite lossy land tiles to native-first canon using H3 source terrain."""
    remapped = 0
    already_canon = 0
    mismatched = 0
    skipped_water_void = 0
    water_channel_updates = 0
    by_h3: Counter[int] = Counter()
    mismatch_examples: list[dict[str, Any]] = []

    for entry in layered_map_data:
        if not isinstance(entry, dict):
            continue
        layer = entry.get("layer")
        map_data = entry.get("mapData") or {}
        source_tiles = map_data.get("tilesMap")
        if not isinstance(layer, int) or not isinstance(source_tiles, list):
            continue
        # Infer source dimensions from layer layout via first/last successful target.
        # Source maps are square SOURCE_WIDTH×SOURCE_HEIGHT for campaign atlases;
        # derive from len(source_tiles) when square.
        cell_count = len(source_tiles)
        side = int(cell_count**0.5)
        if side * side != cell_count:
            raise ValueError(
                f"layeredMapData layer {layer}: tilesMap length {cell_count} is not square"
            )
        source_width = side
        source_height = side
        for source_y in range(source_height):
            for source_x in range(source_width):
                h3_tile = int(source_tiles[source_y * source_width + source_x])
                if h3_tile not in REMAP_H3_IDS:
                    continue
                try:
                    node = int(layer_target_node(layer, source_x, source_y))
                except Exception:
                    mismatched += 1
                    if len(mismatch_examples) < 12:
                        mismatch_examples.append(
                            {
                                "layer": layer,
                                "source": [source_x, source_y],
                                "reason": "layer_target_node_failed",
                                "h3": h3_tile,
                            }
                        )
                    continue
                if node < 0 or node >= len(tiles_map):
                    mismatched += 1
                    continue
                current = int(tiles_map[node])
                if current == VOID_TILE_ID:
                    skipped_water_void += 1
                    continue
                if node < len(water_map) and campaign_ocean.is_emitter_ocean_pair(current, water_map[node]):
                    skipped_water_void += 1
                    continue
                lossy = LOSSY_H3_TO_OLDEN[h3_tile]
                canon = CANON_H3_TO_OLDEN[h3_tile]
                if current == canon:
                    already_canon += 1
                    continue
                if current != lossy:
                    mismatched += 1
                    if len(mismatch_examples) < 12:
                        mismatch_examples.append(
                            {
                                "layer": layer,
                                "source": [source_x, source_y],
                                "node": node,
                                "h3": h3_tile,
                                "current": current,
                                "expectedLossy": lossy,
                                "canon": canon,
                                "reason": "current_tile_not_lossy_projection",
                            }
                        )
                    continue
                tiles_map[node] = canon
                remapped += 1
                by_h3[h3_tile] += 1
                # River channel overlays store the land biome tile id in waterMap.
                if node < len(water_map) and int(water_map[node] or 0) == lossy:
                    water_map[node] = canon
                    water_channel_updates += 1

    return {
        "remappedCellCount": remapped,
        "alreadyCanonCellCount": already_canon,
        "mismatchedCellCount": mismatched,
        "skippedWaterVoidCellCount": skipped_water_void,
        "waterChannelUpdateCount": water_channel_updates,
        "remappedByH3Terrain": {str(k): v for k, v in sorted(by_h3.items())},
        "mismatchExamples": mismatch_examples,
        "table": {
            "lossy": {str(k): v for k, v in sorted(LOSSY_H3_TO_OLDEN.items())},
            "canon": {str(k): v for k, v in sorted(CANON_H3_TO_OLDEN.items())},
            "remapH3Ids": sorted(REMAP_H3_IDS),
        },
    }


def _iter_instances(
    objects: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group in objects:
        if not isinstance(group, dict):
            continue
        sid = group.get("sid")
        if not isinstance(sid, str):
            continue
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        levels = group.get("levels") or []
        if not (len(ids) == len(nodes) == len(rotations) == len(levels)):
            raise ValueError(f"malformed object group for sid={sid!r}")
        for index, object_id in enumerate(ids):
            rows.append(
                {
                    "sid": sid,
                    "objectId": int(object_id),
                    "node": int(nodes[index]),
                    "rotation": int(rotations[index]),
                    "level": levels[index],
                    "group": group,
                    "index": index,
                }
            )
    return rows


def _move_instance_sid(
    objects: list[dict[str, Any]],
    *,
    object_id: int,
    new_sid: str,
) -> None:
    for group in list(objects):
        ids = group.get("ids") or []
        if object_id not in ids:
            continue
        index = ids.index(object_id)
        member = {
            key: [value[index]]
            for key, value in group.items()
            if key != "sid" and isinstance(value, list) and index < len(value)
        }
        for key, value in list(group.items()):
            if key != "sid" and isinstance(value, list) and index < len(value):
                del value[index]
        if not group.get("ids"):
            objects.remove(group)
        target = next((row for row in objects if row.get("sid") == new_sid), None)
        if target is None:
            target = {"sid": new_sid}
            objects.append(target)
        for key, values in member.items():
            target.setdefault(key, []).extend(values)
        return
    raise ValueError(f"object id {object_id} not found for SID move to {new_sid!r}")


def diversify_scenery_variants(
    objects: list[dict[str, Any]],
    *,
    native_object_configs: dict[str, dict[str, Any]],
    map_sid: str,
) -> dict[str, Any]:
    """Swap eligible scenery SIDs within exact ObjectConfig fingerprint pools."""
    # Precompute fingerprint → family → SIDs present in Core configs.
    fingerprint_family_pool: dict[
        tuple[tuple[int, int, tuple[int, ...]], str], list[str]
    ] = defaultdict(list)
    for sid, config in native_object_configs.items():
        if not is_eligible_scenery_sid(sid):
            continue
        family = diversify_family_key(sid)
        if family is None:
            continue
        fp = config_fingerprint(config)
        if fp is None or fp[0] != 1 or fp[1] != 1 or fp[2] != (1,):
            # Diversify pass is 1x1 solid only (trees/mountains/grass).
            continue
        fingerprint_family_pool[(fp, family)].append(sid)
    for key in fingerprint_family_pool:
        fingerprint_family_pool[key] = sorted(set(fingerprint_family_pool[key]))

    changed = 0
    considered = 0
    skipped_no_pool = 0
    by_family: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    changed_ids: list[int] = []

    for row in _iter_instances(objects):
        sid = row["sid"]
        if not is_eligible_scenery_sid(sid):
            continue
        family = diversify_family_key(sid)
        if family is None:
            continue
        config = native_object_configs.get(sid)
        fp = config_fingerprint(config)
        if fp is None or fp[0] != 1 or fp[1] != 1 or fp[2] != (1,):
            continue
        pool = fingerprint_family_pool.get((fp, family)) or []
        # Only keep pool members that still match this exact fingerprint.
        pool = [
            candidate
            for candidate in pool
            if config_fingerprint(native_object_configs.get(candidate)) == fp
        ]
        if len(pool) < 2:
            skipped_no_pool += 1
            continue
        considered += 1
        pick = _stable_pick(
            f"{map_sid}|diversify|{family}|{row['objectId']}|{row['node']}",
            pool,
        )
        if pick == sid:
            continue
        _move_instance_sid(objects, object_id=row["objectId"], new_sid=pick)
        changed += 1
        changed_ids.append(int(row["objectId"]))
        by_family[family] += 1
        if len(examples) < 24:
            examples.append(
                {
                    "objectId": row["objectId"],
                    "node": row["node"],
                    "fromSid": sid,
                    "toSid": pick,
                    "family": family,
                    "fingerprint": {
                        "sizeX": fp[0],
                        "sizeZ": fp[1],
                        "nodes": list(fp[2]),
                    },
                }
            )

    return {
        "consideredCount": considered,
        "changedCount": changed,
        "skippedNoPoolCount": skipped_no_pool,
        "changedByFamily": dict(by_family),
        "changedObjectIds": sorted(changed_ids),
        "examples": examples,
    }


def merge_mountain_clusters(
    objects: list[dict[str, Any]],
    *,
    native_object_configs: dict[str, dict[str, Any]],
    map_sid: str,
    width: int,
    height: int,
) -> dict[str, Any]:
    """Replace solid 2x2/3x3 clusters of same-family 1x1 mountains with one big SID.

    OCC of the big SID must be fully solid and already covered exclusively by those
    1x1 instances. Never expands onto open / functional cells.
    """
    # Build exclusive 1x1 mountain ownership: node -> instance row.
    owners: dict[int, dict[str, Any]] = {}
    multi_owned: set[int] = set()
    for row in _iter_instances(objects):
        sid = row["sid"]
        if not is_eligible_scenery_sid(sid):
            continue
        family = mountain_merge_family_key(sid)
        if family is None:
            continue
        config = native_object_configs.get(sid)
        if not is_fully_solid_square(config):
            continue
        fp = config_fingerprint(config)
        if fp is None or fp[0] != 1:
            continue
        node = row["node"]
        if node in owners:
            multi_owned.add(node)
            owners.pop(node, None)
            continue
        if node in multi_owned:
            continue
        row = dict(row)
        row["family"] = family
        owners[node] = row

    # Pre-validate merge target SIDs: fingerprint must be solid side×side.
    verified_targets: dict[str, dict[int, list[str]]] = {}
    for family, by_side in MOUNTAIN_MERGE_FAMILIES.items():
        verified_targets[family] = {}
        for side, candidates in by_side.items():
            ok: list[str] = []
            for sid in candidates:
                config = native_object_configs.get(sid)
                fp = config_fingerprint(config)
                if fp is None or fp[0] != side or fp[1] != side:
                    continue
                if not all(v == 1 for v in fp[2]):
                    continue
                ok.append(sid)
            if ok:
                verified_targets[family][side] = ok

    merged = 0
    eligible_clusters = 0
    skipped_gate = 0
    skipped_overlap = 0
    skipped_no_target = 0
    consumed: set[int] = set()
    examples: list[dict[str, Any]] = []
    by_family_side: Counter[str] = Counter()

    # Prefer 2x2 over 3x3: iterate sides in MERGE_SIDES order, scan atlas once each.
    for side in MERGE_SIDES:
        for y in range(0, height - side + 1):
            for x in range(0, width - side + 1):
                cells = [
                    (y + dy) * width + (x + dx)
                    for dy in range(side)
                    for dx in range(side)
                ]
                if any(cell in consumed or cell in multi_owned for cell in cells):
                    continue
                rows = [owners.get(cell) for cell in cells]
                if any(row is None for row in rows):
                    continue
                families = {row["family"] for row in rows}  # type: ignore[index]
                if len(families) != 1:
                    continue
                family = next(iter(families))
                targets = (verified_targets.get(family) or {}).get(side) or []
                if not targets:
                    skipped_no_target += 1
                    continue
                # Exclusive ownership: each cell's instance must occupy exactly that cell.
                # (Already true for verified 1x1 solid.)
                eligible_clusters += 1
                seed = f"{map_sid}|merge|{family}|{side}|{x}|{y}"
                if not _merge_gate(seed):
                    skipped_gate += 1
                    continue
                # Anchor = SW corner = (x, y) under OE south-at-anchor (min map y).
                anchor_node = y * width + x
                pick = _stable_pick(seed + "|sid", targets)
                pick_fp = config_fingerprint(native_object_configs.get(pick))
                if pick_fp is None:
                    skipped_no_target += 1
                    continue
                occ = occupied_nodes_for_anchor(
                    size_x=pick_fp[0],
                    size_z=pick_fp[1],
                    nodes=pick_fp[2],
                    anchor_node=anchor_node,
                    width=width,
                    height=height,
                    rotation=0,
                    can_be_mirrored=False,
                )
                if occ is None or occ != set(cells):
                    # Fail closed: big SID OCC must equal the square we intend to cover.
                    skipped_overlap += 1
                    continue
                # Remove covering 1x1s; reuse the lowest object id for the big instance.
                remove_ids = {int(row["objectId"]) for row in rows}  # type: ignore[index]
                keep_id = min(remove_ids)
                level = rows[0]["level"]  # type: ignore[index]
                from layered_objects import remove_object_ids_from_groups

                remove_object_ids_from_groups(objects, remove_ids)
                # Append big mountain.
                target = next((g for g in objects if g.get("sid") == pick), None)
                if target is None:
                    target = {
                        "sid": pick,
                        "ids": [],
                        "nodes": [],
                        "rotations": [],
                        "levels": [],
                    }
                    objects.append(target)
                target.setdefault("ids", []).append(keep_id)
                target.setdefault("nodes", []).append(anchor_node)
                target.setdefault("rotations", []).append(0)
                target.setdefault("levels", []).append(level)
                consumed.update(cells)
                for cell in cells:
                    owners.pop(cell, None)
                merged += 1
                by_family_side[f"{family}:{side}x{side}"] += 1
                if len(examples) < 32:
                    examples.append(
                        {
                            "family": family,
                            "side": side,
                            "anchorNode": anchor_node,
                            "anchorXY": [x, y],
                            "replacementSid": pick,
                            "removedObjectIds": sorted(remove_ids),
                            "keptObjectId": keep_id,
                            "occupiedNodes": sorted(occ),
                        }
                    )

    return {
        "eligibleClusterCount": eligible_clusters,
        "mergedCount": merged,
        "skippedHashGateCount": skipped_gate,
        "skippedNoTargetCount": skipped_no_target,
        "skippedOccMismatchCount": skipped_overlap,
        "multiOwnedCellCount": len(multi_owned),
        "mergedByFamilySide": dict(by_family_side),
        "mergePercent": MERGE_PERCENT,
        "examples": examples,
        "meshOverhangResidualRisk": (
            "ObjectConfig OCC is verified solid and pre-covered; multi-tile mountain "
            "meshes may still overhang OCC visually. Runtime unvalidated; reverse via backup."
        ),
    }


def apply_visual_scenery_canon_postpass(
    *,
    tiles_map: list[int],
    water_map: list[int],
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    layered_map_data: list[dict[str, Any]],
    layer_target_node,
    map_sid: str,
    width: int,
    height: int,
    preserve_source_ids: bool = False,
    skip_flag: bool = False,
) -> dict[str, Any]:
    """Mutate tiles/water/objects in place. Returns manifest-ready report.

    ``preserve_source_ids`` (raw_translation): every object id is a HoMM3 source index that
    placement ground truth and properties key on, so the mountain merge (which deletes 1x1
    instances and keeps one id) is skipped; SID diversify keeps ids and is still applied.
    """
    if skip_requested(skip_flag=skip_flag):
        return {
            "schema": SCHEMA,
            "status": STATUS_SKIPPED,
            "proofBoundary": PROOF_BOUNDARY,
            "policy": "native_first_terrain_plus_fingerprint_scenery_variety",
            "skipEnv": SKIP_ENV,
        }

    terrain = remap_terrain_from_h3_source(
        tiles_map=tiles_map,
        water_map=water_map,
        layered_map_data=layered_map_data,
        layer_target_node=layer_target_node,
        width=width,
        height=height,
    )
    diversify = diversify_scenery_variants(
        objects,
        native_object_configs=native_object_configs,
        map_sid=map_sid,
    )
    if preserve_source_ids:
        merge = {
            "status": "skipped_source_parity",
            "policy": "raw_translation_preserve_source_object_ids",
            "proofBoundary": PROOF_BOUNDARY,
            "mergedCount": 0,
        }
    else:
        merge = merge_mountain_clusters(
            objects,
            native_object_configs=native_object_configs,
            map_sid=map_sid,
            width=width,
            height=height,
        )
    return {
        "schema": SCHEMA,
        "status": STATUS_APPLIED,
        "proofBoundary": PROOF_BOUNDARY,
        "policy": "native_first_terrain_plus_fingerprint_scenery_variety",
        "skipEnv": SKIP_ENV,
        "terrainRemap": terrain,
        "sceneryDiversify": diversify,
        "mountainMerge": merge,
    }


def write_pre_postpass_backup(
    *,
    live_map_path: Path,
    container: poc.OldenMapContainer,
    hash_sum: str,
) -> Path:
    """Write full Olden map container backup beside the live map."""
    path = backup_map_path(live_map_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    poc.write_olden_map_container(path, container, hash_sum)
    return path


def restore_from_backup(
    *,
    live_map_path: Path,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    backup = backup_map_path(live_map_path)
    if not backup.is_file():
        raise FileNotFoundError(f"missing visual scenery postpass backup: {backup}")
    shutil.copy2(backup, live_map_path)
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": STATUS_REVERTED,
        "liveMap": str(live_map_path),
        "backupMap": str(backup),
        "proofBoundary": PROOF_BOUNDARY,
    }
    if manifest_path is not None and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
        post = manifest.setdefault("postPasses", {})
        visual = post.get("visualSceneryCanon")
        if isinstance(visual, dict):
            visual = dict(visual)
            visual["status"] = STATUS_REVERTED
            post["visualSceneryCanon"] = visual
        else:
            post["visualSceneryCanon"] = {
                "schema": SCHEMA,
                "status": STATUS_REVERTED,
                "proofBoundary": PROOF_BOUNDARY,
                "backupMap": str(backup.as_posix()),
            }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        report["manifest"] = str(manifest_path)
    return report


def snapshot_pre_postpass_state(
    *,
    tiles_map: list[int],
    water_map: list[int],
    objects: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deep copy arrays/objects for assembling a pre-pass map backup at write time."""
    return {
        "tilesMap": list(tiles_map),
        "waterMap": list(water_map),
        "objects": copy.deepcopy(objects),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    restore = sub.add_parser("restore", help="Copy pre-postpass backup over the live .map")
    restore.add_argument("--map", type=Path, required=True, help="Live .map path")
    restore.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional install_manifest.json to mark status=reverted",
    )
    args = parser.parse_args()
    if args.command == "restore":
        report = restore_from_backup(live_map_path=args.map, manifest_path=args.manifest)
        print(json.dumps(report, indent=2))
        return 0
    raise SystemExit(f"unknown command {args.command!r}")


if __name__ == "__main__":
    raise SystemExit(main())
