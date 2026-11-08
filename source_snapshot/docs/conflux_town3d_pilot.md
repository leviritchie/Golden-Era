# Conflux 3D town scene pilot (Meshy buildings on a depth-surface backdrop)

Status: **generated artifact / Unity-editor render + Golden Era build target.** Plugin lane
`Homm3TownScene3d` and a camera-registered bundle exist (flag `homm3TownScene3d`, off); nothing deployed,
no game runtime proof. The free-standing building set was generated under the user's
`conflux_placeable_2026-09-26` approval (cap 1200 credits); see "Full placeable set" below.

## What the native town scene is (source/static, UnityPy + ilspy of interop Hex.dll)

- `cityHuman2` (level67): manager `human_city_all_objects` with 20 slot GameObjects (Main, Tier_1..7,
  Tavern, Magic_Guild, Market, ...); each slot holds per-level `BhBuilding` variants (MeshRenderer or
  SkinnedMeshRenderer + BoxCollider for clicks, some Animator/particles). 72 colliders, 43 animators,
  134 particle systems. 428 materials on Hex/Lit (base colour only), Hex/Sea water, VfxUber effects.
- One directional sun (intensity 3.86, colour (1,0.86,0.67), shadows), point lights, linear fog 16.1–92.1,
  trilight ambient, skybox. Camera FOV 47.6, pos (73.28,6.42,4.73), pitch ~8.5 deg. No day/night rig seen.
- Custom towns (`cityFactory`) load cityHuman2 additively, hide donor renderers, and place HoMM3 sprite
  quads in front of a backdrop (`Homm3FactoryCityWorldVisuals`). `Homm3TownSceneMeshBundle` is an
  existing, off-by-default 3D mesh lane (flag `homm3TownSceneMeshes`, one Factory town-hall row).

## Chosen approach

Populate the native structure; do not ship an owned Unity scene. Keep cityFactory's native slots,
BhBuilding colliders, camera, lights and CityUI; ship Meshy geometry as plain prefabs (no game scripts)
parented under each native per-level BhBuilding variant. An owned scene bundle would need the obfuscated
IL2CPP game scripts serialized into it. Buildings are seated on a camera-registered depth surface of the
HoMM3 backdrop (Depth Anything V2). Buildings are **registered** to their sprites (see "Alignment"); the
pilot's rule-based seating is superseded. The shipped lane registers each prefab to the camera instead of
seating it on a surface (see "Plugin integration"). A flat ground plane fails for elevated buildings.

## Tools

- `tools/homm3_town_scene_meshes/generate_conflux_town_meshes.py` — paid Meshy lane: sprite prep ->
  nano-banana-2 concept (6 cr) -> meshy-7 image-to-3d (30 cr); ledger
  `artifacts/meshy_town_scene_meshes/homm3_conflux/meshy_spend.json`.
- `tools/homm3_town_scene_meshes/export_stock_city_scene.py` — UnityPy export of cityHuman2 for the
  stock comparison render (terrain colour is approximated from the layer diffuse means; the native terrain
  shader is not replicated).
- `tools/homm3_town_scene_meshes/fit_mesh_to_sprite.py` — mesh-to-sprite registration (yaw, scale,
  ground-contact pixel) under the native camera.
- `tools/homm3_town_scene_meshes/probe_stock_city_animation.py` — UnityPy probe of how cityHuman2 animates
  (animators + animated transform paths, particle systems, self-animating materials) ->
  `artifacts/homm3_conflux_town3d/stock_city_animation_probe.json` (static-asset).
- `tools/homm3_town_scene_meshes/build_conflux_town3d_preview.py stage|unity|compose` — depth, fits,
  projected layers, Unity batch render (memgate + unitylock), alignment report, sheets and camera-move mp4 in
  `artifacts/homm3_conflux_town3d/media/`. Unity code: `tools/homm3_town_scene_meshes/unity/`. GLBs are
  instantiated from their imported assets; awaiting glTFast `Load` synchronously deadlocks in batchmode.

## Pilot result (108 credits: 3 concepts + 3 meshes)

- tbeldw_5 (golden ring portal): faithful, reads well at town scale.
- tbelhall (domed hall): Meshy simplified the multi-tower palace to one domed building; recognisable but
  loses the silhouette.
- tbeldw_3 (lava pit, a terrain-embedded dwelling): Meshy made a rock plateau; fitted to the sprite box it
  is a thin, barely visible slab. Terrain-embedded dwellings (lava pit, air altar, bridge/river) are the
  weakest Meshy class and probably want projected-plate or hand-built geometry instead.
- Camera move: the depth surface gives real parallax for small moves; at the extremes the backdrop edges
  stretch/tear and camera-parallel sprite cards visibly float. The native camera must stay near the
  registered pose (or the backdrop needs overscan/inpainting).

## Full placeable set (approval `conflux_placeable_2026-09-26`: 720 of 1200 credits)

