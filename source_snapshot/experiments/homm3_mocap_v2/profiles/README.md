# Structured Fitted-Skin Profiles

The registry adds data-authored units to the existing `get_profile` and
`prepare_mapped_skin_asset.py` route. It does not introduce another motion solver.
Existing Python profiles remain their current authority and are not inherited by
new units. The shared `mixamo-25-v1` recipe contains donor facts only.

Every usable entry must declare `status: authored`, the exact original mesh and
SHA-256, a source-selection rationale, and all fields in
`structured_profiles.ANATOMY_FIELDS`. `anatomySha256` is the canonical hash returned
by `structured_profiles.anatomy_hash`. Complete region and source-to-donor maps
are mandatory; undeclared bones cannot silently become torso weights.

`authored` means the anatomical recipe has been supplied, not that its visual
quality is accepted. Generated preparation remains an unreviewed candidate until
separately inspected. Loading verifies mesh and anatomy hashes and current source
bone coverage. The mocap delivery validator repeats the registered-profile gate
before lab import, bundle builds and deployment. Each registered unit's explicit
selection row must pin `structuredProfileSha256` from its prepared profile.
Changing an authored profile cannot silently validate an older selected artifact;
the selection must be regenerated with the matching preparation provenance.

Corpus context includes only native-present movement start/cycle/end groups.
Absent start/end groups are recorded explicitly, never synthesized. This lets
units whose original DEF lacks those groups use the same corpus pipeline without
inventing transitions. Focused provenance and native-presence tests passed;
fresh registered-unit capture and delivery are separate proof stages.

Registered-unit preparation freeze/report, prepared sprite manifest, captured
corpus, registration report and fitted report all carry that same top-level pin.
Consumers reject missing or different pins before work; producers verify that
the selected profile did not change before publishing their report. Preparation
uses the pin from the exact loaded recipe, not a later independent profile read.
Existing artifacts without this registered-unit pin must be regenerated; the
existing preparation validation command cannot add a missing registered pin.
Selection validation also checks the hash-pinned fitted report's profile pin.

Pikeman explicitly selects the original 65-joint source. Its initial anatomical
mapping was inspected from six CPU bind views and source hierarchy; later true
textured views exposed incorrect collar/grip interpretation and incomplete pike
surface ownership. The following preparation records are historical candidates,
not acceptance of that original anatomical mapping. Source +Y is
up, +Z forward, and anatomical left/right are +X/-X relative to the torso. The
missing right collarbone uses the existing relative helper; shoulder, elbow and
wrist are paired directly to observed source joints rather than shifted along a
donor-proportioned chain. The original bridgefix and rigidized meshes remain
unchanged and are not implicit substitutes.

Current Pikeman preparation is `shape_preserved/h3_pikeman/preparation/authored_mapped_v4`.
The reviewed `ownership/h3_pikeman_v2.json` owns the 921-face physical pike and
explicitly initializes 70 misowned waist-plate vertices to Hips. It preserves all
10,054 source faces/corners and albedo, adding only 53 shared boundary copies
(8,246 prepared vertices). Physical ankle/toe pivots are authored in source mesh
space. Preparation and exact source replay passed in 16.88 seconds. Earlier
preparations and their freezes remain historical diagnostics, not current inputs.

The current full corpus under `skin_mesh_pilot/pikeman` captures all 13 native
groups and 80 target frames. `all_def_v2` fitted in 52.36 seconds: rest shape and
idle appearance pass, but attachment, explicit boundary, clipping and animated
surface checks fail. The source thrust lowers the pike while captured wrist
orientation leaves it too upright; the upper grip separates by up to 0.764 source
units. No GLBs were exported. Source-guided held-part orientation and two-hand
contact remain unfinished; Pikeman lighting and runtime behavior are unproven.
True original-material and prepared-bind evidence is under
`artifacts/homm3_mocap_v2/pikeman_original_blender_v1/`. Earlier triangle-colour
annotations are diagnostic, not texture or anatomical acceptance proof.

The registry, draft refusal, exact-coverage checks and build/deploy hook passed
the focused profile/target suite. Draft refusal uses explicit draft fixtures;
the real authored Pikeman registry entry is validated separately. All 20 selected Stronghold source skeletons were separately
read back and had complete region assignments before the coverage check changed.
The unit tests do not establish runtime or visual quality.

## Physical Geometry Ownership

An optional top-level `geometryOwnership: {path, sha256}` pins an authored JSON
sidecar with schema `homm3-source-geometry-ownership-v1`. It declares the original
mesh SHA, exact decoded vertex/face counts, disjoint rigid face masks with exact
attachment owners, and body vertex-region masks that exactly partition vertices
referenced by complement faces. Face IDs use the original `target_asset` decoder
order, not an assumed Blender polygon order. Bone weights can seed authoring
diagnostics but are not physical prop truth. Draft masks cannot prepare:
`authorship.status` must be `reviewed_source_geometry` after source-surface review.
Every rigid part explicitly chooses `interfaceMode`: `split_shared` requires
shared source vertices, while `source_detached` requires none. Both are verified
against the original mask and its complement, before any sequential splitting.

