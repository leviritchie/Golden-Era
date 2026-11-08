# Orc and Ogre Expansion Results

2026-09-06. Generated candidates only; neither unit is visually accepted or
installed. The shared solver was unchanged. All original DEF groups were used.

## Preparation and review

Dedicated profiles inspect the original source rigs rather than borrowing bone
indices: Orc has 66 source joints and Ogre 29; each gets the established
25-joint capture graph fitted to its mesh. All target bones are explicitly
mapped. Both generated binds passed branch, visible-geometry preservation,
and serialized rest-identity checks. Root and a review agent inspected the
multiangle bind sheets.

The initial Ogre profile failed review: it confused the club tip with the wrist
and assigned arms inconsistently with legs. This was corrected before the first
skin preparation. Bone_020 is the right wrist, Bone_019 the rigid club endpoint;
positive-X limbs are left and negative-X limbs right. This was preparation
authoring/review cost, not an automated solver correction.

Orc has no independently declared rigid weapon region in this preparation;
distal source geometry follows explicit hand ownership. Ranged prop release and
terminal hand rotation are not independent captured articulations.

## Runs

Artifacts are under artifacts/homm3_mocap_v2/skin_mesh_pilot/{orc,ogre}.
Owned preparation is under shape_preserved/h3_{orc,ogre}/preparation/mapped_skin_v1.

| Stage | Orc | Ogre |
| --- | ---: | ---: |
| Authored groups / frames | 18 / 103 | 15 / 85 |
| Capture, including encoder and model load | 74.34 s | 66.86 s |
| Owned preparation | 17.97 s | 17.70 s |
| Idle registration | 3.05 s | 2.47 s |
| Original constrained skin + mesh fit, previews, exports | 115.01 s | 91.73 s |
| Continuous-weight comparison, fitting + previews | 54.35 s | 44.31 s |

These are measured stage timings, excluding source preparation, process startup
outside the stage timer, profile authoring, review, orchestration, and debugging.
They are not end-to-end onboarding or model-cost measurements.

The original constrained baseline uses 200 steps and a 600-second budget through
run_skin_mesh_pilot.py. All 18 Orc exports and all 15 Ogre exports pass serialized
animation parity for all 103/85 frames respectively. Maximum vertex errors are
5.62e-7 and 3.84e-7. Baseline quality gates still fail:

- Orc: idle appearance and animated surface; rest geometry and depth pass.
- Ogre: depth clipping and animated surface; rest geometry and idle appearance
  pass. The report counts 333 clipped animated vertices.

The separate continuous-weight comparison uses the same .015 topology prior,
200 steps, and 120-second fit budget as the retained Goblin experiment. Motion,
camera, bind, and original geometry stay fixed. No Goblin weapon landmarks were
transferred. It improves the recorded surface objective from 2.578 to 1.095 for
Orc and 2.899 to 1.496 for Ogre. The image objective improves only modestly.
The 90% region-centroid motion floor is a soft penalty: 14 of 94 observable Orc
rows and 7 of 85 Ogre rows remain below it. These are not acceptance passes.
Continuous-fit outputs are NPZ skins and comparison GIFs, not parity-validated
GLB exports; the baseline's export proof must not be attributed to them.

## Visual findings and next action

Orc front shooting misses source weapon elevation and follow-through. Ogre has
recognizable attack and death events but incorrect direction/body pose and
remaining distortion. Improved strain alone does not establish correct motion.
The comparisons are useful generalization evidence, not satisfactory animations.

Next expand to Cyclops before another unit-specific refinement loop. Retain
these runs unchanged when testing any later shared camera, motion, or skinning
correction. No current result replaces an earlier stronger candidate.

Validation: 29 focused CPU tests passed across the new profiles, mapped skin,
source initialization, corpus preparation/capture, motion loading, and inventory.
The final profile/preparation review found no remaining P1/P2 mapping issue;
that does not prove animation quality. Existing preparation/fitting/export gates
remain the executable contract. No runtime build or deployment was performed.
