#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, core_overlay_enabled, load_json  # noqa: E402


DEFAULT_TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
DEFAULT_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"
ENGLISH_FACTION_LAW_TEXT_MEMBER = "Lang/english/texts/factionLaws.json"
RESOURCE_RICHES_LAW_ICONS: dict[int, str] = {3: "fraction_law_human_3_icon", 16: "fraction_law_human_16_icon", 29: "fraction_law_human_29_icon"}
DIRECT_RESOURCE_LAW_ICONS: dict[str, str] = {
    "gold": "fraction_law_human_1_icon",
    "gems": "fraction_law_human_14_icon",
    "gemstones": "fraction_law_human_14_icon",
    "crystal": "fraction_law_nature_14_icon",
    "crystals": "fraction_law_nature_14_icon",
    "mercury": "fraction_law_dungeon_14_icon",
}
ASTROLOGY_LAW_ICON = "fraction_law_human_34_icon"
CUSTOM_LAW_EXPLICIT_INDEX_ICONS: dict[int, str] = {
    # Shared generic law families whose visual identity is not derivable from
    # parametersPerLevel still need explicit contracts; donor-row icon fallback
    # is forbidden so mismatches remain traceable.
    5: "fraction_law_human_5_icon",
    7: "fraction_law_human_7_icon",
    8: "fraction_law_human_8_icon",
    9: "fraction_law_human_9_icon",
    12: "fraction_law_human_12_icon",
    20: "fraction_law_human_20_icon",
    22: "fraction_law_human_22_icon",
    25: "fraction_law_human_25_icon",
    26: "fraction_law_human_26_icon",
    28: "fraction_law_human_28_icon",
    31: "fraction_law_human_32_icon",
    32: "fraction_law_human_32_icon",
}
DONOR_UNIT_LAW_INDICES: dict[str, tuple[int, ...]] = {
    "human": (4, 10, 11, 17, 23, 24, 30),
    "nature": (5, 6, 10, 16, 22, 23, 27),
    "dungeon": (4, 10, 11, 18, 19, 25, 31),
    "undead": (4, 5, 10, 11, 18, 19, 23),
}
CASTLE_UNIT_LAW_EXPECTATIONS: dict[int, dict[str, Any]] = {
    4: {"icon": "h3_pikeman", "name": "Pikeman Muster", "desc": "Pikeman growth increases by 4. The line gains +1/+2 maximum Damage by rank.", "unit": "h3_pikeman"},
    10: {"icon": "h3_archer", "name": "Archer Muster", "desc": "Archer growth increases by 4. The line gains +1/+2 minimum Damage by rank.", "unit": "h3_archer"},
    11: {"icon": "h3_griffin", "name": "Griffin Muster", "desc": "Griffin growth increases by 2. The line gains +5/+10 HP by rank.", "unit": "h3_griffin"},
    17: {"icon": "h3_swordsman", "name": "Swordsman Muster", "desc": "Swordsman growth increases by 2. The line gains +5/+10 HP by rank.", "unit": "h3_swordsman"},
    23: {"icon": "h3_monk", "name": "Monk Muster", "desc": "Monk growth increases by 1. The line gains +2/+4 Attack by rank.", "unit": "h3_monk"},
    24: {"icon": "h3_cavalier", "name": "Cavalier Muster", "desc": "Cavalier growth increases by 1. The line gains +2/+4 Attack by rank.", "unit": "h3_cavalier"},
    30: {"icon": "h3_angel", "name": "Angel Muster", "desc": "Angel growth increases by 1. The line deals 5%/10% more damage by rank.", "unit": "h3_angel"},
}

VAGUE_DESCRIPTION_TERMS: tuple[str, ...] = (
    "improve",
    "improves",
    "improved",
    "increased",
    "more damage",
    "more melee damage",
    "more ranged damage",
    "additional-action chance",
    "gains morale",
    "gains increased",
    "gold income is increased",
    "astrology progress is increased",
    "last longer",
    "spell school package",
)
NUMERIC_DETAIL_RE = re.compile(r"[+\-]?\d|%")


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def read_zip_json(core: zipfile.ZipFile, member: str) -> Any:
    with core.open(member) as f:
        return json.loads(f.read().decode("utf-8-sig"))


