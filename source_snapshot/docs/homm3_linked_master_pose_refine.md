# Linked-Master Pose Refine (Roc Pilot)

Owner: `experiments/homm3_mocap_v2/run_roc_wing_pose_refine.py`.
Contract tests: `test_pose_rotation_fk.py`, `test_linked_master_pose_refine.py`.

Proof tier: **generated candidate, pending visual acceptance**. Not imported,
built, installed, or game-visible. This stage is explicitly selected. It does
not change the skin-only solver and does not overwrite the original capture.

## Why this exists

The linked-master skin solver freezes bone motion. Some of those frozen local
rotations are reconstructed from joint positions with a minimum-change twist
prior (`minimum_change_prior_not_captured_evidence`). They are not all directly
observed motion. Idle / takeoff / landing can therefore keep the wings spread
even when the sprite shows a fold.

This pilot asks whether **sprite-driven correction of existing wing-joint
rotations** can produce a credible fold on the current mesh and skin. It does
not add per-frame weights, helper bones, or a new mesh.

## What it reuses

From a saved linked-master run (default `artifacts/homm3_mocap_v2/roc_linked_master_v2`):

- capture NPZ, bind GLB, fitted weights, texture, numbered source frames,
  calibrated camera, master-sequence provenance

It does not run Meshy, mocap, SmartRig, or a game rebuild.

## What it changes

Local rotations of joints in profile `regionJoints` keys that start with
`wing_`, on the full Idle cycle and the native MoveStart / MoveEnd frames.
Torso, root, legs, neck, bone lengths, bind pose, geometry, and weights stay
fixed. The complete Move clip is copied exactly. The MoveStart last frame and
the MoveEnd first frame stay on the original flight poses.

Optimization is fixed-length forward kinematics plus the existing
differentiable LBS and `SkinImageRenderer`. Camera and shared sprite canvas are
the saved ones. Comparison GIFs use the same target pixels as the objective;
independent per-sprite letterbox is forbidden. Close-ups apply one crop box to
all three panels.

Five deterministic starts, including unchanged capture, each receive an equal
slice of the 120 s GPU budget (24 s). Intermediate-joint fold seeds are
converted into each joint’s own parent frame. Axis-angle deltas are bounded by
vector magnitude of 2 rad, not per-component clamps. Each branch keeps a
constraint-satisfying checkpoint separately from the lowest aggregate-loss
checkpoint. Only eligible starts may be selected; image loss ranks them.

## Acceptance

Automated eligibility requires geometry, per-frame non-regression on optimized
frames, idle-loop and transition continuity, and unchanged flight/anchor
matrices. Geometry is per wing and per frame: span, absolute log edge-ratio
contraction and stretch, and triangle-area degeneration. Torso intersection
uses that frame’s torso box and is labeled `verified_clear`,
`verified_increased`, or `unverified` — never “no penetration.” A geometry
failure is `rejected_for_geometry`. That is not a proof that the mesh cannot
fold.

Visual acceptance is separate: a folded idle wing, no new takeoff/landing pop,
preserved flight. Improved IoU alone is not enough.

## Frozen v1

`artifacts/homm3_mocap_v2/roc_wing_pose_refine_v1` is frozen. Re-score it with
`--assess-npz` into a separate directory. Do not overwrite v1.

v1 established that the rotation→FK→renderer path runs. It did not establish
mesh impossibility. Its original GIFs used independently letterboxed sprites.
Its geometry gate could miss a one-wing collapse. Its search gave almost the
whole budget to one early winner.

