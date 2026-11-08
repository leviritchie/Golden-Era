# Float64 Corrective Smooth bake (def_retarget morph targets)

Status: generated artifact validated on the pilot and on every unit rebuilt since 2026-09-30 (the bake record, the
rest round trip, the delivery gates). Frozen slices listed under Rollout. Not built into a bundle, not installed, not
seen in game by this change.

Owner files: `tools/homm3_glb_patch/cs_numpy.py` (the one implementation), `tools/homm3_def_retarget/bake_cs.py` (runs
it inside Blender and writes the shape keys), `tools/homm3_def_retarget/export_glb.py` (writes the bake record and
dense morph targets), `tools/homm3_glb_patch/test_cs_numpy.py`, the build gate `tools/validate_homm3_cs_bake_contract.py`
(`ValidateHomm3CsBakeContract` in `OfflineUnlockMod.csproj`, `SkipHomm3CsBakeContract=true` to skip) and its shrinking
allowlist `tools/homm3_def_retarget/cs_bake_legacy.json`.

## The defect

`bake_cs.py` used to evaluate Blender 5.2's Corrective Smooth modifier (30 length-weighted iterations, factor 0.7) on
a welded proxy and store `(C - S)` in rest space as one morph target per key. Thirty iterations collapse thin parts of
a Meshy body (fur, hems, fingers, wing membranes): on `h3_jotunn_upg_alt` 587 of 2483 weld groups end with an incident
smoothed edge under 1e-6. The modifier builds each corner frame from the cross of two such edges in float32, so there
its frames are rounding noise:

- it does not return the rest pose at the rest pose (0.30 max error on the jotunn, measured in the patch lane);
- its stored targets tear more than no Corrective Smooth at all on the jotunn: 2138 edges past 2x over all targets
  against 979 with skinning only.

## The rule (one solution, fail closed)

