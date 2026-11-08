# HoMM3 Bulwark: Meshy T2 town buildings (candidate t2_v1)

**Proof tier: generated artifact.** The t2_v1 bundle was built offline through unitylock and rendered in the Unity
editor (`pan_*`). It passes three gates:

- the see-through gate, no worse than baseline `fx_v6` (829 px in total);
- the framing gate;
- `validate_town_scene3d_contract.py --catalog` (contract OK, 32 of 32 layers reachable).

The bundle is `artifacts/homm3_bulwark_full3d/candidates/t2_v1/bundle/homm3_town_scene3d_bulwark`: 218,504,820 bytes,
sha256 `2a9e3158988616f9558b310cf49ba0f80cab018eaf68fc62b97accde0e1b36e3`.

**Installed payload.** `t2_v1` was installed in commit 7673d920f3. It was superseded on 2026-10-01 by the props pass
candidate `pb_v1`; see "Props and animation pass" below. There is no startup, runtime or user-visible proof.

- **Brief:** `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md`.
- **Cap:** `townCaps.homm3_bulwark` = 456.
- **Before:** the installed candidate `wall_v2` (bundle sha `0e2d821e...`).
- **Tool:** `tools/homm3_town_scene_meshes/town_full3d_t2_meshy.py --faction bulwark`, with the commands
  `fit | stage | revert | sheet | mainsheet`. The Meshy generation was done by the previous agent's
  `bulwark_t2_buildings.py`, and its handoff is `artifacts/meshy_town_scene_meshes/homm3_bulwark/HANDOFF.md`.
- **Environment:** set `TOWN_FULL3D_EXTSRC=artifacts/claude_takeover_20260927/town_all/bulwark/tex_v2/extsrc_bridge_blend`
  for the `stronghold_full3d_scene.py` calls. The tool sets it itself.

## Verdict (user rule 2026-09-29: Meshy geometry beats the painted relief)

**Deliver t2_v1.** 28 layers ship their Meshy body with a painted front. Two layers are reverted to the `wall_v2`
relief because their meshes are genuinely broken, judged by eye at the sweeps.

| reverted layer | reason |
|---|---|
| tbbud001 | Flat slab. Meshy built a rock platform with a ladder. The sled and the rock trail are missing, and the platform's plate reads as grey slabs over the painted snow at rest (fit IoU 0.48). |
| tbbuu001 | Main feature missing. The crane/hoist over the mine came out as a squat turtle-shaped vehicle (fit IoU 0.45). |

**At rest** (`pan_default`, Unity), the frame reads as the painting. The painted front covers 99.4 to 99.98% of each
Meshy layer's rest px.

**At the sweeps,** the halls, castle levels, longhouses (`tbbud201`/`tbbuu201`), the bone huts (`tbbud301`/`tbbuu301`),
the mage-guild towers, market, tavern, silo and rune stones are solid objects. The relief before smeared on the
longhouses, the bone huts and the silo.

The domes with red streaks at the sweeps are `tbbudo01`/`tbbubo01`. They are unreachable relief layers that this work
does not touch, and they are the same in `wall_v2`.

Rest dE76 is **diagnostic only** under the new rule. The Meshy layers score 4.9 to 10.4 against the relief's 2.4 to
5.7. The remaining distance comes from the silhouette, not the colour: fit IoU is 0.57 to 0.87, and wherever the
model leaves sprite px uncovered, the terrain shows through.

**Yaw.** The fit searches camera-facing (183) +-35 deg in 7-deg steps before the refine. The refine ends up to +-47
from facing (136 to 230). Every door and front reads toward the camera at the sweeps (zoom sheets).

## Spend (shared ledger `artifacts/meshy_town_scene_meshes/_ledger.jsonl`, faction `homm3_bulwark`)

**435 credits of the 456 cap:** 29 image-to-3d meshy-t2 smart-topology textured calls at 15 cr, all spent by the
previous agent. This rebuild made no new Meshy calls.

- **Reused:** `tbbuhu01` uses the `tbbuu501` model (0 cr).
- **Skipped (relief kept):**
  - `tbbuho01` is the grail's translucent spirit painted over the sky, not a structure.
  - `tbbumr01` is the bonfire figure, mostly animated fire.
