"""Authentic DEF-frame preparation for the V2 solver."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from .contracts import CameraSpec, PreparedClip, V2Config, fingerprint_paths


def _frame_number(path: Path) -> int:
    match = re.search(r"(?:frame[_-]?)?(\d+)(?:\D*)$", path.stem.lower())
    return int(match.group(1)) if match else 10**9


def _source_files(source_dir: Path) -> list[Path]:
    lowered = str(source_dir).lower().replace("\\", "/")
    if any(token in lowered for token in ("rife", "interpolat", "upscale")):
        raise ValueError(f"V2 refuses interpolated target directories: {source_dir}")
    paths = [path for path in source_dir.glob("*.png") if path.is_file() and "shadow_cull_report" not in path.name]
    paths.sort(key=lambda path: (_frame_number(path), path.name.lower()))
    if not paths:
        raise FileNotFoundError(f"no PNG frames found under authentic DEF source directory: {source_dir}")
    return paths


def _resize_rgba(path: Path, camera: CameraSpec, alpha_threshold: int) -> tuple[np.ndarray, np.ndarray]:
    with Image.open(path) as image:
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    # The cull function is deliberately called for every frame in memory. It
    # is part of the target contract even when a particular source frame has
    # no detectable shadow pixels.
    from def_soft_shadow import cull_def_soft_shadow_rgba

    culled, _ = cull_def_soft_shadow_rgba(rgba.copy())
    resized = Image.fromarray(culled, mode="RGBA").resize((camera.width, camera.height), Image.Resampling.LANCZOS)
    result = np.asarray(resized, dtype=np.float32) / 255.0
    mask = (result[..., 3] * 255.0 >= int(alpha_threshold)).astype(np.float32)
    return result[..., :3], mask


def _front_perspective_frame_name(group_index: int | None, source_stem: str) -> str | None:
    """Convert a source frame stem to the generated group/frame filename."""

    if group_index is None:
        return None
    match = re.fullmatch(r"(?:frame[_-]?)?(\d+)", str(source_stem), re.IGNORECASE)
    if not match:
        return None
    return f"{int(group_index):02d}_{int(match.group(1)):02d}_front.png"


def resolve_front_perspective_paths(
    selection: dict[str, Any] | None,
    source_files: list[Path],
) -> list[Path]:
    """Resolve generated front references by authentic DEF frame stem.

    The source-frame picker materializes normalized ``00.png`` names for the
    notebook, so the normalized names are not sufficient to find the matching
    generated view.  The picker therefore passes the original DEF paths and
    unit SID through the selection contract.  For materialized source frames,
    both ``00.png`` and ``frame_00.png`` resolve to the generated
    ``{group}_{frame}_front.png`` asset.  An explicit path list remains
    supported for custom pipelines.
    """
    value = dict(selection or {})
    explicit = value.get("front_perspective_paths") or value.get("frontViewPaths")
    if explicit is not None:
        paths = [Path(item).resolve() for item in explicit]
        if len(paths) != len(source_files):
            raise ValueError(
                "front_perspective_paths must contain one image per prepared DEF frame"
            )
        return paths
    directory = value.get("front_perspective_dir") or value.get("frontViewDir")
    root = value.get("front_perspective_root") or value.get("frontViewRoot")
    unit_sid = str(value.get("unit_sid") or value.get("unitSid") or "").strip()
    original = value.get("source_frame_paths") or value.get("sourceFramePaths")
    original_paths = [Path(item) for item in original] if original else []
    if directory:
        directory = Path(directory).resolve()
        paths = [directory / f"{path.stem}_front.png" for path in source_files]
    elif root and unit_sid and len(original_paths) == len(source_files):
        root = Path(root).resolve()
        unit_root = root / unit_sid
        # Generic choices retain their original ``.dir`` parent.  The Roc
        # pilot is a pre-materialized choice whose source files are renamed
        # to 00.png, 01.png, ...; recover its group from the animation name
        # and then locate the matching DEF stem under the unit's front asset.
        paths = []
        group_match = re.search(r"(?:^|_)g(\d+)(?:$|_)", str(value.get("animation_name") or value.get("animationName") or ""), re.IGNORECASE)
        group_index = int(group_match.group(1)) if group_match else None
        for index, source in enumerate(original_paths):
            direct = unit_root / source.parent.name / f"{source.stem}_front.png"
            if direct.is_file():
                paths.append(direct)
                continue
            stem = source.stem
            group_prefix = _front_perspective_frame_name(group_index, stem)
            if group_prefix is not None:
                matches = list(unit_root.glob(f"*/{group_prefix}"))
            else:
                matches = list(unit_root.glob(f"*/{stem}_front.png"))
            paths.append(matches[0] if len(matches) == 1 else direct)
    else:
        return []
    return [path.resolve() for path in paths]


def canonicalize_front_rgb_mask(
    rgb: np.ndarray,
    mask: np.ndarray,
    camera: CameraSpec,
    subject_extent: float,
    subject_padding: float,
    *,
    source_label: str = "front reference",
) -> tuple[np.ndarray, np.ndarray]:
    """Center and fit a front-view RGB/mask pair to one subject extent.

    Generated views are not a calibrated camera sequence.  The foreground
    bbox is therefore fitted to one common extent before it becomes a target;
    otherwise the optimizer would incorrectly explain a larger AI crop with
    character translation or joint extension.
    """
    rgb = np.asarray(rgb, dtype=np.float32).clip(0.0, 1.0)
    foreground = (np.asarray(mask, dtype=np.float32) > 0.5).astype(np.uint8) * 255
    ys, xs = np.where(foreground > 0)
    if len(xs) == 0:
        raise ValueError(f"front reference has no foreground after thresholding: {source_label}")
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    width = max(x1 - x0, 1)
    height = max(y1 - y0, 1)
    pad_x = int(round(width * float(subject_padding)))
    pad_y = int(round(height * float(subject_padding)))
    x0 = max(0, x0 - pad_x)
    x1 = min(rgb.shape[1], x1 + pad_x)
    y0 = max(0, y0 - pad_y)
    y1 = min(rgb.shape[0], y1 + pad_y)
    crop_rgb = Image.fromarray((rgb[y0:y1, x0:x1] * 255.0).astype(np.uint8), mode="RGB")
    crop_mask = Image.fromarray(foreground[y0:y1, x0:x1], mode="L")
    extent_px = min(camera.width, camera.height) * float(subject_extent)
    scale = min(extent_px / max(x1 - x0, 1), extent_px / max(y1 - y0, 1))
    scaled_size = (
        max(1, int(round((x1 - x0) * scale))),
        max(1, int(round((y1 - y0) * scale))),
    )
    resized_rgb = crop_rgb.resize(scaled_size, Image.Resampling.LANCZOS)
    resized_mask = crop_mask.resize(scaled_size, Image.Resampling.NEAREST)
    fitted_rgb = Image.new("RGB", (camera.width, camera.height), (0, 0, 0))
    fitted_mask = Image.new("L", (camera.width, camera.height), 0)
    paste_at = (
        (camera.width - scaled_size[0]) // 2,
        (camera.height - scaled_size[1]) // 2,
    )
    fitted_rgb.paste(resized_rgb, paste_at)
    fitted_mask.paste(resized_mask, paste_at)
    return (
        np.asarray(fitted_rgb, dtype=np.float32) / 255.0,
        (np.asarray(fitted_mask, dtype=np.float32) >= 127.0).astype(np.float32),
    )


def _resize_front_rgb_mask(
    path: Path,
    camera: CameraSpec,
    background_threshold: int,
    subject_extent: float,
    subject_padding: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Read generated front art and derive a lighting-independent subject mask.

    Most of the generated library is RGB-on-black, but accepting an alpha
    channel here makes the contract work for future transparent exports too.
    The image is normalized once at ingestion; candidate renders are not
    independently resized during scoring.
    """
    with Image.open(path) as image:
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    rgb = rgba[..., :3]
    # The generated library is RGB-on-black, not RGBA.  Use the brightest
    # channel as a conservative foreground test; no render lighting enters the
    # mask objective.  If a future asset has meaningful alpha, prefer it.
    alpha = rgba[..., 3]
    if int(alpha.max()) > 0 and int(alpha.min()) < 255:
        foreground = (alpha >= int(background_threshold)).astype(np.float32)
    else:
        foreground = (rgb.max(axis=-1) >= int(background_threshold)).astype(np.float32)
    return canonicalize_front_rgb_mask(
        rgb,
        foreground,
        camera,
        subject_extent,
        subject_padding,
        source_label=str(path),
    )


