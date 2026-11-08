# Handoff: per-keyframe combined-score repair (goblin)

Date: 2026-09-18. Prior thread: `537a2e6b`. Commit with this session's work: `bba26bd23d`.
Update (same day, continued): repair completed twice, result is null — see Repair result below.
Measurement caveat (same day, verified by probe): the null holds for the current scorer, but the
scorer is detail-starved — see Measurement limits. Do NOT read this as proof the bind is optimal.

## Original brief (unchanged)

Take the currently deployed Stronghold unit animations; for each keyframe, repair mesh/bind for a
combined silhouette + DINOv2 score.

Hard constraints (do not relitigate): the mocap pipeline contract forbids image scores from
redefining motion or bind for delivery. Generated-artifact-only experiment. Design settled:
per-keyframe combined scoring drives a shared weight + rest repair, motion frozen. Nothing here
touches the shipped payload or the game install.

## What this session finished (committed in `bba26bd23d`, extended after)

1. **Camera question ANSWERED — it was a registration artifact, not bad meshes.**
   - The audit's `_register_camera_from_idle` was grid-only (no local refine despite the policy
     name `bounded_y_up_idle_alpha_grid_then_local_refine`): it fit scale + offset from bbox
     extents with zero translation search, leaving a ~9px vertical gap on goblin idle
     (grid IoU ~0.31 vs ~0.70 achievable; oracle shift `(-2, +10)`px at res 192).
   - Yaw 210 / pitch 30 is a genuine sharp peak (verified by full yaw/pitch IoU curve), so
     orientation was right and only translation was missing.
   - Also fixed two mapping bugs: square-pad offset (`center_plate` divided by `(W,H)` instead
     of accounting for the 25px pad) and pixel-center convention (`(RES-1)` corner mapping vs
     resize's center mapping).
   - Fix: two-stage refine — wide integer-shift scan (dx ±8, dy 0..+16, y-down only) at grid
     orientation/scale, then the `skin_camera_registration`-style bounded box (±5° yaw/pitch,
     scale ×{0.97,1.0,1.03}, offset ±2%). Budget pinned by test: 96 + 243 + 289 + 243 = 871 evals.
   - Proven on CPU before any CUDA: idle IoU **0.3077 → 0.6991** at yaw 210 / pitch 30.
2. **Goblin audit re-baselined** (on disk, git-ignored):
   `artifacts/homm3_mocap_v2/keyframe_combined_repair_v1/audit/h3_goblin/audit.json` —
   mean combined **0.626 → 0.729** (sil 0.253→0.462, chroma 0.682→0.777, dino ~0.949, 61 frames).
   Death-frame silhouette zeros are gone; worst is now Death f8 sil 0.011 (genuine prone pose).
3. **Repair runner fixed, then run twice — result is null (see Repair result).**
   - `repair_weights` takes `joint_slots [V,S]` and expands slot-packed rows to the dense `[V,J]`
     matrix `deform()` contracts (scatter-add, not matmul — slots can share a joint).
   - `field.penalty()` called with no args (passing expanded weights tripped the shape check).
   - Weld-divergent deployed rows (1463/3251 coincident groups on goblin, max drift ~0.04)
     reconciled by position-group averaging; drift recorded as
     `report.weightContract.weldReconcileMaxDrift`. Before/after blend compares the reconciled
     field (raw-GLB replay parity is the audit's job, noted in code).
   - Post-handoff diagnosis: the first completed run fit with the DINO term **detached**
     (`dino.encode` under `no_grad` — readout varied 0.07–0.13 as a passenger while
     photo+geometry drove). Fix: `encode_differentiable` (on-device normalize, grad-preserving,
     chunked by `dino_batch`) + rotating per-step frame shard (`dino_shard_indices`, photo stays
     full-batch). Steered run shows DINO 0.108→0.073 by step 100; later per-shard readout jumps
     are shard rotation working, not divergence.
   - Rescoring window fix: `rescale_bbox_to_working_canvas` maps the source-canvas union bbox to
     the working-resolution canvas (pinned by test with the exact failing coords). Re-verified:
     rescoring `before` reproduces `audit.json` per frame (corr 0.9994, max diff 0.0067).
4. **Contract tests pass** — 10 tests (5 original + evaluation-budget pin + shard coverage,
   normalize-grad, validate-flag parity, bbox-rescale pins). `pytest` is NOT in
   the venv; tests were run by direct import. Do not "fix" this by adding pytest unasked.

## Repair result (goblin, 150 iters, fixed code, 2026-09-18)

`artifacts/homm3_mocap_v2/keyframe_combined_repair_v1/h3_goblin/report.json`:
beforeMean 0.7283 → **afterMean 0.7295** (meanDelta +0.0012, improvedFraction ~0.74,
max|frame delta| 0.010). The pre-fix run converged to the same +0.0012, so the null is
robust across both fits, not an artifact of the detached DINO term.
**Reading (weakened — see Measurement limits): under the current scorer the shared
weight+rest repair shows no headroom.** This does NOT prove the deployed bind is optimal;
it proves this measurement cannot resolve any improvement.
Open hypothesis, deliberately not chased: DINO is ~1% of the objective magnitude
(photo×10 ≈ 5.8, surface×3 ≈ 14, dino×2 ≈ 0.2), so the fit is photo/geometry-dominated.
Testing a rebalanced objective is a new experiment design, not a continuation.

## Measurement limits (verified by render probe, 2026-09-18)

- The GIF is faithful, not a downscale bug: tiles are native-192 rasterizer output pasted
  without resize. It looks crude because the renders ARE crude.
- Subject size: posed idle render covers **0.68% of the 192px frame (~249 silhouette px,
  ~16×32px window)**. The camera frames the whole 450×400 plate, not the unit.
- Shading: render RGB is ~black (inside-silhouette p90 ≈ 0.3/255) while the albedo texture
  is healthy (2048² RGBA, mean 91.5) — the rasterizer applies ~zero light. The GIF's black
  blob is real pipeline output, not a display bug.
- What each term actually sees: silhouette → 249px alpha shape (works, and IS sensitive);
  chroma → hue of near-black pixels (noise-dominated, weak); DINO → 39×39 white-composited
  shape upscaled to 224 (shape-only, zero surface detail — its 0.93 baseline says
  "goblin-shaped blob matches", nothing finer).
- Orientation is NOT the problem: the mesh is posed (LBS idle) and registered (IoU 0.699).
  The odd look is viewpoint (side/back 3D view vs frontal sprite), which registration absorbs.
- Consequence: sub-pixel weight changes cannot move these scores — the +0.001 null may be a
  measurement-resolution artifact. To close the case either way needs: (a) renderer lighting
  (or unlit albedo shading), (b) tighter unit framing and/or higher working resolution, then
  re-baseline + re-run. That is a new experiment, not a continuation.

## Wood elf probe (2026-09-19, same pipeline, no scaffold changes)

Rationale: goblin is a clean mesh; wood elf was suspected damaged. Input staged locally
(git-ignored): 9 `Unit_*.glb` copied from
`remaining_idle0_ingame_v1/units/h3_wood_elf/` to `stronghold_oe_approved_v1/units/h3_wood_elf/`
(`Unit_ShootFront.glb` exists but is outside the pipeline's clip order, ignored).
Separate out root: `keyframe_combined_repair_woodelf_v1/` (audit + repair).

- Audit (192, 61 frames): meanScore **0.691** (sil 0.405, chroma 0.709, dino 0.960).
  Camera sane, no goblin-style registration disaster: grid IoU 0.541 → refined **0.596**
  at yaw 150 / pitch 25. Worst frames concentrate in Death f1–f4 (sil 0.0005–0.23) and
  AttackFront f4–f6 (sil 0.08–0.16), DINO high throughout (0.91–0.96).
- Repair (150 iters, fixed DINO-grad code): beforeMean 0.6906 → afterMean **0.6934**
  (+0.0028, improvedFraction 0.71, max|frame delta| 0.013). The worst frames did not move:
  Death f4 sil 0.001→0.001 (score 0.357→0.352); AttackFront worst +0.01 silhouette.
  Fit itself moved (surface 6.46→2.45) while the score stayed flat.
- Reading: the audit **identifies** damage candidates fine (worst-frames list); the shared
  weight+rest repair cannot **act** on them — same null signature as goblin, on a mesh that
  is actually suspect. Combined with Measurement limits, the open question is whether the
  damage is outside the field's reach (topology/UV/albedo/empty plates) or below the
  scorer's resolution. Do not rerun wood elf unasked.

## Texture-guided neck cuts (2026-09-19, new module, no GLB writes)

Pivot: instead of repairing weights, break the connections that cause warping.
`experiments/homm3_mocap_v2/neck_cut_selection.py` selects ONE cut: severe-warp
faces (violation band + mesh p95, closest-observation so ties never split),
connected over the exact-position-welded graph, ranked by violation mass times
texture-seam fraction. Texture guides but never vetoes: no seamed candidate
means a flagged geometric-neck suggestion, never silence. Feeds the reviewed
`attachment_repair.split_attachment` cutter (owns the edit + invariants).
Validator: `test_neck_cut_selection.py` (10 tests: seam/UV/crush/geometric-fallback
gates, sampler parity with the preview path, a 1024px-texture perf pin from a
real 30-minute hang (per-call 100MB copies, now hoisted), duplicate-ID and
shared-ID end-to-end warp release with rest/UV preservation, quiet/malformed
gates). Run: `artifacts/homm3_mocap_v2/venv/Scripts/python.exe
C:/tmp/run_neck_tests.py` (runner kept outside the repo; run from the repo root).
Review pass applied: violation mass unifies stretch excess + compression deficit,
schema consistent across empty/non-empty reports, malformed baselines
un-confounded, textureAgrees flag semantics documented (callers must not apply
a geometric suggestion blindly). Known limits documented in the module docstring.

Wood elf Death proof (numeric only, staged GLB, nothing written): worst warp is
a 58x max stretch (p95 3.9, 89 fragments over 5x). Suggested cut is 9 faces at
a 0.82-seam boundary, owner mixamorig:Hips. Applied numerically: component max
stretch 13.056 -> 1.0, all rest/UV/face invariants hold, separation opens
0.09-0.21 world units on Death f1 (the documented tradeoff: gap, not drag).
Bigger same-skin masses (36f/25x, 55f/58x, seam <= 0.3) stay listed, uncut.
Next: decide whether the flagged geometric necks get cut, and whether any cut
gets written to a GLB (both need explicit go-ahead; no delivery files touched).

## State on disk

- Scaffold (committed): `experiments/homm3_mocap_v2/keyframe_combined_repair/` — `audit_keyframes.py`,
  `repair_contract.py`, `repair_keyframes.py`, `replay_deployed.py`, `run_keyframe_repair.py`,
  `test_keyframe_repair.py`. No `_tmp_*` files left (all diag scripts deleted).
- Baseline (git-ignored, regenerated): `artifacts/homm3_mocap_v2/keyframe_combined_repair_v1/audit/h3_goblin/`
  (`audit.json`, contact PNG, GIF).
- Repair output (git-ignored): `artifacts/homm3_mocap_v2/keyframe_combined_repair_v1/h3_goblin/`
  (`report.json`, `candidate_weights.npz`, `repaired_mesh.npz`, contact PNG, GIF).
- Venv python: `artifacts/homm3_mocap_v2/venv/Scripts/python.exe`. Lab root:
  `V:/SteamLibrary/steamapps/common/Heroes of Might and Magic Olden Era - Golden Era/BepInEx/plugins/OfflineUnlockMod/homm3_lab`.

## Literal next actions

1. Goblin repair is parked: null result under a detail-starved scorer. Do not rerun unasked.
2. To actually answer the brief: new experiment — lit/tighter/higher-res measurement, then
   re-baseline + re-run. Needs explicit go-ahead (rebuilds the measurement, invalidates the
   0.729 baseline).
3. If rerunning any repair as-is: delete a stale `h3_goblin/` output dir first (runner refuses
   even empty dirs), same command as before with `--iterations 150 --seconds 600`.

## Gotchas

- **Never `read_file` the contact PNG/GIF.** A prior thread died because the PNG inserted a
  base64 image part the Meta endpoint rejects, permanently and across compaction. Diagnose
  numerically (PIL stats in terminal) only.
- Terminal output always shows a `conda : The term 'conda' is not recognized...` preamble —
  harness noise, commands still execute. Ignore it.
- `run_unit` refuses to overwrite: check for and delete an empty `h3_goblin/` output dir before
  each run.
- Audit outputs are git-ignored (`git check-ignore` confirms); only the scaffold commits.

## Post-cut weight reassignment (bind-weight creep fix)

- `attachment_repair.reassign_cut_boundary_weights(split_skin, selected_faces, owner, rings=1)`:
  prop-side ring pinned to exact owner weight; body-side ring (seam sources included) has owner
  mass dropped + renormalized; 100%-owner body rows kept + counted as fallback, never zeroed.
- Wood elf neck (`/tmp/stage3_weights.py`, `C:\tmp\stage3_result.json`): 4 body-side ring rows
  carried 1.665 Hips mass (the creep), all dropped, 0.0 remaining, 0 fallback; component strain
  still 13.056 -> 1.0, gap 0.162 unchanged, all split invariants hold. Residual was entirely
  body-side; prop pinning was a no-op (split already onehots that side).
- Contracts: 4 new tests in `test_attachment_repair.py` (16/16 green), runner suite 7/7 green.
  No GLB written; still needs explicit go-ahead for delivery-side application.

## Owned-rerig position-field rule tried on the cut elf (negative result, kept as experiment)

- Reused `owned_rerig.exact_bind.skin_by_position_field` verbatim (no reimplementation) on the split
  elf with deployed rest-chain bones (`/tmp/stage4_field.py`, `C:\tmp\stage4_result.json`).
- Result: seam gap exactly 0.0 (was 0.162), coincident mismatch 0.0, 3 markers excluded — but
  component stretch 2.18 vs 1.0 and global extremes ~2.5x worse (edges >100%: 4.5% vs 1.8%,
  max 21.0 vs 15.6). Worst edges are stray-card soup (leg+forearm+hand blends), the geometry the
  Sept-17 thread itself concluded no weight rule can fix.
- Why it doesn't transfer: the thread's win was measured with capture-fitted joints on capture
  clips vs their own neighbourhood baseline — never against these deployed Mixamo weights on
  these clips. Deployed skin already carries 0.0 marker mass, so that rule is satisfied here.
- Verdict: keep cut+ring-reassign; do not adopt the raw field. Reel for visual check:
  `artifacts/.../h3_wood_elf/h3_wood_elf_neckcut_closeup_field.gif` (61f, 900x330).

## Hand-binds-to-hip diagnosis (the bleed is deployed-first)

- `/tmp/diag_handhip.py` + `/tmp/diag_handhip2.py`: on 207 deployed-hand verts, DEPLOYED hip-region
  mass averages 0.22 (max 0.31); the field cuts that to 0.025 mean (max 0.33, 4 rows >0.25).
  The symptom the eye sees is in the shipped skin, not introduced by the field.
- Stacked mechanism: (1) the field metric is Euclidean point-to-segment through SPACE, never
  through the surface — hand verts sit 0.29 min from the hip segment, so hip stays competitive;
  (2) the deployed joint fit is loose exactly on the arm chain (left arm/forearm/hand segments
  float 0.15-0.19 off the flesh vs 0.005-0.01 at the pelvis, asymmetric L/R), which promotes the
  bleed from trace to visible. A geodesic (through-geometry) weight could not connect hand to hip
  by construction.
- No fix applied; options open: joint refit (thread's place_bones stage, skipped here),
  geodesic/articulation restriction, or targeted de-bleed. Needs explicit direction.
- Misalignment confirmed as the amplifier (`/tmp/diag_misalign.py`): bone lengths are L/R
  symmetric (arm 0.25/0.28, leg 0.38/0.36) but placement is not — arm chain floats 0.06-0.18
  off flesh vs 0.005-0.01 at the pelvis, left worse; both hands are degenerate POINT bones
  (length 0.000, purely radial cells); deployed hand ownership is 253-vs-15 lopsided by side.
  Airgap hand-to-hip is real (median 0.19, min 0.015, zero shared verts) yet hip wins 29 hand
  cells because the contest is relative: hip touches its flesh at 0.005 while the hand bone
  sits 0.11+ off its own.

## Topology-traced skinning (restrict blends to connected surface) + articulation

- `attachment_repair.topology_traced_weights` (committed, 21/21 tests): per-bone Dijkstra over
  mesh edges + zero-cost coincident links; unreachable bones get nothing; split seam pairs from
  `sourceVertexIds` stay barred; optional `parents` enforces the owned-rerig articulation
  relation (strongest bone + its parent/children only). Reports excludedMass, unreachable
  entries, articulation drops, coincident mismatch (fail-closed).
- Elf numbers (`/tmp/stage5_traced.py`, `/tmp/diag_traced.py`, `C:\tmp\stage5_result.json`):
  travel alone excludes 269 mass units across 43k entries, gap 0.004, component 1.78, bulk
  better-or-equal everywhere (p50 0.028, p99 1.20) — but hand-hip stays 0.22 (seed bleed: 29
  hand verts sit in the hip's Euclidean cell, no contact found). With enforcement: hand-hip
  exactly 0.0, bulk p50/p90 3x better (0.0115/0.093) — but contact tears appear (p99 7.2,
  max 95x at a thigh contact given disjoint sets). Same wall the Sept-17 thread hit.
- Reel: `artifacts/.../h3_wood_elf/h3_wood_elf_neckcut_closeup_traced.gif` (61f, 900x330).
- Standing recommendation: keep travel restriction (clean win); enforcement opt-in only
  (already the design: omit `parents` to skip). No GLB written.

## Toy Story combination: rigid separated part + traced body (wins)

- Per-vertex rigidity (`max_influences` 1..2) goes the wrong way here: neck component
  1.78 -> 6.5 -> 10.8, replicating the thread's "rigidity pays in tearing" verdict. True Toy
  Story means one bone per PART, not per vertex: pin the separated cut component onehot and
  trace the body (`/tmp/stage7_combine.py`, `C:\tmp\stage7_result.json`).
- pinned+parents: component 1.0 (rigid by construction), gap 0.0047 (traced body tracks the
  rigid part; cf. 0.16 for ring-reassign), hand-hip 0.0. Best neck on every axis at once.
- Reel: `artifacts/.../h3_wood_elf/h3_wood_elf_neckcut_closeup_pinned.gif` (61f, 900x330).
  Global body extremes unchanged from traced+parents (thigh contact tear persists there).
- The 61f reel understates the neck fix (neck verts move only 0.003-0.04/frame; panel churn is
  reskinned body): focused reel `h3_wood_elf_neckcut_worstframes.gif` (3f, 600x330, 900ms) shows
  the same face 4752 at 13.5x/13.1x/9.9x before and 1.00x after, tight registered zoom.
- No GLB written.

## Cross-unit joint-proxy refit (the consistent way to refit)

- `joint_refit.refit_joint_proxies` (committed, 7/7 tests): template-free, same params every
  unit. Stage 1: one global translation shared by all owned non-marker bones (mass-weighted
  mean centroid error — absorbs a systematically misplaced skeleton, which is exactly the
  goblin's case: coherent 0.34 offset). Stage 2: per-bone local residual toward its own
  deployed-mass-weighted flesh centroid, clamped to 0.15 mesh extent. Rigid translate only;
  markers/unowned never move; animation skeleton untouched (proxies feed skinning distances).
- `validate_refit_proxies` is the build/deploy gate: schema, frozen params, mesh checksum,
  rigid global+local within budget, moved-flag consistency. Returns ok/errors, never raises.
- Two-unit proof, identical params (`/tmp/stage8_refit.py`): elf median fit 0.102->0.014
  (15 fitted, 1 clamped), goblin 0.114->0.029 (11 fitted, 11 clamped), validator green both.
- HELD OUT of the repair pipeline: refit+pinned+parents opens the neck seam to max 0.61,
  mean 0.20 across 61 frames (vs 0.014/0.004 unrefitted, `/tmp/check_gap.py`). Body-side seam
  verts re-weighted onto torso bones diverge from the rigid Hips prop on Death f1. Next option
  if wanted: extend the rigid part one ring into the body (pin seam sources too).
