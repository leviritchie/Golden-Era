#!/usr/bin/env python3
"""Validate the isolated H3-versus-Olden footprint compatibility pass.

This is a source/static contract plus a small in-memory behavior fixture. It
never reads or rewrites a generated map. The fixture covers the ordered repair
policy, fail-open commit of successful repairs with unresolved leftovers, and
the optional fail-closed transaction boundary.
"""

from __future__ import annotations

import copy
import io
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
RAW = POC / "raw_translation"
APPROACH = POC / "approach_cell"
for path in (POC, RAW, APPROACH):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import homm3_footprint_compatibility as compatibility
import exact_homm3_footprint as exact_fp
import map_load_preflight
import surface_emit as surface_emit_module


WIDTH = 8
HEIGHT = 8


def node(x: int, y: int) -> int:
    return y * WIDTH + x


def target_node(_layer: int, x: int, y: int) -> int:
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
        raise ValueError(f"source projection outside fixture map: {x},{y}")
    return node(x, y)


def _h3_block_mask_for_offsets(offsets: set[tuple[int, int]]) -> list[int]:
    """Build H3M block mask (clear bits = blocked) for BR-relative offsets."""
    rows = [255] * 6
    for dx, dy in offsets:
        col = surface_emit_module.H3M_MASK_ANCHOR_X + dx
        row = surface_emit_module.H3M_MASK_ANCHOR_Y + dy
        if not (0 <= col < 8 and 0 <= row < 6):
            raise ValueError(f"fixture offset outside H3 mask: {(dx, dy)}")
        rows[row] &= ~(1 << col)
    return rows


def _h3_visit_mask_for_offsets(offsets: set[tuple[int, int]]) -> list[int]:
    """Build H3M visit mask (set bits = visit/land-on) for BR-relative offsets."""
    rows = [0] * 6
    for dx, dy in offsets:
        col = surface_emit_module.H3M_MASK_ANCHOR_X + dx
        row = surface_emit_module.H3M_MASK_ANCHOR_Y + dy
        if not (0 <= col < 8 and 0 <= row < 6):
            raise ValueError(f"fixture offset outside H3 mask: {(dx, dy)}")
        rows[row] |= 1 << col
    return rows


def h3_entity(source_index: int, x: int, y: int, layer: int = 0) -> dict[str, Any]:
    # One blocked, non-visitable cell at the H3 anchor. All other mask cells
    # are unblocked; the zero visit mask keeps the blocker non-visitable.
    return {
        "sourceIndex": source_index,
        "sourceLayer": layer,
        "sourceX": x,
        "sourceY": y,
        "templateBlockMask": _h3_block_mask_for_offsets({(0, 0)}),
        "templateVisitMask": [0] * 6,
    }


def h3_entity_with_land_on(
    source_index: int,
    x: int,
    y: int,
    *,
    hard_offsets: set[tuple[int, int]],
    land_on_offsets: set[tuple[int, int]],
    layer: int = 0,
) -> dict[str, Any]:
    """H3 entity with hard blockers and visit/land-on wildcards."""
    if not land_on_offsets:
        raise ValueError("land_on_offsets must be non-empty for land-on fixtures")
    if hard_offsets & land_on_offsets:
        raise ValueError("hard and land-on offsets must be disjoint")
    return {
        "sourceIndex": source_index,
        "sourceLayer": layer,
        "sourceX": x,
        "sourceY": y,
        "templateBlockMask": _h3_block_mask_for_offsets(hard_offsets | land_on_offsets),
        "templateVisitMask": _h3_visit_mask_for_offsets(land_on_offsets),
    }


def config(tag: str) -> dict[str, Any]:
    return {
        "tag": tag,
        "isInteractable": tag == "Interact",
        "sizeX": 1,
        "sizeZ": 2,
        "pivotX": 0,
        "pivotZ": 0,
        "canBeMirrored": False,
        "nodes": [1, 2],
    }


def group(sid: str, rows: list[tuple[int, int]]) -> dict[str, Any]:
    return {
        "sid": sid,
        "ids": [object_id for object_id, _ in rows],
        "nodes": [object_node for _, object_node in rows],
        "rotations": [0] * len(rows),
        "levels": [0] * len(rows),
    }


def run(
    *,
    entities: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    configs: dict[str, dict[str, Any]],
    raise_on_failure: bool = True,
    target_node_fn: Callable[[int, int, int], int] = target_node,
    layer_resolver: Callable[[int], int | None] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    properties: dict[str, Any] = {
        "propObjects": [
            {"id": object_id, "type": 0}
            for object_group in objects
            for object_id in object_group["ids"]
        ]
    }
    original_properties = copy.deepcopy(properties)
    report = compatibility.apply_homm3_footprint_compatibility(
        global_entities=entities,
        objects=objects,
        object_properties=properties,
        native_object_configs=configs,
        layer_target_node=target_node_fn,
        layer_resolver=layer_resolver,
        width=WIDTH,
        height=HEIGHT,
        map_sid="fixture",
        raise_on_failure=raise_on_failure,
    )
    return report, objects, {"originalProperties": original_properties, "properties": properties}


def test_new_scenery_is_deleted_first() -> None:
    # Building H3 at (2,2), Olden at (3,2): one-cell east overhang.
    # Outer-face rule only counts the east neighbor (100), not west/side touches.
    entities = [h3_entity(1, 2, 2), h3_entity(101, 3, 2)]
    objects = [
        group("building", [(1, node(3, 2))]),
        group("scenery", [(100, node(4, 2)), (101, node(3, 2))]),
    ]
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={"building": config("Interact"), "scenery": config("Environment")},
    )
    assert report["status"] == compatibility.STATUS_APPLIED
    assert report["deletedObjectIds"] == [100]
    assert not any(100 in row["ids"] for row in result)
    assert report["repairs"][0]["status"] == "repaired_by_new_scenery_delete"
    assert report["repairs"][0]["initialUnwantedContacts"][0]["blockerObjectId"] == 100
    assert not report["movedBuildings"]


