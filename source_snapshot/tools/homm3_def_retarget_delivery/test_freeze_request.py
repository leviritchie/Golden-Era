"""A freeze request must resolve each lab sid once before mutating frozen inputs."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tempfile  # noqa: E402

from fleet_census import sha  # noqa: E402
from freeze_slice import hold_prior, merge_selection, release_prior, restore_prior, selection_docs, sweep_pinned, validate_request  # noqa: E402


class FreezeRequestTest(unittest.TestCase):
    def test_new_and_carried_labs_are_distinct(self):
        old = [{"labSid": "existing"}]
        validate_request(["source:new"], [], old)
        validate_request(["source:new"], ["existing"], old)

    def test_duplicate_normalized_or_drop_overlap_refuses(self):
        old = [{"labSid": "existing"}]
        with self.assertRaisesRegex(SystemExit, "duplicate requested lab sid"):
            validate_request(["existing", "another:existing"], [], old)
        with self.assertRaisesRegex(SystemExit, "cannot freeze and --drop"):
            validate_request(["another:existing"], ["existing"], old)
        with self.assertRaisesRegex(SystemExit, "not in the existing selection"):
            validate_request(["new"], ["new"], old)


class SelectionRewriteTest(unittest.TestCase):
    def test_unowned_top_level_keys_survive_a_rewrite(self):
        old = {"schema": "s.v1", "slice": "x", "supersededBy": "y_slice_v1", "supersededNote": "why",
               "note": "old note", "units": [{"labSid": "a"}], "custom": {"k": 1}}
        owned = {"schema": "s.v1", "slice": "x", "note": "new note", "units": [{"labSid": "b"}]}
        got = merge_selection(old, owned)
        self.assertEqual(got["supersededBy"], "y_slice_v1")
        self.assertEqual(got["supersededNote"], "why")
        self.assertEqual(got["custom"], {"k": 1})
        self.assertEqual(got["note"], "new note")
        self.assertEqual(got["units"], [{"labSid": "b"}])
        self.assertEqual(list(got)[:4], ["schema", "slice", "supersededBy", "supersededNote"])

    def test_new_selection_is_the_owned_keys(self):
        owned = {"schema": "s.v1", "units": []}
        self.assertEqual(merge_selection({}, owned), owned)


class FreezeTransactionTest(unittest.TestCase):
    """A refused freeze must give every requested unit its prior frozen folder back byte for byte."""

    def test_refused_run_restores_prior_and_removes_partial(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "old" / "inputs").mkdir(parents=True)
            (out / "old" / "inputs" / "look_delivered.glb").write_bytes(b"prior")
            held = hold_prior(out, ["old", "fresh"])
            self.assertFalse((out / "old").exists())
            (out / "old" / "inputs").mkdir(parents=True)
            (out / "old" / "inputs" / "look_delivered.glb").write_bytes(b"partial")
            (out / "fresh").mkdir()
            restore_prior(out, ["old", "fresh"], held)
            self.assertEqual((out / "old" / "inputs" / "look_delivered.glb").read_bytes(), b"prior")
            self.assertFalse((out / "fresh").exists())
            self.assertFalse((out / "old.prior_freeze").exists())

    def test_leftover_prior_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "old.prior_freeze").mkdir()
            with self.assertRaisesRegex(SystemExit, "interrupted freeze"):
                hold_prior(out, ["old"])


class ReleasePriorTest(unittest.TestCase):
    """After a good freeze a superseded folder is freed only when no selection still pins it."""

    OUT = "artifacts/homm3_def_retarget_delivery/s_v1"

    def prior(self, tmp: str) -> tuple[Path, str]:
        prev = Path(tmp) / "u.prior_freeze"
        (prev / "inputs").mkdir(parents=True)
        (prev / "delivered_idle_retimed.glb").write_bytes(b"idle")
        (prev / "inputs" / "look_delivered.glb").write_bytes(b"look")
        return prev, sha(prev / "delivered_idle_retimed.glb")

    def test_unpinned_is_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev, _ = self.prior(tmp)
            docs = [("HEAD:s_v1.json", {"out": self.OUT, "units": [{"labSid": "u", "frozen": {
                "idleRetimedGlbSha256": "other"}}]})]
            release_prior(self.OUT, "u", prev, docs)
            self.assertFalse(prev.exists())

    def test_same_out_row_pinning_a_prior_sha_keeps_it_aside(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev, idle = self.prior(tmp)
            docs = [("HEAD:s_v1.json", {"out": self.OUT, "units": [{"labSid": "u", "frozen": {
                "idleRetimedGlbSha256": idle}}]})]
            release_prior(self.OUT, "u", prev, docs)
            self.assertFalse(prev.exists())
            self.assertTrue((Path(tmp) / f"u.pinned_{idle[:12]}" / "delivered_idle_retimed.glb").is_file())

    def test_other_selection_naming_the_folder_keeps_it_aside(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev, idle = self.prior(tmp)
            docs = [("worktree:t_v1.json", {"out": "artifacts/x/t_v1", "note": f"reuses {self.OUT}/u"})]
            release_prior(self.OUT, "u", prev, docs)
            self.assertTrue((Path(tmp) / f"u.pinned_{idle[:12]}").is_dir())

    def test_unreadable_selections_keep_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            prev, _ = self.prior(tmp)
            release_prior(self.OUT, "u", prev, None)
            self.assertTrue(prev.is_dir())

    def test_pinned_folder_is_swept_once_unpinned(self):
        with tempfile.TemporaryDirectory() as tmp:
            delivery = Path(tmp) / "delivery"
            prev = delivery / "s_v1" / "u.prior_freeze"
            (prev / "inputs").mkdir(parents=True)
            (prev / "delivered_idle_retimed.glb").write_bytes(b"idle")
            (prev / "inputs" / "look_delivered.glb").write_bytes(b"look")
            idle = sha(prev / "delivered_idle_retimed.glb")
            pinning = [("HEAD:s_v1.json", {"out": self.OUT, "units": [{"labSid": "u", "frozen": {
                "idleRetimedGlbSha256": idle}}]})]
            release_prior(self.OUT, "u", prev, pinning)
            pinned = delivery / "s_v1" / f"u.pinned_{idle[:12]}"
            self.assertTrue(pinned.is_dir())
            other = delivery / "t_v1" / "v.pinned_abc"
            other.mkdir(parents=True)
            by_path = [("worktree:x_v1.json", {"out": "artifacts/x/x_v1",
                                               "note": "reuses artifacts/homm3_def_retarget_delivery/t_v1/v"})]
            # Still pinned: nothing goes; selections unreadable: nothing goes.
            self.assertEqual(sweep_pinned(delivery, pinning + by_path), [])
            self.assertEqual(sweep_pinned(delivery, None), [])
            self.assertTrue(pinned.is_dir() and other.is_dir())
            # A later freeze moved the row on: the folder pinned by sha goes, the one named by path stays.
            moved = [("HEAD:s_v1.json", {"out": self.OUT, "units": [{"labSid": "u", "frozen": {
                "idleRetimedGlbSha256": "newer"}}]})]
            self.assertEqual(sweep_pinned(delivery, moved + by_path), [pinned])
            self.assertFalse(pinned.exists())
            self.assertTrue(other.is_dir())
            # A freeze of s_v1 never sweeps another slice's pins.
            self.assertEqual(sweep_pinned(delivery, moved, only="s_v1"), [])
            self.assertTrue(other.is_dir())
            self.assertEqual(sweep_pinned(delivery, moved), [other])

    def test_live_selections_load(self):
        docs = selection_docs()
        self.assertIsNotNone(docs)
        self.assertTrue(any(label.startswith("HEAD:") for label, _ in docs))


if __name__ == "__main__":
    unittest.main()
