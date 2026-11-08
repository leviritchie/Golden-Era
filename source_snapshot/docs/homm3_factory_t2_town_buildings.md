# Factory town scene: Meshy T2 buildings (candidate fa_v9_t2)

**Status: installed payload.** `fa_v9_t2` was installed in commit 7673d920f3. It was superseded on 2026-09-30 by the
props pass candidate `pb_v1`; see "Props and animation pass" below.

- Proof tier: installed payload. The bundle is built, editor-rendered, passes the lane validator and is installed.
- There is no startup, runtime or user-visible proof.

Brief: `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md`. The "before" is the installed candidate **fa_v4**.
Meshes and the first 17 fits came from the earlier Factory agent (`artifacts/meshy_town_scene_meshes/homm3_factory/HANDOFF.md`);
they were reused, not regenerated.

## Verdict

**At the sweeps, fa_v9_t2 is better than fa_v4.**
- The towers behind the grail and the castle's right side no longer turn into the tall striped rubber-sheet slabs that
  fa_v4 shows at sweep_left / sweep_high.
- The mage-guild towers, the tavern, the blacksmith, the dwellings' factory buildings and the watchtowers stay solid
  objects at every pose.

**At rest, it reads as the painting.** Rest-seen faces carry the painting itself (painted-front bake). Rest dE76 was
not measured for Factory: on 2026-09-29 the user made it a diagnostic only, not a revert gate. The review here was by
eye, at rest and at the three sweeps.

**Known defects:**
- **Residual relief pieces.** Sprite px the Meshy body misses at rest keep fa_v4's relief triangles
  (`Mesh_BodyRest_<layer>`, two-sided). They cover 4-29% of each layer's sprite px. The worst are tbfacas2 29%,
  tbfahrd2 27%, tbfamage 24%, tbfaup_2 23% and tbfamark 22%. At the sweeps the windmill sails and the fences around the
  sheds are relief pieces.
- **tbfaup_4** (the carved stone door): its Meshy face is a flat, darker slab. It is solid and keeps its shape, so it
  is not reverted, but it reads duller than the painting.
- **tbfaspc1:** the framing trim drops 1800 triangles of the part Meshy completed past the painted rect's left edge.
  The sprite is cut there too, so nothing painted is lost.
- **Bundle size:** 356.0 MB against fa_v4's 88 MB (2048 Meshy textures plus the paint crops).

## Layers

**Meshed (29):**
- Castle: tbfacas3, tbfacstl.
- Hall: tbfahal3, tbfahal2, tbfahall.
- Mage guild: tbfamag4, tbfamag3, tbfamag2, tbfamage.
- Specials: tbfaholy, tbfatvrn, tbfablak, tbfamark, tbfamrch, tbfaspc1, tbfasilo.
- Dwellings and upgrades: tbfadw_0, tbfaup_0, tbfadw_1, tbfaup_1, tbfadw_3, tbfaup_3, tbfadw_5, tbfaup_5, tbfadw_6,
  tbfaup_6, tbfaup_4, tbfaup_2, tbfadw_4.

**Reused meshes:**
- tbfacas2 uses the tbfacas3 mesh.
- tbfahrd2 uses the tbfaup_2 mesh.

**Skipped:** tbfadw_2 is a ground decal (a strip of crates and fence), so it keeps the fa_v4 relief.

**Reverted to the fa_v4 relief (broken mesh):**

| layer | reason |
|---|---|
| tbfadw_4 | The mine doorway's dark opening reads at rest as faceted, Meshy-textured wood: the main feature (the black opening) is missing. It is also the weakest fit, F0.5 0.787 with the yaw at the edge of the window. |

The revert list lives in `factory_t2_stage.py` (`REVERTED`), and `restore --layer L` applies it.

## Spend

- **435 of 492 credits** (`townCaps["homm3_factory"]`): 29 image-to-3d meshy-t2 calls at 15 credits each, one ledger
  line per call in `artifacts/meshy_town_scene_meshes/_ledger.jsonl` (faction `homm3_factory`).
- No new spend in this pass; Meshy spend for town buildings is frozen. No contingency claim.

