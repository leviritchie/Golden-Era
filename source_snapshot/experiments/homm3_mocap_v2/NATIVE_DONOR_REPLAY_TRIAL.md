# Native Donor Replay Isolation

## Scope And Current Authority

Diagnostic only. No production capture, preparation, selector, export, or runtime
payload is changed. All 21 Stronghold units remain the objective. These two-bird
controls isolate the capture representation before additional target skin fits.

IMPORTANT: `native_donor_v1`, `native_donor_v2`, and
`native_donor_position_anchored_v1` are superseded. The latter two compared raw
normalized network positions with unnormalized native donor positions. Their
raw-position mesh deformation and length-error measurements are not valid
evidence for accepting or rejecting position-preserving replay. Identical names,
parents, and stored BVH offsets did NOT establish identical position units.
The first v1 also omitted textures/DEF and repeated identical mesh columns.

The corrected comparison is `native_donor_position_anchored_v2`. It completed
all 30 clips / 184 authored frames plus the known Landing control. It is rejected
for promotion: raw-position preservation does not recover the missing full wing
action and increases surface distortion. No production animations are replaced.

## Verified Coordinate Conversion

The original Eagle mesh is under
`artifacts/homm3_mocap_v2/vendor/MocapAnything/demo/data/zoo1030/characters_fix_facezplus/Eagle`.
It is not the Eagle-skinned Roc copy. Both bird corpora have exactly the donor's
50 joint names, parent indices, and capture offsets. Those establish identity,
not equality between model-output coordinates and OBJ/BVH units.

The inference batch constructs model position targets as:

```
normalized = (stored_posePosition - stored_posePosition[:, :1]) / globalScale
```

For the current Eagle package, `globalScale` is 0.39390588778938346. Stored
posePosition edge lengths are 0.53305841 times native BVH lengths. Normalized
model-target lengths are therefore 1.35326337 times native lengths.

`native_donor_coordinates.py` derives one proper origin-fixed similarity from
the paired normalized model targets and independently computed native BVH FK,
after removing each frame's root translation. All 91 frames are used. It does
not fit any Thunderbird/Shahrokh prediction or hardcode a corrective scale.

Current derived conversion:

- normalized-model -> native scale: 0.7389544559106105;
- rotation: identity to within approximately 4.1e-9 per component;
- maximum paired-ground-truth joint residual: 8.02997e-8 native units;
- mean paired-ground-truth joint residual: 1.51863e-8 native units.

The raw model roots are zero by the existing static root policy. The conversion
adds the explicit native bind root [0, 0.260791, -0.024336]. Native known-motion
control uses its actual per-frame BVH root translations separately. Root travel
must not be inferred from the model's static zero roots.

The capture's `vendor_offset_a` is not a joint-position array. Vendor BVHReader
sets `rest_pose = anim.offsets`; inference then subtracts root offset and divides
by globalScale. The runner checks that exact local-offset metadata formula.
It does not treat it as global T-pose joints or a posed reference frame.

## Controlled Deformation Comparison

`native_donor_position_replay.py` reconstructs local rotations from converted
Cartesian edge directions, native fixed offsets, and converted root positions.
Original donor vertices, weights, and T-pose inverse bind are used throughout.

With explicit `--position-anchored`, `position_anchored_donor.py` copies those
world rotations and replaces only world translations with the converted capture
positions. It derives local translations in parent coordinates and requires
independent FK parity within 1e-6. This allows variable local translations and
is explicitly not a fixed-length skeleton. It does not recover unobserved twist.

The known Landing BVH is a separate rotation control. Original rotations -> FK
positions -> reconstructed rotations reproduce endpoints to 9.17234e-7 units,
but mesh vertex discrepancies average 0.008845 and reach 0.212391. That is the
position-only orientation ambiguity, not a model normalization comparison.
The main action survives visibly; some wing-surface orientation does not.

## Evidence Requirements

