#!/usr/bin/env python3
"""After clips exist: circular forward/backward vel+accel, then comparison GIFs.

Does not overwrite fused-push gpu_clip_result.json. Writes a parallel tree
under artifacts/circular_temporal_compare/. Proof: generated-artifact GIFs.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))

from circular_temporal_score import (  # noqa: E402
    CircularTemporalConfig,
    apply_circular_temporal_clip,
)
from cascade_clip_pose_tweak import (  # noqa: E402
    gpu_config_for_preview,
    target_frame_dir_from_clip,
)
from deliberate_motion_contract import lifecycle_role_for_clip_name  # noqa: E402
from gpu_cascade_delivery import require_pose_units_degrees  # noqa: E402
from preview_timing import PREVIEW_GIF_FRAME_MS  # noqa: E402
from roc_gpu_cascade_experiment import MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY  # noqa: E402
from smooth_clip_result_physics import (  # noqa: E402
    _BONE_AXES,
    _ROOT_ROTATION_KEYS,
    _ROOT_TRANSLATION_KEYS,
    _bone_vector,
    _pose_bone_names,
    _root_vector,
)

DEFAULT_ROLLOUT = ROOT / "artifacts" / "fused_push_skinned_rollout"
DEFAULT_OUT = ROOT / "artifacts" / "circular_temporal_compare"
PILOTS = (
    ("h3_goblin", "Unit_Idle"),
    ("h3_goblin", "Unit_Move"),
    ("h3_roc", "Unit_Idle"),
    ("h3_roc", "Unit_Move"),
)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sliced_cycle_poses(
    payload: Mapping[str, Any], sidecar: Mapping[str, Any]
) -> dict[int, dict[str, Any]]:
    """Keep original concatenated frame numbers so raster loads the right plates."""
    raw = {int(frame): pose for frame, pose in (payload.get("poses") or {}).items()}
    count = int(sidecar.get("frameCount") or sidecar.get("sourceFrameCount") or 0)
    if count < 1:
        raise ValueError("sidecar is missing frameCount")
    prefix = int(sidecar.get("idlePrefixFrames") or 0)
    animation = str(sidecar.get("fitAnimation") or "")
    if animation == "idle":
        missing = [index for index in range(count) if index not in raw]
        if missing:
            raise KeyError(f"idle payload missing frames {missing[:8]}")
        return {index: raw[index] for index in range(count)}
    frames = list(range(prefix, prefix + count))
    missing = [index for index in frames if index not in raw]
    if missing:
        raise KeyError(f"payload missing sliced frames {missing[:8]}")
    return {index: raw[index] for index in frames}


def _sprite_paths_for_frames(payload: Mapping[str, Any], frames: Sequence[int]) -> list[Path]:
    clip_frames = [int(frame) for frame in payload["frameIndices"]]
    targets = [Path(str(path)) for path in payload["targetPaths"]]
    if len(clip_frames) != len(targets):
        raise ValueError("frameIndices and targetPaths length mismatch")
    by_frame = {frame: path for frame, path in zip(clip_frames, targets)}
    missing = [frame for frame in frames if frame not in by_frame]
    if missing:
        raise KeyError(f"targetPaths missing frames {missing[:8]}")
    return [by_frame[int(frame)] for frame in frames]


def _pack(poses: Mapping[int, Mapping[str, Any]], bone_names: list[str]):
    frames = tuple(sorted(int(frame) for frame in poses))
    bones = np.zeros((len(frames), len(bone_names), 3), dtype=np.float64)
    translation = np.zeros((len(frames), 3), dtype=np.float64)
    rotation = np.zeros((len(frames), 3), dtype=np.float64)
    for row, frame in enumerate(frames):
        pose = poses[frame]
        for bone_i, bone in enumerate(bone_names):
            bones[row, bone_i, :] = np.radians(_bone_vector(pose.get(bone)))
        translation[row, :] = _root_vector(pose, MOTION_ROOT_KEY, _ROOT_TRANSLATION_KEYS)
        rotation[row, :] = np.radians(
            _root_vector(pose, MOTION_ROOT_ROTATION_KEY, _ROOT_ROTATION_KEYS)
        )
    return frames, bones, translation, rotation


def _unpack(
    frames: tuple[int, ...],
    bone_names: list[str],
    bones: np.ndarray,
    translation: np.ndarray,
    rotation: np.ndarray,
) -> dict[int, dict[str, Any]]:
    degrees_bones = np.degrees(bones)
    degrees_rotation = np.degrees(rotation)
    out: dict[int, dict[str, Any]] = {}
    for row, frame in enumerate(frames):
        pose: dict[str, Any] = {}
        for bone_i, bone in enumerate(bone_names):
            values = degrees_bones[row, bone_i, :]
            if float(np.max(np.abs(values))) > 1e-7:
                pose[bone] = {
                    axis: float(values[axis_i]) for axis_i, axis in enumerate(_BONE_AXES)
                }
        pose[MOTION_ROOT_KEY] = {
            axis: float(translation[row, axis_i])
            for axis_i, axis in enumerate(_ROOT_TRANSLATION_KEYS)
        }
        pose[MOTION_ROOT_ROTATION_KEY] = {
            axis: float(degrees_rotation[row, axis_i])
            for axis_i, axis in enumerate(_ROOT_ROTATION_KEYS)
        }
        out[int(frame)] = pose
    return out


def _font(size: int):
    for name in ("arial.ttf", "segoeui.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    cell = Image.new("RGB", size, (18, 18, 22))
    rgba = image.convert("RGBA")
    scale = min(size[0] / rgba.width, size[1] / rgba.height)
    width = max(1, int(rgba.width * scale))
    height = max(1, int(rgba.height * scale))
    resized = rgba.resize((width, height), Image.Resampling.BILINEAR)
    x = (size[0] - width) // 2
    y = (size[1] - height) // 2
    cell.paste(resized, (x, y), resized)
    return cell


def write_looped_compare_gif(
    *,
    sprite_paths: list[Path],
    before_dir: Path,
    after_dir: Path,
    frames: Sequence[int],
    out_gif: Path,
    loops: int = 3,
    cell: tuple[int, int] = (260, 300),
) -> Path:
    n = len(frames)
    if n < 1 or n != len(sprite_paths):
        raise ValueError("sprite_paths must match the cycle frame list")
    font = _font(16)
    header = 28
    width, height = cell
    panels = ("sprite", "current (open loop)", "loop temporal F+B")
    canvas_w = width * 3
    canvas_h = header + height
    images: list[Image.Image] = []
    for _ in range(int(loops)):
        for index, frame in enumerate(frames):
            canvas = Image.new("RGB", (canvas_w, canvas_h), (12, 12, 16))
            draw = ImageDraw.Draw(canvas)
            before = before_dir / f"{int(frame):02d}.png"
            after = after_dir / f"{int(frame):02d}.png"
            missing = [path for path in (sprite_paths[index], before, after) if not path.is_file()]
            if missing:
                raise FileNotFoundError(f"compare GIF missing stills: {missing}")
            cells = [
                Image.open(sprite_paths[index]),
                Image.open(before),
                Image.open(after),
            ]
            for col, (label, image) in enumerate(zip(panels, cells)):
                x0 = col * width
                draw.rectangle([x0, 0, x0 + width - 1, header - 1], fill=(28, 28, 36))
                draw.text((x0 + 8, 6), label, fill=(230, 230, 235), font=font)
                canvas.paste(_fit(image, cell), (x0, header))
                draw.text((x0 + 8, header + 6), f"f{int(frame):02d}", fill=(180, 180, 190), font=font)
            images.append(canvas)
    out_gif.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        out_gif,
        save_all=True,
        append_images=images[1:],
        duration=int(PREVIEW_GIF_FRAME_MS),
        loop=0,
        optimize=False,
    )
    return out_gif


def raster_pose_pair(
    *,
    payload: Mapping[str, Any],
    mesh: Path,
    frames: Sequence[int],
    before_poses: Mapping[int, Mapping[str, Any]],
    after_poses: Mapping[int, Mapping[str, Any]],
    before_dir: Path,
    after_dir: Path,
) -> None:
    import torch
    from nvdiffrast_local import ensure_local_nvdiffrast
    from roc_gpu_cascade_experiment import GpuCascadeExperiment

    camera = payload.get("cameraFitPath")
    if not camera:
        raise ValueError("clip result has no cameraFitPath")
    config_mapping = payload.get("config")
    if not isinstance(config_mapping, Mapping):
        raise ValueError("clip result has no config")
    ensure_local_nvdiffrast(required=True)
    config = replace(
        gpu_config_for_preview(config_mapping),
        root_search_frame=None,
        temporal_loop_wrap_enabled=False,
    )
    experiment = GpuCascadeExperiment(
        src_glb=Path(mesh).resolve(),
        camera_fit=Path(str(camera)).resolve(),
        target_frame_dir=target_frame_dir_from_clip(payload),
        frame_indices=tuple(int(frame) for frame in frames),
        config=config,
    )
    for poses, dest in ((before_poses, before_dir), (after_poses, after_dir)):
        dest.mkdir(parents=True, exist_ok=True)
        bone_vectors, root_translation, root_rotation = experiment._initial_pose_tensors(poses)
        bone_vectors = experiment._bounded_bone_vectors(bone_vectors)
        with torch.no_grad():
            rgb, _alpha, _depth = experiment.exact_triangle_rgb(
                bone_vectors,
                root_translation,
                root_rotation,
                bone_mask=experiment.active_node_mask,
            )
        for position, frame in enumerate(frames):
            rgb_array = np.rint(
                rgb[position].clamp(0.0, 1.0).detach().cpu().numpy() * 255.0
            ).astype(np.uint8)
            Image.fromarray(rgb_array, "RGB").save(
                dest / f"{int(frame):02d}.png", format="PNG", compress_level=0
            )


def process_clip(
    *,
    unit: str,
    contract: str,
    rollout: Path,
    out_root: Path,
    raster: bool,
) -> dict[str, Any]:
    sidecar = _load_json(rollout / "units" / unit / "clips" / f"{contract}.json")
    role = lifecycle_role_for_clip_name(contract)
    if role != "cycle":
        raise ValueError(f"{contract} role is {role!r}; circular wrap is cycle-only")
    payload_path = Path(str(sidecar["clipResultPath"]))
    payload = _load_json(payload_path)
    require_pose_units_degrees(payload, source=str(payload_path))
    poses = _sliced_cycle_poses(payload, sidecar)
    if len(poses) < 2:
        raise ValueError(f"{unit} {contract} has fewer than two poses; wrap is undefined")
    bone_names = _pose_bone_names({str(frame): pose for frame, pose in poses.items()})
    frames, bones, translation, rotation = _pack(poses, bone_names)
    new_bones, new_translation, new_rotation, report = apply_circular_temporal_clip(
        bones,
        translation,
        rotation,
        config=CircularTemporalConfig(),
        wrap=True,
    )
    after_poses = _unpack(frames, bone_names, new_bones, new_translation, new_rotation)
    clip_out = out_root / unit / contract
    clip_out.mkdir(parents=True, exist_ok=True)
    (clip_out / "after_poses.json").write_text(
        json.dumps(
            {
                "labSid": unit,
                "contractName": contract,
                "sourceClipResult": str(payload_path).replace("\\", "/"),
                "frames": [int(frame) for frame in frames],
                "circularTemporal": report,
                "poses": {str(frame): pose for frame, pose in after_poses.items()},
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    sprite_paths = _sprite_paths_for_frames(payload, frames)
    gif_path = clip_out / "compare_loop.gif"
    raster_note = "skipped"
    if raster:
        raster_pose_pair(
            payload=payload,
            mesh=Path(str(sidecar["source"])),
            frames=frames,
            before_poses=poses,
            after_poses=after_poses,
            before_dir=clip_out / "raster_before",
            after_dir=clip_out / "raster_after",
        )
        write_looped_compare_gif(
            sprite_paths=sprite_paths,
            before_dir=clip_out / "raster_before",
            after_dir=clip_out / "raster_after",
            frames=frames,
            out_gif=gif_path,
            loops=3,
        )
        raster_note = str(gif_path).replace("\\", "/")
    result = {
        "labSid": unit,
        "contractName": contract,
        "frames": [int(frame) for frame in frames],
        "circularTemporal": report,
        "gif": raster_note,
        "proofTier": "generated-artifact",
    }
    (clip_out / "report.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rollout-dir", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-raster", action="store_true")
    args = parser.parse_args(argv)

    lock_path = None
    if not args.no_raster:
        from gpu_cascade_batch_lock import (
            acquire_cascade_batch_lock,
            global_cascade_batch_lock_path,
            release_cascade_batch_lock,
        )

        lock_path = acquire_cascade_batch_lock(global_cascade_batch_lock_path(ROOT))
    try:
        reports = []
        for unit, contract in PILOTS:
            print(f"circular temporal {unit} {contract}", flush=True)
            reports.append(
                process_clip(
                    unit=unit,
                    contract=contract,
                    rollout=args.rollout_dir,
                    out_root=args.out,
                    raster=not args.no_raster,
                )
            )
            print(json.dumps(reports[-1]["circularTemporal"], indent=2), flush=True)
        index = {
            "schema": "circular_temporal_compare.v1",
            "clips": reports,
            "proofTier": "generated-artifact",
            "mutatedLivePayloads": False,
        }
        args.out.mkdir(parents=True, exist_ok=True)
        (args.out / "index.json").write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"gifs": [row["gif"] for row in reports]}, indent=2), flush=True)
        return 0
    finally:
        if lock_path is not None:
            from gpu_cascade_batch_lock import release_cascade_batch_lock

            release_cascade_batch_lock(lock_path)


if __name__ == "__main__":
    raise SystemExit(main())
