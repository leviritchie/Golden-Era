"""Declared periphery requirements of the phase-6 pan contract (validate_town_scene3d_contract.check_pan_coverage).

A town whose painting has no river leaving the frame (Stronghold: a desert canyon) declares
periphery.water.required = false with a reason. The scatter kinds follow the faction profile's PERIPHERY_SCATTER
(town_full3d_factions/<key>.py): Stronghold requires its scrub (Mesh_Outer_scrub_) and boulder bins and measures its
near-field density; Castle declares no scrub with a reason and a profile density. Declared-but-missing content must fail
exactly like undeclared missing content, and a fraction whose profile declares nothing fails.
"""
from __future__ import annotations

import copy
import sys
import tempfile
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


def stronghold_like() -> dict:
    """Declared requirements met; the next check is the (absent) coverage file."""
    return {
        "fraction": "homm3_stronghold",
        "nearField": {"density": {"scrubBlobs": 12, "scrubPerM2": 0.0028}},
        "panCoverage": {"file": "no_such_pan_coverage.npz", "sha256": "0" * 64},
        "periphery": {
            "meshyCredits": 0, "mesh": {"frameIntrusions": 0},
            "pieces": {"Mesh_OuterL0": {"tris": 4}},
            "water": {"required": False, "reason": "no river leaves the painted canyon"},
            "scatter": {"_tree": {"sites": 3, "outsideFrame": 2, "prefixes": ["Mesh_Outer_scrub_"]},
                        "Mesh_Outer_scrub_0": {"instances": 2, "tris": 40},
                        "_rock": {"sites": 3, "outsideFrame": 3, "prefixes": ["Mesh_Outer_boulders_"]},
                        "Mesh_Outer_boulders_0": {"instances": 3, "tris": 60}},
        },
        "environment": {"pieces": ["Mesh_OuterL0", "Mesh_Outer_scrub_0", "Mesh_Outer_boulders_0"]},
    }


def castle_like() -> dict:
    """Castle's declaration met (no scrub, profile density); the next check is the (absent) coverage file."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_castle_profile", gate.PROFILES / "castle.py")
    prof = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(prof)
    pol = prof.PERIPHERY_SCATTER
    cat = stronghold_like()
    cat["fraction"] = "homm3_castle"
    cat["nearField"]["density"] = {"scrubBlobs": None, "scrubPerM2": pol["nearDensity"]["perM2"]}
    sc = cat["periphery"]["scatter"]
    del sc["Mesh_Outer_scrub_0"]
    sc["_tree"] = {"sites": 0, "outsideFrame": 0, "prefixes": [], "source": pol["scrub"]["reason"]}
    cat["environment"]["pieces"].remove("Mesh_Outer_scrub_0")
    return cat


def conflux_like() -> dict:
    """The Conflux lane's own declaration (no profile, catalog without per-kind prefixes) met."""
    cat = stronghold_like()
    cat["fraction"] = "homm3_conflux"
    cat["nearField"] = {}
    bins = {"Mesh_Outer_conifer_a_0": {"instances": 5, "tris": 50}, "Mesh_Outer_conifer_b_0": {"instances": 4, "tris": 40},
            "Mesh_Outer_bush_0": {"instances": 3, "tris": 30}, "Mesh_Outer_boulders_1": {"instances": 2, "tris": 20}}
    cat["periphery"]["scatter"] = {"_tree": {"sites": 9, "outsideFrame": 4}, "_bush": {"sites": 3, "outsideFrame": 1},
                                   "_rock": {"sites": 2, "outsideFrame": 2}, **bins}
    cat["environment"]["pieces"] = ["Mesh_OuterL0", *bins]
    return cat


