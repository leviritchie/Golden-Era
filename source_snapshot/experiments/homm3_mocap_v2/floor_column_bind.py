"""Floor-column bind: feet on the mesh bottom, top on the mesh top, then XZ snap.

Y is the up axis. After the mocap skeleton is facing the camera, this pass:

1. Finds every ground-contact joint (1, 2, 4, or more feet).
2. Drops the skeleton so those feet sit on the mesh floor, and pins each foot
   chain to that floor.
3. Scales about the floor so the highest joint meets the mesh top.
4. Yaw-rotates about the feet until the bottom footprint fits; prefers a yaw
   that also fits the top.
5. Walks joints from lowest to highest and moves only X and Z into the local
   center of the nearest filled slice of the mesh.

Queries after init are grid lookups, not per-trial vertex scans.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from inside_mesh_bind import rest_direction_angles_deg, subtree_indices, _voxelize_triangles
from static_bind_registration import apply_similarity, rotation_matrix

SLICE_GRID = 48
MIN_COMPONENT_CELLS = 4
LOCAL_WINDOW_CELLS = 4
FOOT_BAND_FRACTION = 0.18
END_BAND_FRACTION = 0.18
FLOOR_YAW_DEGS = (
    0.0,
    -5.0,
    5.0,
    -10.0,
    10.0,
    -15.0,
    15.0,
    -20.0,
    20.0,
    -30.0,
    30.0,
    -45.0,
    45.0,
    -60.0,
    60.0,
    -90.0,
    90.0,
)
POLICY = "bind_floor_column_xz"
CONTAINMENT_POLICY = "floor_column_xz"
GROUND_HEIGHT_POLICY = "bind_ground_height"
GROUND_HEIGHT_CONTAINMENT = "ground_height_only"
SCALE_TO_GROUND_POLICY = "bind_scale_to_ground"
SCALE_TO_GROUND_CONTAINMENT = "scale_to_ground"
Y_ATOL = 1e-6
FLOOR_VERTEX_BAND = 0.02


class FloorColumnBindError(ValueError):
    """Raised when the floor-column pass cannot place the skeleton on the mesh."""


def _grid_index(value: float, lo: float, span: float, grid: int) -> int:
    if span <= 1e-12:
        return 0
    return int(np.clip(np.floor((value - lo) / span * grid), 0, grid - 1))


def _world_from_cell(index: int, lo: float, span: float, grid: int) -> float:
    if grid <= 1:
        return float(lo)
    return float(lo + (index + 0.5) / grid * span)


def _label_components(occupied: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """4-connected labels on a 2D mask. Returns labels and cell counts per id."""
    height, width = occupied.shape
    labels = np.zeros((height, width), dtype=np.int32)
    counts: list[int] = [0]
    for y in range(height):
        for x in range(width):
            if not occupied[y, x] or labels[y, x] != 0:
                continue
            label = len(counts)
            counts.append(0)
            stack = [(y, x)]
            labels[y, x] = label
            while stack:
                cy, cx = stack.pop()
                counts[label] += 1
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if 0 <= ny < height and 0 <= nx < width and occupied[ny, nx] and labels[ny, nx] == 0:
                        labels[ny, nx] = label
                        stack.append((ny, nx))
    return labels, counts


def _dilate_2d(occupied: np.ndarray) -> np.ndarray:
    out = occupied.copy()
    out[1:, :] |= occupied[:-1, :]
    out[:-1, :] |= occupied[1:, :]
    out[:, 1:] |= occupied[:, :-1]
    out[:, :-1] |= occupied[:, 1:]
    return out


class SliceVolume:
    """Filled XZ occupancy per height layer. Built once; queries do not scan vertices."""

    def __init__(self, vertices: np.ndarray, triangles: np.ndarray | None = None):
        vertices = np.asarray(vertices, dtype=np.float64)
        if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 2:
            raise FloorColumnBindError("slice volume requires [N,3] vertices")
        if not np.isfinite(vertices).all():
            raise FloorColumnBindError("slice volume vertices must be finite")
        self.lo = vertices.min(axis=0)
        self.hi = vertices.max(axis=0)
        self.span = np.maximum(self.hi - self.lo, 1e-9)
        self.grid = SLICE_GRID
        if triangles is None:
            occupied = np.zeros((SLICE_GRID, SLICE_GRID, SLICE_GRID), dtype=bool)
            x0 = _grid_index(float(self.lo[0]), float(self.lo[0]), float(self.span[0]), SLICE_GRID)
            x1 = _grid_index(float(self.hi[0]), float(self.lo[0]), float(self.span[0]), SLICE_GRID)
            z0 = _grid_index(float(self.lo[2]), float(self.lo[2]), float(self.span[2]), SLICE_GRID)
            z1 = _grid_index(float(self.hi[2]), float(self.lo[2]), float(self.span[2]), SLICE_GRID)
            occupied[x0 : x1 + 1, :, z0 : z1 + 1] = True
        else:
            triangles = np.asarray(triangles, dtype=np.int64)
            occupied, lo, span = _voxelize_triangles(vertices, triangles, SLICE_GRID)
            self.lo = lo
            self.span = np.maximum(span, 1e-9)
            self.hi = self.lo + self.span
        self._layers: list[dict[str, Any]] = []
        for iy in range(SLICE_GRID):
            plane = _dilate_2d(occupied[:, iy, :].T.copy())
            labels, counts = _label_components(plane)
            meaningful = np.zeros_like(plane)
            for label, count in enumerate(counts):
                if label > 0 and count >= MIN_COMPONENT_CELLS:
                    meaningful |= labels == label
            labels, counts = _label_components(meaningful)
            self._layers.append({"occupied": meaningful, "labels": labels, "counts": counts})

    @property
    def floor_y(self) -> float:
        return float(self.lo[1])

    @property
    def top_y(self) -> float:
        return float(self.hi[1])

    def _cell(self, point: np.ndarray, *, clip: bool = True) -> tuple[int, int, int] | None:
        point = np.asarray(point, dtype=np.float64).reshape(3)
        raw = (
            (float(point[0]) - float(self.lo[0])) / float(self.span[0]) * self.grid,
            (float(point[1]) - float(self.lo[1])) / float(self.span[1]) * self.grid,
            (float(point[2]) - float(self.lo[2])) / float(self.span[2]) * self.grid,
        )
        if not clip and (
            raw[0] < -1e-9
            or raw[0] > self.grid + 1e-9
            or raw[2] < -1e-9
            or raw[2] > self.grid + 1e-9
        ):
            return None
        iy = int(np.clip(np.floor(raw[1]), 0, self.grid - 1))
        ix = int(np.clip(np.floor(raw[0]), 0, self.grid - 1))
        iz = int(np.clip(np.floor(raw[2]), 0, self.grid - 1))
        return ix, iy, iz

    def _layer_search(self, iy: int) -> tuple[int, ...]:
        nearby = [iy]
        if iy > 0:
            nearby.append(iy - 1)
        if iy + 1 < self.grid:
            nearby.append(iy + 1)
        return tuple(nearby)

    def nearest_occupied(self, point: np.ndarray) -> tuple[int, int, int] | None:
        """Nearest meaningful filled cell in this height band. Grid BFS, not vertices."""
        start = self._cell(point, clip=True)
        if start is None:
            return None
        ix, iy, iz = start
        for layer in self._layer_search(iy):
            labels = self._layers[layer]["labels"]
            if labels[iz, ix] > 0:
                return ix, layer, iz
        best: tuple[int, int, int, int] | None = None
        for layer in self._layer_search(iy):
            occupied = self._layers[layer]["occupied"]
            cells = np.argwhere(occupied)
            if len(cells) == 0:
                continue
            delta = cells - np.array([iz, ix], dtype=np.int64)
            nearest = int(np.argmin(delta[:, 0] ** 2 + delta[:, 1] ** 2))
            cz, cx = (int(cells[nearest, 0]), int(cells[nearest, 1]))
            dist = int(delta[nearest, 0] ** 2 + delta[nearest, 1] ** 2)
            if best is None or dist < best[0]:
                best = (dist, cx, layer, cz)
        if best is None:
            return None
        return best[1], best[2], best[3]

    def xz_inside(self, point: np.ndarray) -> bool:
        cell = self._cell(point, clip=False)
        if cell is None:
            return False
        ix, iy, iz = cell
        return any(int(self._layers[layer]["labels"][iz, ix]) > 0 for layer in self._layer_search(iy))

    def all_joints_inside(self, joints: np.ndarray) -> bool:
        return all(self.xz_inside(point) for point in np.asarray(joints, dtype=np.float64))

    def center_xz(self, point: np.ndarray) -> np.ndarray:
        """Local thickness center of the nearest filled lobe. Does not change Y."""
        found = self.nearest_occupied(point)
        if found is None:
            raise FloorColumnBindError(
                f"no meaningful mesh volume near height {float(np.asarray(point).reshape(3)[1]):.6f}"
            )
        ix, iy, iz = found
        labels = self._layers[iy]["labels"]
        label = int(labels[iz, ix])
        if label <= 0:
            raise FloorColumnBindError("nearest slice cell is empty")
        radius = LOCAL_WINDOW_CELLS
        cells: list[tuple[int, int]] = []
        for z in range(max(0, iz - radius), min(self.grid, iz + radius + 1)):
            for x in range(max(0, ix - radius), min(self.grid, ix + radius + 1)):
                if int(labels[z, x]) == label:
                    cells.append((x, z))
        if not cells:
            raise FloorColumnBindError("nearest slice cell is empty")
        mean_x = float(sum(cell[0] for cell in cells)) / len(cells)
        mean_z = float(sum(cell[1] for cell in cells)) / len(cells)
        snap_x, snap_z = min(cells, key=lambda cell: (cell[0] - mean_x) ** 2 + (cell[1] - mean_z) ** 2)
        return np.array(
            [
                _world_from_cell(snap_x, float(self.lo[0]), float(self.span[0]), self.grid),
                _world_from_cell(snap_z, float(self.lo[2]), float(self.span[2]), self.grid),
            ],
            dtype=np.float64,
        )

    def layer_centroid_xz(self, iy: int | None = None) -> np.ndarray:
        layers = range(self.grid) if iy is None else self._layer_search(int(iy))
        xs: list[float] = []
        zs: list[float] = []
        for layer in layers:
            cells = np.argwhere(self._layers[layer]["occupied"])
            for z, x in cells:
                xs.append(_world_from_cell(int(x), float(self.lo[0]), float(self.span[0]), self.grid))
                zs.append(_world_from_cell(int(z), float(self.lo[2]), float(self.span[2]), self.grid))
        if not xs:
            raise FloorColumnBindError("mesh floor has no meaningful footprint")
        return np.array([float(np.mean(xs)), float(np.mean(zs))], dtype=np.float64)

    def placement_report(self, joints: np.ndarray) -> dict[str, Any]:
        joints = np.asarray(joints, dtype=np.float64)
        inside = [bool(self.xz_inside(point)) for point in joints]
        return {
            "policy": CONTAINMENT_POLICY,
            "jointsInsideCount": int(sum(inside)),
            "jointCount": int(len(joints)),
            "outsideCount": int(len(joints) - sum(inside)),
        }


def identify_foot_joints(joints: np.ndarray, parents: np.ndarray) -> list[int]:
    """Ground contacts: chain bottoms that sit in the lowest height band."""
    joints = np.asarray(joints, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    if parents.shape != (len(joints),):
        raise FloorColumnBindError("parents must be [J]")
    children: list[list[int]] = [[] for _ in range(len(joints))]
    for index, parent in enumerate(parents):
        if parent >= 0:
            children[int(parent)].append(index)
    min_y = float(joints[:, 1].min())
    height = float(np.ptp(joints[:, 1]))
    band = min_y + max(FOOT_BAND_FRACTION * height, 1e-6)
    feet: list[int] = []
    for index in range(len(joints)):
        if float(joints[index, 1]) > band:
            continue
        if any(float(joints[child, 1]) < float(joints[index, 1]) - 1e-9 for child in children[index]):
            continue
        feet.append(index)
    if not feet:
        raise FloorColumnBindError("no ground-contact joints in the lowest band")
    return feet


def _rotate_y(points: np.ndarray, yaw_deg: float, pivot: np.ndarray) -> np.ndarray:
    rotation = rotation_matrix(float(yaw_deg), 0.0, 0.0)
    pivot = np.asarray(pivot, dtype=np.float64).reshape(3)
    return (points - pivot) @ rotation.T + pivot


def _band_indices(joints: np.ndarray, lo: float, hi: float) -> list[int]:
    return [index for index, point in enumerate(joints) if lo <= float(point[1]) <= hi]


def _yaw_fit_score(
    volume: SliceVolume,
    placed: np.ndarray,
    feet: list[int],
    yaw_deg: float,
) -> tuple[int, float] | None:
    height = volume.top_y - volume.floor_y
    bottom = sorted(set(feet + _band_indices(placed, volume.floor_y, volume.floor_y + END_BAND_FRACTION * height)))
    top = _band_indices(placed, volume.top_y - END_BAND_FRACTION * height, volume.top_y)
    if not all(volume.xz_inside(placed[index]) for index in bottom):
        return None
    top_ok = True if not top else all(volume.xz_inside(placed[index]) for index in top)
    return (0 if top_ok else 1, abs(float(yaw_deg)))


def _pin_feet_to_floor(placed: np.ndarray, parents: np.ndarray, feet: list[int], floor_y: float) -> np.ndarray:
    placed = placed.copy()
    for foot in feet:
        delta = float(floor_y) - float(placed[foot, 1])
        if abs(delta) <= 1e-12:
            continue
        for member in subtree_indices(parents, foot):
            placed[member, 1] += delta
    return placed


def _mesh_vertical_extents(vertices: np.ndarray) -> tuple[float, float, np.ndarray]:
    """Mesh floor Y, top Y, and XZ centroid of the lowest vertex band."""
    vertices = np.asarray(vertices, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 2:
        raise FloorColumnBindError("ground-height bind requires [N,3] vertices")
    if not np.isfinite(vertices).all():
        raise FloorColumnBindError("ground-height bind vertices must be finite")
    floor_y = float(vertices[:, 1].min())
    top_y = float(vertices[:, 1].max())
    height = top_y - floor_y
    if height <= 1e-9:
        raise FloorColumnBindError("mesh has no height above its floor")
    band = floor_y + max(FLOOR_VERTEX_BAND * height, 1e-9)
    floor_verts = vertices[vertices[:, 1] <= band]
    if len(floor_verts) == 0:
        raise FloorColumnBindError("mesh has no floor vertices")
    mesh_xz = np.array(
        [float(floor_verts[:, 0].mean()), float(floor_verts[:, 2].mean())],
        dtype=np.float64,
    )
    return floor_y, top_y, mesh_xz


def _uniform_length_scales(parents: np.ndarray) -> np.ndarray:
    return np.ones(len(parents), dtype=np.float64)


def fit_rest_ground_height(
    joints: np.ndarray,
    parents: np.ndarray,
    vertices: np.ndarray,
    triangles: np.ndarray | None = None,
    *,
    seed_yaw_deg: float = 0.0,
    names: list[str] | None = None,
) -> dict[str, Any]:
    """Drop the whole mocap skeleton to the mesh floor, then scale height only.

    One facing yaw, one vertical drop, one uniform scale about the floor, and
    one rigid XZ shift so the feet sit over the mesh floor. No per-bone move,
    no per-bone length edit, no yaw search. Joints may sit outside the mesh.
    """
    del triangles, names
    joints = np.asarray(joints, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    vertices = np.asarray(vertices, dtype=np.float64)
    if joints.ndim != 2 or joints.shape[1] != 3:
        raise FloorColumnBindError(f"joints must be [J,3], got {joints.shape}")
    if parents.shape != (len(joints),):
        raise FloorColumnBindError("parents must be [J]")
    if parents[0] != -1 or any(int(parent) < 0 or int(parent) >= index for index, parent in enumerate(parents[1:], 1)):
        raise FloorColumnBindError("hierarchy must be root-first ordered")
    if not np.isfinite(joints).all() or not np.isfinite(vertices).all():
        raise FloorColumnBindError("joints and vertices must be finite")
    seed_yaw_deg = float(seed_yaw_deg)
    rotation = rotation_matrix(seed_yaw_deg, 0.0, 0.0)
    facing = joints @ rotation.T
    floor_y, top_y, mesh_xz = _mesh_vertical_extents(vertices)
    feet = identify_foot_joints(facing, parents)
    drop = floor_y - float(facing[feet, 1].min())
    dropped = facing.copy()
    dropped[:, 1] += drop
    skel_top = float(dropped[:, 1].max())
    if skel_top <= floor_y + 1e-9:
        raise FloorColumnBindError("skeleton has no height above the mesh floor")
    scale = (top_y - floor_y) / (skel_top - floor_y)
    if not np.isfinite(scale) or scale <= 0:
        raise FloorColumnBindError("floor-to-top scale must be finite and positive")
    pivot = np.array(
        [float(dropped[feet, 0].mean()), floor_y, float(dropped[feet, 2].mean())],
        dtype=np.float64,
    )
    placed = pivot + scale * (dropped - pivot)
    foot_xz = np.array([float(placed[feet, 0].mean()), float(placed[feet, 2].mean())], dtype=np.float64)
    placed[:, 0] += mesh_xz[0] - foot_xz[0]
    placed[:, 2] += mesh_xz[1] - foot_xz[1]
    if abs(float(placed[feet, 1].min()) - floor_y) > Y_ATOL:
        raise FloorColumnBindError("feet left the mesh floor")
    if abs(float(placed[:, 1].max()) - top_y) > Y_ATOL:
        raise FloorColumnBindError("skeleton top left the mesh top")
    translation = placed.mean(axis=0) - scale * facing.mean(axis=0)
    lengths = _uniform_length_scales(parents)
    angles = rest_direction_angles_deg(facing, placed, parents)
    return {
        "joints": placed,
        "preSuctionJoints": placed.copy(),
        "rotation": rotation,
        "yawDeg": seed_yaw_deg,
        "pitchDeg": 0.0,
        "rollDeg": 0.0,
        "extraYawDeg": 0.0,
        "scale": float(scale),
        "translation": translation,
        "footIndices": feet,
        "floorY": floor_y,
        "topY": top_y,
        "drop": float(drop),
        "pivot": pivot,
        "scales": lengths,
        "restAngleDeg": angles,
        "meanRestAngleDeg": float(np.mean(angles[1:])) if len(angles) > 1 else 0.0,
        "meanShortening": 0.0,
        "policy": GROUND_HEIGHT_POLICY,
        "containmentPolicy": GROUND_HEIGHT_CONTAINMENT,
        "placement": {
            "policy": GROUND_HEIGHT_CONTAINMENT,
            "jointsInsideCount": None,
            "jointCount": int(len(placed)),
            "outsideCount": None,
        },
    }


def origin_scale_until_feet_on_floor(
    placed: np.ndarray,
    parents: np.ndarray,
    floor_y: float,
    *,
    pivot_index: int = 0,
) -> tuple[np.ndarray, float, list[int]]:
    """Lab scale slider: grow/shrink about the bind origin until the lowest feet hit the floor."""
    placed = np.asarray(placed, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    if placed.ndim != 2 or placed.shape[1] != 3:
        raise FloorColumnBindError(f"placed joints must be [J,3], got {placed.shape}")
    if parents.shape != (len(placed),):
        raise FloorColumnBindError("parents must be [J]")
    if not (0 <= int(pivot_index) < len(placed)):
        raise FloorColumnBindError("origin-scale pivot is out of range")
    feet = identify_foot_joints(placed, parents)
    pivot = placed[int(pivot_index)].copy()
    foot_y = float(placed[feet, 1].min())
    if abs(foot_y - float(pivot[1])) <= 1e-9:
        raise FloorColumnBindError("feet sit on the scale pivot; cannot scale to the floor")
    extra = (float(floor_y) - float(pivot[1])) / (foot_y - float(pivot[1]))
    if not np.isfinite(extra) or extra <= 0:
        raise FloorColumnBindError("origin scale to the floor must be finite and positive")
    grown = pivot + extra * (placed - pivot)
    if abs(float(grown[feet, 1].min()) - float(floor_y)) > Y_ATOL:
        raise FloorColumnBindError("origin scale left the feet off the mesh floor")
    if np.max(np.abs(grown[int(pivot_index)] - pivot)) > Y_ATOL:
        raise FloorColumnBindError("origin scale moved the bind origin")
    return grown, float(extra), feet


def fit_rest_scale_to_ground(
    joints: np.ndarray,
    parents: np.ndarray,
    vertices: np.ndarray,
    triangles: np.ndarray | None = None,
    *,
    seed_yaw_deg: float = 0.0,
    names: list[str] | None = None,
    base_similarity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Yaw-fix bind, then the lab scale slider: uniform scale about the hips.

    The mesh stays. The extra scale is whatever puts the lowest feet on the
    mesh floor. No drop, no per-bone move.
    """
    del triangles, names, seed_yaw_deg
    if base_similarity is None:
        raise FloorColumnBindError("scale-to-ground requires the previous yaw-fix bind as its base")
    joints = np.asarray(joints, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    vertices = np.asarray(vertices, dtype=np.float64)
    if joints.ndim != 2 or joints.shape[1] != 3:
        raise FloorColumnBindError(f"joints must be [J,3], got {joints.shape}")
    if parents.shape != (len(joints),):
        raise FloorColumnBindError("parents must be [J]")
    if parents[0] != -1 or any(int(parent) < 0 or int(parent) >= index for index, parent in enumerate(parents[1:], 1)):
        raise FloorColumnBindError("hierarchy must be root-first ordered")
    if not np.isfinite(joints).all() or not np.isfinite(vertices).all():
        raise FloorColumnBindError("joints and vertices must be finite")
    rotation = np.asarray(base_similarity["rotation"], dtype=np.float64)
    base_scale = float(base_similarity["scale"])
    translation = np.asarray(base_similarity["translation"], dtype=np.float64).reshape(3)
    if rotation.shape != (3, 3) or not np.isfinite(rotation).all():
        raise FloorColumnBindError("yaw-fix base rotation must be a finite 3x3")
    if not np.isfinite(base_scale) or base_scale <= 0 or not np.isfinite(translation).all():
        raise FloorColumnBindError("yaw-fix base scale/translation must be finite and positive")
    placed = apply_similarity(joints, rotation=rotation, scale=base_scale, translation=translation)
    floor_y = float(vertices[:, 1].min())
    top_y = float(vertices[:, 1].max())
    grown, extra, feet = origin_scale_until_feet_on_floor(placed, parents, floor_y)
    scale = extra * base_scale
    lengths = _uniform_length_scales(parents)
    angles = rest_direction_angles_deg(placed, grown, parents)
    return {
        "joints": grown,
        "preSuctionJoints": grown.copy(),
        "rotation": rotation,
        "yawDeg": float(base_similarity.get("yawDeg", 0.0)),
        "pitchDeg": float(base_similarity.get("pitchDeg", 0.0)),
        "rollDeg": float(base_similarity.get("rollDeg", 0.0)),
        "extraYawDeg": 0.0,
        "scale": float(scale),
        "translation": translation.copy(),
        "footIndices": feet,
        "floorY": floor_y,
        "topY": top_y,
        "drop": 0.0,
        "pivot": placed[0].copy(),
        "originScale": float(extra),
        "baseScale": float(base_scale),
        "scales": lengths,
        "restAngleDeg": angles,
        "meanRestAngleDeg": float(np.mean(angles[1:])) if len(angles) > 1 else 0.0,
        "meanShortening": 0.0,
        "policy": SCALE_TO_GROUND_POLICY,
        "containmentPolicy": SCALE_TO_GROUND_CONTAINMENT,
        "placement": {
            "policy": SCALE_TO_GROUND_CONTAINMENT,
            "jointsInsideCount": None,
            "jointCount": int(len(grown)),
            "outsideCount": None,
        },
    }


def fit_rest_floor_column(
    joints: np.ndarray,
    parents: np.ndarray,
    vertices: np.ndarray,
    triangles: np.ndarray | None = None,
    *,
    seed_yaw_deg: float = 0.0,
    names: list[str] | None = None,
) -> dict[str, Any]:
    """Place a facing mocap skeleton on the mesh floor/top, then snap XZ only."""
    del names
    joints = np.asarray(joints, dtype=np.float64)
    parents = np.asarray(parents, dtype=np.int64)
    vertices = np.asarray(vertices, dtype=np.float64)
    if joints.ndim != 2 or joints.shape[1] != 3:
        raise FloorColumnBindError(f"joints must be [J,3], got {joints.shape}")
    if parents.shape != (len(joints),):
        raise FloorColumnBindError("parents must be [J]")
    if parents[0] != -1 or any(int(parent) < 0 or int(parent) >= index for index, parent in enumerate(parents[1:], 1)):
        raise FloorColumnBindError("hierarchy must be root-first ordered")
    if not np.isfinite(joints).all() or not np.isfinite(vertices).all():
        raise FloorColumnBindError("joints and vertices must be finite")
    seed_yaw_deg = float(seed_yaw_deg)
    facing = joints @ rotation_matrix(seed_yaw_deg, 0.0, 0.0).T
    volume = SliceVolume(vertices, triangles)
    feet = identify_foot_joints(facing, parents)
    drop = volume.floor_y - float(facing[feet, 1].min())
    dropped = facing.copy()
    dropped[:, 1] += drop
    dropped = _pin_feet_to_floor(dropped, parents, feet, volume.floor_y)
    skel_top = float(dropped[:, 1].max())
    if skel_top <= volume.floor_y + 1e-9:
        raise FloorColumnBindError("skeleton has no height above the mesh floor")
    scale = (volume.top_y - volume.floor_y) / (skel_top - volume.floor_y)
    if not np.isfinite(scale) or scale <= 0:
        raise FloorColumnBindError("floor-to-top scale must be finite and positive")
    sized = dropped.copy()
    sized[:, 1] = volume.floor_y + scale * (dropped[:, 1] - volume.floor_y)
    foot_xz = np.array(
        [float(sized[feet, 0].mean()), float(sized[feet, 2].mean())],
        dtype=np.float64,
    )
    mesh_xz = volume.layer_centroid_xz(0)
    sized[:, 0] += mesh_xz[0] - foot_xz[0]
    sized[:, 2] += mesh_xz[1] - foot_xz[1]
    pivot = np.array([mesh_xz[0], volume.floor_y, mesh_xz[1]], dtype=np.float64)
    best: tuple[tuple[int, float], float, np.ndarray] | None = None
    for yaw_deg in FLOOR_YAW_DEGS:
        trial = _rotate_y(sized, yaw_deg, pivot)
        score = _yaw_fit_score(volume, trial, feet, yaw_deg)
        if score is None:
            continue
        if best is None or score < best[0]:
            best = (score, float(yaw_deg), trial)
            if score == (0, 0.0):
                break
    if best is None:
        raise FloorColumnBindError("no yaw places the feet inside the mesh floor")
    extra_yaw = best[1]
    placed = best[2].copy()
    pre_suction = placed.copy()
    locked_y = placed[:, 1].copy()
    for index in np.argsort(placed[:, 1], kind="stable"):
        xz = volume.center_xz(placed[index])
        placed[index, 0] = xz[0]
        placed[index, 2] = xz[1]
        placed[index, 1] = locked_y[index]
    if not volume.all_joints_inside(placed):
        raise FloorColumnBindError("XZ suction left a joint outside a meaningful mesh slice")
    if abs(float(placed[feet, 1].min()) - volume.floor_y) > Y_ATOL:
        raise FloorColumnBindError("feet left the mesh floor")
    if abs(float(placed[:, 1].max()) - volume.top_y) > Y_ATOL:
        raise FloorColumnBindError("skeleton top left the mesh top")
    rotation = rotation_matrix(seed_yaw_deg + extra_yaw, 0.0, 0.0)
    translation = pre_suction.mean(axis=0) - scale * (joints @ rotation.T).mean(axis=0)
    lengths = np.ones(len(parents), dtype=np.float64)
    for index, parent in enumerate(parents):
        if parent < 0:
            continue
        source = float(np.linalg.norm(facing[index] - facing[parent]))
        dest = float(np.linalg.norm(placed[index] - placed[parent]))
        lengths[index] = dest / source if source > 1e-12 else 1.0
    angles = rest_direction_angles_deg(facing, placed, parents)
    return {
        "joints": placed,
        "preSuctionJoints": pre_suction,
        "rotation": rotation,
        "yawDeg": seed_yaw_deg + extra_yaw,
        "pitchDeg": 0.0,
        "rollDeg": 0.0,
        "extraYawDeg": extra_yaw,
        "scale": float(scale),
        "translation": translation,
        "footIndices": feet,
        "floorY": volume.floor_y,
        "topY": volume.top_y,
        "drop": float(drop),
        "pivot": pivot,
        "scales": lengths,
        "restAngleDeg": angles,
        "meanRestAngleDeg": float(np.mean(angles[1:])) if len(angles) > 1 else 0.0,
        "meanShortening": float(np.mean(np.maximum(0.0, 1.0 - lengths[1:]))) if len(lengths) > 1 else 0.0,
        "policy": POLICY,
        "containmentPolicy": CONTAINMENT_POLICY,
        "placement": volume.placement_report(placed),
    }
