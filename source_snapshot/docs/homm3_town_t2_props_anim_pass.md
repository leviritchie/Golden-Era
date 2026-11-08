# Full-3D T2 towns: props + building-animation pass, group A (2026-09-30)

Towns: castle, rampart, tower, inferno, necropolis, dungeon. Candidate `props_v1` per town, built on that town's
`t2_v1` (tower: `tw_t2`). Reference is the HoMM3 town painting only (never the blurred 2D backdrop); the camera's
range is not limited anywhere - the fixes are content at the reachable sweep poses
(`conflux_town_camera_pan.proof_poses`).

Tools (all under `tools/homm3_town_scene_meshes/`):

- `town_t2_streak_map.py` - where the scene streaks at a pose (texel anisotropy, offline raster, no Unity).
- `town_t2_props_gen.py` - Meshy text-to-3D props, every task + credit logged in
  `artifacts/meshy_town_scene_meshes/_ledger.jsonl`; pass cap `_budget_<pass>.json` (900 credits).
- `town_t2_props.py place|stage|check` - greedy placement over the streak px, staging as `Mesh_Prop_<type>` bins.
- `town_t2_anim_pass.py apply [--base <cand>]` - per-building animation recipes (cloth / pulse / shimmer / strike).
- `town_t2_review_sheet.py --before <cand>` - painting | before | after at rest and every pose, effects t0..t2 and a
  motion heat row.
- `town_full3d_bg_depth.py import|compare` - the 2026-09-30 img2img background depth (see below).

Gate: `tools/validate_town_scene3d_contract.py` checks the catalog's `props` block (`check_props`): the
`Mesh_Prop_*` bins equal the declared types, the instance count matches, and `meshyCredits` equals the ledger's spend
for that town in the pass, with the pass total no more than its cap.

## Props (Meshy, pass `props_t2_20260930`, cap 900)

| town | types | instances | credits | target streak px before -> after (offline estimate) |
|---|---|---|---|---|
| castle | pine, spire, shrub | 6 (2 dropped: floats) | 84 | sweep_left 24896 -> 24563, sweep_right 47005 -> 39934, sweep_high 23912 -> 19091 (measured) |
| rampart | fir, oak, boulder | 23 (8 oaks dropped: floats) | 63 | sweep_left 2034 -> 2035, sweep_right 1905 -> 1906, sweep_high 2112 -> 2112 (measured; the props cover the white-void TARGET_RECTS the texel metric misses) |
| tower | boulder, slab, crag (spire placed none) | 39 (1 dropped: floats) | 84 | sweep_left 14439 -> 14335, sweep_right 24419 -> 20920, sweep_high 12627 -> 10736 (tw_t2 -> props_v1, measured) |
| inferno | spikes, crag, mound | 3 (1 dropped: floats) | 63 | sweep_left 7349 -> 6158, sweep_right 17807 -> 17049, sweep_high 7714 -> 7593 (t2_v1 -> props_v1, measured) |
| necropolis | deadtree, ruin, mound | 4 (10 dropped: floats) | 69 | sweep_left 5687 -> 5687, sweep_right 28033 -> 15593, sweep_high 24423 -> 13317 (measured) |
| dungeon | stalagmite, mushrooms (pillar, rock all dropped) | 25 (15 dropped: floats) | 84 | sweep_left 77310 -> 75090, sweep_right 98632 -> 86956, sweep_high 75423 -> 65959 (measured) |

All rows are the streak map (`town_t2_streak_map.py`, whole scene) of the
bundled candidate after `drop-bad`. The dungeon's earlier large estimated gain was almost all from the cave-ceiling
cluster that floated. Rampart: the floating rule flagged exactly the 8 oaks that read by eye as hanging against the
white void (-5.3..-6.7 deg); the 4 other oaks pass and are kept, one of them stands at the left edge at sweep_left in
front of the void with coarse faceted foliage (grounded; flagged for the in-game comparison). The credits of dropped props stay spent (ledger), the drops are in `placement.json` "dropped".

Floating rule (`town_t2_props.py check`, added 2026-09-30 after the editor renders showed rocks hanging in the air):
foot overhang (scene read 4 px below the foot points: nothing, or > 1.15x deeper, at > 50% of the foot at any view)
or a view looking up at the base by more than 4 deg. Threshold from the renders: every instance that read as
floating was at -4.2 deg or lower, those that read as standing were above (necropolis mound 1.0, dungeon mushrooms
-1.2..-0.2); a +3 deg rule dropped every necropolis prop including standing ones. `place` applies the same rule.

