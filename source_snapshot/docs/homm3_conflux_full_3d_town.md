# Conflux town screen as a complete 3D scene

**Current (2026-09-28): phase 6b is staged and installed.** User-approved 6b catalog SHA-256 `e5356521...` and bundle
`8f638512...` are staged in the plugin tree, byte-identical to the Golden Era install (deployed payload proven). The town
validator declares the Conflux lane's scatter in `CONFLUX_LANE_SCATTER` (commit 3db569ff00). Runtime and user-visible
look of 6b are unproven until a town visit. The phase-5 bundle was overwritten in the plugin tree and no copy is kept.

Status: **staged with runtime support** (2026-09-27). The candidate bundle and catalog below are staged in
`OfflineUnlockMod/homm3_town_scene_meshes/scene3d/homm3_conflux/`, and `Homm3TownScene3d.cs` /
`Homm3FactoryCityWorldVisuals.cs` implement the runtime spec at the end of this doc. Proof tier: generated artifact +
source/static + build target; runtime and user-visible look unproven until a town visit on an install. The superseded
2.5D catalog is commit 529ffdce42 (bundle sha f1501756, archived at `F:/homm3_conflux_full3d/superseded_2p5d_529ffdce42/`).

**Phase 2 candidate (2026-09-27, not staged, not installed):** rebuilt after the in-game review of scene 833433d820 /
runtime 856b1f29eb / catalog 095033dc / bundle 1e8ffd6b. See "Phase 2" below; it needs no runtime change. Proof tier:
generated artifact + editor render; nothing of it has been seen in game.

User decision, 2026-09-26: the Conflux town screen must be fully 3D. Today it mixes 2D HotA sprite layers (backdrop,
plate, skirts, remaining building art) with a few meshes, and the user judged that mix will never look good.

Related: `docs/conflux_town3d_pilot.md` (the scene3d lane this extends), `docs/custom_town_scene_paradigm.md`.
Machine-readable inventory: `tools/homm3_town_scene_meshes/conflux_full3d_inventory.json`.

## Inventory (what the town screen shows, and how it becomes 3D)

Only layers that a native level reaches can be seen (`building_layer_map.json` `nativeLevels`, the runtime join for
owned city worlds). Source art is `town_scene_refs/homm3_conflux/layers/<layer>.png`; the backdrop is
`mockups/homm3_conflux_background_upscaled_3840x2160.png` (the 800x374 HoMM3 screen at x3.6 top-left, the right
third and the bottom band outpainted).

### Buildings

| slot | lvl | layer | now | plan | credits |
|---|---|---|---|---|---|
| Main | 1 / 2 / 3 | tbelhall / _2 / _4 | mesh + skirt/hole sprites | reuse meshes, drop sprites | 0 |
| Wall | 1 / 2 / 3 | tbelcstl / _2 / _3 | mesh + sprites (painted hillside, river) | reuse, drop sprites | 0 |
| Magic_Guild | 1-4 | tbelmage .. _4 | mesh + sprites | reuse, drop sprites | 0 |
| Tavern, Treasury, Bank, Market, Resource_Depot, Artifact_Market | 1 | tbeltvrn, tbelblak, tbelspec, tbelmark, tbelsilo, tbeldock | mesh (+ skirts) | reuse, drop sprites | 0 |
| Resource_Depot_level_2 | 1 | tbelhrd2 | lantern mesh + painted mushroom garden | reuse + Meshy mushroom cluster | 36 |
| Tier_1 | 1 / 2 | tbeldw_0 / _0_2 | mesh (+ garden skirt on _2) | reuse; _2 gets the mushrooms | 0 |
| Tier_2 | 1 / 2 | tbeldw_1 / _1_2 | **2D quad** (air shrine on a snowy crag) | Meshy | 36 |
| Tier_3 | 1 / 2 | tbeldw_2 / _2_2 | mesh (dry fountain) | reuse + procedural water surface | 0 |
| Tier_4 | 1 / 2 | tbeldw_3 / _3_2 | **2D quad** (lava pit) | reuse the unshipped pilot mesh `tbeldw_3/mesh_a1` + lava glow | 0 |
| Tier_5 | 1 / 2 | tbeldw_4 / _4_2 | **2D quad** (earth ring) | Meshy standing-stone ring | 36 |
| Tier_6 | 1 / 2 | tbeldw_5 / _5_2 | mesh + skirt, painted-pixel portal disc | reuse; procedural swirl disc | 0 |
| Tier_7 | 1 / 2 | tbeldw_6 / _6_2 | **2D quad** (fire vortex over a peak) | procedural vent rock + fire vortex | 0 |
| Golden_Calf (grail) | 1 | tbelholy | **2D quad** (aurora) | procedural aurora ribbons + cairn | 0 |

Unreachable (no native level; nothing drawn, nothing built): `tbelhall_3` (unusedLayers), `tbelmage_5`, `tbelext2`
(Build_Mother_Nature has no nativeLevels entry), `tbelext4` (transparent placeholder), `tbelhrd1`, `tbel2hrd2`, and
every `tbeldw_*_3` (OE dwellings have two levels).

### Environment

| element | now | plan | credits |
|---|---|---|---|
| backdrop quad (sky, peaks, valley, rivers, waterfall, outpaint) | 2D quad at 80 | removed when `fullScene3d` | 0 |
| black plate quad | 2D quad at 80.5 | removed when `fullScene3d` | 0 |
| terrain: valley, hills, cliffs, banks, far mountains | painted pixels + 16 skirts | procedural lit mesh from the registered depth surface; albedo synthesised per class | 30 (5 tile textures) |
| rivers, waterfall, pond | painted pixels | procedural `Water_` mesh | 0 |
| sky and clouds | painted pixels | procedural `Sky_` dome | 0 |
| forest, bushes | painted pixels | Meshy conifer x2 + bush, scattered | 108 |
| boulders | painted pixels | Meshy boulder cluster, scattered | 36 |
| stone footbridge | painted pixels | Meshy | 36 |

Estimate: **354 credits** base, 144 retry reserve, **cap 500**. Conflux has no `decoration` rows in positions.json.

## Meshy spend log

Balance before the first call: 8004 (2026-09-26). Budget: up to 8000 (coordinator relay; spend what the scene needs;
stop if the balance would fall below 500; note the running total at every 2000 spent).

| task id | kind | credits | input image | purpose |
|---|---|---|---|---|
| `01a0e0f4-3643-74d7-b693-9677594fc4cd` | image-to-image | 6 | `prop_boulders/source_prep.png` | prop_boulders: scatter vegetation/rocks |
| `01a0e0f4-3a4d-7170-a33e-9452f0f881c8` | image-to-image | 6 | `prop_bridge/source_prep.png` | prop_bridge: river footbridge |
| `01a0e0f4-3297-709b-87a4-1710422154c2` | image-to-image | 6 | `prop_bush/source_prep.png` | prop_bush: scatter vegetation/rocks |
| `01a0e0f4-2a5a-7531-a3cb-0cbbdc8b12ee` | image-to-image | 6 | `prop_conifer_a/source_prep.png` | prop_conifer_a: scatter vegetation/rocks |
| `01a0e0f4-2ea4-7121-a3ca-cea71c08f376` | image-to-image | 6 | `prop_conifer_b/source_prep.png` | prop_conifer_b: scatter vegetation/rocks |
| `01a0e0f4-2611-720f-a205-7fa4801d8e9d` | image-to-image | 6 | `prop_mushrooms/source_prep.png` | prop_mushrooms: mushroom garden (Tier_1 upgrade / depot 2 skirt) |
| `01a0e0f4-1d4d-7027-8b60-16dee266a558` | image-to-image | 6 | `tbeldw_1/source_prep.png` | tbeldw_1: Tier_2 air shrine (was 2D quad) |
| `01a0e0f4-2181-7136-9c3d-dc07a32bc674` | image-to-image | 6 | `tbeldw_4/source_prep.png` | tbeldw_4: Tier_5 earth ring (was 2D quad) |
| `01a0e0f4-4ddc-76cf-93fc-027a9c2fba06` | image-to-image | 6 | `tile_dirt/source_prep.png` | tile_dirt: terrain tile texture |
| `01a0e0f4-41bf-76af-9f29-8200cb622eb0` | image-to-image | 6 | `tile_forest/source_prep.png` | tile_forest: terrain tile texture |
| `01a0e0f4-3e01-72c4-bccc-a1c49da39c69` | image-to-image | 6 | `tile_grass/source_prep.png` | tile_grass: terrain tile texture |
| `01a0e0f4-45af-700d-8f45-e73097ca91bb` | image-to-image | 6 | `tile_rock/source_prep.png` | tile_rock: terrain tile texture |
| `01a0e0f4-49c3-71df-a1db-d137107cb6e4` | image-to-image | 6 | `tile_snow/source_prep.png` | tile_snow: terrain tile texture |
| `01a0e0f5-3785-775f-bf6d-85bbcff6acf1` | image-to-3d | 30 | `prop_boulders/concept_a1/concept.png` | prop_boulders: scatter vegetation/rocks |
| `01a0e0f5-3d56-767e-a923-b23f92bba38b` | image-to-3d | 30 | `prop_bridge/concept_a1/concept.png` | prop_bridge: river footbridge |
| `01a0e0f5-31e0-75e4-9270-f6849480e257` | image-to-3d | 30 | `prop_bush/concept_a1/concept.png` | prop_bush: scatter vegetation/rocks |
| `01a0e0f5-268f-7134-80e2-e43c2736efcb` | image-to-3d | 30 | `prop_conifer_a/concept_a1/concept.png` | prop_conifer_a: scatter vegetation/rocks |
| `01a0e0f5-2bb9-7629-9aaa-cda7b18d29a0` | image-to-3d | 30 | `prop_conifer_b/concept_a1/concept.png` | prop_conifer_b: scatter vegetation/rocks |
| `01a0e0f5-2072-7794-9161-aa750e95833a` | image-to-3d | 30 | `prop_mushrooms/concept_a1/concept.png` | prop_mushrooms: mushroom garden (Tier_1 upgrade / depot 2 skirt) |
| `01a0e0f5-14e5-7286-b24c-d0f8d3e01d5d` | image-to-3d | 30 | `tbeldw_1/concept_a1/concept.png` | tbeldw_1: Tier_2 air shrine (was 2D quad) |
| `01a0e0f5-1ae0-75e3-81ae-d64def849c29` | image-to-3d | 30 | `tbeldw_4/concept_a1/concept.png` | tbeldw_4: Tier_5 earth ring (was 2D quad) |

