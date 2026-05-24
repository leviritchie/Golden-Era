# Olden Era Mod Helper

Last updated: 2026-05-24.

This document is a practical architecture and failure guide for modding
Heroes of Might & Magic: Olden Era. It is based on repeated work against the
Steam IL2CPP build with BepInEx, Harmony patches, `Core.zip` data overlays,
custom Unity bundles, and HoMM3-derived assets.

The exact obfuscated names in this document are examples from recent builds.
Treat them as unstable. The durable lesson is the shape of the game systems,
the separation between data and runtime surfaces, and the crash patterns.

## 1. High-Level Mental Model

Olden Era is a Unity IL2CPP game. Most gameplay and UI code is compiled into
native code inside `GameAssembly.dll`, with type and method metadata in the
IL2CPP global metadata file. Mod code normally interacts with the game through:

- BepInEx 6 IL2CPP, which loads managed plugins into the Unity process.
- Generated interop assemblies under `BepInEx/interop`, which expose IL2CPP
  types and methods as managed wrappers.
- Harmony or HarmonyX patches, which redirect or augment IL2CPP wrapper
  methods.
- JSON game data in `HeroesOldenEra_Data/StreamingAssets/Core.zip`.
- Plugin-side files such as custom textures, portraits, AssetBundles,
  reference packs, and config files.

The important point is that Olden Era is not a single data table. A feature can
need all of these at once:

- Core data row.
- Localization token.
- Serialized Unity UI asset support.
- Runtime lookup or aliasing hook.
- Deployed texture or bundle.
- Native dictionary membership.
- A current obfuscated method/field map.

If one layer is missing, the symptom often appears in a different layer. For
example, a custom faction can exist in `DB/fractions/*.json` but still fail in
the faction selector because a serialized Unity `SoFractions` asset does not
know that faction. A custom unit can have correct logic rows but still crash
combat if its UnitView attack arrays do not match its logic arrays. A map can
generate successfully and still fail at map load because terrain renderer
dictionaries were not extended for the custom tile code.

## 2. Main Runtime Layers

### Unity Player And IL2CPP

The shipped game code is native IL2CPP. The important files are:

- `HeroesOldenEra.exe`.
- `GameAssembly.dll`.
- `HeroesOldenEra_Data/il2cpp_data/Metadata/global-metadata.dat`.
- Unity data files and built-in assets under `HeroesOldenEra_Data`.

After a Steam hotfix, `BepInEx/interop/*.dll` may be stale even when the game
binary changed. If a patch suddenly misses or crashes after an update, validate
against current `GameAssembly.dll` plus current metadata, not only the interop
DLL already sitting in `BepInEx/interop`.

### BepInEx And Plugin Load

A BepInEx IL2CPP plugin runs after the Unity process starts and BepInEx loads.
Typical plugin startup does this:

- Read configuration.
- Register any IL2CPP-injected component types.
- Register Harmony patches.
- Register manual/dynamic patch sites whose names or signatures are unstable.
- Load plugin-side assets, indexes, or manifests.
- Fail closed if a required patch surface is unavailable.

For fragile runtime work, explicit startup failure is better than a silent
fallback. If an obfuscated method moved, a warning-only miss can leave the game
half-modded: custom data enters native systems, but the hook that makes it safe
does not run.

### Generated Interop

BepInEx generates managed wrappers for IL2CPP types. These wrappers are useful,
but they are not always a perfect source of truth:

- Properties may wrap native fields that `Type.GetField()` cannot see.
- Old interop can remain after `GameAssembly.dll` changes.
- Some generic reflection and component APIs fail inside IL2CPP bridges.
- Method names are obfuscated and build-specific.

Prefer matching by signature, call site, stack trace, and native disassembly
when exact names drift. Keep discovered names in a central registry such as a
`GameSymbols` file instead of scattering raw strings through hook code.

### Harmony Patches

Harmony patches are the main extension mechanism. There are two broad classes:

- Attribute-discovered patches for stable, direct surfaces.
- Manual patches for dynamic or fragile surfaces.

