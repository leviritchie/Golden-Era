#!/usr/bin/env python3
"""Eye-authored g04_defence landmarks (NN sprites). Hard gate for fixed-length IK."""
from __future__ import annotations

import json

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames/nn_upscale_g04_defence"
OUT = ART / "out_fit/g04_defence_authored"

# 1098x876. R*=sword (screen-left); L*=shield (screen-right).
# Ping-pong: f00==f10, f01==f09, f02==f08, f03==f04==f05==f06==f07 (byte-identical).
# Motion: brace leftward, sword drops from across-body to low rear, shield forward.

_F00 = {  # sword across, tip far screen-right
    "Nose": (555, 285),
    "Neck": (550, 325),
    "RShoulder": (490, 340),
    "RElbow": (470, 410),
    "RWrist": (530, 460),
    "WeaponTip": (779, 408),
    "LShoulder": (605, 345),
    "LElbow": (655, 400),
    "LWrist": (665, 435),
    "MidHip": (545, 490),
    "RHip": (515, 510),
    "RKnee": (530, 590),
    "RAnkle": (510, 680),
    "LHip": (575, 505),
    "LKnee": (625, 575),
    "LAnkle": (640, 670),
}
_F01 = {  # step/brace left; tip down-right
    "Nose": (520, 280),
    "Neck": (515, 320),
    "RShoulder": (455, 335),
    "RElbow": (425, 400),
    "RWrist": (450, 470),
    "WeaponTip": (713, 551),
    "LShoulder": (570, 335),
    "LElbow": (630, 380),
    "LWrist": (640, 420),
    "MidHip": (515, 485),
    "RHip": (485, 505),
    "RKnee": (510, 585),
    "RAnkle": (505, 680),
    "LHip": (545, 500),
    "LKnee": (575, 575),
    "LAnkle": (555, 685),
}
_F02 = {  # deeper brace; tip low near shin
    "Nose": (475, 275),
    "Neck": (470, 315),
    "RShoulder": (410, 330),
    "RElbow": (380, 395),
    "RWrist": (400, 465),
    "WeaponTip": (635, 605),
    "LShoulder": (525, 325),
    "LElbow": (585, 370),
    "LWrist": (595, 400),
    "MidHip": (475, 480),
    "RHip": (445, 500),
    "RKnee": (455, 575),
    "RAnkle": (480, 680),
    "LHip": (505, 495),
    "LKnee": (530, 570),
    "LAnkle": (520, 680),
}
_F03 = {  # held peak brace left; tip down by feet; shield covers torso
    "Nose": (430, 280),
    "Neck": (425, 320),
    "RShoulder": (365, 340),
    "RElbow": (330, 400),
    "RWrist": (340, 470),
    "WeaponTip": (545, 641),
    "LShoulder": (480, 325),
    "LElbow": (520, 370),
    "LWrist": (535, 400),
    "MidHip": (440, 485),
    "RHip": (410, 505),
    "RKnee": (400, 590),
    "RAnkle": (420, 680),
    "LHip": (470, 500),
    "LKnee": (505, 575),
    "LAnkle": (510, 680),
}

FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    _F00,
    _F01,
    _F02,
    _F03,
    dict(_F03),  # f04
    dict(_F03),  # f05
    dict(_F03),  # f06
    dict(_F03),  # f07
    dict(_F02),  # f08
    dict(_F01),  # f09
    dict(_F00),  # f10
]


def main() -> int:
    result = write_authored_clip(
        clip_id="g04_defence",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "defence brace ping-pong; tip tracks across-body then low; "
            "f03-f07 held identical; LElbow/LWrist behind shield"
        ),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
