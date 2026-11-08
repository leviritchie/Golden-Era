#!/usr/bin/env python3
"""Source-guided five-chain Beholder attack diagnostic in Unity Editor, with honest review gates."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.ndimage import binary_dilation
from analyze_beholder_anatomy_sol_v1 import idle_palette


ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SPEC = HERE / "beholder_attack_contour_v14.json"
EDITOR_SCRIPT = HERE / "unity_editor" / "BeholderAttackContourV14.cs"
PROJECT = ROOT / "oldenera_factions"
OUTPUT_ROOT = ROOT / "artifacts" / "homm3_beholder_attack_repair_sol_v1"
EFFECT_ROOT = OUTPUT_ROOT / "effect_envelope"
GROWN_ROOT = OUTPUT_ROOT / "effect_region_grown"
UNITY = Path(r"C:\Program Files\Unity\Hub\Editor\6000.0.66f2\Editor\Unity.exe")


def _unity_queue():
    """Unity jobs go through the Unity queue (docs/unity_queue_runner.md): agents submit, not launch."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("unity_queue", ROOT / "tools" / "unity_queue" / "unity_queue.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def repo_input(relative: str) -> Path:
    name = Path(relative)
    path = ROOT / name
    # oldenera_factions is a junction to the active Unity worktree; this is read-only.
    if name.is_absolute() or ".." in name.parts or not path.is_file():
        raise ValueError(f"missing or escaped input: {relative}")
    return path


