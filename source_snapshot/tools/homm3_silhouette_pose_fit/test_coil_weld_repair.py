"""Coil-weld detect / authorship / fan-split tests."""
from __future__ import annotations

import math
import unittest

import numpy as np

from coil_weld_repair import (
    AUTHORING_METHOD,
    CoilWeldDetectSettings,
    apply_coil_weld_cuts,
    authorship_template,
    cut_source_faces_from_authorship,
    detect_coil_weld_clusters,
    geodesic_diameter_hops,
    parse_coil_weld_authorship,
    same_sheet_weld,
    split_nonmanifold_fans,
    unique_vertex_count,
    vertex_adjacency,
)


def _helical_tube(
    *,
    turns: float = 1.6,
    path_radius: float = 1.0,
    tube_radius: float = 0.14,
    pitch: float = 0.45,
    rings: int = 48,
    circle: int = 10,
) -> tuple[np.ndarray, np.ndarray]:
    if rings < 4 or circle < 4:
        raise ValueError("helical tube needs at least 4 rings and 4 circle verts")
    centers = []
    tangents = []
    for i in range(rings):
        t = (i / (rings - 1)) * turns * 2.0 * math.pi
        center = np.array(
            [path_radius * math.cos(t), path_radius * math.sin(t), pitch * t / (2.0 * math.pi)],
            dtype=np.float64,
        )
        tangent = np.array(
            [
                -path_radius * math.sin(t),
                path_radius * math.cos(t),
                pitch / (2.0 * math.pi),
            ],
            dtype=np.float64,
        )
        tangent /= np.linalg.norm(tangent)
        centers.append(center)
        tangents.append(tangent)
    verts: list[np.ndarray] = []
    for center, tangent in zip(centers, tangents):
        ref = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        normal = np.cross(tangent, ref)
        if float(np.linalg.norm(normal)) < 1e-8:
            normal = np.cross(tangent, np.array([1.0, 0.0, 0.0], dtype=np.float64))
        normal /= np.linalg.norm(normal)
        binormal = np.cross(tangent, normal)
        binormal /= np.linalg.norm(binormal)
        for j in range(circle):
            ang = 2.0 * math.pi * j / circle
            verts.append(center + tube_radius * (math.cos(ang) * normal + math.sin(ang) * binormal))
    points = np.stack(verts, axis=0)
    faces: list[list[int]] = []
    for i in range(rings - 1):
        for j in range(circle):
            a = i * circle + j
            b = i * circle + (j + 1) % circle
            c = (i + 1) * circle + j
            d = (i + 1) * circle + (j + 1) % circle
            faces.append([a, c, b])
            faces.append([b, c, d])
    return points, np.asarray(faces, dtype=np.int64)


def _stitch_rings(verts: np.ndarray, faces: np.ndarray, ring_a: int, ring_b: int, circle: int) -> np.ndarray:
    start_a = ring_a * circle
    start_b = ring_b * circle
    a_pts = verts[start_a : start_a + circle]
    b_pts = verts[start_b : start_b + circle]
    dist = ((a_pts[:, None, :] - b_pts[None, :, :]) ** 2).sum(axis=2)
    a_off, b_off = np.unravel_index(int(dist.argmin()), dist.shape)
    stitches = []
    for step in range(3):
        a0 = start_a + (int(a_off) + step) % circle
        a1 = start_a + (int(a_off) + step + 1) % circle
        b0 = start_b + (int(b_off) + step) % circle
        b1 = start_b + (int(b_off) + step + 1) % circle
        stitches.append([a0, b0, a1])
        stitches.append([a1, b0, b1])
    return np.concatenate([faces, np.asarray(stitches, dtype=np.int64)], axis=0)


class SameSheetWeldTests(unittest.TestCase):
    def test_duplicate_verts_merge_and_far_eps_is_rejected(self) -> None:
        verts = np.array(
            [
                [0.0, 0.0, 0.0],
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 2.0],
            ],
            dtype=np.float64,
        )
        faces = np.array([[0, 2, 3], [1, 2, 3], [0, 2, 4]], dtype=np.int64)
        welded = same_sheet_weld(
            verts,
            faces,
            eps=1e-6,
            reference_eps=1e-6,
            unique_rel_tol=0.02,
        )
        self.assertEqual(int(welded.verts.shape[0]), 4)
        self.assertEqual(unique_vertex_count(verts, 1e-6), 4)
        with self.assertRaisesRegex(ValueError, "non-duplicate"):
            same_sheet_weld(
                verts,
                faces,
                eps=1.5,
                reference_eps=1e-6,
                unique_rel_tol=0.02,
            )


