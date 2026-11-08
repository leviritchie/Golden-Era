# Pikeman Diagnostic Pilot

## Status

Generated diagnostic only. No Pikeman animation is accepted for export, delivery,
or gameplay. Stronghold's approved installed motion is not changed by this pilot.
All paths below are relative to the repository. Preserve the historical candidates.

Frozen inputs:

- Profile: `profiles/h3_pikeman.json`, SHA-256
  `3fa48241fc95884512a98f0a62e48ba7ac3ca9d68375cf2bb802c2afbffb55d5`.
- Ownership: `profiles/ownership/h3_pikeman_v2.json`, SHA-256
  `0a05e318e20faa1aed2f4c76f9dbe0c04fc536b0846902bfd0469467543e3d53`.
- Preparation: `artifacts/homm3_mocap_v2/shape_preserved/h3_pikeman/preparation/authored_mapped_v4/`.
- Corpus and registration: `artifacts/homm3_mocap_v2/skin_mesh_pilot/pikeman/captures_v2/`
  and `registration_v2/`; original corrected-ownership fit: `all_def_v2/`.

## Wrist Trial

`run_source_wrist_trial.py --profile-ownership` used the existing orientation
solver and unchanged completion consumer. The reviewed blade terminal is the
centroid of original source vertices 35, 36, and 54; the true-material annotation
is `artifacts/homm3_mocap_v2/pikeman_wrist_annotations_v1/tip_anchor_060.png`.
The anchor is not the opposite wooden butt. Prepared, fitted, and trial rest-tip
coordinates are identical: `[0.234720846, 1.699963093, 0.308493992]`.

All 80 source frames have an observation inventory. Twelve clips / 75 frames
have observed pike direction and enter completion. Death's five frames remain raw
because its last two frames occlude reliable pike/grip landmarks. Hitted frames
1-4 visibly release the lower hand; their visible upper-hand direction is not
evidence of persistent two-hand contact. Idle timing remains a downstream approved
style policy, not a modification of this raw capture.

Annotation authority:
`artifacts/homm3_mocap_v2/pikeman_wrist_annotations_v1/annotation_draft.json`, SHA-256
`9adb87237e456fa296a2642d885c124ce4239e00cd0b9d3cece361d083fb4469`.
The historical filename is retained; its content records root authorization for
the diagnostic, not motion acceptance. Do not regenerate it in place after use.

Trial output: `artifacts/homm3_mocap_v2/skin_mesh_pilot/pikeman/source_wrist_v1/`.
It completed in 16.24 seconds. Body joint positions, non-owner world transforms,
and protected source-idle vertices have exactly zero change. Observed non-idle
projected pike directions match by construction; this is not an independent
quality score. The source's horizontal thrust becomes visible in the pike.

The existing same-fit runner consumed this completion in `all_def_wrist_v1/`,
completed in 55.76 seconds, and evaluated all 13 clips / 80 frames. All exports
remain rejected. Rest-shape and idle-appearance gates pass; attachment, physical
boundary, depth, and animated-surface gates fail. All 53 split boundary pairs were
measured. Upper-grip source vertices 523 / 529 / 555 reach 0.735987 / 0.778824 /
0.754016 source-unit gaps. The other 50 pairs peak at 0.011753, below the unchanged
0.012977 provisional one-render-pixel limit. These distances do not prove valid
contact elsewhere, and broad mixed-weight attachment faces are not substituted
for the exact physical interface.

Comparison GIFs in `all_def_wrist_v1/`: `g02_idle_comparison.gif`,
`g00_move_comparison.gif`, and `g12_attack_front_comparison.gif`. Fourteen focused
wrist producer/orientation tests pass. No GPU worker remains active for this pass.

## Causal Audit

