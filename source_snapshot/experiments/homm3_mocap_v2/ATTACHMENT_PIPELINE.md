# Shared Attachment Pipeline

## Scope

This is the integration point for the twelve-faction rollout, not an Ogre
repair script. Unit anatomy, rigid regions, donor joints, source landmarks, and
asset/source hashes are data. The shared numerical stages must not branch on a
unit or faction name. Existing unit profiles remain the anatomy registry.

The implementation integrates orientation completion, attachment validation,
motion-equivalent body ownership repair, semantic boundary splitting, and
optional sample/graph mask refinement into the existing skin/mesh pipeline.
It does **not** yet reconstruct missing attachment surfaces or establish
readiness for twelve factions.

## Current Stages

1. Load the frozen preparation, source corpus, and captured motion unchanged.
2. Apply source orientation completion only with an explicit
   `--motion-completion-report`. Validate its input hashes and exact baseline,
   preserve every joint position and non-owner rotation, and retain all clips
   outside its declared scope. Current completion supports a non-root leaf
   owner; it is not a universal articulated-wing or mounted-body solver.
3. Run the existing shared skin and bounded rest-mesh fit across the corpus.
   No separate Ogre fitting implementation was added.
4. With an explicit `--attachment-repair-recipe`, suppress pre-repair GLBs and
   dispatch the shared post-fit repair after releasing the GPU batch lock.
   Keep the fit report immutable and write a separate `pipeline_result.json`.
   An existing fit can enter this same stage through `run_attachment_repair.py`.
5. Evaluate every profile-declared rigid attachment before GLB export. Measure
   rigid shape residual and the surrounding mixed-influence surface, per frame.
   A rigid club with stretched connecting faces must fail, even when the
   whole-mesh percentile looks acceptable. When a profile pins
   `geometryOwnership`, the export interface is the authored split seam
   (`physical_boundary`): mixed donor influence elsewhere on the body remains a
   diagnostic and does not gate GLB export. The shared fitter also freezes
   ownership-pair vertices and every vertex of faces incident to those pairs.
6. Refuse diagnostic GLB export if the rest or attachment contract fails. Keep
   comparison GIFs and failure evidence available. Existing additional depth,
   idle, and animated-surface gates still determine the final quality result;
   diagnostic GLB existence is not acceptance or delivery proof.

Repaired candidates are currently always export-blocked: splitting boundaries
can remove stretched sheets while exposing incomplete surfaces. A rigid-part
pass is not a closed-surface or contact pass.

`motion_completion.py` and `attachment_quality.py` own these generic stages.
`run_skin_mesh_pilot.py` consumes both. `run_source_wrist_trial.py` uses the same
attachment gate for its declared part mask. Neither shared module contains
unit identifiers. Source-reference bind preparation also maps attachment donor
names through its existing canonical-joint mapping.

The canonical diagnostic loader and standard corpus preview restore the recorded
completion before checking motion hashes. They verify the exact report path,
report hash, and completion provenance rather than silently rebuilding raw motion.
Legacy direct corrective-experiment loaders have not all been converted; their
motion-hash checks reject completed fits rather than implicitly discarding completion.

The standard preview accepts `--repair-report` to read the actual saved repaired
mesh. Readback checks fit/recipe/mask/candidate identity, reconstructs the declared
shared operation, checks every array, and restores the exact completed playback.
Recipes are snapshotted inside each repair output; source recipe edits do not
change an existing candidate. String region arrays serialize without pickle.

## Repair Capability

`attachment_repair.py` owns two operations:

- Consolidate a terminal owner's body weights into its parent only when their
  original skin transforms match across the entire corpus. Verify original LBS
  parity before proceeding. Independent terminal motion is an explicit refusal,
  not a reason to substitute another algorithm. Completed playback matrices are
  never changed; completion artifacts supply only the original equivalence-test
  reference when repairing a fit that already contains completion.
- Duplicate shared semantic boundary vertices on the prop side, retain original
  body-side ownership, and make the selected prop rigid. Preserve every triangle,
  face order, rest-space corner, and UV corner. No scissors, blind caps, extra
  bones, per-frame geometry, or attenuation of completed motion are used.

