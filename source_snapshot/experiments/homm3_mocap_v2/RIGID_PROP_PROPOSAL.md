# Cyclops Rigid Prop Proposal

Status: diagnostic generated-artifact evidence only. No accepted mask, skin
change, motion change, projectile lifecycle, exporter change, or runtime proof.

## Reproduce

Use `artifacts/homm3_mocap_v2/venv/Scripts/python.exe` to run
`experiments/homm3_mocap_v2/propose_rigid_prop_mask.py` with `--asset`,
`--annotation`, and an absent `--output` directory. The three reviewed-input
annotations live in `annotations/*rock_proposal.json`. They are AI-authored
front/side bind-panel polygons, not automatic semantic segmentation.

The existing frozen-preparation loader validates source/preparation identity.
Annotation asset and skin hash must match. Selection intersects two projected
polygons with per-vertex texture chroma/brightness limits. A prop triangle
requires all three selected vertices; mixed triangles remain boundary evidence.
Selection is not visibility-tested. Preview geometry is depth-tested using the
entire mesh in one pass. Before panels show texture; highlight panels deliberately
replace texture with gray/red face identification. CPU UV atlas endpoints differ
from CUDA texel-center coordinates and must not be interchanged.

## Verified Results

Final reviewed outputs: `artifacts/homm3_mocap_v2/rigid_prop_proposals/<asset>/v2`.
The earlier v1 previews used blended diagnostic colors and are superseded.

| Asset | Selected vertices | Prop triangles | Mixed boundary triangles |
| --- | ---: | ---: | ---: |
| h3_cyclops | 999 | 813 | 351 |
| h3_cyclops_king | 1064 | 1200 | 378 |
| h3_blood_eyed_cyclops | 763 | 729 | 453 |

All three actual CPU CLI runs completed. Five focused unittests passed, covering
polygon intersection, all-vertex face selection, color rejection, array
immutability, annotation identity, and malformed annotation/triangle rejection.
Tests do not establish anatomical completeness or automatic mask acceptance.

Visual review: front/side proposals isolate much of the visible rock, while
top views expose holes and unresolved contact boundaries. Do not apply the
selected-vertex set directly as a complete rigid attachment. Mixed triangle
counts are topology counts, not missing surface-area measurements.

Selected-region mean original weights differ substantially: standard Cyclops
RightHand 0.869; King RightHand 0.761 and LeftHand 0.173; Blood-Eyed RightHand
0.300, LeftHand 0.450, Spine2 0.151. These measurements describe the proposal,
not a verified rock-only region, and cannot distinguish bad ownership from
selection contamination by themselves.

## Next Acceptance Gate

Complete and inspect the rock/contact boundary, including obscured geometry,
without selecting fingers or torso. Existing owner weights are diagnostic
evidence, not semantic truth. Only a reviewed complete object region may enter
a rigid-ownership animation experiment. Keep fixed body mocap untouched there.
Rock release and native projectile presentation require a separate explicit
delivery contract; this proposal does not implement either.

## Interior Sampling And Rigid Replay

`compare_prop_face_samples.py` compares the same vertex baseline with seven
interior barycentric samples per triangle, accepting at least five samples
inside both polygons and within the same color bounds. It does not grow through
topology or trust existing bone labels as semantic ownership. The all-face
depth renderer now consumes face IDs directly. Final source-pinned comparisons
are under `rigid_prop_face_samples/<asset>/v2` in the mocap artifact root.

Interior sampling selected 974/1353/983 faces for Cyclops/King/Blood-Eyed,
versus 813/1200/729 for vertex sampling. Visual comparison shows fewer holes
without selecting the whole arm. Anatomical completeness remains unproven.
The three CPU comparison runs took 10.48/9.45/8.30 seconds respectively.

`replay_rigid_prop_faces.py` tests declared named-joint ownership on selected
expanded face corners. Final runs: `rigid_prop_replay/<asset>/v2`, all using
explicit `mixamorig:RightHand`, with no alternate-owner fallback. The producer's
saved mask digest must match before replay. Existing fitted rest vertices,
joint trajectories, texture, camera, and all non-prop corners remain unchanged.
This isolates ownership rather than conflating it with rest-shape restoration.

| Asset | Clips | Cached replay seconds | Max edge error | Max boundary gap |
| --- | ---: | ---: | ---: | ---: |
| Cyclops | 18 | 10.81 | 3.25e-7 | 1.234 |
| King | 21 | 16.51 | 2.87e-7 | 1.347 |
| Blood-Eyed | 22 | 15.84 | 2.39e-7 | 1.271 |

