# HoMM3 Unit VFX Preview

## Purpose

Render an animation and a scheduled Unity effect from the `oldenera_factions`
Unity project without launching Olden Era. This is a visual iteration tool, not
a bundle-build, deployment, or gameplay path. A run captures a no-effect pass
and an effect pass at identical clip times, then composes those beside any
authored reference frames listed in the preview spec. Each sequence keeps one
camera framing; the sprite comparison uses a shared crop across the source
sequence to preserve motion around a stable pivot.

## Run

Prerequisites: Unity `6000.0.66f2` with a valid Editor license for batch mode,
the project at `oldenera_factions`, a graphics-capable editor invocation (do
not pass `-nographics`), and Pillow for the comparison GIF. Unity cold-imports
the selected project before running the preview, so use a project whose Library
cache is already warm for repeated iterations.

```powershell
py -3 tools/homm3_import/preview_unit_vfx.py
```

The default spec is `tools/homm3_import/beholder_electricity_preview.json`.
Override the Unity editor or provide another spec with `--unity-editor` or
`--spec`. Outputs are created under `artifacts/unit_vfx_preview/`; an existing
run directory is never overwritten. Source code remains under
`tools/homm3_import/unity_editor`; the runner mirrors that editor script into
`oldenera_factions/Assets/Editor` before invoking Unity.

Specs select a prefab, animation clip, unique attachment transform, sample
rate, camera, explicit reference-frame rate, and deterministic event times.
`loopClip` explicitly controls whether samples wrap; otherwise a sample past
the final key holds that pose. The comparison GIF distributes its 10 ms timing
units across frames to preserve the requested average output rate. An optional
`anchorViewOffsetRelativeToHeight` positions an effect origin in camera-space
right/up/toward axes relative to the unit height, while keeping it attached to
the selected animated transform.
`requireSkinnedMeshDeformation` also writes a larger `mesh_motion.gif` from the
effect-free Unity renders. For every sampled clip time, the Editor calls
`SkinnedMeshRenderer.BakeMesh` and compares vertices in each renderer's local
mesh space, first against frame 0 and then against the preceding frame.
Uniform translation of all vertices is removed before counting movement, so
camera motion, prefab root motion, and a whole-mesh translation cannot satisfy
the check; rigid rotation can still satisfy it. This is a baked-vertex motion
diagnostic, not proof of non-rigid deformation, source-action fidelity, or
visual acceptance. The Beholder fixture requires at least three attack
transitions in which 5% of its vertices (minimum 16) move by at least 1% of
the unit height and the maximum local residual displacement reaches 2% of that
height. The Python report validator repeats the threshold check before
composing GIFs.
Each preview accepts at most 32 scheduled events and requires every event to
overlap a rendered sample. `electricArc` supplies two deterministic, branched
bolt poses from the animated attachment, with a short reach and light pulse,
plus a Unity point light and a lit-only measurement pass that
hides the arc geometry while comparing illuminated mesh pixels to the same-pose
baseline. Its report records changed and brightened mesh-pixel counts; the run
fails unless at least 1% of the visible mesh (minimum 16 pixels) brightens by
more than 12/255 luminance. Because the exported `Hex/Lit` shader is a
non-lighting stub, electric-arc previews use temporary
Built-in Standard materials on the cloned preview unit, copying its base color
texture and tint. This is an editor-only lighting test, not material or lighting
parity with Golden Era.
`particlePrefab` loads a prefab containing Unity ParticleSystems and
re-simulates each scheduled event at fixed sample times; it requires an explicit
`effectBoundsMarginRelativeToHeight` so the camera reserves room around the unit
for particles beyond the mesh bounds. This is a centered estimate, not a fit to
the simulated particle bounds; increase it when the effect extends farther.
This first version does not execute arbitrary `MonoBehaviour.Update` logic or
VFX Graph simulation. Keep one-off runs short and inspect both `baseline` and
`effect` frame sequences; the report fails if a scheduled effect produces no
visible pixel change.

## Beholder Test

The default run pairs `Unit_AttackFront` with the seven CBEHOL DEF group 12
frames. The native electricity is composited through multiple setup, strike,
and recovery poses; frames 3-4 contain the forward discharge but are not the
only electrical frames. It is not a standalone effect asset. The current
single-event cyan arc attached to `mixamorig:Head` is only a lighting/render
prototype and does not reproduce the source effect timing or attachment. Its
light-only pixel-diff check is separate from visual acceptance.

The selected Beholder skinned prefab is a generated lab artifact and the active
candidate review marks its Mixamo-person adapter `needs_geometry_work`. Its
25-bone humanoid rig drives Hips, arms, and legs, not five independently
controlled Beholder tentacle chains. At the configured `cameraDirection` of
`+Z`, the render shows the rear rather than the source-facing eye; the earlier
180-degree diagnostic corrected facing but still folded the tentacles during
attack. The current `Unit_AttackFront` candidate retains a hanging silhouette
through the source's forward-thrust poses 3-4. It is rejected, not pending
visual review.

The Unity fixture's `SkinnedMeshRenderer.BakeMesh` measurement is only a motion
diagnostic: it removes mean vertex translation but does not remove best-fit
rigid rotation, and therefore is not proof of non-rigid skin deformation or
source-action fidelity. A separate local five-chain source-fit pilot reached
the correct facing but did not reproduce the source thrust; its generated
reels are rejected diagnostics under
`artifacts/homm3_beholder_attack_sourcefit_v1/final_preview_v3/`. The existing
34-joint five-chain mesh map is only a candidate rig, and the capture inventory
has no compatible donor motion. A source-backed seven-pose tentacle track is
still needed before this unit can pass animation review.

The Unity project's `Hex/Lit` shader is a local exporter stub. Standard preview
materials allow an actual Unity point light to illuminate the mesh, but this
conversion is isolated to the cloned preview unit and does not validate the
game's shader response.

## Current Validation

The v4 Unity Editor render proves that Unity can load and sample the prefab and
that its point light changes rendered mesh pixels. It does **not** pass
Beholder animation review. Although 8,405 vertices were baked and many moved
between samples, this count was not a quality gate and did not detect the
wrong facing, incompatible human rig, or missing source attack thrust. The
single procedural arc is also mistimed and attached to a generic head bone.
The five-chain source-fit pilot provides a synchronized diagnostic comparison,
but it still fails the thrust pose and is not a Unity delivery. No accepted
Beholder mesh animation or source-matched electricity reel currently exists.

## Proof

A passing run proves that Unity Editor loaded the selected prefab and clip,
sampled the requested times, rendered nonblank camera frames, and produced a
separate visible effect pass without an Olden Era process. For specs requiring
it, the baked-vertex report records local vertex changes after uniform
translation removal. Rigid rotation can satisfy this measurement; it does
not prove source-action fidelity or visual acceptance. The preview does not
prove runtime effect dispatch, gameplay timing, installed payload behavior,
or in-game animation playback.
