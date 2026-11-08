#!/usr/bin/env python3
"""Conservative Homecoming object probe for named town placement.

This is not a full H3M object decoder. It uses the fixed object instance prefix
and the VCMI-documented AB town prefix only to identify named town objects such
as Terraneus. All other object payload boundaries remain unresolved.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc


OUT_ROOT = poc.OUT_ROOT / "layered_ir"
OBJECT_PROBE_PATH = OUT_ROOT / "homecoming.object_probe.json"
OBJECT_REPORT_PATH = OUT_ROOT / "OBJECT_PROBE_REPORT.md"
IR_PATH = OUT_ROOT / "homecoming.layered_map_ir.json"
TOWN_OBJECT_ID = 98
EXPECTED_TERRANEUS = {
    "name": "Terraneus",
    "x": 35,
    "y": 35,
    "layer": 1,
    "templateAnimation": "AVCdung0.def",
    "templateObjectId": TOWN_OBJECT_ID,
    "templateSubtype": 5,
}


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def load_layered_ir() -> dict[str, Any]:
    if not IR_PATH.exists():
        raise FileNotFoundError(f"layered IR is required before object probing: {IR_PATH}")
    return json.loads(IR_PATH.read_text(encoding="utf-8"))


def load_homecoming() -> tuple[bytes, poc.H3MShapeSummary, list[dict[str, Any]], str, str]:
    layered_ir = load_layered_ir()
    campaign_data = poc.read_lod_entry(poc.LOD_PATH, poc.ENTRY_NAME)
    blocks = poc.split_concatenated_gzip_members(campaign_data)
    if len(blocks) < 2:
        raise ValueError(f"expected embedded H3M gzip blocks in {poc.ENTRY_NAME}, got {len(blocks)}")
    homecoming_data = blocks[1].payload
    summary = poc.summarize_h3m_shape(homecoming_data)
    _terrain_start, _object_table_offset, _object_count, templates = poc.locate_h3m_terrain_and_objects(
        homecoming_data,
        summary.size,
        summary.layers,
    )
    title = summary.title or "Homecoming"
    objective = layered_ir["mission"]["objectiveText"]
    return homecoming_data, summary, templates, title, objective


def plausible_object_header_offsets(data: bytes, summary: poc.H3MShapeSummary, templates: list[dict[str, Any]]) -> list[int]:
    offsets: list[int] = []
    start = summary.object_table_offset + 4
    end = len(data) - 12
    for offset in range(start, end):
        x = data[offset]
        y = data[offset + 1]
        z = data[offset + 2]
        if x >= summary.size or y >= summary.size or z >= summary.layers:
            continue
        template_index = int.from_bytes(data[offset + 3 : offset + 7], "little")
        if template_index >= len(templates):
            continue
        if data[offset + 7 : offset + 12] != b"\x00\x00\x00\x00\x00":
            continue
        offsets.append(offset)
    return offsets


def printable_name(value: str) -> bool:
    return 1 <= len(value) <= 64 and poc.printable_score(value) >= 0.95 and any(ch.isalpha() for ch in value)


def parse_town_prefix(data: bytes, offset: int, summary: poc.H3MShapeSummary, templates: list[dict[str, Any]]) -> dict[str, Any] | None:
    x = data[offset]
    y = data[offset + 1]
    layer = data[offset + 2]
    template_index = int.from_bytes(data[offset + 3 : offset + 7], "little")
    template = templates[template_index]
    if template.get("objectId") != TOWN_OBJECT_ID:
        return None

    reader = poc.BinaryReader(data)
    reader.seek(offset + 12)
    try:
        identifier = reader.read_u32()
        owner = reader.read_u8()
        if not (owner <= 8 or owner == 255):
            return None
        has_name = reader.read_bool()
        name = reader.read_base_string(max_length=256) if has_name else None
        if name is not None and not printable_name(name):
            return None
        after_name = reader.tell()
        next_bool = data[after_name] if after_name < len(data) else None
        if next_bool not in (0, 1, None):
            return None
    except Exception:
        return None

    return {
        "recordOffset": f"0x{offset:x}",
        "x": x,
        "y": y,
        "z": layer,
        "layer": layer,
        "key": f"{layer}:{x}:{y}",
        "templateIndex": template_index,
        "templateAnimation": template.get("animation"),
        "templateObjectId": template.get("objectId"),
        "templateSubtype": template.get("subtype"),
        "identifier": f"0x{identifier:08x}",
        "owner": owner,
        "hasName": has_name,
        "name": name,
        "prefixBytesDecoded": after_name - offset,
        "decoderStatus": "town_prefix_only_payload_tail_not_decoded",
    }


def validate_probe(probe: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    towns = probe["townPrefixCandidates"]
    named = [item for item in towns if item.get("name")]
    terraneus = [item for item in named if item.get("name") == EXPECTED_TERRANEUS["name"]]
    if len(terraneus) != 1:
        errors.append(f"expected exactly one Terraneus town prefix, found {len(terraneus)}")
    else:
        row = terraneus[0]
        for key, expected in EXPECTED_TERRANEUS.items():
            if row.get(key) != expected:
                errors.append(f"Terraneus {key} {row.get(key)!r} != {expected!r}")
    if probe.get("silentFallbacksUsed") is not False:
        errors.append("silentFallbacksUsed must be false")
    if probe["fullObjectDecoder"]["status"] != "not_implemented_in_this_slice":
        errors.append("full object decoder status must remain explicit")
    if not named:
        errors.append("town prefix probe found no named towns")
    warnings.append("town prefixes are decoded only far enough to bind names and coordinates; full object payload tails remain unresolved")
    warnings.append("candidate offsets come from prefix invariants and can include false positives for unnamed towns; named Terraneus is validated by exact town-prefix shape")
    return {
        "schema": "homm3.homecoming_object_probe.validation.v0",
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "checkedInvariants": {
            "townPrefixCandidates": len(towns),
            "namedTownPrefixCandidates": len(named),
            "terraneusMatches": len(terraneus),
        },
    }


def update_ir_object_probe(probe: dict[str, Any], validation: dict[str, Any]) -> None:
    ir = load_layered_ir()
    terraneus = [item for item in probe["townPrefixCandidates"] if item.get("name") == "Terraneus"]
    ir["objectInstances"]["namedTownPrefixes"] = {
        "artifact": str(OBJECT_PROBE_PATH),
        "decoderStatus": "town_prefix_only_payload_tail_not_decoded",
        "validatedTerraneus": terraneus[0] if len(terraneus) == 1 else None,
        "validationResult": validation["result"],
    }
    if len(terraneus) == 1:
        ir["mission"]["declaredVictoryCondition"]["portStatus"] = "trigger_shape_portable_town_prefix_located_payload_tail_unresolved"
        ir["mission"]["declaredVictoryCondition"]["sourceObjectKey"] = terraneus[0]["key"]
    write_json(IR_PATH, ir)


def build_report(probe: dict[str, Any], validation: dict[str, Any]) -> str:
    named = [item for item in probe["townPrefixCandidates"] if item.get("name")]
    lines = [
        "# Homecoming Object Probe",
        "",
        f"Validation: {validation['result']}",
        "",
        "## Scope",
        "",
        "This artifact decodes only the fixed H3M object instance prefix plus the AB-level town prefix documented by VCMI: position, template index, five zero bytes, town identifier, owner, has-name flag, and name string. It does not skip or decode full object payload tails.",
        "",
        "## Named Town Prefixes",
        "",
    ]
    for item in named:
        lines.append(
            f"- `{item['name']}` at `{item['key']}` from `{item['templateAnimation']}` "
            f"(record `{item['recordOffset']}`, owner `{item['owner']}`, subtype `{item['templateSubtype']}`)."
        )
    lines.extend(
        [
            "",
            "## Result",
            "",
            "Terraneus is now programmatically located at underground key `1:35:35` with Dungeon town template `AVCdung0.def`. This is enough to attach the Homecoming victory objective to a source-layer coordinate in the IR, but not enough to emit a faithful Olden map object because the remaining town payload and the rest of the object table are not decoded.",
            "",
            "## Remaining Blockers",
            "",
            "- Full H3M object payload boundary decoder for all 1,853 object records.",
            "- Event object ownership and trigger payload decoding.",
            "- H3 object-template to Olden object-SID mapping and footprint transform.",
            "- Native Olden multi-layer map representation or custom layer-aware map runtime.",
        ]
    )
    if validation["errors"]:
        lines.extend(["", "## Validation Errors", ""])
        lines.extend(f"- {error}" for error in validation["errors"])
    return "\n".join(lines) + "\n"


def main() -> int:
    h3m_data, summary, templates, title, objective = load_homecoming()
    header_offsets = plausible_object_header_offsets(h3m_data, summary, templates)
    town_candidates: list[dict[str, Any]] = []
    for offset in header_offsets:
        parsed = parse_town_prefix(h3m_data, offset, summary, templates)
        if parsed is not None:
            town_candidates.append(parsed)
    town_candidates.sort(key=lambda item: (item["layer"], item["y"], item["x"], item["recordOffset"]))

    probe = {
        "schema": "homm3.homecoming_object_probe.v0",
        "source": {
            "campaignEntry": poc.ENTRY_NAME,
            "h3mName": "Good-1a.h3m",
            "missionTitle": title,
            "objectiveText": objective,
            "sourceCoordinateSystem": "heroes3_square_tile_xyz",
            "nodeKey": "layer:x:y",
        },
        "formatAssumption": {
            "h3mVersion": summary.version,
            "vcmiFeatureLevel": "levelAB",
            "townPrefixIncludesIdentifierU32": True,
            "evidence": "VCMI readTown reads identifier before owner when features.levelAB is true; Homecoming named town bytes match only with that field present.",
        },
        "objectTable": {
            "declaredCount": summary.object_count,
            "objectTableOffset": f"0x{summary.object_table_offset:x}",
            "plausiblePrefixOffsetsScanned": len(header_offsets),
            "status": "prefix_scan_only_not_record_boundary_decode",
        },
        "townPrefixCandidates": town_candidates,
        "fullObjectDecoder": {
            "status": "not_implemented_in_this_slice",
            "reason": "Variable payload tails are object-type-specific and must be skipped using a real H3M object reader before all object boundaries/events can be trusted.",
        },
        "silentFallbacksUsed": False,
    }
    validation = validate_probe(probe)
    probe["validation"] = validation
    write_json(OBJECT_PROBE_PATH, probe)
    write_json(OUT_ROOT / "object_probe_validation_report.json", validation)
    OBJECT_REPORT_PATH.write_text(build_report(probe, validation), encoding="utf-8")
    update_ir_object_probe(probe, validation)
    print(
        f"validation={validation['result']} errors={len(validation['errors'])} "
        f"warnings={len(validation['warnings'])} namedTowns={validation['checkedInvariants']['namedTownPrefixCandidates']} "
        f"terraneus={validation['checkedInvariants']['terraneusMatches']}"
    )
    return 0 if validation["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
