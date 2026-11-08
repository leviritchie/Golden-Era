"""Fast, filesystem-free tests for cascade process probes and lock ownership."""
from __future__ import annotations

import json
import math
import subprocess
import unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import gpu_cascade_batch_lock as cascade_lock


class _MemoryWriter:
    def __init__(self, path: "_MemoryPath") -> None:
        self.path = path

    def __enter__(self) -> "_MemoryWriter":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def write(self, value: str) -> int:
        if self.path.write_failure:
            if self.path.write_race_contents is not None:
                self.path.replace_contents(self.path.write_race_contents)
                self.path.write_race_contents = None
            self.path.write_failure = False
            raise OSError("simulated lock write failure")
        self.path.contents = (self.path.contents or "") + value
        return len(value)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None

    def fileno(self) -> int:
        return 4242


class _MemoryPath:
    """Minimal lock-path double; tests never touch a real lock file."""

    def __init__(self, contents: str | None = None) -> None:
        self.contents = contents
        self.unlink_calls = 0
        self.exclusive_race_contents: str | None = None
        self.write_failure = False
        self.write_race_contents: str | None = None
        self.device = 1
        self.inode = 1
        self.next_inode = 2
        self.opened_identity: tuple[int, int] | None = None

    @property
    def parent(self) -> "_MemoryPath":
        return self

    def __str__(self) -> str:
        return "memory://cascade.lock"

    def exists(self) -> bool:
        return self.contents is not None

    def is_file(self) -> bool:
        return self.exists()

    def read_text(self, encoding: str = "utf-8") -> str:
        if self.contents is None:
            raise FileNotFoundError(str(self))
        return self.contents

    def replace_contents(self, value: str) -> None:
        self.contents = value
        self.inode = self.next_inode
        self.next_inode += 1

    def stat(self, *, follow_symlinks: bool = True) -> SimpleNamespace:
        if self.contents is None:
            raise FileNotFoundError(str(self))
        return SimpleNamespace(st_dev=self.device, st_ino=self.inode)

    def lstat(self) -> SimpleNamespace:
        return self.stat()

    def write_text(self, value: str, encoding: str = "utf-8") -> int:
        self.contents = value
        return len(value)

    def mkdir(self, *, parents: bool = False, exist_ok: bool = False) -> None:
        return None

    def open(self, mode: str, encoding: str = "utf-8") -> _MemoryWriter:
        if mode != "x":
            raise AssertionError(f"unexpected lock open mode: {mode}")
        if self.exclusive_race_contents is not None:
            self.replace_contents(self.exclusive_race_contents)
            self.exclusive_race_contents = None
            raise FileExistsError(str(self))
        if self.contents is not None:
            raise FileExistsError(str(self))
        self.contents = ""
        self.inode = self.next_inode
        self.next_inode += 1
        self.opened_identity = (self.device, self.inode)
        return _MemoryWriter(self)

    def unlink(self, *, missing_ok: bool = False) -> None:
        self.unlink_calls += 1
        if self.contents is None and not missing_ok:
            raise FileNotFoundError(str(self))
        self.contents = None


@contextmanager
def _unlocked_guard(_path: str):
    yield True


@contextmanager
def _busy_guard(_path: str):
    yield False


@contextmanager
def _memory_lock_io(path: _MemoryPath):
    def fake_fstat(_fd: int) -> SimpleNamespace:
        if path.opened_identity is None:
            return SimpleNamespace(st_dev=path.device, st_ino=path.inode)
        device, inode = path.opened_identity
        return SimpleNamespace(st_dev=device, st_ino=inode)

    with patch.object(cascade_lock, "Path", new=lambda value: value), patch.object(
        cascade_lock, "advisory_guard", new=_unlocked_guard, create=True
    ), patch.object(cascade_lock.os, "fstat", side_effect=fake_fstat):
        yield


def _probe_stdout(rows: object) -> str:
    return "QUERY_OK\n" + json.dumps(rows, separators=(",", ":")) + "\n"


