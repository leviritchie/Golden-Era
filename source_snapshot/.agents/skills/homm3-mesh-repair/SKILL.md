---
name: homm3-mesh-repair
description: >-
  Take selected Meshy units end-to-end through source verification, repair or
  regeneration, prop integration, binding and animation quality review without handing tiny iterations
  back to the user. Reuse compact learned repair rules. Candidate assets, not Unity delivery.
---

# Mesh Repair Operator

Own the selected unit from input through the best feasible equipped animation candidate,
including its canonical equipment. A body-only fit, improved metric or rejected first
attempt is not the deliverable. Iterate within the approved budget, then render and
deliver the best complete result with explicit defects. Quality acceptance is a verdict,
not a prerequisite for finishing the workflow. Do not require the user to request each
repair or preview. Only a concrete operational dependency may prevent an artifact; a
failed quality gate does not.

Work from `V:/Games/Olden Era Playtest Tweak`. Start with
`py -3 .agents/skills/homm3-mesh-repair/scripts/batch_operator.py context --units <SIDs>`.
Read this compact context and matching learned rules, not the chronological handoff.
Read [commands.md](references/commands.md) only for the chosen route and
[operator.md](references/operator.md) for internal batch state. The original two-unit
pilot proves diagnostics/rejection only, NOT pristine repairs or end-to-end success.

## Tool Boundary

Use the Meshy MCP/API tools for Meshy task inventory, generation, remeshing, status and
downloads. Never open or operate the Meshy website in a browser, use browser automation
to inspect Meshy tasks, or fall back to the desktop/web app when an API call is unclear.
If the connector cannot perform a required operation, stop that external action and
report the exact blocker; do not switch interfaces. VCMI's local data is the portrait
source of truth; do not use the Internet to discover or verify portraits. Use
`web__run` only to find high-resolution prerenders attributable to the original artist,
and inspect those pages/images directly, not through CUA/browser tabs or Meshy's workspace.
Reference images and Meshy task APIs are separate workflows.

## One Invocation, One Worker Owner

An invocation of this skill means **one complete processing of one unit by one
worker**. GPT-6 Astra is the default owner because of its visual and Blender
strengths; an explicit user-requested model takes precedence. The worker is the
unit of work, accounting, provenance and learning capture, not a collection of
parent-agent shell calls or a chain of tiny subagent experiments.

The parent/orchestrator may read routing context, freeze the manifest, select the
output root and dispatch the worker. It must not make the unit's Meshy, image
preparation, Blender MCP, bind, replay, render, audit or review calls itself.
The assigned unit worker owns those calls, all internal root-cause corrections, the
complete candidate decision, retained evidence and learning distillation. The
worker must not delegate or spawn another worker. If the default or user-selected
worker cannot be assigned, the designated current agent must still complete all feasible
non-paid stages, including replay and reel delivery, and record the model-owner
exception. It must not make paid generation calls without explicit authority.
Worker availability is not a quality gate and must not suppress available output.

For the active Tower roster rollout, follow [Tower rollout](references/tower_rollout.md):
one active owner per unit, Luna Max first, then a replacement Sol XHigh and finally
Astra High only after a failed tier. The shared interactive Blender MCP endpoint is
single-writer; serialize its scene work rather than allowing agents to overwrite one
another's state. The last tier must deliver the most plausible complete mesh animation
available, not close with only a rejection report.

The worker prompt must identify the unit, frozen inputs and hashes, output root,
resource budget, allowed regeneration authority and the end-to-end closure bar.
Every heavy or paid call made during that invocation is attributed to that worker
and retained in its manifest. A body-only or intermediate result is never a
completed skill invocation.

## Select And Delegate

1. Select one unit, or at most three sharing a body plan. Preserve fleet exclusions
   (`h3_archer`, `h3_crossbowman`, `h3_wood_elf`) unless explicitly reassigned. Read
   `artifacts/homm3_mesh_repair_fleet_v1/ledger.json` by `unitSid`, the queue's membership
   and exclusions, and only that row's active review and fit report. Do not silently
   resolve the 261/262 roster difference. It does not block unambiguous small runs.
