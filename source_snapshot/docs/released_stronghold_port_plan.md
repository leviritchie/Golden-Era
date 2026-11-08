# Released Stronghold Port Plan

> Historical release-port record (started 2026-05-04). Old build roots and defaults below are preserved as investigation history, not current instructions. Current Golden Era builds use the Steam Golden Era root and `OfficialDeobfBuild=true`.
Date: May 4, 2026.

Scope: move the HoMM3 Stronghold work from `Heroes of Might & Magic Olden Era Playtest/` to the dedicated released Steam install. The released game path is `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era`; do not recreate the removed workspace junction.

## Initial Static Findings

- The released install already has BepInEx 6.0.0-be.755 and regenerated IL2CPP interop under `Heroes of Might and Magic Olden Era - Golden Era/BepInEx/interop`.
- Release bootstrap note from May 4, 2026: the Steam install's `doorstop_config.ini` was disabled (`enabled=false`). It was replaced with the playtest Doorstop config pointing at `BepInEx\core\BepInEx.Unity.IL2CPP.dll`, and `BepInEx\config\BepInEx.cfg` now has `UnityLogListening = false` to avoid the observed `BepInEx.Unity.IL2CPP.Logging.IL2CPPUnityLogSource..ctor()` access violation.
- After the released game regenerated interop, `BepInEx/interop/UnityEngine.UnityWebRequestAudioModule.dll` was absent. The project now conditionally references that module and disables HoMM3 Stronghold `BUILDTWN.wav` town build playback when targeting this release interop set. Town build visual fades still compile and remain active.
- Release-safe profile, added May 4, 2026: when the game root contains `HeroesOldenEra_Data` and not `HeroesOE_Data`, the plugin suppresses legacy playtest-only offline unlock/menu hijack patches, old UI-scale patches, damage histogram patches, retaliation forecast fix, and `autoLaunchOnMenu`. This is required for the full release because the old `BhNavigationButton.OnPointerClick` menu intercept throws on removed `MainMenuNavigationView.quickStartButton` accessors and can make all main menu buttons appear dead. `TryLoad()` must force this default even when root `OfflineLauncherConfig.json` is absent and only stale mod `config.json` exists; otherwise the default `new LauncherConfig()` keeps release-safe off.
- A disposable build of the current plugin source against the released `BepInEx/core` and `BepInEx/interop` succeeded with 0 compile errors. The broad C# API surface still compiles; migration risk is mostly runtime symbol drift, data packaging, and UI integration.
- The released game moved the Unity data root from playtest `HeroesOE_Data` to `HeroesOldenEra_Data`. `Core.zip` now lives at `Heroes of Might and Magic Olden Era - Golden Era/HeroesOldenEra_Data/StreamingAssets/Core.zip`.
- The released `Core.zip` does not contain `homm3_stronghold`. Its `DB/data.json` only lists vanilla `human`, `undead`, `nature`, `demon`, `unfrozen`, `dungeon`, plus `neutral` and `mix`; `availableFractions` only lists the six vanilla playable factions. The playtest-tweaked Core contains `homm3_stronghold`, `homm3_fortress`, and `dungeon_raw`.
- The released data folders use some naming differences versus the playtest-tweaked Core. Example: release has `DB/heroes/demons/*` while the tweaked playtest archive has `DB/heroes/demon/*`. Do not blindly copy whole JSON folders without schema/path comparison.
- `OfflineUnlockMod.csproj` now accepts configurable `GameRoot` and `BepInExRoot` MSBuild properties. Default builds still target the adjacent playtest install; release builds can pass `-p:GameRoot="V:\Games\Olden Era Playtest Tweak\Heroes of Might and Magic Olden Era"`. The project normalizes into derived `GameRootDir`/`BepInExRootDir` properties because command-line MSBuild properties are immutable.
- Verified builds:
  - Playtest target: `dotnet build -c Release -p:DeployPluginToGame=false --nologo` succeeded with 0 errors.
  - Release target: `dotnet build -c Release -p:DeployPluginToGame=false "-p:GameRoot=V:\Games\Olden Era Playtest Tweak\Heroes of Might and Magic Olden Era" --nologo` succeeded with 0 errors.
  - Release deploy target: `dotnet build -c Release "-p:GameRoot=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era" --nologo` succeeded with 0 errors and deployed `BepInEx/plugins/OfflineUnlockMod/OfflineUnlockMod.dll` to the Steam install.

## Release Log Roadblocks

Known release logs show several runtime breaks from older deployed plugin builds:

