"""cove_tailpath capCuts: opt-in only, and only boundary edges between tail-weighted vertices are capped.

h3_naga_upg 2026-10-10: cutting the fused coil laps left holes in each lap (white gaps in the Move trail). capCuts
fills them; it must stay off for the Cove serpents that do not ask for it, and never close an opening outside the
tail (a sleeve or neck boundary)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent / "ext"))
from cove_tailpath import cap_edges  # noqa: E402


def edge(a, b, boundary=True):
    return NS(is_boundary=boundary, verts=[NS(index=a), NS(index=b)])


EDGES = [edge(0, 1), edge(1, 2), edge(2, 0),          # an opening in a lap (tail verts 0-2)
         edge(2, 3, boundary=False),                  # interior tail edge
         edge(4, 5), edge(5, 6)]                      # an opening at the waist/torso (4 is torso)
TAIL = {0, 1, 2, 3, 5, 6}


class CapCutsTest(unittest.TestCase):
    def test_off_unless_opted_in(self):
        self.assertEqual(cap_edges({}, EDGES, TAIL), [])
        self.assertEqual(cap_edges({"capCuts": False}, EDGES, TAIL), [])

    def test_only_tail_boundary_edges(self):
        got = cap_edges({"capCuts": True}, EDGES, TAIL)
        self.assertEqual([(e.verts[0].index, e.verts[1].index) for e in got], [(0, 1), (1, 2), (2, 0), (5, 6)])


if __name__ == "__main__":
    unittest.main()
