# HoMM3 Stronghold: Meshy T2 town buildings (candidate t2_v1)

**Proof tier: installed payload.** Bundle built through unitylock, editor-rendered, validated, installed on
2026-09-30 by `install_town_scene3d.py` and read back. There is no startup, runtime or user-visible proof yet.

- Brief: `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md`.
- Budget: `townCaps.homm3_stronghold` = 396 credits.
- The "before" is the installed full-3D lane candidate **wall_v40**, the solid_v3 + sdgrade relief described in
  `docs/homm3_stronghold_full_3d_town.md`. Its bundle sha `cbb9d7e4...` matches the installed bundle.

## Verdict

**Installed.** This replaces the first-pass verdict ("do not install", which judged by rest dE). The rule of
2026-09-29, set by the user: Meshy geometry is the default for every layer, rest dE76 is a diagnostic only, and a
layer goes back to the relief only when its mesh is genuinely broken, judged by eye at the sweeps.

The redo added the painted front, surgery and a residual grazing filter (Method below). Against the first pass:

- **At rest** the frame reads as the painting. The front faces take the sprite by screen position, so the Meshy
  misregistration no longer smears the painting: mean rest dE fell from 10.6-21.7 to 6.1-12.3 (table below).
- **At the sweeps** the buildings turn as solid bodies. The first pass's defects are gone: the Town Hall fountains'
  white spiky domes (the jets are now the seed residual and the fountain Fx), the pale plaza slab, the market awning's
  dark wedge, the Lyceum monument's lost plinth (it now sits on it), and the black speckles on the fort and houses.
- **No layer was reverted**; none is broken. Known residuals: the Behemoth crag (`dwellingUp2Lvl7_*`) shows a few
  pale-blue slivers along its peaks at the sweeps, and the Lvl6 cave mouth reads a little lighter than the painting
  (de-lit front). Neither hides the main feature.

## Spend (shared ledger `artifacts/meshy_town_scene_meshes/_ledger.jsonl`, faction `homm3_stronghold`)

- Each call is image-to-3d with ai_model `meshy-t2`, smart-topology, should_texture, and no texture prompt or image.
- target_polycount is 15000, the meshy-t2 maximum. The API refuses 30000 with HTTP 400; that refused create was not
  charged and has no ledger line.
- Each call costs 15 cr. There were no claims, no retries and no props.

| layer | taskId | cr |
|---|---|---|
| wall_1 | `01a0ef7e-5fdf-7785-bebf-b5f9cba0a67b` | 15 |
| magicGuild_1 | `01a0ef7e-5fdf-70ce-9c06-a88182dbb8a4` | 15 |
| extraCapitol_3 | `01a0ef7e-5fe3-763c-88df-9813598687ae` | 15 |
| extraCapitol_1 | `01a0ef7e-5fe1-72ed-b190-919daab8556c` | 15 |
| extraCapitol_2 | `01a0ef7e-5fde-708d-8675-43fa997fd989` | 15 |
| wall_2 | `01a0ef7e-5fe1-72ee-b87f-7815bda0a562` | 15 |
| wall_3 | `01a0ef7e-5fdd-7013-95a8-2824e3a6486d` | 15 |
| magicGuild_2 | `01a0ef7e-602a-7120-af5f-26fc49d676c4` | 15 |
| magicGuild_3 | `01a0ef7f-f612-75ac-bbf2-206663932c56` | 15 |
| dwellingUp2Lvl1_1 | `01a0ef80-4671-72f7-85ba-df9db633e454` | 15 |
| dwellingUp2Lvl1_2 | `01a0ef80-462e-7579-9fd3-ba0355d96323` | 15 |
| dwellingUp2Lvl2_1 | `01a0ef80-46b1-7038-b3db-573bc6ed5b41` | 15 |
| dwellingUp2Lvl2_2 | `01a0ef80-6f2f-769c-a447-6e1bd1b876ef` | 15 |
| dwellingUp2Lvl3_2 | `01a0ef80-70f5-71dc-a7a7-db588d137a18` | 15 |
| dwellingUp2Lvl3_1 | `01a0ef80-70bb-7097-982a-592e105837bc` | 15 |
| dwellingUp2Lvl4_1 | `01a0ef80-7824-7076-aed9-8d11e054a3cd` | 15 |
| dwellingUp2Lvl4_2 | `01a0ef83-444f-73ab-9284-dbede747cd36` | 15 |
| tavern | `01a0ef83-6cd9-74f4-be0f-40ea69b276d5` | 15 |
| market | `01a0ef83-6f3a-71e1-b5de-efa204b4b337` | 15 |
| bank | `01a0ef83-6ee6-7512-a64c-85548cf0f946` | 15 |
| resourceDepot | `01a0ef83-9549-71bf-9d4e-4bd8c4013d80` | 15 |
| lyceum | `01a0ef83-9732-777c-a4c9-c051973907b5` | 15 |
| dwellingUp2Lvl6_1 | `01a0ef83-99d1-7643-9041-87395411d15f` | 15 |
| dwellingUp2Lvl6_2 | `01a0ef83-c68b-73d5-ac7a-383c3189b7a6` | 15 |
| dwellingUp2Lvl7_1 | `01a0ef85-a369-7239-b228-d07766bd81c1` | 15 |
| **total** | 25 calls | **375 of 396** |