All 61 clips had exact non-prop corner parity and exact neutral fitted-rest
parity. Boundary gaps are distances between duplicated prop/body corners in
model units, across all clips, NOT screen pixels or a watertightness pass.
These large gaps explicitly prohibit treating the corner diagnostic as a
deliverable mesh. Twelve focused tests pass and cover selection, immutable
inputs, neutral/rigid transforms, shared-corner
isolation, and refusal of missing/wrong producer digests before GPU work.

Visual findings: King recovers a substantial overhead rock lift without any
body mocap edits. Some useful motion was hidden by fitted skin ownership, not
absent from capture. Standard Cyclops holds a more rigid rock but retains its
facing/release problems. Blood-Eyed exposes a floating/misaligned rock during
the throw: RightHand is not demonstrated as a sufficient attachment contract
there. None releases the rock correctly. All remain rejected diagnostics.

Next: derive an explicit object/contact trajectory and release lifecycle from
source evidence, not a universal hand-label rule. Preserve the demonstrated
body invariance while resolving contact boundaries. Fixed original motion and
known-good original rest appearance remain separate acceptance requirements.

## Source Visibility Evidence

Every sparse source frame of Cyclops and King g14/g15/g16 was visually reviewed.
Rock presence is true at 0..5, false at 6..12, then true at 13 through the end.
g14 has 16 frames; g15/g16 have 17. Frame 13 depicts a new pickup, not the
projectile returning. The two `annotations/h3_cyclops*_rock_visibility.json`
files pin asset, corpus hash, every source frame hash, and explicit booleans.
`prop_visibility.py` rejects identity/length/type drift. Undeclared clips are
not given default visibility: an explicit visibility run covers declared clips
only. This is a diagnostic interface, not a deployed animation contract.

With `--visibility`, replay renders only non-prop triangles during absent
frames using the same camera/depth renderer; it does not move faces offscreen,
change motion, or invent projectile travel. All six actual shooting comparisons
completed under `rigid_prop_visibility/<asset>/v1`: 7.33 seconds for Cyclops and
8.27 for King. Fifteen focused prop tests passed. Source-timed hiding removes
the main held rock but reveals remnant fragments and poor underlying hand/torso
surface. The mask and fused mesh remain unsuitable for delivery.

Blood-Eyed is not assigned this lifecycle: its inspected original sparse
shoot frames keep a rock/bright effect present and do not show the same release
and pickup sequence. The apparent 40-to-8-frame discrepancy was investigated:
`extracted_battle/.rife120_done.json` records sourceCount 8/outputCount 40 for
groups 14..16. The profile intentionally reads `extracted_battle_source_12fps`;
`prepare_skin_corpus.py` preserves every sparse frame. This is not truncation.
Capture idle context is separately sliced out, not an authored return sequence.

Joint-center contact diagnostics also rule out assuming a universal two-hand
grasp: in Blood-Eyed g15, left hand to RightHand-rigid rock center ranges
0.635..0.898 model units. These are joint-center distances, not exact contact
surface measurements. Do not average two hand transforms and call it solved.

Next mesh work must address the explicit prop/body surface boundary and the
body surface exposed when the prop is absent. Keep source-specific lifecycle
separate from attachment geometry and native projectile presentation.

## Cut-Boundary Audit

Differential topology reports are in `prop_boundary_audit/<asset>_differential.json`.
Coordinates are rounded into 1e-6 bins for diagnostic vertex identity; this is
not an exact distance-tolerance weld and does not modify original geometry.
Only edges with two incident faces before removal and one afterwards count as
new cut edges. Raw boundary totals must not be attributed entirely to the mask.

| Asset | Existing boundary edges | Existing nonmanifold edges | New cut edges | New interface components |
| --- | ---: | ---: | ---: | ---: |
| Cyclops | 87 | 82 | 167 | 11 |
| King | 57 | 0 | 217 | 8 |

Only 3 Cyclops and 4 King interface components are closed simple loops.
The dominant interfaces have branching vertices. Existing skin-owner mixtures
are diagnostic only and do not prove anatomy. Generic hole capping is not
justified by these boundaries: a cap could bridge hand and torso surfaces.

King prepared-bind body-only front/side/top renders are stored beside the v2
face comparison as `body_only_<view>.png`. The front view exposes a large
incomplete chest/contact region even before animation; side/back coverage is
better. This is not solely a mid-animation skinning issue.

A bounded search of Meshy download inventory and the three corresponding Unity
OwnedSkinned/Source directories found no exact body-only or prop-separated
alternate. Existing rigidized/imported copies are not replacement anatomy.
No cap, substitute source, paid generation, or deployment was performed.
Clean-source generation is an option awaiting user preference and explicit
credit approval, not an accepted dependency or a proven repair. Keep local
surface reconstruction separate from a claim to recover unobserved anatomy.