class FanSplitTests(unittest.TestCase):
    def test_bowtie_vertex_is_duplicated(self) -> None:
        verts = np.array(
            [
                [0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
                [0.0, 0.0, 1.0],
                [-1.0, 0.0, 0.0],
            ],
            dtype=np.float64,
        )
        faces = np.array([[0, 1, 2], [0, 3, 4]], dtype=np.int64)
        split_verts, split_faces, _ = split_nonmanifold_fans(verts, faces)
        self.assertEqual(int(split_verts.shape[0]), 6)
        shared = set(int(index) for index in split_faces[0].tolist()) & set(
            int(index) for index in split_faces[1].tolist()
        )
        self.assertEqual(len(shared), 0)


class AuthorshipTests(unittest.TestCase):
    def test_incomplete_and_overlapping_lists_fail(self) -> None:
        with self.assertRaisesRegex(ValueError, "human_eye_coil_weld_authoring"):
            parse_coil_weld_authorship(
                {"method": "auto", "cutClusterIds": [], "keepClusterIds": []},
                cluster_count=0,
            )
        with self.assertRaisesRegex(ValueError, "exactly once"):
            parse_coil_weld_authorship(
                {
                    "method": AUTHORING_METHOD,
                    "cutClusterIds": [],
                    "keepClusterIds": [],
                },
                cluster_count=2,
            )
        with self.assertRaisesRegex(ValueError, "both cut and keep"):
            parse_coil_weld_authorship(
                {
                    "method": AUTHORING_METHOD,
                    "cutClusterIds": [0],
                    "keepClusterIds": [0],
                },
                cluster_count=1,
            )
        self.assertEqual(
            parse_coil_weld_authorship(
                {
                    "method": AUTHORING_METHOD,
                    "cutClusterIds": [1],
                    "keepClusterIds": [0],
                },
                cluster_count=2,
            ),
            (1,),
        )


class HelixDetectTests(unittest.TestCase):
    def test_separated_helix_has_no_clusters(self) -> None:
        verts, faces = _helical_tube(pitch=0.7, tube_radius=0.12, turns=1.4)
        result = detect_coil_weld_clusters(verts, faces)
        self.assertEqual(len(result.clusters), 0)
        self.assertEqual(int(result.component_count), 1)

    def test_stitched_helix_finds_and_cuts_the_bridge(self) -> None:
        circle = 10
        settings = CoilWeldDetectSettings(contact_edge_scale=2.0, min_cluster_faces=8)
        verts, faces = _helical_tube(
            pitch=0.30,
            tube_radius=0.13,
            turns=1.5,
            rings=40,
            circle=circle,
        )
        clean = detect_coil_weld_clusters(verts, faces, settings)
        stitched = _stitch_rings(verts, faces, 6, 26, circle)
        stitch_start = int(faces.shape[0])
        result = detect_coil_weld_clusters(verts, stitched, settings)
        self.assertGreaterEqual(len(result.clusters), 1)
        self.assertGreater(len(result.clusters), len(clean.clusters))
        stitch_clusters = [
            cluster.cluster_id
            for cluster in result.clusters
            if np.any(cluster.source_face_indices >= stitch_start)
        ]
        self.assertGreaterEqual(len(stitch_clusters), 1)
        keep_ids = [
            cluster.cluster_id
            for cluster in result.clusters
            if cluster.cluster_id not in set(stitch_clusters)
        ]
        authored = {
            "method": AUTHORING_METHOD,
            "cutClusterIds": stitch_clusters,
            "keepClusterIds": keep_ids,
        }
        cut_faces = cut_source_faces_from_authorship(result, authored)
        self.assertGreaterEqual(int(cut_faces.shape[0]), 1)
        before = geodesic_diameter_hops(vertex_adjacency(len(verts), stitched))
        out_verts, out_faces, _, report = apply_coil_weld_cuts(
            verts,
            stitched,
            cut_faces,
            min_largest_component_fraction=0.85,
        )
        after = int(report["geodesicDiameterHops"])
        self.assertEqual(int(report["weldedComponentCount"]), 1)
        self.assertGreater(after, before)
        self.assertGreaterEqual(int(out_verts.shape[0]), 3)
        self.assertGreaterEqual(int(out_faces.shape[0]), 1)
        template = authorship_template(result, src_glb="in.glb", sprite="sprite.png")
        with self.assertRaisesRegex(ValueError, "exactly once"):
            parse_coil_weld_authorship(template, cluster_count=len(result.clusters))

    def test_empty_cut_list_is_rejected_by_apply(self) -> None:
        verts, faces = _helical_tube()
        with self.assertRaisesRegex(ValueError, "at least one authored cut face"):
            apply_coil_weld_cuts(verts, faces, np.zeros((0,), dtype=np.int64))


if __name__ == "__main__":
    unittest.main()
