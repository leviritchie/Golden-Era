#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
DEFAULT_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"
DEFAULT_CLASSIFICATION_PATH = ROOT / "custom_factions" / "custom_law_runtime_completion_classification.json"
NONFINAL_STATUSES = {"needs-runtime", "temporary-compromise", "blocked"}
PENDING_PREFIX = "Pending no-compromise implementation."
STRICT_MARKER = "source candidate has no concrete bonuses"
RUNTIME_CANDIDATE_MARKER = "runtime candidate has no native JSON bonuses"
RUNTIME_ANCHOR_MARKER = "runtime candidate uses native loader anchor"
RUNTIME_DISABLED_MARKER = "runtime disabled; no native JSON bonuses"
HARD_CASE_DISABLED_MARKER = "hard case disabled; no native JSON bonuses"
EXPLICIT_NO_EFFECT_MARKERS = {
    RUNTIME_CANDIDATE_MARKER,
    RUNTIME_DISABLED_MARKER,
    HARD_CASE_DISABLED_MARKER,
}
NATIVE_LOADER_ANCHOR_BONUS = {"type": "heroStat", "parameters": ["defence", "0"]}


def rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_targets(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    doc = load_json(path)
    if not isinstance(doc, dict):
        raise ValueError(f"{rel(path)} root must be an object")
    families = doc.get("families")
    targets = doc.get("targets")
    if not isinstance(families, dict):
        raise ValueError(f"{rel(path)} has no families object")
    if not isinstance(targets, list):
        raise ValueError(f"{rel(path)} has no targets list")
    packets_by_law_index: dict[str, str] = {}
    for key, family in families.items():
        if isinstance(family, dict) and isinstance(family.get("packet"), str):
            packets_by_law_index[str(key)] = str(family["packet"])
    result: dict[str, dict[str, Any]] = {}
    packets_by_sid: dict[str, str] = {}
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError(f"{rel(path)} contains a non-object target")
        sid = target.get("lawSid")
        law_index = target.get("lawIndex")
        if not isinstance(sid, str) or not isinstance(law_index, int):
            raise ValueError(f"invalid target row: {target!r}")
        packet = packets_by_law_index.get(str(law_index))
        if not isinstance(packet, str):
            raise ValueError(f"{sid}: missing packet for lawIndex {law_index}")
        result[sid] = target
        packets_by_sid[sid] = packet
    return result, packets_by_sid


def load_classifications(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    doc = load_json(path)
    if not isinstance(doc, dict):
        raise ValueError(f"{rel(path)} root must be an object")
    rows = doc.get("classifications")
    if not isinstance(rows, list):
        raise ValueError(f"{rel(path)} has no classifications list")
    result: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f"{rel(path)} contains a non-object classification row")
        sid = row.get("lawSid")
        classification = row.get("classification")
        if not isinstance(sid, str) or not isinstance(classification, str):
            raise ValueError(f"invalid classification row: {row!r}")
        result[sid] = classification
    return result


def iter_override_rows(directory: Path) -> list[tuple[Path, str, dict[str, Any]]]:
    rows: list[tuple[Path, str, dict[str, Any]]] = []
    for path in sorted(directory.glob("homm3_*.json")):
        doc = load_json(path)
        if not isinstance(doc, dict):
            raise ValueError(f"{rel(path)} root must be an object")
        overrides = doc.get("lawOverrides")
        if not isinstance(overrides, dict):
            raise ValueError(f"{rel(path)} has no lawOverrides object")
        for sid, row in sorted(overrides.items()):
            if isinstance(sid, str) and isinstance(row, dict):
                rows.append((path, sid, row))
    return rows


def level_bonus_count(row: dict[str, Any]) -> int:
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list):
        return 0
    total = 0
    for level in levels:
        if not isinstance(level, dict):
            continue
        bonuses = level.get("bonuses")
        if isinstance(bonuses, list):
            total += len(bonuses)
    return total


def has_empty_bonus_levels(row: dict[str, Any]) -> bool:
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list) or not levels:
        return False
    for level in levels:
        if not isinstance(level, dict):
            return False
        bonuses = level.get("bonuses")
        if not isinstance(bonuses, list) or bonuses:
            return False
    return True


def has_any_empty_bonus_level(row: dict[str, Any]) -> bool:
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list):
        return False
    for level in levels:
        if isinstance(level, dict) and level.get("bonuses") == []:
            return True
    return False


def has_native_loader_anchor(row: dict[str, Any]) -> bool:
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list):
        return False
    for level in levels:
        if not isinstance(level, dict):
            continue
        bonuses = level.get("bonuses")
        if isinstance(bonuses, list) and NATIVE_LOADER_ANCHOR_BONUS in bonuses:
            return True
    return False


