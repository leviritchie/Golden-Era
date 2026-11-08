"""v45: per-frame tip IoU search under fixed asym wing + leg tuck for Roc Move."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import zoom

from roc_gpu_cascade_experiment import (
    MOTION_ROOT_ROTATION_KEY as RK,
    GpuCascadeConfig,
    GpuCascadeExperiment,
)

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
METHOD = "hybrid_v45_sidecam_perframe_tip_asymwing_legtuck"
OUT = ROOT / "artifacts/pose_picker_runs/hybrid_method_quad" / METHOD / "roc_move"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
SIDE = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/move/initialization/flyer_side_profile_camera_fit.json"
)
SPRITE = ROOT / "artifacts/pose_picker_runs/h3_roc/move/frames_def12_nn_move"
WING = {"Bone_019": {"x": 90.0}, "Bone_022": {"x": -90.0}, "Bone_018": {"y": -20.0}}
LEG = {b: {"x": -150.0} for b in ("Bone_004", "Bone_008")}
LEG.update(
    {
        b: {"x": 0.0}
        for b in ("Bone_005", "Bone_006", "Bone_007", "Bone_009", "Bone_010", "Bone_011")
    }
)
SEED = (32.0, 57.0, 24.0)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frame_paths = sorted(SPRITE.glob("*.png"))
    if not frame_paths:
        raise SystemExit(f"no sprites in {SPRITE}")
    n = len(frame_paths)
    print(f"frames={n} method={METHOD}", flush=True)
    t0 = time.perf_counter()

    cfg = GpuCascadeConfig(
        score_mode="geometry",
        depth_weight=0,
        silhouette_weight=1,
        chroma_weight=0,
        motion_weight=0,
        collision_enabled=False,
        collision_weight=0,
        root_search_enabled=False,
        resolution=(160, 140),
    )
    cfg.validate()
    exp = GpuCascadeExperiment(
        src_glb=MESH,
        camera_fit=SIDE,
        target_frame_dir=SPRITE,
        frame_indices=tuple(range(n)),
        config=cfg,
    )
    ni = {name: i for i, name in enumerate(exp.node_names)}
    hi, ti = ni["Bone_014"], ni["Bone_012"]

    def metrics(fi: int, tip: tuple[float, float, float]) -> dict:
        pose = {
            RK: {
                "camera_forward": float(tip[0]),
                "camera_right": float(tip[1]),
                "camera_up": float(tip[2]),
            },
            **WING,
            **LEG,
        }
        bv, rt, rr = exp._initial_pose_tensors({fi: pose})
        sc = exp.evaluate(bv, rt, rr, frame_indices=(fi,))
        xy = exp._screen_joint_xy(bv, rt, rr)[0].detach().cpu().numpy()
        if xy.ndim == 3:
            xy = xy[0]
        ang = math.degrees(
            math.atan2(float(xy[hi, 1] - xy[ti, 1]), float(xy[hi, 0] - xy[ti, 0]))
        )
        head_right = float(xy[hi, 0] - xy[ti, 0])
        iou = float(sc["silhouetteIoU"].detach().cpu().numpy().reshape(-1)[0])
        mask = sc["predictedMasks"][0].detach().cpu().numpy() > 0.5
        if mask.ndim == 3:
            mask = mask[..., 0]
        ys, xs = np.where(mask)
        asp = (
            float(xs.max() - xs.min() + 1) / float(max(ys.max() - ys.min() + 1, 1))
            if len(xs)
            else 0.0
        )
        return {
            "ang": ang,
            "absang": abs(ang),
            "headRight": head_right,
            "asp": asp,
            "iou": iou,
        }

    poses: dict[str, dict] = {}
    tips: list[dict] = []
    prev_tip = SEED
    for fi in range(n):
        # Prefer continuity from prior frame tip; always keep seed + prev as fallbacks.
        center = prev_tip if fi else SEED
        rows: list[dict] = []
        for tip in (SEED, prev_tip, center):
            m = metrics(fi, tip)
            rows.append({"tip": tip, **m})
        for df in range(-24, 25, 8):
            for dr in range(-24, 25, 8):
                for du in range(-24, 25, 8):
                    tip = (center[0] + df, center[1] + dr, center[2] + du)
                    m = metrics(fi, tip)
                    # Soft gates: keep facing mostly right; allow larger HT so flap frames survive.
                    if m["headRight"] <= -5:
                        continue
                    if m["absang"] > 35:
                        continue
                    rows.append({"tip": tip, **m})
        # Rank: IoU primary, mild HT penalty, mild jump penalty from previous tip.
        def rank(r: dict) -> tuple:
            tip = r["tip"]
            jump = abs(tip[0] - prev_tip[0]) + abs(tip[1] - prev_tip[1]) + abs(tip[2] - prev_tip[2])
            return (-r["iou"], r["absang"] * 0.01, jump * 0.001)

        rows.sort(key=rank)
        best = rows[0]
        f0, r0, u0 = best["tip"]
        fine: list[dict] = []
        for f in range(int(round(f0)) - 6, int(round(f0)) + 7, 2):
            for r in range(int(round(r0)) - 6, int(round(r0)) + 7, 2):
                for u in range(int(round(u0)) - 6, int(round(u0)) + 7, 2):
                    tip = (float(f), float(r), float(u))
                    m = metrics(fi, tip)
                    if m["headRight"] <= -5 or m["absang"] > 35:
                        continue
                    fine.append({"tip": tip, **m})
        if not fine:
            fine = [best]
        fine.sort(key=rank)
        chosen = fine[0]
        tip = chosen["tip"]
        prev_tip = tip
        tips.append({"frame": fi, **chosen})
        poses[str(fi)] = {
            RK: {
                "camera_forward": tip[0],
                "camera_right": tip[1],
                "camera_up": tip[2],
            },
            **{b: dict(a) for b, a in WING.items()},
            **{b: dict(a) for b, a in LEG.items()},
        }
        print(
            f"f{fi:02d} tip={tip} iou={chosen['iou']:.3f} "
            f"ht={chosen['ang']:.1f} asp={chosen['asp']:.2f}",
            flush=True,
        )

    print(f"search_sec={time.perf_counter() - t0:.1f}", flush=True)

    arm = OUT / METHOD
    arm.mkdir(parents=True, exist_ok=True)
    rgb_dir = arm / "solved_rgb"
    rgb_dir.mkdir(exist_ok=True)
    prev = arm / "preview"
    prev.mkdir(exist_ok=True)

    cfg2 = GpuCascadeConfig(
        score_mode="geometry",
        depth_weight=0,
        silhouette_weight=1,
        chroma_weight=0,
        motion_weight=0,
        collision_enabled=False,
        collision_weight=0,
        root_search_enabled=False,
        resolution=(384, 336),
    )
    cfg2.validate()
    exp2 = GpuCascadeExperiment(
        src_glb=MESH,
        camera_fit=SIDE,
        target_frame_dir=SPRITE,
        frame_indices=tuple(range(n)),
        config=cfg2,
    )
    bv, rt, rr = exp2._initial_pose_tensors({int(k): v for k, v in poses.items()})
    rgb = exp2.exact_triangle_rgb(bv, rt, rr)
    if isinstance(rgb, (tuple, list)):
        rgb = rgb[0]
    arr = rgb.detach().float().cpu().numpy()
    if arr.ndim == 3:
        arr = arr[None]
    if arr.shape[-1] in (3, 4) and arr.shape[1] not in (3, 4):
        arr = np.transpose(arr, (0, 3, 1, 2))

    panels: list[Image.Image] = []
    for fi in range(n):
        frame = arr[fi]
        if frame.shape[0] in (3, 4):
            img = np.transpose(frame[:3], (1, 2, 0))
        else:
            img = frame[..., :3]
        if img.max() <= 1.5:
            img = img * 255
        Image.fromarray(img.clip(0, 255).astype(np.uint8)).save(rgb_dir / f"{fi:02d}.png")

        sp = Image.open(frame_paths[fi]).convert("RGBA")
        mesh = Image.open(rgb_dir / f"{fi:02d}.png").convert("RGB")
        w, h = 300, 260
        sp_r = Image.new("RGB", (w, h), (0, 0, 0))
        s2 = sp.resize((w, h), Image.NEAREST)
        sp_r.paste(s2, mask=s2.split()[-1])
        mesh_r = mesh.resize((w, h), Image.NEAREST)
        sc = exp2.evaluate(bv, rt, rr, frame_indices=(fi,))
        pred = sc["predictedMasks"][0].detach().cpu().numpy() > 0.5
        if pred.ndim == 3:
            pred = pred[..., 0]
        tgt = exp2.target_masks[fi].detach().cpu().numpy() > 0.5
        if tgt.ndim == 3:
            tgt = tgt[..., 0]
        tg = zoom(tgt.astype(np.float32), (h / tgt.shape[0], w / tgt.shape[1]), order=0) > 0.5
        pr = (
            zoom(pred.astype(np.float32), (h / pred.shape[0], w / pred.shape[1]), order=0)
            > 0.5
        )
        ov = np.zeros((h, w, 3), np.uint8)
        ov[tg & ~pr] = (220, 40, 40)
        ov[pr & ~tg] = (40, 90, 220)
        ov[tg & pr] = (40, 200, 80)
        strip = Image.new("RGB", (w * 3 + 20, h + 36), (10, 10, 14))
        d = ImageDraw.Draw(strip)
        strip.paste(sp_r, (0, 30))
        strip.paste(mesh_r, (w + 10, 30))
        strip.paste(Image.fromarray(ov), (2 * w + 20, 30))
        tip = tips[fi]["tip"]
        d.text((4, 4), f"target f{fi:02d}", fill=(255, 230, 120))
        d.text(
            (w + 14, 4),
            f"mesh tip=({tip[0]:.0f},{tip[1]:.0f},{tip[2]:.0f}) i={tips[fi]['iou']:.2f}",
            fill=(255, 230, 120),
        )
        d.text((2 * w + 24, 4), "overlay R=tgt B=mesh G=both", fill=(255, 230, 120))
        strip.save(prev / f"preview_{fi:02d}.png")

        left = Image.new("RGB", (320, 280), (0, 0, 0))
        s2 = sp.resize((320, 280), Image.NEAREST)
        left.paste(s2, mask=s2.split()[-1])
        right = mesh.resize((320, 280), Image.NEAREST)
        sheet = Image.new("RGB", (320 * 2 + 12, 280 + 28), (10, 10, 14))
        d2 = ImageDraw.Draw(sheet)
        sheet.paste(left, (0, 28))
        sheet.paste(right, (332, 28))
        d2.text((4, 4), "sprite", fill=(255, 230, 120))
        d2.text((336, 4), METHOD[:34], fill=(255, 230, 120))
        panels.append(sheet)

    gif_path = OUT / "chain_space_compare.gif"
    panels[0].save(
        gif_path,
        save_all=True,
        append_images=panels[1:],
        duration=160,
        loop=0,
    )
    print("gif", gif_path, flush=True)

    elapsed = time.perf_counter() - t0
    payload = {
        "methodId": METHOD,
        "poses": poses,
        "tips": tips,
        "wing": WING,
        "leg": LEG,
        "cameraFit": str(SIDE).replace("\\", "/"),
        "elapsedSec": round(elapsed, 1),
        "budgetSec": 300,
        "withinBudget": elapsed <= 300,
        "meanIou": float(np.mean([t["iou"] for t in tips])),
        "proof": "generated-artifact; hybrid trial; not CURRENT_CASCADE_KEEP; not OE runtime",
    }
    (arm / "gpu_clip_result.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    (OUT / "run_report.json").write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "meanIou": payload["meanIou"],
                "elapsedSec": payload["elapsedSec"],
                "tips": [
                    (t["frame"], [round(x, 1) for x in t["tip"]], round(t["iou"], 3))
                    for t in tips
                ],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