The runner renders actual DEF | raw/FK sticks | fixed native mesh | anchored
native mesh in fixed front and side views. The DEF camera remains independent,
not pixel-calibrated. Exact OBJ face-corner UVs are used. Bounds include every
compared state before freezing the camera, without per-frame fitting.
Input images, captures, corpora, donor files, and implementations are hash-pinned.
The coordinate conversion must pass paired-ground-truth residual validation
before any capture is replayed. Output directories cannot overwrite old evidence.

Eighteen coordinate/replay/runner tests and five position-anchor tests passed.
They cover similarity recovery/refusal, explicit root anchors, observable
articulated skinning, neutral/rigid mesh behavior, input immutability, variable
fork translations, raw-position parity, invalid affine transforms, source index
identity, and fixed framing. These tests do not prove Stronghold visual quality.

## Corrected Results

Corrected replay/render/surface scoring completed in 267.011146 seconds from
cached captures. This excludes capture inference and engineering. Both input
and implementation hashes were independently checked afterward: zero mismatches.

| Unit | Mean stretch violation, fixed | Anchored | Mean compression, fixed | Anchored |
| --- | --- | --- | --- | --- |
| Thunderbird | 0.080233 | 0.115211 | 0.093816 | 0.174438 |
| Shahrokh | 0.067487 | 0.120587 | 0.090268 | 0.138517 |

These are equal-authored-frame averages from the existing triangle principal
stretch diagnostic (>1.5 stretch, <0.67 compression), not image scores.
Anchored joint-position residual is exactly zero in both units, and FK parity
maxima are 3.09e-13 / 2.53e-12. Fixed-length endpoint residual maxima are
0.256256 / 0.265688 native units; raw bone-length discrepancy maxima are
0.246720 / 0.203371. The maxima include all 15 groups per unit, not just movement.

Corrected Thunderbird movement and Shahrokh upward-attack sheets were inspected.
Anchored and fixed meshes are now substantially closer than the mixed-unit trial
suggested, but neither reproduces a convincing full wing action or the source's
folded-wing idle. This rejects anchoring as a standalone fix, not every possible
position-preserving skin/mesh solver. Unobserved orientation remains unresolved.

## Next Decision

Test source-reference sensitivity before another target skin correction. Three
complete local Eagle Landing references were checked: y0, y15, and y90. Current
captures pin y15. The current inference implementation uses reference frame 0,
a raised-wing Landing pose. Whether reference conditioning affects missing folded
poses remains a hypothesis. A comparison must convert each reference's normalized
coordinates using paired vendor data, not assume identical position units or axes.

## Reference-View Comparison

Completed fresh captures for y15, y0, and y90 on movement, idle, and upward attack
for both birds: 18 calls, with source image embeddings held exactly fixed.
All six fresh y15 controls reproduce the old predicted positions bit-for-bit.
No default reference changed. The final comparisons remain visually unsatisfactory;
reference view does not explain the missing full wing action in this cohort.

Authoritative artifacts:

- `artifacts/homm3_mocap_v2/eagle_reference_capture_v1/report.json`;
- `artifacts/homm3_mocap_v2/eagle_reference_preview_v2/report.json`;
- six comparison GIFs/PNGs and converted-position NPZs under the preview directory.

Fresh capture/model-load time was 66.151661 seconds; final conversion/replay/render
time was 71.378791 seconds. These exclude source feature encoding (cached),
engineering, tests, and a superseded 69.115756-second prototype render.

Mean converted joint differences from y15 range from 0.002998 to 0.004444 native
units for y0 and 0.005888 to 0.007839 for y90 across the six unit/clip cases.
They change some feather/body orientation, but movement and folded-wing idle
remain incorrect in inspected Thunderbird movement and Shahrokh idle sheets.

`eagle_reference_preview_v1` is superseded: it aligned each reference performance
to the y15 performance, wrongly treating reference actor yaw as a coordinate
basis change. V2 instead pairs each normalized reference with its OWN native
BVH. Non-root bind offsets are identical across packages. All three conversions
are identity rotations up to numerical noise with scale approximately 0.738954;
maximum paired residual is below 8.4e-8. No relaxed tolerance remains.

