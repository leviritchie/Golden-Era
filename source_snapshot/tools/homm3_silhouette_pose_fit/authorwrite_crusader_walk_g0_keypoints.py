#!/usr/bin/env python3
"""Human-authored walk g0 landmarks (eye-tracked on NN sprites).

Writes keypoints JSON + remaps the stick-figure GIF. Not mesh projection.
"""
from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(r"V:/Games/Olden Era Playtest Tweak")
FRAMES = ROOT / "artifacts/crusader_pose_pipeline/source_frames/nn_upscale_g00_move"
OUT = ROOT / "artifacts/crusader_pose_pipeline/out_fit/walk_sprite_mapped_skeleton"
KPT_OUT = OUT / "keypoints_authored_walk_g0.json"

# Eye-authored in sprite pixel space (1098x876). Facing-right crusader:
# R* = character right / sword side; L* = character left / shield side.
# Walk cycle notes from frame inspection:
#  f0-f1: near two-hand sword raise, left leg forward
#  f2-f3: sword lowers/levels, shield more visible, stride continues
#  f4-f5: sword down-forward, shield up, opposite foot lead
#  f6-f7: recover toward next stride, sword swings

FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    {  # f00 — sword up-right; R=sword arm (screen-left shoulder); L foot forward
        "Nose": (565, 335),
        "Neck": (555, 375),
        "RShoulder": (500, 405),
        "RElbow": (555, 460),
        "RWrist": (630, 505),
        "WeaponTip": (805, 300),
        "LShoulder": (605, 400),
        "LElbow": (645, 450),
        "LWrist": (615, 520),
        "MidHip": (555, 530),
        "RHip": (515, 550),
        "RKnee": (480, 615),
        "RAnkle": (460, 688),
        "LHip": (600, 550),
        "LKnee": (645, 620),
        "LAnkle": (685, 692),
    },
    {  # f01
        "Nose": (560, 320),
        "Neck": (550, 360),
        "RShoulder": (495, 390),
        "RElbow": (545, 455),
        "RWrist": (620, 515),
        "WeaponTip": (820, 305),
        "LShoulder": (600, 385),
        "LElbow": (640, 435),
        "LWrist": (610, 530),
        "MidHip": (550, 515),
        "RHip": (510, 535),
        "RKnee": (485, 605),
        "RAnkle": (470, 678),
        "LHip": (595, 535),
        "LKnee": (650, 610),
        "LAnkle": (690, 682),
    },
    {  # f02 — shield visible on L; sword more level; RWrist on forward grip
        "Nose": (560, 305),
        "Neck": (550, 345),
        "RShoulder": (490, 380),
        "RElbow": (535, 440),
        "RWrist": (620, 495),
        "WeaponTip": (790, 395),
        "LShoulder": (595, 375),
        "LElbow": (645, 425),
        "LWrist": (675, 460),
        "MidHip": (555, 505),
        "RHip": (515, 525),
        "RKnee": (495, 595),
        "RAnkle": (485, 668),
        "LHip": (600, 525),
        "LKnee": (625, 605),
        "LAnkle": (615, 682),
    },
    {  # f03 — sword near-horizontal; RWrist forward on hilt toward tip
        "Nose": (565, 315),
        "Neck": (555, 355),
        "RShoulder": (495, 390),
        "RElbow": (540, 450),
        "RWrist": (610, 505),
        "WeaponTip": (755, 435),
        "LShoulder": (605, 385),
        "LElbow": (650, 435),
        "LWrist": (560, 520),
        "MidHip": (560, 520),
        "RHip": (520, 540),
        "RKnee": (500, 610),
        "RAnkle": (490, 682),
        "LHip": (605, 540),
        "LKnee": (640, 615),
        "LAnkle": (645, 692),
    },
    {  # f04 — sword tip down-forward; R foot forward
        "Nose": (545, 310),
        "Neck": (540, 360),
        "RShoulder": (475, 395),
        "RElbow": (450, 475),
        "RWrist": (440, 550),
        "WeaponTip": (655, 685),
        "LShoulder": (595, 390),
        "LElbow": (645, 455),
        "LWrist": (635, 505),
        "MidHip": (545, 545),
        "RHip": (520, 565),
        "RKnee": (565, 645),
        "RAnkle": (605, 708),
        "LHip": (580, 565),
        "LKnee": (525, 645),
        "LAnkle": (495, 708),
    },
    {  # f05
        "Nose": (545, 300),
        "Neck": (540, 350),
        "RShoulder": (480, 385),
        "RElbow": (465, 465),
        "RWrist": (475, 550),
        "WeaponTip": (645, 695),
        "LShoulder": (595, 380),
        "LElbow": (640, 445),
        "LWrist": (630, 495),
        "MidHip": (545, 535),
        "RHip": (520, 555),
        "RKnee": (560, 635),
        "RAnkle": (590, 708),
        "LHip": (580, 555),
        "LKnee": (540, 640),
        "LAnkle": (515, 708),
    },
    {  # f06
        "Nose": (545, 295),
        "Neck": (540, 345),
        "RShoulder": (485, 380),
        "RElbow": (465, 465),
        "RWrist": (455, 550),
        "WeaponTip": (705, 680),
        "LShoulder": (590, 375),
        "LElbow": (625, 440),
        "LWrist": (635, 480),
        "MidHip": (545, 535),
        "RHip": (520, 555),
        "RKnee": (565, 630),
        "RAnkle": (580, 702),
        "LHip": (580, 555),
        "LKnee": (525, 635),
        "LAnkle": (505, 702),
    },
    {  # f07 — sword extends right; R foot forward
        "Nose": (565, 310),
        "Neck": (555, 360),
        "RShoulder": (505, 395),
        "RElbow": (570, 455),
        "RWrist": (660, 505),
        "WeaponTip": (890, 450),
        "LShoulder": (605, 390),
        "LElbow": (645, 450),
        "LWrist": (660, 490),
        "MidHip": (560, 540),
        "RHip": (535, 560),
        "RKnee": (585, 635),
        "RAnkle": (625, 698),
        "LHip": (595, 560),
        "LKnee": (540, 640),
        "LAnkle": (495, 698),
    },
]

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


