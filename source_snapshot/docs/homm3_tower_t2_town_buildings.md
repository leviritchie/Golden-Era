# Tower town scene: Meshy T2 building meshes (candidate tw_t2)

Brief: `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md` (2026-09-29). Cap `townCaps["homm3_tower"]` = 420 cr.
The first Tower agent's wind-down handoff is `artifacts/meshy_town_scene_meshes/homm3_tower/HANDOFF.md`.

**Proof tier: build target proven. The bundle was built and editor-rendered, and the town-scene contract is OK. See the Status section for install state; nothing is game-visible yet. The installed candidate before this run was `tw_v4`.

## Status

**Not installed.** The coordinator authorised the install (2026-09-29): `python tools/homm3_town_scene_meshes/install_town_scene3d.py tower artifacts/homm3_tower_full3d/candidates/tw_t2/bundle`. The agent's session permission classifier denied running it (2026-09-30), so the install is left to the user. After the install, commit `Heroes of Might & Magic Olden Era Playtest/OfflineUnlockMod/homm3_town_scene_meshes/scene3d/homm3_tower/catalog.json` and raise this doc's tier to installed payload.**

## What it is

- **Candidate:** `artifacts/homm3_tower_full3d/candidates/tw_t2`, seeded from the installed `tw_v4`.
  - Terrain, sky, periphery, near field and FX pieces are the seed's.
  - Only each meshed layer's `Mesh_Body*_<layer>` bins are replaced.
- **Code** (`tools/homm3_town_scene_meshes/`):
  - `tower_t2_meshy.py`: billed generation, cap-checked against the ledger.
  - `tower_t2_stage.py`: `fit`, `yaw-panel` and `stage`.
  - `tower_t2_review.py`: `preview` and `sheet`.
  - `t2_rest_geometry.py`: the faction-neutral fit pieces (`RectFitter`, `quadrant_fit`), shared with Castle's `castle_t2_buildings.py`. The painted-front stage it held is `town_full3d_t2_paint.rest_geometry_split` since 2026-09-30 (see Shared bake).
- **Bins per meshed layer.** Each layer gets the same three lit, two-sided bins as Castle (`docs/homm3_castle_t2_town_buildings.md`):
  - `Mesh_Body_<layer>`: the rest-visible triangles, carrying the de-lit painting.
  - `Mesh_BodyM_<layer>`: the other triangles, carrying the gain-matched Meshy texture.
  - `Mesh_BodyRest_<layer>`: the seed's front triangles over sprite pixels the mesh leaves uncovered.
- **Order.** Tower runs its silhouette warp first. It is a smooth image-plane field that snaps the rest silhouette onto the sprite mask at each vertex's depth, and the warp's final IoU is logged per layer.

## Pipeline decisions (measured)

- **Yaw.**
  - The first agent's fit held yaw within ±45 deg of front-to-camera. Meshy re-poses buildings, so that window excluded the right answer on several layers.
  - `t2_rest_geometry.quadrant_fit` now makes a coarse full-circle pass (15-deg steps, down = 4) and keeps the best F0.5 per 90-deg quadrant. The result is cached in `<layer>/fit_quadrants.json`.
  - The chosen quadrant is refined (±12 deg in 3-deg steps, down = 2), then the stretch pass runs.
  - The silhouette cannot tell a building from its 180-deg turn, since quadrant F0.5 scores sit within about 0.02. The quadrant was therefore picked by eye from `_work/yaw_<layer>.png` panels.
  - `YAW_PICK` in `tower_t2_stage.py` holds these picks: hall_3 180, dw_2 0 (dw_2_2 inherits it), mage_3 180, dw_5 270 and silo 180.
  - Every other layer takes the best coarse F0.5, and those picks were reviewed on the panels.
- **Lean dropped.** The earlier normal lean toward the camera was dropped. The shared painted-front stage de-lights with the seed body's own rest normals (EDT-filled), which is Castle's method.
- **Frame clip and subdivision** work as in Castle: rest-visible triangles are subdivided to ≤ 10 px and cut exactly at the painted rect.

## Layers

31 layers are staged on Meshy geometry: 28 meshes and 3 zero-cost reuses. No layer was reverted to relief.

"Warp IoU" is the silhouette IoU after the warp. "Front" and "Meshy" count the triangles in the painted and Meshy bins.

