# homm3_rampart: Meshy T2 town buildings (candidate t2_v1)

Proof tier: **generated artifact + build target (Unity bundle) + editor render**, validator OK. **Not installed**:
the install step (`install_town_scene3d.py rampart .../t2_v1/bundle`) was denied by the session's permission gate
and was not retried. There is no startup, runtime or user-visible proof.

- Brief: `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md`.
- Candidate: `artifacts/homm3_rampart_full3d/candidates/t2_v1`, seeded from the installed `wall_v4`.
- Terrain and sky are unchanged from `wall_v4`.
- Scripts:
  - `tools/homm3_town_scene_meshes/rampart_t2_generate.py` handles Meshy generation and the ledger.
  - `tools/homm3_town_scene_meshes/rampart_t2_buildings.py` runs the steps fit, stage, revert, fx, finish and preview.

## Rule (user decision 2026-09-29)

- Every layer uses its Meshy body with the painted front.
- The painted relief is kept only for a genuinely broken mesh: fragments, a flat slab, or the main feature missing.
  This is judged by eye at the sweeps.
- Rest dE76 against the painting is a diagnostic only, never a revert gate.

## Method (`rampart_t2_buildings.py stage`)

1. **Fit.**
   - The mesh is registered to its sprite under the rest camera (yaw, scale, ground contact, x/y stretch).
   - `depth_slide` then scales the body about the camera until the staged terrain no longer hides it.
   - The slide keeps the rest projection unchanged. The castles need it: cas3 s=0.563, cas2 0.581, cstl 0.825.
2. **Clip to the painting's frame.**
   - Triangles with a corner outside the painted rect at rest are dropped.
   - These are the parts of a sprite that the frame edge cuts off, such as dw_2's invented tower right of x=1440.
   - The lane's framing gate refused those layers until this clip was added.
3. **Screen-space split.**
   - Every face the rest camera draws is midpoint-split until its projected edges are at most 8 px (`SUBDIV_PX`).
   - Without the split, whole Meshy faces straddle occlusion edges. The hall's rest dE was 6.3 without the split,
     2.36 with it.
   - 4 px gave the same hall dE at 2.3x the triangles, so 8 px was used.
4. **Painted front (`Mesh_Body_<layer>`).**
   - A face counts as seen if it owns at least 60% of its projected SUPER-sampled px, or its centroid or any corner
     is at the rest z-buffer (0.5% slack).
   - Seen faces take the sprite by rest screen position: uv is the rest px in a 2x crop.
   - The texture is de-lit through the lane rig at the smooth view normal (vertex to rest camera).
   - The painted part is shaded with that same view normal. The painting already carries its shading; de-lighting
     through creased Meshy normals left every crease's lighting jump in the texels (hall rest dE 5.3 -> 3.0).
   - Faces seen from their back are re-wound so that the drawn copy carries the view normal.
5. **Meshy remainder (`Mesh_BodyM_<layer>`).**
   - Every other face keeps its Meshy texture.
   - The texture is per-channel gain-matched (clamped 0.5-2) to the de-lit painting.
6. **Residual (`Mesh_BodyRest_<layer>`).**
   - Sprite px the mesh leaves uncovered at rest take the seed relief's front triangles.
7. All bins are two-sided, because the game uses Cull Back.
8. **fx (`rampart_t2_buildings.py fx`).**
   - The seed's Fx_Water meshes and particle emitters (flames, glows) were placed at relief depth.
   - Each is re-derived from the seed and slid along its rest ray onto the T2 surface, 0.2% in front for water and
     1% for particles. Particle scale follows the slide, so the rest frame is unchanged.
   - Water slides: ext0 median 0.953, spec 0.967, dw_3 0.882, dw_3_2 0.978.
   - Particle slides: dw_0 flames 0.92-0.93, dw_6 glow 0.936, ext0 glow 0.943.
   - All water vertices lie over the body (coveredShare 1.0).

## Per-layer verdict (T2 = Meshy body staged; relief = seed wall_v4 body kept)

