# Pose Refinement Objective Follow-Up

Owner: `experiments/homm3_mocap_v2/run_roc_wing_pose_refine.py`.
Shared losses: `linked_master_pose_refine.py`.

## Current Evidence

The 2026-09-12 capture-only follow-up is a **generated, rejected diagnostic**,
not a newly accepted bind, approved animation, or deployed asset. Inputs are the
saved linked-master v2 capture, bind, camera, skin, and texture. No helper bones,
mesh edits, per-frame weights, or anatomy-specific initializers were used.

Artifact: `artifacts/homm3_mocap_v2/takeover_gate_aligned_v2`.
Changed preview and measurements are under
`starts/capture_control_best_loss_unaccepted/`, not the top-level selected reel.
The selected eligible checkpoint remains unchanged; its top-level export parity
does not establish export parity for the changed diagnostic.

The single capture-initialized branch completed 268 steps in its 120-second
search allocation. Mean silhouette-IoU gains were +0.014912 for Idle, +0.121747
for MoveStart, and +0.096956 for MoveEnd. No optimized frame regressed beyond the
existing tolerance. Flight vertices remained bit-identical, and existing idle
closure and transition gates passed.

Geometry still rejects the changed state. Right-wing maximum log contraction
rose from 2.303650 to 2.726127, and its minimum rest-relative triangle-area ratio
fell from 0.008520 to 0.005139. This is not evidence that the mesh cannot fold.
The idle silhouette also remains visibly unlike a properly folded source wing.
The next unresolved problem is deformation, not permission to relax the gate.

## Implementation And Verification

The objective now includes the playback-boundary pairs used by acceptance and
each optimized frame's own IoU non-regression check. Continuity uses squared
excess normalized by existing slack. IoU uses linear excess so its restoring
gradient does not disappear near the threshold. Final acceptance gates are
unchanged; finite penalties do not guarantee feasibility.

Angular loss forward values use the gate's float64 trace-based calculation,
including imperfect capture rotations. Only the derivative is bounded near
singular endpoints. `--capture-only` explicitly allocates the search budget to
the original capture without generating fold/noise starts. Lowest-loss states
are retained separately and visibly labeled unaccepted diagnostics.

The preview no longer multiplies already-premultiplied RGB by alpha again. GIF
centisecond rounding preserves total source timing. The changed pilot GIF has
16 frames and a 1.33-second duration; it concatenates Idle, MoveStart, and
MoveEnd, excluding the unchanged Move cycle. Fourteen frames changed.

Validation: 36 focused pose/rotation tests passed, including imperfect-matrix
parity, finite gradients, near-threshold IoU gradients, and build-guard mutation
negatives. The existing normal-build attachment validator checks that both
constraints remain in the objective. The source validator passed. A review
agent found no blocking issues. No game build, installation, or runtime test was
performed.
