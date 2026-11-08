#!/usr/bin/env python3
"""Validate HoMM3 custom hero level-up skill tables.

Custom heroes start with their HoMM3 faction skill. Their level-up roll tables
must therefore upgrade that exact custom skill and must not offer donor/native
unique faction skills such as Human Righteousness.
"""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_DIR = REPO_ROOT / "custom_factions"
DEFAULT_CORE = REPO_ROOT / "artifacts" / "core_overlay_work" / "Core.zip"
CUSTOM_FACTIONS = (
    "homm3_castle",
    "homm3_conflux",
    "homm3_cove",
    "homm3_dungeon",
    "homm3_fortress",
    "homm3_inferno",
    "homm3_necropolis",
    "homm3_rampart",
    "homm3_stronghold",
    "homm3_tower",
)


class CoreReader:
    def __init__(self, core: Path) -> None:
        self.core = core
        self._zip: zipfile.ZipFile | None = None
        if core.is_file():
            self._zip = zipfile.ZipFile(core, "r")
            self.names = {name.replace("\\", "/") for name in self._zip.namelist()}
        elif core.is_dir():
            self.names = {
                path.relative_to(core).as_posix()
                for path in core.rglob("*")
                if path.is_file()
            }
        else:
            raise FileNotFoundError(f"Core path does not exist: {core}")

    def close(self) -> None:
        if self._zip is not None:
            self._zip.close()

    def read_json(self, member: str) -> dict[str, Any]:
        member = member.replace("\\", "/")
        if member not in self.names:
            raise KeyError(member)
        if self._zip is not None:
            data = self._zip.read(member)
        else:
            data = (self.core / member).read_bytes()
        return json.loads(data.decode("utf-8-sig"))


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)


def load_manifests(manifest_dir: Path) -> list[dict[str, Any]]:
    manifests: list[dict[str, Any]] = []
    for faction_sid in CUSTOM_FACTIONS:
        path = manifest_dir / f"{faction_sid}.json"
        with path.open("r", encoding="utf-8-sig") as handle:
            manifest = json.load(handle)
        identity = manifest.get("identity") if isinstance(manifest, dict) else None
        skills = manifest.get("skillsAndLaws") if isinstance(manifest, dict) else None
        if not isinstance(identity, dict) or not isinstance(skills, dict):
            raise RuntimeError(f"{path}: missing identity or skillsAndLaws")
        manifests.append(manifest)
    return manifests


def array_rows(doc: Any) -> list[Any]:
    rows = doc.get("array") if isinstance(doc, dict) else None
    return rows if isinstance(rows, list) else []


def roll_chance_sids(table_doc: dict[str, Any]) -> list[str]:
    sids: list[str] = []
    for row in array_rows(table_doc):
        if not isinstance(row, dict):
            continue
        for list_key in ("defaultList", "specialList"):
            buckets = row.get(list_key)
            if not isinstance(buckets, list):
                continue
            for bucket in buckets:
                if not isinstance(bucket, dict):
                    continue
                chances = bucket.get("rollChances")
                if not isinstance(chances, list):
                    continue
                for chance in chances:
                    sid = chance.get("sid") if isinstance(chance, dict) else None
                    if isinstance(sid, str):
                        sids.append(sid)
    return sids


def expected_table_sid(faction_sid: str, class_type: str, arena: bool = False) -> str:
    prefix = "arenaGame_" if arena else ""
    return f"{prefix}{faction_sid}_{class_type}_skills_table"


