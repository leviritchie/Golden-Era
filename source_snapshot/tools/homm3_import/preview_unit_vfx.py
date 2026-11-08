#!/usr/bin/env python3
"""Render a unit animation and scheduled Unity effects without launching Olden Era."""

from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parents[1]
DEFAULT_SPEC = SCRIPT_DIR / "beholder_electricity_preview.json"
EDITOR_SOURCE = SCRIPT_DIR / "unity_editor" / "UnitVfxPreview.cs"
EDITOR_SOURCE_MARKER = "CODEX_GENERATED_UNIT_VFX_PREVIEW"
UNITY_DEFAULT = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe")
OUTPUT_ROOT = REPO_ROOT / "artifacts" / "unit_vfx_preview"


def _unity_queue():
    """Unity jobs go through the Unity queue (docs/unity_queue_runner.md): agents submit, not launch."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("unity_queue", REPO_ROOT / "tools" / "unity_queue" / "unity_queue.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_spec(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def validate_spec(spec: dict, project: Path) -> None:
    if spec.get("schema") != "unit_vfx_preview.v1":
        raise ValueError("expected spec schema unit_vfx_preview.v1")
    required = ("unitSid", "prefabAssetPath", "clipAssetPath", "anchorName", "effectKind")
    if any(not isinstance(spec.get(key), str) or not spec[key].strip() for key in required):
        raise ValueError("unitSid, prefabAssetPath, clipAssetPath, anchorName, and effectKind are required")
    if spec["effectKind"] not in {"electricArc", "particlePrefab"}:
        raise ValueError("effectKind must be electricArc or particlePrefab")
    if "loopClip" in spec and not isinstance(spec["loopClip"], bool):
        raise ValueError("loopClip must be a boolean")
    if "requireSkinnedMeshDeformation" in spec and not isinstance(spec["requireSkinnedMeshDeformation"], bool):
        raise ValueError("requireSkinnedMeshDeformation must be a boolean")
    if spec["unitSid"] == "h3_beholder" and spec.get("requireSkinnedMeshDeformation") is not True:
        raise ValueError("Beholder preview requires baked skinned-mesh deformation proof")
    if spec.get("requireSkinnedMeshDeformation"):
        for key, minimum, maximum in (
                ("meshDeformationThresholdRelativeToHeight", 0.005, 0.05),
                ("minimumShapeRmsRelativeToHeight", 0.002, 0.02)):
            value = spec.get(key)
            if (not isinstance(value, (int, float)) or isinstance(value, bool)
                    or not math.isfinite(value) or not minimum <= value <= maximum):
                raise ValueError(f"{key} must be between {minimum} and {maximum}")
    source_fps_value = spec.get("sourceFramesPerSecond")
    if isinstance(source_fps_value, bool):
        raise ValueError("sourceFramesPerSecond must be between 1 and 60")
    try:
        source_fps = float(source_fps_value or 0)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("sourceFramesPerSecond must be between 1 and 60") from exc
    if not math.isfinite(source_fps) or not 1 <= source_fps <= 60:
        raise ValueError("sourceFramesPerSecond must be between 1 and 60")
    if spec["effectKind"] == "particlePrefab" and (
            not isinstance(spec.get("effectPrefabAssetPath"), str) or not spec["effectPrefabAssetPath"].strip()):
        raise ValueError("particlePrefab requires effectPrefabAssetPath")
    if spec["effectKind"] == "particlePrefab":
        try:
            margin = float(spec.get("effectBoundsMarginRelativeToHeight", 0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("particlePrefab requires an effect bounds margin in (0, 4]") from exc
        if not math.isfinite(margin) or not 0 < margin <= 4:
            raise ValueError("particlePrefab requires an effect bounds margin in (0, 4]")
    try:
        duration = float(spec.get("durationSeconds", 0))
        effect_duration = float(spec.get("effectDurationSeconds", 0))
        fps = int(spec.get("fps", 0))
        width, height = int(spec.get("width", 0)), int(spec.get("height", 0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("duration, frame rate, and render dimensions must be numeric") from exc
    events = spec.get("eventTimesSeconds")
    if not (math.isfinite(duration) and math.isfinite(effect_duration)
            and 0 < duration <= 20 and 0 < effect_duration <= 5):
        raise ValueError("durationSeconds/effectDurationSeconds are outside supported limits")
    if not (1 <= fps <= 60 and width >= 128 and height >= 128 and width <= 2048 and height <= 2048):
        raise ValueError("fps or render dimensions are outside supported limits")
    if math.ceil(duration * fps) > 1200:
        raise ValueError("preview exceeds the 1200-frame limit")
    if (not isinstance(events, list) or not events
            or any(not isinstance(t, (int, float)) or isinstance(t, bool) or not math.isfinite(t)
                   for t in events)):
        raise ValueError("eventTimesSeconds must be a non-empty list of finite numbers")
    if events != sorted(events):
        raise ValueError("eventTimesSeconds must be sorted")
    if len(events) > 32:
        raise ValueError("a preview supports at most 32 scheduled effects")
    if any(t < 0 or t + effect_duration > duration + 1e-5 for t in events):
        raise ValueError("all effect events must fall within the preview duration")
    sample_times = [index / fps for index in range(math.ceil(duration * fps))]
    if any(not any(start <= sample_time < start + effect_duration for sample_time in sample_times)
           for start in events):
        raise ValueError("every effect event must overlap at least one rendered sample")
    for vector_name in ("cameraDirection", "anchorLocalOffset", "anchorViewOffsetRelativeToHeight"):
        vector = spec.get(vector_name)
        if vector_name == "cameraDirection" and vector is None:
            raise ValueError(f"{vector_name} must contain three finite numbers")
        if vector is not None and (
                not isinstance(vector, list) or len(vector) != 3
                or any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
                       for value in vector)):
            raise ValueError(f"{vector_name} must contain three finite numbers")
    try:
        padding = float(spec.get("orthographicPadding", 0))
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("orthographicPadding must be between 1 and 3") from exc
    if not math.isfinite(padding) or not 1 <= padding <= 3:
        raise ValueError("orthographicPadding must be between 1 and 3")
    if spec["effectKind"] == "electricArc":
        try:
            arc_length = float(spec.get("arcLengthRelativeToHeight", 0))
            arc_width = float(spec.get("arcWidthRelativeToHeight", 0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("electricArc geometry settings are outside supported limits") from exc
        branches = spec.get("branchCount")
        if (not math.isfinite(arc_length) or not 0 < arc_length <= 2
                or not math.isfinite(arc_width) or not 0 < arc_width <= 0.1
                or not isinstance(branches, int) or isinstance(branches, bool) or not 0 <= branches <= 8):
            raise ValueError("electricArc geometry settings are outside supported limits")
        try:
            light_intensity = float(spec.get("arcLightIntensity", 0))
            light_range = float(spec.get("arcLightRangeRelativeToHeight", 0))
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("electricArc light settings are outside supported limits") from exc
        if (isinstance(spec.get("arcLightIntensity"), bool)
                or isinstance(spec.get("arcLightRangeRelativeToHeight"), bool)
                or not math.isfinite(light_intensity) or not 0 < light_intensity <= 100
                or not math.isfinite(light_range) or not 0 < light_range <= 3):
            raise ValueError("electricArc light settings are outside supported limits")
    if (not isinstance(spec.get("candidateStatus"), str) or not spec["candidateStatus"].strip()
            or not isinstance(spec.get("effectSourceNote"), str) or not spec["effectSourceNote"].strip()):
        raise ValueError("candidateStatus and effectSourceNote provenance notes are required")
    if (not isinstance(spec.get("referenceFrames"), list) or not spec["referenceFrames"]
            or any(not isinstance(path, str) or not path.strip() for path in spec["referenceFrames"])):
        raise ValueError("referenceFrames must contain at least one visual reference")

    asset_paths = [spec["prefabAssetPath"], spec["clipAssetPath"]]
    if spec["effectKind"] == "particlePrefab":
        asset_paths.append(spec["effectPrefabAssetPath"])
    asset_paths.extend(spec.get("referenceFrames", []))
    for relative in asset_paths:
        normalized = Path(relative.replace("\\", "/"))
        if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts or normalized.parts[0] != "Assets":
            raise ValueError(f"Unity asset path must stay under Assets/: {relative}")
        if not (project / normalized).is_file():
            raise FileNotFoundError(project / normalized)


def output_directory(value: str | None) -> Path:
    if value:
        result = Path(value).resolve()
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        result = (OUTPUT_ROOT / f"beholder_electricity_{stamp}").resolve()
    try:
        result.relative_to(OUTPUT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"output must be under {OUTPUT_ROOT}") from exc
    if result.exists():
        raise FileExistsError(f"refusing to overwrite preview output: {result}")
    return result


def validate_report(spec: dict, report: dict) -> None:
    expected_frames = math.ceil(spec["durationSeconds"] * spec["fps"])
    if report.get("gameRuntimeUsed") is not False or report.get("frameCount") != expected_frames:
        raise RuntimeError("Unity preview report failed proof/frame-count checks")
    if spec.get("requireSkinnedMeshDeformation"):
        vertex_count = report.get("skinnedVertexCount")
        renderer_count = report.get("activeSkinnedRendererCount")
        renderer_paths = report.get("activeSkinnedRendererPaths")
        probe_count = report.get("meshDistanceProbeCount")
        model_height = report.get("meshModelHeight")
        normalization = report.get("meshDeformationNormalization")
        threshold = report.get("meshDeformationThreshold")
        minimum_rms = report.get("meshMinimumShapeRms")
        frames = report.get("frames")
        if (not isinstance(vertex_count, int) or isinstance(vertex_count, bool) or vertex_count <= 0
                or not isinstance(renderer_count, int) or isinstance(renderer_count, bool) or renderer_count <= 0
                or not isinstance(renderer_paths, list) or len(renderer_paths) != renderer_count
                or any(not isinstance(path, str) for path in renderer_paths)
                or not isinstance(probe_count, int) or isinstance(probe_count, bool)
                or not 4 * renderer_count <= probe_count <= min(64 * renderer_count, vertex_count)
                or not isinstance(model_height, (int, float)) or isinstance(model_height, bool)
                or not math.isfinite(model_height) or not 0.01 <= model_height <= 1000
                or normalization != "each renderer's initial baked local height"
                or not isinstance(threshold, (int, float)) or isinstance(threshold, bool)
                or not math.isfinite(threshold)
                or not math.isclose(threshold, spec["meshDeformationThresholdRelativeToHeight"],
                                    rel_tol=1e-4, abs_tol=1e-6)
                or not isinstance(minimum_rms, (int, float)) or isinstance(minimum_rms, bool)
                or not math.isfinite(minimum_rms)
                or not math.isclose(minimum_rms, spec["minimumShapeRmsRelativeToHeight"],
                                    rel_tol=1e-4, abs_tol=1e-6)
                or not isinstance(frames, list) or len(frames) != expected_frames
                or not str(report.get("meshDeformationPass", "")).startswith(
                    "Active SkinnedMeshRenderer.BakeMesh(useScale:true); per-renderer renderer-local normalized pairwise-distance signatures; rigid and transform-scale motion excluded")):
            raise RuntimeError("Unity preview report is missing baked skinned-mesh deformation proof")
        required_vertices = max(16, math.ceil(vertex_count * 0.05))
        qualifying = 0
        for index, frame in enumerate(frames):
            from_start = frame.get("meshShapeChangedVerticesFromStart")
            from_previous = frame.get("meshShapeChangedVerticesFromPrevious")
            rms_start = frame.get("meshRmsDistanceSignatureDeltaFromStart")
            rms_previous = frame.get("meshRmsDistanceSignatureDeltaFromPrevious")
            max_start = frame.get("meshMaxPerVertexDistanceSignatureDeltaFromStart")
            max_previous = frame.get("meshMaxPerVertexDistanceSignatureDeltaFromPrevious")
            if (any(not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= vertex_count
                    for value in (from_start, from_previous))
                    or any(not isinstance(value, (int, float)) or isinstance(value, bool)
                           or not math.isfinite(value) or value < 0
                           for value in (rms_start, rms_previous, max_start, max_previous))
                    or rms_start > max_start or rms_previous > max_previous):
                raise RuntimeError(f"invalid skinned shape-motion data in frame {index}")
            for changed, rms_delta, max_delta in (
                    (from_start, rms_start, max_start), (from_previous, rms_previous, max_previous)):
                consistency_slack = max(threshold, max_delta, rms_delta) * 1e-5 + 1e-7
                rms_floor = threshold * math.sqrt(changed / vertex_count)
                if ((changed == 0 and max_delta >= threshold + consistency_slack)
                        or (changed > 0 and max_delta + consistency_slack < threshold)
                        or rms_delta + consistency_slack < rms_floor
                        or max_delta > rms_delta * math.sqrt(vertex_count) + consistency_slack):
                    raise RuntimeError(f"contradictory skinned shape-motion data in frame {index}")
            if index == 0 and (from_start or from_previous or rms_start or rms_previous or max_start or max_previous):
                raise RuntimeError("first skinned frame must be the zero-motion reference")
            if (index and from_previous >= required_vertices
                    and rms_previous >= minimum_rms):
                qualifying += 1
        if qualifying < 3:
            raise RuntimeError("Beholder preview did not show mesh shape change across three attack transitions")
    if spec["effectKind"] != "electricArc":
        return
    for key in ("eventMeshLightingChangedPixels", "eventMeshBrightenedPixels", "eventMeshSurfacePixels"):
        values = report.get(key)
        if (not isinstance(values, list) or len(values) != len(spec["eventTimesSeconds"])
                or any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values)):
            raise RuntimeError(f"Unity preview report failed isolated mesh-light proof: {key}")
    for changed, brightened, surface in zip(
            report["eventMeshLightingChangedPixels"], report["eventMeshBrightenedPixels"],
            report["eventMeshSurfacePixels"]):
        required = max(16, math.ceil(surface * 0.01))
        if changed < required or brightened < required:
            raise RuntimeError("Unity preview report did not show perceptible point-light coverage on the mesh")
    if not str(report.get("meshLightingPass", "")).startswith("Unity Point Light on Standard preview materials;"):
        raise RuntimeError("Unity preview report is missing the isolated Unity point-light proof")


def unity_is_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Unity.exe"],
            check=False,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("could not verify whether Unity.exe is already running") from exc
    if result.returncode != 0:
        raise RuntimeError("tasklist could not verify whether Unity.exe is already running")
    return "Unity.exe" in result.stdout


def fit_rgba(image, box: tuple[int, int], resample, *, crop_alpha: bool = True):
    from PIL import Image

    image = image.convert("RGBA")
    if crop_alpha:
        alpha_box = image.getchannel("A").getbbox()
        if alpha_box:
            image = image.crop(alpha_box)
    if image.width == 0 or image.height == 0:
        return Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    scale = min(box[0] / image.width, box[1] / image.height)
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, resample)


def shared_alpha_bounds(images) -> tuple[int, int, int, int]:
    bounds = None
    for image in images:
        alpha_bounds = image.getchannel("A").getbbox()
        if alpha_bounds:
            if bounds is None:
                bounds = alpha_bounds
            else:
                bounds = (
                    min(bounds[0], alpha_bounds[0]),
                    min(bounds[1], alpha_bounds[1]),
                    max(bounds[2], alpha_bounds[2]),
                    max(bounds[3], alpha_bounds[3]),
                )
    if bounds is None:
        raise ValueError("authored reference frames contain no visible pixels")
    return bounds


def gif_frame_durations(fps: int, frame_count: int) -> list[int]:
    """Distribute GIF's 10 ms timing units to preserve the requested average rate."""
    previous_tick = 0
    durations = []
    for frame in range(1, frame_count + 1):
        elapsed_tick = round(frame * 100 / fps)
        durations.append(max(1, elapsed_tick - previous_tick) * 10)
        previous_tick = elapsed_tick
    return durations


