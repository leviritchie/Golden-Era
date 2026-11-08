# Meshy External Chrome Download Proof

**Date:** 2026-08-11  
**Evidence:** completed browser workflow plus direct Playwright download event  
**Pilot:** `h3_archer`

## Proven route

The in-app browser could complete Meshy generation, texturing, remesh, and
SmartRig, but its download action did not produce a file through Playwright,
DOM-level CUA, or coordinate-level CUA. A separate persistent Chrome profile
with a normal logged-in session succeeded:

1. Open Meshy workspace in external Chrome.
2. Select `Animate`.
3. Select the completed SmartRigged archer asset.
4. For a new rig, choose `Smart Rig (Beta)` directly. Do **not** choose
   `Humanoid` or `Quadruped Dog`; those are the manual rig path, not a
   character-type prerequisite for Smart Rig.
5. Click `Confirm` once and monitor the resulting job until it is complete.
6. Click the viewer `viewer-download-btn`.
7. Leave `GLB` selected in Download Settings.
8. Await the Playwright `download` event and save the file.

## Pilot artifact

- Output: `artifacts/meshy_downloads/h3_archer_smartrigged.glb`
- Suggested Meshy filename: `Meshy_AI_Character_output.glb`
- Size: `56,796,588` bytes
- SHA-256: `9414C966523CEF65AB9298A16D2B36FE3D622D5354745406C0F2320A62301111`
- SmartRig geometry shown in Meshy: `9,024` faces, `4,477` vertices

## Operational consequence

The overnight workflow should use a persistent authenticated Chromium
session for the export stage. The 2026-08-11 archer pilot used external
Chrome. The 2026-08-17 Goblin pass proved the same GLB download through
Playwright MCP Chromium (`viewer-download-btn` → Download Settings `glb` →
`Meshy_AI_Character_output.glb`). Batch processing remains unproven. Do not
retry Remesh or Texture Confirm when the settings dialog stays open.

## Critical submission warning

Meshy may accept a paid operation while leaving its configuration dialog open
and without showing the expected `Task created successfully` toast. The open
dialog is **not** evidence that the operation failed. Never click `Texture`,
`Generate`, or another paid-action button a second time merely because the
dialog remains visible or the toast is missing.

After one paid-action click, the procedure must inspect the account credit
balance and the asset/task list. A new progress entry or a credit decrease is
submission evidence. If the UI is ambiguous, stop and inspect; do not retry.
Duplicate texture submissions can charge the account twice and create two
parallel jobs for the same source mesh. Duplicate remesh submissions are
also forbidden: remesh is often 0 credits, so the balance will not warn you,
and the dialog commonly stays open after a successful submit.

## Asset identity gate

After a model or texture job completes, do not open the next operation from
whatever remains selected in the viewer. Return to the asset grid, explicitly
select the intended task card, and verify its geometry/operation state before
opening `Texture`, `Remesh`, or `Animate`. The viewer can remain on a previous
asset while a newly submitted job is processing, and its controls can still
look valid. A balance change proves that a paid submission was accepted; it
does not prove that the submission targeted the intended asset.

In particular, an already-textured result must never be sent through
`Texture` again merely because the newly generated model is not visibly
selected. If task identity cannot be mapped confidently to the source
creature, stop at inspection rather than guessing.

## Smart Rig UI distinction

`Smart Rig (Beta)` is a separate choice from the `Humanoid` and `Quadruped
Dog` manual-rig choices. The batch procedure must click `Smart Rig (Beta)`
instead of either manual option. A failed Smart Rig job must be recorded as a
Smart Rig failure; do not silently switch to manual markers.

## Batch handoff note

During the August 12 batch, `h3_centaur_ranger` and `h3_cavalier` were
downloaded manually by the user after the browser automation path reached
those assets. They are completed handoffs, not proof of an automated download
for those two files.
