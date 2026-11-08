"""Tests for ship_def_retarget_slice.py repin (runtime record pin refresh, fail closed, dry run by default).

    python tools/homm3_def_retarget_delivery/test_ship_repin.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import import_bindings as IB  # noqa: E402
import ship_def_retarget_slice as S  # noqa: E402

A = {"labSid": "u_a", "bundleName": "custom_units_u_a", "gameSid": "g_a"}
B = {"labSid": "u_b", "bundleName": "custom_units_u_b", "gameSid": "g_b"}
TABLE = {"battleWorldHeightPerHex": 1.0, "entries": [
    {"battlePrefabAssetPath": "Assets/CustomUnits/homm3_lab/u_a/OwnedSkinned/owned_skinned.prefab",
     "bundleName": "custom_units_u_a", "gameUnitSids": ["g_a"]},
    {"battlePrefabAssetPath": "Assets/CustomUnits/homm3_lab/u_b/OwnedSkinned/owned_skinned.prefab",
     "bundleName": "custom_units_u_b", "gameUnitSids": ["g_b"]}]}


def record(units=(A,), fx=None):
    return {"schema": "x", "meshFx": dict(fx if fx is not None else {"fx/catalog.json": "old"}),
            IB.KEY: IB.pin(TABLE, list(units))}


def same(v):
    return lambda rel: v


class PlanRepin(unittest.TestCase):
    def test_repins_identical_meshfx(self):
        p = S.plan_repin(record(), [A], TABLE, same("new"), same("new"), same("new"))
        self.assertEqual(p, {"meshFx": {"fx/catalog.json": ("old", "new")}, "importBindings": {}})

    def test_current_record_is_a_noop(self):
        p = S.plan_repin(record(fx={"fx/catalog.json": "new"}), [A], TABLE, same("new"), same("new"), same("new"))
        self.assertEqual(p, {"meshFx": {}, "importBindings": {}})

    def test_refuses_when_worktree_head_installed_differ(self):
        for w, h, i in (("new", "new", "inst"), ("new", "head", "new"), (None, None, None), ("wt", "new", "new")):
            with self.assertRaises(S.ShipError):
                S.plan_repin(record(), [A], TABLE, same(w), same(h), same(i))

    def test_adds_missing_binding_only_for_selection_units(self):
        p = S.plan_repin(record(), [A, B], TABLE, same("new"), same("new"), same("new"))
        self.assertEqual(p["importBindings"], {"u_b": IB.unit_digest(TABLE, B)})

    def test_refuses_pin_outside_selection(self):
        with self.assertRaises(S.ShipError):
            S.plan_repin(record(units=(A, B)), [A], TABLE, same("new"), same("new"), same("new"))

    def test_refuses_changed_own_binding(self):
        t = json.loads(json.dumps(TABLE))
        t["entries"][0]["gameUnitSids"].append("g_extra")
        with self.assertRaises(S.ShipError):
            S.plan_repin(record(), [A], t, same("new"), same("new"), same("new"))

    def test_refuses_unit_without_binding(self):
        c = {"labSid": "u_c", "bundleName": "custom_units_u_c", "gameSid": "g_c"}
        with self.assertRaises(S.ShipError):
            S.plan_repin(record(), [A, c], TABLE, same("new"), same("new"), same("new"))

    def test_apply_notes_and_check(self):
        rec = record()
        p = S.plan_repin(rec, [A, B], TABLE, same("new"), same("new"), same("new"))
        new = S.apply_repin(rec, p, "s", "abc", "2026-10-01T00:00:00")
        IB.check(new[IB.KEY], TABLE, [A, B], "t")
        self.assertEqual(new["meshFx"]["fx/catalog.json"], "new")
        self.assertIn("meshFxNote", new)
        self.assertIn("importBindingsNote", new)
        self.assertEqual(rec["meshFx"]["fx/catalog.json"], "old")   # the input is not mutated


class RepinStage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(dir=S.ROOT / "artifacts"))
        rel = self.tmp.relative_to(S.ROOT).as_posix()
        self.sel = {"out": rel, "units": [A, B]}
        (self.tmp / "plugin/fx").mkdir(parents=True)
        (self.tmp / "installed/fx").mkdir(parents=True)
        for d in ("plugin", "installed"):
            (self.tmp / d / "fx/catalog.json").write_text("{}", encoding="utf-8")
        (self.tmp / "table.json").write_text(json.dumps(TABLE), encoding="utf-8")
        self.rp = self.tmp / S.RUNTIME_RECORD
        self.rp.write_text(json.dumps(record()), encoding="utf-8")
        self.kw = {"plugin_dir": self.tmp / "plugin", "installed_dir": self.tmp / "installed",
                   "table_path": self.tmp / "table.json",
                   "head_sha": lambda rel: S.sha(self.tmp / "plugin" / rel)}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_dry_run_writes_nothing(self):
        before = self.rp.read_bytes()
        p = S.repin_stage(Path("x_slice.json"), self.sel, False, **self.kw)
        self.assertTrue(p["meshFx"] and p["importBindings"])
        self.assertEqual(self.rp.read_bytes(), before)
        self.assertEqual(sorted(f.name for f in self.tmp.glob("runtime_capability_build*")), [S.RUNTIME_RECORD])

    def test_write_backs_up_and_applies(self):
        S.repin_stage(Path("x_slice.json"), self.sel, True, **self.kw)
        new = json.loads(self.rp.read_text(encoding="utf-8"))
        IB.check(new[IB.KEY], TABLE, [A, B], "t")
        self.assertEqual(new["meshFx"]["fx/catalog.json"], S.sha(self.tmp / "plugin/fx/catalog.json"))
        self.assertEqual(len(list(self.tmp.glob("runtime_capability_build.prerepin_*.json"))), 1)

    def test_write_refuses_divergent_install_and_leaves_record(self):
        (self.tmp / "installed/fx/catalog.json").write_text('{"x": 1}', encoding="utf-8")
        before = self.rp.read_bytes()
        with self.assertRaises(S.ShipError):
            S.repin_stage(Path("x_slice.json"), self.sel, True, **self.kw)
        self.assertEqual(self.rp.read_bytes(), before)

    def test_missing_record_refuses(self):
        self.rp.unlink()
        with self.assertRaises(S.ShipError):
            S.repin_stage(Path("x_slice.json"), self.sel, False, **self.kw)


if __name__ == "__main__":
    unittest.main()
