# Full-Hierarchy Anatomical Plane Trial

## Decision

No promotion. The explicit-plane method changes wing articulation, but the
movement and attack sheets for both birds remain unsatisfactory. This is a
controlled generated diagnostic, not accepted animation or runtime evidence.

## Method And Controls

The source positions and shared idle reference are unchanged. The method
separates body-hub rotation, transfers residual bone directions through explicit
source/target rest planes, reconstructs fixed-length target locals, then applies
one global body rotation and mapped root travel.

Plane hints are selected from corresponding source/target skeletal edges. The
search first excludes candidates degenerate in either rig, then chooses nearest
edge-graph distance, strongest minimum cross-product quality, and deterministic
name ordering. A straight terminal chain can use a measured body branch plane;
there is no world-axis or unit-specific substitute. Selection is static across
all frames sharing a reference and bind.

The comparison has four columns:

1. DEF source image.
2. Original prepared skin and original production motion reconstruction.
3. Canonical coincident-bind skin with existing body-relative reconstruction.
4. Exactly the same canonical skin with anatomical-plane reconstruction.

Only columns 3 and 4 isolate the plane-transfer change. Comparing directly
against column 2 also includes coincident bind and body-relative changes.

Thunderbird has one source-observable but target-collapsed terminal tail helper.
It is explicitly omitted only after proving zero target length, exact zero
skin-weight column, no children, and no body-hub membership. Weighted,
nonterminal, or body-hub collapsed edges still fail closed. The named omission
does not affect a rendered vertex and does not invent a captured direction.

## Results

Each unit covers all 15 groups and 92 authored frames. V3 output directories are
`artifacts/homm3_mocap_v2/skin_mesh_pilot/{thunderbird,shahrokh}/anatomical_v3/`.
Numbers below are frame-weighted means, not clip-weighted means.

| Unit | Variant | IoU | Stretch violation fraction | Compression violation fraction |
| --- | --- | --- | --- | --- |
| Thunderbird | Current prepared | 0.548298 | 0.067851 | 0.097783 |
| Thunderbird | Canonical body-relative | 0.547517 | 0.064122 | 0.087315 |
| Thunderbird | Canonical anatomical | 0.551347 | 0.056979 | 0.099658 |
| Shahrokh | Current prepared | 0.534410 | 0.085644 | 0.090021 |
| Shahrokh | Canonical body-relative | 0.543380 | 0.080555 | 0.066682 |
| Shahrokh | Canonical anatomical | 0.530846 | 0.106882 | 0.060371 |

Thunderbird gains a little overlap and reduces stretch, but compression worsens
against the isolated control. Shahrokh loses overlap and increases stretch.
Visual inspection of g00 movement and g12 front-attack sheets confirms that
neither result recovers a satisfactory source action. Anatomical graph geometry
alone is not a sufficient calibration signal for this cohort.

V3 processing took 23.9034 and 23.9138 seconds (47.8172 seconds total), excluding
engineering, original mocap, preparation, optimization, export, and runtime.
Earlier V1/V2 attempts failed before rendering because the hint selector ranked
ineligible nearest edges before filtering them. That implementation error was
fixed, and a straight-chain synthetic regression test now covers it. Those
partial directories are not completed results.

## Final Verification

Final outputs are each unit's `anatomical_v6/` directory. These preserve the
canonical skin NPZ and its hash plus full hint and inactive-leaf provenance.
The table above was independently recomputed from V6 and is unchanged.
All pinned input and implementation hashes were independently rechecked with
zero mismatches in both reports. All 30 clips completed.

The final pre-GPU control actually reconstructs 13 synthetic captures through
the anatomical method, then compares the weighted mesh against exact rigid
motion. It includes neutral, +/-45 and +/-90 degrees about each axis, and
nonzero root travel. Failure throws before rendering. This is distinct from
V4's earlier skin-only control, which constructed rigid palettes directly and
did not prove the motion reconstruction. V5 exercised reconstruction but did
not yet enforce failure; V6 is the final fail-closed runner.

Thunderbird neutral/rigid maximum coordinate errors were 1.89e-15 / 3.83e-15;
Shahrokh errors were 7.77e-16 / 4.33e-15. A test intentionally corrupts a
reconstructed joint world to verify that the control throws. Thirty-four
focused tests passed, including the earlier clipping diagnostic suite.

V6 processing was 26.9825 + 27.9596 = 54.9420 seconds, separate from prior
comparison runs and engineering time. These passing controls establish
mathematical/weighted-mesh invariants, not acceptable real animation.

## Remaining Work

Static plane correspondences now have a coordinate-consistent implementation,
but geometric correspondence is not visual calibration. A further candidate
must demonstrate source-image improvements on withheld motion while retaining
neutral mesh, rigid motion, and surface quality. Do not promote a mathematical
invariance fix or a small average-IoU gain as a satisfactory wingbeat. Keep the
full 21-unit Stronghold objective and cross-archetype checks; these birds remain
a shared-defect test, not the whole product.
