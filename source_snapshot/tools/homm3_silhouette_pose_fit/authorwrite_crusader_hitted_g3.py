#!/usr/bin/env python3
"""Eye-authored g03_hitted landmarks (NN sprites). Hard gate for fixed-length IK."""
from __future__ import annotations

import json

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames/nn_upscale_g03_hitted"
OUT = ART / "out_fit/g03_hitted_authored"

# 1098x876. R*=sword (screen-left); L*=shield (screen-right).
# Recoil: lean back, sword flung rear/left, shield up, L leg kick, then recover.

FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    {  # f00 — first hit lean; sword nearly vertical; L foot lifted
        "Nose": (470, 300),
        "Neck": (480, 340),
        "RShoulder": (420, 360),
        "RElbow": (390, 420),
        "RWrist": (400, 470),
        "WeaponTip": (410, 180),
        "LShoulder": (560, 340),
        "LElbow": (620, 360),
        "LWrist": (650, 370),
        "MidHip": (510, 500),
        "RHip": (470, 530),
        "RKnee": (490, 610),
        "RAnkle": (505, 680),
        "LHip": (550, 520),
        "LKnee": (640, 510),
        "LAnkle": (660, 590),
    },
    {  # f01 — deep recoil; dark tip far screen-left/up; shield high; L leg kicked up
        "Nose": (455, 335),
        "Neck": (465, 370),
        "RShoulder": (390, 400),
        "RElbow": (340, 455),
        "RWrist": (355, 485),
        "WeaponTip": (174, 323),
        "LShoulder": (540, 345),
        "LElbow": (600, 300),
        "LWrist": (630, 290),
        "MidHip": (470, 530),
        "RHip": (440, 560),
        "RKnee": (470, 630),
        "RAnkle": (500, 680),
        "LHip": (510, 535),
        "LKnee": (600, 530),
        "LAnkle": (650, 585),
    },
    {  # f02 — still reeling; tip at dark blade extreme left; L knee forward
        "Nose": (420, 310),
        "Neck": (430, 350),
        "RShoulder": (370, 380),
        "RElbow": (340, 445),
        "RWrist": (355, 475),
        "WeaponTip": (86, 350),
        "LShoulder": (500, 330),
        "LElbow": (580, 320),
        "LWrist": (610, 310),
        "MidHip": (440, 520),
        "RHip": (410, 550),
        "RKnee": (450, 630),
        "RAnkle": (490, 680),
        "LHip": (480, 525),
        "LKnee": (580, 540),
        "LAnkle": (640, 600),
    },
    {  # f03 — peak extension; tip far left; wrist on hilt (blue gem), not mid-blade
        "Nose": (490, 270),
        "Neck": (500, 310),
        "RShoulder": (430, 350),
        "RElbow": (420, 420),
        "RWrist": (450, 445),
        "WeaponTip": (186, 386),
        "LShoulder": (560, 330),
        "LElbow": (620, 310),
        "LWrist": (650, 300),
        "MidHip": (510, 500),
        "RHip": (470, 530),
        "RKnee": (470, 610),
        "RAnkle": (495, 680),
        "LHip": (550, 515),
        "LKnee": (620, 540),
        "LAnkle": (660, 600),
    },
    {  # f04 — recover toward ready; tip swings up-right
        "Nose": (560, 285),
        "Neck": (555, 325),
        "RShoulder": (500, 345),
        "RElbow": (520, 410),
        "RWrist": (560, 450),
        "WeaponTip": (731, 354),
        "LShoulder": (610, 340),
        "LElbow": (670, 380),
        "LWrist": (680, 420),
        "MidHip": (560, 495),
        "RHip": (530, 515),
        "RKnee": (540, 590),
        "RAnkle": (520, 680),
        "LHip": (590, 510),
        "LKnee": (640, 575),
        "LAnkle": (650, 670),
    },
    {  # f05 — near ready; tip far right-up
        "Nose": (565, 290),
        "Neck": (560, 330),
        "RShoulder": (505, 350),
        "RElbow": (515, 415),
        "RWrist": (570, 455),
        "WeaponTip": (797, 342),
        "LShoulder": (615, 345),
        "LElbow": (680, 385),
        "LWrist": (690, 425),
        "MidHip": (565, 500),
        "RHip": (535, 520),
        "RKnee": (545, 590),
        "RAnkle": (530, 680),
        "LHip": (595, 515),
        "LKnee": (645, 580),
        "LAnkle": (655, 670),
    },
]


def main() -> int:
    result = write_authored_clip(
        clip_id="g03_hitted",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "hit recoil then recover; f01-f03 sword tip on rear blade extreme; "
            "LElbow/LWrist behind raised shield; L leg kick occlusions estimated"
        ),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
