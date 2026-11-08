# Conflux full-3D town: Claude handoff, 2026-09-27

Status: reconstruction for the next agent, not a phase-6 validation report. This
was checked against the Claude subagent transcript ending at 2026-09-27 21:58
UTC, the current worktree, the F: candidate directory, and the active Golden Era
install. The phase-6 build was still unresolved at this checkpoint. Do not treat
an uncommitted file or a camera estimate as installed or user-visible proof.

Execution update: the coordinator's later instruction supersedes Claude's F:
scratch convention. Keep new phase-6 scratch, Unity project, bundle, and
renders under a workspace-local V: root through `CONFLUX_FULL3D_ROOT`. Existing
F: caches and phase-5 artifacts may be read as references, but must not be
bulk-moved. The original background stage was reported not to have survived a
17:03:54 reboot; independently confirm the process audit before restarting it.
The coordinator reserves Unity separately. Nothing below authorizes a Unity
launch or game installation before that reservation.

## Continuation proof, 2026-09-27

The runtime source now accepts an explicit v2 full-3D catalog with the
extracted `cityHuman2` `CityCamera/MainCamera` rest local pose and pinned
`level67` SHA-256. It seats the scene root at that authored pose relative to
the native pivot, while v1 remains an intentional legacy camera-follow path.
The source-asset hash is checked once on first v2 town activation, not in the
main-menu fail-fast preloader. The town presentation owner catches and reports
activation failure rather than silently switching scenes. The v2 light frame
is the seated root, not the moving camera. Source/decomp evidence indicates
the camera controller moves the MainCamera child; live pan and lighting remain
unproven.

A diagnostic OfficialDeobf MSBuild `Compile` target against the active Golden
Era references succeeded with deployment disabled. The fresh compiled `obj`
DLL SHA-256 was `A171ED86E062B909B03FA596D468C443275D2C8BCD6FD5D582C801241EC5AF5C`.
The existing live-interop verifier on that exact DLL resolved 1,174 member
references across 139 live interop assemblies, with 20 existing allow-listed
findings and zero new unresolved references. This is **not** a normal Build
pass: prebuild gates stopped first on missing Factory/Bulwark unit bundles,
then on existing owned-skinned articulation failures when only that first gate
was diagnostically skipped. No phase-6 bundle was built or deployed, and no
in-game town pan or lighting proof exists.

Content continuation: a guarded V: CPU stage completed exit 0 under
`artifacts/homm3_conflux_full3d_phase6/` at 19:01 local. The staged v2
catalog SHA-256 is `45f2cb23cbf6910dd4ae2f83d76a4f5c4ef68a92dd68f0b6fca62bd2e000ce9c`;
`pan_coverage.npz` SHA-256 is
`7a33f7721beef691550918af7cc80dad18c177818c6ab46b495e3267331bc3d7`.
The validator independently re-extracts the native `cityHuman2` camera,
then passes 990,000 sampled rays at three aspects with zero proxy voids; its
stripped-outer negative yields 1.3% voids. Measured candidate gate time is
31 seconds; six focused tests and the installed phase-5 legacy gate also pass.
The content and validator fixes received independent source review. The editor
proof path now prepares six 1080p pan shots and default/left/right sweep shots
at 4096x2160 and 21:9 with runtime-equivalent aspect scaling. This source
work is still unstaged and uncommitted; no Unity bundle/render or game install
has run. The earlier Claude-at-handoff "Next execution" stage and gate steps
are now historical; Unity bundle/readback, editor pixels, vanilla comparison,
then coordinator-controlled runtime proof remain outstanding. The 0.5 m
triangle-height raster and vertex intrusion check are not exact pixel proof,
and the native spline basis/fly-to paths remain unrecovered.

## Product decision and prior delivery

The user rejected a mixed sprite/mesh Conflux town. The destination is a complete
3D city-world in native `cityFactory`: all building levels, terrain, skyline,
decor, water, lava, and effects, with native `BhBuilding` interaction and CityUI.
The original task required a source inventory, careful reuse before spending
Meshy credits, an offline Unity bundle, start/mid/full camera renders, a
no-sprite/full-3D validator, and a handoff without agent-side game installation.
The phase-1 inventory is `tools/homm3_town_scene_meshes/conflux_full3d_inventory.json`;
the detailed build and spend ledger is `docs/homm3_conflux_full_3d_town.md`.

The committed progression is 833433d820 (first complete 3D candidate),
71b9c93e1a (HoMM3-only sharp background, facing, footing, river/effects),
be630a9891 (vanilla terrain texture detail), 5603d7c2c9 (near field and water),
853157bc12 (HoMM3 building-animation effects), and 2b14650f74 (phase-5 near
detail and seam). Runtime support was committed in 856b1f29eb. Total recorded
Meshy spend is 318 credits; phases 2-5 reported no new spend. No new Meshy call
is planned for phase 6.