def test_unique_scenery_is_preserved_and_building_moves() -> None:
    entities = [
        h3_entity(1, 2, 2),
        h3_entity(100, 4, 2),
        h3_entity(3, 3, 3),
        h3_entity(4, 3, 1),
    ]
    objects = [
        group("building", [(1, node(3, 2)), (3, node(3, 3)), (4, node(3, 1))]),
        group("scenery", [(100, node(4, 2))]),
    ]
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={"building": config("Interact"), "scenery": config("Environment")},
    )
    assert report["status"] == compatibility.STATUS_APPLIED
    assert report["deletedObjectIds"] == []
    assert report["movedBuildings"]
    assert report["movedBuildings"][0]["direction"] == "west"
    assert any(1 in row["ids"] and node(2, 2) in row["nodes"] for row in result)


def test_unique_scenery_can_be_removed_when_other_blocker_covers_it():
    entities = [h3_entity(1, 2, 2), h3_entity(100, 3, 2)]
    objects = [
        group("building", [(1, node(3, 2))]),
        group("scenery", [(100, node(3, 2))]),
    ]
    state = compatibility._State(
        objects=objects,
        global_entities=entities,
        native_object_configs={
            "building": config("Interact"),
            "scenery": config("Environment"),
        },
        layer_target_node=target_node,
        width=WIDTH,
        height=HEIGHT,
        layer_resolver=None,
    )
    building = state.instances[1]
    scenery = state.instances[100]
    assert set(scenery.h3_cells) - set(building.h3_cells)
    assert set(scenery.h3_cells) <= set(building.olden_cells)
    removable, reason = compatibility._scenery_can_be_removed(state, scenery)
    assert removable
    assert reason in {
        "H3_blocker_cells_redundantly_covered",
        "H3_blocker_cells_preserved_by_other_permanent_blocker",
    }
    removable_without_building, _reason = compatibility._scenery_can_be_removed(
        state,
        scenery,
        excluded_ids={building.object_id},
    )
    assert not removable_without_building
    removable_at_target, target_reason = compatibility._scenery_can_be_removed(
        state,
        scenery,
        excluded_ids={building.object_id},
        preserved_blocker_cells=scenery.h3_cells,
    )
    assert removable_at_target
    assert target_reason == "H3_blocker_cells_preserved_by_other_permanent_blocker"


def test_final_blocker_parity_delta_detects_extra_and_missing_cells() -> None:
    entities = [h3_entity(1, 2, 2)]
    objects = [group("building", [(1, node(3, 2))])]
    state = compatibility._State(
        objects=objects,
        global_entities=entities,
        native_object_configs={"building": config("Interact")},
        layer_target_node=target_node,
        width=WIDTH,
        height=HEIGHT,
        layer_resolver=None,
    )
    extra, missing = compatibility._final_blocker_parity_delta(
        state,
        {node(2, 2), node(3, 2)},
    )
    assert extra == frozenset({node(3, 2)})
    assert missing == frozenset({node(2, 2)})

def test_scenery_deletion_requires_remaining_olden_coverage() -> None:
    entities = [h3_entity(1, 3, 2), h3_entity(100, 3, 2)]
    objects = [
        group("building", [(1, node(4, 2))]),
        group("scenery", [(100, node(3, 2))]),
    ]
    state = compatibility._State(
        objects=objects,
        global_entities=entities,
        native_object_configs={
            "building": config("Interact"),
            "scenery": config("Environment"),
        },
        layer_target_node=target_node,
        width=WIDTH,
        height=HEIGHT,
        layer_resolver=None,
    )
    removable, reason = compatibility._scenery_can_be_removed(
        state,
        state.instances[100],
    )
    assert not removable
    assert reason == "would_remove_unique_H3_blocker_cell"

def test_building_move_preserves_former_h3_blocker_cells():
    entities = [h3_entity(1, 3, 2)]
    objects = [group("building", [(1, node(3, 2))])]
    state = compatibility._State(
        objects=objects,
        global_entities=entities,
        native_object_configs={"building": config("Interact")},
        layer_target_node=target_node,
        width=WIDTH,
        height=HEIGHT,
        layer_resolver=None,
    )
    building = state.instances[1]
    translated = compatibility._translate_cells(
        building.olden_cells,
        dx=1,
        dy=0,
        width=WIDTH,
        height=HEIGHT,
    )
    assert translated is not None
    assert set(building.h3_cells) & set(building.olden_cells)
    unpreserved = compatibility._unpreserved_h3_blocker_cells_after_move(
        state,
        building,
        translated,
    )
    assert node(3, 2) in unpreserved