Do not broadly scan whole IL2CPP assemblies at startup unless there is no other
route. Broad scans have caused launch crashes in constructor inspection and
trampoline spam. Prefer known target type lists, declared-only members,
signature checks, and capped diagnostics.

## 3. Core.zip Data Architecture

`Core.zip` is the central data archive. It contains JSON under `DB/**` and
localization under `Lang/**`. The game deserializes many of these rows into
dictionaries keyed by ids. Duplicate ids usually crash hard.

Common data areas include:

- `DB/data.json`: available factions and global registration lists.
- `DB/fractions/*.json`: faction identity, icon keys, city names, biome.
- `DB/fractions_laws/**`: faction law rows and law tables.
- `DB/objects_logic/cities/*.json`: city logic, build tree, hire rows,
  building costs, building prerequisites, icon keys.
- `DB/map/objects/4_interactables.json`: map object config rows for towns,
  dwellings, resource objects, and interactables.
- `DB/objects_logic/hires/barracks.json`: external dwelling hire logic.
- `DB/squads/**`: starting and random squad templates.
- `DB/heroes/**`: hero configs.
- `DB/heroes_specializations/**`: hero specialization configs.
- `DB/heroes_skills/**`: hero skills, subskills, and skill tables.
- `DB/units/units_logics/**`: unit gameplay rows.
- `DB/units/units_views/**`: unit UI, attack view, icon, prefab, and
  presentation rows.
- `DB/biomes_info.json`, `DB/map/tiles/tiles.json`,
  `generator/generator_config.json`, and related terrain files.
- `Lang/<locale>/texts/*.json`: visible text tokens.

For a custom faction, a faction row alone is not enough. A working faction
needs matching rows for city, heroes, hero skills, laws, squads, units,
UnitViews, map objects, dwellings, localization, UI routing, and deployed
assets.

### Data Shape Matters

Olden Era native code expects certain JSON arrays to line up. If unit logic has
an alternative attack but UnitView has no corresponding alternative attack view,
combat initialization can throw inside native ability setup. This kind of
failure may not mention the JSON file directly.

The safest rule is: copy complete native data shapes, then replace ids and
payloads deliberately. Do not delete empty-looking buckets just because the
custom unit does not use them. If native rows carry `defaultAttacks`,
`alternativeAttacks`, `counterAttacks`, and `abilities`, keep those buckets in
both logic and view rows unless native evidence proves a smaller shape is safe.

### Core.zip Is A Live Artifact

Source generator output is not proof that the game is using it. Always inspect
the deployed `Core.zip` when debugging:

- Steam updates can replace `Core.zip`.
- A dry-run can say a generator would fix something while the live archive is
  still stale.
- Loose `Lang` files may not be the text source for a surface if the game reads
  `Lang/**` inside `Core.zip`.
- Backup `.zip` files placed next to `Core.zip` can be ingested by the loader
  as another archive and cause duplicate-key errors.

Keep backups outside the loader scan path, or name them so they do not look like
loadable Core archives.

## 4. Serialized Unity Assets And Native Registries

Not every visible thing comes from JSON. Many UI and presentation surfaces are
serialized Unity assets. These assets can contain dictionaries, ScriptableObject
lists, or prefab references that do not know about modded ids.

Examples:

- Faction selector rows may use a serialized `SoFractions` or lobby asset.
- UI sprite lookup can require a runtime resolver for plugin PNGs.
- Unit preview factories can load prefabs directly instead of going through a
  general resource manager.
- Battle queue portraits and selected-unit HUDs may use native dictionaries
  keyed by UnitView ids.

This is why a JSON-only fix often fails. If the serialized asset has no custom
key, you either need a data row that points at a native-safe donor key or a
runtime hook that intercepts only the relevant lookup.

## 5. Asset And Visual Architecture

A custom visual feature usually has three parts:

- A native-safe donor shell that lets the game instantiate something it already
  understands.
