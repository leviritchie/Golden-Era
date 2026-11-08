# Image-Scored Static Joint Axes

## Decision

No promotion. Shared axis calibration improves the new source-motion baseline
on training frames, but both birds remain visually unsatisfactory and neither
beats the existing prepared result on the withheld attacks. No production
preparation, source capture, selector, export, or runtime payload changed.

## Contract

`joint_axis_calibration.py` has one proper rotation correction per non-root
joint, shared across every clip. It conjugates each fixed local rotation by
that correction. Root rotation, root positions, bind offsets, mesh, materials,
and weights are frozen. Conjugation preserves each local angular trajectory
in a changed coordinate gauge; it does not preserve exact world joint positions.

The runner reconstructs positions in the source's shared reference geometry
using body-relative reconstruction, then maps those locals through one static
source-to-target gauge. It does not fit the source motion directly on target
offsets or use learned `pred_rot6d` as motion authority. The target skin is the
explicit canonical coincident-bind candidate.

There are 147 trainable scalar parameters for these 50-joint rigs. Optimization
uses 250 Adam steps at 0.03. Checkpoint selection uses training image loss plus
0.02 times the existing dimensionless surface loss. Whole clips g11_attack_up
and g13_attack_down are withheld: 74 training frames and 18 withheld frames per
unit. Neither image nor surface loss from heldout frames enters training or
checkpoint selection. All 15 clips are rendered and scored afterward.

## Results

Outputs are under
`artifacts/homm3_mocap_v2/skin_mesh_pilot/{thunderbird,shahrokh}/joint_axes_v1/`.
Each directory contains the canonical skin, frozen source locals/roots, learned
parameters/worlds, report, and every clip's comparison GIF and sampled sheet.
Columns are DEF source, current prepared, fixed source axes, learned static axes.

| Unit | Split | Current prepared IoU | Fixed source axes IoU | Learned axes IoU |
| --- | --- | --- | --- | --- |
| Thunderbird | Train (74) | 0.573914 | 0.513537 | 0.563908 |
| Thunderbird | Heldout (18) | 0.443003 | 0.401103 | 0.417011 |
| Shahrokh | Train (74) | 0.550028 | 0.501089 | 0.555747 |
| Shahrokh | Heldout (18) | 0.470200 | 0.457282 | 0.449715 |

Means weight each authored frame equally. Thunderbird improves the new
fixed-source baseline on withheld clips but remains below the existing prepared
result. Shahrokh improves training overlap while regressing withheld overlap.
Visual inspection of g00 movement and g11 heldout upward attack sheets found
incorrect wing/body action in both candidates; higher training fit is not
acceptable animation.

Learned axes reduce heldout stretch-violation fractions versus the new fixed
source baseline (Thunderbird 0.074009 to 0.059189; Shahrokh 0.129913 to 0.082408).
That improvement does not overcome the motion/appearance failure.

## Verification And Cost

Twelve focused tests passed, including whole-clip splits, finite gradient and
synthetic learning, immutable inputs, neutral/rigid invariants under nonzero
calibration, real canonical Thunderbird with arbitrary axes, and a deliberate
learner-output corruption that makes the weighted rigid control throw.

The final reports exercised learned parameters through source reconstruction,
calibrated FK, and weighted skinning on 13 synthetic neutral/rigid poses with
root travel. Maximum rigid errors were 1.63e-14 and 1.48e-13. Rotation-trace
error in float32 was 3.10e-6 for both real fitted runs. All pinned inputs and
implementation hashes were independently rechecked with zero mismatches.

Thunderbird selected step 244 and took 38.6915 seconds; Shahrokh selected step
246 and took 40.3002 seconds. Combined cached preparation/fit/render/control
time was 78.9917 seconds. This excludes original mocap, asset preparation,
engineering, export, and runtime validation; it is not end-to-end throughput.

Further work should not assume target mapping alone explains the remaining
failure. Validate the captured motion on the mocap donor's own actor before
adding another target-side calibration layer. Historical positive Roc skeleton
feedback is not proof that these newer bird captures are accurate.
