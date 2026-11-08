# Inferno town: Meshy T2 buildings (2026-09-29)

Operational brief: `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md`. Faction cap `townCaps["homm3_inferno"]` =
576 credits (`_budget_t2_20260929.json`).

- Tools: `tools/homm3_town_scene_meshes/inferno_t2_buildings.py` (plan / prep / concept / create / poll / fit / stage /
  review / select / sheet / spent; ledger guard) and `inferno_t2_integrate.py` (fit, clip, painted-front bake, stage,
  per-layer review, select, review sheet).
- Scratch (not committed): `artifacts/meshy_town_scene_meshes/homm3_inferno/<layer>/` (input.png, t2/model.glb,
  concept/, placement_t2.json + overlay).
- Candidate: `artifacts/homm3_inferno_full3d/candidates/t2_v1` (seeded from `fix_v2`, the installed candidate; terrain,
  sky, FX, framing untouched).

## Proof tier

**Generated artifact, bundle built, editor-rendered offline. Not installed (the user approves installs); startup,
runtime and in-game visuals are unproven.** Gates on `t2_v1` (second pass, 2026-09-29):
- `validate_town_scene3d_contract` OK (bundle present, reachable 32/32);
- see-through (Cull Back) no worse than `fix_v2` at every pose (`worse {}`, 23692 px total);
- `town_full3d_framing`: every building inside the visible region at rest.

Bundle: `artifacts/homm3_inferno_full3d/candidates/t2_v1/bundle/homm3_town_scene3d_inferno`, 276,790,686 bytes, sha256
`f2b2c6d4f8e57ce3f51652b016b27c45a2c0b8184799f442cb42f8834ff3ae3b`, built through unitylock. It is 2.9x the first
pass's 96.5 MB, because each of the 25 T2 layers carries a painted-front texture plus Meshy's own texture (up to 2048).

Review:
- `artifacts/claude_takeover_20260927/review/homm3_inferno_t2_buildings.png`: painting | fix_v2 | t2_v1, editor renders at rest and the three sweeps;
- `..._zooms.png`: the full-state T2 buildings;
- per-layer offline previews: environment plus one layer, seed vs T2, Cull Back as the game draws them. They are in
  `artifacts/meshy_town_scene_meshes/homm3_inferno/_layer_review/` (scratch) and are what the revert decisions were judged on.

## Method

1. **Input.** Each layer's static sprite (alpha, minus the magenta key, minus background-identical components, minus
   the forge's chimney sky block, closed and hole-filled, inpainted edge), scaled to 1024 px on white, LANCZOS: the
   Castle price-check recipe. The two town-hall sprites are cut by the frame's left edge, so they went through one
   concept step each (image-to-image, "complete the hall to the left, white background").
2. **Mesh.** `image-to-3d`, `meshy-t2`, `smart-topology`, textured, no texture prompt: 15 cr each.
3. **Register.** `fit_mesh_to_sprite.Fitter` under the native rest camera on the calibrated terrain depth: yaw within
   +-60 deg of "model front faces the camera", scale and ground contact, F-beta 0.5 against the layer's native mask;
   optional vertical stretch kept only when F-beta improves by > 0.005; base sunk 2 % of the height.
4. **Clip.** The placed mesh is cut exactly (Sutherland-Hodgman, cut edges interpolated) to the rest-camera wedge of
   its sprite's horizontal extent. Without it the concept-completed hall runs past the frame and Meshy back walls stick
   out beside the sprite, which moves the `town_full3d_framing` aim and puts the blacksmith, the mage guilds and the
   halls outside the visible region at rest (the gate failed on the first staging; it was not loosened).
