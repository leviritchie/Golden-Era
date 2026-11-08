# HoMM3 full-3D town scenes: methodology v2

Status, 2026-10-01 (phase 2): every pilot has been run, and all five measured towns reach zero visible behind-streak
in memory. The first recipe candidate is **staged and certified**: castle `zs_v1`
(`tools/homm3_town_scene_meshes/recipes/castle_zs_v1.json`), with 0 visible px and no ground-hole growth in every town
state. Nothing in this doc is bundled or installed.

Proof tiers:
- Every number is **generated artifact / offline raster** proof unless it says otherwise.
- The by-eye checks use the lane's offline textured preview (`stronghold_full3d_scene.py preview`), not Unity renders.
- By eye, the bar is **not** met yet: see "Phase 2".

What this doc owns:
- the failure taxonomy behind the 2026-10-01 user reports;
- the out-of-the-box options, evaluated against this pipeline;
- the acceptance metric;
- the ranked pilots, and pilot 1's results.

What it does not own (other lanes, folded in below):
- Castle near-camera depth;
- the building seam / layer-split fix (`town_full3d_building_seams.py`, body_v1 residual rule);
- the continuous sky (`docs/homm3_town_sky_continuous.md`, in progress);
- building picking (`town_full3d_pick.py`, MeshCollider model);
- the Cove/Fortress `ssr_dfix` bundles.

## The bar

The user set the bar on 2026-10-01: **"the goal for any working method is 0 visible streaking behind objects."**

- A method succeeds only when no streak is visible behind any object at every reachable camera pose.
- A lower streak-pixel count is progress, not success.

### What "reachable" means

This section supersedes the 3-proof-pose gates.

The town camera has two modes:
- **Cursor mode** is a pure rotation (±3° / ±2°), so it reveals nothing.
- **Free sweep** moves the camera centre on a closed Catmull-Rom loop through 9 nodes, looking at the CityCamera pivot.

Parallax depends only on the camera centre. Edge openings and texel stretch are linear or convex in the centre
offset, so their worst case over the reachable set sits at its extreme centres. The analysis is in
`V:/olden_port_work/methodology_v2/pose_hull.py`, in the rest camera frame:

| | x (m) | y (m) | z (forward, m) |
|---|---|---|---|
| reachable centres | -4.35..5.28 | 0..3.16 | up to 4.04 |
| `sweep_left/right/high` proof poses | within 0.1 m laterally in every direction | | 2.31 |

The proof poses match the lateral extremes, but they miss the forward dolly: the loop reaches 4.04 m forward against
the proof poses' 2.31 m. Forward dolly is what magnifies near-camera geometry (the Castle report). The certificate
therefore adds two pose sets:
- `sweep_fwd`, the most forward loop sample;
- `loop_NNN`, evenly spaced loop samples. Default 36; the tables below use 12.

The full vanilla extent is measured. That is a superset of the runtime framing (zoom 1.17, panScale 0.5), so no camera
range is limited to pass. The user's rule "never limit the town camera" holds.

### The certificate: `tools/homm3_town_scene_meshes/town_full3d_zero_streak.py` (`town_zero_streak.v1`)

For every reachable pose, it rasters the lit `Mesh_` bins and computes four masks:

| mask | definition |
|---|---|
| `streak` | s1 ≥ 6 screen px per texel and s1/s2 ≥ 3 (the `town_t2_streak_map` rule) |
| `revealed` | the drawn point lies more than 3% behind the rest surface at its own rest pixel, so the rest camera did not see it |
| `behind` | streak AND revealed, inside the rest frame |
| `visible` | 4-connected `behind` components of at least 16 px |

**Pass condition:** no visible component at any pose.

Holes are reported, not gated. A hole is an undrawn px enclosed by geometry. Windows and arches legitimately open onto
more sky: castle props_v1 has no cut at all and still goes from 707 to 7909 hole px. Hole regressions are therefore
read against the seed (`holeGrowthPx`) and by eye on the overlays.

Overlay colours (`zs_<pose>.png`):

| colour | meaning |
|---|---|
| red | visible behind |
| orange | streak not revealed |
| blue | revealed, not streaked |
| magenta | enclosed hole |

Runtime is about 25 s per candidate at `--loop 12`. Since 2026-10-01 the per-pose analysis runs on CUDA by default (`--device cuda`). The CPU code is the reference (`--device cpu`) and gives byte-identical reports. The 43-pose x 3-state certificate on Castle zs_v5 takes 197 s on the CPU and 14 s on CUDA. See [town_gpu_kernels.md](town_gpu_kernels.md).

Limits of the certificate:
- Posed bins, Fx and alpha cut-outs are not drawn.
- It is not a by-eye Unity check.
- It is not yet wired into the build as a validator. It is the proposed acceptance gate for the default recipe. Once a
  candidate passes, the next step is to wire it into the stage validators, the way the buildingDepth gate is wired.

## Failure taxonomy (measured)

Certificate over the candidates closest to each installed town, `--loop 12` (19 poses). Columns:
- **max** is the largest visible-behind px count at any one pose, and **worst** is that pose.
- **poses** counts poses with any visible component.
- **sum** is the total over all poses.

Full numbers are in `artifacts/homm3_methodology_v2/results.json`.

| candidate | max | worst | poses | sum | dominant class | worst bin |
|---|---|---|---|---|---|---|
| cove ssr_v1 (installed) | 75248 | sweep_left | 16 | 515221 | bldg_front 351767, terrain 162508 | tbcvsay2 body 295734 |
| cove ssr_dfix | 33096 | sweep_left | 15 | 172602 | terrain 168955 | Mesh_Terrain |
| fortress ssr_v1 (installed) | 50584 | sweep_left | 17 | 354026 | terrain 325835, residual 26947 | Mesh_Terrain |
| fortress ssr_dfix | 60876 | sweep_left | 17 | 434102 | terrain 432183 | Mesh_Terrain |
| dungeon props_v1 | 13563 | sweep_left | 17 | 131227 | terrain 128740 | Mesh_Terrain |
| castle props_v1 | 10019 | sweep_right | 14 | 67108 | terrain 66475 | Mesh_Terrain |
| castle rx_ldi_zone_old (installed terrain) | 2302 | sweep_right | 10 | 10151 | terrain_back 9474 | Mesh_Back_Terrain |
| factory pb_v1 | 7745 | sweep_right | 11 | 24362 | terrain_back 21034 | Mesh_Back_Terrain |
| stronghold pb_v1 | 4240 | sweep_high | 16 | 23509 | terrain 19745, bldg 3254 | Mesh_Terrain |
| inferno props_v1 | 3770 | sweep_right | 16 | 28666 | bldg_front 19909 | tbindw_5_2 body |
| bulwark pb_v1 | 1372 | loop_288 | 11 | 9722 | terrain 9722 | Mesh_Terrain |
| necropolis props_v1 | 784 | sweep_right | 10 | 2248 | terrain 1870 | Mesh_Terrain |
| rampart rx_layer_card (installed) | 734 | sweep_high | 15 | 4557 | bldg_front 4149 | tbrmdw_0_2 body 3011 |
| tower rx_cond_dalarge_dfix | 120 | loop_108 | 8 | 548 | bldg_front 548 | tbtwmage_4 body |

**No town passes.** Tower and Rampart are closest, and what is left on both is Meshy building fronts. Three loop
samples between the proof poses (`loop_072`, `loop_108`, `loop_288`) are worse than any proof pose in several towns.
`sweep_fwd` is non-zero everywhere. So the 3-pose gates passed scenes that fail the bar.

### Root causes

#### R1. A continuous sheet bridges a depth discontinuity

**Terrain class.** This dominates Cove dfix, Fortress, Dungeon, Castle, Stronghold, Bulwark and Necropolis.
- One screen-space sheet from DA V2 depth stretches across every silhouette.
- rx_cond (monotone / envelope) removes it inside the terrain where it applies.
- LDI's zone cut removes it at the cut, but its back layer then streaks in turn (castle: 9474 terrain_back).

Why the LDI back layer streaks: it is relaxed under a forward-depth **ratio cap of 1.25 per triangle**.
- A surface on its own rest rays, with inverse depth w, stretches by |1 + f·b·Δw/ℓ| at baseline b.
- Here f ≈ 1224 px and b_max = 5.79 prefab units, giving G = f·b = 7089 px per unit of inverse depth.
- At that baseline a 1.25 ratio over a 3 px triangle at 150 m stretches about 14x.
- The cap is not the quantity the bar measures. Castle's back-layer anisotropy p99 is 100.

**Fortress and Cove "slab building depth"** is R1 inside a building:
- the Cove `tbcvsay2` body alone is 295734 px over the poses (a near-planar front projected over a deep, grazing body);
- the Fortress `resid` relief adds 26947.

#### R2. No disocclusion content

When a cut opens, the pixels behind it need content. The only sources are:
- push-pull and quilt;
- `keep_holes`, which **puts the stretched smear back** wherever a hole would open.

Pilot 1 below measured this trade directly. Remove the kept smear and the terrain streak goes to about 0, but the
ground holes appear instead. So the last terrain streak in a cut-based recipe is not a depth error. It is the absence
of a surface behind the occluder.

Behind building sprites, the painted background is ground truth: buildings are overlays on the HoMM3 town painting.
So streak behind a building is a building-geometry error, and only streak behind painted backdrop occluders needs
synthesis.

#### R3. Per-element depth reconciled by global pulls

- contact_v1 is affine in disparity, with one contact per layer.
- order_pass then pulls whole layers nearer, about the camera, by factors down to 0.41 (Cove cas3).
- A pull keeps the rest frame but breaks contact consistency with the ground and with neighbouring residual relief.
  That shows up as Meshy-vs-residual seams.
- The seam lane is R3 at building scale. Rampart's "distant buildings break into layers on turn" is this:
  `town_full3d_building_seams.py` measured it, and its body_v1 rule makes the residual take the body's depth.
- Separately, the installed rampart `rx_layer_card` turns terrain components into camera-facing cards with a 300 m far
  band. Cards at different depths are discrete planes by construction. Its certificate result equals props_v1's on
  buildings, plus 408 px of periphery from the cards themselves.

#### R4. The gates measure the wrong set, the wrong quantity, or both

- **Set:** 3 sweep poses, with no forward dolly and no in-between loop samples. See the table above.
- **Quantity:** absolute streak px (or anisotropy p99) over the whole frame. Visible streak behind objects, which is
  the user's bar, is a connected-component quantity on revealed px. Most streak px at a sweep are *not* revealed
  (castle sweep_right: 15172 streak, 2302 behind), so the old totals mix periphery, grazing ground and real defects.

#### R5. Candidate forking ships stale depth

- Every candidate is a copy of a seed's stage directory.
- Cove and Fortress `ssr_v1` were seeded from `pb_v1`, before contact_v1. The installed water work therefore shipped
  stale, streaking building depth: Cove ssr_v1 at 515221 against ssr_dfix at 172602.
- Nothing composes "terrain recipe X + building rule Y + water Z". Nothing fails when a fix is not inherited.

#### R6. Picking from boxes

- Hover and click were native BoxColliders fit to each body's renderer AABB.
- With depth-spread bodies, the AABBs overlap and do not match the silhouettes.
- The picking lane (`town_full3d_pick.py`) measures box against mesh pick IoU and moves the runtime to MeshColliders on
  the drawn bodies.
- That is the right fix and it is not superseded here. Its correctness inherits R1 and R3: a pick mesh that streaks
  also picks where it streaks.

#### R7. Sky seam

- Painted sky outside SKY_MASK is carried by the terrain relief at finite depth, so it parallaxes against the dome,
  and the rect edge shows a seam.
- The continuous-sky lane owns this.
- Methodology consequence: every sky px must be on the dome (at infinity) or on the dome's own feathered panorama.
  None may be on the terrain sheet. The certificate does not draw the sky. The sky lane needs its own seam gate.

## Options evaluated

Each option is scored for:
- gain per failure class;
- cost (compute / VRAM / Meshy spend);
- risk;
- faithfulness to the HoMM3 art;
- how it plugs into catalog / bundle / install.

### A. View-set-aware optimisation (exact parallax bound) — **adopt**

This replaces tuned caps (ratio 1.25, ANISO_CUT 3) with the bound the bar implies. Any surface shipped on its rest rays
must satisfy

> |Δw| ≤ (K-1)·ℓ / G per edge, where G = f·max|b| over the reachable centres.

Where the bound cannot hold, the surface gets a cut plus a flat card or back layer.

- **Gain:** directly targets R1 on terrain and building fronts.
- **Cost:** CPU only, seconds.
- **Risk:** low.
- **Faithfulness:** exact, because rest rays and UVs are unchanged.
- **Plug-in:** inside the stage builders (LDI relax, rx_cond envelope, building front assignment), so the same bins and
  rows ship.
- **Variant:** a building face takes the projected sprite texture only if its stretch at every reachable pose is ≤ K.
  Otherwise it keeps the Meshy texture. This replaces the "owns ≥ 60% of its z-buffer px" rule. That rule is
  rest-only, which is why grazing Meshy faces streak.

Pilot 1 measures the terrain half of this.

### B. Differentiable rendering against the view set (nvdiffrast / moderngl gradients)

Optimise vertex depth along rest rays, plus back-layer texels, with three terms:
- streak and reveal penalties at the reachable poses;
- the rest frame pinned;
- a smoothness prior.

- **Gain:** R1, and the part of R2 that is geometry (where the back layer sits).
- **Cost:** GPU, minutes per town, under 4 GB VRAM.
- **Risk:** medium. The objective has to be the certificate's objective, or it optimises the wrong thing.
- **Faithfulness:** exact at rest.
- **Verdict:** A is the closed-form special case of B. Do B only if A plus cards leaves geometry-shaped residue. It is
  not in the top 3.

### C. Diffusion novel-view priors (Stable Virtual Camera / Seva, ViewCrafter, Gen3C)

- **Gain:** R2 only, by synthesising what is behind occluders.
- **Cost:** Seva runs on one 16 GB card at low res. ViewCrafter needs 18-23 GB, which is too much here.
- **Faithfulness:** the risk is high. The user already rejected img2img depth as "adds contrast", and the SDXL back
  inpaint was a negative (it inherits haze context).
- **Plug-in:** distil into the back-layer texture only, never the front.

Video-diffusion priors hallucinate style, so this is pilot 3 with a faithfulness gate. Use it only as a far-side-
conditioned fill of the measured hole masks, with the HoMM3 frame and its own far-side exemplars as context.

### D. Per-building rigid proxies (one rigid body per building, sprite on its own surface)

- **Gain:** R3 inside a building is removed by construction. The seam lane's body_v1 already approximates it for the
  residual.
- **Cost:** none new.
- **Risk:** low.
- **Faithfulness:** good where the Meshy body fits.
- **Verdict:** the seam lane owns this. The plan below keeps it. It does not address the Meshy-front streak (Rampart,
  Tower, Inferno), which needs A's face rule.

### E. LDI / MPI with inpainting, plus a shader-side discard

- The LDI is already in use.
- An MPI of fronto-parallel planes is streak-free by construction, but it quantises depth into visible layers. That is
  exactly the "discrete layers on turn" report.
- A shader-side stretch discard (alpha-0 where the per-pixel derivative of uv exceeds K) turns streaks into holes at
  runtime. It needs the Hex SRP shader. Holes are not a pass either.
- **Verdict:** keep LDI, with A's bound replacing its cap. Reject MPI and the discard shader as the default.

### F. Gaussian splatting / neural scene

- **Cost:** about 48 bytes per splat. Integration needs aras-p UnityGaussianSplatting, which supports Built-in/URP/HDRP
  only. OE renders through its own Hex SRP, so custom integration means sorting, overdraw and its own depth.
- **Risks:**
  - There is no exact rest frame. Splats fit from a single painted view are a novel-view problem anyway.
  - Floaters.
  - The splats do not interact with the native BhBuilding picking or the lighting pipeline.
- **Verdict:** high risk, low faithfulness at rest. **Rejected.**

### G. Scene-level layout solve (one joint depth solve for all buildings and terrain)

Solve every layer's contact, scale and order jointly:
- contacts on the terrain surface;
- the painted occlusion order as inequality constraints;
- A's bound as a constraint on each layer's spread.

The current pipeline does this in two steps: per-layer contact_v1, then global order pulls.

- **Gain:** R3. Fewer seams. Buildings stay grounded.
- **Cost:** CPU, a small QP.
- **Risk:** medium.
- **Faithfulness:** exact at rest.
- **Plug-in:** replaces `order_pass` in `town_full3d_building_redepth.py`.

