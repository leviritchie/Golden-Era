#!/usr/bin/env python3
"""Audit HoMM3 unit authoring battle-frame folders against units_inventory.json."""

from __future__ import annotations

import argparse
import json
import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[2]
HERE = pathlib.Path(__file__).resolve().parent
INVENTORY = HERE / "units_inventory.json"
PRESETS = HERE / "presets"
UNITY_LAB = ROOT / "oldenera_factions" / "Assets" / "CustomUnits" / "homm3_lab"


def load_json(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def expected_battle_folder(unit: dict) -> str | None:
    basename = unit.get("battleExtractBasename")
    if not basename and unit.get("battleDefPath"):
        basename = pathlib.PurePosixPath(unit["battleDefPath"]).stem
    if not basename and unit.get("battleLodEntry"):
        basename = pathlib.PurePosixPath(unit["battleLodEntry"]).stem
    if not basename:
        return None
    return f"{basename}.dir".lower()


def actual_battle_folder(authoring_path: pathlib.Path) -> str | None:
    if not authoring_path.exists():
        return None
    authoring = load_json(authoring_path)
    folder = authoring.get("framesFolder")
    if not folder:
        return None
    return pathlib.PurePosixPath(folder.replace("\\", "/")).name.lower()


def audit_lane(label: str, root: pathlib.Path, inventory_units: list[dict]) -> list[tuple[str, str, str, str]]:
    mismatches: list[tuple[str, str, str, str]] = []
    for unit in inventory_units:
        sid = unit.get("unitSid")
        if not sid or sid == "sample_creature":
            continue
        expected = expected_battle_folder(unit)
        if not expected:
            continue
        path = root / sid / "authoring.json"
        actual = actual_battle_folder(path)
        if actual is None:
            continue
        if actual != expected:
            mismatches.append((label, sid, expected, actual))
    return mismatches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lane",
        choices=("all", "presets", "unity"),
        default="all",
        help="Authoring lane to check.",
    )
    args = parser.parse_args()

    inventory = load_json(INVENTORY)
    units = inventory.get("units", [])
    if not isinstance(units, list):
        raise SystemExit("units_inventory.json has no units array")

    mismatches: list[tuple[str, str, str, str]] = []
    if args.lane in ("all", "presets"):
        mismatches.extend(audit_lane("presets", PRESETS, units))
    if args.lane in ("all", "unity"):
        mismatches.extend(audit_lane("unity", UNITY_LAB, units))

    if mismatches:
        print("battle sprite source mismatches:")
        for label, sid, expected, actual in mismatches:
            print(f"  {label}: {sid}: expected {expected}, found {actual}")
        return 1

    print("battle sprite source audit passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
