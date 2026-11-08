#!/usr/bin/env python3
"""
Blender-side pseudo-rig multi-pose silhouette fitter.

Invoked by run_pseudo_rig_fit.py:
  blender -b --python blender_pseudo_rig_fit.py -- --job path/to/job.json
"""
from __future__ import annotations

import json
import math
import sys
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Matrix, Vector


TOOL_DIR = Path(__file__).resolve().parent
SILHOUETTE_DIR = TOOL_DIR.parent / "homm3_silhouette_pose_fit"
if str(SILHOUETTE_DIR) not in sys.path:
    sys.path.insert(0, str(SILHOUETTE_DIR))
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))


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
    meshes.sort(key=lambda o: len(o.data.vertices), reverse=True)
    return arms[0], meshes[0]


def _make_silhouette_material() -> bpy.types.Material:
    mat = bpy.data.materials.new("SilhouetteWhite")
    mat.use_nodes = True
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
    for slot in mesh_obj.material_slots:
        slot.material = mat


def _setup_world_black() -> None:
    world = bpy.data.worlds.new("BlackWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0, 0, 0, 1)
    bg.inputs["Strength"].default_value = 1.0


def _setup_render(job: dict, out_path: Path) -> None:
    scene = bpy.context.scene
    res = job.get("render", {})
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


def _camera_basis_arm_space(arm: bpy.types.Object, cam: bpy.types.Object) -> tuple[Vector, Vector, Vector]:
    """Sprite-plane right/up and depth (camera look) in armature local space."""
    mw = cam.matrix_world
    right_w = (mw.to_quaternion() @ Vector((1.0, 0.0, 0.0))).normalized()
    up_w = (mw.to_quaternion() @ Vector((0.0, 1.0, 0.0))).normalized()
    # Camera looks down local -Z.
    forward_w = (mw.to_quaternion() @ Vector((0.0, 0.0, -1.0))).normalized()
    arm_inv = arm.matrix_world.inverted().to_3x3()
    return (
        (arm_inv @ right_w).normalized(),
        (arm_inv @ up_w).normalized(),
        (arm_inv @ forward_w).normalized(),
    )


def _dof_dim(n_handles: int) -> int:
    return n_handles * 6


def _bounds_for_job(job: dict, n_handles: int) -> list[tuple[float, float]]:
    dof = job.get("dof") or {}
    plane_b = float(dof.get("planeTranslateBound", 0.35))
    depth_b = float(dof.get("depthTranslateBound", 0.06))
    rot_b = float(dof.get("rotateBoundRad", 0.61))
    bounds: list[tuple[float, float]] = []
    for _ in range(n_handles):
        bounds.extend(
            [
                (-plane_b, plane_b),
                (-plane_b, plane_b),
                (-depth_b, depth_b),
                (-rot_b, rot_b),
                (-rot_b, rot_b),
                (-rot_b, rot_b),
            ]
        )
    return bounds


def _apply_pose_vector(
    arm: bpy.types.Object,
    names: list[str],
    vec: np.ndarray,
    basis: tuple[Vector, Vector, Vector],
) -> None:
    right, up, forward = basis
    for i, name in enumerate(names):
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        o = i * 6
        u, v, d = float(vec[o]), float(vec[o + 1]), float(vec[o + 2])
        rx, ry, rz = float(vec[o + 3]), float(vec[o + 4]), float(vec[o + 5])
        loc = right * u + up * v + forward * d
        pb.location = loc
        pb.rotation_euler = Euler((rx, ry, rz), "XYZ")


def _clear_pose(arm: bpy.types.Object, names: list[str]) -> None:
    for name in names:
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        pb.location = Vector((0.0, 0.0, 0.0))
        pb.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")


def _clear_animation(arm: bpy.types.Object) -> None:
    if arm.animation_data is not None:
        arm.animation_data_clear()


def _render_mask(tmp_png: Path, threshold: float = 0.15) -> np.ndarray:
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


def _alpha_loss(pred: np.ndarray, target: np.ndarray) -> tuple[float, float]:
    inter = float(np.minimum(pred, target).sum())
    union = float(np.maximum(pred, target).sum()) + 1e-6
    iou = inter / union
    l2 = float(np.mean((pred - target) ** 2))
    return (1.0 - iou) + 0.25 * l2, iou


def _sobel_edges(mask: np.ndarray) -> np.ndarray:
    m = mask.astype(np.float32)
    try:
        from scipy.ndimage import sobel

        gx = sobel(m, axis=1)
        gy = sobel(m, axis=0)
    except Exception:
        kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float32)
        ky = np.array([[-1, -2, -1], [0, 0, 0], [1, 2, 1]], dtype=np.float32)

        def conv2(img: np.ndarray, k: np.ndarray) -> np.ndarray:
            from numpy.lib.stride_tricks import sliding_window_view

            p = np.pad(img, 1, mode="edge")
            win = sliding_window_view(p, (3, 3))
            return (win * k).sum(axis=(-2, -1))

        gx = conv2(m, kx)
        gy = conv2(m, ky)
    mag = np.sqrt(gx * gx + gy * gy)
    mx = float(mag.max())
    if mx > 1e-8:
        mag = mag / mx
    return mag.astype(np.float32)


