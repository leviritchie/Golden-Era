#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
DEFAULT_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"
DEFAULT_ICON_ASSIGNMENTS_PATH = ROOT / "custom_factions" / "custom_law_homm4_icon_assignments.json"
DEFAULT_LOCALIZATION_HANDOFF_PATH = ROOT / "custom_factions" / "custom_law_localization_handoff.json"
DEFAULT_MANIFEST_DIR = ROOT / "custom_factions"
DEFAULT_OVERLAY_SCRIPT = ROOT / "tools" / "release_port" / "apply_release_core_overlay.py"
LOCALIZATION_STATUS = "needs translation refresh for current native-data source text"
ICON_CLASSIFICATION = "native-data-implemented"
LOCALIZATION_KEYS = {
    "lawSid",
    "faction",
    "lawIndex",
    "sourceFile",
    "englishName",
    "englishDescription",
    "localizationStatus",
}
ICON_REQUIRED_KEYS = {
    "faction",
    "lawSid",
    "lawIndex",
    "name",
    "description",
    "classification",
    "homm4IconLabel",
    "homm4IconPath",
    "absoluteImagePath",
    "runtimeIconKey",
}
STALE_TEXT_MARKERS = (
    "candidate-runtime",
    "battle-local Avenger",
    "custom Avenger mark",
    "This candidate uses custom battle state",
    "source/build validated only",
    "runtime hooks are source/build validated",
    "Runtime combat proof",
    "no gameplay effect is active",
    "temporary-mana",
    "battle-local Burning Ash",
    "does not mutate native buff/status data",
    "spellbook placement toggles",
)
def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def iter_strings(value: Any) -> list[str]:
    strings: list[str] = []
    if isinstance(value, str):
        strings.append(value)
    elif isinstance(value, dict):
        for child in value.values():
            strings.extend(iter_strings(child))
    elif isinstance(value, list):
        for child in value:
            strings.extend(iter_strings(child))
    return strings


def collect_stale_markers(value: Any) -> list[str]:
    found: list[str] = []
    for text in iter_strings(value):
        for marker in STALE_TEXT_MARKERS:
            if marker in text:
                found.append(marker)
    return sorted(set(found))


def parse_law_sid(sid: str) -> tuple[str, int] | None:
    prefix = "fraction_law_homm3_"
    if not sid.startswith(prefix):
        return None
    faction_and_index = sid[len(prefix):]
    faction, separator, index_text = faction_and_index.rpartition("_")
    if not separator or not faction:
        return None
    try:
        return faction, int(index_text)
    except ValueError:
        return None


def load_target_sids(path: Path) -> set[str]:
    doc = load_json(path)
    targets = doc.get("targets") if isinstance(doc, dict) else None
    if not isinstance(targets, list):
        raise ValueError(f"{rel(path)} has no targets list")
    result: set[str] = set()
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError(f"{rel(path)} contains a non-object target row")
        sid = target.get("lawSid")
        status = target.get("implementationStatus")
        if not isinstance(sid, str):
            raise ValueError(f"{rel(path)} contains target row without lawSid: {target!r}")
        if status != "native-exact":
            raise ValueError(f"{sid}: current auxiliary handoff gate expects native-exact targets, got {status!r}")
        result.add(sid)
    return result


