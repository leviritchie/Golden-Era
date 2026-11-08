# HoMM3 GLB patch lane (Blender-free localized unit fixes)

Status: generated artifact validated (numpy patch + differential Corrective Smooth re-bake, delivery gates pass on
the pilot). Not built into a bundle, not installed, not seen in game.

Owner files: `tools/homm3_glb_patch/` (`patch_glb.py`, `cs_numpy.py`, `cs_torch.py`, `base.py`, `resmeter.py`, `stretch_relax.py`, `test_patch_glb.py`, `test_stretch_relax.py`),
the `--from-base` route and the patch stage in `tools/homm3_def_retarget_delivery/fleet_rebuild.py`, the
`homm3DefRetargetDeliveryPatch` entry at the head of `DELIVERY_STAGES`
(`tools/validate_homm3_def_retarget_emphasis_contract.py`), and the build gate
`tools/validate_homm3_glb_patch_contract.py` (`ValidateHomm3GlbPatchContract` in `OfflineUnlockMod.csproj`,
`SkipHomm3GlbPatchContract=true` to skip).

## Why

A localized animation fix, such as a hem that dips under the floor, a tail angle or a spear that flails, used to
mean the whole chain: Blender build, `bake_cs`, render, `verify_glb`, emphasis deliver, then the numpy delivery
stages, `look.py --force` and the idle rollout. With several agents working at once that exhausts RAM and disk, and
Blender is refused while the game runs.

## Profile (h3_jotunn_upg_alt, 2026-09-30, `resmeter.py`: process-tree peak RSS, bytes written)

| stage | wall | peak RSS | written |
|---|---|---|---|
| `run_unit.sh` full build (heat, weights, build, bake_cs, render, export) | 60 s | 3391 MB | 106 MB |
| fleet_rebuild full chain (bake_cs, RENDER_ONLY render+export, verify_glb, emphasis deliver, patch, delivery stages, look, idle) | 184 s | 2556 MB | 847 MB |
| fleet_rebuild `--from-base`, one subprocess per stage (before stage fusion) | 16.1 s | 278 MB | 158 MB |
| fleet_rebuild `--from-base`, in-memory stage fusion (current) | 13.5 s | 269 MB (247 MB with the final gc) | **22 MB** |
| of which `patch_glb.py apply` alone (batched CS, cached skin) | 7.0 s | 216 MB | 27 MB |
| of which one numpy delivery stage (e.g. stride match) | 0.9 s | 181 MB | 27 MB |

Ratios, full chain to `--from-base` (fused), same unit and same final GLB:

| measure | full chain | with a build extension (old cloakHold route: + `run_unit.sh`) |
|---|---|---|
| wall | **13.6x** (184 s to 13.5 s) | **18x** (244 s to 13.5 s) |
| peak RAM | **9.5x** (2556 MB to 269 MB; 10.3x at 247 MB) | **12.6x** (3391 MB to 269 MB) |
| disk written | **38x** (847 MB to 22 MB) | **43x** (953 MB to 22 MB) |

Determinism: the full chain and `--from-base` produced the same final GLB (sha256 `57610961ad880f5f...`) from
the same config.

### In-memory stage fusion (2026-09-30)

Before fusion every numpy stage read the 23 MB GLB and wrote it back: the base restore, the patch, stride, the move
low-pass, densify, ground and look apply, plus a 28 MB transaction snapshot. That was a 158 MB floor. Now:

- **One parse chain, one write.** Each stage exposes `apply_bytes` (`deyaw_bytes` for deyaw), which returns a
  `stage_sidecar.StageResult`: the exact bytes its CLI writes, their sha, and the sidecar. `None` means not opted
  in, the CLI's exit 3. `fleet_rebuild.fused_delivery_stages` calls the stages in process. Each stage takes the
  previous stage's bytes, and its output goes to its own log through the fd-level `logged`. A `SystemExit` becomes
  the CLI's exit code. When the last stage is done, the sidecars are written, then the GLB, once.
- **The `--from-base` route writes no GLB itself.** `base.restore` returns the base GLB's bytes, checked against
  `base.json`, and copies only the two JSON. `look.run_unit(u, ["apply"], glb_bytes=...)` installs the bytes as
  `spec.glb_bytes`, so every look check measures them. Look apply then writes the delivered GLB. That is the route's
  one GLB write, plus the superseded original once per new source sha.
- **The full routes** write the pre-look GLB once, because `look.py --force` and `--try-modes` read it from disk.
- **The stage CLIs are unchanged.** Each is the same `apply_bytes` plus `stage_sidecar.commit`: tmp file and
  `os.replace`, then the sidecar.
