#!/usr/bin/env python3
"""
Procedural HoMM3 mount / rider_mount sprite landmarks (no DWPose).

Seeds frame 0 from silhouette geometry (horse nose, rider helmet, lance stripe tip,
four hooves, wrists, saddle). Tracks joints across frames with Lucas–Kanade;
LanceTip uses stripe-color reacquire on large jumps.

Output schema matches dwpose_infer / sprite_landmarks_infer keypoints.json.
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

JOINT_NAMES = [
    "HorseNose",
    "RiderHelmet",
    "LanceTip",
    "LHoofFore",
    "RHoofFore",
    "LHoofHind",
    "RHoofHind",
    "LWrist",
    "RWrist",
    "Saddle",
]

LK_PARAMS = dict(
    winSize=(25, 25),
    maxLevel=4,
    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 40, 0.01),
)

REACQUIRE_JOINTS = {"LanceTip"}


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


def _com_band(mask: np.ndarray, y0: int, y1: int, x0: int = 0, x1: int | None = None) -> tuple[float, float] | None:
    h, w = mask.shape
    x1 = x1 if x1 is not None else w
    band = np.zeros_like(mask)
    band[y0:y1, x0:x1] = mask[y0:y1, x0:x1]
    if not np.any(band):
        return None
    return _com(band)


def _farthest_in_mask(mask: np.ndarray, origin: tuple[float, float]) -> tuple[float, float]:
    ys, xs = np.where(mask)
    if ys.size == 0:
        return origin
    d = (xs.astype(np.float32) - origin[0]) ** 2 + (ys.astype(np.float32) - origin[1]) ** 2
    i = int(np.argmax(d))
    return float(xs[i]), float(ys[i])


def _stripe_mask(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    red = (alpha > 8) & (r > 125) & (g < 95) & (b < 95)
    white = (alpha > 8) & (r > 175) & (g > 175) & (b > 175)
    return (red | white).astype(np.uint8)


def _lance_tip(rgb: np.ndarray, alpha: np.ndarray, saddle: tuple[float, float]) -> tuple[float, float]:
    stripe = _stripe_mask(rgb, alpha)
    ys, xs = np.where(stripe)
    if ys.size > 8:
        # Prefer high + far from saddle along lance axis.
        score = (
            (xs.astype(np.float32) - saddle[0]) ** 2
            + (ys.astype(np.float32) - saddle[1]) ** 2
            + np.maximum(0.0, saddle[1] - ys.astype(np.float32)) * 400.0
        )
        i = int(np.argmax(score))
        return float(xs[i]), float(ys[i])
    mask = alpha > 8
    return _farthest_in_mask(mask, saddle)


def _lowest_point(mask: np.ndarray) -> tuple[float, float] | None:
    ys, xs = np.where(mask)
    if ys.size == 0:
        return None
    i = int(np.argmax(ys))
    return float(xs[i]), float(ys[i])


def extract_landmarks_mount(rgba: np.ndarray, *, facing: str = "right") -> dict[str, dict]:
    alpha = rgba[..., 3]
    rgb = rgba[..., :3]
    mask = alpha > 8
    if not np.any(mask):
        raise RuntimeError("empty sprite alpha")

    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    h = max(1, y1 - y0)
    w = max(1, x1 - x0)
    body = _com(mask)

    saddle = _com_band(mask, y0 + int(0.38 * h), y0 + int(0.58 * h)) or (
        body[0],
        float(y0 + 0.48 * h),
    )
    rider_mask = np.zeros_like(mask)
    rider_mask[y0 : y0 + int(0.32 * h), :] = mask[y0 : y0 + int(0.32 * h), :]
    if np.any(rider_mask):
        rys, rxs = np.where(rider_mask)
        top_i = int(np.argmin(rys))
        rider_helmet = (float(rxs[top_i]), float(rys[top_i]))
    else:
        rider_helmet = _com_band(mask, y0, y0 + int(0.28 * h)) or (
            saddle[0],
            float(y0 + 0.12 * h),
        )

    horse_band_y0 = y0 + int(0.22 * h)
    horse_mask = np.zeros_like(mask)
    horse_mask[horse_band_y0 : y1, :] = mask[horse_band_y0 : y1, :]

    front_is_high_x = facing == "right"
    mid_x = body[0]
    if front_is_high_x:
        horse_nose_band = horse_mask.copy()
        horse_nose_band[:, : int(mid_x)] = False
        horse_head_band = horse_mask.copy()
        horse_head_band[:, int(mid_x) :] = False
        horse_head_band[: y0 + int(0.55 * h), :] = False
    else:
        horse_nose_band = horse_mask.copy()
        horse_nose_band[:, int(mid_x) :] = False
        horse_head_band = horse_mask.copy()
        horse_head_band[:, : int(mid_x)] = False
        horse_head_band[: y0 + int(0.55 * h), :] = False

    horse_nose = _com_band(horse_nose_band, horse_band_y0, y1) or _farthest_in_mask(
        horse_mask, saddle
    )
    if horse_nose_band.any():
        horse_nose = _farthest_in_mask(horse_nose_band, saddle)

    lance_tip = _lance_tip(rgb, alpha, saddle)

    ground_y0 = y0 + int(0.88 * h)
    leg_y0 = y0 + int(0.34 * h)

    if front_is_high_x:
        fore_x0, fore_x1 = int(mid_x), x1
        hind_x0, hind_x1 = x0, int(mid_x)
    else:
        fore_x0, fore_x1 = x0, int(mid_x)
        hind_x0, hind_x1 = int(mid_x), x1

    def _hoof_pair(x0: int, x1: int, y_start: int, y_end: int) -> tuple[tuple[float, float], tuple[float, float]]:
        band = np.zeros_like(mask)
        band[y_start:y_end, x0:x1] = mask[y_start:y_end, x0:x1]
        left = band.copy()
        left[:, int(mid_x) :] = False
        right = band.copy()
        right[:, : int(mid_x)] = False
        lpt = _lowest_point(left) or _lowest_point(band) or (mid_x - 0.1 * w, float(y_end - 2))
        rpt = _lowest_point(right) or _lowest_point(band) or (mid_x + 0.1 * w, float(y_end - 2))
        return lpt, rpt

    # Hind hooves stay on the ground band.
    lhoof_hind, rhoof_hind = _hoof_pair(hind_x0, hind_x1, ground_y0, y1)

    # Fore hooves: planted in ground band when visible, else raised fore-leg band (attack rear).
    fore_ground = np.zeros_like(mask)
    fore_ground[ground_y0:y1, fore_x0:fore_x1] = mask[ground_y0:y1, fore_x0:fore_x1]
    if np.any(fore_ground):
        lhoof_fore, rhoof_fore = _hoof_pair(fore_x0, fore_x1, ground_y0, y1)
    else:
        lhoof_fore, rhoof_fore = _hoof_pair(fore_x0, fore_x1, leg_y0, ground_y0)

    # Wrists: upper-mid band split left/right; right wrist nearer lance base.
    arm_band_y0 = y0 + int(0.30 * h)
    arm_band_y1 = y0 + int(0.62 * h)
    rwrist = _com_band(mask, arm_band_y0, arm_band_y1, int(mid_x), x1) or (
        lance_tip[0] - 0.08 * w,
        float(y0 + 0.45 * h),
    )
    lwrist = _com_band(mask, arm_band_y0, arm_band_y1, x0, int(mid_x)) or (
        horse_nose[0] - 0.02 * w,
        float(y0 + 0.42 * h),
    )

    pts = {
        "HorseNose": horse_nose,
        "RiderHelmet": rider_helmet,
        "LanceTip": lance_tip,
        "LHoofFore": lhoof_fore,
        "RHoofFore": rhoof_fore,
        "LHoofHind": lhoof_hind,
        "RHoofHind": rhoof_hind,
        "LWrist": lwrist,
        "RWrist": rwrist,
        "Saddle": saddle,
    }
    joints = {}
    for name in JOINT_NAMES:
        x, y = pts[name]
        x, y = _snap_to_alpha(alpha, x, y)
        joints[name] = {"x": float(x), "y": float(y), "score": 0.9, "visible": True}
    return joints


def _inside_alpha(alpha: np.ndarray, x: float, y: float) -> bool:
    xi, yi = int(round(x)), int(round(y))
    if yi < 0 or xi < 0 or yi >= alpha.shape[0] or xi >= alpha.shape[1]:
        return False
    return int(alpha[yi, xi]) >= 8


def _snap_to_alpha(alpha: np.ndarray, x: float, y: float, radius: int = 6) -> tuple[float, float]:
    xi, yi = int(round(x)), int(round(y))
    if _inside_alpha(alpha, xi, yi):
        return float(x), float(y)
    h, w = alpha.shape
    best = None
    best_d = 1e18
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            cx, cy = xi + dx, yi + dy
            if cy < 0 or cx < 0 or cy >= h or cx >= w or alpha[cy, cx] < 8:
                continue
            d = float(dx * dx + dy * dy)
            if d < best_d:
                best_d = d
                best = (float(cx), float(cy))
    if best is None:
        return float(x), float(y)
    return best


def _track_frames(
    frame_paths: list[Path],
    seed_joints: dict[str, dict],
    *,
    facing: str = "right",
) -> list[dict[str, dict]]:
    """Per-frame procedural landmarks (no silent LK drift on large DEF jumps)."""
    out: list[dict[str, dict]] = []
    for path in frame_paths:
        rgba = np.array(Image.open(path).convert("RGBA"), dtype=np.uint8)
        alpha = rgba[..., 3]
        joints = extract_landmarks_mount(rgba, facing=facing)
        for name in JOINT_NAMES:
            radius = 16 if "Hoof" in name else 10
            x, y = _snap_to_alpha(alpha, joints[name]["x"], joints[name]["y"], radius=radius)
            joints[name] = {"x": x, "y": y, "score": 0.9, "visible": True}
            if not _inside_alpha(alpha, x, y):
                raise RuntimeError(f"procedural joint {name} off alpha in {path.name}")
        out.append(joints)
    return out


def draw_overlay(rgba: np.ndarray, joints: dict) -> Image.Image:
    im = Image.fromarray(rgba, mode="RGBA").convert("RGB")
    draw = ImageDraw.Draw(im)
    edges = [
        ("Saddle", "RiderHelmet"),
        ("Saddle", "HorseNose"),
        ("RWrist", "LanceTip"),
        ("LWrist", "HorseNose"),
        ("LHoofFore", "RHoofFore"),
        ("LHoofHind", "RHoofHind"),
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

    facing = str((job.get("mountInfer") or {}).get("facing") or "right")
    paths = [Path(fr["path"]) for fr in job["frames"]]

    rgba0 = np.array(Image.open(paths[0]).convert("RGBA"), dtype=np.uint8)
    seed = extract_landmarks_mount(rgba0, facing=facing)
    tracked = _track_frames(paths, seed, facing=facing)

    frames_out = []
    failures = []
    for i, (fr, joints) in enumerate(zip(job["frames"], tracked)):
        src = Path(fr["path"])
        rgba = np.array(Image.open(src).convert("RGBA"), dtype=np.uint8)
        sw, sh = rgba.shape[1], rgba.shape[0]
        overlay = draw_overlay(rgba, joints)
        overlay_path = overlay_dir / f"frame_{i:02d}_overlay.png"
        overlay.save(overlay_path)
        frames_out.append(
            {
                "frameIndex": i,
                "path": str(src),
                "joints": joints,
                "transform": {"srcWidth": sw, "srcHeight": sh},
            }
        )

    payload = {
        "ok": len(failures) == 0,
        "method": "sprite_landmarks_mount",
        "jointNames": JOINT_NAMES,
        "frames": frames_out,
        "failures": failures,
    }
    kpt_path = kpt_dir / "keypoints.json"
    kpt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[mount-infer] wrote {kpt_path} frames={len(frames_out)} failures={len(failures)}", flush=True)
    return payload


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", type=Path, required=True)
    args = ap.parse_args()
    job = _load_job(args.config)
    payload = infer_job(job)
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
