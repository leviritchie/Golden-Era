#!/usr/bin/env python3
"""Patch run_hybrid_method_quad.py to v17 upright-cam + root pitch/roll lock."""

from __future__ import annotations

import ast
from pathlib import Path

path = Path(__file__).with_name("run_hybrid_method_quad.py")
text = path.read_text(encoding="utf-8")

text = text.replace(
    'METHOD_ID = "hybrid_v16_dinov3_flyer_maxiou_profile_freeze"',
    'METHOD_ID = "hybrid_v17_dinov3_flyer_upright_root_pitch_freeze"',
)

old_doc_snip = """v16 compound (frugal, <=5 min/clip):
  - DINOv3-dense joint score (geometry terms zeroed; chain-space off)
  - one articulated round + light physics smooth
  - flyers: Move-local wide-roll profile_init; facing_weight=0; rank_metric=iou
    (composite silhouette score preferred diving cameras over max-IoU flight
    silhouettes); freeze root after profile. No geometry polish.
  - ground: normal profile init + full three-axis root search
"""
new_doc_snip = """v17 compound (frugal, <=5 min/clip):
  - DINOv3-dense joint score (geometry terms zeroed; chain-space off)
  - one articulated round + light physics smooth
  - flyers: upright idle profile camera (NOT wide camera-roll — that banks
    world-up onto screen-right = top-down dive on a Y-up standing mesh).
    Compound root camera_forward roll + camera_right pitch lock against Move
    silhouettes (landscape gate); freeze root; DINOv3 joints only.
  - ground: normal profile init + full three-axis root search
"""
if old_doc_snip not in text:
    raise SystemExit("doc snip missing")
text = text.replace(old_doc_snip, new_doc_snip)

old_kw = """        # Flyers: Move-local wide-roll profile_init on Move frames; then FREEZE root.
        # v12 proved DINOv3 root-search undoes the flight roll (~camera_up -56 deg dive).
        "root_search_enabled": (not flyer),
        "root_rotation_axes": (
            ("camera_forward",)
            if flyer
            else ("camera_forward", "camera_right", "camera_up")
        ),
        "root_rotation_camera_up_limit_deg": 45.0,
        "root_rotation_first_frame_limit_deg": 30.0,
        "root_rotation_per_frame_limit_deg": 30.0,
        "root_rotation_defer_camera_up": (not flyer),
        "profile_init_enabled": True,
        "profile_init_camera_basis_mode": "upright_turntable",
        "profile_init_yaw_step_deg": 10.0 if flyer else 15.0,
        "profile_init_roll_range_deg": 90.0 if flyer else 8.0,
        "profile_init_roll_step_deg": 15.0 if flyer else 8.0,
        # Flyers: drop facing bias and rank by pure IoU (composite preferred dive cams).
        "profile_init_facing_weight": 0.0 if flyer else None,
        "profile_init_rank_metric": "iou" if flyer else None,
"""
new_kw = """        # Flyers: upright idle camera + compound root pitch/roll prior; FREEZE root.
        # v16 wide profile roll banks world-up onto screen-right (top-down dive).
        "root_search_enabled": (not flyer),
        "root_rotation_axes": (
            ("camera_forward",)
            if flyer
            else ("camera_forward", "camera_right", "camera_up")
        ),
        "root_rotation_camera_up_limit_deg": 45.0,
        "root_rotation_first_frame_limit_deg": 30.0,
        "root_rotation_per_frame_limit_deg": 30.0,
        "root_rotation_defer_camera_up": (not flyer),
        "profile_init_enabled": (not flyer),
        "profile_init_camera_basis_mode": "upright_turntable",
        "profile_init_yaw_step_deg": 15.0,
        "profile_init_roll_range_deg": 8.0,
        "profile_init_roll_step_deg": 8.0,
        "profile_init_facing_weight": None,
        "profile_init_rank_metric": None,
"""
if old_kw not in text:
    raise SystemExit("kwargs block missing")
