# HoMM3 Future Faction Porting Source Of Truth

> Historical implementation record, not current source of truth. This document was last bulk-updated in June 2026 and mixes reusable design guidance with point-in-time faction status. Current manifests, generators, validators, packed `Core.zip`, and installed plugin payload take precedence.

This document records repeatable work performed while bringing Tower into the Steam release build. Use it as historical context for future HoMM3 factions, not as a live status checklist.

For a sequential future-agent checklist, start with `docs/homm3_custom_faction_porting_checklist.md`. Keep this source-of-truth document for detailed history, faction-specific notes, and implementation evidence.

## Current Baseline

- Stronghold is the working reference implementation. When a future faction behaves differently, trace Stronghold first instead of guessing.
- Steam release data must be applied through scripts, not manual `Core.zip` editing.
- Visual completion requires three independent surfaces: Core data, plugin runtime hooks, and deployed image/bundle assets.
- Runtime probes are a last resort. Prefer static tracing through current source, generated overlays, Core archive contents, and IL2CPP/decompiled paths.
- Custom faction support now has a manifest-backed registry slice. Faction source data lives in `custom_factions/*.json`, runtime metadata is mirrored in `Homm3CustomFactionRegistry`, and `tools/validate_custom_faction_manifests.py` is the shared validation gate. Use `docs/homm3_custom_faction_refactor_plan.md` for the remaining migration plan. Do not keep adding per-faction branches for donor aliases, faction UI, town visuals, map objects, unit map billboards, and overlay generation unless they are temporary adapters under that migration.
- `tools/release_port/apply_release_core_overlay.py` has a generic manifest-driven Core scaffold generator for factions with `coreOverlayEnabled` not explicitly false. It creates release rows for faction identity, city/laws, donor-safe units/views, squads, heroes, skill tables, direct map objects, hire rows, and Lang, while stripping donor abilities/passives and adding explicit `xHomm3ProductionDebt` / `xHomm3MechanicsDebt`. This is a data-surface unblocker, not final production readiness: visual payloads, import rows/bundles, runtime UI/registry mirrors, and user-guided mechanics remain separate gates. Release UnitViews must keep donor-safe `mesh`/`mapMesh` fields and use `homm3_import.json` plus bundles for HoMM3 visuals.
- The generic release overlay now owns first-pass data-only mechanics that can be copied from native rows without custom runtime hooks: no-retaliation flags and preview passives, full-strength shooter melee, breath-attack patterns, spell-level immunity passives, Phoenix-style rebirth support obstacles, Castle Archangel Rewind Life, Cove Sea Dog Guillotine Shot, Conflux Faerie Leeching Hop, and non-terrain Rampart/Dungeon faction-skill baseline bonuses. Keep these implementations in the generator, with matching logic/view/Lang/support rows, instead of editing generated `Core.zip` members by hand.
- Bulk basic-enable policy applies to all documented HoMM3 factions: registry/Core/basic presentation may be enabled once faction-owned payloads validate through the manifest/Core/plugin gates. Advanced mechanics remain explicit user-guided debt, and generic stats/costs should come from HoMM3/VCMI source data rather than donor rows. Do not confuse basic enablement with release-complete promotion.

## Tower Work Completed In This Conversation

1. Added/extended the Tower Core overlay path.
   - Historical local Tower work started in `tools/apply_homm3_tower_overlay.py`, but the current release path is the shared manifest-driven generator in `tools/release_port/apply_release_core_overlay.py`.
   - As of the June 15, 2026 Tower generic-path cleanup, Tower is not in `DEDICATED_CORE_GENERATOR_FACTION_SIDS`; Tower heroes, skill tables, map objects, unit rows, and Lang should flow through `custom_factions/homm3_tower.json` plus the shared overlay generator.
   - Tower Lang rows are merged into archive-local `Lang/*/texts/*.json`, including both `heroes.json` base rows and `heroInfo.json` `_name` rows.
   - Tower hero display rows must be canonical across the whole packed language archive, not just in `heroes.json`/`heroInfo.json`. `ensure_manifest_hero_display_name_lang_for_all()` deletes exact Tower hero display SIDs from every `Lang/*.json` member before re-adding manifest-backed rows, because stale placeholder rows in unrelated buckets such as `artifacts.json` have been proven to shadow correct names at runtime.
   - Tower arena pick content is appended during release overlay application.

2. Registered Tower as a release faction.
   - Tower faction id is `homm3_tower`.
   - Tower native terrain/biome must be `Tundra`, cloned from Snow presentation, not `Grass` or plain `Snow`.
   - Reapply `tools/release_port/apply_release_core_overlay.py` if Steam `DB/fractions/10_homm3_tower.json` regresses.

3. Cloned functional donor scaffolding from Human.
   - Tower squads, hero scaffolding, and unit views use Human donors.
   - This gets Tower through native game systems while HoMM3 visuals are layered in by plugin hooks.

4. Fixed the release-safe UnitView contract.
   - Steam release `DB/units/units_views/homm3_tower/*_v.json` must keep native-safe Human donor `mesh` and `mapMesh` prefab fields.
   - Do not point those release fields directly at `homm3_import/tower/*`.
   - The import visual path belongs in `homm3_import.json` plus `custom_units_h3_*` bundles.
   - Wrong direct `homm3_import/tower/*` UnitView paths can crash combat/previews before replacement hooks run.

5. Added Tower unit preview/static portraits.
   - `tools/extract_homm3_tower_unit_portraits.py` is retired as a fail-closed loose-preview generator; Tower static portraits come from `tools/generate_homm3_interface_portraits.py`, and idle animation is bundle-backed.
   - Static PNGs are written under `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_portraits/h3_*.png`.
   - Idle/preview animations are bundle-backed Unity RIFE clips; do not write loose `homm3_portrait_anims/h3_*/` runtime payloads.
   - Blank previews usually mean these assets were not generated or deployed.

6. Fixed Tower hero portraits.
   - `tools/extract_homm3_hero_portraits.py` now decodes HoMM3 custom large portrait payloads directly.
   - Do not use Pillow's ordinary PCX decoder for these large portraits; it can produce confetti-like output.
   - Tower hero portrait files are `homm3_tower_hero_1.png` through `homm3_tower_hero_18.png`.

7. Rebuilt Tower town-screen art from the correct sources.
   - The correct Tower static backdrop is HoMM3 `H3bitmap.lod` member `tbtwback.pcx`.
   - `TpThBkTw` / `TowerHallBg.png` is the building UI plate, not the town scene.
   - `tools/build_homm3_tower_town_scene_assets.py` regenerates the runtime mockup and layers.
   - Runtime convention follows Stronghold: source coordinates are 800x374, scaled to a 1440x673 top-left town plate inside a 1920x1080 PNG.
   - HoMM3 town backdrops that use this padded plate convention must use the top-left anchored backdrop/layer scale path. Tower shares Stronghold's `homm3StrongholdTownBackdropScale` behavior instead of center-scaling.
   - Do not ship opaque full-background building layer crops; use transparent building layers aligned to the source backdrop.
   - Create `_1.png` layer aliases because the runtime layer lookup can request those variants.
   - Tower building animations are generated by the same script into `layers/anims/`.
   - Current animated Tower keys are `dwellingUp2Lvl1_1`, `dwellingUp2Lvl3_1`, and `dwellingUp2Lvl7_1`; the other currently available Tower DEF sources are single-frame/static.

8. Added Tower map billboards.
   - City billboard hook is the shared manifest-owned `Homm3CustomTownMapBillboard`; `Homm3TowerTownMapBillboard` is retired.
   - City art lives under `homm3_runtime_assets/map_object_refs/homm3_tower_city/`.
   - External Tower dwellings are handled through `Homm3StrongholdDwellingMapBillboard`.
   - Direct `barracks_homm3_tower_*` SIDs map to `homm3_runtime_assets/map_object_refs/homm3_tower_dwellings/`.
   - Release random-hire `barracks_human_*` objects are eligible for Tower art only when the exact live hire payload resolves to one Tower dwelling SID; seeing `homm3_tower_city` alone is not sufficient context.
   - Stronghold and Tower both deliberately use Dungeon barracks prefab paths in `DB/map/objects/4_interactables.json`; the custom visual is a runtime billboard layered onto the native donor root, not a unique prefab path.
   - The live dwelling hook must reapply the billboard for the current resolved SID even if a marker already exists on the root. Tower and Stronghold can share cached Dungeon barracks roots, and the marker name is shared; treating "marker exists" as "this faction is already correct" can make Tower dwellings silently keep donor/previous art.
   - Do not rewrite shared Human `ObjectConfig` id fields to Tower ids when direct `barracks_homm3_tower_*` rows also exist. That mutates global config state and can make `Hex.Map.MapObjects.Init` throw `ArgumentException: An item with the same key has already been added`.
   - Stronghold's older Dungeon alias path rewrites reflected `ObjectConfig` SID/id fields for tooltip/localization, but Tower needs a per-instance tooltip/localization solution if Human random-hire aliases show donor text.

