# HoMM3 Necropolis Bone Foundry Investigation

Status: **diagnostic only** (2026-10-02). No runtime or plugin code changed.

## Scope And Observation

The user confirmed the failed action was the bottom **Unique Building** menu button for Bone Foundry / Skeleton Transformer, not a click on town-world building art. The current building SID is `Build_Skeleton_Converter`.
The current name is Bone Foundry, owned by the overlay's per-faction name table. Final descriptions are derived by `tools/release_port/homm3_city_building_descriptions.py`.

The earlier log capture used in this investigation reported an empty sprite for icon key `homm3_necropolis_building_Build_Skeleton_Converter_level_1` (then LogOutput.log lines 9603-9606). That is a historical icon lookup observation, not an error opening the converter screen. The newer 2026-10-02 15:16 CDT Golden Era log has town layer/pick entries at those lines and no converter-session entries; do not reuse the old line numbers as current evidence.

## Installed Configured Behavior

Readback source: active Golden Era `HeroesOldenEra_Data/StreamingAssets/Core.zip`, entry `DB/objects_logic/cities/homm3_necropolis_city.json`. Do not use stale `artifacts/core_overlay_work/Core.zip` as installed-payload evidence.

The installed `unitsConverters` row has `sid=Build_Skeleton_Converter` and `sceneSlot=Skeleton_Converter`. It configures a same-tier output for each tier 1-7: Skeleton, Walking Dead, Wight, Vampire, Lich, Black Knight, Bone Dragon.
- `bannedUnits` contains the 21 configured Necropolis base/upgraded/alternate-upgraded unit SIDs; tier 8 has no configured pair.
- This proves the installed row shape only. It does not prove the native session opens, enforce bans, or commit a conversion.

The generator writes these pairs and bans in `tools/release_port/apply_release_core_overlay.py:8461-8484`, called for Necropolis at `:8513-8515`. Existing documentation cites Demo decomp as static evidence for the `fraction == "undead"` exclusion (`docs/homm3_city_building_descriptions.md:54`). That filter was not independently re-pinned to the current/live build in this investigation.

The current mechanics ledger marks `necropolis.skeleton_converter` `substituted` and records the bottom-menu failure plus unproven session opening/transaction (`custom_factions/source_mechanics/homm3_necropolis.json:60-77`).

Installed English tooltip readback is: "Allows sacrificing of other creatures to turn them into units of the same tier: Skeletons, Walking Dead, Wights, Vampires, Liches, Black Knights and Bone Dragons." The converter sentence is built from configured pairs (`tools/release_port/homm3_city_building_descriptions.py:425-435,563-565`); do not treat the older support-filler row in `apply_release_core_overlay.py:7120` as the final tooltip text.

## Difference From Classic HoMM3

Project faction design documentation describes the Skeleton Transformer as converting eligible creatures into Skeletons and Bone Dragons under HoMM3 rules (`docs/homm3_faction_plans/necropolis.md:89,95`). That document is design guidance, not the active contract or evidence that the current mechanic works.

Current installed data instead maps every input tier to the same-tier Necropolis creature. This is a material substitution from the documented classic target; do not change semantics until the design owner selects the intended behavior.

Even if opened, behavior is unproven for input eligibility, conversion ratios/counts, upgraded inputs, hero-stack/inventory commit, and tier-8 inputs without a configured pair. No army transaction was attempted without a disposable/authorized session.

## Overlay Dispatch Findings

`Plugin.PatchReleaseSafeCityTownUi` registers postfixes for `BhNavigationView` navigation and `BhNavigationTabView` click/visual selection (`Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Plugin.cs:1602-1620`). These callbacks observe selection and adjust panel visibility; they do not suppress native navigation (`Plugin.cs:2298-2402`).

The panel map includes `ECityNavigation.Universal` and maps it to the artifact-changer canvas (`Plugin.cs:3160-3180`). The source does not establish a missing Universal route, but the selected navigation state for the user's bottom Unique Building button was not captured.

`BhCitySpecialView` hooks are explicitly recruitment refreshes; `BhCityUnitSpecialSelection.Show` edits recruitment selection (`Homm3CustomUiIconHook.cs:146-148,2465-2479`). They do not establish the Bone Foundry opener.

Static decomp inspection identified typed `unitsConverters` configuration and a dedicated `BhUnitsConversionUISession`. It did not pin a caller from the Unique selector to that screen or establish a faction/SID guard. Treat this as static session-shape evidence only; the open route and failure remain unresolved.

## Separate World And Icon Gaps

The Necropolis layer map omits `Build_Skeleton_Converter` from `buildingLayerIds` and `nativeLevels` (`Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_runtime_assets/town_scene_refs/homm3_necropolis/layers/building_layer_map.json:3-26,33-101`). The generator builds only layers reachable through `nativeLevels` (`tools/homm3_town_scene_meshes/town_full3d_factions/necropolis.py:35-38`). This is a separate world-art/world-click gap, not the established cause of the bottom-menu failure.

The empty icon is also separate: custom icon lookup can decline unresolved keys (`Homm3StrongholdBuildingIconSpriteCache.cs:143-171`), and tooltip replacement returns on missing art instead of failing open (`Homm3CustomUiIconHook.cs:2952-3004`). The available log does not connect the blank icon to the failed session open.

## Proof Boundary And Next Evidence

- Executed validators: `python tools/release_port/validate_homm3_city_building_descriptions_contract.py` => `levels=475 errors=0`; `python tools/release_port/validate_homm3_city_building_tree_contract.py` => `errors=0`; documentation contract passed. These are data/doc checks, not runtime proof.
- Proof tier reached: source/static contracts plus installed Core row readback. No new build/deploy/startup proof was collected for this investigation.
- The failed user check is recorded in `docs/ingame_check_queue.md:60`. It confirms the bottom Unique Building button failure; conversion itself was not exercised.
- No Heroes/Olden process was running during review. Bridge status timestamp `2026-10-02 11:24:55` was stale; no live route trace was available.
- The earlier capture's icon lines do not identify the native selector state, session-open caller, or a converter transaction failure. The newer 15:16 CDT session supplies no converter dispatch evidence either.
- Established: installed row/config shape, current source UI hooks, missing world mapping, and unresolved icon probe. Unresolved: selected native navigation state, call edge to `BhUnitsConversionUISession`, failure cause, and transaction behavior.
- Resume with native read-only bridge inspection of selected navigation state and session lifecycle before volatile probes or any diagnostic build. A later conversion test needs an authorized disposable session. Keep current same-tier semantics pending design selection; the failed check and follow-up owner stay in the single in-game queue.
