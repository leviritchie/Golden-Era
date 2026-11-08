#!/usr/bin/env python3
"""Build a no-swap layered map IR for RoE Castle mission 1: Homecoming.

This intentionally does not generate an Olden .map. It preserves the decoded H3M
surface and underground terrain as repo-owned IR and emits explicit unsupported
records for object payloads, event ownership, and native Olden multi-layer load.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import port_homecoming_poc as poc


OUT_ROOT = poc.OUT_ROOT / "layered_ir"


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def decode_h3m_layer_tiles(data: bytes, summary: poc.H3MShapeSummary) -> list[dict[str, Any]]:
    layers: list[dict[str, Any]] = []
    tiles_per_layer = summary.size * summary.size
    for layer in range(summary.layers):
        tile_rows: list[dict[str, int | str]] = []
        layer_start = summary.terrain_start + layer * tiles_per_layer * 7
        for tile_index in range(tiles_per_layer):
            x = tile_index % summary.size
            y = tile_index // summary.size
            pos = layer_start + tile_index * 7
            terrain = data[pos]
            terrain_sprite = data[pos + 1]
            river = data[pos + 2] & 0x07
            river_sprite = data[pos + 3]
            road = data[pos + 4] & 0x07
            road_sprite = data[pos + 5]
            mirror = data[pos + 6]
            tile_rows.append(
                {
                    "key": f"{layer}:{x}:{y}",
                    "x": x,
                    "y": y,
                    "terrain": terrain,
                    "terrainSprite": terrain_sprite,
                    "river": river,
                    "riverSprite": river_sprite,
                    "road": road,
                    "roadSprite": road_sprite,
                    "mirror": mirror,
                }
            )
        layers.append(
            {
                "index": layer,
                "sid": "surface" if layer == 0 else "underground",
                "isUnderground": layer != 0,
                "width": summary.size,
                "height": summary.size,
                "tileCount": tiles_per_layer,
                "terrainHistogram": summary.terrain_histograms[layer],
                "roadHistogram": summary.road_histograms[layer],
                "riverHistogram": summary.river_histograms[layer],
                "tiles": tile_rows,
            }
        )
    return layers


def decode_first_object_header(data: bytes, summary: poc.H3MShapeSummary, templates: list[dict[str, Any]]) -> dict[str, Any]:
    reader = poc.BinaryReader(data)
    reader.seek(summary.object_table_offset + 4)
    offset = reader.tell()
    x = reader.read_u8()
    y = reader.read_u8()
    z = reader.read_u8()
    template_index = reader.read_u32()
    if template_index >= len(templates):
        raise ValueError(f"first object template index {template_index} outside template count {len(templates)}")
    template = templates[template_index]
    return {
        "recordOffset": f"0x{offset:x}",
        "x": x,
        "y": y,
        "z": z,
        "layer": z,
        "key": f"{z}:{x}:{y}",
        "templateIndex": template_index,
        "templateAnimation": template["animation"],
        "templateObjectId": template["objectId"],
        "templateSubtype": template["subtype"],
        "decoderStatus": "header_only_payload_not_decoded",
    }


def template_name_candidates(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, template in enumerate(templates):
        animation = str(template.get("animation") or "")
        lowered = animation.lower()
        if any(token in lowered for token in ("gate", "sub", "mon", "whirl", "portal")):
            rows.append(
                {
                    "templateIndex": index,
                    "animation": animation,
                    "objectId": template.get("objectId"),
                    "subtype": template.get("subtype"),
                    "status": "name_candidate_only_not_semantic_transition_proof",
                }
            )
    return rows


def build_layered_map_ir(
    *,
    h3m_data: bytes,
    summary: poc.H3MShapeSummary,
    templates: list[dict[str, Any]],
    campaign_title: str,
    mission_title: str,
    objective: str,
    briefing_texts: list[str],
    likely_event_strings: list[poc.ExtractedString],
) -> dict[str, Any]:
    first_object_header = decode_first_object_header(h3m_data, summary, templates)
    return {
        "schema": "homm3.layered_map_ir.v0",
        "status": "partial_header_and_terrain_decode",
        "source": {
            "campaignEntry": poc.ENTRY_NAME,
            "h3mName": "Good-1a.h3m",
            "campaignTitle": campaign_title,
            "missionTitle": mission_title,
            "h3mVersion": summary.version,
            "sourceCoordinateSystem": "heroes3_square_tile_xyz",
            "nodeKey": "layer:x:y",
        },
        "mission": {
            "objectiveText": objective,
            "briefingTexts": briefing_texts,
            "declaredVictoryCondition": {
                "kind": "capture_named_town",
                "sourceName": "Terraneus",
                "portStatus": "trigger_shape_portable_but_object_entity_unresolved",
            },
        },
        "mapShape": {
            "width": summary.size,
            "height": summary.size,
            "layers": summary.layers,
            "tilesPerLayer": summary.size * summary.size,
            "totalLayerTiles": summary.size * summary.size * summary.layers,
        },
        "layers": decode_h3m_layer_tiles(h3m_data, summary),
        "objectTemplates": {
            "declaredCount": len(templates),
            "firstTemplateNames": [item["animation"] for item in templates[:20]],
            "crossLayerTemplateNameCandidates": template_name_candidates(templates),
            "status": "template_catalog_decoded_full_catalog_not_emitted_in_this_ir_slice",
        },
        "objectInstances": {
            "declaredCount": summary.object_count,
            "decodedHeaders": [first_object_header],
            "undecodedRecordCount": max(0, summary.object_count - 1),
            "status": "object_payload_decoder_missing_no_instances_dropped_from_accounting",
        },
        "eventTextRecords": [
            {
                "offset": f"0x{item.offset:x}",
                "text": item.text,
                "owner": None,
                "portStatus": "text_portable_owner_trigger_unresolved_until_object_payload_decode",
            }
            for item in likely_event_strings
        ],
        "crossLayerTransitions": {
            "status": "not_decoded",
            "reason": "Cross-layer entrances require object payload/type decoding; no transition edge is inferred from text or DEF names.",
            "explicitEdges": [],
        },
        "unsupportedFeatureRecords": [
            {
                "feature": "native_olden_multi_layer_map_load",
                "severity": "blocking_for_faithful_map",
                "reason": "Golden Era map containers audited so far expose flat MapData arrays sized sizeX_ * sizeZ_, not per-layer semantic storage.",
            },
            {
                "feature": "h3m_object_payload_decode",
                "severity": "blocking_for_object_and_event_placement",
                "reason": "Only object table count and the first fixed header are decoded in this slice; variable object payloads are not skipped or interpreted.",
            },
            {
                "feature": "event_owner_binding",
                "severity": "blocking_for_trigger_port",
                "reason": "Likely event strings are extracted, but object ownership and trigger conditions are unresolved.",
            },
        ],
        "silentFallbacksUsed": False,
    }


def validate_layered_map_ir(ir: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    shape = ir["mapShape"]
    width = shape["width"]
    height = shape["height"]
    layer_count = shape["layers"]
    expected_tiles_per_layer = width * height
    expected_total = expected_tiles_per_layer * layer_count
    seen_keys: set[str] = set()
    layer_tile_counts: list[int] = []
    for layer in ir["layers"]:
        tiles = layer.get("tiles") or []
        layer_tile_counts.append(len(tiles))
        if len(tiles) != expected_tiles_per_layer:
            errors.append(f"layer {layer.get('index')} tile count {len(tiles)} != {expected_tiles_per_layer}")
        for tile in tiles:
            key = tile.get("key")
            if not isinstance(key, str):
                errors.append(f"layer {layer.get('index')} contains tile without string key")
                continue
            if key in seen_keys:
                errors.append(f"duplicate layer-qualified tile key {key}")
            seen_keys.add(key)
            if tile.get("x", -1) < 0 or tile.get("x", width) >= width or tile.get("y", -1) < 0 or tile.get("y", height) >= height:
                errors.append(f"tile key {key} has out-of-range coordinates")
    if len(seen_keys) != expected_total:
        errors.append(f"unique layer-qualified keys {len(seen_keys)} != expected total {expected_total}")
    objects = ir["objectInstances"]
    if objects["decodedHeaders"] and objects["decodedHeaders"][0]["layer"] >= layer_count:
        errors.append("first decoded object header points outside layer range")
    if objects["declaredCount"] != len(objects["decodedHeaders"]) + objects["undecodedRecordCount"]:
        errors.append("object instance accounting does not preserve declared count")
    if ir.get("silentFallbacksUsed") is not False:
        errors.append("silentFallbacksUsed must be false")
    if objects["undecodedRecordCount"]:
        warnings.append("object payloads are explicitly unresolved; object placement/event ownership remains blocked")
    if ir["eventTextRecords"]:
        warnings.append("event text extracted without owners; trigger port is intentionally incomplete")
    return {
        "schema": "homm3.layered_map_ir.validation.v0",
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": warnings,
        "checkedInvariants": {
            "layers": layer_count,
            "width": width,
            "height": height,
            "expectedTilesPerLayer": expected_tiles_per_layer,
            "expectedTotalLayerTiles": expected_total,
            "actualLayerTileCounts": layer_tile_counts,
            "uniqueLayerQualifiedTileKeys": len(seen_keys),
            "declaredObjectInstances": objects["declaredCount"],
            "decodedObjectHeaders": len(objects["decodedHeaders"]),
            "undecodedObjectRecords": objects["undecodedRecordCount"],
            "eventTextRecords": len(ir["eventTextRecords"]),
            "silentFallbacksUsed": ir.get("silentFallbacksUsed"),
        },
        "blockers": ir["unsupportedFeatureRecords"],
    }


def write_markdown_report(ir: dict[str, Any], validation: dict[str, Any]) -> None:
    shape = ir["mapShape"]
    objects = ir["objectInstances"]
    first = objects["decodedHeaders"][0]
    text = f"""# Homecoming Layered Map IR

