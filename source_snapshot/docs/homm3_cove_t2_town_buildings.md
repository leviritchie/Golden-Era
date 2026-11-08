# Cove T2 town buildings (Meshy image-to-3d, full-3D candidate cv_t2)

Status: **Proof tier: installed payload** (stage gates, bundle built through unitylock, `validate` OK, installed and
read back). Not yet startup-smoke, runtime or user-visible proven.
The Unity render (`render --faction cove`, rc 0) is in `artifacts/homm3_cove_full3d/candidates/cv_t2/renders/`.
Installed 2026-09-30 by `install_town_scene3d.py cove artifacts/homm3_cove_full3d/candidates/cv_t2/bundle`: bundle
sha256 `74d05148483d6b8b04364b1b7b62acd4395ddbb16a5c1cc98949122d28fa48ed` (230084938 bytes), catalog sha256
`5b3ce68450f67d4686f60ad77b0689ea5903a3d3d65a72903c9c7c105e61d71a`, read back and validated in the source tree and
Golden Era. Rollback copy: `artifacts/town_scene_rollback/cove_20260930T061051Z`.

Brief: `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md`. Rule of 2026-09-29, set by the user: Meshy geometry is
the default for every layer, because functional geometry stays consistent at the sweeps while the painted relief warps.
Rest dE76 is a diagnostic only. A layer goes back to the relief only when its mesh is genuinely broken (fragments, a
flat slab, or the main feature missing), and that is judged by eye at the sweeps.

The "before" is `cv_v11`, the Cove full-3D candidate this one is seeded from (`candidate-init --seed-from cv_v11`, with
`work/closing_walls.npz` copied in).

## Spend

The ledger (`artifacts/meshy_town_scene_meshes/_ledger.jsonl`) has these Cove lines: 29 image-to-3d meshy-t2
smart-topology textured creates at 15 cr each, **435 cr**, plus one contingency claim of 45 cr for three retries. The
limit is the cap (480) plus the claim (45), which is 525. No unitReserve was spent, and no Meshy call was made after the
2026-09-29 resume.

