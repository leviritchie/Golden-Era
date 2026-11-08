# Town GPU kernels (zero-streak certificate on CUDA)

Module: `tools/homm3_town_scene_meshes/town_gpu_kernels.py`. Caller: `town_full3d_zero_streak.certify(..., device=)`.
Parity test: `tools/homm3_town_scene_meshes/test_town_gpu_kernels.py`, gated by `tools/validate_town_zero_streak_contract.py`
(staged tier). Proof tier: generated artifact (offline raster), same as the certificate itself.

## Device switch

- `certify(..., device="cpu"|"cuda")`, CLI `town_full3d_zero_streak.py --device cpu|cuda`, env `TOWN_FULL3D_DEVICE`.
- Default: `cuda`. It became the default only after the parity test passed (2026-10-01).
- `cpu` is the reference implementation and stays in the file unchanged. Use it to arbitrate any doubt.
- A missing torch or CUDA device raises `SystemExit`. There is no silent CPU fallback.
- VRAM: the engine caps torch at `TOWN_GPU_VRAM_CAP_GB` (default 8 GB). The measured peak is about 0.7 GB on Castle zs_v5
  (3.0 M faces, 1920x1080). It does not take `town_full3d_gpu.gate`, which is the single-flight lock for the
  SDXL and depth model runs: a 1 GB certificate does not need to queue behind them.

## Profile (castle zs_v5, state `full`, 3.0 M faces, 2026-10-01)

CPU reference, per pose, about 1.9 s:

| stage | s/pose |
|---|---|
| `world_points` x2 (reprojection grid, ground rays) | 0.50 |
| `face_stretch` (project, `np.linalg.svd` of the 2x2 Jacobians) | 0.50 |
| `np.unique` (drawn faces, owners) | 0.23 |
| inline masks, attribution loops | 0.24 |
| `T.project` of 2 M px | 0.16 |
| `TP.zbuffer` (new context and ~70 MB upload per pose) | 0.20 |
| scipy `label` x2 | 0.01 |

This analysis was nearly all of the recipe's wall time. zs_v5's recipe took 474 s: 3 repair rounds plus the gate,
each 23 poses x 3 states.

CUDA path, per pose, about 0.10 s (measured with cProfile over 23 poses):

| stage | s/pose |
|---|---|
| moderngl render plus readback of 33 MB | 0.03 |
| CPU `label` x2 plus sparse attribution | 0.04 |
| torch kernels plus host/device copies | 0.03 |

Fixed costs per process: `import torch` takes about 8 s, and the first CUDA pose takes about 1 s while kernels warm up.
Engine setup per `certify` call takes about 0.3 s.

## What moved, what stayed

- **GPU (moderngl):** one standalone context per `certify` call. The geometry is uploaded once and every pose renders into the
  same framebuffer. The shader and matrices are those of `TP.zbuffer`, and the output is byte-identical. The context is
  made current again before every render, because a `TP.zbuffer` call in between leaves it non-current, and without
  this it renders nothing.
- **GPU (torch, float64):**
  - per-px reprojection into the rest frame and the reveal test;
  - the ground-ray floor test;
  - the drawn-face set (bincount, which gives the same sorted set as `np.unique`);
  - per-face texel Jacobians with closed-form 2x2 singular values;
  - streak, revealed and extension masks;
  - per-bin px counts.
- **CPU:**
  - scipy `label` of the behind mask and of the undrawn mask. It costs about 6 ms each and is a sequential union-find,
    so a GPU port would gain nothing.
  - per-component sparse work.
  - overlay PNGs, which are only made when `out` is set.

## Exactness

Float64 elementwise ops are correctly rounded on both devices. The reference's `@` products go through BLAS, though,
and BLAS has its own FMA and summation order. A GPU value can therefore differ from the CPU value in the last ulp.

Every discrete decision on the GPU is taken with a margin. If a px's or face's deciding value is non-finite, or lies
within `EPS_REL = 1e-9` of a threshold, the reference formula re-decides that px or face on the CPU. The thresholds
covered are:

