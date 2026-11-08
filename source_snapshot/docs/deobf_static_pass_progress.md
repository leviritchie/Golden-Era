# Golden Era Static Pass Progress

This is the running log for the deobf-folder cleanup pass. Work one feature surface at a time. Prefer current Cpp2IL/readable decompile and Golden Era interop metadata over inherited short-name assumptions. Prefer native/upstream lifecycle paths over late cleanup, broad reflection sweeps, or donor fallbacks.

## Workflow

1. Pick one feature surface.
2. Record the current symptom or risk.
3. Compare source assumptions against `experiments/cpp2il_readable_csharp` and installed Golden Era interop metadata.
4. Centralize current names/shapes in `GameSymbols` or a local helper before using them.
5. Remove stale or broad late-patch behavior when the native surface is known.
6. Build against Golden Era, deploy only after the focused surface builds cleanly, and record provenance.

## 2026-06-14 - Selected-Unit Ability Click Identity

Status: source patch ready; subagent review/deploy/provenance pending.

Why this surface: the prior failed deobf experiment could still have correct click/select symbols but fail ability toggling if the click re-entry guard misidentified IL2CPP wrapper instances. Static metadata confirmed the public controls click and private `dxy` selection surfaces exist, so the next easy win was to check the guard between those surfaces.

Static evidence:

- Installed Golden Era interop exposes `BhUnitAbilityView.OnClicked`, `BhUnitControlsView.Method_Public_Void_BhUnitAbilityView_0`, and two private `void(dxy)` methods, including the selected-object setter `Method_Private_Void_ObjectPublicObceInBoInceAbObELInUnique_PDM_0`.
- The source correctly resolves `belt` / generated `PDM_0` through centralized `ControlsSelect` and fails closed if only ambiguous same-shape `void(dxy)` methods are available.
- The click forwarding guard still used `ReferenceEquals(_releaseAbilityClickView, __0)` when `OnClicked()` entered controls click. Harmony/IL2CPP wrappers are not guaranteed to preserve CLR reference identity for the same native object.

Correction:

- `Homm3ImportBhSelectedUnitHudFix` now compares `Il2CppObjectBase.Pointer` identity via `SameIl2CppObject` for release click re-entry checks.
- This prevents the outer `OnClicked` postfix from invoking `belt(dxy)` a second time after the native controls click already selected/cleared the action.
- No symbol lists were broadened, and the change does not enable the explicit SID/config-built action-bar fallback.

Pending:

- Subagent review, deploy to Golden Era if clean, and runtime proof in combat.

## 2026-06-14 - Law Icon / Faction Law UI Surface

Status: source patch ready; build/review/deploy pending.

Why this surface: `LawIcon` was still pending in the audit inventory, and agent notes claimed the required startup surface was `zeb(dtd,dqj)` / `zed()`. Current readable Cpp2IL shows that assumption is stale for Golden Era.

Static evidence:

- Current readable `BhFractionLawView` binds through `zgh(dtj, dqp)` and refreshes through `zgj()`.
- Installed Golden Era interop exposes generated mirrors `Method_Public_Void_Object1PublicSiObFrObccSiLiObcc1Unique_ObjectPublicDaccObLicc1QuObSt1Unique_0` and `Method_Public_Void_0`.
- Current readable `dqp` owns `DataFractionLaw ccep`, exposes `FractionLawConfig cnpl`, and has getter `xow()`.
- Current readable `DataFractionLaw` owns `FractionLawConfig chvf`, exposes property `cobp`, and has getter `bfwo()`.
- Current readable `FractionLawConfig` owns the actual `icon` string field.

Correction:

- `GameSymbols.LawIcon.FractionLawViewBind` now prefers current `zgh` plus the installed generated mirror, with stale readable `zez` removed from the required surface.
- `GameSymbols.LawIcon.FractionLawViewRefresh` now prefers current `zgj` plus the installed generated mirror, with stale readable `zfb` removed from the required surface.
- `Homm3StrongholdLawIconHook` now requires the selected bind/refresh method to match the centralized current/generated symbol hints before patching, so stale same-shape methods cannot satisfy the required gate.
- The bind candidate is constrained to current law side/law parameter types (`dtj`/generated side and `dqp`/generated law object).
- Law icon resolution now includes current `dqp` and `DataFractionLaw` config fields/getters before older compatibility routes.

Pending:

- Build against Golden Era, run required subagent review, deploy if clean, and record DLL provenance.

## 2026-06-14 - Warcry Hero Ability Icon Surface Recheck

Status: source already corrected; stale audit notes updated.

Why this surface: the audit matrix still marked the Warcry hero ability icon route as `Drift`, but later source/provenance notes suggested this surface had already been repaired. This recheck prevents future agents from "fixing" it back to an older wrapper contract.

Static evidence:

- Current readable Cpp2IL `BhHeroAbilitiyView` stores direct ability `edn bydd`, context `bzd byde`, carrier `emb bydf`, and binds through `sli(bzd, emb)`.
- Current readable `BhHeroAbilitiesView` binds through `ski(bzd,List)`, `skj(bzd,List)`, `skk(bzd,ead,List)`, and refreshes through `skp(edn)`.
- Current readable `emb` exposes hero abilities through `beuf(out edn)` and `cwk(out edn)`, while `bzd` carries the active hero ability in `bwhs`.
- Current source already has those names first in `GameSymbols.WarcryHeroAbility`, traverses `heroAbilities` / `separateHeroAbilities`, keeps icon logging behind `homm3_warcry_hero_ability_diag.flag`, and uses idempotent sprite application.

Correction:

- No source behavior change was needed in this pass.
- `docs/cpp2il_surface_audit_20260613.md` now marks the Warcry hero ability icon row as already implemented and deployed.
- `AGENTS.md` now warns against regressing this route to older `skk/sjk/sjl/sjr`, `skw/sjw/sjx/skd`, `edg/els`, or `elz` contracts.

Pending:

- Runtime proof is no longer pending for custom hero-action icon presentation: the June 25 deployed follow-up was successful in both tested factions. Future regressions should start with `Homm3CustomHeroAbilityIconSpriteCache` row/level load count and zero-row fail-closed behavior, not with old wrapper contracts or image-scan fallbacks.

## 2026-06-14 - Map-Squad Visual Controller Symbol Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the static audit still had the map-squad visual controller marked partial. This lane remains explicit-gated and unsafe to enable broadly, but its required startup surface should still match current readable Cpp2IL when an isolated fog-visibility validation pass enables it.

Static evidence:

- Current readable Cpp2IL `ezp` is the map-squad visual controller and exposes `Init(fdh, ctr)`.
- Current readable `ezp` exposes root backing field/property `cjbb`, root getter `bigc()`, and view config field `cjbf`.
- Current readable `fdh` owns the controller backing property `cjog`.
- Installed Golden Era interop exposes generated owner/type mirrors: `ObjectPublicGaObcjObUncjAnBhObStUnique`, `ObjectPublicDaInVeInBoObcjObBocoUnique`, `MonoBehaviour1PublicObmeLa1caObMeDaNoBoUnique`, and root getter `Method_Public_get_GameObject_0`.

Correction:

- `GameSymbols.MapSquadVisual.InitContextTypeHints` now includes current readable `ctr` between the generated mirror and old `ctq` compatibility hint.
- `GameSymbols.MapSquadVisual.RootGetter` now prefers current readable `bigc`, then the generated root getter mirror, then older `biee` compatibility.
- Visibility-like current bool methods `bigo`, `cow`, and `npa` were intentionally not added because static Cpp2IL alone does not prove which method drives draw visibility.
- `homm3ReleaseMapSquadVisualController` remains disabled by default outside an isolated map-fog validation pass.

Verification:

- Golden Era build passed with 0 errors and 44 existing warnings.
- Required subagent review found no drift, hallucinated symbols, silent fallback/bug risk, centralization violation, or patchy non-native fix in this scoped symbol repair.
- Deploy build passed with 0 errors and 44 existing warnings.
- Deployed DLL hash matches release output: `6AB305F5279ED7D4145F14DB316E2B967189C52082596A9A120FB5D8BBEDF3F3`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.
- Runtime proof requires an explicit map-fog validation pass with `homm3ReleaseMapSquadVisualController=true`; this static pass does not enable that lane.

## 2026-06-14 - Projectile Ability Symbol Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the ability audit still had projectile ability config/controller symbols pending, and `GameSymbols.Projectile` was still ordered around older May smoke names rather than the current readable Cpp2IL plus installed Golden Era interop.

Static evidence:

- Current readable Cpp2IL `AbilityViewConfig` exposes `ProjectileConfig rog()`.
- Current readable Cpp2IL `HeroAbilityLevelConfig` exposes `ProjectileConfig rwf()`.
- Current readable Cpp2IL `BhProjectileController` exposes `bbst(Vector3, Vector3, Vector3)` and virtual `bbsv(float)`.
- Installed Golden Era interop exposes generated mirrors `Method_Public_ProjectileConfig_0` on both config owner types, plus `Method_Public_Void_Vector3_Vector3_Vector3_0` and `Method_Public_Virtual_Void_Single_0` on `BhProjectileController`.

Correction:

- `GameSymbols.Projectile.AbilityViewProjectileGetter` now prefers current `rog`, then the generated owner mirror, then old compatibility aliases.
- `GameSymbols.Projectile.HeroAbilityLevelProjectileGetter` now prefers current `rwf`, then the generated owner mirror, then old compatibility aliases.
- `GameSymbols.Projectile.ControllerSetPositions` / `ControllerUpdate` now prefer current `bbst` / `bbsv`, then generated mirrors, then old compatibility aliases.
- `homm3ReleaseProjectile` remains disabled by default; this pass only fixes explicit release-safe projectile registration when enabled.

Verification:

- Golden Era build passed with 0 errors and 44 existing warnings.
- Required subagent review found no drift, hallucinated symbols, silent fallback/bug risk, centralization violation, or patchy non-native fix in this scoped symbol repair.
- Deploy build passed with 0 errors and 44 existing warnings.
- Deployed DLL hash matches release output: `89462596CD3AF4AD2D40CD45C326ADA0E5763FF1B567C80D033A5B62530A5427`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.
- Runtime proof still requires a dedicated combat projectile trace before enabling the projectile visual slice by default.

## 2026-06-14 - Terrain Material Getter Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the Cpp2IL audit still showed a concrete drift in `GameSymbols.TerrainMaterial`: current readable `SoTerrainMaterial` getter names were missing, forcing terrain hooks to rely on generated mirrors or older compatibility aliases.

Static evidence:

- Current readable Cpp2IL `Hex.Render.SoTerrainMaterial` exposes `public static SoTerrainMaterial kwf()` and `public Material kwg()`.
- Installed Golden Era interop exposes generated mirrors `Method_Public_Static_SoTerrainMaterial_0` and `Method_Public_Material_0`.
- `kwg` is also present on the terrain renderer build-map symbol, but that is a different owner type and method shape; owner/type disambiguation is intentional.

Correction:

- `GameSymbols.TerrainMaterial.InstanceGetter` now prefers current readable `kwf`, then the generated Official mirror, then older compatibility aliases.
- `GameSymbols.TerrainMaterial.MaterialGetter` now prefers current readable `kwg`, then the generated Official mirror, then older compatibility aliases.
- No packed terrain rebuild candidates, renderer map hooks, terrain sound hooks, or per-tile lookup behavior were changed in this pass.

Verification:

- Golden Era build passed with 0 errors and 44 existing warnings.
- Required subagent review found no drift, hallucinated symbols, silent fallback/bug risk, centralization violation, or patchy non-native fix in this scoped symbol repair.
- Deploy build passed with 0 errors and 44 existing warnings.
- Deployed DLL hash matches release output: `13D53E1D977C1A93E12F7E863F54C72B975AA24D3AC17A5605268B65CF5ABC12`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.
- Runtime proof is not expected from this symbol-only pass unless terrain material hook registration fails or terrain behavior regresses after deploy.

## 2026-06-14 - Selected-Unit Ability Wrapper Split

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the failed deobf experiment still left ability toggling suspect. A focused static reread showed the previous symbol table had collapsed two current native wrapper families into one list, which could make release action-bar controls resolve the UI/view wrapper instead of the real action-bar ability wrapper if readable names ever resolved first.

Static evidence:

- Current readable Cpp2IL `BhUnitControlsView` binds and selects `dxy` ability wrappers: `beln(dxy[], dxy, bool)` and private `belt(dxy)`.
- Current readable `BhUnitAbilityView` owns `emb chae` as the view wrapper and `dxy chaf` as the actual ability wrapper; bind is `beky(emb, bool)`.
- Current readable `emb` exposes `beue(out dxy)` / `oku(out dxy)`, proving it is an intermediate UI wrapper, not the action-bar ability object.
- Installed Golden Era interop mirrors this split: `ObjectPublicObceInBoInceAbObELInUnique` has `AbilityLogicConfig`/`AbilityViewConfig` fields and is used by controls bind/select arrays, while `ObjectPublicObBochBoObchBochBoUnique` has generated out-methods returning that ability wrapper and is used by `BhUnitAbilityView` bind.

Correction:

- Added `GameSymbols.SelectedUnitHud.AbilityWrapperTypeNames` for the real action-bar ability wrapper family (`ObjectPublicObce...`, readable `dxy`, old compatibility `dwr`).
- Kept `AbilityViewWrapperTypeNames` scoped to the UI/view wrapper family (`ObjectPublicObBo...`, readable `emb`, older `elz`/`els`/`ekn`).
- `GameInteropTypes.ReleaseAbilityWrapperType` and its native alias helper now use `AbilityWrapperTypeNames`, so release controls/manager selection no longer depends on the view-wrapper list.
- Warcry helper wrapper recognition now checks both selected-unit wrapper families where it intentionally accepts broad known wrapper types.

Pending:

- Runtime-check custom ability mouse toggle, hotkey toggle, and selected-state lighting. This patch removes a bad static assumption but does not prove the live scene binds custom controls correctly.

Verification:

- Golden Era build passed with 0 errors and 44 existing warnings.
- Required subagent review found no drift, hallucinated symbols, silent fallback/bug risk, centralization violation, or patchy non-native fix in this scoped split.
- Deploy build passed with 0 errors and 44 existing warnings.
- Deployed DLL hash matches release output: `B0D62A07AEFBDF3B0628336D1B44F5F06FBB47B598620BDB193E688779969FA0`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