class CascadeProbeTests(unittest.TestCase):
    def _run_probe(self, stdout: str, returncode: int = 0) -> list[dict[str, object]]:
        completed = subprocess.CompletedProcess(
            args=["powershell", "-Command", "probe"],
            returncode=returncode,
            stdout=stdout,
            stderr="",
        )
        with patch.object(cascade_lock.os, "name", "nt"), patch.object(
            cascade_lock.subprocess, "run", return_value=completed
        ):
            return cascade_lock.list_python_processes()

    def test_probe_rejects_unknown_results(self) -> None:
        cases = (
            ("nonzero CIM", "QUERY_OK\n[]\n", 1),
            ("empty output", "", 0),
            ("missing sentinel", "[]\n", 0),
            ("empty JSON payload", "QUERY_OK\n", 0),
            ("malformed JSON", "QUERY_OK\n[{bad]\n", 0),
            ("null JSON", "QUERY_OK\nnull\n", 0),
            (
                "malformed row",
                _probe_stdout([{"ProcessId": 0, "CommandLine": "python"}]),
                0,
            ),
            ("missing row field", _probe_stdout([{"ProcessId": 8}]), 0),
            (
                "empty foreign command line",
                _probe_stdout([{"ProcessId": 8, "CommandLine": ""}]),
                0,
            ),
            (
                "null foreign command line",
                _probe_stdout([{"ProcessId": 8, "CommandLine": None}]),
                0,
            ),
        )
        for label, stdout, returncode in cases:
            with self.subTest(label=label), patch.object(
                cascade_lock.os, "name", "nt"
            ), patch.object(
                cascade_lock.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    args=["powershell"],
                    returncode=returncode,
                    stdout=stdout,
                    stderr="",
                ),
            ):
                with self.assertRaises(cascade_lock.ProcessProbeError):
                    cascade_lock.list_python_processes()

        with patch.object(cascade_lock.os, "name", "nt"), patch.object(
            cascade_lock.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["powershell"], 30),
        ):
            with self.assertRaises(cascade_lock.ProcessProbeError):
                cascade_lock.list_python_processes()

        with patch.object(cascade_lock.os, "name", "nt"), patch.object(
            cascade_lock.subprocess, "run", side_effect=OSError("CIM unavailable")
        ):
            with self.assertRaises(cascade_lock.ProcessProbeError):
                cascade_lock.list_python_processes()

    def test_probe_parses_valid_processes_and_deduplicates_live_pids(self) -> None:
        rows = [
            {"ProcessId": 100, "CommandLine": "python run_gpu_cascade_animation_set.py"},
            {"ProcessId": 200, "CommandLine": "python run_crusader_gpu_cascade_animation_set.py"},
            {"ProcessId": 200, "CommandLine": "python run_crusader_gpu_cascade_animation_set.py --resume"},
            {"ProcessId": 300, "CommandLine": "python unrelated.py"},
        ]
        processes = self._run_probe(_probe_stdout(rows))
        self.assertTrue(
            all(
                type(row.get("ProcessId")) is int and row["ProcessId"] > 0
                for row in processes
            )
        )
        self.assertTrue(all(isinstance(row.get("CommandLine"), str) for row in processes))
        self.assertEqual(
            [200],
            cascade_lock.live_cascade_batch_pids(self_pid=100, processes=processes),
        )

    def test_live_owner_is_busy_without_process_inventory(self) -> None:
        path = _MemoryPath("4242\n")
        probe = Mock(side_effect=AssertionError("must not enumerate"))
        with _memory_lock_io(path), self.assertRaises(cascade_lock.CascadeBusyError):
            cascade_lock.acquire_cascade_batch_lock(
                path,
                pid=9001,
                pid_alive=lambda pid: pid == 4242,
                list_processes=probe,
            )
        probe.assert_not_called()
        self.assertEqual("4242\n", path.contents)
        self.assertEqual(0, path.unlink_calls)

    def test_guard_contention_is_busy_without_process_inventory(self) -> None:
        path = _MemoryPath()
        probe = Mock(side_effect=AssertionError("busy guard must not enumerate"))
        with _memory_lock_io(path), patch.object(
            cascade_lock, "advisory_guard", new=_busy_guard
        ), self.assertRaises(cascade_lock.CascadeBusyError):
            cascade_lock.acquire_cascade_batch_lock(
                path,
                pid=9001,
                pid_alive=lambda _pid: False,
                list_processes=probe,
            )
        probe.assert_not_called()
        self.assertIsNone(path.contents)
        self.assertEqual(0, path.unlink_calls)

    def test_dead_and_absent_owner_each_use_one_inventory(self) -> None:
        for initial, label in (("4242\n", "dead owner"), (None, "absent lock")):
            with self.subTest(label=label):
                path = _MemoryPath(initial)
                probe = Mock(return_value=[])
                with _memory_lock_io(path):
                    result = cascade_lock.acquire_cascade_batch_lock(
                        path,
                        pid=9001,
                        pid_alive=lambda _pid: False,
                        list_processes=probe,
                    )
                self.assertIs(result, path)
                probe.assert_called_once_with()
                self.assertEqual("9001\n", path.contents)

    def test_expired_deadline_fails_without_waiting_or_inventory(self) -> None:
        path = _MemoryPath()
        probe = Mock(side_effect=AssertionError("expired deadline must not probe"))
        with _memory_lock_io(path), patch.object(
            cascade_lock.time, "monotonic", return_value=11.0
        ), patch.object(cascade_lock, "list_python_processes", probe), self.assertRaises(
            cascade_lock.CascadeBusyError
        ):
            cascade_lock.acquire_cascade_batch_lock(
                path,
                pid=9001,
                pid_alive=lambda _pid: False,
                deadline=10.0,
            )
        probe.assert_not_called()

    def test_live_cascade_process_blocks_stale_lock_replacement(self) -> None:
        path = _MemoryPath("4242\n")
        probe = Mock(
            return_value=[
                {
                    "ProcessId": 7777,
                    "CommandLine": "python run_gpu_cascade_animation_set.py --fit-only",
                }
            ]
        )
        with _memory_lock_io(path), self.assertRaises(cascade_lock.CascadeBusyError):
            cascade_lock.acquire_cascade_batch_lock(
                path,
                pid=9001,
                pid_alive=lambda _pid: False,
                list_processes=probe,
            )
        probe.assert_called_once_with()
        self.assertEqual("4242\n", path.contents)
        self.assertEqual(0, path.unlink_calls)

    def test_probe_exception_preserves_stale_lock(self) -> None:
        path = _MemoryPath("4242\n")
        probe_error = cascade_lock.ProcessProbeError("inventory unknown")
        probe = Mock(side_effect=probe_error)
        with _memory_lock_io(path), self.assertRaises(cascade_lock.ProcessProbeError):
            cascade_lock.acquire_cascade_batch_lock(
                path,
                pid=9001,
                pid_alive=lambda _pid: False,
                list_processes=probe,
            )
        self.assertEqual("4242\n", path.contents)
        self.assertEqual(0, path.unlink_calls)

    def test_changed_stale_owner_is_rechecked_before_unlink(self) -> None:
        path = _MemoryPath("4242\n")

        def replace_owner() -> list[dict[str, object]]:
            path.replace_contents("7777\n")
            return []

        with _memory_lock_io(path), self.assertRaises(cascade_lock.CascadeBusyError):
            cascade_lock.acquire_cascade_batch_lock(
                path,
                pid=9001,
                pid_alive=lambda pid: pid == 7777,
                list_processes=replace_owner,
            )
        self.assertEqual("7777\n", path.contents)
        self.assertEqual(0, path.unlink_calls)

    def test_exclusive_create_race_preserves_competing_owner(self) -> None:
        path = _MemoryPath()
        path.exclusive_race_contents = "7777\n"
        with _memory_lock_io(path), self.assertRaises(cascade_lock.CascadeBusyError):
            cascade_lock.acquire_cascade_batch_lock(
                path,
                pid=9001,
                pid_alive=lambda _pid: False,
                list_processes=lambda: [],
            )
        self.assertEqual("7777\n", path.contents)
        self.assertEqual(0, path.unlink_calls)

    def test_release_ignores_a_foreign_owner(self) -> None:
        path = _MemoryPath("7777\n")
        with _memory_lock_io(path):
            cascade_lock.release_cascade_batch_lock(path, pid=9001)
        self.assertEqual("7777\n", path.contents)
        self.assertEqual(0, path.unlink_calls)

    def test_write_failure_preserves_a_replacement_owner(self) -> None:
        path = _MemoryPath()
        path.write_failure = True
        path.write_race_contents = "7777\n"
        with _memory_lock_io(path), self.assertRaises((OSError, RuntimeError)):
            cascade_lock.acquire_cascade_batch_lock(
                path,
                pid=9001,
                pid_alive=lambda _pid: False,
                list_processes=lambda: [],
            )
        self.assertEqual("7777\n", path.contents)
        self.assertEqual(0, path.unlink_calls)

    def test_write_failure_removes_its_own_partial_lock(self) -> None:
        path = _MemoryPath()
        path.write_failure = True
        with _memory_lock_io(path), self.assertRaises((OSError, RuntimeError)):
            cascade_lock.acquire_cascade_batch_lock(
                path,
                pid=9001,
                pid_alive=lambda _pid: False,
                list_processes=lambda: [],
            )
        self.assertIsNone(path.contents)
        self.assertEqual(1, path.unlink_calls)

    def test_wait_retries_busy_with_mocked_backoff_then_acquires(self) -> None:
        lock_path = _MemoryPath()
        acquire = Mock(
            side_effect=[
                cascade_lock.CascadeBusyError("busy"),
                lock_path,
            ]
        )
        release = Mock()
        with patch.object(
            cascade_lock, "global_cascade_batch_lock_path", return_value=lock_path
        ), patch.object(cascade_lock, "acquire_cascade_batch_lock", acquire), patch.object(
            cascade_lock, "release_cascade_batch_lock", release
        ), patch.object(
            cascade_lock.time, "monotonic", side_effect=[100.0, 101.0, 102.0]
        ), patch.object(cascade_lock.time, "sleep") as sleep, patch.object(
            cascade_lock.random, "uniform", return_value=1.0
        ):
            with cascade_lock.wait_for_cascade_batch_lock(
                "repo", timeout_sec=60.0, poll_sec=5.0
            ) as (acquired, waited):
                self.assertIs(acquired, lock_path)
                self.assertEqual(2.0, waited)

        self.assertEqual(
            [call(lock_path, deadline=160.0), call(lock_path, deadline=160.0)],
            acquire.call_args_list,
        )
        sleep.assert_called_once_with(5.0)
        release.assert_called_once_with(lock_path)

    def test_wait_propagates_probe_error_without_sleep(self) -> None:
        lock_path = _MemoryPath()
        acquire = Mock(side_effect=cascade_lock.ProcessProbeError("CIM failed"))
        release = Mock()
        with patch.object(
            cascade_lock, "global_cascade_batch_lock_path", return_value=lock_path
        ), patch.object(cascade_lock, "acquire_cascade_batch_lock", acquire), patch.object(
            cascade_lock, "release_cascade_batch_lock", release
        ), patch.object(cascade_lock.time, "monotonic", return_value=20.0), patch.object(
            cascade_lock.time, "sleep"
        ) as sleep, self.assertRaises(cascade_lock.ProcessProbeError):
            with cascade_lock.wait_for_cascade_batch_lock("repo"):
                self.fail("probe errors must be raised before entering the protected body")

        acquire.assert_called_once_with(lock_path, deadline=1820.0)
        sleep.assert_not_called()
        release.assert_not_called()

    def test_body_busy_error_releases_without_retry(self) -> None:
        lock_path = _MemoryPath()
        acquire = Mock(return_value=lock_path)
        release = Mock()
        with patch.object(
            cascade_lock, "global_cascade_batch_lock_path", return_value=lock_path
        ), patch.object(cascade_lock, "acquire_cascade_batch_lock", acquire), patch.object(
            cascade_lock, "release_cascade_batch_lock", release
        ), patch.object(cascade_lock.time, "monotonic", side_effect=[30.0, 31.0]), patch.object(
            cascade_lock.time, "sleep"
        ) as sleep, self.assertRaises(cascade_lock.CascadeBusyError):
            with cascade_lock.wait_for_cascade_batch_lock("repo"):
                raise cascade_lock.CascadeBusyError("body failure")

        acquire.assert_called_once_with(lock_path, deadline=1830.0)
        sleep.assert_not_called()
        release.assert_called_once_with(lock_path)

    def test_wait_rejects_invalid_timeout_and_poll_configuration(self) -> None:
        invalid_options = (
            ("NaN timeout", {"timeout_sec": math.nan}),
            ("infinite timeout", {"timeout_sec": math.inf}),
            ("negative infinite timeout", {"timeout_sec": -math.inf}),
            ("negative timeout", {"timeout_sec": -0.1}),
            ("NaN poll", {"poll_sec": math.nan}),
            ("infinite poll", {"poll_sec": math.inf}),
            ("negative infinite poll", {"poll_sec": -math.inf}),
            ("zero poll", {"poll_sec": 0.0}),
            ("negative poll", {"poll_sec": -0.1}),
        )
        lock_path = _MemoryPath()
        for label, options in invalid_options:
            with self.subTest(label=label):
                acquire = Mock(side_effect=AssertionError("invalid options must fail first"))
                with patch.object(
                    cascade_lock,
                    "global_cascade_batch_lock_path",
                    return_value=lock_path,
                ), patch.object(
                    cascade_lock, "acquire_cascade_batch_lock", acquire
                ), self.assertRaises(ValueError):
                    with cascade_lock.wait_for_cascade_batch_lock("repo", **options):
                        self.fail("invalid wait configuration must not acquire")
                acquire.assert_not_called()

    def test_late_process_inventory_times_out_without_lock_mutation(self) -> None:
        path = _MemoryPath()
        now = [100.0]

        def late_inventory(*, timeout_sec: float, self_pid: int) -> list[dict[str, object]]:
            self.assertEqual(5.0, timeout_sec)
            now[0] = 106.0
            return [{"ProcessId": self_pid, "CommandLine": "python probe.py"}]

        with _memory_lock_io(path), patch.object(
            cascade_lock,
            "global_cascade_batch_lock_path",
            return_value=path,
        ), patch.object(
            cascade_lock.time, "monotonic", side_effect=lambda: now[0]
        ), patch.object(
            cascade_lock, "list_python_processes", side_effect=late_inventory
        ), patch.object(cascade_lock.time, "sleep") as sleep, self.assertRaises(
            cascade_lock.CascadeWaitTimeoutError
        ):
            with cascade_lock.wait_for_cascade_batch_lock("repo", timeout_sec=5.0):
                self.fail("late inventory must not acquire the lock")

        sleep.assert_not_called()
        self.assertIsNone(path.contents)
        self.assertEqual(0, path.unlink_calls)

    def test_wait_caps_backoff_sleep_to_remaining_deadline(self) -> None:
        lock_path = _MemoryPath()
        acquire = Mock(
            side_effect=[
                cascade_lock.CascadeBusyError("busy"),
                cascade_lock.CascadeBusyError("still busy"),
            ]
        )
        release = Mock()
        with patch.object(
            cascade_lock, "global_cascade_batch_lock_path", return_value=lock_path
        ), patch.object(cascade_lock, "acquire_cascade_batch_lock", acquire), patch.object(
            cascade_lock, "release_cascade_batch_lock", release
        ), patch.object(
            cascade_lock.time, "monotonic", side_effect=[100.0, 111.0, 112.0]
        ), patch.object(cascade_lock.time, "sleep") as sleep, patch.object(
            cascade_lock.random, "uniform", return_value=1.0
        ), self.assertRaises(cascade_lock.CascadeWaitTimeoutError):
            with cascade_lock.wait_for_cascade_batch_lock(
                "repo", timeout_sec=12.0, poll_sec=5.0
            ):
                self.fail("busy lock must not enter the protected body")

        self.assertEqual(
            [call(lock_path, deadline=112.0), call(lock_path, deadline=112.0)],
            acquire.call_args_list,
        )
        sleep.assert_called_once_with(1.0)
        release.assert_not_called()


if __name__ == "__main__":
    unittest.main()
