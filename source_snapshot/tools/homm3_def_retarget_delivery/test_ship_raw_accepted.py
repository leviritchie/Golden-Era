"""Frozen rawAccepted provenance must survive the ship path, not only the look/freeze stages.

    python -m unittest tools/homm3_def_retarget_delivery/test_ship_raw_accepted.py
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import struct
import sys
import unittest
import uuid
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import ship_def_retarget_slice as S  # noqa: E402
sys.path.insert(0, str(S.ROOT / "tools"))
import validate_homm3_def_retarget_delivery_contract as V  # noqa: E402


class FrozenRawAcceptedTest(unittest.TestCase):
    def setUp(self):
        scratch = S.ROOT / "artifacts/homm3_def_retarget_delivery/_articulation"
        scratch.mkdir(parents=True, exist_ok=True)
        self.root = scratch / f"test_raw_ship_{uuid.uuid4().hex}"
        self.root.mkdir()
        self.addCleanup(shutil.rmtree, self.root)
        png = io.BytesIO()
        Image.new("RGBA", (1, 1), (17, 42, 70, 255)).save(png, format="PNG")
        self.image = png.getvalue()
        self.sha = hashlib.sha256(self.image).hexdigest()
        js = {"bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": len(self.image)}],
              "images": [{"bufferView": 0, "mimeType": "image/png"}],
              "textures": [{"source": 0}],
              "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}],
              "accessors": [{"count": 1}],
              "meshes": [{"primitives": [{"attributes": {"POSITION": 0}, "material": 0}]}]}
        j = json.dumps(js).encode()
        j += b" " * (-len(j) % 4)
        b = self.image + b"\0" * (-len(self.image) % 4)
        self.glb = self.root / "look_delivered.glb"
        self.glb.write_bytes(struct.pack("<III", 0x46546C67, 2, 28 + len(j) + len(b)) +
                             struct.pack("<II", len(j), 0x4E4F534A) + j +
                             struct.pack("<II", len(b), 0x004E4942) + b)
        self.stamp = {"schema": "homm3_unit_look_stamp.v1", "unit": "unit",
                      "kind": "rawAccepted", "basecolorFile": "raw_basecolor.png",
                      "sourceGlbSha256": "source", "deliveredGlbSha256": "source",
                      "rawAccepted": {"reason": "Both graded modes increase the body L-hist error on this GLB",
                                      "rawLhistBody": 2.0,
                                      "modesTried": {"v7c": {"lhistBody": 3.0}, "v6m": {"lhistBody": 4.0}}}}
        self.stamp_path = self.root / "stamp.json"
        self.stamp_path.write_text(json.dumps(self.stamp))

    def test_valid_frozen_raw_image(self):
        S.verify_frozen_look_kind("unit", "unit", self.stamp, self.glb, self.sha, {"layers": {}})

    def test_missing_evidence_unknown_kind_and_atlas_refuse(self):
        self.stamp["rawAccepted"]["reason"] = ""
        with self.assertRaisesRegex(S.ShipError, "carries no reason"):
            S.verify_frozen_look_kind("unit", "unit", self.stamp, self.glb, self.sha, {"layers": {}})
        self.stamp["rawAccepted"]["reason"] = "Measured on the current source"
        del self.stamp["rawAccepted"]["modesTried"]["v6m"]
        with self.assertRaisesRegex(S.ShipError, "did not try mode"):
            S.verify_frozen_look_kind("unit", "unit", self.stamp, self.glb, self.sha, {"layers": {}})
        self.stamp["kind"] = "unknown"
        with self.assertRaisesRegex(S.ShipError, "unknown frozen look stamp kind"):
            S.verify_frozen_look_kind("unit", "unit", self.stamp, self.glb, self.sha, {"layers": {}})
        self.stamp["kind"] = "rawAccepted"
        self.stamp["rawAccepted"]["modesTried"]["v6m"] = {"lhistBody": 4.0}
        with self.assertRaisesRegex(S.ShipError, "not a uvAtlas"):
            S.verify_frozen_look_kind("unit", "unit", self.stamp, self.glb, self.sha,
                                      {"layers": {"grade": {"type": "uvAtlas"}}})

    def test_embedded_image_mismatch_refuses(self):
        with self.assertRaisesRegex(S.ShipError, "not the GLB's embedded body image"):
            S.verify_frozen_look_kind("unit", "unit", self.stamp, self.glb, "0" * 64, {"layers": {}})

    def test_nonfinite_score_or_wrong_source_unit_refuses(self):
        self.stamp["rawAccepted"]["rawLhistBody"] = float("nan")
        with self.assertRaisesRegex(S.ShipError, "finite raw body L-hist"):
            S.verify_frozen_look_kind("unit", "unit", self.stamp, self.glb, self.sha, {"layers": {}})
        self.stamp["rawAccepted"]["rawLhistBody"] = 2.0
        self.stamp["rawAccepted"]["modesTried"]["v7c"]["lhistBody"] = float("inf")
        with self.assertRaisesRegex(S.ShipError, "does not lose"):
            S.verify_frozen_look_kind("unit", "unit", self.stamp, self.glb, self.sha, {"layers": {}})
        self.stamp["rawAccepted"]["modesTried"]["v7c"]["lhistBody"] = 3.0
        self.stamp["unit"] = "another_unit"
        with self.assertRaisesRegex(S.ShipError, "differs from"):
            S.verify_frozen_look_kind("unit", "unit", self.stamp, self.glb, self.sha, {"layers": {}})
        self.stamp["unit"] = "unit"
        self.stamp["schema"] = "wrong"
        with self.assertRaisesRegex(S.ShipError, "schema must be"):
            S.verify_frozen_look_kind("unit", "unit", self.stamp, self.glb, self.sha, {"layers": {}})

    def test_jpeg_transcode_record(self):
        """A JPEG raw image ships as a pixel-identical PNG: allowed only with a complete rawTranscode record."""
        L = S.look_spec
        jpg = io.BytesIO()
        Image.new("RGB", (4, 4), (120, 60, 30)).save(jpg, format="JPEG")
        png = io.BytesIO()
        Image.open(io.BytesIO(jpg.getvalue())).save(png, format="PNG")
        self.assertEqual(L.image_pixels_sha256(jpg.getvalue()), L.image_pixels_sha256(png.getvalue()))
        tc = {"from": "image/jpeg", "sourceImageFile": L.RAW_SOURCE_IMAGE, "sourceImageSha256": "j" * 64,
              "pngSha256": self.sha, "pixelsSha256": "p" * 64}
        st = {**self.stamp, "basecolorSha256": self.sha, "deliveredGlbSha256": "transcoded", "rawTranscode": tc}
        self.assertEqual(L.raw_accepted_errors(st, "unit"), [])
        self.assertTrue(L.raw_accepted_errors({**st, "rawTranscode": None}, "unit"))       # shas differ, no record
        self.assertTrue(L.raw_accepted_errors({**st, "deliveredGlbSha256": "source"}, "unit"))   # nothing transcoded
        for k, bad in (("from", "image/webp"), ("pngSha256", "0" * 64), ("sourceImageFile", "x.jpg"),
                       ("pixelsSha256", "")):
            with self.subTest(field=k):
                self.assertTrue(L.raw_accepted_errors({**st, "rawTranscode": {**tc, k: bad}}, "unit"))

    def test_whole_stamp_pin_refuses_postfreeze_edit(self):
        frozen = {"lookStampSha256": S.sha(self.stamp_path)}
        S.verify_frozen_stamp_pin("unit", self.stamp, self.stamp_path, frozen)
        with self.assertRaisesRegex(S.ShipError, "no longer pinned"):
            S.verify_frozen_stamp_pin("unit", self.stamp, self.stamp_path, {})
        self.stamp_path.write_text(json.dumps({**self.stamp, "rawAccepted": {**self.stamp["rawAccepted"],
                                                                      "reason": "altered after freeze"}}))
        with self.assertRaisesRegex(S.ShipError, "changed"):
            S.verify_frozen_stamp_pin("unit", self.stamp, self.stamp_path, frozen)
        self.stamp["kind"] = None
        with self.assertRaisesRegex(S.ShipError, "changed"):
            S.verify_frozen_stamp_pin("unit", self.stamp, self.stamp_path, frozen)

    def test_normal_build_checks_raw_stamp_and_spec_pin(self):
        inp = self.root / "inputs"
        inp.mkdir()
        (inp / "stamp.json").write_text(json.dumps(self.stamp))
        spec = {"unit": "unit", "schema": "homm3_unit_look.v1"}
        (inp / "unit.json").write_text(json.dumps(spec))
        frozen = {"lookStampSha256": S.sha(inp / "stamp.json"),
                  "specSha256": S.canonical_sha(spec), "basecolorSha256": self.sha}
        self.stamp["basecolorSha256"] = self.sha
        (inp / "stamp.json").write_text(json.dumps(self.stamp))
        frozen["lookStampSha256"] = S.sha(inp / "stamp.json")
        errors = []
        V.raw_stamp_checks("selection", "unit", self.root, frozen, errors)
        self.assertEqual(errors, [])
        (inp / "stamp.json").write_text(json.dumps({**self.stamp, "unit": "wrong"}))
        errors = []
        V.raw_stamp_checks("selection", "unit", self.root, frozen, errors)
        self.assertTrue(any("stamp" in error for error in errors))

    def test_carryover_pin_check_refuses_changed_inputs_without_build_facts(self):
        out = self.root / "frozen"
        d = out / "unit"
        inp = d / "inputs"
        vfx = inp / "vfx"
        vfx.mkdir(parents=True)
        look = inp / "look_delivered.glb"
        shutil.copy2(self.glb, look)
        retimed = d / "delivered_idle_retimed.glb"
        shutil.copy2(self.glb, retimed)
        basecolor = inp / "basecolor.png"
        basecolor.write_bytes(self.image)
        effect = vfx / "effect.bin"
        effect.write_bytes(b"effect")
        manifest = vfx / "vfx_manifest.json"
        manifest.write_text(json.dumps({"layers": {}, "assets": {"effect.bin": S.sha(effect)}}))
        spec = inp / "unit.json"
        spec.write_text(json.dumps({"unit": "unit", "schema": "homm3_unit_look.v1"}))
        pins = {"lookDeliveredGlbSha256": S.sha(look), "idleRetimedGlbSha256": S.sha(retimed),
                "basecolorSha256": S.sha(basecolor), "vfxManifestSha256": S.sha(manifest),
                "specSha256": S.canonical_sha(S.load(spec))}
        self.stamp.update({"sourceGlbSha256": pins["lookDeliveredGlbSha256"],
                           "deliveredGlbSha256": pins["lookDeliveredGlbSha256"],
                           "basecolorSha256": pins["basecolorSha256"],
                           "vfxManifestSha256": pins["vfxManifestSha256"],
                           "specSha256": pins["specSha256"]})
        stamp = inp / "stamp.json"
        stamp.write_text(json.dumps(self.stamp))
        pins["lookStampSha256"] = S.sha(stamp)
        report = d / "idle_retime_report.json"
        report.write_text(json.dumps({"srcSha256": pins["lookDeliveredGlbSha256"],
                                      "dstSha256": pins["idleRetimedGlbSha256"],
                                      "treatment": {"factor": 1.0}}))
        selection = {"units": [{"labSid": "unit", "frozen": pins}]}
        self.assertEqual(S.verify_freeze(selection, out, pins_only=True), {})
        for path in (look, retimed, basecolor, manifest, spec, effect, stamp, report):
            original = path.read_bytes()
            with self.subTest(path=path.name):
                path.write_bytes(b"changed")
                with self.assertRaises((S.ShipError, ValueError)):
                    S.verify_freeze(selection, out, pins_only=True)
                path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
