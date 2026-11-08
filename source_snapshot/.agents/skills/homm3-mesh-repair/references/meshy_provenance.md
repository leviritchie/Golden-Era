# Meshy Generation Provenance

## Appearance References

Before every Meshy redo, the owning worker performs fresh research and creates a new
unit-specific prepared image inside the current run. Do not reuse an AI upscale, prompt,
appearance brief or Meshy input made by a previous agent, even if that artifact cites the
right sprite. Reuse raw sprites and original-art evidence only after the current worker
independently verifies their source, attribution and hashes, writes a fresh concise brief,
and builds its own image input from them. Use this bounded source order:

1. Open the local VCMI/HoMM3 portrait for the exact creature variant at
   `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_portraits/`
   and its `manifest.json`. This local rendered PNG is the first source for face,
   headwear and upper-torso detail; pair it with the unit's full-body battle
   sprites for silhouette, limbs and equipment. Base/upgrade Tower portraits
   trace to `TwCrPort.def` in `H3sprite.lod` (also present in local VCMI data);
   alternate portraits may trace to a VCMI mod ZIP. Resolve the game SID through
   the faction's base/upgrade/alternate mapping before selecting a PNG: for
   example `h3_magnetic_golem` maps to `h3_golem_upg_alt`, not a same-named
   portrait. Inspect actual bytes and record the manifest's
   `interfacePortraitSources` entry and PNG hash.
2. Search the internet for an attributable HIGH-RES ORIGINAL-ARTIST prerender of
   the exact creature. If absent, search matching upgraded/unupgraded original
   renders or official art, always checked against the exact unit portrait and
   sprite. The web is not needed to discover the portrait.
3. If original renders are unavailable, use HoMM3 board-game card scans on
   GitHub as secondary art, paired with the local portrait and sprites.

Do not use unattributed fanart as a canonical source; fan designs can make large
creative departures. Use targeted web search (`web__run` search/image queries and page
opens), never CUA/browser tabs; Meshy website browsing is forbidden. If the bounded
original-render search fails, record the queries and prepare the strongest fresh
local-portrait-and-sprite-backed image. Never present an AI upscale as evidence of canon. Capture each
source path or URL, attribution, retrieval/hash when available, and which visual details it
supports. Preserve the sprite and prerender views together in the image preparation so
proportion, costume, face, equipment and handedness survive.

A page naming a portrait or a search snippet is NOT appearance evidence. Open the
actual attributable image, inspect it at a resolution where its claimed features
are visible, and retain its bytes/hash or stable source URL. If its image bytes
cannot be viewed, mark it `unviewed` and do not use it to justify headgear,
armor, face or color. Disambiguate base, upgrade and alternate upgrade before
borrowing variant art. When only the unit's battle sprites are viewable, those
sprites are the authority for visible form; do not fill hidden details with
generic fantasy design or another variant's portrait. Record supported traits
and uncertainty rather than a vague "canonical" label. The Stone Golem run
found a web portrait index but did not retrieve the portrait image; the local
portrait PNG and manifest were available and should have been opened first.

Create the actual generation input during this invocation. Prefer one `image_gen__imagegen`
edit/generation using the raw sprite plus the worker-verified canonical reference images;
save its prompt, input paths/hashes, output path and output hash in the run. A local
deterministic upscale/composite tool is also acceptable if it creates a new run-owned file.
Do not pass a pre-existing AI upscale from the shared AAA directory or another agent's
run to Meshy. The newly prepared image is still only an input proposal: inspect it beside
the original references for identity drift before using it.

Before paying Meshy, make a matched-view comparison of the exact unit's source
plates, every actually viewed original reference, the best existing mesh and the
proposed submitted crop. Check silhouette/proportions, face/headwear, material
placement, colors, appendage count, prop shape and handedness separately. Mark
what the rig-open pose intentionally changes and what identity must not change.
If the proposed crop is less faithful than the existing mesh or omits a defining
feature, revise it before generation; a clean spread pose is not an identity pass.
After generation, render new and old bodies with the same camera and lighting and
repeat the identity check before choosing a bind. Do not select a new mesh merely
because it rigs more easily, or discard an older more faithful body without the
canonical/deformation tradeoff. A failed new-body identity check still gets a
best-effort complete animation reel from the best available mesh.

The prepared image set must depict a riggable bind pose, not merely reproduce an idle
sprite's pose. Use T-pose for a supported humanoid. For every non-humanoid, create the pose
in the fresh Meshy input views: a species-preserving T-equivalent spread that exposes joints
and separates every articulated part without changing canonical anatomy. Meshy's automatic
pose controls do not do this for non-humanoids. A registered neutral, idle, or
source-shaped/crouched pose is never a substitute for this deliberately created spread
pose. Record the body-plan pose choice and a
visibility/separation check per articulated region before generation; compare the
generated mesh against that check before binding. When using a later separate topology
operation, review its output against this gate as well. Remeshing cannot fix pose or fused
ownership.

## Cost And Remesh Decision

