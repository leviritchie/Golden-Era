"""Importable procedural map-load preflight used by CLI and frozen GUI builds."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any, Iterable

from tools import map_load_preflight as native_preflight

from .emitter import read_container


class ProceduralPreflightError(ValueError):
    pass


def _catalog_ids(
    archive: zipfile.ZipFile,
    prefixes: Iterable[str],
) -> set[str]:
    result: set[str] = set()
    prefix_tuple = tuple(prefixes)
    for member in sorted(archive.namelist()):
        if not member.endswith(".json") or not member.startswith(prefix_tuple):
            continue
        try:
            document = json.loads(archive.read(member).decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProceduralPreflightError(
                f"effective Core member is not valid JSON: {member}"
            ) from exc
        rows = document.get("array") if isinstance(document, dict) else None
        if not isinstance(rows, list):
            continue
        for row in rows:
            sid = row.get("id") if isinstance(row, dict) else None
            if isinstance(sid, str) and sid:
                result.add(sid)
    return result


def _require_refs(
    kind: str,
    references: set[str],
    available: set[str],
) -> None:
    missing = sorted(references - available)
    if missing:
        preview = ", ".join(missing[:12])
        suffix = "" if len(missing) <= 12 else f" (+{len(missing) - 12} more)"
        raise ProceduralPreflightError(
            f"effective Core is missing {kind} references: {preview}{suffix}"
        )


def validate_procedural_references(
    candidate_core: Path,
    candidate_map: Path,
) -> tuple[str, ...]:
    """Validate emitted typed references not covered by the shared map preflight."""

    chunks = read_container(candidate_map).chunks
    if len(chunks) < 4:
        raise ProceduralPreflightError("procedural map has fewer than four chunks")
    meta, map_data, _dialogs, script = chunks[:4]
    if not all(isinstance(row, dict) for row in (meta, map_data, script)):
        raise ProceduralPreflightError("procedural map chunks are malformed")

    factions: set[str] = set()
    heroes: set[str] = set()
    units: set[str] = set()
    squads: set[str] = set()
    dialogs: set[str] = set()
    building_bans: set[str] = set()
    building_settings: set[str] = set()
    building_constructions: set[str] = set()

    spawn_container = meta.get("spawns")
    if spawn_container is None:
        spawn_container = {}
    if not isinstance(spawn_container, dict):
        raise ProceduralPreflightError("map spawns must be an object")
    spawn_rows = spawn_container.get("spawns", [])
    if not isinstance(spawn_rows, list):
        raise ProceduralPreflightError("map spawns.spawns must be a list")
    for row in spawn_rows:
        if not isinstance(row, dict):
            raise ProceduralPreflightError("map spawn row must be an object")
        for key, target in (("factionSid", factions), ("heroSid", heroes)):
            sid = row.get(key)
            if isinstance(sid, str) and sid:
                target.add(sid)

    properties = map_data.get("objectsProperties")
    if not isinstance(properties, dict):
        raise ProceduralPreflightError("map objectsProperties must be an object")

    def property_rows(name: str) -> list[Any]:
        rows = properties.get(name, [])
        if not isinstance(rows, list):
            raise ProceduralPreflightError(
                f"map objectsProperties.{name} must be a list"
            )
        return rows

    for row in property_rows("propCities"):
        if not isinstance(row, dict):
            raise ProceduralPreflightError("propCities row must be an object")
        for key, target in (
            ("factionSid", factions),
            ("buildingsConstructionSid", building_constructions),
            ("buildingsBanSid", building_bans),
            ("buildingsSettingsSid", building_settings),
        ):
            sid = row.get(key)
            if isinstance(sid, str) and sid:
                target.add(sid)
    for row in property_rows("propHeroes"):
        if not isinstance(row, dict):
            raise ProceduralPreflightError("propHeroes row must be an object")
        sid = row.get("heroSid")
        if isinstance(sid, str) and sid:
            heroes.add(sid)
    for row in property_rows("propSquads"):
        if not isinstance(row, dict):
            raise ProceduralPreflightError("propSquads row must be an object")
        unit_props = row.get("unitProps")
        if not isinstance(unit_props, list):
            raise ProceduralPreflightError("propSquads.unitProps must be a list")
        for unit in unit_props:
            sid = unit.get("sid") if isinstance(unit, dict) else None
            if not isinstance(sid, str) or not sid:
                raise ProceduralPreflightError("propSquads unit row requires sid")
            units.add(sid)
    for row in property_rows("propRandomSquads"):
        if not isinstance(row, dict):
            raise ProceduralPreflightError("propRandomSquads row must be an object")
        faction = row.get("fraction")
        top_unit = row.get("customTopUnit")
        if isinstance(faction, str) and faction:
            factions.add(faction)
        if isinstance(top_unit, str) and top_unit:
            units.add(top_unit)
        raw_sids = row.get("sids")
        if not isinstance(raw_sids, list):
            raise ProceduralPreflightError("propRandomSquads.sids must be a list")
        for sid in raw_sids:
            if not isinstance(sid, str) or not sid:
                raise ProceduralPreflightError(
                    "propRandomSquads.sids must contain non-empty strings"
                )
            squads.add(sid)

    def walk(value: Any) -> Iterable[dict[str, Any]]:
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for row in walk(script):
        if row.get("a") != "Dialog":
            continue
        params = row.get("p")
        if not isinstance(params, list) or not params or not isinstance(params[0], str):
            raise ProceduralPreflightError("Dialog action requires a dialog SID")
        dialogs.add(params[0])

    with zipfile.ZipFile(candidate_core, "r") as archive:
        _require_refs("faction", factions, _catalog_ids(archive, ("DB/fractions/",)))
        _require_refs("hero", heroes, _catalog_ids(archive, ("DB/heroes/",)))
        _require_refs("unit", units, _catalog_ids(archive, ("DB/units/",)))
        _require_refs("squad", squads, _catalog_ids(archive, ("DB/squads/",)))
        _require_refs(
            "dialog",
            dialogs,
            _catalog_ids(archive, ("DB/dialogs/dialogs/",)),
        )
        _require_refs(
            "building-ban",
            building_bans,
            _catalog_ids(archive, ("DB/buildings_bans/",)),
        )
        _require_refs(
            "building-settings",
            building_settings,
            _catalog_ids(archive, ("DB/buildings_settings/",)),
        )
        _require_refs(
            "building-construction",
            building_constructions,
            _catalog_ids(archive, ("DB/buildings_constructions/",)),
        )
    return (
        "map_faction_references",
        "map_hero_references",
        "map_unit_references",
        "map_squad_references",
        "map_dialog_references",
        "map_building_policy_references",
        "map_building_construction_references",
    )


def run_preflight(
    candidate_core: Path,
    candidate_map: Path,
    map_sid: str,
) -> tuple[str, ...]:
    index = native_preflight.build_effective_core_index(candidate_core)
    issues = list(native_preflight.run_core_integrity_checks(index))
    native_preflight.check_map_sids_resolve(
        candidate_map, index, issues=issues, map_sid=map_sid
    )
    native_preflight.check_map_meta_random_res(
        candidate_map, issues=issues, map_sid=map_sid
    )
    native_preflight.check_map_random_item_rarity(
        candidate_map, issues=issues, map_sid=map_sid
    )
    native_preflight.check_map_city_construction_sids(
        candidate_map, index, issues=issues, map_sid=map_sid
    )
    native_preflight.check_map_quest_counter_sid_consistency(
        candidate_map, issues=issues, map_sid=map_sid
    )
    if issues:
        details = "; ".join(
            f"{getattr(issue, 'code', 'preflight')}: "
            f"{getattr(issue, 'message', issue)}"
            for issue in issues[:12]
        )
        raise ProceduralPreflightError(f"map-load preflight failed: {details}")
    checks = (
        "effective_core_integrity",
        "map_object_sid_resolution",
        "map_meta_resources",
        "map_item_rarity",
        "map_city_construction",
        "map_counter_consistency",
    )
    return checks + validate_procedural_references(candidate_core, candidate_map)