def ensure_editor_script_dir(project: Path) -> Path:
    editor_dir = project / "Assets" / "Editor"
    expected = project.resolve() / "Assets" / "Editor"
    if editor_dir.resolve() != expected:
        raise ValueError(f"Unity Editor script directory resolves outside its intended project path: {editor_dir}")
    editor_dir.mkdir(parents=True, exist_ok=True)
    return editor_dir


def build_comparison(spec: dict, project: Path, output: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    report = json.loads((output / "preview_report.json").read_text(encoding="utf-8"))
    baseline_paths = sorted((output / "baseline").glob("frame_*.png"))
    effect_paths = sorted((output / "effect").glob("frame_*.png"))
    reference_paths = [project / Path(p.replace("/", os.sep)) for p in spec["referenceFrames"]]
    reference_images = [Image.open(path).convert("RGBA") for path in reference_paths]
    frame_count = int(report["frameCount"])
    if len(baseline_paths) != frame_count or len(effect_paths) != frame_count or not reference_images:
        raise RuntimeError("preview frame inventory differs from its report/spec")

    # Apply one shared crop so motion within each sequence remains screen-stable.
    reference_bounds = shared_alpha_bounds(reference_images)

    cell_w, cell_h, header_h, footer_h = 400, 450, 38, 34
    canvas_size = (cell_w * 3, header_h + cell_h + footer_h)
    background = (18, 27, 34, 255)
    effect_label = "electricity" if spec["effectKind"] == "electricArc" else "particle FX"
    headers = ("DEF g12 reference", "Beholder 3D, no FX", f"Beholder 3D + {effect_label}")
    try:
        font = ImageFont.truetype("arial.ttf", 18)
        small_font = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        font = ImageFont.load_default()
        small_font = ImageFont.load_default()

    frames = []
    out_frames = output / "comparison_frames"
    out_frames.mkdir()
    source_fps = float(spec["sourceFramesPerSecond"])
    render_fps = int(spec["fps"])
    for index in range(frame_count):
        time_seconds = index / render_fps
        reference_index = min(len(reference_paths) - 1, int(time_seconds * source_fps + 1e-6))
        base_frame = Image.open(baseline_paths[index]).convert("RGBA")
        fx_frame = Image.open(effect_paths[index]).convert("RGBA")
        source_frame = reference_images[reference_index].crop(reference_bounds)
        panel_images = [
            fit_rgba(source_frame, (cell_w - 28, cell_h - 24), Image.Resampling.NEAREST, crop_alpha=False),
            fit_rgba(base_frame, (cell_w - 28, cell_h - 24), Image.Resampling.LANCZOS, crop_alpha=False),
            fit_rgba(fx_frame, (cell_w - 28, cell_h - 24), Image.Resampling.LANCZOS, crop_alpha=False),
        ]
        canvas = Image.new("RGBA", canvas_size, background)
        draw = ImageDraw.Draw(canvas)
        for column, (label, panel) in enumerate(zip(headers, panel_images)):
            x0 = column * cell_w
            draw.rectangle((x0, 0, x0 + cell_w - 1, header_h - 1), fill=(39, 53, 63, 255))
            draw.text((x0 + 12, 9), label, font=font, fill=(226, 236, 240, 255))
            px = x0 + (cell_w - panel.width) // 2
            py = header_h + (cell_h - panel.height) // 2
            canvas.alpha_composite(panel, (px, py))
        active = any(start <= time_seconds < start + spec["effectDurationSeconds"] for start in spec["eventTimesSeconds"])
        reference_label = f"DEF frame {reference_index:02d}   |   t={time_seconds:.3f}s   |   {effect_label} {'ON' if active else 'off'}"
        draw.rectangle((0, header_h + cell_h, canvas_size[0] - 1, canvas_size[1] - 1), fill=(39, 53, 63, 255))
        draw.text((12, header_h + cell_h + 8), reference_label, font=small_font, fill=(201, 218, 225, 255))
        frame_path = out_frames / f"frame_{index:04d}.png"
        canvas.convert("RGB").save(frame_path)
        frames.append(canvas.convert("RGB"))
        base_frame.close()
        fx_frame.close()

    for reference in reference_images:
        reference.close()

    gif_path = output / "comparison.gif"
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=gif_frame_durations(render_fps, len(frames)),
        loop=0,
        disposal=2,
        optimize=False,
    )
    return gif_path