Use Meshy's `latest` standard model for body generation by default when authorized.
`latest` is acceptable; do not require a literal pinned `meshy-7.1` selection. The API's
current `latest` mapping has been Meshy 7.1, but the alias is intentionally allowed to
advance. If connector descriptions lag behind the API, verify the first-party API docs
and use `latest` when it is supported. For the standard image-to-3D path, the current
generation-plus-texture baseline is 30 credits (20 generation + 10 texture). These repair
meshes do not justify the additional 5 credits for 2k/4k Ultra geometry resolution by
default. Standard geometry resolution and standard 2k textures are within the 30-credit
baseline; do not confuse texture resolution with Meshy's paid Ultra geometry pass.
An explicit user grant for one 20+10 standard textured body generation is session-scoped:
use it without prompting again for that call, but do not spend it on a second attempt,
paid Ultra geometry resolution, a separate remesh task or a separate T2 prop. Get fresh
authorization for costs or operations outside that scope.
For new standard single-image or multi-image body generation, set `should_remesh=true`,
`target_polycount=8000`, and `topology=triangle` on the generation request. Meshy's standard
API only applies this target when its integrated remesh phase is enabled. This is the
preferred route at 20 mesh + 10 standard texture credits; the user confirmed it is
equivalent to Adaptive Low in this pipeline while avoiding a separate 5-credit remesh task.
Adaptive Low's `decimation_mode` is retired; never pass it because it overrides
`target_polycount`. Meshy describes the target as approximate; verify and report the
downloaded mesh's actual triangle count rather than assuming exactly 8,000. The Multi-Image
to 3D API and MCP tool accept 1-4 separate views for `latest`/Meshy 7.1; the front view
must be first. Use the multi-image endpoint when a coherent same-unit, same-pose view set is
available. The textured multi-image route is also 30 credits; retain per-view hashes and the
ordered input list ([API](https://docs.meshy.ai/en/api/multi-image-to-3d),
[pricing](https://docs.meshy.ai/en/api/pricing)).

Before any paid multi-image request, record the review-sheet pixel dimensions and exact crop
rectangle for every submitted view. Inspect each final crop at native resolution, verifying
that it contains only its intended angle: no adjacent-panel pixels, second figure, or caption.
A sheet whose figures cross panel boundaries is not safely crop-able just because the intended
view is mostly present. Recompose or repair it without spending; if only the front view can be
isolated cleanly, use the single-image route and record why. Hash and retain the inspected final
crops, not merely the contaminated source sheet. This preflight is grounded in the Gargoyle
run, where nominal panel crops included part of a neighboring panel.

The dedicated remesh endpoint costs 5 credits and only accepts a completed Meshy task ID
or a public model URL; it does not take the generation-only `should_remesh` flag. Prefer
the successful generation task ID. Use a local-only GLB only if an approved, supported
API route can provide it; never upload through the website/browser. Remeshing is a
separate paid operation and requires explicit authorization. When available without extra
credits, retain the generation task's pre-remesh source for comparison; do not submit a
separate remesh merely to create that source.
Record the requested alias, resolved model/version if reported (otherwise mark it
unreported), exact parameters and actual consumed credits from the task response; do not
infer price from the UI or a prior task.

Use a separate explicit-target remesh only when a concrete over-density/topology need
remains after generation and the task budget explicitly authorizes its extra 5 credits;
do not fail-close or accept a million-triangle body merely because Meshy returned it.
Establish the source mesh pose before generation: use T-pose for a supported humanoid;
for a non-humanoid, create the custom T-equivalent spread pose in the input image. The pose
is part of the generated mesh, not a remesh parameter. Then fit the result and deliver the
best available complete animation reel; reducing polygon count alone does not validate
canonical identity, binding or deformation.

Fleet triage must score canonical appearance and animation deformation as separate
failure axes. A mesh may be canonical but unsuitable for the available skeleton, or
deform cleanly but depart from the original prerender. Recommend regeneration when either
failure is evidenced, but first rule out wrong registration, rest-pose mismatch, side or
joint ownership errors and avoidable bind defects. Do not generalize from two pilots to
blanket fleet regeneration; preserve the per-unit evidence and disposition.

If a separate simple prop must be generated, use the cheaper Meshy T2 route rather than
the standard `latest` body route. Treat it as its own generation task and record source references, settings,
task ID, downloaded hash and actual cost. T2 prop generation does not replace the
canonical-reference requirement.

Adaptive Low is retired for this pipeline. In the Goblin full-detail versus Adaptive Low
comparison, the user judged that Adaptive Low did not improve the mesh; most of the
apparent decline came from lighting differences. The preferred 8,000 target is requested
during generation to avoid the separate 5-credit remesh task; the user says this
generation-time route is equivalent to Adaptive Low in this pipeline. Do not misattribute
that result to a separate remesh API task. A separate remesh is exceptional and requires a
concrete topology need plus explicit authorization.
Do not read a thumbnail's shading as geometry evidence. Compare identical source poses
and camera/light settings when evaluating topology or appearance.

## Per-Generation Record

Each generation provenance record should retain:

- Source sprite and appearance-reference paths, attribution, hashes and concise visual brief.
- Exact upscale/prepared-image path and hash used as the Meshy input.
- Model/version, pose mode, geometry/texture settings, task ID, requested and consumed credits.
- Downloaded mesh path/hash and topology counts.
- Any remesh task, settings and cost, with a controlled same-view comparison and explicit
  decision (`improved`, `no_improvement`, `worse`, or `not_compared`).
- Whether the mesh is accepted for the next stage; a cheaper configuration is not itself
  a quality verdict.
