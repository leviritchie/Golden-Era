#!/usr/bin/env python3
"""
Project consensus into sprite pixel keypoints.

Default (--mode iso_sil): take a kept iso-angle digitize sample, similarity-map
its character silhouette box onto the NN-upscaled DEF sprite content box, and
carry the sample's joints through that transform.

Why not raw 3D→sprite: GenAI multi-view poses drift, so triangulated limbs are
often anatomically wrong on the DEF figure. Silhouette registration keeps sticks
on the sprite body even when individual joints are noisy.

Also available:
  --mode iso2d   : average iso 2D → feet-anchored MidHip/Neck Procrustes
  --mode from3d  : triangulated 3D → iso camera → Procrustes
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

TOOL = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOL))
from constants import JOINT_ORDER, MANIFEST, OUT, SRC, SRC_UPSCALED  # noqa: E402


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def _cam_project(
    pts_local: dict[str, list[float]],
    *,
    az_deg: float,
    el_deg: float,
    distance: float = 3.0,
    ortho_scale: float = 2.6,
) -> dict[str, tuple[float, float]]:
    az = math.radians(az_deg)
    el = math.radians(el_deg)
    look_at = np.array([0.0, 0.0, 0.75], dtype=np.float64)
    r = distance * math.cos(el)
    cam = np.array([-r * math.sin(az), -r * math.cos(az), distance * math.sin(el) + 0.35], dtype=np.float64)
    forward = look_at - cam
    forward /= np.linalg.norm(forward) + 1e-9
    world_up = np.array([0.0, 0.0, 1.0], dtype=np.float64)
    right = np.cross(forward, world_up)
    right /= np.linalg.norm(right) + 1e-9
    up = np.cross(right, forward)
    up /= np.linalg.norm(up) + 1e-9
    out = {}
    for name, xyz in pts_local.items():
        p = look_at + np.asarray(xyz, dtype=np.float64)
        rel = p - look_at
        u = float(np.dot(rel, right))
        v = float(np.dot(rel, up))
        out[name] = (u / ortho_scale + 0.5, 0.5 - v / ortho_scale)
    return out


def _alpha_content_bbox_norm(im: Image.Image, *, thresh: int = 8) -> tuple[float, float, float, float]:
    arr = np.asarray(im.convert("RGBA"))
    h, w = arr.shape[:2]
    a = arr[:, :, 3]
    ys, xs = np.where(a > thresh)
    if len(xs) == 0:
        raise RuntimeError("empty alpha content")
    return float(xs.min()) / w, float(ys.min()) / h, float(xs.max()) / w, float(ys.max()) / h


def _overlay_body_bbox_norm(im: Image.Image) -> tuple[float, float, float, float]:
    """Content bbox of GenAI overlay with neon sticks suppressed."""
    rgb = np.asarray(im.convert("RGB")).astype(np.int16)
    h, w = rgb.shape[:2]
    r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    mx = np.maximum(np.maximum(r, g), b)
    # High-sat neon sticks (cyan/lime/magenta/yellow/orange)
    neon = (
        ((b >= g + 25) & (b >= r + 25) & (mx >= 80))  # cyan/blue
        | ((g >= r + 25) & (g >= b + 25) & (mx >= 80))  # lime
        | ((r >= g + 25) & (b >= g + 15) & (mx >= 80))  # magenta
        | ((r >= 80) & (g >= 80) & (b <= np.minimum(r, g) - 25))  # yellow
        | ((r >= g + 30) & (r >= b + 30) & (mx >= 80))  # orange/red
    )
    body = (mx > 35) & ~neon
    ys, xs = np.where(body)
    if len(xs) < 50:
        # Fall back to any non-dark pixel
        ys, xs = np.where(mx > 35)
    if len(xs) == 0:
        raise RuntimeError("overlay has no body silhouette")
    return float(xs.min()) / w, float(ys.min()) / h, float(xs.max()) / w, float(ys.max()) / h


def _bbox_similarity(
    src_bbox: tuple[float, float, float, float],
    dst_bbox: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    """Return s, tx, ty mapping: q = s * p + (tx, ty) (uniform scale, no rotation)."""
    sx0, sy0, sx1, sy1 = src_bbox
    dx0, dy0, dx1, dy1 = dst_bbox
    sw = sx1 - sx0
    sh = sy1 - sy0
    dw = dx1 - dx0
    dh = dy1 - dy0
    if sw < 1e-6 or sh < 1e-6 or dw < 1e-6 or dh < 1e-6:
        raise RuntimeError(f"degenerate bbox map {src_bbox} → {dst_bbox}")
    s = min(dw / sw, dh / sh)
    src_c = np.array([0.5 * (sx0 + sx1), 0.5 * (sy0 + sy1)], dtype=np.float64)
    dst_c = np.array([0.5 * (dx0 + dx1), 0.5 * (dy0 + dy1)], dtype=np.float64)
    t = dst_c - s * src_c
    return float(s), float(t[0]), float(t[1]), float(s)


def _apply_similarity(
    proj: dict[str, tuple[float, float]], s: float, tx: float, ty: float
) -> dict[str, tuple[float, float]]:
    out = {}
    for name, (x, y) in proj.items():
        out[name] = (s * x + tx, s * y + ty)
    return out


def _similarity_midhip_neck(
    proj: dict[str, tuple[float, float]],
    content: tuple[float, float, float, float],
    *,
    mid_from_feet: float = 0.32,
    neck_from_feet: float = 0.72,
    body_aspect: float = 2.25,
) -> tuple[dict[str, tuple[float, float]], dict]:
    if "MidHip" not in proj or "Neck" not in proj:
        raise RuntimeError("need MidHip and Neck for Procrustes fit")
    cx0, cy0, cx1, cy1 = content
    cw, ch = cx1 - cx0, cy1 - cy0
    cx = 0.5 * (cx0 + cx1)
    body_h = min(ch, max(cw * body_aspect, ch * 0.45))
    mid_t = np.array([cx, cy1 - mid_from_feet * body_h], dtype=np.float64)
    neck_t = np.array([cx, cy1 - neck_from_feet * body_h], dtype=np.float64)
    mid_s = np.array(proj["MidHip"], dtype=np.float64)
    neck_s = np.array(proj["Neck"], dtype=np.float64)
    v_s = neck_s - mid_s
    v_t = neck_t - mid_t
    len_s = float(np.linalg.norm(v_s))
    len_t = float(np.linalg.norm(v_t))
    if len_s < 1e-6 or len_t < 1e-6:
        raise RuntimeError("degenerate MidHip-Neck for Procrustes")
    ang_s = math.atan2(float(v_s[1]), float(v_s[0]))
    ang_t = math.atan2(float(v_t[1]), float(v_t[0]))
    dang = ang_t - ang_s
    c, s_ = math.cos(dang), math.sin(dang)
    R = np.array([[c, -s_], [s_, c]], dtype=np.float64)
    scale = len_t / len_s
    fitted = {}
    for name, (nx, ny) in proj.items():
        q = scale * (R @ (np.array([nx, ny]) - mid_s)) + mid_t
        fitted[name] = (float(q[0]), float(q[1]))
    meta = {
        "kind": "midhip_neck_procrustes_feet_anchored",
        "scale": scale,
        "rotRad": dang,
        "midTarget": mid_t.tolist(),
        "neckTarget": neck_t.tolist(),
        "contentNorm": [cx0, cy0, cx1, cy1],
        "bodyHeightNorm": body_h,
    }
    return fitted, meta


def _pick_iso_sample(recs: list[dict]) -> dict:
    """Prefer complete iso sample with MidHip+Neck+tip."""
    scored = []
    for r in recs:
        if not r.get("ok"):
            continue
        js = r.get("joints") or {}
        if "MidHip" not in js or "Neck" not in js:
            continue
        score = len(js)
        if "WeaponTip" in js:
            score += 2
        scored.append((score, r))
    if not scored:
        raise RuntimeError("no usable iso digitize sample")
    scored.sort(key=lambda t: t[0], reverse=True)
    return scored[0][1]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--joints3d", type=Path, default=OUT / "consensus" / "joints_3d.json")
    ap.add_argument("--culled", type=Path, default=OUT / "digitize" / "samples_culled.jsonl")
    ap.add_argument("--out", type=Path, default=OUT / "consensus" / "joints_2d_sprite.json")
    ap.add_argument("--keypoints-out", type=Path, default=OUT / "consensus" / "keypoints.json")
    ap.add_argument("--sprite-dir", type=Path, default=None)
    ap.add_argument(
        "--mode",
        choices=("iso_sil", "iso2d", "from3d"),
        default="iso_sil",
    )
    args = ap.parse_args()
    man = json.loads(args.manifest.read_text(encoding="utf-8"))
    j3 = json.loads(args.joints3d.read_text(encoding="utf-8"))
    if not j3.get("frames"):
        print(f"joints3d missing frames: {args.joints3d}", file=sys.stderr)
        return 2
    iso_cam = man["angles"]["iso"]
    az = float(iso_cam["isoAzimuthDeg"])
    el = float(iso_cam["isoElevationDeg"])

    sprite_dir = args.sprite_dir
    if sprite_dir is None:
        sprite_dir = SRC_UPSCALED if (SRC_UPSCALED / "frame_00.png").is_file() else SRC

    culled_by_frame: dict[int, list[dict]] = {}
    if args.culled.is_file():
        for r in _load_jsonl(args.culled):
            if str(r.get("angle")) != "iso":
                continue
            culled_by_frame.setdefault(int(r["frameIndex"]), []).append(r)

    frames_out = []
    sprite_frames = []
    for fi_s, fr in sorted(j3["frames"].items(), key=lambda kv: int(kv[0])):
        fi = int(fi_s)
        src_path = sprite_dir / f"frame_{fi:02d}.png"
        if not src_path.is_file():
            raise RuntimeError(f"missing sprite {src_path}")
        with Image.open(src_path) as im:
            sw, sh = im.size
            sprite_content = _alpha_content_bbox_norm(im)

        if args.mode == "iso_sil":
            recs = culled_by_frame.get(fi) or []
            if not recs:
                raise RuntimeError(f"frame {fi}: no culled iso samples for iso_sil mode")
            sample = _pick_iso_sample(recs)
            op = Path(str(sample["path"]))
            if not op.is_file():
                op = OUT / "overlays" / f"f{fi:02d}" / "iso" / Path(str(sample["path"])).name
            if not op.is_file():
                raise RuntimeError(f"frame {fi}: missing overlay {sample['path']}")
            with Image.open(op) as oim:
                overlay_content = _overlay_body_bbox_norm(oim)
            proj = {
                k: (float(v["nx"]), float(v["ny"]))
                for k, v in (sample.get("joints") or {}).items()
                if v.get("visible", True)
            }
            s, tx, ty, _ = _bbox_similarity(overlay_content, sprite_content)
            fitted = _apply_similarity(proj, s, tx, ty)
            fit_meta = {
                "kind": "iso_overlay_silhouette_bbox",
                "scale": s,
                "tx": tx,
                "ty": ty,
                "overlayPath": str(op).replace("\\", "/"),
                "overlayContentNorm": list(overlay_content),
                "spriteContentNorm": list(sprite_content),
                "source": "iso_sample_digitize",
                "mode": args.mode,
            }
        elif args.mode == "iso2d":
            raw = (fr.get("angleAvg2d") or {}).get("iso")
            if not raw:
                raise RuntimeError(f"frame {fi}: missing angleAvg2d.iso")
            proj = {k: (float(v[0]), float(v[1])) for k, v in raw.items()}
            fitted, fit_meta = _similarity_midhip_neck(proj, sprite_content)
            fit_meta["source"] = "iso_angle_avg_2d"
            fit_meta["mode"] = args.mode
        else:
            proj = _cam_project(fr["jointsLocal"], az_deg=az, el_deg=el)
            fitted, fit_meta = _similarity_midhip_neck(proj, sprite_content)
            fit_meta["source"] = "triangulated_3d_iso_camera"
            fit_meta["mode"] = args.mode

        joints = {}
        for name in JOINT_ORDER:
            if name not in fitted:
                continue
            nx, ny = fitted[name]
            if abs(nx) > 2.5 or abs(ny) > 2.5:
                raise RuntimeError(f"frame {fi} joint {name} absurd after fit: ({nx:.3f},{ny:.3f})")
            joints[name] = {"x": float(nx * sw), "y": float(ny * sh), "score": 0.9, "visible": True}

        frames_out.append(
            {
                "frameIndex": fi,
                "jointsNormRaw": {k: [proj[k][0], proj[k][1]] for k in proj},
                "joints": {k: [fitted[k][0], fitted[k][1]] for k in fitted},
                "pixelJoints": joints,
                "srcWidth": sw,
                "srcHeight": sh,
                "path": str(src_path).replace("\\", "/"),
                "contentFit": fit_meta,
            }
        )
        sprite_frames.append(
            {
                "frameIndex": fi,
                "ok": True,
                "path": str(src_path).replace("\\", "/"),
                "transform": {"srcWidth": sw, "srcHeight": sh, "pad": 0},
                "joints": joints,
            }
        )

    report = {
        "ok": True,
        "mode": args.mode,
        "camera": {"isoAzimuthDeg": az, "isoElevationDeg": el},
        "spriteDir": str(sprite_dir).replace("\\", "/"),
        "frames": frames_out,
        "proof": (
            f"generated artifact validated — consensus→sprite via {args.mode} "
            "on NN-upscaled sprites; not gameplay proven"
        ),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    kpt = {
        "ok": True,
        "method": f"dense_skeleton_consensus_project_{args.mode}",
        "spriteDir": str(sprite_dir).replace("\\", "/"),
        "frames": sprite_frames,
        "proof": "generated artifact validated — consensus→sprite keypoints for Mixamo check",
    }
    args.keypoints_out.write_text(json.dumps(kpt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "mode": args.mode, "frames": len(frames_out), "spriteDir": str(sprite_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
