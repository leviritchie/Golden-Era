# Corrected Wolf Rider and Goblin

Audited 2026-09-06. Both units have explicit owned preparation, source-pinned
inputs, and fifteen of fifteen export-parity checks passing. Neither unit is
accepted for delivery or runtime use.

## Wolf Rider

Semantic identity is authoritative in `mounted_asset_identity.py`: Wolf Rider
uses `h3_wolf_rider_smartrigged.glb` (sha 2fb1bb07); Wolf Raider uses
`h3_wolf_raider_smartrigged.glb` (sha b15de4cf) (2026-09-27: the two files were renamed so each basename now names its own unit; pre-swap bytes and note in `artifacts/meshy_downloads/_superseded_do_not_use/wolf_identity_swap_20260927.note.json`.) Before that date the basenames were swapped. Historical preparations and fits under the
old pairing remain diagnostic only. The corrected Wolf Rider all-DEF candidate
completed in 85.3998897 cached seconds and was rejected for idle appearance
and animated-surface quality. Its exported parity checks pass, but that does
not promote the animation.

The camera comparison experiment ranked yaw 55 degrees ahead of yaw 115
degrees using silhouette plus chroma. This did not support the proposed
camera-side correction and was not integrated into default registration.
That is a search result, not a motion-quality
or delivery decision. The explicit local calibration registration and the
corrected source identity are required before any retained corpus is reused.

## Goblin

Goblin uses the 80-bone source map with explicit proximal overrides and rigid
club ownership on `Bone_079`/`Bone_078`. Preparation and all 15 export-parity
checks pass. The all-DEF candidate completed in 89.8952 cached seconds and
passed rest-shape, idle-appearance, and depth-unclipped gates, but failed the
animated-surface gate. The attack contact is recognizable, yet the club
trajectory remains wrong for the forward strike. Mesh optimization is not a
substitute for correcting that captured trajectory.

## Reusable Changes

Mounted preparation now supports an unpublished candidate and explicit
hash-checked activation, preserving the prior central freeze. Composition
validates seat and held-child offsets against the canonical bind offsets
without rewriting those bytes. Registration owns its calibration file within
its output directory; runners require the explicit recorded path and hash,
rather than inferring a shared location from preparation-directory depth.

Reported cached times include fitting, comparison previews, and GLB exports.
They exclude source preparation, mocap capture, model startup, anatomy
authoring, investigation, and review. They are not total wall-clock onboarding
times or a claim that these rejected candidates meet the final quality target.

## Boundary

These are generated-candidate and export-parity results. No claim of user
acceptance, installed delivery, runtime behavior, or satisfactory animation is
made for either unit.
