# Source-Reference Bind Trial

2026-09-06. Explicit diagnostic only, not a production selection or replacement
for the frozen preparation. Default `run_skin_mesh_pilot.py` behavior remains
`--bind-mode prepared`. `--bind-mode source_reference` creates a private bind
copy from one proper positive similarity of the registered capture reference.
No per-bone anatomical fitting, per-clip rest reset, or motion-angle scaling is
performed. The original rest mesh, texture, topology and camera are unchanged.

## Implementation And Tests

`source_reference_bind_candidate.py` validates the source hierarchy/reference,
rejects separated structural zeros, collapsed observable bones and collinear
hubs, and fits one proper rotation, positive scale and translation. Scale uses
the signed least-squares numerator after rotation determinant correction.
Canonical coincident skin ownership is retained. Optimizer region supports are
also remapped so it cannot reintroduce an upstream redundant owner.

The existing optimizer operates on frozen motion transforms. Its weight-only,
shared bounded mesh and all-frame refit stages remain separate. A prepared-bind
control is rendered beside the unoptimized source-reference bind and fitted
result. Neutral LBS parity is checked before optimization. Root travel, if
present, receives the same global similarity as the rest skeleton.

The first Thunderbird run (`source_reference_fit_v1`) completed optimization
but stopped at the first GLB verifier because explicit translation channels
were forbidden by the rotation-only reader. It is incomplete, not a completed
export result. The verifier now has an explicit `allow_root_motion` mode that
replays root translation and rejects non-root offsets changing from rest.
The default still rejects all translation channels. This is not bone stretching
or a permissive translation fallback. V2 reruns use that verified mode.

68 focused tests pass, including 8 source-reference tests, 9 coincident tests,
skin/mesh/camera tests, existing motion tests, and 5 serialized-GLB tests.
The serialization tests required execution outside the sandbox permission
restriction for small workspace temporary files; they then passed. The root
motion fixture combines actual joint rotations with translation, rather than
comparing against static rest rotations. Existing test warning about converting
a gradient-bearing tensor to a scalar is unchanged.

## Evidence

Artifacts: `artifacts/homm3_mocap_v2/skin_mesh_pilot/<unit>/source_reference_fit_v2/`.
Use `g00_move_bind_comparison.gif` for source, prepared control, source-reference
bind and fitted skin/mesh. The ordinary comparison GIF's `Original` column means
the unoptimized source-reference bind in this explicit mode, not the old rig.
Each report records bind mode, canonical region support, candidate skin hash,
similarity parameters, fixed motion hashes and implementation hashes.

Thunderbird: all 15 groups / 92 frames completed, 15 GLB parity checks passed
(maximum vertex replay error 8.27e-7). Scale 2.32145. Frame-weighted IoU:
prepared control .548298; source-reference initial .456914; weights .489864;
skin+mesh .492583. Rest and idle appearance passed; depth and animated surface
failed. The inspected wingbeat still lacks the source opening. Not promoted.
Cached fitting/render/export elapsed 100.13 seconds; this excludes the earlier
incomplete V1, authoring, implementation, review and CPU investigation.

Shahrokh: all 15 groups / 92 frames completed, 15 GLB parity checks passed
(maximum replay error 6.13e-7). Scale 2.15178. Frame-weighted IoU: prepared
control .534410; source-reference initial .489407; weights .488678; skin+mesh
.503986. Final color error improves (.623542 versus control .631564), but
silhouette is worse and idle, depth and animated surface fail. Rest shape passes.
Inspected move contact sheet is still unsatisfactory. Not promoted. Cached
fitting/render/export elapsed 106.43 seconds. Final two-unit total is 206.56
seconds; this is not total engineering or first-attempt time. Both completed
reports' implementation hashes were checked against current source.

## Remaining Alignment Evidence

Current Thunderbird captures contain `pred_position`, `pred_rot6d`, embeddings,
offsets, parents and names, but no source-camera matrix or projected 2D joints.
The inspected diagnostic green-skeleton rendering uses synthetic orthographic
views, not a measured source-image camera. Therefore it cannot supply a proven
source-to-mesh camera alignment by itself. No arbitrary axis conversion added.

Nor is `pred_rot6d` a validated hidden-twist replacement: existing canonical
vendor FK disagrees with `pred_position` on the current move capture by mean
.14360 and maximum .42024. The capture report explicitly identifies positions
as the motion interface and learned rotations as diagnostic-only. Do not change
motion authority to those rotations because they happen to move a wing.

The results rule out the claim that merely retaining source skeleton proportions
solves the visual problem with the current skinning setup. They do not exclude
wrong spatial skin ownership, underconstrained twist, or global alignment.
Next evidence should test one asset-wide image-scored capture-frame alignment
while preserving the fixed source motion and exact neutral mesh. Do not replace
that with unit-specific or per-frame angle corrections. All 21 units remain in
scope; inventory validation is not animation acceptance.
