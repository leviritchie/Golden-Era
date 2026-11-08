# Fortress town scene: Meshy T2 buildings (candidate fr_t2)

**Status: installed payload.** `fr_t2` was installed in commit 7673d920f3. It was superseded on 2026-09-30 by the props
pass candidate `pb_v1`; see "Props and animation pass" below.

- Proof tier: installed payload. The bundle is built, editor-rendered, passes the lane validator and is installed.
- There is no startup, runtime or user-visible proof.

Brief: `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md`. The "before" is the installed candidate **fr_v4**.

## Verdict

**At the sweeps, fr_t2 is clearly better than fr_v4:**
- The castle levels become a real stepped temple with walls where fr_v4 showed streaked relief.
- The hydra ponds, wyvern nest, grail flower, dwellings and mage guild levels stay solid objects where fr_v4 stretches into rubber-sheet slabs.

**At rest, fr_t2 reads as the painting, somewhat softer than the relief.** Rest dE76 against the painting is 2.3-9.95 against fr_v4's 2.0-6.4 (table below). On 2026-09-29 the user decided that rest dE76 is a diagnostic only, not a revert gate. The reason is that functional geometry stays consistent at the sweeps while the relief warps. Every layer therefore ships its Meshy body unless the mesh is broken.

**Known defects:**
- **Residual relief pieces.** Sprite px the Meshy body misses at rest keep fr_v4's relief triangles (`Mesh_Body_resid_<layer>`). These cover 6-54% of each layer's sprite px; the worst are tbfrmark 54%, tbfrdw_1 42%, tbfrdw_2_2 40% and tbfrhall 38%. At the sweeps some of them show as floating fragments, most visibly small stepped slabs above the castle top.
- **tbfrspec** reads dim at rest (dE 9.95).
- **Hall platforms:** pale Meshy-texture edges show on them.
- **Bundle size:** the bundle is 331.7 MB against fr_v4's 94.6 MB, because of the 2048 Meshy textures plus the paint crops.

## Layers

**Meshed (30):**
- Castle: tbfrcstl, tbfrcstl_2, tbfrcstl_3.
- Hall: tbfrhall, tbfrhall_2, tbfrhall_3.
- Blacksmith: tbfrblak.
- Dwellings and upgrades: tbfrdw_0, tbfrdw_0_2, tbfrhrd2, tbfrdw_2, tbfrdw_2_2, tbfrdw_1, tbfrdw_1_2, tbfrdw_3_2.
- Specials: tbfrmark, tbfrsilo, tbfrspec.

Of those 30, twelve got an image-to-image concept step first, because the frame cuts their sprites off: tbfrmage, tbfrmage_2, tbfrmage_3, tbfrtvrn, tbfrdw_4, tbfrdw_4_2, tbfrdw_5, tbfrdw_5_2, tbfrdw_6, tbfrdw_6_2, tbfrdock and tbfrholy.

**Skipped:**
- tbfrdw_3 is a 42x49 glow-egg decal on a painted trunk, a tiny overlay rather than a standalone structure.
- The layers that are not reachable are not built at all: the _3 levels, hall_4, ext*, hrd1/hrd3, boat and text5.

**Reverted to the fr_v4 relief (broken mesh):**

| layer | reason |
|---|---|
| tbfrdw_3_2 | The egg-on-trunk decal's Meshy body collapsed to a thin sliver at rest, so the main feature (the egg) is missing. |

## Spend

- Total: **522 of 552 credits** (`townCaps["homm3_fortress"]`). No contingency claim; the unitReserve is untouched.
- Every billed call has its own line in `artifacts/meshy_town_scene_meshes/_ledger.jsonl` (faction `homm3_fortress`, with the task ids).
- Meshy spend for town buildings is now frozen.

| kind | calls | credits each | credits |
|---|---|---|---|
| image-to-3d meshy-t2, smart-topology, textured, sprite input | 18 | 15 | 270 |
| image-to-image concept (nano-banana-2) | 12 | 6 | 72 |
| image-to-3d meshy-t2 from the concept | 12 | 15 | 180 |
| **total** | 42 | | **522** |

## Method (`tools/homm3_town_scene_meshes/t2_fortress/`)

