# Image-supervised skin-weight pilot

Experimental generated-candidate proof only. No accepted asset or runtime deployment.

The subsequent full-DEF skin-and-mesh experiment is documented in
`SKIN_MESH_CORPUS.md`. This file records the earlier weight-only pilot.

## Contract

`run_skin_weight_pilot.py` fits one shared weight field against six attack frames,
with the entire flight clip excluded from training and checkpoint selection.
Motion is the existing frozen idle-calibrated adapted transform sequence, not
raw mocap joint replay. Vertices, topology, UVs, texture, skeleton, inverse bind,
and animation are unchanged. Camera registration uses the original idle mesh
and idle source only; the resulting camera is frozen during fitting.

The scorer combines silhouette, boundary distance, multiscale coverage, and
luminance-normalized chroma. Anatomical support, shared duplicate groups, weight
priors, spatial regularization, and edge strain limit the search. The current
Roc profile supplies anatomical regions; cross-unit robustness is not proven.

`skin_weight_contract.py` runs in the candidate export path. It refuses invalid
normalization, negative/nonfinite values, more than eight influences, forbidden
anatomical influences, or changes to frozen regions. The runner separately
checks idle identity and serialized GLB parity at every animation keyframe.
The holdout gate checks mean silhouette gain and pooled edge-stretch P95;
passing it does not establish visual quality or prevent local surface damage.

## Reproduce

From the repository root, use `artifacts/homm3_mocap_v2/venv/Scripts/python.exe`:

```text
experiments/homm3_mocap_v2/run_skin_weight_pilot.py --output <new-directory> --seconds 600 --iterations 400
experiments/homm3_mocap_v2/preview_skin_weight_pilot.py --pilot-dir <run-directory> --output <new-diagnostic-directory> --resolution 320
-m unittest discover -s experiments/homm3_mocap_v2 -p test_skin_*.py
```

CUDA tests require `RUN_SKIN_IMAGE_CUDA_SMOKE=1` and the global cascade lock.
Both runnable experiment CLIs acquire that lock themselves. Do not run another
GPU worker concurrently. Outputs refuse overwriting. Timing excludes fresh
mocap inference; the run consumes cached captures.

## September 6 Results

Artifacts: `artifacts/homm3_mocap_v2/skin_weight_pilot/`.

- `roc_v1`: rejected registration due to unconverted historical Z-up camera.
- `roc_v2`: stopped by batched tensor-contiguity renderer bug.
- `roc_v3`: obsolete color fit, texture V orientation was wrong.
- `roc_v4`: first corrected fit; silhouette gate passed, off-angle appearance
  did not. Synthetic GIF middle column was mislabeled frozen rather than perturbed.
- `roc_v5`: reporting/label corrections and repeat at unchanged fitting settings.
  Excludes attack frame zero from holdout because it registered the camera.
  Stores source/code hashes, per-frame strain, and explicit timing scope.

Latest measured results (`roc_v5/pilot_report.json`):

| Held-out images | Original IoU | Learned IoU | Edge stretch P95 before / after |
| --- | ---: | ---: | ---: |
| Attack, excluding training and registration | 0.69053 | 0.73277 | 1.19995 / 1.23032 |
| Entire flight clip | 0.50704 | 0.54896 | 2.20204 / 2.43681 |

Raw RGB error also decreased on both holdouts. That recorded metric is not the
normalized-chroma training loss, and does not establish perceptual quality.
The latest candidate **fails** the flight deformation gate. GPU optimization
is not bitwise deterministic: the unchanged-settings repeat varied enough to
cross the 10% relative strain threshold. Neither candidate should be promoted.

Measured cached pipeline time was 23.05 seconds including CPU preparation and
lock wait; the timed GPU-stage pipeline was 21.17 seconds. This leaves runtime
headroom but is not a fresh-capture end-to-end benchmark. All 12 focused tests,
including batched CUDA texture orientation and vertex gradients, passed.
Idle vertex identity and exported-animation parity passed for both clips.

Off-angle diagnostics rotate the source view by 90 degrees and use one framing
over the union of both skins and every frame in both clips. They do not train
or score against a nonexistent side-view source. Visible folds and stretched
surfaces remain, despite improved source-view outlines.

## Decision

Keep the image-supervised weight-fitting direction, reject these skins as final
assets. A silhouette reward can be achieved through unacceptable local strain;
the current pooled regularizer and gate are insufficient. The next bounded
experiment should impose local triangle stretch/compression and region-boundary
constraints before increasing image-fitting freedom. Preserve fixed motion and
shared weights, and reserve new frames/clips for an untouched validation set:
flight has now informed the development decision and is no longer a fresh test
set for subsequent algorithm selection. If constrained weights cannot improve
the image fit, test representational limits rather than silently moving bones.
