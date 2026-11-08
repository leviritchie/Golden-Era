"""Negative contracts for the serialized skin-only repair stage."""
import copy
import json
import shutil
import uuid
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_attachment_skin_refit as refit
from run_attachment_skin_refit import validate_candidate


class SkinRefitContractTests(unittest.TestCase):
    def setUp(self):
        self.skin = {"vertices": np.array([[0., 0, 0], [1, 0, 0], [0, 1, 0]]),
                     "triangles": np.array([[0, 1, 2]]),
                     "uvs": np.zeros((3, 2)), "weights": np.array([[.7, .3], [1., 0], [0, 1.]]),
                     "inverseBind": np.repeat(np.eye(4)[None], 2, axis=0)}
        self.domain = {"trainMask": np.array([True, True, False]),
                       "allowedSupport": np.array([[True, True], [True, False], [False, True]]),
                       "ownershipIds": np.zeros(3, dtype=np.int64)}

    def test_only_train_weights_can_change(self):
        candidate = copy.deepcopy(self.skin)
        candidate["weights"][0] = [.4, .6]
        result = validate_candidate(self.skin, candidate, self.domain)
        self.assertEqual(result["changedVertexCount"], 1)
        self.assertTrue(result["restAndTopologyExact"])

    def test_rest_topology_uv_and_skeleton_changes_rejected(self):
        for key in ("vertices", "triangles", "uvs", "inverseBind"):
            with self.subTest(key=key):
                candidate = copy.deepcopy(self.skin)
                candidate[key].flat[0] += 1
                with self.assertRaisesRegex(ValueError, key):
                    validate_candidate(self.skin, candidate, self.domain)

    def test_frozen_changes_rejected_even_if_normalized(self):
        candidate = copy.deepcopy(self.skin)
        candidate["weights"][2] = [.1, .9]
        domain = copy.deepcopy(self.domain)
        domain["allowedSupport"][2] = True
        with self.assertRaisesRegex(ValueError, "frozen"):
            validate_candidate(self.skin, candidate, domain)

    def test_invalid_or_undeclared_weights_rejected(self):
        for row in ([np.nan, 0], [-.1, 1.1], [.5, .6]):
            candidate = copy.deepcopy(self.skin)
            candidate["weights"][0] = row
            with self.assertRaises(ValueError):
                validate_candidate(self.skin, candidate, self.domain)
        candidate = copy.deepcopy(self.skin)
        candidate["weights"][1] = [.9, .1]
        with self.assertRaisesRegex(ValueError, "support"):
            validate_candidate(self.skin, candidate, self.domain)

    def test_field_inventory_cannot_change(self):
        candidate = copy.deepcopy(self.skin)
        del candidate["inverseBind"]
        with self.assertRaisesRegex(ValueError, "inventory"):
                validate_candidate(self.skin, candidate, self.domain)


