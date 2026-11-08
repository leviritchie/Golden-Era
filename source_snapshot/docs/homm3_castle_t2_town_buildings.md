# Castle town scene: Meshy T2 building meshes (candidate t2_v1)

Brief: `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md` (2026-09-29). Cap `townCaps["homm3_castle"]` = 540 cr.

**Proof tier: build target proven.** The bundle was built and editor-rendered, and the town-scene contract is OK. It is not installed and not game-visible. The installed candidate is still `wall_v4`.

## What it is

- Candidate: `artifacts/homm3_castle_full3d/candidates/t2_v1`, seeded from the installed `wall_v4`.
  Terrain, sky, periphery, near field and FX pieces are the seed's, byte for byte. Only each meshed layer's
  `Mesh_Body_<layer>` is replaced.
- Code:
  - `tools/homm3_town_scene_meshes/castle_t2_buildings.py`: fit / stage / preview / rest-de / restore / sheet.
  - `artifacts/meshy_town_scene_meshes/homm3_castle/gen_castle_t2.py`: billed generation, ledger-checked.
  - The shared `stronghold_full3d_*` and `fit_mesh_to_sprite` modules are imported, never edited.
- Each meshed layer gets up to three lit bins:
  - `Mesh_Body_<layer>`: every triangle the rest camera sees, textured by rest-camera projection of the painting and de-lit with the seed's own painting-derived normals. The rest frame is therefore the painting.
  - `Mesh_BodyM_<layer>`: every other triangle carries the Meshy texture, gain-matched to the de-lit painting and two-sided.
  - `Mesh_BodyRest_<layer>`: the seed's front triangles over sprite px that the mesh does not cover (painted skirts, lake, rocks, shadows).

## Pipeline decisions (measured)

- **Yaw.** Meshy re-poses buildings, so the camera ray gives no yaw, and the silhouette cannot tell a building from its 180-degree turn.
  - Each layer is fitted per quadrant: yaw ±30 about 0/90/180/270, scored by F0.5 of silhouette vs body mask.
  - `YAW_PICK` in the script holds manual quadrant picks, made from per-quadrant yaw panels (`_work/yaw_<layer>.png`).
  - The automatic tiebreak, agreement with the seed's normals, was wrong on hall / hal2 / cstl.
- **Subdivision.** Only triangles seen at rest are subdivided, to ≤ 10 frame px (hall: 40k triangles, not 1.5M).
- **Rest visibility.** Visibility at rest is a depth-consistency test (`rest_visible`), not an id-buffer share. Sliver triangles otherwise left Meshy texels speckled in the rest frame.
- **Frame clip.** New in this run: meshes are cut exactly at the painted rect's frame lines (x = 0, x = TW, y = 0, y = TH at the rest camera).
  - The fit lets frame-cut buildings continue past the cut.
  - `town_full3d_framing` then refused the candidate: tbcshal3 and tbcstvrn went to x = -0.018, and tbcsmage to 0.919 against the HUD edge at 0.90. Only their hidden `Mesh_BodyM` vertices were outside.
  - The seed ends at the same lines. The gate was not changed.
- **Rest dE76** is diagnostic only (coordinator rule, 2026-09-29): Meshy geometry beats the relief. No layer was reverted on dE.

## Layers

29 layers are staged on Meshy geometry. No layer was reverted to relief.