1. **Float64, outside the modifier.** Blender provides only the rest mesh, the weights and the pose bone matrices.
   `cs_numpy.py` does the linear-blend skinning, the length-weighted smoothing, the corner tangent frames with angle
   weights, the delta cache and the Tikhonov solve (floor 0.25, scale mask 0.9) in float64. It is a line-by-line port
   of `MOD_correctivesmooth.cc` on the same welded proxy (the weld key, the faces, the edge set are bake_cs's own).
   Blender's `CORRECTIVE_SMOOTH` modifier is no longer used anywhere in the bake.
2. **Degenerate corners, explicitly.** A corner frame's error is about eps64 x |x| / (shortest edge x sin angle). A
   corner whose *height* (shortest incident edge x sin of its angle) is under `DEGEN_CORNER_HEIGHT = 1e-9` x the body
   scale, in the smoothed rest or the smoothed pose, defines no frame and gets weight 0 (Blender already weights exactly
   parallel corners 0). A weld group left with no valid corner at a pose has no frame there (counted,
   `skinOnlyGroupSamples`) and takes the **harmonic interpolation of its weld neighbours' corrective displacement**
   C - S: the uniform weld-graph Laplacian with the defined groups as the boundary, one exact dense solve per pose
   (refused, never truncated, above `FILL_COMPONENT_MAX = 6000` groups). An undefined component that touches no
   defined group (an isolated sliver) is skinning-only (C = S; `unfilledGroupSamples`). Every displacement is 0 at
   the rest pose, so Corrective Smooth at rest still returns the rest mesh exactly; `bake_cs.py` refuses (raises) if
   the round trip exceeds 1e-9 x scale.
3. **Record.** `bake_cs.py` stores `homm3DefRetargetCsBake` (`schema homm3_def_retarget.cs_bake.v3`, the rule,
   iterations, factor, shape keys, rest round trip, invalid corners, skin-only samples, worst offsets) on the scene;
   `export_glb.py` writes it into the GLB's `asset.extras`, and the delivery stages and the look keep it.
4. **Dense morph targets.** The float64 bake leaves exact zeros on rigid parts where the float32 modifier left noise,
   so Blender's exporter would switch most targets to sparse accessors (59 of 139 on the jotunn). `export_glb.py` now
   exports them dense (`export_try_sparse_sk=False`): the numpy delivery stages and the patch lane read and rewrite
   dense targets in place.

Iterations and factor are unchanged (30 / 0.7, the pegasus line's 60 / 0.8), so conditioned regions keep the exact
Blender result: numpy matches the modifier to 3e-7 in smoothing and to <= 6e-5 H on conditioned groups, and the new
bake agrees with the old numpy port to 2.5e-13 there.

### Alternatives measured and rejected (jotunn, 139 targets; edges past 2x / 3x / worst stretch)

| rule | >2x | >3x | worst |
|---|---|---|---|
| skinning only (no CS) | 1019 | 264 | 12.16 |
| legacy Blender float32 CS | 2138 | 356 | 6.96 |
| float64, no degenerate rule | 924 | 478 | 6.97 |
| **float64 + degenerate-corner rule (shipped)** | **614** | **294** | **6.97** |
| float64, skinning-only where a smoothed edge < 1e-3 H | 292 | 98 | 12.16 |
| float64, bone rotation instead of the frame there | 363 | 118 | 12.60 |
| float64, conditioned-neighbour frame there | 1446 | 632 | 11.28 |
| 10 iterations, float64 | 670 | 306 | 7.85 |

The 1e-3 H cut wins on the jotunn but loses on the rest of the pilot (harpy worst 14.9 -> 34.7, unicorn 11.4 -> 18.7,
red dragon >2x 5239 -> 5911) because it switches off CS on 1-3% of well-behaved groups; fewer iterations change the
smoothing everywhere (unicorn >2x 3406 -> 4933, red dragon 5239 -> 8533). The shipped rule changes nothing where the
frames are defined and is better than or equal to the legacy bake on every pilot unit (next table).

### v2 -> v3: the fill (2026-09-30, during the first rollout)

The first rollout shipped v2: undefined groups left at S. That tears where an undefined group borders a strongly
corrected one: h3_champion's Death clip took one 4.6 mm edge to 24.5x (legacy 7.7x), a skin-only vertex at offset 0
beside a neighbour corrected by 0.111. The fill removes it and is better than or equal to v2 on every measured unit
(numpy over every CS target, edges past 2x / 3x / worst):

| unit | v2 | v3 (fill) |
|---|---|---|
| h3_champion | 562 / 180 / 24.51 | 471 / 94 / 7.30 |
| h3_harpy | 2772 / 653 / 14.87 | 2466 / 499 / 14.87 |
| h3_archer | 5546 / 1832 / 41.46 | 5282 / 1577 / 41.46 |
| h3_swordsman | 2092 / 324 / 7.08 | 1991 / 295 / 7.08 |
| h3_red_dragon | 5276 / 783 / 10.99 | 5188 / 742 / 10.99 |
| h3_halberdier | 1434 / 207 / 6.27 | 1400 / 205 / 6.27 |
| h3_pikeman | 1779 / 307 / 5.86 | 1761 / 299 / 5.86 |
| h3_glaivier | 1506 / 162 / 8.24 | 1490 / 154 / 8.24 |
| h3_unicorn | 3410 / 1014 / 11.44 | 3406 / 1014 / 11.44 |
| h3_jotunn_upg_alt, h3_justiciar | unchanged | unchanged |

GLBs baked by v2 are listed once by sha (`supersededSha256` in `cs_bake_legacy.json`, shrink-only like the float32
list) and leave it when their unit's chain re-runs; the patch lane refuses a v2 base like a float32 one. The pilot
table below is v2 (v3 differs only where the fill table shows).

## Pilot (2026-09-30)

Numpy stretch over every CS target of the GLB (edges past 2x, 3x, worst), the stored targets of the legacy bake
against the float64 bake at the same poses. `noMove`: every clip but `Unit_Move` (see the separate finding below).

| unit (why) | legacy all | float64 all | legacy noMove | float64 noMove | rest round trip |
|---|---|---|---|---|---|
| h3_jotunn_upg_alt (collapsed fur; scratch copy, bulwark in flight) | 2138 / 356 / 6.96 | 614 / 294 / 6.97 | 2068 / 352 | 591 / 290 | 1.7e-14 |
| h3_unicorn (quadruped) | 3661 / 1880 / 68.0 | 3503 / 1815 / 68.0 | 1256 / 301 / 8.24 | 1107 / 239 / 8.24 | 2.8e-14 |
| h3_harpy (flyer, thin wings; numpy only, dungeon in flight) | 4215 / 1470 / 14.9 | 2772 / 653 / 14.9 | | | 2.3e-14 |
| h3_red_dragon (large flyer; numpy only, dungeon in flight) | 5433 / 995 / 11.0 | 5276 / 783 / 11.0 | | | 3.3e-17 |
| h3_pikeman (spear) | 1730 / 295 / 5.86 | 1737 / 300 / 5.86 | 1646 / 288 | 1664 / 296 | 3.3e-17 |
| h3_green_dragon (flyer, thin wings) | 1722 / 314 / 4.77 | 1722 / 314 / 4.77 | | | 2.9e-17 |
| h3_ancient_behemoth (large) | 815 / 271 / 8.93 | 496 / 33 / 5.79 | 597 / 230 | 314 / 16 | 3.3e-17 |

Silhouette IoU against the DEF (metrics.json, the Blender render of the reel) is unchanged to four digits on every
pilot unit (unicorn 0.4388, pikeman 0.4385, green dragon 0.3986, ancient behemoth 0.5936); the render's own stretch
falls (frames' edges past 2x summed: unicorn 1091 -> 1014, behemoth 317 -> 159 with worst 8.93 -> 5.79). Delivery gates: every pilot rebuild passed fleet_rebuild's no-regression
gates (freeze / ground / stride / Unit_Move articulation) and the idle rollout; the pikeman's two standing ground
faults (`Death:dead`, `Death:sinks`) cleared. A Blender run of the new `bake_cs.py` on the jotunn stores exactly what
numpy computes on the exported GLB (the same 614 / 294 / 6.97; whole-mesh parity p99 1.6e-7 H, max 5.6e-6 H).

Review sheet (legacy left, float64 right, triangle colour = worst edge stretch): the jotunn's fur hem and the
unicorn, under `artifacts/homm3_cs_bake/` (`sheet_<unit>.png`).

## Rollout

`fleet_rebuild.py <unit>` picks the new bake up in every route (the direct re-bake runs `bake_cs.py`; the emphasis
route re-bakes through `bl_deliver.py`, which execs the same file). Changed morphs mean every downstream stage and the
look are redone and the unit re-frozen; the ship coordinator owns prepare / lab / bundles / probe / deploy. Per-batch
records: `artifacts/homm3_cs_bake/batch_<slice>.json`. A slice where any unit's canonical GLB is not its frozen GLB
(unfrozen work by its owner; this lane's own pilot rebuilds excepted by their recorded evidence) is skipped whole, and a
unit counts as rebuilt only if its fleet_rebuild record was written by that batch run (the launch guard in batch.py).

## Gate

`tools/validate_homm3_cs_bake_contract.py` (in the build): bake_cs uses cs_numpy and no modifier, export writes the
record, the rule constants and the unit tests hold, and every canonical or frozen GLB with CS_ targets carries a valid
current (v3) record or is a legacy / superseded bake listed by sha in `cs_bake_legacy.json`. The list only shrinks (`--prune-legacy`); a new
unstamped bake fails the build; a v2 bake must be in the once-recorded `supersededSha256` list (shrink-only). The
patch lane (`patch_glb.py apply`) refuses a legacy or v2 base and, on a current-rule base, proves parity on every
vertex (no ill-conditioned split).

## Re-keyed clips: the cs_rekey stage (2026-09-30)

Stages after the export re-key bone channels (stride match rewrites `Unit_Move`, Move low-pass likewise, prop floor its
listed clips) but used to keep the morph targets baked for the pre-stage poses. On the unicorn that is where its tearing
lived: `Unit_Move` stored 2396 edges past 2x, 1576 past 3x, worst 68.0x, while Corrective Smooth recomputed at the
delivered Move poses gives 2303 / 775 / 11.4x. Independent of the precision fix (legacy and float64 bakes both showed it).

Rule (one stage, `tools/homm3_def_retarget_delivery/cs_rekey_glb.py`, in `fleet_rebuild.fused_delivery_stages` after
prop floor and before ground; DELIVERY_STAGES `homm3DefRetargetDeliveryCsRekey` / `<glb>.cs_rekey.json`): per CS_
target, the skin matrices at its key in the post-patch export (the reference) and in the stage's input are compared.
Every weighted joint unchanged -> `unchanged`; every weighted joint moved by one common rigid motion -> `rigid` (deyaw;
CS gives the same rest-space offsets); anything else -> the target is re-baked in cs_numpy at the delivered pose,
after numpy at the reference pose reproduced the stored target (patch_glb's parity limits). A densified clip offers only
its original keys (every keysPerSpan-th) as target keys. Ground runs after it: a whole-body translation, under which CS
is invariant. The per-clip status, counts, worst pose deviation and stretch (stored vs written, at the delivered poses)
go into the bake record itself (`homm3DefRetargetCsBake.rekey`).

Gate: `validate_homm3_cs_bake_contract.py` refuses a current-rule GLB that ran the delivery chain (ground stamp) without
that record, or whose record misses a clip with CS_ targets or a clip a re-keying stage stamps
(`cs_rekey_glb.record_errors`); the only exceptions are shas in `staleRekeySha256` of `cs_bake_legacy.json`, recorded
once (`--init-stale-rekey`, 2026-09-30: h3_centaur's orphaned v3 run) and shrink-only.

Held keys and orphan targets (2026-10-01). A one-frame clip is exported at two keys 1/12 s apart; bake_cs keys its one
target at that frame only, so the constant weight curve leaves the target on at both, and the rig at the second key is
not that pose (0.004-0.009 H off on h3_walking_dead / h3_rot_zombie). The stage used to refuse ("on at 2 keys",
necropolis: h3_wight, h3_walking_dead, h3_rot_zombie Unit_MoveEnd/MoveStart, h3_lich_master Unit_Idle). Rule
(`own_key`): one key is that key; several resolve to the key at the target's own frame (its name's frame / 12 s),
exactly one or refused. Probed first: every target of six units (stride-stamped, densified, plain) sits on its
frame/12 key. The other keys keep the stored weight and are recorded (`heldKeys`, `heldKeyMaxPoseDeviation`). A
target whose clip the export left out by the unit config's `skipDefGroups` (h3_vampire_prince: 7 CS_Unit_ShootFront
targets; its shoot groups skipped, user-approved 2026-09-28) is an orphan: it must be weight 0 in every shipped
clip, is left in place unchanged (removing a target would renumber every clip's weight channel), and is recorded under
`rekey.orphans`, which `record_errors` accepts in place of a clip status when its count matches. A missing clip that
is not skipped stays refused. Tests: `test_cs_rekey_glb.py` (run by the validator).

Measured (numpy over the targets of the delivered GLB, edges past 2x / 3x / worst, stored before -> written after):

| unit | clip | before (stale) | after (re-baked) |
|---|---|---|---|
| h3_centaur | Unit_Move | 544 / 204 / 9.32 | 18 / 0 / 2.65 |
| h3_justiciar | Unit_Move | 395 / 80 / 7.72 | 95 / 27 / 5.75 |
| h3_unicorn | Unit_Move | 2396 / 1576 / 68.0 | 2299 / 775 / 11.44 |

Centaur: its v3 delivery against its retained export. Justiciar and unicorn: measured on their delivered (v2) GLBs
against their retained v2 exports with the stage's arithmetic (v2 and v3 agree on the justiciar; on the unicorn they
differ by 3410 -> 3406 edges); their rollout rebuilds re-measure it on v3 (artifacts/homm3_cs_bake/batch_<slice>.json,
`rekey`). Every other clip of these units measured `unchanged` or `rigid`. Parity of numpy against the stored targets at
the reference poses: p99 <= 2.1e-7 H. Proof tier: generated artifact.
