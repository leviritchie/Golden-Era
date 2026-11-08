from __future__ import annotations

import unittest

import h3m_object_registry as h3obj
from experiments.campaign_port_poc.vanilla_stock.object_map import (
    VanillaStockObjectMapError,
    resolve_object_sid,
)


class VanillaStockHardeningTests(unittest.TestCase):
    def test_unknown_creature_generator_animation_fails_closed(self) -> None:
        with self.assertRaises(VanillaStockObjectMapError):
            resolve_object_sid(
                {
                    "templateObjectId": h3obj.OBJECT_CREATURE_GENERATOR_1,
                    "templateAnimation": "unknown_generator_animation",
                    "templateSubtype": 0,
                    "key": "unknown-generator",
                },
                stock_object_ids={"human_barracks"},
                terrain_biome="grass",
            )


if __name__ == "__main__":
    unittest.main()
