# Mono-to-Deobf Battle Visual Drawer and Spawn Evidence

Status: source-prepared/static-only. This document is not runtime proof.

## Why this exists

Existing custom unit visual code has accumulated several candidate type names and reflection paths. The Mono build helps identify the stable high-level contract, while current deobf shows which obfuscated surfaces actually own battle unit visual state in the current build.

## Current strongest surfaces

### `eck` = current battle unit drawer / battle visual object

Current DiffableCs: `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/eck.cs`.

`eck` has the strongest current battle-drawer evidence:

- class `eck : edg, emp, ecl`
- `Unit <cfdi>k__BackingField` offset `0x38`
- `BhBattleTimelineHelper <cfdk>k__BackingField` offset `0x48`
- `UnitViewConfig cfdm` offset `0x58`
- `Animator cfdn` offset `0x60`
- `GameObject cfdr` offset `0x80`
- `SpriteRenderer cfdw` offset `0xA0`
- `public GameObject bbyo()` / `public GameObject dre()` / `public GameObject err()` style accessors
- `public bool Init(UnitViewConfig, TransferUnit, Random, Vector3, float, bool, int)`
- current duplicate/alias method `mmg(UnitViewConfig, TransferUnit, Random, Vector3, float, bool, int)` in ISIL

Dossier:

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_visual_eck_mmg_dossier.md`

Native-friendly implication: battle unit visual replacement and donor presentation syncing should anchor on current `eck.Init`/`eck.mmg` or a narrower proven child method, not on global resource loading or unrelated event dispatcher candidates.

### `edh.bcvc(...)` = current raw field-object spawn/domain construction

Current DiffableCs: `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/edh.cs`.

Current signature:

`FieldObject bcvc(EFieldObjectType, string, int, eir, Hex, int = -1, bool = false, bool = true, bool = false, eac = null, eab = null)`

Dossier:

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_visual_spawn_edh_bcvc_dossier.md`

Static evidence shows this method creates/initializes field objects including `Unit`, `Sentry`, and `Obstacle` paths. This is a domain/spawn surface, not a renderer presentation helper.

Native-friendly implication: use this only if a feature needs battle field-object construction correlation. Do not use it as a visual replacement point unless the change is specifically about spawn-time identity/domain mapping.

## Suspect or stale surfaces

### `ecd` should not currently be treated as a battle drawer anchor

`GameSymbols.BattleVisual.BattleDrawerTypeNames` includes `ecd`, but the current `ecd` dossier is dominated by event/clickability dispatch evidence:

- `SkillsClickabilityChangedEventArgs`
- battle event dispatch calls
- no clear current visual fields in the DiffableCs shell

Dossier:

- `experiments/cpp2il_readable_csharp/samples/latest_refresh/battle_visual_ecd_methods_dossier.md`

This does not prove `ecd` has no visual relationship anywhere, but it is not a clean drawer object and should be marked suspect for visual replacement until stronger evidence is found.

### `bfdk` is stale for current `edh`

`GameSymbols.BattleVisual.SpawnObject` includes `bfdk`, but current `edh.cs` exposes `bcvb`, `bcvc`, aliases such as `cvi/fsr/gn/leh`, and helper `bcvd`. The attempted `edh::bfdk` dossier failed because that method name is not current in this refresh.

## Relationship to UnitViewConfig

`eck.Init/mmg` consumes `UnitViewConfig` directly. This lines up with the separate UnitViewConfig evidence that current `UnitViewConfig` still owns `mesh`, `mapMesh`, `scale`, and ability-view arrays.

Recommended separation:

- map/adventure prefab loading: `UnitViewConfig.seo()` / `mapMesh`
- battle visual initialization: `eck.Init`/`eck.mmg`
- battle field-object construction: `edh.bcvc`
- renderer presentation copying: mod-side adapter after the specific native object exists

## Existing mod implications

`Homm3ImportReleaseBattleVisualHook.cs`, `Homm3BattleVisualInterop.cs`, and `EsquirePikemanVisuals.cs` should prefer `eck` as the current battle visual object. Any code still treating `ecd` as a drawer candidate should be audited or guarded as historical.

`EsquireBattleVisualPresentation.cs` should remain a presentation helper library, not a surface resolver. It should be called from a proven `eck` or map-squad visual hook after native object creation.

Broad `ResManager.Get<GameObject>` paths remain higher risk because they can affect non-unit scene initialization. The current evidence supports keeping those retired or strictly opt-in diagnostics.

## Gaps before implementation changes

- Focused code audit of `Homm3ImportReleaseBattleVisualHook.cs` and `Homm3BattleVisualInterop.cs` against current `eck` fields/methods.
- Update `GameSymbols.BattleVisual` comments to distinguish current-proven `eck` from suspect/historical `ecd`.
- If changing battle visual hooks, runtime proof is still needed for object lifetime and pool reuse order.

## Evidence boundary

Static evidence proves current field/method shape and strongly identifies `eck` as the battle visual drawer object and `edh.bcvc` as field-object spawn/domain construction. It does not prove Harmony timing, pooled drawer reuse, renderer state after animation setup, or all aliases in generated interop.
