"""Cross-process checks for the per-unit writer lock."""

import contextlib
import io
import multiprocessing
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest
from unittest import mock
import uuid

from tools.homm3_def_retarget import unit_writer


FIRST_UNIT = "h3_automaton_upg_alt"
OTHER_UNIT = "h3_lizardman"


def _hold_in_child(lock_dir, ready, release, crash):
    with unit_writer.hold_unit_lock(FIRST_UNIT, Path(lock_dir)):
        ready.set()
        release.wait(10)
        if crash:
            os._exit(17)


class UnitWriterTests(unittest.TestCase):
    def test_keys_are_known_and_canonical(self):
        unit_writer.validate_unit(FIRST_UNIT)
        for bad in ("../h3_automaton_upg_alt", "H3_automaton_upg_alt", "not_a_unit", "h3_lizardman/../x"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                unit_writer.validate_unit(bad)

    def test_same_unit_refuses_other_unit_proceeds_and_crash_releases(self):
        ctx = multiprocessing.get_context("spawn")
        base = (unit_writer.ROOT / ".tmp_test").resolve()
        base.mkdir(exist_ok=True)
        lock_dir = (base / f"unit_writer_{uuid.uuid4().hex}").resolve()
        self.assertTrue(lock_dir.is_relative_to(base))
        lock_dir.mkdir()
        try:
            for crash in (False, True):
                with self.subTest(crash=crash):
                    ready, release = ctx.Event(), ctx.Event()
                    child = ctx.Process(target=_hold_in_child, args=(lock_dir, ready, release, crash))
                    child.start()
                    try:
                        self.assertTrue(ready.wait(10), "lock holder did not start")
                        with self.assertRaises(unit_writer.UnitLockUnavailable):
                            with unit_writer.hold_unit_lock(FIRST_UNIT, lock_dir):
                                pass
                        with unit_writer.hold_unit_lock(OTHER_UNIT, lock_dir):
                            pass
                    finally:
                        release.set()
                        child.join(10)
                        if child.is_alive():
                            child.terminate()
                            child.join(5)
                    self.assertEqual(17 if crash else 0, child.exitcode)
                    with unit_writer.hold_unit_lock(FIRST_UNIT, lock_dir):
                        pass
        finally:
            self.assertTrue(lock_dir.is_relative_to(base))
            shutil.rmtree(lock_dir)

    def test_cli_holds_lock_across_child_and_returns_child_status(self):
        with mock.patch.object(unit_writer, "_supervised_run", return_value=7) as run:
            self.assertEqual(7, unit_writer.main([FIRST_UNIT, "--", sys.executable, "-c", "pass"]))
        run.assert_called_once_with(FIRST_UNIT, [sys.executable, "-c", "pass"])

    def test_cli_refuses_contended_lock_without_launching_child(self):
        err = io.StringIO()
        with mock.patch.object(unit_writer, "_supervised_run", side_effect=unit_writer.UnitLockUnavailable("busy")), \
             mock.patch.object(unit_writer.subprocess, "run") as run, contextlib.redirect_stderr(err):
            self.assertEqual(1, unit_writer.main([FIRST_UNIT, "--", sys.executable, "-c", "pass"]))
        run.assert_not_called()
        self.assertIn("UNIT_WRITER REFUSED busy", err.getvalue())

    def test_job_kills_live_grandchild_before_lock_reuse(self):
        import win32api
        import win32con
        import win32event

        base = (unit_writer.ROOT / ".tmp_test").resolve()
        base.mkdir(exist_ok=True)
        for kill_supervisor in (False, True):
            with self.subTest(kill_supervisor=kill_supervisor):
                marker = base / f"unit_writer_grandchild_{uuid.uuid4().hex}.txt"
                grandchild_code = f"import os,time;from pathlib import Path;Path({str(marker)!r}).write_text(str(os.getpid()));time.sleep(60)"
                child_code = (
                    "import subprocess,sys,time;from pathlib import Path;"
                    f"subprocess.Popen([sys.executable,'-c',{grandchild_code!r}]);"
                    f"marker=Path({str(marker)!r});"
                    "[(time.sleep(.05)) for _ in range(100) if not marker.exists()];"
                    + ("time.sleep(60)" if kill_supervisor else "pass")
                )
                supervisor = subprocess.Popen(
                    [sys.executable, str(Path(unit_writer.__file__).resolve()), FIRST_UNIT,
                     "--", sys.executable, "-c", child_code],
                    cwd=unit_writer.ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                process = None
                try:
                    deadline = time.monotonic() + 10
                    while not marker.exists() and time.monotonic() < deadline and supervisor.poll() is None:
                        time.sleep(.05)
                    self.assertTrue(marker.exists(), "grandchild never started")
                    pid = int(marker.read_text())
                    try:
                        process = win32api.OpenProcess(win32con.SYNCHRONIZE | win32con.PROCESS_TERMINATE, False, pid)
                    except Exception as exc:
                        if kill_supervisor or getattr(exc, "winerror", None) != 87:
                            raise
                        # The normal-exit path may have drained the Job before this open.
                    if kill_supervisor:
                        with self.assertRaises(unit_writer.UnitLockUnavailable):
                            with unit_writer.hold_unit_lock(FIRST_UNIT):
                                pass
                        supervisor.terminate()
                    supervisor.wait(timeout=10)
                    if process is not None:
                        self.assertEqual(win32event.WAIT_OBJECT_0, win32event.WaitForSingleObject(process, 5000))
                    with unit_writer.hold_unit_lock(FIRST_UNIT):
                        pass
                finally:
                    if supervisor.poll() is None:
                        supervisor.terminate()
                        supervisor.wait(timeout=10)
                    if process is not None:
                        if win32event.WaitForSingleObject(process, 0) != win32event.WAIT_OBJECT_0:
                            win32api.TerminateProcess(process, 1)
                        process.Close()
                    marker.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
