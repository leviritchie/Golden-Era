# HoMM3 map RIFE pilot (Goblin Trapper + Gremlin)

Adventure-map animation is **not** battle `01.Walk`. Map units use `map.prefab` + **`MapIdle`** (material swap over `map_frame_*`), authored from `extracted_map` DEF cycles.

## Pilot units

| Lab SID | Game stack | Bundle |
|---------|------------|--------|
| `toa_goblin_trapper` | `h3_goblin_upg_alt` | `custom_units_toa_goblin_trapper` |
| `h3_gremlin` | `h3_gremlin` | `custom_units_h3_gremlin` |

## One-shot pipeline

```bat
tools\homm3_import\build_homm3_map_rife_pilot.cmd
```

Steps: sync map extracts → RIFE @ 50 FPS → mirror to Unity → rebuild map billboards → bundle → `dotnet build` to Steam.

Requires `OLDENERA_UNITY_PROJECT` (or `oldenera_factions`) and V: temp for RIFE (`setup_vfi_env.sh`).

## Timing contract

- **RIFE wall-clock cycle**: `outputCount / targetFps` (e.g. Gremlin 40÷50 = 0.8s), stored in `.rife_map_done.json`.
- **Authored clip**: `outputCount` materials, `mapFlipBookFps` (50 after RIFE).
- **Runtime routing**: when `.rife_map_done.json` exists, skip town-style hex-lit quads and instantiate **`map.prefab` + MapIdle** (bundles often list only one `map_frame_*` name even though the prefab clip has every frame).
- **Runtime timing** (`TryApplyMapAdventureAnimatorPlaybackTiming`): `animator.speed = MapIdle.length / (outputCount/targetFps)` so a stale 10 FPS clip is corrected (~5× too slow without this).

Town-style disk fallback (if prefab path fails) uses manifest **group** from RIFE meta and `frameMs = cycleSec×1000/frameCount`, not a flat 120ms tick.

If pilots still look wrong after a DLL deploy, rerun the full cmd so `MapIdle.anim` is rebaked at 50 FPS and bundles are refreshed.

## Expanding beyond the pilot

1. Add lab SIDs to `tools/homm3_import/map_rife_pilot_units.txt` (one per line).
2. Run the same cmd with that list (or duplicate the cmd for a faction batch).
3. Confirm map billboards in logs: `map adventure playback timing` with `animator.speed` near `1` when the bundle clip matches RIFE metadata.
4. Do **not** mix map RIFE into battle `interpolate_homm3_battle_all.cmd`; map and battle are separate lanes.

June 2 next-pilot note: use `tools/homm3_import/map_rife_next_pilot_units.txt` for the two-unit Grand Elf + Wolf Raider run. `h3_wolf_raider` is the upgraded Wolf Raider lab source backing game SID `h3_wolf_rider_upg`; do not substitute base `h3_wolf_rider`.