def test_building_can_dig_into_existing_scenery() -> None:
    # Building overhangs east from H3 (2,2) onto Olden (3,2) and contacts source
    # scenery on that outer face. West is blocked by another building, so the
    # repair digs east into the scenery instead of deleting it.
    entities = [h3_entity(1, 2, 2), h3_entity(100, 4, 2), h3_entity(2, 2, 2)]
    objects = [
        group("building", [(1, node(3, 2)), (2, node(2, 2))]),
        group("scenery", [(100, node(4, 2))]),
    ]
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={"building": config("Interact"), "scenery": config("Environment")},
    )
    assert report["status"] == compatibility.STATUS_APPLIED
    assert report["deletedObjectIds"] == []
    assert report["movedBuildings"][0]["direction"] == "east"
    assert any(1 in row["ids"] and node(4, 2) in row["nodes"] for row in result)
    assert any(100 in row["ids"] and node(4, 2) in row["nodes"] for row in result)

    candidate_objects = [
        group("building", [(1, node(3, 2)), (2, node(2, 2))]),
        group("scenery", [(100, node(4, 2))]),
    ]
    state = compatibility._State(
        objects=candidate_objects,
        global_entities=entities,
        native_object_configs={
            "building": config("Interact"),
            "scenery": config("Environment"),
        },
        layer_target_node=target_node,
        width=WIDTH,
        height=HEIGHT,
        layer_resolver=None,
    )
    candidates = compatibility._move_candidates(state, state.instances[1])
    west = next(candidate for candidate in candidates if candidate["direction"] == "west")
    assert west["unsafeOverlaps"]
    assert not west["valid"]

def test_minimal_scenery_cleanup_then_move() -> None:
    # With 2-tile reposition enabled, digging two tiles east into scenery 101
    # clears the outer-face contact without a cull. Prefer that shorter-repair
    # path over deleting scenery and moving one tile.
    entities = [
        h3_entity(1, 2, 2),
        h3_entity(100, 4, 2),
        h3_entity(2, 2, 2),
        h3_entity(3, 3, 3),
        h3_entity(4, 3, 1),
        h3_entity(5, 1, 2),
        h3_entity(6, 0, 2),
    ]
    objects = [
        group(
            "building",
            [
                (1, node(3, 2)),
                (2, node(2, 2)),
                (3, node(3, 3)),
                (4, node(3, 1)),
                (5, node(1, 2)),
                (6, node(0, 2)),
            ],
        ),
        group("scenery", [(100, node(4, 2)), (101, node(5, 2))]),
    ]
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={"building": config("Interact"), "scenery": config("Environment")},
    )
    assert report["status"] == compatibility.STATUS_APPLIED
    move = report["movedBuildings"][0]
    assert move["direction"] == "east"
    assert move["step"] == 2
    assert move["toNode"] == node(5, 2)
    assert any(1 in row["ids"] and node(5, 2) in row["nodes"] for row in result)


def test_scenery_cleanup_can_cull_multiple_to_support_reposition() -> None:
    entities = [h3_entity(1, 2, 2), h3_entity(100, 4, 2)]
    objects = [
        group("building", [(1, node(3, 2))]),
        group("scenery", [(100, node(4, 2)), (101, node(5, 2)), (102, node(4, 2))]),
    ]
    # 102 shares the dig-in cell; 101 remains an outer-face contact after east-1.
    # Cleanup must be allowed to remove every removable obstructing scenery row.
    state = compatibility._State(
        objects=objects,
        global_entities=entities,
        native_object_configs={
            "building": config("Interact"),
            "scenery": config("Environment"),
        },
        layer_target_node=target_node,
        width=WIDTH,
        height=HEIGHT,
        layer_resolver=None,
    )
    building = state.instances[1]
    candidates = compatibility._move_candidates(state, building)
    east1 = next(
        candidate
        for candidate in candidates
        if candidate["direction"] == "east" and candidate["step"] == 1
    )
    required = compatibility._scenery_cleanup_for_candidate(state, building, east1)
    assert required is not None
    assert 101 in required


def test_two_tile_reposition_is_allowed() -> None:
    # Building sits two tiles east of its H3 cell and touches another building on
    # the outer east face. One-tile west overlaps a third building; two-tile west
    # lands on the H3 cell and clears the contact.
    entities = [h3_entity(1, 2, 2), h3_entity(2, 3, 2), h3_entity(3, 5, 2)]
    objects = [
        group("building", [(1, node(4, 2)), (2, node(3, 2)), (3, node(5, 2))]),
    ]
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={"building": config("Interact")},
    )
    assert report["status"] == compatibility.STATUS_APPLIED
    move = report["movedBuildings"][0]
    assert move["direction"] == "west"
    assert move["step"] == 2
    assert move["toNode"] == node(2, 2)
    assert any(1 in row["ids"] and node(2, 2) in row["nodes"] for row in result)


