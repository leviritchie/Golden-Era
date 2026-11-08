# HoMM3 Map Fog Debug Notes

> **Agent warning (2026-06-01):** `Homm3NativeShellVisibilitySync`, `EsquirePikemanMapBillboardFogSync`, fog polling, `Homm3MapNativeHexLitDrawBridge`, and runtime `LateUpdate` squad attach/mirrors **do not work** for HoMM3 map units. Do not reattach them or document them as fixes. The supported path is event-driven from the native map-squad visual controller: `Homm3MapSquadVisualControllerHook` applies bool visibility events to the active HoMM3 draw target (`Homm3NativeShellRendererTransplantSync`, `Homm3MapArraySliceHexLitBridge`, or town-style `homm3_map_visual`). MapIdle/array animation can still update while hidden, but draw visibility must follow the native controller event.

## Goal

Make HoMM3 imported adventure-map unit sprites behave like native Olden Era map units:
hidden by fog/shroud, occluded by terrain objects, eligible for native hover/outline behavior, and without corrupted animated frames.

## Current Working Theory

The town billboard path works because it is attached to a real adventure-map `MapObject` initialization path. Unit sprites are different: `UnitViewConfig.rtd()` returns only a model/prefab root, and that root is later owned by a separate map squad visual controller (`eya`). Material and prefab changes alone cannot reliably inherit fog state because they are below the object that owns visibility.

## Attempts And Results

- `Sprites/Default` billboard path:
  - Visuals render correctly but remain visible through fog.
  - Explicit fog polling was tested and caused poor performance/stutter.
  - This mode is now considered debug/visual fallback only.

- Sanitized `Hex/Lit` material clones:
  - Converted HoMM3 sprite frames to `Hex/Lit` donor-material clones and stripped unsafe properties/keywords.
  - Prevented some texture corruption, but did not make unit sprites participate in native fog.
  - Logs showed runtime animation can restore `Sprites/Default`, requiring `Homm3MapBillboardMaterialSync`.

- Native shell prefab:
  - Cloned a vanilla map unit prefab, added `homm3_map_visual` child, hid native donor renderers with `forceRenderingOff`.
  - Some versions produced donor-shaped shadows, proving the donor shell could participate in native render paths.
  - Unit sprites still remained visible in fog because the shell itself was not owned by a native map object.

- Renderer transplant:
  - Tried copying HoMM3 quad mesh/material onto a native shell renderer.
  - Broad version targeted incompatible `SkinnedMeshRenderer` cases and caused invisible sprites/performance issues.
  - Narrow version required `MeshRenderer + MeshFilter`; logs showed no compatible target for unit prefabs, so it skipped every unit.

- MapObject hook:
  - Hooked `but` / `buv` map-object initialization, same general lifecycle family as the town billboard.
  - It saw map objects such as caches/artifacts, but not HoMM3 unit shells.
  - This proved unit sprites are not under the same `MapObject.Init` path as the town billboard.

- Native shell ancestry diagnostic:
  - `0.1.112` showed `map_native_shell` ancestry as only itself:
    `p0='map_native_shell' comps=[Transform,Component,Homm3NativeShellVisibilitySync]`.
  - This proved the shell component was acting as an isolated model root, not as a child of a fog-owning map object.

- Map squad visual controller hook:
  - `0.1.113` hooked `eya`, the adventure-map squad visual controller.
  - Logs showed HoMM3 visuals under roots named `squad N` with correct `UnitViewConfig.mapMesh`.
  - Init fired while `squad N` roots were inactive and applied hidden state correctly.
  - Later `Homm3NativeShellVisibilitySync` on isolated `map_native_shell` re-enabled sprites, overriding the squad-controller result.

## Current Attempt

Build `0.1.114` removes `Homm3NativeShellVisibilitySync` attachment from HoMM3 imports and adds `Homm3MapSquadVisualMirror` on the `squad N` root. The mirror reacts to `OnEnable`, `OnDisable`, and a light `LateUpdate` on the actual squad root, so root visibility/fog changes should drive `homm3_map_visual` instead of the isolated shell.

## Latest Observation

