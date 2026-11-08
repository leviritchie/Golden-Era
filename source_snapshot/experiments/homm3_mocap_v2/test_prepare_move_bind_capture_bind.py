import unittest

import numpy as np

from prepare_move_bind_capture_bind import (
    bone_segment_distances,
    candidate_support,
    geodesic_bone_distances,
    nearest_bone_segment_weights,
    _mesh_edges,
    narrow_incidental_edge_mask,
)


def _strip(x0, x1, y, z, n=12):
    """Triangle strip along X at height y, depth z: returns vertices, triangles."""
    xs = np.linspace(x0, x1, n)
    verts = np.array([[x, y, z + dz] for x in xs for dz in (0.0, 0.05)])
    tris = []
    for i in range(n - 1):
        a, b, c, d = 2 * i, 2 * i + 1, 2 * i + 2, 2 * i + 3
        tris += [[a, b, c], [b, d, c]]
    return verts, np.asarray(tris)


class GeodesicSupportTest(unittest.TestCase):
    def setUp(self):
        # A "body" strip with a "wing" strip folded back to run parallel to it,
        # 0.02 above: Euclidean-close everywhere, but joined only at the far end.
        body_v, body_t = _strip(0.0, 1.0, 0.0, 0.0)
        wing_v, wing_t = _strip(1.0, 0.0, 0.02, 0.0)
        verts = np.concatenate([body_v, wing_v])
        tris = np.concatenate([body_t, wing_t + len(body_v)])
        # Join at x=1.0 with a bridge so the wing is reachable only via that end.
        bridge = np.array([[len(body_v) - 2, len(body_v) - 1, len(body_v)], [len(body_v) - 1, len(body_v) + 1, len(body_v)]])
        self.vertices, self.triangles = verts, np.concatenate([tris, bridge])
        # Bones: root owns the body segment; the next joint owns the wing segment.
        self.joints = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.02, 0.0]])
        self.parents = np.array([-1, 0, 1])
        self.names = ["Hips", "Shoulder", "WingTip"]
        self.body, self.wing, self.tip = 0, 1, 2
        self.body_count = len(body_v)

    def test_euclidean_makes_wing_a_belly_candidate_but_geodesic_does_not(self):
        euclid = bone_segment_distances(self.vertices, self.joints, self.parents)
        geo = geodesic_bone_distances(self.vertices, self.triangles, euclid)["distances"]
        belly = np.arange(2, 6)  # near x=0.1..0.3 on the body strip
        self.assertTrue(np.all(euclid[belly, self.wing] < 0.06), "wing bone is Euclidean-close to the belly")
        # Only route: along the body strip to the bridge at x=1.0 (>= 0.7 from x<=0.3).
        self.assertTrue(np.all(geo[belly, self.wing] > 0.7), "along the surface the wing bone is a strip-length away")
        self.assertTrue(np.all(geo[belly, self.wing] > 10 * euclid[belly, self.wing]))
        self.assertTrue(np.allclose(geo[belly, self.body], euclid[belly, self.body]), "own bone keeps its Euclidean distance")

    def test_support_excludes_surface_far_bone_and_marks_trainability(self):
        euclid = bone_segment_distances(self.vertices, self.joints, self.parents)
        geo = geodesic_bone_distances(self.vertices, self.triangles, euclid)["distances"]
        weights = nearest_bone_segment_weights(geo, k=2)
        support, trainable = candidate_support(
            geo, weights, ["torso", "wing", "wing"], trainable_regions=("wing",), ratio=2.5, cap=8
        )
        belly = np.arange(2, 6)
        self.assertTrue(np.all(np.argmax(weights[belly], axis=1) == self.body))
        self.assertTrue(np.all(weights[belly, self.wing] < 0.02), "far wing bone must not keep belly mass")
        wing_tip = np.arange(len(self.vertices) - 4, len(self.vertices))
        self.assertTrue(np.all(np.isin(np.argmax(weights[wing_tip], axis=1), (self.wing, self.tip))))
        self.assertTrue((support.sum(axis=1) <= 8).all())
        self.assertTrue(np.all((weights > 1e-8) <= support), "initial weights lie inside support")

    def test_euclidean_voronoi_seeds_preserve_the_nearest_bone_winner(self):
        euclid = bone_segment_distances(self.vertices, self.joints, self.parents)
        geo = geodesic_bone_distances(
            self.vertices,
            self.triangles,
            euclid,
            seed_policy="euclidean_voronoi",
            weld_policy="coincident",
        )["distances"]
        np.testing.assert_array_equal(np.argmin(geo, axis=1), np.argmin(euclid, axis=1))

    def test_contact_island_is_not_promoted_into_a_wing_seed(self):
        vertices = self.vertices.copy()
        contact = 4
        vertices[contact, 1] = 0.019
        euclid = bone_segment_distances(vertices, self.joints, self.parents)
        self.assertEqual(int(np.argmin(euclid[contact])), self.wing)
        old = geodesic_bone_distances(
            vertices,
            self.triangles,
            euclid,
            seed_policy="euclidean_voronoi",
            weld_policy="coincident",
        )["distances"]
        self.assertEqual(int(np.argmin(old[contact])), self.wing)
        new = geodesic_bone_distances(vertices, self.triangles, euclid)["distances"]
        self.assertEqual(int(np.argmin(new[contact])), self.body)
        self.assertGreater(float(new[contact, self.wing]), 0.5)

    def test_uv_split_contact_flake_does_not_seed_through_the_airgap(self):
        vertices = self.vertices.copy()
        contact = 4
        vertices[contact, 1] = 0.019
        src = np.array([2, 3, 4], dtype=np.int64)
        base = len(vertices)
        vertices = np.concatenate([vertices, vertices[src]])
        vertices[base + 2, 1] = 0.019
        triangles = np.concatenate(
            [self.triangles, np.array([[base, base + 1, base + 2]], dtype=np.int64)]
        )
        flake = np.array([base, base + 1, base + 2], dtype=np.int64)
        euclid = bone_segment_distances(vertices, self.joints, self.parents)
        self.assertEqual(int(np.argmin(euclid[contact])), self.wing)
        self.assertEqual(int(np.argmin(euclid[base + 2])), self.wing)
        jumped = geodesic_bone_distances(
            vertices,
            triangles,
            euclid,
            seed_policy="euclidean_voronoi",
            weld_policy="coincident",
        )["distances"]
        self.assertLess(float(jumped[base + 2, self.wing]), 0.06)
        geo = geodesic_bone_distances(vertices, triangles, euclid)["distances"]
        self.assertEqual(int(np.argmin(geo[contact])), self.body)
        self.assertEqual(int(np.argmin(geo[base + 2])), self.body)
        self.assertGreater(float(geo[contact, self.wing]), 0.5)
        self.assertGreater(float(geo[base + 2, self.wing]), 0.5)
        self.assertTrue(np.all(geo[flake, self.wing] > 0.5))

    def test_unique_wing_bridge_is_kept_when_dropping_incidental(self):
        euclid = bone_segment_distances(self.vertices, self.joints, self.parents)
        geo = geodesic_bone_distances(
            self.vertices,
            self.triangles,
            euclid,
            connection_policy="drop_narrow_incidental",
        )
        belly = np.arange(2, 6)
        self.assertTrue(np.all(geo["distances"][belly, self.wing] > 0.7))
        self.assertEqual(geo["droppedIncidentalEdges"], 0)


