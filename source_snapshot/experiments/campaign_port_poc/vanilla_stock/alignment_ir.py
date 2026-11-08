"""Build raw-shaped alignment IR from a standalone HoMM3 .h3m.

Produces the ``propEntities`` + ``layeredMapData`` shape that the vanilla_stock
emit path consumes, without requiring an H3C campaign block. Reuses:

- ``h3m_object_walk.walk_h3m_file`` for records
- ``build_homecoming_object_port_manifest.classify_record`` for category
- ``build_homecoming_olden_storage_alignment.build_entities`` / ``flatten_layer_tiles``
- ``build_homecoming_layered_ir.decode_h3m_layer_tiles`` for terrain arrays
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import build_homecoming_layered_ir as layered_ir
import build_homecoming_object_port_manifest as port_manifest
import build_homecoming_olden_storage_alignment as align
from h3m_object_walk import read_h3m_bytes, summarize_h3m, walk_h3m_file

from . import SCHEMA_ALIGNMENT, STATUS


class VanillaStockAlignmentError(ValueError):
    """Raised when a standalone H3M cannot be turned into alignment IR."""


def _configure_alignment_module(source_size: int) -> None:
    align.SOURCE_SIZE = source_size
    align.SOURCE_TILE_COUNT = source_size * source_size


def build_manifest_records(walk_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for record in walk_records:
        if not isinstance(record, dict):
            raise VanillaStockAlignmentError("walk record must be an object")
        try:
            classified = port_manifest.classify_record(record)
        except ValueError:
            # Standalone maps may include object ids outside the campaign classifier
            # table. Keep a generic IR row so stock object_map can still omit/emit.
            classified = {
                "sourceIndex": record["index"],
                "sourceKey": record["key"],
                "recordOffset": record.get("recordOffset"),
                "templateAnimation": record.get("templateAnimation"),
                "templateBlockMask": record.get("templateBlockMask"),
                "templateVisitMask": record.get("templateVisitMask"),
                "templateObjectId": record.get("templateObjectId"),
                "templateSubtype": record.get("templateSubtype"),
                "payloadKind": record.get("payloadKind"),
                "category": str(record.get("payloadKind") or "unclassified_standalone"),
                "geometryPort": "coordinate_portable",
                "owner": record.get("owner"),
                "classificationFallback": "standalone_unclassified_object_id",
            }
            for key in (
                "identifier",
                "count",
                "character",
                "hasMessage",
                "message",
                "artifact",
                "guardResources",
                "neverFlees",
                "notGrowingTeam",
                "ownerEncoding",
                "generatorFamily",
                "payloadDecoderEvidence",
                "heroType",
                "name",
                "amount",
                "isRandomResource",
                "messageAndGuards",
                "playersMask",
                "computerActivate",
                "removeAfterVisit",
                "boxContent",
                "townState",
            ):
                if key in record:
                    classified[key] = record[key]
        records.append(classified)
    return records


def build_layered_map_data_from_layers(
    layers: list[dict[str, Any]],
    *,
    source_size: int,
) -> list[dict[str, Any]]:
    _configure_alignment_module(source_size)
    layered_map_data: list[dict[str, Any]] = []
    for layer in layers:
        layer_index = int(layer["index"])
        # synthesize the IR layer shape expected by flatten_layer_tiles
        ir_layer = {
            "width": source_size,
            "height": source_size,
            "tiles": layer["tiles"],
        }
        flat = align.flatten_layer_tiles(ir_layer)
        # Olden query-shape map chunk arrays (H3 codes, not yet stock-projected).
        map_data = {
            "sizeX_": source_size,
            "sizeZ_": source_size,
            "tilesMap": flat["terrain"],
            "roadsMap": flat["road"],
            "waterMap": flat["water"],
            "levelsMap": [0] * (source_size * source_size),
            "climbsMap": [0] * (source_size * source_size),
            "mirrorsMap": flat["mirror"],
        }
        layered_map_data.append(
            {
                "layer": layer_index,
                "sid": "surface" if layer_index == 0 else "underground",
                "alignment": "raw_query_shape_only",
                "mapData": map_data,
            }
        )
    return layered_map_data


def build_alignment_ir(
    *,
    h3m_path: Path,
    map_sid: str,
    title: str | None = None,
) -> dict[str, Any]:
    """Build in-memory alignment IR for a standalone .h3m."""
    if not h3m_path.is_file():
        raise VanillaStockAlignmentError(f"H3M not found: {h3m_path}")

    data = read_h3m_bytes(h3m_path)
    summary = summarize_h3m(data)
    walk = walk_h3m_file(h3m_path, include_records=True)
    if not (walk.get("objectTable") or {}).get("complete"):
        raise VanillaStockAlignmentError(f"H3M object walk incomplete: {h3m_path}")

    source_size = int(summary.size)
    _configure_alignment_module(source_size)

    layers = layered_ir.decode_h3m_layer_tiles(data, summary)
    layer_ids = [int(layer["index"]) for layer in layers]
    if layer_ids != list(range(len(layer_ids))):
        raise VanillaStockAlignmentError(f"unexpected layer index sequence: {layer_ids}")

    manifest_records = build_manifest_records(
        [row for row in walk["records"] if isinstance(row, dict)]
    )
    entities, layer_hist = align.build_entities(manifest_records)
    layer_hist = dict(sorted(layer_hist.items()))
    layered_map_data = build_layered_map_data_from_layers(layers, source_size=source_size)

    map_title = title or str(summary.title or h3m_path.stem)
    description = str(summary.description or f"Vanilla stock translation of {map_title}")

    # Minimal story payload (no H3C briefing) so container.chunks[3] exists.
    story_payload = {
        "comment": f"vanilla_stock standalone {map_sid}",
        "briefingSegments": [],
        "objectiveText": description,
        "missionTitle": map_title,
        "source": "standalone_h3m_header",
    }

    global_properties = align.build_layer_object_properties(
        entities,
        before_actions=[],
        after_actions=[],
        scope=align.GLOBAL_OBJECT_PROPERTIES_SCOPE,
    )

    return {
        "schema": SCHEMA_ALIGNMENT,
        "status": STATUS,
        "pipeline": "vanilla_stock",
        "mapSid": map_sid,
        "title": map_title,
        "description": description,
        "source": {
            "h3m": str(h3m_path),
            "sourceSize": source_size,
            "sourceLayers": int(summary.layers),
            "sourceObjectCount": len(manifest_records),
            "sourceLayerCounts": layer_hist,
            "campaignEntry": None,
            "standalone": True,
        },
        "alignment": {
            "alignmentMode": align.ALIGNMENT_MODE,
            "nonNative": True,
            "surfaceLayer": "surface",
            "undergroundLayer": "underground" if len(layers) > 1 else None,
            "globalObjectProperties": global_properties,
        },
        "layeredMapData": layered_map_data,
        "globalEntities": entities,
        "layers": layers,
        "walkRecords": [row for row in walk["records"] if isinstance(row, dict)],
        "manifestRecords": manifest_records,
        "globalTimedEvents": walk.get("globalTimedEvents"),
        "summary": {
            "title": summary.title,
            "description": summary.description,
            "size": summary.size,
            "layers": summary.layers,
            "objectCount": summary.object_count,
        },
        "container": {
            "version": "vanilla-stock-standalone-alignment.v1",
            "chunks": [
                {
                    "sizeX": source_size,
                    "sizeZ": source_size,
                    "title": map_title,
                    "mapSid": map_sid,
                    "sourceLayerHistogram": layer_hist,
                    "nonPlayable": True,
                    "standaloneH3m": True,
                },
                layered_map_data[0]["mapData"] if layered_map_data else {},
                {"dialogs": {"lines": []}, "quests": {"quests": []}},
                story_payload,
            ],
        },
        "validationGates": {
            "expectSourceObjectCount": len(manifest_records),
            "expectLayerCount": len(layers),
            "expectTerrainLength": source_size * source_size,
        },
    }


def entity_layer_histogram(entities: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(e.get("sourceLayer")) for e in entities).items()))
