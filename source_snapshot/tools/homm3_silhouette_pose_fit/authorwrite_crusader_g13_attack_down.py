#!/usr/bin/env python3
"""Eye-authored crusader g13_attack_down landmarks (fixed-length IK gate)."""
from __future__ import annotations

import json
from pathlib import Path

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames/nn_upscale_g13_attack_down"
OUT = ART / "out_fit/g13_attack_down_authored"

# 1098x876 NN sprites. Facing camera-right.
# R* = character RIGHT / sword side (often screen-left).
# L* = character LEFT / shield side (often screen-right).
# f00/f01/f06 identical to g11_attack_up counterparts (same PNG bytes).

FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    {  # f00 — shared with g11 f00
        "Nose": (535, 268),
        "Neck": (528, 305),
        "RShoulder": (468, 335),
        "RElbow": (418, 380),
        "RWrist": (478, 365),
        "WeaponTip": (655, 165),
        "LShoulder": (585, 318),
        "LElbow": (640, 365),
        "LWrist": (685, 395),
        "MidHip": (530, 485),
        "RHip": (495, 500),
        "RKnee": (470, 595),
        "RAnkle": (445, 685),
        "LHip": (570, 495),
        "LKnee": (620, 575),
        "LAnkle": (610, 665),
    },
    {  # f01 — shared with g11 f01
        "Nose": (505, 275),
        "Neck": (500, 315),
        "RShoulder": (455, 350),
        "RElbow": (400, 310),
        "RWrist": (430, 250),
        "WeaponTip": (565, 50),
        "LShoulder": (555, 340),
        "LElbow": (610, 380),
        "LWrist": (660, 410),
        "MidHip": (515, 480),
        "RHip": (480, 500),
        "RKnee": (475, 590),
        "RAnkle": (455, 685),
        "LHip": (555, 490),
        "LKnee": (620, 555),
        "LAnkle": (655, 640),
    },
    {  # f02 — overhead windup with shield; tip UL; L foot forward
        "Nose": (580, 250),
        "Neck": (575, 290),
        "RShoulder": (535, 330),
        "RElbow": (495, 300),
        "RWrist": (475, 255),
        "WeaponTip": (432, 140),
        "LShoulder": (625, 315),
        "LElbow": (660, 365),
        "LWrist": (695, 375),
        "MidHip": (565, 480),
        "RHip": (540, 500),
        "RKnee": (525, 585),
        "RAnkle": (520, 680),
        "LHip": (595, 500),
        "LKnee": (650, 580),
        "LAnkle": (700, 685),
    },
    {  # f03 — downward strike; tip low; L arm extended forward; deep lunge
        "Nose": (670, 370),
        "Neck": (655, 400),
        "RShoulder": (575, 390),
        "RElbow": (545, 470),
        "RWrist": (585, 610),
        "WeaponTip": (560, 800),
        "LShoulder": (680, 385),
        "LElbow": (745, 390),
        "LWrist": (810, 400),
        "MidHip": (605, 505),
        "RHip": (575, 530),
        "RKnee": (550, 615),
        "RAnkle": (530, 715),
        "LHip": (635, 520),
        "LKnee": (680, 600),
        "LAnkle": (710, 735),
    },
    {  # f04 — low follow-through; tip down-forward; crouched
        "Nose": (630, 390),
        "Neck": (620, 425),
        "RShoulder": (545, 430),
        "RElbow": (525, 505),
        "RWrist": (520, 560),
        "WeaponTip": (700, 700),
        "LShoulder": (670, 435),
        "LElbow": (720, 505),
        "LWrist": (730, 545),
        "MidHip": (600, 545),
        "RHip": (565, 560),
        "RKnee": (540, 640),
        "RAnkle": (510, 710),
        "LHip": (640, 560),
        "LKnee": (670, 650),
        "LAnkle": (700, 720),
    },
    {  # f05 — recover; blade across waist tip right; shield out
        "Nose": (640, 320),
        "Neck": (620, 365),
        "RShoulder": (545, 380),
        "RElbow": (515, 465),
        "RWrist": (540, 520),
        "WeaponTip": (830, 520),
        "LShoulder": (655, 380),
        "LElbow": (705, 455),
        "LWrist": (680, 520),
        "MidHip": (600, 510),
        "RHip": (555, 540),
        "RKnee": (540, 625),
        "RAnkle": (515, 690),
        "LHip": (640, 540),
        "LKnee": (650, 630),
        "LAnkle": (670, 690),
    },
    {  # f06 — shared with g11 f06
        "Nose": (575, 290),
        "Neck": (568, 330),
        "RShoulder": (520, 355),
        "RElbow": (500, 410),
        "RWrist": (560, 390),
        "WeaponTip": (770, 235),
        "LShoulder": (615, 340),
        "LElbow": (660, 390),
        "LWrist": (685, 430),
        "MidHip": (575, 490),
        "RHip": (540, 505),
        "RKnee": (520, 595),
        "RAnkle": (510, 685),
        "LHip": (610, 500),
        "LKnee": (640, 585),
        "LAnkle": (635, 680),
    },
]


def main() -> int:
    result = write_authored_clip(
        clip_id="g13_attack_down",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "g13 attack_down: overhead into downward cut then recover; "
            "f00/f01/f06 share sprites with g11; tip on blade including low frames"
        ),
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