The set is 20 concepts (6 cr) and 20 meshes (30 cr); all SUCCEEDED. The ledger is `meshy_spend.json`
(828 in total including the pilot). Review sheets:
`artifacts/meshy_town_scene_meshes/homm3_conflux/concepts_sheet_v2.png` and `meshes_sheet_v2.png`.

Layers:
- tbelhall_2/_3/_4;
- tbelcstl/_2/_3;
- tbelmage/_2/_3/_4;
- tbeltvrn, tbelblak, tbelsilo, tbelspec, tbeldock;
- tbelmark_a/_b (the market sprite split into its two stalls);
- tbeldw_0 (lantern house);
- tbeldw_2 (dry fountain basin);
- tbeldw_5_frame (portal ring with an empty hole).

The level-1 hall is the pilot mesh. Moving parts were kept **out** of the meshes on purpose (no smoke,
water jets or portal surface). tbelhall_4 kept the multi-tower palace silhouette on the first try thanks
to the per-tower prompt, so no retry was spent. Terrain-embedded dwellings (air shrine, lava pit, earth
ring, firestorm, ext2 garden) got no spend; they are projected painted pixels (below).

## Alignment (why the pilot misaligned, and the v2 construction)

Root causes found in the pilot camera-move video:
1. **Flat camera-parallel cards** at one foot depth: every pixel of a wide card (castle + river, ext2
   garden, lantern garden) sat at the wrong depth, so it slid against the depth surface when the camera
   moved.
2. **Rule-based mesh seating** (bounds centre on the sprite box's bottom-centre pixel, yaw = face the
   camera, height = box height): the sprite's lowest pixel is the footprint's front edge, Meshy's front
   axis is arbitrary, and screen-edge sprites have truncated boxes.
3. **State mismatch**: the level-1 hall mesh was compared with the level-4 capitol sprite.
4. Sprite pixels hidden under a later-drawn sprite were projected at the depth of the sprite on top.
   This was found in v2: tbelspec's painted ground drew over the portal ring.
5. Two limits that are not causes: the depth scale (Z_NEAR 10 / Z_FAR 160) is arbitrary, and the 182 px
   band under the 800x374 -> 1920 width-fit (x2.4) is mirrored edge extension, visible as a smeared strip.

v2 construction (`build_conflux_town3d_preview.py`):
- One `STATE` list (one level per slot) drives both the HoMM3 reference composite and the 3D scene.
- Each mesh is registered to its sprite alpha by `fit_mesh_to_sprite.Fitter`. It tries 24 yaws with
  Nelder-Mead over (scale, contact pixel), then refines within ±12 deg. The base rests on the backdrop
  depth surface at the contact pixel. The objective is precision-weighted F-beta (0.5), because sprites
  carry painted content the mesh must not chase (ground, river, smoke, foliage, water jets, portal
  surface).
- **Skirts**: sprite pixels the mesh does not cover, limited to the bottom 35% of the sprite box, stay
  as camera-projected pixels on a depth-displaced grid.
- **Holes**: pixels **enclosed** by the mesh silhouette (the portal surface inside the ring) are a
  separate part at the mesh's own camera depth, so they move with the frame. In the first v2 video they
  were projected at terrain depth and slid out of the ring.
- Terrain and sky layers are projected pixels on a grid displaced by the Depth Anything V2 depth of the
  **full composite**. That depth is least-squares aligned to the backdrop's disparity on background-only
  pixels (gain 1.228, offset 0.187, median residual 1.1% of range over 952k px). Grid triangles that
  cross a >1.3x depth jump are dropped.
- Only pixels **visible** in the HoMM3 composite are ever projected.

Measurement: default native camera pose, Unity-editor render with the preview Hex/Lit replica. Each mesh
is rendered alone as a white-on-black mask and compared with its sprite alpha in the same frame mapping.
Outputs, in `artifacts/homm3_conflux_town3d/media/`:
- `conflux_town3d_alignment.json`;
- `conflux_town3d_alignment_overlay.png`;
- `conflux_town3d_alignment_diff.png`;
- `conflux_town3d_side_by_side.png`.

Precision is the share of mesh pixels that land on the sprite, so it is the misalignment number. Recall
is low where the sprite carries painted content that is deliberately not meshed. The Unity masks match
the Python fit's IoU to within 0.06. That verifies the transform convention end to end: glTFast
x-negation, `Quaternion.Euler(0,yaw,0)` and uniform scale.