9. Updated release UI surfaces.
   - GameHub lobby and Quick Play faction selectors are separate UI paths.
   - Quick Play uses `Hex.BhFactionDetails` and `Hex.BhFactionSelectButton`.
   - Lobby popups use `Hex.GameHub.Lobby.UI.ScFractionSelect` rows and `BhLobbyPopupFractionElement`.
   - Patch both if faction cards/descriptions are incomplete.
   - Write `cme` text with `HardSetText`/`SetText`, not plain `text`.

10. Built, applied, and deployed.
   - Ran the release build against the Steam game root.
   - Applied `tools/release_port/apply_release_core_overlay.py` to Steam `Core.zip`.
   - Deployed rebuilt plugin DLL/PDB and Tower assets into the Steam BepInEx plugin payload.
   - Verified Tower `Core.zip` biome, release-safe UnitView donor fields, required portrait assets, preview manifests, town layers, and dwelling billboard assets.

11. Committed the scoped Tower visual/native-safety fix.
   - Commit: `e907a2d7 Fix Tower release visuals and native-safe unit views`.

12. Filled the next Tower release gaps.
   - Recruitment card portrait hooks now gate on any supported HoMM3 city, not only Stronghold, and Tower uses `h3_gremlin`, `h3_gargoyle`, `h3_golem`, `h3_mage`, `h3_genie`, `h3_naga`, `h3_giant` as index fallbacks.
   - Tower building tree icons are normalized to `homm3_tower_building_<BuildSid>_level_<N>` in `homm3_tower_city.json`, and the runtime icon cache resolves them from `homm3_runtime_assets/town_scene_refs/homm3_tower/layers/`.
   - Mage Guild level 5 must get an icon key even if the donor city had fewer icon rows than name/description rows; city icon normalization uses the longest of `icons`, `names`, and `descriptions`.
   - Tower hero configs are normalized after Human cloning: `icon=hero_homm3_tower_<N>`, `name=homm3_tower_hero_<N>_name`, `nativeBiome=Tundra`, class/table split at heroes 1-8 might and 9-18 magic, and start skills/table rolls point to `skill_faction_homm3_tower`.
   - `skill_faction_homm3_tower` is Arcane Battery. Basic/Advanced/Expert grant `skill_faction_homm3_tower_ability_arcane_battery` as a 2/1/0-Focus once-per-round hero ability. Native ability data carries `refresh_spell_book` only; per-spell cooldowns are intentionally not cleared. Advanced/Expert scholar subskills use `sub_skill_faction_homm3_tower_arcane_battery_*` SIDs for curriculum, Chronomancy, Mana Well Aegis, remote Arcane learning, spell-cost relief, and start Focus. `Mana Well Aegis` is still implemented by `Homm3TowerBottomlessKnowledgeHook` after `ManaPercentSettingReward`, scoped to explicit negative dispellable hero-map curse buffs. Do not restore Bottomless Knowledge `manaRestoreBonusPercent` ranks or the old non-`arcane_battery_` scholar SIDs.
   - `DB/map/objects/4_interactables.json` must include `barracks_homm3_tower_1..7`; `DB/objects_logic/hires/barracks.json` alone is not enough for direct map dwelling objects.
   - Tower hero portrait key normalization accepts release-cloned suffixes such as `hero_homm3_tower_1_ister` and maps them back to the generated `homm3_tower_hero_1.png` files.

## Fortress Release First Pass

1. Fortress release data is generated by `tools/release_port/apply_release_core_overlay.py`.
   - Source design is `docs/homm3_faction_plans/fortress.md`.
   - Do not use the old `generate_homm3_fortress_city.py` output for release; that script is a Dungeon-perfect debug clone.
   - Collision risks and validation gates live in `docs/homm3_fortress_release_collision_risk_plan.md`.

2. Release identity and donor contract.
   - Faction SID is `homm3_fortress`; city SID is `homm3_fortress_city`.
   - City, laws, and heroes currently clone Nature scaffolding. The city logic must keep a native donor `sceneName` such as `cityNature` until a real Fortress scene exists.
   - Keep Nature donor city UI/icon/localization/build-tree tokens until Fortress has a traced town-screen/build-tree asset set. Only rewrite the city identity, faction field, and real recruitment payloads. A broad `nature`/`Nature` -> `homm3_fortress`/`Homm3Fortress` token remap creates missing `Homm3Fortress_Build_*`, `siege_walls_*_homm3_fortress`, and related runtime keys that can poison map/session loading without a clean managed exception.
   - `DB/map/objects/4_interactables.json` must include a direct `homm3_fortress_city` row using a native donor prefab path. Adding the faction to `DB/data.json` without that row lets random map/session setup select Fortress but leaves no starting-town map object to instantiate.
   - Nature donor city/dwelling rows must have their real recruitment payload fields rewritten: `unitsHire.units[].sids`, `unitsData.units[].sids`, `cityUnitsIncrementFromBarrack` parameters, and guard unit SIDs. A top-level `units` field is not used by the working Stronghold/Tower hire rows and does not repair donor recruitment.
   - Data-safe city-building mechanics should be generated through the release overlay's shared `CITY_BUILDING_MECHANICS_BY_FACTION` table, not by editing `Core.zip` or leaving donor bonuses in place. Fixed income uses native `sideRes` rows with canonical Olden Era resource ids, and flat weekly horde growth uses explicit `cityUnitsIncrement` rows for every receiver SID from the faction manifest. If exact HoMM3 building cost, prerequisite, resource output, or build-slot data is not sourced, keep that as generated debt instead of silently shipping the donor row as if it were exact.
   - Generic faction building localization must use canonical HoMM3/HotA building names from source data, not creature-derived placeholders. For example, Cove tier dwellings are `Nymph Waterfall`, `Shack`, `Frigate`, `Nest`, `Tower of the Seas`, `Nix Fort`, and `Maelstrom`; do not regenerate labels like `Pirate Dwelling` from unit names when a town building source exists.
   - `DB/squads/squads_homm3_fortress/**` is required for map/session generation. Clone Nature squad budgets, rename `squad_nature` ids/paths to `squad_homm3_fortress`, and rewrite every Nature unit SID to the matching Fortress `h3_*` unit SID.
   - Fortress hero configs must be accompanied by `DB/heroes_specializations/specializations_homm3_fortress.json`. If a hero points at `homm3_fortress_hero_N_specialization` and that row is absent, map/session load aborts in `Hex.Session.Logic.Hero`.
   - Unit donors are mixed and must stay explicit: Gnoll -> Human Esquire, Lizardman -> Human Crossbowman, Serpent Fly -> Human Griffin, Basilisk -> Nature Qilin, Gorgon -> Dungeon Minos, Wyvern -> Human Angel, Hydra -> Dungeon Hydra.
   - Because Fortress shares some donors with Stronghold/Tower, donor-to-custom reverse lookup is ambiguous and should fail unless explicit faction context is available.

3. Implemented release mechanics.
   - `skill_faction_homm3_fortress` is a unique top-level Swamp Tactics skill row.
   - Rank 1 applies enemy `initiative -1`; rank 2 applies enemy `initiative -1` and `speed -1`; rank 3 applies enemy `initiative -2` and `speed -1`.
   - The row uses native `unitStat` bonuses with `receiverAllegiance=enemy` and no donor subskills.
   - Fortress law text rows belong in `Lang/english/texts/factionLaws.json`; the misspelled `fractionLaws.json` member is ignored by release.
   - Fortress law rows now use `fraction_law_homm3_fortress_<N>_icon` keys, resolved at runtime through the custom-faction UI icon registry to Fortress faction art. Do not point Fortress laws back at `fraction_law_nature_*_icon` or `Scroll_Faction_Nature`.
   - `DB/heroes_sub_classes/sub_classes_homm3_fortress.json` is generated from Nature subclass structure but normalized to `sub_class_homm3_fortress_<might|magic>_<N>` ids, Fortress faction, Fortress class names, and Fortress-resolved icon keys. This removes the old optional-current-debt warning for `heroSubClasses`.
   - Fortress hero configs must set `className` to `Beastmaster` or `Witch`, `classIcon` to the normalized Fortress subclass icon key, and specialization rows to Fortress ids/text/icons. Do not leave profile-visible hero polish on Nature class names, Nature subclass icons, or Nature specialization text.

4. Fortress visual deployment.
   - `tools/deploy_homm3_fortress_assets.py` is retired because it can recreate loose runtime payloads. Fortress release-side assets are now owned by the project deploy target, `homm3_runtime_assets`, bundle-backed idle clips, and `tools/validate_custom_faction_manifests.py --plugin-root ...`.
