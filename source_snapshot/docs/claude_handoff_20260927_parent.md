# Claude session handoff: parent coordination (2026-09-27)

Status: reconstructed from the paused Claude Code transcript, not a validation of
the current worktree, running processes, installed payload, or gameplay. The
source is
`C:/Users/<user>/.claude/projects/V--Games-Olden-Era-Playtest-Tweak/aeba9e69-0217-4c63-98f4-71a64ce15d89.jsonl`
(`T` below). Line numbers are JSONL records; timestamps are UTC. Peer-agent
messages are reports, not user instructions or proof. The latest parent summary
at T:19210 is useful orientation but must be checked against source/artifacts.

## Latest decision and immediate handoff

- At T:19195 (21:56:27), Worker B reported three duplicate `q_fc.sh` queues,
  same-unit Blender output collisions, and permission-denied attempts to stop
  them. Its historical stop list was queue PIDs 53304/33112/43308, guarded2
  49296/17460/66876/57616, run_unit.sh 30072/22396 and their Blender
  children. It explicitly excluded `hota_factory_halfling` fleet build PID
  54808 and the separate royal-griffin build. Verify *live* command lines,
  ancestry and ownership before stopping anything; PIDs may have been reused.
- The user answered "Stop them yourself. The F drive is too slow to work from
  regularly" at T:19278 (22:01:49). Claude hit its weekly limit at T:19285
  before doing so. The prior request for the user to choose who stops the
  processes (T:19276) is superseded. `F:/claude_scratch/` was the workers'
  previous routine build location; the newer instruction supersedes that
  placement for new routine work, not the requirement to preserve existing
  artifacts or to avoid filling C:.
- Do not restart any queue from its old script. Worker B planned one clean
  queue after the collision was cleared: automaton and couatls, then X2 without
  non-roster dreadnoughts, then Y1 (T:19195). Recheck its canonical outputs
  first, especially `h3_automaton_upg_alt`; the collided output is untrustworthy.

## Current parent-level decisions

- The parallel ownership contract is
  `docs/homm3_faction_rollout_parallel_brief.md`: fleet agent owns shared tools,
  gates, exts and Stronghold/Rampart/Castle leftovers/Conflux; Worker A owns
  Tower/Necropolis/Inferno/Dungeon; Worker B owns
  Fortress/Bulwark/Factory/Cove. Workers send shared changes through the
  coordinator. Original assignments: T:17923-17925 (18:15-18:16).
- The user approved stride matching for all factions after seeing Castle in
  game (T:17987, 18:23); keep the stride gate and visual sheet review. A
  passing numeric gate is not enough if motion stalls, floats, pops, or detaches
  props. The user also approved the 80% DEF wing-range concept, but calibration
  admitted rows only for the royal and battle griffins; no general relaxation
  was earned (T:18543; parent summary T:19210).
- The user rejected HoMM3-ripped flipbook effects in engine. HoMM3 determines
  what an effect depicts and when; Olden Era-native materials/particles supply
  its pixels (T:18147, 18:32; effects assignment T:18164). Castle effects are
  to finish, then Conflux is the richer template, then Stronghold. The user
  explicitly said not to stop Castle but to do Conflux next (T:18864), then
  said to hold faction rollout testing until Stronghold effects are done and
  treat effects as part of rollout (T:18731, 20:34). Do not freeze/deploy a new
  faction on motion evidence alone. The Castle/Conflux sequencing is not a
  license to resume broad parallel VFX authoring before Conflux establishes
  the method (T:18777 and the parent response).
- The user approved a *separate regression-fix install* that includes all
  affected installed ranged/index-1-ability slices, not just Castle: answer
  "Yes" at T:19152 to the parent question T:19150. The archer worker was told
  to rebundle from existing frozen selections only, without re-freezing or
  changing motion/look, and to stop short of deploy (T:19156). This does not
  override the hold on newly rolled-out factions.