| time (2026-09-29) | kind | layer | task id | cr |
|---|---|---|---|---|
| 18:27 | image-to-3d meshy-t2 textured | tbcvtave | 01a0ef7e-b33b-7278-a322-e69ccef529d6 | 15 |
| 18:27 | image-to-3d meshy-t2 textured | tbcvhall | 01a0ef7e-b815-75f5-84a4-bf126f51ee9d | 15 |
| 18:27 | image-to-3d meshy-t2 textured | tbcvhal2 | 01a0ef7e-bc78-76ee-81ce-fa4fc8cde8e4 | 15 |
| 18:27 | image-to-3d meshy-t2 textured | tbcvhal3 | 01a0ef7e-c133-76f4-bb31-8abaf69b5418 | 15 |
| 18:27 | image-to-3d meshy-t2 textured | tbcvsmth | 01a0ef7e-c58b-77dd-a3dd-2c1935a66001 | 15 |
| 18:27 | image-to-3d meshy-t2 textured | tbcvmark | 01a0ef7e-c97b-77b2-8d9f-5bd316e01ca9 | 15 |
| 18:27 | image-to-3d meshy-t2 textured | tbcvcstl | 01a0ef7e-cd0d-7202-aa58-9e689dd8290d | 15 |
| 18:27 | image-to-3d meshy-t2 textured | tbcvcas2 | 01a0ef7e-d12b-740a-b8fa-52177a535131 | 15 |
| 18:31 | image-to-3d meshy-t2 textured | tbcvcas3 | 01a0ef82-3246-7210-a224-300f792da464 | 15 |
| 18:31 | image-to-3d meshy-t2 textured | tbcvsay1 | 01a0ef82-8298-76e2-ae58-0796a4823f22 | 15 |
| 18:31 | image-to-3d meshy-t2 textured | tbcvsay2 | 01a0ef82-8715-74bc-80fa-97f56d71637b | 15 |
| 18:31 | image-to-3d meshy-t2 textured | tbcvsa2p | 01a0ef82-8ac3-7282-8450-5ea722f91d4a | 15 |
| 18:32 | image-to-3d meshy-t2 textured | tbcvthgd | 01a0ef82-daf3-72ef-8bd7-c4b4bab14a87 | 15 |
| 18:32 | image-to-3d meshy-t2 textured | tbcvdock | 01a0ef82-df35-725d-8ebe-9abc82318d0f | 15 |
| 18:32 | image-to-3d meshy-t2 textured | tbcvpir1 | 01a0ef82-e2fb-77aa-881e-8bd4fd9888e8 | 15 |
| 18:32 | image-to-3d meshy-t2 textured | tbcvpir2 | 01a0ef83-2bbd-76d3-9e38-c812740d9201 | 15 |
| 18:33 | image-to-3d meshy-t2 textured | tbcvnix1 | 01a0ef83-f7e8-7073-b135-9aebc920ccf1 | 15 |
| 18:33 | image-to-3d meshy-t2 textured | tbcvnix2 | 01a0ef84-4527-7438-bfd5-8e92957b28de | 15 |
| 18:33 | image-to-3d meshy-t2 textured | tbcvgmg1 | 01a0ef84-48b9-7715-9c88-d71126aa85c6 | 15 |
| 18:33 | image-to-3d meshy-t2 textured | tbcvgmg2 | 01a0ef84-4dee-7734-a8ca-9b7cefbc0bde | 15 |
| 18:34 | image-to-3d meshy-t2 textured | tbcvgmg3 | 01a0ef84-9b4c-7357-89d5-ec1d859e005a | 15 |
| 18:34 | image-to-3d meshy-t2 textured | tbcvgmg4 | 01a0ef84-9f01-779e-90b2-5949758b45f7 | 15 |
| 18:34 | image-to-3d meshy-t2 textured | tbcvsor1 | 01a0ef84-a2cc-770b-a7c9-e5f04d2c4ffd | 15 |
| 18:34 | image-to-3d meshy-t2 textured | tbcvsor2 | 01a0ef85-2bae-7477-9826-0acfea591c1c | 15 |
| 18:35 | image-to-3d meshy-t2 textured | tbcvass1 | 01a0ef85-f7d6-76e2-93db-4e3fcde71864 | 15 |
| 18:35 | image-to-3d meshy-t2 textured | tbcvass2 | 01a0ef86-4026-7175-8f2e-5d6030f35c22 | 15 |
| 19:56 | claim | tbcvhall,tbcvsay1,tbcvsay2 | - | 45 |
| 19:57 | image-to-3d meshy-t2 textured | tbcvhall | 01a0efd0-b349-7128-8f81-522fc2d6b7a2 | 15 |
| 19:57 | image-to-3d meshy-t2 textured | tbcvsay1 | 01a0efd0-b709-75a1-961d-6e7c9f53ee22 | 15 |
| 19:57 | image-to-3d meshy-t2 textured | tbcvsay2 | 01a0efd0-ba8a-7361-b8b7-096d85bb62d5 | 15 |

The three retries are these:
- `tbcvhall` a2 was cropped to the building. a1 was a tall, narrow gabled house and is kept in `tbcvhall/attempt1/`.
- `tbcvsay1` and `tbcvsay2` a2 used an input that kept the stilts (no closing or hole fill). Both still failed; see
  below.

## Layers

- **Meshed and staged (24):**
  - tbcvtave;
  - tbcvhall, tbcvhal2, tbcvhal3;
  - tbcvsmth, tbcvmark;
  - tbcvcstl, tbcvcas2, tbcvcas3;
  - tbcvsa2p, tbcvthgd, tbcvdock;
  - tbcvpir1, tbcvpir2, tbcvnix1, tbcvnix2;
  - tbcvgmg1 to tbcvgmg4;
  - tbcvsor1, tbcvsor2, tbcvass1, tbcvass2.
- **Reverted to the relief (meshed, not staged; `STAGE_SKIP` in `cove_t2_stage.py`):**
  - `tbcvsay1` and `tbcvsay2`: both attempts, including the stilt-preserving a2 input, closed the stilt rows into
    solid grey slab columns. The main feature (the stilts) is missing and the body is a slab.