- Core.zip contains gameplay/data rows; it does not carry plugin-side visual payloads. If Fortress is selectable but the custom-game icon/card or unit portraits are blank, check the Steam plugin payload first: `homm3_bundles/custom_units_fortress_h3_*`, `homm3_portraits/h3_gnoll*.png`, bundle-backed recruitment idle clips, `homm3_runtime_assets/faction_icons/homm3_fortress/Icon_Faction_Fortress.png`, and `homm3_runtime_assets/town_scene_refs/homm3_fortress/Fortress-in-background.png`.
- The old bulk remaining-faction deploy helper is retired because it can recreate loose payloads. Use the project deploy target and validator-owned missing-source reports; do not point a missing `_upg_alt` SID at the standard-upgrade bundle just to quiet validation.
- Use `--bundle-import-only` when only bundle/import rows need refreshing. That mode still enforces real source rows with `--strict-missing`, updates `homm3_import.json`, and can copy bundles/import data into a `--plugin-root`, but it skips expensive portrait and `homm3_lab` sidecar walks for both local and plugin targets.
- For remaining-faction card/icon reference art, use `tools/deploy_homm3_remaining_reference_assets.py`. Castle, Dungeon, Rampart, Conflux, Inferno, and Necropolis cards come from decoded `H3bitmap.lod` town backdrops; Cove comes from HotA Cove town background. Derived square icons must stay source-recorded and should be replaced later only by better faction-owned icon art, not donor faction UI art.
   - `Homm3StrongholdFactionBannerSpriteCache` must explicitly resolve `homm3_fortress` banner/card sprites. Do not expect a custom Core.zip faction `icon` key to load arbitrary plugin PNGs by itself.
   - Fortress town card/backdrop must be HoMM3 `H3bitmap.lod` member `tbfrback.pcx`, decoded as the custom 800x374 BGR backdrop payload. Do not use VCMI/third-upgrades `fortressHallBg.png`; that is a hall/build-tree plate, not the swamp town scene.
   - Fortress Tears of Ashan alternate-upgrade source assets are local: `vcmi/Mods/tears-of-ashan/content.zip` contains `config/creatures/fortress/lvl*Alt.json`, alternate icons, battle sprites, and map sprites. `tools/homm3_import/extract_creature.py` converts VCMI JSON-frame animations into the same `homm3_lab/<sid>/extracted_battle` / `extracted_map` contract used by defextract, with source material staged under `OfflineUnlockMod/homm3_runtime_assets/toa_unit_sources/homm3_fortress/`; distinct ToA bundles and deploy payloads must flow through the current bundle/import/deploy target rather than the retired Fortress loose deploy script.
   - The remaining documented factions use the same ToA visual-source rule through `tools/homm3_import/prepare_remaining_faction_bundles.py`; `tools/deploy_homm3_remaining_unit_assets.py` is retired and must not be used for deploy. Keep source/lab SIDs distinct from game-facing `_upg_alt` SIDs: for example `h3_glaivier` is the Unity lab/bundle source, while `h3_pikeman_upg_alt` is the Olden Era SID in Core/import rows. The import table is the translation boundary. Do not make Core rows or registry mirrors depend on source-only lab SIDs, and do not zero a missing-asset debt report unless `--strict-missing` resolves every documented variant from real ToA/HotA/HoMM3 sources.
   - Worktree checkouts may not contain the large ToA `content.zip` or the shared Unity authoring project even when the main checkout does. The extractor/prep/deploy tools search both the worktree root and main checkout root; if a future script only checks `ROOT / "vcmi"` or `ROOT / "oldenera_factions"`, it can falsely report missing sources or fail to deploy freshly built lab sidecars.
   - `tools/homm3_import/build_out/` is ignored for new files, but existing production custom-unit bundles are tracked there. After a successful Unity build for new faction units, force-add the new bundle and `.manifest` files explicitly; otherwise the Steam install may work locally while the repository remains unable to reproduce the payload.

5. Open Fortress debts.
   - Fortress now uses its own town backdrop mockup path, `homm3_runtime_assets/town_scene_refs/homm3_fortress/mockups/homm3_fortress_background_mock_1920x1080.png`. Do not let the runtime fall through to Stronghold for the Fortress city backdrop or town-layer folder.
   - Local VCMI has authoritative Fortress town placement data at `vcmi/Mods/third-upgrades/content/config/town-screen/fortress/factions.json`. Remove any guidance that says Fortress base placement data is missing. The current validation gate should fail `positions.json` / `building_layer_map.json` if Fortress layers are generic, all-zero, unknown to VCMI, or third-upgrade-only while VCMI base placement rows exist.
   - Fortress building presentation must be generated as one surface: city `icons`, `names`, `descriptions`, and `narrativeDescriptions` arrays must point at Fortress keys; `cities.json` must define those keys; layer/source maps must use the live city SIDs carried by the Nature scaffold, including `Build_Mother_Nature`, `Build_Mycelium_Roots`, and `Build_Spring_of_Life`; and direct external dwelling text belongs in `Lang/english/texts/mapObjects.json`.
   - The current Fortress release rows set HotA base/standard-upgrade combat stats and costs directly during overlay generation. HoMM3 sulfur unit costs are folded into `mercury` for Olden Era release data, matching the existing Stronghold/Future-faction resource rule.
   - Fortress `_upg_alt` source art and Unity bundles are no longer missing for the current release payload. The local Tears of Ashan zip is the canonical source for alternate unit sprites, and `_upg_alt` import rows must stay on distinct lab SIDs/bundles such as `h3_corrosive_gorgon` and `custom_units_fortress_h3_corrosive_gorgon`, not the regular `_upg` bundle.
   - The May 14 Fortress quality pass strips misleading donor ability/passive mechanics from generated unit logic and view rows before adding source-backed native mechanics. Current Fortress mechanics are data-driven from existing Core patterns: Dragon Fly Dispel uses `dispel positive`, Weakening Dispel adds `magic_shorten_shadow_effect_1`, Basilisk Petrifying Gaze uses `medusa_stone`, Mighty Gorgon Death Stare uses `kill_stacks`, Wyvern poison uses `magic_fatal_decay_effect_1` / `frog_poison`, Hydra all-adjacent uses native Dungeon Hydra attack patterns, and Ruinous Hydra regeneration uses `heal_percent`. Keep new faction mechanics on these copied-native shapes or a statically traced hook; do not restore donor ability strings as placeholders.
   - Direct map objects exist as `homm3_fortress_city` and `barracks_homm3_fortress_1..7`; generated donor-dwelling aliasing must remain per-instance/contextual and must not mutate shared donor `ObjectConfig.id` fields.
   - Fortress class/subclass/specialization rows are release-safe scaffolds, not final HoMM3 specialty design. They intentionally avoid donor names/icons/text, but the exact Beastmaster/Witch specialty spread still needs a later design pass.

## Dungeon Basic Enablement

1. Dungeon has a manifest-owned source declaration, generic Core scaffolding, runtime registry mirroring, and release UI presentation coverage, but it is not mechanics-complete.
   - `custom_factions/homm3_dungeon.json` reserves `homm3_dungeon` and `homm3_dungeon_city`; do not use `dungeon` or `dungeon_raw` for the custom faction because those collide with native Olden Era Dungeon surfaces.
   - The manifest is basic-enabled, so faction-owned Core rows, `Homm3CustomFactionRegistry` presentation metadata, and release selector exposure are allowed once the faction-owned payload validates.
   - Basic enablement is not a claim of source-exact completion. Before calling Dungeon production-ready, finish exact `unitLines[].variantSids`, matching exact-SID `homm3_import.json` rows and plugin payloads, generated Core row cleanup, and validator runs with both `--core` and `--plugin-root`.

2. Dungeon visual payload is partially staged and still needs hardening.
   - `tools/deploy_homm3_dungeon_assets.py` lists the required plugin payload paths and should remain the validation gate for staged assets.
   - Do not substitute native Olden Era Dungeon textures/cards/town assets for HoMM3 Dungeon. The Dungeon spec requires HoMM3 town/card/backdrop, city map object, dwelling objects, unit visuals, hero portraits, and ToA alternate sources.

3. Dungeon schema/mechanics debts are explicit.
   - The generic generator and runtime registry can read exact variant SIDs, but Dungeon has not been fully converted yet. Current game-facing rows still use suffix SIDs such as `h3_red_dragon_upg`, while source-exact SIDs such as `h3_infernal_troglodyte`, `h3_black_dragon`, and `h3_shadow_dragon` are not complete `gameUnitSids`. Convert manifest `variantSids`, import rows, portraits, and Core rows together; do not treat basic registry mirroring as source-exact completion.
   - Native `skill_faction_dungeon` / Triumvirate's Strength must not be reused for `homm3_dungeon` until static tracing proves its faction/unit filters include custom Dungeon heroes and units. Until then, the scaffold reserves `skill_faction_homm3_dungeon`.
   - Stone Gaze, Scorpicore paralysis, Shadow Dragon acid breath, and other chance-on-hit effects still follow the shared conversion rule: implement them as guaranteed focus-point active abilities with source targeting, duration, removal, and immunity/resist rules preserved.

## Necropolis Manifest Scaffold

1. Necropolis has a manifest/registry/import-table scaffold and generic Core rows, not a complete release payload.
   - Source design is `docs/homm3_faction_plans/necropolis.md`.
   - Manifest path is `custom_factions/homm3_necropolis.json`.
   - Runtime mirror path is `Homm3CustomFactionRegistry`.
   - Import declarations live in `OfflineUnlockMod/homm3_import.json` and intentionally declare future Necropolis bundle/lab paths without claiming those bundles are built.

