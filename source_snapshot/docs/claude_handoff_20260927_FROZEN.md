# Frozen work handoff

All work is paused at the user's explicit request: "Freeze all the work and
create handoffs for it." This supersedes every earlier execution approval,
including the one-build Blender allocator approval. Resume only on a new user
instruction. This is a work pause, not an asset freeze or quality acceptance.
No takeover payload was deployed. Preserve the dirty worktree and ignored
artifacts; do not reset, clean, or stage unrelated changes.

## Read order and methodology

Read this checkpoint first, then the lane handoff linked below. The original
[master reconstruction](claude_handoff_20260927.md) and
[parent methodology](claude_handoff_20260927_parent.md) preserve Claude's
instructions, subagent ownership, rejected approaches and approval boundaries.
Earlier 'active', 'next', game-running, and pending-approval statements in
chronological notes are historical snapshots. This document governs status.

Keep source, generated artifact, build, installed, runtime and user-visible
proof separate. Do not silently relax gates, replace native ownership with
patches, or treat candidate outputs as installed fixes. On eventual resume,
recheck processes/resources; use the existing Unity lock and unit writer guard.
Use V: scratch. Do not launch or stop the user's game.

## Lane checkpoints

### Native effects

[Effects handoff](claude_handoff_20260927_effects.md). Water completed two
guarded Unity lab comparisons. Moving only idle water from Spine1 to Root
removed upper-body occlusion and separated the hit burst. Current evidence:
`artifacts/vanilla_vfx_style/lab/h3_water_elemental/`; first run preserved in
`h3_water_elemental_spine1_v1/`. This is selected-native-subtree lab visual
proof, not full native equivalence or delivery. Commits `b8c20954b1` and
`0c73a007ba` contain the lab milestone and corrected proof boundaries.

Next, only after resume: resolve prepare-before-compile COLOR_0 bake ownership
with a separate derived GLB, fingerprint its producer/spec/output, and verify
actual bundled vertex colors. No frozen water selection exists. Shared ship
changes were proposed but NOT made. Keep draft pending; no promotion/catalog
change. Castle remains eight frozen plans plus a skipped base-griffin row,
not nine deployable effects units. Preserve Castle -> Conflux -> Stronghold
sequencing and the user's hold on effects-incomplete new faction rollout.

### Existing-unit gameplay regression delivery

[Gameplay handoff](claude_handoff_20260927_gameplay.md) and
[96-unit coverage](claude_handoff_20260927_regression_coverage.md).
Candidate Core validation and Pegasus 3/3 editor probes passed; Rampart bundle
and Stronghold remain pending. No full-roster install occurred.

The isolated Mage remap stopped before copy. Read-only Unity evidence proved
a duplicate stock-controller GUID: 200 of 275 source override controllers
reference the unresolved original GUID, 75 reference Unity's synthetic GUID
for the Crusader copy. Of the 96 affected installed units, these counts are
70 and 26. Do not guess a different base or rebundle this invalid project.

Proposed, NOT applied: preserve the original esquire GUID, assign the Crusader
copy its already-referenced synthetic GUID, validate both cohorts and unchanged
controller/clip/prefab bytes, fix bootstrap copying of meta identity, and add
a build-time resolved-base gate. Then rerun the isolated Mage pilot before
broader delivery. Leprechaun and wolf-rider missing-clip/source blockers remain.
Uncommitted planner, tests, pilot and diagnostic sources are preserved under
`tools/homm3_import/`; the diagnostic is outside the normal Editor wildcard.
Diagnostic log: `artifacts/homm3_attack_slot_remap_pilot/`.

### Conflux town content and runtime

[Town handoff](claude_handoff_20260927_town.md) and
[content methodology](homm3_conflux_full_3d_town.md).
Phase-6 CPU stage completed; catalog and coverage are under
`artifacts/homm3_conflux_full3d_phase6/`. Candidate validation passed 990,000
sampled rays with zero proxy voids; stripped-outer negative was 1.3%. Latest
reported runtime was 27.3 seconds. Six focused tests passed. This remains a
sampled geometry proxy, not rendered or runtime proof. Twelve editor shots
are prepared, including 4096x2160 and 21:9 with runtime-equivalent scaling.

Runtime seating and stable lighting source passed diagnostic OfficialDeobf
Compile and live-interop audit (1,174 refs, zero new unresolved). Normal Build
did NOT pass other prebuild asset/articulation gates. No DLL deployed.
All town content/runtime changes remain uncommitted. Scope includes
`Homm3TownScene3d.cs`, the town builder/inventory/Unity editor, periphery and
camera extraction/sampling modules, native camera JSON, focused tests, and
`tools/validate_town_scene3d_contract.py`. Do not discard them.

After resume: guarded exclusive Unity bundle, candidate bundle/readback gate,
then default/pan/wide render inspection. Native spline/fly-to paths and
user-visible pan/lighting remain unproven. Do not skip renders because the
proxy gate passes.

### Grounding proof and Blender

[Grounding handoff](claude_handoff_20260927_grounding.md) contains exact command,
hashes, measurements and sheets. [Process audit](claude_handoff_20260927_processes.md)
explains the startup failure. User approved one isolated Ogre build with
child-only `TBB_MALLOC_DISABLE_REPLACEMENT=1`; it completed exit 0 before pause.
No global environment or installation change was made. The scratch GLB passed
the corrected coherent-time ground gate across nine clips, with zero faults.
The four visual sheets were inspected by the lane owner.

Important: old delivered Ogre includes emphasis/stride/look/retime; the new
candidate is raw. Their IoU comparison is NOT a controlled grounding A/B.
Post-processing, dwarf proof, integration and stale 73-entry debt repinning
remain pending. `ground_check.py` and `test_ground_check.py` are untracked;
three focused tests passed, but committing the whole inherited ground package
would exceed the proven scope. Shared grounding was not enabled. Preserve
scratch under `artifacts/claude_takeover_20260927/grounding_proof/`.

### Fleet workers and shared safeguards

[Fleet handoff](claude_handoff_20260927_fleet.md). Worker A's Arch Devil v6m
look is committed in `925bf914b7`, deep-validated against its exact source GLB;
not motion, effects or delivery acceptance. Checkpoint:
`artifacts/claude_takeover_20260927/worker_a/README.md`.
Worker B ran no clean replacement queue. Collided automaton output remains
untrusted; next would be one clean automaton, then reviewed couatls. Lizardman
needs fresh mode trials and Stormbird has a stale look stamp. Checkpoint:
`artifacts/claude_takeover_20260927/worker_b/CHECKPOINT.md`.
Old game-running claims in those checkpoints require a fresh check, not reuse.

Shared source-grounded teleport holds, frozen provenance, raw-accept checks
and duplicate request rejection are committed in `3acd817847`; focused tests
and three current devil freeze checks passed. Real raw-accepted unit delivery
is still unproven. Grounding edits were deliberately excluded from that commit.
Process safeguards are committed in `a3092dc04b`; water draft in `9b1d37129a`;
initial reconstruction in `36fb2cd408`; water research in `fc84fd904f`.

## Stop-state and preservation

At freeze, all other agents had completed; the grounding owner confirmed its
only supervised build already exited and no owned process remained. Root's
fresh named process check returned no Blender, Unity or Python process.
No further product checks, builds, renders or investigation were launched to
prepare this handoff. Documentation-only checkpointing does not accept or
promote unfinished source. Uncommitted product edits and ignored evidence
remain in place, not bundled into a misleading completion commit.