- streak `s1 >= 6`, `s1/s2 >= 3`, the `|det| > 1e-9` UV gate and the `s2` clamp;
- rest-frame bounds, the `int` truncation of `px`/`py`, `zc > 0` and `zc > z0 * 1.03`;
- ground `0 < t < FAR_CAP_M`;
- the restSky split of the ground holes (2026-10-02): the `int` truncation of the floor hit point's rest-frame `px`/`py`,
  `zc > 0`, the `|nd| > 1e-12` guard and `z0 < zc`. `ZS.ground_split` is the reference; it writes its dot products
  out in a fixed order (no BLAS) so the GPU reproduces it to ulps. The sky coverage comes from a second `Raster` of the
  static Sky_ bins, byte-identical to `TP.zbuffer`. Re-decided px are counted in `redecided["groundSplitPx"]`.
- the background frame of that split (2026-10-02, a general correctness fix that the coordinator approved): a third
  `Raster` draws the environment-only rest frame (`ZS.env_frame_faces`: every `environment/` bin except the backstop
  class, so not `Mesh_Backstop` or its floor fill, and no building layer). Its `fid` at the same truncated hit px
  decides `restSkyEnv`: the background frame is undrawn at q but the state's frame is drawn. Both counts are then
  excluded where the pose's Sky_ raster covers the px. The truncation is the borderline already covered above, so a
  borderline px is re-decided by `ZS.ground_split` with `fid_env` as well.

The counts re-decided are kept in `CertifyEngine.redecided` as a diagnostic. Over 23 poses on zs_v5 `full`, 908 faces
and 113 px were re-decided. Without this step, those faces and px could flip. The `z0 * (1 + REVEAL_TOL)` product
stays float32, as numpy computes it.

## Parity results (2026-10-01)

`test_town_gpu_kernels.py` uses the proof poses, `sweep_fwd` and 4 loop samples (11 poses), state `full`. It
requires byte equality of the report JSON, the `faces_out` map and the overlay PNGs, and checks
`Raster == TP.zbuffer` at two poses.

| case | result | CPU | CUDA |
|---|---|---|---|
| castle zs_v5 (passes the certificate) | identical | 19.7 s | 4.1 s |
| castle rx_ldi_zone_old_nfix (fails: 1707 visible-behind px, 200 failing faces) | identical | 18.3 s | 3.1 s |

End to end on zs_v5 over all 3 states (`start`, `full`, `anim`), comparing the full report JSON and `faces_out`
per state. The source is `V:/olden_port_work/gpu_offload/e2e.py`.

| run | CPU | CUDA | speedup | parity |
|---|---|---|---|---|
| board-pose certificate (recipe gate: loop 12 + 4 extra = 23 poses x 3 states) | 106.3 s | 13.0 s | 8.2x | identical, pass in all 3 states |
| 43-pose certificate (loop 36, 43 poses x 3 states) | 197.4 s | 13.8 s | 14.3x | identical, pass in all 3 states |

The board-run CUDA time includes the one-time `import torch` and the warm-up (about 9 s). The 43-pose run comes
after both in the same process. A recipe build's repair rounds and gate run 4 certificates of this size in one
process, so they amortise that cost.

## Shared helpers for other lanes

`singular_values_2x2(J)` and `project_points(cam, p)` are float64 CUDA versions of `np.linalg.svd(..., compute_uv=False)`
and `T.project`:

| helper | agreement with numpy | 2 M items, CPU | 2 M items, GPU |
|---|---|---|---|
| `singular_values_2x2` | about 1e-15 relative | 1.45 s | 0.02 s |
| `project_points` | about 1e-13 relative | 0.08 s | 0.02 s |

They are meant for continuous measurements such as the mv3 warp-cause Jacobians and texel-fusion weights. They have
no exactness margin, so a caller that applies a threshold must keep its own margin. `Raster` is a reusable
z-buffer with face ids. `load(P, F)` swaps the geometry and `render(cam, fid=False)` returns depth only. Its colour
target is RG32F (z, primitive id), which halves the reference's readback with the same values.

