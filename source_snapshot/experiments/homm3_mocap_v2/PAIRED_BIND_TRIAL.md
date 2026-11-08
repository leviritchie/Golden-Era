# Paired Bind Diagnostic

Generated diagnostic only, 2026-09-06. Not promoted. Existing profiles retain
their polyline fitting behavior and all previous candidates remain unchanged.

`audit_bind_pivot_correspondence.py` reads frozen preparation and current mesh
sites, checking profile and NPZ hashes before measuring their correspondence.
The eight-asset report is `artifacts/homm3_mocap_v2/bind_pivot_audit_v1.json`.
Polyline fitting samples target chains using donor arclength fractions, so
interior fitted sites need not coincide with the supplied anatomical sites.
This is a measurable preparation behavior, not proof of the visual root cause.

The opt-in `paired_landmarks` fitter places equal-count, unique named sites
directly. `paired_bind_candidate.py` copies the profile and recomputes inverse
bind matrices. The comparison runner changes only those bind sites and inverse
binds; source captures, camera, geometry and weights stay fixed. No unit-specific
solver adjustments or production selection were added.

## Result

V1 outputs live in `skin_mesh_pilot/<unit>/paired_bind_v1` under the mocap
artifact root. These use ORIGINAL prepared weights, not the fitted skin-plus-
mesh candidates. Scores are frame-weighted training-frame means.

| Unit | Frames | Original IoU | Paired IoU | Original color error | Paired color error |
| --- | ---: | ---: | ---: | ---: | ---: |
| Orc Chieftain | 106 | .55312 | .55433 | .46333 | .46351 |
| Ogre Mage | 109 | .53715 | .53884 | .45156 | .45084 |
| Cyclops King | 161 | .63820 | .63275 | .63872 | .64063 |

Higher IoU and lower color error are better. The small mixed changes do not
justify promotion. Mage attack inspection still shows weak/misdirected motion
and arm distortion. Fixing site correspondence alone is not a visual solution.
Render/score times were 22.14, 18.82 and 25.52 seconds, excluding authoring,
analysis and orchestration.

The Behemoth comparison stopped before output creation because its historical
registration lacks an explicit calibrationPath. No calibration was guessed and
no older registration was changed. Therefore there is no Behemoth regression
result for this experiment.

V1 reports pin the implementation that actually ran. Additional candidate
profile/donor/mesh hashes and candidate NPZ hashing were added afterward, so
those newer metadata fields are absent from V1. Do not relabel V1 as execution
of the final metadata revision. No rerender is needed to reject this trial.

Four focused paired-bind tests pass, covering exact placement, rejection of
ambiguous site lists, copy isolation and metadata. Two use mocked CPU inputs;
they do not establish rendered visual quality. Independent review found no
remaining fallback or topology bypass. Continue broadening the unchanged
baseline cohort rather than tuning this diagnostic on these three units.