| layer | mesh from | yaw | IoU | F0.5 | tris | painted | Meshy | residual | de-lit clipped |
|---|---|---|---|---|---|---|---|---|---|
| tbcshall | tbcshall | 102 | 0.70 | 0.91 | 39820 | 35906 | 3914 | 8846 | 0.01 |
| tbcshal2 | tbcshal2 | 213 | 0.79 | 0.94 | 58508 | 53345 | 5163 | 6449 | 0.031 |
| tbcshal3 | tbcshal3 | 264 | 0.77 | 0.93 | 62429 | 55736 | 6693 | 6687 | 0.025 |
| tbcscstl | tbcscstl | 258 | 0.74 | 0.91 | 24972 | 18929 | 6043 | 5526 | 0 |
| tbcscas2 | tbcscstl (reuse) | 258 | 0.74 | 0.91 | 25047 | 18973 | 6074 | 18166 | 0 |
| tbcscas3 | tbcscas3 | 219 | 0.76 | 0.90 | 36053 | 30990 | 5063 | 14608 | 0 |
| tbcsmage | tbcsmage | 159 | 0.79 | 0.92 | 6607 | 4571 | 2036 | 1126 | 0.001 |
| tbcsmag2 | tbcsmag2 | 249 | 0.78 | 0.92 | 7837 | 6030 | 1807 | 1136 | 0.003 |
| tbcsmag3 | tbcsmag3 | 165 | 0.72 | 0.90 | 8877 | 6735 | 2142 | 1604 | 0.009 |
| tbcsmag4 | tbcsmag4 | 222 | 0.73 | 0.92 | 9691 | 7749 | 1942 | 2139 | 0.006 |
| tbcmark | tbcmark | 183 | 0.70 | 0.88 | 19572 | 15670 | 3902 | 6718 | 0 |
| tbcsblak | tbcsblak | 180 | 0.70 | 0.89 | 14016 | 11431 | 2585 | 4505 | 0 |
| tbcssilo | tbcssilo | 162 | 0.86 | 0.96 | 5063 | 3543 | 1520 | 753 | 0 |
| tbcsspec | tbcsspec | 336 | 0.90 | 0.95 | 4901 | 3386 | 1515 | 1183 | 0 |
| tbcsholy | tbcsholy | 168 | 0.70 | 0.85 | 6367 | 4820 | 1547 | 1325 | 0.139 |
| tbcstvrn | tbcstvrn (t2_pricecheck) | 159 | 0.82 | 0.95 | 18230 | 12708 | 5522 | 3113 | 0.066 |
| tbcsdw_0 | tbcsdw_0 | 0 | 0.74 | 0.92 | 6304 | 3921 | 2383 | 1566 | 0.064 |
| tbcsdw_0_2 | tbcsdw_0_2 | 156 | 0.72 | 0.91 | 7056 | 4966 | 2090 | 1681 | 0.042 |
| tbcsdw_1 | tbcsdw_1 | 168 | 0.72 | 0.88 | 9268 | 6888 | 2380 | 1457 | 0.072 |
| tbcsdw_1_2 | tbcsdw_1_2 | 162 | 0.78 | 0.92 | 9102 | 6718 | 2384 | 1695 | 0.124 |
| tbcsdw_2 | tbcsdw_2 | 105 | 0.60 | 0.78 | 7943 | 5399 | 2544 | 3478 | 0.093 |
| tbcsdw_2_2 | tbcsdw_2_2 | 201 | 0.58 | 0.82 | 10178 | 7007 | 3171 | 5312 | 0.074 |
| tbcshrd2 | tbcsdw_2_2 (reuse) | 201 | 0.58 | 0.83 | 10190 | 7008 | 3182 | 5320 | 0.051 |
| tbcsdw_3 | tbcsdw_3 | 144 | 0.61 | 0.84 | 7370 | 5231 | 2139 | 2471 | 0.048 |
| tbcsdw_3_2 | tbcsdw_3_2 | 162 | 0.60 | 0.85 | 7641 | 5800 | 1841 | 3405 | 0.083 |
| tbcsdw_4 | tbcsdw_4 | 78 | 0.70 | 0.91 | 8483 | 5819 | 2664 | 1773 | 0 |
| tbcsdw_4_2 | tbcsdw_4_2 | 348 | 0.71 | 0.91 | 13365 | 10249 | 3116 | 2310 | 0 |
| tbcsdw_5 | tbcsdw_5 | 192 | 0.56 | 0.78 | 29301 | 26548 | 2753 | 8055 | 0.002 |
| tbcsdw_5_2 | tbcsdw_5_2 | 114 | 0.58 | 0.83 | 28057 | 24815 | 3242 | 8819 | 0.012 |

