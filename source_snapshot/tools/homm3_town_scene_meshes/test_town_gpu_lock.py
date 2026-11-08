"""Focused, no-GPU fixtures for the town GPU reservation order and capacity gate."""
from __future__ import annotations

import contextlib
import json
import os
import threading
import unittest
from pathlib import Path
from unittest import mock

import town_full3d_gpu as G
from test_tempdir import workspace_tempdir


class TownGpuGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = workspace_tempdir(__file__)
        self.addCleanup(self.tmp.cleanup)
        self.lock = Path(self.tmp.name) / "town-gpu-lock"
        self.lock_patcher = mock.patch.object(G, "LOCK", self.lock)
        self.lock_patcher.start()
        self.addCleanup(self.lock_patcher.stop)

    def patch_capacity(self, snapshots):
        snapshots = iter(snapshots)
        return mock.patch.object(G, "_capacity_snapshot", side_effect=lambda: next(snapshots))

    def test_margin_and_physical_feasibility_are_unchanged(self):
        self.assertGreaterEqual(G.VRAM_MARGIN_GB, 2.5)
        self.assertFalse(G.vram_ok(13.4, 11.0))
        self.assertTrue(G.vram_ok(13.5, 11.0))
        self.assertFalse(G.vram_ok(float("nan"), 11.0))
        with self.patch_capacity([(20.0, 32.0, 13.4, 16.0)]):
            self.assertIn("free RAM", G._capacity_problem(11.0))
        with self.patch_capacity([(20.0, 32.0, 13.5, 16.0)]):
            self.assertIsNone(G._capacity_problem(11.0))
        with self.patch_capacity([(20.0, 32.0, 16.0, 16.0)]):
            self.assertIn("impossible on this hardware", G._capacity_problem(14.0))
        with self.patch_capacity([(20.0, 4.0, 16.0, 16.0)]):
            self.assertIn("impossible on this hardware", G._capacity_problem(1.0))

    def test_impossible_request_refuses_before_any_reservation(self):
        with self.patch_capacity([(20.0, 32.0, 16.0, 16.0)]), \
             mock.patch.object(G.gpuslot, "reap_stale_slots") as reap, \
             mock.patch.object(G, "_take") as take, \
             mock.patch.object(G.gpuslot, "try_slot") as slot:
            with self.assertRaisesRegex(SystemExit, "impossible on this hardware"):
                with G.gate("fixture", need_vram_gb=14.0, wait_min=120):
                    self.fail("impossible capacity must not enter the gate")
        reap.assert_not_called()
        take.assert_not_called()
        slot.assert_not_called()

    def test_wait_precedes_reservations_and_recheck_uses_same_snapshot(self):
        events = []

        def snapshot():
            events.append("capacity")
            return 20.0, 32.0, 13.5, 16.0

        def take(tag):
            events.append("town-lock")
            self.lock.mkdir()
            (self.lock / "owner.json").write_text(json.dumps({"pid": G.os.getpid()}), encoding="utf-8")
            return True

        @contextlib.contextmanager
        def try_slot(*args, **kwargs):
            events.append("slot")
            yield "temporary-slot"
            events.append("slot-released")

        with mock.patch.object(G, "_capacity_snapshot", side_effect=snapshot), \
             mock.patch.object(G.gpuslot, "reap_stale_slots", side_effect=lambda: events.append("reap")), \
             mock.patch.object(G, "_take", side_effect=take), \
             mock.patch.object(G.gpuslot, "try_slot", side_effect=try_slot):
            with G.gate("fixture", need_vram_gb=11.0, wait_min=0):
                events.append("work")

        self.assertLess(events.index("capacity"), events.index("town-lock"))
        self.assertLess(events.index("town-lock"), events.index("slot"))
        self.assertLess(events.index("slot"), events.index("work"))
        self.assertEqual(2, events.count("capacity"))
        self.assertFalse(self.lock.exists())

    def test_lost_capacity_releases_both_reservations_before_retry(self):
        events = []
        snapshots = iter(((20.0, 32.0, 12.0, 16.0),))

        def snapshot():
            events.append("capacity")
            return next(snapshots)

        def take(tag):
            events.append("town-lock")
            self.lock.mkdir()
            (self.lock / "owner.json").write_text(json.dumps({"pid": G.os.getpid()}), encoding="utf-8")
            return True

        def wait(*args):
            events.append("wait")
            if events.count("wait") == 2:
                self.assertFalse(self.lock.exists())
                self.assertIn("slot-released", events)
                raise SystemExit("fixture capacity unavailable")

        @contextlib.contextmanager
        def try_slot(*args, **kwargs):
            events.append("slot")
            try:
                yield "temporary-slot"
            finally:
                events.append("slot-released")

        with mock.patch.object(G, "_capacity_snapshot", side_effect=snapshot), \
             mock.patch.object(G, "_wait_for_capacity", side_effect=wait), \
             mock.patch.object(G.gpuslot, "reap_stale_slots"), \
             mock.patch.object(G, "_take", side_effect=take), \
             mock.patch.object(G.gpuslot, "try_slot", side_effect=try_slot), \
             mock.patch.object(G.time, "sleep"):
            with self.assertRaisesRegex(SystemExit, "fixture capacity unavailable"):
                with G.gate("fixture", need_vram_gb=11.0, wait_min=1):
                    self.fail("lost capacity must never yield")
        self.assertFalse(self.lock.exists())

    def test_probe_failure_refuses_before_reserving(self):
        with mock.patch.object(G.memgate, "memory_gb", side_effect=G.memgate.ProbeError("fixture failure")), \
             mock.patch.object(G.gpuslot, "reap_stale_slots") as reap, \
             mock.patch.object(G, "_take") as take:
            with self.assertRaisesRegex(SystemExit, "memgate probe failed"):
                with G.gate("fixture", need_vram_gb=11.0, wait_min=120):
                    self.fail("probe failure must refuse")
        reap.assert_not_called()
        take.assert_not_called()

    def test_corrupt_town_owner_fails_fast_and_preserves_lock(self):
        self.lock.mkdir()
        (self.lock / "owner.json").write_text("{not-json", encoding="utf-8")
        with self.assertRaisesRegex(G.gpuslot.SlotMetadataError, "owner.json"):
            G._reap_stale_town_lock()
        self.assertTrue(self.lock.is_dir())

    def test_unknown_owner_pid_probe_fails_fast_without_reaping_town_lock(self):
        self.lock.mkdir()
        owner = {"pid": 4321, "created": 123, "tag": "held"}
        (self.lock / "owner.json").write_text(json.dumps(owner), encoding="utf-8")
        with mock.patch.object(G.gpuslot, "_process_state", side_effect=G.gpuslot.SlotProcessProbeError(
                "OpenProcess failed for PID 4321: WinError 6")), \
             mock.patch.object(G.time, "sleep") as sleep:
            with self.assertRaisesRegex(G.gpuslot.SlotProcessProbeError, "WinError 6"):
                G._reap_stale_town_lock()
        sleep.assert_not_called()
        self.assertTrue(self.lock.is_dir())
        self.assertEqual(json.loads((self.lock / "owner.json").read_text(encoding="utf-8")), owner)

    def test_town_acquisition_rejects_own_pid_not_alive_and_cleans_partial_lock(self):
        with mock.patch.object(G, "_creation_time", return_value=("gone", None)):
            with self.assertRaisesRegex(G.gpuslot.SlotProcessProbeError, "was not confirmed alive"):
                G._take("fixture")
        self.assertFalse(self.lock.exists())

    def test_invalid_capacity_snapshot_fails_closed(self):
        with mock.patch.object(G.memgate, "memory_gb", return_value=(float("nan"), 32.0)), \
             mock.patch.object(G.memgate, "vram_gb", return_value=(8.0, 16.0)):
            with self.assertRaisesRegex(SystemExit, "invalid capacity snapshot"):
                G._capacity_snapshot()

    def test_second_town_lock_reaper_cannot_delete_replacement_owner(self):
        self.lock.mkdir()
        (self.lock / "owner.json").write_text(json.dumps({"pid": 123, "created": 1, "tag": "old"}),
                                               encoding="utf-8")
        entered_delete = threading.Event()
        finish_delete = threading.Event()
        real_rmtree = G.shutil.rmtree
        results = []

        def replace_during_delete(path, **kwargs):
            real_rmtree(path, **kwargs)
            Path(path).mkdir()
            (Path(path) / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "created": 2, "tag": "new"}), encoding="utf-8")
            entered_delete.set()
            if not finish_delete.wait(3):
                raise RuntimeError("test did not release town lock reaper")

        with mock.patch.object(G, "STALE_CONFIRM_S", 0), \
             mock.patch.object(G, "holder_state", return_value="gone"), \
             mock.patch.object(G.shutil, "rmtree", side_effect=replace_during_delete):
            first = threading.Thread(target=lambda: results.append(G._reap_stale_town_lock()))
            first.start()
            self.assertTrue(entered_delete.wait(3))
            second = threading.Thread(target=lambda: results.append(G._reap_stale_town_lock()))
            second.start()
            second.join(3)
            self.assertFalse(second.is_alive())
            finish_delete.set()
            first.join(3)
            self.assertFalse(first.is_alive())

        self.assertEqual(2, len(results))
        self.assertTrue(self.lock.is_dir())
        self.assertEqual("new", G.gpuslot.owner(str(self.lock))["tag"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