- The user's Conflux town review says the default pan shows outside the
  terrain on left and right; fill the entire measured camera sweep using
  vanilla scene comparison (T:18937; phase-6 brief T:18941). Earlier feedback
  also rejected a blurred near field and required detailed close geometry,
  coherent pieces, correctly oriented buildings, and river flow (T:16084,
  T:17423-17441). Phase-5 installed is a transcript claim, not fresh proof.
- The how-it-was-made material is for a later YouTube video. Use animated
  demonstrations rather than a static scientific presentation (T:18010,
  T:18274). The three chapters are present and tracked: 14 animation-pipeline,
  7 VFX-pipeline and 9 strides-and-idles MP4s. A read-only `ffprobe` audit
  opened all 30 files and found nonzero duration, H.264 video and 1920x1080
  dimensions. This is container/metadata verification, not visual playback
  QA. Their READMEs explicitly state that none is in-game footage; even the
  `installed` animation shot renders the installed GLB rather than capturing
  gameplay (`how_it_was_made/animation_pipeline/README.md:28`). Do not
  promote the shot's proof tier or rerender completed chapters blindly.
  One request remains only partially represented: the strides-and-idles
  README:55 says the walk clips have no vanilla Olden Era walk footage, only
  measured vanilla slip data, although T:18010 requested examples from both
  games. Source suitable footage before claiming that comparison is complete.
- Paid Meshy work had standing approval for units needing new meshes
  (T:14509). The user also authorized a full-3D Conflux town (T:15389), but
  explicitly withheld Meshy spend for adventure-map building animation in
  favor of modifying the existing meshes (T:12239). Preserve that scope.

## Delegated lanes at the pause

| Claude peer ID | Ownership and last boundary | Primary transcript records |
|---|---|
| `a786b26a5af58a582` | Fleet/shared tools and Castle/Stronghold/Rampart/Conflux units. Runner crash fix was reported committed as `cbe686b4ee`; grounding had been removed from shared `build_unit.py` pending ogre/dwarf proof. Raw-accepted look support was partly committed (`cbd2780cb4`) but `freeze_slice.py` wiring was still working-tree only. Griffin builds, grounding proof, enchanter, and devil freeze gate remained open. | T:19114, T:19193, T:19253 |
| `a03d7fca59055209d` | Worker A. Inferno mostly passed motion, but devil-line teleport holds were falsely flagged from DEF effect pixels; no gate relaxation/knob change. Arch devil look failed: old `v6m` trial looked promising, but must be rerun on the current GLB before a spec change. Tower gargoyles and Necropolis dragons remained queued. | T:18879, T:18990, T:19197, T:19271-19273 |
| `ae359a19f8dbf716c` | Worker B. Bulwark's 21 units passed motion but awaited grounding and native effects. Paokai/Halcyon/Stormbird had clean rebuild reports; automaton output became untrustworthy under duplicate queues. Lizardman raw acceptance still awaited current trials/delivery. | T:19139, T:19195 |
| `a2dcbbe29d0bb96cb` | Native-style unit effects. Castle angel line had been retuned in lab, but holy colour/trail and full Castle promotion still needed verification. Conflux's 14-unit template, material displacement/overlay, and then Stronghold were assigned. No freeze/deploy by this worker. | T:19013, T:19194, T:19254 |
| `a9c83ca8e86d07e1d` | Archer/ability wiring. Assigned narrow attack-clip gate, ranged-aware StockMap, core overlay animation index, projectile ViewHelper, compile and affected-slice rebundles. Needed a hand-back before a combined install. | T:18952, T:18955-18956, T:19156 |
| `a60bf6cb5e1f1a47d` | Full-3D Conflux town phase 6: measured camera-frustum union, vanilla periphery reference, outside filler. Coordinator installs and validates. | T:18937-18941 |

The griffin report needs unit-level care: the stiff **base** `h3_griffin`
seen in game came from the older Sep-16 owned-skinned bundle, whereas the
royal and battle griffins were newer DEF-retarget builds (T:18705). The fleet
agent's `flightLife` pilot improved the **royal** generated build and it
regenerated the base griffin mesh with 36 Meshy credits, but T:19071 says
none of the three was frozen or deployed. The base still needed a rig refit
and full build. Royal/battle artifacts alone cannot close the user's
base-griffin runtime complaint.

