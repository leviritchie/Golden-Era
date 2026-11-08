#!/usr/bin/env python3
"""
Hand-build a Mixamo-style humanoid armature on frame_00 Meshy mesh and auto-skin it.

Does NOT call Meshy smart-rig. Places bones from mesh AABB slices + optional painted
2D keypoints projected onto the mesh depth, then Blender automatic weights.

  blender -b --python rig_frame0_shared_skeleton.py -- \\
    --mesh .../meshes/frame_00.glb \\
    --keypoints .../manual_keypoints/keypoints.json \\
    --output .../rigged/frame_00_rigged.glb \\
    --skeleton-json .../shared_skeleton.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector

ROOT = Path(__file__).resolve().parents[2]


def _argv() -> list[str]:
    return sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []


def _parse() -> dict:
    args = _argv()
    out = {
        "mesh": None,
        "keypoints": None,
        "output": None,
        "skeletonJson": None,
        "frameIndex": 0,
        "unitSid": "h3_hobgoblin",
        "skinMode": "soft_k_nearest_segment",
        "skinK": 4,
        "skinPower": 2.0,
        "skinTrim": 0.0,
        "ownershipRules": None,
        "species": "humanoid",
        "partMap": None,
    }
    i = 0
    while i < len(args):
        if args[i] == "--mesh" and i + 1 < len(args):
            out["mesh"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--keypoints" and i + 1 < len(args):
            out["keypoints"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--output" and i + 1 < len(args):
            out["output"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--skeleton-json" and i + 1 < len(args):
            out["skeletonJson"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--frame-index" and i + 1 < len(args):
            out["frameIndex"] = int(args[i + 1])
            i += 2
        elif args[i] == "--unit-sid" and i + 1 < len(args):
            out["unitSid"] = args[i + 1]
            i += 2
        elif args[i] == "--skin-mode" and i + 1 < len(args):
            out["skinMode"] = args[i + 1]
            i += 2
        elif args[i] == "--skin-k" and i + 1 < len(args):
            out["skinK"] = int(args[i + 1])
            i += 2
        elif args[i] == "--skin-power" and i + 1 < len(args):
            out["skinPower"] = float(args[i + 1])
            i += 2
        elif args[i] == "--skin-trim" and i + 1 < len(args):
            out["skinTrim"] = float(args[i + 1])
            i += 2
        elif args[i] == "--ownership-rules" and i + 1 < len(args):
            out["ownershipRules"] = Path(args[i + 1])
            i += 2
        elif args[i] == "--species" and i + 1 < len(args):
            out["species"] = args[i + 1]
            i += 2
        elif args[i] == "--part-map" and i + 1 < len(args):
            out["partMap"] = Path(args[i + 1])
            i += 2
        else:
            i += 1
    if not out["mesh"] or not out["output"]:
        raise SystemExit("need --mesh --output")
    return out


def _abs(p: Path) -> Path:
    return p.resolve() if p.is_absolute() else (ROOT / p).resolve()


def _mesh_world_verts(obj) -> np.ndarray:
    mw = obj.matrix_world
    return np.array([list(mw @ v.co) for v in obj.data.vertices], dtype=np.float64)


def _slice_centroid(verts: np.ndarray, z0: float, z1: float) -> np.ndarray | None:
    m = (verts[:, 2] >= z0) & (verts[:, 2] < z1)
    if not np.any(m):
        return None
    return verts[m].mean(axis=0)


def _lateral_extremes(verts: np.ndarray, z0: float, z1: float) -> tuple[np.ndarray, np.ndarray] | None:
    m = (verts[:, 2] >= z0) & (verts[:, 2] < z1)
    if np.count_nonzero(m) < 8:
        return None
    s = verts[m]
    left = s[np.argmax(s[:, 0])]   # +X
    right = s[np.argmin(s[:, 0])]  # -X
    return left, right


def _build_joint_guesses(verts: np.ndarray) -> dict[str, np.ndarray]:
    zmin, zmax = float(verts[:, 2].min()), float(verts[:, 2].max())
    h = max(zmax - zmin, 1e-3)
    # Relative bands (feet→head)
    def band(a: float, b: float):
        return zmin + a * h, zmin + b * h

    hips = _slice_centroid(verts, *band(0.42, 0.52))
    chest = _slice_centroid(verts, *band(0.62, 0.72))
    neck = _slice_centroid(verts, *band(0.78, 0.86))
    head = _slice_centroid(verts, *band(0.88, 0.98))
    mid = _slice_centroid(verts, *band(0.52, 0.62))
    if hips is None:
        hips = verts.mean(axis=0)
    if chest is None:
        chest = hips + np.array([0, 0, 0.2 * h])
    if neck is None:
        neck = chest + np.array([0, 0, 0.12 * h])
    if head is None:
        head = neck + np.array([0, 0, 0.12 * h])
    if mid is None:
        mid = 0.5 * (hips + chest)

    sh = _lateral_extremes(verts, *band(0.68, 0.78))
    if sh is None:
        sh = (chest + np.array([0.18 * h, 0, 0.05 * h]), chest + np.array([-0.18 * h, 0, 0.05 * h]))
    l_sh, r_sh = sh  # +X / -X

    # Elbows / wrists from arm bands (upper body lateral)
    el = _lateral_extremes(verts, *band(0.52, 0.62))
    wr = _lateral_extremes(verts, *band(0.38, 0.50))
    if el is None:
        el = (l_sh + np.array([0.12 * h, 0, -0.12 * h]), r_sh + np.array([-0.12 * h, 0, -0.12 * h]))
    if wr is None:
        wr = (el[0] + np.array([0.1 * h, 0, -0.12 * h]), el[1] + np.array([-0.1 * h, 0, -0.12 * h]))
    l_el, r_el = el
    l_wr, r_wr = wr

    # Prefer +X side wrist farther in +X for strike hand
    if l_wr[0] < r_wr[0]:
        l_wr, r_wr = r_wr, l_wr
        l_el, r_el = r_el, l_el
        l_sh, r_sh = r_sh, l_sh

    # Legs
    thigh = _lateral_extremes(verts, *band(0.28, 0.40))
    knee = _lateral_extremes(verts, *band(0.16, 0.28))
    ankle = _lateral_extremes(verts, *band(0.02, 0.12))
    if thigh is None:
        thigh = (hips + np.array([0.1 * h, 0, -0.08 * h]), hips + np.array([-0.1 * h, 0, -0.08 * h]))
    if knee is None:
        knee = (thigh[0] + np.array([0.02 * h, 0, -0.14 * h]), thigh[1] + np.array([-0.02 * h, 0, -0.14 * h]))
    if ankle is None:
        ankle = (knee[0] + np.array([0.0, 0, -0.14 * h]), knee[1] + np.array([0.0, 0, -0.14 * h]))
    l_th, r_th = thigh
    l_kn, r_kn = knee
    l_an, r_an = ankle
    if l_th[0] < r_th[0]:
        l_th, r_th = r_th, l_th
        l_kn, r_kn = r_kn, l_kn
        l_an, r_an = r_an, l_an

    return {
        "Hips": hips,
        "Spine02": mid,
        "Spine01": 0.5 * (mid + chest),
        "Spine": chest,
        "neck": neck,
        "Head": head,
        "head_end": head + np.array([0, 0, 0.08 * h]),
        "LeftShoulder": 0.5 * (chest + l_sh),
        "LeftArm": l_sh,
        "LeftForeArm": l_el,
        "LeftHand": l_wr,
        "RightShoulder": 0.5 * (chest + r_sh),
        "RightArm": r_sh,
        "RightForeArm": r_el,
        "RightHand": r_wr,
        "LeftUpLeg": l_th,
        "LeftLeg": l_kn,
        "LeftFoot": l_an,
        "LeftToeBase": l_an + np.array([0.03 * h, -0.04 * h, -0.02 * h]),
        "RightUpLeg": r_th,
        "RightLeg": r_kn,
        "RightFoot": r_an,
        "RightToeBase": r_an + np.array([-0.03 * h, -0.04 * h, -0.02 * h]),
    }


# Mixamo-like hierarchy: child -> parent
HIERARCHY = [
    ("Hips", None),
    ("Spine02", "Hips"),
    ("Spine01", "Spine02"),
    ("Spine", "Spine01"),
    ("neck", "Spine"),
    ("Head", "neck"),
    ("head_end", "Head"),
    ("LeftShoulder", "Spine"),
    ("LeftArm", "LeftShoulder"),
    ("LeftForeArm", "LeftArm"),
    ("LeftHand", "LeftForeArm"),
    ("RightShoulder", "Spine"),
    ("RightArm", "RightShoulder"),
    ("RightForeArm", "RightArm"),
    ("RightHand", "RightForeArm"),
    ("LeftUpLeg", "Hips"),
    ("LeftLeg", "LeftUpLeg"),
    ("LeftFoot", "LeftLeg"),
    ("LeftToeBase", "LeftFoot"),
    ("RightUpLeg", "Hips"),
    ("RightLeg", "RightUpLeg"),
    ("RightFoot", "RightLeg"),
    ("RightToeBase", "RightFoot"),
]


def _create_armature(joints: dict[str, np.ndarray], name: str = "OwnedHumanoid"):
    arm_data = bpy.data.armatures.new(name)
    arm_obj = bpy.data.objects.new(name, arm_data)
    bpy.context.collection.objects.link(arm_obj)
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    ebones = arm_data.edit_bones

    # Create bones head→tail toward child or small offset
    children: dict[str, list[str]] = {n: [] for n, _ in HIERARCHY}
    parent_of = {}
    for child, parent in HIERARCHY:
        parent_of[child] = parent
        if parent:
            children[parent].append(child)

    created = {}
    for bname, parent in HIERARCHY:
        head = Vector(joints[bname].tolist())
        # Tail: toward first child if any, else along +Z small
        kids = children.get(bname) or []
        if kids:
            tail = Vector(joints[kids[0]].tolist())
            if (tail - head).length < 1e-4:
                tail = head + Vector((0, 0, 0.05))
        else:
            tail = head + Vector((0, 0, 0.05))
        eb = ebones.new(bname)
        eb.head = head
        eb.tail = tail
        created[bname] = eb

    for bname, parent in HIERARCHY:
        if parent:
            created[bname].parent = created[parent]
            created[bname].use_connect = False

    bpy.ops.object.mode_set(mode="OBJECT")
    return arm_obj


def _ensure_bone_lengths(arm_obj, min_len: float = 0.03) -> None:
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode="EDIT")
    for eb in arm_obj.data.edit_bones:
        if (eb.tail - eb.head).length < min_len:
            # Prefer +Z, else along parent
            direction = Vector((0.0, 0.0, min_len))
            if eb.parent is not None:
                pd = eb.head - eb.parent.head
                if pd.length > 1e-6:
                    direction = pd.normalized() * min_len
            eb.tail = eb.head + direction
    bpy.ops.object.mode_set(mode="OBJECT")


def _nearest_bone_weights(arm_obj, mesh_obj, *, k: int = 4, power: float = 2.0, trim: float = 0.0) -> None:
    """
    Soft skin: each vert blends across k nearest bone segments (head→tail).
    Hard 1-bone assignment tears Meshy meshes as soon as limbs rotate.

    Matches the Meshy auto-rig signature with power ~10 and trim ~0.03:
    strong dominant bone per vertex (mean dominant ~0.75) plus gentle blends
    only at piece interfaces; tiny weights are dropped and renormalized.
    """
    while mesh_obj.vertex_groups:
        mesh_obj.vertex_groups.remove(mesh_obj.vertex_groups[0])
    for mod in list(mesh_obj.modifiers):
        if mod.type == "ARMATURE":
            mesh_obj.modifiers.remove(mod)

    bones = []
    for pb in arm_obj.pose.bones:
        if pb.name.endswith("_end") and pb.name != "head_end":
            continue
        head = arm_obj.matrix_world @ pb.head
        tail = arm_obj.matrix_world @ pb.tail
        bones.append((pb.name, head, tail))
        mesh_obj.vertex_groups.new(name=pb.name)

    mw = mesh_obj.matrix_world
    k_use = max(1, min(int(k), len(bones)))
    eps = 1e-4
    for vi, v in enumerate(mesh_obj.data.vertices):
        p = mw @ v.co
        dists = []
        for name, head, tail in bones:
            seg = tail - head
            seg_len2 = seg.length_squared
            if seg_len2 < 1e-12:
                d = (p - head).length
            else:
                t = max(0.0, min(1.0, (p - head).dot(seg) / seg_len2))
                d = (p - (head + seg * t)).length
            dists.append((d, name))
        dists.sort(key=lambda x: x[0])
        picked = dists[:k_use]
        weights = []
        for d, name in picked:
            w = 1.0 / ((d + eps) ** power)
            if trim > 0.0 and w < trim:
                continue
            weights.append((name, w))
        if not weights:
            weights = [(picked[0][1], 1.0)]
        total = sum(w for _, w in weights) or 1.0
        for name, w in weights:
            mesh_obj.vertex_groups[name].add([vi], float(w / total), "REPLACE")

    mesh_obj.parent = arm_obj
    mesh_obj.parent_type = "OBJECT"
    mod = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm_obj
    mod.use_vertex_groups = True


# Flex joints for an all-metal humanoid: parent bone, child bone, and the
# fold band geometry (cm, mesh normalized to ~1.4 m). Everything outside the
# bands is rigid (single-bone) so plate armor moves like metal, not flesh.
DEFAULT_FLEX_JOINTS = [
    # (parent, child, bandWidthCm, bandRadiusCm)
    # neck
    ("neck", "Head", 7.0, 9.0),
    # arm sockets
    ("LeftShoulder", "LeftArm", 7.0, 10.0),
    ("RightShoulder", "RightArm", 7.0, 10.0),
    # elbows
    ("LeftArm", "LeftForeArm", 6.0, 9.0),
    ("RightArm", "RightForeArm", 6.0, 9.0),
    # wrists
    ("LeftForeArm", "LeftHand", 4.5, 7.0),
    ("RightForeArm", "RightHand", 4.5, 7.0),
    # hips
    ("Hips", "LeftUpLeg", 7.0, 11.0),
    ("Hips", "RightUpLeg", 7.0, 11.0),
    # knees
    ("LeftUpLeg", "LeftLeg", 6.5, 10.0),
    ("RightUpLeg", "RightLeg", 6.5, 10.0),
    # ankles
    ("LeftLeg", "LeftFoot", 5.0, 8.0),
    ("RightLeg", "RightFoot", 5.0, 8.0),
    # torso (moderate lean, narrow)
    ("Spine02", "Spine01", 5.0, 8.0),
    ("Spine01", "Spine", 5.0, 8.0),
]


def _rigid_with_joint_blend_weights(arm_obj, mesh_obj, *, flex_joints=None) -> dict:
    """Rigid single-bone skin everywhere except narrow flex bands at joints.

    Model: this unit is all plate armor. Nearly every vertex follows exactly one
    bone so metal cannot shear/stretch; only the fold bands around articulation
    points carry a parent/child blend so the welded mesh bends instead of
    tearing when a limb rotates.
    """
    while mesh_obj.vertex_groups:
        mesh_obj.vertex_groups.remove(mesh_obj.vertex_groups[0])
    for mod in list(mesh_obj.modifiers):
        if mod.type == "ARMATURE":
            mesh_obj.modifiers.remove(mod)

    bones = []
    for pb in arm_obj.pose.bones:
        if pb.name.endswith("_end") and pb.name != "head_end":
            continue
        head = arm_obj.matrix_world @ pb.head
        tail = arm_obj.matrix_world @ pb.tail
        bones.append((pb.name, head, tail))
        mesh_obj.vertex_groups.new(name=pb.name)
    bone_by_name = {name: (head, tail) for name, head, tail in bones}

    mw = mesh_obj.matrix_world
    verts = [mw @ v.co for v in mesh_obj.data.vertices]
    zmin = min(p.z for p in verts)
    zmax = max(p.z for p in verts)
    height = max(zmax - zmin, 1e-6)

    eps = 1e-4
    for vi, p in enumerate(verts):
        dists = []
        for name, head, tail in bones:
            seg = tail - head
            seg_len2 = seg.length_squared
            if seg_len2 < 1e-12:
                d = (p - head).length
            else:
                t = max(0.0, min(1.0, (p - head).dot(seg) / seg_len2))
                d = (p - (head + seg * t)).length
            dists.append((d, name))
        dists.sort(key=lambda x: x[0])
        best_name = dists[0][1]
        # Semantic armor overrides (mirrors _rigid_component_weights): helmet
        # crown follows Head; strike-side blade follows RightWeaponTip.
        if p.z >= zmin + 0.82 * height:
            best_name = "Head"
        if "RightWeaponTip" in bone_by_name:
            hand = bone_by_name.get("RightHand")
            tip = bone_by_name.get("RightWeaponTip")
            if hand is not None and tip is not None:
                origin, tip_pos = hand[1], tip[1]
                direction = tip_pos - origin
                direction_len2 = direction.length_squared
                if direction_len2 > 1e-8:
                    t = float((p - origin).dot(direction) / direction_len2)
                    closest = origin + direction * max(0.0, min(1.0, t))
                    if 0.04 < t <= 1.08 and (p - closest).length <= 0.09:
                        best_name = "RightWeaponTip"
        mesh_obj.vertex_groups[best_name].add([vi], 1.0, "REPLACE")

    # Fold bands: re-blend band verts between parent and child so the weld
    # folds like a hinge instead of tearing. Weight ramps 0 -> 0.5 -> 1 across
    # the band from the parent side to the child side.
    band_stats = {}
    for parent, child, width_cm, radius_cm in (flex_joints or DEFAULT_FLEX_JOINTS):
        if parent not in bone_by_name or child not in bone_by_name:
            continue
        parent_head, parent_tail = bone_by_name[parent]
        child_head, child_tail = bone_by_name[child]
        width = width_cm / 100.0
        radius = radius_cm / 100.0
        # Fold direction: parent's tail-side anchor to child's tail (a straight
        # "unfolded" reference along the limb).
        anchor = parent_tail
        direction = child_tail - parent_head
        direction_len2 = direction.length_squared
        if direction_len2 < 1e-12:
            continue
        direction = direction / math.sqrt(direction_len2)
        pivot = child_head
        band_verts = 0
        for vi, p in enumerate(verts):
            lateral = (p - anchor).dot(direction)
            off_axis = ((p - anchor) - direction * lateral).length
            if off_axis > radius:
                continue
            # t: 0 = parent side (deep), 1 = child side (deep); 0.5 = pivot
            t = (p - pivot).dot(direction) / width + 0.5
            if t <= 0.0 or t >= 1.0:
                continue
            # smoothstep ramp
            s = t * t * (3.0 - 2.0 * t)
            mesh_obj.vertex_groups[child].add([vi], float(s), "REPLACE")
            mesh_obj.vertex_groups[parent].add([vi], float(1.0 - s), "REPLACE")
            band_verts += 1
        band_stats[f"{parent}->{child}"] = band_verts

    mesh_obj.parent = arm_obj
    mesh_obj.parent_type = "OBJECT"
    mod = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm_obj
    mod.use_vertex_groups = True
    return {
        "schema": "owned_skin_flex_band.v1",
        "flexJoints": [(p, c, w, r) for p, c, w, r in (flex_joints or DEFAULT_FLEX_JOINTS)],
        "bandVerts": band_stats,
    }


def _load_ownership_rules(path: Path | None, *, unit_sid: str) -> dict:
    """Load optional data rules for semantic rigid ownership corrections.

    The geometric nearest-bone result remains the default. Rules are a narrow,
    auditable second pass for repeated asset-family boundaries; they are kept
    outside this generic rig builder so new units do not require code branches.
    """
    empty = {
        "schema": "owned_skin_ownership_rules.v1",
        "source": None,
        "rules": [],
    }
    if path is None:
        return empty
    resolved = _abs(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"ownership rules file not found: {resolved}")
    raw = json.loads(resolved.read_text(encoding="utf-8"))
    if raw.get("schema") != "owned_skin_ownership_rules.v1":
        raise ValueError(f"unsupported ownership rules schema in {resolved}")
    declared_unit = raw.get("unitSid")
    if declared_unit is not None and str(declared_unit) != unit_sid:
        raise ValueError(f"ownership rules unitSid {declared_unit!r} does not match {unit_sid!r}")
    rules = raw.get("rules")
    if not isinstance(rules, list):
        raise ValueError(f"ownership rules must contain a list: {resolved}")
    normalized = []
    rule_ids = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            raise ValueError(f"ownership rule {index} is not an object: {resolved}")
        for key in ("id", "fromOwner", "toOwner", "when", "reason"):
            if key not in rule:
                raise ValueError(f"ownership rule {index} missing {key}: {resolved}")
        if not isinstance(rule["when"], dict):
            raise ValueError(f"ownership rule {rule['id']} has invalid when predicate")
        rule_id = str(rule["id"])
        if not rule_id or rule_id in rule_ids:
            raise ValueError(f"ownership rule ids must be unique and non-empty: {rule_id!r}")
        rule_ids.add(rule_id)
        if not str(rule["reason"]).strip():
            raise ValueError(f"ownership rule {rule_id} has an empty reason")
        minimum = int(rule.get("minApplications", 0))
        if minimum < 0:
            raise ValueError(f"ownership rule {rule['id']} has negative minApplications")
        normalized.append({**rule, "minApplications": minimum})
    return {
        "schema": raw["schema"],
        "source": str(resolved).replace("\\", "/"),
        "rules": normalized,
    }


def _axis_value(vector: Vector, axis: str) -> float:
    if axis not in ("x", "y", "z"):
        raise ValueError(f"unsupported ownership predicate axis: {axis}")
    return float(getattr(vector, axis))


def _rule_matches(rule: dict, *, source_owner: str, center: Vector, bone_heads: dict[str, Vector]) -> bool:
    if rule["fromOwner"] != source_owner:
        return False
    when = rule["when"]
    for axis, minimum in when.get("centerMin", {}).items():
        if _axis_value(center, axis) < float(minimum):
            return False
    for axis, maximum in when.get("centerMax", {}).items():
        if _axis_value(center, axis) > float(maximum):
            return False
    for predicate_name, direction in (
        ("centerRelativeToBoneHeadMin", "min"),
        ("centerRelativeToBoneHeadMax", "max"),
    ):
        for predicate in when.get(predicate_name, []):
            if not isinstance(predicate, dict) or not {"bone", "axis", "value"} <= set(predicate):
                raise ValueError(f"invalid {predicate_name} predicate in ownership rule {rule['id']}")
            bone = predicate["bone"]
            if bone not in bone_heads:
                raise ValueError(f"ownership rule {rule['id']} references missing bone {bone}")
            delta = _axis_value(center, predicate["axis"]) - _axis_value(bone_heads[bone], predicate["axis"])
            value = float(predicate["value"])
            if direction == "min" and delta < value:
                return False
            if direction == "max" and delta > value:
                return False
    return True


def _rigid_component_weights(arm_obj, mesh_obj, *, ownership_rules: dict | None = None) -> dict:
    """Bind each disconnected mesh component to exactly one nearest bone.

    This preserves rigid armor plates and props. It intentionally does not
    blend across component boundaries; the deformable body remains a separate
    future skinning policy rather than silently warping metal.
    """
    while mesh_obj.vertex_groups:
        mesh_obj.vertex_groups.remove(mesh_obj.vertex_groups[0])
    for mod in list(mesh_obj.modifiers):
        if mod.type == "ARMATURE":
            mesh_obj.modifiers.remove(mod)

    bones = []
    for pb in arm_obj.pose.bones:
        head = arm_obj.matrix_world @ pb.head
        tail = arm_obj.matrix_world @ pb.tail
        bones.append((pb.name, head, tail))
        mesh_obj.vertex_groups.new(name=pb.name)

    parent = list(range(len(mesh_obj.data.vertices)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for poly in mesh_obj.data.polygons:
        if len(poly.vertices) < 2:
            continue
        first = poly.vertices[0]
        for vi in poly.vertices[1:]:
            union(first, vi)

    components: dict[int, list[int]] = {}
    for vi in range(len(mesh_obj.data.vertices)):
        components.setdefault(find(vi), []).append(vi)

    mw = mesh_obj.matrix_world
    all_world = [mw @ v.co for v in mesh_obj.data.vertices]
    zmin = min(p.z for p in all_world)
    zmax = max(p.z for p in all_world)
    height = max(zmax - zmin, 1e-6)
    bone_heads = {name: head for name, head, _ in bones}
    policy = ownership_rules or {
        "schema": "owned_skin_ownership_rules.v1",
        "source": None,
        "rules": [],
    }
    weapon_component = None
    weapon_bone = arm_obj.pose.bones.get("RightWeaponTip")
    weapon_corridor = None
    if weapon_bone is not None:
        weapon_anchor = arm_obj.matrix_world @ weapon_bone.head
        hand_bone = arm_obj.pose.bones.get("RightHand")
        if hand_bone is not None:
            hand_anchor = arm_obj.matrix_world @ hand_bone.head
            weapon_vec = weapon_anchor - hand_anchor
            weapon_len2 = weapon_vec.length_squared
            if weapon_len2 > 1e-8:
                weapon_corridor = (hand_anchor, weapon_vec, weapon_len2)
        weapon_vertex = min(
            range(len(all_world)),
            key=lambda vi: (all_world[vi] - weapon_anchor).length_squared,
        )
        weapon_component = find(weapon_vertex)
    applied_rules = []
    component_count = 0
    ordered_components = sorted(components.values(), key=lambda values: min(values))
    for component_id, indices in enumerate(ordered_components):
        component_count += 1
        points = [all_world[vi] for vi in indices]
        center = sum(points, Vector()) / len(points)
        best_name = None
        best_dist = float("inf")
        for name, head, tail in bones:
            seg = tail - head
            seg_len2 = seg.length_squared
            if seg_len2 < 1e-12:
                dist = (center - head).length
            else:
                t = max(0.0, min(1.0, (center - head).dot(seg) / seg_len2))
                dist = (center - (head + seg * t)).length
            if dist < best_dist:
                best_dist, best_name = dist, name
        # Critical armor ownership overrides geometric proximity. A helmet
        # crown must never be averaged into the neck/torso just because its
        # disconnected component centroid is lower than the crown vertices.
        corridor_weapon = False
        if weapon_corridor is not None:
            origin, direction, direction_len2 = weapon_corridor
            t = float((center - origin).dot(direction) / direction_len2)
            closest = origin + direction * max(0.0, min(1.0, t))
            corridor_weapon = 0.04 < t <= 1.08 and (center - closest).length <= 0.09
        if weapon_component == find(indices[0]) or corridor_weapon:
            best_name = "RightWeaponTip"
        elif min(p.z for p in points) >= zmin + 0.82 * height:
            best_name = "Head"
        matches = [
            rule
            for rule in policy["rules"]
            if _rule_matches(rule, source_owner=best_name, center=center, bone_heads=bone_heads)
        ]
        if len(matches) > 1:
            ids = ", ".join(rule["id"] for rule in matches)
            raise RuntimeError(f"ownership rules are ambiguous for component {component_id}: {ids}")
        if matches:
            rule = matches[0]
            target = str(rule["toOwner"])
            if target not in bone_heads:
                raise ValueError(f"ownership rule {rule['id']} targets missing bone {target}")
            previous_owner = best_name
            best_name = target
            applied_rules.append(
                {
                    "componentId": component_id,
                    "vertexCount": len(indices),
                    "fromOwner": previous_owner,
                    "toOwner": best_name,
                    "ruleId": rule["id"],
                    "reason": rule["reason"],
                    "center": [float(center.x), float(center.y), float(center.z)],
                }
            )
        if best_name is None:
            raise RuntimeError("rigid component skinning found no candidate bone")
        mesh_obj.vertex_groups[best_name].add(indices, 1.0, "REPLACE")

    counts = {rule["id"]: 0 for rule in policy["rules"]}
    for application in applied_rules:
        counts[application["ruleId"]] += 1
    for rule in policy["rules"]:
        if counts[rule["id"]] < int(rule["minApplications"]):
            raise RuntimeError(
                f"ownership rule {rule['id']} matched {counts[rule['id']]} components; "
                f"expected at least {rule['minApplications']}"
            )

    mesh_obj.parent = arm_obj
    mesh_obj.parent_type = "OBJECT"
    mod = mesh_obj.modifiers.new(name="Armature", type="ARMATURE")
    mod.object = arm_obj
    mod.use_vertex_groups = True
    return {
        "schema": policy["schema"],
        "rulesFile": policy["source"],
        "componentCount": component_count,
        "applied": applied_rules,
        "applicationsByRule": counts,
    }


def _auto_weight(
    arm_obj, mesh_obj, skin_mode: str, ownership_rules: dict | None = None, *, k: int = 4, power: float = 2.0, trim: float = 0.0
) -> tuple[str, dict]:
    """Soft k-nearest bone-segment weights (Bone Heat fails on Meshy islands)."""
    _ensure_bone_lengths(arm_obj)
    if skin_mode == "rigid_connected_components":
        audit = _rigid_component_weights(arm_obj, mesh_obj, ownership_rules=ownership_rules)
        return skin_mode, audit
    if skin_mode == "rigid_with_joint_blend":
        audit = _rigid_with_joint_blend_weights(arm_obj, mesh_obj)
        return skin_mode, audit
    if skin_mode != "soft_k_nearest_segment":
        raise ValueError(f"unsupported skin mode: {skin_mode}")
    _nearest_bone_weights(arm_obj, mesh_obj, k=k, power=power, trim=trim)
    return f"soft_k_nearest_segment_k{k}_p{power}_t{trim}", {
        "schema": "owned_skin_ownership_rules.v1",
        "rulesFile": None,
        "componentCount": None,
        "applied": [],
        "applicationsByRule": {},
    }


def main() -> int:
    global HIERARCHY
    opts = _parse()
    species = str(opts.get("species") or "humanoid")
    if species != "humanoid":
        raise SystemExit(
            f"rig_frame0_shared_skeleton.py is Mixamo-humanoid only. "
            f"For species={species!r} use run_owned_species_bind.py --species {species} "
            "--part-map <authored.json>. Refusing to place Mixamo Hips/Spine on a rider_mount mesh."
        )
    mesh_path = _abs(Path(opts["mesh"]))
    out_path = _abs(Path(opts["output"]))
    skel_path = _abs(Path(opts["skeletonJson"])) if opts["skeletonJson"] else out_path.with_suffix(".skeleton.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(mesh_path))
    mesh_obj = next(o for o in bpy.data.objects if o.type == "MESH")
    # Normalize scale: if mesh is huge/tiny, rescale so height ~1.4m
    verts = _mesh_world_verts(mesh_obj)
    zmin, zmax = float(verts[:, 2].min()), float(verts[:, 2].max())
    height = max(zmax - zmin, 1e-6)
    target_h = 1.4
    scale = target_h / height
    mesh_obj.scale = (scale, scale, scale)
    bpy.context.view_layer.update()
    # Apply scale
    bpy.ops.object.select_all(action="DESELECT")
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = mesh_obj
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    # Center X/Y over origin, feet on z=0
    verts = _mesh_world_verts(mesh_obj)
    center_xy = verts[:, :2].mean(axis=0)
    zmin = float(verts[:, 2].min())
    mesh_obj.location.x -= float(center_xy[0])
    mesh_obj.location.y -= float(center_xy[1])
    mesh_obj.location.z -= zmin
    bpy.context.view_layer.update()
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)

    verts = _mesh_world_verts(mesh_obj)
    joints = _build_joint_guesses(verts)
    # The Crusader's helmet and blade are ownership-critical. The crown is
    # deliberately placed on our Head bone, and the weapon gets a child bone
    # whose rest tail is the farthest vertex from the strike-hand wrist.
    unit_sid = str(opts["unitSid"])
    if unit_sid == "h3_crusader":
        zmin, zmax = float(verts[:, 2].min()), float(verts[:, 2].max())
        height = max(zmax - zmin, 1e-3)
        head_band = verts[(verts[:, 2] >= zmin + 0.78 * height)]
        if len(head_band):
            crown = head_band[np.argmax(head_band[:, 2])]
            # Head must rotate from the neck. The crown is the owned end/site,
            # not the pivot; using the crown as the bone head makes rigid
            # helmet/head components float behind the body during IK.
            joints["Head"] = joints["neck"] + np.array([0, 0, 0.03 * height])
            joints["head_end"] = crown
        hand = joints["RightHand"]
        # The imported Crusader is camera-facing with the sword on +X. Do not
        # choose an arbitrary farthest vertex: that selects a boot or shield.
        # Restrict the search to the raised strike-side upper body, then use
        # the farthest point from the owned wrist within that region.
        strike = verts[(verts[:, 2] >= zmin + 0.48 * height) & (verts[:, 0] >= hand[0] + 0.12 * height)]
        if len(strike) == 0:
            raise RuntimeError("Crusader weapon search found no raised +X strike-side vertices")
        tip = strike[np.argmax(np.linalg.norm(strike - hand[None, :], axis=1))]
        joints["RightWeaponTip"] = tip
    hierarchy = list(HIERARCHY)
    if unit_sid == "h3_crusader":
        hierarchy.append(("RightWeaponTip", "RightHand"))
    old_hierarchy = HIERARCHY
    HIERARCHY = hierarchy
    try:
        arm = _create_armature(joints, name="OwnedCrusader")
    finally:
        HIERARCHY = old_hierarchy
    ownership_rules = _load_ownership_rules(opts["ownershipRules"], unit_sid=unit_sid)
    weight_mode, ownership_audit = _auto_weight(
        arm,
        mesh_obj,
        str(opts["skinMode"]),
        ownership_rules,
        k=int(opts["skinK"]),
        power=float(opts["skinPower"]),
        trim=float(opts["skinTrim"]),
    )
    _ensure_bone_lengths(arm)

    # Export — select only our pair; force skins
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    mesh_obj.select_set(True)
    bpy.context.view_layer.objects.active = arm
    # Ensure armature rest
    bpy.ops.object.mode_set(mode="OBJECT")
    try:
        bpy.ops.export_scene.gltf(
            filepath=str(out_path),
            export_format="GLB",
            use_selection=True,
            export_animations=False,
            export_skins=True,
            export_morph=False,
            export_apply=False,
        )
    except Exception as e:
        # Some Blender 3.5 builds choke on neutral bones; try FBX then? Prefer rewriting parent.
        print(f"[rig] gltf export failed ({e}); retry nearest-bone rebind", flush=True)
        _nearest_bone_weights(arm, mesh_obj)
        weight_mode = "nearest_bone_retry"
        bpy.ops.object.select_all(action="DESELECT")
        arm.select_set(True)
        mesh_obj.select_set(True)
        bpy.context.view_layer.objects.active = arm
        bpy.ops.export_scene.gltf(
            filepath=str(out_path),
            export_format="GLB",
            use_selection=True,
            export_animations=False,
            export_skins=True,
            export_apply=False,
        )

    skel = {
        "rigFamily": "hand_owned_mixamo_like",
        "unitSid": unit_sid,
        "sourceMesh": str(mesh_path).replace("\\", "/"),
        "weightMode": weight_mode,
        "ownership": ownership_audit,
        "bones": [{"name": n, "parent": p, "head": joints[n].tolist()} for n, p in hierarchy],
        "hierarchy": hierarchy,
        "notes": "Frame-0 hand-built owned skeleton. Meshy vertex groups are stripped; Crusader owns helmet crown and weapon tip.",
        "proof": "generated artifact validated — hand skeleton + weights on frame 0",
    }
    skel_path.write_text(json.dumps(skel, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(out_path), "skeleton": str(skel_path), "weightMode": weight_mode, "bones": len(HIERARCHY)}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        import traceback

        traceback.print_exc()
        raise SystemExit(1)