Total 447 of 900. No Meshy was used for any adventure-map building. What props do not fix: the castle (and part of
dungeon) streaks are terrain slivers carved behind the house clusters; a prop that covers them at a sweep is seen at
rest, so placement pays a bounded rest deviation (`check`) and covers little there. That is a carve-geometry problem,
recorded, not fixed.

## Building animations

For every glow/lightning DEF the HoMM3 frames were read (what moves), and the 2026-09-30 editor renders measured how
many px the staged effect moves (`|t1-t0|+|t2-t1|` > 12 inside its rect). All decisions are new work on the town
scene's own effect (retune of the staged group, same rest position and DEF change mask); no adventure-map animation is
reused, because each of these buildings is already staged with its own DEF-masked effect and the adventure-map
versions animate different art at a different scale.

| town | layer(s) | HoMM3 animates | before | decision |
|---|---|---|---|---|
| castle | tbcsdw_5, _5_2, tbcshall, tbcshal2, tbcshal3 | waving banners | 4-52 px | cloth recipe; superseded 2026-10-01 (user: inadequate) by the mesh wave `town_full3d_cloth.py`, docs/homm3_town_cloth_wave.md |
| castle | tbcsmag3, tbcsmag4, tbcsspec | orbs, lighthouse lamp | 5-9 px | pulse (orbs 9 -> 464, lighthouse 5 -> 128) |
| rampart | tbrmdw_6, _6_2 | dragon-cliff glints | 0 px | shimmer |
| tower | tbtwdw_6_2 | lightning strike | 0 px | strike (bolt threshold on decoded noise) |
| tower | smoke, glints | smoke, sparkles | 533 px | kept |
| inferno | flames | fire | healthy | kept |
| necropolis | tbncblak, tbncholy | pillars, holy obelisk | 11 / 0 px | pulse |
| dungeon | tbdndw_0, _0_2, tbdnhrd2, tbdndw_2, _2_2 | slime drips, beholder skin | 0-9 px | shimmer |

Second root cause (found 2026-09-30 evening): the Unity builder reads `build_spec.json`, not `rows.json`, and `apply`
wrote rows.json only, so every re-tune after the first apply never reached a bundle. `apply` now rewrites the build
spec + catalog (`town_t2_anim_pass.py catalog` does that step alone) and `stronghold_full3d_scene.bundle()` refuses a
build spec older than rows.json. The dungeon shimmer was then too strong (slime blotches) and is softened
(smoothstep(0.06, 0.3), unboosted colour, particle alpha 0.7); on the props_v1 render the slime motion is a modest
scatter over the pool. Necropolis on the first correct render: forge 11 -> 2794 px moved, holy obelisk 0 -> 1382
(slight pink haze on the forge).

Root cause of the 0 px effects: the masks and the shared TileNoise textures are imported sRGB, so the shader's
`smoothstep(_Min, _Max, min(n1, n2) * mask)` saw decoded values (0.5 -> 0.21). Masks are now linear; the noise stays
sRGB (shared files) and the thresholds are set on the decoded distribution (`town_t2_anim_pass.py` docstring).

## img2img background depth (2026-09-30): stopped - judged unfaithful

User verdict (2026-09-30, relayed): the img2img maps add contrast rather than predicting depth, so the `bgd_v1` work
stops here; `props_v1` on the old (DA Large) depth is the delivery line. The castle `bgd_v1` pan-coverage void
(1 ray of 330000 at 4096x2160; rampart `bgd_v1` 5 rays at 16:9) is left unfixed. The record below is kept as
evidence; the pin path stays opt-in (no candidate on the delivery line pins it).

Source: `artifacts/img2img_depth_maps/homm3_<town>/background/*__depth_raw.png`, sha-checked against
`background_checkpoint.json`. Import: `town_full3d_bg_depth.py import` writes `depth/img2img_bg.{npy,json}`
(provenance + registration). The terrain reads it only when a candidate pins it (`work/background_depth.json`,
`stronghold_full3d_terrain.background_disparity`; sha mismatch fails, no fallback) and records the source in
`stage_report.terrain.backgroundDepth`.

