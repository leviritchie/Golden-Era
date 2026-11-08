"""Field-delta EquivTester helpers (no live game required)."""

from __future__ import annotations

import unittest

from olden_cs_recovery.field_delta import compare_field_delta, expected_field_delta_engine
from olden_cs_recovery.equiv import EquivTestError, run_equiv_on_oracle


class FieldDeltaExpectationTests(unittest.TestCase):
    def test_bcyl_expectation_has_real_diff(self) -> None:
        exp = expected_field_delta_engine("Hex.Session.Battle.Hex::bcyl(FieldObject)")
        self.assertTrue(exp["hasRealDiff"])
        self.assertIn("fieldObjectsCount", exp["fieldDelta"])

    def test_bdhv_expectation_has_no_real_diff(self) -> None:
        exp = expected_field_delta_engine("eep::bdhv(Unit,Hex)")
        self.assertFalse(exp["hasRealDiff"])

    def test_compare_accepts_matching_bcyl(self) -> None:
        exp = expected_field_delta_engine("Hex.Session.Battle.Hex::bcyl(FieldObject)")
        live = {
            "hasRealDiff": True,
            "fieldDelta": {
                "fieldObjectsCount": {"from": 0, "to": 1},
                "membershipContainsFo": {"from": False, "to": True},
                "cfqg": {"from": False, "to": True},  # extra corroboration allowed
            },
        }
        self.assertEqual(compare_field_delta(exp, live), [])

    def test_compare_rejects_empty_live_diff(self) -> None:
        exp = expected_field_delta_engine("Hex.Session.Battle.Hex::bcyl(FieldObject)")
        live = {"hasRealDiff": False, "fieldDelta": {}}
        diffs = compare_field_delta(exp, live)
        self.assertTrue(any(d.get("reason") == "live_has_no_real_diff" for d in diffs))

    def test_equiv_refuses_field_delta_without_real_diff(self) -> None:
        oracle = {
            "schema_version": 1,
            "method_id": "eep::bdhv(Unit,Hex)",
            "capture_kind": "live_execution",
            "synthetic": False,
            "game_build_id": "0.1.299",
            "gameassembly_sha256": "A" * 64,
            "captured_at": "2026-07-20T12:00:00Z",
            "inputs": {},
            "outputs": {
                "engine": {
                    "hasRealDiff": False,
                    "fieldDelta": {},
                    "before": {"completed": False},
                    "after": {"completed": True},
                }
            },
            "protocol": {
                "name": "olden_cs_recovery.live_execution.field_delta",
                "version": 1,
                "notes": "test",
            },
        }
        with self.assertRaises(EquivTestError) as ctx:
            run_equiv_on_oracle(oracle)
        self.assertIn(ctx.exception.code, {"field_delta_requires_real_diff", "equiv_diff_failed"})


if __name__ == "__main__":
    unittest.main()
