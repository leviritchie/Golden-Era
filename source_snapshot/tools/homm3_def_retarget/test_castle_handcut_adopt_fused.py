"""castle_handcut adopt.fused: the glove's fused vertex is found by position and arm share, not by vertex identity.

h3_champion 2026-10-07: bone heat is a global solve, so a neck edit moved the Hips-fused row from one glove vertex to its
neighbour; the old fixed dst <- src pair then copied the fused row and tore the Hitted twist 8.8x. The rule must give
the same arm ball and donor rows whichever vertex heat fused, and in any vertex order."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent / "ext"))
from castle_handcut import adopt_fused  # noqa: E402

GLOVE = [[-0.27497, -0.24504, 0.9394], [-0.27851, -0.23747, 0.94569]]   # champion right gauntlet spots (Blender xyz)
P = np.array(GLOVE + [[-0.2776, -0.2324, 0.9537], [-0.2738, -0.2165, 0.9432],     # glove neighbours (< 3 cm)
                      [-0.193, -0.13, 0.907], [-0.25, -0.30, 1.06]])               # saddle skin, hand top (> 3 cm)


class AdoptFusedTest(unittest.TestCase):
    def run_rule(self, aw, order=None):
        order = np.arange(len(P)) if order is None else np.asarray(order)
        mem, got = adopt_fused(P[order], np.asarray(aw, float)[order], GLOVE)
        # map results back to the original vertex ids
        return sorted(order[m] for m in mem), {int(order[v]): int(order[j]) for v, j in got.items()}

    def test_fused_vertex_takes_nearest_arm_row_wherever_heat_put_it(self):
        mem_a, got_a = self.run_rule([0.09, 1.0, 1.0, 1.0, 0.0, 0.0])    # heat fuses spot 0 (Hips .91)
        mem_b, got_b = self.run_rule([1.0, 0.09, 1.0, 1.0, 0.0, 0.0])    # after a far mesh edit: spot 1 instead
        self.assertEqual(mem_a, [0, 1]); self.assertEqual(mem_a, mem_b)   # only the spots join the arm
        self.assertEqual(got_a, {0: 1}); self.assertEqual(got_b, {1: 2})   # the nearest arm-dominant row, by position
        self.assertEqual(self.run_rule([1.0, 1.0, 1.0, 1.0, 0.0, 0.0])[1], {})   # nothing fused: rows untouched

    def test_only_spots_join_and_both_fused_copies_take_an_arm_row(self):
        mem, got = self.run_rule([0.09, 0.2, 1.0, 1.0, 0.0, 0.0])
        self.assertEqual(mem, [0, 1])
        self.assertEqual(got, {0: 2, 1: 2})        # both fused copies take the nearest arm-dominant row, never each other

    def test_vertex_order_invariant(self):
        aw = [0.09, 1.0, 1.0, 1.0, 0.0, 0.0]
        self.assertEqual(self.run_rule(aw), self.run_rule(aw, order=[5, 3, 1, 4, 0, 2]))

    def test_missing_spot_is_an_error(self):
        with self.assertRaises(SystemExit):
            adopt_fused(P[2:], np.ones(4), GLOVE)


if __name__ == "__main__":
    unittest.main()