| mesh | IoU | precision | recall | centroid dx, dy (px) | bbox L / T / R / B (px) | yaw | height (u) |
|---|---|---|---|---|---|---|---|
| tbelhall_4 | 0.73 | 0.95 | 0.76 | -3, +4 | +0 / +43 / -5 / +26 | 135 | 4.78 |
| tbelcstl_3 | 0.54 | 0.97 | 0.55 | +45, -13 | +444 / -58 / -85 / +2 | 207 | 12.52 |
| tbelmage_4 | 0.67 | 0.96 | 0.69 | +3, +14 | +50 / +69 / +10 / -3 | 135 | 8.79 |
| tbeltvrn | 0.84 | 0.99 | 0.85 | +0, -1 | +5 / +9 / -1 / -2 | 159 | 3.27 |
| tbelblak | 0.55 | 0.97 | 0.56 | +10, +40 | +25 / +54 / -11 / -19 | 75 | 4.78 |
| tbelmark_a | 0.88 | 0.97 | 0.91 | +1, +1 | +3 / +5 / -2 / +2 | 150 | 3.47 |
| tbelmark_b | 0.78 | 0.93 | 0.83 | -2, -0 | +1 / +11 / -8 / -3 | 192 | 2.49 |
| tbelsilo | 0.77 | 0.94 | 0.81 | +1, +11 | -7 / +19 / +7 / -12 | 168 | 5.24 |
| tbelspec | 0.44 | 0.97 | 0.45 | -34, -32 | +43 / -16 / -151 / -30 | 171 | 3.21 |
| tbeldock | 0.66 | 0.92 | 0.70 | -7, -1 | +14 / +3 / -23 / +3 | 162 | 1.91 |
| tbeldw_0 | 0.49 | 0.90 | 0.52 | -4, +31 | +12 / -4 / +0 / +14 | 168 | 2.91 |
| tbeldw_2 | 0.59 | 0.96 | 0.60 | -1, +8 | +3 / +23 / -1 / -2 | 225 | 1.33 |
| tbeldw_5_frame | 0.64 | 0.97 | 0.65 | +6, +7 | +42 / +7 / -10 / +0 | 0 | 2.02 |

Mean IoU is 0.66, and precision is 0.90–0.99 on every mesh. The large bbox and centroid offsets are
painted, unmeshed content, not misplacement:
- castle: the river running out to the left (+444 px);
- spec: the ground strip to the right (-151 px);
- blacksmith: the smoke (+54 px top);
- lantern: the foliage;
- fountain: the water jets (+23 px top);
- portal: the disc.

Mean |render - reference| over the town area is 12.1 RGB. Shading inside the buildings dominates it:
Meshy albedo under the Hex/Lit sun against painted HoMM3 lighting. The pilot's 8.2 is **not**
comparable, because the pilot showed 14 of 17 slots as pixel-exact sprite cards.

Camera move: `conflux_town3d_camera_move.mp4`, with frames in `conflux_town3d_camera_move_frames.png`.
The pilot video is kept as `before_conflux_town3d_camera_move.mp4`. The path is the pilot's (±3 u
lateral, 4 u dolly, ±4 deg yaw). Meshes, skirts and terrain layers stay seated, and the portal surface
stays inside its ring. Remaining artifacts:
- backdrop edge tears at the frame borders;
- the mirrored bottom band;
- rubber-sheet stretch of the depth-grid layers at large parallax.

The native camera must stay near the registered pose, or the backdrop needs overscan or inpainting.

Open items:
- Meshy gold and copper read dull under the Hex/Lit replica (baked lighting × sun); the material and
  lighting pass is open.
- The castle's minaret overshoots the sprite top by 58 px.

## Material and lighting pass (`bake_town_materials.py`)

Why the pilot read dull pink: the preview lit the city with arena defaults (sun ~1, flat blue ambient
(0.35,0.42,0.59)). The game's real city rig (static-asset, globalgamemanagers + cityHuman2): linear colour
space, `m_LightsUseLinearIntensity`, so the sun is colour.linear x 3.86 = (3.86, 2.77, 1.59), and the trilight
ambient is sky (0.314,0.301,0.474) / equator (0.0123,0.0143,0.0159) / ground (0.0037,0.0033,0.0027). The
installed Hex/Lit Lit pass is albedo x (SH ambient + sun x N.L x shadow + extra lights): no specular, metal or
normal map. The preview shader (`unity/Homm3TownLabHexLit.shader`) now takes that rig; the stock city is
rendered under both rigs for comparison (`unity_out/stock_cityHuman2_{arena_legacy,city_linear}.png`).

Because Hex/Lit cannot shine, burnish has to be in the base colour, and it must not be lit twice. The bake:

    albedo' = clamp( T( shade(meshy) ) / L(n), 0, 1 ),   L(n) = trilight(n) + sun * max(0, n.l)

- `shade` = Meshy base x L x (1 - 0.8 metal) + metal x base x (env reflection + Blinn-Phong sun spec), from
  Meshy's metallic/roughness maps. The env is warm sky / pale horizon / dark ground, which is what gives the
  domes their bright-top / dark-underside copper read.
