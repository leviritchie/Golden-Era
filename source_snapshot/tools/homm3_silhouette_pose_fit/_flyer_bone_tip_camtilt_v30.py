"""Head-tail tip + look-up camera gallery for Roc Move attitude."""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from roc_gpu_cascade_experiment import (
    MOTION_ROOT_ROTATION_KEY,
    GpuCascadeConfig,
    GpuCascadeExperiment,
)

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
OUT = ROOT / "artifacts/pose_picker_runs/hybrid_method_quad/flyer_bone_tip_camtilt_v30"
OUT.mkdir(parents=True, exist_ok=True)
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
CAM = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/idle/gpu_cascade_delivery/initialization/profile_camera_fit.json"
)
SPRITE = ROOT / "artifacts/pose_picker_runs/h3_roc/move/frames_def12_nn_move"


def rodrigues(axis: np.ndarray, deg: float) -> np.ndarray:
    axis = np.asarray(axis, dtype=np.float64)
    axis = axis / (np.linalg.norm(axis) + 1e-12)
    th = math.radians(deg)
    k = np.array(
        [
            [0.0, -axis[2], axis[1]],
            [axis[2], 0.0, -axis[0]],
            [-axis[1], axis[0], 0.0],
        ],
        dtype=np.float64,
    )
    return np.eye(3) + math.sin(th) * k + (1.0 - math.cos(th)) * (k @ k)


def tip_to_target(src: np.ndarray, dst: np.ndarray, fallback_axis: np.ndarray) -> np.ndarray:
    src = src / np.linalg.norm(src)
    dst = dst / np.linalg.norm(dst)
    ax = np.cross(src, dst)
    n = np.linalg.norm(ax)
    if n < 1e-8:
        if src @ dst > 0:
            return np.eye(3)
        return rodrigues(fallback_axis, 180.0)
    ax /= n
    ang = math.degrees(math.acos(float(np.clip(src @ dst, -1.0, 1.0))))
    return rodrigues(ax, ang)


def mat_to_euler(R: np.ndarray, cf: np.ndarray, cr: np.ndarray, cu: np.ndarray):
    best = None
    for f in range(-180, 181, 10):
        for r in range(-180, 181, 10):
            for u in range(-180, 181, 10):
                rm = rodrigues(cu, u) @ rodrigues(cr, r) @ rodrigues(cf, f)
                err = float(np.linalg.norm(rm - R))
                if best is None or err < best[0]:
                    best = (err, f, r, u)
    assert best is not None
    _, f0, r0, u0 = best
    for step in (2, 1):
        _, f0, r0, u0 = best
        for f in range(f0 - 10, f0 + 11, step):
            for r in range(r0 - 10, r0 + 11, step):
                for u in range(u0 - 10, u0 + 11, step):
                    rm = rodrigues(cu, u) @ rodrigues(cr, r) @ rodrigues(cf, f)
                    err = float(np.linalg.norm(rm - R))
                    if err < best[0]:
                        best = (err, f, r, u)
    return best


def render(exp: GpuCascadeExperiment, f: float, r: float, u: float) -> Image.Image:
    seed = {
        0: {
            MOTION_ROOT_ROTATION_KEY: {
                "camera_forward": float(f),
                "camera_right": float(r),
                "camera_up": float(u),
            }
        }
    }
    bone, root_t, root_r = exp._initial_pose_tensors(seed)
    rgb = exp.exact_triangle_rgb(bone, root_t, root_r)
    if isinstance(rgb, (tuple, list)):
        rgb = rgb[0]
    arr = rgb.detach().float().cpu().numpy()
    if arr.ndim == 4:
        arr = arr[0]
    if arr.shape[0] in (3, 4):
        arr = np.transpose(arr[:3], (1, 2, 0))
    if arr.max() <= 1.5:
        arr = arr * 255.0
    return Image.fromarray(arr.clip(0, 255).astype(np.uint8))


def write_pitched_cam(base: dict, pitch_deg: float, path: Path) -> Path:
    sx = np.array(base["basisScreenRows"][0], dtype=np.float64)
    sy = np.array(base["basisScreenRows"][1], dtype=np.float64)
    right = sx / np.linalg.norm(sx)
    up = -sy
    up = up / np.linalg.norm(up)
    rp = rodrigues(right, pitch_deg)
    up2 = rp @ up
    out = dict(base)
    out["basisScreenRows"] = [right.tolist(), (-up2).tolist()]
    metrics = dict(out.get("profileMetrics") or out.get("profileMetrics") or {})
    # keep original profileMetrics if present
    if "profileMetrics" in base:
        metrics = dict(base["profileMetrics"])
    metrics["pitchUpDeg"] = pitch_deg
    metrics["note"] = "manual look-up pitch for flyer belly visibility"
    out["profileMetrics"] = metrics
    path.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    return path


