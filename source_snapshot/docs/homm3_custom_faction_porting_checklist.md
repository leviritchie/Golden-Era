# HoMM3 Custom Faction Porting Checklist

Created May 14, 2026 from the Stronghold, Tower, and Fortress release-port work. Use this as the sequential checklist for future agents before promoting another custom faction to the Steam release build.

This document is intentionally long. The failure mode we hit repeatedly was not "one missing file"; it was a chain of partially completed surfaces where donor data kept the game limping along until map/session load, town UI, or combat tried to resolve the missing custom piece.

## 0. Working Rules

- [ ] Start from the current faction plan in `docs/homm3_faction_plans/<faction>.md`, not from an old generated clone.
- [ ] Read `docs/homm3_future_faction_porting_source_of_truth.md`, `docs/homm3_custom_faction_refactor_plan.md`, and `docs/homm3_donor_collision_execution_plan.md` before touching code.
- [ ] For faction law scaffolding, read `docs/mechanics_audit/olden_era_vanilla_faction_law_uniqueness.md` before cloning donor laws; vanilla unit laws, faction-skill resource laws, and faction-named mechanics must be redesigned or explicitly marked as debt.
- [ ] Treat `docs/stronghold_release_faction_checklist.md` and the current Stronghold implementation as the working reference when a release surface is unclear.
- [ ] Commit narrow, safe slices when possible. Do not accidentally commit unrelated generated asset churn.
- [ ] Update agent-facing docs as soon as a reusable failure or invariant is discovered.
- [ ] Prefer static tracing, generated data inspection, Core archive inspection, and decompiled IL2CPP paths over runtime probing.
- [ ] For custom town presentation, follow `docs/custom_town_scene_paradigm.md` (owned Unity city world + native `BhBuilding` + HotA world art). Do not treat Route A UI posters as the product destination.
- [ ] Do not add runtime fallbacks that hide missing custom data. A missing custom row or payload should fail validation or leave the native surface alone.
- [ ] Centralize hotfix-sensitive obfuscated names in `GameSymbols.cs` and access them through `GameMember` helpers.
- [ ] Do not hand-edit Steam `Core.zip`. Use `tools/release_port/apply_release_core_overlay.py` or a faction-specific generator called by it.
- [ ] If the Steam release build was patched recently, run the hotfix recovery pipeline before assuming old hook names still work.

## 1. Source Inputs

- [ ] Confirm the faction plan exists and is current.
- [ ] Confirm HotA or Tears of Ashan source requirements before assuming HoMM3 Complete has the needed assets.
- [ ] For ToA alternate upgrades, run `python tools\extract_tears_of_ashan_creature_specs.py` and use `docs/homm3_tears_of_ashan_creature_specs.md` as the stats/mechanics source.
- [ ] Inspect local `vcmi/` before searching elsewhere. VCMI and Tears of Ashan assets are in the repo root for many faction needs.
- [ ] Record the exact source file/member for each major visual asset:
  - [ ] Town backdrop.
  - [ ] Town building layers and placement config.
  - [ ] Build-tree icon DEF/sprite source.
  - [ ] Adventure-map city object.
  - [ ] External dwelling objects.
  - [ ] Unit battle/map sprites.
  - [ ] Hero portraits.
  - [ ] Faction icon/card/banner.
- [ ] Verify whether a visual source is a town scene or a UI/build-tree plate. Tower and Fortress both exposed this: `tbtwback.pcx` / `tbfrback.pcx` are town scenes, while hall/backing plates are not.

## 2. Worktree And Release Target

- [ ] Work in the correct worktree. For risky refactors, create a new worktree instead of destabilizing the release branch.
- [ ] Verify `git status --short` before editing. Expect existing dirty/generated asset changes and avoid reverting user work.
- [ ] Identify the target Steam install and `Core.zip` path:
  - `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip`
- [ ] Identify the deployed plugin root:
  - `V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod`
- [ ] Keep release `Core.zip` data, plugin DLL, and plugin payload assets as separate deployment surfaces.
- [ ] After applying to Steam, record the generated backup path.

## 3. Manifest And Registry Gate

