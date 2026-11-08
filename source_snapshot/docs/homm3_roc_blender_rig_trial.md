# Roc Blender Rig Trial

## Scope

This is a user-requested manual rigging diagnostic, not a new production
pipeline or evidence of autonomous processing for the full unit catalog.
The original move-pose T2 surface, UVs, textures and saved capture are retained
as a comparison lane. This trial also contains a generated separable
replacement surface; neither lane is a production deployment.

Artifacts and reproducible scripts are under
`artifacts/homm3_mocap_v2/roc_blender_rig_v1`.

## Authorship

`author_rig.py` runs in official portable Blender 4.5.13 LTS. It imports the
original GLB, creates a new 16-bone armature in edit mode, assigns anatomical
vertex groups and an armature modifier, and saves actual animation keyframes
in `roc_authored.blend` and `roc_authored_animated.glb`.

Bone pivots were authored against six textured coordinate views of this exact
mesh. The body, neck, head, tail, three supports per wing, and three supports
per leg are independently controlled. Weights use authored anatomical regions
and spanwise feather supports rather than the earlier automatic skeleton or
nearest-joint assignment. Geometry is unchanged; fused surfaces remain fused.

## Motion Boundary

The input is the existing linked v2 capture: 66 frames, including five idle
bookends, with Move frame zero (global index 12) as the reference. The preview
contains the nine original clips and 61 authentic frames. Source timing is
12 fps, obtained from the pinned master rather than hard-coded preview speed.

This is a simplified direction retarget, not identical playback of the old
50-joint rig. Each authored bone receives the global swing of its declared
source segment relative to the reference. Parent compensation preserves the
authored bone lengths. Root translation is held; axial twist and finer donor
articulation are not reconstructed. There is no per-clip corrective pose or
motion smoothing. Linear key interpolation is used between saved samples;
quality claims concern the actual sampled frames only.

Only the proper capture-to-mesh orientation is reused from the old alignment.
Its scale, translation and anatomical joint placement are not reused.
Mesh, capture and master hashes are checked before authoring.

## Verification Status

Blender authoring and export completed. The reference-pose maximum vertex
error is below 0.000001 mesh units. Independent review found and corrected
a preview timing mismatch and missing input hash verification.

Fresh-file readback passed at frames 1, 13, 16, 53 and 66: maximum scene
evaluation difference was 0.000001904 mesh units. Exported GLB reimport also
passed sampled nearest-vertex geometry parity (maximum 0.000023843), with
16 joints and all 13,000 triangles retained. This is sampled geometry parity,
not a persistent vertex-identity or visual-quality guarantee.

The authoritative preview is `animation_preview_v2/full_reel.gif`, with nine
individual clip GIFs beside it. It shows source, new-rig side view and new-rig
front view. Source and mesh are independently framed, not registered overlays.
The 61-frame reel lasts 5,080 ms versus 5,083.33 ms ideal, within GIF timing
quantization. Nonblank textured renders and unchanged input hashes passed.
The earlier `animation_preview` folder is superseded: it used incorrect
100 ms timing and was produced across an authoring rerun.

Visual inspection shows that rigging alone has not solved the result: idle
has excessive upward head/body orientation, wings remain angular and do not
fold to the source silhouette, and flight poses differ from the sprites.
The preserved generated bind itself differs from the source wing pose; rest
identity therefore does not imply source-pose agreement. This candidate is
unaccepted and must not be selected for production delivery. A next iteration
must distinguish mesh bind-pose correspondence and motion retargeting from
weight quality rather than adding clip-specific corrections indiscriminately.

## Wing-Plane Follow-Up

`wingplane_v1` is a bounded follow-up, not a replacement for the first trial.
It keeps the same mesh, weights, source frames and 16-bone armature, but uses
non-collinear wing landmarks to construct a per-segment plane basis. This
addresses the specific limitation that a direction-only swing cannot determine
feather-plane roll. The preview is
`artifacts/homm3_mocap_v2/roc_blender_rig_v1/wingplane_v1/animation_preview_v2/full_reel.gif`.

The wing-plane result improves wing orientation in several flight and
front-view samples, but still shows dark, spiky feather separation and
incorrect source silhouettes in other clips. It remains an unaccepted
diagnostic; no production files were replaced.

