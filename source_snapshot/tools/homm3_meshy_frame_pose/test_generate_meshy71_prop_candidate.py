"""The standalone prop generator must persist its task before any polling can resume."""
from __future__ import annotations

import json
import sys
import shutil
import uuid
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_meshy71_prop_candidate as generator  # noqa: E402


class PropCandidateGeneratorTests(unittest.TestCase):
    def test_start_creates_task_parent_and_records_policy(self) -> None:
        root = generator.ROOT / "build/test-temp" / ("prop-candidate-" + uuid.uuid4().hex)
        root.mkdir(parents=True, exist_ok=False)
        try:
            source = root / "reference.png"
            Image.new("RGB", (8, 8), (12, 24, 36)).save(source)
            out = root / "candidate"
            args = Namespace(unit="toa_ogre_brute", prop="club", input=source, out=out, polycount=8000)
            with patch.object(generator, "load_api_key", return_value="key"), \
                 patch.object(generator, "create_image_to_3d", return_value="task-1"):
                self.assertEqual(generator.start(args), 0)
            record = json.loads((out / "tasks/image_to_3d.json").read_text(encoding="utf-8"))
            self.assertEqual(record["taskId"], "task-1")
            self.assertEqual(record["policy"]["prop"], "club")
            self.assertTrue((out / "input.png").is_file())
        finally:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
