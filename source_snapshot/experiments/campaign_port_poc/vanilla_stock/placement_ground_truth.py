"""Placement ground truth for vanilla_stock: HoMM3 → mapping → Olden."""

from __future__ import annotations

from collections import Counter
from typing import Any

from . import SCHEMA_GROUND_TRUTH, STATUS
from .scenery_footprint import occupied_nodes_for_instance


def _index_emitted_instances(objects: list[dict[str, Any]]) -> dict[int, dict[str, Any]]:
    by_id: dict[int, dict[str, Any]] = {}
    for group in objects:
        sid = str(group.get("sid") or "")
        ids = group.get("ids") or []
        nodes = group.get("nodes") or []
        rotations = group.get("rotations") or []
        for index, object_id in enumerate(ids):
            if not isinstance(object_id, int):
                continue
            by_id[object_id] = {
                "sid": sid,
                "node": nodes[index] if index < len(nodes) else None,
                "rotation": rotations[index] if index < len(rotations) else 0,
            }
    return by_id


def build_placement_ground_truth(
    *,
    entities: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    decisions_by_source_index: dict[int, dict[str, Any]],
    native_object_configs: dict[str, dict[str, Any]],
    atlas_width: int,
    atlas_height: int,
    approach_cleared_ids: set[int] | None = None,
) -> dict[str, Any]:
    emitted_by_id = _index_emitted_instances(objects)
    cleared_ids = set(approach_cleared_ids or ())
    placements: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()

    for entity in entities:
        source_index = entity.get("sourceIndex")
        if not isinstance(source_index, int):
            continue
        decision = decisions_by_source_index.get(source_index) or {}
        action = str(decision.get("action") or "missing")
        replacement = decision.get("sid")
        row: dict[str, Any] = {
            "sourceIndex": source_index,
            "sourceKey": entity.get("sourceKey"),
            "sourceLayer": entity.get("sourceLayer"),
            "sourceX": entity.get("sourceX"),
            "sourceY": entity.get("sourceY"),
            "h3": {
                "templateObjectId": entity.get("templateObjectId"),
                "templateAnimation": entity.get("templateAnimation"),
                "templateSubtype": entity.get("templateSubtype"),
                "templateBlockMask": entity.get("templateBlockMask"),
                "templateVisitMask": entity.get("templateVisitMask"),
                "category": entity.get("category"),
                "payloadKind": entity.get("payloadKind"),
                "owner": entity.get("owner"),
            },
            "mapping": {
                "action": action,
                "ruleName": decision.get("reason"),
                "lossiness": decision.get("lossiness") or decision.get("reason"),
                "replacementSid": replacement,
                "kind": decision.get("kind"),
            },
        }

        instance = emitted_by_id.get(source_index)
        if action in {"omit", "miss"}:
            row["emitStatus"] = "omitted"
            row["olden"] = None
        elif action == "outside_envelope":
            row["emitStatus"] = "border_overhang_not_emitted"
            row["olden"] = None
        elif source_index in cleared_ids and instance is None:
            row["emitStatus"] = "approach_cleared"
            row["olden"] = None
        elif decision.get("hostMode") == "invisible_zone_marker" and instance is None:
            # Unguarded map events become markers[] Zone 1x1 hosts (no objects[] instance).
            row["emitStatus"] = "emitted_as_zone_marker"
            row["olden"] = {
                "hostMode": "invisible_zone_marker",
                "hostSid": decision.get("host"),
                "sourceObjectId": source_index,
                "note": "final marker id/node assigned in apply_map_events after landability relocate",
            }
        elif instance is None:
            row["emitStatus"] = "missing_from_emit" if action == "emit" else "omitted"
            row["olden"] = None
        else:
            emitted_sid = str(instance["sid"])
            node = instance["node"]
            rotation = int(instance.get("rotation") or 0)
            config = native_object_configs.get(emitted_sid) or {}
            occupied: list[int] = []
            if isinstance(config, dict) and config and isinstance(node, int):
                try:
                    occupied = sorted(
                        occupied_nodes_for_instance(
                            config,
                            anchor_node=int(node),
                            rotation=rotation,
                            width=atlas_width,
                            height=atlas_height,
                        )
                    )
                except Exception:
                    occupied = []
            status = "emitted"
            if replacement and emitted_sid != replacement and decision.get("kind") != "scenery":
                status = "emitted_sid_mismatch"
            row["emitStatus"] = status
            row["olden"] = {
                "objectId": source_index,
                "sid": emitted_sid,
                "node": node,
                "rotation": rotation,
                "occupiedNodes": occupied,
            }
            if isinstance(decision.get("townAnchorEvidence"), dict):
                row["olden"]["townAnchorEvidence"] = decision["townAnchorEvidence"]
                visit = decision["townAnchorEvidence"].get("visitNode")
                gates = decision["townAnchorEvidence"].get("gateNodes") or []
                if isinstance(visit, int) and visit not in gates:
                    row["emitStatus"] = "town_gate_visit_mismatch"
        status_counts[row["emitStatus"]] += 1
        placements.append(row)

    return {
        "schema": SCHEMA_GROUND_TRUTH,
        "status": STATUS,
        "pipeline": "vanilla_stock",
        "stats": {
            "entityCount": len(placements),
            "statusHistogram": dict(status_counts.most_common()),
        },
        "placements": placements,
    }
