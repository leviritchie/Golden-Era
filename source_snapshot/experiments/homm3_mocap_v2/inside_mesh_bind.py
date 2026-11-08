"""Bind-first rest placement: suck the standing skeleton into the mesh.

Mocap still owns later-frame *relative* swings. The standing pose may change
length and rest joint angles until every joint (and bone segment) sits inside
the mesh. Named Mixamo limbs then occupy anatomical slots: a foot cannot sit
in a knee. After that, body bones keep working until they saturate non-weapon
flesh without collapsing that order. Thin weapon spikes are not a target.
Frame 0 of playback must remain this bind pose.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from skeleton_overlay import BIND_VIEWS

MIN_BONE_LENGTH_SCALE = 0.35
LENGTH_SEARCH_STEPS = 20
INSIDE_SLACK = 1e-9
MIN_SLAB_VERTICES = 4


class InsideMeshBindError(ValueError):
    """Raised when no rest-length assignment places every joint inside the mesh."""


def apply_bone_length_scales(
    joints: np.ndarray,
    parents: np.ndarray,
    scales: np.ndarray,
) -> np.ndarray:
    """Keep parent-to-child directions. Scale each bone length. Root stays put."""
    joints = np.asarray(joints, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    scales = np.asarray(scales, dtype=np.float64)
    if joints.ndim != 2 or joints.shape[1] != 3:
        raise InsideMeshBindError(f"joints must be [J,3], got {joints.shape}")
    if parents.shape != (len(joints),) or scales.shape != (len(joints),):
        raise InsideMeshBindError("parents and scales must be [J]")
    if parents[0] != -1 or any(int(parent) < 0 or int(parent) >= index for index, parent in enumerate(parents[1:], 1)):
        raise InsideMeshBindError("hierarchy must be root-first ordered")
    if not np.isfinite(joints).all() or not np.isfinite(scales).all():
        raise InsideMeshBindError("joints and scales must be finite")
    if np.any(scales[1:] <= 0):
        raise InsideMeshBindError("bone length scales must be positive")
    placed = np.zeros_like(joints)
    for index, parent in enumerate(parents):
        if parent < 0:
            placed[index] = joints[index]
            continue
        placed[index] = placed[parent] + float(scales[index]) * (joints[index] - joints[parent])
    return placed


def bone_directions_match(
    original: np.ndarray,
    placed: np.ndarray,
    parents: np.ndarray,
    *,
    atol: float = 1e-9,
) -> bool:
    """True when every non-root bone kept its parent-to-child direction."""
    original = np.asarray(original, dtype=np.float64)
    placed = np.asarray(placed, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    for index, parent in enumerate(parents):
        if parent < 0:
            continue
        source = original[index] - original[parent]
        dest = placed[index] - placed[parent]
        source_len = float(np.linalg.norm(source))
        dest_len = float(np.linalg.norm(dest))
        if source_len <= 1e-12 and dest_len <= 1e-12:
            continue
        if source_len <= 1e-12 or dest_len <= 1e-12:
            return False
        if float(np.linalg.norm(source / source_len - dest / dest_len)) > atol:
            return False
    return True


def _mesh_bounds(vertices: np.ndarray) -> dict[str, Any]:
    vertices = np.asarray(vertices, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 2:
        raise InsideMeshBindError("mesh vertices must be [N,3]")
    lo = vertices.min(axis=0)
    hi = vertices.max(axis=0)
    if not np.isfinite(lo).all() or not np.isfinite(hi).all() or float(np.linalg.norm(hi - lo)) <= 1e-12:
        raise InsideMeshBindError("mesh AABB is degenerate")
    views = {}
    for name, axes in BIND_VIEWS:
        xy = vertices[:, list(axes)]
        vlo, vhi = xy.min(axis=0), xy.max(axis=0)
        if float(np.linalg.norm(vhi - vlo)) <= 1e-12:
            raise InsideMeshBindError(f"{name} projected mesh AABB is degenerate")
        views[name] = (vlo, vhi, axes)
    return {"lo": lo, "hi": hi, "views": views}


def view_slab_inside(
    vertices: np.ndarray,
    joints: np.ndarray,
    axes: tuple[int, int],
    *,
    slab_fraction: float = 0.08,
) -> np.ndarray:
    """True when each joint's horizontal sits in the mesh width at that height.

    A 2D AABB still treats empty corners as inside. This uses only mesh
    vertices near the joint's vertical coordinate in this view.
    """
    mesh_xy = np.asarray(vertices, dtype=np.float64)[:, list(axes)]
    joint_xy = np.asarray(joints, dtype=np.float64)[:, list(axes)]
    vertical_span = float(mesh_xy[:, 1].max() - mesh_xy[:, 1].min())
    if vertical_span <= 1e-12:
        raise InsideMeshBindError("projected mesh span is degenerate")
    min_count = min(max(int(MIN_SLAB_VERTICES), 1), len(mesh_xy))
    min_band = max(float(slab_fraction) * vertical_span * 0.25, 1e-9)
    inside = np.zeros(len(joint_xy), dtype=bool)
    for index, point in enumerate(joint_xy):
        dist = np.abs(mesh_xy[:, 1] - point[1])
        band = max(float(np.partition(dist, min_count - 1)[min_count - 1]), min_band)
        nearby = mesh_xy[dist <= band + 1e-12]
        lo, hi = float(nearby[:, 0].min()), float(nearby[:, 0].max())
        inside[index] = lo - INSIDE_SLACK <= float(point[0]) <= hi + INSIDE_SLACK
    return inside


def joints_inside_mask(vertices: np.ndarray, joints: np.ndarray) -> np.ndarray:
    """True per joint when it sits in the 3D AABB and every front/side/top slab."""
    joints = np.asarray(joints, dtype=np.float64)
    bounds = _mesh_bounds(vertices)
    inside = np.all((joints >= bounds["lo"] - INSIDE_SLACK) & (joints <= bounds["hi"] + INSIDE_SLACK), axis=1)
    for _name, axes in BIND_VIEWS:
        inside &= view_slab_inside(vertices, joints, axes)
    return inside


def joints_entirely_inside(vertices: np.ndarray, joints: np.ndarray) -> tuple[bool, dict[str, Any]]:
    from skeleton_overlay import multi_view_placement_report

    report = multi_view_placement_report(vertices, joints, margin_fraction=0.0)
    inside = bool(np.all(joints_inside_mask(vertices, joints)))
    return inside, report


def joints_inside_registered_source_view(
    mesh_vertices: np.ndarray,
    rest_joints: np.ndarray,
    *,
    mesh_rotation: np.ndarray,
    skeleton_rotation: np.ndarray,
    scale: float,
    translation: np.ndarray,
) -> tuple[bool, dict[str, Any]]:
    """Containment in the registered mesh/source-view frame, not capture axes.

    Front/side/top slabs are camera axes on the mesh. Inverse similarity puts
    those vertices on capture axes; a 45° yaw then makes capture-space slabs a
    different test. Uniform shrink used to hide that mismatch.
    """
    from static_bind_registration import apply_similarity

    mesh_source = np.asarray(mesh_vertices, dtype=np.float64) @ np.asarray(mesh_rotation, dtype=np.float64).T
    placed = apply_similarity(
        rest_joints,
        rotation=np.asarray(skeleton_rotation, dtype=np.float64),
        scale=float(scale),
        translation=np.asarray(translation, dtype=np.float64),
    )
    return joints_entirely_inside(mesh_source, placed)


def subtree_indices(parents: np.ndarray, joint: int) -> list[int]:
    members: list[int] = []
    for index in range(len(parents)):
        walk = index
        while walk >= 0:
            if walk == joint:
                members.append(index)
                break
            walk = int(parents[walk])
    return members


def fit_bone_lengths_inside_mesh(
    joints: np.ndarray,
    parents: np.ndarray,
    vertices: np.ndarray,
    *,
    min_scale: float = MIN_BONE_LENGTH_SCALE,
) -> dict[str, Any]:
    """Shorten distal bones first, then ancestors, until every joint is inside.

    Lengths may shrink. Directions must not change. Lengthening is refused
    because it can push a later joint back out.
    """
    joints = np.asarray(joints, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    vertices = np.asarray(vertices, dtype=np.float64)
    if not np.isfinite(min_scale) or min_scale <= 0 or min_scale > 1.0:
        raise InsideMeshBindError("min_scale must be in (0, 1]")
    if not bool(np.all(joints_inside_mask(vertices, joints[0:1]))):
        raise InsideMeshBindError("root joint is outside the mesh; length fit cannot move it")
    scales = np.ones(len(joints), dtype=np.float64)
    for index in range(len(parents) - 1, 0, -1):
        parent = int(parents[index])
        if parent < 0:
            continue
        if float(np.linalg.norm(joints[index] - joints[parent])) <= 1e-12:
            continue
        watched = subtree_indices(parents, index)

        def subset_inside(trial_scale: float) -> bool:
            trial = scales.copy()
            trial[index] = float(trial_scale)
            placed = apply_bone_length_scales(joints, parents, trial)
            return bool(np.all(joints_inside_mask(vertices, placed[watched])))

        if subset_inside(1.0):
            scales[index] = 1.0
            continue
        lo, hi = float(min_scale), 1.0
        best = float(min_scale)
        for _ in range(LENGTH_SEARCH_STEPS):
            mid = 0.5 * (lo + hi)
            if subset_inside(mid):
                best = mid
                lo = mid
            else:
                hi = mid
        scales[index] = best
    placed = apply_bone_length_scales(joints, parents, scales)
    if not bone_directions_match(joints, placed, parents):
        raise InsideMeshBindError("length fit changed a bone direction")
    inside, report = joints_entirely_inside(vertices, placed)
    if not inside:
        raise InsideMeshBindError(
            "length fit could not place every joint inside the mesh: "
            + ", ".join(
                f"{name} outside={row['outsideFraction']:.3f} "
                f"maxDiag={row['maxDistanceOutsideFractionOfDiagonal']:.3f}"
                for name, row in report["views"].items()
            )
        )
    return {
        "scales": scales,
        "joints": placed,
        "placement": report,
        "minScale": float(min_scale),
        "meanShortening": float(np.mean(1.0 - scales[1:])) if len(scales) > 1 else 0.0,
        "policy": "shorten_only_keep_mocap_bone_directions",
    }


RASTER_SIZE = 96
SUCTION_LENGTH_STEPS = 12
SEGMENT_SAMPLES = 5
BODY_GRID = 40
BODY_THICK_NEIGHBORS = 3
BODY_CORE_DILATE = 2
SATURATION_PASSES = 2
SATURATION_LENGTH_STEPS = 10
SATURATION_SCORE_SAMPLES = 256
MAX_BODY_REACH_FRACTION = 0.65
WEAPON_NAME_MARKERS = ("weapon", "sword", "shield", "prop", "blade")
LIMB_CHAIN_SPECS = (
    (("leftupleg", "leftleg", "leftfoot", "lefttoebase", "lefttoe_end"), "leg_left", "down"),
    (("rightupleg", "rightleg", "rightfoot", "righttoebase", "righttoe_end"), "leg_right", "down"),
    (("leftshoulder", "leftarm", "leftforearm", "lefthand"), "arm_left", "out_left"),
    (("rightshoulder", "rightarm", "rightforearm", "righthand"), "arm_right", "out_right"),
    (("neck", "head", "headtop_end"), "neck_head", "up"),
)
CHAIN_CANDIDATE_CAP = 48


def _unit(vector: np.ndarray) -> np.ndarray:
    values = np.asarray(vector, dtype=np.float64).reshape(3)
    norm = float(np.linalg.norm(values))
    if norm <= 1e-12:
        return np.zeros(3, dtype=np.float64)
    return values / norm


def _slerp_dir(start: np.ndarray, end: np.ndarray, amount: float) -> np.ndarray:
    a = _unit(start)
    b = _unit(end)
    if float(np.linalg.norm(a)) <= 1e-12:
        return b
    if float(np.linalg.norm(b)) <= 1e-12:
        return a
    dot = float(np.clip(a @ b, -1.0, 1.0))
    if dot > 0.999999:
        return a
    if dot < -0.999999:
        helper = np.array([1.0, 0.0, 0.0]) if abs(a[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        return _unit(np.cross(a, helper))
    omega = float(np.arccos(dot))
    return _unit((np.sin((1.0 - amount) * omega) * a + np.sin(amount * omega) * b) / np.sin(omega))


def _point_in_triangle(point: np.ndarray, tri: np.ndarray) -> bool:
    v0 = tri[1] - tri[0]
    v1 = tri[2] - tri[0]
    v2 = point - tri[0]
    den = float(v0[0] * v1[1] - v1[0] * v0[1])
    if abs(den) <= 1e-18:
        return False
    u = (v2[0] * v1[1] - v1[0] * v2[1]) / den
    v = (v0[0] * v2[1] - v2[0] * v0[1]) / den
    return u >= -1e-9 and v >= -1e-9 and u + v <= 1.0 + 1e-9


def _raster_view(vertices: np.ndarray, triangles: np.ndarray, axes: tuple[int, int]) -> dict[str, Any]:
    xy = np.asarray(vertices, dtype=np.float64)[:, list(axes)]
    lo = xy.min(axis=0)
    hi = xy.max(axis=0)
    span = np.maximum(hi - lo, 1e-9)
    grid = np.zeros((RASTER_SIZE, RASTER_SIZE), dtype=bool)
    scale = (RASTER_SIZE - 1) / span

    def to_px(points: np.ndarray) -> np.ndarray:
        return np.floor((points - lo) * scale).astype(np.int64)

    for tri in np.asarray(triangles, dtype=np.int64):
        pts = xy[tri]
        px = to_px(pts)
        x0, y0 = int(px[:, 0].min()), int(px[:, 1].min())
        x1, y1 = int(px[:, 0].max()), int(px[:, 1].max())
        x0 = max(0, x0)
        y0 = max(0, y0)
        x1 = min(RASTER_SIZE - 1, x1)
        y1 = min(RASTER_SIZE - 1, y1)
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                world = lo + np.array([x, y], dtype=np.float64) / scale
                if _point_in_triangle(world, pts):
                    grid[y, x] = True
    dilated = grid.copy()
    dilated[1:, :] |= grid[:-1, :]
    dilated[:-1, :] |= grid[1:, :]
    dilated[:, 1:] |= grid[:, :-1]
    dilated[:, :-1] |= grid[:, 1:]
    return {"grid": dilated, "lo": lo, "span": span, "axes": axes}


def _pixel_inside(raster: dict[str, Any], point: np.ndarray) -> bool:
    xy = np.asarray(point, dtype=np.float64)[list(raster["axes"])]
    scaled = (xy - raster["lo"]) / raster["span"] * (RASTER_SIZE - 1)
    # A joint exactly on a mesh AABB face can round one U/V coordinate one
    # pixel beyond the raster. The AABB check already applies INSIDE_SLACK;
    # clamp only within that same numeric tolerance, never for a real
    # out-of-bounds point.
    scaled_slack = INSIDE_SLACK / np.maximum(np.asarray(raster["span"], dtype=np.float64), 1e-9)
    scaled_slack *= RASTER_SIZE - 1
    if np.any(scaled < -scaled_slack) or np.any(scaled > (RASTER_SIZE - 1) + scaled_slack):
        return False
    px = np.floor(np.clip(scaled, 0.0, RASTER_SIZE - 1)).astype(np.int64)
    return bool(raster["grid"][int(px[1]), int(px[0])])


class MeshContainment:
    """Front/side/top silhouette hull, plus 3D AABB. Triangles make the hull exact."""

    def __init__(self, vertices: np.ndarray, triangles: np.ndarray | None = None):
        self.vertices = np.asarray(vertices, dtype=np.float64)
        self.bounds = _mesh_bounds(self.vertices)
        self.rasters = None
        if triangles is not None:
            triangles = np.asarray(triangles, dtype=np.int64)
            if triangles.ndim != 2 or triangles.shape[1] != 3:
                raise InsideMeshBindError("triangles must be [F,3]")
            self.rasters = {name: _raster_view(self.vertices, triangles, axes) for name, axes in BIND_VIEWS}

    def point_inside(self, point: np.ndarray) -> bool:
        """Fast search test: AABB plus silhouette rasters when faces exist.

        Vertex-slab containment is applied only when a joint is kept, not on
        every rejected trial.
        """
        point = np.asarray(point, dtype=np.float64).reshape(3)
        lo = self.bounds["lo"]
        hi = self.bounds["hi"]
        if np.any(point < lo - INSIDE_SLACK) or np.any(point > hi + INSIDE_SLACK):
            return False
        if self.rasters is None:
            return bool(np.all(joints_inside_mask(self.vertices, point.reshape(1, 3))))
        return all(_pixel_inside(raster, point) for raster in self.rasters.values())

    def point_kept(self, point: np.ndarray) -> bool:
        point = np.asarray(point, dtype=np.float64).reshape(1, 3)
        if not bool(np.all(joints_inside_mask(self.vertices, point))):
            return False
        if self.rasters is None:
            return True
        return all(_pixel_inside(raster, point[0]) for raster in self.rasters.values())

    def segment_inside(self, start: np.ndarray, end: np.ndarray) -> bool:
        start = np.asarray(start, dtype=np.float64).reshape(3)
        end = np.asarray(end, dtype=np.float64).reshape(3)
        if not self.point_inside(start) or not self.point_inside(end):
            return False
        for amount in np.linspace(0.0, 1.0, SEGMENT_SAMPLES)[1:-1]:
            if not self.point_inside(start + amount * (end - start)):
                return False
        return True


def rest_direction_angles_deg(original: np.ndarray, placed: np.ndarray, parents: np.ndarray) -> np.ndarray:
    original = np.asarray(original, dtype=np.float64)
    placed = np.asarray(placed, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    angles = np.zeros(len(parents), dtype=np.float64)
    for index, parent in enumerate(parents):
        if parent < 0:
            continue
        source = _unit(original[index] - original[parent])
        dest = _unit(placed[index] - placed[parent])
        if float(np.linalg.norm(source)) <= 1e-12 or float(np.linalg.norm(dest)) <= 1e-12:
            continue
        angles[index] = float(np.degrees(np.arccos(np.clip(source @ dest, -1.0, 1.0))))
    return angles


def _candidate_directions(mocap: np.ndarray, toward: np.ndarray) -> list[np.ndarray]:
    mocap = _unit(mocap)
    toward = _unit(toward)
    out = [mocap]
    if float(np.linalg.norm(toward)) > 1e-12:
        out.append(toward)
        for amount in (0.25, 0.5, 0.75):
            out.append(_slerp_dir(mocap, toward, amount))
        helper = np.array([1.0, 0.0, 0.0]) if abs(toward[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
        side = _unit(np.cross(toward, helper))
        up = _unit(np.cross(side, toward))
        for axis in (side, -side, up, -up):
            if float(np.linalg.norm(axis)) > 1e-12:
                out.append(_slerp_dir(toward, toward + 0.45 * axis, 1.0))
    for axis in (
        np.array([0.0, 1.0, 0.0]),
        np.array([0.0, -1.0, 0.0]),
        np.array([1.0, 0.0, 0.0]),
        np.array([-1.0, 0.0, 0.0]),
        np.array([0.0, 0.0, 1.0]),
        np.array([0.0, 0.0, -1.0]),
    ):
        out.append(axis)
    return out


def _neighbor_counts(occupied: np.ndarray) -> np.ndarray:
    counts = np.zeros(occupied.shape, dtype=np.int16)
    counts[1:, :, :] += occupied[:-1, :, :]
    counts[:-1, :, :] += occupied[1:, :, :]
    counts[:, 1:, :] += occupied[:, :-1, :]
    counts[:, :-1, :] += occupied[:, 1:, :]
    counts[:, :, 1:] += occupied[:, :, :-1]
    counts[:, :, :-1] += occupied[:, :, 1:]
    return counts


def _dilate_occupied(occupied: np.ndarray, steps: int) -> np.ndarray:
    out = occupied.copy()
    for _ in range(int(steps)):
        grown = out.copy()
        grown[1:, :, :] |= out[:-1, :, :]
        grown[:-1, :, :] |= out[1:, :, :]
        grown[:, 1:, :] |= out[:, :-1, :]
        grown[:, :-1, :] |= out[:, 1:, :]
        grown[:, :, 1:] |= out[:, :, :-1]
        grown[:, :, :-1] |= out[:, :, 1:]
        out = grown
    return out


def _largest_component(mask: np.ndarray) -> np.ndarray:
    seen = np.zeros_like(mask, dtype=bool)
    best_cells: list[tuple[int, int, int]] = []
    for start in map(tuple, np.argwhere(mask)):
        if seen[start]:
            continue
        stack = [start]
        seen[start] = True
        cells = []
        while stack:
            i, j, k = stack.pop()
            cells.append((i, j, k))
            for di, dj, dk in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                ni, nj, nk = i + di, j + dj, k + dk
                if (
                    0 <= ni < mask.shape[0]
                    and 0 <= nj < mask.shape[1]
                    and 0 <= nk < mask.shape[2]
                    and mask[ni, nj, nk]
                    and not seen[ni, nj, nk]
                ):
                    seen[ni, nj, nk] = True
                    stack.append((ni, nj, nk))
        if len(cells) > len(best_cells):
            best_cells = cells
    out = np.zeros_like(mask, dtype=bool)
    for cell in best_cells:
        out[cell] = True
    return out


def _voxelize_triangles(vertices: np.ndarray, triangles: np.ndarray, grid: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lo = vertices.min(axis=0)
    span = np.maximum(vertices.max(axis=0) - lo, 1e-9)
    occupied = np.zeros((grid, grid, grid), dtype=bool)
    scale = (grid - 1) / span
    for tri in triangles:
        pts = vertices[np.asarray(tri, dtype=np.int64)]
        tlo = np.floor((pts.min(axis=0) - lo) * scale).astype(np.int64)
        thi = np.ceil((pts.max(axis=0) - lo) * scale).astype(np.int64)
        tlo = np.clip(tlo, 0, grid - 1)
        thi = np.clip(thi, 0, grid - 1)
        occupied[tlo[0] : thi[0] + 1, tlo[1] : thi[1] + 1, tlo[2] : thi[2] + 1] = True
    return occupied, lo, span


def body_vertex_mask(vertices: np.ndarray, triangles: np.ndarray | None = None) -> np.ndarray:
    """True on bulky flesh. Thin weapon/horn spikes attached by a narrow neck are false.

    Point clouds without triangles have no weapon topology, so every vertex is body.
    A mesh whose thick core is empty fails closed.
    """
    vertices = np.asarray(vertices, dtype=np.float64)
    if triangles is None:
        return np.ones(len(vertices), dtype=bool)
    triangles = np.asarray(triangles, dtype=np.int64)
    if triangles.ndim != 2 or triangles.shape[1] != 3:
        raise InsideMeshBindError("triangles must be [F,3]")
    occupied, lo, span = _voxelize_triangles(vertices, triangles, BODY_GRID)
    thick = occupied & (_neighbor_counts(occupied) >= BODY_THICK_NEIGHBORS)
    if not bool(thick.any()):
        raise InsideMeshBindError("mesh has no thick body core; cannot separate weapon from body")
    core = _largest_component(thick)
    if not bool(core.any()):
        raise InsideMeshBindError("body opening removed every occupied voxel")
    core_ijk = np.argwhere(core)
    clo = core_ijk.min(axis=0)
    chi = core_ijk.max(axis=0)
    body_voxels = _dilate_occupied(core, BODY_CORE_DILATE)
    idx = np.floor((vertices - lo) / span * (BODY_GRID - 1)).astype(np.int64)
    idx = np.clip(idx, 0, BODY_GRID - 1)
    on_core = body_voxels[idx[:, 0], idx[:, 1], idx[:, 2]]
    in_core_aabb = np.all((idx >= clo) & (idx <= chi), axis=1)
    return on_core | in_core_aabb


def _is_weapon_joint(names: list[str] | None, index: int) -> bool:
    if names is None or index >= len(names):
        return False
    text = str(names[index]).lower()
    return any(marker in text for marker in WEAPON_NAME_MARKERS)


def _joint_region(name: str) -> str:
    text = name.lower()
    if any(marker in text for marker in WEAPON_NAME_MARKERS):
        return "weapon"
    if "head" in text or "neck" in text:
        return "neck_head"
    if any(token in text for token in ("upleg", "leg", "foot", "toe")):
        return "leg_left" if "left" in text else "leg_right"
    if any(token in text for token in ("shoulder", "arm", "hand", "forearm")):
        return "arm_left" if "left" in text else "arm_right"
    return "torso"


def _clean_joint_name(name: str) -> str:
    return str(name).split(":")[-1].lower().replace(" ", "")


def _limb_chains(names: list[str]) -> list[dict[str, Any]]:
    lookup = {_clean_joint_name(name): index for index, name in enumerate(names)}
    chains: list[dict[str, Any]] = []
    for tokens, region, extreme in LIMB_CHAIN_SPECS:
        indices = [lookup[token] for token in tokens if token in lookup]
        if len(indices) >= 2:
            chains.append({"indices": indices, "region": region, "extreme": extreme})
    return chains


def _region_body_vertices(body_vertices: np.ndarray, hip: np.ndarray, region: str) -> np.ndarray:
    """Body vertices that belong to one named limb. Empty is a failed region, not 'use all'."""
    body_vertices = np.asarray(body_vertices, dtype=np.float64)
    hip = np.asarray(hip, dtype=np.float64).reshape(3)
    rel = body_vertices - hip
    height = float(np.ptp(body_vertices[:, 1]))
    width = float(np.ptp(body_vertices[:, 0]))
    if height <= 1e-9 or width <= 1e-9:
        raise InsideMeshBindError(f"{region} body vertices have no extent")
    x, y = rel[:, 0], rel[:, 1]
    if region == "neck_head":
        picked = body_vertices[y > 0.28 * height]
    elif region.startswith("leg"):
        side = x > 0.0 if region.endswith("left") else x < 0.0
        picked = body_vertices[(y < 0.38 * height) & side]
    elif region.startswith("arm"):
        side = x > 0.12 * width if region.endswith("left") else x < -0.12 * width
        picked = body_vertices[(y > 0.22 * height) & (y < 0.82 * height) & side]
    elif region == "torso":
        picked = body_vertices
    else:
        raise InsideMeshBindError(f"unknown anatomical region {region!r}")
    if len(picked) == 0:
        raise InsideMeshBindError(f"no body vertices in {region}")
    return picked


def _extreme_direction(verts: np.ndarray, extreme: str) -> np.ndarray:
    verts = np.asarray(verts, dtype=np.float64)
    if extreme == "down":
        key = verts[:, 1]
        pick = verts[key <= float(np.quantile(key, 0.15))]
    elif extreme == "up":
        key = verts[:, 1]
        pick = verts[key >= float(np.quantile(key, 0.85))]
    elif extreme == "out_left":
        key = verts[:, 0]
        pick = verts[key >= float(np.quantile(key, 0.85))]
    elif extreme == "out_right":
        key = verts[:, 0]
        pick = verts[key <= float(np.quantile(key, 0.15))]
    else:
        raise InsideMeshBindError(f"unknown limb extreme {extreme!r}")
    direction = _unit(pick.mean(axis=0) - verts.mean(axis=0))
    if float(np.linalg.norm(direction)) <= 1e-12:
        raise InsideMeshBindError(f"limb extreme {extreme!r} has no distal direction")
    return direction


def _sample_band(verts: np.ndarray, t: np.ndarray, slot: float, t_span: float) -> np.ndarray:
    half = max(0.08 * t_span, 1e-6)
    band = verts[np.abs(t - slot) <= half]
    if len(band) == 0:
        order = np.argsort(np.abs(t - slot))
        band = verts[order[: min(12, len(verts))]]
    if len(band) > CHAIN_CANDIDATE_CAP:
        order = np.argsort((band - band.mean(axis=0)).sum(axis=1))
        pick = np.linspace(0, len(band) - 1, CHAIN_CANDIDATE_CAP).astype(np.int64)
        band = band[order][pick]
    return band


def _best_inside_child(
    hull: MeshContainment,
    parent: np.ndarray,
    band: np.ndarray,
    *,
    axis: np.ndarray,
    origin: np.ndarray,
    min_t: float,
    slot_t: float,
) -> np.ndarray | None:
    parent = np.asarray(parent, dtype=np.float64)
    mean = band.mean(axis=0)
    candidates = [np.asarray(point, dtype=np.float64) for point in band]
    for frac in (0.35, 0.55, 0.75, 1.0):
        candidates.append(parent + float(frac) * (mean - parent))
    best: tuple[float, np.ndarray] | None = None
    for point in candidates:
        along = float((point - origin) @ axis)
        if along <= min_t:
            continue
        error = abs(along - slot_t)
        if best is not None and error >= best[0] - 1e-12:
            continue
        if not hull.segment_inside(parent, point) or not hull.point_kept(point):
            continue
        best = (error, point)
    return None if best is None else best[1]


def _chain_slot_bands(
    joints: np.ndarray,
    names: list[str],
    body_vertices: np.ndarray,
    hip: np.ndarray,
) -> dict[int, dict[str, Any]]:
    """Exclusive proximal→distal t-bands for each named limb joint."""
    bands: dict[int, dict[str, Any]] = {}
    for chain in _limb_chains(names):
        verts = _region_body_vertices(body_vertices, hip, chain["region"])
        axis = _extreme_direction(verts, chain["extreme"])
        origin = verts.mean(axis=0)
        t = (verts - origin) @ axis
        t_lo, t_hi = float(np.min(t)), float(np.max(t))
        if t_hi <= t_lo + 1e-8:
            raise InsideMeshBindError(f"{chain['region']} has no proximal-to-distal extent")
        ids = chain["indices"]
        spans = [
            max(float(np.linalg.norm(joints[child] - joints[parent])), 1e-6)
            for parent, child in zip(ids, ids[1:])
        ]
        frac = np.concatenate([[0.0], np.cumsum(spans)])
        frac = frac / frac[-1]
        slots = t_lo + (t_hi - t_lo) * frac
        edges = np.concatenate([[t_lo], 0.5 * (slots[:-1] + slots[1:]), [t_hi]])
        for index, joint in enumerate(ids):
            bands[joint] = {
                "region": chain["region"],
                "axis": axis,
                "origin": origin,
                "lo": float(edges[index]),
                "hi": float(edges[index + 1]),
            }
    return bands


def _joint_in_slot_band(point: np.ndarray, band: dict[str, Any]) -> bool:
    along = float((np.asarray(point, dtype=np.float64) - band["origin"]) @ band["axis"])
    return band["lo"] - 1e-9 <= along <= band["hi"] + 1e-9


def assert_anatomical_chain_order(
    placed: np.ndarray,
    names: list[str],
    body_vertices: np.ndarray,
    joints: np.ndarray | None = None,
) -> None:
    """Fail closed when a distal joint sits in a proximal slot (foot in a knee)."""
    source = placed if joints is None else np.asarray(joints, dtype=np.float64)
    bands = _chain_slot_bands(source, names, body_vertices, placed[0])
    for joint, band in bands.items():
        if not _joint_in_slot_band(placed[joint], band):
            raise InsideMeshBindError(
                f"{names[joint]} left its {band['region']} slot; a foot cannot occupy the knee"
            )


def _place_limb_chains(
    placed: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    hull: MeshContainment,
    body_vertices: np.ndarray,
    names: list[str],
) -> np.ndarray:
    """Put each named limb on increasing proximal→distal slots of its mesh part."""
    hip = placed[0]
    for chain in _limb_chains(names):
        region_verts = _region_body_vertices(body_vertices, hip, chain["region"])
        axis = _extreme_direction(region_verts, chain["extreme"])
        origin = region_verts.mean(axis=0)
        t = (region_verts - origin) @ axis
        t_lo, t_hi = float(np.min(t)), float(np.max(t))
        if t_hi <= t_lo + 1e-8:
            raise InsideMeshBindError(f"{chain['region']} has no proximal-to-distal extent")
        ids = chain["indices"]
        spans = [
            max(float(np.linalg.norm(joints[child] - joints[parent])), 1e-6)
            for parent, child in zip(ids, ids[1:])
        ]
        frac = np.concatenate([[0.0], np.cumsum(spans)])
        frac = frac / frac[-1]
        slots = t_lo + (t_hi - t_lo) * frac
        prev_t = t_lo - 1e-4
        for index, joint in enumerate(ids):
            band = _sample_band(region_verts, t, float(slots[index]), t_hi - t_lo)
            parent = int(parents[joint])
            if index == 0:
                current_t = float((placed[joint] - origin) @ axis)
                if (
                    hull.point_inside(placed[joint])
                    and abs(current_t - float(slots[0])) <= 0.12 * (t_hi - t_lo)
                ):
                    prev_t = current_t
                    continue
                target = _best_inside_child(
                    hull,
                    placed[parent] if parent >= 0 else placed[joint],
                    band,
                    axis=axis,
                    origin=origin,
                    min_t=prev_t,
                    slot_t=float(slots[index]),
                )
            else:
                if parent < 0:
                    raise InsideMeshBindError(f"{names[joint]} is a distal limb joint without a parent")
                target = _best_inside_child(
                    hull,
                    placed[parent],
                    band,
                    axis=axis,
                    origin=origin,
                    min_t=prev_t,
                    slot_t=float(slots[index]),
                )
            if target is None:
                raise InsideMeshBindError(
                    f"cannot place {names[joint]} distal of its parent inside {chain['region']}"
                )
            delta = target - placed[joint]
            for member in subtree_indices(parents, joint):
                placed[member] = placed[member] + delta
            prev_t = float((placed[joint] - origin) @ axis)
    return placed


def _anatomical_aim(
    names: list[str],
    index: int,
    body_vertices: np.ndarray,
    placed: np.ndarray,
) -> np.ndarray:
    region = _joint_region(names[index])
    if region == "weapon":
        raise InsideMeshBindError(f"{names[index]} is a weapon joint; suction cannot aim it at body flesh")
    verts = _region_body_vertices(body_vertices, placed[0], region)
    extreme = {
        "leg_left": "down",
        "leg_right": "down",
        "arm_left": "out_left",
        "arm_right": "out_right",
        "neck_head": "up",
        "torso": "up",
    }[region]
    axis = _extreme_direction(verts, extreme)
    return verts.mean(axis=0) + axis * float(np.linalg.norm(np.ptp(verts, axis=0))) * 0.35


def _point_to_segment_distance(points: np.ndarray, start: np.ndarray, end: np.ndarray) -> np.ndarray:
    start = np.asarray(start, dtype=np.float64)
    end = np.asarray(end, dtype=np.float64)
    points = np.asarray(points, dtype=np.float64)
    span = end - start
    length_sq = float(span @ span)
    if length_sq <= 1e-16:
        return np.linalg.norm(points - start, axis=1)
    amount = np.clip(((points - start) @ span) / length_sq, 0.0, 1.0)
    return np.linalg.norm(points - (start + amount[:, None] * span), axis=1)


def body_saturation_score(joints: np.ndarray, parents: np.ndarray, body_vertices: np.ndarray) -> float:
    """How completely bone segments occupy non-weapon body vertices. 1 is saturated."""
    body_vertices = np.asarray(body_vertices, dtype=np.float64)
    if len(body_vertices) == 0:
        raise InsideMeshBindError("body saturation requires at least one body vertex")
    diag = float(np.linalg.norm(np.ptp(body_vertices, axis=0)))
    if diag <= 1e-9:
        raise InsideMeshBindError("body saturation requires nonzero body extent")
    nearest = np.full(len(body_vertices), np.inf, dtype=np.float64)
    for index, parent in enumerate(parents):
        if parent < 0:
            continue
        nearest = np.minimum(nearest, _point_to_segment_distance(body_vertices, joints[parent], joints[index]))
    return float(np.mean(np.exp(-((nearest / (0.18 * diag)) ** 2))))


def _owned_body_vertices(
    body_vertices: np.ndarray,
    placed: np.ndarray,
    parents: np.ndarray,
    index: int,
    names: list[str] | None,
) -> np.ndarray:
    if names is not None and index < len(names):
        region = _joint_region(names[index])
        if region != "torso" and region != "weapon":
            return _region_body_vertices(body_vertices, placed[0], region)
    nearest_bone = np.zeros(len(body_vertices), dtype=np.int64)
    nearest_d = np.full(len(body_vertices), np.inf, dtype=np.float64)
    for bone, parent in enumerate(parents):
        if parent < 0:
            continue
        dist = _point_to_segment_distance(body_vertices, placed[parent], placed[bone])
        closer = dist < nearest_d
        nearest_d[closer] = dist[closer]
        nearest_bone[closer] = bone
    owned = body_vertices[nearest_bone == index]
    return owned if len(owned) > 0 else body_vertices


def _saturate_body_bones(
    placed: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    hull: MeshContainment,
    body_vertices: np.ndarray,
    names: list[str] | None,
    *,
    min_scale: float,
) -> np.ndarray:
    """Grow/re-aim contained body bones toward unused flesh. Stay inside the mesh."""
    diag = float(np.linalg.norm(np.ptp(body_vertices, axis=0)))
    if diag <= 1e-9:
        raise InsideMeshBindError("body saturation requires nonzero body extent")
    slot_bands = (
        _chain_slot_bands(joints, names, body_vertices, placed[0])
        if names is not None and _limb_chains(names)
        else {}
    )
    for _ in range(SATURATION_PASSES):
        for index in range(1, len(parents)):
            if _is_weapon_joint(names, index):
                continue
            parent = int(parents[index])
            mocap_offset = joints[index] - joints[parent]
            mocap_len = float(np.linalg.norm(mocap_offset))
            if mocap_len <= 1e-12:
                continue
            owned = _owned_body_vertices(body_vertices, placed, parents, index, names)
            radius = 0.18 * diag
            if len(owned) > SATURATION_SCORE_SAMPLES:
                pick = np.linspace(0, len(owned) - 1, SATURATION_SCORE_SAMPLES).astype(np.int64)
                scored = owned[pick]
            else:
                scored = owned

            def reach(child: np.ndarray) -> float:
                dist = _point_to_segment_distance(scored, placed[parent], child)
                return float(np.mean(np.exp(-((dist / radius) ** 2))))

            current_score = reach(placed[index])
            target = owned[int(np.argmax(np.linalg.norm(owned - placed[parent], axis=1)))]
            best_score = current_score
            best_joint = placed[index].copy()
            max_len = min(float(np.linalg.norm(target - placed[parent])), MAX_BODY_REACH_FRACTION * diag)
            for direction in _candidate_directions(mocap_offset, target - placed[parent]):
                if float(np.linalg.norm(direction)) <= 1e-12:
                    continue
                for length in np.linspace(max_len, mocap_len * float(min_scale), SATURATION_LENGTH_STEPS):
                    trial = placed[parent] + direction * float(length)
                    if index in slot_bands and not _joint_in_slot_band(trial, slot_bands[index]):
                        continue
                    if not hull.segment_inside(placed[parent], trial):
                        continue
                    score = reach(trial)
                    if score > best_score + 1e-4 and hull.point_kept(trial):
                        best_score = score
                        best_joint = trial
            if best_score > current_score + 1e-4:
                slotted = {
                    joint
                    for chain in (_limb_chains(names) if names is not None else ())
                    for joint in chain["indices"]
                }
                delta = best_joint - placed[index]
                for member in subtree_indices(parents, index):
                    if member != index and member in slotted:
                        continue
                    placed[member] = placed[member] + delta
    return placed


def fit_rest_inside_mesh(
    joints: np.ndarray,
    parents: np.ndarray,
    vertices: np.ndarray,
    triangles: np.ndarray | None = None,
    *,
    min_scale: float = MIN_BONE_LENGTH_SCALE,
    hull: MeshContainment | None = None,
    names: list[str] | None = None,
    body_mask: np.ndarray | None = None,
    saturate: bool = True,
) -> dict[str, Any]:
    """Pull the standing skeleton into the mesh, then saturate non-weapon body.

    Containment is first and fail-closed. Named Mixamo limbs then occupy
    anatomical slots so a foot cannot sit in a knee. 'Already inside' is not
    done: body bones then grow and re-aim toward unused flesh without
    collapsing that order. Thin weapon spikes are not a saturation target.
    Search may call this with saturate=False and saturate only the winner.
    """
    joints = np.asarray(joints, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    vertices = np.asarray(vertices, dtype=np.float64)
    if not np.isfinite(min_scale) or min_scale <= 0 or min_scale > 1.0:
        raise InsideMeshBindError("min_scale must be in (0, 1]")
    if hull is None:
        hull = MeshContainment(vertices, triangles)
    else:
        vertices = hull.vertices
    if body_mask is None:
        body_mask = body_vertex_mask(vertices, triangles)
    body_mask = np.asarray(body_mask, dtype=bool)
    if body_mask.shape != (len(vertices),):
        raise InsideMeshBindError("body_mask must be [V]")
    if not bool(body_mask.any()):
        raise InsideMeshBindError("body saturation found no non-weapon mesh volume")
    body_vertices = vertices[body_mask]
    placed = joints.copy()
    if not hull.point_inside(placed[0]):
        placed[0] = (vertices.max(axis=0) + vertices.min(axis=0)) * 0.5
        if not hull.point_inside(placed[0]):
            raise InsideMeshBindError("root joint cannot be placed inside the mesh")
        placed[1:] += placed[0] - joints[0]
    mesh_center = (vertices.max(axis=0) + vertices.min(axis=0)) * 0.5
    for index in range(1, len(parents)):
        parent = int(parents[index])
        mocap_offset = joints[index] - joints[parent]
        mocap_len = float(np.linalg.norm(mocap_offset))
        if mocap_len <= 1e-12:
            placed[index] = placed[parent]
            continue
        current = placed[index] - placed[parent]
        if hull.segment_inside(placed[parent], placed[parent] + current):
            continue
        if names is not None and not _is_weapon_joint(names, index):
            aim = _anatomical_aim(names, index, body_vertices, placed)
        else:
            aim = mesh_center
        best: tuple[float, np.ndarray] | None = None
        for direction in _candidate_directions(mocap_offset, aim - placed[parent]):
            if float(np.linalg.norm(direction)) <= 1e-12:
                continue
            for frac in np.linspace(1.0, min_scale, SUCTION_LENGTH_STEPS):
                trial = placed[parent] + direction * mocap_len * float(frac)
                if not hull.segment_inside(placed[parent], trial) or not hull.point_kept(trial):
                    continue
                angle = float(np.degrees(np.arccos(np.clip(_unit(mocap_offset) @ direction, -1.0, 1.0))))
                score = angle / 45.0 + 0.35 * (1.0 - float(frac))
                if best is None or score < best[0] - 1e-12:
                    best = (score, trial)
                break
        if best is None:
            raise InsideMeshBindError(f"bind-first suction could not place joint {index} inside the mesh")
        delta = best[1] - placed[index]
        for member in subtree_indices(parents, index):
            placed[member] = placed[member] + delta
    if names is not None:
        placed = _place_limb_chains(placed, joints, parents, hull, body_vertices, names)
    if saturate:
        placed = _saturate_body_bones(
            placed, joints, parents, hull, body_vertices, names, min_scale=min_scale
        )
    if names is not None and _limb_chains(names):
        assert_anatomical_chain_order(placed, names, body_vertices, joints=joints)
    if not bool(np.all([hull.point_inside(point) for point in placed])):
        raise InsideMeshBindError("bind-first suction left a joint outside the mesh")
    inside, report = joints_entirely_inside(vertices, placed)
    if not inside:
        raise InsideMeshBindError("body saturation pushed a joint outside the mesh")
    angles = rest_direction_angles_deg(joints, placed, parents)
    lengths = np.ones(len(parents), dtype=np.float64)
    for index, parent in enumerate(parents):
        if parent < 0:
            continue
        source = float(np.linalg.norm(joints[index] - joints[parent]))
        dest = float(np.linalg.norm(placed[index] - placed[parent]))
        lengths[index] = dest / source if source > 1e-12 else 1.0
    saturation = body_saturation_score(placed, parents, body_vertices)
    return {
        "joints": placed,
        "scales": lengths,
        "restAngleDeg": angles,
        "meanRestAngleDeg": float(np.mean(angles[1:])) if len(angles) > 1 else 0.0,
        "meanShortening": float(np.mean(np.maximum(0.0, 1.0 - lengths[1:]))) if len(lengths) > 1 else 0.0,
        "bodySaturation": float(saturation),
        "bodyVertexCount": int(len(body_vertices)),
        "weaponVertexCount": int(len(vertices) - len(body_vertices)),
        "placement": report,
        "slabInside": inside,
        "policy": (
            "bind_first_inside_mesh_anatomical_slots"
            if names is not None and _limb_chains(names)
            else "bind_first_inside_mesh_saturate_non_weapon_body"
        ),
        "minScale": float(min_scale),
    }
