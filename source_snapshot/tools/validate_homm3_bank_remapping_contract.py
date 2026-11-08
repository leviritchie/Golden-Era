#!/usr/bin/env python3
"""Validate the isolated HoMM3 bank remapping pass (source/static + fixtures)."""

from __future__ import annotations

import copy
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
RAW = POC / "raw_translation"
for path in (POC, RAW):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import homm3_bank_remapping as bank_remap  # noqa: E402


WIDTH = 12
HEIGHT = 12


def node(x: int, y: int) -> int:
    return y * WIDTH + x


def layer_target_node(_layer: int, x: int, y: int) -> int:
    if not (0 <= x < WIDTH and 0 <= y < HEIGHT):
        raise ValueError(f"out of bounds {x},{y}")
    return node(x, y)


def h3_block_mask_for_offsets(offsets: set[tuple[int, int]]) -> list[int]:
    """Build H3M block mask (clear bits = blocked) for BR-relative offsets."""
    anchor_x, anchor_y = 7, 5
    rows = [255] * 6
    for dx, dy in offsets:
        col = anchor_x + dx
        row = anchor_y + dy
        if not (0 <= col < 8 and 0 <= row < 6):
            raise ValueError(f"fixture offset outside H3 mask: {(dx, dy)}")
        rows[row] &= ~(1 << col)
    return rows


def h3_visit_mask_for_offsets(offsets: set[tuple[int, int]]) -> list[int]:
    """Build H3M visit mask (set bits = visit) for BR-relative offsets."""
    anchor_x, anchor_y = 7, 5
    rows = [0] * 6
    for dx, dy in offsets:
        col = anchor_x + dx
        row = anchor_y + dy
        if not (0 <= col < 8 and 0 <= row < 6):
            raise ValueError(f"fixture offset outside H3 mask: {(dx, dy)}")
        rows[row] |= 1 << col
    return rows


def config_1x1_block() -> dict[str, Any]:
    return {
        "id": "abandoned_mansion",
        "tag": "Interact",
        "isInteractable": True,
        "sizeX": 2,
        "sizeZ": 2,
        "pivotX": 0,
        "pivotZ": 0,
        "nodes": [1, 2, 2, 2],
        "generatorConfig": {"buildingSizeX": 1, "buildingSizeZ": 1},
    }


def config_dense_bank(sid: str = "shady_den") -> dict[str, Any]:
    return {
        "id": sid,
        "tag": "Interact",
        "isInteractable": True,
        "sizeX": 3,
        "sizeZ": 3,
        "pivotX": 2,
        "pivotZ": 0,
        "nodes": [0, 1, 1, 2, 1, 1, 2, 2, 0],
        "generatorConfig": {"buildingSizeX": 2, "buildingSizeZ": 2},
    }


def config_watchtower() -> dict[str, Any]:
    return {
        "id": "watchtower",
        "tag": "Interact",
        "isInteractable": True,
        "sizeX": 2,
        "sizeZ": 2,
        "pivotX": 0,
        "pivotZ": 0,
        "nodes": [1, 2, 2, 2],
        "generatorConfig": {"buildingSizeX": 1, "buildingSizeZ": 1},
    }


def bank_entity(
    *,
    source_index: int,
    animation: str,
    template_object_id: int,
    x: int,
    y: int,
    block_offsets: set[tuple[int, int]],
    visit_offsets: set[tuple[int, int]],
    subtype: int = 0,
) -> dict[str, Any]:
    return {
        "sourceIndex": source_index,
        "sourceX": x,
        "sourceY": y,
        "sourceLayer": 0,
        "templateObjectId": template_object_id,
        "templateAnimation": animation,
        "templateSubtype": subtype,
        "templateBlockMask": h3_block_mask_for_offsets(block_offsets | visit_offsets),
        "templateVisitMask": h3_visit_mask_for_offsets(visit_offsets),
    }


def group(sid: str, rows: list[tuple[int, int]]) -> dict[str, Any]:
    return {
        "sid": sid,
        "ids": [object_id for object_id, _ in rows],
        "nodes": [object_node for _, object_node in rows],
        "rotations": [0] * len(rows),
        "levels": [0] * len(rows),
    }