- **Transaction.** On `--from-base` the snapshot hard-links the canonical GLB and the look images instead of
  copying them. The route only ever replaces them (tmp + `os.replace`) and never writes them in place, so the
  pre-run inode is the restore point. JSON files are still copied, because they are rewritten in place. If a link
  cannot be made, the run fails before it starts. An in-place write through the link would be a regression; restore
  detects it (every path is re-hashed) and fails closed, keeping the snapshot (`test_fleet_rebuild_txn.py`). The
  full routes still copy, because Blender's exporter may write in place.
- **A refused stage writes no GLB at all.** The canonical GLB stays the previous delivery, and the transaction
  restores the JSON.

Byte identity was proven in two sandboxes:
- **Old against new.** Two repo-tool sandboxes: one with the per-stage subprocess code, one with this code. Each was
  seeded with the same unit state from the live tree. `--from-base` ran in each and the outputs were compared. Every
  unit gave the same final GLB sha, the same `asset.extras`, the same stage sidecars (only the sandbox root path
  differs), the same look stamp (except `appliedAt`), the same superseded originals, the same idle report and
  retimed GLB, and the same rebuild record.
- **Stage level.** deyaw, move low-pass and densify are not exercised by any unit with a retained base. They were
  compared as the old CLI on a file against the new `apply_bytes` on the same bytes:
  - deyaw: `h3_black_knight`, at yawDeg 40 and 360.
  - move low-pass: `h3_plasma_elemental`.
  - densify: `h3_green_dragon`.

  Each input was the delivered GLB with the stage's own stamp removed. Every output and sidecar was identical.

| unit (body) | final sha | wall | peak RSS | written | processes |
|---|---|---|---|---|---|
| h3_jotunn_upg_alt (biped, glbPatch) | `57610961ad880f5f` both | 19.8 s -> 13.5 s | 269 -> 269 MB (247 MB with the final gc) | 157.8 -> 22.1 MB | 12 -> 5 |
| h3_basilisk (quadruped) | `e9ff4133d1d39990` both | 18.2 s -> 13.5 s | 515 -> 387 MB | 278.4 -> 45.9 MB | 12 -> 5 |
| h3_unicorn (quadruped) | `158c81f7c87066cf` both | 21.3 s -> 14.7 s | 605 -> 453 MB | 336.8 -> 54.7 MB | 12 -> 5 |
| h3_wyvern (flyer) | `609b452e4d7a1d77` both | 13.2 s -> 9.3 s | 532 -> 405 MB (before the gc) | 227.3 -> 46.7 MB | 12 -> 5 |
| h3_troglodyte (biped, propFloor) | `8207b8e3fb23c6b7` both | 33.6 s -> 27.1 s | 447 -> 370 MB | 319.8 -> 42.1 MB | 12 -> 5 |
| h3_pikeman (biped) | `2921565146d62635` both | 22.2 s -> 16.2 s | 472 -> 387 MB | 277.6 -> 44.6 MB | 12 -> 5 |

How to read the table:
- Each row is one old run and one new run, back to back, on the same seeded inputs, measured by `resmeter.py`.
- Wall time varies with machine load (other agents were running). The new run was faster in every pair.
- What is still written is the delivered GLB (23 to 55 MB) plus small JSON. Two more GLB outputs appear only when
  their content changes: the superseded original (a new pre-look sha) and the idle retimed GLB (a changed idle).
- The jotunn and wyvern rows ran on the code before the float64 bake (`0cdc943e68`). The rest ran on it.
- After that bake, the jotunn's legacy base and the wyvern / wyvern_monarch bases (their `.blend` was rebuilt) are
  refused by both codes alike. The new code writes nothing on a refusal: 0.03 MB against 64 to 76 MB.

Peak RAM is now one process. `gc.collect()` runs between stages, because a stage's parsed GLB sits in reference
cycles; without it the unicorn peaked at 597 MB.

Iteration cost is the real win. On the pilot, each candidate ownership (Hips, keep 0.5, same-side foot) was one
`patch_bytes` + stride + ground run of about 10 s at about 220 MB, in the scratch loop. The full chain would have
taken about 3 minutes at 2.5 GB and needed Blender, which is refused while the game runs.

A localized skin or track fix needs none of the Blender stages. Their output (the export, its emphasis stamp and
`glb_verify.json`) is a pure function of the `.blend`, and the fix sits after it. Only the stages that measure or
move the body afterwards have to re-run: deyaw, stride match, move low-pass, densify, prop floor, CS re-key (cs_rekey_glb.py: re-bakes the CS_ targets of every pose those stages re-keyed, docs/homm3_cs_bake_float64.md), ground, look apply
and idle cadence. All of them are numpy.

