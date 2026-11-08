# Surface: HoMM2 shade object class

## Intent

Make Golden Era use the same ReShade object treatment as VCMI: black ink on functional and landscape objects, saturated two-to-three-stop colour on functional objects, and no recode of grass/dirt/water from an invented mask.

This is not a trained Heroes II model. Material still comes from the original frame. DLSS5 stays lighting/residual only.

## Ownership preference

- **Identity:** Golden Era `ObjectConfig.isInteractable`, the same bool `BhMapObject` and Settings "always highlight interactibles" use (`highlightInteractiveObjsAlways` → `SelectionOutlineFlags.Always`). True is visitable (alpha 180). False or unresolved is landscape (alpha 90). This is not `EObjectType`. `Block` / trees / rocks omit the JSON flag or set it false, so they stay landscape. Adventure-map heroes use `HeroMap` drawers. Battle stacks use `BattleVisual` drawers (`ecd` / `eck`). Do not turn the highlight setting on from the plugin.
- **Write:** plugin `Homm2ShadeObjectClassStamp` Harmony-postfixes `RenderPipelineManager.EndCameraRendering` and writes those values into the camera target alpha (swapchain or the world camera's render texture). Do not subscribe `endCameraRendering` through `ConvertDelegate`; that failed at runtime with `NotSupportedException: Method unstripping failed` (**live-negative**). The postfix takes only `Camera` so `ScriptableRenderContext` marshalling cannot swallow the callback. Terrain (`Hex/TerrainMap`) and UI stay unstamped (alpha 255), which the shader already treats as “no engine mask.”
- **Alpha-only draw:** this Unity interop has no `GL.ColorMask` and `RenderTargetBinding` has no write-mask field. The only owned path is the precompiled URP `ColorMask A` shader in bundle `homm2_shade_object_class`. Build it with `python tools/homm3_import/build_homm2_shade_object_class_shader_bundle.py`. Do not runtime-compile ShaderLab from a string in the player. A Built-in CGPROGRAM bundle on this URP player is what produces Unity’s “Shaders failed to load” dialog. If `shader.isSupported` is false, refuse to draw.
- **Present:** shader source of truth remains `dlssnr-recon/tools/vcmi/`. Install onto Golden Era with `python tools/olden_era/launch.py --install-only`. Do not invent a second shader.

Do not classify from pixel colour, object art, or localized names.

## Touch points

| Kind | Path |
| --- | --- |
| Plugin stamp | `OfflineUnlockMod/Homm2ShadeObjectClassStamp.cs` |
| ColorMask A shader | `tools/homm3_import/unity_shaders/Homm2ShadeObjectClass.shader` |
| Bundle builder | `tools/homm3_import/build_homm2_shade_object_class_shader_bundle.py` (slim Unity project `V:/homm3_artifact_mesh_build`, not `oldenera_factions`) |
| Pins | `GameSymbols.Homm2ShadeObjectClass`, plus existing `CustomTownMapBillboard`, `HeroMap`, `BattleVisual`, `HomecomingLayerViewToggle.WorldCameraTypeHints` |
| Shader | `V:/Projects/dlssnr-recon/tools/vcmi/HoMM2_Palette.fx` (`OutlineMode` Map objects, `ObjectSolid`) |
| Wrap install | `V:/Projects/dlssnr-recon/tools/olden_era/launch.py` |
| VCMI encoding | VCMI `RestyleObjectClass` 0 / 90 / 180 / 255 |

## Pitfalls

- VCMI sprite `verticalFlip` is a left–right mirror. Golden Era facing is a 3D rotation / billboard, so do not port that VCMI `isTransparent` remap; class must follow the drawn mesh.
- Alpha 255 means “no mask.” If the stamp does not run, Map-objects ink does nothing. That is fail-closed, not a shader bug.
- Stamp `BhWorldCamera` even when `targetTexture != null`. URP commonly renders the world to a texture and then blits. Skipping every render-texture camera is why `host attached` can appear with no `landscape=` line. Still skip cameras whose names contain UI or Overlay. Town `BhBuilding` meshes are not placed map objects; they stay unclassified like VCMI town screens.
- `GL.ColorMask` is absent on this interop. Drawing `Hidden/Internal-Colored` without ColorMask A would overwrite RGB. Missing or unsupported bundle must refuse to draw, not invent a second write path.
- Do not subscribe `RenderPipelineManager.endCameraRendering` with `ConvertDelegate`. That threw `Method unstripping failed` on this player.
- `EObjectType.Block` is scenery that blocks walking (trees, rocks). Do not treat every non-Block type as visitable; that tagged foliage. If `isInteractable` is unresolved, keep the object as landscape (ink, no solid) and log — do not guess visitable from SID text or from `rxb`.
- Reject `Hex/TerrainMap` renderers. If the placed-object root is too high, those children are ground, not landscape objects.
- Pink / magenta on trees, combat ground, or custom biome props is Unity `Hidden/InternalErrorShader` (missing maps or a foreign shader). The palettizer then recodes that magenta into a pink palette swatch. That is not object-class detection and not a second neural hue. Skip error-shader meshes for class writes. Do not invent an RGB “unpink” remap in the shade wrap.
- Do not replace `winhttp.dll`, `GameAssembly.dll`, or the frozen neural DLL.

## Open unknowns

- Battle obstacles / siege walls as landscape are not registered yet (VCMI stamped them 90). Combat stacks and battle heroes are visitable.
- Whether Unity HDR / post-process discards swapchain alpha on this install is **runtime**-unproven until a player sees Map-objects ink on a mine and not on grass. If the world camera target is a render texture, the blit to the swapchain ReShade sees may still drop alpha — log `targetTexture=` and do not invent a second RGB path.
- Cutout billboard holes depend on `_MainTex` / `_Cutoff` copy into the class material; a foreign shader with a different clip slot would fill a rectangle. Report that; do not invent a second clip path.
- `ZTest LEqual` after the camera finishes assumes the depth buffer still matches the drawn meshes. If a pass rebuilds depth, class would miss. That is runtime-unproven.

## Proof

| Claim | Tier |
| --- | --- |
| Surface card + pins + stamp type exist | **source/static** |
| ColorMask A shader + slim-project bundle build | **generated artifact** |
| Plugin compiled OfficialDeobf and DLL + bundle copied to Golden Era | **deployed** |
| Log line `Homm2ShadeObjectClassStamp: host attached` | **startup smoke** |
| `ConvertDelegate` / `add_endCameraRendering` | **live-negative** — Method unstripping failed |
| Built-in CGPROGRAM class bundle on this URP player | **live-negative** — Unity “Shaders failed to load” |
| Skipping `targetTexture != null` before any status log | **live-negative** — `host attached` with no `landscape=` is explained by this skip as well as by a dead postfix |
| Log counts `landscape=` / `visitable=` / `skip=` / `types=` / `mines=` / `interactable=` on a loaded map | **runtime** |
| Player sees ink on a mine/hero/battle stack and not on grass | **user-visible gameplay** — unproven until inspected |
| Pink trees / terrain | **not class proof** — native `InternalErrorShader` unless a material bind is shown |

Hub: [../agent_surface_guide.md](../agent_surface_guide.md).