Registration (ECC affine on blurred gradient magnitude, painting vs depth; the warp is applied to the depth):

| town | max px | median px | residual tile median / p90 px |
|---|---|---|---|
| necropolis | 12.8 | 10.1 | 2.5 / 3.2 |
| inferno | 7.9 | 5.1 | 1.2 / 2.8 |
| dungeon | 6.5 | 4.2 | phase peaks unusable |
| castle | 3.6 | 1.4 | 1.1 / 2.1 |
| rampart | 1.2 | 0.9 | 1.0 / 2.1 |
| tower | 1.3 | 0.5 | 1.9 / 5.3 |

Evaluation (`bgd_v1` = `props_v1` with terrain/sky/periphery/nearfield restaged on the pinned depth; a control
restage on the old depth reproduces `props_v1`'s meshes). Streak px (`town_t2_streak_map.py`):

| town | sweep_left props_v1 -> bgd_v1 | sweep_right | sweep_high |
|---|---|---|---|
| castle | 24563 -> 70131 | 37189 -> 82423 | 17449 -> 67874 |
| rampart | 2035 -> 67208 | 1906 -> 14906 | 2112 -> 16064 |
| tower | 14335 -> 27312 | 20920 -> 60349 | 10720 -> 33498 |
| inferno | 6158 -> 16318 | 16989 -> 38493 | 7538 -> 21070 |
| necropolis | 5680 -> 23323 | 14948 -> 37900 | 12925 -> 18842 |
| dungeon | 36723 -> 89567 | 39069 -> 125208 | 24852 -> 80223 |

After the floating props were dropped, bgd_v1 of inferno, necropolis and dungeon was restaged with props_v1's exact
post-drop `placement.json` (and the softened dungeon shimmer), re-bundled and re-rendered, so these three compare
like for like again (same props, same effects, only the depth-derived terrain/periphery bins differ):

| town | sweep_left props_v1 -> bgd_v1 | sweep_right | sweep_high |
|---|---|---|---|
| inferno | 6158 -> 16319 | 17049 -> 38493 | 7593 -> 21070 |
| necropolis | 5687 -> 23325 | 15593 -> 38086 | 13317 -> 18987 |
| dungeon | 75090 -> 89749 | 86956 -> 131530 | 65959 -> 82824 |

bgd_v1 keeps props_v1's props and effects (props stand where they were placed on the old terrain), so it is the
props + new depth combination; it was also bundled and editor-rendered for the review board (renders under
`<candidate>/renders/`).

The sharper map puts real depth steps at painted house, ridge and cliff edges; the lane's terrain is one continuous
mesh, so every step becomes a stretched curtain and streaking rises at every sweep in every town. Using this depth
well needs discontinuity cuts with layered fill (an LDI-style terrain) - a terrain fix, not a reason to regenerate
the maps. The user wants the new maps used once that fix exists: experiment candidates `rx_ldi_*`, `rx_layer_*`,
`rx_cond_*` (copied from `bgd_v1`, other agents) are testing it. This pass therefore delivers `props_v1` on the old
depth; no props were re-placed and no credits spent on the new depth's account. The imports, the pin path and the
`bgd_v1` candidates stay (the experiments copy from them).

## Proof tiers

| town | delivered | tier |
|---|---|---|
| inferno | props_v1 installed 2026-10-01T02:48Z (bundle 098f9f4b5594, rollback `artifacts/town_scene_rollback/inferno_20261001T024821Z`) | installed payload (validator + sha256 readback) |
| necropolis | props_v1 installed 2026-10-01T02:49Z (bundle fda92e1dc8e5, rollback `necropolis_20261001T024907Z`) | installed payload |
| dungeon | props_v1 installed 2026-10-01T02:49Z (bundle dd0e56a1fd52, rollback `dungeon_20261001T024943Z`) | installed payload |
| castle, rampart, tower | props_v1 rebuilt after drop-bad (rampart shimmer reapplied), bundled + editor-rendered, validator OK; not installed (the coordinator installs after the in-game terrain-repair comparison); tower strike not seen in the t0..t2 frames | generated artifact |

Editor renders and offline rasters are generated-artifact proof. Nothing here is in-game (startup / runtime /
user-visible) proven.
