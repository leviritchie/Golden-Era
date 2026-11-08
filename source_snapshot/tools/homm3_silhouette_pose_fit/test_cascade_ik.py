"""Tests for the IK initialization stage."""

from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from pathlib import Path

import torch

from roc_gpu_cascade_experiment import (
    GpuCascadeConfig,
    ik_ccd_chain,
    ik_chains_from_bone_roles,
    ik_unproject_2d_to_3d,
    load_ik_bone_roles,
    load_ik_keypoints,
    resolve_ik_bone_roles_path,
    resolve_ik_keypoints_path,
)


class TestIkConfig(unittest.TestCase):
    """Test GpuCascadeConfig IK field validation."""

    def test_ik_defaults(self) -> None:
        config = GpuCascadeConfig()
        self.assertFalse(config.ik_enabled)
        self.assertIsNone(config.ik_keypoints_path)
        self.assertIsNone(config.ik_bone_roles_path)
        self.assertEqual(config.ik_iterations, 16)
        self.assertAlmostEqual(config.ik_max_step_deg, 15.0)
        self.assertEqual(config.ik_miss_max_pairs, 2)
        self.assertAlmostEqual(config.ik_blob_iou_target, 0.9)
        self.assertEqual(config.ik_proximal_min_depth, 3)
        self.assertAlmostEqual(config.ik_proximal_max_step_deg, 5.0)
        self.assertEqual(config.ik_max_chain_depth, 6)
        self.assertEqual(config.ik_blob_search_rounds, 3)
        self.assertEqual(config.ik_silhouette_score_mode, "regional_iou")

    def test_ik_silhouette_score_mode_validation(self) -> None:
        config = GpuCascadeConfig(
            ik_enabled=True,
            ik_keypoints_source="silhouette_miss",
            ik_silhouette_score_mode="wrong",
        )
        with self.assertRaises(ValueError):
            config.validate()
        config = GpuCascadeConfig(ik_enabled=True, ik_keypoints_path=None, ik_bone_roles_path=None)
        with self.assertRaises(ValueError):
            config.validate()
        config = GpuCascadeConfig(
            ik_enabled=True,
            ik_keypoints_source="silhouette_miss",
        )
        config.validate()
        config = GpuCascadeConfig(
            ik_enabled=True,
            ik_keypoints_source="authored",
            ik_bone_roles_path="tools/homm3_silhouette_pose_fit/bone_roles_crusader_meshy_t2.json",
            ik_keypoints_path="foo.json",
        )
        config.validate()
        config = GpuCascadeConfig(
            ik_enabled=True,
            ik_keypoints_source="authored",
            ik_keypoints_path=None,
            ik_bone_roles_path="tools/homm3_silhouette_pose_fit/bone_roles_crusader_meshy_t2.json",
        )
        with self.assertRaises(ValueError):
            config.validate()
        config = GpuCascadeConfig(ik_enabled=True, ik_keypoints_path="foo.json", ik_bone_roles_path=None)
        with self.assertRaises(ValueError):
            config.validate()

    def test_ik_iterations_positive(self) -> None:
        config = GpuCascadeConfig(ik_enabled=True, ik_keypoints_path="a.json", ik_bone_roles_path="b.json", ik_iterations=0)
        with self.assertRaises(ValueError):
            config.validate()
        config = GpuCascadeConfig(ik_enabled=True, ik_keypoints_path="a.json", ik_bone_roles_path="b.json", ik_iterations=-1)
        with self.assertRaises(ValueError):
            config.validate()

    def test_ik_max_step_deg_range(self) -> None:
        config = GpuCascadeConfig(ik_enabled=True, ik_keypoints_path="a.json", ik_bone_roles_path="b.json", ik_max_step_deg=0.0)
        with self.assertRaises(ValueError):
            config.validate()
        config = GpuCascadeConfig(ik_enabled=True, ik_keypoints_path="a.json", ik_bone_roles_path="b.json", ik_max_step_deg=-1.0)
        with self.assertRaises(ValueError):
            config.validate()


