"""CPU tests for sprite feasibility classification, gates, and GLB surgery."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from gpu_cascade_delivery import require_pose_units_degrees
from sprite_anatomy import (
    load_unit_anatomy_catalog,
    anatomy_ventral_bind_axis,
    anatomy_attitude_bones,
    anatomy_central_joint_axes,
    anatomy_central_search_groups,
)
from sprite_body_surgery import (
    _accessor_array,
    _write_accessor,
    bind_like_poses,
    clone_pose_map,
    first_skinned_primitive,
    identity_joint_keep_root_poses,
    insert_child_bone,
    load_glb,
    node_index_by_name,
    normalize_skin_weights,
    rebind_vertices_to_joint,
    rest_sculpt_positions,
    rotate_bone_deg,
    rotate_bone_deg_within_limit,
    rotate_bone_deg_shared_within_limit,
    rotate_bilateral_pair_deg_shared,
    copy_joints_keep_dest_root,
    seed_frame_from_inertial,
    seed_frame_pipeline_relative,
    rotate_root_deg,
    set_root_rotation_deg,
    save_glb,
    scale_bone_rest_translation,
    validate_skinned_glb,
    write_after_poses,
    write_camera_fit_from_candidate,
    write_minimal_skinned_glb,
)
from sprite_pose_feasibility import (
    CLASS_BODY_INFEASIBLE_LENGTH,
    CLASS_BODY_INFEASIBLE_REST,
    CLASS_CAMERA_MISMATCH,
    CLASS_CAMERA_MISMATCH_UNRESOLVED,
    CLASS_CAMERA_OK,
    CLASS_MISSING_GEOMETRY,
    CLASS_MISSING_JOINT,
    CLASS_POSE_SEARCH_DEBT,
    CLASS_WRONG_OWNER,
    EPSILON_LEFTOVER,
    accept_surgery,
    agreed_rebind_vertices,
    aggregate_vertex_owners,
    argmax_round,
    assert_write_path,
    assign_leftover_pixels,
    classify_camera_from_init,
    classify_occupancy_body,
    compare_gif_panel_size,
    invert_lbs_image_plane,
    leftover_flip_is_blendshape,
    occupancy_assigned_unique_bones,
    occupancy_rest_frame_index,
    occupancy_rest_modes,
    occupancy_vertex_deltas_px,
    unique_region_bones_from_pixels,
    unique_region_centroid_shrink_deltas,
    extra_on_vertex_mask,
    apply_rest_space_deltas,
    OccupancyFractions,
    accept_occupancy_rest,
    next_body_class,
    next_pending_class,
    occupancy_fractions,
    pick_highest_facing_profile,
    skip_fraction_reject,
    work_tree_root,
    move_frame_positions,
    flight_attitude_needed,
    leftover_primary_better,
    leftover_extend_scale,
    leftover_extend_target_name,
    flyer_camera_trap_search_bones,
    flyer_visual_body_chain,
    flyer_broad_stroke_search_bones,
    flyer_broad_stroke_ok,
    flyer_phase_needs_right_seed,
    flyer_attitude_occupancy_allows,
    closer_aspect,
    FLIGHT_PRIOR,
    flyer_attitude_bones,
    flyer_spine_chain_bones,
    camera_axis_spans,
    side_view_ratio,
    horizontal_ratio,
    spine_camera_align,
    spine_is_side_view_flight,
    spine_level_score,
    flight_phase_sprite_axis,
    flight_phase_groups,
    flight_phase_representative_frames,
    frame_rest_source,
    bake_lbs_pose_to_rest,
    rotation_aligning_bases,
    rotation_mapping_vector,
    rotate_points_about_pivot,
    assign_opposite_wing_spans,
    symmetric_limb_destinations,
    symmetric_raised_wing_destinations,
    spread_labeled_wing_vertices,
    tpose_stretched_bridge_faces,
    ANATOMY_FIT_STAGES,
    ARCHITECTURE_ACCEPT_NAMES,
    SYMMETRIC_BONE_STEPS_DEG,
    TEMPORAL_COARSE_MAGNITUDES_DEG,
    TEMPORAL_FINE_STEPS_DEG,
    SUBSTANTIAL_LEFTOVER_DROP,
    unique_joint_pose_count,
    leftover_symmetric_insert_parents,
    insert_child_bone_name,
    distal_owner_vertex_indices,
    anatomy_joints_xy,
    ASYMMETRIC_REST_LENGTH_SCALES,
    next_anatomy_fit_stage,
    symmetric_bone_fit_pairs,
    asymmetric_distal_bones,
    symmetric_bone_trial_better,
    substantial_occupancy_better,
    occupancy_collision_unacceptable,
    temporal_coarse_combos,
    combo_beyond_collision_bound,
    combo_pruned_by_collision_bounds,
    leftover_trial_illegal,
    predict_channel_inertial,
    clip_wraps_temporally,
    pose_bidirectional_velocity_rms,
    wrapped_deg_delta,
    flyer_frame_is_perch_trap,
    flyer_frame_is_flat_trap,
    flyer_frame_is_pitch_trap,
    flyer_frame_is_camera_trap,
    FLIGHT_TAKEOFF_AXIS_XY,
    FLIGHT_CRUISE_AXIS_XY,
    FLIGHT_LANDING_AXIS_XY,
    FLIGHT_REST_RIGHT_MIN,
    FLIGHT_SPINE_STEPS_DEG,
    PIPELINE_REFINE_SPINE_STEPS_DEG,
    mask_principal_axis_xy,
    mask_body_core_axis_xy,
    spine_sprite_axis_score,
    spine_is_image_plane,
    belly_camera_align,
    belly_is_down,
    remove_axis_component,
    side_view_flight_better,
    orbit_camera_vectors,
    orbit_projection,
    vision_check_frame_positions,
)

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")


class OccupancyAndGateTests(unittest.TestCase):
    def test_fractions_are_sprite_normalized(self) -> None:
        sprite = np.zeros((4, 4), dtype=bool)
        sprite[0:2, 0:2] = True
        leftover = np.zeros((4, 4), dtype=bool)
        leftover[0, 0] = True
        extra = np.zeros((4, 4), dtype=bool)
        extra[3, 3] = True
        row = occupancy_fractions(leftover, extra, sprite)
        self.assertEqual(row.sprite_pixels, 4)
        self.assertAlmostEqual(row.leftover, 0.25)
        self.assertAlmostEqual(row.extra, 0.25)

    def test_empty_sprite_fails_closed(self) -> None:
        empty = np.zeros((2, 2), dtype=bool)
        with self.assertRaises(ValueError):
            occupancy_fractions(empty, empty, empty)

    def test_compare_gif_panel_is_integer_nearest_upscale(self) -> None:
        small_w, small_h, small_scale = compare_gif_panel_size(192, 172)
        self.assertEqual(small_scale, 7)
        self.assertEqual((small_w, small_h), (1344, 1204))
        mid_w, mid_h, mid_scale = compare_gif_panel_size(288, 258)
        self.assertEqual(mid_scale, 5)
        self.assertEqual((mid_w, mid_h), (1440, 1290))
        native_w, native_h, native_scale = compare_gif_panel_size(1200, 800)
        self.assertEqual(native_scale, 1)
        self.assertEqual((native_w, native_h), (1200, 800))

    def test_compare_gif_panel_follows_occupancy_raster_not_hires_sprite(self) -> None:
        from run_sprite_feasibility_surgery import write_compare_gif

        dest_root = ROOT / "artifacts" / "sprite_feasibility" / "_gif_scale_probe"
        sprite_dir = dest_root / "sprite"
        mesh_dir = dest_root / "mesh"
        sprite_dir.mkdir(parents=True, exist_ok=True)
        mesh_dir.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (200, 220), (20, 180, 40)).save(sprite_dir / "00.png")
        Image.new("RGB", (8, 8), (30, 30, 40)).save(mesh_dir / "00.png")
        gif = write_compare_gif(
            sprite_paths=(sprite_dir / "00.png",),
            panel_a=mesh_dir,
            panel_b=mesh_dir,
            frames=(0,),
            dest=dest_root / "compare.gif",
            labels=("sprite", "before", "after"),
            caption="scale probe",
        )
        with Image.open(gif) as frame:
            panel_w, panel_h, scale = compare_gif_panel_size(8, 8)
            self.assertEqual(scale, 8)
            self.assertEqual(frame.size[0], panel_w * 3)
            self.assertGreaterEqual(frame.size[1], panel_h)
        gif.unlink(missing_ok=True)

    def test_accept_requires_leftover_and_caps_extra_strain(self) -> None:
        sprite = np.ones((10, 10), dtype=bool)
        before = occupancy_fractions(np.ones((10, 10), dtype=bool), np.zeros((10, 10), dtype=bool), sprite)
        after_ok = occupancy_fractions(
            np.zeros((10, 10), dtype=bool),
            np.zeros((10, 10), dtype=bool),
            sprite,
        )
        gate = accept_surgery(before, after_ok, strain_before=0.1, strain_after=0.1)
        self.assertTrue(gate["accepted"])
        after_extra = occupancy_fractions(
            np.zeros((10, 10), dtype=bool),
            np.ones((10, 10), dtype=bool),
            sprite,
        )
        self.assertFalse(
            accept_surgery(before, after_extra, strain_before=0.1, strain_after=0.1)["accepted"]
        )
        self.assertFalse(
            accept_surgery(before, after_ok, strain_before=0.1, strain_after=0.5)["accepted"]
        )
        self.assertGreaterEqual(EPSILON_LEFTOVER, 0.01)

    def test_argmax_ignores_rejected_rounds(self) -> None:
        original = {"roundId": "round_00", "accepted": True, "leftover": 0.20, "extra": 0.05, "strain": 0.02}
        rejected = {"roundId": "round_01", "accepted": False, "leftover": 0.01, "extra": 0.0, "strain": 0.0}
        kept = {"roundId": "round_02", "accepted": True, "leftover": 0.10, "extra": 0.04, "strain": 0.02}
        chosen = argmax_round([original, rejected, kept])
        self.assertEqual(chosen["roundId"], "round_02")

    def test_argmax_uses_epsilon_as_tie_band(self) -> None:
        original = {"roundId": "round_00", "accepted": True, "leftover": 0.10, "extra": 0.08, "strain": 0.02}
        tied = {"roundId": "round_01", "accepted": True, "leftover": 0.11, "extra": 0.01, "strain": 0.02}
        chosen = argmax_round([original, tied])
        self.assertEqual(chosen["roundId"], "round_01")


class LeftoverAssignTests(unittest.TestCase):
    def test_pixels_beyond_cap_stay_unassigned(self) -> None:
        leftover = np.zeros((4, 4), dtype=bool)
        leftover[0, 0] = True
        leftover[3, 3] = True
        unique_a = np.full((4, 4), 100.0)
        unique_a[0, 0] = 2.0
        unique_b = np.full((4, 4), 100.0)
        unique_b[3, 3] = 50.0
        report = assign_leftover_pixels(leftover, {"Bone_A": unique_a, "Bone_B": unique_b}, max_assign_px=8.0)
        self.assertEqual(report["counts"]["Bone_A"], 1)
        self.assertEqual(report["unassigned"], 1)

    def test_owner_agreement_and_disagreement(self) -> None:
        agreed = aggregate_vertex_owners(
            [{0: "Bone_A"}, {0: "Bone_A"}, {0: "Bone_A"}, {0: "Bone_B"}],
            agree_frac=0.75,
        )
        self.assertEqual(agreed["agreed"][0], "Bone_A")
        split = aggregate_vertex_owners(
            [{1: "Bone_A"}, {1: "Bone_B"}, {1: "Bone_A"}, {1: "Bone_B"}],
            agree_frac=0.75,
        )
        self.assertIn(1, split["disagreed"])

    def test_agreed_rebind_keeps_going_when_some_verts_disagree(self) -> None:
        vote = {
            "agreed": {0: "Bone_A", 2: "Bone_C"},
            "disagreed": (1,),
        }
        verts, reason = agreed_rebind_vertices(vote, "Bone_C")
        self.assertIsNone(reason)
        self.assertEqual(verts, [0])

    def test_leftover_flip_is_blendshape_only_on_still_idle(self) -> None:
        self.assertTrue(leftover_flip_is_blendshape(clip_name="idle", leftover_far=False))
        self.assertFalse(leftover_flip_is_blendshape(clip_name="idle_start_move_end", leftover_far=True))
        self.assertFalse(leftover_flip_is_blendshape(clip_name="idle", leftover_far=True))

    def test_occupancy_vertex_moves_toward_leftover_and_extra_toward_sprite(self) -> None:
        leftover = np.zeros((4, 8), dtype=bool)
        leftover[1, 7] = True
        extra = np.zeros((4, 8), dtype=bool)
        extra[2, 1] = True
        sprite = np.zeros((4, 8), dtype=bool)
        sprite[1, 7] = True
        sprite[2, 4] = True
        xs = np.asarray((5.0, 1.0))
        ys = np.asarray((1.0, 2.0))
        deltas, affected = occupancy_vertex_deltas_px(xs, ys, leftover, extra, sprite, max_assign_px=8.0)
        self.assertTrue(bool(affected[0]))
        self.assertGreater(float(deltas[0, 0]), 0.0)
        self.assertTrue(bool(affected[1]))
        self.assertGreater(float(deltas[1, 0]), 0.0)

    def test_occupancy_fill_skips_far_and_extra_vertices(self) -> None:
        leftover = np.zeros((4, 24), dtype=bool)
        leftover[1, 23] = True
        extra = np.zeros((4, 24), dtype=bool)
        extra[1, 4] = True
        sprite = np.zeros((4, 24), dtype=bool)
        sprite[1, 23] = True
        xs = np.asarray((4.0, 4.0))
        ys = np.asarray((1.0, 2.0))
        deltas, affected = occupancy_vertex_deltas_px(
            xs,
            ys,
            leftover,
            extra,
            sprite,
            max_assign_px=8.0,
            fill_leftover=True,
            shrink_extra=False,
        )
        self.assertFalse(bool(affected[0]))
        self.assertFalse(bool(affected[1]))
        self.assertTrue(np.allclose(deltas, 0.0))

    def test_occupancy_fill_only_leftover_facing_rim(self) -> None:
        leftover = np.zeros((4, 8), dtype=bool)
        leftover[1, 7] = True
        extra = np.zeros((4, 8), dtype=bool)
        extra[1, 0] = True
        sprite = np.zeros((4, 8), dtype=bool)
        sprite[1, 7] = True
        sprite[1, 3] = True
        xs = np.asarray((2.0,))
        ys = np.asarray((1.0,))
        _deltas, affected = occupancy_vertex_deltas_px(
            xs,
            ys,
            leftover,
            extra,
            sprite,
            max_assign_px=8.0,
            fill_leftover=True,
            shrink_extra=False,
        )
        self.assertFalse(bool(affected[0]))

    def test_occupancy_rest_modes_dominant_side_only(self) -> None:
        fill, shrink = occupancy_rest_modes(0.097, 0.062)
        self.assertTrue(fill)
        self.assertFalse(shrink)
        fill_roc, shrink_roc = occupancy_rest_modes(0.113, 0.273)
        self.assertFalse(fill_roc)
        self.assertTrue(shrink_roc)

    def test_occupancy_rest_modes_one_side_when_only_one_over(self) -> None:
        fill, shrink = occupancy_rest_modes(0.16, 0.03)
        self.assertTrue(fill)
        self.assertFalse(shrink)
        fill_extra, shrink_extra = occupancy_rest_modes(0.03, 0.27)
        self.assertFalse(fill_extra)
        self.assertTrue(shrink_extra)

    def test_occupancy_rest_frame_picks_extra_heaviest_when_shrinking(self) -> None:
        leftover = [np.zeros((2, 2), dtype=bool) for _ in range(3)]
        leftover[0][0, 0] = True
        leftover[0][0, 1] = True
        extra = [np.zeros((2, 2), dtype=bool) for _ in range(3)]
        extra[2][0, 0] = True
        extra[2][0, 1] = True
        extra[2][1, 0] = True
        extra[1][0, 0] = True
        self.assertEqual(
            occupancy_rest_frame_index(leftover, extra, fill_leftover=False, shrink_extra=True),
            2,
        )
        self.assertEqual(
            occupancy_rest_frame_index(leftover, extra, fill_leftover=True, shrink_extra=False),
            0,
        )
        self.assertEqual(
            occupancy_rest_frame_index(
                leftover, extra, fill_leftover=True, shrink_extra=False, candidates=(1, 2)
            ),
            1,
        )

    def test_leftover_extend_scale_is_parent_relative(self) -> None:
        parent = np.array([10.0, 10.0])
        joint = np.array([20.0, 10.0])
        past_tip = leftover_extend_scale(joint, parent, np.array([[40.0, 10.0]]))
        on_bone = leftover_extend_scale(joint, parent, np.array([[18.0, 10.0]]))
        empty = leftover_extend_scale(joint, parent, np.zeros((0, 2)))
        self.assertAlmostEqual(past_tip, 1.6)
        self.assertAlmostEqual(on_bone, 1.0)
        self.assertAlmostEqual(empty, 1.15)

    def test_leftover_extend_prefers_insert_over_body(self) -> None:
        self.assertEqual(
            leftover_extend_target_name(("Bone_004", "Bone_018", "Bone_FeasibilityInsert")),
            "Bone_FeasibilityInsert",
        )
        self.assertEqual(
            leftover_extend_target_name(("Bone_001", "Bone_018")),
            "Bone_018",
        )
        self.assertIsNone(leftover_extend_target_name(("Bone_000", "Bone_001")))

    def test_camera_trap_search_bones_include_root(self) -> None:
        self.assertEqual(
            flyer_camera_trap_search_bones(("Bone_001", "Bone_003"), ("Bone_000", "Bone_001", "Bone_003")),
            ["Bone_000", "Bone_001", "Bone_003"],
        )
        self.assertEqual(
            flyer_camera_trap_search_bones(("Bone_001",), ("Bone_001",)),
            ["Bone_001"],
        )

    def test_camera_trap_occupancy_allows_leftover_growth(self) -> None:
        before = OccupancyFractions(
            leftover=0.24, extra=0.10, sprite_pixels=100, leftover_pixels=24, extra_pixels=10
        )
        profile = OccupancyFractions(
            leftover=0.32, extra=0.10, sprite_pixels=100, leftover_pixels=32, extra_pixels=10
        )
        extra_up = OccupancyFractions(
            leftover=0.20, extra=0.14, sprite_pixels=100, leftover_pixels=20, extra_pixels=14
        )
        self.assertTrue(
            flyer_attitude_occupancy_allows(before, profile, camera_trap=True, trap=True)
        )
        self.assertFalse(
            flyer_attitude_occupancy_allows(before, extra_up, camera_trap=True, trap=True)
        )
        self.assertFalse(
            flyer_attitude_occupancy_allows(before, profile, camera_trap=False, trap=True)
        )

    def test_occupancy_extra_facing_rim_moves_away_from_extra(self) -> None:
        leftover = np.zeros((4, 24), dtype=bool)
        leftover[1, 20] = True
        extra = np.zeros((4, 24), dtype=bool)
        extra[1, 1] = True
        sprite = np.zeros((4, 24), dtype=bool)
        sprite[1, 4] = True
        sprite[1, 20] = True
        xs = np.asarray((2.5,))
        ys = np.asarray((1.0,))
        deltas, affected = occupancy_vertex_deltas_px(
            xs,
            ys,
            leftover,
            extra,
            sprite,
            max_assign_px=8.0,
            fill_leftover=False,
            shrink_extra=True,
        )
        self.assertTrue(bool(affected[0]))
        self.assertGreater(float(deltas[0, 0]), 0.0)

    def test_occupancy_extra_facing_skips_leftover_closer_verts(self) -> None:
        leftover = np.zeros((4, 8), dtype=bool)
        leftover[1, 6] = True
        extra = np.zeros((4, 8), dtype=bool)
        extra[1, 0] = True
        sprite = np.zeros((4, 8), dtype=bool)
        sprite[1, 6] = True
        sprite[1, 3] = True
        xs = np.asarray((5.0,))
        ys = np.asarray((1.0,))
        deltas, affected = occupancy_vertex_deltas_px(
            xs,
            ys,
            leftover,
            extra,
            sprite,
            max_assign_px=8.0,
            fill_leftover=False,
            shrink_extra=True,
        )
        self.assertFalse(bool(affected[0]))
        self.assertTrue(np.allclose(deltas, 0.0))

    def test_occupancy_unique_rims_fill_and_shrink_different_verts(self) -> None:
        leftover = np.zeros((4, 8), dtype=bool)
        leftover[1, 7] = True
        extra = np.zeros((4, 8), dtype=bool)
        extra[1, 0] = True
        extra[2, 1] = True
        sprite = np.zeros((4, 8), dtype=bool)
        sprite[1, 7] = True
        sprite[1, 3] = True
        sprite[2, 4] = True
        xs = np.asarray((5.0, 2.0, 1.0))
        ys = np.asarray((1.0, 1.0, 2.0))
        deltas, affected = occupancy_vertex_deltas_px(
            xs,
            ys,
            leftover,
            extra,
            sprite,
            max_assign_px=8.0,
            fill_leftover=True,
            shrink_extra=True,
        )
        self.assertTrue(bool(affected[0]))
        self.assertGreater(float(deltas[0, 0]), 0.0)
        self.assertTrue(bool(affected[1]))
        self.assertGreater(float(deltas[1, 0]), 0.0)
        self.assertTrue(bool(affected[2]))
        self.assertGreater(float(deltas[2, 0]), 0.0)

    def test_occupancy_unique_region_skips_other_bone_verts(self) -> None:
        leftover = np.zeros((4, 8), dtype=bool)
        leftover[1, 7] = True
        extra = np.zeros((4, 8), dtype=bool)
        extra[1, 0] = True
        sprite = np.zeros((4, 8), dtype=bool)
        sprite[1, 7] = True
        sprite[1, 3] = True
        xs = np.asarray((5.0, 5.0))
        ys = np.asarray((1.0, 1.0))
        owner_allow = np.asarray((True, False))
        deltas, affected = occupancy_vertex_deltas_px(
            xs,
            ys,
            leftover,
            extra,
            sprite,
            max_assign_px=8.0,
            fill_leftover=True,
            shrink_extra=False,
            owner_allow=owner_allow,
        )
        self.assertTrue(bool(affected[0]))
        self.assertGreater(float(deltas[0, 0]), 0.0)
        self.assertFalse(bool(affected[1]))
        self.assertTrue(np.allclose(deltas[1], 0.0))

    def test_unique_region_bones_keep_peak_and_floor(self) -> None:
        leftover_xs = np.asarray((0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 10.0, 10.0))
        leftover_ys = np.zeros(10, dtype=np.float64)
        joints = {"Bone_A": (0.0, 0.0), "Bone_B": (10.0, 0.0), "Bone_C": (50.0, 0.0)}
        bones = unique_region_bones_from_pixels(leftover_xs, leftover_ys, joints, min_frac=0.10)
        self.assertIn("Bone_A", bones)
        self.assertIn("Bone_B", bones)
        self.assertNotIn("Bone_C", bones)
        self.assertEqual(bones[0], "Bone_A")

    def test_occupancy_assigned_unique_bones_keep_unique_owner(self) -> None:
        bones = occupancy_assigned_unique_bones(
            {"Bone_009": 846, "Bone_016": 1200, "Bone_001": 5},
            "Bone_016",
            min_frac=0.10,
        )
        self.assertIn("Bone_016", bones)
        self.assertIn("Bone_009", bones)
        self.assertNotIn("Bone_001", bones)

    def test_unique_region_centroid_shrink_moves_owned_verts_inward(self) -> None:
        rest = np.asarray(((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (10.0, 0.0, 0.0)), dtype=np.float64)
        deltas, affected = unique_region_centroid_shrink_deltas(
            rest,
            ("Bone_A", "Bone_A", "Bone_B"),
            ("Bone_A",),
            frac=0.5,
        )
        self.assertTrue(bool(affected[0]))
        self.assertTrue(bool(affected[1]))
        self.assertFalse(bool(affected[2]))
        self.assertGreater(float(deltas[0, 0]), 0.0)
        self.assertLess(float(deltas[1, 0]), 0.0)
        self.assertTrue(np.allclose(deltas[2], 0.0))

    def test_unique_region_vert_allow_skips_interior(self) -> None:
        rest = np.asarray(((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (10.0, 0.0, 0.0)), dtype=np.float64)
        deltas, affected = unique_region_centroid_shrink_deltas(
            rest,
            ("Bone_A", "Bone_A", "Bone_B"),
            ("Bone_A",),
            frac=0.5,
            vert_allow=np.asarray((True, False, True)),
        )
        self.assertTrue(bool(affected[0]))
        self.assertFalse(bool(affected[1]))
        self.assertFalse(bool(affected[2]))

    def test_extra_on_vertex_mask_is_projection_only(self) -> None:
        extra = np.zeros((4, 8), dtype=bool)
        extra[1, 6] = True
        mask = extra_on_vertex_mask(np.asarray((6.0, 1.0)), np.asarray((1.0, 1.0)), extra)
        self.assertTrue(bool(mask[0]))
        self.assertFalse(bool(mask[1]))

    def test_move_frame_positions_skip_idle_bands(self) -> None:
        self.assertEqual(move_frame_positions(30, 8, 8), list(range(8, 22)))
        self.assertEqual(move_frame_positions(8, 8, 0), [])

    def test_flight_attitude_needed_for_landscape_move(self) -> None:
        idle = np.zeros((10, 6), dtype=bool)
        idle[1:9, 2:4] = True
        fly = np.zeros((10, 12), dtype=bool)
        fly[4:6, 1:11] = True
        masks = [idle, idle, fly, fly, idle, idle]
        self.assertTrue(flight_attitude_needed(masks, 2, 2))
        walk = [idle, idle, idle, idle, idle, idle]
        self.assertFalse(flight_attitude_needed(walk, 2, 2))

    def test_closer_aspect_picks_landscape_pitch(self) -> None:
        self.assertEqual(closer_aspect((1.75, 1.80), 1.95), 1)
        self.assertEqual(closer_aspect((0.48, 1.75), 1.25), 1)

    def test_flight_prior_is_side_view_identity_root(self) -> None:
        self.assertEqual(FLIGHT_PRIOR, "side_view_identity_root")

    def test_flyer_attitude_bones_are_spine_then_forks(self) -> None:
        names = (
            "UniRigArmature",
            "Bone_000",
            "Bone_001",
            "Bone_003",
            "Bone_002",
            "Bone_016",
            "output_unwrapped",
        )
        parents = (None, 0, 1, 2, 3, 4, 0)
        self.assertEqual(
            flyer_attitude_bones(names, parents, generations=4),
            ["Bone_001", "Bone_003", "Bone_002"],
        )

    def test_flyer_spine_chain_follows_longest_bone_path(self) -> None:
        names = (
            "UniRigArmature",
            "Bone_000",
            "Bone_001",
            "Bone_003",
            "Bone_007",
            "Bone_002",
            "output_unwrapped",
        )
        parents = (None, 0, 1, 2, 2, 3, 0)
        self.assertEqual(
            flyer_spine_chain_bones(names, parents, length=3),
            ["Bone_001", "Bone_003", "Bone_002"],
        )

    def test_leftover_primary_strict_rejects_leftover_growth_for_extra_drop(self) -> None:
        before = OccupancyFractions(leftover=0.150, extra=0.12, sprite_pixels=100, leftover_pixels=15, extra_pixels=12)
        after = OccupancyFractions(leftover=0.154, extra=0.10, sprite_pixels=100, leftover_pixels=16, extra_pixels=10)
        self.assertTrue(leftover_primary_better(before, after))
        self.assertFalse(leftover_primary_better(before, after, allow_leftover_growth=False))

    def test_camera_axis_spans_and_side_view_ratio(self) -> None:
        points = np.asarray(((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 0.5)), dtype=np.float64)
        spans = camera_axis_spans(points, (1.0, 0.0, 0.0), (0.0, -1.0, 0.0), (0.0, 0.0, -1.0))
        self.assertAlmostEqual(spans["right"], 2.0)
        self.assertAlmostEqual(spans["down"], 1.0)
        self.assertAlmostEqual(spans["forward"], 0.5)
        self.assertAlmostEqual(side_view_ratio(spans), 4.0)
        self.assertAlmostEqual(horizontal_ratio(spans), 2.0)

    def test_spine_camera_align_detects_horizontal_vs_dive(self) -> None:
        right = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
        down = np.asarray((0.0, -1.0, 0.0), dtype=np.float64)
        forward = np.asarray((0.0, 0.0, -1.0), dtype=np.float64)
        fly = spine_camera_align(((0.0, 0.0, 0.0), (2.0, 0.0, 0.0)), right, down, forward)
        dive = spine_camera_align(((0.0, 2.0, 0.0), (0.0, 0.0, 0.0)), right, down, forward)
        belly = spine_camera_align(((0.0, 0.0, 0.0), (0.0, 0.0, 2.0)), right, down, forward)
        self.assertGreater(fly["right"], 0.99)
        self.assertTrue(spine_is_side_view_flight(fly))
        self.assertGreater(dive["down"], 0.99)
        self.assertFalse(spine_is_side_view_flight(dive))
        self.assertGreater(belly["forward"], 0.99)
        self.assertFalse(spine_is_side_view_flight(belly))
        self.assertGreater(spine_level_score(fly), spine_level_score(dive))
        self.assertGreater(spine_level_score({"right": 0.86, "down": 0.10, "forward": 0.30}), spine_level_score({"right": 0.86, "down": 0.41, "forward": 0.30}))

    def test_mask_principal_axis_distinguishes_cruise_from_takeoff(self) -> None:
        cruise = np.zeros((20, 40), dtype=bool)
        cruise[9:12, 2:38] = True
        takeoff = np.zeros((20, 40), dtype=bool)
        for index in range(16):
            takeoff[16 - index, 4 + index] = True
            takeoff[15 - index, 4 + index] = True
        cruise_axis = mask_principal_axis_xy(cruise)
        takeoff_axis = mask_principal_axis_xy(takeoff)
        self.assertGreater(cruise_axis[0], 0.95)
        self.assertLess(abs(cruise_axis[1]), 0.2)
        self.assertGreater(takeoff_axis[0], 0.4)
        self.assertLess(takeoff_axis[1], -0.4)
        cruise_spine = {"rightSigned": 1.0, "downSigned": 0.0}
        dive_spine = {"rightSigned": 0.7, "downSigned": 0.7}
        climb_spine = {"rightSigned": 0.7, "downSigned": -0.7}
        self.assertGreater(spine_sprite_axis_score(cruise_spine, cruise_axis), 0.95)
        self.assertGreater(
            spine_sprite_axis_score(climb_spine, takeoff_axis),
            spine_sprite_axis_score(dive_spine, takeoff_axis),
        )

    def test_body_core_axis_ignores_vertical_wings(self) -> None:
        mask = np.zeros((40, 40), dtype=bool)
        mask[16:24, 4:36] = True
        mask[0:40, 19:21] = True
        core = mask_body_core_axis_xy(mask)
        self.assertGreater(core[0], 0.85)
        self.assertLess(abs(core[1]), 0.3)
        self.assertTrue(spine_is_image_plane({"right": 0.86, "down": 0.41, "forward": 0.31}))
        self.assertFalse(spine_is_image_plane({"right": 0.27, "down": 0.37, "forward": 0.89}))

    def test_flight_phase_axis_is_takeoff_cruise_landing(self) -> None:
        self.assertEqual(flight_phase_sprite_axis(8, prefix=8, suffix=8, frame_count=30), FLIGHT_TAKEOFF_AXIS_XY)
        self.assertEqual(flight_phase_sprite_axis(15, prefix=8, suffix=8, frame_count=30), FLIGHT_CRUISE_AXIS_XY)
        self.assertEqual(flight_phase_sprite_axis(21, prefix=8, suffix=8, frame_count=30), FLIGHT_LANDING_AXIS_XY)
        sources = [
            frame_rest_source(index, prefix=8, suffix=8, frame_count=30) for index in range(30)
        ]
        self.assertEqual(sources[:8], ["perch"] * 8)
        self.assertEqual(sources[8:10], ["takeoff"] * 2)
        self.assertEqual(sources[10:20], ["cruise"] * 10)
        self.assertEqual(sources[20:22], ["landing"] * 2)
        self.assertEqual(sources[22:], ["perch"] * 8)
        self.assertEqual(
            flight_phase_representative_frames(list(range(30)), prefix=8, suffix=8),
            {"takeoff": 8, "cruise": 15, "landing": 21},
        )
        climb = {"rightSigned": 0.71, "downSigned": -0.71}
        level = {"rightSigned": 1.0, "downSigned": 0.0}
        self.assertGreater(
            spine_sprite_axis_score(climb, FLIGHT_TAKEOFF_AXIS_XY),
            spine_sprite_axis_score(level, FLIGHT_TAKEOFF_AXIS_XY),
        )
        self.assertGreater(
            spine_sprite_axis_score(level, FLIGHT_CRUISE_AXIS_XY),
            spine_sprite_axis_score(climb, FLIGHT_CRUISE_AXIS_XY),
        )
        perch = {"right": 0.01, "down": 0.99, "forward": 0.09}
        takeoff = {"right": 0.75, "down": 0.53, "forward": 0.40}
        flat = {"right": 0.99, "down": 0.04, "forward": 0.14}
        self.assertTrue(flyer_frame_is_perch_trap(perch, FLIGHT_TAKEOFF_AXIS_XY))
        self.assertFalse(flyer_frame_is_perch_trap(takeoff, FLIGHT_TAKEOFF_AXIS_XY))
        self.assertFalse(
            flyer_frame_is_perch_trap(
                {"right": 0.50, "down": 0.86, "forward": 0.15},
                FLIGHT_LANDING_AXIS_XY,
            )
        )
        self.assertTrue(flyer_frame_is_flat_trap(flat, FLIGHT_LANDING_AXIS_XY))
        self.assertFalse(flyer_frame_is_flat_trap(takeoff, FLIGHT_LANDING_AXIS_XY))
        self.assertTrue(flyer_frame_is_pitch_trap(takeoff, FLIGHT_CRUISE_AXIS_XY))
        self.assertTrue(
            flyer_frame_is_pitch_trap(
                {"right": 0.88, "down": 0.22, "forward": 0.41},
                FLIGHT_CRUISE_AXIS_XY,
            )
        )
        self.assertFalse(flyer_frame_is_pitch_trap({"right": 0.98, "down": 0.10, "forward": 0.12}, FLIGHT_CRUISE_AXIS_XY))
        self.assertTrue(flyer_frame_is_camera_trap({"right": 0.85, "down": 0.03, "forward": 0.53}))
        self.assertFalse(flyer_frame_is_camera_trap({"right": 0.70, "down": 0.70, "forward": 0.08}))
        self.assertGreaterEqual(0.495, FLIGHT_REST_RIGHT_MIN)
        self.assertLess(FLIGHT_REST_RIGHT_MIN, 0.5)
        self.assertEqual(max(abs(step) for step in PIPELINE_REFINE_SPINE_STEPS_DEG), 30.0)
        self.assertNotIn(90.0, PIPELINE_REFINE_SPINE_STEPS_DEG)
        self.assertIn(90.0, FLIGHT_SPINE_STEPS_DEG)
        from run_sprite_feasibility_surgery import (
            flyer_attitude_donor_frame,
            flyer_shared_phase_belly_roll,
            previous_rows_same_phase,
        )

        self.assertTrue(callable(flyer_shared_phase_belly_roll))
        self.assertEqual(
            previous_rows_same_phase(
                [{"frame": 8}, {"frame": 15}],
                frame=21,
                frame_phase={8: "takeoff", 15: "cruise", 21: "landing"},
            ),
            [],
        )
        self.assertEqual(
            [row["frame"] for row in previous_rows_same_phase(
                [{"frame": 10}, {"frame": 15}],
                frame=19,
                frame_phase={10: "cruise", 15: "cruise", 19: "cruise"},
            )],
            [10, 15],
        )

        takeoff_row = {"frame": 8, "spineAlign": {"right": 0.75, "down": 0.53, "forward": 0.40}}
        cruise_row = {"frame": 15, "spineAlign": {"right": 0.88, "down": 0.12, "forward": 0.36}}
        self.assertEqual(
            flyer_attitude_donor_frame([takeoff_row], perch_trap=True, flat_trap=False),
            8,
        )
        self.assertEqual(
            flyer_attitude_donor_frame([takeoff_row, cruise_row], perch_trap=False, flat_trap=True),
            8,
        )

    def test_flyer_funnel_measures_tail_to_head_and_rejects_dive(self) -> None:
        names = ["Bone_000", "Bone_001", "Bone_002", "Bone_012", "Bone_014", "Bone_016"]
        parents = [None, 0, 1, 2, 2, 4]
        self.assertEqual(
            flyer_visual_body_chain(names, parents, catalog=load_unit_anatomy_catalog("h3_roc")),
            ["Bone_012", "Bone_014"],
        )
        search = flyer_broad_stroke_search_bones(
            names, parents, catalog=load_unit_anatomy_catalog("h3_roc")
        )
        self.assertIn("Bone_014", search)
        self.assertIn("Bone_012", search)
        dive = {
            "spineAlign": {
                "right": 0.70,
                "rightSigned": 0.70,
                "down": 0.70,
                "downSigned": 0.70,
                "forward": 0.08,
                "forwardSigned": 0.08,
            },
            "spriteAxis": list(FLIGHT_TAKEOFF_AXIS_XY),
            "perchTrap": False,
            "flatTrap": False,
            "pitchTrap": False,
        }
        climb = {
            "spineAlign": {
                "right": 0.70,
                "rightSigned": 0.70,
                "down": 0.70,
                "downSigned": -0.70,
                "forward": 0.08,
                "forwardSigned": -0.08,
            },
            "spriteAxis": list(FLIGHT_TAKEOFF_AXIS_XY),
            "perchTrap": False,
            "flatTrap": False,
            "pitchTrap": False,
        }
        cruise = {
            "spineAlign": {
                "right": 0.98,
                "rightSigned": 0.98,
                "down": 0.02,
                "downSigned": 0.0,
                "forward": 0.18,
                "forwardSigned": -0.18,
            },
            "spriteAxis": list(FLIGHT_CRUISE_AXIS_XY),
            "perchTrap": False,
            "flatTrap": False,
            "pitchTrap": False,
        }
        self.assertFalse(flyer_broad_stroke_ok([dive, cruise]))
        self.assertTrue(flyer_broad_stroke_ok([climb, cruise]))
        left = dict(cruise)
        left["spineAlign"] = {
            "right": 1.0,
            "rightSigned": -1.0,
            "down": 0.0,
            "downSigned": 0.0,
            "forward": 0.01,
            "forwardSigned": 0.01,
        }
        self.assertFalse(flyer_broad_stroke_ok([climb, left]))
        self.assertTrue(flyer_phase_needs_right_seed(left["spineAlign"], FLIGHT_CRUISE_AXIS_XY))
        self.assertFalse(flyer_phase_needs_right_seed(climb["spineAlign"], FLIGHT_TAKEOFF_AXIS_XY))

    def test_shared_skeleton_velocity_is_bidirectional(self) -> None:
        self.assertFalse(
            clip_wraps_temporally(
                "idle_start_move_end",
                {"config": {"idle_prefix_frames": 8, "idle_suffix_frames": 8}},
            )
        )
        self.assertTrue(clip_wraps_temporally("idle", {"config": {}}))
        groups = flight_phase_groups(
            list(range(8, 22)), prefix=8, suffix=8, frame_count=30
        )
        self.assertEqual(groups["takeoff"], [8, 9])
        self.assertEqual(groups["landing"][-1], 21)
        self.assertIn(15, groups["cruise"])
        delta = wrapped_deg_delta(np.asarray((179.0, 0.0, 0.0)), np.asarray((-179.0, 0.0, 0.0)))
        self.assertLess(abs(float(delta[0])), 3.0)
        standing = {
            7: {"Bone_001": {"x": 0.0, "y": 0.0, "z": 0.0}},
            8: {"Bone_001": {"x": -80.0, "y": 0.0, "z": 0.0}},
            9: {"Bone_001": {"x": 0.0, "y": 0.0, "z": 0.0}},
            10: {"Bone_001": {"x": -80.0, "y": 0.0, "z": 0.0}},
        }
        flying = {
            7: {"Bone_001": {"x": 0.0, "y": 0.0, "z": 0.0}},
            8: {"Bone_001": {"x": -80.0, "y": 0.0, "z": 0.0}},
            9: {"Bone_001": {"x": -80.0, "y": 0.0, "z": 0.0}},
            10: {"Bone_001": {"x": -80.0, "y": 0.0, "z": 0.0}},
        }
        frames = (7, 8, 9, 10)
        self.assertGreater(
            pose_bidirectional_velocity_rms(
                standing, frame=9, frames=frames, bones=("Bone_001",), wrap=False
            ),
            pose_bidirectional_velocity_rms(
                flying, frame=9, frames=frames, bones=("Bone_001",), wrap=False
            ),
        )
        cycle = {
            0: {"Bone_001": {"x": 0.0, "y": 0.0, "z": 0.0}},
            1: {"Bone_001": {"x": 10.0, "y": 0.0, "z": 0.0}},
            2: {"Bone_001": {"x": 90.0, "y": 0.0, "z": 0.0}},
        }
        wrap_vel = pose_bidirectional_velocity_rms(
            cycle, frame=0, frames=(0, 1, 2), bones=("Bone_001",), wrap=True
        )
        nowrap_vel = pose_bidirectional_velocity_rms(
            cycle, frame=0, frames=(0, 1, 2), bones=("Bone_001",), wrap=False
        )
        self.assertGreater(wrap_vel, nowrap_vel)
        shared = {
            0: {"Bone_A": {"x": -140.0, "y": 0.0, "z": 0.0}},
            1: {"Bone_A": {"x": -135.0, "y": 0.0, "z": 0.0}},
        }
        applied = rotate_bone_deg_shared_within_limit(
            shared,
            joint="Bone_A",
            frames=(0, 1),
            axis="x",
            delta_deg=-30.0,
            joint_limit_deg=150.0,
        )
        self.assertAlmostEqual(applied, -10.0)
        self.assertAlmostEqual(shared[0]["Bone_A"]["x"], -150.0)
        self.assertAlmostEqual(shared[1]["Bone_A"]["x"], -145.0)

    def test_belly_align_is_signed_down_not_abs(self) -> None:
        down = np.asarray((0.0, -1.0, 0.0), dtype=np.float64)
        forward = np.asarray((0.0, 0.0, -1.0), dtype=np.float64)
        toward_ground = belly_camera_align((0.0, -1.0, 0.0), down, forward)
        toward_camera = belly_camera_align((0.0, 0.0, -1.0), down, forward)
        self.assertGreater(toward_ground["down"], 0.99)
        self.assertTrue(belly_is_down(toward_ground))
        self.assertGreater(toward_camera["forward"], 0.99)
        self.assertFalse(belly_is_down(toward_camera))
        stripped = remove_axis_component((1.0, -2.0, 0.0), (1.0, 0.0, 0.0))
        np.testing.assert_allclose(stripped, (0.0, -2.0, 0.0), atol=1e-9)

    def test_side_view_flight_prefers_3d_horizontal_over_leftover(self) -> None:
        before = OccupancyFractions(leftover=0.12, extra=0.10, sprite_pixels=100, leftover_pixels=12, extra_pixels=10)
        after = OccupancyFractions(leftover=0.18, extra=0.11, sprite_pixels=100, leftover_pixels=18, extra_pixels=11)
        before_spans = {"right": 0.8, "down": 1.6, "forward": 0.5}
        trial_spans = {"right": 1.7, "down": 1.1, "forward": 0.5}
        self.assertTrue(
            side_view_flight_better(
                before,
                after,
                before_spans=before_spans,
                trial_spans=trial_spans,
                sprite_aspect=1.5,
                before_aspect=horizontal_ratio(before_spans),
                trial_aspect=horizontal_ratio(trial_spans),
                leftover_growth_cap=1.0,
                prefer_aspect=True,
            )
        )

    def test_side_view_flight_rejects_belly_on_even_if_leftover_drops(self) -> None:
        before = OccupancyFractions(leftover=0.20, extra=0.10, sprite_pixels=100, leftover_pixels=20, extra_pixels=10)
        after = OccupancyFractions(leftover=0.12, extra=0.08, sprite_pixels=100, leftover_pixels=12, extra_pixels=8)
        before_spans = {"right": 2.0, "down": 1.0, "forward": 0.5}
        trial_spans = {"right": 2.0, "down": 1.0, "forward": 2.2}
        self.assertFalse(
            side_view_flight_better(
                before,
                after,
                before_spans=before_spans,
                trial_spans=trial_spans,
                sprite_aspect=1.5,
                before_aspect=0.8,
                trial_aspect=1.4,
            )
        )

    def test_side_view_flight_keeps_aspect_match_when_side_ratio_holds(self) -> None:
        before = OccupancyFractions(leftover=0.18, extra=0.12, sprite_pixels=100, leftover_pixels=18, extra_pixels=12)
        after = OccupancyFractions(leftover=0.18, extra=0.12, sprite_pixels=100, leftover_pixels=18, extra_pixels=12)
        spans = {"right": 2.0, "down": 1.0, "forward": 0.5}
        self.assertTrue(
            side_view_flight_better(
                before,
                after,
                before_spans=spans,
                trial_spans=spans,
                sprite_aspect=1.5,
                before_aspect=0.7,
                trial_aspect=1.4,
            )
        )

    def test_orbit_identity_keeps_camera_axes(self) -> None:
        right = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
        down = np.asarray((0.0, -1.0, 0.0), dtype=np.float64)
        rotated_right, rotated_down, rotated_up, rotated_forward = orbit_camera_vectors(
            right, down, yaw_deg=0.0, pitch_deg=0.0
        )
        np.testing.assert_allclose(rotated_right, right, atol=1e-9)
        np.testing.assert_allclose(rotated_down, down, atol=1e-9)
        np.testing.assert_allclose(rotated_up, (0.0, 1.0, 0.0), atol=1e-9)
        np.testing.assert_allclose(rotated_forward, (0.0, 0.0, -1.0), atol=1e-9)

    def test_orbit_yaw_180_flips_right_and_forward(self) -> None:
        right = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
        down = np.asarray((0.0, -1.0, 0.0), dtype=np.float64)
        rotated_right, rotated_down, _up, rotated_forward = orbit_camera_vectors(
            right, down, yaw_deg=180.0, pitch_deg=0.0
        )
        np.testing.assert_allclose(rotated_right, (-1.0, 0.0, 0.0), atol=1e-9)
        np.testing.assert_allclose(rotated_down, down, atol=1e-9)
        np.testing.assert_allclose(rotated_forward, (0.0, 0.0, 1.0), atol=1e-9)

    def test_orbit_projection_keeps_pivot_on_same_screen_pixel(self) -> None:
        right = np.asarray((1.0, 0.0, 0.0), dtype=np.float64)
        down = np.asarray((0.0, -1.0, 0.0), dtype=np.float64)
        offset = np.asarray((100.0, 80.0), dtype=np.float64)
        px_per_world = np.asarray((10.0, 10.0), dtype=np.float64)
        pivot = np.asarray((1.0, 2.0, 3.0), dtype=np.float64)
        seed_screen = np.asarray(
            (
                float(np.dot(pivot, right) * px_per_world[0] + offset[0]),
                float(np.dot(pivot, down) * px_per_world[1] + offset[1]),
            ),
            dtype=np.float64,
        )
        camera = orbit_projection(
            right=right,
            down=down,
            offset=offset,
            px_per_world=px_per_world,
            pivot=pivot,
            yaw_deg=90.0,
            pitch_deg=-75.0,
        )
        moved_screen = np.asarray(
            (
                float(np.dot(pivot, camera["right"]) * px_per_world[0] + camera["offset"][0]),
                float(np.dot(pivot, camera["down"]) * px_per_world[1] + camera["offset"][1]),
            ),
            dtype=np.float64,
        )
        np.testing.assert_allclose(moved_screen, seed_screen, atol=1e-9)
        identity = orbit_projection(
            right=right,
            down=down,
            offset=offset,
            px_per_world=px_per_world,
            pivot=pivot,
            yaw_deg=0.0,
            pitch_deg=0.0,
        )
        np.testing.assert_allclose(identity["right"], right, atol=1e-9)
        np.testing.assert_allclose(identity["down"], down, atol=1e-9)
        np.testing.assert_allclose(identity["offset"], offset, atol=1e-9)

    def test_vision_check_frame_positions_include_idle_and_move(self) -> None:
        self.assertEqual(vision_check_frame_positions(30, 8, 8), [0, 8, 15, 21, 29])
        self.assertEqual(vision_check_frame_positions(8, 8, 0), [0, 7])

    def test_leftover_primary_keeps_leftover_drop_even_if_extra_grows(self) -> None:
        before = OccupancyFractions(leftover=0.20, extra=0.10, sprite_pixels=100, leftover_pixels=20, extra_pixels=10)
        after = OccupancyFractions(leftover=0.08, extra=0.14, sprite_pixels=100, leftover_pixels=8, extra_pixels=14)
        self.assertTrue(leftover_primary_better(before, after))

    def test_set_root_rotation_writes_move_frames_only(self) -> None:
        poses = {
            0: {"__motion_root_rotation__": {"camera_forward": 0.0, "camera_right": 0.0, "camera_up": 1.0}},
            8: {"__motion_root_rotation__": {"camera_forward": 0.0, "camera_right": 0.0, "camera_up": 2.0}},
        }
        set_root_rotation_deg(
            poses,
            frames=(8,),
            values_deg={"camera_right": 90.0, "camera_forward": 15.0},
        )
        self.assertEqual(poses[0]["__motion_root_rotation__"]["camera_right"], 0.0)
        self.assertEqual(poses[0]["__motion_root_rotation__"]["camera_up"], 1.0)
        self.assertEqual(poses[8]["__motion_root_rotation__"]["camera_right"], 90.0)
        self.assertEqual(poses[8]["__motion_root_rotation__"]["camera_forward"], 15.0)
        self.assertEqual(poses[8]["__motion_root_rotation__"]["camera_up"], 2.0)

    def test_apply_rest_space_deltas_skips_over_cap(self) -> None:
        rest = np.asarray(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (3.0, 0.0, 0.0)), dtype=np.float64)
        deltas = np.asarray(((0.1, 0.0, 0.0), (5.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.1, 0.0, 0.0)), dtype=np.float64)
        sculpt = apply_rest_space_deltas(
            rest,
            deltas,
            np.asarray((True, True, True, True)),
            max_displacement=1.0,
        )
        self.assertFalse(bool(sculpt["rejected"]))
        self.assertEqual(int(sculpt["moved"]), 3)
        self.assertEqual(int(sculpt["skipped"]), 1)
        self.assertAlmostEqual(float(sculpt["positions"][0, 0]), 0.1)
        self.assertAlmostEqual(float(sculpt["positions"][1, 0]), 1.0)

    def test_occupancy_rest_gate_accepts_extra_drop_without_leftover_epsilon(self) -> None:
        before = OccupancyFractions(leftover=0.11, extra=0.27, sprite_pixels=100, leftover_pixels=11, extra_pixels=27)
        after = OccupancyFractions(leftover=0.12, extra=0.20, sprite_pixels=100, leftover_pixels=12, extra_pixels=20)
        gate = accept_occupancy_rest(before, after)
        self.assertTrue(gate["accepted"])
        self.assertGreater(float(gate["extraDrop"]), 0.0)

    def test_occupancy_rest_gate_accepts_leftover_fill_with_smaller_extra_overshoot(self) -> None:
        before = OccupancyFractions(leftover=0.191, extra=0.047, sprite_pixels=100, leftover_pixels=19, extra_pixels=5)
        after = OccupancyFractions(leftover=0.160, extra=0.067, sprite_pixels=100, leftover_pixels=16, extra_pixels=7)
        gate = accept_occupancy_rest(before, after)
        self.assertTrue(gate["accepted"])
        self.assertGreater(float(gate["netDrop"]), 0.0)

    def test_occupancy_rest_gate_rejects_when_neither_occupancy_improves(self) -> None:
        before = OccupancyFractions(leftover=0.21, extra=0.03, sprite_pixels=100, leftover_pixels=21, extra_pixels=3)
        after = OccupancyFractions(leftover=0.21, extra=0.04, sprite_pixels=100, leftover_pixels=21, extra_pixels=4)
        gate = accept_occupancy_rest(before, after)
        self.assertFalse(gate["accepted"])

    def test_two_rejects_do_not_skip_diagnosed_missing_joint(self) -> None:
        tried = [CLASS_WRONG_OWNER, CLASS_BODY_INFEASIBLE_REST]
        pending = next_pending_class(
            tried=tried,
            consecutive_rejects=2,
            diagnosed=CLASS_MISSING_JOINT,
        )
        self.assertEqual(pending, CLASS_BODY_INFEASIBLE_LENGTH)
        after_length = next_pending_class(
            tried=tried + [CLASS_BODY_INFEASIBLE_LENGTH],
            consecutive_rejects=3,
            diagnosed=CLASS_MISSING_JOINT,
        )
        self.assertEqual(after_length, CLASS_MISSING_JOINT)


class CameraClassifyTests(unittest.TestCase):
    def test_goblin_shaped_rear_leader_is_camera_mismatch(self) -> None:
        init = {
            "selection": {"selectedFacingScore": 0.058, "selectedYawDeg": -120.0},
            "best": {"facingScore": 0.058, "yawDeg": -120.0},
            "candidates": [
                {"yawDeg": -120.0, "rollDeg": 8.0, "facingScore": 0.058, "silhouetteScore": 0.705},
                {"yawDeg": 0.0, "rollDeg": -8.0, "facingScore": 0.827, "silhouetteScore": 0.668},
            ],
        }
        report = classify_camera_from_init(init)
        self.assertEqual(report["primaryClass"], CLASS_CAMERA_MISMATCH)
        self.assertEqual(report["profileCandidate"]["yawDeg"], 0.0)

    def test_unresolved_when_no_profile_facing_candidate(self) -> None:
        init = {
            "selection": {"selectedFacingScore": 0.05, "selectedYawDeg": 180.0},
            "best": {"facingScore": 0.05, "yawDeg": 180.0},
            "candidates": [
                {"yawDeg": 180.0, "facingScore": 0.05, "silhouetteScore": 0.5},
                {"yawDeg": 90.0, "facingScore": 0.2, "silhouetteScore": 0.4},
            ],
        }
        report = classify_camera_from_init(init)
        self.assertEqual(report["primaryClass"], CLASS_CAMERA_MISMATCH_UNRESOLVED)

    def test_pikeman_shaped_leader_above_veto_is_ok(self) -> None:
        init = {
            "selection": {"selectedFacingScore": 0.202, "selectedYawDeg": 45.0},
            "best": {"facingScore": 0.202, "yawDeg": 45.0},
            "candidates": [
                {"yawDeg": 45.0, "facingScore": 0.202, "silhouetteScore": 0.4975},
                {"yawDeg": -30.0, "facingScore": 0.998, "silhouetteScore": 0.4569},
            ],
        }
        self.assertEqual(classify_camera_from_init(init)["primaryClass"], CLASS_CAMERA_OK)

    def test_pick_highest_facing_not_stored_score(self) -> None:
        pool = [
            {"yawDeg": -120.0, "facingScore": 0.058, "score": 0.698, "silhouetteScore": 0.70},
            {"yawDeg": 0.0, "facingScore": 0.827, "score": 0.925, "silhouetteScore": 0.66},
        ]
        picked = pick_highest_facing_profile(pool)
        self.assertIsNotNone(picked)
        self.assertEqual(picked["yawDeg"], 0.0)


class BodyClassTests(unittest.TestCase):
    def test_causal_geometry_vs_joint(self) -> None:
        self.assertEqual(
            classify_occupancy_body(
                leftover_near=False,
                leftover_far=True,
                unassigned_far=True,
                geometry_projects_near=False,
                debt_helps=False,
                owner_agrees=True,
                unique_owner=None,
            ),
            CLASS_MISSING_GEOMETRY,
        )
        self.assertEqual(
            classify_occupancy_body(
                leftover_near=False,
                leftover_far=True,
                unassigned_far=True,
                geometry_projects_near=True,
                debt_helps=False,
                owner_agrees=True,
                unique_owner=None,
            ),
            CLASS_MISSING_JOINT,
        )

    def test_debt_beats_rest(self) -> None:
        self.assertEqual(
            classify_occupancy_body(
                leftover_near=True,
                leftover_far=False,
                unassigned_far=False,
                geometry_projects_near=True,
                debt_helps=True,
                owner_agrees=True,
                unique_owner="Bone_A",
            ),
            CLASS_POSE_SEARCH_DEBT,
        )

    def test_wrong_owner_and_rest(self) -> None:
        self.assertEqual(
            classify_occupancy_body(
                leftover_near=True,
                leftover_far=False,
                unassigned_far=False,
                geometry_projects_near=True,
                debt_helps=False,
                owner_agrees=False,
                unique_owner="Bone_A",
            ),
            CLASS_WRONG_OWNER,
        )
        self.assertEqual(
            classify_occupancy_body(
                leftover_near=True,
                leftover_far=False,
                unassigned_far=False,
                geometry_projects_near=True,
                debt_helps=False,
                owner_agrees=True,
                unique_owner="Bone_A",
            ),
            CLASS_BODY_INFEASIBLE_REST,
        )

    def test_next_body_class_advances(self) -> None:
        self.assertEqual(next_body_class([]), CLASS_WRONG_OWNER)
        self.assertEqual(next_body_class([CLASS_WRONG_OWNER]), CLASS_BODY_INFEASIBLE_REST)
        self.assertIsNone(
            next_body_class(
                [CLASS_WRONG_OWNER, CLASS_BODY_INFEASIBLE_REST, CLASS_BODY_INFEASIBLE_LENGTH, CLASS_MISSING_JOINT]
            )
        )


class LbsInvertTests(unittest.TestCase):
    def test_identity_blend_moves_rest_by_world_delta(self) -> None:
        rest = np.asarray((0.0, 0.0, 0.0), dtype=np.float64)
        blend = np.eye(4, dtype=np.float64)
        new_rest, status = invert_lbs_image_plane(
            rest,
            blend,
            delta_world=np.asarray((0.1, 0.0, 0.0)),
            max_displacement=1.0,
        )
        self.assertEqual(status, "moved")
        self.assertIsNotNone(new_rest)
        np.testing.assert_allclose(new_rest, (0.1, 0.0, 0.0), atol=1e-8)

    def test_ill_conditioned_blend_skips(self) -> None:
        rest = np.zeros(3, dtype=np.float64)
        blend = np.eye(4, dtype=np.float64)
        blend[0, 0] = 1e-9
        new_rest, status = invert_lbs_image_plane(
            rest,
            blend,
            delta_world=np.asarray((0.1, 0.0, 0.0)),
            max_displacement=1.0,
        )
        self.assertIsNone(new_rest)
        self.assertEqual(status, "ill_conditioned")

    def test_skip_cap(self) -> None:
        self.assertTrue(skip_fraction_reject(3, 10, cap=0.25))
        self.assertFalse(skip_fraction_reject(2, 10, cap=0.25))
        with self.assertRaises(ValueError):
            skip_fraction_reject(0, 0)


class WritePathTests(unittest.TestCase):
    def test_work_tree_ok_live_paths_fail(self) -> None:
        dest = work_tree_root(ROOT) / "_contract_probe_test" / "round_00" / "mesh.glb"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x")
        self.assertEqual(assert_write_path(dest, repo_root=ROOT), dest.resolve())
        live = ROOT / "artifacts" / "meshy_downloads" / "h3_goblin_smartrigged.glb"
        with self.assertRaises(RuntimeError):
            assert_write_path(live, repo_root=ROOT)
        fused = (
            ROOT
            / "artifacts"
            / "pose_picker_runs"
            / "h3_goblin"
            / "idle"
            / "fused_push_v24_pipeline"
            / "gpu_clip_result.json"
        )
        with self.assertRaises(RuntimeError):
            assert_write_path(fused, repo_root=ROOT)


class GlbSurgeryTests(unittest.TestCase):
    def test_minimal_glb_round_trip_and_insert_bone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_minimal_skinned_glb(Path(tmp) / "bar.glb")
            report = validate_skinned_glb(path)
            self.assertEqual(report["jointCount"], 2)
            doc, blob = load_glb(path)
            inserted = insert_child_bone(
                doc,
                blob,
                parent_node=1,
                name="Bone_Finger",
                translation=(0.0, 0.6, 0.0),
                vertex_indices=(4, 5),
            )
            out = Path(tmp) / "after.glb"
            save_glb(out, doc, blob)
            after = validate_skinned_glb(out)
            self.assertEqual(after["jointCount"], 3)
            self.assertEqual(inserted["vertexCount"], 2)

    def test_rest_length_scales_child_translation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_minimal_skinned_glb(Path(tmp) / "bar.glb")
            doc, blob = load_glb(path)
            scale_bone_rest_translation(doc, blob, joint_node=1, scale=1.5)
            out = Path(tmp) / "long.glb"
            save_glb(out, doc, blob)
            validate_skinned_glb(out)
            doc2, _blob = load_glb(out)
            self.assertAlmostEqual(float(doc2["nodes"][1]["translation"][1]), 1.5)

    def test_rest_sculpt_identity_and_skip_cap_reject(self) -> None:
        rest = np.zeros((4, 3), dtype=np.float64)
        blends = np.stack([np.eye(4) for _ in range(4)])
        delta = np.zeros((4, 3), dtype=np.float64)
        delta[:, 0] = 0.05
        report = rest_sculpt_positions(
            rest,
            blends,
            deltas_world=delta,
            affected=np.array([True, True, True, True]),
            body_length=1.0,
        )
        self.assertFalse(report["rejected"])
        self.assertEqual(report["moved"], 4)
        bad = np.stack([np.eye(4) for _ in range(4)])
        for row in bad:
            row[0, 0] = 1e-9
        rejected = rest_sculpt_positions(
            rest,
            bad,
            deltas_world=delta,
            affected=np.array([True, True, True, True]),
            body_length=1.0,
        )
        self.assertTrue(rejected["rejected"])
        self.assertEqual(rejected["reason"], "lbs_ill_conditioned")
        self.assertIsNone(rejected["positions"])

    def test_bake_lbs_pose_to_rest_identity_and_ill_conditioned_reject(self) -> None:
        posed = np.array([[0.0, 1.0, 0.0], [1.0, 1.0, 0.0]], dtype=np.float64)
        blends = np.stack([np.eye(4), np.eye(4)])
        baked = bake_lbs_pose_to_rest(blends, posed)
        self.assertFalse(baked["rejected"])
        np.testing.assert_allclose(baked["positions"], posed)
        bad = np.stack([np.eye(4), np.eye(4)])
        bad[0, 0, 0] = 1e-9
        rejected = bake_lbs_pose_to_rest(bad, posed)
        self.assertTrue(rejected["rejected"])
        self.assertIsNone(rejected["positions"])

    def test_identity_joint_keep_root_zeros_bones_only(self) -> None:
        from sprite_body_surgery import MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY

        poses = {
            8: {
                "Bone_001": {"x": 12.0, "y": 4.0, "z": 0.0},
                MOTION_ROOT_KEY: {"forward": 0.1, "lateral": 0.0, "vertical": 0.2},
                MOTION_ROOT_ROTATION_KEY: {
                    "camera_forward": 3.0,
                    "camera_right": 0.0,
                    "camera_up": 1.0,
                },
            }
        }
        kept = identity_joint_keep_root_poses(poses, (8,))
        self.assertNotIn("Bone_001", kept[8])
        self.assertEqual(kept[8][MOTION_ROOT_KEY]["forward"], 0.1)
        self.assertEqual(kept[8][MOTION_ROOT_ROTATION_KEY]["camera_up"], 1.0)
        bind = bind_like_poses(poses, (8,))
        self.assertNotIn(MOTION_ROOT_ROTATION_KEY, bind[8])

    def test_rotation_aligning_bases_maps_spine_and_belly(self) -> None:
        rotation = rotation_aligning_bases(
            (0.0, 1.0, 0.0),
            (0.0, 0.0, 1.0),
            (1.0, 0.0, 0.0),
            (0.0, -1.0, 0.0),
        )
        np.testing.assert_allclose(rotation @ np.array([0.0, 1.0, 0.0]), (1.0, 0.0, 0.0), atol=1e-9)
        np.testing.assert_allclose(rotation @ np.array([0.0, 0.0, 1.0]), (0.0, -1.0, 0.0), atol=1e-9)
        points = np.array([[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
        moved = rotate_points_about_pivot(points, rotation, np.zeros(3))
        np.testing.assert_allclose(moved[0], (1.0, 0.0, 0.0), atol=1e-9)
        np.testing.assert_allclose(moved[1], (0.0, -1.0, 0.0), atol=1e-9)

    def test_rotation_mapping_vector_maps_axis(self) -> None:
        rotation = rotation_mapping_vector((0.0, 1.0, 0.0), (1.0, 0.0, 0.0))
        np.testing.assert_allclose(rotation @ np.array([0.0, 1.0, 0.0]), (1.0, 0.0, 0.0), atol=1e-9)
        with self.assertRaises(ValueError):
            rotation_mapping_vector((0.0, 0.0, 0.0), (1.0, 0.0, 0.0))

    def test_assign_opposite_wing_spans_does_not_cross(self) -> None:
        dst_a, dst_b = assign_opposite_wing_spans(
            (1.0, 0.2, 0.0),
            (-1.0, 0.1, 0.0),
            (0.0, 1.0, 0.0),
        )
        np.testing.assert_allclose(dst_a, (0.0, 1.0, 0.0), atol=1e-9)
        np.testing.assert_allclose(dst_b, (0.0, -1.0, 0.0), atol=1e-9)
        dst_a, dst_b = assign_opposite_wing_spans(
            (0.0, -1.0, 0.0),
            (0.0, 1.0, 0.0),
            (0.0, 1.0, 0.0),
        )
        np.testing.assert_allclose(dst_a, (0.0, -1.0, 0.0), atol=1e-9)
        np.testing.assert_allclose(dst_b, (0.0, 1.0, 0.0), atol=1e-9)

    def test_symmetric_raised_wings_are_mirrored_and_dorsal(self) -> None:
        dest_a, dest_b = symmetric_raised_wing_destinations(
            (1.0, 0.0, 0.0),
            (-1.0, 0.0, 0.0),
            spine=(0.0, 1.0, 0.0),
            ventral=(0.0, 0.0, 1.0),
        )
        ventral = np.array((0.0, 0.0, 1.0))
        self.assertLess(float(np.dot(dest_a, ventral)), 0.0)
        self.assertLess(float(np.dot(dest_b, ventral)), 0.0)
        summed = dest_a + dest_b
        np.testing.assert_allclose(
            summed / np.linalg.norm(summed),
            (0.0, 0.0, -1.0),
            atol=1e-9,
        )

    def test_spread_labeled_wing_vertices_aims_opposite_spans(self) -> None:
        catalog = {
            "groups": {
                "wing_a": {"bonesDependencyOrder": ["shoulder_a", "tip_a"]},
                "wing_b": {"bonesDependencyOrder": ["shoulder_b", "tip_b"]},
            }
        }
        origins = {
            "shoulder_a": np.array([0.0, 0.0, 0.0]),
            "tip_a": np.array([0.0, 1.0, 0.0]),
            "shoulder_b": np.array([0.0, 0.0, 0.0]),
            "tip_b": np.array([0.0, -1.0, 0.0]),
        }
        positions = np.array(
            [[0.0, 1.0, 0.0]] * 8 + [[0.0, -1.0, 0.0]] * 8,
            dtype=np.float64,
        )
        owners = ["tip_a"] * 8 + ["tip_b"] * 8
        destinations = assign_opposite_wing_spans(
            (0.0, 1.0, 0.0),
            (0.0, -1.0, 0.0),
            (1.0, 0.0, 0.0),
        )
        report = spread_labeled_wing_vertices(
            positions,
            origins=origins,
            owner_names=owners,
            catalog=catalog,
            names=("shoulder_a", "tip_a", "shoulder_b", "tip_b"),
            destinations=destinations,
        )
        np.testing.assert_allclose(report["positions"][0], (1.0, 0.0, 0.0), atol=1e-9)
        np.testing.assert_allclose(report["positions"][8], (-1.0, 0.0, 0.0), atol=1e-9)
        self.assertEqual(report["wings"]["wing_a"]["shoulder"], "shoulder_a")
        self.assertEqual(report["wings"]["wing_b"]["tip"], "tip_b")

    def test_leg_tpose_destinations_are_ventral(self) -> None:
        dest_a, dest_b = symmetric_limb_destinations(
            (1.0, 0.0, 0.0),
            (-1.0, 0.0, 0.0),
            spine=(0.0, 1.0, 0.0),
            ventral=(0.0, 0.0, 1.0),
            pole="ventral",
        )
        ventral = np.array((0.0, 0.0, 1.0))
        self.assertGreater(float(np.dot(dest_a, ventral)), 0.0)
        self.assertGreater(float(np.dot(dest_b, ventral)), 0.0)

    def test_tpose_snip_cuts_mixed_stretched_edges_only(self) -> None:
        catalog = {
            "groups": {
                "wing_a": {"bonesDependencyOrder": ["wa"]},
                "trunk": {"bonesDependencyOrder": ["tr"]},
            }
        }
        perch = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.1, 0.0, 0.0],
                [0.0, 0.1, 0.0],
                [0.0, 0.0, 0.1],
                [0.1, 0.1, 0.0],
                [0.1, 0.0, 0.1],
                [0.0, 0.1, 0.1],
                [0.05, 0.05, 0.05],
            ],
            dtype=np.float64,
        )
        tpose = perch.copy()
        tpose[1] = (5.0, 0.0, 0.0)
        faces = np.array(
            [
                [0, 1, 2],
                [0, 2, 3],
                [0, 3, 4],
                [0, 4, 5],
                [0, 5, 6],
                [0, 6, 7],
                [2, 3, 7],
                [3, 4, 7],
            ],
            dtype=np.int64,
        )
        owners = ["tr", "wa", "tr", "tr", "tr", "tr", "tr", "tr"]
        snip = tpose_stretched_bridge_faces(perch, tpose, faces, owners, catalog, stretch_ratio=4.0)
        self.assertEqual(snip["cutCount"], 1)
        unstretched = perch.copy()
        unstretched[1] = (0.12, 0.0, 0.0)
        keep = tpose_stretched_bridge_faces(
            perch, unstretched, faces, owners, catalog, stretch_ratio=4.0
        )
        self.assertEqual(keep["cutCount"], 0)

    def test_next_anatomy_stage_after_rotation_is_symmetric_bone_fit(self) -> None:
        self.assertEqual(
            next_anatomy_fit_stage(ANATOMY_FIT_STAGES[:3]),
            "symmetric_bone_fit",
        )
        self.assertEqual(
            next_anatomy_fit_stage(ANATOMY_FIT_STAGES[:4]),
            "asymmetric_fine_tune",
        )
        self.assertEqual(
            next_anatomy_fit_stage(ANATOMY_FIT_STAGES[:5]),
            "shared_skeleton_temporal",
        )
        self.assertEqual(
            next_anatomy_fit_stage(ANATOMY_FIT_STAGES[:6]),
            "insert_missing_symmetric",
        )
        self.assertIn("shared_skeleton_temporal", ARCHITECTURE_ACCEPT_NAMES)
        self.assertIn("insert_missing_symmetric", ARCHITECTURE_ACCEPT_NAMES)
        self.assertEqual(next_anatomy_fit_stage([]), "tpose_straighten_spread")
        self.assertIn("symmetric_bone_fit", ARCHITECTURE_ACCEPT_NAMES)
        self.assertIn("asymmetric_fine_tune", ARCHITECTURE_ACCEPT_NAMES)
        self.assertIn("symmetric_only", ARCHITECTURE_ACCEPT_NAMES)
        self.assertEqual(SYMMETRIC_BONE_STEPS_DEG, (90.0, -90.0, 45.0, -45.0))
        self.assertEqual(ASYMMETRIC_REST_LENGTH_SCALES, (1.25, 1.45, 1.60))
        with self.assertRaises(ValueError):
            next_anatomy_fit_stage(["symmetric_bone_fit"])
        with self.assertRaises(ValueError):
            next_anatomy_fit_stage(list(ANATOMY_FIT_STAGES))

    def test_abbreviated_symmetric_only_uses_named_uncut_rest(self) -> None:
        import tempfile
        from run_sprite_feasibility_surgery import (
            architecture_source_round,
            fly_rest_tpose_source,
        )

        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            missing = work / "round_08"
            with self.assertRaises(ValueError):
                architecture_source_round(work, "round_08")
            missing.mkdir()
            found = architecture_source_round(work, "round_08")
            self.assertEqual(found, missing)
            with self.assertRaises(ValueError):
                fly_rest_tpose_source(found, allow_symmetric_standin=True)
            (found / "fly_rest_symmetric.glb").write_bytes(b"glb")
            self.assertEqual(
                fly_rest_tpose_source(found, allow_symmetric_standin=True).name,
                "fly_rest_symmetric.glb",
            )
            with self.assertRaises(ValueError):
                fly_rest_tpose_source(found, allow_symmetric_standin=False)
            (found / "fly_rest_tpose.glb").write_bytes(b"tpose")
            self.assertEqual(
                fly_rest_tpose_source(found, allow_symmetric_standin=True).name,
                "fly_rest_tpose.glb",
            )

    def test_roc_symmetric_pairs_zip_and_skip_trunk(self) -> None:
        catalog = load_unit_anatomy_catalog("h3_roc")
        names: list[str] = []
        for group in catalog["groups"].values():
            names.extend(group["bonesDependencyOrder"])
        pairs = symmetric_bone_fit_pairs(catalog, names)
        self.assertEqual([(row["groupA"], row["groupB"]) for row in pairs], [("wing_a", "wing_b"), ("leg_a", "leg_b")])
        self.assertEqual(len(pairs[0]["bonesA"]), len(pairs[0]["bonesB"]))
        self.assertEqual(len(pairs[1]["bonesA"]), len(pairs[1]["bonesB"]))
        self.assertEqual(anatomy_central_search_groups(catalog), ["neck_head", "tail"])
        distal = asymmetric_distal_bones(catalog, names)
        self.assertEqual(
            [(row["group"], row["bone"]) for row in distal],
            [("wing_a", "Bone_017"), ("wing_b", "Bone_020"), ("leg_a", "Bone_004"), ("leg_b", "Bone_008")],
        )
        self.assertEqual(anatomy_central_joint_axes(catalog), ("x", "y"))

    def test_leftover_unique_region_inserts_symmetric_distals(self) -> None:
        catalog = load_unit_anatomy_catalog("h3_roc")
        rows = leftover_symmetric_insert_parents(catalog, ["Bone_017", "Bone_019"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "bilateral")
        self.assertEqual(rows[0]["groupA"], "wing_a")
        self.assertEqual(rows[0]["groupB"], "wing_b")
        self.assertEqual(rows[0]["parentA"], "Bone_017")
        self.assertEqual(rows[0]["parentB"], "Bone_020")
        self.assertEqual(rows[0]["childA"], insert_child_bone_name("wing_a"))
        self.assertEqual(rows[0]["childB"], insert_child_bone_name("wing_b"))
        one_wing = leftover_symmetric_insert_parents(catalog, ["Bone_022"])
        self.assertEqual(one_wing[0]["parentA"], "Bone_017")
        self.assertEqual(one_wing[0]["parentB"], "Bone_020")
        head = leftover_symmetric_insert_parents(catalog, ["Bone_014"])
        self.assertEqual(head[0]["kind"], "central")
        self.assertEqual(head[0]["parent"], "Bone_014")
        self.assertEqual(head[0]["child"], insert_child_bone_name("neck_head"))
        with self.assertRaises(ValueError):
            leftover_symmetric_insert_parents(catalog, ["Bone_000", "Bone_001"])
        filtered = anatomy_joints_xy(
            catalog,
            {"Bone_017": (1.0, 2.0), "output_unwrapped": (9.0, 9.0), "Bone_014": (3.0, 4.0)},
        )
        self.assertEqual(set(filtered), {"Bone_017", "Bone_014"})
        self.assertNotIn("output_unwrapped", filtered)
        rest = np.array([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 2.0, 0.0]], dtype=np.float64)
        distal = distal_owner_vertex_indices(rest, ["keel", "tip", "tip"], "tip", rest[0], fraction=0.5)
        self.assertEqual(distal, [2])

    def test_symmetric_trial_requires_leftover_drop(self) -> None:
        before = OccupancyFractions(
            leftover=0.20, extra=0.10, sprite_pixels=100, leftover_pixels=20, extra_pixels=10
        )
        better = OccupancyFractions(
            leftover=0.16, extra=0.11, sprite_pixels=100, leftover_pixels=16, extra_pixels=11
        )
        extra_only = OccupancyFractions(
            leftover=0.20, extra=0.05, sprite_pixels=100, leftover_pixels=20, extra_pixels=5
        )
        extra_explodes = OccupancyFractions(
            leftover=0.16, extra=0.20, sprite_pixels=100, leftover_pixels=16, extra_pixels=20
        )
        self.assertTrue(symmetric_bone_trial_better(before, better))
        self.assertFalse(symmetric_bone_trial_better(before, extra_only))
        self.assertFalse(symmetric_bone_trial_better(before, extra_explodes))

    def test_bilateral_pair_mirrors_across_the_model_midline(self) -> None:
        identity = np.eye(3, dtype=np.float64)
        frame = {
            "lateral": np.array((1.0, 0.0, 0.0), dtype=np.float64),
            "spine": np.array((0.0, 1.0, 0.0), dtype=np.float64),
            "ventral": np.array((0.0, 0.0, 1.0), dtype=np.float64),
        }
        rests = {"wing_l": identity, "wing_r": identity}
        dirs = {
            "wing_l": np.array((-1.0, 0.0, 0.0), dtype=np.float64),
            "wing_r": np.array((1.0, 0.0, 0.0), dtype=np.float64),
        }
        poses = {0: {}, 1: {}}
        applied = rotate_bilateral_pair_deg_shared(
            poses,
            bone_a="wing_l",
            bone_b="wing_r",
            frames=(0, 1),
            axis="raise",
            delta_deg=45.0,
            joint_limit_deg=150.0,
            rest_rotations=rests,
            model_frame=frame,
            bone_dirs=dirs,
        )
        self.assertEqual(applied, 45.0)
        from sprite_bilateral_axes import axis_angle_deg_to_matrix

        dorsal = np.array((0.0, 0.0, -1.0), dtype=np.float64)
        left_dir = dirs["wing_l"]
        right_dir = dirs["wing_r"]
        posed_l = axis_angle_deg_to_matrix(
            [poses[0]["wing_l"][a] for a in "xyz"]
        ) @ left_dir
        posed_r = axis_angle_deg_to_matrix(
            [poses[0]["wing_r"][a] for a in "xyz"]
        ) @ right_dir
        self.assertGreater(float(np.dot(posed_l, dorsal)), float(np.dot(left_dir, dorsal)))
        self.assertGreater(float(np.dot(posed_r, dorsal)), float(np.dot(right_dir, dorsal)))
        cramped = {
            0: {
                "wing_l": {"x": 0.0, "y": -140.0, "z": 0.0},
                "wing_r": {"x": 0.0, "y": 0.0, "z": 0.0},
            }
        }
        with self.assertRaises(ValueError):
            rotate_bilateral_pair_deg_shared(
                cramped,
                bone_a="wing_l",
                bone_b="wing_r",
                frames=(0,),
                axis="raise",
                delta_deg=45.0,
                joint_limit_deg=150.0,
                rest_rotations=rests,
                model_frame=frame,
                bone_dirs=dirs,
            )

    def test_unique_joint_pose_count_ignores_root_translation(self) -> None:
        poses = {
            8: {
                "__motion_root__": {"forward": 0.0, "lateral": 0.0, "vertical": 0.0},
                "Bone_A": {"x": 10.0, "y": 0.0, "z": 0.0},
            },
            9: {
                "__motion_root__": {"forward": 1.0, "lateral": 0.0, "vertical": 0.0},
                "Bone_A": {"x": 10.0, "y": 0.0, "z": 0.0},
            },
            10: {
                "__motion_root__": {"forward": 2.0, "lateral": 0.0, "vertical": 0.0},
                "Bone_A": {"x": 45.0, "y": 0.0, "z": 0.0},
            },
        }
        self.assertEqual(unique_joint_pose_count(poses, (8, 9, 10)), 2)

    def test_copy_joints_keeps_dest_root(self) -> None:
        from sprite_body_surgery import MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY

        poses = {
            8: {
                MOTION_ROOT_KEY: {"forward": 0.1, "lateral": 0.0, "vertical": 0.0},
                MOTION_ROOT_ROTATION_KEY: {
                    "camera_forward": 0.0,
                    "camera_right": 0.0,
                    "camera_up": 1.0,
                },
                "Bone_A": {"x": 45.0, "y": 0.0, "z": 0.0},
            },
            9: {
                MOTION_ROOT_KEY: {"forward": 0.5, "lateral": 0.2, "vertical": 0.1},
                MOTION_ROOT_ROTATION_KEY: {
                    "camera_forward": 0.0,
                    "camera_right": 0.0,
                    "camera_up": 3.0,
                },
                "Bone_A": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
        }
        copy_joints_keep_dest_root(poses, dest_frame=9, src_frame=8)
        self.assertEqual(poses[9]["Bone_A"]["x"], 45.0)
        self.assertEqual(poses[9][MOTION_ROOT_KEY]["forward"], 0.5)
        self.assertEqual(poses[9][MOTION_ROOT_ROTATION_KEY]["camera_up"], 3.0)

    def test_substantial_keep_rejects_tiny_leftover_ticks(self) -> None:
        before = OccupancyFractions(
            leftover=0.20, extra=0.10, sprite_pixels=100, leftover_pixels=20, extra_pixels=10
        )
        tiny = OccupancyFractions(
            leftover=0.199999, extra=0.10, sprite_pixels=100, leftover_pixels=20, extra_pixels=10
        )
        better = OccupancyFractions(
            leftover=0.16, extra=0.11, sprite_pixels=100, leftover_pixels=16, extra_pixels=11
        )
        extra_explodes = OccupancyFractions(
            leftover=0.16, extra=0.20, sprite_pixels=100, leftover_pixels=16, extra_pixels=20
        )
        self.assertGreaterEqual(SUBSTANTIAL_LEFTOVER_DROP, 0.004)
        self.assertFalse(substantial_occupancy_better(before, tiny))
        self.assertTrue(substantial_occupancy_better(before, better))
        self.assertFalse(substantial_occupancy_better(before, extra_explodes))
        self.assertTrue(occupancy_collision_unacceptable(before, extra_explodes))
        self.assertFalse(occupancy_collision_unacceptable(before, better))
        self.assertFalse(
            leftover_trial_illegal(before, better, seed_strain=0.12, trial_strain=0.13)
        )
        self.assertTrue(
            leftover_trial_illegal(before, better, seed_strain=0.12, trial_strain=0.20)
        )
        self.assertFalse(
            substantial_occupancy_better(
                before, better, before_strain=0.12, after_strain=0.20
            )
        )
        self.assertTrue(
            substantial_occupancy_better(
                before, better, before_strain=0.12, after_strain=0.13
            )
        )

    def test_coarse_combos_are_combined_axes_small_first(self) -> None:
        combos = temporal_coarse_combos()
        self.assertEqual(TEMPORAL_COARSE_MAGNITUDES_DEG, (45.0, 90.0))
        self.assertIn((45.0, 45.0, 45.0), combos)
        self.assertIn((90.0, -45.0, 45.0), combos)
        self.assertNotIn((0.0, 0.0, 0.0), combos)
        first = combos[0]
        self.assertEqual(max(abs(value) for value in first), 45.0)
        self.assertEqual(sum(1 for value in first if abs(value) > 1e-9), 1)
        forty_five = [combo for combo in combos if max(abs(value) for value in combo) == 45.0]
        ninety = [combo for combo in combos if max(abs(value) for value in combo) == 90.0]
        self.assertEqual(combos[: len(forty_five)], tuple(forty_five))
        self.assertTrue(ninety)
        self.assertLess(len(forty_five), len(combos))

    def test_collision_bound_prunes_further_same_axes_only(self) -> None:
        self.assertTrue(combo_beyond_collision_bound((90.0, 0.0, 0.0), (45.0, 0.0, 0.0)))
        self.assertFalse(combo_beyond_collision_bound((45.0, 45.0, 0.0), (45.0, 0.0, 0.0)))
        self.assertFalse(combo_beyond_collision_bound((45.0, 45.0, 45.0), (45.0, 45.0, 0.0)))
        self.assertTrue(combo_beyond_collision_bound((90.0, 45.0, 45.0), (45.0, 45.0, 45.0)))
        self.assertFalse(combo_beyond_collision_bound((45.0, 0.0, 0.0), (45.0, 0.0, 0.0)))
        self.assertTrue(
            combo_pruned_by_collision_bounds((90.0, 45.0, 0.0), ((45.0, 45.0, 0.0),))
        )
        self.assertFalse(
            combo_pruned_by_collision_bounds((45.0, 45.0, 45.0), ((45.0, 45.0, 0.0),))
        )

    def test_inertial_seed_uses_velocity_and_acceleration(self) -> None:
        from sprite_body_surgery import MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY

        self.assertEqual(predict_channel_inertial((10.0,)), 10.0)
        self.assertEqual(predict_channel_inertial((10.0, 14.0)), 18.0)
        self.assertEqual(predict_channel_inertial((10.0, 14.0, 20.0)), 28.0)
        self.assertEqual(max(abs(step) for step in TEMPORAL_FINE_STEPS_DEG), 15.0)
        poses = {
            8: {
                MOTION_ROOT_KEY: {"forward": 0.1, "lateral": 0.0, "vertical": 0.0},
                "Bone_A": {"x": 10.0, "y": 0.0, "z": 0.0},
            },
            9: {
                MOTION_ROOT_KEY: {"forward": 0.2, "lateral": 0.0, "vertical": 0.0},
                "Bone_A": {"x": 14.0, "y": 0.0, "z": 0.0},
            },
            10: {
                MOTION_ROOT_KEY: {"forward": 0.3, "lateral": 0.0, "vertical": 0.0},
                MOTION_ROOT_ROTATION_KEY: {
                    "camera_forward": 0.0,
                    "camera_right": 0.0,
                    "camera_up": 4.0,
                },
                "Bone_A": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
        }
        seed_frame_from_inertial(
            poses, dest_frame=10, history_frames=(8, 9), joint_limit_deg=150.0
        )
        self.assertEqual(poses[10]["Bone_A"]["x"], 18.0)
        self.assertEqual(poses[10][MOTION_ROOT_KEY]["forward"], 0.3)
        self.assertEqual(poses[10][MOTION_ROOT_ROTATION_KEY]["camera_up"], 4.0)
        later = {
            8: {"Bone_A": {"x": 10.0, "y": 0.0, "z": 0.0}},
            9: {"Bone_A": {"x": 14.0, "y": 0.0, "z": 0.0}},
            10: {"Bone_A": {"x": 20.0, "y": 0.0, "z": 0.0}},
            11: {
                MOTION_ROOT_KEY: {"forward": 9.0, "lateral": 0.0, "vertical": 0.0},
                "Bone_A": {"x": 0.0, "y": 0.0, "z": 0.0},
            },
        }
        seed_frame_from_inertial(
            later, dest_frame=11, history_frames=(8, 9, 10), joint_limit_deg=150.0
        )
        self.assertEqual(later[11]["Bone_A"]["x"], 28.0)
        self.assertEqual(later[11][MOTION_ROOT_KEY]["forward"], 9.0)

    def test_pipeline_relative_seed_is_dest_minus_reference(self) -> None:
        from sprite_body_surgery import MOTION_ROOT_KEY

        pipeline = {
            8: {"Bone_A": {"x": 10.0, "y": 4.0, "z": 0.0}},
            15: {"Bone_A": {"x": 40.0, "y": 4.0, "z": 6.0}},
        }
        dest = {
            15: {
                MOTION_ROOT_KEY: {"forward": 1.5, "lateral": 0.0, "vertical": 0.0},
                "Bone_A": {"x": 0.0, "y": 0.0, "z": 0.0},
            }
        }
        seed_frame_pipeline_relative(
            dest,
            pipeline,
            dest_frame=15,
            reference_frame=8,
            joint_limit_deg=150.0,
        )
        self.assertEqual(dest[15]["Bone_A"]["x"], 30.0)
        self.assertEqual(dest[15]["Bone_A"]["y"], 0.0)
        self.assertEqual(dest[15]["Bone_A"]["z"], 6.0)
        self.assertEqual(dest[15][MOTION_ROOT_KEY]["forward"], 1.5)

    def test_after_poses_require_degrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "after_poses.json"
            write_after_poses(
                dest,
                {0: {"Bone_A": {"x": 1.0, "y": 0.0, "z": 0.0}}},
                frame_indices=(0,),
                camera_fit_path=dest,
            )
            payload = json.loads(dest.read_text(encoding="utf-8"))
            require_pose_units_degrees(payload, source=str(dest))

    def test_camera_fit_write_uses_candidate_yaw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "seed.json"
            seed.write_text(
                json.dumps(
                    {
                        "sourceResolution": [100, 100],
                        "basisScreenRows": [[1, 0, 0], [0, -1, 0]],
                        "pxPerWorld": 10.0,
                        "screenOffsetPx": [50.0, 50.0],
                        "profileMetrics": {},
                    }
                ),
                encoding="utf-8",
            )
            dest = Path(tmp) / "after.json"
            write_camera_fit_from_candidate(
                seed,
                dest,
                {
                    "yawDeg": 0.0,
                    "rollDeg": -8.0,
                    "facingScore": 0.827,
                    "right": [0.0, 0.0, 1.0],
                    "down": [0.0, -1.0, 0.0],
                    "pxPerWorld": [10.0, 10.0],
                    "screenOffsetPx": [50.0, 50.0],
                    "score": 0.9,
                    "iou": 0.6,
                },
                source_resolution=(100, 100),
            )
            data = json.loads(dest.read_text(encoding="utf-8"))
            self.assertEqual(data["profileMetrics"]["bestYawDeg"], 0.0)
            self.assertEqual(data["cameraPolicy"], "sprite_feasibility_camera_surgery")

    def test_rotate_bone_deg_and_rebind(self) -> None:
        poses = {0: {"Bone_A": {"x": 10.0, "y": 0.0, "z": 0.0}}}
        rotate_bone_deg(poses, joint="Bone_A", frames=(0,), axis="x", delta_deg=5.0, joint_limit_deg=150.0)
        self.assertAlmostEqual(poses[0]["Bone_A"]["x"], 15.0)
        with self.assertRaises(ValueError):
            rotate_bone_deg(poses, joint="Bone_A", frames=(0,), axis="x", delta_deg=200.0, joint_limit_deg=150.0)
        near_limit = {0: {"Bone_A": {"x": -135.0, "y": 0.0, "z": 0.0}}}
        applied = rotate_bone_deg_within_limit(
            near_limit,
            joint="Bone_A",
            frames=(0,),
            axis="x",
            delta_deg=-30.0,
            joint_limit_deg=150.0,
        )
        self.assertAlmostEqual(applied, -15.0)
        self.assertAlmostEqual(near_limit[0]["Bone_A"]["x"], -150.0)
        with tempfile.TemporaryDirectory() as tmp:
            path = write_minimal_skinned_glb(Path(tmp) / "bar.glb")
            doc, blob = load_glb(path)
            target = node_index_by_name(doc, "Bone_A")
            report = rebind_vertices_to_joint(doc, blob, vertex_indices=(0, 2), target_node=target)
            out = Path(tmp) / "rebind.glb"
            save_glb(out, doc, blob)
            validate_skinned_glb(out)
            self.assertEqual(report["vertexCount"], 2)
            self.assertEqual(report["parentSlot"], 0)

    def test_normalize_skin_weights_repairs_sum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_minimal_skinned_glb(Path(tmp) / "bar.glb")
            doc, blob = load_glb(path)
            _mesh_i, _prim_i, prim = first_skinned_primitive(doc)
            weights = _accessor_array(doc, blob, int(prim["attributes"]["WEIGHTS_0"])).astype(np.float32)
            weights[0] = (0.2, 0.2, 0.0, 0.0)
            _write_accessor(doc, blob, int(prim["attributes"]["WEIGHTS_0"]), weights)
            report = normalize_skin_weights(doc, blob)
            self.assertGreaterEqual(report["fixedVertices"], 1)
            repaired = _accessor_array(doc, blob, int(prim["attributes"]["WEIGHTS_0"]))
            self.assertAlmostEqual(float(repaired[0].sum()), 1.0, places=5)

    def test_rotate_root_and_nested_clone(self) -> None:
        poses = {
            0: {
                "Bone_A": {"x": 10.0, "y": 0.0, "z": 0.0},
                "__motion_root_rotation__": {"camera_forward": 0.0, "camera_right": 0.0, "camera_up": 5.0},
                "__motion_root__": {"forward": 0.1, "lateral": 0.0, "vertical": 0.0},
            }
        }
        cloned = clone_pose_map(poses)
        cloned[0]["Bone_A"]["x"] = 99.0
        self.assertAlmostEqual(poses[0]["Bone_A"]["x"], 10.0)
        rotate_root_deg(poses, frames=(0,), axis="camera_up", delta_deg=10.0, limit_deg=90.0)
        self.assertAlmostEqual(poses[0]["__motion_root_rotation__"]["camera_up"], 15.0)
        bind = bind_like_poses(poses, (0,))
        self.assertNotIn("Bone_A", bind[0])
        self.assertAlmostEqual(bind[0]["__motion_root__"]["forward"], 0.1)


class AnatomyCatalogTests(unittest.TestCase):
    def test_roc_catalog_labels_tail_head_and_ventral(self) -> None:
        from sprite_anatomy import anatomy_visual_body_chain

        catalog = load_unit_anatomy_catalog("h3_roc")
        names = ["Bone_000", "Bone_001", "Bone_012", "Bone_014"]
        self.assertEqual(anatomy_visual_body_chain(catalog, names), ["Bone_012", "Bone_014"])
        np.testing.assert_allclose(anatomy_ventral_bind_axis(catalog), (0.0, 0.0, 1.0))
        self.assertIn("Bone_001", anatomy_attitude_bones(catalog, ["Bone_000", "Bone_001", "Bone_012"]))
        from sprite_anatomy import anatomy_wing_chain, anatomy_bilateral_wing_pair

        self.assertEqual(
            anatomy_wing_chain(
                catalog,
                "wing_a",
                ["Bone_019", "Bone_018", "Bone_017", "Bone_022"],
            ),
            ["Bone_019", "Bone_018", "Bone_017"],
        )
        self.assertEqual(anatomy_bilateral_wing_pair(catalog), ("wing_a", "wing_b"))
        from sprite_anatomy import anatomy_bilateral_pairs, tpose_pole_for_pair

        self.assertEqual(anatomy_bilateral_pairs(catalog)[1], ("leg_a", "leg_b"))
        self.assertEqual(tpose_pole_for_pair("leg_a", "leg_b"), "ventral")

    def test_hobgoblin_catalog_labels_weapon_and_head(self) -> None:
        catalog = load_unit_anatomy_catalog("h3_hobgoblin")
        self.assertEqual(catalog["landmarks"]["weaponTip"], "Bone_029")
        self.assertEqual(catalog["landmarks"]["head"], "Bone_004")
        self.assertIn("hood", catalog["openUnknowns"])

    def test_unknown_unit_fails_closed(self) -> None:
        with self.assertRaises(ValueError):
            load_unit_anatomy_catalog("h3_not_a_unit")


class BilateralAxesTests(unittest.TestCase):
    def _frame(self) -> dict[str, np.ndarray]:
        return {
            "lateral": np.array((1.0, 0.0, 0.0), dtype=np.float64),
            "spine": np.array((0.0, 1.0, 0.0), dtype=np.float64),
            "ventral": np.array((0.0, 0.0, 1.0), dtype=np.float64),
        }

    def test_anatomical_copy_raises_both_wings(self) -> None:
        from sprite_bilateral_axes import (
            axis_angle_deg_to_matrix,
            bone_anatomical_axes,
            copy_anatomical_delta,
            local_from_world_axis_angle,
        )

        identity = np.eye(3, dtype=np.float64)
        frame = self._frame()
        dir_a = np.array((-1.0, 0.0, 0.0), dtype=np.float64)
        dir_b = np.array((1.0, 0.0, 0.0), dtype=np.float64)
        dorsal = np.array((0.0, 0.0, -1.0), dtype=np.float64)
        axes_a = bone_anatomical_axes(dir_a, frame)
        delta_a = local_from_world_axis_angle(axes_a["raise"] * 20.0, identity)
        delta_b = copy_anatomical_delta(delta_a, identity, identity, dir_a, dir_b, frame)
        posed_a = axis_angle_deg_to_matrix(delta_a) @ dir_a
        posed_b = axis_angle_deg_to_matrix(delta_b) @ dir_b
        self.assertGreater(float(np.dot(posed_a, dorsal)), float(np.dot(dir_a, dorsal)))
        self.assertGreater(float(np.dot(posed_b, dorsal)), float(np.dot(dir_b, dorsal)))
        copied = np.asarray(delta_a, dtype=np.float64)
        self.assertGreater(float(np.linalg.norm(np.asarray(delta_b) - copied)), 1.0)

    def test_anatomical_copy_round_trip(self) -> None:
        from sprite_bilateral_axes import copy_anatomical_delta

        identity = np.eye(3, dtype=np.float64)
        frame = self._frame()
        dir_a = np.array((-1.0, 0.2, 0.0), dtype=np.float64)
        dir_b = np.array((1.0, 0.2, 0.0), dtype=np.float64)
        source = np.array((12.0, -40.0, 7.0), dtype=np.float64)
        once = copy_anatomical_delta(source, identity, identity, dir_a, dir_b, frame)
        twice = copy_anatomical_delta(once, identity, identity, dir_b, dir_a, frame)
        np.testing.assert_allclose(twice, source, atol=1e-5)

    def test_roc_catalog_builds_a_model_frame(self) -> None:
        from sprite_bilateral_axes import model_bind_frame

        catalog = load_unit_anatomy_catalog("h3_roc")
        origins = {
            "Bone_012": np.array((-1.0, 0.0, 0.0), dtype=np.float64),
            "Bone_014": np.array((1.0, 0.0, 0.0), dtype=np.float64),
        }
        frame = model_bind_frame(catalog, origins)
        np.testing.assert_allclose(np.linalg.norm(frame["lateral"]), 1.0, atol=1e-9)
        np.testing.assert_allclose(
            np.dot(frame["lateral"], frame["spine"]), 0.0, atol=1e-9
        )


class ContractValidatorTests(unittest.TestCase):
    def test_write_path_contract_validator(self) -> None:
        import sys

        tools = Path(r"V:/Games/Olden Era Playtest Tweak/tools")
        if str(tools) not in sys.path:
            sys.path.insert(0, str(tools))
        from validate_sprite_feasibility_surgery_contract import validate

        validate()


if __name__ == "__main__":
    raise SystemExit(unittest.main())