- **Not meshed (`SKIP` in `cove_t2_buildings.py`), because none is a structure:**
  - `tbcvgral`: the star-sky panorama;
  - `tbcvnmp1` and `tbcvnmp2`: the waterfall Fx (nmp2 only adds a statue of a few px);
  - `tbcvwhr1` and `tbcvwhr2`: flat whirlpool water discs;
  - `tbcvsmrk`: three chests about 21 px across.

Per layer, from `work/stage_report.json`:
- the fit is `fit_mesh_to_sprite.Fitter` under the rest camera, as a full-circle yaw plus scale plus vertical stretch
  (the fit was redone serially from scratch after the resume);
- cover is the share of the sprite that the Meshy silhouette covers at rest;
- the counts are one-sided triangles (every piece ships double-sided);
- surgery gives the dropped triangles per rule.

| layer | yaw | IoU | cover | front | hull | residual (grazing dropped) | surgery |
|---|---|---|---|---|---|---|---|
| tbcvass1 | 141 | 0.759 | 0.799 | 9425 | 6389 | 256 (72) | offSprite 2, offSpriteFaces 6 |
| tbcvass2 | 204 | 0.677 | 0.669 | 15113 | 5495 | 262 (14) | - |
| tbcvcas2 | 6 | 0.919 | 0.897 | 57931 | 11555 | 139 (33) | loneSheets 1, offSpriteFaces 7 |
| tbcvcas3 | 186 | 0.838 | 0.829 | 71035 | 11762 | 540 (479) | loneSheets 4 |
| tbcvcstl | 6 | 0.901 | 0.846 | 50398 | 10454 | 128 (41) | loneSheets 2 |
| tbcvdock | 183 | 0.801 | 0.730 | 48908 | 6376 | 0 (0) | loneSheets 68, paintOrder 33 (over tbcvcas3 33) |
| tbcvgmg1 | 42 | 0.920 | 0.866 | 25640 | 5261 | 0 (0) | loneSheets 7 |
| tbcvgmg2 | 237 | 0.907 | 0.914 | 40094 | 6473 | 0 (0) | loneSheets 15 |
| tbcvgmg3 | 228 | 0.910 | 0.879 | 40041 | 6738 | 0 (0) | - |
| tbcvgmg4 | 225 | 0.884 | 0.895 | 48243 | 7524 | 116 (47) | - |
| tbcvhal2 | 78 | 0.630 | 0.664 | 134889 | 10903 | 894 (2409) | offSprite 1704, loneSheets 62, offSpriteFaces 337 |
| tbcvhal3 | 84 | 0.724 | 0.759 | 140073 | 8134 | 1228 (2852) | offSprite 979, loneSheets 42, offSpriteFaces 299, paintOrder 424 (over tbcvtave 424) |
| tbcvhall | 159 | 0.523 | 0.561 | 103687 | 6808 | 2680 (7326) | offSprite 1920, loneSheets 142, offSpriteFaces 587, paintOrder 713 (over tbcvtave 713) |
| tbcvmark | 42 | 0.545 | 0.635 | 75861 | 10186 | 1835 (3147) | offSprite 224, loneSheets 36, offSpriteFaces 212, paintOrder 378 (over tbcvsmrk 378) |
| tbcvnix1 | 111 | 0.388 | 0.538 | 21804 | 5187 | 1274 (1397) | offSprite 3724, offSpriteFaces 761 |
| tbcvnix2 | 48 | 0.581 | 0.626 | 45880 | 6257 | 899 (3219) | offSprite 18, loneSheets 68, offSpriteFaces 73 |
| tbcvpir1 | 240 | 0.801 | 0.898 | 47078 | 6560 | 0 (0) | - |
| tbcvpir2 | 159 | 0.798 | 0.914 | 67686 | 7932 | 0 (0) | offSprite 41, offSpriteFaces 52 |
| tbcvsa2p | 237 | 0.472 | 0.648 | 244917 | 16387 | 2997 (7688) | offSprite 2132, loneSheets 116, offSpriteFaces 824 |
| tbcvsmth | 321 | 0.628 | 0.744 | 57769 | 9700 | 755 (1518) | offSprite 79, loneSheets 1, offSpriteFaces 196, paintOrder 37 (over tbcvpir2 37) |
| tbcvsor1 | 33 | 0.864 | 0.804 | 52593 | 6074 | 97 (263) | loneSheets 67 |
| tbcvsor2 | 75 | 0.706 | 0.716 | 62201 | 4757 | 521 (498) | offSprite 10, loneSheets 1, offSpriteFaces 34, paintOrder 1343 (over tbcvgmg4 1343) |
| tbcvtave | 117 | 0.684 | 0.787 | 175845 | 14097 | 1357 (2249) | offSprite 4988, offSpriteFaces 302 |
| tbcvthgd | 327 | 0.837 | 0.854 | 16377 | 5878 | 122 (227) | offSprite 1931, loneSheets 104, offSpriteFaces 733 |

