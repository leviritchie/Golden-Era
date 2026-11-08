#!/usr/bin/env python3
"""Eye-authored landmarks for crusader g20_move_start (2 frames)."""
from __future__ import annotations

import json

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames" / "nn_upscale_g20_move_start"
OUT = ART / "out_fit" / "g20_move_start_authored"

# Facing-right walk start: R*=sword/screen-left; L*=shield/screen-right.
FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    {  # f00 — round shield; sword diagonal up-right; L foot forward
        "Nose": (560, 275),
        "Neck": (555, 318),
        "RShoulder": (525, 325),
        "RElbow": (505, 400),
        "RWrist": (570, 450),
        "WeaponTip": (732, 236),
        "LShoulder": (600, 320),
        "LElbow": (650, 390),
        "LWrist": (635, 435),
        "MidHip": (570, 520),
        "RHip": (535, 540),
        "RKnee": (555, 578),
        "RAnkle": (505, 692),
        "LHip": (605, 535),
        "LKnee": (658, 565),
        "LAnkle": (665, 698),
    },
    {  # f01 — sword extends farther; wider stride; both hands near hilt
        "Nose": (575, 270),
        "Neck": (570, 318),
        "RShoulder": (535, 335),
        "RElbow": (530, 410),
        "RWrist": (580, 470),
        "WeaponTip": (799, 244),
        "LShoulder": (605, 345),
        "LElbow": (640, 430),
        "LWrist": (600, 485),
        "MidHip": (575, 525),
        "RHip": (545, 545),
        "RKnee": (550, 575),
        "RAnkle": (480, 688),
        "LHip": (610, 540),
        "LKnee": (655, 555),
        "LAnkle": (680, 692),
    },
]


def main() -> int:
    result = write_authored_clip(
        clip_id="move_start_g20",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "g20 move-start: facing-right stride begin; diagonal sword tip = rightmost blade "
            "pixel (not plume tip); LWrist near shield/hilt"
        ),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
