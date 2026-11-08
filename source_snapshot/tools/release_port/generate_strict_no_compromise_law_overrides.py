#!/usr/bin/env python3
"""Generate strict no-compromise law override candidates.

This does not modify the playable custom_factions/law_overrides source. It
emits a separate override directory where every non-native-exact target law has
no concrete bonuses and an explicit pending description. The output is useful
for strict candidate builds and for catching inherited donor/Core rows before
runtime packet implementations are proven.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
TARGETS_PATH = ROOT / "custom_factions" / "custom_law_targets.json"
SOURCE_OVERRIDE_DIR = ROOT / "custom_factions" / "law_overrides"
DEFAULT_OUT_DIR = ROOT / "artifacts" / "custom_law_static" / "strict_law_overrides"

NONFINAL_STATUSES = {"needs-runtime", "temporary-compromise", "blocked"}
PENDING_DESCRIPTION_PREFIX = "Pending no-compromise implementation."


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def load_targets() -> tuple[dict[str, dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    doc = load_json(TARGETS_PATH)
    targets = doc.get("targets") if isinstance(doc, dict) else None
    families = doc.get("families") if isinstance(doc, dict) else None
    if not isinstance(targets, list):
        raise ValueError(f"{TARGETS_PATH.relative_to(ROOT)} does not contain a targets list")
    if not isinstance(families, dict):
        raise ValueError(f"{TARGETS_PATH.relative_to(ROOT)} does not contain a families object")

    by_sid: dict[str, dict[str, Any]] = {}
    by_faction: dict[str, list[dict[str, Any]]] = {}
    for target in targets:
        if not isinstance(target, dict):
            raise ValueError("custom_law_targets.json contains a non-object target")
        sid = target.get("lawSid")
        faction = target.get("faction")
        law_index = target.get("lawIndex")
        if not isinstance(sid, str) or not isinstance(faction, str) or not isinstance(law_index, int):
            raise ValueError(f"target has invalid lawSid/faction/lawIndex: {target!r}")
        family = families.get(str(law_index))
        if not isinstance(family, dict) or not isinstance(family.get("packet"), str):
            raise ValueError(f"{sid}: target family has no packet")
        enriched = dict(target)
        enriched["packet"] = family["packet"]
        by_sid[sid] = enriched
        by_faction.setdefault(faction, []).append(enriched)
    return by_sid, by_faction


def pending_description(target: dict[str, Any]) -> str:
    mechanic = target.get("targetMechanic")
    packet = target.get("packet")
    if not isinstance(mechanic, str) or not mechanic.strip():
        raise ValueError(f"{target.get('lawSid')}: missing targetMechanic")
    if not isinstance(packet, str) or not packet.strip():
        raise ValueError(f"{target.get('lawSid')}: missing packet")
    return (
        PENDING_DESCRIPTION_PREFIX
        + " Target mechanic: "
        + mechanic.strip()
        + " This strict candidate row has no gameplay effect until the "
        + packet
        + " packet is runtime-proven and implemented."
    )


def strip_level_bonuses(levels: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(levels, list) or not levels:
        return [{"cost": 3, "bonuses": []}], 0
    stripped: list[dict[str, Any]] = []
    removed = 0
    for level in levels:
        if not isinstance(level, dict):
            stripped.append({"cost": 3, "bonuses": []})
            continue
        new_level = copy.deepcopy(level)
        bonuses = new_level.get("bonuses")
        if isinstance(bonuses, list):
            removed += len(bonuses)
        new_level["bonuses"] = []
        stripped.append(new_level)
    return stripped, removed


def make_pending_row(target: dict[str, Any], source_row: dict[str, Any] | None) -> tuple[dict[str, Any], int, bool]:
    row = copy.deepcopy(source_row) if isinstance(source_row, dict) else {}
    levels, removed = strip_level_bonuses(row.get("parametersPerLevel"))
    row["enabled"] = True
    row["nameText"] = target["name"]
    row["descriptionText"] = pending_description(target)
    row["parametersPerLevel"] = levels
    row["notes"] = (
        "Strict no-compromise candidate row. Concrete donor/native bonuses are stripped until "
        f"the {target['packet']} packet is runtime-proven and implemented."
    )
    row["xHomm3NoCompromiseStrictRows"] = "source candidate has no concrete bonuses"
    return row, removed, source_row is None


def row_bonus_count(row: Any) -> int:
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


def generate(out_dir: Path) -> dict[str, Any]:
    targets_by_sid, targets_by_faction = load_targets()
    if out_dir.exists():
        for path in sorted(out_dir.glob("*.json")):
            path.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "schemaVersion": 1,
        "purpose": "Generated strict no-compromise law override candidates. Not playable default source and not runtime proof.",
        "sourceOverrideDir": str(SOURCE_OVERRIDE_DIR.relative_to(ROOT)).replace("\\", "/"),
        "outDir": str(out_dir.relative_to(ROOT)).replace("\\", "/"),
        "files": [],
        "strippedRows": 0,
        "createdRows": 0,
        "removedBonuses": 0,
        "keptNativeExactRows": 0,
    }

    source_docs: dict[str, dict[str, Any]] = {}
    for path in sorted(SOURCE_OVERRIDE_DIR.glob("homm3_*.json")):
        doc = load_json(path)
        if not isinstance(doc, dict):
            raise ValueError(f"{path.relative_to(ROOT)} is not an object")
        source_docs[path.stem.removeprefix("homm3_")] = doc

    for faction, targets in sorted(targets_by_faction.items()):
        source_doc = copy.deepcopy(source_docs.get(faction, {"lawOverrides": {}}))
        law_overrides = source_doc.get("lawOverrides")
        if not isinstance(law_overrides, dict):
            law_overrides = {}
            source_doc["lawOverrides"] = law_overrides

        file_summary = {
            "faction": faction,
            "file": f"homm3_{faction}.json",
            "strippedRows": 0,
            "createdRows": 0,
            "removedBonuses": 0,
            "keptNativeExactRows": 0,
        }
        for target in sorted(targets, key=lambda row: int(row["lawIndex"])):
            sid = target["lawSid"]
            status = target.get("implementationStatus")
            existing = law_overrides.get(sid)
            if status in NONFINAL_STATUSES:
                replacement, removed, created = make_pending_row(target, existing if isinstance(existing, dict) else None)
                law_overrides[sid] = replacement
                file_summary["removedBonuses"] += removed
                summary["removedBonuses"] += removed
                if created:
                    file_summary["createdRows"] += 1
                    summary["createdRows"] += 1
                else:
                    file_summary["strippedRows"] += 1
                    summary["strippedRows"] += 1
            elif row_bonus_count(existing) > 0:
                file_summary["keptNativeExactRows"] += 1
                summary["keptNativeExactRows"] += 1

        out_file = out_dir / f"homm3_{faction}.json"
        write_json(out_file, source_doc)
        summary["files"].append(file_summary)

    summary_path = out_dir / "_summary.json"
    write_json(summary_path, summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    try:
        summary = generate(args.out_dir)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"strict no-compromise law override generation failed: {exc}", file=sys.stderr)
        return 1

    print(
        "strict no-compromise law overrides generated: "
        f"{len(summary['files'])} file(s), "
        f"{summary['strippedRows']} stripped row(s), "
        f"{summary['createdRows']} created row(s), "
        f"{summary['removedBonuses']} removed bonus object(s)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