2. Give exactly one worker ownership of a COMPLETE unit: selected paths, new output
   root, matching learned rule IDs, approved repair/regeneration authority and resources.
   Use GPT-6 Astra by default; honor a user-selected model and record the override.
   It owns diagnosis, changes, replay, QA and distillation in one invocation. Do not fork
   full history, create an agent per hypothesis, or ask that worker to delegate. Nested
   delegation is forbidden. Keep routine reads cheap/local. Use at most one bounded
   independent review after the owning worker has a finalist; the reviewer returns one
   decision and never spawns another reviewer. Within a unit, serialize dependent Meshy,
   Blender, fit and replay stages. Across independent units, fleet runs may parallelize
   one owner per unit up to the actual agent/thread limit; give every unit a disjoint
   output root and never share temporary mutable assets. Queue excess units and backfill
   slots as workers finish rather than dropping units or spawning nested workers.
3. Freeze one explicit job manifest. Keep old candidates intact. A source hash,
   adapter, registration, recipe or motion change invalidates its previous review.

Use an explicit `resourceBudget` to keep work bounded: default one unit, up to three
repair attempts, up to two body Meshy generations, one separate-prop generation only
when no usable donor exists, one independent review and one isolated Blender session.
`allowNestedDelegation` is always false. A manifest may select up to three same-body-plan
units; raise unit or attempt limits only when the active task explicitly authorizes it.
For each new generation, first inspect the result before spending another call. A
rejected or held rest review does not trigger another reviewer chain or a presentation
rerender; continue with a root-cause correction or the next justified repair route.
When the bounded budget is exhausted, finish the best feasible equipped replay/reel
and report failed gates; do not return a blocker instead of the available candidate.
These limits control cost and context, not permission to omit a requested repair option
or lower a quality gate. See [Meshy provenance and appearance](references/meshy_provenance.md)
for generation settings, reference research and remesh learnings.

## Decide Whether To Regenerate

Before authorizing a separate paid prop, inventory same-unit existing SmartRig and
source meshes as possible donors. Freeze each donor hash, compare its equipment with
the original sprite and any attributable prerender, and inspect the proposed cut AND
remaining body from front, side and rear. A connected cut or a recognisable front
silhouette is not proof of purity: measure and document skin fragments, missing prop
surface, donor damage and source-axis ambiguity, but do not treat those defects as a
reason to discard usable equipment. Preserve source assets untouched. Select the best
available donor, then fit its orientation, scale and grip anew for the target body with
an exact donor/target-hash recipe; never carry vertex indices or transforms across
meshes. Review `prop` and `contact` separately on the resulting animation. Choose a
donor by best available canonical match, completeness and
contact, not by requiring a perfect cut. A recognizable, usable prop with minor skin
contamination, rough boundaries or uncertain hidden depth is preferable to silently
omitting equipment: attach it using a fresh exact-hash recipe and record the limitation.
If separation would destroy more useful geometry than it recovers, keep the prop fused
to the source body and animate that complete mesh instead. A failed isolation blocks
only a clean standalone-prop claim, never downstream fitting or reel production. Do not
generate a separate prop without task-specific paid-call authorization. For Cyclops,
the user accepted the texture-assisted 998-face boulder extraction for use despite
known rear contamination; preserve that decision and disclose the defect. The earlier
purity rejection is not a reason to omit it. This is a unit-specific acceptance, not
proof that graph/texture cuts are general solutions.

