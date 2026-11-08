#!/usr/bin/env python3
"""
Fine-stage pose refine against absolute chroma/pixel loss on the sprite grid.

Warm-starts from joint-fit poseVectors. One Blender session keeps the mesh/camera
loaded; each eval only updates pose and redraws — it does not re-import the GLB.

Optimizer:
  Outer loop runs until lossFloor or maxSteps. Inner L-BFGS-B descends one basin;
  local convergence is non-terminal — a growing random jolt restarts search from
  the best-so-far pose (basin-hopping). Closed-ended: do not stop merely because
  a local minimum looks flat.

Inner-loop draw path (background-safe):
  BLENDER_WORKBENCH FLAT+TEXTURE at low resolution, compare at that same grid.
  OpenGL / GPUOffScreen viewport capture is unavailable under `blender -b` here
  (no GL context), so Workbench is the iteration engine. Full Eevee stills stay
  with the absolute-match gate / preview.

Blender:
  blender -b --python blender_refine_absolute_chroma.py -- --job job.json --report fit_report.json
"""
from __future__ import annotations

import json
import sys
import tempfile
import traceback
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Vector
from PIL import Image

_TOOL_DIR = Path(__file__).resolve().parent
if str(_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOL_DIR))
from absolute_chroma_match import compare_absolute  # noqa: E402
from homm3_pose_camera import setup_pose_camera  # noqa: E402


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {"job": None, "report": None}
    i = 0
    while i < len(args):
        if args[i] == "--job" and i + 1 < len(args):
            out["job"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--report" and i + 1 < len(args):
            out["report"] = Path(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["job"] or not out["report"]:
        raise SystemExit("need --job and --report")
    return out


def _force_unlit_baked(mesh_obj) -> None:
    for mat in mesh_obj.data.materials:
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        nodes = nt.nodes
        links = nt.links
        out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if out is None or bsdf is None:
            continue
        base_in = bsdf.inputs.get("Base Color")
        emit = nodes.new(type="ShaderNodeEmission")
        emit.location = (bsdf.location.x + 200.0, bsdf.location.y)
        emit.inputs["Strength"].default_value = 1.0
        if base_in is not None and base_in.is_linked:
            links.new(base_in.links[0].from_socket, emit.inputs["Color"])
        elif base_in is not None:
            emit.inputs["Color"].default_value = tuple(base_in.default_value)
        links.new(emit.outputs["Emission"], out.inputs["Surface"])


def _apply_pose(arm, rest, names, vec, *, root_rest, cam_axes, root_translate: bool) -> None:
    n_rot = len(names) * 3
    for i, name in enumerate(names):
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        base = rest[name]
        dx, dy, dz = float(vec[i * 3]), float(vec[i * 3 + 1]), float(vec[i * 3 + 2])
        pb.rotation_euler = Euler((base.x + dx, base.y + dy, base.z + dz), "XYZ")
    if root_translate:
        right, up, forward = cam_axes
        tr, tu, tf = float(vec[n_rot]), float(vec[n_rot + 1]), float(vec[n_rot + 2])
        arm.location = root_rest + right * tr + up * tu + forward * tf
    else:
        arm.location = Vector(root_rest)


class WarmPoseCapture:
    """
    Persistent still-capture for pose iteration inside one Blender session.

    Pose changes only; mesh/camera/materials stay loaded. Renders into one
    reused filepath at a fixed low resolution and returns that grid (no upscale).
    """

    def __init__(
        self,
        scene,
        *,
        width: int,
        height: int,
        path: Path,
        engine: str = "BLENDER_WORKBENCH",
        taa_samples: int = 1,
    ) -> None:
        self.scene = scene
        self.width = int(width)
        self.height = int(height)
        self.path = Path(path)
        self.engine = str(engine)
        self._configure(taa_samples=taa_samples)
        # Warm the engine / shader compile once.
        self.capture()

    def _configure(self, *, taa_samples: int) -> None:
        sc = self.scene
        sc.render.engine = self.engine
        if self.engine == "BLENDER_EEVEE":
            sc.eevee.taa_render_samples = max(1, int(taa_samples))
        elif self.engine == "BLENDER_WORKBENCH":
            # Flat+texture ≈ unlit baked look; far cheaper than Eevee TAA stills.
            sc.display.shading.light = "FLAT"
            sc.display.shading.color_type = "TEXTURE"
            sc.display.shading.show_specular_highlight = False
            sc.display.shading.show_backface_culling = True
        sc.render.resolution_x = self.width
        sc.render.resolution_y = self.height
        sc.render.resolution_percentage = 100
        sc.render.filepath = str(self.path)
        sc.render.image_settings.file_format = "PNG"
        sc.render.image_settings.color_mode = "RGBA"
        sc.render.film_transparent = True

    def capture(self) -> np.ndarray:
        bpy.ops.render.render(write_still=True)
        # Native capture resolution only — never upscale inside the hot loop.
        im = Image.open(self.path).convert("RGBA")
        if im.size != (self.width, self.height):
            im = im.resize((self.width, self.height), Image.Resampling.BILINEAR)
        return np.asarray(im, dtype=np.float32)


def run(job_path: Path, report_path: Path) -> dict:
    from scipy.optimize import minimize

    job = json.loads(job_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    refine_cfg = job.get("absoluteRefine") or {}
    if not bool(refine_cfg.get("enabled", True)):
        print("[abs-refine] disabled", flush=True)
        return {"ok": True, "skipped": True}

    match_cfg = job.get("absoluteMatch") or {}
    palette_normalize = bool(match_cfg.get("paletteNormalize", True))
    alpha_thr = float(match_cfg.get("alphaThr", 8.0))
    render_scale = float(refine_cfg.get("renderScale", 0.25))
    # Real L-BFGS iterations (not raw fevals). FD needs ~(dof+1) fevals per step.
    max_steps = int(refine_cfg.get("maxSteps", refine_cfg.get("maxiter", 50)))
    max_steps = max(50, max_steps)
    bound_delta = float(refine_cfg.get("boundDeltaRad", 0.35))
    root_delta = float(refine_cfg.get("rootDelta", 0.20))
    active = list(refine_cfg.get("activeBones") or [])
    chroma_w = float(refine_cfg.get("chromaWeight", 1.0))
    rgb_w = float(refine_cfg.get("rgbWeight", 0.25))
    engine = str(refine_cfg.get("engine", "BLENDER_WORKBENCH"))
    taa_samples = int(refine_cfg.get("taaSamples", 1))
    # Lab is expensive; hot loop uses RGB proxy unless explicitly enabled.
    loop_chroma = bool(refine_cfg.get("loopIncludeChroma", False))
    fd_eps = float(refine_cfg.get("finiteDiffEps", 0.02))
    loss_floor = float(refine_cfg.get("lossFloor", 1e-3))
    # Local L-BFGS chunk size; after each basin, jolt and continue until floor or maxSteps.
    local_chunk = int(refine_cfg.get("localChunkSteps", 8))
    local_chunk = max(1, local_chunk)
    jolt_frac = float(refine_cfg.get("joltFrac", 0.35))
    jolt_grow = float(refine_cfg.get("joltGrow", 1.20))
    jolt_frac_max = float(refine_cfg.get("joltFracMax", 0.95))

    out_dir = Path(job["outputDir"]) / "absolute_refine"
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="abs_refine_"))

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=job["masterGlb"])
    arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    for mesh in meshes:
        _force_unlit_baked(mesh)

    names = list(report["optimizeBones"])
    rest = {}
    for name in names:
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        rest[name] = pb.rotation_euler.copy()
    root_rest = arm.location.copy()
    root_translate = bool(report.get("rootTranslate", False))
    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    m = cam.matrix_world.to_3x3()
    cam_axes = (
        (m @ Vector((1.0, 0.0, 0.0))).normalized(),
        (m @ Vector((0.0, 1.0, 0.0))).normalized(),
        (m @ Vector((0.0, 0.0, -1.0))).normalized(),
    )

    world = bpy.data.worlds.new("AbsRefineWorld")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.0, 0.0, 0.0, 1)
    bg.inputs["Strength"].default_value = 0.0

    scene = bpy.context.scene
    n_rot = len(names) * 3
    if not active:
        active = list(names)
    free_idx: list[int] = []
    for n in active:
        if n not in names:
            continue
        bi = names.index(n) * 3
        free_idx.extend([bi, bi + 1, bi + 2])
    if root_translate:
        free_idx.extend([n_rot, n_rot + 1, n_rot + 2])
    free_idx = sorted(set(free_idx))
    n_dof = len(free_idx)
    # Finite-diff L-BFGS burns ~(dof+1) fevals per real step — size the budget for that.
    fev_per_step = n_dof + 1
    maxfev_default = max_steps * fev_per_step + 64
    maxfev = int(refine_cfg.get("maxfev", maxfev_default))
    if maxfev < maxfev_default:
        print(
            f"[abs-refine] NOTE: maxfev={maxfev} < {maxfev_default} needed for "
            f"{max_steps} FD steps × {n_dof} dof; raising to {maxfev_default}",
            flush=True,
        )
        maxfev = maxfev_default

    pose_vectors = [np.asarray(v, dtype=np.float64).copy() for v in report["poseVectors"]]
    # Prefer joint-only warm start if this report was already refined once.
    kpt_path = Path(job["outputDir"]) / "fit_report_kpt.json"
    if kpt_path.is_file() and "absoluteRefine" in report:
        kpt = json.loads(kpt_path.read_text(encoding="utf-8"))
        if kpt.get("poseVectors") and len(kpt["poseVectors"]) == len(pose_vectors):
            pose_vectors = [np.asarray(v, dtype=np.float64).copy() for v in kpt["poseVectors"]]
            print(f"[abs-refine] warm-start from {kpt_path.name} (joint fit)", flush=True)

    frame_stats = []
    rng = np.random.default_rng(int(refine_cfg.get("seed", 11)))

    # One capture target for the whole clip — resolution may be reconfigured per frame
    # only when sprite aspect forces different rx/ry (same scale → stable).
    capture: WarmPoseCapture | None = None

    print(
        f"[abs-refine] warm session engine={engine} scale={render_scale} "
        f"maxSteps={max_steps} maxfev={maxfev} (~{fev_per_step} fev/step) "
        f"lossFloor={loss_floor} localChunk={local_chunk} "
        f"joltFrac={jolt_frac} freeDof={n_dof} loopChroma={loop_chroma}",
        flush=True,
    )

    for i, warm in enumerate(pose_vectors):
        sprite_path = Path(job["frames"][i]["path"])
        spr_full = np.asarray(Image.open(sprite_path).convert("RGBA"), dtype=np.float32)
        sh, sw = spr_full.shape[0], spr_full.shape[1]
        rx = max(32, int(round(sw * render_scale)))
        ry = max(32, int(round(sh * render_scale)))
        spr = np.asarray(
            Image.fromarray(spr_full.astype(np.uint8)).resize((rx, ry), Image.Resampling.BILINEAR),
            dtype=np.float32,
        )
        render_path = tmp_dir / "capture.png"
        if capture is None or capture.width != rx or capture.height != ry or capture.engine != engine:
            capture = WarmPoseCapture(
                scene,
                width=rx,
                height=ry,
                path=render_path,
                engine=engine,
                taa_samples=taa_samples,
            )
        else:
            capture.path = render_path
            capture._configure(taa_samples=taa_samples)

        def pack(full: np.ndarray) -> np.ndarray:
            return np.array([full[j] for j in free_idx], dtype=np.float64)

        def unpack(partial: np.ndarray, base: np.ndarray) -> np.ndarray:
            out = base.copy()
            for k, j in enumerate(free_idx):
                out[j] = float(partial[k])
            return out

        class _LossFloorHit(Exception):
            def __init__(self, x: np.ndarray, loss: float):
                super().__init__(f"loss floor {loss}")
                self.x = np.asarray(x, dtype=np.float64).copy()
                self.loss = float(loss)

        track = {"fev": 0, "nit": 0, "last_loss": None}

        def objective(partial: np.ndarray, _warm=warm) -> float:
            full = unpack(partial, _warm)
            for j in free_idx:
                if j < n_rot:
                    if abs(full[j] - _warm[j]) > bound_delta * 1.05:
                        return 1e3 + abs(full[j] - _warm[j])
                else:
                    if abs(full[j] - _warm[j]) > root_delta * 1.05:
                        return 1e3 + abs(full[j] - _warm[j])
            _apply_pose(
                arm,
                rest,
                names,
                full,
                root_rest=root_rest,
                cam_axes=cam_axes,
                root_translate=root_translate,
            )
            bpy.context.view_layer.update()
            assert capture is not None
            mesh = capture.capture()
            cmp = compare_absolute(
                spr,
                mesh,
                alpha_thr=alpha_thr,
                palette_normalize=palette_normalize,
                include_chroma=loop_chroma,
            )
            loss = float(chroma_w * cmp["chromaMae"] + rgb_w * cmp["rgbMae"])
            track["fev"] += 1
            track["last_loss"] = loss
            if loss <= loss_floor:
                raise _LossFloorHit(partial, loss)
            return loss

        def _cb(_xk) -> None:
            track["nit"] += 1

        x0 = pack(warm)
        lo = []
        hi = []
        for j in free_idx:
            if j < n_rot:
                lo.append(warm[j] - bound_delta)
                hi.append(warm[j] + bound_delta)
            else:
                lo.append(warm[j] - root_delta)
                hi.append(warm[j] + root_delta)
        bounds = list(zip(lo, hi))

        best_x = x0.copy()
        try:
            best = float(objective(x0))
        except _LossFloorHit as hit:
            best = float(hit.loss)
            best_x = np.clip(hit.x, lo, hi)
        start = best
        stop_reason = "loss_floor" if best <= loss_floor else "max_steps"

        # Basin-hopping style: local L-BFGS is only a tool inside a basin.
        # Local convergence is NOT terminal — jolt and continue until loss floor or step cap.
        x_cur = best_x.copy()
        total_nit = 0
        jolts = 0
        lo_a = np.asarray(lo, dtype=np.float64)
        hi_a = np.asarray(hi, dtype=np.float64)
        span = np.maximum(hi_a - lo_a, 1e-6)

        while best > loss_floor and total_nit < max_steps:
            chunk = min(local_chunk, max_steps - total_nit)
            chunk_fev = chunk * fev_per_step + 16
            track["nit"] = 0
            try:
                result = minimize(
                    objective,
                    x_cur,
                    method="L-BFGS-B",
                    bounds=bounds,
                    callback=_cb,
                    options={
                        "maxiter": chunk,
                        "maxfun": chunk_fev,
                        # Tight numeric tol inside the basin; outer loop decides when to stop.
                        "ftol": 1e-12,
                        "gtol": 1e-10,
                        "eps": fd_eps,
                    },
                )
                nit = max(int(getattr(result, "nit", track["nit"])), 1)
                xx = np.clip(np.asarray(result.x, dtype=np.float64), lo, hi)
                try:
                    val = float(objective(xx))
                except _LossFloorHit as hit:
                    xx = np.clip(hit.x, lo, hi)
                    val = float(hit.loss)
                    total_nit += nit
                    if val < best:
                        best = val
                        best_x = xx.copy()
                    stop_reason = "loss_floor"
                    break
            except _LossFloorHit as hit:
                nit = max(int(track["nit"]), 1)
                xx = np.clip(hit.x, lo, hi)
                val = float(hit.loss)
                total_nit += nit
                if val < best:
                    best = val
                    best_x = xx.copy()
                stop_reason = "loss_floor"
                break

            total_nit += nit
            if val < best:
                best = val
                best_x = xx.copy()
            if best <= loss_floor:
                stop_reason = "loss_floor"
                break
            if total_nit >= max_steps:
                stop_reason = "max_steps"
                break

            # Jolt out of the basin from the best-so-far pose (keep global best).
            frac = min(jolt_frac_max, jolt_frac * (jolt_grow**jolts))
            noise = rng.uniform(-1.0, 1.0, size=n_dof) * (span * frac)
            x_cur = np.clip(best_x + noise, lo, hi)
            jolts += 1
            # Optional accept-if-better probe; always descend from jolted point next.
            try:
                jolt_loss = float(objective(x_cur))
                if jolt_loss < best:
                    best = jolt_loss
                    best_x = x_cur.copy()
                    if best <= loss_floor:
                        stop_reason = "loss_floor"
                        break
            except _LossFloorHit as hit:
                best = float(hit.loss)
                best_x = np.clip(hit.x, lo, hi)
                stop_reason = "loss_floor"
                break

        total_fev = int(track["fev"])
        if best <= loss_floor:
            stop_reason = "loss_floor"
        elif total_nit >= max_steps:
            stop_reason = "max_steps"

        refined = unpack(best_x, warm)
        pose_vectors[i] = refined
        _apply_pose(
            arm,
            rest,
            names,
            refined,
            root_rest=root_rest,
            cam_axes=cam_axes,
            root_translate=root_translate,
        )
        bpy.context.view_layer.update()
        assert capture is not None
        mesh_loop = capture.capture()
        cmp_loop = compare_absolute(
            spr,
            mesh_loop,
            alpha_thr=alpha_thr,
            palette_normalize=palette_normalize,
            include_chroma=True,
        )
        st = {
            "frameIndex": i,
            "startLoss": start,
            "refineLoss": best,
            "nfev": total_fev,
            "nit": total_nit,
            "jolts": jolts,
            "maxSteps": max_steps,
            "localChunkSteps": local_chunk,
            "stopReason": stop_reason,
            "lossFloor": loss_floor,
            "rgbMae": cmp_loop["rgbMae"],
            "chromaMae": cmp_loop["chromaMae"],
            "renderScale": render_scale,
            "captureWh": [rx, ry],
            "engine": engine,
            "freeDofCount": len(free_idx),
            "note": (
                "jolt-until-floor/maxSteps; local L-BFGS convergence is non-terminal; "
                "loop metrics at warm capture resolution; absoluteMatch gate uses full Eevee sprite grid"
            ),
        }
        frame_stats.append(st)
        print(
            f"[abs-refine] frame {i} start={start:.2f} best={best:.2f} "
            f"loopChroma={cmp_loop['chromaMae']:.2f} loopRgb={cmp_loop['rgbMae']:.2f} "
            f"steps~{total_nit}/{max_steps} jolts={jolts} evals~{total_fev} "
            f"stop={stop_reason} {rx}x{ry}",
            flush=True,
        )

    report_out = dict(report)
    report_out["poseVectors"] = [v.tolist() for v in pose_vectors]
    report_out["absoluteRefine"] = {
        "enabled": True,
        "renderScale": render_scale,
        "engine": engine,
        "activeBones": active,
        "frames": frame_stats,
        "proof": (
            "generated artifact validated — warm-session Workbench/low-res absolute refine "
            "from joint warm-start; absoluteMatch gate is the full-grid authority; "
            "not OE runtime proven"
        ),
    }
    report_out["method"] = str(report.get("method", "keypoint_reprojection")) + "+absolute_chroma_refine"
    out_report = out_dir / "fit_report_refined.json"
    out_report.write_text(json.dumps(report_out, indent=2) + "\n", encoding="utf-8")
    primary = Path(job["outputDir"]) / "fit_report.json"
    primary.write_text(json.dumps(report_out, indent=2) + "\n", encoding="utf-8")
    # Preserve pre-refine joint fit if present; do not overwrite with refined.
    kpt_backup = Path(job["outputDir"]) / "fit_report_kpt.json"
    if not kpt_backup.is_file():
        kpt_backup.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(out_report), "primary": str(primary)}, indent=2), flush=True)
    return report_out


def main() -> int:
    try:
        opts = _parse()
        run(opts["job"], opts["report"])
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
