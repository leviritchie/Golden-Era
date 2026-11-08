# Depth-map town buildings as solids (credit-free building pass)

Status: **generated artifact / editor-render evidence only.** The candidate is offline. It has not been installed, and
there is no startup, runtime or in-game proof. Scope: a reusable, credit-free method (no Meshy, no paid generation) that
turns the depth-relief buildings of a full-3D HoMM3 town scene into better closed models. It was piloted and then
applied to all 29 Stronghold prefabs.

Parent lane: `docs/homm3_stronghold_full_3d_town.md` covers registration, terrain, periphery and effects. This doc
replaces only its section 3 (Buildings) mesh closure, and only when `--building-method solid` is used.

## Code

| File | Role |
|---|---|
| `tools/homm3_town_scene_meshes/stronghold_full3d_solids.py` | The solid closure (`build_solid`) and the per-layer `TUNE` rows |
| `tools/homm3_town_scene_meshes/stronghold_full3d_buildings.py` | Shared front surface (`front_surface`, `front_albedo`). The relief method is unchanged: its output is byte-identical to before on the checked layers. `stage_buildings(..., method=)` dispatches |
| `tools/homm3_town_scene_meshes/stronghold_full3d_scene.py` | `candidate-init` command, `--building-method {relief,solid}`, and `STRONGHOLD_FULL3D_CANDIDATE=<name>`, which redirects every output to `artifacts/homm3_stronghold_full3d/candidates/<name>/` so the shipped `bundle/` is never overwritten |
| `tools/homm3_town_scene_meshes/stronghold_full3d_building_review.py` | Offline (moderngl) before/after review: per-building sheets plus `metrics.json` |

Workflow:

```
STRONGHOLD_FULL3D_CANDIDATE=solid_v1 python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py candidate-init
STRONGHOLD_FULL3D_CANDIDATE=solid_v1 python .../stronghold_full3d_scene.py stage --parts buildings --building-method solid
python .../stronghold_full3d_building_review.py --before <shipped unity stage dir> --after <candidate stage dir> --out <dir>
STRONGHOLD_FULL3D_CANDIDATE=solid_v1 python .../stronghold_full3d_scene.py bundle     # memgate + launch_guard + unitylock
python tools/validate_town_scene3d_contract.py --catalog <candidate>/bundle/catalog.json
```

`candidate-init --seed-from <name>` seeds a new candidate from an existing one instead of the shipped outputs.
`solid_v2` was seeded from `solid_v1` this way. `stage --only <layer>` now merges that layer's building rows into
`stage_report.json`. Before this change it replaced the whole buildings section.

The review tool takes `--labels before,after` for the sheet captions. `--rest-diff` also writes two images per layer:
- `<layer>_restdiff.png`: |after - before| at the rest pose, ×4;
- `<layer>_restzoom.png`: the reference, before and after, zoomed to where they differ.

`metrics.json` also carries `restErrSumVsHomm3`, the error summed over the mask. The mean alone moves when the mask
changes.

## Defects found (the "before", ranked by in-game visibility)

The review renders the rest pose, the vanilla sweep extremes (`sweep_left`, `sweep_right`, `sweep_high`, each about 5
camera units, roughly 18 painting metres), and ±18 deg orbits. The orbits are stress tests only; the runtime does not
reach them. Cursor poses are pure rotations, so they reveal nothing and are not reviewed. Metrics per pose:

- `revealed`: pixels hidden at the rest pose, found by reprojecting into the rest depth;
- `streak`: pixels whose UV footprint has anisotropy above 6, which is smeared texture;
- `restErrVsHomm3`: mean abs error of the rest render against the HoMM3 painting plus sprite.

Defect classes of the relief closure:

1. **Streaked side walls.** Each silhouette edge is extruded along the camera ray, so one texel column smears over the
   whole depth. This is the most visible defect: white slabs on the Capitol towers, black fins on the wall towers,
   comb fins on the huts.
2. **Ground slabs.** Plazas, yards and paths that are part of the sprite are extruded to the building's thickness,
   which gives the Capitol plaza, the tavern and market yards, and the bank steps.
3. **Thin parts become sheets.** Poles, spires, banners and blades are extruded to the whole building's depth. Their
   depth also wobbles with the depth model's noise: the lyceum pole, the market spire ring, the mage-guild tower and
   the windmill mast.
4. **Holes at depth steps.** Cut triangles leave see-through gaps, for example the windmill cave on Lvl6_2.

Before ranking, worst first by the sweep metrics and the sheets:

1. lyceum
2. extraCapitol_1/2/3
3. dwellingUp2Lvl6_2
4. dwellingUp2Lvl5_2
5. wall_2/3
6. tavern and market
7. bank
8. huts Lvl1/2
9. the rest

The mage guild and resource depot are the least visible.

## Method (solid closure)

The camera-facing front is kept. Every front vertex stays on its own pixel's camera ray, so moving it along the ray
leaves the rest pose unchanged by construction. The closure behind it is new:

1. **Ground / upright split.** A vertex's height above the painted terrain at its own pixel is
   `h = (z_terrain - z)·|ray·floor.n|`. A vertex with `h` below `H_UP_M` (0.6 m) is ground: it keeps its relief depth
   and gets no volume. Upright specks smaller than 12 cells also count as ground.
2. **Thin members straightened.** Row runs narrower than `THIN_M` (1.5 m) are grouped into 8-connected segments. Each
   segment gets a robust (Tukey IRLS) line fit `z = a + b·t` along its own principal axis `t`
   (`member_axis`), so a pole stays straight and its depth is constant across its width. The earlier planar fit
   `z = a + b·y + c·x` let a background-deep edge column tilt a 1-3 px member about its own axis: once
   `drop_fringe` kept that column, the Stronghold lyceum spire turned edge-on at `pan_sweep_left` and the back behind
   it rendered from inside as a black half-spire (2026-09-29, candidate `fringe_v36`; fixed in `fringe_v37`).
   Regression test: `test_town_full3d_thin_member.py`.
3. **Depth steps sunk, not cut.** A triangle across a depth step is kept at its far depth, with the same UVs, so the
   rest pose keeps its texels and there is no see-through gap.