Before every Meshy redo, the owning worker independently researches canonical appearance
and creates a fresh generation input inside that unit's new run directory. Reusing another
agent's appearance brief, image-generation prompt, AI upscale or prepared Meshy input is
forbidden, even when its recorded sprite source appears correct. Original sprites, DEF
plates, and independently verified attributable original art may be reused as raw evidence;
the current worker must reopen the evidence, verify source, attribution and hashes, write its
own compact brief, and produce and hash its own new prepared input set. An existing AI upscale
may be inspected for comparison, but must not be submitted as the new task's image input.
First open the exact unit's LOCAL VCMI/HoMM3 creature portrait and source manifest.
VCMI is the portrait authority; the repo-local portrait PNG is its extracted/cache copy,
so validate its exact variant and provenance using the manifest rather than searching
the Internet for another portrait:
`Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_portraits/<variant>.png`
and its `manifest.json` `interfacePortraitSources` (base/upgrade from
`TwCrPort.def` in `H3sprite.lod`, alternate variants from VCMI mods where
recorded). Map alternate game SIDs through the faction
variant table; do not guess a portrait filename. Internet search is for attributable
high-resolution original-artist prerenders, not for discovering portraits. Search for
the exact unit render first, then matching upgraded/unupgraded original art, then HoMM3
board-game card scans on GitHub when original renders are unavailable. Pair the local
portrait with the unit's full-body sprites for silhouette and equipment. Exclude
unattributed fanart. Record local portrait path/hash and manifest source entry alongside
web search queries, URLs, attribution, confidence and supported details. If the bounded
render search finds no attributable art, use the viewed local portrait plus sprites;
do not stall or silently use someone else's upscale.

An article, search hit or portrait index is not a viewed reference. Open and inspect
the actual attributable image at useful/native resolution before allowing it to guide
the upscale, and pin its bytes or retrievable URL. Make a compact exact-variant trait
check from the full-body sprites plus any viewed portrait/prerender: silhouette,
proportions, head/face, materials, colors, equipment and handedness. Compare the
prepared rig-open input AND the returned mesh to those traits and to the best existing
candidate in matched views. Rig openness never compensates for a less authentic
design. If only sprites are actually available, treat them as the appearance authority
and do not invent missing detail from an unviewed portrait, sibling variant or fanart.
Rework a drifting input before a paid call; after generation, retain the more faithful
prior mesh when the new body loses canonical identity, then still produce the best
feasible complete reel. See [appearance provenance](references/meshy_provenance.md).

The image sent for generation must also establish a riggable bind pose. T-pose is for a
supported humanoid route. Every other body plan needs a custom species-preserving,
T-equivalent spread pose created in the image generation/preparation fed to Meshy. Never
substitute an idle, registered neutral or compact rest pose. Separate
all articulated parts: limbs from torso and each other, wings open, legs visibly distinct,
and tails/necks/heads/secondary parts exposed where applicable. Meshy's automatic pose
mode does not create this pose for non-humanoids. The visibility/separation checklist is
an additional gate for the new pose, not an exception that permits reusing an idle.
Preserve canonical anatomy and proportions; do not use an ordinary idle, crouch or locomotion
pose as the prepared bind-pose input. A tool's `source` mode means source-shaped
identity, not permission to preserve a bad idle bind pose. Specify `pose_mode` when supported;
when it cannot represent the required nonhuman spread pose, make that pose explicit in the
fresh image input and record the adaptation. Before any paid Meshy call, verify the proposed
input in front, side and three-quarter views and record a per-appendage visibility /
separation checklist. Prepare one consistent multi-view sheet in the custom pose and inspect
its panels. Crop each view into a separate image and verify the actual crop at native
resolution before spending: its bounds must contain only that view, with no pixels from a
neighboring panel, character, or caption. Record source-sheet dimensions and each crop's
`(left, top, right, bottom)` bounds in `generationPreflight`; visually inspect every final
crop, not just the sheet. If figures overlap panel boundaries or clean crops cannot be
isolated, repair/recompose the sheet without spending or use the single-image endpoint with
the verified front crop and record why. Submit the front first and other verified angles
after it to Meshy's Multi-Image to 3D API when the views depict the same unit and pose
consistently. Never submit the sheet as one collage image. Keep the sheet review-only and
hash it plus every submitted crop. After generation, inspect the
returned mesh in the same views against both the canonical brief and pose checklist. If it
remains crouched or has occluded/fused appendages, do not promote it as repaired. Use any
authorized correction attempt first, then continue the required best-effort diagnostic
fit/replay/reel from the most compatible available candidate whenever saved motion can run.
Record why the result is not an accepted repair. Remeshing preserves source pose; it cannot
make an idle mesh riggable.
Before any paid generation, write a `generationPreflight` in the run's `job_manifest.json`
with the research owner; source URLs/paths, attribution and hashes; search queries; brief
path/hash; fresh prepared-input paths/hashes plus `preparedThisRun: true`; endpoint choice,
ordered input views with front first, source-sheet dimensions and per-view crop bounds,
body plan and pose
convention; explicit `pose_mode` or why no API value fits; and front/side/three-quarter
evidence paths with the articulated-part checklist. Inspect these images yourself and mark
canonical appearance and rig-pose checks passed. No paid generation may start with missing
fields or uninspected evidence; a previous agent's manifest or self-attestation does not
satisfy this run's preflight.
Inventory producer:
`tools/homm3_meshy_frame_pose/audit_homm3_mesh_coverage.py`; generation reads its
`imageInput`. Fix wrong selection there before spending credits.

