# Thunderbird And Shahrokh Expansion

2026-09-06. Generated candidates only; no deployment or runtime change.
The fixed-mocap skin/shared-rest-mesh solver and previous candidates were
not changed. This is a breadth test, not another Roc tuning pass.

## Source And Anatomy

Both actual GLB meshes were rendered and inspected before preparation. The
wrong tree-spirit Thunderbird files were excluded. Named skin audits and
original-mesh sheets are under skin_mesh_pilot/h3_thunderbird and
skin_mesh_pilot/toa_shahrokh; processing outputs use thunderbird and shahrokh.
All paths in this document are under artifacts/homm3_mocap_v2 unless stated.

Both corpora contain 15 authentic groups and 92 frames. CTBIRD.dir and
lvl5alt.dir were read from the active Golden Era installation, with exact
known-idle foreground matching and native-idle SHA checks. Authored attack
startup/return and movement start/cycle/end context were retained. Both use
the same frozen Eagle#Eagle-Landing/y15 donor, with no alternate-donor fallback.

Thunderbird has 23 source joints; Shahrokh has 43. Their source-to-donor maps
are separate. Shahrokh's upper torso follows its actual wing attachment,
its outer and inner wing forks remain distinct, and its jaw has explicit
ownership rather than passing through the legacy beak classifier. Source
hierarchy/weight evidence informed preparation, not new per-clip authorship.

## Integration Findings

Thunderbird's initial fit stopped before optimization: the full Eagle leg
region contains 12 joints, exceeding the existing eight-candidate skin limit.
The new profiles distinguish four supported leg skin candidates from eight
toe helpers with no target ownership. All 50 mocap joints remain present.
Neither the donor skeleton nor the shared optimizer was modified.

Thunderbird mapped_skin_v1, registration_v1 and failed all_def_v1 remain
historical diagnostics. Its old freeze was archived as
shape_preserved/h3_thunderbird/preparation_frozen_mapped_skin_v1.json.
Current preparation is mapped_skin_v2 with registration_v2 and all_def_v2.
The source capture was reused unchanged. Shahrokh uses mapped_skin_v1,
registration_v1 and all_def_v1. A wrong-donor Shahrokh draft was rejected
before preparation; no output was generated from that draft.

Focused tests exercise actual donor loading, initialization, fitted bind,
rig validation and CPU WeightField support, rather than only checking names.
Shahrokh also checks complete actual limb/jaw subtrees and dominant-vertex
ownership. Independent review found no substantive P1/P2 mapping issue.

## Results

Thunderbird completed all 15 exports / 92 frames with serialized parity;
maximum vertex error is 8.00e-7. Rest and depth gates passed; idle appearance
and animated surface gates failed. Movement and attack sheets still show
insufficient wing opening. This is already present in the original-skin
column, so optimization alone does not explain the missing wingbeat.

Shahrokh also completed all 15 exports / 92 frames with serialized parity;
maximum vertex error is 6.29e-7. It passed rest and depth but failed idle
appearance and animated surface. Its movement/attack comparisons also lose
the full wing opening before skin optimization. These are baseline failures,
not accepted clips. Source electrical effects are not represented by the mesh.

All 30 exports reproduce generated motion across all 184 frames; this does
not prove correct source motion. Movement and attack GIFs for both birds were
posted. Verification passed 32 asset-profile tests and 21 capture tests,
including the two new actual bird-consumer tests. The inventory validator
passed all 21 configured units with current paths and fit identities. It is
a scope/path/identity check, not a visual-quality substitute.

## Timing Boundary

Thunderbird successful processing stages: preparation 16.61 s, capture
64.46 s, registration 2.97 s, fit/preview/export 104.36 s.
Shahrokh preparation 19.66 s, capture 61.22 s, registration 3.38 s,
fit/preview/export 110.81 s.
These are processing-stage times, not end-to-end onboarding time. Source
materialization, AI mapping, review, rejected drafts, the earlier failed
Thunderbird attempt, and orchestration add wall time and cost.

Next breadth work remains Ancient Behemoth's independent anatomy, Wolf
Raider's mounted profile and Boar Rider's unresolved editable mesh. The
21-unit inventory remains the scope authority; none is declared accepted
solely because processing or export parity passed.