## Seam build (`town_full3d_building_seams.rest_seams`)

`rest_seams(..., device=)` and `seams_for_build(..., device=)` take `device`; without it they read
`TOWN_FULL3D_DEVICE`, and the default is `cuda`. On cuda, every layer and all 6 of its renders (rest plus 5 proof
poses) use one `Raster` context, and only the layer's geometry is uploaded. On cpu, each render opens a fresh
`TP.zbuffer` context; this is the reference.

The adjacent-pair search stays numpy on both devices. A torch port (`torch.nonzero` per layer) measured the same
per layer, about 60 ms, and would have added torch's import, so it was dropped. The seam path imports no torch.

Profile on castle zs_v5 (32 layers, 28 098 pairs, cProfile):

| path | `TP.zbuffer` (192 calls) | of which: context create | of which: readback | per-layer numpy | total |
|---|---|---|---|---|---|
| CPU | 13.3 s | 5.2 s | 2.9 s | about 2.0 s | 15-17 s |
| cuda | `Raster` 3.2 s | none | 1.5 s | about 2.2 s | 6.9 s |

Parity (`test_town_gpu_kernels.py`): every `seam_*` array is byte-identical between the two paths.

| case | CPU | cuda |
|---|---|---|
| zs_v5 | 12.4 s | 4.4 s |
| rx_ldi_zone_old_nfix (37 249 pairs) | 14.1 s | 4.2 s |

## CS re-bake (`cs_numpy.offsets_batch`, `patch_glb.edge_stretch`)

`tools/homm3_glb_patch/cs_torch.py` runs the glbPatch / cs_rekey Corrective Smooth re-bake on CUDA, **bit for bit**.
`cs_numpy.offsets_batch(..., device=)` and `patch_glb.edge_stretch` take the device from `device`, else the env var
`HOMM3_CS_DEVICE`, else `cuda`; the CLI is `patch_glb.py apply|parity --device cpu|cuda`. `cpu` is the numpy reference and
stays the rule. Without torch or a CUDA device it raises `SystemExit`. bake_cs.py (inside Blender) never calls
`offsets_batch`, so the Blender bake imports no torch.

How the bits match:

- `np.bincount` (`_scatter`, the corner weight sums) adds a bin's entries sequentially in index order from +0.0. The
  GPU uses a per-bin table of entries in that order and adds them column by column from a +0.0 tensor.
- `np.einsum` over a contiguous inner axis of 3 sums `(p0 + p2) + p1`, and of 4 `(p0 + p2) + (p1 + p3)`. Over the
  transposed frames (a strided axis) it sums in order. `np.linalg.norm` sums the squares in order. These were measured
  on numpy 2.x (X86_V3) and do not depend on alignment.
- In torch, a Python scalar divided by a tensor is `reciprocal() * scalar`, which rounds twice. The smoothing
  coefficient therefore divides a full tensor.
- Some steps stay on the CPU because CUDA cannot reproduce their bits:
  - `np.arccos` of the corner cosines (the inputs come from the GPU and are already identical);
  - the per-joint `det` and `cbrt` of the skin scale;
  - the harmonic fill;
  - the LAPACK rest-space solve, run per pose on a thread pool (each call is the reference call).

Parity test: `tools/homm3_glb_patch/test_cs_device_parity.py`, run by `tools/validate_homm3_cs_bake_contract.py`
(full tier).

| unit | what is compared | cpu | cuda |
|---|---|---|---|
| h3_griffin (glbPatch, 130 targets) | patched GLB sha256 and the `csRebake` record | 31.4 s | 9.8 s, including the torch import |
| h3_mummy (engine level, every CS_ key, COND_EDGE split on) | offsets, masks, edge stretch with stored and re-baked offsets | 6.2 s | 2.4 s |

Both are identical.

Profile of `patch_bytes` on h3_griffin from the retained base:

- CPU: 41.5 s in total. `smooth` took 19.9 s (of which `_scatter` 7.6 s), `tangents` 5.3 s, `_skin` 5.0 s, `solve` 3.2 s and
  `edge_stretch` 2.8 s.
- CUDA, warm process: 8.3 s, of which `cs_rebake` is 5.1 s. What is left is the CPU solve (about 1.2 s across threads),
  the Weld build (1.2 s), host copies (0.6 s) and the non-CS patch ops.

## Terrain bake (`stronghold_full3d_periphery.bake_piece`, `stronghold_full3d_terrain.raymarch`)

Both functions take `device` (else `TOWN_FULL3D_DEVICE`, else cuda). Their own bodies are the cpu reference; cuda runs
`tools/homm3_town_scene_meshes/town_gpu_terrain.py`. It has no fallback: a missing CUDA device raises SystemExit, and so does
`TOWN_FULL3D_GROUNDSRC` (`baker.gs`, which is not ported) on cuda. Use `--device cpu` / `TOWN_FULL3D_DEVICE=cpu` for that path.
Callers (`periphery.build`, `town_full3d_sky_continuous.rebake_outer`, `ground.frame_depth`, `layer_terrain`) are
unchanged and get the cuda default.

Exactness:

- **raymarch:** byte-identical. The per-ray march, the stop rule and the 12-step bisection match the reference.
  - Rays advance masked. The live set is compacted every 32 steps, so there is one host sync per 32 steps.
  - The bisection runs once at the end, on each crossed ray's bracket.
  - The ray setup and `fz` stay numpy.
- **bake_piece, given the same detail layers:** byte-identical. `Field.sample` (the remap), value noise / fbm, `tiled`,
  `synth_detail_parts`, palette, floor patches, cavity, baked shade, soft normal, `floor.rel`, `project` and the EXTSRC
  remap all run on the GPU in the reference's dtypes and order. The helpers are listed in the module docstring.
- **Kept on the CPU (numpy), on the GPU's bit-identical inputs:**
  - transcendentals: power, exp, log, hypot, cos/sin of the column azimuths;
  - the row `np.interp`;
  - float32 light dots.
- **The detail-layer blur:** the one approximate step. `cv2.GaussianBlur`, sigma = tile/6, up to a 1024 px tile. It runs
  on the GPU as a float64 conv2d over the 3x3-tiled layer, with cv2's float32 kernel and the valid centre region.
  - It cannot be bit-identical, because cv2 accumulates in float32 in its own order.
  - Measured max relative difference per layer: 2.2e-6 to 3.4e-6. Gate: 1e-5.
  - After the delivered sRGB encode (`save_srgb`), the baked pieces differ by at most 1 code value on 0.0005-0.005% of
    channels. Gate: max 1 on at most 0.1% of channels.
  - The visual bound: one 8-bit code is the encode's own rounding step and is not visible.

Parity test: `test_town_gpu_terrain.py`. It runs in the staged tier of `validate_town_zero_streak_contract.py`, and the
static tier pins the dispatch. It checks:

- the raymarch, byte-identical;
- every periphery piece, cpu vs cuda with the reference layers (`layers="cpu"`), byte-identical;
- the production cuda path (GPU layers) against both tolerances.

The default run bakes pieces at 1/4 size per axis. `--full` bakes them at production size.

Measured on the Stronghold default scene, full size (`--full --ray-stride 1`, 2026-10-01). Timings are warm with the
detail layers cached:

| stage | cpu | cuda | speedup |
|---|---|---|---|
| raymarch, all 1,104,480 frame-extension rays (a `frame_depth` cache miss) | 43.4 s | 2.05 s | 21x |
| bake, 8 pieces, 13.5 M texels | 146.3 s | 17.4 s | 8.4x |
| terrain_state (cache miss) + full periphery bake, cold process incl. layers, under cProfile | 268 s (61 + 207) | 23.4 s (6.3 + 17.1) after the sdiv 0-d scalar cache (was 31.2 s) | about 11x |
| detail layers (blur), once per process (5 of 6 layers, after warm-up) | 36.1 s (6 layers) | 0.35 s | about 100x |