| kind | calls | credits each | credits |
|---|---|---|---|
| image-to-3d meshy-t2, textured, sprite input | 29 | 15 | 435 |

## Method

**Tools:**
- `tools/homm3_town_scene_meshes/factory_t2_meshy.py` generated the meshes.
- `tools/homm3_town_scene_meshes/factory_t2_stage.py` does `fit`, `stage` and `restore`.
- `tools/homm3_town_scene_meshes/town_full3d_t2_paint.py` holds the shared painted-front bake, extracted from the
  Rampart / Fortress lanes.

**Fit.**
- `fit_mesh_to_sprite.Fitter` under the native rest camera: yaw, uniform scale and ground-contact pixel on the
  calibrated terrain depth, scored by F0.5 against the sprite's building mask, plus an optional vertical stretch.
- Yaw is kept to Meshy's input-front hemisphere (140-220).
- F0.5 is 0.79-0.97. The weakest fits are tbfadw_4 0.787 (reverted), tbfaup_2 0.854, tbfahrd2 0.854 and tbfacas2 0.852.

**Bake (`stage`).**
- **Framing trim:** triangles with any vertex left of, above or below the painted rect are dropped, and so are
  triangles wholly right of it.
  - The bottom edge became strict on this candidate. tbfatvrn's Meshy base reached 10 px below the painted rect, which
    moved the building union from 0.6236 to 0.6323 of the frame. That re-aimed the `buildings` framing and put
    tbfatvrn and tbfaup_5 out of the visible region at rest, so the framing gate failed.
- **Painted front (`Mesh_Body_<layer>`):**
  - Rest-drawn faces are split in screen space to 4 px edges.
  - A face counts as front if it owns at least 60% of its rest px, or its centroid or a corner lies at the rest
    z-buffer surface.
  - Front faces take the painting by screen position, de-lit by the Hex/Lit irradiance of a camera-facing normal.
- **Meshy remainder (`Mesh_BodyM_<layer>`):**
  - The Meshy texture, per-channel median gain-matched to the de-lit painting (clamped 0.5-2).
  - Its shading normals are wrapped 0.5 toward the key light. The Factory rig has near-zero equatorial ambient, and
    walls facing away from the key would otherwise render near-black at the sweeps.
- **Residual (`Mesh_BodyRest_<layer>`):** fa_v4 relief front triangles over the sprite px the body's rest silhouette
  (grown 2 px) leaves uncovered, for components of at least 20 px.
- All three pieces are two-sided, because Meshy shells are open and the game uses Cull Back.
- Fx_ bins keep their fa_v4 positions.

**Terrain seed.**
- The candidate was seeded from **fa_v8_mirror** (`candidate-init --seed-from fa_v8_mirror`). fa_v8_mirror differs
  from fa_v4 only in the environment prefab; the building prefabs are identical, so the merge is clean.
- Its stage report names the layered-depth back-fill `bundle/terrain_streak.npz`, which candidate-init does not copy.
  The file was copied from `fa_v5_ldi/bundle` after checking that its sha256 matched the report (0ac003de1b6e...).

**Review.**
- `tools/homm3_town_scene_meshes/t2_fortress/fortress_t2_review.py` with `TOWN_FULL3D_FACTION=factory`.
- `pans` / `zoom --renders culled` gave the per-building check against the painting and fa_v4.
- `isolate --cull cw` rendered the suspect layers one by one.
- `sheet --renders unity` built the brief's sheet.

## Gates and outputs (candidate `artifacts/homm3_factory_full3d/candidates/fa_v9_t2`)

**Gates:**
- **Framing gate** (`S.write_catalog`): pass (zoom 1.17, pan 0.5).
- **See-through** (`stronghold_full3d_scene.py --faction factory cull`): 0 px. This is report-only, because Factory
  has no baseline row.
- **Validator:** `town-scene3d-contract: OK homm3_factory layers=32 reachable=32 ... bundle=present ...
  framing=zoom1.17/pan0.5 full3d=on ... panVoid=0 ... streakMax=1.250`.

