#!/usr/bin/env python3
"""Emit HoMM3 true-neutral Core overlay rows from tools/homm3_import/faction_concepts/homm3_neutral.json."""

from __future__ import annotations

import copy
import json
import zipfile
from pathlib import Path
from typing import Any

from homm3_neutral_catalog import (
    catalog_dwellings,
    catalog_units,
    load_homm3_neutral_catalog,
    pool_eligible_unit_sids,
    unit_logic_path,
    unit_view_path,
)

ARENA_PICK_CONTENT_PATH = "DB/ai_pick/arena_pick_content.json"
MAP_OBJECTS_PATH = "DB/map/objects/4_interactables.json"
BARRACKS_HIRES_PATH = "DB/objects_logic/hires/barracks.json"
UNITS_LANG_PATH = "Lang/english/texts/units.json"
MAP_OBJECTS_LANG_PATH = "Lang/english/texts/mapObjects.json"


def _write_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _read_json(release_zip: zipfile.ZipFile, output: dict[str, bytes], name: str) -> Any:
    if name in output:
        return json.loads(output[name].decode("utf-8-sig"))
    return json.loads(release_zip.read(name).decode("utf-8-sig"))


def _upsert_array_row(doc: dict[str, Any], row: dict[str, Any]) -> bool:
    rows = doc.get("array")
    if not isinstance(rows, list):
        doc["array"] = [row]
        return True
    row_id = row.get("id")
    for index, existing in enumerate(rows):
        if isinstance(existing, dict) and existing.get("id") == row_id:
            if existing != row:
                rows[index] = row
                return True
            return False
    rows.append(row)
    return True


def _upsert_lang_rows_into_list(doc: dict[str, Any], key: str, rows: list[dict[str, str]], *, create: bool) -> bool:
    """Upsert localization rows into one LocKit list (tokens or array)."""
    tokens = doc.get(key)
    if not isinstance(tokens, list):
        if not create:
            return False
        tokens = []
        doc[key] = tokens
    by_sid: dict[str, int] = {}
    deduped: list[Any] = []
    changed = False
    for token in tokens:
        if not isinstance(token, dict):
            deduped.append(token)
            continue
        sid = token.get("sid")
        if isinstance(sid, str) and sid in by_sid:
            changed = True
            continue
        if isinstance(sid, str):
            by_sid[sid] = len(deduped)
        deduped.append(token)
    if len(deduped) != len(tokens):
        tokens[:] = deduped
    for row in rows:
        sid = row["sid"]
        if sid in by_sid:
            index = by_sid[sid]
            if tokens[index] != row:
                tokens[index] = row
                changed = True
        else:
            by_sid[sid] = len(tokens)
            tokens.append(row)
            changed = True
    return changed


def _upsert_lang_rows(doc: dict[str, Any], rows: list[dict[str, str]]) -> bool:
    # LocKit / multilingual sync read ``tokens``; some release packs still mirror
    # under ``array``. Writing array-only left neutral dwellings with blank UI text.
    changed = _upsert_lang_rows_into_list(doc, "tokens", rows, create=True)
    changed = _upsert_lang_rows_into_list(doc, "array", rows, create=False) or changed
    return changed


def _first_unit_row(doc: Any) -> dict[str, Any]:
    if not isinstance(doc, dict):
        raise KeyError("unit doc root must be object")
    rows = doc.get("array")
    if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
        raise KeyError("unit doc missing array[0]")
    return rows[0]


