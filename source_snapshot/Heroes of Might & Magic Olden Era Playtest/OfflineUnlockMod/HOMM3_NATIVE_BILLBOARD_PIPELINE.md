# HoMM3 Native Adventure-Map Billboard Pipeline

## Goal

HoMM3 imported adventure-map visuals must behave like native Olden Era map visuals:

- hidden by grey fog and black shroud;
- depth-tested behind terrain and map objects;
- eligible for native hover/outline overlays;
- able to cast native shadows from the HoMM3 silhouette;
- not dependent on per-frame fog polling;
- not dependent on `Sprites/Default` rendering.

Current source has three explicit controller draw targets: `Homm3MapArraySliceHexLitBridge`, native-shell renderer transplant, and direct owned visual renderers for town-style/static billboards. Native-shell transplant is one supported path, not the only current visibility path.

## Native-Transplant Unit Path

The working unit path is implemented in `Homm3ImportVisuals.CreateNativeShellMapPrefabForAdventure` + `TryFinalizeNativeShellMapPresentation`.

The high-level flow is:

1. `UnitViewConfig` map loader requests vanilla map prefab + HoMM3 `map.prefab`.
2. `shell = Instantiate(vanilla)` — same component tree stock units use.
3. `homm3_map_visual = Instantiate(homm3Template)` parented under shell; `FinishHomm3MapPrefabForAdventure` applies scale/Hex/Lit/MapIdle timing.
4. `TryFinalizeNativeShellMapPresentation`:
   - strips any stale `Homm3NativeShellVisibilitySync` / `EsquirePikemanMapBillboardFogSync` (never attach these);
   - picks largest native `MeshRenderer` or `SkinnedMeshRenderer` on the shell (not under `homm3_map_visual`);
   - sets `enabled=false` on all other donor renderers;
   - attaches `Homm3NativeShellRendererTransplantSync` to copy animated materials/mesh from the hidden child onto the native renderer **without** overwriting native `enabled` (engine fog owns that).
5. The shell is returned as the map prefab.

**Do not** treat a visible `homm3_map_visual/quad` as the primary draw path for RIFE/MapIdle units — that bypasses native fog. Town-style static billboards remain a separate fallback when MapIdle is not used.

## Why The Direct Map Prefab Failed

The original imported HoMM3 map prefab rendered with `Sprites/Default` and looked visually correct, but it did not participate in native fog-of-war. It was simply a visible sprite-like renderer under a unit model root.

Changing only the material to `Hex/Lit` was insufficient because the renderer still was not participating in the same native shell/path as stock map units. Some `Hex/Lit` attempts also corrupted textures because stock donor materials contain skinned-mesh or PBR texture slots that are unsafe on a flat flip-book quad.

## Why Per-Instance Fog Sync Failed

Explicit fog synchronization was tested as a fallback. It had two main problems:

- it did not actually match the native ownership path for unit visibility;
- polling and runtime hierarchy scans caused stutter, poor performance, and in one experiment an IL2CPP generic `GetComponents<T>` trampoline failure loop.

The current event-driven controller applies visibility to whichever supported draw target owns the unit. `Homm3NativeShellVisibilitySync` and `EsquirePikemanMapBillboardFogSync` remain retired; do not reattach them.

## Why The Stronghold Town Billboard Was The Model

`Homm3StrongholdTownMapBillboard` worked because it mutates an actual native adventure-map `MapObject` prefab/root. Its behavior proved that a manually-created `MeshRenderer` quad can receive correct fog, depth, outline, and shadow behavior when:

- it is inserted under the native map object/root;
- existing native renderers are hidden;
- a donor `Hex/Lit` material and renderer flags are used.

The unit solution ports that same structure to unit map shells:

- clone native root;
- hide existing native renderers;
- add a single `MeshRenderer` quad;
- use sanitized native `Hex/Lit`;
- copy renderer flags from the donor.

## Unit Texture Source

