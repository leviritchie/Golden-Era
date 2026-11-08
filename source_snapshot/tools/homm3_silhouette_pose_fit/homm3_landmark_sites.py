#!/usr/bin/env python3
"""Resolve sprite-analog landmark sites on a posed Mixamo/Meshy armature+mesh.

Roles may include optional jointSites:

  "jointSites": {
    "Nose": {
      "mode": "farthest_skinned_vert",
      "skinBones": ["Head"],
      "minWeight": 0.35,
      "fromBone": "neck",
      "cacheBone": "Head"
    },
    "WeaponTip": {
      "mode": "farthest_skinned_vert",
      "skinBones": ["RightHand"],
      "minWeight": 0.2,
      "fromBone": "RightHand"
    }
  }

Default without jointSites: bone head of roles.joints[name]
"""
from __future__ import annotations

from mathutils import Vector


def _bone_end_world(arm, bone_name: str, end: str) -> Vector:
    pb = arm.pose.bones.get(bone_name)
    if pb is None:
        raise RuntimeError(f"landmark site: missing bone {bone_name}")
    local = pb.tail if end == "tail" else pb.head
    return arm.matrix_world @ local


def _highest_skinned_vert_world(
    arm,
    mesh,
    *,
    skin_bones: list[str],
    min_weight: float,
    up: Vector,
    posed: bool = False,
) -> tuple[Vector, int]:
    """Pick skinBone-weighted vert with maximum projection onto up (helmet crown / snout top)."""
    import bpy

    group_map = {g.name: g.index for g in mesh.vertex_groups}
    wanted = []
    for bn in skin_bones:
        if bn not in group_map:
            raise RuntimeError(f"landmark tip: missing vertex group {bn}")
        wanted.append(group_map[bn])
    wanted_set = set(wanted)
    up_n = up.normalized()

    if posed:
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        obj_eval = mesh.evaluated_get(depsgraph)
        me = obj_eval.to_mesh()
        mw = obj_eval.matrix_world
        try:
            best_i = -1
            best_h = None
            best_p = None
            for vi, v in enumerate(me.vertices):
                src = mesh.data.vertices[vi]
                w = 0.0
                for g in src.groups:
                    if g.group in wanted_set:
                        w = max(w, float(g.weight))
                if w < min_weight:
                    continue
                p = mw @ v.co
                h = p.dot(up_n)
                if best_h is None or h > best_h:
                    best_h = h
                    best_i = vi
                    best_p = p
        finally:
            obj_eval.to_mesh_clear()
    else:
        mw = mesh.matrix_world
        best_i = -1
        best_h = None
        best_p = None
        for vi, v in enumerate(mesh.data.vertices):
            w = 0.0
            for g in v.groups:
                if g.group in wanted_set:
                    w = max(w, float(g.weight))
            if w < min_weight:
                continue
            p = mw @ v.co
            h = p.dot(up_n)
            if best_h is None or h > best_h:
                best_h = h
                best_i = vi
                best_p = p
    if best_p is None:
        raise RuntimeError(
            f"landmark tip: no skinned verts on {skin_bones} with weight>={min_weight}"
        )
    return Vector(best_p), int(best_i)