- A mod-owned visual payload, often an AssetBundle, PNG sequence, or generated
  material.
- A runtime replacement hook that hides or redirects the native donor visual and
  shows the custom visual.

For HoMM3 unit imports, the key split is:

- Core UnitView `mesh` and often battle construction fields stay native-safe.
- `homm3_import.json` maps game-facing custom SIDs to bundle assets,
  `homm3_lab` source folders, map/battle payloads, and donor shell paths.
- `homm3_bundles/custom_units_*` contains Unity prefab and material assets.
- `homm3_portraits/` and `homm3_portrait_anims/` drive UI portraits and preview
  animations.
- `homm3_lab/<labSid>/extracted_battle` and `extracted_map` contain decoded
  source frames and sidecars.

Battle, adventure-map units, town billboards, unit portraits, hero portraits,
unit detail previews, recruitment cards, timeline portraits, sound effects, and
town screens are independent surfaces. Fixing one does not prove the others.

### Adventure-Map Billboards

A reliable adventure-map billboard path is:

- Instantiate or reuse a native map shell.
- Add a flat billboard quad under that shell.
- Use a sanitized `Hex/Lit` material, not a plain UI sprite material.
- Copy only safe native renderer flags.
- Bind the custom texture into the shader slots the game actually samples.
- Strip unsafe donor material state such as terrain blending or vertex
  displacement.
- Verify fog, black shroud, hover outline, occlusion, shadows, and texture
  identity in-game.

Bare `Shader.Find("Hex/Lit")` materials can render invisible because native
donor state matters. Directly cloning a town/building material can also leak
terrain, emission, PBR, or wave state into a single upright quad.

### Town Screens

Town screens are not just a background image. They include:

- A city scene or donor city scene.
- A custom backdrop plate.
- Building layers.
- Building layer placement data.
- Building SID to visual layer mapping.
- Build-tree button icons.
- Building hover/tooltip art.
- Recruitment and upgrade screens.
- Town music.
- City HUD icon and map town billboard.

The visual building layers are usually not click targets. Moving native
`BhBuildingView` roots or construction UI transforms onto the background can
break the build tree while making blue hit rectangles appear over the town.
If click behavior is wrong, trace native screen state or button routing instead
of moving visual layers.

## 6. Configuration And Feature Gates

Config usually merges more than one source. In the observed mod stack, config is
read from a game-root file and from `BepInEx/plugins/OfflineUnlockMod/config.json`.
Only present keys override defaults.

Feature gates matter for debugging:

- A hook can be compiled but not registered.
- A deployed DLL can be current while the live config disables the feature.
- A config gate can mask a code regression.
- A hook can be enabled without the payload files it requires.

When bisecting, capture the config snapshot printed at plugin load and compare
it against the deployed file, not only the source file.

## 7. Logs And Evidence Order

Use the right log for the failure type:

- `BepInEx/LogOutput.log`: plugin startup, patch registration, config state,
  managed warning lines, diagnostics.
- Unity `Player.log`: map-load, battle-init, scene, native loader, and many
  fatal Unity/IL2CPP exceptions.
- `BepInEx/ErrorLog.log`: native or trampoline crash stacks when the process
  dies before normal managed logging captures a useful exception.
- Deployed `Core.zip`: actual data the game consumed.
- Deployed plugin folder: actual DLL and asset payload.
- Current `GameAssembly.dll` and metadata: actual binary being executed.

For map-load and battle-init failures, `Player.log` is often more decisive than
`LogOutput.log`. `LogOutput.log` can show healthy hook registration while
`Player.log` contains the real exception.

## 8. Recommended Modding Workflow

1. Define the layer you are changing.
   Decide whether the feature is data, runtime hook, asset payload, UI repair,
   or a combination.

2. Start from native or existing working data.
   Copy complete native shapes before changing ids. Preserve buckets, arrays,
   and required fields.

3. Keep custom ids explicit.
   Avoid relying on visible names, sprite names, or pooled UI state to infer the
   current unit, hero, faction, or dwelling.

