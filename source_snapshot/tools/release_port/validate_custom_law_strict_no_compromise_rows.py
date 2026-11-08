#!/usr/bin/env python3
"""Fail-closed strict no-compromise law-row validator.

The normal override layer may keep temporary donor/native rows playable while
runtime packets are still unproven. This validator is for strict no-compromise
candidates: every target that is not `native-exact` must avoid concrete law
bonuses so donor rows cannot be mistaken for the final design.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[2]
TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
LAW_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"

STRICT_NON_FINAL_STATUSES = {"needs-runtime", "temporary-compromise", "blocked"}
PENDING_DESCRIPTION_PREFIX = "Pending no-compromise implementation."


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def load_targets() -> dict[str, dict[str, Any]]:
    doc = load_json(TARGETS_PATH)
    targets = doc.get("targets")
    families = doc.get("families")
    if not isinstance(targets, list):
        raise ValueError(f"{TARGETS_PATH} does not contain a targets list")
    if not isinstance(families, dict):
        raise ValueError(f"{TARGETS_PATH} does not contain a families object")
    result: dict[str, dict[str, Any]] = {}
    for item in targets:
        if not isinstance(item, dict):
            continue
        sid = item.get("lawSid")
        law_index = item.get("lawIndex")
        if isinstance(sid, str):
            if not isinstance(law_index, int):
                raise ValueError(f"{sid} has no integer lawIndex")
            family = families.get(str(law_index))
            if not isinstance(family, dict):
                raise ValueError(f"{sid} references unknown law family {law_index}")
            packet = family.get("packet")
            if not isinstance(packet, str) or not packet:
                raise ValueError(f"{sid} law family {law_index} has no packet")
            enriched = dict(item)
            enriched["packet"] = packet
            result[sid] = enriched
    return result


def has_concrete_law_bonuses(row: dict[str, Any]) -> bool:
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list):
        return False
    for level in levels:
        if not isinstance(level, dict):
            continue
        bonuses = level.get("bonuses")
        if isinstance(bonuses, list) and len(bonuses) > 0:
            return True
    return False


def describe_target(target: dict[str, Any]) -> str:
    return (
        f"{target.get('lawSid')} "
        f"status={target.get('implementationStatus')} "
        f"name={target.get('name')!r}"
    )


def load_override_rows(override_dir: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    rows: dict[str, dict[str, Any]] = {}
    errors: list[str] = []
    for path in sorted(override_dir.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            doc = load_json(path)
        except (OSError, json.JSONDecodeError) as ex:
            errors.append(f"{path.relative_to(ROOT)}: cannot read JSON: {ex}")
            continue
        overrides = doc.get("lawOverrides")
        if not isinstance(overrides, dict):
            errors.append(f"{path.relative_to(ROOT)}: missing lawOverrides object")
            continue
        for sid, row in overrides.items():
            if not isinstance(sid, str):
                continue
            if not isinstance(row, dict):
                errors.append(f"{path.relative_to(ROOT)}: {sid}: override row is not an object")
                continue
            if sid in rows:
                errors.append(f"{path.relative_to(ROOT)}: duplicate override row for {sid}")
                continue
            rows[sid] = row
    return rows, errors


def validate_override_source(targets_by_sid: dict[str, dict[str, Any]], override_dir: Path) -> list[str]:
    override_rows, errors = load_override_rows(override_dir)
    failures = list(errors)
    for sid, target in sorted(targets_by_sid.items()):
        status = target.get("implementationStatus")
        if status not in STRICT_NON_FINAL_STATUSES:
            continue
        row = override_rows.get(sid)
        if row is None:
            failures.append(
                f"{describe_target(target)}: missing strict override row; inherited donor/Core bonuses could survive"
            )
            continue
        if has_concrete_law_bonuses(row):
            failures.append(f"{describe_target(target)}: strict source override still has concrete bonuses")
    return failures


def read_core_law_descriptions(archive: zipfile.ZipFile) -> tuple[dict[str, str], list[str]]:
    member = "Lang/english/texts/factionLaws.json"
    failures: list[str] = []
    try:
        doc = json.loads(archive.read(member).decode("utf-8-sig"))
    except (KeyError, OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
        return {}, [f"{member}: cannot inspect law descriptions: {ex}"]
    tokens = doc.get("tokens") if isinstance(doc, dict) else None
    if not isinstance(tokens, list):
        return {}, [f"{member}: missing tokens list"]
    result: dict[str, str] = {}
    for token in tokens:
        if not isinstance(token, dict):
            failures.append(f"{member}: non-object token row")
            continue
        sid = token.get("sid")
        text = token.get("text")
        if isinstance(sid, str) and isinstance(text, str):
            result[sid] = text
    return result, failures


def validate_pending_description(target: dict[str, Any], descriptions: dict[str, str]) -> list[str]:
    sid = target["lawSid"]
    text = descriptions.get(f"{sid}_desc")
    if not isinstance(text, str):
        return [f"{describe_target(target)}: strict Core row has no generated description token"]
    failures: list[str] = []
    if PENDING_DESCRIPTION_PREFIX not in text:
        failures.append(f"{describe_target(target)}: strict Core description is not marked pending")
    mechanic = target.get("targetMechanic")
    if isinstance(mechanic, str) and mechanic.strip() and mechanic.strip() not in text:
        failures.append(f"{describe_target(target)}: strict Core description does not include target mechanic")
    packet = target.get("packet")
    if isinstance(packet, str) and packet.strip() and packet.strip() not in text:
        failures.append(f"{describe_target(target)}: strict Core description does not include packet name")
    return failures


def iter_candidate_law_rows(node: Any, target_sids: set[str]) -> Iterable[dict[str, Any]]:
    if isinstance(node, dict):
        row_id = node.get("id")
        if isinstance(row_id, str) and row_id in target_sids:
            yield node
        for value in node.values():
            yield from iter_candidate_law_rows(value, target_sids)
    elif isinstance(node, list):
        for item in node:
            yield from iter_candidate_law_rows(item, target_sids)


def validate_core_zip(core: Path, targets_by_sid: dict[str, dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    target_sids = set(targets_by_sid)
    seen: set[str] = set()
    try:
        archive = zipfile.ZipFile(core)
    except (OSError, zipfile.BadZipFile) as ex:
        return [f"{core}: cannot open Core.zip: {ex}"]
    with archive:
        descriptions, description_failures = read_core_law_descriptions(archive)
        failures.extend(description_failures)
        for info in archive.infolist():
            member = info.filename.replace("\\", "/")
            if info.is_dir() or not member.lower().endswith(".json") or "law" not in member.lower():
                continue
            try:
                data = archive.read(info)
                doc = json.loads(data.decode("utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as ex:
                failures.append(f"{member}: cannot inspect JSON: {ex}")
                continue
            for row in iter_candidate_law_rows(doc, target_sids):
                sid = row.get("id")
                if not isinstance(sid, str):
                    continue
                seen.add(sid)
                target = targets_by_sid[sid]
                status = target.get("implementationStatus")
                if status in STRICT_NON_FINAL_STATUSES and has_concrete_law_bonuses(row):
                    failures.append(f"{member}: {describe_target(target)}: strict Core row still has concrete bonuses")
                if status in STRICT_NON_FINAL_STATUSES and not has_concrete_law_bonuses(row):
                    failures.extend(validate_pending_description(target, descriptions))

    missing = sorted(target_sids - seen)
    if missing:
        failures.append(
            "Core inspection did not find target law rows: "
            + ", ".join(missing[:20])
            + (f" ... {len(missing) - 20} more" if len(missing) > 20 else "")
        )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate strict no-compromise custom law rows. "
            "This is a fail-closed static/Core traceability check only; it does not prove runtime behavior."
        )
    )
    parser.add_argument(
        "--core",
        type=Path,
        default=None,
        help="Optional generated Core.zip to inspect instead of only source override rows.",
    )
    parser.add_argument(
        "--override-dir",
        type=Path,
        default=LAW_OVERRIDE_DIR,
        help="Source override directory to inspect when --core is omitted.",
    )
    args = parser.parse_args()

    try:
        targets_by_sid = load_targets()
    except (OSError, json.JSONDecodeError, ValueError) as ex:
        print(f"strict no-compromise law row validation failed to load targets: {ex}", file=sys.stderr)
        return 1

    failures = validate_core_zip(args.core, targets_by_sid) if args.core else validate_override_source(targets_by_sid, args.override_dir)
    if failures:
        print("strict no-compromise law row validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1

    print("strict no-compromise law row validation passed")
    print("Note: this proves only absence of concrete bonuses on non-final target rows, not runtime behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