def validate_and_prepare(output: Path) -> dict:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if spec.get("schema") != "beholder_attack_contour_v14" or spec.get("status") != "candidate_requires_visual_review":
        raise ValueError("repair spec schema/status drift")
    if sha256(repo_input(spec["glb"])).lower() != spec["glbSha256"].lower():
        raise ValueError("frozen five-chain GLB hash drift")
    view = json.loads(repo_input(spec["restViewScan"]).read_text(encoding="utf-8"))
    selected = view["sourceFacingBest"]
    if (selected["yawDegrees"] != spec["yawDegrees"] or selected["eyeViewX"] <= 0.05
            or selected["eyeFacingDot"] <= 0.2):
        raise ValueError("source-facing orientation is not supported by the frozen view scan")
    if len(spec["chains"]) != 5 or sum(map(len, spec["chains"])) != 32:
        raise ValueError("expected five articulated chains and 32 chain joints")
    joint_names = [name for chain in spec["chains"] for name in chain]
    if len(set(joint_names)) != 32:
        raise ValueError("duplicate chain joint")
    slots = [f"12_{index:02d}" for index in range(7)]
    tracks = spec["contours"]
    roots = [chain[0] for chain in spec["chains"]]
    if (len(tracks) != 5 or [track["root"] for track in tracks] != roots
            or roots.count(spec["frontChainRoot"]) != 1
            or any(len(track["frames"]) != 7 for track in tracks)
            or len(spec["emitterChainRoot"]) != 7 or len(spec["emitterJointIndex"]) != 7
            or len(spec["emitterSourceXY"]) != 7):
        raise ValueError("source contour tracks or emitter identity drift")
    for chain, track in zip(spec["chains"], tracks):
        for knots in track["frames"]:
            indices = [k[0] for k in knots]
            if (len(knots) < 2 or indices != sorted(set(indices))
                    or indices[0] != 0 or indices[-1] != len(chain) - 1
                    or any(len(k) != 4 or not isinstance(k[3], bool) for k in knots)):
                raise ValueError(f"invalid full-chain contour: {track['root']}")
    palette = idle_palette()
    manifest = json.loads(repo_input(spec["extractionManifest"]).read_text(encoding="utf-8"))
    if manifest.get("schema") != "homm3_beholder_electricity_extract_sol_v1":
        raise ValueError("electricity extraction provenance drift")
    entries = {row["source"].removesuffix(".png"): row for row in manifest["frames"]}
    effect_manifest = json.loads((EFFECT_ROOT / "manifest.json").read_text(encoding="utf-8"))
    if (effect_manifest.get("schema") != "beholder_source_effect_envelope_sol_v1"
            or effect_manifest.get("status") != "partial_exact_rgba_not_full_effect_matte"):
        raise ValueError("source effect envelope provenance drift")
    effect_entries = {row["slot"]: row for row in effect_manifest["frames"]}
    grown_manifest = json.loads((GROWN_ROOT / "manifest.json").read_text(encoding="utf-8"))
    if (grown_manifest.get("schema") != "beholder_source_effect_region_grown_sol_v1"
            or grown_manifest.get("status") != "candidate_partial_exact_rgba_not_full_effect_matte"):
        raise ValueError("connected source effect recovery provenance drift")
    grown_entries = {row["slot"]: row for row in grown_manifest["frames"]}
    idle_anatomy = []
    for idle_index in range(11):
        idle_path = repo_input(f"oldenera_factions/Assets/CustomUnits/homm3_lab/h3_beholder/extracted_battle/CBEHOL.dir/00_{idle_index:02d}.png")
        with Image.open(idle_path) as loaded:
            idle_anatomy.append(np.asarray(loaded.convert("RGBA"))[:, :, 3] == 255)
    anatomy_envelope = np.any(np.stack(idle_anatomy), axis=0)
    crop_dir = output / "source_effect_crops"
    crop_dir.mkdir(parents=True)
    recovered_dir = output / "source_effect_full_recovery"
    recovered_dir.mkdir(parents=True)
    forward_dir = output / "source_effect_forward_recovery"
    forward_dir.mkdir(parents=True)
    uncertainty_dir = output / "source_effect_uncertainty"
    uncertainty_dir.mkdir(parents=True)
    runtime_frames = []
    invalid_observations = []
    for slot_index, name in enumerate(slots):
        record = entries[name]
        source = repo_input(f"oldenera_factions/Assets/CustomUnits/homm3_lab/h3_beholder/extracted_battle/CBEHOL.dir/{name}.png")
        if sha256(source) != record["source_sha256"]:
            raise ValueError(f"source sprite hash drift: {name}")
        with Image.open(source) as source_image:
            source_rgba = source_image.convert("RGBA")
            source_pixels = np.asarray(source_rgba)
        targets = [{"root": track["root"], "knots": [
            {"jointIndex": k[0], "point": {"x": k[1], "y": k[2]}, "sourceVisible": k[3]}
            for k in track["frames"][slot_index]]} for track in tracks]
        runtime_frame = {"name": name, "sourcePath": str(source), "sourceSha256": sha256(source),
                         "targets": targets, "emitterChainRoot": spec["emitterChainRoot"][slot_index],
                         "emitterJointIndex": spec["emitterJointIndex"][slot_index],
                         "emitterSource": {"x": spec["emitterSourceXY"][slot_index][0],
                                           "y": spec["emitterSourceXY"][slot_index][1]},
                         "cropPath": "", "cropSha256": "", "x0": 0, "y0": 0, "x1": 0, "y1": 0,
                         "corePixels": 0}
        core = repo_input(f"artifacts/homm3_beholder_electricity_extract_sol_v1/{record['core_png']}")
        if sha256(core) != record["core_png_sha256"]:
            raise ValueError(f"white-core extraction hash drift: {name}")
        with Image.open(core) as core_image:
            core_rgba = core_image.convert("RGBA")
            core_bbox = core_rgba.getchannel("A").getbbox()
            if core_bbox != tuple(record["core_bbox_xyxy_exclusive"]):
                raise ValueError(f"core crop bounds drift: {name}")
            core_array = np.asarray(core_rgba)
            selected_core = core_array[:, :, 3] > 0
            if (not np.array_equal(core_array[selected_core], source_pixels[selected_core])
                    or not np.all(core_array[selected_core] == 255)):
                raise ValueError(f"core contains non-exact source pixel: {name}")
            effect_record = effect_entries[name]
            effect_path = EFFECT_ROOT / effect_record["effectPng"]
            if (sha256(effect_path) != effect_record["effectPngSha256"]
                    or effect_record["sourceSha256"] != sha256(source)
                    or effect_record["coreSha256"] != sha256(core)):
                raise ValueError(f"effect envelope provenance drift: {name}")
            with Image.open(effect_path) as effect_image:
                effect_rgba = effect_image.convert("RGBA")
                effect_pixels = np.asarray(effect_rgba)
                source_pixels = np.asarray(source_rgba)
                core_pixels = np.asarray(core_rgba)
                envelope_mask = effect_pixels[:, :, 3] > 0
                if (not np.array_equal(effect_pixels[envelope_mask], source_pixels[envelope_mask])
                        or np.any((core_pixels[:, :, 3] > 0) & ~envelope_mask)
                        or int(envelope_mask.sum()) != effect_record["selectedPixels"]):
                    raise ValueError(f"effect envelope is not an exact-source superset of core: {name}")
                bbox = effect_rgba.getchannel("A").getbbox()
                if bbox != tuple(effect_record["bboxXYXYExclusive"]):
                    raise ValueError(f"effect envelope bounds drift: {name}")
            grown_record = grown_entries[name]
            grown_path = GROWN_ROOT / grown_record["effectPng"]
            if (sha256(grown_path) != grown_record["effectPngSha256"]
                    or grown_record["sourceSha256"] != sha256(source)
                    or grown_record["coreSha256"] != sha256(core)):
                raise ValueError(f"connected source recovery provenance drift: {name}")
            with Image.open(grown_path) as grown_image:
                grown_rgba = np.asarray(grown_image.convert("RGBA"))
            grown_mask = grown_rgba[:, :, 3] > 0
            if (not np.array_equal(grown_rgba[grown_mask], source_pixels[grown_mask])
                    or np.any((core_pixels[:, :, 3] > 0) & ~grown_mask)
                    or int(grown_mask.sum()) != grown_record["selectedPixels"]):
                raise ValueError(f"connected recovery is not an exact-source superset of core: {name}")
            core_mask = core_pixels[:, :, 3] > 0
            recovered = envelope_mask | grown_mask
            if np.any(recovered & anatomy_envelope & ~core_mask):
                raise ValueError(f"source recovery includes registered idle anatomy: {name}")
            ambiguity = (binary_dilation(recovered, iterations=1) & (source_pixels[:, :, 3] > 0)
                         & anatomy_envelope & ~core_mask)
            uncertainty = source_pixels.copy()
            uncertainty[ambiguity] = np.array([255, 86, 32, 255], dtype=np.uint8)
            Image.fromarray(uncertainty, "RGBA").crop((100, 120, 300, 320)) \
                .resize((spec["renderSize"], spec["renderSize"]), Image.Resampling.NEAREST) \
                .save(uncertainty_dir / f"{name}.png")
            for target in targets:
                for knot in target["knots"]:
                    if not knot["sourceVisible"]:
                        continue
                    x, y = int(knot["point"]["x"]), int(knot["point"]["y"])
                    neighborhood = source_pixels[max(0, y - 3):y + 4, max(0, x - 3):x + 4, 3] > 127
                    if (not neighborhood.any() or recovered[y, x]):
                        invalid_observations.append(f"{name} {target['root']} {x},{y}")
            forward = recovered.copy()
            forward[:, :215] = False
            forward[246:, :] = False
            forward_yx = np.argwhere(forward)
            if len(forward_yx):
                origin_x = int(forward_yx[:, 1].min())
                near_origin = forward_yx[forward_yx[:, 1] <= origin_x + 4]
                origin_y = int(np.median(near_origin[:, 0]))
                light_origin = {"x": origin_x, "y": origin_y}
            else:
                light_origin = {"x": 0, "y": 0}
            recovered_rgba = np.zeros_like(source_pixels)
            recovered_rgba[recovered] = source_pixels[recovered]
            recovered_image = Image.fromarray(recovered_rgba, "RGBA")
            recovered_path = recovered_dir / f"{name}.png"
            recovered_image.save(recovered_path)
            with Image.open(recovered_path) as check:
                saved_recovery = np.asarray(check.convert("RGBA"))
            if (not np.array_equal(saved_recovery, recovered_rgba)
                    or not np.array_equal(saved_recovery[recovered], source_pixels[recovered])):
                raise ValueError(f"full recoverable source RGBA changed during PNG round trip: {name}")
            forward_rgba = np.zeros_like(source_pixels)
            forward_rgba[forward] = source_pixels[forward]
            forward_image = Image.fromarray(forward_rgba, "RGBA")
            forward_path = forward_dir / f"{name}.png"
            forward_image.save(forward_path)
            with Image.open(forward_path) as check:
                saved_forward = np.asarray(check.convert("RGBA"))
            if (not np.array_equal(saved_forward, forward_rgba)
                    or not np.array_equal(saved_forward[forward], source_pixels[forward])):
                raise ValueError(f"forward electricity RGBA changed during PNG round trip: {name}")
            forward_bbox = forward_image.getchannel("A").getbbox() or (0, 0, 1, 1)
            crop = crop_dir / f"{name}.png"
            forward_image.crop(forward_bbox).save(crop)
            runtime_frame.update({"cropPath": str(crop), "cropSha256": sha256(crop),
                                  "effectSourcePath": str(forward_path), "effectSourceSha256": sha256(forward_path),
                                  "allRecoveredSourcePath": str(recovered_path),
                                  "allRecoveredSourceSha256": sha256(recovered_path),
                                  "effectPixels": int(forward.sum()),
                                  "recoverableSourcePixels": int(recovered.sum()),
                                  "ambiguousNearCoreAnatomyPixels": int(ambiguity.sum()),
                                  "forwardEffectPixels": int(len(forward_yx)),
                                  "hasLightOrigin": bool(len(forward_yx)), "lightOrigin": light_origin,
                                  "x0": forward_bbox[0], "y0": forward_bbox[1],
                                  "x1": forward_bbox[2], "y1": forward_bbox[3],
                                  "corePixels": record["core_pixels"]})
        runtime_frames.append(runtime_frame)
    if invalid_observations:
        raise ValueError("observed contour is absent or electricity: " + "; ".join(invalid_observations))
    peak_forward = max(frame["forwardEffectPixels"] for frame in runtime_frames)
    if peak_forward < 100 or runtime_frames[0]["forwardEffectPixels"]:
        raise ValueError("forward discharge mask does not establish timed light baseline/peak")
    for frame in runtime_frames:
        frame["lightScale"] = round(frame["forwardEffectPixels"] / peak_forward, 6)
    annotation_dir = output / "source_contours"
    annotation_dir.mkdir()
    colors = ((243, 100, 85), (77, 222, 248), (255, 210, 75), (147, 237, 111), (206, 141, 245))
    for frame in runtime_frames:
        with Image.open(frame["sourcePath"]) as loaded:
            source_crop = loaded.convert("RGBA").crop((100, 120, 300, 320))
        panel = Image.new("RGB", (500, 500), (20, 25, 31))
        source_crop = source_crop.resize((500, 500), Image.Resampling.NEAREST)
        panel.paste(source_crop, (0, 0), source_crop)
        draw = ImageDraw.Draw(panel)
        for target, color in zip(frame["targets"], colors):
            knots = target["knots"]
            points = [((k["point"]["x"] - 100) * 2.5, (k["point"]["y"] - 120) * 2.5) for k in knots]
            draw.line(points, fill=color, width=2)
            for (x, y), knot in zip(points, knots):
                if knot["sourceVisible"]:
                    draw.ellipse((x - 4, y - 4, x + 4, y + 4), fill=color)
                else:
                    draw.ellipse((x - 4, y - 4, x + 4, y + 4), outline=color, width=2)
        panel.save(annotation_dir / f"{frame['name']}.png")
    runtime = {"schema": spec["schema"], "status": spec["status"],
               "glbPath": str(repo_input(spec["glb"])), "glbSha256": spec["glbSha256"],
               "authoredSpecPath": str(SPEC), "authoredSpecSha256": sha256(SPEC),
               "runnerPath": str(Path(__file__).resolve()), "runnerSha256": sha256(Path(__file__).resolve()),
               "editorScriptPath": str(PROJECT / "Assets" / "Editor" / EDITOR_SCRIPT.name),
               "editorScriptSha256": sha256(EDITOR_SCRIPT),
               "yawDegrees": spec["yawDegrees"], "sourceBodyX": spec["sourceBodyX"],
               "sourceGroundY": spec["sourceGroundY"], "pixelsPerUnit": spec["pixelsPerUnit"],
               "pointLightIntensity": spec["pointLightIntensity"],
               "pointLightRange": spec["pointLightRange"],
               "cardDepthTowardCamera": spec["cardDepthTowardCamera"],
               "renderSize": spec["renderSize"], "gifFrameDurationMs": spec["gifFrameDurationMs"],
               "bodyPolicy": spec["bodyPolicy"],
               "frontChainRoot": spec["frontChainRoot"],
               "chains": [{"bones": chain} for chain in spec["chains"]],
               "frames": runtime_frames}
    (output / "runtime_spec.json").write_text(json.dumps(runtime, indent=2) + "\n", encoding="utf-8")
    return runtime