- `0.1.114` loaded and the squad-root mirror attached during `eya.Init`.
- The mirror only attached to init-time inactive roots (`activeInHierarchy=False`).
- Later ancestry showed the actual rendered shell under a different runtime parent:
  `map_native_shell(Clone) <- squad 0 <- Section Root: ...`
- That runtime `squad 0` had only `Transform`, so the mirror attached during `eya.Init` was not on the final visible parent.
- A stale `Homm3NativeShellVisibilitySync` was still present on runtime shells, but with `visualRenderers=0`; it should not directly re-enable the HoMM3 sprite, but it proves stale shell components can survive into runtime instances.

## Next Attempt

Build `0.1.115` adds `Homm3MapSquadRuntimeAttach` to the HoMM3 shell prefab. After runtime reparenting, it finds the actual `squad N` ancestor, attaches `Homm3MapSquadVisualMirror` there, and disables any stale shell-local `Homm3NativeShellVisibilitySync`.

## Rollback

- `0.1.115` did not fix fog visibility.
- It caused severe performance loss and an NRE loop mid-gameplay.
- Logs showed repeated IL2CPP trampoline failures:
  `TypeInitializationException: MethodInfoStoreGeneric_GetComponents_Public_Il2CppArrayBase_1_T_0`.
- Likely cause: managed IL2CPP generic `GetComponents<T>` calls from injected runtime components during `LateUpdate` / reparent attach handling.
- `0.1.116` disables the squad runtime/mirror experiment by removing `Homm3MapSquadVisualControllerHook` registration and removing runtime attach from HoMM3 shell creation. The component source files remain for reference but are unused.

## Current Attempt

- `0.1.117` ports the Stronghold town world-map billboard construction to HoMM3 unit map shells.
- The unit shell now first tries a town-style static billboard:
  - clone the vanilla map unit prefab as the native shell;
  - find the best Hex/Lit donor renderer on that shell;
  - read the first HoMM3 map frame texture and estimated quad size from the HoMM3 map prefab;
  - hide all existing shell renderers with `renderer.enabled = false`, matching the town billboard behavior;
  - add `homm3_map_visual/quad` with a `MeshFilter` + `MeshRenderer`;
  - assign a sanitized Hex/Lit material clone using the HoMM3 frame texture;
  - copy native map renderer flags from the donor to the billboard root.
- This intentionally starts as a static first-frame test. If fog/shadow/outline behavior matches the Stronghold town billboard, animation should be rebuilt on top of this path rather than keeping the old animated visual-child path as the primary renderer.

## Latest Observation

- `0.1.117` applied the town-style path; logs showed `Homm3Import: town-style unit billboard applied ...`.
- Units were invisible on the world map.
- The applied quads were `8x8` Hex/Lit renderers with donor map flags, so the most likely failure was not hook ordering but authored unit billboard transform/orientation being discarded.
- Logs also still showed stale `Homm3NativeShellVisibilitySync` activity on `map_native_shell` roots. This component is not part of the town-style path and can force renderers off when it classifies native/visual renderers.

## Current Attempt

- `0.1.118` keeps the town-style static billboard path but preserves the source HoMM3 `billboard/quad` local transform:
  - billboard root copies the source quad parent local position/rotation/scale where available;
  - quad copies the source renderer local position/rotation/scale;
  - size/bounds are now diagnostic/fallback instead of forcibly replacing the authored transform.
- It also disables/destroys stale `Homm3NativeShellVisibilitySync` components on the shell before adding the town-style billboard.

## Latest Observation

- `0.1.118` is very close: HoMM3 unit billboards are hidden by fog and have native overlays/shadows.
- All units display the same pikeman sprite.
- The likely cause is the sanitized Hex/Lit donor clone keeping/sampling a donor albedo texture slot other than `_MainTex` (`_BaseMap`, `_BaseColorMap`, etc.). Logs showed each unit received a distinct clone and HoMM3 frame texture object name, so the native path is correct but texture slot restoration was incomplete.

## Current Attempt