## Method (`tools/homm3_town_scene_meshes/cove_t2_stage.py stage`)

1. **Placement.** The Meshy GLB is put in the lane frame (x negated, winding reversed). It is placed by the fitted
   yaw, scale, vertical stretch and position, with its foot on the rest-camera contact depth.
2. **Surgery** (`t2_mesh_surgery.py`, which is shared with Stronghold). The faces are selected in model space and
   dropped from the placed mesh. Every Cove layer uses the following rules, in order:
   - `offSprite`: drops whole connected parts with less than half of their area on the sprite at rest (sprite dilated
     8 frame px). This removes the scenery Meshy invented: the tavern's deck and beach, and the hall and nixie side
     pieces.
   - `loneSheets`: drops one- or two-triangle parts with an edge longer than 30% of the model. These are flying
     slivers.
   - `offSpriteFaces`: drops every remaining face with a corner off the dilated sprite. The first stage kept each
     Meshy body past its sprite (the tavern's one-piece deck, bodies running past the painting edge and under the
     ground). The framing aim is the union of the building bounds, so that stage moved the aim until 8 to 10
     buildings left the visible region, and `town_full3d_framing` failed closed. The union was 0.94 of the frame
     wide, against a 0.90 visible region.
   - `paintOrder`: the buildings draw in catalog layer order, and a Meshy body is solid in depth where the painting's
     layer order is not. So a Meshy face is dropped where it sits in front of (more than 1% nearer the camera than) a
     co-existing layer drawn *after* it, on that later layer's sprite at rest. The later layer's depth is its own
     staged Meshy mesh, or its seed relief. This is what the painting says: the later layer is on top. At rest it
     stopped the hall and the upper hall covering the tavern's roof (713 and 424 triangles), the market covering the
     chests (`tbcvsmrk`, 378), and `tbcvsor2` covering `tbcvgmg4` (1343). Measured need, not a guess: without it those layers occluded the later sprite at rest.
3. **Painted front** (`town_full3d_t2_paint.py` since 2026-09-30, when it absorbed `t2_painted_front.py`; a restage of the sample layer tbcvtave is byte-identical (`tools/homm3_town_scene_meshes/t2_bake_restage_check.py`); the coordinator's rule of 2026-09-29, after
   `rampart_t2_buildings.py`).
   - Faces are split until every projected edge is at most 4 px.
   - A face is front if it owns at least 60% of its SUPER=2 z-buffer pixels, or if its centroid or any corner passes
     the depth test. It must also be inside the sprite rect.
   - Front faces take the sprite by screen position, de-lit through the smooth view normal, and ship with the
     camera-facing normal (`Mesh_Body_<lid>`).
   - The remainder keeps the Meshy UV and texture with a per-channel median gain, clamped to 0.5 to 2
     (`Mesh_Body_<lid>_hull`, 1024 max).
4. **Residual** (`Mesh_Body_<lid>_rest`). This is the seed's own depth-relief triangles, only on sprite pixels the
   Meshy silhouette leaves uncovered (dilated 3 px, at least 150 px).
   - Grazing relief faces (|cos| of the normal against the rest ray below 0.35, `PF.facing_rest`) are dropped.
   - In the first stage, those faces were every long streak, black slab and yellow bar at the sweeps: the smithy's
     and market's flying shards, the nixie's black panel, and the stilt-house bars. They cover almost no rest pixel.
5. **Two-sided.** Every piece is double-sided, because Meshy shells are open and the game culls back faces. The
   see-through gate is no worse than the baseline.

