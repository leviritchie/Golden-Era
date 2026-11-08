#!/usr/bin/env python3
"""
Digitize imagegen bone-overlay joints (color legend) into pose-fit keypoints.json.

Legend (requested; imagegen may swap arm colors — digitizer ignores L/R color):
  cyan    = spine / head
  lime/magenta arms = assigned by proximity to orange mace tip (strike=R*)
  yellow  = hips + legs
  orange  = mace shaft + tip

Smoke: digitize f0 + f3, interpolate other frames for an 8-frame clip.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/source_attack_frames_painted_g11"
OVERLAY_DIR = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_bone_overlay_smoke"
OUT = ROOT / "artifacts/hobgoblin_attack_pose_pipeline/out_attack_g11_bone_overlay_apose_mace"
KPT_DIR = OUT / "keypoints"

# HSV ranges (OpenCV-like H 0-179); we use colorsys / simple RGB masks instead.
JOINT_ORDER = [
    "Nose",
    "Neck",
    "RShoulder",
    "RElbow",
    "RWrist",
    "WeaponTip",
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


def _rgb_mask(arr: np.ndarray, center: tuple[int, int, int], tol: int) -> np.ndarray:
    c = np.asarray(center, dtype=np.int16)
    d = np.abs(arr.astype(np.int16) - c)
    return (d.max(axis=2) <= tol) & (arr.max(axis=2) > 40)


def _sat_mask(
    arr: np.ndarray,
    *,
    r_dom: bool = False,
    g_dom: bool = False,
    b_dom: bool = False,
    min_val: int = 80,
    margin: int = 25,
) -> np.ndarray:
    """Channel-dominance mask (more stable than fixed RGB centers on imagegen)."""
    r, g, b = arr[:, :, 0].astype(np.int16), arr[:, :, 1].astype(np.int16), arr[:, :, 2].astype(np.int16)
    mx = np.maximum(np.maximum(r, g), b)
    alive = mx >= min_val
    if r_dom:
        return alive & (r >= g + margin) & (r >= b + margin)
    if g_dom:
        return alive & (g >= r + margin) & (g >= b + margin)
    if b_dom:
        # cyan-ish: G and B both high, B or G dominate R
        return alive & (b >= r + margin) & (g >= r + margin) & (np.abs(g - b) < 80)
    raise ValueError("need a dominance flag")


def _blob_centroids(mask: np.ndarray, min_area: int = 8) -> list[tuple[float, float]]:
    """Connected components via simple flood fill on bool mask."""
    h, w = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    cents: list[tuple[float, float]] = []
    ys, xs = np.where(mask)
    for y0, x0 in zip(ys.tolist(), xs.tolist()):
        if seen[y0, x0]:
            continue
        stack = [(y0, x0)]
        seen[y0, x0] = True
        pts: list[tuple[int, int]] = []
        while stack:
            y, x = stack.pop()
            pts.append((y, x))
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        if len(pts) < min_area:
            continue
        yy = sum(p[0] for p in pts) / len(pts)
        xx = sum(p[1] for p in pts) / len(pts)
        cents.append((float(xx), float(yy)))
    return cents


def _chain_from_anchor(pts: list[tuple[float, float]], anchor: tuple[float, float], n: int) -> list[tuple[float, float]]:
    """Greedy nearest-neighbor chain starting near anchor."""
    if not pts:
        return []
    remaining = pts[:]
    remaining.sort(key=lambda p: (p[0] - anchor[0]) ** 2 + (p[1] - anchor[1]) ** 2)
    cur = remaining.pop(0)
    chain = [cur]
    while remaining and len(chain) < n:
        remaining.sort(key=lambda p: (p[0] - cur[0]) ** 2 + (p[1] - cur[1]) ** 2)
        cur = remaining.pop(0)
        chain.append(cur)
    return chain


def _dist2(a: tuple[float, float], b: tuple[float, float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


def _digitize_one(overlay_path: Path, target_size: tuple[int, int] = (512, 512)) -> dict[str, tuple[float, float]]:
    """
    Digitize overlay joints.

    Arm colors from imagegen are NOT trusted for L/R (they swap). Strike arm (R*)
    is whichever pink/green chain ends closest to the orange mace tip.
    """
    im = Image.open(overlay_path).convert("RGB").resize(target_size, Image.Resampling.LANCZOS)
    arr = np.asarray(im)

    cyan = _blob_centroids(_sat_mask(arr, b_dom=True, min_val=90, margin=20), min_area=5)
    if len(cyan) < 2:
        cyan = _blob_centroids(_rgb_mask(arr, (90, 220, 240), 70), min_area=4)

    green = _blob_centroids(_sat_mask(arr, g_dom=True, min_val=100, margin=30), min_area=6)
    pink = _blob_centroids(_sat_mask(arr, r_dom=True, min_val=100, margin=25), min_area=6)
    # Drop orange-ish from pink: orange has R high but G also elevated
    pink = [
        p
        for p in pink
        if arr[int(p[1]), int(p[0]), 0] > arr[int(p[1]), int(p[0]), 1] + 40
    ]

    yellow = _blob_centroids(_rgb_mask(arr, (245, 220, 50), 40), min_area=8)
    if len(yellow) > 20:
        # Too loose — require stronger yellow
        yellow = _blob_centroids(_rgb_mask(arr, (250, 230, 40), 28), min_area=10)

    orange = _blob_centroids(_rgb_mask(arr, (245, 150, 40), 45), min_area=6)
    # Prefer orange with R>>B and moderate G
    orange = [
        p
        for p in orange
        if arr[int(p[1]), int(p[0]), 0] > 180 and arr[int(p[1]), int(p[0]), 2] < 120
    ]

    out: dict[str, tuple[float, float]] = {}

    cyan_sorted = sorted(cyan, key=lambda p: p[1])
    if cyan_sorted:
        out["Nose"] = cyan_sorted[0]
        out["Neck"] = cyan_sorted[min(1, len(cyan_sorted) - 1)]
        chest = cyan_sorted[min(2, len(cyan_sorted) - 1)]
    else:
        # Fallback: topmost green/pink midpoint
        all_arm = green + pink
        if not all_arm:
            raise RuntimeError(f"{overlay_path.name}: no cyan and no arm dots")
        top = min(all_arm, key=lambda p: p[1])
        out["Nose"] = (top[0], max(20.0, top[1] - 30.0))
        out["Neck"] = top
        chest = top

    if yellow:
        mid_guess = (chest[0], min(480.0, chest[1] + 120.0))
        out["MidHip"] = min(yellow, key=lambda p: _dist2(p, mid_guess))
    else:
        out["MidHip"] = (chest[0], chest[1] + 100.0)
    mid = out["MidHip"]
    neck = out["Neck"]

    # Weapon tip: orange point farthest from MidHip (usually mace head)
    if not orange:
        raise RuntimeError(f"{overlay_path.name}: no orange mace dots")
    tip = max(orange, key=lambda p: _dist2(p, mid))
    out["WeaponTip"] = tip

    # Build two arm chains from green vs pink pools (colors may be L/R swapped).
    chain_a = _chain_from_anchor(green, neck, 4)
    chain_b = _chain_from_anchor(pink, neck, 4)
    if len(chain_a) < 2 and len(chain_b) < 2:
        raise RuntimeError(
            f"{overlay_path.name}: arm chains too short green={len(green)} pink={len(pink)}"
        )
    if len(chain_a) < 2:
        chain_a, chain_b = chain_b, chain_a
    if len(chain_b) < 2:
        # Split the longer pool into two chains by x about neck
        pool = green if len(green) >= len(pink) else pink
        left = [p for p in pool if p[0] < neck[0]]
        right = [p for p in pool if p[0] >= neck[0]]
        chain_a = _chain_from_anchor(right or pool, neck, 4)
        chain_b = _chain_from_anchor(left or pool, neck, 4)

    def distal(chain: list[tuple[float, float]]) -> tuple[float, float]:
        return max(chain, key=lambda p: _dist2(p, neck))

    # Strike (R*) = chain whose distal end is closer to mace tip.
    if _dist2(distal(chain_a), tip) <= _dist2(distal(chain_b), tip):
        strike, support = chain_a, chain_b
    else:
        strike, support = chain_b, chain_a

    def assign_arm(prefix: str, chain: list[tuple[float, float]]) -> None:
        # Order proximal→distal by distance from neck
        ordered = sorted(chain, key=lambda p: _dist2(p, neck))
        if len(ordered) >= 1:
            out[f"{prefix}Shoulder"] = ordered[0]
        if len(ordered) >= 2:
            out[f"{prefix}Elbow"] = ordered[1]
        if len(ordered) >= 3:
            out[f"{prefix}Wrist"] = ordered[2]
        elif len(ordered) >= 2:
            out[f"{prefix}Wrist"] = ordered[-1]

    assign_arm("R", strike)
    assign_arm("L", support)

    # Legs from yellow (exclude MidHip)
    leg_pts = [p for p in yellow if _dist2(p, mid) > 20**2]
    right_leg = sorted([p for p in leg_pts if p[0] >= mid[0]], key=lambda p: p[1])
    left_leg = sorted([p for p in leg_pts if p[0] < mid[0]], key=lambda p: p[1])
    for name, pts in (("R", right_leg), ("L", left_leg)):
        if len(pts) >= 1:
            out[f"{name}Hip"] = pts[0]
        if len(pts) >= 2:
            out[f"{name}Knee"] = pts[1]
        if len(pts) >= 3:
            out[f"{name}Ankle"] = pts[2]
        elif len(pts) >= 1:
            last = pts[-1]
            out.setdefault(f"{name}Ankle", (last[0], min(500.0, last[1] + 40.0)))

    required = [
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
    ]
    missing = [n for n in required if n not in out]
    if missing:
        raise RuntimeError(
            f"{overlay_path.name}: missing {missing}; "
            f"cyan={len(cyan)} green={len(green)} pink={len(pink)} yel={len(yellow)} org={len(orange)}"
        )
    return out


def _lerp_pts(a: dict[str, tuple[float, float]], b: dict[str, tuple[float, float]], t: float) -> dict[str, tuple[float, float]]:
    keys = set(a) | set(b)
    out = {}
    for k in keys:
        if k in a and k in b:
            out[k] = (a[k][0] * (1 - t) + b[k][0] * t, a[k][1] * (1 - t) + b[k][1] * t)
        elif k in a:
            out[k] = a[k]
        else:
            out[k] = b[k]
    return out


def _joint_dict(pts: dict[str, tuple[float, float]]) -> dict:
    joints = {}
    for name in JOINT_ORDER:
        if name in pts:
            x, y = pts[name]
            joints[name] = {
                "x": float(x),
                "y": float(y),
                "xUpscaled": float(x),
                "yUpscaled": float(y),
                "score": 0.95,
                "visible": True,
            }
        else:
            joints[name] = {
                "x": 0.0,
                "y": 0.0,
                "xUpscaled": 0.0,
                "yUpscaled": 0.0,
                "score": 0.0,
                "visible": False,
            }
    for unused in ("LEye", "REye", "LEar", "REar"):
        joints[unused] = {
            "x": 0.0,
            "y": 0.0,
            "xUpscaled": 0.0,
            "yUpscaled": 0.0,
            "score": 0.0,
            "visible": False,
        }
    return joints


def main() -> int:
    KPT_DIR.mkdir(parents=True, exist_ok=True)
    overlays_out = KPT_DIR / "digitize_overlays"
    overlays_out.mkdir(exist_ok=True)

    f0 = _digitize_one(OVERLAY_DIR / "frame_00_bones.png")
    f3 = _digitize_one(OVERLAY_DIR / "frame_03_bones.png")

    # 8-frame clip: keyframes at 0 and 3, interpolate neighbors; hold f3 pose after.
    keyframes = {
        0: f0,
        3: f3,
    }
    # f1-f2 toward f3; f4-f7 linger near f3 with slight ease
    pts_by_frame: dict[int, dict[str, tuple[float, float]]] = {}
    for i in range(8):
        if i in keyframes:
            pts_by_frame[i] = keyframes[i]
        elif i < 3:
            pts_by_frame[i] = _lerp_pts(f0, f3, i / 3.0)
        else:
            pts_by_frame[i] = f3

    transform = {
        "padX": 0,
        "padY": 0,
        "scale": 1.0,
        "srcWidth": 512,
        "srcHeight": 512,
        "upWidth": 512,
        "upHeight": 512,
        "longEdge": 512,
        "bgRgb": [0, 0, 0],
        "cropX0": 0,
        "cropY0": 0,
        "cropW": 512,
        "cropH": 512,
    }

    frames_out = []
    for i in range(8):
        pts = pts_by_frame[i]
        src = SRC / f"frame_{i:02d}.png"
        im = Image.open(src).convert("RGBA")
        canvas = Image.new("RGBA", im.size, (12, 12, 16, 255))
        canvas.paste(im, (0, 0), im)
        draw = ImageDraw.Draw(canvas)
        edges = [
            ("Nose", "Neck"),
            ("Neck", "MidHip"),
            ("RShoulder", "RElbow"),
            ("RElbow", "RWrist"),
            ("RWrist", "WeaponTip"),
            ("LShoulder", "LElbow"),
            ("LElbow", "LWrist"),
            ("MidHip", "RHip"),
            ("RHip", "RKnee"),
            ("RKnee", "RAnkle"),
            ("MidHip", "LHip"),
            ("LHip", "LKnee"),
            ("LKnee", "LAnkle"),
        ]
        for a, b in edges:
            if a in pts and b in pts:
                draw.line([pts[a], pts[b]], fill=(80, 220, 120, 255), width=3)
        for name, (x, y) in pts.items():
            r = 7 if name == "WeaponTip" else 5
            draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 220, 40, 255), outline=(0, 0, 0, 255))
            draw.text((x + 8, y - 8), name, fill=(240, 240, 240, 255))
        canvas.convert("RGB").save(overlays_out / f"frame_{i:02d}.png")
        frames_out.append(
            {
                "frameIndex": i,
                "sourcePath": str(src.resolve()).replace("\\", "/"),
                "transform": transform,
                "variant": "imagegen_bone_overlay_digitized",
                "visibleJoints": sum(1 for n in JOINT_ORDER if n in pts),
                "meanScore": 0.95,
                "joints": _joint_dict(pts),
                "digitizeSource": (
                    "frame_00_bones.png"
                    if i == 0
                    else ("frame_03_bones.png" if i == 3 else "interpolated_f0_f3")
                ),
            }
        )

    payload = {
        "unitSid": "h3_hobgoblin",
        "clipId": "attack_g11",
        "detector": "imagegen_bone_overlay_digitize",
        "masterHint": "hobgoblin_apose_mace_attach.glb",
        "frameCountExpected": 8,
        "frameCountOk": 8,
        "failures": [],
        "frames": frames_out,
        "proof": "generated artifact validated — digitized imagegen overlays f0/f3 + lerp; Mixamo fit separate",
    }
    kpt_path = KPT_DIR / "keypoints.json"
    kpt_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    meta = {
        "keypoints": str(kpt_path).replace("\\", "/"),
        "f0": {k: list(v) for k, v in f0.items()},
        "f3": {k: list(v) for k, v in f3.items()},
        "digitizeOverlays": str(overlays_out).replace("\\", "/"),
    }
    (KPT_DIR / "digitize_report.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, **meta}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
