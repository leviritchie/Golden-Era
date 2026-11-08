"""Native Olden Era map emission for generated procedural scenarios.

The existing campaign proof-of-concept serializer uses the correct container
shape, but ``gzip.compress`` records wall-clock time.  This module owns a small
compatible codec whose output is reproducible byte-for-byte.
"""

from __future__ import annotations

import copy
import gzip
import hashlib
import json
import re
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .native_properties import construction_sid_for_faction, property_rows


ARRAY_KEYS = (
    "tilesMap",
    "levelsMap",
    "climbsMap",
    "roadsMap",
    "waterMap",
    "customAreasPainting",
)
MAP_SID_PATTERN = re.compile(r"^proc_[a-z0-9][a-z0-9_]{2,79}$")
# Core.zip Lang folder names that ship customMaps.json. Keep this explicit so
# quest LocKit upserts cannot silently skip a locale and leave LOC: placeholders.
CORE_CUSTOM_MAPS_LOCALES = (
    "BRportugese",
    "czech",
    "english",
    "french",
    "german",
    "hungarian",
    "italian",
    "japanese",
    "korean",
    "polish",
    "russian",
    "spanish",
    "turkish",
    "ukrainian",
    "zhCN",
    "zhTW",
)
# These are the serialized fields on the native ``ObjectsProperties`` data
# object. Unity's JSON reader leaves omitted list fields as ``null``; the map
# loader then walks them during object initialization. Even when a scenario
# has no rows for a family, emit an empty list so the managed object has the
# same non-null shape as a map saved by the editor.
NATIVE_OBJECT_PROPERTY_KEYS = (
    "propsName",
    "propComments",
    "propSpawns",
    "propCities",
    "propHeroes",
    "propRandomSquads",
    "propRandomItems",
    "propRandomHires",
    "propOwners",
    "propResources",
    "propSquads",
    "propDialogWindows",
    "propPortals",
    "propQuestNames",
    "propMainObjects",
    "propActionsLegacy",
    "propVariants",
    "propActionsBefore",
    "propActionsAfter",
    "propEntities",
    "propAiIntetactions",
    "propRewardParams",
    "propResParams",
    "propMarkers",
    "propGrowthUnits",
    "propActivations",
    "propNoCombineGeometries",
    "propCitiesHold",
    "propQuestMarkers",
)

# Procedural maps own their rules. In particular, native mapWinConditions stay
# empty so the compiled GameVictory action is the only victory path.
SCENARIO_SETTINGS = {
    "aiDifficulties": [True] * 6,
    "astrologyExpModifier": 1.0,
    "bonuses": [],
    "cantRewriteTurnMode": False,
    "customAISid": "",
    "customHeroMaxLevel": -1,
    "disableAutoBattleAgainstEnemyHeroes": True,
    "disableFactionLaws": False,
    "disableMagicCustomLearning": False,
    "disableMagicGuild": False,
    "disableWeekEffect": False,
    "economicDifficulties": [True] * 6,
    "enableCustomAI": False,
    "enableCustomHeroMaxLevel": False,
    "enableHeroHireBan": False,
    "endController": 0,
    "factionLawsExpModifier": 1.0,
    "gameMode": 0,
    "heroCountIncrement": 1,
    "heroCountMax": 5,
    "heroCountMin": 2,
    "idSidesWithoutCameraFollowing": [],
    "idSidesWithoutNotification": [],
    "idSidesWithoutTimer": [],
    "isScenario": True,
    "isTournamentRules": False,
    "mapWinConditions": [],
    "neutralDifficulties": [True] * 6,
    "quickStartDifficulties": [True] * 6,
}


def _scenario_settings(profile: Any) -> dict[str, Any]:
    settings = copy.deepcopy(SCENARIO_SETTINGS)
    raw_difficulty = _field(profile, "difficulty", "normal")
    difficulty = getattr(raw_difficulty, "value", raw_difficulty)
    index_by_difficulty = {"easy": 0, "normal": 1, "hard": 2, "expert": 3}
    if str(difficulty).lower() not in index_by_difficulty:
        raise ValueError(f"unsupported profile difficulty {difficulty!r}")
    return settings


@dataclass(frozen=True)
class NativeMapContainer:
    version: str
    prefix_suffix: bytes
    chunks: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class EmissionResult:
    map_sid: str
    map_path: Path
    sidecar_path: Path
    container_sha256: str
    sidecar_sha256: str
    mechanical_fingerprint: str
    chunks: tuple[dict[str, Any], ...]


def _jsonable(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _jsonable(value.to_dict())
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, Path):
        return str(value)
    return value


def _field(value: Any, name: str, default: Any = None) -> Any:
    camel_name = re.sub(r"_([a-z])", lambda match: match.group(1).upper(), name)
    if isinstance(value, Mapping):
        if name in value:
            return value[name]
        return value.get(camel_name, default)
    if hasattr(value, name):
        return getattr(value, name)
    return getattr(value, camel_name, default)


def _town_construction_sid(
    metadata: Any, faction_sid: str, default_sid: str
) -> str:
    requested = _field(metadata, "buildings_construction_sid")
    if requested is not None:
        if not isinstance(requested, str) or not requested.strip():
            raise ValueError(
                "metadata.buildingsConstructionSid must be a non-empty string when present"
            )
        return requested
    return construction_sid_for_faction(faction_sid, default_sid)


