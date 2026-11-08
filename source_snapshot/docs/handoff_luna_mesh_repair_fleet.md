# Luna handoff: fleet mesh identity and animation repair

## Assignment

Work in `V:/Games/Olden Era Playtest Tweak`. Continue the mesh/bind repair pipeline across the
user's intended 261-unit roster, excluding the three recent pilots below. Also correct the mesh
inventory's source-identity errors, especially neutral units whose meshes were never generated
from their appropriate upscaled images.

Implement repairs and produce visible animation results. Do not stop at a plan, inventory,
successful process exit, or a report explaining why a unit was refused. Work in small resumable
batches, carry shared fixes across matching units, and retain responsibility for visual quality.
This assignment is candidate production and review, not game deployment.

Use Luna for the work. Expert review may help with a bounded unresolved geometry problem if the
parent session can provide it; do not silently replace this assignment with a different model or
create a fleet of standalone tasks. Follow repository instructions and preserve unrelated edits.

## Exclusions and current baseline

Exclude these exact unit IDs from new repair/regeneration jobs:

| Unit | Existing manifest under `tools/homm3_meshy_frame_pose/` | Actual state |
| --- | --- | --- |
| `h3_archer` | `archer_rest_fit_pilot.json` | Mesh-fitted body and rigid crossbow attachment; grip polish remains |
| `h3_crossbowman` | `crossbowman_meshy71_tpose_pilot.json` | Improved T-pose body only; weapon extraction remains unfinished |
| `h3_wood_elf` | `wood_elf_rest_fit_pilot.json` | Mesh-fitted body and rigid longbow attachment; string/contact polish remains |

These are excluded because the user requested it, NOT because all three are production-complete.
Use them read-only as examples and regression fixtures. Do not quietly finish the crossbowman
instead of processing the requested remaining set. Older experiments are not additional exclusions.

Recent relevant commits: `6512bea720` (Archer integration), `31f6b5270d` (supervised Luna crossbowman
trial), `9d63dec166` (wood elf, coordinate picker, tightened workflow). Trust current files over
commit-era prose when they differ.

Read first:

- `docs/homm3_mesh_repair_workflow.md`: commands and operator sequence.
- `docs/homm3_mesh_rest_fit_pipeline.md`: rest-pose and skin-transform conventions.
- `docs/homm3_wood_elf_repair.md`: successful separation example and precise remaining defects.
- `docs/homm3_crossbowman_luna_trial.md`: mistakes to avoid, not a template for stopping early.

## Establish the exact queue

Do not treat every mesh file, inventory row, or old scheduler entry as one requested unit.
At handoff preparation on 2026-09-20, these sources disagreed:

| Source | Observed count / role |
| --- | --- |
| User's requested roster | 261; nominally 258 after the three exclusions |
| `tools/homm3_import/homm3_units_manifest.json` | 262 unique unit IDs |
| `artifacts/meshy_downloads/homm3_mesh_coverage.json` | 275 rows; includes additional inventory coverage |
| `artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/scheduler_manifest.json` | Historical 246-unit selection with failures; not current roster authority |

Reconcile exact IDs using the import manifest, `tools/homm3_import/units_inventory.json`, the
neutral catalog, and current game/lab identity mappings. Record the difference sets and their
reasons. Do not remove arbitrary rows to manufacture 261, or silently expand the task to 275.
If the intended membership remains ambiguous, ask one focused roster question and continue
read-only auditing and work on unambiguous in-scope units while awaiting the answer.

Create a durable queue and ledger under a dedicated V:-drive artifact directory, for example
`artifacts/homm3_mesh_repair_fleet_v1/`. These are outputs to create, not files already supplied.
Freeze the reconciled ID list, source-list hashes, and the three exclusions before bulk writes.
Keep neutral inventory-only corrections outside the confirmed animation roster separately listed;
their presence in the neutral catalog does not silently expand the animation queue.

## First priority: correct source identity

The user has identified a real inventory problem: some neutral meshes were generated from the
wrong image or never regenerated after the correct upscale became available. Existing files and
old `meshPresent` statuses therefore do not establish correct identity.

Relevant sources:

- `tools/homm3_import/faction_concepts/homm3_neutral.json`: neutral IDs, display names, and source
  identity context. For example, neutral Halfling and Factory Halfling are distinct identities.
- `tools/homm3_meshy_frame_pose/audit_homm3_mesh_coverage.py`: current inventory producer,
  explicit semantic aliases, and known refused assets. Read before changing its output.
- `artifacts/creature_aaa_3d_upscale/`: upscaled references and available generation records.
- `artifacts/meshy_downloads/`: meshes, source copies, task records, and candidate metadata.
- `tools/homm3_meshy_frame_pose/generate_meshy71_repair_candidates.py`: generation policy and
  source selection. It reads the coverage inventory; a wrong `imageInput` will reproduce the bug.

Audit ALL neutral catalog entries first, then apply the same identity checks to the rest of the
confirmed queue. For each unit:

1. Establish the correct semantic identity from the catalog and original DEF/source artwork.
   Find the appropriate upscaled image and inspect it. An incorrectly named upscale is also
   possible; exact filename matching alone is insufficient.
2. Trace the selected mesh to its actual generation input through task records, input-image
   copies, hashes, download metadata, and explicit aliases. Compare that with the intended
   upscale. Hash equality is strong file-identity evidence, not semantic proof by itself.
3. Render the existing mesh and inspect it beside the correct upscale. Catch donors, placeholders,
   swapped variants, wrong equipment/body plans, and meshes predating the correct source.
4. Classify independently as `verified_correct`, `confirmed_wrong_source`, `missing_mesh`, or
   `unresolved_provenance`. Record concise evidence. Missing metadata is not proof of a wrong
   image; conversely, a correct SID stamped onto an unrelated mesh is not acceptance.
5. For a confirmed mismatch, repair the authoritative source mapping and its producer first.
   Then regenerate that unit from the verified image. Preserve the old asset and its provenance;
   select the replacement explicitly. Do not overwrite the old mesh under a misleading name.
6. Verify the downloaded replacement's actual source-image hash, task/model settings, and rendered
   identity before binding. Update the inventory through its owning tool, not only a generated
   JSON edit that the next audit will undo.

### Neutral upscale gap: explicit first batch

The coverage snapshot present when this handoff was amended reports `17` neutral catalog rows:
`13` currently point at `meshy_remaining_still` inputs and `4` point at `aaa_upscale` inputs.
Treat that as a lead list, not proof of the actual Meshy task input: rebuild coverage with its
producer and verify each row against the task's retained source copy/hash before classifying it.
The 13 still-backed leads are `h3_peasant`, `h3_neutral_halfling`, `h3_boar`, `h3_rogue`,
`h3_nomad`, `h3_mummy`, `h3_troll`, `h3_enchanter`, `h3_sharpshooter`, `h3_azure_dragon`,
`h3_crystal_dragon`, `h3_faerie_dragon`, and `h3_rust_dragon`.

There are plausible but unapproved upscale candidates in the AAA image directory, including
`h3_faerie.png` and `h3_halfling_upg_alt.png`. Do not alias either by filename resemblance alone:
compare each against the neutral catalog's DEF identity and the original artwork, especially the
SoD Halfling versus Factory Halfling distinction. Search all available upscale references for each
neutral, including alternate names, and record `no appropriate upscale found` separately from
`mesh generated from lower-resolution or wrong reference`.

For every confirmed neutral whose correct upscale exists but whose mesh was not generated from it,
repair the centralized inventory image selection, then create a versioned Meshy 7.1 replacement
from that exact image. Keep the prior mesh and task lineage intact, and require the replacement's
source-image hash plus a side-by-side identity review before selecting it. If the appropriate
upscale is absent, put that unit in a separate source-artwork prerequisite list; do not silently
substitute another unit, an upgrade, or a raw sprite. Keep these neutral inventory repairs separate
from the 261-unit animation roster unless the reconciled roster explicitly includes them. The four
rows already marked `aaa_upscale` still require provenance verification; that marker is not itself
acceptance.

If an upscale is genuinely missing or semantically wrong, resolve that source-image prerequisite
first. Do not substitute a raw sprite, another unit's upscale, or a visually similar donor without
an explicit decision. Ask for a missing capability/approval when needed, but continue other units.
Do not clear an identity error merely because a new mesh file exists.

Add focused regression coverage for confirmed identity mistakes and image selection. Reuse
`test_audit_homm3_mesh_coverage.py` and `test_meshy_client_image_to_3d.py` where applicable. Keep
semantic mappings centralized and durable; do not distribute filename exceptions among scripts.

## Credit and compute discipline

Meshy **7.1** is preferred. Do not substitute T2. The user permits selective regeneration and has
credits for quite a few units, but has explicitly ruled out regenerating every unit.

Reuse a correct existing mesh when the applicable fitting/repair route can improve it. Correct
wrong-source neutral meshes before spending credits merely to obtain convenient T-poses for
otherwise correct units. Keep a generation ledger of reason, image hash, model, settings, task ID,
request outcome, and reported credit cost when available. Do not invent a total credit budget.

Submit small reviewed batches, not a bulk 258-unit request. Before a large expansion of paid work,
show the concrete candidate list and expected spend if known, and obtain a budget decision. A
timeout is not permission to submit another task: resume/poll the recorded task ID first.

Use `generate_meshy71_repair_candidates.py` and existing API helpers. Inspect its saved-task reuse
rules: after correcting an image mapping, a task created from the previous image is NOT reusable.
Use an explicit new versioned request/output or a tested extension for source-hash invalidation;
never delete provenance to make the script believe no previous task existed. Do not print keys.

Keep artifacts and temporary work on V:. Check free space before generation batches. Avoid
unnecessary copies of large embedded textures. Do not delete old evidence or unrelated work to
make room. Render serially or with conservatively bounded concurrency; avoid GPU/process pileups.

## Repair each unit using the right body plan

The current `fit_mesh_rest_pipeline.py` supports Y-up T-pose bipeds with the existing 25-joint
topology. It is NOT a universal solver for the whole fleet. Unsupported body plans are an
engineering queue, not a successful no-op or a reason to stop the assignment.

Classify units into reusable groups: applicable bipeds, other biped rest poses, quadrupeds,
mounted units, winged/flying units, and other distinct structures. Locate existing explicit
species/donor motion routes before inventing another implementation. Preserve the correct saved
motion, topology, and body-part ownership; do not force every creature into the biped joints.

For each new group, choose one representative, implement or adapt one shared fitting/attachment
route, visually validate it, then test a second real member before processing the group. Use
small per-unit data recipes when needed, not a separate code fork or full Blender LLM pass for
each of 258 units. Escalate a bounded technical question with images and attempted fixes if stuck.

For an applicable biped:

1. Find the selected textured mesh, saved capture, sequence, and paired registration. Existing
   runs commonly live under `artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/<unit>/`.
   Explicit corrected registrations may live in `linked_master_remaining_scale/`; the wood elf
   is an example. Missing files require actual source discovery, not invented paths.
2. Inspect the actual rest pose. Correct registration provenance does not mean joints are inside
   the mesh. Use front AND side views. Do not repeat Luna's crossbowman mistake of treating an
   accepted registration as a fitted skeleton.
3. Create a per-unit or small-batch manifest with explicit input paths and a new output directory.
   Run `--review` before `--preview`. The existing operator guide contains the exact commands.
4. Verify the skeleton, elbows, knees, wrists, hips, head, and feet against the textured body.
   Fix alignment first. Never compensate for a misplaced rig by arbitrary weight changes.
5. Separate/attach fused props using the process below. Recheck motion after changing geometry.
6. Render the full saved-frame reel, inspect representative clips and suspect intervals, run
   relevant tests/readback checks, and record the remaining visible defects.

Preserve the proven transform conventions: source canonical T-pose to fitted target T-pose for
T-pose meshes; hierarchical retargeting keeps full rotations; `outgoing_skin_transforms` is
applied exactly once before consuming the outgoing-segment skin field. Do not reduce rotations
back to points and reconstruct unrelated shortest-swing transforms. Do not silently switch to
old cascade motion, fabricated smoothing, donor motion, or a vendor armature.

## Author props without coordinate guessing

Use `inspect_prop_recipe.py` from the operator guide. It writes individual 600x700 textured views
and converts `--pick yaw:x:y` pixels to the visible surface point. Pick on the full-resolution
individual image, not a scaled contact sheet. Background pixels do not snap to guessed vertices.

Seed the COMPLETE prop: a bow needs both limbs and grip; a crossbow also needs its stock.
Add body seeds to nearby clothing/quiver surfaces. The recipe is tied to the exact mesh hash.
Inspect isolated prop AND body remainder from multiple angles before moving the prop. Neither a
connected-component count nor a plausible silhouette proves correct extraction. The rejected
crossbowman selection moved a rod while leaving the weapon behind; another included clothing.

Only then set source grip/orientation, target bone, and target REST-frame offset/orientation.
Do not specify target axes from an animated shooting screenshot as though they were rest axes.
Check held orientation in idle and shooting, not just one frame. Render a full reel only after
useful stills. Finger closure, bowstring draw, missing surfaces, and secondary-hand constraints
are separate work; list them rather than claiming rigid attachment solved them.

If repeated cuts select the wrong object, change the evidence: use another view and actual surface
picks, pin the confusing body region, inspect topology, or propose one shared geometry improvement.
Do not spend an hour producing increasingly similar coordinate-probe scripts or repeatedly render
the same bad full reel. Preserve source textures and attributes through any geometry changes.

## Batch execution and resumable evidence

Start with one end-to-end unit, then batches of about 3-5 visually reviewed units. This is a
checkpoint size, not permission to regenerate every member. Prioritize neutral identity fixes,
then ready units and groups with a validated repair route. Work on unsupported-group adapters
in parallel with processing ready groups only when ownership/resources permit.

Maintain one row per roster ID with: scope/exclusion, identity evidence and status, intended image
path/hash, selected mesh path/hash, body plan, saved-motion/registration paths, recipe/manifest,
Meshy task IDs and generation reason, processing state, current output directory, tests/readback,
images/reel paths, visual reviewer notes, unresolved defect, and next concrete action.

Keep identity status separate from repair and animation-review status. Useful processing states
are `queued`, `working`, `needs_source`, `needs_shared_adapter`, `needs_geometry_work`,
`candidate_reviewed`, and `excluded_prior_pilot`. These are a ledger convention, not proof gates
to implement before doing useful work. A missing-adapter row remains unfinished, not completed.

After each batch, save the ledger, show a compact result summary with representative images,
and commit scoped tested changes. Resume from current fingerprints/evidence rather than rerunning
completed units. Preserve failed attempts as comparisons but keep them out of default manifests.
Do not create scheduled tasks or background continuation claims unless separately requested.

For new shared code, run focused tests and regression-check the applicable existing pilots without
altering their selected inputs. Tests must exercise exported geometry/skin and actual motion, not
only prove that a rotation preserves distances. New lasting contracts need lightweight validation
on the relevant production path, not a large unrelated validation framework.

## Handoff and completion

### Latest checkpoint: 2026-09-20

The three confirmed wrong-source animation-roster rows were regenerated as a bounded Meshy 7.1
`source` batch using the current selected AAA inputs. The existing quarantined meshes were not
overwritten, and all three task IDs completed successfully:

| Unit | Meshy task | Candidate | Current review state |
| --- | --- | --- | --- |
| `h3_mechanic_upg_alt` | `01a0c067-7f9b-753b-a256-52cacd12b837` | `artifacts/meshy_downloads/meshy71_repair_candidates/h3_mechanic_upg_alt/source/` | `needs_geometry_work`; registered-reference bind preflight rejected |
| `h3_paokai` | `01a0c067-99d8-74a8-91bf-d2c4f83f8831` | `artifacts/meshy_downloads/meshy71_repair_candidates/h3_paokai/source/` | `needs_geometry_work`; 768 px replay exposes wing/body collapse |
| `h3_pegasus` | `01a0c067-b2fe-715b-b396-bc0e5397f478` | `artifacts/meshy_downloads/meshy71_repair_candidates/h3_pegasus/source/` | `needs_shared_adapter`; mounted-winged route required |

