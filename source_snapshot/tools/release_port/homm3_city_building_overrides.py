#!/usr/bin/env python3
"""Per-faction city building overrides (building pass 2026-11-22).

Source: ``custom_factions/building_overrides/homm3_<faction>.json``, one file per HoMM3
town, schema in ``docs/building_pass_20261122/BUILD_BRIEF.md`` § Override JSON schema.

Producer: ``apply_release_core_overlay.py`` calls :func:`apply_city_building_overrides`
in each ``homm3_*_city`` normalizer, after the per-faction mechanics tables and before the
cityFactory slot alignment, the Castle-slot strip and the canonical building tree, and
:func:`assert_city_building_overrides_kept` right after the strip. The override row is
the last word on a building's section, fields, bonuses, costs, icons and text; the tree
module still owns every ``prevBuildings`` / ``nodePos`` / ``buildOrders`` entry.

Text: names go to the English Lang overlay from :func:`override_name_lang_rows` (before
the description pass, so they win over the per-faction tables); an explicit
``descriptionText`` rides on the row as ``xHomm3DescriptionText`` and
``homm3_city_building_descriptions`` renders it instead of the computed sentence.
Translations come from the optional ``nameTextLocales`` / ``descriptionTextLocales``.

Fail closed: a section the live IL2CPP ``ObjCityConfig`` does not have, a field its
config class does not have, a template or icon source that does not exist, a bonus type
the section does not apply, or a level without a cost raises ``OverrideError`` with the
file and row.

Check without building: ``python tools/release_port/apply_release_core_overlay.py
--check-building-overrides`` (runs every override through the real city normalizer), or
this file's own ``--check`` for the schema and template half.
"""

from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent))

