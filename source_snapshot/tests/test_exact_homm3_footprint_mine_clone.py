#!/usr/bin/env python3
"""Focused tests for functional HoMM3-footprint mine clones."""

from __future__ import annotations

import json
import io
import sys
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))
sys.path.insert(0, str(ROOT / "tools"))

import exact_homm3_footprint as exact_fp  # noqa: E402
sys.path.insert(0, str(POC / "approach_cell"))
import surface_emit as surface_emit_module  # noqa: E402
import map_load_preflight  # noqa: E402


WOOD_BLOCKS = {
    (-1, -1),
    (0, -1),
    (-3, 0),
    (-2, 0),
    (-1, 0),
    (0, 0),
}
WOOD_VISIT = {(-1, 0)}


def mine_wood_config() -> dict:
    return {
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
        "pivotX": 0,
        "pivotZ": 0,
        "selectionUiPrefabID": "2x2",
    }


class MineCloneTests(unittest.TestCase):
    def test_wood_mask_stays_on_donor_grid_and_overflows(self) -> None:
        # Wood's H3 mask is wider than the native 3x3 once GATE-aligned; overflow
        # is sealed by gap-fill instead of resizing the ObjectConfig (mesh break).
        self.assertEqual(
            exact_fp.functional_clone_grid_size(
                (3, 3),
                block_offsets=WOOD_BLOCKS,
                visit_offsets=WOOD_VISIT,
            ),
            (4, 3),
        )
        footprint = exact_fp.same_size_nodes_from_h3(
            size_x=3,
            size_z=3,
            block_offsets=WOOD_BLOCKS,
            visit_offsets=WOOD_VISIT,
            kind="functional",
        )
        self.assertEqual(footprint.nodes, (0, 0, 0, 0, 1, 1, 1, 2, 1))
        self.assertEqual(footprint.gate_config_x, 1)
        self.assertEqual(footprint.gate_config_z, 2)
        self.assertEqual(footprint.in_grid_block_count, 4)
        self.assertEqual(footprint.overflow_block_count, 1)

    def test_mine_clone_syncs_generator_to_gate_without_resize(self) -> None:
        footprint = exact_fp.same_size_nodes_from_h3(
            size_x=3,
            size_z=3,
            block_offsets=WOOD_BLOCKS,
            visit_offsets=WOOD_VISIT,
            kind="functional",
        )
        clone = exact_fp.apply_same_size_clone(
            mine_wood_config(),
            donor_sid="mine_wood",
            clone_sid="homm3_xfp_f_test",
            footprint=footprint,
        )
        self.assertEqual(clone["id"], "homm3_xfp_f_test")
        self.assertEqual((clone["sizeX"], clone["sizeZ"]), (3, 3))
        self.assertEqual(clone["nodes"], list(footprint.nodes))
        self.assertFalse(clone["canBeMirrored"])
        self.assertEqual(
            clone["generatorConfig"],
            {
                "buildingInteractionLayout": 0,
                "buildingLeftBottomX": 0,
                "buildingLeftBottomZ": 1,
                "buildingSizeX": 2,
                "buildingSizeZ": 2,
            },
        )
        for key in ("tag", "isInteractable", "prefs", "pivotX", "pivotZ", "selectionUiPrefabID"):
            self.assertEqual(clone[key], mine_wood_config()[key])
        self.assertEqual(clone[exact_fp.META_KEY]["donorSid"], "mine_wood")

    def test_size_change_is_forbidden(self) -> None:
        footprint = exact_fp.SameSizeFootprint(
            size_x=4,
            size_z=3,
            nodes=(0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 1),
            gate_config_x=2,
            gate_config_z=2,
            in_grid_block_count=5,
            overflow_block_count=0,
            kind="functional",
        )
        with self.assertRaises(ValueError):
            exact_fp.apply_same_size_clone(
                mine_wood_config(),
                donor_sid="mine_wood",
                clone_sid="homm3_xfp_f_resized",
                footprint=footprint,
                allow_size_change=True,
            )

    def test_size_change_is_not_available_to_scenery(self) -> None:
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
        with self.assertRaises(ValueError):
            exact_fp.apply_same_size_clone(
                {
                    "id": "dirt_rock_1",
                    "sizeX": 1,
                    "sizeZ": 1,
                    "nodes": [1],
                },
                donor_sid="dirt_rock_1",
                clone_sid="homm3_xfp_s_test",
                footprint=footprint,
                allow_size_change=True,
            )

    def test_registry_clones_mine_object_and_logic_rows(self) -> None:
        entity = {
            "sourceIndex": 1,
            "sourceKey": "0:20:20",
            "category": "native_interactable",
        }
        core_zip = io.BytesIO()
        with zipfile.ZipFile(core_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                exact_fp.MINE_LOGIC_MEMBER,
                json.dumps({"array": [{"id": "mine_wood", "resource": "wood", "value": 2}]}),
            )
        core_zip.seek(0)
        registry = exact_fp.build_exact_footprint_registry(
            [entity],
            resolve_donor=lambda _entity: "mine_wood",
            block_offsets_for=lambda _entity: set(WOOD_BLOCKS),
            visit_offsets_for=lambda _entity: set(WOOD_VISIT),
            configs={"mine_wood": mine_wood_config()},
            core_zip_path=core_zip,
            in_source_bounds=lambda _entity: True,
        )
        self.assertEqual(registry.stats["functionalMineClone"], 1)
        self.assertEqual(registry.stats["functionalSameSizeClone"], 1)
        self.assertEqual(len(registry.clone_rows), 1)
        self.assertEqual(len(registry.logic_clones), 1)
        clone_sid = next(iter(registry.clone_rows))
        self.assertEqual(registry.clone_rows[clone_sid]["sizeX"], 3)
        self.assertEqual(registry.clone_rows[clone_sid]["sizeZ"], 3)
        self.assertEqual(
            registry.clone_rows[clone_sid]["generatorConfig"]["buildingLeftBottomX"],
            0,
        )
        self.assertEqual(
            registry.clone_rows[clone_sid]["generatorConfig"]["buildingLeftBottomZ"],
            1,
        )
        self.assertEqual(registry.clone_rows[clone_sid][exact_fp.META_KEY]["donorSid"], "mine_wood")
        self.assertEqual(registry.clone_rows[clone_sid][exact_fp.META_KEY]["overflowBlockCount"], 1)
        logic_clone = registry.logic_clones[0]
        self.assertEqual(logic_clone["member"], exact_fp.MINE_LOGIC_MEMBER)
        self.assertEqual(logic_clone["donorSid"], "mine_wood")
        self.assertEqual(logic_clone["cloneSid"], clone_sid)
        self.assertEqual(logic_clone["row"]["resource"], "wood")


    def test_loader_guard_keeps_objectconfig_backed_mine_logic(self) -> None:
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
        self.assertEqual(removed, {exact_fp.MINE_LOGIC_MEMBER: ["homm3_xfp_f_orphan"]})
        self.assertEqual(
            {row["id"] for row in rows},
            {"mine_wood", "homm3_xfp_f_valid"},
        )

    def test_all_native_mine_logic_rows_are_cloneable(self) -> None:
        resources = {
            "mine_crystals": "crystals",
            "mine_gemstones": "gemstones",
            "mine_gold": "gold",
            "mine_mercury": "mercury",
            "mine_ore": "ore",
            "mine_wood": "wood",
        }
        logic_index = {
            sid: (
                exact_fp.MINE_LOGIC_MEMBER,
                {"id": sid, "resName": resource, "resValue": 2},
            )
            for sid, resource in resources.items()
        }
        logic_clones: list[dict] = []
        for sid in exact_fp.MINE_SIDS:
            exact_fp._maybe_queue_logic_clone(
                donor_sid=sid,
                clone_sid=f"homm3_xfp_f_{sid}",
                logic_index=logic_index,
                logic_clones=logic_clones,
                logic_clone_sids=set(),
            )
        self.assertEqual({row["donorSid"] for row in logic_clones}, set(resources))
        self.assertEqual({row["row"]["resName"] for row in logic_clones}, set(resources.values()))

    def test_missing_mine_logic_fails_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires logic row"):
            exact_fp._maybe_queue_logic_clone(
                donor_sid="mine_wood",
                clone_sid="homm3_xfp_f_missing_logic",
                logic_index={},
                logic_clones=[],
                logic_clone_sids=set(),
            )

    def test_size_change_is_forbidden_for_non_matching_footprint(self) -> None:
        footprint = exact_fp.same_size_nodes_from_h3(
            size_x=4,
            size_z=3,
            block_offsets=WOOD_BLOCKS,
            visit_offsets=WOOD_VISIT,
            kind="functional",
        )
        donor = mine_wood_config()
        donor["id"] = "knowledge_garden"
        with self.assertRaises(ValueError):
            exact_fp.apply_same_size_clone(
                donor,
                donor_sid="knowledge_garden",
                clone_sid="homm3_xfp_f_non_mine",
                footprint=footprint,
                allow_size_change=True,
            )

    def test_logic_overlay_reset_removes_stale_exact_rows(self) -> None:
        doc = {
            "array": [
                {"id": "mine_wood"},
                {"id": "homm3_xfp_f_old"},
                {"id": "custom_logic"},
            ]
        }
        surface_emit_module.reset_exact_logic_clone_rows(doc)
        self.assertEqual(
            {row["id"] for row in doc["array"]},
            {"mine_wood", "custom_logic"},
        )

    def test_all_native_mines_are_in_live_property_allowlists(self) -> None:
        self.assertTrue(exact_fp.MINE_SIDS <= set(surface_emit_module.SUPPORTED_LIVE_PROPERTY_SIDS))
        self.assertTrue(exact_fp.MINE_SIDS <= set(surface_emit_module.ENTITY_SIDS))

if __name__ == "__main__":
    unittest.main()
