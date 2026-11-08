#!/usr/bin/env python3
"""Tests for batch emit stamps and multi-hub overlay merge helpers."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "campaign_port_poc"))
sys.path.insert(0, str(ROOT / "tools"))

import campaign_raw_translation_batch_worker as batch_worker  # noqa: E402
import install_roe_castle_continuity_weave as install  # noqa: E402


class BatchStampTests(unittest.TestCase):
    def test_stamp_stable_for_same_inputs(self) -> None:
        from campaign_mission import load_batch_manifest, mission_by_id
        import generate_campaign_raw_translation_profile as raw_profile

        batch = load_batch_manifest(
            (ROOT / "scenarios" / "ab_sod_campaigns" / "batch_manifest.json").resolve()
        )
        mission = mission_by_id(batch, "gathering_the_legion")
        profile = raw_profile.raw_profile_path_for_mission(mission)
        poc_root = ROOT / "experiments" / "campaign_port_poc"
        a = batch_worker.compute_mission_input_stamp(
            poc_root=poc_root, mission=mission, profile_path=profile
        )
        b = batch_worker.compute_mission_input_stamp(
            poc_root=poc_root, mission=mission, profile_path=profile
        )
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)


class MultiHubOverlayMergeTests(unittest.TestCase):
    def test_lang_sid_merge_keeps_both(self) -> None:
        left = {
            "Lang/en/texts/customMaps.json": (
                b'{"tokens":[{"sid":"a","text":"A"}],"array":[{"sid":"a","text":"A"}]}\n'
            )
        }
        right = {
            "Lang/en/texts/customMaps.json": (
                b'{"tokens":[{"sid":"b","text":"B"}],"array":[{"sid":"b","text":"B"}]}\n'
            )
        }
        merged = install.merge_overlay_member_dicts(left, right)
        text = merged["Lang/en/texts/customMaps.json"].decode("utf-8")
        self.assertIn('"sid": "a"', text)
        self.assertIn('"sid": "b"', text)

    def test_hub_play_order_covers_configs(self) -> None:
        self.assertEqual(
            set(install.HUB_CONFIGS), set(install.HUB_INSTALL_KEYS_PLAY_ORDER)
        )


if __name__ == "__main__":
    unittest.main()
