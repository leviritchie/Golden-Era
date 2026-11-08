#!/usr/bin/env python3
"""Tests for prop-only landmark authoring."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from prop_author_common import (
    CRUSADER_SWORD_SHIELD_JOINTS,
    joint_dict,
    list_sprite_frames,
    write_prop_authored_clip,
)


class PropAuthorCommonTests(unittest.TestCase):
    def test_joint_dict_requires_all_props(self) -> None:
        xy = {name: (10, 20) for name in CRUSADER_SWORD_SHIELD_JOINTS}
        out = joint_dict(xy, CRUSADER_SWORD_SHIELD_JOINTS)
        self.assertEqual(set(out), set(CRUSADER_SWORD_SHIELD_JOINTS))
        self.assertTrue(out["WeaponTip"]["visible"])

    def test_list_sprite_frames_numbered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for i in (10, 11):
                Image.new("RGBA", (32, 32), (0, 0, 0, 0)).save(root / f"{i:02d}.png")
            paths = list_sprite_frames(root)
            self.assertEqual([int(p.stem) for p in paths], [10, 11])

    def test_write_prop_authored_clip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames_dir = root / "frames"
            frames_dir.mkdir()
            out_dir = root / "out"
            for i in range(2):
                Image.new("RGBA", (64, 64), (0, 0, 0, 255)).save(frames_dir / f"frame_{i:02d}.png")
            frames_xy = [
                {name: (20 + i, 30 + i) for name in CRUSADER_SWORD_SHIELD_JOINTS}
                for i in range(2)
            ]
            result = write_prop_authored_clip(
                clip_id="test_props",
                unit_sid="h3_crusader",
                frames_dir=frames_dir,
                out_dir=out_dir,
                frames_xy=frames_xy,
                joint_names=CRUSADER_SWORD_SHIELD_JOINTS,
                notes="unit test",
            )
            self.assertTrue(result["ok"])
            kpt = json.loads((out_dir / "sprite_landmarks" / "keypoints.json").read_text())
            self.assertEqual(kpt["authoringScope"], "props_only")
            self.assertEqual(len(kpt["frames"]), 2)
            self.assertTrue((out_dir / "test_props_props_authored.gif").is_file())


if __name__ == "__main__":
    unittest.main()