## Design

One solution: patch the verified export in numpy and replay only the numpy stages. There is no Blender worker, no
scheduler and no incremental Blender.

1. **Base.** Every full `fleet_rebuild.py` run retains its export right after the emphasis deliver, before any
   delivery stage. It goes to `artifacts/homm3_glb_patch/<unit>/`: `base.glb`, `emphasis_stamp.json`,
   `glb_verify.json`, and `base.json` with every sha plus the `.blend` sha. That costs one GLB per unit, replaced
   by the next full run. A base is valid only while the `.blend` hashes to its record and every retained file
   hashes to `base.json`. An emphasised stamp must name the base as its `emphasisedGlbSha256`.
2. **Patch.** The unit config's `glbPatch` (`{"reason", "ops": [...]}`) runs as the first delivery stage, in every
   route, so every later gate measures the patched body.
   - `moveWeights`: hand bone skin weight to another bone inside a product of rest-space ramps, in Blender body axes
     like the build hooks. It is the port of the former `bulwark_cloakhold` build extension.
     Optional `onlyWith: {bones, atLeast}` limits it to vertices already carrying at least that weight on those
     bones, so a mixed-weight chip at a cut snaps whole without moving the pure vertices beside it (dendroid guard).
   - `diffuseWeights`: Laplacian diffusion of the skin weights of vertices weighted to `bones` (`iterations` steps of
     `alpha` toward the neighbours' mean; seam copies at one rest position stay welded; top 4, renormalised). A gate
     headroom repair for skinning-driven tears at a hard weight boundary; it does not help tears that come from
     corrective-smooth offsets on sliver edges (royal griffin neck: refused, more edges torn).
     Optional `region` (the moveWeights axis/above/below/ramp list, Blender body axes) limits it spatially: only weld
     groups inside move, by alpha x ramp, and only groups weighted to `bones` alone take part, so it never averages
     across a rip into an arm, a rigid prop island or a bone left out (h3_battle_dwarf waist creases: 487 -> 484).
   - `setWeights` `{table, sha256}`: replace the listed vertices' skin weights from a table under
     `tools/homm3_glb_patch/key_rotations/` (schema `homm3_glb_patch_weight_table.v1`,
     `{vertexCount, vertices: {index: {bone: weight}}}`, 1-4 bones summing to 1). It refuses a sha mismatch, another
     body's vertex count or an unknown bone; the CS re-bake's weld check still refuses split seam copies. It carries an
     offline per-vertex re-solve: h3_dwarf_battlerager's overhead Defence guard tore the shoulder/armpit (1217 -> 1271);
     moving the chest/flank off the clavicles and solving 2414 shoulder/armpit vertices on the GPU against every gated
     pose (stretch hinge, Laplacian smoothness, pull to the current weights) gave 1111.
   - `rotateTrack`: post-multiply a bone's local rotation keys in named clips by a fixed axis-angle.
   - `sitRepose`: re-pose a planted sit in named clips, each with a quadrupedSit ease shape (`full`, `easeOut`,
     `easeIn`, `bracket`). It turns the hips by `pitch` degrees about the world lateral axis (glTF +x; positive
     leans toward +z, the front) through the hind hips' mid-point and lowers them by `drop` times the body height.
     Each hind leg is then two-bone IK'd back to its own ankle: lengths kept, the knee on its original side, and the
     foot and toes keep their world rotation, so the feet stay exactly planted. Finally each `turns` bone's subtree
     turns by deg times the weight about its own head. It writes LINEAR keys on the clip's union key grid. CS
     targets re-bake differentially at their own key times, and the stretch gate holds.
     Optional `foreLegs` `{chains: [[upper, lower, hand]], reach}` (an op may carry only this): after the turns,
     each foreleg is two-bone IK'd so its hand stands where the bind pose (the rig's standing quadruped) puts it,
     at the bind hand height shifted by the hind feet's mean height change from bind, the bind lateral offset from
     the upper bone, and `reach` x body height forward of the re-posed upper bone. The elbow bends toward -z and
     the hand turns to its bind world rotation, all blended from the clip's own pose by the clip's weight.
   - `keyRotations` `{table, sha256}`: post-multiply bone-local rotation keys by per-key quaternions from a table
     under `tools/homm3_glb_patch/key_rotations/` (schema `homm3_glb_patch_key_rotations.v1`,
     `clips: {clip: {bone: {times, quat}}}`). The op refuses a table whose sha differs from the spec, a path outside
     that folder, non-unit quaternions, offsets above 120 degrees, out-of-order times, and a table whose times are
     not the channel's own key grid (1e-5 s). In that last case the table was fitted on another GLB and must be
     refitted, unless the op sets `regrid: true`: then a channel whose grid differs but spans the same first and
     last key is resampled onto the table's times first (slerp for LINEAR, held keys for STEP; the channel is
     written LINEAR) and the report lists it under `regridded`. Use it for sparse 2-key hold channels that must
     carry per-frame offsets; leave densified channels (Unit_Move) on their own grid. It is the per-frame
     counterpart of `rotateTrack`. The tables come from a fit to the DEF plates; see
     "Rearing forelimbs" below.
   - `keyTranslations` `{table, sha256}`: add per-time `[dx, dy, dz]` deltas (glTF local units) to bone translation
     keys, from a table in the same folder (schema `homm3_glb_patch_key_translations.v1`,
     `clips: {clip: {bone: {times, delta}}}`), linearly interpolated onto the channel's own key grid and held past
     the table's ends. Refused: a sha or path mismatch, out-of-order times, a delta above 0.25 x the body height.
     Added 2026-10-07 for the h3_royal_griffin wing surgery: the rebuild's wing_chain screen-offset fit moved the
     Hips path 0.02-0.13 per clip, and the op-3 body table had been fitted on the old path.

   - `stretchRelax` `{clips, ratio, iterations, smooth, bones?, maxMove?}`: a per-pose strain-limiting corrective on
     the re-baked CS targets of `clips` (`stretch_relax.py`). It always runs after the other ops, inside the CS
     re-bake and before the tear gate. It is for deep hip and knee flexion, the case no weight op fixes; see
     "Deep hip and knee flexion" below.

   POSITION, NORMAL, TEXCOORD_0, the indices and the images stay byte-identical, and the check refuses otherwise.
   So the look's geometry hash still holds and `look.py --stages apply` re-delivers the stamped texture without a
   re-bake.
