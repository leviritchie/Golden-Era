#!/usr/bin/env python3
"""Decode HoMM3 H3C scenario START_BONUS travel options (VCMI CampaignBonus).

Header block 0 carries per-scenario travel options. Map payloads are separate
gzip members; join via ``H3M_NAME_BY_MISSION_BLOCK`` map filenames.

Proof boundary: source/static decode against Complete LOD archives.
"""

from __future__ import annotations

import struct
from functools import lru_cache
from typing import Any

import port_homecoming_poc as poc
from build_campaign_layered_ir import H3M_NAME_BY_MISSION_BLOCK
from h3c_mission_source import resolve_h3c_lod_path

# CampaignStartOptions
START_NONE = 0
START_BONUS = 1
START_CROSSOVER = 2
START_HERO = 3

# CampaignBonusType
BONUS_SPELL = 0
BONUS_MONSTER = 1
BONUS_BUILDING = 2
BONUS_ARTIFACT = 3
BONUS_SPELL_SCROLL = 4
BONUS_PRIMARY_SKILL = 5
BONUS_SECONDARY_SKILL = 6
BONUS_RESOURCE = 7

BONUS_TYPE_NAMES: dict[int, str] = {
    BONUS_SPELL: "SPELL",
    BONUS_MONSTER: "MONSTER",
    BONUS_BUILDING: "BUILDING",
    BONUS_ARTIFACT: "ARTIFACT",
    BONUS_SPELL_SCROLL: "SPELL_SCROLL",
    BONUS_PRIMARY_SKILL: "PRIMARY_SKILL",
    BONUS_SECONDARY_SKILL: "SECONDARY_SKILL",
    BONUS_RESOURCE: "RESOURCE",
}

# GameResID specials used by campaign resource bonuses (signed i8).
# VCMI / H3: 0xFD = wood+ore (common), 0xFE = rare (mercury/sulfur/crystal/gems).
RESOURCE_COMMON = -3  # 0xFD
RESOURCE_RARE = -2  # 0xFE


class _Reader:
    def __init__(self, blob: bytes) -> None:
        self.b = blob
        self.i = 0

    def u8(self) -> int:
        value = self.b[self.i]
        self.i += 1
        return value

    def i8(self) -> int:
        value = struct.unpack_from("<b", self.b, self.i)[0]
        self.i += 1
        return value

    def u16(self) -> int:
        value = struct.unpack_from("<H", self.b, self.i)[0]
        self.i += 2
        return value

    def i16(self) -> int:
        value = struct.unpack_from("<h", self.b, self.i)[0]
        self.i += 2
        return value

    def u32(self) -> int:
        value = struct.unpack_from("<I", self.b, self.i)[0]
        self.i += 4
        return value

    def i32(self) -> int:
        value = struct.unpack_from("<i", self.b, self.i)[0]
        self.i += 4
        return value

    def s(self) -> str:
        n = self.u32()
        if n > 2_000_000 or self.i + n > len(self.b):
            raise ValueError(f"bad H3C string length {n} at {self.i}")
        raw = self.b[self.i : self.i + n]
        self.i += n
        return raw.split(b"\x00", 1)[0].decode("cp1252", "replace")

    def bool(self) -> bool:
        return self.u8() != 0

    def skip(self, n: int) -> None:
        self.i += n


def discover_scenario_map_names(blob: bytes) -> list[str]:
    """Find unique `.h3m` scenario names in header order."""
    maps: list[tuple[int, str]] = []
    i = 0
    while True:
        j = blob.find(b".h3m", i)
        if j < 0:
            break
        for back in range(4, 50):
            off = j - back
            if off < 0:
                continue
            length = struct.unpack_from("<I", blob, off)[0]
            if length != back or not (5 <= length <= 50):
                continue
            name = blob[off + 4 : off + 4 + length].decode("ascii", "replace")
            if name.lower().endswith(".h3m") and all(32 <= ord(c) < 127 for c in name):
                maps.append((off, name))
                break
        i = j + 1
    seen: set[str] = set()
    out: list[str] = []
    for _off, name in maps:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _read_bonus(reader: _Reader, start_options: int) -> dict[str, Any]:
    if start_options == START_BONUS:
        bonus_type = reader.u8()
        name = BONUS_TYPE_NAMES.get(bonus_type)
        if name is None:
            raise ValueError(f"unsupported campaign bonus type {bonus_type} at {reader.i}")
        if bonus_type == BONUS_SPELL:
            return {"type": name, "hero": reader.i16(), "spell": reader.u8()}
        if bonus_type == BONUS_MONSTER:
            return {
                "type": name,
                "hero": reader.i16(),
                "creature": reader.u16(),
                "amount": reader.u16(),
            }
        if bonus_type == BONUS_BUILDING:
            return {"type": name, "building": reader.u8()}
        if bonus_type == BONUS_ARTIFACT:
            return {"type": name, "hero": reader.i16(), "artifact": reader.u16()}
        if bonus_type == BONUS_SPELL_SCROLL:
            return {"type": name, "hero": reader.i16(), "spell": reader.u8()}
        if bonus_type == BONUS_PRIMARY_SKILL:
            return {
                "type": name,
                "hero": reader.i16(),
                "attack": reader.u8(),
                "defense": reader.u8(),
                "power": reader.u8(),
                "knowledge": reader.u8(),
            }
        if bonus_type == BONUS_SECONDARY_SKILL:
            return {
                "type": name,
                "hero": reader.i16(),
                "skill": reader.u8(),
                "mastery": reader.u8(),
            }
        if bonus_type == BONUS_RESOURCE:
            return {"type": name, "resource": reader.i8(), "amount": reader.i32()}
        raise ValueError(f"unhandled bonus type {bonus_type}")
    if start_options == START_CROSSOVER:
        return {"type": "CROSSOVER", "player": reader.u8(), "scenario": reader.u8()}
    if start_options == START_HERO:
        return {"type": "HERO", "player": reader.u8(), "hero": reader.i16()}
    raise ValueError(f"unexpected startOptions {start_options}")