def canonical_json_bytes(value: Any, *, pretty: bool = False) -> bytes:
    separators = None if pretty else (",", ":")
    text = json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        indent=2 if pretty else None,
        separators=separators,
        sort_keys=True,
    )
    if pretty:
        text += "\n"
    return text.encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def read_varint(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if offset >= len(data):
            raise ValueError("truncated Olden map varint")
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, offset
        shift += 7
        if shift > 63:
            raise ValueError("Olden map varint exceeds 64 bits")


def write_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("Olden map varint cannot be negative")
    output = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        output.append(byte | (0x80 if value else 0))
        if not value:
            return bytes(output)


def parse_container_bytes(payload: bytes) -> NativeMapContainer:
    raw = gzip.decompress(payload)
    if len(raw) < 36 or raw[0:1] != b" ":
        raise ValueError("not an expected Olden map container")
    offset = 33
    version_length = raw[offset]
    offset += 1
    version = raw[offset : offset + version_length].decode("ascii")
    offset += version_length
    prefix_suffix = raw[offset : offset + 2]
    if len(prefix_suffix) != 2:
        raise ValueError("truncated Olden map prefix suffix")
    offset += 2
    chunks: list[dict[str, Any]] = []
    while offset < len(raw):
        chunk_length, offset = read_varint(raw, offset)
        chunk_end = offset + chunk_length
        if chunk_end > len(raw):
            raise ValueError("truncated Olden map JSON chunk")
        chunk = json.loads(raw[offset:chunk_end].decode("utf-8"))
        if not isinstance(chunk, dict):
            raise ValueError("Olden map JSON chunk must be an object")
        chunks.append(chunk)
        offset = chunk_end
    if len(chunks) < 2:
        raise ValueError("Olden map container has fewer than two JSON chunks")
    return NativeMapContainer(version, prefix_suffix, tuple(chunks))


def read_container(path: Path) -> NativeMapContainer:
    return parse_container_bytes(Path(path).read_bytes())


def serialize_container(container: NativeMapContainer, hash_sum: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{32}", hash_sum):
        raise ValueError("hash_sum must be a lowercase 32-character md5")
    version = container.version.encode("ascii")
    if len(version) > 255:
        raise ValueError("container version exceeds one-byte length")
    if len(container.prefix_suffix) != 2:
        raise ValueError("container prefix_suffix must be exactly two bytes")
    raw = bytearray(b" ")
    raw.extend(hash_sum.encode("ascii"))
    raw.append(len(version))
    raw.extend(version)
    raw.extend(container.prefix_suffix)
    for chunk in container.chunks:
        encoded = canonical_json_bytes(chunk)
        raw.extend(write_varint(len(encoded)))
        raw.extend(encoded)
    return gzip.compress(bytes(raw), compresslevel=9, mtime=0)


def write_container(path: Path, container: NativeMapContainer, hash_sum: str) -> str:
    payload = serialize_container(container, hash_sum)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return sha256_bytes(payload)


def mechanical_fingerprint(scenario: Any) -> str:
    mechanical = {
        "schema": _field(scenario, "schema"),
        "generatorVersion": _field(scenario, "generator_version"),
        "mapSid": _field(scenario, "map_sid"),
        "seed": _field(scenario, "seed"),
        "profile": _jsonable(_field(scenario, "profile")),
        "topology": _jsonable(_field(scenario, "topology")),
        "layout": _jsonable(_field(scenario, "layout")),
        "terrain": _jsonable(_field(scenario, "terrain")),
        "placements": _jsonable(_field(scenario, "placements")),
        "events": _jsonable(_field(scenario, "events")),
    }
    return sha256_bytes(canonical_json_bytes(mechanical))


def _terrain_arrays(terrain: Any, size: int) -> dict[str, list[Any]]:
    source = _jsonable(terrain)
    if not isinstance(source, dict):
        raise TypeError("scenario terrain must be an object")
    aliases = {
        "tilesMap": ("tilesMap", "tiles_map"),
        "levelsMap": ("levelsMap", "levels_map"),
        "climbsMap": ("climbsMap", "climbs_map"),
        "roadsMap": ("roadsMap", "roads_map"),
        "waterMap": ("waterMap", "water_map"),
        "customAreasPainting": ("customAreasPainting", "custom_areas_painting"),
    }
    result: dict[str, list[Any]] = {}
    expected = size * size
    for native_key, candidates in aliases.items():
        value = next((source[key] for key in candidates if key in source), None)
        if not isinstance(value, list):
            raise ValueError(f"terrain is missing list {candidates[-1]}")
        if len(value) != expected:
            raise ValueError(
                f"terrain {candidates[-1]} length {len(value)} != {size}x{size}"
            )
        result[native_key] = list(value)
    return result


def _profile_title(profile: Any, map_sid: str) -> str:
    title = _field(profile, "title")
    return str(title).strip() if title else map_sid.replace("_", " ").title()


def quest_main_name_sid(map_sid: str) -> str:
    return f"{map_sid}_main_name"


def quest_main_desc_sid(map_sid: str) -> str:
    return f"{map_sid}_main_desc"


def quest_objective_name_sid(objective_sid: str) -> str:
    return f"{objective_sid}_name"


def quest_localization_rows(
    events: Any,
    map_sid: str,
    *,
    title: str | None = None,
) -> tuple[dict[str, str], ...]:
    """Build LocKit sid/text rows for visible procedural quest labels.

    Olden Era quest ``name``/``desc`` fields are LocKit SIDs, not inline text.
    Missing rows render as ``LOC:`` placeholders in the quest log.
    """

    display_title = str(title).strip() if title else _profile_title({}, map_sid)
    rows: dict[str, str] = {
        quest_main_name_sid(map_sid): display_title,
        quest_main_desc_sid(map_sid): "Complete the scenario objectives.",
    }
    native = _jsonable(events)
    serialized_specs = native if isinstance(native, list) else []
    for spec in serialized_specs:
        if not isinstance(spec, dict):
            continue
        objective_sids = {
            str(action.get("objectiveSid"))
            for action in spec.get("actions") or []
            if isinstance(action, dict)
            and action.get("kind") == "objective_progress"
            and action.get("objectiveSid")
        }
        if len(objective_sids) != 1:
            continue
        objective_sid = next(iter(objective_sids))
        label = str(
            spec.get("objectiveLabel") or spec.get("title") or "Primary Objective"
        ).strip()
        if not label:
            raise ValueError(f"objective event {spec.get('eventId')!r} lacks a label")
        rows[quest_objective_name_sid(objective_sid)] = label
    # Conquest / fallback single-objective scripts still need a visible label
    # when typed objective_progress actions are absent.
    if not any(sid.endswith("_name") and sid != quest_main_name_sid(map_sid) for sid in rows):
        fallback_sid = f"{map_sid}_objective"
        rows[quest_objective_name_sid(fallback_sid)] = "Primary Objective"
    return tuple({"sid": sid, "text": text} for sid, text in sorted(rows.items()))


def quest_localization_core_deltas(
    map_sid: str,
    rows: Sequence[Mapping[str, str]],
    *,
    locale_folders: Sequence[str] = CORE_CUSTOM_MAPS_LOCALES,
) -> tuple[dict[str, Any], ...]:
    """Upsert quest LocKit rows into every Core customMaps locale."""

    if not rows:
        raise ValueError("quest localization requires at least one LocKit row")
    payload = [dict(row) for row in rows]
    for row in payload:
        if set(row) != {"sid", "text"}:
            raise ValueError(f"quest LocKit row must be {{sid,text}}; got {sorted(row)}")
        if not isinstance(row["sid"], str) or not row["sid"]:
            raise ValueError("quest LocKit sid must be a non-empty string")
        if not isinstance(row["text"], str) or not row["text"].strip():
            raise ValueError(f"quest LocKit text for {row['sid']!r} must be non-empty")
    operations: list[dict[str, Any]] = []
    for locale in locale_folders:
        member = f"Lang/{locale}/texts/customMaps.json"
        for section in ("tokens", "array"):
            operations.append(
                {
                    "id": f"{map_sid}:quest_loc:{locale}:{section}",
                    "member": member,
                    "operation": "upsert_array",
                    "path": [section],
                    "key": "sid",
                    "rows": copy.deepcopy(payload),
                }
            )
    return tuple(operations)


def _event_script(
    events: Any,
    map_sid: str,
    *,
    compiled_triggers: Sequence[Mapping[str, Any]] | None = None,
    extra_triggers: Sequence[Mapping[str, Any]] | None = None,
    extra_subquests: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    native = _jsonable(events)
    if isinstance(native, dict):
        for key in ("native_script", "nativeScript", "script"):
            value = native.get(key)
            if isinstance(value, dict):
                if (
                    compiled_triggers is not None
                    or extra_triggers
                    or extra_subquests
                ):
                    raise ValueError(
                        "compiled quest payload cannot override a native script"
                    )
                return copy.deepcopy(value)
        if "counters" in native and "quests" in native:
            if (
                compiled_triggers is not None
                or extra_triggers
                or extra_subquests
            ):
                raise ValueError(
                    "compiled quest payload cannot override a native script"
                )
            return copy.deepcopy(native)
        native_rows = native.get("triggers")
    else:
        native_rows = native

    serialized_specs = native if isinstance(native, list) else []
    typed_specs = bool(serialized_specs) and all(
        isinstance(row, dict)
        and isinstance(row.get("triggers"), list)
        and isinstance(row.get("actions"), list)
        and row.get("eventId")
        for row in serialized_specs
    )
    declared_counter_sids: set[str] = set()
    event_metadata: dict[str, dict[str, Any]] = {}
    if typed_specs:
        for spec in serialized_specs:
            event_id = str(spec["eventId"])
            objective_sids = {
                str(action.get("objectiveSid"))
                for action in spec["actions"]
                if isinstance(action, dict)
                and action.get("kind") == "objective_progress"
                and action.get("objectiveSid")
            }
            if len(objective_sids) > 1:
                raise ValueError(
                    f"event {event_id} advances more than one objective: "
                    f"{sorted(objective_sids)}"
                )
            for row in list(spec["triggers"]) + list(spec["actions"]):
                if (
                    isinstance(row, dict)
                    and row.get("kind") in {"counter", "counter_change"}
                    and row.get("counterSid")
                ):
                    declared_counter_sids.add(str(row["counterSid"]))
            event_metadata[event_id] = {
                "objectiveSid": next(iter(objective_sids), None),
                "name": str(
                    spec.get("objectiveLabel")
                    or spec.get("title")
                    or "Primary Objective"
                ),
            }

    if compiled_triggers is not None:
        trigger_rows = [copy.deepcopy(dict(row)) for row in compiled_triggers]
    elif typed_specs:
        try:
            from .events import compile_mechanical_events

            trigger_rows = list(
                compile_mechanical_events(
                    events,
                    declared_counter_sids=sorted(declared_counter_sids),
                )
            )
        except (ImportError, TypeError, ValueError) as exc:
            raise ValueError("MechanicalEventSpec compilation failed") from exc
    else:
        trigger_rows = native_rows

    if not isinstance(trigger_rows, list):
        trigger_rows = []
    if trigger_rows and not all(
        isinstance(row, dict)
        and isinstance(row.get("conditions"), list)
        and isinstance(row.get("actions"), list)
        for row in trigger_rows
    ):
        raise ValueError("events are neither native trigger rows nor MechanicalEventSpec rows")

    declared_counters: list[dict[str, Any]] = []
    seen_counter_sids: set[str] = set()
    for sid in sorted(declared_counter_sids):
        seen_counter_sids.add(sid)
        declared_counters.append(
            {
                "comment": "",
                "sid": sid,
                "sharing": "Clone",
                "value": 0,
                "minValue": -2147483648,
                "maxValue": 2147483647,
            }
        )
    extra_trigger_rows = list(extra_triggers or ())
    for subquest in extra_subquests or ():
        if not isinstance(subquest, Mapping):
            raise ValueError("seer subquest rows must be objects")
        rows = subquest.get("triggers")
        if not isinstance(rows, list):
            raise ValueError("seer subquest rows require a triggers list")
        extra_trigger_rows.extend(rows)
    for trigger in list(trigger_rows) + extra_trigger_rows:
        for row in list(trigger.get("conditions") or []) + list(trigger.get("actions") or []):
            params = row.get("p") if isinstance(row, dict) else None
            opcode = (row.get("a") or row.get("c")) if isinstance(row, dict) else None
            if opcode in {
                "CounterSet",
                "CounterPlus",
                "Counter",
                "CounterEqual",
                "CounterEqualityInDays",
            } and params:
                sid = str(params[0])
                if sid and sid not in seen_counter_sids:
                    seen_counter_sids.add(sid)
                    declared_counters.append(
                        {
                            "comment": "",
                            "sid": sid,
                            "sharing": "Clone",
                            "value": 0,
                            "minValue": -2147483648,
                            "maxValue": 2147483647,
                        }
                    )

    grouped: dict[str, dict[str, Any]] = {}
    if typed_specs:
        for spec, trigger in zip(serialized_specs, trigger_rows, strict=True):
            event_id = str(spec["eventId"])
            metadata = event_metadata[event_id]
            objective_sid = metadata["objectiveSid"]
            group_sid = objective_sid or f"{map_sid}_mechanics"
            # Visible quest labels must be LocKit SIDs. Hidden mechanic groups
            # intentionally keep empty name/desc like native support quests.
            if objective_sid is None:
                label_name = ""
                label_desc = ""
            else:
                label_name = quest_objective_name_sid(objective_sid)
                label_desc = ""
            group = grouped.setdefault(
                group_sid,
                {
                    "sid": group_sid,
                    "activeOnStart": True,
                    "hidden": objective_sid is None,
                    "name": label_name,
                    "desc": label_desc,
                    "comment": "",
                    "triggers": [],
                },
            )
            group["triggers"].append(copy.deepcopy(trigger))
    else:
        fallback_sid = f"{map_sid}_objective"
        grouped[fallback_sid] = {
            "sid": fallback_sid,
            "activeOnStart": True,
            "hidden": False,
            "name": quest_objective_name_sid(fallback_sid),
            "desc": "",
            "comment": "",
            "triggers": copy.deepcopy(trigger_rows),
        }

    if extra_triggers and extra_subquests:
        raise ValueError(
            "seer script cannot provide both flattened triggers and isolated subquests"
        )
    if extra_triggers:
        seer_group = grouped.setdefault(
            f"{map_sid}_seer_huts",
            {
                "sid": f"{map_sid}_seer_huts",
                "activeOnStart": True,
                "hidden": True,
                "name": "",
                "desc": "",
                "comment": "",
                "triggers": [],
            },
        )
        for trigger in extra_triggers:
            seer_group["triggers"].append(copy.deepcopy(dict(trigger)))

    seer_quests: list[dict[str, Any]] = []
    if extra_subquests:
        by_quest: dict[str, list[dict[str, Any]]] = {}
        for raw_subquest in extra_subquests:
            row = dict(raw_subquest)
            quest_sid = str(row.pop("questSid", "") or "").strip()
            subquest_sid = str(row.get("sid", "") or "").strip()
            triggers = row.get("triggers")
            if not quest_sid or not subquest_sid or not isinstance(triggers, list):
                raise ValueError(
                    "isolated seer subquest requires questSid, sid, and triggers"
                )
            by_quest.setdefault(quest_sid, []).append(
                {
                    "sid": subquest_sid,
                    "activeOnStart": bool(row.get("activeOnStart")),
                    "hidden": bool(row.get("hidden", True)),
                    "name": str(row.get("name") or ""),
                    "desc": str(row.get("desc") or ""),
                    "comment": str(row.get("comment") or ""),
                    "triggers": copy.deepcopy(triggers),
                }
            )
        for quest_sid, subquests in sorted(by_quest.items()):
            seer_quests.append(
                {
                    "sid": quest_sid,
                    "hidden": True,
                    "main": False,
                    "activeOnStart": True,
                    "comment": "Procedural Seer's Hut QuestScript FSM",
                    "sharing": "Clone",
                    "name": "",
                    "desc": "",
                    "subQuests": subquests,
                    "subQuestGroups": [],
                }
            )

    main_quest = {
        "sid": f"{map_sid}_main",
        "hidden": False,
        "main": True,
        "activeOnStart": True,
        "comment": "",
        "sharing": "Clone",
        "name": quest_main_name_sid(map_sid),
        "desc": quest_main_desc_sid(map_sid),
        "subQuests": list(grouped.values()),
        "subQuestGroups": [],
    }
    return {
        "comment": f"procedural scenario {map_sid}",
        "aiRolesId": f"{map_sid}_ai",
        "interruptions": [],
        "counters": sorted(declared_counters, key=lambda row: row["sid"]),
        "quests": [main_quest, *seer_quests],
    }


def _placement_rows(
    placements: Any,
    size: int,
) -> tuple[
    list[dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    rows = _jsonable(placements)
    if not isinstance(rows, list):
        raise TypeError("scenario placements must be a sequence")
    objects: list[dict[str, Any]] = []
    properties: dict[str, list[dict[str, Any]]] = {
        "propSpawns": [], "propCities": [], "propOwners": [], "propHeroes": [],
        "propGrowthUnits": [], "propRandomSquads": [], "propEntities": [],
        "propActionsBefore": [], "propActionsAfter": [], "propActivations": [],
        "propMarkers": [], "propSquads": [],
        "propRewardParams": [], "propResParams": [], "propVariants": [],
        "propAiIntetactions": [],
    }
    spawn_rows: list[dict[str, Any]] = []
    markers: list[dict[str, Any]] = []
    used_ids: set[int] = set()
    entity_sids: set[str] = set()
    next_object_id = 100
    next_marker_id = 1

    def allocate_id(preferred: Any = None) -> int:
        nonlocal next_object_id
        if preferred is not None:
            if isinstance(preferred, bool) or not isinstance(preferred, int) or preferred < 0:
                raise ValueError(f"invalid placement object id {preferred!r}")
            if preferred in used_ids:
                raise ValueError(f"duplicate placement object id {preferred}")
            used_ids.add(preferred)
            return preferred
        while next_object_id in used_ids:
            next_object_id += 1
        object_id = next_object_id
        used_ids.add(object_id)
        next_object_id += 1
        return object_id

    def add_object(
        content_sid: str,
        node: int,
        *,
        entity_sid: str | None,
        preferred_id: Any = None,
        rotation: int = 0,
        level: float = 0.0,
        native_variant: int | None = None,
    ) -> int:
        if not content_sid:
            raise ValueError("emitted object content SID cannot be empty")
        if not isinstance(node, int) or not 0 <= node < size * size:
            raise ValueError(f"emitted object node is out of bounds: {node!r}")
        object_id = allocate_id(preferred_id)
        objects.append({
            "sid": content_sid,
            "ids": [object_id],
            "nodes": [node],
            "rotations": [rotation],
            "levels": [level],
        })
        if entity_sid is not None:
            if not entity_sid or entity_sid in entity_sids:
                raise ValueError(f"duplicate or empty placement entity SID {entity_sid!r}")
            entity_sids.add(entity_sid)
            properties["propEntities"].append(
                {"type": 0, "id": object_id, "sid": entity_sid}
            )
        for family, row in property_rows(content_sid, object_id, variant=native_variant).items():
            properties[family].append(row)
        return object_id

    def origin_xy(value: Any, placement_id: str) -> tuple[int, int]:
        if isinstance(value, dict):
            x, y = value.get("x"), value.get("y")
        elif isinstance(value, (list, tuple)) and len(value) == 2:
            x, y = value
        else:
            raise ValueError(f"placement {placement_id} requires an origin point")
        if any(isinstance(item, bool) or not isinstance(item, int) for item in (x, y)):
            raise ValueError(f"placement {placement_id} origin must contain integers")
        return int(x), int(y)

    def child_node(base: tuple[int, int], slot: Mapping[str, Any], label: str) -> int:
        position = slot.get("position")
        if not isinstance(position, Mapping):
            raise ValueError(f"{label} requires a position object")
        x, y = position.get("x"), position.get("y")
        if any(isinstance(item, bool) or not isinstance(item, int) for item in (x, y)):
            raise ValueError(f"{label} position must contain integers")
        absolute_x, absolute_y = base[0] + int(x), base[1] + int(y)
        if not (0 <= absolute_x < size and 0 <= absolute_y < size):
            raise ValueError(f"{label} position is outside the map")
        return absolute_y * size + absolute_x

    for placement in rows:
        if not isinstance(placement, dict):
            raise TypeError("each placement must serialize to an object")
        content_sid = str(_field(placement, "content_sid", "") or "").strip()
        placement_id = str(_field(placement, "placement_id", "") or "").strip()
        if not content_sid or not placement_id:
            raise ValueError("each placement requires placement_id and content_sid")
        metadata = _field(placement, "metadata", {}) or {}
        if not isinstance(metadata, dict):
            raise ValueError(f"placement {placement_id} metadata must be an object")
        kind = str(_field(placement, "kind", "") or "")
        origin = _field(placement, "origin")
        base = origin_xy(origin, placement_id)

        if kind in {"encounter", "guard"}:
            if _field(metadata, "squad_mode") != "exact":
                raise ValueError(f"encounter {placement_id} must use exact squad mode")
            exact_squad = _field(metadata, "exact_squad")
            instance = _field(metadata, "encounter_template_instance")
            if not isinstance(exact_squad, dict) or not isinstance(instance, dict):
                raise ValueError(
                    f"encounter {placement_id} requires exactSquad and encounterTemplateInstance"
                )
            squad_sid = str(_field(exact_squad, "sid", "") or "").strip()
            unit_props = _field(exact_squad, "unit_props")
            actual_value = _field(exact_squad, "actual_value")
            if (
                not squad_sid
                or not isinstance(unit_props, list)
                or not unit_props
                or any(
                    not isinstance(unit, dict)
                    or not str(unit.get("sid") or "").strip()
                    or isinstance(unit.get("count"), bool)
                    or not isinstance(unit.get("count"), int)
                    or unit["count"] <= 0
                    for unit in unit_props
                )
                or isinstance(actual_value, bool)
                or not isinstance(actual_value, (int, float))
                or actual_value <= 0
            ):
                raise ValueError(f"encounter {placement_id} has an invalid exactSquad")
            guards = instance.get("guards")
            buildings = instance.get("buildings")
            pickups = instance.get("pickups")
            if not isinstance(guards, list) or not guards:
                raise ValueError(f"encounter {placement_id} requires at least one template guard")
            if not isinstance(buildings, list) or not isinstance(pickups, list):
                raise ValueError(f"encounter {placement_id} template slots must be lists")
            preferred = _field(placement, "object_id")
            for guard_index, guard in enumerate(guards):
                if not isinstance(guard, dict):
                    raise ValueError(f"encounter {placement_id} guard slot must be an object")
                if str(_field(guard, "squad_sid", "") or "") != squad_sid:
                    raise ValueError(f"encounter {placement_id} guard does not bind exactSquad")
                entity_sid = str(_field(guard, "entity_sid", "") or "").strip()
                object_id = add_object(
                    content_sid,
                    child_node(base, guard, f"encounter {placement_id} guard"),
                    entity_sid=entity_sid,
                    preferred_id=preferred if guard_index == 0 else None,
                    native_variant=_field(metadata, "native_variant"),
                )
                if content_sid == "random-squad":
                    properties["propRandomSquads"].append({
                        "type": 0,
                        "id": object_id,
                        "sids": [],
                        "requestedValue": float(actual_value),
                        "fraction": str(_field(metadata, "faction_sid", "") or ""),
                        "tier": max(0, int(_field(placement, "risk_tier", 0))),
                        "isMainGuard": guard_index == 0,
                        "reactionType": int(_field(metadata, "reaction_type", 2)),
                        "customTopUnit": str(unit_props[0]["sid"]),
                        "weeklyIncrementBonus": 0.0,
                        "diplomacyUnitsCountBonus": 0.0,
                        "isEscape": True,
                        "isAutobatle": True,
                        "isFreeDiplomacy": False,
                        "isCampaignFreeDiplomacy": False,
                        "isCampaignDiplomacy": False,
                        "isIgnoreMultiply": False,
                        "obstruction": "",
                        "customStacks": 0,
                    })
                else:
                    properties["propSquads"].append({
                        "type": 0,
                        "id": object_id,
                        "isMainGuard": guard_index == 0,
                        "isStartBattleImmediately": False,
                        "reactionType": int(_field(metadata, "reaction_type", 2)),
                        "weeklyIncrementBonus": 0.0,
                        "unitProps": copy.deepcopy(unit_props),
                    })
            for slot_kind, slots in (("building", buildings), ("pickup", pickups)):
                for slot_index, slot in enumerate(slots):
                    if not isinstance(slot, dict):
                        raise ValueError(
                            f"encounter {placement_id} {slot_kind} slot must be an object"
                        )
                    slot_sid = str(_field(slot, "content_sid", "") or "").strip()
                    entity_sid = str(_field(slot, "entity_sid", "") or "").strip()
                    add_object(
                        slot_sid,
                        child_node(
                            base,
                            slot,
                            f"encounter {placement_id} {slot_kind} {slot_index}",
                        ),
                        entity_sid=entity_sid,
                        native_variant=_field(slot, "native_variant"),
                    )
            continue

        node = _field(placement, "node")
        if node is None:
            node = base[1] * size + base[0]
        if not isinstance(node, int) or not 0 <= node < size * size:
            raise ValueError(f"placement {placement_id} has invalid node {node!r}")
        object_id = add_object(
            content_sid,
            node,
            entity_sid=None if kind in {"objective", "scenery"} else placement_id,
            preferred_id=_field(placement, "object_id"),
            rotation=int(_field(metadata, "rotation", 0)),
            level=float(_field(metadata, "level", 0.0)),
            native_variant=_field(metadata, "native_variant"),
        )
        if kind == "objective":
            marker_id = next_marker_id
            next_marker_id += 1
            markers.append({"node": node, "v": "", "sid": "Zone 1x1", "id": marker_id})
            properties["propMarkers"].append(
                {"type": 1, "id": marker_id, "isDelete": False, "isActivate": True}
            )
            if placement_id in entity_sids:
                raise ValueError(f"duplicate placement entity SID {placement_id!r}")
            entity_sids.add(placement_id)
            properties["propEntities"].append(
                {"type": 1, "id": marker_id, "sid": placement_id}
            )
        if kind == "neutral_city":
            faction_sid = str(_field(metadata, "faction_sid", "") or "")
            if not faction_sid:
                raise ValueError(f"neutral city {placement_id} requires metadata.factionSid")
            properties["propCities"].append({
                "type": 0, "id": object_id, "isDefined": True,
                "factionSid": faction_sid, "spawnHero": False,
                "buildingsConstructionSid": _town_construction_sid(
                    metadata, faction_sid, "default_buildings_construction"
                ),
                "buildingsBanSid": str(_field(metadata, "buildings_ban_sid", "default_buildings_ban")),
                "buildingsSettingsSid": str(_field(metadata, "buildings_settings_sid", "default_buildings_settings")),
                "customCityName": str(_field(metadata, "name", "")),
            })
            properties["propOwners"].append({"type": 0, "id": object_id, "owner": -1})
            properties["propGrowthUnits"].append({"type": 0, "id": object_id, "isConstantGrowth": True, "countGrowth": 1})
            properties["propRandomSquads"].append({
                "type": 0, "id": object_id, "sids": [], "requestedValue": 0.0,
                "fraction": "", "tier": 0, "isMainGuard": False, "reactionType": 2,
                "customTopUnit": "", "weeklyIncrementBonus": 0.0, "diplomacyUnitsCountBonus": 0.0,
                "isEscape": True, "isAutobatle": True, "isFreeDiplomacy": False,
                "isCampaignFreeDiplomacy": False, "isCampaignDiplomacy": False,
                "isIgnoreMultiply": False, "obstruction": "", "customStacks": 0,
            })

        if kind in {"settlement", "city", "player_start", "enemy_start", "ai_settlement"}:
            owner = int(_field(metadata, "owner", 1 if kind == "player_start" else 2))
            faction_sid = str(_field(metadata, "faction_sid", "") or "")
            hero_sid = str(_field(metadata, "hero_sid", "") or "")
            if not faction_sid:
                raise ValueError(f"settlement {placement_id} requires metadata.factionSid")
            properties["propSpawns"].append({
                "type": 0, "id": object_id, "owner": owner,
                "spawnType": 0,
                "spawnPointType": 0, "isLocked": False,
            })
            properties["propCities"].append({
                "type": 0, "id": object_id, "isDefined": True,
                "factionSid": faction_sid, "spawnHero": bool(hero_sid),
                "buildingsConstructionSid": _town_construction_sid(
                    metadata, faction_sid, "rich_buildings_construction"
                ),
                "buildingsBanSid": str(_field(
                    metadata, "buildings_ban_sid", "default_buildings_ban"
                )),
                "buildingsSettingsSid": str(_field(
                    metadata, "buildings_settings_sid", "default_buildings_settings"
                )),
                "customCityName": str(_field(metadata, "name", "")),
            })
            if hero_sid:
                properties["propHeroes"].append(
                    {"type": 0, "id": object_id, "isDefined": True, "heroSid": hero_sid}
                )
            properties["propGrowthUnits"].append(
                {"type": 0, "id": object_id, "isConstantGrowth": True, "countGrowth": 1}
            )
            properties["propRandomSquads"].append({
                "type": 0, "id": object_id, "sids": [], "requestedValue": 0.0,
                "fraction": "", "tier": 0, "isMainGuard": False,
                "reactionType": 2, "customTopUnit": "", "weeklyIncrementBonus": 0.0,
                "diplomacyUnitsCountBonus": 0.0, "isEscape": True,
                "isAutobatle": True, "isFreeDiplomacy": False,
                "isCampaignFreeDiplomacy": False, "isCampaignDiplomacy": False,
                "isIgnoreMultiply": False, "obstruction": "", "customStacks": 0,
            })
            spawn_rows.append({
                "owner": owner, "spawnType": 0,
                "playerId": "", "spawnPointType": 0,
                "isCityDefined": True, "factionSid": faction_sid,
                "isHeroDefined": bool(hero_sid), "heroSid": hero_sid,
                "colorId": -1, "isAlive": True, "isLocked": False,
            })
        native_properties = _field(metadata, "native_properties", {}) or {}
        if native_properties:
            if not isinstance(native_properties, dict):
                raise ValueError("metadata.nativeProperties must be an object")
            for key, value in native_properties.items():
                if key not in properties or not isinstance(value, dict):
                    raise ValueError(f"unsupported native property injection {key}")
                properties[key].append({"type": 0, "id": object_id, **copy.deepcopy(value)})
    grouped_objects: dict[str, dict[str, Any]] = {}
    for row in objects:
        sid = str(row["sid"])
        grouped = grouped_objects.setdefault(
            sid,
            {"sid": sid, "ids": [], "nodes": [], "rotations": [], "levels": []},
        )
        for key in ("ids", "nodes", "rotations", "levels"):
            grouped[key].extend(row[key])
    return list(grouped_objects.values()), properties, spawn_rows, markers


def _native_area_rows(
    terrain: Mapping[str, Any],
    objects: Sequence[Mapping[str, Any]],
    properties: Mapping[str, Sequence[Mapping[str, Any]]],
) -> tuple[list[dict[str, Any]], list[int]]:
    """Build area topology from the same painting used by the map grid."""
    painting = terrain["customAreasPainting"]
    values = sorted({int(value) for value in painting})
    object_nodes = {
        int(object_id): int(node)
        for group in objects
        for object_id, node in zip(group["ids"], group["nodes"], strict=True)
    }
    city_ids = {
        int(row["id"])
        for row in properties.get("propCities", ())
        if isinstance(row, Mapping) and isinstance(row.get("id"), int)
    }
    areas: list[dict[str, Any]] = []
    key_objects: list[int] = []
    for area_id, value in enumerate(values):
        nodes = [
            index for index, painted in enumerate(painting) if int(painted) == value
        ]
        if not nodes:
            continue
        node_set = set(nodes)
        keys = sorted(
            object_id
            for object_id in city_ids
            if object_nodes.get(object_id) in node_set
        )
        areas.append(
            {
                "id": area_id,
                "keyObjectId": keys[0] if keys else -1,
                "rootNode": nodes[0],
                "nodes": nodes,
            }
        )
        key_objects.extend(keys)
    return areas, sorted(set(key_objects))


def build_native_container(
    scenario: Any,
    donor: NativeMapContainer,
    *,
    compiled_triggers: Sequence[Mapping[str, Any]] | None = None,
) -> NativeMapContainer:
    map_sid = str(_field(scenario, "map_sid") or "")
    if not MAP_SID_PATTERN.fullmatch(map_sid):
        raise ValueError(
            "procedural map_sid must match proc_[a-z0-9][a-z0-9_]{2,79}"
        )
    size = int(_field(scenario, "size", 0) or _field(_field(scenario, "profile"), "map_size", 0))
    if size not in {32, 48, 64}:
        raise ValueError("procedural surface map size must be 32, 48, or 64")
    if len(donor.chunks) < 4:
        raise ValueError("schema donor map must contain at least four JSON chunks")
    profile = _field(scenario, "profile")
    title = _profile_title(profile, map_sid)
    map_hash = hashlib.md5(map_sid.encode("utf-8")).hexdigest()
    chunks = copy.deepcopy(list(donor.chunks))
    donor_data = chunks[1]
    schema_fields = {
        key: copy.deepcopy(donor_data[key])
        for key in ("cliffRandomSeed", "generatorChecksum")
        if key in donor_data
    }
    schema_fields["settings"] = _scenario_settings(profile)
    terrain = _terrain_arrays(_field(scenario, "terrain"), size)
    objects, properties, spawns, markers = _placement_rows(_field(scenario, "placements"), size)
    donor_properties = donor_data.get("objectsProperties")
    if donor_properties is not None and not isinstance(donor_properties, Mapping):
        raise ValueError("schema donor objectsProperties must be an object")
    property_keys = set(NATIVE_OBJECT_PROPERTY_KEYS)
    if isinstance(donor_properties, Mapping):
        property_keys.update(str(key) for key in donor_properties)
    for key in sorted(property_keys):
        properties.setdefault(key, [])
    areas, key_objects = _native_area_rows(terrain, objects, properties)
    if not any(int(row["owner"]) == 1 for row in spawns):
        raise ValueError("scenario requires a player-owned settlement placement")
    taken_heroes = sorted(
        {
            str(row.get("heroSid"))
            for row in spawns
            if str(row.get("heroSid") or "").strip()
        }
    )
    start_settings = chunks[0].get("startSettings")
    if not isinstance(start_settings, dict):
        raise ValueError("schema donor chunk 0 requires startSettings")
    start_settings = copy.deepcopy(start_settings)
    start_settings["DefeatAllEnemiesEnabled"] = False
    raw_difficulty = _field(profile, "difficulty", "normal")
    difficulty = getattr(raw_difficulty, "value", raw_difficulty)
    difficulty_index = {"easy": 0, "normal": 1, "hard": 2, "expert": 3}.get(str(difficulty).lower())
    if difficulty_index is None:
        raise ValueError(f"unsupported profile difficulty {difficulty!r}")
    start_settings["AiDifficulty"] = difficulty_index
    start_settings["EconomicDifficulty"] = difficulty_index
    start_settings["NeutralsDifficulty"] = difficulty_index
    chunks[0] = {
        **chunks[0],
        "title": title,
        "template": "",
        "desc": str(_field(profile, "description", "")),
        "displayWinCondition": "Complete the primary objective.",
        "hashSum": map_hash,
        "nameFromLocalization": False,
        "descFromLocalization": False,
        "isScenario": True,
        "sizeX": size,
        "sizeZ": size,
        "spawns": {
            "playersCount": len(spawns),
            "spawns": spawns,
            "takenHeroes": taken_heroes,
        },
        "campaignInfo": {
            "missionNameSid": "",
            "missionDescSid": "",
            "campaignSid": "",
            "campaignDescSid": "",
            "hubIconSid": "",
        },
        "startSettings": start_settings,
    }
    chunks[1] = {
        "fileMapName": map_sid,
        "mapName": title,
        "mapNameFromLoc": False,
        "mapDesc": str(_field(profile, "description", "")),
        "mapDescFromLoc": False,
        "sizeX_": size,
        "sizeZ_": size,
        **terrain,
        "haveCustomAreas": True,
        "areasVersion": 1,
        "objects": objects,
        "objectsFreeId": max((item for row in objects for item in row["ids"]), default=99)
        + 1,
        "squads": [],
        "squadsFreeId": 0,
        "markers": markers,
        "markersFreeId": max((int(row["id"]) for row in markers), default=0) + 1,
        "takenHeroes": taken_heroes,
        "keyObjects": key_objects,
        "objectValuesOverrides": {"list": []},
        "areas": areas,
        "rivers": [],
        "views": [
            {
                "name": "",
                "minSecX": 0,
                "minSecZ": 0,
                "secSizeX": size // 16,
                "secSizeZ": size // 16,
                "isUnderground": False,
                "stack": -1,
            }
        ],
        "banInfoData": {
            "bannedMagics": [],
            "bannedItems": [],
            "bannedSkills": [],
            "bannedHeroes": [],
            "bannedUnits": [],
        },
        "objectsProperties": properties,
        **schema_fields,
    }
    chunks[2] = {"dialogs": {"lines": []}, "quests": {"quests": []}}
    seer_subquests = _field(scenario, "seer_script_subquests", ())
    if _field(scenario, "seer_script_triggers", ()) and not seer_subquests:
        raise ValueError(
            "procedural scenario contains flattened Seer triggers without isolated subquests"
        )
    chunks[3] = _event_script(
        _field(scenario, "events"),
        map_sid,
        compiled_triggers=compiled_triggers,
        extra_subquests=seer_subquests,
    )
    return NativeMapContainer(donor.version, donor.prefix_suffix, tuple(chunks))


def emit_scenario(
    scenario: Any,
    output_root: Path,
    *,
    donor_map: Path | None = None,
    donor_container: NativeMapContainer | None = None,
    compiled_triggers: Sequence[Mapping[str, Any]] | None = None,
) -> EmissionResult:
    if (donor_map is None) == (donor_container is None):
        raise ValueError("provide exactly one of donor_map or donor_container")
    donor = donor_container or read_container(Path(donor_map))
    container = build_native_container(
        scenario,
        donor,
        compiled_triggers=compiled_triggers,
    )
    map_sid = str(_field(scenario, "map_sid"))
    maps_root = Path(output_root) / "maps"
    map_path = maps_root / f"{map_sid}.map"
    sidecar_path = maps_root / f"{map_sid}.json"
    map_hash = hashlib.md5(map_sid.encode("utf-8")).hexdigest()
    container_hash = write_container(map_path, container, map_hash)
    script = container.chunks[3]
    sidecar = {
        "counters": copy.deepcopy(list(script.get("counters") or [])),
        "quests": [],
    }
    sidecar_payload = canonical_json_bytes(sidecar, pretty=True)
    sidecar_path.write_bytes(sidecar_payload)
    return EmissionResult(
        map_sid=map_sid,
        map_path=map_path,
        sidecar_path=sidecar_path,
        container_sha256=container_hash,
        sidecar_sha256=sha256_bytes(sidecar_payload),
        mechanical_fingerprint=mechanical_fingerprint(scenario),
        chunks=container.chunks,
    )
