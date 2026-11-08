# HoMM3 Meshy-7 Coverage Rollout

This lane inventories the source-defined HoMM3/HotA manifest plus the neutral
catalog, then generates only units that have no own mesh. Exact
`<unitSid>_smartrigged.glb` files under `artifacts/meshy_downloads/` are the
only files counted as SmartRig coverage; `_WRONG`, legacy, and placeholder
files are evidence, not coverage.

Current source/static inventory (`tools/homm3_meshy_frame_pose/audit_homm3_mesh_coverage.py`):

- 275 distinct unit slots (262 import-manifest entries plus 13 neutral-only entries).
- 246 exact SmartRig GLBs.
- 29 own meshes without a named SmartRig: the pinned `toa_boar_rider` mesh plus
  28 generated Meshy-7 meshes. The boar rider is pinned by
  `experiments/homm3_mocap_v2/asset_profile_boar_rider.py`; the generated
  meshes remain unpromoted until the Luna/Blender handoff is complete.
- Four non-promoted Blender envelope-rig candidates are now tracked
  separately by the audit: `toa_boar_rider`, `h3_water_elemental`,
  `h3_phoenix`, and `h3_sharpshooter`. Their bind/readback checks pass, but all retain
  `accepted=false` until deformation and animation-pipeline review.
- No source-defined slot is currently missing a mesh. The thirteen
  neutral-only slots were extracted from `H3sprite.lod` by
  `extract_neutral_mesh_inputs.py`; all 28 gaps were then queued and downloaded
  with the Meshy-7 policy below.

Run the audit before changing the queue:

```powershell
python tools/homm3_meshy_frame_pose/audit_homm3_mesh_coverage.py
```

Meshy-7 generation is isolated from rigging in
`tools/homm3_meshy_frame_pose/generate_missing_meshy7.py`. It uses the
soft-lit source still, `ai_model=meshy-7`, textured standard topology,
adaptive-medium remesh, PBR maps, `remove_lighting=false`, and writes each
result beneath `artifacts/meshy_downloads/meshy7_missing/<unitSid>/`. The
script never writes a SmartRig path. Start and poll are separate operations:

```powershell
python tools/homm3_meshy_frame_pose/generate_missing_meshy7.py --start --parallel 4
python tools/homm3_meshy_frame_pose/generate_missing_meshy7.py --poll --parallel 4
```

Neutral-only inputs can be reproduced without writing through the read-only
Unity junction:

```powershell
python tools/homm3_meshy_frame_pose/extract_neutral_mesh_inputs.py
```

The queue is idempotent across API poll responses (`id`) and launch envelopes
(`taskId`), and recognizes an already-downloaded `mesh.glb` before creating a
new billable task.

Rigging of generated meshes is a separate Luna/Blender handoff. A generated
Meshy mesh is not promoted until the rig candidate has a source/output hash,
bind/topology/weight readback, and an animation-pipeline preview. Runtime
installation remains a later, explicit delivery gate.