The phase-5 catalog and bundle were installed by the coordinator in
1a9929b8f1. Current readback: catalog SHA-256
`d203bf82907b709389e1c79b013ce9aea4c2cdd3f8aefffefb88b5c87790fad9`,
bundle SHA-256
`6005e85e7f045c47b3eb112413d7c53a72b03dcd00b9138577eab65cbbe8d115`
(114,574,117 bytes). F:/homm3_conflux_full3d/bundle still has those same
phase-5 hashes. The user has seen the town in game and says it looks better,
but has now found a camera-pan coverage failure. The phase-5 doc's final
"not installed" line is stale relative to this installed readback. Its near
field is visually improved, but its far-to-near sharpness metric did not meet
the requested monotonic trend. A silhouette-bridging curtain streak was also
noticed during the phase-6 pan investigation; peripheral filler does not fix it.

## Current user request

"The default camera actually does pan around for a dramatic look at everything,
and it exceeds the bounds of your projected terrain on the left and right sides.
It needs more filler on the outside. Compare to vanilla scenes for reference."
The coordinator requested: measure intro sweep, idle drift, and fly-to/building
paths from native camera assets/decomp rather than extrapolating the default
frame; compute the view-frustum union at 16:9 and wide aspects; inspect 2-3
vanilla towns across the pan; extend Conflux in the vanilla idiom (terrain,
forests, rock/cliff ring, sky/horizon and river) while keeping the default
HoMM3 image registration; add a negative pan-coverage validator; and present
vanilla | phase 5 | phase 6 at pan extremes. Offline/editor renders are
generated-artifact evidence only. Do not install; hand the coordinator hashes.
The account budget relayed to Claude was about 7,390 credits left with a
500-credit reserve. Original HoMM3 art and building art are the only Conflux
painting references; do not derive new scenery from the old blurred 2D
backdrop or its outpaint. Reuse of appropriate vanilla assets is permitted.

## Camera and world evidence

`extract_city_camera_pan.py` reads six vanilla city scenes and their
`SoCityCameraSettings` from installed Golden Era assets into
`vanilla_city_camera_pan.json`. This is game-asset/static evidence, not a live
capture. For `cityHuman2` (level67), `CityCamera` is the pivot/look-at target at
approximately (74.46, 2.65, 35.46), and the child `MainCamera` rest position is
approximately (73.28, 6.42, 4.73), FOV 47.6 degrees. Settings `human2` contain
9 loop position nodes, rotationSpeed 6, cursor delta angles 3 and 2 degrees,
maxMovementSpeed 4, and a 0.5-second mode transition. The first and later
sweeps have separate speed curves. GameAssembly disassembly recovered the
controller's Default, Cursor, and Free modes: Free moves on the path and calls
`Transform.LookAt` on the pivot. The exact spline basis was not recovered, so
`conflux_town_camera_pan.py` conservatively samples closed Catmull-Rom and
polygon paths, both LookAt and rest-rotation envelopes, plus mode transitions.
There is no current proof that every possible fly-to/building path is included.

The Conflux mesh is authored in the default camera's coordinate frame:
`ctx.local(w) = ((w - cpos) @ C) * 0.5260094536051652`. The original terrain
mesh is a projection of a 1920x1080 default view; the HoMM3 art occupies only
x < 1440, y < 673. The conservative pan reaches roughly -50 to +47 degrees
versus a default frame near +/-38 degrees. The user plays at 4096x2160; the
pan code also samples 16:9 and 21:9. The phase-5 coverage probe found about
6% uncovered rays across its sampled poses and up to about 20% in one pose.
These numbers are model/static estimates, not live camera traces.

The vanilla `cityHuman2` asset study found terrain plus `grass_mountain`
pieces extending around the view (approximately -97 to +139 degrees, to about
140 m), with conifer/rock dressing and linear fog at roughly 16-92 m. That is
the reference for peripheral coverage, not permission to copy its terrain
unchanged. The original request also asked for 2-3 vanilla pan screenshots or
renders: only extraction and an exploratory cityHuman2 software render exist
so far; the requested comparison sheet has not been produced.

Important runtime dependency: `Homm3TownScene3d.EnsureRoot` currently calls
`PlaceRoot`, which sets the scene root to the *current* camera position and
rotation on every reconcile. Phase-6 static geometry and pan proof assume the
root remains seated at the camera's **rest pose** while the camera moves. The
coordinator owns `Homm3TownScene3d.cs` and
`Homm3FactoryCityWorldVisuals.cs`; the content agent was explicitly told not
to edit them. Before installing phase 6, specify and validate a native-friendly
rest-pose seating change, preferably derived from the controller's pivot and
MainCamera rest local transform, rather than freezing an arbitrary first
observed pose. Preserve the existing aspect/FOV scale and default-frame
registration. This is a dependency, not a proven runtime fix.

## Phase-6 worktree at handoff

