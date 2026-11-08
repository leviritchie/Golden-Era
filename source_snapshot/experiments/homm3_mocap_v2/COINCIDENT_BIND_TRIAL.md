# Coincident Bind And Ownership Trial

2026-09-06. Generated diagnostic evidence only. Neither candidate is promoted;
no production preparation, motion selector, source mesh, or delivery changed.

## Contract And Structural Evidence

`coincident_bind_candidate.py` validates translation-only inverse binds,
normalized nonnegative weights, rest/FK agreement and serial source-zero groups.
It includes the parent of the first zero edge, moves all group sites to the
terminal's original rest position, regenerates inverse binds, and merges group
weights once onto that terminal. Other world joint sites and all rest geometry,
UVs, topology and texture remain unchanged. Forks and observable sibling branches
are rejected. Neutral LBS is evaluated, not inferred from unchanged vertices.
The no-group path validates and returns an exact deep copy. Reports expose the
1e-8 source-zero tolerance and actual edge norms; assessed bird edges are exact
zeros, not small nonzero anatomical edges. These checks run before diagnostic
rendering; there is no new build/deploy contract or production activation.

Roster audit found source-coincident Hips/Pelvis separated in all three Eagle
skins: Roc 0.406988, Thunderbird 0.393310, Shahrokh 0.168216. The ordinary
25-joint skins have no analogous source-zero edges. Mounted composite skins
were excluded because their captureOffsets are fitted composite offsets, not
raw donor offsets. Thunderbird additionally collapses a nonzero source tail
edge; this trial does not correct that separate issue.

## Controlled Results

Current evidence lives under `artifacts/homm3_mocap_v2/skin_mesh_pilot/`:
`{thunderbird,shahrokh}/rigid_coincident_v2.json`, `coincident_bind_v2/`, and
`coincident_local_v2/`. V1 predates final provenance/no-op validation; V2 was
regenerated and all four comparison implementation ledgers verified against
current files. These comparisons use ORIGINAL prepared skins, not previously
optimized skin-plus-mesh candidates. Every group is included: 15 groups and
92 frames per unit, 368 candidate frame evaluations across four runs.

The 13-pose rigid controls rotate the unchanged source reference through
neutral and +/-45/90 degrees on each axis. Canonical ownership plus local
rotation transfer preserves the entire weighted mesh: maximum vertex errors
3.82e-14 (Thunderbird) and 2.20e-13 (Shahrokh). Moving the bind sites but keeping
old ownership leaves errors 0.681735 and 0.399631 respectively. This proves
the structural ownership issue matters; it does not prove a good wingbeat.

| Unit | Candidate | Baseline IoU | Candidate IoU | Baseline color error | Candidate color error | Seconds |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Thunderbird | Bind + ownership, current motion | .548298 | .548263 | .467514 | .467957 | 18.07 |
| Thunderbird | Bind + ownership, local transfer | .548298 | .491581 | .467514 | .477601 | 17.83 |
| Shahrokh | Bind + ownership, current motion | .534410 | .533961 | .631564 | .632012 | 18.52 |
| Shahrokh | Bind + ownership, local transfer | .534410 | .492519 | .631564 | .635382 | 18.80 |

Frame-weighted means; higher IoU/lower color error is better. Bind correction
alone barely changes scores. Local transfer regresses both units. Inspected
move contact sheets still lack the source wing opening; no promotion justified.
73.22 seconds is the FINAL cached render/score pass only. Earlier V1 trials
took another 74.90 seconds, plus CPU audits, tests, code/review and inspection.
Neither timing includes new mocap, optimizer fitting or delivery export.

Roc was audited structurally but not rendered here. Its legacy registration
records the exact calibration hash but no calibrationPath and does not meet
this runner's idle-only provenance contract. No historical report was rewritten
and no calibration fallback was added to force a third result.

## Remaining Motion Boundary

Luna's Thunderbird move audit found substantial raw wing edge excursions
(about 32-80 degrees), and substantial transferred local excursions. Strong
weight support rules out absent wing influences, NOT wrong spatial ownership.
After applying the exact static whole-body Q, target/source reference edge
misalignment is still 77-90 degrees on right distal segments and 41-83 degrees
on left distal segments. Earlier unaligned-axis numbers were discarded.
This supports a rest-chain orientation/proportion mismatch as a contributor;
it does not establish that all remaining failure is bone placement or exclude
spatial skin ownership. Do not amplify mocap angles to compensate blindly.

Next investigation must separate source motion, target rest correspondence,
and spatial influence ownership on these same frames. Preserve the user's
fixed-mocap authority: improve the mesh/bind/skin relationship rather than
fitting special-case wing or attack angles. All 21 Stronghold units remain in
scope, including the independently unresolved genuine Boar Rider mesh.

## Verification

31 focused tests passed across coincident preparation (9), local rotation,
capture stages, aligned motion, rigid audit and body-relative motion. New tests
cover rigid weighted mesh versus position-only negative control, serial chains,
fork/sibling rejection, invalid inverse binds, nonfinite/unnormalized weights,
input immutability and exact no-op. Independent Luna review checked candidate
ownership/binds and comparison baseline separation; metadata findings were
addressed before V2. Synthetic, generated and runtime proof remain distinct.