def validate(targets_path: Path, override_dir: Path, classification_path: Path) -> list[str]:
    targets, packets_by_sid = load_targets(targets_path)
    classifications = load_classifications(classification_path)
    errors: list[str] = []
    pending_rows = 0
    no_effect_rows = 0
    explicit_no_effect_rows = 0
    for path, sid, row in iter_override_rows(override_dir):
        target = targets.get(sid)
        if target is None:
            continue
        status = target.get("implementationStatus")
        packet = packets_by_sid[sid]
        description = row.get("descriptionText")
        notes = row.get("notes")
        marker = row.get("xHomm3NoCompromiseStrictRows")
        bonus_count = level_bonus_count(row)
        empty_levels = has_empty_bonus_levels(row)
        any_empty_level = has_any_empty_bonus_level(row)
        is_pending = isinstance(description, str) and description.startswith(PENDING_PREFIX)
        is_runtime_candidate = marker == RUNTIME_CANDIDATE_MARKER
        is_runtime_anchor = marker == RUNTIME_ANCHOR_MARKER
        is_runtime_disabled = marker == RUNTIME_DISABLED_MARKER
        is_hard_case_disabled = marker == HARD_CASE_DISABLED_MARKER
        classification = classifications.get(sid)
        if any_empty_level:
            errors.append(f"{rel(path)}:{sid}: enabled target law levels must not use empty bonuses arrays; use an explicit native loader anchor or disable the row")
        if marker in EXPLICIT_NO_EFFECT_MARKERS and not empty_levels:
            errors.append(f"{rel(path)}:{sid}: stale no-native-bonuses marker remains on a loader-valid row")
        if is_runtime_anchor:
            if status != "needs-runtime":
                errors.append(f"{rel(path)}:{sid}: runtime loader-anchor row requires needs-runtime target status, got {status!r}")
            if classification != "candidate-runtime-implemented":
                errors.append(f"{rel(path)}:{sid}: runtime loader-anchor row must be classified as candidate-runtime-implemented")
            if not has_native_loader_anchor(row):
                errors.append(f"{rel(path)}:{sid}: runtime loader-anchor row must include the zero-value native loader anchor bonus")
            if not isinstance(notes, str) or "Candidate implemented" not in notes or "Native loader anchor:" not in notes:
                errors.append(f"{rel(path)}:{sid}: runtime loader-anchor row must identify both the runtime owner and native loader anchor in notes")
        if empty_levels:
            no_effect_rows += 1
            if marker in EXPLICIT_NO_EFFECT_MARKERS:
                explicit_no_effect_rows += 1
            if status not in NONFINAL_STATUSES:
                errors.append(f"{rel(path)}:{sid}: native/final target has a no-effect pending-shaped row")
            if not is_pending and marker not in EXPLICIT_NO_EFFECT_MARKERS:
                errors.append(f"{rel(path)}:{sid}: no-effect target row must be pending or carry an explicit runtime-candidate/runtime-disabled/hard-case marker")
            if is_runtime_candidate:
                if status != "needs-runtime":
                    errors.append(f"{rel(path)}:{sid}: runtime candidate row requires needs-runtime target status, got {status!r}")
                if classification != "candidate-runtime-implemented":
                    errors.append(f"{rel(path)}:{sid}: runtime candidate row must be classified as candidate-runtime-implemented")
                if not isinstance(notes, str) or "Candidate implemented" not in notes:
                    errors.append(f"{rel(path)}:{sid}: runtime candidate row must identify the runtime owner in notes")
            if is_runtime_disabled:
                if status != "needs-runtime":
                    errors.append(f"{rel(path)}:{sid}: runtime-disabled row requires needs-runtime target status, got {status!r}")
                if classification != "disabled-no-implemented-surface":
                    errors.append(f"{rel(path)}:{sid}: runtime-disabled row must be classified as disabled-no-implemented-surface")
                if not isinstance(description, str) or not description.startswith("Currently disabled:"):
                    errors.append(f"{rel(path)}:{sid}: runtime-disabled row description must start with 'Currently disabled:'")
                if not isinstance(notes, str) or not notes.startswith("Runtime disabled:"):
                    errors.append(f"{rel(path)}:{sid}: runtime-disabled row notes must start with 'Runtime disabled:'")
            if is_hard_case_disabled:
                if classification != "named-hard-case":
                    errors.append(f"{rel(path)}:{sid}: hard-case row must be classified as named-hard-case")
                if not isinstance(description, str) or not description.startswith("Hard case disabled:"):
                    errors.append(f"{rel(path)}:{sid}: hard-case row description must start with 'Hard case disabled:'")
                if not isinstance(notes, str) or not notes.startswith("Hard case disabled:"):
                    errors.append(f"{rel(path)}:{sid}: hard-case row notes must start with 'Hard case disabled:'")
        if is_pending:
            pending_rows += 1
            if status not in NONFINAL_STATUSES:
                errors.append(f"{rel(path)}:{sid}: pending row points at final/native target status {status!r}")
            if bonus_count != 0:
                errors.append(f"{rel(path)}:{sid}: pending row must not carry concrete bonuses")
            if not isinstance(description, str) or str(target.get("targetMechanic")) not in description:
                errors.append(f"{rel(path)}:{sid}: pending description must include exact targetMechanic text")
            if f"the {packet} packet is runtime-proven and implemented" not in description:
                errors.append(f"{rel(path)}:{sid}: pending description must name packet gate {packet!r}")
            if not isinstance(notes, str) or "Strict no-compromise candidate row" not in notes or packet not in notes:
                errors.append(f"{rel(path)}:{sid}: pending notes must identify strict no-compromise candidate row and packet")
            if marker != STRICT_MARKER:
                errors.append(f"{rel(path)}:{sid}: pending row must carry xHomm3NoCompromiseStrictRows={STRICT_MARKER!r}")
    if pending_rows + explicit_no_effect_rows != no_effect_rows:
        errors.append(f"pending/explicit/no-effect row count mismatch: pending={pending_rows}, explicitNoEffect={explicit_no_effect_rows}, noEffect={no_effect_rows}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate playable no-effect custom law rows are explicit, target-backed, classification-backed, and bonus-free."
    )
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--override-dir", type=Path, default=DEFAULT_OVERRIDE_DIR)
    parser.add_argument("--classification", type=Path, default=DEFAULT_CLASSIFICATION_PATH)
    args = parser.parse_args()

    try:
        errors = validate(args.targets, args.override_dir, args.classification)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"pending custom law source row validation failed: {exc}")
        return 1
    if errors:
        print("pending custom law source row validation failed:")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("pending custom law source row validation passed")
    print("Note: no-effect rows are explicit source hygiene only; this does not prove runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

