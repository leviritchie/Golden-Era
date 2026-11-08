# Cyclops Expansion Results

2026-09-06. All-group generated candidates, not accepted or installed. Shared
motion, camera-registration, skin, and mesh solvers were unchanged for this run.

## Inputs and preparation

The actual Cyclops GLB has 44 joints, 11,890 vertices and 9,186 triangles.
Mesh SHA-256: b1d7b588c78833e4f6d1687d93075d5aa69d81feb7c25e9c6ba669ed06544248.
The dedicated profile explicitly maps every source joint to the established
25-joint capture graph. Root independently inspected joint coordinates and the
multiangle generated bind sheet; a review agent checked the final preparation.
Rig, unchanged visible mesh, and serialized bind identity gates pass.

The rock is preserved within the skin, not independently releasable. No rigid
weapon region or projectile-release contract is claimed. The Spine2 hub remains
at Bone_003 for this baseline, with Bone_002 also owned by Spine2; this is not a
claim of a one-to-one match between all source and fitted chest pivots.

Golden Era CCYCLR.dir supplies 18 groups and 125 authentic frames. Idle has six
frames. Source preparation passed the existing known-idle pixel check, and
capture hashes, authored indices, counts, and finite predicted positions were
independently checked after capture. No source groups were dropped.

## Results

Artifacts: artifacts/homm3_mocap_v2/skin_mesh_pilot/cyclops/.
Preparation: shape_preserved/h3_cyclops/preparation/mapped_skin_v1 under the same
artifacts/homm3_mocap_v2 root.

- Capture including encoding/model load: 93.58 seconds.
- Owned preparation: 20.99 seconds; idle registration: 3.27 seconds.
- Original constrained fit, previews, and exports: 118.50 seconds.
- Continuous-weight fit and previews: 53.92 seconds, including 36.68 seconds
  fitting/validation/write.

These stage timings exclude source preparation, startup outside stage timers,
authoring, review, orchestration, and investigation; they are not total onboarding
time or model-cost measurements.

All 18 original-fit GLBs pass parity for all 125 frames, max vertex error 5.24e-7.
Rest shape, idle appearance, and depth gates pass; animated surface fails.
Registration selected yaw 155 degrees, pitch 20 degrees. The rendered facing
still disagrees with the source and must not be called visually validated.

The separate continuous-weight trial uses the same .015 topology prior, 200
steps, and 120-second fit budget as Orc/Ogre/Goblin. It retains fixed captured
motion, camera, bind, and original geometry. Surface objective improves from
2.412 to 1.201; image objective from .586 to .566. Of 94 observable region-centroid
trajectories, 29 remain below the soft 90% motion floor. Final maximum triangle
stretch: move 2.67, idle 1.23, front melee 5.88, front throw 8.06, death 7.51.
NPZ skin and GIFs are generated; no continuous-fit GLB parity is claimed.

The throw has a recognizable overhead wind-up, but wrong facing and no rock
release. Death remains distorted and misses the source's final pose. This is a
completed expansion test, not satisfactory animation.

## Generalization evidence and next work

Orc, Ogre, and Cyclops now form a broader untouched baseline cohort. Do not tune
individual clips to conceal these failures. Shared motion/camera defects should
be isolated and evaluated against the cohort and previous stronger units.

diagnose_retarget_source_frame.py supplies an independent CPU fixture with
actual articulated motion, not just translated rest poses. Rotating source
positions, reference, and offsets together while holding the fitted target fixed
changes current target positions by .173659 and local matrix entries by .346652.
The target's actual animation displacement is .359606. The comparison is direct
in the fixed target frame, without an erroneous output back-rotation. This
establishes source-frame sensitivity, not the cause of any particular clip.
The diagnostic is not a quality gate and has not changed production behavior.

A read-only sibling audit found no exact target-topology reuse for Orc Chieftain,
Ogre Mage, or Cyclops King: parent-by-name relationships differ for 32 Orc-family
joints and 13 common Cyclops-family joints; Ogre Mage uses a different 24-joint
semantic graph. Reuse the capture package where justified, not target indices.

32 focused CPU tests pass; the final profile/preparation review found no P1/P2
mapping issue. The 21-unit inventory validator remains the scope check. Existing
preparation/fitting/export gates are unchanged. No deployment/runtime proof.
