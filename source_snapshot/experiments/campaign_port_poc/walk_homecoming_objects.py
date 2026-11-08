#!/usr/bin/env python3
"""Homecoming mission wrapper around the shared H3M object walker."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import h3m_object_walk as core
import port_homecoming_poc as poc

OUT_ROOT = poc.OUT_ROOT / "layered_ir"
IR_PATH = OUT_ROOT / "homecoming.layered_map_ir.json"
WALK_PATH = OUT_ROOT / "homecoming.object_walk.json"
REPORT_PATH = OUT_ROOT / "OBJECT_WALK_REPORT.md"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_homecoming() -> tuple[bytes, poc.H3MShapeSummary, list[dict[str, Any]], dict[str, Any]]:
    if not IR_PATH.exists():
        raise FileNotFoundError(f"layered IR is required before object walking: {IR_PATH}")
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
    campaign_data = poc.read_lod_entry(poc.LOD_PATH, poc.ENTRY_NAME)
    blocks = poc.split_concatenated_gzip_members(campaign_data)
    if len(blocks) < 2:
        raise ValueError(f"expected embedded H3M gzip blocks in {poc.ENTRY_NAME}, got {len(blocks)}")
    h3m = blocks[1].payload
    summary = poc.summarize_h3m_shape(h3m)
    _terrain_start, _object_table_offset, _object_count, templates = poc.locate_h3m_terrain_and_objects(
        h3m,
        summary.size,
        summary.layers,
    )
    return h3m, summary, templates, ir


def walk_objects(
    data: bytes,
    summary: poc.H3MShapeSummary,
    templates: list[dict[str, Any]],
) -> dict[str, Any]:
    walk = core.walk_objects(
        data,
        summary,
        templates,
        core.make_source_metadata(extra={"missionId": "homecoming", "campaignEntry": poc.ENTRY_NAME}),
    )
    walk["schema"] = "homm3.homecoming_object_walk.v0"
    return walk


def validate_walk(walk: dict[str, Any]) -> dict[str, Any]:
    validation = core.validate_generic_walk(walk)
    validation["schema"] = "homm3.homecoming_object_walk.validation.v0"
    errors = list(validation["errors"])
    warnings = list(validation["warnings"])
    table = walk["objectTable"]
    terraneus = [r for r in walk["records"] if r.get("payloadKind") == "town" and r.get("name") == "Terraneus"]
    if len(terraneus) != 1:
        errors.append(f"expected exactly one decoded Terraneus town, found {len(terraneus)}")
    elif terraneus[0].get("key") != "1:35:35":
        errors.append(f"Terraneus key {terraneus[0].get('key')} != 1:35:35")
    validation["result"] = "PASS" if not errors else "FAIL"
    validation["errors"] = errors
    validation["warnings"] = warnings
    validation["checkedInvariants"]["terraneusMatches"] = len(terraneus)
    validation["checkedInvariants"]["unsupportedStop"] = table["unsupportedStop"]
    return validation


def update_ir_object_walk(walk: dict[str, Any], validation: dict[str, Any]) -> None:
    ir = json.loads(IR_PATH.read_text(encoding="utf-8"))
    named_towns = [
        {
            "name": record.get("name"),
            "key": record.get("key"),
            "recordOffset": record.get("recordOffset"),
            "templateAnimation": record.get("templateAnimation"),
            "templateSubtype": record.get("templateSubtype"),
            "townEventCount": record.get("townEventCount"),
        }
        for record in walk["records"]
        if record.get("payloadKind") == "town" and record.get("name")
    ]
    map_events = [
        {
            "key": record.get("key"),
            "recordOffset": record.get("recordOffset"),
            "message": (((record.get("boxContent") or {}).get("messageAndGuards") or {}).get("message")),
            "playersMask": record.get("playersMask"),
            "computerActivate": record.get("computerActivate"),
            "removeAfterVisit": record.get("removeAfterVisit"),
        }
        for record in walk["records"]
        if record.get("payloadKind") == "event"
    ]
    ir["objectInstances"]["sequentialObjectWalk"] = {
        "artifact": str(WALK_PATH),
        "validationResult": validation["result"],
        "declaredCount": walk["objectTable"]["declaredCount"],
        "decodedCount": walk["objectTable"]["decodedCount"],
        "decoderStatus": "full_record_boundary_walk_explicit_payload_and_no_payload_allowlists_payload_summaries_partial",
        "namedTowns": named_towns,
        "mapEvents": map_events,
        "layerTravelCandidates": [
            {
                "key": record.get("key"),
                "recordOffset": record.get("recordOffset"),
                "templateAnimation": record.get("templateAnimation"),
                "templateObjectId": record.get("templateObjectId"),
            }
            for record in walk["records"]
            if record.get("templateObjectId") in (103, 111)
        ],
    }
    terraneus = [town for town in named_towns if town.get("name") == "Terraneus"]
    if len(terraneus) == 1:
        ir["mission"]["declaredVictoryCondition"]["portStatus"] = "trigger_shape_portable_town_object_decoded_payload_summarized"
        ir["mission"]["declaredVictoryCondition"]["sourceObjectKey"] = terraneus[0]["key"]
        ir["mission"]["declaredVictoryCondition"]["sourceRecordOffset"] = terraneus[0]["recordOffset"]
    write_json(IR_PATH, ir)


def write_report(walk: dict[str, Any], validation: dict[str, Any]) -> None:
    table = walk["objectTable"]
    towns = [r for r in walk["records"] if r.get("payloadKind") == "town" and r.get("name")]
    lines = [
        "# Homecoming Object Walk",
        "",
        f"Validation: {validation['result']}",
        f"Decoded records: {table['decodedCount']} / {table['declaredCount']}",
        "",
        "## Named Towns Decoded",
        "",
    ]
    for town in towns:
        lines.append(f"- `{town['name']}` at `{town['key']}` template `{town['templateAnimation']}` record `{town['recordOffset']}`.")
    if table["unsupportedStop"]:
        stop = table["unsupportedStop"]
        lines.extend(["", "## Stop Condition", "", f"Stopped at record `{stop['index']}` offset `{stop['recordOffset']}`: {stop['error']}"])
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "This is a sequential H3M object-table walk using the shared `h3m_object_walk` decoder core plus Homecoming-specific Terraneus validation.",
        ]
    )
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    data, summary, templates, _ir = load_homecoming()
    walk = walk_objects(data, summary, templates)
    validation = validate_walk(walk)
    walk["validation"] = validation
    write_json(WALK_PATH, walk)
    write_json(OUT_ROOT / "object_walk_validation_report.json", validation)
    update_ir_object_walk(walk, validation)
    write_report(walk, validation)
    print(f"validation={validation['result']} decoded={walk['objectTable']['decodedCount']}/{walk['objectTable']['declaredCount']} warnings={len(validation['warnings'])}")
    if walk["objectTable"]["unsupportedStop"]:
        print(json.dumps(walk["objectTable"]["unsupportedStop"], indent=2))
    return 0 if validation["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