## 2026-06-14 - Recruitment/Detail Preview Owner Fields and Party Selector Slot Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the preview audit showed the recruitment/detail code still relied heavily on generated owner-field names and older party-selector slot aliases. In particular, the unit-window party selector SID bind was still `bamz`-first even though current readable Cpp2IL shows `BhUpgradeUnitSlot.baon(...)`.

Static evidence:

- Current readable `BhHireUnitItemView` owns exact fields `RawImage raw` and `BhUnitPreview bzic`; it also exposes raw getter `tvg()` / property `cnju`.
- Current readable `BhUnitPreview` owns exact `GameObject root` and getter `sre()` / property `cnhw`.
- Current readable `BhHireUnitAbilities` binds through `hun(Unit)`.
- Current readable `BhHireUnitAbilityView` owns `Image pic` and binds through `bann(bzd, AbilityViewConfig)` / `bano(AbilityViewConfig, bzd)`.
- Current readable `BhUpgradeUnitSlot` owns current bound unit/SID fields `cegy` and `cehc`, getters/properties `baok()` / `cnxt` and `baom()` / `cnxv`, and current SID bind `baon(string, int, Action, int, bool)`.
- Installed Golden Era interop exposes generated mirrors: `field_Private_RawImage_0`, `field_Private_BhUnitPreview_0`, `Method_Public_get_GameObject_0`, `field_Private_Unit_0`, `Method_Public_get_Unit_0`, `field_Private_String_0`, `Method_Public_get_String_0`, and SID bind `Method_Public_Void_String_Int32_Action_1_BhUpgradeUnitSlot_Int32_Boolean_0`.

Correction:

- `GameSymbols.UnitPreviewAbilityIcons` now includes the readable and generated owner fields/getters for hire-card native raw image, owned `BhUnitPreview`, and preview root.
- `Homm3CustomUiIconHook.HideHireUnitNativeDonorVisuals` now uses the existing member-or-no-arg helper for those exact owners so current getter symbols can resolve before falling back to child RawImage/Renderer heuristics.
- `GameSymbols.UnitPreview.PartySelectorSlotSidBind` now prefers current readable/generated `baon` before old compatibility aliases.
- `GameSymbols.UnitPreview.PartySelectorSlotUnitFields` and `PartySelectorSlotSidFields` now include current readable and generated owner fields/getters before old aliases.
- Existing exact ability-row symbols `hun`, `pic`, `bann`, and `bano` were already present and were left intact.

Pending:

- Runtime-check recruitment/detail preview ability rows and the unit-window party selector slot portraits.

Verification:

- Golden Era build passed with 0 errors and 44 existing warnings.
- Required subagent review found no drift, hallucinated names, new broad silent fallbacks, centralization violations, or patchy non-native fixes in this scoped change.
- Deploy build passed with 0 errors and 44 existing warnings.
- Deployed DLL hash matches release output: `C2D07647CB589B5F4EE5821DCE980583A6EA86417384B7242F623F963A4F4D38`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

## 2026-06-14 - Custom Biome Minimap Build Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the minimap audit showed stale build/render method aliases. The custom biome minimap hook extended `SoMinimapConfig.bioms`, but it patched only one resolved build-map wrapper. Current deobf output shows several sibling build-map wrappers, so one-method registration can miss the native entrypoint used by a specific minimap path.

Static evidence:

- Current readable `bcv` is the minimap renderer and exposes build-map wrappers `hbi(bcr, Map, SoMinimapConfig)`, `hev(...)`, `kcn(...)`, `klt(...)`, and `kym(...)`.
- Current readable `bcv` exposes private render-data bodies `fbm(RenderTexture, MapData, RectInt, SoMinimapConfig, bool)`, `fln(...)`, `klu(...)`, `laf(...)`, and `lxx(...)`.
- Installed Golden Era `Hex.dll` exposes the renderer as generated `ObjectPublicInbrStInbrCoStMaInbrUnique`, not stable `bcv`.
- Installed Golden Era interop exposes exact generated build wrappers `Method_Public_Void_ObjectPublicRebrRebrUnique_Map_SoMinimapConfig_0` through `_4`.
- Installed Golden Era interop also exposes generated private render-data wrappers `Method_Private_Void_RenderTexture_MapData_RectInt_SoMinimapConfig_Boolean_0` and `_PDM_0` through `_PDM_3`.

Correction:

- `GameSymbols.Minimap.RendererBuildMapCurrent` now centralizes all current generated build wrappers plus readable `hbi`/`hev`/`kcn`/`klt`/`kym`; `RendererBuildMap` keeps older compatibility aliases behind those current names.
- `GameSymbols.Minimap.RendererRenderMapData` now centralizes only the runtime-proven current generated private render-data body `Method_Private_Void_RenderTexture_MapData_RectInt_SoMinimapConfig_Boolean_0` and readable `klu`.
- `Homm3CustomBiomeMinimapHook` now patches that exact render-data surface instead of public build-map wrappers. This is intentionally fail-closed: if the exact render-data symbol moves, registration should fail and force a symbol repair rather than guessing by shape.
- The earlier public-wrapper approach was rejected after runtime: deployed hash `C4E15FC...` still stack-overflow crashed immediately after indexed minimap config mutation because the hook patched all five generated public build wrappers. Deployed hash `6733AE8E...` proved the private render-data target by reaching `HOMM3_MAP_LOAD_PROFILE shells=200`, hero HUD init, and Cove town billboard scan with the process still responding.

Verification:

- Golden Era build passed with 0 errors and 44 existing warnings before review.
- Required post-runtime subagent review found the first render-data fix still had same-shape/public-wrapper fallbacks and a permanent retry-suppression bug on minimap config mutation failure. The follow-up deployed as `ED3DFAA...` removed those fallbacks, stopped marking failed config mutations as applied, and passed the same auto-launch map-load verification with the process still responding.
- Rebuild/deploy details for the final follow-up are tracked in `docs/offlineunlockmod_dll_provenance.md`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Pending:

- Runtime-check that custom biome minimap textures are present without shape-fallback renderer resolution or repeated config extension.

## 2026-06-14 - Cove After-Shot Buff Manager Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the Cove after-shot Disrupting Ray rewrite depends on exact `dzv` buff-manager method names. Production still preferred older names and only reached current Golden Era through shape fallback, which is fragile for a broad buff manager full of many string methods.

Static evidence:

- Current readable `dzv` exposes the native buff-add method as `bbgf(string,int,int,eab,int,bool) -> dzt`.
- Current ISIL xrefs show native calls to `dzv.bbgf` from multiple battle/mechanic paths, including `dxx`, `efd`, `efq`, `ehg`, `ehw`, and `eif`.
- Current readable `dzv` exposes by-SID buff query surfaces as `bbfn(string) -> bool` and `bbfl(string) -> List`.
- Current ISIL xrefs show native `bbfn(string)` use as a by-SID presence check from `dyi`, `dyl`, and `ecg`.
- `bbfl(string) -> List` is supported by signature/type/local grouping, but no direct ISIL caller was found in this pass.
- No native-friendly evidence supports broadening this into arbitrary `dzv` string helpers; the hook should stay on exact add/check surfaces.

Correction:

