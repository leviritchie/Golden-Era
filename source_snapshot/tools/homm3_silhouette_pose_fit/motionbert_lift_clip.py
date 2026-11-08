#!/usr/bin/env python3
"""
Run MotionBERT temporal 2D→3D lift on a DWPose keypoints.json clip.

Free/open-source stack (MIT MotionBERT + our DWPose). Not a paid service.

Steps:
  1. Convert OpenPose-18 DWPose joints → AlphaPose/Halpe-26 JSON (MotionBERT wild input)
  2. Build a short mp4 from the sprite frames (for size/fps metadata)
  3. Run MotionBERT pose3d (temporal transformer) with --pixel
  4. Convert H36M-17 X3D back to OpenPose-named keypoints.json for blender_fit_from_keypoints.py

  python motionbert_lift_clip.py --keypoints dwpose/keypoints.json --frames-dir ... --out-dir ...
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
MOTIONBERT_ROOT = ROOT / "tools" / "third_party" / "MotionBERT"
DEFAULT_PYTHON = ROOT / "tools" / ".venvs" / "homm3_motionbert" / "Scripts" / "python.exe"
DEFAULT_CKPT = (
    MOTIONBERT_ROOT
    / "checkpoint"
    / "pose3d"
    / "FT_MB_lite_MB_ft_h36m_global_lite"
    / "best_epoch.bin"
)
DEFAULT_CONFIG = MOTIONBERT_ROOT / "configs" / "pose3d" / "MB_ft_h36m_global_lite.yaml"

# OpenPose body-18 names (DWPose export order).
OPENPOSE18 = [
    "Nose",
    "Neck",
    "RShoulder",
    "RElbow",
    "RWrist",
    "LShoulder",
    "LElbow",
    "LWrist",
    "MidHip",
    "RHip",
    "RKnee",
    "RAnkle",
    "LHip",
    "LKnee",
    "LAnkle",
    "REye",
    "LEye",
    "REar",
]

# H36M-17 index → OpenPose name (MotionBERT / dataset_wild.halpe2h36m order).
H36M_TO_OPENPOSE = {
    0: "MidHip",
    1: "RHip",
    2: "RKnee",
    3: "RAnkle",
    4: "LHip",
    5: "LKnee",
    6: "LAnkle",
    8: "Neck",
    9: "Nose",
    11: "LShoulder",
    12: "LElbow",
    13: "LWrist",
    14: "RShoulder",
    15: "RElbow",
    16: "RWrist",
}


def _joint_xy_score(joints: dict, name: str) -> tuple[float, float, float]:
    j = joints.get(name) or {}
    return float(j.get("x", 0.0)), float(j.get("y", 0.0)), float(j.get("score", 0.0))


def openpose_frame_to_halpe26(joints: dict) -> list[float]:
    """Flatten Halpe-26 keypoints as [x,y,score] * 26 for AlphaPose-style JSON."""
    # Halpe indices used by MotionBERT.halpe2h36m — fill unused with zeros.
    mapping = {
        0: "Nose",
        1: "LEye",
        2: "REye",
        3: "LEar",  # may be missing from OP18
        4: "REar",
        5: "LShoulder",
        6: "RShoulder",
        7: "LElbow",
        8: "RElbow",
        9: "LWrist",
        10: "RWrist",
        11: "LHip",
        12: "RHip",
        13: "LKnee",
        14: "RKnee",
        15: "LAnkle",
        16: "RAnkle",
        17: "Nose",  # Head proxy
        18: "Neck",
        19: "MidHip",
    }
    out: list[float] = []
    for i in range(26):
        name = mapping.get(i)
        if name is None:
            out.extend([0.0, 0.0, 0.0])
            continue
        x, y, s = _joint_xy_score(joints, name)
        # LEar missing in OP18 export — zero is fine (MotionBERT maps Head/Neck separately).
        out.extend([x, y, s])
    return out


def write_alphapose_json(kpt_report: dict, out_path: Path) -> int:
    frames = sorted(kpt_report["frames"], key=lambda f: int(f["frameIndex"]))
    items = []
    for fr in frames:
        kps = openpose_frame_to_halpe26(fr["joints"])
        items.append(
            {
                "image_id": f"frame_{int(fr['frameIndex']):02d}.png",
                "category_id": 1,
                "keypoints": kps,
                "score": float(fr.get("meanScore") or 0.5),
                "idx": 0,
            }
        )
    out_path.write_text(json.dumps(items, indent=2), encoding="utf-8")
    return len(items)


def write_clip_video(frame_paths: list[Path], out_mp4: Path, fps: float = 12.0) -> tuple[int, int]:
    if not frame_paths:
        raise RuntimeError("no frames for video")
    imgs = []
    for p in frame_paths:
        im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
        if im is None:
            raise RuntimeError(f"failed to read {p}")
        if im.shape[2] == 4:
            # Composite on black for MotionBERT size metadata.
            bgr = im[:, :, :3].copy()
            a = im[:, :, 3:4].astype(np.float32) / 255.0
            bgr = (bgr.astype(np.float32) * a).astype(np.uint8)
        else:
            bgr = im
        imgs.append(bgr)
    h, w = imgs[0].shape[:2]
    for i, im in enumerate(imgs):
        if im.shape[0] != h or im.shape[1] != w:
            imgs[i] = cv2.resize(im, (w, h), interpolation=cv2.INTER_AREA)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    writer = cv2.VideoWriter(
        str(out_mp4),
        cv2.VideoWriter_fourcc(*"mp4v"),
        float(fps),
        (w, h),
    )
    if not writer.isOpened():
        raise RuntimeError(f"VideoWriter failed for {out_mp4}")
    for im in imgs:
        writer.write(im)
    writer.release()
    return w, h


def run_motionbert(
    *,
    python_exe: Path,
    json_path: Path,
    vid_path: Path,
    out_dir: Path,
    clip_len: int,
) -> Path:
    if not python_exe.is_file():
        raise RuntimeError(f"MotionBERT python missing: {python_exe}")
    if not DEFAULT_CKPT.is_file():
        raise RuntimeError(f"MotionBERT checkpoint missing: {DEFAULT_CKPT}")
    runner = Path(__file__).resolve().parent / "_motionbert_infer_runner.py"
    cmd = [
        str(python_exe),
        str(runner),
        "--config",
        str(DEFAULT_CONFIG),
        "--evaluate",
        str(DEFAULT_CKPT),
        "--json_path",
        str(json_path),
        "--vid_path",
        str(vid_path),
        "--out_path",
        str(out_dir),
        "--clip_len",
        str(int(clip_len)),
        "--pixel",
    ]
    print("Running:", " ".join(cmd), flush=True)
    proc = subprocess.run(cmd, cwd=str(MOTIONBERT_ROOT))
    if proc.returncode != 0:
        raise RuntimeError(f"MotionBERT infer failed rc={proc.returncode}")
    npy = out_dir / "X3D.npy"
    if not npy.is_file():
        raise RuntimeError(f"missing MotionBERT output {npy}")
    return npy


def x3d_to_keypoints_report(
    x3d: np.ndarray,
    source_report: dict,
    *,
    score_floor: float = 0.35,
) -> dict:
    """
    x3d: (T, 17, 3) pixel-space MotionBERT output.
    Emit OpenPose-named 2D joints from XY; keep Z as optional depth.
    """
    frames_src = sorted(source_report["frames"], key=lambda f: int(f["frameIndex"]))
    if x3d.shape[0] != len(frames_src):
        raise RuntimeError(f"X3D length {x3d.shape[0]} != source frames {len(frames_src)}")
    frames_out = []
    for t, fr in enumerate(frames_src):
        joints = {}
        # Carry unused OP joints with low score so schema stays familiar.
        for name in OPENPOSE18:
            joints[name] = {
                "x": 0.0,
                "y": 0.0,
                "score": 0.0,
                "visible": False,
                "source": "motionbert_missing",
            }
        for hi, name in H36M_TO_OPENPOSE.items():
            x, y, z = float(x3d[t, hi, 0]), float(x3d[t, hi, 1]), float(x3d[t, hi, 2])
            # Prefer source visibility/score when available; else floor.
            src = (fr.get("joints") or {}).get(name) or {}
            score = float(src.get("score", score_floor))
            if score < score_floor:
                score = score_floor
            joints[name] = {
                "x": x,
                "y": y,
                "z": z,
                "score": score,
                "visible": True,
                "source": "motionbert_xy",
            }
        # Eyes/ears: keep DWPose 2D if present (MotionBERT H36M has no ears).
        for name in ("REye", "LEye", "REar", "LEar"):
            src = (fr.get("joints") or {}).get(name)
            if src and src.get("visible"):
                joints[name] = {
                    "x": float(src["x"]),
                    "y": float(src["y"]),
                    "score": float(src.get("score", 0.2)),
                    "visible": True,
                    "source": "dwpose_passthrough",
                }
        nf = {
            "frameIndex": int(fr["frameIndex"]),
            "sourcePath": fr.get("sourcePath"),
            "transform": fr.get("transform"),
            "variant": "motionbert_lift",
            "visibleJoints": sum(1 for j in joints.values() if j.get("visible")),
            "meanScore": float(np.mean([j["score"] for j in joints.values() if j.get("visible")])),
            "joints": joints,
        }
        frames_out.append(nf)

    return {
        "unitSid": source_report.get("unitSid"),
        "clipId": source_report.get("clipId"),
        "detector": "dwpose_onnx+motionbert_pose3d",
        "frameCountExpected": len(frames_out),
        "frameCountOk": len(frames_out),
        "failures": [],
        "frames": frames_out,
        "ok": True,
        "motionBert": {
            "checkpoint": str(DEFAULT_CKPT).replace("\\", "/"),
            "config": str(DEFAULT_CONFIG).replace("\\", "/"),
            "joints": 17,
            "layout": "h36m",
        },
        "proof": "generated artifact validated — MotionBERT temporal lift; not OE runtime proven",
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--keypoints", required=True, type=Path, help="DWPose keypoints.json")
    ap.add_argument(
        "--frame-paths",
        nargs="*",
        default=None,
        help="Explicit ordered frame image paths (else use sourcePath from keypoints)",
    )
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    ap.add_argument("--fps", type=float, default=12.0)
    ap.add_argument("--clip-len", type=int, default=243)
    args = ap.parse_args()

    report = json.loads(args.keypoints.read_text(encoding="utf-8"))
    if not report.get("ok"):
        print(f"refuse: keypoints not ok: {args.keypoints}", file=sys.stderr)
        return 2

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.frame_paths:
        frame_paths = [Path(p) for p in args.frame_paths]
    else:
        frames = sorted(report["frames"], key=lambda f: int(f["frameIndex"]))
        frame_paths = [Path(f["sourcePath"]) for f in frames]
    for p in frame_paths:
        if not p.is_file():
            print(f"missing frame: {p}", file=sys.stderr)
            return 2

    ap_json = out_dir / "alphapose_halpe.json"
    n = write_alphapose_json(report, ap_json)
    print(f"[motionbert] wrote {n} AlphaPose/Halpe frames -> {ap_json}", flush=True)

    vid = out_dir / "clip.mp4"
    w, h = write_clip_video(frame_paths, vid, fps=float(args.fps))
    print(f"[motionbert] clip {w}x{h} -> {vid}", flush=True)

    npy = run_motionbert(
        python_exe=args.python,
        json_path=ap_json,
        vid_path=vid,
        out_dir=out_dir,
        clip_len=int(args.clip_len),
    )
    x3d = np.load(npy)
    print(f"[motionbert] X3D shape={x3d.shape}", flush=True)

    lifted = x3d_to_keypoints_report(x3d, report)
    out_json = out_dir / "keypoints_motionbert.json"
    out_json.write_text(json.dumps(lifted, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "keypointsPath": str(out_json.resolve()).replace("\\", "/"),
                "x3dPath": str(npy.resolve()).replace("\\", "/"),
                "frames": len(lifted["frames"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
