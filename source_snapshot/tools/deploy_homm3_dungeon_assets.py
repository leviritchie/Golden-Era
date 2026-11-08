#!/usr/bin/env python3
"""Audit the HoMM3 Dungeon plugin payload requirements.

Dungeon does not have checked-in HoMM3 visual payloads yet. This script is a
guardrail so future release work has one Dungeon-owned entry point instead of
silently borrowing native Olden Era Dungeon assets.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "custom_factions" / "homm3_dungeon.json"


def load_manifest() -> dict:
    with MANIFEST.open("r", encoding="utf-8") as f:
        return json.load(f)


def expected_plugin_paths(manifest: dict) -> list[str]:
    faction_sid = manifest["identity"]["factionSid"]
    paths: list[str] = []
    for line in manifest["unitLines"]:
        base_sid = line["baseSid"]
        for suffix in manifest["unitVariants"]:
            sid = base_sid + suffix
            paths.extend(
                [
                    f"homm3_bundles/custom_units_dungeon_{sid}",
                    f"homm3_portraits/{sid}.png",
                    f"homm3_lab/{sid}/extracted_battle",
                    f"homm3_lab/{sid}/extracted_map",
                ]
            )
    paths.extend(
        [
            f"homm3_runtime_assets/faction_icons/{faction_sid}/Icon_Faction_Dungeon.png",
            f"homm3_runtime_assets/town_scene_refs/{faction_sid}/Dungeon-in-background.png",
            f"homm3_runtime_assets/town_scene_refs/{faction_sid}/layers/positions.json",
            f"homm3_runtime_assets/town_scene_refs/{faction_sid}/building_icons/",
            f"homm3_runtime_assets/map_object_refs/{faction_sid}_city/",
            f"homm3_runtime_assets/map_object_refs/{faction_sid}_dwellings/",
        ]
    )
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", type=Path, help="Optional deployed OfflineUnlockMod plugin root to audit.")
    parser.add_argument("--list", action="store_true", help="Print the expected Dungeon payload paths.")
    args = parser.parse_args()

    manifest = load_manifest()
    expected = expected_plugin_paths(manifest)
    if args.list or not args.plugin_root:
        for path in expected:
            print(path)
    if not args.plugin_root:
        print("Dungeon asset deployment is scaffold-only; no files were copied.")
        return 2

    missing = [path for path in expected if not (args.plugin_root / path).exists()]
    for path in missing:
        print(f"MISSING: {args.plugin_root / path}")
    if missing:
        print(f"HoMM3 Dungeon payload incomplete: {len(missing)} missing path(s).")
        return 1
    print("HoMM3 Dungeon payload paths are present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
