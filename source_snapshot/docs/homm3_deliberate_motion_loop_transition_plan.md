# HoMM3 Deliberate Motion, Loop, and Transition Plan

Status: implementation in progress. Stronghold generated-artifact baseline exists; full-animation readiness is not claimed.

## Objective

Make every shipped skinned animation move only when the authentic sprite and
authored landmarks support that movement, while making cyclic clips close
cleanly and movement states enter and exit through deliberate transitions.

The success criterion is not merely lower angular velocity or a smoother GIF.
A clip must:

1. retain the source animation's meaningful motion;
2. reject bone and root motion that does not improve the corresponding source
   motion;
3. close cyclic pose and velocity boundaries;
4. meet the adjacent state's pose and velocity at every declared transition;
5. play through the native Animator state machine without a runtime polling or
   `Play`/`CrossFade` workaround.

## Current diagnosis

The user-visible jerk has several connected causes. They need one shared
motion-lifecycle contract rather than independent fixes.

- The shipping keep in
  `tools/homm3_silhouette_pose_fit/gpu_cascade_delivery.py` requires temporal
  consensus and physics smoothing, but explicitly rejects the existing
  sprite-aligned motion lane. The solver can retain frame-local wins as small
  as `1e-6`; still-sprite and sprite-change gates are disabled by default.
- `cascade_sprite_aligned_motion.py` already contains the correct root
  principle: compare a proposed bone/root step with holding the prior pose,
  retain the step only when local source appear/disappear motion improves by a
  meaningful margin, and otherwise hold exactly. It is experimental and not
  ready to promote unchanged: a global still lock previously froze legitimate
  motion, and occupancy alone cannot see every purposeful movement inside an
  unchanged silhouette.
- The current smoother is a metric-free, endpoint-linear cleanup pass. It can
  reduce twitch amplitude, but it cannot decide whether a movement is
  meaningful, preserve a cyclic trajectory, or establish a transition.
- Loop metadata exists in Unity. `Homm3OwnedSkinnedLabBuild.cs` sets
  `loopTime=true` for Move, Idle, Mouseover, and Defence. That flag repeats an
  open clip; it does not close the clip.
- `write_gpu_cascade_clip_glb` writes `N` source poses at
  `0 .. (N-1)/fps` seconds. A loop therefore omits the final source-frame
  interval and jumps from the last pose directly to frame 0. Existing shipped
  assets have no mandatory seam report, so the size and distribution of that
  discontinuity are not yet authoritative until Phase 0 writes the baseline.
- Idle-leading semantic sequences are fitted together and then sliced into
  separate clips. The slicing contract checks indices, not pose or velocity at
  Idle wrap, Move wrap, Idle -> MoveStart, MoveStart -> Move, Move -> MoveEnd,
  or MoveEnd -> Idle.
- Several generated MoveStart and MoveEnd clips contain only one source pose.
  A one-pose asset cannot express a transition and must not pass full-animation
  readiness.
- The stock Esquire controller routes ordinary ground locomotion directly
  between Idle and Move. MoveStart/MoveEnd are used by fly, teleport, stance,
  and ability paths, not by ordinary walking. The data can contain correct
  transition clips while ground movement never plays them.
- Existing validators prove pose units, smoothing provenance, frame indexing,
  quaternion serialization, and some static Unity structure. They do not prove
  deliberate movement, loop closure, transition closure, or runtime state
  flow.

## Locked architecture

### 1. One lifecycle contract

Add one fail-closed `DeliberateMotionContract` generated per unit and consumed
by every fitted sequence, the solver, exporter, Unity builder, validators, and
preview harness. Do not infer different policies independently from suffixes in
Python and C#.

The unit contract names exactly one canonical Idle producer and, for mobile
units, exactly one canonical Move producer. Every action/transition solve
freezes and reuses phase anchors from those canonical cycles. A fitted sequence
may not emit a second incompatible Idle or Move and pass merely because its own
local boundaries close.

Each clip row declares:

- authentic DEF group and frame inventory;
- contract name and lifecycle role: `cycle`, `entry`, `exit`, `one_shot`, or
  `terminal`;
