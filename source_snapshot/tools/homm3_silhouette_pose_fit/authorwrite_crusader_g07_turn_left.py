#!/usr/bin/env python3
"""Eye-authored landmarks for crusader g07_turn_left (2 frames)."""
from __future__ import annotations

import json
from pathlib import Path

from crusader_author_common import ART, write_authored_clip

CLIP = "g07_turn_left"
FRAMES = ART / "source_frames" / "nn_upscale_g07_turn_left"
OUT = ART / "out_fit" / "g07_turn_left_authored"

# Pose A (heater shield) -> Pose B (round buckler). R*=sword/screen-left.
FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    {  # f00 — heater shield; vertical sword mid-chest; L foot forward
        "Nose": (580, 250),
        "Neck": (575, 295),
        "RShoulder": (526, 318),
        "RElbow": (500, 395),
        "RWrist": (575, 440),
        "WeaponTip": (618, 148),
        "LShoulder": (600, 308),
        "LElbow": (650, 400),
        "LWrist": (635, 460),
        "MidHip": (575, 525),
        "RHip": (545, 545),
        "RKnee": (545, 605),
        "RAnkle": (520, 688),
        "LHip": (610, 535),
        "LKnee": (640, 562),
        "LAnkle": (655, 692),
    },
    {  # f01 — round shield; sword raised past helmet
        "Nose": (590, 245),
        "Neck": (585, 290),
        "RShoulder": (550, 318),
        "RElbow": (528, 380),
        "RWrist": (568, 425),
        "WeaponTip": (600, 68),
        "LShoulder": (625, 312),
        "LElbow": (648, 380),
        "LWrist": (625, 415),
        "MidHip": (585, 500),
        "RHip": (550, 520),
        "RKnee": (541, 570),
        "RAnkle": (528, 688),
        "LHip": (615, 515),
        "LKnee": (644, 577),
        "LAnkle": (655, 692),
    },
]


def main() -> int:
    result = write_authored_clip(
        clip_id="turn_left_g7",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "g07 turn-left: heater-shield ready into raised-sword round-buckler; "
            "identical sprites reused by g08/g09/g10 in reverse/alternate order"
        ),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