**Reuses (no spend):**

- tbcscas2 uses the tbcscstl mesh. The castle body is identical in alpha, and the level only adds the moat, which stays painted water.
- tbcshrd2 uses the tbcsdw_2_2 mesh: the same griffin tower in the same place.

**Skipped (relief kept):**

- tbcsdock: painted lake water and a 20 px pier. There is no standalone structure to model.
- tbcsdw_6 and tbcsdw_6_2: the Portal of Glory, a gate on a painted cloud with light rays, 160 m out in the sky. A Meshy cloud would be a solid lump.

**Reverts to relief:** none.

- dw_2 / dw_2_2 / hrd2 and dw_5 / dw_5_2 were the suspects, since they have the weakest IoU (0.56–0.60). All were checked by eye at the four sweeps.
- The griffin towers keep their gate arch in the projection, and the training grounds keep tents and the banner wall.
- None is fragmented, a flat slab, or missing its main feature.

## Spend log (ledger `artifacts/meshy_town_scene_meshes/_ledger.jsonl`)

| ts (2026-09-29) | layer | kind | cr | task id |
|---|---|---|---|---|
| 18:25:45 | tbcscstl | image-to-image nano-banana-2 (concept) | 6 | 01a0ef7d-0849-70b2-9286-e83792482959 |
| 18:25:46 | tbcscas3 | image-to-image nano-banana-2 (concept) | 6 | 01a0ef7d-0b4d-735f-a761-08e3f696fbb7 |
| 18:25:47 | tbcshall | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-0e38-70b7-a560-f426b40ba0f7 |
| 18:25:48 | tbcshal2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-1297-77e0-b8a5-eb88fe43fb09 |
| 18:25:49 | tbcshal3 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-1722-76d1-8681-d4dad0bc0d95 |
| 18:25:50 | tbcsmage | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-1c5e-7673-8494-c705d16f32b4 |
| 18:25:52 | tbcsmag2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-20f4-71ba-930f-615345c2bbe7 |
| 18:25:53 | tbcsmag3 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-2518-72c9-87db-304833984242 |
| 18:26:34 | tbcsmag4 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-c882-76c0-8363-4f44dfe0d517 |
| 18:26:38 | tbcmark | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-d6a4-7750-8324-e360f506929e |
| 18:26:40 | tbcsblak | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-df1e-7422-a778-3427b90a98d2 |
| 18:26:51 | tbcssilo | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-09bf-73e6-8581-5597e4f168b8 |
| 18:26:52 | tbcsspec | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-0d8e-756d-a73c-b57aa4cb64b7 |
| 18:26:54 | tbcsholy | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-1683-71f0-a101-5b20c44f5021 |
| 18:27:53 | tbcsdw_0 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-f944-771a-8cd6-7ffed588def9 |
| 18:27:56 | tbcsdw_0_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7f-0686-741c-9f4a-119d3b8c8a10 |
| 18:28:09 | tbcsdw_1 | image-to-3d meshy-t2 textured | 15 | 01a0ef7f-3a4f-728d-a9b2-d9d2a26fe6f4 |
| 18:28:10 | tbcsdw_1_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7f-3e96-74fb-bd9a-6f80af3d3a1e |
| 18:28:14 | tbcsdw_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7f-4bc4-77f2-86e9-922bddc8c2ce |
| 18:28:28 | tbcsdw_2_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7f-8279-77fb-b4ed-d6500ef09c00 |
| 18:30:39 | tbcscstl | image-to-3d meshy-t2 textured | 15 | 01a0ef81-8238-72cb-a74d-ceceaaa4e00e |
| 18:30:40 | tbcscas3 | image-to-3d meshy-t2 textured | 15 | 01a0ef81-870b-72b1-bc33-f1a211bbdd4e |
| 18:32:29 | tbcsdw_3 | image-to-3d meshy-t2 textured | 15 | 01a0ef83-306a-735f-80b2-09915c5e8535 |
| 18:32:30 | tbcsdw_3_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef83-34f3-7207-9a97-3ecfed3a7039 |
| 18:32:31 | tbcsdw_4 | image-to-3d meshy-t2 textured | 15 | 01a0ef83-3970-7345-82c9-01762ff5f1bf |
| 18:32:32 | tbcsdw_4_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef83-3d39-7526-b13d-250e2ceac7cc |
| 18:32:34 | tbcsdw_5 | image-to-3d meshy-t2 textured | 15 | 01a0ef83-438c-73d9-93ab-bc400e0ece53 |
| 18:32:34 | tbcsdw_5_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef83-4786-75c3-bd33-eaed2759f019 |
| 19:00 | tbcstvrn | image-to-3d meshy-t2 textured (price check, reused) | 15 | 01a0ef76-7ad3-75c6-ac60-65cfe4dae392 |

