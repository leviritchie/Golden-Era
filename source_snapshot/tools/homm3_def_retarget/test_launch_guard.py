"""Focused checks for the shared pre-Blender launch guard."""

import subprocess
import sys
import unittest
from unittest import mock

from tools.homm3_def_retarget import launch_guard


class LaunchGuardTests(unittest.TestCase):
    def test_exact_game_query_requires_valid_result(self):
        for answer, expected in (("ABSENT\n", False), ("RUNNING\n", True)):
            with self.subTest(answer=answer), mock.patch.object(
                launch_guard.subprocess, "run",
                return_value=subprocess.CompletedProcess([], 0, answer, ""),
            ):
                self.assertEqual(expected, launch_guard.game_running())
        for result in (
            subprocess.CompletedProcess([], 2, "", "access denied"),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "UNKNOWN", ""),
        ):
            with self.subTest(result=result), mock.patch.object(launch_guard.subprocess, "run", return_value=result):
                with self.assertRaises(launch_guard.LaunchRefused):
                    launch_guard.game_running()

    def test_resources_and_final_game_recheck(self):
        with mock.patch.object(launch_guard, "game_running", side_effect=[False, False]) as game, \
             mock.patch.object(launch_guard.shutil, "disk_usage", return_value=mock.Mock(free=40 * 1024 ** 3)), \
             mock.patch.object(launch_guard.memgate, "check", return_value=(True, 6.0, 4.0)):
            self.assertEqual((40.0, 6.0, 4.0), launch_guard.check())
        self.assertEqual(2, game.call_count)

    def test_game_disk_and_probe_fail_closed(self):
        with mock.patch.object(launch_guard, "game_running", return_value=True), \
             mock.patch.object(launch_guard.memgate, "check") as probe:
            with self.assertRaisesRegex(launch_guard.LaunchRefused, "HeroesOldenEra is running"):
                launch_guard.check()
            probe.assert_not_called()
        with mock.patch.object(launch_guard, "game_running", return_value=False), \
             mock.patch.object(launch_guard.shutil, "disk_usage", return_value=mock.Mock(free=19 * 1024 ** 3)):
            with self.assertRaisesRegex(launch_guard.LaunchRefused, "V: has"):
                launch_guard.check()
        with mock.patch.object(launch_guard, "game_running", return_value=False), \
             mock.patch.object(launch_guard.shutil, "disk_usage", return_value=mock.Mock(free=40 * 1024 ** 3)), \
             mock.patch.object(launch_guard.memgate, "check", side_effect=launch_guard.memgate.ProbeError("no GPU")):
            with self.assertRaisesRegex(launch_guard.LaunchRefused, "memgate probe failed"):
                launch_guard.check()
        with mock.patch.object(launch_guard, "game_running", side_effect=[False, True]), \
             mock.patch.object(launch_guard.shutil, "disk_usage", return_value=mock.Mock(free=40 * 1024 ** 3)), \
             mock.patch.object(launch_guard.memgate, "check", return_value=(True, 6.0, 4.0)):
            with self.assertRaisesRegex(launch_guard.LaunchRefused, "started during resource check"):
                launch_guard.check()

    def test_blender_child_env_is_child_only(self):
        env = launch_guard.blender_env({"PATH": "x"})
        self.assertEqual({"PATH": "x", "TBB_MALLOC_DISABLE_REPLACEMENT": "1"}, env)
        self.assertNotIn("TBB_MALLOC_DISABLE_REPLACEMENT", launch_guard.os.environ)

    def test_exec_runs_command_with_child_env_only_after_guard_passes(self):
        with mock.patch.object(launch_guard, "check", return_value=(40.0, 6.0, 4.0)), \
             mock.patch.object(launch_guard.subprocess, "run",
                               return_value=subprocess.CompletedProcess([], 7)) as run:
            self.assertEqual(7, launch_guard.main(["--exec", "--", "blender", "-b"]))
        self.assertEqual(["blender", "-b"], run.call_args.args[0])
        self.assertEqual("1", run.call_args.kwargs["env"]["TBB_MALLOC_DISABLE_REPLACEMENT"])
        with mock.patch.object(launch_guard, "check", side_effect=launch_guard.LaunchRefused("game")), \
             mock.patch.object(launch_guard.subprocess, "run") as run:
            self.assertEqual(1, launch_guard.main(["--exec", "--", "blender"]))
            run.assert_not_called()
        self.assertEqual(2, launch_guard.main(["--exec", "--"]))
        self.assertEqual(2, launch_guard.main(["--bogus"]))

    def test_import_leaves_callers_module_resolution_alone(self):
        # 65bc42533f regression: importing launch_guard put this folder (its Blender-only review.py) first on
        # sys.path, so look.py's `import review` loaded the wrong module and every look stage failed.
        root = launch_guard.ROOT
        code = (
            "import sys; sys.path.insert(0, sys.argv[1]); sys.path.append(sys.argv[2]); before = list(sys.path)\n"
            "import launch_guard\n"
            "assert sys.path == before, 'launch_guard changed sys.path'\n"
            "import importlib.util; print(importlib.util.find_spec('review').origin)\n"
        )
        out = subprocess.run([sys.executable, "-c", code, str(root / "tools/homm3_unit_look"),
                              str(root / "tools/homm3_def_retarget")],
                             capture_output=True, text=True, cwd=str(root))
        self.assertEqual(0, out.returncode, out.stderr)
        self.assertIn("homm3_unit_look", out.stdout.replace("\\", "/"))


if __name__ == "__main__":
    unittest.main()