5. **Texture: the painted-front bake** (`town_full3d_t2_paint.painted_front`, the Rampart lane's method; see Shared bake).
   - Split: triangles the rest camera draws are midpoint-split until no projected edge is longer than 4 px, so the
     painted / Meshy split follows occlusion edges.
   - Front: a triangle that owns >= 60 % of its rest px (at 2x the frame), or whose centroid or a corner passes the
     rest depth test, goes into `Mesh_Body_<layer>`. It is wound toward the rest camera and carries the smooth
     camera-facing normal (vertex -> rest eye).
   - Painting: the front takes the sprite by screen position at 2x the frame, de-lit by the Hex/Lit irradiance of that
     normal. The rest frame is the painting up to rasterisation.
   - Everything else goes into `Mesh_BodyM_<layer>`: Meshy's uvs and texture with a per-channel linear gain (clamped
     0.5-2) onto the de-lit painting. Corner normals are welded where they agree with the face (dot >= 0.5), else the
     face normal.
   - Both pieces are two-sided, because Meshy soups have no consistent outside and the game culls back faces.
   - It supersedes the first pass's per-texel re-bake into Meshy's uvs plus a projection set with normals leant 0.6.
     With the same meshes, rest dE76 moves from seed +0.4..+5.8 to seed -1.1..+1.04 (table below).
6. **Skirt.** The seed's triangles that are frontmost (seed rest id buffer) at painted px the mesh leaves uncovered
   (grown 2 px), as `Mesh_Body_<layer>_skirt`: the lava stream, gold floor, pit rims, debris and the parts Meshy did
   not model.
7. **Select.** User decision 2026-09-29: Meshy geometry is the default, because functional geometry stays consistent at the
   sweeps where the relief warps. A layer goes back to the seed's relief (bins and rows verbatim) only when its mesh is
   genuinely broken at the sweeps. That is judged by eye on the per-layer review (`inferno_t2_buildings.py review`) and
   listed in `BROKEN` with the reason. Rest dE76 against the painting is recorded as a diagnostic only.

## Layers

**25 layers ship their Meshy body; 4 are reverted to the relief as broken; 3 are skipped.** Rest dE76 is the layer
alone at the rest camera against the HoMM3 rest picture, inside the native mask (`rest_de`: Cull Back, bilinear albedo x
Hex/Lit light). It is a diagnostic only.

The 7 layers without editor-render sweep evidence were judged on the per-layer review and all ship: tbincstl, tbincstl_2,
tbindw_0, tbindw_1, tbindw_3, tbindw_6, tbinhrd4.