- `0.1.119` updates Hex/Lit map billboard material sanitization:
  - restore the HoMM3 frame texture into all known base/albedo texture slots, not only `_MainTex`;
  - when clearing non-main texture slots, preserve those base/albedo slots instead of nulling them.

## Latest Observation

- `0.1.119` still showed all HoMM3 unit world-map sprites as pikemen.
- This means either:
  - the Hex/Lit shader is sampling a texture slot not covered by the known base/albedo list; or
  - the town-style unit path is extracting the wrong texture from every HoMM3 map template before material creation.

## Current Attempt

- `0.1.120` makes the next run diagnostic and deterministic:
  - force every texture property exposed by the Hex/Lit shader to the HoMM3 frame texture for billboard materials;
  - log texture property names and texture instance IDs;
  - log the source texture instance ID in the town-style unit billboard line.

## Latest Observation

- `0.1.120` showed the Hex/Lit shader only exposes `_MainTex` and `_EmissionTex`; both were forced to the HoMM3 texture.
- Texture IDs differed between unit bundles, so this was not one shared Unity texture object or an unhandled donor texture slot.
- The remaining likely cause is staging: HoMM3 map prefabs appear to reuse the old esquire/pikeman map scaffold/frames, while the per-unit HoMM3 content is present in battle prefab assets.

## Current Attempt

- `0.1.121` keeps using the HoMM3 map prefab for authored map transform/quad placement, but takes the displayed texture from the matching HoMM3 battle prefab.
- The unit billboard log now includes both map and battle texture names/IDs so this can be verified directly.

## Latest Observation

- `0.1.121` switched to battle prefab textures (`00_04`) and logged distinct texture IDs, but visuals still appeared as pikemen.
- The remaining strong suspect is AssetBundle/staged texture content or prefab material selection, not the native Hex/Lit path.

## Current Attempt

- `0.1.122` bypasses AssetBundle texture selection for the displayed image.
- It derives the HoMM3 lab SID from `battlePrefabAssetPath` and loads a PNG directly from:
  `oldenera_factions/Assets/CustomUnits/homm3_lab/<sid>/extracted_battle/...`
- Preferred frame order: `00_04.png`, `00_00.png`, then `02_00.png`.
- The map prefab still supplies transform/placement; only the displayed texture source changes.

## Latest Observation

- `0.1.122` fixed the pikeman-texture issue: HoMM3 units now display their correct sprites.
- Units are still about 2x too large.

## Current Attempt

- `0.1.123` keeps the working native shell + disk texture path and applies `TownStyleUnitBillboardScale = 0.5` to the unit quad scale only.
- The Stronghold town billboard now uses the same IL2CPP-safe PNG decode style and scales its quad by source texture aspect ratio rather than forcing a square.
- Full architecture documentation was added in `HOMM3_NATIVE_BILLBOARD_PIPELINE.md`.

## Latest Observation

- `0.1.123` fixed unit scale.
- The unit billboards were still positioned too high and too far right.
- The Stronghold town billboard still showed a stretched/distorted region even though the source `00_00.png` is square (`192x192`).

## Current Attempt

- `0.1.124` stops inheriting local source-renderer placement for unit billboards.
- Unit billboards now use deterministic bottom-centered placement: root at half displayed height, quad centered at local zero, identity local rotation.
- Sanitized native billboard materials now reset texture scale/offset to `(1,1)` / `(0,0)` for every rebound texture slot. This targets donor-material tiling/offset as the likely cause of the town billboard distortion.

## Current Attempt

- The latest town-map distortion suspect is `HEX_BLEND_INTO_TERRAIN_POSITION`, inherited from the native `byzantine_palace_mat` donor and visible in the 0.1.124 log on `HOMM3_AVCDUNG0_map_billboard_hexlit_mat`.
- `EsquirePikemanVisuals.CreateSanitizedHexLitMapBillboardMaterial` now strips `HEX_BLEND_INTO_TERRAIN_POSITION` and `HEX_BLEND_INTO_TERRAIN_COLOR` from HoMM3 billboard materials. These terrain-blend modes are valid for native map meshes/components but can paint or warp the lower band of a single upright quad.
- Keep using clamp wrap, full-quad UVs, and texture scale/offset `(1,1)` / `(0,0)`; the source AVCSTRC0 and AVCDUNG0 PNGs are both square `192x192`, so bottom-only distortion is more likely shader state than aspect ratio.

