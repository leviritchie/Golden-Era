import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bind_meshy71_candidate as bind


class BindPoseTests(unittest.TestCase):
    def test_explicit_registration_is_used_without_fallback(self):
        sentinel = object()
        with patch.object(Path, "is_file", return_value=True), patch.object(
            bind, "load_registered_pose_source", return_value=sentinel
        ) as loader:
            pose = bind.load_pose(Path("run"), "g02_idle", Path("candidate/registration.json"))
        self.assertIs(pose, sentinel)
        self.assertEqual(loader.call_args.kwargs["registration"], Path("candidate/registration.json").resolve())


if __name__ == "__main__":
    unittest.main()
