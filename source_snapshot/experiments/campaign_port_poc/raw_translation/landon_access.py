#!/usr/bin/env python3
"""Raw-translation land-on access fixes (no local_1c / accessibility_repair import).

- Relocate Guardhouse map_event off the unique south approach when it seals GATE.
- Bind Guardhouse dialog onto the dwelling (marker stays cosmetic).
- Clear suppressible scenery from each land-on barracks' unique south approach cell.
"""
from __future__ import annotations

from typing import Any

import border_guard_gates as bgg
import exact_homm3_footprint as exact_fp
import functional_emit_reservation as fer
import object_property_namespaces as propns
import surface_emit as single

GUARDHOUSE_MAP_EVENT_SOURCE_KEY = "0:18:35"
GUARDHOUSE_DWELLING_SOURCE_KEY = "0:18:34"


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
            raise ValueError(f"object group length mismatch for {sid}")
        for object_id, node, rotation in zip(ids, nodes, rotations):
            if isinstance(object_id, int) and isinstance(node, int) and isinstance(rotation, int):
                index[object_id] = (sid, node, rotation)
    return index


def _set_object_node(objects: list[dict[str, Any]], object_id: int, node: int) -> None:
    for group in objects:
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        if object_id not in ids:
            continue
        index = ids.index(object_id)
        nodes[index] = node
        return
    raise ValueError(f"object {object_id} not found for node relocation")


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


def _remove_property_rows(properties: dict[str, Any] | None, remove_ids: set[int]) -> None:
    propns.remove_object_property_rows(properties, remove_ids)


def _upsert_prop_row(rows: list[dict[str, Any]], object_id: int, row: dict[str, Any]) -> None:
    for index, existing in enumerate(rows):
        if isinstance(existing, dict) and existing.get("id") == object_id:
            rows[index] = row
            return
    rows.append(row)


def _remove_prop_row(rows: list[dict[str, Any]], object_id: int) -> dict[str, Any] | None:
    for index, existing in enumerate(rows):
        if isinstance(existing, dict) and existing.get("id") == object_id:
            return rows.pop(index)
    return None


