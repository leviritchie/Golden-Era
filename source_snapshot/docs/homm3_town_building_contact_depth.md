# Town building contact depth (contact_v1) and the building-depth gate

Status: **generated artifact / Unity-editor render evidence only.** No `*_dfix` candidate is installed, and none has
startup, runtime or in-game proof. The validator check is wired into the town-scene contract (build path). The
building rule is opt-in per candidate.

Scope: how the full-3D HoMM3 town scenes give each building sprite its depth. This covers both the depth-relief
(ray/solid) pieces and the Meshy T2 bodies. Also covered: the gate that refuses the "streak" failure, where a sprite's
own depth runs it hundreds of metres back along its pixel rays, and the measured negatives.

Parent lanes: `docs/homm3_stronghold_full_3d_town.md` (registration, terrain, buildings) and
`docs/homm3_town_depth_building_solids.md` (solid closure).

## The defect (phase-1 diagnosis, 2026-09-30)

The legacy rule depthed each building sprite from its own monocular crop (`<lid>_da_large.npy`). It was footed per
column on the terrain, and its upright depth was clamped to the terrain behind it.

On tall sprites the model reads the art as a receding surface. Examples:

- Cove's waterfall `tbcvnmp1`, at 70 -> 153 m from its p5 to p95 upright depth;
- the stilt houses and their mirrored ladders;
- Fortress `tbfrdw_3`, with a span/width of 117 over 292 m.

The clamp then pins most of the sprite to the backdrop. In the sweep poses the body fans out along its pixel rays
into the long radial streaks. Three causes were separated:

1. **The sprite's depth is unanchored.** There is no single contact, so the receding read survives.
2. **Ground parts are depthed as upright.** These are reflections, decks and stair landings that lie on the floor.
3. **The background is pushed back behind ledges** (a calibration effect of the terrain, not of the building). The
   terrain behind Cove's waterfall reads at a median of 369 m, with 56% at the far cap.

## The rule (contact_v1, `stronghold_full3d_buildings.py`)

Each sprite gets one robust contact per layer.

- **Ground split.** `ground_split` marks as ground every floor-polygon px whose depth agrees with the floor plane in
  value (`GROUND_LOG_TOL`) and in vertical slope (`GROUND_SLOPE_MIN`), and that is connected upward from the sprite's
  bottom (`GROUND_GAP_PX`). An upright island lying wholly in the floor polygon and wholly below the main part's base
  is a reflection, so it is demoted to ground. Ground px take the floor-plane depth.
- **Contact.**
  - The contact row is the `CONTACT_Q` (0.75) quantile of the upright part's per-column lowest rows.
  - `inv_c` is the median inverse depth over `CONTACT_BAND_PX` rows above the contact.
  - `z_c` is the median calibrated terrain over `CONTACT_UNDER_PX` rows under the contact columns.
  - **Ledge rule:** when that terrain is more than `CONTACT_LEDGE_RATIO` (1.3) x deeper than the sprite's own base,
    the base depth is used (`contactSource: rawLedge`, Cove `tbcvnix2`: 381 m -> 233 m). This is the building-side
    guard against cause 3.
- **Affine in disparity, anchored at the contact.** `z = 1 / (1/z_c + sigma (inv - inv_c))`. The thickness prior
  `contact_sigma` picks the largest sigma in [0, 1] that keeps the upright p2-p98 depth extent within
  `CONTACT_THICK_K` (0.8) x its width at the contact and in front of the far cap.
  - **Width** is the p2-p98 extent of the upright px columns (px-weighted), which is the gate's own measure. With the
    min-max extent, a flagpole or eave doubled it: rampart `tbrmdw_1_2` read 11.8 m against a measured 6.5 m.
  - **Tails are clipped.** Upright inverse depth is clipped to the p2-p98 window before the map. Otherwise the 2-4% of
    px beyond the window stay free to streak: `tbrmdw_1_2`'s low side wall ran from a 90 m contact back to 126 m and
    measured 3.5x its width, and castle `tbcsdw_0` / `tbcsdw_0_2` BodyRest measured 3.6x / 4.0x.
- **No per-px terrain clamp on upright px.** Only the far cap applies. Ground px are still clamped to just in front of
  the terrain (`0.997 x zt`). The legacy clamp pinned upright px to the terrain behind them one by one, which is what
  re-made the streak under contact_v1: castle `tbcsdw_0` spanned 49.6 m against a 12.9 m prior. `restClampShare` now
  reports the share of upright px the terrain would have covered, as a diagnostic.
- **Rest pose stays pixel-exact.** Every vertex stays on its own pixel ray; only its distance changes.
- **Meshy T2 bodies share the contact.**
  - The Meshy pieces are scaled about the camera so that the base of the Meshy body sits at `z_c`. The base is its
    lowest 2% of world height, projected at rest and passed as `layer_depth(..., contact_px=)`.
  - Scaling about the camera leaves the rest projection unchanged.
  - The seed's residual pieces (`Mesh_BodyRest_*`, `*_rest`, `Mesh_Body_resid_*`) are re-depthed per vertex on their
    own rays from the same contact_v1 field. Where a residual triangle's depth spread exceeds the cut ratio, the
    triangle is sunk.
