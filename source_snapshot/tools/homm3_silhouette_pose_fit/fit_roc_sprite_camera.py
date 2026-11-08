#!/usr/bin/env python3
"""Fit a camera-plane contract from the Roc bind skeleton to frame-zero.

The Roc sprite is a face-right profile.  An unconstrained Procrustes search over
random view bases minimizes landmark error by folding in large screen roll and
produces a tall end-on / front view that does not match the sprite silhouette.

Preferred construction (this tool's default when --bind-proj is given):
  recover the ortho basis from an authored cam -X projection (bind_proj_mX),
  enforce beak image-right + upright, then scale/offset to the sprite alpha bbox.

Fallback (--samples): profile-prior random search with composite scoring.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.spatial.transform import Rotation


def scale_offset_fit(projected: np.ndarray, target: np.ndarray) -> tuple[float, np.ndarray]:
    p = projected - projected.mean(0)
    t = target - target.mean(0)
    scale = float((p * t).sum() / max(float((p * p).sum()), 1e-12))
    offset = target.mean(0) - projected.mean(0) * scale
    return scale, offset


def sprite_bbox_scale_offset(basis: np.ndarray, xyz: np.ndarray, sprite_path: Path) -> tuple[float, np.ndarray]:
    rgba = np.asarray(Image.open(sprite_path).convert("RGBA"))
    ys, xs = np.where(rgba[:, :, 3] > 8)
    if ys.size == 0:
        raise SystemExit(f"no opaque pixels in {sprite_path}")
    sb = np.array([xs.min(), ys.min(), xs.max(), ys.max()], dtype=float)
    projected = xyz @ basis.T
    scale = float(
        min(
            (sb[2] - sb[0]) / max(float(np.ptp(projected[:, 0])), 1e-9),
            (sb[3] - sb[1]) / max(float(np.ptp(projected[:, 1])), 1e-9),
        )
        * 0.92
    )
    offset = np.array([(sb[0] + sb[2]) * 0.5, (sb[1] + sb[3]) * 0.5]) - projected.mean(0) * scale
    return scale, offset


def orthonormalize_rows(basis: np.ndarray) -> np.ndarray:
    right = basis[0] / max(float(np.linalg.norm(basis[0])), 1e-12)
    down = basis[1] - right * float(np.dot(basis[1], right))
    down = down / max(float(np.linalg.norm(down)), 1e-12)
    return np.stack([right, down], axis=0)


def enforce_face_right_upright(basis: np.ndarray, beak: np.ndarray, root: np.ndarray) -> np.ndarray:
    basis = orthonormalize_rows(basis)
    right, down = basis
    up = -down
    if float((beak - root) @ right) <= 0.0:
        right = -right
        down = -down
        up = -down
    if float(up[2]) < 0.0:
        right = -right
        down = -down
    return orthonormalize_rows(np.stack([right, down], axis=0))


def recover_basis_from_bind_proj(bind_proj: dict) -> np.ndarray:
    names = list(bind_proj["bones"])
    world = np.asarray([bind_proj["bones"][n]["world"] for n in names], dtype=float)
    pixels = np.asarray([[bind_proj["bones"][n]["x"], bind_proj["bones"][n]["y"]] for n in names], dtype=float)
    design = np.concatenate([world, np.ones((len(world), 1))], axis=1)
    affine, *_ = np.linalg.lstsq(design, pixels, rcond=None)
    linear = affine[:3].T
    scale = float(np.linalg.norm(linear, axis=1).mean())
    basis = linear / max(scale, 1e-12)
    q, _ = np.linalg.qr(basis.T)
    basis = q.T.copy()
    if float(np.dot(basis[0], linear[0])) < 0:
        basis[0] *= -1.0
    if float(np.dot(basis[1], linear[1])) < 0:
        basis[1] *= -1.0
    return orthonormalize_rows(basis)


def apply_roll(basis: np.ndarray, degrees: float) -> np.ndarray:
    rad = math.radians(degrees)
    c, s = math.cos(rad), math.sin(rad)
    return np.array([[c, -s], [s, c]], dtype=float) @ basis


def view_metrics(basis: np.ndarray, xyz: np.ndarray, long_axis: np.ndarray, i_root: int, i_beak: int) -> dict:
    basis = orthonormalize_rows(basis)
    right, down = basis
    up = -down
    forward = np.cross(right, up)
    forward = forward / max(float(np.linalg.norm(forward)), 1e-12)
    span_r = float(np.ptp(xyz @ right))
    span_u = float(np.ptp(xyz @ up))
    return {
        "basis": basis,
        "right": right,
        "up": up,
        "forward": forward,
        "depth_long": abs(float(forward @ long_axis)),
        "horiz": abs(float(right @ long_axis)),
        "aspect": span_r / max(span_u, 1e-9),
        "beak_dx": float((xyz[i_beak] - xyz[i_root]) @ right),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skeleton", type=Path, required=True)
    ap.add_argument("--keypoints", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--bind-proj", type=Path, help="Preferred: bind_proj_mX.json (cam -X, beak RIGHT)")
    ap.add_argument("--sprite", type=Path, help="Opaque sprite used for bbox scale (defaults to keypoints frame path if absent)")
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--samples", type=int, default=120000)
    ap.add_argument("--roll-deg", type=float, default=25.0)
    ap.add_argument("--roll-step", type=float, default=2.0)
    args = ap.parse_args()

    skeleton = json.loads(args.skeleton.read_text(encoding="utf-8"))
    keypoints = json.loads(args.keypoints.read_text(encoding="utf-8"))
    frame = keypoints["frames"][0]
    world_map = {b["name"]: np.asarray(b["world"], dtype=float) for b in skeleton["bones"]}
    target_map = {
        name: np.asarray([point["x"], point["y"]], dtype=float)
        for name, point in frame["joints"].items()
        if name in world_map
    }
    names = sorted(target_map)
    xyz = np.asarray([world_map[name] for name in names])
    target = np.asarray([target_map[name] for name in names])
    root_name = "Bone_000" if "Bone_000" in names else names[0]
    beak_name = next((n for n in ("Bone_028", "Bone_002", "Bone_003") if n in names), names[min(1, len(names) - 1)])
    i_root = names.index(root_name)
    i_beak = names.index(beak_name)

    sprite_path = args.sprite
    if sprite_path is None:
        # Common pilot layout: frames_nn_shadow_culled/00.png next to camera fit out dir.
        guess = args.out.parent / "frames_nn_shadow_culled" / "00.png"
        sprite_path = guess if guess.exists() else None

    if args.bind_proj is not None:
        bind_proj = json.loads(args.bind_proj.read_text(encoding="utf-8"))
        basis = recover_basis_from_bind_proj(bind_proj)
        basis = enforce_face_right_upright(basis, world_map[beak_name], world_map[root_name])
        if sprite_path is not None:
            scale, offset = sprite_bbox_scale_offset(basis, xyz, sprite_path)
            policy = "bind_proj_mX_face_right_sprite_bbox_scale"
        else:
            scale, offset = scale_offset_fit(xyz @ basis.T, target)
            policy = "bind_proj_mX_face_right_landmark_scale"
        metrics = view_metrics(basis, xyz, np.linalg.svd(xyz - xyz.mean(0), full_matrices=False)[2][0], i_root, i_beak)
        aligned = xyz @ basis.T * scale + offset
        error = float(np.sqrt(((aligned - target) ** 2).sum(1)).mean())
        out = {
            "unitSid": "h3_roc",
            "clip": "move_g0_rife",
            "sourceFrame": 0,
            "sourceResolution": [1350, 1200],
            "basisScreenRows": basis.tolist(),
            "pxPerWorld": scale,
            "screenOffsetPx": offset.tolist(),
            "meanLandmarkErrorPx": error,
            "depthPolicy": "preserve_bind_depth_relative_to_Bone_000",
            "cameraPolicy": policy,
            "profileMetrics": {
                "projectedAspect": metrics["aspect"],
                "beakImageRight": metrics["beak_dx"] > 0,
                "upZ": float(metrics["up"][2]),
                "view": metrics["forward"].tolist(),
                "screenRight": metrics["right"].tolist(),
                "screenUp": metrics["up"].tolist(),
                "source": str(args.bind_proj),
            },
            "proof": "Recovered from bind_proj cam -X (beak RIGHT). Bind diving pose remains; camera is the profile contract.",
            "landmarks": names,
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"ok": True, "cameraPolicy": policy, "meanLandmarkErrorPx": error, "pxPerWorld": scale, "out": str(args.out)}))
        return 0

    # Fallback profile-prior search (no bind_proj).
    long_axis = np.linalg.svd(xyz - xyz.mean(0), full_matrices=False)[2][0]
    rolls = np.arange(-args.roll_deg, args.roll_deg + 1e-9, args.roll_step)
    rng = np.random.default_rng(args.seed)
    best: dict | None = None
    accepted = 0
    for _ in range(args.samples):
        forward = rng.normal(size=3)
        forward = forward / max(float(np.linalg.norm(forward)), 1e-12)
        if abs(float(forward @ long_axis)) > 0.28:
            continue
        world_up = np.array([0.0, 0.0, 1.0], dtype=float)
        right = np.cross(forward, world_up)
        if float(np.linalg.norm(right)) < 1e-6:
            continue
        right = right / np.linalg.norm(right)
        up = np.cross(right, forward)
        up = up / np.linalg.norm(up)
        seed = np.stack([right, -up], axis=0)
        for roll in rolls:
            metrics = view_metrics(apply_roll(seed, float(roll)), xyz, long_axis, i_root, i_beak)
            if metrics["depth_long"] > 0.28 or metrics["aspect"] < 1.35 or metrics["beak_dx"] <= 0 or metrics["horiz"] < 0.70:
                continue
            if sprite_path is not None:
                scale, offset = sprite_bbox_scale_offset(metrics["basis"], xyz, sprite_path)
            else:
                scale, offset = scale_offset_fit(xyz @ metrics["basis"].T, target)
            if scale <= 0:
                continue
            aligned = xyz @ metrics["basis"].T * scale + offset
            error = float(np.sqrt(((aligned - target) ** 2).sum(1)).mean())
            score = error + 40.0 * metrics["depth_long"] - 15.0 * metrics["aspect"]
            accepted += 1
            metrics.update({"scale": scale, "offset": offset, "error": error, "score": score, "rollDeg": float(roll)})
            if best is None or score < best["score"]:
                best = metrics
    if best is None:
        raise SystemExit("no profile camera found; pass --bind-proj bind_proj_mX.json")

    basis = best["basis"]
    scale, offset, error = best["scale"], best["offset"], best["error"]
    out = {
        "unitSid": "h3_roc",
        "clip": "move_g0_rife",
        "sourceFrame": 0,
        "sourceResolution": [1350, 1200],
        "basisScreenRows": basis.tolist(),
        "pxPerWorld": scale,
        "screenOffsetPx": offset.tolist(),
        "meanLandmarkErrorPx": error,
        "depthPolicy": "preserve_bind_depth_relative_to_Bone_000",
        "cameraPolicy": "face_right_profile_prior_composite",
        "profileMetrics": {
            "depthAlongBody": best["depth_long"],
            "bodyHorizontal": best["horiz"],
            "projectedAspect": best["aspect"],
            "acceptedCandidates": accepted,
        },
        "proof": "profile-prior fallback; prefer --bind-proj for roc",
        "landmarks": names,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "meanLandmarkErrorPx": error, "pxPerWorld": scale, "acceptedCandidates": accepted, "out": str(args.out)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