Previews: `artifacts/homm3_cove_full3d/candidates/cv_t2/work/preview/`. Per-layer isolated rest and sweep sheets used
for the review are in `artifacts/meshy_town_scene_meshes/homm3_cove/_work/ls_*.png`.

## Gates

- **stage:**
  - `town_full3d_framing`: OK at zoom 1.17 and pan 0.5, with no building out of the visible region at rest.
  - see-through `town_full3d_cull`: no worse than baseline cv_v6.
- **bundle:** `homm3_town_scene3d_cove` 230084938 bytes, sha256 `74d05148483d6b8b04364b1b7b62acd4395ddbb16a5c1cc98949122d28fa48ed`, built by
  `Homm3TownScene3dBundleBuild.Run` (rc 0).
- **validate:** `town-scene3d-contract: OK homm3_cove layers=32 reachable=32 unused=0 depths=0 bundle=present flag=off
  (candidate) restPose=installed-native-verified framing=zoom1.17/pan0.5 full3d=on env=16 phase=3 fx=104 shaders=2
  detail=6 water=1 animated=19 nearPieces=2 dressing=3 panRays=990000 panVoid=0 panNeg16x9=0.017`.

## Review

Sheet: `artifacts/claude_takeover_20260927/review/homm3_cove_t2_buildings.png` (+ `.json`), the painting beside
`cv_v11` (before) and `cv_t2` (after) at rest and the three sweeps, then per-layer zooms.

Verdict by eye, under the rule above:
- **Rest** reads as the painting. The front faces carry the sprite, so the frame is the painting where Meshy covers
  it and the seed relief where it does not.
- **Sweeps** are better than `cv_v11` on every zoomed layer. The seed relief's black slabs and long yellow bars at
  sweep_left/right (`tbcvnix2`, `tbcvgmg4`, `tbcvsor2`, `tbcvpir2`, `tbcvdock`, `tbcvsmth`) are gone, and the buildings keep their shape:
  the tavern, halls, smithy and pirate ship turn as solid bodies instead of stretching.
- **No layer is broken**, so no Meshy layer beyond the stilt houses was reverted. `tbcvthgd` (rest dE 21.8) and
  `tbcvgmg4` (13.9) were checked by eye because their dE rose; both read as their sprite at rest, and the dE comes
  from the de-lit front against a painting with baked highlights, which the rule makes a diagnostic.
- **Known residuals**, not reverts:
  - `tbcvsay1`/`tbcvsay2` (relief, reverted on purpose) still streak at the sweeps, as in `cv_v11`.
  - At sweep_right and sweep_high the tavern deck's underside shows a dark wedge below its right edge (about 5000
    near-black px of 1920x1080, measured by rendering the sweep with and without `tbcvtave`). It is Meshy's textured
    hull, not a hole: removing the tavern shows ground there. The deck is the tavern's main feature, so it stays.
  - The large gold slab at sweep_right in the `tbcvgmg4` zoom is the same before and after, so it is not from this
    change.

Rest dE76 per zoomed layer (before -> after), diagnostic only: hal3 5.16 -> 4.74, cas3 6.16 -> 7.41, gmg4 6.05 -> 13.92,
tave 5.77 -> 6.72, mark 7.97 -> 8.98, smth 3.33 -> 4.84, thgd 5.06 -> 21.82, dock 7.34 -> 4.93, pir2 3.94 -> 5.4,
ass2 13.7 -> 5.22, sor2 7.62 -> 8.34, nix2 5.39 -> 6.72.

## Props and animation pass (2026-09-30, candidate `pb_v1`, installed)

`pb_v1` is seeded from `cv_t2` and adds Meshy props over the regions that `town_t2_streak_map.py` flags as streaking
at the reachable sweep poses. The camera range is unchanged. `cv_t2`, described above, is now the rollback.

- **Streak regions.** The main sources are the `tbcvsay2` relief body (up to 84k px) and the terrain: the mid-ground
  water edges, the reeds and rocks, and the cliff foot under the stilt houses.
- **Props.** Specs are in `tools/homm3_town_scene_meshes/town_t2_props_specs_groupB.py`.
  - Generated: `palm`, `reeds`, `agave` and `crag`.
  - Placed: 20 `agave` and 8 `reeds`.
  - Dropped by eye: 2 `crag` instances (pale beige, with the gain clamped near 2.0). The placer chose no `palm`
    position.
  - Credits: 84, logged in `artifacts/meshy_town_scene_meshes/_budget_props_20260930_groupB.json`.
