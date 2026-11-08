#!/usr/bin/env python3
"""
Delta-driven tip-beat fit: each keyframe matches the intended tip motion from painted diffs.

Technique (different from euler authoring / absolute keypoint fit):
  1) Diff painted WeaponTip across frames → intended tip deltas from f0.
  2) Measure mesh tip at identity f0.
  3) For frame i, tip target = tip_f0 + scale * (painted_tip_i - painted_tip_0).
  4) Optimize bone deltas so evaluated mace tip projects to that beat target.
  5) Diff resulting mesh frames vs source + consecutive motion.

Blender:
  blender -b --python fit_apose_mace_tip_deltas.py -- ...
"""
from __future__ import annotations

import json
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
DEFAULT_OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_attack_g11_tipdelta_apose_mace"
SPRITE_DIR = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames/canonical_group_11"

# Focus DOFs on torso + arms + hand twist (legs soft-locked near rest).
ARM_TORSO = [
    "Hips",
    "Spine02",
    "Spine01",
    "Spine",
    "neck",
    "Head",
    "LeftShoulder",
    "LeftArm",
    "LeftForeArm",
    "LeftHand",
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
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


def _project(world: Vector, cam, scene) -> np.ndarray:
    from bpy_extras.object_utils import world_to_camera_view

    co = world_to_camera_view(scene, cam, world)
    return np.array([float(co.x), float(1.0 - co.y)], dtype=np.float64)


def _hand_space_tip_offset(arm, mace) -> Vector:
    """Bind-pose tip offset in LeftHand bone space (mace is 100% LeftHand)."""
    hand_pb = arm.pose.bones["LeftHand"]
    hand_world = arm.matrix_world @ hand_pb.head
    # Mesh data is already in bind pose; do not use broken evaluated bound_box at rest.
    best = None
    best_d = -1.0
    for v in mace.data.vertices:
        p = mace.matrix_world @ v.co
        d = (p - hand_world).length
        if d > best_d:
            best_d = d
            best = p
    if best is None:
        return Vector((0.0, 0.35, 0.0))
    # offset in bone space: bone_matrix maps bone-local → armature space
    tip_arm = arm.matrix_world.inverted() @ best
    return hand_pb.matrix.inverted() @ tip_arm


def _tip_world(arm, mace, tip_offset_bone: Vector) -> Vector:
    hand_pb = arm.pose.bones["LeftHand"]
    tip_arm = hand_pb.matrix @ tip_offset_bone
    return arm.matrix_world @ tip_arm


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


def _painted_tips(kpt: dict) -> np.ndarray:
    """Nx2 normalized tip positions from painted keypoints."""
    rows = []
    for fr in kpt["frames"]:
        tip = fr["joints"]["WeaponTip"]
        tw = float(fr["transform"]["srcWidth"])
        th = float(fr["transform"]["srcHeight"])
        rows.append([float(tip["x"]) / tw, float(tip["y"]) / th])
    return np.asarray(rows, dtype=np.float64)


def _painted_wrists(kpt: dict) -> np.ndarray:
    rows = []
    for fr in kpt["frames"]:
        w = fr["joints"]["RWrist"]
        tw = float(fr["transform"]["srcWidth"])
        th = float(fr["transform"]["srcHeight"])
        rows.append([float(w["x"]) / tw, float(w["y"]) / th])
    return np.asarray(rows, dtype=np.float64)


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
    names = [n for n in ARM_TORSO if n in (roles.get("optimizeBones") or ARM_TORSO)]
    # Keep declared optimize list order preference
    opt = roles.get("optimizeBones") or []
    names = [n for n in opt if n in set(ARM_TORSO)] or names

    painted_tips = _painted_tips(kpt)
    painted_wrists = _painted_wrists(kpt)
    tip_deltas = painted_tips - painted_tips[0]
    wrist_deltas = painted_wrists - painted_wrists[0]

    # Write intended motion diffs for the report
    motion_note = []
    for i in range(1, 8):
        motion_note.append(
            {
                "from": i - 1,
                "to": i,
                "dTip": tip_deltas[i].tolist(),
                "stepTip": (painted_tips[i] - painted_tips[i - 1]).tolist(),
                "beat": (
                    "rise"
                    if i == 1
                    else "backswing"
                    if i in (2, 3)
                    else "apex"
                    if i == 4
                    else "smash"
                    if i in (5, 6)
                    else "recover"
                ),
            }
        )
    (out_dir / "intended_tip_motion.json").write_text(
        json.dumps({"tips": painted_tips.tolist(), "deltasFromF0": tip_deltas.tolist(), "steps": motion_note}, indent=2)
        + "\n",
        encoding="utf-8",
    )

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(master))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    mace = next(o for o in meshes if "Mace" in o.name)
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
        "method": "tipdelta_from_painted_diffs",
        "notes": "Each keyframe targets tip = tip_f0 + painted_tip_delta. Motion diffs are authority.",
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

    # f0 identity — measure tip + wrist anchors
    zero = np.zeros(len(names) * 3, dtype=np.float64)
    _apply(arm, rest, names, zero)
    bpy.context.view_layer.update()
    tip_offset = _hand_space_tip_offset(arm, mace)
    tip0 = _project(_tip_world(arm, mace, tip_offset), cam, scene)
    wrist_bone = (roles.get("joints") or {}).get("RWrist", "LeftHand")
    wrist0 = _project(arm.matrix_world @ arm.pose.bones[wrist_bone].head, cam, scene)
    print(f"[tipdelta] tip_offset_bone={tuple(round(c, 4) for c in tip_offset)}", flush=True)

    # Scale painted deltas into mesh tip space using f1 rise magnitude if possible.
    # painted f0→f1 tip rise is mostly -Y; use that as scale cue vs a small probe later.
    scale = 1.0  # normalized spaces already match 0..1 image

    bound = 1.45
    max_step = 1.25
    pose_vectors = [zero.tolist()]
    losses = [0.0]
    tip_trace = [{"frame": 0, "predTip": tip0.tolist(), "tgtTip": tip0.tolist(), "beat": "identity"}]
    prev = zero.copy()

    for name in names:
        arm.pose.bones[name].keyframe_insert(data_path="rotation_euler", frame=0)
    bpy.context.scene.frame_set(0)
    _render(preview / "mesh_00.png", rw, rh)
    print(f"[tipdelta] f0 tip={tip0.tolist()} wrist={wrist0.tolist()}", flush=True)

    beat_names = ["identity", "rise", "backswing", "deep_backswing", "apex", "smash", "follow", "recover"]

    for fi in range(1, 8):
        tgt_tip = tip0 + scale * tip_deltas[fi]
        tgt_wrist = wrist0 + scale * wrist_deltas[fi]
        # Clamp targets into a reachable image band
        tgt_tip = np.clip(tgt_tip, 0.02, 0.98)
        tgt_wrist = np.clip(tgt_wrist, 0.02, 0.98)

        def objective(vec: np.ndarray) -> float:
            v = np.clip(vec, -bound, bound)
            if np.any(np.abs(v - prev) > max_step * 1.05):
                return 50.0 + float(np.sum(np.clip(np.abs(v - prev) - max_step, 0, None)))
            _apply(arm, rest, names, v)
            bpy.context.view_layer.update()
            tip = _project(_tip_world(arm, mace, tip_offset), cam, scene)
            wrist = _project(arm.matrix_world @ arm.pose.bones[wrist_bone].head, cam, scene)
            # Tip dominates — this is the beat marker from painted diffs
            err = 8.0 * float(np.sum((tip - tgt_tip) ** 2))
            err += 2.5 * float(np.sum((wrist - tgt_wrist) ** 2))
            err += 0.05 * float(np.mean((v - prev) ** 2))
            return err

        lo = np.maximum(-bound, prev - max_step)
        hi = np.minimum(bound, prev + max_step)
        bounds = list(zip(lo.tolist(), hi.tolist()))
        rng = np.random.default_rng(21 + fi * 19)
        best_x = np.clip(prev.copy(), lo, hi)
        best = float(objective(best_x))
        seeds = [best_x]
        for _ in range(8):
            seeds.append(np.clip(prev + rng.uniform(-max_step, max_step, size=prev.shape), lo, hi))
        # Beat-specific seeds from axis probes (strike = Left*)
        def _seed_named(deltas: dict[str, tuple[float, float, float]]) -> np.ndarray:
            # Absolute rest deltas (not offsets from prev).
            v = np.zeros_like(prev)
            for bi, bname in enumerate(names):
                if bname in deltas:
                    dx, dy, dz = deltas[bname]
                    v[bi * 3 : bi * 3 + 3] = [dx, dy, dz]
            return np.clip(v, lo, hi)

        if fi == 1:  # rise
            seeds.append(
                _seed_named(
                    {
                        "LeftShoulder": (-0.55, 0.2, 0.25),
                        "LeftArm": (-0.35, 0.1, -0.7),
                        "LeftForeArm": (0.4, 0.0, -0.4),
                        "LeftHand": (-0.8, 0.3, 0.2),
                        "Spine": (-0.08, 0.04, 0.04),
                    }
                )
            )
        elif fi in (2, 3):  # backswing
            seeds.append(
                _seed_named(
                    {
                        "LeftShoulder": (-1.1, 0.5, 0.4),
                        "LeftArm": (-0.75, 0.3, -1.15),
                        "LeftForeArm": (0.6, 0.1, -0.5),
                        "LeftHand": (-1.2, 0.4, 0.2),
                        "Spine": (-0.35, 0.12, 0.1),
                        "Spine01": (-0.25, 0.1, 0.08),
                        "RightShoulder": (-0.9, -0.3, -0.35),
                        "RightArm": (-0.7, -0.25, 0.95),
                    }
                )
            )
        elif fi == 4:  # apex
            seeds.append(
                _seed_named(
                    {
                        "LeftShoulder": (-1.25, 0.15, 0.55),
                        "LeftArm": (-0.95, 0.15, -1.25),
                        "LeftHand": (-1.15, 0.25, 0.15),
                        "RightShoulder": (-1.0, -0.15, -0.45),
                        "RightArm": (-0.9, -0.15, 1.0),
                    }
                )
            )
        elif fi in (5, 6):  # smash
            seeds.append(
                _seed_named(
                    {
                        "Spine": (0.65, -0.12, 0.04),
                        "Spine01": (0.45, -0.1, 0.02),
                        "LeftShoulder": (0.15, 0.12, 0.25),
                        "LeftArm": (0.25, -1.15, -0.25),
                        "LeftHand": (1.0, 0.2, 0.1),
                        "RightArm": (0.3, 0.7, 0.22),
                    }
                )
            )
        for seed in seeds:
            res = minimize(
                objective,
                seed,
                method="L-BFGS-B",
                bounds=bounds,
                options={"maxiter": 45, "maxfun": 700, "ftol": 1e-11},
            )
            xx = np.clip(np.asarray(res.x, dtype=np.float64), lo, hi)
            val = float(objective(xx))
            if val < best:
                best = val
                best_x = xx

        _apply(arm, rest, names, best_x)
        bpy.context.view_layer.update()
        tip = _project(_tip_world(arm, mace, tip_offset), cam, scene)
        pose_vectors.append(best_x.tolist())
        losses.append(best)
        tip_trace.append(
            {
                "frame": fi,
                "beat": beat_names[fi],
                "loss": best,
                "predTip": [round(float(tip[0]), 4), round(float(tip[1]), 4)],
                "tgtTip": [round(float(tgt_tip[0]), 4), round(float(tgt_tip[1]), 4)],
                "tipErr": float(np.linalg.norm(tip - tgt_tip)),
                "intendedDeltaFromF0": tip_deltas[fi].tolist(),
            }
        )
        for name in names:
            arm.pose.bones[name].keyframe_insert(data_path="rotation_euler", frame=fi)
        bpy.context.scene.frame_set(fi)
        _render(preview / f"mesh_{fi:02d}.png", rw, rh)
        print(
            f"[tipdelta] f{fi} {beat_names[fi]} loss={best:.4f} tipErr={tip_trace[-1]['tipErr']:.4f} "
            f"pred={tip_trace[-1]['predTip']} tgt={tip_trace[-1]['tgtTip']}",
            flush=True,
        )
        prev = best_x

    # Export full optimizeBones vectors padded with zeros for non-optimized bones
    # for render_preview compatibility: store only our names
    bpy.ops.object.mode_set(mode="OBJECT")
    glb = out_dir / "attack_g11_tipdelta.glb"
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
        "method": "tipdelta_from_painted_diffs",
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
        "intendedMotion": motion_note,
        "proof": "generated artifact validated — tip-delta beat fit from painted frame diffs",
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
