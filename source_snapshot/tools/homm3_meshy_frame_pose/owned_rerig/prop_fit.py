"""Is a prop region bindable at all, and if so to which bone?

A prop - a bow, a torch, a standard - is geometry the skeleton does not run through.  When one arrives
fused to the wrong part of a body it shows up as stretching, and the obvious cures (bind the region
rigidly, cut the bridging triangles, delete the patches) are all local surgeries on the weights or the
index buffer.  Before any of them is attempted, one question decides whether they can work:

    is there *any* bone whose motion puts this geometry inside the frames' own plates?

The plates are ground truth for where the unit is in every authored frame, so the question is answered
by measurement, not by opinion: every flesh bone's own rigid transform is tried against every frame's
plate and the best one is reported, at the cost of one transform and one projection per (bone, frame)
pair.  It does not need the full replay audit and it does not weigh the other 7000 vertices.  Measured
on this unit's bow, the answer is no: the best of all 22 flesh bones still leaves it 5 px outside a
plate only 39 px wide, in 7 of 12 frames, so no weighting rule can place it - which is exactly why
rigid ownership and bridge-cutting moved 2 escaped vertices of 748 and 22 torn edges of 1657 and
nothing else.

Two ways to be wrong are ruled out here explicitly:

* deciding by the *global* escaped count.  Moving a 72-vertex region between bones shifts that count by
  two vertices while making the region itself reach further outside its plate (7.28 px -> 8.49 px), so
  the global number is not a selector; the region is scored alone.
* assuming far-from-every-bone means defective.  A region can be far from every bone and still be
  placed inside every plate by the shipped field - this lane reports that as
  ``already_inside_under_the_field`` rather than proposing a repair, because a region that needs no
  repair must not be "fixed".
* judging a region by its own containment alone.  A region one bone *can* place may still be welded to
  the body it lies against, and owning it rigidly then has to shear every edge that leaves it, because
  the weld is one sheet of surface that cannot follow two motions.  On this unit the 72-vertex bow
  region is placed perfectly by ``LeftHand`` - 6.4 px outside its plate under the field, 0.0 px under
  the hand - and is joined to the surrounding far shell by 21 edges, which ownership would take from
  0.0534 of stretch to 0.3153 where the unit's own worst edge under the field is 0.1079.  Containment
  is a necessary condition and not a sufficient one, so the boundary is measured as well, and
  ``bindable_but_the_boundary_would_tear`` is the verdict when the two disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from .exact_bind import (
    _dilate,
    _point_segment_distance,
    bone_tails,
    driver_transforms,
    nearby_vertex_pairs,
    provisional_labels,
    replay_deformed_vertices,
)
from .pose_source import CaptureToWorld, PoseSource
# The lane keys edges one way, and this measurement has to speak the audit's language: the same
# undirected-unique edges ``edge_stretch`` measures, so a seam growth here and a tear there are the
# same quantity.
from .tpose import _undirected_edges

PROP_FIT_SCHEMA = "prop_region_fit.v1"
# The verdicts, in the order of preference a reviewer should read them.
VERDICT_INSIDE = "already_inside_under_the_field"
VERDICT_BINDABLE = "bindable_to_one_bone"
# Bindable, and still refused: the region is welded to geometry that cannot follow it.
VERDICT_SEAM = "bindable_but_the_boundary_would_tear"
VERDICT_UNBINDABLE = "no_bone_fits_the_plates"


@dataclass(frozen=True)
class PropFitParams:
    """Sampling knobs for the region search.  None of them decides a verdict on its own.

    ``far_frac`` and ``link_frac`` are in units of subject height, and they define what a region *is*:
    geometry further than ``far_frac`` from every bone line, grouped where vertices sit within
    ``link_frac`` of each other.  ``max_fraction`` bounds a prop by size, because marker extrapolation
    pushes almost half of a real Meshy mesh beyond ``far_frac``, so without an upper bound the body
    itself is "far from every bone".  A verdict may change if these move; that is why the region's own
    numbers are reported beside it.
    """

    far_frac: float = 0.08
    link_frac: float = 0.04
    min_vertices: int = 20
    max_fraction: float = 0.05

    def __post_init__(self) -> None:
        for name in ("far_frac", "link_frac", "max_fraction"):
            value = float(getattr(self, name))
            if not (0.0 < value < 1.0):
                raise ValueError(f"fail-closed: {name} must be in (0, 1); got {value}")
        if int(self.min_vertices) < 3:
            raise ValueError(
                f"fail-closed: min_vertices must be at least 3; got {self.min_vertices}"
            )

    def marker(self, name: str) -> bool:
        """Markers are not flesh, so they are not candidates: the capture extrapolates them."""
        return name.endswith("Top_End") or name.endswith("Toe_End")


def _outside_px(camera, coverage: np.ndarray, plate_pixels, points: np.ndarray) -> np.ndarray:
    """Distance in pixels from each projected point to the plate, zero where it is inside."""
    projected = camera.project(points)
    rows, cols = plate_pixels
    height, width = coverage.shape
    if rows.size == 0:
        raise ValueError(
            "fail-closed: a frame has an empty plate, so nothing can be said to be inside it"
        )
    column = np.clip(np.rint(projected[:, 0]).astype(np.int64), 0, width - 1)
    row = np.clip(np.rint(projected[:, 1]).astype(np.int64), 0, height - 1)
    outside = np.zeros(len(points), dtype=np.float64)
    missing = ~coverage[row, column]
    if not missing.any():
        return outside
    outside[missing] = np.sqrt(
        (rows[None, :] - row[missing, None]) ** 2 + (cols[None, :] - column[missing, None]) ** 2
    ).min(axis=1)
    return outside


def boundary_seam(
    *,
    edges: np.ndarray,
    members: np.ndarray,
    positions: np.ndarray,
    field_frames: list[np.ndarray],
    rigid_frames: list[np.ndarray],
    budget: float,
) -> dict[str, Any]:
    """What owning one region does to the edges that leave it.

    A region and the surface around it are the same sheet wherever they share an edge, so if one of them
    is driven rigidly and the other is not, that edge is sheared by however far the two motions part.
    That shear is the *cost* of the ownership, and it is invisible to a containment test, which only ever
    asks whether the region itself lands inside the frame's plate.

    ``budget`` is the unit's own worst edge under the field, so the question answered here is the one a
    reviewer would ask: does owning this region make an edge worse than anything the mesh already does in
    this motion?  A region that shares no edge with the rest of the mesh - a prop that really is a
    separate shell - has nothing to shear and passes trivially, which is exactly the case rigid ownership
    exists for.
    """
    members = np.asarray(members, dtype=np.int64)
    edges = np.asarray(edges, dtype=np.int64)
    positions = np.asarray(positions, dtype=np.float64)
    if members.ndim != 1 or members.size == 0:
        raise ValueError(f"fail-closed: a region must be a nonempty 1-D index array; got {members.shape}")
    if edges.ndim != 2 or edges.shape[1] != 2:
        raise ValueError(f"fail-closed: edges must be (E,2); got {edges.shape}")
    if len(field_frames) != len(rigid_frames) or not field_frames:
        raise ValueError(
            f"fail-closed: {len(field_frames)} field frame(s) against {len(rigid_frames)} owned frame(s); "
            "a seam can only be measured per frame on both"
        )

    mask = np.zeros(len(positions), dtype=bool)
    mask[members] = True
    boundary = edges[mask[edges[:, 0]] ^ mask[edges[:, 1]]]
    if boundary.size == 0:
        return {
            "boundaryEdges": 0,
            "regionVerticesOnBoundary": 0,
            "fieldWorstGrowth": 0.0,
            "ownedWorstGrowth": 0.0,
            "ownedWorstFrame": None,
            "fieldWorstFrame": None,
            "grownOverTheField": None,
            "budget": round(float(budget), 5),
            "withinBudget": True,
            "note": "the region shares no edge with the rest of the mesh, so owning it moves a separate "
                    "shell and cannot shear a weld",
        }

    rest = np.linalg.norm(positions[boundary[:, 0]] - positions[boundary[:, 1]], axis=1)
    field_growth: list[float] = []
    owned_growth: list[float] = []
    for field_frame, rigid_frame in zip(field_frames, rigid_frames):
        field_frame = np.asarray(field_frame, dtype=np.float64)
        rigid_frame = np.asarray(rigid_frame, dtype=np.float64)
        field_length = np.linalg.norm(field_frame[boundary[:, 0]] - field_frame[boundary[:, 1]], axis=1)
        owned_length = np.linalg.norm(rigid_frame[boundary[:, 0]] - rigid_frame[boundary[:, 1]], axis=1)
        field_growth.append(float(np.max(field_length - rest)))
        owned_growth.append(float(np.max(owned_length - rest)))
    owned_worst = max(owned_growth)
    field_worst = max(field_growth)
    return {
        "boundaryEdges": int(boundary.shape[0]),
        "regionVerticesOnBoundary": int(len(np.unique(boundary))),
        "fieldWorstGrowth": round(field_worst, 5),
        "ownedWorstGrowth": round(owned_worst, 5),
        "ownedWorstFrame": int(np.argmax(owned_growth)),
        "fieldWorstFrame": int(np.argmax(field_growth)),
        "grownOverTheField": round(owned_worst / field_worst, 3) if field_worst > 1e-9 else None,
        "budget": round(float(budget), 5),
        "withinBudget": bool(owned_worst <= budget),
    }


def prop_regions(
    *,
    positions: np.ndarray,
    heads: np.ndarray,
    parents: list[int | None],
    bone_names: list[str],
    params: PropFitParams,
) -> list[np.ndarray]:
    """Geometry no bone is near, grouped by proximity and bounded to prop scale."""
    vertical_extent = float(np.ptp(heads[:, 1]))
    if vertical_extent <= 0.0:
        raise ValueError("fail-closed: the skeleton has no vertical extent to measure against")
    seed = provisional_labels(positions=positions, heads=heads)
    tails = bone_tails(positions=positions, parents=parents, heads=heads, labels=seed)
    live = np.array([not params.marker(name) for name in bone_names])
    live_ids = np.flatnonzero(live)
    if live_ids.size == 0:
        raise ValueError("fail-closed: every bone is a marker, so no bone can drive a prop")
    distance = np.stack(
        [
            _point_segment_distance(positions, heads[joint], tails[joint])
            for joint in live_ids
        ],
        axis=1,
    )
    far = np.flatnonzero(distance.min(axis=1) > params.far_frac * vertical_extent)
    if far.size == 0:
        return []
    links = nearby_vertex_pairs(positions, params.link_frac * vertical_extent)
    parent = np.arange(len(positions))

    def find(node: int) -> int:
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    for left, right in links:
        root_left, root_right = find(int(left)), find(int(right))
        if root_left != root_right:
            parent[root_left] = root_right
    roots = np.array([find(int(vertex)) for vertex in far], dtype=np.int64)
    limit = int(params.max_fraction * len(positions))
    regions = [
        far[roots == root]
        for root in np.unique(roots)
        if params.min_vertices <= int((roots == root).sum()) <= limit
    ]
    regions.sort(key=lambda members: -members.size)
    return regions


def score_prop_region(
    *,
    pose: PoseSource,
    similarity: CaptureToWorld,
    vertices: np.ndarray,
    members: np.ndarray,
    parents: list[int | None],
    bone_names: list[str],
    heads: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    plates: list[np.ndarray],
    plate_pixels: list[tuple[np.ndarray, np.ndarray]],
    frame_transforms: list[tuple[np.ndarray, np.ndarray]],
    frame_joints: np.ndarray,
    live_ids: np.ndarray,
    params: PropFitParams,
    edges: np.ndarray,
    field_frames: list[np.ndarray],
    mesh_worst_growth: float,
) -> dict[str, Any]:
    """The verdict for one region: what the shipped field does, the best any single bone can do, and
    what that bone's ownership would cost at the region's boundary.

    ``plates``, ``plate_pixels``, ``frame_transforms``, ``edges`` and ``field_frames`` are passed in
    because they are the same for every region, and re-deriving them per region would make a whole-unit
    sweep needlessly slow.  ``field_frames`` is the shipped field's own surface in every frame, so the
    boundary seam is measured against the motion that is already there rather than against the rest pose.
    """
    members = np.asarray(members, dtype=np.int64)
    if members.ndim != 1 or members.size == 0:
        raise ValueError(f"fail-closed: a region must be a nonempty 1-D index array; got {members.shape}")
    if members.min() < 0 or members.max() >= len(vertices):
        raise ValueError(
            f"fail-closed: region indices run outside the {len(vertices)}-vertex mesh"
        )
    field_outside = [
        _outside_px(pose.camera, plates[index], plate_pixels[index], field_frames[index][members])
        for index in range(len(plates))
    ]
    field_worst = float(max(series.max() for series in field_outside))
    scored = []
    for bone in live_ids:
        outside = []
        for index in range(len(plates)):
            rotations, offsets = frame_transforms[index]
            moved = vertices[members] @ rotations[int(bone)].T + offsets[int(bone)]
            outside.append(_outside_px(pose.camera, plates[index], plate_pixels[index], moved))
        scored.append(
            {
                "boneIndex": int(bone),
                "bone": bone_names[int(bone)],
                "framesInside": int(sum(1 for series in outside if not series.any())),
                "worstPxOutside": round(float(max(series.max() for series in outside)), 2),
            }
        )
    scored.sort(key=lambda row: (row["worstPxOutside"], -row["framesInside"]))
    best = scored[0]
    if field_worst == 0.0:
        verdict = VERDICT_INSIDE
    elif float(best["worstPxOutside"]) == 0.0:
        verdict = VERDICT_BINDABLE
    else:
        verdict = VERDICT_UNBINDABLE

    seam = None
    if verdict == VERDICT_BINDABLE:
        bone = int(best["boneIndex"])
        rigid_frames = []
        for index in range(len(plates)):
            rotations, offsets = frame_transforms[index]
            frame = np.asarray(field_frames[index], dtype=np.float64).copy()
            frame[members] = vertices[members] @ rotations[bone].T + offsets[bone]
            rigid_frames.append(frame)
        seam = boundary_seam(
            edges=edges,
            members=members,
            positions=vertices,
            field_frames=field_frames,
            rigid_frames=rigid_frames,
            budget=mesh_worst_growth,
        )
        if not seam["withinBudget"]:
            verdict = VERDICT_SEAM
    return {
        "vertices": int(members.size),
        "centroid": [float(value) for value in vertices[members].mean(axis=0)],
        "field": {
            "framesInside": int(sum(1 for series in field_outside if not series.any())),
            "worstPxOutside": round(field_worst, 2),
            "medianPxOutside": round(
                float(np.median([float(np.median(series)) for series in field_outside])), 2
            ),
        },
        "bestRigid": best,
        "bestRigidAlternatives": scored[1:3],
        "seam": seam,
        "verdict": verdict,
    }


def measure_prop_region_fit(
    *,
    pose: PoseSource,
    similarity: CaptureToWorld,
    mesh_positions: np.ndarray,
    mesh_indices: np.ndarray,
    parents: list[int | None],
    bone_names: list[str],
    heads: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    params: PropFitParams | None = None,
    alpha_dilate_px: int | None = None,
    regions: list[np.ndarray] | None = None,
) -> dict[str, Any]:
    """Per prop region: is the shipped field already inside the plates, and can any one bone be?

    ``regions`` lets a caller that already knows its regions - a preview that boxed them, a lane with
    its own definition of a prop - score those instead of the detected ones.  The verdict logic is
    identical either way, which is why it lives in ``score_prop_region``.
    """
    settings = params or PropFitParams()
    vertices = np.asarray(mesh_positions, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) == 0:
        raise ValueError(f"fail-closed: mesh positions must be a nonempty (N,3); got {vertices.shape}")
    if not np.isfinite(vertices).all():
        raise ValueError("fail-closed: mesh positions contain non-finite values")
    indices = np.asarray(mesh_indices, dtype=np.int64).reshape(-1)
    if indices.size == 0:
        raise ValueError("fail-closed: mesh indices are empty")
    rest_heads = np.asarray(heads, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    joints = np.asarray(joints, dtype=np.int64)
    if weights.shape[0] != len(vertices) or joints.shape[0] != len(vertices):
        raise ValueError(
            f"fail-closed: {len(vertices)} vertices but weights {weights.shape} and joints "
            f"{joints.shape} do not match"
        )
    if len(bone_names) != len(rest_heads) or len(parents) != len(rest_heads):
        raise ValueError("fail-closed: bone names, parents and heads disagree on the bone count")
    if pose.camera is None:
        raise ValueError("fail-closed: the pose source carries no camera, so no plate can be read")

    if alpha_dilate_px is None:
        from .exact_bind import ExactBindParams

        alpha_dilate_px = ExactBindParams().alpha_dilate_px
    plates = [
        _dilate(pose.alpha[index] > 0, int(alpha_dilate_px)) for index in range(len(pose.alpha))
    ]
    plate_pixels = [np.nonzero(plate) for plate in plates]
    frame_joints = similarity.apply(pose.capture_positions[pose.capture_indices])
    # One driver pass per frame, then slice per candidate bone: the transform of one bone does not
    # depend on which other bones are being scored.
    frame_transforms = [
        driver_transforms(heads=rest_heads, parents=parents, frame_joints=frame)
        for frame in frame_joints
    ]
    live_ids = np.array(
        [index for index, name in enumerate(bone_names) if not settings.marker(name)],
        dtype=np.int64,
    )
    # The shipped field's own surface in every frame, and the worst edge it produces anywhere on the
    # unit.  One replay pass per frame serves every region's containment test and every region's
    # boundary seam, and it is also the budget an ownership has to stay inside: a rule that hands a
    # region to a bone may not leave the unit with a worse edge than it already had.
    field_frames = [
        replay_deformed_vertices(
            positions=vertices,
            heads=rest_heads,
            parents=parents,
            joints=joints,
            weights=weights,
            frame_joints=frame_joints[index],
        )
        for index in range(len(frame_joints))
    ]
    edges = _undirected_edges(indices)
    rest_edge = np.linalg.norm(vertices[edges[:, 0]] - vertices[edges[:, 1]], axis=1)
    mesh_worst_growth = max(
        float(
            (
                np.linalg.norm(frame[edges[:, 0]] - frame[edges[:, 1]], axis=1) - rest_edge
            ).max()
        )
        for frame in field_frames
    )

    regions = (
        prop_regions(
            positions=vertices,
            heads=rest_heads,
            parents=parents,
            bone_names=bone_names,
            params=settings,
        )
        if regions is None
        else [np.asarray(members, dtype=np.int64) for members in regions]
    )
    # Region-independent, so they are measured once rather than once per region.
    components = _components(indices, len(vertices))
    nearest_bone = _nearest_bone_distance(
        vertices=vertices, heads=rest_heads, parents=parents, bone_names=bone_names, params=settings
    )
    rows: list[dict[str, Any]] = []
    for members in regions:
        row = score_prop_region(
            pose=pose,
            similarity=similarity,
            vertices=vertices,
            members=members,
            parents=parents,
            bone_names=bone_names,
            heads=rest_heads,
            joints=joints,
            weights=weights,
            plates=plates,
            plate_pixels=plate_pixels,
            frame_transforms=frame_transforms,
            frame_joints=frame_joints,
            live_ids=live_ids,
            params=settings,
            edges=edges,
            field_frames=field_frames,
            mesh_worst_growth=mesh_worst_growth,
        )
        row["patches"] = int(len(np.unique(components[members])))
        row["nearestBoneDistanceMedian"] = round(float(np.median(nearest_bone[members])), 4)
        rows.append(row)
    unbindable = [row for row in rows if row["verdict"] == VERDICT_UNBINDABLE]
    notes = []
    if unbindable:
        worst = max(unbindable, key=lambda row: row["field"]["worstPxOutside"])
        notes.append(
            f"{len(unbindable)} region(s) cannot be placed inside their own frames' plates by any of "
            f"the {len(live_ids)} flesh bones; the worst is {worst['vertices']} vertices that the best "
            f"bone ({worst['bestRigid']['bone']}) still leaves "
            f"{worst['bestRigid']['worstPxOutside']:.1f}px outside, inside on only "
            f"{worst['bestRigid']['framesInside']} of {len(plates)} frames - no weighting rule can "
            "place it, so the geometry disagrees with the art and the fix is mesh-side"
        )
    inside = [row for row in rows if row["verdict"] == VERDICT_INSIDE]
    if inside:
        notes.append(
            f"{len(inside)} region(s) are far from every bone but already inside every plate under the "
            "shipped field; they are not defects and must not be 'repaired'"
        )
    torn = [row for row in rows if row["verdict"] == VERDICT_SEAM]
    if torn:
        worst = max(torn, key=lambda row: row["seam"]["ownedWorstGrowth"])
        seam = worst["seam"]
        ratio = (
            f"{seam['grownOverTheField']}x the same edges under the field"
            if seam["grownOverTheField"] is not None
            else "unbounded against a field seam of zero"
        )
        notes.append(
            f"{len(torn)} region(s) can be placed inside their plates by one bone "
            f"({worst['bestRigid']['bone']}, {worst['bestRigid']['worstPxOutside']:.1f}px outside), but "
            f"owning them would shear the surface where they are welded to the rest: "
            f"{seam['boundaryEdges']} edge(s) leaving the region would grow {seam['ownedWorstGrowth']:.4f} "
            f"against the unit's own worst edge of {seam['budget']:.4f} under the field ({ratio}); the "
            "fault is the weld, not the weights, so no ownership is taken"
        )
    return {
        "schema": PROP_FIT_SCHEMA,
        "subjectHeight": round(float(np.ptp(rest_heads[:, 1])), 4),
        "frameCount": int(len(plates)),
        "candidateBones": int(len(live_ids)),
        "regionCount": len(rows),
        "unbindableVertices": int(sum(row["vertices"] for row in unbindable)),
        "meshWorstEdgeGrowthUnderTheField": round(mesh_worst_growth, 5),
        "regions": rows,
        "reviewNotes": notes,
        "proof": "generated-artifact",
    }


def _components(indices: np.ndarray, count: int) -> np.ndarray:
    from .exact_bind import mesh_components

    return mesh_components(indices, count)


def _nearest_bone_distance(
    *, vertices: np.ndarray, heads: np.ndarray, parents: list[int | None], bone_names: list[str],
    params: PropFitParams,
) -> np.ndarray:
    seed = provisional_labels(positions=vertices, heads=heads)
    tails = bone_tails(positions=vertices, parents=parents, heads=heads, labels=seed)
    live_ids = [index for index, name in enumerate(bone_names) if not params.marker(name)]
    return np.stack(
        [_point_segment_distance(vertices, heads[joint], tails[joint]) for joint in live_ids],
        axis=1,
    ).min(axis=1)


__all__ = [
    "PROP_FIT_SCHEMA",
    "VERDICT_BINDABLE",
    "VERDICT_INSIDE",
    "VERDICT_SEAM",
    "VERDICT_UNBINDABLE",
    "PropFitParams",
    "boundary_seam",
    "measure_prop_region_fit",
    "prop_regions",
    "score_prop_region",
]
