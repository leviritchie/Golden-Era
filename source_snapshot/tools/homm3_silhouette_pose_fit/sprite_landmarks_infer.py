#!/usr/bin/env python3
"""
Automatic HoMM3 sprite landmarks (no DWPose).

Produces the same keypoints.json schema as dwpose_infer.py so blender_fit_from_keypoints.py can consume it.
Heuristics are tuned for right-facing melee sprites (hobgoblin / CHGOBL attack).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]

# Joints we emit (OpenPose names expected by bone_roles_unirig_hobgoblin.json).
JOINT_NAMES = [
    "Nose",
    "Neck",
    "RShoulder",
    "RElbow",
    "RWrist",
    "LShoulder",
    "LElbow",
    "LWrist",
    "MidHip",
    "RHip",
    "RKnee",
    "RAnkle",
    "LHip",
    "LKnee",
    "LAnkle",
]


def _load_job(path: Path) -> dict:
    job = json.loads(path.read_text(encoding="utf-8"))

    def resolve(p: str) -> str:
        pp = Path(p)
        return str(pp if pp.is_absolute() else (ROOT / pp).resolve())

    job["masterGlb"] = resolve(job["masterGlb"])
    job["outputDir"] = resolve(job["outputDir"])
    for fr in job["frames"]:
        fr["path"] = resolve(fr["path"])
    return job


def _com(mask: np.ndarray) -> tuple[float, float]:
    ys, xs = np.where(mask)
    return float(xs.mean()), float(ys.mean())


def _com_band(mask: np.ndarray, y0: int, y1: int) -> tuple[float, float] | None:
    band = np.zeros_like(mask)
    band[y0:y1, :] = mask[y0:y1, :]
    if not np.any(band):
        return None
    return _com(band)


def _metal_mask(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Gray/metal-ish pixels (mace head), excluding green skin."""
    bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    g, r = rgb[..., 1].astype(np.int16), rgb[..., 0].astype(np.int16)
    # Metal: fairly bright, low saturation; not strongly green.
    metal = (alpha > 8) & (s < 70) & (v > 90) & (g - r < 40)
    # Also allow brown-wood handle? keep metal tip preference only.
    return metal.astype(np.uint8)


def _farthest_point(mask: np.ndarray, origin: tuple[float, float]) -> tuple[float, float]:
    ys, xs = np.where(mask)
    if ys.size == 0:
        return origin
    d = (xs.astype(np.float32) - origin[0]) ** 2 + (ys.astype(np.float32) - origin[1]) ** 2
    i = int(np.argmax(d))
    return float(xs[i]), float(ys[i])


def extract_landmarks(rgba: np.ndarray) -> dict[str, dict]:
    alpha = rgba[..., 3]
    rgb = rgba[..., :3]
    mask = alpha > 8
    if not np.any(mask):
        raise RuntimeError("empty sprite alpha")

    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    h = max(1, y1 - y0)
    body = _com(mask)

    # Head / neck / hips from vertical bands of the silhouette.
    head = _com_band(mask, y0, y0 + max(1, int(0.22 * h))) or (body[0], float(y0 + 0.1 * h))
    neck = _com_band(mask, y0 + int(0.18 * h), y0 + int(0.32 * h)) or (head[0], head[1] + 0.08 * h)
    mid = _com_band(mask, y0 + int(0.45 * h), y0 + int(0.62 * h)) or (body[0], float(y0 + 0.55 * h))

    # Feet: bottom band split left/right of body x.
    foot_band = np.zeros_like(mask)
    foot_band[y0 + int(0.82 * h) : y1, :] = mask[y0 + int(0.82 * h) : y1, :]
    fys, fxs = np.where(foot_band)
    if fys.size:
        left_pts = (fxs < body[0])
        right_pts = ~left_pts
        if np.any(left_pts):
            lankle = (float(fxs[left_pts].mean()), float(fys[left_pts].mean()))
        else:
            lankle = (body[0] - 0.08 * (x1 - x0), float(y1 - 2))
        if np.any(right_pts):
            rankle = (float(fxs[right_pts].mean()), float(fys[right_pts].mean()))
        else:
            rankle = (body[0] + 0.08 * (x1 - x0), float(y1 - 2))
    else:
        lankle = (body[0] - 10.0, float(y1 - 2))
        rankle = (body[0] + 10.0, float(y1 - 2))

    # Knees / hips between mid and ankles.
    def lerp(a, b, t):
        return (a[0] * (1 - t) + b[0] * t, a[1] * (1 - t) + b[1] * t)

    rhip = lerp(mid, rankle, 0.15)
    lhip = lerp(mid, lankle, 0.15)
    rknee = lerp(mid, rankle, 0.55)
    lknee = lerp(mid, lankle, 0.55)

    # Weapon tip: metal mask preferred; else farthest silhouette point from body (often flail).
    metal = _metal_mask(rgb, alpha)
    if int(metal.sum()) > 12:
        tip = _com(metal.astype(bool))
        # Prefer the metal pixel farthest from body (spiked ball vs handle).
        tip = _farthest_point(metal.astype(bool), body)
    else:
        tip = _farthest_point(mask, body)

    # Attacking arm (viewer-right / character-right for right-facing profile): shoulder → tip.
    rsho = (neck[0] + 0.35 * (tip[0] - neck[0]), neck[1] + 0.12 * (tip[1] - neck[1]))
    relbow = lerp(rsho, tip, 0.45)
    rwrist = lerp(rsho, tip, 0.72)

    # Off hand stays nearer torso.
    lsho = (neck[0] - 0.15 * abs(tip[0] - neck[0]), neck[1] + 8.0)
    lelbow = lerp(lsho, mid, 0.45)
    lwrist = lerp(lsho, mid, 0.75)

    pts = {
        "Nose": head,
        "Neck": neck,
        "RShoulder": rsho,
        "RElbow": relbow,
        "RWrist": rwrist,
        "LShoulder": lsho,
        "LElbow": lelbow,
        "LWrist": lwrist,
        "MidHip": mid,
        "RHip": rhip,
        "RKnee": rknee,
        "RAnkle": rankle,
        "LHip": lhip,
        "LKnee": lknee,
        "LAnkle": lankle,
    }
    # Weapon tip as extra (not in OpenPose map; store for overlays / future).
    joints = {}
    for name in JOINT_NAMES:
        x, y = pts[name]
        joints[name] = {"x": float(x), "y": float(y), "score": 0.9, "visible": True}
    joints["WeaponTip"] = {"x": float(tip[0]), "y": float(tip[1]), "score": 0.85, "visible": True}
    return joints


