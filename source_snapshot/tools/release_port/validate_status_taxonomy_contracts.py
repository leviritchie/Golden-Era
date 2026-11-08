#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "status_taxonomy_contracts.json"
VANILLA_EFFECT_REFERENCE = ROOT / "docs" / "olden_era_vanilla_effect_text_reference.md"
STATUS_ROW_RE = re.compile(r"^\| `([^`]+)` \| (.+?) \| `([^`]+)` \|$")


def load_status_evidence() -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    if not VANILLA_EFFECT_REFERENCE.exists():
        return evidence
    for line_number, line in enumerate(VANILLA_EFFECT_REFERENCE.read_text(encoding="utf-8-sig").splitlines(), start=1):
        match = STATUS_ROW_RE.match(line)
        if not match:
            continue
        status_sid, description, source = match.groups()
        if not source.endswith("Buff.json") and "magic_buff.json" not in source:
            continue
        evidence[status_sid] = {
            "description": description,
            "source": source,
            "sourceFile": str(VANILLA_EFFECT_REFERENCE.relative_to(ROOT)),
            "sourcePath": f"line {line_number}",
        }
    return evidence


def validate_contracts(doc: Any, evidence: dict[str, dict[str, str]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("status taxonomy contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"status taxonomy contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")

    policy = doc.get("policy")
    if not isinstance(policy, dict) or policy.get("noSidSubstringInference") is not True:
        validation.error("status taxonomy contracts must explicitly forbid SID substring inference")

    allowed_tags_value = doc.get("allowedTags")
    if not isinstance(allowed_tags_value, list) or not allowed_tags_value:
        validation.error("status taxonomy contracts allowedTags must be a non-empty list")
        allowed_tags: set[str] = set()
    else:
        allowed_tags = set()
        for tag in allowed_tags_value:
            if not isinstance(tag, str) or not tag:
                validation.error(f"allowedTags entry must be a non-empty string, got {tag!r}")
                continue
            if tag in allowed_tags:
                validation.error(f"duplicate allowed tag: {tag}")
            allowed_tags.add(tag)

    statuses = doc.get("statuses")
    if not isinstance(statuses, dict) or not statuses:
        validation.error("status taxonomy contracts statuses must be a non-empty object")
        return

    seen_tags: set[str] = set()
    for status_sid, entry in sorted(statuses.items()):
        if not isinstance(entry, dict):
            validation.error(f"{status_sid}: status entry must be an object")
            continue
        row = evidence.get(status_sid)
        if row is None:
            validation.error(f"{status_sid}: no exact vanilla buff/effect text evidence")
        tags = entry.get("tags")
        if not isinstance(tags, list) or not tags:
            validation.error(f"{status_sid}: tags must be a non-empty list")
        else:
            local_tags: set[str] = set()
            for tag in tags:
                if not isinstance(tag, str) or not tag:
                    validation.error(f"{status_sid}: tag must be a non-empty string, got {tag!r}")
                    continue
                if tag not in allowed_tags:
                    validation.error(f"{status_sid}: tag {tag!r} is not in allowedTags")
                if tag in local_tags:
                    validation.error(f"{status_sid}: duplicate tag {tag!r}")
                local_tags.add(tag)
                seen_tags.add(tag)

        evidence_rows = entry.get("evidence")
        if not isinstance(evidence_rows, list) or not evidence_rows:
            validation.error(f"{status_sid}: evidence must be a non-empty list")
        elif row is not None:
            expected_source = row["sourceFile"].replace("\\", "/")
            if not any(isinstance(value, str) and expected_source in value.replace("\\", "/") for value in evidence_rows):
                validation.error(f"{status_sid}: evidence must cite exact source file {expected_source}")

    predicate_groups = doc.get("predicateGroups")
    if not isinstance(predicate_groups, dict) or not predicate_groups:
        validation.error("status taxonomy contracts predicateGroups must be a non-empty object")
        return
    for group_name, group in sorted(predicate_groups.items()):
        if not isinstance(group, dict):
            validation.error(f"{group_name}: predicate group must be an object")
            continue
        status = group.get("status")
        if status not in {"mapped", "partial", "missing"}:
            validation.error(f"{group_name}: status must be mapped, partial, or missing")
        covered = group.get("coveredTags")
        missing = group.get("missingTags")
        if not isinstance(covered, list):
            validation.error(f"{group_name}: coveredTags must be a list")
            covered = []
        if not isinstance(missing, list):
            validation.error(f"{group_name}: missingTags must be a list")
            missing = []
        for tag in covered:
            if tag not in allowed_tags:
                validation.error(f"{group_name}: covered tag {tag!r} is not in allowedTags")
            if tag not in seen_tags:
                validation.error(f"{group_name}: covered tag {tag!r} has no status seed")
        if status == "mapped" and missing:
            validation.error(f"{group_name}: mapped group cannot have missingTags")
        if status == "missing" and covered:
            validation.error(f"{group_name}: missing group cannot have coveredTags")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate source-authored status taxonomy contracts against exact vanilla buff/effect text IDs. "
            "This does not infer tags from SID substrings and does not prove runtime buff behavior."
        )
    )
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    evidence = load_status_evidence()
    validate_contracts(doc, evidence, validation)
    print(f"status taxonomy contracts: {len(doc.get('statuses', {})) if isinstance(doc, dict) else 0} status seeds")
    print(f"vanilla buff/effect evidence: {len(evidence)} exact status entries")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
