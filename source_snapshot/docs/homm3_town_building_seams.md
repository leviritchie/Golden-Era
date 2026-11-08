# Town buildings: one depth model per building, and the seam gate

Status: generated artifact validated (offline restage + raster + projection). No bundle, no install, no runtime proof.
Companion to `docs/homm3_town_building_contact_depth.md` (contact_v1, the `buildingDepth` gate, the order pass).

## The defect (2026-10-01, in game, installed Rampart `rx_layer_card_dfix`)

Distant buildings broke into separate layers when the camera turned. A Meshy T2 layer has two depth models side by side:

- The Meshy body: its own geometry, scaled about the camera so its base sits on the contact.
- The residual: `Mesh_Body_resid_<l>`, `Mesh_BodyRest_<l>` and `*_rest`, which are the sprite pixels the body leaves uncovered at rest. Each vertex is re-depthed from the sprite's own contact_v1 disparity field.

The two models agree only at the contact. Elsewhere the residual sits in front of or behind the body next to it, so a pan opens the seam between them and the terrain shows through. That is cause 2 of the four hypotheses. The others, measured on Rampart:

- **Art painted into the background:** refuted. The splits are within one layer rendered on its own.
- **Several HoMM3 layers make up one building:** refuted for Rampart. Cross-layer seams are not where the splits are.
- **CUT_RATIO sinking:** contributes. Sinking residual triangles over a contact_v1 step creates separate pieces.

## The rule: `body_v1` (`tools/homm3_town_scene_meshes/town_full3d_building_seams.py`)

The residual takes the body's depth:

- **Under the body:** the body's rest front is rendered per native sprite pixel. The residual sits `SEAM_BEHIND` (1.001×) behind it.
- **Everywhere else:** the residual takes the screened harmonic fill (decay `SEAM_DECAY_DEFAULT` = 24 native px) of the correction `log(body / contact_v1)`.
- **Boundaries of the fill:** the fill is Dirichlet on the body and on ground pixels more than `SEAM_FLOOR_PX` (16) from it. So the field is continuous across the seam and returns to contact_v1's floor away from the building.
- **No sinking:** residual triangles are never sunk (`RESIDUAL_CUT_RATIO = None`).
- **Rest pose:** every vertex stays on its own pixel ray, so the rest pose is unchanged.

**Pin.** The rule is set per candidate in `work/building_depth.json` as `"residual": "body_v1" | "contact_v1"`. The default is `body_v1`. The stage report records the rule it applied under `contactDepth.residualDepth.rule`. The gate block's `residualRule` is read from the stage report, not from the pin. A mix of rules within one build fails closed. The old `SEAM_RULE` environment switch is retired and fails closed.

**Ground after a pull: `ground_ramp_v1`** (`town_full3d_building_redepth.ground_rest`). A pulled layer's floor-lying vertices go back to the floor outside other sprites. That return now fades in over `GROUND_RAMP_PX` (64 frame px) of rest screen distance from the vertices that keep the pull. Before, mixed triangles kept the pull on their own torn vertex copies. Those copies came apart from the floor at the sweeps:

- Rampart: tbrmhal3 had 117 split seam pixels and tbrmext0 had 69.
- Fortress: tbfrmage_3, tbfrmark, tbfrsilo and tbfrtvrn opened by p99 70-120 px.

## The gate: `seams_v2` (`buildingDepth.seams`, `building_depth.npz` `seam_*`)

The checks live in `tools/validate_town_scene3d_contract.py` (`building_seam_*`).

**Rest seams.** In one layer's own rest render, a rest seam is any 4-adjacent pixel pair that:

- is drawn by two different pieces (a piece is a bin × mesh-connected component), and
- has at least one residual ("ray") side.

**Split.** Both sides' 3D points are projected at the five vanilla proof poses (`cursor_left/right` and `sweep_left/right/high`). A pair is split at a pose when both of these hold:

- its screen distance grows by more than 2 px, and
- the gap is see-through. The layer rendered alone at that pose (`seam_fill`) draws nothing at the pair's midpoint, or draws only a surface more than 1.01× deeper than both sides.

**Failure.** A layer fails when more than 1% of its residual seam pairs split **and** more than 20 pairs split.

**What the validator recomputes and refuses.** It recomputes the projection itself. It also refuses:

- a block without its arrays, or arrays without their block;
- a changed pose set;
- a loosened threshold;
- a declared count that differs from the re-measured one.

**Exempt pairs.** Meshy-Meshy pairs are not recorded: they are the body's own occlusion steps on closed geometry. Solid-solid pairs are reported but not gated.

**Atomic write.** `building_depth.npz` is written whole to a temporary file and then renamed before its sha256 is taken. A reader cannot hash a half-written file.

**Off-frame correction (`seams_v2`, 2026-10-01).** A pair counts at a proof pose only where its midpoint is on that
pose's screen (in front of the camera and inside the 1920x1080 frame). It still counts at every pose where it is on
screen. `seams_v1` counted off-screen poses as see-through: nothing is rasterised there, so `seam_fill` is inf without
the layer being open. Example: Rampart `tbrmdw_0` sits at the frame's left edge (sprite x 0); 86-91% of its "split"
pairs at `sweep_right` / `cursor_right` were off screen (pose x -52..-108), and its count drops from 111 to 22 / 1951
under the correction. A residual pair on screen at no proof pose cannot be measured: it is counted apart per layer as
`residualUnmeasured` (declared in the block, re-measured by the validator), never passed silently, and a layer whose
unmeasured share is above 25% is flagged in the validator summary (`UNMEASURED-SEAMS:<layer>=u/n`). This is a
measurement correction; the thresholds are unchanged. `seams_v1` blocks (built before it) are re-measured by their own
rule. Tests: `test_town_building_seams.py` `SeamOffFrame` (off-frame, on-screen, never-on-screen, `seams_v1`).

Re-measured with the correction (`V:/olden_port_work/bgroup/seams_v2_audit.json`), every catalog the old rule decided:
no layer's split count rose, no layer went from pass to fail, and no layer has an unmeasured pair (0 of 5524-26211
residual pairs per town).

| catalog | failing layers, seams_v1 | failing layers, seams_v2 |
|---|---|---|
| Cove `ssr_dfix` (installed) | none | none |
| Castle `rx_ldi_zone_old_nfix2` / `_cloth` | 13 | 12 (tbcstvrn passes) |
| Castle `rx_ldi_zone_old_nfix3` / `_cloth`, `zs_v4` | none | none |
| Fortress `ssr_dfix` | tbfrdw_2_2 | none |
| Fortress `ssr_dfix2` | tbfrdw_2_2, tbfrdw_5_2, tbfrmage_3 | none |
| Rampart `rx_layer_card_bgrp` (body_v2) | tbrmdw_0 111 / 1951 | tbrmdw_0 22 / 1951 |

Castle `rx_mv3_inpaint` and `zs_v5` had no `building_depth.npz` on disk at the audit (other lanes), so they were not
re-measured.

Builds made before the seam gate have no seams block, so they are not gated. Every new `buildingDepth` build carries the block.

Unit test: `tools/homm3_town_scene_meshes/test_town_building_seams.py`. Since 2026-10-01 the seam build renders on the GPU by default: one `town_gpu_kernels.Raster` context serves all layers. It produces byte-identical `seam_*` arrays and runs about 3x faster (12.4 s to 4.4 s on Castle zs_v5). `device="cpu"` (or `TOWN_FULL3D_DEVICE=cpu`) selects the reference. Parity is checked in `test_town_gpu_kernels.py`; details are in [town_gpu_kernels.md](town_gpu_kernels.md).

## Measurements (2026-10-01)

### Rampart `rx_layer_card_bgrp` (seeded from `rx_layer_card`)

Gate measure, split pairs by pose, all layers. The cursor poses split nothing under either rule.

