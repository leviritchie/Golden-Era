"""Shared direction-retargeter controls. No GPU and no position_transfer solver."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from capture_binding import deforming_bones_from_aim_chains, validate_retarget_binding
from direction_retarget import (
    MOTION_GATE_RAD,
    TWIST_POLICY,
    bone_lengths,
    motion_preservation_report,
    retarget_clip,
    transport_bind_deltas,
)
from glb_skeleton import load_bind_skeleton
from mesh_preview import fk_world_matrices, rotation_between
from paths import MESHY, MOCAP_INTERMEDIATE, VENDOR_DEMO
from pin import sha256_file
from test_native_rotation import axis_rotation
from vendor_reference import load_complete_package


def _chain_rig(*, joint_count: int, bone: tuple[float, float, float], prefix: str) -> dict[str, np.ndarray | list[str]]:
    names = [f"{prefix}{index}" for index in range(joint_count)]
    parents = np.asarray([-1, *range(joint_count - 1)], dtype=np.int64)
    rest_local = np.repeat(np.eye(3, dtype=np.float64)[None], joint_count, axis=0)
    rest_off = np.zeros((joint_count, 3), dtype=np.float64)
    for index in range(1, joint_count):
        rest_off[index] = np.asarray(bone, dtype=np.float64)
    world = fk_world_matrices(
        local_rotation=rest_local,
        local_translation=rest_off,
        parents=parents,
        root_world=np.zeros(3, dtype=np.float64),
    )
    return {
        "names": names,
        "parents": parents,
        "rest_local": rest_local,
        "rest_off": rest_off,
        "rest_world": world[:, :3, 3],
        "rest_mats": world,
    }


def _pose_positions(rig: dict, local: np.ndarray) -> np.ndarray:
    world = fk_world_matrices(
        local_rotation=local,
        local_translation=rig["rest_off"],
        parents=rig["parents"],
        root_world=rig["rest_world"][0],
    )
    return world[:, :3, 3]


def _identity_chains(rig: dict) -> list[dict[str, object]]:
    return [{"name": "chain", "target": list(rig["names"]), "capture": list(rig["names"])}]


def _swing_local(rig: dict, joint: int, axis: int, angle: float) -> np.ndarray:
    local = rig["rest_local"].copy()
    local[joint] = axis_rotation(axis, angle) @ local[joint]
    return local


def _post_control_gif(name: str, capture: np.ndarray, retarget: np.ndarray, capture_parents: np.ndarray, target_parents: np.ndarray) -> None:
    dest = MOCAP_INTERMEDIATE / "retarget_controls" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    images: list[Image.Image] = []
    for frame in range(capture.shape[0]):
        image = Image.new("RGB", (420, 220), (16, 16, 20))
        draw = ImageDraw.Draw(image)
        draw.text((4, 2), name.replace(".gif", ""), fill=(230, 230, 235))

        def _draw(joints: np.ndarray, parents: np.ndarray, origin_x: int, color: tuple[int, int, int]) -> None:
            coords = joints[:, [0, 1]]
            span = max(float(np.max(np.abs(coords))), 1e-3)
            scale = 80.0 / span
            xy = coords * scale
            xy[:, 0] += origin_x
            xy[:, 1] = 120.0 - xy[:, 1]
            for index, parent in enumerate(parents):
                if int(parent) < 0:
                    continue
                x0, y0 = xy[int(parent)]
                x1, y1 = xy[index]
                draw.line((x0, y0, x1, y1), fill=color, width=2)
            for x, y in xy:
                draw.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)

        _draw(capture[frame], capture_parents, 110, (40, 90, 200))
        _draw(retarget[frame], target_parents, 310, (40, 180, 90))
        draw.text((70, 200), "capture XY", fill=(180, 180, 190))
        draw.text((270, 200), "retarget XY", fill=(180, 180, 190))
        images.append(image)
    images[0].save(dest, save_all=True, append_images=images[1:], duration=120, loop=0)


class DirectionRetargetImportTests(unittest.TestCase):
    def test_module_does_not_reuse_position_transfer(self) -> None:
        text = (EXPERIMENT / "direction_retarget.py").read_text(encoding="utf-8")
        self.assertNotIn("from position_transfer import", text)
        self.assertNotIn("import position_transfer", text)
        self.assertNotIn("solve_fixed_length", text)
        self.assertIn("parent-relative", text)
        self.assertIn(TWIST_POLICY.replace("_", "_"), text)


class DirectionRetargetControlTests(unittest.TestCase):
    def test_bind_delta_transport_preserves_target_bind_and_basis(self) -> None:
        source_rest = np.stack([axis_rotation(1, 0.2), axis_rotation(2, -0.4)])
        target_rest = np.stack([axis_rotation(0, -0.3), axis_rotation(1, 0.5)])
        source_delta = axis_rotation(2, 0.7)
        source_current = np.stack([source_rest, source_rest.copy()])
        source_current[1, 1] = source_rest[1] @ source_delta
        result = transport_bind_deltas(
            source_local_rotation=source_current,
            source_rest_local_rotation=source_rest,
            target_rest_local_rotation=target_rest,
            target_to_source={0: 0, 1: 1},
        )
        np.testing.assert_allclose(result[0], target_rest, atol=1e-7)
        basis = target_rest[1].T @ source_rest[1]
        expected = target_rest[1] @ basis @ source_delta @ basis.T
        np.testing.assert_allclose(result[1, 1], expected, atol=1e-7)

    def test_identity_mapping_recovers_known_swing(self) -> None:
        rig = _chain_rig(joint_count=4, bone=(0.0, 1.0, 0.0), prefix="j")
        swung = _swing_local(rig, 2, 2, 0.7)
        capture = np.stack([rig["rest_world"], _pose_positions(rig, swung), rig["rest_world"]])
        result = retarget_clip(
            capture_positions=capture,
            capture_rest=rig["rest_world"],
            capture_names=rig["names"],
            capture_parents=rig["parents"],
            target_names=rig["names"],
            target_parents=rig["parents"],
            target_rest_local_rotation=rig["rest_local"],
            target_rest_local_translation=rig["rest_off"],
            target_rest_world=rig["rest_world"],
            chains=_identity_chains(rig),
            regularize=False,
        )
        expected = np.stack(
            [
                rig["rest_world"],
                _pose_positions(rig, swung),
                rig["rest_world"],
            ]
        )
        np.testing.assert_allclose(result["jointWorld"][:, :, :3, 3], expected, atol=1e-5)
        self.assertLess(result["lengthErrorMax"], 1e-6)
        self.assertFalse(result["rootTranslationAvailable"])
        self.assertEqual(result["twistPolicy"], TWIST_POLICY)
        self.assertTrue(result["motionPreservation"]["motionPreserved"])
        _post_control_gif(
            "identity_known_swing.gif",
            capture,
            result["jointWorld"][:, :, :3, 3],
            rig["parents"],
            rig["parents"],
        )

    def test_changed_proportions_keep_target_lengths(self) -> None:
        capture_rig = _chain_rig(joint_count=3, bone=(0.0, 1.0, 0.0), prefix="c")
        target_rig = _chain_rig(joint_count=3, bone=(0.0, 2.5, 0.0), prefix="c")
        swung = _swing_local(capture_rig, 1, 2, 0.6)
        capture = np.stack([capture_rig["rest_world"], _pose_positions(capture_rig, swung)])
        chains = [{"name": "arm", "target": target_rig["names"], "capture": capture_rig["names"]}]
        result = retarget_clip(
            capture_positions=capture,
            capture_rest=capture_rig["rest_world"],
            capture_names=capture_rig["names"],
            capture_parents=capture_rig["parents"],
            target_names=target_rig["names"],
            target_parents=target_rig["parents"],
            target_rest_local_rotation=target_rig["rest_local"],
            target_rest_local_translation=target_rig["rest_off"],
            target_rest_world=target_rig["rest_world"],
            chains=chains,
            regularize=False,
        )
        rest_len = bone_lengths(target_rig["rest_mats"], target_rig["parents"])
        posed_len = bone_lengths(result["jointWorld"][1], target_rig["parents"])
        np.testing.assert_allclose(posed_len, rest_len, atol=1e-6)
        rest_dir = target_rig["rest_world"][2] - target_rig["rest_world"][1]
        pose_dir = result["jointWorld"][1, 2, :3, 3] - result["jointWorld"][1, 1, :3, 3]
        capture_dir = capture[1, 2] - capture[1, 1]
        capture_rest_dir = capture_rig["rest_world"][2] - capture_rig["rest_world"][1]
        # Bind-frame: the same swing appears on the longer target bone.
        self.assertGreater(
            float(np.linalg.norm(rotation_between(rest_dir, pose_dir) - np.eye(3))),
            0.1,
        )
        self.assertGreater(float(np.linalg.norm(capture_dir - capture_rest_dir)), 0.1)
        _post_control_gif(
            "changed_proportions.gif",
            capture,
            result["jointWorld"][:, :, :3, 3],
            capture_rig["parents"],
            target_rig["parents"],
        )

    def test_different_chain_segmentation(self) -> None:
        capture_rig = _chain_rig(joint_count=5, bone=(0.0, 1.0, 0.0), prefix="c")
        target_rig = _chain_rig(joint_count=3, bone=(0.0, 1.5, 0.0), prefix="t")
        local = capture_rig["rest_local"].copy()
        local[2] = axis_rotation(2, 0.9) @ local[2]
        capture = np.stack([capture_rig["rest_world"], _pose_positions(capture_rig, local)])
        chains = [
            {
                "name": "limb",
                "target": target_rig["names"],
                "capture": capture_rig["names"],
            }
        ]
        result = retarget_clip(
            capture_positions=capture,
            capture_rest=capture_rig["rest_world"],
            capture_names=capture_rig["names"],
            capture_parents=capture_rig["parents"],
            target_names=target_rig["names"],
            target_parents=target_rig["parents"],
            target_rest_local_rotation=target_rig["rest_local"],
            target_rest_local_translation=target_rig["rest_off"],
            target_rest_world=target_rig["rest_world"],
            chains=chains,
            regularize=False,
        )
        rest_tip = target_rig["rest_world"][-1] - target_rig["rest_world"][0]
        pose_tip = result["jointWorld"][1, -1, :3, 3] - result["jointWorld"][1, 0, :3, 3]
        self.assertGreater(float(np.linalg.norm(_unit(pose_tip) - _unit(rest_tip))), 0.05)
        self.assertLess(result["lengthErrorMax"], 1e-6)
        _post_control_gif(
            "different_segmentation.gif",
            capture,
            result["jointWorld"][:, :, :3, 3],
            capture_rig["parents"],
            target_rig["parents"],
        )

    def test_reference_pose_maps_to_rest_with_unequal_bent_target_bones(self) -> None:
        # Target chain: three bones of very different lengths, bent at each joint.
        # Capture chain: four equal bones. With pose == reference, every target
        # bone must return exactly to rest, otherwise a mesh whose rest is the
        # sprite frame-0 pose would be displaced on frame 0.
        names = ["t0", "t1", "t2", "t3"]
        parents = np.asarray([-1, 0, 1, 2], dtype=np.int64)
        rest_local = np.stack(
            [np.eye(3), axis_rotation(2, 0.5), axis_rotation(0, -0.8), axis_rotation(1, 0.35)]
        )
        rest_off = np.asarray([[0, 0, 0], [0, 0.15, 0], [0, 0.9, 0], [0, 0.35, 0]], dtype=np.float64)
        rest_mats = fk_world_matrices(
            local_rotation=rest_local,
            local_translation=rest_off,
            parents=parents,
            root_world=np.zeros(3),
        )
        target_rest = rest_mats[:, :3, 3]
        capture_rig = _chain_rig(joint_count=5, bone=(0.0, 1.0, 0.0), prefix="c")
        swung = capture_rig["rest_local"].copy()
        swung[2] = axis_rotation(2, 0.6) @ swung[2]
        reference = _pose_positions(capture_rig, swung)
        moved = capture_rig["rest_local"].copy()
        moved[2] = axis_rotation(2, 1.1) @ moved[2]
        capture = np.stack([reference, _pose_positions(capture_rig, moved), reference])
        result = retarget_clip(
            capture_positions=capture,
            capture_rest=reference,
            capture_names=capture_rig["names"],
            capture_parents=capture_rig["parents"],
            target_names=names,
            target_parents=parents,
            target_rest_local_rotation=rest_local,
            target_rest_local_translation=rest_off,
            target_rest_world=target_rest,
            chains=[{"name": "limb", "target": names, "capture": capture_rig["names"]}],
            regularize=False,
        )
        for frame in (0, 2):
            np.testing.assert_allclose(result["sourceLocalRotation"][frame], rest_local, atol=1e-9)
            np.testing.assert_allclose(result["jointWorld"][frame, :, :3, 3], target_rest, atol=1e-9)
        self.assertGreater(
            float(np.abs(result["sourceLocalRotation"][1] - rest_local).max()), 0.05
        )
        self.assertLess(result["lengthErrorMax"], 1e-9)

    def test_branching_aligns_fork_and_leaves_unrelated_child(self) -> None:
        names = ["root", "spine", "left", "right", "head"]
        parents = np.asarray((-1, 0, 1, 1, 0), dtype=np.int64)
        rest_local = np.repeat(np.eye(3)[None], 5, axis=0)
        rest_off = np.asarray(
            (
                (0.0, 0.0, 0.0),
                (0.0, 1.0, 0.0),
                (-0.8, 0.2, 0.0),
                (0.8, 0.2, 0.0),
                (0.0, 0.8, 0.0),
            ),
            dtype=np.float64,
        )
        rest_mats = fk_world_matrices(
            local_rotation=rest_local,
            local_translation=rest_off,
            parents=parents,
            root_world=np.zeros(3),
        )
        rest_world = rest_mats[:, :3, 3]
        local = rest_local.copy()
        local[1] = axis_rotation(2, 0.5) @ local[1]
        capture = np.stack(
            [
                rest_world,
                fk_world_matrices(
                    local_rotation=local,
                    local_translation=rest_off,
                    parents=parents,
                    root_world=np.zeros(3),
                )[:, :3, 3],
            ]
        )
        chains = [
            {"name": "left", "target": ["root", "spine", "left"], "capture": ["root", "spine", "left"]},
            {"name": "right", "target": ["root", "spine", "right"], "capture": ["root", "spine", "right"]},
        ]
        result = retarget_clip(
            capture_positions=capture,
            capture_rest=rest_world,
            capture_names=names,
            capture_parents=parents,
            target_names=names,
            target_parents=parents,
            target_rest_local_rotation=rest_local,
            target_rest_local_translation=rest_off,
            target_rest_world=rest_world,
            chains=chains,
            regularize=False,
        )
        left_travel = float(np.linalg.norm(result["jointWorld"][1, 2, :3, 3] - rest_world[2]))
        right_travel = float(np.linalg.norm(result["jointWorld"][1, 3, :3, 3] - rest_world[3]))
        head_travel = float(np.linalg.norm(result["jointWorld"][1, 4, :3, 3] - rest_world[4]))
        self.assertGreater(left_travel, 0.2)
        self.assertGreater(right_travel, 0.2)
        self.assertLess(head_travel, 1e-5)
        _post_control_gif(
            "branching.gif",
            capture,
            result["jointWorld"][:, :, :3, 3],
            parents,
            parents,
        )

    def test_zero_motion_stays_at_rest(self) -> None:
        rig = _chain_rig(joint_count=4, bone=(0.0, 1.0, 0.0), prefix="j")
        capture = np.repeat(rig["rest_world"][None, ...], 4, axis=0)
        result = retarget_clip(
            capture_positions=capture,
            capture_rest=rig["rest_world"],
            capture_names=rig["names"],
            capture_parents=rig["parents"],
            target_names=rig["names"],
            target_parents=rig["parents"],
            target_rest_local_rotation=rig["rest_local"],
            target_rest_local_translation=rig["rest_off"],
            target_rest_world=rig["rest_world"],
            chains=_identity_chains(rig),
            regularize=True,
        )
        np.testing.assert_allclose(result["jointWorld"][:, :, :3, 3], capture, atol=1e-6)
        self.assertFalse(result["motionPreservation"]["captureHasTemporalMotion"])
        _post_control_gif(
            "zero_motion.gif",
            capture,
            result["jointWorld"][:, :, :3, 3],
            rig["parents"],
            rig["parents"],
        )

    def test_coordinate_basis_change_cancels_in_bind_frame(self) -> None:
        names = ["j0", "j1", "j2", "j3"]
        parents = np.asarray((-1, 0, 1, 2), dtype=np.int64)
        rest_local = np.repeat(np.eye(3)[None], 4, axis=0)
        rest_off = np.asarray(
            ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.0, 0.0), (1.0, 0.0, 0.0)),
            dtype=np.float64,
        )
        rest_mats = fk_world_matrices(
            local_rotation=rest_local,
            local_translation=rest_off,
            parents=parents,
            root_world=np.zeros(3),
        )
        rest_world = rest_mats[:, :3, 3]
        local = rest_local.copy()
        local[2] = axis_rotation(1, 0.7) @ local[2]
        capture = np.stack(
            [
                rest_world,
                fk_world_matrices(
                    local_rotation=local,
                    local_translation=rest_off,
                    parents=parents,
                    root_world=np.zeros(3),
                )[:, :3, 3],
            ]
        )
        basis = axis_rotation(1, 0.5 * np.pi)
        rotated_rest = (basis @ rest_world.T).T
        rotated_capture = np.einsum("ij,tfj->tfi", basis, capture)
        kwargs = dict(
            capture_names=names,
            capture_parents=parents,
            target_names=names,
            target_parents=parents,
            target_rest_local_rotation=rest_local,
            target_rest_local_translation=rest_off,
            target_rest_world=rest_world,
            chains=[{"name": "chain", "target": names, "capture": names}],
            regularize=False,
        )
        original = retarget_clip(capture_positions=capture, capture_rest=rest_world, **kwargs)
        rotated = retarget_clip(capture_positions=rotated_capture, capture_rest=rotated_rest, **kwargs)
        np.testing.assert_allclose(
            rotated["jointWorld"][:, :, :3, 3],
            original["jointWorld"][:, :, :3, 3],
            atol=1e-5,
        )
        _post_control_gif(
            "coordinate_basis.gif",
            rotated_capture,
            rotated["jointWorld"][:, :, :3, 3],
            parents,
            parents,
        )

    def test_root_translation_is_not_manufactured(self) -> None:
        rig = _chain_rig(joint_count=3, bone=(0.0, 1.0, 0.0), prefix="j")
        swung = _swing_local(rig, 1, 2, 0.4)
        capture = np.stack([_pose_positions(rig, swung), _pose_positions(rig, swung)])
        capture = capture + np.asarray((3.0, -2.0, 1.5))
        result = retarget_clip(
            capture_positions=capture,
            capture_rest=rig["rest_world"],
            capture_names=rig["names"],
            capture_parents=rig["parents"],
            target_names=rig["names"],
            target_parents=rig["parents"],
            target_rest_local_rotation=rig["rest_local"],
            target_rest_local_translation=rig["rest_off"],
            target_rest_world=rig["rest_world"],
            chains=_identity_chains(rig),
            regularize=False,
        )
        np.testing.assert_allclose(
            result["jointWorld"][:, 0, :3, 3],
            np.broadcast_to(rig["rest_world"][0], (capture.shape[0], 3)),
            atol=1e-8,
        )
        self.assertLess(result["rootTravelMax"], 1e-8)
        self.assertFalse(result["rootTranslationAvailable"])

    def test_stationary_displaced_pose_fails_motion_gate(self) -> None:
        rig = _chain_rig(joint_count=4, bone=(0.0, 1.0, 0.0), prefix="j")
        swung = _swing_local(rig, 2, 2, 0.9)
        bent = _pose_positions(rig, swung)
        capture = np.repeat(bent[None, ...], 5, axis=0)
        result = retarget_clip(
            capture_positions=capture,
            capture_rest=rig["rest_world"],
            capture_names=rig["names"],
            capture_parents=rig["parents"],
            target_names=rig["names"],
            target_parents=rig["parents"],
            target_rest_local_rotation=rig["rest_local"],
            target_rest_local_translation=rig["rest_off"],
            target_rest_world=rig["rest_world"],
            chains=_identity_chains(rig),
            regularize=False,
        )
        preservation = result["motionPreservation"]
        self.assertGreater(preservation["capture"]["fromRestMaxRad"], MOTION_GATE_RAD)
        self.assertFalse(preservation["captureHasTemporalMotion"])
        self.assertFalse(preservation["motionPreserved"])
        self.assertTrue(preservation["stationaryDisplacedDoesNotPass"])
        _post_control_gif(
            "stationary_displaced.gif",
            capture,
            result["jointWorld"][:, :, :3, 3],
            rig["parents"],
            rig["parents"],
        )

    def test_regularizer_cannot_silently_erase_stroke(self) -> None:
        rig = _chain_rig(joint_count=4, bone=(0.0, 1.0, 0.0), prefix="j")
        frames = [rig["rest_world"]]
        for angle in (0.3, 0.6, 0.9, 0.4, 0.0):
            frames.append(_pose_positions(rig, _swing_local(rig, 2, 2, angle)))
        capture = np.stack(frames)
        result = retarget_clip(
            capture_positions=capture,
            capture_rest=rig["rest_world"],
            capture_names=rig["names"],
            capture_parents=rig["parents"],
            target_names=rig["names"],
            target_parents=rig["parents"],
            target_rest_local_rotation=rig["rest_local"],
            target_rest_local_translation=rig["rest_off"],
            target_rest_world=rig["rest_world"],
            chains=_identity_chains(rig),
            regularize=True,
            regularizer_weight=1.0,
        )
        self.assertFalse(result["motionPreservation"]["regularizerSuppressedStroke"])
        self.assertTrue(result["motionPreservation"]["motionPreserved"])
        rest_like = np.repeat(np.array([[1.0, 0.0, 0.0]]), 4, axis=0)
        swinging = np.stack(
            [
                np.array((1.0, 0.0, 0.0)),
                np.array((0.0, 1.0, 0.0)),
                np.array((-1.0, 0.0, 0.0)),
                np.array((0.0, -1.0, 0.0)),
            ]
        )
        capture_local = np.repeat(swinging[:, None, :], 2, axis=1)
        erased = np.repeat(rest_like[None, ...], 2, axis=1)
        report = motion_preservation_report(
            capture_local=capture_local,
            retarget_local=erased,
            unsmoothed_local=capture_local,
        )
        self.assertTrue(report["regularizerSuppressedStroke"])
        _post_control_gif(
            "regularizer_keeps_stroke.gif",
            capture,
            result["jointWorld"][:, :, :3, 3],
            rig["parents"],
            rig["parents"],
        )

    def test_finite_transforms_and_zero_unrelated_when_chain_skips_a_branch(self) -> None:
        names = ["root", "spine", "head", "wing"]
        parents = np.asarray((-1, 0, 1, 0), dtype=np.int64)
        rest_local = np.repeat(np.eye(3)[None], 4, axis=0)
        rest_off = np.asarray(
            ((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.8, 0.0), (0.9, 0.0, 0.0)),
            dtype=np.float64,
        )
        rest_mats = fk_world_matrices(
            local_rotation=rest_local,
            local_translation=rest_off,
            parents=parents,
            root_world=np.zeros(3),
        )
        rest_world = rest_mats[:, :3, 3]
        local = rest_local.copy()
        local[1] = axis_rotation(2, 0.55) @ local[1]
        capture = np.stack(
            [
                rest_world,
                fk_world_matrices(
                    local_rotation=local,
                    local_translation=rest_off,
                    parents=parents,
                    root_world=np.zeros(3),
                )[:, :3, 3],
            ]
        )
        result = retarget_clip(
            capture_positions=capture,
            capture_rest=rest_world,
            capture_names=names,
            capture_parents=parents,
            target_names=names,
            target_parents=parents,
            target_rest_local_rotation=rest_local,
            target_rest_local_translation=rest_off,
            target_rest_world=rest_world,
            chains=[{"name": "head", "target": ["root", "spine", "head"], "capture": ["root", "spine", "head"]}],
            regularize=False,
        )
        self.assertTrue(np.isfinite(result["jointWorld"]).all())
        wing_travel = float(np.linalg.norm(result["jointWorld"][1, 3, :3, 3] - rest_world[3]))
        head_travel = float(np.linalg.norm(result["jointWorld"][1, 2, :3, 3] - rest_world[2]))
        self.assertGreater(head_travel, 0.1)
        self.assertLess(wing_travel, 1e-5)


def _unit(vector: np.ndarray) -> np.ndarray:
    values = np.asarray(vector, dtype=np.float64).reshape(3)
    return values / float(np.linalg.norm(values))


class RocBindingLiveTests(unittest.TestCase):
    def test_frozen_roc_eagle_binding_covers_deforming_branches(self) -> None:
        bvh = VENDOR_DEMO / "zoo1030" / "bvh" / "Eagle#Eagle-Landing" / "y15.bvh"
        mesh = MESHY / "h3_roc_smartrigged.glb"
        if not bvh.is_file() or not mesh.is_file():
            self.skipTest("Eagle package or Roc mesh is not installed")
        package = load_complete_package("zoo", "Eagle#Eagle-Landing/y15")
        skeleton = load_bind_skeleton(mesh)
        binding = json.loads((EXPERIMENT / "roc_eagle_capture_binding.json").read_text(encoding="utf-8"))
        names = json.loads((EXPERIMENT / "roc_joint_names.json").read_text(encoding="utf-8"))
        required = deforming_bones_from_aim_chains(names)
        report = validate_retarget_binding(
            binding,
            capture_names=package["jointNames"],
            target_names=list(skeleton.names),
            capture_skeleton_sha256=sha256_file(bvh),
            target_mesh_sha256=sha256_file(mesh),
            required_target_branches=required,
        )
        self.assertTrue(report["ok"])
        self.assertGreaterEqual(report["chainCount"], 6)


if __name__ == "__main__":
    unittest.main()