def _edge(mask: np.ndarray) -> np.ndarray:
    try:
        from scipy.ndimage import sobel

        dx = sobel(mask, axis=-1, mode="constant")
        dy = sobel(mask, axis=-2, mode="constant")
        value = np.sqrt(dx * dx + dy * dy)
    except Exception:
        dx = np.diff(mask, axis=-1, prepend=mask[..., :1, :])
        dy = np.diff(mask, axis=-2, prepend=mask[..., :1, :])
        value = np.sqrt(dx * dx + dy * dy)
    return np.clip(value, 0.0, 1.0).astype(np.float32)


def _sdf(mask: np.ndarray) -> np.ndarray:
    try:
        from scipy.ndimage import distance_transform_edt

        inside = distance_transform_edt(mask > 0.5)
        outside = distance_transform_edt(mask <= 0.5)
        return (outside - inside).astype(np.float32)
    except Exception:
        return np.zeros_like(mask, dtype=np.float32)


def _auto_feature_points(mask: np.ndarray, edge: np.ndarray) -> np.ndarray:
    """Discover salient, unnamed silhouette features without a human list.

    The detector intentionally returns a variable number of points.  It uses
    the strongest separated boundary responses, not a fixed anatomy taxonomy;
    this makes it applicable to humanoids, animals, props, and custom units.
    Each row is ``x_norm, y_norm, confidence``.
    """
    ys, xs = np.where((mask > 0.5) & (edge > 0.05))
    if len(xs) < 4:
        return np.zeros((0, 3), dtype=np.float32)
    height, width = mask.shape
    perimeter = max(float(len(xs)), 1.0)
    desired = int(np.clip(round(perimeter / 18.0), 4, 32))
    score = edge[ys, xs].astype(np.float64)
    # Prefer boundary extrema as well as high local contrast. This is still a
    # data-driven point set; no creature-specific bone or feature names enter.
    center = np.asarray(((width - 1) * 0.5, (height - 1) * 0.5), dtype=np.float64)
    distance = np.linalg.norm(np.stack((xs, ys), axis=1) - center[None, :], axis=1)
    score = score + 0.15 * distance / max(float(max(width, height)), 1.0)
    order = np.argsort(-score)
    min_separation = max(2.0, 0.035 * float(min(width, height)))
    selected: list[int] = []
    for candidate in order.tolist():
        point = np.asarray((xs[candidate], ys[candidate]), dtype=np.float64)
        if any(float(np.linalg.norm(point - np.asarray((xs[index], ys[index])))) < min_separation for index in selected):
            continue
        selected.append(int(candidate))
        if len(selected) >= desired:
            break
    if not selected:
        return np.zeros((0, 3), dtype=np.float32)
    values = np.asarray(
        [
            (
                xs[index] / max(width - 1, 1),
                ys[index] / max(height - 1, 1),
                float(np.clip(score[index], 0.0, 1.0)),
            )
            for index in selected
        ],
        dtype=np.float32,
    )
    return values


