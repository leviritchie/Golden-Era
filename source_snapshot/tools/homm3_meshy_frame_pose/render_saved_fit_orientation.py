"""Replay a fitted candidate from its saved motion matrices at diagnostic camera yaws.

This is deliberately narrower than ``reel_meshy71_candidate.py``: it does not reconstruct a
canonical T-pose comparison or rebake source/candidate motion from a registration.  It consumes the
fitted bind and the exact ``retargeted_motion.npz`` emitted by ``fit_mesh_rest_pipeline.py`` so a
front/back inspection cannot be mistaken for a different retargeting experiment.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "artifacts/homm3_owned_bind"))
sys.path.insert(0, str(ROOT / "tools/homm3_meshy_frame_pose"))

import exp_tpose as render  # noqa: E402
import preview_exact_reference_bind as pv  # noqa: E402
from owned_rerig.glb_io import load_render_surface  # noqa: E402


def skin(values: np.ndarray, joints: np.ndarray, weights: np.ndarray, rotations: np.ndarray, offsets: np.ndarray | None = None) -> np.ndarray:
    result = np.zeros_like(values, dtype=float)
    for slot in range(joints.shape[1]):
        ids = joints[:, slot]
        moved = np.einsum("nij,nj->ni", rotations[ids], values)
        if offsets is not None:
            moved += offsets[ids]
        result += moved * weights[:, slot, None]
    return result


def keyframe_indices(labels: list[str]) -> list[int]:
    indices = []
    for clip in ("g02_idle", "g00_move", "g12_attack_front", "g15_shoot_front", "g05_death"):
        matches = [i for i, label in enumerate(labels) if label.endswith(clip)]
        if matches:
            indices.append(matches[len(matches) // 2])
    return indices


def _save_yaw(out: Path, unit: str, surface: dict, delivered: dict, positions: np.ndarray, frames: np.ndarray, normals: np.ndarray, labels: list[str], yaw: float, preview_scale: int) -> dict:
    from PIL import Image, ImageDraw

    render.PANEL = (360 * int(preview_scale), 520 * int(preview_scale))
    yaw_dir = out / f"yaw{int(yaw):03d}"
    yaw_dir.mkdir(parents=True, exist_ok=True)
    cloud = np.concatenate([positions, frames.reshape(-1, 3)])
    view = render.camera(yaw, cloud)
    images = []
    raw = []
    for index, points in enumerate(frames):
        panel = render.textured(view, deformed=points, normals=normals[index], surface=surface, indices=surface["indices"])
        render.label(panel, labels[index])
        image = Image.fromarray(np.clip(panel, 0, 255).astype("uint8"))
        images.append(image)
        raw.append(image.copy())
    if not images:
        raise ValueError("saved motion contains no frames")
    master = yaw_dir / f"{unit}_saved_motion.gif"
    images[0].save(master, save_all=True, append_images=images[1:], duration=100, loop=0, optimize=False)
    selected = [raw[i] for i in keyframe_indices(labels)]
    keyframes = None
    if selected:
        keyframes = yaw_dir / f"{unit}_saved_motion_keyframes.png"
        sheet = Image.new("RGB", (sum(image.width for image in selected), max(image.height for image in selected)))
        offset = 0
        for image in selected:
            sheet.paste(image, (offset, 0))
            offset += image.width
        sheet.save(keyframes)
    first = yaw_dir / f"{unit}_saved_motion_first_frame.png"
    ImageDraw.Draw(raw[0]).text((6, 5), f"{unit} | saved fitted motion | camera yaw {yaw:g}", fill="white")
    raw[0].save(first)
    return {
        "yaw": yaw,
        "masterReel": str(master.resolve()).replace("\\", "/"),
        "keyframes": str(keyframes.resolve()).replace("\\", "/") if keyframes else None,
        "firstFrame": str(first.resolve()).replace("\\", "/"),
        "frames": len(frames),
    }


def run(args: argparse.Namespace) -> int:
    bind = Path(args.bind).resolve()
    motion_path = Path(args.motion).resolve()
    run_dir = Path(args.run_dir).resolve()
    out = Path(args.out).resolve()
    delivered = pv.load_delivered_skeleton(bind)
    surface = load_render_surface(bind)
    motion = np.load(motion_path)
    rotations = np.asarray(motion["rotations"], dtype=np.float64)
    offsets = np.asarray(motion["offsets"], dtype=np.float64)
    if rotations.ndim != 4 or offsets.ndim != 3 or rotations.shape[0] != offsets.shape[0]:
        raise ValueError("retargeted motion must contain matching frame rotations and offsets")
    if rotations.shape[1] != len(delivered["names"]):
        raise ValueError("saved motion joint count does not match fitted bind skeleton")
    positions = np.asarray(delivered["positions"], dtype=np.float64)
    joints = np.asarray(delivered["joints"], dtype=np.int64)
    weights = np.asarray(delivered["weights"], dtype=np.float64)
    frames = np.asarray([skin(positions, joints, weights, r, t) for r, t in zip(rotations, offsets)])
    rest_normals = np.asarray(surface["normals"], dtype=np.float64)
    normals = np.asarray([skin(rest_normals, joints, weights, r) for r in rotations])
    normals /= np.maximum(np.linalg.norm(normals, axis=2, keepdims=True), 1e-12)
    master = json.loads((run_dir / "linked_master/master_sequence/master_sequence.json").read_text(encoding="utf-8"))
    unit = str(master.get("unit") or run_dir.name)
    labels = [f"{unit} | {row['clipKey']}" for row in master["frames"]]
    if len(labels) != len(frames):
        raise ValueError(f"saved motion frame count {len(frames)} does not match master labels {len(labels)}")
    outputs = [_save_yaw(out, unit, surface, delivered, positions, frames, normals, labels, float(yaw), args.preview_scale) for yaw in args.yaw]
    report = {
        "schema": "homm3.saved-fit-orientation-diagnostic.v1",
        "proof": "generated-artifact saved fitted motion replay only",
        "unit": unit,
        "bind": str(bind).replace("\\", "/"),
        "motion": str(motion_path).replace("\\", "/"),
        "runDir": str(run_dir).replace("\\", "/"),
        "cameraYaws": [float(yaw) for yaw in args.yaw],
        "outputs": outputs,
    }
    report_path = out / "saved_fit_orientation_report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"unit": unit, "report": str(report_path), "frames": len(frames), "cameraYaws": args.yaw}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", required=True)
    parser.add_argument("--motion", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--yaw", nargs="+", type=float, default=[0.0, 25.0, 180.0])
    parser.add_argument("--preview-scale", type=int, default=4)
    args = parser.parse_args()
    if args.preview_scale < 1:
        parser.error("--preview-scale must be at least 1")
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
