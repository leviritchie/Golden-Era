# Mesh-fitted rest rigs and motion reuse

## Purpose

Fit joint locations to the actual generated surface, then reuse saved mocap in the fitted rig's
coordinate frame. This separates mesh anatomy from motion, rather than copying the original
capture's yaw, shoulder height, and limb lengths into every regenerated mesh.

The first adapter is a Y-up T-pose biped with the existing 25-joint topology. It measures the arm
axis and surface cross sections; reference proportions only guide ambiguous internal joints.
It is not a quadruped, mounted-unit, wing, or arbitrary-rest-pose fitter. Those are separate fitting
adapters, not exceptions hidden in the biped implementation. The batch orchestration and saved-motion
retargeting are reusable without Meshy requests, Blender sessions, or new motion inference.

The SmartRig A-pose branch has an additional selector contract: a UniRig export can contain a long
lateral armor or accessory chain beside the real arm. The adapter enumerates short candidate chains and
scores their link directions, length profile, and shoulder placement against the registered arm before
assigning `Left*` or `Right*`; maximum lateral separation is not semantic evidence. The guardsman
pilot caught this regression: the old selector chose `Bone_034` for the positive-side arm, while the
shape-matched chain is `Bone_021 -> Bone_020 -> Bone_019 -> Bone_018`. The selector is fail-closed when
it cannot find one distinct chain per side. This is generated-candidate evidence only, not delivery or
runtime proof.

## Running

For the operator checklist, start with [the short workflow](homm3_mesh_repair_workflow.md).
Manifest paths for mesh, runDir, sourceReport, and out are repository-relative (or absolute),
not relative to the shell's current directory. The manifest argument itself follows normal CLI paths.

```powershell
py -3 tools/homm3_meshy_frame_pose/fit_mesh_rest_pipeline.py `
  --manifest tools/homm3_meshy_frame_pose/archer_rest_fit_pilot.json --preview
```

Use `--review` for the rest overlay and five representative poses without rendering the full reel;
the Archer measured 7.31 seconds including this review versus roughly one minute for the full reel.
Omit both visual flags for the fast fit/bind/retarget stage. `--units` selects a small subset of an explicit
job manifest. Content hashes of the inputs and solver code permit unchanged jobs to reuse their
outputs. An ordinary input/fit error is reported per unit and does not prevent later jobs from
running; the batch exits nonzero after reporting its failed units. Unknown body plans are reported
as requiring a fitting adapter, not processed as bipeds.
Duplicate unit IDs and misspelled selections are rejected before running. Recomputed jobs remove
their previous preview files, so an old reel cannot masquerade as the result of a newer fast fit.

Each job emits `fitted_bind.glb`, `retargeted_motion.npz`, and `report.json`. Preview adds front/side
`rest_overlay.png`, `keyframes.png`, and `animation_reel.gif`. The motion archive contains explicit
per-bone matrices, not just joint positions. The static GLB alone does not contain these animations.

## Motion conventions

The source rest used for retargeting must correspond to the target mesh's rest pose: canonical
source T-pose to fitted target T-pose, followed by the original recorded frames. Using the captured
idle as source rest would incorrectly map idle to outstretched target arms.

The retarget solver carries hierarchical local changes between corresponding rest frames,
preserves fitted bone lengths, and retains full rotations through skinning. It does not turn the
result into points and reconstruct unrelated shortest-swing rotations. Position-only mocap cannot
recover independently authored wrist twist.

The existing position field weights outgoing segments (for example elbow to wrist belongs to
ForeArm). The retargeter's incoming-link convention is converted once with
`outgoing_skin_transforms` before skinning and motion export. Without this conversion an elbow
bend leaves forearm flesh following the upper arm. The adapter's elbow test includes an off-axis
surface point and a normal, not only joint positions.

## Archer result

The textured front/side rest overlay and sampled idle, move, attack, shoot, and death frames were
visually inspected. The arms lie along the mesh's own arm axis; the pelvis lies below the belt;
idle no longer maps to a T-pose. Original source textures and surface geometry are retained.
The original body-only `mesh-fitted-v1` left the crossbow beside the leg. The current pilot adds
the explicit `prop_attachment.v1` recipe after body fitting: a seeded surface cut extracts 824
connected prop triangles, duplicates 29 contact vertices, preserves all 8,323 original triangles
and texture coordinates, and attaches the crossbow rigidly to the left hand. Its shooting pose is
horizontal at shoulder height. This recipe is tied to the exact source mesh hash, not a universal
weapon classifier. Finger curl, two-hand grip solving, and hidden-surface reconstruction are not
part of this change.

One local run measured 0.38 seconds through fitting/input preparation, 0.56 seconds through
fitting, skinning, and exporting 70 retargeted frames, and 63.79 seconds including the full textured
reel. These are Archer measurements, not an all-roster throughput guarantee. The output directory
was `artifacts/meshy_downloads/meshy71_repair_candidates/h3_archer/mesh-fitted-v1/`.
The current attached-prop pilot writes `mesh-fitted-v2/`; its integrated quick review measured
7.16 seconds, with 0.63 seconds through export before rendering. The full 70-frame reel measured
58.46 seconds including 0.64 seconds through export; an unchanged rerun hit the cache in 0.14 seconds.
Eleven prop tests and 35 fitting/retarget/workflow tests passed, including a real-asset textured
export round-trip and rigid hand-relative prop motion across all 70 frames. These are local
candidate-generation measurements and tests, not all-roster or game-runtime validation.

The geometry-only fitter measured 29.44 ms median over ten runs and corrected the Archer's
46.20-degree yaw mismatch. Transformed-copy tests exercise yaw, uniform scale, and translation;
they are not a second-unit validation. Thirty focused fitting/retarget/batch tests passed. The
exported 70-frame motion preserves fitted bone lengths to 2.7e-15 mesh units and joint anchors to
1.4e-16. The reel uses a fixed 100 ms/frame review cadence, not a deployed clip-timing contract.

## Experimental scope

This is candidate generation and visual review, not runtime deployment. Prop separation is a
separate geometry/attachment stage; aligning the body rig does not relocate a weapon generated
beside the legs. The generic attachment implementation and the asset-specific Archer recipe are
separate files. Full-roster coverage is not established by the Archer pilot. The fleet-scale design
is shared batch/motion infrastructure plus fitting adapters by body plan, not 261 hand-edited rigs.

The older Meshy selector's synthetic-T-pose source comparison and its reported stretch wins do not
establish a successful repair. Use the mesh-fitted rest overlays and actual replay to judge this lane.
