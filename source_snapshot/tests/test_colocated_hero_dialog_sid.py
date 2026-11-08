#!/usr/bin/env python3
"""dialogHeroSid for colocated EVENT+hero must match resolve_placed_hero_sid."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_POC = Path(__file__).resolve().parents[1] / "experiments" / "campaign_port_poc"
if str(_POC) not in sys.path:
    sys.path.insert(0, str(_POC))

import campaign_runtime_script as crs  # noqa: E402


class ColocatedHeroDialogSidTests(unittest.TestCase):
    def test_truncated_gurnis_uses_stub_sid_not_catalog_type(self) -> None:
        # H3 places type 97 as "Gurnis" (truncated); emit stubs that name.
        # Interrupt planning must reuse the stub, not type-only homm3_stronghold_hero_2.
        with mock.patch.object(
            crs, "_hero_core_icon_sid", return_value="hero_homm3_stronghold_2"
        ):
            avatar = crs.colocated_hero_dialog_avatar(
                {
                    "heroType": 97,
                    "hasName": True,
                    "name": "Gurnis",
                }
            )
        self.assertEqual(avatar["heroSid"], "h3_campaign_placed_gurnis")
        self.assertTrue(str(avatar["icon"]).startswith("icons/dialogue/dialogue_hero_homm3_"))
        self.assertEqual(avatar["title"], "Gurnisson")

    def test_port_manifest_name_without_hasName_still_stubs(self) -> None:
        # object_port_manifest keeps custom name but often omits hasName.
        with mock.patch.object(
            crs, "_hero_core_icon_sid", return_value="hero_homm3_stronghold_2"
        ):
            avatar = crs.colocated_hero_dialog_avatar(
                {
                    "heroType": 97,
                    "name": "Gurnis",
                }
            )
        self.assertEqual(avatar["heroSid"], "h3_campaign_placed_gurnis")

    def test_explicit_hasName_false_ignores_name_text(self) -> None:
        with mock.patch.object(
            crs, "_hero_core_icon_sid", return_value="hero_homm3_stronghold_2"
        ):
            avatar = crs.colocated_hero_dialog_avatar(
                {
                    "heroType": 97,
                    "hasName": False,
                    "name": "Gurnis",
                }
            )
        self.assertEqual(avatar["heroSid"], "homm3_stronghold_hero_2")

    def test_roster_name_keeps_catalog_sid(self) -> None:
        with mock.patch.object(
            crs, "_hero_core_icon_sid", return_value="hero_homm3_castle_1"
        ):
            avatar = crs.colocated_hero_dialog_avatar(
                {
                    "heroType": 0,
                    "hasName": True,
                    "name": "Orrin",
                }
            )
        self.assertEqual(avatar["heroSid"], "homm3_castle_hero_1")

    def test_interruption_copies_dialog_hero_sid(self) -> None:
        rows = crs.build_colocated_hero_interruptions(
            "bashing_skulls",
            {
                "quests": [
                    {
                        "sid": "bashing_skulls_map_event_1",
                        "hostLifetime": crs.COLOCATED_HERO_HOST_LIFETIME,
                        "dialogHeroSid": "h3_campaign_placed_gurnis",
                        "dialogSid": "bashing_skulls_map_event_1_dialog",
                        "message": "Hello",
                        "removeAfterVisit": True,
                        "rewards": {},
                    }
                ]
            },
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["interruption"], "BeforeIamVsHero")
        self.assertEqual(rows[0]["p"], ["h3_campaign_placed_gurnis"])


if __name__ == "__main__":
    unittest.main()
