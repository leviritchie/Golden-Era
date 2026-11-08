#!/usr/bin/env python3
"""Eye-authored crusader idle_attack_front landmarks (fixed-length IK gate)."""
from __future__ import annotations

import json
from pathlib import Path

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames/nn_upscale_idle_attack"
OUT = ART / "out_fit/idle_attack_front_authored"

# 1098x876 NN sprites. Facing camera-right.
# R* = character RIGHT / sword side (often screen-left).
# L* = character LEFT / shield side (often screen-right).
# f00-f07: idle bob (tip/wrist micro-motion). f08+ attack.
# f08/f09/f14 share PNGs with g11/g13 f00/f01/f06.

def _idle_bob(tip: tuple[int, int], rwrist: tuple[int, int], lwrist: tuple[int, int]) -> dict[str, tuple[int, int]]:
    """Shared idle body; tip/wrists vary slightly across bob frames."""
    return {
        "Nose": (575, 265),
        "Neck": (565, 310),
        "RShoulder": (510, 345),
        "RElbow": (535, 400),
        "RWrist": rwrist,
        "WeaponTip": tip,
        "LShoulder": (615, 340),
        "LElbow": (655, 400),
        "LWrist": lwrist,
        "MidHip": (560, 510),
        "RHip": (525, 535),
        "RKnee": (505, 610),
        "RAnkle": (495, 685),
        "LHip": (595, 535),
        "LKnee": (625, 620),
        "LAnkle": (635, 690),
    }


FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    # f00-f07 idle bob (hashes: f1=f7, f2=f6, f3=f5; tip drifts slightly)
    # RWrist on gold crossguard (~592,445); tip on blade UR extremity
    _idle_bob((713, 228), (590, 442), (640, 405)),  # f00
    _idle_bob((707, 228), (589, 443), (640, 405)),  # f01
    _idle_bob((707, 222), (588, 441), (639, 404)),  # f02
    _idle_bob((707, 222), (589, 440), (639, 404)),  # f03
    _idle_bob((707, 216), (589, 438), (639, 403)),  # f04 tip highest
    _idle_bob((707, 222), (589, 440), (639, 404)),  # f05 == f03
    _idle_bob((707, 222), (588, 441), (639, 404)),  # f06 == f02
    _idle_bob((707, 228), (589, 443), (640, 405)),  # f07 == f01
    {  # f08 — shared with g11/g13 f00
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
    {  # f09 — shared with g11/g13 f01
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
    {  # f10 — overhead windup tip UL; shield forward; L step
        "Nose": (545, 230),
        "Neck": (540, 275),
        "RShoulder": (480, 320),
        "RElbow": (450, 280),
        "RWrist": (560, 250),
        "WeaponTip": (385, 145),
        "LShoulder": (590, 320),
        "LElbow": (630, 375),
        "LWrist": (655, 365),
        "MidHip": (545, 490),
        "RHip": (510, 510),
        "RKnee": (470, 600),
        "RAnkle": (445, 685),
        "LHip": (580, 505),
        "LKnee": (640, 575),
        "LAnkle": (680, 680),
    },
    {  # f11 — thrust right; tip far R; deep lunge L forward
        "Nose": (700, 290),
        "Neck": (680, 340),
        "RShoulder": (635, 410),
        "RElbow": (690, 500),
        "RWrist": (755, 520),
        "WeaponTip": (1040, 500),
        "LShoulder": (715, 395),
        "LElbow": (740, 470),
        "LWrist": (755, 520),
        "MidHip": (670, 520),
        "RHip": (640, 540),
        "RKnee": (600, 615),
        "RAnkle": (565, 685),
        "LHip": (705, 535),
        "LKnee": (730, 620),
        "LAnkle": (750, 690),
    },
    {  # f12 — tip UR recover; shield; L lead
        "Nose": (680, 320),
        "Neck": (665, 365),
        "RShoulder": (615, 400),
        "RElbow": (600, 475),
        "RWrist": (690, 470),
        "WeaponTip": (955, 365),
        "LShoulder": (710, 390),
        "LElbow": (745, 450),
        "LWrist": (720, 490),
        "MidHip": (640, 515),
        "RHip": (600, 535),
        "RKnee": (560, 615),
        "RAnkle": (540, 690),
        "LHip": (675, 530),
        "LKnee": (700, 620),
        "LAnkle": (710, 695),
    },
    {  # f13 — tip UR; shield; recovering stance
        "Nose": (655, 285),
        "Neck": (640, 335),
        "RShoulder": (605, 370),
        "RElbow": (630, 455),
        "RWrist": (675, 500),
        "WeaponTip": (865, 285),
        "LShoulder": (680, 370),
        "LElbow": (725, 430),
        "LWrist": (720, 480),
        "MidHip": (630, 515),
        "RHip": (595, 535),
        "RKnee": (545, 610),
        "RAnkle": (520, 685),
        "LHip": (660, 535),
        "LKnee": (680, 625),
        "LAnkle": (685, 695),
    },
    {  # f14 — shared with g11/g13 f06
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
        clip_id="idle_attack_front",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "idle_attack_front: f00-f07 idle bob then attack; "
            "f08/f09/f14 share sprites with g11/g13; tip on blade each frame"
        ),
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
