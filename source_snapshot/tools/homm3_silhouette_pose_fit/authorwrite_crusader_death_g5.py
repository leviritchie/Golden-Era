#!/usr/bin/env python3
"""Eye-authored g05_death landmarks (NN sprites). Hard gate for fixed-length IK."""
from __future__ import annotations

import json

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames/nn_upscale_g05_death"
OUT = ART / "out_fit/g05_death_authored"

# 1098x876. R*=sword (screen-left); L*=shield (screen-right).
# Collapse: upright → reel → fall → prone. Mark all joints even when lying;
# WeaponTip stays on blade tip (may leave hand); shield may separate.

FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    {  # f00 — start; sword tip high; ready-ish
        "Nose": (560, 250),
        "Neck": (555, 300),
        "RShoulder": (490, 330),
        "RElbow": (470, 400),
        "RWrist": (540, 450),
        "WeaponTip": (576, 90),
        "LShoulder": (620, 330),
        "LElbow": (690, 360),
        "LWrist": (700, 400),
        "MidHip": (560, 470),
        "RHip": (525, 495),
        "RKnee": (545, 575),
        "RAnkle": (520, 670),
        "LHip": (595, 490),
        "LKnee": (660, 560),
        "LAnkle": (710, 655),
    },
    {  # f01 — struck back; shield raised; sword vertical — tip at blade top
        "Nose": (490, 360),
        "Neck": (500, 395),
        "RShoulder": (430, 410),
        "RElbow": (380, 430),
        "RWrist": (340, 415),
        "WeaponTip": (366, 200),
        "LShoulder": (580, 330),
        "LElbow": (640, 300),
        "LWrist": (660, 280),
        "MidHip": (500, 510),
        "RHip": (460, 540),
        "RKnee": (430, 610),
        "RAnkle": (500, 680),
        "LHip": (540, 530),
        "LKnee": (620, 560),
        "LAnkle": (560, 680),
    },
    {  # f02 — falling; upright sword tip on LEFT blade (not floating shield)
        "Nose": (520, 280),
        "Neck": (530, 320),
        "RShoulder": (460, 360),
        "RElbow": (400, 400),
        "RWrist": (360, 430),
        "WeaponTip": (315, 162),
        "LShoulder": (580, 300),
        "LElbow": (640, 250),
        "LWrist": (655, 230),
        "MidHip": (540, 450),
        "RHip": (500, 480),
        "RKnee": (430, 520),
        "RAnkle": (450, 620),
        "LHip": (580, 470),
        "LKnee": (640, 520),
        "LAnkle": (680, 600),
    },
    {  # f03 — tumble on back; dark sword tip high-left; shield free above; legs lower-right
        "Nose": (535, 385),
        "Neck": (535, 415),
        "RShoulder": (480, 430),
        "RElbow": (440, 460),
        "RWrist": (420, 485),
        "WeaponTip": (390, 150),
        "LShoulder": (580, 410),
        "LElbow": (610, 350),
        "LWrist": (620, 280),
        "MidHip": (540, 490),
        "RHip": (510, 510),
        "RKnee": (490, 550),
        "RAnkle": (520, 580),
        "LHip": (570, 510),
        "LKnee": (610, 545),
        "LAnkle": (640, 575),
    },
    {  # f04 — dropping toward ground; tip on blade (not helmet metal)
        "Nose": (560, 280),
        "Neck": (565, 320),
        "RShoulder": (520, 340),
        "RElbow": (500, 400),
        "RWrist": (515, 440),
        "WeaponTip": (490, 280),
        "LShoulder": (610, 320),
        "LElbow": (650, 350),
        "LWrist": (670, 380),
        "MidHip": (570, 430),
        "RHip": (540, 460),
        "RKnee": (530, 520),
        "RAnkle": (555, 585),
        "LHip": (600, 455),
        "LKnee": (650, 510),
        "LAnkle": (680, 575),
    },
    {  # f05 — prone face-down, head away (top), feet toward camera; tip on blade toward head
        "Nose": (600, 445),
        "Neck": (600, 470),
        "RShoulder": (545, 490),
        "RElbow": (520, 525),
        "RWrist": (515, 555),
        "WeaponTip": (510, 490),
        "LShoulder": (655, 490),
        "LElbow": (700, 520),
        "LWrist": (715, 545),
        "MidHip": (600, 545),
        "RHip": (560, 560),
        "RKnee": (530, 595),
        "RAnkle": (500, 625),
        "LHip": (640, 560),
        "LKnee": (680, 595),
        "LAnkle": (710, 625),
    },
]


def main() -> int:
    result = write_authored_clip(
        clip_id="g05_death",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "death collapse through prone; all joints marked every frame; "
            "f02-f03 shield may leave wrist (tip still on blade); "
            "f05 prone head-away uncertain occlusions under cape/shield"
        ),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
