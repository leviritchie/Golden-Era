# Expansion Cohort

2026-09-06 user-directed evaluation phase. Orc, Ogre, and Cyclops all-group candidates
are now generated, but not accepted. This is an evaluation protocol, not a
delivery contract or a declaration that the current quality gates pass.

## Scope

Pause further Goblin-specific motion correction and speculative retarget
changes. Expand the current fixed-mocap, silhouette/chroma-guided skin and
shared-rest-mesh fitting approach to Orc and Ogre, followed by Cyclops. Their
different proportions and ranged/melee actions provide broader evidence than
another refinement on the same small group of units.

Keep existing candidates unchanged as regression references. The continuous
weight fit is a separately labelled candidate, not a replacement silently
applied to old results. Do not transfer the Goblin's authored weapon directions
to another unit.

## Evaluation

Prepare every available authentic DEF frame with the existing transition
policy, including action startup and return frames. Per-unit source identity,
anatomy mapping, rigid attachments, owned bind/skin preparation, and camera
registration remain explicit preparation inputs. Do not infer these from a
similar filename or copy a sibling's bone indices without inspecting its rig.

Run the existing pipeline with recorded settings before changing the solver.
Show source-versus-mesh GIFs for idle, movement, representative melee/ranged
attacks where present, and death. Keep all groups in fitting and reporting;
the displayed subset is not permission to discard difficult animations.

Record preparation/authoring effort separately from capture, fitting, preview,
and export compute. Report first-pass quality and any required unit-specific
intervention. The under-ten-minute-per-clip target is not satisfied by quoting
only a cached fitting duration.

Only propose a shared solver change after identifying the same failure across
independent units, or proving an implementation defect with an isolated test.
Test such a change against both the new cohort and retained previous results.
Failed gates stay visible; no automatic recovery or relaxed thresholds.

## Identity and Proof

Source preparation completed using the existing reader and idle-pixel gate:

- Orc: 18 groups, 103 authentic frames; skin_mesh_pilot/orc/corpus_v1.
- Ogre: 15 groups, 85 authentic frames; skin_mesh_pilot/ogre/corpus_v1.

Both paths are under artifacts/homm3_mocap_v2. Their manifests point to the
active Golden Era extraction and retain every group. The corpus_v1 directories
contain prepared source images. Subsequent captures_v1, registration_v1,
all_def_v1, topology_skin_v1, and continuous_fit_v1 directories record separate
stages. See ORC_OGRE_EXPANSION_RESULTS.md and CYCLOPS_EXPANSION_RESULTS.md for
completed first-pass evidence and limitations. ALIGNED_MOTION_TRIAL.md records
the subsequent four-unit controlled diagnostic: source-frame normalization was
rejected for promotion, and existing pipeline defaults remain unchanged.
UPGRADE_EXPANSION_RESULTS.md records the next three-unit first pass, including
the corrected Ogre Mage source identity and all 57 generated clip comparisons.
Those candidates also remain unaccepted; normal capture now checks explicit
native-idle identity pins for the three newly onboarded assets.
ALTERNATE_EXPANSION_RESULTS.md records another three complete capture corpora,
40 new fitted/exported clips, the shared full-canvas registration correction,
and Ancient Behemoth's pre-preparation anatomy quarantine. PAIRED_BIND_TRIAL.md
records the unpromoted paired-site diagnostic; it does not replace the baseline.
TRAPPER_BRUTE_GHOST_RESULTS.md records 49 further baseline clips, their failed
quality gates, and machine-readable named skin audits used to correct onboarding
errors before preparation. No unit-specific solver tuning was added.
BIRD_EXPANSION_RESULTS.md records the Thunderbird and Shahrokh breadth pass,
including bird donor support constraints and independent forked-wing mapping.
ANCIENT_RAIDER_EXPANSION.md records the rebuilt Ancient Behemoth baseline and
the separate source-provenance gate for semantic Wolf Raider.
BODY_RELATIVE_MOTION_TRIAL.md records a proven synthetic rigid-turn defect
and its unpromoted three-unit candidate; no production solver was changed.
WOLF_RAIDER_EXPANSION_RESULTS.md records the completed mounted baseline and
the rejected Boar-labeled wolf placeholder. CAPTURE_STAGE_AND_LOCAL_ROTATION_TRIAL.md
separates capture reconstruction losses and records another rejected cross-unit
motion candidate, without changing production motion.
COINCIDENT_BIND_TRIAL.md records the bird-cohort coincident-joint/skin-owner
correction: weighted rigid controls pass, real wingbeat comparisons still fail
to justify promotion. No production rig or motion policy changed.
SOURCE_REFERENCE_BIND_TRIAL.md records the subsequent explicit source-skeleton
similarity bind and skin/mesh optimization trial, without replacing preparation.
GLOBAL_ALIGNMENT_TRIAL.md tests one image-scored shared motion-frame correction
with withheld frames. Aggregate overlap improves, but visual quality and
cross-unit heldout behavior do not justify promotion.
REGION_CLIPPING_TRIAL.md isolates source-weight region clipping with identical
motion and bind. Removing it reduces extreme local strain but worsens broader
deformation metrics and does not restore wing opening; no promotion.
ANATOMICAL_DIRECTION_GAUGE.md records a coordinate-dependence counterexample
in single-edge transfer and the isolated explicit-plane primitive milestone.
ANATOMICAL_CAPTURE_TRIAL.md records the subsequent full-hierarchy comparison:
graph-derived anatomical planes change articulation but do not produce
satisfactory bird movement or attacks. Production defaults remain unchanged.
JOINT_AXIS_CALIBRATION_TRIAL.md records image-scored shared non-root axis
calibration with two entire attack clips withheld. Training fit improves, but
heldout attacks do not beat the current prepared results; no promotion.

Wolf Rider uses h3_wolf_rider_smartrigged.glb (sha 2fb1bb07); Wolf Raider uses
h3_wolf_raider_smartrigged.glb (sha b15de4cf) (2026-09-27: the two files were renamed so each basename now names its own unit; pre-swap bytes and note in `artifacts/meshy_downloads/_superseded_do_not_use/wolf_identity_swap_20260927.note.json`.) The hash-pinned mapping remains owned by
mounted_asset_identity.py. Historical wrong-pairing results are diagnostic only.

Positive user feedback motivates expansion, but is not blanket acceptance of
every clip. Source preparation, generated candidates, exported parity, visual
acceptance, and installed/runtime behavior remain separate evidence levels.
