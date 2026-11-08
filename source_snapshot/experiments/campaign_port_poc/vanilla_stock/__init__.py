"""Stock-vanilla HoMM3→Olden translator (no Golden Era Core overlays).

This package mirrors the raw_translation pipeline structure (alignment IR →
terrain projection → stock-SID emit → gate-face rotation → placement ground
truth) while remaining strictly stock-legal: only SIDs/tiles present in the
stock Olden ``Core.zip``, with no ``homm3_*`` / Core overlay dependency.

Stock Core.zip ``DB/map/tiles/tiles.json`` currently exposes tiles 1..7 only.
Golden Era tiles Burrow(15) / Water(18-22) / Void(23) are absent from stock and
must not be emitted. Ocean uses a Sand-basin stand-in; subterranean walkable
cells use Dirt; elevated rock uses Dirt at ``levelsMap=1``.
"""

from __future__ import annotations

SCHEMA_MAP = "homm3.vanilla_stock_map.v1"
SCHEMA_VALIDATION = "homm3.vanilla_stock_map.validation.v1"
SCHEMA_ALIGNMENT = "homm3.vanilla_stock_alignment_ir.v1"
SCHEMA_GROUND_TRUTH = "homm3.vanilla_stock_placement_ground_truth.v1"
STATUS = "generated_artifact_runtime_unvalidated"
PIPELINE = "vanilla_stock_raw_parity"

# Legacy constants kept for callers; authoritative allowlist is loaded from Core.
STOCK_TILE_ID_MIN = 1
STOCK_TILE_ID_MAX = 7
STOCK_OCEAN_TILE_ID = 2  # Sand basin stand-in for HoMM3 water (stock has no GE tiles 18-22)
STOCK_PADDING_TILE_ID = 1
STOCK_SUBTERRANEAN_TILE_ID = 7  # Dirt stand-in for Burrow (15 is GE-only)
STOCK_ROCK_TILE_ID = 7
STOCK_SUBTERRANEAN_GATE_SID = "portal_5"

# Tile ids that exist only in Golden Era Core.zip — never emit on stock maps.
GE_ONLY_TILE_IDS = frozenset({15, 18, 19, 20, 21, 22, 23})

__all__ = [
    "SCHEMA_MAP",
    "SCHEMA_VALIDATION",
    "SCHEMA_ALIGNMENT",
    "SCHEMA_GROUND_TRUTH",
    "STATUS",
    "PIPELINE",
    "STOCK_TILE_ID_MIN",
    "STOCK_TILE_ID_MAX",
    "STOCK_OCEAN_TILE_ID",
    "STOCK_PADDING_TILE_ID",
    "STOCK_SUBTERRANEAN_TILE_ID",
    "STOCK_ROCK_TILE_ID",
    "STOCK_SUBTERRANEAN_GATE_SID",
    "GE_ONLY_TILE_IDS",
]
