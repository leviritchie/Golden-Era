"""prune_superseded: a graded stamp keeps exactly its sourceGlbSha256 original and fails closed without it; a
rawAccepted stamp (the delivered GLB is the un-prebaked GLB, superseded: None) keeps none and prunes, but only while the
delivered GLB is the stamped one. 2026-09-28 h3_ghost_dragon: accept-raw passed, then this prune refused (rc 5)
looking for a superseded original a rawAccepted stamp never names, and fleet_rebuild rolled the unit back.

    python -m unittest tools/homm3_unit_look/test_prune_superseded.py
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import look as L  # noqa: E402

S = L.S
U = "u_test"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


class PruneSuperseded(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.out = root / U
        self.sup = self.out / S.SUPERSEDED
        self.sup.mkdir(parents=True)
        self.glb = root / f"{U}.glb"
        self.old = {n: self.sup / f"{n}{S.UNPREBAKED_EXT}" for n in ("aaa", "bbb")}
        for n, p in self.old.items():
            p.write_bytes(n.encode())
        self.stamp = None
        self.patches = [patch.object(S, "out_dir", lambda u: self.out), patch.object(S, "glb_path", lambda u: self.glb),
                        patch.object(L, "read_stamp", lambda u: self.stamp), patch.object(L, "stamp_validates", lambda u: True),
                        patch.object(L, "superseded_path", lambda u, s: self.sup / f"{s}{S.UNPREBAKED_EXT}")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def raw(self, **kw):
        self.glb.write_bytes(b"raw delivery")
        self.stamp = dict({"kind": S.RAW_ACCEPTED, "sourceGlbSha256": sha(b"raw delivery"),
                           "deliveredGlbSha256": sha(b"raw delivery"), "superseded": None}, **kw)

    def test_a_raw_accepted_unit_prunes_every_superseded_original(self):
        self.raw()
        self.assertEqual(L.prune_superseded([U]), 0)
        self.assertEqual(list(self.sup.iterdir()), [])

    def test_a_raw_accepted_unit_whose_glb_is_not_the_stamped_one_is_left_untouched(self):
        self.raw()
        self.glb.write_bytes(b"edited after accept-raw")
        self.assertEqual(L.prune_superseded([U]), 5)
        self.assertTrue(all(p.is_file() for p in self.old.values()))

    def test_a_raw_accepted_stamp_naming_a_superseded_original_is_left_untouched(self):
        self.raw(superseded="aaa")
        self.assertEqual(L.prune_superseded([U]), 5)
        self.assertTrue(all(p.is_file() for p in self.old.values()))

    def test_a_graded_unit_keeps_its_stamped_original_and_fails_closed_without_it(self):
        keep = self.sup / f"{sha(b'aaa')}{S.UNPREBAKED_EXT}"
        keep.write_bytes(b"aaa")
        self.stamp = {"kind": "graded", "sourceGlbSha256": sha(b"aaa")}
        self.assertEqual(L.prune_superseded([U]), 0)
        self.assertEqual(list(self.sup.iterdir()), [keep])
        keep.unlink()
        self.old["bbb"].write_bytes(b"bbb")
        self.assertEqual(L.prune_superseded([U]), 5)
        self.assertTrue(self.old["bbb"].is_file())


if __name__ == "__main__":
    unittest.main()
