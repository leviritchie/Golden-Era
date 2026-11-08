# Pose-Conditioned Mesh Pilot

Status: first diagnostic representation implemented and exercised on all three
pilot units. Not visually accepted or delivery-proven. See results below.
The faction objective remains all 21 Stronghold units. This pilot is not a
replacement acceptance target.

## Decision

Stop the current Eagle reference/context/cadence parameter sweep. Native donor
controls validate the geometry and decoding, while candidate poses still miss
the source wing action. Those tests do not justify another unbounded skin fit.

The current `MeshField` is explicitly one pose-independent rest displacement.
Test a different mesh representation while keeping mocap trajectories fixed:
a small shared set of corrective deformation fields whose coefficients depend
on the mocap pose. Do not add per-frame vertex targets or alter captured joints.
This follows the user's fixed-motion skin/mesh fitting direction; it is not a
return to predicting joint movements from silhouette scores.

## Bounded Experiment

- Start from immutable, existing target preparation and fixed motion transforms.
  Compare against the same baseline geometry, skin, cameras, frames, and scorer.
- Use Thunderbird, Shahrokh, and Ogre as separate fits with the same algorithm
  and parameter budget. Ogre is a non-wing transfer check, not proof for all units.
- Add four spatial corrective modes with pose-derived coefficients. Reuse
  lattice interpolation, duplicate-position grouping, frozen-region handling,
  and surface constraints from the existing mesh/skin pipeline where applicable.
- Features come from fixed local rotation matrices relative to the preparation
  neutral pose. Do not use frame number, clip name, elapsed time, or evaluation
  images as features. Derive any feature reduction from training poses only.
- Corrective displacement must be exactly zero at neutral. Preserve existing
  idle appearance with an explicit independent gate; neutral identity alone
  does not prove correct animated idle.
- Freeze base weights/rest shape for the first comparison. This isolates the
  added representation instead of changing motion, weights, and geometry together.
- Train with the existing silhouette/chroma scorer, retaining surface strain,
  orientation, displacement, and spatial smoothness constraints. Log rejected
  steps rather than silently dropping a constraint or substituting a baseline.
- Withhold the whole upward-attack group and deterministic frames from movement
  and other training groups. Freeze the split before fitting. Evaluate startup,
  stop, loop boundary, and interpolated-pose behavior independently.
- Cap optimization at 300 seconds per unit, excluding clearly reported source
  preparation and preview time. Report actual time and peak memory; the user
  target remains less than ten minutes per delivered clip.

## Feasibility Gates

Before image fitting, test zero-neutral identity, exact duplicate agreement,
frozen-region preservation, finite gradients, feature/input immutability, and
identical-pose determinism across different clip/frame labels. Exercise the
actual corrective calculation, not a mocked decoder or constant fixture only.

Before promotion, inspect DEF/baseline/candidate GIFs for all three units. Require
held-out image improvement without worse idle/rest appearance or surface safety.
An attractive fitted frame, lower training loss, or larger motion alone is not
success. Report whether similar mocap poses demand conflicting source shapes;
if so, do not conceal that limitation by adding frame-specific latent variables.

## Delivery Boundary

`eagle_glb.py` currently exports skeletal rotation/translation channels, not
morph targets or morph-weight tracks. A successful corrective mesh diagnostic
therefore still needs an explicit export/import/playback path and parity tests.
Do not claim mesh sequences are deliverable skeletal clips, silently bake one
mesh per frame, or introduce a billboard path. Choose and validate delivery only
after the representation demonstrates held-out visual value.

If this pilot cannot recover useful motion without excessive deformation or
pose ambiguity, record that the fixed-pose representation is insufficient for
those cases. Do not continue increasing flexibility until it memorizes frames.
Any move to authored/corrected joint trajectories is a separately named change
of motion authority, not a hidden fallback inside the skin solver.

## First Results

`pose_corrective_field.py` implements four bounded lattice modes driven by
uncentered training-only rotation SVD features. Coefficients use RMS projection
scales, so duplicating the training corpus does not attenuate corrections.
Neutral-pose coefficients are exactly zero irrespective of learned controls.
Modes reuse `MeshField` duplicate-position and frozen-region behavior.