| layer | mesh | fit IoU | rest dE76 seed -> T2 | ships | note |
|---|---|---|---|---|---|
| tbinhall | tbinhall | 0.77 | 5.0 -> 4.7 | **T2** | Meshy body (default) |
| tbinhall_2 | tbinhall_3 | 0.76 | 4.38 -> 3.87 | **T2** | Meshy body (default) |
| tbinhall_3 | tbinhall_3 | 0.76 | 4.25 -> 3.7 | **T2** | Meshy body (default) |
| tbincstl | tbincstl | 0.65 | 6.82 -> 6.78 | **T2** | Meshy body (default) |
| tbincstl_2 | tbincstl | 0.65 | 7.62 -> 7.65 | **T2** | Meshy body (default) |
| tbincstl_3 | tbincstl_3 | 0.62 | 8.94 -> 9.02 | **T2** | castle: a solid keep where the relief streaks its sides (sweep_right) |
| tbintvrn | tbintvrn | 0.68 | 2.2 -> 1.96 | **T2** | Meshy body (default) |
| tbinblak | tbinblak | 0.69 | 4.09 -> 4.48 | **T2** | blacksmith: solid walls; the chimney top steps slightly at sweep_right |
| tbinmark | tbinmark | 0.65 | 4.57 -> 5.04 | **T2** | marketplace: timber sheds read as structure; both versions shear at sweep_right |
| tbinsilo | tbinsilo | 0.70 | 4.65 -> 4.25 | **T2** | Meshy body (default) |
| tbinmage | tbinmage | 0.73 | 3.22 -> 4.26 | **T2** | Meshy body (default) |
| tbinmage_2 | tbinmage_2 | 0.76 | 5.12 -> 5.58 | **T2** | Meshy body (default) |
| tbinmage_3 | tbinmage_3 | 0.69 | 5.63 -> 6.29 | **T2** | Meshy body (default) |
| tbinmage_4 | tbinmage_4 | 0.80 | 5.17 -> 5.63 | **T2** | Meshy body (default) |
| tbinext1 | tbinext1 | 0.70 | 4.64 -> 4.08 | **T2** | Meshy body (default) |
| tbinext2 | tbinext2 | 0.77 | 9.04 -> 8.04 | **T2** | Meshy body (default) |
| tbindw_0 | tbindw_0 | 0.67 | 4.15 -> 4.51 | **T2** | Meshy body (default) |
| tbindw_0_2 | tbindw_0_2 | 0.68 | 4.23 -> 4.63 | **T2** | Meshy body (default) |
| tbindw_1 | tbindw_1 | 0.63 | 4.15 -> 4.22 | **T2** | Meshy body (default) |
| tbindw_1_2 | tbindw_1_2 | 0.62 | 6.46 -> 6.53 | **T2** | hall of sins: more solid than the relief's stretched slabs; some edge flaps remain |
| tbindw_2 | tbindw_2 | 0.74 | 2.36 -> 2.6 | **T2** | Meshy body (default) |
| tbindw_2_2 | tbindw_2_2 | 0.42 | 3.28 -> 3.37 | seed relief | kennels gate: a black slit opens along the top of the wall at sweep_right / sweep_high |
| tbinhrd4 | tbinhrd4 | 0.35 | 3.89 -> 3.85 | **T2** | Meshy body (default) |
| tbindw_3 | tbindw_3 | 0.61 | 2.16 -> 2.43 | **T2** | demon gate base: solid, a few jagged edges (sweep_right) |
| tbindw_3_2 | tbindw_3_2 | 0.53 | 6.75 -> 6.71 | seed relief | demon gate: the base shatters into painted shards and the horns double at sweep_right / sweep_high |
| tbindw_4 | skipped | - | - | seed | hell hole level 1 is a pit in the lava floor (a ground decal, 192x56, no standing structure): the depth solid follows the ground |
| tbindw_4_2 | tbindw_4_2 | 0.61 | 1.41 -> 2.06 | seed relief | pentagram gate: the pentagram face breaks into shards at sweep_right / sweep_high |
| tbindw_5 | skipped | - | - | seed | fire lake level 1 is the gold lava floor only (280x24, a ground decal) |
| tbindw_5_2 | tbindw_5_2 | 0.55 | 7.1 -> 6.02 | seed relief | fire lake: the second dome collapses into a dark hole over a floor slab at sweep_right / sweep_high |
| tbindw_6 | tbindw_6 | 0.65 | 3.66 -> 3.45 | **T2** | Meshy body (default) |
| tbindw_6_2 | tbindw_6_2 | 0.76 | 2.31 -> 2.67 | **T2** | Meshy body (default) |
| tbinholy | skipped | - | - | seed | grail: a glowing demon apparition in the sky (no structure to model) |

Unreachable layers are not built: tbinhall_4, tbinmage_5, tbinext0, tbifext5, tbinhrd1-3, tbinhrd2_2, tbinhrd2_4 and every tbindw_*_3.


## Spend log

All from the town cap (417 of 576); no contingency claimed, no retries.