import homm3_city_building_description_locales as _locales
from homm3_city_building_descriptions import (
    NATIVE_SECTION_BONUS_TYPES as _DESCRIPTION_SECTION_BONUS_TYPES,
    text_problems as _text_problems,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OVERRIDES_DIR = REPO_ROOT / "custom_factions" / "building_overrides"
DEFAULT_CORE = Path(
    "V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    "/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)

# ---------------------------------------------------------------------------
# IL2CPP city schema (live Golden Era interop, Steam 26615913, Hex.Configs; read with
# ilspycmd 2026-11-22: ObjCityConfig list fields and each Building*Config's own fields).
# ---------------------------------------------------------------------------

BASE_FIELDS = frozenset(
    {
        "sid",
        "icons",
        "names",
        "descriptions",
        "narrativeDescriptions",
        "backgroundImages",
        "isConstructedOnStart",
        "levelOnStart",
        "sceneSlot",
        "parametersPerLevel",
        "optionalEffectsPerLevel",
    }
)

# ObjCityConfig section -> fields of its Building*Config class beyond BuildingConfigBase.
CITY_SECTION_FIELDS: dict[str, frozenset[str]] = {
    "mains": frozenset({"bonusesPerLevel"}),  # BuildingMainConfig
    "taverns": frozenset(),  # BuildingTavernConfig
    "markets": frozenset(),  # BuildingMarketConfig
    "hires": frozenset({"unitsHire"}),  # BuildingHireConfig
    "magicGuilds": frozenset({"rollChances"}),  # BuildingMagicGuildConfig
    "banks": frozenset({"bonuses"}),  # BuildingBankConfig
    "manaFountains": frozenset(),  # BuildingManaFountainConfig
    "intelligences": frozenset({"viewRadius"}),  # BuildingIntelligenceConfig
    "graals": frozenset({"sideBonuses", "cityBonuses", "graalType"}),  # BuildingGraalConfig
    "heroBonusBanks": frozenset({"bonuses"}),  # BuildingHeroBonusBankConfig
    "cityBonusBanks": frozenset({"bonuses"}),  # BuildingCityBonusBankConfig
    "unitsConverters": frozenset({"conversionPairs", "bannedUnits"}),  # BuildingUnitsConverterConfig
    "trainingRanges": frozenset({"trainingStats"}),  # BuildingTrainingRangeConfig
    "rebirthShrines": frozenset({"resArr", "levelStep"}),  # BuildingShrineOfRebirthConfig
    "myceliumRoots": frozenset(),  # BuildingMyceliumRootsConfig: no bonuses field
    "portalSummonings": frozenset({"numberPurchases"}),  # BuildingPortalSummoningConfig
    "artifactChangers": frozenset({"artifacts"}),  # BuildingArtifactChangerConfig
    "artifactMarkets": frozenset({"extraChargePurchase", "extraChargeSell", "itemsCountPerRarity"}),
    "walls": frozenset({"bonusesPerLevel"}),  # BuildingWallConfig
}
CITY_SECTIONS = tuple(CITY_SECTION_FIELDS)

# Sections that carry one flat ``bonuses`` list, and the per-level ones.
FLAT_BONUS_SECTIONS = frozenset({"banks", "heroBonusBanks", "cityBonusBanks"})
PER_LEVEL_BONUS_SECTIONS = frozenset({"mains", "walls"})
# Per-level sections are not in NATIVE_CITY_BUILDING_BONUS_TYPES; these are the types the
# description module accepts on them (vanilla mains / walls rows).
PER_LEVEL_SECTION_BONUS_TYPES: dict[str, frozenset[str]] = {
    "mains": frozenset({"sideRes", "citySideExp", "astrologyExp"}),
    "walls": frozenset({"cityUnitsIncrementPer"}),
}

# Fields an override sets through its own keys, never through ``fields``.
MANAGED_FIELDS = frozenset(
    {"sid", "icons", "names", "descriptions", "narrativeDescriptions", "parametersPerLevel", "sceneSlot", "bonuses", "bonusesPerLevel"}
)
FIELDS_FROM_BASE = frozenset({"isConstructedOnStart", "levelOnStart", "backgroundImages", "optionalEffectsPerLevel"})

COST_RESOURCES = ("gold", "wood", "ore", "mercury", "crystals", "gemstones", "dust", "graal")
VANILLA_CITY_IDS = ("human_city", "nature_city", "demon_city", "undead_city", "dungeon_city", "unfrozen_city")
GRAAL_TYPES = frozenset({"HumanGraal", "NatureGraal", "DungeonGraal", "DemonGraal", "UndeadGraal", "UnfrozenGraal"})
LOCALES = tuple(_locales.LOCALES)

ROW_KEYS = frozenset(
    {
        "sid",
        "section",
        "template",
        "replace",
        "sceneSlot",
        "costs",
        "fields",
        "bonuses",
        "nameText",
        "nameTextLocales",
        "descriptionText",
        "descriptionTextLocales",
        "narrativeText",
        "iconFrom",
        "plugin",
        "notes",
    }
)
DOC_KEYS = frozenset({"factionSid", "rows", "remove", "notes"})

# Row fields this module writes (read back by the Lang writers and the description module).
NAME_TEXT_FIELD = "xHomm3NameText"
NAME_TEXT_LOCALES_FIELD = "xHomm3NameTextLocales"
DESCRIPTION_TEXT_FIELD = "xHomm3DescriptionText"
DESCRIPTION_TEXT_LOCALES_FIELD = "xHomm3DescriptionTextLocales"
OVERRIDE_NOTE_FIELD = "xHomm3BuildingOverride"
OVERRIDE_PLUGIN_FIELD = "xHomm3BuildingPlugin"

_SOURCE_RE = re.compile(r"^(?P<city>[A-Za-z0-9_]+):(?P<sid>Build_[A-Za-z0-9_]+)$")


class OverrideError(RuntimeError):
    """An override file or row that cannot be applied as written."""


# ---------------------------------------------------------------------------
# Configuration bound by the overlay
# ---------------------------------------------------------------------------

_ACTIVE_DIR: Path = DEFAULT_OVERRIDES_DIR
_TEMPLATE_READER: Callable[[str], Any] | None = None
_CACHE: dict[Path, dict[str, dict[str, Any]]] = {}


def set_overrides_dir(path: Path | None) -> None:
    """Point the applier at another directory (tests, ``--building-overrides-dir``)."""
    global _ACTIVE_DIR
    _ACTIVE_DIR = Path(path) if path is not None else DEFAULT_OVERRIDES_DIR
    _CACHE.pop(_ACTIVE_DIR.resolve(), None)


def overrides_dir() -> Path:
    return _ACTIVE_DIR


def bind_template_reader(reader: Callable[[str], Any] | None) -> None:
    """``reader(city_id)`` returns that city's JSON doc (``{"array": [row]}``) or raises KeyError."""
    global _TEMPLATE_READER
    _TEMPLATE_READER = reader


def zip_template_reader(zf: zipfile.ZipFile, output: dict[str, bytes] | None = None) -> Callable[[str], Any]:
    def read(city_id: str) -> Any:
        name = f"DB/objects_logic/cities/{city_id}.json"
        if output is not None and name in output:
            return json.loads(output[name].decode("utf-8-sig"))
        return json.loads(zf.read(name).decode("utf-8-sig"))

    return read


# ---------------------------------------------------------------------------
# Loading and static validation
# ---------------------------------------------------------------------------


def _levels(row: dict[str, Any]) -> int:
    costs = row.get("costs")
    return len(costs) if isinstance(costs, list) else 0


def _per_level_text(value: Any, levels: int, where: str, what: str) -> list[str]:
    if isinstance(value, str):
        return [value] * levels
    if isinstance(value, list) and len(value) == levels and all(isinstance(v, str) for v in value):
        return list(value)
    raise OverrideError(f"{where}: {what} must be a string or a list of {levels} strings (one per level)")


def _check_source(value: Any, where: str, what: str) -> tuple[str, str]:
    match = _SOURCE_RE.match(value) if isinstance(value, str) else None
    if not match:
        raise OverrideError(f"{where}: {what} {value!r} must be '<vanilla city id>:<sid>' or 'self:<sid>'")
    city = match.group("city")
    if city != "self" and city not in VANILLA_CITY_IDS:
        raise OverrideError(f"{where}: {what} city {city!r} is not a vanilla city ({', '.join(VANILLA_CITY_IDS)}) or 'self'")
    return city, match.group("sid")


def _check_bonus_list(bonuses: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(bonuses, list):
        raise OverrideError(f"{where}: bonuses must be a list of bonus objects")
    for bonus in bonuses:
        if not isinstance(bonus, dict) or not isinstance(bonus.get("type"), str):
            raise OverrideError(f"{where}: malformed bonus {bonus!r}")
        if "parameters" in bonus and not isinstance(bonus["parameters"], list):
            raise OverrideError(f"{where}: bonus {bonus['type']} parameters must be a list")
        if bonus["type"] not in allowed:
            raise OverrideError(
                f"{where}: bonus type {bonus['type']!r} is not applied by the game on this section "
                f"(allowed: {', '.join(sorted(allowed)) or 'none'})"
            )


def section_bonus_types(section: str, native: dict[str, frozenset[str]] | None = None) -> frozenset[str]:
    table = native if native is not None else _DESCRIPTION_SECTION_BONUS_TYPES
    if section in FLAT_BONUS_SECTIONS:
        return frozenset(table[section])
    return PER_LEVEL_SECTION_BONUS_TYPES.get(section, frozenset())


def validate_override_doc(
    doc: Any, where: str, native_bonus_types: dict[str, frozenset[str]] | None = None
) -> list[str]:
    """Schema checks that need no city or Core. Returns warnings; raises OverrideError."""
    warnings: list[str] = []
    if not isinstance(doc, dict):
        raise OverrideError(f"{where}: top level must be an object")
    unknown = set(doc) - DOC_KEYS
    if unknown:
        raise OverrideError(f"{where}: unknown top-level keys {sorted(unknown)}")
    if not isinstance(doc.get("factionSid"), str) or not doc["factionSid"].startswith("homm3_"):
        raise OverrideError(f"{where}: factionSid must be a homm3_<faction> sid")
    rows = doc.get("rows", [])
    removes = doc.get("remove", [])
    if not isinstance(rows, list):
        raise OverrideError(f"{where}: rows must be a list")
    if not isinstance(removes, list) or not all(isinstance(s, str) and s.startswith("Build_") for s in removes):
        raise OverrideError(f"{where}: remove must be a list of Build_* sids")
    if len(set(removes)) != len(removes):
        raise OverrideError(f"{where}: remove lists a sid twice")
    seen: set[str] = set()
    for index, row in enumerate(rows):
        rwhere = f"{where} rows[{index}]"
        if not isinstance(row, dict):
            raise OverrideError(f"{rwhere}: must be an object")
        sid = row.get("sid")
        if not isinstance(sid, str) or not re.fullmatch(r"Build_[A-Za-z0-9_]+", sid):
            raise OverrideError(f"{rwhere}: sid {sid!r} must be Build_<Name>")
        rwhere = f"{where} {sid}"
        unknown = set(row) - ROW_KEYS
        if unknown:
            raise OverrideError(f"{rwhere}: unknown keys {sorted(unknown)} (schema: {', '.join(sorted(ROW_KEYS))})")
        if sid in seen:
            raise OverrideError(f"{rwhere}: sid appears in two rows")
        seen.add(sid)
        section = row.get("section")
        if section not in CITY_SECTION_FIELDS:
            raise OverrideError(f"{rwhere}: section {section!r} is not an ObjCityConfig list ({', '.join(CITY_SECTIONS)})")
        replace = row.get("replace", False)
        if not isinstance(replace, bool):
            raise OverrideError(f"{rwhere}: replace must be true or false")
        if replace and sid in removes:
            raise OverrideError(f"{rwhere}: replace:true on a sid the same file removes")
        if "template" in row:
            _check_source(row["template"], rwhere, "template")
        elif not replace:
            raise OverrideError(f"{rwhere}: a new row needs a template")
        if "iconFrom" in row:
            _check_source(row["iconFrom"], rwhere, "iconFrom")
        if "sceneSlot" in row and (not isinstance(row["sceneSlot"], str) or not row["sceneSlot"].strip()):
            raise OverrideError(f"{rwhere}: sceneSlot must be a non-empty string")
        costs = row.get("costs")
        if not isinstance(costs, list) or not costs:
            raise OverrideError(f"{rwhere}: costs must list one cost object per level")
        for level, cost in enumerate(costs, start=1):
            if not isinstance(cost, dict) or not cost:
                raise OverrideError(f"{rwhere}: level {level} has no cost")
            for res, amount in cost.items():
                if res not in COST_RESOURCES:
                    raise OverrideError(f"{rwhere}: level {level} cost resource {res!r} (allowed {', '.join(COST_RESOURCES)})")
                if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
                    raise OverrideError(f"{rwhere}: level {level} cost {res} must be a non-negative integer")
        levels = len(costs)
        fields = row.get("fields", {})
        if not isinstance(fields, dict):
            raise OverrideError(f"{rwhere}: fields must be an object")
        allowed_fields = CITY_SECTION_FIELDS[section] | FIELDS_FROM_BASE
        for key in fields:
            if key.startswith("xHomm3"):
                continue
            if key in MANAGED_FIELDS:
                raise OverrideError(f"{rwhere}: field {key!r} is set by its own override key, not through fields")
            if key not in allowed_fields:
                raise OverrideError(
                    f"{rwhere}: field {key!r} does not exist on the {section} config class "
                    f"(live interop fields: {', '.join(sorted(allowed_fields))})"
                )
        if section == "graals" and "graalType" in fields and fields["graalType"] not in GRAAL_TYPES:
            raise OverrideError(f"{rwhere}: graalType {fields['graalType']!r} is not a native graal type")
        if section == "intelligences" and "viewRadius" in fields:
            radius = fields["viewRadius"]
            if not isinstance(radius, int) or isinstance(radius, bool) or radius <= 0:
                raise OverrideError(f"{rwhere}: viewRadius must be a positive integer")
        if "bonuses" in row:
            bonuses = row["bonuses"]
            if not isinstance(bonuses, list) or len(bonuses) != levels:
                raise OverrideError(f"{rwhere}: bonuses must hold one list per level ({levels})")
            allowed = section_bonus_types(section, native_bonus_types)
            for level, level_bonuses in enumerate(bonuses, start=1):
                _check_bonus_list(level_bonuses, allowed, f"{rwhere} level {level}")
            if section in FLAT_BONUS_SECTIONS and any(b != bonuses[0] for b in bonuses):
                raise OverrideError(f"{rwhere}: {section} rows carry one bonuses list for every level; per-level values differ")
            if section not in FLAT_BONUS_SECTIONS | PER_LEVEL_BONUS_SECTIONS and any(bonuses):
                raise OverrideError(f"{rwhere}: {section} rows have no bonuses field in the live interop")
        if not replace and "nameText" not in row:
            raise OverrideError(f"{rwhere}: a new row needs nameText")
        if "nameText" in row:
            for text in _per_level_text(row["nameText"], levels, rwhere, "nameText"):
                problems = _text_problems(text, f"{sid} name", kind="name")
                if problems:
                    raise OverrideError(f"{rwhere}: " + "; ".join(problems))
        if "descriptionText" in row:
            for text in _per_level_text(row["descriptionText"], levels, rwhere, "descriptionText"):
                problems = _text_problems(text, f"{sid} description", kind="description")
                if problems:
                    raise OverrideError(f"{rwhere}: " + "; ".join(problems))
        for key, base_key in (("nameTextLocales", "nameText"), ("descriptionTextLocales", "descriptionText")):
            if key not in row:
                continue
            if base_key not in row:
                raise OverrideError(f"{rwhere}: {key} without {base_key}")
            value = row[key]
            if not isinstance(value, dict) or set(value) - set(LOCALES):
                raise OverrideError(f"{rwhere}: {key} must map OE locales ({', '.join(LOCALES)}) to text")
            for lang, text in value.items():
                _per_level_text(text, levels, rwhere, f"{key}.{lang}")
        for key in ("plugin", "notes", "narrativeText"):
            if key in row and not isinstance(row[key], str):
                raise OverrideError(f"{rwhere}: {key} must be a string")
        if "narrativeText" in row:
            warnings.append(
                f"{rwhere}: narrativeText is not shipped (the description contract keeps narrativeDescription == description)"
            )
        if row.get("plugin") and "descriptionText" not in row:
            raise OverrideError(f"{rwhere}: a plugin building must give descriptionText (the computed text cannot see plugin effects)")
    return warnings


def load_override_docs(directory: Path | None = None, *, use_cache: bool = True) -> dict[str, dict[str, Any]]:
    """{factionSid: {"path": Path, "doc": dict, "warnings": [...]}} for every homm3_*.json file."""
    directory = Path(directory) if directory is not None else _ACTIVE_DIR
    key = directory.resolve()
    if use_cache and key in _CACHE:
        return _CACHE[key]
    out: dict[str, dict[str, Any]] = {}
    if directory.is_dir():
        for path in sorted(directory.glob("homm3_*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8-sig"))
            except json.JSONDecodeError as ex:
                raise OverrideError(f"{path}: invalid JSON ({ex})") from ex
            warnings = validate_override_doc(doc, str(path))
            faction = doc["factionSid"]
            if path.stem != faction:
                raise OverrideError(f"{path}: factionSid {faction!r} does not match the file name")
            out[faction] = {"path": path, "doc": doc, "warnings": warnings}
    _CACHE[key] = out
    return out


def faction_override(faction_sid: str) -> dict[str, Any] | None:
    entry = load_override_docs().get(faction_sid)
    return entry["doc"] if entry else None


def overridden_sids(faction_sid: str) -> set[str]:
    doc = faction_override(faction_sid)
    return {row["sid"] for row in doc.get("rows", [])} if doc else set()


# ---------------------------------------------------------------------------
# Applying to a city row
# ---------------------------------------------------------------------------


def _first_item(doc: Any) -> dict[str, Any] | None:
    if isinstance(doc, dict) and isinstance(doc.get("array"), list) and doc["array"] and isinstance(doc["array"][0], dict):
        return doc["array"][0]
    return None


def _building_rows(item: dict[str, Any]) -> dict[str, tuple[str, dict[str, Any]]]:
    out: dict[str, tuple[str, dict[str, Any]]] = {}
    for section in CITY_SECTIONS:
        for row in item.get(section) or []:
            if isinstance(row, dict) and isinstance(row.get("sid"), str):
                if row["sid"] in out:
                    raise OverrideError(f"{item.get('id')}: building {row['sid']} appears twice in the city row")
                out[row["sid"]] = (section, row)
    return out


def _resize(values: Any, levels: int) -> Any:
    if not isinstance(values, list) or not values:
        return values
    if len(values) >= levels:
        return copy.deepcopy(values[:levels])
    return copy.deepcopy(values) + [copy.deepcopy(values[-1]) for _ in range(levels - len(values))]


def _resolve_source(
    source: str,
    snapshot: dict[str, tuple[str, dict[str, Any]]],
    where: str,
    what: str,
) -> tuple[str, dict[str, Any]]:
    city, sid = _check_source(source, where, what)
    if city == "self":
        if sid not in snapshot:
            raise OverrideError(f"{where}: {what} self:{sid} is not a building of this town")
        section, row = snapshot[sid]
        return section, copy.deepcopy(row)
    if _TEMPLATE_READER is None:
        raise OverrideError(f"{where}: {what} {source} needs the release Core (no template reader bound)")
    try:
        doc = _TEMPLATE_READER(city)
    except KeyError as ex:
        raise OverrideError(f"{where}: {what} city {city} is not in the release Core") from ex
    item = _first_item(doc)
    if item is None:
        raise OverrideError(f"{where}: {what} city {city} has no city row")
    rows = _building_rows(item)
    if sid not in rows:
        raise OverrideError(f"{where}: {what} {source} does not exist")
    section, row = rows[sid]
    return section, copy.deepcopy(row)


def _strip_to_section(row: dict[str, Any], section: str) -> dict[str, Any]:
    keep = BASE_FIELDS | CITY_SECTION_FIELDS[section]
    return {k: v for k, v in row.items() if k in keep}


def _native_costs(cost: dict[str, int]) -> list[dict[str, Any]]:
    return [{"name": res, "cost": int(amount)} for res, amount in cost.items()]


def _drop_sids_from_city(item: dict[str, Any], sids: set[str]) -> None:
    for section in CITY_SECTIONS:
        rows = item.get(section)
        if not isinstance(rows, list):
            continue
        for row in rows:
            for level in (row.get("parametersPerLevel") or []) if isinstance(row, dict) else []:
                if isinstance(level, dict) and isinstance(level.get("prevBuildings"), list):
                    level["prevBuildings"] = [
                        p for p in level["prevBuildings"] if not (isinstance(p, dict) and p.get("sid") in sids)
                    ]
    for build_order in item.get("buildOrders") or []:
        order = build_order.get("order") if isinstance(build_order, dict) else None
        if isinstance(order, list):
            order[:] = [e for e in order if not (isinstance(e, dict) and e.get("sid") in sids)]


def apply_overrides_to_city_item(
    item: dict[str, Any],
    faction_sid: str,
    spec: dict[str, Any],
    *,
    key_func: Callable[[str, str, int, int], str],
    native_bonus_types: dict[str, frozenset[str]] | None = None,
    mechanics_spec_sids: Iterable[str] = (),
    where: str | None = None,
) -> list[str]:
    """Apply one faction's override doc to its city row in place. Returns notes."""
    where = where or faction_sid
    notes: list[str] = []
    mechanics_spec_sids = set(mechanics_spec_sids)
    snapshot = {sid: (section, copy.deepcopy(row)) for sid, (section, row) in _building_rows(item).items()}

    removes = list(spec.get("remove") or [])
    for sid in removes:
        if sid not in snapshot:
            raise OverrideError(f"{where}: remove names {sid}, which this town does not have")
        section = snapshot[sid][0]
        item[section] = [r for r in item[section] if not (isinstance(r, dict) and r.get("sid") == sid)]
    if removes:
        _drop_sids_from_city(item, set(removes))
        notes.append(f"{faction_sid}: remove {', '.join(removes)}")

    added: list[tuple[str, int]] = []
    used_slots = {
        row.get("sceneSlot"): sid for sid, (_section, row) in _building_rows(item).items() if isinstance(row.get("sceneSlot"), str)
    }
    for spec_row in spec.get("rows") or []:
        sid = spec_row["sid"]
        rwhere = f"{where} {sid}"
        section = spec_row["section"]
        replace = bool(spec_row.get("replace", False))
        levels = _levels(spec_row)
        current = _building_rows(item)
        if replace:
            if sid not in current:
                raise OverrideError(f"{rwhere}: replace:true but the town has no {sid} row")
            old_section, existing = current[sid]
            if "template" in spec_row:
                tsection, row = _resolve_source(spec_row["template"], snapshot, rwhere, "template")
                for key in ("icons", "sceneSlot", "backgroundImages", "isConstructedOnStart", "levelOnStart"):
                    if key in existing:
                        row[key] = copy.deepcopy(existing[key])
                inherit_bonuses = tsection == section
                inherited_levels = existing.get("parametersPerLevel")
            else:
                row = copy.deepcopy(existing)
                tsection = old_section
                inherit_bonuses = old_section == section
                inherited_levels = existing.get("parametersPerLevel")
            index = next(i for i, r in enumerate(item[old_section]) if isinstance(r, dict) and r.get("sid") == sid)
            del item[old_section][index]
            if sid in mechanics_spec_sids and "nameText" not in spec_row:
                raise OverrideError(
                    f"{rwhere}: replaces a CITY_BUILDING_MECHANICS_BY_FACTION building; give nameText, "
                    "or its old mechanics-table name ships"
                )
        else:
            if sid in current:
                raise OverrideError(f"{rwhere}: the town already has {sid}; use replace:true or remove it first")
            tsection, row = _resolve_source(spec_row["template"], snapshot, rwhere, "template")
            inherit_bonuses = tsection == section
            inherited_levels = None
            old_section, index = section, None

        row = _strip_to_section(row, section)
        if not inherit_bonuses:
            row.pop("bonuses", None)
            row.pop("bonusesPerLevel", None)
        row["sid"] = sid

        # Levels and costs. Prerequisites and nodePos stay for the tree module to rewrite.
        template_levels = inherited_levels if inherited_levels is not None else row.get("parametersPerLevel")
        params: list[dict[str, Any]] = []
        for level_index in range(levels):
            source = None
            if isinstance(template_levels, list) and template_levels:
                source = template_levels[min(level_index, len(template_levels) - 1)]
            level_row = copy.deepcopy(source) if isinstance(source, dict) else {}
            if inherited_levels is None:
                level_row["prevBuildings"] = []  # vanilla template gates name vanilla sids
            level_row.setdefault("prevBuildings", [])
            level_row.setdefault("nodePos", {"xPos": 4, "yPos": 0})
            level_row["costs"] = _native_costs(spec_row["costs"][level_index])
            params.append(level_row)
        row["parametersPerLevel"] = params

        # Icons and per-level presentation lists.
        if "iconFrom" in spec_row:
            _s, icon_row = _resolve_source(spec_row["iconFrom"], snapshot, rwhere, "iconFrom")
            row["icons"] = copy.deepcopy(icon_row.get("icons") or [])
        if not isinstance(row.get("icons"), list) or not row["icons"]:
            raise OverrideError(f"{rwhere}: no icons (give iconFrom)")
        row["icons"] = _resize(row["icons"], levels)
        if isinstance(row.get("backgroundImages"), list) and row["backgroundImages"]:
            row["backgroundImages"] = _resize(row["backgroundImages"], levels)
        if isinstance(row.get("optionalEffectsPerLevel"), list) and len(row["optionalEffectsPerLevel"]) > levels:
            row["optionalEffectsPerLevel"] = row["optionalEffectsPerLevel"][:levels]

        if "sceneSlot" in spec_row:
            row["sceneSlot"] = spec_row["sceneSlot"]
        elif not replace:
            row["sceneSlot"] = sid.removeprefix("Build_")
        slot = row.get("sceneSlot")
        if not replace and isinstance(slot, str) and used_slots.get(slot) not in (None, sid):
            raise OverrideError(f"{rwhere}: sceneSlot {slot!r} is already {used_slots[slot]}'s slot")
        if isinstance(slot, str):
            used_slots[slot] = sid
        row["isConstructedOnStart"] = bool(row.get("isConstructedOnStart", False)) if replace else False
        row.setdefault("levelOnStart", 1)

        for key, value in (spec_row.get("fields") or {}).items():
            row[key] = copy.deepcopy(value)

        if "bonuses" in spec_row:
            if section in FLAT_BONUS_SECTIONS:
                row["bonuses"] = copy.deepcopy(spec_row["bonuses"][0])
            elif section in PER_LEVEL_BONUS_SECTIONS:
                row["bonusesPerLevel"] = [{"bonuses": copy.deepcopy(b)} for b in spec_row["bonuses"]]
        elif section in FLAT_BONUS_SECTIONS:
            row.setdefault("bonuses", [])
        allowed = section_bonus_types(section, native_bonus_types)
        if section in FLAT_BONUS_SECTIONS:
            _check_bonus_list(row.get("bonuses") or [], allowed, rwhere)
        elif section in PER_LEVEL_BONUS_SECTIONS:
            per_level = row.get("bonusesPerLevel") or []
            if len(per_level) != levels:
                raise OverrideError(f"{rwhere}: {section} needs bonusesPerLevel for all {levels} levels")
            for level_index, entry in enumerate(per_level, start=1):
                _check_bonus_list((entry or {}).get("bonuses") or [], allowed, f"{rwhere} level {level_index}")
        if section == "myceliumRoots" and row.get("bonuses"):
            raise OverrideError(f"{rwhere}: myceliumRoots has no bonuses field in the live interop")
        if section == "graals" and row.get("graalType") not in GRAAL_TYPES:
            raise OverrideError(f"{rwhere}: graal row needs a native graalType")
        if section == "intelligences" and not (isinstance(row.get("viewRadius"), int) and row["viewRadius"] > 0):
            raise OverrideError(f"{rwhere}: intelligence row needs viewRadius > 0")

        # Text keys and explicit text.
        row["names"] = [key_func(sid, "name", level, levels) for level in range(1, levels + 1)]
        row["descriptions"] = [key_func(sid, "description", level, levels) for level in range(1, levels + 1)]
        row["narrativeDescriptions"] = [
            key_func(sid, "narrativeDescription", level, levels) for level in range(1, levels + 1)
        ]
        for field in (NAME_TEXT_FIELD, NAME_TEXT_LOCALES_FIELD, DESCRIPTION_TEXT_FIELD, DESCRIPTION_TEXT_LOCALES_FIELD):
            row.pop(field, None)
        if "nameText" in spec_row:
            row[NAME_TEXT_FIELD] = _per_level_text(spec_row["nameText"], levels, rwhere, "nameText")
            if spec_row.get("nameTextLocales"):
                row[NAME_TEXT_LOCALES_FIELD] = {
                    lang: _per_level_text(text, levels, rwhere, f"nameTextLocales.{lang}")
                    for lang, text in sorted(spec_row["nameTextLocales"].items())
                }
        if "descriptionText" in spec_row:
            row[DESCRIPTION_TEXT_FIELD] = _per_level_text(spec_row["descriptionText"], levels, rwhere, "descriptionText")
            if spec_row.get("descriptionTextLocales"):
                row[DESCRIPTION_TEXT_LOCALES_FIELD] = {
                    lang: _per_level_text(text, levels, rwhere, f"descriptionTextLocales.{lang}")
                    for lang, text in sorted(spec_row["descriptionTextLocales"].items())
                }
        for key in [k for k in row if k.startswith("xHomm3") and k not in (
            NAME_TEXT_FIELD, NAME_TEXT_LOCALES_FIELD, DESCRIPTION_TEXT_FIELD, DESCRIPTION_TEXT_LOCALES_FIELD
        )]:
            if key not in (spec_row.get("fields") or {}):
                row.pop(key)  # template metadata describes the template's mechanic, not this one
        row[OVERRIDE_NOTE_FIELD] = spec_row.get("notes") or f"building override {faction_sid}"
        if spec_row.get("plugin"):
            row[OVERRIDE_PLUGIN_FIELD] = spec_row["plugin"]

        target = item.setdefault(section, [])
        if not isinstance(target, list):
            raise OverrideError(f"{rwhere}: city section {section} is not a list")
        if replace and old_section == section and index is not None:
            target.insert(index, row)
        else:
            target.append(row)
        if not replace:
            added.extend((sid, level) for level in range(1, levels + 1))
        notes.append(f"{faction_sid}: {'replace' if replace else 'add'} {sid} in {section} ({levels} level(s))")

    # AI build orders: new levels go to the end; the tree module pulls their prerequisites forward.
    if added:
        for build_order in item.get("buildOrders") or []:
            order = build_order.get("order") if isinstance(build_order, dict) else None
            if not isinstance(order, list):
                continue
            present = {(e.get("sid"), e.get("level", 1)) for e in order if isinstance(e, dict)}
            order.extend({"sid": sid, "level": level} for sid, level in added if (sid, level) not in present)
    return notes


def apply_city_building_overrides(
    doc: Any,
    manifest: dict[str, Any],
    *,
    key_func: Callable[[str, str, int, int], str],
    native_bonus_types: dict[str, frozenset[str]] | None = None,
    mechanics_spec_sids: Iterable[str] = (),
    notes: list[str] | None = None,
) -> Any:
    """Normalizer entry point: apply ``building_overrides/<factionSid>.json`` to ``doc`` if present."""
    faction_sid = manifest["identity"]["factionSid"]
    entry = load_override_docs().get(faction_sid)
    if entry is None:
        return doc
    item = _first_item(doc)
    if item is None:
        raise OverrideError(f"{faction_sid}: city document has no array item for building overrides")
    produced = apply_overrides_to_city_item(
        item,
        faction_sid,
        entry["doc"],
        key_func=key_func,
        native_bonus_types=native_bonus_types,
        mechanics_spec_sids=mechanics_spec_sids,
        where=str(entry["path"].name),
    )
    if notes is not None:
        notes.extend(produced)
    return doc


def assert_city_building_overrides_kept(doc: Any, manifest: dict[str, Any]) -> Any:
    """After the Castle-slot strip: every override row must still be in the city."""
    faction_sid = manifest["identity"]["factionSid"]
    wanted = overridden_sids(faction_sid)
    if not wanted:
        return doc
    item = _first_item(doc)
    present = set(_building_rows(item)) if item is not None else set()
    missing = sorted(wanted - present)
    if missing:
        raise OverrideError(
            f"{faction_sid}: override rows {missing} were stripped as unbound Castle slots; add them to the "
            "building's source_mechanics currentRows (or nativeLevels) so the strip keeps them"
        )
    return doc


# ---------------------------------------------------------------------------
# Lang rows (read back from the final city rows)
# ---------------------------------------------------------------------------


def _override_rows(item: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for section in CITY_SECTIONS:
        for row in item.get(section) or []:
            if isinstance(row, dict) and OVERRIDE_NOTE_FIELD in row:
                yield row


def override_name_lang_rows(city_items: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """English name rows for every override row that gives nameText."""
    rows: list[dict[str, str]] = []
    for item in city_items:
        for row in _override_rows(item):
            texts = row.get(NAME_TEXT_FIELD)
            keys = row.get("names")
            if not isinstance(texts, list) or not isinstance(keys, list):
                continue
            if len(texts) != len(keys):
                raise OverrideError(f"{item.get('id')}:{row.get('sid')}: {len(texts)} name texts for {len(keys)} levels")
            rows.extend({"sid": key, "text": text} for key, text in zip(keys, texts))
    return rows


def override_locale_name_rows(city_items: Iterable[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
    """{locale: rows} for every override row that gives nameTextLocales."""
    out: dict[str, list[dict[str, str]]] = {}
    for item in city_items:
        for row in _override_rows(item):
            by_lang = row.get(NAME_TEXT_LOCALES_FIELD)
            keys = row.get("names")
            if not isinstance(by_lang, dict) or not isinstance(keys, list):
                continue
            for lang, texts in by_lang.items():
                out.setdefault(lang, []).extend({"sid": k, "text": t} for k, t in zip(keys, texts))
    return out


# ---------------------------------------------------------------------------
# Standalone check
# ---------------------------------------------------------------------------


def check_templates(core: Path, directory: Path) -> tuple[list[str], list[str]]:
    """Schema plus every template/iconFrom against the Core. Returns (errors, info)."""
    errors: list[str] = []
    info: list[str] = []
    try:
        docs = load_override_docs(directory, use_cache=False)
    except OverrideError as ex:
        return [str(ex)], info
    with zipfile.ZipFile(core) as zf:
        reader = zip_template_reader(zf)
        previous = _TEMPLATE_READER
        bind_template_reader(reader)
        try:
            for faction, entry in sorted(docs.items()):
                info.extend(entry["warnings"])
                try:
                    city = _first_item(reader(faction + "_city"))
                except KeyError:
                    errors.append(f"{faction}: no {faction}_city in {core}")
                    continue
                snapshot = _building_rows(city or {})
                for row in entry["doc"].get("rows") or []:
                    for key in ("template", "iconFrom"):
                        if key in row:
                            try:
                                _resolve_source(row[key], snapshot, f"{entry['path'].name} {row['sid']}", key)
                            except OverrideError as ex:
                                errors.append(str(ex))
                info.append(f"{faction}: {len(entry['doc'].get('rows') or [])} row(s), {len(entry['doc'].get('remove') or [])} removal(s)")
        finally:
            bind_template_reader(previous)
    return errors, info


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="validate every override file (schema + templates)")
    parser.add_argument("--overrides-dir", type=Path, default=DEFAULT_OVERRIDES_DIR)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE, help="Core.zip that holds the template cities")
    args = parser.parse_args(argv)
    if not args.check:
        parser.print_help()
        return 0
    errors, info = check_templates(args.core, args.overrides_dir)
    for line in info:
        print(line)
    for line in errors:
        print("ERROR: " + line)
    print(f"building overrides: {'FAIL' if errors else 'OK'} ({args.overrides_dir})")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
