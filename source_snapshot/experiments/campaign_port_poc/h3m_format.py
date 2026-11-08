"""Neutral H3M binary parser primitives shared by campaign-port probes."""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any


H3M_VERSION_ROE = 14
H3M_VERSION_AB = 21
H3M_VERSION_SOD = 28
H3M_VERSION_HOTA = 32
H3M_HOTA_FORMAT_LEVEL_1_8 = 9
H3M_HOTA_1_8_HERO_COUNT = 215
SUPPORTED_H3M_VERSIONS = frozenset(
    {H3M_VERSION_ROE, H3M_VERSION_AB, H3M_VERSION_SOD, H3M_VERSION_HOTA}
)
SUPPORTED_H3M_SIZES = frozenset({36, 72, 108, 144, 252})

# VCMI EVictoryConditionType / ELossConditionType (MapFormatH3M).
VICTORY_ARTIFACT = 0
VICTORY_GATHERTROOP = 1
VICTORY_GATHERRESOURCE = 2
VICTORY_BUILDCITY = 3
VICTORY_BUILDGRAIL = 4
VICTORY_BEATHERO = 5
VICTORY_CAPTURECITY = 6
VICTORY_BEATMONSTER = 7
VICTORY_TAKEDWELLINGS = 8
VICTORY_TAKEMINES = 9
VICTORY_TRANSPORTITEM = 10
VICTORY_DEFEAT_ALL_MONSTERS = 11
VICTORY_SURVIVE_TIME = 12
VICTORY_WINSTANDARD = 255

LOSS_CASTLE = 0
LOSS_HERO = 1
LOSS_TIMEEXPIRES = 2
LOSS_STANDARD = 255

VICTORY_CONDITION_NAMES: dict[int, str] = {
    VICTORY_ARTIFACT: "ARTIFACT",
    VICTORY_GATHERTROOP: "GATHERTROOP",
    VICTORY_GATHERRESOURCE: "GATHERRESOURCE",
    VICTORY_BUILDCITY: "BUILDCITY",
    VICTORY_BUILDGRAIL: "BUILDGRAIL",
    VICTORY_BEATHERO: "BEATHERO",
    VICTORY_CAPTURECITY: "CAPTURECITY",
    VICTORY_BEATMONSTER: "BEATMONSTER",
    VICTORY_TAKEDWELLINGS: "TAKEDWELLINGS",
    VICTORY_TAKEMINES: "TAKEMINES",
    VICTORY_TRANSPORTITEM: "TRANSPORTITEM",
    VICTORY_DEFEAT_ALL_MONSTERS: "DEFEAT_ALL_MONSTERS",
    VICTORY_SURVIVE_TIME: "SURVIVE_TIME",
    VICTORY_WINSTANDARD: "WINSTANDARD",
}

LOSS_CONDITION_NAMES: dict[int, str] = {
    LOSS_CASTLE: "LOSSCASTLE",
    LOSS_HERO: "LOSSHERO",
    LOSS_TIMEEXPIRES: "TIMEEXPIRES",
    LOSS_STANDARD: "LOSSSTANDARD",
}


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


def _read_hota_header_extension(reader: BinaryReader, version: int) -> dict[str, Any] | None:
    """Read the HotA 1.8 fields between format id and the classic H3M header.

    Format-level 9 is the HotA 1.8 layout implemented by current VCMI. Older
    HotA levels have different feature widths and remain unsupported rather
    than being interpreted as SoD.
    """

    if version != H3M_VERSION_HOTA:
        return None

    format_level = reader.read_u32()
    if format_level != H3M_HOTA_FORMAT_LEVEL_1_8:
        raise ValueError(
            f"unsupported HotA format level {format_level}; "
            f"expected {H3M_HOTA_FORMAT_LEVEL_1_8} (HotA 1.8)"
        )

    release = (reader.read_u32(), reader.read_u32(), reader.read_u32())
    if release[:2] != (1, 8):
        raise ValueError(f"unsupported HotA release {release[0]}.{release[1]}.{release[2]}")

    is_mirror_map = reader.read_bool()
    is_arena_map = reader.read_bool()
    if is_mirror_map or is_arena_map:
        modes = []
        if is_mirror_map:
            modes.append("mirror")
        if is_arena_map:
            modes.append("arena")
        raise ValueError(f"unsupported HotA map mode: {', '.join(modes)}")

    terrain_types_count = reader.read_u32()
    town_types_count = reader.read_u32()
    allowed_difficulties_mask = reader.read_u8()
    can_hire_defeated_heroes = reader.read_bool()
    force_matching_version = reader.read_bool()
    unknown = reader.read_u32()

    if terrain_types_count != 12:
        raise ValueError(f"unsupported HotA terrain type count {terrain_types_count}; expected 12")
    if town_types_count != 12:
        raise ValueError(f"unsupported HotA town type count {town_types_count}; expected 12")
    if allowed_difficulties_mask not in (0, 31):
        raise ValueError(
            f"unsupported HotA allowed difficulties mask {allowed_difficulties_mask:#x}"
        )
    if unknown != 0:
        raise ValueError(f"unsupported nonzero HotA 1.8 header field {unknown}")

    return {
        "formatLevel": format_level,
        "release": {
            "major": release[0],
            "minor": release[1],
            "patch": release[2],
        },
        "isMirrorMap": is_mirror_map,
        "isArenaMap": is_arena_map,
        "terrainTypesCount": terrain_types_count,
        "townTypesCount": town_types_count,
        "allowedDifficultiesMask": allowed_difficulties_mask,
        "canHireDefeatedHeroes": can_hire_defeated_heroes,
        "forceMatchingVersion": force_matching_version,
    }


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
    if version not in SUPPORTED_H3M_VERSIONS:
        raise ValueError(
            f"unsupported H3M version {version}; expected one of {sorted(SUPPORTED_H3M_VERSIONS)}"
        )
    _read_hota_header_extension(reader, version)
    reader.read_bool()
    size = reader.read_u32()
    if size not in SUPPORTED_H3M_SIZES:
        raise ValueError(f"unsupported H3M map size {size}; expected one of {sorted(SUPPORTED_H3M_SIZES)}")
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


