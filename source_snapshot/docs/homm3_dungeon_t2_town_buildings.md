# homm3_dungeon: Meshy T2 town buildings (candidate t2_v1)

Proof tier: **generated artifact + build target (Unity bundle) + editor render**. The see-through gate and the scene
validator pass, and the review sheet is built from the Unity editor renders. **Not installed**: the install step
(`install_town_scene3d.py dungeon .../t2_v1/bundle`) was denied by the session's permission gate and was not
retried. There is no installed, startup, runtime or user-visible proof.

- Brief: `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md`. This doc replaces `homm3_dungeon/HANDOFF.md`.
- Candidate: `artifacts/homm3_dungeon_full3d/candidates/t2_v1`, seeded from the installed `wall_v7`.
  Terrain, sky and the non-meshed layers are unchanged from `wall_v7`.
- Scripts:
  - `tools/homm3_town_scene_meshes/dungeon_t2_generate.py` handles Meshy generation and the ledger.
  - `tools/homm3_town_scene_meshes/rampart_t2_buildings.py` runs fit, stage, revert, fx, finish and preview.
    - It is the Rampart lane's module. Dungeon is its second `FACTIONS` entry (`_dungeon()`), selected by
      `TOWN_FULL3D_FACTION=dungeon`.
    - The earlier `dungeon_t2_buildings.py` is superseded and has been removed. It had its own snap-warp fit and
      the old per-face bake. Its fits (`artifacts/homm3_dungeon_full3d/t2/fit`) have been deleted.

## Rule (user decision 2026-09-29)

- Every layer uses its Meshy body with the painted front.
- The seed relief is kept only for a genuinely broken mesh: fragments, a flat slab, or the main feature missing.
  This is judged by eye at the sweeps.
- Rest dE76 is a diagnostic only.

## Method

Identical to `docs/homm3_rampart_t2_town_buildings.md`: the same code path and the same constants.

1. Rect-fitter registration, then `depth_slide`.
2. Painted-rect clip.
3. Screen-space split to 8 px.
4. Painted front (`Mesh_Body_`), de-lit through the smooth view normal.
5. Gain-matched Meshy remainder (`Mesh_BodyM_`).
6. Seed residual (`Mesh_BodyRest_`, from `wall_v7`).
7. All bins two-sided.
8. The seed's fx slid onto the T2 surfaces.

Dungeon results:
- **fx.** Five glow emitters were re-derived from `wall_v7`.
  - Slides: dw_0 0.936, dw_0_2 0.943, dw_2 0.970, hrd2 0.950.
  - dw_2_2's glow is not over the body, so it keeps its seed place (slide 1.0).
  - These layers have no Fx_ water meshes.
- **Painted-rect clip.** It dropped the triangles past the frame: dw_0 2700, dw_0_2 6373, hrd2 1202, and about 100
  each on hall, hall_3 and holy.
- **Triangles.** The 21 T2 layers carry 303,186 painted-front and 128,724 Meshy-remainder triangles, counted before
  the two-sided copy.

## Per-layer verdict

- Layers were judged by eye on offline layer sheets: the env plus one layer, lane shading with back-face culling.
- Poses: rest, cursor_left/right and sweep_left/right/high.
- mage_3, mage_4, mark and silo were also compared against `wall_v7`.

