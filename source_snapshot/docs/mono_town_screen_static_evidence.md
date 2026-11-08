# Mono Town Screen Static Evidence

Status: static-only, runtime-unvalidated unless a row explicitly says otherwise. (2026-09-19: all 15 cited input paths verified present; static-only label stands.)

Inputs:

- Mono demo decompile: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_priority_town_decompiled.cs`
- Mono SmoothOpening decompile: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_smooth_opening_decompiled.cs`
- Broad mono/current map: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_deobf_semantic_map.json`
- Current SmoothOpening dossiers: `experiments/cpp2il_readable_csharp/samples/latest_refresh/town_smooth_ddd_car_dossier.md`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/town_smooth_ddh_bra_dossier.md`
- Current building UI dossiers: `experiments/cpp2il_readable_csharp/samples/latest_refresh/town_BhBuildingView_trr_dossier.md`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/town_BhBuildingView_UpdateView_dossier.md`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/town_BhBuildingView_tsi_dossier.md`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/town_BhUIBuildingSession_Init_dossier.md`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/town_BhUIBuildingSession_tud_dossier.md`
- Current scene-building dossiers: `experiments/cpp2il_readable_csharp/samples/latest_refresh/town_BhBuildingsManager_bajs_dossier.md`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/town_BhBuildingsManager_bajt_dossier.md`, `experiments/cpp2il_readable_csharp/samples/latest_refresh/town_BhBuildingsManager_baju_dossier.md`
- Current mod anchors: `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3FastCityOpeningHook.cs`, `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/GameSymbols.cs`

## High-value type survivals

| Mono type | Current deobf type | Confidence | Useful exact survivals | Notes |
|---|---|---|---|---|
| `Hex.UI.City.BhCityUISession` | `Hex.UI.City.BhCityUISession` | strong-static | methods `.ctor`, `OnExitBtn`, `OnHide`; fields `buildingSession`, `hire`, `me`, `navigation`, `townInput` | Main city UI shell survived by full type name, but most lifecycle methods are obfuscated in the current build. Use current dossiers before patching open/refresh paths. |
| `Hex.UI.City.BhUIBuildingSession` | `Hex.UI.City.BhUIBuildingSession` | strong-static | methods `.ctor`, `Init`, `OnEscapeClick`, `OnExitBtn`, `OnHide`, `Start`; fields `arrows`, `arrowsCg`, `buildingsUIs`, `exitButton`, `label`, `navigation`, `root`, `selector` | Strong candidate for building-session UI entry/exit and selector behavior. |
| `Hex.UI.City.BhBuildingView` | `Hex.UI.City.BhBuildingView` | strong-static | methods `.ctor`, `OnDeselect`, `OnHide`, `OnPointerDown`, `OnPointerEnter`, `OnPointerExit`, `UpdateView`; many view-state fields | Best current anchor for building view bind/update/hover/selection. `OnShow` is obfuscated, so use dossier evidence for bind methods like `trr` before relying on names. |
| `Hex.Session.City.BhBuilding` | `Hex.Session.City.BhBuilding` | strong-static | methods `.ctor`, `Deselect`, `Init`, `OnDisable`, `OnDrawGizmosSelected`, `OnEnable`, `OnPointerClick`, `OnPointerEnter`, `OnPointerExit`, `Select`, `Update`; fields `buildingBaseOffset`, `buildingHeight`, `buildingVfxScale`, `vfxRoot` | Scene building object lifecycle survived well. This is a better native anchor than broad GameObject traversal where possible. |
| `Hex.Session.City.BhBuildingsManager` | `Hex.Session.City.BhBuildingsManager` | strong-static | methods `.ctor`, `Awake`, `OnDisable`, `OnEnable`; field `constructOnStart` | Manager refresh/construct methods are obfuscated, but exact lifecycle methods survived. Good anchor for narrowing current refresh candidates. |
| `Hex.BhCityUpgradeStatsView` | `Hex.BhCityUpgradeStatsView` | strong-static | methods `.ctor`, `Init`; fields `arrow`, `arrowBad`, `arrowCrossOut`, `arrowGood`, `arrowGreen`, `arrowNo`, `from`, `label`, `pic`, `to` | Useful for tooltip/cost/stat display surfaces, not city scene load itself. |

## SmoothOpening model

Mono `Hex.Session.SmoothOpening.OpenTimeTracker` exposes the intent behind the fast city-opening hook:

- `OpenTimeTracker.GetMaxFrame(EType, string)` returns `Ceiling(GetMaxTime(type, contentId) * 60)` and adds `2` frames for `EType.Arena` only.
- `OpenTimeTracker.GetMaxTime(EType, string)` reads recent tracked open times, clamps pathological values above `10s`, and falls back to `0.5s`.
- `SmoothOpening.ToCity(WoCity)` computes `GetMaxFrame(EType.City, city.config.id)`, adds network latency sleep frames, and opens city mode after the fade.
- This validates the design target of `Homm3FastCityOpeningHook`: reducing custom city opening wait by clamping the computed city frame count, not bypassing city UI initialization.

## Current SmoothOpening candidates

| Surface | Current deobf evidence | Static confidence | Notes |
|---|---|---|---|
| `ddd.car(ddd+EType, string)` | Calls `ddd.wns(EType,string)`, multiplies returned seconds by 60, calls a Math rounding helper, branches on `EType == 1`, and returns `frameCount + 2` for that branch. Dossier: `town_smooth_ddd_car_dossier.md`. | proven-static current body | This matches Mono `OpenTimeTracker.GetMaxFrame`. The enum value `1` corresponds to Arena in Mono, so city should not receive the +2 branch. |
| `ddd.wns(ddd+EType, string)` | Target of `ddd.car`; same type has multiple `Single(EType,string)` methods with OpenTimeData fields. | strong static candidate | This matches Mono `OpenTimeTracker.GetMaxTime` shape but needs its own focused dossier before mutation or direct patching. |
| `ddh.bra(ddd+EType, string)` | Static wrapper loads a stored `ddd` tracker-like object and calls `ddd.wnr(EType,string)`, returning the int result; otherwise returns `1` or fails through unresolved helper. Dossier: `town_smooth_ddh_bra_dossier.md`. | proven-static wrapper | This matches Mono static `SmoothOpening.GetMaxFrame`/facade behavior. It is safe as a wrapper target only if startup registration proves this method exists in the current runtime. |
| `GameSymbols.SmoothOpening.CityFrameCount` | Currently lists `car`, `edj`, `ekm`, `wnr`, then older hints. | source-prepared/static-supported | `car` is proven-static. The duplicate current names likely exist because Cpp2IL sees repeated generated variants; they should be treated as same-shape candidates until each has a dossier or startup registration evidence. |
| `GameSymbols.SmoothOpening.OpeningFrameCount` | Currently lists `bra`, `gwx`, `kjz`, `oqv`, `wog`, then older hints. | source-prepared/static-supported | `bra` is proven-static as a facade wrapper. Other names are same-signature siblings in `ddh`; treat as candidates until dossier/registration. |

## Current mod-design implications

- The fast-city-opening hook is correctly aimed at frame-count return values, not at scene construction or building UI methods.
- The current hook should remain narrow: patch only `int (EType,string)` methods on `ddd`/`ddh`, then clamp only when `EType == City` and the SID is a custom city.
- Because Mono shows `SmoothOpening.ToCity` still runs fade, state-machine exit, command dispatch, and city mode entry after frame calculation, do not use this hook to skip initialization or suppress city UI refreshes.
- For town load performance beyond frame-count waits, the next native-friendly target is reducing our custom layer sync work after city UI/session has loaded, not further changing SmoothOpening.
## Building UI lifecycle map

Status: static-only; current-method identities below are not runtime registration proof.

| Mono intent | Current deobf surface | Static confidence | Evidence | Mod implication |
|---|---|---|---|---|
| `BhUIBuildingSession.Init(city)` initializes the building tray/session for a city. | `BhUIBuildingSession.Init(fbs _city)` | proven-static current body | Current body clears `BuildingArrows`, stores `_city` into field `bzgs`, deactivates/reuses `buildingsUIs`, enumerates city building data, calls `BuildingData.bgch`, calls `BhBuildingView.trr`, populates view list/dictionary fields, and later calls `BhBuildingView.UpdateView`. | This is the best native lifecycle anchor for one-time building tray binding. A custom town-layer sync tied here should be idempotent and avoid per-view repeated work. |
| `BhBuildingView.OnShow(city, buildingLogic, level)` binds one building UI row. | `BhBuildingView.trr(fbs a, dwc b, int c)` | proven-static current body | Current body activates the view object, clears parent/view state, writes city/building/SID/level fields (`bzfr`, `bzfs`, `bzft`, `bzfu`), resolves `BuildingData.bgch`, reads configured icon data, and updates image/list state. | This is a precise replacement for broad building-view field probing. It is suitable for read-only view metadata capture and late icon/text adjustment, not for scene construction or spending. |
| `BhBuildingView.UpdateView()` recomputes visible state/affordance. | `BhBuildingView.UpdateView()` | proven-static current body | Current body reads bound city/building/SID/level fields, writes `EBuildingUIState` field `bzfv`, toggles lock/overlay/sign/status UI, calls `dwc.badm`, `dry.xzk`, and helper methods around state/status rendering. | This is a refresh surface. It can tell us the UI thinks a building is constructed/available/banned, but it should not be treated as the authoritative construction commit or resource mutation. |
| `BhBuildingView.CheckCost(costs)` checks whether the side can afford costs for display. | `BhBuildingView.tsi(ResNameAndCost[] a)` | proven-static current body for UI affordability check | Current body iterates a `ResNameAndCost[]`, reads the bound city field `bzfr`, reaches a side/resource-like object through `fda.bjbt`, and ANDs per-resource affordability checks. | This is UI affordability only. It is useful for explaining construction button state, but it is not a spending surface and should not be used for custom economy mutation. |
| `BhUIBuildingSession` reacts to construction event and refreshes views. | `BhUIBuildingSession.tud(bfh a)` | proven-static current body | Current body enumerates `bzgt` (`List<BhBuildingView>`) and calls `BhBuildingView.UpdateView` for each matching/active view. | This is the native post-construction UI refresh surface. It is a better hook than generic tooltip/back-button handling for keeping custom town UI in sync after construction. |
| Scene `BhBuildingsManager` constructs/deconstructs scene objects. | `BhBuildingsManager.baju()` | strong static candidate | Current body enumerates manager list `cedd` and calls `BhBuilding.bajc` and `BhBuilding.bajb`; Mono `BhBuilding.Construct`/`Deconstruct` match this kind of scene-object state transition. | This is scene object visibility/animation, not building tray UI. Avoid using it for law/economy logic; it may be useful only for town art/layer alignment after scene objects settle. |
| Scene `BhBuildingsManager` applies one building to a scene slot. | `BhBuildingsManager.bajs(dwc a, bool b)` | strong static candidate | Current body reads `BuildingData.bgch`, calls `BhBuildingsManager.bajt(config.sceneSlot)`, tests for a returned `dxg`, then calls `dxg.bajn(a,b)`. | This is likely the native scene-slot construct/update surface. It is a candidate anchor for custom backdrop/layer sync after a building slot changes. |
| Scene slot lookup by configured `sceneSlot`. | `BhBuildingsManager.bajt(string a)` | proven-static current body for lookup shape | Current body enumerates `cedd` (`List<dxg>`), compares a string field on each `dxg` with the argument, returns the matching `dxg`, or returns null. | This is a safe read-only locator for mapping building config `sceneSlot` to scene object. It can replace broad transform-name searches if runtime registration proves it. |

## Town-load optimization conclusions

- There are three separate town-screen concerns: `SmoothOpening` wait frames, scene building object construction (`BhBuildingsManager`/`BhBuilding`), and building-tray UI binding/refresh (`BhUIBuildingSession`/`BhBuildingView`). Optimizing one must not masquerade as optimizing the others.
- The current `Homm3FastCityOpeningHook` belongs only to `SmoothOpening` frame counts.
- Heavy custom town layer work should attach to either `BhUIBuildingSession.Init` for one-time city binding, `BhUIBuildingSession.tud` for post-construction refresh, or `BhBuildingsManager.bajs`/`baju` for scene-object changes. It should not be driven by broad per-frame scans or generic button/tooltip events.
- Construction/resource gameplay remains outside this UI map. `BhBuildingView.tsi` is explicitly a display affordability check, not a resource spend path.
- The native-friendly next implementation path for town loading is to make custom layer sync idempotent around these exact lifecycle surfaces, then measure which one fires too often. No runtime proof has been run for this map yet.
## Building UI lifecycle map

Status: static-only; current-method identities below are not runtime registration proof.

| Mono intent | Current deobf surface | Static confidence | Evidence | Mod implication |
|---|---|---|---|---|
| `BhUIBuildingSession.Init(city)` initializes the building tray/session for a city. | `BhUIBuildingSession.Init(fbs _city)` | proven-static current body | Current body clears `BuildingArrows`, stores `_city` into field `bzgs`, deactivates/reuses `buildingsUIs`, enumerates city building data, calls `BuildingData.bgch`, calls `BhBuildingView.trr`, populates view list/dictionary fields, and later calls `BhBuildingView.UpdateView`. | This is the best native lifecycle anchor for one-time building tray binding. A custom town-layer sync tied here should be idempotent and avoid per-view repeated work. |
| `BhBuildingView.OnShow(city, buildingLogic, level)` binds one building UI row. | `BhBuildingView.trr(fbs a, dwc b, int c)` | proven-static current body | Current body activates the view object, clears parent/view state, writes city/building/SID/level fields (`bzfr`, `bzfs`, `bzft`, `bzfu`), resolves `BuildingData.bgch`, reads configured icon data, and updates image/list state. | This is a precise replacement for broad building-view field probing. It is suitable for read-only view metadata capture and late icon/text adjustment, not for scene construction or spending. |
| `BhBuildingView.UpdateView()` recomputes visible state/affordance. | `BhBuildingView.UpdateView()` | proven-static current body | Current body reads bound city/building/SID/level fields, writes `EBuildingUIState` field `bzfv`, toggles lock/overlay/sign/status UI, calls `dwc.badm`, `dry.xzk`, and helper methods around state/status rendering. | This is a refresh surface. It can tell us the UI thinks a building is constructed/available/banned, but it should not be treated as the authoritative construction commit or resource mutation. |
| `BhBuildingView.CheckCost(costs)` checks whether the side can afford costs for display. | `BhBuildingView.tsi(ResNameAndCost[] a)` | proven-static current body for UI affordability check | Current body iterates a `ResNameAndCost[]`, reads the bound city field `bzfr`, reaches a side/resource-like object through `fda.bjbt`, and ANDs per-resource affordability checks. | This is UI affordability only. It is useful for explaining construction button state, but it is not a spending surface and should not be used for custom economy mutation. |
| `BhUIBuildingSession` reacts to construction event and refreshes views. | `BhUIBuildingSession.tud(bfh a)` | proven-static current body | Current body enumerates `bzgt` (`List<BhBuildingView>`) and calls `BhBuildingView.UpdateView` for each matching/active view. | This is the native post-construction UI refresh surface. It is a better hook than generic tooltip/back-button handling for keeping custom town UI in sync after construction. |
| Scene `BhBuildingsManager` constructs/deconstructs scene objects. | `BhBuildingsManager.baju()` | strong static candidate | Current body enumerates manager list `cedd` and calls `BhBuilding.bajc` and `BhBuilding.bajb`; Mono `BhBuilding.Construct`/`Deconstruct` match this kind of scene-object state transition. | This is scene object visibility/animation, not building tray UI. Avoid using it for law/economy logic; it may be useful only for town art/layer alignment after scene objects settle. |
| Scene `BhBuildingsManager` applies one building to a scene slot. | `BhBuildingsManager.bajs(dwc a, bool b)` | strong static candidate | Current body reads `BuildingData.bgch`, calls `BhBuildingsManager.bajt(config.sceneSlot)`, tests for a returned `dxg`, then calls `dxg.bajn(a,b)`. | This is likely the native scene-slot construct/update surface. It is a candidate anchor for custom backdrop/layer sync after a building slot changes. |
| Scene slot lookup by configured `sceneSlot`. | `BhBuildingsManager.bajt(string a)` | proven-static current body for lookup shape | Current body enumerates `cedd` (`List<dxg>`), compares a string field on each `dxg` with the argument, returns the matching `dxg`, or returns null. | This is a safe read-only locator for mapping building config `sceneSlot` to scene object. It can replace broad transform-name searches if runtime registration proves it. |

## Town-load optimization conclusions

- There are three separate town-screen concerns: `SmoothOpening` wait frames, scene building object construction (`BhBuildingsManager`/`BhBuilding`), and building-tray UI binding/refresh (`BhUIBuildingSession`/`BhBuildingView`). Optimizing one must not masquerade as optimizing the others.
- The current `Homm3FastCityOpeningHook` belongs only to `SmoothOpening` frame counts.
- Heavy custom town layer work should attach to either `BhUIBuildingSession.Init` for one-time city binding, `BhUIBuildingSession.tud` for post-construction UI refresh, or `BhBuildingsManager.bajs`/`baju` for scene-object changes. It should not be driven by broad per-frame scans or generic button/tooltip events.
- Construction/resource gameplay remains outside this UI map. `BhBuildingView.tsi` is explicitly a display affordability check, not a resource spend path.
- The native-friendly next implementation path for town loading is to make custom layer sync idempotent around these exact lifecycle surfaces, then measure which one fires too often. No runtime proof has been run for this map yet.

## Local mod call-site audit against lifecycle map

Status: static-only, unvalidated. This is a design breadcrumb for future optimization work, not proof that a given runtime path is hot in the current build.

| Current local path | Observed behavior | Lifecycle classification | Risk |
|---|---|---|---|
| `Plugin.PatchReleaseCityTownUi` patches `BhCityUISession`, `BhBuildingsManager`, `BhUIBuildingSession`, `BhBuildingView`, navigation, generic buttons, hire/upgrade UI, and several fallback shapes. | Many postfixes eventually call `ApplyCustomCityBackdrop()` and/or `Homm3StrongholdTownLayers.SyncCurrentCityLayers()`. | Over-broad compatibility net; multiple native lifecycle phases collapse into the same layer sync endpoint. | High performance risk because unrelated UI refreshes can still force panel/fraction/city/building/signature work before the unchanged-signature skip. |
| `BhUIBuildingSession.Init` patch path. | Local postfix captures city wrapper and then can sync custom layers. | Correct one-time city bind anchor. | Best candidate for the primary custom layer build/rebuild trigger. |
| `BhUIBuildingSession.tud` / building-session refresh candidates. | Native body refreshes every `BhBuildingView` after a construction event. | Correct post-construction refresh anchor. | Good candidate for construction-only layer refresh; should not rebuild static assets unless active building levels changed. |
| `BhBuildingView.trr` bind patch path. | Native body binds one building view and stores city/building/SID/level. | Per-view bind. | Useful for observing building data, but syncing full town layers per building-view bind is likely redundant during initial city load. |
| `BhBuildingView.UpdateView` patch path. | Native body recomputes one view's affordance/status. | Per-view UI refresh. | Full town layer sync here is likely too frequent. Use only for capturing view metadata or schedule a coalesced deferred sync. |
| `BhBuildingsManager.bajs` / `baju` candidates. | Native scene-object construction/update path, separate from tray UI. | Scene building object lifecycle. | Good future anchor for aligning custom art with native scene slot changes; not a resource/economy surface. |
| `SyncCurrentCityLayers()` unchanged-signature fast path. | Still resolves panel, fraction, music, city, building entries, and signature before skipping; then reapplies root transform/sibling/order/fade release on unchanged signature. | Shared sink. | Should remain idempotent, but should be called from fewer lifecycle entry points. If still called broadly, its pre-skip work remains load-time overhead. |
| Dynamic layer path `UpdateLayerImages()`. | Plans active layers, ensures `RawImage` objects, loads textures through cache, applies transforms, attaches animations, and sorts/siblings. | Heavy rebuild/update work. | Should occur only when the active building-layer signature changes or a prefab root is first instantiated. |
| Prefab path `TryEnsurePrefabLayerRoot()` / `UpdatePrefabLayerImages()`. | Reuses prefab root when available and avoids dynamic `RawImage` construction. | One-time prefab instantiation plus state visibility update. | Better long-term path, but current notes say prefab artifact may be missing; missing prefab should be a visible warning, not a silent performance fallback claim. |

Native-friendly optimization direction:

1. Keep `Homm3FastCityOpeningHook` isolated to SmoothOpening wait-frame clamping.
2. Make `BhUIBuildingSession.Init` the primary one-shot custom layer sync trigger after city binding.
3. Make `BhUIBuildingSession.tud` the primary post-construction sync trigger.
4. Treat `BhBuildingView.trr` and `UpdateView` as observation/coalescing surfaces, not full sync surfaces.
5. Prefer `BhBuildingsManager.bajs`/`baju` for scene-slot alignment only if the local art layer needs native scene object state.
6. Remove or narrow generic navigation/button/tooltip-triggered layer sync once the two primary lifecycle surfaces are runtime-proven.
7. Keep the unchanged-signature guard, but do not rely on it as the only performance defense.
## Static gaps before implementation changes

- Runtime registration of the current SmoothOpening names is not proven in this document. Startup logs can prove whether `car`/`bra` and siblings are patchable in the live generated interop build.
- `ddd.wns`/`ddd.wnr` are candidate `GetMaxTime`/`GetMaxFrame` siblings; only `ddd.car` and `ddh.bra` have focused dossiers here.
- The exact current `EType` numeric values are inferred from Mono plus current branch shape. If a future patch changes enum ordering, the hook must rely on runtime enum name/type checks where possible rather than raw integer values.
- City-layer performance is not explained by SmoothOpening alone. The heavy local code remains in `Homm3StrongholdTownLayers`, especially texture/path resolution, dynamic image creation, and repeated layer sync. The static lifecycle map above narrows where that work should attach, but the local mod code still needs a call-site audit before optimization changes.

## Next static work for town screen

1. Build focused dossiers for `BhCityUISession` open/show/update candidates, especially the obfuscated methods around Mono `OnShow`, `InitializeCity`, `SetupUI`, and `Refresh`.
2. Audit `Homm3StrongholdTownLayers` call sites and classify each expensive operation against the lifecycle surfaces above: one-time city bind, post-construction refresh, scene-object update, or genuinely per-frame.
3. Build focused dossiers for `BhBuildingsManager.bajq`/`bajr` if the call-site audit shows we still need manager event subscribe/unsubscribe semantics.
4. Only after that, decide whether to optimize custom layer work by moving from broad refresh hooks to exact native lifecycle hooks.



