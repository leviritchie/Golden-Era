# HoMM3 Stronghold: experimental full-3D town scene (depth + hand tuning)

Status: **experimental, generated-artifact evidence only.** An offline Unity bundle and v2 catalog are built and pass
`tools/validate_town_scene3d_contract.py --catalog`, including pan coverage. They are **not installed**, and nothing here
is startup, runtime or user-visible proof. The review images are Unity editor renders.

- No Meshy, and zero credits or paid generation of any kind.
- The only art sources are the original HoMM3 Stronghold background (`Stronghold-in-background.png`, 800x374) and the
  HoMM3 building sprites and DEF frames under
  `OfflineUnlockMod/homm3_runtime_assets/town_scene_refs/homm3_stronghold/`.
- The old runtime 2D backdrop and its outpaint (`mockups/homm3_stronghold_background_*`) are never read.
- Vanilla Olden Era assets are used only for filler: desert textures, rocks, the thorn bush, VFX noise and glow, and
  WaterNormal.

## Code and outputs

All code is in `tools/homm3_town_scene_meshes/stronghold_full3d_*.py`. These are new files; the Conflux phase-6 files,
the runtime C# and the shared `homm3_def_retarget` tools were not edited.

| Module | Role |
|---|---|
| `_common` | Sources, frame convention (1920x1080 cityHuman2 rest pose; HoMM3 screen at x1.8 top-left = 1440x673) |
| `_depth` | Local monocular depth: Depth Anything V2 Base and Large, Apple Depth Pro, on the painting and on per-sprite context crops |
| `_terrain` | Measured floor plane, depth calibration, world field (canyon continued past the painted edges) |
| `_ground` | Frame terrain mesh and albedo (the painting de-lit inside the rect, vanilla desert synthesis outside) |
| `_buildings` | One closed relief mesh per reachable building level (29 prefabs) |
| `_periphery` | Outer world for the vanilla pan and sweep, vanilla desert scatter, `pan_coverage.npz` |
| `_nearfield` | Vanilla scrub, rocks and pebbles in the frame extension at the painting's measured density |
| `_fx` | Effects for the animated DEFs: fountains, windmill, lightning |
| `_vanilla` | Read-only extract of the vanilla assets (`provenance.json` with sha256) |
| `_preview` | moderngl preview (iteration only) |
| `_scene` | stage / catalog / bundle / render / review / validate CLI; Unity runs only through `unitylock` after memgate and launch_guard |

Scratch and outputs live under `artifacts/homm3_stronghold_full3d/` (`STRONGHOLD_FULL3D_ROOT`):

- `bundle/`: the bundle `homm3_town_scene3d_stronghold`, `catalog.json`, `pan_coverage.npz` and the build report;
- `renders/`: editor renders;
- `review/`: review sheets plus `manifest.json` with sha256;
- `work/stage_report.json`: every measured number quoted below.

Rebuild:

```
python tools/homm3_town_scene_meshes/stronghold_full3d_depth.py      # once; re-downloads weights to artifacts/.../hf_cache (V:, pruned after use)
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py stage
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py bundle
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py validate
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py render
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py review
```

## Method

### 1. Registration: the camera is the vanilla one

The default frame is the vanilla cityHuman2 MainCamera rest pose (FOV 47.6), the same frame the Conflux lane uses.
The HoMM3 screen is registered at x1.8 in the top-left of that frame. Every mesh vertex inside the rect is placed on
the ray through its own painted pixel, so the default frame reproduces the painting by construction.

- **Horizon (measured):** HoMM3 y 91, where the far desert meets the sky through the canyon mouth. The floor plane
  vanishes there.
- **Pivot (measured):** the vanilla CityCamera pivot projects to frame (941, 507), on painted floor. The floor plane
  passes through it.
- **Result (measured):** the painted floor rises 8.56 deg away from the camera in the OE world. Registration forces
  this: HoMM3 looked down about 17 deg, the OE camera about 8.5. The camera sits 29.8 painting metres above the floor.
- **Scale (measured cue plus one hand-set value):** a background log hut has a 16 px wall, which is 0.62 camera units
  at its depth. Its eave is hand-set at 2.2 m (`HUT_EAVE_M`), which gives `DEPTH_SCALE` = 0.282 camera units per
  painting metre.

### 2. Terrain depth

Depth Anything V2 Large disparity of the painting is mapped to inverse camera depth by a robust (Tukey IRLS)
degree-2 polynomial fitted to the measured floor plane over a hand-traced floor polygon.