| layer | mesh from | yaw | fit IoU | F0.5 | warp IoU | tris | front | Meshy | residual | de-lit clipped |
|---|---|---|---|---|---|---|---|---|---|---|
| tbtwhall_3 | tbtwhall_3 | 171 | 0.82 | 0.94 | 0.96 | 46190 | 35775 | 10415 | 1130 | 0.1746 |
| tbtwcstl_2 | tbtwcstl_2 | 162 | 0.75 | 0.93 | 0.84 | 73174 | 61447 | 11727 | 1104 | 0.1764 |
| tbtwmage_4 | tbtwmage_4 | 204 | 0.83 | 0.95 | 0.95 | 27020 | 17608 | 9412 | 319 | 0.0189 |
| tbtwdw_6_2 | tbtwdw_6_2 | 3 | 0.84 | 0.95 | 0.89 | 81543 | 71999 | 9544 | 1844 | 0.1951 |
| tbtwdw_6 | tbtwdw_6 | 132 | 0.86 | 0.95 | 0.88 | 48915 | 38340 | 10575 | 1976 | 0.1442 |
| tbtwhall_2 | tbtwhall_2 | 0 | 0.91 | 0.98 | 0.96 | 32608 | 25582 | 7026 | 553 | 0.1288 |
| tbtwblak | tbtwblak | 207 | 0.90 | 0.96 | 0.95 | 35017 | 24837 | 10180 | 470 | 0.0 |
| tbtwdw_2 | tbtwdw_2 | 303 | 0.80 | 0.94 | 0.95 | 26647 | 16531 | 10116 | 201 | 0.2256 |
| tbtwmage_3 | tbtwmage_3 | 207 | 0.58 | 0.81 | 0.86 | 23718 | 16013 | 7705 | 952 | 0.0229 |
| tbtwmage_2 | tbtwmage_2 | 201 | 0.85 | 0.92 | 0.96 | 22026 | 12972 | 9054 | 43 | 0.0139 |
| tbtwmage | tbtwmage | 204 | 0.83 | 0.94 | 0.95 | 19738 | 12241 | 7497 | 431 | 0.0292 |
| tbtwcstl | tbtwcstl | 156 | 0.79 | 0.93 | 0.97 | 46724 | 35935 | 10789 | 475 | 0.1028 |
| tbtwdw_5_2 | tbtwdw_5_2 | 240 | 0.84 | 0.95 | 0.97 | 27322 | 20825 | 6497 | 0 | 0.0 |
| tbtwdw_5 | tbtwdw_5 | 243 | 0.90 | 0.96 | 0.97 | 15976 | 8297 | 7679 | 0 | 0.0 |
| tbtwdw_4_2 | tbtwdw_4_2 | 57 | 0.88 | 0.97 | 0.97 | 18936 | 11089 | 7847 | 0 | 0.0 |
| tbtwdw_4 | tbtwdw_4 | 342 | 0.90 | 0.97 | 0.96 | 25245 | 14870 | 10375 | 222 | 0.0 |
| tbtwtvrn | tbtwtvrn | 132 | 0.89 | 0.97 | 0.97 | 23108 | 12523 | 10585 | 77 | 0.0 |
| tbtwmark | tbtwmark | 216 | 0.76 | 0.93 | 0.94 | 31072 | 20436 | 10636 | 349 | 0.0 |
| tbtwsilo | tbtwsilo | 150 | 0.91 | 0.97 | 0.99 | 13914 | 8998 | 4916 | 0 | 0.0 |
| tbtwdw_3_2 | tbtwdw_3_2 | 126 | 0.88 | 0.95 | 0.93 | 16765 | 10294 | 6471 | 67 | 0.0 |
| tbtwdw_3 | tbtwdw_3 | 288 | 0.78 | 0.94 | 0.86 | 16962 | 10316 | 6646 | 688 | 0.0 |
| tbtwdw_1_2 | tbtwdw_1_2 | 318 | 0.62 | 0.85 | 0.83 | 15680 | 10202 | 5478 | 811 | 0.2413 |
| tbtwdw_1 | tbtwdw_1 | 0 | 0.62 | 0.87 | 0.86 | 14992 | 9371 | 5621 | 517 | 0.2493 |
| tbtwdw_0_2 | tbtwdw_0_2 | 210 | 0.70 | 0.90 | 0.76 | 21616 | 16193 | 5423 | 955 | 0.0 |
| tbtwdw_0 | tbtwdw_0 | 150 | 0.75 | 0.92 | 0.89 | 16657 | 11661 | 4996 | 283 | 0.0 |
| tbtwspec | tbtwspec | 207 | 0.82 | 0.94 | 0.95 | 23574 | 12881 | 10693 | 105 | 0.0016 |
| tbtwholy | tbtwholy | 354 | 0.80 | 0.91 | 0.87 | 18720 | 13240 | 5480 | 1099 | 0.0002 |
| tbtwext2 | tbtwext2 | 21 | 0.83 | 0.93 | 0.91 | 18046 | 9512 | 8534 | 581 | 0.0 |
| tbtwcstl_3 | tbtwcstl_2 (reuse) | 189 | 0.71 | 0.91 | 0.82 | 85123 | 73155 | 11968 | 1577 | 0.1638 |
| tbtwhall_4 | tbtwhall_3 (reuse) | 129 | 0.69 | 0.90 | 0.72 | 53893 | 43400 | 10493 | 4149 | 0.1907 |
| tbtwdw_2_2 | tbtwdw_2 (reuse) | 309 | 0.78 | 0.93 | 0.94 | 27265 | 16730 | 10535 | 292 | 0.2132 |