Each clip checks repaired non-prop corners against original body motion. This
check is unconditional, including recipes that disable consolidation.

`attachment_mask_refinement.py` optionally refines pinned boolean source samples
using a binary Potts cut over exact-position-welded triangle adjacency. UV seams
are not separate geometric parts. Certain foreground/background samples remain
hard seeds; ambiguous faces trade sample evidence against shared-edge smoothness.
Integer capacity limits fail closed. This proposes a mask, not semantic approval.

## Contracts And Coverage

Normal builds run `tools/validate_homm3_attachment_pipeline_contract.py` through
`ValidateHomm3AttachmentPipelineContract`. This standard-library-only source
check pins explicit completion selection, gate ordering, the export veto, and
the absence of unit literals in shared stages. It also pins explicit repair
dispatch, pre-repair export suppression, saved-candidate readback, and blocked
repair export while surface closure is unvalidated. It does not load models, render,
or claim runtime validation. Focused behavioral tests cover the numerical and
artifact contracts separately.

Empty attachment declarations return `applicable: false`. That means no declared
parts were checked, not that an asset has been audited and found attachment-free.
The gate cannot discover omitted parts or repair incomplete masks. In particular,
Ogre's historical profile labels only the club tip; a full-club mask is a distinct
reviewed input, not something the generic gate may infer from the word `weapon`.

Thresholds use the existing 1.5 stretch and 0.67 compression limits, localized to
interfaces and checked per frame. They are conservative structural diagnostics,
not calibrated predictors of human visual acceptance. Do not tune unit-specific
exceptions to make a favored example pass.

## Earlier Gate Evidence

- Ogre wrist replay `wrist_orientation_trial/h3_ogre/v3`: all three attacks
  fail the shared attachment gate; motion and GIFs are unchanged from v2.
- Hobgoblin `attachment_pipeline_audit/h3_hobgoblin/v2`: all 15 clips were
  checked without changing the profile, skin, or motion. Eleven pass; hit,
  death, attack-up, and attack-front flag interfaces. This does not rescind
  earlier positive visual feedback. The recorded cached audit took 3.13 seconds.
- Actual fitter `attachment_pipeline_audit/h3_ogre/fit_integration_v2`:
  explicit completion affects three attacks and preserves the other twelve
  clips. A bounded 120-second/one-image-iteration integration run finished in
  89.37 seconds, failed attachments/depth/animated-surface quality, and emitted
  zero GLBs. This is plumbing/export-rejection proof, not a quality optimization.
- Canonical diagnostic readback restored all fifteen clips with matching motion
  hashes. The standard corpus preview also restored the fit and rendered its
  five focus clips successfully. These are producer-consumer/render checks,
  not evidence that the attachment defect has been repaired.
- Thirty-four focused numerical/consumer/skin tests and four build-contract
  mutation tests passed. The named MSBuild validator target passed with
  deployment disabled. No plugin build, asset deployment, or runtime test ran.

The final integration run includes prepared-path descriptors and frame-zero
metadata recomputation. Source-reference donor remapping is source-reviewed,
not separately end-to-end exercised. No new visual improvement is claimed
from these changes.

## Repair Results

Generated candidates under `artifacts/homm3_mocap_v2/attachment_repair/`:

- `h3_ogre/v4_refined`: all fifteen clips, 14.50 seconds cached repair/render.
  Potts refinement selects 688 faces; 143 boundary duplicates produce 6,940
  vertices from 6,797 while retaining all 8,579 faces. Rest/UV corners are exact.
  Raw body ownership consolidation error is 9.44e-16 model units. Completed
  motion is unchanged. Prop residual is 1.71e-7, with zero owner influence on
  the body side. The large stretched club-to-body sheets are removed.
- The Ogre off-axis readback exposes remaining loose/torn surface fragments
  around the old attachment boundary. The maximum paired seam separation is
  approximately 1.31 model units. This is **not a closed or accepted mesh**.
  A detached prop passes the local rigid gate precisely because no mixed
  interface remains; that does not validate the exposed body/prop surfaces.
