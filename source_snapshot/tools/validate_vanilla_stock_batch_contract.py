#!/usr/bin/env python3
"""Validate every scenario in scenarios/vanilla_stock/batch_manifest.json."""

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
from vanilla_stock.validate_map import VanillaStockValidationError, validate_vanilla_stock_map  # noqa: E402


DEFAULT_MANIFEST = REPO / "scenarios" / "vanilla_stock" / "batch_manifest.json"


def _resolve(path_value: str | Path, *, base: Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (base / path).resolve()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo-root", type=Path, default=REPO)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--require-installed", action="store_true")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    manifest_path = _resolve(args.manifest, base=repo_root)
    batch = json.loads(manifest_path.read_text(encoding="utf-8"))
    if batch.get("schema") != "homm3.vanilla_stock_batch_manifest.v1":
        print(f"unsupported batch manifest schema: {manifest_path}", file=sys.stderr)
        return 1

    artifact_root = _resolve(
        batch.get("artifactRoot") or "artifacts/campaign_port_poc/vanilla_stock",
        base=repo_root,
    )
    stock_core = _resolve(batch.get("stockCore") or DEFAULT_STOCK_CORE, base=repo_root)
    install_dir = _resolve(batch.get("installMapsDir") or "", base=repo_root) if batch.get("installMapsDir") else None
    only = {str(x) for x in args.only}

    errors: list[str] = []
    reports: list[dict[str, Any]] = []
    for row in batch.get("scenarios") or []:
        if not isinstance(row, dict):
            errors.append("scenario row is not an object")
            continue
        scenario_id = str(row.get("id") or "")
        map_sid = str(row.get("mapSid") or "")
        if only and scenario_id not in only:
            continue
        if not scenario_id or not map_sid:
            errors.append(f"incomplete scenario row: {row!r}")
            continue
        map_path = artifact_root / scenario_id / "maps" / f"{map_sid}.map"
        manifest = artifact_root / scenario_id / f"{map_sid}.manifest.json"
        role = str(row.get("role") or "")
        optional = role == "fan_import" or bool(row.get("buildOptional"))
        if not map_path.is_file() or not manifest.is_file():
            if optional:
                print(f"OPTIONAL SKIP {scenario_id}: missing map/manifest artifact", flush=True)
                reports.append(
                    {
                        "id": scenario_id,
                        "mapSid": map_sid,
                        "result": "OPTIONAL_SKIP",
                        "optionalFailure": True,
                    }
                )
                continue
            if not map_path.is_file():
                errors.append(f"{scenario_id}: missing map {map_path}")
            if not manifest.is_file():
                errors.append(f"{scenario_id}: missing manifest {manifest}")
            continue
        try:
            report = validate_vanilla_stock_map(
                map_path=map_path,
                stock_core=stock_core,
                expect_map_sid=map_sid,
                expect_victory_mode=row.get("expectVictoryMode"),
                expect_mine_entity_count=row.get("expectMineEntityCount"),
                expect_map_event_count=row.get("expectMapEventCount"),
                manifest_path=manifest,
            )
        except VanillaStockValidationError as ex:
            if optional:
                print(f"OPTIONAL FAIL {scenario_id}: {ex}", flush=True)
                reports.append(
                    {
                        "id": scenario_id,
                        "mapSid": map_sid,
                        "result": "OPTIONAL_FAIL",
                        "optionalFailure": True,
                    }
                )
                continue
            errors.append(f"{scenario_id}: {ex}")
            continue
        if args.require_installed or batch.get("requireInstalled"):
            if install_dir is None:
                errors.append(f"{scenario_id}: installMapsDir missing from batch manifest")
            else:
                installed = install_dir / f"{map_sid}.map"
                if not installed.is_file():
                    errors.append(f"{scenario_id}: missing installed map {installed}")
                elif installed.read_bytes() != map_path.read_bytes():
                    errors.append(f"{scenario_id}: installed map differs from artifact")
        reports.append({"id": scenario_id, "mapSid": map_sid, "result": report.get("result")})
        print(f"PASS {scenario_id} ({map_sid})", flush=True)

    if errors:
        print("vanilla_stock batch contract FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        json.dumps(
            {
                "schema": "homm3.vanilla_stock_batch_validation.v1",
                "result": "PASS",
                "scenarioCount": len(reports),
                "scenarios": reports,
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