**Generation: `generate_t2_fortress.py`.**
- Input: the sprite scaled so its long side is 1024 (LANCZOS), flattened on white.
- For a frame-cut sprite, a concept step completes it first. The prompt is hand-written in `DESCRIBE` and HoMM3-only.
- Budget is checked from the ledger before every call and a ledger line is appended right after each create.
- At most 4 tasks run in parallel.

**Mesh preparation.**
- A glTF x-negation brings the model into the lane's left-handed frame.
- The castle levels get mesh surgery (`CUT`): the painted water reflection that Meshy built as a hanging keel is removed.
- Their fit ignores the sprite rows below the painted waterline (`FIT_ROW_MAX`).

**Fit: `fortress_t2_buildings.py fit`.**
- Uses `fit_mesh_to_sprite.Fitter` under the native rest camera: yaw, uniform scale and ground-contact pixel, scored by F-beta 0.5 against the lane mask, plus an optional vertical stretch.
- Canopy-hung layers take the relief lane's ring footing depth.
- Yaw is kept to Meshy's input-front hemisphere: 140-220°, or 120-240° for concept inputs. A free 360° search landed on the back of near-symmetric silhouettes. Rest-colour correlation was measured and found too weak to break those ties (|r| < 0.05 on most layers).
- F-beta 0.64-0.95.

**Bake: `fortress_t2_buildings.py stage`.** This is the Rampart lane's painted-front bake, ported, because `rampart_t2_buildings.py` refuses other factions.
- **Framing trim:** triangles past the painted rect are trimmed by the Factory lane's rule, so the `buildings` framing gate is not re-aimed.
- **Painted front (`Mesh_Body_<layer>`):**
  - Rest-drawn faces are split in screen space to 4 px edges.
  - A face is "seen" if it owns at least 60% of its rest px, or its centroid or any corner lies at the rest z-buffer surface.
  - Seen faces take the painting by screen position, with no recolour. The painting is de-lit by the Hex/Lit irradiance of a smooth camera-facing normal.
- **Meshy remainder (`Mesh_BodyM_<layer>`):** every other face keeps the Meshy texture, gain-matched per channel (median, linear, clamped 0.5-2) to the de-lit painting.
- **Residual (`Mesh_Body_resid_<layer>`):** fr_v4 relief triangles cover the sprite px the body leaves uncovered at rest.
- All pieces are two-sided, because Meshy shells are open and the game uses Cull Back.
- Fx_ bins and particles keep their fr_v4 positions.

**Stale bugs, fixed along the way (the rest-dE numbers changed with them):**
- My first bake baked the painting into the Meshy atlas. It had Stronghold's 3x3 depth-min visibility bug, which failed about 60% of visible texels.
- It also treated inward-normal faces as hidden. Meshy's authored normals point inward on whole regions.
- The UV convention was checked and is correct: colours at UV-seam duplicates agree, 3.1 against 11.4 flipped.

**Review: `fortress_t2_review.py`.**
- `sheet` / `zoom`: painting | fr_v4 | fr_t2 at rest and the sweeps.
- `isolate --cull cw` + `restde`: per-layer rest dE76. Each render is the environment plus that one layer, back-face culled, compared with the painting of that layer alone over its sprite mask.
- `pans`: culled previews.

## Rest dE76 (diagnostic)

Mean over the sprite mask; fr_v4 is the before, fr_t2 the after.