def _load_depth(source_dir: Path | None, frame_paths: list[Path], camera: CameraSpec) -> tuple[np.ndarray | None, np.ndarray | None]:
    if source_dir is None:
        return None, None
    directory = Path(source_dir)
    lowered = str(directory).lower().replace("\\", "/")
    if any(token in lowered for token in ("rife", "interpolat", "upscale")):
        raise ValueError(f"V2 refuses interpolated target depth directories: {directory}")
    if not directory.is_dir():
        raise FileNotFoundError(f"configured target depth directory is missing: {directory}")
    result: list[np.ndarray] = []
    confidence: list[np.ndarray] = []
    for frame in frame_paths:
        candidates = [directory / frame.name, directory / f"{_frame_number(frame):02d}.png", directory / f"frame_{_frame_number(frame):02d}.png"]
        path = next((candidate for candidate in candidates if candidate.is_file()), None)
        if path is None:
            raise FileNotFoundError(f"target depth is missing for {frame.name} under {directory}")
        with Image.open(path) as image:
            raw = np.asarray(image.convert("I"), dtype=np.float32)
        if raw.max(initial=0.0) > 1.0:
            raw = raw / max(float(raw.max()), 1.0)
        resized = np.asarray(Image.fromarray(raw).resize((camera.width, camera.height), Image.Resampling.BILINEAR), dtype=np.float32)
        result.append(np.clip(resized, 0.0, 1.0))
        confidence.append((resized > 0.0).astype(np.float32))
    return np.stack(result), np.stack(confidence)


