"""Far silhouette pixels must count as occupancy, not as a cheap depth match."""
from __future__ import annotations

import numpy as np
import torch

from gpu_depth_silhouette_solver import occupied_visible_depth, silhouette_and_depth_quality


def _score(target_fg, pred_fg, target_depth, pred_depth) -> dict[str, float]:
    terms = silhouette_and_depth_quality(
        target_foreground=target_fg,
        predicted_foreground=pred_fg,
        target_depth=target_depth,
        predicted_depth=pred_depth,
        depth_tolerance=0.08,
        depth_robust_delta=0.12,
    )
    iou = float(terms["silhouetteIoU"].item())
    depth_quality = float(terms["depthQuality"].item())
    return {
        "iou": iou,
        "depthQuality": depth_quality,
        "score": (0.65 * depth_quality + 0.35 * iou) / 1.0,
    }


def run() -> dict[str, object]:
    target_fg = torch.zeros((1, 16, 24), dtype=torch.bool)
    target_fg[0, 4:12, 6:16] = True
    target_fg[0, 12:15, 3:8] = True
    target_depth = torch.zeros((1, 16, 24), dtype=torch.float32)
    target_depth[0, 4:12, 6:16] = 0.85
    target_depth[0, 12:15, 3:8] = 0.04

    miss = target_fg.clone()
    miss[0, 12:15, 3:8] = False
    miss_depth = torch.zeros_like(target_depth)
    miss_depth[0, 4:12, 6:16] = 0.85

    cover = target_fg.clone()
    cover_depth = target_depth.clone()

    smear = target_fg.clone()
    smear_depth = torch.zeros_like(target_depth)
    smear_depth[0, 4:12, 6:16] = 0.85
    smear_depth[0, 12:15, 3:8] = 0.85

    missed = _score(target_fg, miss, target_depth, miss_depth)
    covered = _score(target_fg, cover, target_depth, cover_depth)
    smeared = _score(target_fg, smear, target_depth, smear_depth)

    far_vs_empty = float((target_depth[0, 13, 5] - 0.0).abs().item())
    assert far_vs_empty < 0.08, far_vs_empty
    assert covered["iou"] > missed["iou"], (covered, missed)
    assert covered["depthQuality"] > missed["depthQuality"], (covered, missed)
    assert covered["score"] > missed["score"], (covered, missed)
    assert smeared["depthQuality"] < covered["depthQuality"], (smeared, covered)
    assert smeared["score"] < covered["score"], (smeared, covered)

    empty = occupied_visible_depth(np.zeros((8, 8), dtype=np.float32), np.zeros((8, 8), dtype=bool))
    assert float(empty.max()) == 0.0
    far = np.full((8, 8), 0.01, dtype=np.float32)
    occupied = np.zeros((8, 8), dtype=bool)
    occupied[3:6, 3:6] = True
    visible = occupied_visible_depth(far, occupied)
    assert float(visible[4, 4]) >= 16.0 / 255.0
    assert float(visible[0, 0]) == 0.0
    return {
        "ok": True,
        "missed": missed,
        "covered": covered,
        "smeared": smeared,
    }


if __name__ == "__main__":
    print(run())
