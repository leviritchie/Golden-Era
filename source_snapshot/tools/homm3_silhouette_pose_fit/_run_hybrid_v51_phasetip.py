"""v51: scaled cam + rootxy + phase tips (down 32/52/24, up 12/72/34) + phase wings + optional up artic."""
from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy.ndimage import zoom

from roc_gpu_cascade_experiment import (
    MOTION_ROOT_KEY as TK,
    MOTION_ROOT_ROTATION_KEY as RK,
    GpuCascadeConfig,
    GpuCascadeExperiment,
)

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
METHOD = "hybrid_v51_sidecam_scale1p1_phasetip_up127234_down325224_legtuck"
OUT = ROOT / "artifacts/pose_picker_runs/hybrid_method_quad" / METHOD / "roc_move"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
SIDE = (
    ROOT
    / "artifacts/pose_picker_runs/h3_roc/move/initialization/flyer_side_profile_scaled_camera_fit.json"
)
SPRITE = ROOT / "artifacts/pose_picker_runs/h3_roc/move/frames_def12_nn_move"
DOWN_TIP = (32.0, 52.0, 24.0)
UP_TIP = (12.0, 72.0, 34.0)
MID_TIP = (22.0, 62.0, 28.0)
TRANS = (-0.1, -0.05, -0.05)
WING_DOWN = {"Bone_019": {"x": 90.0}, "Bone_022": {"x": -90.0}, "Bone_018": {"y": -90.0}}
WING_UP = {
    "Bone_019": {"x": 90.0},
    "Bone_022": {"x": -90.0, "y": -120.0},
    "Bone_018": {"y": 0.0},
    "Bone_013": {"z": 45.0},
}
LEG = {b: {"x": -150.0} for b in ("Bone_004", "Bone_008")}
LEG.update(
    {
        b: {"x": 0.0}
        for b in ("Bone_005", "Bone_006", "Bone_007", "Bone_009", "Bone_010", "Bone_011")
    }
)
WING_Y_BONES = ("Bone_017", "Bone_018", "Bone_019", "Bone_020", "Bone_021", "Bone_022", "Bone_013")