| time (UTC) | layer | kind | credits | task |
|---|---|---|---|---|
| 2026-09-29T18:31:57 | tbinhall | image-to-image nano-banana-2 | 6 | `01a0ef82-b642-74b1-b3d2-59e09fba0c21` |
| 2026-09-29T18:31:58 | tbinhall_3 | image-to-image nano-banana-2 | 6 | `01a0ef82-b943-7143-91d7-cf100db50232` |
| 2026-09-29T18:32:17 | tbincstl | image-to-3d meshy-t2 textured | 15 | `01a0ef83-0145-75e6-bee7-08b92ffe913e` |
| 2026-09-29T18:32:18 | tbincstl_3 | image-to-3d meshy-t2 textured | 15 | `01a0ef83-05f4-74c2-8bc7-3905c88dcd2a` |
| 2026-09-29T18:32:20 | tbintvrn | image-to-3d meshy-t2 textured | 15 | `01a0ef83-0beb-76a4-8c65-7c2cdffc81a1` |
| 2026-09-29T18:32:22 | tbinblak | image-to-3d meshy-t2 textured | 15 | `01a0ef83-13af-7110-85b4-168b04c81354` |
| 2026-09-29T18:32:24 | tbinmark | image-to-3d meshy-t2 textured | 15 | `01a0ef83-1e19-70f8-9598-6cd6d78f6d5b` |
| 2026-09-29T18:32:26 | tbinsilo | image-to-3d meshy-t2 textured | 15 | `01a0ef83-26c7-7601-bba0-6f802fb92303` |
| 2026-09-29T18:32:29 | tbinmage | image-to-3d meshy-t2 textured | 15 | `01a0ef83-2fb8-7090-8208-12c10f2721d3` |
| 2026-09-29T18:32:31 | tbinmage_2 | image-to-3d meshy-t2 textured | 15 | `01a0ef83-3abb-7285-bad5-65c43576b47b` |
| 2026-09-29T18:34:24 | tbinmage_3 | image-to-3d meshy-t2 textured | 15 | `01a0ef84-f2e9-7342-8613-dcadc5098f25` |
| 2026-09-29T18:34:26 | tbinmage_4 | image-to-3d meshy-t2 textured | 15 | `01a0ef84-fa79-7766-b65a-c2da0bd6a8a9` |
| 2026-09-29T18:34:28 | tbinext1 | image-to-3d meshy-t2 textured | 15 | `01a0ef85-01de-7140-ba9a-9125ff5d8d40` |
| 2026-09-29T18:34:30 | tbinext2 | image-to-3d meshy-t2 textured | 15 | `01a0ef85-0ac7-751b-baaf-191f792761f2` |
| 2026-09-29T18:34:33 | tbindw_0 | image-to-3d meshy-t2 textured | 15 | `01a0ef85-1403-7630-94d4-a973faa96016` |
| 2026-09-29T18:34:36 | tbindw_0_2 | image-to-3d meshy-t2 textured | 15 | `01a0ef85-1f1f-71f3-934c-7e804e023cb4` |
| 2026-09-29T18:35:01 | tbindw_1 | image-to-3d meshy-t2 textured | 15 | `01a0ef85-80f9-701b-ba66-ef18cb2b0fcc` |
| 2026-09-29T18:35:04 | tbindw_1_2 | image-to-3d meshy-t2 textured | 15 | `01a0ef85-8cd1-72d4-85bf-a0fa37db06e4` |
| 2026-09-29T18:36:56 | tbindw_2 | image-to-3d meshy-t2 textured | 15 | `01a0ef87-4566-7270-ac0c-bee613c65edb` |
| 2026-09-29T18:36:57 | tbindw_2_2 | image-to-3d meshy-t2 textured | 15 | `01a0ef87-4aa8-759b-aceb-871a48d329f8` |
| 2026-09-29T18:36:59 | tbinhrd4 | image-to-3d meshy-t2 textured | 15 | `01a0ef87-4ff7-71a5-88f2-2eee47b4fa89` |
| 2026-09-29T18:37:00 | tbindw_3 | image-to-3d meshy-t2 textured | 15 | `01a0ef87-55dd-7689-8278-b2954790a079` |
| 2026-09-29T18:37:03 | tbindw_3_2 | image-to-3d meshy-t2 textured | 15 | `01a0ef87-5dc7-73ef-b850-d83b9f23e503` |
| 2026-09-29T18:37:05 | tbindw_4_2 | image-to-3d meshy-t2 textured | 15 | `01a0ef87-67e7-75b2-a046-b6d0611575e6` |
| 2026-09-29T18:37:08 | tbindw_5_2 | image-to-3d meshy-t2 textured | 15 | `01a0ef87-71e7-71ed-9699-b58b1830ce91` |
| 2026-09-29T18:37:13 | tbindw_6 | image-to-3d meshy-t2 textured | 15 | `01a0ef87-8551-73fc-89fa-5b0471fe93a0` |
| 2026-09-29T18:38:00 | tbindw_6_2 | image-to-3d meshy-t2 textured | 15 | `01a0ef88-3d93-70e0-931f-c4b7dd1388f0` |
| 2026-09-29T18:48:08 | tbinhall | image-to-3d meshy-t2 textured | 15 | `01a0ef91-85bc-7672-8b12-646c269de7c8` |
| 2026-09-29T18:48:10 | tbinhall_3 | image-to-3d meshy-t2 textured | 15 | `01a0ef91-8c29-7274-8750-ae1087074ba8` |
| | **total** | 2 concepts x 6 + 27 meshes x 15 | **417** | cap 576, contingency 0 |


