"""Fail-closed validation for procedural scenario IR and emitted bundles."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .bundle import (
    BUNDLE_SCHEMA,
    CORE_DELTA_SCHEMA,
    normalize_core_deltas,
    verify_source_artifacts,
)
from .events import (
    CounterAction,
    CounterTrigger,
    MechanicalEventSpec,
    compile_mechanical_events,
)
from .model import PlacementKind
from .native_properties import (
    HOMM3_CUSTOM_TOWN_BUILDINGS_CONSTRUCTION_SID,
    RESOURCE_SIDS,
    REWARD_PARAMETER_SIDS,
    VARIANT_SIDS,
)
from .emitter import (
    ARRAY_KEYS,
    CORE_CUSTOM_MAPS_LOCALES,
    MAP_SID_PATTERN,
    NATIVE_OBJECT_PROPERTY_KEYS,
    _field,
    _jsonable,
    parse_container_bytes,
    serialize_container,
    sha256_bytes,
)


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    path: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "context": self.context,
        }


@dataclass(frozen=True)
class ValidationReport:
    subject: str
    issues: tuple[ValidationIssue, ...]
    checks: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.issues

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "subject": self.subject,
            "checks": list(self.checks),
            "issues": [issue.to_dict() for issue in self.issues],
        }

    def raise_for_errors(self) -> None:
        if self.issues:
            summary = "; ".join(
                f"{issue.code}: {issue.message}" for issue in self.issues[:8]
            )
            raise ValueError(f"procedural scenario validation failed: {summary}")


def _issue(
    issues: list[ValidationIssue],
    code: str,
    message: str,
    path: str = "",
    **context: Any,
) -> None:
    issues.append(ValidationIssue(code, message, path, context))


def _safe_bundle_path(root: Path, relative: str) -> Path:
    pure = PurePosixPath(str(relative).replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts or not pure.parts:
        raise ValueError(f"unsafe bundle-relative path {relative!r}")
    target = root.joinpath(*pure.parts).resolve()
    if root.resolve() not in target.parents:
        raise ValueError(f"bundle path escapes root: {relative!r}")
    return target


def _validate_source_hashes(manifest: Mapping[str, Any], issues: list[ValidationIssue]) -> None:
    source_hashes = manifest.get("sourceHashes")
    if not isinstance(source_hashes, Mapping) or not source_hashes:
        _issue(
            issues,
            "source_hashes_missing",
            "manifest sourceHashes must be a non-empty object",
            "manifest.json.sourceHashes",
        )
        return
    if "core" not in source_hashes:
        _issue(
            issues,
            "core_source_hash_missing",
            "sourceHashes must identify the effective Core with logical key 'core'",
            "manifest.json.sourceHashes",
        )
    for raw_key, raw_hash in source_hashes.items():
        key = str(raw_key)
        normalized = key.replace("\\", "/")
        if not key:
            _issue(issues, "source_hash_key_invalid", "source hash keys cannot be empty", "manifest.json.sourceHashes")
        if normalized != "core" and PurePosixPath(normalized).name.lower() == "core.zip":
            _issue(
                issues,
                "core_source_hash_legacy_key",
                "Core source identity must use the path-independent logical key 'core'",
                f"manifest.json.sourceHashes.{key}",
            )
        if not isinstance(raw_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", raw_hash):
            _issue(
                issues,
                "source_hash_invalid",
                "source hashes must be lowercase sha256 values",
                f"manifest.json.sourceHashes.{key}",
            )
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        _issue(issues, "provenance_missing", "manifest provenance must be an object", "manifest.json.provenance")
        return
    provenance_fields = [
        (spelling, provenance[spelling])
        for spelling in ("sourceHashes", "source_hashes")
        if spelling in provenance
    ]
    if not provenance_fields:
        _issue(
            issues,
            "provenance_source_hashes_missing",
            "provenance must record source hashes",
            "manifest.json.provenance",
        )
    for spelling, value in provenance_fields:
        if not isinstance(value, Mapping) or dict(value) != dict(source_hashes):
            _issue(
                issues,
                "source_hash_provenance_mismatch",
                f"manifest sourceHashes differ from provenance.{spelling}",
                f"manifest.json.provenance.{spelling}",
            )

def _walk_native_rows(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if ("a" in value or "c" in value) and isinstance(value.get("p", []), list):
            yield value
        for child in value.values():
            yield from _walk_native_rows(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_native_rows(child)


def _validate_arrays(map_data: dict[str, Any], issues: list[ValidationIssue]) -> None:
    width = map_data.get("sizeX_")
    height = map_data.get("sizeZ_")
    if width not in {32, 48, 64} or height != width:
        _issue(
            issues,
            "map_size_invalid",
            "surface map size must be square and one of 32, 48, or 64",
            "chunks[1]",
            width=width,
            height=height,
        )
        return
    expected = width * height
    for key in ARRAY_KEYS:
        value = map_data.get(key)
        if not isinstance(value, list) or len(value) != expected:
            _issue(
                issues,
                "map_array_length",
                f"{key} must contain exactly {expected} entries",
                f"chunks[1].{key}",
                actual=len(value) if isinstance(value, list) else None,
            )


def _validate_areas(map_data: dict[str, Any], issues: list[ValidationIssue]) -> None:
    areas = map_data.get("areas")
    painting = map_data.get("customAreasPainting")
    objects = map_data.get("objects")
    if not isinstance(areas, list):
        _issue(issues, "areas_invalid", "areas must be a list", "chunks[1].areas")
        return
    if not isinstance(painting, list):
        return
    object_ids = {
        int(object_id)
        for group in objects
        if isinstance(group, dict)
        for object_id in group.get("ids", [])
        if isinstance(object_id, int)
    }
    area_ids: set[int] = set()
    area_nodes: set[int] = set()
    for index, area in enumerate(areas):
        path = f"chunks[1].areas[{index}]"
        if not isinstance(area, dict):
            _issue(issues, "area_shape_invalid", "area must be an object", path)
            continue
        area_id = area.get("id")
        nodes = area.get("nodes")
        root = area.get("rootNode")
        key_object = area.get("keyObjectId")
        if not isinstance(area_id, int) or area_id in area_ids:
            _issue(issues, "area_id_invalid", "area ids must be unique integers", path)
        else:
            area_ids.add(area_id)
        if (
            not isinstance(nodes, list)
            or not nodes
            or any(not isinstance(node, int) or node < 0 or node >= len(painting) for node in nodes)
            or len(set(nodes)) != len(nodes)
        ):
            _issue(issues, "area_nodes_invalid", "area nodes must be unique in-bounds integers", path)
        else:
            overlap = area_nodes.intersection(nodes)
            if overlap:
                _issue(issues, "area_nodes_overlap", "area node sets must not overlap", path, nodes=sorted(overlap)[:20])
            area_nodes.update(nodes)
            if root not in nodes:
                _issue(issues, "area_root_invalid", "area rootNode must belong to its node set", path)
        if key_object != -1 and key_object not in object_ids:
            _issue(issues, "area_key_object_invalid", "area keyObjectId must reference an emitted object or -1", path)
    if area_ids != set(range(len(areas))):
        _issue(issues, "area_ids_noncontiguous", "area ids must be contiguous from zero", "chunks[1].areas", ids=sorted(area_ids))
    painted_ids = {int(value) for value in painting if isinstance(value, int)}
    if painted_ids - area_ids:
        _issue(
            issues,
            "area_paint_unresolved",
            "customAreasPainting contains values without matching area rows",
            "chunks[1].customAreasPainting",
            values=sorted(painted_ids - area_ids),
        )
    if area_nodes != set(range(len(painting))):
        _issue(
            issues,
            "area_partition_incomplete",
            "area rows must partition every painted map node",
            "chunks[1].areas",
            missing=len(set(range(len(painting))) - area_nodes),
            extra=len(area_nodes - set(range(len(painting)))),
        )

def _validate_settings(map_data: dict[str, Any], issues: list[ValidationIssue]) -> None:
    settings = map_data.get("settings")
    if not isinstance(settings, dict):
        _issue(issues, "settings_missing", "scenario settings must be an object", "chunks[1].settings")
        return
    if settings.get("isScenario") is not True:
        _issue(issues, "settings_scenario_flag", "scenario settings must set isScenario=true", "chunks[1].settings.isScenario")
    win_conditions = settings.get("mapWinConditions")
    if win_conditions != []:
        _issue(
            issues,
            "alternate_victory_forbidden",
            "mapWinConditions must be empty; scripted GameVictory is the sole victory contract",
            "chunks[1].settings.mapWinConditions",
            actual=win_conditions,
        )


def _validate_start_settings(meta: Mapping[str, Any], issues: list[ValidationIssue]) -> None:
    start_settings = meta.get("startSettings")
    if not isinstance(start_settings, Mapping):
        _issue(
            issues,
            "start_settings_missing",
            "scenario metadata requires startSettings",
            "chunks[0].startSettings",
        )
        return
    if start_settings.get("DefeatAllEnemiesEnabled") is not False:
        _issue(
            issues,
            "alternate_victory_forbidden",
            "DefeatAllEnemiesEnabled must be false; scripted GameVictory is the sole victory contract",
            "chunks[0].startSettings.DefeatAllEnemiesEnabled",
            actual=start_settings.get("DefeatAllEnemiesEnabled"),
        )

def _validate_spawn_metadata(
    meta: Mapping[str, Any],
    issues: list[ValidationIssue],
    *,
    map_data: Mapping[str, Any] | None = None,
) -> None:
    spawn_container = meta.get("spawns")
    if not isinstance(spawn_container, Mapping):
        return
    spawns = spawn_container.get("spawns")
    if not isinstance(spawns, list):
        return
    invalid_indexes = [
        index
        for index, row in enumerate(spawns)
        if isinstance(row, Mapping)
        and row.get("isCityDefined") is True
        and row.get("spawnPointType") != 0
    ]
    if invalid_indexes:
        _issue(
            issues,
            "city_spawn_metadata_type_invalid",
            "city-defined spawn metadata must use native city spawnPointType 0",
            "chunks[0].spawns.spawns",
            indexes=invalid_indexes,
        )
    invalid_spawn_types = [
        index
        for index, row in enumerate(spawns)
        if isinstance(row, Mapping)
        and row.get("isCityDefined") is True
        and row.get("spawnType") != 0
    ]
    if invalid_spawn_types:
        _issue(
            issues,
            "city_spawn_metadata_spawn_type_invalid",
            "city-defined spawn metadata must use native city spawnType 0",
            "chunks[0].spawns.spawns",
            indexes=invalid_spawn_types,
        )
    if map_data is None:
        return
    properties = map_data.get("objectsProperties")
    property_rows = properties.get("propSpawns") if isinstance(properties, Mapping) else None
    if not isinstance(property_rows, list):
        _issue(
            issues,
            "city_spawn_property_missing",
            "city-defined header spawns require a propSpawns list for parity",
            "chunks[1].objectsProperties.propSpawns",
        )
        return
    header_rows = [
        row for row in spawns
        if isinstance(row, Mapping) and row.get("isCityDefined") is True
    ]
    typed_property_rows = [row for row in property_rows if isinstance(row, Mapping)]
    if len(typed_property_rows) != len(header_rows):
        _issue(
            issues,
            "city_spawn_property_count_mismatch",
            "city-defined header spawns and propSpawns rows must have equal counts",
            "chunks[1].objectsProperties.propSpawns",
            headerCount=len(header_rows),
            propertyCount=len(typed_property_rows),
        )
    for index, header in enumerate(header_rows):
        owner = header.get("owner")
        matches = [row for row in typed_property_rows if row.get("owner") == owner]
        if len(matches) != 1:
            _issue(
                issues,
                "city_spawn_property_owner_mismatch",
                "each city-defined header spawn must have one matching propSpawns owner",
                f"chunks[0].spawns.spawns[{index}]",
                owner=owner,
            )
            continue
        property_row = matches[0]
        if (
            property_row.get("spawnPointType") != header.get("spawnPointType")
            or property_row.get("spawnType") != header.get("spawnType")
        ):
            _issue(
                issues,
                "city_spawn_property_metadata_mismatch",
                "header and propSpawns city spawn metadata must agree",
                f"chunks[0].spawns.spawns[{index}]",
                owner=owner,
            )

def _validate_objects(map_data: dict[str, Any], issues: list[ValidationIssue]) -> set[str]:
    width = map_data.get("sizeX_")
    height = map_data.get("sizeZ_")
    node_count = width * height if isinstance(width, int) and isinstance(height, int) else 0
    objects = map_data.get("objects")
    if not isinstance(objects, list):
        _issue(issues, "objects_missing", "objects must be a list", "chunks[1].objects")
        return set()
    object_ids: set[int] = set()
    object_sid_by_id: dict[int, str] = {}
    for group_index, group in enumerate(objects):
        path = f"chunks[1].objects[{group_index}]"
        if not isinstance(group, dict) or not str(group.get("sid") or "").strip():
            _issue(issues, "object_sid_missing", "object group requires sid", path)
            continue
        lengths = {
            key: len(group.get(key)) if isinstance(group.get(key), list) else None
            for key in ("ids", "nodes", "rotations", "levels")
        }
        if None in lengths.values() or len(set(lengths.values())) != 1:
            _issue(
                issues,
                "object_parallel_arrays",
                "ids/nodes/rotations/levels must be lists with equal lengths",
                path,
                lengths=lengths,
            )
            continue
        for item_index, object_id in enumerate(group["ids"]):
            if not isinstance(object_id, int) or object_id < 0:
                _issue(
                    issues,
                    "object_id_invalid",
                    "object id must be a non-negative integer",
                    f"{path}.ids[{item_index}]",
                )
            elif object_id in object_ids:
                _issue(
                    issues,
                    "object_id_duplicate",
                    f"duplicate object id {object_id}",
                    f"{path}.ids[{item_index}]",
                )
            else:
                object_ids.add(object_id)
                object_sid_by_id[object_id] = str(group["sid"])
        for item_index, node in enumerate(group["nodes"]):
            if not isinstance(node, int) or not 0 <= node < node_count:
                _issue(
                    issues,
                    "object_node_invalid",
                    f"object node must be in [0, {node_count})",
                    f"{path}.nodes[{item_index}]",
                    node=node,
                )
    markers = map_data.get("markers", [])
    marker_ids: set[int] = set()
    if not isinstance(markers, list):
        _issue(issues, "markers_invalid", "markers must be a list", "chunks[1].markers")
        markers = []
    for index, marker in enumerate(markers):
        marker_id = marker.get("id") if isinstance(marker, dict) else None
        marker_node = marker.get("node") if isinstance(marker, dict) else None
        if (
            not isinstance(marker, dict)
            or marker.get("sid") != "Zone 1x1"
            or not isinstance(marker_node, int)
            or not 0 <= marker_node < node_count
        ):
            _issue(
                issues,
                "marker_shape_invalid",
                "interaction markers must be in-bounds native Zone 1x1 rows",
                f"chunks[1].markers[{index}]",
            )
        if not isinstance(marker_id, int) or marker_id in marker_ids:
            _issue(
                issues,
                "marker_id_invalid",
                "marker ids must be unique integers",
                f"chunks[1].markers[{index}].id",
            )
        else:
            marker_ids.add(marker_id)
    properties = map_data.get("objectsProperties")
    missing_property_keys = sorted(
        set(NATIVE_OBJECT_PROPERTY_KEYS) - set(properties)
    ) if isinstance(properties, dict) else []
    if missing_property_keys:
        _issue(
            issues,
            "native_property_schema_missing",
            "objectsProperties must include every native serialized property list",
            "chunks[1].objectsProperties",
            missing=missing_property_keys,
        )
    entity_sids: set[str] = set()
    if not isinstance(properties, dict):
        _issue(
            issues,
            "object_properties_missing",
            "objectsProperties must be an object",
            "chunks[1].objectsProperties",
        )
        return set()
    for name, rows in properties.items():
        if not isinstance(rows, list):
            _issue(
                issues,
                "property_array_invalid",
                f"{name} must be a list",
                f"chunks[1].objectsProperties.{name}",
            )
            continue
        for index, row in enumerate(rows):
            path = f"chunks[1].objectsProperties.{name}[{index}]"
            if not isinstance(row, dict):
                _issue(issues, "property_row_invalid", "property row must be an object", path)
                continue
            reference_type = row.get("type")
            reference_id = row.get("id")
            target_ids = object_ids if reference_type == 0 else marker_ids if reference_type == 1 else None
            if target_ids is None or reference_id not in target_ids:
                _issue(
                    issues,
                    "property_reference_unresolved",
                    f"property references missing type/id target ({reference_type}, {reference_id})",
                    path,
                )
            if name == "propEntities":
                sid = str(row.get("sid") or "").strip()
                if not sid:
                    _issue(issues, "entity_sid_missing", "entity sid cannot be empty", path)
                elif sid in entity_sids:
                    _issue(
                        issues,
                        "entity_sid_duplicate",
                        f"duplicate entity sid {sid}",
                        path,
                    )
                else:
                    entity_sids.add(sid)
    property_ids = {
        name: {
            int(row["id"])
            for row in rows
            if isinstance(row, dict)
            and row.get("type") == 0
            and isinstance(row.get("id"), int)
        }
        for name, rows in properties.items()
        if isinstance(rows, list)
    }
    for index, row in enumerate(properties.get("propCities", [])):
        if not isinstance(row, dict):
            continue
        faction_sid = str(row.get("factionSid") or "")
        construction_sid = row.get("buildingsConstructionSid")
        if (
            faction_sid.startswith("homm3_")
            and construction_sid != HOMM3_CUSTOM_TOWN_BUILDINGS_CONSTRUCTION_SID
        ):
            _issue(
                issues,
                "custom_town_siege_wall_construction_invalid",
                "custom HoMM3 towns must use the constructed-wall building preset",
                f"chunks[1].objectsProperties.propCities[{index}].buildingsConstructionSid",
                factionSid=faction_sid,
                constructionSid=construction_sid,
            )
    city_spawn_ids = property_ids.get("propCities", set()) & property_ids.get(
        "propSpawns", set()
    )
    invalid_city_hosts = sorted(
        object_id
        for object_id in city_spawn_ids
        if object_sid_by_id.get(object_id) != "city-spawner"
    )
    if invalid_city_hosts:
        _issue(
            issues,
            "city_spawn_host_invalid",
            "city spawn rows must be hosted by the native city-spawner ObjectConfig",
            "chunks[1].objectsProperties.propCities",
            objectIds=invalid_city_hosts,
        )
    invalid_spawn_point_ids = sorted(
        int(row["id"])
        for row in properties.get("propSpawns", [])
        if isinstance(row, dict)
        and row.get("type") == 0
        and row.get("id") in city_spawn_ids
        and row.get("spawnPointType") != 0
    )
    if invalid_spawn_point_ids:
        _issue(
            issues,
            "city_spawn_point_type_invalid",
            "city-defined spawns must use native city spawnPointType 0",
            "chunks[1].objectsProperties.propSpawns",
            objectIds=invalid_spawn_point_ids,
        )
    for family, required_sids in (
        ("propResParams", RESOURCE_SIDS),
        ("propRewardParams", REWARD_PARAMETER_SIDS),
        ("propVariants", VARIANT_SIDS),
    ):
        missing = sorted(
            object_id
            for object_id, sid in object_sid_by_id.items()
            if sid in required_sids and object_id not in property_ids.get(family, set())
        )
        if missing:
            _issue(
                issues,
                "native_property_contract_missing",
                f"native objects require {family} rows",
                f"chunks[1].objectsProperties.{family}",
                objectIds=missing,
            )
    random_squad_ids = {
        int(row["id"])
        for row in properties.get("propRandomSquads", [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    exact_squad_ids = {
        int(row["id"])
        for row in properties.get("propSquads", [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    random_object_ids = {
        int(object_id)
        for group in objects
        if isinstance(group, dict) and group.get("sid") == "random-squad"
        for object_id in group.get("ids", [])
        if isinstance(object_id, int)
    }
    random_rows_by_id = {
        int(row["id"]): row
        for row in properties.get("propRandomSquads", [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    for object_id in sorted(random_object_ids):
        has_exact = object_id in exact_squad_ids
        has_random = object_id in random_squad_ids
        if has_exact == has_random:
            _issue(
                issues,
                "squad_properties_mode_invalid",
                "random-squad encounter objects require exactly one native squad property mode",
                "chunks[1].objectsProperties",
                objectId=object_id,
            )
        if has_random:
            row = random_rows_by_id[object_id]
            requested = row.get("requestedValue")
            if (
                isinstance(requested, bool)
                or not isinstance(requested, (int, float))
                or requested <= 0
                or not isinstance(row.get("sids"), list)
                or any(not isinstance(value, str) for value in row["sids"])
                or not isinstance(row.get("fraction"), str)
                or isinstance(row.get("tier"), bool)
                or not isinstance(row.get("tier"), int)
                or row["tier"] < 0
                or not isinstance(row.get("customTopUnit"), str)
                or not row["customTopUnit"].strip()
            ):
                _issue(
                    issues,
                    "random_squad_properties_invalid",
                    "propRandomSquads requires a positive value, faction, tier, and custom top unit",
                    "chunks[1].objectsProperties.propRandomSquads",
                    objectId=object_id,
                )
    for index, row in enumerate(properties.get("propSquads", [])):
        if not isinstance(row, dict):
            continue
        unit_props = row.get("unitProps")
        if (
            not isinstance(unit_props, list)
            or not unit_props
            or any(
                not isinstance(unit, dict)
                or not str(unit.get("sid") or "").strip()
                or not isinstance(unit.get("count"), int)
                or isinstance(unit.get("count"), bool)
                or unit["count"] <= 0
                for unit in unit_props
            )
        ):
            _issue(
                issues,
                "exact_squad_units_invalid",
                "propSquads requires non-empty unitProps with SID and positive count",
                f"chunks[1].objectsProperties.propSquads[{index}].unitProps",
            )
    city_ids = {
        int(row["id"])
        for row in properties.get("propCities", [])
        if isinstance(row, dict) and isinstance(row.get("id"), int)
    }
    missing_city_random = sorted(city_ids - random_squad_ids)
    if missing_city_random:
        _issue(
            issues,
            "city_random_squad_properties_missing",
            "city objects require an explicit propRandomSquads row",
            "chunks[1].objectsProperties.propCities",
            objectIds=missing_city_random,
        )
    return entity_sids


def _validate_events(
    script: dict[str, Any],
    sidecar: Any,
    profile: Any,
    dialog_chunk: dict[str, Any],
    entity_sids: set[str],
    issues: list[ValidationIssue],
) -> None:
    counters = script.get("counters")
    if not isinstance(counters, list):
        _issue(issues, "counters_invalid", "script counters must be a list", "chunks[3].counters")
        counters = []
    declared = [str(row.get("sid") or "") for row in counters if isinstance(row, dict)]
    if any(not sid for sid in declared) or len(set(declared)) != len(declared):
        _issue(
            issues,
            "counter_declarations_invalid",
            "counter SIDs must be non-empty and unique",
            "chunks[3].counters",
        )
    counter_ops = {
        "CounterSet",
        "CounterPlus",
        "Counter",
        "CounterEqual",
        "CounterEqualityInDays",
    }
    referenced: set[str] = set()
    victory_rows: list[dict[str, Any]] = []
    dialog_actions: list[dict[str, Any]] = []
    for row in _walk_native_rows(script):
        opcode = row.get("a") or row.get("c")
        params = row.get("p") or []
        if opcode in counter_ops and params:
            referenced.add(str(params[0]))
        if opcode in {"ObjectInteractionAfter", "SquadKill", "ObjectCaptureEntity"}:
            target_sid = str(params[0]) if params else ""
            if not target_sid or target_sid not in entity_sids:
                _issue(
                    issues,
                    "event_entity_unresolved",
                    "event condition references an undeclared map entity SID",
                    "chunks[3]",
                    opcode=opcode,
                    sid=target_sid,
                )
        if opcode == "GameVictory":
            victory_rows.append(row)
        if opcode in {"Dialog", "Print"}:
            dialog_actions.append(row)
    missing = sorted(referenced - set(declared))
    if missing:
        _issue(
            issues,
            "counter_reference_undeclared",
            "script references undeclared counters",
            "chunks[3]",
            counters=missing,
        )
    if len(victory_rows) != 1:
        _issue(
            issues,
            "victory_contract_count",
            "script must contain exactly one explicit GameVictory action",
            "chunks[3]",
            actual=len(victory_rows),
        )
    sidecar_counters = sidecar.get("counters") if isinstance(sidecar, dict) else None
    if not isinstance(sidecar_counters, list):
        _issue(issues, "sidecar_invalid", "sidecar counters must be a list", "maps/*.json")
    else:
        sidecar_declared = [
            str(row.get("sid") or "") for row in sidecar_counters if isinstance(row, dict)
        ]
        if sidecar_declared != declared:
            _issue(
                issues,
                "sidecar_counter_mismatch",
                "sidecar counter declarations do not match the embedded script",
                "maps/*.json",
            )
    profile_doc = _jsonable(profile)
    text_mode = "none"
    if isinstance(profile_doc, dict):
        settings = profile_doc.get("text_provider", profile_doc.get("textProvider", {}))
        if isinstance(settings, dict):
            text_mode = str(settings.get("mode", "none"))
        else:
            text_mode = str(profile_doc.get("text_mode", "none"))
    if text_mode == "none":
        lines = (
            dialog_chunk.get("dialogs", {}).get("lines", [])
            if isinstance(dialog_chunk, dict)
            else []
        )
        if dialog_actions or lines:
            _issue(
                issues,
                "textless_dialog_forbidden",
                "text mode none forbids Dialog/Print actions and embedded dialog lines",
                "chunks[2:4]",
            )


def _validate_quest_localization(
    script: Mapping[str, Any],
    delta_doc: Any,
    map_sid: str,
    issues: list[ValidationIssue],
) -> None:
    """Visible quest name/desc must be LocKit SIDs covered by customMaps upserts."""

    sid_re = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    required: set[str] = set()
    inline_labels: list[str] = []
    quests = script.get("quests") if isinstance(script, Mapping) else None
    if not isinstance(quests, list):
        return
    for quest in quests:
        if not isinstance(quest, Mapping):
            continue
        rows = [quest, *list(quest.get("subQuests") or [])]
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            # Hidden support groups may keep empty labels like native maps.
            if row.get("hidden") is True:
                continue
            for field_name in ("name", "desc"):
                value = row.get(field_name)
                if value is None:
                    continue
                if not isinstance(value, str):
                    inline_labels.append(f"{row.get('sid')}.{field_name}")
                    continue
                text = value.strip()
                if not text:
                    continue
                if " " in text or not sid_re.fullmatch(text):
                    inline_labels.append(text)
                else:
                    required.add(text)
    if inline_labels:
        _issue(
            issues,
            "quest_label_not_lockit_sid",
            "visible quest name/desc must be LocKit SIDs; inline text renders as LOC:",
            "chunks[3].quests",
            labels=sorted(set(inline_labels))[:20],
        )
    if not required:
        return
    operations = delta_doc.get("operations") if isinstance(delta_doc, Mapping) else None
    if not isinstance(operations, list):
        _issue(
            issues,
            "quest_loc_deltas_missing",
            "quest LocKit SIDs require customMaps Core delta upserts",
            "core_deltas.json.operations",
            sids=sorted(required),
        )
        return
    provided: set[str] = set()
    locales_tokens: set[str] = set()
    locales_array: set[str] = set()
    for row in operations:
        if not isinstance(row, Mapping):
            continue
        member = str(row.get("member") or "")
        if not member.endswith("/texts/customMaps.json"):
            continue
        parts = member.split("/")
        if len(parts) < 4 or parts[0] != "Lang":
            continue
        locale = parts[1]
        path = row.get("path")
        if row.get("operation") != "upsert_array" or not isinstance(path, list):
            continue
        if path == ["tokens"]:
            locales_tokens.add(locale)
        elif path == ["array"]:
            locales_array.add(locale)
        else:
            continue
        for token in row.get("rows") or []:
            if not isinstance(token, Mapping):
                continue
            sid = str(token.get("sid") or "")
            text = token.get("text")
            if sid in required and isinstance(text, str) and text.strip():
                provided.add(sid)
    missing = sorted(required - provided)
    if missing:
        _issue(
            issues,
            "quest_loc_rows_missing",
            "quest LocKit SIDs lack non-empty customMaps upsert rows",
            "core_deltas.json.operations",
            sids=missing,
            mapSid=map_sid,
        )
    expected_locales = set(CORE_CUSTOM_MAPS_LOCALES)
    if locales_tokens != expected_locales or locales_array != expected_locales:
        _issue(
            issues,
            "quest_loc_locale_coverage",
            "quest LocKit upserts must cover tokens and array for every Core customMaps locale",
            "core_deltas.json.operations",
            missingTokens=sorted(expected_locales - locales_tokens),
            missingArray=sorted(expected_locales - locales_array),
        )


def _validate_encounter_ir(placements: Any, issues: list[ValidationIssue]) -> None:
    rows = _jsonable(placements)
    if not isinstance(rows, list):
        return
    for index, placement in enumerate(rows):
        if not isinstance(placement, Mapping) or _field(placement, "kind") not in {"encounter", "guard"}:
            continue
        path = f"placements[{index}].metadata"
        metadata = _field(placement, "metadata")
        if not isinstance(metadata, Mapping) or _field(metadata, "squad_mode") != "exact":
            _issue(issues, "encounter_squad_mode_invalid", "encounters must use exact squad mode", path)
            continue
        exact = _field(metadata, "exact_squad")
        instance = _field(metadata, "encounter_template_instance")
        if not isinstance(exact, Mapping) or not isinstance(instance, Mapping):
            _issue(issues, "encounter_template_instance_missing", "encounters require exactSquad and encounterTemplateInstance", path)
            continue
        unit_props = _field(exact, "unit_props")
        if (
            not str(_field(exact, "sid", "") or "")
            or not isinstance(unit_props, list)
            or not unit_props
            or any(
                not isinstance(unit, Mapping)
                or not str(unit.get("sid") or "")
                or isinstance(unit.get("count"), bool)
                or not isinstance(unit.get("count"), int)
                or unit["count"] <= 0
                for unit in unit_props
            )
        ):
            _issue(issues, "encounter_exact_squad_invalid", "exactSquad requires SID and positive unitProps", f"{path}.exactSquad")
        template = instance.get("template")
        guards = instance.get("guards")
        buildings = instance.get("buildings")
        pickups = instance.get("pickups")
        if not isinstance(template, Mapping):
            _issue(issues, "encounter_template_missing", "template instance requires the selected native template", f"{path}.encounterTemplateInstance.template")
            continue
        width, height = template.get("width"), template.get("height")
        tiles = template.get("tileContents")
        if (
            isinstance(width, bool)
            or not isinstance(width, int)
            or width <= 0
            or isinstance(height, bool)
            or not isinstance(height, int)
            or height <= 0
            or not isinstance(tiles, list)
            or len(tiles) != width * height
        ):
            _issue(issues, "encounter_template_shape_invalid", "native template dimensions and tileContents are inconsistent", f"{path}.encounterTemplateInstance.template")
        if not isinstance(guards, list) or not guards:
            _issue(issues, "encounter_template_guards_missing", "instantiated template requires a guard", f"{path}.encounterTemplateInstance.guards")
        for slot_name, slots in (("buildings", buildings), ("pickups", pickups)):
            if not isinstance(slots, list) or any(
                not isinstance(slot, Mapping)
                or not str(_field(slot, "content_sid", "") or "")
                or not str(_field(slot, "entity_sid", "") or "")
                or not isinstance(slot.get("position"), Mapping)
                for slot in (slots if isinstance(slots, list) else [])
            ):
                _issue(issues, "encounter_template_slots_invalid", "instantiated template slots require content, entity, and position", f"{path}.encounterTemplateInstance.{slot_name}")


def _validate_seer_script(scenario: Any, issues: list[ValidationIssue]) -> None:
    profile = _field(scenario, "profile")
    event_policy = _field(profile, "event_policy")
    expected_count = int(_field(event_policy, "seer_hut_count", 0) or 0)
    flattened = _jsonable(_field(scenario, "seer_script_triggers")) or []
    subquests = _jsonable(_field(scenario, "seer_script_subquests")) or []

    if expected_count <= 0:
        if flattened or subquests:
            _issue(
                issues,
                "seer_payload_without_configured_huts",
                "Seer script rows require eventPolicy.seerHutCount > 0",
                "seer_script_subquests",
            )
        return

    if len(subquests) != expected_count * 4:
        _issue(
            issues,
            "seer_stage_count_invalid",
            "each generated Seer Hut must have offer/incomplete/ready/complete stages",
            "seer_script_subquests",
            expected=expected_count * 4,
            actual=len(subquests),
        )
        return
    if not isinstance(flattened, list):
        _issue(
            issues,
            "seer_flattened_script_invalid",
            "seer_script_triggers must be a list",
            "seer_script_triggers",
        )
        flattened = []

    grouped: dict[str, list[Mapping[str, Any]]] = {}
    flattened_count = 0
    for index, row in enumerate(subquests):
        if not isinstance(row, Mapping):
            _issue(
                issues,
                "seer_subquest_row_invalid",
                "Seer subquest rows must be objects",
                f"seer_script_subquests[{index}]",
            )
            continue
        quest_sid = str(row.get("questSid") or "").strip()
        subquest_sid = str(row.get("sid") or "").strip()
        triggers = row.get("triggers")
        if not quest_sid or not subquest_sid or not isinstance(triggers, list):
            _issue(
                issues,
                "seer_subquest_shape_invalid",
                "Seer subquest requires questSid, sid, and triggers",
                f"seer_script_subquests[{index}]",
            )
            continue
        grouped.setdefault(quest_sid, []).append(row)
        flattened_count += len(triggers)
        if bool(row.get("activeOnStart")) != subquest_sid.endswith("_offer"):
            _issue(
                issues,
                "seer_initial_stage_invalid",
                "only the Seer offer stage must be active at quest start",
                f"seer_script_subquests[{index}].activeOnStart",
            )

    if flattened_count != len(flattened):
        _issue(
            issues,
            "seer_flattened_stage_mismatch",
            "flattened Seer triggers must describe exactly the isolated stage triggers",
            "seer_script_triggers",
            expected=flattened_count,
            actual=len(flattened),
        )
    if len(grouped) != expected_count:
        _issue(
            issues,
            "seer_quest_group_count_invalid",
            "Seer subquest rows must group into one quest per configured hut",
            "seer_script_subquests",
            expected=expected_count,
            actual=len(grouped),
        )
        return

    for quest_sid, rows in grouped.items():
        expected_stages = {
            f"{quest_sid}_offer",
            f"{quest_sid}_incomplete",
            f"{quest_sid}_ready",
            f"{quest_sid}_complete",
        }
        if {str(row.get("sid") or "") for row in rows} != expected_stages:
            _issue(
                issues,
                "seer_stage_ids_invalid",
                "Seer must use offer/incomplete/ready/complete stages for each quest",
                f"seer_script_subquests[{quest_sid}]",
            )
        for row in rows:
            for trigger in row.get("triggers") or []:
                if not isinstance(trigger, Mapping):
                    continue
                for action in trigger.get("actions") or []:
                    if not isinstance(action, Mapping):
                        continue
                    action_name = action.get("a")
                    params = action.get("p")
                    if action_name in {
                        "SubQuestActivate",
                        "SubQuestDone",
                        "SubQuestDeactivate",
                    } and not (
                        isinstance(params, list)
                        and len(params) == 2
                        and params[0] == quest_sid
                    ):
                        _issue(
                            issues,
                            "seer_stage_transition_unscoped",
                            "Seer stage transitions must target their owning quest",
                            f"seer_script_subquests[{quest_sid}]",
                            action=action_name,
                        )


def _validate_presentation(
    manifest: Mapping[str, Any],
    script: Mapping[str, Any],
    delta_doc: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> None:
    dialog_sids = [
        str((row.get("p") or [""])[0])
        for row in _walk_native_rows(script)
        if row.get("a") == "Dialog" and isinstance(row.get("p"), list) and row.get("p")
    ]
    presentation = manifest.get("presentation")
    if presentation is None:
        if dialog_sids:
            _issue(
                issues,
                "presentation_manifest_missing",
                "Dialog actions require presentation provenance and Core bindings",
                "manifest.json.presentation",
            )
        return
    if not isinstance(presentation, Mapping):
        _issue(issues, "presentation_manifest_invalid", "presentation must be an object", "manifest.json.presentation")
        return
    status = presentation.get("status")
    bindings = presentation.get("eventBindings")
    if not isinstance(bindings, list):
        _issue(issues, "presentation_bindings_invalid", "eventBindings must be a list", "manifest.json.presentation.eventBindings")
        return
    if status == "textless":
        if dialog_sids or bindings or presentation.get("dialogCount") != 0:
            _issue(
                issues,
                "textless_presentation_invalid",
                "textless presentation cannot contain dialogs or event bindings",
                "manifest.json.presentation",
            )
        return
    if status != "generated":
        _issue(issues, "presentation_status_invalid", "presentation status must be textless or generated", "manifest.json.presentation.status")
        return
    if presentation.get("dialogCount") != len(bindings) or not bindings:
        _issue(issues, "presentation_count_mismatch", "dialogCount must equal a non-empty eventBindings list", "manifest.json.presentation")
    operation_rows = delta_doc.get("operations") if isinstance(delta_doc, Mapping) else None
    if not isinstance(operation_rows, list):
        _issue(issues, "presentation_deltas_missing", "generated presentation requires Core delta operations", "core_deltas.json.operations")
        return
    operations = {
        str(row.get("id")): row
        for row in operation_rows
        if isinstance(row, Mapping) and str(row.get("id") or "")
    }
    declared_ids = presentation.get("coreDeltaIds")
    if not isinstance(declared_ids, list) or any(not isinstance(value, str) for value in declared_ids):
        _issue(issues, "presentation_delta_ids_invalid", "coreDeltaIds must be a list of operation IDs", "manifest.json.presentation.coreDeltaIds")
        declared_ids = []
    missing_ids = sorted(set(declared_ids) - set(operations))
    if missing_ids:
        _issue(issues, "presentation_delta_missing", "presentation references missing Core delta operations", "manifest.json.presentation.coreDeltaIds", ids=missing_ids)
    generated_ids = {
        operation_id
        for operation_id in operations
        if ":presentation:" in operation_id
    }
    if set(declared_ids) != generated_ids:
        _issue(
            issues,
            "presentation_delta_id_mismatch",
            "coreDeltaIds must name every presentation Core operation exactly",
            "manifest.json.presentation.coreDeltaIds",
            declared=sorted(set(declared_ids)),
            actual=sorted(generated_ids),
        )
    locale_member = presentation.get("localeMember")
    locale_rows = [
        row
        for row in operation_rows
        if isinstance(row, Mapping)
        and row.get("member") == locale_member
        and row.get("operation") == "upsert_array"
    ]
    locale_tokens = {
        str(token.get("sid"))
        for row in locale_rows
        for token in row.get("rows", [])
        if isinstance(token, Mapping) and token.get("sid")
    }
    locale_paths = {
        tuple(row.get("path", []))
        for row in locale_rows
        if isinstance(row.get("path"), list)
    }
    if locale_paths != {("tokens",), ("array",)}:
        _issue(
            issues,
            "presentation_locale_delta_invalid",
            "generated presentation requires tokens and array locale upserts",
            "core_deltas.json.operations",
        )
    bound_dialogs: list[str] = []
    event_ids: set[str] = set()
    for index, binding in enumerate(bindings):
        path = f"manifest.json.presentation.eventBindings[{index}]"
        if not isinstance(binding, Mapping):
            _issue(issues, "presentation_binding_invalid", "event binding must be an object", path)
            continue
        event_id = str(binding.get("eventId") or "")
        dialog_sid = str(binding.get("dialogSid") or "")
        member = str(binding.get("member") or "")
        title_sid = str(binding.get("titleSid") or "")
        body_sid = str(binding.get("bodySid") or "")
        if not all((event_id, dialog_sid, member, title_sid, body_sid)) or event_id in event_ids:
            _issue(issues, "presentation_binding_invalid", "binding fields must be non-empty and event IDs unique", path)
            continue
        event_ids.add(event_id)
        bound_dialogs.append(dialog_sid)
        dialog_ops = [
            row
            for row in operation_rows
            if isinstance(row, Mapping)
            and row.get("member") == member
            and row.get("operation") == "create_json_member"
        ]
        if len(dialog_ops) != 1:
            _issue(issues, "presentation_dialog_delta_invalid", "each binding requires exactly one dialog create_json_member operation", path)
        else:
            value = dialog_ops[0].get("value")
            rows = value.get("array") if isinstance(value, Mapping) else None
            if not isinstance(rows, list) or not any(
                isinstance(row, Mapping) and row.get("id") == dialog_sid for row in rows
            ):
                _issue(issues, "presentation_dialog_sid_unresolved", "dialog delta does not declare the bound dialog SID", path)
        missing_tokens = sorted({title_sid, body_sid} - locale_tokens)
        if missing_tokens:
            _issue(issues, "presentation_locale_token_missing", "bound dialog localization tokens are missing from Core deltas", path, sids=missing_tokens)
    if sorted(dialog_sids) != sorted(bound_dialogs):
        _issue(
            issues,
            "presentation_action_binding_mismatch",
            "Dialog actions must match presentation eventBindings exactly",
            "chunks[3]",
            actions=sorted(dialog_sids),
            bindings=sorted(bound_dialogs),
        )


def _node_id(row: Any) -> str:
    if not isinstance(row, dict):
        return ""
    return str(
        row.get("node_id")
        or row.get("nodeId")
        or row.get("zone_id")
        or row.get("zoneId")
        or row.get("id")
        or ""
    )


def _validate_preview(preview: Any, issues: list[ValidationIssue]) -> None:
    if not isinstance(preview, dict):
        _issue(issues, "preview_invalid", "preview.json must contain an object", "preview.json")
        return
    size = preview.get("size")
    if size not in {32, 48, 64}:
        _issue(issues, "preview_size_invalid", "preview size must be 32, 48, or 64", "preview.json.size")
    topology = preview.get("topology")
    if not isinstance(topology, dict):
        _issue(issues, "topology_missing", "topology must be an object", "preview.json.topology")
    else:
        nodes_value = topology.get("nodes", topology.get("zones"))
        edges_value = topology.get("edges", topology.get("routes"))
        if not isinstance(nodes_value, list) or not nodes_value:
            _issue(issues, "topology_nodes_missing", "topology requires a non-empty nodes list", "preview.json.topology.nodes")
        if not isinstance(edges_value, list):
            _issue(issues, "topology_edges_missing", "topology requires an edges list", "preview.json.topology.edges")
        start_value = (
            topology.get("start_node_id")
            or topology.get("startNodeId")
            or topology.get("start_zone_id")
            or topology.get("startZoneId")
        )
        if not start_value and isinstance(nodes_value, list):
            start_value = next(
                (
                    _node_id(row)
                    for row in nodes_value
                    if isinstance(row, dict)
                    and str(row.get("role") or row.get("kind") or "") == "start"
                ),
                "",
            )
        if not start_value:
            _issue(issues, "topology_start_missing", "topology requires a declared start node", "preview.json.topology")
        objective_values = topology.get(
            "objective_node_ids",
            topology.get(
                "objectiveNodeIds",
                topology.get("objective_zone_ids", topology.get("objectiveZoneIds", [])),
            ),
        )
        role_objectives = [
            _node_id(row)
            for row in nodes_value or []
            if isinstance(row, dict)
            and str(row.get("role") or row.get("kind") or "")
            in {"objective", "victory", "boss"}
        ] if isinstance(nodes_value, list) else []
        if not objective_values and not role_objectives and not (
            topology.get("victory_zone_id") or topology.get("victoryZoneId")
        ):
            _issue(issues, "topology_objective_missing", "topology requires at least one objective node", "preview.json.topology")
    if isinstance(topology, dict):
        nodes = topology.get("nodes", topology.get("zones", []))
        edges = topology.get("edges", topology.get("routes", []))
        if isinstance(nodes, list) and isinstance(edges, list) and nodes:
            node_ids = {_node_id(row) for row in nodes}
            if "" in node_ids or len(node_ids) != len(nodes):
                _issue(
                    issues,
                    "topology_node_ids",
                    "topology node IDs must be non-empty and unique",
                    "preview.json.topology.nodes",
                )
            adjacency = {node: set() for node in node_ids if node}
            for index, edge in enumerate(edges):
                if not isinstance(edge, dict):
                    _issue(
                        issues,
                        "topology_edge_invalid",
                        "topology edge must be an object",
                        f"preview.json.topology.edges[{index}]",
                    )
                    continue
                source = str(
                    edge.get("source")
                    or edge.get("sourceZoneId")
                    or edge.get("from")
                    or edge.get("a")
                    or ""
                )
                target = str(
                    edge.get("target")
                    or edge.get("targetZoneId")
                    or edge.get("to")
                    or edge.get("b")
                    or ""
                )
                if source not in adjacency or target not in adjacency:
                    _issue(
                        issues,
                        "topology_edge_unresolved",
                        "topology edge endpoint does not resolve",
                        f"preview.json.topology.edges[{index}]",
                    )
                    continue
                adjacency[source].add(target)
                if not bool(edge.get("directed", False)):
                    adjacency[target].add(source)
            start = str(
                topology.get("start_node_id")
                or topology.get("startNodeId")
                or topology.get("start_zone_id")
                or topology.get("startZoneId")
                or next(
                    (
                        _node_id(row)
                        for row in nodes
                        if isinstance(row, dict)
                        and str(row.get("role") or row.get("kind") or "") == "start"
                    ),
                    "",
                )
            )
            objectives = {
                _node_id(row)
                for row in nodes
                if isinstance(row, dict)
                and str(row.get("role") or row.get("kind") or "")
                in {"objective", "victory", "boss"}
            }
            objectives.update(
                str(item)
                for item in topology.get(
                    "objective_node_ids",
                    topology.get(
                        "objectiveNodeIds",
                        topology.get(
                            "objective_zone_ids",
                            topology.get("objectiveZoneIds", []),
                        ),
                    ),
                )
            )
            victory_zone_id = str(
                topology.get("victory_zone_id") or topology.get("victoryZoneId") or ""
            )
            if victory_zone_id:
                objectives.add(victory_zone_id)
            if start and start in adjacency:
                reached = {start}
                frontier = [start]
                while frontier:
                    current = frontier.pop()
                    for target in adjacency[current] - reached:
                        reached.add(target)
                        frontier.append(target)
                unreachable = sorted(objectives - reached)
                if unreachable:
                    _issue(
                        issues,
                        "objective_unreachable",
                        "one or more objective zones are unreachable from start",
                        "preview.json.topology",
                        nodes=unreachable,
                    )
    layout = preview.get("layout")
    if layout is not None and not isinstance(layout, dict):
        _issue(issues, "layout_invalid", "layout must be an object", "preview.json.layout")
    terrain = preview.get("terrain")
    blocked: set[int] = set()
    if not isinstance(terrain, dict):
        _issue(issues, "terrain_missing", "terrain must be an object", "preview.json.terrain")
    if isinstance(terrain, dict):
        raw_blocked = terrain.get("blocked", [])
        if isinstance(raw_blocked, list):
            if raw_blocked and all(isinstance(item, bool) for item in raw_blocked):
                blocked = {index for index, value in enumerate(raw_blocked) if value}
            else:
                blocked = {int(item) for item in raw_blocked if isinstance(item, int)}
    placements = preview.get("placements")
    if not isinstance(placements, list):
        _issue(issues, "placements_missing", "placements must be a list", "preview.json.placements")
    if isinstance(placements, list):
        size = int(preview.get("size") or 0)
        for index, placement in enumerate(placements):
            if not isinstance(placement, dict):
                continue
            if not bool(placement.get("interactive", False)):
                continue
            node = placement.get("node")
            origin = placement.get("origin")
            if isinstance(origin, dict):
                origin_xy = (int(origin.get("x", -1)), int(origin.get("y", -1)))
            elif isinstance(origin, list) and len(origin) == 2:
                origin_xy = (int(origin[0]), int(origin[1]))
            else:
                origin_xy = None
            if node is None and origin_xy is not None and size:
                node = origin_xy[1] * size + origin_xy[0]
            if node in blocked:
                _issue(
                    issues,
                    "interaction_blocked",
                    "interactive placement occupies a blocked node",
                    f"preview.json.placements[{index}]",
                    node=node,
                )
            footprint = placement.get("footprint", [])
            points = footprint
            if isinstance(footprint, dict):
                points = list(footprint.get("occupied") or []) + list(
                    footprint.get("interaction") or []
                )
            if isinstance(points, list) and size and origin_xy is not None:
                for point in points:
                    if isinstance(point, dict):
                        delta = (point.get("x"), point.get("y"))
                    elif isinstance(point, list) and len(point) == 2:
                        delta = (point[0], point[1])
                    else:
                        continue
                    x = origin_xy[0] + int(delta[0])
                    y = origin_xy[1] + int(delta[1])
                    if not (0 <= x < size and 0 <= y < size):
                        _issue(
                            issues,
                            "placement_footprint_bounds",
                            "placement footprint extends outside the map",
                            f"preview.json.placements[{index}].footprint",
                        )
                        break
    metrics = preview.get("metrics")
    if not isinstance(metrics, dict):
        _issue(issues, "metrics_missing", "metrics must be an object", "preview.json.metrics")
    if isinstance(metrics, dict):
        for key in ("gameplay_density", "visual_density"):
            value = metrics.get(
                key,
                metrics.get("".join([key.split("_")[0], key.split("_")[1].title()])),
            )
            if value is not None and (
                not isinstance(value, (int, float)) or not 0 <= float(value) <= 1
            ):
                _issue(
                    issues,
                    "density_out_of_range",
                    f"{key} must be in [0, 1]",
                    f"preview.json.metrics.{key}",
                )
        for key in ("gameplayDensityPer100Tiles", "sceneryDensityPer100Tiles"):
            value = metrics.get(key)
            if value is not None and (
                not isinstance(value, (int, float)) or not 0 <= float(value) <= 100
            ):
                _issue(
                    issues,
                    "density_out_of_range",
                    f"{key} must be in [0, 100]",
                    f"preview.json.metrics.{key}",
                )
        spacing = metrics.get(
            "meaningful_decision_spacing",
            metrics.get("decision_spacing_mean", metrics.get("decisionSpacingMean")),
        )
        if spacing is not None and (
            not isinstance(spacing, (int, float)) or not 6 <= float(spacing) <= 10
        ):
            _issue(
                issues,
                "decision_spacing_violation",
                "mean meaningful-decision spacing must be between 6 and 10 movement steps",
                "preview.json.metrics",
                actual=spacing,
            )


def validate_bundle(
    bundle_root: Path,
    *,
    check_determinism: bool = True,
) -> ValidationReport:
    bundle_root = Path(bundle_root).resolve()
    issues: list[ValidationIssue] = []
    checks = [
        "manifest_and_hashes",
        "container_and_chunks",
        "map_arrays_and_ids",
        "event_and_victory_contract",
        "preview_reachability_and_density",
        "core_delta_schema",
    ]
    manifest_path = bundle_root / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _issue(issues, "manifest_unreadable", str(exc), "manifest.json")
        return ValidationReport(str(bundle_root), tuple(issues), tuple(checks))
    if not isinstance(manifest, dict):
        _issue(
            issues,
            "manifest_root_invalid",
            "manifest root must be an object",
            "manifest.json",
        )
        return ValidationReport(str(bundle_root), tuple(issues), tuple(checks))
    if manifest.get("schema") != BUNDLE_SCHEMA:
        _issue(
            issues,
            "manifest_schema",
            f"manifest schema must be {BUNDLE_SCHEMA}",
            "manifest.json.schema",
        )
    _validate_source_hashes(manifest, issues)
    map_sid = str(manifest.get("mapSid") or "")
    if not MAP_SID_PATTERN.fullmatch(map_sid):
        _issue(issues, "map_sid_invalid", "manifest mapSid is not procedural", "manifest.json.mapSid")
    files = manifest.get("files")
    if not isinstance(files, dict):
        _issue(issues, "manifest_files", "manifest files must be an object", "manifest.json.files")
        files = {}
    required = {
        f"maps/{map_sid}.map",
        f"maps/{map_sid}.json",
        "profile.json",
        "preview.json",
        "core_deltas.json",
    }
    source_artifacts = manifest.get("sourceArtifacts")
    artifact_paths = (
        {str(path) for path in source_artifacts.values()}
        if isinstance(source_artifacts, Mapping)
        else set()
    )
    expected_files = required | artifact_paths
    if set(files) != expected_files:
        _issue(
            issues,
            "manifest_file_set",
            "manifest must name exactly the paired map, profile, preview, Core deltas, and source evidence",
            "manifest.json.files",
            missing=sorted(expected_files - set(files)),
            extra=sorted(set(files) - expected_files),
        )
    loaded: dict[str, bytes] = {}
    for relative, expected_hash in files.items():
        try:
            path = _safe_bundle_path(bundle_root, relative)
            payload = path.read_bytes()
        except (OSError, ValueError) as exc:
            _issue(issues, "bundle_file_unreadable", str(exc), str(relative))
            continue
        loaded[str(relative)] = payload
        actual = sha256_bytes(payload)
        if actual != expected_hash:
            _issue(
                issues,
                "bundle_hash_mismatch",
                "bundle file hash does not match manifest",
                str(relative),
                expected=expected_hash,
                actual=actual,
            )
    try:
        verify_source_artifacts(manifest, bundle_root)
    except (OSError, TypeError, ValueError) as exc:
        _issue(
            issues,
            "source_artifact_contract",
            str(exc),
            "manifest.json.sourceArtifacts",
        )
    map_relative = f"maps/{map_sid}.map"
    container = None
    if map_relative in loaded:
        try:
            container = parse_container_bytes(loaded[map_relative])
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            _issue(issues, "container_invalid", str(exc), map_relative)
    profile = {}
    preview = {}
    sidecar = {}
    delta_doc = {}
    for relative, target_name in (
        ("profile.json", "profile"),
        ("preview.json", "preview"),
        (f"maps/{map_sid}.json", "sidecar"),
        ("core_deltas.json", "delta"),
    ):
        if relative not in loaded:
            continue
        try:
            parsed = json.loads(loaded[relative].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _issue(issues, "json_invalid", str(exc), relative)
            continue
        if target_name == "profile":
            profile = parsed
        elif target_name == "preview":
            preview = parsed
        elif target_name == "sidecar":
            sidecar = parsed
        else:
            delta_doc = parsed
    script_for_presentation: Mapping[str, Any] = {}
    if container is not None:
        if len(container.chunks) < 4:
            _issue(
                issues,
                "container_chunks",
                "scenario container must contain at least four chunks",
                map_relative,
                actual=len(container.chunks),
            )
        else:
            meta, map_data, dialogs, script = container.chunks[:4]
            script_for_presentation = script if isinstance(script, Mapping) else {}
            if map_data.get("fileMapName") != map_sid:
                _issue(
                    issues,
                    "map_sid_mismatch",
                    "map data fileMapName differs from manifest mapSid",
                    "chunks[1].fileMapName",
                )
            expected_md5 = hashlib.md5(map_sid.encode("utf-8")).hexdigest()
            if meta.get("hashSum") != expected_md5:
                _issue(
                    issues,
                    "map_hashsum_mismatch",
                    "map metadata hashSum must be md5(mapSid)",
                    "chunks[0].hashSum",
                )
            campaign_info = meta.get("campaignInfo")
            expected_campaign_keys = {
                "missionNameSid",
                "missionDescSid",
                "campaignSid",
                "campaignDescSid",
                "hubIconSid",
            }
            if not isinstance(campaign_info, dict) or set(campaign_info) != expected_campaign_keys:
                _issue(
                    issues,
                    "campaign_info_schema",
                    "campaignInfo must use the native non-null five-field object shape",
                    "chunks[0].campaignInfo",
                )
            overrides = map_data.get("objectValuesOverrides")
            if not isinstance(overrides, dict) or not isinstance(overrides.get("list"), list):
                _issue(
                    issues,
                    "object_values_overrides_schema",
                    "objectValuesOverrides must be the native object wrapper with a list field",
                    "chunks[1].objectValuesOverrides",
                )
            _validate_start_settings(meta, issues)
            _validate_spawn_metadata(meta, issues, map_data=map_data)
            _validate_arrays(map_data, issues)
            _validate_areas(map_data, issues)
            _validate_settings(map_data, issues)
            entity_sids = _validate_objects(map_data, issues)
            _validate_events(script, sidecar, profile, dialogs, entity_sids, issues)
            _validate_quest_localization(script, delta_doc, map_sid, issues)
            if check_determinism:
                checks.append("deterministic_serialization")
                actual = loaded[map_relative]
                if len(actual) < 8 or actual[4:8] != b"\0\0\0\0":
                    _issue(
                        issues,
                        "gzip_timestamp_nondeterministic",
                        "gzip mtime must be zero",
                        map_relative,
                    )
                reproduced = serialize_container(container, expected_md5)
                if reproduced != actual:
                    _issue(
                        issues,
                        "container_nondeterministic",
                        "parse/serialize does not reproduce identical map bytes",
                        map_relative,
                    )
    _validate_preview(preview, issues)
    if not isinstance(delta_doc, dict) or delta_doc.get("schema") != CORE_DELTA_SCHEMA:
        _issue(
            issues,
            "core_delta_schema",
            f"core_deltas.json schema must be {CORE_DELTA_SCHEMA}",
            "core_deltas.json",
        )
    else:
        try:
            normalized = normalize_core_deltas(delta_doc, map_sid=map_sid)
            if normalized != delta_doc:
                _issue(
                    issues,
                    "core_delta_not_normalized",
                    "Core delta document is not in canonical normalized form",
                    "core_deltas.json",
                )
        except (TypeError, ValueError) as exc:
            _issue(issues, "core_delta_invalid", str(exc), "core_deltas.json")
    _validate_presentation(manifest, script_for_presentation, delta_doc, issues)
    return ValidationReport(str(bundle_root), tuple(issues), tuple(checks))


def validate_generated_ir(scenario: Any) -> ValidationReport:
    issues: list[ValidationIssue] = []
    map_sid = str(_field(scenario, "map_sid") or "")
    if not MAP_SID_PATTERN.fullmatch(map_sid):
        _issue(issues, "map_sid_invalid", "generated IR requires a procedural map SID", "map_sid")
    profile = _field(scenario, "profile")
    size = int(_field(scenario, "size", 0) or _field(profile, "map_size", 0))
    if size not in {32, 48, 64}:
        _issue(issues, "map_size_invalid", "map size must be 32, 48, or 64", "profile.map_size")
    preview = {
        "size": size,
        "topology": _jsonable(_field(scenario, "topology")),
        "layout": _jsonable(_field(scenario, "layout")),
        "terrain": _jsonable(_field(scenario, "terrain")),
        "placements": _jsonable(_field(scenario, "placements")),
        "metrics": _jsonable(_field(scenario, "metrics")),
    }
    _validate_preview(preview, issues)
    _validate_encounter_ir(_field(scenario, "placements"), issues)
    _validate_seer_script(scenario, issues)
    events = _field(scenario, "events")
    if not isinstance(events, (list, tuple)) or not events:
        _issue(issues, "events_missing", "generated IR requires a non-empty event list", "events")
    elif all(isinstance(event, MechanicalEventSpec) for event in events):
        declared = {
            row.counter_sid
            for event in events
            for row in tuple(event.triggers) + tuple(event.actions)
            if isinstance(row, (CounterTrigger, CounterAction))
        }
        try:
            compile_mechanical_events(events, declared_counter_sids=declared)
        except (TypeError, ValueError) as exc:
            _issue(issues, "events_invalid", str(exc), "events")
    else:
        serialized_events = _jsonable(events)
        victories = sum(
            1
            for row in _walk_native_rows(serialized_events)
            if row.get("a") == "GameVictory" or row.get("kind") == "victory"
        )
        if victories != 1:
            _issue(
                issues,
                "victory_contract_count",
                "generated IR must contain exactly one explicit victory action",
                "events",
                actual=victories,
            )
    placements = tuple(_field(scenario, "placements") or ())
    expected_ai = int(_field(profile, "ai_count", 0) or 0)
    actual_ai = sum(
        _field(placement, "kind") is PlacementKind.AI_SETTLEMENT
        for placement in placements
    )
    if actual_ai != expected_ai:
        _issue(
            issues,
            "ai_spawn_count_mismatch",
            "generated IR must contain one AI settlement/spawn per configured AI",
            "placements",
            expected=expected_ai,
            actual=actual_ai,
        )
    return ValidationReport(
        f"GeneratedScenarioIR:{map_sid}",
        tuple(issues),
        (
            "profile_and_sid",
            "topology_reachability",
            "placement_footprints",
            "event_and_victory_contract",
            "density",
        ),
    )