def test_land_on_cell_occupied_is_not_overhang() -> None:
    # Source anchor is the land-on cell (3,2); hard blocker at (2,2). Olden
    # occupies both. Scenery east of land-on is not an outer-face contact of a
    # newly emitted cell because land-on may be treated as closed.
    entities = [
        h3_entity_with_land_on(
            1,
            3,
            2,
            hard_offsets={(-1, 0)},
            land_on_offsets={(0, 0)},
        ),
        h3_entity(100, 4, 2),
    ]
    objects = [
        group("building", [(1, node(3, 2))]),
        group("scenery", [(100, node(4, 2))]),
    ]
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={"building": config("Interact"), "scenery": config("Environment")},
    )
    assert report["status"] == compatibility.STATUS_NOOP
    assert report["repairs"] == []
    assert report["failures"] == []
    assert report["deletedObjectIds"] == []
    assert any(100 in row["ids"] for row in result)


def test_move_onto_land_on_cell_is_not_uncovered_extra() -> None:
    # Hard (2,2) + land-on (3,2). Olden sits west and touches scenery on a west
    # overhang. East reposition may cover hard+land-on; land-on is not an
    # uncovered Olden-only blocker.
    entities = [
        h3_entity_with_land_on(
            1,
            3,
            2,
            hard_offsets={(-1, 0)},
            land_on_offsets={(0, 0)},
        ),
        h3_entity(100, 0, 2),
    ]
    objects = [
        group("building", [(1, node(1, 2))]),
        group("scenery", [(100, node(0, 2))]),
    ]
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={"building": config("Interact"), "scenery": config("Environment")},
        raise_on_failure=False,
    )
    assert report["status"] == compatibility.STATUS_APPLIED
    move = report["movedBuildings"][0]
    assert move["direction"] == "east"
    assert move["toNode"] in {node(2, 2), node(3, 2)}
    assert any(1 in row["ids"] and move["toNode"] in row["nodes"] for row in result)


def test_leaving_land_on_open_is_allowed_but_hard_blocker_is_not() -> None:
    # Two-OCC footprint covering hard (2,2) + land-on (3,2). Land-on may open;
    # hard must stay covered. (Helper-level: no GATE required for this check.)
    two_occ = {
        "tag": "Interact",
        "isInteractable": True,
        "sizeX": 2,
        "sizeZ": 1,
        "pivotX": 0,
        "pivotZ": 0,
        "canBeMirrored": False,
        "nodes": [1, 1],
    }
    entities = [
        h3_entity_with_land_on(
            1,
            3,
            2,
            hard_offsets={(-1, 0)},
            land_on_offsets={(0, 0)},
        ),
    ]
    objects = [group("building", [(1, node(2, 2))])]
    state = compatibility._State(
        objects=copy.deepcopy(objects),
        global_entities=entities,
        native_object_configs={"building": two_occ},
        layer_target_node=target_node,
        width=WIDTH,
        height=HEIGHT,
        layer_resolver=None,
    )
    building = state.instances[1]
    assert building.h3_land_on_cells == frozenset({node(3, 2)})
    assert building.h3_cells == frozenset({node(2, 2)})
    assert building.olden_cells == frozenset({node(2, 2), node(3, 2)})
    # Covers hard, opens land-on.
    west = frozenset({node(1, 2), node(2, 2)})
    assert compatibility._unpreserved_h3_blocker_cells_after_move(
        state, building, west
    ) == frozenset()
    # Opens hard → rejected.
    west2 = frozenset({node(0, 2), node(1, 2)})
    assert compatibility._unpreserved_h3_blocker_cells_after_move(
        state, building, west2
    ) == frozenset({node(2, 2)})


def test_shifted_contact_with_already_adjacent_h3_neighbor_is_ignored() -> None:
    # Building and scenery already touch in H3 (west). Olden shifts the contact
    # to the east outer face; that is not a newly adjacent object.
    entities = [h3_entity(1, 2, 2), h3_entity(100, 1, 2)]
    objects = [
        group("building", [(1, node(3, 2))]),
        group("scenery", [(100, node(4, 2))]),
    ]
    state = compatibility._State(
        objects=objects,
        global_entities=entities,
        native_object_configs={
            "building": config("Interact"),
            "scenery": config("Environment"),
        },
        layer_target_node=target_node,
        width=WIDTH,
        height=HEIGHT,
        layer_resolver=None,
    )
    issues = compatibility._unwanted_contacts(state, state.instances[1])
    assert issues == []


def test_side_touch_of_east_overhang_is_ignored() -> None:
    # Building grows east from (2,2) to (3,2). A north neighbor of the new cell
    # is not on the outer/east face, so it must not create an actionable contact.
    entities = [h3_entity(1, 2, 2), h3_entity(100, 3, 3)]
    objects = [
        group("building", [(1, node(3, 2))]),
        group("scenery", [(100, node(3, 3))]),
    ]
    state = compatibility._State(
        objects=objects,
        global_entities=entities,
        native_object_configs={
            "building": config("Interact"),
            "scenery": config("Environment"),
        },
        layer_target_node=target_node,
        width=WIDTH,
        height=HEIGHT,
        layer_resolver=None,
    )
    issues = compatibility._unwanted_contacts(state, state.instances[1])
    assert issues == []