- **Unreachable and untouched:** `tbbha401`, `tbbuh101`, `tbbubo01`, `tbbudo01`, `tbbuex01`, `tbbuspc1`.

| layer | Meshy taskId | cr | fit IoU | yaw | rest dE76 relief (wall_v2) | rest dE76 t2_v1 | ships |
|---|---|---|---|---|---|---|---|
| tbbha201 | `01a0ef7d-7bf7-7653-87dc-052a901425d7` | 15 | 0.829 | 176 | 4.03 | 5.5 | Meshy + painted front |
| tbbha301 | `01a0ef7d-774d-716a-b32b-b239d05d8bc5` | 15 | 0.795 | 166 | 3.66 | 4.94 | Meshy + painted front |
| tbbubl01 | `01a0ef7e-b39e-7267-95b6-cb93da8c9306` | 15 | 0.794 | 204 | 3.26 | 7.01 | Meshy + painted front |
| tbbucas2 | `01a0ef7d-87fe-7215-9a16-362fdb857552` | 15 | 0.686 | 136 | 4.75 | 7.63 | Meshy + painted front |
| tbbucas3 | `01a0ef7d-8c92-7779-8e95-e66cf5a88a28` | 15 | 0.654 | 204 | 5.1 | 8.43 | Meshy + painted front |
| tbbucstl | `01a0ef7d-83de-758d-8122-1ae43e131837` | 15 | 0.723 | 194 | 4.29 | 6.46 | Meshy + painted front |
| tbbud001 | `01a0ef83-61ca-721e-bf18-425562309215` | 15 | 0.481 | 160 | 5.38 | 5.38 | relief (reverted) |
| tbbud201 | `01a0ef7d-90b8-77f2-b81b-88899f7d20c1` | 15 | 0.848 | 230 | 5.69 | 6.92 | Meshy + painted front |
| tbbud301 | `01a0ef7e-b741-7431-924e-ff61bd9d5d49` | 15 | 0.633 | 136 | 4.78 | 8.11 | Meshy + painted front |
| tbbud501 | `01a0ef7f-0991-74d5-9f0a-480518c566b1` | 15 | 0.644 | 162 | 2.51 | 8.18 | Meshy + painted front |
| tbbudw_1 | `01a0ef83-add1-72c4-b3ef-5dba8cc2e698` | 15 | 0.719 | 223 | 2.4 | 7.68 | Meshy + painted front |
| tbbudw_4 | `01a0ef84-41ef-7478-bc89-c3753107e4cf` | 15 | 0.7 | 186 | 3.7 | 9.13 | Meshy + painted front |
| tbbudw_6 | `01a0ef82-8bbd-70eb-a2ca-9fc8c2faaccf` | 15 | 0.868 | 190 | 2.52 | 7.9 | Meshy + painted front |
| tbbuha01 | `01a0ef7d-7fd6-71b9-a434-8955c37d452f` | 15 | 0.793 | 162 | 4.12 | 5.69 | Meshy + painted front |
| tbbuhu01 | reuse of tbbuu501 | 0 | 0.585 | 176 | 3.52 | 6.23 | Meshy + painted front |
| tbbum101 | `01a0ef7f-5684-7705-b6ac-b05cffc8a8da` | 15 | 0.788 | 221 | 4.42 | 7.49 | Meshy + painted front |
| tbbum201 | `01a0ef81-f28d-750c-ad34-8179afa4096b` | 15 | 0.796 | 221 | 3.82 | 6.98 | Meshy + painted front |
| tbbum301 | `01a0ef82-3e9c-7172-a777-5e5665e90645` | 15 | 0.782 | 194 | 3.73 | 7.42 | Meshy + painted front |
| tbbum401 | `01a0ef82-42ec-71ef-a67c-43e7b7669dd1` | 15 | 0.783 | 218 | 4.14 | 6.42 | Meshy + painted front |
| tbbuma01 | `01a0ef7e-af55-753b-bd2a-ffdd8057fbc4` | 15 | 0.746 | 136 | 3.35 | 7.49 | Meshy + painted front |
| tbbus201 | `01a0ef84-cf61-77a1-8a1d-2bb671554dc0` | 15 | 0.857 | 211 | 3.14 | 7.48 | Meshy + painted front |
| tbbusilo | `01a0ef86-2684-772e-8350-a4e7a31c594a` | 15 | 0.857 | 167 | 5.58 | 10.39 | Meshy + painted front |
| tbbutv01 | `01a0ef7e-ab3b-7066-bec0-a53201cb539e` | 15 | 0.689 | 142 | 4.87 | 9.41 | Meshy + painted front |
| tbbuu001 | `01a0ef83-6575-708a-b340-d4ee24bcf460` | 15 | 0.452 | 162 | 4.68 | 4.68 | relief (reverted) |
| tbbuu101 | `01a0ef84-3e4a-7001-bf91-48c908d37905` | 15 | 0.729 | 142 | 2.77 | 9.13 | Meshy + painted front |
| tbbuu201 | `01a0ef7d-9516-751f-ae92-66a27925fd92` | 15 | 0.774 | 227 | 5.21 | 8.29 | Meshy + painted front |
| tbbuu301 | `01a0ef7f-053b-74cb-9608-55014ff003cc` | 15 | 0.665 | 207 | 4.98 | 7.94 | Meshy + painted front |
| tbbuu501 | `01a0ef7f-0da4-7504-ad46-0a11599de2b8` | 15 | 0.57 | 176 | 3.28 | 7.55 | Meshy + painted front |
| tbbuup_4 | `01a0ef84-457b-71f6-b582-c140f5fd44a7` | 15 | 0.796 | 183 | 3.78 | 8.25 | Meshy + painted front |
| tbbuup_6 | `01a0ef83-5dcf-7758-a4ce-ef49b60e0a77` | 15 | 0.871 | 197 | 3.14 | 6.06 | Meshy + painted front |
| **total** | 29 calls | **435** | | | | | |

