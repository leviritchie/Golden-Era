#!/usr/bin/env python3
"""Proof-of-concept RoE Castle campaign mission extractor for Olden Era.

This is intentionally narrow: it extracts Good1.h3c from a local HoMM3 LOD,
decompresses it, mines the first mission's length-prefixed strings, and emits
Olden-style campaign/quest skeleton JSON plus an audit report. It does not
pretend to decode full H3M placed-object geometry.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import struct
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import scenario_menu_shell


ROOT = Path(__file__).resolve().parents[2]
LOD_PATH = ROOT / "HoMM 3 Complete" / "Data" / "H3bitmap.lod"
ENTRY_NAME = "Good1.h3c"
OUT_ROOT = Path(os.environ.get("HOMECOMING_POC_OUT_ROOT", ROOT / "artifacts" / "campaign_port_poc" / "homecoming_poc"))
SOURCE_DIR = OUT_ROOT / "source"
OLDEN_DIR = OUT_ROOT / "olden_skeleton"
PLAYABLE_DIR = OUT_ROOT / "playable_shell"
OLDEN_MAPS_DIR = (
    Path("V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era")
    / "HeroesOldenEra_Data"
    / "StreamingAssets"
    / "maps"
)
OLDEN_STORY_MAPS_DIR = OLDEN_MAPS_DIR / "Story_maps"
# Batch/parallel emit may pin a frozen Core.zip snapshot via env to avoid racing
# the live install path (BadZipFile) and to share one read-only catalog across workers.
_OLDEN_CORE_ZIP_ENV = "OLDEN_ERA_CORE_ZIP"


def resolve_olden_core_zip() -> Path:
    override = (os.environ.get(_OLDEN_CORE_ZIP_ENV) or "").strip()
    if override:
        return Path(override)
    return OLDEN_MAPS_DIR.parent / "Core.zip"


OLDEN_CORE_ZIP = resolve_olden_core_zip()
PLAYABLE_TEMPLATE_MAP = OLDEN_MAPS_DIR / "Thirst_for_Power.map"
PLAYABLE_MAP_SID = "h3_roe_castle_homecoming_poc"
HOMECOMING_TITLE_SID = "homm3_roe_castle_homecoming_title"
HOMECOMING_DESCRIPTION_SID = "homm3_roe_castle_homecoming_description"
HOMECOMING_INTRO_SID = "homm3_roe_castle_homecoming_intro"
HOMECOMING_CAPTURE_TERRANEUS_SID = "homm3_roe_castle_homecoming_capture_terraneus"
TERRANEUS_PROXY_TEMPLATE_ID = 5881
HOMM3_CUSTOM_TOWN_BUILDINGS_CONSTRUCTION_SID = "homm3_custom_town_buildings_construction"


@dataclass(frozen=True)
class ExtractedString:
    offset: int
    text: str


@dataclass(frozen=True)
class H3CBlock:
    index: int
    compressed_offset: int
    compressed_size: int
    payload: bytes


@dataclass(frozen=True)
class H3MShapeSummary:
    version: int
    size: int
    layers: int
    title: str
    description: str
    difficulty: int
    terrain_start: int
    terrain_bytes: int
    template_table_offset: int
    object_table_offset: int
    template_count: int
    object_count: int
    first_template_names: list[str]
    terrain_histograms: list[dict[str, int]]
    road_histograms: list[dict[str, int]]
    river_histograms: list[dict[str, int]]


@dataclass(frozen=True)
class OldenMapContainer:
    version: str
    prefix_suffix: bytes
    chunks: list[dict[str, Any]]


def read_lod_entry(lod_path: Path, entry_name: str) -> bytes:
    header_size = 92
    entry_size = 32
    with lod_path.open("rb") as stream:
        file_size = os.fstat(stream.fileno()).st_size
        if file_size < header_size:
            raise ValueError(f"truncated Heroes III LOD header: {lod_path}")

        header = stream.read(header_size)
        if len(header) != header_size:
            raise ValueError(f"truncated Heroes III LOD header: {lod_path}")
        if header[:4] != b"LOD\0":
            raise ValueError(f"not a Heroes III LOD archive: {lod_path}")

        total, = struct.unpack_from("<I", header, 8)
        table_bytes = total * entry_size
        if table_bytes > file_size - header_size:
            raise ValueError(f"truncated Heroes III LOD entry table: {lod_path}")
        table_end = header_size + table_bytes

        want = entry_name.lower()
        for _ in range(total):
            record = stream.read(entry_size)
            if len(record) != entry_size:
                raise ValueError(f"truncated Heroes III LOD entry table: {lod_path}")
            raw_name = record[:16]
            nul = raw_name.find(b"\0")
            name = (raw_name[:nul] if nul >= 0 else raw_name).decode("ascii", "replace")
            if name.lower() != want:
                continue

            offset, size, _unknown, compressed_size = struct.unpack_from("<IIII", record, 16)
            payload_size = compressed_size if compressed_size else size
            if offset < table_end or offset > file_size or payload_size > file_size - offset:
                raise ValueError(
                    f"invalid bounds for LOD entry {entry_name!r} in {lod_path}: "
                    f"offset={offset}, size={payload_size}, fileSize={file_size}"
                )

            stream.seek(offset)
            raw = stream.read(payload_size)
            if len(raw) != payload_size:
                raise ValueError(f"truncated LOD entry {entry_name!r} in {lod_path}")
            if not compressed_size:
                return raw
            try:
                decoder = zlib.decompressobj()
                unpacked = decoder.decompress(raw, size + 1)
            except zlib.error as exc:
                raise ValueError(f"invalid compressed LOD entry {entry_name!r} in {lod_path}: {exc}") from exc
            if len(unpacked) > size or decoder.unconsumed_tail:
                raise ValueError(
                    f"compressed LOD entry {entry_name!r} exceeds declared size {size} in {lod_path}"
                )
            if not decoder.eof or len(unpacked) != size:
                raise ValueError(
                    f"invalid uncompressed size for LOD entry {entry_name!r} in {lod_path}: "
                    f"expected {size}, got {len(unpacked)}"
                )
            return unpacked

    raise FileNotFoundError(f"{entry_name} not found in {lod_path}")


def printable_score(text: str) -> float:
    if not text:
        return 0.0
    good = 0
    for ch in text:
        if ch in "\r\n\t" or (" " <= ch <= "~") or (0x80 <= ord(ch) <= 0x017F):
            good += 1
    return good / len(text)


def scan_length_prefixed_strings(data: bytes) -> list[ExtractedString]:
    found: dict[tuple[int, str], ExtractedString] = {}
    for off in range(0, len(data) - 8):
        length, = struct.unpack_from("<I", data, off)
        if length < 4 or length > 4096 or off + 4 + length > len(data):
            continue
        raw = data[off + 4 : off + 4 + length]
        if b"\0" in raw:
            continue
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            continue
        if printable_score(text) < 0.92:
            continue
        if not any(ch.isalpha() for ch in text):
            continue
        item = ExtractedString(off + 4, text)
        found[(item.offset, item.text)] = item
    return sorted(found.values(), key=lambda item: item.offset)


def find_required_string(strings: list[ExtractedString], text: str) -> ExtractedString:
    for item in strings:
        if item.text == text:
            return item
    raise ValueError(f"required string not found in campaign payload: {text}")


def first_string_containing(strings: list[ExtractedString], needle: str, after: int = 0) -> ExtractedString:
    for item in strings:
        if item.offset >= after and needle in item.text:
            return item
    raise ValueError(f"string containing {needle!r} not found after offset 0x{after:x}")


def collect_def_names(data: bytes, start: int, end: int) -> list[str]:
    span = data[start:end]
    names = sorted(
        {
            match.group(0).decode("ascii", "replace")
            for match in re.finditer(rb"[A-Za-z0-9_]{3,12}\.def", span, re.IGNORECASE)
        }
    )
    return names


def split_concatenated_gzip_members(data: bytes) -> list[H3CBlock]:
    blocks: list[H3CBlock] = []
    remaining = data
    compressed_offset = 0

    while remaining:
        decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
        payload = decompressor.decompress(remaining)
        payload += decompressor.flush()
        consumed = len(remaining) - len(decompressor.unused_data)
        if consumed <= 0:
            raise ValueError(f"could not advance while splitting gzip member at 0x{compressed_offset:x}")
        blocks.append(
            H3CBlock(
                index=len(blocks),
                compressed_offset=compressed_offset,
                compressed_size=consumed,
                payload=payload,
            )
        )
        if not decompressor.unused_data:
            break
        compressed_offset += consumed
        remaining = decompressor.unused_data

    return blocks


class BinaryReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def tell(self) -> int:
        return self.pos

    def seek(self, pos: int) -> None:
        if pos < 0 or pos > len(self.data):
            raise ValueError(f"seek outside buffer: 0x{pos:x}")
        self.pos = pos

    def skip(self, count: int) -> None:
        self.seek(self.pos + count)

    def read_u8(self) -> int:
        if self.pos >= len(self.data):
            raise ValueError("read past end of buffer")
        value = self.data[self.pos]
        self.pos += 1
        return value

    def read_bool(self) -> bool:
        value = self.read_u8()
        if value not in (0, 1):
            raise ValueError(f"invalid bool byte {value} at 0x{self.pos - 1:x}")
        return value != 0

    def read_u16(self) -> int:
        if self.pos + 2 > len(self.data):
            raise ValueError("read past end of buffer")
        value, = struct.unpack_from("<H", self.data, self.pos)
        self.pos += 2
        return value

    def read_u32(self) -> int:
        if self.pos + 4 > len(self.data):
            raise ValueError("read past end of buffer")
        value, = struct.unpack_from("<I", self.data, self.pos)
        self.pos += 4
        return value

    def read_base_string(self, *, max_length: int = 1_000_000) -> str:
        length = self.read_u32()
        if length > max_length or self.pos + length > len(self.data):
            raise ValueError(f"invalid string length {length} at 0x{self.pos - 4:x}")
        raw = self.data[self.pos : self.pos + length]
        self.pos += length
        return raw.decode("cp1252", "replace")


def parse_h3m_template(reader: BinaryReader) -> dict[str, Any]:
    name = reader.read_base_string(max_length=256)
    if not name.lower().endswith(".def"):
        raise ValueError(f"object template without .def animation at 0x{reader.tell():x}: {name!r}")
    block_mask = list(reader.data[reader.pos : reader.pos + 6])
    reader.skip(6)
    visit_mask = list(reader.data[reader.pos : reader.pos + 6])
    reader.skip(6)
    reader.skip(2)
    terrain_mask = reader.read_u16()
    object_id = reader.read_u32()
    subtype = reader.read_u32()
    template_type = reader.read_u8()
    print_priority = reader.read_u8()
    reader.skip(16)
    return {
        "animation": name,
        "blockMask": block_mask,
        "visitMask": visit_mask,
        "terrainMask": terrain_mask,
        "objectId": object_id,
        "subtype": subtype,
        "templateType": template_type,
        "printPriority": print_priority,
    }


def locate_h3m_terrain_and_objects(data: bytes, size: int, layers: int) -> tuple[int, int, int, list[dict[str, Any]]]:
    terrain_bytes = size * size * layers * 7
    candidates: list[tuple[int, int, int, list[dict[str, Any]]]] = []
    max_scan = min(len(data) - terrain_bytes - 8, 0x8000)
    for terrain_start in range(0x20, max_scan):
        template_offset = terrain_start + terrain_bytes
        reader = BinaryReader(data)
        try:
            reader.seek(template_offset)
            template_count = reader.read_u32()
            if not (1 <= template_count <= 4000):
                continue
            templates = [parse_h3m_template(reader) for _ in range(template_count)]
            object_table_offset = reader.tell()
            object_count = reader.read_u32()
            if not (1 <= object_count <= 100000):
                continue
            x = reader.read_u8()
            y = reader.read_u8()
            z = reader.read_u8()
            def_index = reader.read_u32()
            if x > size + 8 or y > size + 8 or z >= layers or def_index >= template_count:
                continue
            candidates.append((terrain_start, object_table_offset, object_count, templates))
        except (UnicodeDecodeError, ValueError, struct.error):
            continue
    if len(candidates) != 1:
        raise ValueError(f"expected one H3M terrain/template alignment, found {len(candidates)}")
    return candidates[0]


def histogram(values: list[int]) -> dict[str, int]:
    result: dict[str, int] = {}
    for value in values:
        key = str(value)
        result[key] = result.get(key, 0) + 1
    return dict(sorted(result.items(), key=lambda item: int(item[0])))


def summarize_h3m_shape(data: bytes) -> H3MShapeSummary:
    reader = BinaryReader(data)
    version = reader.read_u32()
    reader.read_bool()
    size = reader.read_u32()
    has_underground = reader.read_bool()
    title = reader.read_base_string(max_length=256)
    description = reader.read_base_string(max_length=4096)
    difficulty = reader.read_u8()
    layers = 2 if has_underground else 1

    terrain_start, object_table_offset, object_count, templates = locate_h3m_terrain_and_objects(
        data,
        size,
        layers,
    )
    terrain_bytes = size * size * layers * 7
    template_table_offset = terrain_start + terrain_bytes

    terrain_histograms: list[dict[str, int]] = []
    road_histograms: list[dict[str, int]] = []
    river_histograms: list[dict[str, int]] = []
    tiles_per_layer = size * size
    for layer in range(layers):
        terrain_values: list[int] = []
        road_values: list[int] = []
        river_values: list[int] = []
        layer_start = terrain_start + layer * tiles_per_layer * 7
        for tile_index in range(tiles_per_layer):
            pos = layer_start + tile_index * 7
            terrain_values.append(data[pos])
            river_values.append(data[pos + 2] & 0x07)
            road_values.append(data[pos + 4] & 0x07)
        terrain_histograms.append(histogram(terrain_values))
        road_histograms.append(histogram(road_values))
        river_histograms.append(histogram(river_values))

    return H3MShapeSummary(
        version=version,
        size=size,
        layers=layers,
        title=title,
        description=description,
        difficulty=difficulty,
        terrain_start=terrain_start,
        terrain_bytes=terrain_bytes,
        template_table_offset=template_table_offset,
        object_table_offset=object_table_offset,
        template_count=len(templates),
        object_count=object_count,
        first_template_names=[item["animation"] for item in templates[:20]],
        terrain_histograms=terrain_histograms,
        road_histograms=road_histograms,
        river_histograms=river_histograms,
    )


def h3m_summary_to_json(summary: H3MShapeSummary) -> dict[str, Any]:
    return {
        "version": summary.version,
        "size": summary.size,
        "layers": summary.layers,
        "title": summary.title,
        "description": summary.description,
        "difficulty": summary.difficulty,
        "terrainStart": f"0x{summary.terrain_start:x}",
        "terrainBytes": summary.terrain_bytes,
        "templateTableOffset": f"0x{summary.template_table_offset:x}",
        "objectTableOffset": f"0x{summary.object_table_offset:x}",
        "templateCount": summary.template_count,
        "objectCount": summary.object_count,
        "firstTemplateNames": summary.first_template_names,
        "terrainHistogramsByLayer": summary.terrain_histograms,
        "roadHistogramsByLayer": summary.road_histograms,
        "riverHistogramsByLayer": summary.river_histograms,
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("unterminated Olden varint")
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            return value, offset
        shift += 7
        if shift > 35:
            raise ValueError("Olden varint is unexpectedly large")


def write_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("cannot encode a negative Olden varint")
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def read_olden_map_container(path: Path) -> OldenMapContainer:
    raw = gzip.decompress(path.read_bytes())
    if len(raw) < 43 or raw[0:1] != b" ":
        raise ValueError(f"not an expected Olden map container: {path}")

    offset = 1 + 32
    version_length = raw[offset]
    offset += 1
    version = raw[offset : offset + version_length].decode("ascii")
    offset += version_length
    prefix_suffix = raw[offset : offset + 2]
    offset += 2

    chunks: list[dict[str, Any]] = []
    while offset < len(raw):
        chunk_length, offset = read_varint(raw, offset)
        chunk_bytes = raw[offset : offset + chunk_length]
        if len(chunk_bytes) != chunk_length:
            raise ValueError(f"truncated Olden map JSON chunk in {path}")
        chunks.append(json.loads(chunk_bytes))
        offset += chunk_length

    if len(chunks) < 2:
        raise ValueError(f"Olden map has too few JSON chunks: {path}")
    return OldenMapContainer(version=version, prefix_suffix=prefix_suffix, chunks=chunks)


def audit_olden_map_arrays() -> dict[str, Any]:
    paths = sorted(OLDEN_MAPS_DIR.glob("*.map")) + sorted(OLDEN_STORY_MAPS_DIR.glob("*.map"))
    paths = [path for path in paths if path.stem != PLAYABLE_MAP_SID]
    if not paths:
        raise FileNotFoundError("no Olden .map files found for MapData array audit")

    rows: list[dict[str, Any]] = []
    for path in paths:
        container = read_olden_map_container(path)
        map_data = container.chunks[1]
        size_x = map_data.get("sizeX_")
        size_z = map_data.get("sizeZ_")
        if not isinstance(size_x, int) or not isinstance(size_z, int):
            raise ValueError(f"Olden map missing integer sizeX_/sizeZ_: {path}")
        expected = size_x * size_z
        arrays: dict[str, int] = {}
        for key in ("tilesMap", "levelsMap", "climbsMap", "roadsMap", "waterMap"):
            value = map_data.get(key)
            if not isinstance(value, list):
                raise ValueError(f"Olden map missing list {key}: {path}")
            arrays[key] = len(value)
        rows.append(
            {
                "map": str(path),
                "sizeX": size_x,
                "sizeZ": size_z,
                "expectedFlatArrayLength": expected,
                "arrayLengths": arrays,
                "allArraysAreSizeXTimesSizeZ": all(length == expected for length in arrays.values()),
            }
        )

    non_flat = [row for row in rows if not row["allArraysAreSizeXTimesSizeZ"]]
    return {
        "auditedMapCount": len(rows),
        "nonFlatMapCount": len(non_flat),
        "evidence": rows,
    }


def write_olden_map_container(path: Path, container: OldenMapContainer, hash_sum: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{32}", hash_sum):
        raise ValueError(f"not a 32-character lowercase md5 hash: {hash_sum}")

    raw = bytearray()
    raw.extend(b" ")
    raw.extend(hash_sum.encode("ascii"))
    raw.append(len(container.version))
    raw.extend(container.version.encode("ascii"))
    raw.extend(container.prefix_suffix)
    for chunk in container.chunks:
        # sort_keys keeps gzip bytes stable across deepcopy vs parse order differences.
        chunk_bytes = json.dumps(
            chunk, separators=(",", ":"), ensure_ascii=False, sort_keys=True
        ).encode("utf-8")
        raw.extend(write_varint(len(chunk_bytes)))
        raw.extend(chunk_bytes)

    path.parent.mkdir(parents=True, exist_ok=True)
    # mtime=0 keeps .map bytes stable across regenerations (gzip header otherwise varies).
    path.write_bytes(gzip.compress(bytes(raw), compresslevel=9, mtime=0))


def make_homecoming_script(goal_entity: str, intro_text: str) -> dict[str, Any]:
    return {
        "counters": [
            {"sid": "homecoming_started", "value": 0},
            {"sid": "homecoming_terraneus_captured", "value": 0},
        ],
        "quests": [
            {
                "sid": "homecoming_intro",
                "hidden": True,
                "main": False,
                "activeOnStart": True,
                "comment": "first-turn Homecoming briefing",
                "sharing": "Clone",
                "name": HOMECOMING_TITLE_SID,
                "desc": "",
                "subQuests": [
                    {
                        "sid": "homecoming_intro_start",
                        "activeOnStart": True,
                        "hidden": False,
                        "name": "",
                        "desc": "",
                        "comment": "",
                        "triggers": [
                            {
                                "comment": "",
                                "repeat": False,
                                "conditions": [
                                    {"comment": "", "c": "StartTurn", "p": ["1", "1"], "counter": 1}
                                ],
                                "actions": [
                                    {"comment": "", "a": "Print", "p": [intro_text]},
                                    {
                                        "comment": "",
                                        "a": "SetQuestMarker",
                                        "p": [goal_entity, "effects/global_map/quest_mark_gold_01"],
                                    },
                                    {"comment": "", "a": "CounterSet", "p": ["homecoming_started", "1"]},
                                ],
                                "conditionsLogic": "And",
                            }
                        ],
                    }
                ],
                "subQuestGroups": [],
            },
            {
                "sid": "homecoming_main_goal",
                "hidden": False,
                "main": True,
                "activeOnStart": True,
                "comment": "Homecoming proxy win condition",
                "sharing": "Clone",
                "name": HOMECOMING_TITLE_SID,
                "desc": HOMECOMING_CAPTURE_TERRANEUS_SID,
                "subQuests": [
                    {
                        "sid": "capture_terraneus_proxy",
                        "activeOnStart": True,
                        "hidden": False,
                        "name": HOMECOMING_CAPTURE_TERRANEUS_SID,
                        "desc": "",
                        "comment": "",
                        "triggers": [
                            {
                                "comment": "",
                                "repeat": False,
                                "conditions": [
                                    {"comment": "", "c": "ObjectCaptureEntity", "p": [goal_entity], "counter": 1}
                                ],
                                "actions": [
                                    {
                                        "comment": "",
                                        "a": "CounterSet",
                                        "p": ["homecoming_terraneus_captured", "1"],
                                    },
                                    {"comment": "", "a": "SetActiveQuestMarker", "p": [goal_entity, "false"]},
                                    {"comment": "", "a": "CurrentSubQuestDone", "p": []},
                                    {"comment": "", "a": "GameVictory", "p": []},
                                ],
                                "conditionsLogic": "And",
                            }
                        ],
                    }
                ],
                "subQuestGroups": [],
            },
        ],
        "_pocNote": (
            "Playable shell script. The Terraneus target is an explicit proxy "
            "retagged from an existing neutral Olden city, not decoded from Good-1a.h3m."
        ),
    }


def make_embedded_homecoming_script(goal_entity: str, intro_text: str) -> dict[str, Any]:
    script = make_homecoming_script(goal_entity, intro_text)
    return {
        "comment": "Homecoming playable shell script. Generated artifact is schema/build validated; direct synthetic StartInfo launch is runtime-blocked before map-world readiness.",
        "aiRolesId": "",
        "counters": [
            {
                "comment": "",
                "sid": counter["sid"],
                "sharing": "Clone",
                "value": counter["value"],
                "minValue": -2147483648,
                "maxValue": 2147483647,
            }
            for counter in script["counters"]
        ],
        "interruptions": [],
        "quests": script["quests"],
    }


def retag_terraneus_proxy(map_data: dict[str, Any], goal_entity: str) -> dict[str, Any]:
    props = map_data["objectsProperties"]
    found_entity = False
    for entity in props.get("propEntities", []):
        if entity.get("id") == TERRANEUS_PROXY_TEMPLATE_ID:
            entity["sid"] = goal_entity
            found_entity = True
            break
    if not found_entity:
        raise ValueError("template map no longer has the expected Terraneus entity proxy")

    found_city = False
    for city in props.get("propCities", []):
        if city.get("id") == TERRANEUS_PROXY_TEMPLATE_ID:
            city["customCityName"] = "homecoming_city_name_terraneus"
            found_city = True
            break
    if not found_city:
        raise ValueError("template map no longer has the expected neutral city proxy")

    return map_data


def generate_playable_shell(
    *,
    map_sid: str,
    homecoming_title: str,
    objective: str,
    intro_text: str,
    goal_entity: str,
) -> dict[str, Any]:
    if not PLAYABLE_TEMPLATE_MAP.exists():
        raise FileNotFoundError(f"expected Olden template map at {PLAYABLE_TEMPLATE_MAP}")

    container = read_olden_map_container(PLAYABLE_TEMPLATE_MAP)
    chunks = json.loads(json.dumps(container.chunks, ensure_ascii=False))
    meta = chunks[0]
    map_data = chunks[1]

    new_hash = hashlib.md5(map_sid.encode("utf-8")).hexdigest()
    meta.update(
        {
            "title": HOMECOMING_TITLE_SID,
            "template": "",
            "desc": HOMECOMING_DESCRIPTION_SID,
            "displayWinCondition": HOMECOMING_DESCRIPTION_SID,
            "hashSum": new_hash,
            "nameFromLocalization": True,
            "descFromLocalization": True,
            "isScenario": True,
        }
    )
    map_data.update(
        {
            "fileMapName": map_sid,
            "mapName": HOMECOMING_TITLE_SID,
            "mapNameFromLoc": True,
            "mapDesc": HOMECOMING_DESCRIPTION_SID,
            "mapDescFromLoc": True,
        }
    )
    scenario_menu_shell.apply_menu_shell(meta, map_data, map_sid)
    retag_terraneus_proxy(map_data, goal_entity)

    sidecar_script = make_homecoming_script(goal_entity, intro_text)
    chunks[2] = {"dialogs": {"lines": []}, "quests": {"quests": []}}
    chunks[3] = make_embedded_homecoming_script(goal_entity, intro_text)

    out_maps = PLAYABLE_DIR / "maps"
    out_map = out_maps / f"{map_sid}.map"
    out_json = out_maps / f"{map_sid}.json"
    write_olden_map_container(
        out_map,
        OldenMapContainer(
            version=container.version,
            prefix_suffix=container.prefix_suffix,
            chunks=chunks,
        ),
        new_hash,
    )
    write_json(out_json, sidecar_script)

    manifest = {
        "status": "generated_schema_validated_runtime_launch_blocked",
        "mapSid": map_sid,
        "templateMap": str(PLAYABLE_TEMPLATE_MAP),
        "templateSubstitution": {
            "reason": "Good-1a.h3m terrain and placed objects are not decoded yet.",
            "sourceObjectId": TERRANEUS_PROXY_TEMPLATE_ID,
            "sourceObjectWas": "Thirst_for_Power neutral city tagged undead_city",
            "newEntitySid": goal_entity,
            "newCityName": "Terraneus",
        },
        "outputs": {
            "map": str(out_map),
            "script": str(out_json),
        },
        "manualInstallTargets": {
            "map": str(OLDEN_MAPS_DIR / f"{map_sid}.map"),
            "script": str(OLDEN_MAPS_DIR / f"{map_sid}.json"),
        },
        "knownBlocker": (
            "The generated shell is map-container and quest-schema validated, but direct synthetic "
            "StartInfo.NewMap launch is runtime-blocked before map-world readiness. Faithful Homecoming "
            "geometry, object placement, and event ownership remain blocked on a real H3M decoder; "
            "playable launch now needs the native QuickStart/scenario-map route instead of more scalar StartInfo patches."
        ),
    }
    write_json(PLAYABLE_DIR / "install_manifest.json", manifest)
    return manifest

def read_core_quickstart(core_zip: Path) -> dict[str, Any]:
    if not core_zip.exists():
        raise FileNotFoundError(f"expected Olden Core.zip at {core_zip}")
    with zipfile.ZipFile(core_zip, "r") as archive:
        try:
            payload = archive.read("DB/quickStart.json")
        except KeyError as ex:
            raise ValueError("Core.zip does not contain DB/quickStart.json") from ex
    return json.loads(payload.decode("utf-8-sig"))


def generate_quickstart_catalog_overlay(map_sid: str) -> dict[str, Any]:
    quickstart = read_core_quickstart(OLDEN_CORE_ZIP)
    scenarios = quickstart.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise ValueError("Core quickStart.json scenarios list is missing or empty")
    if "Thirst_for_Power" not in scenarios:
        raise ValueError("Core quickStart.json no longer has the expected Thirst_for_Power scenario anchor")
    if map_sid not in scenarios:
        scenarios.append(map_sid)

    out_dir = PLAYABLE_DIR / "core_overlay"
    out_path = out_dir / "quickStart.json"
    write_json(out_path, quickstart)
    manifest = {
        "status": "generated_catalog_overlay_uninstalled",
        "coreSource": str(OLDEN_CORE_ZIP),
        "coreEntry": "DB/quickStart.json",
        "mapSid": map_sid,
        "scenarioAnchor": "Thirst_for_Power",
        "output": str(out_path),
        "contract": "Homecoming map must be present in QuickStartConfig.scenarios before runtime scenario selection can expose it.",
    }
    write_json(out_dir / "quickstart_catalog_overlay_manifest.json", manifest)
    return manifest

def main() -> int:
    if not LOD_PATH.exists():
        raise FileNotFoundError(f"expected local HoMM3 LOD at {LOD_PATH}")

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    OLDEN_DIR.mkdir(parents=True, exist_ok=True)
    PLAYABLE_DIR.mkdir(parents=True, exist_ok=True)

    compressed_campaign = read_lod_entry(LOD_PATH, ENTRY_NAME)
    h3c_blocks = split_concatenated_gzip_members(compressed_campaign)
    campaign = b"".join(block.payload for block in h3c_blocks)
    if len(h3c_blocks) < 2:
        raise ValueError("campaign did not contain any embedded H3M map blocks")
    homecoming_h3m = h3c_blocks[1].payload
    homecoming_shape = summarize_h3m_shape(homecoming_h3m)
    (SOURCE_DIR / ENTRY_NAME).write_bytes(compressed_campaign)
    (SOURCE_DIR / "Good1.decompressed.bin").write_bytes(campaign)
    blocks_dir = SOURCE_DIR / "h3c_blocks"
    blocks_dir.mkdir(parents=True, exist_ok=True)
    for block in h3c_blocks:
        suffix = "campaign_header.bin" if block.index == 0 else f"map_{block.index:02d}.h3m"
        (blocks_dir / suffix).write_bytes(block.payload)
    (blocks_dir / "Good-1a.h3m").write_bytes(homecoming_h3m)

    strings = scan_length_prefixed_strings(campaign)
    campaign_title = find_required_string(strings, "Long Live the Queen")
    campaign_description = strings[strings.index(campaign_title) + 1]
    map_name = find_required_string(strings, "Good-1a.h3m")
    homecoming = find_required_string(strings, "Homecoming")
    guardian_angels = find_required_string(strings, "Guardian Angels")
    objective = first_string_containing(strings, "Terraneus", after=homecoming.offset)
    first_briefing = first_string_containing(strings, "Queen Catherine has departed", after=map_name.offset)
    second_briefing = first_string_containing(strings, "Our initial landing", after=first_briefing.offset)

    first_map_strings = [
        item for item in strings if homecoming.offset <= item.offset < guardian_angels.offset
    ]
    likely_event_strings = [
        item
        for item in first_map_strings
        if ".def" not in item.text.lower()
        and len(item.text) >= 10
        and item.text not in {"Homecoming", objective.text}
    ]
    sprite_defs = collect_def_names(campaign, homecoming.offset, guardian_angels.offset)

    source_summary = {
        "source": {
            "lod": str(LOD_PATH),
            "entry": ENTRY_NAME,
            "compressedBytes": len(compressed_campaign),
            "decompressedBytes": len(campaign),
        },
        "campaign": {
            "title": campaign_title.text,
            "description": campaign_description.text,
        },
        "firstMission": {
            "h3mName": map_name.text,
            "title": homecoming.text,
            "objectiveText": objective.text,
            "briefingTexts": [first_briefing.text, second_briefing.text],
            "decodedH3m": h3m_summary_to_json(homecoming_shape),
            "homecomingOffset": f"0x{homecoming.offset:x}",
            "nextMissionTitleOffset": f"0x{guardian_angels.offset:x}",
            "extractedLengthPrefixedStringCount": len(first_map_strings),
            "likelyEventStringCount": len(likely_event_strings),
            "spriteDefCount": len(sprite_defs),
        },
        "likelyEventStrings": [
            {"offset": f"0x{item.offset:x}", "text": item.text} for item in likely_event_strings
        ],
        "spriteDefinitions": sprite_defs,
    }
    write_json(OUT_ROOT / "source_summary.json", source_summary)
    write_json(OUT_ROOT / "h3c_block_summary.json", {
        "source": str(LOD_PATH),
        "entry": ENTRY_NAME,
        "blockCount": len(h3c_blocks),
        "blocks": [
            {
                "index": block.index,
                "compressedOffset": f"0x{block.compressed_offset:x}",
                "compressedSize": block.compressed_size,
                "payloadBytes": len(block.payload),
                "kind": "campaign_header" if block.index == 0 else "h3m_map",
                "h3m": h3m_summary_to_json(summarize_h3m_shape(block.payload)) if block.index > 0 else None,
            }
            for block in h3c_blocks
        ],
    })

    mission_id = "homm3_roe_castle_homecoming"
    map_sid = PLAYABLE_MAP_SID
    title_sid = HOMECOMING_TITLE_SID
    description_sid = HOMECOMING_DESCRIPTION_SID
    goal_entity = "homecoming_goal_terraneus_city"
    intro_text = (
        first_briefing.text
        + " "
        + second_briefing.text
        + " Objective: "
        + objective.text
    )

    story_node = {
        "sid": "homm3_roe_castle_node_homecoming",
        "state": "Activated",
        "posX": -285,
        "posY": -75,
        "posZ": 0,
        "interactionActions": [
            {"type": "OpenMissionsPrologue", "values": [mission_id]},
        ],
        "onDoneActions": [
            {"type": "SetCounterValue", "values": [f"{mission_id}_completed", "1"]},
            {"type": "changeNodeState", "values": ["homm3_roe_castle_node_homecoming", "Completed"]},
        ],
        "_pocNote": "Generated proof only; not inserted into Core.zip and not runtime validated.",
    }

    mission_config = {
        "array": [
            {
                "id": mission_id,
                "requiredHeroesCount": 1,
                "bannerSid": "homm3_castle_faction_banner",
                "fixedHeroesSet": ["homm3_castle_hero_7"],
                "disableFactionLaws": False,
                "disableMagicGuild": False,
                "idSidesWithoutTimer": [0],
                "difficultiesParameters": [
                    {
                        "index": index,
                        "nameSid": f"homm3_roe_castle_difficulty_{index}_name",
                        "descriptionSid": f"homm3_roe_castle_difficulty_{index}_description",
                        "isAvailable": index < 4,
                    }
                    for index in range(5)
                ],
                "importanceType": "Main",
                "variants": [
                    {
                        "titleSid": title_sid,
                        "descriptionSid": description_sid,
                        "mapSid": map_sid,
                        "sides": [
                            {"type": "Player", "fractionSid": "homm3_castle", "spawns": [1]},
                            {"type": "AI", "fractionSid": "homm3_dungeon", "spawns": [2]},
                        ],
                        "difficulties": [
                            {
                                "index": index,
                                "economic": {
                                    "playerStartResources": {
                                        "gold": 0,
                                        "wood": 0,
                                        "ore": 0,
                                        "gemstones": 0,
                                        "crystals": 0,
                                        "mercury": 0,
                                        "alchemicalDust": 0,
                                    },
                                    "aiStartResources": {
                                        "gold": 7500,
                                        "wood": 10,
                                        "ore": 10,
                                        "gemstones": 4,
                                        "crystals": 4,
                                        "mercury": 4,
                                        "alchemicalDust": 10,
                                    },
                                },
                                "ai": {
                                    "script": "homm3_roe_castle_homecoming_poc",
                                    "battleScript": "normal",
                                    "buildTag": ["supereasy", "easy", "normal", "hard", "heroic"][index],
                                    "resourceAddPercent": 0.5,
                                    "tempStacksMultiplier": 0.5,
                                    "valuesVsMobsMultiplier": 1.0,
                                    "blockAreaByEnemyMultiplier": 1.0,
                                    "buildingColdown": max(0, 2 - min(index, 2)),
                                },
                                "neutralPowerMultiplier": [0.4, 0.6, 0.8, 1.0, 1.15][index],
                                "guardPowerMultiplier": [0.4, 0.6, 0.8, 1.0, 1.15][index],
                                "neutralExpMultiplier": 2.25,
                            }
                            for index in range(5)
                        ],
                    }
                ],
                "_pocNote": "Mission shell only. The mapSid is not backed by a decoded Olden .map yet.",
            }
        ]
    }

    quest_script = {
        "counters": [
            {"sid": "homecoming_started", "value": 0, "comment": "PoC intro gate."},
            {
                "sid": "homecoming_terraneus_captured",
                "value": 0,
                "comment": "Set when the unresolved Terraneus entity is captured.",
            },
        ],
        "quests": [
            {
                "sid": "homecoming_intro",
                "hidden": True,
                "activeOnStart": True,
                "sharing": "Clone",
                "name": "homecoming_intro",
                "subQuests": [
                    {
                        "sid": "start_dialog",
                        "activeOnStart": True,
                        "triggers": [
                            {
                                "conditions": [{"c": "StartTurn", "p": ["1", "1"]}],
                                "actions": [
                                    {"a": "Dialog", "p": ["homm3_roe_castle_homecoming_intro"]},
                                    {"a": "CounterSet", "p": ["homecoming_started", "1"]},
                                ],
                            }
                        ],
                    }
                ],
            },
            {
                "sid": "homecoming_main_goal",
                "main": True,
                "activeOnStart": True,
                "sharing": "Clone",
                "name": title_sid,
                "subQuests": [
                    {
                        "sid": "capture_terraneus",
                        "activeOnStart": True,
                        "name": "homm3_roe_castle_homecoming_capture_terraneus",
                        "triggers": [
                            {
                                "conditions": [{"c": "ObjectCaptureEntity", "p": [goal_entity]}],
                                "actions": [
                                    {"a": "CounterSet", "p": ["homecoming_terraneus_captured", "1"]},
                                    {"a": "CurrentSubQuestDone"},
                                    {"a": "ChangeCampaignOneStep", "p": ["true"]},
                                    {"a": "GameVictory"},
                                ],
                            }
                        ],
                    }
                ],
            },
        ],
        "_pocUnresolved": [
            {
                "sid": goal_entity,
                "reason": "H3M placed-object geometry is not decoded yet, so the Terraneus town entity cannot be emitted into an Olden .map.",
            }
        ],
    }

    lang_rows = {
        "array": [
            {"sid": title_sid, "text": homecoming.text},
            {"sid": description_sid, "text": objective.text},
            {
                "sid": HOMECOMING_INTRO_SID,
                "text": first_briefing.text + "\n\n" + second_briefing.text,
            },
            {
                "sid": HOMECOMING_CAPTURE_TERRANEUS_SID,
                "text": "Locate and capture Terraneus.",
            },
        ],
        "_pocNote": "Language rows are standalone proof artifacts, not merged into Core.zip.",
    }

    olden_map_array_audit = audit_olden_map_arrays()
    write_json(OUT_ROOT / "olden_map_array_audit.json", olden_map_array_audit)

    map_plan = {
        "mapSid": map_sid,
        "sourceH3m": map_name.text,
        "status": "not_generated",
        "reason": "Full H3M tile/object decoding is required before a valid Olden .map can be generated.",
        "knownFromSource": {
            "title": homecoming.text,
            "objective": objective.text,
            "candidateGoalEntity": goal_entity,
            "mapStringSpan": {
                "start": f"0x{homecoming.offset:x}",
                "endExclusive": f"0x{guardian_angels.offset:x}",
            },
        },
        "requiredNextDecoderWork": [
            "Decode full H3M object instance payloads after the now-split map pieces.",
            "Decode placed objects and identify the town named Terraneus.",
            "Map H3 object templates to Olden object SIDs or explicit unsupported records.",
            "Resolve the two-layer Homecoming map shape against Olden's one-layer MapData model.",
        ],
    }

    blockers = {
        "provenPortableNow": [
            "Campaign title and description extraction from Good1.h3c.",
            "Exact concatenated gzip block split for campaign header and embedded H3M maps.",
            "Homecoming H3M header and terrain/object-template boundary decode.",
            "First mission title/objective/briefing extraction.",
            "Olden StoryHub node skeleton.",
            "Olden mission config skeleton using mapSid and Castle faction SIDs.",
            "Olden QuestScript skeleton for first-turn dialog and Terraneus capture victory condition.",
        ],
        "needsSubstitutionOrNewMapping": [
            "H3 event strings without decoded trigger ownership must become dialogs/guides only after object linkage is decoded.",
            "Terraneus capture can map to ObjectCaptureEntity, but the entity id is unresolved until map objects are decoded.",
            "H3 terrain, roads, rivers, and object footprints need an explicit H3 square-tile to Olden node/coordinate transform.",
            "H3 map object defs need explicit mapping to Olden object SIDs.",
            "The playable shell intentionally substitutes a Thirst_for_Power neutral city for Terraneus.",
        ],
        "impossibleInThisFirstPass": [
            "Generating a faithful Olden .map for Homecoming while preserving the two-layer H3 map shape.",
            "Preserving exact H3 geometry/pathing without a validated Olden coordinate and footprint transform.",
            "Porting all event triggers; only event text has been extracted.",
            "Verifying the mission in Olden runtime.",
        ],
        "majorBlockerFound": {
            "feature": "Two-layer H3M adventure maps.",
            "homecomingEvidence": h3m_summary_to_json(homecoming_shape),
            "oldenEvidence": (
                "Olden MapData exposes sizeX_/sizeZ_ plus one-dimensional tilesMap, levelsMap, "
                "climbsMap, roadsMap, and waterMap arrays. Official .map files inspected have "
                "array lengths exactly sizeX_ * sizeZ_, not sizeX_ * sizeZ_ * layers."
            ),
            "oldenMapArrayAudit": {
                "auditedMapCount": olden_map_array_audit["auditedMapCount"],
                "nonFlatMapCount": olden_map_array_audit["nonFlatMapCount"],
                "artifact": str(OUT_ROOT / "olden_map_array_audit.json"),
            },
            "whyItBlocksExactShape": (
                "Homecoming is a 72x72 map with surface and underground layers. Flattening, "
                "side-by-side expansion, or portal-only substitution would change map shape."
            ),
        },
        "silentFallbacksUsed": False,
    }

    playable_manifest = generate_playable_shell(
        map_sid=map_sid,
        homecoming_title=homecoming.text,
        objective=objective.text,
        intro_text=intro_text,
        goal_entity=goal_entity,
    )
    quickstart_catalog_overlay = generate_quickstart_catalog_overlay(map_sid)

    write_json(OLDEN_DIR / "storyHub.node.json", story_node)
    write_json(OLDEN_DIR / "mission.config.json", mission_config)
    write_json(OLDEN_DIR / "quest_script.json", quest_script)
    write_json(OLDEN_DIR / "lang_rows.json", lang_rows)
    write_json(OLDEN_DIR / "map_plan.json", map_plan)
    write_json(OUT_ROOT / "blockers.json", blockers)

    report = f"""# Homecoming Campaign Port PoC

