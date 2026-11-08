# HoMM3 unit animation authenticity pass

Status: started 2026-10-07. Long-running background effort (expected: months). One unit at a time, every
custom-faction and neutral unit in `homm3_import.json` (268 rows), until each one passes the rubric below on the GLB
the game actually ships.

## Goal and scope

Every clip of every unit must read as its HoMM3 DEF animation: the same poses at the same moments, the same
articulation, the same weight and rhythm, the same distinctive effects. "Close enough" and "passes the gates" are not
the bar; the bar is that someone who knows the HoMM3 sprite would recognise each frame.

- **Exempt: stride length and move speed.** The stride-match lane (`docs/homm3_stride_match.md`) owns them; leg
  phase, contact and articulation inside the stride are still judged.
- **Never a pose substitution.** Keep the HoMM3 stance and fix articulation inside it (e.g. rearing units keep
  rearing; the griffin four-legged sit was rejected for this reason).
- **No Meshy credits** are approved for this pass. Mesh problems are fixed by mesh surgery on the existing meshes
  (cutting fused parts, splitting straddling triangles, local repair, re-weighting); a unit that genuinely needs a new
  mesh is parked as `needs_user` with the reason.
- **VFX** may be authored where the DEF shows an effect the unit lacks (breath, glow, projectile, spell flash, death
  dust). Style: vanilla Olden Era, not ripped DEF flipbooks (`docs/olden_era_vanilla_vfx_style.md`,
  `docs/homm3_vanilla_vfx_faction_rollout.md`); idle/always-on effects must also play in previews.

## Instruments

- Board: `python tools/homm3_authenticity/board.py <unit> [--glb <candidate>]` renders the shipped (frozen) GLB, or a
  candidate, next to every DEF frame of every clip from three cameras: the DEF-matched sprite camera, the in-game
  battle camera and the recruit/preview camera. Outputs per-clip strips, an overview, looping side-by-side GIFs and
  per-frame silhouette numbers (`board.json`). Blender-free, GPU. See `tools/homm3_authenticity/README.md`.
- Ledger: `tools/homm3_authenticity/ledger.py` (`next`, `show`, `clip`, `set`, `summary`), data in
  `tools/homm3_authenticity/ledger.json`. One row per unit, never dropped; clip verdicts with named defects; commits.
- Existing measurements to quote, not to replace judgment: `flyer_articulation` gate and freeze check, stride
  measure, `articulation_sheet.py`, the high-res stretch review (`review_unit.sh`, needs Blender).
- **No inherited approvals (user, 2026-10-07).** Earlier in-game approvals, accepted slices and "reference" units (gargoyle, castle walks, griffin idles) carry no weight here. The DEF is the only bar and every unit is judged fresh.

## Rubric (every clip, every frame, all three views)

**Motion intent first (user, 2026-10-07).** What the creature is doing, and how (the action, its weight, the direction
of force, anticipation, impact and recovery, the rhythm), outranks the silhouette. Each clip is judged first by watching it
play at game speed next to the DEF and stating the action of each in one plain sentence; if the sentences differ, that is
the clip's top defect. **Faces and heads matter most (user, 2026-10-07):** the head must look the same direction as the
DEF's at the same moments (at the camera, the enemy, up, down, turning away); a wrong gaze fails the clip even if all else
matches. Order: head direction and motion intent, then whole silhouette, then subtle joints.

**Abandon silhouette matching (user, 2026-10-07; overrides older wording in this doc).** The DEF shows what the
movement appears to be in the general sense (action, gaze, beats, rhythm, roughly what the body and limbs do). We author
natural 3D motion that reads as the same movement from any game angle. Silhouette overlap, outline fits and frame-exact
limb placement are not goals. Judgement order: gaze and motion intent; natural articulation with no stiff joints where
the DEF moves them; mesh integrity. Rubric item 1 "Key poses" means the general pose and action of each beat, not a traced outline.

**Do not overfit to the DEF's camera angle (user, 2026-10-07).** The DEF is one 2D view. Reconstruct a natural 3D
motion first, then make it read like the DEF from the sprite camera; never buy silhouette match with poses that are
implausible in 3D (e.g. diving the whole body to fake a wing shape). Every clip is judged from the battle, preview and
orbit views as well as the sprite view, and fits carry 3D priors (body attitude, joint limits, smoothness).

**Whole silhouette first (user, 2026-10-07).** Judge the unit as a player sees it: head and neck attitude, body pitch, stance,
proportions and facing come before joint tables, and are named first in every review. Subtlety is part of the same bar, not a
separate one: stiff or static joints stick out and spoil the look of the whole unit. The eye on the whole unit decides.

**Gestalt perfection, not numbers (user, 2026-10-07).** The DEF's resolution does not support numeric precision (as with
significant figures). DEF match is never judged, targeted or reported in numbers (IoU, degree or pixel deltas, joint-row
counts). `joint_coverage.py` and the keypoint tracks only point at where to look; verdicts and run reports are visual.
Mesh-integrity gates (tears, stretch) remain, because they guard visible defects.

A clip passes only when every item holds. Record each failure as a named defect on the clip
(`ledger.py clip <unit> <clip> fail --defect "..."`), with frame numbers.

1. **Key poses.** Each DEF frame's body attitude, head/neck, spine, tail, every limb joint (shoulder, elbow, wrist,
   claw / hip, knee, ankle, toe) and wings match. The eye decides; `board.json` numbers are not evidence.
