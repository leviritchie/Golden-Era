# Operator Commands

All commands run from the repository root in PowerShell. `py -3` must provide numpy,
Pillow and the existing pipeline dependencies. Store output on V:. Commands are
source-verified; see the retained pilot report for which branches were actually run.
Set `$unit`, `$mesh`, `$run`, `$registration`, `$out` explicitly for the chosen unit.
Do not run a template with placeholders unresolved.

## Compact Selection

Preferred entrypoint (prints selected fields plus at most six evidence-backed rules):

```powershell
py -3 .agents/skills/homm3-mesh-repair/scripts/batch_operator.py context --units h3_grand_elf h3_skeleton
```

Only inspect the raw row below when the compact context is insufficient. Run the unit
through the complete skill; these commands are internal stages, not separate user tasks.

```powershell
$unit = 'h3_grand_elf'
$fleet = 'artifacts/homm3_mesh_repair_fleet_v1'
$ledger = Get-Content "$fleet/ledger.json" -Raw | ConvertFrom-Json
$row = $ledger.rows | Where-Object unitSid -eq $unit
$row | ConvertTo-Json -Depth 8
Get-Content $row.repair.animationEvidence.repairReview
```

The queue membership and excluded pilots remain authoritative for selection. Read
only the selected fit report, review and named source image. For historical reasoning,
search `docs/handoff_luna_mesh_repair_fleet.md` for that SID and the latest checkpoint;
do not load thousands of lines into every subagent.

## Canonical Meshy Generation At 8K

These commands are run by the single assigned unit worker (GPT-6 Astra by default,
or the model explicitly selected by the user), not by the parent/orchestrator. The
parent may prepare the manifest and handoff, but it must not submit/poll Meshy or run
the worker's image-preparation, Blender, fit, replay or review phases. One worker owns
the complete unit invocation and its resource accounting.

Before a paid task, the owning worker researches the unit independently and creates a
fresh canonical brief and prepared image under the current run directory. Start from the
raw source sprite/catalog/DEF; do not submit an upscale or prompt made by a previous agent.
Reuse raw canonical references only after independently verifying their origin, attribution
and hashes. Use targeted `web__run` `search_query` and `image_query` calls, then inspect
source pages with `web__run` `open`; never use CUA, browser tabs, or Meshy's website. The
`job_manifest.json` must have `generationPreflight` before a paid generation: research
owner and queries; source URLs/paths, attribution and hashes; brief path/hash; fresh input
paths/hashes with `preparedThisRun:true`; endpoint and ordered submitted views (front
first); body plan, pose convention and pose-mode choice or omission reason; review-sheet
path/hash and pixel dimensions; each submitted view's exact `(left, top, right, bottom)`
crop bounds in that sheet; and a checklist of every
articulated part's visibility/separation. The owner reviews this evidence and records both
canonical and rig-pose checks as passed before submitting. The Hobgoblin example is
`artifacts/homm3_mesh_repair_positive_pilot_v3/canonical_reference/canonical_appearance_brief.json`.
Do not reuse its anatomy for another unit. External mirrors need their URL, hash and
attribution limit; AI upscales do not establish original appearance. Keep the fresh
prepared input, prompt, research queries and source hashes. Create that input inside the
run, preferably with one `image_gen__imagegen` call referencing the raw sprite and
verified canonical-art files; a new local deterministic upscale/composite is also valid.
Review it against the unmodified evidence before submission. The input set must be riggable
pose: supported humanoids use an explicit T-pose; non-humanoids require a custom,
species-preserving T-equivalent pose created in the fresh input image. Never substitute an
idle or registered rest pose. Create one consistent front/side/three-quarter review sheet
in that pose, inspect it, and crop each view to a separate image. When the views consistently
depict the same unit and pose, send them as separate `file_paths` to
`meshy_multi_image_to_3d`, with the front first; never send a collage as a view. This
Meshy-7.1/`latest` endpoint accepts 1-4 actual images. If reliable separate views cannot be
made, send the front crop to the single-image endpoint and record why. Retain/hash the sheet
and each submitted view. Before payment, open every final crop at native resolution and
confirm its recorded bounds contain exactly that view, without neighboring panel pixels,
another figure, or captions. If figures cross panel boundaries or a crop is contaminated,
recompose/re-crop without payment; if clean side views remain unavailable, use the clean
front-only fallback and record the reason. Spread every articulated part so joints are
exposed and limbs, wings, tails or other moving parts are visibly distinct. Meshy's automatic
pose mode does not create this pose for non-humanoids. After download, inspect the mesh in all
views against canonical identity and the complete separation checklist. Remeshing cannot
repair a bad pose.

