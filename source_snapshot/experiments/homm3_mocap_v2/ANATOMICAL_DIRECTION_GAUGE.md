# Explicit Anatomical Direction Gauge

For the subsequent full-hierarchy experiment and its rejected visual results,
see `ANATOMICAL_CAPTURE_TRIAL.md`. This document records the isolated primitive.

## Current Evidence

Diagnostic primitive only; not integrated into production reconstruction or
validated on animated meshes. No new animation candidate is accepted.

`reconstruct_adapted.one_to_one_bone_chains` constructs single-edge chains.
`direction_retarget.transfer_chain_directions` builds source and target rest
frames using `_polyline_hint`; with a single edge there is no adjacent segment,
so the hint is world Y. The target rest direction is accounted for, but the
plane around that direction is selected by a world axis, not anatomical data.

A reproducible fixture uses source rest X, target rest (1,1,0), and source pose
rotated 35 degrees around Z. A common coordinate rotation of 32/61/17 degrees
around X/Y/Z should merely rotate the output direction. The current one-edge
path instead changes the answer by 5.712279411 degrees. This is coordinate
dependence, not evidence of the magnitude of an error in any particular bird.

`anatomical_direction_transfer.transfer_direction` requires explicit source and
target plane hints, rejects nonfinite/zero/near-collinear data, then reuses the
existing frame constructor with a normalized perpendicular hint. Its implicit
axis-selection branches cannot be reached after this validation. It transfers
the posed unit direction through target_frame @ source_frame.T.

Seven CPU tests pass: neutral correspondence, normalized output, common and
independent coordinate changes, exact legacy counterexample, and invalid-hint
rejection. This is a tested mathematical building block, not a tested full
retargeter. No generic anatomical-hint inference has been implemented here.

## Constraints On Integration

- Plane correspondences must come from explicit anatomy or observable branch
  geometry. Do not silently substitute world axes for underdetermined planes.
- Coordinate covariance is not the same as preserving a physical rigid turn.
  Both require independent tests on the assembled hierarchy and weighted mesh.
- Do not conjugate each joint's world rotation by a different static alignment:
  a shared rigid rotation would become different rotations at different joints
  and introduce false articulation. That proposed construction was rejected
  before implementation.
- Neutral identity, fixed lengths, held source trajectories, unchanged mesh,
  and the existing all-frame visual/surface controls remain required.
- Terminal axial twist is not recovered merely by naming a plane. Positions
  alone leave terminal twist unobserved; do not label a prior as captured data.

## Articulation Audit Caution

`audit_g00_wing_articulation.py` is a separate CPU diagnostic comparing each
variant against its own rest geometry after an independent body-hub rigid fit.
It does not compare against one shared rest shape or establish image quality.
Early exploratory measurements mixed rest references or used Thunderbird's old
v1 preparation; those measurements must not support a motion-loss claim.
Explicit registration/preparation provenance and rank checks are required.
Source and reconstructed segment/plane differences are descriptive evidence,
not proof that anatomical-plane transport will improve the final mesh.

The finalized CPU audit was executed against Thunderbird mapped_skin_v2 with
registration_v2 and Shahrokh mapped_skin_v1 with registration_v1. Output:
`artifacts/homm3_mocap_v2/skin_mesh_pilot/articulation_audit_v3/report.json`.
Three audit tests cover rigid-body removal, rank-one refusal, and zero-vector
refusal. Together with the explicit-plane and prior clipping tests, 23 focused
tests passed. This evidence remains generated/CPU diagnostic only.
