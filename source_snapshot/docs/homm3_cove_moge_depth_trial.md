# Cove: layered MoGe-2 depth projection trial (2026-10-16)

The user asked for this test after the cv5_a in-game check: MoGe-2 depth used with the kk layer method, and no meshes. Each layer's depth is matched to the 3D points the layers behind it already placed. The result is shown as a pure depth projection.

Scripts are in `V:/olden_port_work/kokon/cove_trial/moge/`:
- `moge_run.py`: runs MoGe-2 (`Ruicheng/moge-2-vitl-normal`, at the painting's known FoV) on each kk_v4 plate. Weights and source are in `V:/olden_port_work/models/`.
- `align.py`: matches the layers to each other.
- `splat.py`: renders the projection. Each 2x plate pixel becomes one screen-space point, sized to its rest footprint and grown on grazing surfaces using MoGe's normals.

Sheets: `artifacts/homm3_cove_full3d/candidates/moge_trial/`. The env is the empty town; buildings are not included. Nothing was baked or installed.

## Method
Layers go back to front: P3 base (everything peeled), then P2 adds the cliff, P1 adds the objects, and P0 (the painting) adds the near band.
- **Base.** The base is scaled onto the painting's water plane, with a scale that varies by row as `exp(a + b*row)`. MoGe's water is pitched against the plane by 0.42 log per 540 px; after the fit the residual is 3.9%.
- **Each nearer plate.** It is scaled to the depth already placed behind it, using pixels the two plates share in a 160 px ring outside its peel mask. The median log error there is 0.02-0.03.
- **'foot' variant.** Each object is also rescaled to the ground just below it. The ratios came out at 0.96-1.07, so MoGe already places objects on their ground.
- **Order clamp.** This moved 0.4% of cliff pixels, 2.6% of object pixels and 7% of near-band pixels.

## Findings
- **Layering works.** The painting alone leaves a hole behind every rock, plant and the cliff at every moved pose. The layered stack fills those holes from the clean plates, and shared regions agree to about 2-3%.
- **The cliff reads as a receding mountain.** Its foot meets the water plane (67-110 m against the plane's 71-110 m), but its top is at about 480 m, roughly 7 times as deep as its foot. That is beyond the game's 415 m Sky_Dome, so an in-game build would need depth compression or a dome change. The preview puts sky and far fill at 1800 m.
- **MoGe leaves the far mountain without depth.** MoGe gives no depth there (it treats it as infinitely far), so the preview places it on the far band.
- **Gaps that remain are rendering limits.** Dotted gaps on steep receding surfaces and the empty space past the painting's frame edge come from point projection, not from MoGe's depth.

## MoGe-3 A/B (2026-10-16)
**Why.** On the raw MoGe-2 output, before any alignment, the reed strips leaned back at 0.55-1.09 of the water plane's slope (0 = upright, 1 = lying flat). The user approved the newer model, so I ran `Ruicheng/moge-3-vitg` (5 GB, ViT-G).

**Install.** MoGe-3 runs as pure Triton, with no CUDA build. Installed: `triton-windows` 3.7.1, and FlexGEMM at MoGe's pinned commit `b2fadb29` (`pip install --no-deps --no-build-isolation`, source in `V:/olden_port_work/models/flexgemm_src`).

**Commands.**
- `python moge_run.py <fov> v3` writes `moge3_<P>.npz`.
- `MOGE_TAG=moge3 python align.py` aligns the layers.
- `MOGE_TAG=moge3 python splat.py foot` renders the projection.

**Results.**
- **Reeds stand more upright** (MoGe-2 → MoGe-3):

  | Region | MoGe-2 | MoGe-3 |
  |---|---|---|
  | Right shore | 0.61 | 0.49 |
  | Far right strip | 0.66 | 0.30 |
  | Small reeds | 0.87 | 0.50 |
  | Reed clump | 1.09 | 0.96 |

  The reed clump still lies flat. The statue and boulders were already upright and improve further.
- **The cliff top moves in** from about 479 m to about 295 m, inside the 415 m Sky_Dome. Its foot is unchanged at about 66 m, on the water plane.
- **Alignment.** Ring fit: median log error 0.018-0.039. The water-plane fit leaves 3.3% residual. The objects' order clamp (moving an object's depth so it stays in front of what's behind it) touches 0.2% of their pixels in the foot variant.

Sheets: `ab_moge2_vs_moge3.jpg`, `depth_moge2_vs_moge3.jpg`, `moge3_layered_splat.jpg`.

## Stretch heatmap, ellipse splats, reeds stood up (2026-10-16)
MoGe-3 is adopted. Scripts (copies in `artifacts/homm3_cove_full3d/candidates/moge_trial/`): `standup.py`, `surfel.py`, `flatness.py`. Preview only: nothing synthesized or installed.

**Reeds stood up** (`MOGE_TAG=moge3 python standup.py` writes `layers_moge3up.npz`).
- Method: vegetation pixels (hue 45-170°, sat > 0.22) inside object labels that are at least 20% vegetation. Each strand component is re-seated per column at the depth of its lowest pixel (its foot on the water); the foot depths are median-filtered over 9 columns.
- Scope: labels 10, 11, 12, 14, 15, 41, 42; 140k strand pixels.
- Flatness on strand pixels (0 = upright, 1 = lying flat):

  | Label | before | after |
  |---|---|---|
  | 10 right shore | 0.48 | 0.10 |
  | 11 | 0.54 | 0.0 |
  | 12 | 0.50 | 0.0 |
  | 14 | 0.83 | 0.0 |
  | 15 | 0.63 | 0.0 |
  | 42 | 1.69 | 0.0 |

- Visible check: strands now stand as vertical blades at the side and low poses (`reeds_standup_ab.jpg`).
- Correction to the A/B table above: label 22 (the "reed clump") is actually the standing stone in mid-water **plus its reflection**. Its 0.96 is mostly the reflection, which correctly lies on the water. The stone itself still needs its own split and re-seat. Label 8 is the far shoreline strip, not reeds.

**Ellipse (surfel) splats** (`MOGE_TAG=moge3up python surfel.py`).
- Each plate pixel becomes a disc lying in the surface. Its axes are the world step to the neighbouring pixels in the same layer's depth.
- At depth edges (step > 8× the frontal footprint) a disc falls back to facing the camera. That happens for 9-24% of pixels per layer.
- Compared with round (camera-facing) splats of the same footprint, the side poses fill solid foreground rocks, ferns and shore instead of a dotted scatter (`surfel_moge3up.jpg` vs `round_moge3up.jpg`).
- What remains:
  - moiré gaps on the grazing water, where painted ripples give the depth a per-pixel corrugation;
  - stretched smears where the near band runs out at the frame edge;
  - the top-down `orbit_high` view stays unusable either way.

**Texture-stretch heatmap.** Measured on the frontmost surfel per pixel, sky excluded. Stretch = the largest singular value of the screen Jacobian, in 1080p screen px per plate texel. The rest view shows 0.5. Results are in `stretch_moge3up.json`.
- **game_default:** median 0.59, 0% of texels above 1.
- **The three side poses** (catmullRom, loop_288, polygon): median 0.65; 26% above 1, 9% above 2, 0% above 4.
- **By layer**, worst over all poses, share above 2:

  | Layer | > 2 |
  |---|---|
  | base (water + far land) | 14.4% |
  | objects | 2.0% |
  | near | 0.1% |
  | cliff | 0.0% |

- Where it concentrates: the mid-distance water band and far shore seen from the side, where the view grazes the water.
- Reading: within the game poses, stretch peaks at about 2-4×, never severe. So the stretching the user sees is mostly on grazing water. Compensation should target the base water band first, for example by re-synthesizing water texture in world space rather than projecting it.

## Standing stone, water plane, grazing water (2026-10-17)
Input: `layers_moge3up.npz`. `fix_water.py` writes `layers_moge3w.npz`, then run `MOGE_TAG=moge3w MODES=surfel,detail python surfel.py`. Preview only: nothing synthesized or installed.

**Standing stone (label 22).**
- What the label holds: the stone, its reflection, and a water sliver beside the near mossy rock. So 0.96 was mostly reflection.
- Waterline: found by mirror NCC over the stone's columns, peak 0.46 at row 1160 (2x).
- Split:
  - the stone above the waterline (5,066 px) stands upright on the water plane at that row, at 75 m;
  - the reflection and the sliver (11,387 px) lie on the water.
- Flatness of the stone: 0.99 → 0.0.
- `mirror_scan.jpg` shows that no other object label carries its reflection.

**Water boulders 18-21 and 23.**
- They leaned at 0.38-0.75. Each now stands on the plane at its own waterline, with a rounded front: a hemisphere of its half-width (1.4-2.0 m).
- The long rock 16, and the 6/43/44 rocks, keep MoGe's shape.

**Water snapped to the plane.**
- Every base-layer water pixel, plus the clean plate under every peeled object, now sits exactly on the water plane (5.09 M px). The plane is offset by −2.1% log, MoGe's median on water.
- Why: MoGe follows the painted ripples, which corrugated the surface. It also reads the far water (rows 800-900, about 200 m) 20% too deep.

**The moiré was a renderer bug, not the depth.**
- The surfel edge test fell back to camera-facing discs wherever an in-surface step exceeded 8× the frontal footprint. On grazing water that happens past about 110 m (1/sin of the depression angle).
- Those vertical discs were the stripes.
- The fix is a ratio test: a pixel is a depth edge only if its two one-sided steps differ by more than 3×; at an edge it takes the shorter step. The 8× cap stays for non-water layers, so thin strands do not smear.
- Result: the water renders as a continuous surface at every game and orbit pose.
- What's left magenta is far-band disocclusion (around the far mountain and behind the cliff), not water.

**Stretch, re-measured with true in-surface axes.**
- Why re-measure: the old fallback discs under-reported stretch, so the 14.4% above is not comparable.
- **Game poses:**
  - water: 65% of pixels over 1 screen px per texel, 9.8% over 2, 0% over 4;
  - base layer overall: 7.5% over 2;
  - objects: 1.9% over 2;
  - near: 0.1% over 2;
  - cliff: 0% over 2;
  - per pose: 0-5% of texels over 2.
- **World-space water detail (`water_detail.py`):**
  - Method: the painting's near-right water, rectified onto the plane at 3.6 cm per texel, added in the band between what the screen resolves and the plate's own texel.
  - Measured effect: brings the water to 0% over 1 exemplar texel.
  - Visible effect: barely changes the image, even at gain 2.5. The painted near water is dark and low-contrast (high-pass std about 15% of its mean), and the visible stretched look is the low-frequency painted ripple bands, magnified.
- **Recommendation:** in game, leave water detail to the SSR water shader, which already has world-space ripple noise, the vanilla WaterNormal and reflections. Low-pass the projected tint where the plate stretches more than 1×, rather than transferring painting detail.

## cv6_a: game candidate synthesized from moge3w (2026-10-17, not installed)

Scripts: V:/olden_port_work/kokon/cove_trial/v5/moge_env.py and stage_v6.py; review copies are in artifacts/homm3_cove_full3d/candidates/cv6_review.

**Environment.** The moge3w layers are meshed as frame grids:
- cliff → plate P2, objects → P1, near → P0, land (base minus water) → P3.
- Water is not meshed. Mesh_Terrain is the floor plane and runs through the SSR water lane (ssr=3).
- Depth is scaled back by exp(+0.0214), so the water is exactly the floor.
- Depths past 300 m are compressed with tanh into FAR_M.
- Cells whose four corners differ in depth by 1.15× or more are cut.

**Buildings.** Buildings on the cliff or on objects are re-seated onto the MoGe surface depth just below their contact pixel. Paint order is reported, not enforced. Enforcing it would push the sorceress tower ×1.68, to 365 m behind its rock, because the painting draws the guild over the tower's base.

**Lane result.** catalog, SSR stage, bundle, render and validate all return rc 0. The contract is OK:
- streakMax 1.150, panVoid 0
- 249.9 MB bundle, sha 969ae1e7

**Compared with cv5_a:**
- The black MassifGraze slab is gone. The cliff reads as rock from every game pose.
- **Defect:** the mage guild (tbcvgmg1-4, re-seated at 337-355 m) disappears behind the MoGe cliff top in the catmullRom, loop and polygon poses.
- The far-pan orbits still show floor/near streaks.

## Shacks and waterfall at the wrong depth; cliff lean (2026-10-17, nothing installed past cv6_a)

**The in-game problem.** In cv6_a the stilt shacks (tbcvsay1/2) and the waterfall (tbcvnmp1/2) stood at the town hall's depth, about 55-75 m. They are cards, and a card takes its depth from where its lowest px touch the water. In the painting those px are the near water.

**What was checked.**
- **Water plane.** It is not mis-normalized. At the cliff foot, MoGe's raw water (before the snap) agrees with the floor plane within 1-11% in every column.
- **The cliff lean is MoGe's.** It lays the cliff back to about 15° overall between foot and top.
- **Normals check** (`moge/normals_check.py`).
  - MoGe's water normal, rotated onto the floor normal, is 1.8° off gravity.
  - Cliff median lean from vertical: 34° by the gravity-aligned normals, 37° by the depth.
  - The normals agree with the depth, so they offer no independent correction.
- **Rectified crop** (`moge/crop_run.py 0 0 1000 600`). A virtual pinhole is rotated about the camera centre to look at the cliff: an exact homography, a centred principal point and a 46° FoV. Depth and normals are mapped back to the frame (`crop_check.json`).
  - Normal lean comes out about 7° steeper: median 27° instead of 34°.
  - Behind the shacks (x 100-400) the foot-to-top depth recession drops from 2.7-3.8× to 2.1-2.5×.
  - The waterfall columns (x 500-700) are unchanged.
  - So the crop is model-backed evidence for a steeper cliff on the left only, and the change is modest.

**Candidates.** All are baked through the full lane; none is installed.

| Candidate | Change | Result |
|---|---|---|
| cv6_b | Cards draped on the moge surface behind them, plus fx re-projection | The shacks and waterfall reach the cliff. Validate fails: the stilt drape spans 143-169 m |
| cv6_c | Hand-tuned 0.2 cliff lean | Green smear where the foot jumps from 105 to 228 m. Validate fails |
| cv6_d | Contact anchoring: the cliff waterline is pinned to the plane per column (factor 0.90-1.06, median 1.004) and the cards are draped | Clean. Validate fails only on the sloped stilt and waterfall bottoms (span 143-162 m over a 41-44 m width; the cap is 3×) |

**SSR.** The cove SSR reach is raised (`_SsrSteps` 64, `_SsrGrow` 1.1). The fade now starts at about 4.6× eye depth instead of 1.25×, because the MoGe scene is 3-4× deeper.

## cv6_e (2026-10-17): crop cliff + draped cards, validate OK

- Cliff depth: rectified-crop MoGe-3 (`moge3crop_P2.npz`) merged per column (log scale on each column's bottom 40 rows, 121 px smoothing, feathered blend), then anchored to the water plane at the waterline (`CLIFF_MODE="anchor"`).
- Shacks (tbcvsay1/2) and waterfall (tbcvnmp1/2) are draped on the surface behind them. Pixels above the cliff silhouette are plumb-filled from below, so they no longer take ~400 m land depth.
- Streak rule: the face part (`Mesh_Body_{lid}`) is depth-compressed beyond its foot until span ≤ 0.85×3.0× width (compress say1 0.42, say2 0.29, nmp1 0.69, nmp2 1.0). The low/water-contact part is split into `Mesh_Body_{lid}_low`. Contract thresholds are unchanged.
- Validate: OK (streakMax 1.150, spanW<=2.25). Bundle 6b033c82, not installed.
- Result (ab_cv6a_cv6e.jpg): at the game poses the shacks and waterfall now sit on the cliff face rather than at the hall's depth. Trade-off: the compressed shack tops lean back less than the cliff. The orbit at -35° shows the shack windows foreshortened against the cliff.

## Rollout to the other factions (2026-10-17, approved for testing; nothing installed)

The user approved the cv6_e method for testing on the other factions and asked to batch installs. The tools are generic and live in `V:/olden_port_work/moge_rollout/tools`. Run them as `run_lane.sh <faction> <seed> <cand> [ssr]`, with `align.py` run first. Conflux is deferred because it uses the phase6 pipeline.

The final recipe, mg_f1, rests on these flags. Each was added for a specific failure in the first candidates:

- `align MR_BASE_LF=150` corrects the low-frequency depth of the seed ground. Without it, the 2-parameter row fit left factory seat ratios between 0.53 and 1.49, which sheared or buried buildings.
- `env_bake MR_YIELD=1` pushes the MoGe env behind seated buildings where they paint at rest, using a building z-buffer feathered by dilate 31 and σ10. Without it, buildings hid behind MoGe layers.
- `MR_SEAT_KEEP=0.8,1.25`: a contact ratio outside this band counts as a depth disagreement, so the seed depth is kept. This fixed the fortress mage guild, which had seated 0.70 on a canopy.
- `MR_SEAT_SNAP=0.02`: a ratio within ±2% of 1 is left at 1. This keeps residual pieces from separating at the seam.
- Seating uses only base and background surfaces, and a suffixed row (`_2`) takes its base row's ratio.
- `MR_DECAL=drape` (castle, rampart): sprite ground decals are re-draped on the new front env, clamped to the building's depth slab (p2–p98). Letting decals ride with the body re-created the decal depth streaks.
- `lit_normals`: where the painting is brighter than Hex/Lit can render, normals turn toward the sun. Without this, factory's de-lit cliffs clipped to black.

No contract threshold was changed.

### Stronghold hang after the mg_f1 install, fixed forward (2026-10-18)

After the batch install, opening Stronghold hung the game (Windows Application Hang 1002). The user's direction: no rollback, move forward only.

Two causes:

- **Wrong seeds.** Factory, rampart, tower, fortress and stronghold had been installed as `zs_*_bo`, the approved 2026-10-03 body-only cut, but mg_f1 was seeded from the bare `zs_*`. That brought back every Meshy residual bin (`*_rest`, `Mesh_BodyRest_*`, `Mesh_Body_resid_*`), which are dense.
- **Per-frame rebake.** `Homm3TownScene3dPick.ReposeOrThrow` rebakes *baked* pick holders on every reposition: new meshes plus MeshCollider cooking. `Homm3FactoryCityWorldVisuals` repositions on every sync. Stronghold's native buildings carry lossy scales (482, 0.03), so they take the baked path. With the residuals back, each sync took about 650 ms.

The data fix is `env_bake MR_BODY_ONLY=1`. It applies `town_bench/edits/<faction>/body-only.json` (its hide ops) to the seed rows and staged meshes before seating, so these 5 towns are rebuilt from what was actually installed. The plugin fix is proposed as its own task: rebake a pick holder only when its pose changes.

**Lesson:** before seeding, check that the seed matches the installed bundle sha.

## px recipe: clean periphery + house ramp cut (2026-10-18, candidates only, nothing installed)

The user saw heavy streaking in the installed mg_f1 towns. There are two causes:

1. The frame periphery outside the HoMM3 painting rect is a smear from the old extension lane. The rect is 2880x1346 at 2x, origin (0,0). That smear is baked into P0 and every plate.
2. Painted house clusters rubber-sheet over MoGe depth ramps.

The tools are in `V:/olden_port_work/moge_rollout/tools`. The driver is `px_town.sh`, its stages are `prep / out / apply / inp / strad / depth / lane / ab`, and the brief is `BRIEF_px.md`. The steps:

- **`periph.py`:** Kokon outpaints the periphery from the object-free plate (the plate behind the first objects layer), using a "no buildings" prompt. Outpainting from P0 invents new houses.
- **`periph_apply.py`, pass 1:** pastes the outpaint into the periphery of every plate, with a 48 px feather on the rect side. P0's objects are never faded. It clears the layer masks and water in the periphery.
- **`periph_boxes.py` and `periph_strad.py`:** Kokon inpaints boxes under the objects and near components that the seam cuts. Only P0 gets the new pixels. The objects and near masks grow over pixels that differ from the object-free canvas.
- **`moge_splice.py`:** keeps phase A's MoGe depth inside the rect, and uses the new MoGe only in the periphery, matched at the seam band.
  - Without it, MoGe re-reads the whole frame. Rampart's ridges and stronghold's massif receded inside the rect too: ridges shredded, and a fan streaked behind the banners.
  - Exception: factory got worse with the splice, because its phase-A depth was already poor (clamp 0.47). Factory therefore uses its pre-splice candidate.
- **`periph_apply.py --sky`:**
  - Periphery sky is MoGe NaN connected to the top edge, kept above the skyline row at the right seam. Inferno's black range had come back as NaN, which counted as sky.
  - Non-sky NaN pixels get the nearest finite depth.
  - Background layers grow into the periphery over steep pixels, judged by MoGe normals.
  - `MR_PERIPH_WATER=1` grows water (fortress SSR, bulwark river).
- **`env_bake MR_OBJ_CUT=1.03,8`:** snaps depth ramps to steps, then cuts on objects layers at min(1.03, EDGE_RATIO). Fortress skips it, because on tree canopies it tears pale contour lines.
- **`run_lane.sh MR_REVIEW_ONLY=1`:** stops after catalog/ssr. Bundle, the Unity render and validate run at install time, so each candidate's unity_project (1.3 GB) is freed after review.
- **Cove (separate v6 pipeline):** `CV_OBJ_CUT=1.03,8` in `cove_trial/v5/moge_env.py` builds cv6_f from kk_v4. It removes the reed and grass rubber-sheet streaks at the game poses. The bundle failed only on the RAM gate while other agents were running.

| town | candidate | notes |
|---|---|---|
| castle | px_c3 | pre-splice; minor straddler-footing chunks, right-horizon sky slivers |
| bulwark | px_b3 | river continues; periphery snow plainer |
| dungeon | px_d2 | periphery pool brighter teal than the painting |
| factory | px_f1 | pre-splice (splice regressed) |
| fortress | px_f2 | no OBJ_CUT; SSR water grown into periphery |
| inferno | px_i3 | sky cap fixes the right-edge staircase |
| necropolis | px_n2 | periphery mud plainer |
| rampart | px_r2 | splice fixes ridge shredding |
| stronghold | px_s2 | splice removes banner fan |
| tower | px_t1 | gain modest; tan smudge right of seam copied from source plate |
| cove | cv6_f | ramp cut on moge objects |

A/B sheets are at `V:/olden_port_work/moge_rollout/<fac>_px1/ab_mg_f1_<cand>.jpg`. Exceptions: bulwark's is in `bulwark_px2/`, and cove's is `cv6_review/zoom_cv6ef.jpg`.
