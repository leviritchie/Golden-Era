# Factory `cityFactory` Runtime Pilot â€” Breakage Catalog

Proof labels follow `AGENTS.md`. This catalog is for Phase 4 (Castle-parity ownership pilot), not Phase 5 Factory art.

Date: 2026-07-22. Install: Golden Era OfficialDeobf. Registrar: `Homm3FactoryCitySceneRegistrar`. Flag: `homm3FactoryCitySceneReplace: true`.

## Ownership inputs (deployed / installed proven)

| Check | Evidence | Label |
| --- | --- | --- |
| Manifest `releaseScaffold.citySceneName` | `custom_factions/homm3_factory.json` = `cityFactory` | source/static |
| Installed Core city row | `Core.zip` â†’ `DB/objects_logic/cities/homm3_factory_city.json` `sceneName` = `cityFactory` | installed payload |
| EScene ordinal 26 name | `validate_escene_city_factory_pin.py` OK (`cityFactory`) | installed payload |
| Registrar + Route A gate + presentation activate | Deployed `OfflineUnlockMod.dll` contains `EnsureOwnedCityPresentationActive` / `activated presentation root` | deployed |

## Phase 4 pass checklist

| Criterion | Result | Label |
| --- | --- | --- |
| Active town world = `cityFactory` | Log: `activeScene='cityFactory' factoryLoaded=True liveRoots=13` | runtime behavior |
| Not silent `cityHuman2` as Factory world | Active scene name `cityFactory` after own; donor unloaded after move | runtime behavior |
| Load lifecycle (no Instantiate) | Log: `moved 13 LoadScene'd root(s) from cityHuman2 into cityFactory (no Instantiate)` | runtime behavior |
| Di2 + native Void | Log: bind + `allowing native Void` + `native Void(EScene) returned` (twice) | runtime behavior |
| Manager / slots / buildings present after move | Fail-closed `ValidateOwnedContractOrThrow` (BhBuildingsManager, 20 slots, â‰¥34 BhBuilding) before unload | runtime behavior (gate) |
| City camera present | Live probe: `CityCamera` / `MainCamera` in `cityFactory`; FOV 47.6; clearFlags Skybox | runtime behavior |
| CityUI interactive | Log: Factory building icons, recruit portraits, town music while on `cityFactory` | runtime behavior |
| Route A posters off | Log: `skipping Route A poster/suppress`; no `suppressed N donor city renderer(s)` | runtime behavior |
| Visible Castle world | User-confirmed non-black Castle town after `CityCamera`+`Lights` SetActive | user-visible gameplay (Castle art) |
| Auto presentation activate after Void | Runtime-negative; correction source only | The deployed build activated roots too early, then permanently failed on transient zero-active buildings. Source now enters a black camera domain immediately and defers composition to native lifecycle readiness. Restart proof is pending. |

## Breakage / remaining gaps