The source copies now hash-match the selected inventory inputs. `h3_paokai` is the horned winged
dragon shown by its selected AAA input, not a mounted horse; an earlier review sentence described
that source incorrectly and has been corrected. Its replacement candidate was reviewed through the
existing eagle-flyer route across the saved nine-clip set. A 4x supersampled 768 px replay with a
stable content crop is now the authoritative visual review: the candidate preserves head-forward
orientation without a sampled global left/right mirror swap, but its wing/body assembly collapses
into coarse plates in high-motion frames and is marked `needs_geometry_work`. The same detail
replay standard was then applied to the existing green-dragon route: idle remains recognizable, but
AttackFront exposes lower-body and wing/body collapse that the old full-canvas reel hid, so that
row is now also `needs_geometry_work` rather than candidate-reviewed. The bilateral audits show
same-side regional ownership on both dragon candidates and do not justify a blanket L/R name swap.
The same readable-detail check on the existing griffin candidate found the same pattern: idle is
recognizable, but AttackFront exposes wing/body and lower-body collapse while bilateral ownership
remains mostly same-side. The eagle-flyer route is therefore not promoted as a clean shared adapter
from these reviews; Paokai, green dragon, griffin, and royal griffin remain geometry/ownership work.
Geometry preflight remains negative
for all three because Meshy output has genuine welded boundary/non-manifold edges; the mechanic
also places 45.3% of vertices outside the current registered bind plate and is not an accepted
animation candidate. A separate Meshy 7.1 `t-pose` task for the mechanic completed as
`01a0c079-941e-74ed-b029-dd7ce6fd9fb8`; its fitted rest overlay, keyframes, and full 80-frame
candidate reel are now reviewed as `candidate_reviewed`. That candidate has no catastrophic
global twist in the sampled motion, but firearm/hose ownership and topology remain unresolved.
The firearm was then cut with a mesh-hash-bound `prop_attachment.v1` recipe, reviewed from both
front and rear prop/body views, and re-rendered through the full reel; the gun follows `LeftHand`
without introducing a sampled global twist. The hose remains fused to the body and a small
residual fragment still needs an explicit ownership decision.
No candidate `animation_reel.gif` was treated as final quality, and no Unity, deployment, or
runtime validation was performed. Review sidecars are under each unit's `zz*`/`zzz*` directories.
The biped preview path now also emits a stable content-cropped `detail_reel.gif` and
`detail_keyframes.png`; the sidechain-fix swordsman replay was regenerated at 4x (`1440x2080`
per uncropped frame) and reviewed through that detail path. It confirms that the corrected arm
branch selector does not cause a blanket left/right swap, while the death interval still has
real lower-body deformation and equipment ownership defects. The detail replay is diagnostic
evidence only, not delivery proof. The same 4x detail pass on the verified-correct Pikeman
keeps the body recognizable through idle, move, attack, and death; it likewise does not show a
blanket laterality swap, but the long pike's two-hand contact and death-pose quality remain
unresolved.
The same review now covers the verified-correct Halberdier. Its 4x detail replay remains
recognizable through idle, move, attack, and death, with no blanket laterality swap visible;
the halberd's two-hand contact and death-pose quality remain unresolved, so it stays a reviewed
candidate rather than delivery proof.
The shared biped adapter also now handles the verified-correct `h3_marksman` export. Its arm
roots sit above the neck, so the former height-only trunk selector consumed an arm branch and
failed closed. Complete trunk-path shape scoring selects the registered body path, and the
missing `HeadTop_End` is synthesized explicitly when the export has only six trunk nodes. The
4x replay is recognizable across idle, move, attack, shoot, and death; it remains a reviewed
candidate with unresolved bow/clothing ownership and high local cross-side weight mixing.
The same shared route was then piloted on the armored humanoid `h3_steel_golem`. Its front and
side rest overlays are plausibly fitted, and the 4x content-cropped replay remains recognizable
through idle, move, attack, and death. It is retained as a `candidate_reviewed` adapter
candidate, not a finished repair: armor/hand ownership and the compressed death pose remain
visible defects, while the bilateral audit reports 1484 of 7974 mixed vertices with maximum
opposite-side masses of 0.353 and 0.362. This is another case where the readable detail replay
does not support a blanket left/right name swap.
The same pilot on `hota_cove_corsair` failed closed before fitting because its registered toes
point along the hip-to-hip axis rather than the perpendicular forward axis required by this
adapter. That row remains unfinished and needs a body-plan/registration correction, not a forced
biped output.
The same route was then exercised on `h3_rot_zombie` as a second ordinary humanoid. Its front and
side rest overlays are plausible and the 4x replay remains recognizable through idle, move,
attack, and death, so it is retained as another `candidate_reviewed` adapter candidate. The axe,
cloth, and compressed attack/death deformation remain unresolved; its bilateral audit reports
641 of 4387 mixed vertices and maximum opposite-side mass of 0.500 in both directions. Again,
that is local ownership evidence, not proof of a blanket left/right swap.
The same route also fits the armored `h3_magnetic_golem`. Its 4x detail replay is recognizable
through idle, move, attack, and death, and its bilateral audit is cleaner than the other recent
pilots at 674 of 6816 mixed vertices with maximum opposite-side masses of 0.210 and 0.222. It is
still not delivery-ready: the large torso/arm plates compress in attack and death, and armor
ownership has not received a region-level review.
The same generic route was deliberately tested against the distinct `h3_minotaur_taskmaster`
body plan and failed the visual gate. Although the rest overlay is plausible enough to fit, the
4x replay collapses every sampled clip into a low, nearly horizontal pose. The row is therefore
`needs_geometry_work`, not a reviewed candidate: a minotaur-specific body/prop adapter or a
corrected registration is required. Its bilateral audit reports 908 of 6316 mixed vertices, but
that does not support blaming a global left/right name swap; the body-plan/motion mismatch is the
dominant visible failure.
The generic route also refused `h3_horned_demon` before producing a candidate: its tail/fur/arm
topology does not expose the expected left UniRig arm chain. That row remains
`needs_shared_adapter`; no low-quality reel was manufactured to make the route appear complete.
The existing zoo-quadruped route was then upgraded rather than regenerated for `h3_hell_hound`.
Its old comparison reel was too small for a trustworthy judgment, so the saved 62-frame candidate
was rerendered at 768 px with the same content-cropped detail policy. Idle, move, defence, attack,
and death samples remain recognizable without a consistent whole-asset left/right twist. The
bilateral audit reports 819 of 8080 mixed vertices and maximum opposite-side masses of 0.453 and
0.496; tail/leg ownership remains unresolved, so this is reviewed adapter evidence, not delivery
proof.
The same 4x upgrade was applied to the existing horse/quadruped candidate for `h3_unicorn`.
Its 64-frame replay remains recognizable through idle, move, defence, attack, and death, again
without a consistent whole-asset left/right twist. The bilateral audit reports 1194 of 8226 mixed
vertices with maximum opposite-side masses of 0.496 and 0.493. Horn, tail, rein, and leg
ownership remain open, so the candidate is reviewed evidence rather than delivery proof.
The same high-resolution replay was also checked on the two-headed `h3_cerberus` member of the
hound route. Its 62-frame detail replay remains recognizable across the saved clips without a
consistent whole-asset left/right twist; the bilateral audit reports 724 of 10249 mixed vertices
with maximum opposite-side masses of 0.498 in both directions. Two-head, tail, and leg ownership
remain open, so this is reviewed adapter evidence rather than delivery proof.
The same 4x replay standard was applied to the existing eagle-flyer candidate for
`hota_cove_ayssid`. Its 72-frame dragon replay remains recognizable through idle, move, defence,
attack, and death, with coherent wing/tail silhouettes and no consistent whole-asset left/right
twist. The bilateral audit reports 3321 of 8847 mixed vertices with maximum opposite-side mass
of 0.500 in both directions; wing, tail, and foot ownership remain unresolved, so the route is
reviewed evidence rather than delivery proof.
The quadruped replay batch also covered a mammoth and a goat/ram subtype. `h3_mammoth_upg_alt`
remains recognizable across its 77 saved frames with no catastrophic collapse; its audit reports
973 of 14541 mixed vertices and maximum opposite-side masses of 0.288 and 0.457. The
`h3_mountain_ram_upg_alt` replay is likewise recognizable across 66 frames without a global side
inversion; its audit reports 560 of 10247 mixed vertices and maximum opposite-side masses of
0.499 in both directions. Trunk/tusk, horn/tail, armor, and leg ownership remain open on these
subtypes, so both are reviewed candidates rather than delivery assets.
The same high-resolution check rejected the generic anaconda route for `h3_sandworm_upg_alt`.
The source sandworm remains identifiable, but the saved candidate repeatedly reads as a dark,
collapsed or unrelated articulated mass, especially in attack and death. Its skeleton has no
left/right-named joints, so the bilateral audit is not applicable; this is a segment-chain/body
plan failure, not evidence of a global side swap. The row is `needs_geometry_work` and requires a
sandworm-specific adapter plus source-identity recheck.
Because the earlier 4x contact sheets still left small creatures difficult to inspect, the Hell
Hound replay was independently rerendered at true 8x source resolution (1536 px before the
detail crop), not enlarged from the old pixels. That readable check confirms the head/torso
orientation is retained while the attack limbs fold into incorrect plates; it does not show a
global side inversion. The 8x replay is retained as diagnostic evidence under
`artifacts/homm3_mesh_repair_fleet_v1/adapter-replays/h3_hell_hound/zoo-quadruped-v1-8x/`.
As a controlled follow-up, the Minotaur was rerun against its retained `remaining_yawfix`
registration in a separate `smartrig-standard-yawfix-v1` output. The 4x replay collapses in the
same way as the `remaining_scale` output, with the same 908 of 6316 mixed vertices and nearly
identical opposite-side masses. Registration yaw is therefore not the primary cause; both
versioned outputs remain preserved. A readable 4x rerun then exposed the actual shared-adapter
bug: the generic leg selector chose the deep upward torso branch (`Bone_005..Bone_023`) as one
Minotaur leg. The selector now requires a branch to reach the lower body and prefers the two
lowest descendant branches; a regression test pins `Bone_010..Bone_006` and
`Bone_015..Bone_011`. The versioned `smartrig-standard-legfix-v1` candidate remains upright and
recognizable instead of collapsing, with no blanket left/right inversion visible, but weapon,
fur/cloth, contact, and death-pose defects remain. It is therefore a reviewed candidate, not
final-quality delivery. The old yawfix and generic outputs remain preserved as negative
comparisons.
The next horse/dragon quadruped review batch used the same content-cropped replay policy on
`h3_pristine_unicorn`, `h3_war_unicorn`, and `h3_ruinous_hydra`. Both unicorn candidates remain
recognizable through the sampled clips without a consistent whole-asset side inversion; the horse
extremities, reins/halter, mane/tail, and armor still need ownership review. The hydra candidate
is rejected as `needs_geometry_work`: its multi-neck body and dorsal plates repeatedly collapse
under the generic dragon route, so this is a body-plan mismatch rather than evidence for an L/R
swap. Their review sidecars and 4x replays are retained under the per-unit candidate and
`adapter-replays` directories.
The following flyer batch then covered `h3_damsel_fly`, `h3_phoenix`, and `h3_serpent_fly`.
Their readable replays remain recognizable through the sampled clips without a consistent
whole-asset side inversion. Damsel Fly has high bilateral mixing because its broad wings and
tail cross the centerline; Phoenix has the same issue across feather and flame regions; neither
supports a blanket L/R name swap. All three remain reviewed candidates with wing, tail, claw,
ornament, plume, and death/contact ownership unresolved.
The following anaconda-route batch covered `hota_cove_haspid`, `hota_cove_sea_serpent`, and
`hota_factory_olgoi_khorkhoi`. All three are `needs_geometry_work`: the candidate folds into a
compact upright or appendage-heavy mass instead of preserving the source's long segment chain.
Their skeletons do not contain both left and right joint families, so the bilateral audit refused
closed; this is a body-plan failure, not proof of a side-name swap. The generic anaconda outputs
are retained as negative evidence pending dedicated segment-chain adapters.
The next mixed quadruped batch covered `hota_bulwark_argali`, `hota_bulwark_mammoth`, and
`toa_ghost_behemoth`. All three remain recognizable in the readable replays without a
consistent whole-asset side inversion. They are retained as reviewed candidates with local
horn/beard/tail, trunk/tusk/armor, claw/tusk/armor, and death/contact ownership still open.
The next flyer batch covered `h3_red_dragon`, `h3_sacred_phoenix`, and `h3_manticore`. Red
Dragon and Sacred Phoenix remain recognizable reviewed candidates without a consistent whole-asset
side inversion; their wing, tail, feather, claw, plume, and contact ownership remain open. The
Manticore is `needs_geometry_work` because its lion/scorpion/wing assembly collapses into a low
plate-like mass in high-motion frames. Its bilateral statistics do not support a blanket L/R swap.
The next high-resolution flyer batch covered `h3_dragon_fly`, `h3_scorpicore`, and
`h3_silver_pegasus`. At 4x content-cropped replay resolution, Dragon Fly and Scorpicore fold
their long body/wing/tail assemblies into compact masses, while Silver Pegasus separates its rider,
horse, wings, and rear geometry into disconnected plate-like pieces. All three are
`needs_geometry_work`; their bilateral audits show no basis for a blanket L/R name swap. Silver
Pegasus additionally needs a mounted-flyer route rather than the generic eagle-flyer selector.
The next eagle-flyer batch covered `hota_cove_halcyon`, `hota_cove_stormbird`, `hota_factory_couatl`,
and `hota_factory_crimson_couatl`. Halcyon and Stormbird remain recognizable but shed rear-wing
and lower-body plates in high-motion frames, so they are reviewed candidates with ownership work
open. Both Couatl variants collapse their long serpentine body and wing assemblies into compact
folded masses and are `needs_geometry_work`; neither result supports a blanket L/R swap. The
queue/ledger was rebuilt and the focused queue test passes; counts are now 65 identity-verified,
3 identity-confirmed-wrong-source, 128 reviewed animation candidates, 28 reviewed adapter-evidence
rows, 259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262 roster membership
ambiguity remains open.
The next replay-compatible humanoid batch covered `h3_fargazer`, `h3_infernal_troglodyte`, and
`hota_bulwark_kobold`. Fargazer is `needs_geometry_work`: its tentacles and torso repeatedly fold
into a rotated compact mass under the generic Mixamo-person route. Infernal Troglodyte and Kobold
remain recognizable reviewed candidates without a consistent whole-asset side inversion, but their
weapon, armor, extremity, and contact ownership are not final-quality proof. The older mounted
candidate outputs were not promoted because their linked-master directories lack the saved
`master_sequence` contract required for a trustworthy 4x replay; their old reels remain
unreviewed rather than being treated as evidence. Counts are now 65 identity-verified,
3 identity-confirmed-wrong-source, 130 reviewed animation candidates, 29 reviewed adapter-evidence
rows, 259 unresolved repair rows, and 3 excluded pilots.
The next elemental batch covered `h3_frost_elemental`, `h3_ice_elemental`, `h3_magic_elemental`,
and `h3_water_elemental`. Frost, Ice, and Water Elemental are `needs_geometry_work`: the generic
Mixamo-person route folds or separates their serpentine bodies and tails. Magic Elemental remains
recognizable as a reviewed candidate, but cloak, spell-prop, extremity, and contact ownership are
still open. None of the four high-resolution audits supports a blanket L/R swap. Counts are now
65 identity-verified, 3 identity-confirmed-wrong-source, 131 reviewed animation candidates, 32
reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots.

The constructive mounted-registration check also fails closed before writing a candidate: the
stitched horse capture has no Mixamo/Eagle left-right pair from which the generic yaw reader can
derive a source orientation. That is a real route contract gap, not evidence that the rider is
backwards or that its sides should be renamed. A mounted registration must therefore carry an
explicit authored orientation and use the mounted capture's own provenance; the generic biped
registration helper was not widened with a guessed default.
The following aquatic humanoid batch covered `hota_cove_nereid`, `hota_cove_nix_praetorian`,
`hota_cove_nix_warrior`, `hota_cove_nymph`, and `hota_cove_oceanid`. Nereid is
`needs_geometry_work` because the generic person route flattens and detaches its water/serpentine
lower body. Nix Praetorian, Nix Warrior, Nymph, and Oceanid remain recognizable reviewed candidates
without a consistent whole-asset side inversion, but armor, fluid lower-body, weapon, extremity,
and contact ownership remain open. Counts are now 65 identity-verified, 3
identity-confirmed-wrong-source, 135 reviewed animation candidates, 33 reviewed adapter-evidence
rows, 259 unresolved repair rows, and 3 excluded pilots.
The replay tool now also supports an explicit candidate-only yaw diagnostic. This is necessary
because the saved static registration records silhouette coverage and a nominal zero mesh-to-source
yaw, but does not prove semantic front-versus-back orientation. A 0-vs-180 4x comparison was run
for the aquatic batch; the selected yaw remains 0 for all five rows, while the 180 variants expose
the Nix, Nymph, and Oceanid candidates from the rear. Future reviews must record this orientation
check separately from bilateral L/R weights, and no old reel is retroactively promoted to final
quality merely because its facing happens to look plausible.
The same diagnostic was then applied to `hota_factory_juggernaut`: zero yaw retains the source
front plate and dark face/grille details, while 180 degrees exposes the rear housing, so zero was
selected for this unit only. Its 4x replay remains a reviewed candidate, not final quality: armor,
limb/contact, and attack articulation remain unresolved. Its bilateral audit found 583 of 8472
mixed vertices, with maximum opposite-side masses of 0.396 and 0.292; that is a bounded weighting
defect signal, not proof of a global left/right inversion. `hota_factory_sandworm_larva` was
reviewed separately and rejected as `needs_geometry_work`: the generic anaconda route collapses
the segmented larva into a compact faceted mass. It has no bilateral joint families, so the L/R
audit is inapplicable; this is a body-plan/segment-chain failure. Counts are now 65
identity-verified, 3 identity-confirmed-wrong-source, 136 reviewed animation candidates, 34
reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots.
The next orientation-sensitive checks covered `h3_beholder` and `h3_cannon`. Beholder is
backwards at zero yaw and source-facing at 180 degrees, but its tentacles still collapse under
attack and require a dedicated adapter. Cannon is source-facing at zero yaw; 180 degrees exposes
its rear, while ShootFront folds the carriage and barrel into an incorrect plate assembly. Both
are therefore `needs_geometry_work`, and their L/R audits are recorded as weighting diagnostics,
not as proof of a global side swap. Counts are now 65 identity-verified, 3
identity-confirmed-wrong-source, 136 reviewed animation candidates, 36 reviewed adapter-evidence
rows, 259 unresolved repair rows, and 3 excluded pilots.
The next selective Meshy 7.1 generation targeted the queued biped `toa_ogre_brute` using its
selected AAA input and an explicit `t-pose` variant (task
`01a0c1dc-accb-7689-9ade-26b4cbdea0a5`). The task completed and the owned biped fit was reviewed
through a true 4x replay. The body remains recognizable through idle, move, attack, and death,
but the generated t-pose mesh dropped the source club, so the result is a `candidate_reviewed`
body candidate with prop work still required. Counts are now 65 identity-verified, 3
identity-confirmed-wrong-source, 137 reviewed animation candidates, 37 reviewed adapter-evidence
rows, 259 unresolved repair rows, and 3 excluded pilots.
The first Ogre source-vs-candidate orientation control reels were invalidated: they reconstructed
canonical-T-pose motion rather than consuming the fitted `retargeted_motion.npz`, and their source
panel was visibly collapsed. A corrected saved-fit replay now consumes the actual fitted motion at
camera yaw 0, 25, and 180. The candidate preserves its front/back presentation without a global
pose inversion, while the existing source bind presents a different rear/side arrangement and is
not a reliable sprite-facing authority for this unit. This remains a candidate-facing observation,
not a delivery-world orientation or anatomical L/R decision.
The source-only prop audit then confirmed that the old Ogre mesh does contain the club, but the
first mesh-hash-bound cut also captured hand/shoulder/cloth residue and left a club-shaped fragment
in the body remainder. Because the 600x700 view was too small to judge the bridge, the audit was
rerun at 4x (2400x2800 per view); the larger images show the selected region retaining the hand,
shoulder, and cloth while the body remainder still contains both the shaft fragment and upper club
head. That recipe is tied to the old source hash and was not applied to the new candidate hash.
Club transfer therefore remains unresolved rather than being represented by a contaminated prop
extraction. `inspect_prop_recipe.py --panel-scale 4` is now the resumable high-resolution path for
thin props and ambiguous fused regions.
A single controlled Meshy 7.1 prop-only follow-up was then submitted from the isolated audit crop
(task `01a0c221-eb25-76fa-b10d-b9bfee0c4ab1`, 30 reported credits). Its 1200x1400 turntable still
reconstructed a large arm/hand/cloth/armor mass around the club-like shaft and head, so it is
recorded as `rejected_needs_geometry_work`; no attachment or body mutation was performed. The
launcher now creates its task directory before submission and prints the task ID before writing
the record, while the lost-record case was recovered from the task listing without submitting a
duplicate request.
The next selective Meshy 7.1 control case targeted `h3_wraith`. Its source-conditioned task
(`01a0c1ef-e8ba-7770-bf4a-f1cb6959ccfd`) produced a mesh that failed both the separated-arm T-pose
preflight and the single-skeleton SmartRig extraction route. A second explicit T-pose task
(`01a0c1f3-4b19-727a-9a75-21b9433b01d0`) also failed the separated-arm preflight before a fitted
bind or replay existed. Wraith is therefore recorded as `needs_shared_adapter`: the current
unsupported rest-pose/body-plan route does not yet establish a geometry defect. No fabricated reel
or facing decision was recorded. Counts remain 65 identity-verified, 3 identity-confirmed-wrong-source,
137 reviewed animation candidates, 37 reviewed adapter-evidence rows, 259 unresolved repair rows,
and 3 excluded pilots.
The next queued winged row, `h3_air_elemental`, had a real capture-skeleton bind and saved 58-frame
master sequence but no fitted-candidate `report.json` contract for the newer replay tool. A new
`render_existing_bind_replay.py` path now consumes that exact bind/capture/master/registration
contract without fabricating a report or changing the bind. Its fixed-camera 900 px replay is
readable in both the full and detail reels, and the bind frame is rest-exact at 3.17e-15 maximum
vertex error. The authored attack/death plates still diverge materially from the coarse filled
body, so the row is `needs_geometry_work`, not a promoted repair. The bilateral audit reports
5743/16064 mixed vertices with opposite-side mass near 0.5 in both directions; the capture-side
X audit is not a clean mirror oracle either, so this does not justify a blanket left/right name
swap. The replay tool test passes, and the high-resolution evidence is retained under the unit
candidate review sidecar. Counts are now 65 identity-verified, 3 identity-confirmed-wrong-source,
137 reviewed animation candidates, 38 reviewed adapter-evidence rows, 259 unresolved repair rows,
and 3 excluded pilots.
The second winged-elemental control, `h3_hurricane_elemental`, was then run through the same
900 px fixed-camera bind replay. Its saved bind is also rest-exact at 1.01e-15, but the authored
attack and shoot plates lose the elemental silhouette and effect-adjacent limb structure. Its
bilateral audit reports 3443/8097 mixed vertices with opposite-side mass near 0.5 in both
directions. This reproduces the air-elemental weighting/body-plan warning without proving a global
side-name swap, so the existing capture-bind route is not promoted as a shared elemental adapter;
the remaining elemental rows stay queued pending a dedicated flexible-body ownership route or
source-conditioned geometry. Counts are now 65 identity-verified, 3
identity-confirmed-wrong-source, 137 reviewed animation candidates, 39 reviewed adapter-evidence
rows, 259 unresolved repair rows, and 3 excluded pilots.