2. Current schema limitation.
   - The manifest contract still assumes `base`, `_upg`, and `_upg_alt` SIDs.
   - Necropolis therefore records source creature names such as Skeleton Warrior, Zombie, Wraith, Vampire Lord, Power Lich, Dread Knight, and Ghost Dragon as display names over suffix SIDs.
   - Do not create ad hoc runtime aliases like `h3_zombie -> h3_walking_dead_upg`; add explicit per-variant SID support to the manifest/generator contract before changing runtime identity.
   - ToA extras outside the seven-line contract, including the Guard branch, Skeleton Sharpshooter, and Dracolich, remain documented debt.

3. Reference assets.
   - `tools/deploy_homm3_necropolis_assets.py` extracts/copies source-owned reference assets for manifest validation only: faction icon, Necropolis capitol map object, seven creature/dwelling map frames, and a town-source manifest.
   - This script does not build Unity bundles, portraits, hero portraits, town layers, building icons, Core rows, or mechanics.
   - The real Necropolis town backdrop still needs by-eye source validation like Tower/Fortress; do not use donor Undead town assets or third-upgrade-only frames as evidence of complete town-screen support.

4. Release promotion blockers.
   - The generic Core rows cover faction JSON, city logic, laws, units, squads, heroes, specializations, skills, map objects, hire rows, and Lang rows, but they deliberately carry mechanics debt and donor-safe visuals.
   - Before promotion, audit the generated rows for Undead legality/immunity data even if Bone/Ghost/Spectral Dragon use Dungeon Black Dragon as the current visual donor.
   - Necromancy, Skeleton Transformer, Cover of Darkness, undead immunity parity, Lich death cloud, Vampire Lord life drain, Wraith mana drain, Ghost Dragon Aging, and all chance-proc-to-focus conversions remain static-trace or mechanics work.

## Cove Basic Enablement

1. Cove is manifest-owned and basic-enabled for release scaffolding, but it is not mechanics-complete.
   - Source design is `docs/homm3_faction_plans/cove.md`.
   - Manifest path is `custom_factions/homm3_cove.json`.
   - Cove is basic-enabled: `runtimeMirrorRequired=true`, `coreOverlayEnabled=true`, and faction-owned registry/UI presentation rows are allowed once faction-owned payload validation passes.
   - Cove now has substantial local HotA presentation payloads in the production-ready worktree, including import rows, bundles, portraits, hero portraits, town scene assets, city/dwelling billboard art, Cannon asset/audio payloads, and `extracted_battle` lab sidecars. Keep plugin payload validation, Steam Core validation, and the remaining Accurate Shot/Cannon/source mechanics as explicit hardening gates.

2. Cove source ownership is HotA-local.
   - Use `vcmi/Mods/hota/mods/cove/Content/...` for Cove faction config, creatures, town, map objects, heroes, sounds, and Accurate Shot.
   - Use `vcmi/Mods/hota/mods/cannon/Content/...` for Cannon config, sprites, projectile art, map art, and sounds.
   - `tools/deploy_homm3_cove_assets.py` audits those source lanes and validates expected plugin payload paths through the current `homm3_import.json` gameUnitSids, bundle names, and HotA lab SIDs. Its `--deploy-cannon` mode copies the HotA Cannon config, battle/projectile/map sprites, icon PNGs, and WAV files into `homm3_runtime_assets/cannon/homm3_cove/manifest.json`; this is asset packaging only, not a Cannoneering mechanics implementation.
   - `tools/build_homm3_cove_town_scene_assets.py` generates the Cove town-screen mockup, layer PNGs, animation metadata/frames, build-tree icons, and source maps from HotA `town/structures.json`, `town/town.json`, building DEFs, and `townhall` icon PNGs.
   - HoMM3 Complete LOD-only extraction is insufficient for Cove. Do not substitute donor Human/Nature/Dungeon assets to make the validator pass.

3. Current schema/debt notes.
   - Cove uses `variantSids` because HotA's exact names do not always match the suffix convention: `h3_oceanid`, `h3_seaman`, `h3_corsair`, `h3_sea_dog`, `h3_ayssid`, `h3_sorceress`, `h3_nix_warrior`, and `h3_haspid` are explicit source SIDs. Runtime exact-variant support, Core scaffolding, and local import/bundle coverage are available; Cannon/mechanics debt remains explicit until implemented, and generic stats/costs should continue to come from HotA/VCMI source data instead of donor rows.
   - Pirate/Corsair/Sea Dog uses the manifest's third `_upg_alt` slot for HotA's second pirate upgrade, while other `_upg_alt` rows still represent Tears of Ashan alternates from `docs/homm3_tears_of_ashan_creature_specs.md`. Future generator code must not assume every `_upg_alt` is ToA content.
   - Cove's release terrain is the custom `Tropical` biome from the shared custom-biome pack, cloned from Sand presentation with no visual changes. Do not move Cove back to Autumn or invent a Cove-specific Swamp lane unless the faction design is deliberately changed and the custom-biome pack, runtime definitions, and Core validation are updated together.
   - Local HotA has more Cove hero configs than the current 18-hero manifest contract. Final hero inclusion/class split is release debt.
   - Accurate Shot, after-shot Weakness/Disrupting Ray, Nix attack ignore, Poisonous, Haspid Revenge, Cannon/Cannoneering, Shipyard, and water behavior all require static tracing or copied-native mechanics before production-ready signoff.

## Rampart Manifest Scaffold

1. Rampart has a manifest-owned source declaration and generic Core scaffolding, but it is asset-pending and not production-ready.
   - Source design is `docs/homm3_faction_plans/rampart.md`.
   - Manifest path is `custom_factions/homm3_rampart.json`.
   - `tools/release_port/prepare_homm3_rampart_overlay.py` is a preflight stub that expands the manifest SIDs and reports release blockers. The release overlay script now owns the actual generic Core rows.
   - The manifest is marked `validation.status=asset_pending` and `runtimeMirrorRequired=true`; runtime identity is mirrored, but missing alternate-upgrade assets/import rows remain warnings until the real asset lane exists.

2. Rampart proves the manifest contract needs exact per-variant unit SIDs.
   - HoMM3/ToA source names are not suffix-only: `h3_centaur_captain`, `h3_battle_dwarf`, `h3_grand_elf`, `h3_silver_pegasus`, `h3_dendroid_soldier`, `h3_war_unicorn`, `h3_gold_dragon`, plus distinct `_upg_alt` rows such as `h3_centaur_ranger_upg_alt` and `h3_diamond_dragon_upg_alt`.
   - Keep those IDs in `unitLines[].variantSids`; do not rewrite them to `baseSid + _upg` for helper convenience.
   - Release generators, runtime mirrors, and import-row validation now use expanded manifest SID helpers. `Homm3CustomFactionRegistry.UnitLine` has explicit `upgradeSid` / `alternateUpgradeSid` fields; keep validator parsing in sync with that shape.

3. Rampart must not ship as a Nature behavior clone.
   - Blocked mechanics are Dwarf hostile-spell resistance, Pegasus Magic Damper, Dendroid Binding, Unicorn deterministic focus Blind plus adjacent non-stacking resistance aura, dragon breath attack and spell-level immunity, Treasury, Mystic Pond, and Fountain of Fortune.
   - If a mechanic is not data-only, statically trace the native path or emit explicit generated audit debt. Do not hide missing mechanics behind donor abilities or passive text.
   - Donor collisions are expected: Rampart currently uses Human `sunlight_cavalry` and `esquire` plus Nature `elf_tracker`, `twinkle`, `ent`, `qilin`, and `phoenix`; reverse lookup remains context-required.

## Future Faction Porting Checklist

## Conflux Initial Slice

- Conflux is declared in `custom_factions/homm3_conflux.json`, mirrored in `Homm3CustomFactionRegistry`, and release-enabled through the generic Core overlay path. Older `validation.releasePromotionBlocked=true` notes were stale and must not be used to hide Conflux from release selection.
- `docs/homm3_conflux_asset_sources.md` records the current source declarations from `H3sprite.lod` and `H3ab_spr.lod`. Several entries, especially Magic/Magma Elemental naming and the direct town adventure-map object, still require visual verification before extraction.
- `tools/deploy_homm3_conflux_assets.py --check-sources` is a historical source-presence gate only. Current release payload ownership is split across the manifest, release overlay, generic asset deployment, and runtime mirrors; do not treat this checker as a release blocker.
- Do not resolve Conflux runtime crashes by leaning on Nature donor art or by removing the faction from `DB/data.json`. Missing or incorrect Conflux payloads should stay visible as validation debt and be fixed in the owned generation/deployment path.

### 1. Data And Identity

