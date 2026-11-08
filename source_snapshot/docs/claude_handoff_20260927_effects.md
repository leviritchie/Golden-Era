# Claude session handoff: native-style unit effects (2026-09-27)

Status: reconstruction and source/artifact audit, not a new game test. The primary
record is Claude subagent `agent-a2dcbbe29d0bb96cb.jsonl` under
`C:/Users/<user>/.claude/projects/V--Games-Olden-Era-Playtest-Tweak/aeba9e69-0217-4c63-98f4-71a64ce15d89/subagents/`
(`E:` below means its zero-based JSONL record). The preceding pilot is
`agent-a994dbb712c9a4a51.jsonl` (`P:`). Reconcile transcript claims with the
current worktree before reuse; the active details live in
`docs/homm3_vanilla_style_effects_rollout.md` and
`docs/olden_era_vanilla_vfx_style.md`.

## Decision and method

- User decision, relayed in E:0: all HoMM3-derived effects looked bad in the
  actual engine. Replace every `defFlipbook` unit-look layer. HoMM3 DEF groups,
  frames, anatomy, and timing say **what** to depict and **when**; their pixels
  do not appear in the replacement. The pilot's fire/storm conversion was not
  a blanket visual acceptance of the other units (P:0 and P:final).
- Extend `tools/homm3_vfx/vanilla_style_fx.py`, its `vanilla_style/` specs, and
  `Homm3MeshFx`, not a second effect runtime. Inventory every look spec first,
  then design same-kind donor subtrees per unit. Store not-yet-selected specs in
  `vanilla_style/drafts/`; compile only a promoted spec under `units/`. The
  delivery row selects `vfxAuthority: vanilla_style`, `vanillaStyleSpec`, and
  `albedo: basecolor`; its old UV atlas, quads, and effect lights must not ship.
  Do not rerun motion or `look.py` merely to switch effect authority.
- Vanilla research is asset/decomp evidence, not gameplay proof: Olden Era uses
  Shuriken particle hierarchies, mesh/trail renderers, bone-parented idle roots,
  Timeline attack/impact effects, native materials/shaders, and HDR emission
  under Hex/Lit and battle bloom. The runtime loads exact native resPaths
  through `ResManager.Get` in LateUpdate, then clones a selected subtree onto
  the owned rig; never synthesize a ripped-pixel quad. Native `Hex/Lit` material
  sheets should be cloned from a real donor rather than assembled from an
  incomplete carrier. A body overlay follows vanilla
  `BhBattleTimelineHelper.AppendMaterial`, while steady glow belongs to an
  emission map; dynamic lights are not a second steady-glow path. Kept source
  nodes that contain a `Light` must leave that GameObject inactive.
- Each layer is checked against a probed source resPath/childPath, exact
  superseded layer IDs, available bones, and DEF-to-stock clip windows. Same-
  named prefab children need an explicit `firstOfDuplicates` pin because
  `Transform.Find` picks the first serialized sibling. Per-unit source hashes
  avoid invalidating unrelated compiled rows. Review OLD | NEW | VANILLA
  sheets in the Hex/Lit-faithful lab, not a flat preview. The lab uses replica
  shaders and Python bloom, so a good sheet is **lab-render**, not runtime or
  user-visible gameplay proof.

## Completed and rejected work

- The inventory in `docs/homm3_vanilla_style_effects_rollout.md` counted 102
  unit look specs with 188 `defFlipbook` layers (E:666); it records the clip,
  DEF frames, bone, depiction, selection, and status. The committed Castle
  drafts cover nine units: monk/priest/zealot, angel/archangel/seraph, and
  griffin/royal/battle griffin. All nine have `sheet_*.png`, `hero.png`,
  `idle.png`, and `compare.mp4` under
  `artifacts/vanilla_vfx_style/lab/<unit>/` (E:739; current files checked).
  These are lab-tier drafts, not promoted Castle delivery rows.
- Monk line: the Angel target-impact burst on the caster's hand overwhelmed
  the body, so the draft uses vanilla Lightweaver hand gather/release particles
  instead. `Unit_ShootFront` was once unreachable through the stock controller
  (E:413), but fleet commit `fd25e047ca` maps new ranged deliveries to
  `15.Skill_1`; do not perpetuate the old no-shoot conclusion. The monk-line
  promotion dry run later resolved those windows (E:1779).
