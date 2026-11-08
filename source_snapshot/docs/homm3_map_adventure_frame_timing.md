# HoMM3 adventure-map frame timing (inventory)

Baseline for animation work: git commit **`e89df2c6`** (scale + map.prefab routing + `.rife_map_done.json` parse) plus **`RefreshNativeShellMapPrefabForAdventure` must pass the live native `shell` into `FinishHomm3MapPrefabForAdventure`**, not `null` — passing `null` on cached shells skipped Hex/Lit rebind and made reloads look like a failed revert.

**Map array pilots:** when `array_map_manifest.json` exists, call **`Homm3BattleArrayBillboard.TryAttachForMapVisual` on the native shell** after transplant; material shader must be **`OldenEra/Homm3/MapBillboardHexLitArray`** (`map_array_hexlit.mat`), not battle `BillboardArray`.

Gremlin / goblin trapper pilots use **map.prefab `MapIdle`** (material-swap clip), not the town-style disk tick.

---

## A. Which code path is active? (route selection)

Only **one** idle driver should run per unit. Wrong route = wrong speed or static sprite.

| Check | Where | Effect |
|--------|--------|--------|
| **`ShouldUseMapPrefabMapIdleAnimator`** | `Homm3ImportVisuals.cs` | `true` → map.prefab + `MapIdle` / array; `false` → may use town-style disk tick |
| **Town-style wins first** | `CreateNativeShellMapPrefabForAdventure` | If `!ShouldUseMapPrefab… && TryApplyTownStyleUnitBillboard` → **never** reaches map prefab timing |
| **Root name collision (fixed `1c1bbda6`)** | `TownStyleUnitBillboardRootName` = `HOMM3_unit_map_billboard` vs `MapPrefabVisualChildName` = `homm3_map_visual` | Old bug: town-style tick on `homm3_map_visual` at **120 ms/frame** |
| **Map Texture2DArray prototype** | `Homm3BattleArrayBillboard.IsMapArrayPrototypeLabSid` | Uses array + `map_array_manifest.json`, not per-material `MapIdle` |
| **`.rife_map_done.json` present** | `extracted_map/.rife_map_done.json` | Forces map-prefab route even if playback meta incomplete (warning in log) |
| **Bundle `map_frame_*` count** | `CountMapFrameAssetNamesInBundle` | >1 materials → map.prefab route |

**Log lines to grep:** `map prefab route for labSid`, `town-style unit billboard skipped`, `using map.prefab MapIdle`, `map Texture2DArray`.

---

## B. Map.prefab `MapIdle` animator (primary path for RIFE pilots)

| Factor | Where | Formula / notes |
|--------|--------|------------------|
| **RIFE cycle length** | `TryGetMapRifePlaybackMeta` | `cycleSeconds = (outputCount - 1) / targetFps` from `.rife_map_done.json` |
| **Example (gremlin)** | `homm3_lab/h3_gremlin/extracted_map/.rife_map_done.json` | 40 frames @ 50 fps → cycle ≈ **0.78 s** |
| **Unity `MapIdle` clip length** | Built into `map.prefab` / animator controller | `clip.length` (seconds) — **must match material key count**, not PNG file count on disk |
| **Playback speed** | `TryApplyMapAdventureAnimatorPlaybackTiming` | `animator.speed = clamp(clipLength / cycleSeconds, 0.05, 24)` |
| **If meta missing** | `TryGetMapRifePlaybackMeta` returns false | **No speed patch** → default `animator.speed = 1` → often **slow or wrong** vs RIFE intent |
| **Clip discovery** | `TryFindMapAdventureWalkClip` | Clip named **`MapIdle`** (case-insensitive) or only clip on controller |

**Log line:** `Homm3Import: map adventure playback timing labSid=… clipFps=… clipLen=… rifeCycle=… animator.speed=…`

**Slow-motion symptom:** `animator.speed < 1` because **`clip.length` > `cycleSeconds`** (clip authored too long / too many keys vs RIFE `outputCount`).

---

## C. Town-style disk tick (fallback — not for gremlin/trapper when route is correct)

| Factor | Where | Default |
|--------|--------|---------|
| **Frame interval** | `TownStyleUnitIdleFrameMs` | **120 ms** (~8.3 FPS) |
| **Resolved interval** | `ResolveTownStyleMapIdleFrameMs` | `(cycleSec * 1000) / timingFrames`, clamp 8–250 ms, if RIFE meta OK |
| **Frame count for timing** | `ResolveTownStyleMapIdleFrameMs` | Uses `outputCount` if disk has **more** PNGs than RIFE output (double-RIFE / stale glob) |
| **Tick implementation** | `Homm3MapIdleTextureAnimatorRegistry.Tick` | Advances when `TimerMs >= FrameMs` |
| **Attachment** | `TryAttachTownStyleUnitIdleAnimator` on town-style quad only | **Not** used when `ShouldUseMapPrefabMapIdleAnimator` |

---

## D. Authoring / pipeline (before runtime)

