# Town Scene Render Static Mapping

Status: **Historical** Route A analysis (2026-07-20). Preferred product path is the owned Unity city-world paradigm in `docs/custom_town_scene_paradigm.md`. Do not treat Route A UI mirroring as the destination for new custom towns.

## Problem being mapped

The HoMM3 town replacement currently renders as Unity UI content under the town UI panel. Recent runtime results showed two opposite failures:

- Custom town content above native menus/buildings, hiding the usable UI.
- Donor/native town scene visible under native menus while custom HoMM3 content is not visibly replacing it.

The core question is whether this is a simple canvas sort-order problem or a render-domain mismatch between the native town scene and the modded UI replacement.

## High-confidence static model

### Native town scene is world/scene rendered

Evidence:

- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/City/BhCityCameraController.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/City/BhBuildingsManager.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/Session/City/BhBuilding.cs`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/Session/City/BhCityCameraController.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/Session/City/BhBuildingsManager.txt`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/Session/City/BhBuilding.txt`

Findings:

- `BhCityCameraController : MonoBehaviour` owns `lookAtTransform`, `cameraTransform`, `settings`, camera interpolation state, and a static active instance.
- `BhBuildingsManager : MonoBehaviour` owns a list of city building slots and calls `BhBuilding.bajc` / `BhBuilding.bajb` while refreshing building visibility/state.
- `BhBuilding : MonoBehaviour, IPointerClickHandler, IPointerEnterHandler, IPointerExitHandler` owns building scene/VFX state, including `vfxRoot`, building config/state fields, and pointer interaction.
- `BhBuilding.bajg(bool)` calls `GameObject.SetActive` on `vfxRoot`.
- `BhBuilding` references `BhCityCameraController` in its body, so native building presentation is camera-coupled scene content, not just UI imagery.

Interpretation:

The donor town is not a flat background. It is a native city scene with its own camera, world objects, building interaction components, and VFX roots.

### Native town UI is a separate BhScreen/canvas layer

Evidence:

- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/UI/BhScreen.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/UI/City/BhCityUISession.cs`
- `tmp/cpp2il_experiment/out_dev_diffable_cs/DiffableCs/Hex/Hex/UI/City/BhNavigationView.cs`
- `tmp/cpp2il_experiment/out_dev_isil/IsilDump/Hex/Hex/UI/BhScreen.txt`

Findings:

- `BhScreen` requires `Canvas`, `GraphicRaycaster`, and `CanvasGroup`.
- `BhScreen` has serialized `renderToMainCamera` at field offset `0x21`.
- `BhScreen` stores `CanvasGroup cg`, `GraphicRaycaster raycaster`, and `Canvas canvas`.
- `BhScreen.OnEnable` checks `renderToMainCamera`; when true, it calls `jj.hqq(canvas, 0)`.
- The exact native semantics of `jj.hqq` are not resolved in the current address map, so this remains an unresolved helper. Static shape strongly suggests a native canvas render setup path.
- `BhCityUISession : BhScreen` owns city UI groups: city info, heroes groups, navigation, hire view, building session, town input, and tech city HUD.
- `BhNavigationView : BhScreen` is part of the city UI layer and owns navigation buttons/background fields.

Interpretation:

Native town UI is not simply a child list under a random canvas. It is part of the `BhScreen` system, and some screens opt into a native setup path that targets the main camera or active UI render domain.

### Current mod replacement is UGUI RawImage content under CanvasCityPanel

Evidence:

- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Plugin.cs`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3StrongholdTownLayers.cs`
- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3LiveProbeWorkbench.cs`

Findings:

- `ApplyCustomCityBackdrop()` finds `CanvasCityPanel`, creates/reuses `OfflineUnlockCityBackdrop`, adds a `RawImage`, parents it under `CanvasCityPanel`, and calls `EnsureCityBackdropCanvasOrder`.
- `EnsureCityBackdropCanvasOrder()` currently adds/uses a `Canvas`, sets `overrideSorting = true`, and assigns a numeric sorting order.
- `Homm3StrongholdTownLayers.SyncCurrentCityLayers()` creates the town layer root under `CanvasCityPanel` through either `TryEnsurePrefabLayerRoot` or the dynamic layer path.
- The town layer path uses `RawImage` objects and disables raycasts/masking.
- `ApplyLayerRootTransform()` maps layer content into the `CanvasCityPanel` reference space.
- The generated prefab is an AssetBundle optimization of the same UI-layer approach. It is still UGUI content, not native city-scene geometry.

Interpretation:

The current replacement path renders HoMM3 towns as UI images in the city UI hierarchy. It does not replace the native city scene renderers or participate in `BhBuildingsManager`/`BhBuilding` world rendering.

## Current live bridge capability boundary

Evidence:

- `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/Homm3LiveProbeWorkbench.cs`

Findings:

- `CanvasJson` reports:
  - `enabled`
  - `overrideSorting`
  - `sortingOrder`
  - `sortingLayerID`
  - `sortingLayerName`
  - `renderMode`
  - `worldCamera`
  - `planeDistance`
- Canvas write commands currently support:
  - `enabled`
  - `overrideSorting`
  - `sortingOrder`
  - `sortingLayerID`
  - `sortingLayerName`
  - `planeDistance`
- Canvas write commands do not currently support:
  - `renderMode`
  - `worldCamera`

Interpretation:

Runtime bridge tests can observe whether custom canvases differ from the native `BhScreen`/`CanvasCityPanel` render domain, but currently cannot directly test the most important suspected writes: matching `renderMode` and `worldCamera`.

## Static explanation of the failures

### Why “just increase sortingOrder” is weak

Sorting order only controls ordering within compatible canvas/render domains. It does not by itself prove ordering against a separately rendered native city camera/world scene.

Observed runtime outcomes already contradict the idea that one fixed order is enough:

- Low order left custom content behind the donor/native scene or not visible where expected.
- Higher order could move custom content above native UI and hide menus.

Static evidence explains why: the donor town is scene content, while our replacement is UI content. Their relative ordering depends on render mode, camera, plane distance, sorting layers, and native screen setup, not just a single numeric order.

### Most likely root cause

Inferred, not proven:

The custom HoMM3 town canvases do not faithfully mirror the active native town screen canvas render domain. They are child canvases with hand-authored `overrideSorting` and numeric orders. If the native city scene is rendered by the city camera and the UI is rendered by `BhScreen` canvases that may be attached to the main camera through `renderToMainCamera`, our custom canvases can land in the wrong render band.

## Candidate solution routes

### Route A: Stay in UI, but mirror native canvas render domain

Recommended next implementation route if we want a narrow fix.

Implementation shape:

- Add one centralized helper for custom town canvases.
- Find the nearest valid parent/native town canvas from `CanvasCityPanel` or `BhCityUISession`.
- Copy render-domain properties from that canvas:
  - `renderMode`
  - `worldCamera`
  - `planeDistance`
  - `sortingLayerID`
  - `sortingOrder` strategy based on the parent/native city screen, not global constants.
- Keep `raycastTarget = false` on custom town graphics.
- Do not keep experimenting with arbitrary global sort orders.
- Extend bridge canvas writes only if runtime tuning still needs it, adding `renderMode` and a bounded `worldCamera` copy-by-source-canvas operation rather than arbitrary camera assignment.

Risks:

- Still a UI overlay approach, so it may never perfectly match native scene occlusion.
- Requires runtime visual proof in at least one town scene.

### Route B: Move HoMM3 visuals into native city scene render domain

Most native-friendly long-term route.

Implementation shape:

- Treat `BhBuildingsManager` / `BhBuilding` as the owner surface for visible town scene objects.
- Hide or replace donor renderers under city building/world roots, not native UI.
- Instantiate HoMM3 town renderers/materials into the city scene under a world-space root visible to `BhCityCameraController`.
- Keep native UI untouched.
- Preserve or explicitly proxy `BhBuilding` hitboxes/interaction if needed.

Risks:

- More implementation work.
- Requires careful static/runtime identification of which scene renderers are visual-only versus interactive building objects.
- Asset conversion may be needed if current town art is UI-sized textures.

### Route C: Hide donor city renderers, keep UI replacement

Intermediate route.

Implementation shape:

- Use static/runtime evidence to identify donor visual renderers under the active city scene.
- Disable only visual renderers that belong to the donor town scene.
- Keep native UI and hitboxes.
- Render HoMM3 UI layer behind native UI.

Risks:

- If donor visuals and interaction objects are coupled, disabling the wrong renderer or object can break hover/click behavior.
- Requires runtime renderer ownership proof before source change.

## Practical next step

**Superseded as product destination:** Route A was implemented in plugin code (2026-07-20) as a UI-domain mirror. Prefer the owned Unity city-world paradigm in `docs/custom_town_scene_paradigm.md` for new custom towns.

Route A historical notes (legacy lane only):

- `EnsureCustomTownArtCanvas` mirrored `CanvasCityPanel` `renderMode` / `worldCamera` / `planeDistance` / `sortingLayerID` with relative sorting offsets.
- Native menu Overlay elevate ladders were rejected; owned-world towns skip Route A panel lift via `ShouldSkipRouteATownPanelLift`.
- If a faction is still on Route A posters, do not invent a second click system — migrate to owned world rather than polishing posters.