| layer | fr_v4 | fr_t2 |
|---|---|---|
| tbfrcstl | 2.57 | 3.12 |
| tbfrcstl_2 | 2.67 | 2.99 |
| tbfrcstl_3 | 2.29 | 2.27 |
| tbfrhall | 3.39 | 6.38 |
| tbfrhall_2 | 2.89 | 5.61 |
| tbfrhall_3 | 2.74 | 5.35 |
| tbfrblak | 1.98 | 5.25 |
| tbfrdw_0 | 2.82 | 6.33 |
| tbfrdw_0_2 | 5.39 | 6.38 |
| tbfrhrd2 | 5.48 | 5.45 |
| tbfrdw_2 | 2.11 | 3.03 |
| tbfrdw_2_2 | 2.09 | 3.55 |
| tbfrdw_1 | 2.69 | 4.62 |
| tbfrdw_1_2 | 3.18 | 4.71 |
| tbfrdw_3_2 | 4.55 | 9.58 (reverted to relief) |
| tbfrmark | 2.29 | 5.59 |
| tbfrsilo | 2.91 | 5.18 |
| tbfrspec | 4.32 | 9.95 |
| tbfrmage | 2.05 | 4.58 |
| tbfrmage_2 | 2.39 | 2.61 |
| tbfrmage_3 | 2.16 | 5.37 |
| tbfrtvrn | 5.09 | 5.65 |
| tbfrdw_4 | 4.44 | 3.56 |
| tbfrdw_4_2 | 4.31 | 3.74 |
| tbfrdw_5 | 2.17 | 4.26 |
| tbfrdw_5_2 | 2.44 | 5.45 |
| tbfrdw_6 | 6.40 | 4.69 |
| tbfrdw_6_2 | 6.11 | 5.45 |
| tbfrdock | 4.65 | 4.01 |
| tbfrholy | 3.65 | 5.03 |

## Gates and outputs (candidate `artifacts/homm3_fortress_full3d/candidates/fr_t2`)

**Gates:**
- **Framing gate** (`S.write_catalog`): pass.
- **See-through** (`stronghold_full3d_scene.py --faction fortress cull`): 123 px, against fr_v4's 25015. This is report-only, because Fortress has no baseline row.
- **Validator:** `town-scene3d-contract: OK homm3_fortress layers=31 reachable=31 ... bundle=present ... framing=zoom1.21/pan0.5 full3d=on`.

**Outputs:**
- **Bundle:** `bundle/homm3_town_scene3d_fortress`, built through cpuslot + unitylock. sha256 `f8abfd6f2bfa4bb661ad04731a0bedbb336f6415d783641beddf407cb23506e6`, 331,703,164 bytes.
- **Editor renders:** `renders/`. The render was OK: rc 0, through cpuslot + unitylock.
- **Review sheet:** `artifacts/claude_takeover_20260927/review/homm3_fortress_t2_buildings.png`.

**Install:** installed with `install_town_scene3d.py fortress .../fr_t2/bundle` (commit 7673d920f3). Superseded by `pb_v1`
(below); `fr_t2` is now the rollback, in `artifacts/town_scene_rollback/fortress_20260930T232603Z`.

## Shared bake (2026-09-30)

The painted-front bake is `tools/homm3_town_scene_meshes/town_full3d_t2_paint.py`, one module for Fortress, Factory, Cove and Stronghold (it absorbed the Cove / Stronghold copy `t2_painted_front.py`), and since the second fold of 2026-09-30 the one T2 bake for all eleven factions. Restaging the sample layer tbfrholy with the merged module into a scratch stage gives files byte-identical to this candidate's staged bins (`tools/homm3_town_scene_meshes/t2_bake_restage_check.py`). The bundle was not rebuilt.

## Props and animation pass (2026-09-30, candidate `pb_v1`, installed)

`pb_v1` is seeded from `fr_t2` and adds Meshy props over the regions that `town_t2_streak_map.py` flags as streaking
at the reachable sweep poses. The camera range is unchanged.

- **Streak regions.** The painted tree trunks, and the misty background trees of the swamp forest.
- **Props.** Specs are in `tools/homm3_town_scene_meshes/town_t2_props_specs_groupB.py`.
  - Generated: `cypress`, `bgtree`, `reeds` and `fern`. The first `cypress` concept was rejected, and it is kept in
    `rejected_concept_1/`.
  - Placed: 13 `reeds` and 8 `fern`.
  - Dropped by eye: all 9 `bgtree` instances (pale white trunks and a mint canopy). The placer chose no `cypress`
    position.
  - Credits: 90 (4 concepts, 1 re-concept and 4 meshes), logged in
    `artifacts/meshy_town_scene_meshes/_budget_props_20260930_groupB.json`.
- **Measured streak (stretched px, full scene):**

  | pose | before (`fr_t2`) | after (`pb_v1`) |
  |---|---|---|
  | sweep_left | 95904 | 90559 |
  | sweep_right | 90815 | 80171 |
  | sweep_high | 69568 | 59640 |

  The props are small marsh plants on the right bank. Most of the tree-trunk and water-reflection smear remains.