def _metadata_durations(source_dir: Path, frame_paths: list[Path], source_fps: float) -> tuple[float, ...] | None:
    """Read optional native DEF timing without treating it as an image source.

    VCMI exports used by the picker may carry a small timing sidecar.  The
    image directory remains authoritative for frame identity; this helper only
    preserves per-frame display durations when that sidecar exists.
    """
    candidates = (source_dir / "frame_durations.json", source_dir / "timing.json", source_dir / "metadata.json")
    metadata = next((path for path in candidates if path.is_file()), None)
    if metadata is None:
        return None
    import json

    value = json.loads(metadata.read_text(encoding="utf-8"))
    raw = value
    unit = "seconds"
    if isinstance(value, dict):
        raw = value.get("frameDurations", value.get("durations", value.get("frameDurationMs")))
        if "frameDurationMs" in value and raw is value["frameDurationMs"]:
            unit = "milliseconds"
        if raw is None and value.get("fps"):
            raw = [1.0 / float(value["fps"])] * len(frame_paths)
    if isinstance(raw, (int, float)):
        raw = [raw] * len(frame_paths)
    if not isinstance(raw, (list, tuple)) or len(raw) != len(frame_paths):
        return None
    durations = tuple(float(item) for item in raw)
    if unit == "milliseconds":
        durations = tuple(item / 1000.0 for item in durations)
    if any(item <= 0.0 for item in durations):
        raise ValueError(f"native timing sidecar contains non-positive durations: {metadata}")
    return durations


