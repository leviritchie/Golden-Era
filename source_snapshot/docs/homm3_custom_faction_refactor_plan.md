# HoMM3 Custom Faction Refactor Plan

Created May 13, 2026 after the first Fortress release pass exposed donor-collision, missing-data, and display-wiring problems.

## Problem Statement

The current custom-faction implementation grew from Stronghold into Tower and then Fortress by adding per-faction branches to release overlay generation and runtime hooks. That approach is now too brittle. We need to support at least nine custom factions, and the existing pattern creates three failure modes:

- Missing generated data is discovered only at map/session load time, such as Fortress hero specialization configs missing from `DB/heroes_specializations/`.
- Donor collisions are easy to mishandle. Fortress, Stronghold, Tower, and vanilla factions can share donor units, so global donor-to-custom reverse lookup can route the wrong faction into UI, battle, or map-object code.
- Visual and behavior fallback paths hide incomplete work. Donor city, law, specialization, unit, and map-object data can keep the game running while showing wrong assets or advertising wrong mechanics.

Do not add more custom factions by extending the current special-case model. First introduce a manifest-backed registry and validation layer, then migrate existing factions into it.

## Refactor Goals

1. A new faction is described by data, not by editing a dozen unrelated C# conditionals and Python string rewrites.
2. Custom-to-donor mapping is always explicit. Donor-to-custom mapping is contextual or rejected as ambiguous.
3. Runtime loaders fail loudly in validation for missing custom data/assets instead of silently falling through to donor identity.
4. Core data generation, runtime UI/image replacement, map-object/town visual replacement, and gameplay mechanics are separate surfaces with separate ownership.
5. Existing Stronghold and Tower behavior remains stable while Fortress is repaired.
6. Except for centrally registered custom skills/abilities referenced by faction data, custom factions share one executable contract. Divergent behavior between factions with the same declared contract is a validation or shared-path postcondition bug, not a reason to add another faction-specific hook branch.

## Proposed Manifest

Create one manifest per faction under a dedicated path such as `custom_factions/<factionSid>.json` or generate an equivalent compiled registry from source data. Each manifest should contain:

- `identity`: faction SID, city SID, display name token, description token, native terrain/biome, donor faction SID, donor city SID, and release selector metadata.
- `coreOverlay`: generated archive members, donor archive members, direct map-object ids, direct dwelling ids, squad tree paths, hero table paths, skill table paths, law paths, and localization files.
- `units`: custom SID, donor SID, unit line, tier, upgrade relation, UnitView donor prefab fields, import bundle key, portrait key, portrait animation key, map/battle visual keys, and behavior status.
- `heroes`: hero ids, class split, portrait keys, portrait fallback policy, specialization ids, starting army policy, start skills, and skill roll table ids.
- `skillsAndLaws`: faction skill ids, subskill ids, law ids, icon keys, localization keys, and validation rules for global id uniqueness.
- `cityVisuals`: town backdrop, layer folder, layer position map, animation metadata, building icon source map, build-tree icon key prefix, city map-object art, and dwelling map-object art.
- `ui`: faction icon, faction card/background, Quick Play detail mapping, GameHub row mapping, recruitment-strip index fallback SIDs, full hire-card repair rules, hero selector portrait rules.
- `aliases`: custom-to-donor unit mappings and allowed scoped donor aliases. Reverse aliases must include a required context such as active faction/city/session object. No manifest should permit global donor-to-custom mapping.
- `validation`: required Core members, required Lang tokens, required plugin payload files, forbidden donor tokens, allowed donor presentation fields, and known intentional debts.

## Runtime Shape

Introduce these generic components, leaving old names as adapters only during migration:

- `Homm3CustomFactionRegistry`: loads manifests or compiled manifest records once and exposes faction, unit, hero, city, and asset metadata.
- `Homm3CustomUnitSidMap`: replaces duplicated donor dictionaries. It supports `custom -> donor` directly and `donor + context -> custom` only when the context resolves one faction.
- `Homm3CustomAssetResolver`: resolves faction icons/cards, unit portraits, hero portraits, law icons, specialization icons, building icons, town layers, map city billboards, and dwelling billboards from the registry.
- `Homm3CustomTownVisuals`: replaces Stronghold/Tower-specific town-screen branching with registry-driven backdrop, layer, animation, and building-icon lookup.
- `Homm3CustomMapObjectVisuals`: replaces direct Stronghold/Tower/Fortress map-object branches with registry-driven city and dwelling billboard lookup. It must not mutate shared donor `ObjectConfig.id` values when direct custom rows exist.
- `Homm3CustomReleaseOverlayGenerator`: moves the release overlay script from per-faction handwritten normalization into manifest/template-driven generation.

The current `Homm3Stronghold*` helper names can remain temporarily as wrappers to reduce risk, but generic logic should not keep expanding inside Stronghold-named classes.

## Shared Contract Invariant

Faction-specific differences belong in manifests, generated Core rows, asset payloads, and registry records. Runtime hooks may ask the registry for faction data, but they should not branch on Stronghold/Tower/Fortress to make visual, UI, map, battle, or session behavior work.

The intended exception is custom skills/abilities: those can have centrally registered mechanics and custom data rows because they are faction content, not plumbing. Even there, ids, icons, text, and receiver lists should be declared in faction data or manifest-backed generation.

When one faction works and another fails on a shared surface, the fix should tighten the shared contract. For example, map-unit billboard parity is not just "there is a `homm3_import.json` entry"; it also requires the selected runtime entry to match the custom SID, the donor map prefab to be used only as a native shell, the custom `homm3_map_visual/quad` to exist and render, donor renderers to be hidden, the material to use a non-donor custom texture, and any required sidecar frame roots to be present.

## Validation Gates

Add a validation command that can run before applying Steam `Core.zip` and before building/deploying the plugin. It should fail on:

- A faction in `DB/data.json` without faction JSON, city JSON, direct city map object, squad tree, hero configs, hero specializations, faction skill row, and arena pick rows.
- Hero configs whose `specialization` ids lack matching specialization rows.
- Skill tables, hero start skills, or laws that leak donor faction skill ids outside an explicit allowlist.
- Duplicate global ids for subskills, laws, heroes, specializations, units, map objects, or squads.
- Any global donor-to-custom reverse alias.
- Missing plugin payloads referenced by manifest assets: unit bundles, `homm3_import.json` rows, portraits, portrait anim manifests, hero portraits, faction icon/card, town backdrop/layers/building icons, city billboard, and dwelling billboard frames.
- Missing shared-path postconditions for every expanded unit SID: map replacement enabled, donor shell resolved, custom quad/material produced, donor renderers hidden, and required extracted HoMM3 frame roots present when the shared runtime path depends on them.
- Custom build-tree icon keys with no resolver and no file.
- Known donor behavior tokens in unit logic or unit views outside allowed native-safe donor prefab fields.
- Lang rows written to wrong files, such as `fractionLaws.json` instead of `factionLaws.json`.
- Broad token remaps that create unresolved keys such as `Homm3Fortress_Build_*` or faction-specific siege-wall tokens without assets.
- New faction-specific runtime branches in visual/UI/map/battle hooks, except centrally registered custom skills/abilities and narrow legacy adapters that immediately call the registry-backed shared path.

Validation should treat donor scaffolding as allowed only where the manifest says it is intentional. It should not create runtime fallback behavior to compensate for missing rows.

## Migration Order

1. Inventory current special cases.
   - List every Stronghold/Tower/Fortress branch in C# hooks and release overlay scripts.
   - Classify each branch as identity, data generation, UI asset, town visual, map object, portrait, unit donor alias, or gameplay behavior.

2. Add manifests for existing factions with no behavior change.
   - Generate Stronghold, Tower, and Fortress manifests from current source/data.
   - Include known debts in `validation.allowedDebt` so the validator is strict but honest.

3. Introduce registry-backed adapters.
   - Keep existing hook call sites stable.
   - Replace duplicated dictionaries and faction lists with registry queries.
   - Preserve Stronghold/Tower/Fortress output byte-for-byte where possible.

4. Migrate donor aliasing.
   - Centralize custom-to-donor mapping.
   - Remove global donor-to-custom lookup paths.
   - Require faction/city/session context for donor aliases used by map-object and UI paths.

