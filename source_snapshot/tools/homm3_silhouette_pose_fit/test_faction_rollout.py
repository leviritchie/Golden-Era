#!/usr/bin/env python3
from __future__ import annotations

import unittest
from pathlib import Path

TOOL = Path(__file__).resolve().parent
import sys

if str(TOOL) not in sys.path:
    sys.path.insert(0, str(TOOL))

from faction_rollout import (  # noqa: E402
    FACTION_ROLLOUT_ORDER,
    bundle_names_for_faction,
    faction_catalog_lab_sids,
    faction_key_from_bundle,
    faction_tier_lab_sids,
    normalize_faction_key,
    sort_jobs_by_faction,
)


class FactionRolloutTests(unittest.TestCase):
    def test_normalize_castle_aliases(self) -> None:
        self.assertEqual(normalize_faction_key("castle"), "homm3_castle")
        self.assertEqual(normalize_faction_key("homm3_castle"), "homm3_castle")

    def test_bundle_faction_mapping(self) -> None:
        self.assertEqual(
            faction_key_from_bundle("custom_units_castle_h3_crusader"),
            "homm3_castle",
        )
        self.assertEqual(
            faction_key_from_bundle("custom_units_cove_hota_cove_nymph"),
            "homm3_cove",
        )

    def test_castle_catalog_includes_crusader(self) -> None:
        sids = faction_catalog_lab_sids("homm3_castle")
        self.assertIn("h3_crusader", sids)

    def test_castle_tier_order_starts_with_pikeman(self) -> None:
        order = faction_tier_lab_sids("homm3_castle")
        self.assertGreater(len(order), 5)
        self.assertEqual(order[0], "h3_pikeman")

    def test_castle_bundle_prefix(self) -> None:
        names = bundle_names_for_faction("homm3_castle")
        self.assertTrue(all(name.startswith("custom_units_castle_") for name in names))
        self.assertIn("custom_units_castle_h3_crusader", names)

    def test_sort_jobs_respects_tier(self) -> None:
        jobs = [
            ({"labSid": "h3_crusader"}, type("C", (), {"animation_name": "idle"})()),
            ({"labSid": "h3_pikeman"}, type("C", (), {"animation_name": "idle"})()),
        ]
        ordered = sort_jobs_by_faction(jobs, "homm3_castle")
        self.assertEqual(ordered[0][0]["labSid"], "h3_pikeman")

    def test_stronghold_catalog_includes_legacy_h3_bundles(self) -> None:
        from faction_rollout import faction_key_from_import_relpath

        self.assertEqual(
            faction_key_from_import_relpath("homm3_import/stronghold/h3_goblin"),
            "homm3_stronghold",
        )
        sids = faction_catalog_lab_sids("homm3_stronghold")
        self.assertIn("h3_goblin", sids)
        self.assertIn("h3_hobgoblin", sids)
        self.assertIn("h3_behemoth", sids)
        self.assertNotIn("h3_crusader", sids)

    def test_rollout_order_starts_castle(self) -> None:
        self.assertEqual(FACTION_ROLLOUT_ORDER[0], "homm3_castle")

    def test_batch_default_raster_knobs(self) -> None:
        from run_fused_push_regression_triplet import regression_kwargs

        kw = regression_kwargs(batch=True)
        self.assertEqual(kw["joint_score_raster_batch"], 512)
        self.assertEqual(kw["chroma_scale"], 2)

    def test_batch_memory_safe_raster_knobs(self) -> None:
        from run_fused_push_regression_triplet import regression_kwargs

        kw = regression_kwargs(batch=True, memory_safe_batch=True)
        self.assertEqual(kw["joint_score_raster_batch"], 512)
        self.assertEqual(kw["chroma_scale"], 2)

    def test_batch_gpu_fed_raster_knobs(self) -> None:
        from run_fused_push_regression_triplet import regression_kwargs

        kw = regression_kwargs(batch=True, gpu_fed_batch=True)
        self.assertEqual(kw["joint_score_raster_batch"], 1024)
        self.assertEqual(kw["chroma_scale"], 4)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
