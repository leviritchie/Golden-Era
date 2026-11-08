"""Unit/smoke tests for EquivTester using synthetic fixtures only."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

from olden_cs_recovery.equiv import EquivTestError, run_equiv_on_oracle, structural_diff
from olden_cs_recovery.oracle import load_oracle_trace
from olden_cs_recovery.paths import ORACLE_TRACES_SYNTHETIC_DIR, PACKAGE_ROOT

SYNTHETIC_FIXTURE = (
    ORACLE_TRACES_SYNTHETIC_DIR / "synthetic.EquivDiffEngineDemo_Apply.oracle.json"
)


class StructuralDiffTests(unittest.TestCase):
    def test_equal_objects(self) -> None:
        self.assertEqual(structural_diff({"a": 1, "b": [2, 3]}, {"a": 1, "b": [2, 3]}), [])

    def test_missing_field(self) -> None:
        diffs = structural_diff({"a": 1, "b": 2}, {"a": 1})
        self.assertTrue(any(d.get("reason") == "missing_field" for d in diffs))

    def test_float_tolerance(self) -> None:
        diffs = structural_diff(
            {"ratio": 0.6666666667},
            {"ratio": 0.6666666667001},
            tolerances={"$.ratio": 1e-09},
        )
        self.assertEqual(diffs, [])
        diffs_fail = structural_diff(
            {"ratio": 0.6666666667},
            {"ratio": 0.7},
            tolerances={"$.ratio": 1e-09},
        )
        self.assertTrue(diffs_fail)


class ReplayDefaultClassificationTests(unittest.TestCase):
    def test_short_obfuscated_tokens_are_value_enums(self) -> None:
        from olden_cs_recovery.replay import default_value_for_recovered_type

        self.assertEqual(
            default_value_for_recovered_type("ede"),
            {"enumType": "ede", "name": None, "value": 0},
        )

    def test_epascal_case_tokens_are_reference_null(self) -> None:
        from olden_cs_recovery.replay import default_value_for_recovered_type

        # Live construct snapshots prove EMechType / EFieldObjectType default to null.
        self.assertIsNone(default_value_for_recovered_type("EMechType"))
        self.assertIsNone(default_value_for_recovered_type("EFieldObjectType"))


class LiveExecutionOracleReplayTests(unittest.TestCase):
    """Regression: previously mismatched live_execution EventArgs must pass EquivTester."""

    def test_previously_mismatched_eventargs_pass(self) -> None:
        from olden_cs_recovery.equiv import run_equiv_on_oracle
        from olden_cs_recovery.oracle import load_oracle_trace
        from olden_cs_recovery.paths import ORACLE_TRACES_LIVE_DIR

        for stem in (
            "Hex.Session.Battle.HeroAbilityEndCdEventArgs_.ctor",
            "Hex.Session.Battle.ObjectSpawnedEventArgs_.ctor",
            "Hex.Session.Battle.ObjectTookDamageEventArgs_.ctor",
            "Hex.Session.Battle.BattleEventArgs_.ctor",
            "Hex.Session.Battle.AiDebugEventArgs_.ctor_int_BattleAiAction_EActionType",
        ):
            path = ORACLE_TRACES_LIVE_DIR / f"{stem}.oracle.json"
            self.assertTrue(path.is_file(), f"missing {path}")
            oracle = load_oracle_trace(path)
            self.assertEqual(oracle.get("capture_kind"), "live_execution")
            result = run_equiv_on_oracle(oracle)
            self.assertTrue(result["ok"], stem)
            self.assertEqual(result["status"], "equivalence-proven")


class SyntheticEquivTests(unittest.TestCase):
    def test_synthetic_fixture_passes(self) -> None:
        self.assertTrue(SYNTHETIC_FIXTURE.is_file(), f"missing {SYNTHETIC_FIXTURE}")
        oracle = load_oracle_trace(SYNTHETIC_FIXTURE)
        self.assertTrue(oracle["synthetic"])
        self.assertTrue(oracle["method_id"].startswith("synthetic."))
        result = run_equiv_on_oracle(oracle, allow_synthetic=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "equivalence-proven")

    def test_synthetic_mismatch_fails(self) -> None:
        oracle = load_oracle_trace(SYNTHETIC_FIXTURE)
        bad = copy.deepcopy(oracle)
        bad["outputs"]["recovered_replay"]["sum"] = 999
        with self.assertRaises(EquivTestError) as ctx:
            run_equiv_on_oracle(bad, allow_synthetic=True)
        self.assertEqual(ctx.exception.code, "equiv_diff_failed")

    def test_synthetic_cannot_prove_real_method_id(self) -> None:
        oracle = load_oracle_trace(SYNTHETIC_FIXTURE)
        bad = copy.deepcopy(oracle)
        bad["method_id"] = "Hex.Session.Battle.SimpleBoolEventArgs::.ctor()"
        # synthetic flag still true but method_id not synthetic.*
        with self.assertRaises(EquivTestError) as ctx:
            run_equiv_on_oracle(bad, allow_synthetic=True)
        self.assertIn(ctx.exception.code, {"synthetic_method_id_required", "synthetic_blocks_real_method"})

    def test_surface_metadata_never_equivalence_proven(self) -> None:
        oracle = {
            "schema_version": 1,
            "method_id": "synthetic.SurfaceOnly::Noop",
            "capture_kind": "live_surface_metadata",
            "synthetic": True,
            "game_build_id": "synthetic-harness",
            "gameassembly_sha256": "SYNTHETIC_NOT_A_REAL_GAMEASSEMBLY_HASH_0000000000000000",
            "captured_at": "2026-07-20T00:00:00Z",
            "inputs": {},
            "outputs": {"runtime_fields": []},
            "protocol": {"name": "t", "version": 1, "notes": "synthetic surface"},
        }
        with self.assertRaises(EquivTestError) as ctx:
            run_equiv_on_oracle(oracle, allow_synthetic=True)
        self.assertEqual(ctx.exception.code, "bar_c_requires_execution_oracle")

    def test_missing_recovered_replay_fails_closed(self) -> None:
        oracle = load_oracle_trace(SYNTHETIC_FIXTURE)
        bad = copy.deepcopy(oracle)
        del bad["outputs"]["recovered_replay"]
        with self.assertRaises(EquivTestError) as ctx:
            run_equiv_on_oracle(bad, allow_synthetic=True)
        self.assertEqual(ctx.exception.code, "missing_recovered_replay")


def main() -> int:
    # Ensure package root is importable when run as module or script.
    pkg = str(PACKAGE_ROOT)
    if pkg not in sys.path:
        sys.path.insert(0, pkg)
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
