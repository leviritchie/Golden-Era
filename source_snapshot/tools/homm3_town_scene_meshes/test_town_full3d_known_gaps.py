#!/usr/bin/env python3
"""Unit tests: restPaint.knownGaps (town_full3d_recipe load_recipe / apply_known_gaps; coordinator 2026-10-02). Only a
min_ state approved by name in REST_PAINT_KNOWN_GAPS_APPROVED, with maxPx within the approval and a reason, loads; the
state then passes only while every component of REST_PAINT_AREA px or more is at most maxPx and drawn by that layer."""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import town_full3d_recipe as R  # noqa: E402

GAP = {"state": "min_tbfacas2", "layer": "tbfacas2", "maxPx": 590,
       "why": "Meshy T2 cas2 spire over painted sky; same gap installed in pb_v1"}


def recipe(gaps, faction="factory"):
    return {"schema": R.SCHEMA_V2, "faction": faction, "seed": "a", "candidate": "b",
            "ldi": {"pieces": ["Mesh_Terrain"]}, "backstop": {}, "repair": {"rules": ["drop", "card"]},
            "certificate": {"loop": 12}, "restPaint": {"knownGaps": gaps}}


def load(r):
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "r.json"
        p.write_text(json.dumps(r), encoding="utf-8")
        return R.load_recipe(p)


# Factory zs_v1's measured min_tbfacas2 (zero_streak_recipe.json, 2026-10-02)
FACTORY = {"min_tbfacas2": {"maxComponentPx": 539, "overAreaComponents": 1, "pass": False, "components": [
    {"px": 539, "bbox": [804, 50, 18, 44], "drawnBy": {"tbfacas2/Mesh_Body_tbfacas2": 539}},
    {"px": 227, "bbox": [0, 529, 13, 35], "drawnBy": {"environment/Mesh_OuterL1": 227}},
    {"px": 126, "bbox": [804, 102, 12, 13], "drawnBy": {"tbfacas2/Mesh_Body_tbfacas2": 126}}]},
    "full": {"maxComponentPx": 0, "overAreaComponents": 0, "pass": True, "components": []}}


class Load(unittest.TestCase):
    def test_approved_entry_loads(self):
        r = load(recipe([dict(GAP)]))
        self.assertEqual(r["restPaint"]["knownGaps"][0]["approvedMaxPx"], 590)

    def test_refusals(self):
        for bad in ({**GAP, "maxPx": 600},                  # above the approval
                    {**GAP, "why": " "},                    # no reason
                    {**GAP, "layer": "tbfacas3"},           # another layer
                    {**GAP, "state": "full"},               # not a min_ state
                    {**GAP, "state": "min_tbfacas3"},       # not approved by name
                    {k: v for k, v in GAP.items() if k != "why"}):
            with self.assertRaises(SystemExit, msg=json.dumps(bad)):
                load(recipe([bad]))
        with self.assertRaises(SystemExit):
            load(recipe([dict(GAP), dict(GAP)]))            # twice
        with self.assertRaises(SystemExit):
            load(recipe([dict(GAP)], faction="castle"))     # approved for factory only


class Apply(unittest.TestCase):
    def test_factory_gap_passes(self):
        by = copy.deepcopy(FACTORY)
        R.apply_known_gaps(by, [dict(GAP)])
        self.assertTrue(by["min_tbfacas2"]["pass"])
        self.assertTrue(by["min_tbfacas2"]["knownGap"]["applied"])

    def test_bigger_component_fails(self):
        by = copy.deepcopy(FACTORY)
        by["min_tbfacas2"]["components"][0]["px"] = 591
        R.apply_known_gaps(by, [dict(GAP)])
        self.assertFalse(by["min_tbfacas2"]["pass"])

    def test_other_layer_component_fails(self):
        by = copy.deepcopy(FACTORY)
        by["min_tbfacas2"]["components"][1]["px"] = 450
        by["min_tbfacas2"]["overAreaComponents"] = 2
        R.apply_known_gaps(by, [dict(GAP)])
        self.assertFalse(by["min_tbfacas2"]["pass"])

    def test_unlisted_over_area_component_fails(self):
        by = copy.deepcopy(FACTORY)
        by["min_tbfacas2"]["overAreaComponents"] = 6          # more than the listed components show
        R.apply_known_gaps(by, [dict(GAP)])
        self.assertFalse(by["min_tbfacas2"]["pass"])

    def test_unknown_state_fails(self):
        with self.assertRaises(SystemExit):
            R.apply_known_gaps({"full": FACTORY["full"]}, [dict(GAP)])


if __name__ == "__main__":
    unittest.main()
