#!/usr/bin/env python3
"""Eye-authored landmarks for crusader g08_turn_right (2 frames)."""
from __future__ import annotations

import json
from pathlib import Path

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames" / "nn_upscale_g08_turn_right"
OUT = ART / "out_fit" / "g08_turn_right_authored"

# Same two sprites as g07 but reversed: Pose B -> Pose A.
FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    {  # f00 — round buckler / raised sword (g07 f01 twin)
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
    {  # f01 — heater shield (g07 f00 twin)
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
]


def main() -> int:
    result = write_authored_clip(
        clip_id="turn_right_g8",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes="g08 turn-right: reverse of g07 sprite pair (round-buckler into heater-shield)",
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
