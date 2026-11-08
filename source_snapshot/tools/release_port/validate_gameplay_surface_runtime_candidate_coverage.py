#!/usr/bin/env python3
"""Validate generated/runtime candidate coverage report consistency."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT = ROOT / "custom_factions" / "gameplay_surface_runtime_candidate_coverage.json"
DEFAULT_MATRIX = ROOT / "custom_factions" / "gameplay_surface_evidence_matrix.json"
DEFAULT_DOSSIER_INDEX = ROOT / "custom_factions" / "gameplay_surface_weak_dossier_index.json"
DEFAULT_TARGETS = ROOT / "custom_factions" / "custom_law_targets.json"
DEFAULT_PLUGIN = ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod" / "Plugin.cs"
FORBIDDEN_NATIVE_ONLY_RUNTIME_REGISTRATIONS = (
    "Homm3TrainingDamageLawRuntime.TryRegister(",
    "Homm3CounterattackDoctrineMutationRuntime.TryRegister(",
    "Homm3BattleActionLawRuntime.TryRegister(",
    "Homm3SquadValueEconomyLawRuntime.TryRegister(",
    "Homm3MoraleTriggerLawRuntime.TryRegister(",
    "Homm3RampartAvengerMarkerRuntime.TryRegister(",
    "Homm3RampartAvengerCastMarkerRuntime.TryRegister(",
    "Homm3BattleStartMoraleLawRuntime.TryRegister(",
    "Homm3BattleStartStatusLawRuntime.TryRegister(",
    "Homm3ConfluxElementalConjunctionRuntime.TryRegister(",
    "Homm3CustomSpellCooldownLawRuntime.TryRegister(",
)
ALLOWED_LEVELS = {
    "runtime-candidate",
    "live-metadata-proven",
    "method-dossier-only",
    "declaration-only",
    "no-generated-or-dossier-candidate",
}
IMPLEMENTATION_STATUSES = {"candidate", "partial", "missing", "runtime-unproven", "proven-live-metadata"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)



def has_runtime_law_targets(targets_doc: dict[str, Any]) -> bool:
    rows = targets_doc.get("targets")
    if not isinstance(rows, list):
        return True
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("implementationStatus") in {"needs-runtime", "temporary-compromise", "blocked"}:
            return True
    return False

def validate_no_runtime_mutator_registrations(plugin_path: Path) -> list[str]:
    try:
        source = plugin_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        return [f"failed to read startup source {plugin_path}: {exc}"]
    errors: list[str] = []
    for needle in FORBIDDEN_NATIVE_ONLY_RUNTIME_REGISTRATIONS:
        if needle in source:
            errors.append(
                "native-data-only law targets cannot register speculative runtime mutator "
                + needle.removesuffix("(")
            )
    return errors


def implementation_surface_ids(matrix: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for surface_id, surface in matrix.get("surfaces", {}).items():
        if not isinstance(surface, dict):
            continue
        if not surface.get("packets") or surface.get("status") == "rejected":
            continue
        if surface.get("status") in IMPLEMENTATION_STATUSES or surface.get("runtimeSymbolCandidates"):
            result.add(surface_id)
    return result


def weak_index_ids(index: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for row in index.get("surfaces", []):
        if isinstance(row, dict) and isinstance(row.get("surfaceId"), str):
            result.add(row["surfaceId"])
    return result


def validate(report: dict[str, Any], matrix: dict[str, Any], index: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schemaVersion") != 1:
        errors.append(f"schemaVersion must be 1, got {report.get('schemaVersion')!r}")
    rows = report.get("surfaces")
    if not isinstance(rows, list):
        return ["surfaces must be a list"]

    expected_ids = implementation_surface_ids(matrix)
    report_ids = {row.get("surfaceId") for row in rows if isinstance(row, dict)}
    if report_ids != expected_ids:
        missing = sorted(str(x) for x in expected_ids - report_ids)
        extra = sorted(str(x) for x in report_ids - expected_ids)
        if missing:
            errors.append("coverage report missing implementation surface(s): " + ", ".join(missing))
        if extra:
            errors.append("coverage report has extra surface(s): " + ", ".join(extra))

    weak_ids = weak_index_ids(index)
    counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            errors.append("surface rows must be objects")
            continue
        surface_id = row.get("surfaceId")
        level = row.get("coverageLevel")
        if level not in ALLOWED_LEVELS:
            errors.append(f"{surface_id}: unsupported coverageLevel {level!r}")
            continue
        counts[level] = counts.get(level, 0) + 1
        candidate_count = row.get("runtimeCandidateCount")
        if not isinstance(candidate_count, int) or candidate_count < 0:
            errors.append(f"{surface_id}: runtimeCandidateCount must be a non-negative integer")
        if level == "runtime-candidate" and candidate_count <= 0:
            errors.append(f"{surface_id}: runtime-candidate coverage requires runtimeCandidateCount > 0")
        if level == "live-metadata-proven" and candidate_count != 0:
            errors.append(f"{surface_id}: live-metadata-proven coverage should not report runtimeSymbolCandidates")
        if level in {"method-dossier-only", "declaration-only"} and surface_id not in weak_ids:
            errors.append(f"{surface_id}: dossier-only coverage must have a weak dossier index row")
        if level == "no-generated-or-dossier-candidate":
            errors.append(f"{surface_id}: implementation-relevant surface has no runtime candidate or dossier coverage")
        boundary = row.get("boundary")
        if not isinstance(boundary, str) or not boundary.strip():
            errors.append(f"{surface_id}: boundary must be a non-empty string")

    if report.get("implementationRelevantSurfaceCount") != len(rows):
        errors.append("implementationRelevantSurfaceCount must match surface row count")
    if report.get("coverageCounts") != counts:
        errors.append("coverageCounts must match actual rows")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--matrix", type=Path, default=DEFAULT_MATRIX)
    parser.add_argument("--dossier-index", type=Path, default=DEFAULT_DOSSIER_INDEX)
    parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
    parser.add_argument("--plugin", type=Path, default=DEFAULT_PLUGIN)
    args = parser.parse_args()
    try:
        targets = load_json(args.targets)
        if not has_runtime_law_targets(targets):
            startup_errors = validate_no_runtime_mutator_registrations(args.plugin)
            if startup_errors:
                print("runtime candidate coverage validation failed:", file=sys.stderr)
                for error in startup_errors:
                    print(f"  - {error}", file=sys.stderr)
                return 1
            print("runtime candidate coverage validation skipped: no active runtime-backed custom law targets")
            return 0
        report = load_json(args.report)
        matrix = load_json(args.matrix)
        index = load_json(args.dossier_index)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"runtime candidate coverage validation failed: {exc}", file=sys.stderr)
        return 1

    errors = validate(report, matrix, index)
    if errors:
        print("runtime candidate coverage validation failed:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print(f"runtime candidate coverage validation passed ({report.get('implementationRelevantSurfaceCount')} surface(s))")
    print("Note: static pass does not prove runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

