#!/usr/bin/env python3
"""Register the idle T2 mesh to its source sprite, then test rigid skeleton fit.

This iteration is static only. It does not fit skin weights, optimize animation,
generate a mesh, write an accepted bind GLB, or deploy. Generated-artifact only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

EXPERIMENT = Path(__file__).resolve().parent
if str(EXPERIMENT) not in sys.path:
    sys.path.insert(0, str(EXPERIMENT))
_TOOL = EXPERIMENT.parents[1] / "tools/homm3_silhouette_pose_fit"
if str(_TOOL) not in sys.path:
    sys.path.insert(0, str(_TOOL))

from asset_profiles import get_profile  # noqa: E402
from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from paths import REPO  # noqa: E402
from pin import sha256_file  # noqa: E402
from prepare_move_bind_capture_bind import frame0_rest_skeleton, load_capture  # noqa: E402
from roc_copy import _load_unskinned_triangle_surface  # noqa: E402
from run_skin_weight_pilot import shared_canvas_source_images  # noqa: E402
from skin_camera_registration import _bbox_scale_offset, _camera, _target_bbox  # noqa: E402
from skin_image_objective import SkinImageRenderer, image_loss  # noqa: E402
from static_bind_registration import (  # noqa: E402
    CANONICAL_VIEW_PITCH_DEG,
    CANONICAL_VIEW_YAW_DEG,
    IOU_AMBIGUITY_SLACK,
    SCHEMA,
    SOURCE_VIEW_POLICY,
    apply_similarity,
    branch_placement_report,
    canonical_source_view_basis,
    decide_static_outcome,
    distinct_view_candidates,
    evaluate_rigid_compatibility,
    fit_skeleton_similarity,
    require_mesh_space_rest_report,
    mesh_space_rest_similarity,
    joint_groups,
    project_points,
    rotation_matrix,
    source_matches_render_canvas,
)

DEFAULT_MESH = REPO / "artifacts/homm3_mocap_v2/roc_idle_bind_t2_v1/meshes/h3_roc_idle_bind_t2.glb"
DEFAULT_SPRITE = REPO / "artifacts/homm3_mocap_v2/skin_mesh_pilot/corpus_v2/g02_idle/000.png"
DEFAULT_CAPTURE = REPO / "artifacts/homm3_mocap_v2/roc_linked_master_idle_bind_v1/capture/capture/raw_capture.npz"
FALLBACK_CAPTURE = REPO / "artifacts/homm3_mocap_v2/roc_linked_master_v2/capture/capture/raw_capture.npz"
DEFAULT_OUT = REPO / "artifacts/homm3_mocap_v2/roc_idle_static_bind_v1"
DEFAULT_UNIT = "h3_roc"
RESOLUTION = 192
COARSE_YAWS = tuple(range(0, 360, 45))
COARSE_PITCHES = (-20.0, 0.0, 20.0)
COARSE_ROLLS = (-20.0, 0.0, 20.0)
REFINE_YAW = (-10.0, 0.0, 10.0)
REFINE_PITCH = (-10.0, 0.0, 10.0)
REFINE_ROLL = (-10.0, 0.0, 10.0)
REFINE_SCALE = (0.92, 1.0, 1.08)
REFINE_OFFSET = (-0.02, 0.0, 0.02)
TURNTABLE_YAWS = tuple(range(0, 360, 30))
BRANCH_COLORS = {
    "torso": (220, 220, 220),
    "neck_head": (255, 80, 80),
    "beak": (255, 200, 0),
    "tail": (80, 200, 255),
    "wing_left": (80, 255, 80),
    "wing_right": (255, 120, 255),
    "leg_left": (255, 160, 60),
    "leg_right": (160, 100, 255),
}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _as_numpy(value: Any) -> np.ndarray:
    detach = getattr(value, "detach", None)
    if callable(detach):
        value = detach()
    cpu = getattr(value, "cpu", None)
    if callable(cpu):
        value = cpu()
    numpy = getattr(value, "numpy", None)
    if callable(numpy):
        value = numpy()
    return np.asarray(value)


def _u8_rgb(image: np.ndarray) -> np.ndarray:
    array = np.clip(np.asarray(image, dtype=np.float64), 0.0, 1.0)
    return np.uint8(np.round(array * 255.0))


def _panel(image: np.ndarray) -> Image.Image:
    return Image.fromarray(_u8_rgb(image), mode="RGB")


def _labeled(image: Image.Image, text: str) -> Image.Image:
    canvas = Image.new("RGB", (image.width, image.height + 22), (12, 12, 16))
    canvas.paste(image, (0, 22))
    ImageDraw.Draw(canvas).text((4, 4), text, fill=(220, 220, 230))
    return canvas


def _hstack(images: list[Image.Image]) -> Image.Image:
    width = sum(image.width for image in images)
    height = max(image.height for image in images)
    canvas = Image.new("RGB", (width, height), (12, 12, 16))
    x = 0
    for image in images:
        canvas.paste(image, (x, 0))
        x += image.width
    return canvas


def _vstack(images: list[Image.Image]) -> Image.Image:
    width = max(image.width for image in images)
    height = sum(image.height for image in images)
    canvas = Image.new("RGB", (width, height), (12, 12, 16))
    y = 0
    for image in images:
        canvas.paste(image, (0, y))
        y += image.height
    return canvas


def _camera_for(vertices: np.ndarray, basis: np.ndarray, scale: float, offset: np.ndarray, source_size, crop, resolution: int) -> dict[str, Any]:
    return _camera(
        basis,
        scale=float(scale),
        offset=np.asarray(offset, dtype=np.float64),
        vertices=vertices,
        source_size=source_size,
        source_crop=crop,
        resolution=int(resolution),
        yaw_deg=CANONICAL_VIEW_YAW_DEG,
        pitch_deg=CANONICAL_VIEW_PITCH_DEG,
    )


def _score_orientation(
    *,
    renderer: SkinImageRenderer,
    vertices: np.ndarray,
    rotation: np.ndarray,
    yaw_deg: float,
    pitch_deg: float,
    roll_deg: float,
    targets: tuple[Any, Any, Any],
    basis: np.ndarray,
    target_bbox: tuple[float, float, float, float],
    source_size,
    crop,
    resolution: int,
    scale_factor: float = 1.0,
    offset_factor: tuple[float, float] = (0.0, 0.0),
) -> dict[str, Any]:
    rotated = np.asarray(vertices, dtype=np.float64) @ np.asarray(rotation, dtype=np.float64).T
    scale, offset = _bbox_scale_offset(rotated, basis, target_bbox)
    scale *= float(scale_factor)
    offset = offset + np.asarray(offset_factor, dtype=np.float64) * float(resolution)
    camera = _camera_for(rotated, basis, scale, offset, source_size, crop, resolution)
    renderer.set_camera(camera)
    rgb, alpha = renderer.render(rotated[None])
    source_matches_render_canvas(_as_numpy(targets[0])[0], _as_numpy(rgb)[0])
    loss = image_loss(rgb, alpha, targets[0], targets[1], targets[2])
    return {
        "yawDeg": float(yaw_deg),
        "pitchDeg": float(pitch_deg),
        "rollDeg": float(roll_deg),
        "rotation": np.asarray(rotation, dtype=np.float64),
        "projectionScale": float(scale),
        "imageTranslationPx": np.asarray(offset, dtype=np.float64),
        "scaleFactor": float(scale_factor),
        "offsetFactor": [float(offset_factor[0]), float(offset_factor[1])],
        "iou": float(_as_numpy(loss["iou"])),
        "total": float(_as_numpy(loss["total"])),
        "silhouette": float(_as_numpy(loss["silhouette"])),
        "color": float(_as_numpy(loss["color"])),
        "camera": camera,
        "rotated": rotated,
        "rgb": _as_numpy(rgb)[0],
        "alpha": _as_numpy(alpha)[0, ..., 0],
    }


def _search_views(
    *,
    renderer: SkinImageRenderer,
    vertices: np.ndarray,
    targets: tuple[Any, Any, Any],
    basis: np.ndarray,
    target_bbox: tuple[float, float, float, float],
    source_size,
    crop,
    resolution: int,
) -> tuple[dict[str, Any], int]:
    scored: list[dict[str, Any]] = []
    evaluations = 0
    for yaw in COARSE_YAWS:
        for pitch in COARSE_PITCHES:
            for roll in COARSE_ROLLS:
                if len(scored) % 18 == 0:
                    print(f"static-bind coarse {len(scored)}/72", flush=True)
                scored.append(
                    _score_orientation(
                        renderer=renderer,
                        vertices=vertices,
                        rotation=rotation_matrix(yaw, pitch, roll),
                        yaw_deg=yaw,
                        pitch_deg=pitch,
                        roll_deg=roll,
                        targets=targets,
                        basis=basis,
                        target_bbox=target_bbox,
                        source_size=source_size,
                        crop=crop,
                        resolution=resolution,
                    )
                )
                evaluations += 1
    views = distinct_view_candidates(scored)
    refined: list[dict[str, Any]] = []
    for seed in views["candidates"]:
        best = seed
        for dy in REFINE_YAW:
            for dp in REFINE_PITCH:
                for dr in REFINE_ROLL:
                    yaw = seed["yawDeg"] + dy
                    pitch = seed["pitchDeg"] + dp
                    roll = seed["rollDeg"] + dr
                    rotation = rotation_matrix(yaw, pitch, roll)
                    for scale_factor in REFINE_SCALE:
                        for dx in REFINE_OFFSET:
                            for dy_off in REFINE_OFFSET:
                                candidate = _score_orientation(
                                    renderer=renderer,
                                    vertices=vertices,
                                    rotation=rotation,
                                    yaw_deg=yaw,
                                    pitch_deg=pitch,
                                    roll_deg=roll,
                                    targets=targets,
                                    basis=basis,
                                    target_bbox=target_bbox,
                                    source_size=source_size,
                                    crop=crop,
                                    resolution=resolution,
                                    scale_factor=scale_factor,
                                    offset_factor=(dx, dy_off),
                                )
                                evaluations += 1
                                if evaluations % 200 == 0:
                                    print(f"static-bind evaluations={evaluations}", flush=True)
                                if candidate["total"] < best["total"] - 1e-6 or (
                                    abs(candidate["total"] - best["total"]) <= 1e-6 and candidate["iou"] > best["iou"]
                                ):
                                    best = candidate
        refined.append(best)
    return distinct_view_candidates(refined), evaluations


def _draw_skeleton_on_image(
    rgb: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    names: list[str],
    groups: dict[str, list[int]],
    *,
    basis: np.ndarray,
    scale: float,
    offset: np.ndarray,
) -> np.ndarray:
    pixels = project_points(joints, basis=basis, scale=scale, offset=offset)
    image = Image.fromarray(_u8_rgb(rgb), mode="RGB")
    draw = ImageDraw.Draw(image)
    name_region = {names[index]: region for region, indices in groups.items() for index in indices}
    for child, parent in enumerate(parents):
        if int(parent) < 0:
            continue
        region = name_region.get(names[child], "torso")
        color = BRANCH_COLORS.get(region, (255, 255, 255))
        x0, y0 = pixels[int(parent)]
        x1, y1 = pixels[child]
        draw.line([(float(x0), float(y0)), (float(x1), float(y1))], fill=color, width=2)
    for index, (x, y) in enumerate(pixels):
        region = name_region.get(names[index], "torso")
        color = BRANCH_COLORS.get(region, (255, 255, 255))
        draw.ellipse((float(x) - 2, float(y) - 2, float(x) + 2, float(y) + 2), fill=color)
    return np.asarray(image, dtype=np.float64) / 255.0


def _orthographic_panel(
    vertices: np.ndarray,
    joints: np.ndarray,
    parents: np.ndarray,
    names: list[str],
    groups: dict[str, list[int]],
    axes: tuple[int, int],
    title: str,
    size: int = 220,
) -> Image.Image:
    allpts = np.concatenate([vertices, joints], axis=0)
    lo = allpts.min(axis=0)
    span = float(np.ptp(allpts, axis=0).max())
    pad = 16

    def project(points: np.ndarray) -> np.ndarray:
        x = (points[:, axes[0]] - lo[axes[0]]) / max(span, 1e-8) * (size - 2 * pad) + pad
        y = size - ((points[:, axes[1]] - lo[axes[1]]) / max(span, 1e-8) * (size - 2 * pad) + pad)
        return np.stack([x, y], axis=1)

    image = Image.new("RGB", (size, size + 22), (10, 10, 14))
    draw = ImageDraw.Draw(image)
    draw.text((4, 4), title, fill=(220, 220, 230))
    mesh_px = project(vertices)
    for x, y in mesh_px[:: max(1, len(mesh_px) // 2500)]:
        draw.point((float(x), float(y) + 22), fill=(70, 80, 95))
    name_region = {names[index]: region for region, indices in groups.items() for index in indices}
    joint_px = project(joints)
    for child, parent in enumerate(parents):
        if int(parent) < 0:
            continue
        color = BRANCH_COLORS.get(name_region.get(names[child], "torso"), (255, 255, 255))
        x0, y0 = joint_px[int(parent)]
        x1, y1 = joint_px[child]
        draw.line([(float(x0), float(y0) + 22), (float(x1), float(y1) + 22)], fill=color, width=2)
    return image


def _write_turntable(
    path: Path,
    *,
    renderer: SkinImageRenderer,
    rotated: np.ndarray,
    camera: dict[str, Any],
    source_rgb: np.ndarray,
) -> None:
    frames = []
    center = rotated.mean(axis=0)
    renderer.set_camera(camera)
    for yaw in TURNTABLE_YAWS:
        spin = rotation_matrix(yaw, 0.0, 0.0)
        posed = (rotated - center) @ spin.T + center
        rgb, _alpha = renderer.render(posed[None])
        mesh = _as_numpy(rgb)[0]
        source_matches_render_canvas(source_rgb, mesh)
        frame = _hstack(
            [
                _labeled(_panel(source_rgb), "source (fixed)"),
                _labeled(_panel(mesh), f"registered mesh yaw {yaw}"),
                _labeled(_panel(0.5 * source_rgb + 0.5 * mesh), "overlay"),
            ]
        )
        frames.append(frame)
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=120, loop=0)


def _candidate_public(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "yawDeg": row["yawDeg"],
        "pitchDeg": row["pitchDeg"],
        "rollDeg": row["rollDeg"],
        "rotation": np.asarray(row["rotation"]).tolist(),
        "projectionScale": row["projectionScale"],
        "imageTranslationPx": np.asarray(row["imageTranslationPx"]).tolist(),
        "iou": row["iou"],
        "total": row["total"],
        "silhouette": row["silhouette"],
        "color": row["color"],
        "sourceViewPolicy": SOURCE_VIEW_POLICY,
        "canonicalCameraYawDeg": CANONICAL_VIEW_YAW_DEG,
        "canonicalCameraPitchDeg": CANONICAL_VIEW_PITCH_DEG,
    }


def run(
    *,
    mesh_glb: Path,
    sprite: Path,
    capture_path: Path,
    output_dir: Path,
    unit: str,
    bind_frame: int,
    resolution: int,
    overwrite: bool,
    mesh_space_rest_report: Path | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"refusing to overwrite {output_dir} (pass --overwrite)")
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    if not mesh_glb.is_file():
        raise FileNotFoundError(mesh_glb)
    if not sprite.is_file():
        raise FileNotFoundError(sprite)
    if not capture_path.is_file():
        raise FileNotFoundError(capture_path)

    profile = get_profile(unit)
    region_joints = {str(region): [str(bone) for bone in bones] for region, bones in profile["regionJoints"].items()}
    surface = _load_unskinned_triangle_surface(mesh_glb)
    vertices = np.asarray(surface["vertices"], dtype=np.float64)
    capture = load_capture(capture_path)
    rest = frame0_rest_skeleton(capture, bind_frame=bind_frame)
    names = list(capture["names"])
    groups = joint_groups(names, region_joints)
    rest_provenance = None
    if mesh_space_rest_report is not None:
        rest_provenance = require_mesh_space_rest_report(
            json.loads(mesh_space_rest_report.read_text(encoding="utf-8")),
            mesh_sha256=sha256_file(mesh_glb), capture_sha256=capture["sha256"],
            unit=unit, bind_frame=bind_frame)
    basis = canonical_source_view_basis()

    with cascade_batch_lock(REPO):
        targets, crop, source_size = shared_canvas_source_images([sprite], resolution)
        source_rgb = _as_numpy(targets[0])[0]
        source_alpha = _as_numpy(targets[1])[0, ..., 0]
        target_bbox = _target_bbox(source_alpha)
        renderer = SkinImageRenderer(
            np.asarray(surface["triangles"], dtype=np.int32),
            np.asarray(surface["uvs"], dtype=np.float64),
            np.asarray(surface["albedo"]),
            _camera_for(vertices, basis, 1.0, np.zeros(2), source_size, crop, resolution),
            resolution,
        )
        views, evaluations = _search_views(
            renderer=renderer,
            vertices=vertices,
            targets=targets,
            basis=basis,
            target_bbox=target_bbox,
            source_size=source_size,
            crop=crop,
            resolution=resolution,
        )
        evidence_rows = []
        compatibility_by_view = []
        comparison_rows = []
        for index, candidate in enumerate(views["candidates"]):
            prefix = f"view_{index:02d}_y{candidate['yawDeg']:.0f}_p{candidate['pitchDeg']:.0f}_r{candidate['rollDeg']:.0f}"
            mesh_rgb = candidate["rgb"]
            overlay = 0.5 * source_rgb + 0.5 * mesh_rgb
            source_matches_render_canvas(source_rgb, mesh_rgb)
            triplet = _hstack(
                [
                    _labeled(_panel(source_rgb), "source sprite"),
                    _labeled(_panel(mesh_rgb), f"textured mesh IoU {candidate['iou']:.3f}"),
                    _labeled(_panel(overlay), "overlay"),
                ]
            )
            triplet_path = output_dir / f"{prefix}_source_mesh_overlay.png"
            triplet.save(triplet_path)
            turntable_path = output_dir / f"{prefix}_turntable.gif"
            _write_turntable(
                turntable_path,
                renderer=renderer,
                rotated=candidate["rotated"],
                camera=candidate["camera"],
                source_rgb=source_rgb,
            )
            if rest_provenance is not None:
                similarity = mesh_space_rest_similarity(
                    rest["joints"], candidate["rotated"], groups, rotation=candidate["rotation"],
                    yaw_deg=candidate["yawDeg"], pitch_deg=candidate["pitchDeg"], roll_deg=candidate["rollDeg"])
            else:
                similarity = fit_skeleton_similarity(rest["joints"], candidate["rotated"], groups)
            placed = similarity["joints"]
            placement = branch_placement_report(
                joints=placed, names=names, vertices=candidate["rotated"], groups=groups
            )
            compatibility = evaluate_rigid_compatibility(
                joints=placed,
                names=names,
                vertices=candidate["rotated"],
                groups=groups,
                placement=placement,
            )
            skel_source = _draw_skeleton_on_image(
                source_rgb,
                placed,
                capture["parents"],
                names,
                groups,
                basis=basis,
                scale=candidate["projectionScale"],
                offset=candidate["imageTranslationPx"],
            )
            skel_mesh = _draw_skeleton_on_image(
                mesh_rgb,
                placed,
                capture["parents"],
                names,
                groups,
                basis=basis,
                scale=candidate["projectionScale"],
                offset=candidate["imageTranslationPx"],
            )
            skeleton_pair = _hstack(
                [
                    _labeled(_panel(skel_source), "skeleton on source"),
                    _labeled(_panel(skel_mesh), "skeleton on registered mesh"),
                ]
            )
            skeleton_pair_path = output_dir / f"{prefix}_skeleton_source_mesh.png"
            skeleton_pair.save(skeleton_pair_path)
            ortho = _hstack(
                [
                    _orthographic_panel(candidate["rotated"], placed, capture["parents"], names, groups, (0, 1), "front XY"),
                    _orthographic_panel(candidate["rotated"], placed, capture["parents"], names, groups, (2, 1), "side ZY"),
                    _orthographic_panel(candidate["rotated"], placed, capture["parents"], names, groups, (0, 2), "top XZ"),
                ]
            )
            ortho_path = output_dir / f"{prefix}_relative_front_side_top.png"
            ortho.save(ortho_path)
            comparison_rows.append(_vstack([triplet, skeleton_pair, ortho]))
            compatibility_by_view.append(compatibility)
            evidence_rows.append(
                {
                    "id": prefix,
                    "view": _candidate_public(candidate),
                    "meshToSourceView": {
                        "rotation": np.asarray(candidate["rotation"]).tolist(),
                        "yawPitchRollDeg": [candidate["yawDeg"], candidate["pitchDeg"], candidate["rollDeg"]],
                        "projectionScale": candidate["projectionScale"],
                        "imageTranslationPx": np.asarray(candidate["imageTranslationPx"]).tolist(),
                        "policy": SOURCE_VIEW_POLICY,
                    },
                    "skeletonSimilarity": {
                        "rotation": np.asarray(similarity["rotation"]).tolist(),
                        "yawPitchRollDeg": [similarity["yawDeg"], similarity["pitchDeg"], similarity["rollDeg"]],
                        "scale": similarity["scale"],
                        "translation": np.asarray(similarity["translation"]).tolist(),
                        "bodySurfaceMean": similarity["bodySurfaceMean"],
                        "branchBalancedSurfaceMean": similarity["branchBalancedSurfaceMean"],
                        "branchSurfaceMeans": similarity["branchSurfaceMeans"],
                        "skeletonToMeshExtentRatio": similarity["skeletonToMeshExtentRatio"],
                        "extentRatioBounds": similarity["extentRatioBounds"],
                        "policy": similarity["policy"],
                    },
                    "branchPlacement": placement,
                    "compatibility": compatibility,
                    "evidence": {
                        "sourceMeshOverlay": str(triplet_path).replace("\\", "/"),
                        "turntable": str(turntable_path).replace("\\", "/"),
                        "skeletonOnSourceAndMesh": str(skeleton_pair_path).replace("\\", "/"),
                        "relativeFrontSideTop": str(ortho_path).replace("\\", "/"),
                    },
                }
            )
            del candidate["rgb"], candidate["alpha"], candidate["rotated"], candidate["camera"], similarity["joints"]

    outcome = decide_static_outcome(views=views, compatibility_by_view=compatibility_by_view)
    sheet = _vstack(comparison_rows)
    header = Image.new("RGB", (sheet.width, 36), (12, 12, 16))
    ImageDraw.Draw(header).text(
        (6, 10),
        f"static bind {outcome['status']}  views={len(evidence_rows)}  visualConfirmation=false  consumable=false",
        fill=(240, 240, 245),
    )
    sheet_path = output_dir / "static_comparison_sheet.png"
    _vstack([header, sheet]).save(sheet_path)
    elapsed = time.perf_counter() - started
    report = {
        "schema": SCHEMA,
        "unit": unit,
        "bindFrame": int(bind_frame),
        "meshSpaceRestProvenance": None if rest_provenance is None else {
            "path": str(mesh_space_rest_report), "sha256": sha256_file(mesh_space_rest_report),
            "report": rest_provenance, "doesNotProveAcceptance": True},
        "proof": "generated-artifact - static registration and rigid skeleton compatibility only; not OE runtime",
        "inputs": {
            "mesh": str(mesh_glb).replace("\\", "/"),
            "sprite": str(sprite).replace("\\", "/"),
            "capture": str(capture_path).replace("\\", "/"),
        },
        "inputHashes": {
            "mesh": sha256_file(mesh_glb),
            "sprite": sha256_file(sprite),
            "capture": capture["sha256"],
        },
        "sourceView": {
            "policy": SOURCE_VIEW_POLICY,
            "canonicalCameraYawDeg": CANONICAL_VIEW_YAW_DEG,
            "canonicalCameraPitchDeg": CANONICAL_VIEW_PITCH_DEG,
            "sharedCanvas": {"sourceSize": [int(source_size[0]), int(source_size[1])], "crop": dict(crop)},
            "resolution": int(resolution),
            "doesNotInheritFlightAxes": True,
            "doesNotUseLegacyCameraAngles": True,
        },
        "search": {
            "coarseYawDeg": list(COARSE_YAWS),
            "coarsePitchDeg": list(COARSE_PITCHES),
            "coarseRollDeg": list(COARSE_ROLLS),
            "evaluations": int(evaluations),
            "iouAmbiguitySlack": IOU_AMBIGUITY_SLACK,
        },
        "views": {
            "ambiguousOrientation": views["ambiguousOrientation"],
            "selectedAutomatically": False,
            "reason": views["reason"],
            "candidates": evidence_rows,
        },
        "acceptance": outcome,
        "evidence": {
            "comparisonSheet": str(sheet_path).replace("\\", "/"),
        },
        "elapsedSeconds": elapsed,
        "didNotWriteAcceptedBindGlb": True,
        "didNotFitSkinOrMotion": True,
    }
    report_path = output_dir / "static_bind_registration.json"
    _write_json(report_path, report)
    print(
        json.dumps(
            {
                "status": outcome["status"],
                "accepted": False,
                "consumable": False,
                "ambiguousOrientation": views["ambiguousOrientation"],
                "viewCount": len(evidence_rows),
                "comparisonSheet": str(sheet_path).replace("\\", "/"),
                "report": str(report_path).replace("\\", "/"),
                "elapsedSeconds": round(elapsed, 3),
            },
            indent=2,
        ),
        flush=True,
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mesh", type=Path, default=DEFAULT_MESH)
    parser.add_argument("--sprite", type=Path, default=DEFAULT_SPRITE)
    parser.add_argument("--capture", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--unit", default=DEFAULT_UNIT)
    parser.add_argument("--bind-frame", type=int, default=0)
    parser.add_argument("--mesh-space-rest-report", type=Path)
    parser.add_argument("--resolution", type=int, default=RESOLUTION)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    def absolute(path: Path) -> Path:
        return (path if path.is_absolute() else REPO / path).resolve()

    capture = args.capture
    if capture is None:
        capture = DEFAULT_CAPTURE if DEFAULT_CAPTURE.is_file() else FALLBACK_CAPTURE
    run(
        mesh_glb=absolute(args.mesh),
        sprite=absolute(args.sprite),
        capture_path=absolute(capture),
        output_dir=absolute(args.output),
        unit=args.unit,
        bind_frame=int(args.bind_frame),
        mesh_space_rest_report=absolute(args.mesh_space_rest_report) if args.mesh_space_rest_report is not None else None,
        resolution=int(args.resolution),
        overwrite=bool(args.overwrite),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
