"""Shared silhouette, depth, and chroma terms for both GPU solvers.

``one_bone_depth`` thresholds occupancy, then calls these functions.
Cascade Adam uses the same arithmetic with continuous nvdiffrast alpha so
the objective has a gradient. Boolean 0/1 occupancy is unchanged.
"""
from __future__ import annotations

import math


def gpu_score_raster_resolution(
    resolution: tuple[int, int],
    *,
    chroma_weight: float,
    chroma_resolution: tuple[int, int] | None,
    chroma_scale: int,
    rgb_upsample: bool = False,
) -> tuple[int, int]:
    """Return the nvdiffrast canvas used while RGB is a decision term.

    Depth-only runs stay on the cheap proxy. Lab chroma and cascade DINOv3
    dense scoring need more pixels so they are not scored on 96×86
    nearest-neighbor blocks. The camera fit is scaled to this size. An
    explicit chroma_resolution must be the same integer scale on width and
    height and cannot be smaller than the proxy.
    """
    proxy_width, proxy_height = (int(resolution[0]), int(resolution[1]))
    if proxy_width < 16 or proxy_height < 16:
        raise ValueError("resolution must be at least 16x16")
    if float(chroma_weight) <= 0.0 and not bool(rgb_upsample):
        return (proxy_width, proxy_height)
    if chroma_resolution is not None:
        width, height = (int(chroma_resolution[0]), int(chroma_resolution[1]))
        if width < 16 or height < 16:
            raise ValueError("chroma_resolution must be at least 16x16")
        if width < proxy_width or height < proxy_height:
            raise ValueError("chroma_resolution cannot be smaller than the proxy resolution")
        if width % proxy_width != 0 or height % proxy_height != 0:
            raise ValueError("chroma_resolution must be an integer multiple of the proxy resolution")
        if width // proxy_width != height // proxy_height:
            raise ValueError("chroma_resolution must use the same integer scale on width and height")
        return (width, height)
    scale = int(chroma_scale)
    if scale < 2:
        raise ValueError(
            "chroma_scale must be at least 2 when RGB upsample is required "
            "(chroma_weight or rgb_upsample) and chroma_resolution is None"
        )
    return (proxy_width * scale, proxy_height * scale)


def compose_geometry_score(
    *,
    silhouette_iou,
    depth_quality,
    chroma_quality_value,
    depth_weight: float,
    silhouette_weight: float,
    chroma_weight: float,
    motion_quality=None,
    motion_weight: float = 0.0,
):
    """Blend occupancy IoU, Huber depth, Lab a,b, and optional occupancy motion.

    ``motion_weight`` 0 keeps the old three-term mix. Collision is subtracted
    after this blend, not mixed into the weights.
    """
    motion_w = float(motion_weight)
    if not math.isfinite(motion_w) or motion_w < 0.0:
        raise ValueError("motion_weight must be finite and non-negative")
    if motion_w > 0.0 and motion_quality is None:
        raise ValueError("motion_weight is set but motion_quality is missing")
    weight_total = max(
        float(depth_weight)
        + float(silhouette_weight)
        + float(chroma_weight)
        + motion_w,
        1e-6,
    )
    mix = (
        float(depth_weight) * depth_quality
        + float(silhouette_weight) * silhouette_iou
        + float(chroma_weight) * chroma_quality_value
    )
    if motion_w > 0.0:
        mix = mix + motion_w * motion_quality
    return mix / weight_total


def collision_error_above_slack(collision_error, slack: float):
    """Charge only extra collision past ``slack``. Legal 2D overlap is not a pretzel.

    ``slack`` 0 keeps the old full penalty. Negative slack is a config error.
    """
    import torch

    extra = float(slack)
    if not math.isfinite(extra) or extra < 0.0:
        raise ValueError("collision slack must be finite and non-negative")
    if extra == 0.0:
        return collision_error
    return torch.clamp(collision_error - extra, min=0.0)


