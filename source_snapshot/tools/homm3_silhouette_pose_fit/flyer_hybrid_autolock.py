"""Reusable flyer hybrid autolock: scale, tip, phase — not unit-specific Euler tables.

Pipeline class knobs (any flyer mesh + side/profile camera + sprite frames):
  1. Auto-scale camera pxPerWorld (+ small dy) to match sprite silhouette area/IoU.
  2. Resolve head→tail bones from roles or bind AABB extremes (no hardcoded Bone_NN).
  3. Sprite geometry flap phase (up/mid/down) from bbox height + mass top vs bottom.
  4. HT-gated tip search (facing-right + near-level head→tail) scored by IoU + phase band.
  5. Open-wing seed from lateral-signed wing bones; optional local wing refine under HT gate.
  6. Small root translation search on frame 0.

Ground units do not use this module — they stay on the DINOv3 path in the hybrid runner.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from roc_gpu_cascade_experiment import (
    MOTION_ROOT_KEY as ROOT_T_KEY,
    MOTION_ROOT_ROTATION_KEY as ROOT_R_KEY,
    GpuCascadeConfig,
    GpuCascadeExperiment,
)


def _mask_from_rgba(path: Path) -> np.ndarray:
    from PIL import Image

    a = np.array(Image.open(path).convert("RGBA"))
    return a[..., 3] > 8


def sprite_flap_phase(mask: np.ndarray, median_h: float) -> str:
    ys = np.where(mask)[0]
    if len(ys) == 0:
        return "mid"
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


def classify_frame_phases(frame_paths: Sequence[Path]) -> tuple[list[str], float]:
    heights: list[float] = []
    masks: list[np.ndarray] = []
    for path in frame_paths:
        m = _mask_from_rgba(Path(path))
        masks.append(m)
        ys = np.where(m)[0]
        heights.append(0.0 if len(ys) == 0 else float(ys.max() - ys.min() + 1))
    median_h = float(np.median(heights)) if heights else 1.0
    return [sprite_flap_phase(m, median_h) for m in masks], median_h


def load_bone_roles(path: Path | None) -> dict[str, str]:
    if path is None or not Path(path).is_file():
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("roles"), dict):
        return {str(k): str(v) for k, v in payload["roles"].items()}
    if isinstance(payload, dict):
        return {str(k): str(v) for k, v in payload.items() if isinstance(v, str)}
    return {}


def resolve_head_tail_bones(
    *,
    node_names: Sequence[str],
    rest_world: np.ndarray,
    bone_roles: Mapping[str, str] | None = None,
    head_bone: str | None = None,
    tail_bone: str | None = None,
) -> tuple[str, str]:
    """Pick anatomical head and tail bones without unit-specific Euler tables.

    Priority: explicit names → bone_roles Nose/Head + Tail/Pelvis → AABB extremes.
    """
    names = [str(n) for n in node_names]
    name_set = set(names)
    if head_bone and tail_bone and head_bone in name_set and tail_bone in name_set:
        return str(head_bone), str(tail_bone)

    roles = dict(bone_roles or {})
    head_keys = ("Nose", "Head", "head", "Snout", "Beak")
    tail_keys = ("Tail", "tail", "TailTip", "Pelvis", "Hips", "Root")
    head = next((roles[k] for k in head_keys if k in roles and roles[k] in name_set), None)
    tail = next((roles[k] for k in tail_keys if k in roles and roles[k] in name_set), None)
    if head and tail and head != tail:
        return head, tail

    # Bind AABB: bone nearest max/min along longest horizontal axis.
    pos = np.asarray(rest_world, dtype=np.float64).reshape(len(names), 3)
    spans = pos.max(axis=0) - pos.min(axis=0)
    axis = int(np.argmax(spans[[0, 2]]))  # 0→X, 1→Z mapped via [0,2]
    axis = 0 if axis == 0 else 2
    proj = pos[:, axis]
    head_i = int(np.argmax(proj))
    tail_i = int(np.argmin(proj))
    if head_i == tail_i:
        raise RuntimeError("head/tail bone discovery collapsed to one bone")
    return names[head_i], names[tail_i]


def leg_tuck_seed(
    *,
    node_names: Sequence[str],
    rest_world: np.ndarray,
    exclude: Sequence[str],
    bone_roles: Mapping[str, str] | None = None,
) -> dict[str, dict[str, float]]:
    """Tuck lower limbs under a side cam: role hips/ankles, else lowest skinned bones."""
    name_set = set(str(n) for n in node_names)
    exclude_set = set(exclude)
    roles = dict(bone_roles or {})
    role_bones = [
        roles[k]
        for k in ("LHip", "RHip", "LAnkle", "RAnkle", "LKnee", "RKnee", "Hip", "Pelvis")
        if k in roles and roles[k] in name_set and roles[k] not in exclude_set
    ]
    seed: dict[str, dict[str, float]] = {}
    if role_bones:
        for name in role_bones:
            seed[name] = {"x": -150.0}
        return seed
    pos = np.asarray(rest_world, dtype=np.float64).reshape(len(node_names), 3)

    def _is_joint(name: str) -> bool:
        # Prefer UniRig/Mixamo-style joint names; skip armature/mesh roots.
        n = str(name)
        if n in exclude_set:
            return False
        if n.startswith("Bone_"):
            return True
        lower = n.lower()
        if any(tok in lower for tok in ("armature", "unwrapped", "root", "output")):
            return False
        return n[:1].isalpha()

    bone_rows = [
        (float(pos[i, 1]), float(pos[i, 0]), str(node_names[i]), i)
        for i in range(len(node_names))
        if _is_joint(str(node_names[i]))
        and str(node_names[i]).startswith("Bone_")
        and str(node_names[i]) not in {"Bone_000", "Bone_001"}
        and str(node_names[i]) not in set(exclude)
    ]
    if not bone_rows:
        return seed
    # Legs: among laterally offset joints, pick the lowest on each side.
    # On flyer binds feet are often already raised (higher Y) while hips sit lower.
    lateral = [row for row in bone_rows if abs(row[1]) >= 0.05]
    left = [row for row in lateral if row[1] > 0.0]
    right = [row for row in lateral if row[1] < 0.0]
    picked: list[str] = []
    if left:
        picked.append(min(left, key=lambda row: row[0])[2])
    if right:
        picked.append(min(right, key=lambda row: row[0])[2])
    if len(picked) < 2:
        ys = np.asarray([row[0] for row in bone_rows], dtype=np.float64)
        y_lo = float(np.percentile(ys, 15))
        y_hi = float(np.percentile(ys, 55))
        hip_band = [row for row in bone_rows if y_lo <= row[0] <= y_hi]
        mid = sorted(hip_band, key=lambda row: abs(row[1]))[:2]
        picked = [row[2] for row in mid]
    for name in picked[:2]:
        seed[name] = {"x": -150.0}
    # Zero other low lateral bones so distal legs stay tucked at bind.
    for row in sorted(lateral, key=lambda r: r[0])[:8]:
        if row[2] not in seed:
            seed[row[2]] = {"x": 0.0}
    return seed


def open_wing_seed(wing_bones: Sequence[str], rest_world: np.ndarray, node_index: Mapping[str, int]) -> dict[str, dict[str, float]]:
    """Fallback open-wing prior from lateral rest signs (prefer discover_open_wing_seed)."""
    if not wing_bones:
        return {}
    pos = np.asarray(rest_world, dtype=np.float64)
    signed: list[tuple[str, float]] = []
    for name in wing_bones:
        if name not in node_index:
            continue
        i = int(node_index[name])
        signed.append((name, float(pos[i, 0])))
    if not signed:
        return {}
    left = sorted((n for n, x in signed if x >= 0.0), key=lambda n: -abs(float(pos[int(node_index[n]), 0])))
    right = sorted((n for n, x in signed if x < 0.0), key=lambda n: -abs(float(pos[int(node_index[n]), 0])))
    seed: dict[str, dict[str, float]] = {}
    for name in left[:2]:
        seed[name] = {"x": 150.0}
    for name in right[:2]:
        seed[name] = {"x": -150.0}
    remaining = [n for n, _ in signed if n not in seed]
    if remaining:
        mid = min(remaining, key=lambda n: abs(float(pos[int(node_index[n]), 0])))
        seed[mid] = {"y": -90.0}
    return seed


def discover_open_wing_seed(
    exp: GpuCascadeExperiment,
    *,
    frame_index: int,
    tip: tuple[float, float, float],
    root_t: Mapping[str, float],
    wing_bones: Sequence[str],
    rest_world: np.ndarray,
    node_index: Mapping[str, int],
    extra_bones: Mapping[str, Mapping[str, float]] | None,
    head_i: int,
    tail_i: int,
    phase: str,
) -> dict[str, dict[str, float]]:
    """Pick open-wing ±x pair by HT-gated IoU — not by rest-X heuristics alone."""
    pos = np.asarray(rest_world, dtype=np.float64)
    named = [n for n in wing_bones if n in node_index]
    if len(named) < 2:
        return open_wing_seed(wing_bones, rest_world, node_index)
    left = [n for n in named if float(pos[int(node_index[n]), 0]) >= 0.0]
    right = [n for n in named if float(pos[int(node_index[n]), 0]) < 0.0]
    if not left or not right:
        # No clear lateral split: try all unordered pairs with +x/-x.
        left, right = named, named
    mid_candidates = [
        min(named, key=lambda n: abs(float(pos[int(node_index[n]), 0])))
    ]
    best_seed = open_wing_seed(wing_bones, rest_world, node_index)
    best_score = -1e9
    # Cap pairs to keep autolock frugal; try both open-sign polarities.
    left_c = left[:4]
    right_c = right[:4]
    for lb in left_c:
        for rb in right_c:
            if lb == rb:
                continue
            for mid in mid_candidates:
                for sx, sy in ((150.0, -150.0), (-150.0, 150.0), (90.0, -90.0), (-90.0, 90.0)):
                    seed = {lb: {"x": float(sx)}, rb: {"x": float(sy)}}
                    mid_name = mid
                    if mid_name in seed:
                        # Open pair ate the mid candidate; use next-closest bone.
                        others = [
                            n
                            for n in named
                            if n not in seed
                        ]
                        if others:
                            mid_name = min(
                                others,
                                key=lambda n: abs(float(pos[int(node_index[n]), 0])),
                            )
                    if mid_name not in seed:
                        seed[mid_name] = {"y": -90.0}
                    row = score_tip_pose(
                        exp,
                        frame_index=frame_index,
                        tip=tip,
                        root_t=root_t,
                        wing=seed,
                        extra_bones=extra_bones,
                        head_i=head_i,
                        tail_i=tail_i,
                        phase=phase,
                        ht_max_deg=18.0,
                    )
                    if row is None:
                        continue
                    if float(row["score"]) > best_score:
                        best_score = float(row["score"])
                        best_seed = seed
                        print(
                            f"wing pair {lb}/{sx:+.0f} {rb}/{sy:+.0f} mid={mid_name} "
                            f"iou={row['iou']:.3f} score={row['score']:.3f}",
                            flush=True,
                        )
    return best_seed


def phase_wing_seed(
    base: Mapping[str, Mapping[str, float]],
    *,
    phase: str,
) -> dict[str, dict[str, float]]:
    """Default phase wing prior (prefer phase_wing_candidates + IoU pick)."""
    return phase_wing_candidates(base, phase=phase)[0]


def phase_wing_candidates(
    base: Mapping[str, Mapping[str, float]],
    *,
    phase: str,
) -> list[dict[str, dict[str, float]]]:
    """Phase-conditioned wing priors from the open-wing seed (no unit Euler tables)."""
    out: list[dict[str, dict[str, float]]] = []
    if phase == "up":
        for dy in (-120.0, 120.0, -60.0, 60.0):
            for mid_flip in (True, False):
                seed = {b: dict(a) for b, a in base.items()}
                for bone, axes in list(seed.items()):
                    if "x" in axes and abs(float(axes["x"])) >= 80.0:
                        axes["y"] = float(axes.get("y", 0.0)) + float(dy)
                    elif "y" in axes and mid_flip:
                        axes["y"] = -float(axes["y"])
                out.append(seed)
    elif phase == "down":
        # Mild distal tip fold / sweep so downstroke is not a frozen open pose.
        for tip_y in (0.0, -30.0, 30.0, -45.0, 45.0):
            for tip_z in (0.0, -20.0, 20.0):
                seed = {b: dict(a) for b, a in base.items()}
                for bone, axes in list(seed.items()):
                    if "x" in axes and abs(float(axes["x"])) >= 80.0:
                        if tip_y:
                            axes["y"] = float(axes.get("y", 0.0)) + float(tip_y)
                        if tip_z:
                            axes["z"] = float(axes.get("z", 0.0)) + float(tip_z)
                out.append(seed)
    else:
        out.append({b: dict(a) for b, a in base.items()})
    # De-dupe identical seeds.
    uniq: list[dict[str, dict[str, float]]] = []
    seen: set[str] = set()
    for seed in out:
        key = json.dumps(seed, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(seed)
    return uniq or [{b: dict(a) for b, a in base.items()}]


def pick_phase_wing_seed(
    exp: GpuCascadeExperiment,
    *,
    frame_index: int,
    phase: str,
    tip: tuple[float, float, float],
    root_t: Mapping[str, float],
    base_wing: Mapping[str, Mapping[str, float]],
    extra_bones: Mapping[str, Mapping[str, float]] | None,
    head_i: int,
    tail_i: int,
    ht_max_deg: float,
) -> dict[str, dict[str, float]]:
    best_seed = {b: dict(a) for b, a in base_wing.items()}
    best_score = -1e9
    for seed in phase_wing_candidates(base_wing, phase=phase):
        row = score_tip_pose(
            exp,
            frame_index=frame_index,
            tip=tip,
            root_t=root_t,
            wing=seed,
            extra_bones=extra_bones,
            head_i=head_i,
            tail_i=tail_i,
            phase=phase,
            ht_max_deg=ht_max_deg,
        )
        if row is None:
            continue
        if float(row["score"]) > best_score:
            best_score = float(row["score"])
            best_seed = {b: dict(a) for b, a in seed.items()}
    return best_seed


def write_scaled_camera(
    *,
    base_camera: Path,
    out_path: Path,
    scale: float,
    dy_px: float,
) -> Path:
    payload = json.loads(Path(base_camera).read_text(encoding="utf-8"))
    px = float(payload["pxPerWorld"]) * float(scale)
    offset = list(payload.get("screenOffsetPx") or [0.0, 0.0])
    if len(offset) < 2:
        offset = [0.0, 0.0]
    offset[1] = float(offset[1]) + float(dy_px)
    payload["pxPerWorld"] = px
    payload["screenOffsetPx"] = offset
    metrics = dict(payload.get("profileMetrics") or {})
    metrics["autoScale"] = {
        "baseCamera": str(base_camera).replace("\\", "/"),
        "scale": float(scale),
        "dyPx": float(dy_px),
        "pxPerWorld": px,
    }
    payload["profileMetrics"] = metrics
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out_path


def _make_exp(
    *,
    mesh: Path,
    camera_fit: Path,
    sprite_dir: Path,
    frame_index: int,
    resolution: tuple[int, int] = (160, 140),
) -> GpuCascadeExperiment:
    cfg = GpuCascadeConfig(
        score_mode="geometry",
        depth_weight=0.0,
        silhouette_weight=1.0,
        chroma_weight=0.0,
        motion_weight=0.0,
        collision_enabled=False,
        collision_weight=0.0,
        root_search_enabled=False,
        resolution=resolution,
    )
    cfg.validate()
    return GpuCascadeExperiment(
        src_glb=mesh,
        camera_fit=camera_fit,
        target_frame_dir=sprite_dir,
        frame_indices=(int(frame_index),),
        config=cfg,
    )


def _ht_metrics(
    exp: GpuCascadeExperiment,
    *,
    bone_vals,
    root_t,
    root_r,
    head_i: int,
    tail_i: int,
) -> tuple[float, float]:
    xy = exp._screen_joint_xy(bone_vals, root_t, root_r)[0].detach().cpu().numpy()
    if xy.ndim == 3:
        xy = xy[0]
    dx = float(xy[head_i, 0] - xy[tail_i, 0])
    dy = float(xy[head_i, 1] - xy[tail_i, 1])
    ang = math.degrees(math.atan2(dy, dx))
    return ang, dx


def _phase_bands(target_mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    tgt = target_mask > 0.5
    if tgt.ndim == 3:
        tgt = tgt[..., 0]
    ys = np.where(tgt)[0]
    y0, y1 = int(ys.min()), int(ys.max())
    top = tgt & (np.arange(tgt.shape[0])[:, None] < (y0 + 0.4 * (y1 - y0)))
    bot = tgt & (np.arange(tgt.shape[0])[:, None] >= (y0 + 0.6 * (y1 - y0)))
    return top, bot


def score_tip_pose(
    exp: GpuCascadeExperiment,
    *,
    frame_index: int,
    tip: tuple[float, float, float],
    root_t: Mapping[str, float],
    wing: Mapping[str, Mapping[str, float]],
    extra_bones: Mapping[str, Mapping[str, float]] | None,
    head_i: int,
    tail_i: int,
    phase: str,
    ht_max_deg: float,
) -> dict[str, Any] | None:
    pose: dict[str, Any] = {
        ROOT_R_KEY: {
            "camera_forward": float(tip[0]),
            "camera_right": float(tip[1]),
            "camera_up": float(tip[2]),
        },
        ROOT_T_KEY: {
            "forward": float(root_t.get("forward", 0.0)),
            "lateral": float(root_t.get("lateral", 0.0)),
            "vertical": float(root_t.get("vertical", 0.0)),
        },
    }
    for bone, axes in wing.items():
        pose[bone] = {k: float(v) for k, v in axes.items()}
    if extra_bones:
        for bone, axes in extra_bones.items():
            pose[bone] = {k: float(v) for k, v in axes.items()}
    bone_vals, rt, rr = exp._initial_pose_tensors({int(frame_index): pose})
    scored = exp.evaluate(bone_vals, rt, rr)
    iou = float(scored["silhouetteIoU"].detach().cpu().numpy().reshape(-1)[0])
    ang, head_r = _ht_metrics(exp, bone_vals=bone_vals, root_t=rt, root_r=rr, head_i=head_i, tail_i=tail_i)
    if head_r <= 0.0 or abs(ang) > float(ht_max_deg):
        return None
    pred = scored["predictedMasks"][0].detach().cpu().numpy() > 0.5
    if pred.ndim == 3:
        pred = pred[..., 0]
    tgt = exp.target_masks[0].detach().cpu().numpy()
    top_band, bot_band = _phase_bands(tgt)
    top = float((pred & top_band).sum()) / float((pred | top_band).sum() + 1e-6)
    bot = float((pred & bot_band).sum()) / float((pred | bot_band).sum() + 1e-6)
    if phase == "up":
        band = top
        score = 0.30 * iou + 0.70 * band - 0.010 * abs(ang)
    elif phase == "down":
        band = bot
        score = 0.50 * iou + 0.50 * band - 0.015 * abs(ang)
    else:
        band = 0.5 * (top + bot)
        score = 0.50 * iou + 0.50 * band - 0.015 * abs(ang)
    return {
        "iou": iou,
        "top": top,
        "bot": bot,
        "ang": ang,
        "headR": head_r,
        "band": band,
        "score": score,
        "tip": (float(tip[0]), float(tip[1]), float(tip[2])),
        "wing": {b: dict(a) for b, a in wing.items()},
    }


def search_tip(
    exp: GpuCascadeExperiment,
    *,
    frame_index: int,
    phase: str,
    root_t: Mapping[str, float],
    wing_seed: Mapping[str, Mapping[str, float]],
    extra_bones: Mapping[str, Mapping[str, float]] | None,
    head_i: int,
    tail_i: int,
    center: tuple[float, float, float] | None = None,
    coarse: bool = True,
    ht_max_deg: float = 12.0,
    yaw_anchor: float | None = None,
    yaw_max_delta: float = 25.0,
) -> dict[str, Any]:
    """HT-gated tip search. Coarse global grid or local refine around center.

    yaw_anchor keeps camera_up near the downstroke tip so upstroke search cannot
    spin into a top-down view (common failure when maximizing top-band alone).
    """
    best: dict[str, Any] | None = None

    def _yaw_ok(u: float) -> bool:
        if yaw_anchor is None:
            return True
        return abs(float(u) - float(yaw_anchor)) <= float(yaw_max_delta)

    if coarse and center is None:
        forwards = range(-40, 61, 20)
        rights = range(20, 91, 20)
        ups = range(-20, 61, 20)
        for f in forwards:
            for r in rights:
                for u in ups:
                    if not _yaw_ok(u):
                        continue
                    row = score_tip_pose(
                        exp,
                        frame_index=frame_index,
                        tip=(float(f), float(r), float(u)),
                        root_t=root_t,
                        wing=wing_seed,
                        extra_bones=extra_bones,
                        head_i=head_i,
                        tail_i=tail_i,
                        phase=phase,
                        ht_max_deg=ht_max_deg,
                    )
                    if row is None:
                        continue
                    if best is None or float(row["score"]) > float(best["score"]):
                        best = row
    else:
        c0 = center or (0.0, 45.0, 0.0)
        best = score_tip_pose(
            exp,
            frame_index=frame_index,
            tip=c0,
            root_t=root_t,
            wing=wing_seed,
            extra_bones=extra_bones,
            head_i=head_i,
            tail_i=tail_i,
            phase=phase,
            ht_max_deg=ht_max_deg,
        )
        for df in range(-20, 21, 10):
            for dr in range(-20, 21, 10):
                for du in range(-20, 21, 10):
                    tip = (c0[0] + df, c0[1] + dr, c0[2] + du)
                    if not _yaw_ok(tip[2]):
                        continue
                    row = score_tip_pose(
                        exp,
                        frame_index=frame_index,
                        tip=tip,
                        root_t=root_t,
                        wing=wing_seed,
                        extra_bones=extra_bones,
                        head_i=head_i,
                        tail_i=tail_i,
                        phase=phase,
                        ht_max_deg=ht_max_deg,
                    )
                    if row is None:
                        continue
                    if best is None or float(row["score"]) > float(best["score"]):
                        best = row
    if best is None:
        raise RuntimeError(
            f"flyer tip search found no HT-gated candidate "
            f"(frame={frame_index} phase={phase} ht_max={ht_max_deg})"
        )
    return best


def refine_wings(
    exp: GpuCascadeExperiment,
    *,
    frame_index: int,
    phase: str,
    tip: tuple[float, float, float],
    root_t: Mapping[str, float],
    wing0: Mapping[str, Mapping[str, float]],
    wing_bones: Sequence[str],
    extra_bones: Mapping[str, Mapping[str, float]] | None,
    head_i: int,
    tail_i: int,
    ht_max_deg: float = 12.0,
    deltas: Sequence[float] | None = None,
) -> dict[str, Any]:
    best = score_tip_pose(
        exp,
        frame_index=frame_index,
        tip=tip,
        root_t=root_t,
        wing=wing0,
        extra_bones=extra_bones,
        head_i=head_i,
        tail_i=tail_i,
        phase=phase,
        ht_max_deg=ht_max_deg,
    )
    if best is None:
        raise RuntimeError("wing refine: seed failed HT gate")
    # Finer steps read less "snapped" than a ±90 grid; keep a few larger
    # deltas so upstroke can still lift.
    step = tuple(deltas) if deltas is not None else (-60, -30, -15, 0, 15, 30, 60)
    wing = {b: dict(a) for b, a in best["wing"].items()}
    for bone in wing_bones:
        for ax in ("x", "y", "z"):
            # Keep primary open-x on the first seeded pair; refine other axes.
            if bone in wing0 and ax == "x" and "x" in wing0[bone] and abs(float(wing0[bone]["x"])) >= 80.0:
                continue
            base = float(wing.get(bone, {}).get(ax, 0.0))
            for d in step:
                trial = {bb: dict(aa) for bb, aa in wing.items()}
                trial.setdefault(bone, {})
                if bone in wing0 and "x" in wing0[bone] and "x" not in trial[bone]:
                    trial[bone]["x"] = float(wing0[bone]["x"])
                trial[bone][ax] = base + float(d)
                row = score_tip_pose(
                    exp,
                    frame_index=frame_index,
                    tip=tip,
                    root_t=root_t,
                    wing=trial,
                    extra_bones=extra_bones,
                    head_i=head_i,
                    tail_i=tail_i,
                    phase=phase,
                    ht_max_deg=ht_max_deg,
                )
                if row is None:
                    continue
                if float(row["score"]) > float(best["score"]):
                    best = row
                    wing = {b: dict(a) for b, a in row["wing"].items()}
    return best


def soft_tip_around(
    exp: GpuCascadeExperiment,
    *,
    frame_index: int,
    phase: str,
    tip_ref: tuple[float, float, float],
    root_t: Mapping[str, float],
    wing: Mapping[str, Mapping[str, float]],
    extra_bones: Mapping[str, Mapping[str, float]] | None,
    head_i: int,
    tail_i: int,
    ht_max_deg: float,
    max_delta: float = 8.0,
) -> dict[str, Any]:
    """Small attitude bob around a locked tip — keeps flap readable without dive drift.

    Searches one camera axis at a time so the cost stays linear (not 5^3).
    """
    best = score_tip_pose(
        exp,
        frame_index=frame_index,
        tip=tip_ref,
        root_t=root_t,
        wing=wing,
        extra_bones=extra_bones,
        head_i=head_i,
        tail_i=tail_i,
        phase=phase,
        ht_max_deg=ht_max_deg,
    )
    if best is None:
        raise RuntimeError("soft tip: reference tip failed HT gate")
    deltas = (-max_delta, -0.5 * max_delta, 0.0, 0.5 * max_delta, max_delta)
    tip = list(tip_ref)
    for axis in range(3):
        axis_best = best
        for d in deltas:
            trial = list(tip)
            trial[axis] = float(tip_ref[axis]) + float(d)
            row = score_tip_pose(
                exp,
                frame_index=frame_index,
                tip=(float(trial[0]), float(trial[1]), float(trial[2])),
                root_t=root_t,
                wing=wing,
                extra_bones=extra_bones,
                head_i=head_i,
                tail_i=tail_i,
                phase=phase,
                ht_max_deg=ht_max_deg,
            )
            if row is None:
                continue
            if float(row["score"]) > float(axis_best["score"]):
                axis_best = row
        best = axis_best
        tip = list(best["tip"])
    return best


def search_camera_scale(
    *,
    mesh: Path,
    base_camera: Path,
    sprite_dir: Path,
    out_dir: Path,
    tip: tuple[float, float, float],
    root_t: Mapping[str, float],
    wing_seed: Mapping[str, Mapping[str, float]],
    extra_bones: Mapping[str, Mapping[str, float]] | None,
    head_i: int,
    tail_i: int,
    phase: str = "mid",
    scales: Sequence[float] = (0.95, 1.0, 1.05, 1.1, 1.15),
    dy_px_values: Sequence[float] = (0.0, 10.0),
) -> dict[str, Any]:
    """Pick pxPerWorld scale (+dy) maximizing HT-gated IoU on frame 0."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    best: dict[str, Any] | None = None
    for scale in scales:
        for dy in dy_px_values:
            cam_path = write_scaled_camera(
                base_camera=base_camera,
                out_path=out_dir / f"cam_scale{scale:.2f}_dy{dy:.0f}.json",
                scale=float(scale),
                dy_px=float(dy),
            )
            exp = _make_exp(mesh=mesh, camera_fit=cam_path, sprite_dir=sprite_dir, frame_index=0)
            row = score_tip_pose(
                exp,
                frame_index=0,
                tip=tip,
                root_t=root_t,
                wing=wing_seed,
                extra_bones=extra_bones,
                head_i=head_i,
                tail_i=tail_i,
                phase=phase,
                ht_max_deg=18.0,  # looser while scale is unknown
            )
            if row is None:
                print(f"scale search scale={scale} dy={dy} rejected HT", flush=True)
                continue
            cand = {
                "scale": float(scale),
                "dyPx": float(dy),
                "cameraFit": str(cam_path).replace("\\", "/"),
                "iou": float(row["iou"]),
                "score": float(row["score"]),
                "ang": float(row["ang"]),
            }
            print(
                f"scale search scale={scale:.2f} dy={dy:.0f} "
                f"iou={cand['iou']:.3f} score={cand['score']:.3f}",
                flush=True,
            )
            if best is None or cand["iou"] > best["iou"]:
                best = cand
    if best is None:
        raise RuntimeError("flyer camera scale search found no HT-gated candidate")
    return best


