#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
DEFAULT_RUNTIME_PATH = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Homm3CustomFactionLawRuntime.cs"

INDEX_CONST_RE = re.compile(r"internal\s+const\s+int\s+([A-Za-z0-9_]+Index)\s*=\s*([0-9]+)\s*;")
KNOWN_ARRAY_RE = re.compile(r"internal\s+static\s+readonly\s+int\[\]\s+KnownRuntimeLawIndices\s*=\s*\{(?P<body>.*?)\};", re.DOTALL)
IDENT_RE = re.compile(r"\b([A-Za-z0-9_]+Index)\b")


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


def runtime_indices(source: str, v: Validation) -> tuple[dict[str, int], dict[int, list[str]], set[int]]:
    constants: dict[str, int] = {}
    by_value: dict[int, list[str]] = {}
    for name, value_text in INDEX_CONST_RE.findall(source):
        value = int(value_text)
        constants[name] = value
        by_value.setdefault(value, []).append(name)

    match = KNOWN_ARRAY_RE.search(source)
    if not match:
        v.error("KnownRuntimeLawIndices array not found in Homm3CustomFactionLawRuntime.cs")
        return constants, by_value, set()

    known: set[int] = set()
    for ident in IDENT_RE.findall(match.group("body")):
        if ident not in constants:
            v.error(f"KnownRuntimeLawIndices references unknown constant {ident!r}")
            continue
        known.add(constants[ident])
    return constants, by_value, known


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
            index = int(key)
        except ValueError:
            v.error(f"target family key {key!r} is not an integer")
            continue
        indices.add(index)
    return indices


def validate_coverage(runtime_path: Path, targets_path: Path, v: Validation) -> None:
    source = runtime_path.read_text(encoding="utf-8-sig")
    _constants, by_value, known_runtime = runtime_indices(source, v)
    target_indices = target_family_indices(load_json(targets_path), v)

    for index in sorted(known_runtime - target_indices):
        names = ", ".join(by_value.get(index, [])) or "unknown constant"
        v.error(f"runtime law index {index} ({names}) is in KnownRuntimeLawIndices but missing from custom_law_targets.json families")

    for index in sorted(target_indices - known_runtime):
        v.error(f"target family index {index} is not present in Homm3CustomFactionLawRuntime.KnownRuntimeLawIndices")

    for index, names in sorted(by_value.items()):
        if len(names) > 1 and index in known_runtime:
            v.warn(f"runtime law index {index} has multiple constants: {', '.join(names)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate custom law target family indices against runtime law constants.")
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS_PATH)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME_PATH)
    args = parser.parse_args()

    v = Validation()
    if not args.targets.exists():
        v.error(f"missing targets file: {args.targets}")
    if not args.runtime.exists():
        v.error(f"missing runtime law source: {args.runtime}")
    if not v.errors:
        validate_coverage(args.runtime, args.targets, v)

    print(f"errors: {v.errors}")
    if v.warnings:
        print(f"warnings: {v.warnings}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