**Total: 417 of 540 cr** (27 meshes at 15 cr, plus 2 concept images at 6 cr), tavern price check included.

## Gates

- Stage: `town_full3d_framing` passed: every building is inside the visible region at the framed rest, after the frame clip.
- `stronghold_full3d_scene.py cull`: see-through 286 px, no worse than the `fix_v1` baseline.
- `bundle`: `artifacts/homm3_castle_full3d/candidates/t2_v1/bundle/homm3_town_scene3d_castle`, 296374485 bytes, sha256 `27c28c53cf7a3978bd31d32552c3d1ccb70c8cb4aff73ff89ef686ec113e9b4e`. It was built through unitylock, inside a cpuslot.
- `render`: RenderStates rc 0 (`candidates/t2_v1/renders/`).
- `validate`: `town-scene3d-contract: OK homm3_castle layers=32 reachable=32 unused=0 bundle=present flag=off (candidate) restPose=installed-native-verified framing=zoom1.19/pan0.5 ... panVoid=0 panNeg16x9=0.020`.

## Status

**Not installed.** The coordinator authorised the install (2026-09-29): `install_town_scene3d.py castle <cand>/bundle`. The agent's session permission classifier denied running it, so the install is left to the user.

## Review

- Sheet: `artifacts/claude_takeover_20260927/review/homm3_castle_t2_buildings.png`. Columns are painting | before (installed `wall_v4`) | after (`t2_v1`). Rows are rest, sweep_left, sweep_right and sweep_high, plus ten rest zooms.
- **Verdict:**
  - At the sweeps, the relief's smeared depth stripes are gone on the castle, the mage guild, the statue, the griffin towers, the market and the tavern side walls. They are replaced by closed buildings whose visible faces carry the painting and whose hidden faces carry Meshy's texture.
  - At rest the frame is the painting.
  - Weak spots:
    - Small Meshy fragments (crenellation slivers) float above two hill towers at sweep_left.
    - The training grounds' banner wall reads doubled: Meshy banners behind the painted ones.
    - A blacksmith-side grey patch remains, and it reads stronger at rest than in the seed. Darker patches also show at rest on the capitol's lower left and the cathedral's left wall.
    - The seed's terrain streaks are unchanged, by design.
  - The Portal of Glory and the dock stay relief.

## Shared bake (2026-09-30)

The painted-front bake is `tools/homm3_town_scene_meshes/town_full3d_t2_paint.py`, the one T2 bake for all eleven factions. On 2026-09-30 it absorbed the last four copies: `rampart_t2_buildings.stage_split` (Rampart, Dungeon), `inferno_t2_integrate.stage_layer`, `town_full3d_t2_meshy.painted_front` (Necropolis, Bulwark) and `t2_rest_geometry.stage_painted_layer` (Castle, Tower). Where a lane's bake differs by design, the difference is a named parameter of the shared module, set at this lane's call site; no output was changed to force identity.

