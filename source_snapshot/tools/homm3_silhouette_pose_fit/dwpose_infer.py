#!/usr/bin/env python3
"""Fully automatic DWPose inference on HoMM3 sprite frames (fail-closed)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DET = Path(__file__).resolve().parent / "models" / "dwpose" / "yolox_l.onnx"
DEFAULT_POSE = Path(__file__).resolve().parent / "models" / "dwpose" / "dw-ll_ucoco_384.onnx"


def _load_job(path: Path) -> dict:
    job = json.loads(path.read_text(encoding="utf-8"))

    def resolve(p: str) -> str:
        pp = Path(p)
        if pp.is_absolute():
            return str(pp)
        return str((ROOT / pp).resolve())

    job["masterGlb"] = resolve(job["masterGlb"])
    job["outputDir"] = resolve(job["outputDir"])
    for fr in job["frames"]:
        fr["path"] = resolve(fr["path"])
    return job


def crop_to_subject(rgba: np.ndarray, pad_frac: float = 0.12) -> tuple[np.ndarray, dict]:
    """Crop RGBA tightly around opaque subject so DWPose sees a large humanoid."""
    alpha = rgba[..., 3]
    ys, xs = np.where(alpha > 8)
    if ys.size == 0:
        h, w = rgba.shape[:2]
        return rgba, {"cropX0": 0, "cropY0": 0, "cropW": w, "cropH": h}
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    bw, bh = x1 - x0, y1 - y0
    pad = int(round(pad_frac * max(bw, bh)))
    y0 = max(0, y0 - pad)
    x0 = max(0, x0 - pad)
    y1 = min(rgba.shape[0], y1 + pad)
    x1 = min(rgba.shape[1], x1 + pad)
    crop = rgba[y0:y1, x0:x1].copy()
    return crop, {"cropX0": x0, "cropY0": y0, "cropW": crop.shape[1], "cropH": crop.shape[0]}


def upscale_sprite(
    rgba: np.ndarray,
    *,
    long_edge: int = 1024,
    pad_to_square: bool = True,
    bg_rgb: tuple[int, int, int] = (0, 0, 0),
    subject_crop: bool = True,
) -> tuple[np.ndarray, dict]:
    """
    Optional subject crop, pad, nearest-neighbor upscale for DWPose.
    Transform maps upscaled px -> original sprite px.
    """
    crop_meta = {"cropX0": 0, "cropY0": 0, "cropW": rgba.shape[1], "cropH": rgba.shape[0]}
    work = rgba
    if subject_crop:
        work, crop_meta = crop_to_subject(rgba)

    if work.shape[2] == 4:
        alpha = work[..., 3:4].astype(np.float32) / 255.0
        rgb = work[..., :3].astype(np.float32)
        bg = np.array(bg_rgb, dtype=np.float32).reshape(1, 1, 3)
        rgb = (rgb * alpha + bg * (1.0 - alpha)).astype(np.uint8)
    else:
        rgb = work[..., :3]

    h, w = rgb.shape[:2]
    canvas = rgb
    pad_x = pad_y = 0
    if pad_to_square:
        side = max(h, w)
        canvas = np.zeros((side, side, 3), dtype=np.uint8)
        canvas[:] = np.array(bg_rgb, dtype=np.uint8)
        pad_y = (side - h) // 2
        pad_x = (side - w) // 2
        canvas[pad_y : pad_y + h, pad_x : pad_x + w] = rgb
        h2, w2 = side, side
    else:
        h2, w2 = h, w

    scale = float(long_edge) / float(max(h2, w2))
    out_w = max(1, int(round(w2 * scale)))
    out_h = max(1, int(round(h2 * scale)))
    up = cv2.resize(canvas, (out_w, out_h), interpolation=cv2.INTER_NEAREST)
    bgr = cv2.cvtColor(up, cv2.COLOR_RGB2BGR)
    transform = {
        "padX": pad_x,
        "padY": pad_y,
        "scale": scale,
        "srcWidth": int(rgba.shape[1]),
        "srcHeight": int(rgba.shape[0]),
        "upWidth": out_w,
        "upHeight": out_h,
        "longEdge": long_edge,
        "bgRgb": list(bg_rgb),
        **crop_meta,
    }
    return bgr, transform


def _score_pose(person_s: np.ndarray, score_thr: float) -> tuple[int, float]:
    visible = int(np.sum(person_s >= score_thr))
    mean_score = float(np.mean(person_s[person_s >= score_thr])) if visible else 0.0
    return visible, mean_score


def pose_geometry_ok_from_arrays(person_k: np.ndarray, person_s: np.ndarray, score_thr: float) -> tuple[bool, str]:
    """
    OpenPose body-18 indices.
    Pixel-art hobgoblins often produce high-confidence but topologically impossible poses;
    reject those fail-closed rather than fitting junk.
    """
    def pt(i: int):
        if person_s[i] < score_thr:
            return None
        return float(person_k[i, 0]), float(person_k[i, 1])

    head = pt(0) or pt(1)
    neck = pt(1) or pt(0)
    mid = pt(8)
    rsho, lsho = pt(2), pt(5)
    if head is None or neck is None or mid is None:
        return False, "missing_torso"
    if head[1] > mid[1] - 10:
        return False, "head_not_above_hips"
    if neck[1] > mid[1] - 5:
        return False, "neck_not_above_hips"

    def leg_ok(hip, knee, ankle, tag: str) -> tuple[bool, str]:
        if hip is None or knee is None or ankle is None:
            return False, f"missing_{tag}_leg"
        # Image y grows downward: hip above knee above ankle.
        if not (hip[1] + 3 < knee[1] and knee[1] + 3 < ankle[1]):
            return False, f"{tag}_leg_order"
        return True, "ok"

    ok_r, reason_r = leg_ok(pt(9), pt(10), pt(11), "R")
    if not ok_r:
        return False, reason_r
    ok_l, reason_l = leg_ok(pt(12), pt(13), pt(14), "L")
    if not ok_l:
        return False, reason_l

    # Shoulders should sit near/above mid-hip vertically and not collapse into feet.
    for sho, tag in ((rsho, "R"), (lsho, "L")):
        if sho is None:
            return False, f"missing_{tag}_shoulder"
        if sho[1] > mid[1] + 20:
            return False, f"{tag}_shoulder_below_hips"

    rw, lw = pt(4), pt(7)
    if rw and lw and abs(rw[0] - lw[0]) + abs(rw[1] - lw[1]) < 2.0:
        return False, "wrists_collapsed"
    return True, "ok"


def infer_best_variant(
    detector,
    rgba: np.ndarray,
    *,
    long_edges: list[int],
    backgrounds: list[tuple[int, int, int]],
    score_thr: float,
) -> tuple[np.ndarray, np.ndarray, dict, np.ndarray, str] | None:
    """Try automatic upscale variants; return best geometrically-sane pose."""
    best = None
    best_key = (-1, -1.0)
    for long_edge in long_edges:
        for bg in backgrounds:
            bgr, transform = upscale_sprite(rgba, long_edge=long_edge, bg_rgb=bg, subject_crop=True)
            kpts_up, scores = detector(bgr)
            if kpts_up.shape[0] == 0:
                continue
            person_k = kpts_up[0]
            person_s = scores[0]
            ok, reason = pose_geometry_ok_from_arrays(person_k, person_s, score_thr)
            if not ok:
                continue
            visible, mean_score = _score_pose(person_s, score_thr)
            key = (visible, mean_score)
            if key > best_key:
                best_key = key
                label = f"edge{long_edge}_bg{bg[0]}_{bg[1]}_{bg[2]}_{reason}"
                best = (person_k, person_s, transform, bgr, label)
    return best


def upscaled_xy_to_sprite(x: float, y: float, transform: dict) -> tuple[float, float]:
    scale = float(transform["scale"])
    cx = x / scale - float(transform["padX"])
    cy = y / scale - float(transform["padY"])
    sx = cx + float(transform.get("cropX0", 0))
    sy = cy + float(transform.get("cropY0", 0))
    return sx, sy


def draw_overlay(bgr: np.ndarray, keypoints: np.ndarray, scores: np.ndarray, thr: float = 0.3) -> np.ndarray:
    from dwpose_onnx import OPENPOSE_BODY18

    # OpenPose body edges (subset of classic skeleton).
    edges = [
        (1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7),
        (1, 8), (8, 9), (9, 10), (10, 11), (8, 12), (12, 13), (13, 14),
        (1, 0), (0, 15), (0, 16), (15, 17),
    ]
    canvas = bgr.copy()
    for a, b in edges:
        if a >= len(scores) or b >= len(scores):
            continue
        if scores[a] < thr or scores[b] < thr:
            continue
        pa = tuple(np.round(keypoints[a]).astype(int))
        pb = tuple(np.round(keypoints[b]).astype(int))
        cv2.line(canvas, pa, pb, (0, 255, 0), 2)
    for i, (xy, sc) in enumerate(zip(keypoints, scores)):
        if sc < thr:
            continue
        p = tuple(np.round(xy).astype(int))
        cv2.circle(canvas, p, 4, (0, 0, 255), -1)
        name = OPENPOSE_BODY18[i] if i < len(OPENPOSE_BODY18) else str(i)
        cv2.putText(canvas, name, (p[0] + 4, p[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 0), 1)
    return canvas


def infer_job(job: dict, *, det_path: Path, pose_path: Path, force: bool = False) -> dict:
    from dwpose_onnx import OPENPOSE_BODY18, Wholebody

    out_dir = Path(job["outputDir"])
    kpt_dir = out_dir / "dwpose"
    overlay_dir = kpt_dir / "overlays"
    up_dir = kpt_dir / "upscaled"
    kpt_dir.mkdir(parents=True, exist_ok=True)
    overlay_dir.mkdir(parents=True, exist_ok=True)
    up_dir.mkdir(parents=True, exist_ok=True)

    dw = job.get("dwpose", {})
    long_edges = [int(x) for x in dw.get("longEdges", [dw.get("longEdge", 1024), 1280])]
    backgrounds = [tuple(x) for x in dw.get("backgrounds", [[0, 0, 0], [48, 48, 48], [180, 180, 180]])]
    min_mean_score = float(dw.get("minMeanBodyScore", 0.18))
    min_visible = int(dw.get("minVisibleJoints", 6))
    score_thr = float(dw.get("scoreThr", 0.22))

    detector = Wholebody(det_path, pose_path)
    frames_out = []
    failures = []

    for i, fr in enumerate(job["frames"]):
        src = Path(fr["path"])
        rgba = np.array(Image.open(src).convert("RGBA"), dtype=np.uint8)
        best = infer_best_variant(
            detector,
            rgba,
            long_edges=long_edges,
            backgrounds=backgrounds,
            score_thr=score_thr,
        )
        if best is None:
            failures.append({"frameIndex": i, "reason": "no_sane_pose", "path": str(src)})
            # still write a diagnostic from a default upscale
            bgr, _ = upscale_sprite(rgba, long_edge=long_edges[0], bg_rgb=backgrounds[0], subject_crop=True)
            overlay = bgr.copy()
            cv2.putText(overlay, "NO SANE POSE", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 3)
            cv2.imwrite(str(overlay_dir / f"frame_{i:02d}.png"), overlay)
            continue

        person_k, person_s, transform, bgr, variant = best
        up_path = up_dir / f"frame_{i:02d}_up.png"
        cv2.imwrite(str(up_path), bgr)
        visible, mean_score = _score_pose(person_s, score_thr)
        overlay = draw_overlay(bgr, person_k, person_s, thr=score_thr)
        cv2.putText(overlay, variant, (20, overlay.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.imwrite(str(overlay_dir / f"frame_{i:02d}.png"), overlay)

        if visible < min_visible or mean_score < min_mean_score:
            failures.append(
                {
                    "frameIndex": i,
                    "reason": "low_confidence",
                    "visibleJoints": visible,
                    "meanScore": mean_score,
                    "variant": variant,
                    "path": str(src),
                }
            )
            continue

        joints = {}
        for j, name in enumerate(OPENPOSE_BODY18):
            x_up, y_up = float(person_k[j, 0]), float(person_k[j, 1])
            sx, sy = upscaled_xy_to_sprite(x_up, y_up, transform)
            joints[name] = {
                "x": sx,
                "y": sy,
                "xUpscaled": x_up,
                "yUpscaled": y_up,
                "score": float(person_s[j]),
                "visible": bool(person_s[j] >= score_thr),
            }

        frames_out.append(
            {
                "frameIndex": i,
                "sourcePath": str(src).replace("\\", "/"),
                "transform": transform,
                "variant": variant,
                "visibleJoints": visible,
                "meanScore": mean_score,
                "joints": joints,
                "overlay": str((overlay_dir / f"frame_{i:02d}.png").resolve()).replace("\\", "/"),
            }
        )

    report = {
        "unitSid": job.get("unitSid"),
        "clipId": job.get("clipId"),
        "detector": "dwpose_onnx",
        "detModel": str(det_path).replace("\\", "/"),
        "poseModel": str(pose_path).replace("\\", "/"),
        "frameCountExpected": len(job["frames"]),
        "frameCountOk": len(frames_out),
        "failures": failures,
        "frames": frames_out,
        "ok": len(failures) == 0 and len(frames_out) == len(job["frames"]),
        "proof": "generated artifact validated — DWPose keypoints; not OE runtime proven",
    }
    out_json = kpt_dir / "keypoints.json"
    out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["keypointsPath"] = str(out_json.resolve()).replace("\\", "/")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--det", type=Path, default=DEFAULT_DET)
    ap.add_argument("--pose", type=Path, default=DEFAULT_POSE)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    cfg = args.config if args.config.is_file() else ROOT / args.config
    if not cfg.is_file():
        print(f"config not found: {args.config}", file=sys.stderr)
        return 2
    if not args.det.is_file() or not args.pose.is_file():
        print(f"DWPose models missing:\n  {args.det}\n  {args.pose}", file=sys.stderr)
        return 2

    # Allow `python dwpose_infer.py` imports of sibling package.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    job = _load_job(cfg)
    # Also accept resolved job already written to outputDir
    report = infer_job(job, det_path=args.det, pose_path=args.pose, force=args.force)
    print(json.dumps({"ok": report["ok"], "keypointsPath": report.get("keypointsPath"), "failures": report["failures"]}, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    # Package-relative import fix when run as script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
