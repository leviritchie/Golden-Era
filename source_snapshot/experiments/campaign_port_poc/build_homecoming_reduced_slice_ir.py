#!/usr/bin/env python3
"""Build the reduced Homecoming playable-slice IR from the validated object policy."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc
import validate_homecoming_object_policy as policy_validator

OUT_ROOT = poc.OUT_ROOT / "layered_ir"
MANIFEST_PATH = OUT_ROOT / "homecoming.object_port_manifest.json"
POLICY_VALIDATION_PATH = OUT_ROOT / "homecoming.object_policy_validation_report.json"
SLICE_PATH = OUT_ROOT / "homecoming.reduced_slice_ir.json"
VALIDATION_PATH = OUT_ROOT / "homecoming.reduced_slice_validation_report.json"
REPORT_PATH = OUT_ROOT / "REDUCED_SLICE_REPORT.md"
POLICY_PATH = Path(__file__).with_name("homecoming_object_policy.json")

REQUIRED_ENTITY_KEYS = {"1:35:35"}
REQUIRED_EVENT_KEYS = {"0:18:35"}
REQUIRED_CAVE_EDGE_COORDS = {(14, 41), (49, 3)}
CAVE_OBJECT_ID = 103
WHIRLPOOL_OBJECT_ID = 111
EXPECTED_EVENT_MESSAGE = "Having defeated the Troglodytes, your men free the Guardhouse.  Within, the occupying Pikemen are eager to fight at your side."
EXPECTED_UNRESOLVED_WHIRLPOOL_KEYS = {"0:58:67", "0:21:62"}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def parse_key(key: str) -> dict[str, int]:
    layer, x, y = key.split(":")
    return {"layer": int(layer), "x": int(x), "y": int(y)}


def load_inputs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"missing object manifest: {MANIFEST_PATH}")
    if not POLICY_PATH.exists():
        raise FileNotFoundError(f"missing object policy: {POLICY_PATH}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if (manifest.get("validation") or {}).get("result") != "PASS":
        raise ValueError("object manifest must pass before reduced-slice generation")
    policy_validation = policy_validator.validate_policy(manifest, policy)
    if policy_validation.get("result") != "PASS":
        raise ValueError(f"object policy must pass before reduced-slice generation: {policy_validation}")
    return manifest, policy, policy_validation


def matching_policy(record: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    matches = [row for row in policy["objectPolicies"] if policy_validator.row_matches_record(row, record)]
    if len(matches) != 1:
        raise ValueError(f"record {record['sourceIndex']} {record['sourceKey']} matched {len(matches)} policy rows")
    return matches[0]


def projected_record(record: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    projected = {
        "sourceIndex": record["sourceIndex"],
        "sourceKey": record["sourceKey"],
        "position": parse_key(record["sourceKey"]),
        "recordOffset": record["recordOffset"],
        "templateObjectId": record["templateObjectId"],
        "templateAnimation": record["templateAnimation"],
        "sourceCategory": record["category"],
        "policyAction": row["action"],
        "policyScope": row["scope"],
        "runtimeRequirement": row["runtimeRequirement"],
    }
    for optional_key in ("name", "message", "triggerFields", "triggerRole", "triggerPort"):
        if optional_key in record:
            projected[optional_key] = record[optional_key]
    return projected


def build_travel_graph(records: list[dict[str, Any]]) -> dict[str, Any]:
    caves_by_xy: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    whirlpools: list[dict[str, Any]] = []
    for record in records:
        if record["templateObjectId"] == CAVE_OBJECT_ID:
            pos = record["position"]
            caves_by_xy[(pos["x"], pos["y"])].append(record)
        elif record["templateObjectId"] == WHIRLPOOL_OBJECT_ID:
            whirlpools.append(record)

    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for xy, cave_records in sorted(caves_by_xy.items()):
        by_layer = {item["position"]["layer"]: item for item in cave_records}
        if set(by_layer) == {0, 1}:
            surface = by_layer[0]
            underground = by_layer[1]
            edges.append({
                "kind": "subterranean_gate_pair_by_exact_xy",
                "x": xy[0],
                "y": xy[1],
                "from": surface["sourceKey"],
                "to": underground["sourceKey"],
                "bidirectional": True,
                "proof": "decoded cave records share x/y on surface and underground layers",
            })
        else:
            unresolved.append({
                "kind": "unpaired_cave_candidate",
                "x": xy[0],
                "y": xy[1],
                "sourceKeys": [item["sourceKey"] for item in cave_records],
            })
    for item in whirlpools:
        unresolved.append({
            "kind": "unpaired_whirlpool_candidate",
            "sourceKey": item["sourceKey"],
            "reason": "whirlpool destination pairing is not decoded by the current reduced-slice IR",
        })
    return {"edges": edges, "unresolvedCandidates": unresolved}


def validate_slice(slice_ir: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    entities = slice_ir["entities"]
    events = slice_ir["events"]
    travel = slice_ir["travelGraph"]
    entity_keys = {item["sourceKey"] for item in entities}
    event_keys = {item["sourceKey"] for item in events}
    if entity_keys != REQUIRED_ENTITY_KEYS:
        errors.append(f"entity keys {sorted(entity_keys)} do not match required {sorted(REQUIRED_ENTITY_KEYS)}")
    if event_keys != REQUIRED_EVENT_KEYS:
        errors.append(f"event keys {sorted(event_keys)} do not match required {sorted(REQUIRED_EVENT_KEYS)}")
    else:
        event = events[0]
        fields = event.get("triggerFields") or {}
        reward_counts = fields.get("rewardCounts") or {}
        if event.get("message") != EXPECTED_EVENT_MESSAGE:
            errors.append("Guardhouse event message does not match decoded source text")
        if fields.get("playersMask") != 255 or fields.get("computerActivate") is not True or fields.get("removeAfterVisit") is not True:
            errors.append("Guardhouse event trigger activation fields do not match decoded H3M payload")
        if fields.get("hasMessage") is not True or fields.get("hasGuards") is not False:
            errors.append("Guardhouse event message/guard flags do not match decoded H3M payload")
        for reward_key in ("skills", "artifacts", "spells", "creatures"):
            if reward_counts.get(reward_key) != 0:
                errors.append(f"Guardhouse event rewardCounts.{reward_key} expected 0, found {reward_counts.get(reward_key)}")
    edge_coords = {(edge["x"], edge["y"]) for edge in travel["edges"]}
    if edge_coords != REQUIRED_CAVE_EDGE_COORDS:
        errors.append(f"cave travel edge coords {sorted(edge_coords)} do not match required {sorted(REQUIRED_CAVE_EDGE_COORDS)}")
    if any(item["sourceCategory"] == "payloadless_object_unclassified_for_current_scope" for item in slice_ir["emittedRecords"]):
        errors.append("payloadless records must not be emitted in the reduced slice")
    if len(slice_ir["emittedRecords"]) != 8:
        errors.append(f"expected 8 emitted records, found {len(slice_ir['emittedRecords'])}")
    unresolved = travel["unresolvedCandidates"]
    unresolved_whirlpool_keys = {item.get("sourceKey") for item in unresolved if item.get("kind") == "unpaired_whirlpool_candidate"}
    unexpected_unresolved = [item for item in unresolved if item.get("kind") != "unpaired_whirlpool_candidate"]
    if unresolved_whirlpool_keys != EXPECTED_UNRESOLVED_WHIRLPOOL_KEYS:
        errors.append(f"unresolved whirlpool keys {sorted(unresolved_whirlpool_keys)} do not match required {sorted(EXPECTED_UNRESOLVED_WHIRLPOOL_KEYS)}")
    if unexpected_unresolved:
        errors.append(f"unexpected unresolved non-whirlpool travel candidates: {unexpected_unresolved}")
    if unresolved:
        warnings.append("the two known whirlpool candidates remain unresolved and are not valid travel edges")
    return {
        "schema": "homm3.homecoming_reduced_slice.validation.v0",
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "checkedInvariants": {
            "emittedRecords": len(slice_ir["emittedRecords"]),
            "entities": len(entities),
            "events": len(events),
            "travelEdges": len(travel["edges"]),
            "unresolvedTravelCandidates": len(travel["unresolvedCandidates"]),
        },
    }


def update_ir(validation: dict[str, Any]) -> None:
    ir_path = OUT_ROOT / "homecoming.layered_map_ir.json"
    if not ir_path.exists():
        return
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    ir.setdefault("objectInstances", {})["reducedSlice"] = {
        "artifact": str(SLICE_PATH),
        "validationArtifact": str(VALIDATION_PATH),
        "validationResult": validation["result"],
        "primaryBlockingFeature": "missing_layer_aware_olden_map_runtime",
    }
    write_json(ir_path, ir)


def write_report(slice_ir: dict[str, Any], validation: dict[str, Any]) -> None:
    lines = [
        "# Homecoming Reduced Slice IR",
        "",
        f"Validation: {validation['result']}",
        f"Emitted records: {len(slice_ir['emittedRecords'])}",
        "",
        "## Emitted Entities",
        "",
    ]
    for item in slice_ir["entities"]:
        lines.append(f"- `{item['sourceKey']}` {item.get('name')} objectId={item['templateObjectId']} requirement={item['runtimeRequirement']}")
    lines.extend(["", "## Emitted Events", ""])
    for item in slice_ir["events"]:
        fields = item.get("triggerFields") or {}
        lines.append(f"- `{item['sourceKey']}` playersMask={fields.get('playersMask')} computerActivate={fields.get('computerActivate')} removeAfterVisit={fields.get('removeAfterVisit')}")
    lines.extend(["", "## Travel Edges", ""])
    for edge in slice_ir["travelGraph"]["edges"]:
        lines.append(f"- `{edge['from']}` <-> `{edge['to']}` by exact cave x/y ({edge['x']}, {edge['y']})")
    lines.extend(["", "## Unresolved Travel Candidates", ""])
    for item in slice_ir["travelGraph"]["unresolvedCandidates"]:
        lines.append(f"- {item}")
    lines.extend([
        "",
        "## Blocking Runtime Gap",
        "",
        "This IR is a reduced source contract only. It is not an Olden `.map`; playable behavior remains blocked until layer-aware runtime/emission exists.",
    ])
    if validation["warnings"]:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in validation["warnings"])
    if validation["errors"]:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in validation["errors"])
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    manifest, policy, policy_validation = load_inputs()
    policy_validator.write_json(POLICY_VALIDATION_PATH, policy_validation)
    policy_validator.update_ir(policy_validation)
    policy_validator.write_report(policy, policy_validation)
    records_by_action = defaultdict(list)
    emitted: list[dict[str, Any]] = []
    for record in manifest["records"]:
        row = matching_policy(record, policy)
        records_by_action[row["action"]].append(record)
        if row["action"] == "emit_stub":
            emitted.append(projected_record(record, row))
    entities = [item for item in emitted if item["sourceKey"] in REQUIRED_ENTITY_KEYS]
    events = [item for item in emitted if item["sourceKey"] in REQUIRED_EVENT_KEYS]
    travel_candidates = [item for item in emitted if item["templateObjectId"] in (CAVE_OBJECT_ID, WHIRLPOOL_OBJECT_ID)]
    slice_ir = {
        "schema": "homm3.homecoming_reduced_slice.v0",
        "source": manifest["source"],
        "policy": {
            "artifact": str(POLICY_PATH),
            "validationArtifact": str(POLICY_VALIDATION_PATH),
            "validationResult": policy_validation["result"],
        },
        "emittedRecords": emitted,
        "entities": entities,
        "events": events,
        "travelCandidates": travel_candidates,
        "travelGraph": build_travel_graph(travel_candidates),
        "deferredRecordCount": len(records_by_action["defer"]),
        "blockedRecordCount": len(records_by_action["block"]),
        "notPlayableReason": "missing_layer_aware_olden_map_runtime",
    }
    validation = validate_slice(slice_ir)
    slice_ir["validation"] = validation
    write_json(SLICE_PATH, slice_ir)
    write_json(VALIDATION_PATH, validation)
    update_ir(validation)
    write_report(slice_ir, validation)
    print(
        f"validation={validation['result']} emitted={len(emitted)} edges={len(slice_ir['travelGraph']['edges'])} "
        f"unresolvedTravel={len(slice_ir['travelGraph']['unresolvedCandidates'])}"
    )
    return 0 if validation["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())