Status: generated proof artifact. This tool emits a Core.zip quickStart catalog overlay, but does not modify the installed Core.zip directly. Runtime deployment, if performed, is tracked separately in `playable_shell/deployment_status.json`.

## Source Evidence

- Source archive: `{LOD_PATH}`
- Extracted campaign entry: `{ENTRY_NAME}`
- Campaign: `{campaign_title.text}`
- First H3 map piece: `{map_name.text}`
- First mission title: `{homecoming.text}`
- Objective: {objective.text}
- Decoded H3M shape: {homecoming_shape.size}x{homecoming_shape.size}, layers={homecoming_shape.layers}
- H3M terrain starts at `0x{homecoming_shape.terrain_start:x}`; object templates start at `0x{homecoming_shape.template_table_offset:x}`.
- H3M object templates: {homecoming_shape.template_count}; object instances: {homecoming_shape.object_count}

## Generated Olden Skeleton

- `olden_skeleton/storyHub.node.json`
- `olden_skeleton/mission.config.json`
- `olden_skeleton/quest_script.json`
- `olden_skeleton/lang_rows.json`
- `olden_skeleton/map_plan.json`

The generated quest script maps the proven objective text to an Olden
`ObjectCaptureEntity` victory trigger for `{goal_entity}`. That entity is
intentionally unresolved until the H3M placed-object decoder can identify and
place Terraneus in an Olden `.map`.

