"""Owned re-rig: Mixamo-on-mount is replace; rider_mount walls keep the rider still."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "tools" / "homm3_silhouette_pose_fit"))

from owned_rerig.diagnose import diagnose_smartrig_quality
from owned_rerig.glb_io import load_mesh
from owned_rerig.pipeline import run_owned_rerig_pipeline
from owned_rerig.synthetic import authored_part_map_for_fixture, write_mixamo_rider_mount_fixture
from roc_geometric_proxy import load_asset, validate_bind_pose


class OwnedRerigTests(unittest.TestCase):
    def test_mixamo_on_long_mount_is_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            glb = Path(tmp) / "mixamo.glb"
            write_mixamo_rider_mount_fixture(glb)
            report = diagnose_smartrig_quality(glb, expected_species="rider_mount")
            self.assertEqual(report["verdict"], "replace")
            self.assertTrue(report["mixamoLike"])
            self.assertGreaterEqual(report["aabbAspectLengthOverHeight"], 1.15)

    def test_pipeline_builds_walled_rider_mount(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            glb = Path(tmp) / "mixamo.glb"
            write_mixamo_rider_mount_fixture(glb)
            part = Path(tmp) / "part_map.json"
            part.write_text(json.dumps(authored_part_map_for_fixture()), encoding="utf-8")
            report = run_owned_rerig_pipeline(
                dest_dir=dest,
                src_glb=glb,
                part_map_path=part,
                unit_sid="h3_cavalier",
            )
            self.assertTrue(report["audit"]["ok"], report["audit"]["issues"])
            master = Path(report["master"])
            self.assertTrue(master.is_file())
            mesh = load_mesh(master)
            names = mesh.node_names
            for bone in ("HorseLeftShoulder", "RiderHead", "LanceTip", "Saddle"):
                self.assertIn(bone, names)
            self.assertFalse(any("mixamo" in n.lower() for n in names))
            self.assertIsNotNone(mesh.joints)
            self.assertIsNotNone(mesh.weights)
            self.assertLess(report["audit"]["helmetDeltaMax"], 0.02)
            bind = validate_bind_pose(load_asset(master))
            self.assertTrue(bind["ok"], bind)

    def test_horse_leg_rotate_does_not_melt_helmet(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "out"
            glb = Path(tmp) / "mixamo.glb"
            write_mixamo_rider_mount_fixture(glb)
            part = Path(tmp) / "part_map.json"
            part.write_text(json.dumps(authored_part_map_for_fixture()), encoding="utf-8")
            report = run_owned_rerig_pipeline(
                dest_dir=dest,
                src_glb=glb,
                part_map_path=part,
            )
            self.assertTrue(report["audit"]["ok"], report["audit"]["issues"])
            self.assertLess(float(report["audit"]["helmetDeltaMax"]), 0.02)
            self.assertEqual(report["audit"]["crossPartitionLeaks"], 0)


    def test_roc_unirig_is_replace_for_flyer(self) -> None:
        glb = ROOT / "artifacts" / "meshy_downloads" / "h3_roc_smartrigged.glb"
        if not glb.is_file():
            self.skipTest("roc smartrig GLB is not in the worktree")
        report = diagnose_smartrig_quality(glb, expected_species="flyer")
        self.assertEqual(report["verdict"], "replace")
        failed = {row["id"] for row in report["checks"] if not row["ok"]}
        self.assertIn("flyer_not_unirig_bone_star", failed)

    def test_angel_unirig_without_arms_is_replace(self) -> None:
        glb = ROOT / "artifacts" / "meshy_downloads" / "h3_angel_smartrigged_rigidized.glb"
        if not glb.is_file():
            self.skipTest("angel smartrig GLB is not in the worktree")
        report = diagnose_smartrig_quality(glb, expected_species="winged_humanoid")
        self.assertEqual(report["verdict"], "replace")
        failed = {row["id"] for row in report["checks"] if not row["ok"]}
        self.assertIn("named_left_and_right_arm_chains", failed)
        self.assertIn("named_wing_chains", failed)


if __name__ == "__main__":
    unittest.main()
