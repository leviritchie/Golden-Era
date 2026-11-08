"""Plan, gate, and provenance tests for the linked-master pose-refine pilot."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from eagle_glb import gltf_world_matrices, matrices_to_xyzw, write_skinned_glb
from linked_master_pose_refine import (
    IDLE_MEAN_IOU_GAIN,
    acceptance,
    candidate_eligibility,
    evaluate_continuity,
    evaluate_geometry_gates,
    fold_toward_torso_deltas,
    identical_panel_close_box,
    per_clip_metrics,
    playback_continuity_pairs,
    pilot_frame_plan,
    reframe_parent_rotation,
    rotation_change_max,
    search_time_slices,
    source_matches_optimization_canvas,
    vertex_region_mask,
    wing_joint_indices,
)
from pose_rotation_fk import so3_exp_np
from verify_calibrated_export import verify_calibrated_export


def _segment(clip: str, group: int, start: int, count: int) -> dict:
    return {
        "clipKey": clip,
        "defGroup": group,
        "role": "cycle",
        "exportsClip": True,
        "globalStart": start,
        "globalEnd": start + count,
        "frameCount": count,
    }


def _master() -> dict:
    # idle 8, start 4, move 6, end 4 — same shape as the Roc linked master.
    return {
        "unit": "h3_roc",
        "segments": [
            _segment("g02_idle", 2, 0, 8),
            _segment("g20_move_start", 20, 8, 4),
            _segment("g00_move", 0, 12, 6),
            _segment("g21_move_end", 21, 18, 4),
        ],
        "frames": [{"globalIndex": i} for i in range(22)],
    }


class ObjectiveBuildContractTests(unittest.TestCase):
    def test_build_guard_rejects_dropped_objective_constraints(self):
        from tools.validate_homm3_attachment_pipeline_contract import validate_pose_refine_objective

        source = Path(__file__).with_name("run_roc_wing_pose_refine.py").read_text(encoding="utf-8")
        self.assertTrue(validate_pose_refine_objective(source)["poseRefineGateAlignedObjective"])
        for function in ("continuity_hinge_losses", "per_frame_iou_regression_hinge"):
            with self.assertRaises(ValueError):
                validate_pose_refine_objective(source.replace(function + "(", "removed_constraint("))
        for term in ("+ CONTINUITY_GATE_WEIGHT * (continuity[\"angular\"] + continuity[\"surface\"])",
                     "+ FRAME_IOU_GATE_WEIGHT * frame_regression"):
            with self.assertRaises(ValueError):
                validate_pose_refine_objective(source.replace(term, "+ 0.0"))


class PilotPlanTests(unittest.TestCase):
    def test_move_is_pinned_and_idle_is_free(self) -> None:
        plan = pilot_frame_plan(_master())
        self.assertEqual(plan["moveFrames"], list(range(12, 18)))
        self.assertEqual(plan["adjacentToMove"], [11, 18])
        self.assertTrue(set(plan["moveFrames"]).issubset(plan["pinnedFrames"]))
        self.assertNotIn(11, plan["freeFrames"])
        self.assertNotIn(18, plan["freeFrames"])
        self.assertEqual(plan["freeFrames"], list(range(0, 8)) + [8, 9, 10] + [19, 20, 21])
        self.assertIn((0, 1), plan["regularizePairs"])
        self.assertNotIn((11, 12), plan["regularizePairs"], "reel cut / move boundary is not a temporal pair")
        self.assertNotIn((17, 18), plan["regularizePairs"])

    def test_missing_move_start_fails_closed(self) -> None:
        master = _master()
        master["segments"] = [s for s in master["segments"] if s["defGroup"] != 20]
        with self.assertRaisesRegex(ValueError, "MoveStart"):
            pilot_frame_plan(master)

    def test_wing_joints_come_from_profile_regions_not_hard_names(self) -> None:
        names = ["root", "spine", "left_a", "left_b", "right_a", "leg"]
        regions = {
            "torso": ("root", "spine"),
            "wing_left": ("left_a", "left_b"),
            "wing_right": ("right_a",),
            "leg_left": ("leg",),
        }
        wings = wing_joint_indices(names, regions)
        self.assertEqual(wings["names"], ["left_a", "left_b", "right_a"])
        self.assertEqual(wings["protectedNames"], ["root", "spine", "leg"])
        with self.assertRaisesRegex(ValueError, "no wing_"):
            wing_joint_indices(names, {"torso": ("root",), "arm_left": ("left_a",)})


def _mesh_support(regions: np.ndarray, rest: np.ndarray) -> dict:
    triangles = np.asarray(((0, 1, 2), (0, 1, 3), (0, 1, 4), (0, 1, 5)), dtype=np.int64)
    edges = np.unique(np.sort(np.concatenate((triangles[:, :2], triangles[:, 1:], triangles[:, [0, 2]])), axis=1), axis=0)
    lengths = np.linalg.norm(rest[edges[:, 0]] - rest[edges[:, 1]], axis=1)
    return {"triangles": triangles, "edges": edges, "rest_lengths": lengths, "rest_verts": rest, "regions": regions}


def _geometry(before, after, support):
    return evaluate_geometry_gates(
        before_verts=before, after_verts=after, regions=support["regions"],
        rest_verts=support["rest_verts"], triangles=support["triangles"],
        edges=support["edges"], rest_lengths=support["rest_lengths"],
    )


class GateTests(unittest.TestCase):
    def test_mean_iou_alone_is_not_acceptance(self) -> None:
        plan = pilot_frame_plan(_master())
        before_iou = [0.4] * 22
        after_iou = [0.4] * 22
        after_iou[0] = 0.8
        after_iou[1] = 0.2
        after_iou[2:8] = [0.55] * 6
        before_color = [0.1] * 22
        strain = [1.0] * 22
        clips = per_clip_metrics(
            plan=plan, before_iou=before_iou, after_iou=after_iou,
            before_color=before_color, after_color=before_color,
            before_strain_p95=strain, after_strain_p95=strain,
        )
        self.assertGreater(clips["idle"]["meanIouImprovement"], IDLE_MEAN_IOU_GAIN)
        self.assertLess(clips["idle"]["worstFrameIouImprovement"], 0.0)
        geometry = {"passed": True, "torsoIntersection": "verified_clear"}
        eligibility = candidate_eligibility(
            geometry=geometry,
            continuity={"passed": True, "idleLoopChecked": True, "transitionChecked": True},
            clips=clips, move_rotation_max=0.0, pinned_rotation_max=0.0,
            optimize_frames=plan["optimizeFrames"], before_iou=before_iou, after_iou=after_iou,
        )
        gate = acceptance(eligibility=eligibility, clips=clips, geometry=geometry)
        self.assertFalse(gate["passed"])
        self.assertFalse(gate["idleOk"])
        self.assertTrue(gate["masterMeanIouImprovementIsNotAcceptance"])

    def test_one_wing_contraction_rejects_without_shared_span(self) -> None:
        regions = np.array(["torso", "torso", "wing_left", "wing_left", "wing_right", "wing_right"], dtype=object)
        before = np.zeros((2, 6, 3), dtype=np.float64)
        before[:, 0] = (0.0, 0.0, 0.0)
        before[:, 1] = (0.4, 0.4, 0.4)
        before[:, 2] = (2.0, 0.0, 0.0)
        before[:, 3] = (3.0, 0.2, 0.0)
        before[:, 4] = (-3.0, 0.0, 0.2)
        before[:, 5] = (-3.4, 0.1, 0.0)
        support = _mesh_support(regions, before[0])
        support["edges"] = np.vstack((support["edges"], np.array([[2, 3]], dtype=np.int64)))
        support["rest_lengths"] = np.linalg.norm(
            support["rest_verts"][support["edges"][:, 0]] - support["rest_verts"][support["edges"][:, 1]], axis=1
        )
        collapsed = before.copy()
        collapsed[:, 2] = (0.05, 0.0, 0.0)
        collapsed[:, 3] = (0.06, 0.0, 0.0)
        gate = _geometry(before, collapsed, support)
        self.assertTrue(gate["collapsedWing"])
        self.assertTrue(gate["worseContraction"])
        self.assertFalse(gate["passed"])
        self.assertLess(gate["perWing"]["wing_left"]["spanRatioMin"], 0.25)
        self.assertGreater(gate["perWing"]["wing_right"]["spanRatioMin"], 0.9)

    def test_triangle_degeneration_rejects(self) -> None:
        regions = np.array(["torso", "torso", "wing_left", "wing_left", "wing_left"], dtype=object)
        before = np.zeros((1, 5, 3), dtype=np.float64)
        before[0, 0] = (0.0, 0.0, 0.0)
        before[0, 1] = (0.4, 0.0, 0.0)
        before[0, 2] = (1.0, 0.0, 0.0)
        before[0, 3] = (1.0, 1.0, 0.0)
        before[0, 4] = (1.4, 0.2, 0.0)
        triangles = np.asarray(((0, 1, 2), (2, 3, 4)), dtype=np.int64)
        edges = np.unique(np.sort(np.concatenate((triangles[:, :2], triangles[:, 1:], triangles[:, [0, 2]])), axis=1), axis=0)
        rest = before[0]
        support = {
            "triangles": triangles,
            "edges": edges,
            "rest_lengths": np.linalg.norm(rest[edges[:, 0]] - rest[edges[:, 1]], axis=1),
            "rest_verts": rest,
            "regions": regions,
        }
        flat = before.copy()
        flat[0, 3] = (1.0, 0.0, 0.0)
        flat[0, 4] = (1.0, 0.0, 0.0)
        gate = _geometry(before, flat, support)
        self.assertTrue(gate["triangleDegenerated"])
        self.assertFalse(gate["passed"])

    def test_moving_torso_is_checked_per_frame(self) -> None:
        regions = np.array(["torso", "torso", "wing_left", "wing_left", "wing_right", "wing_right"], dtype=object)
        before = np.zeros((2, 6, 3), dtype=np.float64)
        before[0, 0] = (0.0, 0.0, 0.0)
        before[0, 1] = (0.3, 0.3, 0.3)
        before[0, 2] = (3.0, 0.0, 0.0)
        before[0, 3] = (3.2, 0.1, 0.0)
        before[0, 4] = (-3.0, 0.0, 0.0)
        before[0, 5] = (-3.3, 0.1, 0.0)
        before[1] = before[0].copy()
        before[1, 0] = (5.0, 0.0, 0.0)
        before[1, 1] = (5.3, 0.3, 0.3)
        after = before.copy()
        after[1, 2] = (5.1, 0.1, 0.1)
        after[1, 3] = (5.15, 0.15, 0.1)
        support = _mesh_support(regions, before[0])
        gate = _geometry(before, after, support)
        self.assertTrue(gate["hidThroughTorso"])
        self.assertEqual(gate["torsoIntersection"], "verified_increased")
        self.assertFalse(gate["passed"])

    def test_geometry_reject_is_not_an_impossibility_proof(self) -> None:
        plan = pilot_frame_plan(_master())
        iou = [0.5] * 22
        clips = per_clip_metrics(
            plan=plan, before_iou=iou, after_iou=iou, before_color=iou, after_color=iou,
            before_strain_p95=iou, after_strain_p95=iou,
        )
        geometry = {"passed": False, "torsoIntersection": "unverified"}
        eligibility = candidate_eligibility(
            geometry=geometry,
            continuity={"passed": True, "idleLoopChecked": True, "transitionChecked": True},
            clips=clips, move_rotation_max=0.0, pinned_rotation_max=0.0,
            optimize_frames=plan["optimizeFrames"], before_iou=iou, after_iou=iou,
        )
        gate = acceptance(eligibility=eligibility, clips=clips, geometry=geometry)
        self.assertEqual(gate["disposition"], "rejected_for_geometry")
        self.assertTrue(gate["doesNotProveMeshCannotFold"])
        self.assertTrue(gate["meshFeasibilityUnresolved"])


class ContinuityAndSearchTests(unittest.TestCase):
    def test_idle_closure_and_transition_pairs_ignore_reel_cuts(self) -> None:
        pairs = playback_continuity_pairs(pilot_frame_plan(_master()))
        self.assertEqual(pairs["idleLoop"], [(0, 7)])
        self.assertEqual(pairs["transition"], [(10, 11), (18, 19)])
        self.assertNotIn((7, 8), pairs["idleLoop"] + pairs["transition"])
        self.assertNotIn((11, 12), pairs["idleLoop"] + pairs["transition"])

    def test_boundary_pop_fails_even_when_anchors_are_unchanged(self) -> None:
        plan = pilot_frame_plan(_master())
        local = np.repeat(np.eye(3)[None, None], 22, axis=0).repeat(3, axis=1)
        after = local.copy()
        after[10, 1] = so3_exp_np(np.array([0.0, 0.9, 0.0]))
        verts = np.zeros((22, 4, 3))
        verts[:, 1] = (1.0, 0.0, 0.0)
        verts[:, 2] = (2.0, 0.0, 0.0)
        after_v = verts.copy()
        after_v[10, 2] = (2.0, 1.5, 0.0)
        mask = np.array([False, True, True, False])
        cont = evaluate_continuity(
            plan=plan, before_local=local, after_local=after,
            before_verts=verts, after_verts=after_v, wing_joints=[1, 2], wing_mask=mask,
        )
        self.assertFalse(cont["passed"])
        self.assertEqual(rotation_change_max(local, after, plan["pinnedFrames"]), 0.0)
        popped = [row for row in cont["pairs"] if row["frames"] == [10, 11]]
        self.assertTrue(popped[0]["popped"])

    def test_idle_closure_detects_loop_jump(self) -> None:
        plan = pilot_frame_plan(_master())
        local = np.repeat(np.eye(3)[None, None], 22, axis=0).repeat(2, axis=1)
        after = local.copy()
        after[7, 1] = so3_exp_np(np.array([0.0, 0.8, 0.0]))
        verts = np.zeros((22, 3, 3))
        verts[:, 1] = (1.0, 0.0, 0.0)
        after_v = verts.copy()
        after_v[7, 1] = (1.0, 1.2, 0.0)
        cont = evaluate_continuity(
            plan=plan, before_local=local, after_local=after,
            before_verts=verts, after_verts=after_v, wing_joints=[1],
            wing_mask=np.array([False, True, False]),
        )
        self.assertFalse(cont["passed"])
        self.assertTrue(any(row["kind"] == "idleLoop" and row["popped"] for row in cont["pairs"]))

    def test_search_slices_are_equal_and_consume_the_whole_budget(self) -> None:
        slices = search_time_slices(120.0, 5)
        self.assertEqual(slices, [24.0, 24.0, 24.0, 24.0, 24.0])
        self.assertEqual(sum(slices), 120.0)
        self.assertEqual(len(set(slices)), 1)

    def test_intermediate_joint_seed_uses_its_own_parent_frame(self) -> None:
        names = ["root", "torso", "prox", "mid", "tip", "other"]
        parents = np.asarray((-1, 0, 1, 2, 3, 1), dtype=np.int64)
        offsets = np.zeros((6, 3), dtype=np.float64)
        offsets[1] = (0.0, 0.4, 0.0)
        offsets[2] = (0.6, 0.0, 0.0)
        offsets[3] = (0.5, 0.1, 0.0)
        offsets[4] = (0.5, 0.0, 0.0)
        offsets[5] = (-0.6, 0.0, 0.0)
        local = np.repeat(np.eye(3)[None], 6, axis=0)
        local[2] = so3_exp_np(np.array([0.8, 0.0, 0.0]))
        regions = {
            "torso": ("root", "torso"),
            "wing_left": ("prox", "mid", "tip"),
            "wing_right": ("other",),
        }
        omega = fold_toward_torso_deltas(
            local=local[None], offsets=offsets, parents=parents,
            root_world=np.zeros((1, 3)), names=names, region_joints=regions,
            free_frames=[0], amount=0.4, mid_amount=0.2,
        )
        from mesh_preview import fk_world_matrices

        world = fk_world_matrices(local_rotation=local, local_translation=offsets, parents=parents, root_world=np.zeros(3))
        extra_prox = so3_exp_np(omega[0, 0] / 0.4)
        extra_mid = reframe_parent_rotation(extra_prox, world[1, :3, :3], world[2, :3, :3])
        from linked_master_pose_refine import _log_so3

        expected = _log_so3(extra_mid) * 0.2
        np.testing.assert_allclose(omega[0, 1], expected, atol=1e-6)
        sample = reframe_parent_rotation(
            so3_exp_np(np.array([0.0, 0.0, 0.4])), np.eye(3), so3_exp_np(np.array([0.5, 0.0, 0.0]))
        )
        self.assertGreater(float(np.linalg.norm(sample - so3_exp_np(np.array([0.0, 0.0, 0.4])))), 1e-3)


class PreviewTests(unittest.TestCase):
    def test_independently_scaled_sprites_are_rejected(self) -> None:
        shared = np.zeros((2, 8, 8, 3), dtype=np.float32)
        letterboxed = np.zeros((2, 16, 16, 3), dtype=np.float32)
        with self.assertRaisesRegex(ValueError, "optimization target canvas"):
            source_matches_optimization_canvas(letterboxed, shared)

    def test_close_crop_is_identical_across_panels(self) -> None:
        a = np.zeros((20, 20, 3), dtype=np.float32)
        b = np.zeros((20, 20, 3), dtype=np.float32)
        c = np.zeros((20, 20, 3), dtype=np.float32)
        a[4:8, 4:8] = 1.0
        b[5:9, 5:9] = 1.0
        c[6:10, 6:10] = 1.0
        box = identical_panel_close_box(a, b, c)
        from linked_master_pose_refine import crop_panels_identically

        cropped = crop_panels_identically([a, b, c], box)
        self.assertEqual(cropped[0].shape, cropped[1].shape)
        self.assertEqual(cropped[1].shape, cropped[2].shape)


class ProvenanceAndExportTests(unittest.TestCase):
    def test_rotation_change_max_is_zero_on_identical_motion(self) -> None:
        local = np.repeat(np.eye(3)[None, None], 4, axis=0).repeat(2, axis=1)
        self.assertEqual(rotation_change_max(local, local, [0, 1, 2, 3]), 0.0)
        changed = local.copy()
        changed[1, 1] = so3_exp_np(np.array([0.0, 0.0, 0.25]))
        self.assertGreater(rotation_change_max(local, changed, [1], joints=[1]), 0.2)
        self.assertEqual(rotation_change_max(local, changed, [0], joints=[1]), 0.0)
        crooked = local.astype(np.float32)
        crooked[0, 0] = np.array([[0.999, 0.03, 0.0], [-0.03, 0.999, 0.0], [0.0, 0.0, 1.0]], dtype=np.float32)
        self.assertEqual(rotation_change_max(crooked, crooked.copy(), [0, 1], joints=[0]), 0.0)

    def test_glb_export_preserves_frame_count_timing_and_readback(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="pose_refine_export_")
        path = Path(temporary.name) / "pilot.glb"
        names = ["Root"] + [f"Joint{i}" for i in range(1, 8)]
        parents = np.asarray((-1, 0, 1, 2, 3, 4, 5, 6), dtype=np.int64)
        rest_rot = np.repeat(np.eye(3)[None], 8, axis=0)
        rest_trans = np.asarray([(0.0, 0.0, 0.0)] + [(0.0, 0.25, 0.0)] * 7)
        bind = gltf_world_matrices(local_rotation=rest_rot, local_translation=rest_trans, parents=parents)
        vertices = np.asarray(((0.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.4, 1.0, 0.0)))
        weights = np.zeros((3, 8))
        weights[:, 0] = 1.0
        weights[1:, 1] = 1.0
        weights[1:, 0] = 0.0
        rotations = np.repeat(rest_rot[None], 3, axis=0)
        rotations[1, 1] = so3_exp_np(np.array([0.0, 0.0, 0.3]))
        rotations[2, 1] = so3_exp_np(np.array([0.0, 0.0, -0.2]))
        times = np.asarray((0.0, 1.0 / 12.0, 2.0 / 12.0), dtype=np.float32)
        from donor_eagle import skin_dense

        expected = []
        for local in rotations:
            worlds = gltf_world_matrices(local_rotation=local, local_translation=rest_trans, parents=parents)
            expected.append(skin_dense(vertices, weights, worlds, np.linalg.inv(bind)))
        write_skinned_glb(
            path, names=names, parents=parents, rest_local_rotation=rest_rot,
            rest_local_translation=rest_trans, inverse_bind=np.linalg.inv(bind),
            vertices=vertices, triangles=np.asarray(((0, 1, 2),), dtype=np.int64),
            uvs=np.asarray(((0.0, 0.0), (0.5, 1.0), (1.0, 1.0))),
            albedo=np.full((2, 2, 4), 255, dtype=np.uint8), weights=weights,
            animation={"times": times, "rotations": matrices_to_xyzw(rotations)},
        )
        parity = verify_calibrated_export(
            path, expected_meshes=np.stack(expected), expected_times=times, idle_frame=None, allow_root_motion=True
        )
        self.assertTrue(parity["ok"])
        self.assertEqual(len(times), 3)
        temporary.cleanup()

    def test_non_roc_unit_is_refused(self) -> None:
        from run_roc_wing_pose_refine import load_inputs

        with self.assertRaisesRegex(ValueError, "h3_roc"):
            load_inputs(Path("."), "h3_crusader")

    def test_input_hash_check_refuses_capture_drift(self) -> None:
        from pin import sha256_file
        from run_roc_wing_pose_refine import load_inputs

        linked = Path(__file__).resolve().parents[2] / "artifacts/homm3_mocap_v2/roc_linked_master_v2"
        report_path = linked / "report.json"
        if not report_path.is_file():
            self.skipTest("linked-master v2 artifact is not on disk")
        report = json.loads(report_path.read_text(encoding="utf-8"))
        capture = Path(report["capture"])
        self.assertEqual(sha256_file(capture), report["captureSha256"])
        mutated = dict(report)
        mutated["captureSha256"] = "0" * 64
        temporary = tempfile.TemporaryDirectory(prefix="pose_refine_hash_")
        fake = Path(temporary.name)
        (fake / "master_sequence").mkdir()
        (fake / "skin_fit").mkdir()
        (fake / "report.json").write_text(json.dumps(mutated), encoding="utf-8")
        (fake / "master_sequence" / "master_sequence.json").write_text(
            (linked / "master_sequence" / "master_sequence.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        (fake / "skin_fit" / "camera.json").write_bytes((linked / "skin_fit" / "camera.json").read_bytes())
        (fake / "skin_fit" / "candidate_weights.npz").write_bytes((linked / "skin_fit" / "candidate_weights.npz").read_bytes())
        with self.assertRaisesRegex(ValueError, "capture hash drifted"):
            load_inputs(fake, "h3_roc")
        temporary.cleanup()


class GateAlignedObjectiveTests(unittest.TestCase):
    def test_imperfect_capture_matrices_match_trace_gate(self):
        import torch
        from linked_master_pose_refine import continuity_hinge_losses, CONTINUITY_GEODESIC_SLACK

        plan = {"clips": {"idle": {"frames": [0, 1]},
                          "move_start": {"frames": [2, 3]},
                          "move_end": {"frames": [4, 5]}}, "pinnedFrames": [3, 4]}
        baseline = torch.eye(3, dtype=torch.float32).repeat(6, 1, 1, 1)
        vertices = torch.zeros((6, 2, 3), dtype=torch.float32, requires_grad=True)
        for scale in (0.994, 1.0002):
            local = baseline.clone()
            local[1, 0] *= scale
            local.requires_grad_()
            result = continuity_hinge_losses(
                plan=plan, before_local=baseline, after_local=local,
                before_verts=vertices.detach(), after_verts=vertices,
                wing_joints=[0], wing_mask=np.array([True, True]),
            )
            gate = evaluate_continuity(
                plan=plan, before_local=baseline.numpy(), after_local=local.detach().numpy(),
                before_verts=vertices.detach().numpy(), after_verts=vertices.detach().numpy(),
                wing_joints=[0], wing_mask=np.array([True, True]),
            )
            expected = sum(max(row["afterGeodesicMax"] - row["beforeGeodesicMax"]
                               - CONTINUITY_GEODESIC_SLACK, 0.0) ** 2
                           / CONTINUITY_GEODESIC_SLACK ** 2 for row in gate["pairs"]) / len(gate["pairs"])
            self.assertAlmostEqual(float(result["angular"].detach()), expected, places=12)
            self.assertEqual(float(result["angular"].detach()) == 0, gate["passed"])
            (result["angular"] + result["surface"]).backward()
            self.assertTrue(bool(torch.isfinite(local.grad).all()))
            self.assertTrue(bool(torch.isfinite(vertices.grad).all()))

    def test_continuity_matches_gate_and_has_finite_gradients(self):
        import torch
        from linked_master_pose_refine import continuity_hinge_losses

        plan = {"clips": {"idle": {"frames": [0, 1]},
                          "move_start": {"frames": [2, 3]},
                          "move_end": {"frames": [4, 5]}}, "pinnedFrames": [3, 4]}
        before_local = torch.eye(3, dtype=torch.float64).repeat(6, 1, 1, 1)
        before_verts = torch.zeros((6, 2, 3), dtype=torch.float64)
        for frame in (1, 2, 5):
            for angle, travel in ((0.0, 0.0), (0.1, 0.01), (0.3, 0.06)):
                local = before_local.clone()
                local[frame, 0] = torch.as_tensor(so3_exp_np(np.array([0., 0., angle])))
                local.requires_grad_()
                verts = before_verts.clone()
                verts[frame, 0, 0] = travel
                verts.requires_grad_()
                losses = continuity_hinge_losses(
                    plan=plan, before_local=before_local, after_local=local,
                    before_verts=before_verts, after_verts=verts,
                    wing_joints=[0], wing_mask=np.array([True, True]),
                )
                gate = evaluate_continuity(
                    plan=plan, before_local=before_local.numpy(), after_local=local.detach().numpy(),
                    before_verts=before_verts.numpy(), after_verts=verts.detach().numpy(),
                    wing_joints=[0], wing_mask=np.array([True, True]),
                )
                loss = losses["angular"] + losses["surface"]
                self.assertEqual(float(loss.detach()) == 0, gate["passed"])
                loss.backward()
                self.assertTrue(bool(torch.isfinite(local.grad).all()))
                self.assertTrue(bool(torch.isfinite(verts.grad).all()))
                if angle == 0.3:
                    self.assertAlmostEqual(float(losses["angular"].detach()), 0.75)
                    self.assertAlmostEqual(float(losses["surface"].detach()), 4.0 / 3.0)

    def test_iou_hinge_cannot_hide_regression_with_other_frame_gain(self):
        import torch
        from linked_master_pose_refine import per_frame_iou_regression_hinge, per_frame_non_regression

        before = torch.tensor([0.5, 0.5, 0.5], dtype=torch.float64, requires_grad=True)
        after = torch.tensor([0.9, 0.49, 0.1], dtype=torch.float64, requires_grad=True)
        loss = per_frame_iou_regression_hinge(before, after, [0, 1])
        self.assertGreater(float(loss.detach()), 0)
        self.assertAlmostEqual(float(loss.detach()), (0.01 - 1e-6) / 2.0)
        self.assertFalse(per_frame_non_regression(before.tolist(), after.tolist(), [0, 1])["passed"])
        loss.backward()
        self.assertIsNone(before.grad)
        self.assertEqual(float(after.grad[0]), 0)
        self.assertEqual(float(after.grad[1]), -0.5)
        self.assertEqual(float(after.grad[2]), 0)
        same = before.detach().clone().requires_grad_()
        zero = per_frame_iou_regression_hinge(before, same, [0, 1])
        self.assertEqual(float(zero.detach()), 0)
        zero.backward()
        self.assertTrue(bool(torch.isfinite(same.grad).all()))
        near = torch.tensor([0.5, 0.5 - 1.01e-6, 0.5], dtype=torch.float64, requires_grad=True)
        near_loss = per_frame_iou_regression_hinge(before, near, [0, 1])
        self.assertGreater(float(near_loss.detach()), 0)
        near_loss.backward()
        self.assertEqual(float(near.grad[1]), -0.5)


if __name__ == "__main__":
    unittest.main()