Running total under `conflux_full3d_2026-09-26`: **318 credits** (13 concepts x 6, 8 meshes x 30); shared balance after: 7686.
All outputs under `artifacts/meshy_town_scene_meshes/homm3_conflux/<layer>/`. Mesh review (Meshy thumbnails): all eight are clean single objects with no ground slab; tbeldw_1 kept its cloud swirls as carved geometry (fits the air motif, kept).

No further Meshy calls after these 21: every other element is reused or procedural. Total **318 credits**, well under
the first 2000 threshold, so no threshold entry was due.

## Build

`python tools/homm3_town_scene_meshes/build_conflux_full3d_scene.py stage|bundle|render|report` (Unity only through
`tools/homm3_vfx/unitylock.py`, which runs memgate).

* **Data root is on F:** (`F:/homm3_conflux_full3d`, override `CONFLUX_FULL3D_ROOT`). The shared V: drive hit 0 bytes
  free mid-build on 2026-09-26 (`OSError [WinError 112]`); only this lane's own partial output was removed. The bundle
  is built in a dedicated built-in-module Unity project under that root, never in the shared `oldenera_factions`
  project. Every mesh, buildings included, is baked into the camera frame in Python, so no glTF importer is needed.
* Bundle `homm3_town_scene3d_conflux` (same file name as the staged 2.5D bundle it replaces), prefab prefix
  `homm3_conflux3d_`: one `homm3_conflux3d_environment` prefab (Mesh_Terrain, Mesh_Water, Sky_Dome, Mesh_Bridge,
  Mesh_Scatter_conifer_a/b/bush) plus one prefab per reachable layer (32). Every building prefab has at least one
  `Mesh_` child (Tier_7 and the grail carry small Mesh_ rock anchors under their `Fx_` pieces).
* Terrain: the registered depth surface over the whole 16:9 frame (outpaint smoothed), albedo from the Meshy tiles
  (triplanar luminance detail) times a de-lit macro colour of the painting, divided by the Hex/Lit rig so the lit
  result returns the painted colour. Water: the water class, flattened. Sky: camera-centred dome (radius 185 world,
  ~97 prefab units).