- `GameSymbols.CoveAfterShot.BuffAddMethods` now prefers current exact `bbgf`.
- `GameSymbols.CoveAfterShot.BuffListMethods`, `BuffListHasBool`, and `BuffListBySid` now prefer current exact `bbfn` / `bbfl`.
- `GameSymbols.CoveAfterShot.BuffAddShape` includes current `bbgf` before old compatibility names.
- No hook behavior was broadened; the existing prefix still rewrites only repeated Weakness from recognized Cove after-shot casters after a native by-SID Weakness check succeeds.

Verification:

- Golden Era build passed with 0 errors and 44 existing warnings.
- Required subagent review found no blockers. It independently confirmed `dzv.bbgf` is the current buff-add path, `dzv.bbfn` is the current by-SID presence check, and `dzv.bbfl` is a defensible current by-SID list method.
- Deployed DLL hash matches release output: `C3B545973D54D90269F2B5559D135FB7D048F7987186194D2158368556F7FDC0`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Pending:

- Runtime proof should trigger a Sea Witch/Sorceress repeated Weakness after-shot and confirm it rewrites to the Cove Disrupting Ray effect through `dzv.bbgf`, with no broad buff-manager string hooks involved.

## 2026-06-14 - Damage Forecast Histogram Calculator Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the damage histogram/forecast overlay has a broad fallback scan when the configured native calculator type hints do not resolve. Previous agents left old forecast names in `GameSymbols`, and the current readable dump shows the active forecast DTO/calculator moved again.

Static evidence:

- Current readable `ell` is the active static damage-forecast calculator surface. ISIL xrefs prove `bert(DamageUiParams,bool) -> elk` usage; `hem(DamageUiParams,bool) -> elk` is a same-shape calculator method on the same current surface.
- Current `elj` no longer has forecast calculator methods; it returns `eln` from `FieldObject`.
- Current `eky` is target-tooltip mapping, not damage forecast calculation.
- Current `elc` is a target-tooltip/state class, not the result DTO.
- Current readable/ISIL `elk` owns the forecast result fields. `BhHealDamageForecastPanel.Show(elk)` passes `chdd/chde` to `bera(...)` for damage and `chdi/chdj` to `berb(...)` for killed stacks.
- The legacy `RetaliationForecastFix` `Show(ekx)` patch is not a current Golden Era surface; current `BhHealDamageForecastPanel.Show` takes `elk`, and release-safe profile already excludes the old debounce patch.

Correction:

- `GameSymbols.BattleForecast.CalculatorTypeHints` now prefers current `ell` before old compatibility hints.
- `GameSymbols.DamageForecast.FieldGroups` now prefers current `elk` result fields `chdd/chde/chdi/chdj` before old compatibility groups.
- No broad panel-hide suppression or old `Show(ekx)` revival was added.

Verification:

- Golden Era build passed with 0 errors and 44 existing warnings.
- Required subagent review found no blockers. It independently confirmed `ell` is the current forecast calculator surface and that `elk.chdd/chde/chdi/chdj` map to displayed damage min/max and killed-stack min/max through `BhHealDamageForecastPanel.Show(elk)` panel usage.
- Deployed DLL hash matches release output: `F3F4603165BE028E4E466F92C359294C29D48EEFA450F30C6CBF4F0B0145144C`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Pending:

- Runtime proof should hover a normal damage forecast and a retaliation/counterattack forecast, then confirm the histogram records current `ell/elk` values without falling back to broad calculator scans or legacy panel-hide suppression.

## 2026-06-14 - Selected-Unit Ability Symbol Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the previous static ability work correctly identified several current selected-HUD methods, but runtime behavior still failed. The follow-up question was whether the decompilation itself was misleading or whether production was still incomplete around ability-specific symbols.

Static evidence:

- Current readable `BhSelectedUnitHud` exposes event bind `bejn(object, BattleEventArgs)` and direct bind `bejo(bool, Unit)`.
- Current readable `ede` is the `Unit` base that owns the ability manager through field `cfng` and getter `bcud()`.
- Current readable/ISIL `BhUnitControlsView.beln(dxy[], dxy, bool)` writes `chap`, builds ability views, and calls `belt(selected)`.
- Current readable/ISIL `BhUnitControlsView.belt(dxy)` is the native selected-wrapper sync path: it clears prior state, writes `chao`, and updates the clicked view's selected boolean.
- Current `BhUnitAbilityView` stores the wrapper and underlying ability at `chae` and `chaf`.
- Current `dxy` stores `AbilityLogicConfig` and `AbilityViewConfig` at `cejb` and `cejc`.
- Current hire/detail ability rows bind through `BhHireUnitAbilityItemView.banl/banm`, `BhHireUnitAbilityView.bann/bano`, and icon field `pic`.

Correction:

- `GameSymbols.SelectedUnitHud` now includes current `bejn`, `cfng` / `<cfng>k__BackingField`, `bcud`, `chaf`, and `chae`.
- `GameSymbols.BattleUi` now includes current selected-HUD bind names `bejn` and `bejo`.
- `GameSymbols.BattleCommand` now prefers current `dxy` config fields `cejb` and `cejc`.
- `GameSymbols.UnitPreviewAbilityIcons` now centralizes current ability-row bind/icon names `banl`, `banm`, `bann`, `bano`, and `pic`.

Verification:

- Golden Era build passed with 0 errors and 44 existing warnings.
- Required subagent review found no blocking issue in the `GameSymbols.cs` change. It independently checked the current Cpp2IL/ISIL surfaces for `BhSelectedUnitHud`, `BhUnitControlsView`, `BhUnitAbilityView`, `ede`, `dxy`, `BhHireUnitAbilityView`, and `BhHireUnitAbilityItemView`.
- Deployed DLL hash matches release output: `E698ECD84D1ABDE8774D76E834A2BCE33CF37F04A1C55CB5AD28C4C38808FFD9`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Pending:

- Runtime-check ability toggling with diagnostics off. This patch is intentionally symbol-table-only; it proves the decompilation was useful but does not by itself prove runtime click/toggle behavior.

## 2026-06-14 - Selected-Unit Ability Click/Wrapper Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the prior selected-unit ability static pass proved useful names, but user verification still showed ability toggling was not fixed. A deeper static pass compared the current readable Cpp2IL lane with the exact installed Golden Era interop metadata used by `OfficialDeobfBuild=true`.

Static evidence:

- Current readable `BhUnitControlsView.belo(BhUnitAbilityView)` is the public click path.
- Current readable `BhUnitControlsView.belq(BhUnitAbilityView)` is a private ability-view sync helper, not the selected ability object setter.
- Current readable `BhUnitControlsView.belt(dxy)` is the selected ability object path.
- Installed Golden Era `Hex.dll` exposes the same surfaces under generated names: `Method_Public_Void_BhUnitAbilityView_0`, `Method_Private_Void_BhUnitAbilityView_PDM_0`, and `Method_Private_Void_ObjectPublicObceInBoInceAbObELInUnique_PDM_0`.
- Installed Golden Era `BhUnitAbilityView` bind is `Method_Public_Void_ObjectPublicObBochBoObchBochBoUnique_Boolean_PDM_0`.
- Installed Golden Era UI wrapper exposes generated out methods `Method_Public_Boolean_byref_ObjectPublicObceInBoInceAbObELInUnique_PDM_0` and `_PDM_1`.

Correction:

- `GameSymbols.SelectedUnitHud.ControlsClick` no longer treats the generated private `BhUnitAbilityView` method as a click handler.
- `GameSymbols.SelectedUnitHud.ControlsSyncAbilityView` now owns that private sync method.
- `GameSymbols.SelectedUnitHud.AbilityViewBind` and `AbilityWrapperTryGetAbility` now include exact Golden Era generated names.
- `Homm3ImportBhSelectedUnitHudFix.GetReleaseAbility` now falls back from direct ability fields/cache to unwrapping the UI wrapper through centralized out-method names, accepting only the already-resolved native action-bar ability type.

Verification:

- Golden Era build passed with 0 errors and 44 existing warnings.
- Required subagent review found no blockers. It confirmed the patch stayed scoped to the current ability click/wrapper surface and noted only the remaining need for runtime toggle verification.
- Deploy build passed with 0 errors and 33 existing warnings.
- Deployed DLL hash matches release output: `70A21BF5BE79F703F9864BB457741BC36C27C2035065A1AB958875C873F3D0E4`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Pending:

- Runtime-check ability mouse toggle on/off with diagnostics off. This pass corrects the static click/wrapper surface; it still needs a live combat check to prove selected visuals and repeat-click clear behavior.

## 2026-06-14 - Unit Detail Preview Wrapper/Factory Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the failed `A369E573...` run still showed stale `TypeLoadException: Could not load type 'clb'`. This is a concrete deobf-folder symptom that previous preview work was built on old wrapper names.

Static evidence:

- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/clb.cs` now shows `clb` as an empty `MonoBehaviour`, not the unit preview wrapper.
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/clt.cs` shows the preview wrapper fields: `Rotatable`, `Model`, `Background`, `Sid`.
- `BhUnitWindowPreview.cs` stores `clt chgx` and its string/`Transform` factory returns `clt bewc(...)`.
- `BhUnitPreviews.cs` uses `clt prefab` and `bool htv(string,float,out clt)`.
- Installed Golden Era interop does not expose stable CLR types named `clb` or `clt`; it exposes `MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique` with `Rotatable`, `Model`, `Background`, and `Sid` accessors.

Correction:

- `Homm3ImportUnitPreviewModelHook` now treats preview wrappers as `object`/`Component` and uses the existing semantic `Model`/`Rotatable`/`Background`/`Sid` reflection path.
- Direct `clb` type use was removed from the release preview hook.
- The broad `Homm3ImportClbPreviewFactoriesHook` scanner is excluded from `OFFICIAL_DEOBF_BUILD`; it is not part of the native-friendly release path and still belongs to the legacy non-Official lane.
- `GameSymbols.UnitPreview` now centralizes the current wrapper field/type/factory shapes: `field_Private_MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique_0`, `chgx`, `MonoBehaviourPublicSealedGaRoMoGaMeBaStSiUnique`, `clt`, `bewc`, and `htv`.

Verification:

- `dotnet build OfflineUnlockMod.csproj -c Release -p:GameRoot=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era -p:OfficialDeobfBuild=true -p:DeployPluginToGame=false -v:minimal` passed with 0 errors.
- Existing warning set remains; one temporary new dead-field warning from the typed log path was removed after the first build.
- Required subagent review caught one stale helper assumption: the shared preview-factory matcher still recognized only `out cls`. That was replaced with a centralized preview-wrapper shape matcher before the final deploy.
- Deploy build passed with 0 errors and 33 existing warnings.
- Deployed DLL hash matches release output: `31C4D7E9936C711E05774AD07D3729E0725760746CB7325C3347A6DB7245CD3A`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.
- Deployed assembly string check no longer contains `Homm3ImportClbPreviewFactoriesHook`, `FindStringOutClsMethod`, or `IsByRefCls`.

Pending:

- Runtime proof still requires launching a detail preview and confirming no `clb` `TypeLoadException` plus correct detail overlay behavior.

## 2026-06-14 - Adventure Map Town Billboard PropCity Resolver Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the failed `A369E573...` run still had town billboard duplication symptoms, and prior notes showed the native-friendly route is PropCity identity from placed map-object id -> `Map.ObjectsProperties` -> `PropCity.factionSid`. If that route misses, the code falls back to exact-root/section finalizers that can produce stale or duplicate markers.

Static evidence:

- Current readable `bvc` owns the placed-object state used by `bvb`: `bvqf` node, `bvqg` rotation, `bvqk` map, `bvqp` root `GameObject`, and `bvqq` root `Transform`.
- Current readable `Map` exposes `ObjectsProperties` through property `cmwh` and method `ogc()`.
- Current readable `ObjectsProperties` has the scoped object-prop accessors `ovi(EType,int)` and `ovj(EType,int)`.
- Current readable `ObjectsProperties` exposes `propCities` as the fourth list, with property `cmxl` and method `oum()`.
- `ObjectProp.EType.MapObject` is enum value `0`, matching the resolver's existing enum argument construction.

Correction:

- `GameSymbols.CustomTownMapBillboard.MapObjectsPropertiesGetters` now prefers current `ogc` / `cmwh` names before stale map-property candidates.
- `GameSymbols.CustomTownMapBillboard.MapObjectPropertiesGetters` now prefers current `ovi` / `ovj` typed scoped accessors.
- `GameSymbols.CustomTownMapBillboard.PropCitiesGetters` now includes current `oum` / `cmxl`.
- The existing centralized `Homm3MapObjectPropCityResolver` remains the owner of PropCity lookup; no resolver copy or section-root cleanup expansion was added.
- Required subagent review found one P3 comment drift: the local source comment still named stale `ouk` / `oui` accessors. The comment was corrected before deployment.

Verification:

- Golden Era build passed with 0 errors and 44 existing warnings.
- Deploy build passed with 0 errors and 44 existing warnings.
- Deployed DLL hash matches release output: `1BE294624CF431E98E27EF027A9FDDAC65067AFF6B4FB79B875C4B9AB68244F4`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.
- Deployed assembly string check contains the current resolver symbols: `ogc`, `get_cmwh`, `ovi`, `ovj`, `oum`, and `get_cmxl`.

Pending:

- Runtime proof should check that generic `city-spawner` / `random-city` objects resolve custom city identity through PropCity without relying on exact-root finalizer cleanup, and that only one owned `homm3_custom_city_billboard_*` marker remains at the town placement.

## 2026-06-14 - Spawned/Summoned Battle Visual Helper Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the failed deobf run still had mid-combat summoned custom units defaulting to donor visuals. Prior static work had noticed `enk.bffg/fua`, but behavior was not fixed, so the question was whether the decompile was misleading or whether our implementation used it incompletely.

Static evidence:

- Current readable `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/enk.cs` exposes two exact helpers, `enk.bffg` and `enk.fua`, both returning `FieldObject` and both shaped `(edh, Unit, eir, int, string, bool, bool, bool)`.
- Current production had centralized both names in `GameSymbols.BattleVisual.SpawnObject`, and the shared matcher already accepted both legacy 6-arg and current 8-arg shapes.
- The implementation still called `ResolveNativeSpawnObjectMethod()`, which returned only the first exact helper. If native summon/spawn routes split across `bffg` and `fua`, the second route never ran the custom visual recovery postfix.
- The same helper matcher can see same-shape methods, so broad patching must be exact-name-first: patch all exact `bffg/fua` matches when present, and use shape matches only as a fallback when no exact names exist.

Correction:

- `Homm3BattleVisualInterop` now exposes `ResolveNativeSpawnObjectMethods(...)`, preserving the old single-method API for callers that need one method.
- The multi-method resolver returns all exact centralized-name matches first, and returns shape fallback methods only when no exact match exists.
- `Homm3ImportReleaseBattleVisualHook` now patches every resolved exact spawn helper with the spawned-unit postfix and logs the full patched helper set.
- `PostfixSpawnObject` now parses Harmony `__args` by stable positions (`source Unit` at index 1, requested SID at index 4), so the same observer is compatible with both legacy 6-arg and current 8-arg helper shapes without manually invoking or assuming the meaning of the extra booleans.

Verification:

- Golden Era build passed with 0 errors and the existing 44 warnings after the correction.
- Required subagent review found no blockers. It noted that patching both helpers can duplicate postfix execution if one helper delegates to the other, but `QueueSpawnedBattleVisual` already dedupes by unit pointer and SID.
- Deploy build compiled successfully but MSBuild's integrated copy hit access denied on the plugin DLL. An approved DLL-only copy to the Golden Era plugin path succeeded.
- Deployed DLL hash matches release output: `D6C412B0C9A8CA29CD000DB17364692FEE1D6E529959FB6D2CDB7FA66F79F9D4`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.
- Deployed assembly string check contains the new resolver/logging symbols, including `ResolveNativeSpawnObjectMethods`, `bffg`, `fua`, and the current `expected bffg/fua` required-surface message.

Pending:

- Runtime proof should trigger a mid-combat custom summon/spawn and confirm the release battle visual log reports both `enk.bffg` and `enk.fua` patched, then verify the spawned custom unit receives its HoMM3 billboard rather than the donor visual.

## 2026-06-14 - Skeletal Necromancy SubstituteByHp Ability Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the user asked not to give up on the decompilation for abilities. Skeletal Necromancy is a custom ability path with old Golden Era symbol assumptions, manual spawn bridge logic, and prior notes that had drifted from current Golden Era.

Static evidence:

- Current readable Cpp2IL shows both `ehw` and `eij` expose `bdpe(eab,eac,InCastArgs,FieldObject,eaa)`, while the bridge still looked for older Golden Era names such as `bdnm` / `bdml` / `bdln`.
- Shared base `egf` owns the current mechanic state needed for exact gating: `cgcd` battle logic (`eep`), `cgce` `MechConfig`, and `cgcf` `EMechType`.
- Current `FieldObject`, not the mechanic instance, owns `cfnl`, `cfnm`, and `cfnn`; the prior stateful-mechanic interpretation was not supported by the current dump.
- Current battle factory access is on `eep.<cfvj>k__BackingField` / `eep.bdfw()` as `edh`.
- Current side-by-index helper is `enk.bffh(eep,int) -> eir`; the prior `elw.bekj(edg,int)` note was stale.
- Current spawn helpers remain `enk.bffg/fua(edh, Unit, eir, int, string, bool, bool, bool)`. Their extra boolean semantics are still not proven, so manual invocation remains blocked.
- The readable decompilation and generated interop assembly can disagree at the C# type boundary: direct `InCastArgs.castSource.basa()` failed to compile because the generated assembly exposes wrapper types, so the bridge must use centralized reflection helpers for those interface calls.

Correction:

- `GameSymbols.SkeletalNecromancy` now centralizes current `ehw/eij`, `bdpe`, `egf.cgcd/cgce/cgcf`, `eep.cfvj` / `bdfw`, `enk.bffh`, and `basa`.
- Current `enk` side-index helpers are separated from the legacy parallel spawn helper/factory/side arrays so typed legacy resolution is not silently misaligned.
- `Homm3SkeletalNecromancyProbe` resolves current five-argument `bdpe` calls through `castSource`, `caster`, and `InCastArgs`, and exact-gates by ability SID or current `EMechType.SubstituteByHp` + `MechConfig.mech=substitute_by_hp` + `h3_skeleton`.
- The probe no longer treats current `edg` as a hero ability wrapper; current Cpp2IL shows `edg` is a drawer/visual type in this build.
- Manual invocation of current 8-arg `enk.bffg/fua` still fails open and lets native behavior continue until the extra bools are proven.

Verification:

- Golden Era build passed with 0 errors and the existing 44 warnings.
- Required subagent review found two issues: current `enk` had been inserted into a legacy parallel helper array and `basa` was hard-coded outside `GameSymbols`. Both were fixed before deployment.
- Deploy build compiled but MSBuild's integrated copy hit access denied on the plugin DLL. An approved DLL-only copy to the Golden Era plugin path succeeded.
- Deployed DLL hash matches release output: `D9163F53556881A5EB043F3F24AB882D119BC7D704386B3B71E3EDF51384AB62`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Pending:

- Runtime proof should enable the gated `homm3SkeletalNecromancyProbe` path, trigger Skeletal Necromancy, and verify whether the corrected `ehw/eij.bdpe` bridge patches and whether native spawning can be observed safely without manually invoking the unproven 8-arg helper.

## 2026-06-14 - Selected-Unit Ability Click/Select Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the remaining user-visible ability failure is custom unit ability toggling on/off. Prior failures mixed together click registration, native click forwarding, and selected-ability state sync, so this pass focused only on the current Golden Era selected-unit controls surface.

Static evidence:

- Current thin Cpp2IL shows `BhUnitAbilityView.OnClicked()` gates on two booleans (`chah` blocked, `chaj` enabled) and then calls `controlsView.belo(this)`.
- Current `BhUnitControlsView` fields are `chao` selected view and `chap` current `dxy[]` ability array.
- Current controls methods are distinct: `belo(BhUnitAbilityView)` is the click entry, `belq(BhUnitAbilityView)` is a view/config helper, `belt(dxy)` is the wrapper selected-ability sync path, and `belw(dxy)` iterates active views and calls `BhUnitAbilityView.belc()` for matching wrappers.
- `BhUnitControlsView.beln(dxy[], dxy, bool)` ends by calling `belt(selected)`, making `belt` the safe native sync target after a recovered action-bar bind.
- The readable decompilation was useful here, but as a triage/call-flow source rather than a full high-level body: it proved that shape-only `void(dxy)` selection is unsafe because more than one same-shape method exists in current Golden Era.

Correction:

- `GameSymbols.SelectedUnitHud.ControlsSelect` no longer lists `belq` as a wrapper-select alias.
- `belq` remains centralized separately as `ControlsSyncAbilityView` so the current decompilation knowledge is not lost.
- `Homm3ImportBhSelectedUnitHudFix.FindReleaseControlsSelectMethod` now resolves by centralized exact names first, then accepts shape fallback only when exactly one non-special `void(dxy)` method exists.
- `InvokeReleaseControlsSelect` now uses that fail-closed resolver instead of `FindFirstMethodByNames(...) ?? first shape`, preventing future symbol drift from silently invoking `belw`.

Verification:

- Golden Era build passed with 0 errors and the existing 44 warnings.
- Required subagent review found one P3 centralization issue: removing `belq` from `ControlsSelect` made the current `belq(BhUnitAbilityView)` helper disappear from `GameSymbols`. This was fixed before deployment by adding `ControlsSyncAbilityView`.
- Approved DLL-only copy to the Golden Era plugin path succeeded.
- Deployed DLL hash matches release output: `768EE53B37ED4172241AE8B53E5C5BCC26E8EA0CA3D39EC1571F02D6E7A1B554`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Pending:

- Runtime proof should verify diagnostics-off startup logs include release ability click handling and that custom action-bar mouse clicks/select/repeat-click clear route through the patched `belo`/`belt` path without number-key fallback masking the result.

## 2026-06-14 - Hero-Bar Warcry / Custom Hero Ability Icon Surface

Status: deployed to Golden Era, runtime-proven after the June 25 cache follow-up.

Why this surface: the ability pass found conflicting repo notes for hero-action icons. Older guidance described wrapper-heavy `edg`/`els` and `skk/sjk/sjl/sjr` surfaces, while current production expected `edn`/`elz` and `skw/sjw/sjx/skd`. The current readable Cpp2IL showed a third shape again, so this was a good test of whether the decompilation can still produce easy wins.

Static evidence:

- Current `BhHeroAbilitiyView` stores the hero ability directly as `edn bydd`, context as `bzd byde`, and current carrier as `emb bydf`.
- Current button bind is `BhHeroAbilitiyView.sli(bzd, emb)`, not the older two-arg `elz` / `els` wrapper bind.
- Current `emb` can expose the `edn` through `beuf(out edn)` / `cwk(out edn)`, and `bzd` carries the active hero ability in `bwhs`.
- Current container binds are `BhHeroAbilitiesView.ski(bzd,List)`, `skj(bzd,List)`, `skk(bzd,ead,List)`, and context refresh `skp(edn)`.
- The old `skw/sjw/sjx/skd` and `skk/sjk/sjl/sjr` notes remain useful as compatibility history, but treating either set as the first-choice Golden Era contract can make the required release-safe icon slice register incompletely or extract the SID from the wrong carrier.

Correction:

- `GameSymbols.WarcryHeroAbility` now prefers the current `sli`, `ski`, `skj`, `skk`, and `skp` surfaces.
- Current direct ability/carrier members are centralized: `bydd`, `byde`, `bydf`, `bzd.bwhs`, `emb.chev`, `slf`, `get_cnhp`, `beuf`, and `cwk`.
- `Homm3WarcriesHeroAbilityHook` now patches the current three-argument arena/container bind in addition to two-argument container binds.
- Release button postfix extraction now checks the current view, `emb` carrier, and `bzd` context before applying the icon.
- SID extraction now includes the current compiler backing field `<sid>k__BackingField`.

Verification:

- Golden Era build passed with 0 errors and the existing 44 warnings.
- Required subagent review returned no blocking issues; its detailed output was malformed, so the current carrier/wrapper risk was locally rechecked against `BhHeroAbilitiyView.cs`, `BhHeroAbilitiesView.cs`, `edn.cs`, `bzd.cs`, and `emb.cs`.
- Approved DLL-only copy to the Golden Era plugin path succeeded.
- Deployed DLL hash matches release output: `D6E45E3D9ACDF4803C53F5C0E3BE19342D6F35D32C0475F3D10F5DDCF2E95F43`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Runtime proof update, June 25:

- The deployed fix was successful in both tested factions. The final proven path keeps the current native `sli` plus `ski`/`skj`/`skk`/`skp` surfaces, recovers custom ability identity from direct SID, release SID, or `HeroAbilityLevelConfig` `*_name`, and writes only the exact disabled/normal/hover icon children.
- The first failed deployed build showed why stale docs were misleading: generated Core rows and deployed icon payload were present, but `Homm3CustomHeroAbilityIconSpriteCache` loaded zero custom rows and treated that as success. The corrected cache reparses runtime row/level tokens, rejects malformed custom rows, and fails closed on zero loaded rows. Future fixes should not reintroduce hardcoded per-SID icon maps, `BhAbilityViewBase.pics`, broad child-image scans, or WIP-sprite fallbacks.

## 2026-06-14 - Swashbuckler Gold Passive / Resource Ability Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the static ability pass found that this passive custom-unit ability still depended on stale resource-wrapper symbols. It is not the selected-HUD click path, but it is an ability effect with a current Golden Era symbol drift that can make the required release-safe slice fail registration or target the wrong resource operation.

Static evidence:

- Current `dtj` side logic exposes `Side` as property `ccng`, hero list as property `ccns`, and the session manager as private field `ccnw`.
- Current `dsu` session manager exposes `Data` as property `cclb`.
- Current `Hex.Session.Logic.Hero` exposes the data hero payload as property `ccez`.
- Current `dti` resource wrapper no longer has `yla(string,int)`.
- ISIL proves `Resource.bggv(int)` is additive (`value += a`), while `Resource.bggu(int)`/`dti.ymi(string,int)` set the resource value and `Resource.bggw(int)` spends conditionally.
- Current add wrappers proven to call `Resource.bggv(int)` include `ymj`, `nbg`, `cpw`, `mjn`, and `exi`.

Correction:

- `GameSymbols.SwashbucklerGold` now prefers the current `ccng`/`ccns`/`ccnw`/`cclb`/`ccez` symbols.
- `GameSymbols.SwashbucklerGold.AddResource` now prefers the current `ymj` additive wrapper and keeps only other proven current additive wrappers as centralized compatibility hints.
- The setter `ymi` was deliberately not included, because invoking it would replace current gold instead of adding the passive grant.
- The stale `yla` hint was deliberately removed instead of kept as compatibility, because current `dti` has multiple `void(string,int)` resource operations and a future reintroduced `yla` with non-add semantics would be a silent-retarget hazard.

Verification:

- Golden Era build passed with 0 errors and the existing 44 warnings.
- Required subagent review found no blockers. Its one residual-risk note was that stale `yla` could become a future silent-retarget hazard, so `yla` was removed before final build/deploy.
- Approved DLL-only copy to the Golden Era plugin path succeeded.
- Deployed DLL hash matches release output: `87CDA9D25F2FE16AECAC59E992EACFC91477B75916EDA2E2675C2AE577217C83`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Pending:

- Runtime proof should start with diagnostics-off startup registration logs for `Homm3SwashbucklerGoldHook`, then verify a side with `h3_crew_mate_upg_alt` stacks receives `15 * stackCount` gold once per day-start without replacing the existing gold total.

## 2026-06-14 - Selected-HUD Ability Current Symbol Completion

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the selected-HUD click/select pass fixed the highest-risk `belo`/`belt` distinction, but a broader static pass found neighboring current names still missing from the central symbol table. Those misses can affect required startup validation, recovered action-bar click enablement, number-key handling, and battle ability icon rebinding.

Static evidence:

- Current `BhUnitControlsView` exposes bind/click/select surfaces as `beln(dxy[],dxy,bool)`, `belo(BhUnitAbilityView)`, `belq(BhUnitAbilityView)`, and `belt(dxy)`.
- Current `BhUnitControlsView` click-enable setter is `belz(bool)`.
- Current `BhUnitControlsView` hotkey handler is `beme(object,HotkeyAbilityArgs)`.
- Current `BhUnitAbilityView` bind is `beky(emb,bool)`, and current wrapper `emb` exposes `beue(out dxy)` / `oku(out dxy)`.
- Current `BhUnitAbilityView` fields remain `chae` wrapper and `chaf` ability; current controls state fields remain `chao` selected view and `chap` ability array.

Correction:

- `GameSymbols.SelectedUnitHud` now prefers current `belo`, `beln`, `belz`, `beme`, and `beky`.
- Current wrapper type `emb` was added to `AbilityViewWrapperTypeNames` so the battle ability icon binder can patch `BhUnitAbilityView.beky(emb,bool)` by name or by shape.
- Current wrapper ability getters `beue` and `oku` were added to `AbilityWrapperTryGetAbility`, and the incorrect `emb` alias was removed from `ControlsAbilityViewTypeNames` because `emb` is a wrapper, not a `BhUnitAbilityView`.
- Existing legacy/generic hints remain behind the proven current names for older compatibility, but the current Official path no longer has to fall through to stale names or generated method-name guesses.

Verification:

- Golden Era build passed with 0 errors and the existing 44 warnings.
- Required subagent review found two P3 symbol-hygiene issues: `emb` had been left in the view type list, and wrapper getter hints still missed current `beue`/`oku`. Both were fixed before deployment.
- Approved DLL-only copy to the Golden Era plugin path succeeded.
- Deployed DLL hash matches release output: `4DC41DD3D8A006EF5125FA24291DF594DEC796521C1E628399B6B4E936DEC09A`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Pending:

- Runtime proof should verify diagnostics-off startup registers the selected-HUD action-bar surface with current `beln`/`belz`/`beme` names and that mouse click plus number-key selection toggles custom action-bar abilities without donor/default icon fallback.

## 2026-06-14 - Recruitment/Detail Ability Row Bind Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the preview/recruitment/detail ability rows were already mostly aligned with current Cpp2IL, but the owning `BhHireUnitAbilities` binder still depended on a generated-name or shape fallback. That fallback can work when the current type has only one compatible `void(Unit)` method, but it weakens the release-safe required registration path and hides symbol drift.

Static evidence:

- Current `BhHireUnitAbilityItemView` ability-row binds remain `banl(bzd, AbilityViewConfig)` and `banm(bzd, AbilityViewConfig)`.
- Current `BhHireUnitAbilityView` ability-row binds remain `bann(bzd, AbilityViewConfig)` and `bano(AbilityViewConfig, bzd)`.
- Current `BhHireUnitAbilityView` and item rows expose the icon image as `pic`.
- Current `Hex.BhHireUnitAbilities` binds a live `Unit` through `hun(Unit)`, not stale `hue`.
- A generated interop/decompiled mirror under `tools/_tmp_release_hex_decompiled` names the same `void(Unit)` binder `hto(Unit)`, so `hto` is a compatibility hint rather than the primary readable-Cpp2IL name.

Correction:

- `GameSymbols.UnitPreviewAbilityIcons.HireUnitAbilitiesBind` now prefers current `hun`, then compatible `hto`, before the generated and stale compatibility names.
- This keeps recruitment and detail ability-row config swapping on the exact owner binder, without reviving child-image scans, sticky donor-to-custom fallbacks, or global preview mutation.

Verification:

- Golden Era build passed with 0 errors and the existing 44 warnings.
- Required subagent review found no blockers. It confirmed `hun(Unit)` in the readable Cpp2IL path, and after a second evidence check found generated mirror `hto(Unit)`, it confirmed `hto` is safe as a centralized shape-filtered compatibility hint after `hun`.
- Approved DLL-only copy to the Golden Era plugin path succeeded.
- Deployed DLL hash matches release output: `8A41C2DF52AF06569B71E2807D6DB120FF09E07DC07A6140611D002E6A43CB68`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Pending:

- Runtime proof should verify recruitment, detail, and upgrade preview ability rows bind custom unit configs/icons through current `BhHireUnitAbilities.hun(Unit)` or compatible `hto(Unit)` without donor ability rows or placeholder icons.

## 2026-06-14 - UnitAbilityNative Quarantine Recheck

Status: audited, no production change.

Why this surface: `GameSymbols.UnitAbilityNative` still contains old `lis`/`dng` names, and the broader static audit had left this cluster pending. Since the user-facing problem is ability toggling/exposure, this was worth checking before assuming every ability-related symbol list should be patched.

Static evidence:

- `Homm3UnitAbilityNativeHook.TryRegister()` is now a quarantine shim that only logs `stale pre-release wrapper path is quarantined`.
- `Plugin` skips `Homm3UnitAbilityNativeHook` entirely when `ReleaseSafeProfile` is active, logging that native unit ability wrappers need release retracing.
- Existing release notes already reject the stale `dwq`/`dwr`/`ekn` route after earlier `MissingMethodException: dwr.get_cdgt()` failures.
- Current selected-HUD recovery uses the newer `dxx`/`dxy` / controls-view path instead, and the active symbol corrections belong under `GameSymbols.SelectedUnitHud`, not this quarantined shim.

Conclusion:

- No production symbol change was made for `UnitAbilityNative`. Treat `lis`/`dng` as historical quarantine symbols, not an active easy win.
- Do not re-enable `Homm3UnitAbilityNativeHook` as an ability fix unless the release native availability semantics are retraced from current bodies and reviewed separately.

## 2026-06-14 - Hero Profile Portrait Bind Surface

Status: deployed to Golden Era, runtime verification pending.

Why this surface: the static Cpp2IL surface audit flagged `BhHeroPortraitView` as partial: current readable names had drifted, while the release-safe hook still depended on older/generated aliases plus shape fallback. This is a contained hero UI portrait surface, separate from adventure-map hero visuals.

Static evidence:

- Current readable Cpp2IL `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/UI/HeroProfile/BhHeroPortraitView.cs` exposes `zxx(Hero, bool, bool)` at line 25 and `zya(Hero)` at line 31 as the profile portrait bind surfaces.
- The generated interop/decompiled mirror `tools/_tmp_release_hex_decompiled/Hex.Session.UI.HeroProfile/BhHeroPortraitView.cs` names the same shapes `ztr(Hero, bool, bool)` at line 204 and `ztu(Hero)` at line 242, which were already present as compatibility aliases.
- `Homm3HeroPortraitHook.RegisterReleaseSafeUiSlice()` patches these surfaces by exact type plus `Hero,bool,bool` / `Hero` parameter shapes, so adding current names reduces reliance on broad shape fallback without broadening the hook.
- `BhHeroProfileWindow` also has current readable/generator name drift for parameterless lifecycle methods, but several zero-arg methods exist and the available static evidence does not prove which one is the correct presentation refresh. That follow-up needs a narrower body/call-site trace before changing `ProfileWindowShown`.

Correction:

- `GameSymbols.HeroProfile.PortraitViewBind` now prefers current readable `zxx` and `zya` before existing generated/current compatibility names.
- No profile-window parameterless alias was added in this pass.

Verification:

- Golden Era build passed with 0 errors and the existing 44 warnings.
- Required subagent review found no blockers. It confirmed the generated mirror side and asked for exact readable Cpp2IL evidence; the static evidence section now cites the readable file/line numbers directly.
- Approved DLL-only copy to the Golden Era plugin path succeeded.
- Deployed DLL hash matches release output: `25E7B2FCA68AE11FA39196817576AEA8DDE1F9AFF61901806D7C7897EDEAE93C`.
- Only one `OfflineUnlockMod.dll` exists under the Golden Era `BepInEx\plugins` tree.

Pending:

- Runtime proof should verify inventory/profile hero portrait replacement on a custom hero and confirm startup registration no longer depends on fallback-only portrait bind discovery.
