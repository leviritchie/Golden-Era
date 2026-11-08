"""Focused test: gpuslot breaks a slot only when its holder is provably gone (temp slot dir, no real bakes).

    python tools/homm3_unit_look/test_gpuslot.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import unittest
import ctypes
from ctypes import wintypes
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gpuslot  # noqa: E402
from test_tempdir import workspace_tempdir  # noqa: E402


def _dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class GpuSlotStaleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = workspace_tempdir(__file__)
        self.addCleanup(self.tmp.cleanup)
        for name, value in (("SLOTS_DIR", self.tmp.name), ("STALE_CONFIRM_S", 0.0)):
            patcher = mock.patch.object(gpuslot, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.slot = os.path.join(self.tmp.name, "slot_0")
        os.mkdir(self.slot)

    def hold(self, **owner):
        with open(os.path.join(self.slot, "owner.json"), "w") as f:
            json.dump(owner, f)

    def test_live_holder_is_kept(self):
        self.hold(pid=os.getpid(), created=gpuslot.process_created(os.getpid()))
        self.assertIsNotNone(gpuslot.process_created(os.getpid()))
        self.assertEqual(gpuslot.holder_state(gpuslot.owner(self.slot)), "alive")
        self.assertFalse(gpuslot._stale(self.slot))

    def test_legacy_owner_without_created_is_kept_while_alive(self):
        self.hold(pid=os.getpid())
        self.assertFalse(gpuslot._stale(self.slot))

    def test_exited_holder_is_broken(self):
        self.hold(pid=_dead_pid())
        self.assertTrue(gpuslot._stale(self.slot))

    def test_reused_pid_is_broken(self):
        created = gpuslot.process_created(os.getpid())
        self.hold(pid=os.getpid(), created=created + 1)
        self.assertEqual(gpuslot.holder_state(gpuslot.owner(self.slot)), "gone")
        self.assertTrue(gpuslot._stale(self.slot))

    def test_probe_failure_is_diagnostic_and_preserves_slot(self):
        self.hold(pid=12345)
        with mock.patch.object(gpuslot, "_process_state", side_effect=gpuslot.SlotProcessProbeError(
                "OpenProcess failed for PID 12345: WinError 6")):
            with self.assertRaisesRegex(gpuslot.SlotProcessProbeError, "WinError 6"):
                gpuslot._stale(self.slot)
        self.assertTrue(Path(self.slot).is_dir())

    def test_process_probe_distinguishes_denied_gone_and_unknown_open_errors(self):
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 0
        kernel.CloseHandle.return_value = 1
        with mock.patch.object(ctypes, "WinDLL", return_value=kernel), \
             mock.patch.object(ctypes, "get_last_error", return_value=5, create=True):
            self.assertEqual(gpuslot._process_state(4321), ("alive", None))
        with mock.patch.object(ctypes, "WinDLL", return_value=kernel), \
             mock.patch.object(ctypes, "get_last_error", return_value=87, create=True):
            self.assertEqual(gpuslot._process_state(4321), ("gone", None))
        with mock.patch.object(ctypes, "WinDLL", return_value=kernel), \
             mock.patch.object(ctypes, "get_last_error", return_value=6, create=True):
            with self.assertRaisesRegex(gpuslot.SlotProcessProbeError, "OpenProcess.*WinError 6"):
                gpuslot._process_state(4321)
        kernel.OpenProcess.side_effect = OSError("fixture OpenProcess exception")
        with mock.patch.object(ctypes, "WinDLL", return_value=kernel):
            with self.assertRaisesRegex(gpuslot.SlotProcessProbeError, "OpenProcess.*fixture OpenProcess exception"):
                gpuslot._process_state(4321)

    def test_pid_outside_dword_range_is_rejected_before_open_process(self):
        with mock.patch.object(ctypes, "WinDLL", create=True) as win_dll:
            with self.assertRaisesRegex(gpuslot.SlotProcessProbeError, "DWORD range"):
                gpuslot._process_state(0x100000000)
        win_dll.assert_not_called()

    def test_get_exit_probe_unknown_error_is_not_treated_as_a_live_slot(self):
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 1
        kernel.GetExitCodeProcess.return_value = 0
        kernel.CloseHandle.return_value = 1
        for error in (5, 87, 6):
            with self.subTest(error=error), \
                 mock.patch.object(ctypes, "WinDLL", return_value=kernel), \
                 mock.patch.object(ctypes, "get_last_error", return_value=error, create=True):
                with self.assertRaisesRegex(gpuslot.SlotProcessProbeError,
                                            f"GetExitCodeProcess.*WinError {error}"):
                    gpuslot._process_state(4321)
        kernel.GetExitCodeProcess.side_effect = OSError("fixture native query exception")
        with mock.patch.object(ctypes, "WinDLL", return_value=kernel):
            with self.assertRaisesRegex(gpuslot.SlotProcessProbeError, "GetExitCodeProcess.*fixture native query"):
                gpuslot._process_state(4321)

    def test_get_exit_code_87_failure_preserves_existing_slot(self):
        self.hold(pid=4321)
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 1
        kernel.GetExitCodeProcess.return_value = 0
        kernel.CloseHandle.return_value = 1
        with mock.patch.object(ctypes, "WinDLL", return_value=kernel), \
             mock.patch.object(ctypes, "get_last_error", return_value=87, create=True):
            with self.assertRaisesRegex(gpuslot.SlotProcessProbeError, "GetExitCodeProcess.*WinError 87"):
                gpuslot._stale(self.slot)
        self.assertTrue(Path(self.slot).is_dir())
        self.assertEqual(gpuslot.owner(self.slot)["pid"], 4321)

    def test_still_active_process_times_failure_retains_live_owner_without_pin(self):
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 1
        kernel.CloseHandle.return_value = 1

        def still_active(_handle, code_ptr):
            ctypes.cast(code_ptr, ctypes.POINTER(wintypes.DWORD)).contents.value = 259
            return 1

        kernel.GetExitCodeProcess.side_effect = still_active
        kernel.GetProcessTimes.return_value = 0
        with mock.patch.object(ctypes, "WinDLL", return_value=kernel):
            self.assertEqual(gpuslot._process_state(4321), ("alive", None))

    def test_unparseable_owner_fails_fast_and_is_preserved(self):
        self.hold(pid="not-a-pid")
        with self.assertRaisesRegex(gpuslot.SlotMetadataError, "owner.json"):
            gpuslot._stale(self.slot)
        self.assertTrue(Path(self.slot).is_dir())

    def test_unreadable_owner_fails_fast_and_is_preserved(self):
        with mock.patch("builtins.open", side_effect=PermissionError("fixture unreadable owner")):
            with self.assertRaisesRegex(gpuslot.SlotMetadataError, "fixture unreadable owner"):
                gpuslot._stale(self.slot)
        self.assertTrue(Path(self.slot).is_dir())

    def test_break_needs_both_checks(self):
        self.hold(pid=12345)
        with mock.patch.object(gpuslot, "_process_state", side_effect=[("gone", None), ("alive", None)]):
            self.assertFalse(gpuslot._stale(self.slot))

    def test_take_writes_created_and_keeps_live_slot(self):
        self.hold(pid=os.getpid(), created=gpuslot.process_created(os.getpid()))
        with mock.patch.object(gpuslot, "n_slots", return_value=2):
            taken = gpuslot._try_take(["x"], "unit")
        self.assertEqual(taken, os.path.join(self.tmp.name, "slot_1"))
        self.assertTrue(os.path.isdir(self.slot))
        o = gpuslot.owner(taken)
        self.assertEqual(o["pid"], os.getpid())
        self.assertEqual(o["created"], gpuslot.process_created(os.getpid()))

    def test_owner_write_failure_removes_just_created_slot(self):
        os.rmdir(self.slot)
        with mock.patch.object(gpuslot, "n_slots", return_value=1), \
             mock.patch("builtins.open", side_effect=PermissionError("fixture owner write failure")):
            with self.assertRaisesRegex(PermissionError, "fixture owner write failure"):
                gpuslot._try_take(["unused"], "unit")
        self.assertFalse(Path(self.slot).exists())

    def test_try_slot_is_nonblocking_when_occupied(self):
        occupied = Path(self.tmp.name) / "slot_0"
        with mock.patch.object(gpuslot, "n_slots", return_value=1), \
             mock.patch.object(gpuslot.subprocess, "run") as run:
            with gpuslot.try_slot(["unused"], "unit") as slot:
                self.assertIsNone(slot)
        run.assert_not_called()
        self.assertTrue(occupied.is_dir())

    def test_try_slot_releases_its_temp_reservation(self):
        os.rmdir(self.slot)
        with mock.patch.object(gpuslot, "n_slots", return_value=1), \
             mock.patch.object(gpuslot.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)):
            with gpuslot.try_slot(["unused"], "unit") as slot:
                self.assertIsNotNone(slot)
                self.assertTrue(Path(slot).is_dir())
        self.assertFalse(Path(slot).exists())

    def test_zero_wait_slot_refuses_without_sleeping(self):
        with mock.patch.object(gpuslot, "n_slots", return_value=1), \
             mock.patch.object(gpuslot, "wait_minutes", return_value=0), \
             mock.patch.object(gpuslot.time, "sleep") as sleep:
            with self.assertRaisesRegex(gpuslot.SlotError, "stayed busy"):
                with gpuslot.slot(["unused"], "unit"):
                    self.fail("occupied zero-wait slot unexpectedly yielded")
        sleep.assert_not_called()

    def test_second_stale_reaper_cannot_delete_replacement_slot(self):
        entered_delete = threading.Event()
        finish_delete = threading.Event()
        real_rmtree = gpuslot.shutil.rmtree
        results = []

        def replace_during_delete(path, **kwargs):
            real_rmtree(path, **kwargs)
            os.mkdir(path)
            with open(os.path.join(path, "owner.json"), "w") as owner_file:
                json.dump({"pid": os.getpid(), "created": gpuslot.process_created(os.getpid())}, owner_file)
            entered_delete.set()
            if not finish_delete.wait(3):
                raise RuntimeError("test did not release stale reaper")

        with mock.patch.object(gpuslot, "_stale", return_value=True), \
             mock.patch.object(gpuslot.shutil, "rmtree", side_effect=replace_during_delete):
            first = threading.Thread(target=lambda: results.append(gpuslot._reap_stale_slot(self.slot)))
            first.start()
            self.assertTrue(entered_delete.wait(3))
            second = threading.Thread(target=lambda: results.append(gpuslot._reap_stale_slot(self.slot)))
            second.start()
            second.join(3)
            self.assertFalse(second.is_alive())
            finish_delete.set()
            first.join(3)
            self.assertFalse(first.is_alive())

        self.assertEqual(2, len(results))
        self.assertTrue(Path(self.slot).is_dir())
        self.assertEqual(os.getpid(), gpuslot.owner(self.slot)["pid"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