5. Migrate visual resolvers.
   - Move faction banners/cards, unit portraits, hero portraits, building icons, town layers, city billboards, and dwelling billboards to registry-driven lookup.
   - Rename new generic classes away from `Stronghold` once adapters are stable.

6. Migrate release overlay generation.
   - Replace per-faction Python normalization branches with manifest-driven clone, rewrite, and validation templates.
   - Keep Steam apply idempotent and backup behavior unchanged.

7. Add CI/local gates.
   - Run validation before `apply_release_core_overlay.py` mutates the release archive.
   - Run validation after archive apply against live `Core.zip`.
   - Run plugin payload validation before deployment.

8. Repair Fortress through the new path.
   - Do not keep patching Fortress special cases as a parallel implementation.
   - Use Fortress as the proof case for hero specialization rows, donor-collision handling, town/build-tree visual asset wiring, law/specialization icons, map billboards, and honest unit mechanics.

## First Implementation Slice

The safest first code slice is registry scaffolding with no runtime behavior change:

1. Add manifest data for Stronghold, Tower, and Fortress using the current mappings.
2. Add a validator that reads the manifests plus generated/release Core data.
3. Wire one low-risk path to the registry, preferably unit custom-to-donor mapping, because donor collision was the immediate Fortress risk.
4. Keep existing public helper methods as wrappers and add logs when a legacy branch is still used.

This avoids a broad rewrite while giving the project a hard place to put the next six factions.

Initial implementation note: faction manifests live in `custom_factions/`, and `Homm3CustomFactionRegistry` is the compiled runtime mirror used by the migrated donor lookup paths. `python tools/validate_custom_faction_manifests.py` checks the manifest unit mappings against that registry. Run it before migrating another runtime hook to the registry or changing donor mappings.

Donor collision execution note: `docs/homm3_donor_collision_execution_plan.md` is the focused working plan for this risk. The invariant is "donor collisions are legal; donor-only reverse lookup is illegal." The compiled registry must carry donor faction/root metadata for each unit line so mixed-donor factions such as Fortress can load donor prefab paths without Stronghold-only Dungeon tables.

The optional `--core <Core.zip>` check verifies load-bearing archive members. As of the first manifest slice, it warns for two known current debts rather than failing: Tower has no promoted `fractions_laws_table_homm3_tower.json`, and Fortress has no promoted `sub_classes_homm3_fortress.json`. Keep those warnings visible until the relevant data is normalized; do not replace them with runtime fallback behavior.

Second implementation note: `Homm3ImportBhSelectedUnitHudFix` no longer carries its own custom-to-donor dictionary. Selected-HUD dictionary seeding, release guard checks, and custom SID tests now route through `Homm3CustomFactionRegistry`, leaving the registry as the single runtime donor map.

Third implementation note: recruitment-strip base SID selection in `Homm3CustomUiIconHook` now comes from `Homm3CustomFactionRegistry` unit-line metadata. Do not add new per-faction recruitment SID arrays in the UI hook; add the faction to the manifest/registry and let validation catch missing or misordered base units.

Fourth implementation note: release Custom Game faction list injection, faction display text, lobby hero SID recognition, and faction banner/card sprite paths now use `Homm3CustomFactionRegistry`. The validator also checks manifest faction icon/card files and verifies key manifest identity/asset strings are present in the compiled registry. This caught Tower manifest drift: it referenced `Icon_Faction_Tower.png`, but the shipped payload and runtime cache use `H5-Wizard.png`.

Fifth implementation note: `Homm3CustomUiIconHook` now asks the registry for custom hero SID recognition, city SID resolution, and building-icon key prefixes. `Homm3StrongholdBuildingIconSpriteCache` accepts custom building icon keys by registry prefix. Missing Fortress building-icon assets still fail to resolve normally; do not add donor-icon fallback keys to hide that debt.

Sixth implementation note: `tools/release_port/apply_release_core_overlay.py` now gates release Core application with `tools/validate_custom_faction_manifests.py`. It validates source manifests/plugin payload before building the overlay, validates the candidate rewritten `Core.zip` before replacing the live archive, and validates the updated live archive after a real apply. A dry run still writes only a temporary candidate archive, but now proves whether that candidate would pass custom-faction Core validation.

