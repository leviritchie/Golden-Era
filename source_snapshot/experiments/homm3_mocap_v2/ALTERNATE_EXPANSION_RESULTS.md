# Alternate Expansion Results

2026-09-06. Generated-artifact evidence only. No installation or runtime change.
Existing accepted/stronger candidates were not overwritten. All 21 configured
Stronghold units remain in scope. This pass prioritizes breadth over unit tuning.

## Source And Capture

Each source corpus retains all native DEF groups and every startup/return frame.
NN canvas parameters were reused only after exact normalized idle-pixel equality.
Current native idle SHA pins are checked by capture_candidates.json before GPU
capture. defName is descriptive, not an independently authenticated archive gate.

| Unit | Native source | Groups / frames | Capture total |
| --- | --- | --- | ---: |
| Ancient Behemoth | CABEHE.dir | 15 / 84 | 63.70 s |
| Orc Berserker | lvl3alt.dir | 18 / 107 | 61.30 s |
| Blood-Eyed Cyclops | lvl6alt.dir | 22 / 135 | 70.42 s |

Artifacts: artifacts/homm3_mocap_v2/skin_mesh_pilot/<unit>/corpus_v1 and
captures_v1. Native sources are from the active Golden Era lab; ToA lab SIDs
remain toa_orc_berserker and toa_blood_eyed_cyclops, while capture/preparation
asset IDs are h3_orc_berserker and h3_blood_eyed_cyclops. Source manifests own
frame paths/hashes; mesh profiles need not duplicate that source authority.

## First-Pass Fits

The solver, fixed motion, optimization settings and skin/shared-rest-mesh model
are unchanged. The only shared processing fix was full-canvas registration.

| Unit | Preparation | Registration | Fit / GIFs / export | Parity | Quality failures |
| --- | ---: | ---: | ---: | --- | --- |
| Orc Berserker | 15.26 s | 2.71 s | 102.61 s | 18/18, 107 frames | idle appearance, animated surface |
| Blood-Eyed Cyclops | 14.26 s | 2.70 s | 117.26 s | 22/22, 135 frames | idle appearance, animated surface |

Both passed rest-shape and unclipped-depth gates, but neither is accepted.
Berserker loses the wide axe swing and has a facing mismatch. Blood-Eyed
Cyclops has severe held-rock distortion in original skin; fitted skin reduces
some distortion but loses the overhead throw. No independent projectile release
is claimed. All 40 exports match their generated trajectories; parity is not
motion or visual correctness. Candidate directories are all_def_v1 for both.

These are measured stage times, not onboarding wall time. They exclude source
preparation, LLM profile authoring, corrections, review, failed attempts and
orchestration. No per-unit solver tuning was performed.

## Shared Registration Fix

Blood-Eyed registration_v1 rejected a clipped idle foreground before camera
search: the old centered min(width,height) square excluded part of its tall
canvas. Registration now always uses the canonical max(width,height) padded
square already used by animation fitting. The validator allows this exact
centered outside-canvas square or a valid historical inside-canvas crop, never
an arbitrary offset/oversized crop. Source images are not rewritten.

registration_v2 succeeds using the unchanged corpus, mesh and capture. The
failed v1 directory is retained and was not reused. Tests cover tall, wide,
odd and square canvases, PIL foreground retention, unchanged camera rebasing,
and rejection of shifted/oversized crops. Independent review found no silent
fallback or rebase defect. Old cameras remain intact.

## Ancient Behemoth Gate

Capture completed independently of target mesh mapping. The initial profile
copied numbered roles from standard Behemoth and passed set coverage, but root
inspection plus independent hierarchy review proved anatomical contradictions.
It was quarantined BEFORE preparation; no mapped NPZ, registration or fit was
generated. get_profile raises and the shared registry has no Ancient entry.
ANCIENT_BEHEMOTH_ANATOMY_AUDIT.md records verified parents and the remaining
weighted-mesh review. Do not treat the discarded profile's passing tests as
anatomical proof.

## Diagnostic Disposition

PAIRED_BIND_TRIAL.md closes the small mixed bind-site experiment without
promotion. That trial is separate from these unchanged-baseline expansion runs.
Next breadth targets are Goblin Trapper, Ogre Brute and Ghost Behemoth; resolve
Ancient anatomy independently rather than silently substituting a sibling rig.

Final focused verification: 26 asset-profile tests, 21 capture tests, eight
registration tests, four paired-bind tests and four comparison-runner tests
passed. All three actual source-identity manifests pass, all 40 generated
exports pass parity, and the 21-unit inventory validator passes. These are
source/generated-artifact gates, not game build/deploy or runtime validation.