def _owners_at_node(
    objects: list[dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    node: int,
    *,
    exclude_ids: set[int],
) -> list[tuple[int, str]]:
    owners: list[tuple[int, str]] = []
    for group in objects:
        sid = group.get("sid")
        if not isinstance(sid, str):
            continue
        config = native_object_configs.get(sid)
        if not isinstance(config, dict):
            continue
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        for object_id, anchor, rotation in zip(ids, nodes, rotations):
            if not isinstance(object_id, int) or object_id in exclude_ids:
                continue
            occupied = single.occupied_nodes_for_object_instance(sid, config, anchor, rotation)
            gates = single.gate_nodes_for_object_instance(sid, config, anchor, rotation)
            if node in occupied or node in gates:
                owners.append((object_id, sid))
    return owners


def _south_approach(gate_node: int) -> int:
    # Olden +Y = north; unique land-on enter faces south (lower y).
    return gate_node - single.OLDEN_WIDTH


def clear_landon_barracks_south_approaches(
    objects: list[dict[str, Any]],
    properties: dict[str, Any] | None,
    *,
    native_object_configs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Remove suppressible scenery sealing the unique south approach of land-on barracks.

    Hosts whose in-envelope GATE projection is not exactly one cell are skipped with
    diagnostics rather than aborting the whole emit (GATE can clip outside the active
    source envelope on padded atlases).
    """
    index = _object_index(objects)
    cleared: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for object_id, (sid, node, rotation) in sorted(index.items()):
        if sid not in single.HOMM3_LANDON_BARRACKS_SIDS:
            continue
        config = native_object_configs.get(sid)
        if not isinstance(config, dict):
            raise ValueError(f"missing config for land-on barracks {sid}")
        gates = single.gate_nodes_for_object_instance(sid, config, node, rotation)
        if len(gates) != 1:
            # Same rim-clip case as campaign town GATE clearing: use the unclipped
            # native GATE so south-approach cleanup can still run.
            import native_footprint_model as native_fp

            model = native_fp.model_native_footprint(
                sid,
                config,
                node,
                rotation,
                width=single.OLDEN_WIDTH,
                height=single.OLDEN_HEIGHT,
            )
            gates = {int(cell) for cell in model.gate_cells}
        if len(gates) != 1:
            skipped.append({
                "hostObjectId": object_id,
                "hostSid": sid,
                "anchorNode": node,
                "rotation": rotation,
                "gateNodes": sorted(gates),
                "reason": "expected_one_gate",
            })
            continue
        gate = next(iter(gates))
        approach = _south_approach(gate)
        if approach < 0:
            continue
        remove_ids: set[int] = set()
        for occ_id, occ_sid in _owners_at_node(
            objects, native_object_configs, approach, exclude_ids={object_id}
        ):
            if occ_sid == "random-squad":
                # Honest HoMM3 guard on the approach — leave for combat.
                continue
            if occ_sid in fer.SUPPRESSIBLE_SOURCE_SCENERY_SIDS or occ_sid == single.HOMM3_PATHING_GAP_FILL_VISIBLE_SID:
                remove_ids.add(occ_id)
            elif occ_sid == single.HOMM3_PATHING_BLOCKER_SID:
                remove_ids.add(occ_id)
        if remove_ids:
            _remove_object_ids(objects, remove_ids)
            _remove_property_rows(properties, remove_ids)
            cleared.append({
                "hostObjectId": object_id,
                "hostSid": sid,
                "gateNode": gate,
                "approachNode": approach,
                "clearedObjectIds": sorted(remove_ids),
            })
    return {
        "status": "applied",
        "policy": "raw_landon_barracks_clear_suppressible_south_approach",
        "clearedApproachCount": len(cleared),
        "skippedHostCount": len(skipped),
        "skippedHosts": skipped[:20],
        "examples": cleared[:12],
    }


def relocate_guardhouse_map_event(
    objects: list[dict[str, Any]],
    properties: dict[str, Any] | None,
    *,
    entities_by_id: dict[int, dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    path_root_id: int,
) -> dict[str, Any]:
    """Move Guardhouse marker to a free cardinal approach of the Guardhouse GATE."""
    index = _object_index(objects)
    event_id = host_id = None
    for object_id, entity in entities_by_id.items():
        if entity.get("sourceKey") == GUARDHOUSE_MAP_EVENT_SOURCE_KEY:
            event_id = object_id
        if entity.get("sourceKey") == GUARDHOUSE_DWELLING_SOURCE_KEY:
            host_id = object_id
    if event_id is None or host_id is None:
        return {
            "status": "skipped_no_guardhouse_sources",
            "policy": "raw_landon_guardhouse_marker_relocate",
            "requiredSourceKeys": [
                GUARDHOUSE_MAP_EVENT_SOURCE_KEY,
                GUARDHOUSE_DWELLING_SOURCE_KEY,
            ],
        }
    # Homecoming-only coordinates: other maps may place scenery at 0:18:34/35.
    event_kind = str(entities_by_id[event_id].get("payloadKind") or "")
    host_kind = str(entities_by_id[host_id].get("payloadKind") or "")
    event_category = str(entities_by_id[event_id].get("category") or "")
    # Decoder may emit payloadKind "event" while category remains map_event.
    event_ok = event_kind == "map_event" or (
        event_kind == "event" and event_category == "map_event"
    )
    if not event_ok or host_kind not in {"creature_generator", "dwelling"}:
        return {
            "status": "skipped_source_keys_not_guardhouse",
            "policy": "raw_landon_guardhouse_marker_relocate",
            "requiredSourceKeys": [
                GUARDHOUSE_MAP_EVENT_SOURCE_KEY,
                GUARDHOUSE_DWELLING_SOURCE_KEY,
            ],
            "observed": {
                "eventPayloadKind": event_kind,
                "eventCategory": event_category,
                "hostPayloadKind": host_kind,
            },
        }
    if event_id not in index or host_id not in index:
        raise ValueError("Guardhouse map_event/dwelling not present in objects")
    event_sid, previous_node, _rot = index[event_id]
    host_sid, host_node, host_rot = index[host_id]
    if event_sid != single.HOMM3_LANDON_MAP_EVENT_MARKER_SID:
        raise ValueError(f"Guardhouse marker sid must be land-on marker; got {event_sid}")
    if host_sid not in single.HOMM3_LANDON_BARRACKS_SIDS:
        raise ValueError(f"Guardhouse host must be land-on barracks; got {host_sid}")
    host_config = native_object_configs[host_sid]
    host_gates = single.gate_nodes_for_object_instance(host_sid, host_config, host_node, host_rot)
    if len(host_gates) != 1:
        raise ValueError(f"Guardhouse host expected one GATE; got {sorted(host_gates)}")
    gate = next(iter(host_gates))
    path_root_node = index[path_root_id][1] if path_root_id in index else None
    if not isinstance(path_root_node, int):
        raise ValueError(f"path root {path_root_id} missing for Guardhouse marker relocation")

    gx = gate % single.OLDEN_WIDTH
    gy = gate // single.OLDEN_WIDTH
    # Dialog is bound onto the dwelling; the FX marker is cosmetic. Prefer the unique
    # south enter cell when free, else any free 8-neighbor (cardinals first).
    candidates: list[int] = []
    for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0), (-1, -1), (1, -1), (-1, 1), (1, 1)):
        nx, ny = gx + dx, gy + dy
        if 0 <= nx < single.OLDEN_WIDTH and 0 <= ny < single.OLDEN_HEIGHT:
            candidates.append(ny * single.OLDEN_WIDTH + nx)
    root_x = path_root_node % single.OLDEN_WIDTH
    root_y = path_root_node // single.OLDEN_WIDTH
    south = _south_approach(gate)
    candidates.sort(
        key=lambda cell: (
            0 if cell == south else 1,
            abs((cell % single.OLDEN_WIDTH) - root_x) + abs((cell // single.OLDEN_WIDTH) - root_y),
            cell // single.OLDEN_WIDTH,
            cell,
        )
    )

    host_occupied = single.occupied_nodes_for_object_instance(host_sid, host_config, host_node, host_rot)
    host_occupied |= set(host_gates)
    chosen = None
    cleared: set[int] = set()
    for candidate in candidates:
        if candidate in host_occupied:
            continue
        occupants = _owners_at_node(
            objects, native_object_configs, candidate, exclude_ids={event_id, host_id, path_root_id}
        )
        clearable: set[int] = set()
        blocked = False
        for occ_id, occ_sid in occupants:
            if occ_sid == "random-squad":
                blocked = True
                break
            if occ_sid in fer.SUPPRESSIBLE_SOURCE_SCENERY_SIDS or occ_sid in {
                single.HOMM3_PATHING_GAP_FILL_VISIBLE_SID,
                single.HOMM3_PATHING_BLOCKER_SID,
                "learning_stone",
            }:
                clearable.add(occ_id)
                continue
            blocked = True
            break
        if blocked:
            continue
        if clearable:
            _remove_object_ids(objects, clearable)
            _remove_property_rows(properties, clearable)
            cleared = clearable
        chosen = candidate
        break
    if chosen is None:
        raise ValueError(
            f"Guardhouse map_event {GUARDHOUSE_MAP_EVENT_SOURCE_KEY}: no free 8-neighbor cell "
            f"for host GATE {gate}"
        )
    if chosen != previous_node:
        _set_object_node(objects, event_id, chosen)
    return {
        "status": "applied",
        "policy": "raw_guardhouse_map_event_free_neighbor_of_gate",
        "eventObjectId": event_id,
        "hostObjectId": host_id,
        "fromNode": previous_node,
        "toNode": chosen,
        "clearedObjectIds": sorted(cleared),
    }


def bind_map_event_dialog_to_host(
    properties: dict[str, Any],
    *,
    event_id: int,
    host_id: int,
    policy: str,
    host_lifetime: str = "persistent_object",
    dialog_delivery: str = "prop_actions_before",
) -> dict[str, Any]:
    """Move EVENT Dialog/entity/activation props onto a real interactable host.

    Used for Guardhouse dwelling rebind and same-cell hero+EVENT rebind. Never
    DeleteEntity the host — removeAfterVisit is one-shot dialog only.

    dialog_delivery:
      - prop_actions_before: Dialog stays on host propActionsBefore (dwellings/Zones)
      - hero_interruption: strip Dialog from props; runtime BeforeIamVsHero owns it
        (hero-spawner combat does not run propActionsBefore — proven Player.log)
    """
    if dialog_delivery not in {"prop_actions_before", "hero_interruption"}:
        raise ValueError(f"unsupported dialog_delivery {dialog_delivery!r}")
    before_rows = properties.setdefault("propActionsBefore", [])
    after_rows = properties.setdefault("propActionsAfter", [])
    entity_rows = properties.setdefault("propEntities", [])
    activation_rows = properties.setdefault("propActivations", [])

    event_before = _remove_prop_row(before_rows, event_id)
    event_after = _remove_prop_row(after_rows, event_id)
    event_entity = _remove_prop_row(entity_rows, event_id)
    event_activation = _remove_prop_row(activation_rows, event_id)
    ai_rows = properties.setdefault("propAiIntetations", [])
    event_ai = _remove_prop_row(ai_rows, event_id)
    if event_before is None:
        raise ValueError(f"map_event {event_id} missing propActionsBefore Dialog for {policy}")
    if event_entity is None:
        raise ValueError(f"map_event {event_id} missing propEntities sid for {policy}")

    moved_before = False
    if dialog_delivery == "prop_actions_before":
        host_before = dict(event_before)
        host_before["id"] = host_id
        host_before["repeat"] = False
        _upsert_prop_row(before_rows, host_id, host_before)
        moved_before = True
    else:
        # Drop any stale Dialog already bound to this hero host.
        _remove_prop_row(before_rows, host_id)
    moved_after = False
    if event_after is not None:
        host_after = dict(event_after)
        host_after["id"] = host_id
        host_after["repeat"] = False
        actions = [
            action
            for action in (host_after.get("actions") or [])
            if not (isinstance(action, dict) and action.get("a") == "DeleteEntity")
        ]
        if actions:
            host_after["actions"] = actions
            _upsert_prop_row(after_rows, host_id, host_after)
            moved_after = True
    host_entity = dict(event_entity)
    host_entity["id"] = host_id
    _upsert_prop_row(entity_rows, host_id, host_entity)
    if event_activation is not None:
        host_activation = dict(event_activation)
        host_activation["id"] = host_id
        _upsert_prop_row(activation_rows, host_id, host_activation)
    moved_ai = False
    if event_ai is not None:
        host_ai = dict(event_ai)
        host_ai["id"] = host_id
        _upsert_prop_row(ai_rows, host_id, host_ai)
        moved_ai = True

    return {
        "status": "applied",
        "policy": policy,
        "eventObjectId": event_id,
        "hostObjectId": host_id,
        "hostLifetime": host_lifetime,
        "dialogDelivery": dialog_delivery,
        "eventLifetime": "one_shot_no_host_delete",
        "movedPropKeys": [
            key
            for key, moved in (
                ("propActionsBefore", moved_before),
                ("propActionsAfter", moved_after),
                ("propEntities", event_entity is not None),
                ("propActivations", event_activation is not None),
                ("propAiIntetations", moved_ai),
            )
            if moved
        ],
    }


def bind_guardhouse_dialog_to_dwelling(
    properties: dict[str, Any],
    *,
    entities_by_id: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    event_id = host_id = None
    for object_id, entity in entities_by_id.items():
        if entity.get("sourceKey") == GUARDHOUSE_MAP_EVENT_SOURCE_KEY:
            event_id = object_id
        if entity.get("sourceKey") == GUARDHOUSE_DWELLING_SOURCE_KEY:
            host_id = object_id
    if event_id is None or host_id is None:
        return {
            "status": "skipped_no_guardhouse_sources",
            "policy": "raw_landon_guardhouse_dialog_bind",
            "requiredSourceKeys": [
                GUARDHOUSE_MAP_EVENT_SOURCE_KEY,
                GUARDHOUSE_DWELLING_SOURCE_KEY,
            ],
        }
    event_kind = str(entities_by_id[event_id].get("payloadKind") or "")
    host_kind = str(entities_by_id[host_id].get("payloadKind") or "")
    event_category = str(entities_by_id[event_id].get("category") or "")
    # Decoder may emit payloadKind "event" while category remains map_event.
    event_ok = event_kind == "map_event" or (
        event_kind == "event" and event_category == "map_event"
    )
    if not event_ok or host_kind not in {"creature_generator", "dwelling"}:
        return {
            "status": "skipped_source_keys_not_guardhouse",
            "policy": "raw_landon_guardhouse_dialog_bind",
            "requiredSourceKeys": [
                GUARDHOUSE_MAP_EVENT_SOURCE_KEY,
                GUARDHOUSE_DWELLING_SOURCE_KEY,
            ],
            "observed": {
                "eventPayloadKind": event_kind,
                "eventCategory": event_category,
                "hostPayloadKind": host_kind,
            },
        }

    return bind_map_event_dialog_to_host(
        properties,
        event_id=event_id,
        host_id=host_id,
        policy="raw_guardhouse_dialog_on_dwelling_not_fx_marker",
        host_lifetime="persistent_object",
    )


def clear_subterranean_portal_gate_cells(
    objects: list[dict[str, Any]],
    properties: dict[str, Any] | None,
    *,
    native_object_configs: dict[str, dict[str, Any]],
    entities_by_id: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Clear suppressible scenery / gap-fill OCC from scorched subterranean portal GATEs.

    A HoMM3 Border Guard (9) emitted as its key-gate block may hold one GATE of the ring:
    the guard blocks only its own cell in HoMM3 and the entrance stays reachable from its
    other sides, and the block is deleted when the key is taken
    (``border_guard_gates``). It is never cleared (that would drop the guard) and is
    recorded as ``keyGateHeldGates``; a portal whose every GATE is held fails.

    Fail closed if any other non-clearable OCC still buries any GATE marker.
    """
    portal_gates = single.subterranean_portal_gate_nodes(objects, native_object_configs)
    if not portal_gates:
        # Surface-only missions (Deal / Neutral Affairs) have no subterranean portals.
        return {
            "status": "skipped_no_subterranean_portals",
            "policy": "raw_subterranean_portal_scorched_gate_clear",
            "gateNodeCount": 0,
            "clearedObjectCount": 0,
            "examples": [],
        }
    index = _object_index(objects)
    portal_ids = {
        object_id
        for object_id, (sid, _node, _rot) in index.items()
        if sid == single.HOMM3_SUBTERRANEAN_GATE_PORTAL_SID
    }
    cleared: list[dict[str, Any]] = []
    remove_ids: set[int] = set()
    key_gate_held: dict[int, int] = {}
    for gate in sorted(portal_gates):
        foreign: list[tuple[int, str]] = []
        for occ_id, occ_sid in _owners_at_node(
            objects, native_object_configs, gate, exclude_ids=portal_ids
        ):
            # Owners helper matches OCC or GATE; only OCC buries approach.
            config = native_object_configs.get(occ_sid)
            if not isinstance(config, dict):
                raise ValueError(f"missing config while clearing portal GATE for {occ_sid}")
            owner = index.get(occ_id)
            if owner is None:
                raise ValueError(f"missing object index for {occ_id}")
            _sid, anchor, rotation = owner
            occupied = single.occupied_nodes_for_object_instance(occ_sid, config, anchor, rotation)
            if gate not in occupied:
                continue
            if occ_sid == "random-squad":
                foreign.append((occ_id, occ_sid))
                continue
            source_entity = (entities_by_id or {}).get(occ_id)
            if (
                occ_sid == bgg.KEY_GATE_BLOCK_SID
                and isinstance(source_entity, dict)
                and source_entity.get("templateObjectId") == bgg.BORDER_GUARD_TEMPLATE_ID
            ):
                key_gate_held[gate] = occ_id
                continue
            if (
                occ_sid in fer.SUPPRESSIBLE_SOURCE_SCENERY_SIDS
                or exact_fp.is_scenery_exact_footprint_clone_sid(str(occ_sid))
                or occ_sid == single.HOMM3_PATHING_GAP_FILL_VISIBLE_SID
                or occ_sid == single.HOMM3_PATHING_BLOCKER_SID
                # Pickup piles on the portal GATE tile bury the entrance; clear them so
                # the subterranean marker stays walkable (With Blinders On resource_crystals).
                or str(occ_sid).startswith("resource_")
                # Adventure interactables commonly sit on AB/SoD portal tiles; same
                # scorched policy as gate_face_rotation.clearable families.
                or str(occ_sid).startswith("altar_of_magic")
                or str(occ_sid).startswith("shrine_")
                or str(occ_sid).startswith("chest")
                or occ_sid in {
                    "arena",
                    "fountain",
                    "university",
                    "tree_of_knowledge",
                    "lost_library",
                    "mana_well",
                    "shady_den",
                    "chest",
                    # Campfire / tavern sit on AB portal tiles the same way as chests.
                    "camp_fire",
                    "tavern",
                }
            ):
                remove_ids.add(occ_id)
                cleared.append({
                    "gateNode": gate,
                    "clearedObjectId": occ_id,
                    "clearedSid": occ_sid,
                })
            else:
                foreign.append((occ_id, occ_sid))
        if foreign:
            raise ValueError(
                f"subterranean portal GATE {gate} buried by non-clearable OCC {foreign}; "
                "scorched-earth accessibility requires all GATE markers clear"
            )
    if key_gate_held:
        config = native_object_configs[single.HOMM3_SUBTERRANEAN_GATE_PORTAL_SID]
        for object_id in sorted(portal_ids):
            _sid, anchor, rotation = index[object_id]
            own_gates = single.nodes_for_object_instance_with_value(
                single.HOMM3_SUBTERRANEAN_GATE_PORTAL_SID, config, anchor, rotation, node_value=2
            )
            if own_gates and own_gates <= set(key_gate_held):
                raise ValueError(
                    f"subterranean portal {object_id}: every GATE {sorted(own_gates)} is held by a "
                    f"border-guard key-gate block {sorted(set(key_gate_held.values()))}"
                )
    if remove_ids:
        _remove_object_ids(objects, remove_ids)
        _remove_property_rows(properties, remove_ids)
    return {
        "status": "applied",
        "policy": "raw_subterranean_portal_scorched_gate_clear",
        "gateNodeCount": len(portal_gates),
        "clearedObjectCount": len(remove_ids),
        "keyGateHeldGates": [
            {"gateNode": gate, "borderGuardObjectId": object_id}
            for gate, object_id in sorted(key_gate_held.items())
        ],
        "examples": cleared[:20],
    }


def apply_raw_landon_access_pass(
    objects: list[dict[str, Any]],
    properties: dict[str, Any],
    *,
    entities_by_id: dict[int, dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    path_root_id: int,
) -> dict[str, Any]:
    scenery = clear_landon_barracks_south_approaches(
        objects, properties, native_object_configs=native_object_configs
    )
    portal_gates = clear_subterranean_portal_gate_cells(
        objects,
        properties,
        native_object_configs=native_object_configs,
        entities_by_id=entities_by_id,
    )
    marker = relocate_guardhouse_map_event(
        objects,
        properties,
        entities_by_id=entities_by_id,
        native_object_configs=native_object_configs,
        path_root_id=path_root_id,
    )
    dialog = bind_guardhouse_dialog_to_dwelling(properties, entities_by_id=entities_by_id)
    return {
        "status": "applied",
        "policy": "raw_landon_access_guardhouse_south_approach_and_portal_gate_clear",
        "barracksSouthApproachClear": scenery,
        "subterraneanPortalGateClear": portal_gates,
        "guardhouseMarker": marker,
        "guardhouseDialog": dialog,
    }
