"""Unit tests for influence_limit.py (the glTF exporter's 4-influence rule applied before bake_cs.py).

    python tools/homm3_def_retarget/test_influence_limit.py
"""
from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import influence_limit as IL  # noqa: E402

JOINTS = ["Hips", "Spine", "Spine1", "Spine2", "LeftArm", "RightShoulder", "RightArm", "Root"]


def f32(x: float) -> float:
    """a vertex-group weight as Blender returns it (float32)."""
    return struct.unpack("<f", struct.pack("<f", x))[0]


class _G:
    def __init__(self, group, weight):
        self.group, self.weight = group, weight


class _V:
    def __init__(self, index, groups):
        self.index, self.groups = index, groups


class _VG:
    def __init__(self, name, index, log):
        self.name, self.index, self.log = name, index, log

    def remove(self, idx):
        self.log.append(("remove", self.name, tuple(idx)))

    def add(self, idx, w, mode):
        self.log.append(("add", self.name, tuple(idx), w, mode))


class _VGs(list):
    def __getitem__(self, k):
        return next(g for g in self if g.name == k) if isinstance(k, str) else list.__getitem__(self, k)


class _Mesh:
    def __init__(self, verts):
        self.vertices = verts


class _Ob:
    def __init__(self, names, verts):
        self.log = []
        self.vertex_groups = _VGs(_VG(n, i, self.log) for i, n in enumerate(names))
        self.data = _Mesh(verts)


class InfluenceLimitTest(unittest.TestCase):
    def test_noop_at_or_below_four(self):
        for g in ([], [("Spine", 1.0)], [("Spine1", f32(0.5)), ("Spine", f32(0.3)), ("Spine2", f32(0.15)),
                                           ("Hips", f32(0.05))]):
            self.assertIsNone(IL.limit(g, JOINTS))
        # a 5th group at or below the exporter's 1e-4, or not named after a joint, is no influence: still a no-op
        self.assertIsNone(IL.limit([("Spine1", 0.5), ("Spine", 0.3), ("Spine2", 0.1), ("Hips", 0.1),
                                    ("RightArm", 0.0001)], JOINTS))
        self.assertIsNone(IL.limit([("Spine1", 0.5), ("Spine", 0.3), ("Spine2", 0.1), ("Hips", 0.1),
                                    ("Feathers_mask", 0.9)], JOINTS))

    def test_top_four_normalised_like_the_exporter(self):
        # h3_pegasus vertex 14071 as fitted (GLB W4 [0.559 0.2521 0.1201 0.0689], dropped RightShoulder 0.058)
        g = [("Spine", 0.2374), ("RightShoulder", 0.058), ("Spine1", 0.5266), ("Hips", 0.1131), ("Spine2", 0.0649),
             ("LeftArm", 0.00005)]
        kept, dropped = IL.limit(g, JOINTS)
        self.assertEqual([n for n, _ in kept], ["Spine1", "Spine", "Hips", "Spine2"])
        self.assertAlmostEqual(sum(w for _, w in kept), 1.0, places=12)
        tot = 0.5266 + 0.2374 + 0.1131 + 0.0649
        for (n, w), w0 in zip(kept, (0.5266, 0.2374, 0.1131, 0.0649)):
            self.assertAlmostEqual(w, w0 / tot, places=12)
        self.assertEqual(sorted(dropped), ["LeftArm", "RightShoulder"])

    def test_ties_keep_group_order(self):
        g = [("Hips", 0.2), ("Spine", 0.2), ("Spine1", 0.2), ("Spine2", 0.2), ("LeftArm", 0.2)]
        kept, dropped = IL.limit(g, JOINTS)
        self.assertEqual([n for n, _ in kept], ["Hips", "Spine", "Spine1", "Spine2"])
        self.assertEqual(dropped, ["LeftArm"])

    def test_apply_to_mesh_touches_only_over_limit_vertices(self):
        names = JOINTS + ["Feathers_mask"]
        ix = {n: i for i, n in enumerate(names)}
        four = [_G(ix["Spine1"], f32(0.4)), _G(ix["Spine"], f32(0.3)), _G(ix["Hips"], f32(0.2)),
                _G(ix["Spine2"], f32(0.1)), _G(ix["Feathers_mask"], f32(1.0))]
        five = [_G(ix["Spine1"], f32(0.5)), _G(ix["Spine"], f32(0.2)), _G(ix["Hips"], f32(0.15)),
                _G(ix["Spine2"], f32(0.1)), _G(ix["RightArm"], f32(0.05))]
        ob = _Ob(names, [_V(0, four), _V(1, five), _V(2, [])])
        before = [[(g.group, g.weight) for g in v.groups] for v in ob.data.vertices]
        self.assertEqual(IL.apply_to_mesh(ob, JOINTS), 1)
        self.assertTrue(all(e[2] == (1,) for e in ob.log), ob.log)        # vertices 0 and 2: no call at all
        self.assertIn(("remove", "RightArm", (1,)), ob.log)
        self.assertEqual([[(g.group, g.weight) for g in v.groups] for v in ob.data.vertices], before)

    def test_shipped_weights_are_a_fixed_point(self):
        """Weights as exported (<= 4 per vertex, normalised): the limit leaves every one alone."""
        rows = [[("Spine1", 0.5163), ("Spine", 0.4065), ("Spine2", 0.0565), ("Hips", 0.0208)],
                [("Spine1", 0.5765), ("LeftArm", 0.2132), ("Spine", 0.1433), ("Spine2", 0.0671)]]
        for r in rows:
            self.assertIsNone(IL.limit(r, JOINTS))


if __name__ == "__main__":
    unittest.main()