class LoadRefitContractTests(unittest.TestCase):
    """Readback must authenticate every input used by the skin-only stage."""

    def setUp(self):
        self.root = (Path(__file__).resolve().parents[2] /
                     "artifacts/homm3_mocap_v2/attachment_repair/test_fixtures" /
                     uuid.uuid4().hex)
        self.root.mkdir(parents=True)
        self.fit_dir = self.root / "fit"
        self.fit_dir.mkdir()
        self.source_report = self.root / "repair.json"
        self.source_report.write_text('{"schema":"attachment-repair-result-v1"}\n', encoding="utf-8")
        vertices = np.array([[0., 0., 0.], [0., 0., 0.], [0., 1., 0.],
                             [0., 0., 1.], [1., 0., 1.], [0., 1., 1.]])
        weights = np.array([[.5, .5], [.5, .5], [.5, .5],
                            [0., 1.], [0., 1.], [0., 1.]])
        self.original = {
            "vertices": vertices,
            "triangles": np.array([[0, 1, 2], [3, 4, 5]], dtype=np.int64),
            "uvs": np.zeros((6, 2)),
            "weights": weights,
            "names": np.array(["body", "owner"]),
            "parents": np.array([-1, 0], dtype=np.int64),
            "inverseBind": np.repeat(np.eye(4)[None], 2, axis=0),
        }
        self.motions = {"clip": {"jointWorld": np.tile(np.eye(4)[None, None], (2, 2, 1, 1))}}
        self.selected = np.array([1], dtype=np.int64)
        conditioning = refit.condition_body_welds(vertices, self.original["triangles"], weights, self.selected)
        domain = refit.make_repair_domain(vertices, self.original["triangles"],
                                          conditioning["conditionedWeights"], self.selected,
                                          neighbor_rings=1)
        self.domain = domain
        self.candidate = {key: value.copy() for key, value in self.original.items()}
        np.savez_compressed(self.root / "domain.npz",
                            **{key: domain[key] for key in ("ownershipIds", "trainMask", "allowedSupport")})
        np.savez_compressed(self.root / "refitted_skin.npz", **self.candidate)
        invariants = validate_candidate(self.original, self.candidate, domain)
        self.report = {
            "schema": "attachment-skin-refit-v1", "asset": "fixture",
            "repairReport": str(self.source_report.resolve()),
            "repairReportSha256": refit.sha256_file(self.source_report),
            "neighborRings": 1,
            "conditionedWeightsSha256": refit.digest(conditioning["conditionedWeights"]),
            "domainSha256": refit.sha256_file(self.root / "domain.npz"),
            "candidateSha256": refit.sha256_file(self.root / "refitted_skin.npz"),
            "invariants": invariants, "cases": {"clip": {
                "fixedMotionSha256": refit.digest(self.motions["clip"]["jointWorld"])}},
        }
        self.report_path = self.root / "report.json"
        self._write_report()
        self.old_loader = refit.load_repair
        refit.load_repair = lambda source, asset, fit_dir: (
            self.report, {"camera": {}}, self.original, self.motions, self.selected)

    def tearDown(self):
        refit.load_repair = self.old_loader
        shutil.rmtree(self.root, ignore_errors=True)

    def _write_report(self):
        self.report_path.write_text(json.dumps(self.report, indent=2) + "\n", encoding="utf-8")

    def _reload(self):
        return refit.load_refit(self.report_path, "fixture", self.fit_dir)

    def test_valid_serialized_readback(self):
        result = self._reload()
        self.assertTrue(np.array_equal(result[3]["weights"], self.original["weights"]))

    def test_source_hash_drift_rejected(self):
        self.source_report.write_text("changed\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "source identity"):
            self._reload()

    def test_candidate_hash_drift_rejected(self):
        with open(self.root / "refitted_skin.npz", "ab") as handle:
            handle.write(b"drift")
        with self.assertRaisesRegex(ValueError, "candidate identity"):
            self._reload()

    def test_domain_hash_drift_rejected(self):
        with open(self.root / "domain.npz", "ab") as handle:
            handle.write(b"drift")
        with self.assertRaisesRegex(ValueError, "domain identity"):
            self._reload()

    def test_motion_inventory_drift_rejected(self):
        self.motions["clip"]["jointWorld"][0, 0, 0] = 2.
        with self.assertRaisesRegex(ValueError, "motion inventory"):
            self._reload()

    def test_nonweight_candidate_edit_rejected_even_with_updated_file_hash(self):
        changed = {key: value.copy() for key, value in self.candidate.items()}
        changed["vertices"][0, 0] = 4.
        np.savez_compressed(self.root / "refitted_skin.npz", **changed)
        self.report["candidateSha256"] = refit.sha256_file(self.root / "refitted_skin.npz")
        self._write_report()
        with self.assertRaisesRegex(ValueError, "changed vertices"):
            self._reload()

    def test_body_weld_weights_must_remain_identical(self):
        changed = {key: value.copy() for key, value in self.candidate.items()}
        changed["weights"][1] = [.6, .4]
        with self.assertRaisesRegex(ValueError, "body weight weld"):
            validate_candidate(self.original, changed, self.domain)


class LoadSourceSupportRefitTests(LoadRefitContractTests):
    def setUp(self):
        super().setUp()
        self.original["sourceVertexIds"] = np.arange(len(self.original["vertices"]))
        self.candidate = {key: value.copy() for key, value in self.original.items()}
        self.fitted = {key: value.copy() for key, value in self.original.items()}
        self.domain = refit.restore_source_owner_support(self.domain, self.original["vertices"],
                                                        self.fitted["weights"], 1)
        self.report["schema"] = "attachment-skin-refit-v2"
        self.report["domain"] = self.domain["report"]
        np.savez_compressed(self.root / "domain.npz", **{
            key: self.domain[key] for key in ("ownershipIds", "trainMask", "allowedSupport")})
        np.savez_compressed(self.root / "refitted_skin.npz", **self.candidate)
        self.report["domainSha256"] = refit.sha256_file(self.root / "domain.npz")
        self.report["candidateSha256"] = refit.sha256_file(self.root / "refitted_skin.npz")
        refit.load_repair = lambda source, asset, fit_dir: (
            {"topology": {"ownerIndex": 1}}, self.fitted, self.original, self.motions, self.selected)
        self._write_report()

    def test_source_support_evidence_drift_rejected(self):
        self.report["domain"]["unverifiedEvidence"] = True
        self._write_report()
        with self.assertRaisesRegex(ValueError, "source owner support evidence"):
            self._reload()


class LoadAnatomicalInitializationRefitTests(LoadSourceSupportRefitTests):
    def setUp(self):
        super().setUp()
        self.old_profile = refit.get_profile
        refit.get_profile = lambda asset: {"chains": ()}
        initialization = refit.initialize_profile_chains(
            self.original, self.selected, refit.get_profile("fixture"), ()
        )
        self.report["schema"] = "attachment-skin-refit-v3"
        self.report["anatomicalChainRegions"] = []
        self.report["anatomicalInitialization"] = initialization["report"]
        self.report["domain"] = self.domain["report"]
        self._write_report()

    def tearDown(self):
        refit.get_profile = self.old_profile
        super().tearDown()

    def test_valid_v3_initialization_readback(self):
        result = self._reload()
        self.assertTrue(np.array_equal(result[3]["weights"], self.original["weights"]))

    def test_initialization_evidence_drift_rejected(self):
        self.report["anatomicalInitialization"]["accepted"] = True
        self._write_report()
        with self.assertRaisesRegex(ValueError, "anatomical initialization evidence"):
            self._reload()

    def test_schema2_initialization_readback_compatibility(self):
        profile = refit.get_profile("fixture")
        self.report["anatomicalInitialization"] = refit.initialize_profile_chains(
            self.original, self.selected, profile, (), schema="profile-chain-initialization-v2"
        )["report"]
        self._write_report()
        result = self._reload()
        self.assertTrue(np.array_equal(result[3]["weights"], self.original["weights"]))

    def test_joint_anchor_objective_readback_rejects_tampered_spec(self):
        spec = {"schema": "fixed-joint-anchor-objective-v1", "weight": 1.0,
                "model": {"schema": "skin-joint-anchor-model-v1"},
                "jointWorldSha256": "fixture", "coverage": {"supportedAnchorCount": 1}}
        self.report["jointAnchorObjective"] = spec
        self._write_report()
        expected = copy.deepcopy(spec)
        with patch.object(refit, "_anchor_spec", return_value=expected):
            self.assertIsNotNone(self._reload())
        self.report["jointAnchorObjective"]["weight"] = 2.0
        self._write_report()
        with patch.object(refit, "_anchor_spec", return_value=expected):
            with self.assertRaisesRegex(ValueError, "joint anchor objective evidence"):
                self._reload()


class JointAnchorSpecTests(unittest.TestCase):
    def test_zero_weight_is_identity_and_does_not_require_chains(self):
        result = refit._anchor_spec({}, {}, {}, (), {}, {}, 0.0)
        self.assertIsNone(result)

    def test_negative_nan_and_positive_without_chains_fail_closed(self):
        for weight in (-1.0, np.nan, np.inf):
            with self.subTest(weight=weight):
                with self.assertRaisesRegex(ValueError, "joint anchor weight"):
                    refit._anchor_spec({}, {}, {}, (), {}, {}, weight)
        with self.assertRaisesRegex(ValueError, "explicit anatomical chains"):
            refit._anchor_spec({}, {}, {}, (), {}, {}, 1.0)


if __name__ == "__main__":
    unittest.main()
