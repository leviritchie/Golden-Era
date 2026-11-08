"""Tests for the source-mesh stamp (tools/homm3_def_retarget/source_mesh.py) and the freeze/ship identity rule
(source_mesh_identity.py).  python tools/homm3_def_retarget_delivery/test_source_mesh_identity.py"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import source_mesh_identity as S  # noqa: E402
from source_mesh_identity import source_mesh as SM  # noqa: E402


def glb_bytes(uv: np.ndarray, extras: dict | None = None) -> bytes:
    n = len(uv)
    pos = np.zeros((n, 3), "<f4").tobytes()
    tex = uv.astype("<f4").tobytes()
    binb = pos + tex
    js = {"asset": {"version": "2.0", **({"extras": extras} if extras else {})},
          "buffers": [{"byteLength": len(binb)}],
          "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(pos)},
                          {"buffer": 0, "byteOffset": len(pos), "byteLength": len(tex)}],
          "accessors": [{"bufferView": 0, "componentType": 5126, "count": n, "type": "VEC3"},
                        {"bufferView": 1, "componentType": 5126, "count": n, "type": "VEC2"}],
          "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "TEXCOORD_0": 1}}]}],
          "nodes": [{"name": "u", "mesh": 0}]}
    j = json.dumps(js).encode()
    j += b" " * (-len(j) % 4)
    out = struct.pack("<III", 0x46546C67, 2, 0) + struct.pack("<II", len(j), 0x4E4F534A) + j \
        + struct.pack("<II", len(binb), 0x004E4942) + binb
    return out[:8] + struct.pack("<I", len(out)) + out[12:]


UV_A = np.array([[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]])
UV_B = np.array([[0.7, 0.2], [0.3, 0.9], [0.5, 0.1]])
SHA_R, SHA_X = "a" * 64, "b" * 64


def stamp(path: str, sha: str) -> dict:
    return {SM.STAMP: {"schema": SM.SCHEMA, "path": path, "sha256": sha}}


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._root = S.ROOT
        S.ROOT = self.root
        own = self.root / S.own_mesh("h3_free")
        own.parent.mkdir(parents=True)
        own.write_bytes(b"own mesh bytes")
        self.own_sha = SM.file_sha256(own)
        self.reviews = {"h3_rev": {"status": "verified_correct", "meshSha256": SHA_R},
                        "h3_split": {"status": "verified_correct", "meshSha256": SHA_X,
                                     "defRetargetMesh": {"status": "verified_correct", "sha256": SHA_R}}}

    def tearDown(self):
        S.ROOT = self._root
        self.tmp.cleanup()

    def glb(self, uv, extras=None) -> Path:
        p = self.root / f"g{len(list(self.root.glob('g*.glb')))}.glb"
        p.write_bytes(glb_bytes(uv, extras))
        return p

    def attest(self, unit, glb, legacy=None):
        return S.attest(unit, glb, self.reviews, legacy or {})


class StampedRule(Base):
    def test_reviewed_match(self):
        g = self.glb(UV_A, stamp(S.own_mesh("h3_rev"), SHA_R))
        self.assertEqual(self.attest("h3_rev", g), {"sourceMeshSha256": SHA_R, "identityReview": SHA_R})

    def test_reviewed_mismatch_refuses(self):
        g = self.glb(UV_A, stamp(S.own_mesh("h3_rev"), SHA_X))
        with self.assertRaisesRegex(S.IdentityError, "review's meshSha256.*rebuild"):
            self.attest("h3_rev", g)

    def test_def_retarget_review_field_wins(self):
        self.assertEqual(self.attest("h3_split", self.glb(UV_A, stamp(S.own_mesh("h3_split"), SHA_R)))["identityReview"], SHA_R)
        with self.assertRaises(S.IdentityError):
            self.attest("h3_split", self.glb(UV_A, stamp(S.own_mesh("h3_split"), SHA_X)))

    def test_superseded_refuses(self):
        g = self.glb(UV_A, stamp(f"{S.MESHY}/{S.SUPERSEDED}/h3_rev_smartrigged.x.glb", SHA_R))
        with self.assertRaisesRegex(S.IdentityError, "superseded"):
            self.attest("h3_rev", g)

    def test_unreviewed_own_current_file(self):
        g = self.glb(UV_A, stamp(S.own_mesh("h3_free"), self.own_sha))
        self.assertEqual(self.attest("h3_free", g), {"sourceMeshSha256": self.own_sha, "identityReview": "none"})

    def test_unreviewed_other_file_or_replaced_file_refuses(self):
        with self.assertRaisesRegex(S.IdentityError, "not artifacts/meshy_downloads/h3_free"):
            self.attest("h3_free", self.glb(UV_A, stamp(S.own_mesh("h3_wolf"), self.own_sha)))
        with self.assertRaisesRegex(S.IdentityError, "current artifacts/meshy_downloads/h3_free"):
            self.attest("h3_free", self.glb(UV_A, stamp(S.own_mesh("h3_free"), SHA_X)))

    def test_bad_stamp_refuses(self):
        with self.assertRaises(S.IdentityError):
            self.attest("h3_rev", self.glb(UV_A, {SM.STAMP: {"schema": "old"}}))


class LegacyRule(Base):
    def legacy(self, unit, uv, sha):
        js, b = S.read_glb(self.glb(uv))
        return {unit: {"uvSetSha256": S.uv_set_sha256(js, b), "sourceMeshSha256": sha}}

    def test_unstamped_not_listed_refuses(self):
        with self.assertRaisesRegex(S.IdentityError, "no homm3DefRetargetSourceMesh stamp"):
            self.attest("h3_rev", self.glb(UV_A))

    def test_unstamped_same_build_passes(self):
        leg = self.legacy("h3_rev", UV_A, SHA_R)
        self.assertEqual(self.attest("h3_rev", self.glb(UV_A[::-1]), leg)["sourceMeshSha256"], SHA_R)

    def test_unstamped_other_mesh_refuses(self):
        with self.assertRaisesRegex(S.IdentityError, "UV set"):
            self.attest("h3_rev", self.glb(UV_B), self.legacy("h3_rev", UV_A, SHA_R))

    def test_legacy_entry_still_checked_against_review(self):
        with self.assertRaisesRegex(S.IdentityError, "review"):
            self.attest("h3_rev", self.glb(UV_A), self.legacy("h3_rev", UV_A, SHA_X))


class StampSurvives(unittest.TestCase):
    """The stamp export_glb.py writes must survive the in-place GLB editors downstream (glbpatch.Glb: look, emphasis
    deliver; stride_match_glb.Glb: stride, ground, low-pass, densify, prop floor; deyaw re-serialises the same JSON)."""

    def test_write_and_round_trips(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "x.glb"
            p.write_bytes(glb_bytes(UV_A, {"homm3DefRetargetEmphasis": {"k": 1}}))
            st = {"schema": SM.SCHEMA, "path": "artifacts/meshy_downloads/u_smartrigged.glb", "sha256": SHA_R}
            SM.write_glb_stamp(str(p), st)
            js, b = S.read_glb(p)
            self.assertEqual(SM.glb_stamp(js), st)
            self.assertIn("homm3DefRetargetEmphasis", js["asset"]["extras"])
            self.assertEqual(b, S.read_glb(Path(t) / "x.glb")[1])
            self.assertEqual(struct.unpack_from("<I", p.read_bytes(), 8)[0], p.stat().st_size)
            sys.path.insert(0, str(S.ROOT / "tools/homm3_unit_look"))
            import glbpatch
            from stride_match_glb import Glb as StrideGlb
            for cls in (glbpatch.Glb, StrideGlb):
                g = cls(p.read_bytes())
                g.json["asset"]["extras"]["later"] = 1
                self.assertEqual(SM.glb_stamp(cls(g.to_bytes()).json), st, cls)


class LegacyListOnlyShrinks(unittest.TestCase):
    def test_subset_of_first_commit(self):
        rel = S.LEGACY.relative_to(S.ROOT).as_posix()
        first = subprocess.run(["git", "-C", str(S.ROOT), "log", "--diff-filter=A", "--format=%H", "--", rel],
                               capture_output=True, text=True, check=True).stdout.split()
        if not first:
            self.skipTest(f"{rel} not committed yet")
        orig = json.loads(subprocess.run(["git", "-C", str(S.ROOT), "show", f"{first[-1]}:{rel}"],
                                         capture_output=True, text=True, check=True).stdout)["units"]
        now = S.load_legacy()
        grown = sorted(u for u in now if u not in orig or now[u] != orig[u])
        self.assertEqual(grown, [], f"{rel} may only lose entries; added or changed: {grown}")


if __name__ == "__main__":
    unittest.main()