Claude created uncommitted
`tools/homm3_town_scene_meshes/extract_city_camera_pan.py`,
`vanilla_city_camera_pan.json`, `conflux_town_camera_pan.py`, and
`conflux_full3d_periphery.py`. The last builds an outer XZ heightfield, blends
the phase-5 projected edge into it, continues rivers, makes polar outer mesh
pieces/texture bakes, reuses existing conifer/bush/boulder meshes as scatter,
and writes a coverage raster. Its outer mesh removes deep in-frame triangles,
pushes overlap behind the phase-5 surface, and checks default-frame intrusions.
`build_conflux_full3d_scene.py` now calls `P6.build`, declares
`phaseRevision: "6"`, `periphery`, `panCoverage`, and pan proof poses.
The editor-only `unity/Homm3TownScene3dBundleBuild.cs` has a `PanPoseSpec` render
loop. `tools/validate_town_scene3d_contract.py` has a new phase-6 raster
raymarch and an outer-coverage-stripped negative check. These edits are
**unvalidated**; no phase-6 bundle or catalog has been built, installed, or
seen in game. The main Conflux doc and inventory JSON have not received a
phase-6 section/key. No phase-6 commit exists.

The transcript ends after Claude launched `memgate.py --wait 6`, then a
3,000-second `stage` command writing
`F:/homm3_conflux_full3d/work6/stage6.log`. At this checkpoint the log ends
in texture/mesh warnings (last write 17:00:52 local), with no appended `rc`
line; the phase-6 coverage file is absent and the F: bundle remains phase 5.
Do not start a competing stage or Unity session until this job's state is
established. A `Get-CimInstance Win32_Process` check in this session returned
Access denied; the Claude task explicitly says to report denied permission,
not work around it. The transcript's stage command did not show the requested
game-process guard immediately before it. Do not infer that a game guard passed.

The pan validator is a contract candidate, not a passed gate: it constructs
roughly 0.9 million sampled rays over three aspect sets at its current
settings and raymarches positive and negative cases. Benchmark and reduce
that cost if needed before wiring a normal build/deploy gate. A dilated
coverage raster can hide small geometry gaps, so editor pan renders remain a
separate acceptance check. `pan_coverage.npz` is a candidate-side dependency:
packaging must keep it beside the catalog for the validator, or replace it
with a durable, validator-readable representation before deployment.

## Next execution and ownership

1. **Content agent, exclusive:** resolve the earlier stage job; own only
   `tools/homm3_town_scene_meshes/{conflux_full3d_periphery.py,conflux_town_camera_pan.py,extract_city_camera_pan.py,vanilla_city_camera_pan.json,build_conflux_full3d_scene.py,unity/Homm3TownScene3dBundleBuild.cs}`,
   the phase-6 part of `tools/validate_town_scene3d_contract.py`, the phase-6
   sections of the Conflux doc/inventory, and the V: phase-6 scratch/output.
   First prove a successful stage and run focused validator
   positive/negative checks. Then obtain the requested vanilla pan comparisons,
   build through `unitylock`, inspect default and pan-extreme renders, and
   produce a comparison sheet. If coverage fails, fix the one outer-world
   solution rather than adding a silent fallback.
2. **Coordinator/runtime owner, exclusive:** inspect the live town camera and
   the rest-pose seating issue; own any changes to
   `Homm3TownScene3d.cs`/`Homm3FactoryCityWorldVisuals.cs`. Review how the
   phase-6 catalog and coverage dependency will be packaged and validated in
   the normal build/deploy. Do not install until the bundle, catalog, validator,
   render proof, and runtime seating agree. Only the coordinator installs while
   the game is closed and seeks user-visible gameplay proof.
3. **Review agent, after meaningful code is ready:** check instruction drift,
   guessed camera behavior, silent fallbacks, validator cost/false passes,
   obfuscated-name ownership, material/scale/registration and native-friendly
   design. Keep changes scoped; do not modify either implementation lane during
   review.

Before any Blender or Unity run, use a permitted game-process guard and wait
if the game is running, then run `memgate.py`; Unity must launch via
`tools/homm3_vfx/unitylock.py`. Never launch, stop, or kill the game. Put large
new scratch on V:, avoid large tree scans, do not edit shared
`tools/homm3_def_retarget/*.py`, and do not use Meshy for adventure-map
buildings. Preserve other agents' dirty files/index; commit only owned paths
with `git commit --only -F <UTF-8-no-BOM-message> -- <paths>`, no push/amend.
Claude's required message footer was `Co-Authored-By: Claude Opus 5.5
<noreply@anthropic.com>`; a new agent should attribute only its own work.

Evidence: Claude transcript
`C:/Users/<user>/.claude/projects/V--Games-Olden-Era-Playtest-Tweak/aeba9e69-0217-4c63-98f4-71a64ce15d89/subagents/agent-a60bf6cb5e1f1a47d.jsonl`
(especially the continuation summaries at lines 4348, 4659, 4913 and the
last actions at 5105-5211), current source, F: candidate readback and active
Golden Era catalog readback. The transcript summaries were cross-checked
against files rather than treated as current proof.