def sprite_phase(path: Path, median_h: float) -> str:
    a = np.array(Image.open(path).convert("RGBA"))
    m = a[..., 3] > 8
    ys = np.where(m)[0]
    h = float(ys.max() - ys.min() + 1)
    cy = float(ys.mean())
    top = cy - float(ys.min())
    bot = float(ys.max()) - cy
    if h >= median_h * 1.12 and top >= bot:
        return "up"
    if top > bot + 8:
        return "up"
    if bot > top + 8:
        return "down"
    return "mid"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frame_paths = sorted(SPRITE.glob("*.png"))
    if not frame_paths:
        raise SystemExit(f"no sprites in {SPRITE}")
    n = len(frame_paths)
    heights = []
    for p in frame_paths:
        a = np.array(Image.open(p).convert("RGBA"))
        m = a[..., 3] > 8
        ys = np.where(m)[0]
        heights.append(float(ys.max() - ys.min() + 1))
    median_h = float(np.median(heights))
    print(f"frames={n} method={METHOD} median_h={median_h:.1f}", flush=True)
    t0 = time.perf_counter()

    poses: dict[str, dict] = {}
    per_frame: list[dict] = []
    for fi in range(n):
        phase = sprite_phase(frame_paths[fi], median_h)
        if phase == "up":
            tip0, wing0 = UP_TIP, WING_UP
        elif phase == "down":
            tip0, wing0 = DOWN_TIP, WING_DOWN
        else:
            tip0, wing0 = MID_TIP, WING_DOWN

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
        y0, y1 = tys.min(), tys.max()
        top_band = tgt & (np.arange(tgt.shape[0])[:, None] < (y0 + 0.4 * (y1 - y0)))
        bot_band = tgt & (np.arange(tgt.shape[0])[:, None] >= (y0 + 0.6 * (y1 - y0)))
        ni = {name: i for i, name in enumerate(exp.node_names)}
        hi, ti = ni["Bone_014"], ni["Bone_012"]

        def score(tip: tuple[float, float, float], wing: dict) -> dict:
            pose = {
                RK: {
                    "camera_forward": float(tip[0]),
                    "camera_right": float(tip[1]),
                    "camera_up": float(tip[2]),
                },
                TK: {
                    "forward": TRANS[0],
                    "lateral": TRANS[1],
                    "vertical": TRANS[2],
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
            top = float((pred & top_band).sum()) / float((pred | top_band).sum() + 1e-6)
            bot = float((pred & bot_band).sum()) / float((pred | bot_band).sum() + 1e-6)
            xy = exp._screen_joint_xy(bv, rt, rr)[0].detach().cpu().numpy()
            if xy.ndim == 3:
                xy = xy[0]
            ang = math.degrees(
                math.atan2(float(xy[hi, 1] - xy[ti, 1]), float(xy[hi, 0] - xy[ti, 0]))
            )
            head_r = float(xy[hi, 0] - xy[ti, 0])
            if phase == "up":
                band = top
            elif phase == "down":
                band = bot
            else:
                band = 0.5 * (top + bot)
            return {
                "iou": iou,
                "top": top,
                "bot": bot,
                "ang": ang,
                "headR": head_r,
                "score": 0.5 * iou + 0.5 * band - 0.015 * abs(ang),
            }

        best_tip = tip0
        best_wing = {b: dict(a) for b, a in wing0.items()}
        best = score(best_tip, best_wing)

        # Local tip refine (±20 roll/pitch/yaw) under HT gate
        for df in range(-20, 21, 10):
            for dr in range(-20, 21, 10):
                for du in range(-20, 21, 10):
                    tip = (tip0[0] + df, tip0[1] + dr, tip0[2] + du)
                    m = score(tip, best_wing)
                    if m["headR"] <= 0 or abs(m["ang"]) > 12:
                        continue
                    if m["score"] > best["score"]:
                        best, best_tip = m, tip

        # Wing axis refine
        for bone in WING_Y_BONES:
            for ax in ("x", "y", "z"):
                if bone in ("Bone_019", "Bone_022") and ax == "x":
                    continue
                base = float(best_wing.get(bone, {}).get(ax, 0.0))
                for d in (-90, -60, -30, 0, 30, 60, 90):
                    trial = {bb: dict(aa) for bb, aa in best_wing.items()}
                    trial.setdefault(bone, {})
                    if bone in ("Bone_019", "Bone_022") and "x" not in trial[bone]:
                        trial[bone]["x"] = float(wing0.get(bone, {}).get("x", 0.0))
                    trial[bone][ax] = base + d
                    m = score(best_tip, trial)
                    if m["headR"] <= 0 or abs(m["ang"]) > 12:
                        continue
                    if m["score"] > best["score"]:
                        best, best_wing = m, trial

        poses[str(fi)] = {
            RK: {
                "camera_forward": best_tip[0],
                "camera_right": best_tip[1],
                "camera_up": best_tip[2],
            },
            TK: {
                "forward": TRANS[0],
                "lateral": TRANS[1],
                "vertical": TRANS[2],
            },
            **{b: dict(a) for b, a in best_wing.items()},
            **{b: dict(a) for b, a in LEG.items()},
        }
        per_frame.append(
            {
                "frame": fi,
                "phase": phase,
                "tip": best_tip,
                "wing": best_wing,
                **best,
            }
        )
        print(
            f"f{fi:02d} phase={phase} tip={tuple(round(x,1) for x in best_tip)} "
            f"iou={best['iou']:.3f} top={best['top']:.3f} bot={best['bot']:.3f} "
            f"ht={best['ang']:.1f}",
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
        tip = pf["tip"]
        d.text((4, 4), f"target f{fi:02d} {pf['phase']}", fill=(255, 230, 120))
        d.text(
            (w + 14, 4),
            f"mesh i={pf['iou']:.2f} tip=({tip[0]:.0f},{tip[1]:.0f},{tip[2]:.0f})",
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
        "downTip": DOWN_TIP,
        "upTip": UP_TIP,
        "midTip": MID_TIP,
        "rootTranslation": {
            "forward": TRANS[0],
            "lateral": TRANS[1],
            "vertical": TRANS[2],
        },
        "wingDown": WING_DOWN,
        "wingUp": WING_UP,
        "poses": poses,
        "perFrame": per_frame,
        "cameraFit": str(SIDE).replace("\\", "/"),
        "elapsedSec": round(elapsed, 1),
        "budgetSec": 300,
        "withinBudget": elapsed <= 300,
        "meanIou": float(np.mean([p["iou"] for p in per_frame])),
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
                "frames": [
                    {
                        "f": p["frame"],
                        "phase": p["phase"],
                        "iou": round(p["iou"], 3),
                        "tip": [round(x, 1) for x in p["tip"]],
                    }
                    for p in per_frame
                ],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
