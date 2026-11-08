#!/usr/bin/env python3
"""Unit tests for Core.zip process cache used by raw_translation emit."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))

import core_zip_cache  # noqa: E402


class CoreZipCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        core_zip_cache.clear_core_zip_cache()

    def tearDown(self) -> None:
        core_zip_cache.clear_core_zip_cache()

    def test_read_json_and_map_objects_cached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            zip_path = Path(tmp) / "Core.zip"
            member = "DB/map/objects/test_objects.json"
            payload = {"array": [{"id": "rocks_1", "sizeX": 1, "sizeZ": 1, "nodes": [1]}]}
            with zipfile.ZipFile(zip_path, "w") as zf:
                zf.writestr(member, json.dumps(payload))
                zf.writestr("Lang/english/texts/dialogues.json", json.dumps({"tokens": []}))

            first = core_zip_cache.read_core_json(zip_path, member)
            second = core_zip_cache.read_core_json(zip_path, member)
            self.assertIs(first, second)

            configs = core_zip_cache.map_object_configs_by_id(zip_path)
            self.assertEqual(configs["rocks_1"]["id"], "rocks_1")
            again = core_zip_cache.map_object_configs_by_id(zip_path)
            self.assertIs(configs, again)


if __name__ == "__main__":
    unittest.main()