- Resolved bootstrap blocker: `BepInEx/ErrorLog.log` previously showed an early `System.AccessViolationException` in `BepInEx.Unity.IL2CPP.Logging.IL2CPPUnityLogSource..ctor()` before plugin load. The active release config keeps `UnityLogListening = false`; do not re-enable it until the BepInEx/Unity 6000.0.66f1 IL2CPP log callback crash is understood or fixed upstream.
- BepInEx did not launch at first because release `doorstop_config.ini` had only `[Doorstop] enabled=false`. The live Steam install now has Doorstop enabled and targeting `BepInEx\core\BepInEx.Unity.IL2CPP.dll`.
- A short hidden release smoke run after the bootstrap fix touched `BepInEx/interop`, `BepInEx/unity-libs`, and `BepInEx/ErrorLog.log`, confirming Doorstop/BepInEx startup side effects. The run was killed early, so treat it as loader evidence, not as proof that the full plugin loaded cleanly through the main menu.
- May 4 main-menu smoke found release-only obsolete patch failures:
  - `BhNavigationButton.OnPointerClick` intercepted vanilla clicks and threw `MissingMethodException` for `MainMenuNavigationView.get_quickStartButton()`, leaving menu buttons nonfunctional.
  - `BhFont` UI scale hooks threw repeated `MissingMethodException` for `BhFont.shh()`.
  - `DamageHistogramBootstrap.Ensure()` hit release drift around old forecast symbols such as `ejz`; histogram work is explicitly deferred for release.
  - Even after histogram config is forced off, `PatchAnnotatedTypes()` must skip disabled patch classes and probe classes before reading Harmony attributes. Reading attributes first can still deserialize stale `ejz` type references from `BattleForecastProbe` and fail plugin load.
  - Fix policy: do not remap these old launcher/offline/histogram hooks for the release Stronghold port. Keep them suppressed under `releaseSafeProfile` and port Stronghold through vanilla custom-game UI instead.
- Older release `LogOutput.old.log` with plugin `0.1.110` reached plugin load but showed obfuscation drift:
  - `dzk.bath` battle pool hook not found.
  - `UnitViewConfig.rtd` map hook not found.
  - `Hex.UI.UiModelsSpawner` not found.
  - `BhTooltipUnit.srs(string)` not found.
  - `Hex.Pick.BhUnitSlot.lrt(...)` not found, though newer fallback patches on `BhUnitSlots.Init` and `BhTurnView.UpdateView` registered.
  - `Homm3StrongholdTownMapBillboard` hit `TypeLoadException: Could not load type 'but'`.