Seventh implementation note: recruitment UI donor-to-custom inference now requires the current city faction context through `TryGetCustomSidForDonorInFaction`. Do not use the global donor reverse lookup for UI surfaces where Tower/Fortress/Stronghold can share donors such as `esquire`, `crossbowman`, `griffin`, `angel`, `minos`, or `hydra`.

Eighth implementation note: hero portrait/profile/army-strip eligibility now uses `Homm3CustomFactionRegistry.IsCustomHeroSid` instead of hard-coded Stronghold/Tower prefixes. Do not add per-faction prefix branches to `Homm3HeroPortraitHook`, `Homm3HeroClassProfileHook`, or `Homm3ImportArmyStripPortraitHook`; register the faction hero prefixes centrally.

Ninth implementation note: city HUD icon resolution now uses registry-backed city icon assets rather than the old Stronghold-only city sprite cache. Each manifest must declare `assets.cityIcon`, and the validator checks both file existence and compiled-registry coverage. Do not route Tower/Fortress city HUD icons through Stronghold map art as a fallback.

Tenth implementation note: direct external dwelling billboard art now resolves through `Homm3CustomFactionRegistry.TryGetDwellingBillboardAsset`. Fortress `barracks_homm3_fortress_1..7` are first-class direct dwelling SIDs, not missing Stronghold/Tower variants. The validator checks manifest dwelling folder/prefix coverage in the compiled registry; do not add another `SidToImage` table inside the billboard hook.

Eleventh implementation note: direct custom town map objects can now be painted by the registry-backed map-object hook through `TryGetCityMapBillboardAsset`, and seeing any registered custom city SID notifies the donor-alias queue through one city-seen path. This gives Fortress `homm3_fortress_city` a visible map billboard without cloning another `Homm3FortressTownMapBillboard` special-case class.

Twelfth implementation note: Fortress random-hire dwelling aliases are context-gated from raw Nature donor barracks (`barracks_nature_1..7`) to direct Fortress dwelling SIDs only after `homm3_fortress_city` has been seen on the map. Do not add a global Nature-to-Fortress donor reverse lookup; donor barracks are shared native data, and each future custom faction needs an explicit city/session context before raw donor map objects are repainted or config SIDs are rewritten.

Thirteenth implementation note: unit lines may declare a per-line `donorFactionSid` when one custom faction intentionally draws donor unit logic/views from multiple native factions. Fortress now records its Human/Nature/Dungeon donor split in `custom_factions/homm3_fortress.json`, and the release overlay reads that manifest data for Fortress unit generation. Do not add another Python-only donor-faction table for future factions.

Fourteenth implementation note: runtime donor dwelling aliases no longer need seven-row C# maps per donor/faction pair. `Homm3CustomFactionRegistry.TryGetDwellingSidForDonorPrefix` derives the custom dwelling SID from a donor barracks prefix plus target faction SID, then verifies that the target direct dwelling billboard is registered. Keep map-object context and city-seen priority in the billboard hook, but put dwelling identity/prefix data in the registry.

Fifteenth implementation note: donor dwelling prefixes now live in `runtime.dwellingDonorPrefixes` in each custom faction manifest and are mirrored by `Homm3CustomFactionRegistry`. `Homm3StrongholdDwellingMapBillboard` should ask `TryGetDwellingSidForDonorAlias` for target SIDs instead of hard-coding `barracks_human_`, `barracks_dungeon_`, or `barracks_nature_` branches. The hook still owns session context and city priority, because aliasing raw donor objects without map context is the collision bug.

Sixteenth implementation note: Fortress release map-object and hire-row generation now reads `identity.donorCitySid`, `coreOverlay.directCityMapObject`, `coreOverlay.directDwellingPrefix`, and `runtime.dwellingDonorPrefixes` from the manifest. Future factions should add those manifest fields and reuse the helper path instead of writing another `barracks_<donor>_<tier>` to `barracks_homm3_<faction>_<tier>` block in `apply_release_core_overlay.py`.