4. Use native-safe donor shells deliberately.
   A donor shell is fine when native code requires one. A donor reverse lookup
   without context is dangerous.

5. Validate generated data before runtime testing.
   Check the packed `Core.zip`, not just generator source output.

6. Deploy all layers together.
   DLL, config, `Core.zip`, bundles, portraits, manifests, sounds, and reference
   assets are separate deployment surfaces.

7. Read logs before patching.
   Root cause first. Avoid adding fallbacks just to quiet a symptom.

8. Centralize obfuscated names.
   Put hotfix-sensitive names in a registry and update that registry after each
   patch day.

9. Fail closed.
   If a required hook or symbol is missing, stop that feature or leave native
   behavior alone. Do not silently apply broad fallback behavior.

## 9. Frequent Pitfalls And Crash Patterns

### Stale Deployed Core.zip

Symptom:

- Source code or generator output looks fixed.
- Live game still crashes or shows old text/data.
- Duplicate key or missing row errors mention old ids.

Likely cause:

- The live `Core.zip` was not updated, was replaced by Steam, or was overwritten
  by a later overlay stage.

Safer route:

- Inspect the exact member inside the live `Core.zip`.
- Verify the relevant JSON row and localization token.
- Reapply the generator or overlay to the live archive.

### Backup Archive Loaded As Core Data

Symptom:

- Startup or map load throws duplicate key errors unrelated to your latest
  changes.
- Errors mention common keys such as icons or hub assets.

Likely cause:

- A backup `.zip` was left next to `Core.zip` in a folder the game scans.

Safer route:

- Store backups in a subfolder or use a non-loadable suffix such as
  `Core.zip.backup-*`.

### Stale IL2CPP Interop After A Hotfix

Symptom:

- Existing patches compile but fail at runtime.
- Wrapper names appear unchanged while native behavior changed.
- `LogOutput.log` ends without a useful managed exception.

Likely cause:

- `BepInEx/interop` did not reflect the current `GameAssembly.dll`.

Safer route:

- Regenerate or inspect against current `GameAssembly.dll` and
  `global-metadata.dat`.
- Confirm with native dump, metadata token comparison, stack traces, or
  disassembly.

### Obfuscated Name Drift

Symptom:

- A patch silently stops registering.
- A hook binds to the wrong overload.
- A UI or battle patch runs on an older-looking method but no visible surface
  changes.

Likely cause:

- Obfuscated method or field names changed.

Safer route:

- Match by method shape, parameter types, call flow, and stack trace.
- Centralize symbol hints in one registry.
- Keep old aliases only as explicit fallbacks with comments.

### Broad Reflection Scan Crash

Symptom:

- Crash or CLR failure during plugin load.
- Stack includes constructor or parameter reflection.
- Many unrelated IL2CPP types are being inspected.

Likely cause:

- A broad `Assembly.GetTypes()` plus constructor or method-shape probe crossed
  invalid IL2CPP wrapper metadata.

Safer route:

- Patch known candidate types.
- Use declared-only members.
- Cache reflection metadata.
- Avoid scanning every type in hot or startup paths.

### Generic Unity Component Lookup Failure

Symptom:

- `MissingMethodException` or IL2CPP bridge error involving generic component
  lookup or `ReadOnlySpan`.
- Failure happens inside visual helper code.

Likely cause:

- `GameObject.GetComponent(string)` or broad generic component APIs are unsafe
  in that IL2CPP context.

Safer route:

- Use typed, known components where possible.
- Traverse children explicitly and cast through IL2CPP-safe APIs.
- Remove nonessential cleanup scans from hot paths.

### Wrong Overload Patched

Symptom:

- Hook registers but does not affect visible behavior.
- A method name exists multiple times with different argument shapes.
- Finalizer suppresses the wrong exception or corrupts native state.

Likely cause:

- Obfuscated names were matched by name or arity instead of exact signature.

Safer route:

- Match exact parameter types.
- Log one capped "hook fired" line for important surfaces.
- Avoid broad postfixes on every same-name overload.