def validate_skill_tables(core: CoreReader, manifest: dict[str, Any], v: Validation) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    expected_skill = manifest["skillsAndLaws"].get("factionSkillSid")
    if expected_skill != f"skill_faction_{faction_sid}":
        v.error(f"{faction_sid}: manifest faction skill must be skill_faction_{faction_sid}, got {expected_skill!r}")
        return

    for class_type in ("might", "magic"):
        for arena in (False, True):
            table_sid = expected_table_sid(faction_sid, class_type, arena=arena)
            member = f"DB/heroes_skills/skills_by_level_tables/{table_sid}.json"
            if arena and member not in core.names:
                continue
            try:
                table_doc = core.read_json(member)
            except Exception as ex:
                v.error(f"{faction_sid}: missing custom hero {class_type} level-up table {member}: {ex}")
                continue
            table_sids = roll_chance_sids(table_doc)
            faction_sids = sorted({sid for sid in table_sids if sid.startswith("skill_faction_")})
            bad_sids = [sid for sid in faction_sids if sid != expected_skill]
            if bad_sids:
                v.error(f"{faction_sid}: {table_sid} must not offer native/donor faction skills {bad_sids!r}")
            if not arena and expected_skill not in faction_sids:
                v.error(f"{faction_sid}: {table_sid} must offer only the custom faction skill {expected_skill!r}")


def resolve_hero_row(doc: dict[str, Any], hero_sid: str) -> dict[str, Any] | None:
    rows = array_rows(doc)
    if len(rows) == 1 and isinstance(rows[0], dict):
        return rows[0]
    for row in rows:
        if isinstance(row, dict) and row.get("id") == hero_sid:
            return row
    return None


def validate_custom_heroes(core: CoreReader, manifest: dict[str, Any], v: Validation) -> None:
    faction_sid = manifest["identity"]["factionSid"]
    expected_skill = manifest["skillsAndLaws"]["factionSkillSid"]
    heroes = manifest.get("heroes") if isinstance(manifest.get("heroes"), dict) else {}
    hero_prefix = heroes.get("heroPrefix")
    hero_count = heroes.get("count")
    if not isinstance(hero_prefix, str) or not isinstance(hero_count, int):
        v.error(f"{faction_sid}: manifest heroes.heroPrefix/count must be explicit")
        return
    for index in range(1, hero_count + 1):
        hero_sid = f"{hero_prefix}{index}"
        member = f"DB/heroes/{faction_sid}/{hero_sid}.json"
        try:
            hero_doc = core.read_json(member)
        except Exception as ex:
            v.error(f"{faction_sid}: missing custom hero row {member}: {ex}")
            continue
        hero = resolve_hero_row(hero_doc, hero_sid)
        if not isinstance(hero, dict):
            v.error(f"{faction_sid}: cannot resolve custom hero row {hero_sid} in {member}")
            continue
        class_type = hero.get("classType")
        if class_type not in {"might", "magic"}:
            v.error(f"{faction_sid}:{hero_sid}: classType must be might or magic, got {class_type!r}")
            continue
        expected_roll_variant = expected_table_sid(faction_sid, str(class_type))
        if hero.get("skillsRollVariant") != expected_roll_variant:
            v.error(
                f"{faction_sid}:{hero_sid}: skillsRollVariant must be {expected_roll_variant!r}, "
                f"got {hero.get('skillsRollVariant')!r}"
            )
        start_skills = hero.get("startSkills")
        faction_starts: list[str] = []
        if isinstance(start_skills, list):
            for row in start_skills:
                sid = row.get("sid") if isinstance(row, dict) else None
                if isinstance(sid, str) and sid.startswith("skill_faction_"):
                    faction_starts.append(sid)
        if faction_starts != [expected_skill]:
            v.error(f"{faction_sid}:{hero_sid}: startSkills must contain exactly {expected_skill!r}, got {faction_starts!r}")


def validate(core_path: Path, manifest_dir: Path) -> list[str]:
    v = Validation()
    core = CoreReader(core_path)
    try:
        for manifest in load_manifests(manifest_dir):
            validate_skill_tables(core, manifest, v)
            validate_custom_heroes(core, manifest, v)
    finally:
        core.close()
    return v.errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    args = parser.parse_args()

    errors = validate(args.core, args.manifest_dir)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("HoMM3 custom hero level-up skill contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())