The HoMM3 map prefab textures and later battle prefab textures were not reliable for the final displayed unit image. They produced correct texture objects and distinct instance IDs, but the visible image remained the old pikeman sprite.

The working solution bypasses AssetBundle material texture selection for the displayed unit image and loads a PNG directly from the extracted HoMM3 source frames:

`oldenera_factions/Assets/CustomUnits/homm3_lab/<labSid>/extracted_battle/...`

The lab SID is derived from `battlePrefabAssetPath` in `homm3_import.json`, for example:

`Assets/CustomUnits/homm3_lab/h3_orc/battle.prefab` -> `h3_orc`

The preferred disk frame order is:

1. `00_04.png`
2. `00_00.png`
3. `02_00.png`

The map prefab still supplies placement/transform. Only the visible texture source is replaced.

## Unit Scale

Current source owns the normalization constant:

`TownStyleUnitBillboardScale = 0.125f`

For authored adventure-map prefabs, `NormalizeAdventureMapPrefabBillboardScale` only touches oversized `quad` transforms and multiplies both their local scale and local X/Y position by that factor. For direct town-style billboard construction, the same factor is applied to the source quad scale and the replacement root Y is set to half the normalized quad height so its bottom sits on the native shell origin.

These are source/static transform rules, not current runtime visual proof. Do not restore the older `0.5` scale or source-renderer world-Y anchoring narrative without a new focused runtime test and corresponding source change.

## Material Sanitization

All native-map billboards use `EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial`.

That function:

- clones the donor material;
- switches/copies donor `Hex/Lit` state;
- restores the HoMM3 texture;
- resets texture scale/offset to `(1,1)` / `(0,0)` on rebound texture slots;
- forces cutout/fog keywords:
  - `HEX_DITHER_FADE_ENABLED`
  - `HEX_ALPHA_CLIP_ENABLED`
  - `_ALPHATEST_ON`
- clears unsafe secondary texture slots such as normal/spec/detail/parallax maps;
- forces every exposed texture slot on the `Hex/Lit` shader to the billboard texture.

The final point matters because the current `Hex/Lit` shader exposes `_MainTex` and `_EmissionTex`. Setting both avoids donor texture leakage.

## Renderer Flags

Renderer flags are copied from the best native donor renderer on the shell or map object. The donor selection prefers `Hex/Lit` renderers with:

- enabled renderer state;
- map-style render queue;
- `HEX_DITHER_FADE_ENABLED`;
- `HEX_ALPHA_CLIP_ENABLED`;
- shadows enabled.

The copied flags include:

- rendering layer mask;
- shadow casting mode;
- receive shadows;
- light probe usage;
- reflection probe usage;
- motion vector generation mode;
- dynamic occlusion flag.

These flags are part of why the final unit billboard gets native fog/outline/shadow behavior.

## Stronghold Town Billboard

`Homm3StrongholdTownMapBillboard` uses the same native billboard principles:

- mutate the native map-object prefab/root;
- hide existing renderers;
- create a `MeshFilter` + `MeshRenderer` quad;
- use a sanitized donor `Hex/Lit` material;
- copy native map renderer flags.

The town texture is loaded directly from:

`homm3_runtime_assets/map_object_refs/homm3_stronghold_city/avcdung0.dir/00_00.png`

The town billboard now uses the same IL2CPP-safe image decode path as the unit disk loader and scales the quad by texture aspect ratio instead of forcing a square. This should reduce stretching while preserving the native fog/shadow/outline path.

## Things To Avoid

Do not reintroduce these as the primary solution:

- `Sprites/Default` map rendering for HoMM3 units;
- per-instance fog polling;
- runtime squad-root mirror components;
- late-update hierarchy scans using generic `GetComponents<T>` in injected IL2CPP components;
- donor renderer transplants onto arbitrary skinned/native renderers;
- mutating shared AssetBundle material assets in place.
- inherited `Hex/Lit` vertex displacement on single-quad billboards. Donor materials can carry
  `HEX_VERTEX_DISPLACEMENT_FLAG`, `_VertexDisplacementType`, and `_Flag*` wave fields that are
  correct for native flags/buildings but make HoMM3 town/unit billboards hover or wave.

