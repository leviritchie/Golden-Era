#!/usr/bin/env python3
"""Validate custom hero start-skill count and source/Core fidelity."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_DIR = ROOT / "custom_factions"
DEFAULT_HERO_OVERRIDE_DIR = DEFAULT_MANIFEST_DIR / "hero_overrides"
DEFAULT_CORE = ROOT / "artifacts" / "core_overlay_work" / "Core.zip"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def manifest_core_overlay_enabled(manifest: dict[str, Any]) -> bool:
    validation = manifest.get("validation") or {}
    value = validation.get("coreOverlayEnabled")
    if isinstance(value, bool):
        return value
    return True


def first_array_item(doc: Any) -> dict[str, Any] | None:
    rows = doc.get("array") if isinstance(doc, dict) else None
    if isinstance(rows, list) and rows and isinstance(rows[0], dict):
        return rows[0]
    return None


def read_core_json(core: Path, member: str) -> Any | None:
    try:
        if core.is_dir():
            return load_json(core / member)
        with zipfile.ZipFile(core, "r") as zf:
            return json.loads(zf.read(member).decode("utf-8-sig"))
    except (FileNotFoundError, KeyError, json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile):
        return None


def clean_start_skills(value: Any, context: str, errors: list[str]) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        errors.append(f"{context}: startSkills must be a list")
        return None
    clean: list[dict[str, Any]] = []
    for index, row in enumerate(value, start=1):
        if not isinstance(row, dict) or not isinstance(row.get("sid"), str):
            errors.append(f"{context}: startSkills[{index}] must have a string sid")
            continue
        skill_level = row.get("skillLevel")
        if not isinstance(skill_level, int):
            errors.append(f"{context}: startSkills[{index}] must have integer skillLevel")
            continue
        clean.append({"sid": row["sid"], "skillLevel": skill_level})
    return clean


def load_manifests(manifest_dir: Path) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for path in sorted(manifest_dir.glob("homm3_*.json")):
        manifest = load_json(path)
        if isinstance(manifest, dict) and manifest_core_overlay_enabled(manifest):
            manifests.append(manifest)
    return manifests


def hero_override_signatures(
    manifest: dict[str, Any],
    hero_override_dir: Path,
    errors: list[str],
) -> dict[str, list[dict[str, Any]]]:
    faction_sid = manifest["identity"]["factionSid"]
    path = hero_override_dir / f"{faction_sid}.json"
    if not path.is_file():
        return {}
    doc = load_json(path)
    overrides = doc.get("heroOverrides") if isinstance(doc, dict) else None
    if not isinstance(overrides, dict):
        return {}
    signatures: dict[str, list[dict[str, Any]]] = {}
    for hero_sid, entry in overrides.items():
        if not isinstance(hero_sid, str) or not isinstance(entry, dict) or entry.get("enabled") is False:
            continue
        if "startSkills" not in entry:
            continue
        context = f"{faction_sid}:{hero_sid}: hero_overrides"
        clean = clean_start_skills(entry.get("startSkills"), context, errors)
        if clean is None:
            continue
        faction_rows = [row["sid"] for row in clean if row["sid"].startswith("skill_faction_")]
        if faction_rows:
            errors.append(f"{context}: source startSkills must omit derived faction skill(s) {faction_rows!r}")
        non_faction = [row for row in clean if not row["sid"].startswith("skill_faction_")]
        if len(non_faction) > 1:
            errors.append(
                f"{context}: source startSkills must contain at most one HoMM3 skill because Core prepends the unique faction skill"
            )
        # Ban the known-broken HoMM3 secondary that was never emitted into skills.json.
        for row in non_faction:
            if row["skillLevel"] != 1:
                errors.append(
                    f"{context}: non-faction startSkill {row['sid']!r} must be Basic (skillLevel 1); "
                    f"Advanced/Expert grants a free subskill and reads as a third starting skill, got skillLevel={row['skillLevel']}"
                )
            if row["sid"] == "skill_necromancy":
                errors.append(
                    f"{context}: startSkill 'skill_necromancy' is not a Core SkillConfig; remount to an existing skill "
                    f"(e.g. skill_sorcery / skill_assault). Unresolved configs abort hero create and SpawnsCreator."
                )
        signatures[hero_sid] = non_faction
    return signatures


def load_core_skill_ids(core: Path) -> set[str] | None:
    doc = read_core_json(core, "DB/heroes_skills/skills/skills.json")
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return None
    return {row["id"] for row in rows if isinstance(row, dict) and isinstance(row.get("id"), str)}


def validate_core(
    core: Path,
    manifests: list[dict[str, Any]],
    signatures_by_faction: dict[str, dict[str, list[dict[str, Any]]]],
    errors: list[str],
) -> None:
    skill_ids = load_core_skill_ids(core)
    if skill_ids is None:
        errors.append(f"{core}: missing or malformed DB/heroes_skills/skills/skills.json")
        return
    for manifest in manifests:
        faction_sid = manifest["identity"]["factionSid"]
        heroes = manifest.get("heroes") or {}
        hero_prefix = heroes.get("heroPrefix")
        hero_count = heroes.get("count")
        faction_skill_sid = (manifest.get("skillsAndLaws") or {}).get("factionSkillSid")
        if not isinstance(hero_prefix, str) or not isinstance(hero_count, int) or not isinstance(faction_skill_sid, str):
            continue
        for index in range(1, hero_count + 1):
            hero_sid = f"{hero_prefix}{index}"
            member = f"DB/heroes/{faction_sid}/{hero_sid}.json"
            item = first_array_item(read_core_json(core, member))
            context = f"{faction_sid}:{hero_sid}: {member}"
            if not isinstance(item, dict):
                errors.append(f"{context}: missing generated Core hero row")
                continue
            actual = clean_start_skills(item.get("startSkills"), context, errors)
            if actual is None:
                continue
            for row in actual:
                if row["sid"] not in skill_ids:
                    errors.append(
                        f"{context}: startSkill {row['sid']!r} is missing from DB/heroes_skills/skills/skills.json "
                        f"(unresolved skill configs abort DataHeroes create and cascade into SpawnsCreator NREs)"
                    )
            faction_rows = [row for row in actual if row["sid"].startswith("skill_faction_")]
            if len(faction_rows) != 1 or faction_rows[0]["sid"] != faction_skill_sid or faction_rows[0]["skillLevel"] != 1:
                errors.append(f"{context}: generated Core must contain exactly one level-1 faction skill {faction_skill_sid!r}")
            if actual and actual[0]["sid"] != faction_skill_sid:
                errors.append(f"{context}: generated Core startSkills[1] must be the unique faction skill {faction_skill_sid!r}")
            non_faction = [row for row in actual if not row["sid"].startswith("skill_faction_")]
            if len(non_faction) > 1:
                errors.append(f"{context}: generated Core must have at most one HoMM3 source skill, got {non_faction!r}")
            for row in non_faction:
                if row["skillLevel"] != 1:
                    errors.append(
                        f"{context}: generated Core non-faction startSkill {row['sid']!r} must be Basic "
                        f"(skillLevel 1), got skillLevel={row['skillLevel']}"
                    )
            if len(actual) > 2:
                errors.append(f"{context}: generated Core startSkills must be faction + at most one secondary, got {actual!r}")
            expected = signatures_by_faction.get(faction_sid, {}).get(hero_sid)
            if expected is not None and non_faction != expected:
                errors.append(f"{context}: generated Core HoMM3 start skill must match hero_overrides; expected {expected!r}, got {non_faction!r}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--hero-override-dir", type=Path, default=DEFAULT_HERO_OVERRIDE_DIR)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    args = parser.parse_args(argv)

    errors: list[str] = []
    manifests = load_manifests(args.manifest_dir)
    signatures = {
        manifest["identity"]["factionSid"]: hero_override_signatures(manifest, args.hero_override_dir, errors)
        for manifest in manifests
    }
    if args.core:
        validate_core(args.core, manifests, signatures, errors)

    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"custom hero start skill contract failed: {len(errors)} error(s)")
        return 1
    print(f"custom hero start skill contract passed: {len(manifests)} manifest(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))