def prepare_clip(
    source_dir: str | Path,
    *,
    camera: CameraSpec,
    config: V2Config,
    frame_indices: tuple[int, ...] | None = None,
    depth_dir: str | Path | None = None,
    front_perspective_paths: list[Path] | tuple[Path, ...] | None = None,
    front_camera: CameraSpec | None = None,
    source_fps: float = 12.0,
    frame_durations: tuple[float, ...] | None = None,
) -> PreparedClip:
    """Load only source DEF frames and cull alpha shadows before scoring."""
    config.validate()
    source = Path(source_dir).resolve()
    if not source.is_dir():
        raise FileNotFoundError(f"authentic DEF source directory is missing: {source}")
    files = _source_files(source)
    if frame_indices is not None:
        wanted = tuple(int(value) for value in frame_indices)
        by_number = {_frame_number(path): path for path in files}
        missing = [value for value in wanted if value not in by_number]
        if missing:
            raise FileNotFoundError(f"requested DEF frames are missing: {missing}")
        files = [by_number[value] for value in wanted]
        indices = wanted
    else:
        indices = tuple(_frame_number(path) for path in files)
    if frame_durations is None:
        durations = _metadata_durations(source, files, source_fps)
        if durations is None:
            durations = tuple(1.0 / float(source_fps) for _ in files)
    else:
        durations = tuple(float(value) for value in frame_durations)
        if len(durations) != len(files) or any(value <= 0.0 for value in durations):
            raise ValueError("frame_durations must contain one positive duration per prepared frame")
    rgbs: list[np.ndarray] = []
    masks: list[np.ndarray] = []
    for path in files:
        rgb, mask = _resize_rgba(path, camera, config.alpha_threshold)
        rgbs.append(rgb)
        masks.append(mask)
    mask_array = np.stack(masks).astype(np.float32)
    depth, depth_confidence = _load_depth(Path(depth_dir) if depth_dir else None, files, camera)
    edge_array = _edge(mask_array)
    front_paths = tuple(Path(path).resolve() for path in (front_perspective_paths or ()))
    front_rgb: np.ndarray | None = None
    front_masks: np.ndarray | None = None
    front_edge: np.ndarray | None = None
    front_sdf: np.ndarray | None = None
    front_feature_points: tuple[np.ndarray, ...] = ()
    front_fingerprint: str | None = None
    front_provenance: dict[str, Any] | None = None
    if front_paths:
        if front_camera is None:
            raise ValueError("front_camera is required when front perspective paths are supplied")
        missing = [str(path) for path in front_paths if not path.is_file()]
        if missing:
            raise FileNotFoundError(
                "generated front-perspective reference(s) are missing: " + ", ".join(missing[:8])
                + (" ..." if len(missing) > 8 else "")
            )
        front_rgbs: list[np.ndarray] = []
        front_masks_list: list[np.ndarray] = []
        for path in front_paths:
            rgb, mask = _resize_front_rgb_mask(
                path,
                front_camera,
                config.front_view_background_threshold,
                config.front_view_subject_extent,
                config.front_view_subject_padding,
            )
            front_rgbs.append(rgb)
            front_masks_list.append(mask)
        front_rgb = np.stack(front_rgbs).astype(np.float32)
        front_masks = np.stack(front_masks_list).astype(np.float32)
        front_edge = _edge(front_masks)
        front_sdf = _sdf(front_masks)
        front_feature_points = tuple(
            _auto_feature_points(front_masks[index], front_edge[index])
            for index in range(len(front_paths))
        )
        front_fingerprint = fingerprint_paths(
            list(front_paths),
            extra=(
                f"background_threshold={config.front_view_background_threshold};"
                f"resolution={front_camera.width}x{front_camera.height};"
                f"subject_extent={config.front_view_subject_extent};"
                f"subject_padding={config.front_view_subject_padding}"
            ),
        )
        front_provenance = {
            "enabled": True,
            "source": "artifacts/sprite_profile_to_front/out",
            "format": "generated RGB-on-black front perspective",
            "mask": "max-RGB foreground threshold",
            "backgroundThreshold": int(config.front_view_background_threshold),
            "normalization": "foreground bbox centered to fixed subject extent",
            "scalePolicy": "per-frame generated crop normalized, then one shared bind-pose camera fit",
            "subjectExtent": float(config.front_view_subject_extent),
            "subjectPadding": float(config.front_view_subject_padding),
            "frameCount": len(front_paths),
            "paths": [str(path) for path in front_paths],
            "fingerprint": front_fingerprint,
        }
    timing_files = [
        candidate
        for candidate in (source / "frame_durations.json", source / "timing.json", source / "metadata.json")
        if candidate.is_file()
    ]
    return PreparedClip(
        source_dir=source,
        frame_paths=tuple(files),
        frame_indices=indices,
        source_fps=float(source_fps),
        frame_durations=durations,
        rgb=np.stack(rgbs).astype(np.float32),
        masks=mask_array,
        depth=None if depth is None else depth.astype(np.float32),
        depth_confidence=None if depth_confidence is None else depth_confidence.astype(np.float32),
        edge=edge_array,
        sdf=_sdf(mask_array),
        feature_points=tuple(_auto_feature_points(mask_array[index], edge_array[index]) for index in range(len(files))),
        fingerprint=fingerprint_paths(
            [*files, *timing_files],
            extra=f"alpha_threshold={config.alpha_threshold};resolution={camera.width}x{camera.height};durations={durations}",
        ),
        shadow_cull_report={
            "ok": True,
            "applied": True,
            "sourceDir": str(source),
            "frameCount": len(files),
            "method": "def_soft_shadow.cull_def_soft_shadow_rgba",
        },
        front_frame_paths=front_paths,
        front_rgb=front_rgb,
        front_masks=front_masks,
        front_edge=front_edge,
        front_sdf=front_sdf,
        front_feature_points=front_feature_points,
        front_fingerprint=front_fingerprint,
        front_provenance=front_provenance,
    )
