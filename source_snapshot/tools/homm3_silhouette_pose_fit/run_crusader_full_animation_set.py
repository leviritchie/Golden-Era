#!/usr/bin/env python3
"""Fit every authentic Crusader DEF group with the notebook configuration.

This is the batch counterpart to the executed semantic-hybrid notebook.  It
extracts literal keyword values from that notebook's ``RocHybridConfig`` call,
materializes only the original VCMI/DEF frames, and replaces the deprecated
Crusader mesh with the audited Meshy smart-rig output.  The optimizer itself is
not reimplemented here: every clip still goes through initialize() and
run_clip_pilot().

By default, each sparse clip is resampled to 60 fps with the selected
quaternion interpolation method.  The final review video is a single
sprite-versus-mesh sequence covering all authentic DEF groups in group order.
``--fit-only`` is an explicit dataset-scale mode: it fits and records the
original sparse poses, but does not interpolate, render, or retain review
frames.  This keeps review generation separate from the expensive fitting
pass while preserving the existing review-producing behavior by default.
"""
from __future__ import annotations

import argparse
import ast
import gc
import hashlib
import json
import os
import re
import sys
import time
from dataclasses import asdict, fields, replace
from pathlib import Path
from typing import Any, Mapping

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = ROOT / "tools/homm3_silhouette_pose_fit"
NOTEBOOK = TOOL / "roc_chromatic_single_bone_match.ipynb"
MESHY_SMART_RIG = ROOT / "artifacts/meshy_downloads/h3_crusader_smartrigged.glb"
MESHY_RIGIDIZED = ROOT / "artifacts/meshy_downloads/h3_crusader_smartrigged_rigidized.glb"
MESHY_REPORT = ROOT / "artifacts/meshy_downloads/meshy_rigidization_report.json"
DEFAULT_OUT = ROOT / "artifacts/crusader_semantic_full_set_smartrig"
DEFAULT_BLENDER = Path(r"V:/Games/actionmesh/tools/blender-3.5.1/blender.exe")
DEFAULT_METHOD = "quaternion_smoothstep"
DEFAULT_FPS = 60
SOURCE_FPS = 12
SAMPLES_PER_INTERVAL = 5
MOTION_ROOT_KEY = "__motion_root__"
FINAL_FRAME_SIZE = (960, 480)