| pose | contact_v1 | body_v1 |
|---|---|---|
| sweep_left | 10960 | 655 |
| sweep_right | 11325 | 973 |
| sweep_high | 10613 | 539 |
| distinct pairs | 21240 / 61324 (25 layers fail) | 1718 / 60344 (14 layers fail) |

Per layer: `V:/olden_port_work/bgroup/rampart_seam_per_pose.json`.

The worst remaining layers:

| layer | split pairs | p99 opening |
|---|---|---|
| tbrmdw_0 | 343 / 2084 | 21 px |
| tbrmhal2 | 273 | — |
| tbrmhall | 214 | — |
| tbrmmag3 | 110 | — |
| tbrmmag4 | 107 | — |

**Streak (texture anisotropy, `town_t2_streak_map.py`), state full, sweep_left / right / high:**

| measure | before | after |
|---|---|---|
| total streak px | 1472 / 1683 / 877 | 1458 / 2801 / 1033 |
| enclosed-empty px | 91 / 179 / 83 | 2 / 42 / 5 |

The rule trades see-through gaps for stretched texture where a residual crosses a body occlusion step. A depth gradient of about 1% per native px is already about 85° grazing. At such a step, a residual on its own pixel rays can only tear (a gap) or stretch (a streak). No geometry-only rule removes both without inpainting.

**Not passing.** The Rampart pilot does not pass `seams_v1`.

### Fortress `ssr_dfix` (pin `pb_v1`)

| | contact_v1 + ramp | body_v1 + ramp |
|---|---|---|
| split pairs | 1685 / 24618 | 208 / 21451 |
| failing layers | 20 | 3 |

The three body_v1 failures:

- **Seam split, tbfrdw_2_2:** 75 / 2325, all ray-ray. They sit at the frame's left edge, 23-30 m from the camera. The two sides differ by 1.7% in depth, and the field is steep beside a body step.
- **Upright span, tbfrblak:** 8.38. This was already failing at 5.51 before the change.
- **Upright span, tbfrdw_0_2:** 3.37. This was already failing at 3.26 before the change.

### Cove `ssr_dfix`

Both rules pass: contact_v1 59 / 5524 split pairs, body_v1 78 / 5538.

### Castle `rx_ldi_zone_old_nfix2` lineage: `body_v2` (opt-in, a trade)

`body_v1` fails Castle on 13 layers (1094 / 25018 split pairs). The residual ends about 2% off the body px next to it,
and at about 21 m a 2% depth step opens about 2.4 px at the sweeps. The step has three sources: the field's native grid
(1.8 frame px per native px), the residual's 2-frame-px vertex spacing, and the body's steep depth at its silhouettes.

`body_v2` (`BODY_RULE_PARAMS`, pinned with `"residual": "body_v2"`) adds three refinements on top of `body_v1`:
- `sub` 4: the field is solved on a grid 4x finer than the native px.
- `snapPx` 4, `snapSup` 4: residual vertices within 4 frame px of the body blend in log depth onto the body's nearest
  rest px. The body is sampled at 4x the frame, and the weight is `clip((4 - d) / 3, 0, 1)`.
- `subdiv` 2: the residual mesh is midpoint-subdivided twice (uniform, crack-free).

The stage report records these as `residualDepth.sub / snapPx / snapSup / subdiv`. `ground_rest` becomes
`ground_ramp_v2` under `body_v2`: the Meshy body's vertices also keep the pull, so the ramp fades in from the body's
foot. This one was needed for tbcshal3 at 0.89x.

Measured on scratch copies of nfix2. The certificate column is `town_full3d_zero_streak.py --loop 0` (7 poses);
"residual" is its `bldg_residual` visible behind-streak px.