- Choose the faction SID and keep it consistent across Core data, plugin hooks, Lang rows, and asset folders.
- Add faction JSON under the generated overlay.
- Set native terrain/biome explicitly.
- Custom factions now use faction-owned custom biome ids through the main custom-biome pack, not donor biome ids. `DB/biomes_info.json` remains a faction-by-biome mapping table, but the supported route deliberately expands the terrain pipeline with matching Core rows in `DB/map/tiles/tiles.json`, `DB/map/waters/waters.json` if relevant, `generator/generator_config.json` `waterForBiome`, `generator/generator_environment_assets.json` `EnvironmentAssets.BiomeConfig`, `DB/arenas/arenas_info.json`, arena view configs, arena tile-set assets, and arena obstruction model rows. Rendering is separate again through runtime `Hex.Render.SoTerrainMaterial.Biome` entries with `tileCode`, splatmap, and texture fields. May 20/22 tracing showed `beg..ctor` builds render dictionary `bseu` from `SoTerrainMaterial.biomes[*].tileCode`, but the wrapper constructor alone is not a sufficient hook point on current Steam. `Homm3SwampAutumnTintProof` now extends the material biome rows, seeds renderer lookup for custom tile codes, and refreshes packed terrain materials through the constructor-used `beg.nac()` / `beg.ivz()` / `beg.kwe()` path for non-alias custom textures. `bkr.WeightsArray` is only an eight-slot selector for tilesets within one `EnvironmentAssets` biome, not proof of an eight-biome global cap. Use `tools/release_port/build_custom_biome_assets.py` plus `tools/release_port/apply_custom_biome_pack.py`; the old one-off `spike_custom_biome_core.py` notes are historical proof-spike context only.
- The May 20 `Swamp` scratch Core was deployed only to the Steam copy install (`Heroes of Might and Magic Olden Era - Copy`). The first check only proved plugin/Core startup and was ambiguous because Fortress still used `biome=Autumn`; do not treat that run as proof that a real `Swamp` biome can load.
- The May 20 quick visual proof used `tools/release_port/build_swamp_tint_proof_assets.py` to generate bright-green sidecar PNGs from exported Autumn ground textures under `OfflineUnlockMod/homm3_runtime_assets/terrain_tint_proofs/swamp/` and a blue Autumn-fallback marker under `OfflineUnlockMod/homm3_runtime_assets/terrain_tint_proofs/autumn_fallback_marker/`. Those assets and `tools/release_port/spike_custom_biome_core.py` were proof-spike scaffolding only. Current custom terrain definitions live under `OfflineUnlockMod/homm3_runtime_assets/custom_biomes/`, are generated by `tools/release_port/build_custom_biome_assets.py`, and are integrated into Core by `tools/release_port/apply_custom_biome_pack.py`.
- Later May 20 runtime evidence invalidated the optimistic "accepted Swamp" read: when Fortress was actually set to `biome=Swamp`, map generation completed but map load did not. `Player.log` showed `[MapGen] Can't find water for biome 'Swamp'`, then repeated `KeyNotFoundException: The given key '8' was not present in the dictionary` at the terrain renderer map path. The water error was traced to the first scratch Core omitting `generator/generator_config.json` `waterForBiome` and `generator/generator_environment_assets.json` rows; the custom-biome pack now owns those rows. The renderer miss was not solved by a donor alias or by constructor-prefix-only registration. Current working support registers the real custom tile code to the custom biome index and refreshes packed material state for custom textures.
- The follow-up copy-install run with the corrected generator rows showed `Homm3SwampAutumnTintProof` did register and eventually logged that it applied through `SoTerrainMaterial.instance`, but the renderer lookup still missed tile code `8`. That means the old proof hook fired too late for the map-view renderer dictionary path, not that the generator rows were still missing. Static disassembly identified `beg..ctor` as the native tile-code registration point, but current Steam evidence showed patching only that wrapper constructor is not enough when the renderer already exists. The live route seeds the renderer lookup from current map-build hooks and keeps donor aliases forbidden; do not revive the late `kvs` dictionary alias path.
- Later May 20 visual proof evidence: the primed terrain hook let a generated `Swamp` map load and showed the ground as dark grey/green, but trees and combat terrain stayed pink because those are separate presentation lanes. `generator/generator_environment_assets.json` had cloned Autumn object SIDs such as `tree_big_autumn_*`, `tree_autumn_*`, `flowers_autumn_1`, `grass_autumn_*`, `hill_autumn_*`, and `mountain_autumn_*`; combat used cloned Swamp arena view ids that still pointed at `sceneName=autumnArena` / `autumnSiegeArena` and `AutumnTileSet` / `Nature*TileSet`. Current pack generation must keep each custom biome id while choosing explicit presentation donors for terrain, RMG decorations, and combat arena rows; do not assume ground texture success proves trees or combat.
- Combat obstacle visuals are another separate presentation lane. `DB/arenas/arenas_obstructions_configs/test_obstructions.json` stores biome-keyed model paths independently from arena view configs; missing custom biome keys show arrow/dot placeholder markers. The custom-biome pack should clone each custom key's obstruction model list from its arena donor.
- Copy-install deployment warning: keep only the active `Core.zip` as a `.zip` file directly in `HeroesOldenEra_Data/StreamingAssets`. A May 20 Swamp deploy left `Core.backup-before-swamp-native-20260520-180230.zip` next to `Core.zip`; startup then froze in a loop with `System.ArgumentException: An item with the same key has already been added. Key: hub_icon` from `cjz.ruw(...)`. That was not a Swamp renderer failure: it was the native loader ingesting the backup archive as a second Core-like zip and double-registering campaign icon assets. Store backup archives in a subfolder or rename them with a non-`.zip` suffix such as `Core.zip.backup-*`.
- Copy-install plugin warning: keep only the active `OfflineUnlockMod.dll` and dependency DLLs as `.dll` files directly under `BepInEx/plugins/OfflineUnlockMod`. A backup named `OfflineUnlockMod.backup-before-swamp-native-20260520-180230.dll` was loaded by BepInEx as a second plugin, and its older Swamp proof still aliased tileCode `8` to Autumn's packed material slot. Pink Autumn ground in that run was therefore stale plugin loading, not evidence that the constructor-prefix material registration failed.
- Custom biome Core rows must also include biome-keyed sound rows. `Player.log` showed `[SessionWorld] Can't find map music sounds config for biome: Swamp` until `DB/map_music_sounds.json` and `DB/map_ambient_sounds.json` entries were cloned for `Swamp` from the presentation donor. Missing sound rows are a Core data gap, not a runtime hook problem, and the generator should own them for every custom biome.
- Runtime terrain registration is now data-shaped. Use `homm3CustomBiomeRegistration=true` for new terrain proof work and define rows in `OfflineUnlockMod/homm3_runtime_assets/custom_biomes/custom_biomes.json`; the old `homm3SwampAutumnTintProof` key remains a compatibility alias for the copy install. Do not add another hard-coded terrain hook for `Highlands`, `Rough`, or another faction terrain: add a definition row with the custom `tileCode`, material donor, sound donor tile code, texture sidecars, and optional marker donor, then let the shared renderer/sound registration fail loudly if another native tile-code-indexed consumer is missing.
- The May 21 custom-biome pack assigns faction-owned terrain lanes as follows: Tower `Tundra` cloned from Snow, Rampart `Hills` cloned from Grass, Stronghold `Wasteland` cloned from Sand with a tanner palette, Cove `Tropical` cloned from Sand, Conflux `Greenlands` cloned from Grass with a more vibrant palette, Necropolis `Curselands` cloned from Deathland with a greyer palette, Dungeon `Burrow` cloned from Dirt with a darker palette, Castle `Valleys` cloned from Grass, Inferno `Molten` cloned from Lava, Fortress remains `Swamp`, Factory `Foundry` cloned from Sand (tile 29), and Bulwark `Permafrost` cloned from Snow (tile 30). Tile ids `24..28` remain retired display-water Sand aliases and must not be reused. Generate sidecar/runtime definitions with `tools/release_port/build_custom_biome_assets.py`, then generate the copy-install Core artifact with `tools/release_port/apply_custom_biome_pack.py`; do not hand-edit only one side of this pair.
- The custom-biome pack is now part of the main release overlay path: `tools/release_port/apply_release_core_overlay.py` applies `tools/release_port/apply_custom_biome_pack.py` to the candidate `Core.zip` before validation/replacement. `tools/validate_custom_faction_manifests.py --core` must fail if any custom biome is missing from `DB/map/tiles`, `DB/map/waters`, `generator_config.waterForBiome`, `generator_environment_assets`, `DB/biomes_info.json`, or the faction row. Keep runtime `homm3CustomBiomeRegistration=true`; disabling it while Core uses custom tile ids `8..17` / `23` / `29..30` reproduces the map-load failure.
- Later Deathland-looking terrain came with a decisive proof log: `SoTerrainMaterial.instance` was extended, but the renderer lookup still showed `bseu[native,count=7,5->3,8->missing]`. The wrapper constructor patch was therefore not early enough for the existing `beg` renderer. An intermediate proof tried stale `beg.jmr(Map,bool,bool)` / `beg.kvs(Map)` names and old `kvu`/`kvq`/`kvr` material rebuild assumptions; do not copy that route. Current Steam support registers each custom tile code to its own biome index, rejects donor aliases, and uses only the constructor-used packed-material refresh path (`beg.nac()` / `beg.ivz()` / `beg.kwe()`) for non-alias custom textures. Treat this as runtime registration debt until the serialized `TerrainMaterials` resource can own the custom entries natively.
- Clone a known-safe donor faction's squads, unit views, heroes, and towns.
- Verify `DB/squads/squads_<faction>/**` exists in the target archive before runtime testing. A custom faction can be selectable and still fail during map/session startup if the squad tree is missing.
- Merge faction Lang rows through the overlay script. Custom HoMM3 rows must not stop at `Lang/english/texts/*.json`: run or rely on `tools/release_port/sync_multilingual_custom_lang.py` / `sync_multilingual_custom_lang_rows()` so all supported `Lang/<language>/texts/*.json` members receive the custom rows, existing localized rows are preserved, and `{0}` placeholders stay aligned with English.
- Add the faction to release selection surfaces and arena pick content.
- Normalize cloned hero configs after donor remapping: icon keys, localized name keys, native biome, class/skill-table split, start faction skill, and roll-table faction skill entries.
- Add the faction's unique top-level faction skill row before pointing hero start skills or skill tables at it. Do not leave cloned heroes on the donor `skill_faction_*`.
- Do not shallow-clone donor faction skill internals. Nested `subSkills` ids are global, and sharing ids such as `sub_skill_faction_humans_1` across two faction skills aborts session load after map generation. Also do not make a custom faction skill cumulative by repeating the same subskill id in multiple ranks; use distinct ids for each rank.
- Before defining `_upg_alt` units, run `python tools\extract_tears_of_ashan_creature_specs.py` and use `docs/homm3_tears_of_ashan_creature_specs.md` as the canonical Tears of Ashan stats/ability target.
- Treat VCMI ability keys as source identifiers, not OE implementation names. Preserve behavior first, then map it to OE-native data or a statically traced hook.
- Convert percentage-based HoMM3, HotA, and Tears of Ashan on-hit/on-attack effects into guaranteed focus-point-costing active abilities for Olden Era. Keep source targeting, duration, immunity/resist lists, and effect strength explicit; do not represent those mechanics as hidden RNG passives.