- `h3_hobgoblin/v2`: the same stage on all fifteen clips, 12.93 seconds. It uses
  existing profile weapon faces with no mask refinement or added motion. It
  duplicates 37 vertices, retains 8,921 faces, and preserves body corners within
  4.77e-7 in the float32 replay. Paired seam separation is zero. The front-view
  comparison is essentially unchanged, not a new motion-quality improvement.
- `h3_ogre/pipeline_integration_v1`: main fitter through repair in one invocation,
  54.44 seconds cached total (40.32 fitting, 13.90 repair). This deliberately
  short one-image-iteration fit proves dispatch and provenance, not optimized
  animation quality or production throughput. No GLBs were emitted. Standard
  preview successfully read back this completed-motion fit's repaired output.
- Sixty focused numerical/consumer/skin tests and eight build-contract tests
  passed. The named normal-build MSBuild validator passed with deployment off.
  CPU readback, CUDA replay, and off-axis generated previews are proven; no
  plugin build, asset installation, or runtime behavior is claimed.

The Ogre `v1` split-only and `v2` ownership trials were development diagnostics;
`v3_refined` exposed object-dtype region serialization during readback. Use
`v4_refined` or later for serialized-consumer evidence, not those earlier runs.
The recipe and capability are explicit, not automatically applied to every unit.
Leaf owners with independent original motion are deliberately unsupported by
the consolidation operation rather than silently approximated.

## Remaining Surface Work

The structural repair must be asset-level and shared across all clips:

- Review a complete semantic part inventory and attachment sites; store masks,
  ownership, and uncertainty as versioned inputs, not special-case algorithms.
- Distinguish an independently rigid prop, a deforming limb, a mounted body,
  and a releasable object. Do not force them all through the leaf-wrist method.
- Ownership separation is implemented, but exposed connections still need
  complete surface evidence. If topology makes the connection impossible, reconstruct the local
  surface explicitly rather than hiding it with motion attenuation or blind caps.
- Preserve the accepted rest appearance and validate every authored clip,
  including transitions. Separate image-fit improvement from structural safety.
- Promote a capability only after a cross-unit regression set passes; keep
  uncertainty/failure visible and measure annotation, repair, fit, review, and
  export costs separately. Cached solver time is not end-to-end production time.

Surface reconstruction remains to be implemented and visually proven. The
current repair addresses unintended ownership/webbing, not missing surfaces,
contact completeness, or the remaining source-action mismatch. Export stays
blocked instead of mistaking a local rigid-part pass for finished mesh quality.

## Follow-Up Diagnostics

The enclosed-mask diagnostic operates on existing face labels, not geometry.
It preserves the largest background component in each connected mesh and every
explicit background seed, and rejects open or non-manifold candidates. It is
not enabled in the repair runner. On the Ogre's actual 688-face Potts mask,
protecting all 7,800 zero-pass source faces adds only three faces (total area
0.00178163). This does not establish that incomplete mask holes explain the
remaining torn surfaces; no new visual improvement is claimed from this test.

The reusable `audit_faction_fit_status.py` reads and hashes the fit reports
referenced by a faction manifest, without converting legacy export flags into
acceptance. The Stronghold baseline snapshot in
`artifacts/homm3_mocap_v2/stronghold_audit/v2/fit_status_audit.json` contains 21
units and 20 referenced fits. Nineteen reports have quality gates: 19 pass rest
shape, six idle appearance, 13 depth clipping, and none animated surface or the
overall gate. Roc's legacy report has no quality gate; Boar Rider has no fit.
These are the roster's baseline reports, not the latest attachment repairs,
and these automated failures do not erase prior user feedback on previews.

Further interface skin fitting must distinguish motion outside a declared
repair region from bad weights inside it. The current whole-body motion-parity
check isolates the ownership split; it is not evidence that the original body
weights are correct. Any subsequent refit must keep captured motion fixed,
freeze the rigid part, and avoid re-welding the intentionally separated
ownership boundaries. The explicit skin-only follow-up below now implements
that stage; local surface reconstruction is still absent.