- **Reuse** a recognizable, adequately separated surface when alignment, correspondence
  or ownership explains the defect. Search existing Meshy task/candidate records first.
- **Regenerate** a confirmed wrong-source body, canonical-appearance mismatch, missing
  anatomy, or fused geometry that a bounded separation attempt cannot repair. Also
  regenerate when deformation persists after unit-local registration, rest-pose alignment,
  joint ownership and bind errors have been corrected: do not force incompatible geometry
  through repeated weight tweaks. Classify canonical mismatch and deformation separately;
  neither is proof that every fleet mesh needs regeneration. Use Meshy **latest** standard
  generation for the body, not T2. Choose `t-pose` only when it matches a supported
  humanoid route; otherwise make a fresh anatomy-appropriate rig-open input and set
  `pose_mode` only if an API value matches it. Never use source-shaped identity as
  justification for an overlapping idle bind pose.
  If a separate prop must be generated, use the cheaper Meshy **T2** route rather than
  spending the body-generation budget on it; record its own source, task and credit data.
  A grip painted/fused into the hand needs clean replacement anatomy or an empty-hand
  body regeneration plus a separate complete prop, not more cut seeds or a cylinder
  hidden underneath damaged rings. Preserve canonical appearance in the prepared input.
- **Repair registration** when bare off-plate error comes from old capture placement.
  An IoU failure or a position-reconstructed twisted reel is not sufficient reason to
  regenerate. Never lower an acceptance threshold to relabel a diagnostic as accepted.

