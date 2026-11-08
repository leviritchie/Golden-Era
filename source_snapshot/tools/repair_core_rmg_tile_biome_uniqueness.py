#!/usr/bin/env python3
"""Repair Core.zip tile biome-name uniqueness for RMG.

RMG ``bjl..ctor`` builds a name→config dictionary and throws
``ArgumentException: An item with the same key has already been added`` when
``DB/map/tiles/tiles.json`` repeats a biome string. Homecoming water shore tiles
18-22 were installed with five copies of ``biome: "Water"``, which aborts
``blc.GenerateMap``. Retired display-water Sand clones 24-28 create the same
failure mode for ``Sand``.

This tool rewrites the live Core.zip (with a timestamped backup) so:
- tile 18 keeps ``Water``
- tiles 19-22 use unique ``Water Shore {Edge}`` biome names
- retired tiles 24-28 are removed
- every remaining ``biome`` value is unique

Proof boundary: source/static + installed Core.zip rewrite only. Runtime RMG
success remains user-visible gameplay unvalidated until an in-game generate.
"""

from __future__ import annotations

import argparse
import json
import shutil
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_CORE = Path(
    r"V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era"
    r"\HeroesOldenEra_Data\StreamingAssets\Core.zip"
)
TILES_PATH = "DB/map/tiles/tiles.json"
NATIVE_WATER_BIOME_BY_ID = {
    18: "Water",
    19: "Water Shore North",
    20: "Water Shore South",
    21: "Water Shore West",
    22: "Water Shore East",
}
RETIRED_DISPLAY_WATER_TILE_IDS = {24, 25, 26, 27, 28}


class RepairError(RuntimeError):
    pass


def load_tiles(doc: dict[str, Any]) -> list[dict[str, Any]]:
    rows = doc.get("array") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        raise RepairError(f"{TILES_PATH} must contain an array list")
    return rows


def dump_json(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def assert_unique_biomes(rows: list[dict[str, Any]]) -> None:
    biomes = [str(row.get("biome")) for row in rows if isinstance(row, dict)]
    dupes = sorted(name for name, count in Counter(biomes).items() if count > 1)
    if dupes:
        raise RepairError(f"duplicate tile biome name(s) remain: {dupes}")


def repair_tiles_doc(doc: dict[str, Any]) -> dict[str, Any]:
    rows = load_tiles(doc)
    kept: list[dict[str, Any]] = []
    renamed: list[dict[str, Any]] = []
    removed: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            raise RepairError(f"{TILES_PATH} contains a non-object row: {row!r}")
        tile_id = row.get("id")
        if tile_id in RETIRED_DISPLAY_WATER_TILE_IDS:
            removed.append(int(tile_id))
            continue
        if tile_id in NATIVE_WATER_BIOME_BY_ID:
            expected = NATIVE_WATER_BIOME_BY_ID[tile_id]
            if row.get("biome") != expected:
                row = dict(row)
                row["biome"] = expected
                renamed.append({"id": tile_id, "biome": expected})
            if row.get("name") != f"tiles_{tile_id}":
                row = dict(row)
                row["name"] = f"tiles_{tile_id}"
        kept.append(row)
    kept.sort(key=lambda row: int(row["id"]) if isinstance(row.get("id"), int) else 10**9)
    assert_unique_biomes(kept)
    return {
        "doc": {"array": kept},
        "renamed": renamed,
        "removed": sorted(removed),
        "tileCount": len(kept),
    }


def rewrite_core(core_path: Path, *, dry_run: bool) -> dict[str, Any]:
    if not core_path.is_file():
        raise RepairError(f"Core.zip missing: {core_path}")
    with zipfile.ZipFile(core_path, "r") as zin:
        if TILES_PATH not in zin.namelist():
            raise RepairError(f"{TILES_PATH} missing from {core_path}")
        tiles_doc = json.loads(zin.read(TILES_PATH).decode("utf-8-sig"))
        repair = repair_tiles_doc(tiles_doc)
        if dry_run:
            return {
                "core": str(core_path),
                "dryRun": True,
                "renamed": repair["renamed"],
                "removed": repair["removed"],
                "tileCount": repair["tileCount"],
            }
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = core_path.with_name(f"Core.zip.backup-rmg-tile-biome-uniqueness-{stamp}")
        shutil.copy2(core_path, backup)
        tmp = core_path.with_suffix(".zip.tmp-rmg-tile-biome")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                data = zin.read(info.filename)
                if info.filename == TILES_PATH:
                    data = dump_json(repair["doc"])
                # Preserve member metadata where practical.
                out_info = zipfile.ZipInfo(filename=info.filename, date_time=info.date_time)
                out_info.compress_type = zipfile.ZIP_DEFLATED
                out_info.external_attr = info.external_attr
                zout.writestr(out_info, data)
    tmp.replace(core_path)
    return {
        "core": str(core_path),
        "backup": str(backup),
        "dryRun": False,
        "renamed": repair["renamed"],
        "removed": repair["removed"],
        "tileCount": repair["tileCount"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = rewrite_core(args.core.resolve(), dry_run=args.dry_run)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
