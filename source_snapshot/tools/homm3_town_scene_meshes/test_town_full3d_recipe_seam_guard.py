#!/usr/bin/env python3
"""Unit tests: the zero-streak recipe's seamAware repair (town_full3d_recipe guarded_faces / plan_repairs /
load_recipe). A face with a vertex within SEAM_GUARD_PX of its body's rest silhouette is never dropped or carded when
the recipe opts in; without the flag the repair plan is unchanged."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_recipe as R  # noqa: E402


def recipe(**repair):
    return {"schema": R.SCHEMA, "faction": "castle", "seed": "a", "candidate": "b",
            "ldi": {"pieces": ["Mesh_Terrain"]}, "backstop": {}, "repair": {"rules": ["drop", "card"], **repair},
            "certificate": {"loop": 12}}


class Load(unittest.TestCase):
    def load(self, r):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "r.json"
            p.write_text(json.dumps(r), encoding="utf-8")
            return R.load_recipe(p)

    def test_seam_aware_is_an_optional_boolean(self):
        self.assertNotIn("seamAware", self.load(recipe())["repair"])
        self.assertTrue(self.load(recipe(seamAware=True))["repair"]["seamAware"])
        with self.assertRaises(SystemExit):
            self.load(recipe(seamAware="yes"))


class Guard(unittest.TestCase):
    def test_faces_near_the_silhouette_on_either_side_are_guarded(self):
        F = np.array([[0, 1, 2], [3, 4, 5], [6, 7, 8]])
        sd = np.array([5, 6, 1.5, 9, 9, 9, -2, -8, -9.0])      # face 0 touches outside, face 2 just under the body
        np.testing.assert_array_equal(R.guarded_faces(F, sd), [True, False, True])
        np.testing.assert_array_equal(R.guarded_faces(F, sd, 1.0), [False, False, False])
        self.assertEqual(R.guarded_faces(np.zeros((0, 3), np.int64), sd).shape, (0,))


class Plan(unittest.TestCase):
    fails = {(0, 0): 5, (0, 1): 3, (1, 2): 7}
    shown = {(0, 1): 4}

    def test_without_the_guard_the_plan_is_drop_hidden_card_shown(self):
        todo, skip = R.plan_repairs(self.fails, self.shown, {"drop", "card"})
        self.assertEqual(todo, {("drop", 0): [0], ("card", 0): [1], ("drop", 1): [2]})
        self.assertEqual(skip, [])

    def test_guarded_faces_take_no_rule(self):
        g = {0: np.array([True, True, False]), 1: np.array([False, False, False])}
        todo, skip = R.plan_repairs(self.fails, self.shown, {"drop", "card"}, g)
        self.assertEqual(todo, {("drop", 1): [2]})
        self.assertEqual(skip, [(0, 0), (0, 1)])

    def test_a_rule_the_recipe_does_not_allow_fails_closed(self):
        with self.assertRaises(SystemExit):
            R.plan_repairs(self.fails, self.shown, {"drop"})


class SeamWeld(unittest.TestCase):
    """repair.seamWeld: the residual side of each split Body|residual pair slides onto the body's rest distance."""

    def test_plan_takes_residual_sides_of_split_body_pairs_only(self):
        arr = {"seam_roles": np.array([[0, 2], [2, 0], [0, 0], [0, 2], [0, 2]], np.int8),
               "seam_a": np.array([[0, 0, 10.], [0, 0, 20.], [0, 0, 5.], [0, 0, 8.], [0, 0, 11.]]),
               "seam_b": np.array([[0, 0, 10.5], [0, 0, 21.], [0, 0, 6.], [0, 0, 9.], [0, 0, 11.]]),
               "seam_face_bin": np.array([[0, 1], [1, 0], [0, 0], [0, 1], [0, 1]], np.int32),
               "seam_face": np.array([[7, 3], [4, 9], [1, 2], [8, 3], [7, 5]], np.int64)}
        split = np.array([True, True, True, False, True])
        plan = R.seam_weld_plan(arr, split)
        # pair 0 and pair 4 weld face (0, 7): body / residual = 10.5 / 10 and 11 / 11 -> median 1.025
        self.assertAlmostEqual(plan[(0, 7)], 1.025)
        self.assertAlmostEqual(plan[(0, 9)], 20.0 / 21.0)   # pair 1: residual on side b
        self.assertNotIn((0, 1), plan)                      # residual | residual: not welded
        self.assertNotIn((0, 8), plan)                      # not split
        self.assertEqual(len(plan), 2)

    def test_card_at_slides_along_rays_and_keeps_paint(self):
        st = R.Stage.__new__(R.Stage)
        v = np.array([[1.0, 2.0, 10.0], [2.0, 2.0, 12.0], [1.0, 3.0, 14.0], [5.0, 5.0, 20.0]])
        st.bins = [{"v": v.copy(), "n": np.ones((4, 3)), "uv": np.arange(8.0).reshape(4, 2),
                    "f": np.array([[0, 1, 2], [1, 3, 2]]), "dirty": False}]
        z_body = 9.5                                                 # a weld onto the body's distance
        fac = z_body / v[[0, 1, 2], 2]
        st.card_at(0, np.array([0]), fac[None])
        b = st.bins[0]
        np.testing.assert_array_equal(b["f"][1], [1, 3, 2])          # the other face keeps its vertices
        nv = b["v"][b["f"][0]]
        np.testing.assert_allclose(nv[:, 2], z_body)                  # every vertex on the body's depth
        np.testing.assert_allclose(nv[:, :2] / nv[:, 2:], v[:3, :2] / v[:3, 2:])   # on its own rest ray
        np.testing.assert_array_equal(b["uv"][b["f"][0]], np.arange(6.0).reshape(3, 2))
        self.assertTrue(b["dirty"])

    def test_load_validation(self):
        ld = Load.load
        with self.assertRaises(SystemExit):
            ld(Load(), recipe(seamWeld="yes"))
        with self.assertRaises(SystemExit):              # v1 recipe: no building-seam measure to weld against
            ld(Load(), recipe(seamWeld=True))


if __name__ == "__main__":
    unittest.main()
