# Golden Era Remaining Surface Orchestration

Date: 2026-06-09

This is the working process for finishing the remaining Golden Era HoMM3 presentation lanes after the terrain and external random-hire dwelling investigations.

## Scope

Remaining surfaces:

- Town billboard
- Town scene
- Town building icons
- External dwelling billboards
- Unit abilities

Treat these as separate evidence lanes until a runtime batch needs to observe them together. Do not merge hypotheses just because they occur in the same map load.

## Investigation Pattern

1. Split each surface into an independent skeptical investigation.
2. Require each investigator to name:
   - the exact production hook(s),
   - the centralized `GameSymbols` entries,
   - current runtime evidence,
   - the smallest falsifying log line,
   - safe diagnostic/fix boundaries,
   - hazards to avoid.
3. Merge only compatible diagnostics into one DLL. Compatible diagnostics observe independent hooks or field reads without changing the same runtime path.
4. Keep terrain rebuild probes, broad renderer probes, and map-rendering kill switches off while collecting town, dwelling, and ability evidence.
5. Runtime-test the batch once, then parse logs by surface before changing code again.

## Safety Rules

- Prefer field-first identity traversal. Generated IL2CPP property getters can crash and must not be hidden behind generic helper fallbacks.
- Exact live-proven getter methods may be called only from bounded call sites with local exception handling and clear symbol names.
- Centralize every generated or obfuscated type/member/method name in `GameSymbols.cs`.
- Avoid broad same-shape Harmony patching unless the hook is diagnostic-only, bounded, and explicitly flagged.
- Do not use UI/global sprite/image hooks to paper over town scene, town billboard, or building identity failures.
- Do not mutate random-hire SIDs or revive stale `czr`/`vfm` resolver calls for external dwelling billboards.
- Treat donor fallbacks as diagnostics unless the native-friendly route has been proven impossible.

## Current Batch Flags

Normal combined remaining-surface batch:

- `homm3_town_billboard_prop_city_probe.flag`
- `homm3_dwelling_prop_city_probe.flag`
- `releaseTownUiDiagnostics.flag`
- `homm3_town_layers_diag.flag`
- `homm3_ui_icon_diag.flag`
- `homm3_selected_hud_diag.flag`
- `homm3_map_load_flight_recorder.flag`
- `homm3_live_probe_workbench.flag`

Keep off unless specifically retracing terrain or isolation:

- `homm3_terrain_binding_deep_probe.flag`
- `homm3_terrain_renderer_broad_probe.flag`
- `homm3_terrain_donor_alias_probe.flag`
- `homm3_diag_disable_unitview_map_swaps.flag`
- `homm3_diag_disable_map_array_pilots.flag`
- `homm3_diag_disable_native_shell_transplant.flag`
- `homm3_diag_disable_custom_biome_registration.flag`
- `homm3_diag_disable_town_dwelling_billboards.flag`
- `homm3_diag_disable_map_squad_visual_controller.flag`
- `homm3_dwelling_fraction_resolver_probe.flag`

## Runtime Evidence Targets

- Town billboard: PropCity route should resolve the placed object id through `Hex.Map.ObjectsProperties`; applied log must include the custom city SID and donor renderers must be hidden/disabled. June 9 runtime with DLL hash `84F7EDE9...` proved generic `city-spawner` / `random-city` billboards resolve by `ObjectProp.get_field_Public_Int32_0()` as a zero-based `propCities` index plus exact `PropCity.get_factionSid()`; treat new failures here as regressions unless the map lacks generic custom towns.
- Town scene: current city identity must resolve from the release session city wrapper to a custom city SID/faction SID before scene or layer swaps run.
- Town building icons: building model/data/config identity must resolve field-first; success logs should include custom building keys and replacement counts, and diagnostics should show any still-visible overlay child if orange donor tiles remain.
- External dwelling billboard: PropCity donor dwellings and `PropRandomHire(Node)` dwellings must resolve through placed object id plus map area biome/manifest `identity.nativeBiome`; no stale resolver candidate spam should appear. The `ObjectProp.field_Public_Int32_0 -> propRandomHires[index]` bridge is evidence only unless the placed root is the exact native `random-hire` root or a future exact property-type discriminator is proven; runtime showed city/reward roots can also report random-hire-like indexes.
- Unit abilities: selected-unit action bars must build wrappers from current manager/config surfaces, seed native dictionaries for custom SIDs, and log bounded miss reasons rather than allowing native `KeyNotFoundException`.

## June 9 Live Probe Evidence

The `olden_live_probe` MCP adapter is useful for exact live type/method evidence, but in this running Codex session its tools were not exposed directly. Use the same supported file bridge protocol through `tools/live_probe_mcp/server.mjs` or bounded request JSON files only; do not treat the workbench as arbitrary runtime execution.

Fresh runtime bridge status after map load reported `profile=OfficialDeobf`, `scene=worldLight`, and read-only commands only. Live method signatures confirmed the current selected-unit surfaces:

- `Hex.Session.Battle.BhSelectedUnitHud.Method_Private_Void_Object_BattleEventArgs_PDM_0(object, BattleEventArgs)`
- `Hex.Session.Battle.BhSelectedUnitHud.Method_Public_Void_Boolean_Unit_PDM_0(bool, Unit)`
- `Hex.Session.Battle.BhUnitControlsView.Method_Public_Void_Il2CppReferenceArray_1_ObjectPublicObceInBoInceAbObELInUnique_ObjectPublicObceInBoInceAbObELInUnique_Boolean_PDM_0(...)`
- `Hex.Session.Battle.BhUnitControlsView.Method_Public_Void_BhUnitAbilityView_0(BhUnitAbilityView)`
- `Hex.Session.Battle.BhUnitControlsView.Method_Private_Void_BhUnitAbilityView_PDM_0(BhUnitAbilityView)`
- `Hex.Session.Battle.BhUnitControlsView.Method_Private_Void_Object_HotkeyAbilityArgs_PDM_0(object, HotkeyAbilityArgs)`
- `Hex.Session.Battle.BhUnitAbilityView.Method_Public_get_ObjectPublicObceInBoInceAbObELInUnique_0()`
- `Hex.Session.Battle.BhUnitAbilityView.get_field_Private_ObjectPublicObceInBoInceAbObELInUnique_0()`
- `Hex.Session.Battle.BattleEventArgs.get_target()`

Keep these centralized in `GameSymbols.SelectedUnitHud`. For broader `BattleUi` unit-config field lists, do not include bare `chjp`/`chjq` because that path can invoke no-arg generated methods; use only backing-field spellings there.

## Deployment Discipline

- Build gate:
  `dotnet build "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod\OfflineUnlockMod.csproj" -p:OfficialDeobfBuild=true --no-restore -clp:ErrorsOnly -v:quiet`
- Deploy DLL-only to the Golden Era experiment until source bundles are refreshed.
- Record deployed DLL SHA256 in the working notes or provenance ledger.
- Do not leave the game running after verification if another DLL deploy is likely.
