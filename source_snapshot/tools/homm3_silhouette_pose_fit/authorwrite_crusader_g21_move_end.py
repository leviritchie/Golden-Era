#!/usr/bin/env python3
"""Eye-authored landmarks for crusader g21_move_end (2 frames)."""
from __future__ import annotations

import json

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames" / "nn_upscale_g21_move_end"
OUT = ART / "out_fit" / "g21_move_end_authored"

# Facing-right walk end / settle: R*=sword/screen-left.
FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    {  # f00 — longest stride; sword tip farthest right; both hands on hilt
        "Nose": (585, 280),
        "Neck": (575, 322),
        "RShoulder": (540, 338),
        "RElbow": (555, 415),
        "RWrist": (600, 475),
        "WeaponTip": (829, 246),
        "LShoulder": (615, 348),
        "LElbow": (650, 435),
        "LWrist": (620, 495),
        "MidHip": (585, 535),
        "RHip": (545, 550),
        "RKnee": (548, 595),
        "RAnkle": (460, 692),
        "LHip": (620, 545),
        "LKnee": (660, 575),
        "LAnkle": (705, 692),
    },
    {  # f01 — recover; sword shorter diagonal
        "Nose": (590, 275),
        "Neck": (580, 320),
        "RShoulder": (545, 338),
        "RElbow": (555, 415),
        "RWrist": (588, 470),
        "WeaponTip": (774, 240),
        "LShoulder": (615, 348),
        "LElbow": (645, 435),
        "LWrist": (605, 490),
        "MidHip": (595, 530),
        "RHip": (560, 545),
        "RKnee": (575, 580),
        "RAnkle": (500, 688),
        "LHip": (620, 540),
        "LKnee": (645, 568),
        "LAnkle": (665, 692),
    },
]


def main() -> int:
    result = write_authored_clip(
        clip_id="move_end_g21",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "g21 move-end: facing-right stride settle; WeaponTip on blade tip not plume; "
            "trailing R foot back, leading L foot forward"
        ),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
