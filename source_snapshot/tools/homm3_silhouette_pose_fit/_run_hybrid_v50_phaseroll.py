"""v50: scaled cam + rootxy + phase wing seeds + per-frame tip roll (flyer extra rotation)."""
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
METHOD = "hybrid_v50_sidecam_scale1p1_heightphase_roll_rootxy_legtuck"
OUT = ROOT / "artifacts/pose_picker_runs/hybrid_method_quad" / METHOD / "roc_move"
MESH = ROOT / "artifacts/meshy_downloads/h3_roc_smartrigged.glb"
SIDE = (
    ROOT
    / "artifacts/pose_picker_runs/hybrid_method_quad/flyer_scale_search_v48/flyer_move_scaled_camera_fit.json"
)
SPRITE = ROOT / "artifacts/pose_picker_runs/h3_roc/move/frames_def12_nn_move"
TIP0 = (32.0, 52.0, 24.0)
TRANS = (-0.1, -0.05, -0.05)
WING_DOWN = {"Bone_019": {"x": 90.0}, "Bone_022": {"x": -90.0}, "Bone_018": {"y": -90.0}}
WING_UP = {
    "Bone_019": {"x": 90.0, "y": 30.0},
    "Bone_022": {"x": -90.0, "y": -120.0},
    "Bone_018": {"y": 0.0},
}
LEG = {b: {"x": -150.0} for b in ("Bone_004", "Bone_008")}
LEG.update(
    {
        b: {"x": 0.0}
        for b in ("Bone_005", "Bone_006", "Bone_007", "Bone_009", "Bone_010", "Bone_011")
    }
)


def sprite_phase(mask: np.ndarray, *, median_h: float) -> str:
    ys = np.where(mask)[0]
    h = float(ys.max() - ys.min() + 1)
    cy = float(ys.mean())
    top_ext = cy - float(ys.min())
    bot_ext = float(ys.max()) - cy
    # Tall frames are extreme flap; prefer top-extent for upstroke.
    if h >= median_h * 1.12 and top_ext >= bot_ext:
        return "up"
    if top_ext > bot_ext + 8:
        return "up"
    if bot_ext > top_ext + 8:
        return "down"
    return "mid"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    frame_paths = sorted(SPRITE.glob("*.png"))
    if not frame_paths:
        raise SystemExit(f"no sprites in {SPRITE}")
    n = len(frame_paths)
    print(f"frames={n} method={METHOD}", flush=True)
    t0 = time.perf_counter()

    # Precompute median sprite height for phase gating.
    heights: list[float] = []
    for p in frame_paths:
        a = np.array(Image.open(p).convert("RGBA"))
        m = a[..., 3] > 8
        ys = np.where(m)[0]
        heights.append(float(ys.max() - ys.min() + 1))
    median_h = float(np.median(heights))
    print(f"median_sprite_h={median_h:.1f}", flush=True)

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
        phase = sprite_phase(tgt, median_h=median_h * (tgt.shape[0] / heights[fi]))
        # Prefer full-res phase when available.
        a = np.array(Image.open(frame_paths[fi]).convert("RGBA"))
        phase = sprite_phase(a[..., 3] > 8, median_h=median_h)
        wing_seed = WING_UP if phase == "up" else WING_DOWN
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
            xy = exp._screen_joint_xy(bv, rt, rr)[0].detach().cpu().numpy()
            if xy.ndim == 3:
                xy = xy[0]
            ang = math.degrees(
                math.atan2(float(xy[hi, 1] - xy[ti, 1]), float(xy[hi, 0] - xy[ti, 0]))
            )
            head_r = float(xy[hi, 0] - xy[ti, 0])
            return {
                "iou": iou,
                "ang": ang,
                "headR": head_r,
                "score": iou - 0.01 * abs(ang),
            }

        # Flyer-aware extra rotation: search camera_forward (roll) ±50 around tip.
        best_tip = TIP0
        best_wing = {b: dict(a) for b, a in wing_seed.items()}
        best = score(best_tip, best_wing)
        for droll in range(-50, 51, 10):
            for dpitch in (-10, 0, 10):
                tip = (TIP0[0] + droll, TIP0[1] + dpitch, TIP0[2])
                m = score(tip, best_wing)
                if m["headR"] <= 0 or abs(m["ang"]) > 20:
                    continue
                if m["score"] > best["score"]:
                    best, best_tip = m, tip
        # Wing Y refine under chosen tip
        for bone in ("Bone_018", "Bone_019", "Bone_021", "Bone_022"):
            base_y = float(best_wing.get(bone, {}).get("y", 0.0))
            for dy in (-120, -90, -60, -30, 0, 30, 60, 90, 120):
                trial = {bb: dict(aa) for bb, aa in best_wing.items()}
                trial.setdefault(bone, {})
                if bone in ("Bone_019", "Bone_022") and "x" not in trial[bone]:
                    trial[bone]["x"] = float(wing_seed.get(bone, {}).get("x", 0.0))
                trial[bone]["y"] = base_y + dy
                m = score(best_tip, trial)
                if m["headR"] <= 0 or abs(m["ang"]) > 20:
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
            f"iou={best['iou']:.3f} ht={best['ang']:.1f} wing={best_wing}",
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
        "tipSeed": TIP0,
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
                "phases": [(p["frame"], p["phase"], round(p["iou"], 3)) for p in per_frame],
            },
            indent=2,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
