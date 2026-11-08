# Trapper, Brute, And Ghost Expansion

2026-09-06. Generated candidates only; no runtime or installation change.
The fixed-mocap, constrained-skin and shared-rest-mesh solver was not tuned
for these units. Previous stronger candidates remain untouched.

## Coverage And Time

Paths are under artifacts/homm3_mocap_v2/skin_mesh_pilot/<unit>:
corpus_v1, captures_v1, registration_v1, all_def_v1. All available authentic
DEF groups and startup/return frames were retained; no RIFE frames were added.

| Unit | Native source | Groups / frames | Prepare | Capture | Register | Fit / preview / export |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| Goblin Trapper | lvl1alt.dir | 16 / 98 | 16.90 s | 73.56 s | 2.83 s | 100.89 s |
| Ogre Brute | lvl4alt.dir | 18 / 109 | 16.95 s | 63.47 s | 2.73 s | 110.56 s |
| Ghost Behemoth | lvl7alt.dir | 15 / 84 | 16.47 s | 56.60 s | 2.81 s | 90.98 s |

These are measured processing-stage times, not onboarding wall time. Source
materialization, AI authoring, mapping corrections, review and orchestration
are additional. Counts come from actual materialized/captured frames, not an
agent's recollection of a sibling's metadata. Current Golden Era sources pass
the normalized known-idle pixel gate and candidate-owned native-idle hash gate.
Older NN metadata paths were not treated as current source provenance.

## Visual Results

All 49 GLBs pass serialized animation parity over all 291 frames. Maximum
vertex differences are 3.90e-7 (Trapper), 4.27e-7 (Brute), 5.30e-7 (Ghost).
This proves reproduction of generated motion, not correct motion.

| Unit | Passed quality gates | Failed quality gates | Observed limitation |
| --- | --- | --- | --- |
| Goblin Trapper | rest, depth | idle appearance, animated surface | weapon raise/extension stays too close to chest |
| Ogre Brute | rest | idle appearance, depth, animated surface | club/arm distortion and incomplete swing |
| Ghost Behemoth | rest, idle appearance | depth, animated surface | overhead claw raise is absent |

Attack comparison GIFs were posted for all three. Ghost's original bind sheet
was also inspected. No candidate is accepted. Motion missing in the original-
skin column establishes that skin optimization alone cannot explain the gap;
it does not yet isolate capture, motion transfer, or preparation as the cause.

## Structured Mesh Evidence

audit_target_skin.py emits profile-independent named parents, joint positions,
per-joint skin mass, ownership counts and weighted centroids. Influence slots
are scattered through vertex_joints using the existing dense_weights loader;
slots are NOT joint columns. Actual v3 reports show:

| Unit | Joints | Weighted joints | Influence slots | Vertices / triangles |
| --- | ---: | ---: | ---: | --- |
| Goblin Trapper | 79 | 78 | 16 | 8477 / 9957 |
| Ogre Brute | 67 | 66 | 16 | 9053 / 9816 |
| Ghost Behemoth | 49 | 47 | 8 | 7398 / 9265 |

An initial agent claimed Ghost had only eight weighted bones by reading the
eight influence slots as bones. That claim is false. The v3 machine report is
authoritative. Centroids/bounds are explicitly mesh-local; restWorld is glTF
node-world. Do not compare those spaces without verifying the node transform.
Reports pin mesh, audit, decoder and dense-weight implementation hashes.
No report assigns anatomical roles automatically. Earlier v1/v2 reports remain
historical diagnostics; v3 includes final validation and coordinate labeling.

## Profile Review

New profiles map each source joint explicitly. Before preparation, root review
corrected Trapper's reversed leg sides and head tip selection, and Ghost's
overbroad hips mapping and ankle-pair sites. Ogre Brute uses wrists Bone_024
and Bone_019; the elevated Bone_018 endpoint is not a wrist. No independent
weapon release/rigid attachment was invented. Actual subtree regression tests
prevent cross-limb region copying, and actual consumers check fitted rigs,
normalized mapped weights, and unchanged rest vertices. These are preparation
gates, not human acceptance of animation.

Verification: 30 profile tests, 21 capture tests, three real-consumer/subtree
tests and four audit tests passed; the 21-unit inventory validator passes.
Independent review found raw-index and coordinate-labeling issues in the new
diagnostic; both were fixed, along with malformed parent/triangle rejection,
before producing final v3 reports.

## Remaining Breadth

Current import records map Thunderbird and Shahrokh to h3_thunderbird and
toa_shahrokh, and corresponding GLB files exist. Their source idle sprites
are not proof of those GLBs' appearance; actual mesh renders are still needed.
Wrong-tree Thunderbird files remain excluded. Boar Rider has native cboar
source and a binary bundle, but no verified editable source GLB was located.
Do not substitute a Wolf Rider mesh. Ancient Behemoth remains quarantined
pending its independent anatomy rebuild; Wolf Raider retains the explicit
filename-swap identity. All 21 units remain in scope.