def test_different_layers_do_not_count_as_contacts() -> None:
    entities = [
        h3_entity(1, 3, 2, layer=0),
        h3_entity(100, 4, 2, layer=1),
    ]
    objects = [
        group("building", [(1, node(3, 2))]),
        group("scenery", [(100, node(4, 2)), (101, node(5, 2))]),
    ]
    report, _result, _props = run(
        entities=entities,
        objects=objects,
        configs={"building": config("Interact"), "scenery": config("Environment")},
        layer_resolver=lambda object_node: 0 if object_node % WIDTH < 4 else 1,
    )
    assert report["status"] == compatibility.STATUS_NOOP
    assert not report["repairs"]
    assert not report["failures"]


def test_exact_scenery_clone_metadata_overrides_interact_tag() -> None:
    entities = [h3_entity(1, 2, 2)]
    objects = [group("clone", [(1, node(3, 2))])]
    clone = config("Interact")
    clone["homm3ExactFootprint"] = {
        "schema": "homm3.exact_footprint_meta.v1",
        "kind": "scenery",
    }
    report, _result, _props = run(
        entities=entities,
        objects=objects,
        configs={"clone": clone},
    )
    assert report["status"] == compatibility.STATUS_NOOP
    assert report["buildingCount"] == 0
    assert not report["failures"]


def test_synthetic_object_outside_layer_envelope_is_ignored() -> None:
    entities = [h3_entity(1, 3, 2)]
    objects = [
        group("building", [(1, node(3, 2))]),
        group("scenery", [(900, node(0, 0))]),
    ]
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={
            "building": config("Interact"),
            "scenery": config("Environment"),
        },
        layer_resolver=lambda object_node: None if object_node == node(0, 0) else 0,
    )
    assert report["status"] == compatibility.STATUS_NOOP
    assert not report["failures"]
    assert report["skippedSyntheticOutsideLayerEnvelope"] == [{
        "objectId": 900,
        "sid": "scenery",
        "node": node(0, 0),
        "reason": "synthetic_object_outside_active_layer_envelope",
    }]
    assert result == objects


def test_invalid_building_h3_footprint_fails_closed() -> None:
    invalid = h3_entity(1, 2, 2)
    invalid["templateBlockMask"] = [255]
    objects = [group("building", [(1, node(3, 2))])]
    original_objects = copy.deepcopy(objects)
    try:
        run(
            entities=[invalid],
            objects=objects,
            configs={"building": config("Interact")},
        )
    except compatibility.Homm3FootprintCompatibilityError as exc:
        assert exc.report["status"] == compatibility.STATUS_FAILED
        assert exc.report["unresolvedH3BuildingCount"] == 1
        assert any(
            failure["reason"] == "cannot_compare_invalid_H3_footprint"
            for failure in exc.report["failures"]
        )
    else:
        raise AssertionError("invalid source H3 footprint must fail closed")
    assert objects == original_objects

def test_resources_and_enemies_are_not_blockers() -> None:
    entities = [h3_entity(1, 3, 2)]
    objects = [
        group("building", [(1, node(3, 2))]),
        group("pickup", [(10, node(4, 2))]),
        group("enemy", [(11, node(3, 3))]),
    ]
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={
            "building": config("Interact"),
            "pickup": config("Artifact"),
            "enemy": config("Animals"),
        },
    )
    assert report["status"] == compatibility.STATUS_NOOP
    assert not report["repairs"]
    assert len(result) == 3


def test_functional_mine_clones_are_not_blockers() -> None:
    entities = [h3_entity(1, 3, 2)]
    objects = [
        group("building", [(1, node(3, 2))]),
        group("homm3_xfp_f_fixture", [(10, node(4, 2))]),
    ]
    mine_clone = config("Interact")
    mine_clone.update(
        {
            "id": "homm3_xfp_f_fixture",
            "homm3ExactFootprint": {
                "donorSid": "mine_wood",
                "kind": "functional",
            },
        }
    )
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={
            "building": config("Interact"),
            "homm3_xfp_f_fixture": mine_clone,
        },
    )
    assert report["status"] == compatibility.STATUS_NOOP
    assert report["buildingCount"] == 1
    assert not report["failures"]
    assert result == objects


def test_isolated_extra_native_footprint_is_diagnostic_only() -> None:
    entities = [h3_entity(1, 4, 2)]
    objects = [group("building", [(1, node(3, 2))])]
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={"building": config("Interact")},
    )
    assert report["status"] == compatibility.STATUS_NOOP
    assert not report["failures"]
    assert report["unchangedMismatches"][0]["reason"] == "no_new_cardinal_contact"
    assert result == objects


def test_unknown_interactable_tag_is_not_promoted() -> None:
    entities = [h3_entity(1, 2, 2)]
    objects = [group("custom", [(1, node(3, 2))])]
    unknown = config("Interact")
    unknown["tag"] = "FutureInteract"
    unknown["generatorConfig"] = {"buildingSizeX": 1, "buildingSizeZ": 1}
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={"custom": unknown},
    )
    assert report["status"] == compatibility.STATUS_NOOP
    assert report["buildingCount"] == 0
    assert not report["failures"]
    assert result == objects


