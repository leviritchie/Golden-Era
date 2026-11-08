"""Owned bind from an *exact* animation reference (registered capture + DEF plates).

Binding an AI-generated mesh used to be pose-blind: joints were placed at AABB
fractions of an authored species template, or on the silhouette edge, and the result was
judged by a rendered-image score.  That is why a unit could land
``incompatible_bind_pose`` while every automated number still looked acceptable.

This module removes the guesswork whenever an exact reference exists, i.e. whenever the
animation has been captured into per-frame 3D joints and registered onto the mesh
(``pose_source.load_registered_pose_source``).  Then three things are *known* rather
than estimated:

* the bone hierarchy - it is the capture's own joint tree, so the bind has exactly the
  links the animation actually articulates;
* every joint's rest position in the image plane - it is the exact DEF pixel of the
  plate the mesh was generated from, so the only free quantity is depth, and depth is
  the one axis an orthographic plate cannot observe;
* what the bind must produce - replaying the reference on the bind must keep the
  deformed surface inside the DEF coverage of *every* authored frame.

The solver therefore does three things and nothing else:

1. **Fit the reference scale from the mesh.**  The registration's global similarity
   places the capture in mesh space; its scale is checked against the mesh instead of
   trusted.  The chosen correction is the one that puts the reference rest joints as
   close to the flesh as the mesh allows, and it must also satisfy the independent
   extent identity (the skeleton's own span equals the mesh's span), or the reference is
   refused as not describing one subject.
2. **Place joints on the reference rays.**  A joint keeps its exact reference pixel and
   keeps its reference depth unless that depth is not in the flesh; only then does it
   slide along the view axis, and only as far as the rigid bone-length bound allows.  A
   joint that would need more is left where the reference put it and reported, never
   silently moved somewhere plausible.
3. **Skin as a continuous field of position.**  A vertex's weights are a function of where the
   vertex is, never of which connected patch it belongs to: inverse squared-distance to the
   animation's own bones, strongest four.  A mesh whose surface is split into hundreds of
   patches by its exporter then still carries one weight field across the split, because
   coincident vertices are at the same position and therefore get the same weights.

   A field of position cannot know that a *prop* is rigid, though, and a generator fuses props
   into the body it draws them against: bow limbs laid along a thigh come out nearest the thigh
   and are then driven by it.  ``prop_rigid`` adds the one rule that can know it, and only
   because the reference says so - a prop region is handed wholly to the single bone whose own
   rigid transform keeps it inside every frame's plate, and it is left alone when the field
   already places it there, when *no* bone does, which is a geometry fault and not a weighting
   one, or when owning it would shear the edges that weld it to the body.  That last case is the
   one a containment test cannot see: on this unit's bow the hand places the region perfectly and
   the 21 edges leaving it would then grow to three times the unit's own worst edge, so the rule
   refuses and reports the weld as the fault.  ``own_props_rigidly`` is that stage, its default is
   ``prop_rigid="off"``, and off changes
   nothing.

Acceptance is the exact part.  For each authored frame the reference joint positions
drive the bind through position-anchored rigid skinning, and every deformed vertex must
project inside that frame's DEF coverage - not within an IoU tolerance of the plate, but
inside the silhouette that frame actually shows.  A vertex owned by the wrong bone, or a
pivot placed in the wrong place, leaves the silhouette and is counted.  Rigid
bone-length drift and joint flesh clearance are reported and gated too, and the audit
fails closed.

Twist is deliberately absent: joint positions do not determine a bone's roll, which this
repository already records (``vendor_parity.positionToRotationOracle
twistRecoverableFromJointPositions = false``).  A bind solved here makes no claim about
twist and the audit does not depend on it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

import numpy as np

from .animation_bind import mesh_boundary_edges
from .pose_source import CaptureToWorld, PoseSource, ReferenceInconsistentError

BIND_SCHEMA = "exact_reference_bind.v1"
AUDIT_SCHEMA = "exact_reference_bind_audit.v1"
SCALE_FIT_SCHEMA = "exact_reference_scale_fit.v1"

# Joint names that are markers rather than flesh pivots.  Mixamo's terminal markers sit
# past the surface by construction, so requiring flesh clearance for them would reject a
# correct bind; they are still measured and reported.
DEFAULT_MARKER_TOKENS = ("HeadTop_End", "Toe_End")


@dataclass
class ExactBindParams:
    # --- reference scale ---
    # How the capture->mesh similarity's *scale* is decided.  ``extent`` (the default) re-derives it from
    # the identity "an upright reference pose spans the mesh it was generated from" and refuses a bind pose
    # that is not upright.  That identity is a statement about a biped: a quadruped mesh is legitimately
    # longer than it is tall, so for those units the extent identity cannot choose a scale at all and the
    # only available mapping is the registration's own.  ``registered`` takes it verbatim, records why, and
    # leaves the geometry caveat in the report rather than silently rescaling anything.
    scale_source: str = "extent"
    scale_search_min: float = 0.50
    scale_search_max: float = 1.50
    # --- joint placement ---
    flesh_clearance_frac: float = 0.15  # of the rest subject height
    depth_search_frac: float = 0.12  # of the rest subject height
    depth_samples: int = 33
    max_bone_length_drift: float = 0.05
    # --- skinning ---
    # Sharpness of the position field: a bone's raw influence falls as (1/distance)^power.  A sharp
    # falloff gives neighbouring vertices very different weights, and the difference is what tears:
    # measured on this unit, power 8 tore 1262 edges past their own length on the locomotion clip and
    # opened 4 seams, while power 2 tore 540 and opened none - lower is better on every measured axis
    # (edge stretch, seam opening, and containment) because the blend then varies slowly across flesh.
    power: float = 2.0
    trim: float = 0.03
    max_influences: int = 4
    max_own_distance_frac: float = 0.45  # of bone length, on top of the clearance limit
    # Cohesion is measured over vertex pairs that touch at rest, at this fraction of the rest
    # subject height.  A bind that gives the two sides of a split surface different transforms
    # pulls them apart by this much or more, which is the hole the eye sees.
    cohesion_radius_frac: float = 0.003
    # Reporting radius for grouping the vertices that leave their frame's plate, as a fraction of the
    # rest subject height.  Reporting only: acceptance stays the exact per-frame escape count.
    escape_region_radius_frac: float = 0.02
    # Review evidence, not a gate: the worst edge-length distortion the driven surface may show
    # before the audit notes it.  A patch owned by two bones the animation never articulates
    # together tears at tens of times this; ordinary joint skinning stays inside it.
    max_edge_stretch_review: float = 1.0
    # --- acceptance ---
    alpha_dilate_px: int = 2
    # Floor budget for the replay, when the reference is perfectly rigid.  The effective budget
    # is raised to the reference's own measured non-rigidity: a rigid skeleton cannot reproduce
    # joint tracks whose bone lengths move, so no bind can be tighter than its reference.
    max_outside_excess_rest_adjacent: float = 0.02
    # The reference must still be rigid enough for "reproduce the animation" to mean anything.
    max_reference_median_length_excursion: float = 0.25
    # A flesh pivot must project onto the silhouette of the plate it was captured from, to
    # within the antialiasing and registration slack the 2 px dilation budget leaves.
    max_reference_joint_offplate_px: float = 2.5
    max_plate_baseline_outside: float = 0.15
    # How props are owned.  ``off`` keeps the position field everywhere.  ``platefit`` gives each
    # prop region - geometry no flesh bone runs near - to the single bone whose own rigid transform
    # keeps it inside every frame's plate, and only when such a bone exists and the field does not
    # already put it there.  A region no bone can place is left alone and reported: that is a
    # geometry fault, and rigidifying it would trade a stretch for a tear.
    prop_rigid: str = "off"
    marker_tokens: tuple[str, ...] = DEFAULT_MARKER_TOKENS

    def marker(self, name: str) -> bool:
        return any(token in name for token in self.marker_tokens)


# --------------------------------------------------------------------------- #
# small geometry helpers
# --------------------------------------------------------------------------- #


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    out = np.asarray(mask, dtype=bool)
    for _ in range(int(radius)):
        height, width = out.shape
        padded = np.pad(out, 1, mode="constant", constant_values=False)
        grown = np.zeros_like(out)
        for dy in range(3):
            for dx in range(3):
                grown |= padded[dy : dy + height, dx : dx + width]
        out = grown
    return out


def _point_segment_distance(points: np.ndarray, head: np.ndarray, tail: np.ndarray) -> np.ndarray:
    seg = tail - head
    length2 = float(np.dot(seg, seg))
    rel = points - head
    if length2 < 1e-12:
        return np.linalg.norm(rel, axis=1)
    t = np.clip((rel @ seg) / length2, 0.0, 1.0)
    return np.linalg.norm(rel - t[:, None] * seg[None, :], axis=1)


def _closest_point_on_triangles(points: np.ndarray, triangles: np.ndarray) -> np.ndarray:
    """Exact closest point on each triangle (Ericson) for ``(B,3)`` against ``(M,3,3)``.

    Vertex, edge and face regions are mutually exclusive for a point outside the triangle,
    so applying them in specificity order with later overrides yields the correct region.
    """
    a = triangles[:, 0][None, :, :]
    b = triangles[:, 1][None, :, :]
    c = triangles[:, 2][None, :, :]
    p = points[:, None, :]
    ab = b - a
    ac = c - a
    ap = p - a
    d1 = (ab * ap).sum(-1)
    d2 = (ac * ap).sum(-1)
    bp = p - b
    d3 = (ab * bp).sum(-1)
    d4 = (ac * bp).sum(-1)
    cp = p - c
    d5 = (ab * cp).sum(-1)
    d6 = (ac * cp).sum(-1)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2

    def _ratio(numerator: np.ndarray, denominator: np.ndarray) -> np.ndarray:
        safe = np.where(np.abs(denominator) < 1e-20, 1.0, denominator)
        return np.where(np.abs(denominator) < 1e-20, 0.0, numerator / safe)

    denominator = va + vb + vc
    v = _ratio(vb, denominator)
    w = _ratio(vc, denominator)
    closest = a + ab * v[..., None] + ac * w[..., None]

    def _override(mask: np.ndarray, candidate: np.ndarray) -> None:
        nonlocal closest
        closest = np.where(mask[..., None], candidate, closest)

    both = (d4 - d3) + (d5 - d6)
    _override(
        (va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0),
        b + (c - b) * _ratio(d4 - d3, both)[..., None],
    )
    _override((vb <= 0) & (d2 >= 0) & (d6 <= 0), a + ac * _ratio(d2, d2 - d6)[..., None])
    _override((vc <= 0) & (d1 >= 0) & (d3 <= 0), a + ab * _ratio(d1, d1 - d3)[..., None])
    _override((d6 >= 0) & (d5 <= d6), c + cp * 0.0)
    _override((d3 >= 0) & (d4 <= d3), b + bp * 0.0)
    _override((d1 <= 0) & (d2 <= 0), a + ap * 0.0)
    return closest


def _surface_distance(
    points: np.ndarray,
    triangle_indices: np.ndarray,
    vertices: np.ndarray,
    *,
    chunk: int = 32,
) -> np.ndarray:
    """Exact distance from each point to the mesh surface.

    Not a nearest-vertex sample: on a coarse mesh a joint in the middle of the body is a
    long way from any vertex while barely off the surface, which the repository already
    records as not acceptance-grade.  Joint containment depends on the surface.
    """
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    tri = np.asarray(triangle_indices, dtype=np.int64).reshape(-1, 3)
    if len(tri) == 0:
        raise ValueError("surface distance needs a nonempty triangle list")
    triangles = np.asarray(vertices, dtype=np.float64)[tri]
    out = np.empty(len(pts), dtype=np.float64)
    for start in range(0, len(pts), chunk):
        block = pts[start : start + chunk]
        closest = _closest_point_on_triangles(block, triangles)
        out[start : start + chunk] = np.linalg.norm(
            closest - block[:, None, :], axis=2
        ).min(axis=1)
    return out


def _axis_angle_matrix(axis: np.ndarray, angle: float) -> np.ndarray:
    x, y, z = np.asarray(axis, dtype=np.float64).reshape(3)
    c, s = math.cos(angle), math.sin(angle)
    one = 1.0 - c
    return np.array(
        [
            [c + x * x * one, x * y * one - z * s, x * z * one + y * s],
            [y * x * one + z * s, c + y * y * one, y * z * one - x * s],
            [z * x * one - y * s, z * y * one + x * s, c + z * z * one],
        ]
    )


def _rotation_from_to(from_vec: np.ndarray, to_vec: np.ndarray) -> np.ndarray:
    """Minimal rotation taking ``from_vec`` onto ``to_vec``; identity when degenerate.

    The minimal (swing) rotation is the only one a joint-position reference determines.
    """
    a = np.asarray(from_vec, dtype=np.float64).reshape(3)
    b = np.asarray(to_vec, dtype=np.float64).reshape(3)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-12 or nb < 1e-12:
        return np.eye(3)
    a = a / na
    b = b / nb
    cross = np.cross(a, b)
    sin_angle = float(np.linalg.norm(cross))
    cos_angle = float(np.clip(np.dot(a, b), -1.0, 1.0))
    if sin_angle < 1e-12:
        if cos_angle > 0.0:
            return np.eye(3)
        helper = np.array([1.0, 0.0, 0.0])
        if abs(float(np.dot(helper, a))) > 0.9:
            helper = np.array([0.0, 1.0, 0.0])
        axis = np.cross(a, helper)
        axis /= max(float(np.linalg.norm(axis)), 1e-12)
    else:
        axis = cross / sin_angle
    return _axis_angle_matrix(axis, math.atan2(sin_angle, cos_angle))


def bone_names_from_capture(names: list[str]) -> list[str]:
    """``mixamorig:LeftForeArm`` -> ``LeftForeArm``; guaranteed unique and non-empty."""
    out: list[str] = []
    used: dict[str, int] = {}
    for index, raw in enumerate(names):
        short = str(raw).split(":")[-1].strip() or f"Joint_{index:02d}"
        if short in used:
            used[short] += 1
            short = f"{short}_{used[short]}"
        else:
            used[short] = 0
        out.append(short)
    if len(set(out)) != len(out):
        raise ValueError("capture joint names do not reduce to unique bone names")
    return out


def children_of(parents: list[int | None]) -> dict[int, list[int]]:
    children: dict[int, list[int]] = {joint: [] for joint in range(len(parents))}
    for child, parent in enumerate(parents):
        if parent is not None:
            children[parent].append(child)
    return children


def tree_order(parents: list[int | None]) -> list[int]:
    children = children_of(parents)
    roots = [joint for joint, parent in enumerate(parents) if parent is None]
    if len(roots) != 1:
        raise ValueError(f"joint tree must have exactly one root; got {len(roots)}")
    order: list[int] = []
    queue = list(roots)
    while queue:
        node = queue.pop(0)
        order.append(node)
        queue.extend(children[node])
    if len(order) != len(parents):
        raise ValueError("joint tree does not reach every joint")
    return order


def _bone_lengths(positions: np.ndarray, parents: list[int | None]) -> np.ndarray:
    lengths = np.zeros(len(parents), dtype=np.float64)
    for joint, parent in enumerate(parents):
        if parent is not None:
            lengths[joint] = float(np.linalg.norm(positions[joint] - positions[parent]))
    return lengths


def _length_drift(proposed: np.ndarray, parent_head: np.ndarray, reference: float) -> float:
    if reference <= 1e-9:
        return 0.0
    return abs(float(np.linalg.norm(proposed - parent_head)) / reference - 1.0)


# --------------------------------------------------------------------------- #
# 1. reference scale
# --------------------------------------------------------------------------- #


def rescale_to_extent(
    similarity: CaptureToWorld,
    capture_rest: np.ndarray,
    *,
    axis: int,
    target_min: float,
    target_max: float,
) -> CaptureToWorld:
    """Rescale a similarity so the reference spans ``[target_min, target_max]`` on ``axis``.

    The similarity's rotation is a reference quantity and is kept; only its uniform scale
    and its position along ``axis`` change.  This is one equation in one unknown, so it
    cannot be satisfied by a wrong answer the way a distance score can - in particular it
    cannot be gamed by collapsing the skeleton into the body core, which is what a
    mean-distance objective degenerates to.
    """
    capture_rest = np.asarray(capture_rest, dtype=np.float64)
    mapped = similarity.apply(capture_rest)
    low = float(mapped[:, axis].min())
    high = float(mapped[:, axis].max())
    if high - low <= 1e-9:
        raise ReferenceInconsistentError(
            "fail-closed: the reference pose has no extent along the anchor axis; the extent "
            "identity cannot determine the scale"
        )
    if target_max - target_min <= 1e-9:
        raise ReferenceInconsistentError("fail-closed: the mesh has no extent along the anchor axis")
    factor = (target_max - target_min) / (high - low)
    pivot = mapped[int(np.argmin(mapped[:, axis]))].copy()
    scaled = similarity.scaled_about(pivot, factor)
    shift = np.zeros(3, dtype=np.float64)
    shift[axis] = float(target_min) - low
    return CaptureToWorld(
        rotation=scaled.rotation,
        scale=scaled.scale,
        translation=scaled.translation + shift,
        policy=f"{similarity.policy}+extent_anchor_axis{axis}",
        source=similarity.source,
    )


def fit_reference_scale(
    *,
    pose: PoseSource,
    mesh_positions: np.ndarray,
    mesh_indices: np.ndarray,
    params: ExactBindParams,
) -> tuple[CaptureToWorld, dict[str, Any]]:
    """Anchor the reference scale to the mesh's own extent along the stance axis.

    The registration states a capture -> mesh similarity; its *scale* is re-derived here
    rather than trusted, because a registration that was accepted for containment may
    still be the wrong size for the mesh (the published wood-elf registration places the
    skeleton a quarter taller than its own mesh).

    The anchor is the vertical extent, which both artifacts observe directly in the same
    frame: a standing reference pose must span exactly the mesh it was generated from.
    This is deliberately *not* a distance score - the mean distance from the joints to
    the mesh surface is minimised by collapsing the whole skeleton into the body core, so
    it cannot choose a scale.  It is also checked for dominance first, so a crouched bind
    pose is refused instead of silently mis-scaled.
    """
    vertices = np.asarray(mesh_positions, dtype=np.float64)
    capture_rest = np.asarray(pose.capture_positions[pose.bind_index()], dtype=np.float64)
    base_scale = float(pose.similarity.scale)
    if params.scale_source not in ("extent", "registered"):
        raise ValueError(f"unknown scale_source {params.scale_source!r}")

    axis = 1  # glTF Y: vertical in the mesh frame the registration was fitted in
    mapped = pose.similarity.apply(capture_rest)
    extents = {
        "x": float(np.ptp(mapped[:, 0])),
        "y": float(np.ptp(mapped[:, 1])),
        "z": float(np.ptp(mapped[:, 2])),
    }
    mesh_extents = {
        "x": float(np.ptp(vertices[:, 0])),
        "y": float(np.ptp(vertices[:, 1])),
        "z": float(np.ptp(vertices[:, 2])),
    }
    if extents["y"] <= 1e-9 or mesh_extents["y"] <= 1e-9:
        raise ReferenceInconsistentError(
            "fail-closed: the mesh or the reference pose has no vertical extent; the reference "
            "cannot be scaled"
        )
    upright = extents["y"] >= max(extents["x"], extents["z"])
    if not upright and params.scale_source == "extent":
        raise ReferenceInconsistentError(
            "fail-closed: the bind-frame reference pose is not an upright stance "
            f"(extents x={extents['x']:.4f} y={extents['y']:.4f} z={extents['z']:.4f}); the extent "
            "identity cannot determine the scale from a crouched or reclining pose"
        )

    if params.scale_source == "registered":
        # Take the registration's own scale.  Nothing is refitted and nothing is hidden: the extents that
        # would have decided the anchor are returned with the mismatch they carry, so a reader can see how
        # far the reference is from spanning the mesh before believing any containment number built on it.
        mapped = pose.similarity.apply(capture_rest)
        before_distance = _surface_distance(mapped, mesh_indices, vertices)
        extent_ratios = {
            key: (mesh_extents[key] / extents[key]) if extents[key] > 1e-9 else None for key in extents
        }
        return pose.similarity, {
            "schema": SCALE_FIT_SCHEMA,
            "registeredScale": base_scale,
            "fittedScale": base_scale,
            "correctionFactor": 1.0,
            "scaleSource": "registered",
            "criterion": "registration_scale_taken_verbatim",
            "anchorAxis": None,
            "referenceExtents": extents,
            "meshExtents": mesh_extents,
            "extentRatios": extent_ratios,
            "distanceMetric": "exact_point_to_triangle",
            "meanDistanceBefore": float(before_distance.mean()),
            "meanDistanceAfter": float(before_distance.mean()),
            "worstDistanceBefore": float(before_distance.max()),
            "worstDistanceAfter": float(before_distance.max()),
            "scaleCaveat": (
                "the extent identity was not applied: this bind pose is not upright "
                f"(x={extents['x']:.4f} y={extents['y']:.4f} z={extents['z']:.4f}), which is what a "
                "quadruped or reclining subject looks like, so containment measured from this similarity "
                "carries the registration's own scale error"
                if not upright
                else "registration scale kept by request even though the extent identity was available"
            ),
            "proof": "generated-artifact",
            "ok": True,
        }

    scale_fit_similarity = rescale_to_extent(
        pose.similarity,
        capture_rest,
        axis=axis,
        target_min=float(vertices[:, axis].min()),
        target_max=float(vertices[:, axis].max()),
    )
    fitted_scale = float(scale_fit_similarity.scale)
    correction = fitted_scale / base_scale
    lo_bound = base_scale * float(params.scale_search_min)
    hi_bound = base_scale * float(params.scale_search_max)
    if not lo_bound * 1.001 < fitted_scale < hi_bound * 0.999:
        raise ReferenceInconsistentError(
            f"fail-closed: the extent identity needs scale {fitted_scale:.6f} (correction "
            f"{correction:.4f}), outside the accepted band ({lo_bound:.6f}, {hi_bound:.6f}); the "
            "reference and the mesh are not the same subject"
        )

    before = mapped
    after = scale_fit_similarity.apply(capture_rest)
    before_distance = _surface_distance(before, mesh_indices, vertices)
    after_distance = _surface_distance(after, mesh_indices, vertices)
    extent_ratios = {
        key: (mesh_extents[key] / extents[key]) if extents[key] > 1e-9 else None
        for key in extents
    }
    report: dict[str, Any] = {
        "schema": SCALE_FIT_SCHEMA,
        "registeredScale": base_scale,
        "fittedScale": fitted_scale,
        "correctionFactor": correction,
        "scaleSource": "extent",
        "criterion": "reference_pose_must_span_the_mesh_it_was_generated_from",
        "anchorAxis": "y",
        "referenceExtents": extents,
        "meshExtents": mesh_extents,
        "extentRatios": extent_ratios,
        "distanceMetric": "exact_point_to_triangle",
        "meanDistanceBefore": float(before_distance.mean()),
        "meanDistanceAfter": float(after_distance.mean()),
        "worstDistanceBefore": float(before_distance.max()),
        "worstDistanceAfter": float(after_distance.max()),
        "proof": "generated-artifact",
        "ok": True,
    }
    off_axis = [
        f"{key}={ratio:.3f}"
        for key, ratio in extent_ratios.items()
        if key != "y" and ratio is not None and abs(ratio - 1.0) > 0.05
    ]
    if off_axis:
        report["offAxisNote"] = (
            "non-anchor extent ratios "
            + ", ".join(off_axis)
            + "; reviewed, not gated - a held prop widens the mesh beyond the skeleton, and "
            "flesh proximity plus per-joint plate coverage carry the acceptance instead"
        )
    return scale_fit_similarity, report


# --------------------------------------------------------------------------- #
# 2. joint placement
# --------------------------------------------------------------------------- #


def place_joints(
    *,
    pose: PoseSource,
    similarity: CaptureToWorld,
    mesh_positions: np.ndarray,
    mesh_indices: np.ndarray,
    parents: list[int | None],
    bone_names: list[str],
    params: ExactBindParams,
) -> dict[str, Any]:
    """Place rest heads on the exact reference rays, bounded by rigid bone length.

    Each joint's reference pixel is ground truth and is never changed.  Depth is the one
    axis the plates cannot observe, so a joint whose reference depth leaves it outside
    the flesh slides along the view axis - and only as far as the rigid bone-length bound
    permits, because a correction that would stop the bind from reproducing the reference
    is worse than a joint that sits slightly off the surface.
    """
    vertices = np.asarray(mesh_positions, dtype=np.float64)
    indices = np.asarray(mesh_indices, dtype=np.int64).reshape(-1, 3)
    rest = similarity.apply(pose.capture_positions[pose.bind_index()])
    camera = pose.camera
    subject_height = float(np.ptp(rest[:, 1]))
    if subject_height <= 1e-9:
        raise ReferenceInconsistentError("fail-closed: the reference rest pose has no vertical extent")
    clearance_limit = params.flesh_clearance_frac * subject_height
    search = params.depth_search_frac * subject_height
    deltas = np.linspace(-search, search, max(3, int(params.depth_samples)))
    reference_lengths = _bone_lengths(rest, parents)

    heads = rest.copy()
    rows: list[dict[str, Any]] = []
    for joint in tree_order(parents):
        name = bone_names[joint]
        base_point = rest[joint]
        pixel = camera.project(base_point[None, :])[0]
        clearance_at_reference = float(_surface_distance(base_point[None, :], indices, vertices)[0])
        entry: dict[str, Any] = {
            "joint": name,
            "pixel": [float(pixel[0]), float(pixel[1])],
            "marker": bool(params.marker(name)),
            "referencePixelPreserved": True,
            "clearanceAtReferenceDepth": clearance_at_reference,
            "clearance": clearance_at_reference,
            "depthShift": 0.0,
            "shiftRefused": None,
        }
        if params.marker(name):
            entry["reason"] = "distal_marker_not_a_flesh_pivot"
            rows.append(entry)
            continue
        if clearance_at_reference > clearance_limit:
            candidates = camera.slide_along_view(
                np.repeat(base_point[None, :], len(deltas), axis=0), deltas
            )
            distances = _surface_distance(candidates, indices, vertices)
            chosen = float(deltas[int(np.argmin(distances))])
            if abs(chosen) > 1e-12:
                candidate = base_point - camera.forward * chosen
                entry["depthShift"] = chosen
                entry["clearance"] = float(
                    _surface_distance(candidate[None, :], indices, vertices)[0]
                )
            else:
                entry["reason"] = "reference_depth_kept"
        else:
            entry["reason"] = "already_in_flesh"
        heads[joint] = base_point - camera.forward * float(entry["depthShift"])
        rows.append(entry)

    # A depth slide is only admissible if the skeleton can still reproduce the animation, and a
    # shifted ancestor can break a descendant's bone length without the descendant itself moving.
    # The invariant is therefore enforced globally: revert shifts, deepest first, until no bone
    # drifts past the bound.  A violation that survives has no shift to blame and is left for the
    # audit to refuse.
    by_joint = {index: entry for index, entry in zip(tree_order(parents), rows)}
    reference_lengths = _bone_lengths(rest, parents)
    shifted = {joint: abs(float(by_joint[joint]["depthShift"])) > 1e-12 for joint in range(len(parents))}
    repairs: list[str] = []
    for _round in range(len(parents) + 1):
        violations = [
            joint
            for joint, parent in enumerate(parents)
            if parent is not None
            and reference_lengths[joint] > 1e-9
            and _length_drift(heads[joint], heads[parent], float(reference_lengths[joint]))
            > params.max_bone_length_drift
        ]
        if not violations:
            break
        reverted = False
        for joint in violations:
            culprit: int | None = joint
            while culprit is not None and not shifted[culprit]:
                culprit = parents[culprit]
            if culprit is None:
                continue
            shifted[culprit] = False
            heads[culprit] = rest[culprit]
            by_joint[culprit]["depthShift"] = 0.0
            by_joint[culprit]["shiftRefused"] = "reverted_to_keep_rigid_bone_lengths"
            repairs.append(bone_names[culprit])
            reverted = True
        if not reverted:
            break
    return {"heads": heads, "referenceHeads": rest, "joints": rows, "shiftRepairs": repairs}


# --------------------------------------------------------------------------- #
# 3. skinning across the animation's own links
# --------------------------------------------------------------------------- #


def bone_tails(
    *,
    positions: np.ndarray,
    parents: list[int | None],
    heads: np.ndarray,
    labels: np.ndarray,
) -> np.ndarray:
    """Tail = toward the children, or the local flesh extent when there are none."""
    children = children_of(parents)
    tails = np.zeros_like(heads)
    for joint in range(len(parents)):
        head = heads[joint]
        kids = [kid for kid in children[joint] if float(np.linalg.norm(heads[kid] - head)) > 1e-9]
        if kids:
            vectors = [heads[kid] - head for kid in kids]
            spans = [float(np.linalg.norm(vector)) for vector in vectors]
            direction = np.mean([vector / span for vector, span in zip(vectors, spans)], axis=0)
            norm = float(np.linalg.norm(direction))
            direction = direction / norm if norm > 1e-9 else np.array([0.0, 1.0, 0.0])
            length = float(np.median(spans))
        else:
            owned = positions[labels == joint]
            if owned.size:
                offsets = owned - head
                distances = np.linalg.norm(offsets, axis=1)
                far = float(distances.max())
                direction = offsets[int(np.argmax(distances))] / max(far, 1e-12)
                length = far
            else:
                parent = parents[joint]
                if parent is None:
                    direction = np.array([0.0, 1.0, 0.0])
                else:
                    span = float(np.linalg.norm(head - heads[parent]))
                    direction = (head - heads[parent]) / span if span > 1e-12 else np.array([0.0, 1.0, 0.0])
                length = 1e-3
        tails[joint] = head + direction * max(length, 1e-6)
    return tails


def provisional_labels(*, positions: np.ndarray, heads: np.ndarray) -> np.ndarray:
    """Nearest-head labelling, used only to find leaf bone extents."""
    distances = np.linalg.norm(positions[:, None, :] - heads[None, :, :], axis=2)
    return np.argmin(distances, axis=1).astype(np.int64)


def mesh_components(mesh_indices: np.ndarray, vertex_count: int) -> np.ndarray:
    """Connected-component id per vertex, over the mesh's own edges.

    An AI-generated surface is routinely a soup of small open patches rather than one sheet, so
    "which vertices are one piece of flesh" is a topological question, not a proximity one.
    """
    tri = np.asarray(mesh_indices, dtype=np.int64).reshape(-1, 3)
    parent = np.arange(int(vertex_count), dtype=np.int64)

    def find(node: int) -> int:
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    if tri.size:
        for pair in (tri[:, [0, 1]], tri[:, [1, 2]], tri[:, [2, 0]]):
            for left, right in pair:
                root_left, root_right = find(int(left)), find(int(right))
                if root_left != root_right:
                    parent[root_left] = root_right
    roots = np.array([find(vertex) for vertex in range(int(vertex_count))], dtype=np.int64)
    return np.unique(roots, return_inverse=True)[1]


def articulation_neighbourhoods(parents: list[int | None]) -> list[set[int]]:
    """For each bone, the bones the animation can move with it: itself, its parent, its children.

    Reported, not enforced.  Restricting a vertex's blend set to these bones was measured to trade
    tearing for holes: the restriction freezes each of the exporter's split patches onto one bone,
    and the flesh that used to bridge two patches is then pulled apart into a gap instead of
    stretched across it.  The count of vertices whose field blends two bones outside this relation
    is reported so the trade stays visible.
    """
    children = children_of(parents)
    out: list[set[int]] = []
    for joint in range(len(parents)):
        group = {joint, *children[joint]}
        if parents[joint] is not None:
            group.add(int(parents[joint]))
        out.append(group)
    return out


def position_groups(positions: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Which vertices occupy exactly the same point, and one representative vertex per group.

    An AI mesh arrives split: the exporter duplicates a vertex wherever the UV or the normal
    changes, so one sheet of flesh is delivered as hundreds of disconnected patches that share no
    indices at all.  Those duplicates are bit-identical - measured on the h3_wood_elf mesh, exact
    equality and a 0.25 mm tolerance give the same 3796 groups - so the grouping is exact and has no
    tolerance to tune.

    Returns ``(group_of_vertex, representative_vertex)``; the representative is the first vertex of
    each group, so a per-group quantity can be read as ``value[representative]``.
    """
    points = np.asarray(positions, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3:
        raise ValueError(f"positions must be (N,3); got {points.shape}")
    _unique, first, inverse = np.unique(points, axis=0, return_index=True, return_inverse=True)
    inverse = np.asarray(inverse).reshape(-1)
    return inverse, np.asarray(first, dtype=np.int64).reshape(-1)[inverse]


def nearby_vertex_pairs(points: np.ndarray, radius: float) -> np.ndarray:
    """Index pairs of vertices that are within ``radius`` of each other, via a uniform grid."""
    if radius <= 0.0:
        raise ValueError(f"cohesion radius must be positive; got {radius}")
    keys = np.floor(np.asarray(points, dtype=np.float64) / radius).astype(np.int64)
    buckets: dict[tuple[int, int, int], list[int]] = {}
    for index, key in enumerate(map(tuple, keys)):
        buckets.setdefault(key, []).append(index)
    pairs: set[tuple[int, int]] = set()
    for key, members in buckets.items():
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    nearby = buckets.get((key[0] + dx, key[1] + dy, key[2] + dz))
                    if not nearby:
                        continue
                    for right in nearby:
                        for left in members:
                            if left >= right:
                                continue
                            if np.linalg.norm(points[left] - points[right]) <= radius:
                                pairs.add((left, right))
    return np.array(sorted(pairs), dtype=np.int64).reshape(-1, 2)


def skin_by_position_field(
    *,
    positions: np.ndarray,
    mesh_indices: np.ndarray,
    heads: np.ndarray,
    tails: np.ndarray,
    parents: list[int | None],
    bone_names: list[str],
    params: ExactBindParams,
) -> dict[str, Any]:
    """Weight every vertex by position: inverse squared-distance to the bones, strongest four.

    The weights are a function of *where the vertex is*, never of which connected patch it belongs
    to.  That single property is what an AI mesh needs, because its surface is delivered split: the
    exporter duplicates the vertices along every UV seam and hard edge, so two vertices at the same
    point belong to different patches and share no topology.  Any rule keyed on patch identity gives
    those two vertices different transforms and opens the seam into a hole the moment the clip moves
    the limb.  A field keyed on position cannot: same point, same weights, same transform.

    It also removes the other failure mode at once.  Labelling each vertex by its own nearest bone
    makes the *allowed* blend set jump at every boundary, and a patch straddling two limbs is then
    stretched between bones the animation never articulates together.  A distance field has no
    discrete jump to put anywhere: nearby vertices get nearby weights, so the transition is a blend
    of the two physically adjacent bones rather than a seam.

    The trade is honest and measured, not hidden: this blends bones the strict articulation relation
    forbids, and the count of vertices that do so is reported in ``positionField``.  Enforcing the
    relation instead was measured to freeze each patch onto one bone, which traded tearing for holes
    (648 seams opened past the contact radius), so the relation is reported rather than enforced.

    Bones the parameters call markers (``marker_tokens``: Mixamo's ``HeadTop_End`` and ``Toe_End``)
    are not candidates at all.  They are not flesh pivots - the capture extrapolates them past the
    surface, so their tracks carry the lift's own error (68% bone-length excursion on this unit) - and
    a region driven by one is dragged by that noise while the flesh beside it is not.
    """
    if params.max_influences != 4:
        raise ValueError("glTF JOINTS_0/WEIGHTS_0 are VEC4; max_influences must be 4")
    count = len(heads)
    names = list(bone_names)
    if len(names) != count:
        raise ValueError(f"bone_names must name every bone; got {len(names)} for {count}")
    vertices = np.asarray(positions, dtype=np.float64)
    is_marker = np.array([bool(params.marker(name)) for name in names], dtype=bool)
    candidates = np.flatnonzero(~is_marker)
    if candidates.size == 0:
        raise ValueError(
            "fail-closed: every bone is a marker, so there is no flesh pivot to bind the mesh with"
        )
    distances = np.stack(
        [_point_segment_distance(vertices, heads[joint], tails[joint]) for joint in candidates],
        axis=1,
    )
    labels = candidates[np.argmin(distances, axis=1)].astype(np.int64)
    raw = 1.0 / np.power(distances + 1e-4, params.power)
    slots = min(len(candidates), int(params.max_influences))
    order = np.argsort(-raw, axis=1)[:, :slots]
    picked = np.take_along_axis(raw, order, axis=1)
    # glTF JOINTS_0/WEIGHTS_0 are VEC4: keep four columns even when the reference has fewer bones.
    joints = np.zeros((len(vertices), int(params.max_influences)), dtype=np.int32)
    weights = np.zeros((len(vertices), int(params.max_influences)), dtype=np.float64)
    joints[:, :slots] = candidates[order].astype(np.int32)
    if params.trim > 0.0:
        picked = np.where(picked >= params.trim, picked, 0.0)
    totals = picked.sum(axis=1, keepdims=True)
    zero = totals[:, 0] <= 0.0
    if np.any(zero):
        picked[zero, :] = 0.0
        picked[zero, 0] = 1.0
        totals = picked.sum(axis=1, keepdims=True)
    weights[:, :slots] = picked / np.maximum(totals, 1e-12)

    # Coincident vertices must not be separated by the repair either, so ownership repair acts on
    # the whole position group rather than on one vertex of it.
    group, representative = position_groups(vertices)
    rep_index = np.flatnonzero(representative == np.arange(len(vertices)))
    forced: list[str] = []
    for joint in range(count):
        if is_marker[joint] or np.any((joints == joint) & (weights > 0.05)):
            continue
        rows = rep_index[labels[rep_index] == joint]
        if rows.size:
            offsets = np.linalg.norm(vertices[rows] - heads[joint], axis=1)
            nearest = int(rows[int(np.argmin(offsets))])
        else:
            offsets = _point_segment_distance(vertices[rep_index], heads[joint], tails[joint])
            nearest = int(rep_index[int(np.argmin(offsets))])
        members = np.flatnonzero(representative == nearest)
        joints[members, :] = 0
        weights[members, :] = 0.0
        joints[members, 0] = joint
        weights[members, 0] = 1.0
        forced.append(f"{joint}")

    mismatch = float(np.abs(weights - weights[representative]).max())
    if mismatch > 0.0:
        raise ValueError(
            f"fail-closed: vertices at the same position carry different weights (worst {mismatch:.3e}); "
            "the field is not a function of position and the split surface would open at that vertex"
        )

    neighbourhoods = articulation_neighbourhoods(parents)
    strongest = joints[rep_index, 0]
    second = np.where(weights[rep_index, 1] > 0.0, joints[rep_index, 1], joints[rep_index, 0])
    unarticulated = np.array(
        [not (neighbourhoods[int(left)] & neighbourhoods[int(right)]) for left, right in zip(strongest, second)],
        dtype=bool,
    )
    sizes = np.bincount(group)
    rep_size = sizes[group[rep_index]]
    return {
        "joints": joints,
        "weights": weights,
        "labels": labels,
        "forcedOwnership": forced,
        "positionField": {
            "schema": "position_field_weights.v1",
            "rule": "inverse_distance_to_flesh_bones_strongest_four",
            "power": float(params.power),
            "trim": float(params.trim),
            "candidateBones": int(len(candidates)),
            "markerBonesExcluded": [names[int(index)] for index in np.flatnonzero(is_marker)],
            "maxInfluencesPerVertex": int((weights > 0.0).sum(axis=1).max()),
            "positions": int(len(rep_index)),
            "verticesInCoincidentGroups": int(sizes[sizes > 1].sum()),
            "largestCoincidentGroup": int(sizes.max()),
            "meshPatches": int(len(np.unique(mesh_components(mesh_indices, len(vertices))))),
            "coincidentWeightMismatch": mismatch,
            "groupsBlendingUnarticulatedBones": int(unarticulated.sum()),
            "verticesBlendingUnarticulatedBones": int(rep_size[unarticulated].sum()),
        },
    }


# --------------------------------------------------------------------------- #
# 4. exact audit
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 3b. props, which a field of position cannot know are rigid
# --------------------------------------------------------------------------- #

PROP_RIGID_CHOICES = ("off", "platefit")
PROP_RIGID_SCHEMA = "prop_rigid_ownership.v1"


def own_props_rigidly(
    *,
    pose: PoseSource,
    similarity: CaptureToWorld,
    vertices: np.ndarray,
    indices: np.ndarray,
    parents: list[int | None],
    bone_names: list[str],
    heads: np.ndarray,
    joints: np.ndarray,
    weights: np.ndarray,
    params: ExactBindParams,
    prop_params: Any | None = None,
    regions: list[np.ndarray] | None = None,
) -> dict[str, Any]:
    """Hand each prop region to one bone when the reference's own plates say one bone fits it.

    A prop is geometry the skeleton does not run through, and the field cannot tell one from flesh: it
    weights by distance, so a bow limb lying along a thigh is driven by the thigh.  What *can* tell is the
    reference, because the plates are ground truth for where the unit is in every authored frame.  So the
    question asked here is not "which bone is nearest" but "which single bone's own rigid transform keeps
    this region inside every frame's plate" - and the answer decides four ways:

    * the field already keeps it inside, so it is not a defect and must not be repaired;
    * one bone does, so the region is owned wholly by that bone: every vertex of it takes weight 1.0 on
      that bone, which is what makes a rigid object move rigidly and stop stretching;
    * one bone does, but the region is welded to geometry that cannot follow it, so owning it rigidly
      would shear the edges that leave it - that is a tear by construction, and the weld is the fault, so
      the region is left alone and the seam is reported;
    * no bone does, so no weighting rule can place it and the region is left alone.  Rigidifying it
      anyway would only move the fault from a stretch to a tear.

    The regions and their verdicts come from ``prop_fit``, which owns both the search and the scoring;
    this function is the part that acts on a verdict, and it never acts on one that is not a fit.
    ``regions`` lets a caller that already knows its props - or that measured them on a mesh whose scale
    the default search radius does not suit - supply them; the verdict logic is identical either way.
    """
    if params.prop_rigid not in PROP_RIGID_CHOICES:
        raise ValueError(
            f"fail-closed: prop_rigid must be one of {PROP_RIGID_CHOICES}; got {params.prop_rigid!r}"
        )
    # Deferred: ``prop_fit`` imports this module, so the dependency can only be resolved at call time.
    from .prop_fit import PropFitParams, VERDICT_BINDABLE, measure_prop_region_fit, prop_regions

    settings = prop_params if prop_params is not None else PropFitParams()
    searched = (
        prop_regions(
            positions=vertices,
            heads=heads,
            parents=parents,
            bone_names=bone_names,
            params=settings,
        )
        if regions is None
        else [np.asarray(members, dtype=np.int64) for members in regions]
    )
    measured = measure_prop_region_fit(
        pose=pose,
        similarity=similarity,
        mesh_positions=vertices,
        mesh_indices=indices,
        parents=parents,
        bone_names=bone_names,
        heads=heads,
        joints=joints,
        weights=weights,
        params=settings,
        regions=searched,
    )
    if measured["regionCount"] != len(searched):
        raise ValueError(
            f"fail-closed: {len(searched)} region(s) were searched but {measured['regionCount']} were "
            "scored, so a verdict cannot be matched to its vertices"
        )
    slot_of_bone = {name: index for index, name in enumerate(bone_names)}
    joints_out = np.asarray(joints, dtype=np.int64).copy()
    weights_out = np.asarray(weights, dtype=np.float64).copy()
    owned = np.zeros(len(vertices), dtype=bool)
    rows: list[dict[str, Any]] = []
    for members, scored in zip(searched, measured["regions"]):
        row = {
            "vertices": int(members.size),
            "verdict": scored["verdict"],
            "worstPxOutsideUnderField": scored["field"]["worstPxOutside"],
            "bestRigidBone": scored["bestRigid"]["bone"],
            "worstPxOutsideUnderBestRigid": scored["bestRigid"]["worstPxOutside"],
            "seam": scored["seam"],
        }
        if scored["verdict"] != VERDICT_BINDABLE:
            row["owned"] = False
            rows.append(row)
            continue
        bone = slot_of_bone[scored["bestRigid"]["bone"]]
        joints_out[members, :] = 0
        weights_out[members, :] = 0.0
        joints_out[members, 0] = bone
        weights_out[members, 0] = 1.0
        owned[members] = True
        row["owned"] = True
        rows.append(row)

    return {
        "joints": joints_out,
        "weights": weights_out,
        "schema": PROP_RIGID_SCHEMA,
        "rule": params.prop_rigid,
        "regionSearch": {
            "farFrac": float(settings.far_frac),
            "linkFrac": float(settings.link_frac),
            "minVertices": int(settings.min_vertices),
            "maxFraction": float(settings.max_fraction),
        },
        "candidateBones": int(measured["candidateBones"]),
        "regionsSearched": len(searched),
        "regionsFound": int(measured["regionCount"]),
        "regionsOwnedRigidly": int(sum(1 for row in rows if row["owned"])),
        "verticesOwnedRigidly": int(owned.sum()),
        "regions": rows,
        "reviewNotes": list(measured["reviewNotes"]),
        "proof": "generated-artifact",
    }


def driver_transforms(
    *,
    heads: np.ndarray,
    parents: list[int | None],
    frame_joints: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Per-bone rigid transform of the position-anchored driver.

    A bone's transform is the minimal rotation taking its rest direction onto the observed
    direction, composed with the translation that puts the bone head exactly on the observed
    joint.  Exposed separately so a consumer can carry surface data other than positions - a
    normal must rotate with its bone rather than be recomputed from the deformed triangles, which
    would flatten the authored hard edges the mesh is built from.
    """
    count = len(heads)
    rotations = np.zeros((count, 3, 3), dtype=np.float64)
    offsets = np.zeros((count, 3), dtype=np.float64)
    for joint in range(count):
        parent = parents[joint]
        rotation = (
            np.eye(3)
            if parent is None
            else _rotation_from_to(heads[joint] - heads[parent], frame_joints[joint] - frame_joints[parent])
        )
        rotations[joint] = rotation
        offsets[joint] = frame_joints[joint] - rotation @ heads[joint]
    return rotations, offsets


def replay_deformed_vertices(
    *,
    positions: np.ndarray,
    heads: np.ndarray,
    parents: list[int | None],
    joints: np.ndarray,
    weights: np.ndarray,
    frame_joints: np.ndarray,
) -> np.ndarray:
    """Position-anchored rigid skin driving: every bone is anchored at its frame joint.

    A bone's transform is the minimal rotation taking its rest direction onto the observed
    direction, composed with the translation that puts the bone head exactly on the
    observed joint.  At the bind frame that is the identity, so the rest surface is
    reproduced exactly and any drift in another frame belongs to the reference or to the
    ownership - never to the driver.
    """
    rotations, offsets = driver_transforms(heads=heads, parents=parents, frame_joints=frame_joints)
    out = np.zeros_like(positions)
    for slot in range(joints.shape[1]):
        bone = joints[:, slot]
        weight = weights[:, slot]
        active = weight > 0.0
        if not np.any(active):
            continue
        rotated = np.einsum("nij,nj->ni", rotations[bone[active]], positions[active])
        out[active] += weight[active, None] * (rotated + offsets[bone[active]])
    return out


def audit_exact_bind(
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
    scale_fit: dict[str, Any],
    params: ExactBindParams,
    extra_issues: list[str] | None = None,
) -> dict[str, Any]:
    """Measure the solved bind against the reference.  ``similarity`` must be the fitted one.

    The reference quantities (rest joints, projected joints) are all read through the
    similarity the bind was actually solved with, so a scale correction can never be
    silently double-counted as bind error.
    """
    issues: list[str] = list(extra_issues or [])
    review: list[str] = []
    vertices = np.asarray(mesh_positions, dtype=np.float64)
    count = len(bone_names)
    boundary_edges = mesh_boundary_edges(mesh_indices)
    subject_height = float(np.ptp(heads[:, 1]))
    clearance_limit = params.flesh_clearance_frac * subject_height

    # --- joint flesh clearance -------------------------------------------------
    clearance = _surface_distance(heads, mesh_indices, vertices)
    joint_rows: list[dict[str, Any]] = []
    for joint in range(count):
        marker = bool(params.marker(bone_names[joint]))
        joint_rows.append(
            {
                "joint": bone_names[joint],
                "marker": marker,
                "clearance": float(clearance[joint]),
                "clearanceLimit": clearance_limit,
                "withinFlesh": bool(clearance[joint] <= clearance_limit),
            }
        )
        if not marker and clearance[joint] > clearance_limit:
            issues.append(
                f"joint {bone_names[joint]} is {clearance[joint]:.4f} from the mesh "
                f"(limit {clearance_limit:.4f}); it is not a flesh pivot"
            )

    # --- rigid bone-length invariants -----------------------------------------
    reference_rest = similarity.apply(pose.capture_positions[pose.bind_index()])
    bind_lengths = _bone_lengths(heads, parents)
    reference_lengths = _bone_lengths(reference_rest, parents)
    drifts: list[float] = []
    bone_rows: list[dict[str, Any]] = []
    for joint in range(count):
        parent = parents[joint]
        drift: float | None = None
        if parent is not None:
            if reference_lengths[joint] <= 1e-9:
                issues.append(f"bone {bone_names[joint]} has no reference length; it cannot be bound")
            else:
                drift = abs(bind_lengths[joint] / reference_lengths[joint] - 1.0)
                drifts.append(drift)
                if drift > params.max_bone_length_drift:
                    issues.append(
                        f"bone {bone_names[joint]} rest length drifts {drift:.1%} from the reference "
                        f"(limit {params.max_bone_length_drift:.1%}); the bind cannot reproduce the "
                        "animation"
                    )
        bone_rows.append(
            {
                "bone": bone_names[joint],
                "parent": None if parent is None else bone_names[parent],
                "restLength": float(bind_lengths[joint]),
                "referenceLength": float(reference_lengths[joint]),
                "drift": None if drift is None else float(drift),
            }
        )

    # --- ownership locality (review evidence, not a gate) ----------------------
    # A prop held in a hand legitimately sits far from its carrier's bone axis, so
    # distance to the bone segment cannot decide ownership; the replay test below can.
    ownership_rows: list[dict[str, Any]] = []
    for joint in range(count):
        marker = bool(params.marker(bone_names[joint]))
        owned = np.flatnonzero(np.any((joints == joint) & (weights > 0.05), axis=1))
        if owned.size == 0:
            if marker:
                # A marker is not a flesh pivot (``marker_tokens``): the capture extrapolates it past
                # the surface, so dragging flesh with it drags the surface with the capture's own
                # error.  It is reported owning nothing rather than forced to own a vertex - forcing
                # one is what tore this unit's toes at 15x their edge length.
                ownership_rows.append(
                    {
                        "bone": bone_names[joint],
                        "marker": True,
                        "ownedVertices": 0,
                        "worstDistance": None,
                        "reviewLimit": None,
                        "crossesReviewLimit": False,
                    }
                )
                continue
            issues.append(f"bone {bone_names[joint]} owns no mesh vertex")
            continue
        span = _segment_span(heads, parents, joint)
        distances = _point_segment_distance(vertices[owned], heads[joint], span)
        span_length = float(np.linalg.norm(span - heads[joint]))
        limit = params.max_own_distance_frac * span_length + clearance_limit
        worst = float(distances.max())
        ownership_rows.append(
            {
                "bone": bone_names[joint],
                "marker": marker,
                "ownedVertices": int(owned.size),
                "worstDistance": worst,
                "reviewLimit": limit,
                "crossesReviewLimit": bool(worst > limit),
            }
        )
    crossing = [row for row in ownership_rows if row["crossesReviewLimit"]]
    if crossing:
        review.append(
            "ownership extends past the review limit on "
            + ", ".join(f"{row['bone']} ({row['worstDistance']:.3f})" for row in crossing)
            + "; a held prop does this legitimately, so this is not a failure - the replay test "
            "below is the authority"
        )

    # --- the exact test: replay the reference and stay inside the plates --------
    frame_joints = similarity.apply(pose.capture_positions[pose.capture_indices])
    coverage = pose.alpha > 0
    dilated = np.stack(
        [_dilate(coverage[index], params.alpha_dilate_px) for index in range(len(coverage))]
    )
    bind_dilated = _dilate(pose.bind_coverage(), params.alpha_dilate_px)
    width, height = pose.sprite_size

    def inside_mask(positions_in: np.ndarray, mask: np.ndarray) -> np.ndarray:
        pixels = pose.camera.project(positions_in)
        xi = np.clip(np.rint(pixels[:, 0]).astype(np.int64), 0, width - 1)
        yi = np.clip(np.rint(pixels[:, 1]).astype(np.int64), 0, height - 1)
        return mask[yi, xi]

    # The bind plate is the pose the mesh was generated from, so it defines which surface the
    # animation must keep inside the coverage - independently of which clip is being audited.
    bind_inside = inside_mask(vertices, bind_dilated)
    if not np.any(bind_inside):
        raise ReferenceInconsistentError(
            "fail-closed: no part of the mesh projects inside the bind plate; the camera, the plate "
            "or the mesh frame is wrong"
        )
    escaped_count = np.zeros(len(coverage), dtype=np.float64)
    outside_by_frame = np.zeros(len(coverage), dtype=np.float64)
    # Edge-length distortion of the driven surface.  Containment says the silhouette is right;
    # it says nothing about whether a patch is being torn between two bones, which is what the
    # eye sees as stretching.  Measured per authored frame on the same replay.
    stretch_triangles = np.asarray(mesh_indices, dtype=np.int64).reshape(-1, 3)
    stretch_edges = np.unique(
        np.vstack(
            [
                stretch_triangles[:, [0, 1]],
                stretch_triangles[:, [1, 2]],
                stretch_triangles[:, [2, 0]],
            ]
        ),
        axis=0,
    )
    rest_edge = np.linalg.norm(
        vertices[stretch_edges[:, 0]] - vertices[stretch_edges[:, 1]], axis=1
    )
    live_edge = rest_edge > 1e-9
    edge_stretch = np.zeros((len(coverage), len(stretch_edges)), dtype=np.float64)
    weight_by_bone = np.zeros((len(vertices), count), dtype=np.float64)
    for slot in range(joints.shape[1]):
        np.add.at(weight_by_bone, (np.arange(len(vertices)), joints[:, slot]), weights[:, slot])
    weight_jump_across_edge = np.abs(
        weight_by_bone[stretch_edges[:, 0]] - weight_by_bone[stretch_edges[:, 1]]
    ).sum(axis=1)
    # Cohesion: vertices that touch at rest must still touch after the clip moves them.  Edge
    # stretch alone cannot see a hole - freezing a patch onto one bone *lowers* the stretch of the
    # edges inside it and pulls the flesh apart at the seam instead - so the surface itself is
    # measured, on the same replay, keyed on rest proximity rather than on connectivity.
    cohesion_radius = float(params.cohesion_radius_frac) * subject_height
    cohesion_pairs = nearby_vertex_pairs(vertices, cohesion_radius)
    components = mesh_components(mesh_indices, len(vertices))
    if len(cohesion_pairs):
        cohesion_rest = np.linalg.norm(
            vertices[cohesion_pairs[:, 0]] - vertices[cohesion_pairs[:, 1]], axis=1
        )
    else:
        cohesion_rest = np.zeros(0, dtype=np.float64)
    cohesion_growth = np.zeros(len(cohesion_pairs), dtype=np.float64)
    cohesion_frame = np.zeros(len(cohesion_pairs), dtype=np.int64)
    # Escape bookkeeping, per vertex: which vertices leave their own frame's plate.  A global escape
    # fraction says the bind is wrong somewhere, not which geometry is wrong - a prop fused to the
    # wrong limb is a small region that leaves the silhouette while the body stays inside.
    escape_by_vertex = np.zeros(len(vertices), dtype=np.int64)
    escape_rows: list[np.ndarray] = []
    frame_rows: list[dict[str, Any]] = []
    for index in range(len(coverage)):
        deformed = replay_deformed_vertices(
            positions=vertices,
            heads=heads,
            parents=parents,
            joints=joints,
            weights=weights,
            frame_joints=frame_joints[index],
        )
        inside = inside_mask(deformed, dilated[index])
        outside_by_frame[index] = 1.0 - float(inside.mean())
        deformed_edge = np.linalg.norm(
            deformed[stretch_edges[:, 0]] - deformed[stretch_edges[:, 1]], axis=1
        )
        edge_stretch[index, live_edge] = np.abs(
            deformed_edge[live_edge] / rest_edge[live_edge] - 1.0
        )
        if len(cohesion_pairs):
            growth = (
                np.linalg.norm(
                    deformed[cohesion_pairs[:, 0]] - deformed[cohesion_pairs[:, 1]], axis=1
                )
                - cohesion_rest
            )
            worse = growth > cohesion_growth
            cohesion_growth = np.where(worse, growth, cohesion_growth)
            cohesion_frame = np.where(worse, index, cohesion_frame)
        # The vertices the bind plate already holds inside its own silhouette are the population
        # the animation must keep there: a correct rigid replay cannot push its own surface out of
        # the coverage its own pose produced.  The null is therefore exactly zero, so neither a
        # baseline subtraction nor a tuned offset enters the acceptance.
        escape = int(np.sum(bind_inside & ~inside))
        escaped_count[index] = escape / float(bind_inside.sum())
        escaped_rows = np.flatnonzero(bind_inside & ~inside)
        escape_by_vertex[escaped_rows] += 1
        escape_rows.append(escaped_rows)
        frame_rows.append(
            {
                "index": index,
                "defGroup": int(pose.frames[index].def_group),
                "clipKey": pose.frames[index].clip_key,
                "outsideFraction": float(outside_by_frame[index]),
                "escapedFraction": float(escaped_count[index]),
                "escapedVertices": escape,
            }
        )
    baseline = 1.0 - float(bind_inside.mean())

    # --- tearing (review evidence, not a gate) ---------------------------------
    # This is how much the driven surface distorts its own edges.  It is deliberately not the
    # acceptance test: a weight rule can lower it by freezing each patch onto one bone, and the
    # surface then opens into holes instead - which is why cohesion is measured beside it.
    worst_edge = edge_stretch.max(axis=0)
    torn = np.flatnonzero(worst_edge > params.max_edge_stretch_review)
    pathological = np.flatnonzero(worst_edge > 10.0 * params.max_edge_stretch_review)
    tearing = {
        "schema": "edge_stretch.v1",
        "edges": int(len(stretch_edges)),
        "median": float(np.median(edge_stretch)),
        "p99": float(np.percentile(edge_stretch, 99)),
        "max": float(worst_edge.max()),
        "edgesPastReviewLimit": int(torn.size),
        "edgesPastTenTimesReviewLimit": int(pathological.size),
        "reviewLimit": float(params.max_edge_stretch_review),
        "edgesWithWeightJumpOverHalf": int((weight_jump_across_edge > 0.5).sum()),
        "meanStretchAtWeightJump": (
            float(worst_edge[weight_jump_across_edge > 0.5].mean())
            if np.any(weight_jump_across_edge > 0.5)
            else 0.0
        ),
        "meanStretchElsewhere": float(worst_edge[weight_jump_across_edge <= 0.5].mean()),
    }
    if pathological.size:
        review.append(
            f"{pathological.size} mesh edges stretch past {10.0 * params.max_edge_stretch_review:.0f}x "
            f"(worst {worst_edge.max():.0%}); a vertex blended between two bones the animation moves "
            "apart looks like this"
        )

    # --- cohesion (review evidence, not a gate) --------------------------------
    # The counterpart to tearing, and the reason it cannot be the only distortion measure: a surface
    # that is frozen onto one bone per patch has almost no stretched edge, and a hole along every
    # seam.  Measured on rest-adjacent vertex pairs, so it sees the split surface a duplicated-vertex
    # mesh actually is - and it is exact where the field is position-keyed, because two vertices at
    # one point are driven by one transform.
    cohesion: dict[str, Any] = {
        "schema": "surface_cohesion.v1",
        "radius": cohesion_radius,
        "pairs": int(len(cohesion_pairs)),
        "pairsAcrossPatches": int(
            (components[cohesion_pairs[:, 0]] != components[cohesion_pairs[:, 1]]).sum()
        )
        if len(cohesion_pairs)
        else 0,
    }
    if len(cohesion_pairs):
        dominant = np.argmax(weight_by_bone, axis=1)
        worst_pair = int(np.argmax(cohesion_growth))
        left, right = (int(cohesion_pairs[worst_pair, 0]), int(cohesion_pairs[worst_pair, 1]))
        cohesion.update(
            {
                "worstGap": float(cohesion_growth.max()),
                "worstGapAtFrame": int(cohesion_frame[worst_pair]),
                "worstGapRestSeparation": float(cohesion_rest[worst_pair]),
                "worstGapDominantBones": [
                    bone_names[int(dominant[left])],
                    bone_names[int(dominant[right])],
                ],
                "worstGapIsAcrossPatches": bool(components[left] != components[right]),
                "pairsOpenedPastHalfRadius": int((cohesion_growth > 0.5 * cohesion_radius).sum()),
                "pairsOpenedPastRadius": int((cohesion_growth > cohesion_radius).sum()),
            }
        )
        if cohesion["pairsOpenedPastRadius"]:
            review.append(
                f"{cohesion['pairsOpenedPastRadius']} vertex pairs that touch within "
                f"{cohesion_radius:.4f} at rest are pulled past that distance during the clip (worst "
                f"{cohesion['worstGap']:.4f} at frame {cohesion['worstGapAtFrame']} between "
                f"{cohesion['worstGapDominantBones'][0]} and {cohesion['worstGapDominantBones'][1]}); "
                "the surface is opening, so the weights do not drive both sides of a seam together"
            )

    # --- where the surface leaves its own plate (review evidence, not a gate) ---
    # Acceptance counts escapes over the whole surface, which is the right null and the wrong
    # diagnostic: a prop fused to the wrong limb escapes in a small region while the body stays
    # inside, and one number over 7207 vertices hides exactly that.  Group the escaping vertices
    # spatially and name, for each group, the bone that drives it and the reference joint the frame's
    # own plate actually has there - that is what "this geometry is attached to the wrong part"
    # looks like as a measurement.  Nothing here gates; the acceptance null stays exact.
    region_radius = float(params.escape_region_radius_frac) * subject_height
    dominant_by_vertex = np.argmax(weight_by_bone, axis=1)
    hot = np.flatnonzero(escape_by_vertex > 0)
    escaping_regions: list[dict[str, Any]] = []
    if hot.size:
        links = nearby_vertex_pairs(vertices[hot], region_radius)
        parent = np.arange(hot.size, dtype=np.int64)

        def region_root(node: int) -> int:
            root = node
            while parent[root] != root:
                root = parent[root]
            while parent[node] != root:
                parent[node], node = root, parent[node]
            return root

        for left, right in links:
            root_left, root_right = region_root(int(left)), region_root(int(right))
            if root_left != root_right:
                parent[root_left] = root_right
        groups: dict[int, list[int]] = {}
        for position in range(hot.size):
            groups.setdefault(region_root(position), []).append(position)
        escape_flat = np.concatenate(escape_rows) if escape_rows else np.zeros(0, dtype=np.int64)
        escape_flat_frames = np.repeat(
            np.arange(len(coverage)), [len(rows) for rows in escape_rows]
        )
        rows_out: list[dict[str, Any]] = []
        for members_position in groups.values():
            members = hot[np.asarray(members_position, dtype=np.int64)]
            if members.size < 3:
                continue
            touched = np.isin(escape_flat, members)
            frames = np.unique(escape_flat_frames[touched])
            centre = vertices[members].mean(axis=0)
            worst_frame = int(frames[int(np.argmax([
                int(np.count_nonzero(np.isin(escape_rows[index], members))) for index in frames
            ]))])
            joint_distances = np.linalg.norm(frame_joints[worst_frame] - centre, axis=1)
            nearest_joint = int(np.argmin(joint_distances))
            driving: dict[str, int] = {}
            for joint in dominant_by_vertex[members]:
                driving[bone_names[int(joint)]] = driving.get(bone_names[int(joint)], 0) + 1
            ordered_driving = dict(
                sorted(driving.items(), key=lambda item: -item[1])[:4]
            )
            pixel = pose.camera.project(centre[None, :])[0]
            region_rows, region_cols = np.nonzero(coverage[worst_frame])
            projected = pose.camera.project(vertices[members])
            column = np.clip(np.rint(projected[:, 0]).astype(np.int64), 0, width - 1)
            row = np.clip(np.rint(projected[:, 1]).astype(np.int64), 0, height - 1)
            outside_px = np.zeros(members.size, dtype=np.float64)
            if region_rows.size:
                for start in range(0, members.size, 128):
                    stop = min(start + 128, members.size)
                    outside_px[start:stop] = np.sqrt(
                        (region_rows[None, :] - row[start:stop, None]) ** 2
                        + (region_cols[None, :] - column[start:stop, None]) ** 2
                    ).min(axis=1)
            rows_out.append(
                {
                    "vertices": int(members.size),
                    "patches": int(len(np.unique(components[members]))),
                    "framesEscaped": int(frames.size),
                    "firstFrame": int(frames.min()),
                    "worstEscapeFrame": worst_frame,
                    "centroid": [float(value) for value in centre],
                    "centroidPlatePixel": [float(pixel[0]), float(pixel[1])],
                    "bboxMin": [float(value) for value in vertices[members].min(axis=0)],
                    "bboxMax": [float(value) for value in vertices[members].max(axis=0)],
                    "bboxPlatePixels": [
                        [float(value) for value in pose.camera.project(vertices[members]).min(axis=0)],
                        [float(value) for value in pose.camera.project(vertices[members]).max(axis=0)],
                    ],
                    "drivingBones": ordered_driving,
                    "referenceJointNearestCentroid": bone_names[nearest_joint],
                    "referenceJointDistance": float(joint_distances[nearest_joint]),
                    "medianDistanceOutsidePlatePx": float(np.median(outside_px)),
                    "maxDistanceOutsidePlatePx": float(outside_px.max()),
                }
            )
        rows_out.sort(
            key=lambda row: (
                -round(row["maxDistanceOutsidePlatePx"], 2),
                -row["framesEscaped"],
                -row["vertices"],
            )
        )
        # Ordered by how far outside the plate the region reaches, which is the ordering a reader
        # acts on - but never truncated, because the alternative orderings matter too: the worst
        # reach and the largest area are usually different regions, and a truncation that kept only
        # one of them would hide the other (a 3-vertex region reaches furthest here; the 93-vertex
        # one is the defect a person sees).
        escaping_regions = rows_out
        if escaping_regions:
            worst = escaping_regions[0]
            driving_names = ", ".join(
                f"{name} ({count})" for name, count in worst["drivingBones"].items()
            )
            review.append(
                f"{len(rows_out)} region(s) of geometry leave the frame's own plate while the body "
                f"stays inside; the worst reaches {worst['maxDistanceOutsidePlatePx']:.1f}px past it "
                f"({worst['vertices']} vertices in {worst['patches']} patch(es) over "
                f"{worst['framesEscaped']} frame(s), driven by {driving_names}, where the plate has "
                f"{worst['referenceJointNearestCentroid']} "
                f"({worst['referenceJointDistance']:.3f} away)) - geometry attached to the wrong part "
                "looks like this"
            )
    escaping = {
        "schema": "escape_regions.v1",
        "radius": region_radius,
        "verticesEscapingAtLeastOnce": int(hot.size),
        # The list is ordered by reach and *not* truncated, because the orderings disagree as often as
        # they agree: the furthest-reaching region and the largest one are usually different rows.  So
        # `regionCount` counts the rows listed here - groups of three or more escaping vertices within
        # one region radius - and is deliberately not the same quantity as
        # `verticesEscapingAtLeastOnce`, which counts every escaping vertex including lone specks.
        "regionCount": int(len(rows_out)) if hot.size else 0,
        "regions": escaping_regions,
    }
    # How far the clip moves the pose from the bind pose, and how rigid the reference is.  A
    # reference whose bone lengths move cannot be reproduced by any rigid skeleton, so the
    # acceptance floor is raised to that measured slack instead of being a tuned per-clip number.
    reference_px = pose.camera.project(frame_joints)
    bind_px = pose.camera.project(heads)
    pose_excursion = float(np.linalg.norm(reference_px - bind_px[None, :, :], axis=2).max())
    custody = pose.capture_positions[pose.capture_indices]
    excursions: list[dict[str, Any]] = []
    for joint, parent in enumerate(parents):
        if parent is None:
            continue
        lengths = np.linalg.norm(custody[:, joint] - custody[:, parent], axis=1)
        low = float(lengths.min())
        if low <= 1e-9:
            continue
        excursions.append(
            {
                "bone": bone_names[joint],
                "marker": bool(params.marker(bone_names[joint])),
                "excursion": float(lengths.max() / low - 1.0),
            }
        )
    if not excursions:
        raise ReferenceInconsistentError(
            "fail-closed: the reference has no bone with a usable length; it cannot be replayed"
        )
    by_size = sorted(excursions, key=lambda row: -row["excursion"])
    median_excursion = float(np.median([row["excursion"] for row in excursions]))
    max_excursion = float(by_size[0]["excursion"])
    budget = max(params.max_outside_excess_rest_adjacent, median_excursion)
    if median_excursion > params.max_reference_median_length_excursion:
        issues.append(
            f"the reference's bone lengths move by {median_excursion:.1%} at the median "
            f"(limit {params.max_reference_median_length_excursion:.0%}); the joint track is not a "
            "rigid skeleton, so no bind can reproduce it and exactness cannot be claimed"
        )
    if max_excursion > params.max_reference_median_length_excursion:
        worst = [row for row in by_size if row["excursion"] > params.max_reference_median_length_excursion]
        review.append(
            "reference bone lengths move most on "
            + ", ".join(f"{row['bone']} ({row['excursion']:.0%})" for row in worst[:4])
            + "; those joints are lifted less reliably than the rest, and the replay budget is held "
            f"at the median {median_excursion:.1%} rather than at their {max_excursion:.0%}"
        )
    outside_excess = outside_by_frame - baseline
    worst_index = int(np.argmax(outside_excess))
    frame_rows[worst_index]["worst"] = True
    if float(outside_excess.max()) > budget:
        frame = frame_rows[worst_index]
        issues.append(
            f"replaying the reference leaves {outside_excess.max():.1%} more of the surface outside "
            f"DEF group {frame['defGroup']} frame {frame['index']} ({frame['clipKey']}) than the bare "
            f"mesh leaves outside the bind plate (budget {budget:.1%}, reference rigidity "
            f"{median_excursion:.1%}, pose excursion {pose_excursion:.1f}px); joints or ownership do "
            "not follow the animation"
        )
    if baseline > params.max_plate_baseline_outside:
        review.append(
            f"the bare mesh already projects {baseline:.1%} of its vertices outside the bind "
            f"plate (review limit {params.max_plate_baseline_outside:.0%}); that is a mesh-to-plate "
            "registration property owned by the static registration lane, not a bind defect, but "
            "it should be improved upstream"
        )

    # --- the plates must also contain the reference joints ----------------------
    projected = pose.camera.project(similarity.apply(pose.capture_positions[pose.capture_indices]))
    joint_alpha_rows: list[dict[str, Any]] = []
    offenders: list[str] = []
    for joint in range(count):
        distances = np.empty(len(coverage), dtype=np.float64)
        on_plate = 0
        for index in range(len(coverage)):
            col, row = projected[index, joint]
            col_i = int(np.clip(round(float(col)), 0, width - 1))
            row_i = int(np.clip(round(float(row)), 0, height - 1))
            if dilated[index][row_i, col_i]:
                on_plate += 1
                distances[index] = 0.0
                continue
            rows, cols = np.nonzero(coverage[index])
            if rows.size == 0:
                raise ReferenceInconsistentError(
                    f"fail-closed: plate {index} has no covered pixels to measure against"
                )
            distances[index] = float(
                np.sqrt((rows - row) ** 2 + (cols - col) ** 2).min()
            )
        marker = bool(params.marker(bone_names[joint]))
        joint_alpha_rows.append(
            {
                "joint": bone_names[joint],
                "marker": marker,
                "onPlateFraction": float(on_plate / max(len(coverage), 1)),
                "medianOffPlatePx": float(np.median(distances)),
                "maxOffPlatePx": float(distances.max()),
            }
        )
        if not marker and float(np.median(distances)) > params.max_reference_joint_offplate_px:
            offenders.append(
                f"{bone_names[joint]} (median {float(np.median(distances)):.1f}px, max "
                f"{float(distances.max()):.1f}px off the plate, budget "
                f"{params.max_reference_joint_offplate_px:.1f}px)"
            )
    if offenders:
        issues.append(
            "the reference places a flesh pivot off the plate it was captured from, so the "
            "capture and the plate disagree and the bind for that bone is unvalidated: "
            + "; ".join(offenders)
        )

    containment = (
        "closed_mesh_ray_parity_available"
        if boundary_edges == 0
        else "open_mesh_proximity_heuristic_unproven"
    )
    if boundary_edges:
        review.append(
            f"mesh has {boundary_edges} boundary edge(s); joint containment is measured as surface "
            "proximity, not a watertight parity proof - remesh before treating containment as proven"
        )

    return {
        "schema": AUDIT_SCHEMA,
        "ok": not issues,
        "issues": issues,
        "reviewNotes": review,
        "containmentProof": containment,
        "boundaryEdges": int(boundary_edges),
        "jointCount": count,
        "frameCount": int(len(coverage)),
        "bindFrame": int(pose.bind_index()),
        "subjectHeight": subject_height,
        "clearanceLimit": clearance_limit,
        "maxBoneLengthDrift": float(max(drifts)) if drifts else 0.0,
        "outsideFractionAtBind": baseline,
        "maxOutsideExcess": float(outside_excess.max()),
        "outsideExcessBudget": float(budget),
        "poseExcursionPx": pose_excursion,
        "referenceRigidity": {
            "medianLengthExcursion": median_excursion,
            "maxLengthExcursion": max_excursion,
            "worstBones": by_size[:4],
            "bones": excursions,
        },
        "maxEscapedFraction": float(escaped_count.max()),
        "escapePopulation": int(bind_inside.sum()),
        "tearing": tearing,
        "cohesion": cohesion,
        "escaping": escaping,
        "worstFrame": {
            "index": worst_index,
            "defGroup": int(pose.frames[worst_index].def_group),
            "clipKey": pose.frames[worst_index].clip_key,
            "outsideExcess": float(outside_excess[worst_index]),
            "escapedFraction": float(escaped_count[worst_index]),
        },
        "scaleFit": scale_fit,
        "joints": joint_rows,
        "bones": bone_rows,
        "ownership": ownership_rows,
        "frames": frame_rows,
        "referenceJointCoverage": joint_alpha_rows,
        "proof": "generated-artifact",
    }


def _segment_span(heads: np.ndarray, parents: list[int | None], joint: int) -> np.ndarray:
    """Distal end of a bone's span: the farthest of its children, else its parent."""
    children = [child for child, parent in enumerate(parents) if parent == joint]
    if children:
        return heads[max(children, key=lambda child: float(np.linalg.norm(heads[child] - heads[joint])))]
    parent = parents[joint]
    if parent is None:
        return heads[joint]
    span = heads[joint] - heads[parent]
    return heads[joint] + span


# --------------------------------------------------------------------------- #
# solver
# --------------------------------------------------------------------------- #


def bind_from_exact_reference(
    *,
    pose: PoseSource,
    mesh_positions: np.ndarray,
    mesh_indices: np.ndarray,
    params: ExactBindParams | None = None,
) -> dict[str, Any]:
    """Solve and audit an owned bind from an exact animation reference."""
    params = params or ExactBindParams()
    vertices = np.asarray(mesh_positions, dtype=np.float64)
    indices = np.asarray(mesh_indices, dtype=np.int64).reshape(-1)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) == 0:
        raise ValueError(f"mesh positions must be a nonempty (N,3); got {vertices.shape}")
    if not np.isfinite(vertices).all():
        raise ValueError("mesh positions contain non-finite values")
    if mesh_indices.size == 0:
        raise ValueError("mesh indices are empty; the surface cannot be measured")
    if pose.camera.world_frame != "y_up_gltf":
        raise ReferenceInconsistentError(
            f"fail-closed: the reference camera is in {pose.camera.world_frame!r} but the mesh frame "
            "was not declared; refusing to reinterpret the axis"
        )

    similarity, scale_fit = fit_reference_scale(
        pose=pose, mesh_positions=vertices, mesh_indices=indices, params=params
    )
    parents = pose.parents
    names = bone_names_from_capture(pose.joint_names)

    placement = place_joints(
        pose=pose,
        similarity=similarity,
        mesh_positions=vertices,
        mesh_indices=indices,
        parents=parents,
        bone_names=names,
        params=params,
    )
    heads = placement["heads"]
    seed_labels = provisional_labels(positions=vertices, heads=heads)
    tails = bone_tails(positions=vertices, parents=parents, heads=heads, labels=seed_labels)
    skin = skin_by_position_field(
        positions=vertices,
        mesh_indices=indices,
        heads=heads,
        tails=tails,
        parents=parents,
        bone_names=names,
        params=params,
    )

    # Props are the one thing a field of position cannot reason about, and the reference is the only
    # authority for them, so the correction runs here - before the rest-identity check, which then holds
    # the override to the same exactness the field is held to.
    prop_ownership: dict[str, Any] | None = None
    if params.prop_rigid != "off":
        prop_ownership = own_props_rigidly(
            pose=pose,
            similarity=similarity,
            vertices=vertices,
            indices=indices,
            parents=parents,
            bone_names=names,
            heads=heads,
            joints=skin["joints"],
            weights=skin["weights"],
            params=params,
        )
        skin["joints"] = prop_ownership["joints"]
        skin["weights"] = prop_ownership["weights"]

    # The driver must reproduce the bind rest surface exactly, or the bind deforms its own
    # rest pose and every later measurement is meaningless.
    rest_replay = replay_deformed_vertices(
        positions=vertices,
        heads=heads,
        parents=parents,
        joints=skin["joints"],
        weights=skin["weights"],
        frame_joints=similarity.apply(pose.capture_positions[pose.bind_index()]),
    )
    rest_error = float(np.abs(rest_replay - vertices).max())
    extra_issues: list[str] = []
    if rest_error > 1e-9:
        extra_issues.append(
            f"rest skin is not the identity (worst {rest_error:.3e}); the bind would deform its own "
            "rest pose"
        )

    audit = audit_exact_bind(
        pose=pose,
        similarity=similarity,
        mesh_positions=vertices,
        mesh_indices=indices,
        parents=parents,
        bone_names=names,
        heads=heads,
        joints=skin["joints"],
        weights=skin["weights"],
        scale_fit=scale_fit,
        params=params,
        extra_issues=extra_issues,
    )
    return {
        "schema": BIND_SCHEMA,
        "unit": pose.extra.get("unit"),
        "boneNames": names,
        "parents": parents,
        "heads": heads,
        "tails": tails,
        "joints": skin["joints"],
        "weights": skin["weights"],
        "labels": skin["labels"],
        "restIdentityMaxError": rest_error,
        "similarity": similarity.as_report(),
        "scaleFit": scale_fit,
        "jointPlacement": placement["joints"],
        "jointDepthShiftRepairs": placement["shiftRepairs"],
        "skin": {
            "forcedOwnership": skin["forcedOwnership"],
            "positionField": skin["positionField"],
            "propRigid": (
                None
                if prop_ownership is None
                else {key: value for key, value in prop_ownership.items() if key not in ("joints", "weights")}
            ),
        },
        "audit": audit,
        "reference": {
            "capture": pose.source_capture,
            "registration": pose.source_registration,
            "mesh": pose.mesh_source,
            "frameCount": pose.frame_count,
            "jointCount": pose.joint_count,
            "bindFrame": int(pose.bind_index()),
            "cameraPolicy": pose.camera.camera_policy,
            "similarityPolicy": pose.similarity.policy,
        },
        "params": {
            key: (list(value) if isinstance(value, tuple) else value)
            for key, value in params.__dict__.items()
        },
        "proof": "generated-artifact",
    }


bind_from_exact_reference = bind_from_exact_reference
audit_exact_bind = audit_exact_bind
fit_reference_scale = fit_reference_scale
rescale_to_extent = rescale_to_extent
place_joints = place_joints
skin_by_position_field = skin_by_position_field
position_groups = position_groups
nearby_vertex_pairs = nearby_vertex_pairs
replay_deformed_vertices = replay_deformed_vertices
bone_names_from_capture = bone_names_from_capture
bone_tails = bone_tails
children_of = children_of
tree_order = tree_order
provisional_labels = provisional_labels