def _farthest_skinned_vert_world(
    arm,
    mesh,
    *,
    skin_bones: list[str],
    min_weight: float,
    from_bone: str,
    posed: bool = False,
) -> tuple[Vector, int]:
    """Pick farthest skinBone-weighted vert from from_bone.

    When posed=True, read the armature-deformed mesh via the depsgraph so dual-weighted
    sites (e.g. helmet on Head+neck) match the visible crown — not a rigid bone-local cache.
    """
    import bpy

    group_map = {g.name: g.index for g in mesh.vertex_groups}
    wanted = []
    for bn in skin_bones:
        if bn not in group_map:
            raise RuntimeError(f"landmark tip: missing vertex group {bn}")
        wanted.append(group_map[bn])
    wanted_set = set(wanted)
    origin_pb = arm.pose.bones.get(from_bone)
    if origin_pb is None:
        raise RuntimeError(f"landmark tip: missing from_bone {from_bone}")
    origin = arm.matrix_world @ origin_pb.head

    if posed:
        bpy.context.view_layer.update()
        depsgraph = bpy.context.evaluated_depsgraph_get()
        obj_eval = mesh.evaluated_get(depsgraph)
        me = obj_eval.to_mesh()
        mw = obj_eval.matrix_world
        try:
            best_i = -1
            best_d = -1.0
            best_p = None
            # Weights live on the original mesh; indices match evaluated verts.
            for vi, v in enumerate(me.vertices):
                src = mesh.data.vertices[vi]
                w = 0.0
                for g in src.groups:
                    if g.group in wanted_set:
                        w = max(w, float(g.weight))
                if w < min_weight:
                    continue
                p = mw @ v.co
                d = (p - origin).length
                if d > best_d:
                    best_d = d
                    best_i = vi
                    best_p = p
        finally:
            obj_eval.to_mesh_clear()
    else:
        mw = mesh.matrix_world
        best_i = -1
        best_d = -1.0
        best_p = None
        for vi, v in enumerate(mesh.data.vertices):
            w = 0.0
            for g in v.groups:
                if g.group in wanted_set:
                    w = max(w, float(g.weight))
            if w < min_weight:
                continue
            p = mw @ v.co
            d = (p - origin).length
            if d > best_d:
                best_d = d
                best_i = vi
                best_p = p
    if best_p is None:
        raise RuntimeError(
            f"landmark tip: no skinned verts on {skin_bones} with weight>={min_weight}"
        )
    return Vector(best_p), int(best_i)


def _cache_skinned_site_bind_local(
    arm,
    mesh,
    site: dict,
    *,
    default_skin: list[str],
    default_from: str,
    default_cache: str,
) -> dict:
    skin = list(site.get("skinBones") or default_skin)
    min_w = float(site.get("minWeight", 0.2))
    from_bone = str(site.get("fromBone") or default_from)
    cache_bone = str(site.get("cacheBone") or default_cache or from_bone)
    mode = str(site.get("mode") or "farthest_skinned_vert")
    if mode == "highest_skinned_vert":
        tip_w, vi = _highest_skinned_vert_world(
            arm,
            mesh,
            skin_bones=skin,
            min_weight=min_w,
            up=Vector((0.0, 0.0, 1.0)),
            posed=False,
        )
    else:
        tip_w, vi = _farthest_skinned_vert_world(
            arm, mesh, skin_bones=skin, min_weight=min_w, from_bone=from_bone
        )
    pb = arm.pose.bones.get(cache_bone)
    if pb is None:
        raise RuntimeError(f"landmark cache: missing cacheBone {cache_bone}")
    tip_arm = arm.matrix_world.inverted() @ tip_w
    local = pb.matrix.inverted() @ tip_arm
    origin = arm.matrix_world @ arm.pose.bones[from_bone].head
    return {
        "mode": mode,
        "vertIndex": vi,
        "cacheBone": cache_bone,
        "fromBone": from_bone,
        "skinBones": skin,
        "local": [float(local.x), float(local.y), float(local.z)],
        "bindDist": float((tip_w - origin).length),
    }


