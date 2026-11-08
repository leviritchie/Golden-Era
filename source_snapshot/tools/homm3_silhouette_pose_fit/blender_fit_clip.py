#!/usr/bin/env python3
"""
Blender-side silhouette pose fitter.

Invoked by run_fit.py:
  blender -b --python blender_fit_clip.py -- --job path/to/job.json
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Vector


def _argv_after_double_dash() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _load_job(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_master(glb: Path):
    bpy.ops.import_scene.gltf(filepath=str(glb))
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if not arms:
        raise RuntimeError(f"no armature in {glb}")
    if not meshes:
        raise RuntimeError(f"no mesh in {glb}")
    return arms[0], meshes[0]


def _make_silhouette_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("SilhouetteWhite")
    mat.use_nodes = True
    mat.diffuse_color = (1.0, 1.0, 1.0, 1.0)
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emis = nodes.new("ShaderNodeEmission")
    emis.inputs["Color"].default_value = (1, 1, 1, 1)
    emis.inputs["Strength"].default_value = 8.0
    links.new(emis.outputs["Emission"], out.inputs["Surface"])
    return mat


def _apply_material_override(mesh_obj: bpy.types.Object, mat: bpy.types.Material) -> None:
    mesh_obj.data.materials.clear()
    mesh_obj.data.materials.append(mat)
    mesh_obj.color = (1.0, 1.0, 1.0, 1.0)
    for slot in mesh_obj.material_slots:
        slot.material = mat


def _setup_world_black() -> None:
    world = bpy.data.worlds.new("BlackWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0, 0, 0, 1)
    bg.inputs["Strength"].default_value = 1.0


def _setup_camera(job: dict, arm: bpy.types.Object) -> bpy.types.Object:
    cam_data = bpy.data.cameras.new("PoseFitCam")
    cam_data.type = "ORTHO"
    cam = bpy.data.objects.new("PoseFitCam", cam_data)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    cfg = job.get("camera", {})
    # Default: character faces roughly -Y after glTF→Blender; camera on +X sees right-facing profile.
    distance = float(cfg.get("distance", 3.0))
    height = float(cfg.get("height", 0.85))
    ortho_scale = float(cfg.get("orthoScale", 2.2))
    axis = str(cfg.get("axis", "+X")).upper()

    if axis == "+X":
        cam.location = Vector((distance, 0.0, height))
        cam.rotation_euler = Euler((math.pi / 2.0, 0.0, math.pi / 2.0), "XYZ")
    elif axis == "-X":
        cam.location = Vector((-distance, 0.0, height))
        cam.rotation_euler = Euler((math.pi / 2.0, 0.0, -math.pi / 2.0), "XYZ")
    elif axis == "+Y":
        cam.location = Vector((0.0, distance, height))
        cam.rotation_euler = Euler((math.pi / 2.0, 0.0, math.pi), "XYZ")
    elif axis == "-Y":
        cam.location = Vector((0.0, -distance, height))
        cam.rotation_euler = Euler((math.pi / 2.0, 0.0, 0.0), "XYZ")
    else:
        raise RuntimeError(f"unsupported camera.axis={axis}")

    cam_data.ortho_scale = ortho_scale

    # Optional root yaw so facing matches sprites without baking into bone DOF.
    root_yaw_deg = float(cfg.get("rootYawDeg", 0.0))
    if abs(root_yaw_deg) > 1e-6:
        arm.rotation_mode = "XYZ"
        arm.rotation_euler[2] = math.radians(root_yaw_deg)

    return cam


def _setup_render(job: dict, out_path: Path) -> None:
    scene = bpy.context.scene
    res = job.get("render", {})
    # EEVEE + transparent film: silhouette from alpha (Workbench ignored Emission nodes).
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 1
    scene.eevee.use_gtao = False
    scene.eevee.use_bloom = False
    scene.eevee.use_ssr = False
    scene.render.resolution_x = int(res.get("width", 288))
    scene.render.resolution_y = int(res.get("height", 256))
    scene.render.resolution_percentage = 100
    scene.render.filepath = str(out_path)
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    scene.render.use_single_layer = True
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "None"


def _bone_names(job: dict) -> list[str]:
    names = [str(b) for b in job.get("optimizeBones") or []]
    if not names:
        raise RuntimeError("optimizeBones must be a non-empty list")
    return names


def _collect_rest_eulers(arm: bpy.types.Object, names: list[str]) -> dict[str, Euler]:
    out: dict[str, Euler] = {}
    for name in names:
        pb = arm.pose.bones.get(name)
        if pb is None:
            raise RuntimeError(f"missing pose bone {name}")
        pb.rotation_mode = "XYZ"
        out[name] = pb.rotation_euler.copy()
    return out


def _apply_deltas(arm: bpy.types.Object, rest: dict[str, Euler], names: list[str], vec: np.ndarray) -> None:
    # vec layout: [bone0.x, bone0.y, bone0.z, bone1.x, ...] in radians relative to rest
    for i, name in enumerate(names):
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        base = rest[name]
        o = i * 3
        pb.rotation_euler = Euler(
            (base.x + float(vec[o]), base.y + float(vec[o + 1]), base.z + float(vec[o + 2])),
            "XYZ",
        )


def _render_mask(tmp_png: Path, threshold: float = 0.15) -> np.ndarray:
    """
    Render current scene and read the PNG via Pillow.

    Disk round-trip is intentional: Blender's 'Render Result' pixel buffer is
    unreliable in background mode, and bpy.data.images.load leaked datablocks.
    """
    from PIL import Image

    scene = bpy.context.scene
    scene.render.filepath = str(tmp_png)
    bpy.ops.render.render(write_still=True)
    with Image.open(tmp_png) as im:
        arr = np.asarray(im.convert("RGBA"), dtype=np.uint8)
    alpha = arr[..., 3].astype(np.float32) / 255.0
    rgb = arr[..., :3].astype(np.float32) / 255.0
    luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    return np.logical_or(alpha > threshold, luma > threshold).astype(np.float32)


def _normalize_like_target(mask: np.ndarray, out_hw: tuple[int, int], pad_frac: float = 0.08) -> np.ndarray:
    """Match prepare_targets.normalize_mask without importing host modules."""
    from PIL import Image

    ys, xs = np.where(mask > 0.5)
    out_h, out_w = out_hw
    canvas = np.zeros((out_h, out_w), dtype=np.float32)
    if ys.size == 0:
        return canvas
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    crop = mask[y0:y1, x0:x1]
    ch, cw = crop.shape
    pad = int(round(pad_frac * max(ch, cw)))
    padded = np.zeros((ch + 2 * pad, cw + 2 * pad), dtype=np.float32)
    padded[pad : pad + ch, pad : pad + cw] = crop
    ph, pw = padded.shape
    scale = min(out_h / ph, out_w / pw)
    new_h = max(1, int(round(ph * scale)))
    new_w = max(1, int(round(pw * scale)))
    resized = np.array(
        Image.fromarray((padded * 255.0).astype(np.uint8), mode="L").resize(
            (new_w, new_h), resample=Image.Resampling.NEAREST
        ),
        dtype=np.float32,
    ) / 255.0
    resized = (resized > 0.5).astype(np.float32)
    y_off = (out_h - new_h) // 2
    x_off = (out_w - new_w) // 2
    canvas[y_off : y_off + new_h, x_off : x_off + new_w] = resized
    return canvas


def _loss(pred: np.ndarray, target: np.ndarray) -> float:
    # Symmetric difference + mild soft L2 (stable for empty overlap).
    inter = float(np.minimum(pred, target).sum())
    union = float(np.maximum(pred, target).sum()) + 1e-6
    iou = inter / union
    l2 = float(np.mean((pred - target) ** 2))
    return (1.0 - iou) + 0.25 * l2


def _optimize_frame(
    *,
    arm: bpy.types.Object,
    rest: dict[str, Euler],
    names: list[str],
    target: np.ndarray,
    x0: np.ndarray,
    tmp_png: Path,
    job: dict,
    frame_index: int,
) -> tuple[np.ndarray, float, dict]:
    from scipy.optimize import differential_evolution, minimize

    opt = job.get("optimizer", {})
    method = str(opt.get("method", "hybrid")).lower()
    bound = float(opt.get("boundRad", math.radians(55)))
    maxiter = int(opt.get("maxiter", 12))
    polish_iters = int(opt.get("polishIters", 80))
    seed = int(opt.get("seed", 0)) + frame_index * 17
    out_hw = target.shape
    pad_frac = float(job.get("targetPadFrac", 0.08))
    n = len(names) * 3
    bounds = [(-bound, bound)] * n

    eval_count = {"n": 0, "best": float("inf")}

    def objective(vec: np.ndarray) -> float:
        _apply_deltas(arm, rest, names, vec)
        bpy.context.view_layer.update()
        raw = _render_mask(tmp_png)
        pred = _normalize_like_target(raw, out_hw, pad_frac=pad_frac)
        val = _loss(pred, target)
        eval_count["n"] += 1
        if val < eval_count["best"]:
            eval_count["best"] = val
        if eval_count["n"] % 25 == 0:
            print(
                f"[pose-fit] frame {frame_index} eval={eval_count['n']} "
                f"loss={val:.4f} best={eval_count['best']:.4f}",
                flush=True,
            )
        return val

    x = np.array(x0, dtype=np.float64, copy=True)
    best = float(objective(x))

    if method in {"none", "rest", "smoke"}:
        return x, best, {"evals": eval_count["n"], "bestDuring": eval_count["best"]}

    if method in {"de", "hybrid"}:
        de_maxiter = int(opt.get("deMaxiter", maxiter))
        abs_pop = int(opt.get("popsize", 24))
        rng = np.random.default_rng(seed)
        init_pop = rng.uniform(low=-bound, high=bound, size=(abs_pop, n))
        init_pop[0] = np.clip(x, -bound, bound)
        # popsize is ignored when init is an array; pass a dummy >=1 for API completeness.
        result = differential_evolution(
            objective,
            bounds=bounds,
            seed=seed,
            maxiter=de_maxiter,
            popsize=max(1, abs_pop),
            mutation=(0.4, 0.9),
            recombination=0.7,
            polish=False,
            updating="immediate",
            workers=1,
            init=init_pop,
        )
        x = np.array(result.x, dtype=np.float64)
        best = float(result.fun)

    if method in {"nelder", "hybrid", "lbfgs"}:
        # Local polish with warm start; clamp softly via large penalty outside bounds.
        def bounded(vec: np.ndarray) -> float:
            if np.any(np.abs(vec) > bound * 1.05):
                return 10.0 + float(np.sum(np.clip(np.abs(vec) - bound, 0, None)))
            return objective(vec)

        local = minimize(
            bounded,
            x,
            method="Nelder-Mead",
            options={
                "maxiter": polish_iters,
                "maxfev": max(40, polish_iters * 3),
                "xatol": 1e-3,
                "fatol": 1e-4,
                "adaptive": True,
            },
        )
        x = np.array(local.x, dtype=np.float64)
        best = float(local.fun)

    _apply_deltas(arm, rest, names, x)
    bpy.context.view_layer.update()
    return x, best, {"evals": eval_count["n"], "bestDuring": eval_count["best"]}


def _insert_keyframes(arm: bpy.types.Object, names: list[str], frame: int) -> None:
    arm.animation_data_create()
    for name in names:
        pb = arm.pose.bones[name]
        pb.keyframe_insert(data_path="rotation_euler", frame=frame)


def _clear_animation(arm: bpy.types.Object) -> None:
    """Pose edits must not fight an existing Action (view_layer.update would restore keyed values)."""
    if arm.animation_data is not None:
        arm.animation_data_clear()


def _bake_action_from_vectors(
    *,
    arm: bpy.types.Object,
    rest: dict[str, Euler],
    names: list[str],
    pose_vectors: list[np.ndarray],
    root_yaw_deg: float,
) -> None:
    _clear_animation(arm)
    arm.animation_data_create()
    action = bpy.data.actions.new(name="SilhouetteFit")
    arm.animation_data.action = action
    arm.rotation_mode = "XYZ"
    for i, vec in enumerate(pose_vectors):
        frame = i + 1
        bpy.context.scene.frame_set(frame)
        _apply_deltas(arm, rest, names, np.asarray(vec, dtype=np.float64))
        arm.rotation_euler[2] = math.radians(root_yaw_deg)
        for name in names:
            arm.pose.bones[name].keyframe_insert(data_path="rotation_euler", frame=frame)
        arm.keyframe_insert(data_path="rotation_euler", frame=frame)


def _save_mask_png(mask: np.ndarray, path: Path) -> None:
    from PIL import Image

    Image.fromarray((mask * 255.0).astype(np.uint8), mode="L").save(path)


def _write_comparison_strip(
    *,
    targets: list[np.ndarray],
    preds: list[np.ndarray],
    out_path: Path,
) -> None:
    from PIL import Image

    h, w = targets[0].shape
    n = len(targets)
    # rows: target, pred, xor
    sheet = Image.new("RGB", (w * n, h * 3), (0, 0, 0))
    for i, (t, p) in enumerate(zip(targets, preds)):
        t_img = Image.fromarray((t * 255.0).astype(np.uint8), mode="L").convert("RGB")
        p_img = Image.fromarray((p * 255.0).astype(np.uint8), mode="L").convert("RGB")
        xor = np.clip(t - p, 0, 1)  # target only = red-ish via channels
        miss = np.clip(p - t, 0, 1)
        overlay = np.zeros((h, w, 3), dtype=np.uint8)
        overlay[..., 0] = (xor * 255).astype(np.uint8)  # missing pred (in target) red
        overlay[..., 1] = (np.minimum(t, p) * 255).astype(np.uint8)  # overlap green
        overlay[..., 2] = (miss * 255).astype(np.uint8)  # extra pred blue
        o_img = Image.fromarray(overlay, mode="RGB")
        sheet.paste(t_img, (i * w, 0))
        sheet.paste(p_img, (i * w, h))
        sheet.paste(o_img, (i * w, 2 * h))
    sheet.save(out_path)


def run(job_path: Path) -> dict:
    job = _load_job(job_path)
    out_dir = Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    target_dir = out_dir / "targets"
    render_dir = out_dir / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)

    frames = job["frames"]
    targets = []
    for i in range(len(frames)):
        npy = target_dir / f"target_{i:02d}.npy"
        if not npy.is_file():
            raise RuntimeError(f"missing target {npy}; run prepare_targets first")
        targets.append(np.load(npy).astype(np.float32))

    _clear_scene()
    arm, mesh = _import_master(Path(job["masterGlb"]))
    _setup_world_black()
    _apply_material_override(mesh, _make_silhouette_material())
    _setup_camera(job, arm)

    names = _bone_names(job)
    rest = _collect_rest_eulers(arm, names)
    _clear_animation(arm)

    # Ensure pose bones use local XYZ euler.
    for name in names:
        arm.pose.bones[name].rotation_mode = "XYZ"

    tmp_png = render_dir / "_eval.png"
    _setup_render(job, tmp_png)

    x = np.zeros(len(names) * 3, dtype=np.float64)
    pose_vectors: list[np.ndarray] = []
    losses = []
    pred_masks = []
    frame_reports = []

    fps = float(job.get("fps", 12))
    bpy.context.scene.render.fps = int(round(fps))
    root_yaw_deg = float(job.get("camera", {}).get("rootYawDeg", 0.0))

    for i, target in enumerate(targets):
        print(f"[pose-fit] frame {i + 1}/{len(targets)}", flush=True)
        # Keep solver edits live-posed (no Action evaluation).
        _clear_animation(arm)
        bpy.context.scene.frame_set(1)
        x, best, stats = _optimize_frame(
            arm=arm,
            rest=rest,
            names=names,
            target=target,
            x0=x,
            tmp_png=tmp_png,
            job=job,
            frame_index=i,
        )
        _apply_deltas(arm, rest, names, x)
        bpy.context.view_layer.update()
        raw = _render_mask(tmp_png)
        pred = _normalize_like_target(raw, target.shape, pad_frac=float(job.get("targetPadFrac", 0.08)))
        pred_path = render_dir / f"pred_{i:02d}.png"
        _save_mask_png(pred, pred_path)
        raw_path = render_dir / f"raw_{i:02d}.png"
        _save_mask_png(raw, raw_path)

        pose_vectors.append(np.array(x, dtype=np.float64, copy=True))
        losses.append(best)
        pred_masks.append(pred)
        frame_reports.append(
            {
                "frameIndex": i,
                "loss": best,
                "evals": stats["evals"],
                "predMask": str(pred_path).replace("\\", "/"),
                "rawMask": str(raw_path).replace("\\", "/"),
            }
        )
        print(f"[pose-fit] frame {i} loss={best:.4f} evals={stats['evals']}", flush=True)

    strip_path = out_dir / "comparison_strip.png"
    _write_comparison_strip(targets=targets, preds=pred_masks, out_path=strip_path)

    _bake_action_from_vectors(
        arm=arm,
        rest=rest,
        names=names,
        pose_vectors=pose_vectors,
        root_yaw_deg=root_yaw_deg,
    )
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = len(pose_vectors)

    # Export animated GLB
    export_glb = out_dir / f"{job.get('clipId', 'clip')}_fitted.glb"
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=str(export_glb),
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_force_sampling=True,
        export_nla_strips=False,
        export_apply=False,
    )

    report = {
        "unitSid": job.get("unitSid"),
        "clipId": job.get("clipId"),
        "frameCount": len(targets),
        "losses": losses,
        "meanLoss": float(np.mean(losses)) if losses else None,
        "poseVectors": [v.tolist() for v in pose_vectors],
        "optimizeBones": names,
        "comparisonStrip": str(strip_path).replace("\\", "/"),
        "exportGlb": str(export_glb).replace("\\", "/"),
        "frames": frame_reports,
        "proof": "generated artifact validated — silhouette fit comparison strip; not runtime/OE proven",
    }
    report_path = out_dir / "fit_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report_path)}, indent=2), flush=True)
    return report


def main() -> int:
    args = _argv_after_double_dash()
    if len(args) < 2 or args[0] != "--job":
        print("usage: blender -b --python blender_fit_clip.py -- --job path.json", file=sys.stderr)
        return 2
    job_path = Path(args[1])
    try:
        run(job_path)
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