### 2. Native-Safe Release Unit Views

- Pick a donor faction whose native prefabs are stable in Steam release.
- Keep release `mesh` and `mapMesh` fields pointed at donor prefab paths.
- Store HoMM3 visual identity in `homm3_import.json` and asset bundles.
- Verify every new unit SID has a donor-safe `*_v.json`.
- Treat preview/combat null refs as a likely UnitView donor-path failure before changing battle visuals.

### 3. Visual Import Assets

- Ensure `homm3_import.json` contains `gameUnitSids` for every faction unit.
- Ensure matching `custom_units_h3_*` / faction-specific bundles exist under the deployed bundle folder.
- If a VCMI mod ships creature frames as JSON `images[]` plus PNG folders, convert that JSON into defextract-style `sequences[]` in `extracted_battle` / `extracted_map` before running the Unity builder. Validators should detect idle group 2 from the manifest, not only `02_*.png` names.
- Distinct alternate upgrades require distinct `homm3_import.json` lab SIDs and bundles. Do not satisfy `_upg_alt` by reusing the normal `_upg` bundle unless the manifest says the visuals are intentionally identical.
- Generate static unit portraits.
- Generate or verify bundle-backed preview/recruitment idle clips.
- Deploy `homm3_portraits`, bundle-backed recruitment idles, `homm3_bundles`, `homm3_runtime_assets`, `homm3_town_prefabs`, and updated manifests together.
- The old Fortress deploy helper is retired; use the project deploy target after Core data generation and validate with `tools\validate_custom_faction_manifests.py --plugin-root ...`, so do not bypass it by copying only bundles.
- Recruitment card portraits can use a separate city UI path from tooltip/army-strip portraits. Add faction-specific index fallback SIDs for the city recruitment panel; Stronghold-only gates will leave later factions blank.

### 4. Hero Portraits

- Identify the canonical HoMM3 portrait source list.
- Decode using the actual source payload format, not file extension assumptions.
- Check at least one generated portrait visually before deployment.
- Add fallback/reuse mappings explicitly when a faction has fewer source portraits than Olden Era needs.

### 5. Town Screen

- Confirm the source backdrop is the actual town scene, not a UI/building plate.
- Determine the source coordinate basis before scaling.
- Match Stronghold's runtime convention unless the town-layer renderer is intentionally changed.
- Generate a full mockup background and transparent building layers.
- Include level/variant aliases that the runtime lookup requests.
- Validate composited layers over the backdrop before shipping.
- Generate building animation frames and metadata separately from static layers.
- Stronghold's working contract is `homm3_runtime_assets/town_scene_refs/<faction>/layers/anims/metadata.json` plus one folder per animation key such as `extraCapitol_1`.
- Runtime attachment happens in `Homm3StrongholdTownAnimPlayer.TryAttach(image, fraction, layerId, building.level)`, using keys built as `<layerId>_<level>`.
- For Tower, `tools/build_homm3_tower_town_scene_assets.py` writes the compatible `layers/anims/` payload. Keep animation key names synchronized with `Homm3StrongholdTownLayers.TowerBuildingLayerIds` and live building levels.
- Tower regular town layers now use the proven Steam Runtime Copy extraction contract: original HoMM3 `TBTW*.def` layer IDs and explicit VCMI `config/factions/tower.json` top-left coordinates. Do not replace this with generic layer IDs or all-zero positions. The known-good reference path was `V:\Games\Olden Era Steam Runtime Copy\BepInEx\plugins\OfflineUnlockMod\homm3_runtime_assets\town_scene_refs\homm3_tower\layers`.
- Fortress town layers must follow local VCMI named structures too. Use `vcmi/Mods/third-upgrades/content/config/town-screen/fortress/factions.json` as the placement source; do not ship third-upgrade-only placement under the stale assumption that base Fortress coordinates are unavailable.
- Cove town layers must follow HotA named structures too. Use `vcmi/Mods/hota/mods/cove/Content/config/hota/cove/town/structures.json` for layer placement and `sprites/hota/cove/town/townhall.json` frame ids for build-tree icons; do not invent generic/all-zero positions, flatten `hallSlots` as icon indices, or reuse Human donor hall icons.
- Tower current-SID aliases must be handled deliberately. `Build_Bank` is the Tower Capitol visual (`tbtwhall_4`), `Build_Treasury` is the Tower Blacksmith visual (`tbtwblak`), and `Build_Resource_Depot_level_2` is Wall of Knowledge (`tbtwext2`) because the current Tower city JSON still carries Human-donor economy SIDs. Do not “fix” these by visual guessing; either keep the alias documented or normalize the city schema/text.
- Building tree icons are data keys first and PNGs second. Rewrite city `icons` arrays to faction custom keys such as `homm3_tower_building_<BuildSid>_level_<N>`, then teach `Homm3StrongholdBuildingIconSpriteCache` where those keys live. Text-token icon rows like `Homm3Tower_Build_*` or donor `H_build_*` will not resolve through the custom sprite fallback.
- Building hover icons can be overwritten after initial bind. Patch `BhBuildingView` hover/selection methods such as `OnPointerEnter`, `OnPointerExit`, `tov`, `tow`, `tox`, `toy`, and `tpv`-`tpy` with the same building-icon fallback used for `tot`/`UpdateView`/`tpb`-`tpr`.
- When normalizing building `icons`, match the maximum length of `icons`, `names`, and `descriptions`; otherwise final levels such as Tower Mage Guild 5 can keep valid text but have no icon key.
- Do not use town-screen layer crops as generic build-tree icon fallbacks. Tower exposed this badly: unknown non-dwelling `Build_*` keys all mapped to the same capitol or horde layer and made most buttons look identical. Extract the faction hall/icon DEF when available, keep it under `homm3_runtime_assets/town_scene_refs/<faction>/building_icons/`, and map every non-dwelling building SID explicitly.
- Build-tree icon source maps use HoMM3/VCMI building frame IDs, not flattened `hallSlots` positions. The shared contract is mage guild `0..4`, tavern `5`, shipyard `6`, fort/citadel/castle `7..9`, village/town/city/capitol halls `10..13`, market/silo/blacksmith `14..16`, specials/hordes `17..26`, base dwellings `30..36`, upgraded dwellings `37..43`, and third upgrades `44..50`. For Tower, `homm3_runtime_assets/town_scene_refs/homm3_tower/building_icons/althalltowr_source_map.json` is the build-tree icon source of truth; for Cove, `homm3_runtime_assets/town_scene_refs/homm3_cove/building_icons/townhall_source_map.json` must stay aligned with HotA `townhall.json`, including its reused `dwellingUp2Lvl3` frame `46`.

### 6. Map Billboards

