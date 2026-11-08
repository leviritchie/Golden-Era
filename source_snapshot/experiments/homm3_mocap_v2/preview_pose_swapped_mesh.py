#!/usr/bin/env python3
"""Preview a pose-conditioned Roc mesh swap without touching delivery assets.

The flight-shaped Meshy T2 surface is aligned to the existing capture-bind
skeleton, weighted by nearest capture joints, and replayed through the saved
g13_attack_down capture. The original move-bind surface is rendered beside it
as a control. This is generated-candidate evidence for the mesh-swap idea;
the simple preview weights are not a shipping bind.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "tools/homm3_silhouette_pose_fit"))

from gpu_cascade_batch_lock import cascade_batch_lock  # noqa: E402
from reconstruct_ab import reconstruct_ab  # noqa: E402
from run_move_bind_t2_mocap_skin_fit import load_skin_bundle  # noqa: E402
from run_roc_move_bind_t2_mocap import load_glb_surface  # noqa: E402
from run_skin_weight_pilot import skin_with  # noqa: E402
from skin_image_objective import SkinImageRenderer  # noqa: E402


DEFAULT_BIND = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1/capture_bind/h3_roc_move_bind_t2_capture_f0_bind.glb"
DEFAULT_MESH = REPO / "artifacts/homm3_mocap_v2/roc_attack_down_bind_t2_v1/meshes/idle_f0.glb"
DEFAULT_CORPUS = REPO / "artifacts/homm3_mocap_v2/skin_mesh_pilot/captures_v2/corpus.json"
DEFAULT_CAMERA = REPO / "artifacts/homm3_mocap_v2/roc_move_bind_t2_v1/capture_skin_fit/camera.json"
DEFAULT_OUT = REPO / "artifacts/homm3_mocap_v2/roc_attack_down_bind_t2_v1/preview"


def _weights(vertices: np.ndarray, joints: np.ndarray, k: int = 4) -> np.ndarray:
    distance = np.linalg.norm(vertices[:, None, :] - joints[None, :, :], axis=2)
    nearest = np.argpartition(distance, kth=k - 1, axis=1)[:, :k]
    picked = np.take_along_axis(distance, nearest, axis=1)
    values = 1.0 / (picked * picked + 1e-8)
    values /= values.sum(axis=1, keepdims=True)
    result = np.zeros((len(vertices), len(joints)), dtype=np.float64)
    result[np.repeat(np.arange(len(vertices)), k), nearest.reshape(-1)] = values.reshape(-1)
    return result


def _align_surface(vertices: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, dict]:
    source_center = vertices.mean(axis=0)
    target_center = target.mean(axis=0)
    source_span = vertices.max(axis=0) - vertices.min(axis=0)
    target_span = target.max(axis=0) - target.min(axis=0)
    scale = float(np.median(target_span / np.maximum(source_span, 1e-9)))
    aligned = (vertices - source_center) * scale + target_center
    return aligned, {"policy": "uniform_aabb_center", "scale": scale, "sourceSpan": source_span.tolist(), "targetSpan": target_span.tolist()}


def _letterbox(path: Path, resolution: int) -> np.ndarray:
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        box = rgba.getbbox()
        if box is None:
            raise ValueError(f"empty sprite: {path}")
        crop = rgba.crop(box)
    scale = min(resolution / crop.width, resolution / crop.height)
    size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
    resized = crop.resize(size, Image.Resampling.NEAREST)
    canvas = Image.new("RGBA", (resolution, resolution), (0, 0, 0, 255))
    canvas.paste(resized, ((resolution - size[0]) // 2, (resolution - size[1]) // 2), resized)
    values = np.asarray(canvas, dtype=np.float32) / 255.0
    return values[..., :3] * values[..., 3:4]


def _camera(base: dict, posed: np.ndarray, resolution: int) -> dict:
    right = np.asarray(base["right"], dtype=np.float64)
    down = np.asarray(base["down"], dtype=np.float64)
    forward = np.asarray(base["forward"], dtype=np.float64)
    points = posed.reshape(-1, 3)
    x, y, z = points @ right, points @ down, points @ forward
    span = max(float(x.max() - x.min()), float(y.max() - y.min()), 1e-6) * 1.12
    scale = resolution / span
    return {**base, "scale": scale, "offset": [resolution / 2 - scale * float((x.min() + x.max()) / 2), resolution / 2 - scale * float((y.min() + y.max()) / 2)], "depth_center": float((z.min() + z.max()) / 2), "depth_span": float(max(z.max() - z.min(), 1e-3) * 1.2), "resolution": resolution}


def _rotate_outer_wing_tips(frame: np.ndarray, camera: dict, source_slopes: dict[float, float]) -> tuple[np.ndarray, dict]:
    """Rotate each outer wing about its attachment toward a camera-space target.

    This is a bounded preview correction for a pose-conditioned candidate. It derives
    the attachment and tip from lateral silhouette partitions instead of Roc-specific
    vertex ids, and leaves the inner torso/root region fixed.
    """
    right = np.asarray(camera["right"], dtype=np.float64)
    down = np.asarray(camera["down"], dtype=np.float64)
    x = frame @ right
    y = frame @ down
    center = float(np.median(x))
    lateral = np.abs(x - center)
    span = max(float(lateral.max()), 1e-6)
    inner_limit = span * 0.28
    outer_limit = span * 0.82
    inner = lateral <= inner_limit
    outer = lateral >= inner_limit
    if int(inner.sum()) < 8 or int(outer.sum()) < 8:
        return frame, {"applied": False, "reason": "insufficient_lateral_partition"}
    shoulder = float(np.median(y[inner]))
    vertical_span = max(float(np.percentile(y[inner], 90) - np.percentile(y[inner], 10)), 1e-6)
    head_height = vertical_span * 0.18
    shifted = frame.copy()
    side_reports = []
    for sign in (-1.0, 1.0):
        signed = (x - center) * sign
        side = signed >= inner_limit
        attach = (signed >= inner_limit * 0.90) & (signed <= inner_limit * 1.30)
        tip = signed >= max(outer_limit * 0.88, inner_limit * 1.8)
        if int(side.sum()) < 8 or int(attach.sum()) < 3 or int(tip.sum()) < 3:
            side_reports.append({"sign": sign, "applied": False, "reason": "insufficient_side_partition"})
            continue
        pivot_x = float(np.median(x[attach]))
        pivot_y = float(np.median(y[attach]))
        tip_x = float(np.median(x[tip]))
        tip_y = float(np.median(y[tip]))
        # Preserve the source sprite's independent shoulder-to-tip slope while
        # retaining this candidate's lateral reach.
        target = pivot_y + source_slopes[sign] * abs(tip_x - pivot_x)
        dx, dy = tip_x - pivot_x, tip_y - pivot_y
        radius = max(float(np.hypot(dx, dy)), 1e-6)
        desired_dy = target - pivot_y
        if abs(desired_dy) >= radius:
            desired_dy = float(np.sign(desired_dy) * radius * 0.96)
        desired_dx = float(sign * np.sqrt(max(radius * radius - desired_dy * desired_dy, 1e-12)))
        current_angle = float(np.arctan2(dy, dx))
        desired_angle = float(np.arctan2(desired_dy, desired_dx))
        delta = (desired_angle - current_angle + np.pi) % (2.0 * np.pi) - np.pi
        pivot_lateral = abs(pivot_x - center)
        # Taper from the actual attachment across the whole wing, not only
        # the outer feather band. The pivot itself remains fixed at weight 0.
        ramp = np.clip((signed - pivot_lateral) / max(outer_limit - pivot_lateral, 1e-6), 0.0, 1.0)
        idx = np.flatnonzero(side)
        rel_x = x[idx] - pivot_x
        rel_y = y[idx] - pivot_y
        cos_d, sin_d = np.cos(delta * ramp[idx]), np.sin(delta * ramp[idx])
        rotated_x = pivot_x + cos_d * rel_x - sin_d * rel_y
        rotated_y = pivot_y + sin_d * rel_x + cos_d * rel_y
        shifted[idx] += ((rotated_x - x[idx])[:, None] * right[None, :] +
                         (rotated_y - y[idx])[:, None] * down[None, :])
        sample = idx[::max(1, len(idx) // 24)]
        side_reports.append({"sign": sign, "applied": True, "pivot": [pivot_x, pivot_y], "pivotLateral": pivot_lateral, "tipBefore": [tip_x, tip_y], "targetPoint": [tip_x, target], "tipTargetY": target, "angleDegrees": float(np.degrees(delta)), "outerPointsBefore": np.column_stack((x[sample], y[sample])).tolist(), "outerPointsAfter": np.column_stack((rotated_x[np.searchsorted(idx, sample)], rotated_y[np.searchsorted(idx, sample)])).tolist()})
    return shifted, {
        "applied": any(item.get("applied") for item in side_reports),
        "policy": "derived_camera_space_outer_wingtip_rotation",
        "innerLimit": inner_limit,
        "outerLimit": outer_limit,
        "shoulder": shoulder,
        "headHeight": head_height,
        "targetTipY": "sourceMatchedSlope",
        "sourceSlopes": {str(k): float(v) for k, v in source_slopes.items()},
        "sides": side_reports,
    }


def _camera_pixel(camera: dict, point: list[float], scale: int = 1) -> tuple[int, int]:
    px = camera["offset"][0] + camera["scale"] * float(point[0])
    py = camera["offset"][1] + camera["scale"] * float(point[1])
    return round(px * scale), round(py * scale)


def _source_wing_geometry(path: Path, resolution: int) -> dict:
    """Extract source wing slopes and shoulder/tip points in letterbox pixels."""
    with Image.open(path) as image:
        rgba = image.convert("RGBA")
        box = rgba.getbbox()
        if box is None:
            raise ValueError(f"empty source sprite: {path}")
        crop = rgba.crop(box)
    scale = min(resolution / crop.width, resolution / crop.height)
    size = (max(1, round(crop.width * scale)), max(1, round(crop.height * scale)))
    resized = crop.resize(size, Image.Resampling.NEAREST)
    alpha = np.zeros((resolution, resolution), dtype=np.uint8)
    left = (resolution - size[0]) // 2; top = (resolution - size[1]) // 2
    alpha[top:top + size[1], left:left + size[0]] = np.asarray(resized)[..., 3]
    ys, xs = np.nonzero(alpha >= 24)
    center = (resolution - 1) / 2.0
    lateral = np.abs(xs - center)
    span = max(float(lateral.max()), 1.0)
    slopes: dict[float, float] = {}
    points: dict[float, dict[str, list[float]]] = {}
    for sign in (-1.0, 1.0):
        signed = (xs - center) * sign
        tip = signed >= span * 0.78
        attach = (signed >= span * 0.20) & (signed <= span * 0.42)
        if int(tip.sum()) < 3 or int(attach.sum()) < 3:
            continue
        tip_x, tip_y = float(np.median(xs[tip])), float(np.median(ys[tip]))
        attach_x, attach_y = float(np.median(xs[attach])), float(np.percentile(ys[attach], 35))
        slopes[sign] = (tip_y - attach_y) / max(abs(tip_x - attach_x), 1.0)
        points[sign] = {"shoulder": [attach_x, attach_y], "tip": [tip_x, tip_y]}
    if len(slopes) != 2:
        raise ValueError(f"could not derive bilateral source wing slopes from {path}")
    return {"slopes": slopes, "points": points}


def _source_wing_slopes(path: Path, resolution: int) -> dict[float, float]:
    return _source_wing_geometry(path, resolution)["slopes"]


def _wingtip_diagnostic(before: np.ndarray, after: np.ndarray, image_before: np.ndarray,
                        image_after: np.ndarray, correction: dict, camera: dict,
                        resolution: int, path: Path, frame: int) -> None:
    """Write an enlarged f04 before/after panel with wing-selection markers."""
    zoom = 2
    panel = resolution * zoom
    canvas = Image.new("RGB", (panel * 2, panel + 34), (10, 10, 14))
    for col, (label, image) in enumerate((("before tip-target correction", image_before), ("after tip-target correction", image_after))):
        enlarged = Image.fromarray(np.uint8(np.clip(image, 0, 1) * 255)).resize((panel, panel), Image.Resampling.NEAREST)
        canvas.paste(enlarged, (col * panel, 34))
        ImageDraw.Draw(canvas).text((col * panel + 6, 8), f"g13_attack_down f{frame:02d} | {label}", fill=(220, 220, 230))
    draw = ImageDraw.Draw(canvas)
    for side in correction.get("sides", []):
        if not side.get("applied"):
            continue
        pivot = _camera_pixel(camera, side["pivot"], zoom)
        target = _camera_pixel(camera, side["targetPoint"], zoom)
        tip = _camera_pixel(camera, side["tipBefore"], zoom)
        for col, points_key in ((0, "outerPointsBefore"), (1, "outerPointsAfter")):
            ox = col * panel
            for point in side.get(points_key, []):
                x, y = _camera_pixel(camera, point, zoom)
                draw.ellipse((ox + x - 3, 34 + y - 3, ox + x + 3, 34 + y + 3), outline=(255, 235, 70), width=2)
            draw.ellipse((ox + pivot[0] - 6, 34 + pivot[1] - 6, ox + pivot[0] + 6, 34 + pivot[1] + 6), outline=(255, 70, 70), width=3)
            tx, ty = target if col else tip
            draw.line((ox + tx - 8, 34 + ty - 8, ox + tx + 8, 34 + ty + 8), fill=(255, 80, 220), width=3)
            draw.line((ox + tx - 8, 34 + ty + 8, ox + tx + 8, 34 + ty - 8), fill=(255, 80, 220), width=3)
    path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(path)


def _source_candidate_overlay(source: np.ndarray, candidate: np.ndarray, source_geometry: dict,
                              correction: dict, camera: dict, resolution: int, path: Path) -> None:
    """Align source/candidate torso scale and shoulder, then mark both wing slopes."""
    def mask(image: np.ndarray) -> np.ndarray:
        return np.max(image, axis=2) > 0.055
    src_mask, cand_mask = mask(source), mask(candidate)
    yy, xx = np.indices(src_mask.shape)
    center = (resolution - 1) / 2.0
    src_inner = src_mask & (np.abs(xx - center) <= resolution * 0.18)
    cy, cx = np.indices(cand_mask.shape)
    cand_inner = cand_mask & (np.abs(cx - center) <= resolution * 0.18)
    sy = np.flatnonzero(src_inner.any(axis=1)); cyv = np.flatnonzero(cand_inner.any(axis=1))
    if len(sy) < 2 or len(cyv) < 2:
        raise ValueError("could not derive torso alignment for overlay")
    src_h, cand_h = float(sy[-1] - sy[0]), float(cyv[-1] - cyv[0])
    scale = src_h / max(cand_h, 1.0)
    cand_size = (round(resolution * scale), round(resolution * scale))
    cand_img = Image.fromarray(np.uint8(np.clip(candidate, 0, 1) * 255)).resize(cand_size, Image.Resampling.BILINEAR)
    cand_alpha = Image.fromarray(np.uint8(mask(candidate) * 180)).resize(cand_size, Image.Resampling.NEAREST)
    cand_img.putalpha(cand_alpha)
    src_img = Image.fromarray(np.uint8(np.clip(source, 0, 1) * 255))
    # Align central torso x and the upper torso/shoulder anchor.
    src_shoulder_y = float(np.percentile(sy, 30)); cand_shoulder_y = float(np.percentile(cyv, 30)) * scale
    src_center_x = float(np.median(np.flatnonzero(src_inner.any(axis=0))))
    cand_center_x = float(np.median(np.flatnonzero(cand_inner.any(axis=0)))) * scale
    offset_x = src_center_x - cand_center_x; offset_y = src_shoulder_y - cand_shoulder_y
    overlay = Image.new("RGBA", (resolution, resolution), (0, 0, 0, 255)); overlay.paste(src_img.convert("RGBA"), (0, 0))
    cand_layer = Image.new("RGBA", (resolution, resolution), (0, 0, 0, 0)); cand_layer.paste(cand_img, (round(offset_x), round(offset_y)), cand_img)
    overlay = Image.alpha_composite(overlay, cand_layer).convert("RGB")
    zoom = 2; canvas = overlay.resize((resolution * zoom, resolution * zoom), Image.Resampling.NEAREST)
    draw = ImageDraw.Draw(canvas); draw.text((8, 8), "f04 source/candidate overlay | torso scale + shoulder aligned", fill=(255, 255, 255))
    for sign, geom in source_geometry["points"].items():
        sx, sy0 = geom["shoulder"]; tx, ty = geom["tip"]
        draw.line((sx * zoom, sy0 * zoom, tx * zoom, ty * zoom), fill=(70, 235, 255), width=3)
    for side in correction.get("sides", []):
        if side.get("applied"):
            px, py = _camera_pixel(camera, side["pivot"], zoom); tx, ty = _camera_pixel(camera, side["targetPoint"], zoom)
            draw.line((px, py, tx, ty), fill=(255, 80, 220), width=3)
    path.parent.mkdir(parents=True, exist_ok=True); canvas.save(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", type=Path, default=DEFAULT_BIND)
    parser.add_argument("--mesh", type=Path, default=DEFAULT_MESH)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--camera", type=Path, default=DEFAULT_CAMERA)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--resolution", type=int, default=256)
    parser.add_argument("--candidate-bind-frame", type=int, default=4,
                        help="capture frame used as the replacement mesh bind pose")
    parser.add_argument("--wing-elevation-frame", type=int, default=None,
                        help="optionally apply a derived outer-wing lift to this candidate frame")
    parser.add_argument("--swap-start", type=int, default=4)
    parser.add_argument("--swap-end", type=int, default=5)
    args = parser.parse_args()
    bind, mesh_path, corpus_path = (p.resolve() for p in (args.bind, args.mesh, args.corpus))
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    skin = load_skin_bundle(bind)
    candidate = load_glb_surface(mesh_path)
    corpus = json.loads(corpus_path.read_text(encoding="utf-8"))
    entries = {str(item["key"]): item for item in corpus["captures"]}
    key = "g13_attack_down"
    entry = entries[key]
    capture = np.load(Path(entry["capture"]), allow_pickle=False)
    names = [str(x) for x in capture["joint_names"]]
    order = np.asarray([names.index(name) for name in skin["names"]], dtype=np.int64)
    indices = np.asarray(entry["sourceIndices"], dtype=np.int64)
    positions = np.asarray(capture["pred_position"], dtype=np.float64)[indices][:, order]
    bind_frame = int(args.candidate_bind_frame)
    if not 0 <= bind_frame < len(positions):
        raise ValueError(f"candidate bind frame {bind_frame} is outside clip")
    # Bind the candidate at the source pose used to generate the Meshy
    # surface. The move-bind control retains its existing frame-0 skeleton.
    move_entry = entries["g00_move"]
    move_capture = np.load(Path(move_entry["capture"]), allow_pickle=False)
    move_names = [str(x) for x in move_capture["joint_names"]]
    move_order = np.asarray([move_names.index(name) for name in skin["names"]], dtype=np.int64)
    move_positions = np.asarray(move_capture["pred_position"], dtype=np.float64)[np.asarray(move_entry["sourceIndices"], dtype=np.int64)][:, move_order]
    move_ab = reconstruct_ab(capture_positions=move_positions, offsets=skin["offsets"], parents=skin["parents"], reference_frame=0)
    move_worlds = np.asarray(move_ab["jointWorldA"], dtype=np.float64)
    attack_ab = reconstruct_ab(capture_positions=positions, offsets=skin["offsets"], parents=skin["parents"], reference_frame=bind_frame)
    worlds = np.asarray(attack_ab["jointWorldA"], dtype=np.float64)
    move_transforms = torch.as_tensor(move_worlds @ skin["inverseBind"][None], dtype=torch.float32, device="cuda")
    candidate_inverse_bind = np.linalg.inv(worlds[bind_frame])
    bind_vertices_t = torch.as_tensor(np.column_stack((skin["vertices"], np.ones(len(skin["vertices"])))), dtype=torch.float32, device="cuda")
    control_transforms = torch.as_tensor(worlds @ skin["inverseBind"][None], dtype=torch.float32, device="cuda")
    old_candidates = torch.einsum("jkl,vl->vjk", control_transforms[bind_frame, :, :3, :], bind_vertices_t)
    old_bind = skin_with(old_candidates[None], torch.as_tensor(skin["weights"], dtype=torch.float32, device="cuda"))[0].cpu().numpy()
    candidate_vertices, align = _align_surface(candidate["vertices"], old_bind)
    candidate_joints = worlds[bind_frame, :, :3, 3]
    candidate_weights = _weights(candidate_vertices, candidate_joints)
    transforms = torch.as_tensor(worlds @ candidate_inverse_bind[None], dtype=torch.float32, device="cuda")
    candidate_vertices_t = torch.as_tensor(np.column_stack((candidate_vertices, np.ones(len(candidate_vertices)))), dtype=torch.float32, device="cuda")
    candidate_deformed = torch.einsum("fjkl,vl->fvjk", transforms[:, :, :3], candidate_vertices_t)
    original_deformed = torch.einsum("fjkl,vl->fvjk", control_transforms[:, :, :3], bind_vertices_t)
    camera_base = json.loads(args.camera.read_text(encoding="utf-8"))
    correction = {"applied": False, "reason": "disabled"}
    source_slopes = None
    source_geometry = None
    if args.wing_elevation_frame is not None:
        source_geometry = _source_wing_geometry(Path(entry["frames"][int(args.wing_elevation_frame)]), args.resolution)
        source_slopes = source_geometry["slopes"]
    before_posed = None
    before_images = None
    with cascade_batch_lock(REPO), torch.no_grad():
        posed = skin_with(candidate_deformed, torch.as_tensor(candidate_weights, dtype=torch.float32, device="cuda")).detach().cpu().numpy()
        original = skin_with(original_deformed, torch.as_tensor(skin["weights"], dtype=torch.float32, device="cuda")).detach().cpu().numpy()
        if args.wing_elevation_frame is not None:
            correction_frame = int(args.wing_elevation_frame)
            if not 0 <= correction_frame < len(posed):
                raise ValueError(f"wing elevation frame {correction_frame} is outside clip")
            before_posed = posed.copy()
            posed[correction_frame], correction = _rotate_outer_wing_tips(posed[correction_frame], camera_base, source_slopes)
        camera = _camera(camera_base, np.concatenate((posed.reshape(-1, 3), original.reshape(-1, 3))), args.resolution)
        new_renderer = SkinImageRenderer(candidate["triangles"], candidate["uvs"], candidate["albedo"], camera, args.resolution)
        old_renderer = SkinImageRenderer(skin["triangles"], skin["uvs"], skin["albedo"], camera, args.resolution)
        if before_posed is not None:
            before_rgb, before_alpha = new_renderer.render(torch.as_tensor(before_posed, dtype=torch.float32, device="cuda"))
            before_images = (before_rgb * before_alpha).cpu().numpy()
        new_rgb, new_alpha = new_renderer.render(torch.as_tensor(posed, dtype=torch.float32, device="cuda"))
        old_rgb, old_alpha = old_renderer.render(torch.as_tensor(original, dtype=torch.float32, device="cuda"))
        new_images = (new_rgb * new_alpha).cpu().numpy()
        old_images = (old_rgb * old_alpha).cpu().numpy()
    diagnostic_path = None
    overlay_path = None
    if before_posed is not None and before_images is not None and args.wing_elevation_frame is not None:
        diagnostic_path = out / f"f{int(args.wing_elevation_frame):02d}_wingtip_diagnostic.png"
        _wingtip_diagnostic(before_posed[int(args.wing_elevation_frame)], posed[int(args.wing_elevation_frame)], before_images[int(args.wing_elevation_frame)], new_images[int(args.wing_elevation_frame)], correction, camera, args.resolution, diagnostic_path, int(args.wing_elevation_frame))
        overlay_path = out / f"f{int(args.wing_elevation_frame):02d}_source_candidate_overlay.png"
        _source_candidate_overlay(_letterbox(Path(entry["frames"][int(args.wing_elevation_frame)]), args.resolution), new_images[int(args.wing_elevation_frame)], source_geometry, correction, camera, args.resolution, overlay_path)
    swap_start, swap_end = int(args.swap_start), int(args.swap_end)
    if not (0 <= swap_start <= swap_end < len(worlds)):
        raise ValueError(f"swap range {swap_start}..{swap_end} is outside clip")
    swapped_images = old_images.copy()
    swapped_images[swap_start : swap_end + 1] = new_images[swap_start : swap_end + 1]
    frames = []
    for frame in range(len(worlds)):
        sprite = _letterbox(Path(entry["frames"][frame]), args.resolution)
        row = Image.new("RGB", (args.resolution * 4, args.resolution + 30), (10, 10, 14))
        draw = ImageDraw.Draw(row); draw.text((4, 5), f"g13_attack_down f{frame:02d}", fill="white")
        for col, label, image in ((0, "source", sprite), (1, "move-bind control", old_images[frame]), (2, "attack-bind candidate", new_images[frame]), (3, f"phase swap f{swap_start}-{swap_end}", swapped_images[frame])):
            row.paste(Image.fromarray(np.uint8(np.clip(image, 0, 1) * 255)), (col * args.resolution, 30)); draw.text((col * args.resolution + 4, 17), label, fill=(190, 190, 205))
        frames.append(row)
    gif = out / "attack_down_pose_swapped.gif"
    frames[0].save(gif, save_all=True, append_images=frames[1:], duration=85, loop=0)
    contact = Image.new("RGB", (frames[0].width, min(8, len(frames)) * frames[0].height))
    for i, frame in enumerate(frames[:8]): contact.paste(frame, (0, i * frame.height))
    contact_path = out / "attack_down_pose_swapped_contact.png"; contact.save(contact_path)
    report = {"proof": "generated-candidate visual preview; pose-conditioned Meshy surface swap; not delivery", "bind": str(bind), "mesh": str(mesh_path), "clip": key, "frameCount": len(frames), "candidateBindFrame": bind_frame, "swapRange": [swap_start, swap_end], "wingElevationFrame": args.wing_elevation_frame, "wingElevation": correction, "diagnostic": str(diagnostic_path) if diagnostic_path else None, "overlay": str(overlay_path) if overlay_path else None, "alignment": align, "weights": "nearest_capture_joint_inverse_square_k4", "gif": str(gif), "contact": str(contact_path)}
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