The rest dE76 columns are the isolated offline preview (env plus that one layer), against the sprite composited at
x1.8 over the eroded sprite mask. They were measured with the 4 px split; hall and hal3 were re-measured at 8 px.
They are diagnostic only.

| layer | staged | fit IoU | rest dE seed / T2 | note |
|---|---|---|---|---|
| tbrmhall | T2 | 0.846 | 1.51 / 2.36 | sweeps: solid deck and roof |
| tbrmhal2 | T2 | 0.815 | 3.54 / 4.36 | |
| tbrmhal3 | T2 | 0.893 | 5.30 / 4.11 | seed right wing stretches at sweep_left; T2 does not |
| tbrmcstl | T2 | 0.659 | 3.06 / 3.49 | seed pole sheets stretch at sweep_left |
| tbrmcas2 | T2 | 0.648 | 3.90 / 4.42 | as cstl |
| tbrmcas3 | T2 | 0.680 | 4.03 / 4.44 | as cstl |
| tbrmmage | T2 | 0.802 | 2.90 / 4.51 | |
| tbrmmag2 | T2 | 0.786 | 5.39 / 3.50 | |
| tbrmmag3 | T2 | 0.769 | 5.33 / 5.19 | |
| tbrmmag4 | T2 | 0.693 | 2.56 / 1.98 | |
| tbrmtvrn | T2 | 0.819 | 2.65 / 3.52 | |
| tbrmsilo | T2 | 0.769 | 2.78 / 3.07 | |
| tbrmspec | T2 | 0.901 | 10.65 / 4.89 | seed water is a rubber sheet at the sweeps; T2 pond holds |
| tbrmext0 | T2 | 0.878 | 10.59 / 4.93 | as spec |
| tbrmholy | T2 | 0.471 | 2.28 / 3.09 | |
| tbrmdw_0 | T2 | 0.776 | 3.35 / 2.14 | a small ruined porch piece at sweep_left; house body solid |
| tbrmdw_2 | T2 | 0.889 | 3.40 / 2.20 | tower past the frame clipped |
| tbrmdw_2_2 | T2 | 0.801 | 2.63 / 2.15 | as dw_2 |
| tbrmdw_3 | T2 | 0.568 | 3.96 / 4.42 | FIT_TUNE dropRMin 0.3 removes a white basin |
| tbrmdw_3_2 | T2 | 0.609 | 4.03 / 4.47 | |
| tbrmdw_4 | T2 | 0.546 | 3.43 / 3.38 | |
| tbrmdw_4_2 | T2 | 0.528 | 2.85 / 2.70 | |
| tbrmdw_5 | T2 | 0.703 | 2.14 / 2.76 | |
| tbrmdw_5_2 | T2 (dw_5 mesh) | 0.705 | 2.17 / 2.40 | sprite = dw_5 + two lanterns; own paint |
| tbrmdw_6 | T2 (concept c1) | 0.642 | 2.63 / 3.75 | a1 was a flat sheet; concept retry |
| tbrmdw_6_2 | T2 (concept c1) | 0.544 | 2.76 / 2.46 | a1 was loose strips; concept retry; the thin painted stream on the ridge is mostly lost |
| tbrmdw_1 | **relief** | | 1.71 / 2.82 | broken: the mound's left side is a flat bright Meshy ground slab at sweep_left |
| tbrmdw_1_2 | **relief** | | 2.04 / 1.88 | broken: the same slab |
| tbrmhrd1 | **relief** | | 1.69 / 1.89 | broken: a flat bright ground slab beside the mound at sweep_left |
| tbrmdw_0_2 | **relief** | | 3.49 / 3.08 | broken: a flat green ground slab under the porch at sweep_high / sweep_left |
| tbrmmark | **relief** | | 4.91 / 3.03 | broken: the stall comes apart into a dark box and loose fragments at every sweep |
| tbrmblak | **relief** | | | main feature missing: the sprite is a forest clump with a small hut, and T2 modelled the hut alone (meshed, 15 cr, unused) |

