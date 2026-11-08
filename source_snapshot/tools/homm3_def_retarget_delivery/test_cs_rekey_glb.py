"""cs_rekey_glb: a CS_ target on at several keys resolves to its own frame's key, a skipDefGroups clip's targets are
orphans (recorded, not refused), and anything else stays refused.

    python -m unittest tools/homm3_def_retarget_delivery/test_cs_rekey_glb.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import cs_rekey_glb as R  # noqa: E402


class OwnKey(unittest.TestCase):
    def test_one_key_is_that_key(self):
        t = np.array([1, 2, 3]) / 12
        self.assertEqual(R.own_key("CS_Unit_Move_002", "Unit_Move", t, np.array([1])), 1)

    def test_one_frame_clip_sampled_twice_resolves_to_its_frame(self):
        # h3_walking_dead Unit_MoveEnd: keys at 1/12 and 2/12 s, the target (frame 1) on at both
        t = np.array([1, 2]) / 12
        self.assertEqual(R.own_key("CS_Unit_MoveEnd_001", "Unit_MoveEnd", t, np.array([0, 1])), 0)
        # the same shape one frame later in the reel
        t = np.array([7, 8]) / 12
        self.assertEqual(R.own_key("CS_Unit_Idle_007", "Unit_Idle", t, np.array([0, 1])), 0)

    def test_several_keys_none_at_its_frame_is_refused(self):
        t = np.array([1, 2]) / 12
        with self.assertRaises(SystemExit):
            R.own_key("CS_Unit_MoveEnd_005", "Unit_MoveEnd", t, np.array([0, 1]))

    def test_several_keys_at_its_frame_is_refused(self):
        t = np.array([1, 1, 2]) / 12            # a duplicated timestamp is ambiguous, not a hold
        with self.assertRaises(SystemExit):
            R.own_key("CS_Unit_MoveEnd_001", "Unit_MoveEnd", t, np.array([0, 1, 2]))

    def test_no_key_is_refused(self):
        with self.assertRaises(SystemExit):
            R.own_key("CS_Unit_Move_001", "Unit_Move", np.array([1 / 12]), np.array([], int))


class Orphans(unittest.TestCase):
    NAMES = ["CS_Unit_Idle_001", "CS_Unit_ShootFront_003", "CS_Unit_ShootFront_004"]

    def test_skipped_clip_targets_are_orphans(self):
        o = R.orphan_targets(self.NAMES, {"Unit_Idle": {}}, {"Unit_ShootFront": "never shoots"})
        self.assertEqual(o, {"Unit_ShootFront": [1, 2]})

    def test_missing_clip_not_skipped_is_refused(self):
        with self.assertRaises(SystemExit):
            R.orphan_targets(self.NAMES, {"Unit_Idle": {}}, {})

    def test_record_accepts_orphans_with_matching_count_only(self):
        ex = {R.CS.BAKE_STAMP: {R.REKEY: {
                  "schema": R.REKEY_SCHEMA, "sourceGlbSha256": "a",
                  "clips": {"Unit_Idle": {"status": "unchanged", "targets": 1, "rebaked": 0, "rigid": 0, "unchanged": 1}},
                  "orphans": {"Unit_ShootFront": {"targets": 2}}}},
              R.STAMP: {"schema": R.SCHEMA, "sourceGlbSha256": "a", "rebakedClips": []}}
        self.assertEqual(R.record_errors(ex, {"Unit_Idle": 1, "Unit_ShootFront": 2}), [])
        self.assertTrue(R.record_errors(ex, {"Unit_Idle": 1, "Unit_ShootFront": 3}))
        del ex[R.CS.BAKE_STAMP][R.REKEY]["orphans"]
        self.assertTrue(R.record_errors(ex, {"Unit_Idle": 1, "Unit_ShootFront": 2}))


if __name__ == "__main__":
    unittest.main()
