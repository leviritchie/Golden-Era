# Corrective Representation Audit

Scope: diagnose the failed fixed-mocap corrective trial without modifying any
motion, mesh, skin weights, objective weights, or acceptance gate. All 21
Stronghold units remain the delivery objective. This three-unit diagnostic is
not a replacement for that scope and no candidate is promoted.

## Retained Evidence

`audit_corrective_gradient.py` replays the fitted bases and saved corrective
fields for Thunderbird, Shahrokh, and Ogre. Final reports are
`artifacts/homm3_mocap_v2/corrective_gradient_v2/<asset>.json`.
Use v2, which includes the feature-energy measurements in the final implementation.

The audit verifies original corrective input/code hashes, independently
reconstructs the motion, checks the saved train/held split and static field
buffers, and matches both the baseline and candidate mesh arrays within 1e-6.
It computes gradients with respect to actual spatial control parameters, not
unconstrained mesh vertices. Disconnected terms fail rather than receiving a
synthetic zero gradient. Undefined zero-vector cosines are null.

## Four-Feature Compression

For flattened rotation deviations X and saved orthonormal basis B, retained
energy is ||XB||^2 / ||X||^2. The basis was fitted only on training poses.
Upward attack is the whole held-out clip, not an unseen-motion guarantee:
all poses also participate in geometric constraints, and the earlier static
base was fitted using all source images.

| Unit | All poses retained | Training poses retained | Upward attack retained |
| --- | ---: | ---: | ---: |
| Thunderbird | 60.41% | 65.85% | 33.69% |
| Shahrokh | 60.49% | 68.63% | 32.73% |
| Ogre | 71.77% | 79.52% | 34.39% |

The largest per-joint residuals include wing joints for Thunderbird/Shahrokh
and arm/forearm joints for Ogre. This establishes a substantial representation
restriction. It does not prove every discarded component is useful motion or
that retaining it will improve silhouettes. Increasing mode count also changes
the coefficient normalization and regularizer in the current implementation;
do not treat an arbitrary wider basis as an otherwise identical experiment.

## Objective Conflict

At zero corrective controls, the weighted geometry/image gradient-norm ratios
are 21.38, 15.17, and 16.75 respectively. Image-versus-geometry cosine is -0.4725
for Thunderbird, +0.0895 for Shahrokh, and -0.0604 for Ogre.

Thunderbird's image/total-gradient dot product is -0.02157: infinitesimal
Euclidean descent on the current combined objective initially increases image
loss. The saved field also has higher weighted training-image loss than zero
controls (5.18271 versus 5.15272). The other two saved fields improve training
image loss. The conflict is therefore real but not universal.

These are local derivatives in the existing control parameterization, not
physical deformation magnitudes or a replay of Adam updates. Adam moments,
clipping, finite steps, and nonlinear bounds matter. GPU raster gradients can
vary slightly between executions; report the retained run rather than claiming
bit-exact gradient reproducibility. No convergence conclusion follows.

## Verification And Next Decision

Four CPU tests passed for independent gradient arithmetic, zero/disconnected
cases, and known feature-projection energy. Three CUDA replays completed with
saved baseline/candidate parity. Luna reviewed the final math and interpretation.

Before another corrective fit, address the lossy pose representation and test
image improvement without trading away surface quality. Do not weaken quality
thresholds or increase arbitrary displacement bounds to force acceptance.
Missing source actions remain a separate issue: source-grounded edits to joint
motion would change the user's fixed-mocap constraint and must be explicit,
not hidden inside a claimed skin-only improvement.

## Nested Residual Trial

Implemented `ResidualPoseCorrectiveField` as an explicit diagnostic expansion.
The original four coefficients and spatial fields remain unchanged. Additional
training PCA modes reach 95% training-feature energy and receive only the unused
per-frame coefficient budget, `1 - sum(abs(original coefficients))`. Total
absolute coefficient sum remains at most one and the same 10% displacement
bound applies. No bone transforms or static skin weights change. There is no
frame ID or clip ID input.

Each run imports the saved four-mode controls, validates all legacy static
buffers, and reproduces its saved candidate mesh within 1e-6 before training.
Extra controls start at zero. Paired four-mode continuations use the same warm
candidate, 150 Adam steps, objective, training split, and checkpoint rule.
Checkpoints must improve training-image loss while aggregate surface and idle
terms remain no worse than the warm candidate. An unchanged initial checkpoint
is explicitly reported as `feasibleImprovement: false`, not an accepted result.

All three expanded runs and all three four-mode continuations completed all 15
clips. Artifacts are `pose_residual_v1/<asset>/` and
`pose_four_continue_v1/<asset>/` under `artifacts/homm3_mocap_v2/`.

| Unit | Total modes | Training image loss reduction | Aggregate surface reduction | Fit / cached total seconds |
| --- | ---: | ---: | ---: | ---: |
| Thunderbird | 18 | 0.208% | 3.037% | 25.05 / 41.22 |
| Shahrokh | 15 | 0.734% | 1.213% | 26.48 / 40.35 |
| Ogre | 12 | 1.376% | 1.987% | 19.02 / 28.63 |

All four-mode continuations retained their initial checkpoint: none found an
eligible image improvement. Their cached totals were 28.15, 27.89, and 19.68
seconds. These comparisons support a small benefit from expanded capacity
under this optimizer, not recovery of the missing source actions.

All six CPU artifact validations passed structural and provenance checks.
Every candidate still fails reported surface p95 and compression quality gates.
The checkpoint rule protects aggregate losses only: some worst-frame strain
metrics worsen despite a lower total surface term. It must not be described
as preserving surface quality overall. Validators check reported metrics, not
independent rerendered quality or game playback. Expanded Thunderbird remains
worse than the earlier static fit on held-out image metrics.

Twenty focused field, split/checkpoint, and residual-validator tests passed.
Luna reviewed final field, runner, and validator implementations. The inspected
Thunderbird movement, Shahrokh upward attack, and Ogre upward attack comparisons
show only small mesh changes and still insufficient action. No result is
promoted; further expansion of this bounded corrective representation alone
is not supported as the route to faction completion.

Historical four-mode artifacts retain their original implementation hashes;
the runner has since gained this explicit comparison mode. Their use as warm
starts is proven by static-buffer and candidate-mesh parity, not a claim that
their old runner hashes match current source.