def _apply_stats(logic_row: dict[str, Any], unit: dict[str, Any]) -> None:
    stats_src = unit["stats"]
    stats = logic_row.setdefault("stats", {})
    if not isinstance(stats, dict):
        stats = {}
        logic_row["stats"] = stats
    for key in (
        "hp",
        "offence",
        "defence",
        "damageMin",
        "damageMax",
        "initiative",
        "speed",
        "ammo",
        "moveType",
        "numCounters",
    ):
        if key in stats_src:
            stats[key] = stats_src[key]
    logic_row["id"] = unit["sid"]
    logic_row["sid"] = unit["sid"]
    logic_row["tier"] = int(unit["tier"])
    logic_row["fraction"] = "neutral"
    logic_row["nativeBiome"] = unit.get("nativeBiome") or "Valleys"
    ai = unit.get("ai")
    if not isinstance(ai, str) or not ai:
        raise RuntimeError(f"{unit['sid']}: neutral catalog ai must be a non-empty string")
    # Must name a DB/ai_battle row family (<ai>_<difficulty>); tools/validate_unit_battle_ai_contract.py
    # checks the built Core, because an unresolved id softlocks AI auto-battles.
    logic_row["ai"] = ai
    logic_row["squadValue"] = int(stats_src["squadValue"])
    tags = unit.get("tags")
    if isinstance(tags, list):
        logic_row["tags"] = list(tags)
    logic_row["unitCost"] = {
        "costResArray": [{"name": "gold", "cost": int(stats_src["gold"])}]
    }


