#!/usr/bin/env python3
"""Validate campaign raw_translation water traversal profile resolution."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_REL = Path("Heroes of Might & Magic Olden Era Playtest") / "OfflineUnlockMod"
# raw_translation is the only campaign map generation lane; retired suffixes stay listed
# so a historical mapSid still resolves a profile instead of silently missing one.
CAMPAIGN_LANE_SUFFIXES = ("_raw_translation", "_layered_atlas", "_approach_cell")


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def read_text(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"missing required file: {path}")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def validate_runtime_source(repo: Path, errors: list[str]) -> None:
    profile_path = repo / PLUGIN_REL / "HomecomingMapProfile.cs"
    text = read_text(profile_path)
    require("TryResolve(string fileMapName, object mapData, out HomecomingMapProfile profile)" in text,
            "HomecomingMapProfile must expose map-aware TryResolve overload", errors)
    require("IsCampaignWaterLaneMapSid" in text,
            "HomecomingMapProfile must classify campaign water lane map SIDs", errors)
    for suffix in CAMPAIGN_LANE_SUFFIXES:
        require(suffix in text, f"HomecomingMapProfile must list campaign lane suffix {suffix}", errors)
    require("TryBuildCampaignSurfaceProfile" in text,
            "HomecomingMapProfile must derive surface bounds from map views", errors)
    require("ViewSectionSize = 16" in text,
            "HomecomingMapProfile must use 16-cell view sections", errors)

    for bridge in (
        "Homm3HomecomingWaterTraversalBridge.cs",
        "Homm3HomecomingNativeWaterMeshBridge.cs",
        "Homm3HomecomingWaterPresentationOverlay.cs",
    ):
        bridge_text = read_text(repo / PLUGIN_REL / bridge)
        require("TryResolve(fileMapName, mapData, out" in bridge_text,
                f"{bridge} must use map-aware HomecomingMapProfile.TryResolve", errors)


def validate_campaign_manifests(repo: Path, errors: list[str]) -> None:
    roots = [
        repo / "artifacts" / "campaign_port_poc" / "roe_castle_campaign",
        repo / "artifacts" / "campaign_port_poc" / "roe_remaining_campaigns",
        repo / "artifacts" / "campaign_port_poc" / "ab_sod_campaigns",
        repo / "artifacts" / "campaign_port_poc" / "homecoming_poc",
    ]
    sys.path.insert(0, str(repo / "experiments" / "campaign_port_poc"))
    import port_homecoming_poc as poc  # noqa: E402
    import campaign_ocean  # noqa: E402

    checked = 0
    for root in roots:
        if not root.is_dir():
            continue
        for manifest_path in sorted(root.glob("**/raw_translation_map/install_manifest.json")):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            map_sid = manifest.get("mapSid")
            if not isinstance(map_sid, str) or not map_sid.endswith("_raw_translation"):
                continue
            runtime_water = manifest.get("runtimeWaterProfile") or {}
            require(runtime_water.get("profileResolver") == "HomecomingMapProfile",
                    f"{manifest_path}: runtimeWaterProfile.profileResolver must be HomecomingMapProfile", errors)
            require(runtime_water.get("mapSid") == map_sid,
                    f"{manifest_path}: runtimeWaterProfile.mapSid mismatch", errors)

            map_rel = (manifest.get("output") or {}).get("map")
            if not isinstance(map_rel, str):
                continue
            map_path = (repo / map_rel).resolve()
            if not map_path.is_file():
                continue
            container = poc.read_olden_map_container(map_path)
            map_data = container.chunks[1]
            # Fail closed on every raw_translation map: retired Golden Era ocean ids (tiles
            # 18-22, waterMap 18) or a waterMap 2 cell off the Sand seabed / basin level.
            for err in campaign_ocean.map_ocean_errors(map_data, label=map_sid):
                errors.append(err)
            ocean_nodes = campaign_ocean.ocean_cell_count(map_data)
            if ocean_nodes <= 0:
                continue
            views = map_data.get("views") or []
            require(isinstance(views, list) and len(views) >= 1,
                    f"{map_sid}: water-bearing map must expose at least one view for runtime profile bounds", errors)
            surface_views = [v for v in views if isinstance(v, dict) and not v.get("isUnderground")]
            require(surface_views,
                    f"{map_sid}: water-bearing map must expose a surface view", errors)
            checked += 1

    require(checked >= 3,
            f"expected at least 3 water-bearing campaign raw_translation maps; checked {checked}", errors)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    repo = Path(args.repo_root).resolve()
    errors: list[str] = []
    validate_runtime_source(repo, errors)
    validate_campaign_manifests(repo, errors)
    if errors:
        for err in errors:
            print(f"ERROR: {err}", file=sys.stderr)
        return 1
    print("Campaign water traversal profile contract OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