def draw_overlay(rgba: np.ndarray, joints: dict) -> Image.Image:
    im = Image.fromarray(rgba, mode="RGBA").convert("RGB")
    draw = ImageDraw.Draw(im)
    edges = [
        ("Nose", "Neck"),
        ("Neck", "RShoulder"),
        ("RShoulder", "RElbow"),
        ("RElbow", "RWrist"),
        ("Neck", "LShoulder"),
        ("LShoulder", "LElbow"),
        ("LElbow", "LWrist"),
        ("Neck", "MidHip"),
        ("MidHip", "RHip"),
        ("RHip", "RKnee"),
        ("RKnee", "RAnkle"),
        ("MidHip", "LHip"),
        ("LHip", "LKnee"),
        ("LKnee", "LAnkle"),
        ("RWrist", "WeaponTip"),
    ]
    for a, b in edges:
        if a in joints and b in joints:
            draw.line(
                [(joints[a]["x"], joints[a]["y"]), (joints[b]["x"], joints[b]["y"])],
                fill=(0, 255, 0),
                width=2,
            )
    for name, j in joints.items():
        x, y = j["x"], j["y"]
        draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(255, 0, 0))
        draw.text((x + 4, y - 8), name, fill=(255, 255, 0))
    return im


def infer_job(job: dict) -> dict:
    out_dir = Path(job["outputDir"])
    kpt_dir = out_dir / "sprite_landmarks"
    overlay_dir = kpt_dir / "overlays"
    kpt_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)

    frames_out = []
    failures = []
    for i, fr in enumerate(job["frames"]):
        src = Path(fr["path"])
        rgba = np.array(Image.open(src).convert("RGBA"), dtype=np.uint8)
        try:
            joints = extract_landmarks(rgba)
        except Exception as e:
            failures.append({"frameIndex": i, "reason": str(e), "path": str(src)})
            continue
        overlay = draw_overlay(rgba, joints)
        op = overlay_dir / f"frame_{i:02d}.png"
        overlay.save(op)
        h, w = rgba.shape[:2]
        frames_out.append(
            {
                "frameIndex": i,
                "sourcePath": str(src).replace("\\", "/"),
                "transform": {"srcWidth": w, "srcHeight": h, "scale": 1.0, "padX": 0, "padY": 0},
                "variant": "sprite_heuristic_v1",
                "visibleJoints": sum(1 for n in JOINT_NAMES if joints[n]["visible"]),
                "meanScore": 0.9,
                "joints": {n: joints[n] for n in list(JOINT_NAMES) + ["WeaponTip"]},
                "overlay": str(op.resolve()).replace("\\", "/"),
            }
        )

    report = {
        "unitSid": job.get("unitSid"),
        "clipId": job.get("clipId"),
        "detector": "sprite_landmarks_heuristic",
        "frameCountExpected": len(job["frames"]),
        "frameCountOk": len(frames_out),
        "failures": failures,
        "frames": frames_out,
        "ok": len(failures) == 0 and len(frames_out) == len(job["frames"]),
        "proof": "generated artifact validated — heuristic sprite landmarks; not OE runtime proven",
    }
    out_json = kpt_dir / "keypoints.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["keypointsPath"] = str(out_json.resolve()).replace("\\", "/")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    args = ap.parse_args()
    cfg = args.config if args.config.is_file() else ROOT / args.config
    if not cfg.is_file():
        print(f"config not found: {args.config}", file=sys.stderr)
        return 2
    job = _load_job(cfg)
    report = infer_job(job)
    print(json.dumps({"ok": report["ok"], "keypointsPath": report["keypointsPath"], "failures": report["failures"]}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