Corrected metrics for the saved v1 rotations live in
`artifacts/homm3_mocap_v2/roc_wing_pose_refine_v1_reassess` (schema
`homm3.linked-master-pose-refine.v2`). Disposition:
`rejected_for_geometry`. Flight and pinned-anchor matrices stayed unchanged.
Idle mean IoU still rose by +0.0202, but idle frame 4 fell by 0.0041. Takeoff
mean IoU rose by +0.1594 and landing by +0.1137. Geometry failed because the
right-wing minimum triangle-area ratio worsened (0.00852 → 0.00724) on a mesh
that already has rest-relative degenerate triangles. Continuity failed on the
idle loop (frames 0–7) and the takeoff-to-flight pair (10–11): surface
displacement grew while the pinned matrices themselves stayed put. The
reassess GIFs use optimization-target pixels and one shared close-up crop.
Visual review: the idle wing remains spread. This is not a proof that the
mesh cannot fold.

## Balanced v2 pilot

`artifacts/homm3_mocap_v2/roc_wing_pose_refine_v2` ran the full Idle /
MoveStart / MoveEnd scope with five equal 24 s slices (53–57 steps each;
123 s GPU; no leftover dump onto an early winner). Magnitude bound: vector
norm 2 rad; no start saturated it.

| Start | Eligible checkpoint | Idle mean IoU | Takeoff | Landing | Geometry | Disposition of best-loss state |
|---|---|---:|---:|---:|---|---|
| `capture_control` | opening / original only | 0 | 0 | 0 | pass | continuity + per-frame IoU |
| `fold_0.4` | none | −0.0117 | +0.1445 | +0.1076 | pass | continuity + per-frame IoU |
| `fold_0.4_mid_0.2` | none | −0.0214 | +0.1738 | +0.1059 | pass | continuity + per-frame IoU |
| `fold_0.8` | none | −0.0272 | +0.1884 | +0.1149 | fail (contract, stretch, triangles) | geometry + continuity + IoU |
| `noise_0.15` | none | +0.0009 | +0.1533 | +0.0986 | fail (contraction) | geometry + continuity + IoU |

Selection kept `capture_control`’s opening state because it was the only
eligible checkpoint. Aggregate image loss on later capture_control steps
fell (0.536 → 0.465) and optimize-frame IoU rose (0.540 → 0.603), but those
states failed continuity and per-frame non-regression, so they were not
promoted. Flight stayed identical. Export readback parity succeeded on 66
frames. All five starts were written under `starts/`.

Visual acceptance is rejected: the selected reel is the original spread-wing
idle. The fold starts change the silhouette but do not produce a sprite-like
folded idle wing. Automated eligibility and visual acceptance remain
separate. Mesh feasibility is unresolved.

### What the failure points to

The limiter is the **objective and its constraints**, not search allocation
and not a mesh-impossibility proof.

- Takeoff and landing source frames start at much lower IoU (~0.35–0.38)
  than idle (~0.60). The batch image term therefore spends the step budget
  matching those clips. Fold starts raise takeoff/landing IoU while idle
  mean IoU falls.
- States that improve aggregate image loss break idle-loop or
  takeoff-to-flight surface continuity, or they regress at least one
  optimized frame. Eligibility therefore retains only the unchanged
  capture.
- Milder fold seeds passed the corrected geometry gates; `fold_0.8` and
  `noise_0.15` worsened contraction (and `fold_0.8` also stretch and
  triangle area). That is deformation behavior on those starts, not a
  demonstration that no fold exists.

Do not relax thresholds to pass this candidate. No deployment.

## Idle-bind mesh comparison

`artifacts/homm3_mocap_v2/roc_linked_master_idle_bind_v1` plus
`roc_wing_pose_refine_idle_bind_v1` used a new Meshy T2 from corpus idle
frame 000 and bound at global index 0. Capture hash matched the move-bind
v2 reel. Skin fit is `rejected_generalization_or_deformation_gate`. Pose
refine again kept only the unchanged capture start (`rejected_idle_mean_iou`).
Visual: idle still reads as a top-down spread bird against a side-profile
sprite; flight frames collapse the standing surface. This does not prove a
fold is impossible. It shows that changing the T2 rest to idle does not, by
itself, produce a credible idle or keep flight.

## Not this iteration

Whole-body pose search, linked-master replacement, skin refit, delivery
validator, generalization, and runtime proof are separate milestones.