This is pilot 2.

### H. Process: a declarative scene recipe (anything better)

R5 is the cheapest large win. Each town's stage would be built from a recipe instead of forking a candidate:
- seed paint;
- terrain rule;
- building rule;
- water / sky / props passes;
- certificate gate.

A new improvement then lands in every recipe that names it. The ssr_v1 regression could not have shipped.

- **Cost:** engineering only.
- **Plug-in:** the same `catalog.json` / bundle / install path. The recipe is the candidate's provenance.

This is part of the recommended default, not a pilot.

## Ranked pilots (at most 3)

| rank | pilot | town | metric (falsifiable) | budget |
|---|---|---|---|---|
| 1 | **A on terrain:** view-set Lipschitz back layer + bound-violating tiles as flat cards | castle (seed props_v1, installed zone-cut recipe) | certificate: 0 visible-behind components at every reachable pose; hole growth not above the zone-cut baseline's by eye | CPU, about 6 min per variant, 0 Meshy |
| 2 | **A on buildings + G:** stretch-bounded sprite/Meshy texture assignment and a joint layout solve replacing order pulls | tower (closest to zero: 548 px, all bldg_front), then cove (tbcvsay2) | certificate 0 on bldg_front / bldg_residual; buildingDepth and seams_v1 gates still pass | CPU, under 1 h per town, 0 Meshy |
| 3 | **C as a fill:** far-side-conditioned generative fill of the measured hole masks, distilled into back-layer texels | castle, after pilot 1 | certificate holes → rest level with streak still 0; faithfulness: by-eye against the HoMM3 frame, no new contrast; colour statistics of filled texels within the far side's own | GPU (16 GB), about 1 h; 0 Meshy |

## Pilot 1: view-set Lipschitz back layer (run)

The harness is `artifacts/homm3_methodology_v2/pilot_vlb.py`. It works in memory, on the staged `Mesh_Terrain` of
castle `props_v1`, and nothing is staged or installed. It reruns `town_full3d_ldi.keep_holes` with the installed
Castle zone recipe (`ZONE_DEFAULTS`) and swaps only the back layer's depth rule:

| variant | back layer depth rule |
|---|---|
| `ldi_zone` | installed: `relax_to_cap`, ratio 1.25 |
| `vlb_zone` | the smallest deepening of the pushed vertices with \|Δw\| ≤ (K-1)·ℓ/G on every edge (min-plus), alternated with the ratio cap |
| `vlbcard_zone` | `vlb_zone`, and every back tile still over the bound becomes LDI's flat card at its farthest depth (the treatment over-cap tiles already get) |
| `_nokeep` | no `keep_holes` rounds, so no smear is put back in the main sheet |

All variants use G = 7089 px per inverse-depth unit and K = 2 unless stated. `ldi_zone` reproduces the installed
candidate exactly (2302 / 9474), which validates the harness.

| variant | max visible-behind px | poses with visible | sum | classes | hole growth px | ground holes in overlay |
|---|---|---|---|---|---|---|
| ldi_zone (installed recipe) | 2302 | 10/19 | 10151 | terrain_back 9474 | 7214 | 0 |
| vlb_zone | 9539 | 13/19 | 58155 | terrain_back 57465 | 7257 | 87 |
| **vlbcard_zone** | **1090** | 12/19 | **4946** | terrain_sheet 4318 (kept smear), **terrain_back 0** | 7570 | 379 |
| vlbcard_zone, K = 1.5 | 1522 | 12/19 | 7195 | terrain_sheet 6567 | 7666 | 410 |
| **vlbcard_zone_nokeep** | **106** | 10/19 | 656 | Mesh_Houses 584, bldg 44, **terrain 28** | 17893 | 6588 at loop_252 |
| vlbcard_zone_nokeep, band ×3 (≤640 px) | 106 | 10/19 | 656 | same | 20942 | worse |

### Findings

1. **The bound works, the bare relaxation does not.**
   - With the view-set bound and cards, the back layer's own visible streak goes from 9474 to **0**.
   - The bare min-plus relaxation is 6x *worse*. Deepening a pushed vertex toward the far side leaves it far behind
     an adjacent fixed nearer vertex, which makes a new curtain.
   - The bound is only an improvement with the card fallback: a tile that cannot meet the bound must become a flat
     card. It must not ship stretched.
   - This is a measured negative for "relax harder" and a positive for "bound or card".
2. **The last terrain streak is `keep_holes`' smear.**
   - Drop it and terrain behind-streak is 28 px over 19 poses (no component at 16 px is terrain at all).
   - The holes it was hiding open instead: 6588 ground-hole px at `loop_252`, behind the front-left house.
   - That is R2, measured.
   - A wider band does not close them (band ×3: hole growth 20942). They are not band reach. The far side there has no
     surface behind the occluder.
3. **Neither variant passes.** What remains in `vlbcard_zone_nokeep` is not terrain:
   - 584 px of `environment/Mesh_Houses`, an environment relief piece with its own sheet;
   - 44 px of one building front (`tbcsdw_6_2`).
   - Both are inside pilot 2's scope (the face rule applies to any relief piece).
4. **K = 1.5 is worse than 2.** More tiles become cards and more smear is kept. The bound is not a "tighter is better"
   knob. K = 2 stays.
5. **Sky windows.** Most hole px above the horizon, such as the gap under the tree crown, are sky seen through
   geometry. In game the dome fills them, and that is physically right. The certificate counts them; the review by eye
   separates them. A sky-aware hole classifier (hole px whose rest-frame neighbour is the dome) is the remaining
   certificate improvement.

Proof tier: generated artifact (offline moderngl raster of in-memory meshes). Textures were not synthesised for the new
back tiles: streak is a geometric measure, so it does not need them. Unity render and runtime: unproven.

## Phase 2: to a pass (2026-10-01)

All runs below use the certificate at loop 12 (19 poses) unless stated. Harnesses:
- `artifacts/homm3_methodology_v2/pilot_combo.py`: pilots 1 + 2 + pilot 3's geometry, in memory, certificate-driven;
- `pilot_front.py`: pilot 2's front rule alone;
- `pilot_fill.py`: pilot 3's content review.

The certificate gained a sky-aware ground-hole count (`groundHolePx`). A px counts when the pose draws nothing there
but its ray meets the painted floor plane (`T.Floor`) inside the far cap. Sky windows under crowns and arches are the
dome's and are excluded. The pass rule is still visible behind components only; ground holes are gated by the recipe.

### Step 1: Cove and Fortress `ssr_dfix` against `ssr_v1`

| candidate | worst pose px | total px | breakdown |
|---|---|---|---|
| Cove ssr_v1 | 75248 | 515221 | bldg_front 351767 (the tbcvsay2 slab) |
| Cove ssr_dfix | 33096 | 172602 | terrain 168955, bldg 3647 (tbcvtave 2032) |
| Fortress ssr_v1 | 50584 | 354026 | terrain 325835, resid 26947 |
| Fortress ssr_dfix | 60876 | 434102 | terrain 432183 |

- **contact_v1 alone fixes the tbcvsay2 slab** (295734 -> 0 px).
- It does not fix terrain. On Fortress it makes terrain worse: the redepthed buildings reveal more of the backdrop's
  tree-trunk curtains. The terrain mesh is byte-identical across ssr_v1 / pb_v1 / ssr_dfix.

### Pilot 1 on the dfix seeds (terrain layer only)

| run | worst pose px | remaining |
|---|---|---|
| Fortress ldi_zone / vlbcard_zone / **vlbcard_zone_nokeep** | 3050 / 1858 / **1285** | periphery 2730 (OuterL1/L2), terrain 3363, bldg 1136 |
| Cove ldi_zone / vlbcard_zone / **vlbcard_zone_nokeep** | 3209 / 2856 / **808** | terrain 0; bldg_front 3887, OuterL2 1472 |

As on Castle, the view-set bound with cards and no hole keeping removes the terrain-back streak. The holes it opens
are what the backstop is for.

### Pilot 2: the stretch-bounded front texture rule

Rule: a Mesh_Body_<l> front face that a visible component hits takes the Meshy texture of its sibling
(Mesh_BodyM_<l> / _hull). In memory this uses a planar per-face parametrisation at the sibling's texel density.

- **Tower** `rx_cond_dalarge_dfix`: 120 -> **0 (pass)**, with 35 faces moved and 4 rest px changed out of 385564. At
  loop 36 (43 poses): 50 faces, 8 rest px, still a pass.
- **Rampart** `rx_layer_card`: 734 -> 593 with the front rule alone. The rest is the relief-only tbrmdw_0_2, which has
  no Meshy source.

**Layout solve (G): not run.** Once the per-face rules ran, no remaining failure in any of the five towns was
R3-shaped: every failing face was cleared by a face-local rule, with no contact or order change. A joint solve would
target seams and grounding (the seam lane's body_v1), not behind-streak. It is deferred, not refuted.

### Pilot 3 geometry: the Lipschitz backstop, and the combined repair

The backstop is one sheet on the rest rays behind the rest surface.
- Its inverse depth is the largest L-Lipschitz function under w0/1.02, with L = (K-1)/(f·b_max)/√2 per px.
- By the view-set bound it cannot stretch past K at any reachable pose.
- Any face a visible component hits that no state shows at rest is **dropped**: the backstop shows where it opened.

Combined with pilots 1 and 2 (`pilot_combo.py --backstop`, full state):

| town / seed | before | after | rules applied | rest px changed | ground holes |
|---|---|---|---|---|---|
| Rampart rx_layer_card | 734 | **0** | Meshy 86, drop 123, fill 2 | 4 Meshy + 610 fill | 0 |
| Tower rx_cond_dalarge_dfix | 120 | **0** | Meshy 35 | 4 | 0 |
| Castle props_v1 (Terrain + Houses) | 474 | **0** | drop 42 | 0 | 0 (640 before the border margin, below) |
| Cove ssr_dfix | 837 | **0** | Meshy 122, drop 116, fill 1 | 20 + 2 | max 13 (under 16 px), rest 0 |
| Fortress ssr_dfix | 3427 | **0** | Meshy 60, card 242, drop 685, fill 22 | 1 + 445 card + 932 fill; 71 drawn by another face | 0 |

Negatives found on the way:
- **Card whack-a-mole on the periphery.** Without the backstop, Fortress needed 6 rounds: every card's cracks
  uncovered more OuterL1/L2 faces (156 cards, 1167 rest px changed, ground 2510). With the backstop, the hidden faces
  are dropped instead.
- **Rest-degenerate faces cannot be carded.** tbrmdw_0_2 relief side walls and sprite_fill faces have rest
  anisotropy 400-1700. A card of a smear is still a smear. They take a planar `_fill` parametrisation. That changes
  their rest px (Rampart 610, Fortress 932), so they need pilot 3's content and are not stage rules yet.
- **A frame-sized backstop leaves border holes.** A translated pose sees past the frame by f·b·w of what is at the
  border (Castle loop_072: 640 ground-hole px at the right edge). The sheet now continues past each border by that
  border's own parallax (edge-clamped). Castle's margins are 4 / 576 / 572 / 576 px (top / bottom / left / right).
- **Enclosed-hole growth is not a defect gate.** Windows legitimately open more sky as the camera moves (Castle
  props_v1 with no cut: 707 -> 7909). It stays a diagnostic.

### Pilot 3 content: far-side fill, judged by eye

No generative model is used. The SDXL back-inpaint is a recorded negative, and the user rejected img2img as "adds
contrast". Fill candidates were tried on Castle's measured backstop texels (seen by a reachable pose, not touching
the rest surface). CIELAB L\* statistics are against the far-side source within 64 px. They only flag added contrast;
they accept nothing.

| fill | target / source | by eye vs HoMM3 | L\* mean / std (source) | \|Lap\| |
|---|---|---|---|---|
| push-pull | env-owned seen / touching | **rejected**: flat tan blobs | 41.5 / 1.7 (42.4 / 10.5) | 6.1 |
| quilt, touching source | same | **rejected**: roof and purple wall fragments copied in | 40.3 / 7.8 | 11.2 |
| quilt, touching ground source (≤ 1 m off the floor plane) | same | reads as the painting's grass behind the houses; plain grass strips cut into hillsides where the truth was hill | 41.1 / 7.7 (43.0 / 8.5) | 11.3 (source 7.0: tile seams) |

Two further negatives came out of the staged build:
- **A sparse source drifts.** Quilting from touching ground only had 954 windows. The tone shift saturated at its
  ±24 cap and drifted the front-house fill purple. Sourcing from the frame's own ground paint outside a 2 px halo gives
  65439 windows, a tone-shift p95 of 18-22, and no drift.
- **The backstop drew a ground band in the sky.** At sweep_right, the strip behind the horizon terrain was uncovered.
  Backstop triangles that only dome rays (rays missing the floor plane inside the cap) see are now pruned: 4615 on
  Castle.

### Option H: the recipe, and the Castle candidate

`tools/homm3_town_scene_meshes/town_full3d_recipe.py` (`town_full3d_recipe.v1`) builds a fresh candidate from a
recipe JSON and fails closed unless the certificate passes. Steps:
1. seed (`candidate-init`);
2. LDI with the new opt-in flags `--back-rule vlb --keep-rounds 0 --reach-loop 12`;
3. the environment-only Lipschitz backstop `Mesh_Backstop`;
4. certificate-driven drop / card repair over **every town state**;
5. sky-side prune and the ground-source quilt;
6. the gate, with result and sha pins in `work/zero_streak_recipe.json`.

The LDI defaults are unchanged. In-process, the production `--back-rule vlb` path reproduces the pilot's cuts, back
tiles, cards and stop tiles bit-exactly (46026 / 130374 / 7617 / 32470). `tools/validate_town_zero_streak_contract.py`
is wired into the OfflineUnlockMod full-validation build. It checks:
- the pass rule;
- the gate;
- the LDI defaults;
- the recipe schema;
- `verify` (a re-hash of the certified bins) for every recipe candidate staged on the machine.

Mesh_Houses is atlas-mapped, not frame-affine, so LDI refuses it. The recipe layers Mesh_Terrain and leaves the house
relief to the repair rules.

Castle `zs_v1` (seed props_v1), staged and certified. Proof tier: generated artifact, not bundled or installed:

| state | visible behind px | ground holes (max / rest) | enclosed holes (max / rest) |
|---|---|---|---|
| start | 0 | 0 / 0 | 236 / 168 |
| full | 0 (seed: 10019) | 0 / 0 | 7918 / 707 (seed: 7909) |
| anim | 0 | 0 / 0 | 457 / 125 |

Repair: 37 faces dropped and 2 carded (Mesh_Houses, Mesh_Terrain, tbcsdw_6_2).

Backstop:
- 549062 triangles, with 4615 sky-side triangles pruned;
- a 3068x1660 texture;
- 70550 seen texels, 68895 of them filled.

At rest, the backstop draws 3-4 px in each state. The textured preview differs from the seed in 23505 rest px by more
than 8 levels. These sit along the LDI cut cells and silhouettes, where the back layer redraws the cell through its
crop texture.

**By-eye verdict** (offline preview, sweep poses, against the seed):
- The diagonal curtains behind the front-left cottages are gone. Ground shows there instead.
- The replacement still reads as angular flat patches: the VLB cards and the quilted backstop, slightly pink where the
  source is the flower field.
- The vertical stripes on the Mesh_Houses relief side walls remain. They are in the seed too. They are stretch *on*
  the rest surface, not behind it, so the certificate (revealed px only) does not count them.

So `zs_v1` meets the certificate, but it is not yet faithful enough to call the bar met by eye. That needs:
- real geometry for the painted houses (the Meshy untextured lever, evaluated separately);
- a `streakNotRevealed` gate for side walls.

Do not bundle it until those are judged in a Unity render.

### Re-layering an LDI seed: `ldi.fromPreLdi`

Some seeds are themselves LDI candidates whose later fixes are wanted, such as `rx_ldi_zone_old_nfix2_cloth` with its
building depth, seams and cloth. Their Mesh_Terrain is already cut, and Mesh_Back_Terrain sits on the ratio cap.

`town_full3d_ldi.py unlayer --npz <seed>/bundle/terrain_streak.npz` undoes `apply` exactly, from the stage's own
record:
- each main bin gets its cut and smear-cut triangles back;
- the vertices, normals, uv and texture were never touched;
- the back and stop bins, and their rows, are removed;
- the report's `ldi` section moves to `ldiUnlayered`.

