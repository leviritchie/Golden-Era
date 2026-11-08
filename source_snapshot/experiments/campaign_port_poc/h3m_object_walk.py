#!/usr/bin/env python3
"""Reusable fail-closed H3M object table walker.

This module contains the generic object-table walking core used by campaign and
standalone scenario probes. It intentionally has no scan-ahead recovery: every
object payload must be handled by an explicit decoder or an explicit no-payload
allowlist entry, and the first unsupported record stops the walk.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path
from typing import Any, Callable

import h3m_format as h3m
import h3m_object_registry as h3obj


RESOURCES_COUNT = 7
SKILLS_BYTES = 4
SPELLS_BYTES = 9
BUILDINGS_BYTES = 6
CREATURE_SLOTS = 7
ARTIFACT_SLOTS_AB = 19
ARTIFACT_NONE_U16 = 0xFFFF
FACTION_BITMASK_BYTES = 2
H3M_VERSION_HOTA_MIN = 29

OBJECT_GENERIC_NO_PAYLOAD = "explicit_no_payload"


class UnsupportedObjectPayload(ValueError):
    """Raised when the walker reaches a known but intentionally unsupported payload."""

    def __init__(self, status: str, message: str):
        super().__init__(message)
        self.status = status


class H3MObjectWalkIncomplete(RuntimeError):
    """Raised by strict walker APIs when decoding stops before the declared object count."""

    def __init__(self, partial_walk: dict[str, Any]):
        stop = partial_walk["objectTable"]["unsupportedStop"]
        message = "H3M object walk incomplete"
        if stop is not None:
            message = f"{message}: {stop['decoderStatus']}: {stop['error']}"
        super().__init__(message)
        self.partial_walk = partial_walk


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_h3m_bytes(path: str | Path) -> bytes:
    """Read a standalone H3M file, accepting the normal gzip-wrapped form."""

    raw = Path(path).read_bytes()
    if raw.startswith(b"\x1f\x8b"):
        return gzip.decompress(raw)
    return raw


def summarize_h3m(data: bytes) -> h3m.H3MShapeSummary:
    return h3m.summarize_h3m_shape(data)


def read_h3m_summary_and_templates(data: bytes) -> tuple[h3m.H3MShapeSummary, list[dict[str, Any]]]:
    summary = summarize_h3m(data)
    _terrain_start, _object_table_offset, _object_count, templates = h3m.locate_h3m_terrain_and_objects(
        data,
        summary.size,
        summary.layers,
    )
    return summary, templates


def is_hota_map_version(version: int) -> bool:
    return version >= H3M_VERSION_HOTA_MIN


class Walker:
    def __init__(self, data: bytes):
        self.reader = h3m.BinaryReader(data)
        self.data = data

    def tell(self) -> int:
        return self.reader.tell()

    def seek(self, pos: int) -> None:
        self.reader.seek(pos)

    def skip(self, count: int) -> None:
        self.reader.skip(count)

    def read_u8(self) -> int:
        return self.reader.read_u8()

    def read_bool(self) -> bool:
        return self.reader.read_bool()

    def read_u16(self) -> int:
        return self.reader.read_u16()

    def read_u32(self) -> int:
        return self.reader.read_u32()

    def read_i32(self) -> int:
        value = int.from_bytes(self.data[self.tell() : self.tell() + 4], "little", signed=True)
        self.skip(4)
        return value

    def read_i8(self) -> int:
        value = self.data[self.tell()]
        self.skip(1)
        return value if value < 128 else value - 256

    def read_i16(self) -> int:
        value = int.from_bytes(self.data[self.tell() : self.tell() + 2], "little", signed=True)
        self.skip(2)
        return value

    def read_string(self, max_length: int = 4096) -> str:
        return self.reader.read_base_string(max_length=max_length)

    def skip_resources(self) -> None:
        self.skip(RESOURCES_COUNT * 4)

    def read_resources(self) -> list[int]:
        return [self.read_u32() for _ in range(RESOURCES_COUNT)]

    def skip_creature_set(self, *, h3m_version: int | None = None) -> None:
        if h3m_version is not None and h3m_version < h3m.H3M_VERSION_AB:
            # RoE: u8 type + u16 count per slot.
            self.skip(CREATURE_SLOTS * 3)
            return
        self.skip(CREATURE_SLOTS * 4)

    def read_creature_set(self, *, h3m_version: int | None = None) -> list[dict[str, int]]:
        """Decode classic 7-slot creature set.

        RoE uses u8 type (0xFF empty) + u16 count. AB+ uses u16 type (0xFFFF empty) + u16 count.
        """

        stacks: list[dict[str, int]] = []
        roe = h3m_version is not None and h3m_version < h3m.H3M_VERSION_AB
        for slot in range(CREATURE_SLOTS):
            creature_type = self.read_u8() if roe else self.read_u16()
            count = self.read_u16()
            stacks.append({"slot": slot, "creatureType": creature_type, "count": count})
        return stacks

    def read_bitmask_bytes(self, length: int) -> str:
        raw = bytes(self.data[self.tell() : self.tell() + length])
        self.skip(length)
        return raw.hex()

    def skip_bitmask_factions(self) -> None:
        self.skip(FACTION_BITMASK_BYTES)

    def skip_artifact16(self) -> int:
        return self.read_u16()

    def read_secondary_skills(self, count: int) -> list[dict[str, int]]:
        skills: list[dict[str, int]] = []
        for _ in range(count):
            skill_id = self.read_u8()
            level = self.read_u8()
            skills.append({"skillId": skill_id, "level": level})
        return skills

    def read_hero_artifact_set(self, *, h3m_version: int | None = None) -> dict[str, Any]:
        has_art_set = self.read_bool()
        equipped: list[int] = []
        backpack: list[int] = []
        if has_art_set:
            roe = h3m_version is not None and h3m_version < h3m.H3M_VERSION_AB
            sod = h3m_version is not None and h3m_version >= h3m.H3M_VERSION_SOD
            # RoE: 18 equipped slots as u8.
            # AB: 18 equipped slots as u16 (VCMI artifactSlotsCount for AB; empirically
            #     Good2.h3c block 4 hero@1:99:57 desyncs if a 19th u16 is consumed).
            # SoD+: 19 equipped slots as u16 (misc5 / ARTIFACT_SLOTS_AB).
            if roe:
                slot_count = 18
                equipped = [self.read_u8() for _ in range(slot_count)]
            else:
                slot_count = ARTIFACT_SLOTS_AB if sod else 18
                if h3m_version == h3m.H3M_VERSION_HOTA:
                    equipped = [self.read_u32() for _ in range(slot_count)]
                else:
                    equipped = [self.read_u16() for _ in range(slot_count)]
            backpack_count = self.read_u16()
            if backpack_count > 256:
                raise ValueError(f"implausible hero backpack artifact count {backpack_count}")
            if roe:
                backpack = [self.read_u8() for _ in range(backpack_count)]
            elif h3m_version == h3m.H3M_VERSION_HOTA:
                backpack = [self.read_u32() for _ in range(backpack_count)]
            else:
                backpack = [self.read_u16() for _ in range(backpack_count)]
        return {
            "hasArtifactSet": has_art_set,
            "equippedArtifacts": equipped,
            "backpackArtifacts": backpack,
            "backpackArtifactCount": len(backpack),
        }

    def skip_message_and_guards(self, *, h3m_version: int | None = None) -> dict[str, Any]:
        start = self.tell()
        has_message = self.read_bool()
        message = None
        has_guards = False
        guard_stacks: list[dict[str, int]] | None = None
        if has_message:
            message = self.read_string(max_length=1_000_000)
            has_guards = self.read_bool()
            if has_guards:
                guard_stacks = self.read_creature_set(h3m_version=h3m_version)
            self.skip(4)
        result: dict[str, Any] = {
            "hasMessage": has_message,
            "message": message,
            "hasGuards": has_guards,
            "bytes": self.tell() - start,
        }
        if guard_stacks is not None:
            result["guardStacks"] = guard_stacks
        return result

    def skip_box_content(self, *, h3m_version: int | None = None) -> dict[str, Any]:
        """Decode Pandora/event box content with full reward lists (VCMI-shaped)."""

        message = self.skip_message_and_guards(h3m_version=h3m_version)
        experience = self.read_u32()
        mana = self.read_u32()
        morale = self.read_i8()
        luck = self.read_i8()
        resources = self.read_resources()
        primary_skill = self.read_u32()
        skill_count = self.read_u8()
        if skill_count > 64:
            raise ValueError(f"implausible box skill reward count {skill_count}")
        skills = self.read_secondary_skills(skill_count)
        artifact_count = self.read_u8()
        if artifact_count > 128:
            raise ValueError(f"implausible box artifact reward count {artifact_count}")
        if h3m_version == h3m.H3M_VERSION_HOTA:
            artifacts = [self.read_u32() for _ in range(artifact_count)]
        else:
            artifacts = [self.read_u16() for _ in range(artifact_count)]
        spell_count = self.read_u8()
        if spell_count > 128:
            raise ValueError(f"implausible box spell reward count {spell_count}")
        spells = [self.read_u8() for _ in range(spell_count)]
        creature_count = self.read_u8()
        if creature_count > 64:
            raise ValueError(f"implausible box creature reward count {creature_count}")
        creatures: list[dict[str, int]] = []
        for _ in range(creature_count):
            creatures.append({"creatureType": self.read_u16(), "count": self.read_u16()})
        self.skip(8)
        return {
            "messageAndGuards": message,
            "rewardCounts": {
                "skills": skill_count,
                "artifacts": artifact_count,
                "spells": spell_count,
                "creatures": creature_count,
            },
            "rewards": {
                "experience": experience,
                "mana": mana,
                "morale": morale,
                "luck": luck,
                "resources": resources,
                "primarySkill": primary_skill,
                "skills": skills,
                "artifacts": artifacts,
                "spells": spells,
                "creatures": creatures,
            },
        }

    def skip_event_common(self, *, h3m_version: int | None = None) -> dict[str, Any]:
        name = self.read_string()
        message = self.read_string()
        resources = self.read_resources()
        players = self.read_u8()
        # RoE/AB (v14/v21): no humanAffected byte (Homecoming-proven).
        # SoD+ (v28+): humanAffected is present; HotA keeps additional trailing fields below.
        if h3m_version is not None and h3m_version >= h3m.H3M_VERSION_SOD:
            human_affected = self.read_bool()
        else:
            human_affected = True
        computer_affected = self.read_bool()
        first_occurrence = self.read_u16()
        next_occurrence = self.read_u16()
        self.skip(16)
        result = {
            "name": name,
            "message": message,
            "resources": resources,
            "players": players,
            "humanAffected": human_affected,
            "computerAffected": computer_affected,
            "firstOccurrence": first_occurrence,
            "nextOccurrence": next_occurrence,
        }
        if h3m_version == h3m.H3M_VERSION_HOTA:
            result["affectedDifficulties"] = self.read_u32()
            uses_event_system = self.read_bool()
            result["usesEventSystem"] = uses_event_system
            if uses_event_system:
                result["eventId"] = self.read_i32()
                result["synchronizeObjects"] = self.read_bool()
        return result

    def skip_hero_artifact_set(self) -> int:
        return int(self.read_hero_artifact_set()["backpackArtifactCount"])


def parse_header(walker: Walker, summary: h3m.H3MShapeSummary, templates: list[dict[str, Any]], index: int) -> dict[str, Any]:
    offset = walker.tell()
    x = walker.read_u8()
    y = walker.read_u8()
    z = walker.read_u8()
    template_index = walker.read_u32()
    zero = bytes(walker.data[walker.tell() : walker.tell() + 5])
    walker.skip(5)
    if not (0 <= x <= summary.size + 8 and 0 <= y <= summary.size + 8 and 0 <= z < summary.layers):
        raise ValueError(f"record {index} header position out of range at 0x{offset:x}: {x},{y},{z}")
    if template_index >= len(templates):
        raise ValueError(f"record {index} template index {template_index} outside {len(templates)} at 0x{offset:x}")
    if zero != b"\x00\x00\x00\x00\x00":
        raise ValueError(f"record {index} nonzero fixed header padding at 0x{offset + 7:x}: {zero.hex()}")
    template = templates[template_index]
    return {
        "index": index,
        "recordOffset": f"0x{offset:x}",
        "x": x,
        "y": y,
        "z": z,
        "layer": z,
        "key": f"{z}:{x}:{y}",
        "templateIndex": template_index,
        "templateAnimation": template.get("animation"),
        "templateBlockMask": template.get("blockMask"),
        "templateVisitMask": template.get("visitMask"),
        "templateObjectId": template.get("objectId"),
        "templateSubtype": template.get("subtype"),
    }


def skip_generic(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {"payloadKind": OBJECT_GENERIC_NO_PAYLOAD}
    evidence = h3obj.NO_PAYLOAD_OBJECT_EVIDENCE.get(record["templateObjectId"])
    if evidence is not None:
        payload["noPayloadEvidence"] = evidence
    return payload


def skip_sign(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    message = walker.read_string()
    walker.skip(4)
    return {"payloadKind": "sign", "message": message}


def skip_ocean_bottle(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    payload = skip_sign(walker, record)
    payload["payloadKind"] = "ocean_bottle"
    return payload


def skip_owner_u32(walker: Walker, record: dict[str, Any], *, payload_kind: str) -> dict[str, Any]:
    owner = walker.read_u32()
    return {"payloadKind": payload_kind, "owner": owner, "ownerEncoding": "h3m_readPlayer32"}


def skip_mine(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    return skip_owner_u32(walker, record, payload_kind="mine")


def skip_shipyard(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    return skip_owner_u32(walker, record, payload_kind="shipyard")


def skip_lighthouse(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    return skip_owner_u32(walker, record, payload_kind="lighthouse")


# VCMI readAbandonedMine uses readBitmaskResources (one u32), not readResources (7*u32).
ABANDONED_MINE_RESOURCE_BITMASK_BYTES = 4


def skip_abandoned_mine(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    resource_mask = walker.read_u32()
    if is_hota_map_version(record["h3mVersion"]):
        has_custom_guards = walker.read_bool()
        if has_custom_guards:
            walker.skip(4)
            walker.skip(4)
            walker.skip(4)
        else:
            walker.skip(12)
    return {
        "payloadKind": "abandoned_mine",
        "resourceBitmask": f"0x{resource_mask:08x}",
        "resourceEncoding": "h3m_readBitmaskResources",
    }


def skip_mine_family(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    object_id = record["templateObjectId"]
    subtype = int(record.get("templateSubtype") or 0)
    if object_id == h3obj.OBJECT_ABANDONED_MINE or (object_id == h3obj.OBJECT_MINE and subtype >= 7):
        return skip_abandoned_mine(walker, record)
    return skip_mine(walker, record)


def skip_witch_hut(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    # RoE Witch Hut has no object payload. AB+ adds a 4-byte allowed-skills bitmask.
    start = walker.tell()
    if record["h3mVersion"] >= h3m.H3M_VERSION_AB:
        walker.skip(SKILLS_BYTES)
    return {"payloadKind": "witch_hut", "skillMaskBytes": walker.data[start:walker.tell()].hex()}


def skip_scholar(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    bonus_type = walker.read_u8()
    bonus_id = walker.read_u8()
    walker.skip(6)
    return {"payloadKind": "scholar", "bonusTypeRaw": bonus_type, "bonusId": bonus_id}


def skip_monster(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    identifier = walker.read_u32() if record["h3mVersion"] >= h3m.H3M_VERSION_AB else None
    count = walker.read_u16()
    character = walker.read_u8()
    has_message = walker.read_bool()
    message = None
    artifact = None
    guard_resources: list[int] | None = None
    if has_message:
        message = walker.read_string()
        guard_resources = walker.read_resources()
        artifact = walker.read_u16()
    never_flees = walker.read_bool()
    not_growing = walker.read_bool()
    walker.skip(2)
    hota_monster: dict[str, Any] | None = None
    if is_hota_map_version(record["h3mVersion"]):
        hota_monster = {
            "exactAggression": walker.read_i32(),
            "joinOnlyForMoney": walker.read_bool(),
            "joiningPercentage": walker.read_i32(),
            "upgradedStackPresence": walker.read_i32(),
            "stacksCount": walker.read_i32(),
            "sizeByValue": walker.read_bool(),
            "targetValue": walker.read_i32(),
        }
    result: dict[str, Any] = {
        "payloadKind": "monster",
        "identifier": f"0x{identifier:08x}" if identifier is not None else None,
        "count": count,
        "character": character,
        "hasMessage": has_message,
        "message": message,
        "artifact": artifact,
        "neverFlees": never_flees,
        "notGrowingTeam": not_growing,
    }
    if hota_monster is not None:
        result["hota"] = hota_monster
    if guard_resources is not None:
        result["guardResources"] = guard_resources
    return result


def skip_artifact(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    if walker.data[walker.tell() : walker.tell() + 4] == b"\xff\x00\x00\x00":
        if is_hota_map_version(record["h3mVersion"]):
            raise ValueError("HotA artifact payload uses unsupported ff000000 sentinel")
        walker.skip(4)
        return {
            "payloadKind": "artifact",
            "hasMessage": False,
            "message": None,
            "hasGuards": False,
            "sentinel": "ff000000",
        }
    result = {
        "payloadKind": "artifact",
        **walker.skip_message_and_guards(h3m_version=record["h3mVersion"]),
    }
    if is_hota_map_version(record["h3mVersion"]):
        result["pickupMode"] = walker.read_u32()
        result["pickupFlags"] = walker.read_u8()
    return result


def skip_creature_generator(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    object_id = record["templateObjectId"]
    return {
        "payloadKind": "creature_generator",
        "generatorFamily": h3obj.creature_generator_family(object_id),
        "owner": walker.read_u32(),
        "ownerEncoding": "h3m_readPlayer32",
        "payloadDecoderEvidence": h3obj.PAYLOAD_DECODER_EVIDENCE["fixed_creature_generator"],
    }


def skip_resource(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    """Decode fixed (79) or random (76) resource pickup.

    For object id 76 (RANDOM_RESOURCE), amount 0 means the engine picks a random
    amount band; a positive amount is the granted quantity of a randomly chosen
    basic resource. Fixed id 79 uses templateSubtype for the resource type.
    """

    message = walker.skip_message_and_guards(h3m_version=record["h3mVersion"])
    amount = walker.read_u32()
    walker.skip(4)
    return {
        "payloadKind": "resource",
        "messageAndGuards": message,
        "amount": amount,
        "isRandomResource": int(record.get("templateObjectId") or 0) == h3obj.OBJECT_RANDOM_RESOURCE,
    }


def skip_hota_reward_with_garbage(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    """Read HotA 1.7+ fixed reward override plus its reserved value."""

    if not is_hota_map_version(record["h3mVersion"]):
        return skip_generic(walker, record)
    content = walker.read_i32()
    reserved = walker.read_i32()
    return {
        "payloadKind": "hota_reward_with_garbage",
        "content": content,
        "reserved": reserved,
    }


def skip_hota_reward_with_artifact(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    """Read HotA 1.7+ reward selection and artifact-or-reserved value."""

    if not is_hota_map_version(record["h3mVersion"]):
        return skip_generic(walker, record)
    content = walker.read_i32()
    value = walker.read_u32()
    return {
        "payloadKind": "hota_reward_with_artifact",
        "content": content,
        "artifactOrReserved": value,
    }


def skip_hota_resource_reward(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    """Read HotA 1.7+ Campfire/Lean-To/Wagon fixed reward payload."""

    if not is_hota_map_version(record["h3mVersion"]):
        return skip_generic(walker, record)
    content = walker.read_i32()
    reward_data = walker.read_bitmask_bytes(14)
    return {
        "payloadKind": "hota_resource_reward",
        "content": content,
        "rewardData": reward_data,
    }


def skip_hota_creature_bank(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    """Read HotA creature-bank guard and reward customization."""

    if not is_hota_map_version(record["h3mVersion"]):
        return skip_generic(walker, record)
    guards_preset_index = walker.read_i32()
    upgraded_stack_presence = walker.read_i8()
    artifact_count = walker.read_u32()
    if artifact_count > 16:
        raise ValueError(
            f"implausible HotA creature-bank artifact count {artifact_count} "
            f"at {record['recordOffset']}"
        )
    artifacts = [walker.read_u32() for _ in range(artifact_count)]
    return {
        "payloadKind": "hota_creature_bank",
        "guardsPresetIndex": guards_preset_index,
        "upgradedStackPresence": upgraded_stack_presence,
        "artifacts": artifacts,
    }


def skip_hota_fixed_extension(
    walker: Walker,
    record: dict[str, Any],
    *,
    byte_count: int,
    payload_kind: str,
) -> dict[str, Any]:
    if not is_hota_map_version(record["h3mVersion"]):
        return skip_generic(walker, record)
    return {
        "payloadKind": payload_kind,
        "extensionData": walker.read_bitmask_bytes(byte_count),
    }


def skip_hota_box_extension(walker: Walker) -> dict[str, Any]:
    movement_mode = walker.read_i32()
    movement_amount = walker.read_i32()
    affected_difficulties = walker.read_u32()
    uses_event_system = walker.read_bool()
    result = {
        "movementMode": movement_mode,
        "movementAmount": movement_amount,
        "affectedDifficulties": affected_difficulties,
        "usesEventSystem": uses_event_system,
    }
    if uses_event_system:
        result["eventId"] = walker.read_i32()
        result["synchronizeObjects"] = walker.read_bool()
    return result


def skip_event(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    box = walker.skip_box_content(h3m_version=record["h3mVersion"])
    players = walker.read_u8()
    computer_activate = walker.read_bool()
    remove_after_visit = walker.read_bool()
    walker.skip(4)
    human_activate = True
    hota_box = None
    if record["h3mVersion"] == h3m.H3M_VERSION_HOTA:
        human_activate = walker.read_bool()
        hota_box = skip_hota_box_extension(walker)
    result = {
        "payloadKind": "event",
        "boxContent": box,
        "playersMask": players,
        "computerActivate": computer_activate,
        "humanActivate": human_activate,
        "removeAfterVisit": remove_after_visit,
    }
    if hota_box is not None:
        result["hota"] = hota_box
    return result


def skip_pandora(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    box = walker.skip_box_content(h3m_version=record["h3mVersion"])
    hota_box = None
    if record["h3mVersion"] == h3m.H3M_VERSION_HOTA:
        unknown = walker.read_u8()
        hota_box = {"unknown": unknown, **skip_hota_box_extension(walker)}
    result = {"payloadKind": "pandoras_box", "boxContent": box}
    if hota_box is not None:
        result["hota"] = hota_box
    return result


def skip_spell_scroll(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    message = walker.skip_message_and_guards(h3m_version=record["h3mVersion"])
    spell = walker.read_u32()
    return {"payloadKind": "spell_scroll", "messageAndGuards": message, "spellId": spell}


def skip_shrine(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    spell = walker.read_u32()
    return {"payloadKind": "shrine", "spellId": spell}


def skip_grail(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    subtype = int(record.get("templateSubtype") or 0)
    if subtype >= 1000:
        return skip_generic(walker, record)
    radius = walker.read_i32()
    return {"payloadKind": "grail", "radius": radius}


def skip_garrison(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    owner = walker.read_u32()
    garrison_stacks = walker.read_creature_set(h3m_version=record["h3mVersion"])
    removable_units = True
    if record["h3mVersion"] >= h3m.H3M_VERSION_AB:
        removable_units = walker.read_bool()
    walker.skip(8)
    return {
        "payloadKind": "garrison",
        "owner": owner,
        "ownerEncoding": "h3m_readPlayer32",
        "garrisonStacks": garrison_stacks,
        "removableUnits": removable_units,
        "payloadDecoderEvidence": h3obj.PAYLOAD_DECODER_EVIDENCE["garrison"],
    }


def skip_hero_placeholder(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    owner = walker.read_u8()
    hero_type = walker.read_u8()
    power_rank = None
    if hero_type == 0xFF:
        power_rank = walker.read_u8()
    return {
        "payloadKind": "hero_placeholder",
        "owner": owner,
        "heroType": hero_type,
        "powerRank": power_rank,
    }


def skip_random_dwelling(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    object_id = record["templateObjectId"]
    owner = walker.read_u32()
    identifier = None
    if object_id in {h3obj.OBJECT_RANDOM_DWELLING, h3obj.OBJECT_RANDOM_DWELLING_LVL}:
        identifier = walker.read_u32()
        if identifier == 0:
            walker.skip_bitmask_factions()
    if object_id in {h3obj.OBJECT_RANDOM_DWELLING, h3obj.OBJECT_RANDOM_DWELLING_FACTION}:
        walker.skip(2)
    return {
        "payloadKind": "random_dwelling",
        "dwellingFamily": h3obj.random_dwelling_family(object_id),
        "owner": owner,
        "identifier": identifier,
        "ownerEncoding": "h3m_readPlayer32",
        "payloadDecoderEvidence": h3obj.PAYLOAD_DECODER_EVIDENCE["random_dwelling"],
    }


def skip_seer_reward(walker: Walker, reward_type: int, *, h3m_version: int) -> None:
    read_seer_reward(walker, reward_type, h3m_version=h3m_version)


def read_seer_reward(
    walker: Walker, reward_type: int, *, h3m_version: int
) -> dict[str, Any]:
    """Decode Seer hut reward payloads used by campaign/procedural emit."""
    if reward_type == 0:
        return {"rewardType": 0}
    if reward_type == 1:
        return {"rewardType": 1, "experience": walker.read_u32()}
    if reward_type == 2:
        return {"rewardType": 2, "mana": walker.read_u32()}
    if reward_type == 3:
        return {"rewardType": 3, "morale": walker.read_u8()}
    if reward_type == 4:
        return {"rewardType": 4, "luck": walker.read_u8()}
    if reward_type == 5:
        return {
            "rewardType": 5,
            "resourceType": walker.read_u8(),
            "resourceAmount": walker.read_u32(),
        }
    if reward_type == 6:
        return {
            "rewardType": 6,
            "primarySkill": walker.read_u8(),
            "primarySkillAmount": walker.read_u8(),
        }
    if reward_type == 7:
        return {
            "rewardType": 7,
            "secondarySkill": walker.read_u8(),
            "secondaryMastery": walker.read_u8(),
        }
    if reward_type == 8:
        artifact_id = walker.skip_artifact16()
        if h3m_version == h3m.H3M_VERSION_HOTA:
            walker.skip(2)
        return {"rewardType": 8, "artifactId": artifact_id}
    if reward_type == 9:
        return {"rewardType": 9, "spellId": walker.read_u8()}
    if reward_type == 10:
        return {
            "rewardType": 10,
            "creatureType": walker.read_u16(),
            "creatureCount": walker.read_u16(),
        }
    raise ValueError(f"unsupported seer hut reward type {reward_type}")


def skip_quest_mission(walker: Walker, mission_id: int, *, h3m_version: int) -> None:
    read_quest_mission(walker, mission_id, h3m_version=h3m_version)


def read_quest_mission(
    walker: Walker, mission_id: int, *, h3m_version: int
) -> dict[str, Any]:
    """Decode quest mission payloads; keep full structure for Seer emit (types 3–7)."""
    if mission_id == 0:
        return {}
    if mission_id == 1:
        return {"experienceLevel": walker.read_u32()}
    if mission_id == 2:
        return {
            "primarySkills": {
                "attack": walker.read_u8(),
                "defense": walker.read_u8(),
                "spellPower": walker.read_u8(),
                "knowledge": walker.read_u8(),
            }
        }
    if mission_id in {3, 4}:
        return {"targetAbsodId": walker.read_u32()}
    if mission_id == 5:
        art_number = walker.read_u8()
        artifact_bytes = 4 if h3m_version == h3m.H3M_VERSION_HOTA else 2
        artifacts: list[int] = []
        for _ in range(art_number):
            if artifact_bytes == 2:
                artifacts.append(walker.read_u16())
            else:
                artifacts.append(walker.read_u32())
        return {"requiredArtifacts": artifacts}
    if mission_id == 6:
        type_number = walker.read_u8()
        creatures: list[dict[str, int]] = []
        for _ in range(type_number):
            creatures.append(
                {"creatureType": walker.read_u16(), "count": walker.read_u16()}
            )
        return {"requiredCreatures": creatures}
    if mission_id == 7:
        return {"requiredResources": walker.read_resources()}
    if mission_id == 8:
        return {"requiredHeroId": walker.read_u8()}
    if mission_id == 9:
        return {"requiredPlayerColor": walker.read_u8()}
    if mission_id == 10:
        mission_sub_id = walker.read_u32()
        payload: dict[str, Any] = {"hotaMissionSubId": mission_sub_id}
        if mission_sub_id == 0:
            hero_class_count = walker.read_u32()
            if hero_class_count > 256:
                raise ValueError(
                    f"implausible HotA quest hero-class count {hero_class_count}"
                )
            walker.skip((hero_class_count + 7) // 8)
        elif mission_sub_id == 1:
            payload["value"] = walker.read_u32()
        elif mission_sub_id == 2:
            payload["value"] = walker.read_u32()
        elif mission_sub_id == 3:
            payload["value"] = walker.read_u32()
            payload["flag"] = walker.read_u8()
        else:
            raise ValueError(f"unsupported HotA quest mission sub-id {mission_sub_id}")
        return payload
    raise ValueError(f"unsupported quest mission id {mission_id}")


def skip_quest(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    mission_id = walker.read_u8()
    if mission_id == 0:
        return {"missionType": mission_id}
    mission_payload = read_quest_mission(
        walker, mission_id, h3m_version=record["h3mVersion"]
    )
    last_day = walker.read_i32()
    first_visit = walker.read_string()
    next_visit = walker.read_string()
    completed = walker.read_string()
    return {
        "missionType": mission_id,
        **mission_payload,
        "lastDay": last_day,
        "firstVisitText": first_visit,
        "nextVisitText": next_visit,
        "completedText": completed,
    }


def skip_seer_hut_quest(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    if record["h3mVersion"] >= h3m.H3M_VERSION_AB:
        quest = skip_quest(walker, record)
        mission_type = quest["missionType"]
    else:
        artifact_id = walker.skip_artifact16()
        mission_type = 5 if artifact_id != ARTIFACT_NONE_U16 else 0
        quest = {
            "missionType": mission_type,
            "requiredArtifact": artifact_id,
            "requiredArtifacts": [artifact_id] if mission_type == 5 else [],
        }
    if mission_type != 0:
        reward_type = walker.read_u8()
        reward = read_seer_reward(
            walker, reward_type, h3m_version=record["h3mVersion"]
        )
        quest["rewardType"] = reward_type
        quest["reward"] = reward
    else:
        walker.skip(1)
    return quest


def skip_seer_hut(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    if record["h3mVersion"] == h3m.H3M_VERSION_HOTA:
        quest_count = walker.read_u32()
        if quest_count > 64:
            raise ValueError(
                f"implausible HotA seer-hut quest count {quest_count} at {record['recordOffset']}"
            )
        quests = [skip_seer_hut_quest(walker, record) for _ in range(quest_count)]
        repeatable_count = walker.read_u32()
        if repeatable_count > 64:
            raise ValueError(
                f"implausible HotA repeatable seer-hut quest count {repeatable_count} "
                f"at {record['recordOffset']}"
            )
        repeatable = [skip_seer_hut_quest(walker, record) for _ in range(repeatable_count)]
        walker.skip(2)
        return {
            "payloadKind": "seer_hut",
            "quests": quests,
            "repeatableQuests": repeatable,
            "payloadDecoderEvidence": h3obj.PAYLOAD_DECODER_EVIDENCE["seer_hut"],
        }
    quest = skip_seer_hut_quest(walker, record)
    walker.skip(2)
    return {
        "payloadKind": "seer_hut",
        "quest": quest,
        "payloadDecoderEvidence": h3obj.PAYLOAD_DECODER_EVIDENCE["seer_hut"],
    }


ROE_CAMPAIGN_BRIEFING_GAP_PREFIXES = (
    b"\x00\x00\xfb",
    b"\x00\xfb\x00",
    b"\xfb\x00\x00",
)
ROE_CAMPAIGN_BRIEFING_ZERO_BLOCK_BYTES = 24
ROE_CAMPAIGN_BRIEFING_MAX_LAST_DAY = 1_000_000
ROE_CAMPAIGN_BRIEFING_MAX_STRING_LENGTH = 8_192


def _matches_roe_campaign_briefing_gap_prefix(data: bytes, offset: int) -> bool:
    if offset + 3 > len(data):
        return False
    return data[offset : offset + 3] in ROE_CAMPAIGN_BRIEFING_GAP_PREFIXES


def _peek_u32(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=True)


def _peek_briefing_string_length(data: bytes, offset: int) -> int:
    return int.from_bytes(data[offset : offset + 4], "little", signed=False)


def _roe_campaign_briefing_tail_byte_length(data: bytes, start: int) -> int | None:
    if start + 8 > len(data):
        return None
    if _matches_roe_campaign_briefing_gap_prefix(data, start):
        return None
    last_day = _peek_u32(data, start)
    if last_day < 0 or last_day > ROE_CAMPAIGN_BRIEFING_MAX_LAST_DAY:
        return None
    offset = start + 4
    for _ in range(3):
        if offset + 4 > len(data):
            return None
        string_length = _peek_briefing_string_length(data, offset)
        if string_length > ROE_CAMPAIGN_BRIEFING_MAX_STRING_LENGTH:
            return None
        offset += 4 + string_length
        if offset > len(data):
            return None
    if offset + 3 > len(data):
        return None
    reward_type = data[offset]
    offset += 1
    try:
        reward_walker = Walker(data)
        reward_walker.seek(offset)
        skip_seer_reward(
            reward_walker,
            reward_type,
            h3m_version=h3m.H3M_VERSION_ROE,
        )
        offset = reward_walker.tell()
    except ValueError:
        return None
    offset += 2
    if offset > len(data):
        return None
    return offset - start


def can_parse_roe_campaign_briefing_tail(walker: Walker) -> bool:
    return _roe_campaign_briefing_tail_byte_length(walker.data, walker.tell()) is not None


def _looks_like_synthetic_roe_campaign_briefing(data: bytes, offset: int) -> bool:
    walker = Walker(data)
    walker.seek(offset)
    if can_parse_roe_campaign_briefing_zero_block(walker):
        return True
    walker.seek(offset)
    if can_parse_roe_campaign_briefing_gap(walker):
        return True
    walker.seek(offset)
    return can_parse_roe_campaign_briefing_tail(walker)


def _looks_like_false_object_header_for_briefing(
    data: bytes,
    offset: int,
    summary: h3m.H3MShapeSummary,
    templates: list[dict[str, Any]],
) -> bool:
    if offset + 12 > len(data):
        return False
    x, y, z = data[offset], data[offset + 1], data[offset + 2]
    template_index = int.from_bytes(data[offset + 3 : offset + 7], "little", signed=False)
    if not (x == 0 and y == 0 and z == 0 and template_index == 0):
        return False
    if template_index >= len(templates):
        return False
    object_id = templates[template_index].get("objectId")
    if object_id not in h3obj.MONSTER_OBJECT_IDS:
        return False
    return _looks_like_synthetic_roe_campaign_briefing(data, offset)


def can_parse_roe_campaign_briefing_gap(walker: Walker) -> bool:
    start = walker.tell()
    if not _matches_roe_campaign_briefing_gap_prefix(walker.data, start):
        return False
    for end in range(start + 16, min(start + 28, len(walker.data) - 8)):
        if can_parse_roe_campaign_briefing_tail_at(walker.data, end):
            return True
    return False


def can_parse_roe_campaign_briefing_zero_block(walker: Walker) -> bool:
    start = walker.tell()
    end = start + ROE_CAMPAIGN_BRIEFING_ZERO_BLOCK_BYTES
    if end > len(walker.data):
        return False
    if walker.data[start:end] != b"\x00" * ROE_CAMPAIGN_BRIEFING_ZERO_BLOCK_BYTES:
        return False
    return can_parse_roe_campaign_briefing_gap_at(walker.data, end) or can_parse_roe_campaign_briefing_tail_at(
        walker.data, end
    )


def can_parse_roe_campaign_briefing_tail_at(data: bytes, offset: int) -> bool:
    walker = Walker(data)
    walker.seek(offset)
    return can_parse_roe_campaign_briefing_tail(walker)


def can_parse_roe_campaign_briefing_gap_at(data: bytes, offset: int) -> bool:
    walker = Walker(data)
    walker.seek(offset)
    return can_parse_roe_campaign_briefing_gap(walker)


def skip_roe_campaign_briefing_tail(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    if not can_parse_roe_campaign_briefing_tail(walker):
        raise ValueError(
            f"record {record['index']} ROE campaign briefing tail failed shape check at 0x{walker.tell():x}"
        )
    last_day = walker.read_i32()
    first_visit = walker.read_string(max_length=ROE_CAMPAIGN_BRIEFING_MAX_STRING_LENGTH)
    next_visit = walker.read_string(max_length=ROE_CAMPAIGN_BRIEFING_MAX_STRING_LENGTH)
    completed = walker.read_string(max_length=ROE_CAMPAIGN_BRIEFING_MAX_STRING_LENGTH)
    reward_type = walker.read_u8()
    skip_seer_reward(walker, reward_type, h3m_version=h3m.H3M_VERSION_ROE)
    walker.skip(2)
    return {
        "payloadKind": "roe_campaign_briefing",
        "syntheticHeader": True,
        "lastDay": last_day,
        "firstVisitText": first_visit,
        "nextVisitText": next_visit,
        "completedText": completed,
        "rewardType": reward_type,
        "payloadDecoderEvidence": h3obj.PAYLOAD_DECODER_EVIDENCE["roe_campaign_briefing"],
    }


def skip_roe_campaign_briefing_gap(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    start = walker.tell()
    if not _matches_roe_campaign_briefing_gap_prefix(walker.data, start):
        raise ValueError(
            f"record {record['index']} ROE campaign briefing gap missing prefix at 0x{start:x}"
        )
    end = None
    for candidate in range(start + 16, min(start + 28, len(walker.data) - 8)):
        if can_parse_roe_campaign_briefing_tail_at(walker.data, candidate):
            end = candidate
            break
    if end is None:
        raise ValueError(
            f"record {record['index']} ROE campaign briefing gap has no aligned tail at 0x{start:x}"
        )
    walker.seek(end)
    return {
        "payloadKind": "roe_campaign_briefing_gap",
        "syntheticHeader": True,
        "gapBytes": end - start,
        "payloadDecoderEvidence": h3obj.PAYLOAD_DECODER_EVIDENCE["roe_campaign_briefing_gap"],
    }


def skip_roe_campaign_briefing_zero_block(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    start = walker.tell()
    end = start + ROE_CAMPAIGN_BRIEFING_ZERO_BLOCK_BYTES
    if walker.data[start:end] != b"\x00" * ROE_CAMPAIGN_BRIEFING_ZERO_BLOCK_BYTES:
        raise ValueError(
            f"record {record['index']} ROE campaign briefing zero block failed shape check at 0x{start:x}"
        )
    walker.seek(end)
    return {
        "payloadKind": "roe_campaign_briefing_zero_block",
        "syntheticHeader": True,
        "zeroBlockBytes": ROE_CAMPAIGN_BRIEFING_ZERO_BLOCK_BYTES,
        "payloadDecoderEvidence": h3obj.PAYLOAD_DECODER_EVIDENCE["roe_campaign_briefing_zero_block"],
    }


def _make_synthetic_briefing_record(
    index: int,
    offset: int,
    *,
    payload_kind: str,
) -> dict[str, Any]:
    return {
        "index": index,
        "recordOffset": f"0x{offset:x}",
        "x": None,
        "y": None,
        "z": None,
        "layer": None,
        "key": "synthetic:roe_campaign_briefing",
        "templateIndex": None,
        "templateAnimation": None,
        "templateBlockMask": None,
        "templateVisitMask": None,
        "templateObjectId": h3obj.OBJECT_ROE_CAMPAIGN_BRIEFING,
        "templateSubtype": None,
        "syntheticHeader": True,
        "payloadKind": payload_kind,
    }


def _global_timed_events_at_offset(data: bytes, offset: int, *, h3m_version: int) -> dict[str, Any] | None:
    import h3m_global_events as global_events

    return global_events.try_read_global_timed_events(data, offset, h3m_version=h3m_version)


def _try_decode_synthetic_roe_campaign_briefing(
    walker: Walker,
    summary: h3m.H3MShapeSummary,
    index: int,
    start: int,
) -> dict[str, Any] | None:
    if summary.version < h3m.H3M_VERSION_AB or is_hota_map_version(summary.version):
        return None
    # Global timed events share string-shaped bytes with the synthetic briefing
    # heuristic. Prefer the post-object event table whenever it decodes cleanly.
    if _global_timed_events_at_offset(walker.data, start, h3m_version=summary.version) is not None:
        return None
    walker.seek(start)
    if can_parse_roe_campaign_briefing_zero_block(walker):
        record = _make_synthetic_briefing_record(index, start, payload_kind="roe_campaign_briefing_zero_block")
        record["h3mVersion"] = summary.version
        payload = skip_roe_campaign_briefing_zero_block(walker, record)
        record.update(payload)
        return record
    walker.seek(start)
    if can_parse_roe_campaign_briefing_gap(walker):
        record = _make_synthetic_briefing_record(index, start, payload_kind="roe_campaign_briefing_gap")
        record["h3mVersion"] = summary.version
        payload = skip_roe_campaign_briefing_gap(walker, record)
        record.update(payload)
        return record
    walker.seek(start)
    if can_parse_roe_campaign_briefing_tail(walker):
        record = _make_synthetic_briefing_record(index, start, payload_kind="roe_campaign_briefing")
        record["h3mVersion"] = summary.version
        payload = skip_roe_campaign_briefing_tail(walker, record)
        record.update(payload)
        return record
    return None


def skip_quest_guard(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    quest = skip_quest(walker, record)
    return {"payloadKind": "quest_guard", "quest": quest}


def skip_border_gate(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    """Border gate (212): hybrid classic-empty vs quest decode (policy C3).

    Classic keymaster-style subtypes 0–7 are header-only on observed RoE/SoD maps
    (With Blinders On). HotA subtype 1000 carries a quest; unknown subtypes fail
    closed into the quest-guard reader rather than silent zero-byte.
    """
    subtype = int(record.get("templateSubtype") or 0)
    if subtype == 1000:
        quest_payload = skip_quest_guard(walker, record)
        return {
            "payloadKind": "border_gate",
            "classicKeymasterStyle": False,
            "templateSubtype": subtype,
            "quest": quest_payload.get("quest"),
            "payloadDecoderEvidence": h3obj.PAYLOAD_DECODER_EVIDENCE.get("seer_hut"),
        }
    if subtype == 1001 and is_hota_map_version(record["h3mVersion"]):
        content = walker.read_i32()
        if content != -1:
            walker.skip(4)
            walker.skip(4)
            walker.skip(1)
            walker.skip(5)
        else:
            walker.skip(14)
        return {"payloadKind": "hota_grave", "content": content}
    if 0 <= subtype <= 7:
        return {
            "payloadKind": "border_gate",
            "classicKeymasterStyle": True,
            "templateSubtype": subtype,
            "quest": None,
            "payloadDecoderEvidence": {
                "vcmiObject": "borderGate",
                "payloadShape": "no per-instance payload for classic keymaster subtypes 0-7",
                "status": "hybrid_c3_classic_empty",
                "h3mVersions": [h3m.H3M_VERSION_ROE, h3m.H3M_VERSION_AB, h3m.H3M_VERSION_SOD],
                "evidence": (
                    "With Blinders On SoD instances avxbgt00/avxbgt50 are header-only "
                    "(recordBytes=12); quest decode would desync"
                ),
            },
        }
    quest_payload = skip_quest_guard(walker, record)
    return {
        "payloadKind": "border_gate",
        "classicKeymasterStyle": False,
        "templateSubtype": subtype,
        "quest": quest_payload.get("quest"),
        "payloadDecoderEvidence": {
            "vcmiObject": "borderGate",
            "payloadShape": "quest blob (same family as quest guard)",
            "status": "hybrid_c3_quest_decode_unknown_subtype",
            "h3mVersions": [h3m.H3M_VERSION_ROE, h3m.H3M_VERSION_AB, h3m.H3M_VERSION_SOD],
        },
    }


def _skip_hero_ab_post_patrol(walker: Walker) -> dict[str, Any]:
    """AB biography/gender/spell tail after patrol radius has already been consumed."""

    has_custom_biography = False
    biography = None
    gender_raw = -1
    peek = walker.data[walker.tell()]
    if peek in (0, 1):
        has_custom_biography = walker.read_bool()
        biography = walker.read_string(max_length=4096) if has_custom_biography else None
        gender_raw = walker.read_i8()
    spell_byte = walker.read_u8()
    spell = spell_byte if spell_byte < 128 else spell_byte - 256
    walker.skip(16)
    return {
        "hasCustomBiography": has_custom_biography,
        "biography": biography,
        "genderRaw": gender_raw,
        "spell": spell,
    }


def _skip_hero_common(
    walker: Walker,
    record: dict[str, Any],
    *,
    has_identifier: bool,
    experience_gated: bool,
) -> dict[str, Any]:
    h3m_version = int(record["h3mVersion"])
    identifier = walker.read_u32() if has_identifier else None
    owner = walker.read_u8()
    hero_type = walker.read_u8()
    has_name = walker.read_bool()
    name = walker.read_string(max_length=256) if has_name else None
    if experience_gated:
        has_custom_experience = walker.read_bool()
        experience = walker.read_u32() if has_custom_experience else 0
    else:
        experience = walker.read_u32()
    has_portrait = walker.read_bool()
    portrait = walker.read_u8() if has_portrait else None
    has_secondary_skills = walker.read_bool()
    secondary_skills: list[dict[str, int]] = []
    if has_secondary_skills:
        secondary_skill_count = walker.read_u32()
        if secondary_skill_count > 64:
            raise ValueError(f"implausible hero secondary skill count {secondary_skill_count} at {record['recordOffset']}")
        secondary_skills = walker.read_secondary_skills(secondary_skill_count)
    else:
        secondary_skill_count = 0
    has_garrison = walker.read_bool()
    garrison_stacks = walker.read_creature_set(h3m_version=h3m_version) if has_garrison else []
    formation = walker.read_u8()
    artifact_set = walker.read_hero_artifact_set(h3m_version=h3m_version)
    if artifact_set["backpackArtifactCount"] > 128:
        raise ValueError(
            f"implausible hero backpack artifact count {artifact_set['backpackArtifactCount']} at {record['recordOffset']}"
        )
    patrol_radius = walker.read_u8()
    result: dict[str, Any] = {
        "payloadKind": "hero_or_prison",
        "identifier": f"0x{identifier:08x}" if identifier is not None else None,
        "owner": owner,
        "heroType": hero_type,
        "hasName": has_name,
        "name": name,
        "experience": experience,
        "hasPortrait": has_portrait,
        "portrait": portrait,
        "secondarySkillCount": secondary_skill_count,
        "secondarySkills": secondary_skills,
        "hasGarrison": has_garrison,
        "garrisonStacks": garrison_stacks,
        "formation": formation,
        "hasArtifactSet": artifact_set["hasArtifactSet"],
        "equippedArtifacts": artifact_set["equippedArtifacts"],
        "backpackArtifacts": artifact_set["backpackArtifacts"],
        "backpackArtifactCount": artifact_set["backpackArtifactCount"],
        "patrolRadius": patrol_radius,
        "payloadDecoderEvidence": h3obj.PAYLOAD_DECODER_EVIDENCE["hero"],
    }
    if h3m_version < h3m.H3M_VERSION_AB:
        # RoE: patrol then 16 zero bytes. No biography/gender/spell.
        walker.skip(16)
        result.update({
            "hasCustomBiography": False,
            "biography": None,
            "genderRaw": -1,
            "spell": None,
        })
        return result
    if h3m_version < h3m.H3M_VERSION_SOD:
        result.update(_skip_hero_ab_post_patrol(walker))
        return result
    has_custom_biography = walker.read_bool()
    biography = walker.read_string(max_length=4096) if has_custom_biography else None
    gender_raw = walker.read_i8()
    has_custom_spells = walker.read_bool()
    custom_spells = walker.read_bitmask_bytes(SPELLS_BYTES) if has_custom_spells else None
    has_custom_primary = walker.read_bool()
    custom_primary: list[int] | None = None
    if has_custom_primary:
        custom_primary = [walker.read_u8() for _ in range(4)]
    walker.skip(16)
    hota_hero = None
    if h3m_version == h3m.H3M_VERSION_HOTA:
        hota_hero = {
            "alwaysAddSkills": walker.read_bool(),
            "cannotGainExperience": walker.read_bool(),
            "level": walker.read_i32(),
        }
    result.update({
        "hasCustomBiography": has_custom_biography,
        "biography": biography,
        "genderRaw": gender_raw,
        "hasCustomSpells": has_custom_spells,
        "customSpells": custom_spells,
        "hasCustomPrimary": has_custom_primary,
        "customPrimarySkills": custom_primary,
    })
    if hota_hero is not None:
        result["hota"] = hota_hero
    return result


def skip_hero(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    h3m_version = int(record["h3mVersion"])
    return _skip_hero_common(
        walker,
        record,
        has_identifier=h3m_version >= h3m.H3M_VERSION_AB,
        experience_gated=h3m_version >= h3m.H3M_VERSION_SOD,
    )


def _read_town_event_tail(walker: Walker, *, h3m_version: int) -> dict[str, Any]:
    hota: dict[str, Any] | None = None
    if h3m_version == h3m.H3M_VERSION_HOTA:
        hota = {
            "creatureGrowth8": walker.read_i32(),
            "amount": walker.read_i32(),
            "specialBuildingsMaskA": walker.read_i32(),
            "specialBuildingsMaskB": walker.read_i16(),
            "neutralAffected": walker.read_bool(),
        }
    buildings = walker.read_bitmask_bytes(BUILDINGS_BYTES)
    creature_growth = [walker.read_u16() for _ in range(7)]
    unknown_tail = walker.read_u32()
    result = {
        "eventBuildingsMask": buildings,
        "creatureGrowth": creature_growth,
        "unknownTail": unknown_tail,
    }
    if hota is not None:
        result["hota"] = hota
    return result


def _read_town_payload(
    walker: Walker,
    record: dict[str, Any],
    *,
    payload_kind: str,
    has_identifier: bool,
    has_obligatory_spells: bool,
    has_alignment: bool,
) -> dict[str, Any]:
    identifier = walker.read_u32() if has_identifier else None
    owner = walker.read_u8()
    has_name = walker.read_bool()
    name = walker.read_string(max_length=256) if has_name else None
    has_garrison = walker.read_bool()
    garrison_stacks = walker.read_creature_set(h3m_version=record["h3mVersion"]) if has_garrison else []
    formation = walker.read_u8()
    has_custom_buildings = walker.read_bool()
    built_buildings_mask = None
    forbidden_buildings_mask = None
    has_fort = None
    if has_custom_buildings:
        built_buildings_mask = walker.read_bitmask_bytes(BUILDINGS_BYTES)
        forbidden_buildings_mask = walker.read_bitmask_bytes(BUILDINGS_BYTES)
    else:
        has_fort = walker.read_bool()
    obligatory_spells = walker.read_bitmask_bytes(SPELLS_BYTES) if has_obligatory_spells else None
    available_spells = walker.read_bitmask_bytes(SPELLS_BYTES)
    spell_research_allowed = None
    special_buildings: list[int] = []
    if record["h3mVersion"] == h3m.H3M_VERSION_HOTA:
        spell_research_allowed = walker.read_bool()
        special_buildings_count = walker.read_u32()
        if special_buildings_count > 64:
            raise ValueError(
                f"implausible HotA special-building count {special_buildings_count} "
                f"at {record['recordOffset']}"
            )
        special_buildings = [walker.read_u8() for _ in range(special_buildings_count)]
    events: list[dict[str, Any]] = []
    events_count = walker.read_u32()
    if events_count > 256:
        raise ValueError(f"implausible town event count {events_count} at {record['recordOffset']}")
    for _ in range(events_count):
        event = walker.skip_event_common(h3m_version=record["h3mVersion"])
        event.update(_read_town_event_tail(walker, h3m_version=record["h3mVersion"]))
        events.append(event)
    alignment = walker.read_u8() if has_alignment else None
    tail_zero = bytes(walker.data[walker.tell() : walker.tell() + 3])
    walker.skip(3)
    if tail_zero != b"\x00\x00\x00":
        raise ValueError(f"nonzero town tail bytes at {record['recordOffset']}: {tail_zero.hex()}")
    return {
        "payloadKind": payload_kind,
        "identifier": f"0x{identifier:08x}" if identifier is not None else None,
        "owner": owner,
        "hasName": has_name,
        "name": name,
        "hasGarrison": has_garrison,
        "garrisonStacks": garrison_stacks,
        "formation": formation,
        "hasCustomBuildings": has_custom_buildings,
        "builtBuildingsMask": built_buildings_mask,
        "forbiddenBuildingsMask": forbidden_buildings_mask,
        "hasFort": has_fort,
        "obligatorySpells": obligatory_spells,
        "availableSpells": available_spells,
        "spellResearchAllowed": spell_research_allowed,
        "specialBuildings": special_buildings,
        "townEventCount": events_count,
        "townEvents": events,
        "alignment": alignment,
    }


def skip_town(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    h3m_version = record["h3mVersion"]
    return _read_town_payload(
        walker,
        record,
        payload_kind="town",
        has_identifier=h3m_version >= h3m.H3M_VERSION_AB,
        has_obligatory_spells=h3m_version >= h3m.H3M_VERSION_AB,
        has_alignment=h3m_version >= h3m.H3M_VERSION_SOD,
    )


def skip_random_town(walker: Walker, record: dict[str, Any]) -> dict[str, Any]:
    h3m_version = record["h3mVersion"]
    return _read_town_payload(
        walker,
        record,
        payload_kind="random_town",
        has_identifier=h3m_version >= h3m.H3M_VERSION_AB,
        has_obligatory_spells=h3m_version >= h3m.H3M_VERSION_AB,
        has_alignment=h3m_version >= h3m.H3M_VERSION_SOD,
    )


def resolve_payload_skipper(
    object_id: int,
    record: dict[str, Any],
) -> Callable[[Walker, dict[str, Any]], dict[str, Any]] | None:
    if object_id == h3obj.OBJECT_BORDER_GATE:
        return skip_border_gate
    if object_id in {h3obj.OBJECT_MINE, h3obj.OBJECT_ABANDONED_MINE}:
        return skip_mine_family
    if object_id == h3obj.OBJECT_GRAIL:
        return skip_grail
    if object_id in h3obj.REWARD_WITH_GARBAGE_OBJECT_IDS:
        return skip_hota_reward_with_garbage
    if object_id in h3obj.REWARD_WITH_ARTIFACT_OBJECT_IDS:
        return skip_hota_reward_with_artifact
    if object_id in {
        h3obj.OBJECT_CAMPFIRE,
        h3obj.OBJECT_LEAN_TO,
        h3obj.OBJECT_WAGON,
    }:
        return skip_hota_resource_reward
    if object_id in h3obj.CREATURE_BANK_OBJECT_IDS:
        return skip_hota_creature_bank
    if object_id == h3obj.OBJECT_PYRAMID:
        return lambda walker, record: skip_hota_fixed_extension(
            walker,
            record,
            byte_count=8,
            payload_kind="hota_pyramid_reward",
        )
    if object_id == h3obj.OBJECT_BLACK_MARKET:
        return lambda walker, record: skip_hota_fixed_extension(
            walker,
            record,
            byte_count=28,
            payload_kind="hota_black_market",
        )
    if object_id == h3obj.OBJECT_UNIVERSITY:
        return lambda walker, record: skip_hota_fixed_extension(
            walker,
            record,
            byte_count=8,
            payload_kind="hota_university",
        )
    if object_id == h3obj.OBJECT_HOTA_CUSTOM_1:
        subtype = int(record.get("templateSubtype") or 0)
        byte_count = 18 if subtype in (0, 1) else 8
        return lambda walker, record: skip_hota_fixed_extension(
            walker,
            record,
            byte_count=byte_count,
            payload_kind="hota_custom_reward_1",
        )
    if object_id == h3obj.OBJECT_HOTA_CUSTOM_2 and int(record.get("templateSubtype") or 0) == 0:
        return lambda walker, record: skip_hota_fixed_extension(
            walker,
            record,
            byte_count=8,
            payload_kind="hota_seafaring_academy",
        )
    if object_id == h3obj.OBJECT_HOTA_CUSTOM_3 and int(record.get("templateSubtype") or 0) == 12:
        return lambda walker, record: skip_hota_fixed_extension(
            walker,
            record,
            byte_count=16,
            payload_kind="hota_trapper_lodge",
        )
    return SKIPPERS.get(object_id)


SKIPPERS: dict[int, Callable[[Walker, dict[str, Any]], dict[str, Any]]] = {
    h3obj.OBJECT_EVENT: skip_event,
    **{object_id: skip_monster for object_id in h3obj.MONSTER_OBJECT_IDS},
    **{object_id: skip_hero for object_id in h3obj.HERO_OBJECT_IDS},
    h3obj.OBJECT_OCEAN_BOTTLE: skip_ocean_bottle,
    h3obj.OBJECT_SIGN: skip_sign,
    **{object_id: skip_creature_generator for object_id in h3obj.FIXED_CREATURE_GENERATOR_IDS},
    **{object_id: skip_artifact for object_id in h3obj.ARTIFACT_OBJECT_IDS},
    h3obj.OBJECT_RESOURCE: skip_resource,
    h3obj.OBJECT_RANDOM_RESOURCE: skip_resource,
    h3obj.OBJECT_TOWN: skip_town,
    h3obj.OBJECT_RANDOM_TOWN: skip_random_town,
    h3obj.OBJECT_LIGHTHOUSE: skip_lighthouse,
    h3obj.OBJECT_SHIPYARD: skip_shipyard,
    h3obj.OBJECT_SCHOLAR: skip_scholar,
    h3obj.OBJECT_WITCH_HUT: skip_witch_hut,
    h3obj.OBJECT_PANDORAS_BOX: skip_pandora,
    h3obj.OBJECT_SPELL_SCROLL: skip_spell_scroll,
    **{object_id: skip_shrine for object_id in h3obj.SHRINE_OBJECT_IDS},
    **{object_id: skip_garrison for object_id in h3obj.GARRISON_OBJECT_IDS},
    h3obj.OBJECT_SEER_HUT: skip_seer_hut,
    h3obj.OBJECT_QUEST_GUARD: skip_quest_guard,
    h3obj.OBJECT_HERO_PLACEHOLDER: skip_hero_placeholder,
    **{object_id: skip_random_dwelling for object_id in h3obj.RANDOM_DWELLING_IDS},
}


def validate_generic_walk(walk: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    table = walk["objectTable"]
    if walk.get("silentFallbacksUsed"):
        errors.append("silentFallbacksUsed must be false")
    if not table["complete"]:
        stop = table.get("unsupportedStop") or {}
        errors.append(stop.get("error") or "object walk stopped before declared count")

    format_assumption = walk.get("formatAssumption") or {}
    evidence = format_assumption.get("noPayloadObjectEvidence")
    allowed_ids = format_assumption.get("noPayloadObjectIds")
    if not isinstance(evidence, dict) or not isinstance(allowed_ids, list):
        errors.append("no-payload allowlist and evidence must be present")
    else:
        expected_ids = {str(value) for value in allowed_ids}
        if {str(key) for key in evidence} != expected_ids:
            errors.append("no-payload evidence keys must exactly match the positive allowlist")
    for record in walk.get("records") or []:
        if not isinstance(record, dict) or record.get("payloadKind") != OBJECT_GENERIC_NO_PAYLOAD:
            continue
        object_id = record.get("templateObjectId")
        record_evidence = record.get("noPayloadEvidence")
        if not isinstance(object_id, int) or object_id not in h3obj.NO_PAYLOAD_OBJECT_IDS:
            errors.append(f"generic record lacks a positive no-payload allowlist entry: {object_id!r}")
        if not isinstance(record_evidence, dict):
            errors.append(f"generic record lacks no-payload evidence: {record.get('index')!r}")
        elif record_evidence.get("payloadShape") != "no per-instance payload":
            errors.append(f"generic record has malformed no-payload evidence: {record.get('index')!r}")
        elif record.get("h3mVersion") not in (record_evidence.get("h3mVersions") or []):
            errors.append(f"generic record lacks version-specific no-payload evidence: {record.get('index')!r}")
    return {
        "schema": "homm3.h3m_object_walk.validation.v0",
        "result": "PASS" if not errors else "FAIL",
        "errors": errors,
        "warnings": [],
        "checkedInvariants": {
            "declaredObjectRecords": table["declaredCount"],
            "decodedObjectRecords": table["decodedCount"],
            "unsupportedStop": table["unsupportedStop"],
        },
    }


def make_source_metadata(path: str | Path | None = None, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    source: dict[str, Any] = {
        "format": "h3m",
        "coordinateSystem": "heroes3_square_tile_xyz",
        "nodeKey": "layer:x:y",
    }
    if path is not None:
        source["path"] = str(path)
    if extra:
        source.update(extra)
    return source


def compact_h3m_summary(summary: h3m.H3MShapeSummary) -> dict[str, Any]:
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
    }


def _walk_objects_partial(
    data: bytes,
    summary: h3m.H3MShapeSummary,
    templates: list[dict[str, Any]],
    source_metadata: dict[str, Any] | None = None,
    *,
    include_records: bool = True,
) -> dict[str, Any]:
    walker = Walker(data)
    walker.seek(summary.object_table_offset)
    declared = walker.read_u32()
    if declared != summary.object_count:
        raise ValueError(f"object count mismatch {declared} != {summary.object_count}")
    records: list[dict[str, Any]] = []
    decoded_count = 0
    unsupported: dict[str, Any] | None = None
    stopped_at_global_timed_events = False
    for index in range(declared):
        start = walker.tell()
        record: dict[str, Any] | None = None
        # Some RoE campaign maps declare extra object slots past the real table;
        # the trailing bytes are the global timed-event section (Steadwick).
        if _global_timed_events_at_offset(walker.data, start, h3m_version=summary.version) is not None:
            walker.seek(start)
            stopped_at_global_timed_events = True
            break
        if (
            summary.version >= h3m.H3M_VERSION_AB
            and not is_hota_map_version(summary.version)
            and _looks_like_false_object_header_for_briefing(walker.data, start, summary, templates)
        ):
            walker.seek(start)
            synthetic = _try_decode_synthetic_roe_campaign_briefing(walker, summary, index, start)
            if synthetic is not None:
                synthetic["recordEndOffset"] = f"0x{walker.tell():x}"
                synthetic["recordBytes"] = walker.tell() - start
                decoded_count += 1
                if include_records:
                    records.append(synthetic)
                continue
        try:
            walker.seek(start)
            record = parse_header(walker, summary, templates, index)
            record["h3mVersion"] = summary.version
            object_id = record["templateObjectId"]
            skipper = resolve_payload_skipper(object_id, record)
            if skipper is None:
                unsupported_reason = h3obj.unsupported_payload_reason(object_id)
                if unsupported_reason is not None:
                    raise UnsupportedObjectPayload(
                        "unsupported_known_object_family",
                        f"record {index} object id {object_id}: {unsupported_reason}",
                    )
                if not h3obj.is_no_payload_object(object_id):
                    raise UnsupportedObjectPayload(
                        "unsupported_object_id",
                        f"record {index} object id {object_id} has no payload decoder or no-payload allowlist entry",
                    )
                skipper = skip_generic
            payload = skipper(walker, record)
            record.update(payload)
            record["recordEndOffset"] = f"0x{walker.tell():x}"
            record["recordBytes"] = walker.tell() - start
            decoded_count += 1
            if include_records:
                records.append(record)
        except Exception as exc:
            walker.seek(start)
            if _global_timed_events_at_offset(walker.data, start, h3m_version=summary.version) is not None:
                walker.seek(start)
                stopped_at_global_timed_events = True
                break
            synthetic = _try_decode_synthetic_roe_campaign_briefing(walker, summary, index, start)
            if synthetic is not None:
                synthetic["recordEndOffset"] = f"0x{walker.tell():x}"
                synthetic["recordBytes"] = walker.tell() - start
                decoded_count += 1
                if include_records:
                    records.append(synthetic)
                continue
            status = exc.status if isinstance(exc, UnsupportedObjectPayload) else "decoder_error"
            unsupported = {
                "index": index,
                "recordOffset": f"0x{start:x}",
                "decoderStatus": status,
                "error": str(exc),
            }
            if record is not None:
                unsupported["record"] = record
            break
    return {
        "schema": "homm3.h3m_object_walk.v0",
        "source": source_metadata or make_source_metadata(),
        "h3m": compact_h3m_summary(summary),
        "formatAssumption": {
            "h3mVersion": summary.version,
            "vcmiFeatureLevel": "version_gated_roe_ab_sod_subset",
            "resourcesCount": RESOURCES_COUNT,
            "spellsBytes": SPELLS_BYTES,
            "buildingsBytes": BUILDINGS_BYTES,
            "randomTownDecoder": "vcmi_readTown_version_gated",
            "noPayloadObjectIds": sorted(h3obj.NO_PAYLOAD_OBJECT_IDS),
            "noPayloadObjectEvidence": h3obj.NO_PAYLOAD_OBJECT_EVIDENCE,
            "h3mObjectRegistry": {
                "vcmiEntityIdentifiers": h3obj.VCMI_ENTITY_IDENTIFIERS_URL,
                "vcmiMapFormatH3M": h3obj.VCMI_MAP_FORMAT_H3M_URL,
                "monsterObjectIds": sorted(h3obj.MONSTER_OBJECT_IDS),
                "artifactObjectIds": sorted(h3obj.ARTIFACT_OBJECT_IDS),
                "fixedCreatureGeneratorIds": sorted(h3obj.FIXED_CREATURE_GENERATOR_IDS),
                "randomDwellingIds": sorted(h3obj.RANDOM_DWELLING_IDS),
                "unsupportedKnownObjectIds": sorted(h3obj.UNSUPPORTED_KNOWN_OBJECTS),
            },
        },
        "objectTable": {
            "objectTableOffset": f"0x{summary.object_table_offset:x}",
            "declaredCount": declared,
            "decodedCount": decoded_count,
            "walkEndOffset": f"0x{walker.tell():x}",
            "unsupportedStop": unsupported,
            "complete": unsupported is None,
            "stoppedAtPostObjectGlobalTimedEvents": stopped_at_global_timed_events,
            "declaredDecodedDelta": (declared - decoded_count) if stopped_at_global_timed_events else 0,
        },
        "records": records if include_records else [],
        "silentFallbacksUsed": False,
    }


def probe_walk_objects(
    data: bytes,
    summary: h3m.H3MShapeSummary,
    templates: list[dict[str, Any]],
    source_metadata: dict[str, Any] | None = None,
    *,
    include_records: bool = True,
) -> dict[str, Any]:
    return _walk_objects_partial(
        data,
        summary,
        templates,
        source_metadata,
        include_records=include_records,
    )


def walk_objects(
    data: bytes,
    summary: h3m.H3MShapeSummary,
    templates: list[dict[str, Any]],
    source_metadata: dict[str, Any] | None = None,
    *,
    include_records: bool = True,
) -> dict[str, Any]:
    walk = probe_walk_objects(
        data,
        summary,
        templates,
        source_metadata,
        include_records=include_records,
    )
    if not walk["objectTable"]["complete"]:
        raise H3MObjectWalkIncomplete(walk)
    import h3m_global_events as global_events

    return global_events.attach_global_timed_events(walk, data)


def probe_h3m_file(path: str | Path, *, include_records: bool = True) -> dict[str, Any]:
    data = read_h3m_bytes(path)
    summary, templates = read_h3m_summary_and_templates(data)
    return probe_walk_objects(
        data,
        summary,
        templates,
        make_source_metadata(path, {"compressedInput": Path(path).read_bytes().startswith(b"\x1f\x8b")}),
        include_records=include_records,
    )


def walk_h3m_file(path: str | Path, *, include_records: bool = True) -> dict[str, Any]:
    data = read_h3m_bytes(path)
    summary, templates = read_h3m_summary_and_templates(data)
    return walk_objects(
        data,
        summary,
        templates,
        make_source_metadata(path, {"compressedInput": Path(path).read_bytes().startswith(b"\x1f\x8b")}),
        include_records=include_records,
    )


def build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Fail-closed H3M object table walker")
    parser.add_argument("--input", required=True, help="Standalone .h3m path")
    parser.add_argument("--output", help="Optional JSON output path; stdout is used when omitted")
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Emit compact walk metadata without the decoded records array",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_cli_parser().parse_args(argv)
    walk = probe_h3m_file(args.input, include_records=not args.summary_only)
    payload = json.dumps(walk, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0 if walk["objectTable"]["complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
