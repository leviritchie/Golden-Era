"""Reference animation frames (sprite-motion articulation) as a bind constraint source.

Read side of ``tools/homm3_sprite_motion_track/discover_articulation_from_motion.py``.
That lane turns a source animation into rigid parts, relative hinges, and
per-frame part centroids from dense sprite tracks; an owned-bind solver needs
those quantities plus the exact orthographic camera the sprite lane renders
with, so this module owns the loader and the projection and nothing else.

The camera contract mirrors ``tools/homm3_silhouette_pose_fit/homm3_pose_camera.py``
and ``blender_map_articulation_parts.py::_project_world_px``.  Mesh points are
expected in the same Z-up frame the sprite lane imports; ``root_yaw_deg`` is the
armature root yaw that lane applies before rendering.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

FRAMES_SCHEMA = "reference_frame_bind_frames.v1"
PART_PREFIX = "part_"

_DEFAULTS = {
    "distance": 3.0,
    "height": 0.85,
    "orthoScale": 2.6,
    "isoAzimuthDeg": 40.0,
    "isoElevationDeg": 30.0,
    "isoZOffset": 0.35,
    "lookAtZ": 0.75,
}


def part_index(name: str) -> int:
    """``part_03`` -> 3.  The articulation lane's only part vocabulary."""
    if not name.startswith(PART_PREFIX):
        raise ValueError(f"part name {name!r} does not use the {PART_PREFIX}NN contract")
    return int(name[len(PART_PREFIX) :])


def effective_root_yaw_deg(job: dict[str, Any]) -> float:
    cam = job.get("camera") or {}
    mirror = job.get("mirror") or {}
    return float(cam.get("rootYawDeg", 0.0)) + float(mirror.get("reorientYawDeg", 0.0))


@dataclass(frozen=True)
class CameraSpec:
    axis: str = "iso"
    distance: float = _DEFAULTS["distance"]
    height: float = _DEFAULTS["height"]
    ortho_scale: float = _DEFAULTS["orthoScale"]
    iso_azimuth_deg: float = _DEFAULTS["isoAzimuthDeg"]
    iso_elevation_deg: float = _DEFAULTS["isoElevationDeg"]
    iso_z_offset: float = _DEFAULTS["isoZOffset"]
    look_at_z: float = _DEFAULTS["lookAtZ"]
    root_yaw_deg: float = 0.0
    ortho_scale_axis: str = "auto"


def camera_from_job(job: dict[str, Any]) -> CameraSpec:
    cam = dict(job.get("camera") or {})
    axis = str(cam.get("axis", "iso"))
    if axis.upper() == "ISO":
        axis = "iso"
    return CameraSpec(
        axis=axis,
        distance=float(cam.get("distance", _DEFAULTS["distance"])),
        height=float(cam.get("height", _DEFAULTS["height"])),
        ortho_scale=float(cam.get("orthoScale", _DEFAULTS["orthoScale"])),
        iso_azimuth_deg=float(cam.get("isoAzimuthDeg", _DEFAULTS["isoAzimuthDeg"])),
        iso_elevation_deg=float(cam.get("isoElevationDeg", _DEFAULTS["isoElevationDeg"])),
        iso_z_offset=float(cam.get("isoZOffset", _DEFAULTS["isoZOffset"])),
        look_at_z=float(cam.get("lookAtZ", _DEFAULTS["lookAtZ"])),
        root_yaw_deg=effective_root_yaw_deg(job),
        ortho_scale_axis=str(cam.get("orthoScaleAxis", "auto")),
    )


@dataclass(frozen=True)
class CameraBasis:
    location: np.ndarray
    right: np.ndarray
    up: np.ndarray
    forward: np.ndarray
    width_world: float
    height_world: float
    sprite_size: tuple[int, int]


def _euler_xyz_matrix(rx: float, ry: float, rz: float) -> np.ndarray:
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    mat = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    mat = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]]) @ mat
    return np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]]) @ mat


def _track_minus_z_y(direction: np.ndarray) -> np.ndarray:
    """Blender ``Vector.to_track_quat('-Z', 'Y')``.

    Local -Z points along ``direction`` and local +Y stays as close to world +Z
    as possible: the standard camera look-at idiom ``setup_pose_camera`` uses.
    """
    norm = float(np.linalg.norm(direction))
    if norm < 1e-12:
        raise ValueError("camera direction is degenerate")
    z_axis = -direction / norm
    world_up = np.array([0.0, 0.0, 1.0])
    up = world_up - float(np.dot(world_up, z_axis)) * z_axis
    up_norm = float(np.linalg.norm(up))
    if up_norm < 1e-9:
        raise ValueError("camera direction is parallel to world +Z; to_track_quat('Y') is degenerate")
    up = up / up_norm
    right = np.cross(up, z_axis)
    right = right / float(np.linalg.norm(right))
    return np.column_stack((right, up, z_axis))


