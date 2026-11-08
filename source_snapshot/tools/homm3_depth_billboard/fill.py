"""Close 1-pixel silhouette gaps and smooth VDA depth before billboard placement.

Depth billboards are sparse pixel clouds. Small holes in the occupancy (common on
anti-aliased HoMM3 edges) and jagged depth maps read as pinholes when the cloud is
viewed in 3D. This module closes only pixels inside a morphological close of the
original opaque mask, then interpolates RGBA + depth from known neighbors. It does
not invent pixels outside the closed silhouette.
"""
from __future__ import annotations

import numpy as np

ALPHA_OPAQUE = 0.08


def _opaque_mask(rgba: np.ndarray) -> np.ndarray:
    return rgba[..., 3].astype(np.float32) / 255.0 > ALPHA_OPAQUE


def _binary_dilate(mask: np.ndarray) -> np.ndarray:
    """8-connected binary dilation."""
    padded = np.pad(mask, 1, mode="constant", constant_values=False)
    h, w = mask.shape
    out = mask.copy()
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            out |= padded[1 + dr : 1 + dr + h, 1 + dc : 1 + dc + w]
    return out


def _binary_erode(mask: np.ndarray) -> np.ndarray:
    """8-connected binary erosion."""
    padded = np.pad(mask, 1, mode="constant", constant_values=True)
    h, w = mask.shape
    out = mask.copy()
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            out &= padded[1 + dr : 1 + dr + h, 1 + dc : 1 + dc + w]
    return out