- Add city billboard art and hook registration.
- Use the full castle/capitol adventure-map DEF for faction town billboards when the source set has both village/non-castle and completed-castle variants. For Tower, the desired map billboard is HoTA `tower/adventureMap/town/capitol.def`, not base `avctowr0`.
- Add external dwelling billboard art.
- Register direct external dwelling map objects in `DB/map/objects/4_interactables.json`, not only hire logic rows in `DB/objects_logic/hires/barracks.json`.
- If donor map objects are reused, gate aliasing on the exact live hire payload or saved original custom SID, not on seeing a custom faction town first.
- External dwelling billboards are not data-only. Stronghold and Tower can receive generated-map donor barracks, but donor barracks such as `barracks_human_*`, `barracks_dungeon_*`, and `barracks_nature_*` must resolve from the exact hire payload to one custom dwelling SID. Do not infer Tower, Fortress, or any other faction from city-seen state alone.
- Rewrite reflected object config SID/id values only when doing so cannot collide with direct custom map-object rows. If both donor aliases and direct custom ids are present, shared config mutation can poison the next map load.
- Keep map-object arrays deduped by `id`; `Hex.Map.MapObjects.Init` builds a dictionary and duplicate ids abort map generation before rendering.
- Watch for `.dir` vs `.dlv` suffix corruption after obfuscation rename passes; extracted DEF frame folders use `.dir`.
- Adventure-map unit stack billboards are a separate shared path from town/dwelling objects. They must flow through the centralized `UnitViewConfig` map loader symbol, `homm3_import.json` `gameUnitSids`, `swapAdventureMap`, donor map-shell paths, and the custom map prefab/bundle row. The runtime postconditions should be identical for every manifest unit SID: the selected import entry matches the custom SID, the native donor prefab is only a shell, donor renderers are hidden, a custom `homm3_map_visual/quad` exists and is enabled, the material uses a non-donor HoMM3 texture, and required `homm3_lab/<labSid>/extracted_battle` sidecar frames are present.
- If one custom faction's map unit stack renders and another's does not, treat that as a shared-contract or payload-validation failure. Do not add faction-specific map-unit branches to repair Tower/Fortress/Stronghold divergence. First check the live generated `BepInEx/interop/Hex.dll` loader symbol, then manifest/import rows, deployed bundles, deployed lab sidecars, and shared billboard postconditions.

### 7. Faction UI

- Release faction presentation must be fail-closed. `Homm3CustomFactionRegistry` owns which factions are presentation-enabled, and `ReleaseCustomGameUiProbe` should inject only those factions into Custom Game / Quick Play. Do not treat a registry entry or Core scaffold as permission to show a faction; disabled or missing-art `homm3_*` factions must not fall back to Stronghold card/backdrop visuals.
- Patch both lobby and Quick Play faction selector paths.
- Avoid writing shared Quick Play background state without restore/clear logic.
- Patch unit row portraits separately from faction details panels.
- Use text setter methods expected by the UI component.
- Recruitment and upgrade panels can be active but hidden behind the custom town backdrop if their canvases stay below the backdrop sort order. Stronghold's release fix is to force the active `BhScreen` canvas and panel canvas visible at `sortingOrder=140`; apply the same lift to later faction hire/upgrade screens before chasing missing data.
- The full recruitment window is not the same UI surface as the small town recruitment strip. The strip is `BhCitySpecialView.items/itemsLow4/itemsLow3` containing `BhCityHireIncrementItemView`; the full window is `BhHireCityView.items` containing `BhHireUnitItemView` cards. If the town strip works but the recruitment window is blank, patch `BhHireCityView.giq/Init` post-show and reapply card portraits through the native full `items` list. Do not force-activate child UI templates under the hire screen; that brings inactive placeholder cards forward and can break nearby town subwindows.
- If HoMM3 unit previews show donor meshes behind custom/imported previews, check the preview replacement hook before changing donor UnitView mappings. The donor root must remain alive for `BhUnitPreviews` pooling, but its renderers should be disabled before assigning the custom replacement.
- Do not leave release-visible unit views advertising donor abilities/passives. Normalize `DB/units/units_views/<faction>/*_v.json` alongside logic rows, and point names/descriptions at faction-local localization keys so previews explain real baseline mechanics and known static-trace debts.
- Preview donor meshes can live outside the wrapper's `Model` field. Tower still showed Human/Dungeon meshes until `Homm3ImportUnitPreviewModelHook` disabled renderers under `Model`, `Rotatable`, and the reflected wrapper component root while keeping the pooled wrapper alive.
- GameHub lobby dropdown rows need their own text repair. Fixing the selected faction asset/card is not enough; patch `BhLobbyPopupFractionElement` after bind/hover and rewrite row TMP/Text labels through the faction-aware path, or a custom faction can show the donor label such as `Temple` until selected.
- Custom Game faction art has two separate sprites: the small/banner icon must come from `homm3_runtime_assets/faction_icons/<faction>/`, while lobby cards/backgrounds should use a real town/background card image. Reusing a town-screen mockup as the faction icon or using a black-padded/cropped mockup as the card makes Tower look wrong even when faction injection works.
- For Fortress, the deployed release paths are `homm3_runtime_assets/faction_icons/homm3_fortress/Icon_Faction_Fortress.png` and `homm3_runtime_assets/town_scene_refs/homm3_fortress/Fortress-in-background.png`; both are resolved through `Homm3StrongholdFactionBannerSpriteCache`.
- Fortress town assets are generated by `tools/build_homm3_fortress_town_scene_assets.py`. The checked-in local VCMI data has authoritative Fortress placement rows at `vcmi/Mods/third-upgrades/content/config/town-screen/fortress/factions.json` plus the hall icon DEF. The generator and validator should use those named structures; do not preserve stale "base placement missing" guidance, generic/all-zero placement, third-upgrade-only maps, or Stronghold-layer fallbacks.
- Fortress town/build-tree validation is now part of `tools/validate_custom_faction_manifests.py`. The Fortress manifest must point at `assets.townSceneFolder` and `assets.buildingIconFolder`; the validator checks `positions.json`, `building_layer_map.json`, `_1` layer aliases, and the `hallfortalt_source_map.json` frame references. Missing base Fortress coordinates are still a blocker to full base-town parity, not permission to reuse Stronghold layers or donor-only lookups.
- Alternate/Tears upgrade units must be supported in both Core data and UI. If standard upgraded rows do not set `upgradeSid` to their `_upg_alt` row, the alternate units can exist in city hire lists but remain absent from normal upgrade flows. If previews show extra inert upgrade buttons, fix the preview UI path instead of severing the data chain.
- Do not patch `CityHireView.uab/uac` as a recruitment-opening fallback. In the release build those shell methods can run before a valid city hire view exists and will loop `Il2CppInterop` native-trampoline `NullReferenceException` errors at menu/loading time. Keep hire visibility fixes on `BhHireCityView.giq/Init` or trace the click path from `BhCitySpecialView`/`BhCityHireIncrementItemView` more narrowly.
- Minimum viable custom-faction ability coverage is generated in `tools/release_port/apply_release_core_overlay.py`. Exact/simple rows should go through the strong-vanilla mechanic maps first; unresolved HoMM3 mechanics may use explicit MVP donor actives such as Blind, Stunning Blow, Thunderbolt, Blessing, Repair, Animate Dead, Curse, or mana transfer only when the generated `xHomm3ProductionDebt.implementedMechanics` text makes the proxy status obvious. Do not hide unfinished mechanics behind silent donor leftovers or unlabelled fallbacks.
- Minimum viable custom-faction skill coverage means the unique hero/faction skill rows, not creature active abilities. Keep custom faction skill rows under `skill_faction_homm3_*`, avoid donor `subSkills` unless the full graph is cloned with unique ids, and label any donor-inspired baseline such as Cove Cannoneering, Inferno Gating, Conflux Summon Elementals, or Necropolis Necromancy with explicit `xHomm3ImplementedMechanics` / `xHomm3MechanicsDebt` text.

### 8. Steam Apply And Deployment

- Build the plugin against the Steam game root.
- Apply release Core overlay script to Steam `Core.zip`.
- Do not use `tools/apply_homm3_tower_overlay.py` as the Steam release path. It is historical/local Tower tooling; Steam release work should use `tools/release_port/apply_release_core_overlay.py` so Tower stays on the shared manifest path and archive-local Lang merge discipline.
- Copy plugin DLL/PDB to the Steam BepInEx plugin folder.
- Copy all newly generated asset directories to the Steam plugin folder.
- Verify archive contents and deployed asset presence with a scriptable check.
- Do not treat `Core.zip` as evidence that visual deployment is complete. For custom factions, verify the plugin payload in the Steam install as well as the archive data.
- Keep a Core backup created by the apply script.

### 9. Diagnostics And Runtime Probes

- Keep all probes config-gated and capped; a useful trace can still become a hot-path stall during turn passing or battle setup.
- Do not use Harmony `AccessTools.TypeByName` / `AccessTools.Field` for repeated known IL2CPP wrapper member reads inside attack, counter, map-turn, or UI refresh paths.
- Prefer direct `typeof(...)` plus cached `Type.GetField` / `Type.GetProperty` lookup helpers for known generated wrapper types.
- If logs spam `LightProbesQueryDisposeJob`, `<>c`, `AccessTools.GetTypesFromAssembly`, and `AccessTools.Field: Could not find field ...`, trace the nearest plugin log line. This can be Harmony broad assembly enumeration caused by a missing-field probe, not a game asset or Unity light-probe failure.

## Validation Commands Used For Tower

```powershell
python tools\extract_homm3_hero_portraits.py
python tools\generate_homm3_interface_portraits.py
python tools\build_homm3_tower_town_scene_assets.py
python tools\validate_custom_faction_manifests.py --plugin-root "Heroes of Might & Magic Olden Era Playtest\OfflineUnlockMod"
dotnet build -c Release "-p:GameRoot=V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era" -clp:ErrorsOnly
python tools\release_port\apply_release_core_overlay.py --release-core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip"
python tools\validate_custom_faction_manifests.py --core "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\HeroesOldenEra_Data\StreamingAssets\Core.zip" --plugin-root "V:\SteamLibrary\steamapps\common\Heroes of Might and Magic Olden Era - Golden Era\BepInEx\plugins\OfflineUnlockMod"
```