- **Rest occlusion in HoMM3 draw order (`order_pass`).**
  - Where the HoMM3 art draws a sprite over the terrain, or over another opaque sprite, its 3D layer must be the
    nearest surface there.
  - Layers are only ever pulled nearer (scaled about the camera), in one global pass in ascending HoMM3 z.
  - The pass fails closed when a layer would need less than `ORDER_MIN_SCALE` (0.3), or when it stays behind something
    on more than `ORDER_RESIDUAL_MAX` (2%) of its own top px.
  - Per-layer `orderScale` and `restOrder` are written to the stage report. The residual is measured after the pulls
    are written, from re-rendered staged bins (`order_residual`), not predicted from the scales.
  - **Ground rest (`ground_rest`).** A pull scales about the camera, so it lifts the layer's ground part by
    (1 - scale) x the camera height. After the pulls, a pulled ray/solid piece's floor-lying vertices (within
    `ORDER_GROUND_H_M`, 0.5 m, of the floor before the pull) go back to their unpulled depth, capped just in front of
    the rendered terrain. Three conditions apply:
    - The vertex was lifted past `UPRIGHT_H_M` (2 m), so it would stand up as an upright slab.
    - Its rest px lies outside every other layer's HoMM3 sprite, so no building can occlude it or be occluded by it.
    - A triangle that joins a returned vertex to a pulled one keeps the pull, on its own copies of its vertices.
    Tower `tbtwdw_0_2` (0.64x by `tbtwblak`) is the case: its deck rose 7 m, and its BodyRest measured 21.1 m deep over
    4.8 m wide (4.38x) and failed the gate.

Workflow (opt-in, per candidate):

```
TOWN_FULL3D_FACTION=<t> TOWN_FULL3D_CANDIDATE=<c>_dfix python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py candidate-init --faction <t> --seed-from <c>
# copy the seed's work/background_depth.json, work/props/placement.json, bundle/terrain_streak.npz (LDI seeds)
# pin: <cand>/work/building_depth.json = {"mode": "contact_v1", "seed": "<c>"}
python tools/homm3_town_scene_meshes/town_full3d_building_redepth.py apply   # restores the seed's buildings first (idempotent)
TOWN_T2_PROPS_GROUP=<A|B> python tools/homm3_town_scene_meshes/town_t2_props.py stage && ... check   # apply rewrites the catalog: props after it; Cove is group B
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py bundle
python tools/validate_town_scene3d_contract.py --catalog <cand>/bundle/catalog.json
```

`town_full3d_building_depth.py audit --out <cand>/bundle` measures any candidate against the gate, including one
built before the gate existed.

## The gate (`buildingDepth`, `town_building_depth.v1`)

A candidate that pins contact_v1 ships a `buildingDepth` catalog block and `bundle/building_depth.npz` (sha256 in the
block). `tools/validate_town_scene3d_contract.py` (`check_building_depth`) re-measures it.

The measurement covers every upright vertex, meaning one more than `UPRIGHT_H_M` (2 m) above the fitted floor, of
every non-Fx building piece. The threshold was 1 m and was raised because painted ground stands up to 1.0-1.3 m above
the fitted plane (Cove `tbcvhal3_rest` lay on that ground and measured 3.04x as an "upright" slab):

- span = p98 - p2 of forward depth;
- width = the piece's azimuth extent x its median depth.

It fails when:

- a ray/solid bin has span/width > 3 **and** span > 20 m (the streak);
- a layer has `reliefWindowShare` > 0.8 and still ships ray/solid bins (the clamp ate the sprite);
- the declared numbers differ from the re-measured ones;
- a layer's piece is unmeasured;
- the npz sha differs.

Meshy bins are exempt from the span rule: they are modelled bodies, not sprite rays. The thresholds are pinned in the
validator, so a catalog cannot loosen them. Installed catalogs, which have no block, are unaffected. The rule is
unit-tested by `tools/homm3_town_scene_meshes/test_town_building_contact_depth.py`, which also checks that the module
and the validator measure identically.

### Ground on relief terrain (`terrainSample`, 2026-10-01)

