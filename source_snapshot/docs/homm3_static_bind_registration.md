# Static Bind Registration

Owner: `experiments/homm3_mocap_v2/static_bind_registration.py`.
Runner: `experiments/homm3_mocap_v2/run_roc_idle_static_bind.py`.
Gate: `experiments/homm3_mocap_v2/test_static_bind_registration.py`.

Proof tier: **generated-artifact only**. This stage does not write an accepted
bind GLB, fit skin weights, optimize animation, generate a mesh, or deploy.

## What it proves

Three checks stay separate. Passing one is not proof of another.

1. **Source-view registration.** The original textured mesh, before the current
   binder rotates or scales it, is scored against the exact source sprite on the
   shared DEF canvas. The search is one global rigid orientation, uniform
   projection scale, and image translation. The camera is a documented
   yaw-0 / pitch-0 Y-up view; the mesh is rotated instead. Flight-mesh
   `captureBind` axes and the old 15° / 155° cameras are not inherited.
2. **Skeleton compatibility.** The saved bind-frame skeleton and the registered
   mesh share that source-view frame. One global similarity is allowed. The idle-0 Meshy writer
   is a floor column: Mixamo facing is undone onto camera +Z (snapped 45°),
   every ground-contact joint is pinned to the mesh floor, the skeleton is
   height-scaled to the mesh top, yaw-rotated until the floor footprint fits,
   then joints are moved only in X and Z into the nearest filled slice.
   Empty height bands fail closed. A named `idle0_ground_height` experiment
   does only the floor drop and a uniform height scale and is not the live
   idle-0 default. Mocap remains the source of later-frame
   relative motion, not of the standing pose. A 3D AABB alone is not enough. The
   search-and-confirm registrar still uses one global similarity only. Branch
   distances use original mesh vertices and profile `regionJoints` bone names.
   Nearest-bone vertex labels are not anatomy evidence.
3. **Skinning algebra.** Rest linear-blend identity can be exactly zero while
   the skeleton still sits in the wrong body. That fixture is in the gate.

Image-score improvement cannot accept a bind. The search-and-confirm registrar
(`run_roc_idle_static_bind.py`) never sets `acceptance.status` to `accepted` or
`visualConfirmation` to true.

The full-set automatic mocap lane is a different writer:
`idle0_meshy_registration.py`. Meshy meshes in that inventory were generated
from idle DEF group 2 frame 0, so camera (documented yaw-0 / pitch-0) and
frozen bind are that plate. That writer records
`confirmationKind: idle_frame0_meshy_source_identity` and may mark the artifact
consumable. The standing pose is the floor-column bind. A later human GIF
review is still not animation acceptance.

## Outcomes

The artifact schema is `homm3.static-bind-registration.v1`. Status is exactly
one of:

- `accepted` — only after explicit visual confirmation of anatomical placement
  on a single credible view. `consumable` is true only in this state.
- `ambiguous_orientation` — several distinct views remain competitive. Stop and
  choose a view. Do not fabricate landmarks.
- `incompatible_bind_pose` — no single global similarity places the captured
  branches on the matching body parts. This is **capture/mesh bind-pose
  incompatibility under rigid alignment**. It does not mean the mesh is
  unusable. The idle-0 writer is the lane that may shorten rest bone lengths
  without changing mocap angles; if joints still sit outside the mesh at the
  minimum length scale, that writer fails closed instead of accepting.
- `pending_visual_confirmation` — one distinct view is numerically plausible
  and still unreviewed.

## Downstream gate

`prepare_move_bind_capture_bind`, `run_move_bind_t2_mocap_skin_fit.run`, and
`run_linked_master_pipeline` require `--static-registration` pointing at an
artifact whose `acceptance` is `accepted` with `visualConfirmation=true` and
matching mesh hash, capture hash, and bind frame. An unverified registration
cannot produce a new bind GLB or enter skin fitting.

Acceptance must also name `acceptance.selectedCandidateId`, identifying exactly
one `views.candidates` entry. Both recorded rotations must be finite proper
orthonormal matrices; skeleton scale must be positive and translation finite.
Legacy status-only approvals are not consumable and are not upgraded silently.

The selected mesh rotation maps the original mesh into the source-view frame.
The inverse selected skeleton similarity then maps it into capture
coordinates. If the selected row has `bindRestJoints`, the binder uses that
standing pose. Otherwise it applies `boneLengthScales` to the bind-frame
capture joints. Playback aims mocap relative swings from the original capture
bind directions onto that rest. Projection scale and image translation are camera parameters, not
3D mesh scale or translation. The binder must not run semantic-axis or AABB
alignment again. Bind report and region sidecar store the applied similarity,
selected candidate ID, and registration hash. Skin fitting rejects cached binds
whose recorded placement differs from the selected registration.

The normal-build `validate_homm3_attachment_pipeline_contract.py` checks this
producer/consumer wiring without loading CUDA. Focused numerical and export
tests live in `test_static_registration_consumption.py`. This contract does not
establish anatomical quality or automatically accept any existing Roc artifact.

Validated at source/generated-fixture level: 29 focused tests pass, including
nontrivial selected-transform composition, a synthetic non-Roc bind with real
GLB vertex readback, and stale-cache rejection. The build-wired source validator
passes. No existing unit registration has been promoted or animation deployed.

Existing on-disk linked-master artifacts are left in place. They are not
re-labeled as accepted by this gate.

## Roc idle T2 comparison

Inputs: idle T2 `artifacts/homm3_mocap_v2/roc_idle_bind_t2_v1/meshes/h3_roc_idle_bind_t2.glb`
(hash `8dc4ad44…`), corpus idle sprite `g02_idle/000.png`, saved capture
`roc_linked_master_idle_bind_v1/capture/capture/raw_capture.npz` (hash
`2838b444…`, bind frame 0).

Output: `artifacts/homm3_mocap_v2/roc_idle_static_bind_v1`. Recorded status
`incompatible_bind_pose`. One distinct source-view mode (best IoU 0.822 at mesh
yaw 55° / pitch 10° / roll 0°) is well ahead of the next kept view (IoU 0.741).
The mesh registers to the standing idle sprite. The saved bind-frame skeleton
does not: after one global similarity fitted on torso and neck, wing span is
about 1.92× mesh width and mean wing surface distance is 0.76 versus body 0.05.
No accepted bind GLB was written. Elapsed 31.0 s. Generated-artifact only.
