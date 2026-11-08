"""Place billboard pixels in 3D using a Video Depth Anything depth map.

Convention matches ``run_vda_movement_depth.py``:

- VDA relative depth is stored near=bright in [0, 1].
- Outside sprite alpha is zero.
- Billboard space is X right, Y up, +Z toward the camera (the authored quad
  normal). Near pixels move toward the camera.

There is no triangle connectivity. The result is an unordered set of opaque
pixels, each a colored point on the original billboard plane, offset on Z.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image

from fill import prepare_billboard_frame

ALPHA_OPAQUE = 0.08


def _depth_prepare_kwargs(
    *,
    gap_close_radius: int,
    depth_smooth_radius: int,
    depth_bow_vertical_strength: float,
    depth_bow_edge_strength: float,
    depth_bow_local_radius: int,
    depth_bow_edge_falloff_pixels: float,
    depth_edge_strength: float,
    depth_edge_falloff_pixels: float,
    depth_wing_lateral_strength: float,
    depth_wing_lateral_upper_fraction: float,
    depth_wing_lateral_body_lower_fraction: float,
) -> dict:
    return {
        "gap_close_radius": gap_close_radius,
        "depth_smooth_radius": depth_smooth_radius,
        "depth_bow_vertical_strength": depth_bow_vertical_strength,
        "depth_bow_edge_strength": depth_bow_edge_strength,
        "depth_bow_local_radius": depth_bow_local_radius,
        "depth_bow_edge_falloff_pixels": depth_bow_edge_falloff_pixels,
        "depth_edge_strength": depth_edge_strength,
        "depth_edge_falloff_pixels": depth_edge_falloff_pixels,
        "depth_wing_lateral_strength": depth_wing_lateral_strength,
        "depth_wing_lateral_upper_fraction": depth_wing_lateral_upper_fraction,
        "depth_wing_lateral_body_lower_fraction": depth_wing_lateral_body_lower_fraction,
    }


def _needs_depth_prepare(
    gap_close_radius: int,
    depth_smooth_radius: int,
    depth_bow_vertical_strength: float,
    depth_bow_edge_strength: float,
    depth_edge_strength: float,
    depth_wing_lateral_strength: float,
) -> bool:
    return (
        gap_close_radius > 0
        or depth_smooth_radius > 0
        or depth_bow_vertical_strength > 0.0
        or depth_bow_edge_strength > 0.0
        or depth_edge_strength > 0.0
        or depth_wing_lateral_strength > 0.0
    )


@dataclass(frozen=True)
class BillboardPoints:
    """Opaque billboard pixels in object space. Units: sprite height = 1."""

    xy: np.ndarray
    z: np.ndarray
    rgba: np.ndarray
    width: int
    height: int
    depth_scale: float
    pivot: float
    source_rgba: np.ndarray | None = None
    # +1 front shell, -1 back shell, 0 rim (connecting edge). None = render all.
    facing: np.ndarray | None = None

    def __post_init__(self) -> None:
        n = int(self.xy.shape[0])
        if self.xy.shape != (n, 2):
            raise ValueError(f"xy must be (N, 2), got {self.xy.shape}")
        if self.z.shape != (n,):
            raise ValueError(f"z must be (N,), got {self.z.shape}")
        if self.rgba.shape != (n, 4):
            raise ValueError(f"rgba must be (N, 4), got {self.rgba.shape}")
        if self.facing is not None and self.facing.shape != (n,):
            raise ValueError(f"facing must be (N,), got {self.facing.shape}")
        if self.width < 1 or self.height < 1:
            raise ValueError("billboard pixel size must be positive")
        if self.depth_scale <= 0.0:
            raise ValueError("depth_scale must be positive")

    @property
    def count(self) -> int:
        return int(self.xy.shape[0])

    @property
    def aspect(self) -> float:
        return float(self.width) / float(self.height)

    def xyz(self) -> np.ndarray:
        return np.column_stack((self.xy[:, 0], self.xy[:, 1], self.z))


def load_depth01(path: Path) -> np.ndarray:
    """Load a VDA pipeline depth PNG as near=bright float32 in [0, 1]."""
    image = Image.open(path)
    array = np.asarray(image)
    if array.ndim == 3:
        array = array[..., 0]
    if array.dtype == np.uint16:
        return array.astype(np.float32) / 65535.0
    if array.dtype == np.uint8:
        return array.astype(np.float32) / 255.0
    raise ValueError(f"unsupported depth dtype {array.dtype} at {path}")


def _opaque_mask(rgba: np.ndarray) -> np.ndarray:
    return rgba[..., 3].astype(np.float32) / 255.0 > ALPHA_OPAQUE


def _pivot_depth(depth01: np.ndarray, mask: np.ndarray) -> float:
    if not mask.any():
        raise ValueError("sprite has no opaque pixels")
    return float(np.median(depth01[mask]))


def billboard_points_from_frame(
    rgba: np.ndarray,
    depth01: np.ndarray,
    *,
    depth_scale: float = 0.35,
    pivot: float | None = None,
    gap_close_radius: int = 1,
    depth_smooth_radius: int = 1,
    depth_edge_strength: float = 0.0,
    depth_edge_falloff_pixels: float = 3.0,
    depth_bow_vertical_strength: float = 0.0,
    depth_bow_edge_strength: float = 0.0,
    depth_bow_local_radius: int = 7,
    depth_bow_edge_falloff_pixels: float = 3.0,
    depth_wing_lateral_strength: float = 0.0,
    depth_wing_lateral_upper_fraction: float = 0.5,
    depth_wing_lateral_body_lower_fraction: float = 0.5,
) -> BillboardPoints:
    """Convert one RGBA sprite + VDA depth map into 3D billboard points.

    ``depth_scale`` is world thickness for a full 0→1 depth span, in units of
    sprite height. ``pivot`` defaults to the median opaque depth so the body
    stays on the original billboard plane.

    ``gap_close_radius`` / ``depth_smooth_radius`` close tiny alpha holes and
    smooth depth before extracting points (default 1). Set both to 0 to keep
    the raw sprite occupancy.
    """
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError(f"rgba must be HxWx4, got {rgba.shape}")
    if depth01.shape != rgba.shape[:2]:
        raise ValueError(
            f"depth shape {depth01.shape} does not match sprite {rgba.shape[:2]}"
        )
    if float(depth_scale) <= 0.0:
        raise ValueError("depth_scale must be positive")

    prepared_rgba, prepared_depth = rgba, depth01
    if _needs_depth_prepare(
        gap_close_radius,
        depth_smooth_radius,
        depth_bow_vertical_strength,
        depth_bow_edge_strength,
        depth_edge_strength,
        depth_wing_lateral_strength,
    ):
        prepared_rgba, prepared_depth, _ = prepare_billboard_frame(
            rgba,
            depth01,
            **_depth_prepare_kwargs(
                gap_close_radius=gap_close_radius,
                depth_smooth_radius=depth_smooth_radius,
                depth_bow_vertical_strength=depth_bow_vertical_strength,
                depth_bow_edge_strength=depth_bow_edge_strength,
                depth_bow_local_radius=depth_bow_local_radius,
                depth_bow_edge_falloff_pixels=depth_bow_edge_falloff_pixels,
                depth_edge_strength=depth_edge_strength,
                depth_edge_falloff_pixels=depth_edge_falloff_pixels,
                depth_wing_lateral_strength=depth_wing_lateral_strength,
                depth_wing_lateral_upper_fraction=depth_wing_lateral_upper_fraction,
                depth_wing_lateral_body_lower_fraction=depth_wing_lateral_body_lower_fraction,
            ),
        )

    height, width = prepared_rgba.shape[:2]
    mask = _opaque_mask(prepared_rgba)
    if not mask.any():
        raise ValueError("sprite has no opaque pixels")
    chosen_pivot = _pivot_depth(prepared_depth, mask) if pivot is None else float(pivot)
    rows, cols = np.nonzero(mask)
    xs = ((cols.astype(np.float32) + 0.5) / float(width) - 0.5) * (
        float(width) / float(height)
    )
    ys = 0.5 - (rows.astype(np.float32) + 0.5) / float(height)
    z = (prepared_depth[rows, cols] - chosen_pivot) * float(depth_scale)
    return BillboardPoints(
        xy=np.column_stack((xs, ys)).astype(np.float32, copy=False),
        z=z.astype(np.float32, copy=False),
        rgba=prepared_rgba[rows, cols].copy(),
        width=int(width),
        height=int(height),
        depth_scale=float(depth_scale),
        pivot=chosen_pivot,
        source_rgba=prepared_rgba.copy(),
    )


def _interior_mask(mask: np.ndarray) -> np.ndarray:
    """Opaque pixels whose 4-neighbors are all opaque."""
    safe = mask.astype(bool)
    interior = safe.copy()
    interior[1:, :] &= safe[:-1, :]
    interior[:-1, :] &= safe[1:, :]
    interior[:, 1:] &= safe[:, :-1]
    interior[:, :-1] &= safe[:, :-1]
    return interior


def _pixel_xy(rows: np.ndarray, cols: np.ndarray, height: int, width: int) -> np.ndarray:
    xs = ((cols.astype(np.float32) + 0.5) / float(width) - 0.5) * (
        float(width) / float(height)
    )
    ys = 0.5 - (rows.astype(np.float32) + 0.5) / float(height)
    return np.column_stack((xs, ys)).astype(np.float32, copy=False)


@dataclass(frozen=True)
class AnchoredZSurfaces:
    """Per-pixel anchored front/back Z surfaces in billboard object space."""

    rgba: np.ndarray
    mask: np.ndarray
    z_front: np.ndarray
    z_back: np.ndarray
    width: int
    height: int
    depth_scale: float
    pivot: float


def compute_anchored_z_surfaces(
    rgba: np.ndarray,
    depth01: np.ndarray,
    *,
    depth_scale: float = 0.35,
    pivot: float | None = None,
    gap_close_radius: int = 1,
    depth_smooth_radius: int = 1,
    thickness_scale: float = 2.0,
    depth_edge_strength: float = 0.0,
    depth_edge_falloff_pixels: float = 3.0,
    depth_bow_vertical_strength: float = 0.0,
    depth_bow_edge_strength: float = 0.0,
    depth_bow_local_radius: int = 7,
    depth_bow_edge_falloff_pixels: float = 3.0,
    depth_wing_lateral_strength: float = 0.0,
    depth_wing_lateral_upper_fraction: float = 0.5,
    depth_wing_lateral_body_lower_fraction: float = 0.5,
) -> AnchoredZSurfaces:
    """Prepare sprite depth and return full-grid anchored front/back Z surfaces."""
    if thickness_scale <= 0.0:
        raise ValueError("thickness_scale must be positive")
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError(f"rgba must be HxWx4, got {rgba.shape}")
    if depth01.shape != rgba.shape[:2]:
        raise ValueError(
            f"depth shape {depth01.shape} does not match sprite {rgba.shape[:2]}"
        )
    if float(depth_scale) <= 0.0:
        raise ValueError("depth_scale must be positive")

    from scipy.ndimage import distance_transform_edt

    prepared_rgba, prepared_depth = rgba, depth01
    if _needs_depth_prepare(
        gap_close_radius,
        depth_smooth_radius,
        depth_bow_vertical_strength,
        depth_bow_edge_strength,
        depth_edge_strength,
        depth_wing_lateral_strength,
    ):
        prepared_rgba, prepared_depth, _ = prepare_billboard_frame(
            rgba,
            depth01,
            **_depth_prepare_kwargs(
                gap_close_radius=gap_close_radius,
                depth_smooth_radius=depth_smooth_radius,
                depth_bow_vertical_strength=depth_bow_vertical_strength,
                depth_bow_edge_strength=depth_bow_edge_strength,
                depth_bow_local_radius=depth_bow_local_radius,
                depth_bow_edge_falloff_pixels=depth_bow_edge_falloff_pixels,
                depth_edge_strength=depth_edge_strength,
                depth_edge_falloff_pixels=depth_edge_falloff_pixels,
                depth_wing_lateral_strength=depth_wing_lateral_strength,
                depth_wing_lateral_upper_fraction=depth_wing_lateral_upper_fraction,
                depth_wing_lateral_body_lower_fraction=depth_wing_lateral_body_lower_fraction,
            ),
        )

    height, width = prepared_rgba.shape[:2]
    mask = _opaque_mask(prepared_rgba)
    if not mask.any():
        raise ValueError("sprite has no opaque pixels")
    chosen_pivot = _pivot_depth(prepared_depth, mask) if pivot is None else float(pivot)
    z_grid = (prepared_depth - chosen_pivot) * float(depth_scale)
    edge_distance = distance_transform_edt(mask)
    pixel_world = 1.0 / float(height)
    thickness = np.maximum(
        edge_distance.astype(np.float32) * float(thickness_scale) * pixel_world,
        pixel_world,
    )
    z_front = np.where(mask, z_grid, np.nan).astype(np.float32, copy=False)
    z_back = np.where(mask, z_grid - thickness, np.nan).astype(np.float32, copy=False)
    return AnchoredZSurfaces(
        rgba=prepared_rgba.copy(),
        mask=mask,
        z_front=z_front,
        z_back=z_back,
        width=int(width),
        height=int(height),
        depth_scale=float(depth_scale),
        pivot=chosen_pivot,
    )


def build_connected_depth_volume(
    rgba: np.ndarray,
    depth01: np.ndarray,
    *,
    depth_scale: float = 0.35,
    pivot: float | None = None,
    gap_close_radius: int = 1,
    depth_smooth_radius: int = 1,
    fill_spacing_pixels: float = 1.0,
    thickness_scale: float = 2.0,
    depth_edge_strength: float = 0.0,
    depth_edge_falloff_pixels: float = 3.0,
    depth_bow_vertical_strength: float = 0.0,
    depth_bow_edge_strength: float = 0.0,
    depth_bow_local_radius: int = 7,
    depth_bow_edge_falloff_pixels: float = 3.0,
    depth_wing_lateral_strength: float = 0.0,
    depth_wing_lateral_upper_fraction: float = 0.5,
    depth_wing_lateral_body_lower_fraction: float = 0.5,
) -> BillboardPoints:
    """Anchored clam-shell volume: VDA front surface + local-thickness back fill.

    Every opaque pixel keeps its VDA front depth and is extruded *backward* by a
    local thickness estimated from the silhouette's distance transform (distance
    to the nearest transparent edge, in pixels). Thin features like a sword stay
    thin and stay at their VDA depth instead of being re-centered on the
    billboard plane; wide regions like the torso get proportionally deeper fill.

    Columns are sampled at ``fill_spacing_pixels`` world-pixel spacing so side
    views read as one solid surface, not stacked sheets.
    """
    if fill_spacing_pixels <= 0.0:
        raise ValueError("fill_spacing_pixels must be positive")
    if thickness_scale <= 0.0:
        raise ValueError("thickness_scale must be positive")
    if rgba.ndim != 3 or rgba.shape[2] != 4:
        raise ValueError(f"rgba must be HxWx4, got {rgba.shape}")
    if depth01.shape != rgba.shape[:2]:
        raise ValueError(
            f"depth shape {depth01.shape} does not match sprite {rgba.shape[:2]}"
        )
    if float(depth_scale) <= 0.0:
        raise ValueError("depth_scale must be positive")

    surfaces = compute_anchored_z_surfaces(
        rgba,
        depth01,
        depth_scale=depth_scale,
        pivot=pivot,
        gap_close_radius=gap_close_radius,
        depth_smooth_radius=depth_smooth_radius,
        thickness_scale=thickness_scale,
        depth_edge_strength=depth_edge_strength,
        depth_edge_falloff_pixels=depth_edge_falloff_pixels,
        depth_bow_vertical_strength=depth_bow_vertical_strength,
        depth_bow_edge_strength=depth_bow_edge_strength,
        depth_bow_local_radius=depth_bow_local_radius,
        depth_bow_edge_falloff_pixels=depth_bow_edge_falloff_pixels,
        depth_wing_lateral_strength=depth_wing_lateral_strength,
        depth_wing_lateral_upper_fraction=depth_wing_lateral_upper_fraction,
        depth_wing_lateral_body_lower_fraction=depth_wing_lateral_body_lower_fraction,
    )
    prepared_rgba = surfaces.rgba
    mask = surfaces.mask
    height = surfaces.height
    width = surfaces.width
    chosen_pivot = surfaces.pivot
    rows, cols = np.nonzero(mask)
    z_front = surfaces.z_front[rows, cols]
    z_back = surfaces.z_back[rows, cols]
    thickness = z_front - z_back
    pixel_world = 1.0 / float(height)
    step_world = float(fill_spacing_pixels) * pixel_world
    counts = np.maximum(2, np.ceil(thickness / step_world).astype(np.int64) + 1)

    pixel_index = np.repeat(np.arange(rows.size, dtype=np.int64), counts)
    total = int(counts.sum())
    starts = np.concatenate(([0], np.cumsum(counts)[:-1]))
    local = np.arange(total, dtype=np.int64) - np.repeat(starts, counts)
    t = local.astype(np.float32) / np.repeat(counts - 1, counts).astype(np.float32)

    xy_band = _pixel_xy(rows, cols, height, width)
    z_all = z_back[pixel_index] + t * thickness[pixel_index]

    return BillboardPoints(
        xy=xy_band[pixel_index],
        z=z_all.astype(np.float32, copy=False),
        rgba=prepared_rgba[rows, cols][pixel_index],
        width=int(width),
        height=int(height),
        depth_scale=float(depth_scale),
        pivot=chosen_pivot,
        source_rgba=prepared_rgba.copy(),
        facing=None,
    )


def mirror_billboard_depth_volume(points: BillboardPoints) -> BillboardPoints:
    """Legacy Z-mirror duplicate. Prefer ``build_connected_depth_volume``."""
    return BillboardPoints(
        xy=np.concatenate([points.xy, points.xy], axis=0),
        z=np.concatenate([points.z, -points.z], axis=0),
        rgba=np.concatenate([points.rgba, points.rgba], axis=0),
        width=points.width,
        height=points.height,
        depth_scale=points.depth_scale,
        pivot=points.pivot,
        source_rgba=points.source_rgba,
        facing=None,
    )
