import copy
import io
import json
import math
from pathlib import Path
import sys
import unittest
from unittest import mock

from PIL import Image, ImageDraw


TOOLS = Path(__file__).resolve().parent
REPO_ROOT = TOOLS.parents[1]
sys.path.insert(0, str(TOOLS))

import preview_unit_vfx


class UnitVfxPreviewSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.project = REPO_ROOT / "oldenera_factions"
        cls.spec = json.loads((TOOLS / "beholder_electricity_preview.json").read_text(encoding="utf-8"))

    def test_beholder_assets_and_reference_frames_exist(self):
        preview_unit_vfx.validate_spec(self.spec, self.project)
        self.assertEqual(self.spec["unitSid"], "h3_beholder")
        self.assertEqual(len(self.spec["referenceFrames"]), 7)
        self.assertIs(self.spec["requireSkinnedMeshDeformation"], True)

    def test_beholder_cannot_disable_skinned_deformation_proof(self):
        for value in (False, "true", None):
            spec = copy.deepcopy(self.spec)
            spec["requireSkinnedMeshDeformation"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                preview_unit_vfx.validate_spec(spec, self.project)

    def test_beholder_shape_motion_thresholds_have_nontrivial_floors(self):
        for key, value in (
                ("meshDeformationThresholdRelativeToHeight", 0.0001),
                ("minimumShapeRmsRelativeToHeight", 0.0001)):
            spec = copy.deepcopy(self.spec)
            spec[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                preview_unit_vfx.validate_spec(spec, self.project)

    def make_report(self, animated):
        frames = []
        frame_count = math.ceil(self.spec["durationSeconds"] * self.spec["fps"])
        for index in range(frame_count):
            changed = 80 if animated and 1 <= index <= 4 else 0
            rms = 0.005 if changed else 0.0
            maximum = 0.012 if changed else 0.0
            frames.append({
                "meshShapeChangedVerticesFromStart": changed,
                "meshShapeChangedVerticesFromPrevious": changed,
                "meshRmsDistanceSignatureDeltaFromStart": rms,
                "meshRmsDistanceSignatureDeltaFromPrevious": rms,
                "meshMaxPerVertexDistanceSignatureDeltaFromStart": maximum,
                "meshMaxPerVertexDistanceSignatureDeltaFromPrevious": maximum,
            })
        return {
            "gameRuntimeUsed": False,
            "frameCount": frame_count,
            "skinnedVertexCount": 1200,
            "activeSkinnedRendererCount": 1,
            "activeSkinnedRendererPaths": ["body/skin"],
            "meshDistanceProbeCount": 64,
            "meshModelHeight": 2.0,
            "meshDeformationNormalization": "each renderer's initial baked local height",
            "meshDeformationThreshold": self.spec["meshDeformationThresholdRelativeToHeight"],
            "meshMinimumShapeRms": self.spec["minimumShapeRmsRelativeToHeight"],
            "meshDeformationPass": (
                "Active SkinnedMeshRenderer.BakeMesh(useScale:true); per-renderer renderer-local normalized "
                "pairwise-distance signatures; rigid and transform-scale motion excluded"
            ),
            "frames": frames,
            "eventMeshLightingChangedPixels": [32],
            "eventMeshBrightenedPixels": [20],
            "eventMeshSurfacePixels": [1200],
            "meshLightingPass": "Unity Point Light on Standard preview materials; arc geometry hidden during measurement",
        }

    def test_electricity_window_overlaps_authored_group_12_frames_three_and_four(self):
        source_fps = self.spec["sourceFramesPerSecond"]
        output_fps = self.spec["fps"]
        sample_times = [i / output_fps for i in range(math.ceil(self.spec["durationSeconds"] * output_fps))]
        active_reference_frames = {
            min(6, int(t * source_fps + 1e-6))
            for t in sample_times
            if any(start <= t < start + self.spec["effectDurationSeconds"]
                   for start in self.spec["eventTimesSeconds"])
        }
        self.assertEqual(active_reference_frames, {3, 4})

    def test_asset_paths_cannot_escape_unity_project(self):
        spec = copy.deepcopy(self.spec)
        spec["prefabAssetPath"] = "Assets/../../outside.prefab"
        with self.assertRaises(ValueError):
            preview_unit_vfx.validate_spec(spec, self.project)

    def test_preview_duration_is_bounded(self):
        spec = copy.deepcopy(self.spec)
        spec["durationSeconds"] = 20.01
        with self.assertRaises(ValueError):
            preview_unit_vfx.validate_spec(spec, self.project)

    def test_event_times_must_be_finite(self):
        spec = copy.deepcopy(self.spec)
        spec["eventTimesSeconds"] = [float("nan")]
        with self.assertRaises(ValueError):
            preview_unit_vfx.validate_spec(spec, self.project)

    def test_camera_direction_is_required(self):
        spec = copy.deepcopy(self.spec)
        del spec["cameraDirection"]
        with self.assertRaises(ValueError):
            preview_unit_vfx.validate_spec(spec, self.project)

    def test_anchor_view_offset_requires_three_finite_numbers(self):
        spec = copy.deepcopy(self.spec)
        spec["anchorViewOffsetRelativeToHeight"] = [0.0, float("inf"), 0.0]
        with self.assertRaises(ValueError):
            preview_unit_vfx.validate_spec(spec, self.project)

    def test_electric_arc_requires_bounded_mesh_light(self):
        for key, value in (
            ("arcLightIntensity", 0),
            ("arcLightIntensity", float("nan")),
            ("arcLightIntensity", True),
            ("arcLightRangeRelativeToHeight", 0),
            ("arcLightRangeRelativeToHeight", 3.01),
        ):
            spec = copy.deepcopy(self.spec)
            spec[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                preview_unit_vfx.validate_spec(spec, self.project)
        spec = copy.deepcopy(self.spec)
        del spec["arcLightIntensity"]
        with self.assertRaises(ValueError):
            preview_unit_vfx.validate_spec(spec, self.project)

    def test_electric_arc_report_requires_isolated_mesh_brightening(self):
        report = self.make_report(animated=True)
        preview_unit_vfx.validate_report(self.spec, report)
        report["eventMeshBrightenedPixels"] = [12]
        with self.assertRaises(RuntimeError):
            preview_unit_vfx.validate_report(self.spec, report)
        report["eventMeshBrightenedPixels"] = [20]
        report["eventMeshSurfacePixels"] = [10000]
        with self.assertRaises(RuntimeError):
            preview_unit_vfx.validate_report(self.spec, report)

    def test_report_rejects_static_mesh_despite_valid_light(self):
        report = self.make_report(animated=False)
        with self.assertRaisesRegex(RuntimeError, "mesh shape change"):
            preview_unit_vfx.validate_report(self.spec, report)

    def test_report_rejects_fake_small_threshold_and_impossible_shape_metrics(self):
        report = self.make_report(animated=True)
        report["meshDeformationThreshold"] = 1e-12
        with self.assertRaisesRegex(RuntimeError, "missing baked skinned-mesh deformation proof"):
            preview_unit_vfx.validate_report(self.spec, report)
        report = self.make_report(animated=True)
        report["frames"][1]["meshRmsDistanceSignatureDeltaFromPrevious"] = 0.02
        with self.assertRaisesRegex(RuntimeError, "invalid skinned shape-motion data"):
            preview_unit_vfx.validate_report(self.spec, report)
        report = self.make_report(animated=True)
        report["frames"][1]["meshRmsDistanceSignatureDeltaFromPrevious"] = 0.003
        report["frames"][1]["meshMaxPerVertexDistanceSignatureDeltaFromPrevious"] = 0.004
        with self.assertRaisesRegex(RuntimeError, "contradictory skinned shape-motion data"):
            preview_unit_vfx.validate_report(self.spec, report)

    def test_report_requires_active_renderer_provenance_and_bounded_probe_counts(self):
        report = self.make_report(animated=True)
        del report["activeSkinnedRendererPaths"]
        with self.assertRaisesRegex(RuntimeError, "missing baked skinned-mesh deformation proof"):
            preview_unit_vfx.validate_report(self.spec, report)
        report = self.make_report(animated=True)
        report["meshDistanceProbeCount"] = 65
        with self.assertRaisesRegex(RuntimeError, "missing baked skinned-mesh deformation proof"):
            preview_unit_vfx.validate_report(self.spec, report)
        report = self.make_report(animated=True)
        report["activeSkinnedRendererCount"] = 2
        report["activeSkinnedRendererPaths"] = ["body/skin", "weapon/skin"]
        report["meshDistanceProbeCount"] = 128
        preview_unit_vfx.validate_report(self.spec, report)

    def test_report_requires_local_height_normalization(self):
        report = self.make_report(animated=True)
        report["meshDeformationNormalization"] = "world-space model height"
        with self.assertRaisesRegex(RuntimeError, "missing baked skinned-mesh deformation proof"):
            preview_unit_vfx.validate_report(self.spec, report)

    def test_source_frame_rate_is_required_and_bounded(self):
        spec = copy.deepcopy(self.spec)
        del spec["sourceFramesPerSecond"]
        with self.assertRaises(ValueError):
            preview_unit_vfx.validate_spec(spec, self.project)
        spec["sourceFramesPerSecond"] = 0
        with self.assertRaises(ValueError):
            preview_unit_vfx.validate_spec(spec, self.project)
        spec["sourceFramesPerSecond"] = True
        with self.assertRaises(ValueError):
            preview_unit_vfx.validate_spec(spec, self.project)

    def test_editor_script_directory_redirect_is_rejected_before_creation(self):
        project = Path("V:/preview-project")
        editor_dir = project / "Assets" / "Editor"
        redirected = project / "Elsewhere"

        def resolve(path, *args, **kwargs):
            if path == editor_dir:
                return redirected
            if path == project:
                return project
            return path

        with mock.patch.object(Path, "resolve", autospec=True, side_effect=resolve):
            with mock.patch.object(Path, "mkdir") as mkdir:
                with self.assertRaises(ValueError):
                    preview_unit_vfx.ensure_editor_script_dir(project)
                mkdir.assert_not_called()

    def test_gif_delays_preserve_fractional_frame_rate(self):
        sixty_fps = preview_unit_vfx.gif_frame_durations(60, 6)
        twenty_four_fps = preview_unit_vfx.gif_frame_durations(24, 24)
        self.assertEqual(sixty_fps, [20, 10, 20, 20, 10, 20])
        self.assertEqual(sum(sixty_fps), 100)
        self.assertEqual(sum(twenty_four_fps), 1000)
        frames = [Image.new("RGB", (2, 2), (index * 30, 0, 0)) for index in range(6)]
        encoded = io.BytesIO()
        frames[0].save(
            encoded,
            format="GIF",
            save_all=True,
            append_images=frames[1:],
            duration=sixty_fps,
            optimize=False,
        )
        encoded.seek(0)
        with Image.open(encoded) as gif:
            actual = []
            for frame in range(gif.n_frames):
                gif.seek(frame)
                actual.append(gif.info["duration"])
        self.assertEqual(actual, sixty_fps)
        for frame in frames:
            frame.close()

    def test_effect_must_overlap_a_rendered_sample(self):
        spec = copy.deepcopy(self.spec)
        spec["eventTimesSeconds"] = [0.255]
        spec["effectDurationSeconds"] = 0.01
        with self.assertRaises(ValueError):
            preview_unit_vfx.validate_spec(spec, self.project)

    def test_particle_prefab_requires_explicit_camera_margin(self):
        spec = copy.deepcopy(self.spec)
        spec["effectKind"] = "particlePrefab"
        spec["effectPrefabAssetPath"] = spec["prefabAssetPath"]
        spec.pop("effectBoundsMarginRelativeToHeight", None)
        with self.assertRaises(ValueError):
            preview_unit_vfx.validate_spec(spec, self.project)

    def test_output_refuses_paths_outside_preview_artifacts(self):
        outside = REPO_ROOT / "tmp" / "not-a-preview-output"
        with self.assertRaises(ValueError):
            preview_unit_vfx.output_directory(str(outside))

    def test_comparison_keeps_sprite_and_render_motion_in_a_stable_frame(self):
        references = []
        renders = []
        for x_pos in (20, 70):
            reference = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
            ImageDraw.Draw(reference).rectangle((x_pos, 40, x_pos + 9, 49), fill=(255, 0, 0, 255))
            references.append(reference)
            render = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
            ImageDraw.Draw(render).rectangle((x_pos, 40, x_pos + 9, 49), fill=(0, 255, 0, 255))
            renders.append(render)

        common_crop = preview_unit_vfx.shared_alpha_bounds(references)
        source_centroids = []
        render_centroids = []
        for reference, render in zip(references, renders):
            source_panel = preview_unit_vfx.fit_rgba(
                reference.crop(common_crop), (372, 426), Image.Resampling.NEAREST, crop_alpha=False
            )
            render_panel = preview_unit_vfx.fit_rgba(
                render, (372, 426), Image.Resampling.LANCZOS, crop_alpha=False
            )
            for panel, channel, centroids in (
                (source_panel, 0, source_centroids),
                (render_panel, 1, render_centroids),
            ):
                points = [
                    x for y in range(panel.height) for x in range(panel.width)
                    if (pixel := panel.getpixel((x, y)))[channel] > 220 and pixel[1 - channel] < 40
                ]
                self.assertTrue(points)
                centroids.append(sum(points) / len(points))
            source_panel.close()
            render_panel.close()

        self.assertGreater(abs(source_centroids[1] - source_centroids[0]), 50)
        self.assertGreater(abs(render_centroids[1] - render_centroids[0]), 50)
        for image in references + renders:
            image.close()


if __name__ == "__main__":
    unittest.main()