2. **Timing.** Anticipation, contact, impact, recoil and settle land at the DEF phase. Holds where the DEF holds,
   motion where the DEF moves (no frozen pose 3+ frames while the DEF moves). Easing matches (snap vs. drift).
3. **Articulation.** No toy-bounce whole-body motion with stiff limbs. Wings beat with real downstroke/upstroke and
   follow-through. Rearing forelimbs articulate like the DEF, never "miming" rigid in the air.
3a. **Joint coverage and subtleties (user, 2026-10-07).** Every joint that bends or shifts in the DEF / original
   capture must bend or shift in ours, at the same moments and by a comparable amount: knees, hocks, fetlocks, elbows,
   wrists, fingers and claws, neck segments, jaw, ears, tail segments, wing digits, spine flex. A joint that is static
   in our animation while the DEF moves it is a failure even if the big motion reads well; a joint the DEF articulates
   that our rig does not have (no bone, or the bone has no weight) is a rig defect to fix by adding the bone/chain and
   weights, not to hide. Subtle motion often matters more than big motion. `joint_coverage.py` lists capture joints
   that move while ours stay still; where the human capture has no counterpart (each of a quadruped's four legs, tails,
   jaws, ears, wing digits) the reference is the DEF itself, through per-unit DEF keypoint tracks
   (`tools/homm3_authenticity/keypoints/<unit>.json`). No articulating part is exempt for lack of a reference. The eye on
   the full-size board confirms. Example: the champion's horse knees.
4. **Contact and ground.** Planted feet stay planted (no skate inside the stride), nothing sinks through or hovers
   over the floor unless the DEF floats/flies. Two-legged idles keep front limbs off the ground with hind legs planted.
5. **Props.** Weapons, shields, staffs and bows are held, aimed and swung as in the DEF; no flailing, no clipping
   through body or floor, no props detached from hands.
6. **Mesh integrity** at full board resolution: no tears, shards, candy-wrapper twists, stretched faces, fused parts
   dragging (sleeves on bodies, wings on backs), self-intersection that reads on screen.
7. **Loops and transitions.** Idle and Move loops close without a pop. Clip start/end poses join cleanly (idle ->
   move start, move end -> idle, idle -> attack -> idle, death end stays down).
8. **Death.** Falls, collapses, shatters or dissolves the way the DEF does, and the final pose rests on the floor.
9. **Effects.** Every effect the DEF draws (breath, lightning, glow, projectile release, impact flash, death dust)
   exists, is timed to the DEF frame, and plays in the preview where it is an idle/always-on effect.
10. **3D sanity.** The preview and battle views show a coherent 3D pose: no broken depth from a 2D-only fit, wing
    symmetry where the DEF is symmetric, plausible head and torso twist.
11. **Line consistency.** Base, upgrade and alternate upgrade differ where their DEFs differ and agree where the DEFs
    agree.

A unit that is "broadly the same" after a fix is not progress.

## Fix routes (cheapest first)

1. `glbPatch` ops on the GLB patch lane (`docs/homm3_glb_patch_lane.md`; `fleet_rebuild.py --from-base <unit>`):
   default for animation fixes. A fix class the lane lacks is added as a new numpy op, not routed through the full
   chain.
1a. **Rig extension (no limits, user 2026-10-07).** When the DEF articulates something our rig cannot (a tail
   segment, jaw, ear, wing digit, an extra leg segment, a separate fore/hind leg, fingers, a mane or cloak chain), add
   the bones, place them on the mesh, weight them, and drive them from the DEF. This is a normal fix, not an exception:
   extend `tools/homm3_def_retarget` (new chains in the unit config / an extension) and rebuild through the full chain,
   then carry the new rig into the retained base so later fixes return to the patch lane.
2. Unit config + full chain (`run_unit.sh`, `fleet_rebuild.py <unit>`) only for genuine geometry / UV / rig changes
   (Blender; `launch_guard` refuses while the game runs).
3. Mesh surgery on the existing mesh, then a full rebuild.
4. VFX authoring per the vanilla-style docs, previewed in the Unity VFX preview harness (`docs/homm3_unit_vfx_preview.md`)
   through the Unity queue runner.

After any fix, re-board **every** clip of the unit (a fix to one clip has regressed others before), and re-freeze the
unit into its slice through `freeze_slice.py` so the shipped GLB is the judged one. A unit is `passed` only when the
board of its frozen GLB passes every clip.

## Operating rules

- One unit at a time, one heavy job at a time. Never launch, attach to or kill the game. If the game is running,
  only Blender-free work (boards, patch lane) runs; Blender, Unity and bundle builds wait.
- Installs into the working build need no user approval (user, 2026-10-07). A worker that passes a unit reports
  `INSTALL READY` with the slice; the coordinator installs it per unit (claim `golden-era-deploy` on the cross-agent
  manager, game stopped, `ship_def_retarget_slice.py` prepare/lab/bundles/probe/deploy through the Unity queue,
  readback recorded in the run log). VFX drafts for passed units ship the same way. Never while the game runs.
- Codex and other agents share the worktree: skip a unit whose files carry someone else's uncommitted edits or a
  commit from another agent in the last 24 h; commit only own files with `git commit --only`.
- Scratch and boards live under `V:/olden_port_work/authenticity/` (not F:, not the git tree); per-run logs under
  `V:/olden_port_work/authenticity/runs/`. Prune superseded candidate GLBs and boards when a unit passes.
- No broad validators; run only the narrow per-unit checks named by the lane you touched.