## First-Pass Problems Found

1. The campaign archive is usable, but `Good1.h3c` must be split into exact H3M
   map pieces. This is now implemented with concatenated gzip member splitting.
2. Full H3M placed-object payload decoding is required to bind strings to triggers.
   The PoC can see event/riddle/rumor text but not which object owns each event.
3. A faithful Olden `.map` was not generated. This pass emits `map_plan.json`
   plus a separate playable shell built from an official Olden scenario map.
4. Geometry is not a mechanical copy: H3 square tiles and Olden map nodes/object
   positions need one explicit coordinate and footprint transform. The PoC no
   longer assumes the Olden adventure map is hex-based; local static evidence
   shows rectangular `sizeX_`/`sizeZ_` map arrays and flat node indices.
5. Homecoming is a two-layer H3M map. Olden `MapData` currently appears to have
   one tile array per map, with official maps using `len(array) == sizeX_ * sizeZ_`.
   Preserving Homecoming's map shape therefore needs an Olden multi-layer map
   feature or a proven native representation we have not found.
   Audit artifact: `olden_map_array_audit.json` ({olden_map_array_audit["auditedMapCount"]}
   maps inspected, {olden_map_array_audit["nonFlatMapCount"]} non-flat).
6. The victory condition is structurally portable, but not complete: Terraneus
   needs a decoded object entity id before the trigger can run.

