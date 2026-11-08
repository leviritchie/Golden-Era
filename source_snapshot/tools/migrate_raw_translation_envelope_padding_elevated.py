#!/usr/bin/env python3
"""Re-paint raw_translation atlas envelope padding as elevated cliffs.

Applies the current pipeline policy
``envelope_padding_elevated_cliffs_surface_land_match_underground_void`` to
existing raw_translation maps without a full re-emit. Strips retired
``homm3_envelope_padding_blocker`` occupancy objects.

Use when a full ``build_campaign_raw_translation_batch`` rebuild is blocked by
unrelated contracts but map edges must leave flat void + rocks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
POC = ROOT / "experiments" / "campaign_port_poc"
RAW = POC / "raw_translation"
APPROACH = POC / "approach_cell"
for path in (APPROACH, RAW, POC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import build_raw_translation_map as raw_builder  # noqa: E402
import layer_atlas as atlas  # noqa: E402
import port_homecoming_poc as poc  # noqa: E402
from campaign_mission import (  # noqa: E402
    default_batch_manifest_path,
    load_batch_manifest,
    mission_by_id,
)
from scenario_profile import load_scenario_profile  # noqa: E402

ENVELOPE_PADDING_BLOCKER_SID = "homm3_envelope_padding_blocker"
TARGET_POLICY = atlas.ENVELOPE_PADDING_VOID_POLICY


def _raw_map_paths(mission_artifact_root: Path, map_sid: str) -> tuple[Path, Path]:
    out_root = mission_artifact_root / "raw_translation_map"
    return out_root / "maps" / f"{map_sid}.map", out_root / "install_manifest.json"


def _strip_padding_blockers(objects: list[dict[str, Any]]) -> int:
    removed = 0
    kept: list[dict[str, Any]] = []
    for group in objects:
        if not isinstance(group, dict):
            continue
        if group.get("sid") == ENVELOPE_PADDING_BLOCKER_SID:
            removed += len(group.get("ids") or [])
            continue
        kept.append(group)
    objects[:] = kept
    return removed


def migrate_mission(profile_path: Path) -> dict[str, Any]:
    profile = load_scenario_profile(profile_path)
    raw_builder.apply_profile_globals(profile)
    map_path, manifest_path = _raw_map_paths(Path(profile.artifact_root), profile.map_sid)
    if not map_path.is_file():
        raise FileNotFoundError(f"missing map {map_path}")
    container = poc.read_olden_map_container(map_path)
    map_data = container.chunks[1]
    if not isinstance(map_data, dict):
        raise ValueError(f"{profile.map_sid}: mapData is not an object")

    size_x = int((container.chunks[0] or {}).get("sizeX") or 0)
    size_z = int((container.chunks[0] or {}).get("sizeZ") or 0)
    if size_x != atlas.OLDEN_WIDTH or size_z != atlas.OLDEN_HEIGHT:
        raise ValueError(
            f"{profile.map_sid}: map size {size_x}x{size_z} != profile atlas "
            f"{atlas.OLDEN_WIDTH}x{atlas.OLDEN_HEIGHT}"
        )

    tiles = list(map_data["tilesMap"])
    levels = list(map_data["levelsMap"])
    climbs = list(map_data["climbsMap"])
    water = list(map_data["waterMap"])
    expected = atlas.OLDEN_WIDTH * atlas.OLDEN_HEIGHT
    if not (len(tiles) == len(levels) == len(climbs) == len(water) == expected):
        raise ValueError(
            f"{profile.map_sid}: terrain array length mismatch "
            f"tiles={len(tiles)} expected={expected}"
        )

    projected = {
        "tilesMap": tiles,
        "levelsMap": levels,
        "climbsMap": climbs,
        "waterMap": water,
    }
    padding = atlas.paint_atlas_envelope_padding_as_void(projected)
    map_data["tilesMap"] = projected["tilesMap"]
    map_data["levelsMap"] = projected["levelsMap"]
    map_data["climbsMap"] = projected["climbsMap"]
    map_data["waterMap"] = projected["waterMap"]

    objects = map_data.get("objects")
    removed_blockers = 0
    if isinstance(objects, list):
        removed_blockers = _strip_padding_blockers(objects)

    map_hash = hashlib.md5(profile.map_sid.encode("utf-8")).hexdigest()
    meta = container.chunks[0]
    if isinstance(meta, dict):
        meta["hashSum"] = map_hash
    poc.write_olden_map_container(map_path, container, map_hash)

    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    padding_out = {
        **padding,
        "blockers": {
            **(padding.get("blockers") or {}),
            "removedStaleGroups": removed_blockers,
            "status": atlas.ENVELOPE_PADDING_BLOCKERS_STATUS,
            "cellCount": 0,
            "sid": ENVELOPE_PADDING_BLOCKER_SID,
        },
        "migration": {
            "tool": "migrate_raw_translation_envelope_padding_elevated.py",
            "fromPolicy": (manifest.get("envelopePaddingVoid") or {}).get("policy"),
            "proofBoundary": "generated_artifact; full raw_translation re-emit may still be pending",
        },
    }
    manifest["envelopePaddingVoid"] = padding_out
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return {
        "mapSid": profile.map_sid,
        "map": str(map_path),
        "policy": padding_out.get("policy"),
        "cellCount": padding_out.get("cellCount"),
        "removedBlockers": removed_blockers,
        "surfaceMatchedCellCount": padding_out.get("surfaceMatchedCellCount"),
        "undergroundVoidCellCount": padding_out.get("undergroundVoidCellCount"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=None, help="Batch manifest to migrate.")
    parser.add_argument("--mission", action="append", dest="missions", help="missionId filter.")
    parser.add_argument(
        "--all-flat-void",
        action="store_true",
        help="Migrate every raw_translation install_manifest still on flat_void policy.",
    )
    parser.add_argument(
        "--only-if-flat-void",
        action="store_true",
        help="Skip missions already on elevated-cliff policy.",
    )
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    if args.all_flat_void:
        for man_path in sorted(Path("artifacts/campaign_port_poc").rglob("install_manifest.json")):
            if "raw_translation_map" not in man_path.parts:
                continue
            data = json.loads(man_path.read_text(encoding="utf-8"))
            policy = (data.get("envelopePaddingVoid") or {}).get("policy")
            if policy == TARGET_POLICY:
                continue
            if policy != "envelope_padding_flat_void_black_blocked" and args.only_if_flat_void:
                continue
            # Derive profile from mapSid / artifact root
            artifact_root = man_path.parent.parent
            map_sid = data.get("mapSid")
            scenario_id = data.get("scenarioId")
            profile_candidates = []
            if scenario_id:
                profile_candidates.append(ROOT / "scenarios" / str(scenario_id) / "raw_translation.profile.json")
            # Fallback: scan scenarios for matching mapSid
            if not profile_candidates or not profile_candidates[0].is_file():
                for profile_path in (ROOT / "scenarios").glob("*/raw_translation.profile.json"):
                    try:
                        prof = json.loads(profile_path.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    if prof.get("mapSid") == map_sid:
                        profile_candidates = [profile_path]
                        break
            if not profile_candidates or not profile_candidates[0].is_file():
                failures.append(
                    {
                        "artifact": str(artifact_root),
                        "mapSid": map_sid,
                        "error": "no raw_translation.profile.json",
                    }
                )
                continue
            try:
                results.append(migrate_mission(profile_candidates[0]))
                print(f"migrated {map_sid} -> {TARGET_POLICY}")
            except Exception as exc:
                failures.append(
                    {"mapSid": map_sid, "error": f"{type(exc).__name__}: {exc}"}
                )
                print(f"FAILED {map_sid}: {type(exc).__name__}: {exc}")
    else:
        manifest_path = (args.manifest or default_batch_manifest_path()).resolve()
        batch = load_batch_manifest(manifest_path)
        selected = list(args.missions) if args.missions else [m.mission_id for m in batch.missions]
        for mission_id in selected:
            mission = mission_by_id(batch, mission_id)
            profile_path = ROOT / "scenarios" / mission.scenario_id / "raw_translation.profile.json"
            man_path = Path(mission.artifact_root) / "raw_translation_map" / "install_manifest.json"
            if args.only_if_flat_void and man_path.is_file():
                data = json.loads(man_path.read_text(encoding="utf-8"))
                if (data.get("envelopePaddingVoid") or {}).get("policy") == TARGET_POLICY:
                    print(f"skip {mission_id}: already elevated")
                    continue
            try:
                results.append(migrate_mission(profile_path))
                print(f"migrated {mission_id}")
            except Exception as exc:
                failures.append(
                    {"missionId": mission_id, "error": f"{type(exc).__name__}: {exc}"}
                )
                print(f"FAILED {mission_id}: {type(exc).__name__}: {exc}")

    print(json.dumps({"ok": not failures, "migrated": results, "failures": failures}, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