- The source has since wrapped several Stronghold registration paths in `try/catch`, and the current source compiles against release interop. Still, each runtime hook must be re-traced against the released symbols instead of assuming playtest obfuscated names.
- May 4, 2026 visual-hook trace after a successful Stronghold custom game start: the map/unit view path still uses `Hex.Configs.UnitViewConfig`, but the playtest `rtd()` map prefab loader is now release method `sce()` (same public instance zero-argument `GameObject` return shape). Plugin `0.1.146` incorrectly latched onto `get_bxow()` because the shape fallback did not exclude property accessors; `0.1.147` excludes special-name accessors and explicitly prefers `rtd`/`sce`. This is only the adventure-map unit hook; battle pool replacement is still unmapped because release `dzk` no longer has `bath`. Static mapping now points battle visual initialization at `ecd.Init(UnitViewConfig,TransferUnit,Random,Vector3,float,bool,int)`, so do not chase `dzk.bath` in the release build.
- The same run still logged `Homm3StrongholdTownMapBillboard`/dwelling registration failures around `TypeLoadException: Could not load type 'but'`. Treat town and dwelling adventure-map billboards as a separate release roadblock from `UnitViewConfig.sce()`; do not assume the 0.1.146 map-unit fix covers city objects.
- May 4, 2026 release config warning: the live Steam `BepInEx/plugins/OfflineUnlockMod/config.json` still had `esquirePikemanVisuals=true`, so vanilla Castle swordsmen were replaced with pikemen even though that playtest experiment was supposed to be disabled. Plugin `0.1.148` suppresses the Esquire/Pikeman lane under `releaseSafeProfile` so stale release configs cannot contaminate Stronghold testing.
- May 4, 2026 static UI remap pass: release hero portrait/icon surfaces are renamed but still structurally similar. Plugin `0.1.149` adds release aliases for hero portraits (`BhHeroSelectButton.hpf`, `BhTooltipHeroItemView.tal/tam/tan`, `BhHeroPortraitView.ztr/ztu`, `BhTavernHeroView.zbw`) and custom city UI icons (`BhHireUnitAbilityItemView.bajc/bajd`, `BhHireUnitAbilityView.baje/bajf`, `BhCityUIElement.vza/vzb/vze`, `BhTooltipBuilding.syo/syp`). Do not map battle ability `BhUnitAbilityView.begf` by name yet: release uses `els`/`dxs` wrappers while the old postfix expects `ekn`/`dwr`.
- May 4, 2026 release city-click test showed repeated native `NullReferenceException` in `Hex.UI.City.BhHireUnitItemView.UpdateView(string)` after opening/clicking city recruitment. The Stronghold `DB/units/units_logics/homm3_stronghold/*` and `DB/units/units_views/homm3_stronghold/*` members are present in the live release `Core.zip`, so this is not missing unit JSON. Treat it as the release hire-card renderer dereferencing vanilla-only serialized UI assets for custom `h3_*` SIDs. Plugin `0.1.150` rewrites only that UI method's `h3_*` argument to the existing vanilla donor SID before original rendering, then uses the saved Stronghold SID for the portrait overlay.
- May 4, 2026 release adventure/city UI quarantine: after the user reported no fog of war, failed UI initialization, and most mods doing nothing, the logs still showed playtest HUD/session/town hooks attempting stale targets and city backdrop code lifting `CanvasCityTechHUDPanel`. Plugin `0.1.151` skips old `BhHUDSession`, `Loader`, `cta`, `czk`, city backdrop, and town-layer hooks under `releaseSafeProfile`, removes `CanvasCityTechHUDPanel` from city canvas lifting, and makes missing `BhCityUISession.bynh` a quiet null path. Next porting step is a static release remap of `BhCityUISession` and adventure HUD surfaces before re-enabling city backdrops/layers.
- May 4, 2026 release UnitView data blocker: after `0.1.153` quarantined the HoMM3 visual/icon/portrait hook family, the no-HUD/no-fog bug persisted. `Player.log` provided the root path: `Hex.BhUnitPreviews.Start()` -> `clu.spp()` tried to load missing `units/homm3_import/stronghold/...` meshes such as `h3_behemoth_upg_alt`, then `BhHUDSession.iun<T>` NREd after `Session: OnGameStarted`. This is a Core data issue in release-safe mode: the playtest Stronghold unit views use synthetic `homm3_import` mesh keys that require runtime import hooks. Until those hooks are release-ported, release Core overlays must use real donor `mesh`/`mapMesh` prefab paths for Stronghold views.
- May 4/5, 2026 release SoFractions remap: after the UnitView normalization removed the missing mesh failure, the first remaining hard failure was still `Session: OnGameStarted` -> `kh.htf()` -> `cmu.swp<T>()` -> `BhHUDSession.iun<T>()`. Existing custom-faction docs identified this as missing `SoFractions` serialized faction assets. The alias patch must remain enabled in `releaseSafeProfile`; the current Steam method is `Hex.GameHub.UICommon.SoFractions.pvr(string)` by shape, with May 4 `pvs(string)` and playtest `pqu(string)` only as fallbacks.
- May 4, 2026 first re-enabled slice: after `0.1.155` restored stable adventure HUD/fog, `0.1.156` enables only targeted hero portrait/profile UI hooks under `releaseSafeProfile`. It deliberately avoids `Homm3CustomUiIconHook` global resolver scans and all map/battle/town/warcry/native-ability hooks.
- May 4-5, 2026 town-screen release remap: `0.1.185` proved the released `fbi` city wrapper capture and Steam-path asset lookup are working; the Stronghold backdrop loads and the layer placement/map JSON files are found from the deployed plugin folder. The original "backdrop only, no buildings" symptom traced statically to `BuildingsData` drift: earlier release exposed the aggregate `List<BuildingData>` as property `cnvk` and backing field `chps`, while the playtest code was still probing `cgtl/cmzg/bfht`. After the May 5 hotfix the aggregate moved again to `cnvj` / `chpr`; keep all older names only as fallbacks. `0.1.187` remaps release refresh surfaces enough for layer art to appear. `0.1.188` captures pure `fbi` values from `BhUIBuildingSession.Init(fbi)`, `BhUIBuildingSession.bzac`, and `BhBuildingView.tnw(fbi,dvw,int)`, rejects stale `tnd/tep/ezx` assumptions, and restores generated town animation frames to the deployable reference pack. `0.1.189` stops clearing backdrop/layers on `BhUIBuildingSession.OnHide` and `BhBuildingsManager.OnDisable`; those fire during build-panel transitions in release. `0.1.190` lifts city menu canvases from release town refresh postfixes before the backdrop debounce can short-circuit, because `BUILDING VIEW PANEL` is inactive during initial town apply and must be raised after the build-tree route enables it. `0.1.191` was reverted by `0.1.192` after direct generated `BhUIBuildingSession.selector` diagnostics threw `MissingMethodException` from native UI callbacks and regressed town scene display.
- May 5, 2026 full feature slice: after hotfix parity was restored through Custom Game, adventure HUD/fog, map unit/building sprites, Stronghold town scene, build tree, recruitment UI, and army-strip hero portrait, `0.1.226` reintroduced the remaining HoMM3 import custom mesh surfaces and preview hooks under `releaseSafeProfile`. `0.1.227` makes those registrations fault-isolated because a stale playtest `but` reference in the map-object unit visual hook aborted the first release-full run before later preview/tooltip hooks could register. `0.1.228` remaps the unit detail preview hook from stale `BhUnitWindowPreview.cgei` to current `char` / `beri(string,Transform)` wrappers. This uses `TryRegisterReleaseFullFeatureSlice()` instead of broad `TryRegister()` so the recovered release-safe army-strip portrait mapping remains authoritative.
- May 5, 2026 preview/town follow-up: the user confirmed `0.1.228` made the unit preview appear. The same run crashed on town entry because the gated town diagnostic snapshot indexed `Il2CppSystem.Collections.Generic.List<BhBuildingView>` during `BhUIBuildingSession.Init`; `0.1.229` makes that diagnostic Count-only. `0.1.230` fixes the later raw-localization and visual regressions: `apply_release_core_overlay.py` merges Stronghold loose Lang rows into release `Core.zip` `Lang/...` members, the Core parity script now checks archive-localized hero/city rows, recruitment preview replacement is scoped to the temporary donor alias, and the battle visual hook remaps current `ecd` fields by type (`cexw` is the live `GameObject`, stale `cexx` is now `Material`).