## Current Limitations

The unit billboard now supports a narrow idle animation path. `Homm3ImportVisuals` still builds the same cloned native shell, single `homm3_map_visual/quad` renderer, and sanitized `Hex/Lit` material, then registers that material with a global `Homm3MapIdleTextureAnimator` host when multiple bundled `map_frame_` textures are available. The animator swaps texture bindings on the live renderer material only; do not write a renderer `MaterialPropertyBlock` for this path. On May 20, 2026, logs proved map frames were bundled and ticking while the color billboard still disappeared and the shadow continued to animate, so the failure mode was shader pass state, not frame discovery. Dynamic unit map materials also strip dither/emission keywords (`HEX_DITHER_FADE_ENABLED`, `HEX_EMISSION_MAP_ENABLED`, `_EMISSION`) and clear emission textures so loop/reload behavior cannot inherit volatile native billboard fade state.

May 4, 2026 logs proved the global host can tick while the visible map image still stays static. The safer design now also attaches a lightweight `Homm3MapIdleTextureAnimator` component to the quad so runtime prefab clones register their live `Renderer`; the global ticker then applies frames to the renderer's current shared material. This avoids assuming the material instance created during prefab construction is the same object sampled by the visible world-map renderer without clobbering native `Hex/Lit` per-renderer state.

May 4, 2026 contact sheets for Goblin, Cyclops, and Wolf Rider showed extracted battle group `00` is the walking/locomotion loop, while group `02` is the standing idle/breathing loop. Do not switch the map idle glob back to `00_*.png`.

May 4/17, 2026 defeated-map-object fade path: `Homm3MapBillboardDeathFade` is attached only to the existing `homm3_map_visual/quad`, and `Homm3MapBillboardDeathFadeHook` registers that quad through `Homm3MapObjectUnitVisualHook`. In the runtime-manifest worktree, `homm3ReleaseMapObjectUnitVisual=true` makes that unit-visual hook a required release-safe startup gate: it must resolve `GameSymbols.CustomTownMapBillboard` (`bvd` metadata / `bvb` placed object) and patch the current placed-object init before map load. The death-fade trigger itself is quarantined behind `homm3ReleaseDeathFade=false`: the required gate proved the old `fce`/`fcd` int/no-arg candidate list no longer maps to Steam, where those types are `ObjRes`/`ObjResMine` wrappers. Do not revive it by patching every `est` interaction method; first trace the actual defeated map-object removal surface. Do not implement defeat effects through `OnDisable`, renderer disappearance, fog visibility, scene scans, cloned death-animation objects, or stale `buv`/`but` map-object fallbacks.

Do not replace this with the old animated visual-child path. Any future animation expansion should keep the renderer, material shader, shell hierarchy, and fog/visibility behavior intact, and should only change which disk-loaded HoMM3 texture is bound to the existing `Hex/Lit` material.

## Verification Checklist

For any future change, test one HoMM3 Stronghold unit stack:

- visible terrain;
- grey fog;
- black shroud;
- behind a mountain/object;
- hover/selection outline state;
- shadow shape;
- no large donor/corrupted texture frames;
- no frame-by-frame log churn;
- no `Homm3NativeShellVisibilitySync` runtime loop.

Useful log lines:

- `Loading [HeroesOE Offline Unlock 0.1.xxx]`
- `Homm3Import: town-style unit billboard applied ...`
- `Homm3Import: town-style unit idle animator registered ...`
- `Homm3Import: town-style unit idle animator registered live renderer ...`
- `Homm3Import: town-style unit idle animator tick ...`
- `Homm3 map billboard death fade: registered root ...`
- `Homm3 map billboard death fade: triggered path=...`
- `diskTexture=...`
- `quadScale=...`
- `HoMM3 Stronghold town billboard: applied native billboard material ...`
