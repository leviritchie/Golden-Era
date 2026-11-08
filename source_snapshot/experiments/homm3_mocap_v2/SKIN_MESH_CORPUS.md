# Full-DEF constrained skin and mesh experiment

Generated diagnostic only. Latest candidate is rejected by animated-surface
quality checks. Nothing is installed, deployed, or visually accepted.

Shared cross-unit integration, explicit orientation completion, attachment export
gates, and current proof boundaries are documented in `ATTACHMENT_PIPELINE.md`.
The historical Roc-only scope below is not the rollout architecture.

## Scope and ownership

The user authorized rest-mesh adaptation alongside silhouette/chroma-guided
skinning, then requested all available authentic DEF frames and preservation of
attack startup/return motion. This experiment includes all 91 source frames in
15 groups of the active Golden Era `h3_roc` CROC extraction. No RIFE frames are
used, and no groups are excluded as unshipped or unused.

One shared skin and one shared rest mesh are optimized for the complete asset.
The mesh field is a 216-control trilinear lattice, not per-frame vertex animation.
Topology, UVs, texture, skeleton, bind matrices, and captured motion remain fixed
during fitting. Maximum rest displacement is bounded by 3% of original bbox
diagonal. Beak and leg geometry are frozen; displacement tapers near those
regions and duplicate-position vertices share corrections.

Motion authority is still the existing capture-relative adapted transform
reconstruction. It is **not exact replay of the green mocap joint positions**.
This distinction remains important when a source wingbeat cannot be represented
by weights and small shared geometry changes.

## Data and transition contract

`prepare_skin_corpus.py` inventories authentic `GG_FF.png` plates through the
existing DEF reader, applies the recorded shared NN canvas, removes DEF shadows,
and verifies that the prepared idle matches the known registration image.

Every source group keeps every authored frame, including the first and last
attack frames. Capture episodes use explicit context lists:

- Actions: full authored idle context, complete action, full idle context.
- Death: idle context followed by death; no invented recovery.
- Movement: idle, authored start, flight cycle, authored stop, idle. Each group's
  target indices refer to its exact section of that same temporal sequence.

`capture_skin_corpus.py` encodes unique paths once, loads the frozen model once,
and captures clips separately under the global GPU lock. Context frames are
marked separately and excluded from fitting targets and exported clip timing.
The actual donor sequence capacity is checked; there is no silent truncation.
Common canvas dimensions, safe keys, source hashes, capture hashes, and explicit
source/context index ranges are validated.

Crucially, a clip's predicted leading idle is **not its rest reference**. The
network changes that prediction with temporal context. All clips instead use
the single SHA-pinned `idle_reference_v1.json` asset calibration. The first
corpus attempt violated this distinction and must not be reused.

## Optimization and checks

`run_skin_mesh_pilot.py` runs surface repair, constrained weight fitting, joint
weight/mesh fitting, then a final all-frame fit. One interior frame from each
eligible clip is initially withheld. The final stage uses every authored frame;
final scores are training-fit diagnostics, not unseen-data generalization.
Withheld indices are not guaranteed pixel-unique, so the preliminary split is
also not an independent semantic validation set.

The animated constraint measures triangle principal stretch/compression against
the immutable original rest triangles, with tail-strain penalties. A barrier
and explicit control-step backtracking keep rest triangles inside 0.8..1.25
principal stretch and prevent rest normal flips. Backtracked/rejected steps are
counted in the report, not silently replaced by a different solver.

Export-time checks are in the runner and its imported validators:

- `skin_weight_contract.py`: normalized weights, support, frozen regions.
- `validate_rest_field`: finite vertices, frozen anatomy, duplicate consistency.
- `SurfaceConstraints.rest_gate`: displacement, triangle bounds, rest flips.
- `verify_calibrated_export`: serialized animation parity for every keyframe.

Invalid rest geometry prevents GLB export. Diagnostic NPZs are explicitly named
`diagnostic_candidate.npz`. Separate quality gates check idle appearance, depth
clipping, and animated-surface strain. A passing rest/export contract does not
override a failed animated-quality gate. These tools are not part of runtime
deployment, and their diagnostic GLBs must not be installed as approved assets.

## Measured result: September 6

Latest capture: `artifacts/homm3_mocap_v2/skin_mesh_pilot/captures_v2/`.
Latest fit: `artifacts/homm3_mocap_v2/skin_mesh_pilot/all_def_v4/`.
Off-angle checks: `artifacts/homm3_mocap_v2/skin_mesh_pilot/all_def_v4_off_axis/`.

Fresh capture including encoding/model load took 70.12 seconds for the corpus.
The constrained fit, source previews, and 15 serialized export checks took
85.09 seconds. These are measured compute runs, not total development time.

| Metric | Original | Weight-only checkpoint | Final skin + mesh |
| --- | ---: | ---: | ---: |
| Mean per-frame principal-stretch P95 | 3.006 | 2.040 | 2.001 |
| Mean triangle fraction exceeding 1.5 stretch | 13.23% | 10.30% | 10.07% |
| Flight mean silhouette IoU | 0.4896 | 0.5067 | 0.5153 |
| Front attack mean silhouette IoU | 0.4963 | 0.4942 | 0.4982 |
| Movement start mean silhouette IoU | 0.4419 | 0.4325 | 0.4379 |
| Movement stop mean silhouette IoU | 0.5332 | 0.5462 | 0.5502 |
| Death mean silhouette IoU | 0.3774 | 0.3780 | 0.3836 |

The final stage continues weight optimization and uses additional images, so
the difference from the earlier weight-only checkpoint is not a controlled
mesh-only ablation. Do not attribute the entire final gain to geometry changes.
Scores also exclude repeated idle context, unlike some historical clip reports.

Maximum rest movement was 0.03235 world units, approximately 1.14% of bbox
diagonal. Rest triangle ratio violations and normal flips were zero. Mean
idle alpha difference was 0.000757 over the padded image. All 15 GLBs passed
serialized parity. All 29 focused CPU/CUDA tests passed.

The **animated-surface gate fails**. Off-angle folds and insufficient articulation
remain visible. More frames improve coverage and expose contradictions, but do
not by themselves make the current surface/rig representation adequate.

Historical runs: `all_def_v1` used incorrect per-clip rest references and very
restrictive mesh regularization; `all_def_v2` corrected the reference but allowed
invalid rest triangles; `all_def_v3` used full transition context and projection
but frequently stalled on the rest boundary. `all_def_v4` adds the interior
barrier and is the latest inspected result, not an accepted asset.

## Run

Use `artifacts/homm3_mocap_v2/venv/Scripts/python.exe` from the repository root:

```text
experiments/homm3_mocap_v2/prepare_skin_corpus.py --source <active CROC.dir> --output <new source directory>
experiments/homm3_mocap_v2/capture_skin_corpus.py --manifest <source directory>/manifest.json --output <new captures directory>
experiments/homm3_mocap_v2/run_skin_mesh_pilot.py --corpus <captures directory>/corpus.json --output <new fit directory> --iterations 200 --seconds 600
experiments/homm3_mocap_v2/preview_skin_mesh_corpus.py --run-dir <fit directory> --output <new off-angle directory>
```

All output directories refuse overwrites. Only one GPU process may run at a time.
The next useful experiment should isolate whether articulation-aware topology
or the fixed motion-to-surface correspondence is limiting the fit. Do not simply
relax shape checks until the renderer can manufacture a matching silhouette.