**Outputs:**
- **Bundle:** `bundle/homm3_town_scene3d_factory`, built through cpuslot + unitylock. sha256
  `e2d9198d55104bd888b7e1e2d701604c26998631d89f36a7eeb550d2a26ab70f`, 356,023,256 bytes.
- **Editor renders:** `renders/`. The render was OK: rc 0, through cpuslot + unitylock.
- **Review sheet:** `artifacts/claude_takeover_20260927/review/homm3_factory_t2_buildings.png`.

**Install:** installed with `install_town_scene3d.py factory .../fa_v9_t2/bundle` (commit 7673d920f3). Superseded by
`pb_v1` (below); `fa_v9_t2` is now the rollback, in `artifacts/town_scene_rollback/factory_20260930T234226Z`.

## Shared bake (2026-09-30)

The painted-front bake is `tools/homm3_town_scene_meshes/town_full3d_t2_paint.py`, one module for Fortress, Factory, Cove and Stronghold (it absorbed the Cove / Stronghold copy `t2_painted_front.py`), and since the second fold of 2026-09-30 the one T2 bake for all eleven factions. Restaging the sample layer tbfahal3 with the merged module into a scratch stage gives files byte-identical to this candidate's staged bins (`tools/homm3_town_scene_meshes/t2_bake_restage_check.py`). The bundle was not rebuilt.

## Props and animation pass (2026-09-30, candidate `pb_v1`, installed)

`pb_v1` is seeded from `fa_v9_t2` and adds Meshy props over the regions that `town_t2_streak_map.py` flags as
streaking at the reachable sweep poses. The camera range is unchanged.

- **Streak regions.** The `Mesh_Back_Terrain` canyon walls behind the elevator, and the mesa edges of the mid ground.
- **Props.** Specs are in `tools/homm3_town_scene_meshes/town_t2_props_specs_groupB.py`.
  - Generated: `mesa`, `joshua` and `scrub`.
  - Placed: 6 `scrub` and 4 `joshua`.
  - Dropped by eye: all 3 `mesa` instances, which floated in front of the canyon wall.
  - Credits: 63, logged in `artifacts/meshy_town_scene_meshes/_budget_props_20260930_groupB.json`.
- **Measured streak (stretched px, full scene):**

  | pose | before (`fa_v9_t2`) | after (`pb_v1`) |
  |---|---|---|
  | sweep_left | 6106 | 5572 |
  | sweep_right | 22833 | 19821 |
  | sweep_high | 7464 | 6203 |

  The canyon-wall streak, which is the main part, remains.
- **Animation.**
  - Buried Fx were slid in front of the Meshy bodies with `town_t2_fx_occlusion.py snap`: 4 groups, the `tbfacas3`
    wheel and its front, and the `tbfaholy` track and its front. After the snap, the audit reports no hidden Fx.
  - Static, recorded and not animated in this pass, because no measured anim-pass kind fits them:
    - the `tbfacas3` left cog and drums;
    - the `up_3` flywheel, crank rods and governor.
  - The adventure-map `AVGarma` rotor and `AVGauto` smoke in `map_building_anim_spec.json` are on different sculpts.
- **Review sheet:** `artifacts/claude_takeover_20260927/review/homm3_factory_props_pb_v1.png`.
- **Install.** Installed on 2026-09-30:
  - bundle sha256 `435960f62827efd8ed80df762916708f725bd7e5f1fe756c1e9384ed9deb3a65`;
  - catalog sha256 `56bbf5a6f4bbc468decff90e5f929060732f3cdab422fd1c28f6d0e993977177`;
  - rollback in `artifacts/town_scene_rollback/factory_20260930T234226Z`;
  - the validator is OK (`props=10/2types cr=63 pass=342/900`).
- **Depth source.** This pass was built on the lane's DA V2 Large background depth (`depth/da_large.npy`). A rebuild
  on the new img2img background depth maps (`artifacts/img2img_depth_maps/`) was done as candidate `bgd_v1`; see
  "Background depth A/B" below.
- **Adventure-map reuse: none.** The map-building sculpts are separate meshes, and Meshy is not used on map
  buildings, so only the technique could transfer, not the geometry.
- **Proof tier: installed payload.** Startup, runtime and user-visible proof are not yet done.