def load_current_laws(targets_path: Path, override_dir: Path) -> dict[str, dict[str, Any]]:
    target_sids = load_target_sids(targets_path)
    laws: dict[str, dict[str, Any]] = {}
    for path in sorted(override_dir.glob("homm3_*.json")):
        doc = load_json(path)
        overrides = doc.get("lawOverrides") if isinstance(doc, dict) else None
        if not isinstance(overrides, dict):
            raise ValueError(f"{rel(path)} has no lawOverrides object")
        for sid, row in sorted(overrides.items()):
            if sid not in target_sids:
                continue
            if not isinstance(row, dict):
                raise ValueError(f"{rel(path)}:{sid}: override row must be an object")
            if row.get("enabled") is not True:
                raise ValueError(f"{rel(path)}:{sid}: target-backed law row must be enabled")
            parsed = parse_law_sid(sid)
            if parsed is None:
                raise ValueError(f"{rel(path)}:{sid}: cannot parse law SID")
            faction, law_index = parsed
            name = row.get("nameText")
            description = row.get("descriptionText")
            if not isinstance(name, str) or not name:
                raise ValueError(f"{rel(path)}:{sid}: nameText must be a non-empty string")
            if not isinstance(description, str) or not description:
                raise ValueError(f"{rel(path)}:{sid}: descriptionText must be a non-empty string")
            laws[sid] = {
                "faction": faction,
                "lawIndex": law_index,
                "sourceFile": path.name,
                "name": name,
                "description": description,
                "homm4IconLabel": row.get("homm4IconLabel"),
                "homm4IconPath": row.get("homm4IconPath"),
                "iconKey": row.get("iconKey"),
            }
    missing = sorted(target_sids - set(laws))
    if missing:
        raise ValueError("target-backed laws missing from overrides: " + ", ".join(missing))
    return laws


