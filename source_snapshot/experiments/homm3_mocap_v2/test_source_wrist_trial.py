import json
import uuid
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from run_source_wrist_trial import ROOT, _annotation_frames, _validate_candidate, _validate_profile_skin, _profile_anchor_ids, _profile_annotation_scope, sha256_file


class SourceWristTrialValidationTests(unittest.TestCase):
    def setUp(self):
        self.base = (ROOT / "artifacts" / "homm3_mocap_v2" / "wrist_test_fixtures").resolve()
        self.root = self.base / uuid.uuid4().hex
        self.root.mkdir(parents=True)

    def tearDown(self):
        import shutil
        if self.root.resolve().parent != self.base:
            raise ValueError("test cleanup escaped fixture directory")
        shutil.rmtree(self.root)

    def fixture(self, *, nonleaf=False):
        root = self.root
        mask = root / "mask"; cand = root / "candidate"; mask.mkdir(); cand.mkdir()
        vertices = np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [2., 2., 0.]])
        triangles = np.array([[0, 1, 2]], dtype=np.int64)
        names = np.array(["mixamorig:Hips", "mixamorig:RightHand", "mixamorig:Head"])
        parents = np.array([-1, 0, 1 if nonleaf else 0], dtype=np.int64)
        base = np.zeros((4, 3)); base[:, 0] = 1.
        base[0] = [0., 1., 0.]
        fitted = {"vertices": vertices, "weights": base, "triangles": triangles, "names": names, "parents": parents}
        np.savez(mask / "face_proposal.npz", propTriangles=np.array([0], dtype=np.int64))
        mask_report = {"asset": "h3_test", "researchSkinSha256": "skin", "maskSha256": sha256_file(mask / "face_proposal.npz")}
        (mask / "report.json").write_text(json.dumps(mask_report))
        candidate_weights = base.copy(); candidate_weights[:3] = 0.; candidate_weights[:3, 1] = 1.
        candidate_path = cand / "rigid_skin_candidate.npz"
        np.savez(candidate_path, vertices=vertices, weights=candidate_weights, names=names, parents=parents)
        candidate_report = {"asset": "h3_test", "ownershipRepresentation": "skin-vertices", "fitProvenance": {"x": 1}, "maskSha256": mask_report["maskSha256"], "maskReportSha256": sha256_file(mask / "report.json"), "candidateSha256": sha256_file(candidate_path), "cameraSha256": "camera"}
        candidate_report["owner"] = "mixamorig:RightHand"
        (cand / "report.json").write_text(json.dumps(candidate_report))
        fit_report = {"asset": "h3_test", "inputs": {"researchSkin": "skin"}}
        return root, mask, cand, fitted, fit_report

    def test_candidate_subset_passes(self):
        root, mask, cand, fitted, fit = self.fixture()
        _, loaded, selected = _validate_candidate(cand, mask, fit, {"x": 1}, fitted, "mixamorig:RightHand")
        np.testing.assert_array_equal(selected, [0])
        np.testing.assert_array_equal(loaded["weights"][:3, 1], np.ones(3))
        self.assertEqual(np.count_nonzero(np.any(loaded["weights"] != fitted["weights"], axis=1)), 2)

    def test_outside_weight_change_rejected(self):
        root, mask, cand, fitted, fit = self.fixture()
        with np.load(cand / "rigid_skin_candidate.npz", allow_pickle=False) as z:
            data = {k: z[k].copy() for k in z.files}
        data["weights"][3] = [0., 1., 0.]
        np.savez(cand / "rigid_skin_candidate.npz", **data)
        report_path = cand / "report.json"
        report = json.loads(report_path.read_text())
        report["candidateSha256"] = sha256_file(cand / "rigid_skin_candidate.npz")
        report_path.write_text(json.dumps(report))
        with self.assertRaisesRegex(ValueError, "outside selected-face"):
            _validate_candidate(cand, mask, fit, {"x": 1}, fitted, "mixamorig:RightHand")

    def test_nonleaf_owner_rejected(self):
        root, mask, cand, fitted, fit = self.fixture(nonleaf=True)
        with self.assertRaisesRegex(ValueError, "leaf joint"):
            _validate_candidate(cand, mask, fit, {"x": 1}, fitted, "mixamorig:RightHand")

    def test_stale_annotation_frame_hash_rejected(self):
        root = self.root
        image_path = root / "frame.png"
        Image.new("RGBA", (4, 4), (255, 255, 255, 255)).save(image_path)
        frame = {"localIndex": 0, "sourcePath": str(image_path), "sourceSha256": "0" * 64, "grip": [1, 1], "clubTip": [2, 2], "ambiguous": False}
        annotation = {"canvas": {"width": 4, "height": 4}, "captures": {"g": {"captureSha256": "capture", "frameCount": 1, "frames": [frame]}}}
        corpus = {"captures": [{"key": "g", "captureSha256": "capture", "frames": [str(image_path)]}]}
        with self.assertRaisesRegex(ValueError, "sourceSha256 differs"):
            _annotation_frames(annotation, corpus, root / "corpus.json", {"g": [image_path]})