### Donor Reverse Lookup Without Context

Symptom:

- One custom faction shows another faction's art.
- Dwellings or map objects switch to a previously seen custom faction.
- A fix works when only one custom faction exists but fails when two share a
  donor prefix.

Likely cause:

- Code mapped donor SID back to custom SID without exact context.

Safer route:

- Allow `custom SID -> donor SID` when native code needs a shell.
- Require exact context for `donor SID -> custom SID`: saved original SID, live
  hire payload, current unit/hero config, or current map-object payload.
- Refuse ambiguous donor-only reverse lookups.

### Shared ObjectConfig.id Mutation

Symptom:

- Map load fails with `ArgumentException: An item with the same key has already
  been added`.
- The duplicate key is a custom direct map object such as a custom barracks id.

Likely cause:

- Runtime code rewrote a shared donor `ObjectConfig.id` to a direct custom id
  while the direct custom row also existed in the same config array.

Safer route:

- Keep donor config ids stable.
- Resolve visuals per instance.
- If tooltip text needs repair, stamp only the live per-instance config field,
  not the shared global object row.

### Duplicate Skill Or Subskill Ids

Symptom:

- Map/session load fails with duplicate key errors for `sub_skill_*`.
- A custom skill appears to work in JSON but crashes during skill table load.

Likely cause:

- Donor `subSkills` were shallow-cloned, repeated across ranks, or reused from
  a native faction.

Safer route:

- Give every custom subskill a globally unique id.
- Clone the whole graph if using donor skill mechanics.
- Validate the live `Core.zip` skill rows.

### Custom Biome Treated As One Data Row

Symptom:

- Map generation completes but map load fails.
- `Player.log` shows `KeyNotFoundException` for tile ids such as `8` or `17`.
- Logs mention missing water for a biome.
- Combat terrain has placeholder arrow/dot obstacles.

Likely cause:

- Only `DB/biomes_info.json` or a faction `biome` field was changed.

Safer route:

- Custom biomes need coordinated rows for map tiles, waters, generator config,
  environment assets, arena info, arena views, obstruction models, sound rows,
  runtime material registration, and sidecar textures.
- Keep custom biome work generator-owned.
- Validate the packed archive.

### Terrain Renderer Refresh Too Early

Symptom:

- Black terrain.
- `RenderTextureDesc width must be greater than zero`.
- Terrain dictionary lookup succeeds but material rebuild crashes.

Likely cause:

- Renderer material-array or texture rebuild methods were called from a
  map-build prefix before render textures had nonzero dimensions.

Safer route:

- Seed tile-code lookup early enough for map build.
- Refresh packed terrain materials through the constructor-used safe path after
  terrain fields are initialized.
- Do not revive unsafe render-texture allocation methods as a quick fix.

### Custom Biome Registration Disabled

Symptom:

- Live `Core.zip` contains custom tile ids, but map load fails.
- Failures point to unknown or missing terrain dictionary keys.

Likely cause:

- Runtime custom biome registration was disabled while Core data still uses
  custom tile codes.

Safer route:

- Keep registration enabled when Core has custom tile ids.
- If disabling a hook for bisection, also use Core data that does not require
  that hook.

### UnitView Logic/View Array Mismatch

Symptom:

- Battle load hangs or throws in a native ability initializer such as
  `dxr.Init(ecx)`.
- Diagnostics identify a specific custom unit SID.

Likely cause:

- Logic attack or ability arrays do not match UnitView attack or ability view
  arrays.

Safer route:

- Validate `defaultAttacks`, `alternativeAttacks`, `counterAttacks`, and
  `abilities` across logic and view rows.
- Keep native-shaped buckets even when some actions are disabled.
- Inspect the live `Core.zip` row before changing runtime hooks.

### Stale Donor Conditional Passives

Symptom:

- AI end turn or battle startup hangs.
- `Player.log` shows a native stat merge NRE such as `UnitStat.scz`.
- The failing squad contains custom units cloned from a donor faction.