## Post-Separation Skin Refit

The optional shared stage is `run_attachment_skin_refit.py`. In the main
fitter, select it with `--attachment-skin-refit-seconds 240` together with an
explicit `--attachment-repair-recipe`. It runs after topology separation and
records its own immutable report in `pipeline_result.json`. It is not enabled
by default and does not make the candidate exportable.

The stage performs three explicit operations:

1. Reconcile inconsistent weights on exact-position body-side UV copies with
   their least-squares shared row. Prop copies remain separate and exact. A
   union exceeding eight influences is rejected, never silently truncated.
2. Propose bounded support from body topology neighbors, preserving existing
   positive support and recording discarded extra neighbor candidates. The
   declared training scope is all non-prop body vertices, not a guessed
   attachment-only region. Prop-only edges cannot introduce body neighbors.
3. Fit additive simplex-projected weights against every source frame using the
   existing image/surface objective and region-motion floor. This permits
   zero-initialized supported influences to enter without epsilon seeding.
   Rest vertices, faces, UVs, bind data, and completed motion remain unchanged.

Saved readback reconstructs conditioning and support, authenticates both source
and candidate files, and independently checks frozen weights, complete motion
inventory, and body-weld equality. Standard previews accept
`--skin-refit-report`. The normal-build attachment validator covers this stage.

Generated evidence under `attachment_repair/`:

- `h3_ogre/skin_refit_v1`: 15 clips / 85 frames; 339 divergent body weld groups
  (875 vertices) reconciled, with an original maximum weight difference of
  0.379432. Optimization took 39.49 seconds; cached stage plus front rendering
  took 61.15 seconds. The surface objective improves, but front and off-axis
  inspection still show the conspicuous floating fragments. This is not a
  visually successful repair of those fragments.
- `h3_hobgoblin/skin_refit_v1`: same policy, 15 clips / 88 frames, 599 divergent
  groups (1,601 vertices). Optimization took 32.57 seconds; cached stage plus
  rendering took 52.29 seconds. The front preview is essentially unchanged.
- Both saved candidates preserve the rest/topology and frozen prop exactly,
  have at most five positive influences, and have zero region-motion-floor
  violations. These facts do not prove anatomical ownership or surface closure.
- `h3_ogre/skin_pipeline_integration_v1`: real main-fitter -> separation -> skin
  refit dispatch and readback completed in 98.75 cached seconds. The main fit
  deliberately used one image iteration; this proves integration, not final
  fit quality. No GLBs were exported.
- All three saved candidates passed current readback, including the independent
  body-weld gate. Seventy-seven focused numerical, consumer, and build-contract
  tests passed. The named MSBuild validator target passed with deployment off.
  No plugin build, installation, or game-runtime validation was performed.

The reusable `diagnostic_fragment_pick.py` maps an explicitly selected rendered
pixel box to visible triangle IDs, ownership, regions, and skin influences.
The actual Ogre `fragment_pick_v2` readback identifies weapon-labelled source
geometry outside the selected prop mask alongside arm geometry. Source-region
labels are evidence, not final semantic truth. The preceding
`interface_audit_v1` used the wrong pre-repair skin and must not be used to
attribute current tears; `interface_audit_v2` checks the actual saved repair.

A CPU-only Jeffreys sample-likelihood counterfactual in
`h3_ogre/mask_likelihood_audit_v1` also failed to recover the picked weapon
fragments. Neither enclosed-mask filling nor this likelihood variant is
enabled in the repair runner. The next unresolved requirement is complete,
validated part ownership and exposed-interface geometry, not further tuning
of body weights or attenuation of the captured motion.

## Explicit Region-Union Diagnostic

`propose_attachment_region_union.py` produces a review-only repair recipe by
unioning the actual saved selection with faces whose three source corners have
one explicit profile rigid-attachment region. It uses the hash-pinned recipe
snapshot, preserves sample arrays, and leaves motion and source mesh unchanged.
It is not an automatic segmentation stage or an export-acceptance rule.

