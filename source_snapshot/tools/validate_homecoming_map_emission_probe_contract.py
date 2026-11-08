#!/usr/bin/env python3
"""Validate the Homecoming map-emission feasibility probe contract."""

from __future__ import annotations

import argparse
from pathlib import Path


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-dir", default="Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod")
    args = parser.parse_args()
    plugin_dir = Path(args.plugin_dir)
    source_path = plugin_dir / "Homm3HomecomingMapEmissionFeasibilityProbe.cs"
    plugin_path = plugin_dir / "Plugin.cs"
    errors: list[str] = []
    if not source_path.exists():
        errors.append(f"missing probe source: {source_path}")
    if not plugin_path.exists():
        errors.append(f"missing Plugin.cs: {plugin_path}")
    if errors:
        print("Homecoming map-emission feasibility probe validation failed:")
        for error in errors:
            print(f" - {error}")
        return 1

    source = source_path.read_text(encoding="utf-8")
    plugin = plugin_path.read_text(encoding="utf-8")
    require('DiagnosticFlag = "homm3_homecoming_map_emission_feasibility_probe.flag"' in source, "missing exact diagnostic flag", errors)
    require('LogPrefix = "HOMM3_HOMECOMING_MAP_EMISSION_FEASIBILITY_PROBE"' in source, "missing exact log prefix", errors)
    require('GameMember.FindPlacedObjectType(' in source, "probe must use central placed-object type resolver", errors)
    require('GameMember.FindPlacedObjectInitMethods(objectType, metaType)' in source, "probe must use central placed-object init resolver", errors)
    require('Homm3MapObjectPropCityResolver.ResolveObjectsProperties(map)' in source, "probe must inspect map ObjectsProperties", errors)
    require('DiscoverPlacedObjectMutators(map, __instance?.GetType())' in source, "probe must report mutator discovery", errors)
    require('nativeMapMutation=false' in source, "probe must log that it does not mutate native map state", errors)
    require('playable=false' in source, "probe must log that this is not a playable map emitter", errors)
    require('NoInsertionSurfaceBlocker = "no_runtime_placed_object_insertion_surface"' in source, "probe must fail closed when no insertion surface is present", errors)
    require('CandidateMutatorBlocker = "candidate_mutator_requires_separate_safe_insertion_proof"' in source, "probe must require separate proof for candidate mutators", errors)
    call = 'Homm3HomecomingMapEmissionFeasibilityProbe.TryRegister(_harmony, Log);'
    harmony = '_harmony = new Harmony(PluginGuid);'
    release_gate = 'if (cfg.ReleaseSafeProfile && cfg.Homm3ImportEnabled && cfg.Homm3ReleaseSafeUiMapTown)'
    require(call in plugin, "Plugin.cs must register the map-emission feasibility probe", errors)
    if call in plugin and harmony in plugin and release_gate in plugin:
        require(plugin.index(harmony) < plugin.index(call) < plugin.index(release_gate), "probe registration must be reachable by flag before release-safe profile gates", errors)

    forbidden_tokens = [
        '.AddComponent<',
        'new GameObject',
        'Activator.CreateInstance',
        '.Invoke(',
        '.SetValue(',
        '.Remove(',
        'Destroy(',
        'DestroyImmediate(',
    ]
    for token in forbidden_tokens:
        require(token not in source, f"forbidden mutation/fallback token present: {token}", errors)

    if errors:
        print("Homecoming map-emission feasibility probe validation failed:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("Homecoming map-emission feasibility probe validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())