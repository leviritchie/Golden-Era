"""Focused checks for the game-only launch-guard CLI path."""

import contextlib
import io
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.homm3_def_retarget import launch_guard


class LaunchGuardGameProbeTests(unittest.TestCase):
    def invoke_game_only(self, *, result=None, side_effect=None):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with mock.patch.object(launch_guard.subprocess, "run", return_value=result,
                               side_effect=side_effect) as process_query, \
             mock.patch.object(launch_guard, "check") as full_check, \
             mock.patch.object(launch_guard.shutil, "disk_usage") as disk_check, \
             mock.patch.object(launch_guard.memgate, "check") as resource_check, \
             contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = launch_guard.main(["--game-only"])

        full_check.assert_not_called()
        disk_check.assert_not_called()
        resource_check.assert_not_called()
        process_query.assert_called_once()
        return code, stdout.getvalue(), stderr.getvalue(), process_query

    def test_running_game_refuses(self):
        code, stdout, stderr, query = self.invoke_game_only(
            result=subprocess.CompletedProcess([], 0, "RUNNING\n", ""),
        )

        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertIn("LAUNCH_GUARD REFUSED HeroesOldenEra is running", stderr)
        self.assertEqual(15, query.call_args.kwargs["timeout"])

    def test_absent_game_passes(self):
        code, stdout, stderr, query = self.invoke_game_only(
            result=subprocess.CompletedProcess([], 0, "ABSENT\n", ""),
        )

        self.assertEqual(0, code)
        self.assertIn("LAUNCH_GUARD OK HeroesOldenEra is absent", stdout)
        self.assertEqual("", stderr)
        self.assertEqual(15, query.call_args.kwargs["timeout"])

    def test_malformed_and_nonzero_probe_results_refuse(self):
        results = (
            subprocess.CompletedProcess([], 0, "UNKNOWN\n", ""),
            subprocess.CompletedProcess([], 1, "ABSENT\n", "access denied"),
        )
        for result in results:
            with self.subTest(result=result):
                code, stdout, stderr, _ = self.invoke_game_only(result=result)
                self.assertEqual(1, code)
                self.assertEqual("", stdout)
                self.assertIn("LAUNCH_GUARD REFUSED game process query failed", stderr)

    def test_timeout_refuses(self):
        code, stdout, stderr, _ = self.invoke_game_only(
            side_effect=subprocess.TimeoutExpired("powershell", 15),
        )

        self.assertEqual(1, code)
        self.assertEqual("", stdout)
        self.assertIn("LAUNCH_GUARD REFUSED game process query unavailable", stderr)


if __name__ == "__main__":
    unittest.main()