The next queued biped control, `h3_shaman_upg_alt`, used the same existing-bind replay at 900 px.
Its bind is rest-exact at 1.17e-15 and its bilateral audit is materially cleaner than the
elemental controls: 645/8300 mixed vertices, with maximum opposite-side masses 0.243 and 0.275.
The staff-bearing body remains recognizable, but the source antlered head is not preserved and
the head/body proportions are visibly wrong. The separated capture-side X audit provides no reason
to rename the side families. This row is therefore `needs_geometry_work`, not a side-swap repair;
the review sidecar retains the full/detail reels and bilateral audit. Counts are now 65
identity-verified, 3 identity-confirmed-wrong-source, 137 reviewed animation candidates, 40
reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots.

The existing-bind replay renderer was then corrected before further visual decisions. The bind GLB
stores vertices after the accepted mesh-to-capture surface alignment, while the registration camera
is fitted in source-mesh view space; the renderer had been projecting the former with the latter.
It now applies the inverse accepted alignment, selects the registration's accepted camera candidate,
and records `meshRenderSpace` in the replay report. The earlier 900px Air Elemental, Hurricane
Elemental, and Shaman reels, and the first Roc 3x reel, are superseded by true 1350px source-space
replays under `*-3x-source-space-v2`; the sidecars and queue now point to those corrected outputs.

The next high-resolution control, `h3_roc`, was rendered at a true 1350px fixed-camera replay
resolution (`preview-scale 3`) rather than enlarging the old reel. The saved bind is rest-exact at
2.09e-15. In corrected source-space detail, the source Roc is a right-facing profile while the
replay presents a frontal bird, so the accepted registration does not preserve the source-facing
view. The replay is now correctly scaled, but it still loses the source wing/feather silhouette;
this does not support a blanket left/right name swap. Its bilateral audit reports 805/10079 mixed
vertices, with maximum
opposite-side mass 0.410 on left-dominant vertices and 0.413 on right-dominant vertices. The
capture-side X means are 0.113 for the named left family and -0.060 for the named right family,
but both families include centerline joints, so this is not a clean mirror oracle. Because the
ledger still reports unresolved source provenance for the Roc mesh, the row is retained as
`needs_geometry_work` pending source-conditioned avian geometry or a candidate-hash-bound
scale/silhouette and view-registration repair. Counts are now 65 identity-verified, 3
identity-confirmed-wrong-source, 137 reviewed animation candidates, 41 reviewed adapter-evidence rows,
and 3 excluded pilots.

The corrected source-space replay then covered `h3_thunderbird` at 1350px. Its saved bind is
rest-exact at 9.37e-16, but the source is a right-facing profile while the replay presents a
frontal bird, so this is another per-unit view/registration failure rather than a fleet-wide side
rename. The bilateral audit reports 865/10015 mixed vertices, with maximum opposite-side masses
0.500 in both directions; capture-side means are 0.086 for the named left family and -0.097 for
the named right family, with centerline overlap. The row remains `needs_geometry_work` and its
source-conditioned provenance is unresolved. Counts are now 65 identity-verified,
3 identity-confirmed-wrong-source, 137 reviewed animation candidates, 42 reviewed adapter-evidence
rows, 259 unresolved repair rows, and 3 excluded pilots.

The corrected source-space replay then covered `hota_factory_engineer` at 1350px. Its bind is
rest-exact at 3.78e-15, and the source and replay preserve the same right-facing engineer profile
through the sampled idle, move, attack, and death keyframes. It is retained as
`candidate_reviewed`, not final-quality acceptance: rifle/strap/coat and contact ownership remain
open. The bilateral audit reports 2692/8142 mixed vertices, with maximum opposite-side masses
0.500 and 0.499; unlike the avian controls, the capture-side families are cleanly separated
(left mean X 0.207, minimum 0.076; right mean X -0.123, maximum -0.049). This does not justify a
global Left/Right rename. Counts are now 65 identity-verified, 3 identity-confirmed-wrong-source,
138 reviewed animation candidates, 42 reviewed adapter-evidence rows, 259 unresolved repair rows,
and 3 excluded pilots.

The next distinct queued body plan, `h3_evil_eye`, was rendered at the same corrected 1350px
source-space resolution. Its bind is rest-exact at 4.31e-16, but the replay's eye-stalk/head
arrangement and tentacle silhouette do not preserve the source closely enough for promotion. The
bilateral audit reports 3046/7380 mixed vertices, with maximum opposite-side masses 0.497 and
0.486; capture-side placement is not a clean mirror oracle because the named left family crosses
the centerline. This remains `needs_geometry_work` for source-conditioned eye/tentacle geometry
and ownership, not a global Left/Right rename. Counts are now 65 identity-verified,
3 identity-confirmed-wrong-source, 138 reviewed animation candidates, 44 reviewed adapter-evidence
rows, 259 unresolved repair rows, and 3 excluded pilots.

The next flyer control, `temple_griffon`, was rendered at 1350px source-space resolution. Its bind
is rest-exact at 2.22e-16, but the source Griffon is three-quarter/right-facing while the replay
presents a frontal bird-beast; wing, head, and forelimb silhouette are not source-faithful. The
bilateral audit reports 3011/11538 mixed vertices with maximum opposite-side masses 0.320 and
0.291, while most vertices are not side-dominant and the capture-side families cross the centerline.
This is `needs_geometry_work` for per-unit flyer view/registration and source-conditioned geometry,
not a global side-name swap. Counts remain 65 identity-verified, 3 identity-confirmed-wrong-source,
138 reviewed animation candidates, 44 reviewed adapter-evidence rows, 259 unresolved repair rows,
and 3 excluded pilots.

A bounded orientation diagnostic then tested the suspected view mismatch without changing either
bind. For both `h3_roc` and `h3_thunderbird`, the accepted zero-offset replay was frontal while
the source sprite was a right-facing profile; a `+90` degree camera-yaw diagnostic recovered a
close right-facing profile at true 1350px. The reusable renderer now accepts
`--camera-yaw-offset-deg` and records the offset in the report. These yaw-90 outputs are still
diagnostic only: they establish a per-unit orientation correction candidate, not a global camera
policy, left/right rename, or runtime delivery decision.

The same `+90` diagnostic on `h3_shaman_upg_alt` also recovers the source's right-facing profile,
but the antlered head remains absent and the proportions remain wrong. This separates the view
correction from the actual source-geometry defect: yaw can fix the presentation for this unit, but
it cannot manufacture missing anatomy and does not justify a side-family rename.

The controlled Ogre validation then covered `h3_ogre_mage` at the same 1350px source-space
resolution. Its bind is rest-exact at 5.69e-16. The accepted zero-offset replay is frontal while
the source is side/three-quarter; a separate `+90` camera-yaw diagnostic recovers the expected
side presentation, but staff, body, and contact geometry still require source-conditioned review.
The bilateral audit reports 1362/7332 mixed vertices with maximum opposite-side masses 0.496 and
0.498, while the capture-side families are cleanly separated (left mean X 0.230, right -0.142).
This is a per-unit view-registration and geometry issue, not a global left/right binding defect.
The row is recorded as `needs_geometry_work` with the yaw diagnostic retained separately. Counts
are now 65 identity-verified, 3 identity-confirmed-wrong-source, 138 reviewed animation
candidates, 49 reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots.

The next biped control batch covered `h3_efreet_sultan`, `h3_efreeti`, and `h3_genie_vizier` at
1350px. Efreet Sultan and Efreeti reproduce the per-unit orientation pattern: zero-offset is
frontal against a narrow source profile, while +90 recovers the profile presentation but leaves
body/effect deformation and ownership unresolved. Their audits report 1839/8507 and 5260/11586
mixed vertices, with opposite-side masses near 0.5; their capture-side families are mostly
separated and do not support a global side rename. Genie Vizier is a separate negative: neither
the accepted view nor +/-90-degree diagnostics recover the broad source silhouette, so no single
yaw correction is promoted. All three are recorded as `needs_geometry_work` with orientation
diagnostics retained where informative. Counts are now 65 identity-verified,
3 identity-confirmed-wrong-source, 138 reviewed animation candidates, 52 reviewed
adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots.

The next ordinary-biped controls covered `h3_grand_elf`, `h3_monk`, and `h3_lich`. Grand Elf is
readable and source-aligned through the sampled poses, so it is retained as `candidate_reviewed`,
not final: bow, strap, hand, and contact ownership remain open. Monk repeats the per-unit view
issue at 2940px: zero-offset is frontal against a narrow source profile, while +90 recovers the
side presentation but not the hood/body silhouette. Lich is orientation-consistent, but staff,
hand/contact, and side ownership remain unresolved. The audits report 1638/7788, 3026/6862, and
1853/7585 mixed vertices respectively; none supports a global left/right rename. Counts are now
65 identity-verified, 3 identity-confirmed-wrong-source, 139 reviewed animation candidates, 54
reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots.

The next queued controls covered `h3_pit_spawn` and `h3_vermin`. Pit Spawn is retained as
`candidate_reviewed`: its +90-degree diagnostic recovers the source profile, its body/tail read
survives the sampled poses, and its audit is materially cleaner at 1434/7082 mixed vertices with
opposite-side masses 0.188 and 0.251; tail/contact ownership and the candidate-hash-bound
orientation contract remain open. Vermin has the same view recovery but its extra appendages and
tail do not survive the generic bind closely enough, so it remains `needs_geometry_work` at
1384/7549 mixed vertices with opposite-side masses near 0.5. Neither supports a global left/right
rename. Counts are now 65 identity-verified, 3 identity-confirmed-wrong-source, 140 reviewed
animation candidates, 55 reviewed adapter-evidence rows, 259 unresolved repair rows, and 3
excluded pilots.

The following saved-bind control, `h3_yeti_upg_alt`, is the cleanest recent biped control. Its
1350px replay is rest-exact at 4.04e-16, preserves the broad frontal armored-yeti presentation,
and reports only 459/9571 mixed vertices, with maximum opposite-side masses 0.499 and 0.232.
Weapon, hand, and contact plates still prevent final-quality promotion, so it is recorded as
`candidate_reviewed`, not delivered. The capture-side families are mostly separated and do not
support a global left/right rename. Counts are now 65 identity-verified,
3 identity-confirmed-wrong-source, 141 reviewed animation candidates, 55 reviewed
adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots.

The following control pair covered `h3_pit_fiend` and `h3_power_lich`. Pit Fiend is retained as
`candidate_reviewed`: its +90-degree diagnostic recovers the source profile, its body/tail read
survives the sampled poses, and its audit reports 573/7478 mixed vertices with opposite-side
masses 0.294 and 0.296; tail/contact ownership and the orientation contract remain open. Power
Lich is orientation-consistent but staff, cloak/body deformation, and hand/contact motion remain
unresolved, with 1221/6207 mixed vertices and opposite-side masses near 0.5. Neither supports a
global left/right rename. Counts are now 65 identity-verified, 3 identity-confirmed-wrong-source,
142 reviewed animation candidates, 56 reviewed adapter-evidence rows, 259 unresolved repair rows,
and 3 excluded pilots.

The next saved control, `h3_priest`, repeats the view-registration pattern: zero-offset is frontal
against a narrow source profile and +90 recovers the side presentation. The bind is rest-exact at
7.62e-16, but robe/body deformation and hand/contact motion remain unresolved; its bilateral audit
reports 2214/6862 mixed vertices with opposite-side masses 0.499 and 0.500, and the capture-side
families overlap the centerline. It is recorded as `needs_geometry_work`, not a global side-name
repair. Counts are now 65 identity-verified, 3 identity-confirmed-wrong-source, 142 reviewed
animation candidates, 57 reviewed adapter-evidence rows, 259 unresolved repair rows, and 3
excluded pilots.

The remaining elemental controls were then closed at the corrected 1350px source-space replay
resolution: `h3_magma_elemental`, `h3_plasma_elemental`, `h3_psychic_elemental`, and
`h3_storm_elemental`. All four saved binds are rest-exact, but none preserves its authored
elemental body/effect silhouette closely enough for final-quality acceptance under the generic
existing capture-bind route. Their bilateral audits report 326/4269, 542/3653, 2523/5690, and
4751/9897 mixed vertices respectively, with opposite-side masses near 0.5; this is repeated local
ownership/body-plan evidence, not proof of a fleet-wide left/right inversion. The capture-side
families are separated for Magma and Plasma, while Psychic and Storm cross or overlap the
centerline; this variation is itself evidence against a global side rename. All four are recorded
as `needs_geometry_work` with retained high-resolution reels and audits. Counts are now 65
identity-verified, 3 identity-confirmed-wrong-source, 138 reviewed animation candidates, 48
reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots.

At each checkpoint report four counts separately: identity verified/corrected, reviewed animation
candidates, unresolved repair work, and excluded pilots. Include generation spend/task counts and
remaining scope ambiguity. Never present a green scheduler exit or 258 enumerated rows as 258
repaired units. Crossbowman and wood elf demonstrate why body, prop, and contact quality differ.

The assignment is complete only when the reconciled roster is accounted for, requested in-scope
source errors are corrected, and remaining in-scope units have reviewed outputs rather than
silently skipped jobs. Unresolved source or repair work means a checkpoint, not fleet completion.
The queue now records the roster difference as an unavailable ID set rather than an empty set:
the handoff provides only the requested count of 261, while the import manifest provides 262 IDs.
No import-only unit is dropped until an authoritative 261-ID membership list is supplied.
If work remains, give a truthful resumable checkpoint and continue when the session allows; do not
rename a partial batch as fleet completion. Report catalog-only findings outside the animation
roster separately, with an explicit correction or unresolved disposition for each.

Deliver the queue/ledger, corrected inventory mappings and audit, per-unit selected manifests,
reels/contact sheets, reusable adapters/tools, test results, commits, and exact resume command.
`fitted_bind.glb` is a static mesh/skin and `retargeted_motion.npz` contains transforms. Candidate
generation, animated interchange export, Unity build, deployment, and in-game proof remain distinct.
Do not deploy, overwrite installed bundles, or claim game-visible success under this handoff.

The reproducible resume sequence is:

```powershell
Set-Location 'V:\Games\Olden Era Playtest Tweak'
py -3 tools/homm3_meshy_frame_pose/build_mesh_repair_fleet_queue.py --out artifacts/homm3_mesh_repair_fleet_v1
py -3 -m unittest tools.homm3_meshy_frame_pose.test_build_mesh_repair_fleet_queue experiments.homm3_mocap_v2.test_preview_saved_linked_master
```

For a row that has a complete saved linked-master contract, replay the current candidate without
rebinding it:

```powershell
py -3 experiments/homm3_mocap_v2/preview_saved_linked_master.py `
  --linked 'artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/<unit>/<route>/linked_master' `
  --output 'artifacts/homm3_mesh_repair_fleet_v1/adapter-replays/<unit>/<route>-4x' `
  --preview-scale 4 --display-scale 1 --detail-padding 24
```

Use `--candidate-yaw-deg 180` only as a separate facing diagnostic when the source comparison
shows a possible backwards-facing mesh; it does not alter the saved candidate or constitute a
delivery orientation decision.

For an existing capture-skeleton bind that has `capture_bind`, `raw_capture.npz`, and an accepted
idle registration but no fitted-candidate report, use the fixed-camera replay instead of creating
a synthetic report:

```powershell
py -3 tools/homm3_meshy_frame_pose/render_existing_bind_replay.py `
  --bind '.../capture_bind/<unit>_linked_master_bind.glb' `
  --capture '.../linked_master/capture/capture/raw_capture.npz' `
  --master '.../linked_master/master_sequence/master_sequence.json' `
  --registration '.../linked_master_remaining_scale/idle0_registration.json' `
  --out 'artifacts/homm3_mesh_repair_fleet_v1/adapter-replays/<unit>/<route>-3x-source-space-v2' `
  --preview-scale 3 --display-scale 1 --detail-padding 24
```

This renderer selects the accepted idle camera, applies the inverse accepted mesh-to-capture surface
alignment before projection, checks that the saved bind frame is rest-exact, and records full/detail
reels plus a keyframe contact sheet. It is generated-artifact diagnostic evidence only; it does not
promote the existing bind or establish sprite-facing world orientation.

For a fitted candidate, use the saved-motion diagnostic instead of the older canonical-pose
source-vs-candidate renderer:

```powershell
py -3 tools/homm3_meshy_frame_pose/render_saved_fit_orientation.py `
  --bind 'artifacts/homm3_mesh_repair_fleet_v1/candidates/<unit>/<candidate>/fitted_bind.glb' `
  --motion 'artifacts/homm3_mesh_repair_fleet_v1/candidates/<unit>/<candidate>/retargeted_motion.npz' `
  --run-dir 'artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/<unit>' `
  --out 'artifacts/homm3_mesh_repair_fleet_v1/candidates/<unit>/saved-fit-orientation-diagnostic' `
  --yaw 0 25 180 --preview-scale 4
```

This consumes the fitted motion matrices directly. It is still generated-artifact evidence: camera
yaw readability does not by itself prove sprite-facing world orientation or anatomical L/R binding.

The next saved-bind control batch covered `h3_skeleton`, `h3_walking_dead`, and `h3_zealot` at the
corrected 1350px source-space replay resolution. `h3_skeleton` is retained as `candidate_reviewed`:
its replay preserves the sampled side/frontal skeleton poses and is rest-exact at 4.58e-16, while
weapon and hand/contact ownership remain open. Walking Dead and Zealot both repeat the per-unit
orientation pattern: zero-offset replays are frontal against narrow side/three-quarter source
presentations, while separate +90 diagnostics recover a side view. Neither is promoted because body,
robe/limb, weapon, and contact geometry remain materially different from the source. Their bilateral
audits report 636/7518 and 2547/5740 mixed vertices respectively; Skeleton reports 1144/8362, and
none of the three audits supports a global Left/Right rename. The +90 outputs are retained only as
candidate-hash-bound orientation diagnostics, not as delivery orientation decisions. The current
queue checkpoint is 65 identity-verified, 3 identity-confirmed-wrong-source, 143 reviewed animation
candidates, 59 reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots.
The 261-vs-262 roster membership ambiguity remains open; the queue still requires user confirmation
of the authoritative 261-ID membership before it can be called complete.

The flyer follow-up for `h3_faerie`, `h3_harpy`, and `h3_harpy_hag` was intentionally refused by
the fixed-camera replay before rendering: each selected hybrid bind has 37 joints while the raw
capture has 25, with twelve bind-only `BN_Wing_*` joints. These are recorded as
`rejected_needs_shared_adapter` evidence rather than silently dropping or freezing the wing chains.
No reel, bilateral audit, or left/right conclusion is claimed for them until the shared flyer
adapter has an explicit wing-chain motion contract. The current queue checkpoint is therefore 146
reviewed animation candidates, 59 reviewed adapter-evidence rows, 259 unresolved repair rows, and
3 excluded pilots, with the 261-vs-262 roster membership confirmation still open.

