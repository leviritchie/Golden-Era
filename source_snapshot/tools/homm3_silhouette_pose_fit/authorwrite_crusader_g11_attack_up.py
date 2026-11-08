#!/usr/bin/env python3
"""Eye-authored crusader g11_attack_up landmarks (fixed-length IK gate)."""
from __future__ import annotations

import json
from pathlib import Path

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames/nn_upscale_g11_attack_up"
OUT = ART / "out_fit/g11_attack_up_authored"

# 1098x876 NN sprites. Facing camera-right.
# R* = character RIGHT / sword side (often screen-left).
# L* = character LEFT / shield side (often screen-right).
# Authored by inspecting each frame PNG; track seeds assist-only.

FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    {  # f00 — ready; sword over R shoulder tip UR; shield out
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
    {  # f01 — windup; tip high overhead; L knee raised forward
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
    {  # f02 — two-hand overhead; tip UL behind head; L foot forward
        "Nose": (555, 255),
        "Neck": (548, 295),
        "RShoulder": (500, 320),
        "RElbow": (530, 250),
        "RWrist": (560, 285),
        "WeaponTip": (430, 175),
        "LShoulder": (590, 330),
        "LElbow": (630, 290),
        "LWrist": (600, 310),
        "MidHip": (555, 470),
        "RHip": (525, 485),
        "RKnee": (505, 580),
        "RAnkle": (480, 685),
        "LHip": (585, 480),
        "LKnee": (640, 555),
        "LAnkle": (655, 650),
    },
    {  # f03 — swing; body twisted back-to-cam; tip UR; shield back L; R lead
        "Nose": (600, 300),
        "Neck": (590, 345),
        "RShoulder": (640, 380),
        "RElbow": (690, 430),
        "RWrist": (730, 455),
        "WeaponTip": (796, 278),
        "LShoulder": (545, 355),
        "LElbow": (490, 350),
        "LWrist": (455, 340),
        "MidHip": (545, 490),
        "RHip": (575, 505),
        "RKnee": (560, 595),
        "RAnkle": (545, 680),
        "LHip": (525, 505),
        "LKnee": (480, 585),
        "LAnkle": (430, 680),
    },
    {  # f04 — follow-through; tip UR; L leg near-forward; cape/shield rear
        "Nose": (620, 320),
        "Neck": (605, 360),
        "RShoulder": (640, 390),
        "RElbow": (680, 430),
        "RWrist": (710, 450),
        "WeaponTip": (780, 295),
        "LShoulder": (560, 350),
        "LElbow": (530, 400),
        "LWrist": (545, 440),
        "MidHip": (575, 500),
        "RHip": (555, 515),
        "RKnee": (535, 600),
        "RAnkle": (520, 685),
        "LHip": (600, 510),
        "LKnee": (640, 590),
        "LAnkle": (655, 680),
    },
    {  # f05 — recovery; tip far UR; shield prominent; R leg trailing
        "Nose": (590, 300),
        "Neck": (580, 340),
        "RShoulder": (535, 360),
        "RElbow": (560, 420),
        "RWrist": (620, 400),
        "WeaponTip": (865, 280),
        "LShoulder": (625, 345),
        "LElbow": (680, 400),
        "LWrist": (700, 450),
        "MidHip": (590, 495),
        "RHip": (545, 510),
        "RKnee": (515, 590),
        "RAnkle": (500, 680),
        "LHip": (630, 505),
        "LKnee": (655, 585),
        "LAnkle": (650, 680),
    },
    {  # f06 — settle toward ready; tip UR; shield; wide stance
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
        clip_id="g11_attack_up",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "g11 attack_up: windup overhead then slash recovery; "
            "R=sword often screen-left until mid-twist frames; "
            "WeaponTip on blade tip each frame"
        ),
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