| Area | Status | Notes |
| --- | --- | --- |
| Synthetic container | Known gap | No authored `cityFactory.unity` in build settings; content is LoadSceneâ€™d Castle roots moved into `CreateScene_Injected("cityFactory")`. |
| Presentation roots after Void | Source/static corrected; not deployed | The manager root activates before native Void. `EnsureOwnedCityPresentationActive` owns the black camera domain, treats zero-active/unbound variants as transient readiness, and composes only after readiness passes. Structural exceptions enter a distinct fatal presentation state and suspend partial state. |
| Partial first-join art lock | **Live-negative (Rampart log)**; source corrected | Town-layer sync called Ensure every frame, but Ensure blind-returned once `IsApplied` after an 8-frame settle. Native activated Tier_1 first → `applied 1 … building layer(s)` → `HideDonorPresentation` → Main/Tavern/Market later never recomposed. Fix: wait for Main bound before compose; always re-enter Apply (signature-gated; textures after match); invalidate signature on native building mutation. Restart deploy proof pending. |
| Unsuffixed single-variant + sticky-fail loop | **Live-negative (black screen error loop)**; source corrected | Completing the join set activated `H_build_Tavern` (no `_Level_N`). Level parse threw → `FailOwnedCityPresentation` → `Suspend` cleared `_presentationFailed` → town sync retried Ensure forever. Fix: accept unsuffixed names only when `nativeLevels` is exactly `{1}`; re-arm sticky fail after Suspend. Deploy proof pending. |
| Walls without BoxCollider fatal | **Live-negative (Castle black screen)**; source corrected | Full join included `walls_level_1` with no native BoxCollider. Compose threw before HideDonor/art → Suspend. Same cityHuman2 donor trait hits every owned faction once Fort/Walls is active. Fix: paint art; align/disable BoxColliders only when present; never invent parallel click owners. Deploy proof pending. |
| Shared donor vs per-faction art | source/static | Unsuffixed Tavern/Market names and Walls-without-BoxCollider are **cityHuman2 donor** issues (all 12 `OwnedCityWorldFactionSids`). Per-faction gaps that remain are art maps only (e.g. Fortress/Stronghold Magic Guild clipped at L3; runtime clips downward). Validator pins all-faction sprite resolution and forbids Castle-only branches in those compose fixes. |
| Native `BhBuilding` lifecycle/clicks | **User-visible proven** (Factory) | PhysicsRaycaster → native `BhBuilding`; no town-layer click relay as product. |
| Town-hall construction menu | **User-visible proven** (Factory, 2026-07-23) | Open via HUD `BuildingsConstruction` (`TryOpenOwnedCityHallConstructionMenu`). Live-positive close was `ScUpgradeUnits.OnEscapeClick` on hierarchy-active but visually closed `UPGRADE UNIT PANEL`; gate with `IsReleaseTownPanelVisuallyOpen`. See `docs/custom_town_scene_paradigm.md`. |
| Construct / upgrade refresh | Exact native source path; runtime unproven | A postfix on the centralized Golden Era `BhBuildingsManager.bajs(dwc,bool)` pin schedules one deduplicated LateUpdate reconciliation after native `dxg.bajn` mutates a slot. Initial activation uses the same signal; no `IsApplied` gate or synchronous fallback remains. |
| Castle town after Factory | Unproven | Donor is unloaded so Castle can LoadScene `cityHuman2` fresh; second-open / Castle-after-Factory not smoke-proven. |
| Second Factory open same session | Source/static fixed; runtime unvalidated | Suspend now deactivates the manager root to unsubscribe; the next prefix reactivates it before native Void even when owned roots already exist. |
| Town music | Working in log | Sidecar Factory music started during ownership open. |
| Session fade | Likely OK | `sessionFade` inactive in probe; release attempted on ownership sync. |
| Factory HotA visuals (Phase 5) | **User-visible proven** for Factory world art path; Conflux completeness may still gap | Prefer owned-world compositor; do not score Route A posters as pass. Paradigm: `docs/custom_town_scene_paradigm.md`. |
| Hive / alias | Absent | Validators forbid playtest `city_hive` helpers and `cityDemon` alias. |

## 2026-07-23 Factory presentation failure and correction

The first Phase 5 playtest is runtime-negative and user-visible gameplay-negative. The running Golden Era process showed a rainbow/corrupt world background with vanilla Castle buildings still visible. The log and live object census established two independent faults:

- The installed `building_layer_map.json` contained a valid `nativeLevels` object, but a direct `JToken as JObject` cast returned null through the IL2CPP Newtonsoft proxy. Presentation rollback then restored every vanilla renderer. The source now validates token types and reparses object/array tokens from `ToString()` before reading them.
- No `OfflineUnlockFactoryWorldArt` or Factory backdrop object existed while the corrupt background was visible. The synthetic `cityFactory` container had no authored scene render settings, while the moved camera was forced to Skybox. The source now owns a deterministic SolidColor black camera, a full-frame black plate, one required `Unlit/Transparent` shader, and suppresses every non-owned donor Renderer plus Terrain while preserving native `BhBuilding` objects and colliders.
- Native building variants were still transiently inactive at the exact `Void(EScene)` postfix, then became active and bound later. That readiness wait no longer sets the permanent world-ownership failure flag. The exact native building mutation postfix now schedules one required LateUpdate reconciliation without an `IsApplied` gate or synchronous fallback.

