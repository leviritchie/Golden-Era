# Town full-3D: layered-depth back-fill of the terrain (LDI)

**Proof tier:** generated artifact / offline render. The candidate `fa_v5_ldi` was built through the standard stage/bundle
path (Unity via the lane's guards) and passes `validate_town_scene3d_contract.py` at phase 6b. It is **not installed**.
Unity editor render, runtime, and in-game appearance are unproven.

## Problem

The full-3D town terrain is a screen-space grid, projection-textured from the rest frame. Where a near ridge covers far
ground, the grid bridges the depth step with triangles that lie along the rest camera's rays. They are invisible at rest.
Once the camera translates (the vanilla sweep poses), they turn into rubber-sheet bands carrying the ridge's edge texels.
See the "Silhouette curtain streak" section of `docs/homm3_conflux_full_3d_town.md` for the Conflux phase-6b precedent.

## Method (`tools/homm3_town_scene_meshes/town_full3d_ldi.py`)

This is a 3D-photo-style layered depth image, run as a post-stage pass on a candidate's staged terrain bins. It is
faction-agnostic: its only precondition is that each piece's UV is an affine map of the rest frame, and it fails closed
otherwise.

1. **Cut.** A triangle is removed from the main surface in either of two cases:
   - its rest forward-depth ratio (max/min) exceeds 1.25;
   - it spans a depth step (ratio > 1.01) that a reachable proof pose smears past anisotropy 3.

   The second rule is needed because, on Factory, 20 500 of the streaking step triangles have ratios of only 1.01–1.25.
   A ratio-only cut, measured as try 1, barely helped. Main vertices, UVs and textures are untouched.
2. **Back layer (`Mesh_Back_<piece>`).**
   - **Band.** Triangles are taken within a band of the far-side silhouette. The band is at least 120 px wide, else 1.5×
     the widest gap a reachable pose opens across a cut, capped at 320 px (Factory: gap 151 px, band 227 px).
   - **Push back.** These triangles are copied and pushed back along their own rest rays onto a continuation of the far
     surface. That surface is inverse depth, pyramid push-pulled from the far-side pixels of the rest depth only.
   - **Cap.** A stepping continuation is relaxed (`relax_to_cap`: z_i ≥ z_j / cap over the layer's edges, far side fixed)
     so the layer stays one welded sheet under the cap. Try 6 flattened each over-cap tile into its own card; the cracks
     between those cards were 59% of the hole pixels, and relaxing cut the sweep_high holes from 30k to 14k px.
   - **At rest.** The layer is hidden except in the cut cells, which it draws in place: same rays, UV, normal and texel.
3. **Texture.**
   - The back layer samples its own albedo crop. Only texels hidden at rest by the remaining main surface are replaced.
     A 6-texel ring around every texel shown at rest stays verbatim.
   - The fill is `quilt_fill`: classical image quilting (Efros & Freeman), deterministic and seeded. It copies 24-texel
     exemplar tiles verbatim from far-side texels, matches overlaps by SSD, and applies a tone shift clamped to 24 levels.
   - No Meshy, no paid API and no ML model are involved. LaMa is not installed locally. An earlier push-pull + mirrored
     high-pass fill produced flat brown mush.
   - The main textures are never touched.
4. **Closure (`keep_holes`, v2).** Each reachable pose is id-rendered, comparing the original piece with
   main + back + backstop.
   - **Smear cuts.** A pose-smear cut seen through a reveal hole goes back into the main surface, and the pass re-runs.
     A stretched surface is better than an empty one. On Factory this took 2 rounds and kept 1 342 triangles; the holes
     were mostly the bottom rows of `Mesh_Terrain`, where nothing lies beyond the piece edge to continue.
   - **Ratio cuts** never go back (the validator's cap).
   - **Backstop (`Mesh_Back_<piece>_Far`).** The band is built once more at the farthest silhouette depth within it,
     behind both main and back. It is pruned (`prune_stop`) to the triangles that some reachable pose sees where the
     original piece was (Factory: 239 150 -> 8 906), so it does not float in front of the sky elsewhere. Its texture is
     fully synthesised from far-side texels.
   - **Why the extra layer.** It is a terrain-native continuation of the canyon in the same Hex/Lit terrain material
     path, rather than a new sky or backdrop dependency; the scene's sky dome stays behind it.
5. **Contract output.**
   - `bundle/terrain_streak.npz` stores `cut_tris` as the ratio cuts only, so the validator's negative check holds by
     construction. The smear cuts go in `smear_cut_tris`.
   - The stage report gets an `ldi` section.
   - `stronghold_full3d_scene.py catalog` then writes `phaseRevision` "6b" plus `terrainStreak`. It fails closed if the
     npz is missing or its sha differs.

Commands (the candidate must be a fresh seed; `apply` refuses a stage that already carries `Mesh_Back_*`):

    TOWN_FULL3D_CANDIDATE=fa_v5_ldi python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py --faction factory candidate-init --seed-from fa_v4
    TOWN_FULL3D_CANDIDATE=fa_v5_ldi python tools/homm3_town_scene_meshes/town_full3d_ldi.py --faction factory apply
    TOWN_FULL3D_CANDIDATE=fa_v5_ldi python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py --faction factory catalog
    TOWN_FULL3D_CANDIDATE=fa_v5_ldi python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py --faction factory bundle
    python tools/validate_town_scene3d_contract.py --catalog artifacts/homm3_factory_full3d/candidates/fa_v5_ldi/bundle/catalog.json
    python tools/homm3_town_scene_meshes/town_full3d_ldi_review.py --faction factory --before fa_v4 --after fa_v5_ldi --out <dir> [--summary <png>]

Tests: `python tools/homm3_town_scene_meshes/test_town_full3d_ldi.py`. These are synthetic step-grid checks of the cut,
the back layer's cap and rays, the hole-closure loop with the backstop, `relax_to_cap`, and the verbatim guarantee of
`quilt_fill`.

## Factory result (fa_v4 installed -> fa_v5_ldi v2, offline moderngl renders)

The review is written to `artifacts/homm3_factory_full3d/candidates/fa_v5_ldi/ldi_review/`. The single-image summary,
which includes the rest-diff crop row, is `artifacts/claude_takeover_20260927/review/factory_ldi_before_after_v2.png`.
The v1 sheet (`factory_ldi_before_after.png`) is superseded.

Bridging triangles (>1.25 / >1.5 / >2), fa_v4 -> v2:

| group | fa_v4 | v2 |
|---|---|---|
| terrain | 2814/1208/149 | 0/0/0 |
| buildings | 1853/75/0 | unchanged, out of scope this round |
| env | 32/9/0 | unchanged |

| pose | terrain streak | terrain rev+streak | empty px (clear colour): fa_v4 / v1 / v2 | sky holes: v1 -> v2 |
|---|---|---|---|---|
| sweep_left | 73 077 -> 39 229 | 38 693 -> 27 272 | 0 / 4 336 / **0** | 2 347 -> 230 |
| sweep_right | 133 893 -> 64 028 | 75 337 -> 46 453 | 0 / 8 351 / **0** | 10 095 -> 39 |
| sweep_high | 117 524 -> 51 032 | 65 656 -> 36 562 | 0 / 4 694 / **0** | 9 459 -> 405 |
| stress (not reachable) | 218 845 -> 156 955 | 98 335 -> **101 254 (worse)** | 0 / 7 797 / 666 | 9 156 -> 6 675 |

How the columns are measured:
- **Empty px** are pixels where nothing is drawn, which the preview shows as its magenta clear colour. v1's magenta
  blotches were exactly these: reveal holes at pose-smear cuts, mostly the bottom rows of `Mesh_Terrain`.
- **Sky holes** are pixels that show terrain in fa_v4 and sky in the after scene.
- The review tool now **fails (exit 2)** on any empty pixel at a reachable pose. The committed v1 tool, re-run into a
  scratch candidate and reproduced bit-exact (npz sha 01b89f71), fails this gate.

**Rest frame.** The mean absolute difference is 0.046 levels. 6 529 px differ by more than 2 levels and 2 391 px
(0.12%) by more than 8, with a maximum of 250. All of them are 1-px silhouette lines, shown in red in the summary's crop
row. By layer:

| before -> after | px > 8 levels |
|---|---|
| terrain -> terrain | 1 009 |
| terrain -> buildings | 679 |
| terrain -> env | 428 |
| buildings -> buildings | 240 |
| env -> env | 33 |

The removed curtains were edge-on slivers that painted the ridge's edge texel over whatever lay behind, so the frame now
shows that surface on the silhouette line instead.

## What is still imperfect (honest list)

- **Back-layer smear.** The continued surface is a smooth ramp and still stretches at the sweeps (back anisotropy p99
  about 190). Terrain streak is about halved, not gone.
- **Restored smear cuts.** The 1 342 kept triangles stretch as they did before.
- **Sky holes.** A few hundred px remain at the reachable sweeps (above).
- **Environment pixels revealed.** Env revealed+streak rises at sweep_right (0 -> 1 469) and sweep_high (92 -> 1 053):
  the outer pieces, which the curtains used to cover, are now revealed.
- **Revealed pixels increase** at every sweep. This is expected, because the back layers are new geometry.
- **The stress pose (unreachable) is not improved** and keeps 666 empty px.
- **The backstop's quilted texture** can read as a repeated strip where it shows.
- **Buildings are out of scope for this round.** The `tbfaholy` elevator tower's vertical rubber bands (1 755 of the
  1 853 building bridges) remain. A building LDI would need a per-layer uv->frame map, because building bins are not
  frame-affine textured, which this tool requires.
- **Unproven beyond offline renders.** No Unity editor render and no in-game check. The `Mesh_Back_*` pieces are
  expected to take the same Hex/Lit rebind as other `Mesh_` pieces, but that is unverified.

## Install (not done)

`artifacts/claude_takeover_20260927/install/install_town.sh factory artifacts/homm3_factory_full3d/candidates/fa_v5_ldi fa_v4 <msgfile>`.
It copies catalog, bundle, build report, `pan_coverage.npz` and `terrain_streak.npz`, validates the stage, refuses if
the game is running, backs up the installed Golden Era Factory scene, and copies into Golden Era and the tracked repo
mirror. The stage-copy and validate part was dry-run into `candidates/fa_v5_ldi/ldi/dry_install_stage/`: OK,
streakMax 1.250, streakNeg 2814 (v2 bundle sha c67dc9be).

## Cheap alternative tried: atmospheric haze masking (negative, 2026-09-29)

`tools/homm3_town_scene_meshes/town_full3d_haze_probe.py` renders fa_v4 at this review's rest / sweep_left /
sweep_right / sweep_high poses and applies a post-pass haze from per-pixel world distance and height (what a fog term
would see). Vanilla cityHuman2 uses linear fog (colour 0.580/0.773/0.767, 16.1-92.1 m); the lane ships `"fog": "off"`.
Summary: `artifacts/claude_takeover_20260927/review/factory_stretch_haze.png` (offline render only).

- **Any static fog changes the rest frame.** The vanilla-shaped fog changes 1.56 M px by more than 2 levels, and even a
  far-only fog behind every building changes 41 838 px. Only a fog whose density is ramped by the camera's offset from
  rest (zero at rest) keeps the rest frame bit-exact.
- **The smears sit at building depth.** Terrain streak px have a median distance of 147-170 at the sweeps. Buildings
  have a median of 111 and a p99 of 335. Far-only haze therefore removes about 3% of the streak. Enough haze to matter
  also hazes the town.
  - `ramped_mid`: streak roughly halved (73k/134k/118k -> 38k/76k/61k unmasked), with a mean haze of 0.26-0.35 on
    buildings. The smears stay legible, just paler and teal.
  - `ramped_mid_strong`: 4k-18k unmasked streak, with the town 62-78% fogged out.
  - Terrain-only haze leaves the buildings floating on sky-coloured cut-outs.
- **Untouched smears.** The nearest smears (the foreground sand) and the `tbfaholy` building band are not affected by
  any distance fog.
- **Verdict:** not a delivery. A fog that rolls in whenever the camera moves also reads as a lighting change.

## Occlusion-zone cut for the img2img background depth (`--cut zone`, opt-in, 2026-09-30)

**Proof tier:** generated artifact / offline render (plus Unity editor renders where noted). Nothing installed.

**Why.** Swapping the sharper img2img background depth (`depth/img2img_bg.npy`, `work/background_depth.json`) into a
town like-for-like multiplies the terrain curtains (Rampart sweep_left 2 035 -> 67 208 streak px, Castle 24 563 ->
70 131). Run on that depth, the default pass above only halves them (Rampart 29 720 / 5 462 / 3 813 at sweep_left /
right / high), because of how the new map's edges reach the grid:
- **Edges are ramps, not steps.** A real occlusion edge is sampled as a ramp a few cells wide. The per-triangle
  rule cuts scattered ramp cells and welds the back layer to the *middle* of the ramp (the far end of each cut
  triangle), so the continuation inherits the ramp and the curtain survives inside `Mesh_Back_Terrain` (Rampart:
  65 k of the back layer's 153 k triangles still smear past anisotropy 3 at sweep_left).
- **Grass micro-relief.** The meadow's micro-relief fires the smear rule everywhere (74 k cuts on Rampart), which
  swaps the whole plaza for a patchwork of main and back cells.
- **A near post at the painting's edge.** Rampart's painted-edge columns calibrate to a near post (31-52 m in front
  of 115-177 m meadow, frame x 1430-1490). Its internal steps put far-side vertices *on* the post, so the post's
  back copies were never pushed. This post is a depth-map / edge-ramp artefact, not a real object; the zone cut tears
  it like any other edge.

**Rule (`occlusion_zone_cut`).** All of it is computed on the piece's rest depth raster.
- **Zone.** A pixel is in a zone if it lies within `r` px of either:
  - a horizontal step: max/min over a 1 x (2r+1) window > `tau_h` (ground does not recede sideways);
  - a vertical step beyond the ground's own recession: max/min over (2r+1) x 1 > `tau_v` x the same ratio of the
    frame's row-median depth.
- **Seeds.** Only connected zones that hold a ratio cut or a default smear cut count.
- **Near / far.** Inside a zone, a vertex is *near* within `near_tol` of the windowed min depth, and *far* within
  `far_tol` of the windowed max (exclusive of near).
- **What is cut.** Every zone triangle that is not wholly near and not wholly far, plus the ratio cuts. Smear cuts
  outside every zone stay in the main surface.
- **Back layer.** Its weld is the far plateau inside zones and the old geometric split elsewhere. All other machinery
  (push-pull continuation, relax, quilt, keep_holes, backstop) is unchanged.
- **Defaults.** `ZONE_DEFAULTS` = r 24, tau_v 1.2, tau_h 1.15, near/far tol 1.06. With `--cut smear` (the default),
  the npz is byte-identical to before (Rampart seed, sha a65c6f55).

**Crop alignment (`--crop-align 64`, opt-in).** The back layer draws the cut cells at rest from its own albedo crop.
- **The fault.** An odd crop origin (Castle y0 = 213) shifts every mip block, which re-tints minified distant terrain
  at rest: 58 861 px changed by more than 8 levels at rest, 39 892 of them terrain->terrain.
- **The fix.** Aligning the crop to 64 texels gives 20 869 px, of which terrain->terrain is 1 993. Most of the rest
  is terrain->buildings: removed curtain slivers that used to paint over building edges.
- **Rampart.** Its crop origin was already (0, 0).

Commands:

    TOWN_FULL3D_CANDIDATE=<new> python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py --faction <f> candidate-init --seed-from bgd_v1
    TOWN_FULL3D_CANDIDATE=<new> python tools/homm3_town_scene_meshes/town_full3d_ldi.py --faction <f> apply --pieces Mesh_Terrain --cut zone --crop-align 64
    TOWN_FULL3D_CANDIDATE=<new> python tools/homm3_town_scene_meshes/town_t2_anim_pass.py catalog     # build spec + catalog from rows.json

Test: `test_zone_cut_takes_the_whole_ramp_and_continues_the_far_plateau` (a post with three-cell ramps: no ramp
vertex stays in a main triangle, and the ramp's back copies sit at the far plateau). The default rule leaves 142 ramp
triangles in the main surface on that grid.

**Results (generated artifact, 2026-09-30; streak px from `town_t2_streak_map.py`, total / `Mesh_Terrain`).**
Candidates are copies of each town's `bgd_v1` with only `Mesh_Terrain` re-layered. Every variant had 0 empty px at
every reachable pose (`town_full3d_ldi_review.py`). The see-through (cull) gate passed: no reachable pose is worse
than `bgd_v1`.

| Rampart | sweep_left | sweep_right | sweep_high | sky-hole px L/R/H | rest px > 8 |
|---|---|---|---|---|---|
| props_v1 (old depth) | 2 035 | | | | |
| bgd_v1 (img2img depth) | 67 208 / 65 193 | 14 906 / 13 024 | 16 064 / 13 963 | | |
| default LDI | 29 720 / 27 477 | 5 462 / 3 571 | 3 813 / 1 711 | 23 / 132 / 140 | 5 951 |
| zone r16, non-directional | 17 456 | 8 254 | 6 196 | 54 / 132 / 140 | 1 756 |
| + band-max back depth | 6 592 | 6 343 | 6 649 | 949 / 132 / 140 | 2 701 |
| zone r16, directional | 4 155 / 1 858 | 6 926 / 5 044 | 4 701 / 2 600 | 84 / 132 / 140 | 2 484 |
| + smear cuts outside zones | 13 120 | 4 200 | 3 155 | | 6 900 |
| **zone defaults (r24)** | **3 384 / 1 085** | **2 510 / 611** | **3 668 / 1 558** | 91 / 132 / 140 | 7 859 |

| Castle | sweep_left | sweep_right | sweep_high | sky-hole px L/R/H | rest px > 8 |
|---|---|---|---|---|---|
| props_v1 (old depth) | 24 563 | 37 189 | 17 449 | | |
| bgd_v1 (img2img depth) | 70 131 | 82 423 | 67 874 | | |
| default LDI | 15 378 | 24 809 | 12 519 | 477 / 6 / 2 | 47 569 |
| **zone defaults + crop-align 64** | **8 452 / 7 491** | **12 993 / 11 563** | **5 691 / 4 909** | 969 / 1 / 0 | 20 869 |

Negatives:
- **Band-max / max-depth back depth.** Both lose to push-pull. They push the back layer to fog depth, which shows
  as grey wrong-colour patches.
- **r32 zones.** These fail closed: the texture fill has no all-source window.
- **Smear cuts outside zones.** These bring the post curtain back.
- **Sky holes at the post's top.** Rampart's 132 / 140 sky-hole px at sweep_right / high are ratio cuts at the top
  of the edge post (x ~ 1465, y 39-108). Every variant has them.
- **Castle sky holes.** Castle's 969 at sweep_left lie on the upper-left hill skyline.
- **Review orbits.** These are not runtime poses (`orbit_cam`), so they sit outside the gates. In Unity, though,
  Rampart's zone candidate opens:
  - a void at `pan_orbit_y+0_p+14`: 9 120 magenta px against `bgd_v1`'s 389;
  - a sky window behind the rock outcrop at `pan_orbit_y+18_p+6`.

  Both sit where `bgd_v1` shows its post curtain. That curtain was covering a missing back surface.

By eye (Unity, Rampart):
- The default view matches `bgd_v1`.
- At the sweeps, the giant right-edge post curtain is gone.
- Some smaller things remain:
  - smears behind the house right of the pagoda (the outcrop);
  - a faint vertical seam where the post was;
  - grass-clump streaks.

The zone candidates were bundled with group A's new `town_t2_anim_pass` build spec. The `bgd_v1` renders used the
old one, so compare only the static terrain.

By eye (Unity, Castle):
- The default view matches `bgd_v1`.
- At the sweeps and orbits, the diagonal curtains across the town plaza and in front of the lighthouse are mostly
  gone; quilted, slightly blotchy texture takes their place.
- The hill under the left castle still smears at sweep_left and orbit y+18. Those are terrain-on-terrain ramps
  below the zone thresholds.
- Review-orbit magenta void px:
  - `pan_orbit_y+18_p+6`: 42 (`bgd_v1` 0);
  - `pan_orbit_y+0_p+14`: 802 (`bgd_v1` 564).

## No-split canvas (`--frame auto`, 2026-10-20)

The no-split lane's terrain is one grid over the whole painted canvas (factory 2620 x 1400, the 1920 x 1080 rest frame
plus margins) with a mirrored skirt past the canvas. `--frame auto` grows every raster symmetrically about the
principal point to cover the pieces (factory 3464 x 1704) while the focal length stays the rest frame's (`FH`); the
default `--frame rest` is unchanged (projection and rest depth bit-identical). The skirt's uv does not follow the rest
frame, so the uv -> frame affine is fitted on the registered vertices only (`uv_affine_registered`, at least 60%) and
the skirt triangles are frozen: never cut, and left out of the shipped-triangle cap check (their worst ratio is
reported as `frozenMaxRatio`). Factory ns8 (from ns4, `--cut zone`): main-surface smear over 6x at the proof poses
113k -> 52k canvas px; in-view reveal holes at most 671 px (pose 2). Installed 2026-10-20 for an in-game look.

## Floor clamp of the back layers (`town_full3d_ldi_floor.py apply`, opt-in, 2026-10-01)

**Defect.** The back layer continues the far surface under a ridge by inverse-depth push-pull. Where that far side
descends towards the camera, the continuation runs on *below* the painted floor plane (`T.Floor`). A reachable pose
that looks over the ridge passes above the sunken sheet and meets nothing. `town_full3d_zero_streak` counts such a px
as a ground hole: undrawn, but its ray meets the painted floor inside the far cap.

On Castle (`rx_ldi_zone_old_nfix`) this is the hole under the blacksmith's foot at the forward sweeps.

- With the environment alone, the hole is 550 px at `sweep_fwd` in that box, and 906 px at the worst pose
  (`loop_060`).
- The over-pulled blacksmith (order scale 0.652) used to hide it. With the scale at 0.890, the full state showed it:
  476 px at `loop_072`.

**Rule.** The rule runs once per candidate, after `town_full3d_ldi.py apply`, and is recorded as `ldi.floorClamp` in
the stage report.

1. Render the environment alone at every certificate pose (`reachable_cams(sc, 36)`: the default, the pans, the
   sweeps and the 36-pose loop).
2. Map each ground-hole px to the rest frame through its floor hit. On Castle this marks 2292 rest px.
3. Select the back vertices to move. A vertex is selected only if all of these hold:
   - the LDI *pushed* it, which means it is at least 1.01 x the main rest depth at its px, so it is hidden at rest;
   - it lies below the floor plane;
   - it is within 40 px of a hole px.
4. Move each selected vertex up its own rest ray towards the floor plane:
   - all the way within 8 px of a hole px, then by a linearly fading amount out to 40 px;
   - never nearer than `BEHIND` x the main surface at its px.
5. Relax the moved vertices under the ratio cap.

Welded boundary vertices, the cut cells drawn at rest, and the backstop never move, so the rest frame is unchanged.
`terrain_streak.npz` (`back_P`) and `ldi.sha256` are rewritten to match. Test: `test_town_full3d_ldi.test_floor_clamp`.

**Castle result** (43 poses, committed tools):

- 1019 of 70531 back vertices move.
- The maximum ground hole falls from 476 px to 158 px:

  | pose | before | after |
  |---|---|---|
  | `sweep_fwd` | 412 | 130 |
  | `loop_048` | 381 | 146 |
  | `loop_060` | 437 | 118 |
  | `loop_072` | 476 | 158 |
  | `loop_084` | 271 | 149 |

- The pre-order-fix baseline was at most 165 px.
- Visible behind-streak is unchanged at every pose.
- Enclosed holes fall at the forward poses, for example `loop_072` from 1639 to 1321.

**Negative.** Clamping *every* below-floor pushed vertex (26236) closes the same holes, but it raises the
back-terrain streaks summed over the poses from 13941 to 28172 px (`sweep_right` 1592 -> 3954). The raised sheet is
revealed over the cottages, so the clamp stays local to the holes.

**Still open.**

- The remaining holes of 118-158 px are not under a pushed below-floor back vertex. The clamp cannot reach them.
- Proof tier: generated artifact / offline render.
