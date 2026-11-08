#!/usr/bin/env python3
"""Focused checks for build selection and per-build flat hint ownership."""
from __future__ import annotations

import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

import validate_game_symbols_hint_contract as contract  # noqa: E402


PROJECT = REPO / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "OfflineUnlockMod.csproj"


def scope(ref: str | None) -> contract.ScopeSpec:
    return contract.ScopeSpec(hints_ref=ref, hints=[], shape=None)


def group(golden_ref: str | None, current_ref: str | None, name: str) -> contract.GroupSpec:
    return contract.GroupSpec(
        symbol=name,
        group_id=name,
        line=1,
        scopes={"golden": scope(golden_ref), "current": scope(current_ref)},
    )


class BuildSelectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.project = ET.parse(PROJECT).getroot()
        cls.targets = {target.attrib["Name"]: target for target in cls.project.findall("Target")}

    def test_current_is_default_and_golden_is_explicit_override(self) -> None:
        defaults = [
            prop
            for group_node in self.project.findall("PropertyGroup")
            for prop in group_node.findall("GameSymbolsHintContractBuild")
            if prop.attrib.get("Condition") == "'$(GameSymbolsHintContractBuild)' == ''"
        ]
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0].text, "current")

        selector = self.targets["ValidateGameSymbolsHintContractBuildSelector"]
        self.assertEqual(selector.attrib.get("BeforeTargets"), "BeforeBuild")
        errors = selector.findall("Error")
        self.assertEqual(len(errors), 1)
        self.assertIn("'$(GameSymbolsHintContractBuild)' != 'current'", errors[0].attrib["Condition"])
        self.assertIn("'$(GameSymbolsHintContractBuild)' != 'golden'", errors[0].attrib["Condition"])

    def test_normal_gate_checks_selected_build_and_only_skips_explicitly(self) -> None:
        gate = self.targets["ValidateGameSymbolsHintContract"]
        self.assertIn("'$(SkipGameSymbolsHintContract)' != 'true'", gate.attrib["Condition"])
        command = gate.find("Exec").attrib["Command"]
        self.assertIn('--build "$(GameSymbolsHintContractBuild)"', command)
        self.assertIn('--gate "$(GameSymbolsHintContractBuild)"', command)


class FlatOwnershipTests(unittest.TestCase):
    def setUp(self) -> None:
        self.groups = [
            group("TypeGroups.SharedHints", "TypeGroups.SharedHints", "shared"),
            group("TypeGroups.GoldenOnlyHints", None, "golden-only"),
            group(None, "TypeGroups.CurrentOnlyHints", "current-only"),
            group(None, None, "standalone"),
        ]

    def test_current_excludes_build_specific_scopes_and_keeps_shared_arrays(self) -> None:
        self.assertEqual(
            contract.type_group_owned_flat_refs_to_exclude(self.groups, "current"),
            {"TypeGroups.GoldenOnlyHints", "TypeGroups.CurrentOnlyHints"},
        )

    def test_golden_preserves_legacy_current_only_exclusion(self) -> None:
        self.assertEqual(
            contract.type_group_owned_flat_refs_to_exclude(self.groups, "golden"),
            {"TypeGroups.CurrentOnlyHints"},
        )

    def test_unknown_build_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            contract.type_group_owned_flat_refs_to_exclude(self.groups, "future")


class CurrentFlatHintTests(unittest.TestCase):
    """The current-build flat check evaluates what GameSymbolsCurrent.g.cs binds at runtime."""

    def decl(self, name: str, values: list[str]) -> contract.Decl:
        return contract.Decl(name, "array", "", 1, values)

    def test_scoped_group_uses_generated_live_literals(self) -> None:
        scopes = {"G.A": {"status": "scoped", "live": ["liveFull", None, "liveObf"]}}
        self.assertEqual(contract.current_flat_hints(self.decl("G.A", ["goldenFull", "x"]), scopes),
                         (["liveFull", "liveObf"], None, "generated"))

    def test_refused_group_is_refused_not_golden(self) -> None:
        scopes = {"G.B": {"status": "refused", "reason": "remap unmapped"}}
        hints, reason, source = contract.current_flat_hints(self.decl("G.B", ["goldenFull"]), scopes)
        self.assertEqual((hints, reason, source), ([], "remap unmapped", "generated-refused"))

    def test_untouched_group_keeps_declared_literals(self) -> None:
        for scopes in ({}, {"G.C": {"status": "identity", "live": None}}):
            self.assertEqual(contract.current_flat_hints(self.decl("G.C", ["Hex.Real", ""]), scopes),
                             (["Hex.Real"], None, "declared"))

    def test_scoped_group_with_no_live_literal_is_refused(self) -> None:
        scopes = {"G.D": {"status": "scoped", "live": [None, None]}}
        self.assertIsNotNone(contract.current_flat_hints(self.decl("G.D", ["a", "b"]), scopes)[1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
