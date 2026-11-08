"""Tests for upgrade-line keypoint and pose seed donors."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")

from roc_gpu_cascade_experiment import resolve_ik_keypoints_path
from upgrade_line_keypoints import (
    lab_sid_family_peers,
    skeleton_signatures_match,
    upgrade_line_pose_seed,
)


class TestUpgradeLineKeypoints(unittest.TestCase):
    def test_pikeman_line_family_peers(self) -> None:
        peers = lab_sid_family_peers("h3_halberdier")
        self.assertIn("h3_pikeman", peers)
        self.assertIn("h3_halberdier", peers)
        self.assertIn("h3_glaivier", peers)
        self.assertEqual(peers[0], "h3_halberdier")

    def test_meshy_pikeman_line_skeletons_differ(self) -> None:
        meshy = ROOT / "artifacts/meshy_downloads"
        paths = {
            sid: meshy / f"{sid}_smartrigged.glb"
            for sid in ("h3_pikeman", "h3_halberdier", "h3_glaivier")
        }
        if not all(path.is_file() for path in paths.values()):
            self.skipTest("Castle tier-1 smartrig GLBs missing")
        self.assertTrue(skeleton_signatures_match(paths["h3_pikeman"], paths["h3_pikeman"]))
        self.assertFalse(skeleton_signatures_match(paths["h3_pikeman"], paths["h3_halberdier"]))

    def test_keypoint_borrow_when_skeletons_match(self) -> None:
        source_glb = ROOT / "artifacts/meshy_downloads/h3_pikeman_smartrigged.glb"
        if not source_glb.is_file():
            self.skipTest("pikeman smartrig missing")
        with tempfile.TemporaryDirectory() as tmp:
            tmp_root = Path(tmp)
            meshy = tmp_root / "artifacts/meshy_downloads"
            meshy.mkdir(parents=True)
            shutil.copy2(source_glb, meshy / "h3_pikeman_smartrigged.glb")
            shutil.copy2(source_glb, meshy / "h3_halberdier_smartrigged.glb")
            donor = (
                tmp_root
                / "artifacts"
                / "pikeman_pose_pipeline"
                / "out_fit"
                / "idle_authored"
                / "sprite_landmarks"
                / "keypoints.json"
            )
            donor.parent.mkdir(parents=True)
            donor.write_text(
                json.dumps(
                    {
                        "method": "human_eye_landmark_authoring",
                        "frames": [
                            {
                                "frameIndex": 0,
                                "joints": {"Nose": {"x": 1.0, "y": 2.0, "visible": True}},
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            resolved = resolve_ik_keypoints_path(
                root=tmp_root,
                unit_name="halberdier",
                animation_name="idle",
                explicit=None,
                src_glb=meshy / "h3_halberdier_smartrigged.glb",
                lab_sid="h3_halberdier",
            )
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            self.assertEqual(payload.get("borrowedFrom", {}).get("labSid"), "h3_pikeman")
            self.assertEqual(payload["frames"][0]["joints"]["Nose"]["x"], 1.0)

    def test_pose_seed_skips_when_skeletons_differ(self) -> None:
        if not (ROOT / "artifacts/meshy_downloads/h3_halberdier_smartrigged.glb").is_file():
            self.skipTest("halberdier smartrig missing")
        seeded = upgrade_line_pose_seed(
            root=ROOT,
            lab_sid="h3_halberdier",
            animation_name="idle",
            target_mesh=ROOT / "artifacts/meshy_downloads/h3_halberdier_smartrigged.glb",
        )
        self.assertIsNone(seeded)


if __name__ == "__main__":
    unittest.main()