def _edge_loss(pred: np.ndarray, target_edge: np.ndarray) -> float:
    pe = _sobel_edges(pred)
    return float(np.mean(np.abs(pe - target_edge)))


def _dt_loss(pred: np.ndarray, target: np.ndarray) -> float:
    """Symmetric distance-transform mismatch — pulls limb tips into place."""
    from scipy.ndimage import distance_transform_edt

    p = (pred > 0.5).astype(np.uint8)
    t = (target > 0.5).astype(np.uint8)
    if p.sum() == 0 or t.sum() == 0:
        return 1.0
    # Distance outside each silhouette.
    dt_t = distance_transform_edt(1 - t)
    dt_p = distance_transform_edt(1 - p)
    # Pred mass sitting far from target + target mass far from pred.
    a = float((dt_t * p).sum() / (p.sum() + 1e-6))
    b = float((dt_p * t).sum() / (t.sum() + 1e-6))
    # Normalize by diagonal so magnitude is ~O(1).
    diag = float(np.hypot(*pred.shape))
    return (a + b) / max(1.0, diag)


def _mask_com(mask: np.ndarray) -> tuple[float, float]:
    ys, xs = np.where(mask > 0.5)
    if ys.size == 0:
        h, w = mask.shape
        return 0.5 * (h - 1), 0.5 * (w - 1)
    return float(ys.mean()), float(xs.mean())


def _mask_bbox_hw(mask: np.ndarray) -> tuple[float, float]:
    ys, xs = np.where(mask > 0.5)
    if ys.size == 0:
        return 1.0, 1.0
    return float(ys.max() - ys.min() + 1), float(xs.max() - xs.min() + 1)


def _build_frame_pred_registration(
    raw: np.ndarray,
    target: np.ndarray,
) -> dict[str, float]:
    """Scale+align current raw pred CoM/height to this frame's target (v1)."""
    ry, rx = _mask_com(raw)
    ty, tx = _mask_com(target)
    rh, rw = _mask_bbox_hw(raw)
    th, tw = _mask_bbox_hw(target)
    scale = float(min(th / max(1.0, rh), tw / max(1.0, rw)))
    # Prefer height match for upright sprites; clamp extreme scales.
    scale_h = float(th / max(1.0, rh))
    scale = float(np.clip(0.65 * scale + 0.35 * scale_h, 0.35, 2.5))
    return {
        "scale": scale,
        "rest_cy": ry,
        "rest_cx": rx,
        "tgt_cy": ty,
        "tgt_cx": tx,
    }


def _apply_pred_registration(
    raw: np.ndarray,
    reg: dict[str, float],
    out_hw: tuple[int, int],
) -> np.ndarray:
    """Similarity warp via crop→resize→paste (not sparse point scatter)."""
    from PIL import Image

    out_h, out_w = out_hw
    scale = float(reg["scale"])
    canvas = np.zeros((out_h, out_w), dtype=np.float32)
    if scale <= 1e-8:
        return canvas
    ys, xs = np.where(raw > 0.5)
    if ys.size == 0:
        return canvas
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    crop = raw[y0:y1, x0:x1]
    ch, cw = crop.shape
    new_h = max(1, int(round(ch * scale)))
    new_w = max(1, int(round(cw * scale)))
    resized = np.array(
        Image.fromarray((crop * 255.0).astype(np.uint8), mode="L").resize(
            (new_w, new_h), resample=Image.Resampling.BILINEAR
        ),
        dtype=np.float32,
    ) / 255.0
    resized = (resized > 0.35).astype(np.float32)
    # Map crop center (≈ rest CoM if bbox-centered) onto target CoM.
    # Use explicit rest CoM relative to crop origin.
    cy_crop = reg["rest_cy"] - y0
    cx_crop = reg["rest_cx"] - x0
    # After scale, rest CoM lands at (cy_crop*scale, cx_crop*scale) in resized.
    y_off = int(round(reg["tgt_cy"] - cy_crop * scale))
    x_off = int(round(reg["tgt_cx"] - cx_crop * scale))
    # Paste with clipping.
    y_dst0 = max(0, y_off)
    x_dst0 = max(0, x_off)
    y_dst1 = min(out_h, y_off + new_h)
    x_dst1 = min(out_w, x_off + new_w)
    y_src0 = y_dst0 - y_off
    x_src0 = x_dst0 - x_off
    y_src1 = y_src0 + (y_dst1 - y_dst0)
    x_src1 = x_src0 + (x_dst1 - x_dst0)
    if y_dst1 > y_dst0 and x_dst1 > x_dst0:
        canvas[y_dst0:y_dst1, x_dst0:x_dst1] = np.maximum(
            canvas[y_dst0:y_dst1, x_dst0:x_dst1],
            resized[y_src0:y_src1, x_src0:x_src1],
        )
    return canvas


