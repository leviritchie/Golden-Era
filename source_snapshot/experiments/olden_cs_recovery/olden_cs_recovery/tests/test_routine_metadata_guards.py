"""Routine metadata/class-init guards must not block EventArgs base-only execution plans."""

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
    field_assign_plan_from_ir,
    is_base_only_parameterless_ctor,
    is_base_then_param_field_assign_ctor,
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


class RoutineMetadataGuardTests(unittest.TestCase):
    def test_battleeventargs_ctor_is_base_only_after_guard_classification(self) -> None:
        if not (DIFFABLE_BATTLE / "BattleEventArgs.cs").is_file():
            self.skipTest("DiffableCs BattleEventArgs missing")
        ir = _lift(
            "BattleEventArgs.cs",
            "Hex.Session.Battle.BattleEventArgs::.ctor()",
        )
        codes = {u.get("code") for u in ir.get("unresolved") or []}
        self.assertIn("routine_metadata_guard_branch", codes)
        self.assertNotIn("opaque_branch_target", codes)
        labels = [c.get("resolved_label") for c in ir.get("calls") or []]
        self.assertTrue(
            any(lab and "System.EventArgs::.ctor()" in lab for lab in labels),
            labels,
        )
        self.assertTrue(is_base_only_parameterless_ctor(ir))

    def test_aidebug_becomes_param_field_assign_after_guards(self) -> None:
        if not (DIFFABLE_BATTLE / "AiDebugEventArgs.cs").is_file():
            self.skipTest("DiffableCs AiDebugEventArgs missing")
        ir = _lift(
            "AiDebugEventArgs.cs",
            "Hex.Session.Battle.AiDebugEventArgs::.ctor(int[],BattleAiAction,EActionType)",
        )
        codes = {u.get("code") for u in ir.get("unresolved") or []}
        self.assertIn("routine_metadata_guard_branch", codes)
        self.assertNotIn("opaque_branch_target", codes)
        plan = field_assign_plan_from_ir(ir)
        self.assertIsNotNone(plan)
        self.assertEqual([p[0] for p in plan], ["hexValueMap", "bestAction", "actionType"])
        self.assertTrue(is_base_then_param_field_assign_ctor(ir))

    def test_energyupdate_eir_int_not_linear_param_assign(self) -> None:
        if not (DIFFABLE_BATTLE / "EnergyUpdateEventArgs.cs").is_file():
            self.skipTest("DiffableCs EnergyUpdateEventArgs missing")
        ir = _lift(
            "EnergyUpdateEventArgs.cs",
            "Hex.Session.Battle.EnergyUpdateEventArgs::.ctor(eir,int)",
        )
        # Nested-field surface (see test_nested_null_throw); still not linear param-assign.
        self.assertFalse(is_base_then_param_field_assign_ctor(ir))

    def test_unitstartedmovement_not_linear_param_assign(self) -> None:
        if not (DIFFABLE_BATTLE / "UnitStartedMovementEventArgs.cs").is_file():
            self.skipTest("DiffableCs UnitStartedMovementEventArgs missing")
        ir = _lift(
            "UnitStartedMovementEventArgs.cs",
            "Hex.Session.Battle.UnitStartedMovementEventArgs::.ctor(float,float,int,Unit,EMovementType,Hex[],bool)",
        )
        self.assertFalse(is_base_then_param_field_assign_ctor(ir))


if __name__ == "__main__":
    raise SystemExit(unittest.main())