## Custom Game UI Findings

The no-launcher requirement changes the main work. `OfflineLauncherConfig.json`/`autoLaunchOnMenu` can remain as diagnostics, but the released port should integrate Stronghold into the in-game custom game flow.

User smoke test note from May 4, 2026: the released menu exposes two skirmish paths, **Quick Play** and **Custom Game**. Quick Play is a separate path from the configurable Custom Game flow; the user successfully reached both after release-safe menu suppression, then selected a faction and hero inside Custom Game. Stronghold integration should target Custom Game faction/hero selection first, while Quick Play can be handled separately once data injection is stable.

Static metadata/decompile candidates in released `Hex.dll`:

- `Hex.Pick.BhPickGameView`: main custom/pick UI candidate. It has `factionsData`, faction button roots/prefabs, hero ban/pick roots, `BhHeroSelectButton` lists, `BhHeroDetails`, `BhSummaryCard`, and methods including:
  - `Init()`
  - `lpx(int)` - strongly inferred `OnFactionButtonClick`
  - `lpy(int, bool)` - strongly inferred `OnHeroButtonClick`
  - `lpz(int, bool)` - strongly inferred `OnHeroButtonHover`
  - `lqd(UIState, UIState)` - strongly inferred `UpdateScreens`
  - `lqk(bool, RectTransform, float, List<HeroInfo>, List<BhHeroSelectButton>)`
  - `lqo(RectTransform, List<BhHeroSelectButton>, BhHeroDetails, bool)`
  - `lqq(bool, float, int, kw, RectTransform, BhSummaryCard)`
- `Hex.Pick.BhSummaryCard`: summary card binds `HeroConfig`, `SoFractions`, faction image, portrait, class icon, specialization icon, unit slots, and stats. Its methods include:
  - `Init()`
  - `lro(HeroConfig, string)`
  - `lrp(int, string)`
  - `lrs(HeroConfig)`