def _place_pred(
    raw: np.ndarray,
    *,
    out_hw: tuple[int, int],
    pad_frac: float,
    reg: dict[str, float] | None,
    target: np.ndarray | None = None,
    placement: str = "normalize",
) -> np.ndarray:
    mode = str(placement or "normalize").lower()
    if mode in {"match_target", "match_target_frame", "v1"} and target is not None:
        # Recompute each eval so posed limbs aren't locked to rest footprint.
        frame_reg = _build_frame_pred_registration(raw, target)
        return _apply_pred_registration(raw, frame_reg, out_hw)
    if reg is not None and mode in {"clip_rest", "rest_anchor"}:
        return _apply_pred_registration(raw, reg, out_hw)
    return _normalize_like_target(raw, out_hw, pad_frac=pad_frac)


def _handle_rest_positions(catalog: dict | None, names: list[str]) -> np.ndarray:
    if not catalog:
        return np.zeros((len(names), 3), dtype=np.float64)
    by_name = {h["name"]: h["restPosition"] for h in catalog.get("handles") or []}
    out = np.zeros((len(names), 3), dtype=np.float64)
    for i, name in enumerate(names):
        if name not in by_name:
            raise RuntimeError(f"handle {name} missing from catalog")
        out[i] = np.asarray(by_name[name], dtype=np.float64)
    return out


def _build_handle_knn(rest: np.ndarray, k: int) -> list[list[int]]:
    n = rest.shape[0]
    k_use = max(1, min(int(k), max(1, n - 1)))
    neighbors: list[list[int]] = []
    for i in range(n):
        d = np.linalg.norm(rest - rest[i][None, :], axis=1)
        d[i] = np.inf
        idx = np.argsort(d)[:k_use]
        neighbors.append([int(j) for j in idx])
    return neighbors


def _deform_loss(vec: np.ndarray, n_handles: int) -> float:
    # Soft pull of translations toward bind (first 3 of each 6).
    acc = 0.0
    for i in range(n_handles):
        o = i * 6
        acc += float(vec[o] ** 2 + vec[o + 1] ** 2 + vec[o + 2] ** 2)
        acc += 0.25 * float(vec[o + 3] ** 2 + vec[o + 4] ** 2 + vec[o + 5] ** 2)
    return acc / max(1, n_handles)


def _stretch_loss(
    vec: np.ndarray,
    rest: np.ndarray,
    neighbors: list[list[int]],
    basis: tuple[Vector, Vector, Vector],
) -> float:
    right, up, forward = basis
    n = rest.shape[0]
    posed = np.zeros_like(rest)
    for i in range(n):
        o = i * 6
        delta = (
            np.array([right.x, right.y, right.z]) * float(vec[o])
            + np.array([up.x, up.y, up.z]) * float(vec[o + 1])
            + np.array([forward.x, forward.y, forward.z]) * float(vec[o + 2])
        )
        posed[i] = rest[i] + delta
    acc = 0.0
    count = 0
    for i, nbrs in enumerate(neighbors):
        for j in nbrs:
            rest_len = float(np.linalg.norm(rest[i] - rest[j])) + 1e-6
            posed_len = float(np.linalg.norm(posed[i] - posed[j]))
            ratio = posed_len / rest_len
            # Penalize stretch/compress away from 1.
            acc += (ratio - 1.0) ** 2
            count += 1
    return acc / max(1, count)


def _neighbor_loss(vec: np.ndarray, neighbor_vec: np.ndarray | None) -> float:
    if neighbor_vec is None:
        return 0.0
    return float(np.mean((vec - neighbor_vec) ** 2))


def _clip_groups(frames: list[dict]) -> dict[str, list[int]]:
    groups: dict[str, list[int]] = {}
    for i, fr in enumerate(frames):
        cid = str(fr.get("clipId") or fr.get("actionName") or "clip")
        groups.setdefault(cid, []).append(i)
    return groups


def _clip_cyclic(frames: list[dict], indices: list[int]) -> bool:
    return bool(frames[indices[0]].get("cyclic", False))