The floor plane is analytic (the camera's painted floor), so on a terrain with relief, ground lying on a hill above
the plane measured as upright. Tower `rx_cond_dalarge_dfix` failed on exactly that: 36 vertices of
`tbtwdw_0_2/Mesh_BodyRest_tbtwdw_0_2`, at its foot behind `tbtwblak`'s roof, sit on the rendered da_large terrain
(z / terrain front 0.998, about 95 m deep) 2.1-3.5 m above the plane. They carried the bin to 36.9 m over 4.6 m
(8.00). Without them it spans 17.3 m. Raising `ORDER_GROUND_H_M` did not help (8.47 / 8.55 / 8.55 at 1.0 / 1.5 /
2.0 m).

The build now samples the candidate's own staged terrain pieces (`Mesh_Terrain*`, `Mesh_Back_Terrain*` of the
environment prefab, the meshes the bundle ships) into a 0.5 m grid in the floor plane over the buildings' footprint:

- each cell holds the highest *walkable* terrain, meaning triangles within 60 deg of the floor (depth-step walls are
  not ground);
- far stretched triangles are rasterised by barycentric samples at half a cell;
- the grid ships in `building_depth.npz` (`terrain_grid`, `terrain_origin`, `terrain_cell`, `terrain_e1/e2`,
  `terrain_sha`).

A vertex is upright when it is more than 2 m above the floor plane **and not within 2 m of the terrain in its cell**.
So:

- above max(floor plane, terrain) by more than 2 m is upright, as approved;
- a vertex buried more than 2 m under the terrain also stays upright.

That second band was added after the first measure, plain max(plane, terrain), cleared Cove `bgd_v1` `tbcvthgd`'s
whole body (13110 -> 2 upright vertices). There the painting's own building had left a bump in the terrain, and its
walls are not ground. With the band, every pre-fix Cove streak is kept.

**Provenance.** The block's `terrainSample` records the pieces, a sha256 over their names and bytes, and `stageDir`
(repo-relative). The validator:

- recomputes the sha from the stage, and refuses a changed stage (stale sample), a missing stage, or an npz sha that
  differs;
- refuses a block without the npz arrays, or the reverse.

A candidate shipping `terrainSample` must therefore keep its staged Assets. Blocks without it (all four earlier
`*_dfix` bundles) are measured against the floor plane alone. That is the stricter measure: it flags a superset.

Tests (23 OK): synthetic hill ground passes, a streak standing above relief fails, walls buried in a terrain bump fail,
empty cells equal the plane, and a stale/missing/mismatched sample is refused. Real bins are cut from the audits into
`tools/homm3_town_scene_meshes/testdata/building_depth_terrain_cases.npz`:

| bin | expected | result |
|---|---|---|
| Cove `pb_v1` waterfall `tbcvnmp1` | fail | fails |
| Cove `pb_v1` stilt house `tbcvsay1` | fail | fails |
| Cove `bgd_v1` waterfall `tbcvnmp1` | fail | fails |
| Cove `bgd_v1` stilt house `tbcvsay2` | fail | fails |
| tower `rx_cond_dalarge_dfix` `tbtwdw_0_2` | pass | passes |

Every case also checks its plane-only verdict.

Audits rerun with the rule, as plane -> terrain on the same npz:

| candidate | streak bins | worst non-Meshy span/width | bins moved | moved most |
|---|---|---|---|---|
| Cove `pb_dfix` | 0 -> 0 | 1.66 -> 1.66 | 28/74 | `tbcvthgd_rest` 0.81 -> 1.47 |
| castle `rx_ldi_zone_old_dfix` | 0 -> 0 | 2.59 -> 2.18 | 55/90 | `tbcsblak` 2.59 -> 0.85, `tbcsmag3` 2.37 -> 0.70 |
| tower `rx_cond_oldlow_mono_env_dfix` | 0 -> 0 | 3.21 -> 3.21 | 37/90 | `tbtwdw_1_2` 2.18 -> 1.43 |
| tower `rx_cond_dalarge_dfix` | 1 -> 0 | 8.00 -> 3.76 | 38/90 | `tbtwdw_0_2` 8.00 -> 3.76 (36.9 -> 17.3 m) |
| rampart `rx_layer_card_dfix` | not rerun | - | - | its staged Assets were pruned; the shipped block stays plane-only |
| Cove `pb_v1` (pre-fix) | 13 -> 13 | 15.71 -> 21.06 | 42/74 | `tbcvthgd_rest` 12.63 -> 21.06 |
| Cove `bgd_v1` (pre-fix) | 12 -> 12 | 15.72 -> 15.76 | 56/74 | `tbcvsor2_rest` 3.97 -> 5.83 |
| rampart `rx_layer_card` (seed) | 2 -> 2 | 4.18 -> 4.18 | 45/82 | - |
| castle `rx_ldi_zone_old` (seed) | 9 -> 8 | 7.50 -> 7.76 | 71/90 | `tbcsdw_1_2` 3.12 -> 2.22 (52 m, leaves the set) |
| tower `rx_cond_oldlow_mono_env` (seed) | 9 -> 8 | 42.74 -> 8.53 | 50/90 | `tbtwdw_3_2` (62 -> 21 upright vertices) leaves the set |

The audits are in scratch `V:/olden_port_work/depth_fix/audit/terrain_*`, and the plane-only copies are in
`audit_planeonly_20261001`.

