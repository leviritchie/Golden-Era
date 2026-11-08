#!/usr/bin/env python3
"""Regression coverage for permanent native building anchors versus pickups."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
APPROACH = POC / "approach_cell"
for path in (POC, APPROACH):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import exact_homm3_footprint as exact_fp  # noqa: E402
import surface_emit as surface  # noqa: E402


def _ring_config(*, tag: str, generator: bool) -> dict:
    row = {
        "id": "test_ring",
        "tag": tag,
        "isInteractable": True,
        "sizeX": 3,
        "sizeZ": 3,
        "pivotX": 1,
        "pivotZ": 1,
        "nodes": [2, 2, 2, 2, 1, 2, 2, 2, 2],
        "canBeMirrored": True,
        "flippedOffset": 0,
    }
    if generator:
        row["generatorConfig"] = {
            "buildingInteractionLayout": 3,
            "buildingLeftBottomX": 1,
            "buildingLeftBottomZ": 1,
            "buildingSizeX": 1,
            "buildingSizeZ": 1,
        }
    return row


def _watchtower_entity() -> dict:
    return {
        "sourceKey": "0:35:48",
        "sourceX": 35,
        "sourceY": 48,
        "templateVisitMask": [0, 0, 0, 0, 0, 64],
        "templateBlockMask": [255, 255, 255, 255, 255, 191],
    }


class NativeBuildingAnchorPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        # Raw translation places the surface and underground layers side by
        # side in a 160x80 atlas; keep these tests in that node coordinate
        # system rather than surface_emit's standalone 80x80 defaults.
        self._surface_projection_state = (
            surface.OLDEN_WIDTH,
            surface.OLDEN_HEIGHT,
            surface.SOURCE_OFFSET_X,
            surface.SOURCE_OFFSET_Y,
        )
        surface.OLDEN_WIDTH = 160
        surface.OLDEN_HEIGHT = 80
        surface.SOURCE_OFFSET_X = 4
        surface.SOURCE_OFFSET_Y = 4

    def tearDown(self) -> None:
        (
            surface.OLDEN_WIDTH,
            surface.OLDEN_HEIGHT,
            surface.SOURCE_OFFSET_X,
            surface.SOURCE_OFFSET_Y,
        ) = self._surface_projection_state

    def test_ring_shape_is_not_placement_semantics(self) -> None:
        building = _ring_config(tag="Interact", generator=True)
        pickup = _ring_config(tag="Resource", generator=False)

        self.assertEqual(exact_fp.classify_object_config_shape(building, "watchtower"), "gate_ring")
        self.assertEqual(exact_fp.classify_object_config_shape(pickup, "resource_gold"), "gate_ring")
        self.assertTrue(exact_fp.uses_native_building_anchor_policy(building))
        self.assertFalse(exact_fp.uses_native_building_anchor_policy(pickup))
        self.assertFalse(
            exact_fp.uses_native_building_anchor_policy(
                _ring_config(tag="Environment", generator=False)
            )
        )
        for tag in ("Artifact", "meta", "Army"):
            self.assertFalse(
                exact_fp.uses_native_building_anchor_policy(
                    _ring_config(tag=tag, generator=False)
                )
            )
        self.assertFalse(
            exact_fp.uses_native_building_anchor_policy(
                _ring_config(tag="Interact", generator=False)
            )
        )

    def test_native_projection_fails_closed_on_unresolved_rotation(self) -> None:
        with self.assertRaisesRegex(ValueError, "rotation_semantics_unresolved"):
            surface.occupied_nodes_for_object_instance(
                "watchtower",
                _ring_config(tag="Interact", generator=True),
                4359,
                9,
            )

    def test_native_projection_uses_native_zero_for_missing_pivot(self) -> None:
        config = _ring_config(tag="Interact", generator=True)
        config.pop("pivotX")

        occupied = surface.occupied_nodes_for_object_instance(
            "watchtower",
            config,
            4359,
            0,
        )

        self.assertEqual(occupied, {4360})

    def test_native_projection_fails_closed_on_missing_nodes(self) -> None:
        config = _ring_config(tag="Interact", generator=True)
        config.pop("nodes")
        with self.assertRaisesRegex(ValueError, "nodes_grid_shape_invalid"):
            surface.occupied_nodes_for_object_instance(
                "watchtower",
                config,
                4359,
                0,
            )

    def test_native_projection_uses_native_zero_for_missing_flipped_offset(self) -> None:
        config = _ring_config(tag="Interact", generator=True)
        config.pop("flippedOffset")

        occupied = surface.occupied_nodes_for_object_instance(
            "prison", config, 4359, 10
        )

        self.assertEqual(occupied, {4358})

    def test_watchtower_keeps_homm3_source_anchor(self) -> None:
        node, evidence = surface.derive_source_anchor_node(
            _watchtower_entity(),
            "watchtower",
            _ring_config(tag="Interact", generator=True),
            4359,
            rotation=10,
        )

        self.assertEqual(node, 4359)
        self.assertEqual(evidence["decision"], "preserve_h3_source_anchor_for_native_building")
        self.assertNotEqual(evidence["decision"], "emit_node_equals_h3_visit_gate_marker")

    def test_watchtower_native_pivot_projects_h3_blocker_cell(self) -> None:
        config = _ring_config(tag="Interact", generator=True)
        occupied = surface.occupied_nodes_for_object_instance("watchtower", config, 4359, 10)
        gates = surface.gate_nodes_for_object_instance("watchtower", config, 4359, 10)

        self.assertEqual(occupied, {4358})
        self.assertNotIn(4358, gates)
        self.assertEqual(len(gates), 8)

    def test_resource_ring_retains_pickup_policy(self) -> None:
        node, evidence = surface.derive_source_anchor_node(
            _watchtower_entity(),
            "resource_gold",
            _ring_config(tag="Resource", generator=False),
            4359,
            rotation=0,
        )

        self.assertEqual(node, 4358)
        self.assertEqual(evidence["decision"], "emit_node_equals_h3_visit_gate_marker")
        resource_occupied = surface.occupied_nodes_for_object_instance(
            "resource_gold",
            _ring_config(tag="Resource", generator=False),
            4358,
            10,
        )
        self.assertEqual(resource_occupied, {4519})

    def test_native_projection_handles_mirrored_stables_shape(self) -> None:
        config = {
            "id": "stables",
            "tag": "Interact",
            "isInteractable": True,
            "sizeX": 3,
            "sizeZ": 3,
            "pivotX": 1,
            "pivotZ": 0,
            "nodes": [0, 1, 1, 2, 1, 1, 2, 2, 0],
            "canBeMirrored": True,
            "flippedOffset": 1,
            "offsetX": 0.5,
            "offsetZ": 0.45,
            "pathLineStopRadius": None,
            "generatorConfig": {
                "buildingInteractionLayout": 1,
                "buildingLeftBottomX": 1,
                "buildingLeftBottomZ": 1,
                "buildingSizeX": 2,
                "buildingSizeZ": 2,
            },
        }

        occupied = surface.occupied_nodes_for_object_instance("stables", config, 1965, 10)

        self.assertEqual(occupied, {1805, 1806, 1965, 1966})

    def test_native_anchor_fails_closed_when_all_gates_clip(self) -> None:
        config = _ring_config(tag="Interact", generator=True)
        config["pivotX"] = 3
        edge_anchor = 40 * surface.OLDEN_WIDTH + 4

        with self.assertRaisesRegex(ValueError, "no in-envelope native GATE"):
            surface.derive_native_building_anchor_node(
                {"sourceKey": "edge"},
                "watchtower",
                config,
                edge_anchor,
                rotation=0,
            )
    def test_native_projection_clips_outside_active_source_envelope(self) -> None:
        config = _ring_config(tag="Interact", generator=True)
        config["pivotX"] = 0
        config["nodes"] = [2, 2, 1, 2, 2, 2, 2, 2, 2]
        edge_anchor = 40 * surface.OLDEN_WIDTH + 75

        occupied = surface.occupied_nodes_for_object_instance(
            "watchtower", config, edge_anchor, 0
        )
        gates = surface.gate_nodes_for_object_instance(
            "watchtower", config, edge_anchor, 0
        )

        self.assertEqual(occupied, set())
        self.assertTrue(all(surface.is_node_in_source_envelope(node) for node in gates))


if __name__ == "__main__":
    unittest.main()
