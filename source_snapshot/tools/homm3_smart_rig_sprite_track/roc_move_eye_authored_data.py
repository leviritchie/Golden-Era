#!/usr/bin/env python3
"""Eye-authored per-frame UniRig joints for roc move g0.

Coordinates were placed by eye against NN sprites / author grids / contact sheet,
keeping continuity with the previous frame. Wing tips are seated on the sprite
silhouette (except f0, which copies seed_f0_authored.json exactly).

This module only STORES and dumps those marks — it does not LK-track or invent
motion as authority.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

OUT = Path(
    r"V:/Games/Olden Era Playtest Tweak/artifacts/roc_pose_pipeline/smart_rig_move_pilot"
)
AUTH = OUT / "author_frames"
NN = OUT / "frames_nn"

SPINE = ["Bone_000", "Bone_001", "Bone_003", "Bone_002"]
HEAD = ["Bone_019", "Bone_018", "Bone_017", "Bone_027", "Bone_026", "Bone_029", "Bone_028"]
TAIL = ["Bone_006", "Bone_005", "Bone_004"]
LEG_A = ["Bone_011", "Bone_010", "Bone_009", "Bone_008", "Bone_007"]
LEG_B = ["Bone_016", "Bone_015", "Bone_014", "Bone_013", "Bone_012"]
NEAR_ARM = ["Bone_022", "Bone_021", "Bone_020"]
NEAR_D0 = ["Bone_031", "Bone_030"]
NEAR_D1 = ["Bone_034", "Bone_033", "Bone_032"]
NEAR_D2 = ["Bone_037", "Bone_036", "Bone_035"]
FAR_ARM = ["Bone_025", "Bone_024", "Bone_023"]
FAR_D0 = ["Bone_039", "Bone_038"]
FAR_D1 = ["Bone_042", "Bone_041", "Bone_040"]
FAR_D2 = ["Bone_045", "Bone_044", "Bone_043"]


def _load_f0() -> dict[str, dict[str, int]]:
    seed = json.loads((OUT / "seed_f0_authored.json").read_text(encoding="utf-8"))
    return {n: {"x": int(j["x"]), "y": int(j["y"])} for n, j in seed["joints"].items()}


def _pt(x: float, y: float) -> dict[str, int]:
    return {"x": int(round(x)), "y": int(round(y))}


def _fan_from_wrist(
    wrist: tuple[float, float],
    tips: list[tuple[float, float]],
    chains: list[list[str]],
) -> dict:
    out = {}
    for tip, chain in zip(tips, chains):
        n = len(chain)
        for i, name in enumerate(chain):
            t = (i + 1) / n
            out[name] = _pt(
                wrist[0] + (tip[0] - wrist[0]) * t,
                wrist[1] + (tip[1] - wrist[1]) * t,
            )
        out[chain[-1]] = _pt(*tip)
    return out


def _compose(
    spine,
    head,
    tail,
    leg_a,
    leg_b,
    near_arm,
    near_tips,
    far_arm,
    far_tips,
) -> dict[str, dict[str, int]]:
    d: dict[str, dict[str, int]] = {}
    for n, p in zip(SPINE, spine):
        d[n] = _pt(*p)
    for n, p in zip(HEAD, head):
        d[n] = _pt(*p)
    for n, p in zip(TAIL, tail):
        d[n] = _pt(*p)
    for n, p in zip(LEG_A, leg_a):
        d[n] = _pt(*p)
    for n, p in zip(LEG_B, leg_b):
        d[n] = _pt(*p)
    for n, p in zip(NEAR_ARM, near_arm):
        d[n] = _pt(*p)
    for n, p in zip(FAR_ARM, far_arm):
        d[n] = _pt(*p)
    d.update(_fan_from_wrist(near_arm[-1], near_tips, [NEAR_D0, NEAR_D1, NEAR_D2]))
    d.update(_fan_from_wrist(far_arm[-1], far_tips, [FAR_D0, FAR_D1, FAR_D2]))
    return d


def _snap_opaque(fi: int, x: float, y: float, max_r: int = 40) -> tuple[int, int]:
    """Nudge an eye mark onto nearby opaque sprite pixels (fail closed if none)."""
    rgba = np.asarray(Image.open(NN / f"{fi:02d}.png").convert("RGBA"))
    a = rgba[:, :, 3] > 40
    xi, yi = int(round(x)), int(round(y))
    h, w = a.shape
    xi = min(max(xi, 0), w - 1)
    yi = min(max(yi, 0), h - 1)
    if a[yi, xi]:
        return xi, yi
    ys, xs = np.where(a)
    d2 = (xs - xi) ** 2 + (ys - yi) ** 2
    i = int(d2.argmin())
    if d2[i] > max_r * max_r:
        raise SystemExit(f"f{fi:02d} snap ({xi},{yi}) too far d={d2[i]**0.5:.1f}")
    return int(xs[i]), int(ys[i])


def _eye_tip_targets() -> tuple[dict[int, tuple[int, int]], dict[int, tuple[int, int]]]:
    """Hand-chosen tip landmarks from grids/contact sheet, then snap to opaque.

    Near tip (035): down at f00 → peak (672,414) at f15 → down again.
    Far tip (043): back-upper early; rides right-high silhouette mid-flap; returns.
    """
    near_raw = {
        0: (800, 818),  # seed — do not snap
        1: (795, 808),
        2: (782, 790),
        3: (765, 765),
        4: (748, 740),
        5: (735, 715),
        6: (705, 675),
        7: (680, 635),
        8: (655, 585),
        9: (640, 545),
        10: (632, 537),
        11: (628, 513),
        12: (624, 501),
        13: (630, 474),
        14: (660, 438),
        15: (672, 414),
        16: (672, 450),
        17: (685, 495),
        18: (705, 535),
        19: (730, 580),
        20: (750, 625),
        21: (765, 665),
        22: (778, 705),
        23: (785, 740),
        24: (785, 771),
        25: (735, 715),
        26: (735, 715),
        27: (735, 715),
        28: (745, 730),
        29: (760, 755),
    }
    far_raw = {
        0: (570, 555),  # seed — do not snap
        1: (568, 576),
        2: (565, 576),
        3: (560, 582),
        4: (555, 585),
        5: (550, 588),
        6: (600, 560),
        7: (640, 550),
        8: (700, 543),
        9: (822, 519),
        10: (858, 516),
        11: (843, 492),
        12: (846, 483),
        13: (861, 460),
        14: (870, 436),
        15: (831, 426),
        16: (831, 448),
        17: (852, 468),
        18: (843, 480),
        19: (837, 502),
        20: (858, 516),
        21: (822, 526),
        22: (816, 538),
        23: (810, 542),
        24: (753, 554),
        25: (550, 588),
        26: (550, 588),
        27: (552, 588),
        28: (555, 588),
        29: (560, 585),
    }
    near: dict[int, tuple[int, int]] = {0: near_raw[0]}
    far: dict[int, tuple[int, int]] = {0: far_raw[0]}
    for fi in range(1, 30):
        near[fi] = _snap_opaque(fi, *near_raw[fi])
        far[fi] = _snap_opaque(fi, *far_raw[fi])
    return near, far


def _digit_tips(
    wrist: tuple[float, float],
    main_tip: tuple[float, float],
    spread: float,
    phase: str,
) -> list[tuple[float, float]]:
    """Three digit tips around main tip, fanned for near/far wing."""
    wx, wy = wrist
    tx, ty = main_tip
    dx, dy = tx - wx, ty - wy
    # perpendicular unit
    L = max((dx * dx + dy * dy) ** 0.5, 1.0)
    px, py = -dy / L, dx / L
    if phase == "near":
        # seed-like: left / center / right(main) fan
        return [
            (tx + px * spread * 1.15 - dx * 0.08, ty + py * spread * 1.15 - dy * 0.08),
            (tx + px * spread * 0.15, ty + py * spread * 0.15),
            (tx, ty),
        ]
    # far: trailing / mid / leading(main)
    return [
        (tx - px * spread * 0.9 - dx * 0.12, ty - py * spread * 0.9 - dy * 0.12),
        (tx - px * spread * 0.25 - dx * 0.04, ty - py * spread * 0.25 - dy * 0.04),
        (tx, ty),
    ]


def _eye_frame_table() -> dict[int, dict[str, dict[str, int]]]:
    F: dict[int, dict[str, dict[str, int]]] = {}
    F[0] = _load_f0()
    near_tip, far_tip = _eye_tip_targets()

    # Body/head/tail/leg landmarks chosen by eye per frame (grids + cues).
    # near_arm / far_arm: shoulder→elbow→wrist toward tips.
    body = {
        # fi: (spine4, head7, tail3, legA5, legB5, near_shoulder, far_shoulder)
        1: dict(
            spine=[(700, 676), (655, 651), (745, 664), (775, 634)],
            head=[(795, 622), (835, 610), (862, 604), (882, 600), (898, 614), (888, 606), (902, 606)],
            tail=[(615, 654), (535, 634), (477, 612)],
            leg_a=[(675, 691), (668, 714), (660, 736), (652, 754), (645, 768)],
            leg_b=[(710, 688), (702, 711), (694, 732), (686, 750), (678, 764)],
            nsh=(720, 630),
            fsh=(714, 602),
        ),
        2: dict(
            spine=[(698, 674), (654, 649), (744, 662), (774, 632)],
            head=[(795, 624), (835, 612), (862, 606), (882, 602), (898, 616), (888, 608), (902, 609)],
            tail=[(614, 652), (534, 632), (477, 612)],
            leg_a=[(674, 688), (666, 710), (658, 732), (650, 750), (642, 764)],
            leg_b=[(708, 686), (700, 708), (692, 728), (684, 746), (676, 760)],
            nsh=(718, 624),
            fsh=(712, 598),
        ),
        3: dict(
            spine=[(696, 672), (653, 646), (743, 658), (773, 630)],
            head=[(796, 628), (836, 616), (863, 610), (883, 606), (898, 618), (888, 612), (902, 615)],
            tail=[(612, 650), (532, 630), (475, 610)],
            leg_a=[(672, 684), (664, 704), (656, 724), (648, 742), (640, 756)],
            leg_b=[(706, 682), (698, 702), (690, 722), (682, 740), (674, 754)],
            nsh=(716, 616),
            fsh=(710, 592),
        ),
        4: dict(
            spine=[(695, 670), (652, 644), (742, 656), (772, 628)],
            head=[(796, 630), (836, 618), (863, 612), (883, 608), (898, 620), (888, 614), (902, 615)],
            tail=[(610, 648), (530, 628), (472, 608)],
            leg_a=[(670, 680), (662, 698), (654, 716), (646, 734), (638, 748)],
            leg_b=[(704, 678), (696, 696), (688, 714), (680, 732), (672, 746)],
            nsh=(714, 608),
            fsh=(708, 586),
        ),
        5: dict(
            spine=[(694, 668), (651, 642), (741, 654), (771, 626)],
            head=[(797, 634), (837, 622), (864, 616), (884, 612), (898, 622), (888, 618), (902, 621)],
            tail=[(608, 646), (528, 626), (470, 608)],
            leg_a=[(668, 676), (660, 692), (652, 708), (644, 726), (636, 740)],
            leg_b=[(702, 674), (694, 690), (686, 706), (678, 724), (670, 738)],
            nsh=(712, 600),
            fsh=(706, 580),
        ),
        6: dict(
            spine=[(694, 662), (650, 636), (740, 648), (770, 620)],
            head=[(798, 638), (838, 626), (865, 620), (885, 616), (898, 626), (888, 622), (902, 627)],
            tail=[(606, 640), (526, 622), (468, 610)],
            leg_a=[(666, 668), (658, 684), (650, 700), (642, 716), (634, 730)],
            leg_b=[(700, 666), (692, 682), (684, 698), (676, 714), (668, 728)],
            nsh=(710, 590),
            fsh=(710, 570),
        ),
        7: dict(
            spine=[(694, 658), (650, 632), (740, 644), (770, 616)],
            head=[(798, 640), (838, 628), (865, 622), (885, 618), (898, 628), (888, 624), (902, 627)],
            tail=[(604, 636), (524, 620), (468, 610)],
            leg_a=[(664, 662), (656, 678), (648, 692), (640, 708), (632, 722)],
            leg_b=[(698, 660), (690, 676), (682, 690), (674, 706), (666, 720)],
            nsh=(708, 580),
            fsh=(714, 560),
        ),
        8: dict(
            spine=[(695, 652), (651, 626), (741, 638), (771, 612)],
            head=[(800, 644), (840, 632), (866, 626), (886, 622), (898, 632), (888, 628), (902, 633)],
            tail=[(602, 632), (522, 618), (468, 614)],
            leg_a=[(662, 656), (654, 670), (646, 684), (638, 700), (630, 714)],
            leg_b=[(696, 654), (688, 668), (680, 682), (672, 698), (664, 712)],
            nsh=(706, 568),
            fsh=(718, 550),
        ),
        9: dict(
            spine=[(697, 646), (653, 620), (743, 632), (773, 608)],
            head=[(802, 646), (842, 634), (868, 628), (888, 624), (898, 634), (888, 630), (902, 636)],
            tail=[(600, 628), (520, 618), (468, 616)],
            leg_a=[(660, 650), (652, 664), (644, 678), (636, 692), (628, 706)],
            leg_b=[(694, 648), (686, 662), (678, 676), (670, 690), (662, 704)],
            nsh=(705, 556),
            fsh=(724, 540),
        ),
        10: dict(
            spine=[(698, 642), (654, 616), (744, 628), (774, 606)],
            head=[(802, 644), (842, 632), (868, 626), (888, 622), (898, 632), (888, 628), (902, 633)],
            tail=[(598, 626), (518, 618), (468, 618)],
            leg_a=[(658, 646), (650, 660), (642, 674), (634, 688), (626, 702)],
            leg_b=[(692, 644), (684, 658), (676, 672), (668, 686), (660, 700)],
            nsh=(704, 548),
            fsh=(728, 532),
        ),
        11: dict(
            spine=[(701, 632), (656, 606), (746, 618), (776, 598)],
            head=[(804, 648), (844, 636), (870, 630), (888, 626), (898, 636), (888, 632), (902, 642)],
            tail=[(596, 622), (516, 618), (468, 622)],
            leg_a=[(656, 638), (648, 652), (640, 666), (632, 680), (624, 694)],
            leg_b=[(690, 636), (682, 650), (674, 664), (666, 678), (658, 692)],
            nsh=(704, 536),
            fsh=(732, 520),
        ),
        12: dict(
            spine=[(703, 626), (658, 600), (748, 612), (778, 594)],
            head=[(806, 650), (846, 638), (872, 632), (890, 628), (898, 638), (890, 634), (902, 645)],
            tail=[(594, 620), (514, 618), (468, 624)],
            leg_a=[(654, 632), (646, 646), (638, 660), (630, 674), (622, 688)],
            leg_b=[(688, 630), (680, 644), (672, 658), (664, 672), (656, 686)],
            nsh=(702, 524),
            fsh=(734, 512),
        ),
        13: dict(
            spine=[(705, 616), (660, 590), (750, 602), (780, 586)],
            head=[(808, 652), (848, 640), (874, 634), (890, 630), (898, 640), (890, 636), (902, 648)],
            tail=[(592, 618), (512, 620), (471, 628)],
            leg_a=[(652, 624), (644, 638), (636, 652), (628, 666), (620, 680)],
            leg_b=[(686, 622), (678, 636), (670, 650), (662, 664), (654, 678)],
            nsh=(700, 510),
            fsh=(736, 500),
        ),
        14: dict(
            spine=[(706, 604), (662, 580), (752, 592), (782, 580)],
            head=[(808, 650), (848, 638), (874, 632), (890, 628), (896, 638), (888, 634), (899, 645)],
            tail=[(590, 618), (510, 622), (471, 632)],
            leg_a=[(650, 620), (642, 634), (634, 648), (626, 662), (618, 676)],
            leg_b=[(684, 618), (676, 632), (668, 646), (660, 660), (652, 674)],
            nsh=(700, 498),
            fsh=(738, 492),
        ),
        15: dict(
            spine=[(707, 598), (663, 576), (753, 588), (783, 578)],
            head=[(810, 650), (850, 638), (874, 632), (890, 628), (896, 638), (888, 634), (899, 645)],
            tail=[(588, 620), (508, 624), (471, 635)],
            leg_a=[(648, 618), (640, 632), (632, 646), (624, 660), (616, 674)],
            leg_b=[(682, 616), (674, 630), (666, 644), (658, 658), (650, 672)],
            nsh=(700, 490),
            fsh=(740, 488),
        ),
        16: dict(
            spine=[(706, 608), (662, 586), (752, 598), (782, 586)],
            head=[(808, 652), (848, 640), (874, 634), (890, 630), (898, 640), (890, 636), (902, 651)],
            tail=[(590, 618), (510, 622), (468, 630)],
            leg_a=[(650, 622), (642, 636), (634, 650), (626, 664), (618, 678)],
            leg_b=[(684, 620), (676, 634), (668, 648), (660, 662), (652, 676)],
            nsh=(702, 502),
            fsh=(736, 496),
        ),
        17: dict(
            spine=[(703, 620), (660, 596), (750, 608), (780, 594)],
            head=[(806, 650), (846, 638), (872, 632), (890, 628), (898, 638), (890, 634), (902, 645)],
            tail=[(592, 620), (512, 620), (468, 626)],
            leg_a=[(652, 628), (644, 642), (636, 656), (628, 670), (620, 684)],
            leg_b=[(686, 626), (678, 640), (670, 654), (662, 668), (654, 682)],
            nsh=(704, 518),
            fsh=(732, 510),
        ),
        18: dict(
            spine=[(702, 628), (658, 604), (748, 616), (778, 600)],
            head=[(804, 650), (844, 638), (870, 632), (888, 628), (898, 638), (888, 634), (902, 645)],
            tail=[(594, 622), (514, 618), (468, 624)],
            leg_a=[(654, 634), (646, 648), (638, 662), (630, 676), (622, 690)],
            leg_b=[(688, 632), (680, 646), (672, 660), (664, 674), (656, 688)],
            nsh=(706, 532),
            fsh=(728, 520),
        ),
        19: dict(
            spine=[(699, 640), (655, 616), (745, 628), (775, 608)],
            head=[(802, 646), (842, 634), (868, 628), (888, 624), (898, 634), (888, 630), (902, 639)],
            tail=[(596, 624), (516, 618), (468, 620)],
            leg_a=[(656, 642), (648, 656), (640, 670), (632, 684), (624, 698)],
            leg_b=[(690, 640), (682, 654), (674, 668), (666, 682), (658, 696)],
            nsh=(708, 548),
            fsh=(724, 532),
        ),
        20: dict(
            spine=[(698, 648), (654, 624), (744, 636), (774, 612)],
            head=[(800, 644), (840, 632), (866, 626), (886, 622), (898, 632), (888, 628), (902, 633)],
            tail=[(598, 626), (518, 618), (468, 618)],
            leg_a=[(658, 648), (650, 662), (642, 676), (634, 690), (626, 704)],
            leg_b=[(692, 646), (684, 660), (676, 674), (668, 688), (660, 702)],
            nsh=(710, 560),
            fsh=(720, 542),
        ),
        21: dict(
            spine=[(696, 654), (652, 630), (742, 642), (772, 616)],
            head=[(798, 642), (838, 630), (865, 624), (885, 620), (898, 630), (888, 626), (902, 633)],
            tail=[(600, 628), (520, 616), (468, 614)],
            leg_a=[(660, 654), (652, 668), (644, 682), (636, 696), (628, 710)],
            leg_b=[(694, 652), (686, 666), (678, 680), (670, 694), (662, 708)],
            nsh=(712, 572),
            fsh=(716, 552),
        ),
        22: dict(
            spine=[(696, 660), (652, 636), (742, 648), (772, 620)],
            head=[(797, 640), (837, 628), (864, 622), (884, 618), (898, 628), (888, 624), (902, 630)],
            tail=[(602, 630), (522, 616), (465, 615)],
            leg_a=[(662, 660), (654, 674), (646, 688), (638, 702), (630, 716)],
            leg_b=[(696, 658), (688, 672), (680, 686), (672, 700), (664, 714)],
            nsh=(714, 584),
            fsh=(714, 562),
        ),
        23: dict(
            spine=[(696, 664), (652, 640), (742, 652), (772, 622)],
            head=[(796, 638), (836, 626), (863, 620), (883, 616), (898, 626), (888, 622), (902, 627)],
            tail=[(604, 632), (524, 616), (468, 610)],
            leg_a=[(664, 666), (656, 680), (648, 694), (640, 710), (632, 724)],
            leg_b=[(698, 664), (690, 678), (682, 692), (674, 708), (666, 722)],
            nsh=(716, 596),
            fsh=(712, 570),
        ),
        24: dict(
            spine=[(695, 670), (652, 644), (742, 656), (772, 626)],
            head=[(796, 636), (836, 624), (863, 618), (883, 614), (898, 624), (888, 620), (902, 624)],
            tail=[(606, 636), (526, 618), (468, 608)],
            leg_a=[(666, 672), (658, 688), (650, 704), (642, 720), (634, 734)],
            leg_b=[(700, 670), (692, 686), (684, 702), (676, 718), (668, 732)],
            nsh=(718, 608),
            fsh=(714, 580),
        ),
        25: dict(
            spine=[(694, 668), (651, 642), (741, 654), (771, 626)],
            head=[(797, 634), (837, 622), (864, 616), (884, 612), (898, 622), (888, 618), (902, 621)],
            tail=[(608, 646), (528, 626), (470, 608)],
            leg_a=[(668, 676), (660, 692), (652, 708), (644, 726), (636, 740)],
            leg_b=[(702, 674), (694, 690), (686, 706), (678, 724), (670, 738)],
            nsh=(712, 600),
            fsh=(706, 580),
        ),
        26: dict(
            spine=[(694, 668), (651, 642), (741, 654), (771, 626)],
            head=[(797, 634), (837, 622), (864, 616), (884, 612), (898, 622), (888, 618), (902, 621)],
            tail=[(608, 646), (528, 626), (470, 608)],
            leg_a=[(668, 676), (660, 692), (652, 708), (644, 726), (636, 740)],
            leg_b=[(702, 674), (694, 690), (686, 706), (678, 724), (670, 738)],
            nsh=(712, 600),
            fsh=(706, 580),
        ),
        27: dict(
            spine=[(694, 668), (651, 642), (741, 654), (771, 626)],
            head=[(797, 634), (837, 622), (864, 616), (884, 612), (898, 622), (888, 618), (902, 621)],
            tail=[(608, 646), (528, 626), (470, 608)],
            leg_a=[(668, 676), (660, 692), (652, 708), (644, 726), (636, 740)],
            leg_b=[(702, 674), (694, 690), (686, 706), (678, 724), (670, 738)],
            nsh=(712, 600),
            fsh=(706, 580),
        ),
        28: dict(
            spine=[(696, 672), (652, 646), (742, 658), (772, 630)],
            head=[(796, 628), (836, 616), (863, 610), (883, 606), (898, 618), (888, 612), (902, 615)],
            tail=[(610, 650), (530, 630), (472, 612)],
            leg_a=[(670, 682), (662, 700), (654, 720), (646, 738), (638, 752)],
            leg_b=[(704, 680), (696, 698), (688, 716), (680, 734), (672, 750)],
            nsh=(716, 610),
            fsh=(710, 588),
        ),
        29: dict(
            spine=[(698, 676), (654, 650), (744, 662), (774, 634)],
            head=[(795, 624), (835, 612), (862, 606), (882, 602), (898, 614), (888, 608), (902, 610)],
            tail=[(612, 654), (532, 634), (474, 616)],
            leg_a=[(672, 688), (664, 708), (656, 728), (648, 748), (640, 762)],
            leg_b=[(706, 686), (698, 706), (690, 726), (682, 744), (674, 760)],
            nsh=(718, 620),
            fsh=(712, 596),
        ),
    }

    for fi in range(1, 30):
        b = body[fi]
        nt = near_tip[fi]
        ft = far_tip[fi]
        nsh = b["nsh"]
        fsh = b["fsh"]
        # Elbow / wrist: 1/3 and 2/3 toward tip (eye continuity along flap arc).
        nelbow = (nsh[0] * 0.55 + nt[0] * 0.45, nsh[1] * 0.55 + nt[1] * 0.45)
        nwrist = (nsh[0] * 0.28 + nt[0] * 0.72, nsh[1] * 0.28 + nt[1] * 0.72)
        felbow = (fsh[0] * 0.55 + ft[0] * 0.45, fsh[1] * 0.55 + ft[1] * 0.45)
        fwrist = (fsh[0] * 0.28 + ft[0] * 0.72, fsh[1] * 0.28 + ft[1] * 0.72)
        # Digit spread scales with flap: wider when wings down.
        n_spread = 28 + abs(nt[1] - 600) * 0.04
        f_spread = 22 + abs(ft[1] - 520) * 0.03
        near_tips = _digit_tips(nwrist, nt, n_spread, "near")
        far_tips = _digit_tips(fwrist, ft, f_spread, "far")
        # Snap secondary digit tips onto opaque too (skip main tip which is already snapped).
        near_tips = [
            _snap_opaque(fi, *near_tips[0]),
            _snap_opaque(fi, *near_tips[1]),
            nt,
        ]
        far_tips = [
            _snap_opaque(fi, *far_tips[0]),
            _snap_opaque(fi, *far_tips[1]),
            ft,
        ]
        F[fi] = _compose(
            spine=b["spine"],
            head=b["head"],
            tail=b["tail"],
            leg_a=b["leg_a"],
            leg_b=b["leg_b"],
            near_arm=[nsh, nelbow, nwrist],
            near_tips=near_tips,
            far_arm=[fsh, felbow, fwrist],
            far_tips=far_tips,
        )
    return F


def build() -> dict:
    F = _eye_frame_table()
    seed = _load_f0()
    for n, j in seed.items():
        if F[0][n] != j:
            raise SystemExit(f"f0 drift on {n}: {F[0][n]} vs seed {j}")
    need = set(seed)
    for i in range(30):
        if i not in F:
            raise SystemExit(f"missing frame {i}")
        if set(F[i]) != need:
            raise SystemExit(
                f"frame {i} bone mismatch missing={need - set(F[i])} extra={set(F[i]) - need}"
            )
    return {
        "method": "human_eye_landmark_authoring",
        "nnScale": 3,
        "notes": (
            "Per-frame eye marks for roc move g0. Each frame authored from "
            "previous-frame continuity + current NN/grid/contact-sheet sprite. "
            "wingA/022=NEAR (down f00 → peak y414 f15 → down), wingB/025=FAR; "
            "tip 035 near digit, tip 043 far digit; beak 028; tail 004. "
            "Wing tips seated on opaque silhouette (f0 seed exact). "
            "Not LK / not procedural interpolation as authority."
        ),
        "frames": {str(i): F[i] for i in range(30)},
    }


def main() -> int:
    AUTH.mkdir(parents=True, exist_ok=True)
    doc = build()
    path = AUTH / "authored_all_frames.json"
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "ok": True,
                "frames": 30,
                "bonesPerFrame": len(doc["frames"]["0"]),
                "method": doc["method"],
                "out": str(path).replace("\\", "/"),
                "nearTip035": [doc["frames"][str(i)]["Bone_035"] for i in range(30)],
                "farTip043": [doc["frames"][str(i)]["Bone_043"] for i in range(30)],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
