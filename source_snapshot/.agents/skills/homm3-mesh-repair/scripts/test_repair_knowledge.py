"""In-memory fixtures avoid extra files and Windows temporary-directory ACLs."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from repair_knowledge import INDEX, ROOT, load, main, select, validate


class RepairKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.rule = dict(id="fixture", bodyPlans=["biped"], signatures=["gap"],
                         scope="unit", units=["unit-a"], kind="negative", action="Inspect rest.",
                         prerequisites=["Same candidate."], proof="diagnostic",
                         evidence=[dict(path="evidence.txt", sha256=hashlib.sha256(b"before").hexdigest())])
        self.index = dict(schema="repair_learning.v1", records=[self.rule])
        self.files = patch.object(Path, "is_file", return_value=True)
        self.files.start()
        self.addCleanup(self.files.stop)

    def query(self, **kwargs):
        kwargs.setdefault("verify_evidence", False)
        return select(self.index, body_plan="biped", signatures=["gap"], **kwargs)

    def test_unit_scope_is_not_generalized(self):
        self.assertEqual(self.query(), [])
        self.assertEqual(self.query(unit="unit-b"), [])
        self.assertEqual(self.query(unit="unit-a"), [self.rule])
        del self.rule["units"]
        with self.assertRaisesRegex(ValueError, "unit scope"):
            validate(self.index)

    def test_wrong_plan_and_signature_filtered(self):
        self.assertEqual(select(self.index, body_plan="quadruped", signatures="gap", unit="unit-a"), [])
        self.assertEqual(select(self.index, body_plan="biped", signatures="twist", unit="unit-a"), [])

    def test_source_tamper_and_optional_hashing(self):
        with patch.object(Path, "open", return_value=io.BytesIO(b"before")):
            validate(self.index, verify_evidence=True)
        with patch.object(Path, "open", return_value=io.BytesIO(b"tamper")):
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                validate(self.index, verify_evidence=True)
        with patch.object(Path, "open", side_effect=AssertionError("unexpected read")):
            validate(self.index)

    def test_deterministic_ranking_and_hard_cap(self):
        self.index["records"] = []
        for number in reversed(range(10)):
            row = copy.deepcopy(self.rule)
            row["id"] = f"rule-{number}"
            row["scope"] = "asset_class"
            del row["units"]
            self.index["records"].append(row)
        self.index["records"].append(self.rule)
        expected = ["fixture"] + [f"rule-{n}" for n in range(5)]
        self.assertEqual([r["id"] for r in self.query(unit="unit-a", limit=100)], expected)
        self.index["records"].reverse()
        self.assertEqual([r["id"] for r in self.query(unit="unit-a")], expected)
        self.assertEqual(len(self.query(limit=2)), 2)

    def test_signature_overlap_precedes_lexical_tiebreak(self):
        row = copy.deepcopy(self.rule)
        row.update(id="z-more-specific", signatures=["gap", "twist"])
        self.index["records"].append(row)
        result = select(self.index, body_plan="biped", signatures=["gap", "twist"],
                        unit="unit-a", verify_evidence=False)
        self.assertEqual(result[0]["id"], "z-more-specific")

    def test_duplicate_ids(self):
        self.index["records"].append(copy.deepcopy(self.rule))
        with self.assertRaisesRegex(ValueError, "duplicate id"):
            validate(self.index)

    def test_invalid_enums_text_evidence_and_unknown_fields(self):
        mutations = [("scope", "fleet"), ("kind", "success"), ("proof", "runtime"),
                     ("proof", []), ("action", "a" * 601), ("action", "  "),
                     ("prerequisites", []), ("prerequisites", ["x" * 241]),
                     ("bodyPlans", ["*"]), ("evidence", []),
                     ("evidence", [{"path": "evidence.txt", "sha256": "bad"}]),
                     ("evidence", [{"path": "evidence.txt"}]), ("unexpected", "x")]
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                index = copy.deepcopy(self.index)
                index["records"][0][field] = value
                with self.assertRaises(ValueError):
                    validate(index)

    def test_missing_or_escaping_evidence(self):
        with patch.object(Path, "is_file", return_value=False):
            with self.assertRaisesRegex(ValueError, "missing evidence"):
                validate(self.index)
        for path in ("../outside", "/absolute", "C:/outside", "a\\b", "a/../b"):
            self.rule["evidence"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate(self.index)

    def test_recipe_requires_applicability_and_real_improvement(self):
        self.rule["kind"] = "recipe"
        with self.assertRaisesRegex(ValueError, "applicability"):
            validate(self.index)
        improvement = dict(unit="unit-a", metric="escaped vertices", before=10, after=9,
                           direction="lower", evidencePath="evidence.txt")
        self.rule.update(applicability="Only the measured candidate and saved motion.",
                         improvements=[improvement])
        validate(self.index)
        for value in (10, 11, float("nan"), float("inf"), True):
            improvement["after"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate(self.index)
        improvement["after"] = 9
        improvement["evidencePath"] = "unhashed.txt"
        with self.assertRaisesRegex(ValueError, "hashed evidence"):
            validate(self.index)

    def test_asset_class_recipe_cannot_generalize_one_unit(self):
        self.rule.update(kind="recipe", scope="asset_class", applicability="Shared tested route.",
                         improvements=[dict(unit="unit-a", metric="error", before=2, after=1,
                                            direction="lower", evidencePath="evidence.txt")])
        del self.rule["units"]
        with self.assertRaisesRegex(ValueError, "at least two units"):
            validate(self.index)
        second = dict(self.rule["improvements"][0], unit="unit-b")
        self.rule["improvements"].append(second)
        validate(self.index)

    def test_cli_json_and_error_exit(self):
        with patch("repair_knowledge.load", return_value=self.index), \
                patch.object(Path, "open", side_effect=lambda *a, **k: io.BytesIO(b"before")):
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["query", "--body-plan", "biped", "--signature", "gap",
                                       "--unit", "unit-a", "--limit", "100"]), 0)
            self.assertEqual(json.loads(output.getvalue()), [self.rule])
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(main(["query", "--body-plan", "biped", "--unit", "unit-a"]), 0)
            self.assertEqual(json.loads(output.getvalue()), [self.rule])
        with patch("repair_knowledge.load", side_effect=ValueError("bad evidence")):
            output = io.StringIO()
            with contextlib.redirect_stderr(output):
                self.assertEqual(main(["validate"]), 1)
            self.assertFalse(json.loads(output.getvalue())["ok"])

    def test_load_and_structural_selection_do_no_evidence_io(self):
        def open_index(path, *args, **kwargs):
            self.assertEqual(path, Path("index.json"))
            return io.BytesIO(json.dumps(self.index).encode())

        with patch.object(Path, "open", open_index), \
                patch.object(Path, "is_file", side_effect=AssertionError("evidence stat")), \
                patch.object(Path, "resolve", side_effect=AssertionError("evidence resolve")):
            index = load("index.json")
            self.assertEqual(select(index, body_plan="biped", unit="unit-a",
                                    verify_evidence=False), [self.rule])
            self.rule["evidence"][0]["path"] = "../escape"
            with self.assertRaisesRegex(ValueError, "repo-relative"):
                load("index.json")

    def test_omitted_signatures_support_more_than_sixteen_distinct_tags(self):
        self.index["records"] = []
        for number in reversed(range(20)):
            row = copy.deepcopy(self.rule)
            row.update(id=f"rule-{number:02}", signatures=[f"tag-{number}"])
            self.index["records"].append(row)
        result = select(self.index, body_plan="biped", unit="unit-a", verify_evidence=False)
        self.assertEqual([r["id"] for r in result], [f"rule-{n:02}" for n in range(6)])
        self.index["records"].reverse()
        self.assertEqual(select(self.index, body_plan="biped", signatures=None,
                                unit="unit-a", verify_evidence=False), result)
        self.assertEqual(select(self.index, body_plan="biped", unit="unit-b"), [])
        self.assertEqual(select(self.index, body_plan="quadruped", unit="unit-a"), [])

    def test_unrelated_missing_evidence_does_not_block_verified_selection(self):
        missing = copy.deepcopy(self.rule)
        missing.update(id="other-unit", units=["unit-b"])
        missing["evidence"][0]["path"] = "missing.txt"
        self.index["records"].append(missing)

        def is_file(path):
            self.assertNotEqual(path.name, "missing.txt", "unselected evidence was inspected")
            return True

        with patch.object(Path, "is_file", is_file), \
                patch.object(Path, "open", side_effect=lambda *a, **k: io.BytesIO(b"before")):
            self.assertEqual(self.query(unit="unit-a", verify_evidence=True), [self.rule])

    def test_matching_missing_evidence_refused_on_verify(self):
        with patch.object(Path, "is_file", return_value=False):
            self.assertEqual(self.query(unit="unit-a"), [self.rule])
            with self.assertRaisesRegex(ValueError, "missing evidence"):
                self.query(unit="unit-a", verify_evidence=True)
            with self.assertRaisesRegex(ValueError, "missing evidence"):
                validate(self.index, check_evidence=False, verify_evidence=True)

    def test_selected_tampered_evidence_refused(self):
        with patch.object(Path, "open", return_value=io.BytesIO(b"tamper")):
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                select(self.index, body_plan="biped", unit="unit-a")

    def test_seed_evidence_is_current_and_only_negative(self):
        self.files.stop()
        index = load(INDEX, root=ROOT, verify_evidence=True)
        seed_ids = {"grand-elf-local-defects-not-global-swap",
                    "skeleton-five-samples-miss-hit-failure",
                    "saved-matrix-replay-not-continuity-proof",
                    "fused-grip-one-component-not-prop-purity"}
        seeds = [r for r in index["records"] if r["id"] in seed_ids]
        self.assertEqual({r["id"] for r in seeds}, seed_ids)
        self.assertTrue(all(r["kind"] == "negative" and r["proof"] == "diagnostic"
                            for r in seeds))

    def test_fused_grip_negative_is_shared_and_pins_seven_sources(self):
        self.files.stop()
        index = load(INDEX)
        rules = select(index, body_plan="biped", signatures="fused-grip")
        self.assertEqual(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule["scope"], "asset_class")
        self.assertNotIn("units", rule)
        self.assertEqual(rule["signatures"],
                         ["fused-grip", "prop-contamination", "one-component-cut"])
        self.assertEqual(len(rule["evidence"]), 7)
        self.assertEqual(select(index, body_plan="quadruped", signatures="fused-grip"), [])


if __name__ == "__main__":
    unittest.main()
