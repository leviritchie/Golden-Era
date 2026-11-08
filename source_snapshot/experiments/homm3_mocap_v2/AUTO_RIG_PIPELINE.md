# Sequence-Aware Auto-Rig Pipeline

This lane is the deterministic alternative to manual per-unit review. It uses
the frozen mocap skeleton as the motion owner and treats any embedded SmartRig
weights or a camera-free geometric initializer as an explicit starting point.
The optimizer may redistribute only the declared sparse support; it cannot
invent motion, change the skeleton hierarchy, or use image IoU as a deformation
shortcut.

## Cycle

1. Run the same corpus clips, camera, raster, and retarget policy for a matched
   SmartRig baseline and an auto-rig candidate.
2. Split the corpus into explicit fit and held-out validation clips. Fit the
   candidate weights across the fit 3-D mocap frames with local-
   global ARAP, edge/area preservation, sparse-support smoothness, and a
   per-vertex motion-retention prior. Optional geometric initialization and
   mocap-targeted segment/vertex trajectories are deterministic; regions are
   assigned from bind-pose bone proximity before optimization, never from the
   optimized weights.
3. Emit `weights.npz`, an optimized GLB, a report, a preview, and explicit
   candidate provenance. Reload the GLB and compare bind transforms, topology,
   UVs, weights, vertices, and sampled deformations against the in-memory
   result before the report can pass.
4. Run `auto_rig_quality_gate.py` against the matched baseline. Promotion
   requires absolute bind, motion-retention, geometric articulation,
   collapse, stretch, export, and matched-view non-regression floors plus a
   minimum held-out improvement over the baseline. An inconclusive candidate
   is rejected rather than selected as the least-bad result.

Image-space silhouette/chroma remains a secondary validation lane. It is not
allowed to override the 3-D motion and topology gates. A failed vendor rig or
missing topology is therefore visible in provenance and cannot silently become
shipping proof.

## Castle SmartRig modifier pilot

`run_smartrig_modifier.py` is the first Castle-wide deterministic lane. It
loads the authored Castle profile and frozen mocap corpus, keeps the source
SmartRig rest surface as the bind baseline, preserves texture, bind, and motion
authority, and learns only a sparse weight field from 3-D local-global ARAP, edge/area preservation,
support smoothness, and camera-free articulation targets. The run declares
`llmInLoop=false`, emits one candidate GLB per corpus clip plus comparison GIFs,
requires complete hash coverage for every referenced source frame, and performs
serialized GLB readback of hierarchy, bind arrays, weights, and animation
accessors before writing `report.json`. The solver and preview use dual-quaternion
skinning; the emitted GLBs intentionally use standard glTF linear-blend
skinning, so the report marks export parity as `not_equivalent` rather than
silently treating the preview as runtime playback.

Validate a completed run with:

```powershell
python experiments/homm3_mocap_v2/validate_smartrig_modifier_report.py `
   artifacts/homm3_mocap_v2/smartrig_modifier/castle/h3_archer/sequence3d_v11/report.json
```

The six-unit Castle pilot inventory and pinned report hashes are recorded in
`castle_smartrig_modifier_manifest.json`; it covers Archer, Crusader, Marksman,
Pikeman, Monk, and Swordsman (96 clip exports total).

The modifier now has an autonomous topology-repair stage. It detects persistent
or catastrophic high-strain edges with incompatible endpoint weights, then
splits only high-confidence two-face seams into per-face vertices. Each split
keeps the bind surface and UVs unchanged while assigning the face-local copies
the neighboring third-vertex ownership. This addresses fused hand, weapon, and
garment bridges that no static weight field can satisfy. The repair is bounded
(`maxCuts=256`), selects non-conflicting faces, passes a post-split strain and
collapse gate, is recorded in `meshTopologyRepair`, and is rechecked from the
serialized GLB; no unit-specific mask or LLM decision is involved. A rejected
split is retained only as provenance and cannot alter the emitted candidate.

For review renders only, Move and Attack/Shoot clips use the established
Stronghold world-rotation exaggeration profile (`gain=2.20`); Idle, transitions,
and other preserve clips stay at gain 1.0. This is a rotation-only preview
style: raw mocap joint positions are retained, so it is not a second FK solve.
The raw mocap solve and GLB animation authority remain unchanged. The modifier
is a generated candidate, not runtime or visual-acceptance proof; promotion still
requires a separate visual review and delivery gate.

## Current Behemoth pilot

The first controlled pair uses yaw 76 degrees, pitch 14 degrees, and a
512-pixel raster. The old accepted master is the embedded-skin baseline. The
reports under `diagnostics/behemoth_motion_investigation/ab_*_v*_512/` are
generated artifacts only and are not runtime or visual-acceptance proof. The
current blend pilot passes the deterministic 3-D gate (including a held-out
surface-strain improvement), but Astra's visual review rejected its ragged
shoulder/back silhouette; no shipping promotion has been made.
