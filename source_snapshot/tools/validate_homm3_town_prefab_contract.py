#!/usr/bin/env python3
"""Validate HoMM3 town layer metadata against the prefab payload contract."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sanitize_layer_id(layer_id: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in layer_id) or "unknown"


def generated_object_name(layer_id: str, level: int) -> str:
    return f"OfflineUnlockStrongholdTownLayer_{sanitize_layer_id(layer_id)}_{level}"


def resolve_placement(placements: dict[str, Any], layer_id: str, level: int) -> Any | None:
    for candidate in (f"{layer_id}_{level}", f"{layer_id}_lvl{level}", layer_id):
        if candidate in placements:
            return placements[candidate]
    return None


def iter_expected_layers(plugin_root: Path):
    town_root = plugin_root / "homm3_runtime_assets" / "town_scene_refs"
    if not town_root.is_dir():
        raise FileNotFoundError(f"Missing town runtime asset root: {town_root}")

    for faction_dir in sorted(town_root.glob("homm3_*")):
        layers_dir = faction_dir / "layers"
        positions_path = layers_dir / "positions.json"
        map_path = layers_dir / "building_layer_map.json"
        if not positions_path.is_file() or not map_path.is_file():
            raise FileNotFoundError(f"Missing town metadata for {faction_dir.name}")

        positions = load_json(positions_path)
        mappings = load_json(map_path)
        placements = {
            str(row.get("id")): row
            for row in positions.get("layers", [])
            if isinstance(row, dict) and row.get("id")
        }
        expected = set()
        for _building_sid, levels in (mappings.get("levels") or {}).items():
            if not isinstance(levels, dict):
                continue
            for level_text, layer_id in levels.items():
                expected.add((str(layer_id), int(level_text)))
        mapped_with_levels = set((mappings.get("levels") or {}).keys())
        for building_sid, layer_id in (mappings.get("buildingLayerIds") or {}).items():
            if building_sid not in mapped_with_levels:
                expected.add((str(layer_id), 1))

        for layer_id, level in sorted(expected):
            placement = resolve_placement(placements, layer_id, level)
            if placement is None:
                raise AssertionError(f"{faction_dir.name}: mapped layer {layer_id} level {level} has no placement row")
            sprite = placement.get("sprite")
            if not isinstance(sprite, str) or not sprite.strip():
                raise AssertionError(f"{faction_dir.name}: mapped layer {layer_id} level {level} has no explicit sprite")
            sprite_path = layers_dir / sprite
            if not sprite_path.is_file():
                raise AssertionError(f"{faction_dir.name}: mapped layer {layer_id} level {level} sprite is missing: {sprite}")
            yield faction_dir.name, layer_id, level, str(sprite), generated_object_name(layer_id, level)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plugin-root", required=True, help="OfflineUnlockMod plugin payload root to validate.")
    parser.add_argument(
        "--skip-bundle",
        action="store_true",
        help="Validate source metadata only. Build/deploy validation must not use this.",
    )
    args = parser.parse_args()

    plugin_root = Path(args.plugin_root).resolve()
    expected = list(iter_expected_layers(plugin_root))
    if not expected:
        raise AssertionError("No HoMM3 town prefab layer expectations were found")

    if not args.skip_bundle:
        bundle_path = plugin_root / "homm3_town_prefabs" / "homm3_town_prefabs"
        manifest_path = plugin_root / "homm3_town_prefabs" / "Homm3TownPrefabBuildManifest.tsv"
        if not bundle_path.is_file():
            raise FileNotFoundError(f"Missing town prefab bundle: {bundle_path}")
        if not manifest_path.is_file():
            raise FileNotFoundError(f"Missing town prefab build manifest: {manifest_path}")

        manifest_rows = set()
        for line_number, line in enumerate(manifest_path.read_text(encoding="utf-8-sig").splitlines(), start=1):
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                raise AssertionError(f"Invalid town prefab manifest row {line_number}: {line}")
            manifest_rows.add((parts[0], parts[1], parts[2].replace("\\", "/")))

        missing_manifest_rows = []
        for faction, layer_id, level, sprite, object_name in expected:
            expected_texture_path = f"Assets/Generated/Homm3TownPrefabTextures/{faction}/{sprite}"
            if (faction, object_name, expected_texture_path) not in manifest_rows:
                missing_manifest_rows.append(f"{faction}:{layer_id}:{level}:{object_name}:{expected_texture_path}")
        if missing_manifest_rows:
            raise AssertionError(
                "Town prefab build manifest is missing layer row(s):\n" + "\n".join(missing_manifest_rows)
            )

    print(f"validated HoMM3 town prefab contract: {len(expected)} mapped layer entries under {plugin_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())