- Angel: an early cone used the vanilla spear axis and streaked away from the
  HoMM3 sword; its orange-red also read as fire. `alignToReach` rotates the
  native Angel close-hit spear strike onto the skinned RightHand reach so the
  gold-white burst follows the blade. Archangel and seraph retain the DEF's
  orange-gold flaming-sword color. Phoenix wing fire was tried at the grip,
  then aligned/recolored/thinned, but still formed a red column beside the
  body; both now use the Angel strike along the blade. Griffin hit/death
  effects use the first vanilla griffin feather subtree with the lab's
  approximate Disappearance shader. These choices and rejected trials are
  visible in E:1779 and the Castle lab table in the rollout doc.
- The nine Castle drafts passed the freeze/promotion dry run in Claude's
  session (E:979, E:1779), with `h3_griffin` requiring a new delivery row.
  The user had not judged these nine in game. The Castle selection still names
  `unit_look` for them, and the base griffin remains a separate motion/build
  issue; effect readiness cannot be used to claim that mesh complaint solved.
- Commits `81f306225b` (inventory/drafts/lab), `bf11ffdb36` (freeze/gate),
  `c7bce6b3cf` (Angel retune/promotion), `961aab1848` (final Angel line,
  body lanes, bake and validators), and `0b83bd7c7a` (doc correction) are the
  relevant scoped milestones. E:1779 reports an OfficialDeobf build with
  `ValidatePluginLiveInteropRefs` new=0 for the body lanes. This is build
  target proof only; the plugin was neither deployed nor exercised in game
  for these lanes.

## Current faction order and evidence

| Batch | Current evidence | Remaining boundary |
|---|---|---|
| Castle | Nine draft specs and nine lab comparisons; promotion dry run reported 9/9. The native griffin feathers and Angel/Lightweaver donors are selected. | Re-run dry run on current frozen inputs; promote/freeze without motion rebuild, then test in game before visual acceptance. `h3_griffin` needs a row. |
| Conflux | Fire and storm have shipped *source* specs and a `conflux_vanilla_style_slice_v1.json` selection. The other 12 of the 14-unit roster have no effects drafts. E:989-1105 surveyed native body shader/material evidence and found only the two delivery rows. | Use Conflux as the richer template after Castle, with native elemental donors and a Hex/Lit-faithful lab beside a vanilla elemental. No broad faction rollout from the prior two-unit pilot. |
| Stronghold | Inventory identifies roc feather hit/death, thunderbird beak bolt plus feathers, and shahrokh wing/body crackle plus feathers. No native-style drafts or lab sheets exist for these three. | After the Conflux method is judged, start with roc/thunderbird/shahrokh. Stronghold faction rollout testing stays held until effects are part of its delivery. |

The material exploration found Hex/Lit FLAG displacement reads `COLOR.r`, so
`displacement_mask_bake.py` can stamp a localized mask into GLB `COLOR_0.r`;
the plugin refuses a mesh without colors. It is a bounded body-wave option,
**not** proof that any Conflux unit should use it. The overlay lane appends a
probed native material to the body's skinned renderer. Both have source/build
evidence only. A body wave must not be selected until the ship step delivers
the stamped GLB with a source-hash check. The lab has not rendered either lane
(E:1779); `magic/Fresnel` and `magic/test/DepthTexture` were missing in the
existing lab. Claude began a DXBC-grounded Fresnel replica but stopped before
wiring or verifying it (E:1785-1893).

## Reconciliation at takeover

- `tools/homm3_vfx/validate_no_def_flipbook.py` is **already wired** into the
  OfflineUnlockMod build, despite the rollout doc still calling the gate and
  `freeze_slice.py` reverse behavior "proposed." Its current read-only result
  is `debt=18/18 selectedUnitsWithFlipbooks=21`; debt entries must be removed
  and the ceiling lowered as selections change. `freeze_slice.py` in
  `tools/homm3_def_retarget_delivery/` already emits vanilla-style rows under
  commit `bf11ffdb36`. Update the stale rollout prose when the next changes
  are validated; do not implement a duplicate gate.
- `ship_def_retarget_slice.py` has no `displacementMaskGlb` delivery section.
  `vanilla_style_fx.py` additionally points `SHIP_STEP` to nonexistent
  `tools/homm3_def_retarget/ship_def_retarget_slice.py` instead of the real
  `tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py`. Fix the path,
  then retain a fail-closed end-to-end marker check until shipping is real.