## Grounded Fold Follow-Up

`groundfold_v1` through `groundfold_v4` add a generic compact-upright detector
based on source silhouette aspect ratio and capture body posture. It folds
the wing chain toward authored flank targets only when the source supports a
compact grounded state; flight frames continue to use the wing-plane basis.
The final v4 also uses the authored forward neck direction for confidently
compact states, correcting the donor landing capture's raised-neck bias.

Preview: `artifacts/homm3_mocap_v2/roc_blender_rig_v1/groundfold_v4/animation_preview_v2/full_reel.gif`.
The final v4 is visibly closer in idle and mouseover: beak orientation is
forward, wing mass is gathered nearer the flanks, and the front projection is
narrower. It remains a diagnostic rather than an acceptance candidate because
the mesh still has angular feather separation and several action silhouettes
remain unlike the sprites. No clip name is used as the folding switch.

The subsequent `groundfold_v5` pass is the current best of this bounded run:
it retains the wing gather while compacting the neck and keeping the beak
forward. `groundfold_v6` tightened the wing target further and visibly
over-folded the primaries into thin downward spikes, so it is retained only as
a negative comparison. Use the v5 reel for review:
`artifacts/homm3_mocap_v2/roc_blender_rig_v1/groundfold_v5/animation_preview_v2/full_reel.gif`.

`groundfold_v7` tried the opposite correction by lifting the folded primaries
along the flank. It produced an obvious raised-feather fan and is also a
negative comparison. The reproducible default remains the v5 target profile;
the tighter and lifted profiles are explicit experiment switches.
The v5 Blender scene and exported GLB passed the existing independent readback
checks; the result remains visual-diagnostic evidence only.

`groundfold_v8` tested a Blender corrective shape key that shrinks authored
wing-panel vertices in compact states. It produces a modestly narrower idle
silhouette. Blender's first GLB export omitted the node `weights` channel for
that shape key, which was caught by sampled reimport parity rather than being
silently accepted.

The bounded post-export repair is now implemented in
`artifacts/homm3_mocap_v2/roc_blender_rig_v1/patch_dense_morph_animation.py`.
It verifies the handoff mesh, capture, master, and every source-sprite hash
before patching. The Blender export had placed the shape-key channel in a
secondary action; the repair adds one dense 66-sample FLOAT accessor and one
`weights` channel to the primary animation, preserving the existing skin
animation and source timing while refusing to duplicate the primary channel.
The
repaired artifact is
`artifacts/homm3_mocap_v2/roc_blender_rig_v1/groundfold_v8/roc_authored_dense_weights.glb`.
Independent Blender reimport passed at frames 1, 13, 16, 53 and 66, with
maximum symmetric nearest-vertex error 0.0000254 mesh units; an exported-GLB
evaluation render also completed with 61 source frames at 83.333 ms timing.
This proves serialization and playback parity for the diagnostic artifact,
not visual acceptance. The v5 result remains the simpler validated visual
candidate, while v8 is now a valid export experiment rather than a broken
file.

## Replacement-Surface Prototype

Because the T2 surface remains fused at the wing/body boundary, a bounded
replacement experiment is available through
`build_roc_custom_mesh.py` and `make_custom_handoff.py`. It creates one
separable mesh with a rounded body, upright neck/head, independent tail and
bilateral feather blades, then reuses the same capture, detector, armature and
12 fps frame contract through `ROC_HANDOFF`.

The current prototype is intentionally a construction proxy, not an accepted
asset. Its broad overlapping blades are controllable, but the body and wing
surface still need a more faithful raptor silhouette and textured appearance.
The current custom sequence is `groundfold_v37_custom` through
`groundfold_v40_custom`; v40 adds a fold-only feather-drop shape key so open
wing positions remain unchanged. The latest full animation preview is
`artifacts/homm3_mocap_v2/roc_blender_rig_v1/groundfold_v40_custom/animation_preview_v17/full_reel.gif`.
The replacement handoff records real node identities and separate local and
transformed bounds. Component diagnostics round-trip sidecar coordinates
through the glTF node and Blender axis conversion, and the export no longer
contains appearance-bearing vertex colors. These are generated-artifact and
animation-render checks only; visual acceptance and production deployment
remain unproven.