def validate_unity_report(report: dict, runtime: dict, output: Path) -> None:
    if (report.get("schema") != "beholder_attack_contour_v14_report"
            or report.get("proof") != "unity-editor-gltfast-render"
            or report.get("rejectedHumanoidClipUsed") is not False
            or report.get("glbPath") != runtime["glbPath"]
            or report.get("glbSha256") != runtime["glbSha256"]
            or report.get("authoredSpecSha256") != runtime["authoredSpecSha256"]
            or report.get("runnerSha256") != runtime["runnerSha256"]
            or report.get("editorScriptSha256") != runtime["editorScriptSha256"]
            or report.get("yawDegrees") != runtime["yawDegrees"]
            or report.get("vertexCount") != 8405 or report.get("triangleCount") != 9023
            or report.get("skinnedRendererCount") != 1 or report.get("skinBoneCount") != 34
            or report.get("rendererCount", 0) < 1 or report.get("frameCount") != 7):
        raise RuntimeError("Unity report fails frozen-mesh/source-facing/no-humanoid proof")
    if len(report.get("frames", [])) != 7:
        raise RuntimeError("Unity report lacks seven source slots")
    clip = output / "beholder_v14.anim"
    if (report.get("clipArtifactPath") != str(clip)
            or report.get("clipUnityAssetPath") != f"Assets/Editor/BeholderAttackContourV14Generated/{output.name}.anim"
            or not clip.is_file() or report.get("clipSha256") != sha256(clip)
            or report.get("clipSampleMaxAngleDegrees", 999) > 0.5
            or report.get("clipBetweenKeySamples") != 6
            or report.get("clipBetweenKeyMaxAngleDegrees", 999) > 90
            or report.get("clipSampleMaxEmitterPositionDelta", 999) > 0.001
            or report.get("clipSampleMaxLightIntensityError", 999) > 0.001
            or report.get("clipActiveEffectPoseSamples") != sum(bool(frame["forwardEffectPixels"])
                                                                 for frame in runtime["frames"])
            or report.get("clipMaxActiveEffectPositionDelta", 999) > 0.001
            or report.get("clipMaxActiveEffectRotationDelta", 999) > 0.5
            or report.get("clipPhaseActivationKeyErrors", 999) != 0
            or report.get("clipEffectPhaseCount") != sum(bool(frame["forwardEffectPixels"])
                                                         for frame in runtime["frames"])):
        raise RuntimeError("Unity sampled diagnostic AnimationClip missing or hash drift")
    roots = [chain["bones"][0] for chain in runtime["chains"]]
    if roots.count(runtime["frontChainRoot"]) != 1:
        raise RuntimeError("front chain root absent or ambiguous")
    for expected, frame in zip(runtime["frames"], report["frames"]):
        if (frame.get("name") != expected["name"] or frame.get("sourceSha256") != expected["sourceSha256"]
                or frame.get("cropSha256") != expected["cropSha256"] or len(frame.get("chains", [])) != 5
                or frame.get("meshMaskPixels", 0) < 100 or frame.get("magentaFailurePixels", 0) > 10):
            raise RuntimeError(f"Unity frame provenance/mask failed: {expected['name']}")
        if (frame.get("forwardEffectPixels") != expected["forwardEffectPixels"]
                or abs(frame.get("pointLightIntensity", -1) - runtime["pointLightIntensity"] * expected["lightScale"]) > 0.001
                or frame.get("lightOriginX") != expected["lightOrigin"]["x"]
                or frame.get("lightOriginY") != expected["lightOrigin"]["y"]):
            raise RuntimeError(f"source-timed light report drift: {expected['name']}")
        for index, chain in enumerate(frame["chains"]):
            contour = expected["targets"][index]
            visible_count = sum(k["sourceVisible"] for k in contour["knots"])
            if (chain.get("root") != roots[index] or contour["root"] != roots[index]
                    or chain.get("observedContourKnotCount") != visible_count
                    or chain.get("inferredContourKnotCount") != len(contour["knots"]) - visible_count):
                raise RuntimeError(f"Unity full-chain contour identity drift: {expected['name']} {roots[index]}")
        emitter_chain = next((chain for chain in runtime["chains"]
                              if chain["bones"][0] == expected["emitterChainRoot"]), None)
        if emitter_chain is None or expected["emitterJointIndex"] >= len(emitter_chain["bones"]):
            raise RuntimeError(f"configured emitter chain/joint is absent: {expected['name']}")
        expected_emitter_bone = emitter_chain["bones"][expected["emitterJointIndex"]]
        if frame.get("emitterJointName") != expected_emitter_bone + f"@{expected['emitterJointIndex']}":
            raise RuntimeError(f"Unity selected emitter joint drift: {expected['name']}")
        if expected["forwardEffectPixels"] > 0 and frame.get("emitterProjectionResidualPixels", 999) > 4:
            raise RuntimeError(f"source effect contact is not attached to its posed emitter: {expected['name']}")
        for lane in ("baseline", "lit_mesh", "effect", "electricity_front", "clip_effect", "mesh_mask"):
            if not (output / lane / f"{expected['name']}.png").is_file():
                raise RuntimeError(f"Unity output missing {lane}/{expected['name']}")
        if expected["forwardEffectPixels"] > 0:
            if (frame.get("coreVisiblePixels", 0) < 15
                    or frame.get("sourceElectricityCells") != expected["forwardEffectPixels"]
                    or not 0.12 <= frame.get("electricitySurfaceDepthSpan", 0) <= 0.35):
                raise RuntimeError(f"exact source electricity or folded 3D surface proof failed: {expected['name']}")
        elif (frame.get("coreVisiblePixels", 0) != 0
              or frame.get("sourceElectricityCells", -1) != 0
              or frame.get("electricitySurfaceDepthSpan", -1) != 0):
            raise RuntimeError(f"non-discharge frame contains detached electricity geometry: {expected['name']}")
    for slot in (f"12_{index:02d}" for index in range(7)):
        if not (output / "oblique" / f"{slot}.png").is_file():
            raise RuntimeError(f"oblique 2.5D projection proof missing: {slot}")