def load_enabled_law_tables(manifest_dir: Path, v: Validation) -> dict[str, str]:
    law_tables: dict[str, str] = {}
    for path in sorted(manifest_dir.glob("homm3_*.json")):
        doc = load_json(path)
        if not isinstance(doc, dict):
            v.error(f"{path}: manifest root must be an object")
            continue
        if not core_overlay_enabled(doc):
            continue
        identity = doc.get("identity")
        faction_sid = identity.get("factionSid") if isinstance(identity, dict) else None
        overlay = doc.get("coreOverlay")
        laws_table = overlay.get("lawsTable") if isinstance(overlay, dict) else None
        if not isinstance(faction_sid, str) or not faction_sid:
            v.error(f"{path}: enabled manifest missing identity.factionSid")
            continue
        if not isinstance(laws_table, str) or not laws_table:
            v.error(f"{path}: enabled manifest missing coreOverlay.lawsTable")
            continue
        law_tables[faction_sid] = laws_table
    return law_tables


def load_enabled_manifests(manifest_dir: Path, v: Validation) -> dict[str, dict[str, Any]]:
    manifests: dict[str, dict[str, Any]] = {}
    for path in sorted(manifest_dir.glob("homm3_*.json")):
        doc = load_json(path)
        if not isinstance(doc, dict):
            v.error(f"{path}: manifest root must be an object")
            continue
        if not core_overlay_enabled(doc):
            continue
        identity = doc.get("identity")
        faction_sid = identity.get("factionSid") if isinstance(identity, dict) else None
        if not isinstance(faction_sid, str) or not faction_sid:
            v.error(f"{path}: enabled manifest missing identity.factionSid")
            continue
        manifests[faction_sid] = doc
    return manifests


def target_packet(targets_doc: dict[str, Any], target: dict[str, Any]) -> str | None:
    families = targets_doc.get("families")
    law_index = target.get("lawIndex")
    family = families.get(str(law_index)) if isinstance(families, dict) else None
    packet = family.get("packet") if isinstance(family, dict) else None
    return packet if isinstance(packet, str) and packet else None


def load_targets_by_faction(targets_path: Path, v: Validation) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    doc = load_json(targets_path)
    if not isinstance(doc, dict):
        v.error("custom law targets root must be an object")
        return {}, {}
    targets = doc.get("targets")
    if not isinstance(targets, list):
        v.error("custom law targets must contain targets list")
        return {}, doc
    by_faction: dict[str, list[dict[str, Any]]] = {}
    for target in targets:
        if not isinstance(target, dict):
            v.error("target entry must be an object")
            continue
        faction = target.get("faction")
        law_sid = target.get("lawSid")
        if not isinstance(faction, str) or not faction:
            v.error(f"target missing faction: {target!r}")
            continue
        if not isinstance(law_sid, str) or not law_sid:
            v.error(f"{faction}: target missing lawSid")
            continue
        by_faction.setdefault(faction, []).append(target)
    return by_faction, doc


def load_override_rows(override_dir: Path, v: Validation) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for path in sorted(override_dir.glob("homm3_*.json")):
        doc = load_json(path)
        overrides = doc.get("lawOverrides") if isinstance(doc, dict) else None
        if not isinstance(overrides, dict):
            v.error(f"{path}: missing lawOverrides object")
            continue
        for sid, row in sorted(overrides.items()):
            if not isinstance(sid, str) or not isinstance(row, dict):
                continue
            rows[sid] = row
    return rows


def load_english_faction_law_texts(core: zipfile.ZipFile, members: set[str], v: Validation) -> dict[str, str]:
    if ENGLISH_FACTION_LAW_TEXT_MEMBER not in members:
        v.error(f"Core.zip missing {ENGLISH_FACTION_LAW_TEXT_MEMBER}")
        return {}
    doc = read_zip_json(core, ENGLISH_FACTION_LAW_TEXT_MEMBER)
    rows = None
    if isinstance(doc, dict):
        rows = doc.get("tokens")
        if not isinstance(rows, list):
            rows = doc.get("array")
    if not isinstance(rows, list):
        v.error(f"{ENGLISH_FACTION_LAW_TEXT_MEMBER}: root must contain tokens or array list")
        return {}
    texts: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sid = row.get("sid")
        text = row.get("text")
        if isinstance(sid, str) and isinstance(text, str):
            texts[sid] = text
    return texts