class TestLoadIkKeypoints(unittest.TestCase):
    """Test loading keypoints.json."""

    def test_load_valid_keypoints(self) -> None:
        data = {
            "method": "human_eye_landmark_authoring",
            "frames": [
                {
                    "frameIndex": 0,
                    "joints": {
                        "Nose": {"x": 100, "y": 50, "visible": True},
                        "WeaponTip": {"x": 200, "y": 150, "visible": True},
                    },
                },
                {
                    "frameIndex": 5,
                    "joints": {
                        "Nose": {"x": 105, "y": 55, "visible": True},
                        "WeaponTip": {"x": 205, "y": 155, "visible": True},
                    },
                },
            ],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            result = load_ik_keypoints(path)
            self.assertIn(0, result)
            self.assertIn(5, result)
            self.assertEqual(result[0]["Nose"], (100.0, 50.0))
            self.assertEqual(result[0]["WeaponTip"], (200.0, 150.0))
            self.assertEqual(result[5]["Nose"], (105.0, 55.0))
        finally:
            os.unlink(path)

    def test_load_missing_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_ik_keypoints("/nonexistent/path.json")


class TestLoadIkBoneRoles(unittest.TestCase):
    """Test loading bone_roles.json."""

    def test_load_valid_bone_roles(self) -> None:
        data = {
            "joints": {
                "Nose": "Head",
                "WeaponTip": "RightHand",
                "LWrist": "LeftHand",
            }
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            path = f.name
        try:
            result = load_ik_bone_roles(path)
            self.assertEqual(result["Nose"], "Head")
            self.assertEqual(result["WeaponTip"], "RightHand")
            self.assertEqual(result["LWrist"], "LeftHand")
        finally:
            os.unlink(path)

    def test_load_missing_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            load_ik_bone_roles("/nonexistent/path.json")


class TestIkUnproject2dTo3d(unittest.TestCase):
    """Test 2D→3D unprojection."""

    def test_unproject_center(self) -> None:
        right = torch.tensor([1.0, 0.0, 0.0])
        down = torch.tensor([0.0, 1.0, 0.0])
        forward = torch.tensor([0.0, 0.0, 1.0])
        offset = torch.tensor([100.0, 100.0])
        px_per_world = torch.tensor([10.0, 10.0])
        depth = 0.5

        result = ik_unproject_2d_to_3d(100.0, 100.0, depth, right, down, forward, offset, px_per_world)
        self.assertAlmostEqual(float(result[0]), 0.0, places=5)
        self.assertAlmostEqual(float(result[1]), 0.0, places=5)
        self.assertAlmostEqual(float(result[2]), 0.5, places=5)

    def test_unproject_offset(self) -> None:
        right = torch.tensor([1.0, 0.0, 0.0])
        down = torch.tensor([0.0, 1.0, 0.0])
        forward = torch.tensor([0.0, 0.0, 1.0])
        offset = torch.tensor([100.0, 100.0])
        px_per_world = torch.tensor([10.0, 10.0])
        depth = 0.5

        result = ik_unproject_2d_to_3d(110.0, 120.0, depth, right, down, forward, offset, px_per_world)
        self.assertAlmostEqual(float(result[0]), 1.0, places=5)
        self.assertAlmostEqual(float(result[1]), 2.0, places=5)
        self.assertAlmostEqual(float(result[2]), 0.5, places=5)


class TestIkCcdChain(unittest.TestCase):
    """Test CCD IK solver."""

    def _make_simple_skeleton(self) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor, torch.Tensor]:
        """Create a simple 3-bone chain skeleton."""
        parents = torch.tensor([-1, 0, 1], dtype=torch.long)
        base_rotations = torch.eye(3).unsqueeze(0).repeat(3, 1, 1)
        translations = torch.tensor([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
        ])
        scales = torch.ones(3, 3)
        return parents, base_rotations, translations, scales

    def _fk(self, bone_vectors: torch.Tensor, parents: torch.Tensor, base_rotations: torch.Tensor, translations: torch.Tensor, scales: torch.Tensor) -> torch.Tensor:
        """Simple FK for testing. bone_vectors is (batch, n_bones, 3) axis-angle."""
        n_frames, n_bones, _ = bone_vectors.shape
        world = torch.zeros(n_frames, n_bones, 4, 4)
        for i in range(n_bones):
            # Convert axis-angle to rotation matrix using Rodrigues' formula
            r = bone_vectors[:, i, :]  # (batch, 3)
            angle = torch.norm(r, dim=-1, keepdim=True)  # (batch, 1)
            axis = r / (angle + 1e-8)  # (batch, 3)
            # Rodrigues' formula
            K = torch.zeros(n_frames, 3, 3)
            K[:, 0, 1] = -axis[:, 2]
            K[:, 0, 2] = axis[:, 1]
            K[:, 1, 0] = axis[:, 2]
            K[:, 1, 2] = -axis[:, 0]
            K[:, 2, 0] = -axis[:, 1]
            K[:, 2, 1] = axis[:, 0]
            I = torch.eye(3).unsqueeze(0).expand(n_frames, -1, -1)
            R = I + torch.sin(angle).unsqueeze(-1) * K + (1 - torch.cos(angle)).unsqueeze(-1) * (K @ K)
            local = torch.eye(4).unsqueeze(0).expand(n_frames, -1, -1).clone()
            local[:, :3, :3] = R
            local[:, :3, 3] = translations[i] * scales[i]
            if parents[i] >= 0:
                world[:, i] = world[:, parents[i]] @ local
            else:
                world[:, i] = local
        return world

    def test_ccd_chain_reaches_target(self) -> None:
        parents, base_rotations, translations, scales = self._make_simple_skeleton()
        bone_vectors = torch.zeros(3, 3)  # raw storage
        chain_indices = [0, 1, 2]
        target_pos = torch.tensor([1.5, 0.5, 0.0])
        end_effector_index = 2
        joint_limit_rad = math.radians(150.0)
        bone_limit_scales = torch.ones(3, dtype=torch.float32)

        def fk_wrapper(raw):
            bounded = torch.tanh(raw) * joint_limit_rad
            return self._fk(
                bounded,
                parents,
                base_rotations,
                translations,
                scales,
            )

        result = ik_ccd_chain(
            bone_vectors,
            chain_indices,
            target_pos,
            end_effector_index,
            fk_wrapper,
            joint_limit_rad=joint_limit_rad,
            bone_limit_scales=bone_limit_scales,
            max_iterations=50,
            max_step_rad=math.radians(30.0),
        )
        self.assertEqual(result.shape, (3, 3))
        bounded = torch.tanh(result) * joint_limit_rad
        self.assertLess(float(bounded.abs().max().item()), joint_limit_rad + 1e-5)

    def test_ccd_chain_respects_bounded_limits(self) -> None:
        parents, base_rotations, translations, scales = self._make_simple_skeleton()
        bone_vectors = torch.zeros(3, 3)
        chain_indices = [0, 1, 2]
        target_pos = torch.tensor([10.0, 10.0, 0.0])
        end_effector_index = 2
        joint_limit_rad = math.radians(150.0)
        bone_limit_scales = torch.ones(3, dtype=torch.float32)

        def fk_wrapper(raw):
            bounded = torch.tanh(raw) * joint_limit_rad
            return self._fk(
                bounded,
                parents,
                base_rotations,
                translations,
                scales,
            )

        result = ik_ccd_chain(
            bone_vectors,
            chain_indices,
            target_pos,
            end_effector_index,
            fk_wrapper,
            joint_limit_rad=joint_limit_rad,
            bone_limit_scales=bone_limit_scales,
            max_iterations=40,
            max_step_rad=math.radians(5.0),
        )
        bounded = torch.tanh(result) * joint_limit_rad
        self.assertLessEqual(float(bounded.abs().max().item()), joint_limit_rad + 1e-5)


class TestIkPathResolve(unittest.TestCase):
    """Test authored-stick and bone-role path resolution."""

    def test_explicit_keypoints_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            authored = root / "stick.json"
            authored.write_text("{}", encoding="utf-8")
            resolved = resolve_ik_keypoints_path(
                root=root,
                unit_name="crusader",
                animation_name="g00_move",
                explicit=str(authored),
            )
            self.assertEqual(resolved, authored.resolve())

    def test_auto_keypoints_prefers_authored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            authored = (
                root / "artifacts" / "crusader_pose_pipeline" / "out_fit"
                / "g00_move_authored" / "sprite_landmarks" / "keypoints.json"
            )
            authored.parent.mkdir(parents=True)
            authored.write_text("{}", encoding="utf-8")
            resolved = resolve_ik_keypoints_path(
                root=root,
                unit_name="crusader",
                animation_name="g00_move",
                explicit=None,
            )
            self.assertEqual(resolved, authored.resolve())

    def test_auto_keypoints_missing_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FileNotFoundError) as raised:
                resolve_ik_keypoints_path(
                    root=root,
                    unit_name="crusader",
                    animation_name="idle_start_move",
                    explicit=None,
                    def_lab_groups=(2, 20, 0),
                    def_expected_counts=(8, 2, 8),
                )
            message = str(raised.exception)
            self.assertIn("g02_idle", message)
            self.assertIn("Do not point CASCADE_IK_KEYPOINTS_PATH at one child clip", message)

    def test_auto_keypoints_alias_move(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            authored = (
                root / "artifacts" / "crusader_pose_pipeline" / "out_fit"
                / "g00_move_authored" / "sprite_landmarks" / "keypoints.json"
            )
            authored.parent.mkdir(parents=True)
            authored.write_text("{}", encoding="utf-8")
            resolved = resolve_ik_keypoints_path(
                root=root,
                unit_name="crusader",
                animation_name="move",
                explicit=None,
            )
            self.assertEqual(resolved, authored.resolve())

    def test_sequence_stitch_when_every_segment_is_authored(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fit = root / "artifacts" / "crusader_pose_pipeline" / "out_fit"

            def write_clip(stem: str, n: int) -> None:
                path = fit / f"{stem}_authored" / "sprite_landmarks" / "keypoints.json"
                path.parent.mkdir(parents=True)
                frames = [
                    {
                        "frameIndex": index,
                        "joints": {"Nose": {"x": float(index), "y": 1.0, "visible": True}},
                    }
                    for index in range(n)
                ]
                path.write_text(
                    json.dumps({"method": "human_eye_landmark_authoring", "frames": frames}),
                    encoding="utf-8",
                )

            write_clip("g02_idle", 2)
            write_clip("g20_move_start", 1)
            write_clip("g00_move", 2)
            resolved = resolve_ik_keypoints_path(
                root=root,
                unit_name="crusader",
                animation_name="idle_start_move",
                explicit=None,
                def_lab_groups=(2, 20, 0),
                def_expected_counts=(2, 1, 2),
            )
            payload = json.loads(resolved.read_text(encoding="utf-8"))
            self.assertEqual([frame["frameIndex"] for frame in payload["frames"]], [0, 1, 2, 3, 4])

    def test_auto_bone_roles_prefers_meshy_for_smartrig(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp)
            owned = tools / "bone_roles_crusader_owned.json"
            meshy = tools / "bone_roles_crusader_meshy_t2.json"
            owned.write_text("{}", encoding="utf-8")
            meshy.write_text("{}", encoding="utf-8")
            glb = Path(tmp) / "h3_crusader_smartrigged_rigidized.glb"
            resolved = resolve_ik_bone_roles_path(
                unit_name="crusader",
                src_glb=glb,
                explicit=None,
                tools_dir=tools,
            )
            self.assertEqual(resolved, meshy.resolve())

    def test_auto_bone_roles_prefers_owned_for_owned_bind(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tools = Path(tmp)
            owned = tools / "bone_roles_crusader_owned.json"
            meshy = tools / "bone_roles_crusader_meshy_t2.json"
            owned.write_text("{}", encoding="utf-8")
            meshy.write_text("{}", encoding="utf-8")
            glb = Path(tmp) / "owned_bind" / "crusader_master.glb"
            glb.parent.mkdir()
            resolved = resolve_ik_bone_roles_path(
                unit_name="crusader",
                src_glb=glb,
                explicit=None,
                tools_dir=tools,
            )
            self.assertEqual(resolved, owned.resolve())


class TestIkChainsFromBoneRoles(unittest.TestCase):
    def test_builds_chain_and_skips_root(self) -> None:
        bone_roles = {"Nose": "Head", "WeaponTip": "RightHand", "RWrist": "RightHand"}
        node_index = {"Hips": 0, "Spine": 1, "Head": 2, "RightArm": 3, "RightHand": 4}
        parents = [None, 0, 1, 0, 3]
        chains = ik_chains_from_bone_roles(bone_roles, node_index, parents)
        by_joint = {joint: chain for chain, joint, _end in chains}
        self.assertEqual(by_joint["Nose"], [1, 2])
        self.assertEqual(by_joint["WeaponTip"], [3, 4])
        self.assertNotIn("RWrist", by_joint)

    def test_empty_mapping_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            ik_chains_from_bone_roles({"Nose": "Missing"}, {}, [None])


if __name__ == "__main__":
    unittest.main()
