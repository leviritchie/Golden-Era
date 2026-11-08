#!/usr/bin/env python3
"""
Blender: nearest-bone retarget from a Meshy-rigged donor GLB onto the master UniRig.

  blender -b --python retarget_nearest_bones.py -- \\
    --master master.glb --donor donor_rigged.glb --output out.glb \\
    --map-json bone_map.json --report fit_report.json
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


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse() -> dict:
    args = _argv()
    out = {
        "master": None,
        "donor": None,
        "output": None,
        "mapJson": None,
        "report": None,
        "maxDist": 0.35,
        "rootYawDeg": 0.0,
    }
    i = 0
    while i < len(args):
        if args[i] in {"--master", "--donor", "--output", "--map-json", "--report"} and i + 1 < len(args):
            key = {
                "--master": "master",
                "--donor": "donor",
                "--output": "output",
                "--map-json": "mapJson",
                "--report": "report",
            }[args[i]]
            out[key] = Path(args[i + 1])
            i += 2
        elif args[i] == "--max-dist" and i + 1 < len(args):
            out["maxDist"] = float(args[i + 1])
            i += 2
        elif args[i] == "--root-yaw-deg" and i + 1 < len(args):
            out["rootYawDeg"] = float(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["master"] or not out["donor"] or not out["output"]:
        raise SystemExit("need --master --donor --output")
    return out


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_pair(path: Path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objs = [o for o in bpy.data.objects if o not in before]
    arms = [o for o in objs if o.type == "ARMATURE"]
    meshes = [o for o in objs if o.type == "MESH"]
    if not arms:
        raise RuntimeError(f"no armature in {path}")
    if not meshes:
        raise RuntimeError(f"no mesh in {path}")
    return arms[0], meshes[0], objs


def _bone_heads_world(arm) -> dict[str, np.ndarray]:
    out = {}
    for pb in arm.pose.bones:
        head = arm.matrix_world @ pb.head
        out[pb.name] = np.array([head.x, head.y, head.z], dtype=np.float64)
    return out


def _pick_anchor(names: list[str], heads: dict[str, np.ndarray]) -> str:
    for cand in ("Bone_002", "Bone_000", "Bone_001", "mixamorig:Hips", "Hips", "pelvis"):
        if cand in heads:
            return cand
    # lowest Z among bones that look like roots
    return min(names, key=lambda n: float(heads[n][2]))


def _rigid_align(src: np.ndarray, dst: np.ndarray) -> tuple[np.ndarray, float, np.ndarray]:
    """
    Kabsch: src_pts (N,3) -> dst_pts (N,3).
    Returns R (3,3), scale, t (3,) such that (src @ R.T)*scale + t ≈ dst
    """
    assert src.shape == dst.shape and src.shape[0] >= 3
    src_mu = src.mean(axis=0)
    dst_mu = dst.mean(axis=0)
    X = src - src_mu
    Y = dst - dst_mu
    src_scale = np.linalg.norm(X) / math.sqrt(max(1, X.shape[0]))
    dst_scale = np.linalg.norm(Y) / math.sqrt(max(1, Y.shape[0]))
    scale = float(dst_scale / max(src_scale, 1e-8))
    Xn = X / max(src_scale, 1e-8)
    Yn = Y / max(dst_scale, 1e-8)
    H = Xn.T @ Yn
    U, _, Vt = np.linalg.svd(H)
    R = Vt.T @ U.T
    if np.linalg.det(R) < 0:
        Vt[-1, :] *= -1
        R = Vt.T @ U.T
    t = dst_mu - scale * (src_mu @ R.T)
    return R, scale, t


def _apply_object_align(arm, R: np.ndarray, scale: float, t: np.ndarray) -> None:
    M = Matrix.Identity(4)
    for i in range(3):
        for j in range(3):
            M[i][j] = float(R[i, j]) * scale
        M[i][3] = float(t[i])
    arm.matrix_world = Matrix(M) @ arm.matrix_world
    bpy.context.view_layer.update()


def _nearest_map(
    master_heads: dict[str, np.ndarray],
    donor_heads: dict[str, np.ndarray],
    max_dist: float,
) -> tuple[dict[str, str], list[dict]]:
    donor_names = list(donor_heads.keys())
    donor_pts = np.stack([donor_heads[n] for n in donor_names], axis=0)
    mapping: dict[str, str] = {}
    details = []
    used = set()
    for mname, mph in master_heads.items():
        d = np.linalg.norm(donor_pts - mph[None, :], axis=1)
        order = np.argsort(d)
        chosen = None
        dist = None
        for idx in order:
            cand = donor_names[int(idx)]
            dist = float(d[int(idx)])
            if cand in used:
                continue
            if dist > max_dist:
                break
            chosen = cand
            break
        if chosen is None:
            details.append({"master": mname, "donor": None, "dist": float(d[int(order[0])]), "ok": False})
            continue
        used.add(chosen)
        mapping[mname] = chosen
        details.append({"master": mname, "donor": chosen, "dist": dist, "ok": True})
    return mapping, details


def _copy_world_rotations(master, donor, mapping: dict[str, str]) -> None:
    """Match donor bone world orientations; never write pose translation/scale (avoids spaghetti)."""
    bpy.context.view_layer.update()
    for mname, dname in mapping.items():
        mb = master.pose.bones.get(mname)
        db = donor.pose.bones.get(dname)
        if mb is None or db is None:
            continue
        world = donor.matrix_world @ db.matrix
        local = master.convert_space(pose_bone=mb, matrix=world, from_space="WORLD", to_space="LOCAL")
        _loc, quat, _scale = local.decompose()
        mb.rotation_mode = "QUATERNION"
        mb.rotation_quaternion = quat
        mb.location = (0.0, 0.0, 0.0)
        mb.scale = (1.0, 1.0, 1.0)
    bpy.context.view_layer.update()


def run(opts: dict) -> dict:
    _clear()
    master_arm, master_mesh, _ = _import_pair(Path(opts["master"]))
    donor_arm, donor_mesh, _ = _import_pair(Path(opts["donor"]))

    # Hide donor mesh in export selection later; keep for bone positions
    donor_mesh.hide_render = True

    bpy.context.view_layer.update()
    m_heads = _bone_heads_world(master_arm)
    d_heads = _bone_heads_world(donor_arm)

    # Anchor pairs for rigid align: try shared name Bone_* tips/hips/shoulders by nearest after crude hip align
    m_anchor = _pick_anchor(list(m_heads), m_heads)
    d_anchor = _pick_anchor(list(d_heads), d_heads)

    # Use several extremities: min/max on each axis from both sets (3+ points)
    def extremity_pts(heads: dict[str, np.ndarray]) -> np.ndarray:
        pts = np.stack(list(heads.values()), axis=0)
        idxs = []
        for axis in range(3):
            idxs.append(int(np.argmin(pts[:, axis])))
            idxs.append(int(np.argmax(pts[:, axis])))
        # unique
        uniq = []
        for i in idxs:
            if i not in uniq:
                uniq.append(i)
        return pts[uniq]

    # First translate donor hip to master hip
    delta = m_heads[m_anchor] - d_heads[d_anchor]
    donor_arm.location = donor_arm.location + Vector((float(delta[0]), float(delta[1]), float(delta[2])))
    bpy.context.view_layer.update()
    d_heads = _bone_heads_world(donor_arm)

    # Kabsch on extremity clouds (same count by pad/truncate)
    src = extremity_pts(d_heads)
    dst = extremity_pts(m_heads)
    n = min(len(src), len(dst))
    if n < 3:
        raise RuntimeError("not enough extremity points for align")
    R, scale, t = _rigid_align(src[:n], dst[:n])
    _apply_object_align(donor_arm, R, scale, t)
    d_heads = _bone_heads_world(donor_arm)

    max_dist = float(opts["maxDist"])
    # Scale threshold with character size
    mpts = np.stack(list(m_heads.values()))
    mspan = float(np.linalg.norm(mpts.max(axis=0) - mpts.min(axis=0)))
    max_dist = max(max_dist, 0.12 * mspan)

    mapping, details = _nearest_map(m_heads, d_heads, max_dist)
    ok_count = sum(1 for d in details if d["ok"])
    if ok_count < max(6, int(0.35 * len(m_heads))):
        raise RuntimeError(
            f"nearest-bone map too sparse: {ok_count}/{len(m_heads)} within maxDist={max_dist:.3f}"
        )

    # Clear any prior action; bake one keyframe
    if master_arm.animation_data:
        master_arm.animation_data_clear()
    master_arm.animation_data_create()
    action = bpy.data.actions.new(name="MeshyFramePose")
    master_arm.animation_data.action = action

    yaw = float(opts.get("rootYawDeg") or 0.0)
    if abs(yaw) > 1e-6:
        master_arm.rotation_mode = "XYZ"
        master_arm.rotation_euler[2] = math.radians(yaw)

    _copy_world_rotations(master_arm, donor_arm, mapping)
    frame = 1
    bpy.context.scene.frame_set(frame)
    for mname in mapping:
        pb = master_arm.pose.bones[mname]
        pb.keyframe_insert(data_path="rotation_quaternion", frame=frame)
    master_arm.keyframe_insert(data_path="rotation_euler", frame=frame)
    bpy.context.scene.frame_start = 1
    bpy.context.scene.frame_end = 1

    out_path = Path(opts["output"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    master_arm.select_set(True)
    master_mesh.select_set(True)
    bpy.context.view_layer.objects.active = master_arm
    bpy.ops.export_scene.gltf(
        filepath=str(out_path),
        export_format="GLB",
        use_selection=True,
        export_animations=True,
        export_force_sampling=True,
        export_nla_strips=False,
        export_apply=False,
    )

    report = {
        "method": "meshy_donor_nearest_bone",
        "masterBoneCount": len(m_heads),
        "donorBoneCount": len(d_heads),
        "mappedCount": ok_count,
        "maxDist": max_dist,
        "anchors": {"master": m_anchor, "donor": d_anchor},
        "align": {"scale": scale, "t": t.tolist()},
        "mappingDetails": details,
        "exportGlb": str(out_path).replace("\\", "/"),
        "proof": "generated artifact validated — nearest-bone retarget smoke; not OE runtime proven",
    }
    if opts.get("mapJson"):
        Path(opts["mapJson"]).write_text(
            json.dumps({"mapping": mapping, "details": details}, indent=2),
            encoding="utf-8",
        )
    if opts.get("report"):
        Path(opts["report"]).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, "mappedCount": ok_count, "output": str(out_path)}, indent=2), flush=True)
    return report


def main() -> int:
    try:
        run(_parse())
        return 0
    except Exception:
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