def silhouette_and_depth_quality(
    *,
    target_foreground,
    predicted_foreground,
    target_depth,
    predicted_depth,
    depth_tolerance: float,
    depth_robust_delta: float,
    occupancy_ignore=None,
):
    """Return IoU plus depth quality on every target-occupied pixel.

    Empty raster depth is 0, and far surfaces also encode near 0. Measuring
    ``|predicted - target|`` on the union, or on misses, therefore treats a
    skipped back foot as a match whenever that residual sits inside
    ``depth_tolerance``. Occupancy of those pixels belongs to silhouette IoU
    and to the depth term: uncovered target pixels are a full miss (error 1),
    not “close to empty.” Overlap uses the ordinary residual. Extra predicted
    blobs stay out of the depth mean; IoU already penalizes them.

    Occupancy may be boolean or float in ``[0, 1]``. Boolean 0/1 is the
    discrete solver. Continuous alpha is the cascade gradient path. Arithmetic
    matches at 0 and 1.

    ``occupancy_ignore`` drops target-occupied pixels from IoU only (two bones
    both own the pixel). Depth still uses every target pixel. Extra predicted
    blobs on empty sprite pixels still enter the union. Occupancy abstains
    (IoU 1) when the remaining union is empty.
    """
    import torch

    target = target_foreground.to(dtype=torch.float32)
    predicted = predicted_foreground.to(dtype=torch.float32)
    if occupancy_ignore is None:
        target_iou = target
        predicted_iou = predicted
    else:
        ignore = occupancy_ignore.to(dtype=torch.float32)
        if ignore.shape != target.shape:
            if ignore.ndim == target.ndim - 1 and target.shape[0] == 1:
                ignore = ignore.unsqueeze(0)
            if ignore.shape != target.shape:
                raise ValueError(
                    "occupancy_ignore must match target occupancy shape: "
                    f"ignore={tuple(ignore.shape)} target={tuple(target.shape)}"
                )
        ignore = ignore * target
        target_iou = target * (1.0 - ignore)
        predicted_iou = predicted * (1.0 - ignore)
    both = target_iou * predicted_iou
    union = target_iou + predicted_iou - both
    union_count_raw = union.sum(dim=(-2, -1))
    union_count = union_count_raw.clamp_min(1.0)
    intersection = both.sum(dim=(-2, -1))
    target_count = target.sum(dim=(-2, -1))
    silhouette_iou = intersection / union_count
    silhouette_iou = torch.where(
        union_count_raw > 0.0,
        silhouette_iou,
        torch.ones_like(silhouette_iou),
    )
    missed = target * (1.0 - predicted)
    both_depth = target * predicted
    residual = (predicted_depth - target_depth).abs()
    pixel_depth_error = missed + both_depth * residual
    target_denom = target_count.clamp_min(1.0)
    absolute_depth_error = pixel_depth_error.sum(dim=(-2, -1)) / target_denom
    absolute_depth_error = torch.where(
        target_count > 0.0, absolute_depth_error, torch.ones_like(absolute_depth_error)
    )
    tolerance = float(depth_tolerance)
    pixel_excess = torch.clamp(pixel_depth_error - tolerance, min=0.0)
    delta = float(depth_robust_delta)
    quadratic = 0.5 * pixel_excess.square() / delta
    linear = pixel_excess - 0.5 * delta
    robust_pixel_error = torch.where(pixel_excess <= delta, quadratic, linear) * target
    robust_depth_error = robust_pixel_error.sum(dim=(-2, -1)) / target_denom
    max_excess = max(1.0 - tolerance, 1e-6)
    max_robust = (
        0.5 * max_excess * max_excess / delta
        if max_excess <= delta
        else max_excess - 0.5 * delta
    )
    # Do not clamp at 1. A hard cap makes quality 0 with a zero derivative,
    # so Adam cannot leave a totally-wrong bind pose. Discrete argmax still
    # prefers the smaller error.
    robust_depth_error = robust_depth_error / max(max_robust, 1e-6)
    depth_quality = 1.0 - robust_depth_error
    depth_quality = torch.where(target_count > 0.0, depth_quality, torch.zeros_like(depth_quality))
    return {
        "silhouetteIoU": silhouette_iou,
        "depthQuality": depth_quality,
        "depthError": absolute_depth_error,
        "depthRobustError": robust_depth_error,
        "pixelDepthError": pixel_depth_error,
        "intersectionCount": intersection,
        "unionCount": union_count,
        "targetCount": target_count,
    }


