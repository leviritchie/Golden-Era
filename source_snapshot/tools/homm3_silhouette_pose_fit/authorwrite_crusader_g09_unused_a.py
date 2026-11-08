#!/usr/bin/env python3
"""Eye-authored landmarks for crusader g09_unused_a (2 frames)."""
from __future__ import annotations

import json

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames" / "nn_upscale_g09_unused_a"
OUT = ART / "out_fit" / "g09_unused_a_authored"

# Same sprite order as g07 (Pose A -> Pose B).
FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    {  # f00 — heater shield
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
    {  # f01 — round buckler
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
        clip_id="unused_a_g9",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes="g09 unused_a: same two sprites/order as g07 turn-left (heater then round)",
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