- `Hex.Pick.HeroInfo`: value type wrapping `HeroConfig config` and `bool isAvailable`; likely the object list fed to hero buttons.
- `BhHeroLoader` in the root namespace has left/right faction and hero dropdowns plus `sidsBySideId` and a faction-to-hero dictionary. This may be a secondary/debug custom loader, but it is worth tracing before implementing a separate UI.
- `SoFractions`/`FractionLobbyAsset` remains relevant. The existing `SoFractionsCustomFactionAliasPatch` fixed HUD/city UI by aliasing custom faction IDs to Dungeon assets, then cloning the Stronghold icon/banner. The same serialized-asset problem can appear in custom-game faction buttons and summary cards, so the release UI path must be tested with `BhPickGameView` and `BhSummaryCard`, not only session HUD.
- Current full native dump warning: `tools/il2cpp_out_new/dump.cs` is stale for these UI names. Released interop shows `BhPickGameView` methods `lpt` through `lqu`, while the stale dump shows older `ltu`-style names. Do not use `tools/il2cpp_out_new/script.json` RVAs for released custom-game UI until Il2CppDumper is rerun against the released `GameAssembly.dll` and `HeroesOldenEra_Data/il2cpp_data/Metadata/global-metadata.dat`.
- Current `BepInEx/LogOutput.log` did not contain Custom Game runtime breadcrumbs after the user visited Quick Play and Custom Game; it only showed plugin startup diagnostics and existing hero portrait surface dumps. Added `ReleaseCustomGameUiProbe` behind `releaseCustomGameUiProbes=true`.
- May 4, 2026 follow-up from the user's Custom Game route: the first release probe used stale playtest names and only patched `BhPickGameView.Init()` plus `BhHeroSelectButton.hpf`. Static ILSpy remap against released `Hex.dll` showed the current picker names are `BhPickGameView.luk/lue/luf/lug/lur/lux` for the old `lqd/lpx/lpy/lpz/lqk/lqq` roles, and `BhSummaryCard.lvw/lvx/lwa` for old `lro/lrp/lrs`. The probe now tries current release names first and old names second, and avoids broad `AccessTools.TypeByName` scans because they caused noisy UnityEngine type-load warnings.
- May 4, 2026 retail Custom Game route update: after the user started an actual Custom Game, all 11 `BhPickGameView`/`BhSummaryCard` methods patched but emitted zero `RCG.*` runtime lines. The full release path is the retail GameHub lobby UI instead: `Hex.GameHub.Lobby.UI.ScFractionSelect`, `ScHeroSelect`, `BhFraction`, and `BhHero`. Probe those surfaces for faction/hero SID binding; keep `BhPickGameView` notes as a separate/unused picker path until another route proves it live.
- May 4, 2026 GameHub lobby verification: `0.1.142` confirmed `ScFractionSelect.qvm()` returns vanilla faction lobby assets (`human`, `undead`, `nature`, `demon`, `unfrozen`, `dungeon`), `ScFractionSelect.qvo(string)` receives the chosen faction SID, `ScHeroSelect.qvs(string,bool,bool)` binds selected-faction hero rows, and `ScHeroSelect.qvt(string)` receives the chosen hero SID. `0.1.143` appended `homm3_stronghold` as a seventh cloned Dungeon `FractionLobbyAsset`, and logs proved the UI bound it. `0.1.144` and `0.1.145` tried Dungeon replacement/translation for path verification only; those approaches are retired for production. Current production behavior preserves Dungeon and appends a separate Stronghold entry.
- May 4, 2026 `0.1.145` user test showed the former Dungeon slot rendered with the Stronghold symbol and clicked, but the current selection did not visibly change, hero selection showed no heroes, and Start Game did nothing. The release log gave the root cause: `ScHeroSelect.iun<T>` threw `KeyNotFoundException: The given key 'homm3_stronghold' was not present in the dictionary` after `FractionSelected sid=dungeon translated=homm3_stronghold`. This confirms the UI click path reaches the lobby model; do not keep probing click handlers for this symptom. The missing layer was release `Core.zip` data registration.
- The same route exposed stale native ability wrapper code: `Homm3UnitAbilityNativeHook` threw `MissingMethodException: dwr.get_cdgt()` from `dwr.Init`. Released `BhUnitControlsView` decompile points at `dxs`-based ability controls, while old code still assumes `dwr.cdgt/cdgu` and `BhUnitControlsView.bdqs/bdqo`. The hook is now skipped under `releaseSafeProfile`; re-enable only after retracing the release native ability manager and action-bar wrapper statically.

Warning: direct PowerShell/.NET reflection enumeration of released `Hex.dll` caused a `StackOverflowException`. Use metadata-only tools such as the local ILSpy/Mono.Cecil decompiler or native disassembly; do not load and enumerate the IL2CPP interop assembly in-process.

## Core Overlay Tooling

Added read-only analyzer: `tools/release_port/analyze_core_overlay.py`.

Command:

```bash
python tools/release_port/analyze_core_overlay.py --extract-overlay
```

Outputs are ignored scratch under `tools/_tmp_release_port_core_overlay/`:

- `report.md`
- `manifest.json`
- `overlay/` when `--extract-overlay` is supplied

Current report:

- Stronghold-relevant playtest members: 1,559
- Added to release: 1,438
- Changed from release: 60
- Already same: 61
- `DB/data.json` Stronghold-only strings: `homm3_stronghold`, `homm3_fortress`
- Release hero dirs include `campaign`, `custom_maps`, and `demons`; playtest-tweaked dirs include `demon`, `dungeon_raw`, `homm3_fortress`, and `homm3_stronghold`.