def srgb_rgb_to_lab_ab(rgb):
    """Convert sRGB in [0, 1] to CIE Lab a,b. Lightness is discarded.

    HoMM3 sprites and unlit Meshy albedo disagree on brightness. Skin vs
    cloth vs a turned-away back still differ in a and b.
    """
    import torch

    color = rgb.clamp(0.0, 1.0)
    linear = torch.where(
        color <= 0.04045,
        color / 12.92,
        ((color + 0.055) / 1.055) ** 2.4,
    )
    red, green, blue = linear[..., 0], linear[..., 1], linear[..., 2]
    x = red * 0.4124564 + green * 0.3575761 + blue * 0.1804375
    y = red * 0.2126729 + green * 0.7151522 + blue * 0.0721750
    z = red * 0.0193339 + green * 0.1191920 + blue * 0.9503041
    x = x / 0.95047
    z = z / 1.08883
    epsilon = 216.0 / 24389.0
    kappa = 24389.0 / 27.0

    def _lab_f(value):
        # Cube-root derivative is infinite at 0. Evaluate that branch only
        # on x >= epsilon so torch.where cannot leak a NaN gradient from the
        # unused arm when a pixel is sRGB black.
        cubic = torch.pow(value.clamp_min(epsilon), 1.0 / 3.0)
        linear = (kappa * value + 16.0) / 116.0
        return torch.where(value > epsilon, cubic, linear)

    fx, fy, fz = _lab_f(x), _lab_f(y), _lab_f(z)
    return torch.stack((500.0 * (fx - fy), 200.0 * (fy - fz)), dim=-1)


def chroma_quality(
    *,
    target_foreground,
    predicted_foreground,
    target_ab,
    predicted_ab,
    chroma_tolerance: float,
    chroma_robust_delta: float,
    chroma_error_scale: float,
):
    """Return chroma quality on every target-occupied pixel.

    Uncovered target pixels are a full miss. Overlap uses CIE Lab a,b
    Euclidean distance, scaled then Huber-smoothed like depth. Extra
    predicted blobs stay out of the chroma mean; IoU already penalizes them.
    Occupancy may be boolean or float in ``[0, 1]``; 0/1 matches the
    discrete solver.
    """
    import torch

    target = target_foreground.to(dtype=torch.float32)
    predicted = predicted_foreground.to(dtype=torch.float32)
    both = target * predicted
    missed = target * (1.0 - predicted)
    target_count = target.sum(dim=(-2, -1))
    pixel_chroma_dist = torch.linalg.vector_norm(predicted_ab - target_ab, dim=-1)
    pixel_chroma_error = pixel_chroma_dist / float(chroma_error_scale)
    pixel_chroma_error = missed + both * pixel_chroma_error
    target_denom = target_count.clamp_min(1.0)
    absolute_chroma_error = pixel_chroma_error.sum(dim=(-2, -1)) / target_denom
    absolute_chroma_error = torch.where(
        target_count > 0.0, absolute_chroma_error, torch.ones_like(absolute_chroma_error)
    )
    tolerance = float(chroma_tolerance)
    pixel_excess = torch.clamp(pixel_chroma_error - tolerance, min=0.0)
    delta = float(chroma_robust_delta)
    quadratic = 0.5 * pixel_excess.square() / delta
    linear = pixel_excess - 0.5 * delta
    robust_pixel_error = torch.where(pixel_excess <= delta, quadratic, linear) * target
    robust_chroma_error = robust_pixel_error.sum(dim=(-2, -1)) / target_denom
    max_excess = max(1.0 - tolerance, 1e-6)
    max_robust = (
        0.5 * max_excess * max_excess / delta
        if max_excess <= delta
        else max_excess - 0.5 * delta
    )
    robust_chroma_error = robust_chroma_error / max(max_robust, 1e-6)
    chroma_quality_value = 1.0 - robust_chroma_error
    chroma_quality_value = torch.where(
        target_count > 0.0, chroma_quality_value, torch.zeros_like(chroma_quality_value)
    )
    return {
        "chromaQuality": chroma_quality_value,
        "chromaError": absolute_chroma_error,
        "chromaRobustError": robust_chroma_error,
        "pixelChromaError": pixel_chroma_error,
        "overlapCount": both.sum(dim=(-2, -1)),
    }