- [ ] Add or update `custom_factions/<factionSid>.json`.
- [ ] Put identity data in the manifest:
  - [ ] `factionSid`
  - [ ] `citySid`
  - [ ] display-name token
  - [ ] description token
  - [ ] native terrain / target biome
  - [ ] release-safe scaffold biome if different
  - [ ] donor faction SID
  - [ ] donor city SID
- [ ] Put Core output paths in the manifest:
  - [ ] faction JSON
  - [ ] city logic JSON
  - [ ] laws table
  - [ ] squad tree
  - [ ] hero configs
  - [ ] hero specializations
  - [ ] skill tables
  - [ ] direct city map object id
  - [ ] direct dwelling prefix
- [ ] Put unit-line data in the manifest:
  - [ ] custom SID
  - [ ] base/upgraded/alternate-upgrade SIDs
  - [ ] exact per-variant SIDs in `unitLines[].variantSids` when the source uses named upgrades instead of `baseSid + _upg`; Rampart requires this for Centaur Captain, Battle Dwarf, Grand Elf, Silver Pegasus, Dendroid Soldier, War Unicorn, Gold Dragon, and the ToA alternates.
  - [ ] donor SID
  - [ ] donor faction SID when mixed donors are used
  - [ ] tier
  - [ ] import lab SID
  - [ ] bundle key
  - [ ] portrait key
  - [ ] map/battle visual keys
- [ ] Put hero data in the manifest:
  - [ ] hero ID prefix
  - [ ] hero count
  - [ ] portrait keys and fallback policy
  - [ ] class split
  - [ ] specialization IDs
  - [ ] start skill policy
  - [ ] start army policy
- [ ] Put assets in the manifest:
  - [ ] faction icon
  - [ ] faction card/banner
  - [ ] city icon
  - [ ] town backdrop
  - [ ] town layers folder
  - [ ] town placement map
  - [ ] build-tree icon source map
  - [ ] city map-object art
  - [ ] dwelling billboard folder/prefix
- [ ] Put scoped donor aliases in the manifest, not in hook-local tables.
- [ ] Run `python tools\validate_custom_faction_manifests.py` before moving to Steam.
- [ ] Run `python tools\validate_custom_faction_manifests.py --core <Core.zip>` on any candidate or live archive.
- [ ] Run `python tools\validate_custom_faction_manifests.py --plugin-root <OfflineUnlockMod plugin dir>` before asking for manual visual testing.

## 4. Donor Collision Rules

- [ ] Treat donor collisions as legal.
- [ ] Treat donor-only reverse lookup as illegal.
- [ ] `custom SID -> donor SID` can be global.
- [ ] `donor SID -> custom SID` must require context:
  - [ ] current faction SID
  - [ ] current city SID
  - [ ] saved original custom SID
  - [ ] map object SID/prefix
  - [ ] exact live hire payload or saved original custom SID
- [ ] Ambiguous donor-only reverse lookup must fail closed.
- [ ] Do not resolve donor dwellings from "a custom city was seen" or "one custom faction exists" alone. Donor barracks such as `barracks_human_*`, `barracks_dungeon_*`, and `barracks_nature_*` must map to a custom dwelling only when the exact hire payload identifies one custom dwelling SID.
- [ ] Mixed-donor factions must declare per-line donor faction/root metadata. Fortress uses Human, Nature, and Dungeon donors in one faction.
- [ ] Do not add Stronghold-only Dungeon donor tables for future factions.
- [ ] Do not mutate shared donor `ObjectConfig.id` globally when direct custom map-object rows also exist.
- [ ] If map loading throws duplicate-key errors, check for direct custom IDs plus mutated donor IDs in the same map-object config array.
- [ ] If one faction works and another fails on the same shared visual surface, fix the shared contract or payload validation. Do not add another faction-specific branch.

## 5. Core Overlay Identity

