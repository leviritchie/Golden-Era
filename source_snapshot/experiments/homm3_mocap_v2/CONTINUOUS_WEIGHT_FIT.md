# Continuous Weight Fit

2026-09-06 generated-candidate result. No promotion or deployment.

The existing silhouette/chroma plus surface objective now has an explicit
continuous-weight diagnostic path through `ownership_motion_comparison.py
--fit-seconds`. It starts from a separately generated topology skin; original
geometry, skeleton, capture, camera, and preparation are unchanged.

`TopologyWeightField` shares one weight vector across exact-position welds,
including UV and anatomical-label boundaries. Support is fixed to the supplied
initial skin's at-most-eight influences. Rigid attachment rows remain exact.
The regularizer penalizes changes from that prior and their differences across
all welded topology edges; it does not reintroduce hard region barriers.

The shared optimizer accepts an optional region-centroid motion floor. It
measures temporal range within each clip separately, ignoring tiny baseline
ranges explicitly. A static pose offset or a jump between distinct clips is
not movement. This is a soft penalty, not a proof that all vertices retain
their motion or that baseline motion is correct. Ordinary fits without this
option retain the original objective.

## Goblin evidence

Current trial: `artifacts/homm3_mocap_v2/skin_mesh_pilot/goblin/continuous_fit_v1`.
Input: `topology_skin_v2` (.015 prior), original `mapped_skin_v2`, and the
existing calibrated `captures_v1` all-DEF corpus.

- 15 groups, 88 original source frames, 200 optimization steps.
- 34.15 seconds fitting/validation/write; 46.23 seconds including comparison
  previews and input loading. Prior capture, preparation, authoring, process
  startup, investigation, and review excluded.
- Surface objective: 1.36387 -> .64443.
- Image objective: .442209 -> .435389. This is an all-frame training fit,
  not held-out/generalization evidence.
- Maximum stretch, topology initialization -> fitted: move 4.57 -> 1.49;
  idle 1.46 -> 1.15; front attack 5.28 -> 1.96; death 20.30 -> 3.30.
- Every one of the 15 groups has lower maximum stretch than initialization.
- One of 81 observable centroid trajectories remains below the 90% floor:
  move neck/head retains 88.06%. This is reported, not silently accepted.
- Individual-vertex motion is a different metric: walking right-arm median
  temporal range retains only 71.97% of the original restricted skin. The
  centroid penalty does not solve that tradeoff. Attack right-arm median
  range retains 100.63%.
- No rest geometry was changed. Candidate weight invariants passed.

`continuous_attachment_v1` applies the prior source-authored front-attack hand
direction correction with the fitted skin. The 5.53-second preview/export run
passed serialized parity (max vertex error 3.84e-7). The comparison shows the
forward weapon direction, but arm reach and body pose still miss the source.
Surface quality, source agreement, transitions, and unit acceptance remain
incomplete. The original corpus and central preparation freeze were not changed.

## Verification and next work

CPU tests cover exact weld initialization with interleaved duplicates, real
gradient updates, rigid preservation, finite motion-loss gradients, distinct
region/time axes with unequal clip lengths, and no false motion across clips.
Luna implementation/review was independently checked; indexing defects found
during review were fixed before the recorded GPU run.

This establishes a reusable continuous-weight optimization candidate, not a
new accepted delivery contract. The user has redirected the next phase toward
new units rather than further Goblin refinement. Keep the current results as
comparison baselines; defer shoulder/arm and retarget experiments while the
unchanged pipeline is exercised on Orc, Ogre, and then Cyclops. Record residual
errors rather than hiding them with smoothing or relaxed acceptance thresholds.