- `T` = per-building colour transfer fitted on default-pose screen pixels (mesh visible and sprite alpha):
  L* quantile map + L*-banded chroma gain, hue kept. (A banded a*/b* mean shift was tried first; it turned
  the mage tower's blue gems purple.) Raw Meshy under the city rig is *more* saturated than the sprite (hall
  chroma 35.8 vs sprite 21.1); after T it is 21.6.
- Dividing by `L(n)` is the double-lighting treatment: the runtime sun and ambient are modelled and removed,
  so the in-game Lambert re-adds exactly what was divided out.
- The fountain (`tbeldw_2`) gets no transfer: its sprite pixels are mostly the water jets, an effect layer.
- The key light was fitted to the painting (Lambert vs per-building z-scored sprite luminance): travel
  (-0.785,-0.423,0.453), elevation 25 deg, from the front-right. The fit is weak (corr 0.13) but beats the
  city sun (-0.11), so the bake and the preview use it. In game this needs the town's directional light set
  to that direction (step 4); under the stock city sun the division is wrong on the lit/unlit split.

Limits (measured, `materials/bake_report.json`):
- Faces the key light misses get only the tiny equator ambient (~0.013), so their albedo clamps. The
  clamped share of visible pixels is <=1% on hall/market_b/dock, 4-7% on mage/silo/market_a/portal frame,
  10-17% on castle/tavern/blacksmith/specialty/dw_0. A fill directional light (Hex supports up to 4) or a
  lifted ambient would remove the clamp; that is a runtime lever and is untested.
- Reflection is view-dependent and baked for the fixed town camera; it will slide under camera moves.
- Sheet: `media/conflux_town3d_materials.png` (HoMM3 | raw Meshy under the city rig | material pass).
  Proof tier: generated artifact / Unity-editor replica render (not the game shader).

## Proportion fixes: hall and castle (no Meshy spend)

`STRETCH_FIT` in `build_conflux_town3d_preview.py` opts two buildings into a second fit pass
(`fit_mesh_to_sprite.Fitter.refine_stretch` / `refine_knee`); the rest keep the uniform-scale fit.

- **Hall (`tbelhall_4`) read squat.** Fitted vertical stretch (bounds 1.0-1.45) with a top-edge term
  (F-beta minus |mesh top - sprite top| / sprite height): stretch **1.189**, top offset 43 px -> 0 px, Unity
  IoU 0.731 -> 0.771 (precision 0.948 -> 0.921, recall 0.762 -> 0.826). Applied as localScale
  (s, s x 1.189, s); yaw about Y commutes with it.
- **Castle (`tbelcstl_3`) minaret overshot by 58 px.** A whole-body squash fixed the top but cost IoU
  (fit 0.501 -> 0.455) by shortening the walls, so it was rejected. Instead, knee surgery: `spire_knee` finds
  the height above which only the tallest spire exists (the highest vertex > 0.1 x width from the spire
  axis; a plateau at 0.718 of height for any radius 0.08-0.2 x width), and only the geometry above it is
  compressed, here x**0.471**. Top offset -58 -> +1 px, Unity IoU 0.544 -> 0.548, precision 0.967 -> 0.984.
  The castle's low recall is the painted mountainside inside its sprite, not the mesh.
- The preview applies the knee to per-instance mesh copies (`KneeRemap`); the bake applies the same remap
  (normals by the inverse-transpose); a plugin bundle must bake the surgery into the shipped mesh.
- The castle design gap (a clustered keep) was then closed by regeneration; see the next section.
- Sheet: `media/conflux_town3d_step2_hall_castle.png`. Proof tier: generated artifact / Unity-editor
  replica render.

## Castle regeneration and portal ornament

- **Castle regen** (coordinator relay 3, 36 credits under `conflux_placeable_2026-09-26`; approval now 756 of
  1200 committed). Virtual layer `tbelcstl_3_keep` crops the sprite to the keep (sprite px 190,0-322,120), since
  a1's source was mostly painted terrain, and the prompt states the HoMM3 layout: one tall central tower with
  a teal-and-gold cupola, four thin spires behind it, a large copper dome over the crested gate keep, teal
  onion-domed front corner towers, flat-topped back corner towers. First concept and mesh accepted (no retry).
- The fit target for it is the same keep box (`fitBox` in `STATE`; `fit_target()` is shared with the bake's
  colour transfer): against the whole sprite the fit inflated the castle over the painted terrain. Fit IoU
  0.736 against the keep, yaw 204 (its gate side), top within 8 px, so no knee surgery (the knee code stays
  for the a1 mesh). The alignment report's Unity IoU (0.42) is against the whole sprite, terrain included.
- **Hue-preserving clamp:** albedo above 1 is scaled by its largest channel instead of clipped per channel
  (the per-channel clip bleached clamped copper to grey). Castle clamped visible share 0.27.
