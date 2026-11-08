"""Whole-skeleton registration must not place full-size legs beneath a torso fit."""
import unittest
from pathlib import Path
import numpy as np
from static_bind_registration import (fit_skeleton_similarity, evaluate_rigid_compatibility,
                                      require_mesh_space_rest_report, mesh_space_rest_similarity, rotation_matrix)


class SkeletonSimilarityExtentTests(unittest.TestCase):
    def fixture(self):
        joints = np.array([[0, .0, 0], [0, .3, 0], [0, .6, 0], [0, .9, 0],
                           [-.3, .25, 0], [.3, .25, 0], [-.15, -.6, 0], [.15, -.6, 0],
                           [-.15, -1.1, .1], [.15, -1.1, .1]], dtype=float)
        groups = {'torso': [0, 1], 'neck_head': [2, 3], 'arm_left': [4],
                  'arm_right': [5], 'leg_left': [6, 8], 'leg_right': [7, 9]}
        offsets = np.array([[.025, 0, 0], [-.025, 0, 0], [0, .025, 0],
                            [0, -.025, 0], [0, 0, .025], [0, 0, -.025]])
        mesh = (joints[:, None] * .5 + offsets[None]).reshape(-1, 3)
        return joints, mesh, groups

    def test_full_extent_keeps_legs_in_mesh_and_all_branches_in_score(self):
        joints, mesh, groups = self.fixture()
        result = fit_skeleton_similarity(joints, mesh, groups)
        self.assertLess(result['scale'], .7)
        self.assertLess(max(result['branchSurfaceMeans'][name] for name in ('leg_left', 'leg_right')), .06)
        self.assertEqual(set(result['branchSurfaceMeans']), set(groups))
        self.assertAlmostEqual(result['branchBalancedSurfaceMean'], np.mean(list(result['branchSurfaceMeans'].values())))
        self.assertGreaterEqual(result['skeletonToMeshExtentRatio'], .75 - 1e-9)
        self.assertLessEqual(result['skeletonToMeshExtentRatio'], 1.25 + 1e-9)

    def test_scaling_and_translation_of_both_inputs_preserves_fit(self):
        joints, mesh, groups = self.fixture()
        first = fit_skeleton_similarity(joints, mesh, groups)
        factor = 3.
        shift = np.array([2., -4., 1.])
        second = fit_skeleton_similarity(joints * factor + shift, mesh * factor + shift, groups)
        np.testing.assert_allclose(second['joints'], first['joints'] * factor + shift, atol=1e-9)
        self.assertAlmostEqual(second['scale'], first['scale'])
        self.assertAlmostEqual(second['branchBalancedSurfaceMean'], first['branchBalancedSurfaceMean'] * factor)

    def test_missing_or_duplicate_joint_ownership_refuses(self):
        joints, mesh, groups = self.fixture()
        for replacement in ([6], [6, 8, 0]):
            changed = dict(groups, leg_left=replacement)
            with self.assertRaisesRegex(ValueError, 'every joint exactly once'):
                fit_skeleton_similarity(joints, mesh, changed)

    def test_zero_extent_refuses_instead_of_tiny_scale(self):
        joints, mesh, groups = self.fixture()
        with self.assertRaisesRegex(ValueError, 'nonzero extent'):
            fit_skeleton_similarity(np.zeros_like(joints), mesh, groups)

    def test_nonfinite_inputs_refuse(self):
        joints, mesh, groups = self.fixture()
        for points in (joints, mesh):
            for value in (np.nan, np.inf):
                changed = points.copy()
                changed[0, 0] = value
                args = (changed, mesh, groups) if points is joints else (joints, changed, groups)
                with self.assertRaisesRegex(ValueError, 'finite'):
                    fit_skeleton_similarity(*args)

    def test_namespaced_mounted_branches_need_no_body_alias(self):
        joints, mesh, groups = self.fixture()
        mounted = {('rider_' if name.startswith('arm_') else 'mount_') + name: indices
                   for name, indices in groups.items()}
        result = fit_skeleton_similarity(joints, mesh, mounted)
        original = fit_skeleton_similarity(joints, mesh, groups)
        np.testing.assert_allclose(result['joints'], original['joints'])
        self.assertIsNone(result['bodySurfaceMean'])
        self.assertEqual(set(result['branchSurfaceMeans']), set(mounted))
        placement = {'branches': {name: {'meanSurfaceDistance': 0., 'maxSurfaceDistance': 0.}
                                  for name in mounted}}
        gate = evaluate_rigid_compatibility(joints=result['joints'], names=[], vertices=mesh,
                                            groups=mounted, placement=placement)
        self.assertTrue(gate['compatibleUnderRigidAlignment'])
        self.assertFalse(gate['wingChecksApplied'])
        for name in ('wing_left', 'wing_right'):
            placement['branches'][name] = {'meanSurfaceDistance': 0., 'maxSurfaceDistance': 0.}
        with self.assertRaisesRegex(ValueError, 'wing compatibility requires declared'):
            evaluate_rigid_compatibility(joints=result['joints'], names=[], vertices=mesh,
                                         groups=mounted, placement=placement)

    def test_mesh_space_rest_hashes_and_identity_are_mandatory(self):
        report = dict(meshSha256='a' * 64, captureSha256='b' * 64, unit='fixture',
                      referenceFrame=0, restCoordinateSpace='source_mesh')
        args = dict(mesh_sha256='a' * 64, capture_sha256='b' * 64, unit='fixture', bind_frame=0)
        self.assertEqual(require_mesh_space_rest_report(report, **args), report)
        for key in report:
            for changed in ({k: v for k, v in report.items() if k != key}, dict(report, **{key: 'wrong'})):
                with self.assertRaises(ValueError):
                    require_mesh_space_rest_report(changed, **args)
        with self.assertRaises(ValueError):
            require_mesh_space_rest_report(report, **dict(args, bind_frame=1))

    def test_mesh_space_rest_uses_same_rotation_without_refit(self):
        joints, mesh, groups = self.fixture()
        rotation = rotation_matrix(60, 30, -30)
        result = mesh_space_rest_similarity(joints, mesh @ rotation.T, groups, rotation=rotation,
                                           yaw_deg=60, pitch_deg=30, roll_deg=-30)
        np.testing.assert_allclose(result['joints'], joints @ rotation.T)
        np.testing.assert_allclose(result['joints'] @ result['rotation'], joints, atol=1e-12)
        self.assertEqual(result['scale'], 1.)
        np.testing.assert_array_equal(result['translation'], np.zeros(3))
        self.assertIsNone(result['extentRatioBounds'])

    def test_mesh_space_rest_requires_complete_unique_joint_ownership(self):
        joints, mesh, groups = self.fixture()
        for replacement in ([6], [6, 8, 0]):
            with self.assertRaisesRegex(ValueError, 'every joint exactly once'):
                mesh_space_rest_similarity(joints, mesh, dict(groups, leg_left=replacement),
                                           rotation=np.eye(3), yaw_deg=0, pitch_deg=0, roll_deg=0)

    def test_build_contract_rejects_extent_ranking_and_provenance_regressions(self):
        from validate_homm3_attachment_pipeline_contract import validate_registration_similarity
        directory = Path(__file__).resolve().parent
        source = (directory / 'static_bind_registration.py').read_text(encoding='utf-8')
        runner = (directory / 'run_roc_idle_static_bind.py').read_text(encoding='utf-8')
        self.assertTrue(validate_registration_similarity(source, runner)['registrationWholeExtentBranchBalancedFit'])
        mutations = [
            source.replace('rotated = joints @ rotation.T', 'rotated = joints[body_idx] @ rotation.T'),
            source.replace('extent_bounds = (0.75, 1.25)', 'extent_bounds = (0.01, 10.0)'),
            source.replace('score = float(np.mean(list(branch_means.values())))', 'score = float(distances[body_idx].mean())'),
            source.replace('score < best["branchBalancedSurfaceMean"]', 'score < best["bodySurfaceMean"]'),
            source.replace('if body_idx else None', 'if body_idx else 0.0'),
            source.replace('mesh_center =', 'if not body_idx:\n        raise ValueError("legacy body required")\n    mesh_center =', 1),
        ]
        for changed in mutations:
            self.assertNotEqual(changed, source)
            with self.assertRaises(ValueError):
                validate_registration_similarity(changed, runner)
        with self.assertRaises(ValueError):
            validate_registration_similarity(source, runner.replace('"policy": similarity["policy"]', '"policy": "stale_policy"'))
        for changed in (source.replace('"scale": 1.0, "translation": np.zeros(3)', '"scale": 0.8, "translation": np.zeros(3)'),
                        source.replace('placed = joints @ rotation.T', 'placed = joints.copy()')):
            self.assertNotEqual(changed, source)
            with self.assertRaises(ValueError):
                validate_registration_similarity(changed, runner)
        with self.assertRaises(ValueError):
            validate_registration_similarity(source, runner.replace('rest_provenance = require_mesh_space_rest_report(', 'rest_provenance = unchecked_report('))


if __name__ == '__main__':
    unittest.main()
