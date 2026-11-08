#!/usr/bin/env python3
"""Fail-closed contract: HoMM3 city buildings do in OE what their tooltips say, in every locale.

Owner: tools/release_port/homm3_city_building_descriptions.py (+ the locale tables in
homm3_city_building_description_locales.py), applied by apply_release_core_overlay.py
``apply_homm3_native_city_building_bonuses`` / ``apply_homm3_city_building_descriptions`` /
``apply_homm3_city_building_description_locales``. Doc: docs/homm3_city_building_descriptions.md.

For every ``homm3_*_city`` (and ``homm3_landon_*_city`` clone) in the Core
(``--core``, default the Golden Era install), for every building level:
  * the name, description and narrativeDescription keys resolve in
    Lang/english/texts/cities.json to non-empty text that is not a raw key and has
    no unfilled ``{n}`` placeholder (custom keys get no tooltip substitution);
  * no name or description mentions a mechanic/entity OE does not have (war
    machines, shipyards, HoMM3-only buildings) or generic filler;
  * every bonus sits on a section that applies it (banks / cityBonusBanks: sideRes and
    per-dwelling cityUnitsIncrementPer; heroBonusBanks: heroStat / heroExp; myceliumRoots
    carries none) - an inert bonus fails the derivation;
  * the English description equals the text derived from that level's installed
    config row, and narrativeDescription equals description;
  * each of the 15 other locales has exactly the text re-rendered from the same sentences
    with that locale's unit names and vanilla rows, which is not an English fallback and
    carries no war-machine / HoMM3 / filler term; renamed buildings (Blacksmith, Alchemic
    Depot, Spirits of the Forebears) carry their localized name.

Native mechanics (2026-10-01 user decisions), per enabled custom-faction manifest:
  * every CITY_BUILDING_MECHANICS_BY_FACTION building is on its native section with
    exactly the native bonuses (non-growth spec bonuses + per-dwelling growth percent), so
    a dropped or inert bonus fails;
  * every homm3 Build_Treasury (the Blacksmith) equals the vanilla human_city Treasury:
    bonuses, level count, per-level costs and prerequisites;
  * the Necropolis units converter targets the city's own tier 1-7 base units and bans
    every one of its hire sids.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "release_port"))

import homm3_city_building_description_locales as L  # noqa: E402
from homm3_city_building_descriptions import (  # noqa: E402
    NATIVE_SECTION_BONUS_TYPES,
    derive_building_description,
    derive_city_description_sentences,
    iter_city_building_levels,
    locale_text_problems,
    render_sentences,
    text_problems,
)

DEFAULT_CORE = Path(
    r"V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era"
    r"/HeroesOldenEra_Data/StreamingAssets/Core.zip"
)
CITY_PREFIX = "DB/objects_logic/cities/homm3_"
VANILLA_TREASURY_CITY = "DB/objects_logic/cities/human_city.json"


def _read(zf: zipfile.ZipFile, name: str) -> Any:
    return json.loads(zf.read(name).decode("utf-8-sig"))


def _texts(doc: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(doc, dict):
        for list_name in ("array", "tokens"):
            for row in doc.get(list_name) or []:
                if isinstance(row, dict) and isinstance(row.get("sid"), str):
                    out[row["sid"]] = row.get("text")
    return out


def _canon(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _rows_by_sid(item: dict[str, Any]) -> dict[str, list[tuple[str, dict[str, Any]]]]:
    out: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for section, rows in item.items():
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and isinstance(row.get("sid"), str) and "names" in row:
                    out.setdefault(row["sid"], []).append((section, row))
    return out


def native_section_errors(city: str, item: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for section, allowed in NATIVE_SECTION_BONUS_TYPES.items():
        for row in item.get(section) or []:
            if not isinstance(row, dict):
                continue
            for bonus in row.get("bonuses") or []:
                btype = bonus.get("type") if isinstance(bonus, dict) else None
                if btype not in allowed:
                    errors.append(f"{city}:{row.get('sid')}: {section} bonus {btype!r} is not applied by the game")
    for row in item.get("myceliumRoots") or []:
        if isinstance(row, dict) and row.get("bonuses"):
            errors.append(f"{city}:{row.get('sid')}: myceliumRoots has no bonuses field in the live interop")
    return errors


def treasury_errors(city: str, item: dict[str, Any], vanilla: dict[str, Any]) -> list[str]:
    rows = _rows_by_sid(item).get("Build_Treasury", [])
    if len(rows) != 1:
        return [f"{city}: expected one Build_Treasury (Blacksmith) row, found {len(rows)}"]
    section, row = rows[0]
    errors: list[str] = []
    if section != "banks":
        errors.append(f"{city}: Blacksmith is under {section}, vanilla Treasury is a bank")
    if _canon(row.get("bonuses")) != _canon(vanilla.get("bonuses")):
        errors.append(f"{city}: Blacksmith bonuses {row.get('bonuses')} != vanilla Treasury {vanilla.get('bonuses')}")
    levels = row.get("parametersPerLevel") or []
    vlevels = vanilla.get("parametersPerLevel") or []
    if len(levels) != len(vlevels):
        errors.append(f"{city}: Blacksmith has {len(levels)} levels, vanilla Treasury {len(vlevels)}")
    for index, (level, vlevel) in enumerate(zip(levels, vlevels), start=1):
        for field in ("costs", "prevBuildings"):
            if _canon(level.get(field)) != _canon(vlevel.get(field)):
                errors.append(f"{city}: Blacksmith L{index} {field} {level.get(field)} != vanilla {vlevel.get(field)}")
    return errors


def converter_errors(city: str, item: dict[str, Any]) -> list[str]:
    converters = [r for r in (item.get("unitsConverters") or []) if isinstance(r, dict)]
    if not converters:
        return [f"{city}: Bone Foundry units converter missing"]
    errors: list[str] = []
    want_pairs: list[dict[str, Any]] = []
    want_banned: list[str] = []
    for tier in range(1, 8):
        lines = [
            line
            for row in (item.get("hires") or [])
            if isinstance(row, dict) and row.get("sid") == f"Build_Tier_{tier}"
            for line in ((row.get("unitsHire") or {}).get("units") or [])
            if isinstance(line, dict) and line.get("sids")
        ]
        if len(lines) != 1:
            errors.append(f"{city}: tier {tier} has {len(lines)} hire lines")
            continue
        want_pairs.append({"tier": tier, "sid": lines[0]["sids"][0]})
        want_banned.extend(lines[0]["sids"])
    for row in converters:
        if _canon(row.get("conversionPairs")) != _canon(want_pairs):
            errors.append(f"{city}: converter pairs {row.get('conversionPairs')} != own tier 1-7 units {want_pairs}")
        banned = set(row.get("bannedUnits") or [])
        missing = [sid for sid in want_banned if sid not in banned]
        if missing:
            errors.append(f"{city}: converter does not ban own units {missing}")
    return errors


def mechanics_errors(zf: zipfile.ZipFile) -> list[str]:
    """Spec rows on their native section with exactly the native bonuses (overlay is the owner)."""
    import apply_release_core_overlay as O  # heavy; only the mechanics half needs it

    errors: list[str] = []
    for manifest in O.CUSTOM_FACTION_MANIFESTS:
        if not O.manifest_core_overlay_enabled(manifest):
            continue
        faction = manifest["identity"]["factionSid"]
        member = O.manifest_core_member(manifest, "cityLogic")
        if member not in zf.namelist():
            errors.append(f"{faction}: city member missing {member}")
            continue
        item = O.first_array_item(_read(zf, member))
        if not isinstance(item, dict):
            errors.append(f"{faction}: no city row")
            continue
        rows = _rows_by_sid(item)
        for building_sid, spec in O.CITY_BUILDING_MECHANICS_BY_FACTION.get(faction, {}).items():
            found = rows.get(building_sid, [])
            if len(found) != 1:
                errors.append(f"{faction}: mechanics building {building_sid} found {len(found)} times")
                continue
            section, row = found[0]
            want_section = O.native_city_building_section_for_spec(spec)
            if section != want_section:
                errors.append(f"{faction}: {building_sid} is under {section}, its bonuses apply only under {want_section}")
            try:
                expected = O.city_building_mechanic_bonuses(manifest, {**spec, "growth": ()})
                expected.extend(O.homm3_native_growth_bonuses(item, manifest, spec))
            except RuntimeError as ex:
                errors.append(f"{faction}: {building_sid}: {ex}")
                continue
            if _canon(row.get("bonuses")) != _canon(expected):
                errors.append(f"{faction}: {building_sid} bonuses {row.get('bonuses')} != native {expected}")
        if faction == "homm3_necropolis":
            errors.extend(converter_errors(faction, item))
    return errors


def core_errors(core: Path, *, mechanics: bool = True) -> tuple[list[str], int]:
    errors: list[str] = []
    checked = 0
    with zipfile.ZipFile(core) as zf:
        names = zf.namelist()
        english = _texts(_read(zf, "Lang/english/texts/cities.json"))
        units = _texts(_read(zf, "Lang/english/texts/units.json"))
        locales: dict[str, dict[str, Any]] = {}
        locale_units: dict[str, dict[str, Any]] = {}
        for lang in L.LOCALES:
            cities_name = f"Lang/{lang}/texts/cities.json"
            units_name = f"Lang/{lang}/texts/units.json"
            if cities_name not in names or units_name not in names:
                errors.append(f"{lang}: cities.json/units.json missing from Core")
                continue
            locales[lang] = _texts(_read(zf, cities_name))
            locale_units[lang] = _texts(_read(zf, units_name))
        vanilla_treasury = next(
            (row for _section, row in sum(_rows_by_sid(_read(zf, VANILLA_TREASURY_CITY)["array"][0]).values(), [])
             if row.get("sid") == "Build_Treasury"),
            None,
        )
        if vanilla_treasury is None:
            errors.append(f"{VANILLA_TREASURY_CITY}: vanilla Treasury row missing")
        city_members = sorted(n for n in names if n.startswith(CITY_PREFIX) and n.endswith("_city.json"))
        if len(city_members) < 12:
            errors.append(f"expected at least 12 homm3 city documents, found {len(city_members)}")

        def unit_name(unit_sid: str) -> str:
            text = units.get(f"{unit_sid}_name")
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"unit {unit_sid} has no English name")
            return text

        for member in city_members:
            doc = _read(zf, member)
            items = doc.get("array") if isinstance(doc, dict) else None
            if not isinstance(items, list) or not items or not isinstance(items[0], dict):
                errors.append(f"{member}: no city row")
                continue
            item = items[0]
            city = item.get("id")
            errors.extend(native_section_errors(str(city), item))
            if vanilla_treasury is not None:
                errors.extend(treasury_errors(str(city), item, vanilla_treasury))
            try:
                levels = list(iter_city_building_levels(item))
            except ValueError as ex:
                errors.append(f"{city}: {ex}")
                continue
            name_keys: list[str] = []
            for section, row, level_index, level_count in levels:
                checked += 1
                where = f"{city}:{row.get('sid')} L{level_index + 1}"
                keys: dict[str, str] = {}
                for field in ("names", "descriptions", "narrativeDescriptions"):
                    values = row.get(field)
                    if not isinstance(values, list) or len(values) != level_count or not isinstance(values[level_index], str):
                        errors.append(f"{where}: {field} does not cover this level")
                        continue
                    keys[field] = values[level_index]
                if len(keys) != 3:
                    continue
                name_key, desc_key, narr_key = keys["names"], keys["descriptions"], keys["narrativeDescriptions"]
                name_keys.append(name_key)
                errors.extend(f"{where}: {p}" for p in text_problems(english.get(name_key), name_key, kind="name"))
                if row.get("sid") == "Build_Treasury" and english.get(name_key) != "Blacksmith":
                    errors.append(f"{where}: Treasury row must be named 'Blacksmith', got {english.get(name_key)!r}")
                desc = english.get(desc_key)
                desc_problems = text_problems(desc, desc_key, kind="description")
                errors.extend(f"{where}: {p}" for p in desc_problems)
                if not desc_problems:
                    try:
                        expected = derive_building_description(section, row, level_index, level_count, unit_name, item)
                    except ValueError as ex:
                        errors.append(f"{where}: no derived description ({ex})")
                    else:
                        if desc != expected:
                            errors.append(f"{where}: description {desc!r} != derived {expected!r}")
                if english.get(narr_key) != desc:
                    errors.append(f"{where}: narrativeDescription {english.get(narr_key)!r} != description")

            # Locales: exact re-render from the same sentences.
            try:
                sentences_by_key = derive_city_description_sentences(item)
            except ValueError as ex:
                errors.append(f"{city}: {ex}")
                continue
            for lang, texts in sorted(locales.items()):
                lunits = locale_units[lang]
                vanilla = {k: v for k, v in texts.items() if not k.startswith("Homm3")}

                def lunit(unit_sid: str, lunits: dict[str, Any] = lunits, lang: str = lang) -> str:
                    text = lunits.get(f"{unit_sid}_name")
                    if not isinstance(text, str) or not text.strip():
                        raise ValueError(f"unit {unit_sid} has no {lang} name")
                    return text

                def lvanilla(key: str, vanilla: dict[str, Any] = vanilla, lang: str = lang) -> str:
                    text = vanilla.get(key)
                    if not isinstance(text, str) or not text.strip():
                        raise ValueError(f"vanilla {lang} row {key} missing")
                    return text

                for key, sentences in sorted(sentences_by_key.items()):
                    text = texts.get(key)
                    try:
                        expected = render_sentences(lang, sentences, lunit, lvanilla)
                    except (ValueError, KeyError) as ex:
                        errors.append(f"{city}: {lang} {key}: cannot render ({ex})")
                        continue
                    if text != expected:
                        errors.append(f"{city}: {lang} {key} {text!r} != rendered {expected!r}")
                    errors.extend(f"{city}: {p}" for p in locale_text_problems(lang, text, english.get(key), key))
                for name_key in name_keys:
                    text = texts.get(name_key)
                    if not isinstance(text, str) or not text.strip():
                        errors.append(f"{city}: {lang} has no text for {name_key}")
                        continue
                    if "{" in text or "}" in text:
                        errors.append(f"{city}: {lang} {name_key} has an unfilled placeholder {text!r}")
                    localized = L.BUILDING_NAMES.get(english.get(name_key) or "")
                    if localized is not None and text != localized[lang]:
                        errors.append(f"{city}: {lang} {name_key} {text!r} != localized name {localized[lang]!r}")
                    for pattern in L.COMMON_FORBIDDEN + L.FORBIDDEN_PATTERNS[lang]:
                        if re.search(pattern, text, re.IGNORECASE):
                            errors.append(f"{city}: {lang} name {name_key} has forbidden term ({pattern}): {text!r}")
        if mechanics:
            errors.extend(mechanics_errors(zf))
    return errors, checked


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    args = parser.parse_args()
    if not args.core.is_file():
        errors, checked = [f"Core.zip not found: {args.core}"], 0
    else:
        errors, checked = core_errors(args.core)
    for message in errors[:200]:
        print(f"ERROR: {message}")
    if len(errors) > 200:
        print(f"ERROR: ... {len(errors) - 200} more")
    print(f"homm3 city building descriptions contract ({args.core}): levels={checked} errors={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
