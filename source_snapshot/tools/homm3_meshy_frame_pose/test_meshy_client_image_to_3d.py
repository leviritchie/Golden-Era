#!/usr/bin/env python3
"""Request-body contracts for image-to-3d (no network)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from PIL import Image

TOOL = Path(__file__).resolve().parent
if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))
import meshy_client  # noqa: E402


class ImageTo3dRequestTests(unittest.TestCase):
    def _png(self, folder: Path) -> Path:
        path = folder / "plate.png"
        Image.new("RGBA", (8, 8), (12, 24, 36, 255)).save(path)
        return path

    def test_adaptive_medium_omits_target_polycount(self) -> None:
        captured: dict = {}

        def fake_request(method, path, api_key, body=None, timeout=120.0):
            captured["method"] = method
            captured["path"] = path
            captured["body"] = body
            return {"result": "task-1"}

        with TemporaryDirectory() as raw:
            png = self._png(Path(raw))
            with patch.object(meshy_client, "_request", fake_request):
                tid = meshy_client.create_image_to_3d(
                    "k",
                    image_path=png,
                    should_texture=True,
                    target_polycount=None,
                    model_type="standard",
                    ai_model="meshy-7",
                    should_remesh=True,
                    enable_pbr=True,
                    remove_lighting=False,
                    texture_resolution="4k",
                    decimation_mode=3,
                    image_enhancement=False,
                )
        self.assertEqual(tid, "task-1")
        body = captured["body"]
        self.assertEqual(captured["path"], "/image-to-3d")
        self.assertNotIn("target_polycount", body)
        self.assertEqual(body["ai_model"], "meshy-7")
        self.assertEqual(body["model_type"], "standard")
        self.assertEqual(body["decimation_mode"], 3)
        self.assertTrue(body["should_remesh"])
        self.assertFalse(body["remove_lighting"])
        self.assertFalse(body["image_enhancement"])
        self.assertEqual(body["texture_resolution"], "4k")

    def test_t2_still_sends_target_polycount(self) -> None:
        captured: dict = {}

        def fake_request(method, path, api_key, body=None, timeout=120.0):
            captured["body"] = body
            return {"result": "task-2"}

        with TemporaryDirectory() as raw:
            png = self._png(Path(raw))
            with patch.object(meshy_client, "_request", fake_request):
                meshy_client.create_image_to_3d(
                    "k",
                    image_path=png,
                    should_texture=False,
                    target_polycount=8000,
                    model_type="smart-topology",
                    ai_model="meshy-t2",
                    should_remesh=True,
                )
        body = captured["body"]
        self.assertEqual(body["target_polycount"], 8000)
        self.assertNotIn("decimation_mode", body)
        self.assertEqual(body["ai_model"], "meshy-t2")

    def test_meshy71_full_geometry_can_skip_generation_remesh(self) -> None:
        captured: dict = {}

        def fake_request(method, path, api_key, body=None, timeout=120.0):
            captured["body"] = body
            return {"result": "task-3"}

        with TemporaryDirectory() as raw:
            png = self._png(Path(raw))
            with patch.object(meshy_client, "_request", fake_request):
                tid = meshy_client.create_image_to_3d(
                    "k",
                    image_path=png,
                    should_texture=True,
                    target_polycount=None,
                    model_type="standard",
                    ai_model="meshy-7.1",
                    should_remesh=False,
                    enable_pbr=True,
                    texture_resolution="4k",
                    geometry_resolution="4k",
                    pose_mode="t-pose",
                    image_enhancement=False,
                )

        self.assertEqual(tid, "task-3")
        body = captured["body"]
        self.assertEqual(body["geometry_resolution"], "4k")
        self.assertEqual(body["ai_model"], "meshy-7.1")
        self.assertFalse(body["should_remesh"])
        self.assertNotIn("target_polycount", body)


if __name__ == "__main__":
    unittest.main()