text = text.replace(old_kw, new_kw)

old_branch = """    if str(spec["unit_class"]) == "flyer":
        # Default profile_init orients against discovered idle plates; that freezes
        # a standing camera on flight clips. Point orientation at the Move frames.
        move_frames = Path(_sprite_dir(choice))
        culled = Path(str(move_frames) + "_shadow_culled")
        orient_dir = culled if culled.is_dir() else move_frames
        if not orient_dir.is_dir():
            raise RuntimeError(f"{label}: missing Move profile target dir: {orient_dir}")
        gpu_kwargs["profile_init_target_dir"] = orient_dir
        camera_lock["profileInitTargetDir"] = str(orient_dir).replace("\\\\", "/")
        print(f"flyer profile_init_target_dir={orient_dir}", flush=True)
"""
# The file uses single backslash in replace call - match exact
old_branch = """    if str(spec["unit_class"]) == "flyer":
        # Default profile_init orients against discovered idle plates; that freezes
        # a standing camera on flight clips. Point orientation at the Move frames.
        move_frames = Path(_sprite_dir(choice))
        culled = Path(str(move_frames) + "_shadow_culled")
        orient_dir = culled if culled.is_dir() else move_frames
        if not orient_dir.is_dir():
            raise RuntimeError(f"{label}: missing Move profile target dir: {orient_dir}")
        gpu_kwargs["profile_init_target_dir"] = orient_dir
        camera_lock["profileInitTargetDir"] = str(orient_dir).replace("\\", "/")
        print(f"flyer profile_init_target_dir={orient_dir}", flush=True)
"""
new_branch = """    if str(spec["unit_class"]) == "flyer":
        # Upright idle profile camera. Flight attitude comes from compound root
        # roll + pitch against Move silhouettes (not from banking the camera).
        idle_cam = (
            ROOT
            / "artifacts/pose_picker_runs/h3_roc/idle/gpu_cascade_delivery/initialization/profile_camera_fit.json"
        )
        if not idle_cam.is_file():
            raise RuntimeError(f"{label}: missing upright idle profile camera: {idle_cam}")
        config.camera_fit = str(idle_cam)
        move_frames = Path(_sprite_dir(choice))
        culled = Path(str(move_frames) + "_shadow_culled")
        target_dir = culled if culled.is_dir() else move_frames
        if not target_dir.is_dir():
            raise RuntimeError(f"{label}: missing Move silhouette dir: {target_dir}")
        roll_lock = _lock_flyer_roll_by_aspect_iou(
            mesh=mesh,
            camera_fit=idle_cam,
            target_frame_dir=target_dir,
            output_dir=out / "flyer_root_lock",
        )
        root_rot = dict(roll_lock["rootRotation"])
        n_frames = len(tuple(config.frame_indices))
        gpu_kwargs["initial_poses"] = {
            int(i): {MOTION_ROOT_ROTATION_KEY: dict(root_rot)}
            for i in range(n_frames)
        }
        gpu_kwargs["profile_init_enabled"] = False
        camera_lock = {
            "selectedBy": "idle_upright_profile_camera",
            "cameraFit": str(idle_cam).replace("\\\\", "/"),
            "note": "flyer flight from root pitch/roll lock; camera stays upright",
            "rootLock": {
                "rollDeg": roll_lock["rollDeg"],
                "pitchDeg": roll_lock["pitchDeg"],
                "iou": roll_lock["iou"],
                "aspect": roll_lock["aspect"],
                "hybrid": roll_lock["hybrid"],
            },
        }
        print(
            f"flyer upright_cam={idle_cam} root_lock roll={roll_lock['rollDeg']} "
            f"pitch={roll_lock['pitchDeg']} iou={roll_lock['iou']:.3f} "
            f"asp={roll_lock['aspect']:.2f}",
            flush=True,
        )
"""
# Fix the replace string for cameraFit path - use single backslash like the file
new_branch = new_branch.replace(
    'str(idle_cam).replace("\\\\\\\\", "/")',
    'str(idle_cam).replace("\\\\", "/")',
)