## Verdict

**Ship-ready as a candidate for the user's eye: 25 Meshy buildings with the painting on their rest-visible fronts.**
- **At rest:** the frame reads as the painting. Every layer is within about 1 dE76 of the installed relief, and 10 are
  closer to the painting than the relief.
- **At the sweeps:** the castle keep, the halls, the mage guilds, the tavern and the hall of sins hold their shape
  where the relief streaks and stretches its sides.
- **Remaining flaws, not reverted:**
  - the blacksmith chimney top steps slightly at sweep_right;
  - the marketplace and the silo shear at sweep_right, as the relief does;
  - a few edge flaps and small dark specks on the hall of sins and mage guilds 2-3.
- **Reverted:** four layers are genuinely broken and keep the relief: the demon gate (dw_3_2), the pentagram gate
  (dw_4_2), the fire-lake domes (dw_5_2) and the kennels gate (dw_2_2). In all four, Meshy's massing disagrees with the
  painting (fit IoU 0.42-0.61), so the camera-projected front breaks into shards or opens a hole once the camera moves.
- **What would fix those four:** new Meshy inputs whose massing matches the painting (the fire-lake domes without the
  gold floor slab, the gates as one wall). That needs new spend, which this pass did not make.
- **Caveats:** the bundle is 277 MB, 2.9x the first pass. The sweeps are only half-extent (profile panScale 0.5).

History: the first pass (commit defec4a8ad) gated on rest dE76 plus a sweep win and shipped only 4 layers. Its per-texel
re-bake lost at rest on most layers. The painted-front bake removed that loss, and the user's decision removed the rest
gate.

## Shared bake (2026-09-30)

The painted-front bake is `tools/homm3_town_scene_meshes/town_full3d_t2_paint.py`, the one T2 bake for all eleven factions. On 2026-09-30 it absorbed the last four copies: `rampart_t2_buildings.stage_split` (Rampart, Dungeon), `inferno_t2_integrate.stage_layer`, `town_full3d_t2_meshy.painted_front` (Necropolis, Bulwark) and `t2_rest_geometry.stage_painted_layer` (Castle, Tower). Where a lane's bake differs by design, the difference is a named parameter of the shared module, set at this lane's call site; no output was changed to force identity.

This lane's values (`inferno_t2_integrate.stage_layer`): `clip=CLIP_DOME` (its rest id buffer uses the dome's near and far planes); the `sprite_fill` mask is `native_mask`; `gain_guard=("px", 200)` and `gain_dtype=float32`. The skirt stays in this module.

Restaging the sample layer tbintvrn with the shared module into a scratch stage gives files byte-identical to this candidate's (`t2_v1`) staged bins, and so did the old code before the fold (`tools/homm3_town_scene_meshes/t2_bake_restage_check.py`; results in `artifacts/town_t2_bake_consolidation/`). The bundle was not rebuilt. Proof tier of this note: generated artifact.
