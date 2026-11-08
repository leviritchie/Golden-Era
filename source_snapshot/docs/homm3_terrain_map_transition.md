# Adventure-map terrain lookup lifecycle

Status (2026-10-02): source/static and production-linked fixture validated; Golden Era build and installed
payload proven. Startup smoke, live IL2CPP behavior and user-visible snow remain pending.

Owner: `Homm3SwampAutumnTintProof.PrefixRendererPrepareMap` and
`Homm3TerrainMaterialLookup.Replace`. Gate: `tools/validate_homm3_custom_biome_runtime_contract.py`,
already wired into the plugin's Full Validation build/deploy tier.

## Contract

The native adventure-map terrain renderer can survive map unload. Its tile-code-to-material-slot lookup must
be replaced from the current compacted `SoTerrainMaterial.biomes` before native map preparation, including
custom, native-water-only and stock-only maps. Preserve native material entries, declared material aliases
and the existing native-water/Sand-seabed binding. No previous renderer lookup is a source of current slots.
Stock-only compaction must not activate custom-map donor marker textures. Water-only maps keep their existing
current-row/Sand binding rather than creating custom packed water rows. Declared material aliases may
redirect their own catalog row, but their donor slot must come from the current table.

Build the complete managed snapshot and check every slot against the current material-table length before
clearing the native dictionary. Use the native dictionary's `Clear`/`Add` operations, not native dictionary
enumeration. Invalid snapshots throw before mutation; do not extend arrays to accommodate retired entries,
swallow the error or substitute another biome. No changes to terrain art, Core, or payload schemas are needed.
Failure to establish the packed-vector prerequisite throws before lookup replacement instead of returning
with stale renderer state. The obsolete renderer-first donor resolver has been removed.

## Failure evidence

The 2026-10-02 Tower Blitz run (seed `781572298`, generated at 20:00:37 local time) selected Tundra/Snow.
The preceding Fortress map used Swamp and Molten with nine material slots. Tower compacted to eight slots,
but the same renderer retained Burrow `15 -> 8` and Molten `17 -> 8`, outside the new valid range `0..7`.
Native terrain preparation then threw `IndexOutOfRangeException`; the subsequent packed terrain rebuild
was absent. The observed lava-looking ground is consistent with retained earlier terrain presentation,
but the exact native access and displayed pixels were not independently captured.

Evidence: Golden Era `BepInEx/LogOutput.log`, lines 7103-7117 and 10286-10300; General log
`02.10.26-19.49.57-log.txt`, lines 6148-6156 and 6712-6731. These are pre-fix runtime records, not fix proof.

## Verification and cost

The contract gate runs a small, production-linked BCL C# fixture, not Unity or a full plugin build.
It exercises reused lookup replacement, shrinking and equal-sized tables, aliases, native water and
invalid snapshots. Source checks pin the unconditional prepare-map replacement, marker/water guards,
declared alias override and fail-closed prerequisite handling.

Measured on 2026-10-02:

- Final owning validator against installed custom biome assets and Core: PASS, 2.35 seconds including resource sampling.
- Warm fixture subprocess: 1.89 seconds; the fixture's checks themselves: 1 ms. An earlier cold SDK/recompile run took
  24.9 seconds. `dotnet run` reuses ordinary incremental build outputs; the subprocess has a 60-second timeout.
- Fixture process peak working set: 24,879,104 bytes (23.7 MiB). Observed validator/SDK/console-host individual
  process peaks summed to 156,729,344 bytes; adding the short-lived fixture peak gives about 173.2 MiB.
  This is a sum of independent observed peaks, not a concurrent whole-host peak. Shared SDK servers and the
  sampling wrapper are excluded; no GPU work or stage VRAM allocation is involved.
- Final Golden Era binary-only build/deploy: PASS, 18.76 seconds; 54 warnings, zero errors. Live interop audit:
  1,207 member references, no new unresolved references. GameSymbols scope/hint and payload ABI guards: PASS.
- Installed DLL, PDB and ABI sidecar match build outputs by readback. ABI versions remain UnitBundle 1 / TownScene 2.
  Terrain art, Core and bundle payloads were not deployed by this change.

The new lookup reconciliation is one bounded material-table scan plus dictionary replacement per renderer map scope;
it performs no raster, per-pixel work, allocation proportional to map area or GPU work. Dictionary control
flow is sequential CPU work. Build/deploy proof does not prove live IL2CPP behavior or visible snow.

Independent source review completed after correcting adjacent marker, alias, water-only and failed-prerequisite
behavior. No other actionable source issue remained. The owning validator ran directly; the unrelated whole-repo
Full Validation tier was not run.

Focused evidence logs: `V:/olden_port_work/terrain_map_transition/golden_binary_deploy.log` and
`installed_contract.log`. Original pre-fix DLL, PDB and ABI sidecar are preserved in
`V:/olden_port_work/terrain_map_transition/rollback_before_fix/`.

Installed visual checks belong only in `docs/ingame_check_queue.md` (terrain map-transition row).
