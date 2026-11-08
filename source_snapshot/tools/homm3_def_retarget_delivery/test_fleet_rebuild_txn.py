"""fleet_rebuild is transactional over the delivered state: a unit that fails gets its pre-run GLB, stage sidecars,
emphasis and look stamps back byte for byte (files the run created are removed); a unit that passes keeps its new state.

    python -m unittest tools/homm3_def_retarget_delivery/test_fleet_rebuild_txn.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import fleet_rebuild as FR  # noqa: E402

U = "u_test"


class Transaction(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(FR, "ROOT", self.root), patch.object(FR, "LOGS", self.root / "logs")]
        for p in self.patches:
            p.start()
        self.glb = self.root / f"artifacts/homm3_def_retarget/{U}/{U}_def_retarget.glb"
        self.look = self.root / f"artifacts/homm3_unit_look/{U}/stamp.json"
        self.emph = self.root / f"artifacts/homm3_def_retarget_emphasis/{U}/stamp.json"
        self.blend = self.glb.with_name(f"{U}_def_retarget.blend")
        for p, b in ((self.glb, b"looked delivery"), (self.look, b'{"deliveredGlbSha256": "old"}'),
                     (self.emph, b'{"emphasisedGlbSha256": "old"}'), (self.blend, b"old blend")):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
        os.utime(self.glb, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        self.before = {p: p.read_bytes() for p in (self.glb, self.look, self.emph)}
        self.mtime = self.glb.stat().st_mtime_ns

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def half_run(self, fail: bool):
        def rebuild(u, rec):
            self.blend.write_bytes(b"new blend")
            self.glb.write_bytes(b"new export, grounded")
            Path(f"{self.glb}.ground.json").write_text("{}")
            self.emph.write_text('{"emphasisedGlbSha256": "new"}')
            rec["steps"] = [{"step": "ground apply", "rc": 0}]
            if fail:
                raise RuntimeError("look --force rc=3")
            rec["ok"] = True
            return rec
        return rebuild

    def run_main(self, fail: bool, faults=lambda u, glb: set(), idle_rc: int = 0, prune_rc: int = 0) -> dict:
        self.idle_calls, self.prune_calls = [], []
        sup = self.root / f"artifacts/homm3_unit_look/{U}/_superseded_do_not_use"

        def idle(u):
            self.idle_calls.append(u)
            return idle_rc

        def prune(u):   # look.py --prune-superseded: deletes every superseded original but the stamp's source
            self.prune_calls.append((u, list(self.idle_calls)))
            for f in sup.glob("*"):
                if f.name != "kept_by_stamp.glb.unprebaked":
                    f.unlink()
            return prune_rc
        with patch.object(FR, "rebuild", self.half_run(fail)), patch.object(FR, "chain_errors", lambda u, r: []), \
                patch.object(FR, "gate_faults", faults), patch.object(FR, "idle_rollout", idle), \
                patch.object(FR, "prune_superseded", prune), patch.object(sys, "argv", ["fleet_rebuild.py", U]):
            FR.main()
        return json.loads((self.root / f"logs/rebuild_{U}.json").read_text())

    def superseded(self) -> Path:
        """The pre-run stamp's original (what a restore points the look back at) and the new run's source."""
        sup = self.root / f"artifacts/homm3_unit_look/{U}/_superseded_do_not_use"
        sup.mkdir(parents=True, exist_ok=True)
        (sup / "kept_by_stamp.glb.unprebaked").write_bytes(b"new run source")
        old = sup / "fdf3852dce0e.glb.unprebaked"
        old.write_bytes(b"the restored stamp's source")
        return old

    def test_a_refused_idle_rollout_leaves_the_superseded_originals(self):
        # 2026-10-09 h3_peasant: the prune ran before the idle rollout refused; restore brought back a look stamp
        # whose source original the prune had deleted. The prune now runs only after every failing-capable step.
        old = self.superseded()
        rec = self.run_main(fail=False, idle_rc=1)
        self.assertFalse(rec["ok"])
        self.assertIn("restore", rec)
        self.assertEqual(self.prune_calls, [])
        self.assertEqual(old.read_bytes(), b"the restored stamp's source")
        self.assertEqual(self.look.read_bytes(), self.before[self.look])

    def test_a_failed_rebuild_or_gate_never_prunes(self):
        old = self.superseded()
        self.run_main(fail=True)
        self.run_main(fail=False, faults=lambda u, glb: {"ground:new"} if glb == self.glb else set())
        self.assertEqual(self.prune_calls, [])
        self.assertTrue(old.exists())

    def test_a_passing_unit_prunes_last_after_the_idle_rollout(self):
        old = self.superseded()
        rec = self.run_main(fail=False)
        self.assertTrue(rec["ok"])
        self.assertEqual(self.prune_calls, [(U, [U])])     # the idle rollout had already run
        self.assertEqual(rec["prune"], 0)
        self.assertFalse(old.exists())

    def test_a_failed_prune_keeps_the_delivery(self):
        rec = self.run_main(fail=False, prune_rc=2)
        self.assertTrue(rec["ok"])
        self.assertIn("prune-superseded rc=2", rec["warning"])
        self.assertEqual(self.glb.read_bytes(), b"new export, grounded")

    def test_a_passing_unit_rolls_its_idle_cadence(self):
        rec = self.run_main(fail=False)
        self.assertEqual(self.idle_calls, [U])
        self.assertEqual(rec["idleRollout"], 0)

    def test_a_refused_idle_rollout_fails_the_unit_and_restores(self):
        rec = self.run_main(fail=False, idle_rc=1)
        self.assertFalse(rec["ok"])
        self.assertIn("rollout_idle.py", rec["error"])
        for p, b in self.before.items():
            self.assertEqual(p.read_bytes(), b, p.name)

    def test_a_failed_rebuild_does_not_roll_the_idle(self):
        self.run_main(fail=True)
        self.assertEqual(self.idle_calls, [])

    def test_a_new_gate_fault_fails_the_unit_and_restores(self):
        seen = []

        def faults(u, glb):
            b = Path(glb).read_bytes()
            seen.append(b)
            return {"ground:Death:sinks"} | ({"articulation:jittery"} if b"grounded" in b else set())
        rec = self.run_main(fail=False, faults=faults)
        self.assertEqual(seen, [b"looked delivery", b"new export, grounded"])   # the snapshot, then the new GLB
        self.assertFalse(rec["ok"])
        self.assertIn("articulation:jittery", rec["error"])
        self.assertEqual(rec["gateFaults"]["before"], ["ground:Death:sinks"])
        for p, b in self.before.items():
            self.assertEqual(p.read_bytes(), b, p.name)

    def test_faults_the_delivered_glb_already_had_do_not_block(self):
        rec = self.run_main(fail=False, faults=lambda u, glb: {"ground:Death:sinks"})
        self.assertTrue(rec["ok"])
        self.assertEqual(self.glb.read_bytes(), b"new export, grounded")

    def test_a_failed_unit_gets_its_delivered_state_back(self):
        rec = self.run_main(fail=True)
        self.assertFalse(rec["ok"])
        for p, b in self.before.items():
            self.assertEqual(p.read_bytes(), b, p.name)
        self.assertEqual(self.glb.stat().st_mtime_ns, self.mtime)     # the look stamp's deliveredGlbStat still holds
        self.assertFalse(Path(f"{self.glb}.ground.json").exists())    # created by the failed run: removed
        self.assertEqual(set(rec["restore"]["replaced"]), {self.glb.name, "stamp.json"})
        self.assertEqual(rec["restore"]["removed"], [f"{self.glb.name}.ground.json"])
        self.assertEqual(self.blend.read_bytes(), b"new blend")       # a build input, stated as not restored
        self.assertFalse((self.root / f"logs/_txn/{U}").exists())

    def test_a_failed_unit_gets_its_patch_base_back(self):
        B = self.root / f"artifacts/homm3_glb_patch/{U}"
        B.mkdir(parents=True)
        (B / "base.glb").write_bytes(b"old export")
        (B / "base.json").write_text('{"files": "old"}')
        before = {p: p.read_bytes() for p in B.iterdir()}
        inner = self.half_run(True)

        def rebuild(u, rec):
            (B / "base.glb").write_bytes(b"failed export")          # patch_base.retain right after the export
            (B / "base.json").write_text('{"files": "new"}')
            (B / "emphasis_stamp.json").write_text("{}")
            return inner(u, rec)
        with patch.object(FR, "rebuild", rebuild), patch.object(FR, "chain_errors", lambda u, r: []),                 patch.object(FR, "gate_faults", lambda u, glb: set()), patch.object(sys, "argv", ["fleet_rebuild.py", U]):
            FR.main()
        self.assertEqual({p: p.read_bytes() for p in B.iterdir()}, before)  # created file removed, others restored

    def test_a_passing_unit_keeps_its_new_state(self):
        rec = self.run_main(fail=False)
        self.assertTrue(rec["ok"])
        self.assertNotIn("restore", rec)
        self.assertEqual(self.glb.read_bytes(), b"new export, grounded")
        self.assertTrue(Path(f"{self.glb}.ground.json").exists())
        self.assertFalse((self.root / f"logs/_txn/{U}").exists())

    def test_a_broken_chain_fails_the_unit_and_restores(self):
        with patch.object(FR, "rebuild", self.half_run(False)), \
                patch.object(FR, "chain_errors", lambda u, r: ["look source is not the ground output"]), \
                patch.object(FR, "gate_faults", lambda u, glb: set()), patch.object(sys, "argv", ["fleet_rebuild.py", U]):
            self.assertEqual(FR.main(), 1)
        rec = json.loads((self.root / f"logs/rebuild_{U}.json").read_text())
        self.assertFalse(rec["ok"])
        self.assertEqual(self.glb.read_bytes(), self.before[self.glb])

    def test_a_restore_that_cannot_reproduce_the_snapshot_fails_closed(self):
        txn = FR.snapshot(U, self.root / "logs/_txn" / U)
        self.glb.write_bytes(b"changed")
        Path(txn["files"][0]["keep"]).write_bytes(b"corrupted snapshot")
        with self.assertRaises(RuntimeError):
            FR.restore(txn)
        self.assertTrue(Path(txn["dir"]).exists())                     # kept for a hand restore


class PreRunSnapshot(unittest.TestCase):
    """run_unit.sh snapshots before it overwrites the canonical GLB; the fleet_rebuild after it restores that delivery
    (2026-10-09 h3_sharpshooter: the restore put back run_unit's raw export cf42ac0e under the delivered look stamps)."""
    setUp, tearDown, half_run, run_main = Transaction.setUp, Transaction.tearDown, Transaction.half_run, Transaction.run_main

    def run_unit(self):
        FR.pre_run_snapshot(U)
        self.glb.write_bytes(b"raw export")
        FR.pre_run_export(U)

    def test_a_failed_rebuild_after_run_unit_restores_the_delivered_glb(self):
        self.run_unit()
        with patch.dict(os.environ):
            rec = self.run_main(fail=False, idle_rc=1)       # the nearStatic idle-rollout refusal
        self.assertFalse(rec["ok"])
        self.assertEqual(rec["snapshot"], "pre-run (run_unit.sh)")
        self.assertEqual(rec["restore"]["restoredGlbSha256"], FR.sha_bytes(b"looked delivery"))
        for p, b in self.before.items():
            self.assertEqual(p.read_bytes(), b, p.name)
        self.assertFalse((self.root / f"logs/_txn/{U}").exists())

    def test_a_second_run_unit_keeps_the_first_snapshot(self):
        self.run_unit()
        self.run_unit()
        self.assertEqual(Path(FR.snapshot_glb(FR.adopt_pre_run(U), U)).read_bytes(), b"looked delivery")

    def test_a_stale_pre_run_snapshot_is_not_adopted(self):
        self.run_unit()
        self.glb.write_bytes(b"delivered since by --from-base")   # neither the snapshot's GLB nor run_unit's export
        self.assertIsNone(FR.adopt_pre_run(U))
        with patch.dict(os.environ):
            rec = self.run_main(fail=True)
        self.assertEqual(rec["snapshot"], "this run")
        self.assertEqual(self.glb.read_bytes(), b"delivered since by --from-base")


class FromBaseSnapshot(unittest.TestCase):
    """--from-base writes the canonical GLB only by tmp + os.replace (look apply), so its transaction snapshot hard-links
    the GLB and the look images instead of copying them; JSONs (rewritten in place) are still copied."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.patches = [patch.object(FR, "ROOT", self.root), patch.object(FR, "LOGS", self.root / "logs"),
                        patch.object(FR, "FROM_BASE", [False])]
        for p in self.patches:
            p.start()
        self.glb = self.root / f"artifacts/homm3_def_retarget/{U}/{U}_def_retarget.glb"
        self.look = self.root / f"artifacts/homm3_unit_look/{U}/stamp.json"
        self.png = self.root / f"artifacts/homm3_unit_look/{U}/basecolor.png"
        for p, b in ((self.glb, b"looked delivery"), (self.look, b'{"deliveredGlbSha256": "old"}'), (self.png, b"png")):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b)
        os.utime(self.glb, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        self.mtime = self.glb.stat().st_mtime_ns

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def keep(self, txn, p):
        return next(Path(f["keep"]) for f in txn["files"] if Path(f["path"]) == p)

    def test_links_the_glb_and_images_and_copies_the_json(self):
        txn = FR.snapshot(U, self.root / "logs/_txn" / U, link=True)
        self.assertTrue(os.path.samefile(self.keep(txn, self.glb), self.glb))
        self.assertTrue(os.path.samefile(self.keep(txn, self.png), self.png))
        self.assertFalse(os.path.samefile(self.keep(txn, self.look), self.look))
        full = FR.snapshot(U, self.root / "logs/_txn" / U)            # the full routes copy (Blender may write in place)
        self.assertFalse(os.path.samefile(self.keep(full, self.glb), self.glb))

    def test_a_replaced_glb_restores_from_the_linked_inode(self):
        txn = FR.snapshot(U, self.root / "logs/_txn" / U, link=True)
        tmp = self.glb.with_name(self.glb.name + ".unit_look.tmp")
        tmp.write_bytes(b"new delivery")
        os.replace(tmp, self.glb)                                     # look apply's write
        self.look.write_text('{"deliveredGlbSha256": "new"}')
        self.assertEqual(self.keep(txn, self.glb).read_bytes(), b"looked delivery")
        out = FR.restore(txn)
        self.assertEqual(self.glb.read_bytes(), b"looked delivery")
        self.assertEqual(self.glb.stat().st_mtime_ns, self.mtime)
        self.assertEqual(self.look.read_bytes(), b'{"deliveredGlbSha256": "old"}')
        self.assertEqual(set(out["replaced"]), {self.glb.name, "stamp.json"})

    def test_an_in_place_write_through_the_link_fails_closed(self):
        txn = FR.snapshot(U, self.root / "logs/_txn" / U, link=True)
        self.glb.write_bytes(b"written in place")                    # a regression: the route must never do this
        with self.assertRaises(RuntimeError):
            FR.restore(txn)
        self.assertTrue(Path(txn["dir"]).exists())

    def test_main_links_only_on_from_base(self):
        seen = []

        def rebuild(u, rec):
            seen.append(os.path.samefile(self.keep(json.loads((self.root / f"logs/_txn/{U}/txn.json").read_text()),
                                                   self.glb), self.glb))
            raise RuntimeError("refused")
        for argv in (["fleet_rebuild.py", U], ["fleet_rebuild.py", "--from-base", U]):
            with patch.object(FR, "rebuild", rebuild), patch.object(FR, "chain_errors", lambda u, r: []), \
                    patch.object(FR, "gate_faults", lambda u, glb: set()), patch.object(sys, "argv", argv):
                FR.main()
        self.assertEqual(seen, [False, True])
        self.assertEqual(self.glb.read_bytes(), b"looked delivery")


class FusedStages(unittest.TestCase):
    """fleet_rebuild runs the delivery stages in process on the GLB's bytes: each stage's input is the previous one's
    output, skipped stages record their reason, a refused stage writes nothing, and the sidecars are written before the
    one GLB write (none on --from-base, where look apply writes the delivery)."""

    def setUp(self):
        import types
        import stage_sidecar as SS
        self.SS = SS
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.glb = self.root / f"{U}_def_retarget.glb"
        self.glb.write_bytes(b"old delivery")
        self.log = self.root / "log.txt"
        self.log.write_text("")
        self.calls, self.refuse, self.skip = [], set(), set()
        glb = self.glb

        def stage(suffix):
            def apply(u, b, p=None, out=None):
                self.calls.append((suffix, b))
                if suffix in self.refuse:
                    raise SystemExit(f"{u}: {suffix} refused")
                if suffix in self.skip:
                    return None
                new = b + f"|{suffix}".encode()
                return SS.result(new, b, suffix, SS.record("s", u, glb, SS.sha(b), SS.sha(new)), {"unit": u})
            return apply
        mods = {k: types.SimpleNamespace(apply_bytes=stage(k), canonical_glb=lambda u: glb)
                for k in ("patch", "move_lowpass", "densify", "prop_floor", "cs_rekey", "ground")}
        mods["deyaw"] = types.SimpleNamespace(deyaw_bytes=stage("deyaw"), canonical_glb=lambda u: glb)
        sm = stage("stride_match")
        mods["stride_match"] = types.SimpleNamespace(
            apply_bytes=lambda a, b: ((lambda r: (r, None if r else {"unit": U, "skipped": "flier"}))(sm(a.unit, b))),
            build_parser=lambda: types.SimpleNamespace(parse_args=lambda argv: types.SimpleNamespace(unit=argv[1])))
        self.patches = [patch.object(FR, "delivery_stage_modules", lambda: mods), patch.object(FR, "FROM_BASE", [False])]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def run_stages(self, cfg=None):
        rec = {"steps": []}

        def step(name, rc):
            rec["steps"].append({"step": name, "rc": rc})
            if rc != 0:
                raise RuntimeError(f"{name} rc={rc}")
        return FR.fused_delivery_stages(U, rec, [b"export"], cfg or {}, self.log, step), rec

    def test_each_stage_takes_the_previous_output_and_the_glb_is_written_once(self):
        self.skip = {"move_lowpass", "densify"}
        out, rec = self.run_stages({"yawDeg": 30, "extensions": ["castle_yaw"]})
        self.assertEqual([c for c, _ in self.calls],
                         ["patch", "deyaw", "stride_match", "move_lowpass", "densify", "prop_floor", "cs_rekey", "ground"])
        self.assertEqual(out, b"export|patch|deyaw|stride_match|prop_floor|cs_rekey|ground")
        self.assertEqual(self.glb.read_bytes(), out)
        self.assertEqual([s["step"] for s in rec["steps"]],
                         ["glb patch apply", "deyaw", "stride_match apply", "prop_floor apply", "cs_rekey apply",
                          "ground apply"])
        self.assertEqual((rec["moveLowPass"], rec["densify"], rec["deyawed"]),
                         ("skipped: no moveLowPass", "skipped: no deliveryDensify", 30))
        prev = FR.sha_bytes(b"export")
        for suffix in ("patch", "deyaw", "stride_match", "prop_floor", "cs_rekey", "ground"):
            sc = json.loads(Path(f"{self.glb}.{suffix}.json").read_text())
            self.assertEqual(sc["sourceGlbSha256"], prev, suffix)
            prev = sc["outputGlbSha256"]
        self.assertEqual(prev, FR.sha_bytes(out))
        self.assertFalse(Path(f"{self.glb}.densify.json").exists())

    def test_cs_rekey_gets_the_post_patch_bytes_as_its_reference(self):
        seen = []
        orig = FR.delivery_stage_modules()["cs_rekey"].apply_bytes

        def rekey(u, b, ref, out):
            seen.append(ref)
            return orig(u, b, ref, out)
        FR.delivery_stage_modules()["cs_rekey"].apply_bytes = rekey
        self.run_stages()
        self.assertEqual(seen, [b"export|patch"])

    def test_from_base_writes_the_sidecars_but_no_glb(self):
        with patch.object(FR, "FROM_BASE", [True]):
            out, _ = self.run_stages()
        self.assertEqual(self.glb.read_bytes(), b"old delivery")
        self.assertEqual(json.loads(Path(f"{self.glb}.ground.json").read_text())["outputGlbSha256"], FR.sha_bytes(out))

    def test_a_refused_stage_writes_nothing(self):
        self.refuse = {"prop_floor"}
        with self.assertRaises(RuntimeError) as cm:
            self.run_stages()
        self.assertIn("prop_floor apply rc=1", str(cm.exception))
        self.assertEqual(self.glb.read_bytes(), b"old delivery")
        self.assertEqual(list(self.root.glob("*.json")), [])
        self.assertIn("prop_floor refused", self.log.read_text())

    def test_the_ground_stage_cannot_be_skipped(self):
        self.skip = {"ground"}
        with self.assertRaises(RuntimeError):
            self.run_stages()
        self.assertEqual(self.glb.read_bytes(), b"old delivery")


class RawAcceptedLook(unittest.TestCase):
    """A rawAccepted unit re-earns its raw delivery (try-modes, review stages, accept-raw) instead of look --force,
    which would regrade it and refuse; the reason keeps the prior one and records this GLB's numbers once."""

    def test_reason_keeps_the_prior_reason_and_replaces_the_rebuild_numbers(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            for mode, v in (("v7c", 8.3), ("v6m", 4.5)):
                (d / f"try_{mode}_metrics.json").write_text(json.dumps(
                    {"review": {"summary": {"meanLhistBodyLook": v, "meanLhistBodyRaw": 4.2}}}))
            prior = {"kind": FR.RAW_ACCEPTED, "rawAccepted": {
                "reason": "raw beats both modes; coordinator-approved | fleet_rebuild 2026-01-01: body L-hist raw 9"}}
            r = FR.accept_raw_reason(prior, d)
            self.assertTrue(r.startswith("raw beats both modes; coordinator-approved | fleet_rebuild "))
            self.assertEqual(r.count(FR.REBUILD_NOTE), 1)
            self.assertIn("body L-hist raw 4.2, v6m 4.5, v7c 8.3", r)

    def test_missing_or_inconsistent_tries_and_a_reasonless_stamp_refuse(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            prior = {"kind": FR.RAW_ACCEPTED, "rawAccepted": {"reason": "why"}}
            with self.assertRaises(RuntimeError):
                FR.accept_raw_reason(prior, d)
            for mode, raw in (("v7c", 4.2), ("v6m", 4.3)):
                (d / f"try_{mode}_metrics.json").write_text(json.dumps(
                    {"review": {"summary": {"meanLhistBodyLook": 5.0, "meanLhistBodyRaw": raw}}}))
            with self.assertRaises(RuntimeError):
                FR.accept_raw_reason(prior, d)
            with self.assertRaises(RuntimeError):
                FR.accept_raw_reason({"kind": FR.RAW_ACCEPTED, "rawAccepted": {}}, d)

    def test_the_look_step_branches_on_the_prior_stamp(self):
        src = (HERE / "fleet_rebuild.py").read_text(encoding="utf-8")
        i = src.index('if prior.get("kind") == RAW_ACCEPTED:')
        block = src[i:src.index("LOOK_DELIVERED_STEP", i)]
        order = [block.index(x) for x in ('*LOOK_TRY_STEP', '*LOOK_REVIEW_STEP', '"--accept-raw"', 'HOMM3_LOOK_SUPERSEDE_RAW', 'deliver_graded_look(look_step)')]
        self.assertEqual(order, sorted(order))
        # 2026-10-05: the plain look step keeps work/ (content-keyed terms cache); --force would wipe it every rebuild
        self.assertNotIn('"--force"', block)
        self.assertNotIn("--force", FR.LOOK_REVIEW_STEP[1] + FR.LOOK_FINISH_STEP[1])


class StaleWeights(unittest.TestCase):
    """A .blend skinned from NaN weight rows is rebuilt from scratch before anything re-exports it."""

    def test_counts_non_finite_rows_of_the_builds_weights(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as t:
            blend = Path(t) / "u_def_retarget.blend"
            self.assertEqual(FR.stale_weight_rows(blend), 0)
            W = np.ones((5, 3), np.float32)
            W[1, 0] = np.nan
            W[3] = np.inf
            np.savez(str(blend) + ".weights.npz", W=W)
            self.assertEqual(FR.stale_weight_rows(blend), 2)

    def test_the_stale_route_comes_before_every_other_route(self):
        src = (HERE / "fleet_rebuild.py").read_text(encoding="utf-8")
        body = src[src.index("def rebuild("):src.index("# the delivery chain starts here")]
        i = body.index("stale = 0 if FROM_BASE[0] else stale_weight_rows(blend)")
        # the Blender-free --from-base route is the only one ahead of it, and it runs no build step
        fb = body[body.index('rec["route"] = "from_base"'):body.index("elif stale:")]
        self.assertNotIn("run(", fb)
        self.assertLess(i, body.index('rec["route"] = "emphasis_redeliver"'))
        self.assertLess(i, body.index('rec["route"] = "direct_rebake"'))
        block = body[i:body.index("elif stamp.get(\"decision\") == \"emphasised\"")]
        self.assertLess(block.index("run_unit full build"), block.index("direct_rebake()"))


class StaleEmphasisStamp(unittest.TestCase):
    """A canonical a plain build replaced after an "emphasised" stamp is routed as a fresh build."""
    ST = {"decision": "emphasised", "emphasisedBlendSha256": "eb", "sourceBlendSha256": "sb", "emphasisedGlbSha256": "eg"}

    def test_neither_blend_nor_glb_matches(self):
        self.assertTrue(FR.stale_emphasis_stamp(self.ST, "raw", "rawglb", {}))

    def test_any_match_keeps_the_emphasis_route(self):
        for blend, glb, extras in (("eb", "rawglb", {}), ("sb", "rawglb", {}), ("raw", "eg", {}),
                                   ("raw", "rawglb", {"homm3DefRetargetEmphasis": {}})):
            with self.subTest(blend=blend, glb=glb, extras=extras):
                self.assertFalse(FR.stale_emphasis_stamp(self.ST, blend, glb, extras))

    def test_only_an_emphasised_stamp_can_be_stale(self):
        for d in ("unchanged", "stretchGateFailed", None):
            self.assertFalse(FR.stale_emphasis_stamp(dict(self.ST, decision=d), "raw", "rawglb", {}))
        self.assertFalse(FR.stale_emphasis_stamp({}, "raw", "rawglb", {}))

    def test_the_route_sits_between_stale_weights_and_emphasis_redeliver(self):
        src = (HERE / "fleet_rebuild.py").read_text(encoding="utf-8")
        body = src[src.index("def rebuild("):src.index("# the delivery chain starts here")]
        i = body.index('rec["route"] = "fresh_build_stale_emphasis_stamp"')
        self.assertLess(body.index('rec["route"] = "stale_weights_rebuild"'), i)
        self.assertLess(i, body.index('rec["route"] = "emphasis_redeliver"'))
        self.assertIn("direct_rebake()", body[i:body.index('rec["route"] = "emphasis_redeliver"')])


class GateFaults(unittest.TestCase):
    """gate_faults carries freeze_slice's stride gate: a rebuild that newly skates rolls back as freeze would refuse it
    (2026-09-28 hota_bulwark_shaman: the ground stage lifted a stride-planted Move to slip 0.765 > 0.686, unseen)."""

    def faults(self, stride):
        import flyer_articulation as FA
        import ground_check as GCk
        import stride_match_glb as SM
        with patch.object(FA, "freeze_check", lambda u, g: ([], {})), patch.object(GCk, "ground_check", lambda u, g: ([], {})),                 patch.object(FA, "glb_clips", lambda g: {FA.GATE_CLIP: {}}), patch.object(FA, "gate", lambda m, u: []),                 patch.object(SM, "gate_faults", stride):
            return FR.gate_faults(U, Path("x.glb"))

    def test_stride_words_become_keys(self):
        self.assertEqual(self.faults(lambda u, g: ["slip"]), {"stride:slip"})
        self.assertEqual(self.faults(lambda u, g: []), set())

    def test_an_unmeasurable_stride_is_a_fault(self):
        def boom(u, g):
            raise SystemExit("walker has fewer than two walking chains")
        self.assertEqual(self.faults(boom), {"measure:stride SystemExit"})

    def test_the_stride_gate_uses_freezes_thresholds(self):
        import stride_match_glb as SM
        src = (HERE / "stride_match_glb.py").read_text(encoding="utf-8")
        body = src[src.index("def gate_faults("):src.index("def cmd_check(")]
        self.assertIn('stride_faults_after(unit, res["slipRatio"], res["requiredOverActual"], DEFAULT_MAX_SLIP, MAX_RATIO)', body)
        ge = (HERE / "gate_exceptions.py").read_text(encoding="utf-8")
        self.assertIn('if slip > max_slip', ge)
        self.assertIn('if ratio > max_ratio', ge)
        fz = (HERE / "freeze_slice.py").read_text(encoding="utf-8")
        self.assertIn("DEFAULT_MAX_SLIP as STRIDE_MAX_SLIP, MAX_RATIO as STRIDE_MAX_RATIO", fz)
        self.assertLessEqual(SM.DEFAULT_MAX_SLIP, 1.0)


if __name__ == "__main__":
    unittest.main()
