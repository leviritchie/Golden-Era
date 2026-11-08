# Shape-preserving rig adaptation

Generated-artifact lane. Not Olden Era delivery. Not a Crusader mocap claim.

This is the **fifth** mocap_v2 state. It does not replace and must not overwrite:

- the mocap-only baseline
- the intermediate-skeleton pilot
- the Eagle-skinned Roc **copy** (`eagle_skin_v1` failed, `eagle_skin_v2` frozen as a historical conformed-mesh comparison)
- historical weave / recipe runs

v1 and v2 stay as comparisons. Do not rerun v2 to pick up later handle-order changes.

## What this lane does

Fit the **capture skeleton** to the **original character**. The visible mesh, UVs, textures, and materials stay where they were.

The deformation rig keeps the donor’s joint names and parent graph. Bind lengths and joint placements are taken from the target. Weights move through a **hidden** donor surface that is allowed to distort. That surface is not exported.

Motion is capture-relative directions on the fitted bind, with fixed target bone lengths. It is **not** exact-joint replay (historical experiment B). One verified captured idle is paired with the target bind and reused across clips. A clip's first frame is never automatically redefined as the bind.

## Shared idle calibration

The original `shape_preserved_v1` animation used donor rest as its reference.
That was not the posture represented by the preserved target mesh. The attack's
first sprite is pixel-identical to standalone idle, yet the old mapping applied
almost 178 degrees of local rotation at that frame.

`idle_calibration.py` freezes a shared captured-idle reference with source-image,
capture, topology, and frozen-skin provenance. The runner checks it on every clip
and tests that this reference reproduces original vertices before rendering or
export. Missing or changed provenance is an error, not a reason to recalibrate
silently. Flight uses the same reference and must retain its nonidle posture.
Coincident donor hubs have no observable direction and are explicitly excluded
from direction correspondence and angular-motion metrics; separating those hubs
or collapsing a nonzero donor bone is rejected.

The September 6 generated-artifact check reconstructs idle with maximum vertex
error about `1.15e-15`, without changing preparation, geometry, or skin weights.
This proves the idle-reference correction, not acceptable animated deformation:
flight still has severe shape distortion. Keep weights, bone-frame transfer,
and high-angle deformation as separate unresolved questions. Nothing is deployed.

Serialized animation was also replayed through the GLB loader for every key:
24 attack frames and 6 flight frames match the CPU preview within `1.40e-7`.
The exported attack idle differs from the original by about `4.96e-8`, below
the `2.84e-5` mesh-relative gate. `verify_calibrated_export.py` now runs after
export in the motion runner, including a source-time-axis check. These are
generated artifact checks, not engine/runtime or visual quality approval.
The focused `controls` suite passes 30 tests, including stale/tampered reference,
nonidle-start, coincident hub, serialized rotation, and timing negatives.

Current review outputs: `motion/roc_attack/idle_calibrated_v2` and
`motion/roc_flight/idle_calibrated_v2` below the Roc asset directory. Attack has
a separate `serialized_animation_parity.json` readback report. Correctly labeled
four-column sprite/before/calibrated/original GIFs are in
`diagnostics/{roc_attack,roc_flight}/idle_calibrated_v2` below that same directory.
The earlier root-level `diagnostics/h3_roc/.../idle_calibrated_v1` comparisons
show a capture skeleton, not a sprite, in column one; they are historical.

Run `run_shape_preserved.py controls` for the regression suite. The same idle
identity and provenance gates run in `motion` before GLB export. Use new run
names such as `idle_calibrated_v2`; existing output directories are immutable.

## Spaces

| Space | What lives there |
| --- | --- |
| Capture space | Saved `pred_position`, donor BVH offsets. Immutable. |
| Target bind space | Original visible vertices and the fitted `deformation_bind`. |
| Presentation | Shared camera in target bind space. Green capture is root-aligned with one whole-body rotation and **no** baked scale. |

Coordinate normalization is allowed only when it is explicit and reversible. Nonrigid deformation is not baked into the visible mesh.

## Commands

Use the experiment venv.

```
artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/run_shape_preserved.py describe --asset h3_roc
artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/run_shape_preserved.py stamp-semantic --asset h3_roc
artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/run_shape_preserved.py prepare --asset h3_roc --run-name shape_preserved_v1
artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/run_shape_preserved.py actuation --asset h3_roc --run-name shape_preserved_v1
artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/run_shape_preserved.py motion roc_flight --run-name shape_preserved_v1
artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/run_shape_preserved.py motion roc_attack --run-name shape_preserved_v1 --allow-holdout
artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/run_shape_preserved.py describe --asset h3_crusader
artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/run_shape_preserved.py stamp-semantic --asset h3_crusader
artifacts/homm3_mocap_v2/venv/Scripts/python.exe experiments/homm3_mocap_v2/run_shape_preserved.py crusader-control --run-name shape_preserved_v1
```

Writes go under `artifacts/homm3_mocap_v2/shape_preserved/`. Writes under `eagle_skinned_roc/` are refused. Run names `eagle_skin_*` are refused.

Preparation is timed separately from clips. Reconstruct + GIF must stay under 600 seconds. Each asset may use at most three hidden-proxy registration revisions.

The hidden proxy starts from articulated LBS into the fitted bind. Regions that already correspond stay pinned. Regions with unmatched vertices then get region-constrained ARAP plus extra hole handles. The whole donor is not shrink-wrapped onto the closest target vertex.

Correspondence distance is capped at `0.12 ×` the target bounding-box diagonal. That cap is the distance gate; a tight median must not hide remaining holes that are still inside it, and a huge median must not accept a misplaced proxy. Thin two-sided sheets may match the opposite facing within `0.08 ×` that diagonal. Torso vertices cannot take neck/head/beak weights. UV-split copies of the same sheet (same position, region, and facing) share weights.

Motion uses capture-relative bone-frame directions on the fitted bind, plus one whole-body rotation for the overlay. The current rotation-only export refuses captures with root translation relative to the shared idle reference, rather than showing preview motion that the GLB would omit. It does not aim fitted bones at unscaled capture world directions.

## Gates

- **Static:** original vs bind-skinned vertices within `1e-5 × bbox diagonal`; UVs and albedo unchanged; own-bind identity; export reload vs original.
- **Rig:** full donor joint coverage, consistent branch attachments, no left/right swap, nondegenerate articulated segments. Wing 03 still splits to 04 and 05–06.
- **Weight:** finite, normalized, complete coverage. Unmatched correspondence fails closed. No nearest-bone fallback.
- **Deformation:** isolated actuator tests before full clips.
- **Motion:** saved green capture, adapted directions, positional residual reported as a proportion difference.
- **Reuse:** Crusader uses the same `prepare()` with a metadata profile and known synthetic motion. That is a skinning control, not mocap recovery.

`ok: true` means execution completed. `visualAcceptance` stays `unreviewed_candidate` until the user accepts the GIFs.

## Proof

generated-artifact only. Original Meshy assets are not modified. Nothing is deployed to Olden Era.
