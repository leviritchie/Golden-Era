from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "experiments" / "homm3_mocap_v2"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from server import parse_selection, selection_id, _list_units, _variant_title  # noqa: E402
from schema import (  # noqa: E402
    SCHEMA,
    CleanupCandidateError,
    apply_bone_length_offsets,
    apply_edits,
    apply_points,
    brush_target_weight,
    compose_similarity,
    nearest_segment_weights,
    outgoing_segment_distances,
    apply_skin_rules,
    default_skin_rules,
    skin_rules_from_payload,
    rewrite_weights_from_bind,
    shift_chain_weights,
    identity_skeleton_delta,
    new_candidate,
    packed_set_weight,
    packed_trim_influence,
    set_vertex_weight,
    trim_vertex_influence,
    validate_candidate,
)
from static_bind_registration import apply_similarity, rotation_matrix  # noqa: E402


class CleanupListingTests(unittest.TestCase):
    def test_parse_selection_keeps_official_id(self) -> None:
        self.assertEqual(parse_selection("h3_ancient_behemoth"), ("h3_ancient_behemoth", "linked_master"))
        self.assertEqual(
            parse_selection("h3_ancient_behemoth@linked_master_lengthbind"),
            ("h3_ancient_behemoth", "linked_master_lengthbind"),
        )
        self.assertEqual(selection_id("h3_ancient_behemoth", "linked_master"), "h3_ancient_behemoth")

    def test_lists_named_bind_versions_for_one_creature(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            official = root / "h3_ancient_behemoth" / "linked_master"
            previous = root / "h3_ancient_behemoth" / "linked_master_lengthbind"
            hidden = root / "h3_ancient_behemoth" / "linked_master_bindfirst"
            for folder in (official, previous, hidden):
                (folder / "capture_bind").mkdir(parents=True)
                (folder / "clips").mkdir(parents=True)
                (folder / "capture_bind" / "h3_ancient_behemoth_linked_master_bind.glb").write_bytes(b"glb")
                (folder / "clips" / "Unit_Idle.glb").write_bytes(b"clip")
            (official / "idle0_registration.json").write_text(
                json.dumps({"views": {"candidates": [{"skeletonSimilarity": {"fit": "idle0_bind_first_inside_mesh"}}]}}),
                encoding="utf-8",
            )
            rows = _list_units(root)
            ids = [row["id"] for row in rows]
            self.assertEqual(ids, ["h3_ancient_behemoth", "h3_ancient_behemoth@linked_master_lengthbind"])
            self.assertEqual(rows[0]["label"], "h3_ancient_behemoth — bind-first (current)")
            self.assertEqual(rows[1]["label"], "h3_ancient_behemoth — previous length-only")
            self.assertEqual(
                _variant_title(
                    "h3_ancient_behemoth",
                    "linked_master_floor",
                    official / "idle0_registration.json",
                    has_siblings=True,
                ),
                "h3_ancient_behemoth — floor column (feet on mesh bottom)",
            )
            self.assertEqual(
                _variant_title(
                    "h3_ancient_behemoth",
                    "linked_master_ground",
                    official / "idle0_registration.json",
                    has_siblings=True,
                ),
                "h3_ancient_behemoth — ground + height only (no bone moves)",
            )
            self.assertEqual(
                _variant_title(
                    "h3_ancient_behemoth",
                    "linked_master_scale",
                    official / "idle0_registration.json",
                    has_siblings=True,
                ),
                "h3_ancient_behemoth — yaw-fix + scale slider (hips stay)",
            )
            self.assertEqual(
                _variant_title(
                    "h3_angel",
                    "linked_master_hybrid_scale",
                    official / "idle0_registration.json",
                    has_siblings=True,
                ),
                "h3_angel — Mixamo body + Eagle wings (scale)",
            )


class CleanupSchemaTests(unittest.TestCase):
    def test_identity_delta_leaves_points(self) -> None:
        points = np.asarray([[1.0, 2.0, 3.0], [0.0, 0.0, 1.0]], dtype=np.float64)
        np.testing.assert_allclose(apply_points(points, identity_skeleton_delta()), points)

    def test_yaw_then_translate_matches_pipeline_similarity(self) -> None:
        points = np.asarray([[1.0, 0.0, 0.0]], dtype=np.float64)
        delta = {
            "yawDeg": 90.0,
            "pitchDeg": 0.0,
            "rollDeg": 0.0,
            "scale": 2.0,
            "translation": [0.0, 1.0, 0.0],
        }
        got = apply_points(points, delta)
        want = apply_similarity(
            points,
            rotation=rotation_matrix(90.0, 0.0, 0.0),
            scale=2.0,
            translation=np.asarray([0.0, 1.0, 0.0]),
        )
        np.testing.assert_allclose(got, want, atol=1e-12)
        np.testing.assert_allclose(got, [[0.0, 1.0, -2.0]], atol=1e-12)

    def test_compose_applies_delta_after_base(self) -> None:
        points = np.asarray([[1.0, 0.0, 0.0]], dtype=np.float64)
        base = {
            "rotation": rotation_matrix(0.0, 0.0, 0.0),
            "scale": 2.0,
            "translation": np.asarray([1.0, 0.0, 0.0]),
        }
        delta = identity_skeleton_delta()
        delta["translation"] = [0.0, 3.0, 0.0]
        composed = compose_similarity(base, delta)
        got = apply_similarity(
            points,
            rotation=composed["rotation"],
            scale=composed["scale"],
            translation=composed["translation"],
        )
        mid = apply_similarity(
            points,
            rotation=base["rotation"],
            scale=base["scale"],
            translation=base["translation"],
        )
        want = apply_points(mid, delta)
        np.testing.assert_allclose(got, want, atol=1e-12)

    def test_weight_set_renormalizes(self) -> None:
        names = ["mixamorig:Hips", "mixamorig:LeftArm"]
        weights = np.asarray([[0.5, 0.5]], dtype=np.float64)
        out = set_vertex_weight(weights, names, vertex=0, bone="mixamorig:LeftArm", value=0.0)
        np.testing.assert_allclose(out, [[1.0, 0.0]])

    def test_trim_refuses_empty_row(self) -> None:
        names = ["mixamorig:Hips"]
        weights = np.asarray([[1.0]], dtype=np.float64)
        with self.assertRaises(CleanupCandidateError):
            trim_vertex_influence(weights, names, vertex=0, bone="mixamorig:Hips")

    def test_packed_trim_and_replace_weakest(self) -> None:
        joints = np.asarray([0, 1, 2, 3], dtype=np.int64)
        weights = np.asarray([0.7, 0.2, 0.09, 0.01], dtype=np.float64)
        new_j, new_w = packed_trim_influence(joints, weights, bone_index=1)
        self.assertEqual(new_j.tolist(), [0, 1, 2, 3])
        np.testing.assert_allclose(new_w.sum(), 1.0)
        self.assertEqual(new_w[1], 0.0)
        set_j, set_w = packed_set_weight(joints, weights, bone_index=7, value=0.5, joint_count=8)
        self.assertEqual(int(set_j[3]), 7)
        np.testing.assert_allclose(set_w.sum(), 1.0)

    def test_candidate_refuses_self_accept_and_unknown_op(self) -> None:
        source = {
            "bindGlb": "bind.glb",
            "bindSha256": "abc",
            "registration": "reg.json",
            "registrationSha256": "def",
            "clip": "Unit_Idle",
        }
        ok = new_candidate(unit="h3_amalek", source=source)
        self.assertEqual(ok["schema"], SCHEMA)
        self.assertFalse(ok["accepted"])
        self.assertIn("bind_offset_length_scale", ok["opsOwned"])
        with self.assertRaises(CleanupCandidateError):
            new_candidate(unit="h3_amalek", source=source, weight_follow_joints=True)
        with self.assertRaises(CleanupCandidateError):
            new_candidate(unit="h3_amalek", source=source, weight_rewrite_from_bind=True)
        followed = new_candidate(
            unit="h3_amalek",
            source=source,
            bone_lengths={"mixamorig:LeftArm": 1.25},
            weight_follow_joints=True,
            weight_override={"joints": [[0, 1]], "weights": [[0.75, 0.25]]},
        )
        self.assertEqual(followed["boneLengths"]["mixamorig:LeftArm"], 1.25)
        self.assertTrue(followed["weightFollowJoints"])
        rewritten = new_candidate(
            unit="h3_amalek",
            source=source,
            weight_rewrite_from_bind=True,
            weight_override={"joints": [[1, 2]], "weights": [[0.6, 0.4]]},
        )
        self.assertTrue(rewritten["weightRewriteFromBind"])
        self.assertIn("bind_proximity_weight_rewrite", rewritten["opsOwned"])
        bad = dict(ok)
        bad["accepted"] = True
        with self.assertRaises(CleanupCandidateError):
            validate_candidate(bad)
        worse = dict(ok)
        worse["edits"] = [{"op": "apply_pose_as_rest", "vertex": 0, "bone": "mixamorig:Hips"}]
        with self.assertRaises(CleanupCandidateError):
            validate_candidate(worse)

    def test_bone_length_keeps_translation_delta(self) -> None:
        bind = np.asarray([[0.0, 1.0, 0.0], [0.0, 0.5, 0.0]], dtype=np.float64)
        current = bind + np.asarray([[0.1, 0.0, 0.0], [0.0, 0.0, 0.0]], dtype=np.float64)
        got = apply_bone_length_offsets(bind, current, np.asarray([2.0, 1.0]))
        np.testing.assert_allclose(got, [[0.1, 2.0, 0.0], [0.0, 0.5, 0.0]])
        with self.assertRaises(CleanupCandidateError):
            apply_bone_length_offsets(bind, current, np.asarray([0.0, 1.0]))

    def test_chain_weight_follow_preserves_chain_mass(self) -> None:
        vertices = np.asarray([[0.0, 2.2, 0.0]], dtype=np.float64)
        old_joints = np.asarray([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 2.0, 0.0]], dtype=np.float64)
        new_joints = np.asarray([[0.0, 0.0, 0.0], [0.0, 1.5, 0.0], [0.0, 3.0, 0.0]], dtype=np.float64)
        parents = np.asarray([-1, 0, 1], dtype=np.int64)
        old_w = nearest_segment_weights(outgoing_segment_distances(vertices, old_joints, parents), k=3)
        new_prox = nearest_segment_weights(outgoing_segment_distances(vertices, new_joints, parents), k=3)
        shifted = shift_chain_weights(old_w, new_prox, [0, 1, 2])
        np.testing.assert_allclose(shifted.sum(axis=1), 1.0, atol=1e-12)
        np.testing.assert_allclose(shifted[0].sum(), old_w[0].sum())
        self.assertGreater(shifted[0, 1], old_w[0, 1])

    def test_rewrite_weights_from_bind_replaces_all_rows(self) -> None:
        vertices = np.asarray([[0.0, 2.0, 0.0], [0.0, 0.0, 0.0]], dtype=np.float64)
        joints = np.asarray([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 2.0, 0.0]], dtype=np.float64)
        parents = np.asarray([-1, 0, 1], dtype=np.int64)
        old = np.asarray([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)
        rewritten = rewrite_weights_from_bind(vertices, joints, parents, k=3)
        np.testing.assert_allclose(rewritten.sum(axis=1), 1.0, atol=1e-12)
        self.assertGreater(rewritten[0, 1] + rewritten[0, 2], rewritten[0, 0])
        self.assertGreater(rewritten[1, 0], rewritten[1, 2])
        self.assertFalse(np.allclose(rewritten, old))

    def test_skin_rules_exclude_and_falloff_change_assignment(self) -> None:
        vertices = np.asarray([[0.35, 1.15, 0.0]], dtype=np.float64)
        joints = np.asarray([[0.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 2.0, 0.0]], dtype=np.float64)
        parents = np.asarray([-1, 0, 1], dtype=np.int64)
        names = ["root", "mid", "tip"]
        full = apply_skin_rules(vertices, joints, parents, names, {"k": 3, "distance": "euclidean"})
        excluded = apply_skin_rules(
            vertices,
            joints,
            parents,
            names,
            {"k": 3, "distance": "euclidean", "excludedBones": ["tip"]},
        )
        self.assertEqual(excluded[0, 2], 0.0)
        self.assertGreater(full[0, 2], 0.0)
        inverse = apply_skin_rules(
            vertices,
            joints,
            parents,
            names,
            {"k": 3, "distance": "euclidean", "falloff": "inverse"},
        )
        self.assertGreater(abs(float(full[0, 1] - inverse[0, 1])), 1e-6)
        marks: list[float] = []
        apply_skin_rules(
            vertices,
            joints,
            parents,
            names,
            {"k": 3, "distance": "euclidean"},
            progress=lambda fraction, _message: marks.append(fraction),
        )
        self.assertGreaterEqual(marks[-1], 1.0)
        incoming = apply_skin_rules(
            vertices,
            joints,
            parents,
            names,
            {"k": 3, "distance": "euclidean", "ownership": "incoming"},
        )
        self.assertFalse(np.allclose(full, incoming))
        shaft = np.asarray([[0.0, 0.0, 0.0], [0.5, 0.05, 0.0], [1.0, 0.05, 0.0]], dtype=np.float64)
        leaf_joints = np.asarray([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]], dtype=np.float64)
        leaf_parents = np.asarray([-1, 0], dtype=np.int64)
        leaf_dist = outgoing_segment_distances(shaft, leaf_joints, leaf_parents)
        self.assertLess(leaf_dist[2, 1], leaf_dist[2, 0])
        self.assertLess(leaf_dist[1, 0], leaf_dist[1, 1])
        with self.assertRaises(CleanupCandidateError):
            apply_skin_rules(vertices, joints, parents, names, {"falloff": "heat"})
        self.assertEqual(default_skin_rules()["distance"], "euclidean")
        ok = new_candidate(
            unit="h3_amalek",
            source={
                "bindGlb": "bind.glb",
                "bindSha256": "abc",
                "registration": "reg.json",
                "registrationSha256": "def",
                "clip": "Unit_Idle",
            },
            skin_rules={"preset": "pipeline_initializer", "distance": "geodesic", "k": 3},
        )
        self.assertEqual(ok["skinRules"]["distance"], "geodesic")
        self.assertEqual(ok["skinRules"]["connectionPolicy"], "all_edges")
        self.assertIn("bind_skin_rules", ok["opsOwned"])
        narrow = skin_rules_from_payload({"skinRules": {"preset": "surface_ignore_narrow"}})
        self.assertEqual(narrow["distance"], "geodesic")
        self.assertEqual(narrow["connectionPolicy"], "drop_narrow_incidental")
        custom_geo = skin_rules_from_payload({"skinRules": {"distance": "geodesic"}})
        self.assertEqual(custom_geo["connectionPolicy"], "drop_narrow_incidental")
        with self.assertRaises(CleanupCandidateError):
            skin_rules_from_payload({"skinRules": {"connectionPolicy": "heat"}})

    def test_brush_modes(self) -> None:
        self.assertAlmostEqual(brush_target_weight(0.2, mode="add", strength=0.5, falloff=1.0), 0.7)
        self.assertAlmostEqual(brush_target_weight(0.2, mode="subtract", strength=0.5, falloff=0.5), 0.0)
        self.assertAlmostEqual(brush_target_weight(0.0, mode="replace", strength=1.0, falloff=1.0, replace_value=0.8), 0.8)
        with self.assertRaises(CleanupCandidateError):
            brush_target_weight(0.2, mode="smooth", strength=1.0, falloff=1.0)

    def test_apply_edits_replays_in_order(self) -> None:
        names = ["mixamorig:Hips", "mixamorig:LeftArm", "mixamorig:Head"]
        weights = np.asarray([[0.5, 0.4, 0.1]], dtype=np.float64)
        out = apply_edits(
            weights,
            names,
            [
                {"op": "influence_trim", "vertex": 0, "bone": "mixamorig:Head"},
                {"op": "weight_set", "vertex": 0, "bone": "mixamorig:LeftArm", "value": 0.25},
            ],
        )
        np.testing.assert_allclose(out.sum(axis=1), [1.0])
        self.assertGreater(out[0, 0], out[0, 1])
        self.assertEqual(out[0, 2], 0.0)


if __name__ == "__main__":
    unittest.main()