def validate_icon_assignments(path: Path, laws: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    doc = load_json(path)
    if not isinstance(doc, dict):
        return [f"{rel(path)} root must be an object"]
    purpose = doc.get("purpose")
    if not isinstance(purpose, str) or "current native-data" not in purpose or "law_overrides" not in purpose:
        errors.append(f"{rel(path)} purpose must state that rows are current native-data rows synchronized from law_overrides")
    markers = collect_stale_markers(doc)
    if markers:
        errors.append(f"{rel(path)} contains stale runtime/custom-law markers: {', '.join(markers)}")
    assignments = doc.get("assignments")
    if not isinstance(assignments, list):
        return errors + [f"{rel(path)} assignments must be a list"]
    rows_by_sid: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(assignments):
        if not isinstance(row, dict):
            errors.append(f"{rel(path)} assignments[{index}] must be an object")
            continue
        missing_keys = sorted(ICON_REQUIRED_KEYS - set(row))
        if missing_keys:
            errors.append(f"{rel(path)} assignments[{index}] missing keys: {', '.join(missing_keys)}")
        forbidden_keys = sorted({"nameText", "descriptionText", "status", "localizationStatus"} & set(row))
        if forbidden_keys:
            errors.append(f"{rel(path)} assignments[{index}] carries stale/non-icon keys: {', '.join(forbidden_keys)}")
        sid = row.get("lawSid")
        if not isinstance(sid, str):
            errors.append(f"{rel(path)} assignments[{index}] lawSid must be a string")
            continue
        if sid in rows_by_sid:
            errors.append(f"{rel(path)} duplicate icon assignment for {sid}")
        rows_by_sid[sid] = row
        expected = laws.get(sid)
        if expected is None:
            errors.append(f"{rel(path)}:{sid}: icon assignment is not backed by current target law overrides")
            continue
        checks = {
            "faction": expected["faction"],
            "lawIndex": expected["lawIndex"],
            "name": expected["name"],
            "description": expected["description"],
            "classification": ICON_CLASSIFICATION,
            "runtimeIconKey": f"{sid}_icon",
        }
        for key, expected_value in checks.items():
            if row.get(key) != expected_value:
                errors.append(f"{rel(path)}:{sid}: {key} is {row.get(key)!r}, expected {expected_value!r}")
        for key in ("homm4IconLabel", "homm4IconPath", "absoluteImagePath"):
            if not isinstance(row.get(key), str) or not row.get(key):
                errors.append(f"{rel(path)}:{sid}: {key} must be a non-empty string")
    return errors


def validate_localization_handoff(path: Path, laws: dict[str, dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    doc = load_json(path)
    if not isinstance(doc, dict):
        return [f"{rel(path)} root must be an object"]
    purpose = doc.get("purpose")
    limitation = doc.get("limitation")
    if not isinstance(purpose, str) or "Current native-data" not in purpose:
        errors.append(f"{rel(path)} purpose must identify current native-data law text")
    if not isinstance(limitation, str) or "law_overrides" not in limitation or "disabled runtime" not in limitation:
        errors.append(f"{rel(path)} limitation must identify law_overrides synchronization and disabled runtime ambition drift")
    markers = collect_stale_markers(doc)
    if markers:
        errors.append(f"{rel(path)} contains stale runtime/custom-law markers: {', '.join(markers)}")
    rows = doc.get("rows")
    if not isinstance(rows, list):
        return errors + [f"{rel(path)} rows must be a list"]
    rows_by_sid: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"{rel(path)} rows[{index}] must be an object")
            continue
        extra_keys = sorted(set(row) - LOCALIZATION_KEYS)
        missing_keys = sorted(LOCALIZATION_KEYS - set(row))
        if extra_keys:
            errors.append(f"{rel(path)} rows[{index}] has non-canonical keys: {', '.join(extra_keys)}")
        if missing_keys:
            errors.append(f"{rel(path)} rows[{index}] missing keys: {', '.join(missing_keys)}")
        sid = row.get("lawSid")
        if not isinstance(sid, str):
            errors.append(f"{rel(path)} rows[{index}] lawSid must be a string")
            continue
        if sid in rows_by_sid:
            errors.append(f"{rel(path)} duplicate localization handoff row for {sid}")
        rows_by_sid[sid] = row
        expected = laws.get(sid)
        if expected is None:
            errors.append(f"{rel(path)}:{sid}: localization row is not backed by current target law overrides")
            continue
        checks = {
            "faction": expected["faction"],
            "lawIndex": expected["lawIndex"],
            "sourceFile": expected["sourceFile"],
            "englishName": expected["name"],
            "englishDescription": expected["description"],
            "localizationStatus": LOCALIZATION_STATUS,
        }
        for key, expected_value in checks.items():
            if row.get(key) != expected_value:
                errors.append(f"{rel(path)}:{sid}: {key} is {row.get(key)!r}, expected {expected_value!r}")
    expected_sids = sorted(laws)
    actual_sids = sorted(rows_by_sid)
    if actual_sids != expected_sids:
        missing = sorted(set(expected_sids) - set(actual_sids))
        extra = sorted(set(actual_sids) - set(expected_sids))
        if missing:
            errors.append(f"{rel(path)} missing localization handoff rows: {', '.join(missing)}")
        if extra:
            errors.append(f"{rel(path)} has extra localization handoff rows: {', '.join(extra)}")
    return errors


def validate(
    targets_path: Path,
    override_dir: Path,
    icon_assignments_path: Path,
    localization_handoff_path: Path,
    manifest_dir: Path,
    overlay_script: Path,
) -> list[str]:
    laws = load_current_laws(targets_path, override_dir)
    errors: list[str] = []
    errors.extend(validate_icon_assignments(icon_assignments_path, laws))
    errors.extend(validate_localization_handoff(localization_handoff_path, laws))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate current custom-law icon/localization handoff files cannot carry stale runtime-law claims."
    )
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--override-dir", type=Path, default=DEFAULT_OVERRIDE_DIR)
    parser.add_argument("--icon-assignments", type=Path, default=DEFAULT_ICON_ASSIGNMENTS_PATH)
    parser.add_argument("--localization-handoff", type=Path, default=DEFAULT_LOCALIZATION_HANDOFF_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--overlay-script", type=Path, default=DEFAULT_OVERLAY_SCRIPT)
    args = parser.parse_args()

    try:
        errors = validate(
            args.targets,
            args.override_dir,
            args.icon_assignments,
            args.localization_handoff,
            args.manifest_dir,
            args.overlay_script,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"custom law auxiliary handoff validation failed: {exc}")
        return 1
    if errors:
        print("custom law auxiliary handoff validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print("custom law auxiliary handoff validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
