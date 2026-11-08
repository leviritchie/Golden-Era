"""Stock-safe portal and town approach-cell clearance for vanilla_stock.

Ports only the stock-applicable subset of raw_translation landon_access:
subterranean portal GATE scorched clear, plus town GATE south-approach clear.
Does not port GE barracks, Guardhouse dialog relocation, or homm3_* SIDs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from . import STOCK_SUBTERRANEAN_GATE_SID

_APPROACH = Path(__file__).resolve().parents[1] / "approach_cell"
if str(_APPROACH) not in sys.path:
    sys.path.insert(0, str(_APPROACH))

import surface_emit as single  # noqa: E402

SCHEMA = "homm3.vanilla_stock.access_contract.v1"
PROOF_BOUNDARY = "generated_artifact_runtime_unvalidated"

# Stock-safe clearable families on portal GATE / town approach cells.
_CLEARABLE_EXACT = frozenset(
    {
        "arena",
        "fountain",
        "university",
        "tree_of_knowledge",
        "lost_library",
        "mana_well",
        "shady_den",
        "chest",
        "camp_fire",
        "tavern",
    }
)
_CLEARABLE_PREFIXES = (
    "resource_",
    "altar_of_magic",
    "shrine_",
    "mountain_",
    "pinetree_",
    "tree_",
    "grass_",
    "dirt_",
    "snow_",
    "lava_",
    "water_",
    "desert_",
    "flowers_",
    "stones_",
    "cactus_",
    "bush_",
    "rock_",
    "log_",
    "skeleton_",
)


class VanillaStockAccessError(ValueError):
    """Fail-closed access clearance error."""


def _object_index(objects: list[dict[str, Any]]) -> dict[int, tuple[str, int, int]]:
    index: dict[int, tuple[str, int, int]] = {}
    for group in objects:
        if not isinstance(group, dict):
            continue
        sid = group.get("sid")
        if not isinstance(sid, str):
            continue
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        if not (len(ids) == len(nodes) == len(rotations)):
            raise VanillaStockAccessError(f"object group length mismatch for {sid}")
        for object_id, node, rotation in zip(ids, nodes, rotations):
            if isinstance(object_id, int) and isinstance(node, int) and isinstance(rotation, int):
                index[object_id] = (sid, node, rotation)
    return index


def _remove_object_ids(objects: list[dict[str, Any]], remove_ids: set[int]) -> None:
    if not remove_ids:
        return
    surviving: list[dict[str, Any]] = []
    for group in objects:
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        levels = group.get("levels") or []
        keep = [i for i, oid in enumerate(ids) if oid not in remove_ids]
        if not keep:
            continue
        group["ids"] = [ids[i] for i in keep]
        group["nodes"] = [nodes[i] for i in keep]
        group["rotations"] = [rotations[i] for i in keep]
        if levels:
            group["levels"] = [levels[i] for i in keep if i < len(levels)]
        surviving.append(group)
    objects[:] = surviving


def _remove_property_rows(properties: dict[str, Any] | None, remove_ids: set[int]) -> None:
    if not properties or not remove_ids:
        return
    for key, rows in list(properties.items()):
        if not isinstance(rows, list):
            continue
        properties[key] = [
            row
            for row in rows
            if not (isinstance(row, dict) and isinstance(row.get("id"), int) and int(row["id"]) in remove_ids)
        ]


def _is_clearable_sid(sid: str) -> bool:
    if sid in _CLEARABLE_EXACT:
        return True
    if sid.endswith("_city") or sid.startswith("portal_") or sid in {"random-squad", "hero-spawner"}:
        return False
    return any(sid.startswith(prefix) for prefix in _CLEARABLE_PREFIXES)


def _owners_at_node(
    objects: list[dict[str, Any]],
    stock_object_configs: dict[str, dict[str, Any]],
    node: int,
    *,
    exclude_ids: set[int],
    atlas_width: int,
    atlas_height: int,
) -> list[tuple[int, str]]:
    previous_w, previous_h = single.OLDEN_WIDTH, single.OLDEN_HEIGHT
    single.OLDEN_WIDTH = atlas_width
    single.OLDEN_HEIGHT = atlas_height
    try:
        owners: list[tuple[int, str]] = []
        for group in objects:
            sid = group.get("sid")
            if not isinstance(sid, str):
                continue
            config = stock_object_configs.get(sid)
            if not isinstance(config, dict):
                continue
            ids = group.get("ids") or []
            nodes = group.get("nodes") or []
            rotations = group.get("rotations") or []
            for object_id, anchor, rotation in zip(ids, nodes, rotations):
                if not isinstance(object_id, int) or object_id in exclude_ids:
                    continue
                occupied = single.occupied_nodes_for_object_instance(
                    sid, config, int(anchor), int(rotation or 0)
                )
                gates = single.gate_nodes_for_object_instance(
                    sid, config, int(anchor), int(rotation or 0)
                )
                if node in occupied or node in gates:
                    owners.append((object_id, sid))
        return owners
    finally:
        single.OLDEN_WIDTH = previous_w
        single.OLDEN_HEIGHT = previous_h


def clear_subterranean_portal_gate_cells(
    objects: list[dict[str, Any]],
    properties: dict[str, Any] | None,
    *,
    stock_object_configs: dict[str, dict[str, Any]],
    atlas_width: int,
    atlas_height: int,
) -> dict[str, Any]:
    """Remove clearable OCC that buries subterranean portal GATE markers."""
    index = _object_index(objects)
    previous_w, previous_h = single.OLDEN_WIDTH, single.OLDEN_HEIGHT
    single.OLDEN_WIDTH = atlas_width
    single.OLDEN_HEIGHT = atlas_height
    try:
        portal_ids: set[int] = set()
        portal_gates: set[int] = set()
        for object_id, (sid, node, rotation) in index.items():
            if sid != STOCK_SUBTERRANEAN_GATE_SID:
                continue
            config = stock_object_configs.get(sid)
            if not isinstance(config, dict):
                raise VanillaStockAccessError(f"missing stock config for {sid}")
            portal_ids.add(object_id)
            portal_gates |= set(
                single.gate_nodes_for_object_instance(sid, config, node, rotation)
            )
        if not portal_gates:
            return {
                "status": "skipped_no_subterranean_portals",
                "policy": "vanilla_stock_subterranean_portal_gate_clear",
                "gateNodeCount": 0,
                "clearedObjectCount": 0,
                "clearedObjectIds": [],
                "examples": [],
            }

        cleared: list[dict[str, Any]] = []
        remove_ids: set[int] = set()
        for gate in sorted(portal_gates):
            foreign: list[tuple[int, str]] = []
            for occ_id, occ_sid in _owners_at_node(
                objects,
                stock_object_configs,
                gate,
                exclude_ids=portal_ids,
                atlas_width=atlas_width,
                atlas_height=atlas_height,
            ):
                config = stock_object_configs.get(occ_sid)
                if not isinstance(config, dict):
                    raise VanillaStockAccessError(
                        f"missing config while clearing portal GATE for {occ_sid}"
                    )
                owner = index.get(occ_id)
                if owner is None:
                    raise VanillaStockAccessError(f"missing object index for {occ_id}")
                _sid, anchor, rotation = owner
                occupied = single.occupied_nodes_for_object_instance(
                    occ_sid, config, anchor, rotation
                )
                if gate not in occupied:
                    continue
                if occ_sid == "random-squad":
                    foreign.append((occ_id, occ_sid))
                    continue
                if _is_clearable_sid(occ_sid):
                    remove_ids.add(occ_id)
                    cleared.append(
                        {
                            "gateNode": gate,
                            "clearedObjectId": occ_id,
                            "clearedSid": occ_sid,
                        }
                    )
                else:
                    foreign.append((occ_id, occ_sid))
            if foreign:
                raise VanillaStockAccessError(
                    f"subterranean portal GATE {gate} buried by non-clearable OCC {foreign}"
                )
        if remove_ids:
            _remove_object_ids(objects, remove_ids)
            _remove_property_rows(properties, remove_ids)
        return {
            "status": "applied",
            "policy": "vanilla_stock_subterranean_portal_gate_clear",
            "gateNodeCount": len(portal_gates),
            "clearedObjectCount": len(remove_ids),
            "clearedObjectIds": sorted(remove_ids),
            "examples": cleared[:20],
            "proofBoundary": PROOF_BOUNDARY,
        }
    finally:
        single.OLDEN_WIDTH = previous_w
        single.OLDEN_HEIGHT = previous_h


def clear_town_gate_south_approaches(
    objects: list[dict[str, Any]],
    properties: dict[str, Any] | None,
    *,
    stock_object_configs: dict[str, dict[str, Any]],
    atlas_width: int,
    atlas_height: int,
) -> dict[str, Any]:
    """Clear suppressible scenery from each town GATE's unique south approach."""
    index = _object_index(objects)
    previous_w, previous_h = single.OLDEN_WIDTH, single.OLDEN_HEIGHT
    single.OLDEN_WIDTH = atlas_width
    single.OLDEN_HEIGHT = atlas_height
    try:
        cleared: list[dict[str, Any]] = []
        for object_id, (sid, node, rotation) in sorted(index.items()):
            if not (sid.endswith("_city") or sid in {"random-city", "human_city"}):
                continue
            config = stock_object_configs.get(sid)
            if not isinstance(config, dict):
                continue
            gates = single.gate_nodes_for_object_instance(sid, config, node, rotation)
            if not gates:
                continue
            for gate in sorted(gates):
                approach = gate - atlas_width  # Olden +Y = north; south = lower y
                if approach < 0:
                    continue
                remove_ids: set[int] = set()
                for occ_id, occ_sid in _owners_at_node(
                    objects,
                    stock_object_configs,
                    approach,
                    exclude_ids={object_id},
                    atlas_width=atlas_width,
                    atlas_height=atlas_height,
                ):
                    if occ_sid == "random-squad":
                        continue
                    if _is_clearable_sid(occ_sid):
                        remove_ids.add(occ_id)
                if remove_ids:
                    _remove_object_ids(objects, remove_ids)
                    _remove_property_rows(properties, remove_ids)
                    cleared.append(
                        {
                            "hostObjectId": object_id,
                            "hostSid": sid,
                            "gateNode": gate,
                            "approachNode": approach,
                            "clearedObjectIds": sorted(remove_ids),
                        }
                    )
        return {
            "status": "applied",
            "policy": "vanilla_stock_town_gate_south_approach_clear",
            "clearedApproachCount": len(cleared),
            "clearedObjectIds": sorted(
                {
                    object_id
                    for row in cleared
                    for object_id in (row.get("clearedObjectIds") or [])
                }
            ),
            "examples": cleared[:12],
            "proofBoundary": PROOF_BOUNDARY,
        }
    finally:
        single.OLDEN_WIDTH = previous_w
        single.OLDEN_HEIGHT = previous_h


def apply_stock_access_pass(
    objects: list[dict[str, Any]],
    properties: dict[str, Any] | None,
    *,
    stock_object_configs: dict[str, dict[str, Any]],
    atlas_width: int,
    atlas_height: int,
) -> dict[str, Any]:
    portal = clear_subterranean_portal_gate_cells(
        objects,
        properties,
        stock_object_configs=stock_object_configs,
        atlas_width=atlas_width,
        atlas_height=atlas_height,
    )
    town = clear_town_gate_south_approaches(
        objects,
        properties,
        stock_object_configs=stock_object_configs,
        atlas_width=atlas_width,
        atlas_height=atlas_height,
    )
    cleared_ids = sorted(
        set(portal.get("clearedObjectIds") or []) | set(town.get("clearedObjectIds") or [])
    )
    return {
        "schema": SCHEMA,
        "status": "applied",
        "policy": "vanilla_stock_portal_and_town_approach_clear",
        "subterraneanPortalGateClear": portal,
        "townGateSouthApproachClear": town,
        "clearedObjectIds": cleared_ids,
        "proofBoundary": PROOF_BOUNDARY,
    }
