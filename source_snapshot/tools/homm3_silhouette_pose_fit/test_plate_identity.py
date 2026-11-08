#!/usr/bin/env python3
"""Regression guard for repeated-plate detection and loop-seam measurement.

Pins two properties the continuous tracker depends on:

  1. Plate *identity* must not degrade into plate *similarity*. The anchor threshold
     sits between "pixel-identical" (RGB MAD 0.0000) and "adjacent idle frame"
     (0.0063 on h3_roc), a narrow gap. If a change widens matching, a mid-flap pose
     could anchor to a standing pose.
  2. A clip whose first and last plates are identical must be reported as a closed
     loop only when the *pose* also closes, not merely because the plates do.

Run: py -3 test_plate_identity.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import torch

TOOL = Path(__file__).resolve().parent
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from def_plate_identity import (  # noqa: E402
    earlier_plate_matches,
    loop_seam_report,
    plate_distance,
)

MAX_RGB_MAD = 0.004
MIN_ALPHA_IOU = 0.999


def _plate(fill: int, *, box: tuple[int, int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    """A 0..255 RGBA plate with one filled box, matching the DEF raster convention."""
    rgb = np.zeros((32, 32, 3), dtype=np.uint8)
    alpha = np.zeros((32, 32), dtype=np.uint8)
    top, left, bottom, right = box
    rgb[top:bottom, left:right] = fill
    alpha[top:bottom, left:right] = 255
    return rgb, alpha


def test_identical_plates_measure_zero() -> None:
    rgb, alpha = _plate(128, box=(8, 8, 24, 24))
    distance = plate_distance(rgb, alpha, rgb.copy(), alpha.copy())
    assert distance.rgb_mad == 0.0, f"identical plates must read 0.0, got {distance.rgb_mad}"
    assert distance.alpha_iou == 1.0
    assert distance.matches(max_rgb_mad=MAX_RGB_MAD, min_alpha_iou=MIN_ALPHA_IOU)


def test_normalised_input_is_refused_instead_of_silently_rescaled() -> None:
    rgb, alpha = _plate(128, box=(8, 8, 24, 24))
    try:
        plate_distance(
            rgb.astype(np.float32) / 255.0,
            alpha.astype(np.float32) / 255.0,
            rgb.astype(np.float32) / 255.0,
            alpha.astype(np.float32) / 255.0,
        )
    except ValueError as error:
        assert "0..255" in str(error)
        return
    raise AssertionError(
        "0..1 input must raise: inferring the scale would report a 255x smaller "
        "difference and declare unrelated plates identical"
    )


def test_shifted_plate_is_not_treated_as_identical() -> None:
    rgb_a, alpha_a = _plate(128, box=(8, 8, 24, 24))
    rgb_b, alpha_b = _plate(128, box=(9, 8, 25, 24))
    distance = plate_distance(rgb_a, alpha_a, rgb_b, alpha_b)
    assert not distance.matches(max_rgb_mad=MAX_RGB_MAD, min_alpha_iou=MIN_ALPHA_IOU), (
        f"a one-pixel shift must fail the identity test, got iou={distance.alpha_iou} "
        f"mad={distance.rgb_mad}"
    )


def test_only_earlier_frames_are_offered_as_anchors() -> None:
    rgb, alpha = _plate(128, box=(8, 8, 24, 24))
    other_rgb, other_alpha = _plate(200, box=(2, 2, 12, 12))
    rgbs = [rgb, other_rgb, rgb.copy(), rgb.copy()]
    alphas = [alpha, other_alpha, alpha.copy(), alpha.copy()]
    matches = earlier_plate_matches(
        rgbs, alphas, max_rgb_mad=MAX_RGB_MAD, min_alpha_iou=MIN_ALPHA_IOU
    )
    assert 0 not in matches, "frame 0 has no earlier frame and must never carry an anchor"
    assert 1 not in matches, "a distinct plate must not match"
    assert [entry[0] for entry in matches[2]] == [0]
    assert [entry[0] for entry in matches[3]] == [0, 2], (
        "every earlier copy must be offered so the caller can pick the best-solved one"
    )


def test_loop_seam_flags_a_pose_that_does_not_close() -> None:
    rgb, alpha = _plate(128, box=(8, 8, 24, 24))
    moved_rgb, moved_alpha = _plate(200, box=(2, 2, 12, 12))
    rgbs = [rgb, moved_rgb, rgb.copy()]
    alphas = [alpha, moved_alpha, alpha.copy()]

    closed = torch.zeros((3, 4, 3), dtype=torch.float32)
    closed[1, 0, 0] = 0.5
    report = loop_seam_report(
        rgbs=rgbs,
        alphas=alphas,
        bones=closed,
        root_translation=torch.zeros((3, 3)),
        root_rotation=torch.zeros((3, 3)),
    )
    assert report["plateIdentical"] is True
    assert report["seamMeanBoneDeltaDeg"] == 0.0, "identical end poses must show no seam"

    open_seam = closed.clone()
    open_seam[2, 0, 0] = 0.9
    popped = loop_seam_report(
        rgbs=rgbs,
        alphas=alphas,
        bones=open_seam,
        root_translation=torch.zeros((3, 3)),
        root_rotation=torch.zeros((3, 3)),
    )
    assert popped["plateIdentical"] is True
    assert popped["seamMeanBoneDeltaDeg"] > 0.0
    assert float(popped["seamPopRatio"]) > 1.0, (
        "a seam that moves more than an average interior frame must report a ratio "
        f"above 1, got {popped['seamPopRatio']}"
    )


def main() -> int:
    test_identical_plates_measure_zero()
    test_normalised_input_is_refused_instead_of_silently_rescaled()
    test_shifted_plate_is_not_treated_as_identical()
    test_only_earlier_frames_are_offered_as_anchors()
    test_loop_seam_flags_a_pose_that_does_not_close()
    print({"ok": True, "tests": 5})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
