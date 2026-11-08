#!/usr/bin/env python3
"""Focused proofs for campaign entrance occupancy / H3-floor accessibility.

Run from repo root:
  PYTHONPATH=experiments/campaign_port_poc/raw_translation:experiments/campaign_port_poc/approach_cell:experiments/campaign_port_poc \\
    python experiments/campaign_port_poc/raw_translation/test_entrance_occupancy.py
"""
from __future__ import annotations

import sys
from pathlib import Path

POC = Path(__file__).resolve().parents[1]
for path in (POC / "raw_translation", POC / "approach_cell", POC):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

import entrance_occupancy as occupancy
import surface_emit as single

TREE_SID = "log_1"
CHEST_SID = "chest"
SQUAD_SID = "random-squad"

TREE = {"id": TREE_SID, "sizeX": 1, "sizeZ": 1, "nodes": [1]}
CHEST = {"id": CHEST_SID, "sizeX": 1, "sizeZ": 1, "nodes": [2]}
SQUAD = {"id": SQUAD_SID, "sizeX": 1, "sizeZ": 1, "nodes": [1]}


def _group(sid: str, object_id: int, node: int) -> dict:
    return {
        "sid": sid,
        "ids": [object_id],
        "nodes": [node],
        "rotations": [0],
        "levels": [0],
    }


def _h3_block_mask_for_offsets(offsets: set[tuple[int, int]]) -> list[int]:
    rows = [255] * 6
    for dx, dy in offsets:
        col = single.H3M_MASK_ANCHOR_X + dx
        row = single.H3M_MASK_ANCHOR_Y + dy
        rows[row] &= ~(1 << col)
    return rows


def _layer(*, width: int, height: int, tiles: list[int], layer: int = 0) -> dict:
    return {
        "layer": layer,
        "mapData": {
            "tilesMap": list(tiles),
            "sizeX_": width,
            "sizeZ_": height,
        },
    }


def _target(width: int):
    def layer_target_node(_layer: int, source_x: int, source_y: int) -> int:
        if not (0 <= source_x < width):
            raise ValueError(source_x)
        return source_y * width + source_x

    return layer_target_node


def _run(
    *,
    width: int,
    height: int,
    objects: list[dict],
    configs: dict[str, dict],
    tiles: list[int],
    entities: list[dict] | None = None,
):
    previous_w, previous_h = single.OLDEN_WIDTH, single.OLDEN_HEIGHT
    single.OLDEN_WIDTH = width
    single.OLDEN_HEIGHT = height
    try:
        return occupancy.apply_raw_translation_accessibility_pass(
            objects=objects,
            native_object_configs=configs,
            object_properties={"propEntities": []},
            global_entities=list(entities or []),
            layered_map_data=[_layer(width=width, height=height, tiles=tiles)],
            layer_target_node=_target(width),
            width=width,
            height=height,
            source_width=width,
            source_height=height,
            map_sid="fixture",
        )
    finally:
        single.OLDEN_WIDTH = previous_w
        single.OLDEN_HEIGHT = previous_h


def _live_ids(objects: list[dict]) -> set[int]:
    ids: set[int] = set()
    for group in objects:
        for object_id in group.get("ids") or []:
            if isinstance(object_id, int):
                ids.add(object_id)
    return ids


def test_tree_on_chest_gate_removed() -> None:
    width = height = 8
    node = 3 + 3 * width
    objects = [
        _group(CHEST_SID, 10, node),
        _group(TREE_SID, 20, node),
    ]
    tiles = [2] * (width * height)
    report = _run(
        width=width,
        height=height,
        objects=objects,
        configs={CHEST_SID: CHEST, TREE_SID: TREE},
        tiles=tiles,
    )
    assert 20 not in _live_ids(objects), "tree on chest GATE must be deleted"
    assert 10 in _live_ids(objects), "chest must stay"
    assert any(row["objectId"] == 20 for row in report["cleared"])
    assert report["leftoverSuppressibleCount"] == 0


def test_tree_on_h3_walkable_floor_removed() -> None:
    width = height = 4
    objects = [_group(TREE_SID, 20, 1)]  # source (1,0)
    tiles = [2] * (width * height)
    report = _run(
        width=width,
        height=height,
        objects=objects,
        configs={TREE_SID: TREE},
        tiles=tiles,
    )
    assert 20 not in _live_ids(objects), "tree on H3-open grass must be deleted"
    assert report["cleared"][0]["reason"] == "suppressible_sealing_h3_open_floor"


def test_tree_on_h3_blocked_cell_kept() -> None:
    width = height = 4
    objects = [_group(TREE_SID, 20, 1)]  # source (1,0)
    tiles = [2] * (width * height)
    entity = {
        "sourceLayer": 0,
        "sourceX": 1,
        "sourceY": 0,
        "templateBlockMask": _h3_block_mask_for_offsets({(0, 0)}),
        "templateVisitMask": [0] * 6,
    }
    report = _run(
        width=width,
        height=height,
        objects=objects,
        configs={TREE_SID: TREE},
        tiles=tiles,
        entities=[entity],
    )
    assert 20 in _live_ids(objects), "tree on H3-blocked cell must stay"
    assert report["clearedCount"] == 0


def test_random_squad_on_gate_unresolved_not_deleted() -> None:
    width = height = 8
    node = 2 + 2 * width
    objects = [
        _group(CHEST_SID, 10, node),
        _group(SQUAD_SID, 30, node),
    ]
    tiles = [2] * (width * height)
    report = _run(
        width=width,
        height=height,
        objects=objects,
        configs={CHEST_SID: CHEST, SQUAD_SID: SQUAD},
        tiles=tiles,
    )
    assert 30 in _live_ids(objects), "random-squad on GATE must not be deleted"
    assert 10 in _live_ids(objects)
    assert report["unresolvedCount"] == 1
    assert report["unresolved"][0]["objectId"] == 30
    assert report["unresolved"][0]["sid"] == SQUAD_SID


def test_ocean_and_rock_tiles_are_not_walkable() -> None:
    width = height = 4
    tiles = [occupancy.H3_WATER_TERRAIN_ID] * 8 + [occupancy.H3_ROCK_TERRAIN_ID] * 8
    walkable = occupancy.build_h3_ground_truth_walkable_nodes(
        layered_map_data=[_layer(width=width, height=height, tiles=tiles)],
        global_entities=[],
        layer_target_node=_target(width),
        source_width=width,
        source_height=height,
    )
    assert walkable == set()


def test_pass_does_not_accept_or_need_water_maps() -> None:
    import inspect

    params = inspect.signature(occupancy.apply_raw_translation_accessibility_pass).parameters
    for forbidden in ("water_map", "waterMap", "levels_map", "climbs_map"):
        assert forbidden not in params, f"pass must not take {forbidden}"


def main() -> int:
    tests = [
        test_tree_on_chest_gate_removed,
        test_tree_on_h3_walkable_floor_removed,
        test_tree_on_h3_blocked_cell_kept,
        test_random_squad_on_gate_unresolved_not_deleted,
        test_ocean_and_rock_tiles_are_not_walkable,
        test_pass_does_not_accept_or_need_water_maps,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print("test_entrance_occupancy: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