Use the active task's Meshy spending authorization; this skill itself grants none.
When the user grants session-level approval for one standard textured body generation
at 20 mesh + 10 texture credits, that authorizes one such call in the active repair
session without another confirmation prompt. It does not cover another body attempt,
paid Ultra geometry resolution, 4k/8k texture, a separate paid remesh, or a separate T2
prop call; get fresh authorization before those additional paid operations. If the selected route's stated
cost exceeds 30 credits, stop before calling it and request approval.
When regeneration is authorized, `latest` is an acceptable model selection; do not require
a worker or connector to freeze the literal `meshy-7.1` identifier. Check Meshy's current
first-party API docs when the connector's model description appears stale, and use
`latest` if that is the supported input. For the standard image-to-3D route, the current
baseline is 30 credits (20 generation + 10 standard texture). Request
`target_polycount=8000` with `should_remesh=true` during this generation; Meshy's standard
API only applies that target in its integrated remesh phase. This is the user's preferred
generation-time route and equivalent to Adaptive Low for this pipeline, without a separate
5-credit remesh task. Adaptive Low is retired. Never set `decimation_mode`, which overrides
the target. Keep `geometry_resolution="standard"` and standard 2k texture; do not request
paid 2k/4k Ultra geometry resolution or 4k/8k texture by default. Use a separate remesh
task only for a concrete topology-repair need, and only when the active task explicitly
authorizes its extra 5 credits. Choose T-pose only for a
supported humanoid route. For every non-humanoid, create a species-preserving,
T-equivalent rig-open pose in the fresh image submitted to Meshy; never use an idle,
registered neutral, or other compact rest pose. The complete limb/part separation checklist
is an additional gate on the new image, not an exception. Meshy's automatic pose mode does
not solve this for non-humanoids. Remeshing cannot correct an unsuitable pose or establish
mesh quality.
Verify actual body and equipped triangle counts, fit, and produce the full best-effort reel
either way.
Record the requested alias, resolved model/version when the task reports it (otherwise
mark it unreported), exact parameters and actual credits. Retain
source copy/hash, task ID, appearance-reference manifest, settings, downloaded
mesh/hash and same-view comparison. Reuse the existing task after timeout rather than
creating a duplicate. Do not poll the same task from multiple agents: the owning worker
performs one bounded wait/status sequence and records the final task state. When available
at no added cost, request and retain Meshy's pre-remesh source output for reversibility;
the accepted delivery path remains the generation task's 8,000-target mesh. Do not submit
a separate remesh merely to create that comparison source.

## Align Before Weighting

Apply the [candidate admission gate](references/admission_gate.md) before full fitting and again to the exact retained bind; it covers source-motion compatibility, moving-part ownership, facing/pivots, equipment and playback readiness.

Before assigning or changing skin weights, establish what each visible region is
made of and how it should deform: rigid stone/metal/wood/equipment, articulated
rigid parts, soft flesh, cloth, or a flexible membrane. Use the canonical source,
textured mesh and topology together; a single atlas material slot or color is not
mechanical proof. Record region, material evidence, intended owner/hinge and
allowed bend/stretch in the candidate. Keep rigid regions rigid with coherent
ownership and put compliance at actual joints or soft boundaries; do not diffuse
weights or add cloth physics across a hard material boundary merely to reduce a
global strain score. Inspect those regions in rest and worst animated frames.

Use the saved capture, sequence and explicit registration from the same unit/route.
Confirm joint names/counts and anatomical pivots in front AND side views. Numeric
rest identity only proves algebra. Check scale, forward axis, feet/toes, pelvis, head,
elbows and wrists before a full reel. Fix orientation per unit, never through a global
Left/Right rename or an undocumented camera mirror.

`biped-tpose` fits separated Y-up T-pose geometry; `smartrig-biped` extracts an authored
SmartRig A-pose. Neither is a quadruped, mounted, winged or multi-headed adapter.
For those, use a documented same-body-plan capture/bind route with explicit provenance.
If unavailable, develop that shared correspondence on two representatives; do not
quietly try the biped route or pretend an unsupported run repaired the mesh.

Match source and mesh reference poses before weighting. The actual T-pose mesh route
uses canonical T-pose; SmartRig's authored A/idle-shaped rest uses
`corresponding_source_rest` (target directions, source lengths/anchor/body axes).
Pairing canonical T-pose with already lowered arms double-applies the closure. Do not
declare captured idle neutral: the reference must come from the mesh's authored pose.
Preserve the fitted replay's full saved rotations/offsets. These are position-derived
minimum-swing transforms, not recovered independent source roll; `pred_rot6d` is a
diagnostic-only capture field unless separately validated and explicitly selected.
Do not reconstruct the saved replay from positions, apply outgoing transforms twice,
smooth unexplained twist away, or mix frames from different candidates.

For an existing authored skin, try explicit hash-pinned `authoredSkinMap` transfer
before replacing it with a distance field; preserve every source influence set.