Source provenance checks now verify original manifest hashes, all context PNGs
against frozen source hashes, authored ordering/indices, and fresh-versus-old
embedding equality. The final preview independently rechecks these for the
completed captures and requires exact y15 prediction parity. Input and
implementation hashes were rechecked after rendering with zero mismatches.

Five reference-specific tests passed, including source/context replacement and
ordering refusal and a regression proving actor yaw is not removed from the
inferred pose. The eighteen native replay/coordinate/runner tests and five
position-anchor tests also passed. Separate Luna reviews covered math and
provenance; root corrected the identified gaps and inspected the rendered output.

Next isolate temporal context rather than switch reference defaults. In
particular, check whether flight-loop captures are being conditioned as brief
departures from idle, despite movement start/stop having separate authored clips.
Any cyclic-context comparison must repeat only existing authored loop frames,
preserve their timing/order, and leave attack idle transitions unchanged.
The current movement input is specifically 8 idle + 4 move-start + 6 movement +
4 move-end + 8 idle frames for Thunderbird; Shahrokh has 3 move-end frames.
Those are genuine authored transitions, not erroneous padding. The proposed
comparison asks whether sustained cyclic context changes the six retained loop
poses, not whether authored transitions should be removed from delivery.

## Cyclic-Context Comparison

Completed the same-length context control for both birds' movement clips.
The original inputs remain 30/29 frames; candidate inputs repeat only the six
existing authored movement frames. Indices 12..17 retain exactly the same PNGs
and cached image embeddings, in the same order. No interpolated frames, changed
reference, target re-skin, or production manifest changes were used. This is
a diagnostic context policy, not a replacement for authored start/stop delivery.

Authoritative outputs are `eagle_cyclic_context_capture_v1/report.json` and
`eagle_cyclic_context_preview_v1/report.json` beneath
`artifacts/homm3_mocap_v2/`, with two comparison GIFs and position/world NPZs.
Both fresh original-context controls reproduce the old full predicted-position
arrays bit-for-bit. The preview independently checks old manifest/source PNG
identity, capture hashes, full context mapping and embedding equality, reference
identity, and unchanged authored frame paths/indices. Both policies use the same
y15 conversion and original native Eagle geometry, skin, bind, and shared camera.

Mean native joint differences from original context are 0.043410 for Thunderbird
and 0.063194 for Shahrokh. These are substantially larger than the reference-yaw
differences, but not quality scores. Inspection of both comparison sheets still
shows incomplete wing action; neither candidate recovers the source wingbeat.
Reject cyclic context as a standalone fix and do not change default capture policy.
This result establishes context sensitivity, not the cause of the visual failure.

Fresh capture including model load took 32.319791 seconds; conversion, replay,
and rendering took 18.895827 seconds. These exclude cached feature encoding,
engineering, tests, and review. All recorded input and implementation hashes
were independently rechecked with zero mismatches. The 27 `test_eagle_*.py`
tests passed, including seven cyclic mapping/policy tests. Luna review found no
blocking issues after root corrected the initial runner/preview scaffolds.
The 21-unit inventory validator also passed; that is roster/evidence-path
validation, not faction animation acceptance or runtime proof.

## Learned-Rotation Native Replay

Completed a separate native Eagle mesh replay of the actual `pred_rot6d` tensors,
without position-derived orientation, target retargeting, or scale correction.
The decoder is `model_runner.rotations_from_6d`, which calls the vendor
`utils.transforms3d.rotation_6d_to_matrix`. It stacks basis vectors as ROWS
(`dim=-2`), matching the stored first-two-rows local BVH training targets.
Do not confuse it with `utils.rotation.rot6d_to_fk_positions`, whose column
decoder differs. `vendor_fk.storage_rot6d_fk_positions` also uses the correct
row convention; it is not the incompatible helper.

