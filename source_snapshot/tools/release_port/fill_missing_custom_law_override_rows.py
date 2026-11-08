#!/usr/bin/env python3
"""Fill missing playable custom law override rows from strict no-compromise candidates.

This intentionally copies only rows that are absent from custom_factions/law_overrides.
It does not replace existing playable compromises and does not add gameplay bonuses.
The source of each inserted row is the generated strict candidate artifact, which
must already be bonus-free for non-final target laws.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
SOURCE_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"
STRICT_OVERRIDE_DIR = ROOT / "artifacts" / "custom_law_static" / "strict_law_overrides"
NONFINAL_STATUSES = {"needs-runtime", "temporary-compromise", "blocked"}


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def bonus_count(row: Any) -> int:
    if not isinstance(row, dict):
        return 0
    levels = row.get("parametersPerLevel")
    if not isinstance(levels, list):
        return 0
    count = 0
    for level in levels:
        if not isinstance(level, dict):
            continue
        bonuses = level.get("bonuses")
        if isinstance(bonuses, list):
            count += len(bonuses)
    return count


def load_nonfinal_targets() -> list[dict[str, Any]]:
    doc = load_json(TARGETS_PATH)
    targets = doc.get("targets") if isinstance(doc, dict) else None
    if not isinstance(targets, list):
        raise ValueError("custom_law_targets.json has no targets list")
    result: list[dict[str, Any]] = []
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("custom_law_targets.json contains a non-object target")
        status = target.get("implementationStatus")
        sid = target.get("lawSid")
        faction = target.get("faction")
        if status in NONFINAL_STATUSES:
            if not isinstance(sid, str) or not isinstance(faction, str):
                raise ValueError(f"invalid non-final target row: {target!r}")
            result.append(target)
    return result


def load_override_doc(path: Path) -> dict[str, Any]:
    if path.exists():
        doc = load_json(path)
        if not isinstance(doc, dict):
            raise ValueError(f"{path.relative_to(ROOT)} root must be an object")
        overrides = doc.get("lawOverrides")
        if not isinstance(overrides, dict):
            raise ValueError(f"{path.relative_to(ROOT)} has no lawOverrides object")
        return doc
    return {"lawOverrides": {}}


def fill_missing(source_dir: Path, strict_dir: Path) -> dict[str, Any]:
    inserted: list[dict[str, str]] = []
    touched: set[Path] = set()
    for target in load_nonfinal_targets():
        sid = str(target["lawSid"])
        faction = str(target["faction"])
        source_path = source_dir / f"homm3_{faction}.json"
        strict_path = strict_dir / f"homm3_{faction}.json"
        if not strict_path.exists():
            raise ValueError(f"missing strict candidate file for {sid}: {strict_path.relative_to(ROOT)}")
        source_doc = load_override_doc(source_path)
        source_overrides = source_doc["lawOverrides"]
        if sid in source_overrides:
            continue
        strict_doc = load_override_doc(strict_path)
        strict_row = strict_doc["lawOverrides"].get(sid)
        if not isinstance(strict_row, dict):
            raise ValueError(f"strict candidate row missing for {sid}")
        if bonus_count(strict_row) != 0:
            raise ValueError(f"strict candidate row for {sid} has concrete bonuses")
        source_overrides[sid] = strict_row
        write_json(source_path, source_doc)
        touched.add(source_path)
        inserted.append({"faction": faction, "lawSid": sid, "file": str(source_path.relative_to(ROOT)).replace("\\", "/")})
    return {
        "schemaVersion": 1,
        "purpose": "Inserted missing playable law override rows from strict no-compromise candidates. These rows have no gameplay bonuses.",
        "insertedRows": inserted,
        "touchedFiles": sorted(str(path.relative_to(ROOT)).replace("\\", "/") for path in touched),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_OVERRIDE_DIR)
    parser.add_argument("--strict-dir", type=Path, default=STRICT_OVERRIDE_DIR)
    parser.add_argument("--out-summary", type=Path)
    args = parser.parse_args()

    try:
        summary = fill_missing(args.source_dir, args.strict_dir)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"missing law override row fill failed: {exc}", file=sys.stderr)
        return 1

    if args.out_summary:
        write_json(args.out_summary, summary)
    print(f"missing law override rows inserted: {len(summary['insertedRows'])}")
    for row in summary["insertedRows"]:
        print(f"  - {row['lawSid']} -> {row['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