Likely cause:

- Donor conditional passives still refer to donor tags or donor unit families
  after custom tag normalization.

Safer route:

- Strip or rewrite stale donor conditional passives in the generator.
- Do not add fake donor tags to custom units just to satisfy old conditions.

### Invalid Resource Names

Symptom:

- City costs, unit costs, or generation rows fail or behave oddly.

Likely cause:

- HoMM3 resource names were copied directly but Olden Era uses different ids.
  Examples include `gemstones` instead of `gems`, and project-specific folding
  of sulfur into another resource.

Safer route:

- Normalize resources in generator code.
- Validate resource ids against live Core examples.

### Direct Custom Prefab Paths In UnitView

Symptom:

- Combat or preview construction crashes before replacement hooks can run.
- Missing native asset path errors appear for custom `homm3_import/*` fields.

Likely cause:

- Release UnitView `mesh` or related fields were pointed directly at custom
  import paths where native code expects a built-in prefab path.

Safer route:

- Keep UnitView native-safe donor prefab fields.
- Store custom visual identity in import manifests and bundles.
- Replace or hide the donor visual after native construction succeeds.

### Projectile False Leads

Symptom:

- A map-load failure is blamed on projectile hooks because a projectile feature
  gate is enabled.

Likely cause:

- Recency bias. Projectile code may be unrelated.

Safer route:

- Read `Player.log`, deployed config, deployed `Core.zip`, map-object hooks,
  custom biome rows, and random-hire/dwelling state first.
- Treat projectile as primary only when logs, code drift, or a clean bisection
  implicate projectile hooks.

### Custom Projectile Instability

Symptom:

- Ranged attack visuals fail, no projectile appears, or combat action effects
  desync.

Likely cause:

- Custom projectile prefab plumbing is less stable than native projectile rows.

Safer route:

- Prefer a stable native projectile with adjusted trajectory, speed, and sound
  when it communicates the intended behavior.
- Only retrace custom projectile attachment when that is the task.

### City UI Panel Hidden Behind Custom Backdrop

Symptom:

- Town backdrop and layers are visible.
- Build tree, recruitment, or upgrade UI is clickable or active but invisible.

Likely cause:

- Panel canvas sorting order or screen-local body fields are hidden behind the
  custom town backdrop.

Safer route:

- Lift only the active named panel canvas such as `BUILDING VIEW PANEL`,
  `HIRE VIEW PANEL`, or `UPGRADE UNIT PANEL`.
- Keep navigation above those panels.
- Do not recursively activate every child under the panel; inactive templates
  can become visible and break nearby screens.

### CityHireView Broad Patch Loop

Symptom:

- Main menu or loading logs spam native-to-managed trampoline
  `NullReferenceException`.
- Stack mentions broad city hire shell methods.

Likely cause:

- A generic patch was attached to hire shell methods that can run before a real
  hire city view exists.

Safer route:

- Patch a narrower, valid hire-screen show/init path.
- Trace the click path from the city special view or hire increment item before
  adding another hook.

### BhButtonExitHud Town Back Workaround

Symptom:

- A nonworking HUD-style button sits over the town leave button.
- Leave-town hover works but click does not.

Likely cause:

- Old code forced an exit HUD arrow visible/clickable for town back behavior.

Safer route:

- Keep town back handling on screen-local paths.
- Let the native town leave button remain native.
- Route only exact known dead BackClock controls if that specific path is
  proven broken.

### GenericButton Path Interception

Symptom:

- The first construction click is swallowed.
- Upgrade, buy, recruit, or apply buttons stop working.

Likely cause:

- A broad generic-button hook treated a shared UI hierarchy path as a back or
  close button.

Safer route:

- Prove identity through exact close/cross fields or explicit child text.
- Reject Build, Construct, Buy, Upgrade, Hire, Recruit, Apply, and OK actions.
- Do not broaden generic-button hooks to all town buttons.

### Broad Image.sprite Hook

Symptom:

- Many unrelated portraits change to the same custom art.
- Result screens or timeline rows show wrong hero/unit portraits.

