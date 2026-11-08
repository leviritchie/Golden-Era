#!/usr/bin/env python3
"""Focused synthetic tests for fail-closed current-scope override carrying.

Run: python tools/port_current/test_carry_scope_overrides.py
The fixtures replace matching and native file readers; no game data or binaries are loaded.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import carry_scope_overrides as carry  # noqa: E402


class FakeCore:
    def __init__(self, owner_number: int):
        self.key = ("m", owner_number)
        self.cat = "method"
        self.native_name = "OldMethod"
        self.rows = {}


class FakeIndex:
    def __init__(self, old: bool):
        if old:
            self.types = {
                "Old.Owner": SimpleNamespace(full="Old.Owner", asm="oldasm1",
                                              cores=[FakeCore(1), FakeCore(3)]),
                "Old.Owner2": SimpleNamespace(full="Old.Owner2", asm="oldasm2", cores=[FakeCore(2)]),
            }
        else:
            self.types = {}
            for owner_number in (1, 2):
                full = "New.Owner" if owner_number == 1 else "New.Owner2"
                self.types[full] = SimpleNamespace(
                    full=full, asm=f"newasm{owner_number}", runtime_full=full)


class FakeTypeMatcher:
    def __init__(self, *_args):
        pass

    def run(self):
        pass


class FakeRemapper:
    def __init__(self, *_args):
        pass

    def type_status(self, _owner):
        suffix = "2" if _owner.endswith("2") else ""
        return {"status": "MAPPED", "live": f"New.Owner{suffix}", "reason": None}

    def bindings(self, literal):
        if literal.startswith("OldType"):
            return [{"kind": "type", "goldenOwner": "Old.Owner", "liveOwner": "New.Owner",
                     "live": "NewType", "status": "MAPPED", "confidence": 0.99}]
        return [
            {"kind": "member", "memberCategory": "method", "goldenOwner": owner,
             "goldenCoreKey": ["m", token], "liveOwner": live_owner, "live": "NewMethod",
             "status": "MAPPED", "confidence": 0.99}
            for owner, token, live_owner in (
                ("Old.Owner", 1, "New.Owner"),
                ("Old.Owner", 3, "New.Owner"),
                ("Old.Owner2", 2, "New.Owner2"),
            )
        ]

    def members_of(self, owner):
        owner_numbers = (2,) if owner.endswith("2") else (1, 3)
        return {("m", number): SimpleNamespace(
            live=SimpleNamespace(cat="method", key=("m", number))) for number in owner_numbers}

    @staticmethod
    def aggregate(_literal, bindings):
        if not bindings:
            return {"status": "UNMAPPED", "live": None, "confidence": 0.0, "reason": "no binding"}
        binding = bindings[0]
        return {"status": binding["status"], "live": binding["live"], "confidence": binding["confidence"]}


class FakeNativeSide:
    missing_side: str | None = None
    missing_asm: str | None = None
    missing_key: tuple | None = None

    def __init__(self, _tsv, game_assembly, *_args):
        self.side = "old" if Path(game_assembly).name == "old.dll" else "new"

    def va_of(self, asm, core):
        if (self.side == self.missing_side and
                (self.missing_asm is None or asm == self.missing_asm) and
                (self.missing_key is None or tuple(core.key) == self.missing_key)):
            return None
        return 0x1000 if self.side == "old" else 0x2000

    def features(self, va):
        return {"va": va}


class CarryScopeOverridesTest(unittest.TestCase):
    def run_fixture(self, entry: dict, *, missing_side: str | None = None,
                    missing_asm: str | None = None, missing_key: tuple | None = None) -> tuple[dict, dict]:
        root = Path("fixture")
        old_idx, new_idx = root / "old_idx", root / "new_idx"
        overrides, shapes = root / "overrides.json", root / "shapes.tsv"
        output, report = root / "out.json", root / "report.json"
        override_doc = {
            "schema": carry.OVERRIDES_SCHEMA,
            "buildId": "25509697",
            "symbols": {"Fixture.Symbol": entry},
        }
        reads = {
            str(overrides): json.dumps(override_doc),
            str(old_idx / "inputs.json"): json.dumps({
                "steamBuildId": "25509697", "gameAssemblySha256": "oldsha", "metadataSha256": "oldmeta",
            }),
            str(new_idx / "inputs.json"): json.dumps({
                "steamBuildId": "25672315", "gameAssemblySha256": "newsha", "metadataSha256": "newmeta",
            }),
        }
        writes = {}
        args = [
            "--overrides", str(overrides), "--old-idx", str(old_idx), "--old-ga", str(root / "old.dll"),
            "--new-idx", str(new_idx), "--new-ga", str(root / "new.dll"), "--new-shapes", str(shapes),
            "--out-overrides", str(output), "--report", str(report),
        ]
        FakeNativeSide.missing_side = missing_side
        FakeNativeSide.missing_asm = missing_asm
        FakeNativeSide.missing_key = missing_key
        with patch.object(Path, "read_text", lambda self, *a, **k: reads[str(self)]), \
                patch.object(Path, "write_text", lambda self, data, **k: writes.__setitem__(str(self), data) or len(data)), \
                patch.object(Path, "mkdir", lambda self, *a, **k: None), \
                patch.object(carry.model, "load", side_effect=lambda path: FakeIndex("old_idx" in path)), \
                patch.object(carry.match, "TypeMatcher", FakeTypeMatcher), \
                patch.object(carry.remap, "Remapper", FakeRemapper), \
                patch.object(carry.native_body, "NativeSide", FakeNativeSide), \
                patch.object(carry.native_body, "similarity", return_value=0.95), \
                patch.object(carry, "load_shapes", return_value={"New.Owner": ["New.Owner", "System.Object", 1, 2, ""]}), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(carry.main(args), 0)
        return json.loads(writes[str(output)]), json.loads(writes[str(report)])

    @staticmethod
    def method_entry() -> dict:
        return {
            "goldenLiterals": ["OldMethod"],
            "live": ["OldMethod"],
            "owners": ["Old.Owner"],
            "evidence": "curated prior-build evidence",
        }

    def test_method_without_native_addresses_is_held_for_review(self):
        for side in ("old", "new"):
            with self.subTest(missing_side=side):
                output, report = self.run_fixture(self.method_entry(), missing_side=side)
                self.assertNotIn("Fixture.Symbol", output["symbols"])
                self.assertIn("native body address unavailable", report["needsReview"]["Fixture.Symbol"][0])
                self.assertNotIn("bodySim", report["details"]["Fixture.Symbol"][0])
                self.assertIn("pending manual re-derivation", output["note"])
                self.assertNotIn("re-derived by hand", output["note"])

    def test_every_owner_method_body_must_have_native_address_evidence(self):
        entry = self.method_entry()
        entry["owners"] = ["Old.Owner", "Old.Owner2"]
        output, report = self.run_fixture(entry, missing_side="old", missing_asm="oldasm2")
        self.assertNotIn("Fixture.Symbol", output["symbols"])
        self.assertIn("native body address unavailable", report["needsReview"]["Fixture.Symbol"][0])
        self.assertNotIn("bodySim", report["details"]["Fixture.Symbol"][0])

    def test_duplicate_native_literal_uses_each_exact_token_keyed_core(self):
        output, report = self.run_fixture(self.method_entry(), missing_side="old", missing_key=("m", 3))
        self.assertNotIn("Fixture.Symbol", output["symbols"])
        self.assertIn("native body address unavailable", report["needsReview"]["Fixture.Symbol"][0])
        self.assertNotIn("bodySim", report["details"]["Fixture.Symbol"][0])

    def test_remapper_binding_exposes_existing_core_key(self):
        remapper = object.__new__(carry.remap.Remapper)
        remapper.type_status = lambda _owner: {"status": "MAPPED", "live": "New.Owner", "confidence": 0.99}
        remapper.members_of = lambda _owner: {
            FakeCore(1).key: SimpleNamespace(
                live=SimpleNamespace(native_name="NewMethod"), confidence=0.99, method="fixture")}
        remapper.L = SimpleNamespace(types={"New.Owner": SimpleNamespace(runtime_full="New.Owner")})
        binding = carry.remap.Remapper.map_member_binding(
            remapper, SimpleNamespace(full="Old.Owner"), FakeCore(1), "native", "OldMethod")
        self.assertEqual(binding["goldenCoreKey"], ["m", 1])

    def test_short_type_checks_array_is_not_carried_or_truncated(self):
        entry = {
            "goldenLiterals": ["OldTypeA", "OldTypeB"],
            "live": ["OldTypeA", "OldTypeB"],
            "owners": ["Old.Owner"],
            "typeChecks": [["Old.Owner", "System.Object", 1, 1, ""]],
            "evidence": "curated prior-build evidence",
        }
        output, report = self.run_fixture(entry)
        self.assertNotIn("Fixture.Symbol", output["symbols"])
        self.assertIn("typeChecks length must equal live length (2)", report["needsReview"]["Fixture.Symbol"][0])
        self.assertEqual(report["details"]["Fixture.Symbol"], [])

    def test_oversized_and_non_array_type_checks_are_held_for_review(self):
        cases = (
            ([["Old.Owner", "System.Object", 1, 1, ""], ["Old.Owner", "System.Object", 1, 1, ""],
              ["Old.Owner", "System.Object", 1, 1, ""]], "typeChecks length must equal"),
            ({"not": "an array"}, "typeChecks must be an array"),
            (None, "typeChecks must be an array"),
        )
        for checks, expected_message in cases:
            with self.subTest(type_checks=checks):
                entry = {
                    "goldenLiterals": ["OldTypeA", "OldTypeB"],
                    "live": ["OldTypeA", "OldTypeB"],
                    "owners": ["Old.Owner"],
                    "typeChecks": checks,
                    "evidence": "curated prior-build evidence",
                }
                output, report = self.run_fixture(entry)
                self.assertNotIn("Fixture.Symbol", output["symbols"])
                self.assertIn(expected_message, report["needsReview"]["Fixture.Symbol"][0])
                self.assertEqual(report["details"]["Fixture.Symbol"], [])

    def test_split_entry_with_more_live_positions_remains_valid(self):
        entry = self.method_entry()
        entry.update({"goldenLiterals": ["OldMethod"], "live": ["OldMethod", "OldMethod"], "split": True})
        output, report = self.run_fixture(entry)
        carried = output["symbols"]["Fixture.Symbol"]
        self.assertEqual(carried["live"], ["NewMethod", "NewMethod"])
        self.assertEqual(carried["goldenLiterals"], ["OldMethod"])
        self.assertTrue(carried["split"])
        self.assertEqual(len(report["details"]["Fixture.Symbol"]), 2)


if __name__ == "__main__":
    unittest.main()