`run_pose_corrective_pilot.py` completed all 15 groups for Thunderbird, Shahrokh,
and Ogre under `artifacts/homm3_mocap_v2/pose_corrective_v1/`. Upward attack and
every third selected frame elsewhere are excluded from image training; there
is no subsequent all-frame refit. All poses remain geometry witnesses, so these
are held-out IMAGE results, not a claim that evaluation poses were never seen.

| Unit | Held-out IoU, baseline | Corrective | Fit seconds | Total cached seconds |
| --- | ---: | ---: | ---: | ---: |
| Thunderbird | 0.537928 | 0.538478 | 11.811 | 25.747 |
| Shahrokh | 0.519879 | 0.525098 | 14.491 | 28.716 |
| Ogre | 0.564199 | 0.577854 | 10.645 | 22.342 |

The comparison baseline is frozen PREPARED mesh/weights, not the earlier
optimized skin/mesh result. These numbers therefore do not prove improvement
over the best existing candidate. All 45 fixed-motion hashes match the earlier
full-corpus fit reports (Thunderbird all_def_v2, Shahrokh/Ogre all_def_v1).
This permits a fair subsequent comparison with those fitted meshes under the
same motion; no motion regeneration is needed.

Neutral corrective displacement is exactly zero in all three outputs. Animated
idle alpha differences are 0.001257, 0.002510, and 0.000696 respectively. Worst
per-frame p95 surface stretch remains 2.4269, 3.3224, and 2.4664, above the
existing 1.5 acceptance limit. The inspected Thunderbird move, Shahrokh upward
attack, and Ogre upward attack sheets do not recover sufficient action.
No animation or production selection is promoted.

Eleven focused field/split tests passed, including actual control gradients,
neutral identity after nonzero control updates, duplicated-training-set scale
invariance, frozen/duplicate vertices, and deterministic whole-clip holdout.
The full pilot is still incomplete: interpolated-pose/transition gates, conflict
analysis, and export/import/playback remain unproven. The next comparison should
start from the already optimized fixed skin/mesh, not ask the small corrective
field to repair all of the original preparation's deformation defects.

`validate_pose_corrective_artifact.py` was subsequently run on all three saved
outputs. It independently reconstructs the feature/spatial buffers before loading
controls, verifies recorded input/code hashes, and checks finite mesh arrays,
bounded displacement/coefficient sums, exact neutral zero, frozen vertices, and
duplicate agreement. All structural field checks passed. Reported surface p95
and compression gates fail for every unit; idle-alpha and held-out image
non-regression gates pass. It explicitly validates reported quality metrics,
not independent rendered-mesh parity or runtime delivery. The validation records
are each unit's `validation.json`. No claim of full pilot acceptance follows.

## Fitted-Base Comparison

The explicit `--base-fit` path now loads final vertices/weights from an earlier
fixed-motion fit through `fitted_corrective_base.py`. The loader checks asset,
prepared-skin/corpus identity, every motion hash, and finite normalized skin
arrays. Only vertices and weights change; no bind or motion metadata changes.
A requested fitted base cannot silently fall back to the prepared mesh.

All three completed under `artifacts/homm3_mocap_v2/pose_corrective_fitted_v1/`.
These bases were previously fitted on ALL images. The excluded-frame scores
below measure incremental corrective fitting only, not independent whole-pipeline
generalization. Neutral preservation means exact preservation of the chosen
adapted base mesh, not restoration of the original preparation's geometry.

| Unit | Existing-fit IoU | Corrective IoU | Fit seconds | Total cached seconds |
| --- | ---: | ---: | ---: | ---: |
| Thunderbird | 0.525485 | 0.519489 | 11.809 | 25.668 |
| Shahrokh | 0.521318 | 0.525932 | 14.562 | 29.028 |
| Ogre | 0.573798 | 0.584129 | 10.674 | 22.394 |

