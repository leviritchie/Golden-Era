"""validate_homm3_def_retarget_emphasis_contract.delivery_chain_errors: the canonical GLB links back to the emphasised
export through the stamped delivery stages, and a broken link fails.

    python -m unittest tools/homm3_def_retarget_emphasis/test_delivery_chain.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_homm3_def_retarget_emphasis_contract import delivery_chain_errors as chain  # noqa: E402

E, A, B, C, L, G = ("e" * 64, "a" * 64, "b" * 64, "c" * 64, "l" * 64, "g" * 64)
STRIDE, PROP, GROUND = ("homm3DefRetargetDeliveryStrideMatch", "homm3DefRetargetDeliveryPropFloor",
                        "homm3DefRetargetDeliveryGround")


class DeliveryChain(unittest.TestCase):
    def test_the_emphasised_export_itself_and_a_direct_look(self):
        self.assertEqual(chain(E, E, {}, {}, {}), [])
        self.assertEqual(chain(E, G, {}, {"sourceGlbSha256": E, "deliveredGlbSha256": G}, {}), [])
        self.assertTrue(chain(E, G, {}, {"sourceGlbSha256": A, "deliveredGlbSha256": G}, {}))

    def test_stride_then_look_links_back(self):   # h3_archer: stride match (no output record) -> look
        ex = {STRIDE: {"sourceGlbSha256": E}}
        self.assertEqual(chain(E, G, ex, {"sourceGlbSha256": L, "deliveredGlbSha256": G}, {}), [])

    def test_recorded_outputs_must_meet_the_next_stage_and_the_look(self):
        ex = {STRIDE: {"sourceGlbSha256": E}, PROP: {"sourceGlbSha256": A}, GROUND: {"sourceGlbSha256": B}}
        side = {"prop_floor": {"sourceGlbSha256": A, "outputGlbSha256": B},
                "ground": {"sourceGlbSha256": B, "outputGlbSha256": L}}
        look = {"sourceGlbSha256": L, "deliveredGlbSha256": G}
        self.assertEqual(chain(E, G, ex, look, side), [])
        side["prop_floor"]["outputGlbSha256"] = C             # ground ran on something prop floor did not write
        self.assertIn("not on homm3DefRetargetDeliveryPropFloor's recorded output", " ".join(chain(E, G, ex, look, side)))
        side["prop_floor"]["outputGlbSha256"] = B
        side["ground"]["outputGlbSha256"] = C                 # ground re-applied after the look: look is stale
        self.assertIn("look source", " ".join(chain(E, G, ex, look, side)))

    def test_broken_links_fail(self):
        look = {"sourceGlbSha256": L, "deliveredGlbSha256": G}
        self.assertIn("not on the emphasised export", " ".join(chain(E, G, {STRIDE: {"sourceGlbSha256": A}}, look, {})))
        self.assertIn("deliveredGlbSha256", " ".join(chain(E, C, {STRIDE: {"sourceGlbSha256": E}}, look, {})))
        self.assertIn("unknown delivery stage", " ".join(
            chain(E, G, {STRIDE: {"sourceGlbSha256": E}, "homm3DefRetargetDeliveryMystery": {}}, look, {})))
        self.assertIn("no sourceGlbSha256", " ".join(chain(E, G, {STRIDE: {}}, look, {})))
        self.assertIn("input of an earlier stage", " ".join(       # a stage re-run on its own earlier input
            chain(E, G, {STRIDE: {"sourceGlbSha256": E}, GROUND: {"sourceGlbSha256": E}}, look, {})))
        self.assertIn("input of a delivery stage", " ".join(       # the look ran before the last stage
            chain(E, G, {STRIDE: {"sourceGlbSha256": E}}, {"sourceGlbSha256": E, "deliveredGlbSha256": G}, {})))


if __name__ == "__main__":
    unittest.main()