def parse_campaign_header_scenarios(blob: bytes) -> dict[str, Any]:
    """Parse H3C header travel options keyed by scenario map filename."""
    map_names = discover_scenario_map_names(blob)
    if not map_names:
        raise ValueError("H3C header has no scenario map names")
    reader = _Reader(blob)
    version = reader.u32()
    _map_id = reader.u8()
    campaign_name = reader.s()
    _desc = reader.s()
    # AB+ (version > RoE/4) store difficultyChosenByPlayer.
    if version > 4:
        reader.bool()
    _music = reader.u8()

    scenarios: list[dict[str, Any]] = []
    by_map: dict[str, dict[str, Any]] = {}
    for map_name in map_names:
        pref = struct.pack("<I", len(map_name)) + map_name.encode("ascii")
        at = blob.find(pref, reader.i)
        if at < 0:
            raise ValueError(f"H3C header missing scenario map {map_name!r} from {reader.i}")
        reader.i = at
        got = reader.s()
        if got != map_name:
            raise ValueError(f"expected map {map_name!r}, got {got!r}")
        packed = reader.u32()
        if len(map_names) > 8:
            _pre = reader.u16()
        else:
            _pre = reader.u8()
        color = reader.u8()
        difficulty = reader.u8()
        region = reader.s()
        for _ in range(2):  # prolog, epilog
            if reader.bool():
                reader.u8()
                reader.u8()
                reader.s()
        _keeps = reader.u8()
        artifact_bytes = 18 if version >= 6 else 17
        reader.skip(19)  # creatures kept
        reader.skip(artifact_bytes)
        start_options = reader.u8()
        player_color = None
        if start_options == START_BONUS:
            player_color = reader.u8()
        bonuses: list[dict[str, Any]] = []
        if start_options != START_NONE:
            count = reader.u8()
            for _ in range(count):
                bonuses.append(_read_bonus(reader, start_options))
        row = {
            "mapName": map_name,
            "packedSize": packed,
            "regionColor": color,
            "difficulty": difficulty,
            "regionText": region,
            "startOptions": start_options,
            "playerColor": player_color,
            "bonuses": bonuses,
        }
        scenarios.append(row)
        by_map[map_name.lower()] = row
    return {
        "version": version,
        "campaignName": campaign_name,
        "scenarios": scenarios,
        "byMapName": by_map,
    }


@lru_cache(maxsize=64)
def load_campaign_starting_bonus_index(campaign_entry: str) -> dict[str, Any]:
    lod = resolve_h3c_lod_path(campaign_entry)
    compressed = poc.read_lod_entry(lod, campaign_entry)
    blocks = poc.split_concatenated_gzip_members(compressed)
    if not blocks:
        raise ValueError(f"{campaign_entry}: empty H3C")
    return parse_campaign_header_scenarios(blocks[0].payload)


def starting_bonuses_for_mission(
    campaign_entry: str,
    block_index: int,
) -> dict[str, Any] | None:
    """Return START_BONUS payload for a mission block, or None when not choose-one."""
    key = (campaign_entry, block_index)
    map_name = H3M_NAME_BY_MISSION_BLOCK.get(key)
    if map_name is None:
        # Case-insensitive campaign entry fallback (evil1 vs EVIL1.H3C).
        for (entry, block), name in H3M_NAME_BY_MISSION_BLOCK.items():
            if entry.lower() == campaign_entry.lower() and block == block_index:
                map_name = name
                campaign_entry = entry
                break
    if map_name is None:
        raise ValueError(
            f"no H3M map name for campaign={campaign_entry!r} block={block_index}"
        )
    index = load_campaign_starting_bonus_index(campaign_entry)
    row = index["byMapName"].get(map_name.lower())
    if row is None:
        raise ValueError(
            f"{campaign_entry} block {block_index}: header missing map {map_name!r}; "
            f"known={sorted(index['byMapName'])}"
        )
    if int(row["startOptions"]) != START_BONUS:
        return None
    bonuses = list(row["bonuses"] or [])
    # A single listed bonus is not a choose-one dialog (HoMM3 may auto-apply).
    # Day-1 multi-answer Dialogs need at least two options.
    if len(bonuses) < 2:
        return None
    return {
        "campaignEntry": campaign_entry,
        "blockIndex": block_index,
        "mapName": map_name,
        "playerColor": row.get("playerColor"),
        "bonuses": bonuses,
        "campaignName": index.get("campaignName"),
    }