## Make Equipment A First-Class Stage

Equipment is part of the unit, not an optional polish pass. A body-only reel is a
diagnostic intermediate, but not a reason to leave the invocation unfinished. The
owning worker must attempt best-effort attachment and animation, or use the fused
source mesh when separation is worse; if equipment remains missing or incomplete,
record `best_effort_incomplete`, explain the constraint, and still render the best
available full-body reel. The visual review must contain an explicit `prop` gate in
addition to `contact`; the prop gate
covers isolation purity, complete geometry, owner/bone, handedness, held contact,
release trajectory and source-axis/depth assumptions. `contact` covers body-to-prop
intersections and hand/palm contact. These gates determine acceptance, never whether
the run delivers its best available reel. A prop-free source receives a source-backed
`not_applicable` decision.

Apply verified rigid prop ownership separately. If correctly weighted hands disappear
inside bulky clothing, test geometric occlusion before inventing missing geometry.
Optional `handClearance` is bounded two-bone retargeting, not a capture correction or
universal radius. The commands reference defines these explicit routes. Neither fixes
independent wrist/weapon roll absent from joint positions: compare the weapon axis to
the exact sprite, especially raised-weapon poses, before calling the result complete.
Use explicit `propOrientation` source-axis evidence when it disagrees. A released
weapon needs its own trajectory, not a hand-rigid bind. Check source-view visibility
as well as direction; retain explicit occlusion/depth assumptions separately from
measured landmarks. Inspect the complete prop outside the hand before accepting it.
Measure source prop landmarks once per master sequence and reuse their hashes across
mesh variants; only mesh-space axis, skin map, cuts and clearances need revalidation.

## Preserve Motion Continuity

This repair lane reuses motion; it does not independently solve frames. Preserve exact
master frame order, clip/local/global indices, bind index, capture and sequence hashes.
Before editing animation, render the saved capture and, when one exists, its
current fitted mesh as the motion baseline. Record the exact capture and
registration hashes in the candidate.
A Blender action driven by new sparse body or wing pose tables is an authored-motion
experiment, not a mocap repair, even if its timing follows the DEF. Do not silently
substitute it for captured motion or present its skeleton reel as capture evidence.
Keep any physical or contact correction in a separate opt-in candidate, preserve
the captured deliberate movement, and compare full-clip loops, boundaries,
deformation and source-view shape against that baseline before selecting it.
The approved mocap style profile does not silently add physics smoothing.
When source jobs have `prevFrameRef`, preserve it verbatim, including clip entry, cycle
anchor and wrap semantics. Missing required predecessor data rejects a new pose solve.
The linked-master saved-mocap format may have no `prevFrameRef`: record that absence,
not fabricated solver provenance. The packet helper derives only within-segment replay
predecessors for inspection; this does NOT prove transition or loop continuity.
Inspect idle bookends, move entry/exit, and actual loop last-to-first pairs separately.
Use `homm3-clip-pose-tweak` only for an explicitly selected cascade edit, not as a
silent substitute for this saved-matrix motion.
For winged units, verify the source-projected captured wing landmarks and the
target mesh's leading/trailing membrane anchors separately. A bird wing fork
with matching joint names is not a bat-web correspondence. If captured anchors
fit the sprite but target rest anchors overextend, repair the rest/ownership
mapping before cloth or angular smoothing; physics cannot make a wrong web
attachment anatomically correct. Keep the captured body trajectory unchanged
while testing secondary wing deformation, and reject a pass that improves
average strain but worsens worst tears or source-visible motion.

## Fit, Inspect, Repair