Generated `h3_ogre/region_union_v1` adds 27 weapon-labelled faces to the prior
688-face selection. All 15 clips repaired and front-rendered in 13.85 seconds
using cached fit and motion inputs. Saved off-axis inspection still shows green
fragments ahead of the face during the attack. Thus completing the existing
weapon label is insufficient; this candidate is not visually accepted.
The same operation on `h3_hobgoblin/region_union_v1` adds no faces and produces a
byte-identical 595-face proposal. Four focused producer tests pass. This is
generated diagnostic evidence, not a new production contract or runtime proof.

The next ownership investigation must distinguish true hand surface from
mislabelled attachment surface. Removing all wrist influence from non-prop
geometry is an isolation experiment, not proof of anatomical correctness.
Do not promote region labels or body-motion parity into such proof.

## Source-Supported Anatomical Ownership

New skin-refit reports use schema v2. The body solver may use the attachment
owner joint where the original fitted skin had positive owner support, mapped
through the saved split topology. Exact-position body UV copies share that
permission; prop copies remain frozen. This restores an allowed degree of
freedom, not the original weights. Initial weights remain the consolidated,
weld-conditioned weights, without epsilon seeding.

Original support is reserved before optional neighboring joint candidates;
the latter still use the bounded, recorded ranking. Required support exceeding
eight influences fails closed. Version-1 reports retain their original replay
semantics. Version-2 readback reconstructs the source evidence and domain.
Generated `h3_ogre/source_owner_refit_v1` completed all 15 clips / 85 frames in
52.25 cached seconds (35.70 optimization seconds). Support was opened for 938
body vertices across 629 weld groups. The saved solution uses positive owner
weight on only 16 body vertices, maximum 0.1574. Front attack IoU changes from
0.55756 to 0.55960; off-axis fragments remain. This is not a successful visual
repair. `h3_hobgoblin/source_owner_refit_v1` completed all 15 clips / 88 frames
in 238.81 cached seconds while other diagnostics ran; the cause of this timing
variation was not isolated. Front and off-axis previews show no obvious visual
regression, not general acceptance. Both candidates passed saved readback.

The 57 focused domain, field, readback, and build-contract tests pass. The
normal-build attachment validator target passed with deployment off. An actual
older v1 Ogre candidate still passes readback. No runtime proof is claimed.

Rest-space highlighting of the 48 picked faces left outside the 715-face mask
(`h3_ogre/remaining_fragment_rest_views_v1`) locates the visible remaining
pieces on upper-arm/shoulder surface, not merely the grip. The corresponding
`interface_audit_v2/fragment_bone_report.json` finds 82.37% of their area nearest
the RightShoulder-to-RightArm bind segment, while 71.93% was originally
RightHand-dominant. Source weights are therefore unreliable anatomical evidence
in this region. Do not enlarge the club mask to absorb those body faces. The
next repair must correct limb skinning using anatomical and motion evidence,
not assume either source weights or texture labels are authoritative.

## Anatomical Chain Initialization

`anatomical_chain_skin.py` provides an explicit geometry-based initializer for
profile polyline chains. Each outgoing segment is owned by its START joint,
not its distal joint; the terminal joint has a point feature. The nearest two
features receive normalized inverse-squared-distance weights with a fixed
one-percent median-segment-length regularizer. Zero-length or non-parented
chains are rejected. This is a candidate initializer, not anatomical proof.

`--anatomical-chain-regions arm_right arm_left` selects named profile chains
in the shared skin-refit stage and main fitter. The main fitter requires an
enabled attachment skin-refit stage. No unit IDs or face lists select behavior.
Unselected weights remain unchanged by initialization; the subsequent explicit
body-weld conditioning and all-body fit retain their documented wider scope.
Prop weights, rest geometry, bind skeleton, and captured motion remain fixed.

New skin-refit reports use v3 and record the explicit region list and complete
initializer evidence. Saved readback reconstructs the profile-chain seed,
conditioning and support before checking the candidate. Earlier report versions
retain their defined semantics. Empty chain selection is identity initialization,
not a fallback after an invalid chain.

