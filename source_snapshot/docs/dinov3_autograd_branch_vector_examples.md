# DINOv3 Autograd Branch-Vector Examples

## Status

The DINOv3-first phase is an isolated experiment, not a delivery lane. Human
review rejected the v5 result because its improved semantic objective concealed
severely wrong poses and widespread exact bind holds. The follow-up v6 run and
standalone validator passed on 2026-08-20, establishing current-source
generated-artifact validation of a **negative experiment**, not a usable fit.
The example meshes are explicitly classified as foreign smart-rig diagnostics;
none has a matching owned-bind or Meshy rigidization report. The outputs do not
prove an owned production bind, Blender-lit clip, Olden Era import, deployed
payload, runtime behavior, or user-visible gameplay.

## Implemented Contract

- The frozen `facebook/dinov3-vits16-pretrain-lvd1689m` encoder receives
  continuous CUDA float RGB. The autograd path has no detach, uint8 conversion,
  PIL conversion, or CPU transfer.
- Candidate gradients pass through resize, normalization, DINOv3 patch-token
  extraction, local-window dense scoring, the differentiable raster, skinning,
  and joint angles.
- Each optimizer visit owns one disjoint non-forking joint branch across every
  frame. Its F x 3X direction is divided by one full-block RMS value, retaining
  relative gradient strength between frames.
- DINOv3 backward runs in two-frame slices and releases each vision graph
  immediately. Temporal penalties backpropagate once against the complete
  trajectory.
- A trust-region proposal is accepted or rejected once for the whole clip using
  mean DINOv3 quality minus the clip temporal penalty. Rejected proposals do not
  splice frame winners into the pose.
- Each visit tests the complete descending line search from its current radius
  through half steps to the declared `1.25` degree floor. A rejected branch has
  therefore failed every configured local step, rather than only a coarse
  half/full-radius probe.
- Exact candidate comparison uses the established detached inference scorer.
  The differentiable extractor is used only to produce branch gradients.
- Validation reports exactly frozen joints and the fraction whose maximum
  serialized rotation exceeds one degree. This motion evidence is separate
  from objective improvement and does not certify visual pose fidelity.
- Geometry terms, root search, legacy articulated/base/mid/fine searches, IK,
  simulated annealing, the old gradient ladder, smoothing, and rescue stages are
  explicitly disabled. An incompatible configuration is a hard validation
  error, not a fallback.

## Reproduce And Validate

Run the three fits from the repository root:

```powershell
py -3 tools/homm3_silhouette_pose_fit/run_dinov3_branch_vector_examples.py
```

Revalidate the recorded inputs, model checkpoint, source hashes, pose history,
GIF timing, and summary without refitting:

```powershell
py -3 tools/homm3_silhouette_pose_fit/validate_dinov3_branch_vector_examples.py
```

The runner refuses `--skip-existing` reuse when its manifest no longer matches
the selected mesh, source PNGs, camera fit, notebook, model checkpoint, solver
sources, presentation source, or complete fit configuration.

## Generated Results

The synchronized GIFs place the authentic HoMM3 sprite on the left and the
solver RGB raster on the right at 180 ms per source frame.

| Clip | Initial objective | Final objective | Final DINO score | Accepted groups | Joints >1 degree | Exactly frozen |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Angel move | 0.788648 | 0.796398 | 0.799448 | 4/8 | 15/30 | 13/30 |
| Hobgoblin attack | 0.789744 | 0.831735 | 0.833488 | 5/13 | 19/46 | 27/46 |
| Crusader death | 0.789649 | 0.810349 | 0.812675 | 9/13 | 29/48 | 18/48 |

- [Angel move GIF](../artifacts/pose_picker_runs/dinov3_autograd_examples_v6/angel_move/angel_move_dinov3_autograd.gif)
- [Hobgoblin attack GIF](../artifacts/pose_picker_runs/dinov3_autograd_examples_v6/hobgoblin_attack/hobgoblin_attack_dinov3_autograd.gif)
- [Crusader death GIF](../artifacts/pose_picker_runs/dinov3_autograd_examples_v6/crusader_death/crusader_death_dinov3_autograd.gif)

Visual QA is decisively negative. The Angel remains nearly horizontal and only
half its search joints exceed one degree. The Hobgoblin is reclined and is even
more concentrated after the longer search: 27 of 46 joints remain exactly at
bind. The Crusader has broader movement but still leaves 18 of 48 joints at bind
and does not reproduce the target death silhouette or final framing.

The v5 structural validator did not measure articulation coverage, so its
success was overstated. It had exactly frozen counts of 17/30, 19/46, and 33/48
for Angel, Hobgoblin, and Crusader respectively. V6 fixes the coarse trust
search and records motion coverage, but the result remains a failed pose
experiment. Higher DINO similarity is not evidence that the intended joints or
silhouette moved. DINOv3 semantics are too invariant to pose to act as the sole
authority here; they reward character identity and broad action cues while
tolerating severe orientation, geometry, and joint-coverage errors.

Do not spend more sweeps trying to turn this DINO-only lane into a production
solver. The next pose experiment should use authored sprite joints and explicit
geometry as the primary objective, with DINO at most a secondary semantic
regularizer after owned bind, camera, and root initialization are correct.

Machine-readable results are under
`artifacts/pose_picker_runs/dinov3_autograd_examples_v6/example_summary.json`.
The v3 run stopped after Angel when the fail-closed validator found that the
same `depth_target_dir` was serialized with opposite slash conventions in the
preflight and result snapshots. That slot is retained as failed validation,
not published evidence.
The v4 run also stopped after Angel: its validator incorrectly classified the
explicit terminal history row as a branch decision. The retained v4 slot is
likewise failed validation, not published evidence.
The earlier `dinov3_branch_vector_examples` directory is explicitly marked
`NOT_FINAL_DIAGNOSTIC.json`; it inherited a deferred root-yaw stage and is not
evidence for this isolated phase.