def test_known_bank_families_are_intentional() -> None:
    expected = {
        "avxbnk10.def",
        "avxbnk20.def",
        "avxbnk30.def",
        "avxbnk40.def",
        "avxbnk50.def",
        "avxbnk60.def",
        "avxbnk70.def",
        "avxbnk80.def",
        "avxbnk90.def",
        "avxdent.def",
    }
    missing = expected - set(bank_remap.BANK_FAMILIES)
    if missing:
        raise AssertionError(f"missing intentional bank families: {sorted(missing)}")
    griffin = bank_remap.resolve_bank_family(
        template_object_id=16,
        template_animation="AVXbnk30.def",
    )
    if griffin is None or griffin["function"] != bank_remap.FUNCTION_UNIT_BANK:
        raise AssertionError("Griffin Conservatory must resolve to unit-bank function")
    den = bank_remap.resolve_bank_family(
        template_object_id=97,
        template_animation="AVXdent.def",
    )
    if den is None or den["function"] != bank_remap.FUNCTION_SCOUTING:
        raise AssertionError("Den of Thieves must resolve to scouting function")
    if bank_remap.resolve_bank_family(template_object_id=16, template_animation="nope.def"):
        raise AssertionError("unknown animation must not resolve")


def test_object_16_variants_are_not_collapsed_in_catalog() -> None:
    families = {
        bank_remap.BANK_FAMILIES[key]["familyId"]
        for key in bank_remap.BANK_FAMILIES
        if key.startswith("avxbnk")
    }
    if len(families) < 9:
        raise AssertionError(f"object-16 families collapsed: {sorted(families)}")


def test_geometry_valid_native_assignment_rewrites_sid() -> None:
    configs = {
        "abandoned_mansion": config_1x1_block(),
        "black_tower": {**config_1x1_block(), "id": "black_tower"},
        "mereas_shrine": {**config_1x1_block(), "id": "mereas_shrine"},
        "shady_den": config_dense_bank("shady_den"),
    }
    for sid in bank_remap.RESOURCE_BANK_CANDIDATES:
        configs.setdefault(sid, config_dense_bank(sid) if sid not in configs else configs[sid])
        configs[sid] = {**configs[sid], "id": sid}
    for sid in bank_remap.UNIT_BANK_CANDIDATES:
        configs.setdefault(sid, config_dense_bank(sid))
        configs[sid] = {**configs[sid], "id": sid}
    for sid in bank_remap.SCOUTING_CANDIDATES:
        configs.setdefault(sid, config_watchtower())
        configs[sid] = {**configs[sid], "id": sid}

    # One-cell nonvisitable blocker at the source anchor matches abandoned_mansion.
    entities = [
        bank_entity(
            source_index=10,
            animation="AVXbnk10.def",
            template_object_id=16,
            x=4,
            y=4,
            block_offsets={(0, 0), (-1, 0)},
            visit_offsets={(-1, 0)},
        )
    ]
    objects = [group("shady_den", [(10, node(4, 4))])]
    original = copy.deepcopy(objects)
    report = bank_remap.apply_homm3_bank_remapping(
        global_entities=entities,
        objects=objects,
        native_object_configs=configs,
        layer_target_node=layer_target_node,
        width=WIDTH,
        height=HEIGHT,
        map_sid="fixture_bank",
    )
    if report["status"] != bank_remap.STATUS_APPLIED:
        raise AssertionError(f"expected applied remap, got {report}")
    selected = report["assignments"][0]["selectedSid"]
    if selected not in {"abandoned_mansion", "black_tower", "mereas_shrine"}:
        raise AssertionError(f"expected compact resource bank, got {selected}")
    if any(group["sid"] == "shady_den" and 10 in group["ids"] for group in objects):
        raise AssertionError("placement remained on shady_den")
    if original == objects:
        raise AssertionError("objects were not rewritten")


def test_den_of_thieves_never_uses_resource_bank() -> None:
    configs = {
        sid: {**config_1x1_block(), "id": sid}
        for sid in bank_remap.RESOURCE_BANK_CANDIDATES
    }
    configs["watchtower"] = config_watchtower()
    for sid in bank_remap.UNIT_BANK_CANDIDATES:
        configs[sid] = {**config_dense_bank(sid), "id": sid}

    entities = [
        bank_entity(
            source_index=20,
            animation="AVXdent.def",
            template_object_id=97,
            x=5,
            y=5,
            block_offsets={(-1, 0), (0, 0)},
            visit_offsets={(0, 0)},
        )
    ]
    # Emit currently parks Den of Thieves as shady_den on the H3 source anchor.
    # Remapping must re-anchor the single-OCC watchtower onto the nonvisitable cell.
    objects = [group("shady_den", [(20, node(5, 5))])]
    report = bank_remap.apply_homm3_bank_remapping(
        global_entities=entities,
        objects=objects,
        native_object_configs=configs,
        layer_target_node=layer_target_node,
        width=WIDTH,
        height=HEIGHT,
        map_sid="fixture_den",
    )
    if report["status"] != bank_remap.STATUS_APPLIED:
        raise AssertionError(f"den remap failed: {report}")
    assignment = report["assignments"][0]
    if assignment["selectedSid"] != "watchtower":
        raise AssertionError(f"den must map to watchtower, got {assignment}")
    if assignment["sourceFunction"] != bank_remap.FUNCTION_SCOUTING:
        raise AssertionError("den function must remain scouting")
    if assignment["selectedSid"] in bank_remap.RESOURCE_BANK_CANDIDATES:
        raise AssertionError("den must not use guarded-resource-bank logic")


