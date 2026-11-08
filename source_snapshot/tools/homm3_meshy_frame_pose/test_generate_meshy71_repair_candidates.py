"""Isolated candidate/resume tests. All Meshy operations are mocked; no paid calls."""
from argparse import Namespace
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_meshy71_repair_candidates as generator


class RepairCandidateTests(unittest.TestCase):
    def setUp(self):
        self.root = generator.ROOT / "build/test-temp" / ("repair-candidate-" + uuid.uuid4().hex)
        self.root.mkdir(parents=True, exist_ok=False)
        self.addCleanup(shutil.rmtree, self.root)
        self.stack = self.enterContext(ExitStack())
        self.enterContext(redirect_stdout(io.StringIO()))
        self.source = self.root / "prepared.png"
        self.source.write_bytes(b"mock prepared image")
        self.catalog_image = self.root / "catalog.png"
        self.catalog_image.write_bytes(b"mock original catalog image")
        self.coverage = self.root / "coverage.json"
        self.coverage.write_text(json.dumps({"records": [
            {"unitSid": "h3_hobgoblin", "imageInput": str(self.catalog_image)}]}))
        self.out = self.root / "outputs"
        self.stack.enter_context(patch.object(generator, "OUT_ROOT", self.out))
        self.stack.enter_context(patch.object(generator, "COVERAGE", self.coverage))
        self.key = self.stack.enter_context(patch.object(generator, "load_api_key", return_value="mock-key"))
        self.create = self.stack.enter_context(patch.object(generator, "create_image_to_3d", return_value="task-123"))
        self.poll = self.stack.enter_context(patch.object(generator, "poll_task", return_value={"status": "RUNNING"}))
        self.download = self.stack.enter_context(patch.object(generator, "download_url", side_effect=self.fake_download))
        self.args = Namespace(unit="h3_hobgoblin", variant="t-pose", source_image=self.source,
                              attempt="empty-hands-v1", polycount=8000, timeout_s=10)
        self.dest = self.out / self.args.unit / self.args.variant / self.args.attempt

    @staticmethod
    def fake_download(url, dest):
        dest.write_bytes(b"mock mesh data" * 200)
        return dest

    def read(self, name, dest=None):
        return json.loads(((dest or self.dest) / name).read_text())

    def test_prepared_attempt_retains_exact_source_hash_and_settings_before_submission(self):
        def submit(*args, **kwargs):
            record = self.read("tasks/image_to_3d.json")
            self.assertEqual(record["status"], "SUBMITTING")
            self.assertEqual((self.dest / "source.png").read_bytes(), self.source.read_bytes())
            self.assertEqual(record["policy"]["sourceImageSha256"], hashlib.sha256(self.source.read_bytes()).hexdigest())
            return "task-123"
        self.create.side_effect = submit
        self.coverage.unlink()  # The explicit prepared lane must not select a catalog image.
        self.assertEqual(generator.start(self.args), 0)
        saved = self.read("tasks/image_to_3d.json")
        self.assertEqual(saved["taskId"], "task-123")
        self.assertEqual(saved["policy"]["attempt"], "empty-hands-v1")
        self.assertEqual(saved["policy"]["textureResolution"], "2k")
        self.assertEqual(saved["policy"], self.read("candidate_meta.json")["policy"])
        self.create.assert_called_once_with("mock-key", image_path=self.dest / "source.png",
            should_texture=True, target_polycount=8000, model_type="standard", ai_model="latest",
            should_remesh=True, enable_pbr=True, texture_resolution="2k", image_enhancement=False, pose_mode="t-pose")
        self.assertFalse((self.dest.parent / "tasks").exists())

    def test_default_selection_path_uses_generation_integrated_target(self):
        args = deepcopy(self.args); args.source_image = args.attempt = None; args.variant = "source"
        dest = self.out / args.unit / "source"
        generator.start(args)
        self.assertEqual((dest / "source.png").read_bytes(), self.catalog_image.read_bytes())
        self.assertNotIn("attempt", self.read("tasks/image_to_3d.json", dest)["policy"])
        self.assertEqual(self.create.call_args.kwargs["ai_model"], "latest")
        self.assertTrue(self.create.call_args.kwargs["should_remesh"])
        self.assertEqual(self.create.call_args.kwargs["target_polycount"], 8000)
        self.assertIsNone(self.create.call_args.kwargs["pose_mode"])

    def test_generation_integrated_remesh_is_default_and_candidate_dir_isolated(self):
        args = deepcopy(self.args)
        args.candidate_dir = self.out / args.unit / "full-invocation" / "generation"
        generator.start(args)
        policy = self.read("tasks/image_to_3d.json", args.candidate_dir)["policy"]
        self.assertTrue(policy["shouldRemesh"])
        self.assertTrue(self.create.call_args.kwargs["should_remesh"])
        self.assertEqual(self.create.call_args.kwargs["target_polycount"], 8000)

    def test_prepared_jpeg_copy_preserves_extension_and_bytes(self):
        image = self.source.with_suffix(".jpg"); image.write_bytes(b"mock jpeg bytes")
        self.args.source_image = image
        generator.start(self.args)
        self.assertEqual(self.create.call_args.kwargs["image_path"], self.dest / "source.jpg")
        self.assertEqual((self.dest / "source.jpg").read_bytes(), image.read_bytes())

    def test_pair_required_for_every_command_and_cli(self):
        for handler in (generator.start, generator.poll, generator.generate):
            for key in ("source_image", "attempt"):
                args = deepcopy(self.args); setattr(args, key, None)
                with self.subTest(command=handler.__name__, missing=key), self.assertRaisesRegex(SystemExit, "together"):
                    handler(args)
        for extra in (["--source-image", str(self.source)], ["--attempt", "v1"]):
            with patch.object(sys, "argv", ["generator", "start", "--unit", "h3_hobgoblin", "--variant", "t-pose", *extra]), \
                 patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SystemExit):
                generator.main()
        self.create.assert_not_called(); self.poll.assert_not_called(); self.key.assert_not_called()

    def test_unsafe_reserved_and_escaping_names_rejected_before_io(self):
        names = ["", ".", "..", "../outside", "a/b", "a\\b", "V:/outside", "a:stream", "v1.",
                 "v1 ", ".hidden", "CON", "nul", "PrN", "aux", "COM1", "lpt9", "tasks", "a" * 65]
        for name in names:
            args = deepcopy(self.args); args.attempt = name
            with self.subTest(name=name), self.assertRaisesRegex(SystemExit, "unsafe|reserved"):
                generator.start(args)
        args = deepcopy(self.args); args.unit = "../outside"
        with self.assertRaisesRegex(SystemExit, "unsafe"):
            generator.start(args)
        # Simulate a pre-existing junction resolving the otherwise safe attempt outside OUT_ROOT.
        original = Path.resolve
        for target in (self.root / "outside", self.dest.parent):
            with self.subTest(target=target), \
                 patch.object(Path, "resolve", lambda p, *a, **kw: target if p == self.dest else original(p, *a, **kw)), \
                 self.assertRaisesRegex(SystemExit, "escapes"):
                generator.start(self.args)
        self.assertFalse(self.out.exists())
        self.create.assert_not_called(); self.key.assert_not_called()

    def test_start_reuses_same_id_without_rewriting_input_or_records(self):
        generator.start(self.args)
        paths = [self.dest / "source.png", self.dest / "tasks/image_to_3d.json", self.dest / "candidate_meta.json"]
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths]
        generator.start(self.args)
        self.assertEqual(before, [(p.read_bytes(), p.stat().st_mtime_ns) for p in paths])
        self.assertEqual(self.create.call_count, 1)

    def test_cli_attempts_are_isolated_and_preserve_historical_records(self):
        historical = self.dest.parent
        (historical / "tasks").mkdir(parents=True)
        sentinel = historical / "tasks/image_to_3d.json"
        sentinel.write_bytes(b"historical task record stays untouched")
        for attempt in ("empty-hands-v1", "empty-hands-v2"):
            with patch.object(sys, "argv", ["generator", "start", "--unit", self.args.unit,
                    "--variant", "t-pose", "--source-image", str(self.source), "--attempt", attempt]):
                self.assertEqual(generator.main(), 0)
            self.assertEqual(self.read("tasks/image_to_3d.json", historical / attempt)["policy"]["attempt"], attempt)
        self.assertEqual(sentinel.read_bytes(), b"historical task record stays untouched")
        self.assertEqual(self.create.call_count, 2)

    def test_changed_source_settings_or_retained_copy_rejected_on_all_resume_paths(self):
        generator.start(self.args)
        original_source = self.source.read_bytes()
        original_copy = (self.dest / "source.png").read_bytes()
        for change in ("source", "copy", "polycount", "source-path"):
            args = deepcopy(self.args)
            if change == "source":
                self.source.write_bytes(b"changed input")
            elif change == "copy":
                (self.dest / "source.png").write_bytes(b"changed copy")
            elif change == "polycount":
                args.polycount = 12000
            else:
                args.source_image = self.root / "other.png"; args.source_image.write_bytes(original_source)
            for handler in (generator.start, generator.poll, generator.generate):
                with self.subTest(change=change, command=handler.__name__), self.assertRaisesRegex(SystemExit, "mismatch|changed"):
                    handler(args)
            self.source.write_bytes(original_source)
            (self.dest / "source.png").write_bytes(original_copy)
        self.assertEqual(self.create.call_count, 1)
        self.poll.assert_not_called()

    def test_poll_persists_id_and_original_policy_even_when_response_omits_them(self):
        generator.start(self.args)
        original = self.read("tasks/image_to_3d.json")["policy"]
        self.assertEqual(generator.poll(self.args), 2)
        self.assertEqual(generator.poll(self.args), 2)
        self.assertEqual(self.read("tasks/image_to_3d.json")["taskId"], "task-123")
        self.assertEqual(self.read("tasks/image_to_3d.json")["policy"], original)
        self.assertEqual(self.read("candidate_meta.json")["policy"], original)
        self.assertEqual(self.create.call_count, 1)
        for call in self.poll.call_args_list:
            self.assertEqual(call.args, ("mock-key", "image-to-3d", "task-123"))

    def test_timeout_resumes_existing_id_without_resubmission(self):
        generator.start(self.args)
        before = (self.dest / "tasks/image_to_3d.json").read_bytes()
        self.poll.side_effect = TimeoutError("mock timeout")
        with self.assertRaises(TimeoutError):
            generator.poll(self.args)
        self.assertEqual((self.dest / "tasks/image_to_3d.json").read_bytes(), before)
        self.poll.side_effect = None
        generator.generate(self.args)
        self.assertEqual(self.create.call_count, 1)
        self.assertEqual(self.poll.call_count, 2)

    def test_interrupted_record_replace_keeps_previous_id_for_resume(self):
        generator.start(self.args)
        path = self.dest / "tasks/image_to_3d.json"
        before = path.read_bytes()
        with patch.object(generator.os, "replace", side_effect=OSError("mock interrupted replace")), \
             self.assertRaises(OSError):
            generator.poll(self.args)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(list(path.parent.glob("*.tmp")), [])
        generator.poll(self.args)
        self.assertEqual(self.create.call_count, 1)
        self.assertEqual(self.poll.call_args.args[2], "task-123")

    def test_uncertain_submission_never_reposts(self):
        self.create.side_effect = TimeoutError("POST result unknown")
        with self.assertRaises(TimeoutError):
            generator.start(self.args)
        self.assertEqual(self.read("tasks/image_to_3d.json")["status"], "SUBMITTING")
        for handler in (generator.start, generator.poll, generator.generate):
            with self.subTest(command=handler.__name__), self.assertRaisesRegex(SystemExit, "submission uncertain"):
                handler(self.args)
        self.assertEqual(self.create.call_count, 1)
        self.poll.assert_not_called()

    def test_legacy_raw_task_response_uses_original_meta_policy_verbatim(self):
        args = deepcopy(self.args); args.source_image = args.attempt = None
        dest = self.out / args.unit / args.variant
        (dest / "tasks").mkdir(parents=True)
        (dest / "source.png").write_bytes(self.catalog_image.read_bytes())
        # Literal settings from the prior helper contract: pinned Meshy 7.1 and no
        # generation-integrated remesh. Poll must preserve these without resubmitting.
        policy = {
            "schema": generator.SCHEMA,
            "unitSid": args.unit,
            "variant": args.variant,
            "sourceImage": str(self.catalog_image.resolve()).replace("\\", "/"),
            "aiModel": "meshy-7.1",
            "modelType": "standard",
            "targetPolycount": 8000,
            "shouldTexture": True,
            "enablePbr": True,
            "shouldRemesh": False,
            "imageEnhancement": False,
            "poseMode": "t-pose",
            "autoRig": False,
            "armatureAuthority": "owned_in_repo_after_candidate_audit",
            "proof": "generated candidate only",
            "sourceImageSha256": hashlib.sha256(self.catalog_image.read_bytes()).hexdigest(),
            "textureResolution": "2k",
        }
        (dest / "tasks/image_to_3d.json").write_text(json.dumps({"id": "historical-id", "status": "RUNNING"}))
        (dest / "candidate_meta.json").write_text(json.dumps({"taskId": "historical-id", "policy": policy}))
        before = (dest / "candidate_meta.json").read_bytes()
        generator.start(args)
        self.assertEqual((dest / "candidate_meta.json").read_bytes(), before)
        generator.poll(args)
        self.assertEqual(self.read("candidate_meta.json", dest)["policy"], policy)
        self.assertEqual(self.poll.call_args.args[2], "historical-id")
        self.create.assert_not_called()

    def test_missing_conflicting_corrupt_records_do_not_submit_or_poll(self):
        with self.assertRaisesRegex(SystemExit, "no queued task"):
            generator.poll(self.args)
        self.assertFalse(self.out.exists())
        generator.start(self.args)
        task_path = self.dest / "tasks/image_to_3d.json"
        meta_path = self.dest / "candidate_meta.json"
        task, meta = task_path.read_bytes(), meta_path.read_bytes()
        for change in ("corrupt", "missing-policy", "conflicting-policy", "conflicting-id", "missing-task"):
            if change == "corrupt":
                task_path.write_text("{")
            elif change == "missing-policy":
                task_path.write_text('{"taskId":"task-123"}'); meta_path.unlink()
            elif change == "conflicting-policy":
                edited = json.loads(meta); edited["policy"]["targetPolycount"] = 1
                meta_path.write_text(json.dumps(edited))
            elif change == "conflicting-id":
                edited = json.loads(meta); edited["taskId"] = "other"
                meta_path.write_text(json.dumps(edited))
            else:
                task_path.unlink()
            with self.subTest(change=change), self.assertRaises(SystemExit):
                generator.start(self.args)
            task_path.write_bytes(task); meta_path.write_bytes(meta)
        self.assertEqual(self.create.call_count, 1)
        self.poll.assert_not_called()

    def test_success_retains_mesh_hash_and_generate_cache_still_validates_inputs(self):
        self.poll.return_value = {"id": "task-123", "status": "SUCCEEDED", "model_urls": {"glb": "mock://mesh"}}
        generator.generate(self.args)
        meta = self.read("candidate_meta.json")
        self.assertEqual(meta["meshSha256"], hashlib.sha256((self.dest / "mesh.glb").read_bytes()).hexdigest())
        generator.generate(self.args)
        self.assertEqual(self.create.call_count, 1); self.assertEqual(self.poll.call_count, 1)
        self.args.polycount = 12345
        with self.assertRaisesRegex(SystemExit, "mismatch"):
            generator.generate(self.args)
        self.assertEqual(self.read("candidate_meta.json"), meta)

    def test_response_wrong_id_and_success_without_glb_reject(self):
        generator.start(self.args)
        original = (self.dest / "tasks/image_to_3d.json").read_bytes()
        self.poll.return_value = {"id": "wrong-task", "status": "SUCCEEDED"}
        with self.assertRaisesRegex(SystemExit, "ID mismatch"):
            generator.poll(self.args)
        self.assertEqual((self.dest / "tasks/image_to_3d.json").read_bytes(), original)
        self.poll.return_value = {"id": "task-123", "status": "SUCCEEDED"}
        with self.assertRaisesRegex(SystemExit, "no GLB"):
            generator.poll(self.args)
        self.download.assert_not_called()


if __name__ == "__main__":
    unittest.main()