The flyer route was then corrected rather than rejected: `h3_faerie`, `h3_harpy`, and
`h3_harpy_hag` use the matching 37-joint `hybrid_capture/raw_capture.npz` with their hybrid binds;
the ordinary 25-joint linked-master capture was the wrong input and is not used. At 1350px, all three
zero-offset replays are frontal against narrow source views, while +90 diagnostics recover their
side-facing body and wing presentations. They are retained as `candidate_reviewed`, not final,
because wing articulation, tail/lower-body, and contact ownership remain open. Their bilateral audits
report 4324/10074, 2740/11345, and 3112/11345 mixed vertices respectively; the hybrid capture-side
families do not establish a global Left/Right rename. The queue checkpoint is now 146 reviewed
animation candidates, 59 reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded
pilots. The 261-vs-262 membership confirmation remains open.

The next compatible replay batch covered `h3_automaton_upg_alt`, `h3_efreet_sufi`, and `h3_genie`
through the `remaining_forced_mixamo_person` route at the same 1350px source-space resolution.
All three are retained as `candidate_reviewed`, not final: their rest frames are exact at
7.77e-16, 1.74e-15, and 1.02e-15 respectively, and their broad animated silhouettes remain
readable, but each still needs a unit-specific camera/yaw decision plus hard-surface, fire-body,
cloth, hand, or contact inspection before promotion. The zero-offset crops show the same
orientation mismatch seen elsewhere, while the +90 diagnostics are retained as per-unit evidence
only; this does not support a fleet-wide Left/Right rename. Their bilateral audits report 511/4424,
2497/7424, and 2216/5789 mixed vertices respectively, which are local ownership warnings rather
than global-side proof. The automaton source has one intentional blank terminal death plate
(`000080.png`); it was preserved with the explicit `HOMM3_ACCEPT_EMPTY_ALPHA=1` contract and was
not silently dropped. The queue checkpoint is now 149 reviewed animation candidates, 59 reviewed
adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262 membership
confirmation remains open, and all evidence in this paragraph is generated-artifact only.

The next Factory control batch covered `hota_factory_bounty_hunter` and `hota_factory_gunslinger`
using their existing scaled binds at 1350px source-space detail. Both are retained as
`candidate_reviewed`, not final: their rest-frame errors are 5.56e-16 and 4.51e-16, and their
contact sheets preserve the hats, coats, arms, weapons, legs, and broad silhouettes. The two view
renders expose unit-local presentation differences against the source plates; neither supports a
fleet-wide Left/Right rename. Their bilateral audits report 1118/6629 and 2036/7472 mixed vertices,
with separated capture-side means. Bounty Hunter still needs weapon/hand, coat, leg, and contact
inspection; Gunslinger needs the same, with explicit follow-up on its leg-region warning. The queue
checkpoint is now 173 reviewed animation candidates, 61 reviewed adapter-evidence rows, 259
unresolved repair rows, and 3 excluded pilots. The 261-vs-262 membership confirmation remains open,
and all evidence in this paragraph is generated-artifact only.

The next control covered `toa_blood_eyed_cyclops` using its existing scaled bind at 1350px
source-space detail. It is deliberately retained as `needs_geometry_work`, not final: the replay is
rest-exact at 6.21e-16 and the head, eye, armor, arms, legs, shield, and broad silhouette remain
visible, but 2335/7210 vertices are mixed (32.39%) and both leg regions carry substantial
opposite-side mass. Capture-side means remain separated at left X 0.243 and right X -0.120, so
this is a local geometry/ownership blocker rather than proof of a global Left/Right swap. The queue
checkpoint remains 178 reviewed animation candidates and now has 62 reviewed adapter-evidence rows,
259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262 membership confirmation remains
open, and all evidence in this paragraph is generated-artifact only.

The next control covered `toa_shahrokh` using its existing scaled bind at 1350px source-space
detail. It is retained as `candidate_reviewed`, not final: the replay is rest-exact at 5.59e-16,
and the contact sheets preserve the bird body, head, wings, tail, and broad flyer silhouette.
The zero-offset and +90 views are unit-local flyer presentations rather than evidence for a
fleet-wide Left/Right rename. Its bilateral audit reports 2112/13932 mixed vertices, but the
generic leg-region report is not treated as semantic flyer evidence; wing-root, tail, beak, and
contact ownership remain open. The queue checkpoint is now 178 reviewed animation candidates, 61
reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262
membership confirmation remains open, and all evidence in this paragraph is generated-artifact only.

The following ToA biped control batch covered `toa_goblin_trapper` and `toa_orc_berserker` using
their existing scaled binds at 1350px source-space detail. Both are retained as `candidate_reviewed`,
not final: their rest-frame errors are 6.68e-16 and 5.24e-16, and their contact sheets preserve
the heads/horns, armor or clothing, arms, legs, weapons, and broad silhouettes. The +90 renders
remain unit-local orientation diagnostics and do not support a fleet-wide Left/Right rename. Their
bilateral audits report 1538/8477 and 1577/8122 mixed vertices, with separated capture-side means.
Goblin Trapper still needs trap/hand, clothing, leg, and contact inspection, including its left-leg
region warning; Orc Berserker still needs weapon/hand, armor, leg, and contact inspection. The
queue checkpoint is now 177 reviewed animation candidates, 61 reviewed adapter-evidence rows, 259
unresolved repair rows, and 3 excluded pilots. The 261-vs-262 membership confirmation remains open,
and all evidence in this paragraph is generated-artifact only.

The next Factory control batch covered `hota_factory_halfling_grenadier` and `hota_factory_mechanic`
using their existing scaled binds at 1350px source-space detail. Both are retained as
`candidate_reviewed`, not final: their rest-frame errors are 1.95e-15 and 8.47e-16, and their
contact sheets preserve the hats/caps, clothing, equipment, arms, legs, and broad silhouettes.
The +90 renders remain unit-local orientation diagnostics and do not support a fleet-wide
Left/Right rename. Their bilateral audits report 720/7261 and 1046/8320 mixed vertices, with
separated capture-side means. Halfling Grenadier needs grenade/hand, vest, leg, and contact
inspection; Mechanic needs equipment/hand, workwear, leg, and contact inspection, including its
right-leg region warning. The queue checkpoint is now 175 reviewed animation candidates, 61
reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262
membership confirmation remains open, and all evidence in this paragraph is generated-artifact only.

The following Cove control batch covered `hota_cove_crew_mate` and `hota_cove_sea_witch` using
their existing scaled binds at 1350px source-space detail. Both are retained as `candidate_reviewed`,
not final: their rest-frame errors are 6.50e-16 and 5.21e-16, and their saved binds preserve the
body, weapon, sash/coat, hat, raised hand, orb, and broad silhouettes. The zero-offset views are
more frontal than the source side/three-quarter plates, while +90 remains a unit-local diagnostic;
this does not justify a fleet-wide Left/Right rename. Their bilateral audits report 859/5516 and
2011/9209 mixed vertices respectively, with separated capture-side means. Crew Mate still needs
machete/hand, sash, leg, and contact inspection; Sea Witch still needs staff/hand/orb, coat, leg,
and contact inspection. The queue checkpoint is now 171 reviewed animation candidates, 61 reviewed
adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262 membership
confirmation remains open, and all evidence in this paragraph is generated-artifact only.

The following compatible replay batch covered `h3_gremlin_upg`, `h3_lizard_assassin`, and `h3_satyr`
at 1350px source-space detail. All three are retained as `candidate_reviewed`, not final: their
rest-frame errors are 3.11e-08, 1.94e-15, and 5.98e-16 respectively, and their broad animated
silhouettes remain readable. The zero-offset crops are frontal against side-facing source plates;
the separate +90 diagnostics recover the side-facing body reads, so these are unit-specific
orientation contracts rather than evidence for a fleet-wide Left/Right rename. The open work is
robe/ball/chain ownership for Gremlin, tail/weapon/contact ownership for Lizard Assassin, and
fur/weapon/contact ownership for Satyr. Their bilateral audits report 1328/7318, 1401/6329, and
1279/15660 mixed vertices respectively; these are local ownership warnings, not global-side proof.
The queue checkpoint is now 152 reviewed animation candidates, 59 reviewed adapter-evidence rows,
259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262 membership confirmation remains
open, and all evidence in this paragraph is generated-artifact only.

The next saved-bind control covered `hota_bulwark_great_shaman` using the existing scaled bind at
1350px source-space detail. It is retained as `candidate_reviewed`, not final: the replay is
rest-exact at 1.09e-15, the antlers, head, robe, legs, staff, and broad silhouette remain readable,
and the separate +90 diagnostic recovers the source side/three-quarter presentation from the frontal
zero-offset replay. Its bilateral audit reports 1243/7362 mixed vertices, with capture-side means
of left X 0.270 and right X -0.077; the mixed-weight and region-side warnings are local ownership
evidence, not proof for a fleet-wide Left/Right rename. Leg, robe, staff, and contact ownership
remain open. The queue checkpoint is now 167 reviewed animation candidates, 61 reviewed
adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262
membership confirmation remains open, and all evidence in this paragraph is generated-artifact only.

The next family control covered `hota_bulwark_snow_elf` and `hota_bulwark_steel_elf` using their
existing scaled binds at 1350px source-space detail. Both are retained as `candidate_reviewed`, not
final: their rest-frame errors are 1.19e-15 and 5.16e-16, and their zero-offset replays preserve
the source front/three-quarter presentation with readable cloth, spear, shield, and body reads.
The +90 renders remain unit-local side diagnostics rather than required corrections. Their bilateral
audits report 2160/8296 and 1834/8661 mixed vertices respectively, with normally separated capture
side means; these are local ownership warnings, not proof for a fleet-wide Left/Right rename. Snow
Elf still needs cloth/spear/hand/contact inspection; Steel Elf still needs shield/spear/hand/cloth/
contact inspection. The queue checkpoint is now 169 reviewed animation candidates, 61 reviewed
adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262 membership
confirmation remains open, and all evidence in this paragraph is generated-artifact only.

The next saved-bind control batch covered `h3_vampire`, `h3_vampire_lord`, and
`hota_bulwark_jotunn` at 1350px source-space detail. All three are retained as `candidate_reviewed`,
not final: their rest-frame errors are 8.19e-15, 1.24e-08, and 8.97e-09 respectively, and their
body silhouettes remain readable. The zero-offset crops are frontal against side/three-quarter
source plates, while the separate +90 diagnostics recover the side-facing reads; this is a
per-unit orientation contract, not evidence for a fleet-wide Left/Right rename. The open work is
appendage/hand/contact ownership for Vampire, robe/hand/contact ownership for Vampire Lord, and
fur/weapon/contact ownership for Jotunn. Their bilateral audits report 1808/8571 on the 50-joint
Vampire bind, 2873/10772, and 1748/10651 mixed vertices respectively; these are local ownership
warnings, not global-side proof. The queue checkpoint is now 155 reviewed animation candidates,
59 reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The
261-vs-262 membership confirmation remains open, and all evidence in this paragraph is
generated-artifact only.

The following batch covered `hota_cove_swashbuckler`, `hota_factory_automaton`, and
`hota_factory_dreadnought` at 1350px source-space detail. Swashbuckler and Dreadnought are retained
as `candidate_reviewed`, not final: their rest-frame errors are 1.29e-15 and 7.04e-16, and their
side/three-quarter source plates are recovered by the unit-local +90 diagnostics from frontal
zero-offset replays. Factory Automaton is deliberately `needs_geometry_work`: its rest frame is
exact at 1.90e-15 and the side view is recoverable, but its bilateral audit is materially anomalous
(3284/10438 mixed vertices, left capture mean X -0.211, right mean X +0.196), so its local
side/orientation contract must be resolved before promotion. This does not justify a fleet-wide
Left/Right rename. The queue checkpoint is now 165 reviewed animation candidates, 61 reviewed
adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262 membership
confirmation remains open, and all evidence in this paragraph is generated-artifact only.

The next Cove batch covered `hota_cove_pirate`, `hota_cove_sea_dog`, and `hota_cove_seaman` at
1350px source-space detail. Pirate and Sea Dog are retained as `candidate_reviewed`, not final:
their rest-frame errors are 4.23e-15 and 7.02e-16, their broad silhouettes remain readable, and
their +90 diagnostics recover the source side presentation from the frontal zero-offset replay.
Seaman is deliberately `needs_geometry_work`: its rest frame is exact at 9.10e-16 and its yaw
diagnostic is available, but the replay is an untextured white silhouette, so material/texture
quality cannot be accepted. The bilateral audits report 2726/13082 for Pirate, 1856/17072 for Sea
Dog, and 1164/8343 for Seaman; these are local ownership warnings, not proof of a global
Left/Right swap. The queue checkpoint is now 163 reviewed animation candidates, 60 reviewed
adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262 membership
confirmation remains open, and all evidence in this paragraph is generated-artifact only.

The next control batch covered `hota_bulwark_yeti_runemaster`, `hota_bulwark_kobold_foreman`, and
`hota_cove_nix` at 1350px source-space detail. All three are retained as `candidate_reviewed`, not
final: their rest-frame errors are 2.28e-08, 1.05e-15, and 8.82e-16 respectively, and their
body, robe, fur, and weapon silhouettes remain readable. The zero-offset crops are frontal against
the side/three-quarter source plates; the +90 diagnostics recover the side-facing reads, so this
remains a unit-specific orientation contract and does not justify a fleet-wide Left/Right rename.
The open work is fur/staff/robe/contact ownership for Yeti Runemaster, robe/weapon/contact
ownership for Kobold Foreman, and robe/spear/contact ownership for Cove Nix. Their bilateral audits
report 2563/12207, 875/8836, and 1550/18515 mixed vertices respectively; these are local ownership
warnings, not global-side proof. The queue checkpoint is now 161 reviewed animation candidates,
59 reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The
261-vs-262 membership confirmation remains open, and all evidence in this paragraph is
generated-artifact only.

The latest control batch covered `hota_bulwark_jotunn_warlord`, `hota_bulwark_shaman`, and
`hota_bulwark_yeti` at 1350px source-space detail. All three are retained as `candidate_reviewed`,
not final: their rest-frame errors are 1.19e-08, 8.30e-09, and 1.03e-08 respectively, and their
body, armor/robe, fur, and weapon silhouettes remain readable. The zero-offset crops are frontal
against the side/three-quarter source plates, while the +90 diagnostics recover the side-facing
reads; this remains a per-unit orientation contract and does not justify a fleet-wide Left/Right
rename. The open work is fur/shield/weapon/contact ownership for Jotunn Warlord, robe/staff/contact
ownership for Shaman, and fur/staff/contact ownership for Yeti. Their bilateral audits report
1543/8582, 1011/8300, and 1210/9571 mixed vertices respectively; these are local ownership
warnings, not global-side proof. The queue checkpoint is now 158 reviewed animation candidates,
59 reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The
261-vs-262 membership confirmation remains open, and all evidence in this paragraph is
generated-artifact only.

The next saved-bind control covered `hota_factory_sentinel_automaton` at 1350px source-space
detail. It is retained as `candidate_reviewed`, not final: the replay is rest-exact at 7.45e-16,
the broad industrial body, armor, legs, and side assemblies remain readable, and the separate +90
diagnostic recovers the source side/three-quarter presentation from the rear/frontal-ish zero-offset
replay. Its bilateral audit reports 2298/11042 mixed vertices, with capture-side means of left X
0.274 and right X -0.157; this is a local ownership and orientation warning, not evidence for a
fleet-wide Left/Right rename. Hard-surface, leg, side-assembly, and contact ownership remain open.
The queue checkpoint is now 166 reviewed animation candidates, 61 reviewed adapter-evidence rows,
259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262 membership confirmation remains
open, and all evidence in this paragraph is generated-artifact only.

The latest hybrid flyer control batch covered `h3_pixie`, `h3_seraph`, and `h3_sprite` at 1350px
source-space detail using their saved 37-joint hybrid binds, hybrid captures, and per-unit
registrations. All three are retained as `candidate_reviewed`, not final: their replay rest-frame
errors are 4.88e-09, 1.29e-08, and 1.09e-08 respectively, and the body, wings, legs, and cloth or
robe silhouettes remain readable through the sampled poses. Their accepted registrations already
encode different mesh-to-source rotations, so the separate +90 renders are orientation diagnostics
only; they do not support a fleet-wide Left/Right rename. Bilateral audits report 2564/7300,
413/4143, and 2453/7299 mixed vertices respectively. Pixie and Sprite retain larger local wing,
leg, cloth, and contact ownership warnings, while Seraph is substantially cleaner but still needs
wing-root, leg, weapon, and contact validation. These are local ownership warnings, not proof of a
global side swap. The queue checkpoint is now 181 reviewed animation candidates, 62 reviewed
adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262 membership
confirmation remains open, and all evidence in this paragraph is generated-artifact only.

The remaining queue is now route-gated rather than silently treated as repaired. `h3_hydra` has a
completed SmartRig cascade artifact with ten fitted clips, but its generic zoo-dragon source-space
bind fails closed on `j83` at the front/top containment boundary and no paired replay bind/report
was emitted; the existing SmartRig delivery does not have the saved source-space registration and
capture contract needed to substitute for it. `h3_dread_knight` now has a route-local mounted
registration and a 69-frame high-resolution fixed-camera replay, but the zero-offset view is
backwards relative to its source sprite and the separate +180 diagnostic only establishes a
unit-local orientation correction. The mounted replay also remains materially wrong in
horse/rider/cape silhouette and used a route-specific raw authored-bind loader because no standard
adapter regions sidecar exists, so it is `needs_geometry_work`, not final. `h3_wolf_raider` and
`h3_wolf_rider` still have mounted horse/coyote bind material but no equivalent route-local saved
idle registration/replay. `toa_boar_rider` has no authoritative run directory in the current mocap
root. These units remain queued until their own mounted or non-biped route supplies the required
registration, capture, and bind provenance; no generic biped replay or global Left/Right rename is
being used as a fallback.

The Hydra blocker was rechecked rather than accepted as a raster epsilon. The containment raster now
has a focused boundary-rounding regression test, and parentless registration records when it has to
fall back from a vertex-mean center to the mesh AABB center. That fix is committed as `e481f23802`,
but a fresh direct `h3_hydra` zoo-dragon run still fails closed: the AABB-center candidates leave
many joints outside the mesh's height-conditioned front/side/top slabs, so the asset needs a
non-biped registration or geometry repair rather than a permissive tolerance. The mounted route
does contain completed generated artifacts for `h3_dread_knight`, `h3_wolf_raider`, and
`h3_wolf_rider`; Dread now has its route-local registration and 69-frame high-resolution replay,
while Wolf still lacks the same registration/replay contract. No completion status was promoted
from those artifacts. Rebuild the queue after staging the Dread review sidecar; the generated-
artifact and membership counts remain the source of truth rather than this paragraph. A direct
Wolf check makes the provenance gap concrete: each mounted bind has 61 `mount:`/`rider:` joints,
but the adjacent saved capture is only the 25-joint unmounted `mixamorig:` skeleton. The names and
joint counts cannot drive the mounted bind, and the report's historical mounted-source path is not
present in the checkout, so no Wolf registration or replay is fabricated from that mismatch.

### Latest checkpoint: 2026-09-21

Hydra now has a route-local SmartRig non-biped registration adapter rather than a permissive retry
of the failed zoo-dragon biped route. The adapter reads the staged clip's explicit `Orientation`
provenance (`-90` degrees), normalizes the skeleton into the mesh frame with a unit-local `+90`
inverse, and refuses to infer orientation from bilateral joint names. It emits an idle-only
linked-master capture, sequence, and accepted registration under
`remaining_forced_smartrig_cascade`; the adapter is implemented in
`experiments/homm3_mocap_v2/register_smartrig_idle0.py` and the explicit yaw override is covered
by the registration helper contract. The route does not rewrite the SmartRig bind or staged
clips.

