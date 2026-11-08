"""Fast CPU-side contract checks for the V2 package.

These checks deliberately do not start Blender or load a vision model.  The
GPU parity and renderer tests are run by the notebook smoke cell because they
need the local CUDA extension and the selected unit asset.
"""
from __future__ import annotations

from pathlib import Path

import torch
import numpy as np

from .blender_export import _interpolated_poses
from .contracts import CameraSpec, PoseState, preset_config
from .renderer import _axis_angle_matrix
from .targets import _front_perspective_frame_name, _source_files, canonicalize_front_rgb_mask


def run() -> dict[str, object]:
    config = preset_config("plausible_3d", semantic_microbatch=1)
    assert config.source_kind == "def"
    assert config.interpolation_output_fps == 60.0
    assert config.loop_objective_enabled is False
    assert config.front_view_fit_camera_scale is True
    dino_config = preset_config(
        "fast",
        dense_model_id="facebook/dinov3-vits16-pretrain-lvd1689m",
        dense_model_family="dino",
        dense_layers=("last",),
        dense_local_files_only=True,
    )
    assert dino_config.dense_model_family == "dino"
    assert dino_config.dense_local_files_only is True
    CameraSpec().validate()

    # Generic picker exports use frame_00.png while the generated library
    # indexes the same frame as {group}_{frame}_front.png.
    assert _front_perspective_frame_name(13, "frame_00") == "13_00_front.png"
    assert _front_perspective_frame_name(13, "00") == "13_00_front.png"

    # Generated front references are deliberately normalized before the
    # session's one-time bind-pose camera scale fit.  This remains a CPU-only
    # contract check and does not invoke a renderer.
    raw_rgb = np.zeros((32, 48, 3), dtype=np.float32)
    raw_rgb[4:20, 9:31, 0] = 0.8
    raw_mask = (raw_rgb.max(axis=-1) > 0.0).astype(np.float32)
    normalized_rgb, normalized_mask = canonicalize_front_rgb_mask(
        raw_rgb,
        raw_mask,
        CameraSpec(width=32, height=32, offset=(16.0, 16.0)),
        subject_extent=0.5,
        subject_padding=0.1,
    )
    assert normalized_rgb.shape == (32, 32, 3)
    assert normalized_mask.shape == (32, 32)
    assert float(normalized_mask.sum()) > 0.0

    try:
        # The provenance guard runs before filesystem access, so this does
        # not need to create a temporary directory on Windows.
        _source_files(Path("rife_frames"))
    except ValueError as exc:
        assert "interpolated" in str(exc)
    else:
        raise AssertionError("RIFE source directory was not rejected")

    pose = PoseState(
        registration=torch.zeros((1, 7)),
        motion_translation=torch.zeros((1, 2, 3)),
        motion_rotation=torch.zeros((1, 2, 3)),
        bone_rotation=torch.zeros((1, 2, 3, 3)),
        frame_indices=(0, 1),
    )
    interpolated, keyframes = _interpolated_poses(
        pose,
        source_fps=12.0,
        output_fps=60.0,
        mode="quaternion_slerp",
        loop=False,
    )
    assert len(interpolated) == 6
    assert keyframes == [0, 5]
    assert torch.equal(interpolated[0].motion_rotation, pose.motion_rotation[:, :1])
    assert torch.equal(interpolated[-1].motion_rotation, pose.motion_rotation[:, 1:2])

    # Motion roots and bones start at the bind pose.  The renderer's rotation
    # map must therefore expose a usable first derivative at zero; a normalized
    # axis-angle implementation can accidentally make these variables
    # permanently invisible to gradient descent.
    zero_rotation = torch.zeros((1, 3), dtype=torch.float32, requires_grad=True)
    zero_matrix = _axis_angle_matrix(zero_rotation)
    zero_matrix[..., 0, 1].sum().backward()
    assert torch.isfinite(zero_rotation.grad).all()
    assert float(torch.linalg.vector_norm(zero_rotation.grad).item()) > 0.0

    timed, timed_keyframes = _interpolated_poses(
        pose,
        source_fps=12.0,
        output_fps=10.0,
        frame_durations=(0.2, 0.4),
        mode="quaternion_slerp",
        loop=False,
    )
    assert len(timed) == 3
    assert timed_keyframes == [0, 2]
    return {"ok": True, "interpolatedFrames": len(interpolated), "keyframes": keyframes, "timedFrames": len(timed)}


if __name__ == "__main__":
    print(run())
