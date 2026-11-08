"""CPU tests for freeze/rotate of GPU clip poses. No search, no CUDA."""
from __future__ import annotations

import json
import math
from pathlib import Path

from gpu_cascade_batch_lock import SCRIPT_TOKENS
from cascade_clip_pose_tweak import (
    MOTION_ROOT_KEY,
    MOTION_ROOT_ROTATION_KEY,
    apply_operations,
    bone_angles_rad,
    build_axis_probe_trials,
    build_tweaked_payload,
    expand_descendants,
    gpu_config_for_preview,
    inspect_clip,
    occupancy_iou,
    parse_frame_spec,
    root_rotation_deg,
)
from roc_gpu_cascade_experiment import persist_gpu_clip_result


def _pose(bone_x: float = 0.0) -> dict:
    return {
        "Bone_A": {"x": bone_x, "y": 0.0, "z": 0.0},
        MOTION_ROOT_KEY: {"forward": 0.0, "lateral": 0.0, "vertical": 0.0},
        MOTION_ROOT_ROTATION_KEY: {
            "camera_forward": 0.0,
            "camera_right": 0.0,
            "camera_up": 0.0,
        },
    }


def _clip() -> dict:
    poses = {
        "0": _pose(0.0),
        "1": _pose(math.radians(20.0)),
        "2": _pose(math.radians(40.0)),
        "3": _pose(math.radians(10.0)),
    }
    return {
        "poses": poses,
        "frameIndices": [0, 1, 2, 3],
        "skinnedBones": ["Bone_A", "Bone_B"],
        "bones": ["Bone_A", "Bone_B"],
        "searchBones": ["Bone_A"],
        "solver": "cascade",
        "score": 0.5,
        "frameScores": [0.5, 0.5, 0.5, 0.5],
        "config": {"joint_limit_deg": 150.0, "bone_limit_scale_overrides": []},
        "targetPaths": ["V:/unused/00.png"],
        "cameraFitPath": "V:/unused/camera.json",
    }