4. **Width-driven thickness.** In each grid row, every run of upright vertices becomes a cross-section.
   - Its depth is `DEPTH_K`·width (0.8), with a superellipse profile (`PROFILE_N` 3), 0 at the run's ends.
   - It is capped per layer (`T_MAX_M` 16 m by default; crags use the relief lane's hand-set cliff thickness).
   - It is also capped by `DEPTH_K` × the vertex's own column run, so nothing is deeper than it is tall.
   - It is then smoothed vertically.
   The result: a pole is as thin as it is wide, a hut is about as deep as it is wide, and ground has no volume.
5. **Back surface.** The smoothed front depth plus the thickness, placed along each vertex's own ray and welded to the
   front on the upright outline. It is continuous across the front's depth steps, so a step opens onto the volume's
   inside.
6. **Back texture.** Per row, the front art is re-parametrised by 3D arc length. A side shows the building's own edge
   texels spread around the profile (the mirrored hidden side) instead of one smeared column.
7. **Atlas.** The atlas is the de-lit front plus a back half. The back half's luminance is capped at the front's 85%
   quantile and darkened ×0.9, so a sunlit back face does not blow out painted highlights. The atlas is padded to
   16-texel multiples, because NPOT mip misregistration had cost about 8 of rest diff.

`TUNE` rows (hand-set, Stronghold-specific) cover parts the width rule cannot know about:
- lyceum: `tmax 1.2 m`, `n 2`, for a pole with cloth banners;
- round towers and domes: `n 2` for the resource depot and Lvl3, `n 2.5` for the octagonal mage guild.

## Pilot (5 worst) and all-29 result

Pilot sheets: `artifacts/homm3_stronghold_full3d/candidates/solid_v1/building_review_pilot/`. All 29:
`artifacts/homm3_stronghold_full3d/candidates/solid_v1/building_review/<layer>.png`, with `metrics.json`.

Each sheet shows, left to right: the HoMM3 painting plus sprite (the reference), the rest pose before, and the rest pose
after. Below them are before/after rows for each sweep extreme and orbit, all from the vanilla in-game camera pose.

Pilot verdicts:

| Building | Verdict |
|---|---|
| `dwellingUp2Lvl2_2` | Clearly better |
| `wall_3` | Clearly better; the towers are still thin at ±18 deg |
| `tavern` | Better; a mild warm patch remains on the sunlit gable back |
| `extraCapitol_3` | Better; no slabs |
| `lyceum` | Much better; the pole is straight, with a wedge at the spire tip under orbit |

All 29, summed over the three sweep extremes:
- revealed: 212,624 -> 55,611;
- streak: 471,776 -> 35,971.

Per building (rest error vs HoMM3 before/after, revealed before/after, streak before/after):

| Layer | restErr | revealed | streak |
|---|---|---|---|
| `extraCapitol_2` | 10.69 / 6.24 | 23973 / 4923 | 44658 / 2473 |
| `extraCapitol_1` | 10.27 / 5.75 | 22623 / 3544 | 34246 / 2003 |
| `lyceum` | 14.83 / 11.60 | 13147 / 1585 | 40290 / 1837 |
| `extraCapitol_3` | 5.93 / 5.93 | 11027 / 6863 | 39033 / 4031 |
| `dwellingUp2Lvl6_2` | 6.26 / 6.26 | 13397 / 2608 | 25100 / 907 |
| `wall_3` | 7.91 / 7.92 | 10400 / 1481 | 25736 / 685 |
| `market` | 7.66 / 7.66 | 11064 / 2735 | 21054 / 2228 |
| `tavern` | 11.45 / 8.05 | 10623 / 3551 | 20906 / 2118 |
| `wall_2` | 7.90 / 7.90 | 9599 / 1420 | 20621 / 405 |
| `dwellingUp2Lvl5_2` | 7.01 / 6.42 | **7381 / 11076** | 20190 / 10183 |
| `dwellingUp2Lvl2_2` | 5.34 / 5.34 | 7656 / 1282 | 15805 / 489 |
| `dwellingUp2Lvl7_2` | 9.81 / 2.87 | 6832 / 179 | 16533 / 126 |
| `dwellingUp2Lvl7_1` | 9.52 / 2.93 | 6707 / 212 | 16350 / 125 |
| `dwellingUp2Lvl6_1` | 7.10 / 3.23 | 6375 / 3523 | 15255 / 1333 |
| `bank` | 11.70 / 8.05 | 5149 / 1564 | 16039 / 2100 |
| `dwellingUp2Lvl2_1` | 4.94 / 4.94 | 4837 / 1092 | 13430 / 585 |
| `dwellingUp2Lvl3_2` | 7.33 / 7.31 | 5600 / 1592 | 12203 / 571 |
| `dwellingUp2Lvl4_2` | 9.83 / 7.20 | 4200 / 1024 | 11619 / 945 |
| `wall_1` | 7.06 / 7.06 | 4845 / 802 | 10859 / 408 |
| `dwellingUp2Lvl1_2` | 10.78 / 6.31 | 5359 / 913 | 9964 / 292 |
| `dwellingUp2Lvl1_1` | 10.42 / 5.88 | 4839 / 484 | 8012 / 205 |
| `dwellingUp2Lvl4_1` | 5.92 / 5.92 | 3941 / 732 | 7478 / 630 |
| `dwellingUp2Lvl3_1` | 7.08 / 7.08 | 2604 / 1361 | 7367 / 764 |
| `dwellingUp2Lvl5_1` | 6.11 / 6.11 | 3423 / 119 | 5863 / 47 |
| `artifactMarket` | 9.78 / 5.19 | 2997 / 644 | 3777 / 128 |
| `resourceDepot` | 16.03 / 13.17 | 1309 / 73 | 3139 / 67 |
| `magicGuild_3` | 7.57 / 7.57 | 980 / 155 | 2372 / 169 |
| `magicGuild_2` | 9.63 / 9.86 | 1004 / 44 | 2283 / 68 |
| `magicGuild_1` | 10.80 / 5.89 | 733 / 30 | 1594 / 49 |

Honest reading:

- **28 of 29 improve clearly.** Rest error against HoMM3 is equal or lower for every building except `magicGuild_2`,
  where it rises slightly (9.63 -> 9.86).
- The Capitol, walls, huts and Lvl7 crags lose their slabs and fins.
- The market and tavern are still lumpy at the orbits: cart, hay and gable are blob-shaped. They are better, not
  modelled.
- **`dwellingUp2Lvl5_2` (the bird on the crag) is mixed.** Streak is halved, but revealed rises. The relief's pale
  smears are replaced by dark jagged shards along the top edge of the wings at the sweeps.
  - The shards are the wing's own back surface. The wing row runs are wide, and their column run joins the bird's
    body and the crag, so neither the width cap nor the column cap makes them thin.
  - Turning off depth-step sinking for this layer was tried. It does not remove the shards and it opens holes at the
    rest pose, so it was reverted.
  - The fix needs part separation: a wing should be a thin card, apart from its crag. That is not done.

### Back kept behind sunk step triangles (2026-09-29)

- A sunk depth-step triangle sits at its farthest vertex's depth. The back surface uses the *smoothed* front depth, so
  near a deep step it could pass in front of that triangle. Its back-half texels then showed through the front as a
  1-3 px line.
- `build_solid` now pushes every upright, non-rim back vertex of a sunk triangle to `SINK_BACK_MARGIN` (0.3%) behind
  that triangle's farthest depth. The count is reported per building as `solid.sinkBackRaised`.
- Bulwark proof: candidate `fx_v5`, all buildings restaged. Tier: generated artifact plus Unity editor render; not
  installed, not in-game.
  - Before (`fx_v4`), `tbbucas3` drew a pale green-white line at `full3d_full` x317-319, rows 195-326.
  - After (`fx_v5`), the line is gone, and so are two dark slivers on other buildings. The bright-line and dark-bar
    scans show no new hits, and the contract gate is OK.
- The Unity runtime lights these texels, but the offline preview draws them dark. Check at least one Unity render
  before calling a line of this kind fixed.
- The rule is generic, so it reads no faction name. Other factions pick it up the next time their buildings are
  restaged. Their installed bundles are unchanged until then.

### Mask opening kept inside the sprite (2026-09-29)

- `native_mask` removes 1 px specks with a 2x2 `MORPH_OPEN`. An even kernel's anchor is off-centre, so the opening
  alone shifted the mask edge by 1 px and added a transparent rim on the right and bottom edges. Those texels are the
  sprite's black transparent pixels, and they rendered as 1 px near-black bars.
  - Before, `mask & ~alpha` was 66 px for Stronghold `extraCapitol_3` (63 on rims), 396 for `lyceum` (393) and 152 for
    `bank` (146).
  - These rims are not interior slits. A see-through slit scan over every faction found 0.
- The mask is now `m & open(m)`. The speck removal stays, and the mask never gains a pixel outside the unopened mask.
  After the fix, `mask & ~alpha` is 0 for `extraCapitol_3` and `lyceum`. What remains (64 px on `bank`, 684 over all
  Stronghold layers) is the deliberate fill of holes smaller than 400 px.
- Stronghold proof: candidate `tex_sdgrade_v35_opening` = the installed `v34_winding` with the buildings restaged
  (this fix plus `sinkBackRaised`). Tier: generated artifact plus Unity editor render; not installed, not in-game.
  - Rest-render dark bars went from `[151, 311, 637]` to `[151]`. x151 is black painted into the sprite itself.
  - The bar scan over all 21 renders at 1080p lost x311 and x637 wherever they appeared. It gained borderline hits on
    existing dark edges at off-rest poses: `pan_orbit_y-18_p+6` x457 and `pan_sweep_left` x219. `full3d_full_sway_2`
    went from [118, 277] to [118, 119].
  - Seams are unchanged: x1440 2.934/55, y673 1.749/29. Back bleed went from 7 px to 6.
  - Building-pixel fidelity to the HoMM3 sprites over the whole footprint (`sprite_err.py`, 542769 px, rest render):
    mean dE 5.124 -> 5.145, p50 3.16 -> 3.19. That is slightly worse. The delta map is fine noise along the restaged
    relief's normal creases, the same place the de-lit texels are misregistered. It is not a fidelity gain.
- The rule is generic, so it reads no faction name. Other factions pick it up the next time their buildings are
  restaged. Their installed bundles are unchanged until then.
- **Superseded the same day (see next subsection).** `m & open(m)` erodes: OpenCV runs erode and dilate with the
  same off-centre anchor, so the intersection shaves the top / left px off every shape and deletes every sub-2px
  feature (a 6x6 square becomes 5x5, a 1 px line vanishes).

### Fringe removal nominated by a true opening (2026-09-29)

- An audit over every faction's sprites (pre-area-filter, pre-hole-fill) found `m & open(m)` removing 7.1-22.5% of
  the mask (Inferno 13.1%, 20303 px of it differing from the painting under it by dE76 > 20). At rest the Inferno
  spire `tbinext2` lost the left half of every flame spike and of its thin yellow rays, which rendered as broken
  rays with dark holes. The mean-dE gain of the rollout came from the registration fix below and hid the loss.
- `drop_fringe(m, rgb, under)` now does the speck removal. A true 2x2 opening (erode with anchor (0, 0), dilate
  with the reflected anchor (1, 1)) is a subset of m, so it never adds a rim and cannot bring the bars back. It
  only nominates: a nominated px is dropped when its colour is within `FRINGE_DE` (dE76 20) of the painting under
  it. Thin opaque rays, spike tips and teeth stay; background-coloured specks and fringe go. The 25 px area filter
  and the hole fill are unchanged.
- Regression test: `test_town_full3d_mask_fringe.py` (a 6x6 block stays 6x6, an opaque 1 px ray survives, a
  background-matching speck is dropped, the result stays within the input mask).

### De-lit texels registered on the relief grid (2026-09-29)

- `front_albedo` de-lights the sprite by the light at the front's shading normals. It used to resample the per-vertex
  normal grid to texels with a plain `cv2.resize`, which spreads the grid evenly over the box. Grid vertex k actually
  sits at box px `xs[k] + 0.5` (`xs = 0, GRID, ..., ceil(fw) - 1`). The drift reached about 1.1-1.3 px on the Cove
  hall (x226-260), so at a normal crease one texel column was de-lit with the neighbouring facet's light. That
  showed as 1-2 px overbright orange lines (and some dark ones).
- `grid_to_texels` now samples the grid at each texel's own frame position (bilinear `remap` over `grid_axis`). It
  fails closed if the field is not the relief grid's shape. Geometry is unchanged; only the albedo bake moves.
- Cove proof: candidate `cv_v5` = `cv_v4` with buildings and fx restaged, with only this change. The mask-opening fix
  was held back for the build so the effect could be isolated. Tier: generated artifact plus Unity editor render;
  not installed, not in-game.
  - Fidelity to the HoMM3 sprites (`sprite_err.py`, rest render, whole footprint, 693214 px): mean dE
    6.634 -> 6.351, p50 3.70 -> 3.50, p90 14.61 -> 13.91.
  - Band x216-330: mean dE 6.90 -> 5.93, p90 15.74 -> 13.37.
  - Bright-line hits at rest: 111 -> 83.
  - Seams are unchanged: x1440 1.172/11, y673 2.873/96. Rest dark bars are unchanged.
  - A few off-rest dark-bar scan hits move across the 40-row threshold on existing dark edges (for example
    `pan_sweep_right` x644 goes from 78 to 83 dark rows).
- This is now the default. Other factions pick it up the next time their buildings are restaged, together with the
  mask opening above. Their installed bundles are unchanged until then.

## What generalizes, what is Stronghold-specific

Generic (nothing reads a faction name):
- the ground/upright split against the painted terrain;
- thin-member straightening;
- sinking at depth steps;
- width-driven thickness with the column cap;
- the arc-length back texture;
- the back-half atlas and 16-texel padding;
- candidate redirection and the review harness.

Another faction needs these inputs from its own full-3D lane:
- a sprite mask;
- per-crop calibrated depth (`layer_depth`: mask, z, terrain z, kind, thick);
- the rest-pose camera;
- the floor plane.

Stronghold-specific:
- the `TUNE` rows (lyceum banners, round and octagonal towers);
- the crag kind and its hand-set cliff thickness (Lvl5-7 cliff dwellings);
- the constant `BACK_DARKEN`.

For each new faction, expect to add `TUNE` rows for flat cloth (banners, awnings: low `tmax`) and for round forms
(`n` 2). For flying or overhanging parts over a larger mass (the Lvl5_2 wings), expect the same failure until part
separation exists.

Cost: all 29 buildings stage in about 20 s, and the offline review takes about 45 s. It needs no GPU beyond moderngl
and no Blender. Unity runs only for the bundle.

## Part separation (solid_v2)

`--building-method solid_parts` closes the layers listed in `PARTS_LAYERS` with part separation. Every other layer
closes exactly as `solid`, so its geometry is byte-for-byte the solid_v1 closure; the review shows restDiff 0 and
identical metrics for all 26 of them.

Parts are cut where grid neighbours' depth ratio exceeds `PART_RATIO` (1.03, or a per-layer `partRatio`). Each part is
then closed on its own:
- its own row and column runs, so the thickness and the no-deeper-than-tall cap stop at the part boundary;
- its own smoothing of thickness and back depth;
- arc-length back UVs per part;
- no back triangle bridges two parts.

The rules below were each measured on `dwellingUp2Lvl5_2` against solid_v1. The probe numbers are not kept in the
repo.

| Rule | Why |
|---|---|
| Parts smaller than 24 cells merge into their most-shared neighbour | Specks do not get their own back |
| Parts with ≥60% of their cells on the silhouette outline merge the same way | They are depth-model halo, not parts |
| No boundary is cut on the silhouette outline itself (`EDGE_BAND` 1) | Band 2 or 3 made the rest pose worse |
| The outline keeps the plain closure's thickness and back depth | The back there covers the front's sunk halo triangles at the rest pose |
| The back is **not** welded to the front at part boundaries (`PART_WELD` off) | Welding cost rest error: 6.42 -> 6.91 |
| Back triangles that bridge two parts are dropped (`PART_BRIDGE` off) | Keeping them was worse at rest (7.13) and at every sweep |

Which layers use it. The rule is equal or better than solid_v1 at rest (error summed against HoMM3) and at all three
sweep extremes; otherwise a layer keeps its solid_v1 closure.

| Layer | Result against solid_v1 | Kept at v1? |
|---|---|---|
| `dwellingUp2Lvl5_2` | Rest 6.42 -> 6.39. Revealed/streak: `sweep_left` 3972/4274 -> 2102/2918, `sweep_right` 1529/923 -> 1245/812, `sweep_high` 5575/4986 -> 3028/3362. The dark shards along the tops of the wings are mostly gone. A sky-blue halo patch above the left wing and a few pale flecks on the right wing remain at `sweep_left` | No |
| `market` (`partRatio` 1.01) | Rest identical. `sweep_left` 576/773 -> 410/707, `sweep_right` 1390/1025 -> 1180/921, `sweep_high` 769/430 -> 629/361. The hay and stalls are only modestly less blob-like; they still read as lumps at the orbits | No |
| `wall_2` | Rest identical; sweeps equal or better by a pixel or two (tiny) | No |
| Every other layer, including `tavern` | Kept at solid_v1 | Yes |

Why the others were kept:
- **Tavern.** No depth step reaches the ratio even at 1.01, so there are no parts; separation cannot change it. Its
  remaining defect is a pale patch at the left gable end at the sweeps. That is back-texture content (mirrored edge
  texels), not a part-thickness blob.
- **`artifactMarket`.** Parts found at 1.03 made `sweep_right` and `sweep_high` a few pixels worse (revealed 323 -> 327
  and 151 -> 152).
- **Everything else.** Most layers have no depth steps at 1.03, so they are unchanged either way.

All 29 against the relief shells, summed over the three sweep extremes (`candidates/solid_v2/building_review/`):
- revealed: 212,624 -> 50,393;
- streak: 471,776 -> 32,640.

`dwellingUp2Lvl5_2` against relief:
- rest error 7.01 -> 6.39;
- streak lower at every sweep (for example `sweep_left` 9159 -> 2918);
- revealed still a little above relief at `sweep_right` (1184 -> 1245) and `sweep_high` (2461 -> 3028).

Depth-step separation only finds props that stand apart in depth. Parts joined at a similar depth (a gable over its
porch, hay against its cart) need an appearance cue. None is used here.

## Back texture fill (solid_v3)

`--back-fill` gives a new back texture to the layers listed in `BACK_FILL_LAYERS`. Every other layer keeps its solid_v2
back byte-for-byte. The rule is general: it reads no faction or building name.

The old back was the front art, mirrored by arc length, with highlights capped at the 85% luminance quantile. The pale
patch at the tavern's left gable came from that back half (checked with a render that tints the back half green).
Arc length puts the row's own left-end texels on the side wall, and those texels are the pale, lit veranda interior.

The new back does four things:
1. It replaces the texels within `BACK_ERODE_TX` (2) of the mask edge with the interior pushed outwards: a normalised
   blur at growing scales, which removes the edge halo.
2. It compresses the contrast toward the building's own median colour (`BACK_FILL_CONTRAST` 0.5). This lifts painted
   shadows as well as lowering painted highlights.
3. It caps luminance at the front's 60% quantile (`BACK_FILL_LUM_Q`).
4. It sets `BACK_FILL_DARKEN` to 1.0 (no extra darkening).

The review now also counts two things over the revealed pixels at each pose:
- `revealedPale`: brighter than the building's own rest-pose 90% luminance quantile;
- `revealedDark`: darker than its 10% quantile.

A cap alone trivially lowers `pale`, so `dark` is there to catch a side pushed to mud.

Variants measured on six buildings (tavern, extraCapitol_1, Lvl1_1, Lvl6_1, bank, market):

| Variant | Result |
|---|---|
| Cap alone (60%) or erode + blur + cap | Removes the pale patch; raises `dark` at `sweep_left` on most buildings |
| Compression alone (0.35 / 0.5) | Balanced, but leaves most of the tavern patch (652 -> 584 to 606 pale px at `sweep_right`) |
| Compression 0.5 + cap 60% | Removes the tavern patch (`sweep_right` 652 -> 3 pale px, `sweep_high` 426 -> 0); passes the most layers |

The per-layer bar against solid_v2:
- geometry is unchanged, so revealed and streak are identical;
- rest error summed against HoMM3 is no worse than +0.05%;
- pale + dark at each of the three sweep extremes is no worse.

The tavern (+1 on 207,685), `dwellingUp2Lvl4_2` (+28 on 186,368) and `extraCapitol_2` (+1) are inside that rest
tolerance; every other listed layer is equal or better.

18 layers pass and are listed in `BACK_FILL_LAYERS`:
`artifactMarket`, `bank`, `dwellingUp2Lvl4_1`, `dwellingUp2Lvl4_2`, `dwellingUp2Lvl5_1`, `dwellingUp2Lvl6_2`,
`dwellingUp2Lvl7_1`, `dwellingUp2Lvl7_2`, `extraCapitol_2`, `extraCapitol_3`, `lyceum`, `magicGuild_1..3`,
`resourceDepot`, `tavern`, `wall_1`, `wall_3`.

11 layers are kept at solid_v2:
- `dwellingUp2Lvl1_1/1_2/2_1/2_2/3_1/3_2`, `dwellingUp2Lvl6_1` and `wall_2`: `dark` rises at `sweep_left`, by 5 to 224
  px (for example Lvl6_1 317 -> 541);
- `extraCapitol_1`: pale falls from 520 to 188, but `dark` at `sweep_left` rises from 225 to 282;
- `market`: `dark` at `sweep_left` rises from 197 to 201 with the fill, so its back stays at solid_v2 (its geometry
  changes through the colour cue below);
- `dwellingUp2Lvl5_2`: rest error summed rises from 386,505 to 389,725. The back there covers the sunk wing halo at the
  rest pose.

Summed over the three sweeps for all 29 (`candidates/solid_v3/building_review_vs_v2/`, back fill plus the market's
colour cue):
- pale: 10,607 -> 6,253 px;
- dark: 8,408 -> 7,633 px.

## Appearance-cue part separation (solid_v3 prototype, market and tavern only)

`TUNE[<layer>]["partColor"]` adds a second split rule to part separation. It applies only on a `PARTS_LAYERS` layer
that sets it. Two grid neighbours at a similar depth are still split when the sprite's CIELAB chroma (a*, b*) differs
by more than `partColor`. The sprite is median-filtered first (`COLOR_MEDIAN_PX` 5), so texture grain does not read as
a boundary. L* is left out because in a painted sprite it is mostly lighting. The code is `_grid_chroma` and the
`chroma` / `color_step` arguments of `_parts`.

It was measured on the market and the tavern only, against solid_v3 without the cue (`v3_color_*` probes in the
scratch folder). Revealed/streak are given at the sweep extremes, with `thickP50M` as the median solid thickness:

| Step | Market | Tavern |
|---|---|---|
| 12, 18 | No colour boundaries; identical | No colour boundaries; identical |
| 8 | 11 parts (5 before). Left 410/707 -> 319/677, right 1180/921 -> 651/686, high 629/361 -> 310/252. Rest identical, pale+dark better at every sweep. Thickness 2.57 -> 1.85 m | No boundaries: the chroma changes between neighbours are too gradual |
| 6 | 20 parts. 116/639, 399/538, 167/164. `dark` at `sweep_right` 35 -> 71. Thickness 1.29 m | No boundaries |
| 4 | 87 parts. 90/614, 259/511, 127/154. Thickness 0.76 m | 116 parts, 1611 boundary edges. Revealed collapses (1064 -> 16, 1506 -> 43, 981 -> 22) because thickness falls from 5.68 to 0.75 m |

Findings:
- **Much of the revealed gain is thinning, not better volume.** Thickness is width-driven per part, so smaller parts
  are thinner and occlude less. Below step 8 the cue mostly flattens the building back toward a relief; revealed is
  not a quality measure on its own once parts shrink.
- **Tavern: negative.** No step gives a useful split. At steps 6 to 18 there is no boundary. At step 4 the tavern
  shatters into thin shells, which look like the old relief at the sweeps. The tavern is not in `PARTS_LAYERS` and
  sets no `partColor`.
- **Market: adopted at step 8.** The cart and hay bales separate from the stall mass. At `sweep_right` and
  `sweep_high`, the hay bale's smear visibly shortens, and the rest pose is byte-identical in error. The market
  thins by 28% at the median. For carts and bales that is closer to the painting than the stall-sized slab it had.
- **Not widened.** A chroma step is a per-building threshold, and it failed on the tavern, so it stays a
  per-layer TUNE value and does not become a rule.

## Front-surface winding (fixed 2026-09-29, f5f49fd165)

`front_surface` (shared by the relief and solid methods) wound each front triangle toward its shading normal. Those
normals are smoothed and bent toward the key light, so on steep depth faces they disagree with the triangle's own
side: 3524 of 43946 front triangles of Inferno's `tbincstl_3` keep faced away from the rest camera. The lab HexLit
(Cull Off, normal flipped on back faces) shaded them black as 1 px vertical bars. A back-face-culling shader would
have dropped them instead. The game donor's cull mode was unknown at the time; it is now pinned (next section).

`wind_to_camera` now winds every front triangle toward the camera. Every vertex sits on its own pixel's ray, so this
is the grid's own screen winding. Only the winding changes: P, n, uv and textures are the same.

The regression test is `test_town_full3d_winding.py`.

Evidence:
- **Offline emulation of the lab shader** (Inferno): bar columns over the six pan poses went from 8/7/7/4/3/2 to 0.
  The stored-normal preview is byte-identical before and after.
- **Unity editor renders** (Inferno seam_v1): 0 bars at every 1080p pose. The rest render had 6 bar groups before
  the fix (single columns and short runs).
- **Stronghold** (v34 = v33 inputs plus this fix): 29 of 53 bins change winding only, 4978 triangles rewound, and
  every other staged file is byte-identical. Unity rest-render bars go from 9 to 3. The 3 that remain are also in the
  stored-normal offline render, so they are painted dark features or geometry, not winding.
- **Residue:** a few 4K-only hits (the frame edge, the pyre) are not yet root-caused.

Every town built by this lane changes winding when it is rebuilt.

## Back-face culling and the see-through gate (2026-09-29)

The installed Hex/Lit Lit pass culls by the material's `_CullMode` (default 2 = Back; the logged donor
`fence_field_mt` has 2) and has no `SV_IsFrontFace`. The plugin now pins `_CullMode = Back` on every lit clone and
logs the donor's own value (`Homm3TownScene3d.RebindLitPieceOrThrow`, 220a8d6fe7; deployed, the log line is
runtime-unproven). The lab replica `unity/Homm3TownLabHexLit.shader` matches it (Cull Back, no face flip,
505f1c4039), so editor renders show a step face seen from behind as a see-through slit, as the game does, not as a
black bar.