- **Reuses (no spend):** each is refitted to its own sprite.
  - cstl_3 ← cstl_2
  - hall_4 ← hall_3
  - dw_2_2 ← dw_2. The upgrade only adds the animated chimneys.
- **Skipped:** tbtwhall (village hall) keeps the seed. It is painted into the background image, so the lane's mask is only a roof strip, and a mesh would draw it twice.
- **Reverts to relief:** none. Each suspect was judged by eye at rest, sweep_left, sweep_right and sweep_high:
  - ext2, which became a closed circular wall.
  - holy, which has a lens-like disc.
  - dw_3_2, which has a stray board.
  - mage_3, which has the weakest fit (IoU 0.585).
  - dw_1 and dw_1_2 (IoU 0.63).

  None is fragmented, a flat slab or missing its main feature. The hidden faces of ext2 and holy are behind other geometry at every sweep. At rest the painted front carries mage_3, and the warp closes its silhouette.

## Spend log (ledger `artifacts/meshy_town_scene_meshes/_ledger.jsonl`, faction `homm3_tower`)

| ts (2026-09-29) | layer | kind | cr | task id |
|---|---|---|---|---|
| 18:27:34 | tbtwhall_3 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-b043-7080-8703-721c2625c81b |
| 18:27:35 | tbtwcstl_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-b4f2-71b7-b72f-b318bd9f2019 |
| 18:27:36 | tbtwmage_4 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-b93f-7492-af43-74c5586addcb |
| 18:27:37 | tbtwdw_6_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-bcf7-77e7-b23f-c62c4f1b2646 |
| 18:27:38 | tbtwdw_6 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-c10e-71fd-9636-c44e549b3157 |
| 18:27:39 | tbtwhall_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-c43a-74e9-95a8-1ad94f87c419 |
| 18:27:40 | tbtwblak | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-c7a2-7611-aa9a-5b948e0db93f |
| 18:27:41 | tbtwdw_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-cc4a-7142-b2d0-66bfc1697bca |
| 18:31:06 | tbtwmage_3 | image-to-3d meshy-t2 textured | 15 | 01a0ef81-ec0d-7667-b94d-f63cda038284 |
| 18:31:24 | tbtwmage_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef82-347c-74d1-8b98-23c81bf1ac0e |
| 18:31:45 | tbtwmage | image-to-3d meshy-t2 textured | 15 | 01a0ef82-83da-722d-8cf0-f921ef756cc3 |
| 18:31:46 | tbtwcstl | image-to-3d meshy-t2 textured | 15 | 01a0ef82-8864-732c-8db1-63b20cb542c7 |
| 18:31:47 | tbtwdw_5_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef82-8c9b-71f9-9600-9e6fdccdb0c3 |
| 18:32:07 | tbtwdw_5 | image-to-3d meshy-t2 textured | 15 | 01a0ef82-da4c-75d2-9c38-61cd81375356 |
| 18:32:08 | tbtwdw_4_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef82-df6e-762e-9ba5-67929b3eca67 |
| 18:32:27 | tbtwdw_4 | image-to-3d meshy-t2 textured | 15 | 01a0ef83-284a-704b-a781-df02f0b3973a |
| 18:33:20 | tbtwtvrn | image-to-3d meshy-t2 textured | 15 | 01a0ef83-f870-74ed-bdc7-f4255cafce3e |
| 18:33:21 | tbtwmark | image-to-3d meshy-t2 textured | 15 | 01a0ef83-fd1b-77b5-9021-4a28a374690b |
| 18:33:41 | tbtwsilo | image-to-3d meshy-t2 textured | 15 | 01a0ef84-4bbe-759b-bac3-a52804f953da |
| 18:33:42 | tbtwdw_3_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef84-4f9d-75da-a807-0afd3b1f335b |
| 18:33:43 | tbtwdw_3 | image-to-3d meshy-t2 textured | 15 | 01a0ef84-53b4-75b1-a246-9be7cc4feb4b |
| 18:34:02 | tbtwdw_1_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef84-9e2e-74bb-869d-ef3efb6ac1a8 |
| 18:34:04 | tbtwdw_1 | image-to-3d meshy-t2 textured | 15 | 01a0ef84-a238-7499-8563-ec15dbee0077 |
| 18:34:56 | tbtwdw_0_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef85-6f76-752b-a225-b5e4f451d568 |
| 18:35:50 | tbtwdw_0 | image-to-3d meshy-t2 textured | 15 | 01a0ef86-405d-74be-b57c-53a35ab3f45c |
| 18:35:51 | tbtwspec | image-to-3d meshy-t2 textured | 15 | 01a0ef86-45bf-7202-9728-ede1ee1c21ee |
| 18:36:13 | tbtwholy | image-to-3d meshy-t2 textured | 15 | 01a0ef86-98d7-7351-bbc4-f3dfa4a7cff7 |
| 18:36:13 | tbtwext2 | image-to-3d meshy-t2 textured | 15 | 01a0ef86-9ef5-7324-b2db-d5e55c248122 |

