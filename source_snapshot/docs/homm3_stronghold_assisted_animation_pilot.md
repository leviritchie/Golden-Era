# Stronghold Assisted Animation Pilot

2026-09-12. User-selected scope: animate the newly generated Ogre Mage and Boar
Rider before moving to any other unit. Roc remains paused.

## Result

Both new meshes now have genuine source-driven skeletal animation, generated
through the current capture, registration, capture-bone bind, shared skin fitting,
and per-clip export stages. These are not turntables or old saved unit animations.
Neither result is visually approved, installed, or runtime-proven.

Follow-up: [articulation audit](homm3_stronghold_articulation_audit.md) separates
geometry connectivity from independently measured weight-fitting damage. Do not
infer that every deformation in these previews requires replacement geometry.

Artifact root: `artifacts/homm3_mocap_v2/stronghold_animation_pilot_v1/`.

| Unit | Selected run | Linked timeline | Visible review |
| --- | --- | --- | --- |
| Ogre Mage | `ogre_mage/animation_v2` | 25 frames: Idle, Move, native Idle bookend, front attack | Stable recognizable Idle; reduced stride, incorrect weapon action, and thin-sheet arm deformation in attack |
| Boar Rider | `boar_rider/animation_v1` | 30 frames: Idle, real MoveStart, Move, real MoveEnd, native Idle bookend, front attack | Mount and rider move, but facing/lean diverges, overhead weapon action is missing, and attack deformation is poor |

Each run contains `report.json`, `clips/clips_manifest.json`, the fitted skin,
`preview/`, and `focused_preview/`. The focused preview re-renders the same saved
mesh/weights/motion at higher resolution and uses one joint source-and-mesh crop
over the entire reel. It does not crop each frame independently or modify motion.
GIF timing distributes centisecond rounding around the source 12 fps cadence.

The skin fitter returns `candidate_for_visual_review`, not acceptance. These
pilots train on every reel frame; there is no held-out evaluation. The legacy
report label `holdoutIouImprovement` must not be interpreted as independent
generalization evidence for these runs.

## Intervention Record

This is an assisted prototype, not an autonomous pipeline.

- Source identity and short clip selections were explicitly prepared for each
  unit. Ogre Mage uses corrected COGMAG imagery, not the obsolete base-Ogre path.
- Ogre Mage uses one fresh continuous Mixamo-conditioned source capture. Boar
  Rider uses two fresh captures of the same continuous Boar source reel, one for
  the mount and one for the rider. No Wolf motion was reused.
- Boar Rider's seated rest skeleton was manually seeded from actual front/side
  generated-mesh views. Primary body/seat/limb coordinates and terminal joints
  required intervention. This is substantive anatomical authoring, not automatic
  registration. Its anchor recipe and prior rejected scaffold are retained.
- Both static registrations required explicit visual review and candidate
  selection. Static confirmation permits the bounded trial; it is not animation
  or delivery acceptance.
- Boar composition holds the rider's seated root/lower-body policy. The existing
  direction retargeter also applies bounded regularization; the mount changed
  numerically, while the rider's regularization produced no numerical change.
  This is processed source-driven motion, not untouched raw rotation replay.
- After these inputs, binding, shared weight fitting, export parity, and replay
  executed automatically. No further pose hand-tuning was applied to hide the
  final visible defects.

## Shared Corrections

The run exposed general prerequisites that had not been exercised on these units:

1. Static compatibility assumed wing/body branch names. It now checks all
   explicitly owned branches and retains wing-specific tests only for actual
   wing pairs. Mounted names do not need fake aliases.
2. Skeleton placement scaled torso/head extent to the entire mesh. It now uses
   whole-skeleton extent/center and branch-balanced ranking, with a bounded
   extent search and complete joint ownership checks.
3. An already-authored rest skeleton in source-mesh coordinates was being fitted
   again. The explicit provenance-checked mesh-space path preserves that known
   relationship instead of shrinking or rotating it a second time.
4. The binder and skin fitter disagreed on exactly coincident exported vertices.
   The capture binder now uses float32 export-position weld groups and identical
   group distances before producing weights and allowed support. Consumer checks
   remain strict.

Focused registration, weld, and accepted-bind-consumption tests pass. The existing
build-wired attachment source-contract validator passes. Generated animation
output and source checks do not establish visual acceptance or game behavior.

## Scaling Requirement

The user explicitly permits LLM assistance, but expensive GPT-6 Astra-level
open-ended intervention is not an acceptable operating model for 200+ units.
Future unit processing must be workable with modest vision capabilities and
bounded cost. This has not been demonstrated by this pilot.

The intended division is standardized labeled views and short comparisons, a
small set of structured candidate/region decisions, and deterministic geometry,
fitting, checks, and bounded retries. Low-confidence or unresolved cases must be
reported rather than silently escalating to expensive expert reconstruction.
Manual 3D coordinate estimates and code changes in this pilot are explicit gaps
to eliminate or replace with that bounded interface, not reusable per-unit steps.