def unique_occupancy_quality(*, target_foreground, predicted_foreground):
    """Score occupancy this sprite has that the clip-majority sprite does not.

    The common occupancy is the lower-median of the *targets*, not of the
    current uncover maps. A frame's unique error then depends only on that
    frame's prediction, so mixing 0° and 45° across frames does not rewrite
    the other frames' unique scores. Shared rest holes are not in this
    remainder; covering them is root/absolute occupancy, not joint keep.
    """
    import torch

    target = target_foreground.to(dtype=torch.float32)
    predicted = predicted_foreground.to(dtype=torch.float32).clamp(0.0, 1.0)
    if target.ndim != 3 or predicted.ndim != 3:
        raise ValueError("unique_occupancy_quality needs [frames, height, width]")
    if int(target.shape[0]) < 2:
        raise ValueError("unique_occupancy_quality needs at least two frames")
    common_target = target.quantile(0.5, dim=0, interpolation="lower")
    unique_target = (target - common_target).clamp_min(0.0)
    unique_absent = (common_target - target).clamp_min(0.0)
    unique_uncovered = unique_target * (1.0 - predicted)
    unique_leftover = unique_absent * predicted
    unique_mass = (unique_target + unique_absent).sum(dim=(-2, -1))
    unique_error = (unique_uncovered + unique_leftover).sum(dim=(-2, -1)) / unique_mass.clamp_min(1.0)
    unique_error = torch.where(unique_mass > 0.0, unique_error, torch.zeros_like(unique_error))
    return {
        "uniqueOccupancyQuality": 1.0 - unique_error,
        "uniqueOccupancyError": unique_error,
        "uniqueUncoveredCount": unique_uncovered.sum(dim=(-2, -1)),
        "uniqueExtraCount": unique_leftover.sum(dim=(-2, -1)),
        "uniqueMass": unique_mass,
    }


def occupancy_motion_quality(
    *,
    target_foreground,
    predicted_foreground,
    clip_frames: int | None = None,
):
    """Score frame-to-frame occupancy change, not static fill.

    Each consecutive pair has a sprite appear map, a sprite disappear map,
    and the same two maps for the prediction. Quality is one minus the L1
    mismatch of those maps, divided by the combined change mass. A still
    pair (no change on either side) scores 1. Opposite-direction motion on
    the same pixels is a miss; union-of-changed-pixels IoU would score it
    as a hit.

    Packed hypotheses are ``n_hyp * clip_frames`` rows in clip order.
    Frame 0 copies the first pair so the opening pose can move keep.
    """
    import torch

    target = target_foreground.to(dtype=torch.float32)
    predicted = predicted_foreground.to(dtype=torch.float32).clamp(0.0, 1.0)
    if target.ndim != 3 or predicted.ndim != 3:
        raise ValueError("occupancy_motion_quality needs [batch, height, width]")
    if tuple(target.shape) != tuple(predicted.shape):
        raise ValueError(
            "occupancy_motion_quality target/predicted shape mismatch: "
            f"{tuple(target.shape)} vs {tuple(predicted.shape)}"
        )
    batch, height, width = (int(target.shape[0]), int(target.shape[1]), int(target.shape[2]))
    frames = int(batch if clip_frames is None else clip_frames)
    if frames < 2:
        raise ValueError("occupancy_motion_quality needs at least two frames")
    if batch % frames != 0:
        raise ValueError(
            "occupancy_motion_quality batch must be a multiple of clip_frames: "
            f"batch={batch} clip_frames={frames}"
        )
    n_hyp = batch // frames
    tgt = target.view(n_hyp, frames, height, width)
    pred = predicted.view(n_hyp, frames, height, width)
    tgt_appear = (tgt[:, 1:] - tgt[:, :-1]).clamp_min(0.0)
    tgt_disappear = (tgt[:, :-1] - tgt[:, 1:]).clamp_min(0.0)
    pred_appear = (pred[:, 1:] - pred[:, :-1]).clamp_min(0.0)
    pred_disappear = (pred[:, :-1] - pred[:, 1:]).clamp_min(0.0)
    mismatch = (pred_appear - tgt_appear).abs() + (pred_disappear - tgt_disappear).abs()
    mass = tgt_appear + tgt_disappear + pred_appear + pred_disappear
    mass_sum = mass.sum(dim=(-2, -1))
    pair_error = mismatch.sum(dim=(-2, -1)) / mass_sum.clamp_min(1.0)
    pair_error = torch.where(mass_sum > 0.0, pair_error, torch.zeros_like(pair_error))
    pair_quality = (1.0 - pair_error).clamp(0.0, 1.0)
    quality = torch.empty(
        (n_hyp, frames),
        dtype=target.dtype,
        device=target.device,
    )
    quality[:, 1:] = pair_quality
    quality[:, 0] = pair_quality[:, 0]
    flat = quality.reshape(batch)
    return {
        "motionQuality": flat,
        "motionError": 1.0 - flat,
        "motionPairQuality": pair_quality,
    }