- Fit: 93.1% inliers, relative residual 0.0114, monotone.
- Cross-checks (median |log ratio|, reported and never blended): DA V2 Base 0.009 (p90 0.043), Depth Pro 0.030
  (p90 0.109). All three agree on shape. Depth Pro's metric scale is not used.
- Outside the rect (the frame extension, x >= 1440 or y >= 673), each pixel is ray-marched against a world field:
  - the floor plane;
  - the canyon walls continued from the painted edge profiles (wall shift `WALL_SHIFT_M`, ridge noise and foreground
    hummocks, all hand-tuned);
  - a far cap at 400 m.
- The two seams are blended along each pixel's own ray (`SEAM_PX` 70), so registration is unchanged.

### 3. Buildings (29 prefabs, one per reachable level, swapped by native BhBuilding)

For each level:

- **Mask:** sprite alpha, minus HoMM3 shadow/magenta leftovers, minus pixels identical to the background under them.
- **Depth:** DA V2 Large on a context crop (the sprite composited over the background). It is calibrated **per crop**
  by an affine fit to the calibrated terrain inverse depth on the crop's own background pixels, so each building is
  measured against the ground it stands on. Relative residual is 0.012-0.063 (median about 0.02); the lyceum is the
  worst at 0.063.
- **Footing:** the lowest mask pixels of each column are pulled onto the terrain. Footing error is 0.006-0.20 m for
  the town buildings. The walls are 0.28-0.51 m: their base runs along a slope that the terrain relief rounds off.
- **Mesh:** a screen-space grid, with the silhouette snapped to the mask edge. It is **closed by hand**: each
  silhouette edge is extruded away from the camera to a flat back.
- **Texture:** the sprite de-lit by the Hex/Lit irradiance of its normals. Sides and back use the same art, darkened
  and blurred.
- **Hand-tuned per layer (`TUNE`):** relief and thickness.
  - The cliff dwellings (Lvl5-7) are "crags": relief 12-30 m, thickness 20-30 m.
  - The lyceum, resource depot and mage guild are clamped to 1.5-4 m relief. Depth Anything reads their thin spires
    and awnings as deep.
  - Other buildings use relief and thickness derived from their measured width.

**Successor closure (candidate only):** `--building-method solid` replaces this extrusion. It adds a ground/upright
split, width-driven solid thickness, straightened thin members and an arc-length back texture. On the three sweep
extremes it cuts revealed from 212,624 to 55,611 px and streak from 471,776 to 35,971 px, summed over the 29 buildings.
It is built into `artifacts/homm3_stronghold_full3d/candidates/solid_v1/` and is not installed. The method, per-building
verdicts and limits are in `docs/homm3_town_depth_building_solids.md`.

**Building contact depth (contact_v1, candidate only, all HoMM3 full-3D towns):** the per-column footing and
terrain clamp above let tall sprites run hundreds of metres back along their pixel rays in the sweep poses. Examples
are the Cove waterfall and stilt houses, Fortress `tbfrdw_3` (span/width 117) and the Meshy `BodyRest` residues.
contact_v1 replaces it, opt-in per candidate:

- an upright/ground split;
- one robust contact per layer;
- depth affine in disparity about that contact, with a thickness prior;
- Meshy bodies sharing the contact;
- a rest-occlusion pass in HoMM3 draw order.

The rest pose stays pixel-exact. The `buildingDepth` gate in `tools/validate_town_scene3d_contract.py` refuses a
streak (span/width > 3 and span > 20 m) or a clamp-eaten sprite (window share > 0.8).

Status: built as `*_dfix` candidates for rampart, castle, tower and Cove, and **not installed**. Proof tiers are
generated artifact plus Unity-editor renders where noted. The rule, numbers, negatives and the unbuilt anchored
background behind Cove's waterfall cliff are in `docs/homm3_town_building_contact_depth.md`.

### 4. Ground look (calibrated, then hand-set)

- **Inside the rect:** the painting de-lit at full sharpness. At the rest pose, the lit result reproduces the painting.
- **Outside the rect:** vanilla desert textures sampled in world space. The painting supplies only low-frequency colour:
  the floor colour, and a canyon strata palette taken as the median colour per world height.