- [ ] Add the faction to `DB/data.json` fractions and available-fractions arrays.
- [ ] Add the faction to arena pick content if the release UI uses arena/draft pools.
- [ ] Generate `DB/fractions/<faction>.json`.
- [ ] Set native terrain/biome explicitly.
- [ ] Use the shared custom-biome pack for faction-owned terrain ids. Do not write a new biome string such as `Wasteland` outside `tools/release_port/apply_custom_biome_pack.py` / `homm3_runtime_assets/custom_biomes/custom_biomes.json`, and do not rely on fallback behavior.
- [ ] Verify custom-biome Core coverage includes map tiles, waters, `waterForBiome`, generator environment assets, `DB/biomes_info.json`, arena views/info, arena obstruction model rows, and biome-keyed map/ambient sound rows.
- [ ] Keep native-safe donor presentation fields only where the manifest explicitly allows them.
- [ ] If using the generic manifest generator in `tools/release_port/apply_release_core_overlay.py`, verify `coreOverlayEnabled` is intentional. The generator writes release scaffolds for identity/city/laws/units/squads/heroes/map objects/Lang, but it is not a production-ready signal by itself.
- [ ] Avoid broad token remaps such as `Nature -> Homm3Fortress`; they can create missing build-tree, siege-wall, or UI keys that poison map/session load.
- [ ] Merge Lang rows through the overlay script rather than manually patching loose mirrors only.
- [ ] Verify Lang files use the correct member names. Fortress exposed that `factionLaws.json` is read while `fractionLaws.json` is ignored.

## 6. City And Map Startup Data

- [ ] Generate `DB/cities/cities_logic/<faction_city>.json`.
- [ ] Add a direct city map object row to `DB/map/objects/4_interactables.json`.
- [ ] Use a native donor prefab path for the direct city map object unless a real custom prefab path is proven.
- [ ] Generate direct external dwelling map object rows, not only hire-logic rows.
- [ ] Add direct dwellings to `DB/objects_logic/hires/barracks.json`.
- [ ] Generate custom external dwelling name and description localization rows at the same time as the rows/art. A direct custom dwelling with donor text is incomplete.
- [ ] External dwelling descriptions must describe the actual custom creature produced by that dwelling from `custom_factions/<faction>.json` `unitLines[]`; do not reuse donor/native map-object descriptions or city-building description text for the map-object tooltip.
- [ ] Verify direct dwelling object IDs, hire logic IDs, billboard art IDs, and localization tokens all use the same custom tier mapping.
- [ ] Rewrite real recruitment payload fields in donor city/dwelling rows:
  - [ ] `unitsHire.units[].sids`
  - [ ] `unitsData.units[].sids`
  - [ ] `cityUnitsIncrementFromBarrack` parameters
  - [ ] guard unit SIDs
- [ ] Do not rely on a top-level `units` field if the working Stronghold/Tower hire rows do not use it.
- [ ] Generate `DB/squads/squads_<faction>/**`.
- [ ] Rewrite squad IDs, file paths, and unit SIDs from donor to custom.
- [ ] Validate the squad tree exists in the target archive before runtime testing. A selectable faction can still fail during map/session startup if squads are missing.

## 7. Unit Logic And Views

- [ ] Generate logic rows for every base, upgrade, and alternate-upgrade unit.
- [ ] Preserve the native ancestry chain:
  - [ ] base has `upgradeSid`
  - [ ] standard upgrade has `baseSid=<base>` and, if supported, `upgradeSid=<base>_upg_alt`
  - [ ] alternate upgrade has `baseSid=<standard upgrade>` and no `upgradeSid`
- [ ] Keep release UnitView `mesh` and `mapMesh` pointed at native-safe donor prefab paths.
- [ ] Put HoMM3 visual identity in `homm3_import.json` and asset bundles, not directly in release UnitView prefab fields.
- [ ] Strip misleading donor ability/passive mechanics and view strings before adding custom mechanics.
- [ ] For bulk-generated factions, keep the generated `xHomm3ProductionDebt` / `xHomm3MechanicsDebt` markers until real faction mechanics, UI presentation, town/reference payloads, and hero portraits have been validated. Do not keep stale import-row, unit-bundle, static-portrait, or preview-manifest blockers after `--plugin-root` validation proves those unit payloads exist.
- [ ] Do not hide preview UI issues by breaking upgrade chains or removing `_upg_alt` rows.
- [ ] If preview or combat null-refs before visual replacement, inspect donor-safe UnitView paths first.
- [ ] For HoMM3 sulfur costs, fold sulfur into an existing OE resource according to the faction/project rule. Fortress folds sulfur into mercury.
- [ ] Patch HoMM3-specific building costs and prerequisites in the city data, not only names/icons/layers. Donor city rows can keep playing with donor economy if `parametersPerLevel[].costs` and `prevBuildings` are not explicitly normalized.
- [ ] Keep shared Olden Era infrastructure costs standardized unless the task explicitly changes global town economy. Creature dwellings and faction-only buildings should use the HoMM3 source values, with project resource substitutions such as sulfur-to-mercury.
- [ ] Audit every build-order entry after remapping special-building SIDs. Fortress exposed that donor `Build_Gymnasium` / `Build_Lyceum` entries can survive in `buildOrders` even after the visible rows become Fortress-specific SIDs.
- [ ] Validate donor behavior tokens are gone outside allowed native-safe donor presentation fields.

