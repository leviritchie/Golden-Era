#!/usr/bin/env python3
"""Per-model front axis for the adventure-map building meshes (map_building_facing.json).

The runtime (Homm3MapBuildingMeshBundle.OrientToBillboardArtAndSeat) turns every prefab by a fixed 180 deg,
which faces a glTF +Z front at the camera. Meshy does not guarantee +Z: the 2026-09-11 Meshy-7 regens of the
Castle capitol and the Stronghold city came back with their gate on -Z, so the town stood backwards.
A -Z model gets catalog ``artYawDegrees`` 180; every other model gets 0. Meshy can also put the front on a
side axis (the 2026-09-11 Necropolis capitol has its gate and road on glTF +X, so with only +Z/-Z on offer it
was recorded +Z and stood turned 90 deg, user playthrough reported 2026-10-03). glTFast imports glTF -> Unity by negating X
(checked on the staged bundle: the Necropolis mesh AABB x range is mirrored, z unchanged), so glTF +X lands on
Unity -X and needs a further +90 deg (Unity yaw 270) to reach the camera; glTF -X needs -90 deg. This module is the one place that
maps the census to the catalog field; the bundle builder stamps with it and the contract validator checks with it.

    python tools/homm3_map_building_meshes/map_building_facing.py stamp [catalog.json]

restamps a catalog in place (the staged one by default) without a Unity rebuild; the bundle carries no yaw.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACING = Path(__file__).resolve().with_name("map_building_facing.json")
SCHEMA = "homm3_map_building_facing.v1"
STAGED_CATALOG = (ROOT / "Heroes of Might & Magic Olden Era Playtest" / "OfflineUnlockMod"
                  / "homm3_map_building_meshes" / "catalog.json")
ART_YAW_BY_AXIS = {"+Z": 0.0, "-Z": 180.0, "+X": 90.0, "-X": -90.0}


class FacingError(RuntimeError):
    pass


def load_facing(path: Path = FACING) -> dict[str, dict]:
    if not path.is_file():
        raise FacingError(f"facing census missing: {path}")
    doc = json.loads(path.read_text(encoding="utf-8"))
    if doc.get("schema") != SCHEMA:
        raise FacingError(f"{path}: schema {doc.get('schema')!r}, expected {SCHEMA}")
    models = doc.get("models") or {}
    for key, row in models.items():
        if row.get("frontAxis") not in ART_YAW_BY_AXIS:
            raise FacingError(f"{path}: {key} frontAxis {row.get('frontAxis')!r} not in {sorted(ART_YAW_BY_AXIS)}")
        if not isinstance(row.get("glbBytes"), int) or row["glbBytes"] <= 0:
            raise FacingError(f"{path}: {key} glbBytes missing")
        if row["frontAxis"] != "+Z" and not row.get("evidence"):
            raise FacingError(f"{path}: {key} is {row['frontAxis']} without evidence")
    return models


def expected_art_yaw(entry: dict, models: dict[str, dict]) -> float:
    key = entry.get("prefabKey") or ""
    row = models.get(key)
    if row is None:
        raise FacingError(f"{key}: not in the facing census {FACING.name}; inspect its +Z/-Z views and add it")
    yaw = ART_YAW_BY_AXIS[row["frontAxis"]]
    if yaw != 0.0 and (entry.get("animLane") or entry.get("animAnchorPaths") or entry.get("animRotorPaths")
                       or entry.get("animPartPaths")):
        # map_building_anim.py measures anchors on the +Z view and bakes them under the 180 deg front yaw only.
        raise FacingError(f"{key}: {row['frontAxis']} front with animation lane {entry.get('animLane')!r}; "
                          "map_building_anim assumes a +Z front")
    return yaw


def stamp_catalog(catalog: dict, models: dict[str, dict]) -> int:
    turned = 0
    for entry in catalog.get("entries") or []:
        yaw = expected_art_yaw(entry, models)
        entry["artYawDegrees"] = yaw
        turned += yaw != 0.0
    return turned


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "stamp":
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(argv[1]) if len(argv) > 1 else STAGED_CATALOG
    catalog = json.loads(path.read_text(encoding="utf-8"))
    try:
        turned = stamp_catalog(catalog, load_facing())
    except FacingError as ex:
        print(f"map-building-facing: {ex}", file=sys.stderr)
        return 1
    path.write_text(json.dumps(catalog, indent=4) + "\n", encoding="utf-8")
    print(f"stamped artYawDegrees on {len(catalog.get('entries') or [])} entries ({turned} turned off +Z) -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