## Background depth A/B (2026-10-01, candidate `bgd_v1`, not installed)

`bgd_v1` is `pb_v1` with the img2img background depth as the only intended difference. Every `pb_v1` layer is carried
over and seated on the new ground.

- **Depth.** `artifacts/img2img_depth_maps/homm3_factory/background/Factory-in-background__depth_raw.png`
  (sha256 `0f237f1c280e15cbdfa6c13f27b6467e336a46af4ef8f91541341df8b669b0a1`) was registered by ECC affine (`town_full3d_bg_depth.py import`) to
  `depth/img2img_bg.npy` (sha256 `a7cd9217517248f11bcbaa60da581984149f694867bc88f8000913b33ec6f1d2`). It is pinned in `work/background_depth.json` and recorded in
  `stage_report.json` `terrain.backgroundDepth`. Building depths are unchanged.
- **Environment.** `stage --parts terrain,sky,periphery,nearfield` with EXTSRC `town_all/factory/tex_seam/extsrc_bridge_blend_s11` (the lane default `tex/extsrc_p2_blend` fails the control).
  - The same restage on the old depth (control `ctl_v1`, `artifacts/claude_takeover_20260927/town_all/bgdepth_groupB/env_compare.py`) reproduces `pb_v1`'s env bins.
    The nearfield scatter is the exception: it drifts with floor area independently of depth.
- **Buildings.**
  - Buildings: each building prefab is slid along its rest rays onto the new ground by a uniform scale about the rest
    camera. The prefab origin is the camera, so the rest frame is unchanged. k is the median foot-ray ratio of the new
    ground to `pb_v1`'s ground (`artifacts/claude_takeover_20260927/town_all/bgdepth_groupB/snap_buildings.py`; per layer in `work/building_snap.json`). The
    lane's Meshy re-fit tools write shared fit records, so they were not re-run.
  - **LDI and mirror re-applied.** The stale `Mesh_Back_*` bins (old depth) were removed, and then
    `town_full3d_ldi.py --faction factory apply` was re-run (3798 cuts; `terrain_streak.npz` sha `01595431...`, which
    the contract re-measures: `streakMax=1.250`). After that, `town_full3d_mirror.py apply --orig bgdorig_v1` was run.
    `bgdorig_v1` is the uncut terrain staged on the same pinned depth; its unity_project was pruned after use. The LDI
    and mirror passes have no old-depth control in this run.
- **Props.** Each instance keeps its type, yaw and rest pixel. Its base slides along the rest ray onto the new ground
  and its height scales with the distance (`artifacts/claude_takeover_20260927/town_all/bgdepth_groupB/snap_props.py`). On the old-depth control the ratio is
  1.0000 ± 0.0005.
- **Fx.** Re-audited with `town_t2_fx_occlusion.py audit`.
- **Renders:** `artifacts/homm3_factory_full3d/candidates/bgd_v1/renders/` (standard set).
- **Sheet** (pb_v1 | bgd_v1 | diff): `artifacts/claude_takeover_20260927/review/homm3_factory_bgd_v1_vs_pb_v1.png`.
- **By eye:** Every layer is present. At rest, the distant `tbfadw_1` / `tbfaup_1` dwelling now shows over the painted
  ridge at about frame (540-620, 130-280). The building is unchanged at rest by construction; the new depth puts the
  ridge in front of it farther back than the building, so the ridge no longer hides it. This is a rest-frame
  regression that comes from the depth itself. The canyon walls smear more at the sweeps.
- **Measured streak (stretched px, full scene):**

  | pose | `pb_v1` (DA V2 Large) | `bgd_v1` (img2img) |
  |---|---|---|
  | sweep_left | 5572 | 24383 |
  | sweep_right | 19821 | 58065 |
  | sweep_high | 6203 | 25512 |
  | default | 127 | 1087 |

  **Verdict:** Worse: the sweep streak is 3 to 4 times higher, and the rest-pose residue rises too. The new depth is not adopted for this town. `pb_v1` stays installed, and no Meshy
  credits were spent on the new depth.
- **Proof tier:** generated artifact. The bundle was built and editor-rendered; it is not installed.