- **Measured streak (stretched px, full scene):**

  | pose | before (`cv_t2`) | after (`pb_v1`) |
  |---|---|---|
  | sweep_left | 157743 | 141195 |
  | sweep_right | 163727 | 159963 |
  | sweep_high | 135381 | 125753 |

  One agave clump is visible at rest in the right mid-ground.
- **Still remaining.** `tbcvsay1` and `tbcvsay2` stay on relief after two Meshy failures, so their body streak is a
  building-level issue that props cannot cover.
- **Animation.**
  - 29 buried Fx groups were slid in front of the Meshy bodies with `town_t2_fx_occlusion.py snap`: the glints, the
    `sor2` / `nix2` glow and the `whr2` water. After the snap, the audit reports no hidden Fx.
  - Static, recorded and not animated in this pass, because the anim pass has no cloth kind: the pennants and flags
    on `mark`, `pir1` / `pir2`, `smth` and `tave`.
- **Review sheet:** `artifacts/claude_takeover_20260927/review/homm3_cove_props_pb_v1.png`.
- **Install.** Installed on 2026-09-30:
  - bundle sha256 `91642e4cb8b26299940bdb3e592f0caa47d79bfda3e8bcdd0d0c78278fabafb1`;
  - catalog sha256 `2dda576e993ee6aac3d8f2a9dbc9f285af47758a647a27c7660e7eefd5712691`;
  - rollback in `artifacts/town_scene_rollback/cove_20260930T233424Z`;
  - the validator is OK (`props=28/2types cr=84 pass=342/900`).
- **Depth source.** This pass was built on the lane's DA V2 Large background depth (`depth/da_large.npy`). A rebuild
  on the new img2img background depth maps (`artifacts/img2img_depth_maps/`) was done as candidate `bgd_v1`; see
  "Background depth A/B" below.
- **Adventure-map reuse: none.** The map-building sculpts are separate meshes, and Meshy is not used on map
  buildings, so only the technique could transfer, not the geometry.
- **Proof tier: installed payload.** Startup, runtime and user-visible proof are not yet done.

## Background depth A/B (2026-10-01, candidate `bgd_v1`, not installed)

`bgd_v1` is `pb_v1` with the img2img background depth as the only intended difference. Every `pb_v1` layer is carried
over and seated on the new ground.

- **Depth.** `artifacts/img2img_depth_maps/homm3_cove/background/Cove-in-background__depth_raw.png`
  (sha256 `c6b1328f56d811d3fea7c4335b8cede703ca1828bf00d93aad9286d6b9cf035d`) was registered by ECC affine (`town_full3d_bg_depth.py import`) to
  `depth/img2img_bg.npy` (sha256 `1331fc3766bcda01984df674a400cc1e4866bed6f52f519955dbeb28a68e64b9`). It is pinned in `work/background_depth.json` and recorded in
  `stage_report.json` `terrain.backgroundDepth`. Building depths are unchanged.
- **Environment.** `stage --parts terrain,sky,periphery,nearfield` with EXTSRC `town_all/cove/tex_v3/extsrc_bridge_blend`.
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
- **Renders:** `artifacts/homm3_cove_full3d/candidates/bgd_v1/renders/` (standard set).
- **Sheet** (pb_v1 | bgd_v1 | diff): `artifacts/claude_takeover_20260927/review/homm3_cove_bgd_v1_vs_pb_v1.png`.
- **By eye:** Every layer is present. The rest frame matches (2.0% of px over 24). The new ground is much nearer under the
  dock, the gem ponds, the sorcery and the thieves' guild (k about 0.5 to 0.7). The left cliff houses smear more at the
  sweeps. `tbcvgral` is not moved: its foot rays hit no ground in either candidate.