def test_building_without_in_envelope_gate_fails_closed() -> None:
    entities = [h3_entity(1, 2, 0)]
    objects = [group("building", [(1, node(2, 0))])]
    try:
        run(
            entities=entities,
            objects=objects,
            configs={"building": config("Interact")},
        )
    except compatibility.Homm3FootprintCompatibilityError as exc:
        assert any(
            failure.get("reason") == "cannot_compare_unresolved_native_cell_footprint"
            and "native_gate_projection_unavailable" in failure.get("nativeCellUnresolved", [])
            for failure in exc.report["failures"]
        )
    else:
        raise AssertionError("a building without an in-envelope GATE must fail closed")


def test_boundary_clipping_with_gate_is_allowed() -> None:
    def truncated_target_node(_layer: int, x: int, y: int) -> int:
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT - 2):
            raise ValueError("outside active source envelope")
        return node(x, y)

    clipped_config = config("Interact")
    clipped_entity = h3_entity(1, 2, 5)
    clipped_entity["templateBlockMask"] = [255] * 6
    report, _result, _props = run(
        entities=[clipped_entity],
        objects=[group("building", [(1, node(2, 6))])],
        configs={"building": clipped_config},
        target_node_fn=truncated_target_node,
    )
    assert report["status"] == compatibility.STATUS_NOOP
    assert not report["failures"]
    assert report["unresolvedNativeCellInstanceCount"] == 0
    assert report["mismatchedBuildingCount"] == 0


def test_source_scenery_clipped_outside_active_envelope_is_known():
    def truncated_target_node(_layer: int, x: int, y: int) -> int:
        if not (0 <= x < WIDTH and 0 <= y < HEIGHT - 2):
            raise ValueError("outside active source envelope")
        return node(x, y)

    report, _result, _props = run(
        entities=[h3_entity(1, 2, 6)],
        objects=[group("scenery", [(1, node(2, 6))])],
        configs={"scenery": config("Environment")},
        target_node_fn=truncated_target_node,
    )
    assert report["status"] == compatibility.STATUS_NOOP
    assert not report["failures"]
    assert report["unresolvedH3BuildingCount"] == 0


def test_failure_is_closed_without_partial_mutation() -> None:
    # Legacy fail-closed mode: Building 1 overhangs east into another permanent
    # building. Surrounding permanent buildings block every cardinal retreat, so
    # repair must fail closed without mutating the caller's objects/properties.
    entities = [
        h3_entity(1, 2, 2),
        h3_entity(100, 4, 2),
        h3_entity(2, 2, 2),
        h3_entity(3, 3, 3),
        h3_entity(4, 3, 1),
        h3_entity(5, 1, 2),
    ]
    objects = [
        group(
            "building",
            [
                (1, node(3, 2)),
                (100, node(4, 2)),
                (2, node(2, 2)),
                (3, node(3, 3)),
                (4, node(3, 1)),
                (5, node(1, 2)),
            ],
        ),
    ]
    original_objects = copy.deepcopy(objects)
    original_properties = {"propObjects": [{"id": 100, "type": 0}]}
    properties = copy.deepcopy(original_properties)
    try:
        compatibility.apply_homm3_footprint_compatibility(
            global_entities=entities,
            objects=objects,
            object_properties=properties,
            native_object_configs={
                "building": config("Interact"),
            },
            layer_target_node=target_node,
            width=WIDTH,
            height=HEIGHT,
            map_sid="fixture",
            raise_on_failure=True,
        )
    except compatibility.Homm3FootprintCompatibilityError as exc:
        assert exc.report["status"] == compatibility.STATUS_FAILED
        assert exc.report["failures"]
    else:
        raise AssertionError("fixture must fail closed")
    assert objects == original_objects
    assert properties == original_properties


def test_fail_open_commits_successful_repairs_with_unresolved() -> None:
    # Default fail-open: one building is repaired by deleting new scenery; another
    # remains unrepairable among permanent neighbors. Successful repairs commit.
    entities = [
        # Unrepairable cluster (same geometry as fail-closed fixture).
        h3_entity(1, 2, 2),
        h3_entity(100, 4, 2),
        h3_entity(2, 2, 2),
        h3_entity(3, 3, 3),
        h3_entity(4, 3, 1),
        h3_entity(5, 1, 2),
        # Repairable: east overhang into new scenery only.
        h3_entity(200, 2, 5),
    ]
    objects = [
        group(
            "building",
            [
                (1, node(3, 2)),
                (100, node(4, 2)),
                (2, node(2, 2)),
                (3, node(3, 3)),
                (4, node(3, 1)),
                (5, node(1, 2)),
                (200, node(3, 5)),
            ],
        ),
        group("scenery", [(201, node(4, 5))]),
    ]
    report, result, _props = run(
        entities=entities,
        objects=objects,
        configs={"building": config("Interact"), "scenery": config("Environment")},
        raise_on_failure=False,
    )
    assert report["status"] == compatibility.STATUS_APPLIED_WITH_UNRESOLVED
    assert report["failures"]
    assert any(r.get("objectId") == 200 for r in report["repairs"])
    assert 201 in report["deletedObjectIds"]
    assert not any(201 in row["ids"] for row in result)