## Wheel hub grid (`town_full3d_mech.fit_wheel`)

`fit_wheel(..., device)` takes `device` (else `TOWN_FULL3D_DEVICE`, else cuda). On cuda, `town_gpu_mech.wheel_grid_scores`
scores the whole hub x step grid on the GPU in one batch: 418 cells x 89 steps x 8 frames on tbfacas3, the 290 k
`warpAffine` calls of the CPU path. It has no fallback.

What is exact:

- **The screen map:** at q = 1, psi = 0, `ell_affine` reduces to the rotation itself. Its translation is numpy's
  `fma(M00, cx, M01*cy)`, computed with `torch.addcmul`. cos/sin come from Python's `math`. A spot check of 64 maps
  against `ell_affine` fails closed.
- **`cv2.warpAffine`** (4.13, INTER_LINEAR, constant border) is reproduced bit for bit:
  - the map is inverted in double;
  - the fixed-point source position uses AB_BITS 10 and a round delta of 16;
  - the float32 table weights are used, and the taps are summed in order.

  So the warped masks and their px counts are exact.

What is approximate: only the NCC sums, which run in float64 here while numpy reduces float32 pairwise. The measured max
difference is 3.2e-8.

How the pick stays the CPU's: every cell within 2 x `WHEEL_GPU_EPS` (1e-4) of the third-best GPU cell is re-scored on
the CPU with the reference code, and the CPU score chooses the fit. Any true top-3 cell is in that set, and the stable
sort runs in grid order, so ties break the same way. A re-scored cell whose GPU score is more than `WHEEL_GPU_EPS` off
fails closed.

The coordinate ascent, the tilt search and the texture rebuild are unchanged on the CPU.

Parity test: `test_town_gpu_mech.py`. It runs in the staged tier of `validate_town_zero_streak_contract.py`, and the
static tier pins the switch. It checks two rects on tbfacas3:

- the right cog: the same hub (151.5, 45.12), step -5 deg and N 8, the same fit report, and byte-identical tex, front
  and plate;
- the left rect: the same refusal on both devices.

Timings on tbfacas3:

| rect | cpu | cuda |
|---|---|---|
| right cog, first CUDA use | 14.3 s | 4.9 s |
| left rect (refused) | 10.7 s | 3.0 s |

## Not moved (measured)

- **Seam re-measure** (`validate_town_scene3d_contract.building_seam_stats`): 0.04-0.07 s per catalog on about 29 k
  pairs x 5 poses. It stays on the CPU.
- **mv3 `mv3_mask2` / `mv3_v2` / `mv3_fuse`:** owned by the mv3 lane and in active edit. They were offered the helpers
  above and were not rewritten.

## GPU-first audit of the remaining CPU hot spots (2026-10-01, profiled)

The audit's ranks 1-3 have since moved to CUDA. See "Terrain bake" and "CS re-bake" above.

Measured with cProfile on the current tree. Scratch profilers live in `V:/olden_port_work/gpu_offload/`. Ranked by
seconds saved per typical run.