def unique_geometry_quality(
    *,
    target_foreground,
    predicted_foreground,
    pixel_chroma_error,
    silhouette_weight: float,
    chroma_weight: float,
    target_ab=None,
):
    """Clip-unique occupancy plus clip-unique chroma. Depth stays out.

    Occupancy unique only sees limbs that stick out of the rest blob. A
    humanoid walk often stays inside that blob, so occupancy unique is
    already ~0 while Lab paint on the overlapping pixels still moves.
    Unique chroma is mesh Lab error weighted by how this sprite's Lab
    differs from the clip lower-median *target* Lab. Shared rest paint
    has weight 0. Estimated depth stays out of this remainder term.
    Joint keep uses absolute geometry gain (which includes depth) plus a
    weighted unique gain; this function is not the keep itself.
    """
    import torch

    occupancy = unique_occupancy_quality(
        target_foreground=target_foreground,
        predicted_foreground=predicted_foreground,
    )
    unique_occupancy_quality_value = occupancy["uniqueOccupancyQuality"]
    unique_occupancy_error = occupancy["uniqueOccupancyError"]
    zeros = torch.zeros_like(unique_occupancy_error)
    sil_weight = float(silhouette_weight)
    chroma_w = float(chroma_weight)
    if chroma_w > 0.0:
        if pixel_chroma_error is None:
            raise ValueError("chroma_weight is set but pixel_chroma_error is missing")
        if target_ab is None:
            raise ValueError("chroma_weight is set but target_ab is missing")
        chroma_maps = pixel_chroma_error.to(dtype=torch.float32)
        target = target_foreground.to(dtype=torch.float32)
        ab = target_ab.to(dtype=torch.float32)
        if tuple(chroma_maps.shape) != tuple(target.shape):
            raise ValueError(
                "pixel_chroma_error must match target occupancy "
                f"{tuple(target.shape)}, not {tuple(chroma_maps.shape)}"
            )
        if tuple(ab.shape[:3]) != tuple(target.shape):
            raise ValueError(
                "target_ab must match target occupancy "
                f"{tuple(target.shape)} plus 2 Lab channels, not {tuple(ab.shape)}"
            )
        common_ab = ab.quantile(0.5, dim=0, interpolation="lower")
        unique_color_weight = target * torch.linalg.vector_norm(ab - common_ab, dim=-1)
        unique_color_mass = unique_color_weight.sum(dim=(-2, -1))
        unique_chroma_error = (chroma_maps * unique_color_weight).sum(dim=(-2, -1)) / unique_color_mass.clamp_min(1.0)
        unique_chroma_error = torch.where(
            unique_color_mass > 0.0,
            unique_chroma_error,
            torch.zeros_like(unique_chroma_error),
        )
        unique_chroma_quality = 1.0 - unique_chroma_error
    else:
        unique_chroma_error = zeros
        unique_chroma_quality = unique_occupancy_quality_value
    if sil_weight <= 0.0 and chroma_w <= 0.0:
        unique_quality = unique_occupancy_quality_value
    else:
        unique_quality = compose_geometry_score(
            silhouette_iou=unique_occupancy_quality_value,
            depth_quality=unique_occupancy_quality_value,
            chroma_quality_value=unique_chroma_quality,
            depth_weight=0.0,
            silhouette_weight=max(sil_weight, 0.0),
            chroma_weight=max(chroma_w, 0.0),
        )
    return {
        "uniqueGeometryQuality": unique_quality,
        "uniqueGeometryError": 1.0 - unique_quality,
        "uniqueOccupancyQuality": unique_occupancy_quality_value,
        "uniqueOccupancyError": unique_occupancy_error,
        "uniqueChromaQuality": unique_chroma_quality,
        "uniqueChromaError": unique_chroma_error,
        "uniqueUncoveredCount": occupancy["uniqueUncoveredCount"],
        "uniqueExtraCount": occupancy["uniqueExtraCount"],
    }