- **Measured streak (stretched px, full scene):**

  | pose | `pb_v1` (DA V2 Large) | `bgd_v1` (img2img) |
  |---|---|---|
  | sweep_left | 141195 | 259751 |
  | sweep_right | 159963 | 276174 |
  | sweep_high | 125753 | 225552 |
  | default | 256 | 157 |

  **Verdict:** Worse: the sweep streak roughly doubles, while the rest-pose residue drops. The new depth is not adopted for this town. `pb_v1` stays installed, and no Meshy
  credits were spent on the new depth.
- **Proof tier:** generated artifact. The bundle was built and editor-rendered; it is not installed.

## SSR water prototype (2026-10-01, candidates `ssr_v1` for Cove and Fortress, not installed)

**Proof tier.** Generated artifact. Both bundles were built and editor-rendered under the built-in renderer, and the
validator passes on both. Nothing is installed or deployed, and the in-game result is unproven.

- **What it is.** `tools/homm3_town_scene_meshes/town_full3d_ssr_water.py` (`stage` / `preview` / `sheet`) and the shader
  `unity/shaders/Homm3TownSsrWater.shader` (`Homm3Town/SsrWater`).
  - Opt-in per candidate. The tool refuses to run without `TOWN_FULL3D_CANDIDATE`. `write_catalog` adds `waterLook.screenSpaceReflection`
    and the extra entry in `bundleShaders` only when `stage_report.ssrWater` exists, and `copy_editor` copies the shader
    only when `build_spec.json` names it. Other towns build exactly as before.
  - Seeded from `pb_v1`, keeping the old DA depth and the props block.
- **Water geometry.** Both towns paint their water into the terrain albedo.
  - A hand-set frame-space classifier (`TOWNS[...]['mask']`) marks the painted water. It uses floor height, CIELAB
    colour, texture and ripple anisotropy, with a stricter anisotropy in the near band so painted rocks stay dry.
  - The terrain triangles under the dilated mask are copied into `Fx_SsrWater_0..2` fxmesh bins on the environment
    prefab. They use the same vertices, the painting's world up as the normal, and uv2 in world XZ metres.
  - The water's tint has the baked reflections painted out: a robust body colour plus a small share of the low-pass
    and of the fine detail. Its alpha is FlowWater's shore coordinate.
  - The `Fx_Water_*` strips (waterfalls, whirlpools, moat) stay on FlowWater.
- **Shader.** A FlowWater superset whose constant sky reflection is replaced by a raymarched reflection.
  - The ray is cast in view space and samples `_CameraDepthTexture` and `_CameraColorTexture`. There is no GrabPass,
    because the game renders through the scriptable Hex pipeline.
  - On a miss it uses the on-screen sky where the reflected direction lands on sky, otherwise `_SkyColor`, weighted by
    `_MissReflect`.
  - Hits on the water's own monocular floor plane are rejected.
- **Editor harness.** `RenderStates` turns on `depthTextureMode |= Depth` and blits `_CameraColorTexture` at
  `BeforeForwardAlpha`, both only when an SSR material is present. The lab `HexLit` gained a ShadowCaster pass so that
  terrain and buildings fill the depth texture.
- **Runtime source (built, not deployed).** `Homm3TownScene3d.cs` parses `waterLook.screenSpaceReflection`.
  - `EnsureRoot` sets `camera.depthTextureMode |= Depth` and `Clear` restores it.
  - The environment fails closed if an `*/SsrWater` material is undeclared, or if a declared piece is missing.
- **Contract.** `validate_town_scene3d_contract.py` (`check_ssr_water`) refuses any of these:
  - a bundle shader that reads `_CameraDepthTexture`, or an `Fx_SsrWater*` piece, without `waterLook.screenSpaceReflection`;
  - `requiresCameraDepthTexture` / `requiresCameraColorTexture` not true;
  - a GrabPass;
  - pieces that are not Fx_ environment pieces;
  - a runtime without the depth-texture request and restore.
  - Negative-tested by dropping the block and by flipping the flag.
- **Results.**
  - Cove: 729125 water px; bundle 251023128 bytes, sha256 `57bc9df87e21bdc0...`.
  - Fortress: 651879 water px; bundle 348130726 bytes, sha256 `24672b11e9c29e5c...`.
  - Renders and `renders/ssr_compare/pb_v1_vs_ssr_v1_*.png` sheets are in each candidate.
  - By eye: the stilt houses, plants and rocks are mirrored in the lagoon, and the painted rocks keep their outline.