## Latest Observation

- Runtime log confirmed the terrain-blend keyword strip loaded: final town billboard keywords were `HEX_ALPHA_CLIP_ENABLED,HEX_DITHER_FADE_ENABLED,_ALPHATEST_ON`.
- The artifact persisted anyway. The remaining suspicious log state was renderer flags: `shadows=On receiveShadows=True occlusion=True` on a 4.5m upright cutout whose bottom edge sat exactly on the map object origin/terrain plane.

## Current Attempt

- `Homm3StrongholdTownMapBillboard` now applies town-only renderer overrides after donor flag copy: `shadowCastingMode=Off`, `receiveShadows=false`, `allowOcclusionWhenDynamic=false`.
- The town billboard also gets `0.08` world units of ground clearance in addition to the half-height lift. The HoMM3 source sprite already includes its own base/shadow pixels, so dynamic map shadows and exact terrain-plane contact are more likely to corrupt the bottom rows than improve the image.

## Latest Observation

- Runtime log showed the shadow/occlusion attempt loaded (`shadows=Off`, `occlusion=False`), but the bottom distortion still persisted.
- The final material still came from the town city's `byzantine_palace_mat` donor chain even after sanitization, so hidden donor material properties remain a plausible cause.

## Current Attempt

- `Homm3StrongholdTownMapBillboard` now builds a town-specific minimal `Hex/Lit` material from `Shader.Find("Hex/Lit")` instead of cloning donor material properties.
- The minimal material binds the town texture only to `_MainTex` / `_EmissionTex`, resets texture scale/offset, enables only `HEX_ALPHA_CLIP_ENABLED`, `HEX_DITHER_FADE_ENABLED`, and `_ALPHATEST_ON`, sets alpha cutoff fields to `0.05`, forces white `_Color`, black `_EmissionColor`, and uses render queue `2450`.
- The town billboard diagnostic now logs shader texture slots, cutoff values, color values, texture scale/offset, keywords, queue, and renderer flags so the next run can prove no city-donor state survived.

## Latest Observation

- The minimal `Hex/Lit` material made the town invisible while its hover highlight remained. That proves the map object/prefab/highlight path still works, but a bare `Hex/Lit` material lacks required donor state for the visible map pass.
- Working HoMM3 units use a donor-cloned `Hex/Lit` material via `CreateSanitizedHexLitMapBillboardMaterial`, commonly from Dungeon unit materials such as troglodyte, pet, minos, medusa, or hydra.

## Current Attempt

- `Homm3StrongholdTownMapBillboard` now scans loaded materials for a unit-style `Hex/Lit` donor, preferring the same Dungeon unit material names seen in working HoMM3 unit logs and rejecting terrain/city/building donors.
- The town billboard again uses `CreateSanitizedHexLitMapBillboardMaterial`, but with the selected unit-style donor when available. City `byzantine_palace_mat` is only a fallback if no usable unit-style donor is loaded.
- The diagnostic logs the selected donor source (`loaded-unit-style` or `city-fallback`) plus the full donor/final material properties.

## Latest Observation

- The unit-style donor restored the town's visibility, but the bottom stretch/distortion returned unchanged.
- Runtime logs confirmed the town material came from a loaded unit-style donor (`Troglodyte Throne_Mt`) rather than the city `byzantine_palace_mat` chain, so city-donor state is unlikely to be the sole cause.

## Current Attempt

- `Homm3StrongholdTownMapBillboard` now builds a runtime copy of AVCSTRC0 with a 96 px transparent gutter below the source image.
- The quad keeps the visible 192x192 town content at the same world size and ground clearance, while the full texture/UV rectangle extends into transparent padding below the town.
- This is a Hex/Lit-only diagnostic for bottom-edge or terrain-plane sampling: if the artifact moves into the transparent gutter or disappears, the problem is tied to the quad/texture bottom edge rather than the source image or city donor material.
- Expected log: `created bottom-padded texture source=192x192 padded=192x288 bottomPad=96` and the applied billboard log should include `bottomPaddingWorld=2.25`.