`town_full3d_cull.py` counts those slits offline. It renders the full state's piece ids with and without Unity
back-face culling (GL `cull_face = "front"`: handedness) at 12 poses: rest, the ±2.5 render sway, the six vanilla pan
proof poses and the three review orbits. It counts `Mesh_Body_` px whose winner changes. Every building stage
runs it (`work/see_through.json`, `stage_report.json` `seeThrough`), and `stronghold_full3d_scene.py cull`
re-measures a staged candidate. The gate is **no worse than the installed candidate at any pose**
(`town_full3d_cull_baseline.json`, measured on the eight installed candidates); a faction without a row is
report-only. Lower a row only after installing a candidate that measures lower. Test:
`test_town_full3d_cull.py`. Tier: generated artifact (offline id render, no lighting).

### Closing walls on sunk steps (2026-09-29)

Where the see-through came from (Cove cv_v6, offline triangle classification): about 95% of the lost px were back-sheet
triangles that are edge-on at rest (sweep_right 41765 of 44111, orbit +18 63578 of 70485). A cut step's front
triangle is sunk flat to its far depth, so the only surface left at the step was the back sheet. That sheet is wound
away from the camera, and where the near part lies inward of the step it faces inward. A camera panned toward the far
side saw its back. The game culled it and showed the environment; the old lab drew it black (the "side wall lit black"
class).

