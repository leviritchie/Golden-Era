"""one_bone DINOv3 extra-term uses GPU RGB encode, not PIL."""
from __future__ import annotations

import torch
from PIL import Image

from gpu_depth_silhouette_solver import encode_dense_target_grids_from_rgb_hwc
from gpu_geometry_score import gpu_score_raster_resolution
from roc_gpu_cascade_experiment import score_dense_semantic_rgb_batch
from test_cascade_dinov3_score import _FakeDenseScorer


def test_one_bone_dense_target_encode_and_same_frame_score_skip_pil():
    original_fromarray = Image.fromarray

    def _forbid_fromarray(*args, **kwargs):
        raise AssertionError("one_bone dense must not convert GPU RGB through PIL")

    Image.fromarray = _forbid_fromarray
    try:
        scorer = _FakeDenseScorer()
        target_rgb = torch.zeros((2, 8, 8, 3), dtype=torch.float32)
        target_rgb[0, :, :, 0] = 1.0
        target_rgb[1, :, :, 1] = 1.0
        grids = encode_dense_target_grids_from_rgb_hwc(
            scorer,
            target_rgb,
            batch_size=2,
            subject_crop=False,
            subject_padding_frac=0.18,
        )
        assert len(grids) == 2
        assert set(grids[0]) == {"last"}
        candidate = torch.zeros((3, 8, 8, 3), dtype=torch.float32)
        candidate[:, :, :, 0] = 1.0
        positions = torch.zeros((3,), dtype=torch.long)
        qualities = score_dense_semantic_rgb_batch(
            scorer,
            target_grids_by_frame=grids,
            predicted_rgb=candidate,
            frame_positions=positions,
            batch_size=2,
            window_radius=1,
            position_weight=0.0,
            subject_crop=False,
        )
        assert int(qualities.shape[0]) == 3
        assert float(qualities.min().item()) > 0.99
    finally:
        Image.fromarray = original_fromarray


def test_one_bone_dense_scorer_without_gpu_extract_fails_closed():
    class _PilOnly:
        feature_layers = ("last",)

        def extract_layers(self, images):
            raise AssertionError("PIL extract_layers must not be the one_bone dense path")

    rgb = torch.zeros((1, 8, 8, 3), dtype=torch.float32)
    try:
        encode_dense_target_grids_from_rgb_hwc(
            _PilOnly(),
            rgb,
            batch_size=1,
            subject_crop=False,
            subject_padding_frac=0.18,
        )
        raise AssertionError("missing extract_layers_from_rgb_hwc must fail closed")
    except TypeError as exc:
        assert "extract_layers_from_rgb_hwc" in str(exc)


def test_one_bone_dense_upsamples_proxy_when_chroma_is_off():
    assert gpu_score_raster_resolution(
        (96, 86),
        chroma_weight=0.0,
        chroma_resolution=None,
        chroma_scale=4,
        rgb_upsample=True,
    ) == (384, 344)
    assert gpu_score_raster_resolution(
        (96, 86),
        chroma_weight=0.0,
        chroma_resolution=None,
        chroma_scale=4,
        rgb_upsample=False,
    ) == (96, 86)


def test_one_bone_dense_active_requires_weight():
    from gpu_depth_silhouette_solver import DepthSilhouetteConfig

    off = DepthSilhouetteConfig(dense_semantic_enabled=True, dense_semantic_weight=0.0)
    on = DepthSilhouetteConfig(dense_semantic_enabled=True, dense_semantic_weight=0.25)
    assert off.dense_semantic_active() is False
    assert on.dense_semantic_active() is True