def cache_tip_bind_local(arm, mesh, roles: dict) -> dict:
    """Bind-time caches for skinned landmark sites (WeaponTip + Nose crown, etc.)."""
    sites = roles.get("jointSites") or {}
    joints = roles.get("joints") or {}
    out: dict = {}

    if "WeaponTip" in sites or "WeaponTip" in joints:
        tip_site = sites.get("WeaponTip") or {
            "mode": "farthest_skinned_vert",
            "skinBones": ["RightHand"],
            "minWeight": 0.2,
        }
        if tip_site.get("mode") == "bone":
            tip_bone = str(tip_site.get("bone") or joints.get("WeaponTip") or "")
            from_bone = str(tip_site.get("fromBone") or joints.get("RWrist") or "RightHand")
            pb = arm.pose.bones.get(tip_bone)
            origin_pb = arm.pose.bones.get(from_bone)
            if pb is None or origin_pb is None:
                raise RuntimeError(
                    f"WeaponTip bone site missing bone={tip_bone!r} fromBone={from_bone!r}"
                )
            tip_w = arm.matrix_world @ (pb.tail if str(tip_site.get("end") or "head") == "tail" else pb.head)
            origin = arm.matrix_world @ origin_pb.head
            out.update(
                {
                    "vertIndex": None,
                    "handBone": tip_bone,
                    "local": [0.0, 0.0, 0.0],
                    "bindDist": float((tip_w - origin).length),
                    "WeaponTip": {
                        "mode": "bone",
                        "bone": tip_bone,
                        "fromBone": from_bone,
                        "local": [0.0, 0.0, 0.0],
                        "bindDist": float((tip_w - origin).length),
                    },
                }
            )
        elif tip_site.get("mode") == "farthest_skinned_vert":
            cached = _cache_skinned_site_bind_local(
                arm,
                mesh,
                tip_site,
                default_skin=["RightHand"],
                default_from=str(joints.get("RWrist") or "RightHand"),
                default_cache=str(joints.get("RWrist") or "RightHand"),
            )
            out.update(
                {
                    "vertIndex": cached["vertIndex"],
                    "handBone": cached["cacheBone"],
                    "local": cached["local"],
                    "bindDist": cached["bindDist"],
                    "WeaponTip": cached,
                }
            )

    nose_site = sites.get("Nose") or {}
    if "Nose" in joints and nose_site.get("mode") in ("farthest_skinned_vert", "highest_skinned_vert"):
        out["Nose"] = _cache_skinned_site_bind_local(
            arm,
            mesh,
            nose_site,
            default_skin=["Head"],
            default_from=str(joints.get("Neck") or "neck"),
            default_cache=str(joints.get("Nose") or "Head"),
        )

    for jn, site in sites.items():
        if jn in ("WeaponTip", "Nose") or jn in out:
            continue
        mode = str((site or {}).get("mode") or "")
        bone_name = str(joints.get(jn) or jn)
        if mode == "bone":
            tip_bone = str(site.get("bone") or bone_name)
            from_bone = str(site.get("fromBone") or joints.get("RWrist") or bone_name)
            pb = arm.pose.bones.get(tip_bone)
            origin_pb = arm.pose.bones.get(from_bone) or pb
            if pb is None:
                raise RuntimeError(f"{jn} bone site missing bone={tip_bone!r}")
            end = str(site.get("end") or "head")
            tip_w = arm.matrix_world @ (pb.tail if end == "tail" else pb.head)
            origin = arm.matrix_world @ origin_pb.head
            out[jn] = {
                "mode": "bone",
                "bone": tip_bone,
                "fromBone": from_bone,
                "cacheBone": tip_bone,
                "local": [0.0, 0.0, 0.0],
                "bindDist": float((tip_w - origin).length),
            }
        elif mode in ("farthest_skinned_vert", "highest_skinned_vert"):
            out[jn] = _cache_skinned_site_bind_local(
                arm,
                mesh,
                site,
                default_skin=[bone_name],
                default_from=str(site.get("fromBone") or bone_name),
                default_cache=str(site.get("cacheBone") or bone_name),
            )
    return out


def tip_world_from_cache(arm, tip_cache: dict) -> Vector:
    hand = arm.pose.bones[tip_cache["handBone"]]
    local = Vector(tip_cache["local"])
    tip_arm = hand.matrix @ local
    return arm.matrix_world @ tip_arm


def site_world_from_cache(arm, site_cache: dict) -> Vector:
    pb = arm.pose.bones[site_cache["cacheBone"]]
    local = Vector(site_cache["local"])
    return arm.matrix_world @ (pb.matrix @ local)


