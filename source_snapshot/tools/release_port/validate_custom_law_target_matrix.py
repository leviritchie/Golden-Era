#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, core_overlay_enabled, load_json  # noqa: E402


DEFAULT_TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def load_enabled_factions(manifest_dir: Path, v: Validation) -> set[str]:
    factions: set[str] = set()
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
        factions.add(faction_sid)
    return factions


def target_faction_key_from_sid(faction_sid: str) -> str:
    prefix = "homm3_"
    if not faction_sid.startswith(prefix) or len(faction_sid) <= len(prefix):
        raise ValueError(f"enabled custom faction SID is not a HoMM3 SID: {faction_sid!r}")
    return faction_sid[len(prefix):]


def target_family_indices(targets_doc: Any, v: Validation) -> set[int]:
    if not isinstance(targets_doc, dict):
        v.error("custom law targets root must be an object")
        return set()
    families = targets_doc.get("families")
    if not isinstance(families, dict):
        v.error("custom law targets families must be an object")
        return set()
    indices: set[int] = set()
    for key in families:
        try:
            indices.add(int(key))
        except ValueError:
            v.error(f"target family key {key!r} is not an integer")
    return indices


def validate_target_matrix(targets_doc: Any, factions: set[str], family_indices: set[int], v: Validation) -> None:
    if not isinstance(targets_doc, dict):
        return
    targets = targets_doc.get("targets")
    if not isinstance(targets, list):
        v.error("custom law targets must contain a targets list")
        return

    target_factions: set[str] = set()
    for faction_sid in sorted(factions):
        try:
            target_factions.add(target_faction_key_from_sid(faction_sid))
        except ValueError as ex:
            v.error(str(ex))
    seen: dict[tuple[str, int], str] = {}
    for target in targets:
        if not isinstance(target, dict):
            v.error("target entry must be an object")
            continue
        faction = target.get("faction")
        law_index = target.get("lawIndex")
        law_sid = target.get("lawSid")
        if not isinstance(faction, str) or not faction:
            v.error(f"target has invalid faction: {target!r}")
            continue
        if not isinstance(law_index, int):
            v.error(f"{law_sid}: target has invalid lawIndex {law_index!r}")
            continue
        if faction not in target_factions:
            v.error(f"{law_sid}: target faction {faction!r} is not an enabled custom faction key")
        if law_index not in family_indices:
            v.error(f"{law_sid}: target lawIndex {law_index} is not in target families")
        expected_law_sid = f"fraction_law_homm3_{faction}_{law_index}"
        if law_sid != expected_law_sid:
            v.error(f"{law_sid}: target lawSid must be {expected_law_sid!r} for faction key/index")
        key = (faction, law_index)
        if key in seen:
            v.error(f"{law_sid}: duplicate target for faction/index already provided by {seen[key]}")
        seen[key] = str(law_sid)

    for faction in sorted(target_factions):
        for index in sorted(family_indices):
            if (faction, index) not in seen:
                v.error(f"missing target entry for faction={faction!r} lawIndex={index}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate full faction/family matrix coverage in custom_law_targets.json.")
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    args = parser.parse_args()

    v = Validation()
    if not args.targets.exists():
        v.error(f"missing targets file: {args.targets}")
    if not args.manifest_dir.exists():
        v.error(f"missing manifest dir: {args.manifest_dir}")
    if not v.errors:
        targets_doc = json.loads(args.targets.read_text(encoding="utf-8-sig"))
        factions = load_enabled_factions(args.manifest_dir, v)
        families = target_family_indices(targets_doc, v)
        validate_target_matrix(targets_doc, factions, families, v)
        print(f"enabled factions: {sorted(factions)}")
        print(f"target faction keys: {sorted(target_faction_key_from_sid(faction) for faction in factions if faction.startswith('homm3_'))}")
        print(f"target family indices: {sorted(families)}")
    print(f"errors: {v.errors}")
    if v.warnings:
        print(f"warnings: {v.warnings}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
