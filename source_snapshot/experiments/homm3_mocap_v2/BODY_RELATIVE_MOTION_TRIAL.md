# Body-Relative Motion Trial

2026-09-06. Rejected for promotion. No production motion, source captures,
profiles, fitted skins, cameras or delivery exports were changed.

## Demonstrated Failure

audit_rigid_capture_transfer.py rotates each captured idle reference about
its own root at +/-45 and +/-90 degrees around X/Y/Z. The supplied reference
remains UNCHANGED. Rotating both reference and pose would be a coordinate-gauge
test, not this rigid-motion test. The 13 poses have no articulation or length
variation. Distances between every pair of joints must remain constant under
a rigid turn, not merely distances between parent-child bone endpoints.

Actual frozen preparations and registered references produced:

| Unit | Current max pair-distance change / target span | Previous source-aligned candidate | Body-relative candidate |
| --- | ---: | ---: | ---: |
| Ancient Behemoth | 29.79% | 32.41% | below 2e-15 |
| Thunderbird | 50.63% | 51.03% | below 2e-15 |
| Ghost Behemoth | 42.90% | 46.26% | below 2e-15 |

The candidate column reports a dimensionless ratio, not percent.

Source pair-distance drift is below 5e-16. A matched-source-rest target control
through the CURRENT solver stays below 8e-15, while its different fitted-rest
target articulates. Parent-child lengths nevertheless remain fixed. This is
evidence of a motion-transfer defect with different reference postures, not
source inference noise in this synthetic experiment. It does not prove this
defect alone causes the real attack/wingbeat failures.

## Isolated Candidate

body_relative_capture_motion.py estimates a per-frame body rotation using
the existing configured body hubs, removes it and root translation from the
capture, retargets only the residual using the unchanged solver, and reapplies
the body rotation in the target coordinate frame. It is reachable only through
the explicit body_relative comparison option, not the production motion path.

Unknown, duplicate, collinear and numerically ill-conditioned hubs reject
explicitly. Hub-fit residuals, conditioning and inter-frame rotation angles
are reported. Nonrigid hub motion is NOT assumed validated, silently held or
smoothed. Root/world-state checks distinguish translated poses from true bind.

Review prompted conditioning and full-state tests and the hub diagnostics.
The body rotation estimate can absorb articulation because its configured
hubs are not a proven rigid body. This limitation is measured rather than
hidden behind a recovery path.

## Real Clip Comparison

All three units used their ORIGINAL prepared skin, not their subsequently
optimized skin/mesh. Both columns share exactly the same geometry, weights,
camera, calibration, source frames and capture indices. This isolates motion;
it is not a comparison with the user's preferred fitted candidate.

45 groups / 260 authored frames were rendered and scored. Frame-weighted
means below include all available groups. IoU is higher-better; color error
is lower-better.

| Unit | IoU current -> candidate | Color current -> candidate | Comparison time |
| --- | --- | --- | ---: |
| Ancient Behemoth | .63264 -> .63363 | .51515 -> .51396 | 14.17 s |
| Thunderbird | .54830 -> .54164 | .46751 -> .46674 | 19.44 s |
| Ghost Behemoth | .63946 -> .63192 | .77537 -> .77907 | 13.87 s |

Visual review does not show recovered overhead claw reach or wing opening.
Thunderbird instead exhibits excessive body turning. Hub rigid-fit RMS,
normalized by reference hub radius, reaches .33, .36 and .60 respectively;
these hubs are not rigid in the model predictions. Maximum adjacent body
rotation is 51, 58 and 137 degrees, across all clips including terminal/turn
actions. These angles alone do not prove jitter or unintended motion.

The candidate is REJECTED as a default: tiny/mixed scores do not justify a
change, and passing synthetic rigidity does not establish correct animation.
Do not add per-unit rescue angles or replace previously stronger candidates.

## Evidence And Next Boundary

Outputs under artifacts/homm3_mocap_v2/skin_mesh_pilot/<unit>:
rigid_turn_v2.json and body_relative_v2/report.json, per-clip NPZs/GIFs/sheets.
All outputs pin inputs and implementations. v1 predates added hub diagnostics;
root verified that every v1/v2 candidate world matrix is identical. v2 is the
current report. GIFs were posted for Ancient, Thunderbird and Ghost.

Reconstruction/audit are CPU; image comparison and surface scoring use CUDA
under the global lock. The 47.49 seconds total is cached comparison time only,
not onboarding, source capture, optimization, review or agent wall time.
Tests cover rigid turns plus translation, FK consistency, residual articulation,
combined rigid/articulated motion, input immutability, malformed/ill-conditioned
hubs, nonrigidity reporting and pair-distance metric controls. The previous
source-alignment/paired-bind diagnostic tests also pass.

Next: distinguish source trajectory information discarded by fixed-length
reconstruction from incorrect coordinate/rotation interpretation, using the
same cross-unit controls. Do not infer missing motion must be fixed by skin
optimization. Wolf Raider composite preparation and Boar Rider mesh provenance
remain separate outstanding breadth work; all 21 units remain in scope.
