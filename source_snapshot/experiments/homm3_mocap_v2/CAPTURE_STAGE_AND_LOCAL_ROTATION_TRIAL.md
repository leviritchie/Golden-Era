# Capture Stage And Local Rotation Trial

2026-09-06. Diagnostic evidence only. Local-rotation candidate rejected for
promotion. No production motion selection, mesh, skin, source or camera changed.

## Loss Decomposition

audit_capture_stages.py evaluates all 45 groups / 260 authored frames from
Ancient Behemoth, Thunderbird and Ghost Behemoth. The raw model prediction is
the comparison reference, NOT independently verified animation ground truth.
It compares raw joints, independently length-normalized edges (not legal rigid
branch FK), unsmoothed FK on the captured reference posture, the current same-
reference FK, and current fitted-rest FK. All use the original captured inputs.

The first four stages share coordinates, reference lengths and root travel.
Positional RMS is normalized by the captured reference joint-box diagonal.
The following are frame-weighted means of per-clip metrics, not pooled RMS:

| Unit | Length-only RMS | Unsmoothed rigid FK RMS | Unsmoothed / current mean edge error |
| --- | ---: | ---: | ---: |
| Ancient Behemoth | .03135 | .03207 | 1.001 / 1.001 degrees |
| Thunderbird | .02732 | .03031 | 2.771 / 2.776 degrees |
| Ghost Behemoth | .03618 | .03845 | 1.361 / 1.361 degrees |

This does not justify adding bone stretch or disabling smoothing as a general
fix. In these controls, length normalization changes positions but preserves
edge directions; branch rigidity adds limited average directional loss, and
smoothing adds almost none. Per-bone/branch rows remain available because an
average can hide important individual errors. In Thunderbird movement, wing-
root edge errors grow from roughly 6-7 degrees on the captured rest to roughly
26 degrees against desired directions on the fitted rest. The bind transfer
adds a distinct problem, not merely a skin-weight failure.

Branch reports include raw-versus-reference child-pair dot changes. A nonzero
change proves those raw directions cannot all be realized by a single rigid
parent rotation. That is separate from raw-versus-stage direction differences.
Structural zero edges are excluded. Stage-audit v1 incorrectly counted a zero-
length fitted helper as a 90-degree direction error; v2 excludes it explicitly.
Use stage_audit_v2/report.json and accompanying NPZ/GIF/sheets for current data.

Preview skeletons are root-relative and normalized by each reference span.
They use one viewing basis and are NOT pixel-aligned source overlays, mesh
playback, or evidence that a raw prediction follows the actual sprite.
CPU processing for the three v2 audits totaled 28.90 seconds.

## Local Rotation Counterfactual

local_rotation_capture_motion.py reconstructs source local rotations on the
capture reference skeleton using the existing reconstruction policy. One static
reference-to-fit rotation Q transports every local rotation as Q R Q-transpose.
Target FK retains fitted offsets and maps raw root travel through that same Q.
No per-frame body-rotation fit, authored per-unit rescue angle, skin fitting or
mesh optimization is added. The comparison runner requires explicit
--candidate local_rotation; production corpus_motion.py is unchanged.

All columns use the ORIGINAL prepared skin, not the subsequently optimized
skin/mesh. Geometry, weights, camera, source frames and capture indices match.

| Unit | Mean IoU current -> candidate | Color error current -> candidate | Seconds |
| --- | --- | --- | ---: |
| Ancient Behemoth | .63264 -> .62522 | .51515 -> .51564 | 10.43 |
| Thunderbird | .54830 -> .49012 | .46751 -> .47890 | 13.90 |
| Ghost Behemoth | .63946 -> .62360 | .77537 -> .77732 | 9.91 |

All three regress in silhouette and color. Ancient gains some forward claw
reach but not the overhead pose. Thunderbird still lacks a convincing wingbeat
and deforms poorly. Ghost also misses overhead reach. Candidate rejected.
The 34.24 seconds is cached render/score comparison only, excluding coding,
review, source capture, preparation and fitting. No delivery GLBs were exported.

The actual-preparation rigid-turn control is recorded in rigid_turn_v3.json.
The candidate preserves all joint-pair distances for Ancient and Ghost to
numerical precision, but Thunderbird still changes pair distances by 20.88%
of its target joint span. Fixed bone lengths remain within 2.8e-15 on real
clips. Fixed length and passing a simplified synthetic rig are not sufficient
proof of correct rigid motion on the actual skeleton.

## Verification And Next Boundary

Stage tests cover length-only changes, incompatible branch angles, rigid turns,
nonzero reference origins, root travel and nonfinite rejection. Candidate tests
cover reference identity, distinct rest angles, structural coincident hubs,
nonidentity static Q, fixed length and unchanged inputs. Existing comparison
tests continue to pass (26 focused tests total). Reports pin the implementations
and source artifacts.

Do not promote this candidate or compensate with unit-specific angles. The
remaining boundary is reconstruction of observable joint orientation versus
unconstrained twist when reference and fitted branch geometry differ. Diagnose
that on the real failing hierarchy before another production change. Boar mesh
provenance and the rest of the 21-unit roster remain independently outstanding.

## Thunderbird Structural Cause

Follow-up isolated the first nonidentity source local rotation during the rigid
control: Hips stays identity and Bip01_Pelvis carries the turn (up to 90 degrees).
The source Hips-to-Pelvis offset is exactly zero, whereas the frozen target
offset length is 0.3933096885 (root independently verified). Source positions
cannot distinguish assigning a turn to these coincident hubs. Separating them
in the fitted bind makes that formerly unobservable choice affect geometry.
Hips has total skin mass 370.78 over 505 vertices; Pelvis has 30.25 over 311.
This is not merely a distance metric on an irrelevant unweighted helper.

The first nonzero source branch is rank 2, not a collinear multi-child SVD
ambiguity. Do not respond by changing Kabsch rank handling on speculation.
The next corrective trial should preserve coincident-joint structure across
capture and fitted bind, with unchanged rest mesh and explicit regenerated
inverse binds. Audit the entire donor cohort for the same structural mismatch
before introducing a generalized preparation rule. This cause explains the
Thunderbird rigid-control failure; it does not by itself explain every weak
attack/wingbeat in the roster.

Follow-up completed in COINCIDENT_BIND_TRIAL.md: preserving coincidence AND
canonical skin ownership resolves weighted rigid-turn errors on two bird
assets, but actual wingbeats still fail. That diagnostic is not promoted.
