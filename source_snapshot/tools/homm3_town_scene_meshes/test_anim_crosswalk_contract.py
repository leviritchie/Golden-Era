"""Tower's ANIM_CROSSWALK is applied by the phase-4 animation audit (validate_town_scene3d_contract.check_animation_audit).

Tower's animated DEFs are keyed dwellingUp2Lvl*_1 in layers/anims/metadata.json, not by the layer they animate. Before the
crosswalk was wired, tbtwdw_0_2 read as static and a catalog with no effect for it passed silently.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import validate_town_scene3d_contract as gate  # noqa: E402


class GateFail(Exception):
    pass


def _raise(msg: str) -> None:
    raise GateFail(msg)


class AnimCrosswalkContractTests(unittest.TestCase):
    def check(self, cat: dict) -> str:
        with patch.object(gate, "fail", _raise), self.assertRaises(GateFail) as ctx:
            gate.check_animation_audit(cat, "crosswalk-test")
        return str(ctx.exception)

    def test_tower_dwelling_without_audit_row_fails(self):
        cat = {"fraction": "homm3_tower", "animationAudit": {}, "layers": [{"layerId": "tbtwdw_0_2", "pieces": []}]}
        self.assertIn("tbtwdw_0_2: HoMM3 DEF has 20 frames but animationAudit has no row", self.check(cat))

    def test_tower_dwelling_audit_row_takes_the_def_frame_count(self):
        cat = {"fraction": "homm3_tower", "layers": [{"layerId": "tbtwdw_6_2", "pieces": ["Fx_glow"]}],
               "animationAudit": {"tbtwdw_6_2": {"defFrames": 20, "moves": "x", "effects": ["Fx_glow"]}}}
        self.assertIn("animationAudit defFrames 20 != DEF 10", self.check(cat))

    def test_crosswalk_key_as_layer_is_not_animated(self):
        cat = {"fraction": "homm3_tower", "layers": [{"layerId": "dwellingUp2Lvl1_1", "pieces": []}],
               "animationAudit": {"dwellingUp2Lvl1_1": {"defFrames": 20}}}
        self.assertIn("lists dwellingUp2Lvl1_1 but its HoMM3 DEF is static", self.check(cat))


if __name__ == "__main__":
    unittest.main()
