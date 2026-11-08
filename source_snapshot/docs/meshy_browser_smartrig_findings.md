# Meshy Browser Smart-Rig Findings

**Date:** 2026-08-16  
**Evidence level:** authenticated browser-session observation plus downloaded GLB validation  
**Credits used:** no paid Texture or Model operation during the corrective run; the corrective remesh reported cost 0  
**Account/session testing:** performed in the existing signed-in Chrome tab

## Confirmed browser shape

Meshy documents the browser workflow as a single workspace rather than an API
equivalent:

1. Open the Meshy workspace and use the **Model** section to upload an existing
   mesh, or create a model through Image to 3D / Text to 3D.
2. Open the uploaded/generated asset in the workspace viewer.
3. Switch to **Animate**.
4. Start rigging, inspect the result in the viewer, choose a motion when needed,
   and export the rigged asset as GLB or FBX.

The current interface documentation describes a left navigation area with
**Assets**, **Model**, and **Animate** modes, a center 3D viewer, and a right
asset/history panel. Meshy also says that model versions remain traceable in
My Models, which is important for preserving the pre-rig source.

## Smart-rig implications for this project

The browser path appears to keep upload, pose estimation, rig generation,
preview, animation selection, and export inside one workspace session. That is
consistent with the observed failure mode where an API or mixed workflow does
not reproduce browser SmartRig behavior.

However, the public material does **not** establish that browser SmartRig is a
valid ship path for the Olden Era units. Meshy’s own API documentation still
limits auto-rigging to clearly structured humanoids, rejects untextured or
non-humanoid inputs, and documents a 300,000-face limit. The product pages make
broader marketing claims, but they are not sufficient proof for roc, beholder,
or other non-humanoid delivery.

This repo’s locked pose contract remains unchanged: Meshy supplies mesh and
textures; the project owns the bind skeleton and skin; delivery requires a
SkinnedMeshRenderer with owned bone clips. A browser SmartRig result can be
examined as a reference or transition artifact, but it must not silently
replace the owned-bind gate.

## Preflight gates, without spending credits

The next browser-only learning session should stop before any paid operation:

- Confirm whether an existing uploaded GLB appears in **Model** and can be
  opened in the viewer without starting generation.
- Record the exact labels and order of the **Animate** / SmartRig controls.
- Determine whether the browser exposes character-type selection, pose markers,
  orientation controls, or a preview-only rig step before credit confirmation.
- Check whether an already-created asset can be duplicated/versioned before
  rigging, so the source GLB remains untouched.
- Record the displayed credit cost and confirmation point, but do not press the
  final rig/animate action.

Do not upload a project master or click a paid control until the credit cost
and resulting artifact contract are explicitly recorded. In particular, a
low face count is not sufficient evidence that a candidate is textured.

## Sources

- Meshy web quick start: https://docs.meshy.ai/en/webapp/getting-started
- Meshy web interface tour: https://help.meshy.ai/en/articles/12618267-meshy-interface-tour-workspace-tabs-and-navigation
- Existing-model animation help: https://help.meshy.ai/en/articles/9992032-is-it-possible-to-upload-my-existing-model-for-animation
- Meshy rigging API constraints: https://docs.meshy.ai/en/api/rigging
- Meshy animation product overview: https://www.meshy.ai/features/ai-animation-generator/

## Status

This is now a browser-workflow research note with an authenticated corrective
Smart Rig run. The browser path and downloaded artifact are proven for the
pilot below; this does not promote Meshy Smart Rig to the project's owned-bind
delivery authority.

## Authenticated-session procedure correction (2026-08-16)

The following sequencing rule is now mandatory for the browser workflow:

1. Select the remeshed, textured asset, then open **Animate** and click
   **Rig**.
2. In the **Rig Model** dialog, explicitly select **Smart Rig (Beta)**.
   The dialog also offers **Humanoid** and **Quadruped Dog**. Opening the
   dialog does not select Smart Rig. Smart Rig must be selected before the
   confirmation action; do not click through the default Humanoid path.
3. Verify the Smart Rig tile is visibly selected and that the dialog changes
   to the Smart Rig state with **Confirm** before clicking **Confirm** once.

Do not infer Smart Rig from the presence of the Rig dialog, the enabled Next
button, or a completed rig job. Any output for which the explicit Smart Rig
selection was not observed is unverified and must be re-rigged from the
remeshed textured source before download.

Paid-step safeguards remain mandatory: click **Texture** exactly once per
source asset, set **4K**, and never retry Texture merely because its dialog
remains open. Before remeshing, select the colored textured high-poly result
and verify its high face count and material-map controls. After remeshing,
verify the new low-poly result is still visibly colored and exposes the
material maps before opening **Animate**. Never rig a low-poly result merely
because it has the expected face count: the untextured and textured remeshes
can both satisfy that numerical check. On 2026-08-17 the first Pikeman remesh
was gray metal at ~10k faces (untextured generate). The corrected remesh of
the 4K textured high-poly stayed blue/gold with Base Color maps at 10,054
faces. Grid `x12` is not a texture proof by itself; open the card and check
paint.

**Remesh Confirm is one-shot even at displayed cost 0.** Meshy may accept
Remesh while leaving the Remesh dialog open and while the viewer still shows
the old high-poly face count. That is not a failed click. After one Confirm,
wait for a new asset card or a progress percent on that card. Do not click
Confirm again because the dialog stayed open, the viewer still shows ~2M
faces, or credits did not change. Duplicate Adaptive/Medium remeshes of the
same Goblin source on 2026-08-17 produced two ~9.8k colored meshes; credits
stayed at 1,430 because remesh was free. The Smart Rig result is a later
card (~9.9k faces, skeleton, no `x12` badge) and is not the duplicate remesh.

**Playwright submit check:** a locator click that leaves the dialog open is
ambiguous. Treat a new card, progress percent, or a single `/remesh` POST as
submission evidence. Do not retry Confirm to “make sure.” Image-to-3D idle
inputs for missing catalog units are
`artifacts/creature_aaa_3d_upscale/<unitSid>.png` (259 of 262 present;
`h3_water_elemental`, `h3_ice_elemental`, and `h3_frost_elemental` have no
final upscale). Download GLB through Playwright is proven for
`h3_goblin_smartrigged.glb` (2026-08-17).

## Confirmed corrective run (2026-08-16)

`h3_serpent_fly` exposed the failure mode described above. The initially
selected 11,608-face remesh was visibly untextured and still offered the
**Texture** action. It was not used for the corrected rig.

The correction used the colored Meshy 7 textured high-detail source
(`01a00889-26d6-7597-8dca-0f53a7c8f0dc`, 1,999,162 faces), remeshed it with
**Adaptive / Medium / Triangle** at displayed cost `0`, and verified the new
11,639-face result was colored before rigging. The **Smart Rig (Beta)** tile
was visibly selected before **Confirm**. The completed result showed the
automatic skeleton, had 11,658 faces, and produced a valid GLB download:

`artifacts/meshy_downloads/h3_serpent_fly_smartrigged.glb`

The file was fetched from the signed Meshy asset URL with HTTP 200, had a
matching stored byte count of 61,845,336, and began with the GLB header
`glTF`. This is the one confirmed untextured-source outlier from the current
audited h3 subset; every remaining candidate must pass the texture gate above
before another rig action is allowed.

The initial 2026-08-16 audit found 57 final files created in the smart-rig
storage folder. After the first corrected halcyon download, the folder contains
58 final files: halcyon is now explicitly Smart Rig verified, while the other
57 files remain unverified until they pass the selection gate above. Filenames
alone are not compliance evidence.