It fails closed in four cases:
- the npz is not the one the report pins (sha256);
- a main bin's vertices are not that npz's `main_P` slice;
- a cut triangle straddles two pieces;
- a restored triangle repeats.

A recipe with `"ldi": {"fromPreLdi": true, ...}` runs it before `apply`. Checked on nfix2_cloth: the restored
Mesh_Terrain equals props_v1's, in vertices, normals, uv and oriented triangle set. A wrong npz is refused, and so is a
second unlayer. The building-depth terrain sample is re-pinned when the catalog is written (it re-samples the staged
terrain pieces), so the candidate needs `catalog` after the recipe and before `validate_town_scene3d_contract`.

### Residual depth steps: tear and flap

**The conflict.** On Castle, the seams gate (seams_v1) and the streak gate (the certificate) failed on the same faces
(zs_v3). body_v2 snaps residual vertices within 4 px of a Meshy body onto the body's nearest rest depth. Where two
body parts sit side by side at different depths (a pole at 89 m in front of a wall at 103 m), the residual fringe
between them becomes a ramp: sub-pixel faces whose vertices span the step (R1 inside a building).
- At rest they are hidden or nearly hidden. At a sweep they stretch across the opening, so the certificate counts them.
- Dropping them opens the seam, because they were the only surface there, so seams_v1 counts a see-through gap.

**The rule** (recipe repair rule `flap`, `tools/homm3_town_scene_meshes/town_full3d_step_flap.py`):
1. A certificate-failing face of a residual bin whose vertex depths differ by more than `STEP_EPS` (2 %) is torn out
   by the recipe's own drop / card choice, even when seamAware guards it.
2. The far side of the step gets a flap: a pixel-centre grid at the lip's depth on the near side's rest rays.
   - It covers only px where the layer's own rest front is `FLAP_HIDE` (1.01×) nearer, so the rest frame does not change.
   - It reaches only the largest opening the reachable poses produce at each px, plus 2 px, and at most 64 px.
   - Its texels are the residual's own sprite texels mirrored across the lip, through the residual's affine
     rest px → uv map. That map is checked to 0.5 texels and fails closed.
   - No flap triangle crosses a step.
3. At a sweep the opening then shows the far side continuing. The seam's fill test sees a surface at the far side's
   depth, and the certificate sees no stretched texels.

**Measurements** (Castle, seed `rx_ldi_zone_old_nfix3_cloth`, offline raster, loop 12):

| run | residual visible-behind | seams_v1 |
|---|---|---|
| nfix3_cloth (seed) | 2551 px over 224 faces (tbcsdw_5_2 1746, tbcshal3 474, tbcmark 270, ...) | 87 split, 0 layers failing |
| recipe, drop/card only | 0 | 109 split, tbcsdw_5_2 fails (22/1738) |
| recipe + flap (`zs_v4`) | 0, all three states | 102 split of 25029, 0 layers failing |

zs_v4 took 3 repair rounds (345 → 84 → 0 failing faces): 401 faces dropped, 28 carded and 260 torn for flaps. The
flaps cover 18.7k px in all (tbcmark 10.2k, tbcsdw_5_2 4.8k, tbcshal3 3.1k, tvrn 0.4k, cas3 0.2k).
- Board-pose rasters against the seed: 735 px differ by more than 24 levels at the default pose. The largest region
  is 89 px, at the frame-edge tree and a roof. By eye I see no angular patches at rest. At the sweeps and orbits
  there is less ground smear than the seed.
- **zs_v4 failed the 43-pose certificate.** The start and anim states passed. The full state failed at 4 sweep
  samples (loop_060, 096, 240, 336), with one component of 16-17 px at each.
  - The cause was 24 faces in tbcmark, tbcshal3 and tbcsdw_5_2.
  - Every one of them is a residual step face, so the rule covers it. They fail only between the 19 loop-12 poses,
    so the repair rounds never saw them.
- **zs_v5** is the fix (`recipes/castle_zs_v5.json`). It is zs_v4 plus `certificate.extraPoses`: those four samples,
  added to the loop-12 repair and gate poses.
  - The repair is not run on all 43 poses: compute is shared, and 43 poses per round is overkill.
  - Build: 3 rounds, 388 -> 91 -> 0 failing faces.
  - 43-pose certificate, run once: 0 visible behind at every pose in all three states, and no ground-hole growth.
  - seams: 81/25051 split, 0 layers failing.
  - Rest: zs_v5 and zs_v4 differ in at most 6 px at the default and cursor poses.
- Reviewing the rest pose against the installed `rx_ldi_zone_old_nfix`:
  - 14.4k px differ at the default pose. Most of them are the seed's own changes since nfix: the cloth banners and the
    body_v2 depth.
  - In the crops, the cloth banners show a few dark pinholes that were not there before. That is a cloth-lane
    question for the in-game check, not a flap effect.
- If a later 43-pose run fails at new in-between poses, the next step is a face-level rule, not more poses. Such a
  rule would flag every residual face that bridges a step above a bound at any reachable yaw, analytically.
- **Installed:** 2026-10-01, bundle ee8b1565, rollback `artifacts/town_scene_rollback/castle_20261001T230912Z`. Proof
  tier: installed payload. It is not runtime-proven; the Castle row in `docs/ingame_check_queue.md` covers that.
- Review boards (offline albedo raster), with rows of installed | candidate | HoMM3 painting:
  `V:/olden_port_work/castle_review/BOARD_zs_v4.png` and `BOARD_zs_v5.png`.

**Negative.** Tearing every step face that could streak, rather than only the certificate's failing ones, tore smooth
grazing slopes: 929 seam splits. The tear is seeded only from the failing faces.

Proof tier: generated artifact (offline raster, catalog-time seams_v1). Unit test: `test_town_full3d_step_flap.py`.
`tools/validate_town_zero_streak_contract.py` pins `FLAP_HIDE`, `FLAP_UV_TOL` and `STEP_EPS`, and runs the unit test.

### Seam weld: seams_v2 inside the recipe (2026-10-02)

**The conflict.** On Rampart (zs_v5) and Tower (zs_v4) the certificate passed, but the validator's seams_v2 gate failed
after the bundle. Rampart failed on tbrmdw_0 at 24/1990 split pairs, tbrmhal2 at 47/3981 and tbrmhall at 32. Tower
failed on tbtwdw_6 at 34. A layer fails when more than 20 pairs split and more than 1 % of its residual pairs split.
- The seed (body_v2_gc) was already at the margin, with 19-26 splits per layer.
- Every seed split is a Meshy body | residual (BodyRest) pair. body_v2 leaves a 1-3 % depth step there, and at a sweep
  the gap shows something more than 1.01x deeper.
- The repair rounds add a few more pairs, between a residual and a new card or flap face, and that tips a layer over.

**Tightening.** The recipe gate (`gate`) and `final` now run the validator's own measure on the staged files
(`seams_staged`: `town_full3d_building_seams.seams_for_build` + `building_seam_failures`). A split fails the build
before the bundle.

**The rule** (opt-in `repair.seamWeld`, v2 only; `seam_weld` / `seam_weld_plan` in `town_full3d_recipe.py`):
1. It runs inside the repair fixed point, once the rounds are clean and the sky-side prune removes nothing.
2. It measures seams_v2 on the in-memory stage, with `rest_seams(load=..., faces=True)`, which also returns the face
   drawing each side of a pair.
3. In each failing layer, the residual face of every split Body|residual pair is carded onto the body. The face is
   copied per vertex and slid along its rest rays by the median of body distance / residual distance over its split
   pairs, so the rest frame keeps every px.
4. It repeats measure-and-card up to `SEAM_WELD_ITERS` (3) times, stopping as soon as no layer fails.
5. The rounds then run again to certify the welded geometry. This happens at most `SEAM_WELD_CYCLES` (2) times, and
   the build fails closed after that.
6. The result records each welded face (bin, face, factor, split pairs) and each layer's split count before and after.

**Measurements:**

| town | layer | split before | split after |
|---|---|---|---|
| Rampart zs_v7 | tbrmdw_0 | 25 | 19 |
| Rampart zs_v7 | tbrmhal2 | 47 | 32 |
| Rampart zs_v7 | tbrmhall | 32 | 32 (already passing) |
| Tower zs_v4 (offline dry run) | tbtwdw_6 | 34 | 23 |
| Tower zs_v7 | tbtwdw_6 | 34 | 23 |

- Rampart zs_v7 welded 51 faces in cycle 1. The certifying rounds stayed clean: 0 failing faces.
- Rampart totals: 181/57581 pairs split, no layer failing. FINAL PASS, 157 poses x 32 states.
- Installed 2026-10-02, bundle 1e113254, rollback `artifacts/town_scene_rollback/rampart_20261002T185555Z`. Proof tier:
  installed payload. It is not runtime-proven.
- Tower zs_v7 (built on merged main) welded 23 BodyRest_tbtwdw_6 faces in cycle 1 (factors 0.865-1.137); cycle 2
  carded nothing and the rounds stayed clean. Totals: 110/15764 pairs split, no layer failing. FINAL PASS, 157 poses x
  32 states; bundle ace3d86e. Generated artifact validated; handed to the coordinator for install.
- Weld factors run from 0.86 to 1.14, so some residual faces move up to 14 % along their rays. The rounds re-certify
  that, but it is the first thing to check in game if a weld edge looks wrong.

**Negative: seamCard.** seamCard was a repair rule tried before seam weld and then removed from the tool. A
seam-guarded failing face shown at rest was carded at the depth of its own span nearest its body's front, instead of
at its farthest depth. Rule flap also took each px's nearest lip.
- Rampart zs_v6 converged with it, but seams_v2 still failed on tbrmdw_0 (24), tbrmhal2 (48) and tbrmhall (40).
  zs_v5 without it had 24 / 47 / 32.
- It acted only on faces the certificate failed. The splits are on body seams the certificate never flags.
- Carding every guarded face onto the body (try 1) took 9 rounds with about 1200 drops per round, and did no better.
- Its zs_v6 recipes are retired; they are kept under `V:/olden_port_work/towns_rampart_fortress_tower/rejected/recipes/`.

**Board note (Rampart).**
- In the offline albedo raster (`pilot_meshy_geom.render`, unlit), trees and foliage show bright yellow-green patches,
  even at rest. The lit Unity renders do not show them, so this is an artifact of the board renderer, not of the scene.
- At sweep_left, the dark smeared ground and trees behind the big right-hand house are pre-existing and remain a
  known defect. The certificate passes there, because the smear is far-side backstop fill, not a streak.

Tests:
- `test_town_full3d_recipe_seam_guard.py` (SeamWeld) covers the plan, the load checks and `card_at`.
- `test_town_gpu_kernels.py` checks the `faces=True` / `load=` arrays between cpu and cuda and against the file read.

### The Meshy untextured lever (pilot, 2026-10-01): a negative

The question was whether untextured Meshy meshes for the painted cottages could replace the Mesh_Houses relief, with
the painting projected from the rest camera onto rest-seen faces (|cos| >= 0.2). The pilot used Meshy T2
smart-topology at 5 cr each, on Castle, measured at the review-board poses (offline raster).

Meshy has no "T2.5": it is not in the API docs, the API or webapp changelogs, or a web search. `meshy-t2` is the only
smart-topology model. Meshy-6/7/7.1 cost 20 cr untextured.

Spend: 20 of the 60 cr cap. Pass `meshgeom_pilot_20261001` in `_ledger.jsonl`, budget
`_budget_meshgeom_pilot_20261001.json`.
- 3 cluster crops (`cott_right`, `cott_centre`, `cott_left`).
- 1 single cottage (`cottage_a`), instanced greedily 11 + 14 times over the centre and right cluster masks.

| run | visible behind px, sweep L / R | relief stretch on the rest surface, sweep L / R | rest px changed |
|---|---|---|---|
| nfix | 1707 / 1592 | - | - |
| nfix + clusters | 2737 / 2215 | - | - |
| zs_v1 | 0 / 0 | 645 / 482 | - |
| zs_v1 + clusters | 0 / 0 | 227 / 225 | 57.5k |
| zs_v1 + cottage_a instances | 0 / 0 | 287 / 374 | 8.1k |

Which taxonomy classes geometry fixes, and which it does not:
- **Terrain back (R1, the ratio cap): no.** On nfix the cottages reveal more of the stretched Back_Terrain
  (1042 -> 2151 px at sweep_left). VLB fixes this; geometry does not.
- **Disocclusion (R2): no.** The backstop covers it.
- **Mesh_Houses behind-streak at the orbits: yes, but small.** 57/63/42 -> 25/0/0.
- **Mesh_Houses side-wall stretch on the rest surface: halved.** Each form costs something by eye:
  - clusters: lumpy roofs and flat planar faces at rest, a rest regression;
  - instances: close to the painting at rest, but under sweep the projected paint tears across cottages that do not
    match the painted ones.
- **cott_left: nothing.** The hall sprite covers it in the full state, so those 5 cr were wasted.

Verdict: not a rollout lever. The certificate's visible-behind failures are depth and ordering problems (R1, R2, R3),
not missing geometry. A rollout of one 5-cr generation per painted-house type per town (about 8 towns × 2-4 types,
40-160 cr of the 1200) would buy only on-surface stretch, at the by-eye cost above.

Harness, generated-artifact tier, nothing staged:
- `artifacts/homm3_methodology_v2/pilot_meshy_locate.py`;
- `artifacts/homm3_methodology_v2/pilot_meshy_geom.py` (`prep` / `gen` / `fit` / `instance` / `measure`).

### mv3 multi-view inpaint (Castle, 2026-10-01)

The pilot gives the scene three painted views: rest, `sweep_left`, `sweep_right`. Each side view is inpainted by Meshy
`gpt-image-2-5-sunburst` (12 cr), then delivered into the staged candidate `rx_mv3_inpaint`. Scratch is
`V:/olden_port_work/mv3_inpaint/`, and every call is logged in `meshy_live/INDEX.md`. Proof tier: generated
artifact (offline moderngl raster of the staged candidate). Nothing is bundled or installed, and the gameplay view
is unproven.

Method:
1. Step 1 (`mv3_step1.py`): build the rest-wide window and the outpaint.
2. Mask: find the side-view px that are wrong, build image 1 (view with grey holes) + image 2 (mask), exactly
   1536x864, with no full-painting reference.
3. Make the call (`mv3_meshy.py`, `MV3_PASS` picks the pass budget).
4. Register and gate (`mv3_register.py`: SIFT, drift, uncovered depth, building presence >= 0.75).
5. Deliver the result.
6. Do the right side conditioned on the delivered left.

#### Mask v1 vs mask v2

Mask v1 (state (a)) cut only the faces with 0 rest px. It kept depth-edge sheets, object and building sides, and the
4-texel mip guard, so most warping was never offered to the model.

Mask v2 (`mv3_mask2.py`, `mv3_v2.py mask`) marks a px as a hole when it is wrong, whatever object it belongs to:
- **warped:** M = J_pose · J_owner^-1. The px is a hole when σ1/σ2 >= 3 or σ1 >= 4 (strict). The loose 2 / 2.5
  thresholds flagged fine meadow. The owner model:
  - rest-projected bins: owned by the rest frame;
  - authored Meshy bins: the streak rule;
  - side bins: their own pose.
- **revealed:** a disocclusion, or a revealed px that repeats its rest occluder ("borrowed", low-pass dE < 10).

Only two exclusions apply:
- building fronts (rest-seen, not edge-on);
- px an earlier side fill already owns, when they are not warped.

Mask v2 sends a hole of 20.6% (left) / 21.7% (right) of the view, against 8.3% / 6.6% for v1. Overlay:
`meshy_live/BOARD_maskv2_masks.png` (red = sent hole, blue = deliverable, yellow = building front excluded).

#### Delivery v2 (texture + geometry)

The delivery writes no texel the rest frame samples, so it needs no mip guard. Every face with deliverable hole px
moves into a side bin `Mesh_MV3S<L|R>_<layer>`:
- UV = the side-pose screen projection;
- texture = the de-lit composite (neutral-rig albedo × composite / lossless).

Faces are handled by type:
- **Hidden at rest-wide:** moved.
- **Edge-on at rest (|cos| < 0.17, the depth-edge sheets):** subdivided into 3 levels. The sheet goes to the side
  bin. Each rest-seen sub-face gets a cap: its vertices are slid along their rest rays to the sub-face's nearest
  depth. That gives the same footprint and UVs, so the rest frame stays identical.
