#!/usr/bin/env python3
"""Write/update golden fingerprints for the vanilla_stock regression sample.

Requires artifacts already built (``tools/build_vanilla_stock_regression.py``).
HotA optional rows are written when artifacts exist; skipped otherwise.
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

from vanilla_stock.regression_fingerprint import (  # noqa: E402
    VanillaStockFingerprintError,
    extract_from_artifact_dir,
    write_fingerprint,
)


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
        "--include-optional",
        action="store_true",
        help="Also write baselines for optional HotA rows when artifacts exist",
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
    only = {str(x) for x in args.only}

    written = 0
    skipped = 0
    errors: list[str] = []

    for row in batch.get("scenarios") or []:
        if not isinstance(row, dict):
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
        if optional and not args.include_optional:
            skipped += 1
            continue

        artifact_dir = artifact_root / scenario_id
        manifest_file = artifact_dir / f"{map_sid}.manifest.json"
        if not manifest_file.is_file():
            if optional:
                print(f"SKIP optional {scenario_id}: no artifact", flush=True)
                skipped += 1
                continue
            errors.append(f"{scenario_id}: missing artifact manifest {manifest_file}")
            continue

        format_version = row.get("formatVersion")
        try:
            fingerprint = extract_from_artifact_dir(
                scenario_id=scenario_id,
                map_sid=map_sid,
                era=era,
                format_version=format_version if isinstance(format_version, int) else None,
                artifact_dir=artifact_dir,
            )
            out_path = baseline_root / f"{scenario_id}.fingerprint.json"
            write_fingerprint(out_path, fingerprint)
        except VanillaStockFingerprintError as ex:
            errors.append(f"{scenario_id}: {ex}")
            continue
        written += 1
        print(f"WROTE {out_path.relative_to(repo_root)}", flush=True)

    summary = {"written": written, "skipped": skipped, "errors": errors}
    print(json.dumps(summary, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