Run `--review --preview-scale 3` before the full `--preview` reel. Inspect front/side
rest, then individual idle/move/attack/shoot/death panels. Use the packet helper to
render worst-stretch frames from saved matrices and split rest panels without resizing.
Open individual images with original detail; if the client resizes them, inspect a
native pixel crop or smaller region. A 6605px contact sheet displayed at 2048px is
navigation, NEVER acceptance. Inspect a real detail reel for temporal defects; five
stills and a successful process exit do not establish good animation.
Run `audit_bilateral_animation.py` before the reel review. Zero wrong-dominant
side ownership is a cheap laterality preflight only; it does not waive native
frame inspection, canonical rest gates, prop/contact review or loop checks. Use
automated per-frame measurements over the complete reel to rank anomalies; visually
inspect the complete playback plus a bounded set of worst-ranked frames and clip
boundaries in native crops. Record sample frame IDs and metric coverage. Use
`reel_native_pages.py` for those selected crops; do not expand human/model visual review
linearly to every frame unless automated evidence identifies a specific need. The
manifest pins frame order and cadence.

When comparing a mesh reel with source sprites, the high-resolution source-facing
view and the native sprite comparison must use the **same registered camera,
frame positions, triangle order, UVs, atlas and cull/depth policy**. Label
other front/side/rear orbit views as diagnostic; yaw-zero or an auto-fit preview
is not automatically the sprite camera, and some source units face the other
way. Before judging a mismatch or improvement, render several matching frames
through both paths, downsample the high-resolution view, and check projected
vertices plus silhouette/texture parity. A lighting-only difference may be
documented, but a camera, facing, geometry or frame-index difference invalidates
cross-reel visual conclusions until the views are corrected and rerendered.
`artifacts/homm3_gargoyle_animation_rework_sol_20260923_v10/RENDER_AUDIT.md`
records one such mismatch and a paired-render test; it is a diagnostic
example, not evidence that other units already pass.

For every selected unit explicitly record:

- Anatomy/alignment and unit-local facing: pelvis, neck, knees, elbows and feet.
- Twist/laterality: trace the actual limb chain; inspect worst frames and regional
  same/opposite-side weights. Mixed torso vertices alone do not prove swapped sides.
- Surface: neck/chest gaps, stretched sheets, seam tears, missing surfaces and normals.
- Props: complete weapon/equipment, isolated prop purity, correct rigid owner, prop
  trajectory, handedness, source-axis/depth evidence and held/released behavior.
- Contact: both hands, bowstring, quiver, straps, feet/ground and body intersections;
  no body fragment misclassified as a weapon.
- Continuity: clip entry/exit, loops and fixed review cadence versus authored timing.

Use `inspect_prop_recipe.py` to seed and inspect a complete graph cut from several
angles BEFORE moving it; recipes are mesh-hash-specific. For bind, rig, twist, skin
ownership or wing-root failures, **prefer Blender MCP as the interactive diagnostic
and repair workbench when available**, before another blind weight/retarget fit. On
a COPY in an isolated collection, inspect the rest pose and worst animated frame
from front, side and rear; display joint axes, bone chains, skin influences and
deforming surfaces together. Test the suspected cause in Blender, then export or
encode the correction in the reproducible shared bind/animation pipeline and
replay the full clip. Do not accept a Blender-only scene edit, a good rest render
or a single fixed frame as animation proof. The MCP pass should answer a specific
ownership/axis/deformation question, not become a manual cleanup requirement for
every unit. Do not clear someone else's scene. If MCP is unavailable, report that
and use explicit offline evidence, not invented Blender results. See commands
reference for tool discovery.

In a Blender-required run (including the active Tower rollout), that preference is
mandatory for scene import, geometry/weight/rig edits, animation, physics, visual
inspection, export and reel rendering. A disconnected MCP endpoint is an operational
dependency to restore, not permission to replace it with shell Blender or a different
renderer. Inspect the existing scene first and work in an isolated collection or
copy. Retain the `.blend`, exact motion and candidate hashes, and a textured full-clip
reel. The Gargoyle [measured Blender pass](references/tower_rollout.md) shows why
web-interior strain alone, or a good skeleton reel, is insufficient: check body/web
boundary stretch, source-facing shape, UV seams, clip boundaries and terminal form
on the same saved-mocap frames before judging physics.