- **Straddling:** split, and the hidden sub-faces move.
- **Cloth:** never moved.

An in-memory rest simulation reverts any face that changes the rest-wide frame by more than 2 levels. It includes
the float32 local round trip.

Measured results:
- Left: 44k moved, 24k capped, 3.5k split, 687 reverted.
- Right: 23k moved, 10k capped, 2.1k split, 676 reverted.
- Rest frame and rest-wide window: max abs 2, 0 px > 2 (`restcheck`).

**Best-view reassignment** (`mv3_v2.py reassign`) is required after both sides are delivered. A face delivered by
the left and later seen from the right or from above shows the left texture stretched. Every visible-behind px of
the plain v2 state came from such faces (Mesh_MV3SL at sweep_right / high / fwd, 3,909 px).

The reassignment gives each side face the L or R texture with the lower streak cost over the 7 reachable poses. A
side is eligible only if its view sees >= 80% of the face. The result:
- 86,968 faces moved L -> R, and 4,291 moved R -> L;
- the cost fell from 398,731 to 183,639;
- the rest frame is unchanged.

#### Calls (pass `mv3_inpaint_maskv2_20261001`, cap 72 cr)

36 cr were spent, 36 are left.

| call | side | verdict |
|---|---|---|
| 09 | left, mask v2 | accepted (SIFT 1868 / 0.51 px, 17/17 buildings, known dE 7.29) |
| 10 | right, conditioned | refused by the gate: dock presence 0.667. The model repainted the pale smeared lake under the dock as saturated blue. |
| 11 | right, retry, prompt v2w | accepted (SIFT 1792 / 0.49 px, 17/17, dock 0.999, known dE 6.36) |

Prompt v2w = v2m plus "the lake, dock and non-grey shore keep their exact existing pale colours".

#### Warping px by cause (mask metric, sweep_left + right + high + fwd)

| cause | state (a) | v2 + reassign |
|---|---:|---:|
| c1 depth-edge sheet (grazing / straddle) | 446,547 (68.8%) | 16,982 |
| c5 rest-seen surface seen obliquely, env | 83,756 (12.9%) | 80,861 |
| c6 fill texture reprojected to another pose | 47,514 (7.3%) | 78,825 |
| c4 mip guard / no texture | 32,727 (5.0%) | 3,143 |
| c3 building hidden side | 17,509 (2.7%) | 1,057 |
| c2 object / prop / rock hidden side | 17,010 (2.6%) | 331 |
| c5 oblique, building | 4,350 (0.7%) | 3,229 |
| **total** | **649,413** | **184,428 (-71.6%)** |

Per pose (a) -> v2:
- left: 175k -> 43k;
- right: 265k -> 59k;
- high: 128k -> 52k;
- fwd: 81k -> 31k.

Cause overlays: `meshy_live/BOARD_maskv2_causes.png`. The board: `meshy_live/BOARD_final_maskv2*.png`, with seed,
(a) and v2 columns for the rest pose and the 4 sweeps.

#### Certificate `--loop 0`: visible-behind px / streak px

| pose | seed | (a) | v2 + reassign |
|---|---:|---:|---:|
| sweep_left | 1724 / 9113 | 642 / 7688 | 0 / 1502 |
| sweep_right | 1435 / 16004 | 99 / 8164 | 63 / 6451 |
| sweep_high | 298 / 4379 | 116 / 3386 | 170 / 3158 |
| sweep_fwd | 68 / 1596 | 20 / 1423 | 375 / 2493 |
| sum, max | 3525, 1724 | 877, 642 | 608, 375 |

No state passes. The v2 residuals are:
- Mesh_MV3SL faces at sweep_fwd / high that neither side sees well;
- the tbcsdw_6_2 body front.

The certificate's rest counts moved slightly: enclosed holes 707 -> 715, ground holes 0 -> 6. The mv3 raster's
rest-wide check shows max abs 2. This is unexplained; check it before the delivery is made permanent.

#### Cause 5: view-dependent proposal (`mv3_vdep.py`)

A texture-only delivery cannot fix a rest-seen surface viewed obliquely, because the rest frame samples the same
texels.

**Proposal.** Each surface keeps UV0 = its rest texture, so the rest pose is exact. It also samples the L and R
fills by projective lookup:
- the side camera VP matrices;
- the side depth maps for visibility;
- weights from the camera position, so the rest pose = the rest texture.

**Measured headroom** on the delivered v2 geometry (oracle = best visible source per px):
- 79.8% of the remaining warped px are fixable: 184,428 -> 37,191;
- a position blend gets 79.7%; a yaw-only blend gets 76.2%.

The board sweeps themselves are trivial, because they sit at the side cameras. At the in-between poses:
- sweep_high: 55.7%;
- sweep_fwd: 65.0% (yaw-only 43.8%, so position weighting is needed).

Blends: `mask2/vdep_<pose>.png`. They show some ghosting where L and R disagree.

**Runtime support today.** Lit bins are rebound to the city Hex / Lit donor: one `_MainTex`, Cull Back, base colour
only. Only `Fx_*` bins (`fxmesh`) keep their own bundle material and an optional `uv2`. A view-dependent shader would
therefore need:
- a plugin change to keep a custom material on lit env bins, plus 2 side textures, 2 VP matrices and 2 depth maps
  per bin;
- baked lighting.

This tier is a proposal; it is not built.

#### Lessons

1. Sunburst extends the real painting very well.
2. A full-painting reference gets copied instead of image 1 being edited. Send image 1 + mask only.
3. Name the fragile known objects in the prompt (cloud castle on its cloud, lake + dock). Call 10 shows that
   naming is not enough for a smeared known region next to them: also say that its non-grey colours stay.
4. A texture-only delivery needs a mip guard. Delivery v2 avoids the need: side bins own their texels.
5. A dropped face must be replaced by a fill, never by nothing. A cap or split keeps the rest frame identical.
6. Side fills don't fix building-front streaks. zs_v1's geometry repair does.
7. Most "smear trails" were rest-visible edge-on depth-edge sheets (c1, 69% of the warping), not hidden geometry.
   Cut them by grazing angle and cap them, not only by 0-rest-px.
8. Measure the mask by what is wrong at the pose (Jacobian vs the owner), not by what the rest frame shows.
9. Two side textures need best-view assignment per face. Otherwise the first side's grazing texture becomes the
   second side's streaks.
10. In-between poses (high, fwd) still lack a good source. The next lever is a view-dependent tier or a third fill
    pose, not more side-pose credits.

Reproduce:
```
python artifacts/homm3_methodology_v2/mv3_v2.py base | mask <pose> [cond] | send <pose> | composite <pose> <nn> | deliver <pose> <nn> | reassign
MV3_FILLED=v2 python artifacts/homm3_methodology_v2/mv3_mask2.py measure <label>
python artifacts/homm3_methodology_v2/mv3_vdep.py measure <left composite> <right composite>
python artifacts/homm3_methodology_v2/mv3_board.py masks | causes <labels> | final <label=dir>...
```

#### Fused texture per surface (2026-10-01, no credits, no shader / plugin change)