The standalone `run_anatomical_chain_trial.py` is a diagnostic counterfactual,
not a delivery consumer. Both-arm trials completed all 15 clips in 33.07 cached
seconds for Ogre and 31.57 seconds for Hobgoblin, including front and off-axis
rendering. Ogre's major off-axis fragments diminish, but a thin front-view strip
remains. Hobgoblin shows modest limb-shape changes. Off-axis comparisons are
visual only, without an off-axis DEF target. Integrated optimized results remain
under evaluation; neither trial is accepted or exportable.

`h3_ogre/anatomical_refit_v1` is an actual v3 shared-stage run over 15 clips /
85 frames. Cached generation and front rendering took 257.31 seconds, including
222.21 optimization seconds. Saved readback and off-axis rendering passed;
maximum active influences are five and rest/prop invariants remain exact.
Major off-axis fragments diminish, but a narrow fragment remains. Front-attack
IoU declines from 0.55756 to 0.55421. One of 101 observable region/clip checks
misses the 0.9 motion floor (down-attack right arm ratio 0.872). This candidate
must not be described as quality accepted merely because it looks cleaner.

Further attribution in `interface_audit_v2/fragment_prepared_fitted_report.json`
compares identical face topology and joint-name arrays. Mean wrist weight on
the 48 picked body faces is already 0.425685 in preparation and rises to
0.559094 after fitting; 22 versus 29 faces exceed 0.5. Thus initialization
already contains misplaced support and fitting amplifies it. Identical arrays
exclude a simple post-fit column permutation, not every possible upstream bug.

The same integrated v3 policy completed `h3_hobgoblin/anatomical_refit_v1` over
15 clips / 88 frames in 233.15 cached seconds (209.97 optimization seconds).
Saved readback and front/off-axis inspection passed without an obvious new
visual defect. Attack IoU is 0.60822 before and 0.60871 after; all 103 observable
motion-floor checks pass. Maximum active influences are six. This is a control
candidate, not a faction-wide or runtime acceptance claim.

Fifty-six focused initializer, versioned readback, and build-contract tests
pass. The named normal-build validator target passes with deployment disabled,
including parent-outgoing ownership and frozen-attachment source checks. The
shared refit stage was actually executed; main-fitter argument forwarding is
source/build-contract validated, not a new full-fitter invocation in this pass.

## Ownership-Aware Initialization Routing

New runs retain outer refit v3 and select inner profile initialization v2.
Readback dispatches from the saved inner schema, so existing v3/inner-v1
candidates remain reproducible. When the selected rigid part has a unique
one-hot owner and its declared label also occurs on body-owned vertices,
those body vertices join the explicitly selected anatomical owner chain.
Ambiguous relevant ownership fails closed. Stored labels, selected faces,
prop weights, rest geometry and motion are unchanged. Routing and counts are
recorded; this is not a per-unit face-list expansion.
Every routed label component must also touch the target chain's body topology
through body-only triangle edges or exact-position body welds. Disconnected
same-label patches fail closed instead of being silently reinitialized. This
review-driven validation was added after generation; both saved candidates below
pass exact CPU reconstruction under the stricter check, without changed weights.

`h3_ogre/anatomical_routed_v2` exercised the finalized code on all 15 clips /
85 frames in 232.30 cached seconds, including 209.21 optimization seconds.
Eight body vertices with the stale weapon label received chain initialization.
Saved readback and off-axis rendering passed. The loose off-axis flap is reduced,
but arm distortion remains; front attack IoU is 0.55583 versus 0.55756 before.
All rest/topology and frozen-prop invariants pass, with at most six influences.
This is NOT an accepted visual repair or exportable candidate.

The unchanged centroid motion floor reports 11 failures in 101 observable
checks: ten concern the eight body vertices still stored under `weapon`, not
the frozen club; one is the down-attack right arm (ratio 0.874). Routing currently
affects initialization, not the legacy metric's region grouping. Do not conceal
these failures or confuse that body-label group with actual prop motion.
The earlier `anatomical_routed_v1` run overlapped helper validation edits and is
exploratory only; v2 is the finalized-code evidence run.