- authoritative frame-duration and exact cycle/terminal duration policy;
- predecessor and successor edges;
- whether root, branch, and individual-joint motion are permitted;
- authored landmark source and provenance;
- source motion-evidence regions and owning skeleton branches;
- loop and boundary pose/velocity limits;
- native Animator state, parameter, expected transition path, and the unique
  emitted Unity clip asset for that state role.

Lifecycle belongs to an emitted Unity asset, not merely to reusable source
poses. When the same source poses feed incompatible controller roles, emit
separate named assets and mappings. For example, looping Stance and one-shot
Victory cannot share one `Defence.anim` because one `.anim` has only one loop
flag. Shared source provenance is allowed; shared lifecycle identity is not.

Initial lifecycle policy:

| Contract | Role | Required behavior |
|---|---|---|
| Idle | cycle | deliberate low-amplitude motion only; C0/C1 closed |
| Move | cycle | deliberate locomotion only; C0/C1 closed |
| MoveStart | entry | Idle anchor -> Move phase anchor; never loops |
| MoveEnd | exit | Move phase anchor -> Idle anchor; never loops |
| StanceLoop / other held states | cycle | dedicated looping asset |
| Victory / skills / rare reactions | explicit per controller state | dedicated one-shot or cycle asset matching that state |
| Attack / Shoot / Hitted | one_shot | deliberate action, then compatible Idle return |
| Death | terminal | never loops and never returns to Idle |

Missing authored landmarks, absent source groups, a one-pose transition, an
unknown Animator mapping, or an unclassified edge is an error. A unit with a
one-pose MoveStart or MoveEnd remains blocked from the new full-animation lane
until source-supported authored transition evidence exists. Do not invent the
missing motion, retain its invalid full-animation payload, substitute Idle, or
map an action onto a convenient clip.

### 2. Deliberate motion is the primary authority

Build a source-motion ledger before optimization. It combines explicit,
declared evidence rather than using one broad image heuristic:

- authored 2D landmark displacement for the skeleton branch;
- alpha occupancy appeared/disappeared masks;
- region-scoped chroma/depth change for purposeful internal motion that does
  not change the outer silhouette;
- registration-root displacement as evidence only, plus declared armature-root
  attitude or pelvis motion when the source actually supports it.

Convert contiguous evidence into **motion islands**: a branch, a frame range,
and an expected direction/magnitude envelope. Frames and branches outside
those islands are held, not merely penalized.

Change proposal ownership from independent per-frame joint wins to complete
branch trajectories. Use the existing branch/chain configuration-space lane to
propose motion, then exact-raster and landmark-score the complete articulated
trajectory. There is no fallback from a rejected branch trajectory to small
independent joint changes.

For every significant branch/root step, score a counterfactual in which that
branch is held at its island-entry pose. Retain the full proposed motion only
when all of the following are true:

- the affected local source-motion pairs improve by the calibrated minimum;
- no affected boundary pair regresses beyond tolerance;
- authored landmark error improves for the branch, or an explicitly declared
  regional appearance channel supports the motion;
- per-frame appearance/collision quality stays above the accepted floor;
- motion economy is reasonable: large geodesic travel cannot buy negligible
  visible or landmark gain.

Otherwise hold the branch exactly. Do not scale every rejected step to a
smaller twitch.

The deliberate-motion gate must also reject the opposite failure: a perfectly
still mesh over a moving source. Every material source-motion island needs a
minimum rendered-motion and landmark-motion recall.

### 3. Physics is bounded polish, not authority

After deliberate motion passes, retain physics stabilization as a bounded
secondary operation inside accepted motion islands. It must not:

- create a new moving branch/frame;
- erase required motion recall;
- change a held region;
- break loop or transition boundaries;
- rescue a clip that failed the deliberate-motion gate.

The current smoothing requirement stays in place during the pilot, but it runs
only after the raw deliberate trajectory has passed. Promotion may replace the
old boolean-only `physicsSmooth.enabled` gate only after the new gate proves
whole-clip angular velocity, acceleration, jerk, rendered-vertex step, and
bounded deviation from the accepted deliberate trajectory. Stabilization
provenance remains mandatory either way. Smoothness alone is never ship
authority, and smoothing cannot turn a failed raw motion report into a pass.
Loop clips require circular boundary conditions; transition clips require
fixed entry/exit anchors.