Legacy candidates, measured with `audit` at the original 1 m upright height (failures, worst span/width). At the
final 2 m the streak bins are: cove 13 (34 failures), fortress 7, rampart 2, castle 9, tower 9.

| candidate | failures | clamp layers | streak bins | worst span/width |
|---|---|---|---|---|
| cove pb_v1 | 32 | 21 | 11 (waterfall `nmp1`/`nmp2`, stilt `say1`/`say2`, BodyRest) | 15.9 |
| fortress pb_v1 | 29 | - | 6 (`tbfrdw_3` 117.3 over 292 m) | 117.3 |
| rampart rx_layer_card | 20 | 19 | 1 (`tbrmdw_4` BodyRest) | 4.29 |
| castle rx_ldi_zone_old | 25 | 16 | 9 (BodyRest) | 7.27 |
| tower rx_cond_oldlow_mono_env | 25 | 16 | 9 (BodyRest) | 42.7 |

Built `*_dfix` candidates (2026-10-01, final rule). Each passes `town_full3d_building_redepth.py apply`, which includes
the rest-order residual and the see-through gate, then `town_t2_props.py stage` + `check`, the `audit`, and
`tools/validate_town_scene3d_contract.py --catalog <cand>/bundle/catalog.json` (OK, `bundle=absent`):

| candidate (seed) | gate failures before (1 m table) -> after | worst span/width after | see-through px (gate baseline) | strongest order pulls |
|---|---|---|---|---|
| rampart `rx_layer_card_dfix` | 20 -> 0 | 2.92 | 2403 (seam_v1, no worse) | none below 0.87 |
| castle `rx_ldi_zone_old_dfix` | 25 -> 0 | 2.59 | 851 (fix_v1, no worse) | `tbcssilo` 0.52, `tbcmark` 0.60, `tbcsblak` 0.65 |
| tower `rx_cond_oldlow_mono_env_dfix` | 25 -> 0 | 3.21 (span under 20 m) | 0 (no baseline row) | `tbtwdw_0_2` 0.64, `tbtwdw_3_2` 0.64 |
| cove `pb_dfix` | 32 -> 0 | 1.66 | 1617 (cv_v6, no worse) | `tbcvcas3` 0.41, `tbcvgmg4` 0.49, `tbcvtave` 0.56 |

Fortress was measured (29 failures, `tbfrdw_3` 117.3) but no candidate was built for it in this lane.

The props check passes for rampart (23 instances), castle (6) and tower (39). On Cove (props group B, 28 instances)
it flags props 12 and 24, which were already floating in `pb_v1`, and prop 4 (sweep_left 0.892), which stood on a
building streak that is gone. This is reported rather than patched.


## Depth source: da_large, anchored to the shipped terrain

Building crops always use `<lid>_da_large.npy`. The phase-1 calibration (floor median |log error| / vertical-face
nearer share at 0.9) favours da_large over img2img in every town measured:

| town | da_large | img2img |
|---|---|---|
| rampart | 0.022 / 0.009 | 0.032 / 0.054 |
| tower | 0.055 / 0.31 | 0.133 / 0.70 |
| castle | 0.009 | 0.049 |

The contact comes from each candidate's own shipped terrain, rendered and compared against the contact reference
(median |log| 0.0015-0.006, p90 0.013-0.08 for cove, rampart, castle and tower). This includes the img2img terrains
of rampart `rx_layer_card` and tower `rx_cond_oldlow_mono_env`, so the buildings stand on the terrain the player sees.
Re-seeding those two terrains on da_large is a separate decision. It is not part of this lane.

## Cause 3: the anchored background (measured, not built)

The Cove waterfall `tbcvnmp1`:

- legacy upright depth 70.7 / 133.6 / 152.9 m (p5 / p50 / p95);
- contact_v1 188 / 198 / 201 m, with its contact at 186.6 m (floor plane 185.6 m).

The terrain behind it reads at a median of 369 m, leaving a 170 m gap to the cliff. Recalibrating the whole
background does not close that gap:

| recalibration | cliff | gap |
|---|---|---|
| none | 369 m | 170 m |
| floor-affine | 280 m | 83 m |
| floor plus vertical-face anchors | 287 m | 90 m |

**So the waterfall's cliff does need a local background anchor.** That means pulling the terrain behind a footed
building to the building's contact. It would be a separate opt-in lane. It is not implemented here. The building
itself now stands at its pool (the contact) and no longer streaks, but the cliff face it pours from is still 83-170 m
behind it at the sweep extremes.

## Negatives (measured, kept out)