def landmark_world(
    arm,
    mesh,
    roles: dict,
    joint_name: str,
    *,
    tip_cache: dict | None = None,
) -> Vector:
    """World-space position for a named landmark on the current pose."""
    joints = roles.get("joints") or {}
    sites = roles.get("jointSites") or {}
    site = sites.get(joint_name)

    # Skinned crown/snout sites on posed mesh (not bind cache).
    if (site or {}).get("mode") in ("highest_skinned_vert", "farthest_skinned_vert") and mesh is not None:
        skin = list((site or {}).get("skinBones") or [joints.get(joint_name) or "Head"])
        min_w = float((site or {}).get("minWeight", 0.35))
        mode = str(site.get("mode"))
        if mode == "highest_skinned_vert":
            pt, _vi = _highest_skinned_vert_world(
                arm,
                mesh,
                skin_bones=skin,
                min_weight=min_w,
                up=Vector((0.0, 0.0, 1.0)),
                posed=True,
            )
            return pt
        from_bone = str(site.get("fromBone") or joints.get(joint_name) or "neck")
        pt, _vi = _farthest_skinned_vert_world(
            arm,
            mesh,
            skin_bones=skin,
            min_weight=min_w,
            from_bone=from_bone,
            posed=True,
        )
        return pt

    if tip_cache and joint_name in tip_cache and isinstance(tip_cache[joint_name], dict):
        entry = tip_cache[joint_name]
        if entry.get("mode") == "bone":
            bone = str(entry.get("bone") or joints.get(joint_name) or "")
            end = str((sites.get(joint_name) or {}).get("end") or "head")
            return _bone_end_world(arm, bone, end)
        if entry.get("mode") in ("farthest_skinned_vert", "highest_skinned_vert") and "local" in entry:
            return site_world_from_cache(arm, entry)

    if joint_name == "WeaponTip":
        if tip_cache and "handBone" in tip_cache and "local" in tip_cache:
            return tip_world_from_cache(arm, tip_cache)
        mode = (site or {}).get("mode", "farthest_skinned_vert")
        if mode == "farthest_skinned_vert":
            if mesh is None:
                raise RuntimeError("WeaponTip farthest_skinned_vert needs mesh")
            skin = list((site or {}).get("skinBones") or ["RightHand"])
            min_w = float((site or {}).get("minWeight", 0.2))
            from_bone = str(
                (site or {}).get("fromBone")
                or joints.get("RWrist")
                or "RightHand"
            )
            pt, _vi = _farthest_skinned_vert_world(
                arm, mesh, skin_bones=skin, min_weight=min_w, from_bone=from_bone
            )
            return pt
        # fall through to bone end

    if site is not None and site.get("mode") == "farthest_skinned_vert":
        if mesh is None:
            raise RuntimeError(f"{joint_name} farthest_skinned_vert needs mesh")
        skin = list(site.get("skinBones") or [joints.get(joint_name) or "Head"])
        min_w = float(site.get("minWeight", 0.2))
        from_bone = str(site.get("fromBone") or joints.get("Neck") or "neck")
        pt, _vi = _farthest_skinned_vert_world(
            arm, mesh, skin_bones=skin, min_weight=min_w, from_bone=from_bone
        )
        return pt

    if site is not None and "bone" in site:
        end = str(site.get("end") or "head")
        return _bone_end_world(arm, str(site["bone"]), end)

    bname = joints.get(joint_name)
    if not bname:
        raise RuntimeError(f"roles.joints missing {joint_name}")
    if joint_name == "WeaponTip":
        # Last resort: hand tail (legacy; prefer farthest vert).
        return _bone_end_world(arm, bname, "tail")
    return _bone_end_world(arm, bname, "head")


def bind_depth_anchors(arm, mesh, roles: dict, tip_cache: dict | None = None) -> dict[str, Vector]:
    out = {}
    for jn in (roles.get("joints") or {}):
        out[jn] = landmark_world(arm, mesh, roles, jn, tip_cache=tip_cache)
    return out