class LeafTipOwnershipTest(unittest.TestCase):
    def test_outgoing_surface_weights_include_the_leaf_tip(self):
        verts, tris = _strip(0.0, 1.0, 0.0, 0.0, n=12)
        joints = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]])
        parents = np.array([-1, 0])
        euclid = bone_segment_distances(verts, joints, parents)
        tip = np.arange(len(verts) - 2, len(verts))
        shaft = np.arange(4, 8)
        self.assertTrue(np.all(np.argmin(euclid[tip], axis=1) == 1))
        self.assertTrue(np.all(np.argmin(euclid[shaft], axis=1) == 0))
        geo = geodesic_bone_distances(verts, tris, euclid)
        self.assertGreater(geo["seedCounts"][1], 0)
        weights = nearest_bone_segment_weights(geo["distances"], k=2)
        self.assertTrue(np.all(weights[tip, 1] > 0.4))
        self.assertTrue(np.all(np.argmax(weights[shaft], axis=1) == 0))


def _grid(nx, ny, origin, du, dv):
    verts = np.asarray(
        [origin + i * du + j * dv for j in range(ny) for i in range(nx)],
        dtype=np.float64,
    )
    tris = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            b = a + 1
            c = a + nx
            d = c + 1
            tris += [[a, b, c], [b, d, c]]
    return verts, np.asarray(tris, dtype=np.int64)


