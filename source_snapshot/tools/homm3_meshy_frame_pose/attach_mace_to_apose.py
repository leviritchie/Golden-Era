#!/usr/bin/env python3
"""
Blender: extract mace from combat Meshy46 donor and attach to A-pose rigged body hand.

Args after -- :
  --body PATH           A-pose rigged GLB
  --mace-donor PATH     Combat master with fused mace (Meshy46)
  --output PATH         Assembly GLB
  --roles-out PATH      Bone roles JSON for pose fit
  --report-out PATH     Attach diagnostics JSON
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def _parse() -> argparse.Namespace:
    argv = sys.argv
    if "--" in argv:
        argv = argv[argv.index("--") + 1 :]
    else:
        argv = []
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", type=Path, required=True)
    ap.add_argument("--mace-donor", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--roles-out", type=Path, required=True)
    ap.add_argument("--report-out", type=Path, required=True)
    return ap.parse_args(argv)


def _clear() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _import_glb(path: Path) -> tuple[bpy.types.Object, bpy.types.Object]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    added = [o for o in bpy.data.objects if o not in before]
    arm = next(o for o in added if o.type == "ARMATURE")
    mesh = next(o for o in added if o.type == "MESH")
    return arm, mesh


def _bone_head(arm, name: str) -> Vector:
    return arm.matrix_world @ arm.pose.bones[name].head


def _connected_components(me) -> dict[int, list[int]]:
    n = len(me.vertices)
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for e in me.edges:
        union(e.vertices[0], e.vertices[1])
    comps: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        comps[find(i)].append(i)
    return comps


def _mixamo_roles(bones: dict) -> dict | None:
    """
    Meshy humanoid auto-rig uses Mixamo-style names.
    Character Left = +X = our R/strike side (iso attack read).
    """
    required = (
        "Hips",
        "LeftArm",
        "LeftForeArm",
        "LeftHand",
        "RightArm",
        "RightForeArm",
        "RightHand",
        "LeftUpLeg",
        "LeftLeg",
        "LeftFoot",
        "RightUpLeg",
        "RightLeg",
        "RightFoot",
    )
    if not all(n in bones for n in required):
        return None
    nose = "headfront" if "headfront" in bones else ("Head" if "Head" in bones else "Hips")
    neck = "neck" if "neck" in bones else ("Spine" if "Spine" in bones else "Hips")
    joints = {
        "Nose": nose,
        "Neck": neck,
        "RShoulder": "LeftArm",
        "RElbow": "LeftForeArm",
        "RWrist": "LeftHand",
        "WeaponTip": "LeftHand",
        "LShoulder": "RightArm",
        "LElbow": "RightForeArm",
        "LWrist": "RightHand",
        "MidHip": "Hips",
        "RHip": "LeftUpLeg",
        "RKnee": "LeftLeg",
        "RAnkle": "LeftFoot",
        "LHip": "RightUpLeg",
        "LKnee": "RightLeg",
        "LAnkle": "RightFoot",
    }
    optimize = [
        n
        for n in (
            "Hips",
            "Spine02",
            "Spine01",
            "Spine",
            neck,
            "Head",
            "LeftShoulder",
            "LeftArm",
            "LeftForeArm",
            "LeftHand",
            "RightShoulder",
            "RightArm",
            "RightForeArm",
            "RightHand",
            "LeftUpLeg",
            "LeftLeg",
            "RightUpLeg",
            "RightLeg",
        )
        if n in bones
    ]
    return {
        "rigFamily": "meshy_apose_mixamo_mace_attach",
        "unitSid": "h3_hobgoblin",
        "notes": (
            "Meshy A-pose auto-rig (Mixamo names). Character Left=+X = our R/strike. "
            "Mace prop skinned 100% to LeftHand."
        ),
        "joints": joints,
        "jointWeights": {
            "Nose": 1.0,
            "Neck": 1.0,
            "MidHip": 1.0,
            "RShoulder": 1.6,
            "RElbow": 2.0,
            "RWrist": 2.4,
            "WeaponTip": 3.5,
            "LShoulder": 1.0,
            "LElbow": 1.1,
            "LWrist": 1.3,
            "RHip": 0.8,
            "RKnee": 0.9,
            "LHip": 0.8,
            "LKnee": 0.9,
        },
        "primaryJoints": [
            "Nose",
            "Neck",
            "MidHip",
            "RShoulder",
            "RElbow",
            "RWrist",
            "WeaponTip",
            "LShoulder",
            "LElbow",
            "LWrist",
            "RHip",
            "RKnee",
            "LHip",
            "LKnee",
        ],
        "optimizeBones": optimize,
        "lockedBones": [],
        "rArmChain": ["LeftArm", "LeftForeArm", "LeftHand"],
        "lArmChain": ["RightArm", "RightForeArm", "RightHand"],
        "weaponTip": "LeftHand",
    }


def _guess_roles(arm) -> dict:
    """Heuristic OpenPose→bone map for Meshy UniRig-like hierarchies."""
    bones = {b.name: b for b in arm.data.bones}
    mixamo = _mixamo_roles(bones)
    if mixamo is not None:
        return mixamo
    # Prefer chains hanging from upper torso.
    # MidHip: bone with most children under root-ish
    rootish = [b for b in bones.values() if b.parent is None or b.parent.parent is None]
    mid = None
    for cand in sorted(bones.values(), key=lambda b: len(b.children_recursive), reverse=True):
        if cand.parent is not None:
            mid = cand.name
            break
    if mid is None:
        mid = next(iter(bones))

    def deepest_leaf(start_name: str) -> str:
        b = bones[start_name]
        while b.children:
            # pick child with longest remaining chain
            b = max(b.children, key=lambda c: len(c.children_recursive))
        return b.name

    def chain_from(start: str) -> list[str]:
        out = [start]
        b = bones[start]
        while b.children:
            b = max(b.children, key=lambda c: len(c.children_recursive))
            out.append(b.name)
        return out

    # Find two arm-like chains from a neck/chest bone: bones with lateral tips.
    tips = []
    for b in bones.values():
        if not b.children:
            h = arm.matrix_world @ arm.pose.bones[b.name].head
            tips.append((b.name, h))
    # Sort tips by |x| then height
    tips_sorted = sorted(tips, key=lambda t: (abs(t[1].x), -t[1].z), reverse=True)

    # Shoulder candidates: bones whose world head is high and lateral
    shoulders = []
    for b in bones.values():
        h = arm.matrix_world @ arm.pose.bones[b.name].head
        if h.z > 0.9 and abs(h.x) > 0.15 and b.children:
            shoulders.append((b.name, h))
    shoulders.sort(key=lambda t: t[1].x)  # -X then +X

    # Fallback: use longest two sibling chains under a high bone
    r_shoulder = shoulders[-1][0] if shoulders else tips_sorted[0][0]
    l_shoulder = shoulders[0][0] if len(shoulders) > 1 else tips_sorted[1][0] if len(tips_sorted) > 1 else r_shoulder

    r_chain = chain_from(r_shoulder)
    l_chain = chain_from(l_shoulder)
    # Ensure R is +X side
    rh = arm.matrix_world @ arm.pose.bones[r_chain[0]].head
    lh = arm.matrix_world @ arm.pose.bones[l_chain[0]].head
    if rh.x < lh.x:
        r_chain, l_chain = l_chain, r_chain

    def pick(chain: list[str], idx_from_end: int) -> str:
        if not chain:
            return mid
        i = max(0, len(chain) - 1 - idx_from_end)
        return chain[i]

    # Legs: low lateral bones
    hips = []
    for b in bones.values():
        h = arm.matrix_world @ arm.pose.bones[b.name].head
        if 0.4 < h.z < 0.95 and abs(h.x) > 0.05 and b.children:
            hips.append((b.name, h))
    hips.sort(key=lambda t: t[1].x)
    r_hip = hips[-1][0] if hips else mid
    l_hip = hips[0][0] if len(hips) > 1 else mid
    rh2 = arm.matrix_world @ arm.pose.bones[r_hip].head
    lh2 = arm.matrix_world @ arm.pose.bones[l_hip].head
    if rh2.x < lh2.x:
        r_hip, l_hip = l_hip, r_hip
    r_leg = chain_from(r_hip)
    l_leg = chain_from(l_hip)

    # Head: highest tip
    nose = max(tips, key=lambda t: t[1].z)[0]
    # Neck: parent of nose or mid-high
    neck = bones[nose].parent.name if bones[nose].parent else mid

    weapon_tip = r_chain[-1]
    # Prefer a finger/tip child if chain ends short; else last
    joints = {
        "Nose": nose,
        "Neck": neck,
        "RShoulder": pick(r_chain, len(r_chain) - 1) if False else r_chain[0],
        "RElbow": r_chain[min(1, len(r_chain) - 1)],
        "RWrist": r_chain[min(2, len(r_chain) - 1)],
        "WeaponTip": weapon_tip,
        "LShoulder": l_chain[0],
        "LElbow": l_chain[min(1, len(l_chain) - 1)],
        "LWrist": l_chain[min(2, len(l_chain) - 1)],
        "MidHip": mid,
        "RHip": r_leg[0],
        "RKnee": r_leg[min(1, len(r_leg) - 1)],
        "RAnkle": r_leg[-1],
        "LHip": l_leg[0],
        "LKnee": l_leg[min(1, len(l_leg) - 1)],
        "LAnkle": l_leg[-1],
    }
    # Fix RShoulder assignment
    joints["RShoulder"] = r_chain[0]

    optimize = []
    for key in (
        "MidHip",
        "Neck",
        "Nose",
        "RShoulder",
        "RElbow",
        "RWrist",
        "WeaponTip",
        "LShoulder",
        "LElbow",
        "LWrist",
        "RHip",
        "RKnee",
        "LHip",
        "LKnee",
    ):
        bn = joints[key]
        # include parents along path for a few spine bones
        if bn not in optimize:
            optimize.append(bn)
    # add intermediate arm bones
    for chain in (r_chain, l_chain):
        for bn in chain[:5]:
            if bn not in optimize:
                optimize.append(bn)

    return {
        "rigFamily": "meshy_apose_mace_attach",
        "unitSid": "h3_hobgoblin",
        "notes": "A-pose Meshy auto-rig + separate mace parented/weighted to WeaponTip. R=+X strike side.",
        "joints": joints,
        "jointWeights": {
            "Nose": 1.0,
            "Neck": 1.0,
            "MidHip": 1.0,
            "RShoulder": 1.6,
            "RElbow": 2.0,
            "RWrist": 2.4,
            "WeaponTip": 3.5,
            "LShoulder": 1.0,
            "LElbow": 1.1,
            "LWrist": 1.3,
            "RHip": 0.7,
            "RKnee": 0.8,
            "LHip": 0.7,
            "LKnee": 0.8,
        },
        "primaryJoints": [
            "Nose",
            "Neck",
            "MidHip",
            "RShoulder",
            "RElbow",
            "RWrist",
            "WeaponTip",
            "LShoulder",
            "LElbow",
            "LWrist",
            "RHip",
            "RKnee",
            "LHip",
            "LKnee",
        ],
        "optimizeBones": optimize,
        "lockedBones": [],
        "rArmChain": r_chain,
        "lArmChain": l_chain,
    }


def _extract_mace_object(donor_arm, donor_mesh, tip_bone: str = "Bone_033") -> bpy.types.Object:
    """Duplicate tip-near islands from donor into a new mesh object."""
    tip = _bone_head(donor_arm, tip_bone) if tip_bone in donor_arm.pose.bones else None
    if tip is None:
        # fallback: rightmost high-ish verts centroid as tip guess
        tip = Vector((0.4, 0.0, 0.9))
        for b in donor_arm.pose.bones:
            h = _bone_head(donor_arm, b.name)
            if h.x > tip.x and h.z > 0.5:
                tip = h

    comps = _connected_components(donor_mesh.data)
    keep_idxs: set[int] = set()
    for idxs in comps.values():
        c = Vector((0, 0, 0))
        for i in idxs:
            c += donor_mesh.matrix_world @ donor_mesh.data.vertices[i].co
        c /= float(len(idxs))
        if (c - tip).length < 0.32:
            keep_idxs.update(idxs)
    if len(keep_idxs) < 50:
        # broaden
        for idxs in comps.values():
            c = Vector((0, 0, 0))
            for i in idxs:
                c += donor_mesh.matrix_world @ donor_mesh.data.vertices[i].co
            c /= float(len(idxs))
            if (c - tip).length < 0.45:
                keep_idxs.update(idxs)
    if not keep_idxs:
        raise RuntimeError("mace extract found no tip-near islands")

    # Select and separate
    bpy.ops.object.select_all(action="DESELECT")
    donor_mesh.select_set(True)
    bpy.context.view_layer.objects.active = donor_mesh
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    for i, v in enumerate(donor_mesh.data.vertices):
        v.select = i in keep_idxs
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.duplicate()
    bpy.ops.mesh.separate(type="SELECTED")
    bpy.ops.object.mode_set(mode="OBJECT")
    # New object is the separated selection; identify by name/last selected
    mace = None
    for o in bpy.context.selected_objects:
        if o.type == "MESH" and o != donor_mesh:
            mace = o
            break
    if mace is None:
        # find newest mesh not donor
        meshes = [o for o in bpy.data.objects if o.type == "MESH" and o != donor_mesh]
        mace = meshes[-1]
    mace.name = "MaceProp"
    # Clear armature parenting/weights from donor skin
    mace.parent = None
    while mace.vertex_groups:
        mace.vertex_groups.remove(mace.vertex_groups[0])
    for mod in list(mace.modifiers):
        if mod.type == "ARMATURE":
            mace.modifiers.remove(mod)
    return mace


def _mace_grip_and_tip_world(mace, *, under_head_frac: float = 0.32) -> tuple[Vector, Vector, Vector, dict]:
    """
    Tip = denser/fatter spiked head end; pommel = thinner shaft end.
    Grip contact = a short way under the head toward the pommel (not the centroid,
    and not the pommel — HoMM3 holds just below the spiked head).
    """
    bpy.context.view_layer.update()
    pts = [mace.matrix_world @ v.co for v in mace.data.vertices]
    if len(pts) < 20:
        raise RuntimeError(f"mace too few verts for grip/tip: {len(pts)}")
    # Farthest-pair axis (O(n^2) ok for extracted prop).
    best_d = -1.0
    a = b = pts[0]
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            d = (pts[i] - pts[j]).length
            if d > best_d:
                best_d = d
                a, b = pts[i], pts[j]
    if best_d < 0.05:
        raise RuntimeError(f"mace axis too short: {best_d:.4f}")
    axis = (b - a).normalized()

    def end_radius(end: Vector) -> float:
        dists = []
        for p in pts:
            if (p - end).length > best_d * 0.28:
                continue
            t = (p - a).dot(axis)
            closest = a + axis * t
            dists.append((p - closest).length)
        if len(dists) < 5:
            return 0.0
        return float(sum(dists) / len(dists))

    ra, rb = end_radius(a), end_radius(b)
    if abs(ra - rb) < 1e-4:
        raise RuntimeError(f"mace ends not distinguishable by radius ({ra:.4f} vs {rb:.4f})")
    if ra > rb:
        tip, pommel = a, b
        tip_r, pommel_r = ra, rb
    else:
        tip, pommel = b, a
        tip_r, pommel_r = rb, ra
    frac = float(under_head_frac)
    if not (0.05 <= frac <= 0.45):
        raise RuntimeError(f"under_head_frac out of range: {frac}")
    grip = tip.lerp(pommel, frac)
    meta = {
        "axisLength": round(best_d, 4),
        "tipRadius": round(tip_r, 4),
        "pommelRadius": round(pommel_r, 4),
        "underHeadFrac": frac,
        "tip": [round(float(x), 4) for x in tip],
        "pommel": [round(float(x), 4) for x in pommel],
        "grip": [round(float(x), 4) for x in grip],
    }
    return grip, tip, pommel, meta


def _attach_mace(body_arm, body_mesh, mace, hand_bone: str) -> dict:
    """
    Place mace so the under-head grip sits at the hand bone head, then skin 100%
    to that bone. Do NOT place the mesh centroid on the hand — that puts the
    spiked head in the palm.
    """
    hand_pb = body_arm.pose.bones[hand_bone]
    hand_world = body_arm.matrix_world @ hand_pb.head
    grip, tip, pommel, meta = _mace_grip_and_tip_world(mace)
    delta = hand_world - grip
    mace.location = mace.location + delta
    bpy.context.view_layer.update()
    # Re-measure after translate for report.
    grip2, tip2, pommel2, meta2 = _mace_grip_and_tip_world(mace)
    meta2["handBone"] = hand_bone
    meta2["handWorld"] = [round(float(x), 4) for x in hand_world]
    meta2["gripToHand"] = round(float((grip2 - hand_world).length), 5)
    if meta2["gripToHand"] > 0.02:
        raise RuntimeError(f"grip did not land on hand: dist={meta2['gripToHand']}")
    meta2["tipToHand"] = round(float((tip2 - hand_world).length), 4)
    meta2["pommelToHand"] = round(float((pommel2 - hand_world).length), 4)
    if meta2["tipToHand"] < meta2["gripToHand"] + 0.01:
        raise RuntimeError("tip closer to hand than grip after attach — wrong end chosen")

    # Tip offset in hand rotation frame — persist for fitters (GLB round-trip often
    # leaves MaceProp unevaluated / tiny-bind, so measuring after re-import is unsafe).
    _loc, rot, _scale = (body_arm.matrix_world @ hand_pb.matrix).decompose()
    tip_local = rot.to_matrix().inverted() @ (tip2 - hand_world)
    meta2["tipLocal"] = [round(float(x), 6) for x in tip_local]

    # Parent to armature, weight all verts to hand bone
    mace.parent = body_arm
    mace.parent_type = "OBJECT"
    vg = mace.vertex_groups.new(name=hand_bone)
    vg.add([v.index for v in mace.data.vertices], 1.0, "REPLACE")
    # Join into body so glTF round-trip keeps one skinned mesh (separate MaceProp
    # often imports with tiny bind scale and fails to evaluate under Armature).
    bpy.ops.object.select_all(action="DESELECT")
    body_mesh.select_set(True)
    mace.select_set(True)
    bpy.context.view_layer.objects.active = body_mesh
    bpy.ops.object.join()
    body_mesh = bpy.context.view_layer.objects.active
    body_mesh.name = "HobgoblinMaceBody"
    # Ensure armature modifier on joined mesh
    if not any(mod.type == "ARMATURE" for mod in body_mesh.modifiers):
        mod = body_mesh.modifiers.new(name="Armature", type="ARMATURE")
        mod.object = body_arm
    else:
        for mod in body_mesh.modifiers:
            if mod.type == "ARMATURE":
                mod.object = body_arm
    meta2["joinedIntoBody"] = True
    meta2["bodyMeshName"] = body_mesh.name
    return meta2, body_mesh


def main() -> int:
    args = _parse()
    _clear()
    body_arm, body_mesh = _import_glb(args.body)
    # Import donor in same scene
    donor_arm, donor_mesh = _import_glb(args.mace_donor)

    roles = _guess_roles(body_arm)
    # Strike hand owns the prop; WeaponTip joint name still maps to this bone in roles
    # for legacy configs, but attach must use the grip (not centroid/tip).
    hand_bone = roles["joints"]["RWrist"]

    # Extract mace using donor Bone_033 if present else donor tip heuristic
    donor_tip = "Bone_033" if "Bone_033" in donor_arm.pose.bones else hand_bone
    mace = _extract_mace_object(donor_arm, donor_mesh, tip_bone=donor_tip)

    # Remove donor from scene (keep mace)
    bpy.data.objects.remove(donor_mesh, do_unlink=True)
    bpy.data.objects.remove(donor_arm, do_unlink=True)

    attach_meta, body_mesh = _attach_mace(body_arm, body_mesh, mace, hand_bone)

    # Export body mesh + armature (mace already joined)
    bpy.ops.object.select_all(action="DESELECT")
    body_arm.select_set(True)
    body_mesh.select_set(True)
    bpy.context.view_layer.objects.active = body_arm
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(
        filepath=str(args.output),
        export_format="GLB",
        use_selection=True,
        export_animations=False,
        export_skins=True,
        export_apply=False,
    )

    roles["masterGlb"] = str(args.output).replace("\\", "/")
    roles["notes"] = (
        "Meshy A-pose auto-rig (Mixamo names). Character Left=+X = our R/strike. "
        "Mace prop skinned 100% to LeftHand at under-head grip (not centroid)."
    )
    roles["weaponTipAim"] = {
        "handBone": hand_bone,
        "weight": 3.0,
        "tipLocal": attach_meta["tipLocal"],
    }
    args.roles_out.parent.mkdir(parents=True, exist_ok=True)
    args.roles_out.write_text(json.dumps(roles, indent=2) + "\n", encoding="utf-8")

    report = {
        "ok": True,
        "body": str(args.body).replace("\\", "/"),
        "maceDonor": str(args.mace_donor).replace("\\", "/"),
        "output": str(args.output).replace("\\", "/"),
        "handBone": hand_bone,
        "attach": attach_meta,
        "maceVerts": len(mace.data.vertices),
        "bodyBones": len(body_arm.data.bones),
        "rArmChain": roles.get("rArmChain"),
        "lArmChain": roles.get("lArmChain"),
        "proof": "generated artifact validated — mace grip-attached to A-pose LeftHand (not centroid)",
    }
    args.report_out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