class StrongholdPeripheryContractTests(unittest.TestCase):
    def check(self, cat: dict) -> str:
        with patch.object(gate, "fail", _raise), self.assertRaises(GateFail) as ctx:
            gate.check_pan_coverage(cat, "stronghold-test", HERE)
        return str(ctx.exception)

    def test_declared_requirements_met_reach_the_coverage_check(self):
        self.assertIn("panCoverage file", self.check(stronghold_like()))

    def test_water_not_required_needs_a_reason(self):
        cat = stronghold_like()
        cat["periphery"]["water"]["reason"] = "  "
        self.assertIn("without a reason", self.check(cat))

    def test_water_required_must_be_boolean(self):
        cat = stronghold_like()
        cat["periphery"]["water"]["required"] = "no"
        self.assertIn("must be a boolean", self.check(cat))

    def test_water_declared_absent_but_present_fails(self):
        cat = stronghold_like()
        cat["environment"]["pieces"].append("Fx_WaterOuter")
        self.assertIn("required is false but Fx_WaterOuter", self.check(cat))

    def test_water_required_by_default(self):
        cat = stronghold_like()
        del cat["periphery"]["water"]
        self.assertIn("Fx_WaterOuter with two continued rivers", self.check(cat))

    def test_declared_tree_prefix_without_bins_fails(self):
        cat = stronghold_like()
        sc = cat["periphery"]["scatter"]
        sc["Mesh_Outer_conifer_a_0"] = sc.pop("Mesh_Outer_scrub_0")   # content under another prefix only
        self.assertIn("tree scatter bins (Mesh_Outer_scrub_*)", self.check(cat))

    def test_declared_tree_bin_without_instances_fails(self):
        cat = stronghold_like()
        cat["periphery"]["scatter"]["Mesh_Outer_scrub_0"]["instances"] = 0
        self.assertIn("tree scatter bins (Mesh_Outer_scrub_*)", self.check(cat))

    def test_every_declared_prefix_needs_content(self):
        cat = stronghold_like()
        cat["periphery"]["scatter"]["_tree"]["prefixes"].append("Mesh_Outer_deadtree_")
        self.assertIn("!= profile PERIPHERY_SCATTER.scrub.prefixes", self.check(cat))

    def test_bad_prefix_declarations_fail(self):
        for bad in ([], ["Mesh_Outer_"], ["Mesh_Terrain"], "Mesh_Outer_scrub_"):
            cat = stronghold_like()
            cat["periphery"]["scatter"]["_tree"]["prefixes"] = bad
            self.assertIn("prefixes must be", self.check(cat), bad)

    def test_default_rock_prefix_still_required(self):
        cat = stronghold_like()
        del cat["periphery"]["scatter"]["Mesh_Outer_boulders_0"]
        self.assertIn("rock scatter bins (Mesh_Outer_boulders_*)", self.check(cat))

    def test_no_outside_frame_sites_fails(self):
        cat = stronghold_like()
        cat["periphery"]["scatter"]["_tree"]["outsideFrame"] = 0
        self.assertIn("tree scatter bins", self.check(cat))

    def test_declared_bins_must_be_environment_pieces(self):
        cat = stronghold_like()
        cat["environment"]["pieces"].remove("Mesh_Outer_scrub_0")
        self.assertIn("missing from the environment", self.check(cat))

    def test_measured_density_needs_a_blob_count(self):
        cat = stronghold_like()
        cat["nearField"]["density"]["scrubBlobs"] = None
        self.assertIn("nearDensity is measured", self.check(cat))

    def test_castle_declared_no_scrub_reaches_the_coverage_check(self):
        self.assertIn("panCoverage file", self.check(castle_like()))

    def test_castle_scrub_content_fails_its_declaration(self):
        cat = castle_like()
        cat["periphery"]["scatter"]["Mesh_Outer_scrub_0"] = {"instances": 2, "tris": 40}
        cat["environment"]["pieces"].append("Mesh_Outer_scrub_0")
        self.assertIn("belong to no declared PERIPHERY_SCATTER kind", self.check(cat))
        cat = castle_like()
        cat["periphery"]["scatter"]["_tree"]["source"] = "some other reason"
        self.assertIn("with the declared reason", self.check(cat))
        cat = castle_like()
        cat["environment"]["pieces"].append("Mesh_Near_scrub")
        self.assertIn("Mesh_Near_scrub piece is built", self.check(cat))

    def test_castle_density_must_be_the_profile_value(self):
        cat = castle_like()
        cat["nearField"]["density"]["scrubPerM2"] = 0.1
        self.assertIn("nearDensity perM2", self.check(cat))

    def test_conflux_lane_declaration_reaches_the_coverage_check(self):
        self.assertIn("panCoverage file", self.check(conflux_like()))

    def test_conflux_declared_bush_without_bins_fails(self):
        cat = conflux_like()
        del cat["periphery"]["scatter"]["Mesh_Outer_bush_0"]
        self.assertIn("bush scatter bins (Mesh_Outer_bush_*)", self.check(cat))
        cat = conflux_like()
        cat["periphery"]["scatter"]["_bush"]["outsideFrame"] = 0
        self.assertIn("bush scatter bins", self.check(cat))

    def test_conflux_catalog_prefixes_must_equal_the_declaration(self):
        cat = conflux_like()
        cat["periphery"]["scatter"]["_tree"]["prefixes"] = ["Mesh_Outer_conifer_a_"]
        self.assertIn("!= profile PERIPHERY_SCATTER.scrub.prefixes", self.check(cat))

    def test_conflux_undeclared_bins_and_near_scrub_fail(self):
        cat = conflux_like()
        cat["periphery"]["scatter"]["Mesh_Outer_deadtree_0"] = {"instances": 1, "tris": 9}
        self.assertIn("belong to no declared PERIPHERY_SCATTER kind", self.check(cat))
        cat = conflux_like()
        cat["environment"]["pieces"].append("Mesh_Near_scrub")
        self.assertIn("nearDensity is none", self.check(cat))
        cat = conflux_like()
        cat["nearField"] = {"density": {"scrubBlobs": 3}}
        self.assertIn("nearDensity is none", self.check(cat))

    def test_bush_on_a_fraction_without_a_bush_declaration_fails(self):
        cat = stronghold_like()
        cat["periphery"]["scatter"]["_bush"] = {"sites": 1, "outsideFrame": 1}
        self.assertIn("declares no PERIPHERY_SCATTER.bush", self.check(cat))

    def test_fraction_without_a_declaration_fails(self):
        cat = castle_like()
        cat["fraction"] = "homm3_no_such_town"
        self.assertIn("needs exactly one town_full3d_factions profile", self.check(cat))
        cat = castle_like()
        with tempfile.TemporaryDirectory() as d:
            src = (gate.PROFILES / "castle.py").read_text(encoding="utf-8")
            i = src.index("PERIPHERY_SCATTER = {")
            Path(d, "castle.py").write_text(src[:i] + src[src.index("\n\n", i):], encoding="utf-8")
            with patch.object(gate, "PROFILES", Path(d)):
                self.assertIn("must declare PERIPHERY_SCATTER", self.check(cat))

    def test_input_not_mutated(self):
        cat = stronghold_like()
        before = copy.deepcopy(cat)
        self.check(cat)
        self.assertEqual(cat, before)


if __name__ == "__main__":
    unittest.main()
