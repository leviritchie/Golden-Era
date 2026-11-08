#!/usr/bin/env python3
"""Eye-authored landmarks for crusader g02 idle (8 frames).

Ping-pong: f01==f07, f02==f06, f03==f05. Standing ready bob; R*=sword/screen-left,
L*=shield/screen-right. Idle is the temporal prefix of idle_start_move.
"""
from __future__ import annotations

import json

from crusader_author_common import ART, write_authored_clip

FRAMES = ART / "source_frames" / "nn_upscale_g02_idle"
OUT = ART / "out_fit" / "g02_idle_authored"


def _bob(
    *,
    nose: tuple[int, int],
    neck: tuple[int, int],
    tip: tuple[int, int],
    rwrist: tuple[int, int],
    lwrist: tuple[int, int],
    relbow: tuple[int, int],
    lelbow: tuple[int, int],
) -> dict[str, tuple[int, int]]:
    """Shared idle body; plume/sword/wrists bob a few pixels."""
    return {
        "Nose": nose,
        "Neck": neck,
        "RShoulder": (502, 348),
        "RElbow": relbow,
        "RWrist": rwrist,
        "WeaponTip": tip,
        "LShoulder": (612, 342),
        "LElbow": lelbow,
        "LWrist": lwrist,
        "MidHip": (558, 512),
        "RHip": (522, 534),
        "RKnee": (508, 612),
        "RAnkle": (498, 692),
        "LHip": (592, 532),
        "LKnee": (628, 618),
        "LAnkle": (638, 690),
    }


_F00 = _bob(nose=(568, 272), neck=(558, 318), tip=(708, 232), rwrist=(588, 444), lwrist=(642, 408), relbow=(532, 402), lelbow=(654, 398))
_F01 = _bob(nose=(568, 270), neck=(558, 316), tip=(706, 226), rwrist=(587, 442), lwrist=(641, 406), relbow=(531, 400), lelbow=(653, 396))
_F02 = _bob(nose=(569, 268), neck=(559, 314), tip=(704, 222), rwrist=(586, 440), lwrist=(640, 404), relbow=(530, 398), lelbow=(652, 394))
_F03 = _bob(nose=(569, 266), neck=(559, 312), tip=(702, 218), rwrist=(586, 438), lwrist=(640, 402), relbow=(530, 396), lelbow=(652, 392))
_F04 = _bob(nose=(570, 264), neck=(560, 310), tip=(700, 214), rwrist=(585, 436), lwrist=(639, 400), relbow=(529, 394), lelbow=(651, 390))

FRAMES_XY: list[dict[str, tuple[int, int]]] = [
    _F00,
    _F01,
    _F02,
    _F03,
    _F04,
    _F03,  # f05 == f03
    _F02,  # f06 == f02
    _F01,  # f07 == f01
]


def main() -> int:
    result = write_authored_clip(
        clip_id="idle_g02",
        frames_dir=FRAMES,
        out_dir=OUT,
        frames_xy=FRAMES_XY,
        notes=(
            "g02 idle: facing-right ready bob; ping-pong f1=f7, f2=f6, f3=f5; "
            "round shield; sword diagonal up-right (tip = blade UR extremity, not plume); "
            "ships as Crusader_Idle; also used as a fitting prefix before other DEF groups"
        ),
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
