#!/usr/bin/env python3
"""Map tracked 2D joints onto each crusader walk sprite (stick-figure GIF).

This deliberately does NOT project the 3D mesh skeleton. It places the
tracked landmark joints on each sprite frame and connects them so you can
see the joints move with the animation.

  py -3 tools/homm3_silhouette_pose_fit/render_walk_sprite_mapped_skeleton.py
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
DEFAULT_FRAMES = ROOT / "artifacts/crusader_pose_pipeline/source_frames/nn_upscale_g00_move"
DEFAULT_KPT = (
    ROOT
    / "artifacts/crusader_pose_pipeline/out_fit/g00_move/sprite_landmarks/keypoints.json"
)
DEFAULT_OUT = ROOT / "artifacts/crusader_pose_pipeline/out_fit/walk_sprite_mapped_skeleton"

# Stick-figure edges in landmark space.
EDGES = [
    ("Nose", "Neck"),
    ("Neck", "MidHip"),
    ("Neck", "RShoulder"),
    ("RShoulder", "RElbow"),
    ("RElbow", "RWrist"),
    ("RWrist", "WeaponTip"),
    ("Neck", "LShoulder"),
    ("LShoulder", "LElbow"),
    ("LElbow", "LWrist"),
    ("MidHip", "RHip"),
    ("RHip", "RKnee"),
    ("RKnee", "RAnkle"),
    ("MidHip", "LHip"),
    ("LHip", "LKnee"),
    ("LKnee", "LAnkle"),
]

COLORS = {
    "Nose": (255, 80, 80),
    "Neck": (255, 160, 80),
    "MidHip": (255, 255, 80),
    "RShoulder": (80, 255, 120),
    "RElbow": (80, 220, 180),
    "RWrist": (80, 200, 255),
    "WeaponTip": (255, 40, 255),
    "LShoulder": (180, 120, 255),
    "LElbow": (200, 150, 255),
    "LWrist": (220, 180, 255),
    "RHip": (120, 200, 120),
    "RKnee": (100, 180, 100),
    "RAnkle": (80, 160, 80),
    "LHip": (120, 160, 220),
    "LKnee": (100, 140, 200),
    "LAnkle": (80, 120, 180),
}


def _load_frame_joints(kpt: dict, frame_index: int) -> dict[str, tuple[float, float]]:
    frames = kpt.get("frames") or []
    if frame_index < 0 or frame_index >= len(frames):
        raise SystemExit(f"keypoints missing frame {frame_index}")
    joints = frames[frame_index].get("joints") or {}
    out: dict[str, tuple[float, float]] = {}
    for name, j in joints.items():
        if not j or not j.get("visible", True):
            continue
        out[name] = (float(j["x"]), float(j["y"]))
    return out


def _draw_mapped(
    sprite_path: Path,
    joints_xy: dict[str, tuple[float, float]],
    *,
    label: str,
    pad: int = 24,
) -> Image.Image:
    sp = Image.open(sprite_path).convert("RGBA")
    # Canvas = sprite native pixels so landmark x/y land exactly on the art.
    canvas = Image.new("RGBA", (sp.width + pad * 2, sp.height + pad * 2), (0, 0, 0, 255))
    canvas.paste(sp, (pad, pad), sp)
    d = ImageDraw.Draw(canvas)

    def pt(name: str) -> tuple[int, int] | None:
        if name not in joints_xy:
            return None
        x, y = joints_xy[name]
        return int(round(x + pad)), int(round(y + pad))

    for a, b in EDGES:
        pa, pb = pt(a), pt(b)
        if pa is None or pb is None:
            continue
        d.line([pa, pb], fill=(0, 0, 0), width=5)
        d.line([pa, pb], fill=(0, 255, 90), width=3)

    for name, (x, y) in joints_xy.items():
        p = (int(round(x + pad)), int(round(y + pad)))
        rgb = COLORS.get(name, (255, 255, 255))
        r = 7 if name == "WeaponTip" else 5
        d.ellipse([p[0] - r - 1, p[1] - r - 1, p[0] + r + 1, p[1] + r + 1], fill=(0, 0, 0))
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=rgb)
        d.text((p[0] + r + 2, p[1] - 6), name, fill=rgb)

    d.text((8, 8), label, fill=(255, 255, 0))
    d.text((8, 24), f"mappedJoints={len(joints_xy)} (2D landmarks, not mesh projection)", fill=(200, 200, 80))
    return canvas.convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-dir", type=Path, default=DEFAULT_FRAMES)
    ap.add_argument("--keypoints", type=Path, default=DEFAULT_KPT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--duration-ms", type=int, default=160)
    args = ap.parse_args()

    frames_dir = args.frames_dir.resolve()
    kpt_path = args.keypoints.resolve()
    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not kpt_path.is_file():
        raise SystemExit(f"keypoints missing: {kpt_path}")
    frames = sorted(frames_dir.glob("frame_*.png"))
    if not frames:
        raise SystemExit(f"no frames in {frames_dir}")

    kpt = json.loads(kpt_path.read_text(encoding="utf-8"))
    n = min(len(frames), len(kpt.get("frames") or []))
    if n < 1:
        raise SystemExit("no overlapping sprite/keypoint frames")

    gif_frames: list[Image.Image] = []
    paths: list[str] = []
    for i in range(n):
        joints = _load_frame_joints(kpt, i)
        if len(joints) < 6:
            raise SystemExit(f"frame {i}: too few visible joints ({len(joints)})")
        im = _draw_mapped(
            frames[i],
            joints,
            label=f"walk mapped skeleton f{i:02d}",
        )
        out_path = out_dir / f"mapped_{i:02d}.png"
        im.save(out_path)
        gif_frames.append(im)
        paths.append(str(out_path).replace("\\", "/"))
        print(f"[mapped-skel] frame {i} joints={len(joints)}", flush=True)

    # Uniform canvas size for GIF (pad to max).
    mw = max(im.width for im in gif_frames)
    mh = max(im.height for im in gif_frames)
    normalized = []
    for im in gif_frames:
        canvas = Image.new("RGB", (mw, mh), (0, 0, 0))
        canvas.paste(im, ((mw - im.width) // 2, (mh - im.height) // 2))
        normalized.append(canvas)

    gif_path = out_dir / "walk_sprite_mapped_skeleton.gif"
    normalized[0].save(
        gif_path,
        save_all=True,
        append_images=normalized[1:],
        duration=int(args.duration_ms),
        loop=0,
        optimize=False,
    )
    report = {
        "ok": True,
        "gif": str(gif_path).replace("\\", "/"),
        "frames": paths,
        "frameCount": n,
        "keypoints": str(kpt_path).replace("\\", "/"),
        "method": "2d_landmark_stick_figure_on_sprite",
        "notes": (
            "Joints are the tracked sprite landmarks placed in sprite pixel space "
            "and connected as a stick figure. Not a projection of the 3D Mixamo mesh pose."
        ),
        "proof": "generated — mapped 2D skeleton on walk sprites; not OE runtime",
    }
    (out_dir / "walk_sprite_mapped_skeleton_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"ok": True, "gif": report["gif"], "frames": n}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
