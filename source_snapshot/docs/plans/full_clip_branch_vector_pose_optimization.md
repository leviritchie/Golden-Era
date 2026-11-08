# Full-Clip Branch-Vector Pose Optimization Experiment

## Summary

Implement a new opt-in `branch_vector` joint solver in the GPU cascade. For a branch containing `X` joints, each frame's configuration is a bounded `3X`-component local rotation vector; across `F` frames, the solver optimizes an `F x X x 3` clip state. Forward kinematics, skinning, projection, and rasterization remain the deterministic pose-to-image mapping. The rendered clip objective selects a solution; no endpoint or centroid is treated as uniquely determining the inverse pose.

Use the currently selected 28-frame Crusader `idle_start_move_end` sequence and cover every solver-eligible deforming joint. Produce four independent matched runs from one frozen initialization:

| Objective | Existing discrete solver | New branch-vector solver |
|---|---:|---:|
| Geometry | Control | Treatment |
| DINOv3 dense | Control | Treatment |

All outputs remain generated experiment candidates. Do not change the delivery gate or claim build, deployment, runtime, or gameplay proof.

## Solver Architecture

- Freeze the initialized camera, root transform, frame set, bind pose, input hashes, score weights, and random seed into one shared initialization manifest. All four runs must read that same state.
- Partition active bones into disjoint maximal non-forking hierarchy segments. The trunk ends at a fork; each child begins a new segment. Validate that segments are connected, pairwise disjoint, and cover every eligible search bone exactly once.
- Keep motion-root registration separate and frozen during all joint comparisons. Zero-influence or non-deforming nodes are excluded explicitly with recorded reasons rather than silently omitted.
- Visit branches deterministically in root-to-leaf order. Recompute the clip gradient after every accepted branch so later branches see the updated geometry.
- Define the minimized clip loss as `1 - mean(active image score) + existing bone-pose, velocity, and acceleration penalties`. Geometry runs use the configured silhouette/depth/chroma score and collision policy; DINOv3 runs use dense semantic similarity without geometry terms. Both use the same temporal weights.
- Mask the gradient to the current branch, retain all three local rotation components, and normalize the resulting full-clip direction by its RMS magnitude. Apply movement in bounded angle space, project to the existing joint limits, and invert back to the raw parameter representation.
- Use a per-branch trust radius starting at `20` degrees RMS, bounded to `1.25..40` degrees. Every visit tests the current radius and every descending half step through the floor. After acceptance, grow from the selected step by `1.5x`; after rejection, retain only the floor for a later surface-changing revisit. Commit only a finite candidate that improves complete clip loss by more than `1e-6`.
- The DINOv3-first runner uses four complete branch sweeps and stops early after a sweep accepts no branch. A finite gradient below `1e-6` is an explicitly logged plateau; missing or non-finite gradients are hard failures.
- Save the current pose, trust radii, completed branch index, objective history, and input/config hashes after each accepted branch. Resume is explicit and must reject mismatched inputs or configuration.

## DINOv3 Gradient Path

- Add a differentiable GPU-float preprocessing path alongside the existing inference-only path in `dense_semantic_features.py`. It must apply the selected processor's resize, crop, rescale, mean, and standard deviation without `detach`, integer conversion, PIL, or CPU transfer.
- Freeze DINOv3 model parameters but execute candidate forwards with autograd enabled. Keep target feature grids cached and detached.
- Accumulate image gradients in two-frame microbatches on the available 16 GB RTX 5070 Ti, then backpropagate temporal penalties once per branch. Do not retain one activation graph for all 28 frames.
- Keep the existing uint8/inference implementation unchanged for the DINOv3 discrete control and exact reporting.
- Fail closed when the processor contract is unsupported, CUDA is unavailable, the candidate graph becomes detached, or a gradient is non-finite. Never substitute geometry gradients for a failed DINOv3 run.
- Allow DINOv3 autograd only for `joint_solver_mode="branch_vector"` with root optimization disabled. Preserve the existing prohibition against silently mixing DINOv3, geometry, collision, IK, and legacy gradient-ladder scoring.