## 8. Mechanics Implementation

- [ ] Start from the faction doc's mechanics, not donor behavior.
- [ ] Search existing Core data for native equivalents before writing runtime hooks.
- [ ] Copy complete native data shapes, including view rows and localization tokens.
- [ ] Convert percentage-based HoMM3, HotA, and ToA on-hit/on-attack effects into guaranteed focus-point-costing active abilities unless the source behavior is deliberately exempted.
- [ ] Preserve targeting, duration, immunity/resist lists, and effect strength explicitly.
- [ ] For focus actions that are thematically contact moves (bite, grasp, hook, charge, pounce, talon, slam, breath-on-attack), set the logic row to `attackType_="melee"` even when the effect payload is spell-like. Do not leave them as plain `cast` rows unless the intended behavior is ranged targeting.
- [ ] Apply the same rule to rows in `custom_factions/ability_overrides/*.json`; override envelopes support `attackType`, and spell-effect overrides otherwise default to `cast`.
- [ ] Do not count ordinary tags such as `Shooter`, `Ground`, or `Flying` as special abilities when auditing faction docs.
- [ ] If a mechanic cannot be data-only, statically trace the native path before adding a hook.
- [ ] Add custom mechanics through central registered paths, not through one-off per-faction plumbing branches.
- [ ] Fortress native-shape examples:
  - [ ] Dispel: use native `dispel` mechanic with `positive`.
  - [ ] Weakening Dispel: add the native `magic_shorten_shadow_effect_1` debuff.
  - [ ] Stone Gaze: use Medusa `medusa_stone`.
  - [ ] Death Stare: use native `kill_stacks` shape.
  - [ ] Poison/max-health damage: use Fatal Decay / poison-style native buffs such as `magic_fatal_decay_effect_1` and `frog_poison`.
  - [ ] Hydra all-adjacent attacks: copy native Dungeon Hydra attack patterns.
  - [ ] Regeneration: use native `heal_percent` where appropriate.
  - [ ] Double Strike: use native double-attack/extra-attack shapes where possible.
- [ ] After adding mechanics, update `Lang/english/texts/unitsAbility.json` and view ability/passive rows together.
- [ ] Live-test active abilities and attack patterns. Data-backed does not guarantee battle behavior is perfect.

## 9. Faction Skill, Laws, Classes, And Hero Specializations

- [ ] Create a unique top-level faction skill row before hero configs or skill tables reference it.
- [ ] Do not shallow-clone donor `subSkills`.
- [ ] Ensure every subskill ID is globally unique. Native session skill IDs are flattened into global dictionaries.
- [ ] Add skill-table rows and start-skill references to the custom faction skill.
- [ ] Generate law rows with custom IDs, text tokens, and icons.
- [ ] Add law text rows to the correct Lang member.
- [ ] Normalize hero classes/subclasses away from donor names/icons/text.
- [ ] Generate `DB/heroes_specializations/specializations_<faction>.json`.
- [ ] Ensure every hero config specialization ID has a matching specialization row.
- [ ] Treat missing specialization rows as load blockers. Fortress map/session load aborted in `Hex.Session.Logic.Hero` when `homm3_fortress_hero_1_specialization` was absent.
- [ ] Do not leave profile-visible polish on donor class names, subclass icons, or specialization text.
- [ ] If the first pass uses safe scaffold mechanics, document that as debt rather than letting donor specializations look final.