For the standard repair, reuse an existing successful Meshy generation task only when
its source image, identity and rig-open pose match this unit. Otherwise create one
standard `latest` textured Multi-Image to 3D task from the prepared views with
`should_remesh=true`, `target_polycount=8000`, `topology="triangle"`, standard texture and
GLB output; leave geometry resolution at standard and omit `decimation_mode`. Put the front
view first. This applies the target in the generation task's integrated remesh phase. The
multi-image textured price is the same 30-credit baseline (20 mesh + 10 texture), avoiding
the separate 5-credit remesh task. Preserve the returned result and record endpoint, ordered
view paths/hashes, target, actual triangle count, task ID and credits. The result may differ
slightly from 8,000. When available without extra credits, also retain the pre-remesh source
output for comparison. The official endpoint accepts 1-4 views and is available for
`latest`/Meshy 7.1 ([API](https://docs.meshy.ai/en/api/multi-image-to-3d),
[pricing](https://docs.meshy.ai/en/api/pricing)).
Do not call `meshy_remesh` by default. Use it only for a concrete topology-repair need
after reviewing the generation result, and only when the active task explicitly includes
the extra 5-credit cost.

If a suitable successful Meshy task already exists, reuse its output and skip paid
generation. The remesh endpoint accepts `input_task_id` or a public
`model_url`; it does not accept `should_remesh`. Do not try a browser upload for local
files. If no task ID/public URL path is available, report that connector limitation and
continue the best-effort local fit/reel rather than switching to the web app.

The local `generate_meshy71_repair_candidates.py` helper accepts a single prepared image;
use it only for the single-image fallback. It sets `should_remesh=true`, so its
`--polycount 8000` target is integrated into that generation task, not a separate task.
For a multi-image run, call the MCP `meshy_multi_image_to_3d` tool with `file_paths` and
the same generation parameters instead. `source` means retain species identity, never
compact/idle pose; a non-humanoid's prepared views must all show the custom spread pose.
A humanoid uses `t-pose` only when its route supports it.

Inspect `homm3_mesh_coverage.json`'s selected `imageInput`, the intended AAA image and
`meshy71_repair_candidates/<unit>/<variant>/` before these paid commands:

```powershell
py -3 tools/homm3_meshy_frame_pose/generate_meshy71_repair_candidates.py start --unit $unit --variant $variant --source-image $preparedImage --attempt $version --polycount 8000
py -3 tools/homm3_meshy_frame_pose/generate_meshy71_repair_candidates.py poll --unit $unit --variant $variant --source-image $preparedImage --attempt $version --polycount 8000 --timeout-s 1800
```

Use `source` for a non-humanoid only to preserve its species/body-plan identity. Its
reviewed prepared image must already show a custom T-equivalent spread pose. Set
`$variant` to `source` or the supported humanoid pose. This isolates output in
`<unit>/<variant>/<version>/`; names cannot escape the
directory or use reserved Windows names. Choose a new version only for a justified
new paid attempt, not an uncertain submission.

`generate` combines start/poll and reuses a downloaded result only after source/settings
identity checks. `start` reuses the existing task, including failed tasks. Saved policy
and retained source hashes must match requested inputs; polling preserves that policy.
An uncertain submission is retained and refuses resubmission until its existing task ID
is recovered. Timeout does not cancel the remote task. Never delete records to retry.

## Biped Fit And Evidence

The pilot manifest is an executable example, not a fleet default. For a new unit copy
its field structure with `apply_patch`, set the correct body plan and a fresh output.
`sourceReport` accepts the selected static registration directly. Do not copy another
unit's registration, prop seeds or orientation. Only these two body plans are supported
by this fitter: `biped-tpose`, `smartrig-biped`.
Their reference construction differs deliberately: canonical T-pose for the former,
authored-direction corresponding source rest for the latter. `sourceRestConvention`
in the fit report records the choice. Refit older SmartRig outputs after this fix;
their code fingerprint is stale and replaying old matrices does not apply the repair.

Optional job inputs are explicit, source-hash-pinned JSON paths, not fallback flags:

- `authoredSkinMap`: `authored_skin_map.v1`, `sourceMeshSha256`, explicit `boneMap`
  from every positively weighted source bone to the target name, and
  `reduction: top4-renormalize`. Reads all contiguous JOINTS_n/WEIGHTS_n pairs;
  unmapped positive influences or changed vertex order reject. Review reported lost
  influence mass and the full body, not only ownership labels.
- `propAttachments`: inspected `prop_attachment.v1` recipe. Transfer body weights
  first; the prop recipe then assigns the isolated complete equipment rigidly.
- `handClearance`: `retarget_clearance.v1`, `sourceMeshSha256`, `maxCorrection`,
  `constraints` containing `hand`, `colliderStart`, `colliderEnd`, `radius`.
  Before outgoing skin conversion, exact two-bone IK moves penetrating wrists onto
  named capsules while retaining link lengths/pole/roll. Both elbow and wrist are
  budgeted. Singular, unreachable and overbudget corrections reject without clamping.
  Dimensions come from THIS mesh. It changes retargeted motion, not source capture;
  `motion.clearanceReport` records every correction. It is not smoothing or acceptance.
- `propOrientation`: `prop_orientation.v1`, mesh/registration/master/attachment hashes,
  explicit rest shaft endpoints, owner, prop name and new prop bone; one source-hashed
  axis record per saved frame. Measure visible pommel/head centers in the original
  plate coordinates; a visible shaft point supports direction, not base positioning.
  The selected registration supplies the camera. Held frames rotate the leaf hand
  and prop together; released frames leave the hand alone and place the independent
  prop head from its observed plate location. `source-visible-front-depth-plane`
  selects a constant released depth satisfying body/head foreground constraints using
  a measured `headRadius` and `visibilityMargin`. This resolves projected direction
  and visibility, not true source depth or axial twist. Inspect the result from sides.
  Occluded axes require explicit bounded reference-frame records, never fabricated
  landmarks. The Hobgoblin's final two death axes are explicitly held from frame 62;
  their head positions remain measured. Such an assumption is not observed motion.

For a confirmed missing shaft revealed by release, a prop recipe may include explicit
`shaftBridges` (`a`, `b`, `radius`, `sections`, `uvSourceFace`) in attached-rest space.
The cylinder belongs to the prop and reports generated faces separately from retained
source faces. Do not add it merely because the grip is hidden inside a hand or garment.

The combined executable example is
`artifacts/homm3_mesh_repair_positive_pilot_v3/hobgoblin_contact_manifest.json`.
Its source map, mace seeds and clearance dimensions are unit-specific. The completed
prop-trajectory variant is `hobgoblin_complete_prop_manifest.json` in the same directory;
consult its current visual-review evidence before any acceptance claim. Do not
generalize unit masks, clearance radii or occlusion decisions fleet-wide.

```powershell
$manifest = 'artifacts/homm3_mesh_repair_skill_pilot_v1/manifest.json'
py -3 tools/homm3_meshy_frame_pose/fit_mesh_rest_pipeline.py --manifest $manifest --units h3_grand_elf h3_skeleton --review --preview-scale 3
```

Open each front/side skeleton overlay. Correct anatomy before the full reel:

```powershell
py -3 tools/homm3_meshy_frame_pose/fit_mesh_rest_pipeline.py --manifest $manifest --units h3_grand_elf h3_skeleton --preview --preview-scale 3
py -3 .agents/skills/homm3-mesh-repair/scripts/review_packet.py --candidate artifacts/homm3_mesh_repair_skill_pilot_v1/h3_grand_elf --out artifacts/homm3_mesh_repair_skill_pilot_v1/grand-elf-review
py -3 .agents/skills/homm3-mesh-repair/scripts/review_packet.py --candidate artifacts/homm3_mesh_repair_skill_pilot_v1/h3_skeleton --out artifacts/homm3_mesh_repair_skill_pilot_v1/skeleton-review
```

Packet directories must not exist. Choose a new version when rerunning; don't destroy
the previous review. The helper does not alter the mesh, motion, queue or quality state.
It renders the usual first/clip-midpoint/worst-stretch panels plus at most eight explicit
additional indices supplied with `--frames`, checks the fitter's shared input/code fingerprint before labeling
saved motion, verifies matrix shapes/finiteness and selected source-plate hashes,
records file hashes and within-segment replay lineage, and splits the rest overlay.
It measures **absolute change in edge length ratio**, not the ratio itself. Tiny edges
can exaggerate relative error; the packet also retains absolute growth/body-height.
It does not calculate regional bilateral ownership or decide aesthetic acceptance.

Open `packet.json`, `rest_front.png`, `rest_side.png`, two worst frames and the suspected
prop/contact frame at original detail, then the candidate's `detail_reel.gif`. Expand
only on an observed issue. Review source plates at the exact selected frame indices.
The full reel uses 100ms review cadence, not authored game timing. Pose order being
preserved does not validate loops/transitions. Explicitly inspect those boundary pairs.

For a source-sprite comparison, save the registered source camera in the job and
render the candidate's same frame/mesh/UV/atlas at native and high resolution
through that camera. Downsample the high-res output and compare silhouettes
and textured interiors before relying on the comparison. Do not call an
auto-fit yaw-zero OpenGL preview the source-facing front view. Label orbit
front/side/rear separately. See
`artifacts/homm3_gargoyle_animation_rework_sol_20260923_v10/RENDER_AUDIT.md`
and its `test_render_contract.py` for a bounded paired-render example; those files
do not validate another unit by themselves.

Inspect all frames without client thumbnail loss (fresh output directory):

```powershell
py -3 .agents/skills/homm3-mesh-repair/scripts/reel_native_pages.py --reel "$out/detail_reel.gif" --out "$out-native-pages"
```

Pages retain native body pixels and frame IDs; `manifest.json` records every crop,
duration and image hash. They supplement GIF playback, not temporal acceptance.

Before spending time on a full visual review, run
`py -3 tools/homm3_meshy_frame_pose/audit_bilateral_animation.py --glb
<fitted_bind.glb>`. A zero wrong-dominant side count is only a cheap laterality
preflight; it does not establish smooth animation or replace the native pages.

For the separate paired-reel tool, fitted candidates require the explicit flags
`--candidate-motion saved-retargeted --candidate-motion-file <out>/retargeted_motion.npz`.
Do not accept the older position-derived default as this candidate's motion.
Its source panel may still use position-derived rotations: not twist ground truth.

## Props And Blender

```powershell
py -3 tools/homm3_meshy_frame_pose/inspect_prop_recipe.py --mesh $mesh --out $out --panel-scale 4
py -3 tools/homm3_meshy_frame_pose/inspect_prop_recipe.py --mesh $mesh --out $out --panel-scale 4 --pick 90:1280:1640
```

Pick coordinates are illustrative; choose visible pixels in YOUR individual PNG.
For the actual cut add `--recipe <mesh-specific-recipe.json>`, then inspect both prop
and remaining-body views. Use `docs/homm3_mesh_repair_workflow.md` for recipe fields.
Add `propAttachments` and `propOrientation` to the fit job and write a new candidate
directory. Do not close the unit on the body-only reel: the final review must include
the explicit `prop` and `contact` gates. A genuinely prop-free unit must record a
source-backed `not_applicable` prop decision instead of silently omitting the stage.

For suspected bind, rig, twist or skin-ownership faults, prefer Blender MCP when
available. Discover the `mcp__blender__` tools, read their descriptions and get
a scene summary first. Tools include
`get_objects_summary`, `get_object_detail_summary`, `execute_blender_code`, and
`render_viewport_to_path`; do not guess their argument schemas. Import only a copy
into a new named collection, preserve the existing scene, and retain the script and
screenshots on V:. Inspect the raw mesh before adding candidate motion. Test an
ownership hypothesis on one rest/failure-frame pair with joint axes, weight display
and front/side/rear renders, then check the corrected full reel. Convert useful
operations into the shared recipe/pipeline, not per-unit undocumented scene edits.
Use offline inspection when the MCP is unavailable or the bind question is already
settled by reproducible numeric evidence; record which route was used and why.

## Explicit Non-Biped Routes

Do not improvise a donor from the SID. Read that unit's adapter evidence and prove
capture joint identities correspond to the bind. An existing exact-reference route:

```powershell
py -3 tools/homm3_meshy_frame_pose/bind_from_exact_reference.py --run-dir $run --mesh $mesh --registration $registration --out-dir $out --clip g00_move --max-frames 3 --scale-source registered
```

`registered` is an EXPLICIT quadruped-scale decision, not a looser default: it trusts
registration scale and records the caveat. Use the normal extent policy where valid.
Read the audit, not just exit status. `bind_meshy71_candidate.py` can return zero and
emit a mesh with `auditOk:false`; emission is not acceptance.

`experiments/homm3_mocap_v2/register_smartrig_idle0.py --unit $unit --bind <bind.glb>
--clip <recorded-clip.json> --manifest <corpus.json> --out $out` creates only an idle
reference from explicit SmartRig `Orientation` provenance, not full motion. Never
infer its orientation by renaming bilateral joints. Mounted-plus-winged subjects
need horse, rider AND wing correspondence, not an eagle-only substitute.

Do not use `rebind_idle0_existing_capture.py` as generic replacement topology weight
transfer: it reuses fitted weights and recursively deletes existing output. Do not
run authored fleet dispatchers as hidden recovery; some allow best-effort defects.
Unsupported routes require a bounded shared-adapter experiment with retained negatives.

## Review Record, Tests And Queue

Record per-unit generation decision, source status, input hashes, selected frame IDs,
individual panel/reel paths, observed defects, orientation, continuity and ownership
checks, disposition and next action in the existing fleet review format. Keep the
newest review explicitly selected; the queue's review discovery is not visual QA.

```powershell
py -3 -m unittest discover -s .agents/skills/homm3-mesh-repair/scripts -p test_review_packet.py
py -3 -m unittest discover -s .agents/skills/homm3-mesh-repair/scripts -p test_batch_operator.py
py -3 -m unittest discover -s .agents/skills/homm3-mesh-repair/scripts -p test_repair_knowledge.py
py -3 .agents/skills/homm3-mesh-repair/scripts/repair_knowledge.py validate --verify-evidence
py -3 -m unittest tools.homm3_meshy_frame_pose.test_smartrig_biped tools.homm3_meshy_frame_pose.test_fit_mesh_rest_pipeline tools.homm3_meshy_frame_pose.test_rest_retarget
py -3 tools/homm3_meshy_frame_pose/build_mesh_repair_fleet_queue.py --out artifacts/homm3_mesh_repair_fleet_v1
```

Run the queue rebuild only after intentional fleet review changes, not for this
isolated skill pilot. The builder rewrites queue, ledger and neutral audit; `--out`
does not redirect its input roots. This skill introduces no build/deploy acceptance
contract. Existing pipeline validators remain authoritative; the helper is a
diagnostic packet with unconditional `qualityAccepted:false`.