- **Meshy sprite-contact anchoring.** Scaling the Meshy body so its own rest depth over the sprite's contact band lands
  on `z_c` sounds more consistent, but on Cove it needed more and larger order pulls:

  | layer | sprite-contact anchoring | body-base rule (shipped) |
  |---|---|---|
  | hal3 | 0.43, behind the terrain | not pulled |
  | tave | 0.45 | 0.56 |
  | hall | 0.65 | not pulled |
  | pir2 | 0.62 | 0.74 |

  The cause is that the Cove fits carry pseudo-ground and reflections over that band, nearer than the body.

- **Order pulls on genuine overlaps.**
  - Cove `tbcvcas3` is pulled to 0.41 by `tbcvdock`, and `tbcvgmg4` to 0.49 by `tbcvsor2`. The HoMM3 art overlaps them
    where their contacts are 100+ m apart. Keeping the rest occlusion costs them their contact depth.
  - `ORDER_MIN_SCALE` was lowered from 0.5 to 0.3 for this. A layer needing less still fails.
  - A pulled layer's ground part floats above the floor by the pull.
- **Prop 4 on Cove.** It stood on a building streak that no longer exists; its sweep_left overhang is 0.892.
- **Ground-split speckle limit.** A one-row x1.3 depth speckle inside a ground run is absorbed. A larger one cuts the
  run upward, which is a documented limit with its own unit test.
- **Per-state order settling** missed cross-state conflicts (`tbcvtave` behind `tbcvhal3`), so the pass is global.
- **Floor-keep for every ground vertex of a pulled layer.** Leaving all floor-lying vertices on the floor plane hid
  them behind terrain that stands above the plane, and behind the layers the pull was clearing. Residuals: rampart
  `tbrmdw_4_2` 3.7%, castle `tbcsdock` 46%. `ground_rest` keeps only the vertices outside every other sprite, capped in
  front of the rendered terrain.
- **Ground pulled onto the rendered terrain.** Moving pulled ground to just in front of the terrain left it behind the
  layers the pull was clearing (rampart `tbrmdw_1_2` behind `tbrmhrd1`). It also tore pulled bodies off their own
  ground: Cove `tbcvgmg4_rest` went 201 m deep at 0.49x. `ground_rest` never moves a vertex deeper than its unpulled
  depth.
- **Ground rest variants.**
  - Returning every lifted floor vertex, and sinking a mixed triangle to its deepest vertex (ray_redepth's cut), put
    Cove `tbcvsmrk` behind `tbcvmark` on 3.6% of its top px (residual gate 2%).
  - Leaving mixed triangles stretched between floor and body turned their backs at pan poses (`tbcvsmrk` Cull Back
    see-through 9 -> 12 px at pan_cursor_right, over the cv_v6 baseline).
  - Returning ground under small pulls only split the piece: rampart `tbrmdw_0_2` at 0.97x returned 6065 vertices, and
    see-through rose 2396 -> 3799 px over the sweeps and orbits. That is why the 2 m lift condition exists.
- **Width as the min-max column extent.** A flagpole or eave doubled it (see the rule). The p2-p98 extent is used.

Framing fix found on the way: `town_full3d_framing.py` subsampled the building boxes (`[::7]`) when it aimed the
default pose and measured it. Rampart `tbrmspec` then sat 0.0004 below the HUD edge and failed "out of the visible
region at rest". Every point is now used.

## Posed effect cards ride with the body (fixed 2026-10-01)

User report (2026-10-01, in game): the upgraded Workshop's pendulum (tower `tbtwdw_0_2`, `Fx_Swing_0` /
`Fx_SwingFront_0`) does not swing. The swing card loaded (`applied layer 'tbtwdw_0_2' ... painted=2`), but it was
hidden. A swing / spin / keyed card is a *posed* bin: a holder at `pos` / `rot`, with holder-local vertices. The
redepth scaled only the vertex bytes, in both the Meshy pass (`meshyScale`) and `order_pass`. So the card shrank about
its own pivot and stayed at its seed depth. Meanwhile the body moved to 0.744 x 0.6375 = 0.474x. On the installed
`rx_cond_oldlow_mono_env_dfix`, the body's residual and Meshy pieces sat about 18 units in front of the bob, on 89% and
31% of its rays. The seed render shows the bob and the dfix render does not.

`scale_bin_about_camera` now scales `pos` with the vertices, so the projection is unchanged. A solid layer's posed
card takes one ratio at its pivot. `posed_ride_check` fails the apply unless each posed bin's `pos` ratio equals its
own Meshy body's vertex ratio. Test: `test_town_building_contact_depth.PosedBinScaleTest`.

Other installed dfix towns were checked. The castle and rampart posed bins are `Fx_Water` sheets at `pos` 0, which
this bug cannot move. Factory and Stronghold have posed cards (wheels, track, windmill sails, basins) but no dfix.

Separate gap, not fixed here: HoMM3's base Workshop `TBTWDW_0.def` and `TBTWUP_0.def` both carry the 20-frame pendulum.
The Tower `layers/anims` set holds only the third-upgrade DEFs (`TBTWUP2_*`), so base `tbtwdw_0` has no effect at all.

