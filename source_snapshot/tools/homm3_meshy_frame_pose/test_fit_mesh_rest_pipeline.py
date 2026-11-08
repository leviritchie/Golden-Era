"""Small integration tests for transform consumption and batch isolation."""
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fit_mesh_rest_pipeline as pipeline


class PipelineTests(unittest.TestCase):
    def test_authored_rest_and_tpose_reference_routes_are_explicit(self):
        rest, heads, parents, names = object(), object(), object(), object()
        authored, canonical = object(), object()
        with patch.object(pipeline, "corresponding_source_rest", return_value=authored) as match, \
             patch.object(pipeline, "tpose_joint_track", return_value={"joints": canonical}) as tpose:
            self.assertIs(pipeline.retarget_reference("smartrig-biped", rest, heads, parents, names), authored)
            match.assert_called_once_with(rest, heads, parents, names)
            tpose.assert_not_called()
            self.assertIs(pipeline.retarget_reference("biped-tpose", rest, heads, parents, names), canonical)
            tpose.assert_called_once_with(rest=rest, parents=parents, joint_names=names)
            with self.assertRaises(ValueError):
                pipeline.retarget_reference("unknown", rest, heads, parents, names)

    def test_failed_job_replaces_old_directory_handoff(self):
        job = {"unit": "archer", "out": "example/out"}
        with patch.object(sys, "argv", ["pipeline", "--manifest", "jobs.json"]), \
             patch.object(Path, "read_text", return_value=json.dumps({"jobs": [job]})), \
             patch.object(pipeline, "run_job", side_effect=OSError("missing source")), \
             patch.object(pipeline, "record_incomplete") as record:
            self.assertEqual(pipeline.main(), 1)
            self.assertEqual(record.call_args.args[0], pipeline.ROOT / "example/out")
            self.assertEqual(record.call_args.args[1]["status"], "error")
            self.assertEqual(record.call_args.args[1]["outputs"], {})

    def test_incomplete_record_invalidates_all_previews(self):
        with patch.object(Path, "mkdir"), patch.object(Path, "unlink") as unlink, patch.object(Path, "write_text") as write:
            pipeline.record_incomplete(Path("out"), {"status": "error", "outputs": {}})
            self.assertEqual(unlink.call_count, len(pipeline.PREVIEW_FILES))
            self.assertEqual(json.loads(write.call_args.args[0]), {"status": "error", "outputs": {}})

    def test_quick_review_renders_selected_poses_without_reel(self):
        calls = []
        renderer = types.SimpleNamespace(
            camera=lambda yaw, cloud: {"right": np.array([1., 0., 0.]), "down": np.array([0., 1., 0.]), "k": 1., "off": 0.},
            textured=lambda *args, **kwargs: (calls.append(True) or np.zeros((32, 32, 3))),
            label=lambda *args: None,
        )
        points = np.array([[0., 0., 0.]])
        joints, weights = np.zeros((1, 4), dtype=int), np.array([[1., 0., 0., 0.]])
        labels = [f"unit | {clip}" for clip in ("g02_idle", "g00_move", "g12_attack_front", "g15_shoot_front", "g05_death") for _ in range(4)]
        motion = {"rotations": np.tile(np.eye(3), (20, 1, 1, 1)), "offsets": np.zeros((20, 1, 3))}
        with patch.object(Image.Image, "save") as save, patch.dict(sys.modules, {"exp_tpose": renderer}):
            out = Path("unused-review-output")
            pipeline.render_preview(out, {"normals": points, "indices": np.array([], dtype=int)}, points, points, [None], ["root"], joints, weights, motion, labels, reel=False)
            saved = [call.args[0].name for call in save.call_args_list]
            self.assertEqual(saved, ["rest_overlay.png", "first_frame.png", "keyframes.png"])
            self.assertEqual(len(calls), 8)  # Two rest views, first frame, five clip middles.

    def test_content_crop_is_stable_across_frames(self):
        first = Image.new("RGB", (20, 20), (0, 0, 0))
        second = Image.new("RGB", (20, 20), (0, 0, 0))
        first.putpixel((4, 5), (255, 255, 255))
        second.putpixel((12, 15), (255, 255, 255))
        self.assertEqual(pipeline._content_crop([first, second], padding=1), (3, 4, 14, 17))

    def test_unknown_selection_does_not_silently_run_nothing(self):
        with patch.object(sys, "argv", ["pipeline", "--manifest", "jobs.json", "--units", "typo"]), \
             patch.object(Path, "read_text", return_value=json.dumps({"jobs": [{"unit": "archer"}]})), \
             patch.object(pipeline, "run_job") as run:
            with self.assertRaises(SystemExit) as error:
                pipeline.main()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()

    def test_manifest_paths_resolve_from_repo_not_caller(self):
        job = {"unit": "archer", "mesh": "example/mesh.glb", "runDir": "example/run", "sourceReport": "example/source.json", "out": "example/out"}
        with patch.object(sys, "argv", ["pipeline", "--manifest", "jobs.json", "--review"]), \
             patch.object(Path, "read_text", return_value=json.dumps({"jobs": [job]})), \
             patch.object(pipeline, "run_job", return_value={"status": "experimental_candidate"}) as run:
            self.assertEqual(pipeline.main(), 0)
            self.assertEqual(run.call_args.args[0]["mesh"], str(pipeline.ROOT / job["mesh"]))
            self.assertEqual(run.call_args.kwargs, {"preview": False, "review": True, "preview_scale": 1})

    def test_skin_consumes_full_rotation_and_translation(self):
        values = np.array([[1., 0., 0.]])
        rotation = np.array([[[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]]])
        joints, weights = np.zeros((1, 4), dtype=int), np.array([[1., 0., 0., 0.]])
        actual = pipeline.skin(values, joints, weights, rotation, np.array([[2., 3., 0.]]))
        np.testing.assert_allclose(actual, [[2., 4., 0.]])
        np.testing.assert_allclose(pipeline.skin(values, joints, weights, rotation), [[0., 1., 0.]])

    def test_batch_continues_after_expected_fit_error(self):
        jobs = [{"unit": "first"}, {"unit": "second"}]
        with patch.object(sys, "argv", ["pipeline", "--manifest", "not-read.json"]), \
             patch.object(Path, "read_text", return_value=json.dumps({"jobs": jobs})), \
             patch.object(pipeline, "run_job", side_effect=[ValueError("fit unavailable"), {"status": "experimental_candidate"}]) as run:
            self.assertEqual(pipeline.main(), 1)
            self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