The fixed joint/source mismatch is visible before skinning in
`artifacts/homm3_mocap_v2/pikeman_wrist_annotations_v1/attack_front_joint_stages.png`
and its JSON measurements. Frames 0 / 3 / 5 / 9 show fixed retargeted joints,
the existing aligned raw-capture diagnostic, and independently framed original
XY/XZ skeleton views. Neither raw display is an original input-camera reprojection.
They do not establish that the neural capture itself is the cause.

The exact frame-5 trace is in `frame5_provenance_audit.json` and
`frame5_preprocess_stages.png` in that annotation directory:

- Native `12_05.png` replays pixel-exact through Pikeman's own fixed union crop
  `[128,141,295,285]`, nearest-neighbor 6x resize, and shadow cull to its 1008x870
  prepared frame. The old path string in the canvas metadata is not used as a
  source fallback; actual source and prepared hashes are checked.
- Frame 5 maps to capture index 12 after seven idle context frames, and global
  encoder input 64. Both copied inputs have the exact prepared-frame hash.
- The encoder then uses vendor per-frame alpha cropping and square padding.
  Idle is 684x684 with source translation `[-66,-129]`; frame 5 is 798x798 with
  translation `[-228,-168]`. DINO resizes to 256 and center-crops to 224, yielding
  scale factors 0.374269 and 0.320802 respectively. This framing change is real
  and source-visible, but is not alone evidence that the trained preprocessing is
  wrong. Replayed processor images retain the thrust and body.
- Raw names and parent arrays match the frozen preparation exactly. Left arm /
  forearm / hand indices are 8 / 9 / 10, right indices 12 / 13 / 14. Array parity
  is not independent proof that inferred anatomical positions are accurate.
- Target camera registration is an idle-mesh silhouette fit at yaw 125 degrees,
  pitch 0, with one fixed scale/offset. It is not a raw-capture camera estimate.
  The raw NPZ contains no input camera or pixel reprojection transform. The vendor
  camera preview uses fixed Matplotlib elevation/azimuth and normalized extents.
- The existing raw-to-target Kabsch rotation is proper (determinant 1), scale 1;
  its `mappedCapture` replay differs by only 2.22e-16. This rigid alignment supplies
  the diagnostic and root travel. Actual bone directions are transferred through
  independently constructed per-chain rest frames. With one-bone chains the hint
  is global up; coordinate-frame and gesture-plane behavior remain a separate
  retargeting question, not a skin fitting problem.

The original grip-based measurements in this audit were superseded by the
full-resolution observation correction below. Historical artifacts are retained;
their approximate grip coordinates must not be treated as current contact labels.
The wrist trial leaves all body joint positions unchanged.

## Exact-Edge Counterfactual

The subsequent CPU-only audit is `attack_front_arm_plane_ab.png` / `.json` in the
annotation directory, authored by `audit_actual_chain_frames.py`. It changes only
six exact named arm-edge directions, without arc-length resampling or optimization.
It compares current global-up frames, corresponding adjacent anatomical-edge hints,
and minimal capture swing in the shared aligned coordinates. Target lengths, root
travel, other body directions, and camera remain fixed. No alternative motion is
published into a corpus or production consumer.

The actual Kabsch up-axis tilt is 4.9457 degrees. Neighbor-vs-global-up rest-plane
differences span 2.78-38.11 degrees, but frame-5 arm direction differences are only
0.74-7.71 degrees; shared swing differs by 0.69-6.60 degrees. Rebuilding the current
directions without regularization matches production positions exactly, eliminating
regularization as a confound in this comparison.

Neither variant repairs the source thrust; the viewed overlays remain substantially
wrong. The original grip-error values in that report use the subsequently corrected
annotation and are historical, not current contact measurements. The direction
comparison bounds the proposed arm-plane explanation for this candidate; it does
not establish raw inference failure or justify replacing the production retargeter.

Next work must distinguish raw inference, per-frame image framing, camera
correspondence, and retarget direction transfer through bounded comparisons.
Do not add body IK, more skin iterations, or a contact workaround before that
attribution; do not replace approved delivery motion silently.

## Translation Lower Bound