def _read_int3(reader: BinaryReader) -> dict[str, int]:
    return {"x": reader.read_u8(), "y": reader.read_u8(), "z": reader.read_u8()}


def decode_h3m_scenario_header(data: bytes) -> dict[str, Any]:
    """Decode players + victory/loss from the H3M header (VCMI-shaped AB/RoE/SoD).

    Empty-player padding follows VCMI MapFormatH3M: RoE contributes 6 unused bytes,
    AB adds another 6 (12 total), SoD adds 1 more. Proven against Dungeon Keeper
    (WINSTANDARD) and Treasure Hunt (TAKEMINES) stock Complete maps.
    """

    reader = BinaryReader(data)
    version = reader.read_u32()
    if version not in SUPPORTED_H3M_VERSIONS:
        raise ValueError(
            f"unsupported H3M version {version}; expected one of {sorted(SUPPORTED_H3M_VERSIONS)}"
        )
    hota = _read_hota_header_extension(reader, version)
    any_players = reader.read_bool()
    size = reader.read_u32()
    if size not in SUPPORTED_H3M_SIZES:
        raise ValueError(f"unsupported H3M map size {size}; expected one of {sorted(SUPPORTED_H3M_SIZES)}")
    has_underground = reader.read_bool()
    title = reader.read_base_string(max_length=256)
    description = reader.read_base_string(max_length=4096)
    difficulty = reader.read_u8()
    is_ab = version >= H3M_VERSION_AB
    is_sod = version >= H3M_VERSION_SOD
    level_limit = reader.read_u8() if is_ab else 0
    factions_bytes = 2 if is_ab else 1
    heroes_bytes = 27 if version == H3M_VERSION_HOTA else (20 if is_ab else 16)

    players: list[dict[str, Any]] = []
    for index in range(8):
        can_human = reader.read_bool()
        can_computer = reader.read_bool()
        if not (can_human or can_computer):
            # VCMI: independent skips for each format feature bit that is set.
            skip_n = 6
            if is_ab:
                skip_n += 6
            if is_sod:
                skip_n += 1
            reader.skip(skip_n)
            players.append(
                {
                    "index": index,
                    "playable": False,
                    "canHuman": can_human,
                    "canComputer": can_computer,
                }
            )
            continue

        ai_tactic = reader.read_u8()
        if is_sod:
            reader.skip(1)  # faction selectable
        factions_mask = list(data[reader.tell() : reader.tell() + factions_bytes])
        reader.skip(factions_bytes)
        is_faction_random = reader.read_bool()
        has_main_town = reader.read_bool()
        main_town = None
        if has_main_town:
            generate_hero = True
            if is_ab:
                generate_hero = reader.read_bool()
                reader.skip(1)  # unused starting town type
            main_town = {"generateHero": generate_hero, **_read_int3(reader)}
        has_random_hero = reader.read_bool()
        main_custom_hero_id = reader.read_u8()
        custom_hero = None
        if main_custom_hero_id != 0xFF:
            custom_hero = {
                "portrait": reader.read_u8(),
                "name": reader.read_base_string(max_length=256),
            }
        heroes_names: list[dict[str, Any]] = []
        if is_ab:
            reader.skip(1)
            hero_count = reader.read_u32()
            if hero_count > 64:
                raise ValueError(f"implausible player heroCount {hero_count} at 0x{reader.tell() - 4:x}")
            for _ in range(hero_count):
                heroes_names.append(
                    {
                        "id": reader.read_u8(),
                        "name": reader.read_base_string(max_length=256),
                    }
                )
        players.append(
            {
                "index": index,
                "playable": True,
                "canHuman": can_human,
                "canComputer": can_computer,
                "aiTactic": ai_tactic,
                "factionsMask": factions_mask,
                "isFactionRandom": is_faction_random,
                "mainTown": main_town,
                "hasRandomHero": has_random_hero,
                "mainCustomHeroId": main_custom_hero_id,
                "customHero": custom_hero,
                "heroesNames": heroes_names,
            }
        )

    victory_type = reader.read_u8()
    allow_normal_victory: bool | None = None
    applies_to_computer: bool | None = None
    victory_special: dict[str, Any] = {}
    if victory_type != VICTORY_WINSTANDARD:
        allow_normal_victory = reader.read_bool()
        applies_to_computer = reader.read_bool()
        if victory_type == VICTORY_ARTIFACT:
            victory_special["artifactId"] = reader.read_u8()
            if is_ab:
                reader.skip(1)
        elif victory_type == VICTORY_GATHERTROOP:
            creature_id = reader.read_u8()
            if is_ab:
                reader.skip(1)
            victory_special["creatureId"] = creature_id
            victory_special["count"] = reader.read_u32()
        elif victory_type == VICTORY_GATHERRESOURCE:
            victory_special["resourceId"] = reader.read_u8()
            victory_special["count"] = reader.read_u32()
        elif victory_type == VICTORY_BUILDCITY:
            victory_special["position"] = _read_int3(reader)
            victory_special["hallLevel"] = reader.read_u8()
            victory_special["castleLevel"] = reader.read_u8()
        elif victory_type in (
            VICTORY_BUILDGRAIL,
            VICTORY_BEATHERO,
            VICTORY_CAPTURECITY,
            VICTORY_BEATMONSTER,
        ):
            victory_special["position"] = _read_int3(reader)
        elif victory_type in (VICTORY_TAKEDWELLINGS, VICTORY_TAKEMINES):
            pass
        elif victory_type == VICTORY_TRANSPORTITEM:
            victory_special["artifactId"] = reader.read_u8()
            victory_special["position"] = _read_int3(reader)
        elif victory_type == VICTORY_SURVIVE_TIME:
            victory_special["days"] = reader.read_u16()
        elif victory_type == VICTORY_DEFEAT_ALL_MONSTERS:
            pass
        else:
            raise ValueError(f"unsupported victory condition type {victory_type} at 0x{reader.tell() - 1:x}")

    loss_type = reader.read_u8()
    loss_special: dict[str, Any] = {}
    if loss_type != LOSS_STANDARD:
        if loss_type in (LOSS_CASTLE, LOSS_HERO):
            loss_special["position"] = _read_int3(reader)
        elif loss_type == LOSS_TIMEEXPIRES:
            loss_special["days"] = reader.read_u16()
        else:
            raise ValueError(f"unsupported loss condition type {loss_type} at 0x{reader.tell() - 1:x}")

    teams_count = reader.read_u8()
    teams: list[int] = []
    if teams_count:
        teams = list(data[reader.tell() : reader.tell() + 8])
        reader.skip(8)
    if version == H3M_VERSION_HOTA:
        heroes_count = reader.read_u32()
        if heroes_count != H3M_HOTA_1_8_HERO_COUNT:
            raise ValueError(
                f"unsupported HotA hero count {heroes_count}; "
                f"expected {H3M_HOTA_1_8_HERO_COUNT}"
            )
        heroes_bytes = (heroes_count + 7) // 8
    allowed_heroes = list(data[reader.tell() : reader.tell() + heroes_bytes])
    reader.skip(heroes_bytes)
    placeholders: list[int] = []
    if is_ab:
        placeholder_count = reader.read_u32()
        if placeholder_count > 200:
            raise ValueError(
                f"implausible campaign hero placeholder count {placeholder_count} at 0x{reader.tell() - 4:x}"
            )
        placeholders = [reader.read_u8() for _ in range(placeholder_count)]

    victory_name = VICTORY_CONDITION_NAMES.get(victory_type)
    loss_name = LOSS_CONDITION_NAMES.get(loss_type)
    if victory_name is None:
        raise ValueError(f"unmapped victory condition type {victory_type}")
    if loss_name is None:
        raise ValueError(f"unmapped loss condition type {loss_type}")

    return {
        "version": version,
        "anyPlayers": any_players,
        "size": size,
        "hasUnderground": has_underground,
        "title": title,
        "description": description,
        "difficulty": difficulty,
        "levelLimit": level_limit,
        "hota": hota,
        "players": players,
        "victory": {
            "type": victory_type,
            "name": victory_name,
            "allowNormalVictory": allow_normal_victory,
            "appliesToComputer": applies_to_computer,
            "special": victory_special,
        },
        "loss": {
            "type": loss_type,
            "name": loss_name,
            "special": loss_special,
        },
        "teamsCount": teams_count,
        "teams": teams,
        "allowedHeroesMask": allowed_heroes,
        "campaignHeroPlaceholders": placeholders,
        "headerPlayersEndOffset": reader.tell(),
    }
