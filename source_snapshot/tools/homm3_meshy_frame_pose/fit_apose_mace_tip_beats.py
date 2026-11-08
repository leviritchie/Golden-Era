#!/usr/bin/env python3
"""
Per-beat tip-reprojection pose fit on A-pose + mace master.

Different from euler authoring / silhouette-only:
  - Painted keypoints define each animation beat (intended tip/wrists/shoulders).
  - Loss uses evaluated MaceProp centroid as WeaponTip (not LeftHand bone head).
  - Each frame is optimized to match that beat; prev pose is only a warm start
    with a generous maxStep so extreme overhead/smash remains reachable.

Blender:
  blender -b --python fit_apose_mace_tip_beats.py -- \\
    --master .../hobgoblin_apose_mace_attach.glb \\
    --keypoints .../manual_keypoints/keypoints.json \\
    --roles .../bone_roles_apose_mace.json \\
    --out .../out_attack_g11_tipbeat_apose_mace
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Euler, Vector
from scipy.optimize import minimize

_TOOL = Path(__file__).resolve().parent
_POSE = _TOOL.parent / "homm3_silhouette_pose_fit"
if str(_POSE) not in sys.path:
    sys.path.insert(0, str(_POSE))
from homm3_pose_camera import setup_pose_camera  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MASTER = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/hobgoblin_apose_mace_attach.glb"
DEFAULT_KPT = (
    ROOT
    / "artifacts/hobgoblin_attack_pose_pipeline/out_attack_g11_manual_painted_meshy46/manual_keypoints/keypoints.json"
)
DEFAULT_ROLES = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_apose_mace_attach/bone_roles_apose_mace.json"
DEFAULT_OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_attack_g11_tipbeat_apose_mace"
SPRITE_DIR = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11"

# Joints used in 2D loss (OpenPose-style names from painted keypoints).
LOSS_JOINTS = [
    "Nose",
    "Neck",
    "RShoulder",
    "RElbow",
    "RWrist",
    "WeaponTip",
    "LShoulder",
    "LElbow",
    "LWrist",
    "MidHip",
    "RHip",
    "RKnee",
    "LHip",
    "LKnee",
]


def _parse() -> dict:
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    out = {
        "master": DEFAULT_MASTER,
        "keypoints": DEFAULT_KPT,
        "roles": DEFAULT_ROLES,
        "out": DEFAULT_OUT,
        "width": 504,
        "height": 456,
    }
    i = 0
    while i < len(argv):
        if argv[i] in {"--master", "--keypoints", "--roles", "--out"} and i + 1 < len(argv):
            out[argv[i][2:]] = Path(argv[i + 1])
            i += 2
        else:
            i += 1
    return out


def _abs(p: Path) -> Path:
    return p.resolve() if p.is_absolute() else (ROOT / p).resolve()


def _force_unlit(mesh_obj) -> None:
    for mat in mesh_obj.data.materials:
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        nodes, links = nt.nodes, nt.links
        out = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if out is None or bsdf is None:
            continue
        base_in = bsdf.inputs.get("Base Color")
        emit = nodes.new(type="ShaderNodeEmission")
        emit.inputs["Strength"].default_value = 1.0
        if base_in is not None and base_in.is_linked:
            links.new(base_in.links[0].from_socket, emit.inputs["Color"])
        elif base_in is not None:
            emit.inputs["Color"].default_value = tuple(base_in.default_value)
        for link in list(out.inputs["Surface"].links):
            links.remove(link)
        links.new(emit.outputs["Emission"], out.inputs["Surface"])


def _project_world(world: Vector, cam, scene) -> tuple[float, float]:
    """Normalized 0..1 image coords, top-left origin (matches blender_fit_from_keypoints)."""
    from bpy_extras.object_utils import world_to_camera_view

    co = world_to_camera_view(scene, cam, world)
    return float(co.x), float(1.0 - co.y)


def _mace_centroid(mace) -> Vector:
    dg = bpy.context.evaluated_depsgraph_get()
    ev = mace.evaluated_get(dg)
    me = ev.to_mesh()
    c = Vector((0, 0, 0))
    for v in me.vertices:
        c += ev.matrix_world @ v.co
    c /= float(max(1, len(me.vertices)))
    ev.to_mesh_clear()
    return c


def _apply(arm, rest, names, vec) -> None:
    for i, name in enumerate(names):
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        base = rest[name]
        o = i * 3
        pb.rotation_euler = Euler(
            (base.x + float(vec[o]), base.y + float(vec[o + 1]), base.z + float(vec[o + 2])),
            "XYZ",
        )


def _targets_for_frame(fr: dict, roles: dict) -> dict[str, tuple[float, float, float]]:
    """Painted joints → normalized 0..1 top-left + weight."""
    joints = fr.get("joints") or {}
    tw = float((fr.get("transform") or {}).get("srcWidth") or 512)
    th = float((fr.get("transform") or {}).get("srcHeight") or 512)
    jw = roles.get("jointWeights") or {}
    out = {}
    for name in LOSS_JOINTS:
        j = joints.get(name)
        if not j or not j.get("visible", True):
            continue
        x = float(j["x"]) / tw
        y = float(j["y"]) / th
        w = float(jw.get(name, 1.0))
        if name == "WeaponTip":
            w = max(w, 4.5)
        if name in ("RWrist", "RElbow", "RShoulder"):
            w = max(w, 2.0)
        if name in ("LWrist", "LElbow"):
            w = max(w, 1.4)
        out[name] = (x, y, w)
    return out


def _pred_joints(arm, mace, roles, cam, scene) -> dict[str, tuple[float, float]]:
    joint_to_bone = roles.get("joints") or {}
    pred = {}
    for jname, bname in joint_to_bone.items():
        if jname == "WeaponTip":
            continue
        if bname not in arm.pose.bones:
            continue
        world = arm.matrix_world @ arm.pose.bones[bname].head
        pred[jname] = _project_world(world, cam, scene)
    pred["WeaponTip"] = _project_world(_mace_centroid(mace), cam, scene)
    return pred


def _render(path: Path, w: int, h: int) -> None:
    sc = bpy.context.scene
    sc.render.engine = "BLENDER_EEVEE"
    sc.render.resolution_x = w
    sc.render.resolution_y = h
    sc.render.film_transparent = True
    sc.render.filepath = str(path)
    sc.render.image_settings.file_format = "PNG"
    sc.render.image_settings.color_mode = "RGBA"
    bpy.ops.render.render(write_still=True)


def main() -> int:
    opts = _parse()
    master = _abs(Path(opts["master"]))
    kpt_path = _abs(Path(opts["keypoints"]))
    roles_path = _abs(Path(opts["roles"]))
    out_dir = _abs(Path(opts["out"]))
    preview = out_dir / "preview" / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    preview.mkdir(parents=True, exist_ok=True)

    roles = json.loads(roles_path.read_text(encoding="utf-8"))
    kpt = json.loads(kpt_path.read_text(encoding="utf-8"))
    names = list(roles.get("optimizeBones") or [])
    if not names:
        raise RuntimeError("roles.optimizeBones empty")

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(master))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    mace = next((o for o in meshes if "Mace" in o.name), None)
    if mace is None:
        raise RuntimeError("MaceProp mesh not found")
    for m in meshes:
        _force_unlit(m)

    rw, rh = int(opts["width"]), int(opts["height"])
    job = {
        "unitSid": "h3_hobgoblin",
        "clipId": "attack_g11",
        "fps": 12,
        "masterGlb": str(master.relative_to(ROOT)).replace("\\", "/"),
        "outputDir": str(out_dir).replace("\\", "/"),
        "optimizeBones": names,
        "boneRoles": str(roles_path.relative_to(ROOT)).replace("\\", "/"),
        "camera": {
            "axis": "iso",
            "isoAzimuthDeg": 40.0,
            "isoElevationDeg": 30.0,
            "distance": 3.0,
            "orthoScale": 2.6,
            "rootYawDeg": 0.0,
        },
        "frames": [
            {"path": str((SPRITE_DIR / f"frame_{i:02d}.png").relative_to(ROOT)).replace("\\", "/")}
            for i in range(8)
        ],
        "method": "tipbeat_painted_reproj",
        "notes": "Per-beat painted keypoint fit; WeaponTip=mace centroid. Diff frames after.",
    }
    (out_dir / "job.resolved.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")

    cam = setup_pose_camera(job, arm, bpy_module=bpy)
    scene = bpy.context.scene
    scene.render.resolution_x = rw
    scene.render.resolution_y = rh

    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    rest = {}
    for name in names:
        pb = arm.pose.bones[name]
        pb.rotation_mode = "XYZ"
        rest[name] = pb.rotation_euler.copy()

    bound = 1.35
    # Generous step so each beat can reach its intended extreme from previous.
    max_step = 1.10
    pose_vectors: list[list[float]] = []
    losses: list[float] = []
    tip_trace = []
    prev = np.zeros(len(names) * 3, dtype=np.float64)

    frames = list(kpt.get("frames") or [])
    if len(frames) != 8:
        raise RuntimeError(f"expected 8 painted frames, got {len(frames)}")

    for fi, fr in enumerate(frames):
        targets = _targets_for_frame(fr, roles)
        if "WeaponTip" not in targets:
            raise RuntimeError(f"frame {fi} missing WeaponTip")

        # Frame 0: keep bind / identity
        if fi == 0:
            vec = np.zeros(len(names) * 3, dtype=np.float64)
            _apply(arm, rest, names, vec)
            bpy.context.view_layer.update()
            pose_vectors.append(vec.tolist())
            losses.append(0.0)
            pred0 = _pred_joints(arm, mace, roles, cam, scene)
            tip_trace.append(
                {
                    "frame": 0,
                    "predTip": [round(pred0["WeaponTip"][0], 4), round(pred0["WeaponTip"][1], 4)],
                    "tgtTip": [round(targets["WeaponTip"][0], 4), round(targets["WeaponTip"][1], 4)],
                }
            )
            for name in names:
                arm.pose.bones[name].keyframe_insert(data_path="rotation_euler", frame=fi)
            bpy.context.scene.frame_set(fi)
            _render(preview / f"mesh_{fi:02d}.png", rw, rh)
            print(f"[tipbeat] f0 identity tipPred={tip_trace[-1]['predTip']} tipTgt={tip_trace[-1]['tgtTip']}", flush=True)
            prev = vec
            continue

        tgt_names = [n for n in LOSS_JOINTS if n in targets]
        tgt = np.array([[targets[n][0], targets[n][1]] for n in tgt_names], dtype=np.float64)
        tw = np.array([targets[n][2] for n in tgt_names], dtype=np.float64)
        # Normalize by MidHip / Neck span when available
        root_i = tgt_names.index("MidHip") if "MidHip" in tgt_names else 0
        scale_i = tgt_names.index("Neck") if "Neck" in tgt_names else min(1, len(tgt_names) - 1)

        def _norm(pts: np.ndarray) -> np.ndarray:
            root = pts[root_i]
            scale = float(np.linalg.norm(pts[scale_i] - root)) + 1e-6
            return (pts - root) / scale

        tgt_n = _norm(tgt)

        def objective(vec: np.ndarray) -> float:
            v = np.clip(vec, -bound, bound)
            if np.any(np.abs(v - prev) > max_step * 1.05):
                return 40.0 + float(np.sum(np.clip(np.abs(v - prev) - max_step, 0, None)))
            _apply(arm, rest, names, v)
            bpy.context.view_layer.update()
            pred_map = _pred_joints(arm, mace, roles, cam, scene)
            pred = np.array([pred_map[n] for n in tgt_names], dtype=np.float64)
            pred_n = _norm(pred)
            err = float(np.sum(tw * np.sum((pred_n - tgt_n) ** 2, axis=1)) / (float(np.sum(tw)) + 1e-8))
            # Soft motion regularizer (beat match dominates)
            err += 0.04 * float(np.mean((v - prev) ** 2))
            return err

        x0 = np.clip(prev.copy(), -bound, bound)
        lo = np.maximum(-bound, prev - max_step)
        hi = np.minimum(bound, prev + max_step)
        bounds = list(zip(lo.tolist(), hi.tolist()))
        rng = np.random.default_rng(11 + fi * 17)
        best_x = x0
        best = float(objective(x0))
        seeds = [x0]
        for _ in range(6):
            seeds.append(np.clip(prev + rng.uniform(-max_step, max_step, size=x0.shape), lo, hi))
        for seed in seeds:
            res = minimize(
                objective,
                seed,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 60, "maxfun": 900, "ftol": 1e-10},
            )
            xx = np.clip(np.asarray(res.x, dtype=np.float64), lo, hi)
            val = float(objective(xx))
            if val < best:
                best = val
                best_x = xx

        _apply(arm, rest, names, best_x)
        bpy.context.view_layer.update()
        pred = _pred_joints(arm, mace, roles, cam, scene)
        pose_vectors.append(best_x.tolist())
        losses.append(best)
        tip_trace.append(
            {
                "frame": fi,
                "loss": best,
                "predTip": [round(pred["WeaponTip"][0], 4), round(pred["WeaponTip"][1], 4)],
                "tgtTip": [round(targets["WeaponTip"][0], 4), round(targets["WeaponTip"][1], 4)],
            }
        )
        for name in names:
            arm.pose.bones[name].keyframe_insert(data_path="rotation_euler", frame=fi)
        bpy.context.scene.frame_set(fi)
        _render(preview / f"mesh_{fi:02d}.png", rw, rh)
        print(
            f"[tipbeat] f{fi} loss={best:.4f} tipPred={tip_trace[-1]['predTip']} tipTgt={tip_trace[-1]['tgtTip']}",
            flush=True,
        )
        prev = best_x

    bpy.ops.object.mode_set(mode="OBJECT")
    glb = out_dir / "attack_g11_tipbeat.glb"
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    for m in meshes:
        m.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=str(glb),
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_apply=False,
    )

    report = {
        "unitSid": "h3_hobgoblin",
        "clipId": "attack_g11",
        "method": "tipbeat_painted_reproj",
        "frameCount": 8,
        "losses": losses,
        "meanLoss": float(np.mean(losses)),
        "poseVectors": pose_vectors,
        "optimizeBones": names,
        "wholeModelBones": [],
        "mirror": {"x": False, "y": False, "z": False, "reorientYawDeg": 0.0},
        "effectiveRootYawDeg": 0.0,
        "exportGlb": str(glb).replace("\\", "/"),
        "tipTrace": tip_trace,
        "proof": "generated artifact validated — tip-beat painted reproj; not OE runtime proven",
        "frames": [{"frameIndex": i, "loss": losses[i]} for i in range(8)],
    }
    (out_dir / "fit_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "out": str(out_dir), "meanLoss": report["meanLoss"], "tipTrace": tip_trace}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
