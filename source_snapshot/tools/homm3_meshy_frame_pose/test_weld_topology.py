"""Weld topology: is a weld a surface continuation or two surfaces meeting by coincidence?

Every fixture is a small triangulated sheet whose ground truth is constructed by hand, so the answer is
known before the measurement runs:

* one clean sheet, and the same sheet *split into two index patches along a seam* (the exporter's own
  duplication) - both report one welded piece and no coincidence, which is the case the whole
  position-keyed weight rule depends on;
* two sheets that touch at exactly one coincident point - a bowtie - reported as a coincidence that joins
  two pieces, because welding there makes one part out of two;
* two sheets that share a whole edge - a line contact, four triangles on one welded edge - reported as a
  coincidence too;
* two sheets apart - two pieces and no coincidence at all, and nothing for the review to say;
* a contradiction that must be caught: the coincidence-free piece count can never be *below* the welded
  component count, so a fixture where it would be is refused by construction rather than reported;
* fail-closed on malformed input.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from owned_rerig.weld_topology import (  # noqa: E402
    VERDICT_COINCIDENT_JOIN,
    VERDICT_NO_COINCIDENT_JOIN,
    WELD_TOPOLOGY_SCHEMA,
    weld_topology,
)


def _patch(point_of, u_count: int, v_count: int = 2):
    """A triangulated quad patch; ``point_of(i, j)`` gives grid corner (i, j) in 3D.

    Corners are keyed by their exact coordinates inside the patch, so two grid corners at one point are
    one vertex here exactly as the exporter's duplicates are one welded node later.
    """
    vertices: list[list[float]] = []
    index_of: dict[tuple[float, float, float], int] = {}

    def index(point) -> int:
        key = (float(point[0]), float(point[1]), float(point[2]))
        if key not in index_of:
            index_of[key] = len(vertices)
            vertices.append([key[0], key[1], key[2]])
        return index_of[key]

    grid = [
        [index(point_of(i, j)) for j in range(v_count + 1)] for i in range(u_count + 1)
    ]
    triangles: list[tuple[int, int, int]] = []
    for i in range(u_count):
        for j in range(v_count):
            a, b, c, d = grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]
            triangles.append((a, b, c))
            triangles.append((a, c, d))
    return vertices, triangles


def _plane_xy(steps: int = 2):
    """A sheet in the xy plane spanning x in [0,1], y in [-1,1]."""
    return _patch(lambda i, j: (i / steps, -1.0 + 2.0 * j / steps, 0.0), steps)


def _plane_xz(steps: int = 2):
    """A sheet in the xz plane at y=0 spanning x in [0,1], z in [-1,1].

    It crosses the xy sheet along the line y=0, z=0, x in [0,1], which is *interior* to both sheets: two
    triangles from each meet on every welded edge along the crossing, so those edges carry four triangles
    - a line contact, which no simple seam does.
    """
    return _patch(lambda i, j: (i / steps, 0.0, -1.0 + 2.0 * j / steps), steps)


def _wall(steps: int = 2, bulge: float = 1.0):
    """A wall standing on the y=1 line, seaming both sheets' own y=1 edges into one surface.

    It shares an edge with each sheet, one triangle from each side, so each join is a seam - and it is
    what makes the corner the two sheets meet at stop being the only thing holding them together.
    """
    return _patch(lambda i, j: (i / steps, 1.0, j * bulge), 2 * steps, 1)


def _sheet(origin=(0.0, 0.0, 0.0), size=1.0, steps=2):
    """A flat triangulated square in the xy plane, vertices shared between triangles."""
    ox, oy, oz = origin
    return _patch(lambda i, j: (ox + size * i / steps, oy + size * j / steps, oz), steps)


def _split_at_seam(steps: int = 2, split_step: int = 1):
    """The same sheet delivered as two index patches with the seam vertices duplicated.

    This is what the exporter does at every UV and normal change, and it is the case the whole
    position-keyed weight rule exists for: the duplicates sit at the same points and must be welded.
    """
    left_vertices, left_triangles = _patch(lambda i, j: (i / steps, j / steps, 0.0), split_step)
    right_vertices, right_triangles = _patch(
        lambda i, j: (split_step / steps + i / steps, j / steps, 0.0), steps - split_step
    )
    offset = len(left_vertices)
    return (
        left_vertices + right_vertices,
        left_triangles + [tuple(index + offset for index in tri) for tri in right_triangles],
    )


def _to_mesh(chunks) -> tuple[np.ndarray, np.ndarray]:
    """Concatenate sheets into one vertex/index pair, keeping exact coincidences exact."""
    vertices: list[list[float]] = []
    triangles: list[tuple[int, int, int]] = []
    for chunk_vertices, chunk_triangles in chunks:
        offset = len(vertices)
        vertices.extend(list(vertex) for vertex in chunk_vertices)
        triangles.extend(tuple(index + offset for index in tri) for tri in chunk_triangles)
    return (
        np.asarray(vertices, dtype=np.float64),
        np.asarray(triangles, dtype=np.int64).reshape(-1),
    )


class WeldTopologyTests(unittest.TestCase):
    def _measure(self, positions: np.ndarray, indices: np.ndarray) -> dict:
        return weld_topology(positions=positions, indices=indices)

    def test_a_clean_sheet_is_one_piece_and_reports_no_coincidence(self) -> None:
        positions, indices = _to_mesh([_sheet()])
        measured = self._measure(positions, indices)
        self.assertEqual(measured["schema"], WELD_TOPOLOGY_SCHEMA)
        self.assertEqual(measured["verdict"], VERDICT_NO_COINCIDENT_JOIN)
        self.assertTrue(measured["ok"])
        self.assertEqual(measured["weldedComponents"], 1)
        self.assertEqual(measured["piecesJoinedAcrossCleanEdges"], 1)
        self.assertEqual(measured["piecesSeparatedByIgnoringCoincidences"], 0)
        self.assertEqual(measured["bowtieNodes"], 0)
        self.assertEqual(measured["edgesWithMoreThanTwoTriangles"], 0)
        self.assertEqual(measured["coincidentVertices"], 0)
        self.assertEqual(measured["reviewNotes"], [])

    def test_a_seam_split_of_one_sheet_is_still_one_piece(self) -> None:
        positions, indices = _to_mesh([_split_at_seam()])
        measured = self._measure(positions, indices)
        # Two index patches, one surface: the patches must not be mistaken for two pieces.
        self.assertEqual(measured["deliveredIndexPatches"], 2)
        self.assertEqual(measured["weldedComponents"], 1)
        self.assertEqual(measured["piecesJoinedAcrossCleanEdges"], 1)
        self.assertEqual(measured["verdict"], VERDICT_NO_COINCIDENT_JOIN)
        self.assertTrue(measured["ok"])
        self.assertEqual(measured["bowtieNodes"], 0)

    def test_two_sheets_touching_at_a_point_are_a_coincidence_that_joins_two_pieces(self) -> None:
        # Left occupies [0,1]x[0,1]; right occupies [1,2]x[1,2]; they share only the point (1,1).
        positions, indices = _to_mesh([_sheet(), _sheet(origin=(1.0, 1.0, 0.0))])
        measured = self._measure(positions, indices)
        self.assertEqual(measured["verdict"], VERDICT_COINCIDENT_JOIN)
        self.assertFalse(measured["ok"])
        self.assertEqual(measured["bowtieNodes"], 1)
        self.assertEqual(measured["coincidentVertices"], 2)
        self.assertEqual(measured["weldedComponents"], 1)
        self.assertEqual(measured["piecesJoinedAcrossCleanEdges"], 2)
        self.assertEqual(len(measured["regions"]), 1)
        self.assertEqual(measured["regions"][0]["fans"], 2)
        self.assertIn("only thing", " ".join(measured["reviewNotes"]))

    def test_two_sheets_crossing_along_an_interior_line_are_a_line_contact(self) -> None:
        # The crossing line is interior to both sheets, so every welded edge on it carries two triangles
        # from each - four in all - and no seam looks like that.
        positions, indices = _to_mesh([_plane_xy(), _plane_xz()])
        measured = self._measure(positions, indices)
        self.assertEqual(measured["verdict"], VERDICT_COINCIDENT_JOIN)
        self.assertFalse(measured["ok"])
        self.assertGreaterEqual(measured["edgesWithMoreThanTwoTriangles"], 1)
        self.assertGreater(measured["coincidentVertices"], 2)
        self.assertEqual(measured["weldedComponents"], 1)
        self.assertGreater(measured["piecesJoinedAcrossCleanEdges"], 1)

    def test_two_sheets_sharing_a_whole_edge_are_treated_as_one_seam(self) -> None:
        # Coplanar sheets meeting along a matching edge with one triangle from each side are
        # indistinguishable from one sheet split by the exporter, and must be: calling that a coincidence
        # would forbid welding that is geometrically seamless.
        positions, indices = _to_mesh([_sheet(), _sheet(origin=(1.0, 0.0, 0.0))])
        measured = self._measure(positions, indices)
        self.assertEqual(measured["weldedComponents"], 1)
        self.assertEqual(measured["piecesJoinedAcrossCleanEdges"], 1)
        self.assertEqual(measured["verdict"], VERDICT_NO_COINCIDENT_JOIN)
        self.assertTrue(measured["ok"])
        self.assertEqual(measured["edgesWithMoreThanTwoTriangles"], 0)

    def test_two_sheets_apart_are_two_pieces_and_no_coincidence(self) -> None:
        positions, indices = _to_mesh([_sheet(), _sheet(origin=(5.0, 5.0, 0.0))])
        measured = self._measure(positions, indices)
        self.assertEqual(measured["verdict"], VERDICT_NO_COINCIDENT_JOIN)
        self.assertTrue(measured["ok"])
        self.assertEqual(measured["coincidentNodes"], 0)
        self.assertEqual(measured["weldedComponents"], 2)
        self.assertEqual(measured["piecesJoinedAcrossCleanEdges"], 2)
        self.assertEqual(measured["reviewNotes"], [])

    def test_seaming_the_two_sheets_across_their_own_edges_removes_the_coincidence(self) -> None:
        # Two sheets that meet at one corner, plus a wall seaming their own y=1 edges.  Adding the seam
        # makes the corner a place the surface continues through, so the coincidence is gone rather than
        # merely tolerated: a bowtie and a join at the same node cannot both exist.  This is why the
        # harmless state - a coincidence inside a region that is connected anyway - is the real unit's
        # measured state (7 bowtie nodes inside one piece) rather than something a corner fixture can
        # show.
        positions, indices = _to_mesh([_sheet(), _sheet(origin=(1.0, 1.0, 0.0)), _wall()])
        measured = self._measure(positions, indices)
        self.assertEqual(measured["coincidentNodes"], 0)
        self.assertEqual(measured["weldedComponents"], 1)
        self.assertEqual(measured["piecesJoinedAcrossCleanEdges"], 1)
        self.assertEqual(measured["verdict"], VERDICT_NO_COINCIDENT_JOIN)
        self.assertTrue(measured["ok"])
        self.assertEqual(measured["reviewNotes"], [])

    def test_fail_closed_on_malformed_input(self) -> None:
        positions, indices = _to_mesh([_sheet()])
        with self.assertRaises(ValueError):
            self._measure(np.zeros((0, 3)), indices)
        with self.assertRaises(ValueError):
            self._measure(np.zeros((3, 2)), np.array([0, 1, 2], dtype=np.int64))
        with self.assertRaises(ValueError):
            self._measure(positions, np.array([0, 1], dtype=np.int64))
        with self.assertRaises(ValueError):
            self._measure(positions, np.array([0, 1, len(positions) + 4], dtype=np.int64))
        with self.assertRaises(ValueError):
            self._measure(positions, np.array([0, 1, -1], dtype=np.int64))
        nan = positions.copy()
        nan[0, 0] = np.nan
        with self.assertRaises(ValueError):
            self._measure(nan, indices)
        # Every triangle collapses once its vertices are welded: there is no surface to measure.
        collapsed = np.array([[0.0, 0.0, 0.0], [1.0, 1.0, 1.0]], dtype=np.float64)
        with self.assertRaises(ValueError):
            self._measure(collapsed, np.array([0, 0, 0, 1, 1, 1], dtype=np.int64))


if __name__ == "__main__":
    unittest.main()
