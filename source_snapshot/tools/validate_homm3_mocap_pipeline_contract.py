#!/usr/bin/env python3
"""Validate provenance for the current captured-mocap lane.

This is intentionally separate from the legacy fused-push validator.  It can
be run against a corpus, a fitter report, or both, and is also imported by the
candidate fitter before GPU work begins.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.homm3_mocap_v2.pipeline_contract import (  # noqa: E402
    SCHEMA,
    validate_corpus_contract,
    validate_fit_report_contract,
)


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_inventory(path: Path) -> dict:
    """Validate the full-set inventory without running GPU or Blender work."""
    data = _load(path)
    if data.get("schema") != "homm3.mocap-unit-inventory.v1":
        raise ValueError("unsupported mocap unit inventory schema")
    rows = data.get("units")
    if not isinstance(rows, list) or int(data.get("unitCount", -1)) != len(rows):
        raise ValueError("inventory unitCount does not match rows")
    seen: set[str] = set()
    summary: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("unit"):
            raise ValueError("inventory row is missing unit")
        unit = str(row["unit"])
        if unit in seen:
            raise ValueError(f"duplicate inventory unit {unit}")
        seen.add(unit)
        readiness = str(row.get("readiness") or "")
        summary[readiness] = summary.get(readiness, 0) + 1
        source = row.get("source") or {}
        corpus = source.get("corpus")
        if corpus:
            corpus_path = (ROOT / str(corpus)).resolve()
            if not corpus_path.is_file():
                raise ValueError(f"{unit}: corpus path is missing")
            if source.get("corpusSha256") != _sha(corpus_path):
                raise ValueError(f"{unit}: corpus hash drift")
        registration = row.get("registration") or {}
        if registration.get("status") == "registered_unaccepted":
            root = (ROOT / str(registration.get("root"))).resolve()
            required = (root / "pilot_report.json", root / "camera.json", root / "camera_registration.json")
            if not all(path.is_file() for path in required):
                raise ValueError(f"{unit}: registered baseline is incomplete")
            if _load(required[2]).get("status") != "registered":
                raise ValueError(f"{unit}: registration status is not registered")
            if registration.get("sha256") != _sha(required[2]):
                raise ValueError(f"{unit}: registration hash drift")
        command = row.get("plannedCommand") or []
        if readiness == "ready_for_weights_only":
            if row.get("rig", {}).get("kind") != "canonical_smartrig" or not command:
                raise ValueError(f"{unit}: ready row lacks canonical rig or command")
            if "weights_only" not in command or unit not in command:
                raise ValueError(f"{unit}: planned command is not weights-only for this unit")
            rig_value = row.get("rig", {}).get("path")
            prep_value = (row.get("preparation") or {}).get("path")
            if not rig_value or not prep_value:
                raise ValueError(f"{unit}: ready row lacks rig/preparation identity paths")
            rig_path = (ROOT / str(rig_value)).resolve()
            prep_path = (ROOT / str(prep_value)).resolve()
            if not rig_path.is_file() or not prep_path.is_file():
                raise ValueError(f"{unit}: ready rig or frozen preparation is missing")
            frozen = _load(prep_path)
            expected_mesh = str((frozen.get("inputHashes") or {}).get("originalMesh") or "")
            if not expected_mesh:
                raise ValueError(f"{unit}: frozen preparation lacks originalMesh hash")
            if _sha(rig_path) != expected_mesh:
                raise ValueError(f"{unit}: rig bytes do not match frozen preparation originalMesh")
        elif command:
            raise ValueError(f"{unit}: non-ready row has a planned command")
    if summary != data.get("summary"):
        raise ValueError("inventory summary drift")
    return {
        "schema": data["schema"],
        "ok": True,
        "unitCount": len(rows),
        "summary": dict(sorted(summary.items())),
        "proof": "source-static",
    }


def validate_lighting_selection(path: Path) -> dict:
    """Validate the downstream lighting selection and its pinned hashes."""
    data = _load(path)
    if data.get("schema") != "homm3.mocap-lighting-selection.v1":
        raise ValueError("unsupported mocap lighting selection schema")
    rows = data.get("units")
    if not isinstance(rows, list) or not rows:
        raise ValueError("lighting selection must contain at least one unit")
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("lighting selection row is not an object")
        sid = str(row.get("labSid") or "")
        if not sid or sid in seen:
            raise ValueError(f"duplicate or missing lighting unit {sid!r}")
        seen.add(sid)
        for key in ("sourceReport", "corpus"):
            value = row.get(key)
            if not value or not (ROOT / str(value)).is_file():
                raise ValueError(f"{sid}: lighting {key} path is missing")
        report = ROOT / str(row["sourceReport"])
        corpus = ROOT / str(row["corpus"])
        if row.get("sourceReportSha256") != _sha(report):
            raise ValueError(f"{sid}: lighting source report hash drift")
        if row.get("corpusSha256") != _sha(corpus):
            raise ValueError(f"{sid}: lighting corpus hash drift")
    return {
        "schema": data["schema"],
        "ok": True,
        "unitCount": len(rows),
        "proof": "source-static",
    }


def validate_deformation_audit(path: Path) -> dict:
    """Validate the shape and error accounting of the read-only audit batch."""
    data = _load(path)
    if data.get("schema") != "homm3.mocap-frame-deformation-batch.v1":
        raise ValueError("unsupported mocap deformation audit schema")
    rows = data.get("units")
    if not isinstance(rows, list) or int(data.get("clipCount", -1)) != len(rows):
        raise ValueError("deformation audit clipCount does not match rows")
    units = {str(row.get("unit") or "") for row in rows if isinstance(row, dict)}
    if "" in units or int(data.get("unitCount", -1)) != len(units):
        raise ValueError("deformation audit unitCount does not match rows")
    errors = sorted({str(row["unit"]) for row in rows if row.get("error")})
    if errors != sorted(str(value) for value in (data.get("errorUnits") or [])):
        raise ValueError("deformation audit error accounting drift")
    for row in rows:
        if not isinstance(row, dict) or not row.get("unit"):
            raise ValueError("deformation audit row is missing unit")
        if row.get("error"):
            continue
        regions = row.get("regions")
        if not isinstance(regions, dict) or not isinstance(row.get("flaggedRegions"), list):
            raise ValueError(f"{row['unit']}: deformation audit regions are missing")
        for name, region in regions.items():
            if not isinstance(name, str) or not isinstance(region, dict):
                raise ValueError(f"{row['unit']}: malformed region {name!r}")
            if not isinstance(region.get("perFrame"), list) or not isinstance(region.get("highStrain"), bool):
                raise ValueError(f"{row['unit']}: malformed region metrics for {name}")
    return {
        "schema": data["schema"],
        "ok": True,
        "clipCount": len(rows),
        "unitCount": len(units),
        "errorCount": len(errors),
        "proof": "source-static",
    }


def validate(*, corpus: Path | None = None, fit_report: Path | None = None,
             inventory: Path | None = None, delivery: bool = False,
             require_explicit_corpus: bool = False) -> dict:
    if corpus is None and fit_report is None and inventory is None:
        raise ValueError("provide --corpus, --fit-report, and/or --inventory")
    result = {"schema": SCHEMA, "ok": True, "proof": "source-static"}
    if corpus is not None:
        result["corpus"] = validate_corpus_contract(
            _load(corpus), allow_legacy=not require_explicit_corpus
        )
        result["corpusPath"] = str(corpus.resolve()).replace("\\", "/")
    if fit_report is not None:
        result["fitReport"] = validate_fit_report_contract(_load(fit_report), delivery=delivery)
        result["fitReportPath"] = str(fit_report.resolve()).replace("\\", "/")
    if inventory is not None:
        result["inventory"] = validate_inventory(inventory)
        result["inventoryPath"] = str(inventory.resolve()).replace("\\", "/")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--fit-report", type=Path)
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--lighting-selection", type=Path)
    parser.add_argument("--deformation-audit", type=Path)
    parser.add_argument("--delivery", action="store_true")
    parser.add_argument("--require-explicit-corpus", action="store_true",
                        help="reject historical corpora that omit motionRepresentation")
    args = parser.parse_args()
    if args.lighting_selection and args.corpus is None and args.fit_report is None and args.inventory is None:
        result = {"schema": SCHEMA, "ok": True, "proof": "source-static"}
    else:
        result = validate(corpus=args.corpus, fit_report=args.fit_report,
                          inventory=args.inventory,
                          delivery=args.delivery,
                          require_explicit_corpus=args.require_explicit_corpus)
    if args.lighting_selection:
        result["lightingSelection"] = validate_lighting_selection(args.lighting_selection)
        result["lightingSelectionPath"] = str(args.lighting_selection.resolve()).replace("\\", "/")
    if args.deformation_audit:
        result["deformationAudit"] = validate_deformation_audit(args.deformation_audit)
        result["deformationAuditPath"] = str(args.deformation_audit.resolve()).replace("\\", "/")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
