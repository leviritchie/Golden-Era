# Olden Era Playtest Agentic Knowledge Base

> Archived reference snapshot (2026-05-02). This file is not an operational
> source of truth and its "current" statements have not been reconciled with the
> present worktree. Use `../AGENTS.md`, `README.md`, and `agent_surface_guide.md`
> for navigation, then verify claims against current source, validators,
> generated artifacts, installed payloads, logs, or decomp evidence. The RAG
> chunks derived from this file have the same historical status.

Document version: 2026-05-02

Purpose: give coding agents one large, grep-friendly, RAG-friendly reference for this workspace. This is not official game documentation. It is a project-local synthesis from the checked-in mod code, existing investigation notes, generated scripts, configs, and observed runtime behavior.

Use this document only for historical search context. It is deliberately
redundant in places so individual chunks remain useful when retrieved out of
context, but retrieved claims still require current verification.

## RAG Chunk Map

Each section starts with a stable marker:

`RAG_CHUNK: olden-era-playtest/<topic>`

Recommended retrieval split points are those markers. Companion chunk files live under `docs/rag_chunks/` and duplicate the highest-signal parts of each topic for systems that prefer one file per chunk.

| Chunk id | Topic |
| --- | --- |
| `000-navigation` | How to use this document and where truth lives |
| `010-runtime-stack` | Unity IL2CPP, BepInEx, Harmony, interop, obfuscated names |
| `020-repo-map` | Workspace layout, source vs deployed plugin, data sources |
| `030-build-deploy` | Build, deploy, packaging, generated assets |
| `040-config` | Config merge model and important flags |
| `localization-args-oom` | LocKit startup OOM from oversized Lang args files |
| `050-plugin-load` | Plugin load order and patch registration model |
| `060-offline-session` | Offline unlock, quick start, configured new game |
| `070-core-data` | Core.zip JSON data model and custom faction requirements |
| `080-stronghold-data` | HoMM3 Stronghold faction, city, units, heroes, parity checker |
| `090-ability-mechanics` | Olden Era unit ability mechanics and Stronghold roadmap |
| `100-visual-lanes` | Esquire lane and HoMM3 import lane |
| `110-map-billboards-fog` | Native map billboard path, fog, material sanitization |
| `120-town-city` | Town backdrops, Stronghold layers, town music, map city billboard |
| `130-portraits-icons` | Unit portraits, hero portraits, sprite lookup pitfalls |
| `140-damage-histogram` | Damage forecast histogram and HoMM3 damage model |
| `150-retaliation-probes` | Retaliation fix, probes, safe diagnostics |
| `160-il2cpp-rebase` | Il2Cpp dump, Map.Init analysis, rebase checklist |
| `165-il2cpp-semantic-map` | Obfuscated IL2CPP semantic-name map and evidence workflow |
| `170-agent-workflow` | Safe agent workflow, warnings, validation |
| `180-status-matrix` | Current feature state summary |
| `homm3-faction-automation` | Automation/manual-work estimate for other HoMM3 factions |
| `homm3-first-pass-principles` | Stronghold-derived placeholder design principles for first AI passes |
| `homm3-faction-planning-docs` | Editable per-faction planning documents for non-Stronghold HoMM3 towns |
| `190-glossary` | Common symbols, SIDs, files, and obfuscated names |

---

## RAG_CHUNK: olden-era-playtest/000-navigation

## Navigation And Source Of Truth

This workspace is both a live game install and a mod source tree. Many files are generated, deployed, or extracted. Agents should identify whether a file is:

- source to edit,
- deployed runtime output,
- extracted reference data,
- temporary scratch output,
- or generated content inside `Core.zip`.

Primary source tree:

`Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`

Deployed plugin tree:

`Heroes of Might & Magic Olden Era Playtest/BepInEx/plugins/OfflineUnlockMod/`

Primary existing agent reference:

`docs/AGENT_REFERENCE.md`

This document is intended to become the high-level canonical map. When a narrow investigation has a dedicated note, keep both:

- update this document with the stable outcome and warnings;
- keep the narrow note for raw evidence, run logs, history, and failed attempts.

Important companion notes:

- `docs/AGENT_REFERENCE.md`: compact agent-searchable reference.
- `docs/stronghold_ability_mapping.md`: HoMM3 / Tears of Ashan ability mapping to Olden Era mechanics.
- `docs/stronghold_ability_implementation_findings.md`: what ability work is data-only vs C# required.
- `docs/homm3_stronghold_hero_portrait_findings.md`: hero portrait state and central sprite resolver recommendation.
- `docs/homm3_stronghold_stat_power_alignment.md`: raw stat tier alignment for Stronghold units.
- `docs/homm3_stronghold_squad_value_audit.md`: static squad-value and squad-template audit for Stronghold auto-battle balance.
- `docs/il2cpp-map-generate-trace.md`: native `Map.Init` / `buz` / `buf` / `bwe` disassembly notes.
- `docs/il2cpp-semantic-map.md`: working semantic map for obfuscated battle/UI symbols, confidence levels, evidence, and Warcries controller diagnostics.
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/HOMM3_NATIVE_BILLBOARD_PIPELINE.md`: current best map billboard path.
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/HOMM3_MAP_FOG_NOTES.md`: chronological map fog experiments and rollbacks.
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/CUSTOM_FACTION_UI_ASSET_LEARNINGS.md`: custom faction UI binding root cause.
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/AGENT_REBUILD_AND_MAINTENANCE.md`: damage histogram-focused maintainer guide.

When updating documentation:

- Prefer ASCII in new docs unless the file already uses non-ASCII intentionally.
- Add stable grep tokens such as file names, class names, config keys, SIDs, and runtime log fragments.
- Record negative findings. In this repo, failed attempts are often as valuable as successful patches because IL2CPP/Unity failures can be expensive to rediscover.
- Map incidental IL2CPP discoveries in `docs/il2cpp-semantic-map.md`: method roles, field meanings, pointer chains, native dictionaries, donor/custom divergences, and rejected interpretations. If the evidence is only a hunch, record it as Tentative or leave a brief note in the relevant topic doc instead of promoting it.
- Do not erase old warnings unless a later verified runtime test invalidates them.

---

## RAG_CHUNK: olden-era-playtest/010-runtime-stack

## Runtime Stack: Unity IL2CPP, BepInEx, Harmony, Interop

Olden Era is a Unity IL2CPP game. The mod is a BepInEx 6 IL2CPP plugin written in C# and compiled to `netstandard2.1`.

Installed loader version, verified from `BepInEx/LogOutput.log` and `BepInEx/core/*.dll` assembly metadata on May 4, 2026: **BepInEx 6.0.0-be.755**, built from commit `3fab71a1914132a1ce3a545caf3192da603f2258`. The log also reports .NET runtime **6.0.7**.

Core runtime layers:

- Unity player executable and `GameAssembly.dll`.
- IL2CPP metadata at `HeroesOE_Data/il2cpp_data/Metadata/global-metadata.dat`.
- BepInEx 6 IL2CPP loader under `BepInEx/`.
- Generated interop assemblies under `BepInEx/interop/`, especially `Hex.dll` and `Hex.Shared.dll`.
- Harmony patches applied from `OfflineUnlockMod.dll`.
- JSON game data in `Core.zip`, especially `DB/**` and localization files.

The mod relies on generated interop names. Some names are readable, such as:

- `Hex.Session.Battle.DamageUiParams`
- `Hex.Session.Battle.BhHealDamageForecastPanel`
- `Hex.Session.Loader`
- `Hex.Configs.ObjCityConfig`

Other names are obfuscated and unstable across game builds, such as:

- `ejz.bdwu()` and `ejz.oez()` for damage forecast helpers.
- `ejy` for a damage forecast DTO.
- `dzk.bath` for battle unit pool / prefab creation.
- `buv` and `but` for map-object metadata/object lifecycle.
- `fvh`, `fvf`, `fvj` for sound registry/group lookup code used by Stronghold city music.
- `czk.uvl`, `cmc.sni`, `BhHUDSession.ira` in HUD/session binding failure stacks.

Agent rule: never assume short obfuscated names are stable. After a game update, regenerate or inspect interop and re-anchor patches by signature, call site, stack trace, or string evidence.

Harmony patch model:

- Most normal patches are auto-discovered by `Plugin.PatchAnnotatedTypes()`, which scans the plugin assembly for `[HarmonyPatch]`.
- Types marked with `[ProbePatch]` are excluded from normal patching and patched only when retaliation debugging is enabled.
- Some patches use manual registration because the target is dynamic, obfuscated, or optional. Examples include `Homm3ImportVisuals.TryRegister`, `Homm3StrongholdTownMapBillboard.TryRegister`, `Homm3HeroPortraitHook.TryRegister`, `Homm3StrongholdCityMusic.TryRegister`, and `SoFractionsCustomFactionAliasPatch`.

Interop safety:

- IL2CPP objects can crash the process if reflected too broadly.
- Avoid recursive property scans across arbitrary Unity objects.
- Avoid generic `GetComponents<T>` loops from injected IL2CPP `MonoBehaviour` code unless tested. A prior runtime squad attach experiment caused IL2CPP trampoline failures around `MethodInfoStoreGeneric_GetComponents_Public_Il2CppArrayBase_1_T_0`.
- Prefer explicit known fields and narrow lifecycle patches over broad hierarchy scans.

---

## RAG_CHUNK: olden-era-playtest/020-repo-map

## Workspace And Directory Map

Top-level workspace:

`v:/Games/Olden Era Playtest Tweak/`

Important directories:

