"""Mutation tests for build budgets and strict release validation scope."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
import unittest
from unittest import mock
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import validate_validator_performance_contract as gate
import test_tempdir


class BuildBudgetTests(unittest.TestCase):
    def setUp(self):
        self.project = ET.parse(ROOT / gate.PROJECT).getroot()

    def target(self, name):
        return next(node for node in self.project.iter("Target") if node.get("Name") == name)

    def test_current_project(self):
        self.assertEqual(gate.project_errors(self.project), [])

    def test_required_gates_cannot_skip_or_ignore_exec_failures(self):
        for name in ("ValidateValidatorPerformanceContract", "ValidateHomm3DefRetargetDeliveryContract",
                     "RefuseDeployWhileGameRunning"):
            for attribute, value in (("Condition", "false"), ("IgnoreExitCode", "true"),
                                     ("ContinueOnError", "true"), ("ContinueOnError", "WarnAndContinue")):
                with self.subTest(target=name, attribute=attribute, value=value):
                    altered = copy.deepcopy(self.project)
                    target = next(node for node in altered.iter("Target") if node.get("Name") == name)
                    next(target.iter("Exec")).set(attribute, value)
                    self.assertTrue(gate.project_errors(altered))

    def test_game_guard_cannot_drop_deploy_order_or_condition(self):
        for attribute in ("Condition", "BeforeTargets"):
            with self.subTest(attribute=attribute):
                altered = copy.deepcopy(self.project)
                target = next(node for node in altered.iter("Target") if node.get("Name") == "RefuseDeployWhileGameRunning")
                target.set(attribute, "false")
                self.assertTrue(gate.project_errors(altered))

    def test_game_and_fixture_budgets_cannot_expand_to_general_ceiling(self):
        for name, timeout in (("RefuseDeployWhileGameRunning", "30001"),
                              ("ValidateValidatorPerformanceContract", "120001")):
            with self.subTest(target=name):
                altered = copy.deepcopy(self.project)
                target = next(node for node in altered.iter("Target") if node.get("Name") == name)
                next(target.iter("Exec")).set("Timeout", timeout)
                self.assertTrue(gate.project_errors(altered))

    def test_fixture_scratch_supports_tests_callers_and_refuses_foreign_owners(self):
        with test_tempdir.workspace_tempdir(__file__) as folder:
            path = Path(folder)
            self.assertEqual(path.parent, ROOT)
            self.assertTrue(path.is_dir())
        self.assertFalse(path.exists())
        with mock.patch.object(test_tempdir.Path, "mkdir") as create:
            with self.assertRaisesRegex(ValueError, "owner must be inside"):
                test_tempdir.workspace_tempdir(str(ROOT.parent / "foreign_test.py"))
            create.assert_not_called()

    def test_full_town_cannot_drop_or_weaken_cuda_parity(self):
        for change in ("remove", "ignore", "condition", "scope"):
            with self.subTest(change=change):
                altered = copy.deepcopy(self.project)
                target = next(node for node in altered.iter("Target") if node.get("Name") == "ValidateTownScene3dContract")
                parity = next(node for node in target.iter("Exec") if "test_town_gpu_pan.py" in node.get("Command", ""))
                if change == "remove":
                    target.remove(parity)
                elif change == "ignore":
                    parity.set("IgnoreExitCode", "true")
                elif change == "condition":
                    parity.set("Condition", "false")
                else:
                    coverage = next(node for node in target.iter("Exec") if "$(TownScene3dValidator)" in node.get("Command", ""))
                    coverage.set("Command", coverage.get("Command") + " --only homm3_factory")
                self.assertTrue(gate.project_errors(altered))

    def test_fixture_cleanup_checks_resolved_workspace_target(self):
        temporary = test_tempdir.WorkspaceTemporaryDirectory.__new__(test_tempdir.WorkspaceTemporaryDirectory)
        temporary.repo_root = ROOT
        temporary.path = mock.Mock()
        with mock.patch.object(test_tempdir.shutil, "rmtree") as remove:
            for resolved in (ROOT.parent / ".fixture-foreign", ROOT / "unrelated"):
                temporary.path.resolve.return_value = resolved
                with self.assertRaisesRegex(RuntimeError, "outside its workspace"):
                    temporary.cleanup()
                remove.assert_not_called()
            safe = ROOT / ".fixture-owned"
            temporary.path.resolve.return_value = safe
            temporary.cleanup()
            remove.assert_called_once_with(safe)
            temporary.path.resolve.assert_called_with(strict=True)

    def test_missing_unbounded_and_excessive_timeout_refused(self):
        execute = next(self.target("ValidateMapLoadPreflightContract").iter("Exec"))
        for timeout in (None, "-1", "0", "$(UnknownBudget)", "300001"):
            with self.subTest(timeout=timeout):
                mutated = copy.deepcopy(self.project)
                item = next(node for node in mutated.iter("Target")
                            if node.get("Name") == "ValidateMapLoadPreflightContract")
                child = next(item.iter("Exec"))
                if timeout is None:
                    child.attrib.pop("Timeout", None)
                else:
                    child.set("Timeout", timeout)
                self.assertTrue(gate.project_errors(mutated))
        self.assertIsNotNone(execute)

    def test_embedded_deploy_validator_requires_budget(self):
        target = self.target("DeployPluginToGame")
        ET.SubElement(target, "Exec", Command="python validate_new_payload.py")
        self.assertTrue(gate.project_errors(self.project))

    def test_quick_tier_regression_refused(self):
        self.target("ValidateValidatorPerformanceContract").set("Condition", "")
        self.assertTrue(gate.project_errors(self.project))

    def test_release_selection_scope_refused(self):
        execute = next(self.target("ValidateHomm3DefRetargetDeliveryContract").iter("Exec"))
        execute.set("Command", execute.get("Command") + " --selection one.json")
        self.assertTrue(gate.project_errors(self.project))

    def test_delivery_opt_in_or_missing_exec_refused(self):
        target = self.target("ValidateHomm3DefRetargetDeliveryContract")
        target.set("Condition", "'$(RunSomeOptionalAudit)' == 'true'")
        self.assertTrue(gate.project_errors(self.project))
        self.project = ET.parse(ROOT / gate.PROJECT).getroot()
        target = self.target("ValidateHomm3DefRetargetDeliveryContract")
        for execute in list(target.iter("Exec")):
            target.remove(execute)
        self.assertTrue(gate.project_errors(self.project))

    def test_game_probe_failure_cannot_be_ignored(self):
        execute = next(self.target("RefuseDeployWhileGameRunning").iter("Exec"))
        execute.set("IgnoreExitCode", "true")
        self.assertTrue(gate.project_errors(self.project))


if __name__ == "__main__":
    unittest.main(verbosity=2)