Status: `{validation['result']}` validation for the repo-owned layered IR. This is
not an Olden `.map` and does not mutate `Core.zip` or the Golden Era install.

## Preserved Programmatically

- Campaign mission identity: `{ir['source']['campaignTitle']}` / `{ir['source']['missionTitle']}`.
- Objective text and first two briefing texts.
- H3M shape: {shape['width']}x{shape['height']} with {shape['layers']} simultaneous layers.
- Layer-qualified tile keys: `{ir['source']['nodeKey']}`.
- Terrain/river/road/mirror bytes for all {shape['totalLayerTiles']} layer tiles.
- Object accounting: declared {objects['declaredCount']} instances, with the first fixed header decoded and {objects['undecodedRecordCount']} records explicitly unresolved.
- Event text accounting: {len(ir['eventTextRecords'])} likely event text records kept as unowned trigger text.

## First Decoded Object Header

- Offset: `{first['recordOffset']}`
- Key: `{first['key']}`
- Template: `{first['templateAnimation']}`
- Template object/subtype: `{first['templateObjectId']}` / `{first['templateSubtype']}`

## Validation

- Result: `{validation['result']}`
- Errors: {len(validation['errors'])}
- Warnings: {len(validation['warnings'])}
- Tile counts by layer: {validation['checkedInvariants']['actualLayerTileCounts']}
- Unique layer-qualified tile keys: {validation['checkedInvariants']['uniqueLayerQualifiedTileKeys']}
- Silent fallbacks used: `{validation['checkedInvariants']['silentFallbacksUsed']}`