## Near layers (Castle, 2026-10-01)

User report (2026-10-01, in game): near-camera Castle buildings and props have bad depth. The installed candidate is
`rx_ldi_zone_old_dfix`. The cause is `order_pass`. It pulled the near layers far toward the camera because of tiny
tails (the 1% quantile) of environment occluders. A pull lifts a layer by (1 - s) x camH, and Castle camH is about
20.95 m. So the near buildings hovered and tore away from their residuals at the pans.

| layer | installed scale | cap driver |
|---|---|---|
| `tbcsblak` | 0.652 | `Mesh_Houses`: the sprite redraws the roof of the painted cottage in front of it (median dE 3.8, legitimate occlusion) plus a terrain foot band |
| `tbcmark` | 0.604 | a modelled house spilling over the left canopy tip (491 px, 1.3%) plus terrain at the stall bases |
| `tbcssilo` | 0.518 | chained from `tbcmark` |
| `tbcstvrn` | 0.783 | chained from `tbcshal3` |

**Rule (opt-in per candidate).** The pin `work/building_depth.json` takes an optional `"order"` block,
`{"q": <terrain cap quantile, in (0, ORDER_RESIDUAL_MAX]>, "artSameDE": <CIELAB>}`. Unknown keys are refused, and the
defaults reproduce the installed rule.

- `artSameDE`: a sprite px within that dE of the background painting under it restates the painting. There the HoMM3
  art states no order against the terrain or environment, so the px neither caps a pull nor counts as residual.
- `order_residual` still gates every layer at 2%.

Test: `test_town_building_contact_depth.OrderOptions`.

**Castle `rx_ldi_zone_old_nfix`** uses `{"q": 0.015, "artSameDE": 6.0}`.

| layer | scale before | scale after |
|---|---|---|
| `tbcmark` | 0.604 | 0.902 |
| `tbcsblak` | 0.652 | 0.890 |
| `tbcssilo` | 0.518 | 0.774 |
| `tbcsdw_0_2` | 0.741 | 0.982 |
| `tbcsdw_0` | 0.820 | 1.0 |

- `tbcshal3` (0.790) and `tbcstvrn` (0.789) are almost unchanged. They are layer-vs-layer caps (`tbcsdw_5_2`, then
  `tbcshal3`), which this rule does not touch.
- No layer fails, and see-through is no worse than the baseline.

**Certificate** (`town_full3d_zero_streak.py`, 43 reachable poses). Before is the installed rule reproduced in the same
candidate. Both columns come from the committed tools; neither uses the uncommitted building-seams work.

| measure | before | after |
|---|---|---|
| max visible behind-streak | 3461 px | 1707 px |
| `Mesh_Back_Terrain`, sum over poses | 28856 | 13941 |
| `tbcmark/Mesh_BodyRest`, sum over poses | 16 | 0 |

| pose | before | after |
|---|---|---|
| sweep_left | 1782 | 1707 |
| sweep_right | 3461 | 1592 |
| sweep_high | 1483 | 502 |
| sweep_fwd | 497 | 94 |
| default, cursor | 0 | 0 |

Unity editor pairs (installed `_dfix` renders against `_nfix`) show the change directly. At sweep_right the blacksmith
loses its smeared ghost, and the market stalls sit on the ground; at sweep_left the floating, torn market stall is gone.
Validator (committed contract, bundle built): `OK ... bundle=present ... bldDepth=contact_v1:90 spanW<=2.18`.

**Still failing the zero bar.** The certificate does not pass: 38 of 43 poses still have a visible component.

- `Mesh_Back_Terrain`: back terrain revealed behind the painted cottages, at most 1508 px at a pose.
- `tbcsdw_6_2/Mesh_Body`: the Meshy front windows of the floating cloud gate (7436, unchanged).
- `Mesh_Houses`: 1358.

None of these is a near-camera layer.

**Ground hole at the blacksmith's foot (fixed).** At the forward poses (`sweep_fwd`, `loop_048`-`loop_084`), a ground
hole at the foot of `tbcsblak` grew from at most 165 px to at most 476 px.

- The cause is the terrain, not the building. The LDI back layer under the terrain lip there continues below the
  painted floor plane: about 65.5 m against 59.7 m at rest row 680.
- With the environment alone the hole is 550 px. The deep pull (0.652) used to hide it.
- It is closed at the terrain's own stage by the hole-driven floor clamp of the back layer
  (`town_full3d_ldi_floor.py`; see `docs/homm3_town_layered_depth_backfill.md`). Ground holes are now at most 158 px,
  and nothing else changes.

**Installed (2026-10-01).** `rx_ldi_zone_old_nfix` is installed into Golden Era: the order rule plus the floor
clamp, bundled from the committed tools.

