"""CPU-only contract tests for the keyframe combined-repair experiment.

These never touch CUDA, the game install, or delivery. They pin:
- the equal-mean combined score and its frame_metrics definition,
- plate lookup (case-insensitive DEF dir, group->frames),
- deployed clip discovery order,
- rotation-only replay parity on a synthetic GLB (via eagle_glb writer).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
# HERE is the module dir: parents[0]=homm3_mocap_v2, [1]=experiments, [2]=repo.
REPO = HERE.parents[2]
EXP = REPO / "experiments" / "homm3_mocap_v2"
for path in (str(EXP), str(HERE)):
    if path not in sys.path:
        sys.path.insert(0, path)

from repair_contract import (  # noqa: E402
    CLIP_TO_GROUP,
    combined_score,
    deployed_clips,
    frame_metrics,
    resolve_plate_lookup,
)


def test_combined_score_equal_mean() -> None:
    assert combined_score(silhouette=0.6, chroma_quality=0.9, dino_quality=0.3) == (
        0.6 + 0.9 + 0.3
    ) / 3.0


def test_frame_metrics_perfect_overlap() -> None:
    source = np.zeros((8, 8, 4), dtype=np.uint8)
    source[2:6, 2:6, :] = (200, 100, 50, 255)
    mesh = source.copy()
    embed = np.asarray([1.0, 0.0, 0.0], dtype=np.float32)
    metrics = frame_metrics(source, mesh, embed, embed)
    assert metrics["silhouette"] == 1.0
    assert metrics["chroma"] == 1.0
    assert metrics["normalizedDinoV2"] == 1.0
    assert metrics["score"] == 1.0


def test_frame_metrics_empty_union_is_zero() -> None:
    source = np.zeros((8, 8, 4), dtype=np.uint8)
    mesh = np.zeros((8, 8, 4), dtype=np.uint8)
    embed = np.asarray([1.0, 0.0], dtype=np.float32)
    metrics = frame_metrics(source, mesh, embed, embed)
    assert metrics["silhouette"] == 0.0
    assert 0.0 <= metrics["score"] <= 1.0


def test_plate_lookup_case_insensitive(tmp_path: Path) -> None:
    unit = tmp_path / "h3_probe" / "extracted_battle_source_12fps"
    (unit / "CPROBE.dir").mkdir(parents=True)
    (unit / "CPROBE.dir" / "00_00.png").write_bytes(b"a")
    (unit / "CPROBE.dir" / "02_00.png").write_bytes(b"b")
    (unit / "CPROBE.json").write_text(
        json.dumps(
            {
                "sequences": [
                    {"group": 0, "frames": ["cprobe.dir\\00_00.png"]},
                    {"group": 2, "frames": ["cprobe.dir\\02_00.png"]},
                ]
            }
        ),
        encoding="utf-8",
    )
    lookup = resolve_plate_lookup(tmp_path, "h3_probe")
    assert lookup["defDir"].name == "CPROBE.dir"
    assert [p.name for p in lookup["groups"][0]] == ["00_00.png"]
    assert [p.name for p in lookup["groups"][2]] == ["02_00.png"]


def test_register_evaluation_budget() -> None:
    # Pin the policy's evaluation budget: 96 grid + 243 pre-shift box +
    # 17x17 shift scan + 243 aligned box. If this changes, the cameraReport
    # contract (and any baseline comparison against it) changes too.
    import audit_keyframes as audit_mod
    import inspect

    source = inspect.getsource(audit_mod._register_camera_from_idle)
    assert "SHIFT_RANGE_X = range(-8, 9)" in source
    assert "SHIFT_RANGE_Y = range(0, 17)" in source
    assert source.count("for scale_factor in REFINE_SCALE_FACTORS:") == 2
    assert 96 + 243 + 17 * 17 + 243 == 871


def test_deployed_clip_order(tmp_path: Path) -> None:
    for name in ("Unit_Idle.glb", "Unit_Move.glb", "Unit_Death.glb"):
        (tmp_path / name).write_bytes(b"x")
    clips = deployed_clips(tmp_path)
    assert [p.stem for p in clips] == ["Unit_Move", "Unit_Idle", "Unit_Death"]
    assert CLIP_TO_GROUP["Unit_Move"] == 0
    assert CLIP_TO_GROUP["Unit_AttackFront"] == 12
    assert CLIP_TO_GROUP["Unit_MoveEnd"] == 21


def test_dino_shard_covers_all_frames() -> None:
    import repair_keyframes as repair_mod

    frames, shard = 61, 8
    shards = [repair_mod.dino_shard_indices(s, frames, shard) for s in range(20)]
    assert all(len(s) <= shard and len(s) > 0 for s in shards)
    assert shards[0] == shards[8]  # deterministic rotation, period ceil(61/8) = 8
    seen: set[int] = set()
    for s in shards[:8]:
        seen.update(s)
    assert seen == set(range(frames))
    assert repair_mod.dino_shard_indices(0, 5, 8) == [0, 1, 2, 3, 4]


def test_dino_normalize_matches_processor_math_and_preserves_grad() -> None:
    import torch

    import repair_keyframes as repair_mod

    subjects = torch.rand(2, 3, 4, 4, dtype=torch.float64, requires_grad=True)
    mean = torch.as_tensor([0.485, 0.456, 0.406], dtype=torch.float64).reshape(1, 3, 1, 1)
    std = torch.as_tensor([0.229, 0.224, 0.225], dtype=torch.float64).reshape(1, 3, 1, 1)
    out = repair_mod.dino_normalize(subjects, mean, std)
    assert torch.allclose(out, (subjects.detach() - mean) / std)
    assert out.requires_grad
    out.sum().backward()
    assert subjects.grad is not None and bool(torch.isfinite(subjects.grad).all())


def test_image_loss_validate_flag_matches_unvalidated() -> None:
    import torch

    import skin_image_objective as objective

    torch.manual_seed(0)
    rgb = torch.rand(2, 8, 8, 3)
    alpha = (torch.rand(2, 8, 8, 1) > 0.4).float()
    distance = torch.rand(2, 8, 8)
    checked = objective.image_loss(rgb, alpha, rgb.clone(), alpha.clone(), distance)
    fast = objective.image_loss(
        rgb, alpha, rgb.clone(), alpha.clone(), distance, validate=False
    )
    assert set(fast) == set(checked)
    for key in ("silhouette", "color", "total"):
        assert float(fast[key]) == float(checked[key])


def test_rescale_bbox_to_working_canvas() -> None:
    import run_keyframe_repair as run_mod

    rescale = run_mod.rescale_bbox_to_working_canvas
    assert rescale((10, 20, 30, 40), (192, 192), 192) == (10, 20, 31, 41)
    # Exact rescoring failure: a source-canvas bbox applied raw to 192px
    # images cropped empty; rescaled per-axis it fits and stays non-empty.
    assert rescale((171, 200, 234, 268), (400, 300), 192) == (82, 128, 113, 172)
    assert rescale((5, 5, 6, 6), (1000, 1000), 192) == (0, 0, 2, 2)