Likely cause:

- A global image setter hook or descendant image scan was too broad.

Safer route:

- Patch the owning UI component or exact serialized image field.
- Gate by current bound unit/hero/faction.
- Avoid scanning every descendant `Image` under a complex pooled panel.

### Sticky overrideSprite

Symptom:

- A custom portrait or card persists after native code changes `sprite`.
- Hovering other factions or units still shows old custom art.

Likely cause:

- `Image.overrideSprite` was set and not cleared on pooled UI rows.

Safer route:

- Prefer writing only the field native actually uses.
- Clear custom `overrideSprite` when the current resolved SID is not custom.
- Treat pooled UI elements as stateful.

### Preview Hooks Forced On

Symptom:

- Detail preview NREs appear even when preview feature config is false.
- Recruitment or unit preview screens break after a release hotfix.

Likely cause:

- Preview hooks were registered despite config disabling them, or an old wrapper
  path was assumed current.

Safer route:

- Respect preview feature gates.
- Keep detail preview, recruitment preview, and shared preview factories
  separate.
- Re-map current wrapper fields before re-enabling a preview hook.

### Camera Enumeration Crash

Symptom:

- Preview open crashes inside `UnityEngine.Camera.get_allCameras()` or a
  similar Unity camera enumeration path.

Likely cause:

- Camera enumeration was called from an IL2CPP UI postfix.

Safer route:

- Use exact traced UI RectTransform members or conservative static placement.
- Avoid `Camera.allCameras` in fragile UI hooks.

### RawImage Reuse Leak

Symptom:

- A custom unit preview leaks into later enemy or vanilla previews.
- Preview rects drift or become corner-offset after multiple opens.

Likely cause:

- The hook mutated a native `RawImage` instance reused by pooled preview UI.

Safer route:

- Use owned overlay objects with clear names.
- Remove owned overlays on rebind.
- Avoid changing native preview rects or textures unless the surface is proven
  owned by the mod.

### Hero Portrait Icon Field Only

Symptom:

- Hero JSON has a custom icon key, but UI still shows placeholder art.

Likely cause:

- The native sprite registry or UI surface does not resolve arbitrary plugin
  PNG keys.

Safer route:

- Add runtime sprite resolver support for known custom keys.
- Patch specific hero portrait surfaces or central icon lookup surfaces.
- Verify deployed portrait PNGs and the current key flowing through the UI.

### Unit Detail Preview Uses Wrong Surface

Symptom:

- Combat ability icons are correct, but preview window icons or ability rows
  show placeholders.

Likely cause:

- Preview/detail UI uses different binders from battle action UI.

Safer route:

- Trace preview/detail bind methods separately.
- Centralize their obfuscated names.
- Do not assume the combat action-bar fix covers preview windows.

### Map Billboard Material Corruption

Symptom:

- Town or unit billboard is visible but warped, bright, stretched, wavy, or has
  corrupted lower rows.

Likely cause:

- Donor `Hex/Lit` material carried terrain blend, emission, tiling, offset,
  shadow, occlusion, or vertex displacement state.

Safer route:

- Sanitize cloned materials.
- Reset texture slots and scale/offset.
- Strip terrain blend and wave flags.
- Disable receive shadows or dynamic occlusion when the upright quad interacts
  badly with terrain.

### Town Layer Misalignment

Symptom:

- Building layers are offset, too large, or appear as black/opaque blocks.

Likely cause:

- Source coordinates, padded runtime plate size, and `positions.json` do not
  match.

Safer route:

- Keep a clear source coordinate contract.
- Generate transparent layers, not opaque crops.
- Preserve top-left anchoring where the source town screen uses black padding.
- Validate base and upgrade row dimensions separately.

### Build Tree Icons Repeat

Symptom:

- Many build buttons show the same building icon.

Likely cause:

- Missing building icon keys were mapped to a generic layer crop or guessed
  visually.

Safer route:

- Extract the source hall/build-tree icon DEF or JSON frame map.
- Create explicit `Build_*` to icon-frame mappings.
- Fail validation on missing non-dwelling icons instead of falling back to a
  repeated icon.

### Custom Dwelling Text With Correct Art

Symptom:

- External dwelling billboard art is correct, but tooltip text is donor text.

Likely cause:

- The visible art was resolved per instance, but the tooltip/localization path
  still reads donor config or donor `sidConfig`.

Safer route:

- Repair tooltip identity per instance after exact payload resolution.
- Do not mutate shared donor rows globally.
- Keep direct custom dwelling ids, hire logic ids, billboard art ids, and text
  tokens aligned by tier.

### Missing Asset Assumption

Symptom:

- A UI surface shows a placeholder.
- First instinct is to add more PNGs.

Likely cause:

- The art exists, but the key, resolver, overlay layer, or placeholder overlay
  is wrong.

Safer route:

- Check the exact live key flowing through the binder.
- Check whether random/shadow placeholder overlays sit above the portrait.
- Check whether the sprite resolver supports that key.
- Check deployed plugin payload before changing source art.

### Player-Facing Text Describes Implementation Debt

Symptom:

- Faction, unit, or ability text says "placeholder", "source trait",
  "not implemented", "data pass", or similar.

Likely cause:

- Internal generator/debt text leaked into localization.

Safer route:

- Keep implementation notes in docs or `xHomm3ProductionDebt` metadata.
- Player-facing localization should describe actual shipped behavior.
- Validate the final post-override `Lang` member inside live `Core.zip`.

### Patch-Day CSV Treated As Truth

Symptom:

- A visual method-name diff exists but the wrong hook gets fixed.

Likely cause:

- Name comparison was treated as authoritative instead of a routing aid.

Safer route:

- Use name diffs to find candidates.
- Confirm with current `GameAssembly.dll`, metadata, disassembly, and
  `GameSymbols` checks.
- Fix actual bound surfaces first.

## 10. Practical Debugging Checklist

When a modded feature fails, answer these in order:

1. What exact live artifact is the game using?
   Check deployed DLL, config, `Core.zip`, and plugin assets.

2. Which layer is failing?
   Data load, UI sprite resolution, map object construction, battle init,
   resource loading, material rendering, or click routing?

3. Which log has the fatal evidence?
   Use `Player.log` and `ErrorLog.log`, not only `LogOutput.log`.

4. Is the custom id entering a native dictionary that lacks it?
   If yes, use a native-safe donor alias only for that native call and restore
   state immediately.

5. Is a donor id being reverse-mapped without exact context?
   If yes, stop and redesign. This is a common cross-faction bug.

6. Are logic rows and view rows shape-compatible?
   Check arrays and corresponding localization/icon rows.

7. Are serialized Unity assets involved?
   JSON icon keys do not automatically teach Unity UI assets about plugin PNGs.

8. Did an obfuscated symbol drift?
   Re-anchor by signature, stack, call site, and current binary.

9. Is the fix a fallback?
   If the fallback hides a missing data contract, it will likely cause a later
   crash somewhere else.

10. Can the failure be validated without launching the whole game?
    Prefer packed archive inspection, validator scripts, static tracing, and
    targeted log checks before broad runtime probes.

## 11. Stable Rules Of Thumb

- Core data, runtime hooks, and asset deployment are separate.
- `Core.zip` is the final truth for data; source generator output is not enough.
- `GameAssembly.dll` plus metadata is the final truth for patch surfaces; stale
  interop is not enough.
- Player-facing UI often uses serialized Unity assets, not only JSON.
- Donor shells are acceptable; donor reverse lookup without exact context is
  not.
- Pooled UI elements retain state. Clear what you set.
- Broad reflection, broad image scans, and broad generic button hooks are
  common crash sources.
- Custom biomes are full terrain pipelines, not faction-row strings.
- Battle/map/preview/portrait/town/SFX surfaces are independent.
- Prefer fail-closed behavior over silent compatibility fallbacks.
