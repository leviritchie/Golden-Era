"""Fast, side-effect-free regressions for the Unity queue's resource and lock ordering."""
from __future__ import annotations

import json
import unittest
import sys
from pathlib import Path
from unittest import mock

import unity_queue as queue

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.test_tempdir import workspace_tempdir


class FakeEntry:
    def __init__(self, stem: str):
        self.stem = stem
        self.name = stem + ".json"


class FakeQueueDir:
    def __init__(self, entries=()):
        self.entries = list(entries)

    def glob(self, _pattern: str):
        return iter(self.entries)

    def __truediv__(self, name: str):
        return FakeQueueFile(self, name)


class FakeQueueFile:
    def __init__(self, directory: FakeQueueDir, name: str):
        self.directory = directory
        self.name = name

    def is_file(self):
        return any(entry.name == self.name for entry in self.directory.entries)


class FakeQueueRoot:
    def __init__(self, files=()):
        self.files = set(files)

    def __truediv__(self, part: str):
        return FakeQueuePath((*part.split("/"),), self.files)


class FakeQueuePath:
    def __init__(self, parts, files):
        self.parts = tuple(parts)
        self.files = files

    def __truediv__(self, part: str):
        return FakeQueuePath((*self.parts, str(part)), self.files)

    def is_file(self):
        return self.parts in self.files


def job(job_id="job-a"):
    return {
        "id": job_id,
        "key": "key-" + job_id,
        "kind": "fixture",
        "executeMethod": "Fixture.Run",
        "requester": "unittest",
        "inputs": [],
        "project": "P:/unity-project",
        "projectPathAsGiven": "P:/unity-project",
        "unity": "P:/Unity.exe",
        "buildTarget": None,
        "graphics": False,
    }


def capacity_ready():
    return queue.CapacityWaitResult(refusal=None, aborted=False, probe_failed=False)


