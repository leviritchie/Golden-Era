# Wolf Rider actor isolation control

Status: generated diagnostic only. Neither isolated capture nor revised skin
has been promoted; no new skin optimization or game deployment was performed.

## Experiment

Three authored clips: idle (8 frames), movement (6), front attack (7).
There are 23 unique plates with the original idle/start/stop context included.
`wolf_rider_mask_recipe.py` supplies eye-authored visible rider contours.
`actor_mask_trial.py` preserves original RGB and canvas, partitions alpha into
complementary mount/rider masks, checks exact recomposition, and synthesizes no
occluded anatomy. These are approximate authored masks, not segmentation truth.
The source plate contact sheet exposed two incorrect contours in v1; the used
v2 corrects the attack-2 leg and attack-5 torso contours before inference.

Four lanes are captured: full-plate mount, isolated mount, full-plate rider,
isolated rider. All use the same fixed full-canvas DINO preprocessing, donor
packages, temporal mapping, and inference implementation. This prevents vendor
per-frame recentering from confounding the isolation comparison. The old
vendor-cropped full-plate result is historical context, not this experiment's
control. Hidden RGB under zero alpha is excluded by the actual encoder path.

## Results

Twelve capture clips completed in 64.195 seconds, including 34.648 seconds of
encoding. This excludes mask authorship, tooling, review, and diagnostics; it
is not an end-to-end onboarding benchmark or a model-dollar cost estimate.

Fixed-view raw skeleton inspection shows that actor isolation materially changes
the rider pose, but does not establish a convincing improvement in the strike.
The mount still articulates under either input; isolation alone is not a proven
solution. No quantitative source-landmark accuracy score is claimed. Do not
promote a larger movement or changed pose to better motion accuracy.

Independent +/-30 degree world-X probes on the existing owned skin reproduce
large deformation without mocap. Triangle 13953, for example, joins two vertices
labeled rider_arm_left to one labeled mount_front_left; its mean edge-length
ratio reaches 12.997 under the -30 degree left-arm probe. Triangle 12703 joins
mount_torso and rider_arm_left and reaches 12.807 in the opposite probe.
The non-actuated actor's own vertices remain fixed to numerical precision, so
simple actor leakage checks alone miss the cross-boundary triangle tearing.
These are mean edge-length ratios, NOT principal stretch measurements.

The mount's vendor-named neck is also parent to its front limb branches, so its
probe is a front-body articulation test, not an isolated head test.

## Decision

Do not run another silhouette/chroma optimization on these inputs yet. Two
prerequisites remain: a source-grounded rider-motion acceptance check and a
topology-aware shared ownership correction passing the simple actuator probes.
The current sharp region boundaries and source-rig-derived labels are not
adequate merely because they preserve the initial rest pose. No existing
accepted unit pipeline was changed to use this mounted candidate.

## Reproduction and evidence

Use the existing `artifacts/homm3_mocap_v2/venv/Scripts/python.exe` runtime.
Scripts, in order: `wolf_rider_mask_recipe.py`, `actor_mask_trial.py`,
`isolated_actor_capture.py`, `compare_actor_capture.py`. Their `--help` documents
inputs. Output directories refuse overwrite. `mounted_ownership_diagnostic.py`
is independent of inference and reads the frozen preparation only.

Root: `artifacts/homm3_mocap_v2/skin_mesh_pilot/wolf_rider/`.
Used mask recipe: `actor_mask_recipe_v2.json`; masks: `isolation_masks_v2`.
Captures and timing: `isolated_capture_v1/isolated_actor_capture.json`.
Six fixed-scale comparison GIFs: `isolation_comparison_v1`.
Actuator evidence: `ownership_probe_v2.json`, `.gif`, and `.png`.
Legacy raw capture previews normalize skeleton scale separately per frame;
use the new comparison GIFs for temporal/view comparisons instead.

Tests cover exact alpha partition, unchanged RGB, timeline ordering, hidden-RGB
encoder invariance, and ownership probe geometry. The broader focused suite
passed 53 tests. Visual mask/capture/ownership inspection remains a separate gate.
