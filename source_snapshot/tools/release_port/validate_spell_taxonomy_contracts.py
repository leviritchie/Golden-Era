#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import Validation, load_json  # noqa: E402


DEFAULT_CONTRACTS_PATH = ROOT / "custom_factions" / "spell_taxonomy_contracts.json"
ABILITY_OVERRIDES_DIR = ROOT / "custom_factions" / "ability_overrides"
VANILLA_EFFECT_REFERENCE = ROOT / "docs" / "olden_era_vanilla_effect_text_reference.md"


def load_spell_evidence() -> dict[str, dict[str, str]]:
    evidence: dict[str, dict[str, str]] = {}
    for path in sorted(ABILITY_OVERRIDES_DIR.glob("homm3_*.json")):
        doc = load_json(path)
        unit_overrides = doc.get("unitOverrides") if isinstance(doc, dict) else None
        if not isinstance(unit_overrides, dict):
            continue
        for unit_sid, entry in sorted(unit_overrides.items()):
            if not isinstance(entry, dict):
                continue
            specials = entry.get("existingSpecials")
            if not isinstance(specials, list):
                continue
            for index, special in enumerate(specials):
                if not isinstance(special, dict):
                    continue
                payload = special.get("effectPayload")
                if not isinstance(payload, dict):
                    continue
                spell_sid = payload.get("spellSid")
                school = payload.get("school")
                if isinstance(spell_sid, str) and isinstance(school, str):
                    evidence[spell_sid] = {
                        "school": school,
                        "sourceFile": str(path.relative_to(ROOT)),
                        "sourcePath": f"unitOverrides.{unit_sid}.existingSpecials[{index}].effectPayload",
                    }
    if VANILLA_EFFECT_REFERENCE.exists():
        for line_number, line in enumerate(VANILLA_EFFECT_REFERENCE.read_text(encoding="utf-8-sig").splitlines(), start=1):
            if not line.startswith("### ") or "(`" not in line or "`)" not in line:
                continue
            spell_sid = line.split("(`", 1)[1].split("`)", 1)[0]
            if "_magic_" not in spell_sid and not spell_sid.startswith("neutral_magic_") and not spell_sid.startswith("bonus_magic_"):
                continue
            evidence.setdefault(
                spell_sid,
                {
                    "school": "",
                    "sourceFile": str(VANILLA_EFFECT_REFERENCE.relative_to(ROOT)),
                    "sourcePath": f"line {line_number}",
                },
            )
    return evidence


def validate_contracts(doc: Any, spell_evidence: dict[str, dict[str, str]], validation: Validation) -> None:
    if not isinstance(doc, dict):
        validation.error("spell taxonomy contracts root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        validation.error(f"spell taxonomy contracts schemaVersion must be 1, got {doc.get('schemaVersion')!r}")

    policy = doc.get("policy")
    if not isinstance(policy, dict) or policy.get("noSidSubstringInference") is not True:
        validation.error("spell taxonomy contracts must explicitly forbid SID substring inference")

    allowed_tags_value = doc.get("allowedTags")
    if not isinstance(allowed_tags_value, list) or not allowed_tags_value:
        validation.error("spell taxonomy contracts allowedTags must be a non-empty list")
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

    spells = doc.get("spells")
    if not isinstance(spells, dict) or not spells:
        validation.error("spell taxonomy contracts spells must be a non-empty object")
        return

    seen_tags: set[str] = set()
    for spell_sid, entry in sorted(spells.items()):
        if not isinstance(entry, dict):
            validation.error(f"{spell_sid}: spell entry must be an object")
            continue
        evidence = spell_evidence.get(spell_sid)
        if evidence is None:
            validation.error(f"{spell_sid}: no exact ability_overrides or vanilla spell reference evidence")
        school = entry.get("school")
        if not isinstance(school, str) or not school:
            validation.error(f"{spell_sid}: school must be a non-empty string")
        elif evidence is not None and evidence["school"] and evidence["school"] != school:
            validation.error(
                f"{spell_sid}: contract school {school!r} does not match exact ability_overrides school {evidence['school']!r}"
            )

        tags = entry.get("tags")
        if not isinstance(tags, list) or not tags:
            validation.error(f"{spell_sid}: tags must be a non-empty list")
        else:
            local_tags: set[str] = set()
            for tag in tags:
                if not isinstance(tag, str) or not tag:
                    validation.error(f"{spell_sid}: tag must be a non-empty string, got {tag!r}")
                    continue
                if tag not in allowed_tags:
                    validation.error(f"{spell_sid}: tag {tag!r} is not in allowedTags")
                if tag in local_tags:
                    validation.error(f"{spell_sid}: duplicate tag {tag!r}")
                local_tags.add(tag)
                seen_tags.add(tag)

        evidence_rows = entry.get("evidence")
        if not isinstance(evidence_rows, list) or not evidence_rows:
            validation.error(f"{spell_sid}: evidence must be a non-empty list")
        elif evidence is not None:
            expected_source = evidence["sourceFile"].replace("\\", "/")
            if not any(isinstance(row, str) and expected_source in row.replace("\\", "/") for row in evidence_rows):
                validation.error(f"{spell_sid}: evidence must cite exact source file {expected_source}")

    predicate_groups = doc.get("predicateGroups")
    if not isinstance(predicate_groups, dict) or not predicate_groups:
        validation.error("spell taxonomy contracts predicateGroups must be a non-empty object")
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
                validation.error(f"{group_name}: covered tag {tag!r} has no spell seed")
        if status == "mapped" and missing:
            validation.error(f"{group_name}: mapped group cannot have missingTags")
        if status == "missing" and covered:
            validation.error(f"{group_name}: missing group cannot have coveredTags")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate source-authored spell taxonomy contracts against exact ability_overrides spellSid evidence. "
            "This does not infer tags from spell SID substrings and does not prove runtime spell behavior."
        )
    )
    parser.add_argument("--contracts", type=Path, default=DEFAULT_CONTRACTS_PATH)
    args = parser.parse_args()

    validation = Validation()
    doc = load_json(args.contracts)
    spell_evidence = load_spell_evidence()
    validate_contracts(doc, spell_evidence, validation)
    print(f"spell taxonomy contracts: {len(doc.get('spells', {})) if isinstance(doc, dict) else 0} spell seeds")
    print(f"ability override spell evidence: {len(spell_evidence)} exact spell entries")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
