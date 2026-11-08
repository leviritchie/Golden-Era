#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import DEFAULT_MANIFEST_DIR, Validation, core_overlay_enabled, load_json  # noqa: E402


def load_structure_contracts(manifest_dir: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(manifest_dir.glob("homm3_*.json")):
        manifest = load_json(path)
        if not isinstance(manifest, dict) or not core_overlay_enabled(manifest):
            continue
        identity = manifest.get("identity") if isinstance(manifest.get("identity"), dict) else {}
        overlay = manifest.get("coreOverlay") if isinstance(manifest.get("coreOverlay"), dict) else {}
        faction_sid = identity.get("factionSid")
        city_sid = identity.get("citySid")
        direct_city = overlay.get("directCityMapObject")
        dwelling_prefix = overlay.get("directDwellingPrefix")
        rows.append(
            {
                "sourceFile": str(path.relative_to(ROOT)),
                "factionSid": faction_sid,
                "citySid": city_sid,
                "directCityMapObject": direct_city,
                "directDwellingPrefix": dwelling_prefix,
            }
        )
    return rows


def validate_structure_contracts(rows: list[dict[str, Any]], validation: Validation) -> None:
    if not rows:
        validation.error("no enabled custom faction manifests found for adventure owned-structure registry")
        return
    seen: set[str] = set()
    for row in rows:
        context = row.get("sourceFile") or row.get("factionSid") or "<unknown>"
        faction_sid = row.get("factionSid")
        city_sid = row.get("citySid")
        direct_city = row.get("directCityMapObject")
        dwelling_prefix = row.get("directDwellingPrefix")
        if not isinstance(faction_sid, str) or not faction_sid.startswith("homm3_"):
            validation.error(f"{context}: factionSid must be a homm3_* string")
            continue
        if faction_sid in seen:
            validation.error(f"{context}: duplicate enabled factionSid {faction_sid}")
        seen.add(faction_sid)
        if not isinstance(city_sid, str) or not city_sid:
            validation.error(f"{context}: identity.citySid must be a non-empty string")
        if direct_city != city_sid:
            validation.error(f"{context}: directCityMapObject {direct_city!r} must match identity.citySid {city_sid!r}")
        if not isinstance(dwelling_prefix, str) or not dwelling_prefix:
            validation.error(f"{context}: directDwellingPrefix must be a non-empty string")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate manifest-derived adventure owned-structure registry source. "
            "This proves exact custom city SIDs and dwelling prefixes only, not runtime ownership or reveal behavior."
        )
    )
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    args = parser.parse_args()

    validation = Validation()
    rows = load_structure_contracts(args.manifest_dir)
    validate_structure_contracts(rows, validation)
    print(f"adventure owned-structure source contracts: {len(rows)} enabled faction row(s)")
    print(f"errors: {validation.errors}")
    if validation.warnings:
        print(f"warnings: {validation.warnings}")
    return 1 if validation.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