def description_needs_numeric_detail(text: str) -> bool:
    lower = text.lower()
    return any(term in lower for term in VAGUE_DESCRIPTION_TERMS) and NUMERIC_DETAIL_RE.search(text) is None


def validate_source_description_specificity(source_rows: dict[str, dict[str, Any]], v: Validation) -> None:
    for law_sid, row in sorted(source_rows.items()):
        desc_text = row.get("descriptionText")
        if isinstance(desc_text, str) and description_needs_numeric_detail(desc_text):
            v.error(f"{law_sid}: source description is vague and lacks numeric detail: {desc_text!r}")



def validate_target_mechanic_specificity(targets_by_faction: dict[str, list[dict[str, Any]]], v: Validation) -> None:
    for faction, targets in sorted(targets_by_faction.items()):
        for target in targets:
            law_sid = target.get("lawSid")
            mechanic = target.get("targetMechanic")
            if isinstance(mechanic, str) and description_needs_numeric_detail(mechanic):
                v.error(f"{faction}:{law_sid}: targetMechanic is vague and lacks numeric detail: {mechanic!r}")

def validate_row_source_parity(
    member: str,
    law_sid: str,
    row: dict[str, Any],
    source_row: dict[str, Any] | None,
    english_texts: dict[str, str],
    v: Validation,
) -> None:
    if source_row is None:
        v.error(f"{member}:{law_sid}: missing source override row for target-backed generated law")
        return
    if source_row.get("enabled") is not True:
        v.error(f"{member}:{law_sid}: source override row must be enabled")
    name_text = source_row.get("nameText")
    desc_text = source_row.get("descriptionText")
    source_levels = source_row.get("parametersPerLevel")
    if not isinstance(name_text, str) or not name_text.strip():
        v.error(f"{member}:{law_sid}: source override row missing nameText")
    if not isinstance(desc_text, str) or not desc_text.strip():
        v.error(f"{member}:{law_sid}: source override row missing descriptionText")
    if not isinstance(source_levels, list) or not source_levels:
        v.error(f"{member}:{law_sid}: source override row missing parametersPerLevel")
    expected_name_token = f"{law_sid}_name"
    expected_desc_token = f"{law_sid}_desc"
    if row.get("name") != expected_name_token:
        v.error(f"{member}:{law_sid}: generated name token is {row.get('name')!r}, expected {expected_name_token!r}")
    if row.get("desc") != expected_desc_token:
        v.error(f"{member}:{law_sid}: generated desc token is {row.get('desc')!r}, expected {expected_desc_token!r}")
    if isinstance(name_text, str) and english_texts.get(expected_name_token) != name_text.strip():
        v.error(
            f"{ENGLISH_FACTION_LAW_TEXT_MEMBER}:{expected_name_token}: text is "
            f"{english_texts.get(expected_name_token)!r}, expected {name_text.strip()!r}"
        )
    if isinstance(desc_text, str) and english_texts.get(expected_desc_token) != desc_text.strip():
        v.error(
            f"{ENGLISH_FACTION_LAW_TEXT_MEMBER}:{expected_desc_token}: text is "
            f"{english_texts.get(expected_desc_token)!r}, expected {desc_text.strip()!r}"
        )
    if isinstance(source_levels, list) and row.get("parametersPerLevel") != source_levels:
        v.error(f"{member}:{law_sid}: generated parametersPerLevel does not exactly match source override row")


def row_by_id(doc: Any, member: str, v: Validation) -> dict[str, dict[str, Any]]:
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        v.error(f"{member}: law table root missing array")
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_id = row.get("id")
        if isinstance(row_id, str) and row_id:
            result[row_id] = row
    return result