def _joint_dict(xy: dict[str, tuple[int, int]]) -> dict:
    return {
        name: {"x": float(x), "y": float(y), "visible": True, "score": 1.0, "source": "human_eye"}
        for name, (x, y) in xy.items()
    }


def _draw(sprite: Path, joints: dict[str, tuple[int, int]], label: str) -> Image.Image:
    sp = Image.open(sprite).convert("RGBA")
    pad = 24
    canvas = Image.new("RGBA", (sp.width + pad * 2, sp.height + pad * 2), (0, 0, 0, 255))
    canvas.paste(sp, (pad, pad), sp)
    d = ImageDraw.Draw(canvas)

    def pt(n: str):
        x, y = joints[n]
        return int(x + pad), int(y + pad)

    for a, b in EDGES:
        if a not in joints or b not in joints:
            continue
        pa, pb = pt(a), pt(b)
        d.line([pa, pb], fill=(0, 0, 0), width=5)
        d.line([pa, pb], fill=(0, 255, 90), width=3)
    for name, (x, y) in joints.items():
        p = (int(x + pad), int(y + pad))
        rgb = COLORS.get(name, (255, 255, 255))
        r = 7 if name == "WeaponTip" else 5
        d.ellipse([p[0] - r - 1, p[1] - r - 1, p[0] + r + 1, p[1] + r + 1], fill=(0, 0, 0))
        d.ellipse([p[0] - r, p[1] - r, p[0] + r, p[1] + r], fill=rgb)
        d.text((p[0] + r + 2, p[1] - 6), name, fill=rgb)
    d.text((8, 8), label, fill=(255, 255, 0))
    d.text((8, 24), "human eye-authored landmarks on sprite", fill=(220, 220, 80))
    return canvas.convert("RGB")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    sprites = sorted(FRAMES.glob("frame_*.png"))
    if len(sprites) != len(FRAMES_XY):
        raise SystemExit(f"frame count mismatch sprites={len(sprites)} authored={len(FRAMES_XY)}")

    frames_out = []
    gif_frames = []
    for i, (sp, xy) in enumerate(zip(sprites, FRAMES_XY)):
        frames_out.append(
            {
                "frameIndex": i,
                "path": str(sp).replace("\\", "/"),
                "joints": _joint_dict(xy),
            }
        )
        im = _draw(sp, xy, f"walk eye-mapped f{i:02d}")
        out_png = OUT / f"authored_{i:02d}.png"
        im.save(out_png)
        gif_frames.append(im)
        print(f"[authored] f{i:02d} -> {out_png.name}", flush=True)

    mw = max(im.width for im in gif_frames)
    mh = max(im.height for im in gif_frames)
    norm = []
    for im in gif_frames:
        c = Image.new("RGB", (mw, mh), (0, 0, 0))
        c.paste(im, ((mw - im.width) // 2, (mh - im.height) // 2))
        norm.append(c)
    gif = OUT / "walk_sprite_authored_skeleton.gif"
    norm[0].save(gif, save_all=True, append_images=norm[1:], duration=180, loop=0, optimize=False)

    doc = {
        "ok": True,
        "unitSid": "h3_crusader",
        "clipId": "move_g0",
        "method": "human_eye_landmark_authoring",
        "proof": "authored by inspecting each NN walk sprite; not OE runtime; not mesh projection",
        "frames": frames_out,
    }
    KPT_OUT.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    # Also replace the display GIF name users already have open.
    display = OUT / "walk_sprite_mapped_skeleton.gif"
    norm[0].save(display, save_all=True, append_images=norm[1:], duration=180, loop=0, optimize=False)
    print(json.dumps({"ok": True, "gif": str(display).replace("\\", "/"), "keypoints": str(KPT_OUT).replace("\\", "/")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
