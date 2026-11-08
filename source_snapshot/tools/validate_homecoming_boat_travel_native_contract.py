#!/usr/bin/env python3
"""Validate that Homecoming native water traversal uses WaterTraversalBridge, not retired direct-state paths."""

from __future__ import annotations

import argparse
from pathlib import Path


PLUGIN_REL = Path("Heroes of Might & Magic Olden Era Playtest") / "OfflineUnlockMod"
RETIRED_RUNTIME_FLAGS = [
    "homm3_homecoming_playable_shell_launch.flag",
    "homm3_homecoming_boat_travel_native_proof.flag",
    "homm3_homecoming_quickstart_state_probe.flag",
]
RETIRED_WORKBENCH_TOKENS = [
    "homecoming_water_traversal_state",
    "homecoming_water_traversal_apply",
    "Homm3HomecomingWaterTraversalBridge.TryDescribeStateForBridge",
    "Homm3HomecomingWaterTraversalBridge.TryApplyForBridge",
    "CapabilityJson(\"homecoming_water_traversal_apply\"",
]
REQUIRED_PLUGIN_TOKENS = [
    "Homm3HomecomingWaterTraversalBridge.RegisterRequiredReleaseSafeSlice(_harmony, Log);",
]


def read(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"missing required file: {path}")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def validate_runtime_source(repo: Path) -> None:
    plugin_dir = repo / PLUGIN_REL
    plugin_text = read(plugin_dir / "Plugin.cs")
    runtime_text = read(plugin_dir / "Homm3HomecomingBoatTravelNativeProof.cs")
    visual_text = read(plugin_dir / "Homm3HomecomingBoatVisualProof.cs")
    workbench_text = read(plugin_dir / "Homm3LiveProbeWorkbench.cs")
    symbols_text = read(plugin_dir / "GameSymbols.cs")

    require("Retired Homecoming direct-state boat/water runtime" in runtime_text,
            "Homecoming boat-travel runtime must remain a retired marker class")
    require("Retired standalone Homecoming boat visual proof" in visual_text,
            "Homecoming boat visual proof must remain a retired marker class")
    for token in [
        "Homm3HomecomingBoatTravelNativeProof.TryRegister(_harmony, Log);",
        "Homm3HomecomingBoatVisualProof.TryRegister(_harmony, Log);",
        "Homm3HomecomingWaterOverlayRuntime.TryRegister",
    ]:
        require(token not in plugin_text,
                f"Homecoming native water must not register retired overlay/direct-state path: {token}")
    for token in REQUIRED_PLUGIN_TOKENS:
        require(token in plugin_text,
                f"Plugin.cs must register active Homecoming water traversal bridge: {token}")

    for flag_name in RETIRED_RUNTIME_FLAGS:
        require(not (plugin_dir / flag_name).exists(),
                f"diagnostic/runtime flag must not be present in source plugin baseline: {flag_name}")
    for token in RETIRED_WORKBENCH_TOKENS:
        require(token not in workbench_text,
                f"live probe workbench must not expose retired direct-state water traversal command: {token}")
    for forbidden in [
        "TrySetHomecomingOceanTravelBoatVisual",
        "homm3_homecoming_ocean_travel_boat_visual",
        "runtimeAdjacentEntryWaterTravelProven=true",
        "direct-state ocean-travel",
        "current direct-state ocean travel path",
    ]:
        require(forbidden not in symbols_text + runtime_text + visual_text,
                f"retired Homecoming water traversal proof language or active token remains: {forbidden}")

    profile_text = read(plugin_dir / "HomecomingMapProfile.cs")
    require(
        'ApproachCellMapSid = "h3_roe_castle_homecoming_approach_cell"' in symbols_text,
        "GameSymbols must define ApproachCellMapSid for approach_cell water bridges",
    )
    require(
        "ApproachCell.MapSid" in profile_text and "approach_cell_surface" in profile_text,
        "HomecomingMapProfile must resolve approach_cell SID for water traversal",
    )
    require(
        "IsCampaignWaterLaneMapSid" in profile_text,
        "HomecomingMapProfile must classify campaign water lane map SIDs",
    )
    require(
        "TryResolve(string fileMapName, object mapData, out HomecomingMapProfile profile)" in profile_text,
        "HomecomingMapProfile must expose map-aware TryResolve for campaign maps",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=".")
    args = parser.parse_args()
    validate_runtime_source(Path(args.repo_root).resolve())
    print("Homecoming native water traversal bridge contract OK")


if __name__ == "__main__":
    main()
