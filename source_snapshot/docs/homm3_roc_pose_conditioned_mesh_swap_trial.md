# Roc Pose-Conditioned Mesh Swap Trial

This trial evaluates a bounded alternative to forcing one Roc surface to survive every
animation pose. The existing Meshy move-bind surface is retained as the flight/control
surface. A second Meshy surface is generated from a difficult attack-down source pose,
then replayed through the same captured skeleton only for the frames where that pose is
known to expose the control surface's failure.

## Current evidence

- The earlier hand-authored custom replacement lane was abandoned. Its generated
  artifacts were deleted to reclaim space; the source scripts remain as historical
  tooling and are not part of this trial.
- `roc_move_bind_t2_v1` is the control candidate. Its linked reel shows a recognizable
  flight mesh, but it remains flight-shaped during the attack-down clip.
- `roc_attack_down_bind_t2_v1` and `v2` were generated from attack-down frame 04. The
  v2 prepared-image candidate was rejected by visual review because its torso became a
  broad featureless mass and its feet disappeared.
- `roc_attack_down_bind_t2_v3` is generated from attack-down frame 03, where the Roc is
  front-facing with level wings and visible feet. Its generated-candidate contact sheet
  is the current comparison artifact:
  `artifacts/homm3_mocap_v2/roc_attack_down_bind_t2_v3/preview_v9/attack_down_pose_swapped_contact.png`.

The preview is deliberately phase-gated (`f03-f04`) so the replacement is visible
beside the control and source. The v3 comparison also applies a derived, bilateral
outer-wing rotation to f04 only: each wing rotates around its detected attachment while
its tip follows the corresponding source sprite's shoulder-to-tip slope, with the
influence tapered continuously across the full wing; the torso and root region stay
fixed. An enlarged before/after marker diagnostic is emitted next to the contact sheet,
along with a torso-scale/shoulder-aligned source/candidate overlay that draws both
shoulder-to-tip lines.
It uses a temporary nearest-joint weight field and uniform AABB alignment; this is a
visual hypothesis test, not a shipping bind or a runtime proof. Different Meshy
topologies cannot be vertex-blended directly, so any future transition treatment must be
an explicit image-space preview or a separately validated warp/remesh stage rather than
an implicit topology fallback.

## Acceptance gate

Do not promote a pose-conditioned surface until a visual reviewer confirms that the
replacement preserves a recognizable head/beak, torso proportions, feet, and wing
silhouette at its bind pose and does not introduce a visible discontinuity at the gate.
After acceptance, build a proper owned-bind candidate and validate it through the normal
delivery contract. Until then all artifacts in this trial are generated-candidate
evidence only.