def _ortho_frame(camera: CameraSpec, sw: int, sh: int) -> tuple[float, float]:
    """Blender maps ``orthoScale`` across the larger render dimension (sensor fit AUTO)."""
    scale = camera.ortho_scale
    axis = camera.ortho_scale_axis
    if axis == "x":
        return scale, scale * sh / sw
    if axis == "y":
        return scale * sw / sh, scale
    if sw >= sh:
        return scale, scale * sh / sw
    return scale * sw / sh, scale


def camera_basis(camera: CameraSpec, sprite_size: tuple[int, int]) -> CameraBasis:
    sw, sh = int(sprite_size[0]), int(sprite_size[1])
    if sw <= 0 or sh <= 0:
        raise ValueError(f"bad sprite size {sprite_size}")
    distance = camera.distance
    if camera.axis == "iso":
        azimuth = math.radians(camera.iso_azimuth_deg)
        elevation = math.radians(camera.iso_elevation_deg)
        radius = distance * math.cos(elevation)
        loc = np.array(
            [
                -radius * math.sin(azimuth),
                -radius * math.cos(azimuth),
                distance * math.sin(elevation) + camera.iso_z_offset,
            ]
        )
        target = np.array([0.0, 0.0, camera.look_at_z])
        rot = _track_minus_z_y(target - loc)
    elif camera.axis == "-X":
        loc = np.array([-distance, 0.0, camera.height])
        rot = _euler_xyz_matrix(math.pi / 2.0, 0.0, -math.pi / 2.0)
    elif camera.axis == "+X":
        loc = np.array([distance, 0.0, camera.height])
        rot = _euler_xyz_matrix(math.pi / 2.0, 0.0, math.pi / 2.0)
    elif camera.axis == "-Y":
        loc = np.array([0.0, -distance, camera.height])
        rot = _euler_xyz_matrix(math.pi / 2.0, 0.0, 0.0)
    elif camera.axis == "+Y":
        loc = np.array([0.0, distance, camera.height])
        rot = _euler_xyz_matrix(math.pi / 2.0, 0.0, math.pi)
    else:
        raise ValueError(f"unsupported camera axis {camera.axis!r}")
    width, height = _ortho_frame(camera, sw, sh)
    return CameraBasis(
        location=loc,
        right=rot[:, 0].copy(),
        up=rot[:, 1].copy(),
        forward=-rot[:, 2].copy(),
        width_world=width,
        height_world=height,
        sprite_size=(sw, sh),
    )


def root_yaw_matrix(deg: float) -> np.ndarray:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def apply_root_yaw(points: np.ndarray, deg: float) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float64)
    if abs(float(deg)) < 1e-12:
        return pts
    return pts @ root_yaw_matrix(deg).T


def project_points(points: np.ndarray, basis: CameraBasis) -> np.ndarray:
    """(N,3) world -> (N,3) ``[px, py, depth]``; depth is along the view direction."""
    rel = np.asarray(points, dtype=np.float64) - basis.location
    cx = rel @ basis.right
    cy = rel @ basis.up
    depth = rel @ basis.forward
    sw, sh = basis.sprite_size
    return np.column_stack(
        (
            (cx / basis.width_world + 0.5) * sw,
            (0.5 - cy / basis.height_world) * sh,
            depth,
        )
    )


def pixel_offset(px: float, py: float, basis: CameraBasis) -> tuple[float, float]:
    sw, sh = basis.sprite_size
    return (
        (float(px) / sw - 0.5) * basis.width_world,
        (0.5 - float(py) / sh) * basis.height_world,
    )


def ray_origin(px: float, py: float, basis: CameraBasis) -> np.ndarray:
    cx, cy = pixel_offset(px, py, basis)
    return basis.location + basis.right * cx + basis.up * cy


def ray_point(px: float, py: float, t: float, basis: CameraBasis) -> np.ndarray:
    return ray_origin(px, py, basis) + basis.forward * float(t)