Preparation reuses `attachment_repair.split_attachment` to duplicate shared
boundary vertices, never delete/cap faces or move rest corners. Composed source
vertex IDs and every split boundary pair are saved with the skin. Exact original
face order/count, mapped triangle indices, position corners and UV corners are
checked. Only explicit physical prop vertices receive one-hot owner weights
without requiring original donor support; body zero-support remains an error.
Frozen preparation load replays from the original GLB and compares all ownership
arrays and initial weights rather than trusting report flags.
Pair validation checks uniqueness, shape, range, complete duplicate coverage and
exact source correspondence, including every part's original shared vertices.
Already-detached props report boundary checks as not applicable, never as proven
contact or closure. Separate attachment and contact acceptance remain necessary.

Where original source weights misassign a reviewed body surface, the sidecar may
declare `bodyWeightOverrides` rows with `sourceVertexId`, normalized donor
`weights`, and a nonempty authored `rationale`. Each source ID must belong to one
explicit body region, and its donors must be allowed by that region. Initialization
uses the composed source-vertex mapping and applies the override exactly once to
the body copy, never to rigid prop copies sharing the same source ID. Invalid or
unused overrides fail; unsupported body vertices without an authored override
still fail. This is explicit weight authorship, not nearest-bone recovery.

Each sidecar supplies `maxBoundaryGap` in `source_mesh_units`, plus pinned camera
evidence converting a provisional limit of at most one rendered pixel. Camera
hash, positive `pxPerWorld`, and the exact conversion are checked. The complete
expected corpus frame count and all replayed boundary pairs are evaluated before
fit export. Missing/nonfinite/subset animation cannot pass. This tolerance remains
`provisional_unaccepted`; geometric mask review is not animated contact acceptance.
The build selection gate requires the matching hash-pinned fit report to contain
passing ownership-boundary and export gates. The delivery gate additionally replays
final GLB keys and midpoint samples against the source-replayed preparation; this
does not establish continuous animation or runtime acceptance. Focused synthetic tests validate the shared implementation;
no real ownership sidecar is accepted merely by those tests.

## Authored Joint Positions

The shared bind fitter also accepts `authored_positions`: explicit donor names
and `[N,3]` positions in `target_mesh_space`, pinned to `sourceMeshSha256` with
nonempty authored evidence. Values must be finite and inside original source
bounds; no clamp or later helper overwrite is allowed, and existing degeneracy
checks remain active. Six focused tests passed. This supplies anatomical data to
the existing solver, not another motion engine or proof of fitted visual quality.

## Crusader Physical Candidate

`h3_crusader.json` explicitly selects the original source mesh and authored
anatomical sites, with physical sword ownership on RightHand and shield ownership
on LeftHand. The previous built-in profile remains unselected history. Source
views and the fresh `authored_physical_v1` bind were reviewed for preparation,
not animation acceptance. Preparation took 16.55 seconds and preserved all 6,911
source triangles, their order, corner positions and UVs; 85 interface duplicates
produce 8,837 prepared vertices from 8,752 source vertices.

The first `all_def_physical_v1` fit is rejected, with no GLB exports. Its sword
split gap is 0.002549 source units, but shield gap reaches 0.647965 against the
provisional 0.010246 limit. Diagnostic source vertex 7254 is physical left thigh,
correctly weighted to LeftUpLeg; shield face 5483 includes it incorrectly.
This profile/ownership version is preserved as reproducible preparation and
rejected-fit evidence, not approved physical contact or delivery readiness.
True-camera closeups and the failed defence frame are under
`artifacts/crusader_original_blender_v1/shield_boundary_diagnosis_v1/`.

The current ownership v2 replaces the rejected shield selection with the reviewed
624-face `visible_shield_candidate_v5`. Source-authoritative double-sided CPU
visibility buffers provide polygon witnesses; separately authored shell/rim
surface rows record exact face IDs, original positions/UVs and explicit reasons.
No hidden-centroid or weight-based selection is used. Blender diagnostic colors
are camera-ray-only: original materials remain on indirect/shadow rays so colored
light bounce cannot masquerade as selected body geometry.

Fresh `authored_physical_v2` preparation passed in 15.97 seconds, with 8,825
vertices, 73 complete boundary pairs and all 6,911 source faces/corners/UVs
preserved. The 103 existing chest overrides are unchanged; unsupported body donor
support remains fail-closed. New source/capture/registration artifacts use the
current profile pin. The first v2 fit hit its 120-second stage budget before final
refit, an infrastructure/time-budget failure rather than quality evidence.
Animation export and delivery acceptance remain unproven until a completed fit
and the subsequent gates pass.
