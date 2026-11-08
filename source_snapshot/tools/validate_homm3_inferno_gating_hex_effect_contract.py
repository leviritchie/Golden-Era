#!/usr/bin/env python3
"""Validate the HoMM3 Inferno Gating legal-hex VFX contract."""

from __future__ import annotations

import argparse
import importlib.util
import json
import pathlib
import sys
import zipfile
from typing import Any

ABILITY_MEMBER = "DB/heroes_abilities/heroes_abilities_base/hero_abilities.json"


def fail(message: str) -> None:
    print(f"homm3-inferno-gating-hex-effect-contract: {message}", file=sys.stderr)
    raise SystemExit(1)


def import_overlay(repo_root: pathlib.Path) -> Any:
    overlay_dir = repo_root / "tools" / "release_port"
    overlay_path = overlay_dir / "apply_release_core_overlay.py"
    if str(overlay_dir) not in sys.path:
        sys.path.insert(0, str(overlay_dir))
    spec = importlib.util.spec_from_file_location("homm3_inferno_gating_hex_effect_overlay", overlay_path)
    if spec is None or spec.loader is None:
        fail(f"cannot import {overlay_path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as ex:  # noqa: BLE001 - validators should fail closed with source context.
        fail(f"cannot import overlay module: {ex}")
    return module


def read_json(core_zip: zipfile.ZipFile, overlay: dict[str, bytes], member: str) -> Any:
    try:
        raw = overlay[member] if member in overlay else core_zip.read(member)
    except KeyError:
        fail(f"candidate Core output is missing {member}")
    return json.loads(raw.decode("utf-8-sig"))


def array_rows(doc: Any, member: str) -> list[Any]:
    rows = doc.get("array") if isinstance(doc, dict) else None
    if isinstance(rows, list):
        return rows
    fail(f"{member}: missing array rows")


def row_by_id(rows: list[Any], row_id: str, member: str) -> dict[str, Any]:
    for row in rows:
        if isinstance(row, dict) and row.get("id") == row_id:
            return row
    fail(f"{member}: missing row id {row_id}")


def only_level(row: dict[str, Any], row_id: str) -> dict[str, Any]:
    levels = row.get("levels")
    if not isinstance(levels, list) or len(levels) != 1 or not isinstance(levels[0], dict):
        fail(f"{row_id}: expected exactly one hero ability level")
    return levels[0]


def validate_gating_level(row_id: str, level: dict[str, Any], unit_sid: str, expected_hex_effect: str, issues: list[str]) -> None:
    if level.get("effect") != expected_hex_effect:
        issues.append(f"{row_id}: effect={level.get('effect')!r}, expected {expected_hex_effect!r}")
    if level.get("hexEffect") != expected_hex_effect:
        issues.append(f"{row_id}: hexEffect={level.get('hexEffect')!r}, expected {expected_hex_effect!r}")
    damage_dealer = level.get("damageDealer")
    if not isinstance(damage_dealer, dict):
        issues.append(f"{row_id}: missing damageDealer")
        return
    for key in ("castTargetParams", "affectTargetParams"):
        params = damage_dealer.get(key)
        expected = {
            "castTarget_": "ally",
            "selection": "hex",
            "areaType": "near_units",
            "distance": 2,
        }
        if params != expected:
            issues.append(f"{row_id}: {key}={params!r}, expected {expected!r}")
    mechanics = damage_dealer.get("targetMechanics")
    if not isinstance(mechanics, list) or len(mechanics) != 1 or not isinstance(mechanics[0], dict):
        issues.append(f"{row_id}: expected exactly one target mechanic")
        return
    mechanic = mechanics[0]
    values = mechanic.get("values")
    if mechanic.get("mech") != "spawn_object":
        issues.append(f"{row_id}: mech={mechanic.get('mech')!r}, expected 'spawn_object'")
    if not isinstance(values, list) or len(values) < 2 or values[0] != "unit" or values[1] != unit_sid:
        issues.append(f"{row_id}: spawn_object values={values!r}, expected unit {unit_sid!r}")


def validate_rows(rows: list[Any], expected_rows: dict[str, str], expected_hex_effect: str, issues: list[str]) -> None:
    for row_id, unit_sid in expected_rows.items():
        row = row_by_id(rows, row_id, ABILITY_MEMBER)
        validate_gating_level(row_id, only_level(row, row_id), unit_sid, expected_hex_effect, issues)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=pathlib.Path, required=True)
    parser.add_argument("--core", type=pathlib.Path, required=True)
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    core_path = args.core.resolve()
    if not core_path.is_file():
        fail(f"missing source Core.zip: {core_path}")

    module = import_overlay(repo_root)
    expected_rows = {
        module.HOMM3_INFERNO_GATING_IMP_ABILITY_SID: "h3_imp",
        module.HOMM3_INFERNO_GATING_GOG_ABILITY_SID: "h3_gog",
        module.HOMM3_INFERNO_GATING_HELL_HOUND_ABILITY_SID: "h3_hell_hound",
    }
    expected_hex_effect = module.HOMM3_INFERNO_GATING_SUMMON_VFX
    issues: list[str] = []

    generated_rows = module.make_homm3_inferno_gating_hero_abilities()
    validate_rows(generated_rows, expected_rows, expected_hex_effect, issues)

    try:
        overlay, _notes = module.build_overlay(core_path)
    except Exception as ex:  # noqa: BLE001
        fail(f"cannot build candidate Core overlay in memory: {ex}")
    with zipfile.ZipFile(core_path) as core_zip:
        ability_doc = read_json(core_zip, overlay, ABILITY_MEMBER)
        validate_rows(array_rows(ability_doc, ABILITY_MEMBER), expected_rows, expected_hex_effect, issues)

    if issues:
        for issue in issues:
            print(issue, file=sys.stderr)
        fail(f"Inferno Gating hex-effect contract has {len(issues)} issue(s)")
    print(
        "homm3-inferno-gating-hex-effect-contract: "
        f"validated {len(expected_rows)} Gating hero abilities with dedicated hexEffect, range-2 ally hex targeting, "
        "and spawn_object unit mechanics"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())