- **Portal frame ornament:** the Meshy ring had none of the sprite's stars and gold filigree. `PROJECT_SPRITE`
  in the bake gives texels the town camera sees (39% of the ring's texels) the sprite's own colour divided by
  the modelled runtime light, blended by visibility and facing. It is paint, not geometry, and exact only at the
  default pose. No spend.
- Sheet: `media/conflux_town3d_castle_regen_portal.png` (HoMM3 | raw Meshy | material pass). Proof tier:
  generated artifact / Unity-editor replica render.

## Effects and animation

HoMM3 is the reference for **what moves and when**, not for the pixels. No HoMM3 sprite frames on flat
panels: every effect uses the vanilla OE mechanisms in `docs/olden_era_vanilla_vfx_style.md`.

HoMM3 Conflux motion inventory. Source: static-asset DEF frame deltas;
`artifacts/homm3_conflux_town3d/inventory/conflux_layers_inventory.json`, `conflux_anim_frames.png`.

| layer | frames | what moves |
|---|---|---|
| tbelblak | 14 | chimney smoke |
| tbeldw_0 (+hordes) | 10 | lantern house sways and glows |
| tbeldw_1 | 15 | floating stones/crystals circling the air shrine |
| tbeldw_2 | 8 | fountain water jets |
| tbeldw_3 | 8 | lava bubbling and flames |
| tbeldw_4 | 8 | earth ring glow |
| tbeldw_5 | 20 | portal surface swirl inside the ring |
| tbeldw_6 | 19 | firestorm vortex in the sky |
| tbelholy (grail) | 15 | aurora shimmer |

No motion: hall, castle, mage guild, tavern, market, silo, spec, dock, ext2.

How stock cityHuman2 animates. Source: static-asset, `stock_city_animation_probe.json` (43 animators, 134
particle systems, 109 self-animating materials).
- **Rigid-transform Animator loops on separate bones:**
  - tavern sign chain swing, 3 s;
  - mage guild L4 planets orbit, 30 s, plus a sun particle;
  - artifact-market arrow, 8.33 s;
  - depot barrel, 40 s;
  - ship roll, 13.3 s;
  - jousting horse, 7.2 s;
  - Tier 7 angels flying, 1.67 s.
- **Hex/Lit `HEX_VERTEX_DISPLACEMENT_FLAG`** (`_FlagSpeed`, `_FlagDirection`) for flags, cloth, awnings
  and foliage.
- **Hex/Lit emission + blink** for windows: HDR (11.98, 4.14, 0.19), BlinkPower 0.62. The radiant forge
  is blue (0.33, 1.36, 2.12).
- **Shuriken particles on `magic/VfxUber`:**
  - tavern chimney smoke: 3–4 systems, 10–15/s, life 2–3 s, size 0.2–0.8, speed 0.1–0.3;
  - Tier 1 pollen;
  - Tier 6 light symbols;
  - Tier 7 radiant forge: 30 systems plus a FlashLight;
  - golden calf: 39 systems.
- **Hex/Sea** and **`magic/Water_fire_stylized`** for water sheets.
- Hex/Lit `_UvScroll` for flowing dust.

Plan. Each moving part is its own object under the slot's BhBuilding, as in the stock city.

| Conflux layer | moving part | vanilla mechanism |
|---|---|---|
| tbelblak | chimney smoke | VfxUber smoke particles at a chimney-top socket, tavern values (3 systems, ~12/s, life 2.5 s) |
| tbeldw_0 | lantern sway + glow | separate lantern object pivoted at the vine tip, Animator rigid swing loop (~3 s, like the tavern chain); Hex/Lit emission blink on the windows (warm HDR, BlinkPower ~0.6) |
| tbeldw_1 | floating stones | small separate stone meshes on an orbit bone, Animator loop (mage-guild planets pattern, 20–30 s), a few VfxUber wind wisps; the shrine stays projected |
| tbeldw_2 | water jets | VfxUber / `Water_fire_stylized` jet particles from the dolphin spouts, plus a Hex/Sea basin surface (the mesh is dry by design) |
| tbeldw_3 | lava + flames | Hex/Lit emission + `_UvScroll` lava disc over the projected pit; VfxUber fire particles (phoenix palette) with short FlashLight bursts |
| tbeldw_4 | ring glow | emission-blink disc (earth tones) over the projected ring |
| tbeldw_5 | portal surface | **separate disc object** in the ring (today the static hole part): VfxUber two-noise scrolling material, HDR blue, slow Animator spin, a few sparks |
| tbeldw_6 | firestorm vortex | VfxUber fire particles on a vortex shape (orbital velocity), HDR orange; the sky layer stays projected |
| tbelmark_a/_b | awnings / pennants | `HEX_VERTEX_DISPLACEMENT_FLAG` on canvas and pennants |
| tbelholy (grail) | aurora | VfxUber ribbon particles (not in this state) |

## Runtime framing, key and fill light

- The preview now renders in the runtime layout `conflux_4k_outpaint_v1`: the 800x374 screen is scaled x3.6
  top-left onto the 3840x2160 outpainted plate (at 1920x1080: scale 1.8, town 1440x673); the smeared strip
  below 0.921 H is depth-edge-extended. All IoUs and sheets use that framing.
- Key light refitted in that framing: travel (-0.5265, -0.5736, 0.6275), elevation 35 deg, painting
  correlation 0.194. Catalog camera-local: (-0.554, -0.484, 0.677). The runtime sets it as the city
  LightingSettings volume's zenith/azimuth (see Plugin integration); colour and intensity stay stock.
- **Fill light** (`bake_town_materials.py --fill 0.35`): the key mirrored across the camera's vertical plane,
  elevation 20 deg, cool tint (0.85, 0.93, 1.12) x mean(sun) x 0.35 = linear (0.816, 0.892, 1.075), no
  shadows. World travel (0.678, -0.342, 0.651); catalog camera-local (0.644, -0.230, 0.730). The bake divides
  it out like the key, and the preview shader adds it (`_FillDir` / `_FillColor`). Pixel-weighted visible
  clamp 0.0259 -> 0.0019: castle keep 0.071 -> 0.003, tavern 0.107 -> 0.001, dw_0 0.064 -> 0, portal frame
  0.042 -> 0.003, hall 0.007 -> 0.002. Proof tier: generated artifact + Unity-editor replica render.
- Hall stretch (1.198) and any knee are baked into the shipped vertices (normals by inverse transpose); the
  regenerated castle needs no knee.
- Unity IoU per mesh (runtime framing): hall 0.85, castle keep 0.79, mage 0.65, tavern 0.89, blacksmith 0.60,
  market a 0.84 / b 0.77, silo 0.72, spec 0.46, dock 0.62, dw_0 0.45, dw_2 0.57, dw_5 0.63; mean 0.681.

## Plugin integration (`Homm3TownScene3d`)

- **Bundle** (`tools/homm3_town_scene_meshes/build_town_scene3d_bundle.py`, Unity side
  `unity/Homm3TownScene3dBundleBuild.cs`, via unitylock): one prefab per layer whose root *is* the reference
  camera frame. Pieces are `Mesh_<name>` (baked albedo, Unlit placeholder material rebound at runtime),
  2D depth-grid sprites `Sprite_<name>`, and `Anim_PortalDisc`. Everything is scaled about the camera by
  `depthScale` 0.526 (projection-invariant) so the farthest point sits inside 72, in front of the backdrop
  quad at 80. Staged at `OfflineUnlockMod/homm3_town_scene_meshes/scene3d/homm3_conflux/`
  (`homm3_town_scene3d_conflux`, gitignored, 24,509,799 bytes, sha256 recorded in `catalog.json`).
- **Readback:** `--verify` loads the staged bundle, seats it as the runtime does, and renders per-layer masks;
  min IoU 0.9992 against the preview (`artifacts/homm3_conflux_town3d/scene3d_bundle/readback_report.json`).
- **Runtime** (`Homm3TownScene3d.cs`, wired from `Homm3FactoryCityWorldVisuals`): the root is placed at the
  live camera pose with scale (kx, ky, 1), where ky = tan(fov/2)/tan(fov_ref/2) and kx = ky x aspect/aspect_ref.
  So the registration follows camera moves (re-seated on reposition), FOV and aspect. Each layer instance
  sits under the scene root. Its Mesh_ body is rebound to a clean stock Hex/Lit donor (fewest shaderKeywords)
  with the baked albedo. The native BhBuilding is moved to the body's bounds centre, so SpawnEffect and
  construction FX land on it, and its BoxCollider is aligned to the body (clickable buildings). Construction
  state follows the native per-level variant loop; layers not built this visit are removed. HotA 2D layers
  that remain use catalog `layerDepths` (median painted depth under their opaque pixels, scaled) instead of
  the backdrop distance, so they sort against the meshes as painted. Lighting: key direction and fog off go
  through the city's `Hex.Render.LightingSettings` post-process volume, plus one added fill directional light;
  all restored on Clear. The Hex pipeline's per-camera render (`bdr::kqq` -> `bdw::ktg`, static disassembly)
  sets the main light's rotation to `AngleAxis(lightAzimuthAngle, up) * AngleAxis(lightZenithAngle, right)`
  and writes `RenderSettings.fog` from the blended volume on every render. The first in-game run rotated the
  sun transform and set `RenderSettings.fog` directly, and both were overwritten before the next render. The
  lane now overrides `lightZenithAngle = asin(-d.y)`, `lightAzimuthAngle = atan2(d.x, d.z)` and
  `fogEnabled = false` on an instanced copy of each LightingSettings volume profile (cityHuman2: under
  `CityCamera`). On Clear it sets `profile = null` and destroys the copy, so the shared asset is never written.
  With no such volume it fails closed.
  The diag block logs:
  - per camera: depth, culling mask and the directional lights it admits;
  - per directional light: `offKeyDeg`, where the Hex main light near 0 means the override landed;
  - the Hex globals, which belong to the last-rendered camera.
  `bdw::ktd` counts every visible directional light (up to 4) into `_DirectionalLightsCount`, so the earlier
  single global read (count 1) came from whichever camera rendered last and does not show that the fill
  misses the city camera.
- **Building coverage (2026-09-26 in-game report):** layers apply from the native build state, not the full
  preview town. The first in-game town had three built layers: Main L1 (`tbelhall`), Tier_1 (`tbeldw_0`) and
  Tier_2 (`tbeldw_1`). At that point only `tbeldw_0` was meshed, so one mesh and two 2D layers was the correct output.
- **Lower-tier town states (2026-09-26, user-approved; 36 Meshy credits):** the catalog now meshes 23 layers (was
  12). Every reachable building layer that the preview draws as a mesh now has one at every native level.
  - Hall `tbelhall`/`tbelhall_2`, fort `tbelcstl`/`tbelcstl_2` and mage `tbelmage`/`_2`/`_3` reuse the a1 meshes
    already generated under approval `conflux_placeable_2026-09-26` (same concept -> meshy-7 lane, same ledger).
    No new calls were made; Meshy balance was 8400, checked before starting.
  - `tbelcstl_2` a1 stood on a full-footprint slab: its bottom 3% of height spans 1.90 x 1.90, against 1.48 for
    the walls. The interim cut, `cut_ground_plate.py` -> `tbelcstl_2_noplate`, is glTF-level surgery with no spend.
    It removed the slab but left a plain wall block.
  - The fort is now regenerated as `tbelcstl_2_keep`, under approval `conflux_lower_tier_2026-09-26` (cap 600).
    - Spend: concept 6 cr + meshy-7 30 cr = 36; the ledger total is 900.
    - Input critique: the (190,0,322,120) keep crop still carries painted hillside and a grass strip. A colour
      matte cut into the teal domes, so it was not used. The concept prompt states the exact layout and forbids
      a plate or terrain.
    - Concept review before the mesh was paid for: the fort was isolated on white, with no plate, and the layout
      matched.
    - Mesh: footprint 1.80 x 0.74, no slab, a shallow facade. Fit IoU 0.774, was 0.741.
  - Lower mage towers use the hall's stretch pass (`STRETCH_FIT`, 1.0-1.45): the uniform fit stopped short of the
    dome. stretchY is 1.22, 1.38 and 1.25.
  - Upgrade dwellings `tbeldw_0_2`/`_2_2`/`_5_2` and the horde `tbelhrd2` are the base mesh again. Their HoMM3
    sprites repeat the base building: `tbeldw_1..5 _2` differ from their base by an animation frame only (mean
    |diff| 3-14/255), and `_0_2`/`hrd2` add a painted garden and mushrooms. So each is registered against the
    base sprite (`fitLayer`), with the same transform and the base's baked texture (`bakeAs`). The upgrade's own
    painted ground becomes that instance's skirt (`skirtFrac` 1.0). `tbelhrd2` (Resource_Depot_level_2) can show
    together with Tier_1: its mesh coincides with the dwelling's, exactly as the 2D sprite repeats the lantern.
  - Terrain-embedded and sky dwellings stay projected 2D, as in the preview: `tbeldw_1`/`_3`/`_4` and their
    upgrades, `tbeldw_6`/`_6_2` (firestorm), `tbelholy` (aurora) and `tbelext2`. The earlier note that
    "dwellings 1/3/4/6 need Meshy" was wrong. The preview never meshed them; the lava pit a1 is a slab (IoU 0.32).
  - Registration is one town state at a time. `VARIANT_STATES` in `build_conflux_town3d_preview.py` defines
    `level1`/`level2`/`level3`: the full town with those slots replaced. Each state gets its own HoMM3 composite,
    Depth Anything pass and aligned depth. Skirts, holes and projected layers are therefore cut against the town
    they are shown in. The full state, key light, fill, depthScale, layerDepths and all 14 full-state baked
    textures are byte-identical to before.
  - Unity mask IoU vs sprite, with the full-state value in brackets where it is shared:
    - hall 0.79 / 0.75 [capitol 0.85]
    - fort 0.76 / 0.74 (noplate) [0.79]
    - mage 0.69 / 0.68 / 0.64 [0.65]
    - dwelling reuses keep their base values
  - State means: IoU full 0.681, level1 0.677, level2 0.673, level3 0.680. Town |diff| 12.6 / 10.1 / 11.2 / 12.7 RGB.
  - Sheets: `media/conflux_town3d_level{1,2,3}_side_by_side.png` and `_town_closeup.png` (HoMM3 above Unity).
  - **Lava pit fix:** `tbeldw_3` never showed in any preview render, full state included. Depth Anything reads
    the painted crater as a hollow, and 86% of its pixels were projected behind the backdrop depth surface. The
    air shrine `tbeldw_1` had 56% behind the surface.
    - Composite depth is now clamped to the plate surface (`aligned_z`): a painted layer lies on or in front of
      the terrain it is painted on. Town |diff| fell 12.6 -> 10.7 (full) and 11.2 -> 9.3 (level2).
    - The runtime was not affected: its backdrop is a flat quad at 80 and every layerDepth is at 72 or less.
      But the same clamp moves 14 painted-terrain `layerDepths` up to 1.4 closer (e.g. `tbeldw_3` 40.14 -> 38.83).
      depthScale is unchanged.
- **Gates:** `tools/validate_town_scene3d_contract.py`, run BeforeBuild in `OfflineUnlockMod.csproj`, checks
  schema parity, no `IsKeywordEnabled`, owned fraction, layers/depths vs positions.json, unit light
  directions, fog off and bundle sha. The bundle must be staged when the flag is on. At startup the preloader
  fails closed on a bad payload when the flag is on.
- **Hall level (product choice, 2026-09-26):** OE's Main has three levels and HotA has four halls; the meshed
  hall is the capitol `tbelhall_4`. The Conflux `building_layer_map.json` declares
  `nativeLevelSourceOverrides {"Build_Main": {"3": 4}}`, so the third hall level shows the capitol, 2D or
  3D. The HotA City Hall `tbelhall_3` is recorded in `unusedLayers` with its reason.
  `tools/generate_owned_city_native_levels.py` applies overrides and fails when a displaced layer is not
  recorded. The contract fails on a meshed layer that no nativeLevels entry or decoration row reaches, and
  on an `unusedLayers` entry that is still reached or meshed. Before this, the capitol mesh never rendered.
  Proof: source/static and generated artifact; runtime unproven.
- **Enable:** set `"homm3TownScene3d": true` in `config.json` and deploy (the existing
  `homm3_town_scene_meshes\**` deploy item carries the scene3d folder). Not deployed by this pass.

## Animation built, and the effects gap list

- Built: `tbeldw_5` portal disc, a camera-facing disc inside the ring with an Animator loop (z 0 -> -360 over 14 s,
  AlwaysAnimate).
- Not built:
  - `tbeldw_0` lantern sway: the lantern is fused into the dwelling mesh (one welded component, 5752
    nodes), so there is no separable part to pivot.
  - `tbeldw_1` stone orbit: that layer has no mesh (it stays a projected 2D layer).
  Both are recorded in the catalog's `notAnimated`.
- Gaps for the effects lane (vanilla mechanisms from `docs/olden_era_vanilla_vfx_style.md`, owned there):
  - a building-anchored vanillaParticles host;
  - a source for stock city particle systems (chimney smoke, fountain jets);
  - emissionMap support for town building materials (lantern glow, lava);
  - a portal swirl material for the disc;
  - `HEX_VERTEX_DISPLACEMENT_FLAG` cloth wave on the market awnings.

## Proof tiers (this pass)

- Meshy meshes: generated artifact (20/20 SUCCEEDED, reviewed on the thumbnail sheet).
- Alignment numbers, overlay, diff and camera-move video: Unity-editor render with the preview Hex/Lit
  replica. This is not the game shader and not in-game.
- Stock animation vocabulary and HoMM3 motion inventory: static-asset.
- Material pass: generated artifact (baked base colours) + Unity-editor replica render under the modelled
  city rig. Not the game shader, not in game.
- Effects: plan only; nothing built or rendered.
- Effects: portal disc spin built (Animator in the bundle); everything else is the gap list above.
- Fill light: generated artifact + Unity-editor replica render (clamp numbers above).
- Bundle: generated artifact, Unity-editor readback (min IoU 0.9992 vs the preview masks; 23 layers after the
  lower-tier pass).
- Lower-tier states: generated artifact + Unity-editor replica render per state. Not in game.
- Plugin: source/static (`validate_town_scene3d_contract.py`) + build target (Golden Era OfficialDeobf
  build, live-interop gate). Deployed, startup, runtime and user-visible gameplay remain unproven.

## Known risks

Painted 2.5D backdrop vs real meshes (style clash, parallax under camera movement); baked Meshy lighting
under the Hex/Lit sun (double lighting); ~45 per-level layers; collider re-alignment; construction
SpawnEffect anchor (the lane moves BhBuilding.position to the body centre); 800x374 -> 16:9 crop (bottom
band is edge-extended). Runtime unknowns: whether the pipeline publishes a second directional light to
Hex/Lit in the city camera (the fill; see the diag block), whether the LightingSettings override lands
(the `offKeyDeg` readback), and non-16:9 displays (kx/ky scale keeps the registration but not the backdrop
fit). Lowest-IoU meshes: spec 0.46, dw_0 0.45, dw_2 0.57, blacksmith 0.60.
