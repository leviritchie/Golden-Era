#!/usr/bin/env python3
from __future__ import annotations

import unittest

from fused_push_mesh_raster_budget import (
    CHROMA_QUALITY,
    CHROMA_TIGHT,
    choose_batch_raster,
    primitive_triangle_count,
)


class MeshRasterBudgetTests(unittest.TestCase):
    def test_cavalier_class_keeps_chroma_quality_pack(self) -> None:
        chosen = choose_batch_raster(
            vertex_count=18_000,
            raster_triangle_count=4_000,
            primitive_count=1,
            skinned_joint_count=52,
            frame_count=18,
        )
        self.assertEqual(chosen["chroma_scale"], CHROMA_QUALITY)
        self.assertGreaterEqual(chosen["jointScoreHypsPerLaunch"], 12)
        self.assertEqual(
            chosen["joint_score_raster_batch"],
            chosen["jointScoreHypsPerLaunch"] * 18,
        )

    def test_dense_goblin_class_tightens_pack(self) -> None:
        light = choose_batch_raster(
            vertex_count=18_000,
            raster_triangle_count=4_000,
            primitive_count=1,
            skinned_joint_count=52,
            frame_count=25,
        )
        dense = choose_batch_raster(
            vertex_count=48_000,
            raster_triangle_count=12_000,
            primitive_count=6,
            skinned_joint_count=80,
            frame_count=25,
        )
        self.assertLess(
            dense["joint_score_raster_batch"],
            light["joint_score_raster_batch"],
        )
        self.assertEqual(dense["chroma_scale"], CHROMA_TIGHT)
        self.assertGreaterEqual(dense["jointScoreHypsPerLaunch"], 1)
        self.assertEqual(dense["joint_score_raster_batch"] % 25, 0)

    def test_high_joint_count_drops_chroma_even_when_verts_are_low(self) -> None:
        chosen = choose_batch_raster(
            vertex_count=10_528,
            raster_triangle_count=2_048,
            primitive_count=1,
            skinned_joint_count=80,
            frame_count=25,
        )
        self.assertEqual(chosen["chroma_scale"], CHROMA_TIGHT)
        self.assertLessEqual(chosen["joint_score_raster_batch"], 768)

    def test_fail_closed_on_empty_mesh_stats(self) -> None:
        with self.assertRaises(ValueError):
            choose_batch_raster(
                vertex_count=0,
                raster_triangle_count=10,
                primitive_count=1,
                skinned_joint_count=8,
                frame_count=12,
            )
        with self.assertRaises(ValueError):
            choose_batch_raster(
                vertex_count=100,
                raster_triangle_count=10,
                primitive_count=1,
                skinned_joint_count=8,
                frame_count=0,
            )

    def test_primitive_triangle_count(self) -> None:
        self.assertEqual(primitive_triangle_count(None, 9), 3)
        self.assertEqual(
            primitive_triangle_count([0, 1, 2, 3, 4, 5], 6),
            2,
        )
        with self.assertRaises(ValueError):
            primitive_triangle_count([0, 1, 2, 3], 4)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