class ProfileOwnershipWristTests(unittest.TestCase):
    def test_explicit_tip_anchor_rejects_stale_outside_duplicate_ids(self):
        import copy
        profile = {'expectedMeshSha256': 'mesh', 'geometryOwnership': {'sha256': 'mask'}}
        skin = {'sourceVertexIds': np.array([10, 11, 12, 10])}
        annotation = {'targetAnchor': {'role': 'weapon_tip', 'sourceMeshSha256': 'mesh',
                      'geometryOwnershipSha256': 'mask', 'sourceVertexIds': [10, 11], 'evidence': 'reviewed blade'}}
        np.testing.assert_array_equal(_profile_anchor_ids(annotation, profile, skin, np.array([0, 1, 2])), [0, 1])
        for field, value in [('sourceMeshSha256', 'stale'), ('geometryOwnershipSha256', 'stale'),
                             ('sourceVertexIds', [10, 10]), ('sourceVertexIds', [99]), ('sourceVertexIds', [True]),
                             ('role', 'butt'), ('evidence', '')]:
            bad = copy.deepcopy(annotation)
            bad['targetAnchor'][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                _profile_anchor_ids(bad, profile, skin, np.array([0, 1, 2]))
        with self.assertRaises(ValueError):
            _profile_anchor_ids(annotation, profile, skin, np.array([0, 1, 3]))

    def test_observed_scope_exact_partition_and_omitted_provenance(self):
        import copy
        from unittest.mock import patch
        path = (Path.cwd() / 'source.png').resolve()
        frame = {'localIndex': 0, 'sourcePath': str(path), 'sourceSha256': 'frame',
                 'directionEvidence': 'observed', 'ambiguous': False}
        capture = {'captureSha256': 'capture', 'frameCount': 1, 'frames': [frame]}
        omitted = copy.deepcopy(capture)
        omitted['reason'] = 'Occluded endpoint; raw capture retained'
        annotation = {'completionScope': 'Observed only', 'captures': {'move': capture}, 'uncompletedCaptures': {'death': omitted}}
        corpus = {'captures': [{'key': key, 'captureSha256': 'capture', 'frames': [str(path)]} for key in ('move', 'death')]}
        paths = {'move': [path], 'death': [path]}
        with patch('run_source_wrist_trial.sha256_file', return_value='frame'):
            self.assertEqual(_profile_annotation_scope(annotation, corpus, path, paths)['completedFrameCount'], 1)
            for change in ('missing', 'duplicate', 'stale', 'inferred', 'reason'):
                bad = copy.deepcopy(annotation)
                if change == 'missing': bad['uncompletedCaptures'] = {}
                if change == 'duplicate': bad['uncompletedCaptures']['move'] = omitted
                if change == 'stale': bad['uncompletedCaptures']['death']['frames'][0]['sourceSha256'] = 'stale'
                if change == 'inferred': bad['captures']['move']['frames'][0]['directionEvidence'] = 'inferred'
                if change == 'reason': bad['uncompletedCaptures']['death']['reason'] = ''
                with self.subTest(change=change), self.assertRaises(ValueError):
                    _profile_annotation_scope(bad, corpus, path, paths)

    def fixture(self):
        skin = {'names': np.array(['root', 'hand']), 'parents': np.array([-1, 0]),
                'vertices': np.array([[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]),
                'triangles': np.array([[0, 1, 2]]), 'sourceVertexIds': np.arange(3),
                'weights': np.array([[0., 1.]] * 3), 'regions': np.array(['weapon'] * 3)}
        ownership = {'rigidParts': [{'owner': 'hand', 'region': 'weapon', 'faceIds': [0]}]}
        return skin, {k: v.copy() for k, v in skin.items()}, ownership

    def test_exact_profile_mask_preserves_candidate(self):
        fitted, prepared, ownership = self.fixture()
        candidate, selected = _validate_profile_skin(fitted, prepared, ownership, 'hand')
        np.testing.assert_array_equal(selected, [0])
        for key in candidate:
            np.testing.assert_array_equal(candidate[key], fitted[key])
            self.assertIsNot(candidate[key], fitted[key])

    def test_rejects_changed_topology_or_source_map(self):
        for key in ('triangles', 'sourceVertexIds'):
            fitted, prepared, ownership = self.fixture()
            fitted[key].flat[0] = 2
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'differs'):
                _validate_profile_skin(fitted, prepared, ownership, 'hand')

    def test_rejects_nonrigid_region_owner_and_face_drift(self):
        for fault in ('weights', 'regions', 'owner', 'faceIds'):
            fitted, prepared, ownership = self.fixture()
            if fault == 'weights':
                fitted['weights'][0] = [.1, .9]
            elif fault == 'regions':
                fitted['regions'][0] = 'body'
            elif fault == 'owner':
                ownership['rigidParts'][0]['owner'] = 'absent'
            else:
                ownership['rigidParts'][0]['faceIds'] = [0, 0]
            with self.subTest(fault=fault), self.assertRaises(ValueError):
                _validate_profile_skin(fitted, prepared, ownership, 'hand')


if __name__ == "__main__": unittest.main()