`grip_reaudit_v2.json` supersedes `translation_lower_bound.json` in the annotation
directory, using corrected visible grip proxies and the unchanged projected wrist
joints. The old report is retained as superseded evidence. For each sampled frame,
the mean source-minus-current displacement gives the least-squares shared 2-D
translation of both hands. This is an independent per-frame diagnostic lower
bound, not authored root motion or a proposed correction.

| Frame | Best translation X/Y, pixels | Residual per hand, pixels | Hand-vector error magnitude, pixels |
| --- | --- | --- | --- |
| 0 | -21.26 / 33.44 | 48.87 | 97.74 |
| 3 | 34.14 / 35.28 | 97.84 | 195.69 |
| 5 | 173.78 / 94.45 | 92.88 | 185.77 |
| 9 | -32.00 / 50.52 | 61.77 | 123.53 |

Units are the original 1008x870 source canvas. At thrust frame 5, the source
left-minus-right grip vector is `[70,-4]`, whereas the projected joint vector is
`[-114.44,-26.16]`. Even unrestricted shared translation cannot change that
relative posture: both hands retain 92.88-pixel residuals at their joint/grip
landmarks. Missing root travel alone therefore cannot explain the mismatch.
No motion, camera, annotation, or fitted skin was changed by this calculation.

## Corrected Observation And Camera Audit

Direct full-resolution reinspection found that the historical frame-5 lower grip
`[423,597]` was near the waist, not the visible gripping hand. The corrected visible
right/left hand centers are `[500,590]` / `[570,586]`. Frames 0, 3, and 9 were also
re-audited in `grip_reaudit_v2.png` / `.json`. The old wrist-trial annotation is not
mutated or promoted as accurate contact data. With the same observed blade tips,
correcting lower grip changes projected grip-to-tip angles by -1.16, 0.13, 0.99,
and 0.65 degrees in frames 0, 3, 5, and 9. This supports the broad horizontal-axis
observation, not exact wrist orientation or contact acceptance.

Visible hand centers are approximate shaft-grip proxies, not hidden wrist origins
or exact surface contact points. Author-estimated location uncertainty is about
two native pixels (12 enlarged pixels) per coordinate, not a statistical confidence
interval. Systematic hand-center-to-joint offsets remain separate. Body camera
proxies have three-native-pixel uncertainty at collar/knees/ankles and four at
the visible belt center; the belt is not a claimed hidden pelvis observation.

`raw_camera_v1/annotations.json`, `camera_reprojection.png`, and `report.json` fit
only a weak-perspective rigid camera to unchanged raw capture frames 0 and 5.
Six visible body proxies enter fitting: collar/neck, belt, two knees, two ankles.
Both hands are held out. Each camera has six degrees of freedom: proper rotation
3, positive isotropic scale 1, screen translation 2. There is no joint optimization,
perspective/depth translation, or crop correction. SciPy least-squares uses 24
deterministic initial rotations, up to 400 evaluations each. An alternative
lower-limb label assignment is explicitly reported, not silently selected.

For the declared leg assignment:

| Camera | Body RMS, enlarged pixels | Held-out right/left grip errors, pixels |
| --- | --- | --- |
| Shared, frame 0 | 30.96 across both frames | 9.19 / 70.11 |
| Shared, frame 5 | 30.96 across both frames | 116.05 / 69.71 |
| Independent frame 0 | 13.51 | 28.03 / 52.15 |
| Independent frame 5 | 15.61 | 88.63 / 41.98 |

The swapped-label frame-5 camera has body RMS 20.49 pixels and held-out errors
86.35 / 251.41. Camera ambiguity and approximate body/joint sites preclude treating
these fits as ground-truth reconstruction. A camera fit substantially changes the
apparent raw pose and improves body overlay, but these body-only solutions still
leave significant held-out hand discrepancy. This is not proof that projection
alone explains the motion, nor a definitive neural-inference fault diagnosis.
