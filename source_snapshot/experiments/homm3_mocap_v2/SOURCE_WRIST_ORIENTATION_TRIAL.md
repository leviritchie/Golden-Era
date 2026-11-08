# Source-Guided Wrist Orientation Trial

## Scope

The user authorized source-guided wrist/weapon rotations while retaining every
mocap joint position. This is an isolated diagnostic, not a new motion-loader
default, an accepted Stronghold delivery, or permission for paid asset generation.

The first test is Ogre's three authored attack clips, using the existing
full-club rigid skin candidate. The baseline and trial share fitted rest geometry,
weights, camera, captured joint positions, and every non-wrist world rotation.
Only the terminal right wrist orientation may differ. Added rotations are saved
separately from the frozen mocap and fitted inputs.

## Observable Information

Eye-authored, source-hash-pinned grip/tip landmarks supply a two-dimensional club
direction. The solver retains the current direction's camera-forward component
and projected length, changes its screen-plane azimuth, and applies a minimal
proper rotation. Depth and axial roll remain priors, not recovered observations.
Ambiguous landmarks remain identified as such.

This cannot repair an incorrect wrist trajectory, missing arm action, incorrect
mesh anatomy, or contact geometry. Direction agreement is a diagnostic measure,
not a visual-quality acceptance score. Identical source idle frames must retain
their baseline pose; first/last frame indices alone do not identify idle.

## Validation

The runner must fail on stale source/candidate hashes, mismatched fitted inputs,
nonterminal ownership, altered joint positions, altered non-wrist transforms,
changed vertices with zero wrist influence, loss of selected-club rigidity, or
neutral-rest drift. No output is wired into production or deployment.

Fourteen focused tests pass, including the mathematical, legacy candidate/source,
reviewed-profile ownership, explicit tip-anchor, and observed-scope checks. The isolated runner also
checks source-frame foreground support near both landmarks before any GPU work;
this rejects gross off-mesh annotation errors, not subtle semantic errors.

## Generated Results

The first generated pass is under
`artifacts/homm3_mocap_v2/wrist_orientation_trial/h3_ogre/v1/`.
All three seven-frame attack clips were replayed. The first frame in each is
byte-identical to an idle source frame, so its baseline pose was protected.

- All joint positions, non-wrist world matrices, zero-wrist-influence vertices,
  and protected-idle vertices have exactly zero baseline/candidate difference.
- Selected rigid club edge error is at most 2.24e-7 model units; neutral skin
  identity error is 2.39e-7 model units.
- The 18 non-idle frames match the annotated projected direction to numerical
  precision. This is expected by construction, not independent visual proof.
- Added wrist rotations reach 126.1 degrees. Unobserved depth remains unchanged;
  consequently foreshortening is not recovered from the source.
- Input validation took 3.49 seconds and replay/render took 3.96 seconds,
  7.47 seconds total inside the runner. This excludes process startup, original
  capture/base fitting, landmark authoring, review, and engineering. It does not
  establish a sub-ten-minute end-to-end production process.

Visual result: the weapon now aims along the source's attacks, but large wrist
rotations expose severe stretched connecting faces. The fixed captured arm poses
also remain unlike the source. This pass is rejected as a finished animation.

The corrected `v1/surface_audit.json` uses the actual rigid candidate weights,
not the fitted baseline weights. All 668 selected club faces are fully rigid;
the candidate has 727 fully wrist-owned faces, 1,230 mixed-influence faces, and
6,622 zero-wrist-influence faces. The extreme additional stretch occurs outside
the selected club mask in mixed-influence faces. The audit's topology and inverse
bind were independently compared with the registered preparation and are equal.
This supports an attachment/skin-boundary defect, not a failure to keep the club
itself rigid. It does not establish the sole cause of every visual defect.

The final validator-hardened rerun is in the sibling `v2/` directory. It passed
the same checks in 9.26 seconds (3.34 input validation, 5.91 replay/render).
All three GIFs and the serialized motion NPZ are byte-identical to v1. The v1
surface audit therefore describes the same motion/skin result. Independent
review found no further correctness blocker; this is generated diagnostic proof,
not visual acceptance, build/deploy proof, or runtime proof.

Next work should address semantic part ownership and a valid deformable
hand/forearm attachment before broadening this orientation layer. Do not hide
the defect by shrinking the source-supported action, increasing global smoothing,
or detaching arbitrary faces without a valid surface/contact reconstruction.
No source inputs, production loaders, deployed bundles, or runtime were changed.

## Reviewed Profile Input

`--profile-ownership` is an explicit diagnostic input mode for a current structured
profile and its frozen preparation. It is mutually exclusive with legacy
candidate/mask directories. The producer replays the reviewed physical ownership,
checks the fitted source-vertex map and rigid weights, and requires the selected
profile digest in preparation, corpus, fit, and annotation. It rechecks the
current profile before publishing its report.

This mode requires source-pinned, visually reviewed blade-tip vertex IDs inside
the exact rigid surface. It does not use the legacy farthest-five-percent anchor
heuristic. Every corpus clip must appear either as fully observed completion
input or as an explicitly uncompleted, source-hashed capture with a reason.
Each completed clip reports all source-replayed ownership boundary pairs through
the existing gate, including failures. The existing motion-completion consumer
remains unchanged; uncompleted clips retain their saved raw motion.

The Pikeman diagnostic and its unresolved capture/retarget attribution are
documented in [Pikeman Pilot](pilots/pikeman/README.md). No new optimizer, production
motion default, delivery exception, or acceptance threshold is introduced.