The end-of-combat softlock, spell and Pandora investigations were separate
agents. T:19210 reports their source commits (`2c5cfd6929`, `29b0fdbe05`,
`497c6a425b`) and says only the softlock fix had reached the installed DLL.
Verify each commit, current payload and logs before promoting proof. The
user's in-game reports are T:17790 and T:18528. The Castle adventure-map
facing fix and the three video chapters are also reported complete in T:19210;
they are not reasons to recreate work blindly. Earlier portrait, neutral,
map-building-animation and disk-cleanup requests exist (T:14351, T:17512),
but had no new parent assignment at the pause; audit their current owners and
artifacts rather than launching duplicate work.

The parent summary T:19210 also flags 58 uncommitted unit-look JSON changes
from an earlier fitting pass, not owned by the effects agent, with no decision
to commit or discard them. The worktree is heavily dirty; stage only the paths
in each scoped milestone and preserve unrelated changes/deletions.

## Integration and proof discipline

1. Stabilize build concurrency first. The shared runner previously hid a
   Blender import failure and exported stale `.blend` data as OK. The fleet
   agent reported the fail-closed fix in `cbe686b4ee` and an audit of the
   affected Stormbird, Halcyon, Paokai and battle griffin (T:19095,
   T:19114-19117). Treat old "OK" records for these as provisional until
   their clean rebuilds and source hashes are checked. Never use competing
   Blender writers on the same unit.
   For the uncommitted grounding work, `grounding: false` in legacy configs
   is not a ground-contact exemption. The proposed `groundContact` exemption
   requires an explicit reason and still measures the unit; its debt pins
   carried-over frozen hashes. The ogre/dwarf proof must precede returning
   grounding to the shared build path (T:19071, T:19073, T:19193).
2. Preserve a single owner for each shared file. Worker-specific per-unit
   configs need explicit reasons for knobs; shared tool changes route through
   the fleet owner except the specifically assigned archer edits. Fail closed
   rather than adding silent fallbacks, lowering gates, or accepting a missing
   effect/mesh as a pass. Current normal-build validators and installed
   readback, not dated prose, define the contract.
3. When workers hand back, check their visual sheets and source/DEF identity,
   articulation, stride, facing, look stamp, ground contact, held-frame gate,
   native-style effects and pass-table hashes. A worker's `pass` is generated
   artifact evidence, not runtime or user-visible proof. Workers were
   instructed not to freeze or deploy; the coordinator integrates and applies
   only scoped commits (T:17923-17925 and the parallel brief).
   The `rawAccepted` look path was not accepted end-to-end at the pause.
   `cbd2780cb4` committed its look/spec/validator side, while `freeze_slice`
   wiring remained working-tree only. Its fail-closed sequence is current-GLB
   `--try-modes`, then `--stages bake,fit,vfx,review` to restore the selected
   VFX, then `--accept-raw` with a reason; old trials cannot qualify
   (T:19193). Lizardman or Stormbird should be the first full pilot.
4. For the regression install, first confirm archer gate/probe results across
   Castle and all affected existing slices; then build the combined plugin
   with live-interop validation, re-pin capability records, check the game is
   closed, deploy selected bundles/overlay, run installed validators, and
   leave gameplay checks explicit: ranged shot animation and projectile,
   Spread Out, Pandora rewards, and the end-of-combat result screen (T:19210
   pending-task section). If any slice fails, do not quietly omit it.
5. Check live process and disk state before heavy work. Use memgate for
   Blender/Unity, one Unity run via `unitylock.py`, no routine F: work, no
   large C: writes, and no unverified bulk cleanup. Do not interpret a
   generated artifact, successful build, or installed payload as user-visible
   gameplay proof. Update any stale documentation after actual validation.