## Tower-Specific Warnings

- Wrong town backdrop: Tower must use `tbtwback.pcx`, not `TowerHallBg.png`.
- Wrong native terrain: Tower must be the custom `Tundra` biome, cloned from Snow presentation.
- Missing recruitment card portraits: check `Homm3CustomUiIconHook` current-city gates and faction-specific recruitment fallback arrays before changing portrait assets.
- Recruitment window does not open or opens blank: do not assume missing hire rows if `homm3_tower_city.json`, `DB/objects_logic/hires/barracks.json`, and `DB/map/objects/4_interactables.json` are populated. Trace the full hire screen path: live Steam `BhHireCityView` exposes `items` and `dayPanel`, while `BhHireUnitItemView` binds through `Init(HireArgs,int,BhUnitPreview)`, `tsk(HireArgs,int)`, `UpdateView(string)`, `tsp`, and `tsv`.
- Combat does not load with Tower units: inspect Steam `Core.zip` UnitView rows before changing combat hooks. Release `DB/units/units_views/homm3_tower/*_v.json` must keep donor `Humans/1Prefabs/*` mesh/mapMesh fields; direct `homm3_import/tower/*` fields can abort native combat/previews before replacement hooks run.
- Missing Tower building tree icons: confirm `homm3_tower_city.json` uses `homm3_tower_building_*` icon keys and that `Homm3StrongholdBuildingIconSpriteCache` can resolve every `Build_*` SID, including special buildings and Mage Guild 5.
- Mixed-up Tower building tree icons: check `althalltowr_source_map.json` and VCMI `hallSlots` order before changing individual frame numbers. The frame order is not reliable by visual guessing.
- Mixed-up Tower town buildings: check `building_layer_map.json` first. Normal level 1/2 buildings should map to original DEF-name layer IDs such as `tbtwdw_0`, `tbtwhall`, `tbtwcstl`, `tbtwmage`, `tbtwext1`, and `tbtwholy`; the `dwellingUp2Lvl*` layers are third-upgrade assets and should not drive normal dwellings.
- Tower building assignment review artifact: `homm3_runtime_assets/town_scene_refs/homm3_tower/tower_building_mapping_collage.png` shows the current Olden Era SID -> Tower DEF layer crosswalk. Regenerate or update that collage whenever `building_layer_map.json` changes.
- Missing Tower hero names/portraits: cloned Human heroes can retain `hero_homm3_tower_<N>_ister`, `nativeBiome=Grass`/`Snow`, and `skill_faction_humans` unless the overlay script normalizes them to Tower keys and `nativeBiome=Tundra`.
- Missing external Tower dwellings: confirm both `DB/map/objects/4_interactables.json` and `DB/objects_logic/hires/barracks.json` contain `barracks_homm3_tower_1..7`, then check `Homm3StrongholdDwellingMapBillboard` exact-payload donor routing. Random-hire map objects may arrive as Human or Dungeon barracks, but Tower art should apply only when their live hire payload resolves to one Tower dwelling SID.
- External dwelling audit difference: Stronghold direct rows and Tower direct rows are structurally the same in `Core.zip`, but Tower has an extra Human-donor alias path because its faction/city scaffolding began as Human. If direct rows exist and still show no billboards, suspect runtime hook/marker/context behavior before changing Core data.
- Map does not load with `same key ... barracks_homm3_tower_1`: check whether a runtime alias rewrote a donor `ObjectConfig.id` to a direct Tower id. Static `Core.zip` can be clean while the live process is poisoned by shared config mutation; restart after deploying the fixed hook.
- Tower unique faction skill: `skill_faction_homm3_tower` is Arcane Battery. Ranks grant `skill_faction_homm3_tower_ability_arcane_battery` (2/1/0 Focus, once per round) with native `refresh_spell_book` only — per-spell cooldowns are intentionally not cleared. Scholar subskills must stay under `sub_skill_faction_homm3_tower_arcane_battery_*` with unique ids across rank lists. `Mana Well Aegis` is handled by `Homm3TowerBottomlessKnowledgeHook` after `ManaPercentSettingReward`, scoped to explicit negative dispellable hero-map curse buffs. Do not restore Bottomless Knowledge morning mana ranks or stale non-`arcane_battery_` scholar SIDs. Stale Tower skill localization must be pruned by exact Tower token SID from every `Lang/*.json` member, because duplicate `skill_faction_homm3_tower_name` rows in unrelated text buckets can override the clean `heroSkills.json` row at runtime.
- Map generation completes but loading aborts with `same key ... sub_skill_faction_humans_1` or another `sub_skill_*`: check that the custom faction skill row does not still reference donor `subSkills`, and that it does not repeat its own subskill ids across multiple ranks. For placeholder skills, strip `bonuses` and `subSkills`; for real faction mechanics, clone the complete skill graph with unique ids.
- Passing turns or entering battle freezes while logs spam `LightProbesQueryDisposeJob`, `<>c`, `AccessTools.GetTypesFromAssembly`, and `AccessTools.Field: Could not find field for type cke and name bxpr`: check config-gated diagnostics first. `Homm3BattleAttackCommandProbe` must not call Harmony `AccessTools` for stale `cke.bxpi..bxpr` static tag fields on hot paths; use direct cached reflection and keep the probe capped.
- Main-menu or loading logs loop `During invoking native->managed trampoline` with `DMD<Hex.UI.City.CityHireView::uab>`: remove broad `CityHireView.uab/uac` patches. Those methods are not safe as generic recruitment-open hooks.
- Combat/previews crashing or freezing early: check release UnitView `mesh/mapMesh` donor fields first.
- Blank previews: check `homm3_portraits/h3_*.png` plus bundle-backed recruitment idle deployment first.
- Hero portrait confetti: rerun the custom payload decoder, not generic PCX decoding.
- Misaligned town buildings: check 800x374-to-1440x673 scaling and transparent layer generation.
- Missing town layer variants: check `_1.png` aliases.
- Missing town building animations: check for `homm3_runtime_assets/town_scene_refs/homm3_tower/layers/anims/metadata.json` and matching `<layerId>_<level>` frame folders. The Tower generator currently emits only the multi-frame DEFs present in the source set.
- Tower building animation ids can differ from corrected static layer ids. The placed layers use original HoMM3 ids such as `tbtwdw_0`, while current extracted animation metadata still uses older synthetic ids such as `dwellingUp2Lvl1_1`; keep `Homm3StrongholdTownAnimPlayer` aliases in sync until the generator emits metadata with the final layer ids.
- Missing external dwelling art: check Tower dwellings were force-added/deployed despite ignore rules.
- Missing Tower unit stack billboards on the adventure map: do not assume the Tower prefabs are bad if they work in battle and preview windows. The map-unit path can fail earlier if `Homm3ImportUnitViewHook` does not bind the live `UnitViewConfig` map GameObject loader, if `homm3_import.json` rows are not selected by `gameUnitSids`, or if the shared native-shell postconditions fail. Decompile/check the live generated `BepInEx/interop/Hex.dll` wrapper before trusting a stale native dump; update `GameSymbols.UnitViewConfig.MapMeshLoader` rather than adding a shape fallback.
- Tower adventure-map town billboard should use `homm3_runtime_assets/map_object_refs/homm3_tower_city/capitol.dir/00_00.png`, extracted from HoTA `capitol.def`, through the shared `Homm3CustomTownMapBillboard` path. The older `avctowr0.dir/00_00.png` and `avctowc0.dir/00_00.png` lanes are stale for release Tower; do not deploy `Homm3TowerDev`/`homm3TowerDev.flag` as a Tower billboard path.
- Tower build-tree icons use `homm3_runtime_assets/town_scene_refs/homm3_tower/building_icons/althalltowr.dir/` extracted from `AltHallTowr.def`. Do not fallback non-dwelling buildings to `extraCapitol` or `horde1Upgr2`; that makes the build tree look like repeated copies of the same building.
- Tower unit views must be normalized with `tools/quality_pass_homm3_tower_overlay.py`, not only unit logic rows. That script removes donor ability/passive rows from Tower previews, rewrites preview `defaultAttacks`/`alternativeAttacks` away from donor keys such as `minos_ability_*`, adds Tower/common localization keys, keeps standard-upgrade -> `_upg_alt` chains, and sources ToA alternate stats/names from `docs/homm3_tears_of_ashan_creature_specs.md`.

## Open Runtime Validation

The static/build/deployment validation completed for Tower, but the durable source of truth should record any additional runtime findings here as they are discovered.

- Battle launch and first upgraded Gremlin flow: pending current runtime verification.
- Tower town screen layer alignment in live UI: pending current runtime verification.
- Tower building animation frame extraction/metadata generation: implemented for current multi-frame sources; pending live UI verification.
- Tower adventure-map unit stack billboards: pending current runtime verification. If Tower units remain invisible while battle/previews work, audit `Homm3ImportUnitViewHook` registration and shared map-unit postconditions before changing Tower unit prefabs.
- Tower external dwelling tooltip localization in live map: pending current runtime verification.
- Quick Play and lobby faction selectors after final art replacement: pending current runtime verification.
