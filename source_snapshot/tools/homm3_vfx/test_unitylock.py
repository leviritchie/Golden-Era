"""Mocked process-probe and preflight-order tests for the legacy Unity wrapper."""
from __future__ import annotations

import contextlib
import ctypes
import io
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

import unitylock
from test_tempdir import workspace_tempdir


class UnityLockTests(unittest.TestCase):
    def test_pid_probe_maps_denied_and_gone_but_fails_unknown_api_errors(self):
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 0
        with mock.patch.object(unitylock.os, "name", "nt"), \
             mock.patch.object(unitylock.ctypes, "WinDLL", return_value=kernel, create=True), \
             mock.patch.object(unitylock.ctypes, "get_last_error", return_value=5, create=True):
            self.assertTrue(unitylock.pid_alive(4321))
        with mock.patch.object(unitylock.os, "name", "nt"), \
             mock.patch.object(unitylock.ctypes, "WinDLL", return_value=kernel, create=True), \
             mock.patch.object(unitylock.ctypes, "get_last_error", return_value=87, create=True):
            self.assertFalse(unitylock.pid_alive(4321))
        with mock.patch.object(unitylock.os, "name", "nt"), \
             mock.patch.object(unitylock.ctypes, "WinDLL", return_value=kernel, create=True), \
             mock.patch.object(unitylock.ctypes, "get_last_error", return_value=6, create=True):
            with self.assertRaisesRegex(unitylock.ProcessProbeError, "OpenProcess.*WinError 6"):
                unitylock.pid_alive(4321)

        kernel.OpenProcess.side_effect = OSError("fixture OpenProcess exception")
        with mock.patch.object(unitylock.os, "name", "nt"), \
             mock.patch.object(unitylock.ctypes, "WinDLL", return_value=kernel, create=True):
            with self.assertRaisesRegex(unitylock.ProcessProbeError, "OpenProcess.*fixture OpenProcess exception"):
                unitylock.pid_alive(4321)

        kernel.OpenProcess.return_value = 1
        kernel.OpenProcess.side_effect = None
        kernel.GetExitCodeProcess.return_value = 0
        for error in (5, 87, 6):
            with self.subTest(api="GetExitCodeProcess", error=error), \
                 mock.patch.object(unitylock.os, "name", "nt"), \
                 mock.patch.object(unitylock.ctypes, "WinDLL", return_value=kernel, create=True), \
                 mock.patch.object(unitylock.ctypes, "get_last_error", return_value=error, create=True):
                with self.assertRaisesRegex(unitylock.ProcessProbeError,
                                            f"GetExitCodeProcess.*WinError {error}"):
                    unitylock.pid_alive(4321)
        kernel.GetExitCodeProcess.side_effect = OSError("fixture native query exception")
        with mock.patch.object(unitylock.os, "name", "nt"), \
             mock.patch.object(unitylock.ctypes, "WinDLL", return_value=kernel, create=True):
            with self.assertRaisesRegex(unitylock.ProcessProbeError, "GetExitCodeProcess.*fixture native query"):
                unitylock.pid_alive(4321)

        with mock.patch.object(unitylock.os, "name", "nt"), \
             mock.patch.object(unitylock.ctypes, "WinDLL", create=True) as win_dll:
            with self.assertRaisesRegex(unitylock.ProcessProbeError, "DWORD range"):
                unitylock.pid_alive(0x100000000)
        win_dll.assert_not_called()

    def test_unknown_pid_probe_error_stops_acquire_without_sleep_or_lock_mutation(self):
        with workspace_tempdir(__file__) as root:
            lock = Path(root) / "unity.lock"
            lock.mkdir()
            owner = {"pid": 4321, "cmd": "fixture"}
            (lock / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
            output = io.StringIO()
            with mock.patch.object(unitylock, "LOCK", str(lock)), \
                 mock.patch.object(unitylock, "pid_alive", side_effect=unitylock.ProcessProbeError(
                     "GetExitCodeProcess failed for PID 4321: WinError 87")), \
                 mock.patch.object(unitylock.time, "sleep") as sleep, \
                 contextlib.redirect_stdout(output):
                self.assertFalse(unitylock.acquire(240, ["unused"]))
            sleep.assert_not_called()
            self.assertTrue(lock.is_dir())
            self.assertEqual(json.loads((lock / "owner.json").read_text(encoding="utf-8")), owner)
            self.assertIn("PID 4321", output.getvalue())
            self.assertIn("WinError 87", output.getvalue())

    def test_get_exit_code_87_failure_preserves_existing_unity_lock(self):
        with workspace_tempdir(__file__) as root:
            lock = Path(root) / "unity.lock"
            lock.mkdir()
            owner = {"pid": 4321, "cmd": "fixture"}
            owner_path = lock / "owner.json"
            owner_path.write_text(json.dumps(owner), encoding="utf-8")
            kernel = mock.Mock()
            kernel.OpenProcess.return_value = 1
            kernel.GetExitCodeProcess.return_value = 0
            kernel.CloseHandle.return_value = 1
            output = io.StringIO()
            with mock.patch.object(unitylock, "LOCK", str(lock)), \
                 mock.patch.object(unitylock.os, "name", "nt"), \
                 mock.patch.object(unitylock.ctypes, "WinDLL", return_value=kernel, create=True), \
                 mock.patch.object(unitylock.ctypes, "get_last_error", return_value=87, create=True), \
                 mock.patch.object(unitylock.time, "sleep") as sleep, \
                 contextlib.redirect_stdout(output):
                self.assertFalse(unitylock.acquire(240, ["unused"]))
            sleep.assert_not_called()
            self.assertTrue(lock.is_dir())
            self.assertEqual(json.loads(owner_path.read_text(encoding="utf-8")), owner)
            self.assertIn("GetExitCodeProcess", output.getvalue())
            self.assertIn("WinError 87", output.getvalue())

    def test_shared_advisory_guard_is_nonblocking_and_preserves_body_errors(self):
        with workspace_tempdir(__file__) as root:
            guard_path = Path(root) / "owner.guard"
            with unitylock.advisory_guard(guard_path) as first:
                self.assertTrue(first)
                with unitylock.advisory_guard(guard_path) as second:
                    self.assertFalse(second)
            with self.assertRaisesRegex(OSError, "body failure"):
                with unitylock.advisory_guard(guard_path) as acquired:
                    self.assertTrue(acquired)
                    raise OSError("body failure")
            with unitylock.advisory_guard(guard_path) as acquired_after_error:
                self.assertTrue(acquired_after_error)

    def test_shared_advisory_guard_serializes_other_processes(self):
        with workspace_tempdir(__file__) as root:
            guard_path = Path(root) / "cross-process.guard"
            code = "\n".join((
                "import sys, time",
                "sys.path.insert(0, sys.argv[2])",
                "from resource_lock_guard import advisory_guard",
                "with advisory_guard(sys.argv[1]) as locked:",
                "    print('held' if locked else 'busy', flush=True)",
                "    time.sleep(0.5)",
            ))
            with subprocess.Popen(
                [sys.executable, "-c", code, str(guard_path), str(Path(__file__).resolve().parents[1])],
                cwd=Path(__file__).resolve().parents[2], stdout=subprocess.PIPE, text=True,
            ) as proc:
                self.assertEqual("held", proc.stdout.readline().strip())
                with unitylock.advisory_guard(guard_path) as acquired:
                    self.assertFalse(acquired)
                self.assertEqual(0, proc.wait(timeout=3))

    def test_process_inventory_requires_a_valid_successful_cim_result(self):
        payload = '[{"ProcessId":123,"CommandLine":"Unity.exe -projectPath V:/project"}]'
        with mock.patch.object(unitylock.os, "name", "nt"), \
             mock.patch.object(unitylock.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, payload, "")):
            self.assertEqual([{"ProcessId": 123, "CommandLine": "Unity.exe -projectPath V:/project"}],
                             unitylock.list_unity_processes())
        bad = [
            subprocess.CompletedProcess([], 1, "[]", "access denied"),
            subprocess.CompletedProcess([], 0, "not-json", ""),
            subprocess.CompletedProcess([], 0, "null", ""),
            subprocess.CompletedProcess([], 0, '[{"CommandLine":"Unity"}]', ""),
        ]
        for result in bad:
            with self.subTest(result=result), \
                 mock.patch.object(unitylock.os, "name", "nt"), \
                 mock.patch.object(unitylock.subprocess, "run", return_value=result):
                with self.assertRaises(unitylock.ProcessProbeError):
                    unitylock.list_unity_processes()

    def test_unknown_command_line_is_treated_as_a_possible_target_editor(self):
        with mock.patch.object(unitylock, "list_unity_processes", return_value=[
            {"ProcessId": 123, "CommandLine": None},
        ]):
            self.assertTrue(unitylock.unity_running_on("runner -projectPath V:/project"))

    def test_project_paths_are_parsed_with_quotes_and_compared_exactly(self):
        with workspace_tempdir(__file__) as root:
            target = str(Path(root) / "Town")
            other = target + "ship"
            batch_flag = "-" + "batch" + "mode"
            command = f'Unity.exe -projectPath "{other}" {batch_flag}'
            self.assertEqual(other, unitylock.project_path_from_commandline(command))
            with mock.patch.object(unitylock, "list_unity_processes", return_value=[
                {"ProcessId": 123, "CommandLine": command},
            ]):
                self.assertFalse(unitylock.unity_running_on("runner", target))
                self.assertTrue(unitylock.unity_running_on("runner", other))

    def test_cim_failure_never_breaks_a_dead_owner_lock(self):
        with workspace_tempdir(__file__) as root:
            lock = Path(root) / "unity.lock"
            lock.mkdir()
            (lock / "owner.json").write_text(json.dumps({"pid": 123, "cmd": "unity -projectPath V:/project"}),
                                              encoding="utf-8")
            with mock.patch.object(unitylock, "LOCK", str(lock)), \
                 mock.patch.object(unitylock, "pid_alive", return_value=False), \
                 mock.patch.object(unitylock, "unity_running_on", side_effect=unitylock.ProcessProbeError("denied")), \
                 mock.patch.object(unitylock.time, "time", return_value=100.0), \
                 mock.patch.object(unitylock.time, "sleep"):
                self.assertFalse(unitylock.acquire(0, ["unused"]))
                self.assertTrue(lock.exists())

    def test_stale_reaper_refuses_a_replaced_lock_owner(self):
        original = {"pid": 123, "since": 1, "cmd": "old"}
        replacement = {"pid": 456, "since": 2, "cmd": "new"}
        with workspace_tempdir(__file__) as root, \
             mock.patch.object(unitylock, "holder", return_value=replacement), \
             mock.patch.object(unitylock, "pid_alive") as pid_alive, \
             mock.patch.object(unitylock.shutil, "rmtree") as rmtree:
            self.assertFalse(unitylock.remove_stale_lock(original, str(Path(root) / "unity.lock")))
        pid_alive.assert_not_called()
        rmtree.assert_not_called()

    def test_release_does_not_remove_a_replacement_owner(self):
        original = {"pid": os.getpid(), "since": 1, "cmd": "old"}
        replacement = {"pid": os.getpid(), "since": 2, "cmd": "new"}
        with workspace_tempdir(__file__) as root, \
             mock.patch.object(unitylock, "holder", side_effect=(original, replacement)), \
             mock.patch.object(unitylock.shutil, "rmtree") as rmtree:
            self.assertFalse(unitylock.release_owned_lock(lock_path=str(Path(root) / "unity.lock")))
        rmtree.assert_not_called()

    def test_owner_write_failure_removes_just_created_unity_lock(self):
        with workspace_tempdir(__file__) as root:
            lock = Path(root) / "unity.lock"
            with mock.patch.object(unitylock, "LOCK", str(lock)), \
                 mock.patch("builtins.open", side_effect=PermissionError("fixture owner write failure")):
                with self.assertRaisesRegex(PermissionError, "fixture owner write failure"):
                    unitylock.acquire(0, ["unused"])
            self.assertFalse(lock.exists())

    def test_corrupt_lock_metadata_fails_fast_and_preserves_lock(self):
        with workspace_tempdir(__file__) as root:
            lock = Path(root) / "unity.lock"
            lock.mkdir()
            (lock / "owner.json").write_text("{not-json", encoding="utf-8")
            output = io.StringIO()
            with mock.patch.object(unitylock, "LOCK", str(lock)), \
                 mock.patch.object(unitylock.time, "sleep") as sleep, \
                 contextlib.redirect_stdout(output):
                self.assertFalse(unitylock.acquire(240, ["unused"]))
            sleep.assert_not_called()
            self.assertTrue(lock.is_dir())
            self.assertIn(str(lock / "owner.json"), output.getvalue())
            self.assertIn("lock preserved", output.getvalue())

    def test_unreadable_lock_metadata_fails_fast_and_preserves_lock(self):
        with workspace_tempdir(__file__) as root:
            lock = Path(root) / "unity.lock"
            lock.mkdir()
            (lock / "owner.json").write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")
            output = io.StringIO()
            with mock.patch.object(unitylock, "LOCK", str(lock)), \
                 mock.patch("builtins.open", side_effect=PermissionError("fixture unreadable owner")), \
                 mock.patch.object(unitylock.time, "sleep") as sleep, \
                 contextlib.redirect_stdout(output):
                self.assertFalse(unitylock.acquire(240, ["unused"]))
            sleep.assert_not_called()
            self.assertTrue(lock.is_dir())
            self.assertIn("fixture unreadable owner", output.getvalue())

    def test_missing_owner_has_only_a_short_creation_grace(self):
        with workspace_tempdir(__file__) as root:
            lock = Path(root) / "unity.lock"
            lock.mkdir()
            output = io.StringIO()
            with mock.patch.object(unitylock, "LOCK", str(lock)), \
                 mock.patch.object(unitylock.time, "sleep") as sleep, \
                 contextlib.redirect_stdout(output):
                self.assertFalse(unitylock.acquire(0, ["unused"]))
                self.assertTrue(lock.is_dir())
                os.utime(lock, (1.0, 1.0))
                self.assertFalse(unitylock.acquire(240, ["unused"]))
            sleep.assert_not_called()
            self.assertIn("no owner.json", output.getvalue())
            self.assertIn(str(lock), output.getvalue())

    def test_status_distinguishes_pending_from_expired_owner_metadata(self):
        with workspace_tempdir(__file__) as root:
            lock = Path(root) / "unity.lock"
            lock.mkdir()
            output = io.StringIO()
            error = io.StringIO()
            with mock.patch.object(unitylock, "LOCK", str(lock)), \
                 contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                self.assertEqual(3, unitylock.main(["status"]))
                self.assertIn("owner metadata pending", output.getvalue())
                self.assertNotIn("UNITYLOCK free", output.getvalue())
                os.utime(lock, (1.0, 1.0))
                output.seek(0)
                output.truncate(0)
                self.assertEqual(5, unitylock.main(["status"]))
            self.assertIn("no owner.json", error.getvalue())
            self.assertIn(str(lock), error.getvalue())
            self.assertTrue(lock.is_dir())

    def test_second_stale_reaper_cannot_delete_replacement_lock(self):
        original = {"pid": 123, "since": 1, "cmd": "old"}
        replacement = {"pid": os.getpid(), "since": 2, "cmd": "new"}
        entered_delete = threading.Event()
        finish_delete = threading.Event()
        results = []

        with workspace_tempdir(__file__) as root:
            lock = Path(root) / "unity.lock"
            lock.mkdir()
            (lock / "owner.json").write_text(json.dumps(original), encoding="utf-8")
            real_rmtree = unitylock.shutil.rmtree

            def replace_during_delete(path, **kwargs):
                real_rmtree(path, **kwargs)
                Path(path).mkdir()
                (Path(path) / "owner.json").write_text(json.dumps(replacement), encoding="utf-8")
                entered_delete.set()
                if not finish_delete.wait(3):
                    raise RuntimeError("test did not release Unity lock reaper")

            with mock.patch.object(unitylock, "pid_alive", return_value=False), \
                 mock.patch.object(unitylock, "unity_running_on", return_value=False), \
                 mock.patch.object(unitylock.shutil, "rmtree", side_effect=replace_during_delete):
                first = threading.Thread(target=lambda: results.append(unitylock.remove_stale_lock(original, str(lock))))
                first.start()
                self.assertTrue(entered_delete.wait(3))
                second = threading.Thread(target=lambda: results.append(unitylock.remove_stale_lock(original, str(lock))))
                second.start()
                second.join(3)
                self.assertFalse(second.is_alive())
                finish_delete.set()
                first.join(3)
                self.assertFalse(first.is_alive())

            self.assertEqual(2, len(results))
            self.assertEqual(replacement, json.loads((lock / "owner.json").read_text(encoding="utf-8")))

    def test_main_waits_for_capacity_before_lock_and_rechecks_after_lock(self):
        events = []
        results = iter((subprocess.CompletedProcess([], 0), subprocess.CompletedProcess([], 1),
                        subprocess.CompletedProcess([], 0)))

        def run(cmd, **kwargs):
            events.append(("run", cmd))
            return next(results)

        with mock.patch.object(unitylock, "MEMGATE", "memgate.py"), \
             mock.patch.object(unitylock.subprocess, "run", side_effect=run), \
             mock.patch.object(unitylock, "acquire", side_effect=lambda wait, cmd: events.append(("lock", None)) or True), \
             mock.patch.object(unitylock, "release_owned_lock",
                               side_effect=lambda: events.append(("release", None)) or True):
            result = unitylock.main(["run", "--wait", "0", "--", "unused"])

        self.assertEqual(4, result)
        self.assertEqual(["run", "lock", "run", "release"], [kind for kind, _ in events])
        self.assertIn("--wait", events[0][1])
        self.assertNotIn("--wait", events[2][1])


if __name__ == "__main__":
    unittest.main(verbosity=2)
