#!/usr/bin/env python3
"""Validate weak gameplay-surface dossier coverage.

This checks the generated dossier index against the generated weak-surface plan.
It is a static artifact consistency gate only; it does not build dossiers,
launch the game, or prove runtime behavior.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = ROOT / "custom_factions" / "gameplay_surface_weak_dossier_plan.json"
DEFAULT_INDEX = ROOT / "custom_factions" / "gameplay_surface_weak_dossier_index.json"
VALID_DOSSIER_STATUSES = {"built", "declaration-only", "failed", "unresolved-target"}
ACCEPTED_DOSSIER_STATUSES = {"built", "declaration-only"}


class Validation:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def as_object(value: Any, label: str, v: Validation) -> dict[str, Any]:
    if not isinstance(value, dict):
        v.error(f"{label} must be an object")
        return {}
    return value


def as_list(value: Any, label: str, v: Validation) -> list[Any]:
    if not isinstance(value, list):
        v.error(f"{label} must be a list")
        return []
    return value


def check_path(path_value: Any, label: str, v: Validation) -> Path | None:
    if not isinstance(path_value, str) or not path_value.strip():
        v.error(f"{label} must be a non-empty string")
        return None
    path = ROOT / path_value
    if not path.exists():
        v.error(f"{label} does not exist: {path_value}")
    return path


def validate_dossier(surface_id: str, index: int, raw: Any, v: Validation) -> str | None:
    dossier = as_object(raw, f"{surface_id}.dossiers[{index}]", v)
    if not dossier:
        return None
    status = dossier.get("status")
    if status not in VALID_DOSSIER_STATUSES:
        v.error(f"{surface_id}.dossiers[{index}].status has unsupported value {status!r}")
    if status not in ACCEPTED_DOSSIER_STATUSES:
        v.error(f"{surface_id}.dossiers[{index}] is not accepted: {status!r}")

    check_path(dossier.get("markdown"), f"{surface_id}.dossiers[{index}].markdown", v)
    manifest = check_path(dossier.get("manifest"), f"{surface_id}.dossiers[{index}].manifest", v)
    if manifest is not None and manifest.exists():
        try:
            manifest_doc = load_json(manifest)
        except (OSError, json.JSONDecodeError) as exc:
            v.error(f"{surface_id}.dossiers[{index}].manifest is not valid JSON: {exc}")
        else:
            if status == "declaration-only" and manifest_doc.get("status") != "declaration-only":
                v.error(f"{surface_id}.dossiers[{index}].manifest must record declaration-only status")

    if status == "built":
        if not dossier.get("targetType"):
            v.error(f"{surface_id}.dossiers[{index}].targetType must be present for built dossiers")
        if dossier.get("returnCode") != 0:
            v.error(f"{surface_id}.dossiers[{index}].returnCode must be 0 for built dossiers")
    if status == "declaration-only":
        boundary = dossier.get("candidateBoundary")
        if not isinstance(boundary, str) or not boundary.strip():
            v.error(f"{surface_id}.dossiers[{index}].candidateBoundary must describe declaration-only limits")
    return status if isinstance(status, str) else None


def validate(plan_doc: Any, index_doc: Any) -> Validation:
    v = Validation()
    plan = as_object(plan_doc, "plan root", v)
    index = as_object(index_doc, "index root", v)
    if v.errors:
        return v

    if plan.get("schemaVersion") != 1:
        v.error(f"plan schemaVersion must be 1, got {plan.get('schemaVersion')!r}")
    if index.get("schemaVersion") != 1:
        v.error(f"index schemaVersion must be 1, got {index.get('schemaVersion')!r}")

    weak_surfaces = [row for row in as_list(plan.get("weakSurfaces"), "plan.weakSurfaces", v) if isinstance(row, dict)]
    index_surfaces = [row for row in as_list(index.get("surfaces"), "index.surfaces", v) if isinstance(row, dict)]
    plan_ids = {row.get("surfaceId") for row in weak_surfaces}
    index_ids = {row.get("surfaceId") for row in index_surfaces}
    if plan_ids != index_ids:
        missing = sorted(str(x) for x in plan_ids - index_ids)
        extra = sorted(str(x) for x in index_ids - plan_ids)
        if missing:
            v.error("index missing weak surface(s): " + ", ".join(missing))
        if extra:
            v.error("index has extra surface(s): " + ", ".join(extra))

    if index.get("sourcePlanWeakSurfaceCount") != plan.get("weakSurfaceCount"):
        v.error("index.sourcePlanWeakSurfaceCount must match plan.weakSurfaceCount")
    if index.get("surfaceCount") != len(index_surfaces):
        v.error("index.surfaceCount must equal actual surface count")
    if index.get("surfaceCount") != len(weak_surfaces):
        v.error("index.surfaceCount must equal weak surface count")
    if index.get("failedDossierCount") != 0:
        v.error("index.failedDossierCount must be 0")
    if index.get("unresolvedSurfaceCount") != 0:
        v.error("index.unresolvedSurfaceCount must be 0")

    counted: dict[str, int] = {"built": 0, "declaration-only": 0, "failed": 0, "unresolved-target": 0}
    for raw_surface in index_surfaces:
        surface_id = raw_surface.get("surfaceId")
        if not isinstance(surface_id, str) or not surface_id.strip():
            v.error("index surfaceId must be a non-empty string")
            continue
        dossiers = as_list(raw_surface.get("dossiers"), f"{surface_id}.dossiers", v)
        if not dossiers:
            v.error(f"{surface_id}: must have at least one dossier")
            continue
        for dossier_index, raw_dossier in enumerate(dossiers):
            status = validate_dossier(surface_id, dossier_index, raw_dossier, v)
            if status in counted:
                counted[status] += 1

    if index.get("builtDossierCount") != counted["built"]:
        v.error("index.builtDossierCount does not match actual built dossier count")
    if index.get("declarationOnlyDossierCount") != counted["declaration-only"]:
        v.error("index.declarationOnlyDossierCount does not match actual declaration-only dossier count")
    if index.get("failedDossierCount") != counted["failed"]:
        v.error("index.failedDossierCount does not match actual failed dossier count")
    if index.get("unresolvedSurfaceCount") != counted["unresolved-target"]:
        v.error("index.unresolvedSurfaceCount does not match actual unresolved dossier count")
    return v


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    args = parser.parse_args()

    try:
        plan = load_json(args.plan)
        index = load_json(args.index)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"weak gameplay surface dossier index validation failed: {exc}", file=sys.stderr)
        return 1

    result = validate(plan, index)
    if result.errors:
        print("weak gameplay surface dossier index validation failed:", file=sys.stderr)
        for error in result.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    surface_count = len(index.get("surfaces", []))
    print(f"weak gameplay surface dossier index validation passed ({surface_count} surface(s))")
    print("Note: static pass does not prove runtime law behavior.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
