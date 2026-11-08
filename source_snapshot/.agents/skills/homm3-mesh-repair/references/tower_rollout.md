# Tower Mesh-Repair Rollout

This is the user-directed Tower override for `homm3-mesh-repair`, not a new
motion source or a waiver of provenance. Source roster: `custom_factions/homm3_tower.json`
(`unitLines` and `unitVariants`). One unit is one owning worker and one complete
equipped mesh animation result. The base Mage and base Stone Gargoyle have already
had dedicated passes; do not silently treat the old fleet `candidate_reviewed`
status as a completed repair for any other unit.

Portraits are local, not a web-search task. Inspect
`Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_portraits/`
and its `manifest.json` `interfacePortraitSources` before preparing a mesh input.
The base and upgrade files use their game SIDs directly. Alternate game SIDs use
these portrait aliases: `h3_gremlin_mechanic` -> `h3_gremlin_upg_alt`,
`h3_elemental_gargoyle` -> `h3_gargoyle_upg_alt`, `h3_magnetic_golem` ->
`h3_golem_upg_alt`, `h3_battle_mage` -> `h3_mage_upg_alt`,
`h3_genie_vizier` -> `h3_genie_upg_alt`, `h3_naga_rani` ->
`h3_naga_upg_alt`, and `h3_colossus` -> `h3_giant_upg_alt`. Check the
actual PNG and manifest source bytes, not a portrait index. The internet is
for attributable high-resolution original-artist renders; use the exact local
portrait plus battle sprites as the baseline when no such render is found.

## Dispatch And Escalation

- Pending: `h3_gremlin`, `h3_gremlin_upg`, `h3_gremlin_mechanic`,
  `h3_gargoyle_upg`, `h3_elemental_gargoyle`, `h3_golem`, `h3_golem_upg`,
  `h3_magnetic_golem`, `h3_mage_upg`, `h3_battle_mage`, `h3_genie`,
  `h3_genie_upg`, `h3_genie_vizier`, `h3_naga`, `h3_naga_upg`,
  `h3_naga_rani`, `h3_giant`, `h3_giant_upg`, `h3_colossus`.
- First owner: GPT-6 Luna, Max effort. A failed owner result gets one fresh
  GPT-6 Sol, XHigh owner on that SAME unit; a failed Sol result gets one fresh
  GPT-6 Astra, High owner. Close/retire the preceding owner before replacement;
  do not fork its long conversation or let it spawn agents. Give the successor
  the frozen inputs, prior artifacts/defects and the skill, not the predecessor's
  unverified conclusions as ground truth. Do not skip a tier or restart the
  ladder for each small hypothesis.
- An operational failure (no complete equipped mesh reel, unavailable dependency,
  wrong source, or no plausible candidate) triggers escalation after the owner
  has attempted its end-to-end route. A quality-rejected but complete reel is a
  failure when the owner judges it not plausible to ship; retain it for the
  next tier. A usable candidate with disclosed minor defects is a result, not
  automatic failure. The user may approve a candidate despite diagnostic gates.
  The final Astra tier is the last chance for that unit: choose and deliver the
  most plausible complete candidate and reel, with defects explicit, rather
  than returning only a veto or another research plan. Do not label it pristine
  or runtime-proven without evidence.
- Use one Blender MCP writer at a time. The interactive endpoint is a shared
  mutable scene, not a safe parallel render farm. Queue workers or their scene
  stages; never let one unit clear, overwrite or reconfigure another's scene.
  Each owner first inspects the scene, then uses a separate collection/copy and
  disjoint output root. If MCP is down, restore it before 3D work; do not
  silently switch to shell Blender. The tested local launch used Blender 5.2.2
  with `--online-mode` and the installed MCP add-on; confirm the active endpoint
  rather than relying on a past process ID.
