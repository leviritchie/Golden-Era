#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
DEFAULT_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"

ALLOWED_STATUSES = {
    "native-exact",
    "needs-runtime",
    "temporary-compromise",
    "blocked",
}
ALLOWED_PACKETS = {
    "vision",
    "committed-damage",
    "counterattack",
    "battle-action",
    "reward-result",
    "morale",
    "spell-cooldown",
    "construction",
}
RESOURCE_RICHES_NAME_RE = re.compile(r"resource\s+riches", re.IGNORECASE)


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def law_sid_for(faction: str, index: int) -> str:
    return f"fraction_law_homm3_{faction}_{index}"


def validate_family(key: str, value: Any, v: Validation) -> None:
    if not isinstance(value, dict):
        v.error(f"families.{key}: must be an object")
        return
    try:
        index = int(key)
    except ValueError:
        v.error(f"families key {key!r}: must be an integer law index string")
        return
    if index <= 0:
        v.error(f"families.{key}: index must be positive")
    packet = value.get("packet")
    if packet not in ALLOWED_PACKETS:
        v.error(f"families.{key}.packet: unsupported packet {packet!r}")
    for required in ("key", "label"):
        if not isinstance(value.get(required), str) or not value.get(required):
            v.error(f"families.{key}.{required}: required non-empty string")


def validate_target(target: Any, families: dict[str, Any], seen: set[tuple[str, int]], v: Validation) -> None:
    if not isinstance(target, dict):
        v.error("target entry must be an object")
        return

    faction = target.get("faction")
    law_index = target.get("lawIndex")
    law_sid = target.get("lawSid")
    name = target.get("name")
    target_mechanic = target.get("targetMechanic")
    status = target.get("implementationStatus")

    if not isinstance(faction, str) or not faction:
        v.error(f"target {target!r}: faction must be a non-empty string")
        return
    if not isinstance(law_index, int):
        v.error(f"{faction}: lawIndex must be an integer")
        return
    if str(law_index) not in families:
        v.error(f"{faction} law {law_index}: no family definition exists")
    expected_sid = law_sid_for(faction, law_index)
    if law_sid != expected_sid:
        v.error(f"{faction} law {law_index}: lawSid must be {expected_sid!r}, got {law_sid!r}")
    if not isinstance(name, str) or not name:
        v.error(f"{expected_sid}: name must be a non-empty string")
    elif RESOURCE_RICHES_NAME_RE.search(name):
        v.error(f"{expected_sid}: Resource Riches is universal and must not be in custom_law_targets.json")
    if not isinstance(target_mechanic, str) or not target_mechanic:
        v.error(f"{expected_sid}: targetMechanic must be a non-empty string")
    if status not in ALLOWED_STATUSES:
        v.error(f"{expected_sid}: unsupported implementationStatus {status!r}")
    if (faction, law_index) in seen:
        v.error(f"{expected_sid}: duplicate faction/lawIndex target")
    seen.add((faction, law_index))


def load_override_law_sids(override_dir: Path) -> set[str]:
    law_sids: set[str] = set()
    for path in sorted(override_dir.glob("homm3_*.json")):
        doc = load_json(path)
        if not isinstance(doc, dict):
            continue
        overrides = doc.get("lawOverrides")
        if not isinstance(overrides, dict):
            continue
        for sid in overrides:
            if isinstance(sid, str):
                law_sids.add(sid)
    return law_sids


def validate_targets(doc: Any, override_law_sids: set[str], v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("custom law targets root must be an object")
        return
    if doc.get("schemaVersion") != 1:
        v.error(f"schemaVersion must be 1, got {doc.get('schemaVersion')!r}")

    families = doc.get("families")
    if not isinstance(families, dict):
        v.error("families must be an object keyed by law index")
        families = {}
    for key, value in sorted(families.items()):
        validate_family(str(key), value, v)

    targets = doc.get("targets")
    if not isinstance(targets, list):
        v.error("targets must be a list")
        return

    seen: set[tuple[str, int]] = set()
    for target in targets:
        validate_target(target, families, seen, v)
        if isinstance(target, dict) and target.get("lawSid") not in override_law_sids:
            v.error(f"{target.get('lawSid')}: not present in law_overrides; every target law must have an explicit source row")


def summarize(doc: Any) -> dict[str, int]:
    counts = {status: 0 for status in sorted(ALLOWED_STATUSES)}
    if isinstance(doc, dict):
        for target in doc.get("targets", []):
            if isinstance(target, dict) and target.get("implementationStatus") in counts:
                counts[str(target["implementationStatus"])] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate no-compromise custom law target spec.")
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--override-dir", type=Path, default=DEFAULT_OVERRIDE_DIR)
    args = parser.parse_args()

    v = Validation()
    if not args.targets.exists():
        v.error(f"missing targets file: {args.targets}")
        print(f"errors: {v.errors}")
        return 1

    doc = load_json(args.targets)
    override_law_sids = load_override_law_sids(args.override_dir) if args.override_dir.exists() else set()
    validate_targets(doc, override_law_sids, v)

    counts = summarize(doc)
    print(f"custom law targets: {sum(counts.values())} entries")
    print("implementation statuses: " + ", ".join(f"{key}={value}" for key, value in sorted(counts.items())))
    print(f"errors: {v.errors}")
    if v.warnings:
        print(f"warnings: {v.warnings}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