The resulting 3600px source-space idle replay is retained under
`artifacts/homm3_mesh_repair_fleet_v1/adapter-replays/h3_hydra/smartrig-idle-source-space-v1/replay-8x-v2/`.
Its rest-frame maximum vertex error is `5.41e-07`, but the readable frame comparison exposes the
real blocker: the Hydra source is a small coiled green serpent while the current candidate renders
as a tall armored humanoid-like assembly. This is a source/geometry/body-plan failure, not a
remaining orientation-only or global Left/Right problem. The review sidecar records
`needs_geometry_work`; no delivery or runtime proof is claimed. The SmartRig bind also lacks the
standard adapter regions sidecar and keeps non-identity vendor rest rotations, so the replay uses
a route-specific raw GLB diagnostic loader and is not promoted as a normal adapter candidate.

The queue/ledger are rebuilt and now report 65 identity-verified rows, 3
identity-confirmed-wrong-source rows, 181 reviewed animation candidates, 64 reviewed
adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. The 261-vs-262
membership confirmation remains open. The generic Hydra zoo-dragon failure remains preserved
separately; this SmartRig result proves the explicit non-biped orientation path is feasible, not
that the current Hydra mesh is acceptable. The next action is a verified Hydra-source Meshy
regeneration or Hydra-specific mesh, followed by the same 3600px idle and full saved-clip review.
Do not rename all Left/Right joints.

The next high-resolution controls covered `h3_horned_demon` and `h3_snow_elf_upg_alt` through
their existing saved capture-bind routes. Both generic adapters had failed on nonstandard joint
naming (`Left UniRig arm chain` and `two UniRig leg roots`), but the binds still carried their own
captures and accepted registrations, so the review used the fixed-camera existing-bind renderer
without inventing bilateral names. At 3600px source-space detail, Horned Demon is a compact red,
armored, digitigrade demon in the sprite but a much taller upright humanoid with different head,
torso, limb, and contact design in the bind replay; Snow Elf is a short, broad, blue-and-silver
shielded unit in the sprite but a taller, narrower dark-clad polearm unit in the replay. Their
rest-frame errors are `4.20e-16` and `4.79e-16`, respectively, so these are source/geometry/body-
plan failures rather than rest placement or global orientation failures. The replays cover 66 and
69 saved frames and are recorded as `needs_geometry_work`; no global Left/Right rename is implied.
The sidecars are under the corresponding `candidates/h3_horned_demon/` and
`candidates/h3_snow_elf_upg_alt/` review directories. The queue has been rebuilt with both
sidecars; the next actionable fleet rows are now verified-source Meshy regeneration for
Hydra, Horned Demon, and Snow Elf, while both mounted Wolf rows and Boar Rider remain provenance-
blocked.

The approved source-image Meshy 7.1 regeneration was then run once for each of those three
verified-source geometry failures at an 8000-poly target. All three remote tasks succeeded, but
none passed the owned exact-reference bind gate: Hydra rest identity was `3.33e-16` with 56.7%
of bare vertices outside the reference plate; Horned Demon was `2.22e-16` with 54.3% outside; and
Snow Elf was `2.22e-16` with 44.9% outside. Horned Demon and Snow Elf also retain reference-pivot
plate disagreement, while Snow Elf has 203 and Horned Demon two edges past the tearing review
limit. Hydra's owned audit had zero torn edges past that limit, but still fails the plate/pivot
contract. These candidates are therefore retained as `needs_geometry_work`, not replayed or
promoted. Their source meshes, task metadata, owned-bind reports, and review sidecars are kept
under the corresponding `meshy_downloads/`, `meshy-binds/`, and fleet candidate directories.
This confirms that the first Meshy regeneration did not solve the body-plan/registration problem;
it does not support a global Left/Right rename. A verified source plate or unit-specific mesh is
still required before the 3600px saved-clip replay gate can be meaningfully passed.

### Corrective checkpoint: saved-motion replay and registration separation

The first source-Meshy conclusion above was too strong. The high-resolution candidate-vs-plate
turn views show that the Hydra source candidate is recognizably a three-headed quadruped, and the
Horned Demon and Snow Elf T-pose candidates are recognizable source-conditioned meshes. Their
old registered-reference audits still fail, but the large bare-surface off-plate percentages are
also exposing a mismatch between the replacement surface and the older capture/plate registration;
they are not, by themselves, proof that another generation is required. The Hydra result therefore
remains withheld from promotion while its source/registration route is repaired, rather than being
discarded as a geometry failure.

The previous Horned Demon and Snow Elf comparison reels also contained a diagnostic defect. They
reconstructed candidate transforms from joint positions and an older bind report, which discards
inherited axial rotation. That path could create the apparent head/leg collapse and consistent twist
without implicating Left/Right ownership. `reel_meshy71_candidate.py` now accepts the fitter's
`retargeted_motion.npz` and skins both vertices and normals with its saved rotations/offsets. The
new 2586x1860 paired replays are retained under each `meshy-fit-tpose-v1/saved-motion-replay/`
directory and are the only valid comparison reels for these refits. They are still candidate-only:
Horned Demon retains residual stretch and route mismatch, while Snow Elf still needs unit-specific
shield/weapon/cloth attachment review. Neither is final quality or delivery proof, and neither
supports a global side rename. The active sidecars are now the `meshy-tpose-fit-v1` reviews, with
`needs_shared_adapter` until each unit has a demonstrated registration/correspondence route.

The next action is to establish that unit-local route and rerun the exact-reference and bilateral
audits using saved motion. Do not regenerate Meshy source images solely because of the superseded
position-only reel. Wolf and Boar Rider provenance blockers remain unchanged.

The first Hydra candidate-specific registration experiment is now also recorded. An explicit
SmartRig orientation-aware registration was generated over the Meshy surface, but the exact bind
gate refused it because the required extent correction was `2.2939`, outside the accepted band
`(0.253779, 0.761336)`. The registrar's inside-mesh acceptance was therefore only a containment
placement, not a valid subject correspondence; no permissive scale was added. This is the desired
fail-closed result and leaves Hydra at `needs_shared_adapter`, not promoted geometry and not a
global side-binding problem. The route-local registration support is reusable through the explicit
`--registration` option on `bind_meshy71_candidate.py`.

### Follow-up checkpoint: Astra review and laterality audit

An Astra review of the current direction confirmed that the old position-only comparison
reels were not a valid twist evaluation: they rebuilt candidate transforms from joint positions
and discarded inherited axial rotation. That contract is now corrected, and the Horned Demon
and Snow Elf replays consume their saved `retargeted_motion.npz` rotations and offsets. The
review also confirmed that backward-facing presentation is unit-local orientation evidence,
not grounds for a fleet-wide Left/Right rename.

The next rejected shared-adapter fixtures were checked directly rather than re-labeled. The
Crusader and Gremlin rest overlays place plausible skeletons, and their candidate mesh-side
weights remain separated: positive-side vertices average `0.680/0.027` left/right for
Crusader and `0.799/0.006` for Gremlin; negative-side vertices average `0.010/0.840` and
`0.001/0.810`. No dominant limb region crossed to the opposite side. Their saved-motion
deformations nevertheless reach `34.723x` and `41.472x` worst triangle-edge stretch, so the
consistent failure is a local retarget/ownership/correspondence problem, not a proven global
side-name swap. Both remain `rejected_needs_shared_adapter`; no new Meshy generation or global
rename is justified by this evidence.

A controlled counterfactual retarget was also run on those two fixtures. Feeding the registered
idle pose as the source rest reduces median edge stretch (`27.145x` to `13.765x` on Crusader;
`15.140x` to `9.373x` on Gremlin), but it leaves the candidate at its A-pose bind instead of
replaying the captured idle motion. It is therefore not a valid repair; the canonical-T-pose
source-rest contract remains in force. This separates a tempting lower-number shortcut from a
correct animation result.

This checkpoint remains generated-artifact evidence only. The queue is unchanged at 181
reviewed animation candidates, 66 reviewed adapter-evidence rows, 259 unresolved repair rows,
and 3 excluded pilots; the 261-vs-262 membership confirmation is still open. The next repair
work is a shared adapter/ownership correction with the saved-motion edge-stretch audit kept as
the acceptance diagnostic, followed by high-resolution replay review. No installed, runtime,
or final-quality claim is made.

### Follow-up checkpoint: corrected-source candidates and fitter-owned replay

The three confirmed wrong-source rows were checked against the retained Meshy 7.1 source
candidates. The replacement source candidates are semantically correct: `h3_mechanic_upg_alt`
is the armed mechanic, `h3_paokai` is the horned winged dragon, and `h3_pegasus` is the mounted
winged horse and rider. The stale canonical SmartRig meshes remain quarantined and therefore
continue to report `confirmed_wrong_source`; that status is not cleared merely because a
replacement candidate exists. No global side mapping was changed.

The mechanic replacement now has a corrected 2586x1860 per-clip replay under
`candidates/h3_mechanic_upg_alt/meshy71-tpose-fit-v1/saved-motion-replay-v2/`. It consumes the
fitter-owned `retargeted_motion.npz` rotations and offsets directly. Across all nine sampled
clips its candidate worst edge stretch is `5.46x` to `7.35x`, and the rendered attack/death
samples retain the mechanic silhouette and the configured hand-owned firearm without a uniform
left/right twist. It is retained as `candidate_reviewed`, not final quality: the hose remains
fused geometry, wrist/prop ownership is still open, and the Meshy topology preflight still
reports genuine boundary/non-manifold edges. The failed attempt to rebind an already fitted
surface is retained under `meshy-binds/h3_mechanic_upg_alt/tpose-fit-v1/` as diagnostic evidence,
not treated as a candidate rejection.

`reel_meshy71_candidate.py` now permits a saved-retargeted replay to use a fitter report without
an obsolete similarity block, and its `--skip-master` mode writes the per-clip metrics and
high-resolution GIFs without retaining the memory-heavy aggregate reel. This prevents a valid
per-clip review from stalling while building a several-gigabyte master GIF. Paokai remains
`needs_geometry_work`: its 768px-plus replay shows wing/body plate collapse despite correct
same-side wing ownership. Pegasus remains `needs_shared_adapter`: the mounted rider, horse,
wings, and weapon require a dedicated mounted-flyer route, not the existing eagle-flyer or a
generic biped fallback.

The queue was rebuilt after this checkpoint and remains at 181 reviewed animation candidates,
66 reviewed adapter-evidence rows, 259 unresolved repair rows, and 3 excluded pilots. All
evidence here is generated-artifact only; no installed, runtime, gameplay, or final-quality
claim is made.

### Follow-up checkpoint: Astra evidence-selection review and saved-motion mechanic replay

A fresh Astra review found two evidence-selection hazards and they are now corrected. The
`reel_meshy71_candidate.py` CLI requires an explicit candidate motion mode instead of silently
defaulting to the position-derived canonical-T-pose path. Fitter candidates must use
`--candidate-motion saved-retargeted` with their `retargeted_motion.npz`; the older position
reconstruction modes remain explicit diagnostics only. The fleet queue producer also promotes a
review's `highResolutionReplay` into `repairDetailReel`, so a later high-resolution replay cannot
be hidden by an older generic `animationReel` field. The Paokai row now resolves to its
`preview-hires-v3/detail_reel.gif` evidence.

The corrected Mechanic candidate was rerendered from its saved rotations and offsets with
per-clip `2586x1860` panels. The reviewed idle and mid-motion frames preserve the mechanic
silhouette and hand-owned firearm without a uniform left/right twist. The hose remains fused
body geometry, and genuine boundary/non-manifold topology findings remain, so the candidate is
still `candidate_reviewed`, not final quality. The current active review is
`candidates/h3_mechanic_upg_alt/zzzzzz-meshy71-saved-motion-review-v2/review.json`; the older
`zzzzz-meshy71-tpose-8x-review-v1` sidecar is retained as superseded historical evidence.

The corrected-source identity state remains deliberately separate: the stale canonical meshes
for Mechanic, Paokai, and Pegasus still report `confirmed_wrong_source` while their replacement
Meshy candidates are reviewed independently. Paokai remains `needs_geometry_work` under the
existing eagle-flyer comparison, and Pegasus remains `needs_shared_adapter` pending a mounted
horse/rider/wing route. No global Left/Right rename or generic biped fallback is justified.

Verification after this checkpoint: the focused replay and queue tests pass, and the queue was
rebuilt at `181` reviewed animation candidates, `66` reviewed adapter-evidence rows, `259`
unresolved repair rows, and `3` excluded pilots. This remains generated-artifact evidence only;
there is no installed, runtime, gameplay, or final-quality proof.

### Follow-up checkpoint: Mechanic prop-isolation rerun

The Mechanic prop inspection was rerun against the exact corrected Meshy source mesh at panel
scale `4` after an older failed `inspection.json` was found in the output directory. The current
inspection is complete: the firearm and green canister form one connected cut of `349` faces and
`185` welded nodes. The high-resolution prop-only and body-only views retain the full firearm,
while the body-only view makes the remaining small prop fragment and the fused hose visible.
This clears stale diagnostic state, not the geometry issue: hose ownership, the residual fragment,
and the candidate's boundary/non-manifold topology remain unresolved and candidate-only.

The queue was rebuilt after the inspection and still resolves the active Mechanic review to the
saved-motion replay. The fleet remains at `181` reviewed animation candidates, `66` reviewed
adapter-evidence rows, `259` unresolved repair rows, and `3` excluded pilots. The next
productive lane is a Paokai dragon-specific wing/body ownership experiment using the existing
captured motion and high-resolution replay; do not spend another Meshy generation or infer a
global Left/Right rename from the current evidence. Resume the queue audit with:
`py -3 tools/homm3_meshy_frame_pose/build_mesh_repair_fleet_queue.py --out artifacts/homm3_mesh_repair_fleet_v1`.

A bounded hose-segmentation probe was also run from rear-view surface picks. The initial seed set
selected `634` faces and `343` welded nodes but split into two components and left the main hose
loop in the body-only view. A widened seed set produced one connected region (`1699` faces,
`881` welded nodes), but it also removed coat/body pieces in the body-only view. Both probes are
rejected as ownership recipes and are retained only as diagnostic evidence; no hose vertices or
candidate weights were changed. A future hose treatment must first establish a connected,
visually complete region without body over-selection before any torso-owned or rigid attachment
is tested.

### Follow-up checkpoint: Paokai ownership counterfactual rejected

The Paokai dragon-specific ownership question was tested against the existing 50-joint eagle-flyer
capture, the pinned capture bind, and the saved fitted `candidate_weights.npz`. The diagnostic
`tools/homm3_meshy_frame_pose/paokai_ownership_counterfactual.py` wrote
`candidates/h3_paokai/paokai-ownership-counterfactual-v3/counterfactual_report.json` and 768 px
replays for three non-delivery variants: the current fitted weights, the current weights masked to
each labeled region's profile joints, and a one-bone-per-region rigid baseline. The region mask
was usable for `13682/13684` vertices; two vertices retained their current support as an explicit
fallback. No production bind, pinned sidecar, or queue row was modified.

The result rejects an ownership-only repair for this candidate. The current fitted weights are the
least damaging of the three on the saved motion (`1.577x` all-frame edge-stretch p95;
`1.649x` AttackFront; `1.923x` Death). Region restriction raises those values to `1.874x`,
`2.039x`, and `2.661x`; the rigid baseline reaches `4.203x`, `5.259x`, and `6.017x`.
The 768 px comparison panels show the same compact body/wing collapse, with restriction adding
plate tearing rather than restoring the authored dragon silhouette. This is evidence against a
global left/right swap and against simply hardening the existing region labels. Paokai remains
`needs_geometry_work`; the productive next step is geometry/registration correction or a new
dragon-specific candidate, followed by the same high-resolution replay. The three `.npz` files
and replays are retained as diagnostic counterfactuals only.

### Follow-up checkpoint: Paokai high-resolution refit remains geometry-blocked

Because the original Paokai skin fit optimized at `192` px with edge-strain weight `0.5`, an
isolated refit was run at `768` px against the same pinned bind, saved 50-joint capture, and all
70 authored frames. It stopped at the five-minute budget after 50 optimizer steps and wrote
`linked_master/skin_fit_hires_v1/` plus the saved-motion replay
`linked_master/replay_hires_v1/replay_report.json`. The refit improved the saved-motion edge
stretch p95 from `1.577x` to `1.391x` overall, `1.649x` to `1.442x` on AttackFront, and
`1.923x` to `1.612x` on Death. This is a useful diagnostic improvement, not a final-quality
acceptance: the 768 px contact still shows a compact wing/body mass and plate tears against the
source dragon, especially in the high-motion rows. The new weights and replay are therefore
retained as `needs_geometry_work` evidence rather than promoted into the active candidate review.
The result separates a real high-resolution weight refinement opportunity from the unresolved
geometry/registration limitation; no global laterality change is indicated.

### Follow-up checkpoint: Pegasus mounted-adapter blocker confirmed

The next Astra-recommended lane was checked directly. The corrected Pegasus Meshy candidate is the
intended mounted winged horse and rider, but the only retained capture is a 65-frame, 25-joint
Mixamo humanoid with hips, spine/head, arms, and legs only. It has no horse branch, rider/mount
separation, wing chains, seat constraint, or weapon-owner contract. The old canonical mesh is a
bear-like wrong-source artifact and remains quarantined; the forced eagle-flyer result is adapter
evidence only and is not a mounted repair.

The superseding review is
`candidates/h3_pegasus/zzzz-pegasus-mounted-adapter-blocker-v1/review.json`. Pegasus remains
`needs_shared_adapter`. This is a structural blocker, not evidence for a Left/Right swap. The
professional next route is a dedicated two-actor mounted composition extended with explicit wing
controls, then a new owned bind and high-resolution replay; reusing the current 25-joint biped or
the generic eagle-flyer route would silently omit the horse/rider/wing ownership contract.

### Follow-up checkpoint: mounted Wolf review and Boar source blocker

The next three formerly queued mounted rows were reconciled against the semantic identity pins and
retained generated evidence. `h3_wolf_raider` is correctly pinned to the helmeted rider on the dark
wolf under the legacy `h3_wolf_rider_smartrigged.glb` filename, while `h3_wolf_rider` is correctly
pinned to the unhelmeted rider on the gray wolf under `h3_wolf_raider_smartrigged.glb`. (Superseded
2026-09-27: the files were renamed so each basename names its own unit; the sha pins are unchanged.) This is a
semantic filename correction already owned by `mounted_asset_identity.py`; it is not a reason for a
fleet-wide Left/Right rename. Both full-set mounted routes report generated-artifact completion, but
the retained strict review rejects the corresponding motion/surface quality. Neither row had a
retained high-resolution contact suitable for final-quality review, so both now have explicit
`needs_geometry_work` sidecars rather than remaining silently queued:

* `candidates/h3_wolf_raider/zzzz-wolf-raider-mounted-review-v1/review.json`
* `candidates/h3_wolf_rider/zzzz-wolf-rider-identity-review-v1/review.json`

The Wolf Raider review records the failed idle-appearance, depth-unclipped, and animated-surface
gates, incomplete source extension/sword sweep, and stretching ownership boundaries. The Wolf Rider
review preserves the corrected-mesh identity boundary, rejects reuse of the invalidated Raider
pairing, and records that the weapon-only boundary trial correctly found no justified body edit.
The next mounted work must rerun each semantically pinned mesh with saved motion and high-resolution
per-clip contacts before any promotion.