def morph_close(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius < 1:
        return mask.astype(bool, copy=True)
    closed = mask.astype(bool, copy=True)
    for _ in range(radius):
        closed = _binary_dilate(closed)
    for _ in range(radius):
        closed = _binary_erode(closed)
    return closed


def _neighbor_indices(h: int, w: int) -> tuple[np.ndarray, np.ndarray]:
    offsets = ((-1, 0), (1, 0), (0, -1), (0, 1))
    rows = np.arange(h, dtype=np.int32)
    cols = np.arange(w, dtype=np.int32)
    grid_r = np.broadcast_to(rows[:, None], (h, w))
    grid_c = np.broadcast_to(cols[None, :], (h, w))
    neighbor_rows: list[np.ndarray] = []
    neighbor_cols: list[np.ndarray] = []
    for dr, dc in offsets:
        nr = np.clip(grid_r + dr, 0, h - 1)
        nc = np.clip(grid_c + dc, 0, w - 1)
        # ignore wrap: only use neighbor if actually adjacent
        valid = (grid_r + dr >= 0) & (grid_r + dr < h) & (grid_c + dc >= 0) & (grid_c + dc < w)
        neighbor_rows.append(np.where(valid, grid_r + dr, grid_r))
        neighbor_cols.append(np.where(valid, grid_c + dc, grid_c))
    return neighbor_rows, neighbor_cols


def _interpolate_gaps(
    rgba: np.ndarray,
    depth01: np.ndarray,
    source_mask: np.ndarray,
    target_mask: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Fill gap pixels from 4-connected known neighbors (iterative)."""
    rgba_out = rgba.copy()
    depth_out = depth01.astype(np.float32, copy=True)
    known = source_mask.astype(bool, copy=True)
    gap = target_mask.astype(bool) & ~known
    if not gap.any():
        return rgba_out, depth_out

    h, w = known.shape
    neighbor_rows, neighbor_cols = _neighbor_indices(h, w)
    max_iters = int(gap.sum()) + 4
    for _ in range(max_iters):
        if not gap.any():
            break
        gap_rows, gap_cols = np.nonzero(gap)
        filled_any = False
        for r, c in zip(gap_rows, gap_cols):
            n_r = [nr[r, c] for nr in neighbor_rows]
            n_c = [nc[r, c] for nc in neighbor_cols]
            known_neighbors = [
                (nr, nc)
                for nr, nc in zip(n_r, n_c)
                if known[nr, nc]
                and (nr != r or nc != c)
                and (abs(nr - r) + abs(nc - c) == 1)
            ]
            if not known_neighbors:
                continue
            rgb = np.mean([rgba_out[nr, nc, :3] for nr, nc in known_neighbors], axis=0)
            alpha = float(np.mean([rgba_out[nr, nc, 3] for nr, nc in known_neighbors]))
            depth_val = float(np.mean([depth_out[nr, nc] for nr, nc in known_neighbors]))
            rgba_out[r, c, :3] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
            rgba_out[r, c, 3] = int(np.clip(np.rint(alpha), 0, 255))
            depth_out[r, c] = depth_val
            known[r, c] = True
            gap[r, c] = False
            filled_any = True
        if not filled_any:
            break
    if gap.any():
        raise ValueError(
            f"could not interpolate {int(gap.sum())} gap pixels; "
            "increase gap_close_radius or inspect the source alpha"
        )
    return rgba_out, depth_out


def smooth_depth_box(depth01: np.ndarray, mask: np.ndarray, radius: int) -> np.ndarray:
    """Box-smooth depth inside ``mask``. Values outside mask stay untouched."""
    if radius < 1:
        return depth01.astype(np.float32, copy=True)
    depth = depth01.astype(np.float32, copy=True)
    active = mask.astype(bool, copy=True)
    h, w = depth.shape
    neighbor_rows, neighbor_cols = _neighbor_indices(h, w)
    for _ in range(radius):
        new_depth = depth.copy()
        rows, cols = np.nonzero(active)
        for r, c in zip(rows, cols):
            n_r = [nr[r, c] for nr in neighbor_rows]
            n_c = [nc[r, c] for nc in neighbor_cols]
            neighbors = [
                (nr, nc)
                for nr, nc in zip(n_r, n_c)
                if active[nr, nc] and (abs(nr - r) + abs(nc - c) <= 1)
            ]
            if not neighbors:
                continue
            new_depth[r, c] = float(np.mean([depth[nr, nc] for nr, nc in neighbors]))
        depth = new_depth
    return depth


def correct_depth_vertical_bow(
    depth01: np.ndarray,
    mask: np.ndarray,
    *,
    strength: float = 0.0,
    interior_min_distance: float = 3.0,
) -> np.ndarray:
    """Flatten VDA's vertical U-bow using interior row medians.

    Extremity rows (helmet, boots) are often pushed back relative to the torso
    center even on interior pixels. Subtract a smoothed per-row offset estimated
    from deep-interior pixels only.
    """
    if strength <= 0.0:
        return depth01.astype(np.float32, copy=True)
    if interior_min_distance <= 0.0:
        raise ValueError("interior_min_distance must be positive")

    from scipy.ndimage import distance_transform_edt

    active = mask.astype(bool, copy=True)
    if not active.any():
        raise ValueError("mask has no opaque pixels")

    depth = depth01.astype(np.float32, copy=True)
    edt = distance_transform_edt(active)
    interior = active & (edt >= float(interior_min_distance))
    if not interior.any():
        raise ValueError("no interior pixels for vertical bow correction")

    height = depth.shape[0]
    row_ref = np.full(height, np.nan, dtype=np.float32)
    for row in range(height):
        row_interior = interior[row]
        if int(row_interior.sum()) < 2:
            continue
        row_ref[row] = float(np.median(depth[row, row_interior]))

    valid_rows = np.flatnonzero(~np.isnan(row_ref))
    if valid_rows.size < 2:
        return depth
    if valid_rows.size == 1:
        global_ref = float(row_ref[valid_rows[0]])
        delta = (row_ref - global_ref) * float(strength)
    else:
        global_ref = float(np.median(depth[interior]))
        missing = np.flatnonzero(np.isnan(row_ref))
        if missing.size:
            row_ref[missing] = np.interp(
                missing.astype(np.float64),
                valid_rows.astype(np.float64),
                row_ref[valid_rows].astype(np.float64),
            )
        delta = (row_ref - global_ref) * float(strength)

    for row in range(height):
        row_mask = active[row]
        if row_mask.any():
            depth[row, row_mask] -= delta[row]
    depth[~active] = 0.0
    return depth.astype(np.float32, copy=False)


def correct_depth_local_max_edges(
    depth01: np.ndarray,
    mask: np.ndarray,
    *,
    strength: float = 0.0,
    local_radius: int = 7,
    falloff_pixels: float = 3.0,
) -> np.ndarray:
    """Lift silhouette-edge depth toward a local interior maximum.

    Uses a grey-dilation (max filter) so helmet tips and boot soles inherit
    nearby torso depth instead of staying at VDA's dark fringe values.
    """
    if strength <= 0.0:
        return depth01.astype(np.float32, copy=True)
    if local_radius < 2:
        raise ValueError("local_radius must be >= 2")
    if falloff_pixels <= 0.0:
        raise ValueError("falloff_pixels must be positive")

    from scipy.ndimage import distance_transform_edt, maximum_filter

    active = mask.astype(bool, copy=True)
    if not active.any():
        raise ValueError("mask has no opaque pixels")

    depth = depth01.astype(np.float32, copy=True)
    depth_work = np.where(active, depth, 0.0).astype(np.float32, copy=False)
    size = int(local_radius) * 2 + 1
    local_max = maximum_filter(depth_work, size=size)
    edt = distance_transform_edt(active)
    weight = np.clip(1.0 - edt / float(falloff_pixels), 0.0, 1.0) * float(strength)
    corrected = depth * (1.0 - weight) + local_max * weight
    corrected[~active] = 0.0
    return corrected.astype(np.float32, copy=False)


def correct_depth_bowing(
    depth01: np.ndarray,
    mask: np.ndarray,
    *,
    vertical_strength: float = 0.65,
    edge_strength: float = 0.75,
    local_radius: int = 7,
    edge_falloff_pixels: float = 3.0,
    interior_min_distance: float = 3.0,
) -> np.ndarray:
    """Correct VDA top/bottom bowing on billboard sprites (vertical + edge)."""
    if vertical_strength <= 0.0 and edge_strength <= 0.0:
        return depth01.astype(np.float32, copy=True)
    depth = correct_depth_vertical_bow(
        depth01,
        mask,
        strength=vertical_strength,
        interior_min_distance=interior_min_distance,
    )
    depth = correct_depth_local_max_edges(
        depth,
        mask,
        strength=edge_strength,
        local_radius=local_radius,
        falloff_pixels=edge_falloff_pixels,
    )
    return depth


def _estimate_spine_col(
    mask: np.ndarray,
    *,
    body_lower_fraction: float = 0.5,
    min_row_span: int = 10,
) -> float:
    """Median column of the lower-body silhouette (torso anchor)."""
    height, width = mask.shape
    row_start = int(height * float(body_lower_fraction))
    medians: list[float] = []
    for row in range(row_start, height):
        cols = np.where(mask[row])[0]
        if cols.size >= int(min_row_span):
            medians.append(float(np.median(cols)))
    if not medians:
        return float(width) * 0.5
    return float(np.median(np.asarray(medians, dtype=np.float64)))


def correct_depth_bilateral_wing_lateral(
    depth01: np.ndarray,
    mask: np.ndarray,
    *,
    strength: float = 0.0,
    upper_row_fraction: float = 0.5,
    body_lower_fraction: float = 0.5,
) -> np.ndarray:
    """Separate left/right wing lobes in depth when the alpha blob is connected.

    Raised wings often merge into one silhouette over the head while VDA assigns
    one depth plane. Push pixels left of the torso spine nearer and right-side
    pixels farther (near=bright) so yaw views read two wings instead of one slab.
    """
    if strength <= 0.0:
        return depth01.astype(np.float32, copy=True)
    if upper_row_fraction <= 0.0 or upper_row_fraction >= 1.0:
        raise ValueError("upper_row_fraction must be in (0, 1)")
    if body_lower_fraction <= 0.0 or body_lower_fraction >= 1.0:
        raise ValueError("body_lower_fraction must be in (0, 1)")

    active = mask.astype(bool, copy=True)
    if not active.any():
        raise ValueError("mask has no opaque pixels")

    height, width = mask.shape
    spine_x = _estimate_spine_col(
        active,
        body_lower_fraction=body_lower_fraction,
    )
    upper_end = int(height * float(upper_row_fraction))
    depth = depth01.astype(np.float32, copy=True)

    for row in range(upper_end):
        row_mask = active[row]
        if not row_mask.any():
            continue
        cols = np.where(row_mask)[0]
        lateral_scale = max(float(np.max(np.abs(cols - spine_x))), 1.0)
        lateral = (np.arange(width, dtype=np.float32) - spine_x) / lateral_scale
        delta = lateral * float(strength)
        depth[row, row_mask] = np.clip(depth[row, row_mask] + delta[row_mask], 0.0, 1.0)

    depth[~active] = 0.0
    return depth.astype(np.float32, copy=False)


def correct_depth_edge_bias(
    depth01: np.ndarray,
    mask: np.ndarray,
    *,
    strength: float = 0.0,
    falloff_pixels: float = 3.0,
) -> np.ndarray:
    """Lift silhouette-edge depth toward each column's nearest (bright) value.

    Monocular depth models often push thin vertical extremities and silhouette
    boundaries farther from the camera than the interior torso. Blending edge
    pixels toward the per-column maximum preserves horizontal relief while
    reducing top/bottom bowing on billboard sprites.
    """
    if strength <= 0.0:
        return depth01.astype(np.float32, copy=True)
    if falloff_pixels <= 0.0:
        raise ValueError("falloff_pixels must be positive")

    from scipy.ndimage import distance_transform_edt

    active = mask.astype(bool, copy=True)
    if not active.any():
        raise ValueError("mask has no opaque pixels")

    depth = depth01.astype(np.float32, copy=True)
    depth_masked = np.where(active, depth, -np.inf)
    col_max = np.max(depth_masked, axis=0)
    col_max = np.where(np.any(active, axis=0), col_max, 0.0).astype(np.float32)
    col_grid = np.broadcast_to(col_max, depth.shape).copy()

    edt = distance_transform_edt(active)
    weight = np.clip(1.0 - edt / float(falloff_pixels), 0.0, 1.0) * float(strength)
    corrected = depth * (1.0 - weight) + col_grid * weight
    corrected[~active] = 0.0
    return corrected.astype(np.float32, copy=False)


def prepare_billboard_frame(
    rgba: np.ndarray,
    depth01: np.ndarray,
    *,
    gap_close_radius: int = 1,
    depth_smooth_radius: int = 1,
    depth_bow_vertical_strength: float = 0.0,
    depth_bow_edge_strength: float = 0.0,
    depth_bow_local_radius: int = 7,
    depth_bow_edge_falloff_pixels: float = 3.0,
    depth_edge_strength: float = 0.0,
    depth_edge_falloff_pixels: float = 3.0,
    depth_wing_lateral_strength: float = 0.0,
    depth_wing_lateral_upper_fraction: float = 0.5,
    depth_wing_lateral_body_lower_fraction: float = 0.5,
) -> tuple[np.ndarray, np.ndarray, dict]:
    """Close tiny occupancy holes, smooth depth, and correct VDA bowing."""
    if gap_close_radius < 0 or depth_smooth_radius < 0:
        raise ValueError("gap_close_radius and depth_smooth_radius must be >= 0")
    if depth_bow_local_radius < 2:
        raise ValueError("depth_bow_local_radius must be >= 2")
    for name, value in (
        ("depth_bow_vertical_strength", depth_bow_vertical_strength),
        ("depth_bow_edge_strength", depth_bow_edge_strength),
        ("depth_edge_strength", depth_edge_strength),
        ("depth_wing_lateral_strength", depth_wing_lateral_strength),
    ):
        if value < 0.0 or value > 1.0:
            raise ValueError(f"{name} must be in [0, 1]")
    if depth_bow_edge_falloff_pixels <= 0.0 or depth_edge_falloff_pixels <= 0.0:
        raise ValueError("bow/edge falloff pixels must be positive")
    source_mask = _opaque_mask(rgba)
    if not source_mask.any():
        raise ValueError("sprite has no opaque pixels")

    target_mask = morph_close(source_mask, gap_close_radius) if gap_close_radius > 0 else source_mask
    rgba_out, depth_out = _interpolate_gaps(rgba, depth01, source_mask, target_mask)
    if depth_smooth_radius > 0:
        depth_out = smooth_depth_box(depth_out, target_mask, depth_smooth_radius)
    if depth_bow_vertical_strength > 0.0 or depth_bow_edge_strength > 0.0:
        depth_out = correct_depth_bowing(
            depth_out,
            target_mask,
            vertical_strength=depth_bow_vertical_strength,
            edge_strength=depth_bow_edge_strength,
            local_radius=depth_bow_local_radius,
            edge_falloff_pixels=depth_bow_edge_falloff_pixels,
        )
    elif depth_edge_strength > 0.0:
        depth_out = correct_depth_edge_bias(
            depth_out,
            target_mask,
            strength=depth_edge_strength,
            falloff_pixels=depth_edge_falloff_pixels,
        )
    if depth_wing_lateral_strength > 0.0:
        depth_out = correct_depth_bilateral_wing_lateral(
            depth_out,
            source_mask,
            strength=depth_wing_lateral_strength,
            upper_row_fraction=depth_wing_lateral_upper_fraction,
            body_lower_fraction=depth_wing_lateral_body_lower_fraction,
        )

    stats = {
        "sourceOpaque": int(source_mask.sum()),
        "filledOpaque": int(target_mask.sum()),
        "gapFilled": int(target_mask.sum() - source_mask.sum()),
        "gapCloseRadius": int(gap_close_radius),
        "depthSmoothRadius": int(depth_smooth_radius),
        "depthBowVerticalStrength": float(depth_bow_vertical_strength),
        "depthBowEdgeStrength": float(depth_bow_edge_strength),
        "depthBowLocalRadius": int(depth_bow_local_radius),
        "depthBowEdgeFalloffPixels": float(depth_bow_edge_falloff_pixels),
        "depthEdgeStrength": float(depth_edge_strength),
        "depthEdgeFalloffPixels": float(depth_edge_falloff_pixels),
        "depthWingLateralStrength": float(depth_wing_lateral_strength),
        "depthWingLateralUpperFraction": float(depth_wing_lateral_upper_fraction),
        "depthWingLateralBodyLowerFraction": float(depth_wing_lateral_body_lower_fraction),
    }
    return rgba_out, depth_out, stats