| layer | staged | fit IoU | depth slide | residual px / sprite px | note |
|---|---|---|---|---|---|
| tbdnblak | T2 | 0.698 | 0.8831 | 2399 / 9800 |  |
| tbdncstl | T2 | 0.504 | 0.7199 | 20216 / 40615 | half the sprite px are the seed residual (fit IoU 0.50: the Meshy castle is narrower than the painting's towers) |
| tbdncstl_2 | T2 | 0.562 | 1.0 | 20268 / 48265 | as cstl |
| tbdncstl_3 | T2 | 0.670 | 1.0 | 10855 / 50140 |  |
| tbdndw_0 | T2 | 0.693 | 1.0 | 3432 / 13980 | mushroom caps are separate small pieces at sweep_right / sweep_high; house body solid |
| tbdndw_0_2 | T2 | 0.661 | 0.9708 | 5600 / 18106 | as dw_0 |
| tbdndw_2 | T2 | 0.745 | 0.9985 | 2066 / 10044 |  |
| tbdndw_2_2 | T2 | 0.627 | 0.9509 | 4854 / 14088 | glow particle not over the body (slide 1.0) |
| tbdndw_4 | T2 | 0.629 | 0.8288 | 2998 / 8225 |  |
| tbdndw_4_2 | T2 | 0.618 | 0.9949 | 4569 / 12313 |  |
| tbdnhall | T2 | 0.608 | 0.8155 | 3737 / 13026 |  |
| tbdnhall_2 | T2 | 0.652 | 0.8379 | 3935 / 16552 |  |
| tbdnhall_3 | T2 | 0.719 | 0.6774 | 5059 / 21568 |  |
| tbdnholy | T2 | 0.754 | 0.6849 | 7635 / 40520 |  |
| tbdnhrd2 | T2 (tbdndw_0_2 mesh) | 0.743 | 0.968 | 3971 / 18964 | dw_0_2 mesh, own paint; mushrooms as dw_0 |
| tbdnmage | T2 | 0.682 | 0.9525 | 3156 / 9416 |  |
| tbdnmage_2 | T2 | 0.698 | 0.9039 | 3768 / 13594 |  |
| tbdnmage_3 | T2 | 0.767 | 0.731 | 3284 / 16513 | holds shape where the seed's towers smear at sweep_left |
| tbdnmage_4 | T2 | 0.761 | 0.6524 | 3796 / 21079 | as mage_3 |
| tbdnspec | T2 | 0.768 | 0.9796 | 2320 / 10017 |  |
| tbdntvrn | T2 | 0.682 | 1.0 | 2701 / 8175 |  |
| tbdnmark | **relief** | 0.652 | | | broken: the stall row comes apart; its lower half is a separate floating slab of smeared paint at every sweep |
| tbdnsilo | **relief** | 0.472 | | | broken: the sprite is a tiny frame-cut grain field; T2 made a flat white trough, a white plank across the grain at every sweep |

**Never meshed.** These keep the `wall_v7` relief; the reasons are in `dungeon_t2_generate.py`.
- dw_1 / dw_1_2, dw_3 / dw_3_2, dw_5 / dw_5_2 and dw_6 / dw_6_2 are painted pieces of the cavern wall or floor.
- ext0 is the sparkle-ring overlay.

The validator reports reachable=32 of 32 layers.

**Weak spots.**
- The castles cstl and cstl_2 fit at IoU 0.50-0.56, so about half their sprite px at rest come from the seed
  residual.
- The mushroom caps of dw_0, dw_0_2 and hrd2 are separate small pieces at the sweeps. The house bodies are solid.
- The Meshy remainder colour is only gain-matched. The dark-stone layers clamp at gain 0.5.

## Gates

| gate | result |
|---|---|
| See-through (Cull Back, no worse than baseline dg_v4_edge at every pose) | pass: total 717 px, worse = {} |
| Validator (`stronghold_full3d_scene.py validate`, candidate) | `town-scene3d-contract: OK homm3_dungeon layers=32 reachable=32 unused=0 ... panVoid=0` (bundle=present) |
| Bundle | built through cpuslot + unitylock (memgate / launch_guard OK), rc 0: `artifacts/homm3_dungeon_full3d/candidates/t2_v1/bundle/homm3_town_scene3d_dungeon`, 194,932,703 bytes, sha256 `5ef6bf0ea8606839da138772fd0b2a3894d52e7f6e982aabe1617d9ad2103f3f` |
| Editor render | `RenderStates` rc 0 (after V: was freed to 20.9 GB) |
| Validator after render | `town-scene3d-contract: OK homm3_dungeon layers=32 reachable=32 unused=0 ... bundle=present ... panVoid=0` |
| Review sheet | built; looks right (see Review) |
| Install | **not done**: denied by the session's permission gate, and not retried |

## Review

- **Sheet:** `artifacts/claude_takeover_20260927/review/homm3_dungeon_t2_buildings.png` (Unity editor renders).
  Columns: painting | before wall_v7 | after t2_v1, at rest and sweep_left / sweep_right / sweep_high. Zooms:
  cstl_3, hall_3, mage_4, tvrn, spec, holy, blak, hrd2, dw_2_2, dw_4_2.
- **Verdict: T2 is the better town at the sweeps.**
  - The castle stays a castle; in wall_v7 its towers stretch into a vertical sheet at sweep_left and sweep_right.
  - hall_3's left stair tower holds; in wall_v7 it becomes a bright yellow slab at sweep_high and a dark sheet at
    sweep_left.
  - mage_3 and mage_4 keep their towers upright, where the seed relief smears them.
  - At rest the town reads as the painting.
- **Weak spots:** the castles take about half their rest pixels from the seed residual, and the mushroom caps of
  dw_0, dw_0_2 and hrd2 break into small pieces at the sweeps.
- **Rest dE76, diagnostic only** (the `.json` beside the sheet; before / after, mean):
  - hall_3 3.57 / 2.58, cstl_3 2.80 / 2.86, mage_4 3.78 / 3.52, tvrn 4.13 / 3.84, blak 2.78 / 2.47.
  - spec 8.45 / 4.84, holy 2.83 / 2.84, hrd2 8.95 / 6.80, dw_0_2 8.51 / 6.28, dw_2_2 6.32 / 5.89, dw_4_2 3.04 / 3.04.
- The offline layer sheets used for the per-layer verdicts were deleted once this sheet existed.

## Spend (shared ledger `artifacts/meshy_town_scene_meshes/_ledger.jsonl`, faction homm3_dungeon)

- The cap is 552. **Spent 330**: 22 image-to-3d calls at 15 credits.
- No contingency was claimed, and nothing was spent in this pass.
- tbdnsilo and tbdnmark (30 credits) are meshed but unused.

| time | layer | kind | credits | taskId |
|---|---|---|---|---|
| 2026-09-29T18:25:18 | tbdntvrn | image-to-3d meshy-t2 textured | 15 | 01a0ef7c-9d81-717b-b1e2-e2a40e46c410 |
| 2026-09-29T18:26:12 | tbdnhall | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-723f-74b4-98e4-e27f69291dbd |
| 2026-09-29T18:26:13 | tbdnhall_3 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-7536-7762-8cbe-8f5e55819ed1 |
| 2026-09-29T18:26:14 | tbdnhall_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-78a8-7229-a820-5b663b425c81 |
| 2026-09-29T18:26:15 | tbdncstl_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-7c79-72b7-93af-651ba765d0dd |
| 2026-09-29T18:26:16 | tbdncstl_3 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-802b-7715-bdb4-7cc65483498d |
| 2026-09-29T18:26:17 | tbdnmage_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-83cc-72d6-b17c-060731d61890 |
| 2026-09-29T18:26:18 | tbdnmage | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-87e5-724c-a008-dd635a098a00 |
| 2026-09-29T18:26:19 | tbdncstl | image-to-3d meshy-t2 textured | 15 | 01a0ef7d-8bb4-7396-8634-f690ae6397fe |
| 2026-09-29T18:27:00 | tbdnmage_3 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-2b4d-73fd-be46-87fb3acbaea7 |
| 2026-09-29T18:27:01 | tbdnmage_4 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-2fbf-75ae-ac44-7aca7553face |
| 2026-09-29T18:27:02 | tbdnmark | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-3313-7653-9da7-a9ce53ff59da |
| 2026-09-29T18:27:18 | tbdnsilo | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-71ac-779b-b228-b557a8cf12d2 |
| 2026-09-29T18:27:19 | tbdnblak | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-75da-7111-b392-2d176c9da05f |
| 2026-09-29T18:27:20 | tbdnspec | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-7a41-7511-9c54-5de08e781d85 |
| 2026-09-29T18:27:37 | tbdnholy | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-bcbd-7167-b89c-2e07a6771672 |
| 2026-09-29T18:27:38 | tbdndw_0 | image-to-3d meshy-t2 textured | 15 | 01a0ef7e-c11f-71c5-8b4b-2fdf503a5b6d |
| 2026-09-29T18:29:03 | tbdndw_0_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef80-0f16-7666-a541-19af9a844e43 |
| 2026-09-29T18:29:04 | tbdndw_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef80-123e-7607-9d65-1fba642bf2f0 |
| 2026-09-29T18:29:05 | tbdndw_2_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef80-15d6-7623-b129-65a68494b873 |
| 2026-09-29T18:29:36 | tbdndw_4 | image-to-3d meshy-t2 textured | 15 | 01a0ef80-901a-776d-b9a0-f2d3c04e357d |
| 2026-09-29T18:29:39 | tbdndw_4_2 | image-to-3d meshy-t2 textured | 15 | 01a0ef80-998f-77f3-b505-8387a89127ce |

## Resume / reproduce

- Run every heavy step through `python artifacts/claude_takeover_20260927/cpuslot.py -- ...`.
- Set `TOWN_FULL3D_FACTION=dungeon TOWN_FULL3D_CANDIDATE=t2_v1`.
- The candidate is complete through the review sheet. Only the install (the last line, which needs permission)
  remains.

```
python tools/homm3_town_scene_meshes/rampart_t2_buildings.py fit
python tools/homm3_town_scene_meshes/rampart_t2_buildings.py stage     # every layer not in BROKEN
python tools/homm3_town_scene_meshes/rampart_t2_buildings.py revert    # BROKEN layers back to wall_v7's relief
python tools/homm3_town_scene_meshes/rampart_t2_buildings.py fx
python tools/homm3_town_scene_meshes/rampart_t2_buildings.py finish    # closing walls, catalog, see-through gate
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py bundle
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py render
python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py validate
python tools/homm3_town_scene_meshes/t2_town_review.py --before wall_v7 \
    --zooms tbdncstl_3,tbdnhall_3,tbdnmage_4,tbdntvrn,tbdnspec,tbdnholy,tbdnblak,tbdnhrd2,tbdndw_2_2,tbdndw_4_2 \
    --out artifacts/claude_takeover_20260927/review/homm3_dungeon_t2_buildings.png
python tools/homm3_town_scene_meshes/install_town_scene3d.py dungeon artifacts/homm3_dungeon_full3d/candidates/t2_v1/bundle
```

## Shared bake (2026-09-30)

The painted-front bake is `tools/homm3_town_scene_meshes/town_full3d_t2_paint.py`, the one T2 bake for all eleven factions. On 2026-09-30 it absorbed the last four copies: `rampart_t2_buildings.stage_split` (Rampart, Dungeon), `inferno_t2_integrate.stage_layer`, `town_full3d_t2_meshy.painted_front` (Necropolis, Bulwark) and `t2_rest_geometry.stage_painted_layer` (Castle, Tower). Where a lane's bake differs by design, the difference is a named parameter of the shared module, set at this lane's call site; no output was changed to force identity.

This lane's values (`rampart_t2_buildings.stage_split` / `stage_layer`): `subdivide_screen(max_px=8)`; the `sprite_fill` mask is `native_mask`; `painted_split(zbuf=...)` reuses the rest z-buffer that `lean_normals` already rendered; `gain_guard=("px", 200)` and `gain_dtype=float32` for the Meshy gain; `preview=False`. The seed residual (`Mesh_BodyRest_`) uses the shared `seed_residual`.

Restaging the sample layer tbdntvrn with the shared module into a scratch stage gives files byte-identical to this candidate's (`t2_v1`) staged bins, and so did the old code before the fold (`tools/homm3_town_scene_meshes/t2_bake_restage_check.py`; results in `artifacts/town_t2_bake_consolidation/`). The bundle was not rebuilt. Proof tier of this note: generated artifact.
