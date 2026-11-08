# Rigid Weapon Skin Pilot

Status: generated candidate, visually rejected for action fidelity. No source
replacement, deployment, or runtime claim.

## Ogre Ownership Finding

The Ogre profile already declares `weapon -> mixamorig:RightHand`, and the
optimizer correctly freezes that region's weights and rest vertices. Numeric
inspection shows 236 vertices unchanged at exact one-hot ownership. However,
front/side diagnostic renders in `rigid_weapon_audit/h3_ogre` show that this
region covers only the club tip, not its full shaft. A named semantic region
is not proof of complete object coverage. Do not change the optimizer to fix
this incomplete region assignment.

`annotations/ogre_club_proposal.json` pins the unchanged prepared mesh and two
AI-reviewed bind-view polygons. An explicit ordered RGB criterion distinguishes
brown wood from green skin inside those regions. The existing spread/mean
criterion remains unchanged for old annotations; both vertex and interior-face
classifiers now use the same color function. Prop labels are not hardcoded to
rock. This is authored mask evidence, not automatic semantic recognition.

The face proposal selected 668 triangles versus 517 with vertex-only sampling.
The front/side/top comparison is under `rigid_prop_face_samples/h3_ogre/v1`.
It visibly covers much more of the shaft while excluding most of the hand.
Unseen contact coverage remains unproven.

## Actual Shared-Topology Candidate

`replay_rigid_prop_faces.py --ownership skin-vertices` derives one-hot weights
for the union of selected-face vertices. It writes a separate NPZ candidate,
uses the existing shared topology, and preserves fitted rest vertices and
fixed mocap. This is distinct from the diagnostic split-corner mode. Connected
neighboring triangles can change; the invariant is exact parity of vertices
outside the declared union, not all nonselected faces. Visibility is explicitly
incompatible with this mode because no detachable mesh contract exists.

Final artifacts: `rigid_weapon_skin/h3_ogre/v2` under the mocap artifact root.

- 662 declared rigid vertices; 452 weight rows actually changed.
- All remaining weight rows and all fitted rest vertices exactly unchanged.
- All 15 clips replayed; outside-union vertex motion error exactly zero.
- Maximum selected-triangle edge error: 2.76e-7 model units.
- Actual full-skin neutral identity error: 2.39e-7 model units.
- Cached replay/render time: 7.59 seconds, excluding capture/preparation/work.
- Sixteen focused prop tests passed; serialized candidate independently read
  back and checked against the pinned fitted base and mask.

Visual result: ownership is more complete, but the club/arm direction remains
wrong in the attack. Full-canvas mean RGB change for attack-up is only 0.000304;
that is not a quality score. Do not promote the candidate as an animation fix.
The test rules out incomplete club ownership as a sufficient explanation for
the action failure. Next motion work must distinguish wrist orientation and
arm trajectory, while respecting the still-fixed body-mocap constraint.

## Terminal Rotation Evidence

The active `capture_positions_v1` loader uses `reconstruct_adapted`, then
`direction_retarget.reconstruct_frame_locals`. A terminal hand has no child
direction, so its local rotation retains the rest/minimum-change prior. Its
world orientation changes with ancestors, not from observed wrist articulation.

All 15 Ogre raw captures were checked through the current validated
`native_donor_rotation_replay._rotations` decoder, with each corpus capture hash
and authored `sourceIndices` verified. Both hand channels have exactly zero
frame-to-frame matrix change in every clip; maximum matrix deviation from
identity is approximately 1.0472e-7. This is not merely a loader discarding
nonzero hand rotation: the raw channels themselves contain no changing signal.
Historical `isSo3:false` report fields use an obsolete diagnostic and were not
used as rotation evidence in this check.

The idle-reference capture hash resolves to `captures_v1/g02_idle/capture/`
`raw_capture.npz` (be9913790c31552ba437925e36ed8e2933e64b67d1a5c2b825f3e162b49fefdc).
Attack-up raw hash is
6c946b5ff8d9bd4a634d210921c3a371dfae417ddd6791a978addddaaf4ae7f6.

No native rotation substitution was performed. A subsequently user-authorized,
isolated authored wrist trial is documented in `SOURCE_WRIST_ORIENTATION_TRIAL.md`.
It adds information absent from this fixed motion interface and is explicitly
not recovered raw mocap or a skin-only fix. It is not a production default.

The independent cross-unit report `terminal_rotation_audit/v1/report.json`
extends this check to 114 clips across Hobgoblin, Behemoth, Orc, Orc Berserker,
Ogre Brute, Ancient Behemoth, and Ghost Behemoth. Every audited hand has zero
children and zero decoded frame-to-frame local rotation change. Capture hashes
and authored indices are recorded per clip. Orc Chieftain was not covered by
that report because the requested v1 corpus is absent; its active v2 is a
separate unperformed check, not an inferred result.

Positive-feedback controls share this limitation. Therefore constant terminal
rotation is not by itself proof that a clip looks bad; it establishes missing
degrees of observation, whose visual impact depends on the action and prop.
Do not claim every remaining Stronghold defect has this one cause.