Overlay rule: files marked `added_to_release` are candidates for direct overlay. Files marked `changed_from_release` are merge work items; do not overwrite release versions wholesale because they may contain released-game schema/data additions.

Added write tool: `tools/release_port/apply_release_core_overlay.py`.

Command:

```bash
python tools/release_port/apply_release_core_overlay.py
```

May 4, 2026 update: the write tool also normalizes `DB/units/units_views/homm3_stronghold/*_v.json` for release-safe testing. It keeps Stronghold ids and gameplay metadata but copies known-good donor prefab fields (`mesh`, `mapMesh`, scale/height fields) from the matching Dungeon unit views. Do not remove this while `releaseSafeProfile` quarantines HoMM3 import mesh hooks; otherwise vanilla `BhUnitPreviews.Start()` can fail before adventure HUD/fog initialization finishes.

The tool creates a timestamped `Core.zip.backup-*` beside the release archive, copies missing Stronghold-only members from the playtest-tweaked Core, and merges only token-bearing Stronghold rows into JSON files that already exist in the release archive. It intentionally excludes `homm3_fortress` and `dungeon_raw`, and it does not replace release `DB/data.json` wholesale; it only appends `homm3_stronghold` to `fractions` and `availableFractions`.

Applied to the live Steam archive on May 4, 2026:

- Target: `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip`
- Backup: `Core.zip.backup-20260504-170456`
- Update count: 744 zip members
- Verification: `DB/data.json` now has `availableFractions=human,undead,nature,demon,unfrozen,dungeon,homm3_stronghold`; `DB/fractions/7_homm3_stronghold.json`, Stronghold heroes, Stronghold subclasses, unit logic/view files, city data, and Stronghold squads exist in the release archive.

May 5, 2026 hotfix recovery: the Steam hotfix replaced the overlaid live `Core.zip` with vanilla data. Read-only parity found zero `homm3_stronghold` registrations, while the plugin still injected a seventh UI faction entry and then hit `ScFractionSelect.qvm(...)` `NullReferenceException` when selected. Reapplying `tools/release_port/apply_release_core_overlay.py` prepared 744 member updates and created `Core.zip.backup-20260505-150402`. The overlay script now skips generic re-merging of already-normalized Stronghold unit-view files, so a healthy post-apply dry run reports 0 member updates. Plugin `0.1.230` extends the same tool to merge Stronghold localization from loose playtest `Lang` files into archive `Lang/...` members; do not judge localization parity from loose `StreamingAssets\Lang` alone. Detailed recovery steps live in `docs/release_patch_recovery_log.md`.

May 5, 2026 release-full follow-up: plugin `0.1.231` addresses the first post-localization battle/preview fallout. Preview windows and the large town recruitment unit panel must donor-alias custom preview inputs before native `BhUnitWindowPreview.Show` / `beri(string,Transform)` runs, because the native factory can throw before a postfix replacement executes. Plugin `0.1.232` corrects the important split: `beri(string,Transform)` receives a unit key and should be donor-aliased to a SID such as `assassin`, while `UnitViewConfig.mesh` / `mapMesh` are prefab-path fields and should use `Dungeon/1Prefabs/...` if they need donor paths. Release battle HUD softlock recovery moved from retired `BhSelectedUnitHud.bdon` to current `BhSelectedUnitHud.beet`; the key failure signature is `KeyNotFoundException` for `h3_*` from `beet` after a Stronghold unit acts. Current release `dxs` wrapper fields are `cech` logic, `ceci` view, `cecj` bool, so ability icon/focus code must not use the stale `ceci`/`cecj` interpretation. `0.1.232` binds the release action bar through reflection over `unit.cfhm` / `dxr.bama` / `BhUnitControlsView.begt` so the source remains compatible with older interop, and it adds a Stronghold-only `BhHireUnitItemView.trs/try` NRE finalizer for the full recruit panel.

## Working Plan

1. Stabilize released loader startup.
   - Done for the first blocker: Doorstop was disabled in the release install and has been enabled; Unity log listening remains disabled to avoid the `IL2CPPUnityLogSource` access violation.
   - Done for the second blocker: release-safe profile suppresses the old menu unlock/UI-scale/histogram paths that broke main-menu interaction.
   - Next validation should be a full release launch to main menu, click through vanilla buttons into custom game, and confirm no `MainMenuNavigationView.get_quickStartButton`, `BhFont.shh`, or `ejz` errors appear in `BepInEx/LogOutput.log`.

2. Split build/deploy roots.
   - Done: `OfflineUnlockMod.csproj` accepts configurable `GameRoot`/`BepInExRoot` so the same source can target playtest or release.
   - Default deployment should not overwrite the playtest unless explicitly requested.
   - Keep the released install as a live target; do not commit copied game files.