def _optimize_frame(
    *,
    arm: bpy.types.Object,
    names: list[str],
    basis: tuple[Vector, Vector, Vector],
    target: np.ndarray,
    target_edge: np.ndarray | None,
    x0: np.ndarray,
    tmp_png: Path,
    job: dict,
    frame_index: int,
    neighbor_vecs: list[np.ndarray | None],
    rest_pos: np.ndarray,
    handle_knn: list[list[int]],
    pred_reg: dict[str, float] | None = None,
    polish_iters: int | None = None,
) -> tuple[np.ndarray, float, float, dict]:
    from scipy.optimize import differential_evolution, minimize

    opt = job.get("optimizer") or {}
    loss_cfg = job.get("loss") or {}
    method = str(opt.get("method", "nelder")).lower()
    # Stage A explores freely; Stage B (with neighbors) keeps deform/stretch.
    if not neighbor_vecs:
        lam_d = float(loss_cfg.get("lambdaDeformStageA", 0.01))
        lam_s = float(loss_cfg.get("lambdaStretchStageA", 0.01))
        lam_t = 0.0
    else:
        lam_t = float(loss_cfg.get("lambdaNeighbor", 0.15))
        lam_d = float(loss_cfg.get("lambdaDeform", 0.08))
        lam_s = float(loss_cfg.get("lambdaStretch", 0.05))
    lam_e = float(loss_cfg.get("lambdaEdge", 0.0))
    lam_dt = float(loss_cfg.get("lambdaDt", 0.0))
    pad_frac = float(job.get("targetPadFrac", 0.08))
    out_hw = target.shape
    bounds = _bounds_for_job(job, len(names))
    n = len(bounds)
    seed = int(opt.get("seed", 0)) + frame_index * 17
    polish = int(polish_iters if polish_iters is not None else opt.get("polishIters", 120))
    # Block-coordinate NM: 288-D full Nelder is intractable; optimize handle blocks.
    block_handles = int(opt.get("blockSize", 8))
    block_handles = max(1, min(block_handles, len(names)))

    eval_count = {"n": 0, "best": float("inf"), "best_iou": 0.0}

    def objective(vec: np.ndarray) -> float:
        _apply_pose_vector(arm, names, vec, basis)
        bpy.context.view_layer.update()
        raw = _render_mask(tmp_png)
        pred = _place_pred(
            raw,
            out_hw=out_hw,
            pad_frac=pad_frac,
            reg=pred_reg,
            target=target,
            placement=str((job.get("predPlacement") or "normalize")),
        )
        alpha, iou = _alpha_loss(pred, target)
        edge = 0.0
        if lam_e > 0.0 and target_edge is not None:
            edge = _edge_loss(pred, target_edge)
        dt = 0.0
        if lam_dt > 0.0:
            dt = _dt_loss(pred, target)
        neigh = 0.0
        for nv in neighbor_vecs:
            neigh += _neighbor_loss(vec, nv)
        neigh /= max(1, len(neighbor_vecs))
        deform = _deform_loss(vec, len(names))
        stretch = _stretch_loss(vec, rest_pos, handle_knn, basis)
        val = (
            alpha
            + lam_e * edge
            + lam_dt * dt
            + lam_t * neigh
            + lam_d * deform
            + lam_s * stretch
        )
        eval_count["n"] += 1
        if val < eval_count["best"]:
            eval_count["best"] = val
            eval_count["best_iou"] = iou
        if eval_count["n"] % 25 == 0:
            print(
                f"[pseudo-fit] frame {frame_index} eval={eval_count['n']} "
                f"loss={val:.4f} best={eval_count['best']:.4f} iou={iou:.4f} "
                f"edge={edge:.4f} dt={dt:.4f}",
                flush=True,
            )
        return val

    x = np.array(x0, dtype=np.float64, copy=True)
    best = float(objective(x))
    best_iou = float(eval_count["best_iou"])
    lo = np.array([b[0] for b in bounds], dtype=np.float64)
    hi = np.array([b[1] for b in bounds], dtype=np.float64)

    if method in {"none", "rest", "smoke"}:
        return x, best, best_iou, {"evals": eval_count["n"], "method": method}

    if method in {"de", "hybrid"}:
        de_maxiter = int(opt.get("deMaxiter", 2))
        abs_pop = int(opt.get("popsize", 4))
        rng = np.random.default_rng(seed)
        init_pop = rng.uniform(low=lo, high=hi, size=(abs_pop, n))
        init_pop[0] = np.clip(x, lo, hi)
        result = differential_evolution(
            objective,
            bounds,
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
        n_blocks = int(math.ceil(len(names) / float(block_handles)))
        # Spread polish budget across blocks.
        per_block = max(20, int(math.ceil(polish / max(1, n_blocks))))
        n_random = int(opt.get("randomProbesPerBlock", 24))
        simplex_frac = float(opt.get("simplexBoundFrac", 0.35))
        rng = np.random.default_rng(seed)

        for b in range(n_blocks):
            h0 = b * block_handles
            h1 = min(len(names), h0 + block_handles)
            idx = []
            for hi_i in range(h0, h1):
                base = hi_i * 6
                idx.extend(range(base, base + 6))
            idx_arr = np.asarray(idx, dtype=np.int64)
            lo_b = lo[idx_arr]
            hi_b = hi[idx_arr]
            span = np.maximum(hi_b - lo_b, 1e-6)

            def block_obj(block_vec: np.ndarray, base: np.ndarray = x, indices: np.ndarray = idx_arr) -> float:
                trial = base.copy()
                trial[indices] = block_vec
                if np.any(block_vec < lo_b - 1e-6) or np.any(block_vec > hi_b + 1e-6):
                    return 10.0 + float(
                        np.sum(np.clip(lo_b - block_vec, 0, None) + np.clip(block_vec - hi_b, 0, None))
                    )
                return objective(trial)

            # Random probes — critical when x0 is near zero (scipy NM zdelt=2.5e-4 is invisible).
            best_block = x[idx_arr].copy()
            best_val = block_obj(best_block)
            for _ in range(max(0, n_random)):
                cand = best_block.copy()
                # Prefer translation probes; lighter rotation noise.
                for hi_i in range(h0, h1):
                    local = (hi_i - h0) * 6
                    cand[local : local + 3] = rng.uniform(lo_b[local : local + 3], hi_b[local : local + 3])
                    cand[local + 3 : local + 6] = rng.normal(0.0, 0.15, size=3)
                cand = np.clip(cand, lo_b, hi_b)
                val = block_obj(cand)
                if val < best_val:
                    best_val = val
                    best_block = cand

            # Bound-scaled Nelder-Mead simplex (not scipy's tiny zero-component step).
            dim = int(idx_arr.size)
            simplex = np.zeros((dim + 1, dim), dtype=np.float64)
            simplex[0] = best_block
            for i in range(dim):
                row = best_block.copy()
                step = simplex_frac * span[i]
                # Alternate direction so the simplex isn't one-sided.
                if (i + frame_index + b) % 2 == 0:
                    row[i] = np.clip(row[i] + step, lo_b[i], hi_b[i])
                else:
                    row[i] = np.clip(row[i] - step, lo_b[i], hi_b[i])
                if abs(row[i] - best_block[i]) < 1e-8:
                    row[i] = np.clip(best_block[i] + (0.05 * span[i]), lo_b[i], hi_b[i])
                simplex[i + 1] = row

            local = minimize(
                block_obj,
                best_block,
                method="Nelder-Mead",
                options={
                    "maxiter": per_block,
                    "maxfev": max(40, per_block * 4),
                    "xatol": 1e-3,
                    "fatol": 1e-4,
                    "adaptive": True,
                    "initial_simplex": simplex,
                },
            )
            x[idx_arr] = np.clip(np.array(local.x, dtype=np.float64), lo_b, hi_b)
        best = float(objective(x))

    _apply_pose_vector(arm, names, x, basis)
    bpy.context.view_layer.update()
    raw = _render_mask(tmp_png)
    pred = _place_pred(
        raw,
        out_hw=out_hw,
        pad_frac=pad_frac,
        reg=pred_reg,
        target=target,
        placement=str((job.get("predPlacement") or "normalize")),
    )
    _, iou = _alpha_loss(pred, target)
    return (
        x,
        best,
        float(iou),
        {
            "evals": eval_count["n"],
            "method": method,
            "blockSize": block_handles,
            "bestDuring": eval_count["best"],
        },
    )


def _write_comparison_strip(
    *,
    targets: list[np.ndarray],
    preds: list[np.ndarray],
    out_path: Path,
    labels: list[str] | None = None,
) -> None:
    from PIL import Image, ImageDraw

    h, w = targets[0].shape
    n = len(targets)
    sheet = Image.new("RGB", (w * n, h * 3 + (18 if labels else 0)), (0, 0, 0))
    y0 = 18 if labels else 0
    draw = ImageDraw.Draw(sheet) if labels else None
    for i, (t, p) in enumerate(zip(targets, preds)):
        t_img = Image.fromarray((t * 255.0).astype(np.uint8), mode="L").convert("RGB")
        p_img = Image.fromarray((p * 255.0).astype(np.uint8), mode="L").convert("RGB")
        xor = np.clip(t - p, 0, 1)
        miss = np.clip(p - t, 0, 1)
        overlay = np.zeros((h, w, 3), dtype=np.uint8)
        overlay[..., 0] = (xor * 255).astype(np.uint8)
        overlay[..., 1] = (np.minimum(t, p) * 255).astype(np.uint8)
        overlay[..., 2] = (miss * 255).astype(np.uint8)
        o_img = Image.fromarray(overlay, mode="RGB")
        sheet.paste(t_img, (i * w, y0))
        sheet.paste(p_img, (i * w, y0 + h))
        sheet.paste(o_img, (i * w, y0 + 2 * h))
        if draw and labels:
            draw.text((i * w + 2, 2), labels[i][:18], fill=(220, 220, 220))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out_path)


