# RMG Hybrid Scenario

Status: source/static bridge architecture implemented; runtime capture and patched-scenario output remain unvalidated. The July 9 `Map.ohc(MapData)` failure is the last recorded runtime blocker, not a confirmed-current result.

## Goal

Use native RMG for zone graph, guarded corridors, and towns, then graft scenario events onto an exported native map. Do not replace native generation with another custom topology engine.

## Current Capture Architecture

`Homm3RmgMapCaptureBridge` is no longer a Map.Init-only hook. The current source combines:

1. RMG terrain-biome sanitization before generation.
2. Capture arming from map initialization.
3. Renderer prepare-map observation.
4. Explicit Map-to-MapData synchronization attempts.
5. Deferred host/world polling until serializable map data is available.
6. Fail-closed artifact writing only after a coherent capture exists.

This broader bridge is an attempt to solve the July 9 readiness gap. It does not prove the native generator reaches a capturable state.

## Intended Pipeline

```text
Homecoming_POC.rmg.json
  -> native ELoad.Generate
  -> Homm3RmgMapCaptureBridge multi-surface capture
  -> artifacts/rmg_capture/<sid>.map or MapData JSON
  -> role resolution
  -> scenario event patch
  -> separate installed scenario SID
```

## Key Files

| Path | Role |
| --- | --- |
| `scenarios/homecoming_roe_castle/Homecoming_POC.rmg.json` | native template input |
| `scenarios/homecoming_roe_castle/Homecoming_POC.roles.json` | role mapping input |
| `OfflineUnlockMod/Homm3RmgMapCaptureBridge.cs` | multi-surface runtime capture |
| `tools/wrap_rmg_capture_map.py` | MapData JSON wrapper |
| `tools/install_homecoming_rmg_template.py` | template install/config |
| `campaign_runtime_script.py` | event compiler candidate |

## Proof Boundary

Source shape and static registration can be validated without launching the game. Successful generation, capture, reload, deterministic seed behavior, role resolution, and patched event execution all remain runtime-open. Preserve any future failure as a named runtime observation rather than rewriting it into a static guarantee.