if old_branch not in text:
    raise SystemExit("flyer branch missing")
text = text.replace(old_branch, new_branch)

text = text.replace(
    '"note": "flyers use Move-local wide-roll profile_init; idle keep camera not reused"',
    '"note": "flyers use upright idle camera + root pitch/roll lock"',
)
text = text.replace('"schema": "hybrid_method_quad.v16"', '"schema": "hybrid_method_quad.v17"')

# failure blurb — find and replace loosely
old_fail_markers = [
    "v15 facing_weight=0 still ranked by composite",
    "v16 ranks by IoU",
]
# dump if needed
if "v7Failure" in text or "v7Failure" in text:
    pass

# Prefer replacing any long failure string near notes
import re

text2, n = re.subn(
    r'("v7Failure": \(\n)(?:        .*\n)+?(        \),)',
    r'''\1            "v16 max-IoU wide camera-roll still dove: roll=±90 banks world-up onto "
            "screen-right on a standing Y-up mesh. v17 keeps upright idle camera and "
            "puts flight attitude into frozen root pitch/roll."
\2''',
    text,
    count=1,
)
if n == 1:
    text = text2
else:
    # try vFailure key variants
    text2, n = re.subn(
        r'("vFailure": \(\n)(?:        .*\n)+?(        \),)',
        r'''\1            "v16 max-IoU wide camera-roll still dove: roll=±90 banks world-up onto "
            "screen-right on a standing Y-up mesh. v17 keeps upright idle camera and "
            "puts flight attitude into frozen root pitch/roll."
\2''',
        text,
        count=1,
    )
    if n == 1:
        text = text2

old_gate = """    if str(spec["unit_class"]) == "flyer":
        # profile_init knobs are not always echoed into clipResult config; verify via notes knobs.
        knobs = hybrid_kwargs(unit_class="flyer")
        if not bool(knobs.get("profile_init_enabled")):
            raise RuntimeError(f"{label}: flyer hybrid requires profile_init_enabled")
        if float(knobs.get("profile_init_roll_range_deg") or 0.0) < 80.0:
            raise RuntimeError(f"{label}: flyer profile_init_roll_range_deg must be >=80")
        facing_w = knobs.get("profile_init_facing_weight")
        if facing_w is None or float(facing_w) != 0.0:
            raise RuntimeError(f"{label}: flyer profile_init_facing_weight must be 0.0")
        if str(knobs.get("profile_init_rank_metric") or "") != "iou":
            raise RuntimeError(f"{label}: flyer profile_init_rank_metric must be 'iou'")
"""
new_gate = """    if str(spec["unit_class"]) == "flyer":
        knobs = hybrid_kwargs(unit_class="flyer")
        if bool(knobs.get("profile_init_enabled")):
            raise RuntimeError(f"{label}: flyer must skip profile_init and reuse upright idle camera")
        if roll_lock is None:
            raise RuntimeError(f"{label}: flyer requires root pitch/roll lock")
        if float(roll_lock.get("aspect") or 0.0) < 1.15:
            raise RuntimeError(f"{label}: flyer root lock aspect must be landscape (>=1.15)")
"""
if old_gate not in text:
    raise SystemExit("gate block missing")
text = text.replace(old_gate, new_gate)

# notes should include rollLock from roll_lock variable — already does
# Ensure notes schema mentions roll_lock — camera_lock overwrite is fine

path.write_text(text, encoding="utf-8")
ast.parse(text)
print("patched ok")
print([line for line in text.splitlines() if line.startswith("METHOD_ID")][0])
# quick sanity: symbols used exist
for needle in [
    "_lock_flyer_roll_by_aspect_iou",
    "MOTION_ROOT_ROTATION_KEY",
    "config.frame_indices",
    "initial_poses",
    "rootRotation",
]:
    print(needle, text.count(needle))
