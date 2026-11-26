# HoMM3 Necropolis: Meshy T2 town buildings (candidate t2_v1)

**Proof tier: generated artifact.** The painted-front t2_v1 (restaged 2026-09-30) was bundled offline through
unitylock and rendered in the Unity editor (`pan_*`). It passes three gates:

- the see-through gate, no worse than baseline `seam_v3` (976 px);
- the framing gate;
- `validate_town_scene3d_contract.py --catalog` (OK, 32 of 32 layers reachable).

The bundle is 207,660,689 bytes, sha256 `ed49e66867ae13cc21b3608f2838529e49147f9f7046fb300f69311f3c75bb7d`. It supersedes
the pre-painted-front bundle `c1c178e1...`.

It is **not installed**. There is no startup, runtime or user-visible proof.

- **Brief:** `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md`.
- **Cap:** `townCaps.homm3_necropolis` = 600.
- **Before:** the installed full-3D candidate `wall_v2`.
- **Tool:** `tools/homm3_town_scene_meshes/town_full3d_t2_meshy.py --faction necropolis`, with the commands
  `prep | generate | spent | fit | stage | revert | sheet | mainsheet`.
- **Meshy data:** `artifacts/meshy_town_scene_meshes/homm3_necropolis/<layer>/t2_a1/` holds `model.glb`, `task.json`,
  `fit.json` and `fit_viz.png`.
- **Rest dE per layer:** `artifacts/meshy_town_scene_meshes/homm3_necropolis/rest_de.json` (diagnostic only).

## Verdict (user rule 2026-09-29: Meshy geometry beats the painted relief)

**Deliver t2_v1.** All 29 meshed layers ship their Meshy body with a painted front.
**No layer is reverted:** none is fragmented, a flat slab, or missing its main feature at the sweeps.

- **At rest:** the frame reads as the painting. The painted front covers 99.2 to 100% of each layer's rest px.
- **At the sweeps:** the castle levels, dwellings, mage guild, tavern, market, silo and obelisk are solid objects.
  The relief before smeared on the dwellings and the cliff-side houses.
- **Sideways-yaw check:** `tbncdw_4` (57 deg) and `tbncdw_5_2` (39 deg) were checked by eye at all three sweeps.
  Neither shows a side or back where the painting has the front: the painted front carries the painting on the
  camera-facing surface, and their sides read as plausible walls.
- **Weakest layer:** `tbncdw_1`, the graveyard. It is thin (fit IoU 0.68) but still reads as the fence, tree and
  graves, so it is kept.

Rest dE76 is **diagnostic only**. The remaining distance to the painting comes from silhouette coverage (fit IoU 0.66 to
0.91), not colour.

**Painted front** (as in `docs/homm3_bulwark_t2_town_buildings.md`):

- Rest-seen faces are split to 4 px or less.
- Those faces take the de-lit painting in screen space at SUPER=2, shaded with a smooth camera-facing normal.
- The remainder keeps the Meshy atlas.
- Both parts are two-sided.

The old rule's result (every layer kept the relief on rest dE76) is superseded.

## Spend (shared ledger `artifacts/meshy_town_scene_meshes/_ledger.jsonl`, faction `homm3_necropolis`)

**435 credits of the 600 cap:** 29 image-to-3d calls at 15 cr each.

- **Call settings:** `ai_model="meshy-t2"`, `model_type="smart-topology"`, `should_texture=True`,
  `target_polycount` 8000, with no texture prompt or image.
- **Nothing else was spent:** no concept (image-to-image) calls, no retries and no contingency claims.
- **Outcome:** every task SUCCEEDED on the first pass.

