#!/usr/bin/env python3
"""Compare the cached single-frame depth model with multi-frame DA3.

This is an inspection lane, not a silent replacement for the pose pipeline.
The current depth maps are loaded from the existing V2 Small artifacts.  The
comparison model is Depth Anything 3 (DA3-LARGE-1.1), run once per ordered
animation clip so its reference-view geometry is shared across frames.

The script deliberately uses the same neutral alpha composite as
``predict_sprite_depth.py`` and keeps the source alpha as a validity mask.
DA3 is resized back to the source frame resolution and converted to the
pipeline convention (near=bright, transparent pixels=zero).

Windows note: the DA3 input processor normally creates a worker pool.  That
can fail in a notebook/Windows process with WinError 5, so this comparison
forces the processor to run sequentially.  It does not change the model or
the multi-frame reference strategy; it only removes the fragile subprocess.

Examples:

    python compare_sprite_depth_models.py
    python compare_sprite_depth_models.py --sequence crusader_walk griffon_walk

The output contains the two normalized depth sequences, contact sheets, GIFs,
and a JSON provenance/timing report under ``artifacts/depth_model_comparison``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import importlib.metadata
import platform
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = Path(__file__).resolve().parent
DA3_SOURCE = ROOT / "tools" / "external" / "Depth-Anything-3" / "src"
DA3_DEPS = ROOT / "tools" / "external" / "depth_anything_deps"
DA3_MODEL = ROOT / "artifacts" / "model_cache" / "DA3-LARGE-1.1"


@dataclass(frozen=True)
class SequenceSpec:
    """One authentic source sequence and its cached current depth maps."""

    key: str
    label: str
    source_dir: Path
    current_depth_dir: Path
    note: str = ""
    fps: float = 12.0


def _p(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def default_sequences(root: Path = ROOT) -> dict[str, SequenceSpec]:
    """Return the known local comparison sequences.

    The local Hobgoblin pose-picker inventory currently contains attack_g11,
    not a walk/move group.  It is included under an explicit name instead of
    silently relabeling an attack as a walk.
    """
    return {
        "crusader_walk": SequenceSpec(
            key="crusader_walk",
            label="Crusader walk / move_g0",
            source_dir=root / "artifacts/pose_picker_runs/h3_crusader/move_g0/frames_ground_truth_shadow_culled",
            current_depth_dir=root / "artifacts/pose_picker_runs/h3_crusader/move_g0/frames_ground_truth_depth_predicted",
            note="Authentic ground-truth DEF group 0; alpha-shadow culled.",
        ),
        "griffon_walk": SequenceSpec(
            key="griffon_walk",
            label="Griffon walk / move_g0",
            source_dir=root / "artifacts/roc_pose_pipeline/smart_rig_move_pilot/frames_ground_truth_shadow_culled",
            current_depth_dir=root / "artifacts/roc_pose_pipeline/smart_rig_move_pilot/frames_ground_truth_depth_predicted",
            note="Authentic ground-truth DEF move frames; alpha-shadow culled.",
        ),
        "hobgoblin_available_attack": SequenceSpec(
            key="hobgoblin_available_attack",
            label="Hobgoblin attack / attack_g11",
            source_dir=root / "artifacts/pose_picker_runs/h3_hobgoblin/attack_g11/frames_src_shadow_culled",
            current_depth_dir=root / "artifacts/pose_picker_runs/h3_hobgoblin/attack_g11/frames_src_depth_predicted",
            note=(
                "The local pose-picker inventory has attack_g11 but no walk/move "
                "source directory; this is intentionally not mislabeled as walk."
            ),
        ),
    }


def _ensure_da3_importable() -> None:
    missing = [str(path) for path in (DA3_SOURCE, DA3_DEPS) if not path.is_dir()]
    if missing:
        raise RuntimeError(
            "DA3 comparison dependencies are missing; expected local paths: "
            + ", ".join(missing)
        )
    for path in (DA3_DEPS, DA3_SOURCE):
        text_path = str(path)
        if text_path not in sys.path:
            sys.path.insert(0, text_path)


def _pngs(directory: Path) -> list[Path]:
    paths = sorted(directory.glob("*.png"), key=lambda p: (int(p.stem) if p.stem.isdigit() else p.stem))
    if not paths:
        raise FileNotFoundError(f"no PNG frames found: {directory}")
    return paths


def _validate_spec(spec: SequenceSpec) -> tuple[list[Path], list[Path]]:
    if not spec.source_dir.is_dir():
        raise FileNotFoundError(f"source frame directory is missing: {spec.source_dir}")
    if not spec.current_depth_dir.is_dir():
        raise FileNotFoundError(f"current depth directory is missing: {spec.current_depth_dir}")
    source_paths = _pngs(spec.source_dir)
    current_paths = []
    for source_path in source_paths:
        depth_path = spec.current_depth_dir / source_path.name
        if not depth_path.is_file():
            raise FileNotFoundError(
                f"current depth map is missing for {spec.key} frame {source_path.name}: {depth_path}"
            )
        current_paths.append(depth_path)
    return source_paths, current_paths


def _rgba_and_rgb(path: Path) -> tuple[np.ndarray, np.ndarray]:
    rgba = np.asarray(Image.open(path).convert("RGBA"), dtype=np.uint8)
    alpha = rgba[:, :, 3].astype(np.float32) / 255.0
    rgb = rgba[:, :, :3].copy()
    # Match predict_sprite_depth.py: transparent sprite pixels are neutral,
    # not black, before the monocular model sees them.
    for channel, value in enumerate((128, 128, 128)):
        rgb_channel = rgb[:, :, channel].astype(np.float32)
        rgb[:, :, channel] = np.clip(
            rgb_channel * alpha + value * (1.0 - alpha), 0.0, 255.0
        ).astype(np.uint8)
    return rgba, rgb


def _resize_float(depth: np.ndarray, width: int, height: int) -> np.ndarray:
    if depth.shape == (height, width):
        return np.asarray(depth, dtype=np.float32)
    image = Image.fromarray(np.asarray(depth, dtype=np.float32), mode="F")
    resized = image.resize((width, height), Image.Resampling.BILINEAR)
    return np.asarray(resized, dtype=np.float32)


def _sequence_normalize_da3(
    raw_depths: list[np.ndarray],
    masks: list[np.ndarray],
    *,
    lower_percentile: float = 2.0,
    upper_percentile: float = 98.0,
) -> list[np.ndarray]:
    """Normalize a sequence with one scale, retaining temporal depth order.

    DA3's ``depth`` output is distance-like in the current API, whereas this
    pipeline stores near=bright.  We therefore invert after the shared robust
    stretch.  A single clip-wide stretch is important: per-frame stretching
    would make temporal comparisons look artificially consistent.
    """
    values = [depth[mask] for depth, mask in zip(raw_depths, masks) if mask.any()]
    if not values:
        return [np.zeros_like(depth, dtype=np.float32) for depth in raw_depths]
    joined = np.concatenate(values).astype(np.float32, copy=False)
    lo = float(np.percentile(joined, lower_percentile))
    hi = float(np.percentile(joined, upper_percentile))
    if hi - lo < 1e-6:
        hi = lo + 1.0
    normalized: list[np.ndarray] = []
    for depth, mask in zip(raw_depths, masks):
        # Distance -> near-bright disparity convention.
        near_bright = 1.0 - np.clip((depth - lo) / (hi - lo), 0.0, 1.0)
        out = np.zeros(depth.shape, dtype=np.float32)
        out[mask] = near_bright[mask]
        normalized.append(out)
    return normalized


def _load_current_depths(paths: Iterable[Path], masks: list[np.ndarray]) -> list[np.ndarray]:
    tool_text = str(TOOL_DIR)
    if tool_text not in sys.path:
        sys.path.insert(0, tool_text)
    from predict_sprite_depth import load_depth_u16

    result: list[np.ndarray] = []
    for path, mask in zip(paths, masks):
        source_height, source_width = mask.shape
        depth = load_depth_u16(path)
        depth = _resize_float(depth, source_width, source_height)
        depth = np.clip(depth, 0.0, 1.0).astype(np.float32)
        depth[~mask] = 0.0
        result.append(depth)
    return result


class _SequentialInputProcessor:
    """Force DA3 preprocessing into the current process on Windows."""

    def __init__(self, base: Any):
        self.base = base

    def __call__(
        self,
        image: Any,
        extrinsics: Any = None,
        intrinsics: Any = None,
        process_res: int = 504,
        process_res_method: str = "upper_bound_resize",
        **kwargs: Any,
    ) -> Any:
        # DepthAnything3._preprocess calls InputProcessor positionally.  Keep
        # that API shape here, then pass the worker controls as keyword-only
        # arguments to the real processor.
        kwargs["num_workers"] = 1
        kwargs["sequential"] = True
        return self.base(
            image,
            extrinsics,
            intrinsics,
            process_res,
            process_res_method,
            **kwargs,
        )


def _load_da3(model_dir: Path, device: str = "cuda") -> tuple[Any, Any]:
    _ensure_da3_importable()
    import torch
    from depth_anything_3.api import DepthAnything3

    if not torch.cuda.is_available():
        raise RuntimeError("DA3 comparison requires CUDA; refusing CPU inference.")
    if not model_dir.is_dir():
        raise FileNotFoundError(f"local DA3 model directory is missing: {model_dir}")
    model = DepthAnything3.from_pretrained(str(model_dir)).to(device).eval()
    model.input_processor = _SequentialInputProcessor(model.input_processor)
    return model, torch


def _predict_da3_sequence(
    model: Any,
    torch: Any,
    rgb_frames: list[np.ndarray],
    masks: list[np.ndarray],
    *,
    reference_view: str,
    process_res: int,
) -> tuple[list[np.ndarray], dict[str, float]]:
    start = time.perf_counter()
    torch.cuda.reset_peak_memory_stats()
    with torch.inference_mode():
        prediction = model.inference(
            rgb_frames,
            ref_view_strategy=reference_view,
            process_res=int(process_res),
            process_res_method="upper_bound_resize",
        )
    torch.cuda.synchronize()
    elapsed = time.perf_counter() - start
    depth_value = prediction.depth
    if hasattr(depth_value, "detach"):
        depth_batch = depth_value.detach().float().cpu().numpy()
    else:
        depth_batch = np.asarray(depth_value, dtype=np.float32)
    depth_batch = np.asarray(depth_batch, dtype=np.float32)
    if depth_batch.ndim != 3 or depth_batch.shape[0] != len(rgb_frames):
        raise RuntimeError(
            f"unexpected DA3 depth output shape {depth_batch.shape}; "
            f"expected [{len(rgb_frames)}, H, W]"
        )
    raw_depths: list[np.ndarray] = []
    for depth, mask in zip(depth_batch, masks):
        height, width = mask.shape
        raw_depths.append(_resize_float(depth, width, height))
    normalized = _sequence_normalize_da3(raw_depths, masks)
    return normalized, {
        "seconds": elapsed,
        "peak_allocated_gb": float(torch.cuda.max_memory_allocated() / (1024**3)),
        "processed_height": float(depth_batch.shape[1]),
        "processed_width": float(depth_batch.shape[2]),
    }


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", size)
    except OSError:
        return ImageFont.load_default()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_paths(paths: Iterable[Path]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        path = Path(path)
        digest.update(str(path).encode("utf-8"))
        digest.update(_sha256_file(path).encode("ascii"))
    return digest.hexdigest()


def _git_revision(directory: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(directory), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    revision = result.stdout.strip()
    return revision or None


def _runtime_provenance(model_dir: Path) -> dict[str, Any]:
    import torch

    model_files = sorted(
        path for path in model_dir.iterdir() if path.is_file() and path.name in {"config.json", "model.safetensors"}
    )
    versions: dict[str, str | None] = {}
    for package in ("torch", "transformers", "numpy", "Pillow", "omegaconf", "einops"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    gpu_name = None
    cuda_name = None
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        cuda_name = torch.version.cuda
    return {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "packages": versions,
        "torch_cuda": cuda_name,
        "gpu": gpu_name,
        "model_file_sha256": {
            path.name: _sha256_file(path) for path in model_files
        },
        "model_files_sha256": _sha256_paths(model_files),
        "da3_source_revision": _git_revision(DA3_SOURCE.parent),
        "runner_sha256": _sha256_file(Path(__file__).resolve()),
    }


def _pearson(x: np.ndarray, y: np.ndarray) -> float | None:
    if x.size < 2 or y.size < 2:
        return None
    x_centered = x - float(x.mean())
    y_centered = y - float(y.mean())
    denom = float(np.linalg.norm(x_centered) * np.linalg.norm(y_centered))
    if denom < 1e-8:
        return None
    return float(np.dot(x_centered, y_centered) / denom)


def _rank_values(values: np.ndarray) -> np.ndarray:
    # Monocular relative depth is best compared by ordering.  The small
    # amount of quantization in the input PNGs is handled by stable ordering.
    return np.argsort(np.argsort(values, kind="stable"), kind="stable").astype(np.float32)


def _depth_agreement_metrics(
    current: np.ndarray,
    da3: np.ndarray,
    mask: np.ndarray,
) -> dict[str, float | None]:
    valid = mask & np.isfinite(current) & np.isfinite(da3)
    x = current[valid].astype(np.float32, copy=False)
    y = da3[valid].astype(np.float32, copy=False)
    if x.size < 32:
        return {
            "valid_pixels": float(x.size),
            "masked_mean_abs_difference": None,
            "pearson_agreement": None,
            "rank_agreement": None,
        }
    return {
        "valid_pixels": float(x.size),
        "masked_mean_abs_difference": float(np.mean(np.abs(x - y))),
        "pearson_agreement": _pearson(x, y),
        "rank_agreement": _pearson(_rank_values(x), _rank_values(y)),
    }


def _sequence_agreement_metrics(
    current_depths: list[np.ndarray],
    da3_depths: list[np.ndarray],
    masks: list[np.ndarray],
) -> dict[str, Any]:
    per_frame = [
        _depth_agreement_metrics(current, da3, mask)
        for current, da3, mask in zip(current_depths, da3_depths, masks)
    ]
    summary: dict[str, float | None] = {}
    for key in ("masked_mean_abs_difference", "pearson_agreement", "rank_agreement"):
        values = [item[key] for item in per_frame if item[key] is not None]
        summary[key] = float(np.mean(values)) if values else None
    return {
        "scope": (
            "diagnostic agreement between two relative-depth estimates; "
            "not ground-truth depth accuracy"
        ),
        "mean": summary,
        "per_frame": per_frame,
    }


def _source_preview(rgba: np.ndarray, size: tuple[int, int]) -> Image.Image:
    image = Image.fromarray(rgba, "RGBA")
    background = Image.new("RGBA", image.size, (8, 8, 8, 255))
    return Image.alpha_composite(background, image).convert("RGB").resize(
        size, Image.Resampling.LANCZOS
    )


def _depth_preview(depth: np.ndarray, size: tuple[int, int]) -> Image.Image:
    gray = Image.fromarray(np.clip(np.rint(depth * 255.0), 0, 255).astype(np.uint8), "L")
    # A neutral grayscale presentation keeps model differences readable and
    # avoids implying that these relative estimates are metrically calibrated.
    return gray.resize(size, Image.Resampling.BILINEAR).convert("RGB")


def _panel_frame(
    rgba: np.ndarray,
    current: np.ndarray,
    da3: np.ndarray,
    *,
    panel_width: int,
    frame_name: str,
) -> Image.Image:
    source_height, source_width = rgba.shape[:2]
    panel_height = max(1, round(panel_width * source_height / source_width))
    gap = 4
    title_height = 30
    canvas = Image.new(
        "RGB", (panel_width * 3 + gap * 2, panel_height + title_height), (22, 22, 22)
    )
    draw = ImageDraw.Draw(canvas)
    title_font = _font(15)
    labels = ["sprite RGB", "current: Depth Anything V2 Small", "multi-frame: DA3-LARGE-1.1"]
    panels = [
        _source_preview(rgba, (panel_width, panel_height)),
        _depth_preview(current, (panel_width, panel_height)),
        _depth_preview(da3, (panel_width, panel_height)),
    ]
    for index, (label, panel) in enumerate(zip(labels, panels)):
        x = index * (panel_width + gap)
        draw.text((x + 5, 5), label, fill=(235, 235, 235), font=title_font)
        canvas.paste(panel, (x, title_height))
    draw.text(
        (canvas.width - 92, 5), frame_name,
        fill=(175, 195, 210), font=title_font,
    )
    return canvas


def _save_sequence_outputs(
    spec: SequenceSpec,
    source_paths: list[Path],
    current_depths: list[np.ndarray],
    da3_depths: list[np.ndarray],
    rgba_frames: list[np.ndarray],
    output_root: Path,
    *,
    panel_width: int,
    fps: float,
) -> dict[str, Any]:
    sequence_dir = output_root / spec.key
    current_dir = sequence_dir / "current_v2_small"
    da3_dir = sequence_dir / "da3_large_1_1_multiframe"
    current_dir.mkdir(parents=True, exist_ok=True)
    da3_dir.mkdir(parents=True, exist_ok=True)
    frames: list[Image.Image] = []
    for source_path, current, da3, rgba in zip(
        source_paths, current_depths, da3_depths, rgba_frames
    ):
        Image.fromarray(np.clip(np.rint(current * 65535.0), 0, 65535).astype(np.uint16)).save(
            current_dir / source_path.name
        )
        Image.fromarray(np.clip(np.rint(da3 * 65535.0), 0, 65535).astype(np.uint16)).save(
            da3_dir / source_path.name
        )
        frames.append(
            _panel_frame(
                rgba,
                current,
                da3,
                panel_width=panel_width,
                frame_name=source_path.stem,
            )
        )
    contact = Image.new(
        "RGB",
        (frames[0].width, sum(frame.height for frame in frames)),
        (22, 22, 22),
    )
    y = 0
    for frame in frames:
        contact.paste(frame, (0, y))
        y += frame.height
    contact_path = sequence_dir / "contact_sheet.png"
    contact.save(contact_path)
    gif_path = sequence_dir / "comparison.gif"
    duration_ms = max(1, round(1000.0 / fps))
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=duration_ms,
        loop=0,
        optimize=False,
    )
    return {
        "key": spec.key,
        "label": spec.label,
        "note": spec.note,
        "frame_count": len(source_paths),
        "source_frames": [str(path) for path in source_paths],
        "original_current_depth_dir": str(spec.current_depth_dir),
        "current_depth_dir": str(current_dir),
        "da3_depth_dir": str(da3_dir),
        "contact_sheet": str(contact_path),
        "gif": str(gif_path),
        "fps": fps,
    }


def run_comparison(
    sequences: list[SequenceSpec],
    *,
    output_root: Path,
    model_dir: Path = DA3_MODEL,
    reference_view: str = "middle",
    process_res: int = 504,
    panel_width: int = 340,
    fps: float = 12.0,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run all selected clips with one resident DA3 model."""
    if not sequences:
        raise ValueError("at least one comparison sequence must be selected")
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_root = output_root / run_id
    output_root.mkdir(parents=True, exist_ok=False)
    validated: list[tuple[SequenceSpec, list[Path], list[Path]]] = []
    for spec in sequences:
        source_paths, current_paths = _validate_spec(spec)
        validated.append((spec, source_paths, current_paths))

    model_load_start = time.perf_counter()
    model, torch = _load_da3(model_dir)
    model_load_seconds = time.perf_counter() - model_load_start
    provenance = _runtime_provenance(model_dir)
    results: list[dict[str, Any]] = []
    for spec, source_paths, current_paths in validated:
        print(f"[{spec.key}] loading {len(source_paths)} frames", flush=True)
        rgba_frames: list[np.ndarray] = []
        rgb_frames: list[np.ndarray] = []
        masks: list[np.ndarray] = []
        for path in source_paths:
            rgba, rgb = _rgba_and_rgb(path)
            rgba_frames.append(rgba)
            rgb_frames.append(rgb)
            masks.append((rgba[:, :, 3] / 255.0) > 0.08)
        current_depths = _load_current_depths(current_paths, masks)
        print(
            f"[{spec.key}] DA3 reference={reference_view} process_res={process_res}",
            flush=True,
        )
        da3_depths, timing = _predict_da3_sequence(
            model,
            torch,
            rgb_frames,
            masks,
            reference_view=reference_view,
            process_res=process_res,
        )
        paths = _save_sequence_outputs(
            spec,
            source_paths,
            current_depths,
            da3_depths,
            rgba_frames,
            output_root,
            panel_width=panel_width,
            fps=spec.fps if spec.fps > 0 else fps,
        )
        paths["source_frames_sha256"] = _sha256_paths(source_paths)
        paths["original_current_depth_sha256"] = _sha256_paths(current_paths)
        order_digest = hashlib.sha256()
        for path in source_paths:
            order_digest.update(path.name.encode("utf-8"))
            order_digest.update(b"\0")
        paths["frame_order_sha256"] = order_digest.hexdigest()
        paths["timing"] = timing
        paths["agreement_metrics"] = _sequence_agreement_metrics(
            current_depths, da3_depths, masks
        )
        results.append(paths)
        print(
            f"[{spec.key}] done in {timing['seconds']:.2f}s; "
            f"peak allocated {timing['peak_allocated_gb']:.2f} GB",
            flush=True,
        )
    report = {
        "schema_version": 1,
        "current_model": "depth-anything/Depth-Anything-V2-Small-hf",
        "comparison_model": "depth-anything/DA3-LARGE-1.1",
        "comparison_model_dir": str(model_dir),
        "run_id": run_id,
        "output_root": str(output_root),
        "model_load_seconds": model_load_seconds,
        "provenance": provenance,
        "reference_view": reference_view,
        "process_res": process_res,
        "normalization": {
            "alpha_threshold": 0.08,
            "background": [128, 128, 128],
            "da3_percentiles": [2.0, 98.0],
            "sequence_wide": True,
            "stored_convention": "near=bright, outside-alpha=zero",
        },
        "sequences": results,
    }
    report_path = output_root / "comparison_manifest.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"manifest: {report_path}", flush=True)
    return report


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    available = default_sequences()
    parser.add_argument(
        "--sequence",
        nargs="*",
        choices=sorted(available),
        default=sorted(available),
        help="comparison keys; defaults to all available local sequences",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/depth_model_comparison/da3_large_1_1_multiframe",
    )
    parser.add_argument("--model-dir", type=Path, default=DA3_MODEL)
    parser.add_argument("--reference-view", default="middle")
    parser.add_argument("--process-res", type=int, default=504)
    parser.add_argument("--panel-width", type=int, default=340)
    parser.add_argument("--fps", type=float, default=12.0)
    parser.add_argument(
        "--run-id",
        default=None,
        help="optional output subdirectory name; defaults to a UTC timestamp",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    available = default_sequences()
    selected = [available[key] for key in args.sequence]
    report = run_comparison(
        selected,
        output_root=_p(args.output),
        model_dir=_p(args.model_dir),
        reference_view=args.reference_view,
        process_res=args.process_res,
        panel_width=args.panel_width,
        fps=args.fps,
        run_id=args.run_id,
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