- **Detail contrast:** `DETAIL_CONTRAST` 2.0, `ROCK_CONTRAST` 5.0, `SHADE_GAIN` (3.0, 0.8) and `CAV_K` 0.20 were
  calibrated against the painting's measured band contrast in `calib_contrast.py` (a one-off, since deleted).
  - The floor matches.
  - The extension walls still read flatter than the painted walls: macro contrast 0.66 against 1.10. More gain turned
    the vanilla rock texture into noise, so the gap was left open.

### 5. Periphery for pan and sweep (vanilla idiom, no invented water)

The pan poses come from the vanilla cityHuman2 `BhCityCameraController` and `SoCityCameraSettings` (the Conflux lane's
`vanilla_city_camera_pan.json`).

- **Mesh:** a polar grid spanning ±70 deg and 6-398 m. Inside the default frame, vertices move back along their own
  rest ray, so the frame is unchanged: 1070 moved, 39 lowered to the skyline, 0 intrusions.
- **Scatter:** vanilla desert boulders (Rock_desert_new_01..03 and Des_Rock_01..04 with their own textures, 56 sites)
  and a re-tinted Dead_thorns_01 scrub, placed only where the whole instance projects outside the default frame.
- **Water:** none. The painting is a dry canyon, so a continued water body would be invented.
- **Sky:** a 4096x2048 dome at 415 m (117 units, inside the runtime's raised far clip of 120).
- **Coverage:** the validator reports `panRays=990000 panVoid=0 panNeg16x9=0.021`.

### 6. Near field

Olive scrub blobs were counted in the painting's nearest floor rows (560-673): 6 blobs over 2133 m² of floor, which
is 0.0028 per m².

The extension below and right of the rect is dressed at that density: 7 scrub, 3 rocks and 8 pebbles. Every instance
box projects wholly outside the HoMM3 rect, so the painting stays untouched. The rock and pebble multiples are
hand-set, because the painting's stones are too small to count at 800x374.

### 7. Effects (the animated DEFs, measured, drawn in the vanilla style)

The DEF frames are read **only to measure**: frame 0 is the whole sprite, and the alpha boxes of frames 1 onward are
the moving rects. Nothing is played as a ripped flipbook.

- **Fountains** (`extraCapitol_1..3`, two each):
  - **Basin water:** the convex hull of the blue patch pixels, on the basin's own relief pulled 0.3 m toward the
    camera. It uses the bundle's FlowWater with vanilla WaterNormal and TileNoise.
  - **Jet:** its apex is the highest white pixel of any frame, measured on the vertical through the basin centre:
    5.5-6.1 m, so v0 = sqrt(2gh) ≈ 10.3-10.9 m/s.
  - **Particles:** the plume, falling bell, splash ring and mist are VfxUber-replica particles under real gravity.
- **Windmill** (`dwellingUp2Lvl6_2`):
  - **Measured:** hub (151.9, 23.3) px, radius 28.4 px, and a frame-to-frame rotation fit of 8.5 deg median per
    100 ms. That is counter-clockwise on screen, with a period of 4.2 s.
  - **Sails:** cut out against the per-pixel median of all frames. The median is the sail-free background, and it also
    replaces the sails in the static building texture.
  - **Drawing:** an unlit, camera-facing Fx_ disc spun about its axis.
- **Lightning** (DEF keyed `dwellingUp2Lvl7_2`, re-keyed 2026-09-28): a camera-facing VfxUber particle masked by the union of the DEF's
  bolt pixels, crackling through fast-scrolling vanilla noise, with a glow flicker and sparks.

All vanilla textures used are recorded with sha256 in `catalog.effectsReport` and `stage_report.fx.vanillaTextures`.

### 8. Framing (zoom, aim, pan extent; per-faction `FRAMING`)

The native rest view shows the painting in only about two thirds of the region the HUD leaves visible. The profile's
`FRAMING` (`town_full3d_framing.py`, catalog `referenceCamera.framing`, schema `town_full3d_framing.v1`) closes that gap
with the native camera rather than a post-scale:

- **Zoom:** `MainCamera.fieldOfView = 2 atan(tan(native/2) / zoom)`. The root keeps its native-FOV scale.
- **Aim:** the root turns by `aimRotation` about the rest camera, centring the buildings' union.
- **Pan extent:** the controller's `SoCityCameraSettings` is swapped for a clone. In the clone, the sweep nodes (about
  the rest camera) and the cursor angles are scaled by `panScale`.
- **Restore:** all of it is undone on clear, or when entering a fraction without framing.

