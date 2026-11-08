#!/usr/bin/env python3
"""Run official Video Depth Anything Small on authentic movement frames.

This is a focused comparison lane. It consumes the shadow-culled movement
frames produced by ``fit_def_corpus_depth.py`` and runs VDA's actual temporal
video-depth model over the complete movement sequence. It does not use DA3,
RIFE frames, Blender, or a video codec round trip.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
VDA_ROOT = ROOT / "tools" / "external" / "Video-Depth-Anything"
DEFAULT_CHECKPOINT = ROOT / "artifacts" / "model_cache" / "video_depth_anything_vits.pth"
DEFAULT_SOURCE = (
    ROOT
    / "artifacts/depth_model_comparison/def_animation_sets/h3_hobgoblin"
    / "20260815_hobgoblin_corpus/corpus/source_shadow_culled/g00_move"
)
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts/depth_model_comparison/def_animation_sets/h3_hobgoblin"
    / "20260815_hobgoblin_corpus/movement_preview/vda_small"
)
VDA_MODEL_ID = "Video-Depth-Anything-Small"
DAV2_MODEL_ID = "depth-anything/Depth-Anything-V2-Small-hf"
PIPELINE_CACHE_VERSION = 1
PIPELINE_MANIFEST_NAME = ".depth_cache_manifest.json"
PIPELINE_DEPTH_DIR_NAME = "frames_ground_truth_depth_vda"
PIPELINE_REVERSE_DEPTH_DIR_NAME = "frames_src_depth_vda_reverse"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pngs(directory: Path) -> list[Path]:
    paths = sorted(directory.glob("*.png"), key=lambda p: int(p.stem))
    if not paths:
        raise FileNotFoundError(f"no movement PNG frames found: {directory}")
    return paths


def _neutral_rgb(
    rgba: np.ndarray,
    *,
    alpha_opaque: float = 0.08,
) -> tuple[np.ndarray, np.ndarray]:
    alpha = rgba[..., 3].astype(np.float32) / 255.0
    rgb = rgba[..., :3].copy()
    for channel in range(3):
        rgb[..., channel] = np.clip(
            rgb[..., channel].astype(np.float32) * alpha + 128.0 * (1.0 - alpha),
            0.0,
            255.0,
        ).astype(np.uint8)
    return rgb, alpha > float(alpha_opaque)


def _normalize_depth(
    depths: np.ndarray,
    masks: list[np.ndarray],
    *,
    lower_percentile: float = 2.0,
    upper_percentile: float = 98.0,
    norm_mode: str = "clip",
) -> list[np.ndarray]:
    if norm_mode not in ("clip", "per_frame"):
        raise ValueError("norm_mode must be 'clip' or 'per_frame'")

    if norm_mode == "per_frame":
        result: list[np.ndarray] = []
        for depth, mask in zip(depths, masks):
            if not mask.any():
                raise ValueError("movement frame contains no valid alpha pixels")
            values = depth[mask].astype(np.float32, copy=False)
            lo, hi = np.percentile(values, [float(lower_percentile), float(upper_percentile)])
            if float(hi - lo) < 1e-6:
                hi = lo + 1.0
            near_bright = np.clip((depth - lo) / (hi - lo), 0.0, 1.0)
            frame = np.zeros(depth.shape, dtype=np.float32)
            frame[mask] = near_bright[mask]
            result.append(frame)
        return result

    values = np.concatenate(
        [depth[mask] for depth, mask in zip(depths, masks) if mask.any()]
    ).astype(np.float32, copy=False)
    if values.size == 0:
        raise ValueError("movement frames contain no valid alpha pixels")
    lo, hi = np.percentile(values, [float(lower_percentile), float(upper_percentile)])
    if float(hi - lo) < 1e-6:
        hi = lo + 1.0
    result: list[np.ndarray] = []
    for depth, mask in zip(depths, masks):
        # VDA's relative-depth checkpoint emits inverse depth/disparity:
        # larger values are nearer. Do not invert it a second time. Store the
        # pipeline convention directly: near=bright and outside-alpha=zero.
        near_bright = np.clip((depth - lo) / (hi - lo), 0.0, 1.0)
        frame = np.zeros(depth.shape, dtype=np.float32)
        frame[mask] = near_bright[mask]
        result.append(frame)
    return result


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _panel(rgba: np.ndarray, depth: np.ndarray, name: str, width: int) -> Image.Image:
    height, source_width = rgba.shape[:2]
    panel_height = max(1, round(width * height / source_width))
    gap, title = 6, 32
    canvas = Image.new("RGB", (width * 2 + gap, panel_height + title), (22, 22, 22))
    draw = ImageDraw.Draw(canvas)
    font = _font(16)
    sprite = Image.fromarray(rgba, "RGBA")
    bg = Image.new("RGBA", sprite.size, (8, 8, 8, 255))
    sprite = Image.alpha_composite(bg, sprite).convert("RGB").resize(
        (width, panel_height), Image.Resampling.LANCZOS
    )
    depth_image = Image.fromarray(
        np.clip(np.rint(depth * 255.0), 0, 255).astype(np.uint8), "L"
    ).resize((width, panel_height), Image.Resampling.BILINEAR).convert("RGB")
    for x, label, image in (
        (0, "movement sprite (shadow culled)", sprite),
        (width + gap, "VDA-S temporal depth (near=bright)", depth_image),
    ):
        draw.text((x + 5, 6), label, fill=(240, 240, 240), font=font)
        canvas.paste(image, (x, title))
    draw.text((canvas.width - 92, 6), name, fill=(180, 200, 215), font=font)
    return canvas


def source_signature(source_dir: Path) -> str:
    sources = _pngs(source_dir)
    return hashlib.sha256(
        json.dumps(
            {"files": [(path.name, _sha256(path)) for path in sources]},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def comparison_vda_run_dir(root: Path, unit_name: str, animation_name: str) -> Path:
    return (
        Path(root)
        / "artifacts/depth_model_comparison/def_animation_sets"
        / f"h3_{unit_name}"
        / str(animation_name)
        / "vda_small"
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _save_depth_u16(path: Path, depth01: np.ndarray) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(
        np.clip(np.rint(depth01 * 65535.0), 0, 65535).astype(np.uint16)
    ).save(path)


def _write_pipeline_manifest(
    output_dir: Path,
    *,
    source_dir: Path,
    checkpoint: Path,
    source_paths: list[Path],
    input_size: int,
    fps: float,
    provenance: str,
    import_run_dir: Path | None = None,
    fp32: bool = False,
    norm_lower_percentile: float = 2.0,
    norm_upper_percentile: float = 98.0,
    norm_mode: str = "clip",
    alpha_opaque: float = 0.08,
) -> Path:
    manifest = {
        "version": PIPELINE_CACHE_VERSION,
        "model": VDA_MODEL_ID,
        "encoder": "vits",
        "checkpoint": str(Path(checkpoint).resolve()),
        "checkpointSha256": _sha256(Path(checkpoint)),
        "sourceDirectory": str(Path(source_dir).resolve()),
        "sourceSignature": source_signature(source_dir),
        "frameNames": [path.name for path in source_paths],
        "inputSize": int(input_size),
        "requestedFps": float(fps),
        "fp32": bool(fp32),
        "normLowerPercentile": float(norm_lower_percentile),
        "normUpperPercentile": float(norm_upper_percentile),
        "normMode": str(norm_mode),
        "alphaOpaque": float(alpha_opaque),
        "provenance": provenance,
    }
    if import_run_dir is not None:
        manifest["importRunDir"] = str(Path(import_run_dir).resolve())
    path = Path(output_dir) / PIPELINE_MANIFEST_NAME
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def assert_vda_pipeline_cache(output_dir: Path) -> dict[str, Any]:
    """Refuse per-frame DAV2 leftovers and unlabelled depth folders."""
    output_dir = Path(output_dir)
    manifest = _read_json(output_dir / PIPELINE_MANIFEST_NAME)
    if manifest is None:
        raise RuntimeError(
            f"depth cache has no Video Depth Anything manifest: {output_dir / PIPELINE_MANIFEST_NAME}"
        )
    model = manifest.get("model")
    if model == DAV2_MODEL_ID:
        raise RuntimeError(
            f"refusing Depth Anything V2 Small cache at {output_dir}; "
            f"this solver requires {VDA_MODEL_ID}"
        )
    if model != VDA_MODEL_ID:
        raise RuntimeError(
            f"unexpected depth model {model!r} at {output_dir}; required {VDA_MODEL_ID!r}"
        )
    return manifest


def pipeline_cache_is_valid(
    output_dir: Path,
    source_dir: Path,
    checkpoint: Path,
    *,
    input_size: int = 518,
    fps: float = 12.0,
    fp32: bool = False,
    norm_lower_percentile: float = 2.0,
    norm_upper_percentile: float = 98.0,
    norm_mode: str = "clip",
    alpha_opaque: float = 0.08,
) -> bool:
    output_dir = Path(output_dir)
    checkpoint = Path(checkpoint)
    if not checkpoint.is_file():
        return False
    try:
        manifest = assert_vda_pipeline_cache(output_dir)
    except RuntimeError:
        return False
    source_paths = _pngs(source_dir)
    expected_names = [path.name for path in source_paths]
    present = {path.name for path in output_dir.glob("*.png")}
    manifest_fp32 = bool(manifest.get("fp32", False))
    return (
        manifest.get("version") == PIPELINE_CACHE_VERSION
        and manifest.get("checkpointSha256") == _sha256(checkpoint)
        and manifest.get("sourceSignature") == source_signature(source_dir)
        and manifest.get("frameNames") == expected_names
        and int(manifest.get("inputSize", -1)) == int(input_size)
        and float(manifest.get("requestedFps", -1.0)) == float(fps)
        and manifest_fp32 == bool(fp32)
        and float(manifest.get("normLowerPercentile", 2.0)) == float(norm_lower_percentile)
        and float(manifest.get("normUpperPercentile", 98.0)) == float(norm_upper_percentile)
        and str(manifest.get("normMode", "clip")) == str(norm_mode)
        and float(manifest.get("alphaOpaque", 0.08)) == float(alpha_opaque)
        and set(expected_names) <= present
    )


def _refuse_dav2_mix(output_dir: Path) -> None:
    manifest = _read_json(Path(output_dir) / PIPELINE_MANIFEST_NAME)
    if manifest is None:
        return
    if manifest.get("model") == DAV2_MODEL_ID:
        raise RuntimeError(
            f"refusing to mix {VDA_MODEL_ID} into a Depth Anything V2 cache: {output_dir}. "
            f"Point target_depth_dir at {PIPELINE_DEPTH_DIR_NAME}."
        )


def _clear_owned_vda_cache(output_dir: Path) -> None:
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return
    for path in output_dir.glob("*.png"):
        path.unlink()
    manifest_path = output_dir / PIPELINE_MANIFEST_NAME
    if manifest_path.is_file():
        manifest_path.unlink()


def _import_matching_vda_run(
    *,
    source_dir: Path,
    output_dir: Path,
    checkpoint: Path,
    run_dir: Path,
    input_size: int,
    fps: float,
) -> bool:
    run_dir = Path(run_dir)
    run_manifest = _read_json(run_dir / "vda_s_manifest.json")
    if run_manifest is None:
        return False
    if run_manifest.get("model") != VDA_MODEL_ID:
        return False
    if run_manifest.get("checkpoint_sha256") != _sha256(checkpoint):
        return False
    source_paths = _pngs(source_dir)
    recorded = run_manifest.get("source_frame_sha256")
    if not isinstance(recorded, list) or len(recorded) != len(source_paths):
        return False
    if [_sha256(path) for path in source_paths] != list(recorded):
        return False
    depth_dir = run_dir / "depth"
    missing = [path.name for path in source_paths if not (depth_dir / path.name).is_file()]
    if missing:
        return False
    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_owned_vda_cache(output_dir)
    for path in source_paths:
        shutil.copy2(depth_dir / path.name, output_dir / path.name)
    _write_pipeline_manifest(
        output_dir,
        source_dir=source_dir,
        checkpoint=checkpoint,
        source_paths=source_paths,
        input_size=input_size,
        fps=fps,
        provenance="imported",
        import_run_dir=run_dir,
    )
    return True


def infer_normalized_vda_depths(
    source_dir: Path,
    checkpoint: Path = DEFAULT_CHECKPOINT,
    input_size: int = 518,
    fps: float = 12.0,
    allow_cpu: bool = False,
    vda_root: Path | None = None,
    fp32: bool = False,
    norm_lower_percentile: float = 2.0,
    norm_upper_percentile: float = 98.0,
    norm_mode: str = "clip",
    alpha_opaque: float = 0.08,
) -> dict[str, Any]:
    """Run official VDA-S over the complete clip. Never fills a subset of frames.

    CUDA is required unless ``allow_cpu`` is set. CPU is the same Video Depth
    Anything Small weights, not Depth Anything V2 and not a made-up map.
    """
    checkout = Path(vda_root) if vda_root is not None else VDA_ROOT
    if not checkout.is_dir():
        raise FileNotFoundError(f"VDA source checkout is missing: {checkout}")
    checkpoint = Path(checkpoint)
    if not checkpoint.is_file():
        raise FileNotFoundError(f"VDA-S checkpoint is missing: {checkpoint}")
    source_paths = _pngs(source_dir)
    sys.path.insert(0, str(checkout))
    import torch
    from video_depth_anything.video_depth import VideoDepthAnything

    cuda = bool(torch.cuda.is_available())
    if not cuda and not allow_cpu:
        raise RuntimeError("VDA-S requires CUDA; refusing CPU inference")
    device = "cuda" if cuda else "cpu"
    use_fp32 = device == "cpu" or bool(fp32)
    model = VideoDepthAnything(
        encoder="vits", features=64, out_channels=[48, 96, 192, 384]
    )
    model.load_state_dict(torch.load(checkpoint, map_location="cpu"), strict=True)
    model = model.to(device).eval()

    rgba_frames: list[np.ndarray] = []
    rgb_frames: list[np.ndarray] = []
    masks: list[np.ndarray] = []
    for path in source_paths:
        rgba = np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)
        rgb, mask = _neutral_rgb(rgba, alpha_opaque=alpha_opaque)
        rgba_frames.append(rgba)
        rgb_frames.append(rgb)
        masks.append(mask)
    frames = np.stack(rgb_frames, axis=0)
    if cuda:
        torch.cuda.reset_peak_memory_stats()
    start = time.perf_counter()
    with torch.inference_mode():
        raw_depths, effective_fps = model.infer_video_depth(
            frames,
            target_fps=float(fps),
            input_size=int(input_size),
            device=device,
            fp32=use_fp32,
        )
    if cuda:
        torch.cuda.synchronize()
        peak = float(torch.cuda.max_memory_allocated() / (1024**3))
        gpu = torch.cuda.get_device_name(0)
        cuda_ver = str(torch.version.cuda)
    else:
        peak = 0.0
        gpu = "cpu"
        cuda_ver = None
    elapsed = time.perf_counter() - start
    return {
        "source_paths": source_paths,
        "rgba_frames": rgba_frames,
        "normalized": _normalize_depth(
            np.asarray(raw_depths),
            masks,
            lower_percentile=norm_lower_percentile,
            upper_percentile=norm_upper_percentile,
            norm_mode=norm_mode,
        ),
        "elapsed_seconds": elapsed,
        "peak_allocated_gb": peak,
        "effective_fps": float(effective_fps),
        "gpu": gpu,
        "torch": str(torch.__version__),
        "cuda": cuda_ver,
        "device": device,
        "fp32": use_fp32,
        "normLowerPercentile": float(norm_lower_percentile),
        "normUpperPercentile": float(norm_upper_percentile),
        "alphaOpaque": float(alpha_opaque),
        "inputSize": int(input_size),
    }


def ensure_vda_pipeline_cache(
    source_dir: Path,
    output_dir: Path,
    checkpoint: Path = DEFAULT_CHECKPOINT,
    input_size: int = 518,
    fps: float = 12.0,
    import_run_dir: Path | None = None,
    infer_fn: Callable[..., list[np.ndarray]] | None = None,
    allow_cpu: bool = False,
    vda_root: Path | None = None,
    fp32: bool = False,
    norm_lower_percentile: float = 2.0,
    norm_upper_percentile: float = 98.0,
    norm_mode: str = "clip",
    alpha_opaque: float = 0.08,
) -> dict[str, Any]:
    """Write or reuse a whole-clip VDA depth cache. Never mixes DAV2 frames."""
    source_dir = Path(source_dir)
    output_dir = Path(output_dir)
    checkpoint = Path(checkpoint)
    if not checkpoint.is_file():
        raise FileNotFoundError(f"VDA-S checkpoint is missing: {checkpoint}")
    source_paths = _pngs(source_dir)
    _refuse_dav2_mix(output_dir)
    if pipeline_cache_is_valid(
        output_dir,
        source_dir,
        checkpoint,
        input_size=input_size,
        fps=fps,
        fp32=fp32,
        norm_lower_percentile=norm_lower_percentile,
        norm_upper_percentile=norm_upper_percentile,
        norm_mode=norm_mode,
        alpha_opaque=alpha_opaque,
    ):
        return {
            "status": "reused",
            "output_dir": str(output_dir.resolve()),
            "frame_count": len(source_paths),
        }
    leftover_pngs = sorted(output_dir.glob("*.png")) if output_dir.is_dir() else []
    leftover_manifest = _read_json(output_dir / PIPELINE_MANIFEST_NAME) if output_dir.is_dir() else None
    if leftover_pngs and leftover_manifest is None:
        raise RuntimeError(
            f"refusing to overwrite unlabelled depth PNGs at {output_dir}; "
            f"delete that folder or point target_depth_dir at {PIPELINE_DEPTH_DIR_NAME}"
        )
    if import_run_dir is not None and _import_matching_vda_run(
        source_dir=source_dir,
        output_dir=output_dir,
        checkpoint=checkpoint,
        run_dir=import_run_dir,
        input_size=input_size,
        fps=fps,
    ):
        return {
            "status": "imported",
            "output_dir": str(output_dir.resolve()),
            "import_run_dir": str(Path(import_run_dir).resolve()),
            "frame_count": len(source_paths),
        }
    output_dir.mkdir(parents=True, exist_ok=True)
    _clear_owned_vda_cache(output_dir)
    if infer_fn is None:
        inferred = infer_normalized_vda_depths(
            source_dir,
            checkpoint=checkpoint,
            input_size=input_size,
            fps=fps,
            allow_cpu=allow_cpu,
            vda_root=vda_root,
            fp32=fp32,
            norm_lower_percentile=norm_lower_percentile,
            norm_upper_percentile=norm_upper_percentile,
            norm_mode=norm_mode,
            alpha_opaque=alpha_opaque,
        )
        depths = list(inferred["normalized"])
        provenance = "inferred_cpu" if inferred.get("device") == "cpu" else "inferred"
    else:
        depths = list(infer_fn(source_dir, checkpoint, input_size, fps))
        provenance = "inferred"
    if len(depths) != len(source_paths):
        raise RuntimeError(
            f"VDA inference returned {len(depths)} maps for {len(source_paths)} frames"
        )
    for path, depth in zip(source_paths, depths):
        _save_depth_u16(output_dir / path.name, np.asarray(depth, dtype=np.float32))
    _write_pipeline_manifest(
        output_dir,
        source_dir=source_dir,
        checkpoint=checkpoint,
        source_paths=source_paths,
        input_size=input_size,
        fps=fps,
        provenance=provenance,
        fp32=fp32,
        norm_lower_percentile=norm_lower_percentile,
        norm_upper_percentile=norm_upper_percentile,
        norm_mode=norm_mode,
        alpha_opaque=alpha_opaque,
    )
    return {
        "status": "inferred",
        "output_dir": str(output_dir.resolve()),
        "frame_count": len(source_paths),
    }


def run_vda(
    source_dir: Path = DEFAULT_SOURCE,
    checkpoint: Path = DEFAULT_CHECKPOINT,
    output_dir: Path = DEFAULT_OUTPUT,
    input_size: int = 518,
    fps: float = 12.0,
    panel_width: int = 420,
    allow_cpu: bool = False,
    vda_root: Path | None = None,
    fp32: bool = False,
    norm_lower_percentile: float = 2.0,
    norm_upper_percentile: float = 98.0,
    norm_mode: str = "clip",
    alpha_opaque: float = 0.08,
) -> dict[str, Any]:
    source_paths = _pngs(source_dir)
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=False)
    inferred = infer_normalized_vda_depths(
        source_dir,
        checkpoint=checkpoint,
        input_size=input_size,
        fps=fps,
        allow_cpu=allow_cpu,
        vda_root=vda_root,
        fp32=fp32,
        norm_lower_percentile=norm_lower_percentile,
        norm_upper_percentile=norm_upper_percentile,
        norm_mode=norm_mode,
        alpha_opaque=alpha_opaque,
    )

    depth_dir = output_dir / "depth"
    depth_dir.mkdir()
    panels: list[Image.Image] = []
    for path, rgba, depth in zip(source_paths, inferred["rgba_frames"], inferred["normalized"]):
        Image.fromarray(np.clip(np.rint(depth * 65535), 0, 65535).astype(np.uint16)).save(
            depth_dir / path.name
        )
        panels.append(_panel(rgba, depth, path.stem, panel_width))
    contact = Image.new("RGB", (panels[0].width, sum(p.height for p in panels)), (22, 22, 22))
    y = 0
    for panel in panels:
        contact.paste(panel, (0, y))
        y += panel.height
    contact_path = output_dir / "movement_vda_s_contact_sheet.png"
    contact.save(contact_path)
    gif_path = output_dir / "movement_vda_s.gif"
    panels[0].save(
        gif_path,
        save_all=True,
        append_images=panels[1:],
        duration=max(1, round(1000.0 / fps)),
        loop=0,
        optimize=False,
    )
    checkpoint = Path(checkpoint)
    manifest = {
        "schema_version": 1,
        "model": VDA_MODEL_ID,
        "encoder": "vits",
        "checkpoint": str(checkpoint.resolve()),
        "checkpoint_sha256": _sha256(checkpoint),
        "source_dir": str(Path(source_dir).resolve()),
        "source_frames": [str(path) for path in source_paths],
        "source_frame_sha256": [_sha256(path) for path in source_paths],
        "frame_count": len(source_paths),
        "input_size": input_size,
        "requested_fps": fps,
        "effective_fps": float(inferred["effective_fps"]),
        "elapsed_seconds": inferred["elapsed_seconds"],
        "peak_allocated_gb": inferred["peak_allocated_gb"],
        "gpu": inferred["gpu"],
        "torch": inferred["torch"],
        "cuda": inferred["cuda"],
        "source_policy": {
            "authentic_def_frames_only": True,
            "rife_interpolated_frames_used": False,
            "alpha_shadow_culled": True,
            "scope": "group 0 movement frames",
        },
        "outputs": {
            "depth_dir": str(depth_dir),
            "contact_sheet": str(contact_path),
            "gif": str(gif_path),
        },
    }
    manifest_path = output_dir / "vda_s_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"VDA-S complete: {inferred['elapsed_seconds']:.2f}s, peak={manifest['peak_allocated_gb']:.2f} GB")
    print(f"preview: {contact_path}")
    print(f"gif: {gif_path}")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--input-size", type=int, default=518)
    parser.add_argument("--fps", type=float, default=12.0)
    parser.add_argument("--panel-width", type=int, default=420)
    parser.add_argument(
        "--fp32",
        action="store_true",
        help="Run VDA-S inference in FP32 (default FP16 on CUDA).",
    )
    parser.add_argument("--norm-low", type=float, default=2.0)
    parser.add_argument("--norm-high", type=float, default=98.0)
    parser.add_argument(
        "--norm-mode",
        choices=("clip", "per_frame"),
        default="clip",
        help="clip = one percentile range across the whole movement; per_frame = per-frame range.",
    )
    parser.add_argument("--alpha-opaque", type=float, default=0.08)
    parser.add_argument(
        "--allow-cpu",
        action="store_true",
        help="Run Video-Depth-Anything-Small on CPU. Default still refuses without CUDA.",
    )
    parser.add_argument("--vda-root", type=Path, default=None)
    args = parser.parse_args()
    run_vda(
        args.source_dir.resolve(),
        args.checkpoint.resolve(),
        args.output_dir.resolve(),
        args.input_size,
        args.fps,
        args.panel_width,
        allow_cpu=args.allow_cpu,
        vda_root=args.vda_root,
        fp32=args.fp32,
        norm_lower_percentile=args.norm_low,
        norm_upper_percentile=args.norm_high,
        norm_mode=args.norm_mode,
        alpha_opaque=args.alpha_opaque,
    )


if __name__ == "__main__":
    main()