def test_functional_mine_clone_policy() -> None:
    blocks = {
        (-1, -1),
        (0, -1),
        (-3, 0),
        (-2, 0),
        (-1, 0),
        (0, 0),
    }
    visits = {(-1, 0)}
    # Helper still reports the grown grid that would fit the mask, but mine clones
    # must stay on the donor 3x3 and gap-fill overflow (resizing breaks the mesh).
    assert exact_fp.functional_clone_grid_size(
        (3, 3),
        block_offsets=blocks,
        visit_offsets=visits,
    ) == (4, 3)
    footprint = exact_fp.same_size_nodes_from_h3(
        size_x=3,
        size_z=3,
        block_offsets=blocks,
        visit_offsets=visits,
        kind="functional",
    )
    assert footprint.nodes == (0, 0, 0, 0, 1, 1, 1, 2, 1)
    assert footprint.overflow_block_count == 1
    donor = {
        "id": "mine_wood",
        "tag": "Interact",
        "isInteractable": True,
        "prefs": ["interactive/mine_wood"],
        "generatorConfig": {
            "buildingInteractionLayout": 0,
            "buildingLeftBottomX": 0,
            "buildingLeftBottomZ": 1,
            "buildingSizeX": 2,
            "buildingSizeZ": 2,
        },
        "nodes": [1, 1, 0, 1, 1, 2, 0, 2, 2],
        "sizeX": 3,
        "sizeZ": 3,
        "canBeMirrored": True,
    }
    clone = exact_fp.apply_same_size_clone(
        donor,
        donor_sid="mine_wood",
        clone_sid="homm3_xfp_f_fixture",
        footprint=footprint,
    )
    assert (clone["sizeX"], clone["sizeZ"]) == (3, 3)
    assert clone["nodes"] == list(footprint.nodes)
    assert clone["prefs"] == donor["prefs"]
    assert clone["generatorConfig"]["buildingLeftBottomX"] == 0
    assert clone["generatorConfig"]["buildingLeftBottomZ"] == 1
    assert clone["isInteractable"] is True
    assert clone["canBeMirrored"] is False
    logic_clones: list[dict[str, Any]] = []
    exact_fp._maybe_queue_logic_clone(
        donor_sid="mine_wood",
        clone_sid="homm3_xfp_f_fixture",
        logic_index={
            "mine_wood": (
                exact_fp.MINE_LOGIC_MEMBER,
                {"id": "mine_wood", "resource": "wood"},
            )
        },
        logic_clones=logic_clones,
        logic_clone_sids=set(),
    )
    assert len(logic_clones) == 1
    assert logic_clones[0]["member"] == exact_fp.MINE_LOGIC_MEMBER
    assert logic_clones[0]["row"]["id"] == "homm3_xfp_f_fixture"


def test_install_guard_preserves_objectconfig_backed_mine_logic() -> None:
    core_zip = io.BytesIO()
    with zipfile.ZipFile(core_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "DB/map/objects/homecoming_exact_footprint_objects.json",
            json.dumps({"array": [{"id": "homm3_xfp_f_valid"}]}),
        )
    core_zip.seek(0)
    overlay = {
        exact_fp.MINE_LOGIC_MEMBER: json.dumps(
            {
                "array": [
                    {"id": "mine_wood"},
                    {"id": "homm3_xfp_f_valid"},
                    {"id": "homm3_xfp_f_orphan"},
                ]
            }
        ).encode("utf-8")
    }
    with zipfile.ZipFile(core_zip, "r") as source:
        removed = map_load_preflight.scrub_orphan_xfp_logic_members(source, overlay)
    rows = json.loads(overlay[exact_fp.MINE_LOGIC_MEMBER])["array"]
    assert removed == {exact_fp.MINE_LOGIC_MEMBER: ["homm3_xfp_f_orphan"]}
    assert {row["id"] for row in rows} == {"mine_wood", "homm3_xfp_f_valid"}