def _ensure_hf_token() -> None:
    """Load the user-scoped token into this process without printing it."""

    if os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN"):
        return
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
                token, _ = winreg.QueryValueEx(key, "HF_TOKEN")
        except (FileNotFoundError, OSError):
            token = ""
        if token:
            os.environ["HF_TOKEN"] = str(token)
    if not (os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACE_HUB_TOKEN")):
        raise RuntimeError(
            "The notebook enables DINOv3, but this process has no HF_TOKEN. "
            "Set the user-scoped HF_TOKEN and start a fresh Python process."
        )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value


def _json_sha256(value: Any) -> str:
    payload = json.dumps(_json_safe(value), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_fingerprint(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        return {"path": str(path), "exists": False}
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size": int(stat.st_size),
        "sha256": _sha256(path),
    }


def _directory_fingerprint(path: Path, *, suffix: str = ".png") -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        return {"path": str(path), "exists": False, "count": 0, "sha256": None}
    entries = []
    for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
        if not child.is_file() or child.suffix.lower() != suffix.lower():
            continue
        entries.append((child.name, _file_fingerprint(child)))
    return {
        "path": str(path),
        "exists": True,
        "count": len(entries),
        "sha256": _json_sha256(entries),
    }


def _clip_input_fingerprint(
    *,
    unit_name: str,
    animation_name: str,
    mesh: Path,
    pilot_dir: Path,
    camera_fit: Path,
    config: Any,
) -> dict[str, Any]:
    """Identify every file/config input that makes a fitted clip reproducible."""

    return {
        "unit": str(unit_name),
        "animation": str(animation_name),
        "mesh": _file_fingerprint(mesh),
        "cameraFit": _file_fingerprint(camera_fit),
        "sourceManifest": _file_fingerprint(pilot_dir / "frames_ground_truth" / "original_frames.json"),
        "sourceFrames": _directory_fingerprint(pilot_dir / "frames_ground_truth"),
        "shadowCulledFrames": _directory_fingerprint(
            pilot_dir / "frames_ground_truth_shadow_culled"
        ),
        "configSha256": _json_sha256(asdict(config)),
    }


def _config_call_source(notebook: Path) -> str:
    payload = json.loads(notebook.read_text(encoding="utf-8"))
    for cell in payload.get("cells", []):
        source = "".join(cell.get("source", []))
        if "CONFIG = RocHybridConfig(" in source:
            return source
    raise RuntimeError(f"RocHybridConfig call not found in notebook: {notebook}")


def _literal_config_kwargs(
    notebook: Path,
    *,
    require_dino: bool = True,
) -> dict[str, Any]:
    """Extract the notebook's literal config overrides without executing widgets."""

    source = _config_call_source(notebook)
    tree = ast.parse(source, filename=str(notebook))
    call = None
    def _call_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return node.attr
        return None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "CONFIG" for target in node.targets):
            continue
        if not isinstance(node.value, ast.Call):
            continue
        if _call_name(node.value.func) != "RocHybridConfig":
            continue
        call = node.value
        break
    if call is None:
        raise RuntimeError(f"CONFIG assignment is not a RocHybridConfig call: {notebook}")

    values: dict[str, Any] = {}
    dynamic: dict[str, str] = {}
    for keyword in call.keywords:
        if keyword.arg is None:
            continue
        try:
            values[keyword.arg] = ast.literal_eval(keyword.value)
        except (ValueError, TypeError, SyntaxError):
            dynamic[keyword.arg] = ast.unparse(keyword.value)

    # The current notebook deliberately switches this conditional on after the
    # user authenticated DINOv3.  Keep that explicit choice rather than
    # silently falling back to the global SigLIP encoder in a batch process.
    dino_toggle = re.search(r"^\s*USE_DINOV3_DENSE\s*=\s*(True|False)\b", source, flags=re.MULTILINE)
    if require_dino and (dino_toggle is None or dino_toggle.group(1) != "True"):
        raise RuntimeError(
            "This full-set runner requires the notebook's USE_DINOV3_DENSE=True "
            "configuration; refusing to guess or silently switch dense encoders."
        )
    if "semantic_dense_model_id" in dynamic:
        model_id = "facebook/dinov3-vits16-pretrain-lvd1689m"
        if "DINO_V3_MODEL_ID" in source:
            values["semantic_dense_model_id"] = model_id
        else:
            raise RuntimeError(
                "Notebook semantic_dense_model_id is dynamic, but its DINOv3 source "
                "declaration was not found; refusing to guess."
            )

    # These are intentionally supplied per choice below.  The notebook gets
    # them from ASSET_PICKER.config_overrides(), not from literal syntax.
    for key in ("src_glb", "meshy_rigidization_report", "unit_name", "animation_name", "pilot_dir", "camera_fit_path", "frame_indices"):
        values.pop(key, None)
        dynamic.pop(key, None)
    values["match_dir_name"] = values.get("match_dir_name", "crusader_smartrig_full_set")
    return values


def _load_runtime_modules():
    if str(TOOL) not in sys.path:
        sys.path.insert(0, str(TOOL))
    from roc_pose_interpolation import interpolate_clip, write_pose_artifact
    from roc_semantic_hybrid_experiment import RocHybridConfig, initialize, run_clip_pilot
    import roc_semantic_hybrid_widgets as widgets

    return RocHybridConfig, initialize, run_clip_pilot, widgets, interpolate_clip, write_pose_artifact


def _notebook_config(
    RocHybridConfig: type,
    kwargs: dict[str, Any],
    *,
    notebook: Path | None = None,
):
    valid = {field.name for field in fields(RocHybridConfig)}
    unknown = sorted(set(kwargs) - valid)
    if unknown:
        raise TypeError(
            "Notebook contains config fields that the current source does not expose: "
            + ", ".join(unknown)
        )
    config = RocHybridConfig(root=ROOT, **kwargs)
    if notebook is None:
        return config
    from roc_semantic_hybrid_settings_presets import (
        apply_settings_override,
        parse_settings_override_assignment,
    )

    source = _config_call_source(notebook)
    return apply_settings_override(config, parse_settings_override_assignment(source))


def _authentic_group_ids() -> tuple[int, ...]:
    """Read group ids from the extracted CCRUSD.def frame inventory."""

    stage_report = ROOT / "artifacts/crusader_pose_pipeline/source_frames/stage_report.json"
    payload = json.loads(stage_report.read_text(encoding="utf-8"))
    frames = payload.get("nnMeta", {}).get("frames", [])
    group_ids: set[int] = set()
    for name in frames:
        match = re.match(r"^(\d+)_\d+\.png$", str(name))
        if match:
            group_ids.add(int(match.group(1)))
    if not group_ids:
        raise RuntimeError(f"no authentic DEF group frames found in {stage_report}")
    return tuple(sorted(group_ids))


def _group_id(animation_name: str) -> int | None:
    match = re.search(r"_g(\d+)$", str(animation_name), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _select_crusader_choices(widgets, group_ids: tuple[int, ...]):
    choices = [
        choice
        for choice in widgets.discover_asset_choices(ROOT)
        if choice.unit_sid == "h3_crusader" and _group_id(choice.animation_name) in group_ids
    ]
    by_group = {_group_id(choice.animation_name): choice for choice in choices}
    missing = [group for group in group_ids if group not in by_group]
    if missing:
        raise RuntimeError(
            "authentic Crusader group(s) are absent from the source picker: "
            + ", ".join(str(group) for group in missing)
        )
    ordered = [by_group[group] for group in group_ids]
    for choice in ordered:
        source = str(choice.source_label).lower()
        if "rife" in source:
            raise RuntimeError(f"RIFE source rejected for {choice.choice_id}: {choice.source_label}")
    return ordered


def _prepare_smartrig() -> None:
    for path in (MESHY_SMART_RIG, MESHY_RIGIDIZED, MESHY_REPORT):
        if not path.is_file():
            raise FileNotFoundError(f"required current Meshy smart-rig artifact is missing: {path}")
    report = json.loads(MESHY_REPORT.read_text(encoding="utf-8"))
    if report.get("status") != "pass" or report.get("armatureAuthority") != "meshy_auto_rig":
        raise RuntimeError(
            "current Crusader Meshy rigidization report is not a passing Meshy-armature audit: "
            + str({"status": report.get("status"), "armatureAuthority": report.get("armatureAuthority")})
        )
    output = Path(str(report.get("output", ""))).resolve()
    if output != MESHY_RIGIDIZED.resolve():
        raise RuntimeError(f"Meshy report output does not match current rigidized asset: {output}")
    if report.get("outputSha256") and _sha256(MESHY_RIGIDIZED) != report["outputSha256"]:
        raise RuntimeError("current rigidized Crusader GLB does not match meshy_rigidization_report.json")


def _materialize_choice(widgets, choice):
    runtime_dir, camera_fit = widgets._materialize_choice(choice)
    manifest = runtime_dir / "frames_ground_truth" / "original_frames.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    provenance = str(payload.get("provenance", "")).lower()
    if payload.get("sourceKind") != "vcmi_def" or "no rife interpolation" not in provenance:
        raise RuntimeError(f"source-frame provenance failed for {choice.choice_id}: {manifest}")
    if int(payload.get("frameCount", -1)) != len(choice.frame_indices):
        raise RuntimeError(f"source-frame count mismatch for {choice.choice_id}: {manifest}")
    return runtime_dir, camera_fit, manifest


def _materialize_choice_for_run(widgets, choice):
    """Materialize a picker choice without crossing source-frame lanes.

    The generic full-set runner also consumes this module's shared helpers, but
    authentic DEF choices intentionally reject the legacy materializer.  Keep
    that distinction in one place so a future batch entry point cannot silently
    turn original DEF plates into the deprecated pipeline source.
    """
    if choice.source_kind == "authentic_def":
        root = Path(getattr(widgets, "root", ROOT))
        return widgets._materialize_def_choice(root, choice)
    runtime_dir, camera_fit = widgets._materialize_choice(choice)
    source_manifest = runtime_dir / "frames_ground_truth" / "original_frames.json"
    if not source_manifest.is_file() and getattr(choice, "source_label", ""):
        source_manifest = Path(choice.source_label)
    return runtime_dir, camera_fit, source_manifest


def _black_rgb(path: Path) -> Image.Image:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    background.alpha_composite(rgba)
    return background.convert("RGB")


def _font() -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("arial.ttf", 18)
    except OSError:
        return ImageFont.load_default()


def _comparison_frame(target: Image.Image, render: Image.Image, label: str, scale: float = 0.5) -> Image.Image:
    target_w = max(1, int(round(target.width * scale)))
    target_h = max(1, int(round(target.height * scale)))
    render_w = max(1, int(round(render.width * scale)))
    render_h = max(1, int(round(render.height * scale)))
    header = 30
    height = max(target_h, render_h) + header
    sheet = Image.new("RGB", (target_w + render_w + 4, height), (0, 0, 0))
    font = _font()
    draw = ImageDraw.Draw(sheet)
    for x, image, width, height_value, title in (
        (0, target, target_w, target_h, "sprite"),
        (target_w + 4, render, render_w, render_h, "mesh"),
    ):
        resized = ImageOps.contain(image, (width, height_value), method=Image.Resampling.LANCZOS)
        sheet.paste(resized, (x + (width - resized.width) // 2, header + (height_value - resized.height) // 2))
        draw.text((x + 8, 7), title, fill=(235, 235, 235), font=font)
    draw.line((target_w + 1, 0, target_w + 1, height), fill=(80, 80, 80), width=2)
    draw.text((8, height - 22), label, fill=(255, 205, 80), font=font)
    return sheet


def _normalize_final_frame(frame: Image.Image) -> Image.Image:
    """Put every source raster on one fixed canvas for video encoding."""

    canvas = Image.new("RGB", FINAL_FRAME_SIZE, (0, 0, 0))
    contained = ImageOps.contain(frame, FINAL_FRAME_SIZE, method=Image.Resampling.LANCZOS)
    canvas.paste(
        contained,
        ((FINAL_FRAME_SIZE[0] - contained.width) // 2, (FINAL_FRAME_SIZE[1] - contained.height) // 2),
    )
    return canvas


def _write_mp4(frames: list[Image.Image], path: Path, fps: int) -> None:
    if not frames:
        raise RuntimeError("cannot encode an empty review clip")
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = frames[0].size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), int(fps), (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"OpenCV could not open MP4 writer: {path}")
    try:
        for frame in frames:
            writer.write(cv2.cvtColor(np.asarray(frame), cv2.COLOR_RGB2BGR))
    finally:
        writer.release()


def _write_gif(frames: list[Image.Image], path: Path, fps: int) -> None:
    if not frames:
        raise RuntimeError("cannot encode an empty review GIF")
    path.parent.mkdir(parents=True, exist_ok=True)
    small = [frame.resize((max(1, frame.width // 2), max(1, frame.height // 2)), Image.Resampling.BILINEAR) for frame in frames]
    small[0].save(path, save_all=True, append_images=small[1:], duration=max(1, round(1000 / fps)), loop=0, optimize=False)


def _write_sparse_pose_artifact(
    path: Path,
    poses: list[Mapping[str, Any]],
    *,
    source_metadata: Mapping[str, Any],
    fps: int,
) -> None:
    """Write fitted source-frame poses without claiming interpolation occurred."""

    source_indices = list(source_metadata.get("sourceFrameIndices", []))
    if len(source_indices) != len(poses):
        raise ValueError(
            "sparse pose artifact requires one pose per source frame: "
            f"{len(poses)} poses for {len(source_indices)} source indices"
        )
    payload = {
        "interpolationApplied": False,
        "sourceFrameIndices": source_indices,
        "sourceFrameCount": int(len(source_indices)),
        "outputFrameCount": int(len(poses)),
        "outputFps": int(fps),
        "source": dict(source_metadata),
        "poses": {
            str(frame): dict(pose)
            for frame, pose in zip(source_indices, poses)
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), indent=2) + "\n", encoding="utf-8")


def _load_sparse_pose_result(path: Path) -> dict[str, Any]:
    """Adapt a fit-only artifact to the existing review renderer contract."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("interpolationApplied") is not False:
        raise ValueError(f"sparse review input is not explicitly non-interpolated: {path}")
    source = payload.get("source") or {}
    frame_indices = [int(value) for value in payload.get("sourceFrameIndices", source.get("sourceFrameIndices", []))]
    raw_poses = payload.get("poses")
    if not isinstance(raw_poses, dict) or not frame_indices:
        raise ValueError(f"sparse pose artifact is missing source frames or poses: {path}")
    keyed = {int(key): value for key, value in raw_poses.items()}
    if set(keyed) != set(frame_indices):
        if len(keyed) != len(frame_indices):
            raise ValueError(f"sparse pose/frame count mismatch: {path}")
        keyed = {
            frame: keyed[key]
            for frame, key in zip(frame_indices, sorted(keyed))
        }
    return {
        "config": {"frameIndices": tuple(frame_indices)},
        "poses": keyed,
        "objective": payload.get("objective"),
        "evaluations": payload.get("evaluations"),
        "accepted": payload.get("accepted"),
        "sourcePoseArtifact": str(Path(path).resolve()),
    }


def _render_clip(
    *,
    experiment,
    result: dict[str, Any],
    choice,
    out_dir: Path,
    method: str,
    fps: int,
    interpolate_clip,
    write_pose_artifact,
    global_frames: list[Image.Image] | None,
    fit_only: bool = False,
    mesh_path: Path | None = None,
    unit_name: str | None = None,
) -> dict[str, Any]:
    frames = [int(frame) for frame in result.get("config", {}).get("frameIndices", ())]
    if not frames:
        frames = sorted(int(frame) for frame in result["poses"])
    pose_map = result["poses"]
    poses = [pose_map[frame] if frame in pose_map else pose_map[str(frame)] for frame in frames]
    resolved_mesh = Path(mesh_path or MESHY_RIGIDIZED).resolve()
    resolved_unit = str(unit_name or getattr(choice, "unit_name", "crusader"))
    out_dir.mkdir(parents=True, exist_ok=True)
    provenance = {
        "unit": resolved_unit,
        "animation": choice.animation_name,
        "choiceId": choice.choice_id,
        "mesh": str(resolved_mesh),
        "meshSha256": _sha256(resolved_mesh),
        "sourceFrameDir": str((choice.pilot_dir / "frames_ground_truth").resolve()),
        "sourceFrameIndices": frames,
        "sourceKind": "vcmi_def",
        "interpolationMethod": None if fit_only else method,
        "sourceFps": SOURCE_FPS,
        "outputFps": SOURCE_FPS if fit_only else fps,
        "samplesPerInterval": 1 if fit_only else SAMPLES_PER_INTERVAL,
        "loop": True,
        "fitOnly": bool(fit_only),
        "interpolationApplied": not fit_only,
    }

    if fit_only:
        pose_path = out_dir / "clip_poses_sparse.json"
        _write_sparse_pose_artifact(pose_path, poses, source_metadata=provenance, fps=SOURCE_FPS)
        return {
            "animation": choice.animation_name,
            "choiceId": choice.choice_id,
            "group": _group_id(choice.animation_name),
            "reviewMode": "fit_only",
            "sourceFrameCount": len(frames),
            "sourceFrameIndices": frames,
            "outputFrameCount": len(poses),
            "outputFps": SOURCE_FPS,
            "poseArtifact": str(pose_path),
            "interpolationApplied": False,
            "reviewFramesRetained": False,
            "clipObjective": result.get("objective"),
            "clipEvaluations": result.get("evaluations"),
            "clipAccepted": result.get("accepted"),
        }

    interpolated = interpolate_clip(poses, method=method, samples_per_interval=SAMPLES_PER_INTERVAL, loop=True)
    pose_path = out_dir / "clip_poses.json"
    write_pose_artifact(
        pose_path,
        interpolated,
        method=method,
        source_metadata=provenance,
        samples_per_interval=SAMPLES_PER_INTERVAL,
        loop=True,
        fps=fps,
    )
    (out_dir / "clip_poses.provenance.json").write_text(json.dumps(_json_safe(provenance), indent=2) + "\n", encoding="utf-8")

    keyframe_dir = out_dir / "keyframes"
    interp_dir = out_dir / "frames_60fps"
    keyframe_dir.mkdir(parents=True, exist_ok=True)
    interp_dir.mkdir(parents=True, exist_ok=True)
    worker = experiment.namespace.get("worker")
    if worker is None:
        raise RuntimeError("semantic experiment has no persistent Blender worker")
    target_dir = choice.pilot_dir / "frames_ground_truth_shadow_culled"
    local_frames: list[Image.Image] = []
    for index, pose in enumerate(poses):
        worker.request({"cmd": "set_pose", "angles": pose})
        keyframe_path = keyframe_dir / f"frame_{frames[index]:02d}.png"
        response = worker.request({"cmd": "save_render", "out": str(keyframe_path)})
        if not response.get("ok") or not keyframe_path.is_file():
            raise RuntimeError({"stage": "keyframe_render", "animation": choice.animation_name, "frame": frames[index], "response": response})

    for index, pose in enumerate(interpolated):
        worker.request({"cmd": "set_pose", "angles": pose})
        render_path = interp_dir / f"frame_{index:04d}.png"
        response = worker.request({"cmd": "save_render", "out": str(render_path)})
        if not response.get("ok") or not render_path.is_file():
            raise RuntimeError({"stage": "interpolated_render", "animation": choice.animation_name, "frame": index, "response": response})
        source_index = (index // SAMPLES_PER_INTERVAL) % len(frames)
        target_path = target_dir / f"{frames[source_index]:02d}.png"
        target = _black_rgb(target_path)
        render = _black_rgb(render_path)
        sheet = _comparison_frame(target, render, f"{choice.animation_name}  source {frames[source_index]:02d}  output {index:04d}")
        local_frames.append(sheet)
        if global_frames is not None:
            global_frames.append(_normalize_final_frame(sheet))
        target.close()
        render.close()
        if (index + 1) % 25 == 0 or index + 1 == len(interpolated):
            print(f"{choice.animation_name}: rendered {index + 1}/{len(interpolated)} interpolated frames", flush=True)
    gif_path = out_dir / f"{choice.animation_name}_{fps}fps.gif"
    mp4_path = out_dir / f"{choice.animation_name}_{fps}fps.mp4"
    _write_gif(local_frames, gif_path, fps)
    _write_mp4(local_frames, mp4_path, fps)
    for image in local_frames:
        image.close()
    return {
        "animation": choice.animation_name,
        "choiceId": choice.choice_id,
        "group": _group_id(choice.animation_name),
        "sourceFrameCount": len(frames),
        "sourceFrameIndices": frames,
        "outputFrameCount": len(interpolated),
        "reviewMode": "interpolated",
        "outputFps": fps,
        "poseArtifact": str(pose_path),
        "frames60fps": str(interp_dir),
        "targetFrameDir": str(target_dir),
        "gif": str(gif_path),
        "mp4": str(mp4_path),
        "clipObjective": result.get("objective"),
        "clipEvaluations": result.get("evaluations"),
        "clipAccepted": result.get("accepted"),
    }


def _build_config(base, choice, runtime_dir: Path, camera_fit: Path):
    return replace(
        base,
        src_glb=MESHY_RIGIDIZED,
        meshy_rigidization_report=MESHY_REPORT,
        require_meshy_rigidization=True,
        unit_name="crusader",
        animation_name=choice.animation_name,
        pilot_dir=runtime_dir,
        camera_fit_path=camera_fit,
        frame_indices=tuple(choice.frame_indices),
        match_dir_name="crusader_smartrig_full_set",
    )


def _effective_base_config(base):
    """Return the shared config snapshot after the batch mesh substitution."""

    return replace(
        base,
        src_glb=MESHY_RIGIDIZED,
        meshy_rigidization_report=MESHY_REPORT,
        require_meshy_rigidization=True,
        unit_name="crusader",
        match_dir_name="crusader_smartrig_full_set",
    )


def _load_existing_comparison_frames(clip_summary: Mapping[str, Any]) -> list[Image.Image]:
    """Load a completed clip's saved review frames for a resumed final assembly."""

    animation = str(clip_summary.get("animation", "clip"))
    frame_dir = Path(str(clip_summary.get("frames60fps", "")))
    target_dir = Path(str(clip_summary.get("targetFrameDir", "")))
    if not frame_dir.is_dir() or not target_dir.is_dir():
        raise RuntimeError(f"completed clip cannot be resumed; review inputs are missing: {animation}")
    source_frames = [int(value) for value in clip_summary.get("sourceFrameIndices", ())]
    if not source_frames:
        raise RuntimeError(f"completed clip has no source frame indices: {animation}")
    output: list[Image.Image] = []
    for index, render_path in enumerate(sorted(frame_dir.glob("frame_*.png"))):
        source_index = source_frames[(index // SAMPLES_PER_INTERVAL) % len(source_frames)]
        target = _black_rgb(target_dir / f"{source_index:02d}.png")
        render = _black_rgb(render_path)
        output.append(_normalize_final_frame(_comparison_frame(target, render, f"{animation}  source {source_index:02d}  output {index:04d}")))
        target.close()
        render.close()
    return output


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notebook", type=Path, default=NOTEBOOK)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--method", choices=("euler_linear", "quaternion_slerp", "quaternion_smoothstep"), default=DEFAULT_METHOD)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--limit", type=int, default=0, help="run only the first N authentic groups; 0 means all")
    parser.add_argument("--no-resume", action="store_true", help="rerun clips even when a matching completed manifest exists")
    parser.add_argument("--dry-run", action="store_true", help="print the exact mesh/config/group plan without starting Blender")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--assemble-only",
        action="store_true",
        help="rebuild the aggregate GIF/MP4 from completed interpolated clip artifacts without fitting",
    )
    mode_group.add_argument(
        "--fit-only",
        action="store_true",
        help=(
            "fit and save sparse original-frame poses only; do not interpolate, render review frames, "
            "or create GIF/MP4 output"
        ),
    )
    mode_group.add_argument(
        "--review-only",
        action="store_true",
        help="render/interpolate existing clip_poses_sparse.json artifacts without rerunning the optimizer",
    )
    parser.add_argument(
        "--no-persistent-blender-workers",
        action="store_true",
        help=(
            "start and close Blender workers for each clip instead of reusing "
            "the worker pool across this creature's animation set"
        ),
    )
    parser.add_argument(
        "--release-cuda-between-clips",
        action="store_true",
        help="opt into gc/torch.cuda.empty_cache between clips when diagnosing memory pressure",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    notebook = args.notebook.resolve()
    out_root = args.out.resolve()
    if args.fps != 60:
        raise ValueError("this delivery lane is defined at 60 fps")
    if not notebook.is_file():
        raise FileNotFoundError(notebook)
    _prepare_smartrig()
    _ensure_hf_token()
    RocHybridConfig, initialize, run_clip_pilot, widgets, interpolate_clip, write_pose_artifact = _load_runtime_modules()
    base_kwargs = _literal_config_kwargs(notebook)
    base = _notebook_config(RocHybridConfig, base_kwargs, notebook=notebook)
    effective_base = _effective_base_config(base)
    from roc_semantic_hybrid_settings_presets import (
        describe_settings_override,
        parse_settings_override_assignment,
    )

    settings_override = parse_settings_override_assignment(_config_call_source(notebook))
    group_ids = _authentic_group_ids()
    choices = _select_crusader_choices(widgets, group_ids)
    if args.limit:
        choices = choices[: args.limit]
    print("Notebook config:", notebook)
    print("Notebook sha256:", _sha256(notebook))
    print(
        "Settings override:",
        settings_override,
        f"({describe_settings_override(settings_override)})",
    )
    print("Meshy source:", MESHY_SMART_RIG)
    print("Meshy audited output:", MESHY_RIGIDIZED)
    print("Meshy report:", MESHY_REPORT)
    print("Authentic Crusader groups:", [f"g{group:02d}" for group in group_ids])
    print("Run groups:", [choice.animation_name for choice in choices])
    print("Run mode:", "fit-only" if args.fit_only else "review-only" if args.review_only else "review", flush=True)
    if args.fit_only:
        print("Interpolation: disabled; fitting original source frames only", flush=True)
    else:
        print("Interpolation:", args.method, "source fps:", SOURCE_FPS, "output fps:", args.fps, "samples:", SAMPLES_PER_INTERVAL)
    print("Config overrides copied from notebook:", len(base_kwargs))
    if args.dry_run:
        for choice in choices:
            print(json.dumps({"choice": choice.choice_id, "frames": len(choice.frame_indices), "source": str(choice.source_label), "mesh": str(MESHY_RIGIDIZED)}, default=str))
        return 0

    if args.assemble_only:
        if args.limit:
            raise ValueError("--assemble-only requires the complete authentic group set; omit --limit")
        global_frames: list[Image.Image] = []
        summaries: list[dict[str, Any]] = []
        for choice in choices:
            clip_manifest_path = out_root / "clips" / choice.animation_name / "clip_manifest.json"
            if not clip_manifest_path.is_file():
                raise FileNotFoundError(f"completed clip manifest is missing: {clip_manifest_path}")
            summary = json.loads(clip_manifest_path.read_text(encoding="utf-8"))
            if summary.get("status") != "complete":
                raise RuntimeError(f"clip is not complete: {clip_manifest_path}")
            global_frames.extend(_load_existing_comparison_frames(summary))
            summaries.append(summary)
        final_mp4 = out_root / "crusader_all_animations_60fps_side_by_side.mp4"
        final_gif = out_root / "crusader_all_animations_60fps_side_by_side.gif"
        _write_mp4(global_frames, final_mp4, args.fps)
        _write_gif(global_frames, final_gif, args.fps)
        run_manifest_path = out_root / "run_manifest.json"
        run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8")) if run_manifest_path.is_file() else {}
        run_manifest.update(
            {
                "status": "complete",
                "finalMp4": str(final_mp4),
                "finalGif": str(final_gif),
                "totalOutputFrames": len(global_frames),
                "totalDurationSeconds": len(global_frames) / float(args.fps),
                "aggregateFrameSize": list(FINAL_FRAME_SIZE),
                "config": _json_safe(asdict(effective_base)),
                "clips": summaries,
            }
        )
        run_manifest_path.write_text(json.dumps(_json_safe(run_manifest), indent=2) + "\n", encoding="utf-8")
        for image in global_frames:
            image.close()
        print("FINAL MP4:", final_mp4)
        print("FINAL GIF:", final_gif)
        print("RUN MANIFEST:", run_manifest_path)
        return 0

    out_root.mkdir(parents=True, exist_ok=True)
    run_manifest_path = out_root / "run_manifest.json"
    run_manifest: dict[str, Any] = {
        "status": "running",
        "createdAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "notebook": str(notebook),
        "notebookSha256": _sha256(notebook),
        "meshSource": str(MESHY_SMART_RIG),
        "mesh": str(MESHY_RIGIDIZED),
        "meshSha256": _sha256(MESHY_RIGIDIZED),
        "meshyRigidizationReport": str(MESHY_REPORT),
        "meshyRigidizationReportSha256": _sha256(MESHY_REPORT),
        "armatureAuthority": "meshy_auto_rig",
        "sourceInventory": "CCRUSD.def extracted VCMI frames; no RIFE interpolation",
        "sourceFps": SOURCE_FPS,
        "outputFps": SOURCE_FPS if args.fit_only else args.fps,
        "interpolationMethod": None if args.fit_only else args.method,
        "interpolationApplied": not args.fit_only,
        "samplesPerInterval": 1 if args.fit_only else SAMPLES_PER_INTERVAL,
        "runMode": "fit_only" if args.fit_only else "review_only" if args.review_only else "review",
        "reviewFramesRetained": not args.fit_only,
        "reviewOnly": bool(args.review_only),
        "persistentBlenderWorkers": not args.no_persistent_blender_workers,
        "authenticGroupIds": group_ids,
        "config": _json_safe(asdict(effective_base)),
        "clips": [],
    }
    run_manifest_path.write_text(json.dumps(_json_safe(run_manifest), indent=2) + "\n", encoding="utf-8")
    global_frames: list[Image.Image] | None = [] if not args.fit_only else None
    experiment = None
    persistent_worker_pool = None
    try:
        for index, choice in enumerate(choices, 1):
            clip_dir = out_root / "clips" / choice.animation_name
            clip_manifest_path = clip_dir / "clip_manifest.json"
            print(f"[{index}/{len(choices)}] preparing {choice.animation_name} ({len(choice.frame_indices)} original frames)", flush=True)
            runtime_dir, camera_fit, source_manifest = _materialize_choice(widgets, choice)
            config = _build_config(base, choice, runtime_dir, camera_fit)
            input_fingerprint = _clip_input_fingerprint(
                unit_name="crusader",
                animation_name=choice.animation_name,
                mesh=MESHY_RIGIDIZED,
                pilot_dir=runtime_dir,
                camera_fit=camera_fit,
                config=config,
            )
            if not args.no_resume and clip_manifest_path.is_file():
                try:
                    existing = json.loads(clip_manifest_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    existing = None
                review_resume_ready = (
                    isinstance(existing, dict)
                    and existing.get("status") == "complete"
                    and existing.get("mesh") == str(MESHY_RIGIDIZED)
                    and existing.get("inputFingerprint") == input_fingerprint
                    and existing.get("notebookSha256") == run_manifest["notebookSha256"]
                    and Path(str(existing.get("mp4", ""))).is_file()
                )
                fit_resume_ready = (
                    isinstance(existing, dict)
                    and existing.get("status") == "complete"
                    and existing.get("reviewMode") == "fit_only"
                    and existing.get("mesh") == str(MESHY_RIGIDIZED)
                    and existing.get("inputFingerprint") == input_fingerprint
                    and existing.get("notebookSha256") == run_manifest["notebookSha256"]
                    and Path(str(existing.get("poseArtifact", ""))).is_file()
                )
                if (args.fit_only and fit_resume_ready) or (not args.fit_only and review_resume_ready):
                    print(f"[{index}/{len(choices)}] {choice.animation_name}: reusing matching completed clip", flush=True)
                    run_manifest["clips"].append(existing)
                    if global_frames is not None:
                        global_frames.extend(_load_existing_comparison_frames(existing))
                    continue

            clip_dir.mkdir(parents=True, exist_ok=True)
            started = time.perf_counter()
            experiment = initialize(
                config,
                persistent_worker_pool=(
                    None if args.no_persistent_blender_workers else persistent_worker_pool
                ),
            )
            if not args.no_persistent_blender_workers and persistent_worker_pool is None:
                persistent_worker_pool = experiment.namespace.get("worker_pool")
                if persistent_worker_pool is None:
                    raise RuntimeError("initialized experiment did not expose a Blender worker pool")
                # The run, rather than this clip, owns the pool now. This lets
                # the next initialize() reconfigure the same worker processes.
                experiment.namespace["worker_pool_owned"] = False
            try:
                result = (
                    _load_sparse_pose_result(clip_dir / "clip_poses_sparse.json")
                    if args.review_only
                    else run_clip_pilot(experiment)
                )
                clip_summary = _render_clip(
                    experiment=experiment,
                    result=result,
                    choice=choice,
                    out_dir=clip_dir,
                    method=args.method,
                    fps=args.fps,
                    interpolate_clip=interpolate_clip,
                    write_pose_artifact=write_pose_artifact,
                    global_frames=global_frames,
                    fit_only=args.fit_only,
                )
            finally:
                experiment.close()
                experiment = None
                if args.release_cuda_between_clips:
                    gc.collect()
                    try:
                        import torch

                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except ImportError:
                        pass
            clip_summary.update(
                {
                    "status": "complete",
                    "elapsedSeconds": round(time.perf_counter() - started, 3),
                    "mesh": str(MESHY_RIGIDIZED),
                    "notebookSha256": run_manifest["notebookSha256"],
                    "sourceManifest": str(source_manifest),
                    "cameraFit": str(camera_fit),
                    "inputFingerprint": input_fingerprint,
                    "reviewOnly": bool(args.review_only),
                }
            )
            clip_manifest_path.write_text(json.dumps(_json_safe(clip_summary), indent=2) + "\n", encoding="utf-8")
            run_manifest["clips"].append(clip_summary)
            run_manifest_path.write_text(json.dumps(_json_safe(run_manifest), indent=2) + "\n", encoding="utf-8")
            output_path = clip_summary.get("mp4") or clip_summary["poseArtifact"]
            print(f"{choice.animation_name}: complete in {clip_summary['elapsedSeconds']:.1f}s -> {output_path}", flush=True)

        if args.fit_only:
            run_manifest.update(
                {
                    "status": "complete",
                    "completedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "runMode": "fit_only",
                    "reviewFramesRetained": False,
                    "fittedClipCount": len(run_manifest["clips"]),
                    "totalSourceFrames": sum(int(clip.get("sourceFrameCount", 0)) for clip in run_manifest["clips"]),
                }
            )
            run_manifest_path.write_text(json.dumps(_json_safe(run_manifest), indent=2) + "\n", encoding="utf-8")
            print("FIT-ONLY RUN MANIFEST:", run_manifest_path)
            print("No 60 fps interpolation, review rendering, GIF, or MP4 was produced.")
            return 0

        if not global_frames:
            raise RuntimeError("no clips were rendered; cannot assemble final review video")
        final_mp4 = out_root / "crusader_all_animations_60fps_side_by_side.mp4"
        final_gif = out_root / "crusader_all_animations_60fps_side_by_side.gif"
        _write_mp4(global_frames, final_mp4, args.fps)
        _write_gif(global_frames, final_gif, args.fps)
        run_manifest.update(
            {
                "status": "complete",
                "completedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "finalMp4": str(final_mp4),
                "finalGif": str(final_gif),
                "totalOutputFrames": len(global_frames),
                "totalDurationSeconds": len(global_frames) / float(args.fps),
                "aggregateFrameSize": list(FINAL_FRAME_SIZE),
            }
        )
        run_manifest_path.write_text(json.dumps(_json_safe(run_manifest), indent=2) + "\n", encoding="utf-8")
        for image in global_frames:
            image.close()
        print("FINAL MP4:", final_mp4)
        print("FINAL GIF:", final_gif)
        print("RUN MANIFEST:", run_manifest_path)
        return 0
    except Exception as exc:
        if experiment is not None:
            experiment.close()
        run_manifest["status"] = "failed"
        run_manifest["error"] = repr(exc)
        run_manifest_path.write_text(json.dumps(_json_safe(run_manifest), indent=2) + "\n", encoding="utf-8")
        raise
    finally:
        if persistent_worker_pool is not None:
            persistent_worker_pool.close()


if __name__ == "__main__":
    raise SystemExit(main())
