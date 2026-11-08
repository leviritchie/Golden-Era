# Attachment Motion Authority

Generated-candidate experiment, 2026-09-06. Not a delivery contract or a
satisfactory-unit claim. The all-Stronghold animation objective remains open.

## Diagnosed limitation

`corpus_motion.load_motion` reconstructs the ordinary capture-position lane
through `reconstruct_adapted`. `direction_retarget.reconstruct_frame_locals`
starts joints at rest and changes a joint only when an observable child
direction is available. A terminal hand therefore has no independent local
rotation. Goblin's calibrated front attack has exactly zero local hand
deviation from identity across all eight source frames. A rigidly hand-owned
club inherits the arm orientation without an independent weapon direction.
This is a representation limitation, not proof of a failed skin optimizer or
necessarily a bad raw learned rotation. Other motion errors remain separate.

## Bounded correction

`screen_attachment_direction.correct` changes only a declared non-root leaf's
rotation. Its source signal is the per-frame grip-to-weapon-head direction,
authored on the original source images. Changes are relative to the unchanged
first pose. It rotates around the camera-plane normal, preserving the existing
axis depth component and length. This does not infer absolute 3D twist or fix
wrist travel, body turns, arm reach, or hidden anatomy.

`run_attachment_direction_trial.py` uses the same asset-wide idle calibration
and fixed research skin as the main fitting pipeline, not raw donor FK. It
pins source frames, corpus, mesh, skin, camera, and calibration. Existing input
artifacts are not rewritten. The new animation is a separate diagnostic GLB;
the main corpus and accepted-delivery inputs are unchanged.

## Goblin front attack evidence

Current output: `artifacts/homm3_mocap_v2/skin_mesh_pilot/goblin/attachment_direction_v3/`.
The earlier v1 stopped at a preview filename error; v2 completed before the
additional camera pin and surface metrics. v3 is the current reproducible run.

- Eight original attack frames, with source startup and return poses retained.
- First local/world pose unchanged exactly; all other joint local/world
  matrices and every wrist/joint translation unchanged exactly.
- Mean direction error relative to the calibrated source-angle changes:
  24.5931 degrees before, below 1e-10 degrees after.
- Maximum correction: 55.9698 degrees. Axis depth/length errors below 2e-16.
- Serialized GLB parity passed; maximum vertex error 2.30e-7 world units.
- 5.18 seconds for load, correction, preview, and export; excludes source
  authoring, process startup, prior preparation/capture, investigation/review.
- Agent visual inspection: forward weapon direction improved, but arm reach
  remains short. Surface strain remains high and some wrist-region strain
  increases; this is not an animated-surface or full-animation quality pass.

Attack-to-idle integration and unobserved context-frame wrist corrections have
not been validated. Do not promote this isolated clip as a transition-ready
animation. The source overlays are `authored_source.gif`; the comparison uses
the same fixed mesh and skin before and after correction.

## Next work

Retain mocap where it provides useful joint motion, while explicitly supplying
orientation evidence absent from a position-only terminal joint. Test source
shoulder/elbow/wrist motion separately before asking skin fitting to repair
reach errors. Reuse this numeric operation through per-unit attachment data,
not unit-name branches. Full-unit surface, clip inventory, transitions, visual
acceptance, and eventual delivery proof are still required.

CPU regression coverage includes real nonzero correction under a tilted camera
and moving parent, invariant checks, malformed inputs, and preflight provenance
negatives. Separately, the existing screen-landmark IK's per-joint bound array
was corrected to follow frame/joint/axis ordering; component-wise bounds and
actual SO(3) excursions are now reported separately.
