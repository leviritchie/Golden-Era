#!/usr/bin/env python3
"""Validate vanilla_stock regression maps and compare golden fingerprints.

Required RoE/AB/SoD rows must build-validate and match committed baselines under
``scenarios/vanilla_stock/regression_baselines/``. HotA rows marked
``buildOptional`` soft-fail (reported, not gate-breaking).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
POC = REPO / "experiments" / "campaign_port_poc"
if str(POC) not in sys.path:
    sys.path.insert(0, str(POC))

from vanilla_stock.emit_map import DEFAULT_STOCK_CORE  # noqa: E402
from vanilla_stock.regression_fingerprint import (  # noqa: E402
    SCHEMA as FINGERPRINT_SCHEMA,
    VanillaStockFingerprintError,
    diff_fingerprints,
    extract_from_artifact_dir,
    load_fingerprint,
)
from vanilla_stock.validate_map import VanillaStockValidationError, validate_vanilla_stock_map  # noqa: E402


DEFAULT_MANIFEST = REPO / "scenarios" / "vanilla_stock" / "regression_manifest.json"


def _resolve(path_value: str | Path, *, base: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def _is_optional(row: dict[str, Any]) -> bool:
    role = str(row.get("role") or "")
    return bool(row.get("buildOptional")) or role in {"fan_import", "hota_soft"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument(
        "--allow-missing-baselines",
        action="store_true",
        help="Pass when baselines are absent (bootstrap only; still validates maps)",
    )
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    manifest_path = _resolve(args.manifest, base=repo_root)
    batch = json.loads(manifest_path.read_text(encoding="utf-8"))
    if batch.get("schema") != "homm3.vanilla_stock_batch_manifest.v1":
        print(f"unsupported regression manifest schema: {manifest_path}", file=sys.stderr)
        return 1

    artifact_root = _resolve(
        batch.get("artifactRoot") or "artifacts/campaign_port_poc/vanilla_stock",
        base=repo_root,
    )
    baseline_root = _resolve(
        batch.get("baselineRoot") or "scenarios/vanilla_stock/regression_baselines",
        base=repo_root,
    )
    stock_core = _resolve(batch.get("stockCore") or DEFAULT_STOCK_CORE, base=repo_root)
    only = {str(x) for x in args.only}

    errors: list[str] = []
    reports: list[dict[str, Any]] = []
    era_coverage: dict[str, int] = {}

    for row in batch.get("scenarios") or []:
        if not isinstance(row, dict):
            errors.append("scenario row is not an object")
            continue
        scenario_id = str(row.get("id") or "")
        map_sid = str(row.get("mapSid") or "")
        era = str(row.get("era") or "unknown")
        if only and scenario_id not in only:
            continue
        if not scenario_id or not map_sid:
            errors.append(f"incomplete scenario row: {row!r}")
            continue

        optional = _is_optional(row)
        map_path = artifact_root / scenario_id / "maps" / f"{map_sid}.map"
        manifest_file = artifact_root / scenario_id / f"{map_sid}.manifest.json"
        baseline_path = baseline_root / f"{scenario_id}.fingerprint.json"
        report: dict[str, Any] = {
            "id": scenario_id,
            "mapSid": map_sid,
            "era": era,
            "optional": optional,
        }

        if not map_path.is_file() or not manifest_file.is_file():
            msg = f"missing map/manifest artifact under {artifact_root / scenario_id}"
            if optional:
                print(f"OPTIONAL SKIP {scenario_id}: {msg}", flush=True)
                report["result"] = "OPTIONAL_SKIP"
                reports.append(report)
                continue
            errors.append(f"{scenario_id}: {msg}")
            continue

        try:
            validate_vanilla_stock_map(
                map_path=map_path,
                stock_core=stock_core,
                expect_map_sid=map_sid,
                expect_victory_mode=row.get("expectVictoryMode"),
                expect_mine_entity_count=row.get("expectMineEntityCount"),
                expect_map_event_count=row.get("expectMapEventCount"),
                manifest_path=manifest_file,
            )
        except VanillaStockValidationError as ex:
            if optional:
                print(f"OPTIONAL FAIL {scenario_id}: validate {ex}", flush=True)
                report["result"] = "OPTIONAL_FAIL"
                reports.append(report)
                continue
            errors.append(f"{scenario_id}: validate {ex}")
            continue

        format_version = row.get("formatVersion")
        if format_version is not None and not isinstance(format_version, int):
            errors.append(f"{scenario_id}: formatVersion must be int")
            continue

        try:
            actual = extract_from_artifact_dir(
                scenario_id=scenario_id,
                map_sid=map_sid,
                era=era,
                format_version=format_version if isinstance(format_version, int) else None,
                artifact_dir=artifact_root / scenario_id,
            )
        except VanillaStockFingerprintError as ex:
            if optional:
                print(f"OPTIONAL FAIL {scenario_id}: fingerprint {ex}", flush=True)
                report["result"] = "OPTIONAL_FAIL"
                reports.append(report)
                continue
            errors.append(f"{scenario_id}: fingerprint {ex}")
            continue

        if not baseline_path.is_file():
            msg = f"missing baseline {baseline_path}"
            if optional:
                print(f"OPTIONAL SKIP {scenario_id}: {msg}", flush=True)
                report["result"] = "OPTIONAL_SKIP_BASELINE"
                reports.append(report)
                continue
            if args.allow_missing_baselines:
                print(f"WARN {scenario_id}: {msg} (--allow-missing-baselines)", flush=True)
                report["result"] = "PASS_NO_BASELINE"
                era_coverage[era] = era_coverage.get(era, 0) + 1
                reports.append(report)
                continue
            errors.append(f"{scenario_id}: {msg}")
            continue

        try:
            expected = load_fingerprint(baseline_path)
        except VanillaStockFingerprintError as ex:
            if optional:
                print(f"OPTIONAL FAIL {scenario_id}: baseline {ex}", flush=True)
                report["result"] = "OPTIONAL_FAIL"
                reports.append(report)
                continue
            errors.append(f"{scenario_id}: baseline {ex}")
            continue

        # Compare semantic payload; ignore era/formatVersion metadata drift only if
        # baseline omitted them historically — still require id/mapSid/schema match.
        diffs = diff_fingerprints(expected, actual)
        if diffs:
            detail = "; ".join(diffs[:12])
            if len(diffs) > 12:
                detail += f"; ... (+{len(diffs) - 12} more)"
            if optional:
                print(f"OPTIONAL FAIL {scenario_id}: fingerprint drift: {detail}", flush=True)
                report["result"] = "OPTIONAL_FAIL"
                report["diffCount"] = len(diffs)
                reports.append(report)
                continue
            errors.append(f"{scenario_id}: fingerprint drift ({len(diffs)}): {detail}")
            continue

        print(f"PASS {scenario_id} ({era}, {map_sid})", flush=True)
        report["result"] = "PASS"
        report["fingerprintSchema"] = FINGERPRINT_SCHEMA
        era_coverage[era] = era_coverage.get(era, 0) + 1
        reports.append(report)

    required_eras = {"RoE", "AB", "SoD"}
    missing_eras = sorted(required_eras - set(era_coverage))
    if missing_eras and not only:
        errors.append(f"regression suite missing required era coverage after PASS: {missing_eras}")

    if errors:
        print("vanilla_stock regression contract FAIL")
        for error in errors:
            print(f"- {error}")
        return 1

    print(
        json.dumps(
            {
                "schema": "homm3.vanilla_stock_regression_validation.v1",
                "result": "PASS",
                "scenarioCount": len(reports),
                "eraCoverage": era_coverage,
                "scenarios": reports,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