Measurement is the share of the visible (non-HUD) viewport that shows the painting. Here, "painting" means a pixel
that projects into the painted rect and is not disoccluded. The HUD is measured from a 2560x1440 capture: right 0.90,
bottom 0.764, top 0.03.

Stronghold, `tex_sdgrade_v31` stage:

| | default | cursor L | cursor R | sweep L | sweep R | sweep high | buildings out at rest |
|---|---|---|---|---|---|---|---|
| before (native) | 0.672 | 0.676 | 0.667 | 0.605 | 0.710 | 0.646 | 4 |
| zoom 1.17, aim, pan 0.5 | 0.900 | 0.868 | 0.876 | 0.801 | 0.873 | 0.839 | 0 |
| same, native pan extent | 0.900 | 0.811 | 0.826 | 0.752 | 0.810 | 0.789 | 0 |

- **Why 1.17:** it is the largest zoom at which every building's bounds stay inside the visible region at rest. At
  1.18, the Lvl7 dwellings leave over the top and the market goes under the hero panel.
- **Last row:** the case where the native controller keeps a sweep spline cached from the original nodes.
- **Proof tier:** source/static and generated-artifact only. The plugin is compiled on the Golden Era path and passes
  the live-interop check. Runtime is unproven: nothing yet shows that the controller rebuilds its sweep from swapped
  settings, and nothing shows that no native code rewrites the camera FOV.

## What worked

- **Registration by construction:** every in-rect vertex sits on its own pixel's ray, and buildings and effects keep
  it too. The default frame is the HoMM3 image, and the cropped extension adds nothing on top of the painting.
- **The three depth models agree** on the canyon's shape (DA Base against Large 0.9%, Depth Pro 3%), so the terrain
  is not one model's hallucination.
- **Per-crop calibration** puts each building on its own ground, with footing errors in the tens of centimetres.
- **Effects from measurement:** the fountain height, windmill speed and sense, and bolt shape come from the DEF itself.
- **Periphery:** the pan and sweep see continuous canyon and desert with no voids.

## Where depth alone fell short (hand tuning or rejection was needed)

1. **Thin structures** (spires, banner poles, awnings, the lyceum and mage guild towers) read as far too deep.
   Relief is clamped by hand.
2. **Cliff dwellings** are the canyon wall itself. Depth gives a plausible front but no volume. Thickness is hand-set,
   and the backs are flat.
3. **The HoMM3 projection is not the OE projection.** HoMM3 was drawn looking down about 17 deg, the OE camera about
   8.5. A level water plane through the painted basin ellipse stretched to 20-36 m deep, so it was rejected; the water
   lies on the basin relief instead. The same mismatch makes horizontal features (splash rings) read flatter than
   painted.
4. **Scale has one hand-set anchor** (a 2.2 m hut eave). Everything metric (gravity, particle sizes, periphery
   distances) inherits that guess.
5. **Painted walls outside the rect cannot be measured.** Their continuation (shift, ridge noise, hummocks) is hand
   tuning. Their texture is vanilla rock, flatter than the painting (see section 4). Seams at x=1440 and y=673 remain
   visible as a change of texture character, though not of geometry.
6. **Low scrub density:** only 6 blobs were countable, so the near field is sparse by measurement, not by choice.

## Known defects and notes for the coordinator

- **Mis-keyed DEF (fixed 2026-09-28, user-approved).** `layers/anims/metadata.json` keyed the blue-lightning DEF as
  `dwellingUp2Lvl7_1`, but its frame 0 is pixel-identical to the **`dwellingUp2Lvl7_2`** sprite (0 px differ; 13782 px
  differ from `_1`, whose cleft is red). The base dwelling showed a blue bolt and the upgraded one none.
  - Both refs copies (`homm3_runtime_assets`, `reference_pack`) now key it `dwellingUp2Lvl7_2`, and the frame folder
    moved to match; `stronghold_full3d_fx.py` and the profile's anim state follow. Candidate `solid_v3_1` is solid_v3
    plus only this re-key. The 2D anim player looks up by layer id, so it follows the same metadata.
  - Still open: `artifactMarket_1` / `lyceum_1` DEF ids do not match catalog layer ids (their banners stay static).
- **Runtime needs** (not edited here: `Homm3TownScene3d.cs` / `Homm3FactoryCityWorldVisuals.cs`):
  - Fx_ pieces keep their own bundle shaders (FlowWater, VfxUber).
  - The windmill disc is unlit and spins through `spinPeriod` on the child `_mesh` about its local Y, the same as the
    Conflux fx bins.
  - Particle systems carry their own gravity (scaled into the prefab).