21 cr are left unspent. See "Skipped" for why they were not used.

## Layers

**Meshed (25 Meshy meshes, 26 layers):**

- extraCapitol_1, extraCapitol_2 and extraCapitol_3 (Town Hall to Capitol);
- wall_1, wall_2 and wall_3 (fort);
- magicGuild_1, magicGuild_2 and magicGuild_3;
- tavern, bank, market, resourceDepot and lyceum;
- dwellingUp2Lvl1_1 and 1_2, 2_1 and 2_2, 3_1 and 3_2, 4_1 and 4_2, 6_1 and 6_2, and 7_1;
- dwellingUp2Lvl7_2 reuses 7_1's mesh. Its sprite is the same except for the bolt colour, and the painting texels come
  from 7_2's own sprite.

**Skipped:**

- `artifactMarket`: an 86x42 px ground decal with a small post, which is overlay scale.
- `dwellingUp2Lvl5_1` and `dwellingUp2Lvl5_2` (thunderbird crag): not meshed. The first pass did not beat the relief
  at rest on any layer (see the verdict), so spending the remaining 21 cr on a 26th mesh would not change the outcome.
  These layers keep the seed relief.
- Every layer not listed above keeps the seed's staged bins byte for byte: terrain, sky, periphery, near field and
  effects.

## Method (`tools/homm3_town_scene_meshes/stronghold_full3d_meshy.py`)

- **Inputs** (`artifacts/meshy_town_scene_meshes/homm3_stronghold/_work/prep_inputs.py`): the static plate's native
  mask on white, with the long side at 0.9 x 1024 (LANCZOS). Calls go through `stronghold_t2_meshy.py`, which does the
  following:
  - sums the faction's ledger lines before every call and refuses a call that would pass cap + claims;
  - appends the ledger line immediately after create;
  - runs at most 4 tasks at once.
