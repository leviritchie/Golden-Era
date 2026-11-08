#!/usr/bin/env python3
"""
Repair Meshy-style prop/body welds for animation-ready skinning.

Meshy GLBs often ship with thousands of unwelded duplicate verts (looks like a
solid character, but edge connectivity is shattered into thousands of islands).
Bridge faces between mace and hair/armor then rubber-band under pose.

Pipeline (fail-closed):
  1. Weld near-duplicate verts (restores one coherent surface).
  2. Label verts WEAPON vs BODY (spatial shaft/tip + dominant bone weights).
  3. Sample albedo Lab a,b (texture chroma) and refine ambiguous contact-band
     labels toward the nearer weapon/body chroma prototype. Mark bridge faces
     that span a large Lab-ab jump (hand/cloth welds that weights miss).
  4. Also mark mixed-label faces and faces on edges that stretch under a
     diagnostic arm pose.
  5. Delete those faces; remove loose verts/edges (weapon may become its own
     component — that is desired).
  6. Strip non-weapon skin weights from weapon verts; detach head↔tip overlap.

Blender:
  blender -b --python tools/homm3_silhouette_pose_fit/repair_meshy_prop_bridges.py -- \\
    --src artifacts/.../Meshy_AI_Character_output_4.glb \\
    --out artifacts/.../Meshy_AI_Character_output_4_bridgefix.glb \\
    --report artifacts/.../meshy46_v4_bridgefix_report.json

Proof: generated artifact validated — weld + prop bridge + weight cleanup;
not OE runtime proven.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict, deque
from pathlib import Path

import bmesh
import bpy
from mathutils import Euler, Quaternion, Vector

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")

MOTION_ROOT_KEY = "__motion_root__"
MOTION_ROOT_ROTATION_KEY = "__motion_root_rotation__"

# UniRig meshy46 strike arm + finger chain (same set as skinfix / reskin).
DEFAULT_WEAPON_BONES = {
    "Bone_037",
    "Bone_036",
    "Bone_035",
    "Bone_034",
    "Bone_033",
    "Bone_039",
    "Bone_038",
    "Bone_042",
    "Bone_041",
    "Bone_040",
    "Bone_045",
    "Bone_044",
    "Bone_043",
}

# Mixamo / Meshy auto-rig sword arm (crusader and similar masters without prop bones).
MIXAMO_SWORD_WEAPON_BONES = {
    "RightShoulder",
    "RightArm",
    "RightForeArm",
    "RightHand",
}

# UniRig Castle cavalry: horse legs/neck vs rider torso/limbs (63 joints, full cover).
MOUNT_CAVALIER_HORSE_BONES = {
    "Bone_000",
    "Bone_001",
    "Bone_003",
    "Bone_002",
    "Bone_015",
    "Bone_014",
    "Bone_013",
    "Bone_012",
    "Bone_011",
    "Bone_020",
    "Bone_019",
    "Bone_018",
    "Bone_017",
    "Bone_016",
    "Bone_008",
    "Bone_007",
    "Bone_006",
    "Bone_005",
    "Bone_004",
}
MOUNT_CAVALIER_RIDER_BONES = {
    "Bone_010",
    "Bone_009",
    "Bone_023",
    "Bone_022",
    "Bone_021",
    "Bone_027",
    "Bone_026",
    "Bone_039",
    "Bone_038",
    "Bone_043",
    "Bone_042",
    "Bone_041",
    "Bone_040",
    "Bone_047",
    "Bone_046",
    "Bone_045",
    "Bone_044",
    "Bone_055",
    "Bone_054",
    "Bone_053",
    "Bone_052",
    "Bone_051",
    "Bone_050",
    "Bone_049",
    "Bone_048",
    "Bone_062",
    "Bone_061",
    "Bone_060",
    "Bone_059",
    "Bone_058",
    "Bone_057",
    "Bone_056",
    "Bone_032",
    "Bone_031",
    "Bone_030",
    "Bone_029",
    "Bone_028",
    "Bone_037",
    "Bone_036",
    "Bone_035",
    "Bone_034",
    "Bone_033",
    "Bone_025",
    "Bone_024",
}
MOUNT_CAVALIER_PROP_BONES = MOUNT_CAVALIER_RIDER_BONES & DEFAULT_WEAPON_BONES

MOUNT_PROFILES: dict[str, dict[str, set[str]]] = {
    "cavalier": {
        "horse": set(MOUNT_CAVALIER_HORSE_BONES),
        "rider": set(MOUNT_CAVALIER_RIDER_BONES),
        "prop": set(MOUNT_CAVALIER_PROP_BONES),
    },
}

# Diagnostic pose: pull strike arm away from torso/head to expose rubber-band bridges.
DIAG_POSE_RAD = {
    "Bone_037": (-0.55, -0.35, 0.25),
    "Bone_036": (0.40, -0.20, -0.55),
    "Bone_035": (0.25, -0.45, -0.15),
    # UniRig off-hand (archer hand-on-hip welds).
    "Bone_042": (-0.55, 0.35, -0.25),
    "Bone_041": (0.40, 0.20, 0.55),
    "Bone_040": (0.25, 0.45, 0.15),
    # Mixamo right arm (sword side for crusader idle facing +X).
    "RightArm": (-0.45, -0.30, 0.20),
    "RightForeArm": (0.35, -0.25, -0.45),
    "RightHand": (0.20, -0.40, -0.15),
}

# Mounted units: flex horse neck/head and rider torso in addition to sword-arm pull.
MOUNT_DIAG_POSE_RAD = {
    **DIAG_POSE_RAD,
    "Bone_008": (0.40, 0.0, 0.15),
    "Bone_007": (0.30, 0.0, 0.10),
    "Bone_006": (0.20, 0.0, 0.05),
    "Bone_021": (0.12, 0.0, -0.08),
    "Bone_032": (0.10, 0.15, 0.0),
    "Bone_037": (0.10, -0.15, 0.0),
}


def _argv() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return sys.argv[1:]


def _parse() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--src",
        type=Path,
        default=ROOT / "artifacts/hobgoblin_attack_pose_pipeline/master/Meshy_AI_Character_output_4.glb",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=ROOT
        / "artifacts/hobgoblin_attack_pose_pipeline/master/Meshy_AI_Character_output_4_bridgefix.glb",
    )
    ap.add_argument(
        "--report",
        type=Path,
        default=ROOT
        / "artifacts/hobgoblin_attack_pose_pipeline/master/meshy46_v4_bridgefix_report.json",
    )
    ap.add_argument("--tip-bone", default="Bone_033")
    ap.add_argument("--wrist-bone", default="Bone_035")
    ap.add_argument("--elbow-bone", default="Bone_036")
    ap.add_argument("--head-bone", default="Bone_025")
    ap.add_argument(
        "--tip-end",
        choices=("head", "tail"),
        default="head",
        help="Which end of tip-bone to use as tip probe (auto-tail when tip==wrist).",
    )
    ap.add_argument(
        "--wrist-end",
        choices=("head", "tail"),
        default="head",
        help="Which end of wrist-bone to use as wrist probe.",
    )
    ap.add_argument(
        "--species",
        choices=("infantry", "mount"),
        default="infantry",
        help="infantry = weapon/body bridgefix; mount = horse/rider/prop bridgefix.",
    )
    ap.add_argument(
        "--mount-profile",
        default="cavalier",
        help="Mount bone partition preset when --species mount (default: cavalier).",
    )
    ap.add_argument(
        "--weapon-bones",
        default="",
        help="Comma-separated weapon bone names. Empty = UniRig meshy46 defaults. "
        "Use preset 'mixamo_sword' for RightShoulder/Arm/ForeArm/Hand.",
    )
    ap.add_argument(
        "--head-bones",
        default="",
        help="Comma-separated head bones for scalp vs tip detachment. "
        "Empty = UniRig defaults, or Mixamo Head/neck set when --weapon-bones=mixamo_sword.",
    )
    ap.add_argument("--tip-radius", type=float, default=0.28)
    ap.add_argument("--shaft-radius", type=float, default=0.10)
    ap.add_argument("--stretch-thresh", type=float, default=0.12)
    ap.add_argument(
        "--stretch-ratio",
        type=float,
        default=3.5,
        help="Delete faces on edges whose posed/bind length ratio exceeds this (tip-touching).",
    )
    ap.add_argument(
        "--weld-dist",
        type=float,
        default=1e-4,
        help="Merge verts closer than this (Meshy ships unwelded duplicates). 0 disables.",
    )
    ap.add_argument(
        "--max-tip-contam",
        type=int,
        default=0,
        help="Fail-closed if tip-near verts still carry non-weapon weights above this count.",
    )
    ap.add_argument(
        "--max-delete-face-frac",
        type=float,
        default=0.12,
        help="Fail-closed if bridge delete would remove more than this fraction of faces.",
    )
    ap.add_argument(
        "--max-second-pass-mixed-frac",
        type=float,
        default=0.10,
        help="Budget for iterative post-delete mixed-face cleanup as a fraction of face count.",
    )
    ap.add_argument(
        "--max-remaining-mixed-faces",
        type=int,
        default=0,
        help="Fail-closed if mixed-label faces remain after cleanup passes exceed this count.",
    )
    ap.add_argument(
        "--min-bridge-faces",
        type=int,
        default=0,
        help="Minimum bridge faces to delete. 0 allows weld-only repairs.",
    )
    ap.add_argument(
        "--chroma",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use albedo Lab a,b (texture chroma) for label refine + bridge faces. "
        "Default on; fail-closed if no Base Color texture when enabled.",
    )
    ap.add_argument(
        "--chroma-edge-ab",
        type=float,
        default=28.0,
        help="Min Lab-ab distance across a face to count as a chroma bridge.",
    )
    ap.add_argument(
        "--chroma-margin",
        type=float,
        default=4.0,
        help="Required Lab-ab gap favoring one prototype before flipping a seed label.",
    )
    ap.add_argument(
        "--chroma-contact-radius",
        type=float,
        default=0.28,
        help="World-space radius around tip/shaft where chroma may re-label verts.",
    )
    ap.add_argument(
        "--chroma-secondary-tip-bone",
        default="Bone_045",
        help="Extra contact probe for off-hand welds (UniRig left fingertip). "
        "Empty disables.",
    )
    ap.add_argument(
        "--animation-clips-root",
        type=Path,
        default=None,
        help="Scan fused_push gpu_clip_result.json under this unit directory and "
        "union 3D mesh stretch hits from fitted keyframes (not 2D silhouette).",
    )
    ap.add_argument(
        "--animation-min-frame-score",
        type=float,
        default=0.0,
        help="Skip clip frames whose frameScores entry is below this (0 = all fitted frames).",
    )
    ap.add_argument(
        "--animation-only-stretch",
        action="store_true",
        help="Use animation-keyframe stretch only; skip the fixed diagnostic arm pose.",
    )
    ap.add_argument(
        "--animation-distortion-report",
        type=Path,
        default=None,
        help="Optional path to write animation stretch scan JSON before bridge delete.",
    )
    return ap.parse_args(_argv())


def _weld_mesh(mesh, dist: float) -> dict:
    """Merge near-duplicate verts. Returns weld stats. Preserves faces/weights via bmesh."""
    if dist <= 0.0:
        return {
            "enabled": False,
            "dist": dist,
            "vertsBefore": len(mesh.data.vertices),
            "vertsAfter": len(mesh.data.vertices),
            "vertsRemoved": 0,
            "componentsBefore": None,
            "componentsAfter": None,
        }
    comps_before = _connected_components(mesh)
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    n_before = len(bm.verts)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=float(dist))
    n_after = len(bm.verts)
    bm.to_mesh(mesh.data)
    bm.free()
    mesh.data.update()
    # Vertex group indices stay valid; orphaned weights on removed verts are gone with them.
    comps_after = _connected_components(mesh)
    return {
        "enabled": True,
        "dist": float(dist),
        "vertsBefore": n_before,
        "vertsAfter": n_after,
        "vertsRemoved": int(n_before - n_after),
        "componentsBefore": len(comps_before),
        "componentsAfter": len(comps_after),
        "componentSizesTopBefore": [len(c) for c in comps_before[:8]],
        "componentSizesTopAfter": [len(c) for c in comps_after[:8]],
    }


def _clear_scene() -> None:
    bpy.ops.wm.read_factory_settings(use_empty=True)


def _bone_end(arm, name: str, end: str = "head") -> Vector:
    pb = arm.pose.bones.get(name)
    if pb is None:
        raise RuntimeError(f"missing bone {name}")
    local = pb.tail if end == "tail" else pb.head
    return arm.matrix_world @ local


def _bone_head(arm, name: str) -> Vector:
    return _bone_end(arm, name, "head")


def _weapon_tip_and_wrist(
    arm,
    *,
    tip_bone: str,
    wrist_bone: str,
    tip_end: str,
    wrist_end: str,
) -> tuple[Vector, Vector]:
    """Resolve tip/wrist probe points.

    Mixamo auto-rigs often have no dedicated tip bone: tip_bone == wrist_bone.
    In that case default tip to the hand bone tail and wrist to the hand head so
    shaft/tip radii still span the held prop.
    """
    if tip_bone == wrist_bone and tip_end == "head" and wrist_end == "head":
        tip = _bone_end(arm, tip_bone, "tail")
        wrist = _bone_end(arm, wrist_bone, "head")
        if (tip - wrist).length < 1e-4:
            # Degenerate bone: synthesize a short outward tip probe.
            tip = wrist + Vector((0.0, -0.12, 0.0))
        return tip, wrist
    return _bone_end(arm, tip_bone, tip_end), _bone_end(arm, wrist_bone, wrist_end)

def _seg_dist(p: Vector, a: Vector, b: Vector) -> float:
    ab = b - a
    denom = ab.length_squared
    if denom < 1e-12:
        return (p - a).length
    t = max(0.0, min(1.0, (p - a).dot(ab) / denom))
    return (p - (a + ab * t)).length


def _ensure_groups(mesh, names: set[str]) -> dict[str, bpy.types.VertexGroup]:
    out = {g.name: g for g in mesh.vertex_groups}
    for n in names:
        if n not in out:
            out[n] = mesh.vertex_groups.new(name=n)
    return out


def _dominant_bone(v, vg_index: dict[int, str]) -> tuple[str | None, float]:
    best = None
    bw = 0.0
    for g in v.groups:
        w = float(g.weight)
        if w > bw:
            bw = w
            best = vg_index.get(g.group)
    return best, bw



def _srgb_to_lab_ab(r: float, g: float, b: float) -> tuple[float, float]:
    """sRGB [0,1] -> CIE Lab a,b (lightness discarded). Matches gpu_geometry_score."""

    def _lin(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

    rl, gl, bl = (
        _lin(max(0.0, min(1.0, r))),
        _lin(max(0.0, min(1.0, g))),
        _lin(max(0.0, min(1.0, b))),
    )
    x = (rl * 0.4124564 + gl * 0.3575761 + bl * 0.1804375) / 0.95047
    y = rl * 0.2126729 + gl * 0.7151522 + bl * 0.0721750
    z = (rl * 0.0193339 + gl * 0.1191920 + bl * 0.9503041) / 1.08883
    eps = 216.0 / 24389.0
    kappa = 24389.0 / 27.0

    def _f(t: float) -> float:
        return t ** (1.0 / 3.0) if t > eps else (kappa * t + 16.0) / 116.0

    fx, fy, fz = _f(x), _f(y), _f(z)
    return (500.0 * (fx - fy), 200.0 * (fy - fz))


def _lab_ab_dist(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _median_ab(points: list[tuple[float, float]]) -> tuple[float, float] | None:
    if not points:
        return None
    as_ = sorted(p[0] for p in points)
    bs_ = sorted(p[1] for p in points)
    mid = len(points) // 2
    return (as_[mid], bs_[mid])


def _find_albedo_image(mesh) -> bpy.types.Image | None:
    """Prefer Principled BSDF Base Color image; else first non-ORM TEX_IMAGE."""
    for slot in mesh.material_slots:
        mat = slot.material
        if mat is None or not mat.use_nodes or mat.node_tree is None:
            continue
        for node in mat.node_tree.nodes:
            if node.type != "BSDF_PRINCIPLED":
                continue
            base = node.inputs.get("Base Color")
            if base is None:
                continue
            for link in base.links:
                src = link.from_node
                if src.type == "TEX_IMAGE" and src.image is not None:
                    return src.image
        for node in mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image is not None:
                name = (node.image.name or "").lower()
                if any(tok in name for tok in ("metal", "rough", "normal", "orm")):
                    continue
                return node.image
    return None


def _sample_vert_lab_ab(mesh) -> dict:
    """Per-vertex Lab a,b from albedo UV. None where UV/alpha is unusable."""
    image = _find_albedo_image(mesh)
    n_verts = len(mesh.data.vertices)
    if image is None:
        return {
            "ok": False,
            "reason": "no_albedo_image",
            "image": None,
            "labAb": [None] * n_verts,
            "sampled": 0,
        }
    if not mesh.data.uv_layers:
        return {
            "ok": False,
            "reason": "no_uv_layer",
            "image": image.name,
            "labAb": [None] * n_verts,
            "sampled": 0,
        }
    w, h = int(image.size[0]), int(image.size[1])
    if w < 4 or h < 4:
        return {
            "ok": False,
            "reason": f"albedo_too_small_{w}x{h}",
            "image": image.name,
            "labAb": [None] * n_verts,
            "sampled": 0,
        }
    n_pix = w * h * 4
    rgba = None
    flat = None
    try:
        import numpy as np

        buf = np.empty(n_pix, dtype=np.float32)
        image.pixels.foreach_get(buf)
        rgba = buf.reshape(h, w, 4)
    except Exception:
        flat = list(image.pixels)

    uv_layer = mesh.data.uv_layers.active or mesh.data.uv_layers[0]
    uv_sum: list[list[float]] = [[0.0, 0.0, 0.0] for _ in range(n_verts)]
    for poly in mesh.data.polygons:
        for li in poly.loop_indices:
            vi = mesh.data.loops[li].vertex_index
            uv = uv_layer.data[li].uv
            uv_sum[vi][0] += float(uv.x)
            uv_sum[vi][1] += float(uv.y)
            uv_sum[vi][2] += 1.0

    lab_ab: list[tuple[float, float] | None] = [None] * n_verts
    sampled = 0
    for vi, (su, sv, cnt) in enumerate(uv_sum):
        if cnt < 1.0:
            continue
        u = (su / cnt) % 1.0
        v = (sv / cnt) % 1.0
        x = min(w - 1, max(0, int(u * w)))
        y = min(h - 1, max(0, int(v * h)))
        if rgba is not None:
            r, g, b, a = (
                float(rgba[y, x, 0]),
                float(rgba[y, x, 1]),
                float(rgba[y, x, 2]),
                float(rgba[y, x, 3]),
            )
        else:
            assert flat is not None
            i = (y * w + x) * 4
            r, g, b, a = flat[i], flat[i + 1], flat[i + 2], flat[i + 3]
        if a < 0.05:
            continue
        lab_ab[vi] = _srgb_to_lab_ab(r, g, b)
        sampled += 1
    return {
        "ok": sampled >= 64,
        "reason": None if sampled >= 64 else f"too_few_chroma_samples_{sampled}",
        "image": image.name,
        "imageSize": [w, h],
        "labAb": lab_ab,
        "sampled": sampled,
    }


def _refine_labels_with_chroma(
    mesh,
    arm,
    labels: list[str],
    lab_ab: list[tuple[float, float] | None],
    weapon_bones: set[str],
    *,
    tip_bone: str,
    wrist_bone: str,
    tip_end: str,
    wrist_end: str,
    tip_radius: float,
    shaft_radius: float,
    contact_radius: float,
    chroma_margin: float,
) -> dict:
    """Flip contact-band seed labels toward the nearer weapon/body Lab-ab prototype."""
    tip, wrist = _weapon_tip_and_wrist(
        arm,
        tip_bone=tip_bone,
        wrist_bone=wrist_bone,
        tip_end=tip_end,
        wrist_end=wrist_end,
    )
    direction = tip - wrist
    tip_ext = tip if direction.length < 1e-6 else tip + direction.normalized() * 0.12
    vg_index = {g.index: g.name for g in mesh.vertex_groups}
    mw = mesh.matrix_world

    weapon_seed: list[tuple[float, float]] = []
    body_seed: list[tuple[float, float]] = []
    for idx, lab in enumerate(labels):
        ab = lab_ab[idx] if idx < len(lab_ab) else None
        if ab is None:
            continue
        v = mesh.data.vertices[idx]
        co = mw @ v.co
        w_weapon = 0.0
        for g in v.groups:
            n = vg_index.get(g.group)
            if n in weapon_bones:
                w_weapon += float(g.weight)
        d_tip = (co - tip).length
        d_seg = _seg_dist(co, wrist, tip_ext)
        if lab == "weapon" and w_weapon >= 0.45 and (
            d_seg <= shaft_radius * 1.5 or d_tip <= tip_radius
        ):
            weapon_seed.append(ab)
        elif lab == "body" and w_weapon < 0.15 and d_tip > contact_radius:
            body_seed.append(ab)

    weapon_proto = _median_ab(weapon_seed)
    body_proto = _median_ab(body_seed)
    if weapon_proto is None or body_proto is None:
        return {
            "ok": False,
            "reason": (
                f"chroma_prototypes_missing weaponSeeds={len(weapon_seed)} "
                f"bodySeeds={len(body_seed)}"
            ),
            "weaponProtoAb": weapon_proto,
            "bodyProtoAb": body_proto,
            "flippedToWeapon": 0,
            "flippedToBody": 0,
            "contactBandVerts": 0,
            "labels": labels,
        }

    proto_sep = _lab_ab_dist(weapon_proto, body_proto)
    if proto_sep < chroma_margin:
        # Skin-on-skin limbs (archer hand vs torso skin) share Lab-ab. Skip
        # prototype flips; local face chroma bridges still cut cloth welds.
        return {
            "ok": True,
            "reason": None,
            "skippedPrototypeRefine": True,
            "skipReason": f"weapon_body_chroma_too_similar dist={proto_sep:.2f}",
            "weaponProtoAb": list(weapon_proto),
            "bodyProtoAb": list(body_proto),
            "protoSeparationAb": round(proto_sep, 3),
            "weaponSeedCount": len(weapon_seed),
            "bodySeedCount": len(body_seed),
            "flippedToWeapon": 0,
            "flippedToBody": 0,
            "contactBandVerts": 0,
            "labels": labels,
        }

    out = list(labels)
    flipped_w = 0
    flipped_b = 0
    contact_n = 0
    for idx, lab in enumerate(labels):
        ab = lab_ab[idx] if idx < len(lab_ab) else None
        if ab is None:
            continue
        v = mesh.data.vertices[idx]
        co = mw @ v.co
        d_tip = (co - tip).length
        d_seg = _seg_dist(co, wrist, tip_ext)
        w_weapon = 0.0
        w_body = 0.0
        for g in v.groups:
            n = vg_index.get(g.group)
            gw = float(g.weight)
            if n in weapon_bones:
                w_weapon += gw
            elif n:
                w_body += gw
        in_contact = (
            d_tip <= contact_radius
            or d_seg <= max(shaft_radius * 2.5, 0.16)
            or (w_weapon >= 0.12 and w_body >= 0.12)
        )
        if not in_contact:
            continue
        contact_n += 1
        d_w = _lab_ab_dist(ab, weapon_proto)
        d_b = _lab_ab_dist(ab, body_proto)
        name, w = _dominant_bone(v, vg_index)
        strong_weapon = (
            name in weapon_bones and w >= 0.55 and d_seg <= shaft_radius * 1.2
        )
        if d_w + chroma_margin < d_b and lab != "weapon":
            out[idx] = "weapon"
            flipped_w += 1
        elif (
            d_b + chroma_margin < d_w
            and lab != "body"
            and not (strong_weapon and d_b + chroma_margin * 2.0 >= d_w)
        ):
            out[idx] = "body"
            flipped_b += 1

    return {
        "ok": True,
        "reason": None,
        "weaponProtoAb": list(weapon_proto),
        "bodyProtoAb": list(body_proto),
        "protoSeparationAb": round(proto_sep, 3),
        "weaponSeedCount": len(weapon_seed),
        "bodySeedCount": len(body_seed),
        "flippedToWeapon": flipped_w,
        "flippedToBody": flipped_b,
        "contactBandVerts": contact_n,
        "labels": out,
    }


def _bridge_faces_from_chroma(
    mesh,
    labels: list[str],
    lab_ab: list[tuple[float, float] | None],
    *,
    chroma_edge_ab: float,
    tip,
    contact_radius: float,
    contact_points: list | None = None,
) -> set[int]:
    """Faces spanning a large albedo Lab-ab jump near prop/body contact.

    Contact probes include the primary tip plus any extras (e.g. off-hand tip)
    so left-hand/hip welds are not tied to the strike-hand tip alone.
    """
    mw = mesh.matrix_world
    probes = list(contact_points) if contact_points else [tip]
    hit: set[int] = set()
    # Same-label textured cloth needs a stricter Lab-ab jump than mixed labels.
    same_label_ab = float(chroma_edge_ab) * 1.35
    for pi, poly in enumerate(mesh.data.polygons):
        ids = list(poly.vertices)
        abs_ = [
            lab_ab[i]
            for i in ids
            if i < len(lab_ab) and lab_ab[i] is not None
        ]
        if len(abs_) < 2:
            continue
        max_d = 0.0
        for i in range(len(abs_)):
            for j in range(i + 1, len(abs_)):
                max_d = max(max_d, _lab_ab_dist(abs_[i], abs_[j]))
        labs = {labels[i] for i in ids}
        mixed = "weapon" in labs and "body" in labs
        if mixed and max_d < chroma_edge_ab:
            continue
        if (not mixed) and max_d < same_label_ab:
            continue
        near_contact = False
        for i in ids:
            co = mw @ mesh.data.vertices[i].co
            if any((co - p).length <= contact_radius for p in probes):
                near_contact = True
                break
        # Chroma cuts only in the tip/off-hand contact band (or already mixed labels).
        if mixed or near_contact:
            hit.add(pi)
    return hit


def _chroma_faces_mixed_label_only(
    mesh,
    labels: list[str],
    chroma_faces: set[int],
) -> set[int]:
    """Keep chroma bridge hits that span weapon/body labels only."""
    mixed_only: set[int] = set()
    polys = mesh.data.polygons
    for pi in chroma_faces:
        ids = list(polys[int(pi)].vertices)
        labs = {labels[int(i)] for i in ids}
        if "weapon" in labs and "body" in labs:
            mixed_only.add(int(pi))
    return mixed_only


def _label_verts(
    mesh,
    arm,
    weapon_bones: set[str],
    *,
    tip_bone: str,
    wrist_bone: str,
    elbow_bone: str,
    tip_radius: float,
    shaft_radius: float,
    head_bones: set[str] | None = None,
    tip_end: str = "head",
    wrist_end: str = "head",
) -> list[str]:
    """Per-vert label: 'weapon' | 'body'.

    Do NOT treat tip_radius alone as weapon: Meshy A-pose often parks the mace
    against the head/hair, so that would mis-label scalp verts as mace.
    """
    tip, wrist = _weapon_tip_and_wrist(
        arm,
        tip_bone=tip_bone,
        wrist_bone=wrist_bone,
        tip_end=tip_end,
        wrist_end=wrist_end,
    )
    elbow = _bone_head(arm, elbow_bone)
    direction = tip - wrist
    if direction.length < 1e-6:
        tip_ext = tip
    else:
        tip_ext = tip + direction.normalized() * 0.12
    head = head_bones or {"Bone_025", "Bone_026", "Bone_014", "Bone_015"}
    vg_index = {g.index: g.name for g in mesh.vertex_groups}
    labels: list[str] = []
    mw = mesh.matrix_world
    for v in mesh.data.vertices:
        co = mw @ v.co
        d_tip = (co - tip).length
        d_seg = _seg_dist(co, wrist, tip_ext)
        d_fore = _seg_dist(co, elbow, wrist)
        name, w = _dominant_bone(v, vg_index)
        w_weapon = 0.0
        w_head = 0.0
        for g in v.groups:
            n = vg_index.get(g.group)
            gw = float(g.weight)
            if n in weapon_bones:
                w_weapon += gw
            if n in head:
                w_head += gw
        # Shaft / forearm band is reliable. Tip ball only if already weapon-weighted
        # and not head-dominated (avoids hair glued to resting mace).
        on_shaft = d_seg <= shaft_radius or (d_fore <= 0.09 and w_weapon >= 0.25)
        on_tip = (
            d_tip <= tip_radius
            and w_weapon >= 0.30
            and w_head < 0.20
            and (name in weapon_bones or w_weapon >= 0.45)
        )
        weighty = (
            name in weapon_bones
            and w >= 0.40
            and w_head < 0.15
            and (d_seg <= 0.18 or d_tip <= 0.40)
        )
        labels.append("weapon" if (on_shaft or on_tip or weighty) else "body")
    return labels


def _mount_profile(name: str) -> dict[str, set[str]]:
    key = str(name or "cavalier").strip().lower()
    profile = MOUNT_PROFILES.get(key)
    if profile is None:
        known = ", ".join(sorted(MOUNT_PROFILES))
        raise RuntimeError(f"unknown mount profile {name!r}; known: {known}")
    return profile


def _label_verts_mount(
    mesh,
    arm,
    horse_bones: set[str],
    rider_bones: set[str],
    prop_bones: set[str],
    *,
    lance_head_bone: str = "Bone_004",
    lance_neck_bone: str = "Bone_005",
    saddle_bone: str = "Bone_025",
    lance_radius: float = 0.38,
) -> list[str]:
    """Per-vert label: horse | rider | prop (rider sword + horse-head lance)."""
    head = _bone_head(arm, lance_head_bone)
    neck = _bone_head(arm, lance_neck_bone)
    direction = head - neck
    lance_tip = head + direction.normalized() * 0.45 if direction.length > 1e-6 else head
    saddle = _bone_head(arm, saddle_bone)
    vg_index = {g.index: g.name for g in mesh.vertex_groups}
    labels: list[str] = []
    mw = mesh.matrix_world
    for v in mesh.data.vertices:
        co = mw @ v.co
        dom_name, dom_w = _dominant_bone(v, vg_index)
        w_horse = 0.0
        w_rider = 0.0
        w_prop = 0.0
        for g in v.groups:
            n = vg_index.get(g.group)
            gw = float(g.weight)
            if n in horse_bones:
                w_horse += gw
            if n in rider_bones:
                w_rider += gw
            if n in prop_bones:
                w_prop += gw
        d_lance = min((co - head).length, (co - lance_tip).length)
        saddle_band = (co - saddle).length <= 0.42 and co.z <= saddle.z + 0.18
        lance_weld = (
            d_lance <= lance_radius
            and dom_name in {"Bone_004", "Bone_005"}
            and w_horse >= 0.08
        )
        rider_weapon = dom_name in prop_bones and dom_w >= 0.22
        prop_blend = w_prop >= 0.30 and (w_rider >= 0.08 or dom_name in prop_bones)
        if lance_weld or rider_weapon or prop_blend:
            labels.append("prop")
        elif saddle_band and w_horse >= 0.06 and w_horse >= w_rider * 0.40:
            labels.append("horse")
        elif dom_name in horse_bones:
            labels.append("horse")
        elif dom_name in prop_bones:
            labels.append("prop")
        elif dom_name in rider_bones:
            labels.append("rider")
        elif w_horse >= w_rider and w_horse >= 0.12:
            labels.append("horse")
        elif w_rider >= 0.10:
            labels.append("rider")
        elif co.z <= saddle.z + 0.05:
            labels.append("horse")
        else:
            labels.append("rider")
    return labels


def _bridge_faces_from_mount_labels(mesh, labels: list[str]) -> set[int]:
    out: set[int] = set()
    for pi, poly in enumerate(mesh.data.polygons):
        labs = {labels[vi] for vi in poly.vertices}
        if len(labs) > 1:
            out.add(pi)
    return out


def _fix_mount_weights(
    mesh,
    labels: list[str],
    *,
    horse_bones: set[str],
    rider_bones: set[str],
    prop_bones: set[str],
) -> dict[str, int | float]:
    allowed_by_label = {
        "horse": horse_bones,
        "rider": rider_bones,
        "prop": prop_bones,
    }
    vg_index = {g.index: g.name for g in mesh.vertex_groups}
    fixed = {"horse": 0, "rider": 0, "prop": 0}
    stripped_mass = 0.0
    for idx, lab in enumerate(labels):
        if idx >= len(mesh.data.vertices):
            continue
        allowed = allowed_by_label.get(lab)
        if not allowed:
            continue
        v = mesh.data.vertices[idx]
        kept: dict[str, float] = {}
        stripped = 0.0
        for g in list(v.groups):
            name = vg_index.get(g.group)
            w = float(g.weight)
            if name in allowed and w > 1e-6:
                kept[name] = kept.get(name, 0.0) + w
            else:
                stripped += w
                if name is not None:
                    mesh.vertex_groups[name].remove([idx])
        if stripped <= 1e-6:
            continue
        stripped_mass += stripped
        fixed[lab] = int(fixed[lab]) + 1
        if kept:
            total = sum(kept.values())
            for name, w in kept.items():
                mesh.vertex_groups[name].add([idx], w / total, "REPLACE")
    return {
        "fixedHorseVerts": int(fixed["horse"]),
        "fixedRiderVerts": int(fixed["rider"]),
        "fixedPropVerts": int(fixed["prop"]),
        "strippedWeightMass": round(stripped_mass, 3),
    }


def _clear_pose(arm) -> None:
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    bpy.ops.pose.transforms_clear()
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()


def _apply_mount_diag_pose(arm) -> None:
    _clear_pose(arm)
    for name, xyz in MOUNT_DIAG_POSE_RAD.items():
        pb = arm.pose.bones.get(name)
        if pb is None:
            continue
        pb.rotation_mode = "XYZ"
        base = pb.rotation_euler
        pb.rotation_euler = Euler(
            (base.x + xyz[0], base.y + xyz[1], base.z + xyz[2]),
            "XYZ",
        )
    bpy.context.view_layer.update()


def _apply_diag_pose(arm, weapon_bones: set[str]) -> None:
    _clear_pose(arm)
    for name, xyz in DIAG_POSE_RAD.items():
        if name not in weapon_bones:
            continue
        pb = arm.pose.bones.get(name)
        if pb is None:
            raise RuntimeError(f"diagnostic pose missing bone {name}")
        pb.rotation_mode = "XYZ"
        base = pb.rotation_euler
        pb.rotation_euler = Euler(
            (base.x + xyz[0], base.y + xyz[1], base.z + xyz[2]),
            "XYZ",
        )
    bpy.context.view_layer.update()


def _axis_angle_quaternion_from_degrees(entry: dict) -> Quaternion:
    vector = [math.radians(float(entry.get(axis, 0.0))) for axis in ("x", "y", "z")]
    angle = math.sqrt(sum(value * value for value in vector))
    if angle <= 1e-12:
        return Quaternion((1.0, 0.0, 0.0, 0.0))
    axis = [value / angle for value in vector]
    return Quaternion(axis, angle)


def _apply_gpu_clip_pose(arm, pose: dict) -> None:
    """Apply one fused-push keyframe (degrees-as-vector, same contract as GPU fit)."""
    _clear_pose(arm)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="POSE")
    for pb in arm.pose.bones:
        entry = pose.get(pb.name)
        if isinstance(entry, dict):
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = _axis_angle_quaternion_from_degrees(entry)
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.context.view_layer.update()


def _discover_animation_clip_results(clips_root: Path) -> list[Path]:
    root = clips_root if clips_root.is_absolute() else (ROOT / clips_root)
    if not root.is_dir():
        raise FileNotFoundError(f"animation clips root is missing: {root}")
    hits = sorted(root.glob("**/fused_push_v24_pipeline/gpu_clip_result.json"))
    if not hits:
        hits = sorted(root.glob("**/gpu_cascade_delivery/gpu_clip_result.json"))
    return hits


def _load_animation_pose_frames(
    clip_path: Path,
    *,
    min_frame_score: float,
) -> list[tuple[int, dict]]:
    payload = json.loads(clip_path.read_text(encoding="utf-8"))
    poses = payload.get("poses")
    if not isinstance(poses, dict) or not poses:
        raise ValueError(f"{clip_path} has no poses")
    frame_indices = payload.get("frameIndices")
    if not isinstance(frame_indices, list) or not frame_indices:
        frame_indices = sorted(int(key) for key in poses.keys())
    frame_scores = payload.get("frameScores")
    if not isinstance(frame_scores, list):
        frame_scores = []
    out: list[tuple[int, dict]] = []
    for index, raw_frame in enumerate(frame_indices):
        frame = int(raw_frame)
        if min_frame_score > 0.0 and index < len(frame_scores):
            if float(frame_scores[index]) < float(min_frame_score):
                continue
        pose = poses.get(str(frame))
        if not isinstance(pose, dict):
            raise ValueError(f"{clip_path} missing pose for frame {frame}")
        out.append((frame, pose))
    return out


def _bridge_faces_from_animation_poses(
    mesh,
    arm,
    labels: list[str],
    clip_paths: list[Path],
    *,
    tip_bone: str,
    head_bone: str,
    stretch_thresh: float,
    stretch_ratio: float,
    min_frame_score: float,
) -> tuple[set[int], dict]:
    """Union stretch-bridge faces across all accepted fitted animation keyframes."""
    hit: set[int] = set()
    per_clip: list[dict] = []
    frames_scanned = 0
    frames_with_hits = 0
    for clip_path in clip_paths:
        clip_name = clip_path.parent.parent.name
        clip_score = None
        try:
            clip_payload = json.loads(clip_path.read_text(encoding="utf-8"))
            clip_score = float(clip_payload.get("score")) if clip_payload.get("score") is not None else None
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            clip_score = None
        frame_rows: list[dict] = []
        for frame, pose in _load_animation_pose_frames(
            clip_path,
            min_frame_score=min_frame_score,
        ):
            frames_scanned += 1
            _apply_gpu_clip_pose(arm, pose)
            frame_hits = _bridge_faces_from_stretch(
                mesh,
                arm,
                labels,
                tip_bone=tip_bone,
                head_bone=head_bone,
                stretch_thresh=stretch_thresh,
                stretch_ratio=stretch_ratio,
            )
            if frame_hits:
                frames_with_hits += 1
                hit |= frame_hits
            frame_rows.append(
                {
                    "frame": int(frame),
                    "bridgeFacesStretch": len(frame_hits),
                }
            )
        per_clip.append(
            {
                "clip": clip_name,
                "clipResult": str(clip_path).replace("\\", "/"),
                "clipScore": clip_score,
                "framesScanned": len(frame_rows),
                "framesWithStretchHits": sum(1 for row in frame_rows if row["bridgeFacesStretch"] > 0),
                "frames": frame_rows,
            }
        )
    _clear_pose(arm)
    stats = {
        "enabled": True,
        "clipsScanned": len(clip_paths),
        "framesScanned": frames_scanned,
        "framesWithStretchHits": frames_with_hits,
        "bridgeFacesAnimationUnion": len(hit),
        "minFrameScore": float(min_frame_score),
        "stretchThresh": float(stretch_thresh),
        "stretchRatio": float(stretch_ratio),
        "perClip": per_clip,
        "proof": (
            "generated artifact validated — 3D bind→posed edge stretch from fitted "
            "gpu_clip_result keyframes; not 2D silhouette detection"
        ),
    }
    return hit, stats


def _bridge_faces_from_labels(mesh, labels: list[str]) -> set[int]:
    out: set[int] = set()
    for pi, poly in enumerate(mesh.data.polygons):
        labs = {labels[vi] for vi in poly.vertices}
        if "weapon" in labs and "body" in labs:
            out.add(pi)
    return out


def _bridge_faces_from_stretch(
    mesh,
    arm,
    labels: list[str],
    *,
    tip_bone: str,
    head_bone: str,
    stretch_thresh: float,
    stretch_ratio: float = 4.0,
    body_labels: frozenset[str] | None = None,
) -> set[int]:
    """
    Faces on edges that rubber-band under the current (diagnostic) pose.

    Prefer bind→pose length *ratio*: Meshy welds are short in bind and explode when posed.
    Also keep absolute-length / tip↔head heuristics as backups.
    """
    tip = _bone_head(arm, tip_bone)
    head = _bone_head(arm, head_bone)
    body_like = body_labels if body_labels is not None else frozenset({"body"})
    # Bind lengths from unevaluated mesh (pose is applied to armature only).
    bind_mw = mesh.matrix_world
    bind_verts = [bind_mw @ v.co for v in mesh.data.vertices]
    bind_len: dict[tuple[int, int], float] = {}
    for e in mesh.data.edges:
        a, b = e.vertices
        key = (a, b) if a < b else (b, a)
        bind_len[key] = (bind_verts[a] - bind_verts[b]).length

    deps = bpy.context.evaluated_depsgraph_get()
    ev = mesh.evaluated_get(deps)
    me = ev.to_mesh()
    try:
        mw = ev.matrix_world
        verts = [mw @ v.co for v in me.vertices]
        edge_faces: dict[tuple[int, int], list[int]] = defaultdict(list)
        for pi, poly in enumerate(mesh.data.polygons):
            ids = list(poly.vertices)
            n = len(ids)
            for i in range(n):
                a, b = ids[i], ids[(i + 1) % n]
                key = (a, b) if a < b else (b, a)
                edge_faces[key].append(pi)

        hit: set[int] = set()
        for e in me.edges:
            a, b = e.vertices
            key = (a, b) if a < b else (b, a)
            L = (verts[a] - verts[b]).length
            bL = bind_len.get(key, L)
            ratio = L / max(bL, 1e-6)
            la, lb = labels[a], labels[b]
            da = (verts[a] - tip).length
            db = (verts[b] - tip).length
            ha = (verts[a] - head).length
            hb = (verts[b] - head).length
            tip_body = (da < 0.30 and lb in body_like and la not in body_like and db > 0.22) or (
                db < 0.30 and la in body_like and lb not in body_like and da > 0.22
            )
            tip_head = (da < 0.28 and hb < 0.32 and db > 0.18 and la in body_like) or (
                db < 0.28 and ha < 0.32 and da > 0.18 and lb in body_like
            )
            rubber = ratio >= stretch_ratio and L >= min(stretch_thresh, 0.08)
            # Rubber bands that touch the tip ball are always bridges we want cut.
            rubber_tip = rubber and (da < 0.35 or db < 0.35)
            if la != lb or tip_body or tip_head or rubber_tip or (rubber and la != lb):
                if L >= stretch_thresh or rubber_tip or la != lb:
                    for pi in edge_faces.get(key, []):
                        hit.add(pi)
            # Absolute long mixed / tip-head even without ratio.
            elif L >= stretch_thresh and (la != lb or tip_body or tip_head):
                for pi in edge_faces.get(key, []):
                    hit.add(pi)
        return hit
    finally:
        ev.to_mesh_clear()


def _detach_head_weapon_weights(
    mesh,
    arm,
    weapon_bones: set[str],
    *,
    tip: Vector,
    head_bones: set[str],
) -> dict:
    """Keep scalp on head bones and tip ball on weapon bones when they overlap in bind."""
    vg_index = {g.index: g.name for g in mesh.vertex_groups}
    stripped_weapon_from_head = 0
    stripped_body_from_tip = 0
    for v in mesh.data.vertices:
        co = mesh.matrix_world @ v.co
        d_tip = (co - tip).length
        w_weapon = 0.0
        w_head = 0.0
        for g in v.groups:
            n = vg_index.get(g.group)
            if n in weapon_bones:
                w_weapon += float(g.weight)
            if n in head_bones:
                w_head += float(g.weight)
        if d_tip <= 0.35 and w_head >= 0.20 and w_weapon > 0.0:
            for g in list(v.groups):
                n = vg_index.get(g.group)
                if n in weapon_bones:
                    mesh.vertex_groups[n].remove([v.index])
            stripped_weapon_from_head += 1
        if d_tip <= 0.22 and w_weapon >= 0.40:
            for g in list(v.groups):
                n = vg_index.get(g.group)
                if n and n not in weapon_bones:
                    mesh.vertex_groups[n].remove([v.index])
            stripped_body_from_tip += 1
    return {
        "strippedWeaponFromHeadVerts": stripped_weapon_from_head,
        "strippedBodyFromTipVerts": stripped_body_from_tip,
    }

def _delete_faces(mesh, face_indices: set[int]) -> int:
    if not face_indices:
        return 0
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    bm.faces.ensure_lookup_table()
    # bmesh face index matches mesh face index only before edits; delete by walking once.
    to_del = [f for f in bm.faces if f.index in face_indices]
    bmesh.ops.delete(bm, geom=to_del, context="FACES")
    # Drop loose verts/edges left by bridge removal.
    loose_verts = [v for v in bm.verts if not v.link_edges]
    if loose_verts:
        bmesh.ops.delete(bm, geom=loose_verts, context="VERTS")
    loose_edges = [e for e in bm.edges if e.is_wire and not e.link_faces]
    # Also remove edges with no faces.
    no_face_edges = [e for e in bm.edges if len(e.link_faces) == 0]
    if no_face_edges:
        bmesh.ops.delete(bm, geom=no_face_edges, context="EDGES")
    bm.to_mesh(mesh.data)
    bm.free()
    mesh.data.update()
    return len(to_del)


def _delete_tiny_components(mesh, *, min_keep: int = 24, keep_top_n: int = 2) -> dict:
    """
    After bridge cuts, tiny face scraps can remain. Keep the largest keep_top_n
    components (body + weapon, or horse + rider + prop) and any other component
    with >= min_keep verts.
    """
    comps = _connected_components(mesh)
    if len(comps) <= keep_top_n:
        return {"deletedVerts": 0, "deletedComponents": 0, "keptComponents": len(comps)}
    keep: set[int] = set()
    for i, c in enumerate(comps):
        if i < keep_top_n or len(c) >= min_keep:
            keep.update(c)
    drop = [i for i in range(len(mesh.data.vertices)) if i not in keep]
    if not drop:
        return {"deletedVerts": 0, "deletedComponents": 0, "keptComponents": len(comps)}
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    bm.verts.ensure_lookup_table()
    to_del = [bm.verts[i] for i in drop if i < len(bm.verts)]
    bmesh.ops.delete(bm, geom=to_del, context="VERTS")
    bm.to_mesh(mesh.data)
    bm.free()
    mesh.data.update()
    comps_after = _connected_components(mesh)
    return {
        "deletedVerts": len(drop),
        "deletedComponents": max(0, len(comps) - len(comps_after)),
        "keptComponents": len(comps_after),
        "componentSizesTop": [len(c) for c in comps_after[:8]],
    }


def _connected_components(mesh) -> list[list[int]]:
    adj: dict[int, set[int]] = defaultdict(set)
    for e in mesh.data.edges:
        a, b = e.vertices
        adj[a].add(b)
        adj[b].add(a)
    seen: set[int] = set()
    comps: list[list[int]] = []
    n = len(mesh.data.vertices)
    for i in range(n):
        if i in seen:
            continue
        if i not in adj and not mesh.data.vertices[i].groups:
            # isolated vert — still a component
            seen.add(i)
            comps.append([i])
            continue
        q = deque([i])
        seen.add(i)
        c = [i]
        while q:
            u = q.popleft()
            for v in adj.get(u, ()):
                if v not in seen:
                    seen.add(v)
                    q.append(v)
                    c.append(v)
        comps.append(c)
    comps.sort(key=len, reverse=True)
    return comps


def _fix_weapon_weights(
    mesh, labels: list[str], weapon_bones: set[str], *, tip_bone: str
) -> dict:
    groups = _ensure_groups(mesh, weapon_bones)
    if tip_bone not in groups:
        groups[tip_bone] = mesh.vertex_groups.new(name=tip_bone)
    vg_index = {g.index: g.name for g in mesh.vertex_groups}
    fixed = 0
    stripped_mass = 0.0
    assigned_full_tip = 0
    for idx, lab in enumerate(labels):
        if lab != "weapon":
            continue
        if idx >= len(mesh.data.vertices):
            continue
        v = mesh.data.vertices[idx]
        kept: dict[str, float] = {}
        stripped = 0.0
        for g in list(v.groups):
            name = vg_index.get(g.group)
            w = float(g.weight)
            if name in weapon_bones and w > 1e-6:
                kept[name] = kept.get(name, 0.0) + w
            else:
                stripped += w
                if name is not None:
                    mesh.vertex_groups[name].remove([idx])
        if stripped <= 1e-6 and kept:
            continue
        stripped_mass += stripped
        if not kept:
            groups[tip_bone].add([idx], 1.0, "REPLACE")
            assigned_full_tip += 1
        else:
            total = sum(kept.values())
            for name, w in kept.items():
                groups[name].add([idx], w / total, "REPLACE")
        fixed += 1
    return {
        "fixedVerts": fixed,
        "strippedWeightMass": round(stripped_mass, 3),
        "assignedFullTip": assigned_full_tip,
        "tipBone": tip_bone,
    }


def _export(arm, mesh, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    arm.select_set(True)
    mesh.select_set(True)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.export_scene.gltf(
        filepath=str(out),
        export_format="GLB",
        use_selection=True,
        export_animations=False,
        export_apply=False,
        export_skins=True,
        export_morph=False,
    )


def _repair_mount(
    args: argparse.Namespace,
    src: Path,
    out: Path,
    report_path: Path,
) -> int:
    profile = _mount_profile(args.mount_profile)
    horse_bones = profile["horse"]
    rider_bones = profile["rider"]
    prop_bones = profile["prop"]

    _clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(src))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if len(meshes) != 1:
        print(
            f"expected exactly one mesh object for mount bridge repair, got "
            f"{[(m.name, len(m.data.vertices)) for m in meshes]}",
            file=sys.stderr,
        )
        return 2
    mesh = meshes[0]
    all_mount_bones = horse_bones | rider_bones | prop_bones
    missing = sorted(b for b in all_mount_bones if b not in arm.pose.bones)
    if missing:
        print(
            f"fail-closed: mount profile bones missing from armature: {missing}",
            file=sys.stderr,
        )
        return 2
    _clear_pose(arm)

    n_faces_before = len(mesh.data.polygons)
    n_verts_before = len(mesh.data.vertices)
    weld_stats = _weld_mesh(mesh, float(args.weld_dist))
    if weld_stats["enabled"] and weld_stats["vertsRemoved"] > 0:
        print(
            f"[mount-bridgefix] weld dist={weld_stats['dist']} "
            f"removed {weld_stats['vertsRemoved']} verts "
            f"({weld_stats['vertsBefore']}→{weld_stats['vertsAfter']}); "
            f"components {weld_stats['componentsBefore']}→{weld_stats['componentsAfter']}",
            flush=True,
        )

    labels = _label_verts_mount(mesh, arm, horse_bones, rider_bones, prop_bones)
    n_horse = sum(1 for x in labels if x == "horse")
    n_rider = sum(1 for x in labels if x == "rider")
    n_prop = sum(1 for x in labels if x == "prop")
    if n_horse < 500:
        print(f"fail-closed: too few horse verts labeled ({n_horse})", file=sys.stderr)
        return 2
    if n_rider < 200:
        print(f"fail-closed: too few rider verts labeled ({n_rider})", file=sys.stderr)
        return 2
    if n_prop < 10:
        print(f"fail-closed: too few prop verts labeled ({n_prop})", file=sys.stderr)
        return 2

    mixed = _bridge_faces_from_mount_labels(mesh, labels)
    _apply_mount_diag_pose(arm)
    diag_stretched = _bridge_faces_from_stretch(
        mesh,
        arm,
        labels,
        tip_bone=args.tip_bone,
        head_bone=args.head_bone,
        stretch_thresh=args.stretch_thresh,
        stretch_ratio=float(args.stretch_ratio),
        body_labels=frozenset({"horse", "rider"}),
    )
    _clear_pose(arm)
    stretched = diag_stretched

    to_delete = mixed | stretched
    frac = len(to_delete) / max(1, len(mesh.data.polygons))
    if len(to_delete) < int(args.min_bridge_faces) and weld_stats.get("vertsRemoved", 0) <= 0:
        print(
            f"fail-closed: found only {len(to_delete)} mount bridge faces "
            f"(mixed={len(mixed)} stretch={len(stretched)}) and weld removed 0 verts",
            file=sys.stderr,
        )
        return 2
    if frac > float(args.max_delete_face_frac) and mixed:
        mixed_only_frac = len(mixed) / max(1, len(mesh.data.polygons))
        if mixed_only_frac <= float(args.max_delete_face_frac) and len(mixed) < len(to_delete):
            to_delete = set(mixed)
            frac = mixed_only_frac
            print(
                "[mount-bridgefix] mixed-only fallback: dropped stretch hits; "
                f"delete {len(to_delete)}/{len(mesh.data.polygons)} ({frac:.3f})",
                flush=True,
            )
    if frac > float(args.max_delete_face_frac):
        print(
            f"fail-closed: mount bridge delete {len(to_delete)}/{len(mesh.data.polygons)} "
            f"({frac:.3f}) exceeds maxDeleteFaceFrac={args.max_delete_face_frac}",
            file=sys.stderr,
        )
        return 2

    deleted = _delete_faces(mesh, to_delete) if to_delete else 0
    labels_after = _label_verts_mount(mesh, arm, horse_bones, rider_bones, prop_bones)
    weight_stats = _fix_mount_weights(
        mesh,
        labels_after,
        horse_bones=horse_bones,
        rider_bones=rider_bones,
        prop_bones=prop_bones,
    )
    debris_stats = _delete_tiny_components(mesh, min_keep=24, keep_top_n=3)

    labels_after = _label_verts_mount(mesh, arm, horse_bones, rider_bones, prop_bones)
    comps = _connected_components(mesh)

    remain_mixed = _bridge_faces_from_mount_labels(mesh, labels_after)
    second_pass_deleted = 0
    mixed_pass_budget = max(
        32,
        int(len(mesh.data.polygons) * float(args.max_second_pass_mixed_frac)),
    )
    while remain_mixed and second_pass_deleted < mixed_pass_budget:
        batch = remain_mixed
        if len(batch) > mixed_pass_budget - second_pass_deleted:
            break
        second_pass_deleted += _delete_faces(mesh, batch)
        labels_after = _label_verts_mount(mesh, arm, horse_bones, rider_bones, prop_bones)
        remain_mixed = _bridge_faces_from_mount_labels(mesh, labels_after)

    if remain_mixed and second_pass_deleted:
        print(
            f"[mount-bridgefix] second-pass mixed cleanup deleted {second_pass_deleted} faces; "
            f"remainingMixed={len(remain_mixed)} budget={mixed_pass_budget}",
            flush=True,
        )

    if len(remain_mixed) > int(args.max_remaining_mixed_faces):
        print(
            f"fail-closed: remainingMixedLabelFaces={len(remain_mixed)} after mount delete "
            f"(maxRemainingMixedFaces={args.max_remaining_mixed_faces})",
            file=sys.stderr,
        )
        return 2

    _export(arm, mesh, out)
    report = {
        "ok": True,
        "species": "mount",
        "mountProfile": str(args.mount_profile),
        "source": str(src).replace("\\", "/"),
        "output": str(out).replace("\\", "/"),
        "facesBefore": n_faces_before,
        "vertsBefore": n_verts_before,
        "facesAfter": len(mesh.data.polygons),
        "vertsAfter": len(mesh.data.vertices),
        "weld": weld_stats,
        "horseVertsLabeled": n_horse,
        "riderVertsLabeled": n_rider,
        "propVertsLabeled": n_prop,
        "bridgeFacesMixedLabel": len(mixed),
        "bridgeFacesStretch": len(stretched),
        "bridgeFacesStretchDiag": len(diag_stretched),
        "bridgeFacesUnion": len(to_delete),
        "facesDeleted": deleted,
        "remainingMixedLabelFaces": len(remain_mixed),
        "secondPassMixedFacesDeleted": second_pass_deleted,
        "connectedComponents": len(comps),
        "componentSizesTop": [len(c) for c in comps[:12]],
        "debrisCleanup": debris_stats,
        "stretchThresh": args.stretch_thresh,
        "stretchRatio": args.stretch_ratio,
        "maxDeleteFaceFrac": args.max_delete_face_frac,
        "horseBones": sorted(horse_bones),
        "riderBones": sorted(rider_bones),
        "propBones": sorted(prop_bones),
        "weightFix": weight_stats,
        "proof": (
            "generated artifact validated (mount horse/rider/prop partition + diag stretch) — "
            "weld + saddle/lance bridge cut + partition weight cleanup; not OE runtime proven"
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


def main() -> int:
    args = _parse()
    src = args.src if args.src.is_absolute() else (ROOT / args.src)
    out = args.out if args.out.is_absolute() else (ROOT / args.out)
    report_path = args.report if args.report.is_absolute() else (ROOT / args.report)
    if not src.is_file():
        print(f"missing source GLB: {src}", file=sys.stderr)
        return 2

    if str(args.species).strip().lower() == "mount":
        return _repair_mount(args, src, out, report_path)

    raw_wb = str(args.weapon_bones or "").strip()
    if not raw_wb:
        weapon_bones = set(DEFAULT_WEAPON_BONES)
    elif raw_wb.lower() in {"mixamo_sword", "mixamo", "crusader_sword"}:
        weapon_bones = set(MIXAMO_SWORD_WEAPON_BONES)
    else:
        weapon_bones = {s.strip() for s in raw_wb.split(",") if s.strip()}
        if not weapon_bones:
            print("fail-closed: --weapon-bones resolved empty", file=sys.stderr)
            return 2
    _clear_scene()
    bpy.ops.import_scene.gltf(filepath=str(src))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    meshes = [o for o in bpy.data.objects if o.type == "MESH"]
    if len(meshes) != 1:
        print(
            f"expected exactly one mesh object for bridge repair, got "
            f"{[(m.name, len(m.data.vertices)) for m in meshes]}",
            file=sys.stderr,
        )
        return 2
    mesh = meshes[0]
    missing_wb = sorted(b for b in weapon_bones if b not in arm.pose.bones)
    if missing_wb:
        print(
            f"fail-closed: weapon bones missing from armature: {missing_wb}",
            file=sys.stderr,
        )
        return 2
    _clear_pose(arm)

    n_faces_before = len(mesh.data.polygons)
    n_verts_before = len(mesh.data.vertices)
    weld_stats = _weld_mesh(mesh, float(args.weld_dist))
    if weld_stats["enabled"] and weld_stats["vertsRemoved"] > 0:
        print(
            f"[bridgefix] weld dist={weld_stats['dist']} "
            f"removed {weld_stats['vertsRemoved']} verts "
            f"({weld_stats['vertsBefore']}→{weld_stats['vertsAfter']}); "
            f"components {weld_stats['componentsBefore']}→{weld_stats['componentsAfter']}",
            flush=True,
        )
        if weld_stats["componentsAfter"] > 50:
            print(
                f"fail-closed: after weld still {weld_stats['componentsAfter']} components "
                f"(expected a coherent surface; top={weld_stats['componentSizesTopAfter']})",
                file=sys.stderr,
            )
            return 2

    labels = _label_verts(
        mesh,
        arm,
        weapon_bones,
        tip_bone=args.tip_bone,
        wrist_bone=args.wrist_bone,
        elbow_bone=args.elbow_bone,
        tip_radius=args.tip_radius,
        shaft_radius=args.shaft_radius,
        tip_end=args.tip_end,
        wrist_end=args.wrist_end,
    )
    n_weapon = sum(1 for x in labels if x == "weapon")
    n_body = sum(1 for x in labels if x == "body")
    if n_weapon < 50:
        print(f"fail-closed: too few weapon verts labeled ({n_weapon})", file=sys.stderr)
        return 2

    tip_probe, _wrist_probe = _weapon_tip_and_wrist(
        arm,
        tip_bone=args.tip_bone,
        wrist_bone=args.wrist_bone,
        tip_end=args.tip_end,
        wrist_end=args.wrist_end,
    )

    chroma_stats: dict = {"enabled": False}
    chroma_faces: set[int] = set()
    chroma_faces_full: set[int] = set()
    chroma_faces_used: set[int] = set()
    chroma_bridge_fallback = False
    if bool(args.chroma):
        chroma_sample = _sample_vert_lab_ab(mesh)
        if not chroma_sample["ok"]:
            print(
                f"fail-closed: chroma sampling failed ({chroma_sample.get('reason')}); "
                f"image={chroma_sample.get('image')!r} sampled={chroma_sample.get('sampled')}",
                file=sys.stderr,
            )
            return 2
        refine = _refine_labels_with_chroma(
            mesh,
            arm,
            labels,
            chroma_sample["labAb"],
            weapon_bones,
            tip_bone=args.tip_bone,
            wrist_bone=args.wrist_bone,
            tip_end=args.tip_end,
            wrist_end=args.wrist_end,
            tip_radius=float(args.tip_radius),
            shaft_radius=float(args.shaft_radius),
            contact_radius=float(args.chroma_contact_radius),
            chroma_margin=float(args.chroma_margin),
        )
        if not refine["ok"]:
            print(
                f"fail-closed: chroma label refine failed ({refine.get('reason')})",
                file=sys.stderr,
            )
            return 2
        labels = refine["labels"]
        n_weapon = sum(1 for x in labels if x == "weapon")
        n_body = sum(1 for x in labels if x == "body")
        if n_weapon < 50:
            print(
                f"fail-closed: after chroma refine too few weapon verts ({n_weapon})",
                file=sys.stderr,
            )
            return 2
        contact_points = [tip_probe]
        sec = str(args.chroma_secondary_tip_bone or "").strip()
        if sec:
            if sec not in arm.pose.bones:
                print(
                    f"fail-closed: chroma secondary tip bone missing: {sec}",
                    file=sys.stderr,
                )
                return 2
            contact_points.append(_bone_head(arm, sec))
        chroma_faces = _bridge_faces_from_chroma(
            mesh,
            labels,
            chroma_sample["labAb"],
            chroma_edge_ab=float(args.chroma_edge_ab),
            tip=tip_probe,
            contact_radius=float(args.chroma_contact_radius),
            contact_points=contact_points,
        )
        chroma_stats = {
            "enabled": True,
            "image": chroma_sample.get("image"),
            "imageSize": chroma_sample.get("imageSize"),
            "sampledVerts": chroma_sample.get("sampled"),
            "weaponProtoAb": refine.get("weaponProtoAb"),
            "bodyProtoAb": refine.get("bodyProtoAb"),
            "protoSeparationAb": refine.get("protoSeparationAb"),
            "weaponSeedCount": refine.get("weaponSeedCount"),
            "bodySeedCount": refine.get("bodySeedCount"),
            "flippedToWeapon": refine.get("flippedToWeapon"),
            "flippedToBody": refine.get("flippedToBody"),
            "contactBandVerts": refine.get("contactBandVerts"),
            "chromaEdgeAb": float(args.chroma_edge_ab),
            "chromaMargin": float(args.chroma_margin),
            "chromaContactRadius": float(args.chroma_contact_radius),
            "chromaSecondaryTipBone": str(args.chroma_secondary_tip_bone or "").strip() or None,
            "skippedPrototypeRefine": bool(refine.get("skippedPrototypeRefine")),
            "skipReason": refine.get("skipReason"),
            "bridgeFacesChroma": len(chroma_faces),
        }
        print(
            f"[bridgefix] chroma image={chroma_stats['image']} "
            f"sampled={chroma_stats['sampledVerts']} "
            f"flippedW={chroma_stats['flippedToWeapon']} "
            f"flippedB={chroma_stats['flippedToBody']} "
            f"chromaFaces={len(chroma_faces)} "
            f"protoSep={chroma_stats['protoSeparationAb']}",
            flush=True,
        )

    mixed = _bridge_faces_from_labels(mesh, labels)
    animation_stretched: set[int] = set()
    animation_stats: dict = {"enabled": False}
    diag_stretched: set[int] = set()
    if args.animation_clips_root is not None:
        clips_root = (
            args.animation_clips_root
            if args.animation_clips_root.is_absolute()
            else (ROOT / args.animation_clips_root)
        )
        clip_paths = _discover_animation_clip_results(clips_root)
        if not clip_paths:
            print(
                f"fail-closed: no gpu_clip_result.json under {clips_root}",
                file=sys.stderr,
            )
            return 2
        animation_stretched, animation_stats = _bridge_faces_from_animation_poses(
            mesh,
            arm,
            labels,
            clip_paths,
            tip_bone=args.tip_bone,
            head_bone=args.head_bone,
            stretch_thresh=args.stretch_thresh,
            stretch_ratio=float(args.stretch_ratio),
            min_frame_score=float(args.animation_min_frame_score),
        )
        if args.animation_distortion_report is not None:
            distortion_report = (
                args.animation_distortion_report
                if args.animation_distortion_report.is_absolute()
                else (ROOT / args.animation_distortion_report)
            )
            distortion_report.parent.mkdir(parents=True, exist_ok=True)
            distortion_report.write_text(
                json.dumps(animation_stats, indent=2) + "\n",
                encoding="utf-8",
            )
        print(
            f"[bridgefix] animation stretch scan: clips={animation_stats['clipsScanned']} "
            f"frames={animation_stats['framesScanned']} "
            f"framesWithHits={animation_stats['framesWithStretchHits']} "
            f"unionFaces={animation_stats['bridgeFacesAnimationUnion']}",
            flush=True,
        )
    if not bool(args.animation_only_stretch):
        _apply_diag_pose(arm, weapon_bones)
        diag_stretched = _bridge_faces_from_stretch(
            mesh,
            arm,
            labels,
            tip_bone=args.tip_bone,
            head_bone=args.head_bone,
            stretch_thresh=args.stretch_thresh,
            stretch_ratio=float(args.stretch_ratio),
        )
        _clear_pose(arm)
    stretched = animation_stretched | diag_stretched

    to_delete = mixed | stretched | chroma_faces
    chroma_faces_full = set(chroma_faces)
    chroma_faces_used = chroma_faces
    chroma_bridge_fallback = False
    frac = len(to_delete) / max(1, len(mesh.data.polygons))
    if len(to_delete) < int(args.min_bridge_faces) and weld_stats.get("vertsRemoved", 0) <= 0:
        print(
            f"fail-closed: found only {len(to_delete)} bridge faces "
            f"(mixed={len(mixed)} stretch={len(stretched)} chroma={len(chroma_faces)}) "
            f"and weld removed 0 verts",
            file=sys.stderr,
        )
        return 2
    if frac > float(args.max_delete_face_frac) and chroma_faces_full:
        chroma_mixed = _chroma_faces_mixed_label_only(mesh, labels, chroma_faces_full)
        fallback_delete = mixed | stretched | chroma_mixed
        fallback_frac = len(fallback_delete) / max(1, len(mesh.data.polygons))
        if fallback_frac <= float(args.max_delete_face_frac):
            chroma_bridge_fallback = True
            chroma_faces_used = chroma_mixed
            to_delete = fallback_delete
            frac = fallback_frac
            print(
                "[bridgefix] chroma bridge fallback: suppressed "
                f"{len(chroma_faces_full) - len(chroma_mixed)} same-label contact "
                f"chroma hits; delete {len(to_delete)}/{len(mesh.data.polygons)} "
                f"({frac:.3f})",
                flush=True,
            )
    if frac > float(args.max_delete_face_frac):
        chroma_mixed = (
            _chroma_faces_mixed_label_only(mesh, labels, chroma_faces_full)
            if chroma_faces_full
            else set()
        )
        lean_delete = mixed | chroma_mixed
        lean_frac = len(lean_delete) / max(1, len(mesh.data.polygons))
        if lean_frac <= float(args.max_delete_face_frac) and len(lean_delete) < len(to_delete):
            chroma_bridge_fallback = chroma_bridge_fallback or bool(chroma_faces_full)
            chroma_faces_used = chroma_mixed if chroma_mixed else chroma_faces_used
            to_delete = lean_delete
            frac = lean_frac
            print(
                "[bridgefix] lean bridge fallback: dropped stretch hits; "
                f"delete {len(to_delete)}/{len(mesh.data.polygons)} ({frac:.3f})",
                flush=True,
            )
    if frac > float(args.max_delete_face_frac) and mixed:
        mixed_only_frac = len(mixed) / max(1, len(mesh.data.polygons))
        if mixed_only_frac <= float(args.max_delete_face_frac) and len(mixed) < len(to_delete):
            to_delete = set(mixed)
            frac = mixed_only_frac
            chroma_faces_used = set()
            print(
                "[bridgefix] mixed-only fallback: dropped stretch/chroma hits; "
                f"delete {len(to_delete)}/{len(mesh.data.polygons)} ({frac:.3f})",
                flush=True,
            )
    if frac > float(args.max_delete_face_frac):
        print(
            f"fail-closed: bridge delete {len(to_delete)}/{len(mesh.data.polygons)} "
            f"({frac:.3f}) exceeds maxDeleteFaceFrac={args.max_delete_face_frac}",
            file=sys.stderr,
        )
        return 2

    deleted = 0
    if to_delete:
        deleted = _delete_faces(mesh, to_delete)
    # Labels are index-based on pre-delete verts; rebuild after topology edits.
    label_kw = dict(
        tip_bone=args.tip_bone,
        wrist_bone=args.wrist_bone,
        elbow_bone=args.elbow_bone,
        tip_radius=args.tip_radius,
        shaft_radius=args.shaft_radius,
        tip_end=args.tip_end,
        wrist_end=args.wrist_end,
    )
    labels_after = _label_verts(mesh, arm, weapon_bones, **label_kw)
    if bool(args.chroma):
        chroma_after = _sample_vert_lab_ab(mesh)
        if chroma_after["ok"]:
            refine_after = _refine_labels_with_chroma(
                mesh,
                arm,
                labels_after,
                chroma_after["labAb"],
                weapon_bones,
                tip_bone=args.tip_bone,
                wrist_bone=args.wrist_bone,
                tip_end=args.tip_end,
                wrist_end=args.wrist_end,
                tip_radius=float(args.tip_radius),
                shaft_radius=float(args.shaft_radius),
                contact_radius=float(args.chroma_contact_radius),
                chroma_margin=float(args.chroma_margin),
            )
            if refine_after["ok"]:
                labels_after = refine_after["labels"]
    weight_stats = _fix_weapon_weights(
        mesh, labels_after, weapon_bones, tip_bone=args.tip_bone
    )
    raw_hb = str(args.head_bones or "").strip()
    if raw_hb:
        head_bones = {s.strip() for s in raw_hb.split(",") if s.strip()}
    elif raw_wb.lower() in {"mixamo_sword", "mixamo", "crusader_sword"}:
        head_bones = {"Head", "neck", "head_end", "headfront"}
    else:
        head_bones = {"Bone_025", "Bone_026", "Bone_014", "Bone_015"}
    tip_probe, _ = _weapon_tip_and_wrist(
        arm,
        tip_bone=args.tip_bone,
        wrist_bone=args.wrist_bone,
        tip_end=args.tip_end,
        wrist_end=args.wrist_end,
    )
    detach_stats = _detach_head_weapon_weights(
        mesh,
        arm,
        weapon_bones,
        tip=tip_probe,
        head_bones=head_bones,
    )

    # Drop tiny debris islands left after bridge cuts (keep largest body + weapon).
    debris_stats = _delete_tiny_components(mesh, min_keep=24)

    labels_after = _label_verts(mesh, arm, weapon_bones, **label_kw)
    comps = _connected_components(mesh)

    # Post-check: tip-near verts that still mix weapon + body weights (true glue).
    # Body-only verts near the resting mace (e.g. hip) are expected — not contamination.
    tip = tip_probe
    vg_index = {g.index: g.name for g in mesh.vertex_groups}
    tip_near = 0
    tip_contam = 0
    for v in mesh.data.vertices:
        co = mesh.matrix_world @ v.co
        if (co - tip).length > 0.22:
            continue
        tip_near += 1
        w_weapon = 0.0
        w_body = 0.0
        for g in v.groups:
            if g.weight <= 0.05:
                continue
            n = vg_index.get(g.group)
            if n in weapon_bones:
                w_weapon += float(g.weight)
            elif n:
                w_body += float(g.weight)
        if w_weapon > 0.05 and w_body > 0.05:
            tip_contam += 1

    # Remaining mixed faces after repair: iterative cleanup within a face budget.
    remain_mixed = _bridge_faces_from_labels(mesh, labels_after)
    second_pass_deleted = 0
    mixed_pass_budget = max(
        32,
        int(len(mesh.data.polygons) * float(args.max_second_pass_mixed_frac)),
    )
    while remain_mixed and second_pass_deleted < mixed_pass_budget:
        batch = remain_mixed
        if len(batch) > mixed_pass_budget - second_pass_deleted:
            break
        second_pass_deleted += _delete_faces(mesh, batch)
        labels_after = _label_verts(mesh, arm, weapon_bones, **label_kw)
        remain_mixed = _bridge_faces_from_labels(mesh, labels_after)

    if remain_mixed and second_pass_deleted:
        print(
            f"[bridgefix] second-pass mixed cleanup deleted {second_pass_deleted} faces; "
            f"remainingMixed={len(remain_mixed)} budget={mixed_pass_budget}",
            flush=True,
        )

    if tip_contam > int(args.max_tip_contam):
        print(
            f"fail-closed: tipNearStillContaminated={tip_contam} "
            f"> maxTipContam={args.max_tip_contam}",
            file=sys.stderr,
        )
        return 2
    if len(remain_mixed) > int(args.max_remaining_mixed_faces):
        print(
            f"fail-closed: remainingMixedLabelFaces={len(remain_mixed)} after delete "
            f"(maxRemainingMixedFaces={args.max_remaining_mixed_faces})",
            file=sys.stderr,
        )
        return 2

    _export(arm, mesh, out)
    report = {
        "ok": True,
        "source": str(src).replace("\\", "/"),
        "output": str(out).replace("\\", "/"),
        "facesBefore": n_faces_before,
        "vertsBefore": n_verts_before,
        "facesAfter": len(mesh.data.polygons),
        "vertsAfter": len(mesh.data.vertices),
        "weld": weld_stats,
        "weaponVertsLabeled": n_weapon,
        "bodyVertsLabeled": n_body,
        "bridgeFacesMixedLabel": len(mixed),
        "bridgeFacesStretch": len(stretched),
        "bridgeFacesStretchDiag": len(diag_stretched),
        "bridgeFacesStretchAnimation": len(animation_stretched),
        "animationDistortion": animation_stats,
        "bridgeFacesChroma": len(chroma_faces_used),
        "bridgeFacesChromaFull": len(chroma_faces_full),
        "chromaBridgeFallback": chroma_bridge_fallback,
        "bridgeFacesUnion": len(to_delete),
        "facesDeleted": deleted,
        "chroma": chroma_stats,
        "remainingMixedLabelFaces": len(remain_mixed),
        "secondPassMixedFacesDeleted": second_pass_deleted,
        "connectedComponents": len(comps),
        "componentSizesTop": [len(c) for c in comps[:12]],
        "debrisCleanup": debris_stats,
        "tipNearAfter": tip_near,
        "tipNearStillContaminated": tip_contam,
        "note": (
            "In-session after weld the mesh is 1–2 components. glTF export/reimport "
            "re-splits verts at UV seams, so on-disk reimport component counts rise again; "
            "consumers should weld-on-load (see blender_ik_markers) for coherent topology."
        ),
        "stretchThresh": args.stretch_thresh,
        "stretchRatio": args.stretch_ratio,
        "maxDeleteFaceFrac": args.max_delete_face_frac,
        "maxTipContam": int(args.max_tip_contam),
        "weaponBones": sorted(weapon_bones),
        "weightFix": weight_stats,
        "headWeaponDetach": detach_stats,
        "proof": (
            "generated artifact validated (texture-chroma label refine/bridge cut) — weld near-duplicates + prop bridge face "
            "delete + weapon weight cleanup; not OE runtime proven"
        ),
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