- `Heroes of Might & Magic Olden Era Playtest/`: live Olden Era playtest install and mod source.
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/`: C# source, generators, docs, reference pack.
- `Heroes of Might & Magic Olden Era Playtest/BepInEx/plugins/OfflineUnlockMod/`: deployed plugin runtime folder.
- `Heroes of Might & Magic Olden Era Playtest/BepInEx/interop/`: generated IL2CPP interop assemblies.
- `Heroes of Might & Magic Olden Era Playtest/tools/`: IL2CPP dump and audit tools.
- `HoMM 3 Complete/`: GOG HoMM3 Complete / HotA data source.
- `vcmi/`: VCMI install and reference data.
- `tools/`: repo-level extraction, conversion, portrait, DEF/LOD, and playtest scripts.
- `oldenera_factions/`: Unity/custom unit lab asset worktree used by import/bundle pipelines.
- `docs/`: agent/reference docs and investigation notes.

Source vs deployed:

- Source C# files are in `OfflineUnlockMod/`.
- Built DLL deploys to `BepInEx/plugins/OfflineUnlockMod/OfflineUnlockMod.dll`.
- Source `homm3_import.json` is in `OfflineUnlockMod/`.
- Runtime `homm3_import.json` is expected under the deployed plugin folder.
- Source `homm3_portraits/` deploys to plugin `homm3_portraits/`.
- Source `homm3_hero_portraits/` and `homm3_hero_map_sprites/` deploy to matching plugin folders for Stronghold hero UI portraits and adventure-map hero billboards.
- `homm3_runtime_assets/` source deploys to plugin `homm3_runtime_assets/`.
- `Core.zip` is game data, not normal source. Generators patch it directly and create backups.

Common file roles:

- `Plugin.cs`: BepInEx entry point, offline unlock, menu/session actions, city backdrop, UI alias patches.
- `LauncherConfig.cs`: merged config model and JSON parsing.
- `OfflineUnlockMod.csproj`: build references and deploy copy target.
- `EsquirePikemanVisuals.cs`: Esquire replacement lane, shared map material sanitization helpers.
- `Homm3ImportVisuals.cs`: HoMM3 import manifest loading, bundle loading, map shell/billboard construction.
- `ResManagerGameObjectLaneHooks.cs`: ResManager replacement lane used by visual systems.
- `Homm3ImportBattlePoolHook.cs`: HoMM3 battle prefab injection.
- `Homm3ImportUnitViewHook.cs`: HoMM3 adventure map view hook.
- `Homm3StrongholdTownMapBillboard.cs`: world-map city object billboard.
- `Homm3StrongholdTownLayers.cs`: city screen building layer overlay.
- `Homm3StrongholdCityMusic.cs`: routes Stronghold city music sound set.
- `DamageHistogramOverlay.cs`: forecast PMF capture and UI rendering.
- `DamageDistribution.cs`: HoMM3-style damage PMF.
- `RetaliationForecastFix.cs`: forecast panel hide debounce.
- `generate_homm3_stronghold_city.py`: patches `Core.zip` for Stronghold city/fraction/units/data.
- `generate_homm3_stronghold_heroes.py`: patches `Core.zip` for Stronghold heroes/subclasses/specializations.
- `verify_homm3_stronghold_core_parity.py`: read-only Core.zip parity checks.

---

## RAG_CHUNK: olden-era-playtest/030-build-deploy

## Build, Deploy, Packaging

Build from the mod source directory:

```powershell
cd "Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod"
dotnet build -c Release --nologo
```

The `.csproj` targets `netstandard2.1` and references BepInEx core, IL2CPP interop, `Hex`, `Hex.Shared`, `Hex.Sound.Runtime`, Newtonsoft, TextMeshPro, Unity modules, Harmony, and Il2CppInterop.

The `DeployPluginToGame` MSBuild target runs after build unless disabled:

```powershell
dotnet build -c Release -p:DeployPluginToGame=false
```

Use `DeployPluginToGame=false` when:

- the game is running and locks `OfflineUnlockMod.dll`;
- you only need compile validation;
- you are packaging and do not want to mutate the live plugin folder.

Deploy target currently copies:

- `OfflineUnlockMod.dll`
- `homm3_portraits/**`
- `histogram_icons/**`
- `homm3_runtime_assets/**`
- `custom_units_esquire` from `tools/custom_prefab_pipeline/build_out/`
- all `homm3_*_city_music` bundles from `tools/homm3_import/build_out/`

Important packaging distinction:

- Full local playtest work includes many custom features.
- Public histogram-only packaging should not ship unrelated local playtest systems.
- Existing `package_release.ps1` / `.sh` are documented as histogram-only packaging scripts in the maintainer note.

Generated content warning:

- `Core.zip` mutations are made by Python generators and should be reproducible from scripts.
- Runtime plugin folder content can be ahead of source. Do not treat deployed-only files as durable unless you add them to source/deploy.
- Hero map sprite assets must stay source-backed; if deployed `homm3_hero_map_sprites/` changes, copy the source folder too.

Safe build validation sequence:

1. Check `git status --short` before editing.
2. Build with `-p:DeployPluginToGame=false` first if you are touching compile-sensitive C#.
3. Build normally only when deployment is intended.
4. For runtime behavior, run the game and inspect `BepInEx/LogOutput.log`, Unity `Player.log`, and mod-specific logs.

---

## RAG_CHUNK: olden-era-playtest/040-config

## Configuration Model

Config class: `LauncherConfig` in `LauncherConfig.cs`.

Main config sources:

1. Game root `OfflineLauncherConfig.json`.
2. Canonical mod config `BepInEx/plugins/OfflineUnlockMod/config.json`.
3. Legacy fallbacks such as `mod_settings.json` and `offline_unlock_mod_config.json`.

Merge behavior:

- `LauncherConfigReader.TryLoad()` reads launcher/root config first.
- Mod config overrides only keys present in the second file.
- The parser is custom/regex-based rather than a full typed JSON serializer.
- `LauncherConfigReader.LoadGeneration` increments after load/invalidation and is used by UI caches.

Important config keys:

Session and UI:

- `matchMode`: `SinglePlayer` or `Hotseat`.
- `mapTemplate`: RMG template name, default `Jebus Outcast`.
- `difficultyIndex`: selected difficulty row index.
- `playerOneFaction`, `playerOneHero`, `playerTwoFaction`, `playerTwoHero`: explicit SID or `random`.
- `autoLaunchOnMenu`, `autoLaunchDelayMs`: menu auto-start.
- `skipIntroCinematics`, `skipIntroCinematicsBootRealtimeCapSec`: video skip behavior.
- `uiScalePercent`: 80-200 percent clamped in UI scale hooks.

Crash/workaround:

- `suppressBhAppStartTypeInitLoop`: suppresses an app-start init NRE loop.
- `suppressBhHudSessionIraNre`: suppresses custom faction HUD binding NRE after alias patching.

Esquire visual lane:

- `esquirePikemanVisuals`
- `esquirePikemanApplyHarmony`
- `esquirePikemanPrewarmBundle`
- `esquirePikemanDiagnostics`
- `esquirePikemanVerbose`
- `esquirePikemanDeferPatch`
- `esquirePikemanDeferBySceneLoad`
- `esquirePikemanDeferSceneLoadSkips`
- `esquirePikemanDeferPatchFrames`
- `esquirePikemanDeferResManagerOffsetFrames`
- `esquirePikemanSwapAdventureMap`
- `esquirePikemanMapBillboardMaterialMode`: `hexLitVanilla` is the important native-map mode.
- `esquirePikemanResManagerPostfix`: legacy; current Esquire hooks avoid broad ResManager mode.
- `esquirePikemanUnityErrorCorrelator`
- `esquirePikemanNarrowUiSpawnerHook`
- `esquireBattleSfxVolume`

Current live state as of 2026-05-03: `BepInEx/plugins/OfflineUnlockMod/config.json` sets `esquirePikemanVisuals=false` so vanilla Castle esquire/swordsman/pikeman visuals are not replaced by `custom_units_esquire`. Do not turn this back on while testing HoMM3 Stronghold unless the Esquire lane itself is under investigation. Stronghold visuals use `homm3ImportEnabled` / `homm3ImportApplyHarmony` and remain independent.

HoMM3 import:

- `homm3ImportEnabled`
- `homm3ImportApplyHarmony`
- `homm3ImportPreviewHooks`: preview hooks are fragile. If the right-side adventure HUD loses hero/town buttons after game/session initialization or after leaving city/recruitment UI, suspect shared `BhUnitPreviews`/`clb` cache mutation first. The safer preview path keeps this flag on for testing but avoids broad reflected `Homm3ImportClbPreviewFactoriesHook` registration.
- `homm3TooltipPortraitVanillaDungeonFallback`
- `homm3StrongholdTownMusicVolume`
- `strongholdAbilityPanelProbes`

Damage histogram:

- `damageHistograms`
- `damageHistogramConvolutionMaxUnits`
- `damageHistogramChartWidthPx`
- `damageHistogramChartHeightPx`
- `damageHistogramGapPx`
- `damageHistogramUseNativeFrameSprite`
- `damageHistogramPanelUgui`
- `damageHistogramPanelUguiLayoutPercent`
- `damageHistogramPanelUguiEdgeFeatherPx`
- `damageHistogramFontScalePercent`
- `damageHistogramMinBars`

Retaliation:

- `retaliationForecastFix`
- `retaliationForecastDebounceMs`

Agent warning: changing config can mask code defects. When bisecting runtime crashes, record the config snapshot printed by `Plugin.Load()`.

---

## RAG_CHUNK: olden-era-playtest/localization-args-oom

`HeroesOE_Data/StreamingAssets/Lang/args/unitsAbility.json` and `unitsBuff.json` are read by LocKit with `File.ReadAllText` during startup. If one becomes enormous, the game can log `System.OutOfMemoryException` in `bxe.pbh()` / `il..cctor()` while reading `Lang/args/unitsAbility.json`.

May 2026 finding:

- `args/unitsAbility.json` had grown to about 4.77 GB.
- `args/unitsBuff.json` had grown to about 1.57 GB.
- The game eventually continued, but startup stalled hard while LocKit tried to read the oversized files.

Root cause:

- `generate_homm3_stronghold_city.py` `propagate_base_args_to_upgrades()` matched every SID starting with a base custom unit id, including already-upgraded SIDs such as `h3_goblin_upg_*`.
- Repeated runs could then create nested upgrade tokens like `h3_goblin_upg_upg_*`, growing the args files rapidly.

Fix / recovery:

- `propagate_base_args_to_upgrades()` must only propagate true base-unit SIDs, excluding remainders beginning with `upg_` or `upg_alt_`.
- Restore clean args files from `tools/reference/assetripper_olden_demo_unity/ExportedProject/Assets/StreamingAssets/Lang/args/`.
- Rerun `python generate_homm3_stronghold_city.py --lang-only`.
- Healthy patched sizes are roughly `unitsAbility.json` 35 KB and `unitsBuff.json` 7 KB, with no `_upg_upg` or `_upg_alt_upg` SIDs.

---

## RAG_CHUNK: olden-era-playtest/050-plugin-load

## Plugin Load Order And Patch Registration

Entry point: `OfflineUnlockMod.Plugin`.

Plugin identity:

- GUID: `levir.heroesoe.offlineunlock`
- Name: `HeroesOE Offline Unlock`
- Version at time of this doc: `0.1.124`

High-level `Plugin.Load()` sequence:

1. Set global logger and initialize Harmony.
2. Run `LocKitDebugProbe.TryRun()`.
3. Load merged config through `LauncherConfigReader.TryLoad()`.
4. Register `ElangHjsNreWorkaround`.
5. Register `BhAppStartTypeInitLoopWorkaround`.
6. Log a structured config snapshot through `AgentDebugLog`.
7. Apply Esquire map billboard material mode from config.
8. If Esquire enabled, configure `EsquirePikemanVisuals`, optionally prewarm bundle, and register hooks.
9. Optionally run Esquire spawner reflection probe and narrow UI spawner hook.
10. If HoMM3 import enabled and Harmony enabled, register `Homm3ImportVisuals`, Stronghold city music, and optionally Stronghold ability probes / preview fine-tune hooks.
11. Register Stronghold town map billboard.
12. Register HoMM3 hero portrait hook.
13. Auto-patch normal `[HarmonyPatch]` types.
14. Patch city open/start for custom backdrop.
15. Ensure Grove backdrop adjuster and damage histogram bootstrap.
16. Log final load summary.
17. If retaliation debug enabled, patch `[ProbePatch]` classes with a separate Harmony instance.

Auto-patched normal classes include:

- menu unlock patches,
- early access / thank-you skip,
- demo overlay hiding,
- navigation button interception,
- UI scale patches,
- custom faction UI alias,
- HUD/session probes and NRE guard,
- damage histogram patches when prepared,
- retaliation fix when prepared,
- town layer sync patches,
- intro video skip patch.

Manual or special registration is used for:

- ResManager and battle pool lanes;
- dynamic obfuscated type targets;
- city music registry hooks;
- map billboard lifecycle hooks;
- hero portrait surface hooks.

Patch safety rules:

- `Prepare()` should gate optional features so disabled config does not patch runtime methods.
- Prefer narrow target methods over broad central hooks unless the feature genuinely needs a central interception.
- Central hooks like ResManager can create surprising cross-feature interference.
- Probe patches must stay opt-in.

---

## RAG_CHUNK: olden-era-playtest/060-offline-session

## Offline Unlock And Session Launch

Status: working.

Feature goal:

- Re-enable playtest menu paths that are blocked by demo/early access UI.
- Allow offline quick matches and configured starts without online gating.

Patched UI surfaces:

- `ScMainMenu.Start`
- `ScMainMenu.Update`
- `MainMenuNavigationView.Start`
- `ScEarlyAccess.Open`
- `ScDemoThankYou.Open`
- `BhDemoIconTxtUI.Start`
- `BhDemoIconTxtUI.ghj`
- `BhDemoIconTxtUI.yca`
- `BhNavigationButton.OnPointerClick`

Main behavior:

- Menu buttons are repeatedly kept enabled.
- Early access screen returns a completed task.
- Demo thank-you screen is bypassed.
- Demo overlay/watermark is hidden.
- Quick Start/New Game clicks are intercepted and routed to mod launchers.

Launch paths:

- `TryStartOfflineQuickMatch()` reads `Core.zip` data and quick start config, selects random factions/heroes, and calls session loader.
- `TryStartConfiguredNewGame()` uses merged config for faction, hero, map template, difficulty, and match mode.
- The loader call path uses `Hex.Session.Loader.utt()`.

Data dependencies:

- `DB/quickStart.json`
- `DB/data.json`
- faction lists and available fractions
- hero rows by faction
- RMG templates
- difficulty rows

Common failure classes:

- Missing faction in `DB/data.json` or available faction list.
- Hero faction mismatch.
- Missing `sub_class_config` for cloned heroes.
- Missing squads under `DB/squads/squads_<fraction>/`.
- Missing barracks or map interactable rows for generated faction.
- UI serialized asset lookup failure even when session data is valid. That is the `SoFractions.pqu` problem described in the custom faction docs.

Agent warning: a map can load while the session remains broken. Use UI binding, city open, recruit, return-to-world, and logs as validation, not map load alone.

---

## RAG_CHUNK: olden-era-playtest/070-core-data

## Core.zip Data Model And Custom Faction Requirements

Olden Era game data lives in `Core.zip`, mostly under `DB/`. The generators patch this zip directly and create backups.

Custom faction data cannot rely on one JSON file. A faction that appears in map/session/city/hero UI must be represented across many tables.

Strongly confirmed custom faction requirements:

- `DB/fractions/*.json`: fraction config row.
- `DB/fractions_laws/*.json`: faction laws table.
- `DB/data.json`: add to `fractions` and `availableFractions` as needed.
- `DB/cities/*.json`: city config.
- `DB/map/objects/4_interactables.json`: town and external dwelling map object registrations.
- `DB/map_objects_sounds.json`: map object sound mappings.
- `DB/city_ambient_sounds.json`: city ambient sound mapping.
- `DB/city_music_sounds.json`: city music sound mapping.
- `DB/objects_logic/hires/barracks.json`: faction-tier external hire rows.
- `DB/squads/squads_<fraction>/**`: squad definitions for neutral/session map logic.
- `DB/heroes/<fraction>/*.json`: hero rows.
- `DB/heroes_sub_classes/sub_classes_<fraction>.json`: subclass config referenced by heroes.
- `DB/heroes_skills/**`: skill tables and specializations where applicable.
- `DB/info/info_script_unit/units_<fraction>.script`: unit info scripts where applicable.
- localization JSON for cities, units, abilities, buffs, map objects, hero info.
- M2/M10 building banlists and construction presets when using RMG templates that reference city-specific rows.

Custom faction UI root cause:

- Runtime-added faction IDs are valid in JSON but absent from Unity-authored serialized `SoFractions` assets.
- HUD/city code calls `SoFractions.pqu(string)` to resolve `FractionLobbyAsset`.
- `homm3_stronghold`, `homm3_fortress`, and `dungeon_raw` are not serialized entries.
- Patch `SoFractions.pqu` to alias these IDs to `dungeon` for UI asset lookup only.
- Stronghold's alias result is now cloned before return, with only `icon` and `bigIcon` replaced by `homm3_runtime_assets/faction_icons/homm3_stronghold/Stronghold_H6_banner.png`; JSON-only faction icon edits do not affect this serialized UI path.

Do not confuse:

- data/session identity (`homm3_stronghold` should stay real);
- visual/UI serialized asset identity (`dungeon` can be used as an alias);
- unit visual prefab identity (`h3_*` routes through HoMM3 import paths);
- icon sprite key identity (`fraction_dungeon`, `hero_dungeon_*`, etc.).

Known misleading log:

- `Hero by id -1 not found` can appear in vanilla control runs. Treat it as a weak signal unless paired with broken UI transition or `BhHUDSession.ira` NRE.

Strong validation signals:

- `SoFractions: aliasing UI asset lookup 'homm3_stronghold' -> 'dungeon'.`
- no `BhHUDSession.ira` NRE on HUD startup;
- city open completes with time-spent log;
- Stronghold `h3_*` recruitment logs succeed;
- returning to world mode succeeds.

---

## RAG_CHUNK: olden-era-playtest/080-stronghold-data

## HoMM3 Stronghold Data Implementation

Main faction SID:

- `homm3_stronghold`

Main city SID:

- `homm3_stronghold_city`

Core generator scripts:

- `generate_homm3_stronghold_city.py`
- `generate_homm3_stronghold_heroes.py`
- `verify_homm3_stronghold_core_parity.py`

Stronghold is currently implemented as a data-level custom faction layered on Olden Era Dungeon structures while replacing units and parts of the presentation with HoMM3 assets.

Dungeon-to-Stronghold unit SID mapping:

| Dungeon donor | Stronghold SID |
| --- | --- |
| `trogl` | `h3_goblin` |
| `trogl_upg` | `h3_goblin_upg` |
| `trogl_upg_alt` | `h3_goblin_upg_alt` |
| `assassin` | `h3_wolf_rider` |
| `assassin_upg` | `h3_wolf_rider_upg` |
| `assassin_upg_alt` | `h3_wolf_rider_upg_alt` |
| `blade_dancer` | `h3_orc` |
| `blade_dancer_upg` | `h3_orc_upg` |
| `blade_dancer_upg_alt` | `h3_orc_upg_alt` |
| `minos` | `h3_ogre` |
| `minos_upg` | `h3_ogre_upg` |
| `minos_upg_alt` | `h3_ogre_upg_alt` |
| `medusa` | `h3_roc` |
| `medusa_upg` | `h3_roc_upg` |
| `medusa_upg_alt` | `h3_roc_upg_alt` |
| `hydra` | `h3_cyclops` |
| `hydra_upg` | `h3_cyclops_upg` |
| `hydra_upg_alt` | `h3_cyclops_upg_alt` |
| `black_dragon` | `h3_behemoth` |
| `black_dragon_upg` | `h3_behemoth_upg` |
| `black_dragon_upg_alt` | `h3_behemoth_upg_alt` |

Tier naming:

- Tier 1: Goblin / Hobgoblin / Hobgoblin Veteran.
- Tier 2: Wolf Rider / Wolf Raider / Wolf Raider Veteran.
- Tier 3: Orc / Orc Chieftain / Orc Warlord.
- Tier 4: Ogre / Ogre Mage / Ogre Warlord.
- Tier 5: Roc / Thunderbird / Stormbird.
- Tier 6: Cyclops / Cyclops King / Cyclops Warlord.
- Tier 7: Behemoth / Ancient Behemoth / Dire Behemoth.

City generator duties:

- clone Dungeon city/fraction/laws into Stronghold IDs;
- append faction to data lists;
- register Stronghold town and barracks map interactables;
- clone map and city audio rows;
- clone external hire rows;
- clone M2/M10 city preset rows;
- clone Dungeon squads into `squads_homm3_stronghold`;
- clone or rewrite unit logic/view data;
- keep Stronghold dwelling upgrade costs on HoMM3 resource/gold values while adding Olden Era's standard alchemical dust ladder on level-2 dwellings only: T1 10, T2 20, T3 30, T4 40, T5 50, T6 75, T7 100;
- add localization for city, unit, ability, buff, and map object tokens;
- write Stronghold-specific unit descriptions and ability display text.

Hero generator duties:

- clone Dungeon heroes into `homm3_stronghold_hero_*`;
- remap creature SIDs to `h3_*`;
- clone subclasses to `sub_classes_homm3_stronghold.json`;
- copy/adjust hero specializations and skills;
- remove bad custom faction skill SID that caused duplicate sub-skill key crashes;
- clone hero info localization tokens.

Parity checker duties:

- read `Core.zip` without modifying it;
- verify expected files and rows exist;
- verify squads, city/fraction/laws, audio, M2/M10, heroes, subclasses, and arena game references.

Squad-value audit, May 6, 2026:

- `tools/audit_stronghold_squad_power.py` reads the live release `Core.zip` and writes `docs/homm3_stronghold_squad_value_audit.md`.
- Static finding: Stronghold `squads_homm3_stronghold` templates are broadly in vanilla budget families; do not assume auto-battle trouble means squad templates are too low.
- More likely player-side auto-battle problem: high-tier unit `squadValue` is optimistic relative to raw stat output, especially Cyclops and Behemoth lines, unless their special mechanics fully compensate in auto-battle.
- If Stronghold guards are estimated too easy, first inspect specific ability semantics or auto-battle AI behavior before changing every map squad budget.
- Unit `squadValue` controls how many creatures a value budget buys; squad templates control encounter budget placement. Change the correct layer for the symptom.
- Auto-battle is not merely a `squadValue` formula. Release static metadata has `DataSquad.isAutobattle`, side `useMagicInAutoBattle`/`simulateBattle`, `UnitLogicConfig.saj/sak(EAbilityType)`, the `dxr`/`dxs` unit ability manager, and `BattleAiParams.topAbilityCasts` plus mech evaluation fields. Native passives, auras, default attacks, counterattacks, and alternative attacks should participate in simulated battles. Active `abilities[]` are case-by-case because the AI must be able to score and target them; do not count UI-only/custom hook behavior as auto-battle power without tracing.
- Live `DB/ai_battle/battle_ai_normal.json` and `battle_ai_hard.json` currently use `topAbilityCasts=1`. Explicit `mechValues` exist for heal, dispel, revive, substitute-by-hp, destroy stack/summon/temp stacks, assassinate, add energy, and global buff. Generic damage/debuff actives may already work through normal damage/buff scoring. Trap placement needs special caution: `trapHexValue=-300` means the default AI evaluates trap hexes negatively, so trap actives likely need native scoring work or redesign before they help auto-battle.

Agent warnings:

- Do not patch only units and call the faction done. The session can fail in squads, hero subclass, external hires, RMG presets, or UI asset lookup.
- Do not leave generated Stronghold hero icon keys pointing to unknown sprites unless `Homm3CustomUiIconHook` or another runtime sprite lookup path handles those keys.
- `fraction_law_homm3_stronghold_22` / Stronghold Envoys remaps the cloned Dungeon `heroStat` bonuses to `fraction="homm3_stronghold"`, so the law affects Stronghold heroes. Keep the localization aligned with that scope and do not change the mechanics back to Dungeon.
- Stronghold town dwelling upgrades must not require another dwelling's upgraded level. May 4, 2026 audit removed `Build_Tier_1` level 2 from `Build_Tier_2` level 2's prereqs; `verify_homm3_stronghold_core_parity.py` now fails any upgraded `Build_Tier_*` row that depends on a different `Build_Tier_*` at level > 1.
- Stronghold follows HoMM3's Mage Guild cap: generated `Build_Magic_Guild` must expose exactly 3 levels, not the Dungeon donor's 5. Keep the generator truncation and parity guard in place.
- Visible `{0}` / `{1}` in Stronghold text usually means the matching `HeroesOE_Data/StreamingAssets/Lang/args/*.json` `tokensArgs` row is missing or too short; the `texts/*.json` row alone is not enough. Use `generate_homm3_stronghold_city.py --lang-only` for repairs. May 2026: `h3_ogre_moral_selfbuff_description` needed explicit `H3_UNIT_BUFF_ARG_OVERRIDES` because the Dungeon donor `minos_moral_selfbuff_description` has no `unitsBuff` args row. A structural audit found no literal `[0]` placeholder-like tokens in Stronghold `Lang/*/texts`; capture the exact UI surface if square-bracket numbers appear in game.
- Hero descriptions have a separate trap: `homm3_stronghold_hero_*_raw_spec_description` and `_raw_raw_spec_description` are cloned Dungeon donor aliases and can show raw `{0}` placeholders even when the main `_spec_description` override is clean. `generate_homm3_stronghold_heroes.py --lang-only` refreshes those aliases to the same static Stronghold override text without rewriting `Core.zip`.
- If a generator directly mutates `Core.zip`, keep the script reproducible and update this doc with any new required tables.

---

## RAG_CHUNK: olden-era-playtest/090-ability-mechanics

## Ability And Mechanics Model

Olden Era supports many ability patterns, but not arbitrary custom JSON schema. The engine recognizes specific structures. Unsupported custom passive shapes can crash or NRE.

Stronghold ability mapping documents found:

- Most HoMM3 and Tears of Ashan Stronghold concepts have close Olden Era mechanic matches.
- Trap-laying was the only completely absent major mechanic in the mapping.
- Some mechanics are partial and require composition or C# support.
- Hero specialization findings: `docs/homm3_stronghold_hero_ability_mechanics.md`. Current Stronghold hero text is not authoritative because `generate_homm3_stronghold_heroes.py` clones Dungeon specialization `bonuses` and only remaps unit SIDs.

Data-layer abilities already implemented or cloned:

- Goblin/Hobgoblin: Long Reach alternate attack from Troglodyte donor.
- Roc/Thunderbird/Stormbird: Wing Gust movement/reposition pattern.
- Thunderbird/Stormbird: Lightning Strike from Medusa stone-gaze-like magic damage pattern.
- Cyclops: Boulder Throw using AoE shoot pattern `attack_rumble_x1_x100`.
- Cyclops Warlord: Petrification cloned from Medusa upgrade.
- Behemoth: Rampage / Whirlwind using swirl attack pattern.

Mechanics confirmed in data:

- melee and ranged attack profiles;
- alternate attacks;
- flying movement;
- blink/teleport;
- push;
- AoE around self;
- ranged AoE;
- DoT mechanics such as poison/burn;
- stun/petrify/turn skip;
- buffs/debuffs through a legitimate `buff` object;
- morale/luck auras in existing unit data;
- adjacent ally/enemy effects in existing patterns;
- defense-piercing passives;
- reflection when attacked;
- on-damage and on-death style triggers in existing units.

Data-only limitations:

- The passive system is not generic.
- Custom `aura`, `onDamage`, or `onAllyDeath` JSON invented by an agent is unsafe.
- `abilityCast` was observed as not recognized; use known ability attack types such as `move`, `melee`, `cast`, `jump`, and `end_move_attack`.
- Donor cloning is a safe ceiling but not full Stronghold design.

C# required or likely required:

- Wolf Pack aura.
- Fear Aura.
- Bloodlust active buff.
- Battle Cry AoE ally buff.
- Howl morale debuff.
- Blood Rage on ally death.
- Orc Rage on taking damage.
- Static Field melee reflection.
- Low-HP Berserker-style triggers.
- Siege-wall targeting if unit-based instead of hero ability.

Implementation pattern for C# abilities:

1. Find a narrow battle hook through interop, logs, or disassembly.
2. Gate by unit SID or `homm3_sa_` tag prefix.
3. Use known engine buff/mechanic structures where possible.
4. Log through `AgentDebugLog.Write`.
5. Add config/probe gates for risky discovery.
6. Validate in combat, not just by build success.

Agent warning: changing display text in `unitsAbility.json` does not implement mechanics. Keep "display strings", "data mechanics", and "runtime C# hooks" separate.

Agent warning: changing `homm3_stronghold_hero_*_spec_description` text also does not implement hero specialization mechanics. Inspect `DB/heroes_specializations/specializations_homm3_stronghold.json`; current live mismatches include Offense text on a Roc specialist row and Bloodlust text on a Cyclops specialist row.

---

## RAG_CHUNK: olden-era-playtest/100-visual-lanes

## Visual Replacement Lanes

There are two major unit visual replacement lanes.

### Esquire lane

Primary file:

- `EsquirePikemanVisuals.cs`

Purpose:

- Replace stock `esquire` / `esquire_map` with a custom AssetBundle visual and SFX.

Important paths:

- Battle prefab key: `units/Humans/1Prefabs/esquire`
- Map prefab key: `units/Humans/1Prefabs/esquire_map`
- Bundle: `custom_units_esquire`

Important hooks:

- `EsquirePikemanBattlePoolHook`: battle pool replacement.
- `EsquirePikemanUnitViewHook`: adventure map view replacement.
- `ResManagerGameObjectLaneHooks`: selected ResManager paths and battle SFX.
- `EsquirePikemanNarrowSpawnerHook`: optional UI spawner route.
- `EsquireBattleAnimatorSetHook`: animator state sync.
- `EsquireBattleAudioPlayer`: SFX playback.
- `EsquireUnityErrorCorrelator`: optional error correlation log.

Known state:

- Battle works with donor presentation constraints.
- Map is basic and historically fog-sensitive.
- Town/previews are partial or failed.
- Legacy broad ResManager postfix should not be re-enabled casually.

### HoMM3 import lane

Primary files:

- `Homm3ImportVisuals.cs`
- `homm3_import.json`
- `Homm3ImportBattlePoolHook.cs`
- `Homm3ImportUnitViewHook.cs`
- `Homm3ImportTooltipPortraitHook.cs`
- `Homm3ImportArmyStripPortraitHook.cs`
- `Homm3ImportNarrowSpawnerHook.cs`
- `Homm3ImportPreviewWindowHook.cs`
- `Homm3ImportUnitPreviewModelHook.cs`

Purpose:

- Replace multiple Stronghold units with HoMM3 DEF-derived AssetBundle visuals, portraits, and SFX.

Manifest shape:

- `bundleSubdir`: usually `homm3_bundles`.
- `battleResPath`: synthetic HoMM3 import battle path.
- `mapResPath`: synthetic HoMM3 import map path.
- `battlePresentationResPath`: vanilla donor battle prefab for presentation/animation shell.
- `mapShellResPath`: vanilla donor map prefab shell.
- `swapAdventureMap`: per-entry adventure map flag.
- `bundleName`: custom unit bundle.
- `battlePrefabAssetPath`
- `mapPrefabAssetPath`
- `audioStemPrefix`: lab-folder keyed battle SFX prefix (`HOMM3_<homm3_lab sid>_`), never faction-keyed.
- `gameUnitSids`

Current entries:

- 21 Stronghold unit entries.
- Base/upgraded/alternate variants for 7 tiers.
- Some upgraded and alternate variants share bundles.

Battle visual approach:

- Use donor presentation shell and imported HoMM3 billboard/texture.
- Hook battle pool and sometimes ResManager/spawner paths.
- Attach HoMM3 lab audio driver using lab-folder-keyed `audioStemPrefix` (`HOMM3_<homm3_lab sid>_`; no faction prefix).
- Runtime vertical lift is controlled by live config `esquirePikemanBattleBillboardExtraY`; as of May 2026 Stronghold uses `0.06` so HD-2D feet do not clip into the battlefield. Keep matching `battleQuadLocalPositionExtraY=0.06` in Stronghold `tools/homm3_import/presets/*/authoring.json` before Unity bundle rebuilds, or a rebuilt bundle plus reset config can make the units look slightly sunk again.

Map visual approach:

- Current best path is native shell + town-style static billboard + sanitized `Hex/Lit` material + disk-loaded HoMM3 texture.
- The map prefab supplies placement/authoring reference, but displayed texture may be loaded directly from extracted disk PNGs.

Preview state:

- Preview hooks are experimental and controlled by `homm3ImportPreviewHooks`.
- Golden Era correction, June 14, 2026: old `clb` preview-wrapper assumptions are historical. Current preview wrapper resolution should go through `GameSymbols.UnitPreview.PreviewWrapperTypeNames` / semantic accessors; `Homm3ImportClbPreviewFactoriesHook` is legacy and must stay outside `OFFICIAL_DEOBF_BUILD`.
- The black unit-preview backdrop failure observed on May 2, 2026 came from `Hex.BhUnitPreviews.hqv(UnitViewConfig)` calling `cld.sgk` with synthetic `units/homm3_import/...` paths, logging `unit mesh ... dont loaded`, and returning no model. This bypasses `ResManager.Get<GameObject>` and the battle pool.
- `Homm3ImportPreviewSyntheticMeshHook` patches `cld.sgk(string, ref GameObject, float, Transform, int)` bool/void loader variants for synthetic HoMM3 battle paths and supplies the bundle battle prefab so the normal preview factory can finish. `Homm3ImportUnitPreviewModelHook` then post-processes either a resolved preview wrapper or an already-supplied HoMM3 model for preview layer/material visibility.
- Do not re-enable broad reflected `Homm3ImportClbPreviewFactoriesHook` registration from `Homm3ImportUnitPreviewModelHook`. On May 2, 2026 the broad factory path post-processed shared preview rigs and matched the right-side HUD hero/town button disappearance after city/recruitment UI use. Keep the safer path limited to synthetic `cld.sgk` supply and explicit `BhUnitWindowPreview.bebc/Show` post-processing. The narrow `BhUnitPreviews.hqr` recruitment hook was disabled again after May 3, 2026 logs showed it uses a shared world-space preview point, so all replacement sprites render behind/around the recruitment window instead of per tile.
- Follow-up log findings: resolving `cld` only through `typeof(ObjCityConfig).Assembly` missed the method even though the stack trace showed `cld:sgk(String, GameObject&, Single, Transform, Int32)`. A later log found `Hex:cld` but still missed because the matcher assumed an exact `:bool` return. The hook now scans relevant loaded game assemblies, matches by loader parameter shape, supports bool and void return variants, and logs reflected `sgk` candidates if it still cannot patch.
- After the loader fix, logs showed normal preview background/circle plus supplied HoMM3 `battle` models with enabled `billboard/quad` renderers but no visible sprite. That points away from asset loading and toward render visibility. A follow-up attempt to make `Homm3BattleBillboardCameraFacing` score `Camera.allCameras`, `WorldToViewportPoint`, `cullingMask`, and `targetTexture` from injected `LateUpdate` crashed in `coreclr.dll` (`0xc0000005`) immediately after preview attachments. Do not revive that path. Preview windows should avoid attaching the dynamic camera-facing component and instead use safer renderer/material fixes such as double-sided preview materials.
- If a preview still shows the stock background/circle but no HoMM3 sprite, inspect `Homm3Import unit preview custom(after presentation)` for material/shader/texture/cull diagnostics. Preview targets currently default to `Sprites/Default` via `Homm3PreviewFineTuneRegistry` because `Hex/Lit` can be valid on the battlefield/map but fail to render in the preview pass.
- May 2, 2026 transform experiments: exact background-depth fit, slight negative-Z offset, parenting to the preview background, detaching from `Rotatable`, and a blind yaw+180 flip all failed. The last partially visible state kept the model under `Rotatable` and fitted to the background; the sprite was only visible after manually spinning the preview. A first production attempt mapped "leftmost" to orbit160, but it landed far right and required rotation. Orbit200 was near center but made the quad thin because orbit rotated its orientation too; orbit205 was visible but barely right of center. Production currently sets `PreviewCalibrationEnabled=false` in `Homm3ImportUnitPreviewModelHook` and applies position-only orbit207, scale 1.25, and slot `(0, -0.12, 0)` so the single detail-preview billboard stays broadside. Do not apply that world-space background fit/orbit to `BhUnitPreviews` recruitment previews: May 3, 2026 logs showed every recruitment tile reporting the same `platform`/`background` world point, which collapses all sprites into one screen area. A local-only replacement and wrapper re-entry guards still rendered large/shared sprites behind the recruitment window, so `BhUnitPreviews.hqr` replacement is disabled. Recruitment/upgrade visuals need a UI image/portrait hook or a discovered per-tile anchor, not 3D preview-wrapper replacement.
- May 3, 2026 follow-up: disabling `BhUnitPreviews.hqr` did not change the remaining recruitment visuals because `Homm3ImportPreviewSyntheticMeshHook` was still supplying `cld.sgk` requests with `layerArg=0` for every Stronghold unit. A follow-up attempt to refuse layer-0 synthetic mesh requests was wrong: it made all previews black and caused `BhUnitWindowPreview` NREs, proving the calibrated detail preview can still depend on those supplied prefabs. The safer recruitment attempt keeps synthetic mesh supply enabled for unknown/detail-preview calls, but for stacks clearly from city hire/upgrade UI it supplies an empty placeholder `GameObject`; simply returning false lets the original loader fail on synthetic paths and can produce selective black tiles. The placeholder must still contain at least one child transform: a later May 3 log showed `Transform child out of bounds` in `BhUnitPreviews.hqv`/`hqr` from `BhHireUnitItemView.tig` when the placeholder root had no children.
- Release launch-noise correction, May 6, 2026: plugin `0.1.256` makes the release full-feature slice respect `homm3ImportPreviewHooks=false` again. Forcing preview hooks on produced live Steam `BhUnitWindowPreview.beri(string,Transform)` / `Show(UnitViewConfig)` NREs even though the config disabled preview work. Keep release detail-preview replacement opt-in until the current wrapper path is statically remapped. The same pass removed the explicit `BhLobbyPopupFractionElement.Init` patch because Harmony could not bind parameter name `a`; the shape patch still covers the four-argument `(string, Sprite, bool, bool)` faction element surface.
- Release detail-preview packaged-animation fallback, May 7, 2026: Steam logs with `Homm3Import unit preview raw image` showed upgraded/Tears of Ashan unit previews such as `h3_wolf_rider_upg` and `h3_goblin_upg_alt` using static `homm3_portrait_*` textures, despite deployed `bundle-backed recruitment idle clips<sid>` folders. The raw-image animator was only using `TryGetIdleClip()` against `homm3_lab/<sid>/extracted_battle/02_*.png`, and the release install only had that lab tree for some base units. `Homm3HireUnitPortraitAnimator.ApplyIdle/ApplyRawIdle` now falls back to packaged `bundle-backed Unity RIFE idle clips` clips, and `Homm3ImportUnitPreviewModelHook` bounds the detail `RawImage` to 360px max instead of stretching 256x256 frames across the native render surface.
- Release turn-item patch crash, May 6, 2026: plugin `0.1.258` fixes a launch crash from `Homm3ImportReleaseBattleUiHook` broad-scanning `Hex.dll` turn-item candidates. The fatal signature was CLR `0x80131506` in `RuntimeConstructorInfo.GetParameters()` while inspecting unrelated IL2CPP constructors. Keep turn-item timeline portrait hooks limited to known classes (`elq`/`elm`) and declared-only members; do not use broad constructor-shape scans during plugin load.
- Release turn-item interop member warning, May 6, 2026: plugin `0.1.259` keeps the known-class/declared-only guard but detects generated interop properties/getters as well as fields. For live Steam `elq`, `cgyh` and `cgyj` are exposed through `get_cgyh` / `get_cgyj` over `NativeFieldInfoPtr_*`; `Type.GetField("cgyh")` alone silently skips turn-item patch registration.
- May 3, 2026 end-game NRE triage: Unity `Player.log` showed late `System.NullReferenceException` stacks only after the Stronghold starting hero was killed and `player 0:Player killed` fired. The stacks were `ezj.bhrb` and `ezi.bhqy` through `fbf.bigo(TypeEndGame)`, then `cta.ukr` through `BhSideTimers.via` at Bot turn start; `fm.OnDestroy` followed during shutdown. Keep these separate from preview/recruitment errors when reading logs.
- Treat unit preview/model window work as fragile until in-game validation confirms every Stronghold creature is framed and animating.

Agent warning: visual correctness has several independent surfaces: battle, adventure map, town, unit preview, tooltip portrait, army strip portrait, hero portrait, SFX. Fixing one does not imply the others are wired.

---

## RAG_CHUNK: olden-era-playtest/110-map-billboards-fog

## Native Adventure-Map Billboards, Fog, And Material Sanitization

**Agent warning:** `Homm3NativeShellVisibilitySync`, `EsquirePikemanMapBillboardFogSync`, fog polling, and squad mirrors **do not work** for HoMM3 map units. Never document or reattach them as FoW fixes.

Supported unit path (2026-05-31):

- `Homm3ImportVisuals.CreateNativeShellMapPrefabForAdventure` + `TryFinalizeNativeShellMapPresentation`
- clone vanilla map prefab shell;
- hidden `homm3_map_visual` child runs MapIdle (`map_frame_*` materials);
- **`Homm3NativeShellRendererTransplantSync`** copies animated mesh/materials onto the vanilla shell `MeshRenderer`/`SkinnedMeshRenderer` each frame;
- donor renderers use `enabled=false`; engine fog toggles the **native** renderer `enabled` like stock map sprites;
- apply `TownStyleUnitBillboardScale = 0.125` via `NormalizeAdventureMapPrefabBillboardScale`;
- log: `map finish signature v8-native-transplant`.

Do not rely on `Sprites/Default`, per-frame fog polling, visibility mirrors, or a visible child quad as the primary draw path for MapIdle/RIFE units.

Preferred disk frame order for unit billboard textures:

1. `00_04.png`
2. `00_00.png`
3. `02_00.png`

Material sanitizer:

- `EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial`

Sanitizer responsibilities:

- clone donor material;
- preserve HoMM3 texture;
- assign texture into all relevant exposed texture slots;
- reset scale/offset to `(1,1)` / `(0,0)`;
- clear unsafe secondary maps;
- force alpha clip / dither fade keywords;
- strip terrain-blend keywords unsafe for upright quads.

Important keywords:

- Keep or set: `HEX_DITHER_FADE_ENABLED`, `HEX_ALPHA_CLIP_ENABLED`, `_ALPHATEST_ON`.
- Strip for HoMM3 upright billboards: `HEX_BLEND_INTO_TERRAIN_POSITION`, `HEX_BLEND_INTO_TERRAIN_COLOR`.

Why strip terrain blend:

- Runtime logs showed donor `byzantine_palace_mat` carrying `HEX_BLEND_INTO_TERRAIN_POSITION`.
- That keyword is valid for native terrain-blended meshes but can distort the lower band of a simple upright quad.

Avoided/failed approaches:

- `Sprites/Default` primary map rendering: looks visible but ignores fog.
- Per-instance fog polling: performance issues and poor native matching.
- Runtime squad-root mirror components: wrong lifecycle and performance/NRE failures.
- Generic `GetComponents<T>` loops inside injected components: IL2CPP trampoline failures.
- Early renderer-transplant prototypes that copied `enabled` from the hidden child (broke engine fog) or targeted wrong renderer types.
- `Homm3NativeShellVisibilitySync` / `EsquirePikemanMapBillboardFogSync`: never worked; do not reattach.
- Mutating shared AssetBundle materials in place.

Verification checklist:

- visible on clear terrain;
- hidden by grey fog and black shroud;
- occluded by terrain/objects;
- outline/hover works;
- shadow shape is plausible;
- no donor/pikeman texture leakage;
- no bottom texture distortion;
- idle animation advances while the unit still hides in grey fog and black shroud;
- no frame-by-frame log spam;
- log includes `native-shell renderer transplant` and **not** `native-shell visibility mirror`.

Adventure-map idle animation warning:

- Keep animation on the native-shell `Hex/Lit` path. `Homm3MapIdleTextureAnimator` only swaps the texture bound to the existing material's texture slots; it must not replace the renderer, material shader, shell hierarchy, or visibility path.
- Use a global host/static registry rather than storing frame arrays on a component attached to the prefab quad. May 4, 2026 logs showed prefab-time `idle animator attached` lines but no visible animation; the injected component also warned about an unsupported `Texture2D[]` method parameter. The global host should produce bounded `idle animator tick` logs if it is running.
- If tick logs appear but sprites remain visually static, do not assume the frame source is wrong. May 4, 2026 logs showed host ticks against prefab-time material instances, so the animation path now also registers the live quad `Renderer` from a no-parameter component and applies the current frame through the renderer property block. Expected confirming log: `Homm3Import: town-style unit idle animator registered live renderer ...`.
- Use the disk glob for `02_*.png` frames under the lab's `extracted_battle` folder. A stricter JSON-manifest reader failed silently in the May 4, 2026 runtime log: static billboards appeared, but no idle animator registration/attach lines appeared. Do not use `00_*.png` for map idle; May 4, 2026 contact sheets for Goblin, Cyclops, and Wolf Rider showed group `00` is walking/locomotion and group `02` is standing idle/breathing.
- Do not restore the old animated `Sprites/Default` visual as the primary map renderer. It animates but bypasses native fog-of-war.

---

## RAG_CHUNK: olden-era-playtest/120-town-city

## Town, City Screen, Music, And Map Object Presentation

### City screen backdrops

Grove/nature backdrop:

- Runtime method: `ModActions.ApplyCustomCityBackdrop()`.
- Source image: `homm3_runtime_assets/town_scene_refs/grove/mockups/grove_background_mock_1920x1080.png`.
- Parent: `CanvasCityPanel` RectTransform.
- Rendering: `RawImage`.
- Status: working.
- Warning: do not lift or reorder global `CanvasTechHUDPanel` while fixing city backdrop layering. Runtime logs showed `BhHUDSession.me` uses `CanvasTechHUDPanel`; treating it as a city menu canvas can hide or cover the right-side adventure HUD hero/town buttons after initialization or city/recruitment transitions.

HoMM3 Stronghold backdrop:

- Source image: `homm3_runtime_assets/town_scene_refs/homm3_stronghold/mockups/homm3_stronghold_background_mock_1920x1080.png`.
- Applies for `homm3_stronghold` and other Homm3-style/dungeon-raw cases.
- Config key `homm3StrongholdTownBackdropScale` defaults to `1.18`. Stronghold scaling is top-left anchored because the useful HoMM3 content sits in the top-left of a padded 1920x1080 image; do not center-scale it or the town content can overrun the left/top edge.
- Status: PNG backdrop works.

Backdrop adjuster:

- `GroveBackdropAdjusterBehaviour`
- runtime actions can adjust sibling order, offset, scale, and alpha.

### Stronghold town building layers

Primary file:

- `Homm3StrongholdTownLayers.cs`

Purpose:

- Overlay building-layer PNGs on the city screen according to current town building state.

Layer source:

- `homm3_runtime_assets/town_scene_refs/homm3_stronghold/layers/`

Placement tooling:

- `homm3_runtime_assets/town_scene_refs/homm3_stronghold/placement_editor.py` previews the full padded 1920x1080 backdrop. The useful HoMM3 town source is intentionally in the top-left 1440x673-ish region; the right/bottom black padding is part of the runtime alignment.
- Runtime logs one line like `CanvasCityPanel basis WxH`; pass that to the editor with `python placement_editor.py --panel WxH` when the in-game city panel is not exactly 1920x1080-shaped.
- Upgrade placement overrides are supported in `positions.json`: runtime tries `layerId_<level>`, then `layerId_lvl<level>`, then base `layerId`. In the editor, choose an upgrade PNG and click `Add selected sprite as layer` to create a row like `extraCapitol_2` that can be dragged independently. Base placement rows must point at base/level-1 art; a base-row `sprite` override such as `*_2.png` makes upgraded/high-level town art appear before the low-level building is constructed. When copying a base row to an upgrade row, bottom-align different-height sprites with `upgradeY = baseY + baseHeight - upgradeHeight`; leaving the same top-left `y` makes taller upgrades sit too low.
- Warning: old editor assumptions cropped the backdrop to 1440x810 and could make drag adjustments look correct in the tool while drifting against the stretched RawImage in game.
- Runtime layer sizing uses per-axis scaling to match the stretched backdrop RawImage, and the layer root follows F8 backdrop offset/scale adjustments. If positions look right in the editor but not in game, check whether the F8 adjuster is active and press `R` to reset before comparing.
- Warning: resolve exact level sprites (`extraCapitol_1.png`) before base sprites (`extraCapitol.png`). The town hall/capitol animation swaps level-specific frames onto the base image; sizing the RectTransform from the full base capitol produces a misleading scale/offset error.

Runtime remapping:

- `building_layer_map.json` in the layers folder maps Olden Era building SIDs to layer IDs. This is what controls construction-order visual swaps.
- Use `python tools/remap_stronghold_town_layers.py` to launch the simple GUI remapper. It shows raw building SIDs, English in-game building names from `Lang/english/texts/cities.json`, and thumbnails for the selected layer sprite, with fallback names for odd aliases such as `Build_Spy_Network`. Warning: this tool only remaps visual layers; wrong building identities/SIDs must be fixed in the city generator/data, not by swapping localized names.
- Use `python tools/remap_stronghold_town_layers.py --list` to inspect it.
- Use `--tier-order layer1,layer2,layer3,layer4,layer5,layer6,layer7` to assign visuals to `Build_Tier_1..7`.
- Use `--set Build_Tier_1=dwellingUp2Lvl3` for targeted edits.
- Warning: `positions.json` only moves layers. `building_layer_map.json` changes which constructed building displays which sprite and animation key.

Representative placement mappings:

- `dwellingUp2Lvl1` / `horde2`: Build_Tier_1 at around `(373,187)`.
- `dwellingUp2Lvl2`: Build_Tier_2 at around `(266,225)`.
- `dwellingUp2Lvl3`: Build_Tier_3 at around `(566,134)`.
- `dwellingUp2Lvl4`: Build_Tier_4 at around `(197,107)`.
- `dwellingUp2Lvl5`: Build_Tier_5 at around `(129,15)`.
- `dwellingUp2Lvl6`: Build_Tier_6 at around `(616,93)`.
- `dwellingUp2Lvl7`: Build_Tier_7 at around `(604,0)`.
- `extraCapitol`: Build_Main Capitol at around `(760,0)`.

Sync hooks:

- Playtest: `BhCityUISession.ghj`
- `BhCityUISession.OnHide`
- Release: `BhUIBuildingSession.Init(fbi)` plus `tqf/tqg/tqh/tqj`; current city wrapper is `fbi bzac`
- `BhUIBuildingSession.OnHide`
- Release: `BhBuildingView.tnw(fbi,dvw,int)` / `UpdateView`, with `fbi byzb`
- Playtest: `BhBuildingsManager.zrj`; release: `BhBuildingsManager.bafl/bafh/bafi/bafj`, with `fbi cdwl`
- Release `BhUIBuildingSession.OnHide` and `BhBuildingsManager.OnDisable` are build-panel transition refresh anchors, not town-exit clears; clearing here reveals the donor Dungeon town after closing the build tree.
- `BhTownInput.ExitTownCmd`
- For release build-tree visibility, lift city menu canvases before backdrop sync on every release town refresh. `BUILDING VIEW PANEL` can be inactive during first town apply, then become active when the build-tree button is clicked; if `ApplyCustomCityBackdrop()` returns early on its debounce before lifting canvases, the custom backdrop/layers can stay above the native tree.
- Do not directly call generated private UI getters such as `BhUIBuildingSession.selector` from release diagnostics. `0.1.191` proved they can compile but throw `MissingMethodException` from native UI trampolines at runtime; use reflected access or IL2CPP field pointers instead.
- If `BhUIBuildingSession` diagnostics do not fire, instrument owner-level `BhCityUISession` methods instead. In `0.1.194`, the released `BhCityUISession` owns a `buildingSession` field and the likely build-panel route sits in the `twp/twq/twr/tws/twt/twu/twv/tww/twx/twy/twz/txa/txb/txc/txd` cluster.
- `0.1.197` rolled back the `0.1.195`/`0.1.196` release UI-art slice because startup still crashed right after chainloader completion. Do not reintroduce army-strip, hero-HUD, city-garrison, city-HUD-icon, and build-tree-icon remaps together; statically trace and re-enable one exact binder family at a time.
- `0.1.198` starts that re-enable with build-tree icons only. The release binder is `BhBuildingView.tnw(fbi,dvw,int)`, not a no-arg refresh; `icon` is a `List<Image>` and `overlayIcon` is a `GameObject`. `dvw.cnov/cnow/cdtc` provide key/level/config data. Keep `UpdateView/toi/toj/tok` disabled until the single-binder slice is proven stable.
- `0.1.199` adds the next isolated slice: release city HUD icon refreshes `BhCityUIElement.vza(int)`, `vzb()`, and private `vze()`. The old `vyf/vyg` names are stale for current Steam interop. Keep this separate from `BhHeroHUDPanel` and party/army hooks.
- `0.1.200` adds only the release build-tree hover oval art binders: `BhTooltipBuilding.syo(fbi,dvw,int)` and `syp(BhBuildingView,dvw,int,Action)`. These write the resolved `homm3_stronghold_building_<BuildSid>_level_<N>` sprite into `buildingBp`; they are not the same path as the already-working `BhBuildingView.tnw` row icons.
- `0.1.201` was stable but targeted the wrong surface: actual city garrison/visitor `BhHeroWithPartyCityView.txw(dsu)`, while the reported missing art was the main-town recruitment panel. `0.1.202` restored the old `BhHireUnitItemView.UpdateView(string)` hire-card hook, but that also did not affect the small recruitment strip. Static release mapping for the small strip is `BhCitySpecialView.items/itemsLow4/itemsLow3/bzfz -> BhCityHireIncrementItemView.pic`; the item binders are `BhCityHireIncrementItemView.tyk(Sprite, string, int, bool)` and `tyl(Sprite)`. The current release unit-slot list is still `BhUnitSlots.cngz` / `wcq()` / backing `cbap`; each slot's unit is `BhUnitUI.cngm` / `vvf()` / backing `cavr`. Older `cnfi/wbv/cnev/vuk` names are fallback only.
- `0.1.203` was confirmed in game: both the full recruitment screen and recruitment card display Stronghold art. The full recruitment screen still has Dungeon donor models visible behind the animated Stronghold sprites, so the next recruitment-specific task is hiding/suppressing the donor model layer rather than finding another icon binder. Because the tested recruitment slice is stable, the earlier startup crash is now most likely in the unreintroduced hero/army HUD portrait icon family, but treat this as a hypothesis until the exact release binder is isolated.
- `0.1.204` isolates the side hero/army-strip hero portrait to `BhHeroUIElement`, not the old HUD panel. Release fields/methods: `heroIcon` is the visible `Image`, `cayu` is the stored `ess` hero, `Init(ess)` is the primary binder, and `vzl()` / `vzr()` are local refresh paths. `BhHeroHUDPanel.ghk` is stale/not found in release and should remain disabled unless a future static trace proves its replacement.
- `0.1.206` confirms the selected hero HUD portrait path: `BhHeroUIElement.heroIcon` can be replaced successfully without affecting the visible selected hero portrait. The visible surface is `BhHeroHUDPanel.heroView: BhTooltipHeroItemView`, with release `ess` binders `tak(ess,bool)` and `taq(ess,bool)` applying through `heroFace`.
- `0.1.207` reintroduces only the release-safe adventure-map unit sprite lane. Static release tracing confirms `Hex.Configs.UnitViewConfig.sce()` is the map `GameObject` loader. The previous `Homm3MapSquadVisualControllerHook` should not be enabled yet because release `eya` has `bhou()` / `bhow(ess)` and simple `cip*` fields, not the playtest `Init(fbl,cta)` plus `chym/chyq` root/view-config fields.
- `0.1.208` records the first release-map visual failure mode: the map swap can succeed while every stack still shows stale pikeman-like art if the deployed plugin lacks disk frame PNGs. The runtime should prefer `Paths.PluginPath/OfflineUnlockMod/homm3_lab/<sid>/extracted_battle` and only use the repo-adjacent `oldenera_factions` root as a development fallback.
- `0.1.209` ports only the Stronghold adventure-map town/dwelling billboard hooks. The release path is `bve` metadata (`bvlm` config, `bvln` prefab array) plus `bvc` live placed object (`bvke` meta, `bvkq`/`bvkt` root); old `buv`/`but` assumptions are playtest-only. Direct `global::bve` and `global::bvc` source references failed compilation despite ILSpy showing top-level classes, so use assembly lookup and shape-based Harmony registration.

Click/hover handling:

- Stronghold layer `RawImage`s must stay non-raycast.
- Do not remap `BhBuildingView` root/`rect` transforms. May 2026 testing showed those transforms are visible construction/building-tree UI objects; moving them onto Stronghold town coordinates makes building-tree nodes disappear and creates blue button rectangles over the town.
- Do not revive the failed proxy approach: top-canvas transparent hit targets, extra `GraphicRaycaster`s, broad `Resources.FindObjectsOfTypeAll<BhBuildingView>()` scans, or global native raycast suppression caused severe load stalls, broken animations, and unreliable clicks.
- A future click solution must first isolate a truly invisible hit-only native child or find a native building action/screen API that can be called without moving construction UI.

Known state:

- Additional building layers are still not reliably working.
- Missing/incorrect layer PNG assets are suspected.

### Stronghold town map billboard

Primary file:

- `Homm3StrongholdTownMapBillboard.cs`

Purpose:

- Replace the world-map `homm3_stronghold_city` object, which reuses Dungeon city prefab registration, with a HoMM3-style town billboard.

Texture path:

- `homm3_runtime_assets/map_object_refs/homm3_stronghold_city/avcstrc0.dir/00_00.png`

Hooks:

- `buv` map-object metadata lifecycle.
- `but` map-object lifecycle.
- ResManager `interactive/dungeon_city` path interception.

Material path:

- Creates a quad with `MeshFilter` and `MeshRenderer`.
- Uses sanitized donor `Hex/Lit` material.
- Copies native renderer flags.
- Strips terrain-blend keywords.

### Stronghold city music

Primary file:

- `Homm3StrongholdCityMusic.cs`

Purpose:

- Route Stronghold city music to `sounds/city/music/homm3_stronghold`.
- Patch sound registry/group lookups around `fvh`, `fvf`, and `fvj`.
- Config volume: `homm3StrongholdTownMusicVolume`.

Agent warning: city presentation has separate surfaces: `Core.zip` city data, Unity city scene/backdrop, building layers, map object billboard, music, map object registration, and UI assets. Keep them separate while debugging.

---

## RAG_CHUNK: olden-era-playtest/130-portraits-icons

## Portraits, Icons, And Sprite Lookup

### HoMM3 unit portraits

Source:

- HoMM3 Complete `Data/H3sprite.lod`.

Mod source/deploy:

- Source: `OfflineUnlockMod/homm3_portraits/`
- Deployed: `BepInEx/plugins/OfflineUnlockMod/homm3_portraits/`
- Manifest maps unit SIDs to source DEF names.

Runtime use:

- `Homm3ImportPortraitSpriteCache.cs`
- `BattlePrefabPortraitTexture.cs`
- `Homm3ImportTooltipPortraitHook.cs`
- `Homm3ImportArmyStripPortraitHook.cs`
- `VanillaDungeonTooltipPortraitResLoader.cs` fallback.

Known state:

- Tooltip and army strip portrait replacement is partial but useful.
- There is a Dungeon fallback flag for tooltip portraits.
- Release auto-battle preview and battle-result hero portraits are separate surfaces. Current static layout maps pre-fight preview to `Hex.BhSimulatedBattleHeroesView.Init(TransferSide,TransferSide)` with `heroLeft`/`heroRight` images fed by `TransferSide.logicHero` or `TransferSide.hero.configId`. Battle results use `Hex.Session.Hud.BhSimulatedBattle.portraitLeft`/`portraitRight`, each a `BhHeroPortrait` where only `icon` is the real portrait; `panelLossHero`, `deathHero`, and `escapeHero` are result/status overlay fields. Do not write custom hero art into those overlay fields or the result screen shows an extra small hero icon.
- Release pooled unit portrait warning: if Stronghold unit portraits appear on unrelated enemy packs, selected-unit panes, or turn-order entries, inspect stale `Image.overrideSprite` before changing data or assets. `Homm3ImportReleaseBattleUiHook.ApplySprite()` writes both `sprite` and `overrideSprite`; native reuse can later set only `sprite` for a non-Stronghold unit, leaving the old Stronghold override visually active. Clear Stronghold overrides on non-Stronghold/missing SID refreshes or avoid `overrideSprite` on pooled portrait images.

### HoMM3 Stronghold Warcries

- Stronghold `skill_faction_homm3_stronghold` / Warcries is a unique generated faction skill, not a Dungeon/Triumvirate alias. It has three modes: Rallying Cry (`moral` side buff), Fortune Cry (`luck` side buff), and Tempo Cry (allied unit `initiative` global buff), scaling +1/+2/+3 by skill rank. Subskill `_1` is scoped to `fraction="homm3_stronghold"`, `_2` applies matching enemy penalties, `_3` gives friendly creatures `offencePerc=0.15`, `_4` adds +1 to the selected Warcry stat, and `_5`/`_6` preserve the Dungeon Flow/Mana behavior.
- Release Warcry gate correction from May 7, 2026: `0.1.285` was a false fix. Static disassembly showed `BhHeroAbilitiyView.siy(bzd,els)` and `OnClicked()` gate bytes, but forcing `els+0x18`, view `+0x49/+0x4A/+0x4B`, and child `CanvasGroup` state only made all three Warcry buttons light incorrectly. Do not patch release Warcry behavior by manufacturing UI gate state. Use `edg.baon()` for availability tracing and `BhHeroAbilitiesView.sia()` -> `cru.udy(view)` for click/cast dispatch tracing.
- Tempo Cry root cause from May 7, 2026: morale/luck working does not prove the creature `global_buff` path is resolving, because both have side-buff fallbacks. Early Start and Doreath's Tide store their initiative-capable buff rows in `DB/buffs/buffs_space_magics.json`. Generated Warcry creature buff rows must also be mirrored there, in addition to `DB/buffs/sub_skills_battle_hero_buffs.json` and `DB/buffs/sub_skills_battle_hero_ability_buffs.json`; otherwise Tempo Cry can cast and still apply no initiative change.
- Tempo Cry direct-buff fallback from May 7, 2026: after the `buffs_space_magics.json` mirror still had no visible effect in Steam release, generate Tempo base, Tempo `_2`, and Tempo `_4` as direct unit-buff dealers using `damageDealer.buff` and `buffTarget_="ally"` / `"enemy"`, matching Early Start's proven initiative application path. Do not change Rallying/Fortune while their side-buff behavior is working.
- Tempo Cry direct-buff shape correction from May 7, 2026: `0.1.287` still produced no visible buff when the direct unit-buff dealer inherited Warcry's `untargetedCast=true`; `0.1.288` also failed because it removed both `untargetedCast` and `multitargetType`. Doreath's Tide proves working all-unit initiative fanout keeps `multitargetType="simultaneous"` but omits `untargetedCast`. Generated Tempo direct-buff dealers now keep simultaneous fanout, remove only `untargetedCast`, and retain `attack_single_x100`, `castTarget_="all"`, `damageType_="none"`, and the direct `buff` payload. If this still fails, trace native direct-buff cast dispatch instead of toggling those two fields again.
- Tempo Cry presentation/duration correction from May 7, 2026: once Tempo direct buffs applied, they still used `duration=9999` and generic Dungeon offence buff metadata, so they could outlive the round and fail to present like normal initiative buffs. Tempo direct `damageDealer.buff` rows should use `duration=1`; generated initiative buff rows should use `magic_early_start_effect_icon` and include `movementPositive` / `movementNegative` tags alongside the Warcry-specific dispel tags.
- Tempo Cry buff-indicator correction from May 7, 2026: buff rows can apply and affect turn order without showing a unit-panel indicator if their `description_` points only at `heroSkills` tokens. Unit buff indicator/tooltip text for magic-style buffs resolves through `Lang/*/texts/magic_buff.json` plus `Lang/args/magic_buff.json`. Generated Warcry unit buffs now use `homm3_stronghold_warcry_{mode}_effect[_negative]_description` magic-buff tokens and args such as `current_buff_initiative_param`; keep those loose Lang rows because the Steam release overlay merges loose Lang into release `Core.zip`.
- May 4, 2026 native-registry cleanup: the generator writes Warcries into normal and arena registry surfaces. Arena rows include `arena_skill_faction_homm3_stronghold` in `DB/heroes_skills/skills/skills_arena.json`, `arena_sub_skill_faction_homm3_stronghold_*` in `DB/heroes_skills/sub_skills/sub_skills_arena.json`, cloned `arenaGame_homm3_stronghold_*_skills_table` files, and `arenaGame.json` Stronghold hero entries pointing at those tables. Do not point Stronghold arena heroes back at `arenaGame_dungeon_*_skills_table`.
- `Homm3WarcriesHeroAbilityHook` should stay narrow. It normalizes only the three `skill_faction_homm3_stronghold_ability_*` rows, bypasses the Focus comparison while preserving native cooldown/cast checks, forces representative no-arg energy getters to zero, and corrects `ekn.cgci` only for currently usable Warcries before `BhHeroAbilitiyView.rzt` consumes the wrapper. Do not broad-patch every `ecf` energy alias; a May 4, 2026 attempt caused battle-start recursion in `DynamicClass.DMD<ecf::jtq>`.
- Warcries native disassembly notes from May 4, 2026: `BhHeroAbilitiesView.ryt` (`0x2A6F0A0`) and `ryu` (`0x2A6F320`) build the hero ability buttons by calling `ecf.baak()` (`0x1ECA6E0`), constructing `ekn(dyu,bool,bool)` (`0x200D5F0`), then binding through `BhHeroAbilitiyView.rzt` (`0x2AA3B50`). `rzt` reads `ecf.bcdm()` (`0x1ECA8F0`) for energy pips and branches on `ekn.cgci` at wrapper offset `+0x18`; a false value calls `BhAbilityViewBase.tuf()` (`0x2B21330`) and marks the view disabled. The native side energy resolver used by `baak` is `0x1FB8270`; it returns zero cost when `ecf.configEnergyLevel` (`+0x6C`) is zero, before looking at current Focus thresholds. Warcry rows should omit explicit `energyLevel` / `dontUseEnergy`, matching Triumvirate; default zero is enough. The hook can normalize `configEnergyLevel`/`config.energyLevel` to zero before native wrapper creation, but do not set `config.dontUseEnergy`. If logs show `wrapperEnabled=True` while buttons are grey, the remaining state is coming from the `BhHeroAbilitiesView` / `crg` turn-side controller after bind, not from `ecf.baak()`.
- Current Warcries controller diagnostics are read-only. `Homm3WarcriesHeroAbilityHook` logs capped `rzt-post`, `refresh-*`, and `controller-*` snapshots for Warcry and Dungeon/Triumvirate SIDs, including wrapper enabled/selected state, view bool fields, and child `CanvasGroup` state. It also logs `fired; no compared hero ability view found` when a refresh/controller hook runs but root traversal does not expose a relevant view. Use those logs to locate the first post-bind refresh that greys Warcries after enemy retaliation or enemy-side events; do not treat the diagnostic probes as a behavioral fix.
- Follow-up: if `refresh-rza`/`refresh-rzd` fire with no compared view found, remember that `BhHeroAbilitiesView` stores buttons in IL2CPP list fields `heroAbilities` and `separateHeroAbilities`; they may not enumerate through managed `IEnumerable`, and dump names may not be exposed through `AccessTools.Field` on the generated interop wrapper. The diagnostic hook now tries property/field lookup directly and logs a one-time `BhHeroAbilitiesView members` line to map the available wrapper names.
- Member map result: `BhHeroAbilitiesView` exposes `heroAbilities` and `separateHeroAbilities` as interop properties. Child `BhHeroAbilitiyView` ability/wrapper extraction should also prefer properties (`cmfk`, `bxfy`, `bxga`) and `rzq()` before raw field scanning.
- Resolved refresh snapshots showed Warcry buttons remained enabled/interactable through `rza/rzd/rzb/rze`; the grey symptom was not reproduced as a wrapper, hero view bool, or top CanvasGroup flip. The next `BhAbilityViewBase` probe showed `pics` still using grey `WIP` sprites (`rgba(0.71...)`) despite `wrapperEnabled=True`. This is a missing hero-button icon fallback path: the JSON can name donor icons, and `Homm3CustomUiIconHook` can resolve them for other surfaces, but `BhHeroAbilitiyView` battle buttons still keep prefab WIP art unless patched after bind. `Homm3WarcriesHeroAbilityHook` now maps Warcry SIDs to `skill_leadership` / `skill_luck` / `skill_tactics` and reapplies those sprites to `viewBase.pics` after `rzt` and refresh; expected log is `Homm3WarcriesHeroAbility: hero icon applied ...`.
- Crash warning: do not call `BhHeroAbilitiyView.rzu(true)` from a `BhHeroAbilitiyView.rzt` postfix. The May 4, 2026 attempt to force the button enabled in `rzt` caused recursive `rzt -> rzu -> rzt` stacks and a crash after leaving tactics phase.
- Safer Warcries button-bind correction: if working at `BhHeroAbilitiyView.rzt`, only inspect/correct the incoming `ekn` wrapper. Read the underlying ability via `ekn.cgch` first; helper methods such as `bdzg/hwt` may fail to expose the Warcry. It is safe to set `ekn.cgci=true` for a currently usable Warcry before native bind consumes the wrapper, but do not call hero-view methods from the `rzt` patch.

### HoMM3 selected-unit battle HUD

Primary file:

- `Homm3ImportBhSelectedUnitHudFix.cs`

Known state:

- `BhSelectedUnitHud.bdon` indexes a vanilla dictionary directly and throws `KeyNotFoundException` for custom `h3_*` SIDs such as `h3_goblin` and `h3_wolf_rider`.
- The fix seeds any `BhSelectedUnitHud` string-keyed dictionaries by copying donor entries to the custom `h3_*` SID before vanilla `bdon` runs, then still suppresses that exception as a fallback so the battle update loop can continue. If this path works, logs show `Homm3Import selected-unit HUD: seeded ... dictionary`.
- Do not restore `StrongholdUnitSidMapping.cs` as the default path. Donor SID rewriting can make the selected-unit HUD bind donor state, producing hydra-style portraits and blank/stale one-turn-cooldown ability buttons.
- May 2026 logs showed the patched `BhSelectedUnitHud` instance is a `UNIT SELECTION` GameObject with zero child `Image` objects. It is an event handler, not necessarily the visible portrait/ability UI parent.
- Current fallback scans active UI images under a `Canvas` after a custom-SID lookup failure and replaces donor-looking portrait images with `homm3_portraits` sprites. This must stay donor-sprite-gated and cached; a broad scene predicate caused turn-change performance spikes and replaced unrelated UI images. Useful log prefix: `Homm3Import selected-unit HUD scene portrait`.
- May 2026 follow-up: do not hide `BhUnitAbilityView`/ability-looking objects from the selected-unit HUD finalizer. Logs showed that cleanup hid 6 active ability objects after each custom-SID lookup failure, which made every Stronghold battle action bar blank even when the ability data existed. Prefer suppressing the exception and leaving the action bar surface alone until the real custom-SID dictionary source is found.
- May 2026 blank one-turn cooldown follow-up: if vanilla `BhSelectedUnitHud.bdon` throws before it reaches its controls binding, the finalizer can keep the game alive but leave stale action-bar buttons visible. Recovery still calls private `BhUnitControlsView.bdqs(Unit)` through the HUD's generated `controlsView` property after suppressing a custom-SID lookup failure, but runtime probes showed `bdqs(unit)` alone left `BhUnitControlsView` at `map=0 current=-1` and never invoked `bdqo`/`BhUnitAbilityView.bdpz`.
- May 2026 correction: `AccessTools.Field(typeof(BhSelectedUnitHud), "controlsView")` does not work against this IL2CPP interop type. Even though the native dump lists `controlsView` as a field, the managed interop wrapper exposes it as a generated public property. Use `hud.controlsView`; startup logs showing `AccessTools.Field: Could not find field...controlsView` mean the action-bar recovery path is not running.
- May 2026 direct-bind correction: the current finalizer recovery now reads the selected unit's live `unit.celq` (`dwq`) ability manager, tries `bv` then `zxy` for `Hex.Configs.EAbilityType.Ability`, `AlternativeAttack`, and `All`, clears stale controls, and calls `controlsView.bdqo(abilities, null, true)` when a non-empty `dwr[]` exists. Prefer full `bv` buckets here because `zxy` may go empty after use/cooldown and make actions disappear. Do not pass the first ability as the selected ability: that made every recovered button render as preselected/glowing. Do keep the bind flag true, because `false` made available buttons render greyed out. Useful log prefix: `Homm3Import selected-unit HUD controls direct bind`. This is now a fallback behind the lower-level `Homm3UnitAbilityNativeHook` bridge.
- May 4, 2026 playtest live interop audit: `unit.celq` is inherited from base `ebw`, not declared on `Hex.Session.Battle.Unit` itself. The playtest native target is `ebw.celq` (`dwq`), whose mutable bucket table is `dwq.cdga: Dictionary<EAbilityType, Il2CppReferenceArray<dwr>>`; `dwq.zxy(EAbilityType)` and `dwq.bv(EAbilityType)` expose those `dwr[]` buckets. Each playtest `dwr` wraps `AbilityLogicConfig cdgt`, `AbilityViewConfig cdgu`, and an `AbilityID`; `dwr.Init(AbilityLogicConfig, AbilityViewConfig, AbilityID)` constructs the wrapper and `dwr.baak()` is the native availability check. `BhUnitControlsView.bdqs(Unit)` is the selected-unit entry, while `BhUnitControlsView.bdqo(dwr[], dwr selected, bool)` is the concrete action-bar bind call. Release warning: current Steam interop rejects this mapping. Release `dwr` is a Shrine of Rebirth building wrapper; release ability work must use `dxr` manager, `dxs` wrappers, `BhUnitControlsView.begy/begu`, and `BhUnitAbilityView.begf`.
- May 4, 2026 native unit action-bar bridge: `Homm3UnitAbilityNativeHook` patches `dwq.Init(ebw)` and `BhUnitControlsView.bdqs(Unit)` for Stronghold units, normalizes `unit.celq` buckets before wrapper availability is read, and binds merged `Ability` + `AlternativeAttack` arrays through native `bdqo`. It intentionally prefers full `dwq.bv(...)` buckets over currently-available `dwq.zxy(...)` buckets, leaving `dwr.baak()` to grey out unavailable actions without removing them from the bar.
- The source data feeding `unit.celq` is the paired unit logic/view config arrays in `Core.zip`: `DB/units/units_logics/<fraction>/*_l.json` and `DB/units/units_views/<fraction>/*_v.json`. For Stronghold this is `DB/units/units_logics/homm3_stronghold/*_l.json` plus `DB/units/units_views/homm3_stronghold/*_v.json`, generated by `generate_homm3_stronghold_city.py`. Live wrappers expose these as `UnitLogicConfig.abilities/defaultAttacks/counterAttacks/alternativeAttacks` and `UnitViewConfig.abilities/defaultAttacks/counterAttacks/alternativeAttacks`, with per-type accessors `UnitLogicConfig.rrj/rrk(EAbilityType,...)` and `UnitViewConfig.rtb/rta(EAbilityType,...)`. For action-bar stability, prefer correcting those arrays or `dwq.cdga` before `bdqs/bdqo`, not late UI-only `BhUnitAbilityView` visual patches.
- Warning: `tools/il2cpp_out_new/dump.cs` has stale obfuscated names in this area. Use the target install's live `BepInEx/interop/Hex.dll` decompile for action-bar traces, and do not apply playtest `dwq/dwr/ekn/bdqo/bdpz` assumptions to the released game.
- May 2026 toggle-state follow-up: direct-bind recovery clears and rebuilds the controls, so it must preserve an existing selected action from `BhUnitControlsView.cfyf` before calling `Clear()`. Pass that same `dwr` back into `bdqo` only when it is already selected and still present in the recovered ability array; otherwise pass `null`. This avoids both always-glowing buttons and losing the glow/toggle state after clicking an action.
- May 2026 repeated-bind correction: do not call `Clear()`/`bdqo()` again when `BhUnitControlsView.cfyg` already matches the recovered ability array. Logs showed repeated `bdqo(... selected=null ...)` for the same Orc melee action after the bar was already populated, which can wipe native click/toggle state before it is visible.
- May 2026 hidden-view correction: `cfyg` can keep matching the recovered Orc ability even after another custom unit with no action-bar abilities calls `ClearAndHideUnitControls` and hides the shared `BhUnitAbilityView` object. The "already bound" fast path must also verify that active ability view GameObjects contain the same abilities; otherwise call `bdqo` again to reactivate the slot.
- May 2026 click-state correction: native disassembly of `BhUnitControlsView.bdqp` shows a same-button branch, so repeat-click deselect depends on `cfyf` matching the clicked `BhUnitAbilityView`. Recovered custom buttons now mirror `cfyf` in a `bdqp` patch and call `BhUnitAbilityView.bdqc(true/false)` to restore selected-ring animation and let the native deselect branch run on the next click. Useful log prefix: `Homm3Import selected-unit HUD controls selection`.
- May 2026 hotkey correction: native `BhUnitControlsView.bdrf(object, HotkeyAbilityArgs)` is the selected-unit ability hotkey handler. It uses `HotkeyAbilityArgs.idButton` to index `abilities` and then calls `bdqp(view)` if the slot has a wrapper. The recovery patches `bdrf` for custom recovered views and routes through `bdqp`, including a one-based/only-active fallback. Keep it custom-gated; broad raw keyboard polling would bypass player hotkey settings.
- May 2026 hotkey fallback follow-up: a later run had mouse `controls selection` logs but no `hotkey action` logs, showing that recovered custom controls were not receiving the native ability-hotkey event. A hidden IL2CPP `Homm3RecoveredHudHotkeyFallback` polls only default ability keys `1`-`5`/keypad `1`-`5` while a recovered custom action-bar view is active and routes through `bdqp`. This is deliberately narrower than global input replacement.
- May 2026 post-use visibility correction: after a custom action is used, `dwq.zxy(...)` may return no currently available ability. Direct-bind recovery may reuse the last successfully bound ability array only when the current SID is the same custom SID; cross-SID cache reuse would leak stale action-bar buttons between units.
- May 2026 active-plus-alt correction: direct-bind recovery must merge `EAbilityType.Ability` and `EAbilityType.AlternativeAttack` buckets before binding `BhUnitControlsView.bdqo`. Returning after the first non-empty `Ability` bucket made basic Orc Hamstring replace the vanilla ranged-unit melee fallback button even though the generated `common_attack_1_name` alternative attack row still existed.
- May 2026 disabled-button correction: recovered custom action buttons must respect the `ekn` wrapper passed to `BhUnitAbilityView.bdpz`; `ekn.cgci` is the enabled/available flag logged by `StrongholdAbilityPanelProbe`. Cache that flag per `BhUnitAbilityView` instance and have recovered click/hotkey patches ignore disabled views, or no-Focus abilities can still glow/select cosmetically even though the game correctly refuses to execute them.
- May 2026 blank cooldown root cause: `unit.celq` also exposes normal/alternative attacks. Logs for `h3_orc` showed `bdqo` binding `common_attack_1_name` with `canUI=False`, `icon=objects/test_images/padlock`, `cd=-1`, which rendered as a blank/padlock one-turn-cooldown action-bar item. Direct-bind recovery must reject common/default attacks, but do not require `canShowOnUI` for every real ability: generated Stronghold abilities like Thunderbird Lightning Strike use `abilityType=Ability_type_*` / `infoDescription=ability_*` without `canShowOnUI`.
- Ranged melee fallback rule: vanilla ranged units can show `common_attack_1_name` in `alternativeAttacks`, but the view row includes `abilityType=Ability_type_attack_alt`. Stronghold Orc/Cyclops rows originally lacked this field, so the HUD filter either rejected them or rendered padlock/blank state. Keep generated ranged melee alt views aligned with vanilla by setting `abilityType=Ability_type_attack_alt`.
- Stronghold custom creature rows now carry explicit vanilla donor `AbilityViewConfig.icon` keys to avoid padlock/placeholder art in battle and recruitment surfaces. Current generator mapping: Goblin Trapper Land Mine and Orc/Orc Chieftain Hamstring -> `wasp_debuff_icon`, Double Attack -> `pet_blood_icon`, Boar Rider Charge and Ogre Brute Frenzied Charge -> `minos_buff_icon`, Bloodlust -> `magic_sharp_edge_effect_icon`, Return After Strike -> `assassin_buff_icon`, Lightning Strike -> `primal_1_magic_thunderbolt`, Ferocity -> `dragon_hunter_blood_icon`, No Distance Penalty -> `crossbowman_buff_icon`, Behemoth defense reduction -> `sub_skill_units_attackPen_icon`. Keep `verify_homm3_stronghold_core_parity.py` in sync with this mapping. JSON is not enough for every UI path: `Homm3CustomUiIconHook` must also allowlist these exact donor keys and resolve them through `TryFindLoadedSprite`, the same pattern used for Dungeon subclass icons.
- Combat action-bar icons use a separate surface from preview/recruitment icons. If preview icons work but battle buttons still show placeholders, patch/check `BhUnitAbilityView.bdpz`; `Homm3CustomUiIconHook` has a postfix there that reads the bound `dwr.cdgu.icon`, resolves known donor keys, replaces icon-like/placeholder child `Image`s, and creates a non-raycast `HOMM3_BATTLE_ABILITY_ICON` overlay on the chosen icon rect. The overlay is needed because the native button has multiple child image layers and replacing only the first scored image can still leave a placeholder visible on top.
- Focus cost pips on combat action-bar abilities are owned by the serialized `BhAbilityViewBase.energyContainer`; the exposed native updater is `BhAbilityViewBase.ucx(int,int)`. Stronghold recovered/custom buttons can bind and gate correctly while still missing pips, so `Homm3CustomUiIconHook` reapplies `ucx(cost,cost)` for known custom Stronghold actives with `energyLevel > 0` and no `dontUseEnergy`. Keep custom icon overlays below the native energy container (`HOMM3_BATTLE_ABILITY_ICON` must not be last sibling above pips), or the cost markers can be present but hidden.
- Hobgoblin differentiation: normal Hobgoblin (`h3_goblin_upg`) carries the extra-counter identity, not Goblin Trapper. Set `stats.numCounters=2`, show `base_passive_aware_1_name` / `base_passive_aware_1_description` in the view, and keep Trapper at `numCounters=1`. This mirrors vanilla Griffin/Toxic Troglodyte's visible `Alert I` convention for two counters per round.
- Goblin Trapper `Land Mine` is currently a 1-Focus hex-target unit active that uses OE's native `spawn_object` target mechanic with the existing `magic_space_trap_snare_summon` trap config. This gives a real hidden snare trap but is not yet the exact HoMM3/ToA damage-scaling Land Mine behavior.
- Boar Rider `Charge` is a 1-Focus committing melee active. It deals 100% normal damage, triggers normal melee counter behavior, and applies `h3_wolf_rider_upg_alt_charge_debuff` (`Luck -5`) to the target for 1 round. It is a charge analogue, not true distance-scaling Jousting.
- Orc Hamstring is an experimental custom active ability, not HoMM3 canon. It uses the vanilla ranged debuff schema (`attackType_="shoot"`, `cd=1`, `energyLevel=1`, `damageDealer.tags` including `ability` + `debuff_ability`, and `damageDealer.buffTarget_="enemy"` with a negative unit buff SID). Basic Orc deals 50% ranged attack damage and applies Speed -2 for 1 round; Orc Chieftain deals 100% ranged attack damage and applies Speed -3 for 1 round. For abilities that should end the unit's action, do not add `infoDescription="ability_no_turn"` to the view row.
- Ranged melee fallback tooltip rule: the Stronghold generator must also set `infoDescription="ability_no_energy"` on Orc/Orc Chieftain/Cyclops/Cyclops King/Blood-Eyed Cyclops `common_attack_1_name` alternative attack view rows. The logic rows already use `dontUseEnergy=true`; without the view hint, native tooltips can imply a Focus cost that does not exist.
- May 2026 stale-control correction: `BhSelectedUnitHud.bdon` exceptions can report a custom missing key such as `h3_orc` while `BattleEventArgs.target` is null or a stale vanilla unit. Prefer the exception key only for a real custom target or a same-SID transient refresh. If the missing custom SID is paired with a non-custom/mismatched event target, suppress the exception but do not touch portrait or controls; logs showed stale `h3_goblin`/`skeleton_upg` events clearing Orc's shared action bar after Orc used an action. After a custom action is used, transient null/stale refreshes should keep or restore the cached action bar only for the same custom SID.
- Triage rule: if direct-bind logs `cleared: no live action-bar abilities`, the HUD layer is probably no longer the primary issue; inspect ability construction/config loading for why `unit.celq` has no active buckets. If it logs `bound` and the UI still shows blank one-turn cooldown buttons, inspect `StrongholdAbilityPanelProbe` `bdqo`/`bdpz` output for wrapper/view data before changing donors or custom SIDs.
- The portrait fallback has separate discovery and cached-update predicates. Discovery requires donor sprite evidence, while cached updates validate the selected HUD path (`BattleBottomHudCanvas/.../UNITPart/UNIT PIC/BACK PORTRAIT`). Reusing the donor-sprite predicate for cached updates makes the first HoMM3 portrait stick for the whole battle.

Diagnostic warning:

- `StrongholdAbilityPanelProbe.cs` logged that `BhUnitAbilityView.Start` was absent in this build. Do not assume Unity lifecycle method names on obfuscated IL2CPP UI classes; scan candidate methods narrowly and cap runtime logs. For battle action-bar issues, use `BhUnitControlsView.bdqs/bdqo` and `BhUnitAbilityView.bdpz` probes because those are the actual selected-unit controls and per-button bind methods.

### HoMM3 hero portraits

Dedicated findings:

- `docs/homm3_stronghold_hero_portrait_findings.md`
- `docs/homm3_custom_ui_icon_fallback.md`

Current state:

- Stronghold hero slots 1-18 use custom JSON icon keys `hero_homm3_stronghold_N`.
- Hero slots 17-18 have no extracted HoMM3 Stronghold portrait PNGs, so `Homm3ImportPortraitSpriteCache` aliases them to existing HoMM3 portraits until real art exists. Do not restore Dungeon donor icon keys for those slots.
- Extracted HoMM3 hero PNGs are under `OfflineUnlockMod/homm3_hero_portraits/` and deploy through the `.csproj`.
- `Homm3HeroPortraitHook.cs` still contains targeted surface fallbacks, but the broad working path is `Homm3CustomUiIconHook.cs`.
- `Homm3CustomUiIconHook.cs` supplies runtime sprites/textures for custom keys that the game's serialized sprite registry does not know: `h3_*`, `hero_homm3_stronghold_*`, `homm3_stronghold_hero_*`, and `fraction_law_homm3_stronghold_*_icon`. It also has a deliberately narrow loaded-Unity-sprite fallback for the four Dungeon subclass icon keys used by Stronghold hero classes.
- Runtime testing showed this shared fallback resolved the widespread orange placeholder issue for unit portraits before recruitment, ability icons in unit/recruitment previews, Stronghold law custom art, and hero portraits.
- Release law icon drift, May 7, 2026: current Steam `BhFractionLawView` binds through `zce(dtd,dqj)` and refreshes through `zcg()`. The `dqj` wrapper no longer exposes the custom law icon through the old playtest names alone; static metadata shows `cnis` / private `cbxu`, and `DataFractionLaw` exposes `cnuv` / private `chpa`. Keep those names in `Homm3StrongholdLawIconHook.ResolveLawIconKey()` or Stronghold unit-law PNGs can be present while the UI still falls back to placeholders.
- Adventure-map hero models are separate from portrait/icon UI and from the solved unit/town-object map billboard path. The current safe path is `Homm3HeroMapSpriteHook.cs`: patch the concrete hero drawer constructor selected by signature plus the current session-hero visual attachment surfaces, gate eligible heroes with `Homm3CustomFactionRegistry`, and resolve drawer/root/config/SID names through `GameSymbols.HeroMap`. Do not call native root getters such as `ese.bgus()` from the session visual path, and do not reintroduce hot root-getter postfixes or scene polling for heroes.
- `OfflineUnlockMod/homm3_hero_map_sprites/` must deploy to `BepInEx/plugins/OfflineUnlockMod/homm3_hero_map_sprites/`. Sprite selection is faction/class specific: prefer `HeroConfig.fraction + classType`, and if the session surface lacks `HeroConfig`, use direct `Hex.Session.Data.Hero.configSid` only with explicit deployed `homm3_hero_portraits/manifest.json` `classType` metadata. Do not infer might/magic from hero number ranges, do not guess missing manifest rows, and do not share Stronghold hero DEF art across other factions once their own extracted sprite folders exist.
- Defextract showed HoMM3 adventure hero DEF group `02` is a single idle frame for `AH13_` and `AH13b_`. The current visible map animation loops group `07` turn frames first, then group `08`, and only falls back to single-frame `02`. Do not assume these hero DEFs have creature-style multi-frame idle groups.

Why changing only JSON `icon` is not enough:

- The normal game UI resolves `hero.icon` through serialized sprite dictionaries.
- New keys like `hero_homm3_stronghold_1` are unknown unless a runtime sprite lookup hook or dictionary injection provides sprites.
- Unknown icon keys can yield blank UI or lookup errors.
- `ckj` is not the central resolver in this playtest build; logs showed no useful `ckj` `Sprite(string)` resolver. Do not repeat the `ckj.scf/hqu/scg` assumption.

Current runtime icon fallback path:

1. Keep custom keys limited to the prefixes handled by `Homm3CustomUiIconHook`.
2. For missing UI art, check logs for `Homm3CustomUiIcon: supplied Sprite/Texture`, `Homm3CustomUiIcon: surface replaced`, and `Homm3CustomUiIcon diag: ability`.
3. If replacement lines appear but the visible art is still a placeholder, the visible image is probably overwritten later or owned by a different UI surface.
4. If diagnostics show only vanilla donor keys, the issue is not a missing custom key; inspect that UI binder or its serialized sprite lookup.

Stronghold building-tree portraits now use custom `homm3_stronghold_building_<BuildSid>_level_<N>` keys in `DB/objects_logic/cities/homm3_stronghold_city.json`. `Homm3StrongholdBuildingIconSpriteCache` resolves those keys from `homm3_runtime_assets/town_scene_refs/homm3_stronghold/layers/*.png` through the shared custom icon fallback. Do not restore cloned Dungeon `G_build_*` keys when regenerating the city. The large oval hover art in the town build menu is not the same binding path: playtest used `Hex.UI.BhTooltipBuilding.spi/spj`, while the current full release uses `syo(fbi,dvw,int)` and `syp(BhBuildingView,dvw,int,Action)`. The hook gates on current city fraction `homm3_stronghold`, derives the same key from release `dvw.cnov/cnow` and the tooltip level argument, then writes the sprite to `buildingBp`.

Stronghold map/HUD city buttons use `homm3_stronghold_city_icon`, resolved by `Homm3StrongholdCityIconSpriteCache` from `homm3_runtime_assets/map_object_refs/homm3_stronghold_city/avcstrc0.dir/00_00.png`. The cache also accepts `homm3_stronghold_city` and `fraction_homm3_stronghold` for surfaces that bind directly by city/fraction SID. The world-map city button is `Hex.Session.Hud.BhCityUIElement`; May 2026 logs showed the visible orange placeholder is child image `Pic` with sprite `WIP`, while city wrapper SID reflection can be null. Do not add more DB aliases for this symptom; replace the live `Pic`/placeholder child after the Stronghold city icon key is requested.

The static `homm3_portraits/h3_*_upg_alt.png` files should be generated from Tears of Ashan `content.zip` large creature icons (`sprites/creatures/stronghold/iconsbig/lvl{N}Alt.png`). Earlier extractor versions reused normal HoMM3 upgraded DEFs for `_upg_alt`, which made alternate upgrades show the same portrait as the standard upgrade on every UI surface backed by `Homm3ImportPortraitSpriteCache`.

City recruitment item visuals: `BhHireUnitItemView.UpdateView` exposes the unit key, but the first child `Image` logged as `UNIT HIRE FRAME`, not the actual creature portrait. Do not write HoMM3 portraits into that frame image. `Homm3CustomUiIconHook` creates/updates a non-interactive `HOMM3_HIRE_UNIT_PORTRAIT` overlay under the hire item root, falling back to the frame `RectTransform` as the overlay parent if the view component is not directly on a UI transform. If overlay creation fails, return without replacing the frame image; the frame replacement produced black-looking hire visuals.

Known remaining icon/framing issues:

- Small hero class/subclass icons next to the hero preview portrait now route through the custom icon fallback only for the four Dungeon subclass icon keys used by Stronghold (`sub_class_dungeon_might_1_icon`, `sub_class_dungeon_might_2_icon`, `sub_class_dungeon_magic_1_icon`, `sub_class_dungeon_magic_2_icon`). Useful runtime confirmation: `Homm3CustomUiIcon: loaded vanilla sprite fallback key='sub_class_dungeon_...'`.
- Stronghold hero class names are HoMM3 names, not Olden Era Dungeon donor names: Might = `Barbarian`, Magic = `Battle Mage`. `generate_homm3_stronghold_heroes.py` writes subclass name SIDs `sub_class_homm3_stronghold_might_name` / `sub_class_homm3_stronghold_magic_name` and adds compatibility heroSkills aliases such as `stronghold_might_hero`, `stronghold_magic_hero`, `homm3_stronghold_might_hero`, and `homm3_stronghold_magic_hero`. Preserve these aliases to avoid raw `LOD:` class placeholders in UI surfaces that derive class text differently.
- No obvious HoMM3-specific Might/Magic class badge asset has been found in repo reference assets. Default policy: use Dungeon class icons for Barbarian/Battle Mage-style Might/Magic unless real HoMM3 class badge art is added.
- Hero portraits now resolve. Preview polish is asset-side: `homm3_hero_portraits/*.png` are 64x64 circular-alpha PNGs, and `Homm3HeroPortraitHook` applies them without a runtime `Outline`. The H3bitmap LOD entries may not decode as normal PCX bytes in this environment, so `tools/extract_homm3_hero_portraits.py` can circularize existing PNGs as a fallback.

Candidate portrait surfaces if continuing surface hooks:

- `BhHeroHUDPanel`
- `BhHeroWithPartyCityView`
- `BhHeroPortraitView`
- `BhTooltipHeroItemView`
- `BhTooltipSquad`
- `BhHeroView`
- `BhTavernHeroView`
- hero selection/pick UI classes.

Agent warning: icon key, portrait PNG, `Sprite` object, UI `Image`, localization-visible hero name, and central sprite dictionary are separate things. Do not conflate them.

---

## RAG_CHUNK: olden-era-playtest/140-damage-histogram

## Damage Forecast Histogram

Status: working, with known retaliation display mismatch.

Purpose:

- Display a kill-probability histogram near the game damage forecast.
- Use game-provided min/max forecast as bounds, then model probability shape with HoMM3-style damage roll logic.

Primary files:

- `DamageHistogramOverlay.cs`: forecast capture, state, UI rendering, tuner.
- `DamageDistribution.cs`: total damage PMF and kill PMF.
- `DamageKillMapping.cs`: integer damage to killed stack count using game unit data.
- `LuckCritMixture.cs`: luck/crit mixture layer.
- `DamageHistogramPanelUgui.cs`: uGUI panel renderer.
- `DamageHistogramGameChrome.cs`: captures stock forecast panel frame sprite.
- `DamageHistogramCastBlocklist.cs`: filters forecast-only kill-stack cast types.
- `HOMM3_damage_rolls.md`: design reference.
- `AGENT_REBUILD_AND_MAINTENANCE.md`: maintainer guide.

Runtime hooks:

- `ejz.bdwu(DamageUiParams, bool) -> ejy`
- `ejz.oez(DamageUiParams, bool) -> ejy`
- `BhHealDamageForecastPanel.Show(ejy)`
- `BhHealDamageForecastPanel.Hide()`

Steam release port/coexistence note, May 7, 2026:

- Keep histogram as a separate BepInEx plugin package from Stronghold, with its own plugin GUID, folder, config, and uninstall state.
- No mod manager is required just to install histogram beside Stronghold. BepInEx loads multiple plugin DLLs from `BepInEx/plugins`, and Stronghold's installer already handles the shared Doorstop/BepInEx bootstrap.
- The histogram installer should be idempotent around shared bootstrap files and should not remove or overwrite `BepInEx/plugins/OfflineUnlockMod`.
- Histogram should stay code/UI-only for the release port and must not patch `HeroesOldenEra_Data/StreamingAssets/Core.zip`. If future histogram work needs Core data edits, then use a merge-aware installer or mod manager because Stronghold already owns a Core overlay/backup path.
- Implementation shape: `Heroes of Might & Magic Olden Era Playtest/DamageHistogramMod/DamageHistogramMod.csproj` builds a separate `DamageHistogramMod.dll` into `BepInEx/plugins/DamageHistogramMod/`. It links the shared histogram source from `OfflineUnlockMod` but supplies its own BepInEx plugin GUID, entry point, and `config.json`; do not package it as part of `OfflineUnlockMod` when the goal is standalone install.
- Co-install warning: if the Stronghold/`OfflineUnlockMod` assembly also has `damageHistograms=true`, both plugins can patch/render the same forecast surface. Standalone release installs should keep Stronghold's `damageHistograms` disabled and let `DamageHistogramMod/config.json` own the feature.
- Do not assume the playtest `ejz` forecast surface exists in the Steam release. Re-map the release forecast path statically from regenerated interop/decompiled code before enabling histogram patches.
- May 7 remap: release `dump.cs` still has `Hex.Session.Battle.DamageUiParams` and `BhHealDamageForecastPanel`, but the forecast calculator moved from playtest `ejz.bdwu/oez(DamageUiParams,bool) -> ejy` to release global static `elc` methods returning `elb`: `bemz`, `iqw`, `bsh`, and `jvd`. The release forecast DTO fields map structurally from old `ejy` as `cgau/cgav/cgaz/cgba` -> `elb.cgwy/cgwz/cgxd/cgxe`; `BhHealDamageForecastPanel.Show` now takes `elb`, and its RectTransform accessor is `bemd()` instead of the old `bdvy()` path. The port now resolves these by field/method shape instead of hardcoding old class names. First runtime load before the resolver fix logged `Damage histogram forecast calculator patches applied: 0` and `panel Show patch target not found`; do not treat that as evidence the static map is wrong.
- Standalone compile follow-up: release `DamageUiParams` uses interfaces `dzv/dzw/dzz` rather than the old concrete playtest `dyt/dyu/dyx` helper surface. The standalone plugin now reads stack counts/stats by reflection (`bayd`/`bbco`/`bayc`/`bayb` style names) and disables the old synthetic retaliation re-query path until the release retaliation caster/source/target interfaces are traced. Do not reintroduce direct `global::dyt/dyu/dyx` signatures into shared histogram code.
- Standalone startup crash fix, May 7, 2026: do not use `Newtonsoft.Json.DeserializeObject<T>` in the separate histogram plugin's early config load. The first standalone build crashed before Chainloader startup completed with `AccessViolationException` under `JsonConvert+MethodInfoStoreGeneric_DeserializeObject...cctor()` while loading `HeroesOE Damage Histogram 0.1.0`. Keep the standalone config reader dependency-free or use a non-generic parser proven safe under BepInEx IL2CPP startup.
- Standalone hook resolver fix, May 7, 2026: after the Newtonsoft crash was fixed, runtime logs showed the standalone plugin loaded but registered zero forecast patches and no panel Show patch. The release static map was still correct (`elc` and `BhHealDamageForecastPanel.Show(elb)`), but looking up `elc` only through `typeof(DamageUiParams).Assembly.GetType("elc")` was stale in the standalone load context. Resolve `ejz`/`elc` across loaded assemblies first, then fall back to a bounded `(DamageUiParams,bool) -> forecast DTO` static-method shape scan; resolve the panel Show hook by a single forecast DTO parameter instead of depending on a literal method name. Keep the panel postfix argument-free so Harmony does not need to bind obfuscated release parameter names.

Important DTO:

- `ejy` contains forecast min/max damage and kill hints. Field names are obfuscated and must be revalidated after game updates.

Damage model:

- Treat engine forecast min/max total damage as authoritative bounds.
- Infer per-creature min/max from total bounds and stack size.
- For stack size <= 10, convolve independent uniform per-creature rolls.
- For stack size > 10, use HoMM3 10-roll rule and scale by stack size.
- Apply luck/crit mixture afterward where supported.
- Convert total damage PMF to kill PMF using `DamageKillMapping`.

Render paths:

- IMGUI path through `OnGUI`.
- uGUI path parented to the forecast panel RectTransform.

Tuner:

- F9 opens histogram tuner overlay.
- Tuner controls chart dimensions, gap, layout percent, edge feather, font scale, and min bars.
- Save writes relevant keys to canonical mod config and invalidates config cache.

Known issue:

- Retaliation chart can show even when the game's retaliation indicator does not show.
- The mismatch likely sits in `DamageHistogramState.TooltipRetaliationRowVisible` or related forecast panel row visibility interpretation.

Rebase warning:

- Search regenerated interop for `DamageUiParams`, `BhHealDamageForecastPanel`, `bdwu`, `oez`, and forecast DTO shape.
- Compare output to stock UI after field names change.

---

## RAG_CHUNK: olden-era-playtest/150-retaliation-probes

## Retaliation Fixes, Probes, And Diagnostics

### Retaliation forecast fix

Primary file:

- `RetaliationForecastFix.cs`

Purpose:

- Suppress rapid `BhHealDamageForecastPanel.Hide()` calls after `Show()` to reduce flicker.

Config:

- `retaliationForecastFix`
- `retaliationForecastDebounceMs`

Hooks:

- `BhHealDamageForecastPanel.Show(ejy)`
- `BhHealDamageForecastPanel.Hide()`

State:

- Records show time by panel.
- Suppresses hide if elapsed time is within debounce window.

Known state:

- Partially working. Debounce helps some flicker but is not a complete retaliation logic fix.

### Probe architecture

Probe marker:

- `[ProbePatch]`

Behavior:

- Normal auto-patching excludes probe patches.
- Probe patches are loaded through separate Harmony only when retaliation debug is enabled.

Probe files:

- `BattleForecastProbe.cs`
- `BattleTooltipProbe.cs`
- session probe classes in `Plugin.cs`
- `StrongholdAbilityPanelProbe.cs`
- `ResManagerInteropProbe.cs`
- Esquire spawner reflection probe.

Diagnostics:

- `AgentDebugLog.cs` writes structured JSON-ish log entries for agent consumption.
- Esquire diagnostics log state and resource paths.
- Unity error correlator can tie Unity errors to Esquire state.

Dangerous diagnostic pattern:

- Broad reflective `SessionStateProbe` shape scanning can crash IL2CPP, including observed `LocalKeyword.get_isDynamic()` access violation.
- Runtime `MonoBehaviour` loops with broad generic component scans can create IL2CPP trampoline failures and NRE loops.

Safe diagnostic pattern:

- Patch a known narrow method.
- Log method name, SID, object name, path, and a few primitive fields.
- Cap logs.
- Gate probes with config.
- Remove or disable probes after collecting evidence.

---

## RAG_CHUNK: olden-era-playtest/160-il2cpp-rebase

## IL2CPP Dump, Native Map.Init Analysis, And Rebase Workflow

Use official/source-generated interop where possible, but for method bodies and native null locations use Il2CppDumper + disassembly.

Local dump tools:

- `Heroes of Might & Magic Olden Era Playtest/tools/run_il2cpp_dumper.cmd`
- `Heroes of Might & Magic Olden Era Playtest/tools/run_il2cpp_dumper.sh`
- `Heroes of Might & Magic Olden Era Playtest/tools/disasm_il2cpp_rva.py`
- `Heroes of Might & Magic Olden Era Playtest/tools/search_il2cpp_dump.py`
- `Heroes of Might & Magic Olden Era Playtest/tools/il2cpp_rva_sanity_check.py`

Inputs:

- `GameAssembly.dll`
- `HeroesOE_Data/il2cpp_data/Metadata/global-metadata.dat`

Outputs:

- `tools/il2cpp_out/dump.cs`
- `tools/il2cpp_out/script.json`
- `tools/il2cpp_out/stringliteral.json`

Important Map.Init findings:

- `Hex.Map.Map.Init` constructs many subsystems before `buz`.
- NREs inside `Map.Init` before `buz..ctor` can come from `bua`, `bwe`, `bvh`, `bva`, or `bvk`, not just `buz`/`buf`.
- `buz..ctor` constructs `buf`, `bun`, `bty`, `buj`, `bvi`, and `buh` in a specific call order.
- `bwe..ctor` is a key null-risk region mixing static Unity data and map graph initialization.

Known playtest RVA examples from existing note:

- `epw$$GenerateMap`: `0x20D4DF0`
- `Hex.Map.Map$$Init`: `0x28CB310`
- `buf$$.ctor`: `0x28D8E20`
- `buz$$.ctor`: `0x2900A70`
- `bwe$$.ctor`: `0x2939110`
- `bts$$Init`: `0x28C15F0`

Rebase checklist:

1. Regenerate BepInEx IL2CPP interop for the new game build.
2. Refresh `BepInEx/core` and `BepInEx/interop` references only if that is part of the intended change.
3. Search interop for key symbols: `bdwu`, `oez`, `DamageUiParams`, `BhHealDamageForecastPanel`, `dzk`, `buv`, `but`, `SoFractions`, `BhHUDSession`, `ResManager`.
4. Build with deploy disabled.
5. Fix compile errors caused by obfuscated renames.
6. Re-run narrow runtime smoke tests by feature flag.
7. Update docs with changed names and removed assumptions.
8. Bump plugin version if shipping runtime changes.

Agent warning: method stubs in `dump.cs` do not contain bodies. They tell you names/signatures/RVAs, not control flow. Use disassembly for native null paths.

May 4, 2026 HoMM3 world-map billboard defeat effect: prefer the narrow fade path in `Homm3MapBillboardDeathFade`. It attaches to the already-working `homm3_map_visual/quad` Hex/Lit renderer, registers live map roots through `Homm3MapObjectUnitVisualHook`, and probes capped `fce`/`fcd` removal/death candidates. Runtime evidence should come from `Homm3 map billboard death fade: triggered path=...`. Avoid defeat hooks based on `OnDisable`, renderer disappearance, fog/shroud visibility, scene-wide scans, or spawned clone death animations; those paths are either ambiguous with fog or have caused severe stutter.

---

## RAG_CHUNK: olden-era-playtest/165-il2cpp-semantic-map

## IL2CPP Semantic Map And Obfuscated Name Translation

Use `docs/il2cpp-semantic-map.md` as the working translation table for obfuscated native symbols. The purpose is to gradually attach semantic names to methods, fields, and pointer chains using evidence, similar to translating an unknown language from parallel texts.

Confidence levels:

- Known: exposed by interop name, enum, JSON field, method signature, or logged SID.
- Strong inference: static disassembly and runtime behavior agree across a meaningful scenario.
- Tentative: plausible from call flow, field offset, or a single runtime observation.
- Rejected: disproven interpretation or unsafe fix path kept as a warning.

For each mapped symbol, record the current symbol, RVA when known, inferred name, confidence, evidence, callers/callees, and warnings. Do not promote an inferred name just because it explains one failing run. Prefer confirmation from a vanilla donor path, such as Dungeon/Triumvirate's Strength, compared directly against the custom Stronghold path.

Current priority target: battle ability controls.

- `ecf.baak()` is strongly inferred as the hero ability availability gate.
- `ekn(dyu,bool,bool)` is the ability view wrapper; `ekn.cgci` is strongly inferred as the wrapper enabled flag.
- `BhHeroAbilitiesView.ryt/ryu` build hero ability buttons and bind them through `BhHeroAbilitiyView.rzt`.
- `BhHeroAbilitiyView.rzt` is strongly inferred as the hero ability button bind method.
- `BhHeroAbilitiesView.rzi/ryy/ryw` and `crg.tuq/tun/tur/...` remain tentative controller/refresh/click-path methods until donor/custom runtime traces name their exact roles.

Warcries diagnostic principle: if logs show `wrapperEnabled=True` during `BhHeroAbilitiyView.rzt` while the button later appears grey, the remaining disagreement is after initial bind. Investigate `BhHeroAbilitiesView` / `crg` refresh/controller state before making more Focus-cost or `ecf.baak()` changes.

Patch safety:

- Do not call `BhHeroAbilitiyView.rzu(true)` from an `rzt` postfix; this previously caused recursive `rzt -> rzu -> rzt` crashes after tactics.
- Do not patch every apparent `ecf` energy alias; a broad alias patch previously caused battle-start recursion in `DynamicClass.DMD<ecf::jtq>`.
- Keep runtime probes bounded and SID-filtered.
- Prefer data/registry fixes if the donor enters a native dictionary that the custom SID misses.

---

## RAG_CHUNK: olden-era-playtest/170-agent-workflow

## Agent Workflow And Warnings

This project has many uncommitted and generated files. Treat the worktree as shared with the user.

Before edits:

- Run `git status --short`.
- Identify staged vs unstaged changes.
- Do not revert or unstage user changes unless explicitly asked.
- Prefer new docs or narrow additions when existing files are already dirty.
- Read existing topic docs before implementing a "new" approach; many failed paths are already recorded.

During edits:

- Keep changes scoped to source files, not deployed runtime outputs, unless deployment is the task.
- Use existing patterns: Harmony patches, config gates, `AgentDebugLog`, explicit SIDs.
- Avoid broad reflection and broad ResManager hooks.
- Avoid inventing JSON schema for unit abilities.
- Avoid changing `Core.zip` manually when a generator should own the change.
- Add warnings to docs when you discover a false lead.
- When you learn anything concrete about an obfuscated IL2CPP method, field, pointer chain, or native registry, update `docs/il2cpp-semantic-map.md` with the symbol, inferred name, confidence, and evidence. This applies even when the discovery is incidental to another fix.

Validation:

- `dotnet build -c Release -p:DeployPluginToGame=false` for compile-sensitive C#.
- Feature-specific runtime smoke is required for rendering, UI binding, and IL2CPP patches.
- Core.zip data changes should run `verify_homm3_stronghold_core_parity.py` when Stronghold is touched.
- Visual map changes need clear terrain, fog, black shroud, occlusion, outline, shadow, and texture-leak checks.
- Hero portrait changes need multiple UI surfaces, not just the HUD panel.

Commit guidance:

- Commit when possible and safe.
- If unrelated staged changes exist, do not make a broad commit.
- If committing only your docs, use an explicit path-limited commit and verify it did not include unrelated staged work.
- If a file already had user changes and you add a hunk, be careful not to commit the user's hunks accidentally.

High-value warnings against repeated mistakes:

- Do not fix hero portraits by changing `icon` keys alone.
- Do not re-add `HEX_BLEND_INTO_TERRAIN_POSITION` or `HEX_BLEND_INTO_TERRAIN_COLOR` to upright HoMM3 billboards without proof.
- Do not share postfixes containing playtest-only `global::but` references with full-release `bvc` map-object hooks. The `0.1.209` map-object billboard slice produced repeated `TypeLoadException: Could not load type 'but'`, map-load stutter, and a crash on turn pass. Use release-only reflection postfixes and patch `bve.Init(ObjectConfig)` / `bvc.Init(Map,bve,int,byte,float)` narrowly.
- Do not call generated playtest `buv.buwy` / `buv.buwz` accessors from release map-object billboard hooks. `0.1.210` removed the `but` trampoline issue but still spammed `Method not found: 'Hex.Map.ObjectConfig buv.get_buwy()'` from the dwelling path; release `bve`/`bvc` hooks need reflection-only SID/prefab readers.
- Do not read `Hex.Map.ObjectConfig.id` or other string members reflectively inside release `bve.Init(ObjectConfig)` postfixes. `0.1.211` crashed on turn pass with `AccessViolationException` in `ConfigElementBase<string>.get_id()` from the Stronghold town billboard metadata hook. `0.1.212` avoids release metadata-init billboard hooks and keeps replacement on live `bvc.Init(Map,bve,int,byte,float)`.
- Do not revive runtime squad mirror / runtime attach loops for fog.
- Do not use `Sprites/Default` as the primary map unit solution.
- Do not treat map load as full custom faction validation.
- Do not trust obfuscated method names after game updates.
- Do not broadly reflect Unity/IL2CPP object graphs.
- Do not assume display strings implement abilities.

---

## RAG_CHUNK: olden-era-playtest/180-status-matrix

## Current Feature Status Matrix

| Feature | Status | Notes |
| --- | --- | --- |
| Offline menu unlock | Working | Buttons, EA skip, thank-you skip, demo overlay hide |
| Offline quick match | Working | Uses Core.zip quick start/data |
| Configured new game | Working | SinglePlayer/Hotseat config-driven |
| UI scale | Working | BhFont + CanvasScaler hooks |
| Intro cinematic skip | Working | VideoPlayer patch + init safeguards |
| Custom faction UI alias | Working | `SoFractions.pqu` alias to Dungeon |
| Stronghold Core.zip faction | Working/iterating | Generator plus parity checker |
| Stronghold heroes | Working/iterating | HoMM3 portrait keys resolve through `Homm3CustomUiIconHook`; class icons use Dungeon fallback keys; preview portraits use circular-alpha assets |
| Stronghold abilities | Partial | Some data-layer abilities; C# required for auras/triggers |
| Esquire battle visuals | Working | Donor presentation constraints |
| Esquire map visuals | Basic/legacy | Fog-sensitive history |
| Esquire previews | Nonworking | Failed/leftover attempts |
| HoMM3 battle visuals | Working | Manifest-driven bundles |
| HoMM3 map visuals | Working but verify per build | Native shell + disk texture + sanitized Hex/Lit |
| HoMM3 unit previews | Experimental | `homm3ImportPreviewHooks`; synthetic `cld.sgk` hook added for black preview backdrop |
| HoMM3 tooltip/army portraits | Working/iterating | Cache, surface hooks, and custom icon fallback |
| HoMM3 hero portraits | Working/iterating | Shared custom icon fallback plus targeted surfaces; 64x64 circular-alpha PNGs |
| Stronghold city backdrop | Working | PNG under city canvas |
| Stronghold town layers | Not reliable | Asset/layer issues suspected |
| Stronghold map city billboard | Working, verify distortion fix | AVCSTRC0 quad; strip terrain blend keywords |
| Stronghold city music | Implemented | Sound lookup patches; runtime verification needed after changes |
| Damage histogram | Working | Retaliation chart mismatch remains |
| Retaliation forecast fix | Partial | Debounce only |
| IL2CPP Map.Init docs | Useful | RVAs version-specific |

---

## RAG_CHUNK: olden-era-playtest/homm3-faction-automation

## HoMM3 Faction Automation Investigation

Full note: `docs/homm3_faction_automation_investigation.md`.

Stronghold is close enough to use as the automation template for other HoMM3 factions, but not as a copy-paste runtime implementation. Rough estimate: 70-80% of mechanical scaffolding can be automated after adding a manifest-driven generator for faction SID rows, unit donor mappings, HoMM3 DEF/audio names, heroes, town sources, laws, localization stems, release overlay rows, and runtime registry data.

High-automation areas: Core.zip faction/city/law/squad/hero/map/quickgame/localization shells; unit logic/view row cloning; `tools/homm3_import/` extraction/bootstrap; AssetBundle authoring stubs; `homm3_import.json`; release Core overlay entries; basic Custom Game registration and icon/portrait keys.

Manual release-quality areas: OE donor mapping per unit; stats/growth/cost/projectile/AI tuning; native-heavy ability mechanics; town DEF-to-building SID mapping and `positions.json` placement; faction laws and building graph; hero specialties, skills, armies, spells, portraits, class labels, and map sprites; release UI/hook revalidation after Steam hotfixes; external dwelling/RMG/random-hire logic beyond visual aliases.

Refactor warnings: replace `StrongholdUnitSidMapping.cs` with a data-driven donor alias registry; generalize `ReleaseCustomGameUiProbe.cs` production insertion from Stronghold-only to configured custom factions; split `Homm3StrongholdTownLayers.cs` into a generic layer loader plus faction data; make hero/class portrait hooks consume generated registries. Stronghold town extraction scripts are templates, not generic tools yet. Placeholder decision rules for the first automated pass are in `docs/homm3_ai_first_pass_design_principles.md`.

Expected effort: first additional faction around 1-2 days for scaffold plus 3-7 days of manual quality work; later factions after manifest/runtime-registry refactor should be much faster. Castle/Rampart are lower-risk, Dungeon/Fortress moderate-high, Tower/Inferno/Necropolis/Conflux high because of native-heavy mechanics and town/unit complexity. HotA/Cove needs a separate asset-source lane; HoMM3 Complete `H3sprite.lod` is not enough.

---

## RAG_CHUNK: olden-era-playtest/homm3-first-pass-principles

## HoMM3 AI First-Pass Design Principles

Full note: `docs/homm3_ai_first_pass_design_principles.md`.

Stronghold-derived hierarchy for first-pass faction design: keep the game stable and playable; preserve recognizable HoMM3 identity where OE data supports it; use OE-native data before runtime hooks; make approximations explicit in data/text/docs; defer native-heavy behavior until statically traced.

Use Horn of the Abyss balance values over vanilla Complete values when HotA has an entry. Convert probability-based HoMM3 or Tears of Ashan creature effects into focus-point abilities instead of hidden random passives. Every `_upg_alt` row must have at least one passive or active ability differentiator from `_upg`; pure stat changes are not enough.

Use donors for engine compatibility, not lore purity. Stronghold cloned Dungeon for faction/city/unit scaffolding and used Undead map shells for Wolf Riders where that fit the map unit better. Keep HoMM3 import keys in private namespaces so vanilla donor enemies do not collide with custom swaps.

Prefer data-only approximations. Stronghold implemented Hall of Valhalla as a hero Attack building, Mess Hall as `cityUnitsIncrement h3_goblin +8`, Resource Silo through known resource income, and deferred Escape Tunnel/Freelancer's Guild/Ballista Yard because no safe data path was known. Visible text must describe implemented behavior, not desired source behavior.

Preserve unit shape before exact numbers. Stronghold kept Goblins fast/glassy, treated Wolf Riders as already high offence/speed, and flagged Cyclops/Behemoth for high-tier manual review. Use OE same-tier ranges as guardrails, keep stat and ability review separate, and do not use `squadValue` alone.

First-pass manifests should store design intent with each placeholder: `decisionStatus`, `sourceBehavior`, `implementedBehavior`, `rationale`, `confidence`, `manualReviewReason`, and `staticTraceRequired`. Decision ladder: exact OE data behavior, safe OE approximation, donor-backed scaffold, static trace required, or visual placeholder. Do not jump from unknown native behavior to an untraced runtime hook.

Hard warnings: clone complete gameplay surfaces, not just units; make text match implemented behavior; do not fix building identity with localization or town art; do not duplicate global sub-skill IDs when adding faction skills; mark town layer placement as manual review.

---

## RAG_CHUNK: olden-era-playtest/homm3-faction-planning-docs

## HoMM3 Faction Planning Documents

Editable first-pass plans for non-Stronghold HoMM3 factions live in `docs/homm3_faction_plans/`.

Plan files: `castle.md`, `rampart.md`, `tower.md`, `inferno.md`, `necropolis.md`, `dungeon.md`, `fortress.md`, `conflux.md`, and `cove.md`.

Unique faction skill recommendations, updated May 7, 2026: Castle should reuse OE native `Righteousness` (`skill_faction_humans`); Necropolis should reuse OE native `Necromancy` (`skill_faction_undead`), with a warning that native Necromancy currently works on vanilla undead and may need eligibility changes for HoMM3 undead; Dungeon should reuse OE native `Triumvirate's Strength` (`skill_faction_dungeon`) and verify `homm3_dungeon` filters; Tower `Artifice` makes constructs gain Attack from hero Spell Power and Defense from hero Knowledge at 20/40/60%; Inferno `Gating` summons Imps to a target hex based on army strength via the Hive larvae-egg donor flow; Fortress `Swamp Tactics` applies enemy -1 Init / -1 Init and -1 Speed / -2 Init and -1 Speed by rank; Conflux `Summon Elementals` summons rank-dependent elemental types with quantity from Spell Power; Cove `Cannoneering` replaces Heroic Strike with a Cannon blast whose adjacent splash is 20/40/60% by rank and should use the HoMM3/HotA Cannon sprite through the Cove asset lane.

Shared assumptions: use `docs/homm3_ai_first_pass_design_principles.md`; keep target SIDs as `homm3_<faction>` and `homm3_<faction>_city`; use HoMM3 base/upgraded units as base/upg and treat `_upg_alt` as an editable OE alternate proposal; prefer HotA balance values over vanilla Complete values; convert probability effects into focus abilities; require an active/passive differentiator for every `_upg_alt`; preserve the Stronghold dwelling upgrade dust ladder T1..T7 = 10,20,30,40,50,75,100; clone complete gameplay surfaces, not just units; keep visible text matched to implemented behavior; mark every town layer/position as manual review.

Risk summary: Castle low-medium; Rampart medium; Tower high; Inferno high; Necropolis high; Dungeon medium-high; Fortress medium-high; Conflux high; Cove high. High-risk items are mostly native-heavy mechanics such as resurrection, double shots, no-retaliation, elemental immunity, post-battle necromancy, gating, teleport, petrify, death stare, Phoenix rebirth, Magic University, Aurora Borealis, Cannon, Shipyard/water behavior, Cove HotA assets, and town/RMG/session behaviors.

Do not use `dungeon` or `dungeon_raw` for HoMM3 Dungeon. The custom faction SID should be `homm3_dungeon` to avoid colliding with OE Dungeon and existing debug clone names.

---

## RAG_CHUNK: olden-era-playtest/190-glossary

## Glossary And Grep Terms

Project terms:

- Olden Era: Unity IL2CPP game being modded.
- HoMM3: Heroes of Might and Magic III Complete/HotA data source.
- VCMI: open-source Heroes III engine/data reference.
- BepInEx: plugin loader.
- Harmony: method patching library.
- Interop: generated managed assemblies for IL2CPP types.
- Core.zip: Olden Era JSON data archive.
- SID: string identifier used across JSON/config/code.

Faction/city SIDs:

- `homm3_stronghold`
- `homm3_stronghold_city`
- `homm3_fortress`
- `dungeon_raw`
- `dungeon`

Stronghold unit SIDs:

- `h3_goblin`, `h3_goblin_upg`, `h3_goblin_upg_alt`
- `h3_wolf_rider`, `h3_wolf_rider_upg`, `h3_wolf_rider_upg_alt`
- `h3_orc`, `h3_orc_upg`, `h3_orc_upg_alt`
- `h3_ogre`, `h3_ogre_upg`, `h3_ogre_upg_alt`
- `h3_roc`, `h3_roc_upg`, `h3_roc_upg_alt`
- `h3_cyclops`, `h3_cyclops_upg`, `h3_cyclops_upg_alt`
- `h3_behemoth`, `h3_behemoth_upg`, `h3_behemoth_upg_alt`

Common donor unit SIDs:

- `trogl`, `assassin`, `blade_dancer`, `minos`, `medusa`, `hydra`, `black_dragon`
- upgrade suffixes: `_upg`, `_upg_alt`

Important classes/files:

- `Plugin`
- `LauncherConfigReader`
- `ModActions`
- `AgentDebugLog`
- `EsquirePikemanVisuals`
- `Homm3ImportVisuals`
- `Homm3StrongholdTownMapBillboard`
- `Homm3StrongholdTownLayers`
- `Homm3StrongholdCityMusic`
- `Homm3HeroPortraitHook`
- `Homm3ImportPortraitSpriteCache`
- `DamageHistogramOverlay`
- `DamageDistribution`
- `RetaliationForecastFix`
- `SoFractionsCustomFactionAliasPatch`

Obfuscated or unstable symbols:

- `ejz.bdwu`
- `ejz.oez`
- `ejy`
- `dzk.bath`
- `buv`
- `but`
- `bwe`
- `buz`
- `buf`
- `fvh`
- `fvf`
- `fvj`
- `ckj.scf` / `ckj.hqu` (documented failed assumption for this build; not the working custom icon resolver)
- `czk.uvl`
- `cmc.sni`
- `BhHUDSession.ira`

Useful log fragments:

- `Loading [HeroesOE Offline Unlock`
- `Launcher config:`
- `build-session-snapshot`
- `SoFractions: aliasing UI asset lookup`
- `Homm3Import: town-style unit billboard applied`
- `diskTexture=`
- `HoMM3 Stronghold town billboard`
- `Homm3CustomUiIcon: supplied Sprite/Texture`
- `Homm3CustomUiIcon: surface replaced`
- `Homm3CustomUiIcon diag: ability`
- `BhHUDSession.ira`
- `MethodInfoStoreGeneric_GetComponents`
- `HEX_BLEND_INTO_TERRAIN_POSITION`
- `Homm3HeroPortrait: replaced`

Release build-tree diagnostic note:

- For the full release, `BhUIBuildingSession.Init(fbi)` and `BhBuildingView.tnw(fbi,dvw,int)` are the current build-tree anchors. Generated private UI getters can compile but throw at runtime; use raw IL2CPP field reads for `BhUIBuildingSession.root`, `buildingsUIs`, `arrowsCg`, `bzad`, and `bzae` when diagnosing invisible build-tree nodes.
- Full release `0.1.194` adds `city-session-build-snapshot` before `build-session-snapshot`; use both markers to tell whether the build-tree button path reaches `BhCityUISession` but not `BhUIBuildingSession`.

Release HoMM3 local-install check:

- May 5, 2026 investigation is captured in `docs/release_homm3_ownership_check.md`.
- Preferred release gate is explicit configured path, then GOG Complete product/root id `1207658787` plus marker files, then Steam HD Edition app id `297000` plus marker files.
- Do not extract or read HoMM3 asset archive contents for this check: avoid opening Complete `*.lod`, `*.snd`, `*.vid` and HD `*.pak` files. Presence and rough size markers are enough for a good-faith local-install ownership signal.
- Do not describe this as cryptographic DRM. It is a local install requirement that should disable HoMM3-derived content gracefully when missing.