- An earlier pass reverted 22 layers under a stricter "T2 must beat the seed" rule. All 22 were re-judged under the
  2026-09-29 rule, and 17 are back on T2.
- A cut of faces wholly outside the sprite was tried on the five broken layers, dw_0 and dw_2. It removed only 3-39
  faces and fixed none of them, because the slabs straddle the sprite outline, so it is not shipped.

Unity editor render rest dE76 (`t2_town_review.py` json beside the sheet, full state, before wall_v4 / after t2_v1):
hal3 5.16 / 4.24, cas3 3.31 / 3.32, mag4 2.81 / 2.98, tvrn 4.25 / 4.06, silo 3.56 / 3.47, ext0 10.51 / 5.66,
holy 4.24 / 4.40, dw_2_2 3.74 / 2.92, dw_3_2 4.15 / 4.42, dw_4_2 3.44 / 3.43, dw_5_2 3.28 / 3.45,
dw_6_2 10.54 / 4.74.

Skipped, unreachable: none. The validator reports reachable=32 of 32 layers.

## Gates

| gate | result |
|---|---|
| Framing | pass, after the painted-rect clip; before the clip dw_0, dw_2, dw_2_2, dw_6_2, ext0, hal3 and spec were out of the visible region at rest |
| See-through (Cull Back, no worse than baseline seam_v1 at every pose) | pass: total 2274 px, worse = {} |
| Bundle | built through cpuslot + unitylock (memgate / launch_guard OK), rc 0: `artifacts/homm3_rampart_full3d/candidates/t2_v1/bundle/homm3_town_scene3d_rampart`, 271,038,409 bytes (wall_v4: 100,528,130), sha256 `23ebf9e9958e893f1048cd92854eb6ca70a4242807937e90f0698b70b1743955` |
| Editor render | `RenderStates` rc 0 |
| Validator | `town-scene3d-contract: OK homm3_rampart layers=32 reachable=32 unused=0 ... panVoid=0` |
| Install | **not done**: permission denied |

- The bundle is 2.7x the size of wall_v4.
- The 26 T2 layers carry 764,358 painted-front triangles and 187,561 Meshy-remainder triangles, all two-sided.
- Hall, hal2 and hal3 dominate (78k-129k painted triangles each).
- Runtime frame time and memory with this bundle are unmeasured.

## Review

- Sheet: `artifacts/claude_takeover_20260927/review/homm3_rampart_t2_buildings.png`. Its columns are painting |
  before wall_v4 | after t2_v1, at rest, sweep_left, sweep_right and sweep_high. Per-building zooms follow: cas3,
  hal3, mag4, tvrn, spec, ext0, dw_2_2, dw_3_2, dw_4_2, dw_6_2, holy and silo. These are Unity editor renders.
- **Verdict.** At the sweeps T2 is the better town:
  - The pond (spec/ext0) stays a pond, where the seed's water and rocks stretch into sheets.
  - The hall cluster's right wing and the castle's poles no longer smear.
  - Everything else holds its shape at least as well as the relief.
- At rest the town still reads as the painting. The painted front reproduces it up to rasterisation. Remaining
  error sits on thin rails and on edges where Meshy shells z-fight.
- Weak spots:
  - The Meshy remainder colour on faces hidden at rest is only gain-matched.
  - dw_6_2 loses most of its thin painted stream.
  - dw_0 shows a small ruined porch piece at sweep_left.
  - The bundle size (above).

## Spend (shared ledger `artifacts/meshy_town_scene_meshes/_ledger.jsonl`, faction homm3_rampart)

- The cap is 588 (`_budget_t2_20260929.json` townCaps). **Spent 507**: 33 image-to-3d calls at 15 credits plus 2
  image-to-image concept calls at 6 credits.
