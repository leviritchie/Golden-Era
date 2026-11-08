# Upgrade Expansion Results

2026-09-06. Generated candidates only, not accepted, installed or runtime-proven.
Shared motion, camera, skin and mesh solvers remain unchanged. Each new asset
uses its own inspected target skeleton and the established 25-joint capture
donor. No sibling target indices were reused blindly.

## Preparation Evidence

Profiles: asset_profile_orc_chieftain.py, asset_profile_ogre_mage.py,
asset_profile_cyclops_king.py. All three actual preparation CLI runs passed rig,
unchanged visible mesh, UV, texture and serialized own-bind identity gates.

Orc Chieftain has 66 joints / 8,307 vertices / 9,736 triangles. Current
preparation is mapped_skin_v2. A v1 preparation was rejected for cross-hand
finger ownership; its freeze was renamed preparation_frozen_rejected_v1.json.
The corrected arm regions match complete shoulder descendant subtrees. Wrist
sites are Bone_030 and Bone_025, not distal hand or weapon-facing endpoints.
Duplicated short leg branches are assigned to the same sides as the full legs.

Cyclops King has 45 source joints; wrist sites are Bone_021 and Bone_026.
Bone_025 extends toward the rock center and is not a wrist site. The rock is
still skinned geometry, not an independently released projectile.

Ogre Mage has 24 semantic source joints / 7,332 vertices. Its spine hierarchy
is Hips -> Spine02 -> Spine01 -> Spine, opposite the numerical naming intuition.
Donor toe-end helpers do not imply target toe-end bones. No isolated rigid
club ownership is claimed. Both Mage and King use mapped_skin_v1.

Root inspection corrected multiple draft mappings before fitting. Label and
coverage tests alone were insufficient: test_upgrade_preparation.py now runs
actual bind fitting, rig gate, source-weight initialization, weight gate and
rest reconstruction for all three assets. This is a CPU preparation check,
not proof of visible animation quality.

## Source Identity Correction

Historical Ogre Mage source under the active Golden Era lab is COGRE.dir.
Its authoring.json also points to COGRE. All 85 native frame hashes, grouped by
group and frame index, exactly match base Ogre. The old known-idle images also
have identical SHA-256 61dff34a275e539e047bd4dc909b4825added160c0403751ca16da90955e2fe3.

The original local HoMM 3 Complete/Data/H3sprite.lod contains COGMAG.def. It was
extracted through tools/lod_extract_entry_py3.py and tools/defextract_py3.py to
skin_mesh_pilot/ogre_mage/source_identity_v1 under artifacts/homm3_mocap_v2.
Extracted DEF SHA-256:
8196a8e264e8bd7b277aa015d9a7f6cb6bb17961cc78b9c06fe73b02e6fc883e.
Native idle SHA-256:
20130e77d0435188ac99bf5dd458ce0ea22538b69a04973e91badc2085a0b42b.
The original native idle was visually inspected and differs from Ogre.

Existing ensure_def_nn_upscale_meta generated a new all-frame union canvas.
Existing nn_upscale_native_frame generated verified_idle_nn.png directly from
that inspected native idle. No old Ogre canvas or idle was reused. The corrected
corpus has 18 groups / 109 authentic frames including all action transitions.
The 85-frame corpus_v1 remains a rejected provenance witness, not Mage input.
Nothing in the installed lab, import table or runtime bundle was modified.

The existing Mage mesh visually resembles the old Ogre source more closely
than the corrected Mage sprite. Motion fitting must not be described as proof
that this mesh now has the correct Mage appearance.

## Source Guard

capture_candidates.json now pins native idle identity for these three assets.
capture_skin_corpus.py checks those optional candidate-owned pins before output
creation, package load or GPU work. It separately verifies native and prepared
hashes and that the prepared provenance row is the manifest idle. There is no
manifest override or alternate source. Older entries without pins retain their
existing validation; this is not a claim that all historical sources are audited.

The native idle hash is the executable identity gate. defName is a descriptive
provenance label, not an independently verified archive identity. It does not
claim to authenticate every frame of an archive. Normal corpus hashes and frame
indices remain separate checks. The real corrected Mage manifest passes; its
historical duplicate fails in the focused tests.

## First-Pass Results

Paths below are under artifacts/homm3_mocap_v2/skin_mesh_pilot/<unit>.

| Unit | Capture | Fit / preview / export | Groups / frames | Export parity | Quality failures |
| --- | --- | --- | --- | --- | --- |
| Orc Chieftain | captures_v2, 169.27 s | all_def_v1, 118.59 s | 18 / 106 | all, max 4.88e-7 | idle, depth, animated surface |
| Cyclops King | captures_v1, 85.27 s | all_def_v1, 135.96 s | 21 / 161 | all, max 3.84e-7 | idle, animated surface |
| Ogre Mage | captures_corrected_v1, 68.24 s | all_def_corrected_v1, 97.90 s | 18 / 109 | all, max 4.98e-7 | idle, animated surface |

Chieftain still has wrong facing and weak attack reach. King is more front-facing
than the base Cyclops candidate, but arms and rock distort, and the rock cannot
release. Correct-source Ogre Mage still loses weapon swing and differs in
appearance from the source. These runs expand failure evidence; none is
satisfactory animation. Total coverage is 57 groups / 376 authentic frames.

Current successful preparation times were 22.41 s (Chieftain), 17.50 s (King),
18.58 s (Mage). Idle registration took 4.65 s, 3.07 s and 2.37 s respectively.
These exclude previous failed preparation attempts and authoring corrections.

Validation: 20 profile tests, 21 capture tests (including seven identity tests),
and one live three-asset preparation-consumer test pass. The inventory validator
still covers all 21 configured units. All 57 generated clip exports pass parity
over all 376 source frames. An independent review found no remaining mapping or
fallback defect; the descriptive defName limitation is explicitly documented
above. These gates do not override the failed visual-quality checks.

Orc Chieftain captures_v1 exited with code 1 and no recorded traceback before
inference completed. The process was verified absent before captures_v2 began.
The incomplete output was retained and not reused. Timings in the table exclude
that failed attempt, source preparation, agent authoring, corrections, review,
tool delays and orchestration; they are not end-to-end onboarding timings.

The expanded cohort supports addressing motion correspondence and held-object
ownership across multiple units, not further unit-specific weight tuning. Keep
all 21 configured units in scope and preserve stronger previous candidates.