`toa_boar_rider` is now an explicit `needs_source` blocker under
`candidates/toa_boar_rider/zzzz-boar-rider-source-blocker-v1/review.json`. Its retained 61-joint,
30-frame two-actor candidate has a useful high-resolution contact and serialized parity, but remains
`accepted:false` and cannot be evaluated as a Boar because the supposed Boar source is a byte-identical
Wolf payload (`57` joints, `12863` vertices, `15122` triangles; Orientation only rotates it). The
provisional reel is retained as failed source evidence, not accepted animation. A genuine Boar mesh
must be pinned before composition or laterality conclusions are revisited.

The queue was rebuilt after this checkpoint. It now reports `181` reviewed animation candidates,
`69` reviewed adapter-evidence rows, `259` unresolved repair rows, and `3` excluded pilots. The
261-vs-262 membership confirmation remains open. All three reviews are generated-artifact evidence
only; no installed, runtime, gameplay, or final-quality proof is claimed.

### Follow-up checkpoint: unresolved provenance batch pinned

The remaining source-gated rows that had no review pointer were checked without conflating missing
provenance with a source mismatch. The mesh and selected upscale hashes are now recorded in explicit
`provenance-audit-v1/review.json` sidecars for `h3_banshee`, `h3_genie_upg`, `h3_magog`, `h3_orc`,
`h3_orc_chieftain`, `h3_wight`, `hota_cove_corsair`, `hota_cove_sorceress`, and
`hota_cove_tidecaller`. Each remains `needs_source`: no retained Meshy input/task record was found,
so no animation candidate or source-identity claim is being promoted. The next action is either to
recover the exact input provenance or submit a new explicitly pinned Meshy 7.1 request; no blind
regeneration or donor substitution is authorized by this audit.

This raises the queue's reviewed adapter-evidence count to `78` while leaving `259` repair rows
unresolved. The queue has no silent `queued` rows, and its source membership remains the
261-vs-262 `needs_user_confirmation` delta. Resume the queue audit or a bounded source-recovery
batch with:
`py -3 tools/homm3_meshy_frame_pose/build_mesh_repair_fleet_queue.py --out artifacts/homm3_mesh_repair_fleet_v1`.
These sidecars are provenance evidence only; they do not establish installed, runtime, gameplay, or
final-quality proof.

### Follow-up checkpoint: Fury unit-local orientation contract

The low-resolution Fury contact was not sufficient to judge the apparent twist, so the exact saved
bind was replayed at `3600px` output resolution across all `67` captured frames. The zero-offset
replay showed the source sprite as a right-facing profile while the candidate read nearly front-on.
The documented `+90` camera-yaw diagnostic then made the rest frame read as the same right-facing
profile as the source. This is a unit-local orientation/registration correction, not a fleet-wide
Left/Right rename and not a weight acceptance result.

The superseding review is
`candidates/h3_fury/zzzz-fury-yaw90-highres-review-v1/review.json`. Its `1800px` yaw-corrected
contact and detail reel still expose real body-proportion, wing, lower-body, and talon ownership
differences across the saved motion, so Fury remains `needs_geometry_work`. The zero-offset 8x
replay, yaw-corrected 4x replay, exact saved bind, and rest-frame error `2.2300921650065435e-08`
are retained as generated-artifact evidence. No deployment, runtime, gameplay, or final-quality
claim is made. A separate `orientation_corrected_registration.json` and replay through that
registration were also emitted; the original accepted registration remains immutable.

The Fury bilateral audit further separates the defects: `2443/11433` vertices have both left and
right mass above `0.1`, but the largest opposite-side masses on dominant vertices are approximately
`0.499/0.500`. That is a local flyer-to-biped ownership warning and does not support a global
left/right joint rename. The next repair should use the corrected registration while addressing the
wing and lower-body ownership model.

### Follow-up checkpoint: Fury hybrid wing adapter replay

The retained Fury flyer experiment was rerun as a real hybrid adapter instead of the
previous generic biped fit. The composed capture keeps the Mixamo body chain and adds
12 explicit Eagle wing joints (37 joints total), with wing roots attached to
`mixamorig:Spine2`; the previous 25-joint result had no wing joints and changed zero
skin weights. The new bind and clips are retained under
`artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_fury/linked_master_hybrid_v2_scale/`.

The 4x saved-motion replay was rendered both at the registration view and with the
unit-local `+90` camera diagnostic. The zero-offset view is front-on relative to the
right-facing source sprite; the `+90` view puts the candidate in the same profile
direction. This remains a Fury-local presentation/registration contract, not a
fleet-wide Left/Right rename. The +90 replay still fails visual acceptance because the
body, lower-body, and talon silhouette do not track the source closely enough. The
hybrid bilateral audit reports 2,114/11,433 mixed vertices; wing own-side mass is
0.891 left and 0.861 right, while the leg regions retain 0.095 and 0.164 opposite-side
mass. Those numbers support local geometry/ownership repair, not a global side swap.

The superseding review is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_fury/zzzz-fury-hybrid-wing-adapter-review-v1/review.json`.
Fury remains `needs_geometry_work`, and the prior generic-biped review is retained as
history rather than being treated as the active candidate. Queue rebuild remains
`181` reviewed animation candidates, `78` reviewed adapter-evidence rows, and `259`
unresolved repair rows; the 261-vs-262 membership confirmation remains open. The
queue test passes. The compose test exercised 6/7 tests but its temporary-file case
hit the environment's `PermissionError`/`WinError 5` before cleanup, so that result is
not claimed as a product regression. All evidence remains generated-artifact only;
there is no installed, runtime, gameplay, or final-quality proof.

Resume with:
`py -3 tools/homm3_meshy_frame_pose/build_mesh_repair_fleet_queue.py --out artifacts/homm3_mesh_repair_fleet_v1`

### Follow-up checkpoint: Fury source-derived Meshy candidate

The existing Fury canonical mesh was confirmed to be the wrong body plan for the
source: it reads as a humanoid with wings in replay, while the pinned source image is
a bird-legged, taloned Fury carrying a weapon. With Meshy generation explicitly
approved, a new source-image candidate was requested from
`artifacts/creature_aaa_3d_upscale/h3_fury.png` using Meshy 7.1 task
`01a0c4ca-f492-7518-8c46-0ca0cf0fdf95`. The 768px static review shows the correct
feathered lower body, bird legs, talons, wings, and weapon; it is retained under
`artifacts/meshy_downloads/meshy71_repair_candidates/h3_fury/source/`.

That candidate was bound against the retained 37-joint body-plus-wing capture and
replayed across all 67 saved frames. The unit-local `+90` camera diagnostic is still
required to place the candidate in the same profile direction as the source. The
high-resolution replay improves the static body-plan mismatch but still shows wing
pose collapse and lower-body/leg deformation, so it remains `needs_geometry_work`.
Its bilateral audit reports 2,827/14,300 mixed vertices, wing own-side mass of 0.853
and 0.796, and leg opposite-side mass of 0.084 and 0.143. These are local ownership
diagnostics, not evidence for a global left/right swap.

The superseding review is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_fury/zzzzzz-fury-meshy-source-replay-review-v1/review.json`.
The 4x contact is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_fury/meshy71-source-replay-v1/yaw90/keyframes_contact.png`.
The next Fury step is to repair wing and bird-leg ownership/deformation from this
source-derived mesh, then rerun the same high-resolution replay. No candidate has
been promoted to delivery; no installed, runtime, gameplay, or final-quality proof
is claimed.

### Follow-up checkpoint: Fury full Eagle species adapter

The 37-joint Mixamo-body hybrid still left the bird-leg contract implicit, so the
source-derived Meshy candidate was rebound against the retained full Eagle capture.
This gives Fury a 50-joint species adapter with explicit bird thighs, horse-links,
toe chains, tail, jaw, and both wing chains. The bind and saved-motion exports are
under
`artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_fury/linked_master_eagle_meshy_v1_scale/`.

The 4x +90 replay preserves the unit-local profile correction and has rest-frame
vertex error `8.364749540756631e-16`. It is a better structural baseline than the
Mixamo hybrid, but it still shows wing-pose and lower-body deformation against the
authored frames. The bilateral audit reports `2,752/14,300` mixed vertices, wing
own-side mass `0.685` / `0.813`, and leg opposite-side mass `0.086` / `0.167`.
Those remain local ownership diagnostics, not proof of a global left/right swap.

The Meshy geometry preflight also found `503` welded boundary edges, `377` welded
non-manifold edges, and three welded surface components, so the candidate has an
independent topology blocker in addition to the replay deformation findings.

The current active review is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_fury/zzzzzzz-fury-meshy-eagle-adapter-review-v1/review.json`.
Fury remains `needs_geometry_work`; the earlier 37-joint hybrid and source-derived
Mixamo replays are retained as comparison evidence. The next repair is now a
species-adapter ownership/deformation pass on the source-derived Meshy geometry,
followed by the same high-resolution +90 replay. No delivery, runtime, gameplay,
or final-quality proof is claimed.

An explicit Meshy `a-pose` comparison was also generated from the same Fury source
image. Its 768px static views have fuller symmetric wings, but the full Eagle
saved-motion replay collapses those wings into a narrow strip and loses the authored
body/weapon pose. It is retained as a negative comparison under
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_fury/meshy71-a-pose-eagle-replay-v1/`;
it does not replace the source-pose Eagle baseline or change the queue's active
review. The a-pose preflight still reports `420` welded boundary edges and `411`
welded non-manifold edges.

### Follow-up checkpoint: Fury bilateral side-mask counterfactual rejected

The suspected twisting failure was isolated with a diagnostic side-mask counterfactual
against the active source-pose Eagle bind. For each labeled `_left` or `_right` region,
opposite-side wing, leg, tail, and toe joints were zeroed and the remaining weights were
renormalized; the original fitted weights were retained wherever the mask had no usable
support. This changed `2,472/14,300` weight rows, with mean per-vertex L1 change
`0.0748459`, while the four-joint region mask covered `14,288/14,300` vertices.

The masked bind was replayed across the same `67` saved frames at the same `1800px` output,
`4x` preview scale, and unit-local `+90` camera yaw. Its contact is visually near-identical
to the active Eagle replay: the wing collapse, lower-body deformation, and pose-dependent
silhouette errors remain. The diagnostic bind and sidecar are retained under
`artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_fury/eagle_meshy_side_mask_v1d/`;
the high-resolution contact is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_fury/meshy71-source-eagle-side-mask-replay-v1/yaw90/keyframes_contact.png`.

This is evidence against a simple global left/right reversal or a blanket opposite-side
weight mask as the root repair. It does not prove every individual joint assignment is
correct; a joint-local mapping error remains possible, but the next productive repair is
species-adapter/geometry/registration work rather than a fleet-wide laterality rename.
The side-mask sidecar uses an explicit diagnostic-only candidate-support override so the
renderer can load the counterfactual; it is not a production bind contract. No queue row,
active review, delivery artifact, installed payload, runtime behavior, gameplay behavior,
or final-quality claim was changed by this experiment.
### Follow-up checkpoint: Magog source candidate exposes an adapter blocker

One small Meshy 7.1 source-recovery batch member was submitted for `h3_magog` using the
pinned `artifacts/creature_aaa_3d_upscale/h3_magog.png` image. Task
`01a0c4fa-3f88-702c-b79d-86a92eff1f64` completed successfully and the candidate is retained
under `artifacts/meshy_downloads/meshy71_repair_candidates/h3_magog/source/`. Its preflight
is recorded at
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_magog/meshy71-source-static-review-v1/geometry_preflight.json`:
one welded component, `35` welded boundary edges, and `48` welded non-manifold edges. It
still requires an owned-bind audit.

The animation attempt correctly found a shared-adapter blocker. The retained Magog
`linked_master` capture provenance names `Eagle#Eagle-Landing/y15` with `50` joints,
including wing and Eagle toe chains. The earlier forced Mixamo-person route refused it
because the reference toes point along the hip-to-hip axis. A new source-mesh replay under
`artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_magog/meshy71_source_scale_v1/`
therefore reused the incompatible Eagle profile only as a diagnostic; its high-resolution
contact at
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_magog/meshy71-source-replay-v1/yaw0/keyframes_contact.png`
is not Magog animation evidence or final-quality proof.

The explicit blocker review is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_magog/zzzz-magog-meshy-source-adapter-blocker-v1/review.json`.
Magog remains source-gated in the fleet queue, and no old mesh was overwritten. The next
valid route is a Magog-compatible biped capture with a validated forward axis, followed by
an owned bind and high-resolution replay; no generic Eagle reuse or fleet-wide laterality
rename is justified.
### Follow-up checkpoint: Orc control confirms the side-mask negative

`h3_orc` was selected as a compatible control because its retained capture is the
25-joint OBJ/Mixamo biped route rather than the Eagle species package exposed by Magog.
Meshy 7.1 task `01a0c508-2db5-7212-ad60-986c67c7ba60` completed from the pinned
`artifacts/creature_aaa_3d_upscale/h3_orc.png` source. The candidate preflight reports one
welded component, `91` welded boundary edges, and `100` welded non-manifold edges. The
candidate bind and 75-frame saved-motion replay were serialized under
`artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_orc/meshy71_source_scale_v1/`;
the high-resolution contact is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_orc/meshy71-source-replay-v1/yaw0/keyframes_contact.png`.

Its bilateral audit still reports `2,894/12,627` mixed vertices and dominant opposite-side
mass near `0.50`. A matched diagnostic mask removed opposite-side arm and leg influences,
changing `3,599` rows with mean L1 change `0.0887017`, but the 4x contact remained visually
near-identical. The masked replay is retained at
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_orc/meshy71-source-side-mask-replay-v1/yaw0/keyframes_contact.png`.

Together with Fury, this rejects a blanket fleet-wide Left/Right swap or simple
opposite-side mask as the common repair. It does not rule out a joint-local mapping error;
those must be tested against the affected geometry and motion. Orc remains
`needs_geometry_work` with the explicit review at
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_orc/zzzz-orc-meshy-source-review-v1/review.json`.
No old inventory mesh was overwritten, and no delivery, runtime, gameplay, or final-quality
claim is made.
### Follow-up checkpoint: Orc Chieftain validates the shared biped control

The second member of the compatible biped test group, `h3_orc_chieftain`, was generated
from its pinned `h3_orc_chieftain.png` source with Meshy 7.1 task
`01a0c512-ce19-73cf-a64c-758b20e2cc33`. The candidate preflight reports one welded
component, `19` welded boundary edges, and `18` welded non-manifold edges. Its 25-joint
source bind and 76-frame replay are under
`artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_orc_chieftain/meshy71_source_scale_v1/`;
the high-resolution contact is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_orc_chieftain/meshy71-source-replay-v1/yaw0/keyframes_contact.png`.

The route preserves the bind identity gate (`2.618455766672135e-16` rest-frame vertex
error), but it is not final-quality evidence: the armor and two-handed weapon still need
detail-panel inspection, and the candidate retains topology and ownership risks. Its
bilateral audit reports `2,667/13,910` mixed vertices and dominant opposite-side mass near
`0.49`. Alongside Orc and Fury, this supports a shared fitted-ownership/geometry problem,
not a blanket Left/Right rename. The explicit review is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_orc_chieftain/zzzz-orc-chieftain-meshy-source-review-v1/review.json`.
No delivery, runtime, gameplay, or final-quality claim is made.
### Follow-up checkpoint: Orc joint-pair laterality search rejected

Because the bilateral masks did not resolve the visible issue, a narrower laterality search
was run on the compatible Orc biped route. The diagnostic screened the saved 75-frame replay
against the source sprite alpha masks at `900px` and tested all lateral pairs, arms, legs,
upper legs, lower legs, shoulders/upper arms, forearms/hands, and feet/toes separately.
Baseline mean alpha IoU was `0.5174427`; the best counterfactual was swapping only the two
upper-leg weights at `0.5188674`. Swapping all leg pairs fell to `0.5067579`, and swapping
arms fell to `0.4901003`.

The upper-leg variant was then rendered at the same `1800px` output and `4x` preview scale:
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_orc/meshy71-source-swap-upper-legs-replay-v1/yaw0/keyframes_contact.png`.
Its contact is visually indistinguishable from the baseline replay at
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_orc/meshy71-source-replay-v1/yaw0/keyframes_contact.png`.
The search report is retained at
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_orc/side_swap_search_v1/metrics.json`;
the swapped bind is diagnostic-only under
`artifacts/homm3_mocap_v2/full_set_mocap_idle0_v1/runs/h3_orc/meshy71_source_swap_upper_legs_v1/`.

This rejects the remaining simple joint-pair swap hypotheses tested here. It does not prove
that every local joint mapping is correct, but it does establish that the current twisting
pattern is not repaired by a global, chain-level, or upper-leg-only Left/Right exchange.
The next repair remains geometry/ownership and source-to-motion correspondence, not a
fleet-wide laterality rename. No active candidate, queue state, delivery artifact, installed
payload, runtime behavior, gameplay behavior, or final-quality claim changed.

### Follow-up checkpoint: biped replay separates orientation from weight rewrite

The high-resolution replay was then inspected at the actual panel resolution rather than
through the small reel contact sheets. On `h3_orc`, the pre-rewrite capture bind and the
final `surface_ignore_narrow` weight replay are effectively identical at both idle and
attack frames. This means the visible arm/body failure is already present before the last
skin rewrite; changing only the final fitted weights is not a root repair.

The inspection also exposed a unit-local orientation mismatch that the previous `yaw0`
contacts hid: the saved Orc bind is front-on while the source plate is a three-quarter /
profile presentation. Replaying the same bind with a diagnostic `+90` camera yaw produces
the expected profile direction, with the source and candidate facing the same way. The
corresponding 4x replay is retained at
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_orientation_plus90_hr/`.
The second compatible biped, `h3_orc_chieftain`, shows the same class of orientation
discrepancy; its `+90` diagnostic is retained at
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_chieftain_orientation_plus90_hr/`.
These are orientation investigations, not accepted registration edits: the active queue
reviews still point to their `yaw0` evidence until the per-unit source-view correction is
encoded and rerun through the registration contract.

As a separate ownership diagnostic, the current Orc weights were masked to each vertex's
declared profile region and renormalized, then compared with a one-joint-per-region
counterfactual. The reusable generator is
`tools/homm3_meshy_frame_pose/diagnose_region_weight_counterfactual.py`; its output is
under `artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_region_counterfactual/`.
The region-restricted replay changes the torso/arm silhouette slightly but does not remove
the attack deformation, so it is not promoted as the shared repair. The underlying audit
does confirm a real quality problem in the unconstrained geodesic rewrite: the Orc
candidate has region-labeled leg vertices carrying unrelated arm mass and only `0.7043`
mean mass inside their declared region before restriction. That is a useful ownership
finding, but the high-resolution replay says orientation/source correspondence must be
fixed before treating the weight restriction as an acceptance candidate.

The next action is therefore to add an explicit unit-local source-view orientation to the
Meshy candidate registration path, rerun the Orc and Orc Chieftain replays at 4x / 1800px,
and only then retest region-constrained ownership. No global Left/Right rename, active
candidate promotion, delivery artifact, installed payload, runtime behavior, gameplay
behavior, or final-quality claim is made.

### Follow-up checkpoint: measured biped source-view correction

The unit-local orientation was measured rather than selected from the old `+90` diagnostic.
`tools/homm3_meshy_frame_pose/measure_bind_yaw_iou.py` rendered the saved bind frame at
4x across `-180` through `+180` degree view offsets. Both compatible biped controls select
`+45` degrees by source-mask overlap: Orc `0.6712` versus `0.6615` at zero, and Orc
Chieftain `0.7199` versus `0.6163` at zero. The sweep reports are retained at
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_yaw_iou_sweep_v1/report.json`
and
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_chieftain_yaw_iou_sweep_v1/report.json`.