3. **Corrective Smooth re-bake.** `cs_numpy.py` is a line-by-line port of Blender 5.2's `MOD_correctivesmooth.cc`
   on `bake_cs`'s welded proxy: the length-weighted smoothing, the corner tangent frames with angle weights, the
   delta cache, and the Tikhonov solve with the scale mask. Per morph target, conditioned vertices get
   `stored + (CS(new) - CS(old))`; every vertex where the difference is under 1e-7 keeps Blender's bytes.
   Each target must be on at exactly one key of its clip. A one-frame clip (for example the dendroid guard's
   MoveStart) holds its target on both keys; if the pose is the same on every such key, it counts as one.
   It runs on CUDA by default (`cs_torch.py`), byte-identical to the numpy reference (`--device cpu`, env
   `HOMM3_CS_DEVICE`); parity test `test_cs_device_parity.py`, see `docs/town_gpu_kernels.md`, "CS re-bake".
4. **Stamps.** `asset.extras.homm3DefRetargetDeliveryPatch` records `{schema, sourceGlbSha256, configSha256, reason,
   ops, csRebake, proof}`, and the `<glb>.patch.json` sidecar carries the source and output sha. The patch is the
   first link of `DELIVERY_STAGES`, so `delivery_chain_errors` proves the shipped GLB is the frozen export plus this
   recorded patch plus the stamped stages. The existing sha pins, ground, freeze, stride and articulation gates, the
   transaction restore and `chain_errors` all run unchanged on both routes.

### Parity and conditioning (the measured finding)

The re-bake (patch_glb.py `cs_rebake`, cs_rekey_glb.py) smooths with the bake record's own `iterations` / `factor`
(`cs_numpy.bake_smoothing`; a float64 record without them refuses). Until 2026-10-09 both used the module defaults
30 / 0.7, so h3_pegasus (baked at 60 / 0.8) failed parity at p99 0.08·H on every clip; with its own parameters it is
p99 1.4e-5·H, max 0.018·H (generated artifact, base 2026-10-09).

Tested against Blender 5.2 by dumping the modifier on the same proxy and the same frame:
- The smoothing matches to 3e-7.
- Skinning matches to 7e-7.
- The edge set and the face winding are identical.

The corrected result still differed by up to 0.18·H. The cause: 30 length-weighted iterations collapse thin parts of
a Meshy body. On the jotunn, 587 of 2483 weld groups end up with an incident smoothed edge under 1e-6. There
Blender's float32 corner frames are rounding noise: its Corrective Smooth does not even return the rest pose at rest
(max 0.30 error). No other implementation reproduces those bytes.