## Interfaces And Artifacts

- Add `joint_solver_mode: Literal["discrete", "branch_vector"]`, defaulting to `discrete`, in `roc_gpu_cascade_experiment.py`.
- Add validated branch-vector controls for maximum sweeps, trust-radius bounds, growth/backtracking factors, minimum improvement, minimum gradient norm, and DINO gradient microbatch size. Continue using the existing `score_mode` to select `geometry` or `dinov3_dense`.
- Reject configurations that combine `branch_vector` with discrete base/mid/fine/articulated search, branch rescue, the old all-bone gradient ladder, simulated annealing, IK, temporal consensus, or physics smoothing. The adapter must not silently disable incompatible stages.
- Add notebook controls and a reproducible four-run command in `roc_chromatic_single_bone_match.ipynb` without overwriting the current uncommitted experiment settings.
- Write each run to an isolated manifest-owned directory containing the complete pose JSON, branch topology, objective history, evaluation/model-forward counts, wall time, peak GPU memory, exact replay scores, and lit preview.
- Generate a four-way synchronized GIF/contact sheet and a comparison report that cross-scores every result under geometry and DINOv3, then reports temporal motion, collision, joint-limit saturation, and evaluation efficiency.
- Keep `CURRENT_CASCADE_KEEP` rejecting these outputs. Label documentation and manifests `generated experiment candidate; not delivery validated`.

## Validation

- Unit-test branch partitioning on forked synthetic hierarchies for exact coverage, connectivity, deterministic ordering, and zero overlap.
- Unit-test trust-radius growth/backtracking, strict commit/rollback behavior, joint-limit projection, plateau reporting, checkpoint hash rejection, and non-finite failure paths.
- Verify geometry angle gradients against centered finite differences on a tiny differentiable mesh.
- Verify differentiable DINO preprocessing against the existing quantized-equivalent inference score within `1e-3`; separately prove a finite, nonzero RGB-to-feature and angle-to-score gradient.
- Add a lightweight fake-DINO clip test that proves frame-microbatch gradient accumulation equals an unchunked reference and includes temporal terms.
- Wire a fast branch-vector contract validator into the pose experiment's mandatory preflight. Keep gated model loading and the 28-frame GPU run out of ordinary builds, but require them before recording experiment results.
- Execute all four full runs, replay their saved poses, and verify every frame and branch is present. Every committed step must strictly improve its own complete clip objective; rejected steps must leave the serialized pose byte-equivalent.
- Report exactly frozen search joints and joints whose maximum serialized rotation exceeds one degree. Objective improvement and source integrity can validate a negative experiment; neither may be described as articulation or pose success.
- Judge the hypothesis by the matched quality-versus-cost curves, not by whether the implementation completed: branch-vector search is favorable only if it reaches an equal-or-better matched objective with fewer evaluations or less wall time. A completed but inferior result is retained and reported as a negative experiment.
- After validation, have a review agent audit instruction drift, silent fallbacks, mathematical claims, branch ownership, and delivery-proof boundaries, then commit the scoped milestone.

## Assumptions

- “All branches” means all current solver-eligible deforming joints, with `skip_tiny_bones=False` and no motion-root inclusion.
- Every joint uses the existing three-component bounded local rotation vector; no new anatomical hinge-axis contract is introduced.
- The four runs use identical input frames, mesh, camera/root initialization, joint limits, temporal weights, and seed. Only the objective and joint solver differ.
- Existing uncommitted workspace changes are preserved and integrated rather than reverted.

## DINOv3-First Finding

The three-clip v6 DINOv3-only treatment is a negative result. Bounded
backtracking eliminated the coarse-step explanation, but movement remained
sparse or partial while semantic scores rose. DINOv3 is therefore rejected as
the sole pose authority for the next phase. The remaining matched controls are
still unexecuted; do not imply that this DINO-first run completed the original
four-arm experiment.
