#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import (  # noqa: E402
    DEFAULT_MANIFEST_DIR,
    Validation,
    core_overlay_enabled,
    expand_units,
    load_json,
)


DEFAULT_TAGS_PATH = ROOT / "custom_factions" / "unit_family_tags.json"
ALLOWED_FACTS = {
    "gunpowder",
    "shooter",
    "melee",
    "construct",
    "elemental",
    "undead",
    "living",
    "gatedOrSummoned",
    "corpseProducing",
}
ALLOWED_VALUES = {"yes", "no", "unknown"}


def load_live_unit_sids(manifest_dir: Path) -> set[str]:
    sids: set[str] = set()
    for path in sorted(manifest_dir.glob("homm3_*.json")):
        manifest = load_json(path)
        if not isinstance(manifest, dict) or not core_overlay_enabled(manifest):
            continue
        for sid in expand_units(manifest):
            sids.add(sid)
    return sids


def validate_tags(doc: Any, live_sids: set[str], v: Validation) -> None:
    if not isinstance(doc, dict):
        v.error("unit family tags root must be an object")
        return

    schema_version = doc.get("schemaVersion")
    if schema_version != 1:
        v.error(f"schemaVersion must be 1, got {schema_version!r}")

    units = doc.get("units")
    if not isinstance(units, dict):
        v.error("units must be an object keyed by exact custom unit SID")
        return

    for sid, entry in sorted(units.items()):
        if not isinstance(sid, str) or not sid:
            v.error(f"unit key must be a non-empty string, got {sid!r}")
            continue
        if sid not in live_sids:
            v.error(f"{sid}: not found in enabled custom faction unit manifests")
        if not isinstance(entry, dict):
            v.error(f"{sid}: entry must be an object")
            continue

        for key, value in sorted(entry.items()):
            if key not in ALLOWED_FACTS:
                v.error(f"{sid}: unsupported family fact {key!r}")
                continue
            if value not in ALLOWED_VALUES:
                v.error(f"{sid}.{key}: value must be one of {sorted(ALLOWED_VALUES)}, got {value!r}")

        for fact in ALLOWED_FACTS:
            if fact not in entry:
                v.error(f"{sid}: missing explicit fact {fact!r}; use 'unknown' when unproven")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tags", type=Path, default=DEFAULT_TAGS_PATH)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    args = parser.parse_args()

    v = Validation()
    if not args.tags.exists():
        v.error(f"missing unit family tags file: {args.tags}")
        print(f"errors: {v.errors}")
        return 1

    live_sids = load_live_unit_sids(args.manifest_dir)
    doc = load_json(args.tags)
    validate_tags(doc, live_sids, v)

    units = doc.get("units") if isinstance(doc, dict) else {}
    unit_count = len(units) if isinstance(units, dict) else 0
    print(f"unit family tags: {unit_count} authored unit entr{'y' if unit_count == 1 else 'ies'}")
    print(f"known enabled custom unit SIDs: {len(live_sids)}")
    print(f"errors: {v.errors}")
    if v.warnings:
        print(f"warnings: {v.warnings}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
