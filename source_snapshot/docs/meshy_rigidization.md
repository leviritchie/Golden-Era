# Meshy post-rig rigidization

Meshy auto-rigging is the armature authority for the scalable custom-unit
pipeline.  This stage does not replace that armature and does not infer a
second skeleton.  It consumes the Meshy-rigged GLB, corrects high-confidence
vertex ownership, and emits another GLB with the same Meshy armature.

## What it does

`tools/homm3_silhouette_pose_fit/rigidize_meshy_skin.py` imports the Meshy GLB
in Blender and:

1. Finds the single armature that owns the skinned mesh objects.
2. Reads the existing Meshy vertex groups and determines each vertex's
   dominant Meshy bone.
3. Builds same-owner connected regions from existing topology.  It does not
   weld vertices or merge nearby geometry, because an automatic weld can join
   a held prop to the body.
4. Freezes only regions whose existing weights provide a decisive single
   owner.  Every accepted vertex receives weight `1.0` from that existing
   Meshy bone.
5. Leaves mixed/flexible regions unchanged.
6. Fails closed when a region looks rigid-like but its attachment owner is
   ambiguous, unless the diagnostic-only `--allow-ambiguous` escape hatch is
   supplied.
7. Exports the Meshy armature, skin, textures, and animations, then re-imports
   the output and audits the exported artifact.

The result is rigid follow, not world-space freezing.  A sword still follows
the hand; its blade does not bend across the wrist or elbow.  A helmet follows
the head; it is not left behind while the head rotates.

## Run it

Use the host wrapper so Blender is explicit:

```powershell
py -3 tools/homm3_silhouette_pose_fit/run_meshy_rigidization.py `
  --src artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/rigged/idle_f0_rigged.glb `
  --out artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/rigged/idle_f0_rigged_rigidized.glb `
  --report artifacts/crusader_pose_pipeline/out_meshy_t2_idle_f0/rigged/meshy_rigidization_report.json `
  --config tools/homm3_silhouette_pose_fit/configs/meshy_rigidization_default.json
```

The source is never overwritten.  The report is the acceptance record.  A
passing report has `status: "pass"` and
`armatureAuthority: "meshy_auto_rig"`.

When `generate_meshy_t2_unit_master.py` downloads a Meshy rig, it now runs this
stage automatically unless `--skip-rigidization` is passed.  Auto-rigging is
the default; `--skip-rig` is an explicit mesh-only diagnostic path.
The raw Meshy GLB remains at `idle_f0_rigged.glb`; the audited output is
`idle_f0_rigged_rigidized.glb` and becomes the canonical `riggedGlb` in
`generate_meta.json`.

## Notebook integration

Run the notebook's executable cells in this order: asset selector, the
separate Meshy rigidization preflight, then configuration. The selector owns
the Mesh, Unit, and Animation choices. The preflight runs the host wrapper (or
reuses an adjacent passing artifact), derives all generated paths from the
selected GLB, and never overwrites the raw Meshy source. Do not paste a
literal placeholder such as ``<unit>`` into the notebook.

The rigidization cell exposes `RUN_MESHY_RIGIDIZATION`,
`MESHY_RIGIDIZATION_REUSE_PASSING`, `MESHY_RIGIDIZATION_OVERWRITE`, and
`MESHY_RIGIDIZATION_ALLOW_AMBIGUOUS`. It stores the audited output and report
in notebook variables; the following configuration cell forwards those
variables to `RocHybridConfig` only when they belong to the currently selected
source mesh.

```python
ASSET_SELECTION = ASSET_PICKER.config_overrides()
MESHY_RIGIDIZATION_REPORT = ASSET_SELECTION.pop("meshy_rigidization_report", None)

CONFIG = RocHybridConfig(
    **ASSET_SELECTION,
    meshy_rigidization_report=MESHY_RIGIDIZATION_REPORT,
    require_meshy_rigidization=True,
)
```

`initialize(CONFIG)` verifies the report schema, passing status, Meshy
authority, selected output path, and output SHA-256 before starting Blender
workers.  If the selected GLB is the raw or a stale rigidized file, the run
fails instead of silently fitting the wrong artifact.

## Acceptance and limits

The audit checks:

- Meshy bone names, hierarchy, and rest transforms remain unchanged within
  export precision.
- Skinned mesh objects are not lost and are not allowed to lose vertices.
- Accepted rigid owners still have at least the expected single-owner vertex
  coverage after glTF export/re-import.
- Existing Meshy animation actions are not lost.

Attribute-driven glTF vertex splits are allowed and recorded.  They are not a
rigging change; they are the exporter duplicating vertices with different
attribute tuples.

The classifier is intentionally conservative.  A low-confidence or mixed
region is preserved as flexible rather than guessed.  That is the correct
behavior for unattended batch processing: a unit can be rejected or reported
for policy tuning, but it cannot silently receive a wrong attachment bone.
The stage does not yet create child prop bones or split a plate that genuinely
crosses a joint.  Those are separate, explicit operations to add only when
the existing Meshy hierarchy cannot represent the attachment.

Proof level: generated artifact plus Blender re-import audit.  Unity import,
SkinnedMeshRenderer deformation, and in-game runtime behavior remain separate
proof gates.