- **Banners** on the artifact market and lyceum are static: their DEF ids do not match the layers, so no audit row is
  required, but they do not move.
- **Bundle asset names must be unique across prefabs.** The Unity builder writes each bin to
  `generated/<bin name>.asset|.mat`, and each particle material to `generated/<group>_<system>.mat`.
  - The first bundle named every building bin `Mesh_Body`. All 29 prefabs silently shared the last writer's mesh
    (wall_3), and the validator could not see it.
  - Names are now suffixed with the layer id (`Mesh_Body_<layer>`, `Fx_Basin_<k>_<layer>`, and so on).
    `write_catalog` fails closed on any repeated bin or group name.
    `write_catalog(sc, carry=...)` must declare how it meets the candidate's previous catalog
    (`town_full3d_fork.catalog_carry`): `previous` carries every block it does not produce (props, houses) and
    fails without a previous catalog; `fresh` refuses if it would drop such a block. An opt-in block it owns
    (`buildingDepth`, `skyLook`, `clothLook`, `terrainStreak`) is never carried stale: one the previous catalog
    had and the write no longer produces refuses unless the caller lists it in `drop`. The scene CLI's `stage` /
    `catalog` take `--carry` (default `fresh`). Test: `test_town_full3d_fork.py` (every call site passes carry).
  - The Conflux builder and the shared validator were not changed, so another lane that reuses a bin name across
    prefabs would hit the same silent sharing.
- **The windmill spin is not visible in the editor renders.** It is an Animator clip, and `RenderStates` only advances
  `_TimeOffset` and particle simulation. The disc's rotation is therefore static-verified only (clip and period in the
  spec).
- **Proof tier:** generated artifact. The bundle is built and validated. It is not installed, there is no startup
  smoke test, and it has not been seen in game.

## Assessment

**Review set:** `artifacts/homm3_stronghold_full3d/review/`, which includes `manifest.json` with the sha256 of every
sheet and raw render. Bundle sha256: `eb7df19d905b2af8cccc24fb0acefd9c051d2f0ba8a36a15ebbd6a5ca0008452`
(105,308,939 bytes).

**How far depth and hand tuning got:**
- **Default frame:** a faithful match to the HoMM3 screen inside the registered rect (`01_homm3_vs_3d_*.png`). This is
  by construction.
- **Small moves** (cursor pan and most of the vanilla sweep, `04`/`05`): these work. The town reads as layered 3D:
  buildings separate from the canyon, the fountains sit in their basins, and the canyon continues past the painted
  edges.
- **Larger moves** (the ±18 deg review orbits, `06`): the method's limit is plain. Every building is a relief shell. Its
  sides are the silhouette extruded with a smeared texture. Tall thin pieces (the banner pole, the market's spire
  ring, the mage-guild tower) turn into sheets. Canyon ridges stretch into streaks where the painting has depth
  discontinuities that a single-view mesh cannot fill.

**The frame extension** (right column and bottom band) is the weakest region:
- vanilla desert textures tiled at the calibrated contrast read as a repeating pattern;
- the right-hand canyon wall is flatter and blurrier than the painted walls;
- the seam at x=1440 is visible as a change of texture character.
The vanilla town fills its extension with modelled hills and props. This scene has only a sparse scatter (by
measurement).

**Effects:**
- The fountains move, and their jet height and water extent are measured. The water shades too pale, and the right
  basin's relief bulges into a dome, because it inherits the basin sprite's depth.
- The lightning crackles, but it is keyed to the wrong level (see the mis-keyed DEF above).
- The windmill is cut and spun correctly by measurement. Its disc carries some background around the sails.

**What would still need Meshy or manual modelling** to hold up under the full vanilla orbit, rather than the cursor pan
alone:
- the Town Hall/Capitol and the walls (large, near and blocky: manual box modelling from the sprite would be quick and
  better than relief);
- the cliff dwellings (Lvl5-7), which need real back volumes;
- the thin structures (banner pole, market spire ring, lyceum and mage-guild towers), which need proper
  cylinders/cards;
- the huts and the log palisade, whose repeated forms are ideal for one modelled hut instanced;
- a painted or modelled extension for the right canyon wall, instead of tiled vanilla rock.

Depth plus hand tuning is enough for the rest pose and small parallax. It is not enough for free orbit.
