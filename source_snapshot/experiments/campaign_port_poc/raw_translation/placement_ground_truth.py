#!/usr/bin/env python3
"""Three-way placement ground truth for raw_translation: HoMM3 + mapping + Olden."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import emit_policy
import layer_atlas as atlas
import layered_objects as lob
import port_homecoming_poc as poc
import surface_emit as single
import town_gate_align

SCHEMA = "homm3.olden_raw_translation_placement_ground_truth.v1"
ARTIFACT_NAME = "homecoming.raw_translation_placement_ground_truth.json"


def _index_emitted_instances(objects: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    for group in objects:
        sid = str(group.get("sid") or "")
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        levels = group.get("levels") or []
        for index, object_id in enumerate(ids):
            if not isinstance(object_id, int):
                continue
            by_id[object_id] = {
                "sid": sid,
                "node": nodes[index] if index < len(nodes) else None,
                "rotation": rotations[index] if index < len(rotations) else 0,
                "level": levels[index] if index < len(levels) else 0.0,
            }
    return by_id


def _h3_block(entity: dict[str, Any]) -> dict[str, Any]:
    return {
        "alignmentSid": entity.get("sid"),
        "templateObjectId": entity.get("templateObjectId"),
        "templateAnimation": entity.get("templateAnimation"),
        "templateSubtype": entity.get("templateSubtype"),
        "templateBlockMask": entity.get("templateBlockMask"),
        "templateVisitMask": entity.get("templateVisitMask"),
        "category": entity.get("category"),
        "payloadKind": entity.get("payloadKind"),
        "sourceRotation": int(entity.get("rotation") or 0),
        "sourceX": entity.get("sourceX"),
        "sourceY": entity.get("sourceY"),
        "sourceLayer": entity.get("sourceLayer"),
    }


def _mapping_block(
    entity: dict[str, Any],
    replacement_sid: str | None,
    rule_name: str,
    lossiness: str,
) -> dict[str, Any]:
    return {
        "sourceSignature": single.signature_for(entity),
        "ruleName": rule_name,
        "lossiness": lossiness,
        "replacementSid": replacement_sid,
    }


def _olden_block(
    *,
    object_id: int,
    sid: str,
    node: int,
    rotation: int,
    level: float,
    native_object_configs: dict[str, dict[str, Any]],
    default_node: int | None,
    entity: dict[str, Any],
    visit_nodes: list[int],
) -> dict[str, Any]:
    config = native_object_configs.get(sid) or {}
    occupied = (
        sorted(
            single.occupied_nodes_for_object_instance(sid, config, node, rotation)
        )
        if isinstance(config, dict) and config
        else []
    )
    gate_nodes = (
        sorted(
            single.nodes_for_object_instance_with_value(
                sid, config, node, rotation, node_value=2
            )
        )
        if isinstance(config, dict) and config
        else []
    )
    block = {
        "objectId": object_id,
        "sid": sid,
        "node": node,
        "rotation": rotation,
        "level": level,
        "occupiedNodes": occupied,
        "gateNodes": gate_nodes,
        "homm3VisitNodes": visit_nodes,
        "defaultNode": default_node,
        "nodeShiftedFromDefault": default_node is not None and default_node != node,
    }
    if sid in single.HOMM3_LANDON_OBJECT_SIDS and sid != single.HOMM3_LANDON_MAP_EVENT_MARKER_SID:
        block["landonGateAligned"] = True
        if town_gate_align.is_landon_city_sid(sid):
            block["landonBodyCenterAligned"] = True
    return block


def _is_map_event_entity(entity: dict[str, Any]) -> bool:
    return entity.get("category") == "map_event" or entity.get("payloadKind") in {
        "map_event",
        "event",
    }


def build_placement_ground_truth(
    *,
    global_entities: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    substitution_lookup: dict[str, dict[str, Any]],
    valid_ids: set[str],
    native_object_configs: dict[str, dict[str, Any]],
    profile: Any,
    approach_cleared_ids: set[int] | None = None,
    fer_omitted_ids: set[int] | None = None,
    map_event_host_ledger: dict[int, dict[str, Any]] | None = None,
    visual_scenery_sid_change_ids: set[int] | None = None,
    promoted_start_bindings: dict[int, int] | None = None,
    object_billboard_hosts: dict[int, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Per-source-placement emit ledger.

    ``visual_scenery_sid_change_ids``: ids whose SID the visual scenery postpass swapped
    within the same ObjectConfig fingerprint family; they count as ``emitted`` under the
    emitted SID, with the resolved substitution SID kept in ``visualScenerySidChange``.
    ``promoted_start_bindings``: retired start-hero object id -> town object id that the
    campaign city start promoted in its place (``start_city_promoted``).
    ``object_billboard_hosts``: source index -> visual-only billboard host
    (``object_billboards.py``), recorded on the row as ``visualBillboard``.
    """
    emitted_by_id = _index_emitted_instances(objects)
    visual_change_ids = set(visual_scenery_sid_change_ids or ())
    promoted = dict(promoted_start_bindings or {})
    cleared_ids = set(approach_cleared_ids or ())
    fer_ids = set(fer_omitted_ids or ())
    host_ledger = dict(map_event_host_ledger or {})
    billboard_hosts = dict(object_billboard_hosts or {})
    placements: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()

    previous_w, previous_h = single.OLDEN_WIDTH, single.OLDEN_HEIGHT
    single.OLDEN_WIDTH = atlas.OLDEN_WIDTH
    single.OLDEN_HEIGHT = atlas.OLDEN_HEIGHT
    try:
        for entity in global_entities:
            source_index = entity.get("sourceIndex")
            if not isinstance(source_index, int):
                continue
            source_layer = entity.get("sourceLayer")
            if not isinstance(source_layer, int):
                continue

            replacement_sid, rule_name, lossiness = single.resolve_replacement_sid(
                entity, substitution_lookup, valid_ids
            )
            row: dict[str, Any] = {
                "sourceIndex": source_index,
                "sourceKey": entity.get("sourceKey"),
                "sourceLayer": source_layer,
                "sourceX": entity.get("sourceX"),
                "sourceY": entity.get("sourceY"),
                "h3": _h3_block(entity),
                "mapping": _mapping_block(entity, replacement_sid, rule_name, lossiness),
            }

            in_bounds = lob.in_source_bounds(entity)
            instance = emitted_by_id.get(source_index)
            host = host_ledger.get(source_index) if _is_map_event_entity(entity) else None
            if not in_bounds:
                row["emitStatus"] = "border_overhang_not_emitted"
                row["olden"] = None
            elif replacement_sid is None:
                row["emitStatus"] = "blocked_by_substitution"
                row["olden"] = None
            elif instance is None and source_index in cleared_ids:
                row["emitStatus"] = "approach_cleared"
                row["olden"] = None
            elif instance is None and source_index in promoted:
                row["emitStatus"] = "start_city_promoted"
                row["olden"] = None
                row["startCityPromotion"] = {
                    "replacementObjectId": int(promoted[source_index]),
                    "retiredObjectId": source_index,
                }
            elif instance is None and source_index in fer_ids:
                row["emitStatus"] = "fer_omitted"
                row["olden"] = None
            elif instance is None and isinstance(host, dict):
                # Raw translation remaps unguarded events to Zone 1x1 / colocated hero.
                # ObjectConfig marker is intentionally absent — not a silent emit miss.
                host_mode = str(host.get("hostMode") or "")
                row["emitStatus"] = "emitted_native_event_host"
                row["mapEventHost"] = host
                node = host.get("node")
                row["olden"] = {
                    "objectId": source_index,
                    "sid": host.get("sid"),
                    "node": node,
                    "hostMode": host_mode,
                    "markerId": host.get("markerId"),
                    "hostObjectId": host.get("hostObjectId"),
                }
            elif instance is None:
                row["emitStatus"] = "missing_from_emit"
                row["olden"] = None
            else:
                emitted_sid = str(instance["sid"])
                node = instance["node"]
                rotation = int(instance.get("rotation") or 0)
                level = float(instance.get("level") or 0.0)
                default_node = None
                visit_nodes: list[int] = []
                if (
                    isinstance(entity.get("sourceX"), int)
                    and isinstance(entity.get("sourceY"), int)
                    and isinstance(native_object_configs.get(emitted_sid), dict)
                ):
                    with lob.single_projection_context(source_layer):
                        visit_nodes = sorted(single.entity_visit_nodes(entity))
                        try:
                            default_node = single.target_node_allowing_source_padding(
                                int(entity["sourceX"]),
                                int(entity["sourceY"]),
                            )
                        except ValueError:
                            default_node = None
                        # Re-derive emit-time anchor for evidence (same as surface_emit).
                        try:
                            derived_node, anchor_evidence = single.derive_source_anchor_node(
                                entity,
                                emitted_sid,
                                native_object_configs[emitted_sid],
                                default_node if default_node is not None else int(node),
                                rotation=rotation,
                            )
                            row["anchorEvidence"] = {
                                "decision": anchor_evidence.get("decision"),
                                "reason": anchor_evidence.get("reason"),
                                "derivedNode": derived_node,
                                "homm3ScenerySolidSquare": anchor_evidence.get("homm3ScenerySolidSquare"),
                            }
                        except ValueError as exc:
                            row["anchorEvidence"] = {"error": str(exc)}

                row["olden"] = _olden_block(
                    object_id=source_index,
                    sid=emitted_sid,
                    node=int(node),
                    rotation=rotation,
                    level=level,
                    native_object_configs=native_object_configs,
                    default_node=default_node,
                    entity=entity,
                    visit_nodes=visit_nodes,
                )
                intentional_guard_host = (
                    isinstance(host, dict)
                    and host.get("hostMode") == "guarded_random_squad"
                    and emitted_sid == "random-squad"
                )
                if intentional_guard_host:
                    row["emitStatus"] = "emitted_native_event_host"
                    row["mapEventHost"] = host
                elif emitted_sid != replacement_sid and source_index in visual_change_ids:
                    row["emitStatus"] = "emitted"
                    row["mapping"]["replacementSid"] = emitted_sid
                    row["visualScenerySidChange"] = {
                        "resolvedReplacementSid": replacement_sid,
                        "emittedSid": emitted_sid,
                    }
                elif emitted_sid != replacement_sid:
                    row["emitStatus"] = "emitted_sid_mismatch"
                    row["mappingEmittedSidDelta"] = {
                        "resolvedReplacementSid": replacement_sid,
                        "emittedSid": emitted_sid,
                    }
                else:
                    row["emitStatus"] = "emitted"

            if source_index in billboard_hosts:
                row["visualBillboard"] = billboard_hosts[source_index]
            status_counts[str(row["emitStatus"])] += 1
            placements.append(row)
    finally:
        single.OLDEN_WIDTH = previous_w
        single.OLDEN_HEIGHT = previous_h

    # Synthetic / non-source objects (envelope pads, etc.).
    synthetic: list[dict[str, Any]] = []
    source_ids = {
        int(entity["sourceIndex"])
        for entity in global_entities
        if isinstance(entity.get("sourceIndex"), int)
    }
    for object_id, instance in sorted(emitted_by_id.items()):
        if object_id in source_ids:
            continue
        sid = str(instance["sid"])
        node = instance["node"]
        rotation = int(instance.get("rotation") or 0)
        config = native_object_configs.get(sid) or {}
        occupied = (
            sorted(single.occupied_nodes_for_object_instance(sid, config, int(node), rotation))
            if isinstance(config, dict) and config and isinstance(node, int)
            else []
        )
        synthetic.append(
            {
                "objectId": object_id,
                "sid": sid,
                "node": node,
                "rotation": rotation,
                "level": instance.get("level"),
                "occupiedNodes": occupied,
                "kind": "synthetic_non_source",
            }
        )

    alignment_path = Path(getattr(profile, "alignment_path", atlas.ALIGNMENT_PATH))
    substitution_path = Path(getattr(profile, "substitution_path", atlas.SUBSTITUTION_PATH))
    try:
        alignment_rel = str(alignment_path.resolve().relative_to(Path(poc.ROOT))).replace("\\", "/")
    except Exception:
        alignment_rel = str(alignment_path).replace("\\", "/")
    try:
        substitution_rel = str(substitution_path.resolve().relative_to(Path(poc.ROOT))).replace("\\", "/")
    except Exception:
        substitution_rel = str(substitution_path).replace("\\", "/")

    return {
        "schema": SCHEMA,
        "mapSid": atlas.MAP_SID,
        "pipeline": "raw_translation",
        "emitPolicyPack": emit_policy.RAW_TRANSLATION_EMIT_POLICY.to_manifest(),
        "brNodeShiftPolicy": emit_policy.RAW_TRANSLATION_BR_NODE_SHIFT_POLICY,
        "proofBoundary": "generated_artifact_validator_runtime_unvalidated",
        "inputs": {
            "alignment": alignment_rel,
            "substitutionMap": substitution_rel,
        },
        "stats": {
            "sourceEntityCount": len(placements),
            "statusHistogram": dict(status_counts.most_common()),
            "emittedCount": int(status_counts.get("emitted", 0)),
            "emittedNativeEventHostCount": int(status_counts.get("emitted_native_event_host", 0)),
            "emittedSidMismatchCount": int(status_counts.get("emitted_sid_mismatch", 0)),
            "blockedCount": int(status_counts.get("blocked_by_substitution", 0)),
            "missingFromEmitCount": int(status_counts.get("missing_from_emit", 0)),
            "ferOmittedCount": int(status_counts.get("fer_omitted", 0)),
            "approachClearedCount": int(status_counts.get("approach_cleared", 0)),
            "startCityPromotedCount": int(status_counts.get("start_city_promoted", 0)),
            "borderOverhangCount": int(status_counts.get("border_overhang_not_emitted", 0)),
            "syntheticNonSourceCount": len(synthetic),
            "mapEventHostLedgerCount": len(host_ledger),
            "visualBillboardCount": sum(1 for row in placements if row.get("visualBillboard")),
            "nodeShiftedCount": sum(
                1
                for row in placements
                if isinstance(row.get("olden"), dict) and row["olden"].get("nodeShiftedFromDefault") is True
            ),
        },
        "placements": placements,
        "syntheticObjects": synthetic,
    }


def write_placement_ground_truth(doc: dict[str, Any], out_root: Path | None = None) -> Path:
    root = out_root or atlas.OUT_ROOT
    path = root / ARTIFACT_NAME
    atlas.write_json(path, doc)
    return path