- **Fit** (`fit`, cached per GLB in `fit.json` under the GLB's sha256 and spec key): `fit_mesh_to_sprite.Fitter` under
  the rest camera.
  - It searches yaw within ±45° of camera-facing, scale, the ground-contact pixel on the calibrated terrain depth, and
    an optional vertical stretch.
  - Scoring is F-beta 0.5 against the native mask.
  - A layer cut by the painting's right edge (`openRight`: Lvl6) is not scored past x = TW.
  - The GLB takes the glTFast x negation into the left-handed painting world.
- **Texture** (`bake`): the Meshy atlas is re-baked texel by texel.
  - A texel whose surface point is visible at rest, at its own depth pixel, and lies inside the sprite mask takes the
    sprite's texel. That texel is de-lit by the Hex/Lit irradiance of the texel normal, with no recolour.
  - Hidden texels keep the Meshy texture with a per-channel median gain, clamped to [0.5, 2].
  - The painting weight falls off at grazing view.
  - Normals are bent toward the light where the de-lit value would clip (ALBEDO_MAX 0.97).
  - The atlas is baked at 2048 and shipped area-averaged at 1024 (`ATLAS_OUT`). The lane contract requires the
    buildings to be no denser than the near terrain (4 texels/px).
- **Edges** (`clip_edges`):
  - The Town Hall touches the sprite's x = 0 edge, so triangles left of the frame are dropped (`clipLeft`).
  - The Lvl6 layers take the profile's `edge_fray` at the right edge.
  - Both satisfy the framing gate (all buildings inside the visible region at rest).
- **Double-sided** (`double_side`): every triangle gets a reversed copy. Meshy meshes are open shells, and the game's
  Cull Back dropped sheets seen from behind: 3740 px at rest and up to 6440 px at the orbits, against a baseline of 0
  to 4433.
- **Surgery** (`t2_mesh_surgery.py`, shared with Cove): per-layer rules from
  `town_full3d_factions/stronghold.py` drop Meshy parts that are not the building: `groundPlate` (the Town Hall's
  plaza slab), `fountainJets` (the spiky white domes Meshy made of the fountain jets), `loneSheets` (one- or
  two-triangle slivers, including the market awning plane).
- **Painted front** (`town_full3d_t2_paint.py` since 2026-09-30, when it absorbed `t2_painted_front.py`; a restage of the sample layer tavern is byte-identical (`tools/homm3_town_scene_meshes/t2_bake_restage_check.py`); the coordinator's rule of 2026-09-29): faces visible at rest inside the
  sprite take the sprite by screen position, de-lit, and ship with the camera-facing normal; hidden faces keep the
  Meshy texture with a median gain. This replaced the texel re-bake above as the texture of record for visible faces
  and removed the hidden-face black speckles.
- **Residual** (`residual`): the pattern comes from `cove_t2_stage.py`. The seed relief's triangles are kept where the
  Meshy rest silhouette, grown by 3 px, leaves sprite pixels uncovered (at least 150 px): fountain basins, plaza steps
  and poles. Grazing relief faces (|cos| of the normal against the rest ray below 0.35, `PF.facing_rest`) are
  dropped; they were the streaks at the sweeps. Each residual is a separate `Mesh_Body_<lid>_rest` piece and is also
  double-sided.
- The Lyceum's sink is 0 so the monument stands on its plinth.
- A catalog `meshyBuildings` block records the layers and the ledger credits. The lane's nearField and periphery
  `meshyCredits` stay 0, because those parts used no Meshy.

### Bugs found and fixed during the pass (they are recorded because the numbers changed)

- trimesh stores glTF UVs flipped to bottom-origin, and the bake assumed glTF's top-origin. The painting bake stayed
  self-consistent, but the hidden faces read the Meshy texture from the mirrored row, which scrambled it.
- The rest visibility test first used a 3x3 minimum of the depth buffer. That failed about 60% of the texels of drawn
  triangles on relief detail. On resourceDepot the median depth ratio was 1.037, against 1.0003 at the texel's own
  pixel, so those texels kept the Meshy texture where the painting belonged.
- After both fixes the rest dE against the painting fell, for example resourceDepot 29.3 -> 20.4 and tavern
  14.6 -> 11.4.

## Gates (candidate `artifacts/homm3_stronghold_full3d/candidates/t2_v1`)

- **Framing gate** (`S.write_catalog`): pass, after `clipLeft` on the Town Hall and `edge_fray` on Lvl6.
- **See-through gate** (`town_full3d_cull`, no worse than baseline fringe_v37 at every pose): pass. The total is
  3880 px, the same as the seed's own pieces; the Meshy bodies contribute 0 because they are double-sided.
- **Texel-density contract**: buildings median 2.8 texels/px against near terrain 4.0. The 2048 atlases first gave
  5.601 and failed the validator; the fix was the 1024 ship size, and the gate was not changed.
- **Bundle**: `artifacts/homm3_stronghold_full3d/candidates/t2_v1/bundle/homm3_town_scene3d_stronghold`, 348,597,018
  bytes (wall_v40 is 115,195,998), sha256 `c07d41ed6d9c908494befb14227d22b01235ee28c0aa23d58df05aee6c914e64`. It was
  built through `unitylock` (memgate and launch_guard OK) and editor-rendered, and the render returned rc 0.
- **Validator**: `stronghold_full3d_scene.py validate` returns `town-scene3d-contract: OK homm3_stronghold layers=29
  reachable=29 ... panVoid=0`.
- **Installed** 2026-09-30: bundle sha256 `c07d41ed...14e64`, catalog sha256
  `9f169be7f905ec06aae247efcb5eb91786699afc4dfac2561c0d9b35a59d6a29`, read back in the source tree and Golden Era.
  Rollback copy: `artifacts/town_scene_rollback/stronghold_20260930T063210Z`.

## Review

- Sheet: `artifacts/claude_takeover_20260927/review/homm3_stronghold_t2_buildings.png`.
  - The columns are painting | before wall_v40 | after t2_v1, at rest, sweep_left, sweep_right and sweep_high.
  - These are followed by per-building zooms, before over after, at the same four poses.
  - The images are Unity editor renders.
- The `.json` beside the sheet gives the rest dE76 against the painting over each Meshy layer's sprite mask, before and
  after.

Mean rest dE76 over the sprite mask, from the Unity editor render at `full3d_full.png` (diagnostic only):

| layer (full state) | before wall_v40 | first pass | after t2_v1 (painted front) |
|---|---|---|---|
| extraCapitol_3 | 5.36 | 20.49 | 8.17 |
| wall_3 | 3.87 | 12.82 | 6.93 |
| magicGuild_3 | 4.71 | 14.69 | 8.98 |
| tavern | 4.83 | 12.51 | 7.76 |
| market | 5.7 | 15.07 | 8.87 |
| resourceDepot | 8.46 | 21.69 | 11.29 |
| bank | 5.11 | 10.64 | 8.06 |
| lyceum | 3.86 | 16.51 | 12.15 |
| dwellingUp2Lvl1_2 | 4.52 | 16.77 | 9.59 |
| dwellingUp2Lvl2_2 | 4.69 | 15.92 | 9.28 |
| dwellingUp2Lvl3_2 | 4.33 | 13.59 | 7.71 |
| dwellingUp2Lvl4_2 | 3.97 | 15.55 | 6.11 |
| dwellingUp2Lvl6_2 | 5.97 | 15.0 | 12.26 |
| dwellingUp2Lvl7_2 | 4.59 | 14.79 | 9.51 |

## Props and animation pass (2026-09-30, candidate `pb_v1`, installed)

Candidate `pb_v1` is seeded from the installed `t2_v1` and adds Meshy props over the regions that
`town_t2_streak_map.py` flags as streaking at the reachable sweep poses. The camera range is unchanged.

- **Streak regions.** Before the pass, the streaks were on the ridge crests of the canyon terrain against the sky
  (the left massif, the gap behind the castle, the spiked right massif) and on the Lvl5 crag.
- **Props.** Three types were generated from crops of the HoMM3 painting: `spire`, `butte` and `cones`. The
  generator is `town_t2_props_gen.py` with `TOWN_T2_PROPS_GROUP=B`, and the specs are in
  `tools/homm3_town_scene_meshes/town_t2_props_specs_groupB.py`.
  - Placed: 17 `cones` (hoodoo clusters) and 1 `butte`. The placer chose no `spire` position.
  - Credits: 63 (3 x 6 for the concepts plus 3 x 15 for the meshes). They are logged in
    `artifacts/meshy_town_scene_meshes/_budget_props_20260930_groupB.json` (group B cap 900).
- **Measured streak (stretched px, `town_t2_streak_map.py`, full scene):**

  | pose | before (`t2_v1`) | after (`pb_v1`) |
  |---|---|---|
  | sweep_left | 15336 | 10979 |
  | sweep_right | 34558 | 20880 |
  | sweep_high | 34774 | 23101 |

  The cursor poses stay at 0. By eye, the rainbow crest smears are largely replaced by hoodoo clusters. One pale
  butte sits in the top-right extension. The remaining streak is crest terrain that no prop covers.
- **Animation.**
  - The HoMM3-animated Stronghold buildings already carry Fx in this scene: the capitol fountains, Lvl7
    lightning and the others.
  - Several Fx were buried inside Meshy bodies. `town_t2_fx_occlusion.py snap` moved them along the rest camera ray
    in front of the bodies, so the rest frame is unchanged. The layers moved were:
    - `extraCapitol_3` fountain spray and basin;
    - `dwellingUp2Lvl7_2` lightning;
    - the `extraCapitol_1` / `extraCapitol_2` fountains, in the `start` state.
  - After the snap, the audit reports no hidden Fx.
  - No adventure-map geometry was reused. The map-building sculpts are separate meshes, and Meshy is not used on
    map buildings.
- **Review sheet** (painting | before | after, at rest and sweeps):
  `artifacts/claude_takeover_20260927/review/homm3_stronghold_props_pb_v1.png`.
- **Install.** Installed on 2026-09-30 with `install_town_scene3d.py`:
  - bundle sha256 `6eff3fa3e4174e3062aeb9e1b021a2731231571916050eb76561b597b6fc8e96`;
  - catalog sha256 `5f3376b93a01e58cc878dcb8799be9c99b7cf6828e572d487db635212ad8ee8e`;
  - rollback in `artifacts/town_scene_rollback/stronghold_20260930T223331Z`;
  - the scene3d validator is OK (`props=18/2types cr=63 pass=342/900`).
- **Proof tier: installed payload.** Startup, runtime and user-visible proof are not yet done.

## Background depth A/B (2026-10-01, candidate `bgd_v1`, not installed)

`bgd_v1` is `pb_v1` with the img2img background depth as the only intended difference. Every `pb_v1` layer is carried
over and seated on the new ground.

- **Depth.** `artifacts/img2img_depth_maps/homm3_stronghold/background/Stronghold-in-background__depth_raw.png`
  (sha256 `5093c66decd9134e5c63cd59b21d1140e6389ea4ab4006894e9e79e325673088`) was registered by ECC affine (`town_full3d_bg_depth.py import`) to
  `depth/img2img_bg.npy` (sha256 `cf671e344e6c74b241860ac7c6afb92fe97ad89e619e62abbf4b1031d6c72090`). It is pinned in `work/background_depth.json` and recorded in
  `stage_report.json` `terrain.backgroundDepth`. Building depths are unchanged.
- **Environment.** `stage --parts terrain,sky,periphery,nearfield` with EXTSRC `town_all/stronghold/tex_v33/extsrc_bridge_blend`, plus HOUSES `town_all/stronghold/houses_v33`.
  - The same restage on the old depth (control `ctl_v1`, `artifacts/claude_takeover_20260927/town_all/bgdepth_groupB/env_compare.py`) reproduces `pb_v1`'s env bins.
    The nearfield scatter is the exception: it drifts with floor area independently of depth.
- **Buildings.**
  - The 26 Meshy T2 bodies were re-seated on the new ground by `stronghold_full3d_meshy.py stage`, using the same
    cached fits (yaw, scale, contact pixel and stretch).
  - The 3 relief layers (`artifactMarket`, `dwellingUp2Lvl5_1` and `_2`) were restaged with
    `--parts buildings --building-method solid_parts --back-fill`. The same call on the old-depth control is
    byte-identical to `pb_v1`.
  - **Not carried onto the new depth:** the Meshy residual pieces (`Mesh_Body_<layer>_rest`). They are taken from
    `wall_v40`'s relief, which was built on the old depth, so they draw the same rest pixels but stand at old-depth
    positions.
- **Props.** Each instance keeps its type, yaw and rest pixel. Its base slides along the rest ray onto the new ground
  and its height scales with the distance (`artifacts/claude_takeover_20260927/town_all/bgdepth_groupB/snap_props.py`). On the old-depth control the ratio is
  1.0000 ± 0.0005.
- **Fx.** Re-audited with `town_t2_fx_occlusion.py audit`.
- **Renders:** `artifacts/homm3_stronghold_full3d/candidates/bgd_v1/renders/` (standard set).
- **Sheet** (pb_v1 | bgd_v1 | diff): `artifacts/claude_takeover_20260927/review/homm3_stronghold_bgd_v1_vs_pb_v1.png`.
- **By eye:** Every layer is present. The rest frame differs at building edges (the re-seated Meshy bodies) and at the
  nearfield pebbles. A few nearfield grass tufts are gone at `sweep_left`, and one cone prop near the right edge is
  larger.
- **Measured streak (stretched px, full scene):**

  | pose | `pb_v1` (DA V2 Large) | `bgd_v1` (img2img) |
  |---|---|---|
  | sweep_left | 10979 | 12267 |
  | sweep_right | 20880 | 18963 |
  | sweep_high | 23101 | 21326 |
  | default | 504 | 554 |

  **Verdict:** Roughly neutral: sweep_left is up 12%, sweep_right is down 9% and sweep_high is down 8%. The new depth is not adopted for this town. `pb_v1` stays installed, and no Meshy
  credits were spent on the new depth.
- **Proof tier:** generated artifact. The bundle was built and editor-rendered; it is not installed.

## Reproduce

```
python tools/homm3_town_scene_meshes/stronghold_t2_meshy.py spend
TOWN_FULL3D_CANDIDATE=t2_v1 python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py candidate-init --seed-from wall_v40
#   (copy wall_v40/work/closing_walls.npz into t2_v1/work: candidate-init does not copy it)
TOWN_FULL3D_CANDIDATE=t2_v1 python tools/homm3_town_scene_meshes/stronghold_full3d_meshy.py fit --procs 3
TOWN_FULL3D_CANDIDATE=t2_v1 python tools/homm3_town_scene_meshes/stronghold_full3d_meshy.py stage --procs 3
TOWN_FULL3D_CANDIDATE=t2_v1 python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py bundle
TOWN_FULL3D_CANDIDATE=t2_v1 python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py render
TOWN_FULL3D_CANDIDATE=t2_v1 python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py validate
TOWN_FULL3D_CANDIDATE=t2_v1 python tools/homm3_town_scene_meshes/t2_town_review.py --before wall_v40 \
    --out artifacts/claude_takeover_20260927/review/homm3_stronghold_t2_buildings.png
```
