import unittest
from unittest.mock import patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from capture_skin_corpus import validate_manifest


class CaptureSkinCorpusManifestTests(unittest.TestCase):
    def setUp(self):
        self.idle = (Path.cwd() / "virtual_corpus/idle.png").resolve()
        self.frame = (Path.cwd() / "virtual_corpus/frame.png").resolve()
        files = {self.idle, self.frame}
        exists = patch.object(Path, "is_file", autospec=True, side_effect=lambda path: path in files)
        exists.start()
        self.addCleanup(exists.stop)

    def _manifest(self, clip):
        class FakeImage:
            size = (64, 64)
            def __enter__(self): return self
            def __exit__(self, *args): pass
        return patch("PIL.Image.open", return_value=FakeImage()), {"unit": "h3_roc", "idle": str(self.idle), "clips": [clip]}

    def test_valid_manifest_preserves_authored_order(self):
        patcher, manifest = self._manifest({"key": "attack", "frames": [str(self.frame), str(self.frame)], "contextBefore": [str(self.idle)], "contextAfter": []})
        with patcher:
            value = validate_manifest(manifest)
        self.assertEqual(value["clips"][0]["frames"][0], str(self.frame))

    def test_valid_manifest_accepts_other_homm3_units(self):
        patcher, manifest = self._manifest({"key": "idle", "frames": [str(self.frame)], "contextBefore": [str(self.idle)], "contextAfter": []})
        manifest["unit"] = "h3_behemoth"
        with patcher:
            value = validate_manifest(manifest)
        self.assertEqual(value["unit"], "h3_behemoth")

    def test_rejects_non_homm3_unit_ids(self):
        patcher, manifest = self._manifest({"key": "idle", "frames": [str(self.frame)], "contextBefore": [str(self.idle)], "contextAfter": []})
        manifest["unit"] = "behemoth"
        with patcher, self.assertRaises(ValueError):
            validate_manifest(manifest)

    def test_rejects_relative_or_missing_inputs(self):
        with self.assertRaises(ValueError):
            validate_manifest({"unit": "h3_roc", "idle": "idle.png", "clips": []})
        patcher, manifest = self._manifest({"key": "x", "frames": [str(self.idle.with_name("missing.png"))], "contextBefore": [str(self.idle)], "contextAfter": []})
        with patcher, self.assertRaises(ValueError):
            validate_manifest(manifest)

    def test_rejects_duplicate_keys_and_unsafe_keys(self):
        clip = {"key": "x", "frames": [str(self.frame)], "contextBefore": [str(self.idle)], "contextAfter": []}
        patcher, manifest = self._manifest(clip)
        manifest["clips"].append(clip)
        with patcher, self.assertRaises(ValueError):
            validate_manifest(manifest)

    def test_rejects_mixed_canvas_sizes(self):
        class FakeImage:
            def __init__(self, size): self.size = size
            def __enter__(self): return self
            def __exit__(self, *args): pass
        def open_image(path):
            return FakeImage((32, 32) if Path(path) == self.frame else (64, 64))
        clip = {"key": "mixed", "frames": [str(self.frame)], "contextBefore": [str(self.idle)], "contextAfter": []}
        with patch("PIL.Image.open", side_effect=open_image), self.assertRaises(ValueError):
            validate_manifest({"unit": "h3_roc", "idle": str(self.idle), "clips": [clip]})
        patcher, manifest = self._manifest({"key": "../escape", "frames": [str(self.frame)], "contextBefore": [str(self.idle)], "contextAfter": []})
        with patcher, self.assertRaises(ValueError):
            validate_manifest(manifest)


if __name__ == "__main__":
    unittest.main()
