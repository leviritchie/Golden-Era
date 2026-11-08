# Mono Custom Biome, Minimap, Terrain Material, and Sound Static Evidence

Status: source-prepared/static-only. Runtime-unvalidated.

This dossier maps the old Mono demo's readable biome/minimap/terrain contracts onto the current Golden Era DiffableCs/ISIL output. It is meant to keep custom HoMM3 biome support native-friendly: mutate config/data contracts where possible, avoid renderer rewrites unless a later proof shows the data path is insufficient.

## Bottom line

The strongest static route for custom minimap biome colors/textures is still `SoMinimapConfig.bioms`, not a custom minimap renderer. Mono shows `Minimap` loads `configs/MinimapConfig` and passes that same config into the renderer. Current deobf still has `Hex.Session.World.SoMinimapConfig` with `bioms` at field offset `0x98`, and current `Minimap` still loads that config, stores it in `cimd`, then passes it into `bcv` render/update methods.

The strongest static route for custom terrain material support is `SoTerrainMaterial.biomes`, plus the current packed terrain renderer state in `beh`. Mono shows `SoTerrainMaterial.GetInstance()` loads `configs/TerrainMaterials`, and `GetTerrainMaterial()` creates the terrain shader material, sets `_TextureNodes`, and enables the terrain keyword. Current deobf keeps the same resource singleton shape (`kwf`) and terrain material creation shape (`kwg`), while `beh` consumes `SoTerrainMaterial.biomes` into packed texture arrays and shader globals.

Sound support is less complete. Current `EHeroSoundType` and `EAmbientSoundType` preserve named enum values for vanilla terrain classes. That is strong evidence for safe aliasing of custom biomes onto existing sound categories, but not proof of a new independent sound category pipeline.

## Mono source evidence