## 10. Heroes And Portraits

- [ ] Generate hero configs with custom IDs, names, icon keys, class names, and native biome.
- [ ] Normalize start armies to custom unit SIDs.
- [ ] Normalize skill-table rolls to the custom faction skill.
- [ ] Identify the canonical HoMM3 portrait source list.
- [ ] Decode using the actual source payload format, not file extension assumptions. HoMM3 large portraits may not be ordinary PCX files.
- [ ] Generate `homm3_hero_portraits/<faction_hero>.png`.
- [ ] Add explicit fallback mappings if the faction has fewer source portraits than OE needs.
- [ ] Test hero portraits in selector, hero profile, and army-strip/HUD paths. These are separate UI surfaces.

## 11. Unit Visual Assets

- [ ] Ensure `homm3_import.json` has entries for every expanded custom unit SID.
- [ ] Ensure each import row has `gameUnitSids`.
- [ ] Ensure each import row maps to the correct distinct lab SID and bundle.
- [ ] Ensure `_upg_alt` rows use distinct ToA lab SIDs and bundles when the faction doc names distinct alternate creatures.
- [ ] Convert VCMI JSON-frame animations into defextract-style `sequences[]` under `extracted_battle` and `extracted_map` before building Unity bundles.
- [ ] Validate idle group identity from the converted manifest, not just filename patterns.
- [ ] Generate static unit portraits.
- [ ] Generate preview/recruitment animation manifests.
- [ ] Deploy together:
  - [ ] `homm3_bundles/custom_units_*`
  - [ ] `homm3_import.json`
  - [ ] `homm3_portraits/*.png`
  - [ ] `bundle-backed Unity RIFE idle clips`
  - [ ] `homm3_lab/<labSid>/extracted_battle`
  - [ ] `homm3_lab/<labSid>/extracted_map`
- [ ] During final hardening, separate visual payload validation from broader release readiness. In the production-ready source plugin, the documented remaining factions already have `homm3_import.json` rows, bundles, static portraits, preview manifests, hero portraits, and lab sidecars; their remaining blockers are town/build-tree presentation, UI/registry exposure, terrain gaps, and mechanics unless validation later regresses.
- [ ] Verify source identity, not just path existence. Fortress ToA alternates initially had files but reused regular-upgrade bundle/source identity.
- [ ] For HoMM3 DEF creature names, do not guess base vs upgrade from shorter filenames. Stronghold Wolf Rider/Raider showed that `CB...` and `CU...` must be mapped by actual source meaning.

## 12. Town Scene

- [ ] Locate the true town-scene backdrop.
- [ ] Decode custom H3 bitmap payloads with the correct decoder.
- [ ] Confirm the source coordinate basis, usually 800x374 for HoMM3 town screens.
- [ ] Generate a 1920x1080 runtime mockup using the established top-left plate convention when matching Stronghold/Tower.
- [ ] Generate transparent building layers, not opaque full-background crops.
- [ ] Use local VCMI town-screen config for building placements when available.
- [ ] Do not ship generic/all-zero placement rows when VCMI base rows exist.
- [ ] Key `positions.json` and `building_layer_map.json` to named VCMI structures, not visual guesses.
- [ ] Implement faction town buildings through the same data/source-map path used by the working factions. Stronghold and Tower use VCMI structure names, explicit layer maps, explicit positions, and runtime resolver keys; future factions must not use a partial or Fortress-only shortcut.
- [ ] Audit every live `Build_*` row in the release city JSON, including donor leftovers such as `Build_Artifact_Market`, against the building-layer map and icon source map. If the city can request it, it needs an intentional name, icon, layer, and source note, or it needs to be deliberately removed.
- [ ] Generate or normalize building names and descriptions with the building visual/source-map pass. Correct art with donor or placeholder building text is not release-complete.
- [ ] Verify every constructed building visible in the town has all three pieces aligned: Olden Era `Build_*` SID, VCMI/source structure name, and localized display name/description.
- [ ] Generate `_1.png` or level aliases that runtime layer lookup can request.
- [ ] Generate building animation folders and `layers/anims/metadata.json` separately.
- [ ] Keep animation keys synchronized with the runtime `<layerId>_<level>` contract.
- [ ] Ensure the town animation resolver uses the custom faction SID as the town layer folder. Do not leave a Stronghold/Tower branch that maps new `homm3_*` factions back to `homm3_stronghold`.
- [ ] Ensure the runtime city backdrop path does not fall through to Stronghold or donor town art.
- [ ] Guard city backdrop/layer refresh hooks so they do nothing during map loading, `loadingScene`, or `worldLight` when no real `CanvasCityPanel` exists.
- [ ] Keep destructive town-layer clears on explicit town hide/exit paths only.