`rest_de.json` holds rest dE76 per layer: the mean CIELAB distance to the painting inside the sprite mask, from the
offline Hex/Lit preview with the environment plus that one layer.

## Method

- **Fit.** `fit_mesh_to_sprite.Fitter` searches camera-facing yaw +-35/7 plus refine, with ground contact on the
  painted terrain's depth.
  - The score is the F0.5 silhouette inside the painted rect.
  - `refine_stretch` 0.8 to 1.25 is kept only if it adds more than 0.005 IoU.
  - The castle levels' TRIM px (the foot below row 190/219 native) are don't-care.
  - The fit ran as one serial batch through `cpuslot.py`.
- **Trim and bake** are the same as Necropolis (`docs/homm3_necropolis_t2_town_buildings.md`): pad split/drop,
  buried drop, frame clip, inward-normal flip, sun-bent normals, and a 1024 atlas colour-matched to the painting.
- **Painted front** (the Rampart lane's method, now `town_full3d_t2_paint.painted_front`; see Shared bake):
  - Rest-drawn faces are subdivided to 4 px or less.
  - A face is front if it owns 60% or more of its SUPER=2 px, or if its centroid or any corner is at the rest
    surface within 0.5%.
  - `Mesh_Body_<layer>` holds the front faces. Their UV is the rest px in a SUPER=2 crop of the painting's sprite
    plate. That plate is de-lit per px by the Hex/Lit irradiance of the smooth camera-facing normal, which the bin
    carries.
  - `Mesh_Body_<layer>_meshy` holds the rest of the faces, with the Meshy atlas.
  - Both bins are two-sided.
  - Outside the sprite's opaque non-shadow alpha, the plate carries the nearest inside px. Before this was fixed, the
    fill used the building mask, which painted the castle's snow ledge with wall stone.
- **Revert:** the `revert` command copies the layer's staged prefab files and rows from `wall_v2`, drops the
  `_meshy` bin, records the reason in `stage_report.json` (`meshyT2.reverted`), and re-runs catalog, preview and the
  see-through gate.

## Props and animation pass (2026-09-30, candidate `pb_v1`, installed)

`pb_v1` is seeded from `t2_v1`. It went through the group B props pass over the regions that `town_t2_streak_map.py`
flags as streaking at the reachable sweep poses. The camera range is unchanged.

- **Streak regions.** The snow slope by the rune stones and the stair ruins, and the ground around the pyre and the
  market.
- **Props.** Specs are in `tools/homm3_town_scene_meshes/town_t2_props_specs_groupB.py`.
  - Generated: `boulder` and `ruin`.
  - The placer chose 1 `ruin` position (estimated gain 864 px at sweep_right) and no `boulder` position.
  - The ruin was dropped by eye, so **no prop ships**. The environment has no `Mesh_Prop_*` bin and the catalog has
    no props block. `stage_report.json` keeps the block with `shipped: false`, and the drop is in `placement.json`.
  - Credits: 42 (2 concepts and 2 meshes), logged under `"pass": "props_20260930_groupB"` in
    `artifacts/meshy_town_scene_meshes/_ledger.jsonl`. The group B pass total is 342/900.
- **Measured streak (stretched px, full scene, `pb_v1`):**

  | pose | streak |
  |---|---|
  | sweep_left | 9767 |
  | sweep_right | 17352 |
  | sweep_high | 10757 |

  The streak is unchanged by props, because none shipped.
- **Animation.**
  - One buried effect was slid in front of its Meshy body along the rest camera ray with
    `town_t2_fx_occlusion.py snap`: the `tbbuma01` glow (`Fx_Glow_0_tbbuma01`, occluded share 0.66 before, slide
    0.968). The rest frame is unchanged.
  - Static, recorded and not animated in this pass: the hoist bucket.
  - Adventure-map reuse: none, because the map-building sculpts are separate meshes.
- **Review sheet:** `artifacts/claude_takeover_20260927/review/homm3_bulwark_props_pb_v1.png`.
- **Install.** Installed on 2026-10-01:
  - bundle sha256 `d81069a444f98d087e311c60c65dde3deaee9a4d84a1bf8b6da20551f6d72ceb` (218,557,610 bytes);
  - catalog sha256 `212c696be3c71dc014e07165dc9b6a5b887e4280680bc77e2c7e42beb8046bbf`;
  - rollback (`t2_v1`) in `artifacts/town_scene_rollback/bulwark_20261001T005314Z`;
  - the validator is OK, with no props block.

  An earlier bundle attempt failed with UNITYLOCK BUSY, caused by a stale lock left by a dead group A process. It was
  rebuilt after the coordinator's unitylock fix (e3df978cf2).
- **Depth source.** This pass was built on the lane's DA V2 Large background depth. The like-for-like rebuild on the
  img2img background depth is candidate `bgd_v1`; see "Background depth A/B" below.
- **Proof tier: installed payload.** Startup, runtime and user-visible proof are not yet done.

## Review

- **Main sheet:** `artifacts/claude_takeover_20260927/review/homm3_bulwark_t2_buildings.png`. It shows painting |
  before | after as Unity renders at the rest and 3 sweep poses.
- **Zoom sheets:** `homm3_bulwark_t2_buildings_zoom_{1,2,3}.png`, offline Hex/Lit, painting | before | after at
  rest and before | after at each sweep.
- **Renders:** `artifacts/homm3_bulwark_full3d/candidates/t2_v1/renders/`.

## Shared bake (2026-09-30)

The painted-front bake is `tools/homm3_town_scene_meshes/town_full3d_t2_paint.py`, the one T2 bake for all eleven factions. On 2026-09-30 it absorbed the last four copies: `rampart_t2_buildings.stage_split` (Rampart, Dungeon), `inferno_t2_integrate.stage_layer`, `town_full3d_t2_meshy.painted_front` (Necropolis, Bulwark) and `t2_rest_geometry.stage_painted_layer` (Castle, Tower). Where a lane's bake differs by design, the difference is a named parameter of the shared module, set at this lane's call site; no output was changed to force identity.

This lane's values (`town_full3d_t2_meshy.painted_front`): `subdivide_screen(seen_super=1)` (faces are split when drawn at frame px); the `sprite_fill` mask is the plate's opaque non-shadow alpha (`_plate_mask`); `sampler="scipy"`; `min_front_tris=50`; `meshy_albedo=` the atlas that `bake` colour-matched, so no gain is applied.

Restaging the sample layer tbbutv01 with the shared module into a scratch stage gives files byte-identical to this candidate's (`t2_v1`) staged bins, and so did the old code before the fold (`tools/homm3_town_scene_meshes/t2_bake_restage_check.py`; results in `artifacts/town_t2_bake_consolidation/`). The bundle was not rebuilt. Proof tier of this note: generated artifact.

## Background depth A/B (2026-10-01, candidate `bgd_v1`, not installed)

`bgd_v1` is `pb_v1` with the img2img background depth as the only intended difference. Every `pb_v1` layer is carried
over and seated on the new ground.

- **Depth.** `artifacts/img2img_depth_maps/homm3_bulwark/background/Bulwark-in-background__depth_raw.png`
  (sha256 `99accfaec2c14f66a56abd25408e86c3b1bd617ba689cdf0c71086b860233c68`) was registered by ECC affine (`town_full3d_bg_depth.py import`) to
  `depth/img2img_bg.npy` (sha256 `c11dc3a85a96b6b175c95bd2b28aa105614b6a3f58da0b3a5048bae6c9dc69cb`). It is pinned in `work/background_depth.json` and recorded in
  `stage_report.json` `terrain.backgroundDepth`. Building depths are unchanged.
- **Environment.** `stage --parts terrain,sky,periphery,nearfield` with EXTSRC `town_all/bulwark/tex_v2/extsrc_bridge_blend` (the control matches, apart from a 2-vertex / 0.24 mean texel drift in `Mesh_Terrain` and nearfield scatter drift).
  - The same restage on the old depth (control `ctl_v1`, `artifacts/claude_takeover_20260927/town_all/bgdepth_groupB/env_compare.py`) reproduces `pb_v1`'s env bins.
    The nearfield scatter is the exception: it drifts with floor area independently of depth.
- **Buildings.**
  - Buildings: each building prefab is slid along its rest rays onto the new ground by a uniform scale about the rest
    camera. The prefab origin is the camera, so the rest frame is unchanged. k is the median foot-ray ratio of the new
    ground to `pb_v1`'s ground (`artifacts/claude_takeover_20260927/town_all/bgdepth_groupB/snap_buildings.py`; per layer in `work/building_snap.json`). The
    lane's Meshy re-fit tools write shared fit records, so they were not re-run.
- **Props.** Each instance keeps its type, yaw and rest pixel. Its base slides along the rest ray onto the new ground
  and its height scales with the distance (`artifacts/claude_takeover_20260927/town_all/bgdepth_groupB/snap_props.py`). On the old-depth control the ratio is
  1.0000 ± 0.0005.
- **Fx.** Re-audited with `town_t2_fx_occlusion.py audit`.
- **Renders:** `artifacts/homm3_bulwark_full3d/candidates/bgd_v1/renders/` (standard set).
- **Sheet** (pb_v1 | bgd_v1 | diff): `artifacts/claude_takeover_20260927/review/homm3_bulwark_bgd_v1_vs_pb_v1.png`.
- **By eye:** Every layer is present. The rest frame shows a faint seam along the painted rect's top and right edges.
  At the sweeps, the stream bed and the right slopes smear much more. `Fx_Glow_0_tbbum401` is newly part-occluded
  (0.28).
- **Measured streak (stretched px, full scene):**

  | pose | `pb_v1` (DA V2 Large) | `bgd_v1` (img2img) |
  |---|---|---|
  | sweep_left | 9767 | 49342 |
  | sweep_right | 17352 | 68147 |
  | sweep_high | 10757 | 52011 |
  | default | 0 | 402 |

  **Verdict:** Worse: the sweep streak is about 4 to 5 times higher. The new depth is not adopted for this town. `pb_v1` stays installed, and no Meshy
  credits were spent on the new depth.
- **Proof tier:** generated artifact. The bundle was built and editor-rendered; it is not installed.