`artifacts/homm3_methodology_v2/mv3_fuse.py fuse`. One texture per surface. Each texel is a weighted blend of the
views that see it (rest, left fill, right fill).
- Weight = visible (depth test, in frame, painted by that view: its hole, or the bin's own side) × q^3, where
  q = σ2 of that view's px per texel.
- Ghosting: where L and R both see a texel, their q differ by less than 2x and CIELAB dE > 12, the sharper view
  wins outright.
- Rest-visible bins read at runtime LOD ≥ 1 take only zero-mean detail per 2^floor(LOD) block. Each block's
  integer sum is kept, so the rest mip texel stays the same. Bins read at LOD < 1 stay frozen: Back_Terrain,
  Houses, Outer*.
- Runtime caveat: env rows carry mipBias -0.5. Mesh_Terrain (2x the rest frame) is therefore read at LOD 0.5 and
  would be frozen. It was re-tiled at 4x into `Mesh_Terrain_T0/T1`. Each texel is replicated 2x2, and the tile rows
  are inserted at the original row so the draw order holds. The re-tile is rest-exact.
- Side bins are upsampled 2x.

Rest guard (`mv3_v2.restcheck`): max 2 levels, 0 px > 2. With mipBias emulated (`MV3_MIPBIAS=1`): max 1.

Measured on the 4 board poses. "v2b now" is v2b re-measured under the same code, with the owner-J grid cap.

| | v2b now | fused | vdep oracle |
|---|---:|---:|---:|
| warping px | 185,742 | 177,860 (−4.2%) | 37,191 |
| c6 fillReproj | 78,875 | 72,595 (−8.0%) | |
| c5 restOblique env | 82,110 | 80,881 (−1.5%) | |
| certificate visible-behind, sum of 4 sweeps | 608 | 188 | |
| certificate streak px, sum of 4 sweeps | 13,604 | 10,363 | |

Certificate visible-behind per pose, v2b → fused:

| pose | v2b | fused |
|---|---:|---:|
| sweep_left | 0 | 0 |
| sweep_right | 63 | 21 |
| sweep_high | 170 | 96 |
| sweep_fwd | 375 | 71 |

The certificate still fails: high has 96 bldg_front px, and holes grow at high (8748).

**Fusion does not remove c6, and removes almost none of c5.** Fusion can only redistribute data the views already
hold.
- c6 sits mostly at high and fwd (33k and 24k px). Neither side view sees those surfaces as densely as these poses
  do.
- c5 env sits at sweep_left and sweep_right (30k and 49k px), on rest-visible terrain. There the side views hold no
  painted data, only a re-render of the rest texture, so rest is the only real source.
- Both need new detail at a higher density, either from a fill pose at high/fwd or from a detail-only inpaint of
  the c5 terrain at the side poses. The block-mean split above then makes that detail safe for the rest frame.

The view-dependent tier's headroom, by contrast, comes from blending the existing fills per pose.

Disagreement: 615k texels have dE > 12 with both views seeing them well (`fuse/disagree_*.png`). Of those, 499k
were winner-take-all, mostly on terrain where both holes overlap and two independent Meshy calls painted different
content.

GPU: the per-texel work runs in torch CUDA (`--device cuda`, the default; it raises if there is no CUDA device). The
numpy reference stays behind `--device cpu`, with bilinear and Lab written out on both paths.
`mv3_fuse.py parity` covers a crop of Terrain_T0, TerrainNear_1 and MV3SL_environment and found 0 decision flips
and 0 differing texels. The full run's per-bin stats are identical on both devices.

| step | cpu | cuda |
|---|---:|---:|
| per-texel pass | 27.5 s | 1.0 s |
| per-face Jacobian | 8.0 s | 2.8 s |
| total (scene load and side renders are 27 s of each) | 77 s | 45 s |

Rest-count drift (enclosed holes 707 → 715, ground holes 0 → 6 at `default`) came from single-px T-junction
cracks. `deliver` split and capped faces, and the faces next to them kept the original edge. A fan-reseal of those
faces (`mv3_fuse.py seal`) made the rest frame worse (114 px > 2, cracks 710 → 714) and was rejected.

#### Edge-conforming subdivision in `deliver` (2026-10-01)

`mv3_v2.conform()` replaces the seal. Every point that `deliver` writes is a canonical lattice point (1/8
barycentric numerators). It is computed in prefab-local float64 from the face corners' position classes, summed in
class order, then cast to float32, so two faces that share an edge write bit-identical points on it.
- The side-sheet copies (in the side bins, same prefab) use the same points.
- Every unedited drawn neighbour in the same bin is closed over each edge it shares with an edited face. The closure
  inserts all 7 interior lattice points: an apex fan for one edge, a centroid fan for more.
- Caps stay flat per sub-face, as in v2b. A crack between two caps shows the sheet copy behind it.
- A first version slid cap points per vertex with pinning. It closed the cracks but cost side quality (sweep_left dE
  median 0.86 → 1.36) and was dropped.
- Faces that an earlier delivery appended are never edited again. One crack px came from R re-subdividing an L
  closure fan next to an L cap: R's sheet copy got lattice points that L's sheet copy does not have. The rule costs R
  9,288 faces of delivery.
- The sim guard now holds to step 1's rest frame instead of the current render, because two deliveries on one px
  had added up to 3 levels.
- `reassign` rewrites the side bins' local points as they are, with no world round trip.

Gate (certificate default pose): enclosed 707 and ground 0, back to the s1 baseline (v2b: 715 / 6). The rest guard
holds at max 2 (0 px > 2) after L, R, reassign, tile and fuse.

Side quality, achieved vs target:

| | L | R |
|---|---|---|
| v2b, dE median / p90 | 0.86 / 20.9 | 0.81 / 13.6 |
| conform, dE median / p90 | 0.86 / 20.95 | 0.86 / 17.4 |

GPU: the array math runs in torch CUDA by default, with the numpy reference behind `--device cpu`. Only elementwise,
correctly rounded ops are used. Division by a scalar is written as a reciprocal multiply, because torch CUDA does
that internally.
- `mv3_v2.py conform_parity <pose>`: all points, normals, UVs, source ids, drops, sheet points and blame sets are
  bit-identical.
- conform takes 14 s on CUDA and 15 s on CPU. The rest is the bins' I/O and the per-sub-face side-list bookkeeping
  in plan_faces.
- `deliver` takes about 2 min per side, mostly the rest simulation's rasters. Its remaining array steps (precompute,
  plan, simulate's set logic) are still numpy and are the next GPU port.

#### Fill views at sweep_high and sweep_fwd (2026-10-01, 24 cr)

Two sunburst calls (approach a: input + mask v2, prompt v2 adapted to the view). Both passed the `mv3_register`
gates on the first try:
- call 12, high: 1975 inliers, error 0.53 px, 17/17 buildings;
- call 13, fwd: 2036 inliers, error 0.68 px, 18/18 buildings.

They were fused as views H and F (owner codes 4 and 5) with L and R, through the same block-detail split. The rest
guard holds at 0 px > 2, and cpu/cuda parity passes with 4 views.

Warping px on the 4 board poses (`mv3_mask2 measure`; "c" = the conformed geometry):

| | v2b now | fused (v2b, L+R) | c, unfused | c, fused L+R | c, fused L+R+H+F |
|---|---:|---:|---:|---:|---:|
| warping px | 185,742 | 177,860 | 198,030 | 189,011 | 180,726 |
| c1 depthEdge | 16,989 | 16,653 | 26,285 | 24,994 | 23,220 |
| c5 restOblique env | 82,110 | 80,881 | 81,980 | 80,787 | 79,656 |
| c6 fillReproj | 78,875 | 72,595 | 81,628 | 75,131 | 70,946 |
| sweep_high | 52,336 | 48,503 | 57,526 | 53,266 | 49,183 |
| sweep_fwd | 31,617 | 29,826 | 33,831 | 31,924 | 28,889 |

Certificate visible-behind px per pose:

| pose | v2b | zs_fused | c, fused (2 or 4 views) |
|---|---:|---:|---:|
| sweep_left | 0 | 0 | 0 |
| sweep_right | 63 | 21 | 99 |
| sweep_high | 170 | 96 | 141 |
| sweep_fwd | 375 | 71 | 91 |

The certificate reads geometry and UVs only, so H/F content does not move it.

Reading:
- Adding H/F on the same geometry cuts warping by 8,285 px (−4.4%), c6 by 5.6%, sweep_high by 7.7% and sweep_fwd by
  9.5%.
- The conformed geometry costs about +11k warping px against zs_fused, mostly c1 at sweep_right and sweep_high. The
  same cost shows in the certificate (terrain_back behind px). Its likely source is the R faces left undelivered by
  the appended-face rule. A narrower rule (skip only appended faces that touch an earlier sheet copy) is the next
  step, after the deliver GPU port.
- The c5 terrain detail-only inpaint was not tried (measure first): c5 is still 79.7k px, 44% of what remains.

Proof tier: generated artifact (offline raster of the staged candidate). Nothing bundled or installed.

#### View-dependent shading prototype (`mv3_vshade.py`, 2026-10-01, offline, no credits)

The texture-only fusion plateaued: H/F bought 4.4%, and c5 cannot be fixed by one shared texture. The deliver / R-loss
work is parked, because Castle is being restaged from the houses lane. This prototype is the mv3 board renderer's
shading model. It is a moderngl GPU shader written to port to a Unity shader. No plugin change has been made.

Inputs, per town (not per surface):
- four projective view textures, `viewTex` (L, R, H, F): 1920x1080 RGBA8; rgb = de-lit albedo, a = painted mask;
- `viewDepth`: R32F camera-z for each view;
- the static view poses: `viewVP`, `viewPos`, `viewFwd`.

Per-frame work on the CPU:
- Pose weights are D_k = |pos − pos_k| + 20·|fwd − fwd_k| over {rest, L, R, H, F}, with w ∝ 1/D², normalised, and
  w = 1 exactly at a node.
- The top two fill views are bound to slots 0 and 1 (`viewW0/1`). The rest of the weight goes to `restW`.

Per fragment:
- Projective uv per slot, then a depth test (`texelFetch`, `zTol` 0.01).
- A quality factor q from the SVD of d(view px)/d(screen px), ramped by `magT` 4 and `anisoT` 3.
- a = w·painted·q, normalised against the rest pose's own quality (`restVP`):
  a_s /= restW·q_rest + a_0 + a_1.
- The colour uses the same block-detail rule as the fused texture: low(MainTex) + view − low(view), with low =
  `textureGrad` at 8 px.
- Derivatives are taken before any non-uniform branch.

Samples per fragment: 8 (MainTex ×2, and per slot depth ×1 and view ×2).

Checks:
- The rest pose is exact: 0 px differ, and the largest view weight is 4e-19.
- Parity at mid_LH:
  - shader vis×painted against the numpy reference agrees on clear px (H 1.0, L 0.99999);
  - the warp combine on cpu and cuda gives 0 mismatched px.
- Timing: the shader takes 0.18–0.23 s per pose, and the combine about 0.03 s. Measuring 10 poses takes about 5 min,
  dominated by the existing numpy `mv3_mask2.analyse` (not ported).

Measurement:
- warp mass = (1−a_0−a_1)·W_base + a_0·warp_0 + a_1·warp_1, where warp_k = is_warp(J_pose·J_k⁻¹) per face.
- A px counts as warping when the mass is ≥ 0.5, followed by the same area filter and rest window as `mv3_mask2`.
- The intermediate poses are midpoints with lerped pos and fwd (mid_LH, mid_HR, mid_RF, mid_FL, mid_restL,
  mid_restR).
- The view-dependent shading runs on the c_fused4 geometry and textures.

| warping px | zs_fused | c_fused4 | view-dep (additive) | view-dep (quality-normalised) |
|---|---:|---:|---:|---:|
| 4 board poses | 177,860 | 180,726 | 5,168 | **4,896** (−97%) |
| 6 intermediate poses | 201,308 | 205,738 | 145,034 | **54,333** (−74%) |

| pose | c_fused4 | view-dep |
|---|---:|---:|
| sweep_left / right / high / fwd | 43,051 / 59,603 / 49,183 / 28,889 | 924 / 2,208 / 1,511 / 253 |
| mid_LH / mid_HR / mid_RF | 19,101 / 71,958 / 65,626 | 15,185 / 2,430 / 7,332 |
| mid_FL / mid_restL / mid_restR | 18,322 / 11,809 / 18,922 | 13,098 / 7,863 / 8,425 |

Warping px by cause (zs_fused → view-dep):

| cause | board | intermediate |
|---|---|---|
| c1 depthEdge | 16,653 → 1,551 | 25,071 → 10,869 |
| c5 env | 80,881 → 468 | 30,649 → 1,323 |
| c5 bldg | 3,207 → 2,799 | 1,896 → 1,312 |
| c6 fillReproj | 72,595 → 78 | 137,043 → 36,761 |
| c2+c3+c4 | 4,524 → 0 | 6,649 → 4,068 |
| viewWarp | — → 0 | — → 0 |

Reading:
- The earlier oracle estimate was 37,191 board px (`mv3_vdep.py`, 3 maps, v2 era). The measured result with 4 views
  and the shader is 4,896.
- The additive blend failed between views: the weights spread over 5 nodes, so the mass stays below 0.5. Normalising
  by quality fixes that.
- The remaining intermediate px are mostly c6 and c1 at mid_LH, mid_FL and mid_restL. There the rest weight is high
  (0.28–0.40) and no view painted the px. More views, or a view whose pose is nearer to those midpoints, is the lever.
- By eye, a full-res crop at mid_RF shows less streaking than zs_fused. It also shows one new visible defect: a
  mottled, high-frequency band in the foreground terrain, where a view's detail term lands on a surface at a steep
  angle to that view. The warp metric does not count it, so view-dependent shading needs a by-eye gate as well as the
  px count.
- Board: `V:/olden_port_work/mv3_inpaint/meshy_live/BOARD_vshade.png` (zs_fused | c_fused4 | view-dependent, at the 4
  board poses plus mid_LH and mid_RF).

Runtime port cost (estimate; nothing built):
- VRAM per town:
  - 4 × (RGBA8 1920x1080 with mips, about 11 MB, plus R32F depth 8.3 MB) ≈ 78 MB;
  - with R16F depth, about 60 MB;
  - with BC7 colour and R16F depth, about 28 MB.
- Bundle: about 4 × (3 MB colour + 2–4 MB depth) ≈ 20–28 MB per town.
- The surface textures are unchanged.
- Shader: 8 samples per fragment, two SVDs (2x2, closed form) and one 4x4 transform per slot.
- The plugin must supply:
  - static: the 4 view poses (VP, pos, fwd), the view and depth textures, and `restVP`;
  - per frame: the camera pose, the 5 pose weights, the top-2 slot binding (texture + VP + pos + fwd + weight) and
    `restW`.
- The depth maps tie the views to the staged geometry. A restage (such as the coming houses-lane Castle) must re-render
  the depth maps and re-register the views. The painted masks are image-space and survive only if the
  rest-frame content is unchanged.

Proof tier: generated artifact (an offline moderngl raster of the staged candidate). There is no shader port, no
plugin change, and nothing bundled or installed.

Reproduce:
1. `python artifacts/homm3_methodology_v2/mv3_vshade.py prep`
2. `... measure vdep_c4 [--device cpu|cuda]`
3. `... base zs_fused` (with the `fuse/owner_zsf` owner maps)
4. `... parity`
5. `... board ...`

#### View-dependent shading, round 2: GPU measure, mottle gate, dense sweep (2026-10-01, offline, no credits)

**`mv3_mask2.analyse` on the GPU** (`mv3_mask2_gpu.py`, torch CUDA float64; the numpy `analyse` is still the
reference):
- Speed: 15–19 s per pose became 0.16–0.24 s.
  - The reference spent half its time recomputing world points once per fused owner bin (about 50 times per pose).
  - It spent another 4 s building `filled_px` textures it then threw away. That function now returns early when
    there is no filled set, with the same result.
- What runs where:
  - On the GPU: one world-point pass; the face Jacobians; `cap_grid` in closed form (torch's batched 2x2 SVD took
    0.2 s per call); one gather over all the owner maps concatenated; and the borrowed Lab / blur / remap test.
  - On the CPU: `scipy.ndimage.label` for the area filter (about 20 ms, sequential).
- Parity on the 4 board poses (`mv3_mask2_gpu.py parity`):
  - warp, owner and reveal px are exact, and no faces needed re-deciding;
  - W differs by at most 64 px (0.13%) per pose. The cause is the borrowed test: OpenCV's float Lab uses a
    spline-tabulated gamma, and `cv2.remap` uses fixed-point weights.
  - The gate is 0.2% of W.
- A 22-pose `mv3_vshade measure` now takes 19–24 s on a free GPU. While another agent held the card at 99%, the same
  run took 110–130 s.

**Mottle metric** (`mottle()`, torch, with a parity run on cpu vs cuda):
- A px mottles where three things hold:
  - the blend weight flickers: box15(|a − box5(a)|) > 0.12, with a = a0 + a1;
  - the render has more high-frequency luminance energy than the plain render at the same pose:
    E_v > 2·E_plain + (3/255)², with hf = lum − box5(lum) and E = box15(hf²);
  - a ≥ 0.05.
- Then the MIN_AREA filter.
- View detail delivered through a smooth weight does not count.

**Dense sweep: 22 poses.**
- Each loop edge L→H→R→F→L is sampled at t = 0, .25, .5, .75.
- rest→L and rest→R are sampled at .25, .5, .75.

**Root cause of the band.** At mid_RF the band's px alternate between `Mesh_Terrain_T1` and the delivered
`Mesh_MV3SL_environment` sheet (about 7k px each in a 200x100 window): the two surfaces z-fight. Their rest-quality
terms differ, so the quality-normalised weight `a = w q / (restW·q_rest + Σ a)` stripes face by face. q, vis and
painted were all 1 there.

Variants tried (all keep the rest pose exact: 0 px differ):

| change | effect |
|---|---|
| soft depth test (`textureGather` 2x2 PCF + slope tolerance) | no change in mottle |
| quality from the interpolated geometry (`qexact`: G from the two VP matrices along a tangent basis) | no change in mottle |
| the bins' vertex normals | unusable: they are shading normals (median \|cos\| to the face normal about 0.7) |
| baked smooth geometric normals (one extra vertex channel), plus neighbour smoothing | no change in mottle |
| grazing-angle attenuation on a | +warp, little mottle change |
| feathered painted mask, clamp(2 x low-passed alpha) | board warp 4.9k → 1.3k |
| **rest term restW·0.25 in place of restW·q_rest** (surface-agnostic) | removes the stripes |
| smooth slots: w_k − w_3rd | removes the slot pop |

Chosen default `ef_k25` = PCF + qexact + feather + restK 0.25 + smooth slots:

| 22 poses (vs c_fused4 plain) | plain warp | v0 warp / mottle | ef_k25 warp / mottle |
|---|---:|---:|---:|
| 4 board | 180,704 | 4,896 / 38,565 | **1,264 / 29,185** |
| 6 mids | 205,676 | 54,289 / 11,846 | 67,071 / **919** |
| all 22 | 873,169 | 142,015 / 87,690 | 154,542 / **47,727** |
| mid_RF | 65,618 | 7,329 / 3,745 | 6,712 / **263** |

Reading:
- The weight flicker at mid_RF is gone (mottle −93%).
- The band's remaining texture is the R/F views' own painted content under magnification. Most of the rest is the
  z-fight, which the houses-lane restage changes.
- Costs:
  - Mids warp is +24% against v0. Smooth slots lower the second view's weight.
  - At 3-way ties the views get almost no weight: mid_LH stays at the plain 19,098, the worst intermediate pose for
    warp.
  - At the H and F nodes, mottle rises from 3.4k / 3.6k to 9.7k / 10.1k. Feathering pulls view detail into the hole
    mask's fine patchwork. By eye it is mostly added detail, plus frayed stall-roof edges.
- The worst intermediate pose for mottle is d_restL_75 at 4,163.

**Continuity.** The per-frame weights, sampled along every edge:
- hard top-2 jumps by 0.23 at default→sweep_right t ≈ 0.5, whatever the sampling (a pop);
- smooth slots step by 0.0387 / 0.0194 / 0.0097 / 0.0048 at 100 / 200 / 400 / 800 steps, so the step halves with
  the sampling and the weights are continuous.

**Checks for `ef_k25`** (`parity_ef_k25.json`):
- shader vis × painted against numpy on clear px: 1.0 for R and 1.0 for F;
- the cpu row (numpy mask2) against the cuda row at mid_RF: Wbase 65,626 / 65,618, Wvdep 6,715 / 6,712, mottle
  263 / 263 with 0 px different.

**Board.** `V:/olden_port_work/mv3_inpaint/meshy_live/BOARD_vshade_crops.png`: full-res 800x400 crops. The columns
are plain | v0 | v0 mottle | ef_k25 | ef_k25 mottle. The rows are mid_RF at the band, d_restL_75, sweep_fwd and
mid_LH.

**Runtime cost update.** Still 8 samples per fragment: `GatherRed` on depth replaces the `texelFetch`. New
requirements:
- one baked vertex channel (smooth geometric normal);
- uniforms `poseVP` and `restK`;
- `restVP` is no longer needed when restK > 0;
- `textureGather` needs GLSL `GL_ARB_texture_gather` or HLSL SM 4.1.

Proof tier: generated artifact (offline raster). Nothing bundled or installed.

#### Per-face view selection (PARKED 2026-10-01, partial)

The user approved a different direction (main session): view-dependent shading may read as the camera fading
between views. Instead, each face gets ONE authoritative view, chosen once from rest and the generated views, and
that choice is baked into the ordinary textures. This needs no plugin change.

The lane was parked mid-measure. Castle zs_v6 was accepted by eye, and the GPU was needed for the all-faction
rollout. The lane is parked, not abandoned.

**Code.** `artifacts/homm3_methodology_v2/mv3_facesel.py`, in the style of MVS-Texturing (Waechter et al. 2014).
The module doc gives the exact rule.
- Labels: rest, L, R, H, F, plus the c5 detail views c5L and c5R.
- Data term per face: area × (1 − min(q, 1) · cos · vis), infeasible below a vis of 0.6.
  - q is σ2, the view's px per texel.
  - cos is the grazing angle.
  - vis is the share of the face's texels that the view paints after the depth test.
  - Rest gets a bonus of 0.05 × area.
- Pairwise term on welded interior edges: edge length × λ × (1 + ΔE/10), where ΔE is the CIELAB distance between
  what the two views paint at three points on the edge.
- Solver: parallel ICM on a Luby independent set with a fixed random priority, so the energy never rises. It has a
  numpy twin.
- Bake:
  - rest-visible texels take zero-mean detail through `mv3_fuse.block_detail_t` (block means are rest's mip texels);
  - hidden faces take their view outright, but only 8B texels clear of every texel the rest frame samples (a
    barycentric UV from each rest px);
  - side bins are free;
  - seam levelling is a global per-view gain plus a feather of a 9-texel box on the label one-hot.
- Everything runs in torch, with `--device cpu` as the reference.
- `parity` (cpu vs cuda, plus the numpy solver) is written but **was not run** before the lane was parked.

**c5 detail inpaint** (pass `mv3_c5_detail_20261001`: 2 of the 4 allowed calls, 24 of 48 cr).
- Calls 14 (sweep_left) and 15 (sweep_right) were sunburst calls on the c5 env masks of c_fused4: 30,020 and 47,773
  px. The prompt was detail continuation (`c5/prompt_c5_detail.txt`).
- Both passed the mv3_register gates:
  - call 14: 3,563 inliers, 0.57 px, 18/18 buildings;
  - call 15: 4,262 inliers, 0.49 px, 17/17 buildings.
- Both are logged in INDEX.md.
- The selection almost never picks them: 116 and 19 faces. Most c5 faces are hidden at rest, and H, F or R sees them
  with a better q·cos. So the c5 views change little under this data term.

**Selection on state_c** (`facesel/select_{c5,noc5}_cuda.json`).
- 1.20M faces and 3.35M interior edges.
- Faces by label: rest 279k, L 446k, R 412k, H 46k, F 21k.
- Seam edges: 1.37M with the data term alone, 370k after the solve. λ from 0.5 to 8 leaves the seams unchanged. 780k
  faces have exactly one feasible label, so the remaining seams are visibility boundaries.
- Rest guard: 0 px > 2 (max 2).
- The mipBias check shows 7 px > 2. That count is identical on state_c and c_fused4 themselves, so the baseline
  carries it.
- About 2 min per run. Most of that is FuseCtx view loading (45 s) plus c5 views (20 s). Solve 4–6 s, bake 5–8 s on
  cuda.

**Measured: selection without c5, 22 poses** (`facesel/measure_fs_noc5.json`). W is mv3_mask2 inside the rest frame.

| set | plain c_fused4 | ef_k25 view-dependent | per-face selection (no c5) |
|---|---:|---:|---:|
| board (4) | 180,704 | 1,264 | 171,572 |
| mids (6) | 205,676 | 67,071 | 182,681 |
| all 22 | 873,169 | 154,542 | 772,330 (−11.5%) |
| mid_RF | 65,618 | 6,712 | 59,694 |
| mid_LH | 19,098 | — | 18,995 |

- The selection is a single texture, so it removes about 11% of the warp. View-dependent shading removes about 82%.
  This is the c5 limit noted above: a rest-visible surface keeps rest's low frequency at every pose.
- Mottle for a static texture uses `mv3_vshade.mottle` with a = 1 where the px's owner is a view, against the plain
  c_fused4 render: 2,831 px over the 22 poses. This is not the same quantity as ef_k25's 47,727.
- Seams (new metric): px pairs on one bin whose owner view differs, on the 3x3-blurred render. The mean ΔE across
  seams exceeds the other pairs by 0.086. 8,483 of 276,903 seam pairs step by more than ΔE 12.
- **No seam baseline was measured** for c_fused4 or ef_k25.

**Not done.**
- The measure of the selection with c5, of plain c_fused4 under the static measure (W area-filtered, seam), of
  ef_k25's seams, and of zs_fused at 22 poses. The chain is in the log `facesel/m_fs_noc5.log`, and the commands are
  `measure <label> <ownerDir> [ef]`.
- `parity`.
- The 3-column board (`board`).
- Snapshots state_fs_* were dropped. The selection rebuilds from state_c with
  `python mv3_facesel.py select [--no-c5]`. The stage is back on state_c_fused4.

Proof tier: generated artifact (offline raster). Nothing bundled or installed.

### Recipe v2: ground contact, and the houses-lane carve pit (2026-10-01)

The user on Castle `zs_v5` in game: cottages float, and their meshes do not line up with their textures. Two
causes were measured.
- Mesh_Houses side walls and skirts that the rest camera never saw are textured with stretched rest paint. The
  certificate counted stretch only on revealed px. Recipe v2 adds the unseen-face term, repaired by rule `planar`.
- The houses lane's silhouette carve leaves a pit under every footprint. The ring's push-pull depth is dominated by
  the far terrain around a silhouette (cottage 2 at 38 m stood over terrain at 66 to 77 m, a 5.6 m gap).

Ground contact (`town_full3d_ground_contact.py`, `--device cuda` by default, a cpu reference, and the parity test
`test_town_ground_contact_gpu.py`):
- The term: a ray straight down from each piece's lowest points onto every ground bin. The gate is 0.15 m.
- Anchoring order: a piece slide (scale about the rest camera), then a ground fill (hidden ground slides along its
  own rays to the base plane), then fail closed. Rest identity must be 0 px in all 32 tree states.
- An "apron" stage (raising visible ground along its rays to a cone around the footprint) and a "ground push" stage
  were prototyped for cottage 6 and rejected: the best result was a 2.04 m gap at a 73.7 deg slope. On the pitted
  terrain, the visible ground right under cottage 6 is a near-vertical wall 0.7 m behind its base and 4.4 m lower.
  No rest-preserving move puts ground under its base.

The fix is at the source, in `town_full3d_houses.group_ground`:
- The carve's depth is capped where each px's rest ray meets the base plane of the model drawn there. The base
  heights are stored per label in silhouettes.npz (`B<label>`, `N<label>`); run `town_full3d_houses.py silhouettes`.
- Where models overlap, the cap uses the farther model's base. With the highest base instead, longhouse 6 buried
  longhouse 5 by 1.5 m.
- The cap is grown CARVE_DILATE px into uncovered px only.

Pit audit (Castle, max pit below base in the foot window, before → after): longhouse 3 3.13 → 0.0, longhouse 4
4.67 → 0.0, longhouse 7 0.39 → 0.0, cottage 3 0.02 → 0.0. The other instances never had a pit. 26,870 frame px
changed.

**Delivered terrain does not reproduce from current lane code.** Castle `props_v1`, restaged on 2026-10-01 with the
pit cap disabled, differs from its own delivered terrain (staged 2026-09-29):
- TerrainNear_1: 13,958 vertices move by up to 0.9 m;
- TerrainNear_0: 891 vertices move by up to 0.05 m;
- Mesh_Terrain: 87 more vertices, and 599k albedo texels change by more than 8 levels;
- the stage report's `field.extSkyline` changes (bins 204 → 206, farCellsCapped 999 → 1244, edgeRamp raisedColumns
  48 → 38).

Candidate causes, not bisected: the terrain depth commits since then. These are the da_large `background_depth` pin
with monotone/envelope conditioning (6c3509c590), and the depth-conditioning hooks in `rect_depth` (3b14192c5a,
9a88beff0d). They feed the outer field's skyline fit and the frame normals that de-light the albedo. So a delivered
scene cannot be regenerated from current code. A full restage would carry this drift into everything anchored to
the terrain: building contact depth, cloth, props and the mv3 fills.

**Carve delta** (`town_full3d_carve_delta.py`), the default for the other towns' pit fixes unless a town is being
restaged anyway:
- Stage the seed's terrain twice with today's code, the fix off (`before`) and on (`after`).
- Unlayer the delivered candidate (`town_full3d_ldi.py unlayer`).
- Carry only what the fix changes. A moved vertex is scaled along its own rest ray by |after| / |before| (its rest px
  is kept) and takes the after normal. A changed texel takes the after texel.
- Everything else stays bit-identical. It fails closed on a topology or uv mismatch, a vertex off its ray, or a
  candidate still layered.
- The recipe then runs the LDI (`ldi.fromPreLdi` false).

**The cap is not enough: the foot check.** The first `zs_v6` build failed ground contact on house 6 (longhouse 3) with a
4.00 m gap after the LDI, with the cap on or off. Down its column the carve ends at the base row, capped at the base
plane (h -2.4 m, depth 44 m), and the painted px right below it is terrain at depth 67 m, h -7.5 m. The model stood
4.4 m over the painted ground in front of it. The cause was the label, not the carve. The hand label box
(`castle/houses/house_labels.py`) ended at y 612, through the painted lower wall, and the tex prop mask misses that
wall too. The fit's ground ring then took the wall px below the box as "ground" and put the base at the box bottom.
Longhouse 4 was the same: the box ended at y 585, and its base was 7 m over the grass at depth 45 m instead of 74 m.

`town_full3d_houses.foot_contact` is now a fail-closed step of `fit`. `stage` refuses a group set without a passing
`foot_contact.json` pinned to the current placement of every group; `town_full3d_houses.py foot` records one.
- Sample: every bottom-edge px of a placed silhouette whose FOOT_ROW_PX = 4 px below are covered by no silhouette
  and no label of any group, in the painted rect, not sky.
- Compare the painted terrain's camera depth there with the depth where that px's rest ray meets the base plane of
  the instance drawn at the edge px (`B<label>`, so split pairs are judged per part).
- An instance floats when more than FOOT_FLOAT_MAX = 0.25 of its edge px have a ratio above 1 + FOOT_TOL (0.08).
  With fewer than FOOT_MIN_PX = 8 edge px the foot is hidden: recorded, not judged.
- A ratio below 1 (something nearer under the edge) is recorded as `buriedShare`, not judged.
- Vectorised numpy over the edge px only (tens to hundreds per instance). There is no raster or per-frame-px filter
  to port.
- On Castle before the relabel: longhouse 3 and 4 had floatShare 1.0 (ratio 1.60 / 1.98). Every other judged
  instance had floatShare 0.

The fit's ground ring also excludes manifest `propMask` px now, so an unlabelled wall or chimney next to the foot
can't fit the plane. Castle relabel (`house_labels.py` v6):
- Longhouse 3's box reaches y 629 and longhouse 4's y 601.
- `FOOT_ADD` polygons give each house the wall px the prop mask misses. They are painted after every box, so
  longhouse 7 no longer takes longhouse 4's wall.
- Labels 3 and 4 were refitted (`fit --labels 3,4`) and both pass the foot check:
  - longhouse 3: base -8.75 m, depth 75 m, IoU 0.814, contact 1.0;
  - longhouse 4: base -7.80 m, IoU 0.764, contact 0.84.
- The pre-change labels and placement are kept in `V:/olden_port_work/castle_restage/houses_backup/`.

Castle seed `carve_v1`:
- rx_ldi_zone_old_nfix3_cloth, with Mesh_Houses restaged from the new placement. Mesh_Houses was byte-identical
  across the lineage (props_v1 to nfix3_cloth), so no later edit is lost.
- Unlayered, then the delta. `before` is carve_repro (old labels, cap off); `after` is carve_fixstage (new labels
  and fit, cap on).
- Moved: Mesh_Terrain 14,017 vertices / 424k texels; TerrainNear_0 949 vertices; TerrainNear_1 1,352 vertices.
- Buildings, cloth, props, periphery and sky are untouched.

**Rule planar per uv chart.** The second `zs_v6` build passed ground contact (ANCHOR pass, 3 pieces moved) but then
failed repair. Griffin Tower's cloth bin `Mesh_Cloth_tbcsdw_5_2_b0` had unseen faces, and its uv is not one affine
map of rest px (162 texels off). A cloth bin packs crops of two source bins into one atlas.
- Rule planar now fits one map per uv chart (`town_full3d_step_flap.uv_affine_charts`). A chart is linked by shared
  vertices and by identical uv (the coincident corners of a triangle soup); two packed crops never share a uv.
- A face takes the map of the rest-shown face nearest to it in rest px: the paint around where it stands, from the
  chart that paints there. An unseen face's own chart may hold no rest px at all (`Mesh_Body_tbcsdock`'s Meshy
  back-fill charts, third zs_v6 build).