Motion-channel ownership is explicit:

- source registration/camera root is scoring evidence only and is never
  serialized into the battle clip;
- native battle movement transform owns world translation;
- armature-root local rotation is serialized only when explicitly declared and
  supported;
- pelvis/hips local motion is ordinary skeletal motion and must pass the same
  deliberate-motion authority as other branches.

Validators must not credit a registration-root improvement as delivered motion
when the exporter intentionally discards that channel.

### 4. Segment-aware loop and transition solve

Fit the complete semantic chain with explicit subsegment topology, not one
global `loop_enabled` flag:

```text
Idle(cycle) -> MoveStart(entry) -> Move(cycle) -> MoveEnd(exit) -> Idle(cycle)
```

The canonical Idle/Move cycles are solved first and become immutable anchor
authority for every later sequence. Within the coupled solves:

- enforce quaternion-geodesic pose closure (C0) on Idle and Move;
- match seam angular velocity (C1) using the last two and first two poses;
- score the wrap pair as a real source-motion pair;
- select a stable cycle phase that minimizes both entry and exit mismatch;
- anchor MoveStart first pose to the chosen Idle phase and its last pose to the
  chosen Move phase;
- anchor MoveEnd first pose to the chosen Move phase and its last pose to the
  chosen Idle phase;
- align one-shot endings with the return-to-Idle anchor; Death has no return
  edge.

Only slice groups into ship clips after the coupled solve produces and records
a passing boundary report. Preserve those metrics in the delivery manifest.

### 5. Correct authored timing at export

Do not infer playback cadence from a directory named `source_12fps`, a solver
job FPS, or stock Esquire clip duration. The lifecycle row carries an
authoritative `frameDurationSeconds` derived and validated in Phase 0 from the
DEF timing/locked source-preview timing and the native state's timing owner.
Do not silently stretch clips to stock durations.

The current canonical preview contract is 180 ms per authentic source pose.
Phase 0 must either carry that timing into delivery or document and prove the
state-specific gameplay owner that requires a different duration.

- A cycle with `N` authentic poses gets keys for those poses at
  `0 .. (N-1)*frameDuration`, plus a quaternion-sign-aligned copy of frame 0 at
  `N*frameDuration`.
  Report `sourceFrameCount=N`, `keyCount=N+1`, and
  `cycleDurationSeconds=N*frameDuration`.
- MoveStart and MoveEnd receive explicit terminal keys only as required by
  their validated entry/exit timing rows.
- Attack, hit, death, audio-cued, and other one-shot states retain their current
  timing until a static and runtime trace identifies the gameplay/SFX completion
  owner. Their terminal-hold policy is explicit per state, never a blanket
  exporter rule.
- Perform circular shortest-arc quaternion sign alignment for cycles before
  Unity import. Continue to copy local rotations only and keep
  `applyRootMotion=false`.
- Keep `loopTime=true` for declared cycles and false for other roles.
  `loopBlend` may not be used to hide a failed seam.

Update the existing exporter tests that currently pin the `N-1` interval
convention and update the rollout validator that treats an 8-pose Idle ending
at key 7 as the complete period.

### 6. Native Animator owns state flow

Create a project-owned controller derived structurally from the stock donor
controller. Preserve native parameter names, battle-speed behavior, action
triggers, AnyState paths, and native animator-field ownership.

Change ground locomotion to:

```text
Idle --move=true--> MoveStart --exit--> Move
Move --move=false--> MoveEnd --exit--> Idle
```

Define interruption rules in the controller for `move` cancellation during
MoveStart and reassertion during MoveEnd. Preserve the existing start/loop/end
semantics for Fly, Teleport, Stance, and their ability variants. Do not add an
`Update()` poller, runtime state guessing, or `Animator.Play/CrossFade` repair.