Fresh 75-frame and 76-frame 1800px replays at `+45` are retained at
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_orientation_plus45_hr/` and
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_chieftain_orientation_plus45_hr/`.
They correct the presentation direction and make the source/mesh comparison materially
more legible, but the attack panels still show source-to-motion correspondence and
ownership errors: Orc's weapon/arm action is not reproduced, and Chieftain's arms and
weapon do not follow the authored attack. Therefore `+45` is a measured review camera
correction, not final-quality proof and not yet an active queue-registration edit.

The next implementation step is to encode this as an explicit per-unit source-view field
in the Meshy review/replay path, keeping the canonical Left/Right joint names untouched,
then rerun geometry/ownership diagnostics against that corrected view. The two biped
reviews remain `needs_geometry_work`; no delivery, runtime, gameplay, or final-quality
claim is made.

### Follow-up checkpoint: source-view field encoded and ownership counterfactual replayed

The unit-local source-view correction is now an explicit optional input to the shared pose
source loader and the Meshy candidate replay path. `source_view_yaw_offset_deg` is applied
to the accepted registration camera basis while preserving its scale and screen offset;
the generated replay report records the offset under `sourceView`. The default remains zero,
so existing registration and bind consumers are unchanged unless a review explicitly selects
the unit-local diagnostic field. The implementation is in
`tools/homm3_meshy_frame_pose/owned_rerig/pose_source.py` and
`tools/homm3_meshy_frame_pose/render_meshy_candidate_replay.py`.

The Orc review now records `sourceView.yawOffsetDeg = 45` and the Chieftain review records
the same independently measured value. This is a review-path field only: it does not rename
any joint, edit the bind, rewrite weights, or change the active registration artifact. The
explicit reviews remain `needs_geometry_work`.

The Orc region-restricted and region-rigid ownership counterfactuals were replayed at the
corrected `+45` view and 1800px output. Their high-resolution outputs are retained under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_region_counterfactual/restricted_replay_plus45_hr/`
and `.../rigid_replay_plus45_hr/`. The corrected presentation makes the source/mesh
comparison easier to read, but neither counterfactual removes the attack correspondence
failure. This confirms that the orientation field fixes an evaluation confound; it is not
the mesh repair. No active candidate promotion, delivery artifact, installed payload,
runtime behavior, gameplay behavior, or final-quality claim is made.

### Follow-up checkpoint: source attack track is not the gross mismatch

To separate a bad candidate bind from a bad retained motion track, the Orc attack was
rendered as a 1800px source-frame overlay with the captured 25-joint skeleton projected
through the measured unit-local `+45` source-view field. The retained overlay is under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_source_skeleton_attack_plus45_hr/`.
Across the attack frames, the predicted arm/forearm/hand chain follows the source weapon's
broad swing and recovery direction. This is not a final-quality or landmark-accuracy proof,
but it rejects the gross explanation that the candidate is simply playing an unrelated
attack track or that every Left/Right name is globally reversed.

The same capture track still produces the candidate's visible arm/torso deformation when
skinned onto the Meshy surface, and region-restricted or rigid ownership counterfactuals
do not remove it. The next repair therefore remains candidate geometry/ownership, with
the weapon/forearm/torso transition needing a targeted audit. No canonical joint rename,
active candidate promotion, delivery artifact, installed payload, runtime behavior,
gameplay behavior, or final-quality claim is made.

### Follow-up checkpoint: A-pose regeneration does not close the Orc weapon transition

The approved bounded Meshy 7.1 A-pose control was completed for both compatible biped
members rather than starting another request after the first poll. Orc task
`01a0c555-871c-7408-b4c7-38697dbae70c` produced
`artifacts/meshy_downloads/meshy71_repair_candidates/h3_orc/a-pose/mesh.glb`; the
matching Chieftain task produced
`artifacts/meshy_downloads/meshy71_repair_candidates/h3_orc_chieftain/a-pose/mesh.glb`.
Each candidate was bound through the existing registered-reference path and replayed at
`1800px` with the independently measured unit-local `+45` source-view diagnostic:

* Orc: `artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_apose_attack_plus45_hr_v2/`
* Chieftain: `artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_chieftain_apose_attack_plus45_hr_v2/`

Both A-pose binds reproduce their own rest vertices to floating-point error, but both
remain audit-negative. Orc's audit records an off-plate `LeftToeBase`, 25 escaped regions,
12 cohesion pairs opened past the review radius, a 17.0% bare-mesh outside-plate rate,
and 13,983 welded boundary edges. The Chieftain audit is likewise negative for off-plate
capture joints, escaped regions, cohesion/topology, and rest registration. The replay
comparison is useful for a more specific reason: changing the Meshy body pose variant
does not supply the authored attack weapon. The A-pose body has plausible neutral
equipment from the selected neutral upscale, but the attack plate's moving weapon is a
separate source element and is absent from the candidate body, so it cannot be accepted
as a body-weight fix or judged as a successful weapon attachment.

This is a negative for the narrow hypothesis "regenerate the body in A-pose and keep the
same weapon/ownership assumptions," not a universal rejection of Meshy or a claim that
the source track is wrong. The next professional route is an explicit prop-aware audit:
isolate the authored attack weapon from a sufficiently informative source view, generate
or recover a weapon candidate without contaminating it with hand/torso pixels, attach it
to the measured hand in the candidate rest frame, and then replay idle plus attack. No
queue promotion, active bind replacement, delivery artifact, installed payload, runtime
behavior, gameplay behavior, or final-quality claim is made.

### Follow-up checkpoint: the first Orc attack-axe prop candidate is contaminated

The prop-aware route was exercised once, not assumed complete. A source-conditioned
Meshy 7.1 prop task was submitted from the readable `g12_attack_front` frame crop after
confirming the axe's motion across all six attack frames. Task
`01a0c566-b0fe-71f0-b3e0-ce816ed9e7c7` completed as
`artifacts/meshy_downloads/meshy71_prop_candidates/h3_orc/attack_axe_source_conditioned_v1/mesh.glb`.
The input and its visible high-resolution source crop are retained beside the replay
diagnostics. This was deliberately a source-conditioned experiment, not an input
provenance claim for the neutral body mesh.

The 768px/Blender turntable shows a recognizable long axe-like span, but it also carries
a fused green hand/forearm-shaped mass at the grip. The geometry preflight reports one
welded non-manifold edge and one welded connected component before the diagnostic trim.
Removing faces touching the sampled green hand/body colors does not make a clean prop:
the v2 trim still has `262` welded boundary edges, one welded non-manifold edge, two
components, and a visible contaminated/ruptured grip in the retained turntable under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_attack_axe_trimmed_candidate_v2/`.

The prop candidate is therefore rejected before attachment. No attempt was made to hide
the contamination with a guessed hand offset, a wrong-side bone, or a partial mesh cut.
The active Orc/Chieftain body binds and queue registrations are unchanged. The next
repair requires either a cleaner multi-view weapon source or a deliberately authored
weapon mesh, followed by a bone-local attachment and idle/attack replay. This remains
generated-artifact evidence only; no candidate promotion, delivery, runtime, gameplay,
or final-quality claim is made.

A second bounded prop request used a stricter crop with the hand/body removed from the
visible input. Meshy task `01a0c571-bc1e-720a-ac03-a5f9952836a9` completed under
`artifacts/meshy_downloads/meshy71_prop_candidates/h3_orc/attack_axe_source_conditioned_v2/`.
This avoids the v1 hand contamination, but the 768px turntable shows a flat malformed
blade-like slab rather than a usable axe; its preflight reports `28` welded boundary
edges and `12` welded non-manifold edges. It is also rejected before attachment. The two
attempts together show that the available single-frame sprite crop is not a sufficient
3D prop source, so another blind Meshy crop is not the next action. The remaining route
is a cleaner multi-view source or deliberate authored prop geometry with explicit grip
and orientation evidence.

### Follow-up checkpoint: authored rigid prop separates attachment from weapon reconstruction

The deliberate authored route was exercised as a control, not as a replacement for the
missing source weapon. `tools/homm3_meshy_frame_pose/author_rigid_prop_diagnostic.py`
appends a small low-poly axe-like prop to the Orc A-pose bind, places its grip at the
measured `RightHand` head, and gives every prop vertex 100-percent ownership by that
hand. It writes a separate generated GLB and copied bind report; it does not modify the
active candidate, queue, or delivery exporter.

The positive control replays six `g12_attack_front` frames at 1800px with the accepted
unit-local `+45` source-view correction under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_apose_authored_axe_attack_plus45_hr_v1/`.
The prop remains rigidly attached to the hand through the attack and the replay retains
the expected rest identity (`3.39e-08` max rest vertex error and `1.11e-16` max joint
head error). This isolates a real attachment path from the contaminated Meshy prop
attempts, but it is only generated-artifact evidence and the bind audit remains false.

The control also falsifies a shortcut: a single forearm-to-hand axis sign is not the
weapon solution. The `+1` and `-1` axis variants both follow the hand, but neither
matches the sprite weapon direction for every attack frame. The minus variant is kept
under `artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_orc_apose_authored_axe_attack_plus45_hr_axis_minus_v1/`
as a unit-local negative. The source weapon needs a measured hand-local grip/orientation
per attack state, or a clean multi-view prop source; changing global left/right labels or
silently applying one axis sign would hide the actual mismatch. No prop is attached to a
delivery bind, no queue promotion was made, and no runtime/gameplay/final-quality claim
is made.

### Follow-up checkpoint: nested-pelvis sweep does not unlock a second batch silently

A static extractor-only sweep was run over every queue row whose prior candidate error was
`Could not find two UniRig leg roots`. The repaired rule does not silently turn the remaining
rows into candidates: Monk and Priest still fail the same topology check, while Dwarf Battlerager,
Efreet Sufi, Genie, Skeleton, and Vampire Lord now fail later at unit-specific arm-chain
selection. Lizard Assassin and Kobold Foreman are blocked by missing linked-master registration.
No rendering or queue promotion was performed from this sweep; these remain separate adapter or
source lanes rather than evidence for a global lateral correction.

### Follow-up checkpoint: Monk and Priest are not standard SmartRig bipeds

The next bounded pair, `h3_monk` and `h3_priest`, was run through the repaired
SmartRig route at preview scale `3`. Both refuse with `Could not find two UniRig leg roots`.
Inspection of the actual skin trees shows a single vertical chain ending at `Bone_001`, with
three short upper branches; there are no two bilateral downward limb chains to assign as legs.
This is a Meshy topology/body-plan negative, not evidence that the named left/right sides are
backwards. They remain unresolved and require a dedicated source or body-plan adapter; no
plausible-looking fallback bind was emitted.

### Follow-up checkpoint: Fury 8x replay confirms the wing failure is real

The full 50-joint Eagle adapter was replayed again from the saved capture at `3600px`
(8x preview scale), using the unit-local `+90` source-facing diagnostic. The retained
high-resolution evidence is under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_fury_eagle_full_replay_yaw90_8x/`;
the replay covers all `67` saved frames and reports rest-frame vertex error
`8.364749540756631e-16`.

The enlarged detail contact makes the failure unambiguous: the candidate bird body and
talons remain recognizable, but the wing chains collapse into a narrow/folded pose in
frames whose source wings are extended, and the lower-body/foot silhouette also drifts.
This is not a low-resolution reel artifact and still does not support a fleet-wide
left/right rename. The active Fury candidate remains `needs_geometry_work`; no delivery,
runtime, gameplay, or final-quality claim is made.

### Follow-up checkpoint: source-recovery batch pinned six new candidates

The previously provenance-gated source rows were advanced with explicitly recorded Meshy
7.1 tasks from their pinned source images: `h3_banshee`, `h3_genie_upg`, `h3_wight`,
`hota_cove_corsair`, `hota_cove_sorceress`, and `hota_cove_tidecaller`. All six tasks
completed and their candidates are retained under
`artifacts/meshy_downloads/meshy71_repair_candidates/<unit>/source/`, with task-backed
metadata and 4K PBR texture outputs. Geometry preflight was run before any binding:
the candidates report genuine welded openings/non-manifold defects, with Genie also
having six welded components and the two Cove candidates two components each. All six
therefore remain `needs_geometry_work`, not accepted meshes.

New `zzzz-meshy-source-recovery-review-v1/review.json` sidecars pin each task and
preflight while keeping the saved neutral payload's separate identity status unchanged.
The queue rebuild still reports `194` unresolved-provenance identity rows, `259`
unresolved repair rows, and the unresolved `261` versus `262` roster delta. These new
source candidates are generated-artifact inputs for the next owned-bind audit only; no
animation, delivery, installed, runtime, gameplay, or final-quality proof is claimed.

### Follow-up checkpoint: Banshee source candidate is geometry-negative at high resolution

The recovered Banshee candidate was bound against its existing 25-joint registered
reference and replayed on the seven-frame `g12_attack_front` clip at `1800px`. The bind
preserves rest identity to `3.13e-08` max vertex error, but its audit is false: the
captured lower-body pivots sit well outside their own plates. The retained bind report is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_banshee/meshy71-source-bind-attack-v1/bind_h3_banshee_source-recovery-attack.json`.

The high-resolution contact under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_banshee_source_recovery_attack_hr/`
also makes the animation defect clear. The regenerated skeleton reads as a plausible
Banshee at rest, but the attack frames lose the source's broad wing/robe sweep and do not
track the authored silhouette. This is a geometry/ownership negative, not a global
laterality signal. The candidate remains `needs_geometry_work`; no bind, queue row,
delivery artifact, runtime behavior, gameplay behavior, or final-quality claim is
promoted.

### Follow-up checkpoint: Wight source candidate is also a motion negative

The recovered Wight candidate was bound against the saved 25-joint reference and
replayed on seven `g12_attack_front` frames at `1800px`. Rest identity is preserved to
`3.79e-08` max vertex error, but the audit remains false. The retained bind report is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_wight/meshy71-source-bind-attack-v1/bind_h3_wight_source-recovery-attack.json`.

The high-resolution replay under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_wight_source_recovery_attack_hr/`
shows why the source regeneration is not enough: the neutral robe/body is recognizable,
but the attack's staff/weapon and robe sweep do not track the authored frames. This is
another unit-local geometry/ownership negative, not evidence of a wrong global side
mapping. The candidate remains `needs_geometry_work`; nothing was promoted to delivery
or runtime.

### Follow-up checkpoint: Cove Corsair source recovery is a viable baseline, not a repair

The new `hota_cove_corsair` source candidate was the first of the recovered Cove rows to
complete the exact saved-reference path. Its registered-reference bind reproduces rest
identity to `3.08e-08` max vertex error, but the audit is false because captured flesh
pivots, including the arms and lower body, sit outside their own plates. The bind report
is `artifacts/homm3_mesh_repair_fleet_v1/candidates/hota_cove_corsair/meshy71-source-bind-attack-v1/bind_hota_cove_corsair_source-recovery-attack.json`.

The `1800px` attack replay under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/hota_cove_corsair_source_recovery_attack_hr/`
is materially closer than the rejected body plans: the pirate body, clothing, and sword
read correctly. It still misses the authored arm/weapon sweep and lower-body
correspondence, so it is a useful geometry baseline rather than a finished repair. This
result does not support global left/right reassignment. The candidate remains
`needs_geometry_work`; no delivery or runtime artifact was promoted.

The separate `+180` unit-local presentation counterfactual under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/hota_cove_corsair_source_recovery_attack_yaw180_hr/`
reads rear-facing and is visibly worse than the accepted zero-offset presentation. Cove
therefore is not one of the backward-facing exceptions; its remaining mismatch is the
off-plate reference/ownership and weapon-motion contract.

### Follow-up checkpoint: Genie source candidate is rejected by exact-reference identity

The recovered `h3_genie_upg` candidate was tested against its saved registered reference
with the owned exact-bind path. The bind refused before emitting skin weights because the
extent fit required correction `2.4826`, outside the accepted band
`(0.213790, 0.641371)`. This is a fail-closed subject/adapter mismatch, not a reason to
force a bind, reuse a donor, or reinterpret left/right labels. No replay or promotion was
performed; the candidate remains a pinned generated source artifact with
`needs_geometry_work` and an adapter-identity blocker.

### Follow-up checkpoint: Cove Sorceress shares the exact-reference identity blocker

The recovered `hota_cove_sorceress` candidate was tested against the saved registered
reference before any skinning edit. Exact binding refused with an extent correction of
`1.8627`, outside the accepted band `(0.278195, 0.834584)`. This is a fail-closed
subject/adapter mismatch, not a backward-facing presentation result and not evidence for
renaming left/right joints. No replay or promotion was performed; the source candidate
remains generated-artifact evidence with `needs_geometry_work`.

### Follow-up checkpoint: Cove Tidecaller has the same identity refusal

The recovered `hota_cove_tidecaller` candidate was tested against the saved registered
reference before any skinning edit. Exact binding refused with an extent correction of
`1.8187`, outside the accepted band `(0.275980, 0.827939)`. This is the same
fail-closed subject/adapter mismatch seen on Sorceress. No replay or promotion was
performed, and no left/right reinterpretation was introduced.

### Follow-up checkpoint: shared side-chain fix validated on Battle Mage at high resolution

The corrected `h3_battle_mage` side-chain candidate was replayed from its saved fitted
bind and retargeted motion at true 3x preview scale under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_battle_mage_sidechain_fix_3x/yaw000/`.
The replay covers `85` saved frames and includes idle, movement, attack, shoot, and
death keyframes. The wizard remains coherent through the sampled poses, and the arm
chains stay on the visible body rather than taking the old lateral accessory branch.
Together with the Guardsman 4x replay, this is evidence that the shared adapter fix is
joint-local and reusable for this matching biped group; it is not evidence for a
fleet-wide Left/Right rename.

The candidate remains `candidate_reviewed`, not final-quality: staff, robe, beard,
pouch, and accessory ownership/contact are still unresolved, and this replay is
generated-artifact evidence rather than delivery or runtime proof. The high-resolution
paths are now recorded in both unit review sidecars so the queue/ledger retain the
actual evidence used for this checkpoint.

The same high-resolution pass was then applied to the matching `h3_mage` candidate at
3x under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_mage_sidechain_fix_3x/yaw000/`.
All `85` saved frames rendered successfully. Its arms remain attached through idle,
movement, attack, shoot, and death, while the staff and robe remain visibly source-owned
and outside the side-chain acceptance claim. This extends the shared-adapter evidence to
three ordinary biped candidates (`h3_guardsman`, `h3_battle_mage`, and `h3_mage`) and
keeps the separate `h3_gremlin` 41.472x cloth/deformation failure rejected rather than
misclassified as laterality. No delivery or runtime status changed.

### Follow-up checkpoint: Guardsman side-chain repair survives high-resolution replay

The existing corrected `h3_guardsman` side-chain candidate was replayed at true 4x
preview scale from its saved fitted bind and retargeted motion under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_guardsman_sidechain_fix_4x/yaw000/`.
The retained keyframe sheet and reel cover the saved idle, movement, attack, and death
samples. At this resolution the corrected arm chains remain attached to the armored
shoulders and do not reproduce the prior lateral-accessory branch twist visible in the
original `biped-fit-v1` keyframes. The old and corrected candidates therefore provide
direct evidence for a joint-local adapter-selection defect, not a global Left/Right
rename.

This is still an experimental candidate: the replay is mesh-only rather than a new
source-plate overlay, and sword, shield, cape, and equipment ownership/contact remain
unresolved. The corrected bind is not promoted to delivery, runtime, gameplay, or
final-quality acceptance. The diagnostic command was intentionally stopped after the
zero-offset pass; the 180-degree presentation was not needed for this side-chain
comparison and would not be an acceptance view.

