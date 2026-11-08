#!/usr/bin/env python3
"""Multi-angle bind-pose joint audit for a Meshy Mixamo master + bone_roles.

Blender (prefer host wrapper run_joint_audit.py):
  blender -b --python render_crusader_joint_audit.py -- \\
    --master <glb> --roles <json> --out <dir> [--sprite <png>]

Fail-closed: duplicate role world positions, missing bones, bbox outliers,
and collapsed LWrist/LElbow (same bone or almost-identical heads).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
from PIL import Image, ImageDraw

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from homm3_pose_camera import setup_pose_camera  # noqa: E402

DEFAULT_MASTER = (
    ROOT
    / "artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/rigged"
    / "idle_f0_rigged_meshy6_bridgefix_hand.glb"
)
DEFAULT_ROLES = TOOL / "bone_roles_crusader_meshy_t2.json"
DEFAULT_SPRITE = (
    ROOT
    / "artifacts/crusader_pose_pipeline/source_frames/nn_upscale_idle_attack/frame_00.png"
)
DEFAULT_OUT = ROOT / "artifacts/crusader_pose_pipeline/out_fit/joint_audit_bind"
W = H = 720
DUP_EPS_M = 0.02

ROLE_COLORS = {
    "Nose": (255, 80, 80),
    "Neck": (255, 160, 80),
    "MidHip": (255, 255, 80),
    "RShoulder": (80, 255, 120),
    "RElbow": (80, 220, 180),
    "RWrist": (80, 200, 255),
    "WeaponTip": (255, 40, 255),
    "LShoulder": (180, 120, 255),
    "LElbow": (200, 150, 255),
    "LWrist": (220, 180, 255),
    "RHip": (120, 200, 120),
    "RKnee": (100, 180, 100),
    "RAnkle": (80, 160, 80),
    "LHip": (120, 160, 220),
    "LKnee": (100, 140, 200),
    "LAnkle": (80, 120, 180),
}


def _argv_after_sep() -> list[str]:
    if "--" in sys.argv:
        return sys.argv[sys.argv.index("--") + 1 :]
    return []


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Bind-pose multi-angle joint audit")
    ap.add_argument("--master", type=Path, default=DEFAULT_MASTER)
    ap.add_argument("--roles", type=Path, default=DEFAULT_ROLES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--sprite", type=Path, default=DEFAULT_SPRITE)
    ap.add_argument("--width", type=int, default=W)
    ap.add_argument("--height", type=int, default=H)
    return ap.parse_args(_argv_after_sep())


def _clear_anim(arm) -> None:
    if arm.animation_data:
        arm.animation_data_clear()
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0.0, 0.0, 0.0)
        pb.location = (0.0, 0.0, 0.0)
        pb.scale = (1.0, 1.0, 1.0)


def _emission_mesh(mesh) -> None:
    for mat in mesh.data.materials:
        if mat is None or not mat.use_nodes:
            continue
        nt = mat.node_tree
        nodes = nt.nodes
        links = nt.links
        outn = next((n for n in nodes if n.type == "OUTPUT_MATERIAL"), None)
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if not outn or not bsdf:
            continue
        base = bsdf.inputs.get("Base Color")
        emit = nodes.new("ShaderNodeEmission")
        emit.inputs["Strength"].default_value = 1.0
        if base is not None and base.is_linked:
            links.new(base.links[0].from_socket, emit.inputs["Color"])
        elif base is not None:
            emit.inputs["Color"].default_value = tuple(base.default_value)
        for link in list(outn.inputs["Surface"].links):
            links.remove(link)
        links.new(emit.outputs["Emission"], outn.inputs["Surface"])


def _project(scene, cam, world_pt, width: int, height: int) -> tuple[float, float, float]:
    c = world_to_camera_view(scene, cam, world_pt)
    return float(c.x * width), float((1.0 - c.y) * height), float(c.z)


def _draw_overlay(
    base: Image.Image,
    *,
    segs: list,
    role_pts: dict,
    label: str,
    height: int,
) -> Image.Image:
    im = base.convert("RGBA")
    over = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(over)
    for name, a, b, opt in segs:
        col = (80, 255, 120, 220) if opt else (90, 130, 190, 120)
        d.line([a, b], fill=col, width=3 if opt else 2)
    for jname, (x, y, depth, bone) in role_pts.items():
        if depth < 0.0 or depth > 1.0:
            continue
        rgb = ROLE_COLORS.get(jname, (255, 255, 255))
        r = 8 if jname == "WeaponTip" else 5
        d.ellipse([x - r, y - r, x + r, y + r], fill=(*rgb, 255), outline=(0, 0, 0, 255))
        d.text((x + r + 2, y - 6), f"{jname}", fill=(*rgb, 255))
    out = Image.alpha_composite(im, over).convert("RGB")
    ImageDraw.Draw(out).text((10, 10), label, fill=(240, 240, 240))
    ImageDraw.Draw(out).text(
        (10, height - 22),
        "green=optimize bones  magenta=WeaponTip  labeled dots=role joints",
        fill=(180, 180, 180),
    )
    return out


def _max_skin_weight(mesh, bone_name: str) -> float:
    vg = mesh.vertex_groups.get(bone_name)
    if vg is None:
        return 0.0
    best = 0.0
    for v in mesh.data.vertices:
        for g in v.groups:
            if g.group == vg.index:
                best = max(best, float(g.weight))
    return best


def main() -> int:
    args = _parse_args()
    master = args.master.resolve()
    roles_path = args.roles.resolve()
    out_dir = args.out.resolve()
    sprite = args.sprite.resolve() if args.sprite else None
    width = int(args.width)
    height = int(args.height)

    if not master.is_file():
        raise SystemExit(f"master missing: {master}")
    if not roles_path.is_file():
        raise SystemExit(f"roles missing: {roles_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    roles = json.loads(roles_path.read_text(encoding="utf-8"))
    joint_map = roles["joints"]
    optimize = set(roles.get("optimizeBones") or [])

    # Fail closed before render if roles deliberately collapse elbow/wrist.
    if joint_map.get("LElbow") and joint_map.get("LWrist") == joint_map.get("LElbow"):
        raise SystemExit(
            "roles map LWrist and LElbow to the same bone "
            f"({joint_map.get('LElbow')}); use LeftHand (or equivalent) for LWrist"
        )

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(master))
    arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
    mesh = next(o for o in bpy.data.objects if o.type == "MESH")
    _clear_anim(arm)
    _emission_mesh(mesh)
    bpy.context.view_layer.update()

    world = bpy.data.worlds.new("W")
    bpy.context.scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes["Background"]
    bg.inputs["Color"].default_value = (0.08, 0.08, 0.10, 1.0)
    bg.inputs["Strength"].default_value = 0.35

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 16
    scene.render.resolution_x = width
    scene.render.resolution_y = height
    scene.render.image_settings.file_format = "PNG"
    scene.render.film_transparent = False

    deps = bpy.context.evaluated_depsgraph_get()
    eval_obj = mesh.evaluated_get(deps)
    eval_mesh = eval_obj.to_mesh()
    try:
        coords = [mesh.matrix_world @ v.co for v in eval_mesh.vertices]
    finally:
        eval_obj.to_mesh_clear()
    xs = [p.x for p in coords]
    ys = [p.y for p in coords]
    zs = [p.z for p in coords]
    bbox = {
        "min": [min(xs), min(ys), min(zs)],
        "max": [max(xs), max(ys), max(zs)],
        "center": [
            0.5 * (min(xs) + max(xs)),
            0.5 * (min(ys) + max(ys)),
            0.5 * (min(zs) + max(zs)),
        ],
    }

    views = [
        (
            "iso_pipeline",
            {
                "axis": "iso",
                "isoAzimuthDeg": 40.0,
                "isoElevationDeg": 30.0,
                "distance": 3.0,
                "orthoScale": 4.2,
                "rootYawDeg": 0.0,
            },
        ),
        (
            "front",
            {
                "axis": "iso",
                "isoAzimuthDeg": 0.0,
                "isoElevationDeg": 12.0,
                "distance": 3.0,
                "orthoScale": 4.2,
                "rootYawDeg": 0.0,
            },
        ),
        (
            "side_right",
            {
                "axis": "iso",
                "isoAzimuthDeg": 90.0,
                "isoElevationDeg": 8.0,
                "distance": 3.0,
                "orthoScale": 4.2,
                "rootYawDeg": 0.0,
            },
        ),
        (
            "three_quarter_back",
            {
                "axis": "iso",
                "isoAzimuthDeg": 140.0,
                "isoElevationDeg": 25.0,
                "distance": 3.0,
                "orthoScale": 4.2,
                "rootYawDeg": 0.0,
            },
        ),
        (
            "topish",
            {
                "axis": "iso",
                "isoAzimuthDeg": 40.0,
                "isoElevationDeg": 70.0,
                "distance": 3.2,
                "orthoScale": 4.2,
                "rootYawDeg": 0.0,
            },
        ),
    ]

    bone_world = {}
    for b in arm.pose.bones:
        bone_world[b.name] = {
            "head": list(arm.matrix_world @ b.head),
            "tail": list(arm.matrix_world @ b.tail),
        }

    role_world = {}
    issues = []
    tip_world = None
    hand = arm.pose.bones.get("RightHand")
    if hand is not None:
        from homm3_landmark_sites import landmark_world as _lw

        try:
            tip_world = _lw(arm, mesh, roles, "WeaponTip")
        except Exception as exc:  # noqa: BLE001 — report as issue
            issues.append({"joint": "WeaponTip", "issue": f"tip_resolve_failed:{exc}"})

    for jname, bname in joint_map.items():
        if jname == "WeaponTip" and tip_world is not None:
            pt = tip_world
            src = "jointSites:WeaponTip"
        else:
            sites = (roles.get("jointSites") or {}).get(jname)
            if sites and "bone" in sites:
                pb = arm.pose.bones.get(str(sites["bone"]))
                if pb is None:
                    issues.append(
                        {
                            "joint": jname,
                            "issue": "missing_site_bone",
                            "bone": sites["bone"],
                        }
                    )
                    continue
                end = str(sites.get("end") or "head")
                pt = arm.matrix_world @ (pb.tail if end == "tail" else pb.head)
                src = f"jointSites:{sites['bone']}.{end}"
                bname = str(sites["bone"])
            else:
                pb = arm.pose.bones.get(bname)
                if pb is None:
                    issues.append({"joint": jname, "issue": "missing_bone", "bone": bname})
                    continue
                pt = arm.matrix_world @ pb.head
                src = f"bone_head:{bname}"
        role_world[jname] = {"xyz": list(pt), "source": src, "bone": bname}
        pad = 0.15
        mn, mx = bbox["min"], bbox["max"]
        outside = [
            a
            for a, v, lo, hi in zip("xyz", pt, mn, mx)
            if v < lo - pad or v > hi + pad
        ]
        if outside:
            issues.append(
                {
                    "joint": jname,
                    "issue": "outside_mesh_bbox",
                    "axes": outside,
                    "xyz": list(pt),
                    "source": src,
                }
            )

    # Duplicate role positions (e.g. LWrist collapsed onto LElbow).
    names = list(role_world.keys())
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            if {a, b} == {"RWrist", "WeaponTip"}:
                continue
            pa = Vector(role_world[a]["xyz"])
            pb = Vector(role_world[b]["xyz"])
            dist = float((pa - pb).length)
            if dist < DUP_EPS_M:
                issues.append(
                    {
                        "issue": "duplicate_role_world_position",
                        "joints": [a, b],
                        "dist": dist,
                        "bones": [role_world[a]["bone"], role_world[b]["bone"]],
                    }
                )

    def _z(j):
        return float(role_world[j]["xyz"][2]) if j in role_world else None

    checks = [
        ("Neck_above_MidHip", _z("Neck"), _z("MidHip"), True),
        ("Nose_above_Neck", _z("Nose"), _z("Neck"), True),
        ("RShoulder_above_RElbow", _z("RShoulder"), _z("RElbow"), True),
        ("RHip_above_RKnee", _z("RHip"), _z("RKnee"), True),
        ("RKnee_above_RAnkle", _z("RKnee"), _z("RAnkle"), True),
        ("LElbow_above_or_near_LWrist", _z("LElbow"), _z("LWrist"), None),
    ]
    for name, a, b, expect_gt in checks:
        if a is None or b is None:
            continue
        if expect_gt is True and not (a > b - 0.02):
            issues.append({"check": name, "issue": "order_fail", "a": a, "b": b})

    if "LElbow" in role_world and "LWrist" in role_world:
        d_lw = float(
            (
                Vector(role_world["LWrist"]["xyz"]) - Vector(role_world["LElbow"]["xyz"])
            ).length
        )
        role_world["LWrist"]["distFromElbow"] = d_lw
        if d_lw < 0.05:
            issues.append(
                {
                    "joint": "LWrist",
                    "issue": "too_close_to_LElbow",
                    "dist": d_lw,
                    "hint": "map LWrist to LeftHand bone head even if LeftHand skin weight is 0",
                }
            )

    if "RWrist" in role_world and "WeaponTip" in role_world:
        rw = Vector(role_world["RWrist"]["xyz"])
        tip = Vector(role_world["WeaponTip"]["xyz"])
        dist = float((tip - rw).length)
        role_world["WeaponTip"]["distFromWrist"] = dist
        if dist < 0.05:
            issues.append({"joint": "WeaponTip", "issue": "too_close_to_wrist", "dist": dist})
        if dist > 1.8:
            issues.append({"joint": "WeaponTip", "issue": "too_far_from_wrist", "dist": dist})

    left_hand_skin = _max_skin_weight(mesh, "LeftHand")
    skin_note = {
        "LeftHandMaxSkinWeight": left_hand_skin,
        "note": (
            "LeftHand may be zero-skinned on Meshy exports; bone head is still valid for LWrist. "
            "IK skinBoneExtras must include LeftForeArm for grab verts."
            if left_hand_skin < 1e-6
            else "LeftHand has skin weights."
        ),
    }

    rendered = []
    for view_name, cam_cfg in views:
        for o in list(bpy.data.objects):
            if o.type == "CAMERA":
                bpy.data.objects.remove(o, do_unlink=True)
        job = {"camera": cam_cfg}
        cam = setup_pose_camera(job, arm, bpy_module=bpy)
        bpy.context.view_layer.update()

        raw_path = out_dir / f"mesh_{view_name}.png"
        scene.render.filepath = str(raw_path)
        bpy.ops.render.render(write_still=True)
        mesh_im = Image.open(raw_path).convert("RGB")

        segs = []
        for b in arm.pose.bones:
            h = arm.matrix_world @ b.head
            t = arm.matrix_world @ b.tail
            hx, hy, _hz = _project(scene, cam, h, width, height)
            tx, ty, _tz = _project(scene, cam, t, width, height)
            segs.append((b.name, (hx, hy), (tx, ty), b.name in optimize))

        role_pts = {}
        for jname, info in role_world.items():
            x, y, z = _project(scene, cam, Vector(info["xyz"]), width, height)
            role_pts[jname] = (x, y, z, info["bone"])

        labeled = _draw_overlay(
            mesh_im,
            segs=segs,
            role_pts=role_pts,
            label=f"bind {view_name}",
            height=height,
        )
        out_path = out_dir / f"joints_{view_name}.png"
        labeled.save(out_path)
        rendered.append(str(out_path).replace("\\", "/"))

    paths = [out_dir / f"joints_{v[0]}.png" for v in views]
    imgs = [Image.open(p).convert("RGB") for p in paths if p.is_file()]
    if imgs:
        cols = 3
        rows = (len(imgs) + cols - 1) // cols
        sheet = Image.new("RGB", (cols * width, rows * height), (10, 10, 12))
        for i, im in enumerate(imgs):
            sheet.paste(im, ((i % cols) * width, (i // cols) * height))
        sheet_path = out_dir / "joints_contact_sheet.png"
        sheet.save(sheet_path)
        rendered.append(str(sheet_path).replace("\\", "/"))

    if sprite is not None and sprite.is_file() and (out_dir / "joints_iso_pipeline.png").is_file():
        sp = Image.open(sprite).convert("RGBA")
        mj = Image.open(out_dir / "joints_iso_pipeline.png").convert("RGB")
        canvas = Image.new("RGB", (width * 2 + 12, height), (0, 0, 0))
        scale = min(width / sp.width, height / sp.height) * 0.92
        nw, nh = max(1, int(sp.width * scale)), max(1, int(sp.height * scale))
        sp2 = sp.resize((nw, nh), Image.Resampling.NEAREST)
        left = Image.new("RGB", (width, height), (0, 0, 0))
        left.paste(sp2.convert("RGB"), ((width - nw) // 2, (height - nh) // 2))
        canvas.paste(left, (0, 0))
        canvas.paste(mj, (width + 12, 0))
        ImageDraw.Draw(canvas).text((8, 8), "sprite f0", fill=(220, 220, 220))
        ImageDraw.Draw(canvas).text(
            (width + 20, 8), "mesh bind + joints (iso)", fill=(220, 220, 220)
        )
        side = out_dir / "sprite_vs_bind_iso.png"
        canvas.save(side)
        rendered.append(str(side).replace("\\", "/"))

    report = {
        "ok": len(issues) == 0,
        "masterGlb": str(master).replace("\\", "/"),
        "roles": str(roles_path).replace("\\", "/"),
        "bbox": bbox,
        "roleJoints": role_world,
        "boneCount": len(bone_world),
        "skinNote": skin_note,
        "issues": issues,
        "renders": rendered,
        "proof": "generated — bind-pose multi-angle joint audit; not OE runtime",
    }
    (out_dir / "joint_audit_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"ok": report["ok"], "issues": issues, "out": str(out_dir).replace("\\", "/")},
            indent=2,
        )
    )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
