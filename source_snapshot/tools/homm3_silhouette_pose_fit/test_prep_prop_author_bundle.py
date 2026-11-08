#!/usr/bin/env python3
"""Tests for prep_prop_author_bundle."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

import prep_prop_author_bundle as prep


class PrepPropAuthorBundleTests(unittest.TestCase):
    def test_resolve_source_numbered_and_plain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGBA", (4, 4)).save(root / "10.png")
            path = prep._resolve_source_path(root, 10, None)
            self.assertEqual(path.name, "10.png")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new("RGBA", (4, 4)).save(root / "frame_03.png")
            path = prep._resolve_source_path(root, 3, "frame_{:02d}.png")
            self.assertEqual(path.name, "frame_03.png")

    def test_build_bundle_stages_sprites_and_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            source.mkdir()
            out = root / "out"
            for idx in (10, 11):
                Image.new("RGBA", (32, 24), (0, 0, 0, 255)).save(source / f"{idx}.png")

            bundle = prep.build_bundle(
                unit_sid="h3_crusader",
                clip_id="move_g0",
                source_frames_dir=source,
                frame_indices=[10, 11],
                out_dir=out,
                joints=["WeaponTip", "RWrist", "ShieldCenter", "LWrist"],
                edge_set="crusader_sword_shield",
                sequence="test",
                def_group=0,
                def_name="move",
                source_name_pattern=None,
            )
            self.assertEqual(bundle["schema"], "homm3_prop_author_bundle.v1")
            self.assertEqual(bundle["spriteSize"], {"width": 32, "height": 24})
            self.assertEqual(len(bundle["frames"]), 2)
            for entry in bundle["frames"]:
                self.assertTrue(Path(entry["stagedSprite"]).is_file())
            manifest = json.loads((out / "author_bundle.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["markingMethod"], "multimodal_eye_only")
            self.assertIn("track_joints_lk", manifest["forbiddenForSubagent"])


if __name__ == "__main__":
    unittest.main()
