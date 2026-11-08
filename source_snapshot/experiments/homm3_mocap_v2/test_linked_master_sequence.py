"""Contract test: the linked-master reel is derived from the native DEF-group contract, for any unit."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from linked_master_sequence import (
    IDLE_GROUP,
    MOVE_GROUP,
    ROLE_BOOKEND,
    ROLE_CYCLE,
    all_sequence_indices,
    build_master_sequence,
    effective_capture_capacity,
    export_segments,
    native_reel,
    reel_frame_count,
)

CLIP_NAMES = {
    0: "move", 1: "mouseover", 2: "idle", 3: "hitted", 4: "defence", 5: "death",
    7: "turn_left", 8: "turn_right", 11: "attack_up", 12: "attack_front", 13: "attack_down",
    15: "shoot_front", 20: "move_start", 21: "move_end",
}


def _manifest(root: Path, unit: str, groups: dict[int, int]) -> Path:
    clips = []
    for group, count in sorted(groups.items()):
        key = f"g{group:02d}_{CLIP_NAMES[group]}"
        frames = []
        for index in range(count):
            path = root / key / f"{index:03d}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGBA", (8, 8), (index * 10, group, 0, 255)).save(path)
            frames.append(str(path))
        clips.append({"key": key, "group": group, "frames": frames})
    manifest = root / "manifest.json"
    manifest.write_text(json.dumps({"unit": unit, "clips": clips, "sourceFrameMs": 1000 / 12}), encoding="utf-8")
    return manifest


class NativeReelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reel_uses_each_native_group_once_and_skips_the_rest(self):
        manifest_path = _manifest(self.root, "h3_example", {0: 6, 1: 7, 2: 8, 3: 7, 4: 9, 5: 8, 7: 3, 11: 9, 12: 8, 13: 9, 20: 4, 21: 4})
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        reel, skipped = native_reel(manifest, idle_bookend_frames=1)
        cycles = [row["defGroup"] for row in reel if row["role"] == ROLE_CYCLE]
        self.assertEqual(cycles, [2, 20, 0, 21, 1, 3, 4, 12, 5], "idle, move chain, actions in group order, death last")
        self.assertEqual(len(cycles), len(set(cycles)))
        bookends = [row for row in reel if row["role"] == ROLE_BOOKEND]
        self.assertTrue(all(row["defGroup"] == IDLE_GROUP and row["frameLimit"] == 1 for row in bookends))
        self.assertEqual([row["defGroup"] for row in skipped], [7, 11, 13])
        self.assertEqual({row["reason"] for row in skipped}, {"skipped_def_group"})
        # 8 idle + 4 + 6 + 4 + 7 + 7 + 9 + 8 + 8 cycles + 5 single-frame bookends
        self.assertEqual(reel_frame_count(reel, manifest), 8 + 4 + 6 + 4 + 7 + 7 + 9 + 8 + 8 + 5)

    def test_shooter_includes_shoot_front_and_tolerates_missing_move_start_end(self):
        manifest_path = _manifest(self.root, "h3_archer_like", {0: 6, 2: 8, 12: 8, 15: 8, 5: 8})
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        reel, skipped = native_reel(manifest, idle_bookend_frames=2)
        self.assertEqual([row["defGroup"] for row in reel if row["role"] == ROLE_CYCLE], [2, 0, 12, 15, 5])
        self.assertEqual(skipped, [])
        self.assertTrue(all(row["frameLimit"] == 2 for row in reel if row["role"] == ROLE_BOOKEND))

    def test_unit_skip_def_groups_drops_the_shoot_clip_with_its_reason(self):
        manifest_path = _manifest(self.root, "h3_caster_like", {0: 6, 2: 8, 12: 8, 15: 8, 5: 8})
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        reel, skipped = native_reel(manifest, idle_bookend_frames=1, unit_skips={15: "view never shoots"})
        self.assertEqual([row["defGroup"] for row in reel if row["role"] == ROLE_CYCLE], [2, 0, 12, 5])
        self.assertEqual(skipped, [{"clipKey": "g15_shoot_front", "defGroup": 15, "reason": "unit_skip_def_group",
                                    "unitReason": "view never shoots"}])

    def test_unit_skips_default_to_the_unit_config(self):
        # a unit with no retarget config skips nothing extra; the real knob is read from units/<unit>.json
        manifest = json.loads(_manifest(self.root, "h3_no_such_config", {0: 6, 2: 8, 15: 8}).read_text(encoding="utf-8"))
        reel, skipped = native_reel(manifest, idle_bookend_frames=1)
        self.assertIn(15, [row["defGroup"] for row in reel])
        self.assertEqual(skipped, [])

    def test_missing_idle_or_move_fails_closed(self):
        manifest_path = _manifest(self.root, "h3_static", {2: 8, 12: 8})
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        with self.assertRaisesRegex(ValueError, "required native groups"):
            native_reel(manifest, idle_bookend_frames=1)

    def test_build_writes_provenance_bind_and_export_segments(self):
        manifest_path = _manifest(self.root, "h3_example", {0: 6, 2: 8, 12: 8, 5: 8, 7: 3})
        master = build_master_sequence(manifest_path, self.root / "out", pose_capacity=90, idle_bookend_frames=1)
        self.assertEqual(master["unit"], "h3_example")
        self.assertEqual(master["frameCount"], 8 + 6 + 1 + 8 + 1 + 8)
        self.assertEqual(master["bindGroup"], MOVE_GROUP)
        self.assertEqual(master["bindGlobalIndex"], 8, "bind is the first move frame, after the full idle cycle")
        self.assertEqual(all_sequence_indices(master), list(range(master["frameCount"])))
        exported = export_segments(master)
        self.assertEqual([s["contractSuffix"] for s in exported], ["Idle", "Move", "AttackFront", "Death"])
        for segment in exported:
            self.assertEqual(segment["frameCount"], segment["sourceClipFrameCount"], "exported cycles are never truncated")
        frames = master["frames"]
        self.assertEqual(frames[8]["clipKey"], "g00_move")
        self.assertEqual(frames[8]["localIndex"], 0)
        self.assertEqual(frames[14]["role"], ROLE_BOOKEND)
        numbered = sorted(Path(master["framesDir"]).glob("*.png"))
        self.assertEqual(len(numbered), master["frameCount"])
        self.assertEqual([row["defGroup"] for row in master["skippedClips"]], [7])

    def test_non_h3_sid_is_a_valid_manifest_unit(self):
        manifest_path = _manifest(self.root, "toa_shahrokh", {0: 4, 2: 4, 5: 2})
        master = build_master_sequence(manifest_path, self.root / "toa", pose_capacity=90, idle_bookend_frames=1, bind_group=IDLE_GROUP)
        self.assertEqual(master["unit"], "toa_shahrokh")
        self.assertEqual(master["bindGlobalIndex"], 0)

    def test_idle_bind_is_the_first_cycle_frame(self):
        manifest_path = _manifest(self.root, "h3_example", {0: 6, 2: 8, 12: 8, 5: 8})
        master = build_master_sequence(
            manifest_path,
            self.root / "idle_bind",
            pose_capacity=90,
            idle_bookend_frames=1,
            bind_group=IDLE_GROUP,
        )
        self.assertEqual(master["bindGroup"], IDLE_GROUP)
        self.assertEqual(master["bindLocalFrame"], 0)
        self.assertEqual(master["bindGlobalIndex"], 0)
        self.assertEqual(master["frames"][0]["clipKey"], "g02_idle")
        self.assertEqual(master["frames"][0]["localIndex"], 0)
        self.assertEqual(master["frames"][0]["role"], ROLE_CYCLE)

    def test_reel_over_capacity_fails_closed(self):
        manifest_path = _manifest(self.root, "h3_example", {0: 30, 2: 30, 12: 30, 5: 30})
        with self.assertRaisesRegex(ValueError, "one capture can return"):
            build_master_sequence(manifest_path, self.root / "out", pose_capacity=90, idle_bookend_frames=1)

    def test_capacity_drops_the_truncated_frame(self):
        import numpy as np

        self.assertEqual(effective_capture_capacity({"posePosition": np.zeros((91, 50, 3))}), 90)
        with self.assertRaises(ValueError):
            effective_capture_capacity({"posePosition": np.zeros((2, 50, 3))})


if __name__ == "__main__":
    unittest.main()