## 13. Build-Tree Icons

- [ ] Extract the faction's hall/build-tree icon source when available.
- [ ] Create an explicit source map from icon frames to Olden Era `Build_*` IDs.
- [ ] Rewrite city `icons` arrays to custom keys such as `homm3_<faction>_building_<BuildSid>_level_<N>`.
- [ ] Rewrite city `names` and `descriptions` arrays to custom localization keys for the same `Build_*` rows. Do this with the same generated mapping used for icons so text, icon, and building layer cannot drift.
- [ ] Match the maximum length of `icons`, `names`, and `descriptions` so later levels such as Mage Guild 5 are not missing icons.
- [ ] Add the custom prefix to the registry/resolver path.
- [ ] Do not fall back unknown non-dwelling buildings to capitol/horde sprites. Tower showed this makes many buttons identical.
- [ ] Patch narrow building bind/update/tooltip icon refresh paths only.
- [ ] Avoid broad `BhBuildingView` hover/transition hooks unless static tracing proves they are safe.

## 14. Faction UI Surfaces

- [ ] Patch both GameHub lobby and Quick Play faction selectors.
- [ ] Quick Play paths include `BhFactionDetails` and `BhFactionSelectButton`.
- [ ] GameHub lobby popup paths include `ScFractionSelect` rows and `BhLobbyPopupFractionElement`.
- [ ] Write localized text through the native text setter path such as `HardSetText` / `SetText`, not plain `.text`, when that is how the live surface binds text.
- [ ] Clear or restore reused panel images when hovering away from the custom faction. Stronghold background persistence exposed this.
- [ ] Add faction icon, faction card/banner, city icon, law icon, specialization icon, and hero portrait resolvers through the registry.
- [ ] Recruitment card portraits are separate from tooltip/detail portraits. Add faction-specific base-line fallback SIDs through registry data.
- [ ] Do not rely on Core icon keys alone to load plugin PNGs.

## 15. Map Objects And Adventure Map Billboards

- [ ] Add direct custom city map-object rows and art.
- [ ] Use the full castle/capitol adventure-map DEF when the source has non-castle and completed-castle variants.
- [ ] Add direct custom dwelling rows and art for tiers 1-7.
- [ ] Add direct custom dwelling names and descriptions in `Lang/english/texts/mapObjects.json` or the current release member that owns map-object localization.
- [ ] Verify external dwelling tooltip text in game, not just JSON presence. Donor aliases can display donor localization unless the per-instance custom SID/text path is active.
- [ ] Add donor dwelling aliases only with map/session context, usually after seeing the custom faction city.
- [ ] Register direct city and dwelling billboard art in the registry.
- [ ] Keep donor IDs stable when direct custom rows exist.
- [ ] Deduplicate map-object IDs before applying to `Core.zip`.
- [ ] Check `.dir` vs `.dlv` path corruption after automated rename passes.
- [ ] Treat adventure-map unit stacks as a shared path:
  - [ ] the live `UnitViewConfig` map loader symbol resolves from `GameSymbols`
  - [ ] the selected import entry matches the custom SID
  - [ ] the native donor map prefab is only a shell
  - [ ] donor renderers are hidden
  - [ ] custom `homm3_map_visual/quad` exists and is enabled
  - [ ] the custom material has a non-donor texture
  - [ ] required lab sidecar frames are deployed
  - [ ] layer/visibility is copied from the native renderable donor child, not blindly from root layer 0
- [ ] Ensure the adventure-map squad visual controller hook keeps custom renderers in sync after native shell renderers are hidden.