So parity is proven, and gated, only on **conditioned** groups: groups whose incident edges in both the smoothed rest
and the smoothed pose are at least `COND_EDGE = 1e-3·H`. On the jotunn that gives, over all 139 targets:
- p99 2e-6·H and max 2e-4·H, against the limits of 0.002 and 0.02.
- 47% of vertex-samples are ill-conditioned.

On **ill-conditioned** changed vertices the lane writes numpy's own offset, not Blender's noise plus a difference.
Measured on the unpatched jotunn, edges stretched past 2x summed over all targets were:
- 979 with no CS at all
- 2138 with Blender's stored CS
- 878 with numpy CS

The worst stretch was the same, 6.96, for Blender's stored CS and for numpy CS. Because this region is not
parity-proven, a fail-closed stretch gate replaces parity there. The patched body's edges past 2x may not exceed the
input's, and its worst stretch may not rise by more than 5%. The downstream ground, articulation and freeze gates
measure the result as usual.

This was also a fleet-level finding outside this lane: `bake_cs` itself shipped float32 noise on collapsed regions,
doubling the jotunn's torn edges against no CS. **Fixed 2026-09-30** (`docs/homm3_cs_bake_float64.md`): `bake_cs`
now bakes in float64 through `cs_numpy.py` with an explicit degenerate-corner rule and stamps
`asset.extras.homm3DefRetargetCsBake` (current schema `cs_numpy.BAKE_SCHEMA`, v3). On such a base Blender's bytes
*are* numpy's, so the lane drops the conditioning split (`COND_EDGE` 0, parity on every vertex) and records the base's
`sourceBake`. `patch_glb.py` refuses a base without the current stamp (float32 or the superseded v2): run the unit's full chain once
(`fleet_rebuild.py <unit>`) first. The conditioning text above describes legacy bases only.

## Usage

```
# once per unit (any full run retains the base; Blender, game closed):
python tools/homm3_def_retarget_delivery/fleet_rebuild.py <unit>
# then each localized fix: edit "glbPatch" in tools/homm3_def_retarget/units/<unit>.json, and
python tools/homm3_glb_patch/patch_glb.py parity <unit> --glb artifacts/homm3_glb_patch/<unit>/base.glb   # optional
python tools/homm3_def_retarget_delivery/fleet_rebuild.py --from-base <unit>
python tools/homm3_glb_patch/base.py status <unit>
python tools/validate_homm3_glb_patch_contract.py
```

`--from-base` runs while the game is up, because it launches no Blender. It needs no GPU slot and no memgate. A
changed `glbPatch` that was not re-delivered fails the build validator, and so does a patched GLB whose config no
longer declares the patch.

## When the lane is NOT valid (use the full chain)

- **Geometry, UV, normal or topology changes**: retopology, cut or split edges, a remesh, new props, a texture
  re-bake. The patch refuses any geometry, normal or image hash change.
- **Rig changes**: joint rest positions, new bones such as extra kobold tail bones, bone lengths such as shaman leg
  joints. Inverse binds and rest are the build's.
- **Weight changes that split a weld group.** UV-seam copies would skin differently and crack; the patch refuses and
  asks for wider ramps.
- **A rawAccepted look.** `look.py --try-modes` re-bakes in Blender, so `--from-base` refuses.
- **No base, or a stale base**: the `.blend` was rebuilt since, or the unit is `bake_disabled`. The full run
  retains a fresh one.
- **A fix that must change the DEF fit or retarget itself**: emphasis plans, the retarget, `yawDeg`. Those are
  Blender build inputs.
- **Parity or stretch refusal**: numpy CS disagrees with Blender on the changed conditioned support, or the patch
  tears more edges than the input.

### Scratch dry runs must follow the from-base stage order (2026-10-11, h3_wolf_rider)

A scratch "dry stages" run (patch on the retained base, then every numpy delivery stage in memory) is only a stand-in
for `--from-base` if it runs the same stages in the same order as `fleet_rebuild.fused_delivery_stages`. That includes
**deyaw**, which runs right after the patch on any unit whose config has a `yawDeg` and the `castle_yaw` or
`necropolis_yaw` extension. Without it, stride match and ground measure the body still turned to the fit's yaw, and
the dry verdict does not match the real one.

- **Observed:** on h3_wolf_rider (`yawDeg` 40, `castle_yaw`), a Move fix passed a dry run that skipped deyaw.
  `--from-base` then refused at ground ("grounding would float the stride plant": planted soles lifted to
  +0.047 to +0.050, with the lowest point on RR3- and FR2-owned geometry).
- **Confirmed:** adding deyaw to the dry run reproduced that refusal exactly (same soles, same lifts, same owners).
  Low-point diagnoses taken from the un-deyawed dry GLB were misleading.