def run() -> dict[str, object]:
    frames = (0, 1, 2, 3)
    assert parse_frame_spec("all", frames) == frames
    assert parse_frame_spec("1-2", frames) == (1, 2)
    assert parse_frame_spec("0,3", frames) == (0, 3)
    try:
        parse_frame_spec("4", frames)
        raise AssertionError("out-of-range frames must fail closed")
    except ValueError as exc:
        assert "not in this clip" in str(exc)

    hierarchy = {
        "Bone_A": {"index": 0, "parent": None, "children": ("Bone_B",)},
        "Bone_B": {"index": 1, "parent": "Bone_A", "children": ()},
    }
    assert expand_descendants(("Bone_A",), hierarchy) == ("Bone_A", "Bone_B")
    try:
        expand_descendants((MOTION_ROOT_KEY,), hierarchy)
        raise AssertionError("root descendants must fail closed")
    except ValueError as exc:
        assert "motion root" in str(exc)

    payload = _clip()
    frozen = apply_operations(
        payload,
        [{"op": "freeze", "bone": "Bone_A", "frames": "1-2", "source": "previous"}],
    )
    assert abs(bone_angles_rad(frozen[1], "Bone_A")["x"]) < 1e-9
    assert abs(bone_angles_rad(frozen[2], "Bone_A")["x"]) < 1e-9
    assert abs(bone_angles_rad(frozen[3], "Bone_A")["x"] - math.radians(10.0)) < 1e-9

    bind = apply_operations(
        payload,
        [{"op": "freeze", "bone": "Bone_A", "frames": "3", "source": "bind"}],
    )
    assert "Bone_A" not in bind[3]

    rotated = apply_operations(
        payload,
        [{"op": "rotate", "bone": "Bone_A", "frames": [1], "axis": "x", "delta_deg": -5.0}],
    )
    got = math.degrees(bone_angles_rad(rotated[1], "Bone_A")["x"])
    assert abs(got - 15.0) < 1e-6, got

    copied = apply_operations(
        payload,
        [{"op": "copy_frame", "from": 0, "frames": "1-3"}],
    )
    for frame in (1, 2, 3):
        assert abs(bone_angles_rad(copied[frame], "Bone_A")["x"]) < 1e-9

    yawed = apply_operations(
        payload,
        [
            {
                "op": "rotate",
                "bone": "root_rotation",
                "frames": "2",
                "axis": "camera_up",
                "delta_deg": 12.0,
            }
        ],
    )
    assert abs(root_rotation_deg(yawed[2])["camera_up"] - 12.0) < 1e-9

    try:
        apply_operations(
            payload,
            [{"op": "rotate", "bone": "Bone_NOPE", "frames": "1", "axis": "x", "delta_deg": 1.0}],
        )
        raise AssertionError("unknown bone must fail closed")
    except ValueError as exc:
        assert "unknown joint" in str(exc)

    try:
        apply_operations(
            payload,
            [{"op": "freeze", "bone": "Bone_A", "frames": "0", "source": "previous"}],
        )
        raise AssertionError("freeze first frame from previous must fail closed")
    except ValueError as exc:
        assert "first clip frame" in str(exc)

    try:
        apply_operations(
            payload,
            [{"op": "rotate", "bone": "Bone_A", "frames": "1", "axis": "x", "delta_deg": 200.0}],
        )
        raise AssertionError("over-limit rotate must fail closed")
    except ValueError as exc:
        assert "joint limit" in str(exc)

    try:
        apply_operations(
            payload,
            [
                {
                    "op": "freeze",
                    "bone": "Bone_A",
                    "frames": "1",
                    "source": "previous",
                    "include_descendants": True,
                }
            ],
        )
        raise AssertionError("descendants without hierarchy must fail closed")
    except ValueError as exc:
        assert "include_descendants" in str(exc)

    with_kids = apply_operations(
        payload,
        [
            {
                "op": "freeze",
                "bone": "Bone_A",
                "frames": "2",
                "source": "bind",
                "include_descendants": True,
            }
        ],
        hierarchy=hierarchy,
    )
    assert "Bone_A" not in with_kids[2]
    assert "Bone_B" not in with_kids[2]

    report = inspect_clip(payload, hierarchy=hierarchy)
    assert report["frameIndices"] == [0, 1, 2, 3]
    moved = next(row for row in report["bones"] if row["bone"] == "Bone_A")
    assert 1 in moved["movedFrames"]
    assert 2 in moved["movedFrames"]

    tweaked = build_tweaked_payload(
        payload,
        frozen,
        source_clip="V:/fake/gpu_clip_result.json",
        operations=[{"op": "freeze", "bone": "Bone_A", "frames": "1-2", "source": "previous"}],
    )
    assert tweaked["solver"] == "cascade_manual_tweak"
    assert tweaked.get("score") is None or "score" not in tweaked
    assert "frameScores" not in tweaked
    assert tweaked["tweakReport"]["searched"] is False
    assert tweaked["tweakReport"]["damped"] is False

    preview_cfg = gpu_config_for_preview(
        {
            "resolution": [384, 344],
            "chroma_weight": 0.2,
            "motion_weight": 1.0,
            "score_mode": "geometry",
            "exact_raster_enabled": True,
            "joint_limit_deg": 150.0,
            "bone_limit_scale_overrides": [],
            "root_rotation_axes": ["camera_forward", "camera_right", "camera_up"],
        }
    )
    preview_cfg.validate()
    assert preview_cfg.collision_enabled is False
    assert preview_cfg.collision_weight == 0.0
    assert preview_cfg.resolution == (384, 344)
    try:
        gpu_config_for_preview({"score_mode": "dinov3_dense"})
        raise AssertionError("dinov3_dense preview must fail closed")
    except ValueError as exc:
        assert "dinov3_dense" in str(exc)

    source = Path(__file__).read_text(encoding="utf-8")
    lib = Path(__file__).with_name("cascade_clip_pose_tweak.py").read_text(encoding="utf-8")
    cli = Path(__file__).with_name("tweak_gpu_clip_poses.py").read_text(encoding="utf-8")
    assert "optimize_clip(" not in lib
    assert "optimize_clip(" not in cli
    assert "physics_smooth" not in lib.split("gpu_config_for_preview")[0]
    assert persist_gpu_clip_result is not None
    assert "tweak_gpu_clip_poses.py" in SCRIPT_TOKENS
    assert "acquire_cascade_batch_lock" in cli
    assert "inspect" in cli and "apply" in cli and "preview" in cli and "probe" in cli

    import numpy as np

    pred = np.zeros((4, 4), dtype=np.float32)
    target = np.zeros((4, 4), dtype=np.float32)
    pred[:2, :2] = 1.0
    target[1:3, 1:3] = 1.0
    scores = occupancy_iou(pred, target)
    assert scores["shared"] == 1.0
    assert scores["union"] == 7.0
    assert abs(scores["iou"] - (1.0 / 7.0)) < 1e-9
    known = frozenset({MOTION_ROOT_KEY, MOTION_ROOT_ROTATION_KEY, "Bone_A"})
    trials = build_axis_probe_trials(
        joints=("Bone_A", "root_rotation", "root_translation"),
        known=known,
        delta_deg=20.0,
        translate_delta=0.08,
    )
    ids = [trial["id"] for trial in trials]
    assert "Bone_A:x:+20.0" in ids
    assert "Bone_A:x:-20.0" in ids
    assert any(trial["op"] == "translate_root" and trial["axis"] == "lateral" for trial in trials)
    assert any(
        trial["op"] == "rotate"
        and trial["joint"] == MOTION_ROOT_ROTATION_KEY
        and trial["axis"] == "camera_forward"
        for trial in trials
    )
    return {"ok": True, "sourceChars": len(source)}


if __name__ == "__main__":
    print(json.dumps(run()))