Seventeenth implementation note: Fortress release faction/city/law output paths now come from `coreOverlay.factionJson`, `coreOverlay.cityLogic`, and `coreOverlay.lawsTable`, and the city donor source comes from `identity.donorCitySid`. Keep generated content changes separate from source/path refactors; this slice intentionally preserves the current Nature scaffold output while removing path/source literals.

Eighteenth implementation note: Fortress release squad-tree generation now derives its source folder from `identity.donorFactionSid` and its target folder from `coreOverlay.squadTree`. The Fortress-specific Nature squad unit replacement table still exists because it encodes the current scaffold's creature substitutions, but source/target squad IDs should be computed from manifest identity rather than hard-coded `squad_nature` or `squad_homm3_fortress` literals.

Nineteenth implementation note: Fortress release unit logic/view generation now uses the manifest `identity.factionSid` for target folders, logic `fraction`, and normalized unit tags. The per-line donor faction still comes from `unitLines[].donorFactionSid`, so mixed Human/Nature/Dungeon donor rows remain explicit manifest data rather than Python-only routing.

Twentieth implementation note: Fortress release hero, specialization, and skill-table generation now derives donor hero paths, target hero paths, hero/icon prefixes, faction skill SID, skill-table SIDs, and specialization output path from the manifest. Keep the current hero start squads and placeholder specialization text separate from this identity/path refactor; those are Fortress content-quality debts, not pipeline routing.

Twenty-first implementation note: Fortress release law rows, faction skill row IDs, and language token IDs now derive from manifest identity plus `skillsAndLaws.factionSkillSid` and `skillsAndLaws.lawPrefix`. Placeholder text and current Swamp Tactics mechanics remain unchanged; only token construction moved out of hard-coded Fortress literals.

Twenty-second implementation note: release overlay custom-faction scan tokens now derive from each manifest's identity, unit lines, hero prefixes, skill/law IDs, plus optional `searchTokens` aliases for legacy names such as Stronghold upgraded display SIDs and hook class name fragments. Do not add new `*_ONLY_TOKENS` tuples for future factions; add stable aliases to the manifest and let the shared token builder feed copy/merge discovery.

Twenty-third implementation note: release overlay expanded unit SID lists now derive from manifest `unitLines` and `unitVariants` for Stronghold, Tower, and Fortress. Future factions should add manifest rows, not another hard-coded `*_GAME_UNIT_SIDS` block.

Twenty-fourth implementation note: Fortress unit display names and hero names now live in `custom_factions/homm3_fortress.json`, with validator checks for unit-line name arity and hero-name count. Keep faction content in the manifest or source faction docs instead of rebuilding Python-only name tables.

Twenty-fifth implementation note: Fortress squad-tree donor unit replacements now live under manifest `squadTree.unitReplacements`, with validator checks that replacement targets are declared manifest unit SIDs. This table is still scaffold-specific content debt, but it is no longer hidden as a Python-only Nature replacement map.

Twenty-sixth implementation note: Fortress release-only Nature scaffold fields now live under manifest `releaseScaffold`: release biome, city scene, faction icon, law panel icon, and law row icon. Live release currently has no `Swamp` biome enum, so generated Fortress Core rows still use the explicit `Autumn` scaffold biome while `identity.nativeBiome` remains the HoMM3 target terrain. Do not scatter `Autumn` or Nature icon literals back into the overlay script.

Twenty-seventh implementation note: adventure-map unit billboards are part of the custom-faction registry contract, not a Stronghold-only visual path. Runtime map stack visuals flow through `UnitViewConfig` map prefab loading, `homm3_import.json` `gameUnitSids`, `swapAdventureMap`, bundle/prefab paths, and native donor shell paths. The observed mixed behavior was Stronghold goblins rendering correctly, Tower gargoyles invisible, and Fortress gnolls falling back to Human pikemen; that means future refactor work must validate and diagnose the shared import/billboard path for every manifest unit SID. The manifest validator now checks that every expanded custom unit SID has a complete `homm3_import.json` map/battle entry. Do not hide missing map replacements behind donor fallback visuals; missing or failed custom map visuals should be explicit.