def head_tail_axis(asset) -> np.ndarray:
    verts = np.concatenate(
        [np.asarray(p.positions, dtype=np.float64) for p in asset.primitives],
        axis=0,
    )
    ys = verts[:, 1]
    top = verts[ys >= np.quantile(ys, 0.7)]
    head = top[np.argmax(top[:, 2])]
    tail = verts[np.argmin(verts[:, 2])]
    axis = head - tail
    return axis / np.linalg.norm(axis)


def make_cfg() -> GpuCascadeConfig:
    cfg = GpuCascadeConfig(
        score_mode="geometry",
        depth_weight=0.0,
        silhouette_weight=1.0,
        chroma_weight=0.0,
        motion_weight=0.0,
        collision_enabled=False,
        collision_weight=0.0,
        root_search_enabled=False,
        resolution=(256, 224),
    )
    cfg.validate()
    return cfg


def main() -> None:
    cfg = make_cfg()
    exp = GpuCascadeExperiment(
        src_glb=MESH,
        camera_fit=CAM,
        target_frame_dir=SPRITE,
        frame_indices=(0,),
        config=cfg,
    )
    axis = head_tail_axis(exp.asset)
    cf = exp.camera_forward.detach().cpu().numpy().reshape(3)
    cr = exp.camera_right.detach().cpu().numpy().reshape(3)
    cu = exp.camera_up.detach().cpu().numpy().reshape(3)
    print("head-tail", axis, flush=True)

    cam_json = json.loads(CAM.read_text(encoding="utf-8"))
    sprite_img = Image.open(sorted(SPRITE.glob("*.png"))[0]).convert("RGBA")
    cells: list[tuple[str, Image.Image, dict]] = []

    r0 = tip_to_target(axis, cr, fallback_axis=cf)
    for bank in (-40, -20, 0, 20, 40, 60):
        R = rodrigues(cr, bank) @ r0
        err, f, r, u = mat_to_euler(R, cf, cr, cu)
        label = f"idle b{bank:+d} {f}/{r}/{u}"
        print(label, "err", round(err, 4), flush=True)
        cells.append(
            (
                label,
                render(exp, f, r, u),
                {"cam": "idle", "bank": bank, "f": f, "r": r, "u": u, "err": err},
            )
        )

    for pitch in (15, 25, 35):
        cam_path = write_pitched_cam(cam_json, pitch, OUT / f"cam_pitch{pitch}.json")
        exp_p = GpuCascadeExperiment(
            src_glb=MESH,
            camera_fit=cam_path,
            target_frame_dir=SPRITE,
            frame_indices=(0,),
            config=cfg,
        )
        cfp = exp_p.camera_forward.detach().cpu().numpy().reshape(3)
        crp = exp_p.camera_right.detach().cpu().numpy().reshape(3)
        cup = exp_p.camera_up.detach().cpu().numpy().reshape(3)
        r0p = tip_to_target(axis, crp, fallback_axis=cfp)
        for bank in (0, 20, 40):
            R = rodrigues(crp, bank) @ r0p
            err, f, r, u = mat_to_euler(R, cfp, crp, cup)
            label = f"p{pitch} b{bank:+d} {f}/{r}/{u}"
            print(label, "err", round(err, 4), flush=True)
            cells.append(
                (
                    label,
                    render(exp_p, f, r, u),
                    {
                        "cam": f"pitch{pitch}",
                        "bank": bank,
                        "f": f,
                        "r": r,
                        "u": u,
                        "err": err,
                    },
                )
            )

    w, h = 200, 175
    pad = 5
    lh = 20
    cols = 7
    items = [("sprite", None, {})] + cells
    rows = (len(items) + cols - 1) // cols
    sheet = Image.new(
        "RGB",
        (cols * (w + pad) + pad, rows * (h + lh + pad) + pad),
        (20, 20, 24),
    )
    draw = ImageDraw.Draw(sheet)
    for i, (name, im, _meta) in enumerate(items):
        rr = i // cols
        cc = i % cols
        x = pad + cc * (w + pad)
        y = pad + rr * (h + lh + pad)
        if im is None:
            cell = Image.new("RGB", (w, h), (0, 0, 0))
            sr = sprite_img.resize((w, h), Image.NEAREST)
            cell.paste(sr, mask=sr.split()[-1])
        else:
            cell = im.resize((w, h), Image.NEAREST)
        sheet.paste(cell, (x, y + lh))
        draw.text((x, y), name[:32], fill=(255, 220, 120))
    sheet.save(OUT / "sheet.png")
    (OUT / "meta.json").write_text(
        json.dumps({"axis": axis.tolist(), "cells": [m for _, _, m in cells]}, indent=2)
        + "\n",
        encoding="utf-8",
    )
    print("wrote", OUT / "sheet.png", "n=", len(cells), flush=True)


if __name__ == "__main__":
    main()