def _write_clip_gifs(
    *,
    frames_meta: list[dict],
    targets: list[np.ndarray],
    preds: list[np.ndarray],
    out_dir: Path,
    frame_ms: int = 180,
) -> list[str]:
    from PIL import Image

    out_dir.mkdir(parents=True, exist_ok=True)
    groups = _clip_groups(frames_meta)
    written = []
    for clip_id, indices in groups.items():
        imgs = []
        for i in indices:
            h, w = targets[i].shape
            canvas = Image.new("RGB", (w * 2, h), (0, 0, 0))
            t_img = Image.fromarray((targets[i] * 255.0).astype(np.uint8), mode="L").convert("RGB")
            p_img = Image.fromarray((preds[i] * 255.0).astype(np.uint8), mode="L").convert("RGB")
            canvas.paste(t_img, (0, 0))
            canvas.paste(p_img, (w, 0))
            imgs.append(canvas)
        path = out_dir / f"{clip_id}_silhouette.gif"
        imgs[0].save(
            path,
            save_all=True,
            append_images=imgs[1:],
            duration=frame_ms,
            loop=0,
        )
        written.append(str(path))
    return written


def _bake_and_export(
    *,
    arm: bpy.types.Object,
    mesh: bpy.types.Object,
    names: list[str],
    basis: tuple[Vector, Vector, Vector],
    pose_vectors: list[np.ndarray],
    frames_meta: list[dict],
    export_dir: Path,
    job: dict,
) -> dict:
    export_dir.mkdir(parents=True, exist_ok=True)
    _clear_animation(arm)
    arm.animation_data_create()

    groups = _clip_groups(frames_meta)
    clip_map = {"schema": "homm3_pseudo_rig_clip_map.v1", "clips": []}
    fps = float(job.get("fps", 12))
    bpy.context.scene.render.fps = int(round(fps))

    # One Action per clip on its own NLA track (glTF multi-anim export).
    for clip_id, indices in groups.items():
        action_name = str(frames_meta[indices[0]].get("actionName") or clip_id)
        action = bpy.data.actions.new(name=action_name)
        arm.animation_data.action = action
        for local_i, global_i in enumerate(indices):
            frame = local_i + 1
            bpy.context.scene.frame_set(frame)
            _apply_pose_vector(arm, names, pose_vectors[global_i], basis)
            for name in names:
                pb = arm.pose.bones[name]
                pb.keyframe_insert(data_path="location", frame=frame)
                pb.keyframe_insert(data_path="rotation_euler", frame=frame)
        track = arm.animation_data.nla_tracks.new()
        track.name = action_name
        start = 1
        track.strips.new(action_name, start, action)
        arm.animation_data.action = None
        clip_map["clips"].append(
            {
                "clipId": clip_id,
                "actionName": action_name,
                "frameCount": len(indices),
                "cyclic": _clip_cyclic(frames_meta, indices),
                "globalFrameIndices": indices,
            }
        )

    out_glb = export_dir / "crusader_pseudo_rig.glb"
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=str(out_glb),
        export_format="GLB",
        export_skins=True,
        export_animations=True,
        export_nla_strips=True,
        export_force_sampling=True,
        export_apply=False,
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
    )
    clip_map_path = export_dir / "clip_map.json"
    clip_map["outputGlb"] = str(out_glb)
    clip_map["proof"] = (
        "generated-artifact validated — pseudo-rig bake; not OE runtime"
    )
    clip_map_path.write_text(json.dumps(clip_map, indent=2), encoding="utf-8")
    return {"glb": str(out_glb), "clipMap": str(clip_map_path), "clips": clip_map["clips"]}