Ground stop uses the authentic canonical Move exit phase: when `move` becomes
false, the controller finishes only to the next declared phase anchor, then
plays MoveEnd. It does not transition from an arbitrary gait pose. The unit
contract declares the maximum resulting visual stop latency (never more than
one Move period); Phase 0 calibrates the player-approved bound. A clip that
cannot meet that bound remains blocked until an additional source-authored exit
path exists. During this visual completion, native battle translation has
already stopped and is never animation-owned.

## Implementation phases

### Phase 0: Baseline and classification

1. Add a read-only audit over current payloads, exported GLBs, Unity clips,
   override mappings, and installed bundle readback.
2. Inventory source-motion evidence, significant branch/root steps, held
   counterfactual scores, loop seams, transition seams, clip durations, and
   Animator paths.
3. Trace the authoritative frame-duration owner for preview, battle state,
   gameplay completion, and SFX; write timing into lifecycle rows instead of
   assuming solver FPS.
4. Measure canonical Move period and establish a player-approved maximum stop
   latency for the chosen phase-anchor exit. Block units that cannot meet it.
5. Separate metrics for current raw output, current physics-smoothed output,
   and installed Unity output. Do not compare unlike proof tiers.
6. Select three bounded pilots from complete authored data: one ground walker,
   one flyer, and one compound or multi-limb unit.
7. Calibrate thresholds from the audit and player-approved reference previews;
   do not invent universal degree or pixel limits before measuring skeleton
   classes.

Deliverable: `deliberate_motion_baseline.json` plus a short human-readable
report listing the worst unsupported movements and worst six boundaries.

### Phase 1: Deliberate-motion pilot

1. Add the lifecycle/source-motion schema and fail-closed loader.
2. Promote the existing local appear/disappear hold counterfactual into a
   motion-island/branch trajectory gate.
3. Integrate authored landmark motion and explicit regional appearance evidence
   so inner-silhouette movement is not incorrectly frozen.
4. Run matched-budget **raw authority** comparisons with physics smoothing
   disabled: current pre-smooth keep versus deliberate branch keep-or-hold.
   Then apply the same bounded stabilization to both passing raw candidates for
   the shipping comparison. Do not compare a stabilized control with an
   unstabilized experiment.
5. Produce selectable previews showing source, current ship candidate,
   deliberate candidate, motion-evidence overlay, held frames, and the exact
   loop/transition boundary.

Promotion gate: higher deliberate-motion precision without loss of required
motion recall or accepted appearance quality. A smoother result is not enough.

### Phase 2: Topology-aware solve and export

1. Establish and freeze the one canonical Idle and Move producer per unit.
2. Add cyclic and anchored boundary constraints to the branch trajectory solve.
3. Couple the full Idle/Move semantic chain, then slice only after boundary
   validation.
4. Add cycle closing keys and explicit lifecycle timing to GLB export; leave
   action terminal timing unchanged until its native owner is proven.
5. Make residual stabilization circular or anchor-preserving and gate its
   deviation/velocity/acceleration/jerk.
6. Emit lifecycle, motion, seam, timing, and channel-ownership reports in every
   delivery manifest.

### Phase 3: Animator integration

1. Export the donor controller state graph through Unity Editor APIs.
2. Generate or maintain one project-owned native-compatible controller from a
   checked structural contract.
3. Route ground movement through MoveStart and MoveEnd.
4. Import clips using lifecycle rows, not an independent suffix loop table.
5. Add a headless Animator harness that drives real parameters and samples all
   skinned bones and rendered vertices at 60 Hz.

### Phase 4: Validators and build/deploy gates

Add a focused validator wired into normal build/deploy. It must fail on:

- missing or ambiguous lifecycle/source-motion classification;
- multiple or incompatible canonical Idle/Move producers;
- one emitted Unity clip reused by states with incompatible lifecycle roles;
- significant bone/root travel with no passing hold counterfactual;
- frozen rendered output over material source motion;
- excessive motion travel per unit of visible/landmark gain;
- excessive whole-clip angular velocity, acceleration, jerk, rendered-vertex
  step, or stabilization deviation inside an accepted motion island;