## Playable Shell Attempt

- Generated map: `{playable_manifest["outputs"]["map"]}`
- Generated script: `{playable_manifest["outputs"]["script"]}`
- QuickStart catalog overlay: `{quickstart_catalog_overlay["output"]}`
- Template: `{PLAYABLE_TEMPLATE_MAP}`

This pass creates a load-shaped standalone Olden scenario by cloning an official
scenario map and retagging its existing neutral city object id
`{TERRANEUS_PROXY_TEMPLATE_ID}` as `{goal_entity}` / `Terraneus`. The first-turn
briefing still uses a direct `Print` payload; quest labels and scenario
metadata use generated `customMaps` localization rows that must be installed
into Core.zip before runtime. The win trigger is a real `ObjectCaptureEntity`
condition against that retagged proxy.

This is an intentional substitution, not a faithful Homecoming map. A real H3M
object decoder is still needed for Terraneus and event ownership, but the
current stop condition is stricter: preserving Homecoming's exact shape requires
an Olden multi-layer adventure map representation or an equivalent native
feature we have not found.

## Useful Extracted Counts

- Length-prefixed strings in first mission span: {len(first_map_strings)}
- Likely event strings in first mission span: {len(likely_event_strings)}
- Sprite `.def` names in first mission span: {len(sprite_defs)}
"""
    (OUT_ROOT / "PORT_REPORT.md").write_text(report, encoding="utf-8")

    print(f"wrote {OUT_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