**Total: 420 of 420 cr** (28 meshes at 15 cr). No contingency was claimed.

A first create attempt used `target_polycount=30000` and got HTTP 400 before any task was made, so it was not billed.

## Gates

- Stage: `town_full3d_framing` passed for every layer, after the frame clip.
- `stronghold_full3d_scene.py cull`: see-through 0 px. This is report-only, because Tower has no baseline row.
- `bundle`: `artifacts/homm3_tower_full3d/candidates/tw_t2/bundle/homm3_town_scene3d_tower`, 332355901 bytes, sha256 `3593a4bc37117668f7cbe6197dab4531f4e0635e453073f5dd13d10b8705b837`. It was built through unitylock, inside a cpuslot.
- `render`: RenderStates rc 0 (`candidates/tw_t2/renders/`).
- `validate`: `town-scene3d-contract: OK homm3_tower layers=32 reachable=32 unused=0 depths=0 bundle=present flag=off (candidate) restPose=installed-native-verified framing=zoom1.22/pan0.5 full3d=on ... panVoid=0 panNeg16x9=0.018`.
- V: was at 98-99% full during this run. Unity's 20 GB free-space guard refused two bundle and render attempts, and they were retried after space freed up. The gate was not changed.

## Review

- **Sheet:** `artifacts/claude_takeover_20260927/review/homm3_tower_t2_buildings.png`.
  - Columns: painting | before (installed `tw_v4`) | after (`tw_t2`).
  - Rows: rest, sweep_left, sweep_right and sweep_high, plus rest zooms.
- **Verdict:**
  - At the sweeps, `tw_v4`'s smeared relief stripes are replaced by closed buildings. Those stripes were worst on the cloud castle, the capitol's side, the golem factory, the dwellings row and the sky ship. Their visible faces carry the painting and their hidden faces carry Meshy's texture.
  - The rest frame is the painting.
  - Weak spots:
    - Small Meshy slivers float beside the cloud castle's spires at sweep_left and sweep_right.
    - The dwellings row's roofs are Meshy re-interpretations wherever the sweep shows their back.
    - The seed's snow and terrain streaks are unchanged, by design (terrain and sky are out of scope).

## Shared bake (2026-09-30)

The painted-front bake is `tools/homm3_town_scene_meshes/town_full3d_t2_paint.py`, the one T2 bake for all eleven factions. On 2026-09-30 it absorbed the last four copies: `rampart_t2_buildings.stage_split` (Rampart, Dungeon), `inferno_t2_integrate.stage_layer`, `town_full3d_t2_meshy.painted_front` (Necropolis, Bulwark) and `t2_rest_geometry.stage_painted_layer` (Castle, Tower). Where a lane's bake differs by design, the difference is a named parameter of the shared module, set at this lane's call site; no output was changed to force identity.

This lane's bake is `rest_geometry_split` (formerly `t2_rest_geometry.stage_painted_layer`). It is a different method by design, not a parameter of `painted_front`: rest visibility by any px or depth consistency, a frame-line clip, the painting with its background at `tex_k`, the seed's normals with a relative light floor, and `back_fill`. Its knobs are named keyword parameters: `tex_k`, `subdiv_px`, `subdiv_rounds=8`, `light_floor`, `gain_guard=("px", 200)`, `gain_dtype=float32`, `meshy_tex_max` and `resid_min_px`. It reuses the shared `subdivide_screen` (with a `seen` callback), `meshy_gain`, `remainder`, `two_sided` and `seed_residual`. `t2_rest_geometry.py` keeps only the fit pieces (`RectFitter`, `quadrant_fit`).

Restaging the sample layer tbtwtvrn with the shared module into a scratch stage gives files byte-identical to this candidate's (`tw_t2`) staged bins, and so did the old code before the fold (`tools/homm3_town_scene_meshes/t2_bake_restage_check.py`; results in `artifacts/town_t2_bake_consolidation/`). The bundle was not rebuilt. Proof tier of this note: generated artifact.