- Only a chart whose uv is a rest projection has a map. A Meshy body's mirrored back-fill chart, which the rest
  raster still reaches at the silhouette (`Mesh_Body_tbcsdw_6`, 31.8 texels off), has none. Such charts are recorded
  per round (`planarNonAffineCharts`). The rule fails closed when no chart of the bin has a map.
- `Stage.planar` takes per-face maps. Parity: `test_town_ground_contact_gpu.py` adds a per-face case; the unit test
  is in `test_town_full3d_step_flap.py`.
- This is also the per-chart uv the Fortress flap needs.

Ground contact before the LDI: every house has gap <= 0 except house 9 (longhouse 6, at the rect bottom), which has
no ground under it, as in the seed. The gate measures it after the LDI, in every state.

Per-town pit worklist (every town that went through the houses lane):
- **Castle**: silhouette carve. The cap applies, carried as `carve_v1` into `zs_v6`.
- **Stronghold**: `houses_v33`, label carve, single dir. The cap does not apply on that path, because the single
  label dir keeps the original byte-identical code. Next steps: measure the installed scene with the GPU
  ground-contact term (re-measure the scrub and boulder bins per instance). If it pits, extend the cap to the label
  carve and carry it with the carve delta.
  - Foot audit (dry run, scratch silhouettes, terrain of `tex_sdgrade_v34_winding`): 33 labels; **label 14 floats**
    (floatShare 0.92, ratio 1.17 at 49 edge px). Every other judged label has floatShare 0.
  - `stage` now refuses houses_v33 until it has a passing `foot_contact.json`. Fix label 14 (label or fit) before
    any Stronghold houses restage. Not fixed yet.
- No other town has a houses dir.

Proof tier: generated artifact.

**zs_v6 result, and what the certificate missed.** The third `zs_v6` build passed every v2 term: 32 states,
unseen-face 0, ground contact, facesPlanar 5,534, binsSha `b04bc6a2`. On the board, a shrub prop (Meshy `shrub`,
instance 0) stood in front of the refitted longhouse 3 at rest, about 1,700 px of green over the painted roof and wall.
No term caught it, for three reasons:
- Rest identity compares the rest face ids before and after anchoring. It never compares what is drawn with the
  painting.
- The props lane's `check` let each instance show up to 600 px at rest. It also counted visibility with the staged
  `Mesh_Prop_*` bins as occluders. Those bins are the instances themselves, so each placed copy lost the depth tie to
  its own staged copy and counted ~0 px: shrub 0 counted 211 px, and 2,555 px after the fix.
- The props were placed against the old houses, where longhouse 3 hid shrub 0, and nothing re-checked them after the
  houses restage.

The same per-state measurement shows that zs_v5 had a defect of its own. Shrub 3 is hidden by the tavern upgrade in
the full state, but with the tavern unbuilt (`start`, `anim`) it covers the painted cottages at the left edge: 2,924
px at rest. zs_v5's v1 recipe measured only three states and no rest colour.

Fixes, all fail closed:
- **Rest-paint term** (`town_full3d_recipe.rest_paint`, in the v2 gate and in `final`; `rest-paint` command).
  - Per build state, the rest albedo of the staged bins is compared with that state's HoMM3 painting, inside the
    painted rect.
  - The comparison uses chromaticity: the albedo is the painting de-lit by a grey shade, which leaves chromaticity
    unchanged.
  - A px differs when a channel is more than 8 % off (`REST_PAINT_CHROMA`; both px have an rgb sum above 60). The term
    fails on a 3x3-opened component of 400 px or more (`REST_PAINT_AREA`).
  - Calibration: zs_v5's full state peaks at 260 px (house edges and the orb glow, which is registration noise). The
    shrubs give 1,694 px (zs_v6 full) and 2,288 px (zs_v5 anim), so both candidates fail it.
  - Runtime: 51 s for 32 states on Castle.
- **Props check per build state** (`town_t2_props.check`). It takes the worst state per instance and leaves the
  staged props out of the occluders.
- **Props re-check in the houses stage.** `town_full3d_houses.stage` fails closed while the props check fails. The
  remedy is `town_t2_props.py replace` or `drop`.
- **Cloth vertex colours.** `Stage.card` / `Stage.planar` append vertices. Rule planar on two Griffin Tower cloth bins
  left their `.vcol` short (3,447 colours for 3,498 vertices), and the Unity bundle build refused it. `Stage` now
  carries `.vcol` with the vertices and re-pins the stage report's cloth block on write. The zs_v6 bundle was
  repaired one-off: each new vertex takes the colour of its exact-position source vertex, which is unambiguous. Only
  `clothLook` changed in the catalog; the bins sha is the same.

Seed `carve_v2` = carve_v1's chain plus props 0 and 3 re-placed. The houses stage's props re-check failed them, and
`replace` re-picked both with 0 px at rest in every state. `zs_v7` is zs_v6's recipe on that seed.

**zs_v7 → zs_v8: sprite ground decals (2026-10-02).** zs_v7 passed every term except rest-paint. It failed in three
early states:
- `min_tbcscas2` / `min_tbcscas3`: 1,290 px. The Citadel sprite paints the river at frame x 1356-1440. The residual
  covers part of it; the rest falls through to the grass terrain.
- `min_tbcsdw_5`: 887 px. Nothing draws the Griffin Tower's wooden structure, so Back_Terrain shows.

These coverage gaps are in the building seed and are byte-identical since zs_v5. No streak rule can see them. zs_v7
was installed with them (coordinator, 2026-10-02; install decision read start/full/anim).

The generic fix is `town_full3d_sprite_decal.py`, the optional v2 recipe step `"decal": {}`. Per building layer:
- **Which px.** Px the environment draws at rest (environment plus that layer alone) where the layer's sprite covers
  the frame (alpha > 0.5) and the environment's albedo differs in chromaticity from the painting of the layer over
  the bare background. The thresholds are the rest-paint term's own (8 %, sum 60), opened 3x3 and dilated 2 px
  inside the alpha.
- **Geometry.** Faces through the px centres, on the environment surface each rest ray meets, moved toward the camera
  along that ray by 0.4 % per level. The rest px are kept, and at a pose the paint moves with the ground under it.
  - Levels separate overlapping decals of layers that some build state shows together. Upgrades are never shown
    together, so they share level 1.
  - A quad whose corners differ in depth by more than 5 % is skipped and counted (`DEPTH_JUMP`). No decal face spans
    a depth step.
- **Albedo.** The painting times the environment's de-lighting ratio at that px. The ratio is clamped and smoothed.
- **Where it lives.** One `Mesh_Decal_<layer>` bin in the layer's prefab, so it shows only when the layer is built.
  Building depth measures it as a ray bin (residual: flap and seam-guard treat it like `Mesh_BodyRest`).
- **When it runs.** In `_finish`, after the backstop and before the repair rounds, so the rounds certify the new
  faces.

Castle results:
- A read-only probe on zs_v7 put 22 decals in the stage (largest: tbcscas2, 3,160 px). The rest-paint maximum fell
  from 1,290 px to 368 px in every state. The 368 px is the pre-existing start-state terrain patch at (667, 657),
  which zs_v7 also had.
- `zs_v8` = zs_v7's recipe plus `"decal": {}`. The rounds converged at round 2. Rest-paint passes all 32 states (max
  368 px). PASS, binsSha `529c440d`.
- Proof tier: generated artifact. Lit look: the albedo of the river decal is brighter than the residual's next to it,
  because the two shades differ. At rest the lit result should match the painting, but that is unchecked in Unity.
  It is in the in-game check row.

