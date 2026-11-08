# Linked-Master Mocap Pipeline (Unit-Generic)

Owner: `experiments/homm3_mocap_v2/run_linked_master_pipeline.py`.
Contract test: `experiments/homm3_mocap_v2/test_linked_master_sequence.py`.

Proof tier: **generated-artifact only**. Nothing here is imported into Unity,
built into a bundle, installed, or game-visible unless a separate record says so.

## What it does

This is the unit-generic **capture acquisition** lane. It is not the accepted
Stronghold delivery lane by itself. When a unit already has a frozen captured
corpus, use `run_skin_mesh_pilot.py` and preserve that capture; do not replace
it with a linked-master rerun merely because the latter is newer.

One command turns a unit's sprite corpus plus an unrigged Meshy T2 surface into
a shared-skin set of per-clip GLBs, with continuous bone motion from a single
mocap pass:

1. **Reel** (`linked_master_sequence.build_master_sequence`). Every manifest clip
   whose DEF group has a native Unity clip contract (`CONTRACT_SUFFIX_BY_GROUP`
   in `tools/homm3_silhouette_pose_fit/gpu_cascade_delivery.py`) appears once as
   a full cycle: idle, move start, move, move end, then each remaining action in
   group order, death last. A one-frame idle "bookend" sits before each action so
   the mocap model returns to rest between clips. Turns, vertical attacks, and
   unused groups are listed under `skippedClips` and never captured.
   `master_sequence.json` records, per frame, the clip key, DEF group, local
   index, segment role, and source sprite hash.
2. **Capture** (`capture_master_sequence`). One vendor mocap run over the whole
   reel. Capacity is `effective_capture_capacity(package)` = donor pose-dummy
   frames minus one (the vendor truncates the last frame). A reel that does not
   fit fails; capture is never chunked or stitched.
3. **Static registration, then bind** (`prepare_move_bind_capture_bind`).
   The accepted-artifact path still requires `--static-registration` pointing at
   an accepted `homm3.static-bind-registration.v1` artifact
   (`docs/homm3_static_bind_registration.md`). The full-set automatic lane uses
   `--registration-policy idle_frame0_meshy_source_identity` and `--bind-group 2`:
   it writes that artifact after capture from idle frame 0 because the Meshy
   mesh was generated from that plate. Idle-0 bind is a floor column: undo the
   Mixamo capture's snapped 45° facing onto camera +Z, pin every
   ground-contact joint to the mesh floor, height-scale to the mesh top, yaw
   until the floor footprint fits, then XZ-only suction up the column.
   `linked_master_ground` is an opt-in experiment: floor drop plus uniform
   height scale only, no per-bone move. `linked_master_scale` is one uniform
   scale is the previous yaw-fix bind plus the lab origin-scale slider until
   the feet reach the floor. Neither is the live idle-0 default.
   Mocap still supplies the relative swings after
   that standing pose. After the gate, the surface is aligned to that
   rest skeleton. Axes come from the unit profile's `captureBind` block. A
   profile without `captureBind` stops the run.
4. **Skin fit** (`run_move_bind_t2_mocap_skin_fit.run`). Bones stay fixed;
   only skin weights change, against every reel frame at once
   (`objectivePolicy: all_frames_after_bind`, gate
   `skin_weight_contract.all_frame_objective_gate`).
5. **Export**. `clips/<Prefix>_<Suffix>.glb` per native clip, sliced from the
   master motion (`clips_manifest.json` carries global frame ranges and export
   parity). Prefix comes from `gpu_cascade_delivery.contract_prefix_for_unit`.
   A sprite|mesh GIF and contact sheet cover the entire reel.

## Running a new unit

```
python experiments/homm3_mocap_v2/run_linked_master_pipeline.py \
  --unit h3_<sid> --manifest <corpus>/manifest.json \
  --source-mesh <t2_from_bind_sprite>.glb \
  --static-registration <accepted_static_bind_registration.json> \
  --output artifacts/homm3_mocap_v2/<sid>_linked_master_v1
```

Required per-unit data (all declared, none hand-authored keypoints):

- a frozen primary donor package in `capture_candidates.json`;
- a profile from `asset_profiles.get_profile(sid)` with `regionJoints` covering
  every capture joint and a `captureBind` block;
- a T2 surface generated from the same sprite as the bind frame. The pipeline
  records the mesh hash but cannot verify which sprite produced it.

`--bind-group` selects which cycle is rest (default `0` = first move frame).
`--bind-group 2` binds to idle frame 0. That is a comparison, not the default.

## Roc reference run

`artifacts/homm3_mocap_v2/roc_linked_master_v2` (gitignored): 66 frames,
9 exported clips, skin disposition `candidate_for_visual_review`, camera IoU 0.67,
all-frame mean IoU +0.11. Wall time about 49 s on the lab GPU: capture 24 s
(17 s sprite encoding, 5 s inference), bind 1 s, skin fit 13 s, clip export 9 s,
GIF 2 s. Budget roughly one minute per unit of this size plus Meshy generation.

## Known idle-wing limitation

Idle/standing frames can keep the wings mostly spread: the Eagle donor plus
side-profile plate hide the far wing, and `reconstruct_ab` fills unconstrained
axial twist with a minimum-change prior, not captured evidence. That is not a
skinning or reel-linking fault. A separate, explicitly selected pose-refine
pilot (`docs/homm3_linked_master_pose_refine.md`) may correct wing-joint
rotations on saved capture; it does not silently replace this pipeline's
motion. The balanced Roc v2 pilot did not produce an eligible folded idle;
mesh feasibility remains unresolved.

An idle-bind T2 comparison (`roc_idle_bind_t2_v1` mesh,
`roc_linked_master_idle_bind_v1` reel, `--bind-group 2`) used the same
deterministic capture as v2. That earlier bind used flight-mesh axes and bbox
containment; it is not a static-bind acceptance. The dedicated static
registration run (`artifacts/homm3_mocap_v2/roc_idle_static_bind_v1`) is
`incompatible_bind_pose`: the standing mesh registers to the idle sprite, but
the saved flyer skeleton cannot be placed with one global similarity
(`docs/homm3_static_bind_registration.md`). It does not replace the move-bind
default and writes no consumable bind GLB.