Mono decompile artifact: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_priority_custom_biome_minimap_decompiled.cs`.

Relevant Mono types:

| Mono type | Evidence |
|---|---|
| `Hex.Session.World.SoMinimapConfig` | `BiomSettings` has `tileID`, `Texture2D texture`, and `textureScale`; public `bioms` array is part of terrain config. |
| `Hex.Session.World.Minimap` | Constructor loads `Resources.Load<SoMinimapConfig>("configs/MinimapConfig")`, gets `ServiceLocator.GetInstance().Minimap`, creates targets, and calls `RenderBackgroundForAllViews(renderTargets, map, config)`. `Update()` calls `renderer.Render(..., config)`. |
| `Hex.Render.SoTerrainMaterial` | `Biome` has `name`, `tileCode`, splatmap, blend, texture count/mode, up to four texture slots, tilings, and heightmap scales. `GetInstance()` loads `Resources.Load<SoTerrainMaterial>("configs/TerrainMaterials")`. `GetTerrainMaterial()` creates `Shader.Find("Hex/TerrainMap")`, sets `_TextureNodes`, and enables `HEX_TERRAIN_TILE`. |
| `Hex.Configs.BiomesInfo` | `GetFractionForBiome` maps biome strings to faction strings with `"neutral"` as fallback. This is semantic evidence for biome-to-faction flavor classification only, not terrain rendering. |

## Current Golden Era evidence

Current deobf artifacts:

- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/World/Minimap.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/World/SoMinimapConfig.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Render/SoTerrainMaterial.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Configs/BiomesInfo.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Configs/EHeroSoundType.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Configs/EAmbientSoundType.cs`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/Session/World/Minimap.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/bcv.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/Render/SoTerrainMaterial.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/beh.txt`

Current shell and ISIL matches:

| Current surface | Claim | Evidence strength |
|---|---|---|
| `Hex.Session.World.SoMinimapConfig.BiomSettings` | Same minimap biome data contract survives: `tileID`, `texture`, `textureScale`. | Strong static: exact type and field shape. |
| `Hex.Session.World.SoMinimapConfig.bioms` | Current minimap config remains array-driven for biome minimap textures. | Strong static: current shell field offset `0x98`; renderer methods accept `SoMinimapConfig`. |
| `Hex.Session.World.Minimap.cimd` | Current `Minimap` stores loaded `SoMinimapConfig` in `cimd`. | Strong static: ISIL constructor loads `SoMinimapConfig` via resource path helper and stores to `cimd`. |
| `Hex.Session.World.Minimap.cimc` | Current `Minimap` stores minimap renderer object `bcv` in `cimc`. | Strong static: ISIL constructor obtains renderer from service locator backing field and stores to `cimc`. |
| `bcv.klp` | Current renderer creates render targets for a map. | Probable static: called from `Minimap..ctor` with `(Map, -1)` and result stored as `cimg`, matching Mono `CreateTargetsForMap(map)`. |
| `bcv.klt` | Current renderer renders background for all views. | Probable static: called from `Minimap..ctor` with `(bcr renderTargets, Map, SoMinimapConfig)`, matching Mono `RenderBackgroundForAllViews(renderTargets, map, config)`. |
| `bcv.kls` | Current renderer update path consumes render targets, sprite state, and `SoMinimapConfig`. | Probable static: called from `Minimap.bhmz()` with current `cimh`, `cimg`, `cimd`, matching Mono `Render(..., config)` update semantics. |
| `bcv.klu` / `bcv.lxx` | Current render-map-data path accepts `RenderTexture`, `MapData`, `RectInt`, `SoMinimapConfig`, `bool`. | Strong static for signature; runtime behavior still visual-unvalidated. |
| `Hex.Render.SoTerrainMaterial.kwf` | Current singleton loader still loads `configs/TerrainMaterials`. | Strong static: ISIL calls resource load into static `SoTerrainMaterial` backing field. |
| `Hex.Render.SoTerrainMaterial.kwg` | Current material getter creates terrain shader material, sets texture-node texture, enables terrain keyword. | Strong static: ISIL calls `Shader.Find`, `Material..ctor`, `Material.SetTexture`, `Material.EnableKeyword`. |
| `beh` packed terrain state | Current terrain renderer consumes `SoTerrainMaterial.biomes` and packs arrays/textures for shader globals. | Strong static for consumption path; exact method roles need focused body dossiers if editing this path. |

## Current symbol implications

Existing `GameSymbols.Minimap.RendererRenderMapData` using generated signature plus `lxx`/`klu` is structurally correct for identifying the render-map-data path. However, for adding custom biome minimap entries, the preferred hook point remains `SoMinimapConfig` mutation before render, because both Mono and current deobf prove render methods receive the config.

Existing `GameSymbols.TerrainMaterial` is broadly aligned with current evidence:

- `SoTerrainMaterial.kwf` maps to `GetInstance`.
- `SoTerrainMaterial.kwg` maps to `GetTerrainMaterial`.
- `beh` is the current terrain material/packing renderer class.
- Packed current fields such as `bshu`, `bshv`, `bshw`, `bshx`, `bsia`, `bsib`, and `bsic` are renderer internals, not authored biome data.

Treat direct `beh` field mutation as a higher-risk path. Prefer adding custom biome definitions to `SoTerrainMaterial.biomes` before `beh` builds its packed state.

## What this says about current custom biome code

`Homm3CustomBiomeMinimapHook` is directionally native-friendly because it mutates `SoMinimapConfig.bioms` and keeps the renderer intact. Its signature-based patch against `RenderTexture, MapData, RectInt, SoMinimapConfig, bool` is supported by current deobf signatures, but the more important design point is that the patch only uses that render call as a timing point to ensure the config is populated.

The hook should not grow broad renderer fallbacks. If a future patch renames `bcv.klu/lxx`, the stable shape to recover is:

- owner accepts/uses `SoMinimapConfig`,
- render-map-data method has `RenderTexture`, `MapData`, `RectInt`, `SoMinimapConfig`, `bool`,
- `Minimap` constructor loads `SoMinimapConfig` and passes it to render target/background creation.

## Remaining uncertainty

| Uncertainty | Why it remains | Recommended proof |
|---|---|---|
| Exact visual correctness of custom minimap textures | Static evidence proves data contract, not final pixel output. | Runtime screenshot of custom biome on minimap. |
| Whether terrain material custom biomes must be injected before a specific `beh` lifecycle method | Static evidence proves `beh` consumes `SoTerrainMaterial.biomes`, but not the exact earliest safe injection moment. | Runtime log around `SoTerrainMaterial.kwf`, `beh` prepare/build methods, and first map render. |
| Custom biome sound beyond vanilla aliases | Static evidence only proves current vanilla enum values. | Keep aliases to existing `EHeroSoundType`/`EAmbientSoundType` unless a later dossier proves extensible audio config arrays. |
| `BiomesInfo` gameplay relevance | Mono and current shells show biome-to-faction mapping, but no current consumer was mapped in this pass. | Xref `BiomesInfo.rqy` if faction-by-biome gameplay or UI flavor is needed. |

## Implementation guidance

Do:

- Keep custom minimap biome support as `SoMinimapConfig.bioms` extension.
- Keep custom terrain material support as `SoTerrainMaterial.biomes` extension where possible.
- Alias custom biome sounds to existing `EHeroSoundType` and `EAmbientSoundType` values unless a later sound config dossier proves new entries are safe.
- Centralize obfuscated names in `GameSymbols`.

Do not:

- Replace or fork the minimap renderer just to add custom biome textures.
- Mutate packed `beh` renderer arrays unless the authored `SoTerrainMaterial.biomes` path proves insufficient.
- Treat this dossier as runtime proof. It is static evidence only.
