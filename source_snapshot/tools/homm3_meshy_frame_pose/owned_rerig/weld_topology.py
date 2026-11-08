"""Can part separation be trusted on this mesh, or are its pieces glued by coincidence?

``position_groups`` welds vertices that occupy the same point, and that is required: the exporter
duplicates a vertex wherever the UV or the normal changes, so one continuous sheet arrives as hundreds of
index patches and both sides of a seam must be driven by one transform.  The same weld also joins two
*different* surfaces that merely touch - a bow laid against a hip, a hand inside a leg - and there the
shared transform is the fault, because they are two pieces that may move apart.

The two cases are told apart by topology alone, with no weights, no reference and no threshold:

* a real seam leaves exactly **two** triangles on the shared welded edge and **one** connected triangle fan
  around the shared node, because the surface continues through it;
* a coincidence leaves the node carrying **two or more** fans that meet only at the point (a "bowtie"), or
  the shared edge carrying **four** triangles (a line contact).

What a coincidence costs is then measured rather than assumed, by counting pieces two ways:

* ``weldedComponents`` - the pieces a part rule sees, where triangles are joined through every welded edge,
  so two sheets that share one coincident vertex are one piece;
* ``piecesJoinedAcrossCleanEdges`` - the pieces the same rule sees if nothing is joined through a
  coincidence, which is a strict refinement of the first: any two triangles joined across a clean edge are
  also joined through the node graph, never the other way round.

Equality is therefore the threshold-free test of whether a coincidence changes what a piece *is*: a bowtie
inside a region the rest of the graph already connects leaves the counts equal and is harmless, and a
coincidence that is the only thing joining two regions raises the second count above the first.

Scope - this can prove a weld bad, never prove one good.  A generator that fuses two objects into one
continuous surface leaves no topological trace at all, so a clean report here means "no wrong weld can be
shown", not "every piece is one object".  Separating a fused prop needs the reference's own containment
evidence, which lives in the bind lane beside this measurement.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .exact_bind import mesh_components, position_groups

WELD_TOPOLOGY_SCHEMA = "weld_topology.v1"
VERDICT_NO_COINCIDENT_JOIN = "every_weld_is_a_surface_continuation"
VERDICT_COINCIDENT_JOIN = "a_coincidence_joins_two_pieces"
# How many coincidence regions are reported back, worst first.  Reporting only.
MAX_REPORTED_REGIONS = 8


class _DisjointSet:
    def __init__(self, count: int) -> None:
        self.parent = np.arange(int(count), dtype=np.int64)

    def find(self, node: int) -> int:
        root = node
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[node] != root:
            self.parent[node], node = root, self.parent[node]
        return int(root)

    def union(self, left: int, right: int) -> None:
        root_left, root_right = self.find(left), self.find(right)
        if root_left != root_right:
            self.parent[root_left] = root_right

    def components(self, indices) -> int:
        return len({self.find(int(index)) for index in indices})


def weld_topology(*, positions: np.ndarray, indices: np.ndarray) -> dict[str, Any]:
    """Measure whether the welded node graph is a surface, and whether a coincidence changes its pieces.

    ``positions`` is the delivered vertex array and ``indices`` the delivered triangle list, both as
    shipped; the welding is done here with the same rule the bind lane uses, so the answer is about the
    mesh that would actually be bound.
    """
    vertices = np.asarray(positions, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) == 0:
        raise ValueError(f"fail-closed: positions must be a nonempty (N,3); got {vertices.shape}")
    if not np.isfinite(vertices).all():
        raise ValueError("fail-closed: positions contain non-finite values")
    flat = np.asarray(indices, dtype=np.int64).reshape(-1)
    if flat.size == 0 or flat.size % 3:
        raise ValueError(f"fail-closed: indices must be a nonempty multiple of three; got {flat.size}")
    if flat.min() < 0 or flat.max() >= len(vertices):
        raise ValueError("fail-closed: an index runs outside the vertex array")
    triangles = flat.reshape(-1, 3)

    index_patches = mesh_components(flat, len(vertices))
    node_of_vertex, _representative = position_groups(vertices)
    node_count = int(node_of_vertex.max()) + 1
    tri_nodes = node_of_vertex[triangles]
    degenerate = (
        (tri_nodes[:, 0] == tri_nodes[:, 1])
        | (tri_nodes[:, 1] == tri_nodes[:, 2])
        | (tri_nodes[:, 0] == tri_nodes[:, 2])
    )
    welded_triangles = np.unique(np.sort(tri_nodes[~degenerate], axis=1), axis=0)
    triangle_count = len(welded_triangles)
    if triangle_count == 0:
        raise ValueError(
            "fail-closed: every triangle collapses once coincident vertices are welded, so there is no "
            "surface here to measure"
        )

    edge_triangles: dict[tuple[int, int], list[int]] = {}
    for triangle, (a, b, c) in enumerate(welded_triangles):
        for left, right in ((a, b), (b, c), (c, a)):
            key = (int(min(left, right)), int(max(left, right)))
            edge_triangles.setdefault(key, []).append(triangle)
    clean = {edge: tris for edge, tris in edge_triangles.items() if len(tris) == 2}
    over_full = {edge: tris for edge, tris in edge_triangles.items() if len(tris) > 2}

    # One corner per (node, triangle); corners of one node are joined when their triangles share a clean
    # edge that contains the node.  One group at a node means the surface continues through it.
    corner_parent: dict[tuple[int, int], tuple[int, int]] = {}

    def find_corner(corner: tuple[int, int]) -> tuple[int, int]:
        root = corner
        while corner_parent.get(root, root) != root:
            root = corner_parent[root]
        while corner_parent.get(corner, corner) != root:
            corner_parent[corner], corner = root, corner_parent[corner]
        return root

    for edge, tris in clean.items():
        for node in edge:
            left, right = (node, int(tris[0])), (node, int(tris[1]))
            root_left, root_right = find_corner(left), find_corner(right)
            if root_left != root_right:
                corner_parent[root_left] = root_right

    node_corners: dict[int, list[int]] = {}
    for triangle, (a, b, c) in enumerate(welded_triangles):
        for node in (a, b, c):
            node_corners.setdefault(int(node), []).append(triangle)
    fans_of_node = {
        node: len({find_corner((node, triangle)) for triangle in tris})
        for node, tris in node_corners.items()
    }
    bowtie_nodes = np.array([node for node, fans in fans_of_node.items() if fans > 1], dtype=np.int64)
    line_contacts = np.array(sorted(over_full), dtype=np.int64).reshape(-1, 2)
    line_contact_nodes = np.unique(line_contacts) if line_contacts.size else np.zeros(0, np.int64)
    coincident_nodes = np.unique(np.concatenate([bowtie_nodes, line_contact_nodes]))
    coincident_vertices = np.flatnonzero(np.isin(node_of_vertex, coincident_nodes))

    # The two counts: pieces a part rule sees through every welded edge, and pieces it sees when nothing
    # is joined through a coincidence.  The second is a strict refinement of the first.
    welded_graph = _DisjointSet(node_count)
    for left, right in edge_triangles:
        welded_graph.union(int(left), int(right))
    welded_components = welded_graph.components(range(node_count))

    clean_pieces = _DisjointSet(triangle_count)
    for tris in clean.values():
        clean_pieces.union(int(tris[0]), int(tris[1]))
    pieces_without_coincidences = clean_pieces.components(range(triangle_count))

    coincidence_joins_two_pieces = pieces_without_coincidences > welded_components
    review: list[str] = []
    if coincidence_joins_two_pieces:
        review.append(
            f"welding across coincidences leaves {welded_components} piece(s) where ignoring them leaves "
            f"{pieces_without_coincidences}: {len(coincident_nodes)} welded node(s) are the only thing "
            "joining regions that are otherwise separate surfaces, so a part rule keyed on this weld makes "
            "one part out of two and the two sides cannot move apart"
        )
    elif coincident_nodes.size:
        review.append(
            f"{len(coincident_nodes)} welded node(s) carry more than one triangle fan or a shared edge "
            "with four triangles, but every one of them is inside a region the rest of the graph already "
            "connects, so no coincidence changes which vertices are one piece"
        )

    regions: list[dict[str, Any]] = []
    line_contact_set = set(int(value) for value in line_contact_nodes)
    for node in sorted(coincident_nodes, key=lambda value: -fans_of_node.get(int(value), 1))[
        :MAX_REPORTED_REGIONS
    ]:
        node = int(node)
        members = node_of_vertex == node
        regions.append(
            {
                "node": node,
                "fans": int(fans_of_node.get(node, 1)),
                "lineContact": node in line_contact_set,
                "vertices": int(members.sum()),
                "indexPatches": int(len(np.unique(index_patches[members]))),
                "position": [round(float(value), 5) for value in vertices[members][0]],
            }
        )

    return {
        "schema": WELD_TOPOLOGY_SCHEMA,
        "verdict": (
            VERDICT_COINCIDENT_JOIN if coincidence_joins_two_pieces else VERDICT_NO_COINCIDENT_JOIN
        ),
        "ok": not coincidence_joins_two_pieces,
        "deliveredVertices": int(len(vertices)),
        "deliveredTriangles": int(len(triangles)),
        "deliveredIndexPatches": int(len(np.unique(index_patches))),
        "weldedNodes": node_count,
        "weldedEdges": len(edge_triangles),
        "weldedComponents": int(welded_components),
        "uniqueWeldedTriangles": triangle_count,
        "degenerateTriangles": int(degenerate.sum()),
        "cleanEdges": len(clean),
        "edgesWithMoreThanTwoTriangles": len(over_full),
        "bowtieNodes": int(bowtie_nodes.size),
        "lineContactNodes": int(line_contact_nodes.size),
        "coincidentNodes": int(coincident_nodes.size),
        "coincidentVertices": int(coincident_vertices.size),
        "piecesJoinedAcrossCleanEdges": int(pieces_without_coincidences),
        "piecesSeparatedByIgnoringCoincidences": int(
            pieces_without_coincidences - welded_components
        ),
        "regions": regions,
        "reviewNotes": review,
        "proof": "generated-artifact",
    }


__all__ = [
    "WELD_TOPOLOGY_SCHEMA",
    "VERDICT_NO_COINCIDENT_JOIN",
    "VERDICT_COINCIDENT_JOIN",
    "weld_topology",
]