The diagnostic `interface_audit_v2/skin_joint_anchor_report.json` evaluates
fixed-joint tracking independently on the earlier anatomical candidate.
Valid right upper-arm/forearm anchors improve while hand tracking slightly
worsens. Shoulder anchors cannot reconstruct their bind sites and are explicitly
unsupported. This does not prove the cause of a centroid-floor failure.
The initializer's terminal point feature is capped at 0.5 by the clamped final
segment distance tie; that is a measured limitation, not yet a validated fix.

The same policy ran `h3_hobgoblin/anatomical_routed_v1`: 15 clips / 88 frames,
198.32 cached seconds including 168.49 optimization seconds. It routes 55 body
vertices, preserves rest/topology and frozen prop weights, and passes all 103
observable centroid-floor checks. Front attack IoU changes from 0.60822 to
0.60893; front inspection shows no obvious new defect, not broad acceptance.
Timing excludes previous capture/preparation and engineering/review time.

Seventy focused initializer, readback and build-contract tests pass. The named
MSBuild attachment validator passes with deployment disabled. Independent review
found no remaining substantive implementation blocker after the disconnected
label guard; visual quality remains unresolved. No game build/deployment or
runtime validation was performed for this diagnostic stage.

## Fixed-Joint Tracking

`skin_joint_anchors.py` builds fixed convex mesh anchors from unique body
vertices in explicit profile chains, including recorded body-label routing.
The constrained least-squares anchor must reproduce its bind joint within
five percent of the adjacent segment length. Unsupported sites are reported,
not filled by a guessed anchor. The target is the joint-world ORIGIN, not the
joint-world matrix applied a second time to the bind point. Reports retain
support, conditioning, residuals, coefficients and exact selected joint names.

`run_skin_joint_anchor_audit.py` reloads saved candidates, compares separated,
initialized and fitted meshes against those targets, and independently checks
rigid skinning transforms and parent/child agreement at shared bind joints.
`h3_ogre/joint_anchor_audit_v1` and the Hobgoblin equivalent take 8.60 and 10.07
cached CPU seconds. Both cached skeletons are internally coherent. Six arm
anchors are supported for each unit; the two shoulder sites are unsupported.
This limited coverage must not be presented as whole-body tracking proof.

`--joint-anchor-weight` is forwarded by the main fitter to shared skin refit.
Zero (the default) explicitly disables this experimental term. Positive weight
requires explicit anatomical chains and at least one supported anchor. The
objective minimizes squared distance to fixed joint origins, normalized by
adjacent segment length squared. It supplements image, surface and legacy
centroid objectives; it does NOT weaken or replace the existing motion floor.
Saved reports record the complete deterministic model, fixed-motion digest,
coverage and selected weight; readback reconstructs and compares that evidence.

Both actual `joint_anchor_refit_v1` pilots use the same weight 10000 and all DEF
frames, with no unit-specific gain. Ogre generation/front previews take 57.51
cached seconds (39.42 optimization); Hobgoblin 52.23 (35.48 optimization).
These warm timings exclude capture, preparation, separate off-axis rendering,
diagnostic CPU audits and engineering, and do not explain previous timing
variation. Rest/topology, frozen prop weights and fixed motion remain unchanged.

The saved CPU re-audits (`joint_anchor_refit_audit_v1`) find front-attack mean
supported-anchor error decreases from 0.001318 to 0.00007717 for Ogre and from
0.001045 to 0.00005503 for Hobgoblin, compared with the prior unanchored refits.
Ogre front IoU is 0.55653, still below the separated baseline 0.55756; its 11
legacy floor failures remain. Hobgoblin front IoU is 0.60892 and all observable
floor checks pass. The previews remain visually similar: improving point
tracking does not repair all intervening surface deformation. These are NOT
accepted or exportable assets. Full surface quality and broader cohort adoption
remain unresolved; do not increase this gain merely to chase a tracking score.

Ninety-five focused tests and the named normal-build contract target pass.
Shared-stage execution and saved front/off-axis readback are generated-candidate
proof. Main-fitter forwarding is source-contract validated only in this pass;
no game build, deploy or runtime validation was performed.