- Bundle sha256 `c54ffb90ab50…`.
- Rollback: `artifacts/town_scene_rollback/castle_20261001T190119Z`.
- Validator: `OK ... bldDepth=contact_v1:90 ... terrain=087cbdcbf005 props=6/3types`.
- Proof tier: deployed payload proven by sha readback. The order rule's effect is shown in Unity editor renders; the
  floor clamp's effect only in offline renders. Runtime and in-game visibility are unproven.

**Combined with the cloth wave: blocked by the seams gate (2026-10-01).** The installed `rx_ldi_zone_old_nfix` is a
pre-seams build: no `buildingDepth.seams` block. It was bundled from tools frozen before `eb72eb3e2d`. With
`eb72eb3e2d`, every new `buildingDepth` build carries the seams gate, so any rebuild of the Castle catalog, the cloth
pass included, is measured by it.

- `rx_ldi_zone_old_nfix2` is nfix rebuilt under HEAD: residual `body_v1` (the default) and `ground_ramp_v1`.
- `rx_ldi_zone_old_nfix2_cloth` adds `town_full3d_cloth.py apply` on top: 24 banners, bundle `f605c971...`.
- Editor renders and the review are done for `rx_ldi_zone_old_nfix2_cloth`.
- Both candidates fail the seams gate on 13 Castle layers, with split shares from 0.025 (`tbcsmag4`) to 0.152
  (`tbcshal3`, p99 16 px). The `contact_v1` residual fails it on even more layers. Making Castle pass the gate is
  the seams lane's open work. Neither candidate is installed.
- Certificate, nfix2 against the installed nfix:
  - max visible behind: 1701 against 1707;
  - ground holes: at most 138 against 158;
  - 15 poses are better.
  - `tbcsdw_5_2/Mesh_BodyRest` adds at most 49 px at `loop_252`-`loop_300`.
- `town_full3d_building_seams.rest_seams` skips cloth pieces. Before, it raised `KeyError: 'cloth'`, so no catalog
  with cloth could be built under HEAD.
- The deployed Golden Era plugin (13:24) has no cloth runtime: `clothLook` is absent from the DLL. The wave needs a
  plugin deploy as well as the bundle.

**Tower: layer-on-layer chains need a non-whole-layer pull (design, not built).** The installed Tower,
`rx_cond_oldlow_mono_env_dfix`, has its strongest pulls between layers, which the `artSameDE` rule does not touch:

| layer | scale | driver |
|---|---|---|
| `tbtwdw_0_2` | 0.637 | `tbtwblak` |
| `tbtwdw_3_2` | 0.644 | |
| `tbtwext2` | 0.737 | |
| `tbtwsilo` | 0.795 | `tbtwmark` |
| `tbtwspec` | 0.807 | |
| `tbtwdw_5_2` | 0.817 | |

A whole-layer pull to s lifts the entire layer, its ground contact included, by (1 - s) x camH. For `tbtwdw_0_2` that
is about 7.2 m, implying camH of about 19.8 m. The order the art states only has to hold on the overlap with the
occluder. So the proposal (`order_local_v1`) changes per-vertex depth along each vertex's own rest ray, which leaves
the rest frame identical by construction:

1. **Constraint set.**
   - For each ordered pair (A over B) that `order_pass` finds, take O_AB: the px of A's rest footprint where A must
     win against B. These are B-nearer px, minus `art_same` px.
   - Every A vertex whose rest px is in O_AB gets a target depth t_i = min zB(px_i) / ORDER_MARGIN. Use the same
     quantile guard as today, so a 1% tail does not set the target.
2. **Anchored, smooth solve.**
   - Each vertex gets a factor k_i in (0, 1], with new depth z_i' = k_i z_i.
   - Minimise Σ (1 - k_i)^2 + λ Σ_edges (k_i - k_j)^2, subject to k_i z_i <= t_i on the constraint set.
   - k_i = 1 holds on A's contact band: vertices within the upright test's `h_min` of the terrain under them
     (`buildingDepth.terrainSample`). So the ground contact keeps contact depth, and only the part that overlaps B
     comes forward.
   - The solve is projected Jacobi, monotone like `relax_to_cap`, over the bin's own edges. Residual bins follow the
     body as they do today.
3. **Gates (fail-closed, no silent whole-layer fallback).**
   - Lift: the largest height change of any vertex, (1 - k_i) z_i projected on the floor normal, stays at or under
     `UPRIGHT_H_M`.
   - Shear: the pose anisotropy of A's triangles at the reachable poses stays at or under `ANISO_CUT` (the LDI's
     smear test), so the lean does not become a streak.
   - `order_residual` stays at or under 2%, as now.
   - A layer that cannot meet all three is reported as unresolved and keeps the contact depth. It is never scaled
     whole.
4. **Choose the mover.** When the occluder B is the one with slack, push B's occluded px back instead. That is the
   same solve with t_i as a lower bound on B. Take whichever side has the smaller lift. For example, `tbtwblak` may
   be the cheaper side for `tbtwdw_0_2`.