## 16. Runtime Hook Hygiene

- [ ] Prefer registry-driven generic hooks over new faction-specific branches.
- [ ] Keep Stronghold-named helpers as temporary adapters only; do not keep expanding them as the permanent custom-faction API.
- [ ] Put hotfix-sensitive method/field names in `GameSymbols.cs`.
- [ ] Avoid repeated `AccessTools.Method`/`AccessTools.Field` probes on hot UI or combat paths.
- [ ] Cache reflection results.
- [ ] Keep diagnostics capped and config-gated.
- [ ] If logs show repeated Harmony `AccessTools.GetTypesFromAssembly` errors, suspect our diagnostics/probes before blaming Unity systems.
- [ ] Do not revive broad global sprite setter hooks.
- [ ] Do not patch direct close/back methods that can fire during normal panel open/refresh. Gate on exact owner/surface and active screen.
- [ ] Keep city panel visibility fixes separate from click-routing fixes.
- [ ] Keep `CityNavigation` above raised build/hire canvases so the town does not trap clicks.

## 17. Validation Before Steam Apply

- [ ] Run Python syntax checks on changed scripts:
  - `python -m py_compile tools\release_port\apply_release_core_overlay.py`
- [ ] Run manifest validation:
  - `python tools\validate_custom_faction_manifests.py`
- [ ] Run source/payload validation when assets are involved:
  - `python tools\validate_custom_faction_manifests.py --plugin-root "<plugin root>"`
- [ ] Run a release Core dry run:
  - `python tools\release_port\apply_release_core_overlay.py --release-core "<Steam Core.zip>" --dry-run`
- [ ] Inspect warnings. Do not normalize real missing data into allowed debt just to pass.
- [ ] Validate the candidate archive before replacing live `Core.zip`.
- [ ] Validate the live archive after apply.
- [ ] If runtime hooks changed, run:
  - `python tools\audit_obfuscated_symbols.py`
  - `python tools\verify_patch_surfaces.py tools\il2cpp_out_<YYYYMMDD>_golden_era\dump.cs --source "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod" --no-probes -r rename_map.json` (dump from Golden Era install; see `tools/IL2CPP_DUMP.md`)
- [ ] Build against the Steam game root when C# changed:
  - `dotnet build -c Release "-p:GameRoot=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era" --nologo`
- [ ] Copy the built DLL/PDB only after a successful build.

## 18. Deployment

- [ ] Apply Core overlay through the script.
- [ ] Record the `Core.zip.backup-*` path.
- [ ] Deploy the plugin DLL/PDB if C# changed.
- [ ] Deploy plugin payload assets if visuals changed.
- [ ] Verify Steam plugin payload paths exist after deployment:
  - [ ] bundles
  - [ ] import table
  - [ ] static unit portraits
  - [ ] portrait animation manifests
  - [ ] hero portraits
  - [ ] faction icon/card/city icon
  - [ ] town backdrop/layers/building icons
  - [ ] city/dwelling map-object frames
  - [ ] lab sidecar frame roots
- [ ] Do not call a Core-only deployment done if plugin payload assets are required.

## 19. Smoke Test Order

- [ ] Check `BepInEx\LogOutput.log` first after every failed load.
- [ ] Start with same-faction vs same-faction map/session load. Stronghold vs Stronghold broke during the Fortress thread, proving the culprit can be shared source changes.
- [ ] Verify map/session load reaches adventure map.
- [ ] Verify no missing config errors such as missing hero specializations.
- [ ] Verify no duplicate map-object key errors.
- [ ] Verify custom city map billboard.
- [ ] Verify direct dwelling billboards.
- [ ] Verify generated/random donor dwelling aliases after seeing the custom city.
- [ ] Open the town screen.
- [ ] Verify town backdrop, layers, building placement, and no donor/Stronghold placeholder town.
- [ ] Verify build-tree icons, building names, and building descriptions.
- [ ] Verify town-scene building art, build-tree icon, building name, and building description all refer to the same intended structure.
- [ ] Verify hire screen, upgrade screen, close/back controls, and click routing.
- [ ] Verify faction selection in GameHub lobby and Quick Play.
- [ ] Verify faction card/banner, description, city icon, laws, hero class/profile, and hero portraits.
- [ ] Verify recruitment card portraits and unit preview/detail portraits.
- [ ] Verify adventure-map unit-stack billboards.
- [ ] Enter battle and verify:
  - [ ] battle sprites render
  - [ ] unit facing/side scale follows native orientation
  - [ ] donor meshes are hidden behind custom sprites
  - [ ] turn queue and selected-unit HUD portraits/icons are correct
  - [ ] active abilities show correct text/icons
  - [ ] active abilities are usable and not stuck on 1-turn cooldown
  - [ ] custom mechanics behave plausibly
  - [ ] attack animations use correct groups and do not fall into death frames

