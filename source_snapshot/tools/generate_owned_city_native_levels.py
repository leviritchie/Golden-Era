#!/usr/bin/env python3
"""Generate Castle-clipped nativeLevels for owned cityFactory world presentation.

Route A may keep a full HotA `levels` inventory. The cityFactory compositor joins only
`nativeLevels`: donor-graph levels that exist as Castle BhBuilding variants.
Fail closed when a required SID cannot be mapped to a positions layer id.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TOWN_REFS = (
    ROOT
    / "Heroes of Might & Magic Olden Era Playtest"
    / "OfflineUnlockMod"
    / "homm3_runtime_assets"
    / "town_scene_refs"
)

# Matches tools/build_hota_factory_bulwark_runtime_assets.py and Factory C# BuildingSidBySceneSlot.
NATIVE_LEVEL_SOURCE_BY_SID: dict[str, dict[int, int]] = {
    "Build_Main": {1: 1, 2: 2, 3: 3},
    "Build_Wall": {1: 1, 2: 2, 3: 3},
    "Build_Magic_Guild": {1: 1, 2: 2, 3: 3, 4: 4},
    "Build_Artifact_Market": {1: 1},
    "Build_Golden_Calf": {1: 1},
    "Build_Tavern": {1: 1},
    "Build_Treasury": {1: 1},
    "Build_Bank": {1: 1},
    "Build_Market": {1: 1},
    "Build_Resource_Depot": {1: 1},
    "Build_Resource_Depot_level_2": {1: 1},
    **{f"Build_Tier_{i}": {1: 1, 2: 2} for i in range(1, 8)},
}

REQUIRED_SIDS = tuple(NATIVE_LEVEL_SOURCE_BY_SID.keys())

# Per-faction product choice, declared in building_layer_map.json:
#   "nativeLevelSourceOverrides": {"Build_Main": {"3": 4}}
# means native level 3 shows the faction's HotA level-4 layer (Conflux: OE's third town-hall level
# shows the capitol, which is also the meshed hall). Every layer an override displaces from nativeLevels
# must be recorded in "unusedLayers" ({layerId: reason}) or generation fails, so no layer silently
# drops out of reach. tools/validate_town_scene3d_contract.py checks the result for scene3d factions.
OVERRIDES_KEY = "nativeLevelSourceOverrides"
UNUSED_KEY = "unusedLayers"


def source_maps_for(layer_map: dict[str, Any], faction: str) -> dict[str, dict[int, int]]:
    overrides = layer_map.get(OVERRIDES_KEY) or {}
    if not isinstance(overrides, dict):
        raise SystemExit(f"{faction}: {OVERRIDES_KEY} must be an object")
    merged = {sid: dict(levels) for sid, levels in NATIVE_LEVEL_SOURCE_BY_SID.items()}
    for sid, levels in overrides.items():
        if sid not in merged or not isinstance(levels, dict) or not levels:
            raise SystemExit(f"{faction}: {OVERRIDES_KEY}.{sid} must name a native SID with a non-empty object")
        for native_level, source_level in levels.items():
            if int(native_level) not in merged[sid] or not isinstance(source_level, int) or source_level < 1:
                raise SystemExit(
                    f"{faction}: {OVERRIDES_KEY}.{sid}.{native_level} must override an existing native level "
                    f"with a positive HotA source level"
                )
            merged[sid][int(native_level)] = source_level
    return merged


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def position_layer_ids(positions: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = positions.get("layers") or []
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("id"), str) and row["id"].strip():
            by_id[row["id"]] = row
    return by_id


def pick_grail_layer(by_id: dict[str, dict[str, Any]], building_ids: dict[str, str]) -> str | None:
    if "Build_Golden_Calf" in building_ids:
        return building_ids["Build_Golden_Calf"]
    for layer_id, row in by_id.items():
        structure = str(row.get("structure") or "").lower()
        lid = layer_id.lower()
        if "grail" in structure or "holy" in lid or "grail" in lid:
            return layer_id
    return None


def resolve_layer_id(layer_id: str, by_id: dict[str, dict[str, Any]]) -> str | None:
    if layer_id in by_id:
        return layer_id
    # Stronghold-style base id with leveled position rows (extraCapitol_1..).
    leveled = [f"{layer_id}_{n}" for n in range(1, 9) if f"{layer_id}_{n}" in by_id]
    if leveled:
        return leveled[0]
    return None


def expand_levels_from_prefix(prefix: str, by_id: dict[str, dict[str, Any]]) -> dict[int, str]:
    """Map HotA layer IDs under a buildingLayerIds prefix.

    HoMM3 town DEFs use the bare prefix as Village Hall / base tier (level 1) and
    ``prefix_2``.. for upgrades. Treating only ``prefix_N`` as leveled rows left
    level 1 unmapped whenever ``prefix_1`` was absent, which black-screened
    owned cityFactory towns on first enter (Necropolis/Dungeon/Tower/Fortress).
    """
    found: dict[int, str] = {}
    if prefix in by_id:
        found[1] = prefix
    for n in range(1, 9):
        candidate = f"{prefix}_{n}"
        if candidate in by_id:
            found[n] = candidate
    return found


def clip_from_building_ids(
    building_ids: dict[str, str],
    by_id: dict[str, dict[str, Any]],
    source_maps: dict[str, dict[int, int]] = NATIVE_LEVEL_SOURCE_BY_SID,
) -> dict[str, dict[str, str]]:
    native: dict[str, dict[str, str]] = {}
    for sid, source_map in source_maps.items():
        layer = building_ids.get(sid)
        if not isinstance(layer, str) or not layer.strip():
            continue
        resolved = resolve_layer_id(layer, by_id)
        if resolved is None:
            raise SystemExit(f"{sid} buildingLayerIds maps to unknown layer {layer!r}")

        # Prefer explicit leveled rows under the base prefix when present.
        leveled = expand_levels_from_prefix(layer, by_id)
        clipped: dict[str, str] = {}
        if leveled:
            for native_level, source_level in source_map.items():
                token = leveled.get(source_level)
                if token is None:
                    continue
                clipped[str(native_level)] = token
        if not clipped:
            clipped["1"] = resolved
        native[sid] = clipped
    return native


def clip_from_levels(
    levels: dict[str, Any],
    by_id: dict[str, dict[str, Any]],
    source_maps: dict[str, dict[int, int]] = NATIVE_LEVEL_SOURCE_BY_SID,
) -> dict[str, dict[str, str]]:
    native: dict[str, dict[str, str]] = {}
    for sid, source_map in source_maps.items():
        raw = levels.get(sid)
        if not isinstance(raw, dict):
            continue
        clipped: dict[str, str] = {}
        for native_level, source_level in source_map.items():
            token = raw.get(str(source_level))
            if not isinstance(token, str) or not token.strip():
                continue
            resolved = resolve_layer_id(token, by_id)
            if resolved is None:
                raise SystemExit(f"{sid} level {native_level} maps to unknown layer {token!r}")
            clipped[str(native_level)] = resolved
        if clipped:
            native[sid] = clipped
    return native


def ensure_faction(faction_dir: Path, *, check_only: bool) -> list[str]:
    notes: list[str] = []
    map_path = faction_dir / "layers" / "building_layer_map.json"
    positions_path = faction_dir / "layers" / "positions.json"
    if not map_path.is_file() or not positions_path.is_file():
        raise SystemExit(f"{faction_dir.name}: missing layers map/positions")

    layer_map = load_json(map_path)
    positions = load_json(positions_path)
    by_id = position_layer_ids(positions)
    building_ids = layer_map.get("buildingLayerIds") or {}
    if not isinstance(building_ids, dict):
        raise SystemExit(f"{faction_dir.name}: buildingLayerIds must be an object")

    source_maps = source_maps_for(layer_map, faction_dir.name)
    levels = layer_map.get("levels")
    if isinstance(levels, dict) and levels:
        native = clip_from_levels(levels, by_id, source_maps)
        notes.append("clipped from levels")
    else:
        native = {}
        notes.append("no levels inventory")

    id_seed = clip_from_building_ids(
        {k: str(v) for k, v in building_ids.items() if isinstance(v, str)},
        by_id,
        source_maps,
    )
    filled = 0
    for sid, level_map in id_seed.items():
        if sid not in native:
            native[sid] = level_map
            filled += 1
        else:
            # Fill missing native levels from buildingLayerIds level-1 only when levels lacked them.
            for level_key, layer in level_map.items():
                if level_key not in native[sid]:
                    native[sid][level_key] = layer
                    filled += 1
    if filled:
        notes.append(f"filled {filled} from buildingLayerIds")

    if "Build_Golden_Calf" not in native:
        grail = pick_grail_layer(by_id, {k: str(v) for k, v in building_ids.items() if isinstance(v, str)})
        if grail is None:
            raise SystemExit(
                f"{faction_dir.name}: cannot map Build_Golden_Calf; add a grail/holy layer or explicit binding"
            )
        native["Build_Golden_Calf"] = {"1": grail}
        notes.append(f"Golden_Calf <- {grail}")

    missing = [sid for sid in REQUIRED_SIDS if sid not in native]
    if missing:
        raise SystemExit(f"{faction_dir.name}: nativeLevels missing required SIDs: {', '.join(missing)}")

    unused = layer_map.get(UNUSED_KEY) or {}
    if not isinstance(unused, dict) or not all(isinstance(v, str) and v.strip() for v in unused.values()):
        raise SystemExit(f"{faction_dir.name}: {UNUSED_KEY} must map layerId -> non-empty reason")
    if source_maps != NATIVE_LEVEL_SOURCE_BY_SID:
        default_native = (
            clip_from_levels(levels, by_id) if isinstance(levels, dict) and levels else {}
        )
        for sid, level_map in clip_from_building_ids(
            {k: str(v) for k, v in building_ids.items() if isinstance(v, str)}, by_id
        ).items():
            for level_key, layer in level_map.items():
                default_native.setdefault(sid, {}).setdefault(level_key, layer)
        reached = {layer for level_map in native.values() for layer in level_map.values()}
        displaced = sorted(
            {layer for level_map in default_native.values() for layer in level_map.values()} - reached
        )
        unrecorded = [layer for layer in displaced if layer not in unused]
        if unrecorded:
            raise SystemExit(
                f"{faction_dir.name}: {OVERRIDES_KEY} displaces {', '.join(unrecorded)} from nativeLevels; "
                f"record each in {UNUSED_KEY} with a reason"
            )
        notes.append(f"overrides {layer_map[OVERRIDES_KEY]} displace {displaced}")
    still_reached = sorted(
        layer for layer in unused if any(layer in level_map.values() for level_map in native.values())
    )
    if still_reached:
        raise SystemExit(f"{faction_dir.name}: {UNUSED_KEY} lists layers nativeLevels still reaches: {still_reached}")

    existing = layer_map.get("nativeLevels")
    if existing == native:
        notes.append("unchanged")
        return notes

    if check_only:
        raise SystemExit(f"{faction_dir.name}: nativeLevels would change (run without --check)")

    layer_map["nativeLevels"] = native
    layer_map["runtimeStatus"] = (
        "source/static validated; nativeLevels clipped for cityFactory Castle-parity compositor"
    )
    write_json(map_path, layer_map)
    notes.append("wrote nativeLevels")
    return notes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if any faction needs writes")
    parser.add_argument(
        "--faction",
        action="append",
        default=[],
        help="Limit to one or more faction folder names (e.g. homm3_castle)",
    )
    args = parser.parse_args()

    factions = sorted(
        p for p in TOWN_REFS.glob("homm3_*") if p.is_dir() and (p / "layers" / "building_layer_map.json").is_file()
    )
    if args.faction:
        wanted = set(args.faction)
        factions = [p for p in factions if p.name in wanted]
        missing = wanted - {p.name for p in factions}
        if missing:
            raise SystemExit(f"unknown faction(s): {', '.join(sorted(missing))}")

    for faction_dir in factions:
        notes = ensure_faction(faction_dir, check_only=args.check)
        print(f"OK {faction_dir.name}: {'; '.join(notes)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