- No contingency was claimed.
- Deviation: the dw_6 and dw_6_2 concept retries (42 credits) were paid from cap headroom, not from a claim line.
- The two superseded a1 outputs (dw_6, dw_6_2) were deleted after the c1 retries replaced them.

| time | layer | kind | credits | taskId |
|---|---|---|---|---|
| 2026-09-29T18:24:40 | tbrmcstl | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-08eb-7683-98a3-4ff1c8794fa1 |
| 2026-09-29T18:24:41 | tbrmcas2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-0d13-7671-9489-e919e39de932 |
| 2026-09-29T18:24:42 | tbrmcas3 | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-110b-7154-8ab9-90e71b75e632 |
| 2026-09-29T18:24:43 | tbrmhal2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-150c-7587-b600-508eb7bd6715 |
| 2026-09-29T18:24:44 | tbrmhall | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-197d-7014-ab08-e0766c312f0a |
| 2026-09-29T18:24:45 | tbrmmag2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-1de2-7289-ab0c-d3ea80081db9 |
| 2026-09-29T18:24:47 | tbrmmage | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-22a3-7348-ad0c-1d982ed47689 |
| 2026-09-29T18:24:48 | tbrmhal3 | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-275b-7784-9ca3-3822daf3e86e |
| 2026-09-29T18:25:14 | tbrmmag3 | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-8750-74d5-a5a9-86d584727b09 |
| 2026-09-29T18:25:15 | tbrmmag4 | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-90d1-7205-9d64-0f13ee25358a |
| 2026-09-29T18:25:16 | tbrmtvrn | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-9547-7019-99bb-0d6244669795 |
| 2026-09-29T18:25:30 | tbrmmark | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-cbee-7209-a330-71f6e1b53a64 |
| 2026-09-29T18:25:32 | tbrmsilo | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-d433-7034-9a10-4abbb7853427 |
| 2026-09-29T18:25:33 | tbrmblak | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-d875-7515-8894-78d2ad681089 |
| 2026-09-29T18:25:34 | tbrmspec | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-dcf7-77a9-b0e6-6aa565294164 |
| 2026-09-29T18:25:36 | tbrmext0 | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-e2a5-73dd-ad82-ad72940b427d |
| 2026-09-29T18:25:48 | tbrmhrd1 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-13b9-765d-a0da-6c3c804c9c04 |
| 2026-09-29T18:26:02 | tbrmholy | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-46af-73c0-929a-668423030d03 |
| 2026-09-29T18:26:03 | tbrmdw_0 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-4e4a-73d4-865e-f0909d25b5b5 |
| 2026-09-29T18:26:04 | tbrmdw_0_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-52b9-7517-8e28-f28a912957cb |
| 2026-09-29T18:26:20 | tbrmdw_1 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-8e36-723f-bbc1-60a2392f295e |
| 2026-09-29T18:26:21 | tbrmdw_1_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-9258-7216-82d5-65af5e251b9d |
| 2026-09-29T18:26:22 | tbrmdw_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-9792-7609-a21a-cd01c3d9a621 |
| 2026-09-29T18:26:23 | tbrmdw_2_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-9ce7-714b-b66f-0b0329654c91 |
| 2026-09-29T18:26:36 | tbrmdw_3 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-ce42-77e7-95ab-c75b5fdccba6 |
| 2026-09-29T18:26:50 | tbrmdw_3_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-0478-72c3-a4b8-ea0c96d9b451 |
| 2026-09-29T18:26:51 | tbrmdw_4 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-08dd-742a-b70a-fc4aec89ecec |
| 2026-09-29T18:26:52 | tbrmdw_4_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-0dba-7663-8fdd-99d603f2e1a5 |
| 2026-09-29T18:27:38 | tbrmdw_5 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-bf42-72ed-bd7e-ab8b3cf25776 |
| 2026-09-29T18:27:39 | tbrmdw_6 | image-to-3d meshy-t2 textured (a1, superseded) | 15 | 01a0ef7e-c391-7347-b770-fae988ef75c6 |
| 2026-09-29T18:27:40 | tbrmdw_6_2 | image-to-3d meshy-t2 textured (a1, superseded) | 15 | 01a0ef7e-c8a2-75ab-ab7d-7ba61b25457c |
| 2026-09-29T18:40:38 | tbrmdw_6 | image-to-image concept | 6 | 01a0ef8a-a918-76cf-8386-0c54706ccc53 |
| 2026-09-29T18:40:39 | tbrmdw_6_2 | image-to-image concept | 6 | 01a0ef8a-acd4-720d-8e75-0dec641326b2 |
| 2026-09-29T18:40:50 | tbrmdw_6 | image-to-3d meshy-t2 textured (c1) | 15 | 01a0ef8a-d6c5-71ae-910b-9cdf911227fb |
| 2026-09-29T18:41:02 | tbrmdw_6_2 | image-to-3d meshy-t2 textured (c1) | 15 | 01a0ef8b-0283-7261-869e-825d27773bb4 |

