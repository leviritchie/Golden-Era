#!/usr/bin/env python3
"""Print before/after depth bow metrics for one sprite + VDA depth frame."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import distance_transform_edt

DEPTH_BB = Path(__file__).resolve().parent
if str(DEPTH_BB) not in sys.path:
    sys.path.insert(0, str(DEPTH_BB))

from fill import correct_depth_bowing, prepare_billboard_frame, _opaque_mask  # noqa: E402
from geometry import load_depth01  # noqa: E402


def _metrics(depth: np.ndarray, mask: np.ndarray) -> dict[str, float]:
    edt = distance_transform_edt(mask)
    edge = mask & (edt <= 1.5)
    interior = mask & (edt >= 4.0)
    row_medians: list[float] = []
    rows: list[int] = []
    for row in range(depth.shape[0]):
        row_interior = interior[row]
        if row_interior.any():
            rows.append(row)
            row_medians.append(float(np.median(depth[row, row_interior])))
    corr = 0.0
    if len(rows) >= 3:
        corr = float(np.corrcoef(rows, row_medians)[0, 1])
    return {
        "edgeMean": float(depth[edge].mean()) if edge.any() else 0.0,
        "interiorMean": float(depth[interior].mean()) if interior.any() else 0.0,
        "interiorRowCorr": corr,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sprite", type=Path, required=True)
    parser.add_argument("--depth", type=Path, required=True)
    parser.add_argument("--bow-vertical", type=float, default=0.65)
    parser.add_argument("--bow-edge", type=float, default=0.75)
    parser.add_argument("--bow-radius", type=int, default=7)
    args = parser.parse_args()

    rgba = np.asarray(Image.open(args.sprite).convert("RGBA"), dtype=np.uint8)
    depth = load_depth01(args.depth)
    mask = _opaque_mask(rgba)
    _, corrected, stats = prepare_billboard_frame(
        rgba,
        depth,
        gap_close_radius=1,
        depth_smooth_radius=1,
        depth_bow_vertical_strength=args.bow_vertical,
        depth_bow_edge_strength=args.bow_edge,
        depth_bow_local_radius=args.bow_radius,
    )
    report = {
        "raw": _metrics(depth, mask),
        "corrected": _metrics(corrected, _opaque_mask(rgba)),
        "prepareStats": stats,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
