"""Escape worst-frame selection can weight collision alongside hybrid score."""
from __future__ import annotations

import torch

from roc_gpu_cascade_experiment import escape_worst_frame_indices, worst_frame_indices


def run() -> dict[str, object]:
    scores = torch.tensor([0.9, 0.65, 0.7, 0.6], dtype=torch.float32)
    collision = torch.tensor([0.0, 0.5, 0.01, 0.02], dtype=torch.float32)
    score_only = worst_frame_indices(scores, keep_count=2).tolist()
    assert score_only == [3, 1], score_only
    blended = escape_worst_frame_indices(
        scores,
        collision,
        keep_count=2,
        collision_weight=0.5,
    ).tolist()
    # frame 1: (1-0.65)+0.25=0.60; frame 3: 0.40 — collision pushes frame 1 ahead.
    assert blended == [1, 3], blended
    zero_weight = escape_worst_frame_indices(
        scores,
        collision,
        keep_count=2,
        collision_weight=0.0,
    ).tolist()
    assert zero_weight == score_only, zero_weight
    return {"scoreOnly": score_only, "blended": blended}


if __name__ == "__main__":
    print(run())