def search_root_translation(
    exp: GpuCascadeExperiment,
    *,
    tip: tuple[float, float, float],
    wing: Mapping[str, Mapping[str, float]],
    extra_bones: Mapping[str, Mapping[str, float]] | None,
    head_i: int,
    tail_i: int,
    phase: str,
) -> dict[str, float]:
    best_t = {"forward": 0.0, "lateral": 0.0, "vertical": 0.0}
    best_score = -1e9
    for fwd in (-0.15, -0.1, -0.05, 0.0):
        for lat in (-0.1, -0.05, 0.0, 0.05):
            for vert in (-0.1, -0.05, 0.0):
                row = score_tip_pose(
                    exp,
                    frame_index=0,
                    tip=tip,
                    root_t={"forward": fwd, "lateral": lat, "vertical": vert},
                    wing=wing,
                    extra_bones=extra_bones,
                    head_i=head_i,
                    tail_i=tail_i,
                    phase=phase,
                    ht_max_deg=12.0,
                )
                if row is None:
                    continue
                if float(row["score"]) > best_score:
                    best_score = float(row["score"])
                    best_t = {"forward": fwd, "lateral": lat, "vertical": vert}
    return best_t


def autolock_flyer_clip(
    *,
    mesh: Path,
    base_camera: Path,
    sprite_dir: Path,
    out_dir: Path,
    wing_bones: Sequence[str],
    bone_roles_path: Path | None = None,
    head_bone: str | None = None,
    tail_bone: str | None = None,
    extra_bones: Mapping[str, Mapping[str, float]] | None = None,
    refine_wings_per_frame: bool = True,
    refine_bones: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Full flyer autolock → per-frame seeded poses + scaled camera + report."""
    refine_bone_list = tuple(refine_bones) if refine_bones is not None else tuple(wing_bones)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    frame_paths = sorted(Path(sprite_dir).glob("*.png"))
    if not frame_paths:
        raise RuntimeError(f"no sprites in {sprite_dir}")
    phases, median_h = classify_frame_phases(frame_paths)
    n = len(frame_paths)

    # Probe experiment on base cam for bone discovery + wing seed.
    probe = _make_exp(mesh=mesh, camera_fit=base_camera, sprite_dir=sprite_dir, frame_index=0)
    node_index = {name: i for i, name in enumerate(probe.node_names)}
    heads = probe._bind_joint_heads()
    rest = np.asarray(
        [heads[name] for name in probe.node_names],
        dtype=np.float64,
    )
    roles = load_bone_roles(bone_roles_path)
    head_name, tail_name = resolve_head_tail_bones(
        node_names=probe.node_names,
        rest_world=rest,
        bone_roles=roles,
        head_bone=head_bone,
        tail_bone=tail_bone,
    )
    head_i = int(node_index[head_name])
    tail_i = int(node_index[tail_name])
    wing_seed = open_wing_seed(wing_bones, rest, node_index)
    if extra_bones is None:
        extra_bones = leg_tuck_seed(
            node_names=probe.node_names,
            rest_world=rest,
            exclude=[head_name, tail_name, *wing_bones],
            bone_roles=roles,
        )
    print(
        f"flyer autolock head={head_name} tail={tail_name} "
        f"leg_tuck={list(extra_bones)} frames={n} median_h={median_h:.1f}",
        flush=True,
    )

    # Coarse tip under heuristic wings, then IoU-pick the open pair under that tip.
    tip0_row = search_tip(
        probe,
        frame_index=0,
        phase=phases[0],
        root_t={"forward": 0.0, "lateral": 0.0, "vertical": 0.0},
        wing_seed=wing_seed,
        extra_bones=extra_bones,
        head_i=head_i,
        tail_i=tail_i,
        coarse=True,
    )
    print(
        f"flyer coarse tip={tip0_row['tip']} iou={tip0_row['iou']:.3f} "
        f"ang={tip0_row['ang']:.1f}",
        flush=True,
    )
    wing_seed = discover_open_wing_seed(
        probe,
        frame_index=0,
        tip=tuple(tip0_row["tip"]),
        root_t={"forward": 0.0, "lateral": 0.0, "vertical": 0.0},
        wing_bones=wing_bones,
        rest_world=rest,
        node_index=node_index,
        extra_bones=extra_bones,
        head_i=head_i,
        tail_i=tail_i,
        phase=phases[0],
    )
    print(f"flyer wing_seed={wing_seed}", flush=True)

    # Lock tip on base cam under discovered wings, then scale-search.
    tip_base = search_tip(
        probe,
        frame_index=0,
        phase=phases[0],
        root_t={"forward": 0.0, "lateral": 0.0, "vertical": 0.0},
        wing_seed=wing_seed,
        extra_bones=extra_bones,
        head_i=head_i,
        tail_i=tail_i,
        center=tuple(tip0_row["tip"]),
        coarse=False,
    )
    scale_row = search_camera_scale(
        mesh=mesh,
        base_camera=base_camera,
        sprite_dir=sprite_dir,
        out_dir=out_dir / "scale_search",
        tip=tuple(tip_base["tip"]),
        root_t={"forward": 0.0, "lateral": 0.0, "vertical": 0.0},
        wing_seed=wing_seed,
        extra_bones=extra_bones,
        head_i=head_i,
        tail_i=tail_i,
        phase=phases[0],
    )
    camera_fit = Path(scale_row["cameraFit"])
    print(
        f"flyer scale chosen scale={scale_row['scale']} dy={scale_row['dyPx']} "
        f"iou={scale_row['iou']:.3f}",
        flush=True,
    )

    exp0 = _make_exp(mesh=mesh, camera_fit=camera_fit, sprite_dir=sprite_dir, frame_index=0)
    tip_locked = search_tip(
        exp0,
        frame_index=0,
        phase=phases[0],
        root_t={"forward": 0.0, "lateral": 0.0, "vertical": 0.0},
        wing_seed=wing_seed,
        extra_bones=extra_bones,
        head_i=head_i,
        tail_i=tail_i,
        center=tuple(tip_base["tip"]),
        coarse=False,
    )
    root_t = search_root_translation(
        exp0,
        tip=tuple(tip_locked["tip"]),
        wing=tip_locked["wing"],
        extra_bones=extra_bones,
        head_i=head_i,
        tail_i=tail_i,
        phase=phases[0],
    )
    print(f"flyer root_t={root_t} tip0={tip_locked['tip']}", flush=True)

    poses: dict[str, dict[str, Any]] = {}
    per_frame: list[dict[str, Any]] = []
    tip_ref = tuple(tip_locked["tip"])
    for fi in range(n):
        phase = phases[fi]
        exp = _make_exp(mesh=mesh, camera_fit=camera_fit, sprite_dir=sprite_dir, frame_index=fi)
        ht_gate = 16.0 if phase == "up" else 12.0
        # Soft vertical bob with flap (class policy — not a unit Euler table).
        frame_root_t = dict(root_t)
        if phase == "up":
            frame_root_t["vertical"] = float(root_t.get("vertical", 0.0)) + 0.04
        elif phase == "down":
            frame_root_t["vertical"] = float(root_t.get("vertical", 0.0)) - 0.02
        # Anchor tip; allow a small soft bob so body is not mannequin-stiff.
        wing_for_phase = pick_phase_wing_seed(
            exp,
            frame_index=fi,
            phase=phase,
            tip=tip_ref,
            root_t=frame_root_t,
            base_wing=wing_seed,
            extra_bones=extra_bones,
            head_i=head_i,
            tail_i=tail_i,
            ht_max_deg=ht_gate,
        )
        row = soft_tip_around(
            exp,
            frame_index=fi,
            phase=phase,
            tip_ref=tip_ref,
            root_t=frame_root_t,
            wing=wing_for_phase,
            extra_bones=extra_bones,
            head_i=head_i,
            tail_i=tail_i,
            ht_max_deg=ht_gate,
            max_delta=8.0,
        )
        # Distal/mid wing refine on every phase — downstroke used to stay frozen
        # at the open seed and read as stiff mannequin joints.
        if refine_wings_per_frame:
            row = refine_wings(
                exp,
                frame_index=fi,
                phase=phase,
                tip=tuple(row["tip"]),
                root_t=frame_root_t,
                wing0=row["wing"],
                wing_bones=refine_bone_list,
                extra_bones=extra_bones,
                head_i=head_i,
                tail_i=tail_i,
                ht_max_deg=ht_gate,
                deltas=(-45, -25, -10, 0, 10, 25, 45) if phase != "up" else None,
            )
            # Re-score soft tip after distal refine so attitude tracks the wing.
            row = soft_tip_around(
                exp,
                frame_index=fi,
                phase=phase,
                tip_ref=tuple(row["tip"]),
                root_t=frame_root_t,
                wing=row["wing"],
                extra_bones=extra_bones,
                head_i=head_i,
                tail_i=tail_i,
                ht_max_deg=ht_gate,
                max_delta=6.0,
            )
        tip = tuple(row["tip"])
        pose: dict[str, Any] = {
            ROOT_R_KEY: {
                "camera_forward": tip[0],
                "camera_right": tip[1],
                "camera_up": tip[2],
            },
            ROOT_T_KEY: dict(frame_root_t),
            **{b: dict(a) for b, a in row["wing"].items()},
        }
        if extra_bones:
            for b, a in extra_bones.items():
                pose[b] = dict(a)
        poses[str(fi)] = pose
        per_frame.append(
            {
                "frame": fi,
                "phase": phase,
                "tip": list(tip),
                "iou": float(row["iou"]),
                "top": float(row["top"]),
                "bot": float(row["bot"]),
                "ang": float(row["ang"]),
                "score": float(row["score"]),
            }
        )
        print(
            f"f{fi:02d} phase={phase} tip={tip[0]:.0f}/{tip[1]:.0f}/{tip[2]:.0f} "
            f"iou={row['iou']:.3f} top={row['top']:.3f} bot={row['bot']:.3f} "
            f"ang={row['ang']:.1f}",
            flush=True,
        )

    tip0_pose = (poses.get("0") or {}).get(ROOT_R_KEY) or {}
    tip0_list = [
        float(tip0_pose.get("camera_forward", tip_locked["tip"][0])),
        float(tip0_pose.get("camera_right", tip_locked["tip"][1])),
        float(tip0_pose.get("camera_up", tip_locked["tip"][2])),
    ]
    report = {
        "schema": "flyer_hybrid_autolock.v1",
        "headBone": head_name,
        "tailBone": tail_name,
        "wingBones": list(wing_bones),
        "wingSeed": wing_seed,
        "legTuck": dict(extra_bones or {}),
        "medianSpriteHeight": median_h,
        "phases": phases,
        "scale": scale_row,
        "rootTranslation": root_t,
        "tipFrame0": tip0_list,
        "cameraFit": str(camera_fit).replace("\\", "/"),
        "perFrame": per_frame,
        "poses": poses,
    }
    (out_dir / "autolock_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report
