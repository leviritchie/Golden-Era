#!/usr/bin/env python3
"""Digitize high-saturation bone overlays into per-sample joint dicts."""
from __future__ import annotations

import argparse
import colorsys
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from constants import JOINT_ORDER, MANIFEST, OUT, REQUIRED_CORE, SRC  # noqa: E402


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
    min_hsv_sat: float = 0.45,
) -> np.ndarray:
    """Channel-dominance mask that also requires neon-level HSV saturation.

    Olive/moss creature skin is green-dominant but low-sat; without a sat gate it
    floods the lime arm mask and MidHip/leg chaining collapses.
    """
    r, g, b = arr[:, :, 0].astype(np.int16), arr[:, :, 1].astype(np.int16), arr[:, :, 2].astype(np.int16)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    alive = mx >= min_val
    sat = np.zeros(mx.shape, dtype=np.float32)
    nz = mx > 0
    sat[nz] = 1.0 - (mn[nz].astype(np.float32) / mx[nz].astype(np.float32))
    neon = sat >= min_hsv_sat
    if r_dom:
        return alive & neon & (r >= g + margin) & (r >= b + margin)
    if g_dom:
        return alive & neon & (g >= r + margin) & (g >= b + margin)
    if b_dom:
        return alive & neon & (b >= r + margin) & (g >= r + margin) & (np.abs(g - b) < 80)
    raise ValueError("need a dominance flag")