## Reproduce

Run every heavy step through `python artifacts/claude_takeover_20260927/cpuslot.py -- ...`, with
`TOWN_FULL3D_FACTION=rampart TOWN_FULL3D_CANDIDATE=t2_v1`.

```
python tools/homm3_town_scene_meshes/rampart_t2_generate.py spent
python tools/homm3_town_scene_meshes/rampart_t2_buildings.py fit
python tools/homm3_town_scene_meshes/rampart_t2_buildings.py stage     # every layer not in BROKEN
python tools/homm3_town_scene_meshes/rampart_t2_buildings.py revert    # BROKEN layers back to wall_v4's relief
python tools/homm3_town_scene_meshes/rampart_t2_buildings.py fx        # fx onto the T2 bodies
python tools/homm3_town_scene_meshes/rampart_t2_buildings.py finish    # closing walls, catalog, see-through gate
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py bundle
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py render
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py validate
python tools/homm3_town_scene_meshes/t2_town_review.py --before wall_v4 \
    --zooms tbrmcas3,tbrmhal3,tbrmmag4,tbrmtvrn,tbrmspec,tbrmext0,tbrmdw_2_2,tbrmdw_3_2,tbrmdw_4_2,tbrmdw_6_2,tbrmholy,tbrmsilo \
    --out artifacts/claude_takeover_20260927/review/homm3_rampart_t2_buildings.png
# install (needs permission; not run):
python tools/homm3_town_scene_meshes/install_town_scene3d.py rampart artifacts/homm3_rampart_full3d/candidates/t2_v1/bundle
```

## Shared bake (2026-09-30)

The painted-front bake is `tools/homm3_town_scene_meshes/town_full3d_t2_paint.py`, the one T2 bake for all eleven factions. On 2026-09-30 it absorbed the last four copies: `rampart_t2_buildings.stage_split` (Rampart, Dungeon), `inferno_t2_integrate.stage_layer`, `town_full3d_t2_meshy.painted_front` (Necropolis, Bulwark) and `t2_rest_geometry.stage_painted_layer` (Castle, Tower). Where a lane's bake differs by design, the difference is a named parameter of the shared module, set at this lane's call site; no output was changed to force identity.

This lane's values (`rampart_t2_buildings.stage_split` / `stage_layer`): `subdivide_screen(max_px=8)`; the `sprite_fill` mask is `native_mask`; `painted_split(zbuf=...)` reuses the rest z-buffer that `lean_normals` already rendered; `gain_guard=("px", 200)` and `gain_dtype=float32` for the Meshy gain; `preview=False`. The seed residual (`Mesh_BodyRest_`) uses the shared `seed_residual`.

Restaging the sample layer tbrmtvrn with the shared module into a scratch stage gives files byte-identical to this candidate's (`t2_v1`) staged bins, and so did the old code before the fold (`tools/homm3_town_scene_meshes/t2_bake_restage_check.py`; results in `artifacts/town_t2_bake_consolidation/`). The bundle was not rebuilt. Proof tier of this note: generated artifact.