| variant | split pairs | failing layers | residual visible-behind px | max visible-behind px |
|---|---|---|---|---|
| body_v1 (nfix2) | 1094 | 13 | 68 | 1701 |
| body_v2 | 87 | 0 | 748 | 2037 |
| body_v2 without subdivision | 230 | 7 | 50 | 1718 |
| body_v2 without snap | 379 | 9 | 299 | 1825 |
| body_v2 with sub 1 | 88 | 0 | 755 | 2049 |
| body_v2, 1 subdivision level | 133 | 1 | 676 | - |

So `body_v2` passes `seams_v1`, but it raises the zero-streak certificate's maximum. On the 19-pose run (`cloth check`)
the base `bldg_residual` sum goes from 185 to 2545. The subdivided border follows the body's steep silhouette depth,
and small residual faces such as the tbcsdw_5_2 banner rectangle fold, which the certificate then counts as revealed
streak. The rule is kept opt-in, and `body_v1` stays the default. Neither rule meets both gates on Castle.

Measured negatives on the same copies:
- **Snap onto the front-most body px (minimum filter):** 1427 split pairs.
- **Snap 8 px:** streak 994. **Snap 2 px:** 3 failing layers.
- **Snap sampled at 1x:** no gain.
- **Subdivision only within 3 px of the silhouette (red-green, crack-free):** streak 719. Outside the body only: 620,
  with 3 failing layers. So the streak comes from the border band itself.
- **A harmonic band (6 px) between the body front and the field in place of the snap:** 271 / 5 failing layers, and
  481 / 13 without subdivision.
- **A 3 px skirt under the body from the residual's boundary edges:** it showed at rest (rest seam pairs 2736 -> 4173),
  with 261 split pairs and streak 983.

## Fortress span: an order-pass finding (open)

Both span failures come from `order_pass`, not from the residual rule.

**tbfrblak is pulled 0.61× by tbfrcstl_3.**

- 26% of blak's own HoMM3-top pixels lie over the castle sprite.
- On every one of those pixels, the castle's Meshy model is 30-40% nearer than blak's contact (castle front 70-94 m, blak contact 112 m).
- So the painting's order contradicts the two contacts. This is not a raster tail.

The pull makes the whole layer hover. Its residual ground then has to be one of three things, and each fails a gate:

| What the residual ground does | Gate it fails |
|---|---|
| Stays pulled (an elevated copy of the floor, 52-59 m) | Upright span |
| Returns to the 110 m floor with a ramp | The ramp skirt counts as upright span |
| Returns to the floor with a tear | Seam split |

No ground-only rule can satisfy all three. The fix belongs in how the order contradiction is resolved, meaning which layer yields. The Castle near-camera lane works on the same pass.

**tbfrdw_0_2 is pulled 0.69× by tbfrcstl_3, on a tail.**

- Only 0.94% of its top pixels lie behind the castle.
- The layer cap takes `ORDER_Q` as a quantile over the *overlap* pixels.
- The terrain cap takes it over all of the layer's top pixels, which is what the `ORDER_Q` comment says it is.

Measured with the layer caps computed as a share of the layer's top pixels as well:

- Every Fortress pull gets milder. dw_0_2 0.69 → 0.86, dw_6_2 0.78 → 0.93, tvrn 0.80 → 0.99, mark 0.76 → 0.83.
- The dw_0_2 span failure is gone. blak only moves to 8.10.
- Two small seam failures appear: tbfrdw_5_2 25 / 733 and tbfrmage_3 24 / 651.

It is opt-in per pin (`"order": {"layerShare": true}`, `town_full3d_building_redepth.py` `order_options`; reported as
`restOrder.layerShare`), not the default: it changes every town's order pass, and it was not validated on the other
towns. Under `seams_v2` the two new seam failures are off-frame artefacts (tbfrdw_5_2 19 / 733, tbfrmage_3 1 / 651,
tbfrdw_2_2 8 / 2325, all pass), so Fortress `ssr_dfix2` (body_v1 + layerShare) fails only the tbfrblak span, 8.10. That
span is the order contradiction above and belongs to the residual depth / ordering work (R1-R3).

## Negatives (measured, kept out)

