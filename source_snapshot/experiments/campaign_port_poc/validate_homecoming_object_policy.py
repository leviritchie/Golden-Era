#!/usr/bin/env python3
"""Validate the Homecoming reduced-slice object policy against the manifest."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc

OUT_ROOT = poc.OUT_ROOT / "layered_ir"
MANIFEST_PATH = OUT_ROOT / "homecoming.object_port_manifest.json"
VALIDATION_PATH = OUT_ROOT / "homecoming.object_policy_validation_report.json"
REPORT_PATH = OUT_ROOT / "OBJECT_POLICY_REPORT.md"
POLICY_PATH = Path(__file__).with_name("homecoming_object_policy.json")

ALLOWED_ACTIONS = {"emit_stub", "defer", "block"}
REQUIRED_EMIT_RECORD_KEYS = {"0:18:35", "1:35:35", "0:49:3", "0:14:41", "1:14:41", "1:49:3", "0:58:67", "0:21:62"}
PAYLOADLESS_CATEGORY = "payloadless_object_unclassified_for_current_scope"
TERRANEUS_KEY = "1:35:35"
GUARDHOUSE_EVENT_KEY = "0:18:35"
NON_PRIMARY_TOWN_KEYS = {"0:10:54", "0:68:56", "0:35:35", "0:60:8"}
NON_PRIMARY_TOWN_NAMES = {"Plinth", "Caryatid", "Mirham", "Trailia"}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_inputs() -> tuple[dict[str, Any], dict[str, Any]]:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"missing object port manifest: {MANIFEST_PATH}")
    if not POLICY_PATH.exists():
        raise FileNotFoundError(f"missing object policy: {POLICY_PATH}")
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    validation = manifest.get("validation") or {}
    if validation.get("result") != "PASS":
        raise ValueError(f"object manifest must pass before policy validation: {validation}")
    return manifest, policy


def row_matches_record(row: dict[str, Any], record: dict[str, Any]) -> bool:
    object_ids = row.get("objectIds") or []
    if record.get("templateObjectId") not in object_ids:
        return False
    if row.get("sourceCategory") != record.get("category"):
        return False
    source_keys = row.get("sourceKeys")
    if source_keys is not None and record.get("sourceKey") not in source_keys:
        return False
    names = row.get("names")
    if names is not None and record.get("name") not in names:
        return False
    return True


def validate_policy(manifest: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if policy.get("schema") != "homm3.homecoming_object_policy.v0":
        errors.append(f"unexpected policy schema {policy.get('schema')!r}")
    if policy.get("policyMode") != "reduced_playable_slice":
        errors.append(f"unexpected policyMode {policy.get('policyMode')!r}")
    policy_rows = policy.get("objectPolicies")
    if not isinstance(policy_rows, list) or not policy_rows:
        errors.append("objectPolicies must be a non-empty list")
        policy_rows = []

    manifest_records = manifest["records"]
    manifest_keys = {record["sourceKey"] for record in manifest_records}
    matched_records: dict[int, int] = {}
    emitted_keys: set[str] = set()
    deferred_non_primary_town_keys: set[str] = set()
    deferred_non_primary_town_names: set[str] = set()
    policy_object_ids: set[int] = set()
    actions = Counter()

    for row_index, row in enumerate(policy_rows):
        object_ids = row.get("objectIds")
        action = row.get("action")
        if action not in ALLOWED_ACTIONS:
            errors.append(f"policy row {row_index} has unsupported action {action!r}")
        else:
            actions[action] += 1
        for required_field in ("sourceCategory", "scope", "runtimeRequirement", "reason"):
            if not row.get(required_field):
                errors.append(f"policy row {row_index} missing {required_field}")
        if not isinstance(object_ids, list) or not object_ids:
            errors.append(f"policy row {row_index} objectIds must be a non-empty list")
            continue
        for object_id in object_ids:
            if not isinstance(object_id, int):
                errors.append(f"policy row {row_index} has non-integer object id {object_id!r}")
            else:
                policy_object_ids.add(object_id)
        for selector_field in ("sourceKeys", "names"):
            values = row.get(selector_field)
            if values is not None and (not isinstance(values, list) or not values):
                errors.append(f"policy row {row_index} {selector_field} must be a non-empty list when present")

    for record in manifest_records:
        matches = [idx for idx, row in enumerate(policy_rows) if row_matches_record(row, record)]
        if len(matches) != 1:
            errors.append(
                f"source record {record['sourceIndex']} {record['sourceKey']} object {record['templateObjectId']} matched {len(matches)} policy rows {matches}"
            )
            continue
        row_index = matches[0]
        row = policy_rows[row_index]
        matched_records[record["sourceIndex"]] = row_index
        action = row.get("action")
        if record.get("category") == PAYLOADLESS_CATEGORY and action != "block":
            errors.append(f"payloadless source record {record['sourceIndex']} {record['sourceKey']} must remain action=block")
        if action == "emit_stub":
            emitted_keys.add(record["sourceKey"])
            if record["sourceKey"] not in REQUIRED_EMIT_RECORD_KEYS:
                errors.append(f"emit_stub is not authorized for source record {record['sourceIndex']} {record['sourceKey']}")
        if record.get("templateObjectId") == 98 and record.get("sourceKey") != TERRANEUS_KEY:
            if action == "defer":
                deferred_non_primary_town_keys.add(record["sourceKey"])
                if record.get("name"):
                    deferred_non_primary_town_names.add(record["name"])
            else:
                errors.append(f"non-primary town {record['sourceKey']} {record.get('name')} must be action=defer, found {action}")

    if len(matched_records) != len(manifest_records):
        errors.append(f"matched records {len(matched_records)} does not match manifest record count {len(manifest_records)}")
    missing_required_emit = sorted(REQUIRED_EMIT_RECORD_KEYS - emitted_keys)
    if missing_required_emit:
        errors.append(f"reduced playable slice missing emit_stub source keys: {missing_required_emit}")
    unexpected_emit = sorted(emitted_keys - REQUIRED_EMIT_RECORD_KEYS)
    if unexpected_emit:
        errors.append(f"emit_stub produced unexpected source keys: {unexpected_emit}")
    if TERRANEUS_KEY not in emitted_keys:
        errors.append("Terraneus source key is not emitted")
    if GUARDHOUSE_EVENT_KEY not in emitted_keys:
        errors.append("Guardhouse event source key is not emitted")
    if not REQUIRED_EMIT_RECORD_KEYS.issubset(manifest_keys):
        errors.append(f"required emit source keys missing from manifest: {sorted(REQUIRED_EMIT_RECORD_KEYS - manifest_keys)}")
    if deferred_non_primary_town_keys != NON_PRIMARY_TOWN_KEYS:
        errors.append(f"non-primary deferred town keys {sorted(deferred_non_primary_town_keys)} do not match required {sorted(NON_PRIMARY_TOWN_KEYS)}")
    if deferred_non_primary_town_names != NON_PRIMARY_TOWN_NAMES:
        errors.append(f"non-primary deferred town names {sorted(deferred_non_primary_town_names)} do not match required {sorted(NON_PRIMARY_TOWN_NAMES)}")
    if actions.get("block", 0) == 0:
        errors.append("policy must include explicit block rows for unresolved object ids")
    if actions.get("emit_stub", 0) == 0:
        errors.append("policy must include at least one emit_stub row for the reduced slice")

    return {
        "schema": "homm3.homecoming_object_policy.validation.v0",
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "checkedInvariants": {
            "manifestRecords": len(manifest_records),
            "matchedRecords": len(matched_records),
            "policyObjectIds": len(policy_object_ids),
            "policyRows": len(policy_rows),
            "actions": dict(sorted(actions.items())),
            "requiredEmitSourceKeys": sorted(REQUIRED_EMIT_RECORD_KEYS),
            "emittedSourceKeys": sorted(emitted_keys),
            "deferredNonPrimaryTownKeys": sorted(deferred_non_primary_town_keys),
            "deferredNonPrimaryTownNames": sorted(deferred_non_primary_town_names),
        },
    }

def update_ir(validation: dict[str, Any]) -> None:
    ir_path = OUT_ROOT / "homecoming.layered_map_ir.json"
    if not ir_path.exists():
        return
    ir = json.loads(ir_path.read_text(encoding="utf-8"))
    ir.setdefault("objectInstances", {})["objectPolicy"] = {
        "artifact": str(POLICY_PATH),
        "validationArtifact": str(VALIDATION_PATH),
        "validationResult": validation["result"],
        "primaryBlockingFeature": "missing_layer_aware_olden_map_runtime",
    }
    write_json(ir_path, ir)


def write_report(policy: dict[str, Any], validation: dict[str, Any]) -> None:
    invariants = validation["checkedInvariants"]
    lines = [
        "# Homecoming Object Policy",
        "",
        f"Validation: {validation['result']}",
        f"Policy mode: {policy.get('policyMode')}",
        f"Policy rows: {invariants['policyRows']}",
        f"Manifest records matched: {invariants['matchedRecords']}/{invariants['manifestRecords']}",
        "",
        "## Actions",
        "",
    ]
    for action, count in sorted(invariants["actions"].items()):
        lines.append(f"- `{action}`: {count} policy row(s)")
    lines.extend([
        "",
        "## Reduced Slice",
        "",
        "- `emit_stub`: Terraneus, the Guardhouse event, four cave records, and two whirlpool records only.",
        "- Non-primary towns share object id 98 with Terraneus and are explicitly deferred by source key/name.",
        "- Payloadless object records remain blocked until each source object id has a specific interaction/omission policy.",
        "",
        "## Remaining Blocker",
        "",
        "A reduced playable map still requires layer-aware map runtime/emission before these policies can produce playable Olden behavior.",
    ])
    if validation["errors"]:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in validation["errors"])
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    manifest, policy = load_inputs()
    validation = validate_policy(manifest, policy)
    write_json(VALIDATION_PATH, validation)
    update_ir(validation)
    write_report(policy, validation)
    print(
        f"validation={validation['result']} matchedRecords={validation['checkedInvariants']['matchedRecords']} "
        f"manifestRecords={validation['checkedInvariants']['manifestRecords']}"
    )
    return 0 if validation["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())