| Source | File | Fields |
|--------|------|--------|
| **Unity authoring preset** | `homm3_lab/<sid>/authoring.json` | `mapFlipBookFps` (often **50** pilots, **10** bulk), `flipBookFps` (**battle**, often 60 or 120) |
| **Map RIFE done marker** | `homm3_lab/<sid>/extracted_map/.rife_map_done.json` | `cycle.outputCount`, `cycle.targetFps`, `targetFps`, `sourceFps` |
| **Map RIFE interpolation** | `tools/homm3_import/interpolate_homm3_map_sequences.py` | Writes PNGs + `.rife_map_done.json`; sets `authoring.json` **`mapFlipBookFps`** |
| **Battle RIFE** | `interpolate_homm3_battle_sequences.py` | `flipBookFps` / `deathClipFps` — **battle only**, not map `MapIdle` |
| **Unity bundle build** | `Homm3BillboardAnimatorBuild.cs` | Builds `map_frame_*` materials + **`MapIdle`** clip; uses `MapFlipBookFps` from authoring when building clip sample rate |
| **Map array path** | `Homm3BillboardAnimatorBuild.ArrayMap.cs` | `mapFlipBookFps` from authoring; `Homm3BattleArrayBillboard` reads `map_array_manifest.json` |

**Mismatch to watch:** `authoring.mapFlipBookFps` vs `.rife_map_done.json` `targetFps` vs **actual** `MapIdle` clip `frameRate`×`length` in built bundle.

---

## E. Bundle / asset counts (common slow-motion cause)

| Issue | Symptom | Check |
|--------|---------|--------|
| **Too many PNGs in `extracted_map`** | Town-style or wrong frame count | Folder file count vs `outputCount` in `.rife_map_done.json` |
| **`map_frame_*` materials in bundle** | `MapIdle` clip length tied to **material count** | Unity `map.prefab` / bundle asset names |
| **Single static `map_frame_`** | No animation; idle missing | Log: `idle-animation-missing` |
| **Steam vs repo lab mismatch** | Meta says 40 frames, bundle has different count | Compare deployed `homm3_lab` + bundle under plugin |

---

## F. Runtime material animation (does not change timing by itself)

| Component | Role |
|-----------|------|
| **`Homm3MapBillboardMaterialSync`** | Replaces `map_frame_*` with Hex/Lit clones **after** animator swaps material each frame |
| **`EsquirePikemanVisuals.TryRebindHomm3MapMaterialsFromVanilla`** | Initial Hex/Lit rebind from vanilla donor |
| **Native shell `PrepareNativeShellDriverRenderers`** | Hides vanilla donor draw (`forceRenderingOff`); **does not** change flip-book timing |

---

## G. Map Texture2DArray path (array prototypes)

| Factor | Where |
|--------|--------|
| **Manifest FPS** | `homm3_lab/<sid>/map_array_manifest.json` → `clips[].fps` (synced from `.rife_map_done.json` via `sync_homm3_array_manifests_from_unity.py`) |
| **Playback** | `Homm3BattleArrayBillboard` on map visual; uses animator state + `_FrameIndex` |
| **Battle vs map FPS** | `HOMM3_TARGET_FPS=60` battle vs map pilot **50** in `.rife_map_done.json` — different pipelines |

---

## H. Constants (quick reference)

```text
TownStyleUnitIdleFrameMs     = 120f     // town-style disk tick only
MapAdventureWalkClipName     = "MapIdle"
MapAdventurePlaybackSpeedMin = 0.05f
MapAdventurePlaybackSpeedMax = 24f
TownStyleUnitBillboardScale  = 0.125f   // size only
```

---

## I. Diagnostic checklist (one unit, e.g. `h3_gremlin`)

1. Log: **`map prefab route for labSid='h3_gremlin'`** (not town-style tick on same unit).
2. Log: **`map adventure playback timing`** with `animator.speed` — if **absent**, RIFE meta or animator/clip missing.
3. Read **`extracted_map/.rife_map_done.json`**: `outputCount`, `targetFps` → compute `cycleSeconds`.
4. In play mode / logs: **`MapIdle` `clip.length` and `clip.frameRate`** vs `cycleSeconds`.
5. Count **`map_frame_*`** in bundle / prefab vs `outputCount`.
6. Confirm **no** `Homm3MapIdleTextureAnimator` on `homm3_map_visual` (town-style tick).
7. Confirm plugin marker **`map-rife-baseline`** and finish signature **`v4-baseline`**.

---

## J. Map FoW — do not use fog sync (never worked)

**`Homm3NativeShellVisibilitySync`, `EsquirePikemanMapBillboardFogSync`, fog polling, and `Homm3MapNativeHexLitDrawBridge` do not work for HoMM3 map units.** Do not attach them or document them as fixes.

**Supported path (2026-05-31):** `TryFinalizeNativeShellMapPresentation` + `Homm3NativeShellRendererTransplantSync` — hidden `homm3_map_visual` runs MapIdle; vanilla shell `Renderer` displays frames so fog matches stock map sprites. Log: `map finish signature v8-native-transplant`.

**Owned-skinned exception:** transplant cannot draw a skinned mesh. Native donor stays `forceRenderingOff`. Owned draw follows the map-squad visibility flag (`requested`). The fog probe must not force owned meshes visible. Do not copy native `enabled` onto owned skins. Do not `initRestoreDraw=owned-skinned`.
