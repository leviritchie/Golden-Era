#!/usr/bin/env python3
"""Neutral helpers for translating layered HoMM3 scenarios into Olden maps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import h3m_object_registry as h3obj


OLDEN_VIEW_SECTION_SIZE = 16
Y_AXIS_FLIP = "h3m_top_left_to_olden_bottom_left"
SUBTERRANEAN_GATE_PAIRING_POLICY = "nearest_corresponding_cross_layer_gate_pairing_mutual_required"
SUBTERRANEAN_GATE_PAIRING_SOURCE = "HoMM3 subterranean-gate nearest corresponding cross-layer rule"
SUBTERRANEAN_GATE_TIE_BREAK = "distance_then_northmost_then_westmost"
WHIRLPOOL_PAIRING_POLICY = (
    "same_layer_mutual_nearest_when_even_else_global_circular_chain"
)
WHIRLPOOL_PAIRING_SOURCE = (
    "HoMM3 whirlpools form one map network; Olden propPortals only carry a single "
    "targetIdx so even same-layer groups stay mutual-nearest pairs and odd/cross-layer "
    "groups become a deterministic circular chain"
)
WHIRLPOOL_TIE_BREAK = "distance_then_northmost_then_westmost"
MONOLITH_TWO_WAY_PAIRING_POLICY = "cross_layer_same_animation_mutual_pair_or_circular_chain"
MONOLITH_TWO_WAY_PAIRING_SOURCE = "HoMM3 two-way monolith same-animation pairing across map levels"
MONOLITH_TWO_WAY_TIE_BREAK = "lowest_object_id_first"
MONOLITH_TWO_WAY_CROSS_LAYER_POLICY = "same_subtype_cross_layer_mutual_pair_or_circular_chain"
MONOLITH_TWO_WAY_CROSS_LAYER_SOURCE = "HoMM3 two-way monolith subtype network across map levels"

H3_UNDERGROUND_SUBTERRANEAN_TERRAIN_ID = 6
H3_UNDERGROUND_ROCK_TERRAIN_ID = 9
OLDEN_BURROW_TILE_ID = 15
OLDEN_VOID_TILE_ID = 23
UNDERGROUND_ROCK_LEVEL = 1
UNDERGROUND_ROCK_CLIMB = 0
UNDERGROUND_ROCK_PROJECTION_POLICY = "homm3_rock_as_elevated_black_no_ramp_surface"

# Native open-ocean / water-tile basin geometry matches shipped Olden maps such as
# water_example.map and Glittering_Strait.map: depressed water cells use levelsMap -1,
# with climbsMap ramp bytes on perimeter water tiles (generous 8-neighbor land contact).
NATIVE_OCEAN_BASIN_LEVEL = -1
NATIVE_OCEAN_BASIN_INTERIOR_CLIMB = 0
NATIVE_OCEAN_BASIN_PERIMETER_CLIMB = 1
NATIVE_OCEAN_BASIN_GEOMETRY_POLICY = "depressed_levels_map_minus_one_with_generous_perimeter_climbs_map_ramps"

# Olden stock/GE maps only evidence roadsMap codes 1 and 2. H3 also uses code 3
# (cobblestone). Map it lossily to Olden 2 rather than inventing an unevidenced
# Olden code 3 or silently dropping the road.
H3_SURFACE_ROAD_TO_OLDEN_ROAD = {
    1: 1,
    2: 2,
    3: 2,
}
ROAD_PROJECTION_POLICY = (
    "native_roads_map_direct_code_1_to_1_2_to_2_h3_3_to_olden_2_lossy_fail_closed_otherwise"
)


class ScenarioTranslationError(ValueError):
    """Raised when a neutral scenario translation contract cannot be satisfied."""


class ScenarioTravelPairingError(ScenarioTranslationError):
    """Raised when layer-qualified travel objects cannot be paired safely."""


@dataclass(frozen=True)
class LayerAtlasLayout:
    source_width: int
    source_height: int
    layer_width: int
    layer_height: int
    atlas_width: int
    atlas_height: int
    source_offset_x: int
    source_offset_y: int
    sector_size: int
    layers: dict[int, dict[str, Any]]

    def target_node(self, layer: int, source_x: int, source_y: int) -> int:
        if layer not in self.layers:
            raise ScenarioTranslationError(f"unsupported source layer: {layer}")
        if not (0 <= source_x < self.source_width and 0 <= source_y < self.source_height):
            raise ScenarioTranslationError(f"source coordinate outside emitted envelope: layer={layer} {source_x},{source_y}")
        spec = self.layers[layer]
        return (self.source_height - 1 - source_y + spec["offsetY"]) * self.atlas_width + source_x + spec["offsetX"]

    def node_xy(self, node: int) -> dict[str, int]:
        if not (0 <= node < self.atlas_width * self.atlas_height):
            raise ScenarioTranslationError(f"node outside atlas bounds: {node}")
        return {"x": node % self.atlas_width, "y": node // self.atlas_width}

    def as_manifest(self) -> dict[str, Any]:
        return {
            "sourceWidth": self.source_width,
            "sourceHeight": self.source_height,
            "layerWidth": self.layer_width,
            "layerHeight": self.layer_height,
            "atlasWidth": self.atlas_width,
            "atlasHeight": self.atlas_height,
            "sourceOffsetX": self.source_offset_x,
            "sourceOffsetY": self.source_offset_y,
            "sectorSize": self.sector_size,
            "yAxisTransform": Y_AXIS_FLIP,
            "layers": self.layers,
        }


def align_to_sector(size: int, sector_size: int = OLDEN_VIEW_SECTION_SIZE) -> int:
    if not isinstance(size, int) or size <= 0:
        raise ScenarioTranslationError(f"size must be a positive integer: {size!r}")
    if not isinstance(sector_size, int) or sector_size <= 0:
        raise ScenarioTranslationError(f"sector size must be a positive integer: {sector_size!r}")
    return ((size + sector_size - 1) // sector_size) * sector_size


def project_h3_road_code(layer: int, h3_road_code: int) -> int:
    """Project H3 road codes onto Olden roadsMap values evidenced in stock maps.

    Side-by-side atlases place underground on the same Olden plane, so non-surface
    H3 roads use the same code map as surface roads.
    """
    if not isinstance(layer, int):
        raise ScenarioTranslationError(f"road layer must be an integer: {layer!r}")
    if not isinstance(h3_road_code, int) or not 0 <= h3_road_code <= 7:
        raise ScenarioTranslationError(f"H3 road code must be an integer in 0..7: {h3_road_code!r}")
    if h3_road_code == 0:
        return 0
    try:
        return H3_SURFACE_ROAD_TO_OLDEN_ROAD[h3_road_code]
    except KeyError as ex:
        raise ScenarioTranslationError(
            f"unsupported H3 road code {h3_road_code} on layer {layer}; "
            "add evidence and an explicit mapping"
        ) from ex


def build_side_by_side_layer_atlas(
    *,
    source_width: int,
    source_height: int,
    layer_ids: Iterable[int],
    sector_size: int = OLDEN_VIEW_SECTION_SIZE,
    view_names: dict[int, str] | None = None,
    underground_layers: set[int] | None = None,
) -> LayerAtlasLayout:
    ordered_layers = list(layer_ids)
    if not ordered_layers:
        raise ScenarioTranslationError("at least one source layer is required")
    if len(set(ordered_layers)) != len(ordered_layers):
        raise ScenarioTranslationError(f"source layer list contains duplicates: {ordered_layers}")
    if any(not isinstance(layer, int) for layer in ordered_layers):
        raise ScenarioTranslationError(f"source layer ids must be integers: {ordered_layers}")

    layer_width = align_to_sector(source_width, sector_size)
    layer_height = align_to_sector(source_height, sector_size)
    source_offset_x = (layer_width - source_width) // 2
    source_offset_y = (layer_height - source_height) // 2
    if source_offset_x < 0 or source_offset_y < 0:
        raise ScenarioTranslationError("aligned layer envelope is smaller than the source map")

    view_names = view_names or {}
    if underground_layers is None:
        underground_layers = {layer for layer in ordered_layers if layer != 0}
    else:
        unknown_underground_layers = sorted(set(underground_layers) - set(ordered_layers))
        if unknown_underground_layers:
            raise ScenarioTranslationError(f"underground layer ids are not in source layers: {unknown_underground_layers}")
    layers: dict[int, dict[str, Any]] = {}
    sec_size_x = layer_width // sector_size
    sec_size_z = layer_height // sector_size
    for atlas_index, layer in enumerate(ordered_layers):
        layer_origin_x = atlas_index * layer_width
        name = view_names.get(layer) or ("surface" if layer == 0 else f"layer_{layer}")
        layers[layer] = {
            "sid": name,
            "offsetX": layer_origin_x + source_offset_x,
            "offsetY": source_offset_y,
            "layerOriginX": layer_origin_x,
            "layerOriginY": 0,
            "view": {
                "name": name,
                "minSecX": layer_origin_x // sector_size,
                "minSecZ": 0,
                "secSizeX": sec_size_x,
                "secSizeZ": sec_size_z,
                "isUnderground": layer in underground_layers,
                "stack": -1,
            },
        }

    return LayerAtlasLayout(
        source_width=source_width,
        source_height=source_height,
        layer_width=layer_width,
        layer_height=layer_height,
        atlas_width=layer_width * len(ordered_layers),
        atlas_height=layer_height,
        source_offset_x=source_offset_x,
        source_offset_y=source_offset_y,
        sector_size=sector_size,
        layers=layers,
    )


def _required_int(entity: dict[str, Any], key: str) -> int:
    value = entity.get(key)
    if not isinstance(value, int):
        raise ScenarioTravelPairingError(f"travel entity missing integer {key}: {entity}")
    return value


def _first_int(entity: dict[str, Any], primary: str, fallback: str) -> int:
    if isinstance(entity.get(primary), int):
        return int(entity[primary])
    return _required_int(entity, fallback)


def _source_key(entity: dict[str, Any]) -> str:
    value = entity.get("sourceKey") or entity.get("key")
    if isinstance(value, str):
        return value
    layer = entity.get("sourceLayer", entity.get("layer"))
    x = entity.get("sourceX", entity.get("x"))
    y = entity.get("sourceY", entity.get("y"))
    return f"{layer}:{x}:{y}"


def _candidate_record(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "objectId": _first_int(entity, "sourceIndex", "index"),
        "sourceKey": _source_key(entity),
        "sourceLayer": _first_int(entity, "sourceLayer", "layer"),
        "sourceX": _first_int(entity, "sourceX", "x"),
        "sourceY": _first_int(entity, "sourceY", "y"),
        "templateObjectId": _required_int(entity, "templateObjectId"),
        "templateSubtype": entity.get("templateSubtype"),
        "templateAnimation": entity.get("templateAnimation"),
        "category": entity.get("category"),
        "payloadKind": entity.get("payloadKind"),
    }


def _pair_sort_key(source: dict[str, Any], target: dict[str, Any]) -> tuple[int, int, int, int]:
    dx = int(source["sourceX"]) - int(target["sourceX"])
    dy = int(source["sourceY"]) - int(target["sourceY"])
    return (dx * dx + dy * dy, int(target["sourceY"]), int(target["sourceX"]), int(target["objectId"]))


def _nearest_candidate(source: dict[str, Any], targets: list[dict[str, Any]]) -> tuple[dict[str, Any], tuple[int, int, int, int]]:
    if not targets:
        raise ScenarioTravelPairingError(f"no opposite-layer candidate for gate {source['sourceKey']}")
    ordered = sorted(targets, key=lambda target: _pair_sort_key(source, target))
    return ordered[0], _pair_sort_key(source, ordered[0])


def pair_subterranean_gates_by_nearest_cross_layer_rule(entities: Iterable[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        _candidate_record(entity)
        for entity in entities
        if entity.get("templateObjectId") == h3obj.OBJECT_SUBTERRANEAN_GATE
    ]
    if not candidates:
        return {
            "status": "generated_static_contract_runtime_unvalidated",
            "objectId": h3obj.OBJECT_SUBTERRANEAN_GATE,
            "objectName": "subterranean_gate",
            "source": SUBTERRANEAN_GATE_PAIRING_SOURCE,
            "policy": SUBTERRANEAN_GATE_PAIRING_POLICY,
            "tieBreak": SUBTERRANEAN_GATE_TIE_BREAK,
            "pairCount": 0,
            "pairs": [],
        }

    by_layer: dict[int, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_layer.setdefault(int(candidate["sourceLayer"]), []).append(candidate)
    if set(by_layer) != {0, 1}:
        raise ScenarioTravelPairingError(f"subterranean gate pairing requires exactly surface/underground layers 0 and 1; found {sorted(by_layer)}")
    if len(by_layer[0]) != len(by_layer[1]):
        raise ScenarioTravelPairingError(f"subterranean gate count mismatch: surface={len(by_layer[0])} underground={len(by_layer[1])}")

    nearest_by_id: dict[int, tuple[dict[str, Any], tuple[int, int, int, int]]] = {}
    all_candidates = by_layer[0] + by_layer[1]
    for candidate in all_candidates:
        opposite_layer = 1 - int(candidate["sourceLayer"])
        nearest_by_id[int(candidate["objectId"])] = _nearest_candidate(candidate, by_layer[opposite_layer])

    # Prefer mutual nearest pairs; fall back to greedy min-distance matching when
    # AB/SoD maps have asymmetric gate layouts (nearest-pair conflicts).
    pairs: list[dict[str, Any]] = []
    seen: set[int] = set()
    mutual_ok = True
    for surface in sorted(by_layer[0], key=lambda item: int(item["objectId"])):
        underground, surface_key = nearest_by_id[int(surface["objectId"])]
        reverse, underground_key = nearest_by_id[int(underground["objectId"])]
        if int(reverse["objectId"]) != int(surface["objectId"]):
            mutual_ok = False
            break
        surface_id = int(surface["objectId"])
        underground_id = int(underground["objectId"])
        if surface_id in seen or underground_id in seen:
            mutual_ok = False
            break
        seen.add(surface_id)
        seen.add(underground_id)
        pairs.append({
            "surfaceObjectId": surface_id,
            "surfaceSourceKey": surface["sourceKey"],
            "surfaceSourceX": surface["sourceX"],
            "surfaceSourceY": surface["sourceY"],
            "undergroundObjectId": underground_id,
            "undergroundSourceKey": underground["sourceKey"],
            "undergroundSourceX": underground["sourceX"],
            "undergroundSourceY": underground["sourceY"],
            "sourceDistanceSquared": surface_key[0],
            "reverseDistanceSquared": underground_key[0],
            "templateObjectId": h3obj.OBJECT_SUBTERRANEAN_GATE,
            "templateAnimation": surface.get("templateAnimation"),
            "category": surface.get("category"),
            "payloadKind": surface.get("payloadKind"),
            "tieBreak": SUBTERRANEAN_GATE_TIE_BREAK,
            "pairingMode": "mutual_nearest",
        })

    if not mutual_ok:
        pairs = []
        seen = set()
        edges: list[tuple[tuple[int, int, int, int], dict[str, Any], dict[str, Any]]] = []
        for surface in by_layer[0]:
            for underground in by_layer[1]:
                edges.append((_pair_sort_key(surface, underground), surface, underground))
        edges.sort(key=lambda item: item[0])
        for sort_key, surface, underground in edges:
            surface_id = int(surface["objectId"])
            underground_id = int(underground["objectId"])
            if surface_id in seen or underground_id in seen:
                continue
            seen.add(surface_id)
            seen.add(underground_id)
            reverse_key = _pair_sort_key(underground, surface)
            pairs.append({
                "surfaceObjectId": surface_id,
                "surfaceSourceKey": surface["sourceKey"],
                "surfaceSourceX": surface["sourceX"],
                "surfaceSourceY": surface["sourceY"],
                "undergroundObjectId": underground_id,
                "undergroundSourceKey": underground["sourceKey"],
                "undergroundSourceX": underground["sourceX"],
                "undergroundSourceY": underground["sourceY"],
                "sourceDistanceSquared": sort_key[0],
                "reverseDistanceSquared": reverse_key[0],
                "templateObjectId": h3obj.OBJECT_SUBTERRANEAN_GATE,
                "templateAnimation": surface.get("templateAnimation"),
                "category": surface.get("category"),
                "payloadKind": surface.get("payloadKind"),
                "tieBreak": SUBTERRANEAN_GATE_TIE_BREAK,
                "pairingMode": "greedy_min_distance_fallback",
            })

    if len(seen) != len(all_candidates):
        missing = sorted(int(item["objectId"]) for item in all_candidates if int(item["objectId"]) not in seen)
        raise ScenarioTravelPairingError(f"subterranean gate pairing coverage mismatch, unpaired ids={missing}")
    return {
        "status": "generated_static_contract_runtime_unvalidated",
        "objectId": h3obj.OBJECT_SUBTERRANEAN_GATE,
        "objectName": "subterranean_gate",
        "source": SUBTERRANEAN_GATE_PAIRING_SOURCE,
        "policy": (
            SUBTERRANEAN_GATE_PAIRING_POLICY
            if mutual_ok
            else "greedy_min_distance_fallback_when_mutual_nearest_conflicts"
        ),
        "tieBreak": SUBTERRANEAN_GATE_TIE_BREAK,
        "pairCount": len(pairs),
        "pairs": pairs,
    }


def pair_whirlpools_by_nearest_same_layer_rule(entities: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Route whirlpools for Olden single-target portals.

    Even same-layer-only maps keep mutual nearest pairs (Homecoming-stable).
    Odd counts or multi-layer networks (Tunnels: 4 surface + 1 underground) use a
    deterministic circular chain sorted by (layer, objectId). Returns directed
    pairs (objectIdA → objectIdB); callers must not assume mutual edges.
    """

    candidates = [
        _candidate_record(entity)
        for entity in entities
        if entity.get("templateObjectId") == h3obj.OBJECT_WHIRLPOOL
    ]
    if not candidates:
        return {
            "status": "generated_static_contract_runtime_unvalidated",
            "objectId": h3obj.OBJECT_WHIRLPOOL,
            "objectName": "whirlpool",
            "source": WHIRLPOOL_PAIRING_SOURCE,
            "policy": WHIRLPOOL_PAIRING_POLICY,
            "tieBreak": WHIRLPOOL_TIE_BREAK,
            "pairCount": 0,
            "pairs": [],
            "routing": "empty",
        }
    if len(candidates) == 1:
        alone = candidates[0]
        raise ScenarioTravelPairingError(
            "whirlpool routing requires at least 2 objects; found 1 at "
            f"{alone.get('sourceKey')} layer={alone.get('sourceLayer')}"
        )

    by_layer: dict[int, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_layer.setdefault(int(candidate["sourceLayer"]), []).append(candidate)
    multi_layer = len(by_layer) > 1
    odd_layer = any(len(group) % 2 for group in by_layer.values())
    use_circular = multi_layer or odd_layer

    pairs: list[dict[str, Any]] = []
    if use_circular:
        ordered = sorted(
            candidates,
            key=lambda item: (int(item["sourceLayer"]), int(item["objectId"])),
        )
        for index, first in enumerate(ordered):
            second = ordered[(index + 1) % len(ordered)]
            pairs.append(
                {
                    "objectIdA": int(first["objectId"]),
                    "sourceKeyA": first["sourceKey"],
                    "sourceXA": first["sourceX"],
                    "sourceYA": first["sourceY"],
                    "sourceLayerA": int(first["sourceLayer"]),
                    "objectIdB": int(second["objectId"]),
                    "sourceKeyB": second["sourceKey"],
                    "sourceXB": second["sourceX"],
                    "sourceYB": second["sourceY"],
                    "sourceLayerB": int(second["sourceLayer"]),
                    "sourceLayer": int(first["sourceLayer"]),
                    "templateObjectId": h3obj.OBJECT_WHIRLPOOL,
                    "templateAnimation": first.get("templateAnimation"),
                    "category": first.get("category"),
                    "payloadKind": first.get("payloadKind"),
                    "tieBreak": WHIRLPOOL_TIE_BREAK,
                    "groupSize": len(ordered),
                    "routing": "circular_chain",
                }
            )
        routing = "circular_chain"
    else:
        seen: set[int] = set()
        mutual_ok = True
        for layer, layer_candidates in sorted(by_layer.items()):
            nearest_by_id: dict[int, tuple[dict[str, Any], tuple[int, int, int, int]]] = {}
            for candidate in layer_candidates:
                others = [
                    item
                    for item in layer_candidates
                    if int(item["objectId"]) != int(candidate["objectId"])
                ]
                nearest_by_id[int(candidate["objectId"])] = _nearest_candidate(
                    candidate, others
                )
            for candidate in sorted(layer_candidates, key=lambda item: int(item["objectId"])):
                object_id = int(candidate["objectId"])
                if object_id in seen:
                    continue
                partner, forward_key = nearest_by_id[object_id]
                reverse, reverse_key = nearest_by_id[int(partner["objectId"])]
                if int(reverse["objectId"]) != object_id:
                    mutual_ok = False
                    break
                partner_id = int(partner["objectId"])
                if partner_id in seen:
                    mutual_ok = False
                    break
                seen.add(object_id)
                seen.add(partner_id)
                for first, second, dist_key, rev_key in (
                    (candidate, partner, forward_key, reverse_key),
                    (partner, candidate, reverse_key, forward_key),
                ):
                    pairs.append(
                        {
                            "objectIdA": int(first["objectId"]),
                            "sourceKeyA": first["sourceKey"],
                            "sourceXA": first["sourceX"],
                            "sourceYA": first["sourceY"],
                            "sourceLayerA": layer,
                            "objectIdB": int(second["objectId"]),
                            "sourceKeyB": second["sourceKey"],
                            "sourceXB": second["sourceX"],
                            "sourceYB": second["sourceY"],
                            "sourceLayerB": layer,
                            "sourceLayer": layer,
                            "sourceDistanceSquared": dist_key[0],
                            "reverseDistanceSquared": rev_key[0],
                            "templateObjectId": h3obj.OBJECT_WHIRLPOOL,
                            "templateAnimation": first.get("templateAnimation"),
                            "category": first.get("category"),
                            "payloadKind": first.get("payloadKind"),
                            "tieBreak": WHIRLPOOL_TIE_BREAK,
                            "groupSize": 2,
                            "routing": "mutual_pair",
                        }
                    )
            if not mutual_ok:
                break

        if not mutual_ok:
            # AB/SoD maps can have asymmetric same-layer whirlpool clusters.
            pairs = []
            seen = set()
            for layer, layer_candidates in sorted(by_layer.items()):
                edges: list[tuple[tuple[int, int, int, int], dict[str, Any], dict[str, Any]]] = []
                for left in layer_candidates:
                    for right in layer_candidates:
                        if int(left["objectId"]) >= int(right["objectId"]):
                            continue
                        edges.append((_pair_sort_key(left, right), left, right))
                edges.sort(key=lambda item: item[0])
                for sort_key, left, right in edges:
                    left_id = int(left["objectId"])
                    right_id = int(right["objectId"])
                    if left_id in seen or right_id in seen:
                        continue
                    seen.add(left_id)
                    seen.add(right_id)
                    reverse_key = _pair_sort_key(right, left)
                    for first, second, dist_key, rev_key in (
                        (left, right, sort_key, reverse_key),
                        (right, left, reverse_key, sort_key),
                    ):
                        pairs.append(
                            {
                                "objectIdA": int(first["objectId"]),
                                "sourceKeyA": first["sourceKey"],
                                "sourceXA": first["sourceX"],
                                "sourceYA": first["sourceY"],
                                "sourceLayerA": layer,
                                "objectIdB": int(second["objectId"]),
                                "sourceKeyB": second["sourceKey"],
                                "sourceXB": second["sourceX"],
                                "sourceYB": second["sourceY"],
                                "sourceLayerB": layer,
                                "sourceLayer": layer,
                                "sourceDistanceSquared": dist_key[0],
                                "reverseDistanceSquared": rev_key[0],
                                "templateObjectId": h3obj.OBJECT_WHIRLPOOL,
                                "templateAnimation": first.get("templateAnimation"),
                                "category": first.get("category"),
                                "payloadKind": first.get("payloadKind"),
                                "tieBreak": WHIRLPOOL_TIE_BREAK,
                                "groupSize": 2,
                                "routing": "greedy_min_distance_fallback",
                            }
                        )
            routing = "greedy_min_distance_fallback_when_mutual_nearest_conflicts"
        else:
            routing = "mutual_nearest_same_layer"

        if len(seen) != len(candidates):
            missing = sorted(
                int(item["objectId"])
                for item in candidates
                if int(item["objectId"]) not in seen
            )
            raise ScenarioTravelPairingError(
                f"whirlpool pairing coverage mismatch, unpaired ids={missing}"
            )

    return {
        "status": "generated_static_contract_runtime_unvalidated",
        "objectId": h3obj.OBJECT_WHIRLPOOL,
        "objectName": "whirlpool",
        "source": WHIRLPOOL_PAIRING_SOURCE,
        "policy": WHIRLPOOL_PAIRING_POLICY,
        "tieBreak": WHIRLPOOL_TIE_BREAK,
        "pairCount": len(pairs),
        "pairs": pairs,
        "routing": routing,
    }


def pair_two_way_monoliths_by_animation_same_layer_rule(entities: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Route two-way monoliths that share animation (color), across layers.

    Classic RoE/AB/SoD maps identify two-way monolith networks by animation DEF,
    not by map layer. Same-color pairs routinely connect surface↔underground.
    (Function name retains ``same_layer`` for call-site stability; grouping is by
    animation only.)

    HoMM3 allows N>=2 same-color two-way monoliths (Neutral Affairs has 3).
    Olden ``propPortals`` carries a single ``targetIdx`` per object, so N==2 stays
    a mutual pair and N>2 becomes a deterministic circular chain
    (sorted by layer, then objectId): A→B→…→Z→A.
    """

    candidates = [
        _candidate_record(entity)
        for entity in entities
        if entity.get("templateObjectId") == h3obj.OBJECT_TWO_WAY_MONOLITH
    ]
    if not candidates:
        return {
            "status": "generated_static_contract_runtime_unvalidated",
            "objectId": h3obj.OBJECT_TWO_WAY_MONOLITH,
            "objectName": "two_way_monolith",
            "source": MONOLITH_TWO_WAY_PAIRING_SOURCE,
            "policy": MONOLITH_TWO_WAY_PAIRING_POLICY,
            "tieBreak": MONOLITH_TWO_WAY_TIE_BREAK,
            "pairCount": 0,
            "pairs": [],
        }

    by_animation: dict[str, list[dict[str, Any]]] = {}
    for candidate in candidates:
        animation = candidate.get("templateAnimation")
        if not isinstance(animation, str) or not animation:
            raise ScenarioTravelPairingError(
                f"monolith pairing requires templateAnimation for {candidate['sourceKey']}"
            )
        by_animation.setdefault(animation, []).append(candidate)

    pairs: list[dict[str, Any]] = []
    seen: set[int] = set()
    for animation, group in sorted(by_animation.items()):
        if len(group) < 2:
            raise ScenarioTravelPairingError(
                "monolith pairing requires at least 2 objects per animation group; "
                f"animation={animation} found {len(group)}"
            )
        ordered = sorted(
            group,
            key=lambda item: (int(item["sourceLayer"]), int(item["objectId"])),
        )
        for index, first in enumerate(ordered):
            second = ordered[(index + 1) % len(ordered)]
            object_a = int(first["objectId"])
            object_b = int(second["objectId"])
            if object_a in seen:
                raise ScenarioTravelPairingError(
                    f"monolith duplicate route source detected: {object_a}->{object_b}"
                )
            seen.add(object_a)
            pairs.append({
                "objectIdA": object_a,
                "sourceKeyA": first["sourceKey"],
                "sourceXA": first["sourceX"],
                "sourceYA": first["sourceY"],
                "sourceLayerA": int(first["sourceLayer"]),
                "objectIdB": object_b,
                "sourceKeyB": second["sourceKey"],
                "sourceXB": second["sourceX"],
                "sourceYB": second["sourceY"],
                "sourceLayerB": int(second["sourceLayer"]),
                "templateObjectId": h3obj.OBJECT_TWO_WAY_MONOLITH,
                "templateAnimation": animation,
                "category": first.get("category"),
                "payloadKind": first.get("payloadKind"),
                "tieBreak": MONOLITH_TWO_WAY_TIE_BREAK,
                "groupSize": len(ordered),
                "routing": "mutual_pair" if len(ordered) == 2 else "circular_chain",
            })

    if len(seen) != len(candidates):
        missing = sorted(int(item["objectId"]) for item in candidates if int(item["objectId"]) not in seen)
        raise ScenarioTravelPairingError(f"monolith pairing coverage mismatch, unpaired ids={missing}")
    return {
        "status": "generated_static_contract_runtime_unvalidated",
        "objectId": h3obj.OBJECT_TWO_WAY_MONOLITH,
        "objectName": "two_way_monolith",
        "source": MONOLITH_TWO_WAY_PAIRING_SOURCE,
        "policy": MONOLITH_TWO_WAY_PAIRING_POLICY,
        "tieBreak": MONOLITH_TWO_WAY_TIE_BREAK,
        "pairCount": len(pairs),
        "pairs": pairs,
    }


def pair_two_way_monoliths_by_subtype_cross_layer_rule(
    entities: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Route each HoMM3 two-way monolith subtype as one map-wide network."""

    candidates = [
        _candidate_record(entity)
        for entity in entities
        if entity.get("templateObjectId") == h3obj.OBJECT_TWO_WAY_MONOLITH
    ]
    if not candidates:
        return {
            "status": "generated_static_contract_runtime_unvalidated",
            "objectId": h3obj.OBJECT_TWO_WAY_MONOLITH,
            "objectName": "two_way_monolith",
            "source": MONOLITH_TWO_WAY_CROSS_LAYER_SOURCE,
            "policy": MONOLITH_TWO_WAY_CROSS_LAYER_POLICY,
            "tieBreak": MONOLITH_TWO_WAY_TIE_BREAK,
            "pairCount": 0,
            "pairs": [],
        }

    by_subtype: dict[int, list[dict[str, Any]]] = {}
    for candidate in candidates:
        by_subtype.setdefault(int(candidate["templateSubtype"]), []).append(candidate)

    pairs: list[dict[str, Any]] = []
    seen: set[int] = set()
    for subtype, group in sorted(by_subtype.items()):
        if len(group) < 2:
            only = group[0]
            raise ScenarioTravelPairingError(
                "monolith pairing requires at least 2 objects per subtype network; "
                f"subtype={subtype} found 1 at {only['sourceKey']}"
            )
        ordered = sorted(
            group,
            key=lambda item: (int(item["sourceLayer"]), int(item["objectId"])),
        )
        for index, first in enumerate(ordered):
            second = ordered[(index + 1) % len(ordered)]
            object_a = int(first["objectId"])
            object_b = int(second["objectId"])
            if object_a in seen:
                raise ScenarioTravelPairingError(
                    f"monolith duplicate route source detected: {object_a}->{object_b}"
                )
            seen.add(object_a)
            pairs.append(
                {
                    "objectIdA": object_a,
                    "sourceKeyA": first["sourceKey"],
                    "sourceXA": first["sourceX"],
                    "sourceYA": first["sourceY"],
                    "sourceLayerA": int(first["sourceLayer"]),
                    "objectIdB": object_b,
                    "sourceKeyB": second["sourceKey"],
                    "sourceXB": second["sourceX"],
                    "sourceYB": second["sourceY"],
                    "sourceLayerB": int(second["sourceLayer"]),
                    "sourceLayer": int(first["sourceLayer"]),
                    "templateObjectId": h3obj.OBJECT_TWO_WAY_MONOLITH,
                    "templateSubtype": subtype,
                    "templateAnimation": first.get("templateAnimation"),
                    "category": first.get("category"),
                    "payloadKind": first.get("payloadKind"),
                    "tieBreak": MONOLITH_TWO_WAY_TIE_BREAK,
                    "groupSize": len(ordered),
                    "routing": "mutual_pair" if len(ordered) == 2 else "circular_chain",
                }
            )

    if len(seen) != len(candidates):
        missing = sorted(int(item["objectId"]) for item in candidates if int(item["objectId"]) not in seen)
        raise ScenarioTravelPairingError(f"monolith pairing coverage mismatch, unpaired ids={missing}")
    return {
        "status": "generated_static_contract_runtime_unvalidated",
        "objectId": h3obj.OBJECT_TWO_WAY_MONOLITH,
        "objectName": "two_way_monolith",
        "source": MONOLITH_TWO_WAY_CROSS_LAYER_SOURCE,
        "policy": MONOLITH_TWO_WAY_CROSS_LAYER_POLICY,
        "tieBreak": MONOLITH_TWO_WAY_TIE_BREAK,
        "pairCount": len(pairs),
        "pairs": pairs,
    }