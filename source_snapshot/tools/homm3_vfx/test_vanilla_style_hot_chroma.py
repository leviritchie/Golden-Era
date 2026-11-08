"""Focused test: the hot_chroma emission mask rule selects painted hot spots only, and on the delivered h3_fire_hound it
lands on the heads (eyes / mouth), not on the body at large.

    python tools/homm3_vfx/test_vanilla_style_hot_chroma.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vanilla_style_fx as vs  # noqa: E402
from glb_io import Glb  # noqa: E402

UNIT = "h3_fire_hound"
HEADS = ("HeadLeft", "HeadRight", "Head")
HEAD_RADIUS = 0.45     # model units around each head joint; the hound's snouts end inside it
MIN_HEAD_SHARE = 0.9   # measured 0.95 on the 2026-09-28 delivery
RASTER = 512


def emission_layer(spec):
    return next(l for l in spec["layers"] if l["type"] == "emissionMap")


def joint_positions(glb_path):
    g = Glb(glb_path)
    skin = g.json["skins"][0]
    ibm = g.accessor(skin["inverseBindMatrices"]).reshape(-1, 4, 4)
    return {g.json["nodes"][j]["name"]: np.linalg.inv(m.T)[:3, 3] for j, m in zip(skin["joints"], ibm)}


class HotChroma(unittest.TestCase):
    LAYER = {"mask": {"rule": "hot_chroma", "warmLo": 0.45, "warmHi": 0.5, "satLo": 0.55, "satHi": 0.6,
                      "lumLo": 0.25, "lumHi": 0.3}}

    def test_saturated_hot_spot_in_warm_highlight_out(self):
        rgb = np.zeros((4, 4, 3), np.uint8)
        rgb[0, 0] = (255, 128, 14)    # DEF eye orange: selected
        rgb[0, 1] = (210, 150, 120)   # warm, bright, unsaturated body highlight: not selected
        rgb[0, 2] = (120, 30, 20)     # saturated but dark body red: not selected
        rgb[0, 3] = (40, 120, 255)    # cold: not selected
        with tempfile.TemporaryDirectory() as t:
            bc = Path(t) / "bc.png"
            Image.fromarray(rgb).save(bc)
            vs.build_emission("u", self.LAYER, {"basecolor": bc}, Path(t) / "e.png")
            m = np.asarray(Image.open(Path(t) / "e.png").convert("L")) / 255.0
        self.assertGreater(m[0, 0], 0.9)
        self.assertEqual(m[0, 1:].max(), 0.0)

    def test_fire_hound_glow_is_on_the_heads(self):
        spec = vs.load(vs.VS_DIR / "units" / f"{UNIT}.json")
        layer = emission_layer(spec)
        self.assertEqual(layer["mask"]["rule"], "hot_chroma")
        df = vs.delivery_facts(UNIT, spec)
        with tempfile.TemporaryDirectory() as t:
            stats = vs.build_emission(UNIT, layer, df, Path(t) / "e.png")
            m = np.asarray(Image.open(Path(t) / "e.png").convert("L")) / 255.0
        self.assertGreater(stats["coverage"], 0.0)
        self.assertIsNone(vs.emission_glow_error(UNIT, layer["id"], layer, stats))
        # the mask's texels, counted per raster cell and located on the bind-pose mesh
        n = m.shape[0] // RASTER
        count = (m > 0.05).reshape(RASTER, n, RASTER, n).sum(axis=(1, 3))
        pos, cov = vs.raster_positions(df["glb"], (RASTER, RASTER))
        count = np.where(cov, count, 0)
        joints = joint_positions(df["glb"])
        dist = np.min([np.linalg.norm(pos - joints[h], axis=-1) for h in HEADS], 0)
        share = count[dist < HEAD_RADIUS].sum() / max(int(count.sum()), 1)
        self.assertGreater(int(count.sum()), 0)
        self.assertGreaterEqual(share, MIN_HEAD_SHARE, f"only {share:.3f} of the glow is on the heads")


if __name__ == "__main__":
    unittest.main()