- **Rule:** before a dry pass is trusted, check the unit config for `yawDeg` plus `castle_yaw` or `necropolis_yaw`.
  If present, the dry run must deyaw after the patch. Fit the patch's own world aim directions on the base's (yawed)
  facing, because the patch runs before deyaw. `--from-base`'s ground stage stays the gate.

### Rig or mesh rebuild of a unit that already has a glbPatch (2026-10-10, h3_pit_lord)

A full chain on a unit whose config carries a `glbPatch` applies that patch to the freshly exported base. If the
rebuild changed the mesh, weights or rig (a `floaterFix`, a new bone chain), key tables fitted on the old base can
fail the tear gate there. The chain then stops before it retains the new base, so `--from-base` refuses (".blend
rebuilt since the base export") and nothing can be gated against the new mesh. Flow:

1. Move `glbPatch` out of the unit config (keep a copy), then run `run_unit.sh <unit>` if the Blender build changed.
2. Run `fleet_rebuild.py <unit>` (full chain, no patch). It exports and retains the new `base.glb`.
3. Refit the key tables (`gen.py`) and gate the patch against the new base (teardiag / dry stages). Fix the weights
   or the pose until it passes. Never relax the gate.
4. Restore `glbPatch` with the new table sha256s, then run `fleet_rebuild.py --from-base <unit>`.

Gate during step 3 against the new `base.glb`, never the previous one: before step 2 the retained base is still the
old mesh.

### DEF_Master in the tear gate

After the ops, the patch rebuilds `<unit>_DEF_Master` from the patched `Unit_*` clips, using build_unit.py's frame map
(master sync). The game never plays the master. A mapped master frame is a derived copy of a shipped pose.

- **One count per pose.** The stretch gate counts each shipped pose once, on its `Unit_*` clip. It skips the CS targets
  of mapped master frames on both the input and the output side, and the stamp records how many as
  `stretch.dedupedMasterTargets`.
- **Unmapped frames stay gated.** A master frame with no shipped counterpart keeps its keys and stays in the gate.
- **Thresholds unchanged.** `STRETCH_RATIO`, `WORST_STRETCH_SLACK` and the edge measure are the same as before.
- **Copy check.** `verify_master_copy` makes the dedup sound. Every mapped master frame must match its `Unit_*` pose
  joint by joint:
  - world rotation within `MASTER_COPY_TOL_DEG` (0.01 deg);
  - world position within `MASTER_COPY_TOL_POS` (1e-5 of body height).
  
  Otherwise the patch refuses. The stamp records the check as `masterSync.copyCheck`.
- **Griffin baseline.** Before the dedup, the griffin gate counted 4389 input edges; with it, 2182. The copy check
  measured a worst deviation of 4e-5 deg.

## Pilot: h3_jotunn_upg_alt fur hem

The floor-length back hem (rest height 0.007-0.02, Blender y > 0.18) went under the floor. On the unpatched base,
ground refuses at +0.091 below the sole. The hem needs an owner that stays on the floor during stance.

| owner of the hem | result |
|---|---|
| legs (the former cloakHold) | the knee swing takes it under: refused +0.091 |
| `Hips` | the 0.045·H pelvis drop takes it under: refused +0.042 / +0.057 |
| `Hips`, keep 0.5 | refused +0.053 / +0.064 |
| same-side foot (the shipped ops) | passes |

The shipped ops:
- `LeftUpLeg`/`LeftLeg` go to `LeftFoot`, and `RightUpLeg`/`RightLeg` go to `RightFoot`, inside y > 0.18 and z < 0.3.
- `Hips` is split by the sign of x to the same-side foot.

The results:
- The `--from-base` delivery passes every gate, and the chain is linked.
- `gateFaults` fell from 7 on the previously delivered GLB to none. The 7 were `ground:Death:dead`,
  `ground:Death:sinks`, `ground:Mouseover:sinks`, `ground:MoveStart:enters`, `ground:MoveStart:sinks`, `stride:ratio`
  and `stride:slip`.
- The idle rollout passes.
- The CS edges past 2x fell from 2138 to 1080, and the worst stretch stayed at 6.965.

## Griffin rampant idle (sitRepose, 2026-10-01)

User, in game: "the griffin's flight animation is much much better now, but ... its idle animation [is] terrible ...
quadrapeds miming on thin air". Commit 48028f8642 shipped the level flight together with an "s5 rampant stand" for
the sit clips. It set quadrupedSit fixed to {pitch 78, drop 0.04} and added Neck -5 / Head -25, Arm +30 / ForeArm
-60/-78 and wing fold offsets. The result:
- The body stands vertical on near-straight hind legs.
- The head bends back behind the shoulders into the raised wings.
- The forelegs paw the air.

The build's own sitfit IoU fell below no sit at all: griffin 0.475 to 0.421, royal 0.543 to 0.422, battle 0.492 to
0.447.

The fix is `sitRepose` on the sit clips, using the build's ease shapes. Its parameters:
- pitch 20, drop 0.06;
- Neck +20, Head +40;
- WingL_00 / WingR_00 -40;
- LeftArm -30.

The result reads as the DEF's rampant griffin: crouched planted hind legs, the beak leading the chest forward of the
swept-back wings, and one talon raised.

Measured on h3_griffin:
- Sprite-camera Idle IoU against DEF group 02: 0.462 to 0.555.
- Unit_Move: tracks and CS targets byte-identical to the frozen delivery.
- Tear edges past 2x over the sit-clip targets: 1537 to 1349.
- gateFaults: none before or after.

Neck turns of 45-90 degrees read slightly better but tore the neck skin past the lane's stretch gate on every
griffin. The head turn tears nothing.

h3_royal_griffin and h3_battle_griffin take the same op, measured in scratch with no added tearing (4289 to 4161
and 2676 to 2565). They cannot use `--from-base` yet: their bases are CS bake v2 (castle_slice_v1 carried them), so
each needs one full chain first.

### Four-legged sit (sitRepose foreLegs, 2026-10-01)

Coordinator review of the sit above: the forelegs still hang in the air, so the idle is a rampant three-point
stand, not the gargoyle-level four-legged sit asked for. Each griffin's `glbPatch` now runs two `sitRepose` ops:

1. Body lean: pitch 55, head +10, wings -40, no neck turn (Neck -10 tore the royal's skin past the gate). The drop
   is griffin 0.12, royal 0.125 and battle 0.11 H.
2. `foreLegs` on Unit_Idle and Unit_Mouseover (full), blended out over MoveStart and in over MoveEnd. Reach is 0 on
   the griffin and royal and 0.06 on the battle griffin: reach 0 to 0.04 added 4 to 95 torn edges there, while
   0.05 to 0.08 add none. Defence, Hitted, AttackFront and Death keep their own foreleg motion, because planting
   them there tore the shoulder skin (worst edge 5.5 to 7.8).

The lane's tear count is noisy at this scale. Royal drop 0.13 added 21 of about 9550 edges, and 0.125 adds none.

Measured on the three canonical GLBs after `fleet_rebuild --from-base` (offline skinned point-cloud sheet, 8 Idle
and 8 Mouseover times):
- Worst foot height above the floor: griffin 0.016 H, royal 0.016 H, battle 0.023 H.
- Unit_Move: untouched (flight).
- gateFaults: none.

The visual quality bar (the gargoyle) still needs the user's eyes in game.

## Deep hip and knee flexion (stretchRelax, 2026-10-10)

### The problem

A seated or kneeling collapse into a heap, as the HoMM3 DEF Death clips do, tore the skin past the lane's gate on
every unit that tried it. The torn edges were at the waist, crotch, hip side and back of the knee. On h3_giant_upg,
heap spec D3 went from 980 to 1512 torn edges (1199 with the arm tucks). The h3_mage robes added 1500 to 2100.

No weight op fixed it. Tried on the Titan:
- hip, waist and shoulder `diffuseWeights`;
- `moveWeights` of the arm and thigh bleed;
- spreading the fold over more spine joints;
- a kneeling variant.

Tried on the mages:
- a hem hold;
- the robe to `Hips`;
- a `Root`-anchored hem ramp;
- shin to thigh;
- diffusion;
- a Death-only accordion corrective.

The cause is linear blend skinning. Around a hard weight band it stretches a few rows of edges far past 2x, while
the edges a little further along the thigh and back stay near rest. Moving weights only moves the band. The tear
gate's threshold stays as it is (binding user policy).

### What the op does

`stretchRelax` (`tools/homm3_glb_patch/stretch_relax.py`) adds a per-pose corrective inside the CS re-bake, on each
CS target of the listed clips. It runs before the tear gate counts, so the gate, the morph-extent gate and every
delivery stage after it measure the corrected body.

Each target is relaxed in posed space, on weld groups (UV-seam copies move together):
- **Pull.** Every edge longer than `ratio` x its rest length pulls its two ends toward that length, half each. A group
  averages the pulls of its over-long edges.
- **Slide.** The pull is projected onto the posed surface's tangent plane. The skin slides along the body, so the
  silhouette and the volume stay.
- **Spread.** The displacement field is Laplacian-smoothed by `smooth`. The slack then comes from the near-rest
  edges around the fold, the material a real fold would pull in.
- **Pin.** A group whose blended skin matrix has a singular value under `SIGMA_MIN` (0.5) stays put at that pose.
  That is the candy-wrapper core of the fold. Without the pin, mapping back to rest space amplified a 0.06 slide to
  1.33 (Titan f4) and the morph extent rose from 0.08 to 0.79 H.
- **Map back.** The posed change goes back to rest space through each vertex's blended skin matrix and is added to the
  target.

Optional `bones` limits which vertices may move (any weight over 0.01 on the listed bones).

### Refusals

The op refuses:
- a slide past `maxMove` x the body height (default 0.05, at most 0.1): past that it is a reshape, not a strain limit;
- a rest-offset change past `maxMove / SIGMA_MIN`;
- a clip that is not in the GLB or carries no CS target;
- any op listed after it.

It changes no skin weights, keyframes, geometry, normals or images.

### Device and records

The iteration loop runs on CUDA by default (`HOMM3_CS_DEVICE`, no fallback). Its output is byte-identical to the
numpy reference. Skinning and the rest-space solve run on the CPU on both devices.

The stamp's `ops` and `csRebake.stretchRelax` record, per pose:
- torn edges before and after;
- the largest slide and the largest rest-offset change, as fractions of the body height;
- the groups pinned.

### Downstream stages

`cs_rekey` re-bakes only the clips that a later stage re-keys. For those clips it runs a parity check first, so a
corrected clip that some stage re-keys is refused, not silently overwritten. Do not list `Unit_Move` (stride match
re-keys it). Ground is a rigid motion and keeps the corrective.

### Proof: h3_giant_upg heap D3 (generated artifact)

Inputs:
- the retained base;
- the shipped ops;
- the D3 heap's body rotations and Hips translations, applied without its arm keys. The shipped chest tuck stays.
  These are the tables `key_rotations/h3_giant_upg_heapD3_body_{rot,tr}.json`, cut from `heapD3_rot/tr`.

| | edges past 2x (gate total) | worst stretch | Death clip | morph extent |
|---|---|---|---|---|
| base (gate input) | 980 | 7.549 | | 0.0835 H |
| heap, no corrective | 1199: **refused** | 8.895: **refused** | 683 | 0.0865 H |
| heap + `stretchRelax` ratio 1.7, 1000 iterations, smooth 0.4 | **870** | **7.053** | 354 | 0.0865 H |

Further measurements:
- **Slides.** Largest slide 0.037 H; largest rest-offset change 0.054 H.
- **Runtime.** 14 s for the whole patch on CUDA; the numpy reference took 35 s and gave the same GLB sha.
- **Other settings.** ratio 1.8 gave 946; ratio 1.6 with 1500 iterations gave 825.
- **Delivery stages.** stride match, CS re-key (re-baked Unit_Move only), ground and the rest pass when run in
  memory on the patched bytes.
- **Look.** At board distance the heap frames match the uncorrected ones. A stretch heatmap shows the red bands at the
  waist and flank spread into the 1.2 to 1.9 range.
- **Boards.** `V:/olden_port_work/authenticity/hipflex/` (`board_relax17`, `heat_death_heap.png`).

Not delivered, frozen or installed. The Titan's `glbPatch` is the authenticity lane's to change.

### Mages (dry run on the shipped configs, Death and Hitted)

- **h3_mage:** the gate total falls from 2911 to 2532 and the worst stretch from 11.84 to 7.95, with `maxMove` 0.08.
  That frees 379 edges against a heap's +1500 to 2100. On the Titan the op also removed about half of the heap's own
  added tears, so a retry may pass but is not proven.
- **h3_mage_upg:** the floor-length robe wants slides of 0.12 H, past the cap. That is a reshape, so the robe still
  needs more geometry there.

### Test

`python tools/homm3_glb_patch/test_stretch_relax.py --titan` checks schema refusals, fewer tears on a synthetic
sheet with in-plane slides, non-movable and pinned vertices left alone, welded seam copies, cpu/cuda byte parity, and
the Titan proof above.

## Proof tier

- Generated artifact: the patch, the CS parity, the stretch gate and the delivery-stage gates on
  `h3_jotunn_upg_alt`.
- Source/static: the validator, the unit tests, and the fleet_rebuild wiring.
- Not proven: bundle build, install, in-game appearance. `h3_jotunn_upg_alt` is not in `bulwark_slice_v1`, so
  shipping it needs a slice decision.
