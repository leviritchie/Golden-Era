"""Audit fit reports referenced by an asset-agnostic faction manifest.

This is a read-only generated-artifact audit. It does not infer delivery or
runtime acceptance from file existence, candidate flags, or status prose.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def audit(manifest_path: Path, output: Path, *, path_root: Path | None = None) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    root = (path_root or Path(__file__).resolve().parents[2]).resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    output = output.resolve()
    if output.exists():
        raise FileExistsError(output)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = manifest.get("units")
    if not isinstance(rows, list) or not rows:
        raise ValueError("manifest units must be a non-empty list")
    sids = [row.get("sid") for row in rows if isinstance(row, dict)]
    if len(sids) != len(set(sids)):
        raise ValueError("manifest contains duplicate sids")
    audited = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("name") or not row.get("sid"):
            raise ValueError("each manifest row requires name and sid")
        fit_value = row.get("fit")
        base = {"name": row["name"], "sid": row["sid"], "evidenceAsset": row.get("evidenceAsset")}
        if not fit_value:
            audited.append({**base, "fit": None, "fitState": "unreferenced", "acceptance": "unknown"})
            continue
        fit_path = (root / fit_value).resolve()
        if not fit_path.is_file():
            raise FileNotFoundError(fit_path)
        report = json.loads(fit_path.read_text(encoding="utf-8"))
        if not isinstance(report, dict):
            raise ValueError(f"fit report root must be an object for {row['name']}")
        fit_asset = report.get("asset")
        expected = row.get("evidenceAsset")
        if expected is not None and fit_asset != expected:
            raise ValueError(f"fit report asset {fit_asset!r} does not match evidenceAsset {expected!r} for {row['name']}")
        gate = report.get("qualityGate")
        if gate is not None and not isinstance(gate, dict):
            raise ValueError(f"qualityGate must be an object for {row['name']}")
        if gate is not None and any(type(value) is not bool for value in gate.values()):
            raise ValueError(f"qualityGate values must be boolean for {row['name']}")
        audited.append({**base, "fit": str(fit_path), "fitSha256": sha256_file(fit_path),
                        "fitState": "report-loaded", "fitAsset": fit_asset,
                        "sourceSidMapping": {"manifestSid": row["sid"], "reportAsset": fit_asset, "matchedBy": "explicit evidenceAsset" if expected is not None else "recorded-only"},
                        "qualityGate": gate, "candidateValidForExport": report.get("candidateValidForExport"),
                        "disposition": report.get("disposition"), "elapsedSecondsCached": report.get("elapsedSecondsCached"),
                        "clipCount": len(report.get("cases", {})) if isinstance(report.get("cases"), dict) else None,
                        "acceptance": "unknown"})
    result = {"schema": "faction-fit-status-audit-v1", "manifest": str(manifest_path),
              "manifestSha256": sha256_file(manifest_path), "unitCount": len(audited),
              "fitReportCount": sum(row["fitState"] == "report-loaded" for row in audited),
              "acceptance": "unknown", "units": audited}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--path-root", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.manifest, args.output, path_root=args.path_root), indent=2))