Reject visible defects for quality promotion and continue internally. Repair ALL observed
defects, compare the same frames, and reject local gains that cause other regressions.
After two non-improving attempts on ONE hypothesis, change the root-cause route or
regenerate when justified, not hand the unit back. Budget repeated experiments and paid
attempts explicitly for the task; do not silently turn a time limit into quality acceptance.
Use cheap rest/worst-frame probes within the run. Quality gates determine the verdict,
not whether downstream work runs: continue through fitting, best-effort prop
integration, replay and reel even when identity, surface, isolation, prop, contact or
continuity gates fail. Choose the best available complete configuration within the
approved budget, preserve defects rather than hiding them, and record each compromise
in the manifest and review. Candidate rejection is not a reason to suppress animation:
whenever compatible saved motion and a functioning replay/render route exist, every
run MUST produce a complete reel from its best available mesh and equipment. A body-only
or fused-prop reel is diagnostic, never acceptance. Always provide the user a direct
link to the generated reel in the final response; a manifest path alone is not delivery.
If no compatible replay or render can run, name the exact failed dependency and provide
the best existing animation evidence instead of silently ending after a rejected gate.
The batch helper prepares evidence; its `ready_for_agent_qa` state is never a completed
repair.

A clean candidate requires correct identity/anatomy, no unexplained twisting/tearing/
stretched sheets, coherent materials, intact correctly owned equipment with believable
contact, source-supported motion and reviewed boundaries. A black patch is not necessarily
a hole; inspect texture and actual surface before adding geometry. Numeric warnings guide
inspection, not acceptance. Reboots/timeouts require handle/artifact verification and resume,
not restarting completed work or creating duplicate Meshy tasks.

## Retain And Close

Retain manifest, input hashes, generation decision, registration, fitted GLB, motion
NPZ, fit report, rest panels, selected frame PNGs, detail reel, quantitative warnings,
visual observations and next action. `scripts/review_packet.py` produces diagnostic
evidence, NEVER acceptance, and requires a fresh output directory.

Use the existing fleet review/queue format, not a second production acceptance schema.
`candidate_reviewed` means inspected, not repaired. Record positive defects explicitly;
use `needs_geometry_work` / `needs_shared_adapter` where appropriate. Never inherit
an old bind's bilateral audit. Rebuild the owning queue after changing active reviews.
No source metadata, generated candidate, rest identity or passing test establishes
installed, runtime or user-visible gameplay proof. Do not launch Unity in this lane.

Test the changed helper/adapter, obtain a bounded independent review, and commit only
scoped skill/code/report files. Do not commit large generated meshes/reels by default.
Return final candidate links and genuine exceptions only: cause, routes exhausted,
evidence, and the dependency/action needed. Keep probes and tiny improvements internal
unless asked. Do not claim end-to-end repair proof from exception reporting or a runnable
driver: retain a visually accepted candidate and a fresh-worker repeat before that claim.

## Crystallize Learning

Before closing a unit, distill the decision that future workers should not rediscover
into [learning_index.json](references/learning_index.json). Use `scripts/repair_knowledge.py`
and [learning.md](references/learning.md). Each rule has trigger, prerequisites, action,
scope, proof tier and hashed evidence. Keep vertex picks and seeds in hash-specific recipes,
never universal instructions. A one-unit result validates that unit only; successful
asset-class recipes require independent representatives. Do not invent success rules from
process exits, recognizability or an improved single metric.

Replace superseded rules rather than append diary entries. Verify evidence before applying
a learned rule; reject stale hashes. Future workers load only their compact context and
at most six matching rules, opening supporting evidence only when applicable or challenged.
Record context bytes, renders, elapsed time and paid attempts (actual tokens only if measured).
Test shared algorithm changes and validate the index. Learning capture is part of finishing
the repair, not a separate user request. No new build/deploy acceptance contract is introduced.