## Latest Observation

- The 96 px transparent bottom gutter made the town texture very close to correct. The remaining bottom softness appears consistent with the added transparent skirt and/or residual edge sampling rather than the original stretched ground-colored band.

## Current Attempt

- Keep the 96 px bottom gutter as the current town billboard fix.
- Re-enable town billboard shadow casting (`shadowCastingMode=On`) for map readability, but keep `receiveShadows=false` and `allowOcclusionWhenDynamic=false` so terrain/object shadow receiving does not reintroduce dirty lower rows.

## Latest Observation

- Custom unit scale is now in the right range. Current logs showed `quadScale=(2, 2, 1)` after the runtime map billboard normalization landed.
- The same logs still loaded only one bundled `map_frame_` texture and no bundled `homm3_frame_` idle sequence even though raw bundle bytes contain `homm3_frame_###` asset names. That points at bundle asset enumeration/loading rather than a missing loose PNG fallback.
- Units appearing on the first generated map but disappearing after loading a second map in the same process is an explicit squad-controller visibility symptom. Treat it separately from UnitView map-swap routing; UnitView swaps can still be firing while the owning squad visual controller stops mirroring or attaching the custom billboard.

## Historical Attempt (Retired)

Bundle frame scanning remains relevant, but the runtime mirror/attach experiment described here is retired. The current controller is event-driven and does not register Homm3MapSquadVisualMirror or Homm3MapSquadRuntimeAttach.

## Startup Fix (2026-06-02)

- Plugin load failed with `required Homm3Import map squad visual controller surface(s) missing: map squad visual init surface, map squad visual bool visibility surface` because registration used brittle `ParameterType.Name` checks for `fcy`/`ctp` instead of live `ezg` method names.
- **Root cause (Jun 2026):** Stale dumps targeted **`ezg`**, but Golden Era map-squad visual is **`ezn`** (`Init(fdf, ctq)`, visibility `bieq(bool)`). The name `ezg` is ambient sound in the same build; hooking it matched unrelated `bibz`/`bibx`/`kbr` two-arg methods and never the squad controller.
- Registration is explicit-only on `ezn` via `GameSymbols.MapSquadVisual` (no shape fallbacks). Re-dump from Golden Era per `tools/IL2CPP_DUMP.md` after hotfixes.

## Current Attempt

- `Homm3MapSquadVisualControllerHook` is now event-driven only. It no longer registers `Homm3MapSquadVisualMirror` or `Homm3MapSquadRuntimeAttach`, and `Plugin` keeps runtime attach disabled even when the controller hook is enabled.
- The hook applies native init/visibility bool events to the actual draw target:
  - map-array pilots: `Homm3MapArraySliceHexLitBridge.ApplyControllerVisibility()`;
  - MapIdle/transplant units: `Homm3NativeShellRendererTransplantSync.ApplyControllerVisibility()`;
  - town-style units: renderers under the owned `homm3_map_visual` billboard.
- The bridge methods persist controller-hidden state across their own `LateUpdate` so animation/material sync cannot re-enable a fog-hidden renderer.
- Expected log: `Homm3Import map squad visual: ... appliedTargets=... drawTargets=... drawState=...` (renderer enabled/forceOff on the active draw target).

## Useful Log Patterns

- Build/version:
  - `Loading [HeroesOE Offline Unlock 0.1.xxx]`
  - `Launcher config: ... | build=0.1.xxx`
- Unit prefab swap:
  - `Homm3Import: native-shell map swap ...`
- Runtime material override:
  - `Homm3Import: runtime map material classification ... replacedAny=True`
- Squad controller path:
  - `Homm3Import map squad visual: ... root='squad N' ...`
  - Retired/bad sign: `Homm3Import map squad visual mirror: ...`
  - Retired/bad sign: `Homm3Import runtime squad attach: ...`
- Bad sign for current approach:
  - `Homm3Import: native-shell visibility mirror ... visible=True`
  - This means the old shell-local mirror is still attached/enabled.