**Layers.** 32 are reachable (the profile's native building levels):

- **Meshed:** 29, every row of the table below.
- **Skipped (0 cr):** these three keep the relief.
  - `tbncdw_6` and `tbncdw_6_2` are the cliff-face window and ledge painted on the rock, not a standalone structure.
  - `tbncdock` is a flat water pool and pier at ground level, which makes it a decal.
- **Not reachable:** 18 sprites are not referenced by any native building level, so no prefab uses them and they
  were not touched. They are `tbncdw_*_3`, `tbnchall_4`, `tbncmage_5`, `tbncext*`, `tbncboat`, `tbnchrd1` and
  `tbnchrd3`.

| layer | Meshy taskId | cr | fit IoU | rest silhouette IoU / sprite px covered | rest dE76 relief (wall_v2) | rest dE76 t2_v1 (painted front) | ships |
|---|---|---|---|---|---|---|---|
| tbncblak | `01a0ef7d-19a2-704a-88b5-7d5afa576bd2` | 15 | 0.791 | 0.7174 / 0.731 | 4.08 | 9.8 | Meshy + painted front |
| tbnccstl | `01a0ef7d-2534-7125-bc10-59cf3914c4eb` | 15 | 0.797 | 0.8153 / 0.8257 | 3.28 | 3.49 | Meshy + painted front |
| tbnccstl_2 | `01a0ef7d-215b-73e7-9fdd-68fe24084fbe` | 15 | 0.76 | 0.8228 / 0.8361 | 2.78 | 4.53 | Meshy + painted front |
| tbnccstl_3 | `01a0ef7d-1243-779b-8840-342a0240fe6e` | 15 | 0.809 | 0.8658 / 0.9014 | 2.77 | 4.37 | Meshy + painted front |
| tbncdw_0 | `01a0ef7d-1db9-70ed-b546-67c42ce0f67b` | 15 | 0.784 | 0.8034 / 0.8206 | 2.5 | 4.13 | Meshy + painted front |
| tbncdw_0_2 | `01a0ef7d-2c7b-75b2-9a91-c84e9176a252` | 15 | 0.777 | 0.8089 / 0.8332 | 2.81 | 3.44 | Meshy + painted front |
| tbncdw_1 | `01a0ef7d-1647-7079-a456-d8734faed16b` | 15 | 0.683 | 0.5833 / 0.5929 | 2.62 | 8.3 | Meshy + painted front |
| tbncdw_1_2 | `01a0ef7d-2927-74c9-9631-8d664138e620` | 15 | 0.789 | 0.7663 / 0.7909 | 2.38 | 4.88 | Meshy + painted front |
| tbncdw_2 | `01a0ef7d-cbda-75e7-8196-4baea5309f0d` | 15 | 0.679 | 0.6549 / 0.6866 | 3.43 | 6.89 | Meshy + painted front |
| tbncdw_2_2 | `01a0ef7d-d087-73cb-9d6d-ded561175f6b` | 15 | 0.734 | 0.7973 / 0.8483 | 4.13 | 6.13 | Meshy + painted front |
| tbncdw_3 | `01a0ef7d-d460-76d4-a846-7ce8962ec8b4` | 15 | 0.871 | 0.8834 / 0.8937 | 2.7 | 5.3 | Meshy + painted front |
| tbncdw_3_2 | `01a0ef7e-12a2-7267-a078-0fe8d3f2ce85` | 15 | 0.885 | 0.8652 / 0.8891 | 2.11 | 4.03 | Meshy + painted front |
| tbncdw_4 | `01a0ef7e-185b-725a-b1d5-60737f20155b` | 15 | 0.82 | 0.8146 / 0.8341 | 3.51 | 3.73 | Meshy + painted front |
| tbncdw_4_2 | `01a0ef7e-1c73-7465-b8cd-22129d081491` | 15 | 0.853 | 0.8241 / 0.8451 | 3.25 | 4.31 | Meshy + painted front |
| tbncdw_5 | `01a0ef7e-2110-7150-b517-e9517261adcc` | 15 | 0.829 | 0.7935 / 0.8103 | 2.9 | 4.53 | Meshy + painted front |
| tbncdw_5_2 | `01a0ef7e-2558-77f7-8911-ad011c710c57` | 15 | 0.8 | 0.812 / 0.8235 | 2.64 | 4.51 | Meshy + painted front |
| tbnchall | `01a0ef7e-ff22-70ad-a1f9-2201b089f97f` | 15 | 0.844 | 0.8238 / 0.8495 | 2.35 | 3.67 | Meshy + painted front |
| tbnchall_2 | `01a0ef7f-03cd-7092-add6-75c13050346e` | 15 | 0.768 | 0.7673 / 0.7748 | 2.3 | 4.12 | Meshy + painted front |
| tbnchall_3 | `01a0ef7f-0885-7184-8658-0ff495f3233e` | 15 | 0.789 | 0.788 / 0.7984 | 2.18 | 5.21 | Meshy + painted front |
| tbncholy | `01a0ef7f-421d-7130-a4b0-7c1417b5d824` | 15 | 0.661 | 0.7626 / 0.7683 | 1.84 | 5.5 | Meshy + painted front |
| tbnchrd2 | `01a0ef7f-5191-7353-ade2-a696c78646bf` | 15 | 0.746 | 0.771 / 0.7894 | 2.41 | 4.96 | Meshy + painted front |
| tbncmage | `01a0ef7f-84bc-74b1-ba55-ad255ac86ca6` | 15 | 0.913 | 0.8834 / 0.8916 | 1.97 | 3.6 | Meshy + painted front |
| tbncmage_2 | `01a0ef7f-8991-747e-89a5-d90d05095471` | 15 | 0.901 | 0.878 / 0.8934 | 2.11 | 3.68 | Meshy + painted front |
| tbncmage_3 | `01a0ef7f-938a-7626-a6e5-e9877d680c15` | 15 | 0.869 | 0.8596 / 0.8728 | 1.99 | 3.93 | Meshy + painted front |
| tbncmage_4 | `01a0ef82-fb4d-7209-b2d7-d484df4347af` | 15 | 0.885 | 0.8896 / 0.9047 | 1.86 | 4.55 | Meshy + painted front |
| tbncmark | `01a0ef83-00e5-7221-b97f-58b2219e50ca` | 15 | 0.839 | 0.7306 / 0.7418 | 2.21 | 5.22 | Meshy + painted front |
| tbncsilo | `01a0ef83-3bc6-703f-9d1e-60055615f864` | 15 | 0.745 | 0.7221 / 0.7398 | 1.97 | 6.11 | Meshy + painted front |
| tbncspec | `01a0ef83-3f53-77a0-88c6-b25c6ab25752` | 15 | 0.859 | 0.8493 / 0.871 | 3.38 | 4.14 | Meshy + painted front |
| tbnctvrn | `01a0ef83-446c-71c1-b3cc-4c99dc4481fb` | 15 | 0.756 | 0.8113 / 0.8192 | 2.15 | 4.3 | Meshy + painted front |
| **total** | 29 calls | **435** | | | | | |

**How rest dE76 is measured.** It is the mean CIELAB distance to the HoMM3 painting inside the layer's sprite mask
(clipped to the painted rect). Each layer is rendered with the environment plus that one layer, through the lane's
offline Hex/Lit preview at the rest camera, for both `wall_v2` and `t2_v1`.

## Method (t2_v1)

**Input.** Each sprite is cut out onto a white 1024 canvas at 900 px (LANCZOS). The mask is the closed native mask
inside the opaque alpha. `tbncspec` drops its flat cloud region, which stays a flat card in its own bin.

**Fit.** The fit uses `fit_mesh_to_sprite.Fitter` under the native city camera.

- The score is the F0.5 silhouette, counted only inside the painted rect.
- The search covers yaw and ground contact on the painted terrain's depth.
- A Y stretch of 0.8 to 1.25 is kept only if it raises IoU by more than 0.005.

**Trim.**

- **Ground pad:** the Meshy ground pad (the lowest 8% of the model's height) is split into triangles of at most 10 px.
  A pad triangle is dropped if it lies outside the sprite mask grown by 4 px.
- **Buried triangles:** a low triangle is also dropped if it sits more than 0.5% behind the painted terrain at rest.
  These showed as dark shards in the Unity render.
- **Frame clip:** triangles that leave the painted rect are clipped.
- **Orphan vertices:** these are removed, because the framing gate bounds a building by all the vertices in its bin.

**Orientation.** A rest-visible vertex whose Meshy normal faces more than 0.2 away from the camera is flipped, and its
triangles are rewound. Before this fix, the tavern's right block rendered black in Unity.

**Bake.** The atlas is 1024 texels square, laid out on the Meshy UVs.

- **Rest-visible faces take the sprite texels** by rest-camera projection.
  - Visibility is tested against the building's own depth buffer, with a 3x3 max guard.
  - The painting is blended in by facing, ramped over n.v 0.12 to 0.35. Flat ground-pad texels take the painting at
    any n.v > 0.
  - The texels are de-lit by the lane's Hex/Lit irradiance at the vertex normal. That normal is bent toward the sun
    until the painted colour is reachable with albedo at or below 0.95.
- **Hidden faces take the Meshy texture.**
  - It is colour-matched in log space, with the gain clamped to 0.6 to 1.6.
  - It is white-balanced against the rig's tinted irradiance (clamp 0.7 to 1.4). This removed a lavender cast.
  - Its normals are bent until the mean irradiance is at least 0.35.
- **Two-sided geometry:** every triangle gets a reversed twin. Meshy models are not closed shells, and without the
  twins the see-through gate failed.
- **Atlas size:** a 2048 atlas put the buildings' median painted texels/px at 4.46, above the near terrain's 4.0,
  which the contract refuses. Hence 1024. The bundle is 126 MB, against the installed 95 MB.

**Checks against the Stronghold findings (2026-09-29).**

- **UV flip:** trimesh flips glTF v. The UV-space raster is read top row first, so atlas row 0 is image row 0, and
  the Meshy texture is sampled without a flip. There is no scramble.
- **Rest visibility:** the test uses a 3x3 depth *max* guard, not a min, so painted texels are not falsely rejected.

## Review

- **Main sheet:** `artifacts/claude_takeover_20260927/review/homm3_necropolis_t2_buildings.png`. It shows painting |
  before `wall_v2` | after `t2_v1`, as Unity editor renders at `pan_default`, `pan_sweep_left`, `pan_sweep_right` and
  `pan_sweep_high`.
- **Building zooms:** `homm3_necropolis_t2_buildings_zoom_{1,2,3}.png`, from the offline Hex/Lit preview. Each shows
  painting | before | after at rest, then before | after at each sweep.
- **Renders:** `artifacts/homm3_necropolis_full3d/candidates/t2_v1/renders/`.
- **Bundle:** `artifacts/homm3_necropolis_full3d/candidates/t2_v1/bundle/homm3_town_scene3d_necropolis`
  (sha256 `ed49e668...`, painted front).

## Shared bake (2026-09-30)

The painted-front bake is `tools/homm3_town_scene_meshes/town_full3d_t2_paint.py`, the one T2 bake for all eleven factions. On 2026-09-30 it absorbed the last four copies: `rampart_t2_buildings.stage_split` (Rampart, Dungeon), `inferno_t2_integrate.stage_layer`, `town_full3d_t2_meshy.painted_front` (Necropolis, Bulwark) and `t2_rest_geometry.stage_painted_layer` (Castle, Tower). Where a lane's bake differs by design, the difference is a named parameter of the shared module, set at this lane's call site; no output was changed to force identity.

This lane's values (`town_full3d_t2_meshy.painted_front`): `subdivide_screen(seen_super=1)` (faces are split when drawn at frame px); the `sprite_fill` mask is the plate's opaque non-shadow alpha (`_plate_mask`); `sampler="scipy"`; `min_front_tris=50`; `meshy_albedo=` the atlas that `bake` colour-matched, so no gain is applied.

Restaging the sample layer tbnctvrn with the shared module into a scratch stage gives files byte-identical to this candidate's (`t2_v1`) staged bins, and so did the old code before the fold (`tools/homm3_town_scene_meshes/t2_bake_restage_check.py`; results in `artifacts/town_t2_bake_consolidation/`). The bundle was not rebuilt. Proof tier of this note: generated artifact.
