#!/usr/bin/env python3
"""Tests for H3 campaign-only placed hero stubs (Tyranell-class names)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

_POC = Path(__file__).resolve().parents[1] / "experiments" / "campaign_port_poc"
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

import h3_campaign_placed_heroes as cph
import h3m_hero_sid as hs


class CampaignPlacedHeroStubTests(unittest.TestCase):
    def test_tyranell_resolves_to_campaign_stub_not_tyris(self) -> None:
        sid, tag = cph.resolve_placed_hero_sid(7, name="Tyranell")
        self.assertEqual(sid, "h3_campaign_placed_tyranell")
        self.assertEqual(tag, "h3_campaign_placed_custom_name")
        stock, _ = hs.resolve_h3_hero_sid(7, name=None)
        self.assertEqual(stock, "homm3_castle_hero_8")
        self.assertNotEqual(sid, stock)

    def test_known_roster_name_unchanged(self) -> None:
        sid, tag = cph.resolve_placed_hero_sid(0, name="Orrin")
        self.assertEqual(sid, "homm3_castle_hero_1")
        self.assertIn(tag, {"h3m_hero_name", "h3m_hero_name_over_type"})

    def test_slug_stable(self) -> None:
        self.assertEqual(cph.sid_for_display_name("Lord Chasim"), "h3_campaign_placed_lord_chasim")
        self.assertEqual(cph.sid_for_display_name("Gen. Kendal"), "h3_campaign_placed_gen_kendal")


if __name__ == "__main__":
    unittest.main()
