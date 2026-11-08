"""Stock-safe wrapper around raw gate_face_rotation.

Elevated underground rock is Dirt tile 7 at levelsMap=1 on stock maps (Void tile
23 is GE-only). Raw pathability treats only water tiles + Void as non-land, so
this wrapper temporarily marks elevated-rock cells as Void for freeness checks,
runs the shared rotation pass, then:

- restores elevated cells that stayed Void back to Dirt levels=1 / climbs=0
- converts elevated cells carved to Burrow into stock Dirt levels=0
- refuses leftover GE-only tile ids on the real arrays
"""

from __future__ import annotations

from typing import Any

from . import GE_ONLY_TILE_IDS, STOCK_SUBTERRANEAN_TILE_ID


class VanillaStockGateFaceError(ValueError):
    """Raised when gate-face rotation would leak GE tiles or fail closed."""


def _import_gate_face_rotation():
    """Import raw gate_face_rotation with its approach_cell leave path configured."""
    import sys
    from pathlib import Path

    poc = Path(__file__).resolve().parents[1]
    raw = poc / "raw_translation"
    approach = poc / "approach_cell"
    for path in (str(raw), str(approach), str(poc)):
        if path not in sys.path:
            sys.path.insert(0, path)
    import gate_face_rotation

    return gate_face_rotation


def apply_stock_gate_face_rotations(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    *,
    tiles_map: list[int],
    water_map: list[int],
    levels_map: list[int],
    climbs_map: list[int],
    width: int,
    height: int,
    clearable_object_ids: set[int],
    relocation_region_width: int,
    max_relocation_radius: int = 6,
) -> dict[str, Any]:
    # Import late so vanilla_stock does not pull approach_cell leaves at package import.
    gate_face_rotation = _import_gate_face_rotation()

    expected = width * height
    if len(tiles_map) != expected or len(water_map) != expected:
        raise VanillaStockGateFaceError(
            f"atlas array length mismatch for gate-face: tiles={len(tiles_map)} "
            f"water={len(water_map)} expected={expected}"
        )
    if len(levels_map) != expected or len(climbs_map) != expected:
        raise VanillaStockGateFaceError(
            f"levels/climbs length mismatch for gate-face: levels={len(levels_map)} "
            f"climbs={len(climbs_map)} expected={expected}"
        )

    elevated = {index for index, level in enumerate(levels_map) if int(level) == 1}
    tiles_view = list(tiles_map)
    for index in elevated:
        tiles_view[index] = 23  # temporary Void marker for raw pathability only

    report = gate_face_rotation.apply_single_gate_face_rotations(
        objects,
        native_object_configs,
        tiles_map=tiles_view,
        water_map=water_map,
        levels_map=levels_map,
        climbs_map=climbs_map,
        width=width,
        height=height,
        clearable_object_ids=clearable_object_ids,
        relocation_region_width=relocation_region_width,
        max_relocation_radius=max_relocation_radius,
    )

    carved_nodes: list[int] = []
    restored_elevated_nodes: list[int] = []
    for index, tile in enumerate(tiles_view):
        tile_id = int(tile)
        if index in elevated:
            if tile_id == 23:
                # Pathability marker only — restore elevated Dirt cliff.
                tiles_map[index] = STOCK_SUBTERRANEAN_TILE_ID
                levels_map[index] = 1
                climbs_map[index] = 0
                water_map[index] = 0
                restored_elevated_nodes.append(index)
            elif tile_id in GE_ONLY_TILE_IDS:
                # Gate-face carved elevated rock (Void→Burrow) into a walkable shoulder.
                tiles_map[index] = STOCK_SUBTERRANEAN_TILE_ID
                levels_map[index] = 0
                climbs_map[index] = 0
                water_map[index] = 0
                carved_nodes.append(index)
            else:
                raise VanillaStockGateFaceError(
                    f"gate-face mutated elevated rock at node {index} to non-GE tile {tile_id}"
                )
            continue

        if tile_id in GE_ONLY_TILE_IDS:
            # Unexpected GE tile on non-elevated land — fail closed.
            raise VanillaStockGateFaceError(
                f"gate-face introduced GE-only tile {tile_id} on non-elevated node {index}"
            )
        if tile_id != int(tiles_map[index]):
            raise VanillaStockGateFaceError(
                f"gate-face rotation mutated stock tile at node {index}: "
                f"{tiles_map[index]} -> {tile_id}"
            )

    ge_remaining = sorted({int(t) for t in tiles_map if int(t) in GE_ONLY_TILE_IDS})
    if ge_remaining:
        raise VanillaStockGateFaceError(
            f"GE-only tile ids remain after stock gate-face sync: {ge_remaining}"
        )

    report = dict(report)
    report["stockAdaptation"] = {
        "policy": "elevated_rock_as_void_for_pathability_restore_cliffs_carve_to_stock_dirt",
        "elevatedRockCellCount": len(elevated),
        "restoredElevatedCliffCount": len(restored_elevated_nodes),
        "stockDirtCarveCount": len(carved_nodes),
        "geOnlyTilesForbidden": sorted(GE_ONLY_TILE_IDS),
    }
    return report