def validate_generated_law_table_shape(faction_sid: str, member: str, rows: dict[str, dict[str, Any]], v: Validation) -> None:
    indices: set[int] = set()
    prefix = f"fraction_law_{faction_sid}_"
    for row_id, row in rows.items():
        if not row_id.startswith(prefix):
            continue
        suffix = row_id.removeprefix(prefix)
        if not suffix.isdigit():
            v.error(f"{member}:{row_id}: custom law row id does not end with a numeric index")
            continue
        indices.add(int(suffix))
        levels = row.get("parametersPerLevel")
        if not isinstance(levels, list) or not levels:
            v.error(f"{member}:{row_id}: generated custom law row must have non-empty parametersPerLevel")
            continue
        for level_index, level in enumerate(levels, 1):
            if not isinstance(level, dict):
                v.error(f"{member}:{row_id}: level {level_index} must be an object")
                continue
            bonuses = level.get("bonuses")
            if bonuses == []:
                v.error(f"{member}:{row_id}: level {level_index} has empty bonuses array; use a native loader anchor or disable the law")
            elif not isinstance(bonuses, list):
                v.error(f"{member}:{row_id}: level {level_index} missing bonuses list")
    if indices:
        missing = [index for index in range(1, max(indices) + 1) if index not in indices]
        if missing:
            v.error(f"{member}: generated custom law indices must be contiguous from 1 to {max(indices)}; missing {missing}")


DONOR_FRACTION_ID_BY_RUNTIME: dict[str, str] = {
    "humans": "human",
    "human": "human",
    "demons": "demon",
    "demon": "demon",
    "undead": "undead",
    "necros": "undead",
    "dungeon": "dungeon",
    "nature": "nature",
    "unfrozen": "unfrozen",
}


def donor_fraction_sid(manifest: dict[str, Any]) -> str:
    overlay = manifest.get("coreOverlay")
    identity = manifest.get("identity")
    donor = overlay.get("donorFactionCoreSid") if isinstance(overlay, dict) else None
    if not isinstance(donor, str) or not donor:
        donor = identity.get("donorFactionSid") if isinstance(identity, dict) else None
    if not isinstance(donor, str) or not donor:
        return "human"
    return DONOR_FRACTION_ID_BY_RUNTIME.get(donor, donor)


def direct_resource_icon(row: dict[str, Any], index: int | None) -> str | None:
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list):
        return None
    bonuses: list[dict[str, Any]] = []
    for level in levels:
        if not isinstance(level, dict):
            continue
        level_bonuses = level.get("bonuses")
        if isinstance(level_bonuses, list):
            bonuses.extend(bonus for bonus in level_bonuses if isinstance(bonus, dict))
    if not bonuses:
        return None
    if all(bonus.get("type") == "astrologyExp" for bonus in bonuses):
        return ASTROLOGY_LAW_ICON
    if all(bonus.get("type") == "sideRes" for bonus in bonuses):
        resources: set[str] = set()
        for bonus in bonuses:
            parameters = bonus.get("parameters")
            if isinstance(parameters, list) and parameters and isinstance(parameters[0], str):
                resources.add(parameters[0])
        if len(resources) == 1:
            return DIRECT_RESOURCE_LAW_ICONS.get(next(iter(resources)))
    if all(bonus.get("type") == "sideOneTimeAddRes" for bonus in bonuses):
        resources: set[str] = set()
        for bonus in bonuses:
            parameters = bonus.get("parameters")
            if isinstance(parameters, list) and parameters and isinstance(parameters[0], str):
                resources.add(parameters[0])
        if index is not None and {"gold", "wood", "ore"}.issubset(resources):
            return RESOURCE_RICHES_LAW_ICONS.get(index)
    return None


def city_units_increment_icon(row: dict[str, Any]) -> str | None:
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list):
        return None
    expected_icon: str | None = None
    for level in levels:
        if not isinstance(level, dict):
            continue
        bonuses = level.get("bonuses")
        if not isinstance(bonuses, list):
            continue
        for bonus in bonuses:
            if not isinstance(bonus, dict) or bonus.get("type") != "cityUnitsIncrement":
                continue
            parameters = bonus.get("parameters")
            if not isinstance(parameters, list) or not parameters:
                continue
            unit_sid = parameters[0]
            if not isinstance(unit_sid, str) or not unit_sid.startswith("h3_"):
                continue
            if expected_icon is None:
                expected_icon = unit_sid
            elif expected_icon != unit_sid:
                return None
    return expected_icon