Before replaying candidates, the runner decodes all 91 known Landing frames and
compares against native BVH quaternion FK using the same Eagle mesh/skin/bind.
Maximum local-matrix difference is 1.80618e-7; maximum world-matrix difference
is 4.77632e-7; maximum skinned-vertex distance is 2.47167e-7 native units.
All pass the explicit 1e-5 control gate. The known-motion comparison sheet was
visually checked as well. This proves decoding and native mesh replay for the
stored ground truth, not accuracy of learned rotations on HoMM3 sprites.

Authoritative results: `artifacts/homm3_mocap_v2/native_donor_rotation_preview_v1/`
contains `report.json`, the known Landing control GIF, six bird comparison GIFs,
and per-case raw positions plus position/rotation world-transform NPZs.
The candidate cases cover movement, idle, and upward attack for both Thunderbird
and Shahrokh, retaining the original source/context captures unchanged.
Both paths use fixed native bone lengths and explicit bind-root anchors.
No predicted positions are used to correct the learned-rotation candidate.

The learned-rotation output still fails to recover a convincing source wingbeat
or folded-wing idle in the inspected Thunderbird movement and Shahrokh idle
comparisons. Reject switching directly to learned rotations as a standalone
fix. The known control demonstrates that the native donor can represent folded
wings; the bad idle is not proof of a donor geometry incapable of folding.
Learned rotation FK differs from raw model positions by mean distances of
0.09911 to 0.12690 native units across the six cases. These are disagreement
measurements, not source-pixel quality scores or acceptance thresholds.

Total cached replay/control/render time was 135.154116 seconds, including the
91-frame known-motion render. No fresh inference or feature encoding was run.
All recorded input and implementation hashes were rechecked with zero mismatch.
Twenty-four native donor tests passed, including six rotation-replay tests
with actual vendor decoding, plus two intermediate FK convention tests.
Luna reviewed the implementation; root corrected convention wording and replaced
mock-only decoder coverage with actual-decoder tests. Production remains unchanged.

## Held-Frame Cadence Comparison

Completed original versus `hold2` for Thunderbird and Shahrokh movement.
`hold2` repeats EACH original context frame twice, not two passes through the
sequence. Input lengths are 60/58 rather than 30/29. The six retained authored
frames are selected at twice the original indices, using the first copy of
each held frame. Source images, reference, and final 12 FPS preview timing remain
unchanged. This tests sampling sensitivity; it is not a verified 30 FPS input
normalization and does not interpolate new poses.

Both original controls again reproduce the full old predicted-position tensors
bit-for-bit. The preview independently checks original source identity, old/new
capture hashes, exact per-frame repetition, selected authored correspondence,
and cached embedding equality. It uses the same native Eagle donor and y15
coordinate conversion, with no target remapping or production changes.

Results: `artifacts/homm3_mocap_v2/eagle_cadence_capture_v1/report.json` and
`eagle_cadence_preview_v1/report.json`, plus both movement GIFs/PNGs/NPZs.
Mean converted joint differences from original are 0.0322243 for Thunderbird
and 0.0496641 for Shahrokh. Inspection of both sheets still shows inadequate
wing action. Reject held-frame cadence as a standalone fix; do not promote
different movement as better movement or change default source sampling.

Fresh capture including model load took 34.689716 seconds; replay/render took
19.590213 seconds. Feature encoding was cached. Engineering/review/test time is
excluded. Eight cadence tests passed, including actual repeated-frame versus
whole-sequence-repeat rejection and mapped PNG identity tests. Recorded input
and implementation hashes were rechecked with zero mismatches. Luna review of
the root-corrected scripts found no blocking issue.

Stop this input-setting sweep. The next representation experiment is described
in `POSE_CONDITIONED_MESH_PILOT.md`: fixed mocap controlling a small shared set
of mesh correctives rather than another shared rest-only deformation. That
document is a proposal, not an implemented result or a delivery contract.
