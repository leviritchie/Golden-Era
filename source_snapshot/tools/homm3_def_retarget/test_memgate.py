"""Focused, no-GPU tests for the pre-Blender resource gate."""

import contextlib
import io
import subprocess
import ctypes
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.homm3_def_retarget import memgate


class MemgateTests(unittest.TestCase):
    def test_native_memory_status_layout_and_snapshot(self):
        self.assertEqual(64, memgate.ctypes.sizeof(memgate.MEMORYSTATUSEX))
        class NativeProbe:
            def __call__(self, pointer):
                status = ctypes.cast(pointer, ctypes.POINTER(memgate.MEMORYSTATUSEX)).contents
                status.ullAvailPhys = 6 * 1024 ** 3
                status.ullTotalPhys = 32 * 1024 ** 3
                return 1

        native_probe = NativeProbe()
        with mock.patch.object(memgate.ctypes, "WinDLL", return_value=SimpleNamespace(
            GlobalMemoryStatusEx=native_probe,
        )):
            self.assertEqual((6.0, 32.0), memgate.memory_gb())
            self.assertEqual(6.0, memgate.free_ram_gb())

    def test_native_memory_probe_error_refuses(self):
        with mock.patch.object(memgate.ctypes, "WinDLL", side_effect=OSError("unavailable")):
            with self.assertRaisesRegex(memgate.ProbeError, "GlobalMemoryStatusEx unavailable"):
                memgate.free_ram_gb()

    def test_gpu_probe_requires_success_and_a_number(self):
        with mock.patch.object(memgate.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "8192, 4096\n", "")):
            self.assertEqual(4.0, memgate.free_vram_gb())
        bad_results = [
            subprocess.CompletedProcess([], 1, "8192, 4096\n", "failed"),
            subprocess.CompletedProcess([], 0, "", ""),
            subprocess.CompletedProcess([], 0, "unknown\n", ""),
            subprocess.CompletedProcess([], 0, "8192\n", ""),
            subprocess.CompletedProcess([], 0, "-1, 0\n", ""),
            subprocess.CompletedProcess([], 0, "8192, 9000\n", ""),
        ]
        for result in bad_results:
            with self.subTest(result=result):
                with mock.patch.object(memgate.subprocess, "run", return_value=result):
                    with self.assertRaises(memgate.ProbeError):
                        memgate.free_vram_gb()
        with mock.patch.object(memgate.subprocess, "run", side_effect=FileNotFoundError("nvidia-smi")):
            with self.assertRaisesRegex(memgate.ProbeError, "nvidia-smi unavailable"):
                memgate.free_vram_gb()

    def test_vram_snapshot_returns_free_and_total_from_one_probe(self):
        result = subprocess.CompletedProcess([], 0, "16303, 13526\n", "")
        with mock.patch.object(memgate.subprocess, "run", return_value=result) as run:
            free, total = memgate.vram_gb()
        self.assertAlmostEqual(13526 / 1024, free)
        self.assertAlmostEqual(16303 / 1024, total)
        self.assertEqual("--query-gpu=memory.total,memory.free", run.call_args.args[0][1])

    def test_cli_numeric_outputs_and_probe_failure(self):
        cases = [
            (6.0, 4.0, 0, "MEMGATE OK free RAM 6.0 GB, free VRAM 4.0 GB"),
            (4.0, 4.0, 1, "MEMGATE FULL free RAM 4.0 GB (need 5.0), free VRAM 4.0 GB (need 3.0)"),
            (6.0, 2.0, 1, "MEMGATE FULL free RAM 6.0 GB (need 5.0), free VRAM 2.0 GB (need 3.0)"),
        ]
        for ram, vram, expected_rc, expected_line in cases:
            with self.subTest(ram=ram, vram=vram):
                out = io.StringIO()
                with mock.patch.object(memgate, "free_ram_gb", return_value=ram), \
                     mock.patch.object(memgate, "free_vram_gb", return_value=vram), \
                     mock.patch.object(memgate.time, "sleep"), contextlib.redirect_stdout(out):
                    self.assertEqual(expected_rc, memgate.main([]))
                self.assertEqual(expected_line, out.getvalue().strip())

        out = io.StringIO()
        with mock.patch.object(memgate, "free_ram_gb", return_value=6.0), \
             mock.patch.object(memgate, "free_vram_gb", side_effect=memgate.ProbeError("nvidia-smi exited 1")), \
             mock.patch.object(memgate.time, "sleep"), contextlib.redirect_stdout(out):
            self.assertEqual(1, memgate.main(["--wait", "30"]))
        self.assertEqual("MEMGATE FULL probe failed: nvidia-smi exited 1", out.getvalue().strip())

    def test_zero_wait_probes_immediately_without_jitter(self):
        out = io.StringIO()
        with mock.patch.object(memgate, "check", return_value=(False, 4.0, 2.0)), \
             mock.patch.object(memgate.time, "monotonic", side_effect=(10.0, 10.0)), \
             mock.patch.object(memgate.time, "sleep") as sleep, contextlib.redirect_stdout(out):
            self.assertEqual(1, memgate.main([]))
        sleep.assert_not_called()
        self.assertIn("MEMGATE FULL free RAM 4.0 GB", out.getvalue())

    def test_wait_sleep_is_capped_to_remaining_deadline(self):
        out = io.StringIO()
        with mock.patch.object(memgate, "check", return_value=(False, 4.0, 2.0)), \
             mock.patch.object(memgate.time, "monotonic", side_effect=(0.0, 29.0, 30.0)), \
             mock.patch.object(memgate.random, "uniform", return_value=15.0), \
             mock.patch.object(memgate.time, "sleep") as sleep, contextlib.redirect_stdout(out):
            self.assertEqual(1, memgate.main(["--wait", "0.5"]))
        sleep.assert_called_once_with(1.0)

    def test_wait_rejects_nonfinite_negative_or_missing_values(self):
        for args in (("--wait", "nan"), ("--wait", "inf"), ("--wait", "-1"), ("--wait",)):
            with self.subTest(args=args):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    self.assertEqual(2, memgate.main(list(args)))
                self.assertIn("invalid --wait value", out.getvalue())


if __name__ == "__main__":
    unittest.main()