def _mean_saturation(arr: np.ndarray) -> float:
    """Mean HSV saturation of bright non-dark pixels (0..1)."""
    flat = arr.reshape(-1, 3).astype(np.float64) / 255.0
    bright = flat.max(axis=1) > 0.25
    if not np.any(bright):
        return 0.0
    sats = []
    for rgb in flat[bright][:: max(1, bright.sum() // 5000)]:
        sats.append(colorsys.rgb_to_hsv(float(rgb[0]), float(rgb[1]), float(rgb[2]))[1])
    return float(np.mean(sats)) if sats else 0.0


def _blob_centroids(mask: np.ndarray, min_area: int = 8) -> list[tuple[float, float]]:
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


def digitize_one(
    overlay_path: Path,
    *,
    target_size: tuple[int, int] = (512, 512),
    min_mean_sat: float = 0.22,
    min_overlay_coverage: float = 0.003,
) -> dict:
    im = Image.open(overlay_path).convert("RGB").resize(target_size, Image.Resampling.LANCZOS)
    arr = np.asarray(im)
    mean_sat = _mean_saturation(arr)

    cyan_m = _sat_mask(arr, b_dom=True, min_val=90, margin=20, min_hsv_sat=0.40)
    green_m = _sat_mask(arr, g_dom=True, min_val=110, margin=35, min_hsv_sat=0.50)
    pink_m = _sat_mask(arr, r_dom=True, min_val=100, margin=25, min_hsv_sat=0.40)
    # Yellow/orange sticks: tol match + require high sat so brown pants do not win.
    yellow_m = _rgb_mask(arr, (245, 220, 50), 40)
    orange_m = _rgb_mask(arr, (245, 150, 40), 45)
    r16, g16, b16 = arr[:, :, 0].astype(np.int16), arr[:, :, 1].astype(np.int16), arr[:, :, 2].astype(np.int16)
    mx16 = np.maximum(np.maximum(r16, g16), b16)
    mn16 = np.minimum(np.minimum(r16, g16), b16)
    sat16 = np.zeros(mx16.shape, dtype=np.float32)
    nz = mx16 > 0
    sat16[nz] = 1.0 - (mn16[nz].astype(np.float32) / mx16[nz].astype(np.float32))
    yellow_m = yellow_m & (sat16 >= 0.45) & (b16 < 120)
    orange_m = orange_m & (sat16 >= 0.45) & (b16 < 130)
    coverage = float(
        (cyan_m | green_m | pink_m | yellow_m | orange_m).sum() / float(arr.shape[0] * arr.shape[1])
    )
    if mean_sat < min_mean_sat:
        raise RuntimeError(
            f"{overlay_path.name}: mean saturation {mean_sat:.3f} < {min_mean_sat} (fail-closed)"
        )
    if coverage < min_overlay_coverage:
        raise RuntimeError(
            f"{overlay_path.name}: overlay coverage {coverage:.5f} < {min_overlay_coverage} (fail-closed)"
        )

    cyan = _blob_centroids(cyan_m, min_area=5)
    if len(cyan) < 2:
        cyan = _blob_centroids(_rgb_mask(arr, (90, 220, 240), 70), min_area=4)
    green = _blob_centroids(green_m, min_area=6)
    pink = _blob_centroids(pink_m, min_area=6)
    pink = [
        p
        for p in pink
        if int(arr[int(p[1]), int(p[0]), 0]) > int(arr[int(p[1]), int(p[0]), 1]) + 40
    ]
    yellow = _blob_centroids(yellow_m, min_area=8)
    if len(yellow) > 20:
        yellow = _blob_centroids(_rgb_mask(arr, (250, 230, 40), 28), min_area=10)
    orange = _blob_centroids(orange_m, min_area=6)
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

    if not orange:
        raise RuntimeError(f"{overlay_path.name}: no orange mace dots")
    tip = max(orange, key=lambda p: _dist2(p, mid))
    out["WeaponTip"] = tip

    chain_a = _chain_from_anchor(green, neck, 4)
    chain_b = _chain_from_anchor(pink, neck, 4)
    if len(chain_a) < 2 and len(chain_b) < 2:
        raise RuntimeError(
            f"{overlay_path.name}: arm chains too short green={len(green)} pink={len(pink)}"
        )
    if len(chain_a) < 2:
        chain_a, chain_b = chain_b, chain_a
    if len(chain_b) < 2:
        pool = green if len(green) >= len(pink) else pink
        left = [p for p in pool if p[0] < neck[0]]
        right = [p for p in pool if p[0] >= neck[0]]
        chain_a = _chain_from_anchor(right or pool, neck, 4)
        chain_b = _chain_from_anchor(left or pool, neck, 4)

    def distal(chain: list[tuple[float, float]]) -> tuple[float, float]:
        return max(chain, key=lambda p: _dist2(p, neck))

    if _dist2(distal(chain_a), tip) <= _dist2(distal(chain_b), tip):
        strike, support = chain_a, chain_b
    else:
        strike, support = chain_b, chain_a

    def assign_arm(prefix: str, chain: list[tuple[float, float]]) -> None:
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

    missing = [n for n in REQUIRED_CORE if n not in out]
    if missing:
        raise RuntimeError(
            f"{overlay_path.name}: missing {missing}; "
            f"cyan={len(cyan)} green={len(green)} pink={len(pink)} yel={len(yellow)} org={len(orange)}"
        )

    tw, th = target_size
    joints = {}
    for name, (x, y) in out.items():
        joints[name] = {
            "x": float(x),
            "y": float(y),
            "nx": float(x) / tw,
            "ny": float(y) / th,
            "score": 1.0,
            "visible": True,
        }
    return {
        "ok": True,
        "joints": joints,
        "meanSaturation": mean_sat,
        "overlayCoverage": coverage,
        "imageSize": [tw, th],
    }


def discover_overlays(overlays_root: Path) -> list[dict]:
    rows = []
    for path in sorted(overlays_root.glob("f*/**/*.png")):
        # overlays/f00/iso/sample_00.png
        parts = path.relative_to(overlays_root).parts
        if len(parts) != 3:
            continue
        fdir, angle, fname = parts
        if not fdir.startswith("f") or not fname.startswith("sample_"):
            continue
        frame = int(fdir[1:])
        sample = int(Path(fname).stem.split("_")[-1])
        rows.append({"frameIndex": frame, "angle": angle, "sample": sample, "path": path})
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--overlays", type=Path, default=OUT / "overlays")
    ap.add_argument("--out", type=Path, default=OUT / "digitize" / "samples.jsonl")
    args = ap.parse_args()
    if not args.manifest.is_file():
        print(f"missing manifest: {args.manifest}", file=sys.stderr)
        return 2
    rows = discover_overlays(args.overlays)
    if not rows:
        print(f"no overlays under {args.overlays}", file=sys.stderr)
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    ok_n = fail_n = 0
    with args.out.open("w", encoding="utf-8") as fh:
        for row in rows:
            rec = {
                "frameIndex": row["frameIndex"],
                "angle": row["angle"],
                "sample": row["sample"],
                "path": str(row["path"]).replace("\\", "/"),
            }
            try:
                dig = digitize_one(row["path"])
                rec.update(dig)
                ok_n += 1
            except Exception as e:
                rec["ok"] = False
                rec["error"] = str(e)
                fail_n += 1
            fh.write(json.dumps(rec) + "\n")
    summary = {"ok": fail_n == 0, "digitizedOk": ok_n, "digitizedFail": fail_n, "out": str(args.out)}
    (args.out.parent / "digitize_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0 if ok_n > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