def main() -> int:
    module = RAW / "homm3_footprint_compatibility.py"
    builder = RAW / "build_raw_translation_map.py"
    worker = POC / "campaign_raw_translation_batch_worker.py"
    batch = POC / "build_campaign_raw_translation_batch.py"
    preflight = ROOT / "tools" / "map_load_preflight.py"
    errors: list[str] = []
    for path in (module, builder, worker, batch):
        if not path.is_file():
            errors.append(f"missing compatibility integration file: {path}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    module_text = module.read_text(encoding="utf-8")
    builder_text = builder.read_text(encoding="utf-8")
    worker_text = worker.read_text(encoding="utf-8")
    batch_text = batch.read_text(encoding="utf-8")
    preflight_text = preflight.read_text(encoding="utf-8")
    exact_text = (POC / "exact_homm3_footprint.py").read_text(encoding="utf-8")
    required = (
        ("SCHEMA = \"olden.raw_translation.homm3_footprint_compatibility.v1\"", module_text),
        ("MINE_SIDS", exact_text),
        ("MINE_LOGIC_MEMBER", exact_text),
        ("mine_generator_config_for_gate", exact_text),
        ("functional_clone_grid_size", exact_text),
        ("functionalMineClone", exact_text),
        ("allow_size_change", exact_text),
        ("size-changing exact footprint clones are forbidden", exact_text),
        ("_maybe_queue_logic_clone", exact_text),
        ("entity_nonvisitable_block_offsets", module_text),
        ("source_visit_offsets", module_text),
        ("h3_land_on_cells", module_text),
        ("_h3_footprint_mismatched", module_text),
        ("scenery_cleanup_then_cardinal_reposition", module_text),
        ("STATUS_APPLIED_WITH_UNRESOLVED", module_text),
        ("fail-open", module_text),
        ("raise_on_failure: bool = False", module_text),
        ("Homm3FootprintCompatibilityError", module_text),
        ("native_grid_projection_out_of_bounds", module_text),
        ("native_gate_projection_unavailable", module_text),
        ("preserved_blocker_cells", module_text),
        ("Only blockers that remain in the Olden layout", module_text),
        ("unpreserved_h3_blocker_cells", module_text),
        ("unresolvedH3BlockerCells", module_text),
        ("_uncovered_extra_olden_cells_after_move", module_text),
        ("_extension_outward_contact_cells", module_text),
        ("outer face of newly emitted Olden blockers", module_text),
        ("no_new_cardinal_contact", module_text),
        ("NON_PERMANENT_EXACT_DONOR_PREFIXES", module_text),
        ("unsafeOverlapBlockers", module_text),
        ("candidateRejectionReasons", module_text),
        ("H3_blocker_cells_preserved_by_other_permanent_blocker", module_text),
        ("unresolvedH3BuildingCount", module_text),
        ("import homm3_footprint_compatibility", builder_text),
        ("layer_resolver=_atlas_layer_for_node", builder_text),
        ("STATUS_DISABLED", builder_text),
        ("candidate_only_explicit_opt_in", builder_text),
        ("--enable-homm3-footprint-compatibility", builder_text),
        ("homm3_footprint_compatibility.py", worker_text),
        ("native_footprint_model.py", worker_text),
        ("enableHomm3FootprintCompatibility", worker_text),
        ("--enable-homm3-footprint-compatibility", batch_text),
        ("_effective_object_config_ids", preflight_text),
        ("scrub_orphan_xfp_logic_members", preflight_text),
        ("sid not in object_config_ids", preflight_text),
    )
    for token, text in required:
        if token not in text:
            errors.append(f"missing contract token {token!r}")
    if not callable(getattr(surface_emit_module, "reset_exact_logic_clone_rows", None)):
        errors.append("exact footprint logic overlay reset helper is missing")
    supported_property_sids = set(surface_emit_module.SUPPORTED_LIVE_PROPERTY_SIDS)
    entity_sids = set(surface_emit_module.ENTITY_SIDS)
    for mine_sid in sorted(exact_fp.MINE_SIDS):
        if mine_sid not in supported_property_sids or mine_sid not in entity_sids:
            errors.append(f"mine property allowlist is incomplete for {mine_sid!r}")
    if errors:
        for error in errors:
            print(f"FAIL: {error}")
        return 1
    test_new_scenery_is_deleted_first()
    test_unique_scenery_is_preserved_and_building_moves()
    test_unique_scenery_can_be_removed_when_other_blocker_covers_it()
    test_final_blocker_parity_delta_detects_extra_and_missing_cells()
    test_scenery_deletion_requires_remaining_olden_coverage()
    test_building_move_preserves_former_h3_blocker_cells()
    test_building_can_dig_into_existing_scenery()
    test_minimal_scenery_cleanup_then_move()
    test_scenery_cleanup_can_cull_multiple_to_support_reposition()
    test_two_tile_reposition_is_allowed()
    test_land_on_cell_occupied_is_not_overhang()
    test_move_onto_land_on_cell_is_not_uncovered_extra()
    test_leaving_land_on_open_is_allowed_but_hard_blocker_is_not()
    test_shifted_contact_with_already_adjacent_h3_neighbor_is_ignored()
    test_side_touch_of_east_overhang_is_ignored()
    test_different_layers_do_not_count_as_contacts()
    test_exact_scenery_clone_metadata_overrides_interact_tag()
    test_synthetic_object_outside_layer_envelope_is_ignored()
    test_invalid_building_h3_footprint_fails_closed()
    test_resources_and_enemies_are_not_blockers()
    test_functional_mine_clones_are_not_blockers()
    test_isolated_extra_native_footprint_is_diagnostic_only()
    test_unknown_interactable_tag_is_not_promoted()
    test_building_without_in_envelope_gate_fails_closed()
    test_boundary_clipping_with_gate_is_allowed()
    test_source_scenery_clipped_outside_active_envelope_is_known()
    test_failure_is_closed_without_partial_mutation()
    test_fail_open_commits_successful_repairs_with_unresolved()
    test_functional_mine_clone_policy()
    test_install_guard_preserves_objectconfig_backed_mine_logic()
    print("HoMM3 footprint compatibility contract: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
