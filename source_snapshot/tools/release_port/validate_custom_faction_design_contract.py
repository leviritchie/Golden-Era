#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from validate_custom_faction_manifests import (  # noqa: E402
    DEFAULT_ABILITY_OVERRIDE_DIR,
    DEFAULT_HERO_OVERRIDE_DIR,
    DEFAULT_MANIFEST_DIR,
    DEFAULT_SOURCE_MECHANICS_DIR,
    Validation,
    collect_city_building_config_rows,
    core_overlay_enabled,
    expand_units,
    load_json,
    read_core_json,
    validate_core_members,
)


def load_manifests(manifest_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    result: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(manifest_dir.glob("homm3_*.json")):
        result.append((path, load_json(path)))
    return result


def core_text(core: Path, member: str) -> str:
    with zipfile.ZipFile(core, "r") as zf:
        try:
            return zf.read(member).decode("utf-8-sig")
        except KeyError:
            return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--plugin-root", type=Path)
    parser.add_argument("--manifest-dir", type=Path, default=DEFAULT_MANIFEST_DIR)
    parser.add_argument("--recommendations", type=Path, default=ROOT / "docs" / "custom_faction_design_recommendations.md")
    parser.add_argument("--source-mechanics-dir", type=Path, default=DEFAULT_SOURCE_MECHANICS_DIR)
    parser.add_argument("--hero-override-dir", type=Path, default=DEFAULT_HERO_OVERRIDE_DIR)
    parser.add_argument("--ability-override-dir", type=Path, default=DEFAULT_ABILITY_OVERRIDE_DIR)
    args = parser.parse_args()

    manifests = load_manifests(args.manifest_dir)
    v = Validation()
    validate_core_members(
        args.core,
        manifests,
        v,
        args.source_mechanics_dir,
        args.hero_override_dir,
        args.ability_override_dir,
        no_design_debt=True,
    )

    recommendations = args.recommendations.read_text(encoding="utf-8-sig") if args.recommendations.exists() else ""
    if not recommendations:
        v.error(f"missing recommendations document {args.recommendations}")

    unit_total = 0
    hero_total = 0
    building_total = 0
    source_counts: dict[str, int] = {}
    for _path, manifest in manifests:
        if not core_overlay_enabled(manifest):
            continue
        faction_sid = manifest["identity"]["factionSid"]
        for custom_sid in expand_units(manifest):
            unit_total += 1
            if recommendations and custom_sid not in recommendations:
                v.error(f"{faction_sid}:{custom_sid}: recommendations document does not reference live unit SID")
        hero_count = int((manifest.get("heroes") or {}).get("count") or 0)
        for index in range(1, hero_count + 1):
            hero_total += 1
            hero_sid = f"{faction_sid}_hero_{index}"
            if recommendations and hero_sid not in recommendations:
                v.error(f"{faction_sid}:{hero_sid}: recommendations document does not reference live hero SID")
        city_member = (manifest.get("coreOverlay") or {}).get("cityLogic")
        city_doc = read_core_json(args.core, city_member) if isinstance(city_member, str) else None
        if city_doc is not None:
            for item in collect_city_building_config_rows(city_doc):
                if isinstance(item.get("sid"), str) and item["sid"].startswith("Build_"):
                    building_total += 1
                    if recommendations and item["sid"] not in recommendations:
                        v.error(f"{faction_sid}:{item['sid']}: recommendations document does not reference live building SID")
        source_path = args.source_mechanics_dir / f"{faction_sid}.json"
        if source_path.exists():
            doc = json.loads(source_path.read_text(encoding="utf-8-sig"))
            for mechanic in doc.get("mechanics", []) if isinstance(doc, dict) else []:
                if isinstance(mechanic, dict):
                    status = str(mechanic.get("status") or "unknown")
                    source_counts[status] = source_counts.get(status, 0) + 1

    print(f"custom faction design contract: {sum(1 for _p, m in manifests if core_overlay_enabled(m))} factions")
    print(f"units: {unit_total}/{unit_total} covered")
    print(f"heroes: {hero_total}/{hero_total} covered")
    print(f"buildings: {building_total}/{building_total} covered")
    print("source mechanics: " + ", ".join(f"{key}={value}" for key, value in sorted(source_counts.items())))
    print(f"errors: {v.errors}")
    if v.warnings:
        print(f"warnings: {v.warnings}")
    return 1 if v.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