@dataclass
class ReferenceFrames:
    """Rigid parts, hinges, and per-frame part centroids from the sprite animation."""

    source_report: str
    tracks_path: str
    parts: list[dict[str, Any]]
    part_names: list[str]
    centroids: np.ndarray  # (F, P, 2) sprite px, NaN where the part is absent
    hinges: list[dict[str, Any]]
    track_xy0: np.ndarray  # (Nt, 2) sprite px at the bind frame
    track_labels: np.ndarray  # (Nt,)

    @property
    def part_count(self) -> int:
        return len(self.parts)

    @property
    def frame_count(self) -> int:
        return int(self.centroids.shape[0])

    def centroid_f0(self, part: int) -> np.ndarray:
        c0 = self.parts[part].get("centroidF0")
        if not isinstance(c0, (list, tuple)) or len(c0) != 2:
            raise ValueError(f"part {part} has no centroidF0 in {self.source_report}")
        return np.array([float(c0[0]), float(c0[1])], dtype=np.float64)

    def hinge_pairs(self) -> dict[tuple[int, int], dict[str, Any]]:
        out: dict[tuple[int, int], dict[str, Any]] = {}
        for hinge in self.hinges:
            a = part_index(str(hinge["partA"]))
            b = part_index(str(hinge["partB"]))
            out[(min(a, b), max(a, b))] = hinge
        return out

    def hinge_pixel(self, a: int, b: int) -> tuple[float, float]:
        hinge = self.hinge_pairs()[(min(a, b), max(a, b))]
        return float(hinge["x"]), float(hinge["y"])


def load_reference_frames(articulation_report: Path) -> ReferenceFrames:
    """Load and validate ``articulation_report.json`` + its ``tracks.npz``."""
    path = Path(articulation_report)
    if not path.is_file():
        raise FileNotFoundError(f"articulation report missing: {path}")
    report = json.loads(path.read_text(encoding="utf-8"))
    parts = report.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValueError(f"{path}: articulation report has no parts")
    rows = report.get("partCentroidsPerFrame")
    if not isinstance(rows, list) or not rows:
        raise ValueError(f"{path}: articulation report has no partCentroidsPerFrame")
    count = len(parts)
    centroids = np.full((len(rows), count, 2), np.nan, dtype=np.float64)
    for frame_index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != count:
            raise ValueError(
                f"{path}: partCentroidsPerFrame[{frame_index}] is not a {count}-entry row"
            )
        for part_id, item in enumerate(row):
            if item is None:
                continue
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                raise ValueError(
                    f"{path}: partCentroidsPerFrame[{frame_index}][{part_id}] is not [x,y]"
                )
            centroids[frame_index, part_id] = (float(item[0]), float(item[1]))
    if not np.isfinite(centroids[0]).all():
        missing = [
            f"{PART_PREFIX}{part_id:02d}"
            for part_id in range(count)
            if not np.isfinite(centroids[0, part_id]).all()
        ]
        raise ValueError(
            f"{path}: no bind-frame centroid for {missing}; the bind frame must observe every part"
        )
    names: list[str] = []
    for part_id, part in enumerate(parts):
        name = str(part.get("id") or f"{PART_PREFIX}{part_id:02d}")
        if name != f"{PART_PREFIX}{part_id:02d}":
            raise ValueError(
                f"{path}: part {part_id} id {name!r} breaks the {PART_PREFIX}NN contract"
            )
        names.append(name)
    tracks_path = Path(str(report.get("tracks") or ""))
    if not tracks_path.is_file():
        raise FileNotFoundError(f"{path}: tracks.npz missing: {tracks_path}")
    with np.load(tracks_path) as tracks:
        xy0 = np.asarray(tracks["xy0"], dtype=np.float64)
        labels = np.asarray(tracks["labels"], dtype=np.int64).reshape(-1)
    if xy0.ndim != 2 or xy0.shape[1] != 2 or labels.shape[0] != xy0.shape[0]:
        raise ValueError(f"{tracks_path}: xy0/labels shape mismatch {xy0.shape} / {labels.shape}")
    if labels.size and (int(labels.min()) < 0 or int(labels.max()) >= count):
        raise ValueError(f"{tracks_path}: track labels out of range for {count} parts")
    hinges = report.get("hinges")
    if not isinstance(hinges, list):
        raise ValueError(f"{path}: articulation report has no hinges list")
    for hinge in hinges:
        part_index(str(hinge["partA"]))
        part_index(str(hinge["partB"]))
        float(hinge["x"])
        float(hinge["y"])
        float(hinge.get("relMotionPx") or 0.0)
    return ReferenceFrames(
        source_report=str(path.resolve()).replace("\\", "/"),
        tracks_path=str(tracks_path.resolve()).replace("\\", "/"),
        parts=parts,
        part_names=names,
        centroids=centroids,
        hinges=hinges,
        track_xy0=xy0,
        track_labels=labels,
    )


def load_sprite_alpha(path: Path) -> np.ndarray:
    from PIL import Image

    with Image.open(path) as image:
        return np.asarray(image.convert("RGBA").split()[-1], dtype=np.uint8)


load_reference_frames = load_reference_frames
camera_from_job = camera_from_job
camera_basis = camera_basis
project_points = project_points