5. **Proof.** Run `town_full3d_zero_streak` over the 43 poses, before and after, for Tower:
   - visible behind-streak per piece;
   - ground and enclosed holes;
   - per-layer maximum lift against the whole-layer lift in the table above.

A cap on the whole-layer pull at `UPRIGHT_H_M` alone was considered and rejected. Without the pull, A no longer wins
the overlap, so `order_residual` exceeds the 2% gate. That only moves the failure.

**Enclosed holes.** The enclosed-hole growth (to about 9400 px at sweep_high) is sky enclosed under the cloud gate
once `tbcsdw_0_2` stops being pulled. It is not a see-through.

**Preview caveat.** `stronghold_full3d_scene.preview` draws every layer of every state at once. So base and upgraded
dwellings (`tbcsdw_0` over `tbcsdw_0_2`) and the mage guild tiers overlap after a re-scale, and look like a regression.
Judge previews filtered to one state.

## Proof

| claim | tier |
|---|---|
| contact/thickness rule, gate measure identical in module and validator | unit test (16 tests) |
| four `*_dfix` candidates, 0 gate failures, rest-order residual <= 2%, see-through no worse than baseline | generated artifact |
| catalog contract on each `*_dfix` with the bundle built | build target (Unity editor batch bundle; `validate_town_scene3d_contract.py --catalog`: OK, `bundle=present`) |
| before/after in sweep, default and rest poses, final rule | Unity editor renders (rampart, tower, Cove; castle has no "before" render: its seed render waited on the running port game and was stopped) |
| installed, startup, runtime, in-game | **none**; nothing is installed |

Bundle sha256 (2026-10-01):

- rampart `91947b090cf47227626c9b2e614c38fa2c04e993cb15f6b24eb00abde626ca65`
- castle `2debf98a64eb34feba0b324f666d9a9b19d15af64139fa84dc66f7a1d727671f`
- tower `ef2f629bc290dfb4bd3532c96cf8d2cf3152cca8f7faffdd26e6e0fb6e0a6e61`
- Cove `bb44dfd5f615ef18ab7975d6c2cbf3d5c4c57a0c275c362ee3d737286abe2b65`
- tower `rx_cond_dalarge_dfix` (da_large + monotone/envelope terrain, the only bundle with `terrainSample`):
  `93bbfc09a3a518496736bcad56e9ca28dddcc18203c6c91a2f036ab9fb5f22cb`.
  - Validator: `OK ... bldDepth=contact_v1:90 spanW<=3.76 terrain=3a082eca0a0e props=39/3types`.
  - Unity bundles of an unchanged `build_spec.json` were not byte-identical: three builds gave three shas.
  - Pairs against `rx_cond_oldlow_mono_env_dfix` are in `cmp/final_tower_dalarge_<pose>.png`.
  - Offline streak px (`town_t2_streak_map.py`, sweep left / right / high, almost all on Meshy bodies):
    - this candidate: 1466 / 2915 / 1585;
    - the img2img seed `rx_cond_oldlow_mono_env`, pre-dfix: 836 / 1788 / 996 (the dfix's staged Assets are pruned);
    - plain da_large `props_v1`: 14335 / 20920 / 10720.
  - In the editor pairs the da_large terrain reads more smeared on the right-hand mountain at the sweeps, and the
    buildings match. Whether to prefer it is open.
- Pruned after validation (the bundles and catalogs stay, and validate plane-only): the staged Assets of castle,
  tower `rx_cond_oldlow_mono_env_dfix` and Cove `pb_dfix`, to keep V: above the Unity guard.

The editor pairs are in scratch `V:/olden_port_work/depth_fix/cmp/final_<town>_<pose>.png`. The plan view is
`V:/olden_port_work/depth_diag/plan_cove_pb_v1_vs_pb_dfix.png`.

- **Cove** is where the rule pays off. The stilt houses stand instead of streaking back as slabs, and the waterfall
  stands at its pool on the cliff line. The cliff face behind it is still the far backdrop (cause 3).
- Measured on an earlier version of the rule (not re-measured on the final one):
  - Cove building streak px fell 72038 / 113228 / 92110 -> 4897 / 22998 / 11657 (sweep_left / sweep_right /
    sweep_high).
  - Total streak px fell 157743 -> 75183, 163727 -> 59528 and 135381 -> 38368.
  - Rest art lost on the pulled layers fell: `tbcvgmg4` 0.196 -> 0.028, `tbcvsmrk` 0.136 -> 0.001, `tbcvtave` 0.303
    -> 0.030.
- **Rampart and tower** change little to the eye, because their legacy failures were mostly clamp-eaten layers rather
  than visible streaks. Some Meshy BodyRest residues read more fragmented at the sweep extremes, such as tower's centre
  houses and rampart's left house. That is the cost of re-depthing a residue on its own rays.

Installing any `*_dfix` candidate is a separate decision.
