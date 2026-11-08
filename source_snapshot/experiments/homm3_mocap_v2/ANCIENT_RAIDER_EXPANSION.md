# Ancient Behemoth And Raider Expansion

2026-09-06. Generated evidence only. No shared motion solver changes, no
deployment, and no replacement of previously preferred candidates.

## Ancient Behemoth

The quarantined sibling-index draft was replaced with a source-specific
profile. See ANCIENT_BEHEMOTH_ANATOMY_AUDIT.md for hierarchy and preservation
evidence. Existing CABEHE captures were reused with their original manifest
hash, retaining all 15 groups and 84 frames. New preparation and registration
use mapped_skin_v1 and registration_v1; all_def_v1 completed all 15 clip exports.
Serialized playback parity passed on all 84 frames (maximum vertex error
3.99e-7). Rest shape and idle appearance passed; depth and animated-surface
gates failed. Attack motion is present but the overhead claw pose remains
underextended/misoriented. This baseline is not accepted. Movement and attack
GIFs were posted; the original and prepared bind sheets were inspected.

Successful preparation took 17.07 seconds; registration took 2.95 seconds.
Fit, previews and export took 110.50 seconds. The earlier complete capture
cost 63.70 seconds and was not repeated.
These are processing timings, not onboarding/review wall time.

## Wolf Raider Source Gate

Semantic identity is owned by mounted_asset_identity.py, not the filename:

- Raider: h3_wolf_raider_smartrigged.glb (named h3_wolf_rider_smartrigged.glb until 2026-09-27), SHA
  b15de4cfcd0ae93eebee224dae779ef9d8913f34cadfa86a65d86966a985916f;
  57 joints, 12,863 vertices, 15,122 triangles. All 57 joints have skin support.
- Actual mesh rendering confirms the helmeted rider on the dark wolf.
- Native source is Golden Era h3_wolf_raider/extracted_battle_source_12fps/
  CUWLFR.dir; idle SHA
  56d324f3e4949be62ac0b525e9f9a73052379ee36221a8286b92da2d468a6c13.

All 15 groups / 80 frames were materialized with the exact known-idle gate.
Root compared all 80 native paired images against Rider's CBWLFR.dir:
zero files are hash-identical and zero decoded RGBA images are identical.
Matching group counts do not justify reusing source-conditioned captures.
mounted_capture.py feeds the full source plate to BOTH actor donors, so both
actor captures require Raider provenance; mount captures are not exempt.
The Coyote and Mixamo donor packages and composition policy remain reusable,
not the old target anatomy, camera, offsets, weights or sprite captures.

Artifacts are under artifacts/homm3_mocap_v2/skin_mesh_pilot/wolf_raider:
corpus_v1/manifest.json, target_skin_audit_v1.json and source_mesh_sheet.png.
Both actors were newly captured from Raider plates using mounted_capture.py:
actors_v1/mount/corpus.json and actors_v1/rider/corpus.json. Each covers all
15 groups / 80 authored frames; total processing time was 88.38 seconds.
Root verified source/actor/capture hashes, finite positions, in-range source
indices and identical actor frame/reference timelines for all 30 actor clips.
These actor captures are not themselves a fitted Raider animation or visual proof.
Subsequent composite preparation and fitting completed; see
WOLF_RAIDER_EXPANSION_RESULTS.md. The generated candidate failed quality gates
and is not visually accepted.

## Verification

The 31 current asset-profile tests passed, including the rebuilt Ancient
Behemoth real-consumer test and review-driven head/neck assertions. No shared
solver behavior or older unit profile was changed by this iteration.
The inventory validator passed all 21 configured units with current paths.