def test_fail_closed_without_shady_den_fallback() -> None:
    # Dense source mask that no native 1-OCC candidate covers without extras.
    configs = {
        sid: {**config_dense_bank(sid), "id": sid}
        for sid in (
            set(bank_remap.RESOURCE_BANK_CANDIDATES)
            | set(bank_remap.UNIT_BANK_CANDIDATES)
            | set(bank_remap.SCOUTING_CANDIDATES)
        )
    }
    configs["abandoned_mansion"] = config_1x1_block()
    configs["black_tower"] = {**config_1x1_block(), "id": "black_tower"}
    configs["mereas_shrine"] = {**config_1x1_block(), "id": "mereas_shrine"}
    configs["watchtower"] = config_watchtower()

    entities = [
        bank_entity(
            source_index=30,
            animation="AVXbnk20.def",
            template_object_id=16,
            x=6,
            y=6,
            block_offsets={(-2, 0), (-1, 0), (0, 0)},
            visit_offsets={(-1, 0)},
        )
    ]
    objects = [group("shady_den", [(30, node(6, 6))])]
    try:
        bank_remap.apply_homm3_bank_remapping(
            global_entities=entities,
            objects=objects,
            native_object_configs=configs,
            layer_target_node=layer_target_node,
            width=WIDTH,
            height=HEIGHT,
            map_sid="fixture_fail",
        )
        raise AssertionError("expected fail-closed error")
    except bank_remap.Homm3BankRemappingError as exc:
        report = exc.report
    if report["status"] != bank_remap.STATUS_FAILED:
        raise AssertionError(report)
    if objects[0]["sid"] != "shady_den" or objects[0]["ids"] != [30]:
        raise AssertionError("failed pass must not rewrite objects")
    failure = report["failures"][0]
    if failure.get("reason") != "no_geometry_valid_native_candidate":
        raise AssertionError(failure)
    if "shady_den" in failure.get("reason", ""):
        raise AssertionError("must not mention shady_den as fallback")


def test_least_used_is_deterministic() -> None:
    configs = {
        sid: {**config_1x1_block(), "id": sid}
        for sid in bank_remap.RESOURCE_BANK_CANDIDATES
    }
    for sid in bank_remap.UNIT_BANK_CANDIDATES:
        configs[sid] = {**config_dense_bank(sid), "id": sid}
    for sid in bank_remap.SCOUTING_CANDIDATES:
        configs[sid] = config_watchtower()

    entities = [
        bank_entity(
            source_index=i,
            animation="AVXbnk10.def",
            template_object_id=16,
            x=3 + i,
            y=3,
            block_offsets={(0, 0), (-1, 0)},
            visit_offsets={(-1, 0)},
        )
        for i in (1, 2, 3)
    ]
    objects = [
        group(
            "shady_den",
            [(1, node(4, 3)), (2, node(5, 3)), (3, node(6, 3))],
        )
    ]
    report_a = bank_remap.apply_homm3_bank_remapping(
        global_entities=entities,
        objects=copy.deepcopy(objects),
        native_object_configs=copy.deepcopy(configs),
        layer_target_node=layer_target_node,
        width=WIDTH,
        height=HEIGHT,
        map_sid="det_a",
    )
    report_b = bank_remap.apply_homm3_bank_remapping(
        global_entities=entities,
        objects=copy.deepcopy(objects),
        native_object_configs=copy.deepcopy(configs),
        layer_target_node=layer_target_node,
        width=WIDTH,
        height=HEIGHT,
        map_sid="det_b",
    )
    selected_a = [row["selectedSid"] for row in report_a["assignments"]]
    selected_b = [row["selectedSid"] for row in report_b["assignments"]]
    if selected_a != selected_b:
        raise AssertionError(f"non-deterministic assignment: {selected_a} vs {selected_b}")
    # Three equal 2x2 candidates should spread rather than all one SID when possible.
    if len(set(selected_a)) < 2:
        raise AssertionError(f"expected least-used diversification, got {selected_a}")


def main() -> int:
    tests = [
        test_known_bank_families_are_intentional,
        test_object_16_variants_are_not_collapsed_in_catalog,
        test_geometry_valid_native_assignment_rewrites_sid,
        test_den_of_thieves_never_uses_resource_bank,
        test_fail_closed_without_shady_den_fallback,
        test_least_used_is_deterministic,
    ]
    for test in tests:
        test()
        print(f"ok {test.__name__}")
    print(f"homm3 bank remapping contract: {len(tests)} checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
