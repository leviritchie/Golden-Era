"""Nested-field + null-throw EventArgs must lift and classify after disasm grounding."""

from __future__ import annotations

import unittest
from pathlib import Path

from olden_cs_recovery.lifter.address_map import load_address_map
from olden_cs_recovery.lifter.ir_build import build_ir
from olden_cs_recovery.lifter.isil_parse import (
    match_isil_method,
    parse_diffable_fields_with_bases,
    parse_isil_file,
)
from olden_cs_recovery.paths import REPO_ROOT
from olden_cs_recovery.replay import (
    is_nested_null_guarded_field_copy_ctor,
    nested_null_guarded_field_copy_plan,
)

DIFFABLE_BATTLE = (
    REPO_ROOT
    / "tmp"
    / "cpp2il_experiment"
    / "out_dev_diffable_cs"
    / "DiffableCs"
    / "Hex"
    / "Hex"
    / "Session"
    / "Battle"
)
ISIL_BATTLE = (
    REPO_ROOT
    / "tmp"
    / "cpp2il_experiment"
    / "out_dev_isil"
    / "IsilDump"
    / "Hex"
    / "Hex"
    / "Session"
    / "Battle"
)
ADDR_MAP = (
    REPO_ROOT
    / "experiments"
    / "cpp2il_readable_csharp"
    / "samples"
    / "latest_refresh"
    / "address_map_hex_session_battle.json"
)


def _lift(type_file: str, method_id: str, method_name: str = ".ctor") -> dict:
    diffable = DIFFABLE_BATTLE / type_file
    isil = ISIL_BATTLE / type_file.replace(".cs", ".txt")
    type_name = "Hex.Session.Battle." + type_file.replace(".cs", "")
    methods = parse_isil_file(isil)
    isil_method = match_isil_method(
        methods, type_name=type_name, method_name=method_name, method_id=method_id
    )
    fields = parse_diffable_fields_with_bases(diffable)
    address_map = load_address_map(ADDR_MAP) if ADDR_MAP.is_file() else None
    return build_ir(
        method_id=method_id,
        type_name=type_name,
        method_name=method_name,
        isil_method=isil_method,
        fields=fields,
        address_map=address_map,
        sources={
            "diffable_cs": str(diffable),
            "isil": str(isil),
            "address_map": str(ADDR_MAP) if ADDR_MAP.is_file() else None,
            "native_disasm": None,
        },
        native_address=None,
        native_disasm_present=False,
    )


class NestedNullThrowTests(unittest.TestCase):
    def test_energyupdate_eir_int_resolves_null_throws_and_nested_plan(self) -> None:
        if not (DIFFABLE_BATTLE / "EnergyUpdateEventArgs.cs").is_file():
            self.skipTest("DiffableCs EnergyUpdateEventArgs missing")
        ir = _lift(
            "EnergyUpdateEventArgs.cs",
            "Hex.Session.Battle.EnergyUpdateEventArgs::.ctor(eir,int)",
        )
        codes = {u.get("code") for u in ir.get("unresolved") or []}
        self.assertIn("null_throw_helper_branch", codes)
        self.assertNotIn("opaque_branch_target", codes)
        self.assertTrue(is_nested_null_guarded_field_copy_ctor(ir))
        plan = nested_null_guarded_field_copy_plan(ir)
        assert plan is not None
        self.assertEqual([p["field"] for p in plan], ["side", "energy", "energyDistribution", "energyDelta"])

    def test_unitstartedmovement_resolves_null_throw_and_nested_id(self) -> None:
        if not (DIFFABLE_BATTLE / "UnitStartedMovementEventArgs.cs").is_file():
            self.skipTest("DiffableCs UnitStartedMovementEventArgs missing")
        ir = _lift(
            "UnitStartedMovementEventArgs.cs",
            "Hex.Session.Battle.UnitStartedMovementEventArgs::.ctor(float,float,int,Unit,EMovementType,Hex[],bool)",
        )
        codes = {u.get("code") for u in ir.get("unresolved") or []}
        self.assertIn("null_throw_helper_branch", codes)
        self.assertNotIn("opaque_branch_target", codes)
        self.assertTrue(is_nested_null_guarded_field_copy_ctor(ir))
        plan = nested_null_guarded_field_copy_plan(ir)
        assert plan is not None
        id_step = next(p for p in plan if p["field"] == "id")
        self.assertEqual(id_step["from"], "nested")
        self.assertEqual(id_step["root_arg"], 3)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