**Houses fit: the foot slide (2026-10-02).** Stronghold houses_v33 label 14 floated: ratio 1.18 on 92 % of its 49
edge px. Its label box holds the whole painted hut. The ground plane fitted around the foot runs above a hillside
that falls toward the camera, so the plane, not the label, put the base 18 % too near.
- `fit` now scales such an instance about the rest camera by its median foot ratio. Base and scale are both multiplied
  by k, so every rest px is kept and the base meets the painted ground under its edge.
- It applies only to labels the fit refitted, only for ratios within `FOOT_SLIDE_MAX` 1.5, and only when the scale
  stays in the manifest range. Anything else stays failing, because a label that cuts the painted house needs a new
  label.
- Label 14: slide x1.178, then contact 0.938 and ratio p50 1.000. The record is in `houses_v36`, the copy of
  houses_v33 used from now on.

**Shared-tool changes, 2026-10-02 (methodology lead, from the town agents' requests).**
- **Decal role** (66ca9fd125). `Mesh_Decal_<lid>` has its own building-depth role, `decal`. It is measured for span
  like `ray`, but it gets no building seam and no flap (`town_full3d_building_seams` skips it, as it skips cloth).
  Before this, zs_v8's decals counted as `ray` residual seams and failed the scene3d seam check.
- **Rule flap is per chart** (a691220b95). Residual bins that pack several crops into one atlas have no single
  rest px -> uv map: Cove and Necropolis zs_v1 were 256 / 713 texels off one map.
  - Flap builds one map per chart (`town_full3d_step_flap.uv_affine_charts`) over the rest-shown faces. Each flap
    vertex takes the map of its lip vertex's chart.
  - A vertex of a chart with no map takes the nearest mapped vertex's map in rest px, as rule planar does.
  - Card and planar carry the per-vertex map index with the faces they copy.
  - A bin with no affine chart fails closed and is named. Non-affine charts are recorded under
    `repair.flap.nonAffineCharts`.
- **Certificate extraPoses** (0f17104f0f). `certificate.extraPoses` takes any pose that `final` measures:
  `loop_*`, `cursor_cN`, `free_*` and `transition_NNN`, resolved from `reachable_cams_full`. An unknown name fails
  closed.
- **Rest-paint smoke / flame exclusion** (an exclusion class decided by the coordinator, not a threshold change).
  - Why: a plume is a DEF animation that the scene draws as a particle emitter, not as staged albedo. The painting's
    frame-0 plume therefore differs from the rest albedo by construction.
  - What is skipped (`REST_PAINT_FX_*`, pinned by `validate_town_zero_streak_contract.py`):
    - only the DEF-changed px, using `town_full3d_fx`'s own effect mask (rects, exclude, colour), dilated 2 px;
    - only for an effect of kind `smoke` or `flame` (fire). The fx lane has no steam kind: steam is classified as
      smoke;
    - only on a layer present in the state;
    - only when that effect's emitter (the `Fx_Smoke_<k>_*` / `Fx_Flame_<k>_*` particle group) is staged in the
      layer's prefab. Without the emitter, the px still count.
  - Fail closed: per state and layer, the build stops when the layer's exclusion exceeds 6,000 px or 25 % of its
    sprite px, whichever is smaller (frame px). The first cap was 1,500 px. The coordinator raised it after Factory's
    measurement (below): the per-layer share and the staged-emitter requirement are the guard.
  - Reporting: `rest_paint.byState[state]` records `fxExcludedPx`, plus per layer the px, the share, the emitters and
    any effect whose emitter is missing. The gate print, the `final` result (`fxExcludedByState`) and the `rest-paint`
    command list the excluded px per layer for every state.
  - Per-layer override: only for layers the coordinator approves by name. Each entry in
    `REST_PAINT_FX_SHARE_APPROVED` carries a share, a pxCap and a reason. An entry without all three fails at import.
    - For that layer only, the entry's share and pxCap replace the 25 % share and the 6,000 px cap. The
      staged-emitter requirement still applies.
    - A recipe names the override as `"restPaint": {"fxShareOverride": {"<layer>": {"share", "why"}}}`.
      `load_recipe` refuses a layer that isn't in the table, or a share above the entry's.
    - The report names the overridden layer and its excluded px for every state.
    - 2026-10-02 approvals:
      - Bulwark's great pyre `tbbumr01`: 40 %, 8,000 px. It needs 6,122 of its 17,913 sprite px (34 %).
      - Necropolis' Cover of Darkness `tbncspec`: 40 %, 21,000 px. It needs 20,055 of its 57,152 sprite px (35 %).
  - First measurement, Factory zs_v1 (read-only probe; all numbers in frame px, x1.8):
    - The exclusion removes the plume components: tbfaup_3 1,002 px, tbfablak 531 / 454 px.
    - tbfablak's mask is 5,909 px (19.8 % of its sprite): its effect has no rects, so the whole DEF counts.
      tbfaup_3's mask is 3,558 px, and the tavern plume's 672 px. The painted plume components alone add up to
      1,987 px in state full, so no mask fits a 1,500 px cap. Narrowing the masks would also re-fit the emitters.
    - Separately, min_tbfacas2 still fails at 539 px on `Mesh_Body_tbfacas2`. That component is not smoke.
- **Ground contact: extensionDrop** (opt-in, recipe `"groundContact": {"extensionDrop": true}`; coordinator
  decision 2026-10-02).
  - The case: Stronghold zs_v1 has 26 Mesh_Near_scrub pieces (vanilla Dead_thorns in the synthesized frame
    extension) at 0.15-0.59 m.
    - The piece slide changes 1-20 rest px per state: depth order against neighbouring dressing.
    - The ground fill moves nothing, because the ground under a sparse thorn bush is visible through it at rest.
  - The rule: an `EXT_DROP` piece (`Mesh_Near_*`) that both moves fail on, and whose every vertex projects outside
    the painted rect before and after, drops straight down by its gap.
    - It is kept only with 0 px change inside the painted rect in every build state.
    - The px it changes in the extension, which has no painting to keep, are recorded as `restPxOutsideRect`.
    - The frames the rest checks compare with are rebased on the drop.
    - The recipe re-checks the painted rect against the pre-anchor frames at the end.
  - Root-cause follow-up (worklist, not done): the nearfield placer (`stronghold_full3d_nearfield.candidates`)
    puts each base on `field.height`, not on the staged ground mesh. Placing on the staged ground removes the gaps
    at the source.
- **The LDI cut can strand props** (Necropolis, acd34). A prop placed on terrain that the LDI back-layer cut later
  moves keeps its old ground. The props check after staging is what catches it. Re-run props `replace` after any
  change to an LDI cut.
- **Ground contact: removeHidden** (recipe `"groundContact": {"removeHidden": [{"bin", "piece", "verts", "why"}]}`;
  coordinator decision 2026-10-02, option (a), no gate change).
  - The case: Stronghold zs_v1, houses_v36 `Mesh_Houses` piece 0 (9,807 verts). The houses placer put it 9-14 m
    underground in the left hill, with no terrain under its low points. The contact gate counts it `unsupported`,
    and there is no ground to anchor it to.
  - Measured read-only before removal: 0 px at the rest camera and at 169 reachable poses (all 48 sweep samples,
    final's cursor / free / transition poses) in all 29 build states.
  - The rule (`town_full3d_ground_contact.remove_hidden`):
    - The entry names the bin, the piece number and its vertex count. The count is an identity pin: a restage that
      renumbers or reshapes the pieces fails instead of removing another piece.
    - Before anything is removed, the environment alone is rastered at rest and at every sweep sample plus final's
      poses plus the recipe's. A state only adds layers, and a depth-tested raster can only hide px when geometry is
      added, so 0 px over the environment alone means 0 px in every state.
    - Any px fails closed. The anchoring step that follows still requires 0 rest px changed in every state.
    - The result records `removedHidden`.
  - Root-cause follow-up (worklist): the houses placer (`town_full3d_houses`) placed a house 9-14 m under the
    staged terrain. A placer check that refuses a house with no ground under its foot would stop this at the source.
- **Periphery settle** (recipe `"peripherySettle": {"pieces": [Mesh_Outer..], "why"}`, v2, opt-in;
  `town_full3d_recipe.periphery_settle`, step 2a of `_finish`; Dungeon zs_v4 2026-10-02).
  - The case: Dungeon zs_v1 put `Mesh_OuterL1` into the LDI, which refused it: its uv is the periphery's world-space
    polar chart (one chart, 690 px off an affine map of rest px, 96 % of its vertices off the frame). The LDI is a
    rest-frame method and the refusal is correct. zs_v2 (Terrain-only LDI) failed closed in the repair on two OuterL1
    cards at frame x 0-7. They are rest-degenerate slivers (rest anisotropy 16-19, s1 6.2-6.9 px per texel), and a
    card of a sliver is still a streak.
  - Root cause: the polar sheets were drawn in front of the staged frame surface at rest in 7,416 px (OuterL1 5,555
    px at x 0-21, down to 0.69 x the frame's depth; also OuterC1 / L0 / L2 / R1). The periphery's own contract
    (`stronghold_full3d_periphery.settle`, `frameIntrusions` 0) holds against the terrain it was built on, not
    against the later terrain. The seed props_v2 already had it (1,829 px at x < 8).
  - The rule: the periphery's settle rule against the staged frame surface (every environment bin that is neither
    `Mesh_Outer*` nor the backstop, z-buffered at rest). An intrusion is a listed piece's px nearer than that surface
    or over no frame surface. Each round moves the vertices of the intruding faces back along their own rest rays,
    to PUSH_REL / PUSH_ABS behind the farthest frame surface (3x3-conservative) over the px the face intrudes at.
    1/z is affine on screen, so a face whose vertices are all behind a depth is behind it everywhere. The rest px
    of every vertex is kept; uv and normals are untouched.
    - It fails closed on a sky intrusion (no settle depth), on any intrusion left after 8 rounds, and on a round
      that moves nothing.
    - Every v2 build records `periphery.measured` (the intrusion px of all `Mesh_Outer*` bins after the step), so
      other towns can see whether they need it.
  - Dungeon: 4 rounds, 347 vertices moved, 7,832 -> 0 px. The repair then drops the settled faces that streak (the
    backstop is behind them). The last Meshy prop (mushrooms) had stood half off the left edge on OuterL1's
    intrusion, with no ground under it once the sheet sat behind the frame. Seed props_v3 drops it (0 props left).
    zs_v4 = that seed plus `peripherySettle` over the eight polar sheets plus `decal`. PASS: certificate, ground
    contact, and rest-paint in every state (max 257 px).
- **Ground-hole term: restSky refinement** (coordinator decision 2026-10-02; `town_full3d_zero_streak.ground_split`,
  with the GPU path in `town_gpu_kernels.CertifyEngine._ground_split`).
  - The case: Inferno zs_v1. 99 % of its ground holes are px whose floor-plane hit point projects onto an undrawn rest
    px: the painting's own sky past the painted horizon, where the floor plane runs on to the far cap. The rest frame
    has 30,643 such px, so the growth term measured motion of the sky line, not missing ground.
  - The term now splits each pose's ground holes:
    - **restSky** is the hit point landing on an undrawn rest px. It is excluded only where the pose raster of the
      static Sky_ bins (`load_sky`: kind sky, unposed) covers the px. That is the explicit check that the pose render
      shows the skybox there and not the clear colour. Without coverage, or when no `sky` is passed, the px still
      counts (fail closed).
    - **hidden** is a rest surface standing in front of the hit point: unknown ground behind an occluder. It always
      counts, so `groundHoleGrowthPx == 0` still holds for it.
  - Each pose row reports `groundRestSkyPx` (excluded), `groundHiddenPx` and `groundRestSkyUncoveredPx` (both
    counted). The summary carries their maxima and `groundSkyChecked`.
  - The recipe's repair-round and gate certificates pass the staged Sky_ bins. The cloth lane's relative
    certificates do not, and keep the unrefined term.
- **Worklist: Inferno T2 layers are not marked meshy in the stage report** (found 2026-10-02 by the parity test's
  rest_seams case on inferno zs_v1: "buildingDepth: tbinblak: piece Mesh_BodyM_tbinblak has no contact_v1 role
  (meshy=False)").
  - `inferno_t2_integrate.stage` stages `Mesh_Body_<l>` + `Mesh_BodyM_<l>` + `Mesh_Body_<l>_skirt` on 24 layers. It
    writes only `t2_report.json`. Castle and Factory also set `stage_report.buildings[lid].method = "meshy_t2"`, so
    `is_meshy` is true there.
  - Today this does not block Inferno: its catalog pins no buildingDepth, and the recipe's seam_guard and
    residual_bins skip rows that are not meshy. Only rest_seams (the parity test, and a future contact_v1 pin) reaches
    the refusal.
  - The fix, when Inferno is next restaged: mark the rows `meshy_t2`, and give `Mesh_Body_<l>_skirt` a role in
    `building_depth.piece_role`'s meshy branch (today only the non-meshy branch accepts it, as solid). Do not skip the
    case.
  - **Done 2026-10-02 (inferno lane).** `inferno_t2_integrate.stage` now marks its layers through `mark_meshy`.
    `inferno_t2_buildings.py mark-meshy [--layers]` marks a candidate staged before the fix, which is every layer of
    its `t2_report.json`. It fails closed on a layer without a t2 row, a stage-report row or a staged `Mesh_Body_<l>`,
    and on a row with another method. `piece_role`'s meshy branch now takes `Mesh_Body_<l>_skirt` as solid.
    - The recipe's build does not change. Inferno has no ray-role bins, so `residual_bins` stays empty, and
      `seamAware` is off.
- **Ground-hole term: the background frame** (coordinator decision 2026-10-02: a general correctness fix of the term,
  not a named exception; `town_full3d_zero_streak.ground_split` / `env_frame_faces`, GPU
  `town_gpu_kernels.CertifyEngine._ground_split`).
  - The case: Inferno zs_v2, which is zs_v1 rebuilt on main and stopped at repair round 0. Ground-hole growth was
    479 px in start, 8522 in full, 7665 in anim and up to 5529 in the min_ states.
  - Every `groundHidden` px was split by what the environment-only rest frame has at the hit point's rest px q:
    - full sweep_left: 8522 = 8299 with the environment undrawn at q + 223 behind an environment ridge;
    - sweep_right: 8305 = 8230 + 75;
    - min_tbinext1 sweep_left: 4347 = 3889 + 458.
  - For every px of the first class, some build state shows q as undrawn sky at rest. Inferno's far mountains are
    painted on Sky_Dome, and the environment has no geometry in that band. Only the building in front made the term
    call it hidden.
  - A HoMM3 building is a sprite over the background painting. Where the background frame is sky at q, the painting
    has sky behind the building, so a pose ray past it that shows the dome is faithful. Ground placed there would put
    fake lava in front of the painted mountains.
  - The rule:
    - The background frame is every `environment/` bin except the backstop class: no `Mesh_Backstop`, no floor fill
      (those are hidden fill, not painting), and no building layer. It is rendered from the same rest camera.
    - A hit point whose q the background frame leaves undrawn, while the state's frame draws it, is `restSkyEnv`. It
      is excluded only where the pose's Sky_ raster covers the px (fail closed). With sky passed and no environment
      bin staged, the certificate refuses to run.
    - `hidden` is the background frame drawn at q plus a rest surface in front of the hit point. It always counts.
    - Each pose row adds `groundRestSkyEnvPx`. The summary adds `maxGroundRestSkyEnvPx`.
  - Verdicts unchanged on the installed, user-approved scenes (main vs the fork, the recipe's own cams, cuda): Castle
    zs_v8 start (23 poses) and Factory zs_v1 full (45 poses) both pass. Every pose's ground row is identical, with
    `groundRestSkyEnvPx` 0. `test_town_gpu_kernels.py` parity is OK on its default cases.
- **Backstop: the floor fill** (recipe `"backstop": {"groundFloor": true}`, v2, opt-in;
  `town_full3d_recipe.floor_fill` / `rest_cover`).
  - The case: the real ridge holes left after the background frame (Inferno start: 458 px at sweep_left, 479 at
    loop_396). 98 % of their hit points land 0-11 px under the top edge of the coverage. There the Lipschitz sheet is
    pulled toward infinity next to the painting's sky, and the pose ray passes between the ridge and the sheet.
  - The fill is the painted floor plane, staged in the backstop bin with the backstop's uv, so the same content step
    fills its texels.
    - A px is valid when every build state covers it at rest (GPU raster per state) and the floor point on its
      centre's ray lies `FLOOR_FILL_BEHIND` (1.05) x behind the farthest rest surface of any state, within the far
      cap plus the cams' reach (the largest rest-to-pose camera displacement over the build's and `final`'s cams;
      Inferno 400 + 18.0 m). The certificate counts ground up to the far cap from the pose camera, so by the
      triangle inequality its hit points lie within that distance of the rest camera. The first zs_v3 run used a
      fixed 1.02 x 400 = 408 m and failed the gate on 28 px at sweep_fwd: hit points at 397 m from the pose, 411 m
      from the rest camera.
    - The kept px are the valid px within `FLOOR_FILL_BAND_PX` (16) of an invalid one, each as its px square. The
      square's vertices sit on the px corners, shared between neighbours, so the fill is watertight. At rest each
      square contains exactly one px centre, its own.
    - The outer boundary corners move `FLOOR_FILL_EPS_PX` (0.05) outward, along the sum of (corner - square centre)
      over the kept squares at that corner. A pose ray whose floor hit lies on the boundary edge would otherwise be
      lost to the raster's tie rule. The first zs_v3 run had 3 such single px (q within 0.002 px of the edge, at
      loop_000, loop_036 and loop_324). Each square still holds no other px centre at rest.
    - Hidden at rest is true by construction and is also checked: a fill face drawn at rest in any state fails the
      build.
  - A first version, the backstop's 4 px grid with an eroded window, left 73 / 168 px: the cells at the very edge.
    The px squares leave 0 / 0 (debug on the staged candidate, start state).
  - The sky-side prune keeps fill faces that are ground for some certified pose: a vertex within the far cap of a
    build or `final` camera (`fill_ground_faces`, torch cdist on cuda with a numpy reference; parity in
    `test_town_full3d_floor_fill.py`). The content step fills every fill square's texel. The prune only sees the
    build's cams, so a fill square past the far cap for every build pose that meets it was removed, while a closer
    `final` pose needs it. Inferno zs_v3 run 2 passed the build gate and failed `final` with 120 px of hidden ground
    at loop_060 and 62 at transition_011, all on removed fill squares. With the unpruned fill those poses read 0.
  - One rule for every ground-bearing prune keep (Dungeon, 2026-10-02): `_finish` builds the certified pose set once
    (`cert_cams`: the build's cams plus `reachable_cams_full(sc, FINAL_LOOP)`). The fill's keep reads it, and so does
    the backstop sheet's. A backstop triangle that a ground ray of a certified pose the build does not see meets is
    kept (`ground_ray_px`: the per-pose mask of rays meeting the painted floor plane inside the far cap, torch on cuda
    with a numpy reference, parity in `test_town_full3d_prune_ground.py`; `final_ground_tris`: one raster context per
    state, run only when the cycle has prune candidates). The case: Dungeon zs_v7 and zs_v8 passed the build and
    failed `final` on 1-2 px of hidden ground at 6, then 8 other poses. Each was a 1 px slit between
    `Mesh_Back_Terrain` columns onto a backstop triangle the prune had removed, because only sky rays of the build's
    cams met it. Adding the failing poses to `extraPoses` moved the slits to poses the build did not see. It only
    keeps more (a tightening). PRUNE rows report `finalPoses`, `secondsBuildCams` and `secondsTotal`.
  - `certificate.extraPoses: "final"` (v2, opt-in, `cert_cams_of`): the build's cams are `final`'s own pose set
    (`reachable_cams_full(sc, FINAL_LOOP)`, 157 poses) from the start. The repair rounds, the backstop, the prune and
    the build gate then see every pose `final` judges, and the prune's extra ground pass is empty. Dungeon zs_v9
    (2026-10-02, host shared with 4-5 other builds): build gate PASS over 157 poses x 32 states (behind, unseen and
    ground-hole growth 0 in every state), `_finish` 10,549 s against zs_v8's 4,079 s with a 43-pose loop (2.6x).
    That is about 14 min per repair round and 25-28 min per prune cycle (3 cycles). The build replaces the
    build -> final -> extraPoses -> rebuild loop (zs_v5 to zs_v8: four rebuilds, each failing `final` on new poses).
    It stays opt-in (coordinator 2026-10-02: 2.6x is over the ~2x bar for a default). Follow-up, not measured: the
    loop's cams for the repair rounds, with `final`'s set only for the prune and the build gate.
  - The fill extends `FLOOR_FILL_EXT_PX` (16, capped by the backstop's texture margin: 4 px at Inferno) past the rest
    frame, with the frame edge's cover and zmax replicated outward. A floor hit that projects outside the rest frame
    always counts as a ground hole. Nothing draws there at rest, so the fill stays hidden. zs_v3 run 3 had 5 such px
    at loop_240, 0.1-2.4 px left of the frame, between Mesh_OuterL2 and the backstop.
  - Result, Inferno zs_v3 (recipe `inferno_zs_v3.json`, 29 build poses; bins 197ed9e4): the build gate passes, and
    so does `final`, 157 poses x 32 states with every term 0. The fill: 127,827 squares, 377 of them off-frame;
    254,623 of 255,654 faces are ground for some pose. Rest paint, ground contact and `validate_town_scene3d_contract`
    pass. Generated artifact only; the installed scene is unchanged until the coordinator installs it.
- **Props `replace --dropped`: the batched GPU search** (`town_t2_props.py`; coordinator 2026-10-02: "batch the
  candidate scoring and snap on the GPU ... with a --device cpu parity check"; a prop with no valid spot is reported
  and left out, never forced).
  - Every candidate is drawn first (the per-candidate loop's draws, in its order). One `Ground.gap` lookup then snaps
    all of them, chunked at `SNAP_CHUNK_PTS` under the VRAM cap. The gap is pointwise, so chunking changes no bit.
    60,000 candidates take about 5 s on cuda; the CPU loop took about 5 min per prop.
  - `--parity` first compares the lifted-foot gaps of `PARITY_CANDS` draws bit for bit (cpu per candidate against
    the cuda batch), then the snapped candidates and pick's answer. Any difference fails closed. On Stronghold
    sh_carve_v1, all 999,000 gap points were equal, 998,960 of them finite.
  - The snap measures from the foot points lifted by the instance height. `Ground.gap` only counts surfaces up to
    0.5 m above a point, so an uphill foot point under the slope read as no ground: 59,999 of 60,000 cones
    candidates were refused as `noGround` before the fix.
  - Result on Stronghold sh_carve_v1 (houses_v36 terrain), a negative: 18 of 18 dropped props have no valid spot
    (17 cones, 1 butte). `steepFooting` refuses about 99.6 % of the candidates. Over 3,000 draws, the median ground
    span under the foot is 0.86x the prop's height for cones and 1.0x for butte. Only 0.33 % of cones draws are at or
    below 0.25x, and none at or below the 0.15x `SNAP_SINK_MAX`. The ratio does not depend on scale (foot span and
    height scale together), so the fix is flatter ground or a narrower-footed prop, not a smaller one. Each dropped
    entry records its `search` block (cands, refusals by reason, device, seconds).
  - Rock-embed trial (coordinator follow-up 2026-10-02; `replace --dropped --rock-embed --dry-run`, opt-in, writes
    nothing). For the props in `ROCK_FORMATIONS` only (natural rock, never built structures), the uphill side may be
    buried up to `ROCK_EMBED_MAX` (0.5) of the height. The downhill foot still rests on the ground, so nothing floats.
    On Stronghold sh_carve_v1:
    - At 0.5: about 3,200 cones candidates per prop snap. The best gain of every one of them is negative (-196 to
      -241 px), because the spots where a cone fits cover building px rather than streak targets. 0 of 18 place, and
      butte still has no candidate.
    - At 0.75 (a one-off measurement, not the constant): 2 of 18 place, two cones with gains 1,112 and 487 px,
      buried three quarters on the uphill side.
    - Not adopted. zs_v2 ships with all 18 dropped.
- **Sprite decals skip the fx-drawn px** (Factory zs_v2, 2026-10-02). `"decal": {}` laid the painted smoke plumes of
  tbfablak (1,749 px) and tbfaup_3 (1,339 px) on the environment as ground paint, but the scene draws that paint as
  Fx. The decal step now takes rest-paint's own exclusion masks (`rest_paint_fx_masks`: a layer's smoke and flame
  whose emitter is staged) and removes them from the layer's decal px. The report gives `fxExcludedPx` per layer.
  The rule is pinned in `validate_town_zero_streak_contract.py`. Proof: source/static only, until Factory is
  rebuilt.
- **Rest paint: `restPaint.knownGaps`** (coordinator decision 2026-10-02; recipe
  `"restPaint": {"knownGaps": [{"state", "layer", "maxPx", "why"}]}`).
  - The case: Factory zs_v1 passes every term except rest-paint in `min_tbfacas2`. That is one 539 px component, a
    spire of the Meshy T2 cas2 body (`Mesh_Body_tbfacas2`) where the painting has sky. The same gap is in the
    installed pb_v1. Build and final blocked on it, although start, full and anim pass.
  - The rule:
    - The coordinator approves each entry by name, per town, in `REST_PAINT_KNOWN_GAPS_APPROVED`
      ({(faction, state): {layer, maxPx, reason}}). Only `min_` states are eligible. maxPx is the measured figure
      plus at most 10 %. Today the only entry is Factory `min_tbfacas2`, `tbfacas2`, 590 px.
    - `load_recipe` refuses an entry that is not approved, a non-`min_` state, another layer, maxPx above the
      approval, a missing reason, or a duplicate.
    - `apply_known_gaps`: the named state passes only when every component of `REST_PAINT_AREA` px or more is
      listed, is at most maxPx, and is drawn mostly by the entry's layer. Any other state, a bigger component, or
      another layer's component still fails.
    - The state records `knownGap` (`applied`, `within`). The result's and final's rest-paint blocks carry
      `knownGaps`.
  - Unit tests: `test_town_full3d_known_gaps.py`, run by `validate_town_zero_streak_contract.py`, which also pins the
    approved table.

- **restOwner: rest ownership of Meshy T2 bodies** (opt-in, recipe `"restOwner": {"layers": [..], "why"}`; Fortress
  zs_v2, 2026-10-02; `town_full3d_recipe.rest_owner`).
  - The case: Fortress zs_v2 passed the certificate, ground contact and prune, and failed rest-paint in five states.
    A read-only `rest-paint` run on the seeds gave the same components on ssr_v1 and props_drop_v1, so these are
    seed defects. Dropping the props cleared 24 of the 30 states ssr_v1 fails (of 31); props_drop_v1 fails 6.
    - `min_tbfrdw_0_2`: 2,067 px, and `min_tbfrdw_2`: 768 + 246 px. The Meshy body is drawn outside its own sprite,
      where the painting shows mist and trees. Meshy completed geometry that the sprite never had, painted with
      flat extrapolated colour.
    - `full`: 404 + 367 px of tbfrcstl_3's wall drawn in front of tbfrhrd2. The painting's positions z order draws
      the horde building over the wall.
    - Terrain components in `full`, `min_tbfrholy` and `min_tbfrhrd2` (1,432 / 555 px). The existing `"decal": {}`
      step handles these.
  - Relation to `paintOrder` (Cove): that cut drops a body face in front of a later layer only when every state that
    builds the body also builds such a layer. tbfrcstl_3's faces are shown by `min_tbfrcstl_3`, so paintOrder keeps
    them. restOwner moves them back instead, and it also handles faces outside the layer's own sprite.
  - The rule. It runs per build state that shows a listed layer A.
    - A px is misowned when all of these hold:
      - it is inside the painted rect;
      - the rest-paint term counts it as differing (chroma, min sum, 3x3 open);
      - A draws it;
      - the painting's owner there is not A. The owner is the sprites composited in z order, alpha > 0.5; A's own
        px are grown 2 px.
    - Outside A's own sprite (grown 2 px), the face is dropped. It is not part of the HoMM3 building in any state.
    - Under a later layer B, A's vertices of the face go back along their own rest rays behind B's rest surface,
      using the 3x3-conservative depth and the periphery's PUSH_REL / PUSH_ABS. This keeps rest px and uv in every
      state. A px where B has no surface is counted (noOwnerSurfacePx) and left to the rest-paint term.
    - The step runs before ground contact, so anchoring and every later term see the settled bodies.
    - It stops at a fixed point, or after 3 rounds with no new minimum, and reports the residue. It fails closed at
      40 rounds, or when a listed layer is in no build state.
  - Fortress zs_v2: misowned px went from 6,382 to 252 (plateau at round 27). Faces dropped: tbfrdw_0_2 3,832,
    tbfrdw_2 1,788, tbfrcstl_3 421. Vertices pushed: tbfrcstl_3 9,352, tbfrdw_2 787.
  - Proof tier: generated artifact.
  - Result: zs_v2 = this step plus `"decal": {}` plus `repair.rounds` 12. The pushed tbfrcstl_3 faces converge at
    round 12. PASS: certificate, ground contact, and rest-paint in every state (max 341 px), measured on the fork
    before the merge.

- **Worklist: fold restOwner and paintOrder into one step** (coordinator, 2026-10-02; restOwner landed in
  `2131fd1bdc`). Both steps decide who owns a rest px by paint order. One problem should have one solution.
  - When: after both Cove and Fortress have shipped.
  - The single step: restOwner's push-back along rest rays, plus paintOrder's all-states drop rule (drop a face
    only when every state that builds the body also builds the covering layer).
  - Proof: re-run Cove's and Fortress's rest-paint. The results must be unchanged or better.

## Recommendation: the new default recipe

These statements supersede earlier rules:
- The certificate (`town_zero_streak.v1`, reachable loop + forward dolly, visible components on revealed px) is the
  acceptance. It supersedes 3-pose streak px and back-anisotropy p99 as the acceptance metric. Those stay as
  diagnostics.
- The view-set bound plus card fallback supersedes LDI's 1.25 ratio cap and ANISO_CUT as the depth rule for back
  layers. The ratio cap is kept only as the validator floor.
- A hole is never filled with the smear (`keep_holes` off in the default) once a content fill exists (pilot 3). Until
  then, the trade is explicit per town: streak, or hole.
- A joint layout solve (pilot 2) supersedes contact_v1 + `order_pass` pulls. The seam lane's body_v1 residual rule is
  kept inside it.
- The rx_layer card variant is identified as the "discrete layers" cause on the terrain side. The building side is the
  seam lane. Neither card terrain nor MPI is a default.
- A declarative recipe per town supersedes forked candidates. Cove and Fortress must be rebuilt from a recipe that
  names contact_v1 (the ssr_dfix lane is the hand-made version of that).
- MeshCollider picking (the pick lane) stays. Sky on the dome only (the sky lane) stays.

What the default covers once pilots 2 and 3 land:
- terrain sheets (A);
- back layers (A + cards);
- building fronts and residual (A face rule + G);
- disocclusion content (C fill).

What it does not cover yet:
- posed / Fx bins and alpha cut-outs, which the certificate does not draw;
- runtime proof.

## Reproduce

```sh
# certificate on any staged candidate
TOWN_FULL3D_FACTION=castle TOWN_FULL3D_CANDIDATE=rx_ldi_zone_old \
  python tools/homm3_town_scene_meshes/town_full3d_zero_streak.py --loop 12 --save-worst 2 --out <dir>
# pilot 1
TOWN_FULL3D_FACTION=castle TOWN_FULL3D_CANDIDATE=props_v1 \
  python artifacts/homm3_methodology_v2/pilot_vlb.py --variant vlbcard_zone_nokeep --out <dir>
# pilots 1+2(+3 geometry) in memory, certificate-driven repair
TOWN_FULL3D_FACTION=cove TOWN_FULL3D_CANDIDATE=ssr_dfix   python artifacts/homm3_methodology_v2/pilot_combo.py --pieces Mesh_Terrain --backstop --rounds 8 --out <dir>
# pilot 3 content review (in memory)
TOWN_FULL3D_FACTION=castle TOWN_FULL3D_CANDIDATE=props_v1   python artifacts/homm3_methodology_v2/pilot_fill.py --ground-src-m 1.0 --combo <combo dir> --out <dir>
# option H: build / verify a recipe candidate (fresh candidate; fails closed unless the certificate passes)
python tools/homm3_town_scene_meshes/town_full3d_recipe.py build  tools/homm3_town_scene_meshes/recipes/castle_zs_v1.json
python tools/homm3_town_scene_meshes/town_full3d_recipe.py verify tools/homm3_town_scene_meshes/recipes/castle_zs_v1.json
python tools/validate_town_zero_streak_contract.py
```
