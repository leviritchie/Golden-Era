"""Visual-only HoMM3 DEF billboards for map objects that have no Olden Era stand-in.

The user accepted (2026-09-26) that these HoMM3 objects are drawn as a static sprite from their
own DEF art and do nothing else. HoMM3 objects covered: Garrison (33, 219), derelict ship (24),
cover of darkness (15), mermaids (52), obelisk (57), pyramid (63), shipwreck (85), sirens (92),
one-way monolith entrance/exit (43, 44), war machine factory (106), and the Keymaster's Tent (10),
whose function is already the border key-gate zone marker (``border_guard_gates.py``).

Host: one inert custom SID per DEF (``homm3_objbb_<def stem>``). The ObjectConfig is the
``homm3_seer_hut`` shell (``interactive/wise_owl`` prefab, 2x2, generatorConfig), the only
custom Interact host that is live-positive for placement and map-object Init. Two things differ:

* ``nodes`` is ``[1, 0, 0, 0]``: one blocked cell at the anchor and no GATE, so there is
  nothing to visit;
* there is no ``objects_logic`` row. The seer hut history (``tools/map_load_preflight.py``,
  ``ensure_homm3_seer_hut_objectconfig``) records that without an event bank the host loads and
  the cursor treats it as scenery.

The host sits on one of the object's own HoMM3 non-visitable blocked cells (the visit cell for
the one-way monoliths and the obelisk, which have no other cell and no Olden Era function). It prefers a cell
that holds a synthetic 1x1 gap fill (the scenery or invisible blocker the gap-fill pass plants on
HoMM3 blocked cells) and replaces it, so pathing is unchanged. Otherwise it takes a free blocked
cell that is no GATE or marker and leaves every adjacent GATE or marker at least two open approaches, which blocks a cell HoMM3
blocked too. A placement with no such cell is left undrawn and reported with its reason.

The runtime draws the sprite on the host (``Homm3ArtifactMapBillboard.cs``, SID prefix
``homm3_objbb_``). The PNGs are built by ``tools/build_homm3_object_billboard_assets.py``. A missing
image or a failed apply is a LogError there, not a silent blank.

Proof tier: generated artifact. The host shape without GATE or event bank, and the billboard on
it, are runtime-unproven.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

SID_PREFIX = "homm3_objbb_"
HOST_DONOR_PREFAB = "interactive/wise_owl"
HOST_NODES = [1, 0, 0, 0]
OBJECT_BILLBOARD_ID_BASE = 990_000
OVERLAY_MEMBER = "DB/map/objects/4_interactables.json"
NEVER_REPLACED_SIDS = frozenset({"campaign_FX_block"})
MIN_OPEN_APPROACHES = 2
# One-way monoliths and the obelisk occupy only their visit cell. With no Olden Era function the
# host may take that cell. Never garrisons (their visit cell is the passage) or tents (it holds
# the key marker).
VISIT_CELL_HOST_IDS = frozenset({43, 44, 57})
SCHEMA = "homm3_object_billboards.v1"

# HoMM3 object id -> name.
BILLBOARD_TEMPLATE_IDS: dict[int, str] = {
    10: "Keymaster's Tent",
    15: "Cover of Darkness",
    24: "Derelict Ship",
    33: "Garrison",
    43: "One-Way Monolith Entrance",
    44: "One-Way Monolith Exit",
    52: "Mermaids",
    57: "Obelisk",
    63: "Pyramid",
    85: "Shipwreck",
    92: "Sirens",
    106: "War Machine Factory",
    219: "Garrison (vertical)",
}

# DEF (H3sprite.lod) per HoMM3 object id, from the placement census. A placement whose DEF is
# not listed fails the mission, so an unseen variant cannot silently draw nothing.
BILLBOARD_DEFS: dict[int, tuple[str, ...]] = {
    10: ("avxkey00", "avxkey10", "avxkey20", "avxkey30", "avxkey40", "avxkey50", "avxkey60", "avxkey70"),
    15: ("avxcovr0",),
    24: ("avadlic0",),
    33: ("avcgar10", "avcgar20"),
    43: ("avxmn1b0", "avxmn1r0", "avxmn1y0", "avxmn5i0", "avxmn6i0", "avxmn7i0", "avxmn8i0"),
    44: ("avxmx1b0", "avxmx1r0", "avxmx1y0", "avxmn5o0", "avxmn6o0", "avxmn7o0", "avxmn8o0"),
    52: ("avxmerm0",),
    57: ("avxoblg", "avxoblw"),
    63: ("avxprmd0",),
    85: ("avawre20", "avawrek0"),
    92: ("avxsirn0",),
    106: ("avgsieg0",),
    219: ("avcvgarm", "avcvgr"),
}


def def_stem(animation: str) -> str:
    stem = animation.strip().lower()
    if stem.endswith(".def"):
        stem = stem[:-4]
    if not stem or not all("a" <= c <= "z" or "0" <= c <= "9" or c == "_" for c in stem):
        raise ValueError(f"unsupported HoMM3 DEF name for an object billboard: {animation!r}")
    return stem


def sid_for_def(animation: str) -> str:
    return SID_PREFIX + def_stem(animation)


def all_billboard_defs() -> list[str]:
    return sorted({d for defs in BILLBOARD_DEFS.values() for d in defs})


def all_billboard_sids() -> list[str]:
    return [sid_for_def(d) for d in all_billboard_defs()]


def host_object_row(sid: str) -> dict[str, Any]:
    """Inert Interact host: the homm3_seer_hut shell with one blocked cell and no GATE."""
    if not sid.startswith(SID_PREFIX):
        raise ValueError(f"not an object billboard SID: {sid!r}")
    return {
        "id": sid,
        "tag": "Interact",
        "isInteractable": True,
        "prefs": [HOST_DONOR_PREFAB],
        "canBeMirrored": False,
        "selectionUiPrefabID": "1x1",
        "pivotX": 0,
        "pivotZ": 0,
        "sizeX": 2,
        "sizeZ": 2,
        "offsetX": 0,
        "offsetZ": 0,
        "nodes": list(HOST_NODES),
        "generatorConfig": {
            "buildingSizeX": 1,
            "buildingSizeZ": 1,
            "buildingLeftBottomX": 0,
            "buildingLeftBottomZ": 0,
            "buildingInteractionLayout": 0,
        },
    }


def _template_id(entity: dict[str, Any]) -> int | None:
    value = entity.get("templateObjectId")
    return value if isinstance(value, int) else None


def _occupancy(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    source_ids: set[int],
    single: Any,
) -> tuple[dict[int, list[tuple[int, str]]], dict[int, list[tuple[int, str]]], dict[int, tuple[int, str, float]]]:
    """(node -> occupying (id, sid)), (GATE node -> owning (id, sid)), and node -> replaceable gap fill.

    A replaceable gap fill is a synthetic (non-source) 1x1 non-Interact object whose only cell
    blocks: the invisible ``homm3_pathing_blocker`` or the scenery the gap-fill pass plants on a
    HoMM3 blocked cell. Key-gate blocks are never replaced.
    """
    occupied: dict[int, list[tuple[int, str]]] = {}
    gates: dict[int, list[tuple[int, str]]] = {}
    gap_fill: dict[int, tuple[int, str, float]] = {}
    for group in objects:
        sid = group.get("sid")
        config = native_object_configs.get(sid) if isinstance(sid, str) else None
        if not isinstance(config, dict):
            raise ValueError(f"object billboards: no ObjectConfig for emitted group {sid!r}")
        levels = group.get("levels") or []
        replaceable_shape = (
            sid not in NEVER_REPLACED_SIDS
            and not str(sid).startswith(SID_PREFIX)
            and config.get("nodes") == [1]
            and int(config.get("sizeX") or 1) == 1
            and int(config.get("sizeZ") or 1) == 1
            and config.get("tag") != "Interact"
        )
        for index, (object_id, node, rotation) in enumerate(
            zip(group.get("ids") or [], group.get("nodes") or [], group.get("rotations") or [])
        ):
            node, rotation = int(node), int(rotation or 0)
            for cell in single.occupied_nodes_for_object_instance(sid, config, node, rotation):
                occupied.setdefault(int(cell), []).append((int(object_id), sid))
            for cell in single.nodes_for_object_instance_with_value(sid, config, node, rotation, node_value=2):
                gates.setdefault(int(cell), []).append((int(object_id), sid))
            if replaceable_shape and int(object_id) not in source_ids:
                level = float(levels[index]) if index < len(levels) else 0.0
                gap_fill[node] = (int(object_id), sid, level)
    return occupied, gates, gap_fill


def _ranked_body_cells(entity: dict[str, Any], single: Any) -> list[tuple[int, int]]:
    """HoMM3 non-visitable blocked cells, bottom row first, nearest the row's centre first.

    Objects in ``VISIT_CELL_HOST_IDS`` have no such cell, so their HoMM3 visit cell is the
    candidate instead: it is blocked in HoMM3 and has no function in Olden Era.
    """
    offsets = sorted(single.entity_nonvisitable_block_offsets(entity))
    if not offsets and _template_id(entity) in VISIT_CELL_HOST_IDS:
        offsets = sorted(single.source_visit_offsets(entity))
    if not offsets:
        return []
    bottom = max(dy for _dx, dy in offsets)
    row = [dx for dx, dy in offsets if dy == bottom]
    centre2 = min(row) + max(row)  # twice the bottom-row centre, integer
    sx, sy = int(entity["sourceX"]), int(entity["sourceY"])
    ranked = sorted(offsets, key=lambda o: (bottom - o[1], abs(2 * o[0] - centre2), o[0]))
    return [(sx + dx, sy + dy) for dx, dy in ranked]


def _neighbours4(node: int, width: int, height: int) -> list[int]:
    x, y = node % width, node // width
    out = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < width and 0 <= ny < height:
            out.append(ny * width + nx)
    return out


def apply_object_billboard_hosts(
    *,
    global_entities: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    single: Any,
    lob: Any,
    marker_nodes: set[int],
    width: int,
    height: int,
) -> dict[str, Any]:
    """Put one inert billboard host on a HoMM3 blocked cell of each covered object.

    Cell choice per placement, over the object's own HoMM3 non-visitable blocked cells in
    bottom-centre order:
      1. a cell holding a synthetic 1x1 gap fill: the gap fill is replaced, pathing unchanged;
      2. otherwise a free cell that is no object's cell, GATE or marker, and whose every
         neighbouring GATE or marker keeps at least ``MIN_OPEN_APPROACHES`` open 4-neighbours
         with it blocked, so no approach is sealed. It blocks a cell HoMM3 blocked too.
    No such cell: the placement stays undrawn and is reported.
    Must run after the last occupancy pass and before the placement ground truth.
    """
    source_ids = {int(e["sourceIndex"]) for e in global_entities if isinstance(e.get("sourceIndex"), int)}
    occupied, gates, gap_fill = _occupancy(objects, native_object_configs, source_ids, single)
    guarded = set(gates) | {int(n) for n in marker_nodes}
    used_ids = {int(i) for group in objects for i in (group.get("ids") or [])}
    next_id = OBJECT_BILLBOARD_ID_BASE
    hosts: dict[int, dict[str, Any]] = {}
    unplaced: list[dict[str, Any]] = []
    remove_ids: set[int] = set()
    taken: set[int] = set()
    by_sid: Counter[str] = Counter()
    by_mode: Counter[str] = Counter()
    for entity in global_entities:
        tid = _template_id(entity)
        if tid not in BILLBOARD_TEMPLATE_IDS:
            continue
        source_index = entity.get("sourceIndex")
        layer = entity.get("sourceLayer")
        if not isinstance(source_index, int) or not isinstance(layer, int) or not lob.in_source_bounds(entity):
            continue
        animation = str(entity.get("templateAnimation") or "")
        stem = def_stem(animation)
        if stem not in BILLBOARD_DEFS[tid]:
            raise ValueError(
                f"HoMM3 object {tid} ({BILLBOARD_TEMPLATE_IDS[tid]}) placement {entity.get('sourceKey')} uses "
                f"DEF {animation!r}, which has no billboard; add it to object_billboards.BILLBOARD_DEFS"
            )
        sid = sid_for_def(animation)
        cells: list[tuple[int, int, int]] = []
        with lob.single_projection_context(layer):
            for sx, sy in _ranked_body_cells(entity, single):
                if 0 <= sx < single.SOURCE_WIDTH and 0 <= sy < single.SOURCE_HEIGHT:
                    cells.append((sx, sy, single.target_node(sx, sy)))
        chosen = None
        for sx, sy, node in cells:
            hit = gap_fill.get(node)
            if node not in taken and hit is not None and hit[0] not in remove_ids:
                chosen = (node, sx, sy, "replaced_gap_fill", hit)
                break
        def seals_approach(node: int) -> bool:
            for g in _neighbours4(node, width, height):
                if g not in guarded:
                    continue
                open_n = [
                    n for n in _neighbours4(g, width, height)
                    if n != node and n not in occupied and n not in taken and n not in guarded
                ]
                if len(open_n) < MIN_OPEN_APPROACHES:
                    return True
            return False

        if chosen is None:
            for sx, sy, node in cells:
                if node not in taken and node not in occupied and node not in guarded and not seals_approach(node):
                    chosen = (node, sx, sy, "free_homm3_blocked_cell", None)
                    break
        if chosen is None:
            unplaced.append({
                "sourceIndex": source_index,
                "sourceKey": entity.get("sourceKey"),
                "objectId": tid,
                "def": stem,
                "reason": "no HoMM3 blocked cell of the object is a gap fill or a free cell that leaves every adjacent GATE/marker open",
                "cells": [
                    {
                        "cell": [sx, sy],
                        "node": node,
                        "occupiedBy": [s for _i, s in occupied.get(node, [])],
                        "gateOf": [s for _i, s in gates.get(node, [])],
                        "marker": node in marker_nodes,
                        "wouldSealApproach": node not in guarded and seals_approach(node),
                    }
                    for sx, sy, node in cells
                ],
            })
            continue
        node, sx, sy, mode, hit = chosen
        while next_id in used_ids:
            next_id += 1
        object_id = next_id
        used_ids.add(object_id)
        taken.add(node)
        level = 0.0
        host: dict[str, Any] = {
            "sid": sid,
            "objectId": object_id,
            "node": node,
            "sourceCell": [sx, sy],
            "mode": mode,
            "templateObjectId": tid,
        }
        if hit is not None:
            remove_ids.add(hit[0])
            level = hit[2]
            host["replacedGapFill"] = {"objectId": hit[0], "sid": hit[1]}
        single.append_object_instances(objects, sid, [object_id], [node], [0], [level])
        native_object_configs.setdefault(sid, host_object_row(sid))
        by_sid[sid] += 1
        by_mode[mode] += 1
        hosts[source_index] = host
    _remove_object_ids(objects, remove_ids)
    return {
        "schema": SCHEMA,
        "placed": len(hosts),
        "unplacedCount": len(unplaced),
        "unplaced": unplaced,
        "bySid": dict(sorted(by_sid.items())),
        "byMode": dict(sorted(by_mode.items())),
        "hosts": {str(k): v for k, v in sorted(hosts.items())},
        "policy": "visual_only_homm3_def_billboard_on_inert_interact_host_on_a_homm3_blocked_cell",
        "proofBoundary": "generated artifact; host shape and runtime billboard unproven",
    }


def hosts_by_source_index(report: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(k): v for k, v in (report.get("hosts") or {}).items()}


def write_host_overlay(core_overlay_root: Path, sids: set[str]) -> dict[str, Any]:
    """Append the host ObjectConfig rows to the mission overlay 4_interactables.json.

    Custom Interact hosts must live in 4_interactables.json: the seer hut was placed but never
    got a map-object Init from homecoming_custom_objects.json (map_load_preflight history).
    """
    path = core_overlay_root / OVERLAY_MEMBER
    doc = json.loads(path.read_text(encoding="utf-8-sig")) if path.is_file() else {"array": []}
    rows = doc.get("array")
    if not isinstance(rows, list):
        raise ValueError(f"{path} has no array")
    existing = {row.get("id"): row for row in rows if isinstance(row, dict)}
    added = 0
    for sid in sorted(sids):
        want = host_object_row(sid)
        have = existing.get(sid)
        if have is None:
            rows.append(want)
            added += 1
        elif have != want:
            raise ValueError(f"{path} already has a different {sid!r} row: {have}")
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {"member": OVERLAY_MEMBER, "rowsAdded": added, "sids": sorted(sids)}


def _remove_object_ids(objects: list[dict[str, Any]], remove_ids: set[int]) -> None:
    if not remove_ids:
        return
    for group in objects:
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        levels = group.get("levels") or []
        keep = [i for i, oid in enumerate(ids) if oid not in remove_ids]
        group["ids"] = [ids[i] for i in keep]
        group["nodes"] = [nodes[i] for i in keep]
        group["rotations"] = [rotations[i] for i in keep]
        if levels:
            group["levels"] = [levels[i] for i in keep if i < len(levels)]
    objects[:] = [group for group in objects if (group.get("ids") or [])]
