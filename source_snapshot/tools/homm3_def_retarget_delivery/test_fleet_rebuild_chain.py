"""fleet_rebuild's last step: the canonical GLB must be the look's delivery of the run's export, or the unit fails
naming the broken link (a stage that rewrote the GLB before the run stopped short of look included).

    python -m unittest tools/homm3_def_retarget_delivery/test_fleet_rebuild_chain.py
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fleet_rebuild as FR  # noqa: E402
import stage_sidecar  # noqa: E402

U = "u_test"


def glb_bytes(extras: dict, tag: str) -> bytes:
    js = json.dumps({"asset": {"version": "2.0", "extras": extras}, "tag": tag}).encode()
    js += b" " * ((-len(js)) % 4)
    return struct.pack("<III", 0x46546C67, 2, 20 + len(js)) + struct.pack("<II", len(js), 0x4E4F534A) + js


def h(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class ChainAtEnd(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.glb = self.root / f"artifacts/homm3_def_retarget/{U}/{U}_def_retarget.glb"
        self.glb.parent.mkdir(parents=True)
        (self.root / f"artifacts/homm3_unit_look/{U}").mkdir(parents=True)
        (self.root / f"artifacts/homm3_def_retarget_emphasis/{U}").mkdir(parents=True)
        self.export = glb_bytes({"homm3DefRetargetEmphasis": {}}, "export")
        (self.root / f"artifacts/homm3_def_retarget_emphasis/{U}/stamp.json").write_text(
            json.dumps({"emphasisedGlbSha256": h(self.export)}))
        self.p = patch.object(FR, "ROOT", self.root)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        self.tmp.cleanup()

    def ground(self) -> bytes:
        g = glb_bytes({"homm3DefRetargetEmphasis": {}, "homm3DefRetargetDeliveryGround":
                       {"sourceGlbSha256": h(self.export)}}, "grounded")
        self.glb.write_bytes(g)
        Path(str(self.glb) + ".ground.json").write_text(json.dumps(
            {"sourceGlbSha256": h(self.export), "outputGlbSha256": h(g)}))
        return g

    def look(self, source: bytes, delivered: bytes):
        (self.root / f"artifacts/homm3_unit_look/{U}/stamp.json").write_text(json.dumps(
            {"sourceGlbSha256": h(source), "deliveredGlbSha256": h(delivered)}))

    def rec(self, last_step=FR.LOOK_DELIVERED_STEP):
        return {"route": "emphasis_redeliver", "deliveryBaseGlbSha256": h(self.export),
                "steps": [{"step": last_step, "rc": 0}]}

    def test_linked_run_passes(self):
        g = self.ground()
        looked = glb_bytes({"homm3DefRetargetEmphasis": {}, "homm3DefRetargetDeliveryGround":
                            {"sourceGlbSha256": h(self.export)}}, "looked")
        self.glb.write_bytes(looked)
        self.look(g, looked)
        self.assertEqual(FR.chain_errors(U, self.rec()), [])

    def test_ground_rewrote_the_glb_and_look_did_not_rerun(self):
        old = glb_bytes({}, "last week's look")
        self.look(old, old)
        self.ground()
        errs = FR.chain_errors(U, self.rec(last_step="ground apply"))
        self.assertTrue(any("deliveredGlbSha256" in e for e in errs), errs)

    def test_stopped_after_the_export_before_any_stage(self):
        self.glb.write_bytes(self.export)
        old = glb_bytes({}, "last week's look")
        self.look(old, old)
        errs = FR.chain_errors(U, self.rec(last_step="deliver --force"))
        self.assertTrue(any("un-looked export" in e for e in errs), errs)

    def test_export_is_not_the_emphasis_stamps(self):
        other = glb_bytes({}, "a different export")
        self.glb.write_bytes(other)
        r = self.rec(); r["deliveryBaseGlbSha256"] = h(other)
        self.assertTrue(any("emphasisedGlbSha256" in e for e in FR.chain_errors(U, r)))

    def test_recorded_stride_output_must_be_grounds_input(self):
        strided = glb_bytes({"homm3DefRetargetDeliveryStrideMatch": {"sourceGlbSha256": h(self.export)}}, "strided")
        stage_sidecar.write(self.glb, "stride_match", "s", U, h(self.export), h(strided))
        for ground_src, ok in ((strided, True), (glb_bytes({}, "something else"), False)):
            ex = {"homm3DefRetargetDeliveryStrideMatch": {"sourceGlbSha256": h(self.export)},
                  "homm3DefRetargetDeliveryGround": {"sourceGlbSha256": h(ground_src)}}
            g = glb_bytes(ex, "grounded")
            Path(str(self.glb) + ".ground.json").write_text(json.dumps(
                {"sourceGlbSha256": h(ground_src), "outputGlbSha256": h(g)}))
            looked = glb_bytes(ex, "looked")
            self.glb.write_bytes(looked)
            self.look(g, looked)
            errs = FR.chain_errors(U, self.rec())
            self.assertEqual(errs == [], ok, errs)

    def test_no_export_no_base(self):
        self.assertEqual(len(FR.chain_errors(U, {"steps": []})), 1)



class RawVerdict(unittest.TestCase):
    """A rebuilt rawAccepted unit re-makes its look decision on the try-modes numbers (2026-10-01 hota_cove_ayssid:
    v7c 3.3 now below raw 3.38, so --accept-raw refused every rebuild)."""

    def _dir(self, raw, v7c, v6m):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        d = Path(t.name)
        for m, v in (("v7c", v7c), ("v6m", v6m)):
            (d / f"try_{m}_metrics.json").write_text(json.dumps(
                {"review": {"summary": {"meanLhistBodyLook": v, "meanLhistBodyRaw": raw}}}), encoding="utf-8")
        return d

    def test_raw_still_below_every_mode_is_re_earned(self):
        self.assertEqual(FR.raw_verdict(self._dir(3.0, 3.3, 5.7), U, "v7c")[0], "raw")

    def test_spec_mode_beating_raw_takes_the_applied_look(self):
        self.assertEqual(FR.raw_verdict(self._dir(3.38, 3.3, 5.74), U, "v7c")[0], "applied")

    def test_the_applied_decision_is_the_reviewed_bake(self):
        """metrics.json (the spec-mode bake --stages apply delivers) decides, not the try run: they differ by rebake
        noise (ayssid: try v7c 3.3, a --force rebake 3.4, raw 3.39)."""
        d = self._dir(3.39, 3.35, 5.73)
        (d / "metrics.json").write_text(json.dumps(
            {"review": {"summary": {"meanLhistBodyLook": 3.4, "meanLhistBodyRaw": 3.39}}}), encoding="utf-8")
        self.assertEqual(FR.raw_verdict(d, U, "v7c")[0], "refuse")
        (d / "metrics.json").write_text(json.dumps(
            {"review": {"summary": {"meanLhistBodyLook": 3.35, "meanLhistBodyRaw": 3.39}}}), encoding="utf-8")
        self.assertEqual(FR.raw_verdict(d, U, "v7c")[0], "applied")

    def test_another_mode_beating_raw_refuses(self):
        self.assertEqual(FR.raw_verdict(self._dir(3.38, 3.3, 5.74), U, "v6m")[0], "refuse")

    def test_disagreeing_raw_refuses(self):
        d = self._dir(3.38, 3.3, 5.74)
        (d / "try_v6m_metrics.json").write_text(json.dumps(
            {"review": {"summary": {"meanLhistBodyLook": 5.74, "meanLhistBodyRaw": 3.1}}}), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "disagree"):
            FR.raw_verdict(d, U, "v7c")


class GradedLookOrder(unittest.TestCase):
    """The rebuild reviews the fitted look (A) against the DEF before the finish (look B), the same order as the
    look-B rollout (look.py --stages finish,apply on reviewed looks); look.py's apply refusal stays the gate
    (2026-10-09 h3_azure_dragon: a bare look.py reviewed B, 7.07 vs raw 3.51, and refused the approved look)."""

    def stages(self, args):
        return args[args.index("--stages") + 1].split(",")

    def test_review_runs_before_finish(self):
        calls = []
        FR.deliver_graded_look(lambda name, args: calls.append(self.stages(args)))
        self.assertEqual(len(calls), 2)
        first, second = calls
        self.assertIn("review", first)
        self.assertNotIn("finish", first)
        self.assertNotIn("apply", first)
        self.assertEqual(second, ["finish", "apply"])
        self.assertEqual(first, ["bake", "fit", "vfx", "review"])

    def test_a_refused_review_stops_before_finish(self):
        calls = []

        def look_step(name, args):
            calls.append(self.stages(args))
            raise RuntimeError(f"{name} rc=5")
        with self.assertRaises(RuntimeError):
            FR.deliver_graded_look(look_step)
        self.assertEqual(len(calls), 1)

    def test_superseded_raw_finishes_the_reviewed_bake(self):
        self.assertEqual(self.stages(FR.LOOK_FINISH_STEP[1]), ["finish", "apply"])

    def test_try_modes_measure_what_the_review_measures(self):
        """raw_verdict sets the try numbers against the reviewed bake: both judge look A, never the finish (2026-10-11
        h3_ghost_dragon: try v6m 4.22 post-finish vs the reviewed bake 4.43, raw 4.28, refused both routes)."""
        args = FR.LOOK_TRY_STEP[1]
        self.assertIn("--try-modes", args)
        self.assertEqual(self.stages(args), self.stages(FR.LOOK_REVIEW_STEP[1]))
        self.assertNotIn("finish", self.stages(args))


if __name__ == "__main__":
    unittest.main()