def _predict_mask(
    arm: bpy.types.Object,
    names: list[str],
    vec: np.ndarray,
    basis: tuple[Vector, Vector, Vector],
    tmp_png: Path,
    out_hw: tuple[int, int],
    pad_frac: float,
    *,
    target: np.ndarray | None = None,
    placement: str = "normalize",
    pred_reg: dict[str, float] | None = None,
) -> np.ndarray:
    _apply_pose_vector(arm, names, vec, basis)
    bpy.context.view_layer.update()
    raw = _render_mask(tmp_png)
    return _place_pred(
        raw,
        out_hw=out_hw,
        pad_frac=pad_frac,
        reg=pred_reg,
        target=target,
        placement=placement,
    )


def run(job_path: Path) -> dict:
    from homm3_pose_camera import setup_pose_camera

    job = _load_job(job_path)
    out_dir = Path(job["outputDir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    export_dir = Path(job.get("exportDir") or (out_dir.parent / "export"))
    target_dir = out_dir / "targets"
    render_dir = out_dir / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)
    poses_dir = out_dir / "poses"
    poses_dir.mkdir(parents=True, exist_ok=True)

    frames_meta = list(job["frames"])
    targets = []
    target_edges: list[np.ndarray | None] = []
    for i in range(len(frames_meta)):
        npy = target_dir / f"target_{i:02d}.npy"
        if not npy.is_file():
            npy = target_dir / f"target_{i:03d}.npy"
        if not npy.is_file():
            raise RuntimeError(f"missing target {npy}; run prepare_targets first")
        targets.append(np.load(npy).astype(np.float32))
        edge_npy = target_dir / f"edge_{i:02d}.npy"
        if not edge_npy.is_file():
            edge_npy = target_dir / f"edge_{i:03d}.npy"
        if edge_npy.is_file():
            target_edges.append(np.load(edge_npy).astype(np.float32))
        else:
            target_edges.append(_sobel_edges(targets[-1]))

    use_v1 = str(job.get("targetVersion", "v0")).lower() in {"v1", "edge", "clip_shared"}
    placement = str(job.get("predPlacement") or ("match_target" if use_v1 else "normalize"))
    if use_v1:
        print(
            f"[pseudo-fit] targetVersion=v1 placement={placement} (edge/dt loss)",
            flush=True,
        )

    catalog = None
    cat_path = job.get("handleCatalog")
    if cat_path:
        catalog = json.loads(Path(cat_path).read_text(encoding="utf-8"))

    _clear_scene()
    arm, mesh = _import_master(Path(job["masterGlb"]))
    _setup_world_black()
    _apply_material_override(mesh, _make_silhouette_material())
    cam = setup_pose_camera(job, arm, bpy_module=bpy)

    names = _bone_names(job)
    for name in names:
        if name not in arm.pose.bones:
            raise RuntimeError(f"missing pose bone {name}")
        arm.pose.bones[name].rotation_mode = "XYZ"
    _clear_animation(arm)
    _clear_pose(arm, names)

    basis = _camera_basis_arm_space(arm, cam)
    rest_pos = _handle_rest_positions(catalog, names)
    knn_k = int((job.get("loss") or {}).get("handleNeighborK", 4))
    handle_knn = _build_handle_knn(rest_pos, knn_k)

    tmp_png = render_dir / "_eval.png"
    _setup_render(job, tmp_png)
    pad_frac = float(job.get("targetPadFrac", 0.08))
    out_hw = targets[0].shape

    groups = _clip_groups(frames_meta)
    rest_vec = np.zeros(_dof_dim(len(names)), dtype=np.float64)

    # Rest-pose baseline IoU (diagnose camera/scale before claiming progress).
    rest_ious = []
    for i, target in enumerate(targets):
        rest_pred = _predict_mask(
            arm,
            names,
            rest_vec,
            basis,
            tmp_png,
            out_hw,
            pad_frac,
            target=target,
            placement=placement,
        )
        _, ri = _alpha_loss(rest_pred, target)
        rest_ious.append(float(ri))
    rest_iou0 = rest_ious[0]
    rest_mean = float(np.mean(rest_ious))
    print(
        f"[pseudo-fit] rest-pose IoU frame0={rest_iou0:.4f} mean={rest_mean:.4f}",
        flush=True,
    )

    pose_vectors = [np.zeros(_dof_dim(len(names)), dtype=np.float64) for _ in targets]
    frame_reports = []

    opt = job.get("optimizer") or {}
    stage_a_method = str(opt.get("method", "nelder"))

    # ---- Stage A: per-clip sequential warm-start ----
    print("[pseudo-fit] Stage A: per-clip sequential", flush=True)
    for clip_id, indices in groups.items():
        x = np.zeros(_dof_dim(len(names)), dtype=np.float64)
        for local_i, fi in enumerate(indices):
            print(
                f"[pseudo-fit] StageA {clip_id} frame {local_i + 1}/{len(indices)} "
                f"(global {fi})",
                flush=True,
            )
            _clear_animation(arm)
            bpy.context.scene.frame_set(1)
            x, best, iou, stats = _optimize_frame(
                arm=arm,
                names=names,
                basis=basis,
                target=targets[fi],
                target_edge=target_edges[fi],
                x0=x,
                tmp_png=tmp_png,
                job={
                    **job,
                    "optimizer": {**opt, "method": stage_a_method},
                    "predPlacement": placement,
                },
                frame_index=fi,
                neighbor_vecs=[],
                rest_pos=rest_pos,
                handle_knn=handle_knn,
                pred_reg=None,
            )
            pose_vectors[fi] = x
            np.save(poses_dir / f"pose_{fi:03d}.npy", x)
            frame_reports.append(
                {
                    "frame": fi,
                    "clipId": clip_id,
                    "stage": "A",
                    "loss": best,
                    "iou": iou,
                    "evals": stats.get("evals"),
                }
            )
            print(
                f"[pseudo-fit] StageA done frame={fi} loss={best:.4f} iou={iou:.4f}",
                flush=True,
            )

    # Gate: Stage A must beat rest baseline on mean IoU (skipped for smoke wiring).
    stage_a_ious = [r["iou"] for r in frame_reports if r["stage"] == "A"]
    mean_a = float(np.mean(stage_a_ious)) if stage_a_ious else 0.0
    print(f"[pseudo-fit] Stage A mean IoU={mean_a:.4f} rest0={rest_iou0:.4f}", flush=True)
    smoke = stage_a_method in {"none", "rest", "smoke"}
    if (not smoke) and mean_a < rest_mean + 0.01:
        raise RuntimeError(
            f"Stage A mean IoU {mean_a:.4f} not above rest mean {rest_mean:.4f}+0.01; "
            "stop before Stage B (camera/scale/handle coverage)"
        )

    # ---- Stage B: multi-pose polish with neighbor + deform ----
    stage_b_passes = 0 if smoke else int(opt.get("stageBPasses", 2))
    stage_b_polish = int(opt.get("stageBPolishIters", 60))
    print(f"[pseudo-fit] Stage B: {stage_b_passes} multi-pose passes", flush=True)
    for pass_i in range(stage_b_passes):
        for clip_id, indices in groups.items():
            cyclic = _clip_cyclic(frames_meta, indices)
            for local_i, fi in enumerate(indices):
                prev_i = indices[local_i - 1] if local_i > 0 else (indices[-1] if cyclic else None)
                next_i = (
                    indices[local_i + 1]
                    if local_i + 1 < len(indices)
                    else (indices[0] if cyclic else None)
                )
                neighbors = []
                if prev_i is not None:
                    neighbors.append(pose_vectors[prev_i])
                if next_i is not None:
                    neighbors.append(pose_vectors[next_i])
                print(
                    f"[pseudo-fit] StageB pass {pass_i + 1}/{stage_b_passes} "
                    f"{clip_id} local {local_i + 1}/{len(indices)}",
                    flush=True,
                )
                _clear_animation(arm)
                x, best, iou, stats = _optimize_frame(
                    arm=arm,
                    names=names,
                    basis=basis,
                    target=targets[fi],
                    target_edge=target_edges[fi],
                    x0=pose_vectors[fi],
                    tmp_png=tmp_png,
                    job={**job, "optimizer": {**opt, "method": "nelder"}, "predPlacement": placement},
                    frame_index=fi,
                    neighbor_vecs=neighbors,
                    rest_pos=rest_pos,
                    handle_knn=handle_knn,
                    pred_reg=None,
                    polish_iters=stage_b_polish,
                )
                pose_vectors[fi] = x
                np.save(poses_dir / f"pose_{fi:03d}.npy", x)
                frame_reports.append(
                    {
                        "frame": fi,
                        "clipId": clip_id,
                        "stage": f"B{pass_i + 1}",
                        "loss": best,
                        "iou": iou,
                        "evals": stats.get("evals"),
                    }
                )

    # Final preds + metrics
    preds = []
    final_ious = []
    final_losses = []
    for i, target in enumerate(targets):
        pred = _predict_mask(
            arm,
            names,
            pose_vectors[i],
            basis,
            tmp_png,
            out_hw,
            pad_frac,
            target=target,
            placement=placement,
        )
        preds.append(pred)
        loss, iou = _alpha_loss(pred, target)
        final_ious.append(iou)
        final_losses.append(loss)
        from PIL import Image

        Image.fromarray((pred * 255.0).astype(np.uint8), mode="L").save(
            render_dir / f"pred_{i:03d}.png"
        )

    # Comparison strip: one representative frame per clip + full strip downsampled
    labels = []
    strip_targets = []
    strip_preds = []
    for clip_id, indices in groups.items():
        mid = indices[len(indices) // 2]
        labels.append(f"{clip_id}:{mid}")
        strip_targets.append(targets[mid])
        strip_preds.append(preds[mid])
    _write_comparison_strip(
        targets=strip_targets,
        preds=strip_preds,
        out_path=out_dir / "comparison_strip_per_clip.png",
        labels=labels,
    )
    # Full strip can be huge; write in chunks of 10.
    for start in range(0, len(targets), 10):
        end = min(len(targets), start + 10)
        _write_comparison_strip(
            targets=targets[start:end],
            preds=preds[start:end],
            out_path=out_dir / f"comparison_strip_{start:02d}_{end - 1:02d}.png",
            labels=[
                f"{frames_meta[i].get('clipId')}:{frames_meta[i].get('clipFrame')}"
                for i in range(start, end)
            ],
        )

    gif_paths = _write_clip_gifs(
        frames_meta=frames_meta,
        targets=targets,
        preds=preds,
        out_dir=out_dir / "gifs",
        frame_ms=180,
    )

    bake_info = _bake_and_export(
        arm=arm,
        mesh=mesh,
        names=names,
        basis=basis,
        pose_vectors=pose_vectors,
        frames_meta=frames_meta,
        export_dir=export_dir,
        job=job,
    )

    per_clip = {}
    for clip_id, indices in groups.items():
        per_clip[clip_id] = {
            "meanIoU": float(np.mean([final_ious[i] for i in indices])),
            "meanLoss": float(np.mean([final_losses[i] for i in indices])),
            "frameCount": len(indices),
        }

    report = {
        "ok": True,
        "schema": "homm3_pseudo_rig_fit_report.v1",
        "unitSid": job.get("unitSid"),
        "frameCount": len(targets),
        "handleCount": len(names),
        "restPoseIoUFrame0": rest_iou0,
        "restPoseMeanIoU": rest_mean,
        "stageAMeanIoU": mean_a,
        "targetVersion": "v1" if use_v1 else "v0",
        "finalMeanIoU": float(np.mean(final_ious)),
        "finalMeanLoss": float(np.mean(final_losses)),
        "perClip": per_clip,
        "frames": [
            {
                "frame": i,
                "clipId": frames_meta[i].get("clipId"),
                "clipFrame": frames_meta[i].get("clipFrame"),
                "iou": final_ious[i],
                "loss": final_losses[i],
            }
            for i in range(len(targets))
        ],
        "stageHistory": frame_reports,
        "gifs": gif_paths,
        "comparisonStrip": str(out_dir / "comparison_strip_per_clip.png"),
        "export": bake_info,
        "proof": "generated-artifact validated — pseudo-rig multi-pose silhouette fit; not OE runtime",
    }
    report_path = out_dir / "fit_report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(report_path), "meanIoU": report["finalMeanIoU"]}), flush=True)
    return report


def main() -> int:
    argv = _argv_after_double_dash()
    if not argv or argv[0] != "--job":
        print("usage: blender -b --python blender_pseudo_rig_fit.py -- --job job.json", file=sys.stderr)
        return 2
    job_path = Path(argv[1])
    try:
        run(job_path)
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
