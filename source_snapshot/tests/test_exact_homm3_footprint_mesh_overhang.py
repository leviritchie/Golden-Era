#!/usr/bin/env python3
"""Generator fail-closed: scenery same-size clones must not mesh-overhang."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
for path in (POC, POC / "approach_cell"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import exact_homm3_footprint as exact_fp  # noqa: E402
import build_homecoming_entity_substitution_map as sub_mod  # noqa: E402


def _dirt_rock_config() -> dict:
    return {
        "id": "dirt_rock_1",
        "sizeX": 2,
        "sizeZ": 2,
        "nodes": [1, 1, 1, 1],
        "prefs": ["environment/dirt_rock_1"],
    }


def _rocks_1_config() -> dict:
    return {"id": "rocks_1", "sizeX": 1, "sizeZ": 1, "nodes": [1]}


class MeshOverhangFootprintTests(unittest.TestCase):
    def test_partial_nodes_are_mesh_overhang(self) -> None:
        footprint = exact_fp.SameSizeFootprint(
            size_x=2,
            size_z=2,
            nodes=(0, 0, 1, 1),
            gate_config_x=None,
            gate_config_z=None,
            in_grid_block_count=2,
            overflow_block_count=0,
            kind="scenery",
        )
        self.assertTrue(exact_fp.scenery_clone_has_mesh_overhang(footprint))

    def test_solid_fill_is_not_mesh_overhang(self) -> None:
        footprint = exact_fp.SameSizeFootprint(
            size_x=2,
            size_z=2,
            nodes=(1, 1, 1, 1),
            gate_config_x=None,
            gate_config_z=None,
            in_grid_block_count=4,
            overflow_block_count=0,
            kind="scenery",
        )
        self.assertFalse(exact_fp.scenery_clone_has_mesh_overhang(footprint))

    def test_apply_same_size_clone_refuses_overhang(self) -> None:
        footprint = exact_fp.same_size_nodes_from_h3(
            size_x=2,
            size_z=2,
            block_offsets={(-1, 0), (0, 0)},
            visit_offsets=set(),
            kind="scenery",
        )
        self.assertEqual(footprint.nodes, (0, 0, 1, 1))
        with self.assertRaises(ValueError) as ctx:
            exact_fp.apply_same_size_clone(
                _dirt_rock_config(),
                donor_sid="dirt_rock_1",
                clone_sid="homm3_xfp_s_test",
                footprint=footprint,
            )
        self.assertIn("mesh overhang", str(ctx.exception))

    def test_two_cell_rock_prefers_rocks_1_not_clone(self) -> None:
        configs = {
            "dirt_rock_1": _dirt_rock_config(),
            "rocks_1": _rocks_1_config(),
        }
        entities = [
            {
                "sourceIndex": 1,
                "sourceKey": "0:41:62",
                "category": "payloadless_object_unclassified_for_current_scope",
                "templateAnimation": "AvLRD02.def",
            }
        ]

        def resolve_donor(_entity: dict) -> str:
            return "dirt_rock_1"

        def block_offsets(_entity: dict) -> set[tuple[int, int]]:
            return {(-1, 0), (0, 0)}

        registry = exact_fp.build_exact_footprint_registry(
            entities,
            resolve_donor=resolve_donor,
            block_offsets_for=block_offsets,
            visit_offsets_for=lambda _e: set(),
            configs=configs,
            core_zip_path="unused",
            in_source_bounds=lambda _e: True,
        )
        entry = registry.by_source_index[1]
        self.assertEqual(entry.action, "catalog_match")
        self.assertEqual(entry.result_sid, "rocks_1")
        self.assertEqual(registry.stats.get("sceneryClone"), 0)
        self.assertFalse(any(sid.startswith("homm3_xfp_") for sid in registry.clone_rows))

    def test_ensure_rock_forces_rocks_1(self) -> None:
        sid = sub_mod.ensure_rock_sid_fits_homm3_block_mask(
            "dirt_rock_1",
            {(-1, 0), (0, 0)},
            {"rocks_1", "dirt_rock_1"},
        )
        self.assertEqual(sid, "rocks_1")

    def test_pool_overhang_forces_1x1_primary(self) -> None:
        configs = {
            "pool_dirt_small_1": {
                "id": "pool_dirt_small_1",
                "sizeX": 2,
                "sizeZ": 2,
                "nodes": [1, 1, 1, 1],
                "prefs": ["environment/pool_dirt_small_1"],
            },
            "mountain_dirt_small_1": {
                "id": "mountain_dirt_small_1",
                "sizeX": 1,
                "sizeZ": 1,
                "nodes": [1],
            },
        }
        # AVLoc3d0 is Outcropping (rock). A mis-sub to pool_dirt_small_1 must not
        # emit a sparsened 2x2 pool clone over H3-open road cells; overhang fail-closed
        # picks a 1x1 primary (mountain_dirt_small_1 / rocks_*).
        entities = [
            {
                "sourceIndex": 7,
                "sourceKey": "0:10:10",
                "category": "payloadless_object_unclassified_for_current_scope",
                "templateAnimation": "AVLoc3d0.def",
            }
        ]
        registry = exact_fp.build_exact_footprint_registry(
            entities,
            resolve_donor=lambda _e: "pool_dirt_small_1",
            block_offsets_for=lambda _e: {(-1, 0), (0, 0)},
            visit_offsets_for=lambda _e: set(),
            configs=configs,
            core_zip_path="unused",
            in_source_bounds=lambda _e: True,
        )
        entry = registry.by_source_index[7]
        self.assertEqual(entry.action, "catalog_match")
        self.assertEqual(entry.result_sid, "mountain_dirt_small_1")
        self.assertEqual(registry.stats.get("sceneryClone"), 0)


if __name__ == "__main__":
    unittest.main()