- **Animation.**
  - Buried Fx were slid in front of the Meshy bodies along the rest camera ray with `town_t2_fx_occlusion.py snap`,
    so the rest frame is unchanged. There were 4 groups: the `tbfrcstl_3` flame, the `tbfrtvrn` flame and the
    `tbfrdw_6_2` water. After the snap, the audit reports no hidden Fx.
  - Static, recorded and not animated in this pass: the market boats' bob and the pennants.
- **Review sheet** (painting | before | after, at rest and sweeps):
  `artifacts/claude_takeover_20260927/review/homm3_fortress_props_pb_v1.png`.
- **Install.** Installed on 2026-09-30:
  - bundle sha256 `75e12e2783107957b5e60909d8492538b343fe97e95ccd4187c1602f43b86a4a`;
  - catalog sha256 `d290f4d5669ef55c1d8b00789dd9454e77a17f9c60b7443633ad2bf3271d2cda`;
  - rollback in `artifacts/town_scene_rollback/fortress_20260930T232603Z`;
  - the validator is OK (`props=21/2types cr=90 pass=342/900`).
- **Depth source.** This pass was built on the lane's DA V2 Large background depth (`depth/da_large.npy`). A rebuild
  on the new img2img background depth maps (`artifacts/img2img_depth_maps/`) was done as candidate `bgd_v1`; see
  "Background depth A/B" below.
- **Adventure-map reuse: none.** The map-building sculpts are separate meshes, and Meshy is not used on map
  buildings, so only the technique could transfer, not the geometry.
- **Proof tier: installed payload.** Startup, runtime and user-visible proof are not yet done.

## Background depth A/B (2026-10-01, candidate `bgd_v1`, not installed)

`bgd_v1` is `pb_v1` with the img2img background depth as the only intended difference. Every `pb_v1` layer is carried
over and seated on the new ground.

- **Depth.** `artifacts/img2img_depth_maps/homm3_fortress/background/Fortress-in-background__depth_raw.png`
  (sha256 `92d9f96b21121c20b3ba8aa7527d42889db33b2cfaa7ced960c0feb95b98a0f5`) was registered by ECC affine (`town_full3d_bg_depth.py import`) to
  `depth/img2img_bg.npy` (sha256 `89e7093bfc0fb7c377dec437926fb0355c2ce129bdfce82cf7c978b1a677c496`). It is pinned in `work/background_depth.json` and recorded in
  `stage_report.json` `terrain.backgroundDepth`. Building depths are unchanged.
- **Environment.** `stage --parts terrain,sky,periphery,nearfield` with EXTSRC `town_all/fortress/tex_seam/extsrc_bridge_blend_s11` (the lane default `tex/extsrc_p2_blend` fails the control: it has a different right-hand extension).
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
- **Renders:** `artifacts/homm3_fortress_full3d/candidates/bgd_v1/renders/` (standard set).
- **Sheet** (pb_v1 | bgd_v1 | diff): `artifacts/claude_takeover_20260927/review/homm3_fortress_bgd_v1_vs_pb_v1.png`.
- **By eye:** Every layer is present. The rest frame matches (2.0% of px over 24, at building and prop edges). At the
  sweeps the left trees and the water edges smear more. `Fx_Flame_0_1_tbfrmage_3` is newly part-occluded (0.27);
  the snap rule leaves it, because the median front is behind the flame.
- **Measured streak (stretched px, full scene):**

  | pose | `pb_v1` (DA V2 Large) | `bgd_v1` (img2img) |
  |---|---|---|
  | sweep_left | 90559 | 183883 |
  | sweep_right | 80171 | 176279 |
  | sweep_high | 59640 | 131531 |
  | default | 1105 | 173 |

  **Verdict:** Worse: the sweep streak roughly doubles, while the rest-pose residue drops. The new depth is not adopted for this town. `pb_v1` stays installed, and no Meshy
  credits were spent on the new depth.
- **Proof tier:** generated artifact. The bundle was built and editor-rendered; it is not installed.

## SSR water prototype (2026-10-01, candidate `ssr_v1`, not installed)

See `docs/homm3_cove_t2_town_buildings.md` section "SSR water prototype". It covers both towns: method, contract, artefacts, the Hex SRP caveat and the install steps. Proof tier: generated artifact.