class UnityQueueResourceTests(unittest.TestCase):
    def test_drain_waits_for_capacity_before_lock_and_claim(self):
        pending = FakeQueueDir([FakeEntry("job-a")])
        events = []
        lock_held = False

        def wait_for_capacity(abort=None, timeout_s=None):
            self.assertFalse(lock_held)
            self.assertEqual(timeout_s, 45)
            events.append("capacity")
            return capacity_ready()

        def acquire(*_args, **_kwargs):
            nonlocal lock_held
            events.append("lock")
            lock_held = True
            return True

        def claim():
            self.assertTrue(lock_held)
            events.append("claim")
            return [job()]

        def launch(*_args, **_kwargs):
            self.assertTrue(lock_held)
            events.append("launch")
            return []

        def release():
            nonlocal lock_held
            events.append("release")
            lock_held = False

        with (
            mock.patch.object(queue, "qdir", return_value=pending),
            mock.patch.object(queue, "wait_for_capacity", side_effect=wait_for_capacity),
            mock.patch.object(queue, "acquire_unity_lock", side_effect=acquire),
            mock.patch.object(queue, "recover_orphans", side_effect=lambda **_kw: events.append("recover")),
            mock.patch.object(queue, "claim_pending", side_effect=claim),
            mock.patch.object(queue, "run_launch", side_effect=launch),
            mock.patch.object(queue, "release_unity_lock", side_effect=release),
        ):
            launches = queue.drain_once(capacity_wait_s=45)

        self.assertEqual(launches, 1)
        self.assertEqual(events, ["capacity", "lock", "recover", "claim", "launch", "release"])
        self.assertFalse(lock_held)

    def test_caller_deadline_is_passed_to_memwait_and_expiry_leaves_pending(self):
        pending = FakeQueueDir([FakeEntry("job-a")])
        root = FakeQueueRoot({("pending", "job-a.json")})
        expected = {"id": "job-a", "status": "ok"}
        with (
            mock.patch.object(queue, "QUEUE_ROOT", root),
            mock.patch.object(queue, "now", return_value=100.0),
            mock.patch.object(queue, "result", side_effect=[None, expected]),
            mock.patch.object(queue, "drain_once", return_value=0) as drain,
        ):
            result = queue.wait_for("job-a", timeout_s=3.25)

        self.assertIs(result, expected)
        self.assertEqual(drain.call_count, 1)
        self.assertEqual(drain.call_args.kwargs["capacity_wait_s"], 3.25)
        self.assertEqual([entry.name for entry in pending.entries], ["job-a.json"])

    def test_capacity_probe_receives_caller_budget_and_zero_budget_skips_probe(self):
        with (
            mock.patch.object(queue.time, "monotonic", return_value=100.0),
            mock.patch.object(queue.memgate, "check", return_value=(True, 8.0, 8.0)) as check,
        ):
            result = queue.wait_for_capacity(timeout_s=2.5)

        self.assertFalse(result.aborted)
        self.assertFalse(result.probe_failed)
        self.assertEqual(check.call_args.kwargs["timeout_s"], 2.5)

        with (
            mock.patch.object(queue.time, "monotonic", return_value=100.0),
            mock.patch.object(queue.memgate, "check") as check,
        ):
            result = queue.wait_for_capacity(timeout_s=0)

        self.assertTrue(result.aborted)
        check.assert_not_called()

    def test_probe_error_before_deadline_fails_closed_before_lock_and_keeps_pending(self):
        pending = FakeQueueDir([FakeEntry("job-a")])
        acquire = mock.Mock()
        claim = mock.Mock()
        with (
            mock.patch.object(queue, "qdir", return_value=pending),
            mock.patch.object(queue.time, "monotonic", return_value=100.0),
            mock.patch.object(queue.memgate, "check", side_effect=queue.memgate.ProbeError(
                "capacity probe timed out")) as check,
            mock.patch.object(queue, "acquire_unity_lock", acquire),
            mock.patch.object(queue, "claim_pending", claim),
        ):
            with self.assertRaisesRegex(queue.QueueError, "capacity probe timed out"):
                queue.drain_once(capacity_wait_s=2.5)

        self.assertEqual(check.call_args.kwargs["timeout_s"], 2.5)
        acquire.assert_not_called()
        claim.assert_not_called()
        self.assertEqual([entry.name for entry in pending.entries], ["job-a.json"])

    def test_probe_timeout_at_caller_deadline_aborts_without_lock_or_claim(self):
        pending = FakeQueueDir([FakeEntry("job-a")])
        acquire = mock.Mock()
        claim = mock.Mock()
        clock = {"tick": 100.0}

        def timed_out_probe(*, timeout_s):
            self.assertEqual(timeout_s, 2.5)
            clock["tick"] = 102.5
            raise queue.memgate.ProbeError("capacity probe timed out")

        with (
            mock.patch.object(queue, "qdir", return_value=pending),
            mock.patch.object(queue.time, "monotonic", side_effect=lambda: clock["tick"]),
            mock.patch.object(queue.memgate, "check", side_effect=timed_out_probe) as check,
            mock.patch.object(queue, "acquire_unity_lock", acquire),
            mock.patch.object(queue, "claim_pending", claim),
        ):
            self.assertEqual(queue.drain_once(capacity_wait_s=2.5), 0)

        self.assertTrue(check.called)
        acquire.assert_not_called()
        claim.assert_not_called()
        self.assertEqual([entry.name for entry in pending.entries], ["job-a.json"])

    def test_pending_job_claimed_by_another_runner_aborts_capacity_wait(self):
        pending = FakeQueueDir([FakeEntry("job-a")])
        acquire = mock.Mock()
        claim = mock.Mock()

        def capacity_wait(abort=None, timeout_s=None):
            self.assertEqual(timeout_s, 30)
            pending.entries.clear()
            self.assertTrue(abort())
            return queue.CapacityWaitResult(aborted=True)

        with (
            mock.patch.object(queue, "qdir", return_value=pending),
            mock.patch.object(queue, "wait_for_capacity", side_effect=capacity_wait),
            mock.patch.object(queue, "acquire_unity_lock", acquire),
            mock.patch.object(queue, "claim_pending", claim),
        ):
            self.assertEqual(queue.drain_once(capacity_wait_s=30), 0)

        acquire.assert_not_called()
        claim.assert_not_called()
        self.assertEqual(pending.entries, [])

    def test_timeout_before_lock_leaves_pending(self):
        pending = FakeQueueDir([FakeEntry("job-a")])
        lock = mock.Mock()
        claim = mock.Mock()
        with (
            mock.patch.object(queue, "qdir", return_value=pending),
            mock.patch.object(queue, "wait_for_capacity", return_value=queue.CapacityWaitResult(
                refusal=None, aborted=True, probe_failed=False)),
            mock.patch.object(queue, "acquire_unity_lock", lock),
            mock.patch.object(queue, "claim_pending", claim),
        ):
            self.assertEqual(queue.drain_once(capacity_wait_s=0.01), 0)

        lock.assert_not_called()
        claim.assert_not_called()
        self.assertEqual([entry.name for entry in pending.entries], ["job-a.json"])

    def test_owner_write_failure_removes_only_the_new_lock_directory(self):
        with workspace_tempdir(__file__) as temp_root:
            root = Path(temp_root)
            lock = root / "queue-lock"
            sibling = root / "unrelated.txt"
            sibling.write_text("keep", encoding="utf-8")
            original_write_text = Path.write_text

            def fail_owner_write(path, data, *args, **kwargs):
                if path.name.startswith("owner.json.tmp-"):
                    raise OSError("mock owner write failure")
                return original_write_text(path, data, *args, **kwargs)

            with (
                mock.patch.object(queue.unitylock, "LOCK", str(lock)),
                mock.patch.object(Path, "write_text", autospec=True, side_effect=fail_owner_write),
            ):
                with self.assertRaisesRegex(OSError, "mock owner write failure"):
                    queue.acquire_unity_lock("fixture", wait_s=0)

            self.assertFalse(lock.exists())
            self.assertEqual(sibling.read_text(encoding="utf-8"), "keep")

    def test_malformed_lock_metadata_fails_without_polling(self):
        with workspace_tempdir(__file__) as temp_root:
            lock = Path(temp_root) / "held-lock"
            lock.mkdir()
            (lock / "owner.json").write_text("{bad json", encoding="utf-8")
            with (
                mock.patch.object(queue.unitylock, "LOCK", str(lock)),
                mock.patch.object(queue.unitylock, "holder", side_effect=queue.unitylock.LockMetadataError(
                    "malformed owner metadata")),
                mock.patch.object(queue.time, "sleep") as sleep,
                mock.patch.object(queue, "pid_alive") as pid_alive,
            ):
                with self.assertRaisesRegex(queue.QueueError, "malformed owner metadata"):
                    queue.acquire_unity_lock("fixture", wait_s=3600)

            sleep.assert_not_called()
            pid_alive.assert_not_called()

    def test_unknown_lock_owner_pid_probe_fails_without_waiting_or_reaping(self):
        with workspace_tempdir(__file__) as temp_root:
            lock = Path(temp_root) / "held-lock"
            lock.mkdir()
            owner = {"pid": 4321, "cmd": "fixture"}
            (lock / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
            with (
                mock.patch.object(queue.unitylock, "LOCK", str(lock)),
                mock.patch.object(queue.unitylock, "holder", return_value=owner),
                mock.patch.object(queue, "pid_alive", side_effect=queue.unitylock.ProcessProbeError(
                    "OpenProcess failed for PID 4321: WinError 6")),
                mock.patch.object(queue.unitylock, "remove_stale_lock") as remove_stale,
                mock.patch.object(queue.time, "sleep") as sleep,
            ):
                with self.assertRaisesRegex(queue.QueueError, "PID 4321.*WinError 6"):
                    queue.acquire_unity_lock("fixture", wait_s=3600)

            sleep.assert_not_called()
            remove_stale.assert_not_called()
            self.assertTrue(lock.is_dir())
            self.assertTrue((lock / "owner.json").is_file())

    def test_missing_owner_after_grace_fails_without_polling_or_mutation(self):
        with workspace_tempdir(__file__) as temp_root:
            lock = Path(temp_root) / "ownerless-lock"
            lock.mkdir()
            old_time = max(1.0, queue.time.time() - queue.unitylock.LOCK_OWNER_GRACE_S - 1.0)
            queue.os.utime(lock, (old_time, old_time))
            before = sorted(path.name for path in lock.iterdir())
            with (
                mock.patch.object(queue.unitylock, "LOCK", str(lock)),
                mock.patch.object(queue.time, "sleep") as sleep,
            ):
                with self.assertRaisesRegex(queue.QueueError, "no owner.json after"):
                    queue.acquire_unity_lock("fixture", wait_s=3600)

            sleep.assert_not_called()
            self.assertTrue(lock.is_dir())
            self.assertFalse((lock / "owner.json").exists())
            self.assertEqual(sorted(path.name for path in lock.iterdir()), before)

    def test_missing_owner_within_grace_caps_wait_to_remaining_window(self):
        with workspace_tempdir(__file__) as temp_root:
            lock = Path(temp_root) / "ownerless-lock"
            lock.mkdir()
            grace = queue.unitylock.LOCK_OWNER_GRACE_S
            first_now = 100.0
            old_time = first_now - grace + 0.5
            queue.os.utime(lock, (old_time, old_time))
            delays = []

            def no_wait(delay):
                delays.append(delay)

            with (
                mock.patch.object(queue.unitylock, "LOCK", str(lock)),
                mock.patch.object(queue.time, "time", side_effect=[first_now, first_now + 1.0]),
                mock.patch.object(queue.time, "sleep", side_effect=no_wait),
                mock.patch.object(queue.random, "uniform", return_value=5.0),
            ):
                with self.assertRaisesRegex(queue.QueueError, "no owner.json after"):
                    queue.acquire_unity_lock("fixture", wait_s=3600)

            self.assertEqual(len(delays), 1)
            self.assertGreater(delays[0], 0)
            self.assertLessEqual(delays[0], 0.5 + 0.001)
            self.assertTrue(lock.is_dir())
            self.assertFalse((lock / "owner.json").exists())

    def test_lock_held_preflight_refusal_finishes_and_releases_without_launch(self):
        pending = FakeQueueDir([FakeEntry("job-a")])
        events = []
        lock_held = False
        refused_job = job()

        def acquire(*_args, **_kwargs):
            nonlocal lock_held
            lock_held = True
            events.append("lock")
            return True

        def preflight(*_args, **_kwargs):
            self.assertTrue(lock_held)
            events.append("fresh-preflight")
            return "launch_guard refused"

        def finish(_job, _state, result, _log):
            events.append("refuse")
            return {"id": _job["id"], **result}

        def release():
            nonlocal lock_held
            events.append("release")
            lock_held = False

        with (
            mock.patch.object(queue, "qdir", return_value=pending),
            mock.patch.object(queue, "wait_for_capacity", return_value=capacity_ready()),
            mock.patch.object(queue, "acquire_unity_lock", side_effect=acquire),
            mock.patch.object(queue, "recover_orphans"),
            mock.patch.object(queue, "claim_pending", return_value=[refused_job]),
            mock.patch.object(queue, "fingerprint_input", side_effect=AssertionError("no inputs to hash")),
            mock.patch.object(queue, "preflight", side_effect=preflight),
            mock.patch.object(queue, "finish", side_effect=finish),
            mock.patch.object(queue.subprocess, "Popen", side_effect=AssertionError("refused launch started")),
            mock.patch.object(queue, "release_unity_lock", side_effect=release),
        ):
            queue.drain_once(capacity_wait_s=30)

        self.assertEqual(events, ["lock", "fresh-preflight", "refuse", "release"])
        self.assertFalse(lock_held)

    def test_waiter_orphan_recovery_probes_each_pid_once_and_is_rate_limited(self):
        running = FakeQueueDir([FakeEntry("job-a"), FakeEntry("job-b"), FakeEntry("job-c")])
        jobs = {
            "job-a": {"id": "job-a", "claim": {"pid": 4321}},
            "job-b": {"id": "job-b", "claim": {"pid": 4321}},
            "job-c": {"id": "job-c", "claim": {"pid": 9876}},
        }
        clock = {"tick": 100.0}
        results = [None, None, {"id": "job-a", "status": "ok"}]
        root = FakeQueueRoot({("running", "job-a.json")})
        with (
            mock.patch.object(queue, "QUEUE_ROOT", root),
            mock.patch.object(queue, "qdir", return_value=running) as qdir,
            mock.patch.object(queue, "load", side_effect=lambda path: jobs[path.stem]),
            mock.patch.object(queue, "result", side_effect=results),
            mock.patch.object(queue, "pid_alive", return_value=True) as alive,
            mock.patch.object(queue, "finish") as finish,
            mock.patch.object(queue, "now", return_value=100.0),
            mock.patch.object(queue.time, "monotonic", side_effect=lambda: clock["tick"]),
            mock.patch.object(queue.time, "sleep", side_effect=lambda _s: clock.__setitem__("tick", clock["tick"] + 1)),
            mock.patch.object(queue, "_last_orphan_recovery", 0.0),
        ):
            result = queue.wait_for("job-a", timeout_s=30, drain=False)

        self.assertEqual(result["status"], "ok")
        self.assertEqual(alive.call_args_list, [mock.call(4321), mock.call(9876)])
        self.assertEqual(finish.call_count, 0)
        self.assertEqual(qdir.call_args_list, [mock.call("running")])

    def test_orphan_probe_error_fails_without_finishing_or_changing_running_job(self):
        running = FakeQueueDir([FakeEntry("job-a")])
        active_job = {"id": "job-a", "claim": {"pid": 4321}}
        with (
            mock.patch.object(queue, "qdir", return_value=running),
            mock.patch.object(queue, "load", return_value=active_job),
            mock.patch.object(queue, "pid_alive", side_effect=queue.unitylock.ProcessProbeError(
                "OpenProcess failed for PID 4321: WinError 6")),
            mock.patch.object(queue, "finish") as finish,
            mock.patch.object(queue, "_last_orphan_recovery", 0.0),
        ):
            with self.assertRaisesRegex(queue.QueueError, "no orphan recovery.*WinError 6"):
                queue.recover_orphans(force=True)

        finish.assert_not_called()
        self.assertEqual([entry.name for entry in running.entries], ["job-a.json"])

    def test_cold_library_refuses_jobs_but_not_the_warmup(self):
        with workspace_tempdir(__file__) as temp_root:
            root = Path(temp_root)
            project, launches = root / "proj", root / "q" / "launches"
            for d in (project / "Library" / "ArtifactDB", project / "Library" / "SourceAssetDB", launches / "a",
                      launches / "b"):
                d.mkdir(parents=True)
            head = f"COMMAND LINE ARGUMENTS:\nUnity.exe\n-nographics\n-projectPath\n{project}\n"
            (launches / "a" / "unity.log").write_text(head + queue.INITIAL_REFRESH_END + "\n", encoding="utf-8")
            with mock.patch.object(queue, "QUEUE_ROOT", root / "q"):
                self.assertIsNone(queue.library_cold(str(project)))
                (launches / "b" / "unity.log").write_text(
                    head + "Message: Failed to write the asset file 'Assets/x.glb'\n", encoding="utf-8")
                self.assertIn("no completed refresh", queue.library_cold(str(project)))
                with mock.patch.object(queue, "free_gb", return_value=50.0):
                    self.assertIn("run the warm-up job", queue.library_refusal(str(project), "P", warmup=False))
                    self.assertIsNone(queue.library_refusal(str(project), "P", warmup=True))
                with mock.patch.object(queue, "free_gb", return_value=queue.WARMUP_MIN_FREE_GB - 1):
                    self.assertIn("warm-up needs", queue.library_refusal(str(project), "P", warmup=True))
                (launches / "b" / "unity.log").write_text(head + queue.INITIAL_REFRESH_END + "\n", encoding="utf-8")
                self.assertIsNone(queue.library_cold(str(project)))
                (project / queue.LIBRARY_WIPED_MARKER).write_text("", encoding="utf-8")
                self.assertIn("wipe marker", queue.library_cold(str(project)))
                (project / queue.LIBRARY_WIPED_MARKER).unlink()
                (project / "Library" / "SourceAssetDB").rmdir()
                self.assertIn("SourceAssetDB", queue.library_cold(str(project)))


if __name__ == "__main__":
    unittest.main()
