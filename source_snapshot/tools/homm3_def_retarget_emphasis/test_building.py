"""deliver.building(): only a real builder holds a unit (Blender, or python / bash running a build script that names
it); a read-only python whose argv merely lists the unit (a dry run, a validator) does not.

    python -m unittest tools/homm3_def_retarget_emphasis/test_building.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import deliver as D  # noqa: E402

U = "toa_ghost_behemoth"
PY = r"C:\Python312\python.exe"


def procs(*rows):
    return {pid: (0, name, cl) for pid, name, cl in rows}


class Building(unittest.TestCase):
    def test_a_dry_run_listing_the_fleet_does_not_hold_a_unit(self):
        p = procs((10, "python.exe", f"{PY} artifacts/scratch/dry.py h3_behemoth {U} h3_ogre"),
                  (11, "python.exe", f"{PY} tools/validate_homm3_unit_look_contract.py --unit {U}"))
        self.assertEqual(D.holders(U, p, set()), [])

    def test_real_builders_hold_the_unit(self):
        for name, cl in (("python.exe", rf"{PY} V:\x\tools\homm3_def_retarget_emphasis\deliver.py {U} --force"),
                         ("python.exe", f"{PY} tools/homm3_def_retarget_delivery/fleet_rebuild.py {U}"),
                         ("python.exe", f"{PY} tools/homm3_unit_look/look.py {U} --force"),
                         ("python.exe", f"{PY} tools/homm3_def_retarget_delivery/ground_glb.py apply {U}"),
                         ("bash.exe", f"bash tools/homm3_def_retarget/run_unit.sh {U}"),
                         ("blender.exe", f"blender -b V:/a/artifacts/homm3_def_retarget/{U}/{U}_def_retarget.blend -P x.py")):
            self.assertEqual(D.holders(U, procs((20, name, cl)), set()), [20], cl)

    def test_a_builder_for_another_unit_does_not_hold_it(self):
        p = procs((30, "python.exe", f"{PY} tools/homm3_def_retarget_delivery/fleet_rebuild.py h3_behemoth"))
        self.assertEqual(D.holders(U, p, set()), [])

    def test_this_process_and_its_ancestors_are_not_counted(self):
        p = procs((40, "python.exe", f"{PY} tools/homm3_def_retarget_emphasis/deliver.py {U}"))
        self.assertEqual(D.holders(U, p, {40}), [])

    def test_the_rebuild_chain_that_launched_deliver_is_not_a_holder(self):
        # unit_writer -> fleet_rebuild -> deliver, all builders naming the unit: deliver's own ancestry is this build
        p = {1: (0, "explorer.exe", "explorer"),
             50: (1, "python.exe", f"{PY} tools/homm3_def_retarget/unit_writer.py {U} -- python fleet_rebuild.py {U}"),
             51: (50, "python.exe", f"{PY} tools/homm3_def_retarget_delivery/fleet_rebuild.py {U}"),
             52: (51, "python.exe", f"{PY} tools/homm3_def_retarget_emphasis/deliver.py {U} --force"),
             60: (1, "python.exe", f"{PY} tools/homm3_def_retarget_delivery/fleet_rebuild.py {U}")}   # another agent
        mine = D.ancestry(p, 52)
        self.assertEqual(mine, {52, 51, 50, 1})
        self.assertEqual(D.holders(U, p, mine), [60])
        del p[60]
        self.assertEqual(D.holders(U, p, D.ancestry(p, 52)), [])


class NotDoneExit(unittest.TestCase):
    """A deferred / errored / failed emphasis step exits non-zero, so fleet_rebuild cannot count it as OK."""

    def test_not_done_decisions_fail(self):
        for d in ("deferred-busy", "error", "failed"):
            self.assertEqual(D.not_done_exit([{"unit": U, "decision": d}]), D.NOT_DONE_EXIT, d)

    def test_done_decisions_pass(self):
        for d in ("emphasised", "unchanged", "up-to-date", "stretchGateFailed", "exception"):
            self.assertEqual(D.not_done_exit([{"unit": U, "decision": d}]), 0, d)

    def test_a_deferred_unit_done_on_its_retry_passes(self):
        self.assertEqual(D.not_done_exit([{"unit": U, "decision": "deferred-busy"},
                                          {"unit": U, "decision": "emphasised"}]), 0)
        self.assertEqual(D.not_done_exit([{"unit": U, "decision": "deferred-busy"},
                                          {"unit": U, "decision": "deferred-busy"}]), D.NOT_DONE_EXIT)


if __name__ == "__main__":
    unittest.main()
