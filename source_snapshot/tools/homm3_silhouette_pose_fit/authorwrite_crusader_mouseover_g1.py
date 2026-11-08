#!/usr/bin/env python3
"""Eye-authored g01_mouseover landmarks (NN sprites). Hard gate for fixed-length IK."""
from __future__ import annotations

import json
from pathlib import Path

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames/nn_upscale_g01_mouseover"
OUT = ART / "out_fit/g01_mouseover_authored"

# 1098x876. R*=sword/character-right (screen-left); L*=shield (screen-right).
# Clip is ping-pong: f00==f07, f01==f06, f02==f05, f03==f04 (byte-identical).
# Motion: ready stance with sword tip bobbing up-right / more vertical / farther right.

_F00 = {  # tip up-right near plume height
    "Nose": (555, 278),
    "Neck": (550, 318),
    "RShoulder": (490, 335),
    "RElbow": (478, 415),
    "RWrist": (545, 455),
    "WeaponTip": (644, 174),
    "LShoulder": (605, 340),
    "LElbow": (655, 400),
    "LWrist": (650, 440),
    "MidHip": (545, 490),
    "RHip": (515, 510),
    "RKnee": (525, 590),
    "RAnkle": (515, 680),
    "LHip": (575, 505),
    "LKnee": (640, 580),
    "LAnkle": (645, 675),
}
_F01 = {  # sword more vertical; tip higher
    "Nose": (548, 265),
    "Neck": (545, 305),
    "RShoulder": (485, 325),
    "RElbow": (470, 400),
    "RWrist": (535, 445),
    "WeaponTip": (608, 156),
    "LShoulder": (600, 330),
    "LElbow": (650, 390),
    "LWrist": (645, 430),
    "MidHip": (540, 480),
    "RHip": (510, 500),
    "RKnee": (525, 585),
    "RAnkle": (515, 680),
    "LHip": (570, 495),
    "LKnee": (640, 575),
    "LAnkle": (645, 675),
}
_F02 = {  # tip shifts right/down slightly on diagonal
    "Nose": (555, 275),
    "Neck": (550, 315),
    "RShoulder": (490, 330),
    "RElbow": (485, 405),
    "RWrist": (555, 450),
    "WeaponTip": (665, 216),
    "LShoulder": (605, 335),
    "LElbow": (655, 395),
    "LWrist": (660, 435),
    "MidHip": (550, 485),
    "RHip": (520, 505),
    "RKnee": (525, 590),
    "RAnkle": (515, 680),
    "LHip": (580, 500),
    "LKnee": (635, 575),
    "LAnkle": (645, 675),
}
_F03 = {  # tip farthest up-right
    "Nose": (550, 285),
    "Neck": (545, 325),
    "RShoulder": (485, 335),
    "RElbow": (495, 410),
    "RWrist": (560, 450),
    "WeaponTip": (746, 186),
    "LShoulder": (600, 340),
    "LElbow": (665, 395),
    "LWrist": (680, 430),
    "MidHip": (550, 490),
    "RHip": (520, 510),
    "RKnee": (530, 590),
    "RAnkle": (515, 680),
    "LHip": (580, 505),
    "LKnee": (635, 575),
    "LAnkle": (645, 675),
}

FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    _F00,
    _F01,
    _F02,
    _F03,
    dict(_F03),  # f04 == f03
    dict(_F02),  # f05 == f02
    dict(_F01),  # f06 == f01
    dict(_F00),  # f07 == f00
]


def main() -> int:
    result = write_authored_clip(
        clip_id="g01_mouseover",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "mouseover ping-pong ready bob; sword tip up-right; "
            "LElbow/LWrist inferred behind round shield; identical frame pairs copied"
        ),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