## 20. Common Failure Symptoms And First Checks

- [ ] Map never finishes loading:
  - [ ] Check `BepInEx\LogOutput.log`.
  - [ ] Check missing hero specialization rows.
  - [ ] Check duplicate map-object IDs from donor mutation.
  - [ ] Check squad tree existence.
  - [ ] Check town UI hooks are not clearing/rebuilding during loading scenes.
- [ ] Faction selectable but no starting town:
  - [ ] Check direct city map object row in `DB/map/objects/4_interactables.json`.
- [ ] Stronghold/Tower breaks after adding Fortress:
  - [ ] Suspect shared registry/hook/source changes from the current thread, not older unrelated history.
  - [ ] Check donor reverse lookup and shared map-object visual paths.
- [ ] Donor faction art appears:
  - [ ] Check plugin payload assets first.
  - [ ] Check resolver registration and custom key prefixes.
  - [ ] Check reused UI panel cleanup.
- [ ] Town scene is donor backdrop with no buildings:
  - [ ] Prefer owned Unity city-world paradigm (`docs/custom_town_scene_paradigm.md`): HotA world art on native `BhBuilding` slots, not Route A posters alone.
  - [ ] Check town scene source, placement map, layer names, runtime layer folder, and owned-world / city-panel gating.
- [ ] Town-hall construction menu opens then closes:
  - [ ] Open via HUD `BuildingsConstruction` navigation; do not call escape/hide on visually closed CityUI panels (`IsReleaseTownPanelVisuallyOpen`).
- [ ] Build-tree icons are repeated/wrong:
  - [ ] Check explicit build-tree icon source map; do not use layer crops as generic fallback.
- [ ] Build-tree icons and background buildings refer to different structures:
  - [ ] Compare live city `icons[]`, `building_layer_map.json`, `positions.json` `structure`, and the icon source map in one table. Per-faction source maps should win over old hard-coded icon tables.
- [ ] Buildings have wrong names/descriptions:
  - [ ] Check city `names`/`descriptions` arrays, Lang rows, and whether they were generated from the same `Build_*` mapping as icons/layers.
- [ ] External dwellings have wrong names/descriptions:
  - [ ] Check direct dwelling map-object Lang rows, donor alias context, and whether tooltip/localization sees the custom SID rather than the donor SID.
- [ ] Unit previews show donor meshes behind sprites:
  - [ ] Check preview wrapper resolution and donor renderer suppression before changing donor templates.
- [ ] Adventure-map units are invisible or donor units:
  - [ ] Check `UnitViewConfig` loader symbol, `homm3_import.json`, bundle payloads, lab sidecars, renderer layers, and squad-controller mirroring.
- [ ] Active abilities show unavailable or wrong cooldown:
  - [ ] Check release `dxr`/`dxs` manager normalization and selected-HUD binder path.
- [ ] Combat freezes with repeated reflection warnings:
  - [ ] Check stale diagnostics/probes and missing `GameSymbols` entries.

## 21. Review And Commit

- [ ] Review `git diff --stat` and `git diff -- <changed docs/scripts/source>` before committing.
- [ ] If the index already has unrelated staged asset changes, use explicit pathspec commits.
- [ ] Do not run broad cleanup or revert commands in a dirty worktree without user approval.
- [ ] Commit docs/source slices separately from large generated asset payloads when practical.
- [ ] Include validation commands and Steam backup path in the final handoff.
- [ ] State clearly whether live in-game smoke testing was run or still needs the user.
