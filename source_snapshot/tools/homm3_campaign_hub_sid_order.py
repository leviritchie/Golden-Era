"""Canonical HoMM3 StoryHub hub SIDs ordered for Profiles list alpha-sort.

Native campaign discovery lists hubs alphabetically by folder/SID. Zero-padded
``homm3_NN_…`` prefixes put Complete Edition campaigns in play order
(RoE → AB → SoD) without a runtime reorder hook.

Legacy unprefixed SIDs remain in LEGACY_TO_PLAY_ORDER for Core.zip migration.
"""

from __future__ import annotations

# (legacy_hub_sid, play_order_hub_sid) in Complete Edition play order.
HUB_SID_PLAY_ORDER_ROWS: tuple[tuple[str, str], ...] = (
    ("homm3_roe_castle_good1", "homm3_01_roe_castle_good1"),
    ("homm3_roe_castle_good2", "homm3_02_roe_castle_good2"),
    ("homm3_roe_castle_good3", "homm3_03_roe_castle_good3"),
    ("homm3_roe_dungeon_evil1", "homm3_04_roe_dungeon_evil1"),
    ("homm3_roe_necropolis_evil2", "homm3_05_roe_necropolis_evil2"),
    ("homm3_roe_neutral_neutral1", "homm3_06_roe_neutral_neutral1"),
    ("homm3_roe_rampart_secret1", "homm3_07_roe_rampart_secret1"),
    ("homm3_roe_necropolis_secret", "homm3_08_roe_necropolis_secret"),
    ("homm3_ab_conflux_ab", "homm3_09_ab_conflux_ab"),
    ("homm3_ab_dungeon_blood", "homm3_10_ab_dungeon_blood"),
    ("homm3_ab_tower_slayer", "homm3_11_ab_tower_slayer"),
    ("homm3_ab_stronghold_festival", "homm3_12_ab_stronghold_festival"),
    ("homm3_ab_fortress_fire", "homm3_13_ab_fortress_fire"),
    ("homm3_ab_castle_fool", "homm3_14_ab_castle_fool"),
    ("homm3_sod_necropolis_sandro", "homm3_15_sod_necropolis_sandro"),
    ("homm3_sod_stronghold_crag", "homm3_16_sod_stronghold_crag"),
    ("homm3_sod_stronghold_yog", "homm3_17_sod_stronghold_yog"),
    ("homm3_sod_rampart_gem", "homm3_18_sod_rampart_gem"),
    ("homm3_sod_rampart_gelu", "homm3_19_sod_rampart_gelu"),
    ("homm3_sod_necropolis_final", "homm3_20_sod_necropolis_final"),
)

LEGACY_TO_PLAY_ORDER: dict[str, str] = {
    legacy: play for legacy, play in HUB_SID_PLAY_ORDER_ROWS
}
PLAY_ORDER_TO_LEGACY: dict[str, str] = {
    play: legacy for legacy, play in HUB_SID_PLAY_ORDER_ROWS
}
PLAY_ORDER_HUB_SIDS: tuple[str, ...] = tuple(play for _, play in HUB_SID_PLAY_ORDER_ROWS)
LEGACY_HUB_SIDS: tuple[str, ...] = tuple(legacy for legacy, _ in HUB_SID_PLAY_ORDER_ROWS)


def rewrite_hub_sid_text(text: str) -> str:
    """Replace legacy hub SIDs with play-order SIDs (longest-first)."""
    out = text
    for legacy, play in sorted(
        LEGACY_TO_PLAY_ORDER.items(), key=lambda item: len(item[0]), reverse=True
    ):
        out = out.replace(legacy, play)
    return out