def law_index(law_sid: str) -> int | None:
    suffix = law_sid.rsplit("_", 1)[-1]
    return int(suffix) if suffix.isdigit() else None


def source_icon_contract(law_sid: str, row: dict[str, Any], source_row: dict[str, Any] | None) -> tuple[str | None, str | None]:
    index = law_index(law_sid)
    resource_icon = direct_resource_icon(row, index)
    if isinstance(resource_icon, str) and resource_icon:
        return resource_icon, "direct resource or astrology production mechanics"
    if isinstance(source_row, dict) and source_row.get("enabled") is not False:
        icon = source_row.get("iconKey")
        homm4_icon_path = source_row.get("homm4IconPath")
        if isinstance(homm4_icon_path, str) and homm4_icon_path.strip() and isinstance(icon, str) and icon.strip():
            return icon.strip(), "HOMM4-backed iconKey"
        portrait_icon = source_row.get("portraitIconSid")
        if isinstance(portrait_icon, str) and portrait_icon.strip():
            return portrait_icon.strip(), "portraitIconSid"
    unit_icon = city_units_increment_icon(row)
    if isinstance(unit_icon, str) and unit_icon:
        return unit_icon, "cityUnitsIncrement custom unit portrait"
    if index is not None:
        explicit_icon = CUSTOM_LAW_EXPLICIT_INDEX_ICONS.get(index)
        if isinstance(explicit_icon, str) and explicit_icon:
            return explicit_icon, "explicit index icon anchor"
    if isinstance(source_row, dict) and source_row.get("enabled") is not False:
        icon = source_row.get("iconKey")
        if isinstance(icon, str) and icon.strip():
            return icon.strip(), "iconKey"
    return None, None


def validate_law_icons(faction_sid: str, member: str, rows: dict[str, dict[str, Any]], source_rows: dict[str, dict[str, Any]], v: Validation) -> None:
    prefix = f"fraction_law_{faction_sid}_"
    for law_sid, row in sorted(rows.items()):
        if not law_sid.startswith(prefix):
            continue
        expected_icon, reason = source_icon_contract(law_sid, row, source_rows.get(law_sid))
        if expected_icon is None:
            v.error(f"{member}:{law_sid}: generated law has no explicit icon contract; donor fallback is forbidden")
            continue
        if row.get("icon") != expected_icon:
            v.error(f"{member}:{law_sid}: generated icon is {row.get('icon')!r}, expected {expected_icon!r} from {reason}")



def validate_castle_unit_law_identity(rows: dict[str, dict[str, Any]], english_texts: dict[str, str], member: str, v: Validation) -> None:
    for index, expected in CASTLE_UNIT_LAW_EXPECTATIONS.items():
        law_sid = f"fraction_law_homm3_castle_{index}"
        row = rows.get(law_sid)
        if row is None:
            v.error(f"{member}:{law_sid}: missing Castle unit-law row")
            continue
        if row.get("icon") != expected["icon"]:
            v.error(f"{member}:{law_sid}: Castle unit-law icon is {row.get('icon')!r}, expected {expected['icon']!r}")
        name_sid = f"{law_sid}_name"
        desc_sid = f"{law_sid}_desc"
        if english_texts.get(name_sid) != expected["name"]:
            v.error(f"{ENGLISH_FACTION_LAW_TEXT_MEMBER}:{name_sid}: Castle unit-law name is {english_texts.get(name_sid)!r}, expected {expected['name']!r}")
        if english_texts.get(desc_sid) != expected["desc"]:
            v.error(f"{ENGLISH_FACTION_LAW_TEXT_MEMBER}:{desc_sid}: Castle unit-law desc is {english_texts.get(desc_sid)!r}, expected {expected['desc']!r}")
        unit_icon = city_units_increment_icon(row)
        if unit_icon != expected["unit"]:
            v.error(f"{member}:{law_sid}: Castle unit-law mechanics increment {unit_icon!r}, expected {expected['unit']!r}")