This lane's bake is `rest_geometry_split` (formerly `t2_rest_geometry.stage_painted_layer`). It is a different method by design, not a parameter of `painted_front`: rest visibility by any px or depth consistency, a frame-line clip, the painting with its background at `tex_k`, the seed's normals with a relative light floor, and `back_fill`. Its knobs are named keyword parameters: `tex_k`, `subdiv_px`, `subdiv_rounds=8`, `light_floor`, `gain_guard=("px", 200)`, `gain_dtype=float32`, `meshy_tex_max` and `resid_min_px`. It reuses the shared `subdivide_screen` (with a `seen` callback), `meshy_gain`, `remainder`, `two_sided` and `seed_residual`. `t2_rest_geometry.py` keeps only the fit pieces (`RectFitter`, `quadrant_fit`).

Restaging the sample layer tbcstvrn with the shared module into a scratch stage gives files byte-identical to this candidate's (`t2_v1`) staged bins, and so did the old code before the fold (`tools/homm3_town_scene_meshes/t2_bake_restage_check.py`; results in `artifacts/town_t2_bake_consolidation/`). The bundle was not rebuilt. Proof tier of this note: generated artifact.

## Keep regen, 2026-10-04 (pass castle_keep_20261004, installed as `zs_v8_bok1`)

User-approved (15 cr from the Castle budget). The keep's original sprite (`tbcscas3`, 322 x 210, `town_scene_refs/homm3_castle/layers/`) ends at x = 478 + 322 = 800, the town canvas's right edge, with the Mage Guild in front of it. The t2_a1 keep was meshed from a nano-banana concept that was told to "complete the frame-cut building", and it invented an extra tower past the frame. The frame clip (`clip_to_painting`) then sliced that tower into white shards beside the right corner tower.

- **Source.** `tbcscas3/t2_b1/complete_tower.py` closes the right corner tower over x 322-329 with a nearest-px mirrored copy of the keep's own left corner tower. It is aligned on the banners (scale 1.6 x 1.22) and changes no original px. There is no AI step and no concept step. `input.png` is the body (rows < 151) on white, LANCZOS-scaled to 896 px in a 1024 square.
- **Mesh.** `gen_castle_keep_b1.py` makes one meshy-t2 smart-topology textured call, task `01a10a29-497d-721d-b994-ec0bbee2fee9`, 15 cr, budget `_budget_castle_keep_20261004.json` (cap 30). Meshy added a sand base plate, so the faces lying entirely within the bottom 0.010 model units were dropped (238 of 3663): `model_noplate.glb` (`GLB["tbcscas3"]` in `castle_t2_buildings.py`).
- **Fit.** Yaw 228, IoU 0.83, F0.5 0.936 (t2_a1: 0.76 / 0.90). The t2_a1 fit is kept in `tbcscas3/fit_t2_a1/`. The wall_v4 seed body was read from its F: copy (`MOVED_TO_F.txt`).
- **Integration.** carve_v2 → zs_v8 changed the keep's Body / BodyM bins by one uniform scale about the rest camera: s = 0.96127457 (least squares rms 1.7e-6; normals, uv, tris and albedo unchanged). The new `rest_geometry_split` bins therefore get the same scale and replace those two bins in a copy of zs_v8. bench_bake `_finish --no-gate` then applies `body-only` exactly as `zs_v8_bo` did. The framing aim is unchanged and no building is out at rest. The catalog restPose is rebound to the installed port-native level67 (70a3658c), as for Cove wf2. Scratch: `V:/olden_port_work/town_bench/castle_keep_regen/` (`stage_keep.py`, `build_candidate.py`, `rebind_restpose.py`).
- **Limit.** The HUD edge sits at the painting's right frame line, and the framing gate allows about 12 frame px past it. The new right tower reaches 32 px past it, so the frame clip still trims the tower's outer side. The banner and the front face are whole, and the shards are gone.
- **Proof tier: installed payload.** Bench full-frame renders at default / sweep_left / sweep_right / loop_096 / loop_264 (states full and min_tbcscas3) were compared with the installed zs_v8_bo. The bench render of the installed version is byte-identical to the earlier evidence. The change is not yet user-checked in game.
