# Sprite-Guided Surface Exceptions

Status: **diagnostic prototype, not an accepted folded-wing animation**.
This is an explicitly selected source-frame correction layer, not an automatic
fallback from skeletal animation. It does not claim that a mesh is incapable
of a pose merely because a search failed.

## Mechanism

1. Compare the same immutable mesh, skin, capture, source frames and camera
   against at least two distinct corrected pose contents. Independently replay
   each pose through the fixed skeleton and skin before using its geometry.
2. Find faces where those attempts improve source-view agreement while
   repeatedly worsening compression or stretch. Require global silhouette gain
   and lower mean visible residual on the same face, not image improvement
   elsewhere. Missing sprite pixels remain unowned source-space evidence.
3. Reject visibility-loss evidence: a candidate face must retain at least half
   its baseline covered pixels to contribute a vote. This and the numerical
   tolerances are conservative diagnostic policies, not calibrated classifiers
   or proof of correct hidden anatomy.
4. An explicit source-clip selection may fit a local corrective surface. The
   support is selected-clip conflict faces, a declared source-topology
   neighborhood, and exact rest-position/skin-weight duplicate groups. No bone
   names, custom feather geometry, or inferred anatomical labels select it.
5. Fit direct source-frame residual positions with fixed topology, texture,
   skeleton, weights and camera. Surface, spatial, temporal and depth penalties
   constrain the diagnostic. Preserve every unselected frame and unsupported
   vertex exactly. Show source/original/candidate and an alternate fixed view.

The field deliberately does not compress evidence into captured-pose PCA
features: a bad capture may not describe the missing source state. Conversely,
these direct source-frame controls do not generalize to unseen poses. They are
not yet a runtime corrective driver, morph-target export, or transition system.

## Current Measured Pilot

Artifact: `artifacts/homm3_mocap_v2/sprite_exception_surface_v2/`.
Selected source clip: `g02_idle`, eight frames. Both prior pose candidates
replayed with maximum vertex error zero. Forty-seven conflict faces seeded the
fixed four-ring neighborhood; after exact duplicate expansion, 822 of 10,921
vertices were editable. Every other source frame and unsupported vertex is
bit-identical to the original saved linked-master candidate.

The fit completed 5,410 steps in the 120-second allocation. Mean idle silhouette
IoU rose from 0.616993 to 0.636538; each idle frame improved. Worst-frame p95
stretch decreased from 2.287582 to 2.266129, and worst-frame worst-one-percent
log strain decreased from 2.435391 to 2.423861. These aggregate improvements do
not establish per-face quality or collision safety. Maximum correction was
0.114294 world units. The source-view and side-view GIFs each contain eight
frames and last 670 ms, retaining the source timing within GIF precision.

The visible change is modest. The open-wing appearance is not resolved, and
the original surface already exceeds normal stretch/compression limits. The
prototype demonstrates local detection and correction, not complete recovery
of a folded shape. A complete corrective state may need larger coherent
surface ownership or authored source correspondences; do not silently widen
the support, displacement budget, or quality limits to make this pilot pass.

Earlier `sprite_exception_surface_v1` is superseded diagnostic evidence: its
detector counted disappearing faces as image improvement and its optimizer
steps were too large. Do not use it as validated exception-selection evidence.

## Ownership And Validation

- `pose_representation_exception.py`: same-face repeated-conflict detector.
- `sprite_surface_residual.py`: explicit source-frame correction field.
- `run_sprite_exception_pilot.py`: provenance, selection, bounded fit, previews.
- `tools/validate_homm3_attachment_pipeline_contract.py`: existing normal-build
  gate now also pins detection/visibility/reconstruction and non-delivery scope.

Seventeen focused CPU tests passed, including hidden-face exclusion, duplicate
support, vector bounds, nonfinite reconstruction rejection, topology selection,
unowned source residuals and source-contract mutation negatives. The source
validator passed. Reviewer findings on visibility and pose-trial provenance
were addressed; the final finite-reconstruction guard has a regression test.
No GLB was exported, no game build or deployment occurred, and neither runtime
behavior nor transitions were validated.