Twenty-eighth implementation note: the shared-contract standard is stricter than declaration parity. It is not enough for every faction to have the same manifest fields or `homm3_import.json` keys; the shared runtime path must reach the same observable postconditions for each expanded unit SID. For map-unit billboards that means the selected entry matches the custom SID, the native donor shell is only a shell, the custom `homm3_map_visual/quad` exists and is enabled, donor renderers are disabled, the material has a usable custom texture, and any required `homm3_lab/<labSid>/extracted_battle` sidecar frames are present. If Stronghold works while Tower or Fortress fails, tighten shared validation/diagnostics or fix the missing payload; do not branch on Tower/Fortress in the hook.

Twenty-ninth implementation note: `tools/validate_custom_faction_manifests.py --plugin-root <OfflineUnlockMod plugin dir>` validates deployed runtime payload parity for every manifest unit SID. It now checks bundles, static portraits, portrait animation manifests, and `homm3_lab/<labSid>/extracted_battle` PNG/idle frames. This intentionally caught the Fortress map-sprite divergence as missing deployed lab sidecars while leaving the shared runtime hook unchanged. Use the gate before asking for another manual Steam map test.

Thirtieth implementation note: payload existence is only the first layer. The validator must also enforce source identity for variants: if a faction doc/manifest names a distinct `_upg_alt` creature, that alternate cannot reuse the normal `_upg` bundle, `homm3_lab` source, or deployed portrait-animation `sourceManifest`. Fortress failed this across all seven Tears of Ashan alternates, which explains missing ToA sprites even though every required file path existed. Future custom factions need this semantic asset check before release promotion.

Thirty-first implementation note: release map-unit billboard swapping must bind to the explicit centralized `UnitViewConfig` map loader symbol. The May 14 live generated interop loader is `sdn()` even though the native dump can still show `scy()`; older names include `scy`, `scd`, `rtd`, and `sce`. Do not fall back to "the only parameterless GameObject method" because that makes a hotfix rename look like valid behavior and lets factions diverge by accident. If the symbol hints stop resolving, update `GameSymbols.UnitViewConfig.MapMeshLoader` from the live generated `BepInEx/interop/Hex.dll` decompilation first, not from a stale native dump alone.

Thirty-second implementation note: HoMM3 animation-group identity is part of the shared asset contract. Group 5 is death and must not be placed in UI "action" animation loops; ranged attacks use shooting groups 14, 15, and 16, not only melee attack groups 11, 12, and 13. The battle disk texture remapper now prefers shooting groups when they exist and only falls back to melee groups when no shooter family is present, so shooter lines such as Elves/Lizardmen do not resolve ranged attacks into melee or death frames. Portrait animation extractors should use the same non-death action group policy.

Thirty-third implementation note: Stronghold Wolf Rider/Raider source names are easy to invert. `CBWLFR.dir` is the base Wolf Rider and `CUWLFR.dir` is the upgraded Wolf Raider; both authoring presets and portrait extraction must keep that order. If the live build still shows them swapped after this source correction, rebuild and redeploy the affected `custom_units_h3_wolf_rider` / `custom_units_h3_wolf_raider` bundles because the old bundle payload may still contain the inverted frames.

Thirty-fourth implementation note: map-unit billboard visibility is a shared-path postcondition, not a faction-specific asset quirk. The May 14 logs showed Tower, Fortress, and Stronghold all reaching the shared `UnitViewConfig` swap path and building animated HoMM3 billboards, but the custom quad renderer stayed on Unity layer 0. Native donor map prefab roots can be layer 0 while the renderable donor child carries the map-visible layer, so the shared path must copy `gameObject.layer` from the selected donor `Renderer` to the custom billboard root/quad along with renderer flags.

Thirty-fifth implementation note: the map-unit shared path has two runtime surfaces. `UnitViewConfig` map loading swaps the prefab, but the adventure-map squad visual controller owns later fog/visibility state. Current release uses `ezg` with root `ciwk`, view config `ciwo`, and init-like `(fcy, ctp)` methods; older `eya.chym/chyq` hooks are stale. The release full-feature slice must register the squad-controller hook so `Homm3MapSquadVisualMirror` can keep the custom `homm3_map_visual` renderers in sync after native shell renderers are hidden.