3. Build a release Core overlay instead of copying the playtest archive wholesale.
   - Done for read-only inventory: `tools/release_port/analyze_core_overlay.py` diffs release `Core.zip` against the tweaked playtest Core for Stronghold-bearing files.
   - Port only required Stronghold rows: `DB/data.json`, `DB/fractions`, faction laws, heroes, subclasses, skills tables, unit configs, squads, city/building/barracks/map object registrations, biome/RMG hooks, localization aliases, and sounds.
   - Reconcile release naming/path differences such as `demons` versus `demon`.
   - Produce a repeatable patch/merge script so the release Core overlay can be regenerated after Steam updates.

4. Re-trace released visual/runtime hooks.
   - Use metadata and native disassembly to remap battle visual initialization, map prefab loading, tooltip portraits, army-strip portraits, selected-unit HUD, town map billboard, and dwelling billboard hooks.
   - Done for the first map-unit remap: release `UnitViewConfig.rtd()` is `UnitViewConfig.sce()` by static decompile and method shape; `0.1.146` uses shape-based discovery for HoMM3 and Esquire unit map prefabs.
   - Still open: dwelling descriptions/random-hire logic, full battle visual validation, and any fog-of-war lifecycle differences after the `sce()` hook attaches. `0.1.230` remaps the current battle visual slots by type after the hotfix changed `ecd.cexx` from the live visual object into a `Material`; do not chase `dzk.bath` in release.
   - May 4, 2026 quarantine: `0.1.153` disables the HoMM3 visual/icon/portrait/warcry hook family under `releaseSafeProfile` because adventure HUD/fog still failed after the old HUD/canvas hooks and shared preview resolver were removed. Use this to separate Core/custom-game session validity from visual hook fallout; only re-enable release visual slices after static remap.
   - Prefer resilient shape-based method discovery when the shape is narrow and static. Avoid broad reflection scans over Unity objects or interop assemblies.
   - Update `docs/il2cpp-semantic-map.md` with any confirmed/rejected symbol mappings.