* Scatter: 176 conifers (joint Poisson draw, two variants), 35 bushes. Boulders are optional and currently place 0
  (on the painted cliffs they floated on the depth estimate's noisy rock faces).
* Placement notes: new dwellings tbeldw_1 / tbeldw_4 are silhouette-fitted (IoU 0.73 / 0.70) and sunk 15% of their
  height into the terrain; the pilot lava plateau tbeldw_3 is a flat slab that a silhouette fit inflated to 16x, so it
  is placed by the sprite's width at its bottom-centre ground point, stairs to camera, tilted 28 deg toward the camera.
  The Unity projects render in Linear colour space (as the game does); the first Gamma render was overexposed.

## Result (generated artifact)

Renders from the cityHuman2 reference camera, magenta clear so any hole shows (none does):

* `F:/homm3_conflux_full3d/renders/full3d_start.png` (tbelhall, tbeldw_0, tbeldw_1)
* `F:/homm3_conflux_full3d/renders/full3d_mid.png` (11 layers)
* `F:/homm3_conflux_full3d/renders/full3d_full.png` (18 layers incl. Tier_7 vortex and grail aurora)
* `F:/homm3_conflux_full3d/renders/full3d_full_sway_{0,1,2}.png` (lateral camera sway: parallax check)
* `F:/homm3_conflux_full3d/work/full3d_states_sheet.png` (contact sheet)

| file | sha256 |
|---|---|
| `F:/homm3_conflux_full3d/bundle/homm3_town_scene3d_conflux` (82,564,943 bytes) | `1e8ffd6bb7f0f45b0c55e712e8ac87a2ed369786281399e0f61099a22da53dcf` |
| `F:/homm3_conflux_full3d/bundle/catalog.json` | `095033dc104a38f1bfbdb872933739eeb23ca9c95747f33c7bd8504eb10f646b` |

Known weaknesses, visible in the full render: the outpainted right third (x > 1440 of 1920) is a blurred cliff because
the source there is outpaint, not HoMM3 art; the reused capitol mesh sits above the painted ground line at the lab's
registered placement; the aurora is static and striped rather than shimmering; the vortex is a helical strand funnel,
not a volumetric fire. None of these is a 2D element.

## Phase 2 (2026-09-27): review fixes

Only two references are used: the HoMM3 Conflux town screen (`Conflux-in-background.png`, 800x374, placed at x1.8 =
1440x673 top-left of the 1920x1080 frame) and the HoMM3 building art (`layers/*.png`). The old 2D backdrop, its
outpaint and every derivative are gone from the pipeline (`catalog.references`; the validator refuses "plate",
"outpaint" and "backdrop" there). Code: `build_conflux_full3d_scene.py` (orchestration), `conflux_full3d_env.py`
(terrain, extension, sky, water flow), `conflux_full3d_integration.py` (footing skirts, patches),
`unity/shaders/*.shader` (bundle effect shaders), `unity/Homm3TownScene3dBundleBuild.cs` (fxmesh + particle builds).
Work files: `F:/homm3_conflux_full3d/work2/`.

1. **Sharp background.** Inside the HoMM3 rect the terrain is depth-registered to the HoMM3 screen itself (monocular
   disparity calibrated through the building ground contacts). Outside it (right third, bottom band) the ground is a
   ray-marched 3D heightmap continued from the HoMM3 terrain, textured with sharp tiles tone-matched per channel to
   the seam; the sky is a dome built from the HoMM3 sky. No pixel of the frame comes from an upscale or outpaint, so
   the right cliff is geometry, not a blur. Small disparity drop-outs inside the mountains (snow glare) are filled
   as terrain, and grid normals that bridge a depth step are pulled toward up + viewer; both had left dark specks
   along the ridges (35 -> 2 dark px in the ridge window of the start render).
2. **Facing.** Every building mesh was scored against its HoMM3 sprite at 0/90/180/270 deg plus a fine yaw sweep
   (`work2/facing.json`, `facing_sheet.png`). Only the Altar of Air (tbeldw_1 / tbeldw_1_2) was wrong: it now faces
   the camera at yaw 177 (silhouette IoU 0.70). All others kept their yaw.
3. **Integration.** Each building gets a `Mesh_Skirt_<layer>`: the HoMM3 sprite's own ground pixels around its base,
   rasterised onto the terrain depth and lifted ~3% so the base blends into the ground (no float, no sunk plinth, no
   cut edge). The lava pit (tbeldw_3) is now the sprite's whole crater as a registered patch. Scatter was trimmed
   from the near foreground (no bushes nearer than 20 m, boulders 14-45 m inside the HoMM3 rect, conifers kept off a
   61 px band under each building). Scale, placement and lighting follow the HoMM3 screen (buildings at their
   positions.json anchors; Hex/Lit rig unchanged).
4. **Rivers flow toward the camera.** `Fx_Water` carries UV1 = (across-stream metres, geodesic metres downstream from
   each river's mountain source); `Homm3Conflux/FlowWater` samples its ripples at `y - t * speed`, so the pattern moves
   down each river, round its bends, toward the camera (`work2/flow_v.png`, `phase2_motion_sheet.png`).
5. **Effects** (vanilla Olden Era VfxUber-style particles and shaders, no ripped flipbooks; everything is in the
   prefabs, so it also plays in previews):
   * pyre (tbeldw_6): VentRock anchor + `Fx_Pyre_*` particle group: base glow, flames, a 13.5 m flame column, a flat
     turning cloud (orange heart -> violet rim, radius ~9 m), cloud glow, smoke, embers;
   * lava pit (tbeldw_3): `Fx_Lava_*` (`Homm3Conflux/Lava`: the sprite's own painted lava modulated by two scrolling
     vanilla lava layers) + `Fx_FirePit_*` particles (glow, flames, smoke, embers);
   * magic portal (tbeldw_5): `Fx_Portal_*` (`Homm3Conflux/Portal`: differential-rotation spiral, inward flow, bright
     core) replaces the rigidly spinning disc;
   * grail (tbelholy): `Fx_Aurora` (`Homm3Conflux/Aurora`: drifting rays, travelling folds, breathing) replaces the
     static curtain.
   Not animated in phase 2: tbeldw_0 (lantern) and tbeldw_2 (fountain); both are covered by Phase 4 below.

**Runtime:** no change needed. The runtime re-materials only `MeshRenderer`s. The `Fx_` effect meshes are drawn by
bone-less `SkinnedMeshRenderer`s and the particles by `ParticleSystemRenderer`s, so both keep their bundle
materials and shaders. The bundle is built for D3D11 + D3D12. *Fallback spec* (only if the bundle shaders fail to
render in game, e.g. pink): the runtime would need to drive `Fx_Water` itself with a material that scrolls UV1.y
downstream at 1.4 m/s over the painted tint, and to give `Fx_Lava_*` / `Fx_Portal_*` / `Fx_Aurora` the sprite
material with a UV scroll/rotation. Route that to the town-runtime owner (`Homm3TownScene3d.cs`,
`Homm3FactoryCityWorldVisuals.cs`); this lane does not edit them.

Sheets (editor renders, cityHuman2 camera): `F:/homm3_conflux_full3d/work2/phase2_before_after_sheet.png` (HoMM3
reference | phase 1 installed | phase 2, for start/mid/full), `phase2_closeups_sheet.png` (fort, right cliff, fire
pit, pyre + aurora, air shrine + rivers), `phase2_motion_sheet.png` (t = 0 / 1.5 s, flow coordinate, difference),
`full3d_parallax_sheet.png`.

| phase 2 file | sha256 |
|---|---|
| `F:/homm3_conflux_full3d/bundle/homm3_town_scene3d_conflux` (87,529,444 bytes) | `7327f1876386b5529747e8529c2177c6558de269b7928512110c72184366db7e` |
| `F:/homm3_conflux_full3d/bundle/catalog.json` | `5c972aae4530820f9fddaff9aad94d9d1c8d9abb89a3bc6c5975ca4fe6c71537` |

Known weaknesses: the pyre cloud reads pinker than the HoMM3 orange/violet; the bottom-right extension is plain
meadow with a wide river mouth; the custom bundle shaders and particles are unproven in game. Meshy spend is unchanged
at 318 credits (no Meshy in phase 2).

## Phase 3 (2026-09-27): terrain detail at building texel density

Review: the terrain read far lower-resolution than the building meshes. Cause: the terrain albedo is registered to the
HoMM3 screen, so inside the town rect it holds 0.56 source texels per 1080p pixel however large the bake is.

Fix (`tools/homm3_town_scene_meshes/conflux_full3d_detail.py`, called from `stage` in the builder): the HoMM3-derived
albedo stays the macro colour and the only composition reference, and tiling detail from the game's own terrain
textures is multiplied into it, then baked into the same `Mesh_Terrain*` / `Mesh_Skirt_*` albedo (the runtime
re-materials those renderers to Hex/Lit with their own mainTexture, so a custom terrain shader would be replaced;
**no runtime change is needed**). No AI upscale, outpaint, blur or Meshy.

* **Sources** (read-only UnityPy extract from the installed Golden Era `HeroesOldenEra_Data/resources.assets`, cached
  at `F:/homm3_conflux_full3d/vanilla_terrain/`, provenance with sha256 in the catalog's `terrainDetail`): grass
  `grass1` (pathId 5783, 512), dirt / river bank `dirt_ground3` (5911, 512), rock `512_6_dirt_rock4_diffuse` (7797,
  512), snow `Snow2` (6931, 1024). All four tile seamlessly. The extracted textures are not committed.
* **Splat** from the macro map's own classes and slope: grass/forest -> grass, steep (40-58 deg) -> rock, rock ->
  rock, snow -> snow, a 1.5 m dirt band along every river bank; nothing on water or sky.
* **Modulation**: each texture becomes a mean-1 luminance (+ a little chroma) map high-passed at size/24 texels (grain,
  not blotches), raised to a per-layer strength. Painted shadows (macro luminance < 0.3-0.7 of its 12 px
  neighbourhood) fade the detail out so the HoMM3 light/shade modelling of the crags survives; on grass and dirt the
  macro's own sub-2 px painted grain is damped to 0.75.
* **Projection**: level ground seen from above takes a top-down world projection with distance levels; everything
  else (grazing meadow, slopes, right cliff, mountain faces) takes the fixed reference camera's image plane at 0.3 px
  per detail texel, two octaves, prefiltered to the bake texel. Measured and rejected on the way: a 3-axis triplanar
  and an orthographic camera-plane projection on the depth-derived normals smeared the pattern along the view, and a
  geometric-mean normalisation / unconditioned rock detail laid a grey haze over the painted crags.
* The footing skirts get the same detail at 2x (same frame positions, so they continue into the terrain), which also
  covers the bottom-right meadow extension, the right cliff and the mountain faces.

**Texel density** (texels per 1080p pixel at the cityHuman2 camera, area-weighted, `stage_report.json` `texelDensity`):
buildings median 2.06 (p10 1.05, p90 4.93) texture texels/px, about 1 visible after GPU mip. Terrain before 0.56 in
the town rect (fort and Altar of Air windows 0.56), 0.61 median on the extension. Terrain after: 2.0 bake texels/px
everywhere, with vanilla detail present down to the bake texel, so about 1 visible after mip, the same as the
buildings. High-frequency energy of the rendered terrain (mean |L - Gauss1.5(L)|, 8-bit, `work2/phase3_hf_energy.json`):

| window | before | after |
|---|---|---|
| frame | 6.2 | 6.82 |
| fort | 7.22 | 8.03 |
| altar_of_air | 5.72 | 6.32 |
| foreground | 5.44 | 5.82 |
| right_cliff_meadow | 4.23 | 5.53 |
| meadow_extension | 5.03 | 5.24 |

Sheets (editor renders): `F:/homm3_conflux_full3d/work2/phase3_before_after_sheet.png` (HoMM3 | phase 2 | phase 3),
`phase3_closeups_sheet.png` (fort, Altar of Air, foreground river, right cliff, meadow extension, mountain faces,
pyre; 2x), `phase3_density_sheet.png`. The before renders are `CONFLUX_DETAIL_OFF=1` builds kept in
`F:/homm3_conflux_full3d/renders_phase2/`.

Phase-2 weak spots: the pyre cloud and column keys were moved from pink-violet to orange-red -> violet and the cloud
glow to orange. It still reads pinker than HoMM3 in the editor render. The bottom-right meadow is still empty and the
river mouth still straight; neither was addressed.

Proof tier: generated artifact + editor render. Not installed and not seen in game. Meshy spend unchanged at 318.

## Phase 3b (2026-09-27): near field, water, altar footing, pyre, meadow

Review of phase 3 (installed, catalog cd77a0ee / bundle 052bdfdb): the right cliff and mountains improved, but the
terrain nearest the camera barely changed, the rivers were flat with stair-stepped edges, the Altar of Air floated on a
hard-edged snow slab, the pyre was a pink mushroom plume, and the bottom-right meadow was empty with a straight river
mouth. All changes are on the generated-artifact side; **no runtime change is needed** (terrain/footing are still
`Mesh_` albedo, water and fire are still `Fx_` pieces on bundle shaders).

* **Near-field terrain sharpness.** Two causes, both fixed. (1) Sampling: the frame-registered albedo holds 2 texels
  per 1080p pixel, so trilinear sampling sat on mip 1 everywhere and averaged away the detail the bake carries. The
  terrain and footing textures now import with `mipMapBias -1` and `anisoLevel 8` (`TERRAIN_MIP_BIAS`,
  `TERRAIN_ANISO`; `Homm3TownScene3dBundleBuild.Tex`). Both serialize with the Texture2D, and the runtime keeps
  `mainTexture` when it rebinds Hex/Lit, so they should survive in game (catalog `terrainSampler`; unproven in game).
  (2) The macro's dark blotches in the extension (outside the HoMM3 rect: the foreground and the meadow) overpowered
  the detail and also tripped the painted-shadow gate, which then faded the detail out inside them. Outside the rect
  the macro's mid-scale pattern is flattened (`EXT_KEEP 0.4` above a 10 px low-pass), the blotches are compressed
  toward a 60 px base as a luminance ratio (`EXT_BLOTCH_GAMMA 0.45`, hue kept), the shadow gate reads the flattened
  macro, and the detail gets `EXT_DETAIL_GAIN 1.35`. The top-down projection's detail texel went from 2.0 to 0.6 bake
  texels.
* **Water** (`unity/shaders/Homm3ConfluxFlowWater.shader`, `conflux_full3d_env.water_mesh`). The vanilla Olden Era
  river material `Mtl_River_Water` (Hex/Sea, resources.assets pathId 4170) was read for its recipe: normal map
  `WaterNormal` (pathId 6555, sha256 in the catalog's `waterLook`; extracted to
  `F:/homm3_conflux_full3d/vanilla_recipes/tex/`, not committed), reflection opacity 0.279, a fixed specular direction
  (azimuth/zenith, not the scene sun), deep (0.093, 0.259, 0.462) / shallow (0.3, 0.712, 0.849) absorption colours,
  shore foam. The FlowWater shader now carries two scrolling layers of WaterNormal in the flow frame (flow direction
  unchanged: still UV1.y downstream), Blinn specular toward a light 22 deg above the far horizon, a fresnel sky
  reflection (sky colour = median painted HoMM3 sky) at 0.28, a depth tint from the vanilla deep/shallow ratio
  (`_Deep 0.7` over 16 px from the bank) and a thin broken foam line. The water tint's alpha is now a shore
  coordinate: the signed distance to a smoothed bank (`SHORE_OUT 6` px outside, `SHORE_RANGE 32`), so the surface is
  alpha-feathered across the bank instead of cut on the pixel mask (no stairs).
* **River mouths.** Extension channels meander (`MEANDER_AMP 0.75` rad, `MEANDER_LEN 14` m, eased in over the first
  6 m so each leaves the HoMM3 exit on its painted heading) and pool/narrow along their length. Both the bottom-right
  mouth and the left river's exit toward the bottom-left now curve.
* **Altar of Air footing** (`conflux_full3d_integration.ledge`). Its mesh ends in a slab over a far slope, so there
  is no painted ground for `skirt()`. A ledge membrane covers the slab's side/underside band (16 px, drawn just in
  front of the mesh) and runs down to the slope: a thin noise-broken snow rim, then the mountain's own lit crag rock
  (upper-luminance median of the ROCK class near the altar) with vertical snow streaks, feathered into the painted
  slope, with a ragged lower edge. Its shading normal is a camera-facing mountain face: the geometric normal of a
  curtain receding to the far slope faces down and rendered it as a black block. The slab's dark underside line is
  gone and the base reads as a snowy outcrop.
* **Pyre** (`pyre_systems`): a narrow twisting column (radius R*0.025, strong orbital swirl) under a flat spreading
  cap: a thin disc of particles carried outward while it turns (orange heart; `cap` material = Map_fire_02 at lower
  intensity and more alpha so overlaps no longer blow out to pink) plus a violet rim ring just under the disc edge.
  The glow is orange at low alpha and the smoke is flatter and violet-dark.
* **Bottom-right meadow** (`meadow_dressing`): three conifer groves framing the right edge (conifer_a 9, conifer_b 7,
  on slopes too) and 5 boulders along the banks, from the existing Meshy props (no new spend). Round bushes were
  dropped because they read as green balls.

**Sharpness** (mean |L - Gauss1.5(L)| of the 8-bit render luminance; terrain = live splat minus the building meshes'
screen coverage dilated 15 px, eroded 5; buildings = building coverage eroded 5; `work2/phase3b_hf_energy.json`,
written by `report`). The phase-3 table above used a crude "unchanged pixels" building mask that read ~9. With the
real coverage mask the buildings measure ~15, because their silhouettes and ornament carry edges the terrain does not
have.

| window | terrain phase 3 | terrain 3b | buildings |
|---|---|---|---|
| frame | 6.67 | 8.33 | 15.17 |
| fort | 7.97 | 9.06 | 16.02 |
| altar_of_air | 5.42 | 6.26 | 20.35 |
| foreground | 5.13 | 7.77 | - |
| meadow | 5.21 | 8.35 | - |
| right_cliff | 5.53 | 7.61 | - |

The foreground and meadow terrain rose 50-60 % and now sit near the fort's terrain (~9, the old building figure).
They do not reach the buildings' own edge energy, and a grass field should not.

Sheets: `F:/homm3_conflux_full3d/work2/phase3b_states_sheet.png` (HoMM3 | phase 3 | phase 3b for start / mid / full)
and `phase3b_closeups_sheet.png` (foreground, meadow + river mouth, water banks, Altar of Air, pyre, fort). The phase-3
renders are kept in `F:/homm3_conflux_full3d/renders_phase3/`.

Remaining: the river bank dirt band shows `dirt_ground3`'s cracked-earth cells clearly at the nearest banks; the
left river thins into a pale haze where it leaves the HoMM3 rect (present since phase 2); the pyre cap's orange heart
is rounder than HoMM3's fan.

Proof tier: generated artifact + editor render. Not installed and not seen in game. Meshy spend unchanged at 318.

## Phase 4 (2026-09-27): building-animation audit

The user's phase-3b check found the Altar of Water dry, so every Conflux building DEF was re-audited. Frame counts
come from the SoD `H3sprite.lod` DEF headers (block frame counts); the HotA-only layers use
`layers/anims/metadata.json`, which the plugin tree carries beside the layer sprites and which agrees with the lod for
every SoD layer. What moves was read from the frame differences, i.e. the pixels where frame k differs from frame 0
by more than 20 (`def_motion` in the builder).

Static in HoMM3 (DEF has 1 frame): tbelhall, tbelhall_2/_3/_4, tbelcstl, tbelcstl_2/_3, tbelmage, tbelmage_2..5,
tbeltvrn, tbelmark, tbelsilo, tbeldock, tbelspec, tbelext2, tbelext4. The HoMM3 town background (rivers, waterfall,
sky) is a static bitmap; our `Fx_Water` flow is an addition, not a port.

| Building (layer) | HoMM3 DEF frames | What moves in the DEF | Our effect (catalog pieces) | Status |
|---|---|---|---|---|
| Blacksmith (tbelblak) | 14 | dark grey smoke billowing from the forge chimney | `Fx_Smoke_tbelblak`: grey VfxUber smoke plume + puffs from the mesh's chimney mouth, rising the DEF's plume height (3.9 m) | new |
| Magic Lantern (tbeldw_0) | 10 | the lantern's light flickering in its glass | `Fx_Lantern_tbeldw_0`: short overlapping warm glows of random strength, a bright core, a soft halo at the glass | new |
| Magic Lantern upg. (tbeldw_0_2) | 10 | same | `Fx_Lantern_tbeldw_0_2` | new |
| Lantern horde (tbelhrd2) | 10 | the same lantern (same sprite position as tbeldw_0_2) | `sharedWith: tbeldw_0_2`, no doubled glow | new |
| Altar of Air (tbeldw_1) | 15 | six crystals glinting in turn; white shimmer in the doorway | `Fx_AirGlints_tbeldw_1`: a sparkle on each crystal's DEF position snapped to the mesh, a breathing doorway light with rising motes | new |
| Altar of Air upg. (tbeldw_1_2) | 15 | same | `Fx_AirGlints_tbeldw_1_2` (the base DEF's parts: the upgrade's doorway shimmer merges with two crystals) | new |
| Altar of Water (tbeldw_2) | 8 | white jets arcing from the central vase into the basin; splash and foam | `Fx_Basin_` (FlowWater surface filling the basin to 85% of its rim, rings running outward), `Fx_FountainJets_` (a central column + six arcing FlowWater ribbons, streaks running down each jet), `Fx_FountainSpray_` (splash at each landing point, foam ring, mist) | new |
| Altar of Water upg. (tbeldw_2_2) | 8 | same | `Fx_Basin_/Fx_FountainJets_/Fx_FountainSpray_tbeldw_2_2` | new |
| Altar of Fire (tbeldw_3) | 8 | lava churning in the crater; glowing steps | `Fx_Lava_tbeldw_3` (Homm3Conflux/Lava) + `Fx_FirePit_tbeldw_3` | phase 2, re-checked |
| Altar of Fire upg. (tbeldw_3_2) | 8 | same | `Fx_Lava_/Fx_FirePit_tbeldw_3_2` | phase 2, re-checked |
| Altar of Earth (tbeldw_4) | 8 | glittering bright points over the stone ring | `Fx_EarthGlints_tbeldw_4`: sparkles (grow and vanish) in a box over the DEF's moving region, at the ring's depth | new |
| Altar of Earth upg. (tbeldw_4_2) | 8 | same, reaching up the spires | `Fx_EarthGlints_tbeldw_4_2` | new |
| Magic portal (tbeldw_5) | 20 | the orb swirling inside the ring | `Fx_Portal_tbeldw_5` (Homm3Conflux/Portal) | phase 2, re-checked |
| Magic portal upg. (tbeldw_5_2) | 21 | same | `Fx_Portal_tbeldw_5_2` | phase 2, re-checked |
| Pyre (tbeldw_6) | 19 | fire column into a swirling fire cloud | `Fx_Pyre_tbeldw_6` | phase 3b, re-checked |
| Pyre upg. (tbeldw_6_2) | 19 | same | `Fx_Pyre_tbeldw_6_2` | phase 3b, re-checked |
| Grail (tbelholy) | 15 | aurora curtains rippling across the sky | `Fx_Aurora` (Homm3Conflux/Aurora) | phase 2, re-checked |

Not in the catalog (no native level reaches them): tbelhrd1 (10 frames, the non-upgraded horde's lantern) and the
HotA `_3` variants (tbel2hrd2 10, tbeldw_0_3 10, tbeldw_1_3 15, tbeldw_2_3..4_3 8, tbeldw_5_3 21, tbeldw_6_3 19).

How the new effects are placed (`building_animations` in the builder):

* Every effect is anchored in the DEF's own moving pixels, mapped to the frame at the layer's position (x1.8) and
  snapped to the building mesh's rasterised depth (the footing loop now keeps each layer's mesh depth).
* Blacksmith: our mesh's chimney is taller than HoMM3's, so the plume starts at the mesh's chimney mouth (its
  highest 2 % of vertices, frame px 864, 279) rather than the DEF's plume base (854, 374); the plume height is the
  DEF's. A lighter-grey first pass disappeared against the snow and sky behind it; the delivered plume is mid-grey
  with a lower smoothstep ceiling (0.3) so a single stream of puffs stays opaque.
* Water altar: the basin mesh is a closed box with a floor at y 3.13 and a rim at 4.18. The water plane sits at 85 %
  of that height (4.02) over the floor's footprint (a superellipse, half axes 1.83 x 1.81 m). The jets follow the
  DEF's heights (apex 24 sprite px, vase 16 above the water, 1.79 m and 1.19 m). They are camera-facing FlowWater
  ribbons (uv1 = across / arc metres; a centre-peaked shore alpha feathers each edge into foam). The splash rises
  from above the front rim, which otherwise hides the water line. Both water materials use the vanilla WaterNormal
  and the rivers' specular direction and sky colour.
* A render-time pitfall is recorded in the builder: FlowWater's `_Speed x _Scale` must not be a whole number of
  noise tiles per second. The first jet material had exactly 4.0, so the t = 1 s render repeated t = 0.
* Lantern: a glow in the glass is the DEF's whole motion. The lantern stays part of the dwelling mesh; cutting it out
  was not needed for a light flicker.

Render and proof:

* The render spec gained per-state `timed` (C# `StateSpec.timed`, editor-side `Homm3TownScene3dBundleBuild.cs` only)
  and an `anim_base` state (environment + tbeldw_0..6), so every animated base and upgrade layer is rendered at
  `TIME_FRAMES = [0.0, 1.0]`.
* The motion sheets are `F:/homm3_conflux_full3d/work2/phase4_motion_sheet_{0,1,2}.png`. Each row shows HoMM3 DEF
  frame 0, a middle frame, our render at t = 0 and t = 1 s, and |t1 - t0| x4. `phase4_motion.json` counts crop
  pixels whose luminance changes by more than 10: every animated layer moves, from 107 (Altar of Earth, sparse
  sparkles) to 5099 (pyre). The fountain moves 1543 px and the smoke 3941 px.

Remaining: the earth sparkles are small and sparse, as in HoMM3, and read only up close. The smoke leaves from the
taller mesh chimney, not HoMM3's squat one.

Catalog: `"phaseRevision": "4"`, `animationAudit` {layer: defFrames, moves, effects[, sharedWith]}; the stale
`notAnimated` block is gone. Proof tier: generated artifact + editor render. Not installed and not seen in game.
Meshy spend unchanged at 318.

## Phase 5 (2026-09-27): near field and right edge

The user's in-game review: a cutoff near the camera and along the right edge, where the phase 1-4 extension was
blurry ("close up geometry is generally expected to have the MOST detail, not the least"). Cause: the extension
outside the 1440x673 HoMM3 rect was seamless crops of the 800x374 painting upscaled 2x and tiled in world space, with
a mirrored feather along the frame rectangle. The phase-4 editor render at 3840x2160 shows the near grass magnified
and soft. The module is `tools/homm3_town_scene_meshes/conflux_full3d_nearfield.py` (N5); the builder calls it.

What changed (no runtime .cs change; the runtime still takes Mesh_ pieces with a mainTexture):

* **Albedo.** Outside the rect the terrain is synthesised from the vanilla Olden Era terrain textures (grass1,
  dirt_ground3, 512_6_dirt_rock4_diffuse, Snow2; `resources.assets` pathId + sha256 in the catalog): each is a
  full-colour mean-1 layer, sampled at three rotated scales mixed by world fbm, with a 0.53x octave nearer than
  16 m, side projection on slopes, a contrast power (grass 1.9, dirt 1.4, rock 1.2), world-noise gain and hue, and
  wet banks. The painting is **low-frequency colour only**: its albedo blurred with sigma 10 px inside the rect;
  outside it, class colours pulled toward the rect's edge colour. No painted crop is upscaled or tiled, and the
  painting is not mirrored.
* **Seam.** The synthesis ramps into the rect over a world-space band: 3.5 m from the seam, at least 200 px at
  1080p, broken by world noise that scales with the distance. The edge colour tone uses an e-folding of 5 m, at
  least 260 px. Three step lines found in renders were fixed:
  * a grass/dirt-only ramp left a hard rock edge at x = 1440;
  * additive noise let the ramp sit at 0.5 exactly on the seam;
  * the nearest-ground-pixel edge colour jumped across a river mouth, drawing a line at x ~ 388.

  The depth kink where the calibrated rect depth meets the heightmap (slope -0.06 against -0.02 m/px) turned the
  normals into a lit/unlit step down x = 1440. `seam_depth` smooths the inverse depth over a 70 px band. It moves
  along each pixel's ray and changes depth by at most 4 %.
* **Texel density.** The terrain is split into pieces that share vertices:

  | Pieces | Where | Texels / 1080p px |
  |---|---|---|
  | `Mesh_TerrainNear_0..3` | below y ~ 560, noise-jittered | 4 |
  | `Mesh_TerrainRight` | x > ~1320, 190 < y < the near boundary | 3 |
  | `Mesh_Terrain` | the rest | 2 |

  The buildings' median is 2.06 texels/px. The synthesis bake filters anisotropically: up to 8 lookups down a
  grazing texel's column. An isotropic lookup had aliased into horizontal streaks on the right-hand slopes.
* **Relief.** Undulation, bumps and grassy mounds (0.09 / 0.03 / 0.10 m) in the extension's near field, displaced
  along each vertex's camera ray (screen registration unchanged). The relief fades between 22 and 32 m and stays off
  water, plots and steep ground.
* **Near-field geometry.** Merged lit Mesh_ bins, one draw each:

  | Bin | Count | Tris | What |
  |---|---|---|---|
  | `Mesh_NearGrass` | 3175 tufts | 180k | camera-facing blades; 32-colour palette k-means'd from the ground colour; to 60 m on synthesised ground |
  | `Mesh_NearFlowers` | 50 clumps | 2.8k | Conflux elemental palette at 0.6 albedo; round five-lobed heads (a first star shape read as sparkles) |
  | `Mesh_NearPebbles` | 451 | 36k | along banks and the water's edge |
  | `Mesh_NearRocks` | 3 | 3.8k | larger pieces |
  | `Mesh_NearRoots` | 16 conifers | 3.7k | exposed roots at near conifers |

  Pebbles and rocks are textured from rock4 swatches in the Meshy boulders' colour. The painting's rock class colour
  had made a near rock black.

  Density is rho*(8/z)^k per m2; tufts get a floor of 3/m2 beyond 26 m. Size grows toward the camera
  (1 + 0.6*smoothstep(18, 9, z)).

  Tuft sites by depth are 777 at 0-12 m, 1265 at 12-18 m, 655 at 18-26 m and 478 at 26-60 m. The near band is the
  narrowest in area, so the per-m2 density rises toward the camera by construction.
* **Other fixes.**
  * The terrain grid now reaches x = W and y = H: the last pixel row had shown the clear colour (magenta) in every
    render since phase 1.
  * `decimate` now welds seams and transfers UVs by per-face barycentrics. The previous nearest-vertex UV mixed UV
    charts, and the decimated Meshy bushes and boulders rendered as shattered shards.

Assumptions, not measured:
* the HUD covers the bottom 64 px of the 1080p frame (`HUD_BOTTOM_PX`), and no dressing is placed there;
* there is no fly-path data, so tall pieces keep off each plot's screen corridor toward the camera (the conifer
  rule);
* the game's cull mode for the Hex/Lit donor is unknown. The dressing is wound like the terrain, and the blades face
  the camera.

Meshy spend is 0 in phase 5; the total stays at 318.

Proof (editor renders at the reference camera, 1080p and 3840x2160; the user plays at 4096x2160). The sheets are in
`F:/homm3_conflux_full3d/work2/`:
* `phase5_before_after_4k.png`: bottom band, right edge and seam corner, phase 4 | phase 5;
* `phase5_{bottom_band,right_edge,seam_corner}_4k_1to1.png`;
* `phase5_full_frame.png`;
* `phase5_parallax_near.png`: the near field under camera sway, -2.5 / 0 / +2.5 m;
* `phase5_metrics.json`.

Sharpness is the mean |L - Gauss1.5(L)| over terrain and dressing pixels, by relieved ground depth. Phase 4 is the
installed bundle ac8f215a:

| Region | 1080p before | 1080p after | 4K before | 4K after |
|---|---|---|---|---|
| buildings | 15.13 | 15.22 | 11.23 | 11.13 |
| far (z >= 45 m) | 7.62 | 8.11 | 4.30 | 4.84 |
| mid (22-45 m) | 10.86 | 9.37 | 8.28 | 7.21 |
| near (12-22 m) | 8.48 | 6.97 | 5.62 | 5.77 |
| nearest (< 12 m) | 7.45 | 4.91 | 4.45 | 3.89 |
| right edge (x >= 1600) | 7.80 | 7.25 | 5.75 | 5.85 |

Read this honestly:
* The per-pixel HF measure does **not** rise far to near, and at 1080p the nearest band scores lower than phase 4.
* The phase-4 near field was high-contrast painted texture magnified; its grain is at the pixel scale, which this
  measure rewards.
* The phase-5 near field is real blades and pebbles many pixels wide (see the 1:1 crops). That detail sits above the
  1.5 px scale.
* At 4K the near band now exceeds phase 4 and the far band, and the right edge improves. Only the nearest band is
  still lower.
* A synthesis contrast of 1.0 had scored 4.08 / 3.13. The contrast power and denser tufts were raised because of that.

The requirement "sharpness rises far to near" is therefore **met visually but not by this metric**.

Seam visibility: per 24 px segment, the step in mean luminance across the line over the mean standard deviation of
the 10 px strips on either side (median). Control lines sit 100 px inside the rect.

| Line | 1080p before | 1080p after | 4K before | 4K after |
|---|---|---|---|---|
| right seam x = 1440 | 0.685 | 0.483 | 0.685 | 0.493 |
| bottom seam y = 673 | 0.362 | 0.488 | 0.360 | 0.415 |
| control x = 1340 | 0.497 | 0.431 | 0.483 | 0.432 |
| control y = 573 | 0.404 | 0.325 | 0.410 | 0.282 |

* The right seam's step now sits near its control (0.48 against 0.43).
* The bottom seam is 0.49 against its control's 0.33 at 1080p: there the painted meadow meets the synthesised grass,
  which has a different grain. It is the remaining measurable boundary.

Catalog: `"phaseRevision": "5"` and `nearField`, which carries:
* `extensionAlbedo`: the sources with sha256, `paintingRole` and `paintedCrops: false`;
* `seamBlend`;
* `texturePieces` with texelsPerPx;
* `buildingsTexelsPerPx`, `relief`, `dressing` and `sitesByDepth`;
* `hudBottomPx`, `assumptions` and `meshyCredits`.

The render spec gained `hires` (the C# `HiresSpec`, editor-side only), which shoots the full state and the sway at
3840x2160.

The phase-5 bundle was subsequently installed in Golden Era (bundle SHA-256
`6005e85e7f045c47b3eb112413d7c53a72b03dcd00b9138577eab65cbbe8d115`). The user saw an improved town,
but its camera pan exposed the left and right terrain limits. The editor measures above are phase-5 evidence, not
phase-6 coverage proof. Frame cost remains unmeasured: dressing adds about 227k triangles in 5 draws, and the
terrain pieces add 5 draws.

## Phase 6: Pan Periphery (bundle and editor renders, 2026-09-27; not installed)

The Golden Era `cityHuman2` town camera is a moving `BhCityCameraController`, not a fixed default screenshot.
`extract_city_camera_pan.py` reads its `CityCamera` pivot, child `MainCamera` rest transform and
`SoCityCameraSettings` directly from installed `level67` / `resources.assets`; two other vanilla cities can be used
for render comparison. The full-3D runtime's v2 catalog seats the scene at that authored rest pose relative to the
fixed pivot, instead of following the live camera as the legacy v1 catalog does. The v2 C# path has compiled through
the OfficialDeobf target and passed live-interop reference verification, but runtime seating has not been observed
in the game. The normal build is separately blocked by unrelated asset/motion gates.

The V: phase-6 stage output is `artifacts/homm3_conflux_full3d_phase6/` (`CONFLUX_FULL3D_ROOT`); its old F: phase-5
texture extracts are read-only inputs through `CONFLUX_FULL3D_SOURCE_ROOT`. The staged outer world adds eight
retained terrain pieces (82,712 triangles), two continued river ribbons (`Fx_WaterOuter`, 1,601 triangles), and 11
merged scatter bins using already-owned conifer, bush and boulder meshes. The stage report records 326 conifer and
44 boulder sites wholly outside the default frame, 1,290 outer vertices moved behind the frame, and zero vertex
intrusions. It spent no new Meshy credits. The stage completed with exit code 0; the catalog and coverage raster
are generated candidates, not a Unity bundle. Stage-only catalog SHA-256:
`45f2cb23cbf6910dd4ae2f83d76a4f5c4ef68a92dd68f0b6fca62bd2e000ce9c`; coverage raster SHA-256:
`7a33f7721beef691550918af7cc80dad18c177818c6ab46b495e3267331bc3d7`.

The v2 validator re-extracts `cityHuman2` from the installed native assets rather than trusting the mutable camera
JSON's own hashes. It requires the continued water and nonempty forest/rock bins, then raymarches the saved
post-settle triangle-height raster at sampled Default, Cursor, Free and mode-transition poses, at 16:9, 4096x2160
and 21:9. The candidate gate passed in 31 seconds: 990,000 sampled rays, zero proxy voids; stripping the outer
coverage made 1.3% of canonical 16:9 rays fail (negative sensitivity check). Five focused tests include native-row
drift refusal, missing water/tree/rock refusal, the old pre-settle false hit, and the exact mathematical image border.
The installed phase-5 v1 gate still passes. The new gate is wired to the existing build/deploy validator but no
phase-6 bundle or deployment has passed it yet.

Limits remain explicit: this is a 0.5 m sampled height proxy, not exact triangle or pixel visibility; the zero
intrusions count checks vertices, not triangle pixels. The exact native spline basis and fly-to paths are not
recovered. Default-frame, pan-extreme and wide-aspect Unity editor renders (including comparison against phase 5
and vanilla town views) must decide visual acceptance before any installation. No phase-6 runtime or user-visible
claim has been made.

### Phase 6 bundle and editor renders (generated artifact + editor render tier)

The guarded Unity bundle build (unitylock, memgate, game-process guard; `CONFLUX_FULL3D_ROOT` on V:) produced
`bundle/homm3_town_scene3d_conflux` (kept as `bundle_phase6/` once 6b was built) (157,151,152 bytes, SHA-256
`df2b1517d8c39fdf289104d253b36aac4c8a1355260c1fb22506bf223690871b`). The bundle and render steps stamp the catalog, so
the catalog to install beside it is SHA-256 `d4d50d8d1ae94ccd8eb96ebad0f837ffd14523ad7eeaeaab5d80e9e1515677dc`;
`pan_coverage.npz` (`7a33f772...`) must be staged beside it for the validator. The candidate gate on that final
catalog: `OK ... restPose=installed-native-verified ... panRays=990000 panVoid=0 panNeg16x9=0.013`.

Pan poses are rendered by `RenderStates` from `pan_render_specs()` (default, cursor left/right, sweep left/right,
sweep high; the default and sweep extremes again at 4096x2160 and 21:9). A pan camera's offset is world metres
applied under the aspect-scaled root, so the editor places it at `root.position + root.rotation * pos` (not scaled
by the root's `scaleX`). The same spec was rendered against the phase-5 bundle for comparison. Magenta (unfilled
clear) pixel share, phase 5 -> phase 6:

| pose | 16:9 | 4096x2160 | 21:9 |
|---|---|---|---|
| default | 0 -> 0 | 0 -> 0 | 0 -> 0 |
| sweep_left | 6.46% -> 0 | 5.70% -> 0 | 3.23% -> 0 |
| sweep_right | 2.04% -> 0 | 1.42% -> 0 | 0.04% -> 0 |
| sweep_high | 5.76% -> 0 | - | - |

Default-frame registration is unchanged: phase 5 and phase 6 `pan_default.png` differ by a mean of 0.0096/255 per
channel. The proof sheet (vanilla | phase 5 | phase 6, rows default/sweep_left/sweep_right at the three aspects) is
`artifacts/homm3_conflux_full3d_phase6/work6/pan_sheet_vanilla_p5_p6.png`
(SHA-256 `324fb329...`).

The vanilla column renders the exported `cityHuman2` scene at the same extracted pan poses (`work6/vanilla_pan.py`,
moderngl). It approximates the vanilla Hex/Lit shading with flat-colour terrain and sea and the scene fog colour,
and 4096x2160 is rendered at half size, so it compares framing and the periphery idiom (continuous terrain to fogged
distance, scatter thinning outward), not final look. Vanilla fills every pan pose with world; phase 6 now does too.

**Silhouette curtain streak (diagnosed, not fixed).** The streaked bands visible at the sweep poses (mid ridge and
mountain silhouettes, upper half of the frame) are inherited from phase 5: the screen-space terrain grid bridges
depth discontinuities where a near ridge occludes far terrain. 1,713 grid triangles have a forward-depth ratio above
1.25 (median longest edge 41 m), 702 above 1.5, 51 above 2, all at y < 360 of the 1280x720 grid. They are edge-on
along the rest-frame rays, so the default frame is clean, and become stretched bands once the camera moves. The
proposed single fix: cut those bridging triangles, and add a back-layer surface that continues the far side a few
cells under the near ridge (depth push-pulled from the far side, far-side colour), so the rest frame stays covered
and a moved camera sees continued far terrain. Diagnostic: `work6/curtain.py`, `work6/curtain_view.png`.

No installation, runtime seating, or user-visible claim is made for phase 6; Meshy spend remains 0. Phase 6b
supersedes the phase-6 bundle for installation.

## Phase 6b: ridge-curtain cut and back layer (bundle and editor renders, 2026-09-27; installed 2026-09-28)

`conflux_full3d_curtain.py` (called from the stage right after the terrain grid is built):

* **Cut.** Every terrain triangle whose rest-camera forward-depth ratio (max/min over its vertices) exceeds 1.25 is
  removed from the grid: 1,713 triangles, worst ratio 2.228.
* **Cut-cell patches.** Each cut cell is re-covered by its own vertex copies on the same rest rays. Far vertices stay
  on the main surface; near vertices move back only as far as the cap needs (least change to the rest frame's
  perspective interpolation). They keep their own frame UV and normal, so the default frame shows the same cell.
* **Extension.** Vertices up to 40 grid cells (120 px) under the near side of a cut get a copy pushed onto a
  continuation of the far surface: a normalised-convolution push-pull of far-side depths (sigma 3 cells) anchored to
  the nearest silhouette vertex. It is textured from the far side (the vertex mirrored across its silhouette when
  that lands on far ground, else the silhouette vertex). The patches sit in front of it, so it is hidden at rest and
  is what a moved camera sees under the ridge.
* **Flattened tiles.** Where the continued far surface itself steps (two far layers behind one ridge), 400 extension
  cells get their own copies pushed to within the cap of their farthest vertex instead of becoming new curtains.
* Result: 45,409 back-layer triangles in `Mesh_Back_Terrain` (terrain_albedo.png) and `Mesh_Back_TerrainRight`
  (the right piece's texture). The maximum shipped ratio is 1.250.

Gate: `terrainStreak` in the catalog pins `terrain_streak.npz` (every shipped terrain triangle, main and back layer,
in painting-world space, plus the cut triangles). The validator re-measures the rest forward-depth ratio of all of
them against `STREAK_RATIO_CAP = 1.25`. As a negative, the stored cut triangles must each exceed the cap and match
`cutTris`, so the measurement is shown to see the curtains the phase-6 grid shipped. Focused tests:
`test_phase6b_streak_contract.py` (7). They cover the cut and cap on a synthetic ridge grid, back-layer vertices on
rest rays, and refusals for a main-mesh curtain, a back-layer curtain, a negative that cannot fail, a loose cap and
a missing back-layer bin. The phase-6 pan tests (6) still pass.

Build (unitylock, memgate, game-process guard; `CONFLUX_FULL3D_ROOT` on V:; the phase-6 bundle and renders were kept
as `bundle_phase6/` and `renders_phase6/`):

* bundle `homm3_town_scene3d_conflux`: 158,012,008 bytes, SHA-256
  `8f638512dd0a8f39d31c592640fb3617bab99a62a209a97ed9fa3b84f05997bc`
* catalog (after the bundle and render stamps): SHA-256
  `e53565218d9aece08efdd44f21f91b8582fc175a890e6864e36c8194d560c0ac`
* `pan_coverage.npz`: `7a33f7721beef691550918af7cc80dad18c177818c6ab46b495e3267331bc3d7` (unchanged)
* `terrain_streak.npz`: `fb79a490bb66872f15dcaf5d5edefa9b0f7897e8be1efdd9193c0e7013b647de`

Both npz files must sit beside the catalog. Candidate gate:
`OK ... restPose=installed-native-verified ... panRays=990000 panVoid=0 panNeg16x9=0.013 streakMax=1.250 streakNeg=1713`.

Editor renders (same 12 pan poses): no magenta at any pose or aspect. Default-frame registration against phase 6
(mean abs diff per channel, 0-255):

| frame | mean | pixels over 8 |
|---|---|---|
| pan_default 16:9 | 0.0081 | 522 |
| pan_default 4096x2160 | 0.0079 | 2130 |
| pan_default 21:9 | 0.0079 | 666 |
| full3d_full | 0.0081 | 522 |

The before/after sheet (phase 6 | 6b at sweep_left and sweep_right_21x9, full frame plus ridge zoom) is
`artifacts/homm3_conflux_full3d_phase6/work6b/streak_sheet_phase6_vs_6b.png`; metrics are in `streak_metrics.json`
beside it.

What it fixes and what remains:

* The bridging curtains are gone. The left mountain's curtain now opens onto sky and terrain behind it, and the mid
  ridge's streak bands become far-side ground.
* Residuals:
  * The back layer's mirrored far-side texture still reads as a coarse smear where it is exposed.
  * Thin cracks between unshared patch/tile copies show the sky dome or outer terrain behind.
  * The tall snowy peak's receding right face streaks in phase 5, 6 and 6b alike. That is the depth map's own fin
    (triangles along the rays but under the 1.25 ratio at 250-300 m), not a bridge.
  * A pan-parallax cap is not a usable alternative: at the 11 m maximum pan offset it flags ordinary near ground
    (6,061 triangles over 12 px, median ratio 1.05 at 34 m). The next lever for fins would be a grazing-angle test.

Proof tier: generated artifact + editor render. Not installed, runtime unproven. Meshy spend 0.

## Validator

`tools/validate_town_scene3d_contract.py` (already a BeforeBuild target of OfflineUnlockMod) enforces, when a catalog
says `"fullScene3d": true`: every reachable layer has a 3D prefab, no sprites, empty `layerDepths`,
`"backdrop": "hidden"`, an environment with Mesh_Terrain and a Sky_ dome, only Mesh_/Sky_/Fx_ piece names, the
bundle build report lists every prefab with `sprites=0`, and a *staged* full-3D catalog requires
`Homm3TownScene3d.cs` to parse `fullScene3d`. `--catalog <path>` checks a candidate outside the plugin tree. Phase-2 catalogs (`"phase": 2`) also need references
free of the backdrop/outpaint lineage, `bundleShaders` each declared under `unity/shaders/` with `_TimeOffset` /
`_TimeScale`, a built bin or particle system behind every `Fx_` prefab, and reasons for `notAnimated`. Phase-3 catalogs (`"phase": 3`) also need `terrainDetail.sources`, each a game `.assets`
Texture2D with `pathId` + `sha256`, and no upscale/Meshy lineage (negative check: a source without sha256 fails).
Phase-3b catalogs (`"phaseRevision": "3b"`) also need `waterLook.sources` (game `.assets` textures with `pathId` +
`sha256`) and a `waterLook.shader` that is a declared bundle shader exposing `_NormalMap` / `_ShoreRange` /
`_ShoreOut` / `_SpecDir` (negative check: a non-integer pathId fails).
Phase-4 catalogs (`"phaseRevision": "4"`) also need `animationAudit`: every catalog layer whose HoMM3 DEF has
more than one frame (`layers/anims/metadata.json`) has a row with the matching `defFrames`, `moves`, and a non-empty
`effects` list of `Fx_` pieces of that layer (or of its `sharedWith` layer); a static layer may not have a row.
Negative checks on mutated copies all fail: a removed row (tbeldw_2), empty effects (tbeldw_0), an effect name that
is not a piece (tbelblak), and an effect piece removed from the layer (tbeldw_2_2).

Phase-5 catalogs (`"phaseRevision": "5"`) also need `nearField`:
* `extensionAlbedo.sources` are game `.assets` textures with `pathId` + `sha256`;
* `paintedCrops` is false, and the painting's role is declared low-frequency;
* no upscale, outpaint or backdrop lineage is named;
* `seamBlend` is world-space;
* every near terrain piece is an environment piece, and the near pieces are at or above the buildings' median
  texels/px;
* every dressing bin is a built `Mesh_` environment piece with triangles.

Negative checks on mutated copies all fail: `paintedCrops` true, a source without sha256, a near piece at 1 texel/px,
a dressing name that is not a piece, a frame-space seam, and a missing `nearField`.

* candidate: `town-scene3d-contract: OK homm3_conflux layers=32 reachable=32 unused=1 depths=0 bundle=present flag=off (candidate) full3d=on env=7`
* staged (unchanged 2.5D): `OK homm3_conflux layers=23 ... depths=22 bundle=present flag=off`
* negative checks on mutated copies fail as intended: a layer sprite, a missing reachable layer, `backdrop` not hidden.

## Runtime change spec (implemented 2026-09-27; source/static + build target, runtime unproven)

Implementation notes:
- The environment instance is `OfflineUnlockTownScene3DEnvironment` under the scene3d root. Its colliders are
  disabled, and any root child outside `Mesh_`/`Sky_`/`Fx_` throws.
- The sky uses a copy of the town's proven `Sprites/Default` material at renderQueue 1000. The sky texture is RGB, so
  it draws opaque. The shader writes no depth, so every mesh covers it.
- The far clip is raised to 120 only when it is lower, and restored on clear.
- The plate and backdrop roots still exist, because reposition and clear key off them, but their renderers are
  disabled and the backdrop texture is not loaded.

1. Catalog: parse `fullScene3d` (bool), `backdrop` (`"hidden"`), `environment.prefabKey`; accept an empty
   `layerDepths` when `fullScene3d`.
2. When `fullScene3d`: instantiate `environment.prefabKey` once under the scene3d root (same seating as layer prefabs)
   and keep it in `scene3dKeep`. Root children `Mesh_*`: rebind every renderer to the Hex/Lit donor material with its
   own `mainTexture` (as layer Bodies), **no collider, no Body role**. `Sky_*`: an unlit **opaque** material with its
   texture (not the sprite alpha material), drawn first (e.g. renderQueue 1000 or Background). `Fx_*`: the existing
   sprite material path.
3. Hide the backdrop quad (distance 80) and the black plate quad (80.5); skip `decoration` rows.
4. A reachable layer without a catalog prefab must throw (no 2D HotA-art fallback in full-3D mode).
5. `ValidatePayloadOrFail`: also load the environment prefab by key.
6. Building prefabs keep today's EnsureLayer semantics (Mesh_ = Body/collider/Hex-Lit, other renderers = sprite
   material, `Anim_PortalDisc` animator loop). Animated `Fx_` holders carry their own Animator (y spin).
7. Camera far clip must be >= ~110 prefab units (the sky dome sits at ~97).
8. Optional: shadows stay off (the bakes assume none).

## Building picking (2026-10-01; source/static + build target + generated artifact, runtime unproven)

Owner: `Homm3TownScene3dPick.cs`, called from `Homm3FactoryCityWorldVisuals` (`ApplyScene3dPickOrThrow`,
`RepositionScene3dLayerOrThrow`, after `EnsureEnvironment`). Measured by
`tools/homm3_town_scene_meshes/town_full3d_pick.py`. Gated by `tools/validate_town_scene3d_pick_contract.py`, which
runs in the FULL tier and takes about 3 minutes.

Native dispatch is unchanged: the PhysicsRaycaster on the city MainCamera takes the nearest collider, and the event
bubbles up to `BhBuilding.OnPointerEnter/Exit/Click`. Only which building is hit changed.

- **Before.** Each building had one native BoxCollider, refit to an AABB of its body's AABB in the collider's
  rotated space.
  - The thin relief meshes get boxes that cover gaps and terrain, and a near box wins the ray over a farther
    building that is drawn in front.
  - Walls and Resource_Depot_2 ship no collider.
- **Now.**
  - The native boxes are disabled (and restored on clear).
  - Every drawn `Mesh_` body renderer gets a MeshCollider of its own mesh under the BhBuilding.
  - Every non-interactive variant and every environment `Mesh_` renderer (terrain, water, rocks, props) gets an
    *occluder* MeshCollider on layer 31.
  - Layer 31 is outside the level67 MainCamera cullingMask `0x9f17`, so the PhysicsRaycaster never targets it. The
    raycaster's `finalEventMask` is checked at build, and the build throws if it sees layer 31.
  - A postfix on `PhysicsRaycaster.Raycast` drops that raycaster's hits that lie beyond the nearest occluder on its
    own ray (`ComputeRayAndDistance`).
- **Why not plain environment colliders.** `BhCityCamera` and `CursorCameraMode.IsOverUI` (Demo mono decomp of
  `Hex.dll`) are `EventSystem.IsPointerOverGameObject && !CursorRayCast.isOverCityBuilding`. A raycast-visible
  collider with no handler would therefore freeze the cursor camera wherever the pointer is over it.

Pixel agreement of hit vs visible building id: 640x360, HUD excluded, the native pan's 56 poses, every town state.

| town | old box | mesh colliders only | shipped (occluded) |
| --- | --- | --- | --- |
| bulwark | 0.2115 | 0.9773 | 1.0000 |
| castle | 0.1453 | 0.9876 | 1.0000 |
| conflux | 0.1142 | 0.9096 | 1.0000 |
| cove | 0.0275 | 0.9859 | 1.0000 |
| dungeon | 0.1087 | 0.9659 | 1.0000 |
| factory | 0.1242 | 0.9807 | 1.0000 |
| fortress | 0.1159 | 0.9349 | 1.0000 |
| inferno | 0.2129 | 0.9790 | 1.0000 |
| necropolis | 0.1748 | 0.9972 | 1.0000 |
| rampart | 0.1910 | 0.9880 | 1.0000 |
| stronghold | 0.1934 | 0.9477 | 1.0000 |
| tower | 0.1460 | 0.9974 | 1.0000 |

- **Old box.** Many buildings have IoU 0 (for example Castle Main, Cove Bank, Tower Main).
- **Mesh colliders only.** The whole residual is building surface hidden by scenery (terrain first). The worst
  cases are Cove Bank (IoU 0.07), Inferno Tier_6 (0.09) and Fortress Bank (0.39).
- **Shipped model.** It equals the visible buffer by construction, because the drawn pieces and the collider pieces
  are the same set. The gate therefore fails on what would break that set:
  - a reachable layer without a prefab or without a `Mesh_` body;
  - a mesh that is not Read/Write, which a runtime MeshCollider cannot cook;
  - an environment without `Mesh_`;
  - source drift in the wiring.

Not proven: the in-game hover and click, the Harmony detour on the IL2CPP `PhysicsRaycaster.Raycast`, and the cost of
cooking the terrain MeshCollider on the first town open. Sprite and `Fx_` pieces on buildings (flags, effects) are
not pickable, as before.
