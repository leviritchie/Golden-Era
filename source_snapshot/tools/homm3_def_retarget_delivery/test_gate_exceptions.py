"""gate_exceptions: the per-unit, value-pinned gate exceptions fail closed, go stale, and never excuse a worse fault."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gate_exceptions as GE  # noqa: E402

WHY = "a defect; user-approved exception 2026-09-28"


class _Units(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = GE.UNITS
        GE.UNITS = Path(self.tmp.name)

    def tearDown(self):
        GE.UNITS = self.old
        self.tmp.cleanup()

    def unit(self, ex, name="u"):
        (GE.UNITS / f"{name}.json").write_text(json.dumps({"unit": name, "gateExceptions": ex}), encoding="utf-8")
        return name


class ParserFailsClosed(_Units):
    def test_malformed(self):
        for ex in ({}, [], {"groundz": {"Move:sinks": {"value": -0.05, "reason": WHY}}},
                   {"ground": {}},
                   {"ground": {"Move sinks": {"value": -0.05, "reason": WHY}}},
                   {"ground": {"Move:sinks": {"value": -0.05}}},
                   {"ground": {"Move:sinks": {"value": -0.05, "reason": " "}}},
                   {"ground": {"Move:sinks": {"value": True, "reason": WHY}}},
                   {"ground": {"Move:sinks": {"value": "-0.05", "reason": WHY}}},
                   {"ground": {"Move:sinks": {"value": -0.05, "reason": WHY, "extra": 1}}},
                   {"stride": {"skate": {"value": 0.7, "reason": WHY}}},
                   {"articulation": {"wings:beat": {"value": 50, "reason": WHY}}}):
            with self.subTest(ex=ex), self.assertRaises(SystemExit):
                GE.apply(self.unit(ex), "ground", [])

    def test_absent_is_no_exception(self):
        (GE.UNITS / "plain.json").write_text("{}", encoding="utf-8")
        self.assertEqual(GE.apply("plain", "ground", ["Move sinks to -0.053 (DEF allows -0.040)"])[0],
                         ["Move sinks to -0.053 (DEF allows -0.040)"])
        self.assertEqual(GE.apply(None, "articulation", ["jittery: 0.46 of"])[0], ["jittery: 0.46 of"])


class Pins(_Units):
    def test_within_pin_is_excused_and_recorded(self):
        u = self.unit({"ground": {"Move:sinks": {"value": -0.053, "reason": WHY},
                                  "MoveStart:enters": {"value": 0.168, "reason": WHY}}})
        left, ex = GE.apply(u, "ground", ["Move sinks to -0.053 (DEF allows -0.040)",
                                          "MoveStart enters at +0.120 off the floor (DEF first frame +0.000, allowed [-0.040, +0.040])",
                                          "Death sinks to -0.300 (DEF allows -0.040)"])
        self.assertEqual(left, ["Death sinks to -0.300 (DEF allows -0.040)"])
        self.assertEqual([(x["key"], x["value"]) for x in ex], [("Move:sinks", -0.053), ("MoveStart:enters", 0.12)])

    def test_worse_than_pin_stays_a_fault(self):
        u = self.unit({"ground": {"Move:sinks": {"value": -0.053, "reason": WHY},
                                  "Move:enters": {"value": 0.10, "reason": WHY}}})
        left, ex = GE.apply(u, "ground", ["Move sinks to -0.054 (DEF allows -0.040)",
                                          "Move enters at -0.050 off the floor (DEF first frame +0.000, allowed [-0.040, +0.040])"])
        self.assertEqual(ex, [])
        self.assertEqual(len(left), 2)
        self.assertTrue(all("worse than its gate exception pin" in f for f in left))

    def test_floor_checks_are_worse_when_lower(self):
        u = self.unit({"articulation": {"wings": {"value": 57.9, "reason": WHY}, "body": {"value": 1.3, "reason": WHY}}})
        left, _ = GE.apply(u, "articulation", ["wings beat 58.2 deg peak to peak relative to the torso (flatFloor 60)",
                                               "body turns 1.30x the wing swing (bodyRot 61.0; cap 0.6)"])
        self.assertEqual(left, [])
        left, _ = GE.apply(u, "articulation", ["wings beat 57.8 deg peak to peak relative to the torso (flatFloor 60)",
                                               "body turns 1.31x the wing swing (bodyRot 61.0; cap 0.6)"])
        self.assertEqual(len(left), 2)

    def test_freeze_key_and_suffix(self):
        u = self.unit({"freeze": {"Unit_ShootFront:holds": {"value": 3, "reason": WHY}}})
        f = "Unit_ShootFront holds one pose for {} frames from frame 12 while the DEF moves (max 2) [x_def_retarget.glb]"
        self.assertEqual(GE.apply(u, "freeze", [f.format(3)])[0], [])
        self.assertEqual(len(GE.apply(u, "freeze", [f.format(4)])[0]), 1)

    def test_stale_key_is_a_fault(self):
        u = self.unit({"ground": {"Move:sinks": {"value": -0.053, "reason": WHY}}})
        left, _ = GE.apply(u, "ground", [])
        self.assertEqual(len(left), 1)
        self.assertIn("stale gate exception", left[0])


class Stride(_Units):
    def test_stride_faults_after(self):
        u = self.unit({"stride": {"slip": {"value": 0.7651, "reason": WHY}}})
        self.assertEqual(GE.stride_exceptions(u), {"slip": (0.7651, WHY)})
        self.assertEqual(GE.stride_faults_after(u, 0.7651, 1.06, 0.686, 1.4), [])
        self.assertEqual(GE.stride_faults_after(u, 0.7651, 1.5, 0.686, 1.4), ["ratio 1.5"])
        self.assertIn("worse than", GE.stride_faults_after(u, 0.7652, 1.06, 0.686, 1.4)[0])
        self.assertIn("stale", GE.stride_faults_after(u, 0.60, 1.06, 0.686, 1.4)[0])


if __name__ == "__main__":
    unittest.main()