def source_mask(source: Path, palette: set[tuple[int, int, int]]) -> Image.Image:
    with Image.open(source) as image:
        rgba = np.asarray(image.convert("RGBA"))
    rgb, alpha = rgba[:, :, :3], rgba[:, :, 3]
    anatomy = np.array([tuple(pixel) in palette for pixel in rgb.reshape(-1, 3)],
                       dtype=bool).reshape(rgb.shape[:2]) & (alpha > 127)
    return Image.fromarray((anatomy * 255).astype("uint8"))


def review_metrics(report: dict, runtime: dict, output: Path) -> dict:
    roots = [chain["bones"][0] for chain in runtime["chains"]]
    if roots.count(runtime["frontChainRoot"]) != 1:
        raise RuntimeError("review front chain root absent or ambiguous")
    front_index = roots.index(runtime["frontChainRoot"])
    palette = idle_palette()
    size = runtime["renderSize"]
    scale = size / 500
    overlay_dir = output / "overlays"
    overlay_dir.mkdir()
    joint_dir = output / "joint_correspondence"
    joint_dir.mkdir()
    with Image.open(output / "mesh_mask" / "12_00.png") as rendered:
        static = np.asarray(rendered.convert("RGB"))[:, :, 0] > 190
    yy, xx = np.indices(static.shape)
    body_region = (xx >= 200 * scale) & (xx < 290 * scale) & (yy >= 150 * scale) & (yy < 240 * scale)
    appendage_region = (xx >= 130 * scale) & (xx < 420 * scale) & (yy >= 220 * scale) & (yy < 385 * scale)
    lower_curl_region = ((xx >= 250 * scale) & (xx < 350 * scale)
                         & (yy >= 260 * scale) & (yy < 340 * scale))

    def iou(a: np.ndarray, b: np.ndarray, region: np.ndarray) -> float:
        candidate = a & region
        reference = b & region
        return round(float(np.logical_and(candidate, reference).sum() /
                           max(1, np.logical_or(candidate, reference).sum())), 4)

    def overlay(mesh: np.ndarray, reference: np.ndarray) -> Image.Image:
        pixels = np.full((size, size, 3), (20, 25, 31), dtype=np.uint8)
        pixels[reference] = (181, 89, 70)
        pixels[mesh] = (59, 189, 197)
        pixels[reference & mesh] = (234, 226, 187)
        return Image.fromarray(pixels)

    measurements = []
    for expected, frame in zip(runtime["frames"], report["frames"]):
        with Image.open(output / "mesh_mask" / f"{expected['name']}.png") as rendered:
            mesh = np.asarray(rendered.convert("RGB"))[:, :, 0] > 190
        with Image.open(output / "clip_effect" / f"{expected['name']}.png") as rendered:
            effect_rgb = np.asarray(rendered.convert("RGB"), dtype=np.int16)
        with Image.open(output / "electricity_front" / f"{expected['name']}.png") as rendered:
            front_rgb = np.asarray(rendered.convert("RGB"))
        front_background = front_rgb[0, 0]
        rendered_front_mask = np.any(front_rgb != front_background, axis=2)
        with Image.open(output / "lit_mesh" / f"{expected['name']}.png") as rendered:
            lit_rgb = np.asarray(rendered.convert("RGB"), dtype=np.int16)
        visible_core = np.all(effect_rgb > lit_rgb + 30, axis=2)
        with Image.open(expected["cropPath"]) as crop_image:
            full_effect = Image.new("L", (450, 400), 0)
            full_effect.paste(crop_image.convert("RGBA").getchannel("A"), (expected["x0"], expected["y0"]))
        expected_effect = np.asarray(full_effect.crop((100, 120, 300, 320)).resize((size, size), Image.Resampling.NEAREST)) > 0
        with Image.open(expected["sourcePath"]) as loaded:
            expected_source_rgb = np.asarray(loaded.convert("RGB").crop((100, 120, 300, 320))
                                             .resize((size, size), Image.Resampling.NEAREST))
        front_rgb_mismatches = int((expected_effect & np.any(front_rgb != expected_source_rgb, axis=2)).sum())
        source = source_mask(Path(expected["sourcePath"]), palette)
        source = source.crop((100, 120, 300, 320)).resize((size, size), Image.Resampling.NEAREST)
        reference = np.asarray(source) > 0
        comparison = Image.new("RGB", (size * 2, size), (20, 25, 31))
        comparison.paste(overlay(static, reference), (0, 0))
        comparison.paste(overlay(mesh, reference), (size, 0))
        comparison.save(overlay_dir / f"{expected['name']}.png")
        with Image.open(expected["sourcePath"]) as loaded:
            source_rgba = loaded.convert("RGBA").crop((100, 120, 300, 320)).resize((size, size), Image.Resampling.NEAREST)
        with Image.open(output / "baseline" / f"{expected['name']}.png") as loaded:
            mesh_rgb = loaded.convert("RGB")
        joint_panel = Image.new("RGB", (size * 2, size), (20, 25, 31))
        joint_panel.paste(source_rgba, (0, 0), source_rgba)
        joint_panel.paste(mesh_rgb, (size, 0))
        joint_draw = ImageDraw.Draw(joint_panel)
        colors = ((243, 100, 85), (77, 222, 248), (255, 210, 75), (147, 237, 111), (206, 141, 245))
        for chain_index, chain in enumerate(frame["chains"]):
            points = [((joint["x"] - 100) * size / 200, (joint["y"] - 120) * size / 200) for joint in chain["jointXY"]]
            for offset in (0, size):
                shifted = [(x + offset, y) for x, y in points]
                joint_draw.line(shifted, fill=colors[chain_index], width=2)
                for x, y in shifted:
                    joint_draw.ellipse((x - 3, y - 3, x + 3, y + 3), fill=colors[chain_index])
        joint_panel.save(joint_dir / f"{expected['name']}.png")
        constrained = frame["chains"][front_index]
        effect_iou = (iou(visible_core, expected_effect, np.ones_like(mesh))
                      if expected["forwardEffectPixels"] > 0 else 1.0)
        front_iou = (iou(rendered_front_mask, expected_effect, np.ones_like(mesh))
                     if expected["forwardEffectPixels"] > 0 else 1.0)
        front_mask_mismatches = int(np.logical_xor(rendered_front_mask, expected_effect).sum())
        measurements.append({"slot": expected["name"], "anatomySilhouetteIoU": iou(mesh, reference, np.ones_like(mesh)),
                             "bodyIoU": iou(mesh, reference, body_region),
                              "appendageIoU": iou(mesh, reference, appendage_region),
                              "staticAppendageBaselineIoU": iou(static, reference, appendage_region),
                              "lowerCurlIoU": iou(mesh, reference, lower_curl_region),
                              "staticLowerCurlBaselineIoU": iou(static, reference, lower_curl_region),
                             "appendageIoUGainVsStatic": round(iou(mesh, reference, appendage_region)
                                                                 - iou(static, reference, appendage_region), 4),
                             "meshMaskChangedPixelsFromRest": int(np.logical_xor(mesh, static).sum()),
                             "bakedMeshMaxVertexDelta": round(frame["bakedMeshMaxVertexDelta"], 5),
                             "chainTipTravelPixels": [round(float(np.hypot(chain["actualX"] - report["frames"][0]["chains"][index]["actualX"],
                                                        chain["actualY"] - report["frames"][0]["chains"][index]["actualY"])), 2)
                                                      for index, chain in enumerate(frame["chains"])],
                             "chainBakedMaxDisplacementVsHeldRest": [round(chain["bakedMaxDisplacementVsHoldingThisChainAtRest"], 5)
                                                                        for chain in frame["chains"]],
                             "frontVisibleContourMaxResidualPixels": round(constrained["observedContourMaxResidualPixels"], 2),
                             "allVisibleContourMaxResidualsPixels": [round(chain["observedContourMaxResidualPixels"], 2)
                                                                     for chain in frame["chains"]],
                             "inferredKnotCounts": [chain["inferredContourKnotCount"] for chain in frame["chains"]],
                             "distalTipsInferred": [chain["distalNotTargeted"] for chain in frame["chains"]],
                              "emitterProjectionResidualPixels": round(frame["emitterProjectionResidualPixels"], 2),
                              "sourceEffectRasterIoU": effect_iou,
                              "sourceEffectFrontProjectionIoU": front_iou,
                              "sourceEffectFrontProjectionMaskMismatches": front_mask_mismatches,
                              "sourceEffectFrontProjectionRgbMismatches": front_rgb_mismatches,
                              "renderedSourceElectricityPixels": int(rendered_front_mask.sum()),
                              "recoveredSourceEffectPixels": expected["effectPixels"],
                              "allRecoverableSourcePixels": expected["recoverableSourcePixels"],
                              "unresolvedSourceOverlapPixels": expected["ambiguousNearCoreAnatomyPixels"],
                              "coreVisiblePixels": frame["coreVisiblePixels"],
                             "magentaFailurePixels": frame["magentaFailurePixels"],
                             "meshLightingChangedPixels": frame["meshLightingChangedPixels"],
                             "meshBrightenedPixels": frame["meshBrightenedPixels"],
                             "forwardEffectPixels": frame["forwardEffectPixels"],
                             "sourceElectricityCells": frame["sourceElectricityCells"],
                             "electricitySurfaceDepthSpan": round(frame["electricitySurfaceDepthSpan"], 4),
                             "pointLightIntensity": round(frame["pointLightIntensity"], 4),
                             "lightOriginXY": [frame["lightOriginX"], frame["lightOriginY"]]})
    by_name = {row["slot"]: row for row in measurements}
    chains0 = report["frames"][0]["chains"]
    thrust = min(report["frames"][index]["chains"][front_index]["actualX"]
                 - chains0[front_index]["actualX"] for index in (3, 4))
    gates = {
        "sourceFacingEye": True,
        "frozenFiveChainGLB": True,
        "noHumanoidClip": True,
        "fiveChainAnatomicalIdentityResolved": False,
        "broadLowerStrikeChainSelectedFromGlbAndJointOverlays": roots[3] == "Bone_025",
        "fullChainContoursPresent": all(len(target["knots"]) >= 2
                                         for frame in runtime["frames"] for target in frame["targets"]),
        "skinnedMeshActuallyDeforms": any(row["bakedMeshMaxVertexDelta"] >= 0.03 for row in measurements[1:]),
        "renderedMeshMaskActuallyChanges": any(row["meshMaskChangedPixelsFromRest"] >= 30 for row in measurements[1:]),
        "strikeDistalTipObservedInSource": False,
        "frontShaftTipAdvancesBothStrikeSlots": thrust >= 2,
        "visibleContourKnotsWithin4Px": all(
            residual <= 4 for row in measurements for residual in row["allVisibleContourMaxResidualsPixels"]),
        "appendageIoUImprovesOverStaticInBothStrikeSlots": all(
            by_name[name]["appendageIoU"] >= by_name[name]["staticAppendageBaselineIoU"] + 0.03
            for name in ("12_03", "12_04")),
        "sourceAppendageIoUAtLeast0_45EverySlot": all(row["appendageIoU"] >= 0.45 for row in measurements),
        "exactSourceEffectVisibleEveryDischargeSlot": all(
            row["coreVisiblePixels"] >= 15 for row in measurements if row["forwardEffectPixels"] > 0),
        "exactRecoveredSourceMaskInFrontProjectionEveryDischargeSlot": all(
            row["sourceEffectFrontProjectionMaskMismatches"] == 0
            for row in measurements if row["forwardEffectPixels"] > 0),
        "exactRecoveredSourceRGBAInClipFrontProjectionEveryDischargeSlot": all(
            row["sourceEffectFrontProjectionRgbMismatches"] == 0
            for row in measurements if row["forwardEffectPixels"] > 0),
        "foldedElectricityGeometryHas3DDepthEveryDischargeSlot": all(
            0.12 <= row["electricitySurfaceDepthSpan"] <= 0.35
            for row in measurements if row["forwardEffectPixels"] > 0),
        "noElectricityFragmentInQuietSlots": all(
            row["coreVisiblePixels"] == 0 and row["pointLightIntensity"] == 0
            and row["renderedSourceElectricityPixels"] == 0
            for row in measurements if row["forwardEffectPixels"] == 0),
        "isolatedPointLightBrightensMesh": all(by_name[name]["meshBrightenedPixels"] >= 20 for name in ("12_03", "12_04")),
        "idlePointLightOff": by_name["12_00"]["meshLightingChangedPixels"] == 0
            and by_name["12_00"]["pointLightIntensity"] == 0,
        "occludedDistalTipsLabeledInferred": all(all(row["distalTipsInferred"])
                                                for row in measurements),
        "posedEmitterWithin4PxOfSourceContact": all(by_name[name]["emitterProjectionResidualPixels"] <= 4
                                                       for name in ("12_02", "12_03", "12_04", "12_05")),
        "sampledUnityClipEmitted": bool(report["clipSha256"]),
        "unityClipKeyPosesRoundTrip": report["clipSampleMaxAngleDegrees"] <= 0.5,
        "unityClipBetweenKeysSampled": report["clipBetweenKeySamples"] == 6,
        "unityClipEmitterAndLightRoundTrip": report["clipSampleMaxEmitterPositionDelta"] <= 0.001
            and report["clipSampleMaxLightIntensityError"] <= 0.001,
        "unityClipElectricityTransformRoundTrip": report["clipActiveEffectPoseSamples"] == report["clipEffectPhaseCount"]
            and report["clipMaxActiveEffectPositionDelta"] <= 0.001
            and report["clipMaxActiveEffectRotationDelta"] <= 0.5,
        "unityClipEffectPhaseAndLightEnableKeysRoundTrip": report["clipPhaseActivationKeyErrors"] == 0,
        "lowerCurlImprovesOverStaticAtBothStrikeSlots": all(
            by_name[name]["lowerCurlIoU"] > by_name[name]["staticLowerCurlBaselineIoU"]
            for name in ("12_03", "12_04")),
        "obliqueClipProofRendered": all((output / "oblique" / f"12_{index:02d}.png").is_file()
                                           for index in range(7)),
    }
    result = {"schema": "beholder_attack_repair_review_v1",
              "candidateStatus": "rejected_diagnostic_only",
              "frontChainRoot": runtime["frontChainRoot"],
              "broadLowerStrikeChain": {
                  "root": roots[3],
                  "evidence": "Frozen GLB chain topology and skin influence locality plus source-facing GLTFast joint overlays place Bone_025 on the right/front long appendage; visible 12_03/12_04 centerline knots fit its broad lower curl. Bone_006 is a separate, thinner nearby stalk. Composited crossings still prevent a complete anatomical ownership claim.",
                  "strikeSlots": {name: {
                      "visibleCenterlineKnots": report["frames"][index]["chains"][3]["observedContourKnotCount"],
                      "maxVisibleResidualPixels": round(report["frames"][index]["chains"][3]["observedContourMaxResidualPixels"], 3),
                      "inferredKnots": report["frames"][index]["chains"][3]["inferredContourKnotCount"]}
                      for index, name in ((3, "12_03"), (4, "12_04"))}},
              "inputHashes": {key: runtime[key] for key in ("glbSha256", "authoredSpecSha256",
                                                        "runnerSha256", "editorScriptSha256")},
              "effectSourceEvidence": {
                  "selection": "union of a conservative exact-source envelope and connected off-idle recovery, restricted to x>=215 and y<246 in the forward-discharge region; every included RGBA value is copied from the original sprite",
                  "frontProjection": "Unity samples the persisted animation clip, hides the unit mesh, then compares the animated electricity object's front mask and RGB pixels against the selected source crop",
                  "depth": "The thin folded 3D depth field and per-pixel cell thickness are reconstructed for preview; the flat sprite does not encode electricity depth",
                  "ambiguousPixels": "Registered idle-anatomy overlaps near the recovered effect are excluded from the electricity surface and highlighted orange in the uncertainty panel",
                  "boundary": "This is an exact mask and RGB match for selected/recoverable forward pixels, not a complete semantic matte. The region is deliberately limited, and flattened body/electricity crossings and occluded flash pixels remain unresolved; no replacement bolt pixels are generated."},
              "clipDelivery": "Diagnostic only: the AnimationClip references the generated preview hierarchy; its temporary mesh/material objects are not emitted as a reusable prefab or deployed effect asset.",
              "note": "This is one source-guided technical preview, not an accepted production animation. It copies selected forward electricity RGBA from the HoMM3 sprites onto a thin folded per-pixel surface, samples the persisted Unity clip, verifies the effect object's source-facing world pose, and compares its rendered RGB/mask with the selected crop; an oblique clip render demonstrates the reconstructed depth. Lightning/body overlaps remain unresolved and depth is not source-authored. The saved Unity clip is diagnostic, not a reusable prefab or deployed asset. Mesh-animation quality remains independently gated by the anatomy/silhouette review.",
              "diagnosticUnityClipSha256": report["clipSha256"],
              "unityClipSampleMaxAngleDegrees": round(report["clipSampleMaxAngleDegrees"], 5),
              "frontShaftMinimumAdvancePixels": round(thrust, 2), "gates": gates, "frames": measurements}
    (output / "review_metrics.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


def make_gif(runtime: dict, output: Path) -> Path:
    font = ImageFont.truetype("arial.ttf", 18)
    frames = []
    labels = ("HoMM3 source", "Forward electricity crop | exact source RGBA", "Unity clip | mesh + electricity",
              "Unity mesh | light off", "Unity mesh | point light on", "Isolated mesh-light delta",
              "Oblique clip | folded 3D surface", "Unresolved overlap | excluded", "Clip front | source projection")
    for frame in runtime["frames"]:
        canvas = Image.new("RGB", (2000, 1596), (20, 25, 31))
        draw = ImageDraw.Draw(canvas)
        paths = (Path(frame["sourcePath"]), Path(frame["effectSourcePath"]),
                 output / "clip_effect" / f"{frame['name']}.png",
                 output / "baseline" / f"{frame['name']}.png",
                 output / "lit_mesh" / f"{frame['name']}.png", None,
                 output / "oblique" / f"{frame['name']}.png",
                 output / "source_effect_uncertainty" / f"{frame['name']}.png",
                 output / "electricity_front" / f"{frame['name']}.png")
        for index, (label, path) in enumerate(zip(labels, paths)):
            x, y = (index % 4) * 500, (index // 4) * 532
            draw.rectangle((x, y, x + 499, y + 31), fill=(43, 52, 63))
            draw.text((x + 12, y + 5), f"{label} | {frame['name']}", font=font, fill=(238, 242, 246))
            if path is None:
                with Image.open(paths[3]) as off, Image.open(paths[4]) as on:
                    off_rgb = np.asarray(off.convert("RGB"), dtype=np.int16)
                    on_rgb = np.asarray(on.convert("RGB"), dtype=np.int16)
                delta = np.clip(np.maximum(on_rgb - off_rgb, 0) * 4, 0, 255).astype(np.uint8)
                delta_image = Image.fromarray(delta)
                if delta_image.size != (500, 500):
                    delta_image = delta_image.resize((500, 500), Image.Resampling.NEAREST)
                canvas.paste(delta_image, (x, y + 32))
                continue
            with Image.open(path) as loaded:
                if index in (0, 1):
                    crop = loaded.convert("RGBA").crop((100, 120, 300, 320))
                    crop = crop.resize((500, 500), Image.Resampling.NEAREST)
                    canvas.paste(crop, (x, y + 32), crop)
                else:
                    image = loaded.convert("RGB")
                    if image.size != (500, 500):
                        image = image.resize((500, 500), Image.Resampling.NEAREST)
                    canvas.paste(image, (x, y + 32))
        frames.append(canvas)
    gif = output / "beholder_v14_review.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=220,
                   loop=0, disposal=2, optimize=False)
    return gif


def run(args: argparse.Namespace) -> Path:
    name = args.name or f"unity_attack_{datetime.now():%Y%m%d_%H%M%S}"
    output = (OUTPUT_ROOT / name).resolve()
    if output.parent != OUTPUT_ROOT.resolve() or output.exists():
        raise ValueError("new output directory must be directly under the fresh repair artifact root")
    unity = Path(args.unity or os.environ.get("UNITY_EDITOR") or UNITY)
    if not unity.is_file():
        raise FileNotFoundError(f"Unity Editor unavailable: {unity}")
    output.mkdir(parents=True)
    runtime = validate_and_prepare(output)
    if args.prepare_only:
        return output / "runtime_spec.json"
    target = PROJECT / "Assets" / "Editor" / EDITOR_SCRIPT.name
    if target.exists() and sha256(target) != sha256(EDITOR_SCRIPT):
        raise FileExistsError(f"different Editor script already exists: {target}")
    if not target.exists():
        shutil.copy2(EDITOR_SCRIPT, target)
    command = [str(unity), "-batchmode", "-quit", "-projectPath", str(PROJECT),
               "-executeMethod", "OldenEra.Homm3Import.BeholderAttackContourV14.RenderFromBatch",
               "-beholderAttackRepairSpec", str(output / "runtime_spec.json"),
               "-beholderAttackRepairOut", str(output), "-logFile", str(output / "unity_editor.log")]
    # The queue's preflight replaces the old tasklist refusal; --unity-direct is the explicit, loudly logged opt-out.
    completed = _unity_queue().run_cmd(command, kind="beholder_attack_contour_v14", timeout_s=args.timeout,
                                       direct=args.unity_direct)
    (output / "unity_process_output.txt").write_text(completed.stdout + "\n--- stderr ---\n" + completed.stderr,
                                                       encoding="utf-8")
    report_path = output / "preview_report.json"
    if completed.returncode or not report_path.is_file():
        log = output / "unity_editor.log"
        tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]) if log.is_file() else "no Unity log"
        raise RuntimeError(f"Unity attack proof failed (exit {completed.returncode}); output {output}\n{tail}")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    validate_unity_report(report, runtime, output)
    review_metrics(report, runtime, output)
    gif = make_gif(runtime, output)
    hashes = {str(path.relative_to(output)).replace("\\", "/"): sha256(path)
              for path in output.rglob("*") if path.is_file() and path.name != "hashes.json"}
    (output / "hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")
    return gif


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", help="new child directory under the repair artifact root")
    parser.add_argument("--unity", help="Unity.exe path")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--unity-direct", action="store_true",
                        help="explicit opt-out: launch Unity directly instead of submitting to the Unity queue")
    try:
        print(run(parser.parse_args()))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"beholder_attack_repair_sol_v1: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