- Do not accumulate every unit's multi-hundred-MB scene in the same live Blender
  process. The Magnetic Golem Luna pass saved an 811 MB inherited workbench and
  subsequent MCP calls timed out. Retain each unit's isolated `.blend`, verify
  it, and start the next unit in a fresh lightweight Blender MCP scene/process
  once the prior owner finishes. Never discard an unsaved user scene; preserve
  it first. A dead/unresponsive endpoint is an operational failure to restore,
  not evidence that the mesh needs regeneration.
- The existing session authorization covers at most one standard 20+10-credit
  body generation per unit when the skill's canonical and pose preflight passes.
  It is not authorization for a second generation, Ultra, separate remesh or
  paid prop. Inventory donor props before spending. Freeze each input/task/hash.

## Measured Gargoyle Lesson

The retained 37-joint, 75-frame Gargoyle saved mocap was animated through
interactive Blender MCP without replacing body motion. Exact evidence and the
selected attempt-3 reels are in
`artifacts/homm3_gargoyle_blender_mocap_rebind_physics_astra_20260923_v1/`.
Its `ASSESSMENT.md`, `metrics.json`, `source_view_metrics.json` and `.blend`
are the source of the following condensed rules. The unit-specific learning
record is `gargoyle-blender-web-field-does-not-repair-attachment` in
`learning_index.json`; do not generalize its vertex indices or parameters.

1. Inspect the textured rest and worst frames with the joint chains from front,
   side and rear before changing weights. The Gargoyle root is behind the upper
   torso, not at the hand; a bird wrist fork with familiar names was not a bat
   membrane rib. Preserve the exact saved full skin matrices and registration.
   Deriving new rotations from point positions or replacing the body trajectory
   would confound the bind test.
2. Classify spar, web, body and attachment separately on welded topology. A
   direct distal-fork-to-proximal merge reduced web strain but opened a 68.09x
   attachment edge. A connected-web field reduced mean wing edges above 2x
   from 120.93 to 10.11 and peak wing stretch from 12.01x to 6.20x, yet raised
   attachment stretch from 4.95x to 12.89x. Copy weights to UV duplicates and
   hold body/boundary weights fixed so a wing experiment cannot quietly change
   body motion. Evaluate the attachment as its own gate; do not call an
   interior-only improvement a general repair.
3. Native Blender Cloth on a welded proxy can add bounded secondary motion
   after the bind, not replace mocap. In the selected attempt, body/spar pins
   were fixed, web pins were 0.92 and displacement was capped at 1% of rest
   height. The raw solver exceeded that cap on 22,668 node-frames. With the
   envelope, wing/attachment peaks were 6.34x/13.02x and collapse was not
   solved. This is a selected visual treatment, not proof of physical cloth or
   contact; collision/self-collision were disabled. Do not use physics to hide
   wrong ownership, rest correspondence or a missing death/rubble state.
4. Pair baseline and candidate in the SAME registered source-facing Blender
   camera, frame, mesh topology and render policy; label side/rear diagnostic.
   The static source bridge still had about 4.31 source-pixel body residual,
   so its IoU is comparative only. Inspect loops and clip entries, source-visible
   shape, wing/body boundary, contact and terminal form. The selected pass still
   has loop gaps, body/contact mismatch and intact suspended death. It was
   user-approved as plausible to ship despite those recorded defects; approval
   changes selection, not measured facts or proof tier.
5. Retain a textured full-frame mesh reel, `.blend`, exact input hashes and
   all-frame readback. The Gargoyle result has two selected 75-frame MP4s and
   a packed-texture `.blend`. Its exported weight-only GLB is NOT the selected
   physics surface. Native glTF dropped sub-0.0001 weights; verify exported
   skin/animation against the Blender candidate and never call an earlier
   weight-only export the physics delivery.

These are transferable diagnostic operations, not a Gargoyle recipe to apply
blindly to Golems, Genies or Nagas. The skill's canonical reference, prop,
source-motion, same-camera and full-reel requirements still apply to every unit.
