"""v47: side cam + tip 37/47/4 + asym wing + Bone_018 y-90 + per-frame wing Y refine."""
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
METHOD = "hybrid_v47_sidecam_leveltip_374704_wing018ym90_perframeY_legtuck"
OUT = ROOT / "artifacts/pose_picker_runs/hybrid_method_quad" / METHOD / "roc_move"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
SIDE = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/move/initialization/flyer_side_profile_camera_fit.json"
)
SPRITE = ROOT / "artifacts/pose_picker_runs/h3_roc/move/frames_def12_nn_move"
TIP = (37.0, 47.0, 4.0)
WING0 = {"Bone_019": {"x": 90.0}, "Bone_022": {"x": -90.0}, "Bone_018": {"y": -90.0}}
LEG = {b: {"x": -150.0} for b in ("Bone_004", "Bone_008")}
LEG.update(
    {
        b: {"x": 0.0}
        for b in ("Bone_005", "Bone_006", "Bone_007", "Bone_009", "Bone_010", "Bone_011")
    }
)
WING_Y_BONES = ("Bone_018", "Bone_021", "Bone_022")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frame_paths = sorted(SPRITE.glob("*.png"))
    if not frame_paths:
        raise SystemExit(f"no sprites in {SPRITE}")
    n = len(frame_paths)
    print(f"frames={n} method={METHOD}", flush=True)
    t0 = time.perf_counter()

    poses: dict[str, dict] = {}
    per_frame: list[dict] = []
    for fi in range(n):
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
            frame_indices=(fi,),
            config=cfg,
        )
        tgt = exp.target_masks[0].detach().cpu().numpy() > 0.5
        if tgt.ndim == 3:
            tgt = tgt[..., 0]
        tys = np.where(tgt)[0]
        ymid = 0.5 * (tys.min() + tys.max())
        tgt_low = tgt & (np.arange(tgt.shape[0])[:, None] >= ymid)
        ni = {name: i for i, name in enumerate(exp.node_names)}
        hi, ti = ni["Bone_014"], ni["Bone_012"]

        def score_wing(wing: dict) -> dict:
            pose = {
                RK: {
                    "camera_forward": TIP[0],
                    "camera_right": TIP[1],
                    "camera_up": TIP[2],
                },
                **wing,
                **LEG,
            }
            bv, rt, rr = exp._initial_pose_tensors({fi: pose})
            sc = exp.evaluate(bv, rt, rr)
            iou = float(sc["silhouetteIoU"].detach().cpu().numpy().reshape(-1)[0])
            pred = sc["predictedMasks"][0].detach().cpu().numpy() > 0.5
            if pred.ndim == 3:
                pred = pred[..., 0]
            pred_low = pred & (np.arange(pred.shape[0])[:, None] >= ymid)
            low = float((pred_low & tgt_low).sum()) / float(
                (pred_low | tgt_low).sum() + 1e-6
            )
            xy = exp._screen_joint_xy(bv, rt, rr)[0].detach().cpu().numpy()
            if xy.ndim == 3:
                xy = xy[0]
            ang = math.degrees(
                math.atan2(float(xy[hi, 1] - xy[ti, 1]), float(xy[hi, 0] - xy[ti, 0]))
            )
            return {
                "iou": iou,
                "low": low,
                "ang": ang,
                "score": 0.55 * iou + 0.45 * low,
            }

        best_wing = {b: dict(a) for b, a in WING0.items()}
        best = score_wing(best_wing)
        for bone in WING_Y_BONES:
            base_y = float(best_wing.get(bone, {}).get("y", 0.0))
            for dy in (-120, -90, -60, -30, 0, 30, 60, 90, 120):
                trial = {bb: dict(aa) for bb, aa in best_wing.items()}
                trial.setdefault(bone, {})
                if bone in ("Bone_019", "Bone_022") and "x" not in trial[bone]:
                    trial[bone]["x"] = float(WING0.get(bone, {}).get("x", 0.0))
                trial[bone]["y"] = base_y + dy
                m = score_wing(trial)
                if m["score"] > best["score"]:
                    best, best_wing = m, trial
        for bone in WING_Y_BONES:
            cur = float(best_wing.get(bone, {}).get("y", 0.0))
            for dy in (-15, -10, -5, 5, 10, 15):
                trial = {bb: dict(aa) for bb, aa in best_wing.items()}
                trial.setdefault(bone, {})
                if bone in ("Bone_019", "Bone_022") and "x" not in trial[bone]:
                    trial[bone]["x"] = float(WING0.get(bone, {}).get("x", 0.0))
                trial[bone]["y"] = cur + dy
                m = score_wing(trial)
                if m["score"] > best["score"]:
                    best, best_wing = m, trial

        poses[str(fi)] = {
            RK: {
                "camera_forward": TIP[0],
                "camera_right": TIP[1],
                "camera_up": TIP[2],
            },
            **{b: dict(a) for b, a in best_wing.items()},
            **{b: dict(a) for b, a in LEG.items()},
        }
        per_frame.append({"frame": fi, "wing": best_wing, **best})
        print(
            f"f{fi:02d} iou={best['iou']:.3f} low={best['low']:.3f} "
            f"ht={best['ang']:.1f} wing={best_wing}",
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
        left = Image.new("RGB", (w, h), (0, 0, 0))
        s2 = sp.resize((w, h), Image.NEAREST)
        left.paste(s2, mask=s2.split()[-1])
        right = mesh.resize((w, h), Image.NEAREST)
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
        strip.paste(left, (0, 30))
        strip.paste(right, (w + 10, 30))
        strip.paste(Image.fromarray(ov), (2 * w + 20, 30))
        pf = per_frame[fi]
        d.text((4, 4), f"target f{fi:02d}", fill=(255, 230, 120))
        d.text(
            (w + 14, 4),
            f"mesh i={pf['iou']:.2f} L={pf['low']:.2f}",
            fill=(255, 230, 120),
        )
        d.text((2 * w + 24, 4), "overlay R=tgt B=mesh G=both", fill=(255, 230, 120))
        strip.save(prev / f"preview_{fi:02d}.png")

        sheet = Image.new("RGB", (w * 2 + 12, h + 28), (10, 10, 14))
        d2 = ImageDraw.Draw(sheet)
        sheet.paste(left, (0, 28))
        sheet.paste(right, (w + 12, 28))
        d2.text((4, 4), "sprite", fill=(255, 230, 120))
        d2.text((w + 16, 4), METHOD[:36], fill=(255, 230, 120))
        panels.append(sheet)

    gif_path = OUT / "chain_space_compare.gif"
    panels[0].save(
        gif_path, save_all=True, append_images=panels[1:], duration=160, loop=0
    )
    print("gif", gif_path, flush=True)

    elapsed = time.perf_counter() - t0
    payload = {
        "methodId": METHOD,
        "tip": TIP,
        "wingSeed": WING0,
        "poses": poses,
        "perFrame": per_frame,
        "cameraFit": str(SIDE).replace("\\", "/"),
        "elapsedSec": round(elapsed, 1),
        "budgetSec": 300,
        "withinBudget": elapsed <= 300,
        "meanIou": float(np.mean([p["iou"] for p in per_frame])),
        "meanLowIou": float(np.mean([p["low"] for p in per_frame])),
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
                "meanLowIou": payload["meanLowIou"],
                "elapsedSec": payload["elapsedSec"],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