- At takeover, `vanilla_style_fx.py`, `promote_vanilla_style.py`, and
  `vanilla_ps_recipe.py` contain uncommitted interrupted work: draft-only
  pending-lane handling and extraction of renderer `meshMaterials` for lab
  overlays. `unity/Homm3VfxFresnelReplica.shader` is untracked. None has been
  validated or committed. The shared `homm3_mesh_fx/catalog.json` is also
  marked dirty, with no substantive `git diff` observed; preserve it and do
  not normalize its line endings as collateral cleanup.
- No displacement bake artifact exists under
  `artifacts/vanilla_vfx_style/displacement/`. This is consistent with no
  selected `bodyDisplacement` spec, not a failed runtime observation. Historical
  scratch paths under `F:/claude_scratch/vfx_rollout/` are not a directive for
  new routine work; use V: scratch. Claude reported pruning 2.17 GB of old
  raw lab frames (E:634) and about 113 MB later (E:1779), not newly verified
  free space.

## Next bounded milestone

1. Correct the `SHIP_STEP` path and check it through the existing effects
   validator. Preserve the fail-closed refusal for a shipped body wave until
   the fleet-owned ship section verifies `sourceGlbSha256` against the frozen
   row's `idleRetimedGlbSha256`, delivers the color-stamped GLB, and pins its
   SHA. Coordinate before editing the shared ship script.
2. Re-run all nine Castle promotion dry runs against current frozen inputs;
   record failures rather than weakening the checks. Do not move drafts,
   compile the shared catalog, freeze, build, or deploy during this diagnostic
   step. The coordinator owns any subsequent selection/payload change.
3. Build one Conflux donor-backed template in `vanilla_style/drafts/`, then
   judge a Hex/Lit lab comparison when the Unity lock is free. Keep body wave
   and material overlay as explicit, evidence-backed options, not generic
   fallback effects. Only after that template has been judged should the
   remaining Conflux units and then Stronghold be designed.

Any Blender/Unity run must wait for the game, confirm at least 20 GB free on
V:, run `memgate.py --wait 30`, recheck the game, and use `unitylock.py` for
Unity. Do not launch, stop, or kill the game to make the lab run. Lab/render,
build, installed bytes, runtime behavior, and user-visible gameplay are
different proof tiers.

## Current execution checkpoint

After this reconstruction, the `SHIP_STEP` path was corrected to the real
delivery script and an existence check added to the existing build-wired
`validate_homm3_vanilla_style_fx_contract.py`. That validator passed with the
three currently compiled units. The nine Castle promotion dry runs were then
repeated against current live and frozen manifests: `9 ok, 0 failed`.
Eight units resolved 3-7 planned catalog rows apiece; `h3_griffin` passed the
live-look freeze check but has no Castle selection row, so its plan was
correctly skipped until freeze adds it. This is source/generated-artifact
verification only. No draft moved, shared catalog rewritten, build, freeze,
deploy, Unity run, or game test was performed in this checkpoint.

The first bounded Conflux template is now a **lab-only**
`vanilla_style/drafts/h3_water_elemental.json`. It names all three retired
look layers: stepped body-flow atlas, DEF-pixel attack splash, and its fitted
light. The first donor choice, `magic/prefabs_vfx/nature/aqualotl/naiad_upg_impact_unit`,
was rejected before lab judgment: it is a target impact, not an attached
water-elemental body or self-hit effect, repeating the Castle monk's
target-on-caster mistake. The current draft instead pins the installed
`units/nature/1prefabs/aqualotl_upg` prefab's own idle water children and
`Naiad_upg_hit_root/Water_01` self-hit burst. That prefab was added as one
new source to `vanilla_sources.json`; the eight prior source records did not
change. The localized Hex/Lit FLAG ripple is explicitly
pending the ship step's `COLOR_0` mask delivery. `check-drafts` passes for all
ten drafts, while water `plan`, promotion dry run, and shipped-mode validation
all refuse the missing delivery lane. The existing build-wired effects
validator checks that pending drafts remain refused by those three
boundaries. An explicit ship hold prevents a source-marker string alone from
unlocking displacement; clearing it requires a candidate ship and readback
proof in the gate. The validator also refuses mixed mask-rule keys, unknown
displacement-layer keys, bool/non-finite numbers, and a zero wave direction.
This is static/source proof, not a visual verdict.
The rejected target-impact source recipe extracted with no unsupported
ParticleSystem modules; that did not make it a suitable caster donor. The
in-unit source was subsequently extracted through its full direct-child
path, and the lab's restricted water material and masked FLAG support were
added before visual comparison. No runtime-payload acceptance follows from
the draft or the lab.