- **Known artefacts.**
  - Screen-edge cut-off: rays that leave the frame fade to the miss colour.
  - Thin objects smear: reeds, masts and plant fronds stretch vertically because of the thickness heuristic.
  - Hard-edged patches of sky colour on far water, where the miss lands on sky.
  - The water copies the monocular floor, so at the sweeps it inherits the terrain's streaks.
  - Residues the mask cannot remove:
    - Fortress: green plant reflections and lily pads stay baked, so a plant can be reflected twice.
    - Cove: the wreck reflection.
  - Fortress mask edge: along the far shore under the temple and stilt houses the SSR piece ends in hard, dark
    blocky notches where the frame-space mask cuts between water and bank. The shore fade does not cover them yet.
  - Post-processing: the colour copy is pre-transparent and pre-post. TAA jitter, bloom and contour lines were not
    exercised.
- **Upright sprites with painted reflections** (`tbcvnmp1` waterfall, `tbcvsay1`/`tbcvsay2` stilt houses) are untouched.
  - Their footing is measured on the reflection's bottom row, which is what pulls the waterfall about 130 to 195 m in
    front of its cliff.
  - Cutting the reflection from the sprite mask would raise that bottom row to the true contact line. The footing
    depth would then move back to the cliff, which is a building restage and out of scope here.
  - Until then SSR reflects each sprite's own painted reflection a second time.
- **Hex SRP caveat.** The game's `GraphicsSettings` names a custom pipeline (`Hex.Render.HexRenderPipelineAsset`).
  - Whether `depthTextureMode` matters there, and whether the pipeline fills `_CameraDepthTexture` and
    `_CameraColorTexture` in the town scene, is unproven. Vanilla `Hex/Sea` binds both.
  - The pipeline also has native screen-space planar reflections (`BhCameraContext.screenSpacePlanarReflections` /
    `waterPlaneY`; `Hex/Sea` reads `_ReflectionHashTexture`), which are the native alternative.
- **Install (not done).**
  1. Deploy the plugin build containing the runtime change first.
  2. Then run `python tools/homm3_town_scene_meshes/install_town_scene3d.py cove artifacts/homm3_cove_full3d/candidates/ssr_v1/bundle fortress artifacts/homm3_fortress_full3d/candidates/ssr_v1/bundle`.
  3. Verify in game: the BepInEx log line `camera depthTextureMode ... for the SSR water`, and that reflections are
     present.

## Reproduce

```
TOWN_FULL3D_FACTION=cove python tools/homm3_town_scene_meshes/cove_t2_buildings.py status
TOWN_FULL3D_FACTION=cove TOWN_FULL3D_CANDIDATE=cv_t2 python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py candidate-init --seed-from cv_v11
#   (copy cv_v11/work/closing_walls.npz into cv_t2/work)
TOWN_FULL3D_FACTION=cove python tools/homm3_town_scene_meshes/cove_t2_stage.py fit
TOWN_FULL3D_FACTION=cove TOWN_FULL3D_CANDIDATE=cv_t2 python tools/homm3_town_scene_meshes/cove_t2_stage.py stage
TOWN_FULL3D_FACTION=cove TOWN_FULL3D_CANDIDATE=cv_t2 python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py bundle --faction cove
TOWN_FULL3D_FACTION=cove TOWN_FULL3D_CANDIDATE=cv_t2 python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py render --faction cove
TOWN_FULL3D_FACTION=cove TOWN_FULL3D_CANDIDATE=cv_t2 python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py validate --faction cove
TOWN_FULL3D_FACTION=cove TOWN_FULL3D_CANDIDATE=cv_t2 python tools/homm3_town_scene_meshes/t2_town_review.py --before cv_v11 \
    --zooms tbcvtave,tbcvhal3,tbcvsmth,tbcvmark,tbcvcas3,tbcvsa2p,tbcvdock,tbcvpir2,tbcvnix2,tbcvgmg4,tbcvsor2,tbcvass2 \
    --out artifacts/claude_takeover_20260927/review/homm3_cove_t2_buildings.png
```

Each heavy step runs through `python artifacts/claude_takeover_20260927/cpuslot.py -- ...`.
