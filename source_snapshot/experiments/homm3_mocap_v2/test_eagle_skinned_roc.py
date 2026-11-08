"""Mapping, transfer fail-closed, and hash tests for the Eagle-skinned Roc copy."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))

from barycentric_transfer import UnmatchedCorrespondenceError, transfer_weights
from donor_eagle import (
    REGION_JOINTS,
    bind_world_matrices,
    compute_rest_joints,
    inverse_bind_matrices,
    joint_region_ids,
    load_donor_package,
    region_for_joint,
)
from pin import sha256_file
from roc_copy import ROC_REGION_BONES, ROC_TO_EAGLE_LANDMARKS, roc_to_eagle_bones
from shared_camera import freeze_shared_camera, project_view
from vendor_reference import completeness_report, refuse_skeleton_mutation


class MappingCoverageTests(unittest.TestCase):
    def test_json_chunk_padding_uses_spaces(self):
        from eagle_glb import _pad_json4
        for length in range(1, 9):
            padded = _pad_json4(b"x" * length)
            self.assertEqual(len(padded) % 4, 0)
            self.assertNotIn(b"\x00", padded)

    @classmethod
    def setUpClass(cls) -> None:
        cls.donor = load_donor_package()
        cls.names = cls.donor["captureSkeleton"]["jointNames"]

    def test_every_capture_joint_has_a_region(self) -> None:
        mapped = joint_region_ids(self.names)
        self.assertEqual(len(mapped), 50)
        self.assertEqual(set(mapped), set(REGION_JOINTS))

    def test_missing_branch_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            region_for_joint("BN_NotABranch")

    def test_left_right_landmark_sides_are_not_swapped(self) -> None:
        pairs = dict(ROC_TO_EAGLE_LANDMARKS)
        self.assertEqual(pairs["Bone_022"], "BN_Wing_L_01")
        self.assertEqual(pairs["Bone_019"], "BN_Wing_R_01")
        self.assertEqual(pairs["Bone_020"], "BN_Wing_L_04")
        self.assertEqual(pairs["Bone_017"], "BN_Wing_R_04")
        self.assertEqual(pairs["Bone_004"], "Bip01_L_Foot")
        self.assertEqual(pairs["Bone_008"], "Bip01_R_Foot")
        self.assertNotEqual(pairs["Bone_022"], pairs["Bone_019"])

    def test_roc_regions_cover_the_smart_rig_init_bones(self) -> None:
        listed = {bone for bones in ROC_REGION_BONES.values() for bone in bones}
        self.assertIn("Bone_014", listed)
        self.assertIn("Bone_019", listed)
        self.assertIn("Bone_022", listed)
        self.assertIn("Bone_012", listed)
        self.assertIn("Bone_013", listed)

    def test_tail_and_head_are_in_the_articulated_bone_map(self) -> None:
        mapped = roc_to_eagle_bones()
        self.assertEqual(mapped["Bone_012"], "BN_Tai_R_02")
        self.assertEqual(mapped["Bone_013"], "BN_Tai_01")
        self.assertEqual(mapped["Bone_014"], "Bip01_Head")
        self.assertNotIn("REGION_LANDMARKS", dir(__import__("roc_copy")))

    def test_incomplete_package_is_not_a_donor(self) -> None:
        report = completeness_report("zoo", "Eagle#Eagle-Landing/y30")
        self.assertFalse(report["complete"])

    def test_refusing_a_renamed_skeleton(self) -> None:
        with self.assertRaisesRegex(ValueError, "unmodified"):
            refuse_skeleton_mutation(original_names=self.names, pruned=True)
        with self.assertRaisesRegex(ValueError, "renamed"):
            refuse_skeleton_mutation(original_names=self.names, proposed_names=self.names[::-1])


class TransferFailClosedTests(unittest.TestCase):
    def test_unmatched_vertices_are_not_assigned_to_root(self) -> None:
        donor_v = np.array(((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)), dtype=np.float64)
        donor_faces = np.array(((0, 1, 2),), dtype=np.int64)
        donor_w = np.zeros((3, 50), dtype=np.float64)
        donor_w[:, 0] = 1.0
        names = load_donor_package()["captureSkeleton"]["jointNames"]
        roc_v = np.array(((10.0, 10.0, 10.0),), dtype=np.float64)
        roc_regions = np.array(["wing_left"], dtype=object)
        with self.assertRaises(UnmatchedCorrespondenceError) as ctx:
            transfer_weights(
                roc_vertices=roc_v,
                roc_regions=roc_regions,
                donor_vertices=donor_v,
                donor_faces=donor_faces,
                donor_weights=donor_w,
                donor_names=names,
            )
        self.assertEqual(ctx.exception.unmatched[0]["reason"], "no_donor_triangle_in_region")


class SharedCameraTests(unittest.TestCase):
    def test_refuses_per_panel_autofit_and_keeps_one_scale(self) -> None:
        points = np.array(((0.0, 0.0, 0.0), (1.0, 0.2, 0.4)), dtype=np.float64)
        cameras = freeze_shared_camera(points, width=100, height=100)
        self.assertFalse(cameras["perPanelAutofit"])
        xy = project_view(points, cameras, "front")
        self.assertEqual(xy.shape, (2, 2))
        cameras["perPanelAutofit"] = True
        with self.assertRaisesRegex(ValueError, "auto-fit"):
            project_view(points, cameras, "front")


class OriginalAssetHashTests(unittest.TestCase):
    def test_original_roc_hash_is_stable_in_this_process(self) -> None:
        from paths import MESHY

        path = MESHY / "h3_roc_smartrigged.glb"
        first = sha256_file(path)
        second = sha256_file(path)
        self.assertEqual(first, second)
        self.assertEqual(first, "f3644a01a07413441dd0081406e63c56c45ee70218d38e7a2a525864c67acf3a")


class BindGlbExportReloadTests(unittest.TestCase):
    def _payload(self) -> dict:
        names = ["Hips", "Spine"] + [f"Pad{index}" for index in range(6)]
        parents = np.asarray((-1, 0, 0, 0, 0, 0, 0, 0), dtype=np.int64)
        offsets = np.zeros((8, 3), dtype=np.float64)
        offsets[0] = (0.0, 0.260791, -0.024336)
        offsets[1] = (0.0, 0.10, 0.0)
        rest_local = np.repeat(np.eye(3, dtype=np.float64)[None], 8, axis=0)
        rest = compute_rest_joints(offsets, parents)
        bind = bind_world_matrices(offsets, parents)
        ibm = inverse_bind_matrices(bind)
        vertices = np.asarray(
            ((0.0, 0.26, 0.0), (0.05, 0.36, 0.0), (-0.05, 0.36, 0.0)),
            dtype=np.float64,
        )
        weights = np.zeros((3, 8), dtype=np.float64)
        weights[0, 0] = 1.0
        weights[1, 0] = 0.4
        weights[1, 1] = 0.6
        weights[2, 0] = 0.4
        weights[2, 1] = 0.6
        return {
            "names": names,
            "parents": parents,
            "offsets": offsets,
            "rest_local": rest_local,
            "rest": rest,
            "ibm": ibm,
            "vertices": vertices,
            "triangles": np.asarray(((0, 1, 2),), dtype=np.int64),
            "uvs": np.zeros((3, 2), dtype=np.float64),
            "weights": weights,
            "albedo": np.zeros((4, 4, 4), dtype=np.uint8),
        }

    def test_zeroed_root_translation_is_refused_at_export(self) -> None:
        from eagle_glb import write_skinned_glb

        payload = self._payload()
        rest_off = payload["offsets"].copy()
        rest_off[0] = 0.0
        dest = Path(r"V:/Games/Olden Era Playtest Tweak/artifacts/homm3_mocap_v2/eagle_skinned_roc/_reload_gate_tmp")
        dest.mkdir(parents=True, exist_ok=True)
        with self.assertRaisesRegex(ValueError, "bind origin"):
            write_skinned_glb(
                dest / "must_not_write.glb",
                names=payload["names"],
                parents=payload["parents"],
                rest_local_rotation=payload["rest_local"],
                rest_local_translation=rest_off,
                inverse_bind=payload["ibm"],
                vertices=payload["vertices"],
                triangles=payload["triangles"],
                uvs=payload["uvs"],
                albedo=payload["albedo"],
                weights=payload["weights"],
            )
        self.assertFalse((dest / "must_not_write.glb").exists())

    def test_bind_glb_own_rest_recovers_vertices(self) -> None:
        from eagle_glb import make_bind_skeleton, reload_and_compare, write_skinned_glb

        payload = self._payload()
        dest = Path(r"V:/Games/Olden Era Playtest Tweak/artifacts/homm3_mocap_v2/eagle_skinned_roc/_reload_gate_tmp")
        dest.mkdir(parents=True, exist_ok=True)
        glb = dest / "bind_roundtrip.glb"
        write_skinned_glb(
            glb,
            names=payload["names"],
            parents=payload["parents"],
            rest_local_rotation=payload["rest_local"],
            rest_local_translation=payload["offsets"],
            inverse_bind=payload["ibm"],
            vertices=payload["vertices"],
            triangles=payload["triangles"],
            uvs=payload["uvs"],
            albedo=payload["albedo"],
            weights=payload["weights"],
        )
        working = make_bind_skeleton(
            names=payload["names"],
            parents=payload["parents"],
            rest_world=payload["rest"],
            rest_local_rotation=payload["rest_local"],
            rest_local_translation=payload["offsets"],
            inverse_bind=payload["ibm"],
            vertices=payload["vertices"],
            triangles=payload["triangles"],
            uvs=payload["uvs"],
            weights=payload["weights"],
            albedo=payload["albedo"],
        )
        report = reload_and_compare(glb, working)
        self.assertLess(report["loadedOwnBindIdentityMax"], report["bindIdentityGate"])
        self.assertLess(report["workingOwnBindIdentityMax"], report["bindIdentityGate"])
        self.assertTrue(report["ok"])

    def test_rest_world_shortcut_does_not_hide_zeroed_root(self) -> None:
        from eagle_glb import make_bind_skeleton, own_bind_identity_gate

        payload = self._payload()
        rest_off = payload["offsets"].copy()
        rest_off[0] = 0.0
        working = make_bind_skeleton(
            names=payload["names"],
            parents=payload["parents"],
            rest_world=payload["rest"],
            rest_local_rotation=payload["rest_local"],
            rest_local_translation=rest_off,
            inverse_bind=payload["ibm"],
            vertices=payload["vertices"],
            triangles=payload["triangles"],
            uvs=payload["uvs"],
            weights=payload["weights"],
            albedo=payload["albedo"],
        )
        own = own_bind_identity_gate(working)
        self.assertGreater(own["loadedOwnBindIdentityMax"], own["bindIdentityGate"])

    def test_v1_candidate_fails_own_bind_gate(self) -> None:
        from eagle_glb import own_bind_identity_gate
        from glb_skeleton import load_bind_skeleton
        from paths import MOCAP_EAGLE_SKINNED

        glb = MOCAP_EAGLE_SKINNED / "preparation" / "eagle_skin_v1" / "roc_copy_eagle_bind.glb"
        loaded = load_bind_skeleton(glb)
        own = own_bind_identity_gate(loaded)
        self.assertGreater(own["loadedOwnBindIdentityMax"], own["bindIdentityGate"])

    def test_v2_bind_glb_passes_own_bind_gate(self) -> None:
        from eagle_glb import own_bind_identity_gate
        from glb_skeleton import load_bind_skeleton
        from paths import MOCAP_EAGLE_SKINNED

        glb = MOCAP_EAGLE_SKINNED / "preparation" / "eagle_skin_v2" / "roc_copy_eagle_bind.glb"
        loaded = load_bind_skeleton(glb)
        hips = next(index for index, name in enumerate(loaded.names) if name == "Hips")
        np.testing.assert_allclose(
            loaded.rest_local_translation[hips],
            (0.0, 0.260791, -0.024336),
            atol=1e-6,
        )
        own = own_bind_identity_gate(loaded)
        self.assertLess(own["loadedOwnBindIdentityMax"], own["bindIdentityGate"])


if __name__ == "__main__":
    unittest.main()
