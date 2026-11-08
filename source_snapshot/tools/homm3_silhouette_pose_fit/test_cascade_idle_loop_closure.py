"""Idle suffix loop closure helpers."""
from __future__ import annotations

import copy


def run() -> dict[str, object]:
    from cascade_idle_loop_closure import (
        lock_idle_suffix_winner,
        mirror_idle_suffix_from_prefix,
    )

    import torch

    winner = torch.tensor([1, 2, 3, 4, 5, 6], dtype=torch.long)
    locked = lock_idle_suffix_winner(winner, suffix_count=2, frame_count=6)
    assert locked.tolist() == [1, 2, 3, 4, 0, 0]

    bones = torch.zeros((6, 2, 3))
    root_t = torch.arange(6, dtype=torch.float32).unsqueeze(1).repeat(1, 3)
    root_r = torch.zeros((6, 3))
    bones[0, 0, 0] = 1.0
    bones[1, 1, 1] = 2.0
    copied = mirror_idle_suffix_from_prefix(
        bones,
        root_t,
        root_r,
        prefix_count=2,
        suffix_count=2,
    )
    assert copied == 2
    assert float(bones[4, 0, 0]) == 1.0
    assert float(bones[5, 1, 1]) == 2.0
    assert float(root_t[4, 0]) == 0.0
    assert float(root_t[5, 0]) == 1.0

    from roc_stacked_solve_common import JOINT_DINO_QUICK_LOOSE_PATCH

    assert JOINT_DINO_QUICK_LOOSE_PATCH["idle_suffix_mirror_prefix_enabled"] is True
    return {"ok": True, "copied": copied}


if __name__ == "__main__":
    print(run())
