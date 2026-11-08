#!/usr/bin/env python3
"""
Cheap Roc-move pilot: project UniRig rest skeleton onto RIFE frames, LK-track
with previous-frame continuity, draw stick overlays, emit keypoints + GIF.

Seed is a similarity fit of orthographic bone XY onto frame-0 silhouette AABB.
Not authorship — pilot only for iteration speed.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
PREVIEW_GIF_FRAME_MS = 180

LK_PARAMS = dict(
    winSize=(21, 21),
    maxLevel=3,
    criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
)


def _load_rgba(path: Path) -> np.ndarray:
    return np.asarray(Image.open(path).convert("RGBA"))


def _alpha_bbox(alpha: np.ndarray, thr: int = 8) -> tuple[int, int, int, int]:
    ys, xs = np.where(alpha >= thr)
    if len(xs) == 0:
        raise RuntimeError("empty alpha")
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _nn_upscale_rgba(rgba: np.ndarray, scale: int) -> np.ndarray:
    if scale == 1:
        return rgba
    h, w = rgba.shape[:2]
    return np.asarray(
        Image.fromarray(rgba, "RGBA").resize((w * scale, h * scale), Image.NEAREST)
    )


def _project_bones_ortho(bones: list[dict], mode: str) -> dict[str, tuple[float, float]]:
    """Drop one axis to get a 2D rest layout. Y-up Meshy: side uses (Z,Y), front (X,Y)."""
    out: dict[str, tuple[float, float]] = {}
    for b in bones:
        x, y, z = b["world"]
        if mode == "side_zy":
            # HoMM3 battle faces +X screen-right; Meshy bird beak ~+Z → map Z→u, Y→v
            u, v = float(z), float(y)
        elif mode == "side_xy":
            u, v = float(x), float(y)
        elif mode == "top_xz":
            u, v = float(x), float(z)
        else:
            raise ValueError(mode)
        out[b["name"]] = (u, v)
    return out


def _fit_similarity(
    pts: dict[str, tuple[float, float]],
    bbox: tuple[int, int, int, int],
    *,
    flip_u: bool = False,
    flip_v: bool = True,
    pad: float = 0.06,
) -> dict[str, tuple[float, float]]:
    names = list(pts.keys())
    arr = np.array([pts[n] for n in names], dtype=np.float64)
    if flip_u:
        arr[:, 0] *= -1.0
    if flip_v:
        arr[:, 1] *= -1.0
    mn = arr.min(axis=0)
    mx = arr.max(axis=0)
    span = np.maximum(mx - mn, 1e-6)
    x0, y0, x1, y1 = bbox
    bw = max(1.0, float(x1 - x0))
    bh = max(1.0, float(y1 - y0))
    # letterbox into bbox with pad
    inner_w = bw * (1.0 - 2.0 * pad)
    inner_h = bh * (1.0 - 2.0 * pad)
    s = min(inner_w / span[0], inner_h / span[1])
    cx = 0.5 * (x0 + x1)
    cy = 0.5 * (y0 + y1)
    mid = 0.5 * (mn + mx)
    out: dict[str, tuple[float, float]] = {}
    for i, n in enumerate(names):
        p = (arr[i] - mid) * s
        out[n] = (float(cx + p[0]), float(cy + p[1]))
    return out


def _clamp_to_alpha(x: float, y: float, alpha: np.ndarray, search: int = 12) -> tuple[float, float]:
    h, w = alpha.shape
    xi, yi = int(round(x)), int(round(y))
    if 0 <= xi < w and 0 <= yi < h and alpha[yi, xi] >= 8:
        return float(xi), float(yi)
    best = None
    best_d = 1e18
    for dy in range(-search, search + 1):
        for dx in range(-search, search + 1):
            xx, yy = xi + dx, yi + dy
            if 0 <= xx < w and 0 <= yy < h and alpha[yy, xx] >= 8:
                d = dx * dx + dy * dy
                if d < best_d:
                    best_d = d
                    best = (float(xx), float(yy))
    if best is None:
        return float(np.clip(xi, 0, w - 1)), float(np.clip(yi, 0, h - 1))
    return best


def _track_lk(
    prev_gray: np.ndarray,
    next_gray: np.ndarray,
    prev_pts: dict[str, tuple[float, float]],
    next_alpha: np.ndarray,
) -> dict[str, tuple[float, float]]:
    names = list(prev_pts.keys())
    p0 = np.array([[prev_pts[n]] for n in names], dtype=np.float32)
    p1, st, _err = cv2.calcOpticalFlowPyrLK(prev_gray, next_gray, p0, None, **LK_PARAMS)
    # backward check
    p0r, st_b, _ = cv2.calcOpticalFlowPyrLK(next_gray, prev_gray, p1, None, **LK_PARAMS)
    out: dict[str, tuple[float, float]] = {}
    for i, n in enumerate(names):
        ok = bool(st[i, 0]) and bool(st_b[i, 0])
        if ok:
            fb = float(np.linalg.norm(p0[i, 0] - p0r[i, 0]))
            if fb > 6.0:
                ok = False
        if ok:
            x, y = float(p1[i, 0, 0]), float(p1[i, 0, 1])
        else:
            # hold previous (continuity) then snap to alpha
            x, y = prev_pts[n]
        out[n] = _clamp_to_alpha(x, y, next_alpha)
    return out


def _bone_color(name: str) -> tuple[int, int, int]:
    # cheap semantic coloring by bone index digit
    try:
        n = int(name.split("_")[-1])
    except Exception:
        n = 0
    if n <= 1:
        return (0, 255, 255)  # root cyan
    if n in {2, 3, 17, 18, 19, 26, 27, 28, 29}:
        return (0, 255, 255)  # spine/head cyan
    if n in {20, 21, 22, 30, 31, 32, 33, 34, 35, 36, 37}:
        return (255, 64, 255)  # left wing magenta
    if n in {23, 24, 25, 38, 39, 40, 41, 42, 43, 44, 45}:
        return (64, 255, 64)  # right wing lime
    if n in {4, 5, 6}:
        return (255, 200, 0)  # tail orange
    if n in {7, 8, 9, 10, 11}:
        return (255, 255, 0)  # leg A yellow
    if n in {12, 13, 14, 15, 16}:
        return (255, 160, 0)  # leg B
    return (200, 200, 200)


def _draw_overlay(
    rgba: np.ndarray,
    joints: dict[str, tuple[float, float]],
    edges: list[dict],
    label: str,
) -> Image.Image:
    base = Image.fromarray(rgba, "RGBA").convert("RGB")
    # composite on dark checker so transparent pads read clearly
    bg = Image.new("RGB", base.size, (18, 18, 22))
    a = Image.fromarray(rgba[:, :, 3], "L")
    bg.paste(base, mask=a)
    dr = ImageDraw.Draw(bg)
    for e in edges:
        a_n, b_n = e["parentName"], e["childName"]
        if a_n not in joints or b_n not in joints:
            continue
        x0, y0 = joints[a_n]
        x1, y1 = joints[b_n]
        col = _bone_color(b_n)
        dr.line([(x0, y0), (x1, y1)], fill=col, width=2)
    for name, (x, y) in joints.items():
        col = _bone_color(name)
        r = 3
        dr.ellipse([x - r, y - r, x + r, y + r], fill=col, outline=(0, 0, 0))
    dr.text((6, 4), label, fill=(240, 240, 240))
    return bg


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skeleton", type=Path, required=True)
    ap.add_argument("--frames-dir", type=Path, required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--nn-scale", type=int, default=3)
    ap.add_argument("--proj-mode", default="side_zy", choices=["side_zy", "side_xy", "top_xz"])
    ap.add_argument("--flip-u", action="store_true", default=False)
    ap.add_argument("--no-flip-v", action="store_true", default=False)
    ap.add_argument(
        "--seed-json",
        type=Path,
        default=None,
        help="Optional eye-authored f0 joints JSON ({joints:{name:{x,y}}}). Skips ortho AABB seed.",
    )
    args = ap.parse_args()

    skel = json.loads(args.skeleton.read_text(encoding="utf-8"))
    bones = skel["bones"]
    edges = skel["edges"]
    frame_paths = sorted(args.frames_dir.glob("*.png"))
    if not frame_paths:
        raise SystemExit(f"no frames in {args.frames_dir}")

    out = args.out_dir
    ov_dir = out / "overlays"
    nn_dir = out / "frames_nn"
    ov_dir.mkdir(parents=True, exist_ok=True)
    nn_dir.mkdir(parents=True, exist_ok=True)

    # frame 0 seed
    rgba0 = _nn_upscale_rgba(_load_rgba(frame_paths[0]), args.nn_scale)
    Image.fromarray(rgba0, "RGBA").save(nn_dir / f"{0:02d}.png")
    bbox = _alpha_bbox(rgba0[:, :, 3])
    bone_names = [b["name"] for b in bones]
    seed_method = "unirig_ortho_sil_aabb_seed"
    if args.seed_json is not None:
        seed_doc = json.loads(args.seed_json.read_text(encoding="utf-8"))
        raw = seed_doc.get("joints") or seed_doc
        missing = [n for n in bone_names if n not in raw]
        if missing:
            raise SystemExit(f"seed missing joints: {missing[:8]}{'...' if len(missing) > 8 else ''}")
        joints = {n: (float(raw[n]["x"]), float(raw[n]["y"])) for n in bone_names}
        seed_method = str(seed_doc.get("method") or "human_eye_landmark_authoring")
    else:
        rest2d = _project_bones_ortho(bones, args.proj_mode)
        joints = _fit_similarity(
            rest2d,
            bbox,
            flip_u=bool(args.flip_u),
            flip_v=not bool(args.no_flip_v),
        )
    # snap seed onto opaque pixels (skip for eye-authored — keep pilot marks)
    if args.seed_json is None:
        for n in list(joints.keys()):
            joints[n] = _clamp_to_alpha(joints[n][0], joints[n][1], rgba0[:, :, 3], search=24)

    frames_out = []
    gif_frames = []
    prev_rgba = rgba0
    prev_gray = cv2.cvtColor(rgba0[:, :, :3], cv2.COLOR_RGB2GRAY)
    prev_joints = joints

    for fi, fp in enumerate(frame_paths):
        if fi == 0:
            cur_rgba = rgba0
            cur_joints = prev_joints
        else:
            cur_rgba = _nn_upscale_rgba(_load_rgba(fp), args.nn_scale)
            Image.fromarray(cur_rgba, "RGBA").save(nn_dir / f"{fi:02d}.png")
            cur_gray = cv2.cvtColor(cur_rgba[:, :, :3], cv2.COLOR_RGB2GRAY)
            cur_joints = _track_lk(prev_gray, cur_gray, prev_joints, cur_rgba[:, :, 3])
            # mild temporal blend toward previous for stability
            blended = {}
            for n, (x, y) in cur_joints.items():
                px, py = prev_joints[n]
                blended[n] = (0.75 * x + 0.25 * px, 0.75 * y + 0.25 * py)
            cur_joints = {
                n: _clamp_to_alpha(xy[0], xy[1], cur_rgba[:, :, 3]) for n, xy in blended.items()
            }
            prev_gray = cur_gray

        if fi == 0:
            label = f"roc move g0 f00 eye-authored  nn×{args.nn_scale}"
            method = seed_method
        else:
            label = f"roc move g0 f{fi:02d} UniRig LK←prev  nn×{args.nn_scale}"
            method = "unirig_lk_prev_frame"
        overlay = _draw_overlay(cur_rgba, cur_joints, edges, label)
        op = ov_dir / f"overlay_{fi:02d}.png"
        overlay.save(op)
        gif_frames.append(overlay)
        frames_out.append(
            {
                "frame": fi,
                "source": str(fp.resolve()).replace("\\", "/"),
                "nn": str((nn_dir / f"{fi:02d}.png").resolve()).replace("\\", "/"),
                "overlay": str(op.resolve()).replace("\\", "/"),
                "joints": {n: {"x": float(x), "y": float(y)} for n, (x, y) in cur_joints.items()},
                "method": method,
            }
        )
        prev_rgba = cur_rgba
        prev_joints = cur_joints

    kpt_path = out / "keypoints.json"
    kpt_path.write_text(
        json.dumps(
            {
                "unitSid": "h3_roc",
                "clip": "move_g0_rife",
                "skeleton": str(args.skeleton.resolve()).replace("\\", "/"),
                "projMode": args.proj_mode,
                "nnScale": args.nn_scale,
                "edges": edges,
                "frames": frames_out,
                "proof": "generated artifact validated — LK track pilot; not LLM authorship",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    gif_path = out / "stick_preview.gif"
    gif_frames[0].save(
        gif_path,
        save_all=True,
        append_images=gif_frames[1:],
        duration=PREVIEW_GIF_FRAME_MS,
        loop=0,
        optimize=False,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "frames": len(frames_out),
                "keypoints": str(kpt_path),
                "gif": str(gif_path),
                "bbox0": bbox,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
