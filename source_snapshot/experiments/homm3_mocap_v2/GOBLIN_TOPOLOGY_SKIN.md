# Goblin Topology Skin Trial

Generated-candidate evidence, 2026-09-06. No preparation promotion or delivery.

## Cause and intervention

The mapped skin's hard region restriction produces discontinuities at torso/arm
boundaries. Triangle 3833 is a concrete example: vertices 4979 and 4837 have
approximately 87% RightShoulder and 13% RightArm ownership, while adjacent
vertex 5015 has only Spine/Spine1/Spine2 ownership. This creates substantial
stretch under the retained capture. A CPU audit found the worst edge failures
predominantly at mixed-region torso/arm boundaries, not in the rigid weapon.

The existing exact-weld screened harmonic solver was reused, not replaced.
It changes weights only, uses original weights as a prior, and keeps the rigid
weapon pinned. Both trials preserved mesh/UV/texture/skeleton/bind fields and
coincident-vertex ownership. The original preparation and source corpus remain
unchanged. These weights intentionally do not satisfy the old hard per-region
support policy and are not silently installed as that policy's output.

## Results

Inputs: Goblin `mapped_skin_v2`, `captures_v1`, `registration_v1`.
Outputs under `artifacts/homm3_mocap_v2/skin_mesh_pilot/goblin/`:

- `topology_skin_v1`: prior strength .05; solve/validation/write .45 seconds.
- `topology_skin_v2`: prior strength .015; solve/validation/write .41 seconds.
- `topology_comparison_v1` and `topology_comparison_v2`: identical-motion
  move, idle, and front attack comparisons.
- `topology_all_def_v2`: all 15 source groups compared with the stronger skin.
- `topology_attachment_v1`: lighter skin plus the separately authored front
  attack hand-direction correction; 5.42 seconds including preview/export.

Front attack, original -> lighter -> stronger:

- Maximum principal stretch: 23.94 -> 6.96 -> 5.28.
- Mean fraction of triangles exceeding 1.5x stretch: 4.45% -> 1.35% -> .71%.
- Right-arm median temporal range retention: 99.7% and 101.1% respectively.
- Rigid weapon motion is unchanged by either weight-only trial.

Walking right-arm median range retention is lower: 77.9% and 75.3%. This is
explicitly a tradeoff, not a motion-preservation pass. Range measures temporal
excursion, not displacement from rest; a statically displaced vertex does not
count as moving.

The stronger skin reduced the maximum stretch in every one of the 15 groups.
It did not make the mesh quality acceptable: death remains at 20.30x maximum
stretch (from 67.18x), and front attack remains above 5x. Idle's maximum stretch
falls from 4.33x to 1.46x, but absolute source appearance remains a separate gate.
No claim of visual acceptance follows from these metrics.

The combined lighter-skin/hand-direction export passed serialized animation
parity with max vertex error 2.91e-7. The comparison visibly retains the forward
weapon correction but still lacks the source's full arm reach. It is not a
transition-ready or complete-unit result.

## Reusable diagnostic changes

The existing weight comparator now accepts explicit position-capture
registration, using the same asset-wide calibration and full-canvas camera as
the fitter. The fixed-composed-FK path retains its strict existing loader.
Surface measurements reuse `SurfaceConstraints`; source hashes and selected
clip inventory are checked. `--all-clips` includes native startup/stop groups.

`restAnchors` is optional only when absent from both compared skins; offsets,
inverse bind, and all core geometry/skeleton fields remain required and exact.
The attachment trial accepts a separate, explicitly hash-pinned candidate skin
and validates it before rendering/export. No central freeze is rewritten.

Next: replace hard anatomical weight barriers with a deliberate continuous
ownership contract before optimizing on top of this initialization. Preserve
motion floors and rigid attachments; inspect the residual deformation hot
spots and source-supported body motion rather than merely increasing smoothing.
