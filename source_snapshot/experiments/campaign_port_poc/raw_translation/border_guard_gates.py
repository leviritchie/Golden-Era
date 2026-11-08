"""HoMM3 key-gated passages (Border Guard 9, Border Gate 212, Keymaster's Tent 10) on native OE.

HoMM3: a Keymaster's Tent of colour C gives the visiting player the C key; a Border Guard of
colour C then vanishes for that player and a Border Gate of colour C lets key holders through.

Native Olden Era has no key object. The native key-gated passage is Core
``DB/map/objects/9_blocks.json`` ``campaign_FX_block`` (fx_map_smoke, one blocked node): story
maps give each block a propEntities SID and delete it from QuestScript
(``Counter(key,"=",1)`` -> ``DeleteEntity``, e.g. all_cats_go_to_heaven). This module wires
exactly that:

* Border Guard (9): the substitution map emits ``campaign_FX_block`` on the guard cell
  (``border_guard_to_campaign_fx_block_key_gate``); here it gets an entity SID.
* Border Gate (212): keeps its ``fx_quest_mark_gold_01`` marker and gains a
  ``campaign_FX_block`` on its HoMM3 visit (passage) cell, which was open before.
* Keymaster's Tent (10): an invisible ``Zone 1x1`` marker on the tent's HoMM3 visit cell
  (the map-event host pattern) with ``propActionsBefore`` Dialog and ``propActionsAfter``
  ``CounterSet <mission>_border_key_<colour> 1``.
* One hidden quest per colour that has a tent and at least one guard/gate:
  ``Counter(key,"=",1)`` -> ``DeleteEntity`` for every block of that colour.

The gate passage cell must be free. The Olden resource-pile body sits one cell off its
HoMM3 tile and can land on it, so the pickup anchoring pass keeps pile bodies off gate
passages and tent cells (``surface_emit.key_gate_reserved_cells``, the same clearance it
gives mine bodies); any occupant left on a passage fails the mission. A tent visit cell can
still sit under a larger Olden body (a town, an artifact or camp-fire body offset onto it);
its marker then moves to the first free HoMM3-passable land neighbour of that cell, front
(HoMM3 south) first, preferring a cell no object is anchored on over the walkable anchor of
a visitable neighbour (a pickup the hero stands on anyway); recorded as
``visitNodeRelocation``. No free neighbour fails the mission.

Behaviour difference (accepted by the user 2026-09-26 as a deliberate difference from
HoMM3): the block is deleted for everyone once any side visits the tent, not only for the
key holder. A colour with guards but no tent stays
closed, as in HoMM3.

Proof tier: generated artifact. Runtime deletion of campaign_FX_block via DeleteEntity is the
native story-map pattern but is unproven on these maps.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

BORDER_GUARD_TEMPLATE_ID = 9
KEYMASTER_TENT_TEMPLATE_ID = 10
BORDER_GATE_TEMPLATE_ID = 212
KEY_GATE_BLOCK_SID = "campaign_FX_block"
# Clear of envelope padding (920_000 + up to 2 x 80 x 80) and the other synthetic id bases.
BORDER_GATE_BLOCK_ID_BASE = 970_000
TENT_HOST_MODE = "keymaster_tent_zone_marker"
SCHEMA = "homm3_border_key_gates.v1"

# HoMM3 key colours (object subtype 0..7).
KEY_COLOUR_NAMES = {
    0: "Light Blue",
    1: "Green",
    2: "Red",
    3: "Dark Blue",
    4: "Brown",
    5: "Purple",
    6: "White",
    7: "Black",
}


def key_counter_sid(mission_id: str, colour: int) -> str:
    return f"{mission_id}_border_key_{colour}"


def guard_entity_sid(mission_id: str, object_id: int) -> str:
    return f"{mission_id}_border_block_{object_id}"


def tent_entity_sid(mission_id: str, object_id: int) -> str:
    return f"{mission_id}_keymaster_tent_{object_id}"


def tent_dialog_sid(mission_id: str, colour: int) -> str:
    return f"{mission_id}_keymaster_tent_{colour}_dialog"


def gate_quest_sid(mission_id: str, colour: int) -> str:
    return f"{mission_id}_border_gate_{colour}"


def _colour(entity: dict[str, Any]) -> int:
    subtype = entity.get("templateSubtype")
    if not isinstance(subtype, int) or subtype not in KEY_COLOUR_NAMES:
        raise ValueError(
            f"border key object {entity.get('sourceKey')!r} (template "
            f"{entity.get('templateObjectId')}) has no key colour subtype: {subtype!r}"
        )
    return subtype


def _instances_by_id(objects: list[dict[str, Any]]) -> dict[int, tuple[str, int]]:
    out: dict[int, tuple[str, int]] = {}
    for group in objects:
        sid = group.get("sid")
        for object_id, node in zip(group.get("ids") or [], group.get("nodes") or []):
            if isinstance(object_id, int):
                out[object_id] = (str(sid), int(node))
    return out


def _single_visit_node(entity: dict[str, Any], *, single: Any, lob: Any) -> int:
    layer = int(entity.get("sourceLayer") or 0)
    with lob.single_projection_context(layer):
        nodes = sorted(single.entity_visit_nodes(entity))
    if len(nodes) != 1:
        raise ValueError(
            f"border key object {entity.get('sourceKey')!r} (template "
            f"{entity.get('templateObjectId')}) needs exactly one HoMM3 visit cell; got {nodes}"
        )
    return nodes[0]


# HoMM3 source deltas from a tent visit cell, front (south, the approach side) first.
TENT_RELOCATION_SOURCE_DELTAS = ((0, 1), (-1, 0), (1, 0), (0, -1), (-1, 1), (1, 1), (-1, -1), (1, -1))


def _homm3_blocked_source_cells(global_entities: list[dict[str, Any]], *, single: Any, layer: int) -> set[tuple[int, int]]:
    cells: set[tuple[int, int]] = set()
    for entity in global_entities:
        if not isinstance(entity, dict) or int(entity.get("sourceLayer") or 0) != layer:
            continue
        sx, sy = entity.get("sourceX"), entity.get("sourceY")
        if not isinstance(sx, int) or not isinstance(sy, int):
            continue
        cells |= {(sx + dx, sy + dy) for dx, dy in single.entity_nonvisitable_block_offsets(entity)}
    return cells


def _occupied_cells(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    single: Any,
) -> dict[int, list[tuple[int, str]]]:
    occupied: dict[int, list[tuple[int, str]]] = defaultdict(list)
    for group in objects:
        sid = str(group.get("sid"))
        config = native_object_configs.get(sid)
        if not isinstance(config, dict):
            continue
        for object_id, node, rotation in zip(group.get("ids") or [], group.get("nodes") or [], group.get("rotations") or []):
            for cell in single.occupied_nodes_for_object_instance(sid, config, int(node), int(rotation)):
                occupied[int(cell)].append((int(object_id), sid))
    return occupied


def apply_border_key_gate_hosts(
    *,
    mission_id: str,
    global_entities: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    markers: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    single: Any,
    lob: Any,
    land_cell: Any,
) -> dict[str, Any]:
    """Bind guard/gate blocks and tent zone markers in place. Returns the plan/report.

    ``land_cell(node)`` says whether an atlas node is walkable land (tent relocation only).

    Must run before ``rebase_native_event_marker_ids`` (tent markers use local ids like the
    map-event markers) and before the final orphan-property scrub.
    """
    guards: dict[int, list[dict[str, Any]]] = defaultdict(list)
    tents: dict[int, list[dict[str, Any]]] = defaultdict(list)
    skipped: list[dict[str, Any]] = []
    instances = _instances_by_id(objects)
    occupied_nodes = {node for _, node in instances.values()}
    occupied_cells = _occupied_cells(objects, native_object_configs, single)
    marker_nodes = {int(m["node"]) for m in markers if isinstance(m.get("node"), int)}
    next_gate_block_id = BORDER_GATE_BLOCK_ID_BASE
    gate_passage_nodes = {
        _single_visit_node(entity, single=single, lob=lob)
        for entity in global_entities
        if isinstance(entity, dict)
        and entity.get("templateObjectId") == BORDER_GATE_TEMPLATE_ID
        and isinstance(entity.get("sourceIndex"), int)
        and lob.in_source_bounds(entity)
    }
    blocked_source_by_layer: dict[int, set[tuple[int, int]]] = {}

    for entity in global_entities:
        if not isinstance(entity, dict):
            continue
        template_id = entity.get("templateObjectId")
        if template_id not in (BORDER_GUARD_TEMPLATE_ID, KEYMASTER_TENT_TEMPLATE_ID, BORDER_GATE_TEMPLATE_ID):
            continue
        source_index = entity.get("sourceIndex")
        if not isinstance(source_index, int):
            continue
        if not lob.in_source_bounds(entity):
            skipped.append({"sourceIndex": source_index, "templateObjectId": template_id, "reason": "border_overhang"})
            continue
        colour = _colour(entity)
        if template_id == BORDER_GUARD_TEMPLATE_ID:
            instance = instances.get(source_index)
            if instance is None or instance[0] != KEY_GATE_BLOCK_SID:
                raise ValueError(
                    f"{mission_id}: border guard {entity.get('sourceKey')!r} (object {source_index}) "
                    f"must be emitted as {KEY_GATE_BLOCK_SID}; found {instance!r}"
                )
            entity_sid = guard_entity_sid(mission_id, source_index)
            properties.setdefault("propEntities", []).append({"type": 0, "id": source_index, "sid": entity_sid})
            guards[colour].append(
                {"kind": "border_guard", "objectId": source_index, "node": instance[1], "entitySid": entity_sid, "sourceKey": entity.get("sourceKey")}
            )
        elif template_id == BORDER_GATE_TEMPLATE_ID:
            node = _single_visit_node(entity, single=single, lob=lob)
            if node in occupied_nodes or node in occupied_cells or node in marker_nodes:
                owners = sorted({*occupied_cells.get(node, []), *((oid, sid) for oid, (sid, n) in instances.items() if n == node)})
                raise ValueError(
                    f"{mission_id}: border gate {entity.get('sourceKey')!r} passage node {node} is already "
                    f"occupied by {owners}{' and a marker' if node in marker_nodes else ''}"
                )
            object_id = next_gate_block_id
            next_gate_block_id += 1
            if object_id in instances:
                raise ValueError(f"{mission_id}: border gate block id {object_id} is already used")
            single.append_object_instances(objects, KEY_GATE_BLOCK_SID, [object_id], [node], [0], [0.0])
            occupied_nodes.add(node)
            occupied_cells[node].append((object_id, KEY_GATE_BLOCK_SID))
            entity_sid = guard_entity_sid(mission_id, object_id)
            properties.setdefault("propEntities", []).append({"type": 0, "id": object_id, "sid": entity_sid})
            guards[colour].append(
                {"kind": "border_gate", "objectId": object_id, "gateSourceIndex": source_index, "node": node, "entitySid": entity_sid, "sourceKey": entity.get("sourceKey")}
            )
        else:
            node = _single_visit_node(entity, single=single, lob=lob)
            relocation = None
            if node in marker_nodes or occupied_cells.get(node):
                layer = int(entity.get("sourceLayer") or 0)
                if layer not in blocked_source_by_layer:
                    blocked_source_by_layer[layer] = _homm3_blocked_source_cells(global_entities, single=single, layer=layer)
                (vdx, vdy), = single.source_visit_offsets(entity)
                vx, vy = int(entity["sourceX"]) + vdx, int(entity["sourceY"]) + vdy
                tried: list[dict[str, Any]] = []
                chosen = None
                shares_anchor: list[list[Any]] = []
                # Pass 0: a cell nothing stands on. Pass 1: the walkable anchor (GATE) of a
                # HoMM3-visitable neighbour such as a pickup - the hero stands there anyway
                # to reach the tent. Never an Olden OCC cell or a HoMM3 impassable cell.
                for allow_anchor in (False, True):
                    for ddx, ddy in TENT_RELOCATION_SOURCE_DELTAS:
                        cell = (vx + ddx, vy + ddy)
                        with lob.single_projection_context(layer):
                            try:
                                candidate = single.target_node_allowing_source_padding(*cell)
                            except ValueError:
                                tried.append({"source": list(cell), "reason": "outside_envelope"})
                                continue
                        anchors = sorted([oid, sid] for oid, (sid, n) in instances.items() if n == candidate)
                        if cell in blocked_source_by_layer[layer]:
                            reason = "homm3_impassable"
                        elif occupied_cells.get(candidate):
                            reason = f"occupied_by_{occupied_cells[candidate]}"
                        elif candidate in marker_nodes or candidate in gate_passage_nodes:
                            reason = "marker_or_gate_passage"
                        elif not land_cell(candidate):
                            reason = "not_land"
                        elif anchors and not allow_anchor:
                            reason = f"object_anchor_{anchors}"
                        else:
                            chosen = candidate
                            shares_anchor = anchors
                            break
                        tried.append({"source": list(cell), "node": candidate, "reason": reason, "pass": int(allow_anchor)})
                    if chosen is not None:
                        break
                if chosen is None:
                    raise ValueError(
                        f"{mission_id}: keymaster tent {entity.get('sourceKey')!r} visit node {node} is occupied by "
                        f"{occupied_cells.get(node) or 'a marker'} and no neighbour is free: {tried}"
                    )
                relocation = {
                    "fromNode": node,
                    "toNode": chosen,
                    "occupiedBy": [list(owner) for owner in occupied_cells.get(node) or []],
                    "sourceCell": [vx, vy],
                    "sharesNodeWithAnchor": shares_anchor,
                    "rejected": tried,
                }
                node = chosen
            marker_id = len(markers)
            entity_sid = tent_entity_sid(mission_id, source_index)
            properties.setdefault("propEntities", []).append({"type": 1, "id": marker_id, "sid": entity_sid})
            properties.setdefault("propActionsBefore", []).append(
                {
                    "type": 1,
                    "id": marker_id,
                    "repeat": False,
                    "sides": "",
                    "computerActivate": True,
                    "actions": [{"comment": "", "a": "Dialog", "p": [tent_dialog_sid(mission_id, colour)]}],
                }
            )
            properties.setdefault("propActionsAfter", []).append(
                {
                    "type": 1,
                    "id": marker_id,
                    "repeat": False,
                    "sides": "",
                    "actions": [{"comment": "", "a": "CounterSet", "p": [key_counter_sid(mission_id, colour), "1"]}],
                }
            )
            properties.setdefault("propMarkers", []).append(
                {"type": 1, "id": marker_id, "isDelete": False, "isActivate": True}
            )
            markers.append(
                {
                    "node": node,
                    "v": "",
                    "sid": "Zone 1x1",
                    "id": marker_id,
                    "sourceIndex": source_index,
                    "sourceKey": entity.get("sourceKey"),
                    "hostMode": TENT_HOST_MODE,
                }
            )
            marker_nodes.add(node)
            tents[colour].append(
                {
                    "objectId": source_index,
                    "node": node,
                    "markerLocalId": marker_id,
                    "entitySid": entity_sid,
                    "sourceKey": entity.get("sourceKey"),
                    **({"visitNodeRelocation": relocation} if relocation else {}),
                }
            )

    colours = sorted(set(guards) | set(tents))
    return {
        "schema": SCHEMA,
        "missionId": mission_id,
        "policy": "native_campaign_fx_block_deleted_by_key_counter_quest",
        "behaviourDifference": "blocks are deleted for every side once any side visits the colour's tent",
        "proofBoundary": "generated_artifact; runtime DeleteEntity of campaign_FX_block unproven on these maps",
        "colours": {
            str(colour): {
                "name": KEY_COLOUR_NAMES[colour],
                "keyCounter": key_counter_sid(mission_id, colour),
                "blocks": guards.get(colour, []),
                "tents": tents.get(colour, []),
                "opens": bool(tents.get(colour)) and bool(guards.get(colour)),
            }
            for colour in colours
        },
        "blockCount": sum(len(v) for v in guards.values()),
        "tentCount": sum(len(v) for v in tents.values()),
        "tentsRelocated": sum(1 for v in tents.values() for t in v if t.get("visitNodeRelocation")),
        "skipped": skipped,
    }


def apply_border_key_gate_script(
    *,
    mission_id: str,
    plan: dict[str, Any],
    chunk3: dict[str, Any],
    properties: dict[str, Any],
) -> list[dict[str, Any]]:
    """Append key counters and per-colour DeleteEntity quests; return dialog entries."""
    live_entity_sids = {
        str(row.get("sid"))
        for row in (properties.get("propEntities") or [])
        if isinstance(row, dict)
    }
    counters = chunk3.setdefault("counters", [])
    quests = chunk3.setdefault("quests", [])
    declared = {str(row.get("sid")) for row in counters if isinstance(row, dict)}
    dialog_entries: list[dict[str, Any]] = []
    for colour_key, row in sorted((plan.get("colours") or {}).items(), key=lambda kv: int(kv[0])):
        colour = int(colour_key)
        name = str(row["name"])
        blocks = list(row.get("blocks") or [])
        tents = list(row.get("tents") or [])
        for block in blocks:
            if block["entitySid"] not in live_entity_sids:
                raise ValueError(f"{mission_id}: border block {block['entitySid']} lost its propEntities row")
        if not tents:
            continue
        for tent in tents:
            if tent["entitySid"] not in live_entity_sids:
                raise ValueError(f"{mission_id}: keymaster tent {tent['entitySid']} lost its propEntities row")
        counter_sid = key_counter_sid(mission_id, colour)
        if counter_sid in declared:
            raise ValueError(f"{mission_id}: key counter {counter_sid} already declared")
        counters.append(
            {
                "comment": f"HoMM3 {name} key (Keymaster's Tent visited)",
                "sid": counter_sid,
                "sharing": "Clone",
                "value": 0,
                "minValue": -2147483648,
                "maxValue": 2147483647,
            }
        )
        declared.add(counter_sid)
        if blocks:
            quest_sid = gate_quest_sid(mission_id, colour)
            quests.append(
                {
                    "sid": quest_sid,
                    "hidden": True,
                    "main": False,
                    "activeOnStart": True,
                    "comment": f"HoMM3 {name} Border Guards/Gates: removed once the {name} Keymaster's Tent is visited",
                    "sharing": "Clone",
                    "name": "",
                    "desc": "",
                    "subQuests": [
                        {
                            "sid": f"{quest_sid}_open",
                            "activeOnStart": True,
                            "hidden": True,
                            "name": "",
                            "desc": "",
                            "comment": "",
                            "triggers": [
                                {
                                    "comment": f"{name} key obtained: delete every {name} border block",
                                    "repeat": False,
                                    "conditions": [
                                        {"comment": "", "c": "Counter", "p": [counter_sid, "=", "1"], "counter": 1}
                                    ],
                                    "actions": [
                                        {"comment": "", "a": "DeleteEntity", "p": [block["entitySid"]]}
                                        for block in blocks
                                    ],
                                    "conditionsLogic": "And",
                                }
                            ],
                        }
                    ],
                    "subQuestGroups": [],
                }
            )
        text = f"The Keymaster greets you and hands over the {name} key."
        if blocks:
            text += f" The {name} Border Guards and Border Gates now stand open."
        dialog_entries.append({"id": tent_dialog_sid(mission_id, colour), "title": "Keymaster's Tent", "text": text})
    return dialog_entries


def verify_border_key_gates_final(
    *,
    plan: dict[str, Any],
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    markers: list[dict[str, Any]],
    properties: dict[str, Any],
    single: Any,
) -> dict[str, Any]:
    """Fail closed on the final map: blocks live on their nodes, tent cells are walkable."""
    mission_id = str(plan.get("missionId"))
    instances = _instances_by_id(objects)
    occupied = _occupied_cells(objects, native_object_configs, single)
    entity_rows = {
        str(row.get("sid")): row for row in (properties.get("propEntities") or []) if isinstance(row, dict)
    }
    markers_by_source = {
        int(m["sourceIndex"]): m for m in markers if m.get("hostMode") == TENT_HOST_MODE
    }
    errors: list[str] = []
    for colour_key, row in (plan.get("colours") or {}).items():
        for block in row.get("blocks") or []:
            instance = instances.get(int(block["objectId"]))
            if instance != (KEY_GATE_BLOCK_SID, int(block["node"])):
                errors.append(f"block {block['entitySid']} is {instance!r}, expected {KEY_GATE_BLOCK_SID} at {block['node']}")
            ent = entity_rows.get(block["entitySid"])
            if not ent or ent.get("type") != 0 or ent.get("id") != block["objectId"]:
                errors.append(f"block {block['entitySid']} propEntities row {ent!r}")
        for tent in row.get("tents") or []:
            marker = markers_by_source.get(int(tent["objectId"]))
            if marker is None or int(marker["node"]) != int(tent["node"]):
                errors.append(f"tent {tent['entitySid']} lost its zone marker")
                continue
            ent = entity_rows.get(tent["entitySid"])
            if not ent or ent.get("type") != 1 or ent.get("id") != marker["id"]:
                errors.append(f"tent {tent['entitySid']} propEntities row {ent!r} does not bind marker {marker['id']}")
            owners = occupied.get(int(tent["node"]))
            if owners:
                errors.append(f"tent {tent['entitySid']} visit node {tent['node']} is occupied by {owners}")
    if errors:
        raise ValueError(f"{mission_id}: border key gate final check failed: " + "; ".join(errors[:8]))
    return {"status": "verified", "blockCount": plan.get("blockCount"), "tentCount": plan.get("tentCount")}