`stronghold_full3d_buildings.closing_walls` (called by `front_surface` with `sink_cuts`, i.e. both solid methods):
- **Split:** each cut triangle is split at its largest depth-ratio gap.
- **Wall:** where two vertices are near, a quad runs on those two vertices' own rays from their depth to the sunk depth.
- **Rest pose unchanged:** the quad lies in the plane of the two rays, so it projects to zero area at the rest camera.
- **Watertight:** it shares its top edge with the near sheet and its bottom edge with the sunk triangle.
- **Winding:** toward the far side, not toward the camera.
- **Texels:** one existing front texel of the building per wall, unmodified (`stronghold_full3d_solids.wall_texels`):
  of the in-mask texels within 16 texels of the edge midpoint and at least 3 texels from the edge line, on the near
  side of that line (away from the cut triangle's far vertex), the 24 nearest the midpoint; of those, the one of
  median luminance rank; all four corners sit on its centre. A step on the silhouette (near vertices on the outline
  ring, whose in-mask part is the 1-2 texel outline: Cove tbcvdock) has no near-side texel 3 in; its band is taken
  the same way inward on the far side, and such walls are counted (`wallTexels.silhouette`). Earlier rules that
  failed closed on real layers: a depth threshold for the near side (Cove tbcvsay1: the near surface slopes past the
  far layer's depth) and a depth comparison beside the edge (silhouette edges have no in-mask texel there). Repeating the near edge's own texels smeared an
  edge highlight (a lit window) along the wall as a bright yellow streak (Cove cv_v9 sweep_right / orbit +18). No
  tonal change: the back half is derived (capped / compressed) art and is not used, and `build_solid` fails closed if
  a wall uv is off a texel centre or its texel is not an in-mask front texel. Mip levels average neighbours as for
  every surface. Test: `test_town_full3d_wall_texels.py`.
- **Rest pose:** `town_full3d_wall_rest.py`. The stage fails closed if any wall triangle covers 1e-6 frame px^2 or
  more at the painting camera (measured ~1e-13), and writes each building's wall near edges (prefab frame) to
  `work/closing_walls.npz`. The walls are on the Unity rest camera too: bins are in the prefab frame with the
  painting camera at the origin, and framing is an FOV change plus a rotation about that point. At rest a wall still
  touches pixels, only on its own projected edge: the rasteriser leaves crack pixels between a near sheet's edge and
  its sunk triangle (light or black specks in Cove cv_v8), and the edge-on wall fills them (cv_v8 -> cv_v9: 6460 px
  at 1080, all on step edges). So the Unity check is not zero-diff: `python town_full3d_wall_rest.py --faction F
  --before <twin> --after <candidate>` requires every rest-render pixel that differs by more than 2 levels between
  twins whose buildings differ only in walls to lie within 1 px of a wall's projected near edge at the framed rest
  camera (Unity editor render; generated artifact). Test: `test_town_full3d_wall_rest.py`.
- **Test:** `test_town_full3d_closing_walls.py` checks zero rest area, a closed top-edge loop, the sunk-depth bottom,
  far-side winding, and see-through 1188 -> 0 px at a side camera.

**Fray caps** (`stronghold_full3d_solids.cap_cut`, called from every `BL.edge_fray*` on a solid). A frame-edge fray
removes front and back triangles by their rest-camera centroid, so it left the solid open along the fray line: a
camera moved toward the cut saw the back sheet's inside, and the game's Cull Back showed what was behind it. This was
Necropolis tbncdock at orbit -18: 8128 of that pose's 10483 see-through px. A grid cell's front and back vertices
lie on the same rays, so the kept front's cut edge and the kept back's cut edge share two rays. The cap quad between
them lies in their plane: it is edge-on at rest (`rest_area_or_exit`), watertight, and wound toward the removed side.
Each cap carries one in-mask front texel of the building, chosen by the `wall_texels` rule (unmodified). Its near
edge goes into `closing_walls.npz`, so the Unity rest check covers it. Three variants are capped too, and each is counted. A front cut edge whose back cell was never built (the
all-upright rule beside a rim vertex: Bulwark tbbha201 at its fray's row limit) is capped on the back vertices of
its rays (`capsWithoutBackEdge`). A front cut edge whose other end is ground (no back on that ray, thickness 0 as
on the outline: Factory tbfamark, Stronghold dwellingUp2Lvl6_1, Dungeon tbdndw_0, Castle tbcscas3, Rampart
tbrmdw_2_2) gets a cap triangle to that front vertex (`capsToGround`). A back cut edge whose front cut runs along
sunk step triangles is capped against the deepest kept front edge on its rays (`capsOnUnsharedFrontEdge`); sunk
step triangles have their own vertices, so they share no index with the dropped neighbour (Cove tbcvnix1, 1 edge).
A back cut under a front that the fray left whole on those rays is a hole, and it fails closed. A fray through a closing wall
leaves a sheet edge, not an opening: wall edges are never capped. The cap's texel band is located from the edge's
rest-camera frame position, not its uv. A snapped ring uv, or a wall's single texel, can put both ends of an edge on
one texel: this happened on Castle tbcshrd2 and Fortress tbfrdw_0_2, where `wall_texels` refused the degenerate edge. A welded rim edge needs no cap. Necropolis wall_v2 had 152 caps on tbncdock; its see-through
total went from 21031 to 6863 px (tbncdock at orbit -18: 8128 -> 529). Relief shells keep plain removal. Test:
`test_town_full3d_fray_cap.py` (side camera 1158 -> 0 px; a second fray on the capped mesh stays closed; a one-sided
cut is refused).

`build_solid` also drops a back triangle whose three vertices are a sunk front triangle's when a welded rim vertex of it
has no wall and is still in front of the sunk depth. That triangle faces away, so at rest the game dropped it anyway.
Rim vertices that top a wall keep their back triangle, and rim vertices are not raised. Both alternatives let the walls
on Cove tbcvnmp2's rigging show their backs past the silhouette: orbit -18 see-through 8.4k -> 17-24k px.

A faction can opt in to `SINK_RIM_GRAZE_DROP = {"maxCos": c}` in its profile. It is off by default and only Bulwark sets
it, at 0.02. Under it, a walled-rim back triangle is dropped when its plane grazes the rest ray. Bulwark needs this for
one tbbum401 triangle: 2 px^2 at rest, |cos| 0.006. It made wall_v1 fail the gate by 1 px at each cursor pose. With the
opt-in, 64 triangles drop and the gate passes (8156 px). The rule stays scoped because it opens Cove: 85 tbcvnmp2
triangles drop and orbit y-18 goes 24593 -> 30023 px. A rest-area epsilon would not catch the Bulwark triangle, since it
is not degenerate at rest. Test: `test_town_full3d_graze_drop.py` (Bulwark on; Cove and every other faction off).

Measured, see-through total over 12 poses (installed -> restaged):

| Town | Installed | Restaged |
|---|---|---|
| Cove | 249484 | 39237 |
| Stronghold | 23411 | 10717 |
| Rampart | 49903 | 30401 |
| Castle | 39202 | 23864 |
| Dungeon | 64481 | 18184 |
| Necropolis | 26824 | 21031 |
| Bulwark | 47482 | 23253 |

- Necropolis and Bulwark fail the per-pose gate by 1-200 px at single poses, in classes the walls do not touch:
  Necropolis tbncdock has no sunk steps, and Bulwark tbbuu201 / tbbum401 regress too.
- What remains is mostly back-sheet faces that are *not* edge-on at rest, seen at the orbits and the extreme sweeps.
  Examples: Necropolis tbncdock, Bulwark tbbuu201, Cove tbcvnmp2 rigging.

## Known limits (still need modelling for free orbit)

- The hidden side is a mirror of the front, not real art. Asymmetric buildings look symmetric from behind.
- Part separation is depth-step based, on 3 layers (plus a colour cue on the market). Overhangs on other layers
  (eaves, awnings) that are joined to a larger mass still get that mass's thickness.
- The ±18 deg orbits still show wedges at spire tips and thin wall towers. The runtime sweep does not reach those
  angles.

## Candidate bundle

`artifacts/homm3_stronghold_full3d/candidates/solid_v1/bundle/homm3_town_scene3d_stronghold`:
- 104,571,399 bytes;
- sha256 `cb6023fb66f8acb15747d3eb2aa461293f236675118a50d98248aeb520b82904`;
- built through memgate, launch_guard and unitylock, with Unity rc 0.

The installed "before" bundle is unchanged at `eb7df19d...0008452`.

`python tools/validate_town_scene3d_contract.py --catalog artifacts/homm3_stronghold_full3d/candidates/solid_v1/bundle/catalog.json`
reports:
`OK homm3_stronghold layers=29 reachable=29 unused=0 depths=0 bundle=present flag=off (candidate) ... fx=14 ... panVoid=0`.

**solid_v2** (part separation on 3 layers, the other 26 at solid_v1 geometry):
- path: `artifacts/homm3_stronghold_full3d/candidates/solid_v2/bundle/homm3_town_scene3d_stronghold`;
- 104,593,002 bytes;
- sha256 `c4cc2a7a1da374690c9e463b0f42fb9a6f641f96b3d9e40ba8bdcc7fcd0780f2`;
- built with Unity rc 0 through memgate, launch_guard and unitylock.

The validator on `candidates/solid_v2/bundle/catalog.json` reports the same OK line as solid_v1 (`layers=29
reachable=29 ... fx=14 ... panVoid=0`). The solid_v1 bundle is unchanged (`cb6023fb...`).

**solid_v3** (seeded from solid_v2: back fill on 18 layers, colour cue on the market, the rest at solid_v2):
- path: `artifacts/homm3_stronghold_full3d/candidates/solid_v3/bundle/homm3_town_scene3d_stronghold`;
- 104,470,007 bytes;
- sha256 `a01fdcd408c732ae8c4609e16e2fc6aa1a9c9f06a49639b719581f7d268c3b8c`;
- built with Unity rc 0 through memgate, launch_guard and unitylock;
- review against solid_v2: `candidates/solid_v3/building_review_vs_v2/` (all 29 layers pass the per-layer bar).

The validator on `candidates/solid_v3/bundle/catalog.json` reports the same OK line (`layers=29 reachable=29 ...
fx=14 ... panVoid=0`). The solid_v1 and solid_v2 bundles and the installed "before" are unchanged.

Reviews:
- `candidates/solid_v2/building_review_vs_v1/`: against solid_v1, with rest diff and zoom images;
- `candidates/solid_v2/building_review/`: against the installed relief shells.

The anims metadata was **not** re-keyed in solid_v2 / solid_v3: their lightning sits on `dwellingUp2Lvl7_1`.

### solid_v3_1: the lightning re-key (2026-09-28, user-approved)

The lightning DEF is re-keyed to `dwellingUp2Lvl7_2` in the refs (see the parent doc), which is runtime-visible:
`Homm3StrongholdTownAnimPlayer.cs` and `Homm3FactoryCityWorldAnimDriver.cs` read that metadata. `candidates/solid_v3_1`
was seeded from solid_v3 and fully restaged with no texture override. Against solid_v3, the only staged differences
are the lightning's: the `_2` prefab's bolt mask and particle row, the `_1` row losing it, `build_spec.json` (output
path) and the catalog. A full fx stage now clears effects from prefabs it no longer names (`save_rows`), since the
merge otherwise kept the old `_1` particles. Validator OK; bundle 104,498,936 bytes,
`fcf3147fecbcb9651edb94c7a6e58b9911830b549a9b90af5bcfb759c889362d` (generated artifact; not installed by this lane).

## Faction argument (all 11 remaining factions)

The `stronghold_full3d_*` tools are now faction-generic code. Everything that describes one HoMM3 town painting lives
in `tools/homm3_town_scene_meshes/town_full3d_factions/<key>.py`:
- identity: fraction, background file, output folder, bundle, prefix, asset root, effects module;
- the hand-measured terrain values: horizon, hut scale, floor polygon, far cap, spurs, wall shift;
- the biome's vanilla filler (ground and rock textures, scatter meshes, near-field rocks, the vanilla extract lists);
- the per-building rows: relief TUNE, solid TUNE, `PARTS_LAYERS`, `BACK_FILL_LAYERS`, render states.

`--faction <key>` (or `TOWN_FULL3D_FACTION`) selects the profile and is read when the lane is first imported.
`stronghold` stays the default. A faction without a profile file stops with `no profile for faction '<key>'`, and a
missing profile field raises: there is no fallback to Stronghold's values. `TOWN_FULL3D_CANDIDATE` replaces
`STRONGHOLD_FULL3D_CANDIDATE`, which is still read; the two must agree when both are set. Depth-model weights are
shared across factions (`artifacts/homm3_stronghold_full3d/hf_cache`).

Byte-identity check (2026-09-28): a full stage of Stronghold (all parts, `solid_parts --back-fill`) with the
pre-refactor code (`candidates/gen_base`) and with `--faction stronghold` after it (`candidates/gen_after`) produce the
same 317 staged files and catalog, byte for byte. The only difference is the build spec's own `outputPath`. Those
staged inputs are also byte-identical to the installed solid_v3's. The Unity bundle is **not** byte-reproducible from
identical inputs:
- gen_base: 104,455,742 bytes, `c4949bdc...`;
- gen_after: 104,476,470 bytes, `bbf176cd...`;
- solid_v3: 104,470,007 bytes, `a01fdcd4...`.
Two builds of the same staged inputs already differ, so the proof of "rebuilds identically" is at the
staged-input level, and the installed solid_v3 bundle stays the delivery.

Known defect (recorded 2026-09-29, unassigned): Necropolis's `nativeLevels` map does not reach these layers, so they
are never staged as reachable:
- `tbnchall_4`
- `tbncmage_5`
- `tbncext0`-`tbncext5`
- `tbnchrd1`, `tbnchrd3`
- `tbncdw_*_3`
- `tbncboat`

Source/static observation only. The fix belongs to the faction's layer map, not to the lane.
- The runtime layer map (`OfflineUnlockMod/homm3_runtime_assets/town_scene_refs/homm3_necropolis/layers/building_layer_map.json`)
  labels `nativeLevels` "clipped for cityFactory Castle-parity compositor". Its `buildingLayerIds` also map OE SIDs
  (`Mother_Nature`, `Spy_Network` -> `tbncext0`; `Mycelium_Roots` / `Lyceum` -> `tbncext1`) that `nativeLevels` omits.
- Castle has the same kind of gap: `tbcsdw_*_3`, `tbcsext0`-`tbcsext2`, `tbcshal4`, `tbcshrd3`, `tbcstext5`. So does
  Rampart. Profile `STATES` may only list reachable layers, or the Unity `RenderStates` step fails with "prefab ... not in
  bundle".
- Widening `nativeLevels` is a runtime contract change and is out of scope for the scene lane (main, 2026-09-29).
- These levels do **not** cause the floating fragments top-left of Necropolis `cursor_right` / `sweep_high`. An id pass
  (`town_all/seamfix/piece_at.py`) shows those were `tbncspec`'s storm cloud; see "Painted plumes" below.

### Painted plumes: flat card and top fray (opt-in per layer)

Necropolis `tbncspec` (Cover of Darkness) carries a large storm cloud above its tower. That cloud was built as solid
relief, and under the pan poses it floated in cracked, side-lit islands. Two causes:
- `native_mask` dropped the dark smoke that lies within `BG_EQUAL` of the dark sky, even though the painting has no cloud
  there (`town_all/necropolis/tbncspec_bg_vs_sprite.png`);
- the depth model read the billowing cloud as rough relief.

Two geometry-only fixes (`stronghold_full3d_buildings`):
- `RELIEF_TUNE[lid]["flat"] = {"source": "defChanged", "closePx", "growPx"}` (`flat_region`). The region is:
  - the DEF's own changed pixels (`town_full3d_fx.changed_count`: the cloud is what moves), closed and grown inside the
    sprite alpha;
  - plus the alpha pixels `native_mask` dropped where they touch it, above its lowest changed row.

  The region joins the layer mask. It becomes a flat card at its own median depth, and the solid closure gives it no
  volume. It fails closed if the layer has no animated DEF, if the frame and mask sizes differ, or if the region has
  fewer than 200 px.
- `EDGE_FRAY_TOP = {lid: {minPx, maxPx, sigmaPx}}` (`edge_fray_top`). It removes triangles above a ragged line near
  `y = 0`, the top-edge mirror of `EDGE_FRAY` / `EDGE_FRAY_BOTTOM`.

Necropolis seam_v2 result:
- Settings: `closePx` 4 and `growPx` 3, giving 9053 px, 824 of them re-joined from the painting test. The card sits at
  250 m. Top fray is 2-16 px.
- Generated artifact plus Unity lab render only; not installed.
- Offline pan crops: `town_all/necropolis/crops_plume_seam_v1_vs_v2.png`.

## Texture sources (experiments, off by default)

Two environment overrides change only what the albedo bakes read; masks, depth and geometry always read the native art.
Both fail closed (missing file, wrong faction, canvas not covering the frame), and with neither set the stage is
byte-identical to solid_v3 (checked 2026-09-28 on solid_v3_1: every staged file except the lightning re-key's).
- `TOWN_FULL3D_TEXSRC=<dir>`: an upscaled painting and static plates from `town_full3d_texsrc.py build`
  (`--model esrgan-x4plus | esrgan-x4plus-anime | seedvr2`, `--mode unified | separate`). Read by the terrain rect,
  the sky and the building front albedo.
- `TOWN_FULL3D_EXTSRC=<dir>`: an integrated outpaint canvas (`town_full3d_extsrc.v1`: the rest camera's image plane in
  frame px, columns `canvasX`). It replaces the vanilla-texture synthesis outside the painted rect, de-lit like the
  rect. The periphery uses it where the rest ray lands on the canvas outside the frame, faded in over 60 px from the
  canvas border.

Measured on Stronghold (offline previews; seam step = colour step across the seam over the same at control lines):
v3 x=1440 2.005 / y=673 0.881; Real-ESRGAN x4plus unified 2.233 / 0.917; SeedVR2 3B unified 2.017 / 0.893. Both
upscalers sharpen painting and sprites together (Laplacian ratio sprite/painting 1.79 native, 2.19 ESRGAN, 2.27
SeedVR2) and neither closes the sprite-vs-painting gap or touches the extension seams, so neither was adopted.

## Proof tier

The candidate bundle and catalog are generated artifacts. The review sheets are offline (moderngl) renders from the
vanilla camera poses. There is no Unity editor render of the solid candidate, and it has not been installed or seen in
game.