| rank | file:function | measured | GPU gain (estimate) | note |
|---|---|---|---|---|
| 1 | `stronghold_full3d_periphery.bake_piece` (periphery stage) | 207 s for 13.5 M texels, 8 pieces (Stronghold default); recorded `bakeSeconds` median 150 s, max 258 s | high: about 10-30x | Pure per-texel: `G.synth_detail_parts` 120 s (`tiled`/`sample_wrap` 62 s, `T.value_noise`/`fbm` about 80 s), `G.floor_patches` 36 s, `T.Field.sample` 58 s, `T.Field.normal` 18 s, `cv2.GaussianBlur` 49 s over 20 large-sigma calls. Every op is a gather plus elementwise math. The albedo is continuous, so parity is a uint8 PNG tolerance or float64 kernels, not byte equality. |
| 2 | `tools/homm3_glb_patch/cs_numpy` `smooth`/`_scatter`/`_skin`/`solve` (via `patch_glb.apply_bytes`) | 34.6 s per griffin patch: `smooth` 16.4 s, `_scatter` 6.4 s, `_skin` 3.9 s, `solve` 3.0 s | high: about 5-10x | A sparse Laplacian and scatter-adds. Use torch CSR matmul in float64 with a fixed order (no atomic `index_add`), so the bake stays deterministic. |
| 3 | `stronghold_full3d_scene.terrain_state` -> `T.raymarch` (terrain stage) | 61 s on a `frame_depth.npz` cache miss, of which `raymarch` is 53 s; recorded `terrain` median 43 s, max 84 s | high on a miss: about 20x | A per-pixel height-field march. It is the same `Field.sample` gather as rank 1 and can share its kernel. |
| 4 | `prop_floor_glb.prop_heights` | 12.0 s of 18.7 s per mummy apply | none from a GPU | 985 k calls to `stride_match_glb.read`. This is Python call overhead: cache or vectorise the accessor reads. |
| 5 | `layerTerrain` / `t2Buildings` stages | 22 s, and 7-18 s per layer (recorded) | unknown | Not function-profiled. |
| 6 | glb_patch `cs_rekey` (`edge_stretch`, `smooth`), `ground` (`def_wing_calibrate.skin` einsum), `stride_match`, `densify` | 2.0 s, 1.6-3.8 s, 0.9 s, 0.3 s | low | Below the cost of a torch import. |
| - | unit look/deliver (Blender bake_terms, render_passes) | about 125 s of a 153 s mummy rebuild | out of scope | Blender-bound, not numpy. |

### Re-ranked after the ports (2026-10-01, re-profiled)

| was | item | now | status |
|---|---|---|---|
| 1 | periphery `bake_piece` | 17.1 s for the full ring, from a cold process with layers (was 207 s) | moved (Terrain bake) |
| 3 | `terrain_state` on a cache miss | 6.3 s (was 61 s) | moved (Terrain bake) |
| 2 | glbPatch CS re-bake | 8.3 s griffin, 6.9 s mummy `cs_rekey`, about 1.5 s of it the torch import (was 35 s) | moved (CS re-bake) |
| 4 | `prop_floor_glb` | 1.1-2.0 s on 4 units (mummy was 17.1 s) | CPU vectorised (420825f810): one gather in `prop_heights`, one channel snapshot. Output GLB sha256 unchanged on h3_mummy, h3_troglodyte, h3_infernal_troglodyte, hota_cove_nix |
| 5 | `layerTerrain` (Rampart rx_layer_card, opt-in) | 28.8 s on a cache miss | left: `cv2.inpaint` 7.5 s (3 calls), torch import 5.8 s (one-time), `Baker.bake` 2.7 s, GaussianBlur 2.4 s; each is under 10 s and none ports bit-exactly (inpaint is sequential fast marching) |
| 5 | `t2Buildings`: Factory `tbfacas3` wheel fit | 14.3 s on the CPU, 4.9 s on cuda (first CUDA use) | moved (Wheel hub grid). Before the port, `fit_wheel` was 18.5 s of the 23.9 s stage. The Castle/Tower T2 seeds no longer hold their bodies on V:, so those stages were not re-profiled |
| 6 | the rest | under 4 s each | left |

GROUNDSRC (`baker.gs`): no recipe or candidate sets `TOWN_FULL3D_GROUNDSRC`. The recipes' `groundSrcM` is an unrelated
backstop parameter. It stays unported, and cuda refuses it (SystemExit).

Owned by other lanes and in active edit, so listed only and not touched:

- `town_full3d_zero_streak.py` recipe repair/backstop (its certificate is already on CUDA above);
- `town_full3d_ground_contact.py` (already has `gs.device`);
- `mv3_mask2.analyse`, `mv3_v2`, `mv3_fuse`: `ZS.world_points`, `SM.face_stretch`, per-face SVD, `cv2.remap`, `block_detail` loops. `singular_values_2x2` and `project_points` above are the drop-ins.