Thunderbird also worsens color error; the other two improve it slightly.
All three again pass structural field checks but fail reported surface p95 and
compression limits. Neutral correction and duplicate differences are exactly
zero. The inspected Thunderbird/Shahrokh movement and Ogre attack comparisons
still lack sufficient action. No result is promoted, and increasing corrective
mode count or bounds is not justified by these results alone.

Fifteen focused field/split/fitted-base tests passed. CPU artifact validators ran
on all three outputs, including input/implementation hash checks and fitted-base
reconstruction. Luna reviewed the explicit base selection and provenance path.
Older prepared-base outputs remain historical evidence tied to the implementation
at commit `1d4a0932be`, not outputs of the subsequently modified runner.

## Surface-Loss Attribution

A read-only calculation on the fitted-base Thunderbird/Shahrokh baseline mesh
sequences measured the squared boundary penalty from `surface_constraint_loss`.
For each triangle, average its squared violation over frames and both principal
stretches, then select the largest ceil(1% of valid triangles) contributions.
Thunderbird: 87.5836% of that penalty comes from this set, covering 0.7497% of
rest area. Shahrokh: 74.6835%, covering 0.8777% of rest area.

This is not evidence that these faces may be ignored: a concentrated penalty
can reflect real tears. The existing mean-log term is already area-weighted,
whereas the squared violation and worst-face terms are not. Next inspect the
offending faces in image space, including positive-feedback Hobgoblin/Behemoth
controls, before changing any loss weight or acceptance threshold. Motion
fidelity remains a separate unsolved issue; loss concentration does not explain
or excuse the absent wingbeat by itself.

### Rendered Four-Unit Check

`run_surface_loss_attribution.py` completed all 15 clips for Thunderbird,
Shahrokh, Hobgoblin, and Behemoth. Retained same-code outputs are under
`artifacts/homm3_mocap_v2/surface_attribution_v2/<asset>/`. This is diagnostic
replay of existing fitted bases, not a new fit or an accepted animation set.
The runner uses the fit report's explicit motion-reference path and verifies
its hash against both fit and registration records. It checks source-frame
identity, skeleton inventory, shared reference, and every fixed-motion hash.
Camera hashes are recorded, not retrospectively proven against older fit
reports that did not pin the camera hash.

Each GIF shows DEF, textured fitted mesh, and a gray mesh with the clip's
top 1% squared-boundary contributors colored red. Expanded triangle corners
with constant face UVs make the colors face-specific; the renderer is rebuilt
for each clip. Red-pixel fractions are thresholded visible coverage of the
whole canvas, not percentages of the mesh or exact geometric area. Rankings
are per clip, unlike the whole-corpus calculation above.

Movement-clip evidence (percentages averaged over authored frames):

| Unit | Top 1% boundary share | Top rest area | Violating rest area | Red canvas area |
| --- | ---: | ---: | ---: | ---: |
| Thunderbird | 89.768% | 0.754% | 29.110% | 0.084% |
| Shahrokh | 80.524% | 0.914% | 36.208% | 0.194% |
| Hobgoblin | 96.257% | 0.561% | 2.890% | 0.022% |
| Behemoth | 87.752% | 0.706% | 6.695% | 0.185% |

Concentration also occurs in the positive-feedback controls, so it does not
distinguish missing action from better motion. Crucially, area-weighted
violations are still widespread in the birds: their defects cannot be dismissed
as only tiny triangles dominating a count-based metric. The inspected movement
and upward-attack sheets show localized red patches alongside much larger pose
mismatches. Hobgoblin's overhead action also remains incomplete; earlier positive
feedback does not establish that every clip is satisfactory.

Eight focused helper/face-UV tests passed, including invalid-face exclusion,
original face IDs, independent boundary arithmetic, and changing clip selections.
Luna reviewed the corrected renderer and provenance path. Same-code replay,
attribution, and previews took 9.87 / 9.51 / 8.16 / 8.23 seconds respectively
(35.77 seconds total), excluding process startup, mocap, fitting, and engineering.
No motion, weights, geometry, solver loss, or acceptance thresholds changed.
Next work must address source action fidelity and widespread deformation
separately; lowering the surface gate is not supported by this comparison.
