"""The GPU one-bone-depth live panel is the target | candidate | overlay image."""
from __future__ import annotations

import inspect
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from PIL import Image

from gpu_depth_silhouette_solver import (
    GpuDepthLivePreview,
    compose_chroma_occupancy_panel,
    compose_depth_silhouette_panel,
    live_preview_due,
    render_chroma_occupancy_preview,
    render_depth_silhouette_preview,
)
from roc_gpu_cascade_experiment import (
    GpuCascadeExperiment,
    cascade_live_preview_depth_panel,
    cascade_live_preview_frame_position,
    cascade_live_preview_frame_positions,
    cascade_live_preview_pane_size,
    compose_cascade_solver_watch,
)


def run() -> dict[str, object]:
    target_depth = np.zeros((8, 8), dtype=np.float32)
    predicted_depth = np.zeros((8, 8), dtype=np.float32)
    target_mask = np.zeros((8, 8), dtype=np.float32)
    predicted_mask = np.zeros((8, 8), dtype=np.float32)
    target_depth[2:5, 2:5] = 0.8
    predicted_depth[3:6, 3:6] = 0.4
    target_mask[2:5, 2:5] = 1.0
    predicted_mask[3:6, 3:6] = 1.0

    canvas = compose_depth_silhouette_panel(
        target_depth,
        predicted_depth,
        target_mask,
        predicted_mask,
        frame=10,
        label="f10 start",
        scale=1,
        predicted_alpha_threshold=0.01,
    )
    assert canvas.size == (24, 26), canvas.size
    overlay = np.asarray(canvas)[18:, 16:, :]
    # Shared 3x3 is the overlap of [2:5,2:5] and [3:6,3:6].
    assert tuple(overlay[2, 2]) == (235, 45, 45), overlay[2, 2]
    assert tuple(overlay[4, 4]) == (35, 210, 100), overlay[4, 4]
    assert tuple(overlay[5, 5]) == (45, 105, 240), overlay[5, 5]

    scaled = compose_depth_silhouette_panel(
        target_depth,
        predicted_depth,
        target_mask,
        predicted_mask,
        frame=10,
        scale=4,
    )
    assert scaled.size == (96, 104), scaled.size

    try:
        compose_depth_silhouette_panel(
            target_depth,
            predicted_depth[:7],
            target_mask,
            predicted_mask,
            frame=0,
        )
        raise AssertionError("mismatched depth panels must stay fail-closed")
    except ValueError as exc:
        assert "matching 2D arrays" in str(exc)

    try:
        GpuDepthLivePreview("x.png", every=0, scale=1, alpha_threshold=0.01)
        raise AssertionError("preview_every < 1 must stay fail-closed")
    except ValueError as exc:
        assert "preview_every" in str(exc)

    assert live_preview_due(visit=1, every=1, elapsed_s=0.0, min_interval_s=1.0, force=True)
    assert not live_preview_due(visit=1, every=1, elapsed_s=0.0, min_interval_s=1.0, force=False)
    assert live_preview_due(visit=1, every=1, elapsed_s=1.0, min_interval_s=1.0, force=False)
    assert not live_preview_due(visit=1, every=2, elapsed_s=10.0, min_interval_s=1.0, force=False)
    assert live_preview_due(visit=2, every=2, elapsed_s=10.0, min_interval_s=1.0, force=False)
    try:
        live_preview_due(visit=1, every=1, elapsed_s=1.0, min_interval_s=0.0, force=False)
        raise AssertionError("zero min_interval_s must stay fail-closed")
    except ValueError as exc:
        assert "min_interval_s" in str(exc)

    with TemporaryDirectory() as temp_dir:
        gif_path = render_depth_silhouette_preview(
            {
                "targetDepth": target_depth[None],
                "predictedDepth": predicted_depth[None],
                "targetMasks": target_mask[None],
                "predictedMasks": predicted_mask[None],
                "config": {"predicted_alpha_threshold": 0.01},
            },
            output_dir=Path(temp_dir),
            frame_indices=(10,),
            scale=1,
        )
        assert gif_path.is_file(), gif_path
        png = gif_path.parent / "preview_10.png"
        assert png.is_file(), png
        gif_image = np.asarray(Image.open(png))
        assert gif_image.shape == (26, 24, 3), gif_image.shape
        assert tuple(gif_image[20, 18]) == (235, 45, 45)

        target_rgb = np.zeros((8, 8, 3), dtype=np.float32)
        predicted_rgb = np.zeros((8, 8, 3), dtype=np.float32)
        target_rgb[2:5, 2:5] = (0.2, 0.8, 0.1)
        predicted_rgb[3:6, 3:6] = (0.9, 0.2, 0.1)
        color_canvas = compose_chroma_occupancy_panel(
            target_rgb,
            predicted_rgb,
            target_mask,
            predicted_mask,
            frame=10,
            scale=1,
        )
        assert color_canvas.size == (24, 26), color_canvas.size
        color_gif = render_chroma_occupancy_preview(
            {
                "targetRgb": target_rgb[None],
                "predictedRgb": predicted_rgb[None],
                "targetMasks": target_mask[None],
                "predictedMasks": predicted_mask[None],
                "config": {"predicted_alpha_threshold": 0.01},
            },
            output_dir=Path(temp_dir) / "color",
            frame_indices=(10,),
            scale=1,
        )
        assert color_gif.is_file(), color_gif
        color_png = np.asarray(Image.open(color_gif.parent / "preview_10.png"))
        assert color_png.shape == (26, 24, 3), color_png.shape
        assert tuple(color_png[20, 2]) == (51, 204, 26), color_png[20, 2]

    assert cascade_live_preview_frame_position(frame_count=18, idle_prefix_frames=0) == 0
    assert cascade_live_preview_frame_position(frame_count=18, idle_prefix_frames=8) == 8
    assert cascade_live_preview_frame_position(frame_count=8, idle_prefix_frames=8) == 7
    assert cascade_live_preview_frame_positions(
        frame_count=18,
        idle_prefix_frames=8,
        idle_suffix_frames=8,
        max_frames=4,
    ) == (0, 8, 9, 17)
    assert cascade_live_preview_pane_size(344, 384, max_width=96) == (86, 96)
    try:
        cascade_live_preview_frame_position(frame_count=0, idle_prefix_frames=0)
        raise AssertionError("empty clip must stay fail-closed")
    except ValueError as exc:
        assert "no clip frames" in str(exc)
    try:
        cascade_live_preview_frame_position(frame_count=8, idle_prefix_frames=-1)
        raise AssertionError("negative idle prefix must stay fail-closed")
    except ValueError as exc:
        assert "non-negative" in str(exc)

    mask = np.ones((8, 8), dtype=np.float32)
    rgb_a = np.zeros((8, 8, 3), dtype=np.float32)
    rgb_b = np.zeros((8, 8, 3), dtype=np.float32)
    rgb_a[2:5, 2:5] = (0.2, 0.8, 0.1)
    rgb_b[3:6, 3:6] = (0.9, 0.2, 0.1)
    first = compose_cascade_solver_watch(
        frames=(8,),
        current_label="base 1/2 done",
        current_rgb=(rgb_a,),
        current_mask=(mask,),
        target_mask=(mask,),
        pane_size=(8, 8),
    )
    assert first.size[0] == 8
    compared = compose_cascade_solver_watch(
        frames=(8, 14),
        current_label="base 2/2",
        current_rgb=(rgb_b, rgb_b),
        current_mask=(mask, mask),
        target_mask=(mask, mask),
        previous_label="base 1/2 done",
        previous_rgb=(rgb_a, rgb_a),
        pane_size=(8, 8),
        change_gain=4.0,
    )
    assert compared.size == (16, (18 + 8) * 4), compared.size
    unchanged = compose_cascade_solver_watch(
        frames=(8,),
        current_label="base 2/2 done",
        current_rgb=(rgb_a,),
        current_mask=(mask,),
        target_mask=(mask,),
        previous_label="base 1/2 done",
        previous_rgb=(rgb_a,),
        pane_size=(8, 8),
    )
    change_row = np.asarray(unchanged)[(18 + 8) * 2 + 18 : (18 + 8) * 3, :, :]
    assert float(change_row.max()) == 0.0
    changed_row = np.asarray(compared)[(18 + 8) * 2 + 18 : (18 + 8) * 3, :8, :]
    assert float(changed_row.max()) > 0.0

    rgb_placeholder = cascade_live_preview_depth_panel(None, mask, uses_rgb=True)
    assert rgb_placeholder.shape == mask.shape
    assert rgb_placeholder.dtype == np.float32
    assert float(rgb_placeholder.max()) == 0.0
    depth = np.full((8, 8), 0.4, dtype=np.float32)
    assert np.allclose(
        cascade_live_preview_depth_panel(depth, mask, uses_rgb=True),
        depth,
    )
    try:
        cascade_live_preview_depth_panel(None, mask, uses_rgb=False)
        raise AssertionError("geometry preview without VDA must stay fail-closed")
    except RuntimeError as exc:
        assert "target depth" in str(exc)

    refresh_src = inspect.getsource(GpuCascadeExperiment._refresh_live_preview)
    assert "cascade_live_preview_depth_panel" in refresh_src
    assert "uses_rgb" in refresh_src
    clip_src = inspect.getsource(GpuCascadeExperiment.optimize_clip)
    for label in (
        '"init"',
        '"root-search"',
        '"physics"',
        "ik done",
        "round_label",
        "{round_label} done",
        "commit=True",
    ):
        assert label in clip_src, label
    assert clip_src.count("self._preview_clip_pose(") >= 8
    preview_src = inspect.getsource(GpuCascadeExperiment._preview_clip_pose)
    assert "compose_cascade_solver_watch" in preview_src
    assert "commit" in preview_src

    return {
        "ok": True,
        "panel": list(canvas.size),
        "overlayTargetOnly": [int(value) for value in overlay[2, 2]],
        "overlayShared": [int(value) for value in overlay[4, 4]],
        "overlayCandidateOnly": [int(value) for value in overlay[5, 5]],
    }


if __name__ == "__main__":
    print(run())