def validate_row_metadata(row: dict[str, Any], target: dict[str, Any], packet: str | None, v: Validation) -> None:
    law_sid = str(target.get("lawSid"))
    if row.get("xHomm3NoCompromiseTarget") is not True:
        v.error(f"{law_sid}: missing xHomm3NoCompromiseTarget=true")
    expected_status = target.get("implementationStatus")
    if isinstance(expected_status, str) and row.get("xHomm3NoCompromiseStatus") != expected_status:
        v.error(f"{law_sid}: xHomm3NoCompromiseStatus expected {expected_status!r}, got {row.get('xHomm3NoCompromiseStatus')!r}")
    if isinstance(packet, str) and row.get("xHomm3NoCompromisePacket") != packet:
        v.error(f"{law_sid}: xHomm3NoCompromisePacket expected {packet!r}, got {row.get('xHomm3NoCompromisePacket')!r}")
    mechanic = target.get("targetMechanic")
    if isinstance(mechanic, str) and row.get("xHomm3NoCompromiseTargetMechanic") != mechanic:
        v.error(f"{law_sid}: xHomm3NoCompromiseTargetMechanic does not match target spec")


def validate_core(core_path: Path, manifest_dir: Path, targets_path: Path, override_dir: Path, v: Validation) -> None:
    manifests = load_enabled_manifests(manifest_dir, v)
    law_tables = load_enabled_law_tables(manifest_dir, v)
    targets_by_faction, targets_doc = load_targets_by_faction(targets_path, v)
    source_rows = load_override_rows(override_dir, v)
    validate_source_description_specificity(source_rows, v)
    validate_target_mechanic_specificity(targets_by_faction, v)
    if v.errors:
        return

    with zipfile.ZipFile(core_path, "r") as core:
        members = {name.replace("\\", "/") for name in core.namelist()}
        english_texts = load_english_faction_law_texts(core, members, v)
        for faction, targets in sorted(targets_by_faction.items()):
            faction_sid = faction if faction.startswith("homm3_") else f"homm3_{faction}"
            member = law_tables.get(faction_sid)
            if member is None:
                v.error(f"{faction}: no enabled manifest law table found for {faction_sid}")
                continue
            normalized_member = member.replace("\\", "/")
            if normalized_member not in members:
                v.error(f"{faction}: Core.zip missing law table {normalized_member}")
                continue
            rows = row_by_id(read_zip_json(core, normalized_member), normalized_member, v)
            validate_generated_law_table_shape(faction_sid, normalized_member, rows, v)
            validate_law_icons(faction_sid, normalized_member, rows, source_rows, v)
            if faction_sid == "homm3_castle":
                validate_castle_unit_law_identity(rows, english_texts, normalized_member, v)
            for target in targets:
                law_sid = str(target.get("lawSid"))
                row = rows.get(law_sid)
                if row is None:
                    v.error(f"{law_sid}: missing generated law row in {normalized_member}")
                    continue
                validate_row_metadata(row, target, target_packet(targets_doc, target), v)
                validate_row_source_parity(normalized_member, law_sid, row, source_rows.get(law_sid), english_texts, v)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate no-compromise custom law metadata in a generated Core.zip.")
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--override-dir", type=Path, default=DEFAULT_OVERRIDE_DIR)
    args = parser.parse_args()

    v = Validation()
    if not args.core.exists():
        v.error(f"missing Core.zip: {args.core}")
    if not args.manifest_dir.exists():
        v.error(f"missing manifest dir: {args.manifest_dir}")
    if not args.targets.exists():
        v.error(f"missing targets file: {args.targets}")
    if not args.override_dir.exists():
        v.error(f"missing override dir: {args.override_dir}")
    if not v.errors:
        validate_core(args.core, args.manifest_dir, args.targets, args.override_dir, v)

    print(f"errors: {v.errors}")
    if v.warnings:
        print(f"warnings: {v.warnings}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