## Current Blockers

1. Native Golden Era map containers still need a proven semantic multi-layer load/render path before this can become a faithful `.map`.
2. H3M object payload decoding is still required before object placement, Terraneus identity, and cross-layer entrances can be ported.
3. Event strings are portable as text, but event owners and trigger conditions remain unresolved.

No swap-based layer representation was emitted.
"""
    (OUT_ROOT / "PORTABILITY_REPORT.md").write_text(text, encoding="utf-8")


def main() -> int:
    compressed_campaign = poc.read_lod_entry(poc.LOD_PATH, poc.ENTRY_NAME)
    h3c_blocks = poc.split_concatenated_gzip_members(compressed_campaign)
    campaign = b"".join(block.payload for block in h3c_blocks)
    if len(h3c_blocks) < 2:
        raise ValueError("campaign did not contain Homecoming H3M block")
    homecoming_h3m = h3c_blocks[1].payload
    summary = poc.summarize_h3m_shape(homecoming_h3m)
    _terrain_start, _object_table_offset, _object_count, templates = poc.locate_h3m_terrain_and_objects(homecoming_h3m, summary.size, summary.layers)

    strings = poc.scan_length_prefixed_strings(campaign)
    campaign_title = poc.find_required_string(strings, "Long Live the Queen")
    map_name = poc.find_required_string(strings, "Good-1a.h3m")
    homecoming = poc.find_required_string(strings, "Homecoming")
    guardian_angels = poc.find_required_string(strings, "Guardian Angels")
    objective = poc.first_string_containing(strings, "Terraneus", after=homecoming.offset)
    first_briefing = poc.first_string_containing(strings, "Queen Catherine has departed", after=map_name.offset)
    second_briefing = poc.first_string_containing(strings, "Our initial landing", after=first_briefing.offset)
    first_map_strings = [item for item in strings if homecoming.offset <= item.offset < guardian_angels.offset]
    likely_event_strings = [
        item
        for item in first_map_strings
        if ".def" not in item.text.lower()
        and len(item.text) >= 10
        and item.text not in {"Homecoming", objective.text}
    ]

    ir = build_layered_map_ir(
        h3m_data=homecoming_h3m,
        summary=summary,
        templates=templates,
        campaign_title=campaign_title.text,
        mission_title=homecoming.text,
        objective=objective.text,
        briefing_texts=[first_briefing.text, second_briefing.text],
        likely_event_strings=likely_event_strings,
    )
    validation = validate_layered_map_ir(ir)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_json(OUT_ROOT / "homecoming.layered_map_ir.json", ir)
    write_json(OUT_ROOT / "validation_report.json", validation)
    write_markdown_report(ir, validation)
    print(f"wrote {OUT_ROOT}")
    print(f"validation={validation['result']} errors={len(validation['errors'])} warnings={len(validation['warnings'])}")
    if validation["errors"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