### Follow-up checkpoint: Sorceress registered-scale recovery remains a geometry negative

The `hota_cove_sorceress` Meshy 7.1 source candidate was rerun with the registration's
own scale rather than the default extent-derived scale. This intentionally tests whether
the earlier correction refusal was only a scale-policy issue. The bind emitted a
candidate and the preview completed, but the result is not a repair: the 12,524-vertex
candidate has `31.7%` of its bind-pose vertices outside the saved DEF plates, `93`
escaping regions, `980` edges past the review stretch limit, and a worst edge stretch of
`71.1901x`. The ten-frame 1800px plate sheet at
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/hota_cove_sorceress_registered_scale_attack_hr/g12_attack_front_sheet.png`
shows the candidate mostly offset from the drawn art rather than merely facing the
wrong way.

This is generated-artifact evidence only. Registered scale removes the extent refusal;
it does not establish source identity, correct ownership, or a laterality fix. The
candidate remains `needs_geometry_work`, and the next action is to resolve the
Sorceress source/reference identity or provide a dedicated matching adapter. The bind
report now records the explicit candidate mesh as `reference.mesh` and preserves the
registration asset as `reference.registrationMesh`, so this negative cannot be mistaken
for a preview of the wrong surface.

### Follow-up checkpoint: Automaton replay is readable at 1800px but remains unaccepted

The existing `h3_automaton_upg_alt` fixed-camera bind replay was rerendered with the
documented source-space renderer at true `1800px` (`preview-scale 4`) under
`artifacts/homm3_mesh_repair_fleet_v1/adapter-replays/h3_automaton_upg_alt/remaining-forced-mixamo-person-existing-bind-4x-v1/`.
All `81` frames rendered after explicitly accepting the known transparent terminal death
frame `000080.png` with `HOMM3_ACCEPT_EMPTY_ALPHA=1`; the replay remains rest-exact at
`7.77e-16`.

The larger contact sheet makes the distinction clearer: the broad automaton body remains
readable, but hard-surface seams, leg/contact ownership, and the unit-local source/camera
correspondence are still unresolved. It does not show a fleet-wide left/right inversion,
and higher resolution does not promote the existing adapter replay to final quality. The
unit remains `candidate_reviewed` and generated-artifact-only; the queue and review
sidecar now point at the 1800px detail reel as the current visual evidence.

### Follow-up checkpoint: three wrong-source inventory rows now select verified replacements

The three previously confirmed wrong-source rows were corrected at the inventory producer
rather than merely relabeled in the queue. `audit_homm3_mesh_coverage.py` now selects the
task-backed Meshy 7.1 source candidates for `h3_mechanic_upg_alt`, `h3_paokai`, and
`h3_pegasus` only when their retained `source.png` hash matches the selected AAA upscale and
their task metadata is `SUCCEEDED`. The old snake-statue, cartoon-bear, and bear-like demo
meshes remain present as explicit quarantine evidence; none is treated as canonical coverage.

The queue identity rows now report `verified_correct` for all three, with
`meshy7_generated_mesh_replacement` and `verified_source_candidate` inventory markers. This
corrects source identity only. The mechanic remains a reviewed saved-motion candidate, while
Paokai remains geometry-blocked and Pegasus remains mounted-adapter-blocked; no rigging,
animation, delivery, runtime, gameplay, or final-quality claim is implied by the inventory
promotion.

The rebuilt ledger now reports `68` identity-verified rows, `0` confirmed-wrong-source rows,
`194` unresolved-provenance rows, `181` reviewed animation candidates, `78` reviewed
adapter-evidence rows, and `259` unresolved repair rows. The `261` versus `262` roster
membership ambiguity remains open, so this is a source-identity checkpoint rather than fleet
completion. The three repaired rows above do not close the neutral upscale gap: the neutral
catalog's current coverage inputs still include the 13 lower-resolution leads listed in the
first-priority audit section, and their exact Meshy task inputs and source-image suitability must
be reverified before those rows can be called fixed.

### Follow-up checkpoint: Paokai ownership counterfactuals remain a dragon-specific negative

The Paokai ownership diagnostic now emits hash-bound region sidecars for each counterfactual
GLB, allowing the normal saved-bind renderer to replay the variants instead of stopping at
768px diagnostic output. The current, region-restricted, and region-rigid variants were
rerendered at true `1800px` across all `70` saved frames under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_paokai_region_counterfactual/`.
Each replay is rest-exact within `2.61e-14` vertex error.

The high-resolution comparison does not support a production ownership change. Region
restriction lowers the all-frame worst stretch from `120.67x` to `104.76x` and the
AttackFront worst from `94.11x` to `53.49x`, but worsens all-frame p95 from `1.577x` to
`1.874x` and AttackFront p95 from `1.649x` to `2.039x`. The attack and death panels still
show the compact wing/body correspondence failure and introduce more hard-edged region
boundaries. Region-rigid ownership is visibly worse and measures `4.203x` all-frame p95
with `140.33x` worst stretch. It is rejected rather than promoted.

The side-by-side replay keeps the unit's recorded presentation, including its per-unit
orientation, and does not expose a uniform left/right inversion. The remaining Paokai
failure is therefore still dragon-specific geometry, registration, and ownership
correspondence, not evidence for a fleet-wide side rename. The review is recorded in
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_paokai/zzzzzz-paokai-wing-body-counterfactual-review-v1/review.json`.

This is generated-artifact diagnostic evidence only. Paokai remains `needs_geometry_work`,
and the next productive lane is a dragon-specific geometry/registration or clean-source
investigation. No delivery, runtime, gameplay, or final-quality status changed.

### Follow-up checkpoint: Green Dragon ownership counterfactual also remains negative

The same ownership diagnostic was applied to the existing `h3_green_dragon` eagle-flyer
candidate. Current and region-restricted binds were replayed through the standard renderer
at true `1800px` across all `59` saved frames under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_green_dragon_region_counterfactual/`.
Both are rest-exact within `3.95e-15` vertex error.

The larger defence panels make the unit-local problem clearer: the authored source is a
long side-profile dragon, while the candidate reads as a compact front-biased body with
wing/body and lower-chain correspondence loss. Region restriction changes the wing planes
but does not restore the source silhouette or motion correspondence. The rigid diagnostic
was rejected fail-closed by the normal renderer because its initial weights leave the
sidecar candidate support; the renderer contract was not weakened to force a preview.

The recorded per-unit presentation was preserved rather than globally mirroring the source
or mesh. This does not establish a uniform left/right joint inversion. The active review is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_green_dragon/zzzzzz-green-dragon-ownership-counterfactual-review-v1/review.json`.
Green Dragon remains `needs_geometry_work`; this is generated-artifact evidence only, with
no delivery, runtime, gameplay, or final-quality promotion.

### Follow-up checkpoint: Green Dragon source regeneration is bind/export-negative

With Meshy generation explicitly approved, a new source-derived Green Dragon candidate was
requested from `artifacts/creature_aaa_3d_upscale/h3_green_dragon.png` using task
`01a0c631-f4bc-77a8-8236-0e6a0383bed0`. The task completed, but the owned exact-bind gate
does not accept the result. The registered-scale audit covers eight idle frames and reports
`59.8%` of vertices outside the bind plate, `8,077` edges past the review stretch limit,
`57.7432x` worst edge stretch, and `2.4751%` maximum escaped vertices. The candidate's
rest identity error is also `0.011683`, so it is not a clean source replacement.

The exported 50-joint bind was then sent through the normal exact-reference preview. The
preview refused it because the owned-bind placement pass deliberately depth-shifted
`BN_Wing_L_04` by `0.07597`, so the emitted bind no longer preserves the fitted reference
rest pose at that joint. This is a fail-closed rest-identity and joint-placement blocker,
not evidence of a GLB serialization bug; the renderer contract was not weakened and no
unsupported replay was made visible. The superseding review is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_green_dragon/zzzzzzz-green-dragon-meshy-source-bind-review-v1/review.json`.

This source regeneration therefore remains `needs_geometry_work`. It provides a concrete
next engineering target, namely the Green Dragon 50-joint adapter/export contract or a
dedicated dragon registration, and does not support a global left/right rename or any
delivery, runtime, gameplay, or final-quality claim.

### Follow-up checkpoint: Dragon Fly source regeneration confirms the serpentine adapter blocker

The same explicitly approved Meshy source lane was run for `h3_dragon_fly` using task
`01a0c639-2e0b-70d7-8153-7efe701ce0ee`. The source candidate completed, but the registered-
scale owned-bind audit is structurally negative: `62.1%` of vertices begin outside the
bind plate, the audit reaches `29.1297%` escaped vertices, `2,982` edges pass the review
stretch limit, the worst edge reaches `37.4975x`, and the reference's median bone-length
excursion is `35.9%`.

The exact-reference preview also refused the exported 50-joint bind because the owned-bind
placement pass depth-shifted `Hips` by `0.02009`, with smaller shifts on `BN_Wing_L_05` and
`BN_Wing_L_06`, so the emitted bind fails the fitted rest-identity gate. This is consistent
with the prior Dragon Fly review: a serpentine wing/tail body plan needs its own registration
and joint-placement contract, not a relaxed exporter check. The superseding review is
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_dragon_fly/zzzzzzz-dragon-fly-meshy-source-bind-review-v1/review.json`.

Dragon Fly remains `needs_geometry_work`. The candidate is retained as generated evidence only;
no generic flyer promotion, global left/right change, delivery, runtime, gameplay, or
final-quality claim is made.

### Follow-up checkpoint: Green Dragon source refit is a high-resolution deformation negative

The fresh source-derived Green Dragon Meshy surface was re-registered against its own saved
idle frame and Eagle capture with the existing `idle0_bind_first_inside_mesh` route, then
refit with a new skin-weight field for the new vertex set. This removes the stale old-mesh
weight-field mismatch rather than reusing weights from the prior SmartRig surface. The skin
fit itself rejects the candidate with `holdoutIouImprovement=0.05586`, `cameraIoU=0.801996`,
and disposition `rejected_generalization_or_deformation_gate`.

The resulting bounded key-frame replay was rendered at true `1800px` under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_green_dragon_meshy_source_bindfirst_keyframes_1800_v1/`;
the rest-only comparison is under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_green_dragon_meshy_source_bindfirst_rest_1800_v1/`.
The rest surface is coherent, but its presentation is compact and front-biased against the
long side-profile source plate. Under motion, the wing, crest, and lower-chain regions
separate visibly, confirming a dragon-specific ownership/adapter deformation failure rather
than a low-resolution diagnostic artifact. This is not evidence for a global left/right
rename; the sprite-to-mesh facing difference is retained as unit-local orientation evidence.

The review is recorded in
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_green_dragon/zzzzzzzz-green-dragon-meshy-source-skin-fit-review-v1/review.json`.
Green Dragon remains `needs_geometry_work`; no delivery, runtime, gameplay, or final-quality
promotion is made.

The same candidate's bilateral audit reports `13,252 / 42,020` vertices with at least `0.1`
weight on both named side families; the right-wing region has only `0.517` mean own-side mass
and `0.267` mean opposite-side mass. A diagnostic swap of the named left/right weight columns
was rendered at `1800px` under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_green_dragon_meshy_source_bindfirst_lr_swap_keyframes_1800_v1/`.
It makes the deformation visibly worse, so the repeated twist is actionable local ownership
evidence but not a global side-binding fix. The next adapter must identify the dragon's wing
and lower-chain ownership per region, while preserving the unit-local source orientation.

### Follow-up checkpoint: Dragon Fly fresh registration confirms a second body-plan negative

The same no-recapture experiment was applied to the new `h3_dragon_fly` Meshy source. The
fresh bind-first registration completed, but the normal camera registration gate refused it
at `0.301499 IoU` against the required `0.48`. A separate diagnostic-only fit at the
explicitly recorded `0.25` threshold was allowed only to obtain a readable failure view; it
still rejected itself with `holdoutIouImprovement=0.03005` and
`rejected_generalization_or_deformation_gate`.

The rest and bounded saved-motion comparisons are retained at true `1800px` under
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_dragon_fly_meshy_source_bindfirst_rest_1800_v1/`
and
`artifacts/homm3_mesh_repair_fleet_v1/diagnostics/h3_dragon_fly_meshy_source_bindfirst_camera025_keyframes_1800_v1/`.
They show a coherent generated serpentine surface at rest but a compact twisted stack under
motion, not a low-resolution artifact. The bilateral audit finds only `2,535 / 35,149`
vertices with substantial mass on both side families, while the wing regions retain `0.946`
and `0.835` mean own-side mass, so this second representative also does not support a global
left/right swap.

The review is recorded in
`artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_dragon_fly/zzzzzzzz-dragon-fly-meshy-source-skin-fit-review-v1/review.json`.
Dragon Fly remains `needs_geometry_work`; the diagnostic threshold is not an acceptance gate,
and no delivery, runtime, gameplay, or final-quality promotion is made.

### Follow-up checkpoint: nested SmartRig pelvis selection removes a false root-side diagnosis

The shared SmartRig biped adapter was extended to handle Meshy exports that insert pelvis/helper
nodes below the skin root. The old rule treated the first root child as Hips; on several units
that made a torso or accessory branch compete with one real leg and could present as a laterality
or twisting failure. The new rule evaluates complete trunk paths and bilateral downward branch
spread, keeps the trunk-shape veto, and remains fail-closed. It does not rename or swap global
Left/Right columns. The focused adapter suite now passes `5/5`, including explicit coverage for
`h3_walking_dead`, `h3_power_lich`, and `h3_snow_elf_upg_alt` nested-pelvis layouts.

The bounded high-resolution review was then run on Power Lich and Snow Elf with saved motion,
using preview scale `3` for rest/keyframe overlays and scale `2` for the full replay. The outputs
are retained under:

- `artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_power_lich/biped-fit-v1/`
- `artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_snow_elf_upg_alt/biped-fit-v1/`

Both now produce an experimental candidate instead of the previous topology exception. The
readable replays still show unit-local deformation: Power Lich's robe and attached prop regions
separate under motion, while Snow Elf remains compact/floating with unreliable prop/cloth
tracking. These are not final-quality repairs and are not explained by the old low-resolution
GIFs alone. Their review sidecars are:

- `artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_power_lich/zzzzzzzz-power-lich-nested-pelvis-review-v1/review.json`
- `artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_snow_elf_upg_alt/zzzzzzzz-snow-elf-nested-pelvis-review-v1/review.json`

Walking Dead now reaches the adapter but is refused by the downstream rest-fit contract because
its registered reference toes point along the hip-to-hip axis. That is a source/reference
orientation failure, not evidence for a global side swap. The roster remains incomplete and the
fleet remains candidate/review work only; no delivery, runtime, gameplay, or final-quality claim
is made.

### Follow-up checkpoint: skin-graph trunk selection unlocks Horned Demon

The SmartRig adapter now evaluates short simple paths over the skin graph, not only directed child
links, while leg roots remain directed from the selected pelvis. This recovers h3_horned_demon's
reversed trunk segment after the earlier arm-chain refusal. The focused SmartRig suite passes `6/6`.
High-resolution rest/keyframe review at scale `3` and a full saved-motion replay at scale `2` are
retained under `artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_horned_demon/meshy-fit-tpose-v1/`.
The candidate is recorded as `candidate_reviewed` only: the rest and keyframes are recognizable and
do not show a persistent whole-asset twist, but crouched proportions, hands/feet, prop/contact
ownership, and bilateral ownership have not been accepted for delivery. The replay uses this unit's
local Meshy orientation; no mirror was applied to match other units.

The same graph route statically unlocks h3_dwarf_battlerager, h3_genie, and h3_gremlin_upg, but
those rows still fail their registered reference toe-axis gate, so no generic replay was promoted
for them. This is source/reference orientation evidence, not justification for a global Left/Right
swap. The roster remains incomplete and the fleet remains candidate/review work only; no delivery,
runtime, gameplay, or final-quality claim is made.

### Follow-up checkpoint: arm endpoint laterality unlocks Skeleton but exposes geometry failure

The SmartRig arm selector now classifies a candidate by the endpoint of its four-joint path when
the exported shoulder helpers sit near the torso centerline. This unlocks h3_skeleton without a
global Left/Right swap; the focused SmartRig suite passes `7/7`. Its scale-3 rest overlay is
structurally coherent, and a full scale-2 saved-motion replay completed for all `67` frames.
The replay is retained under `artifacts/homm3_mesh_repair_fleet_v1/candidates/h3_skeleton/biped-fit-v1/`.
It is recorded as `needs_geometry_work`: the high-resolution keyframes show severe lower-body and
weapon/attached-region separation and stretched sheets, so this is not a final repair or a twisting
fix. The unit-local orientation was preserved; no mirror or global side remap was applied.

The remaining efreet, Genie Vizier, Gorgon, and Vampire Lord rows still refuse the common biped
adapter at their elevated-arm topology gate, while Monk and Priest do not expose two leg chains.
Those remain source/topology negatives rather than reasons to relax the fail-closed adapter globally.
The roster remains incomplete and the fleet remains candidate/review work only; no delivery, runtime,
gameplay, or final-quality claim is made.

### Follow-up checkpoint: three additional graph-route candidates survive high-resolution replay

The static sweep after the graph and arm-endpoint fixes unlocked h3_grand_elf, h3_lich, and
h3_ogre_mage without a global side remap. Each was reviewed at scale `3` for rest/keyframe fit and
replayed at scale `2` through the complete saved motion set:

- h3_grand_elf: `79` frames, recognizable bow-user motion, no persistent whole-asset twist visible;
  retained as `candidate_reviewed`.
- h3_lich: `80` frames, recognizable staff-user motion, no persistent whole-asset twist visible;
  retained as `candidate_reviewed`, with staff/skirt ownership still unvalidated.
- h3_ogre_mage: `64` frames, recognizable bat-user motion, no persistent whole-asset twist visible;
  retained as `candidate_reviewed`.

Their high-resolution outputs and review sidecars are retained under the corresponding
`artifacts/homm3_mesh_repair_fleet_v1/candidates/<unit>/biped-fit-v1/` directories. These are still
generated candidates only: prop/contact ownership, bilateral weight mixing, installed payload, and
game-visible behavior remain unproven. Mesh orientation was handled per unit; no fleet-wide mirror
was applied. The roster remains incomplete and the fleet remains candidate/review work only; no
delivery, runtime, gameplay, or final-quality claim is made.

### Follow-up checkpoint: Grand Elf 4x inspection separates display limits from repair evidence

Because the wide Grand Elf contact sheet is resized substantially in the chat window, h3_grand_elf was
re-rendered at preview scale `4` for both the front/side rest/keyframe view and the complete `79`-frame
saved-motion replay. The resulting detail sheet is `6605x1780`; it is still too wide to judge reliably as
a single chat image. Individual approximately `1321x1780` panel crops were inspected instead. They keep
the body recognizable through idle, move, attack, shot, and death and do not establish a persistent global
side reversal. They do show local neck/chest gaps, intersecting bow/arm/torso surfaces, dangling lower-body
geometry, and unresolved prop/contact defects. That is not a clean bill of health: bilateral ownership
remains unaudited, and the candidate stays `candidate_reviewed`, not final-quality or delivery-ready.

This confirms the display concern without conflating it with deformation: chat downscaling does not twist
the mesh, but the contact sheet is not an adequate acceptance surface. The high-resolution panel evidence
is retained in the candidate directory and recorded in the Grand Elf review sidecar. No global Left/Right
swap or fleet-wide mirror is justified by this inspection.