- **Blurring or median-filtering the body correction:** more seam splits.
- **A per-piece rigid correction:** more splits and more streak.
- **The floor as a boundary right at the body's foot:** tbrmext0_rest streak went from 154 to 1877 px at sweep_right.
- **Sinking residual triangles over a contact_v1 step:** ray-ray splits went from 85 to 188 at sweep_left.
- **Tearing pulled ground onto vertex copies:** the gaps above.
- **Freeing pulled ground wherever lower layers sit behind the floor:** tbfrblak 8.38 → 5.08, but tbfrdw_0_2 3.37 → 3.89.
- **`body_v3`, opening the body front's pits (a residual over a hole in the Meshy front, with nothing behind, takes the
  back surface):** 17+ layers fail on Rampart bgrp, tbrmdw_0 included. Reverted.
- **`body_v2` on Fortress:** 9 failing seam layers against body_v1's 1.

### Rampart tbrmdw_0 (open, not tuned)

Under `seams_v2` tbrmdw_0 still fails at 22 / 1951 (1.1% > 1%, p99 2.5 px). It is a near-camera porch / pergola at the
frame's left edge, 39-43 m: the Meshy front has a back wall at 43 m and front posts at 39 m, with open gaps between the
posts. The residual fills those gaps on its own pixel rays, so at the sweeps the residual-to-post seams open: the
tear-or-stretch case at a depth step described above. It is reported, not tuned to the threshold.

### Board-pose certificate (`town_full3d_zero_streak.py --loop 0`, 7 poses, 2026-10-01)

Neither candidate passes the second gate, so neither is installed.

| candidate | max visible-behind px (pose) | by class (sum over poses) |
|---|---|---|
| Rampart `rx_layer_card_bgrp` (body_v2) | 573 (sweep_right) | bldg_front 829, bldg_residual 779, periphery 31 |
| Fortress `ssr_dfix2` (body_v1 + layerShare) | 58937 (sweep_left) | terrain_sheet 128988, bldg_residual 4289, bldg_front 392, periphery 39 |

Fortress's certificate is dominated by its terrain sheet: the town has not been through a zero-streak terrain recipe,
and the building lanes cannot move that number.

**Zero-streak recipe (`town_full3d_recipe.py`, castle_zs_v4 shape: pieces Mesh_Terrain, fromPreLdi false, repair
drop / card / flap), 2026-10-01; recipes `recipes/rampart_zs_v1.json`, `recipes/fortress_zs_v1.json` (uncommitted,
candidates `zs_v1`):**

- Rampart (seed bgrp): the repair rounds converge (round 5: 0 failing faces in every state), then the final gate
  fails on periphery only (Mesh_Outer*: 7 of 19 poses, max 33 px at loop_288, sum 167 px). The likely cause is the
  content step's sky-side backstop prune after the last repair round, which no repair rule covers (not verified;
  recipe-tool work).
- Fortress (seed ssr_dfix2, props re-placed): the flap rule fails closed before any round: "the residual's uv is not
  an affine map of rest px (294 texels off)".

Neither reaches the seams re-check, and neither is installed.

## Rebuild recipe (per town)

1. Run `stronghold_full3d_scene.py candidate-init --seed-from <installed>`.
2. Pin `work/building_depth.json` with `mode: contact_v1`, `seed`, and optionally `residual`.
3. Run `town_full3d_building_redepth.py apply`.
4. Run `town_t2_props.py check` (and `stage` when the placement changes), using the town's `TOWN_T2_PROPS_GROUP`.
   Redepth (like every step that rewrites a catalog) calls `write_catalog(sc, carry="previous")`, which carries every
   block it does not produce (the props block included) from the candidate's own catalog
   (`town_full3d_fork.catalog_carry`), so props need not be re-staged after a redepth.
5. Build the bundle.
6. Run `validate_town_scene3d_contract.py --catalog <cand>/bundle/catalog.json`.
7. Install with `install_town_scene3d.py`. That command is the user's call.