def build_mesh_motion(spec: dict, output: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    report = json.loads((output / "preview_report.json").read_text(encoding="utf-8"))
    paths = sorted((output / "baseline").glob("frame_*.png"))
    if len(paths) != report["frameCount"]:
        raise RuntimeError("mesh-motion frame inventory differs from its report")
    source_frames = [Image.open(path).convert("RGBA") for path in paths]
    try:
        bounds = shared_alpha_bounds(source_frames)
        try:
            font = ImageFont.truetype("arial.ttf", 18)
        except OSError:
            font = ImageFont.load_default()
        frames = []
        for index, source in enumerate(source_frames):
            cropped = source.crop(bounds)
            panel = fit_rgba(cropped, (570, 570), Image.Resampling.LANCZOS, crop_alpha=False)
            canvas = Image.new("RGBA", (600, 650), (18, 27, 34, 255))
            canvas.alpha_composite(panel, ((600 - panel.width) // 2, 40 + (570 - panel.height) // 2))
            draw = ImageDraw.Draw(canvas)
            draw.rectangle((0, 0, 599, 39), fill=(39, 53, 63, 255))
            draw.rectangle((0, 610, 599, 649), fill=(39, 53, 63, 255))
            draw.text((12, 10), "Beholder skinned mesh | Unit_AttackFront", font=font,
                      fill=(226, 236, 240, 255))
            changed = report["frames"][index]["meshDeformedVerticesFromPrevious"]
            draw.text((12, 620), f"t={index / spec['fps']:.3f}s  |  {changed:,} / "
                      f"{report['skinnedVertexCount']:,} vertices moved", font=font,
                      fill=(201, 218, 225, 255))
            frames.append(canvas.convert("RGB"))
            cropped.close()
            panel.close()
        gif_path = output / "mesh_motion.gif"
        frames[0].save(gif_path, save_all=True, append_images=frames[1:],
                       duration=gif_frame_durations(int(spec["fps"]), len(frames)),
                       loop=0, disposal=2, optimize=False)
        for frame in frames:
            frame.close()
        return gif_path
    finally:
        for frame in source_frames:
            frame.close()


def run(args: argparse.Namespace) -> Path:
    project = Path(args.project).resolve()
    spec_path = Path(args.spec).resolve()
    spec = load_spec(spec_path)
    validate_spec(spec, project)
    if not EDITOR_SOURCE.is_file():
        raise FileNotFoundError(EDITOR_SOURCE)
    if not (project / "ProjectSettings" / "ProjectVersion.txt").is_file():
        raise FileNotFoundError(project / "ProjectSettings" / "ProjectVersion.txt")
    unity = Path(args.unity_editor or os.environ.get("UNITY_EDITOR") or UNITY_DEFAULT)
    if not unity.is_file():
        raise FileNotFoundError(f"Unity Editor not found: {unity}; set UNITY_EDITOR")
    output = output_directory(args.out)
    output.mkdir(parents=True)
    editor_dir = ensure_editor_script_dir(project)
    editor_target = editor_dir / EDITOR_SOURCE.name
    if editor_target.is_symlink():
        raise ValueError(f"refusing to write through a linked Unity editor script: {editor_target}")
    if editor_target.exists():
        if editor_target.stat().st_nlink > 1:
            raise ValueError(f"refusing to write through a linked Unity editor script: {editor_target}")
        current_source = editor_target.read_text(encoding="utf-8")
        if EDITOR_SOURCE_MARKER not in current_source:
            raise FileExistsError(f"refusing to overwrite existing Unity editor script: {editor_target}")
        if editor_target.read_bytes() != EDITOR_SOURCE.read_bytes():
            shutil.copy2(EDITOR_SOURCE, editor_target)
    else:
        shutil.copy2(EDITOR_SOURCE, editor_target)
    log_path = output / "unity_editor.log"
    runtime_spec = output / "preview_spec.json"
    runtime_spec.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")

    command = [
        str(unity),
        "-batchmode",
        "-quit",
        "-projectPath",
        str(project),
        "-unitVfxPreviewSpec",
        str(runtime_spec),
        "-unitVfxPreviewOut",
        str(output),
        "-executeMethod",
        "OldenEra.Homm3Import.UnitVfxPreview.RenderFromBatch",
        "-logFile",
        str(log_path),
    ]
    # The queue's preflight replaces the old "Unity.exe already running" refusal; --unity-direct is the explicit,
    # loudly logged opt-out. A queue timeout comes back as a failed job (nonzero returncode).
    completed = _unity_queue().run_cmd(
        command, kind="unit_vfx_preview", timeout_s=args.timeout, direct=getattr(args, "unity_direct", False)
    )
    (output / "unity_process_output.txt").write_text(
        (completed.stdout or "") + "\n--- stderr ---\n" + (completed.stderr or ""), encoding="utf-8"
    )
    if completed.returncode != 0 or not (output / "preview_report.json").is_file():
        tail = ""
        if log_path.is_file():
            tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-60:])
        if "No valid Unity Editor license found" in tail:
            raise RuntimeError(
                "Unity refused the Editor render because this host has no valid batch-mode Editor license. "
                "Activate or assign a Unity Editor license, then retry. No preview report was produced."
            )
        raise RuntimeError(f"Unity preview failed (exit {completed.returncode}). Log: {log_path}\n{tail}")

    report = json.loads((output / "preview_report.json").read_text(encoding="utf-8"))
    validate_report(spec, report)
    comparison = build_comparison(spec, project, output)
    mesh_motion = build_mesh_motion(spec, output) if spec.get("requireSkinnedMeshDeformation") else None
    print(f"Unity editor render: {report['frameCount']} frames; Olden Era runtime not used")
    print(f"Comparison preview: {comparison}")
    if mesh_motion:
        print(f"Skinned-mesh motion preview: {mesh_motion}")
    print(f"Run report: {output / 'preview_report.json'}")
    return comparison


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", default=str(DEFAULT_SPEC), help="preview JSON spec")
    parser.add_argument("--project", default=str(REPO_ROOT / "oldenera_factions"), help="Unity project path")
    parser.add_argument("--unity-editor", help="Unity.exe path; defaults to UNITY_EDITOR or the project standard")
    parser.add_argument("--out", help="new output directory under artifacts/unit_vfx_preview")
    parser.add_argument("--timeout", type=int, default=600, help="Unity batch timeout in seconds")
    parser.add_argument("--unity-direct", action="store_true",
                        help="explicit opt-out: launch Unity directly instead of submitting to the Unity queue")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        run(parse_args(argv))
    except (OSError, ValueError, RuntimeError, TypeError, OverflowError) as exc:
        print(f"preview_unit_vfx: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