class NarrowIncidentalConnectionTest(unittest.TestCase):
    def test_shortcut_glue_is_dropped_so_the_long_walk_wins(self):
        body, body_t = _grid(6, 6, np.array([0.0, 0.0, 0.0]), np.array([0.2, 0.0, 0.0]), np.array([0.0, 0.2, 0.0]))
        wing, wing_t = _grid(6, 6, np.array([3.0, 0.0, 0.0]), np.array([0.2, 0.0, 0.0]), np.array([0.0, 0.2, 0.0]))
        verts = np.concatenate([body, wing])
        tris = np.concatenate([body_t, wing_t + len(body)])
        a_tr, a_left = 5 + 5 * 6, 4 + 5 * 6
        b_tl, b_right = len(body) + 5 * 6, len(body) + 1 + 5 * 6
        glue = np.array([[a_tr, a_left, b_tl], [a_left, b_right, b_tl]], dtype=np.int64)
        path = []
        for y in np.linspace(-0.2, -2.0, 10):
            path.append([0.4, y, 0.0])
        for x in np.linspace(0.4, 3.4, 16):
            path.append([x, -2.0, 0.0])
        for y in np.linspace(-2.0, -0.2, 10):
            path.append([3.4, y, 0.0])
        path = np.asarray(path, dtype=np.float64)
        base = len(verts)
        left = path + np.array([0.0, 0.0, 0.0])
        right = path + np.array([0.0, 0.0, 0.05])
        strip_v = np.empty((len(path) * 2, 3), dtype=np.float64)
        strip_v[0::2] = left
        strip_v[1::2] = right
        strip_t = []
        for i in range(len(path) - 1):
            a, b, c, d = base + 2 * i, base + 2 * i + 1, base + 2 * i + 2, base + 2 * i + 3
            strip_t += [[a, b, c], [b, d, c]]
        a_bot, a_bot2 = 2, 3
        b_bot, b_bot2 = len(body) + 2, len(body) + 3
        last = base + 2 * (len(path) - 1)
        stitch = np.array(
            [
                [a_bot, a_bot2, base],
                [a_bot2, base + 1, base],
                [b_bot, last, last + 1],
                [b_bot, b_bot2, last + 1],
            ],
            dtype=np.int64,
        )
        verts = np.concatenate([verts, strip_v])
        tris = np.concatenate([tris, glue, np.asarray(strip_t, dtype=np.int64), stitch])
        joints = np.array([[0.5, 0.5, 0.0], [3.5, 0.5, 0.0]])
        parents = np.array([-1, -1])
        euclid = bone_segment_distances(verts, joints, parents)
        probe = len(body) + 2 + 2 * 6
        all_edges = geodesic_bone_distances(verts, tris, euclid, connection_policy="all_edges")["distances"]
        dropped = geodesic_bone_distances(verts, tris, euclid, connection_policy="drop_narrow_incidental")
        self.assertGreater(dropped["droppedIncidentalEdges"], 0)
        self.assertGreater(float(dropped["distances"][probe, 0]), float(all_edges[probe, 0]) + 0.8)
        self.assertTrue(np.isfinite(dropped["distances"][probe, 0]))

    def test_unique_tube_is_not_shattered(self):
        left, left_t = _grid(5, 5, np.array([0.0, 0.0, 0.0]), np.array([0.2, 0.0, 0.0]), np.array([0.0, 0.2, 0.0]))
        right, right_t = _grid(5, 5, np.array([3.0, 0.0, 0.0]), np.array([0.2, 0.0, 0.0]), np.array([0.0, 0.2, 0.0]))
        tube_v, tube_t = _strip(0.8, 3.0, 0.4, 0.0, n=14)
        verts = np.concatenate([left, right, tube_v])
        tris = np.concatenate([left_t, right_t + len(left), tube_t + len(left) + len(right)])
        a = 2 + 2 * 5
        b = len(left) + 2 + 2 * 5
        t0 = len(left) + len(right)
        t1 = t0 + len(tube_v) - 2
        stitch = np.array([[a, t0, t0 + 1], [b, t1, t1 + 1]], dtype=np.int64)
        tris = np.concatenate([tris, stitch])
        joints = np.array([[0.4, 0.4, 0.0], [3.4, 0.4, 0.0]])
        parents = np.array([-1, -1])
        euclid = bone_segment_distances(verts, joints, parents)
        geo = geodesic_bone_distances(verts, tris, euclid, connection_policy="drop_narrow_incidental")
        probe = len(left) + 2 + 2 * 5
        self.assertTrue(np.isfinite(geo["distances"][probe, 0]))
        self.assertGreater(float(geo["distances"][probe, 0]), 1.5)

    def test_mask_refuses_non_positive_cut(self):
        edges = _mesh_edges(np.array([[0, 1, 2]], dtype=np.int64))
        with self.assertRaises(ValueError):
            narrow_incidental_edge_mask(np.zeros((3, 3)), edges, max_cut=0)


if __name__ == "__main__":
    unittest.main()