The independent shader read pinned the installed `magic/Water_fire_stylized`
no-fog pass (PS program 14), its four bound textures, particle vertex-stream
layout, alpha mask and world-height branch, and the two selected Aqualotl
material variants; the reproduction and limitations are recorded in
`artifacts/claude_takeover_20260927/water_shader/RESEARCH.md`. A lab-only
restricted replica now refuses every other
`Water_fire_stylized` material instead of drawing a flat substitute; its
property-to-register map and Custom1 packing are still static inferences.
The Hex/Lit lab shader has the source FLAG equation gated to a baked
`COLOR_0.r` mask. Python source preflight resolved six selected native water
systems from full-path recipes, baked/read back a localized 16,348-vertex
water-elemental mask (mean 0.10648, max 1.0), and derived emission coverage
0.0914 (mean 0.0389). Two guarded OLD | NEW | selected-VANILLA lab runs then
tested the visual placement; neither is game/runtime proof.

That first guarded single-unit Unity lab run completed in
`artifacts/vanilla_vfx_style/lab/h3_water_elemental_spine1_v1/` with 54 old, 54 new,
and 57 vanilla frames, `unsupported=[]`, and the selected attack/self-hit
triggers firing. `hero.png`, `idle.png`, both clip sheets, raw half-float
frames, and `compare.mp4` are retained. **The first Spine1 variant failed
visual judgment:** its always-on water reads as a dense white patch over the upper
torso/neck, obscuring the figure, whereas the selected Aqualotl native water
sits around the base/tail. The attack burst does not separate clearly from
the constant idle water in the sampled frames. The isolated follow-up moved
only the idle donor from `Spine1` to the water elemental's base
`Root` bone, keeping attack timing, FLAG, emission, material replica and
scale fixed. The first run is a lab diagnosis, not a shipped-asset approval.

The second guarded lab run made exactly that attachment change. The first
run's complete 175-file output was preserved in
`artifacts/vanilla_vfx_style/lab/h3_water_elemental_spine1_v1/`; the current
`h3_water_elemental/` lab output is the Root iteration. Again the Unity run
exited successfully, no selected shader or module was unsupported, and the
attack trigger fired once. In the current `hero.png`, `idle.png`, and both
sheets, water now stays near the coiled tail/base instead of covering the
face and shoulders, and the later Spine1 self-hit burst is visibly separate.
That resolves the first lab placement negative, but does not establish full
native equivalence: the VANILLA reference is a selected water subset, FLAG
and emission appearance are editor-replica evidence, and no delivery mask,
installed bundle, battle runtime, or user-visible game proof exists. Keep the
draft pending; do not promote from a lab sheet alone.

The water lab masked `artifacts/homm3_def_retarget/h3_water_elemental/`
source geometry for an editor comparison; it did not use a frozen delivery
GLB. No `h3_water_elemental` row exists in the current
`tools/homm3_def_retarget_delivery/*.json` selections. The ship path also
has a sequencing gap: `prepare` chooses its `masterGlb` before the lab,
whereas the current effects compiler makes the `COLOR_0` bake only after
reading that lab's report. Merely changing a source marker or handing the
compiler's later GLB path to Unity would not prove a deliverable mask. A
frozen water selection, prepare-time bake, and imported/bundled color
readback are separate gates before this draft can be promoted.

### Checkpoint: Conflux drafts and Fresnel (2026-09-27)

- The Fresnel replica (`unity/Homm3VfxFresnelReplica.shader`) and the lab's bodyOverlay lane are committed. Psychic and
  magic show the rim on the NEW and VANILLA panels.
- All 15 Conflux drafts pass `check-drafts`. The lab set and per-unit readings are in the rollout doc under "Conflux lab
  set" and in `artifacts/vanilla_vfx_style/lab/conflux_comparison.png`.
- This is lab-render tier only. The bodyDisplacement layers remain pending the fleet ship step. There has been no
  promotion, freeze, deploy or game run.
- Stronghold (roc, thunderbird, shahrokh) is next, after the user's Conflux verdict.

- The raw half-float `renders/` frames of both water lab runs were pruned (about 1.8 GB). The stills, sheets and `compare.mp4`
  are kept.