def _clone_unit_from_donor(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    unit: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    donor_faction = str(unit["donorFactionSid"])
    donor_unit = str(unit["donorUnitSid"])
    logic_name = f"DB/units/units_logics/{donor_faction}/{donor_unit}_l.json"
    view_name = f"DB/units/units_views/{donor_faction}/{donor_unit}_v.json"
    # Custom-faction donors (e.g. homm3_stronghold/h3_wolf_rider) are generated
    # earlier in the same overlay run, so read the pending overlay output first;
    # on a vanilla Core they do not exist in the archive yet.
    logic_doc = _read_json(release_zip, output, logic_name)
    view_doc = _read_json(release_zip, output, view_name)
    logic_row = copy.deepcopy(_first_unit_row(logic_doc))
    view_row = copy.deepcopy(_first_unit_row(view_doc))
    _apply_stats(logic_row, unit)
    view_row["id"] = unit["sid"]
    view_row["sid"] = unit["sid"]
    _strip_donor_line_identity(logic_row, view_row)
    logic_row["xHomm3ImplementationAudit"] = {
        "source": f"tools/homm3_import/faction_concepts/homm3_neutral.json:{unit['sid']}",
        "implementedData": (
            f"HoMM3/HotA neutral combat stats for {unit.get('displayName')}; donor "
            f"{donor_faction}/{donor_unit} supplies the attack/animation shell and passives only "
            "(no upgrade/base line, active abilities or role text). mesh/mapMesh are this unit's own "
            "homm3_import paths when it has an import row, else the donor's (listed stopgap)."
        ),
    }
    return {"array": [logic_row]}, {"array": [view_row]}


# Donor line identity a neutral must never inherit: the upgrade/base links would let a
# neutral stack upgrade into (or claim to be) a faction unit, active abilities are the
# donor's own kit, and the xHomm3 role keys describe the donor's faction line.
_DONOR_LINE_LOGIC_KEYS = ("upgradeSid", "baseSid")
_DONOR_ROLE_KEYS = (
    "xHomm3BranchRole",
    "xHomm3SourceMechanic",
    "xHomm3DecisionTest",
    "xHomm3CastleQuality",
    "xHomm3ReleaseQuality",
    "xHomm3BalanceRecommendation20260625",
)


def _strip_donor_line_identity(logic_row: dict[str, Any], view_row: dict[str, Any]) -> None:
    for key in _DONOR_LINE_LOGIC_KEYS:
        logic_row.pop(key, None)
        view_row.pop(key, None)
    for key in _DONOR_ROLE_KEYS:
        logic_row.pop(key, None)
        view_row.pop(key, None)
    logic_row["abilities"] = []
    view_row["abilities"] = []


def apply_homm3_neutral_own_view_meshes(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
    import_view_meshes: dict[str, dict[str, str]],
) -> None:
    """Point every catalog neutral that has a homm3_import row at its own mesh/mapMesh.

    Covers hand-authored rows (Fangarm) too, so this must run after every emitter that
    writes neutral views. A neutral without an import row keeps its donor paths; that
    stopgap is enumerated by tools/validate_homm3_unit_presentation_stopgap_contract.py.
    """
    catalog = load_homm3_neutral_catalog()
    changed = 0
    for unit in catalog_units(catalog):
        sid = str(unit["sid"])
        expected = import_view_meshes.get(sid)
        if not expected:
            continue
        name = unit_view_path(sid, catalog)
        doc = _read_json(release_zip, output, name)
        view_row = _first_unit_row(doc)
        if view_row.get("mesh") == expected["mesh"] and view_row.get("mapMesh") == expected["mapMesh"]:
            continue
        view_row["mesh"] = expected["mesh"]
        view_row["mapMesh"] = expected["mapMesh"]
        output[name] = _write_json(doc)
        changed += 1
    if changed:
        notes.append(f"point homm3_neutral UnitView mesh/mapMesh at own homm3_import paths ({changed})")


def homm3_neutral_donor_unit_sids() -> set[str]:
    """Donor unit sids the neutral clone reads (same skip rule as add_homm3_neutral_unit_rows)."""
    return {
        str(unit["donorUnitSid"])
        for unit in catalog_units(load_homm3_neutral_catalog())
        if unit.get("handAuthoredCore") is not True
    }


def add_homm3_neutral_unit_rows(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
) -> None:
    catalog = load_homm3_neutral_catalog()
    changed = 0
    for unit in catalog_units(catalog):
        sid = str(unit["sid"])
        if unit.get("handAuthoredCore") is True:
            # Fangarm stays owned by Cove hand-authored emitter; still ensure paths exist later.
            continue
        logic_doc, view_doc = _clone_unit_from_donor(release_zip, output, unit)
        output[unit_logic_path(sid, catalog)] = _write_json(logic_doc)
        output[unit_view_path(sid, catalog)] = _write_json(view_doc)
        changed += 2
    if changed:
        notes.append(f"generate homm3_neutral unit logic/view rows ({changed})")


def add_homm3_neutral_lang_rows(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
) -> None:
    catalog = load_homm3_neutral_catalog()
    unit_rows: list[dict[str, str]] = []
    map_rows: list[dict[str, str]] = []
    for unit in catalog_units(catalog):
        sid = str(unit["sid"])
        name = str(unit.get("displayName") or sid)
        unit_rows.append({"sid": f"{sid}_name", "text": name})
        unit_rows.append(
            {
                "sid": f"{sid}_narrativeDescription",
                "text": f"A HoMM3 neutral {name} available in the Olden Era wandering-monster pool.",
            }
        )
    for dwelling in catalog_dwellings(catalog):
        barracks_sid = str(dwelling["barracksSid"])
        creature = str(dwelling["displayName"])
        dwelling_name = str(dwelling["name"])
        description = f"An external dwelling that provides {creature} recruits."
        map_rows.append({"sid": f"{barracks_sid}_name", "text": dwelling_name})
        map_rows.append({"sid": f"{barracks_sid}_description", "text": description})
        map_rows.append({"sid": f"{barracks_sid}_narrativeDescription", "text": description})
    if unit_rows:
        doc = _read_json(release_zip, output, UNITS_LANG_PATH)
        if _upsert_lang_rows(doc, unit_rows):
            output[UNITS_LANG_PATH] = _write_json(doc)
            notes.append(f"merge homm3_neutral unit localization ({len(unit_rows)})")
    if map_rows:
        doc = _read_json(release_zip, output, MAP_OBJECTS_LANG_PATH)
        if _upsert_lang_rows(doc, map_rows):
            output[MAP_OBJECTS_LANG_PATH] = _write_json(doc)
            notes.append(f"merge homm3_neutral dwelling localization ({len(map_rows)})")


def merge_homm3_neutral_arena_pick(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
    *,
    faction_unit_sids: tuple[str, ...] = (),
) -> None:
    catalog = load_homm3_neutral_catalog()
    sids = list(dict.fromkeys([*faction_unit_sids, *pool_eligible_unit_sids(catalog)]))
    doc = _read_json(release_zip, output, ARENA_PICK_CONTENT_PATH)
    if not isinstance(doc, dict):
        raise RuntimeError(f"malformed {ARENA_PICK_CONTENT_PATH}")
    content = doc.get("content")
    if not isinstance(content, list):
        content = []
        doc["content"] = content
    bucket = next((row for row in content if isinstance(row, dict) and row.get("sid") == "units"), None)
    if bucket is None:
        bucket = {"sid": "units", "array": []}
        content.append(bucket)
    rows = bucket.get("array")
    if not isinstance(rows, list):
        rows = []
        bucket["array"] = rows
    existing = {row.get("sid") for row in rows if isinstance(row, dict)}
    changed = 0
    for sid in sids:
        if sid in existing:
            continue
        rows.append({"sid": sid, "val": 100})
        existing.add(sid)
        changed += 1
    if changed:
        output[ARENA_PICK_CONTENT_PATH] = _write_json(doc)
        notes.append(f"merge arena_pick unit pool (+{changed})")


def add_homm3_neutral_squad_templates(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
) -> None:
    catalog = load_homm3_neutral_catalog()
    core = catalog.get("coreOverlay") or {}
    target_prefix = str(core.get("squadTree") or "DB/squads/squads_homm3_neutral/")
    changed = 0
    for unit in catalog_units(catalog):
        if unit.get("poolEligible") is not True:
            continue
        sid = str(unit["sid"])
        tier = int(unit["tier"])
        squad_value = int(unit["stats"]["squadValue"])
        squad_id = f"squad_homm3_neutral_{sid}"
        member = f"{target_prefix}{squad_id}.json"
        doc = {
            "array": [
                {
                    "id": squad_id,
                    "squad": [],
                    "useOldSquads": False,
                    "rollChance": max(100, 1000 // max(1, tier)),
                    "canBeMainGuard": True,
                    "baseSquad": {"units": [{"s": sid, "v": squad_value}]},
                    "dynamicSquad": {"requiredValue": squad_value, "units": [sid]},
                    "randomSquad": {
                        "maxValue": squad_value * 4,
                        "units": [{"s": sid, "v": squad_value * 4}],
                    },
                    "tier": tier,
                    "fraction": "neutral",
                }
            ]
        }
        output[member] = _write_json(doc)
        changed += 1
    if changed:
        notes.append(f"generate homm3_neutral squad templates ({changed})")


# tier -> (guard stack amount, customGuardValue, aiValue, goodsValue), from vanilla barracks_human_4..7.
HIGH_TIER_DWELLING_GUARDS = {
    4: (12, 6000, 30000, 10000),
    5: (6, 8000, 36000, 12000),
    6: (4, 11000, 42000, 12000),
    7: (2, 15000, 48000, 16000),
}


def add_homm3_neutral_dwellings(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
) -> None:
    catalog = load_homm3_neutral_catalog()
    core = catalog.get("coreOverlay") or {}
    donor_dwelling_sid = str(core.get("donorDwellingSid") or "barracks_human_1")
    map_doc = _read_json(release_zip, output, MAP_OBJECTS_PATH)
    hire_doc = _read_json(release_zip, output, BARRACKS_HIRES_PATH)
    donor_map = next(
        (row for row in map_doc.get("array", []) if isinstance(row, dict) and row.get("id") == donor_dwelling_sid),
        None,
    )
    donor_hire = next(
        (row for row in hire_doc.get("array", []) if isinstance(row, dict) and row.get("id") == donor_dwelling_sid),
        None,
    )
    if donor_map is None or donor_hire is None:
        raise RuntimeError(f"homm3_neutral: missing donor dwelling {donor_dwelling_sid}")

    map_changed = False
    hire_changed = False
    for dwelling in catalog_dwellings(catalog):
        barracks_sid = str(dwelling["barracksSid"])
        unit_sid = str(dwelling["unitSid"])
        growth = int(dwelling["growth"])
        cost_gold = int(dwelling.get("costGold") or 0)
        tier = int(dwelling.get("tier") or 1)

        map_row = copy.deepcopy(donor_map)
        map_row["id"] = barracks_sid
        map_row["prefs"] = [f"barracks/{donor_dwelling_sid}"]
        map_changed = _upsert_array_row(map_doc, map_row) or map_changed

        hire_row = copy.deepcopy(donor_hire)
        hire_row["id"] = barracks_sid
        hire_row["fraction"] = "neutral"
        hire_row["tier"] = tier
        hire_row["unitsData"] = {
            "units": [
                {
                    "sids": [unit_sid],
                    "weeklyIncrement": growth,
                }
            ]
        }
        for bonus in hire_row.get("bonuses", []) if isinstance(hire_row.get("bonuses"), list) else []:
            if isinstance(bonus, dict) and bonus.get("type") == "cityUnitsIncrementFromBarrack":
                parameters = bonus.get("parameters")
                if isinstance(parameters, list) and parameters:
                    parameters[0] = unit_sid
                    if len(parameters) > 1:
                        parameters[1] = str(growth)
        guard_units = hire_row.get("guardUnits")
        if isinstance(guard_units, list):
            for guard in guard_units:
                if isinstance(guard, dict):
                    guard["sid"] = unit_sid
        # Vanilla tier 4+ dwellings are guarded by two stacks of their own unit; the tier-1 donor
        # has none, so give tier 4+ the vanilla faction-dwelling guard/value rows for that tier.
        tier_guard = HIGH_TIER_DWELLING_GUARDS.get(tier)
        if tier_guard is None:
            hire_row["guardUnits"] = []
        else:
            amount, guard_value, ai_value, goods_value = tier_guard
            hire_row["guardUnits"] = [{"amount": amount, "sid": unit_sid}, {"amount": amount, "sid": unit_sid}]
            hire_row["customGuardValue"] = guard_value
            hire_row["aiValue"] = ai_value
            hire_row["goodsValue"] = goods_value
        if cost_gold >= 0:
            hire_row["goodsValue"] = max(int(hire_row.get("goodsValue") or 0), cost_gold * growth)
        hire_changed = _upsert_array_row(hire_doc, hire_row) or hire_changed

    if map_changed:
        output[MAP_OBJECTS_PATH] = _write_json(map_doc)
        notes.append("merge homm3_neutral dwelling map objects")
    if hire_changed:
        output[BARRACKS_HIRES_PATH] = _write_json(hire_doc)
        notes.append("merge homm3_neutral dwelling hire rows")


def add_homm3_neutral_core_overlay(
    release_zip: zipfile.ZipFile,
    output: dict[str, bytes],
    notes: list[str],
    *,
    faction_unit_sids: tuple[str, ...] = (),
    import_view_meshes: dict[str, dict[str, str]],
) -> None:
    add_homm3_neutral_unit_rows(release_zip, output, notes)
    apply_homm3_neutral_own_view_meshes(release_zip, output, notes, import_view_meshes)
    add_homm3_neutral_squad_templates(release_zip, output, notes)
    add_homm3_neutral_dwellings(release_zip, output, notes)
    merge_homm3_neutral_arena_pick(
        release_zip,
        output,
        notes,
        faction_unit_sids=faction_unit_sids,
    )
    add_homm3_neutral_lang_rows(release_zip, output, notes)