Proof boundary (historical for the 2026-07-23 morning correction): that source pass was not yet the later user-visible Factory art/click/hall proof. Prefer `docs/custom_town_scene_paradigm.md` and the breakage rows above for current status. The prior rainbow/Castle bleed result must not be described as a successful Factory presentation.
## Smoke to prove the correction

After the running Golden Era process is closed, deploy the corrected DLL and restart. Open Factory town, then require:

1. One `manifest inputs:` line resolving the installed Factory map and positions files.
2. Optional `Factory presentation waiting for native lifecycle:` followed by no fatal presentation error.
3. `applied N native-owned Factory building layer(s)` after the native mutation/LateUpdate reconciliation.
4. No `nativeLevels` parse error, no `world own failed`, and no `Factory presentation was suspended` line.
5. Factory background and Factory building layers visible with no Castle renderers or rainbow render domain.
6. A world-building click still dispatches through the native `BhBuilding` owner.

These are runtime and user-visible proof requirements; compile and validator success do not satisfy them.

## Assumptions and short proof

**Assumption:** Preferred custom-town product path is Factory-owned `cityFactory` with Castle-parity manager/slot/building/camera contract, HotA world art on native `BhBuilding`s, and native CityUI (hall via HUD construction nav) — not Route A posters.

**Proof:** Installed Core + ownership logs + live hall-close trace + user-confirmed hall/menu and world art establish the paradigm. Remaining Conflux/construct-refresh edges stay unproven until a focused smoke says otherwise; see `docs/custom_town_scene_paradigm.md`.

## Factory layer / native-slot boundary (2026-07-22)

The six currently constructed native slots are all exactly art-mapped: Main, Tavern, Market, Tier 1, Tier 2, and Bank. The compositor validates the full join before hiding any vanilla renderer and uses the highest active level when native variants are cumulative.

| Building | Boundary |
| --- | --- |
| `Build_Factory_Gantry` | Factory art exists, but Castle's native manager graph has no `Factory_Gantry` slot. Requires an authored native `BhBuilding` slot; aliasing another slot would corrupt click ownership. |
| `Build_Mother_Nature` | Factory art exists, but the native graph has no `Mother_Nature` slot. It can coexist with Bank, so Bank is not a valid alias. |
| `Build_Intelligence_Academy` | Native Castle slot exists, but HotA Factory has no accepted source layer in `nativeLevels`. Overlay strips this SID from constructible city rows for owned-world peers until scene v2 maps art. Do not alias. |
| `Build_Training_Range` | Same unbound-slot policy as Intelligence Academy. Non-constructible without `nativeLevels`. |
| `Build_Golden_Calf` | Native slot and HotA grail art both exist. Generator and layer map now bind level 1 to `tbfaholy`; source/static only. |
| `Build_Main` | Castle exposes three native variants and installed Factory data identifies them as Village Hall, Town Hall, and City Hall. The explicit runtime map is `tbfahall/tbfahal2/tbfahal3`; Capitol remains source-only because the donor graph has no fourth native owner. |
| Build_Magic_Guild | Castle exposes four native variants while HotA has five source layers. Native levels 1-4 map exactly to Factory levels 1-4; Factory level 5 remains source-only because the donor graph cannot own or click a fifth variant. |

Construction/upgrade recomposition is source-wired to an exact, centralized Golden Era manager mutation pin whose static body calls `dxg.bajn` before returning. The postfix and complete collider rollback contracts are validator-pinned. A live build/upgrade is still required for runtime proof.
