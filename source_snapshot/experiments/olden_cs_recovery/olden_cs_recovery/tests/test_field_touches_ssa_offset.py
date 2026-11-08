"""Regression: SSA+register ISIL offset stores must resolve into field_touches."""

from __future__ import annotations

import unittest
from pathlib import Path

from olden_cs_recovery.lifter.ir_build import FIELD_OFFSET_RE, build_ir
from olden_cs_recovery.lifter.isil_parse import (
    match_isil_method,
    parse_diffable_fields_with_bases,
    parse_isil_file,
)
from olden_cs_recovery.paths import REPO_ROOT
from olden_cs_recovery.replay import field_assign_plan_from_ir

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


class SsaOffsetFieldTouchTests(unittest.TestCase):
    def test_field_offset_re_matches_ssa_register_form(self) -> None:
        sample = "[v11 @ rdi_v1 (Hex.Session.Battle.StepEventArgs)+10]"
        match = FIELD_OFFSET_RE.search(sample)
        self.assertIsNotNone(match)
        self.assertEqual(match.group("offset"), "10")

    def test_inherited_battleeventargs_target_field(self) -> None:
        path = DIFFABLE_BATTLE / "StepEventArgs.cs"
        if not path.is_file():
            self.skipTest(f"missing DiffableCs {path}")
        fields = parse_diffable_fields_with_bases(path)
        self.assertIn(0x10, fields)
        self.assertEqual(fields[0x10].name, "target")
        self.assertEqual(fields[0x20].name, "step")

    def test_step_eventargs_plan_consumes_unit_and_string(self) -> None:
        self._assert_unit_base_field_ctor(
            type_name="Hex.Session.Battle.StepEventArgs",
            method_id="Hex.Session.Battle.StepEventArgs::.ctor(Unit,string)",
            stem="StepEventArgs",
            expected_plan=[
                ("target", "Unit", ("arg", 0)),
                ("step", "string", ("arg", 1)),
            ],
        )

    def test_unit_pos_changed_plan_consumes_unit_and_hex(self) -> None:
        self._assert_unit_base_field_ctor(
            type_name="Hex.Session.Battle.UnitPosChangedEventArgs",
            method_id="Hex.Session.Battle.UnitPosChangedEventArgs::.ctor(Unit,Hex)",
            stem="UnitPosChangedEventArgs",
            expected_plan=[
                ("target", "Unit", ("arg", 0)),
                ("targetHex", "Hex", ("arg", 1)),
            ],
        )

    def _assert_unit_base_field_ctor(
        self,
        *,
        type_name: str,
        method_id: str,
        stem: str,
        expected_plan: list[tuple],
    ) -> None:
        diffable = DIFFABLE_BATTLE / f"{stem}.cs"
        isil_path = ISIL_BATTLE / f"{stem}.txt"
        if not diffable.is_file() or not isil_path.is_file():
            self.skipTest(f"missing DiffableCs/ISIL for {stem}")
        fields = parse_diffable_fields_with_bases(diffable)
        methods = parse_isil_file(isil_path)
        method = match_isil_method(
            methods,
            type_name=type_name,
            method_name=".ctor",
            method_id=method_id,
        )
        ir = build_ir(
            method_id=method_id,
            type_name=type_name,
            method_name=".ctor",
            isil_method=method,
            fields=fields,
            address_map=None,
            sources={
                "diffable_cs": str(diffable),
                "isil": str(isil_path),
                "address_map": None,
                "native_disasm": None,
            },
        )
        writes = [t for t in ir["field_touches"] if t.get("access") == "write"]
        write_names = [t.get("field_name") for t in writes]
        self.assertIn("target", write_names)
        # Without address map, base CallVoid stays unresolved — still exercise plan builder.
        plan = field_assign_plan_from_ir(ir)
        self.assertEqual(plan, expected_plan)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
