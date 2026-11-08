# Ground-contact proof continuation (2026-09-27)

Status: one isolated ogre raw-build candidate generated and measured. The
shared grounding build path, post-build delivery chain, frozen selection,
install, runtime, and the legacy 73-entry debt file remain unproven.

## Reconstructed method

The paused fleet worker proposed three world-Z corrections after all
`before_keys` hooks and before writing animation keys: align each clip's entry
to the Idle floor within the DEF's first-frame offset, ease Death's last frame
onto that floor, then lift only frames whose skinned mesh is below the DEF's
own opaque-body bottom-row allowance. The floor and scale are measured from
the skinned Idle key 0, not the capture's lowest joint. This is implemented in
the uncommitted `tools/homm3_def_retarget/grounding.py`; the shared
`build_unit.py` still does not import it. The earlier proof builder at
`F:/claude_scratch/aeba/gtools/build_unit_ground.py` differs from shared
`build_unit.py` only by that block and path resolutions. Its copied V: version
and runner are under `artifacts/claude_takeover_20260927/grounding_proof/`.

The requested proof is ogre Death, Hitted, Move, and AttackFront as DEF | old |
new render sheets, then dwarf AttackFront to verify that the DEF-supported
lunge is preserved. Inspect Death contact, clip-entry continuity, visual
vertical pops, and whether jumps retain air time. `grounding: false` only
disables the capture-joint hip drop; it is not a contact exemption. The
separate `groundContact` reasons still require measurements.

## Baseline and preflight

The current old generated GLBs were measured read-only by `ground_check.py`:

| Unit | Existing delivered-GLB contact failure | Earlier arithmetic projection on that GLB |
|---|---|---|
| `h3_ogre` | Death low -0.228, last -0.165, Hips entry -0.052; Mouseover low -0.044 | Death last 0.000, Death min -0.016, Hitted entry 0.000, AttackFront min -0.012 |
| `h3_dwarf` | Death last +0.180 | Death last 0.000; AttackFront retains -0.068 at the DEF's -0.145 lunge frame |

The right column is **not** a controlled raw-builder counterfactual: the
delivered ogre GLB already has emphasis, idle-retime, look, and stride
processing. Dwarf AttackFront also
predicts a +0.061 height correction at the preceding frame; its transition
must be judged on the sheet rather than passed on the numeric gate alone. A
synthetic positive-height jump is unchanged by the lift-only clamp, but that
does not replace review of actual motion.
Move is intentionally omitted from the prediction table: the canonical GLB
has post-build stride retiming with mixed sampler grids, so applying the
unshipped builder's frame rule to that GLB is not an equivalent experiment.

## Ground-gate sampling defect

Read-only reproduction in the proof directory's `audit_sampler_time.py`
found that `ground_check.glb_ground()` evaluates `Rig.world(k)` at the same
*key index* for every glTF channel, ignoring each channel's sampler-input
times. Post-stride Move clips have dense Hips/leg keys but sparse upper-body
keys. Ogre Move at index 4 combines Hips time 0.083333 s (41 keys) with Head
and Hand time 0.416667 s (10 keys); the assembled LeftHand world position is
0.156 scene units away from a coherent-time evaluation. Across the 41 Hips
times, the index-built lowest vertex is -0.105631 versus -0.072584 at common
times, with a 0.046597-unit maximum per-frame floor error. Dwarf Move mixes
0.052083 and 0.260417 s at index 4; its index/coherent minima are -0.111936
and -0.089424. Both Idle heights measure 1.7 units. At that point, a Move
ground-gate result could not be trusted until the sampler was fixed. Ogre
Death and dwarf AttackFront have aligned 8-key TRS samplers,
and the reproducer returns zero discrepancy for those clips; their baseline
contact values above remain usable.

The existing time-aware implementation is
`stride_match_glb.Glb.sample_local(clip, times)` plus `.world(local)`, which
supports LINEAR/STEP and quaternion slerp. The ground gate should sample all
TRS channels on one timestamp grid and feed those matrices to `Rig.skin`;
do not interpolate quaternion components or infer time from the maximum key
count. That correction is now in the shared `ground_check.py` worktree only,
with three focused mixed-sampler and unknown-interpolation regression tests
in `test_ground_check.py` passing. Independent source review is clear after
adding an explicit LINEAR/STEP sampler allowlist; an unknown interpolation
must fail, not silently become LINEAR. Broad validator readback and a scoped
integration commit remain pending; this does not validate the grounding
build rule.

On the current old GLBs, the correction changes ogre Move's measured minimum
from -0.062 to -0.043 of height, and dwarf Move's from -0.050 to -0.037.
Both units retain exactly the same ground-fault lists, including ogre Death
and dwarf Death; dwarf AttackFront still reaches -0.068 at the DEF's real
-0.145 dip. No tolerance or DEF-source policy changed.

The 73-entry `homm3_owned_skinned_ground_debt.json` predates this sampler
correction. Its SHA/fault-key entries may still match, but its `measured[]`
figures can now be stale. The fleet/shared owner must remeasure that debt and
run the full articulation validator before promoting the ground gate. The
current sampler correction is source/test validated on two units only.