5. Integrate Stronghold into custom game UI.
   - Current production route: preserve Dungeon and append `homm3_stronghold` as a seventh `FractionLobbyAsset` from `ScFractionSelect.qvl()`. Dungeon replacement and Dungeon click translation were path-verification experiments and are retired for production.
   - Data comes first: if the appended entry exists but selecting it throws `ScFractionSelect.qvm(...)` `NullReferenceException`, verify the live Steam `Core.zip` still contains Stronghold data before changing UI hooks. The May 5 hotfix reproduced exactly this failure after reverting the archive to vanilla data.
   - Keep the active picker hooks shape-based: `ScFractionSelect.qvl()`, `BhFraction(String,Sprite,bool,bool)`, `BhFraction.OnBtn/qnf`, and `BhHero(String,bool,bool,Action<T>)`. The current release `SoFractions` lookup is `pvr(string)` by shape; `pvs`/`pqu` are only fallbacks for older builds.
   - Keep the old `BhPickGameView`/`BhFactionSelectButton`/`HeroInfo` notes for non-retail picker paths, but do not prioritize them for the released Custom Game route unless runtime logs show they fire.
   - Patch `BhSummaryCard` surfaces for Stronghold hero portrait, class label/icon, faction image, specialization icon, and unit strip. Existing `Homm3HeroPortraitHook`, `Homm3HeroClassProfileHook`, and `Homm3ImportArmyStripPortraitHook` are likely reusable but need release method remaps.
   - May 4, 2026 hero UI slice update: release-safe portrait/profile surfaces are `BhHeroSelectButton.hpf`, `BhTooltipHeroItemView.tal/tam/tan`, `BhHeroPortraitView.ztr/ztu`, and `BhTavernHeroView.zbw`. The released hero data path is `Hex.Session.Logic.Hero.cbyf`/`xlt()` -> `Hex.Session.Data.Hero.configSid`; `Data.Hero.chpd/cnva` expose `HeroConfig`, whose string id fallback is `cmyj`. Do not rely on the old playtest-only `ivd`, `ipk`, or `get_heroConfig` names for release UI features.
   - May 4, 2026 follow-up: the normal release-safe log with probes off showed no hero portrait/class apply lines after startup, so Custom Game hero selection is not using the profile/tavern bind surfaces. Patch the GameHub hero tile bind directly: live release interop exposes `Hex.GameHub.Lobby.UI.BhHero.qod(string,bool,bool,Action<string>)`, which stores the hero SID and has an `icon` image field. Do not use the stale scratch-decompile `qid/3` name.
   - May 4, 2026 faction picker update: once the release Core overlay exposed `homm3_stronghold` as a real selectable faction, stop hijacking Dungeon. Production integration should leave `dungeon` untouched and only replace the banner for `homm3_stronghold`.
   - May 4, 2026 army strip update: user confirmed hero inventory portrait and class portrait work, while army strip portraits remained orange placeholders. The `0.1.160` attempt to re-enable only `BhUnitUI.Start`/`BhUnitSlots.Init` was rolled back in `0.1.161`: release logs showed repeated `MissingMethodException` for old compiled getters `BhUnitUI.vkd()` and `BhUnitSlots.vrl()` when the postfix touched `cmko`/`cmlb`. Static remap in `0.1.162`: picker/summary unit slot binder is `Hex.Pick.BhUnitSlot.lvv`, active HUD unit list is `BhUnitSlots.cnfi`/`wbv()`, unit data accessor is `BhUnitUI.cnev`/`vuk()`, and the data unit SID is `Hex.Session.Data.Unit.sid`.
   - May 4, 2026 town icon update: released `BhCityUIElement` still stores `fbe cawv` and `Image cityIcon`, with `Init(fbe)`, `vyf(int)`, and `vyg()` refresh surfaces. `0.1.162` adds `vyf(int)` and widens Stronghold city icon keys to include object-style aliases such as `city_homm3_stronghold` and `obj_city_homm3_stronghold`.
   - May 4, 2026 build-tree update: `0.1.192` restored the Stronghold town scene after reverting unsafe direct getter diagnostics. `0.1.193` keeps the restored behavior and adds only a `releaseTownUiDiagnostics.flag` gated snapshot of `BhUIBuildingSession` through raw IL2CPP field reads (`root`, `buildingsUIs`, `arrowsCg`, `bzad`, `bzae`). The next log showed no `build-session-snapshot` entries from `BhUIBuildingSession`, so `0.1.194` snapshots the owner-level `BhCityUISession.buildingSession` from the `twp/twq/twr/tws/twt/twu/twv/tww/twx/twy/twz/txa/txb/txc/txd` method cluster before reusing the build-session snapshot. The live `Core.zip` Stronghold city data has valid `parametersPerLevel.nodePos` and `prevBuildings`, so if the next log shows zero current views or inactive/transparent roots, continue tracing the native build-session UI state rather than regenerating city JSON.
   - May 5, 2026 external dwelling update: user confirmed the `0.1.212` live `bvc`-only billboard hook fixed the pass-turn crash, and then confirmed `0.1.213` gives external dwellings the Stronghold look. Descriptions remain Dungeon/default. Static Core inspection explains why the prior direct Stronghold dwelling hook missed active maps: normal generator lists place `random_hire_1..7`, while direct `barracks_*` lists live only in `generator/content_lists/test_content_lists.json`; the Stronghold `barracks_homm3_stronghold_*` object configs also reference Dungeon barracks prefabs. Remaining work is to trace the `RandomHire` resolver (`MetaObjectConfig`, `ObjRandomHireConfig`, `ObjHireConfig`, and likely `czp`/`czm`) so descriptions, faction/tier selection, and mixed-map behavior are correct instead of relying on the visual Dungeon alias.
   - May 5, 2026 battle sprite update: `0.1.214` ports the battle visual hook to release `ecd.Init(...)`. It resolves by `TransferUnit.configSid` and `homm3_import.json` `gameUnitSids`, then replaces `ecd.cexx` with the HoMM3 bundle battle prefab while updating `cext`/`ceyc`. This is intentionally narrower than the old `dzk.bath` pool hook and preserves the native battle unit controller.
   - Final start should flow through the vanilla custom game/pick UI into the normal `GameStartInfo`/`Hex.Session.Loader` path, not through `OfflineLauncherConfig.json`.

6. Validation order.
   - Loader reaches plugin load on release.
   - Release plugin logs clean guarded registration, no fatal missing-type load.
   - Stronghold appears in custom game faction selection with correct icon/banner.
   - Stronghold heroes appear after choosing the faction; summary card renders portrait/class/faction/unit strip.
   - Starting a custom game with Stronghold produces a valid session, city, hero, army, map object, town screen, recruitment, combat visuals, and HUD return from city.

## Scratch Artifacts

Ignored scratch used for this investigation:

- `tools/_tmp_release_port_compile/OfflineUnlockMod`: disposable source copy with release-relative references.
- `tools/_tmp_release_port_compile/release_custom_game_ui_decompiled.cs`: filtered ILSpy output for released `Hex.dll`.
