"""Frozen capture-skeleton candidates. Chosen before sprite inference."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from paths import EXPERIMENT
from vendor_reference import load_complete_package, require_complete_package

CANDIDATES_PATH = EXPERIMENT / "capture_candidates.json"
ASSET_UNITS = ("h3_roc", "h3_crusader", "h3_beholder")


def load_candidates(path: Path | None = None) -> dict[str, Any]:
    payload = json.loads((path or CANDIDATES_PATH).read_text(encoding="utf-8"))
    assets = payload.get("assets")
    if not isinstance(assets, dict) or set(ASSET_UNITS) - set(assets):
        raise ValueError("capture_candidates.json must define h3_roc, h3_crusader, and h3_beholder")
    return payload


def asset_entry(unit: str, *, path: Path | None = None) -> dict[str, Any]:
    assets = load_candidates(path)["assets"]
    if unit not in assets:
        raise KeyError(f"no frozen capture candidate for {unit}")
    return assets[unit]


def coverage_status(unit: str) -> str:
    return str(asset_entry(unit).get("coverage") or "")


def candidate_record(unit: str, *, role: str = "primary") -> dict[str, Any]:
    entry = asset_entry(unit)
    if entry.get("coverage") == "unsupported":
        raise ValueError(
            f"{unit} has no defensible vendor capture skeleton: {entry.get('why')}"
        )
    if role not in {"primary", "comparison"}:
        raise ValueError(f"candidate role must be primary or comparison, got {role!r}")
    record = entry.get(role)
    if not isinstance(record, dict) or not record.get("refSeq"):
        raise ValueError(f"{unit} has no frozen {role} candidate")
    return dict(record)


def require_frozen_package(unit: str, *, role: str = "primary") -> dict[str, Any]:
    record = candidate_record(unit, role=role)
    kind = str(record["kind"])
    ref_seq = str(record["refSeq"])
    report = require_complete_package(kind, ref_seq)
    package = load_complete_package(kind, ref_seq)
    package["candidateRole"] = role
    package["unit"] = unit
    package["why"] = record.get("why")
    package["anatomy"] = record.get("anatomy")
    package["configName"] = record.get("configName")
    package["completeness"] = report
    return package


def refuse_unfrozen_reference(unit: str, kind: str, ref_seq: str) -> None:
    entry = asset_entry(unit)
    allowed = []
    for role in ("primary", "comparison"):
        record = entry.get(role)
        if isinstance(record, dict) and record.get("refSeq"):
            allowed.append((str(record["kind"]), str(record["refSeq"])))
    if (kind, ref_seq) not in allowed:
        raise ValueError(
            f"{kind}:{ref_seq} is not a frozen candidate for {unit}; "
            "capture exploration is bound to the preselected references"
        )