The isolated runner writes only to its own V: proof directory and does not
invoke fleet rebuild, freeze, deploy, Unity, or the game. Every Blender call
uses `launch_guard.py` for game process, V: free space, and RAM/VRAM, and the
whole unit build will hold `unit_writer.py`'s per-unit OS lock. The bounded
command is the explicit Git coreutils
`C:/Program Files/Git/usr/bin/timeout.exe 3600` wrapped around Git Bash and
the isolated runner. The copied runner's approval environment flag prevents
an accidental standalone launch.

At 18:24 local on 2026-09-27, `HeroesOldenEra` PID 21484 began running and
the root coordinator revoked the provisional ogre resource slot. The game
subsequently exited, and a new guarded, locked ogre slot was approved. That
first proof command reached only the `build_heat` Blender process, which
exited 127 before exporting heat; its log says only `Failed to replace
function free in module ucrtbase.dll`. Direct read-only `blender.exe --version`
probes in the sandbox and with escalation both fail before startup with
Windows exit 3221226505 and the same message; a locked probe also reproduces
it. No ground candidate, render sheet, canonical change, or freeze resulted.
The process-audit lane diagnosed Blender startup before any retry. Generated
candidates remain separate from canonical and frozen payloads.

A later child-only diagnostic with `TBB_MALLOC_DISABLE_REPLACEMENT=1` let the
same Blender binary print `Blender 5.2.2 LTS` with exit 0. This pins the
startup failure to allocator replacement rather than the grounded builder.
The user subsequently authorized that process-local setting for one isolated
ogre build only, not a permanent environment or product-pipeline change.

The successful run used a fresh `launch_guard.py` check (game absent, V: 139.5
GiB free, RAM 20.9 GiB, VRAM 13.6 GiB), a per-unit writer lock, and a fresh
guard before each Blender process. Git Bash needed its known sandbox
escalation for its signal pipe. Exact bounded command:

```powershell
$env:GROUND_PROOF_APPROVED = '1'
$env:TBB_MALLOC_DISABLE_REPLACEMENT = '1'
python tools/homm3_def_retarget/unit_writer.py h3_ogre -- 'C:\Program Files\Git\usr\bin\timeout.exe' 3600 'C:\Program Files\Git\bin\bash.exe' 'V:/Games/Olden Era Playtest Tweak/artifacts/claude_takeover_20260927/grounding_proof/run_unit_ground.sh' h3_ogre
```

The whole process exited **0** at 19:37 local, exporting
`artifacts/claude_takeover_20260927/grounding_proof/h3_ogre/h3_ogre_def_retarget.glb`
(SHA256 `BB53E6AB394DE536F27BCECA010C78E1888004FC7FABB6E1F04D6D1D1E77E281`).
The canonical ogre GLB stayed at
`65ACDEA1A3DFBAC61DFBDD48DB6044C13B040C63445A9AF0A24DEA72D8A38C66`;
the dwarf GLB and ogre config also retained their pre-run hashes. The raw
builder's `.ground.json` stamps 64 DEF frames with SHA1
`9d27c9cb665cb1fe4d348020eea1afd4b578a12e`. No freeze or deploy ran.

The corrected coherent-time `ground_check.py` parses this new GLB and returns
exit **0**, with no faults among the nine Unit clips. In the same raw build,
Death's skinned low changes from -0.228 to -0.016 body heights, its last frame
from -0.093 to 0, and AttackFront's low from -0.026 to -0.012 against DEF
-0.012. Hitted's entry returns to the Idle floor; Move's low is -0.013
against DEF -0.024. The old delivered GLB still reports four faults (Death
sink, Death entry Hips step, Death landing, Mouseover sink). These are
generated-artifact contact measurements, not runtime behavior.

`make_sheets.py` generated and the agent inspected DEF | delivered old |
isolated new sheets for Death, Hitted, Move, and AttackFront in the proof
directory. The new Death body is visibly lifted during its descent and lands
at the measured floor; Hitted and AttackFront retain their main action poses,
and Move has no apparent large vertical pop in these nine frames. The render
has no explicit floor plane, so the gate supplies the precise contact measure.
The isolated render's mean silhouette IoU versus DEF is Death 0.456, Hitted
0.643, Move 0.607, AttackFront 0.654, against the delivered old render's
0.331, 0.611, 0.620, 0.625 respectively. **This is not an A/B estimate of
grounding quality**: `verify_channel_delta.py` finds the delivered old GLB's
emphasis/stride stamps, 13 changed non-Hips rotation channels in each of
Death/Hitted/AttackFront, and 41 old versus 10 new Hips Move keys. The old
`blend` SHA is the emphasis stamp's output, not the raw source. The isolated
grounding block itself only translates the post-hook world pose vertically,
but no matching raw ungrounded render was made. The new GLB has not passed
emphasis, idle retime, look, stride match, bundle build, or game inspection.

Work frozen at the user's request after the ogre pilot and focused ground
sampler tests. The supervised ogre build exited 0; this lane owns no running
process or pending Blender session. Do not run any further stage until the
user explicitly resumes work.

Stop here for coordinator review before dwarf or broad builds. For promotion,
evaluate the same-source post-processing chain and repin the 73-entry debt's
`measured[]` under coherent-time sampling; passing this single raw contact
gate does not justify enabling the shared grounding block or freezing units.