- appearance/collision regression below the accepted floor;
- failed Idle or Move C0/C1 seam;
- failed declared cross-state boundary;
- one-pose entry/exit clips;
- incorrect source-frame/key count or duration;
- wrong Unity loop flag, curve type, hierarchy binding, or override mapping;
- controller graph/conditions that bypass declared ground entry/exit states;
- stop latency above the declared phase-anchor limit;
- serialized registration/camera-root travel, root translation/scale curves, or
  enabled Unity root motion;
- changed action/gameplay/SFX completion timing without a passing owner trace.

Write one structured quality report per unit and one aggregate report. Always
list the worst offending bones, frames, branches, and edges rather than only a
pass/fail boolean.

### Phase 5: Rollout and proof

1. Pass unit tests and intentionally broken fixtures.
2. Pass the three-archetype generated-artifact pilot and player preview gate.
3. Rebuild a bounded Unity bundle wave and inspect assets through Editor APIs.
4. Read back the installed Golden Era bundle and controller assets.
5. Use existing Animator telemetry, extended with expected state/clip and seam
   sampling, to prove runtime state flow.
6. Run user-visible battle smoke before broad rollout.
7. Roll out by skeleton/species class, not all units at once; each wave keeps
   its own failure inventory and proof record.

## Required test matrix

### Deliberate-motion fixtures

- still source plus a 40-degree one-frame bone pop: hold it;
- moving limb plus frozen mesh: fail motion recall;
- one affected pair improves while the adjacent pair worsens: reject;
- real branch swing improves the declared evidence: retain full swing;
- large internal bone travel with unchanged rendered/landmark evidence: reject;
- root movement that improves fill but not declared motion direction: reject;
- seamless statue over a moving loop: fail deliberate-motion recall;
- deliberate movement with a bad wrap: pass motion authority, fail continuity.

### Offline Animator matrix

- Idle for at least three wraps;
- Move for at least three wraps;
- Idle -> MoveStart -> Move -> MoveEnd -> Idle;
- cancellation during MoveStart and restart during MoveEnd;
- stops from representative Move phases;
- Fly, Teleport, and Stance start/loop/end paths;
- Attack/Damage and each emitted skill/stance/victory role's return behavior;
- Death terminal behavior;
- slow, default, and fast battle speed;
- battle prefab, unit preview, and adventure-map surfaces.

For every case, assert state/clip sequence, transition time, loop count, maximum
sampled pose/vertex step, deliberate-motion report identity, and no final-pose
hold where a cycle is required.

### Visual gate

Generate DQS-lit, source-timed reels with boundary markers:

- three Idle cycles;
- three Move cycles;
- full ground start/loop/stop chain;
- one action-to-Idle chain;
- one flyer chain.

Show the authentic sprite strip, current installed behavior, deliberate
candidate, motion-evidence overlay, and held/rejected branch decisions. Keep the
pilot small and selectable so the user remains the visual authority.

## Non-solutions

- enabling `loopTime` or `loopBlend` without closing the authored trajectory;
- increasing physics stiffness or adding another low-pass filter;
- accepting lower mean angular velocity as proof of deliberate motion;
- global still-frame locking based only on RGB MAD;
- fixing every seam with a generic crossfade;
- stretching authentic clips to donor durations;
- inferring playback duration from solver FPS or a folder name;
- runtime `Update()` polling or manual `Animator.Play/CrossFade` calls;
- silently mapping missing MoveStart/MoveEnd/action clips to Idle;
- falling back from a rejected branch trajectory to independent joint twitch.

## Proof ladder and completion criteria

Proof must be reported without promotion:

1. source/static validated;
2. generated artifact validated;
3. Unity build target proven;
4. deployed/installed payload read back;
5. startup smoke proven;
6. runtime Animator state and seam behavior proven;
7. user-visible gameplay proven.

This plan is complete only when the build/deploy validator is mandatory, the
installed payload passes, and the user-visible battle matrix demonstrates
deliberate motion, closed Idle/Move cycles, and correct movement return to Idle.

After proof, update `docs/homm3_full_creature_animation_pipeline.md`,
`docs/surfaces/custom_unit_skinned_mesh.md`, and the pose-pipeline skill. Remove
the current contradictory duration and physics-smoothing-as-readiness language
rather than leaving historical claims beside the new contract.
