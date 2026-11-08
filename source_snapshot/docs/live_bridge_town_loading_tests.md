# Live Bridge Town Loading Tests

Status: diagnostic-only, not a validator contract. Preferred custom-town product path is the owned Unity city-world paradigm in `docs/custom_town_scene_paradigm.md` (`cityFactory` / native `BhBuilding` / HotA world art). These tests still help separate visual-layer cost from native CityUI bind cost; do not use them to justify Route A posters as the destination.

## Tool

Run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_town_load_live_bridge_profile.ps1 -Mode WatchOpen -WaitForClickPrompt
```

The script writes timestamped JSON artifacts under `artifacts/live_bridge_town_load_profiles/`. The default bridge path targets the Golden Era install:

`V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod\live_probe_bridge`

## Run Order

1. Fresh-launch the game with the same map/save each time.
2. Stand on the adventure map with the target custom town ready to open.
3. Start the watcher:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_town_load_live_bridge_profile.ps1 -Mode WatchOpen -DurationSeconds 30 -IntervalMs 500 -WaitForClickPrompt
```

4. When the script prompts, press Enter and immediately open the town.
5. When the town is fully visible, run a stable snapshot:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_town_load_live_bridge_profile.ps1 -Mode Snapshot
```

6. To isolate the custom visual layer refresh path after the town is already open, run:

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_town_load_live_bridge_profile.ps1 -Mode Refresh -RefreshIterations 8
```

`WatchOpen` and `Snapshot` are read-only. `Snapshot` intentionally uses exact object probes instead of broad Unity UI/renderer scans; the first broad-scan attempt was too intrusive for repeatable load profiling. `Refresh` uses the existing explicit volatile bridge command `volatile_refresh_town_layers_from_cached_wrapper`; it does not change save data, but it does exercise live town-layer sync in the current scene.

## Latest Event Trace Result

The first event-only volatile Harmony trace, `artifacts/live_bridge_town_entry_traces/town_entry_event_trace_20260622_204853.jsonl`, was captured on the currently deployed first-runtime-falsified DLL. Parsed summaries are in `artifacts/live_bridge_town_entry_traces/town_entry_event_trace_20260622_204853_analysis/`.

Result: the dominant measured work was native building-card binding, not raw custom visual texture upload. `BhBuildingView.bind` ran 34 times and totaled 3308.928 ms, with the slowest single call at 190.414 ms. `UpdateLayerImages` totaled 34.391 ms across 35 calls; hero garrison bind totaled 47.109 ms; HUD city element refresh totaled 1.048 ms; the patched minimap render method did not fire during the captured window. `ApplyCustomCityBackdrop` and `SyncCurrentCityLayers` were called repeatedly, but their cost mostly reflects churn around native building view binding rather than expensive per-layer image creation.

Next diagnostic target: instrument the native building-card bind path more narrowly, especially the custom building data lookup/icon/text state creation inside `BhBuildingView.trr(fbs, dwc, int)`, and compare one custom town against one vanilla town with the same event-only method set. Do not add a production optimization or validator from this trace alone.


### Building Bind Cost Split

The follow-up live probe `artifacts/live_bridge_town_entry_traces/town_building_bind_cost_20260623_021839.jsonl` separated native `BhBuildingView.bind` from the mod's building-art postfix and sprite cache. Parsed summaries are in `artifacts/live_bridge_town_entry_traces/town_building_bind_cost_20260623_021839_analysis/`.

Result: native building-card bind/update remains the dominant measured cost. In the first captured town-entry cycle, `BhBuildingView.bind` ran 34 times and totaled 3640.525 ms. Native `UpdateView` ran 86 times and totaled 879.726 ms; nesting shows this as 34 calls inside the 34 bind calls plus 52 additional native refresh calls immediately after the bind pass. The mod hook contributes but does not explain the full stall: `PostfixBuildingViewBind` totaled 709.273 ms across 154 calls, `TryApplyBuildingView` totaled 202.270 ms, and `TryGetOrCreateSprite` totaled only 86.650 ms across 406 calls. This falsifies lazy custom building sprite creation as the primary root cause for this run. Hygiene note: the trace file includes extra cycles after the first stop attempt because the bridge loaded a fresh assembly instance for `stop`; the active Harmony patches were later cleared by `TownBuildingBindCostProbeCleanup.dll` via `Harmony.UnpatchID`. The next production candidate should focus on why custom town definitions cause repeated expensive native building-card bind/update work, while treating postfix idempotence as a secondary optimization.
## What To Compare

Use at least three runs on the same map/save.

- If `status.scene` switches to `cityHuman2` quickly, `townUi.layers.rootActive` becomes true quickly, and `activeLayers/rawImages` are populated while the hero garrison card or minimap is still late, the bottleneck is probably native HUD/data binding rather than custom town art.
- If `cityHuman2` appears late, the bottleneck is before our town visuals and likely scene load/native city setup.
- If `cityHuman2` appears quickly but `townUi.layers.rootActive` or `activeLayers/rawImages` lag, the custom visual path is still suspect.
- If `Refresh` round trips are consistently low after the town is open, steady-state custom layer sync is unlikely to explain the original loading delay.
- If `Refresh` is slow or returns bridge errors, inspect the raw `refresh_raw.json` result before assuming the native HUD is at fault.
- If `Snapshot` shows active `CanvasCityPanel`/`GarnisonPanel`/minimap objects before they are visible or interactive, the next target should be UI asset binding or data-driven card refresh, not town layer creation.

## Manual Notes To Record

For each run, write down the player-observed timing next to the artifact folder:

- time until town background/buildings are visible
- time until hero garrison card is visible and populated
- time until minimap is visible and responsive
- whether donor city renderers bleed through
- whether building placement is aligned

These manual observations are still needed because the current bridge can sample object state, but it does not yet measure real player-visible paint or interaction readiness.