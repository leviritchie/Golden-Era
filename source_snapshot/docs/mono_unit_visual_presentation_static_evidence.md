# Mono-to-Deobf Unit Visual Presentation Evidence

Status: source-prepared/static-only. This document is not runtime proof.

## Why this exists

Existing visual replacement code has historically used a mix of bundle prefab swaps, narrow hooks, broad `ResManager` interception, and renderer-layer copying. Mono gives a cleaner picture of the stable asset contract: `UnitViewConfig` owns the unit visual paths and map prefab cache.

## Mono reference shape

Focused Mono extract: `experiments/cpp2il_readable_csharp/samples/latest_refresh/mono_priority_visual_presentation_decompiled.cs`.

Mono `Hex.Configs.UnitViewConfig` contains:

- `float scale`
- `string mesh`
- `string mapMesh`
- `string[] meshVariants`
- ability view arrays
- private cached `GameObject prefab`

Mono `UnitViewConfig.GetMapPrefab()` builds `units/{mapMesh}` and calls `ResManager.Get<GameObject>(text)`, caching the result.

Mono `UnitViewConfig.GetMeshes()` calls `MapMagicVision.GetMeshData(GetMapPrefab())`.

## Current deobf shape

Current `Hex.Configs.UnitViewConfig` survives by name and retains the same core fields:

- `scale` offset `0x28`
- `mesh` offset `0x48`
- `mapMesh` offset `0x50`
- `meshVariants` offset `0x60`
- private cached `GameObject bxuw` offset `0x110`

Current method mapping by shape:

- Mono `GetAbility(AbilityID)` -> current `sek(AbilityID)`
- Mono `GetAbility(EAbilityType,int)` -> current `sel(EAbilityType,int)`
- Mono `GetViewArrayByType(EAbilityType)` -> current `sem(EAbilityType)`
- Mono `CreateStubAbilityArray(EAbilityType,int)` -> current `sen(EAbilityType,int)`
- Mono `GetMapPrefab()` -> current `seo()`

The attempted dossier for `UnitViewConfig.sec` failed because `sec` is not current for this refresh. `GameSymbols.UnitViewConfig.MapMeshLoader` should be updated to prefer `seo`, with `sec` treated as old evidence only.

## Native-friendly implications

For adventure-map unit prefab replacement, `UnitViewConfig.mapMesh` plus current `UnitViewConfig.seo()` is the strongest stable route. It is narrower and more native-friendly than a global `ResManager.Get<GameObject>` prefix/postfix.

For battle unit visual replacement, use the battle drawer/spawn surfaces only after focused current dossiers identify the exact drawer initialization method. Do not infer battle spawning from Mono `UnitViewConfig.GetMapPrefab()`, because that method is explicitly map-prefab oriented.

For renderer/layer fixes, prefer copying presentation state from a known donor renderer at the point where a current visual controller has already produced the object. Avoid wholesale transform-tree copying; existing source comments correctly identify that as dangerous because native locals are parent-relative.

## Existing mod implications

`EsquirePikemanVisuals.cs` already documents that the broad `ResManager` prefix broke `Map.Init`, and current static evidence supports retiring broad resource interception in favor of `UnitViewConfig.seo()` for map visuals and focused battle drawer hooks for battle visuals.

`EsquireBattleVisualPresentation.cs` contains useful renderer-copy helpers, but those helpers are presentation adapters, not surface proof. The surface proof should come from current `UnitViewConfig`/drawer/map-squad dossiers, then the adapter can copy layers, sorting, and rendering-layer masks at that specific point.

`Homm3MapSquadVisualControllerHook.cs` is closer to the current deobf route than the old `BhMapSquad` path because it resolves `ezp`/`fdh`/`ctr` and validates `UnitViewConfig` ownership.

## Gaps before implementation changes

- Update `GameSymbols.UnitViewConfig.MapMeshLoader` from stale `sec` to current `seo`, or carry both with comments that `seo` is current-proven and `sec` is historical.
- Build focused dossiers for current battle drawer initialization candidates before changing battle visual swap points.
- Build focused dossiers for current `ezp` visibility/effect methods before changing map-squad visibility behavior.

## Evidence boundary

Static evidence proves the UnitViewConfig field/method shape and identifies `seo()` as the current map-prefab getter. It does not prove Unity object lifetime, asset-bundle load order, battle drawer instantiation timing, or visibility/fog state at runtime.
