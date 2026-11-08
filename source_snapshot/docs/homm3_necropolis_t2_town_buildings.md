# HoMM3 Necropolis: Meshy T2 town buildings (candidate t2_v1)

**Proof tier: generated artifact.** The t2_v1 bundle was built offline through unitylock and rendered in the Unity
editor. It passed three gates:

- the see-through gate, no worse than baseline (976 px in total, against 6679 for the installed candidate);
- the framing gate;
- `validate_town_scene3d_contract.py --catalog`.

It is **not installed**. There is no startup, runtime or user-visible proof.

- **Brief:** `artifacts/meshy_town_scene_meshes/_BRIEF_t2_towns.md`.
- **Cap:** `townCaps.homm3_necropolis` = 600.
- **Before:** the installed full-3D candidate `wall_v2`. Its catalog matched the Golden Era install when this work
  started.
- **Tool:** `tools/homm3_town_scene_meshes/town_full3d_t2_meshy.py`. Its commands are
  `prep | generate | spent | fit | stage | sheet | mainsheet`.
- **Meshy data:** `artifacts/meshy_town_scene_meshes/homm3_necropolis/<layer>/t2_a1/` holds `model.glb`, `task.json`,
  `fit.json` and `fit_viz.png`.
- **Rest dE per layer:** `artifacts/meshy_town_scene_meshes/homm3_necropolis/rest_de.json`.

## Verdict

> **Superseded rule, 2026-09-29.** The user decided that Meshy geometry beats the painted relief. Rest dE76 is now
> diagnostic only and is never a revert gate.
>
> The planned delivery is t2_v1 restaged with the painted front (as in `docs/homm3_bulwark_t2_town_buildings.md`),
> with only genuinely broken meshes reverted.
>
> **That restage has NOT been run yet.** The verdict below is the old rule's result, and t2_v1's staged bins are still
> the pre-painted-front bake.

**Do not install t2_v1.** The per-layer rest rule says a layer ships its Meshy body only if its rest dE76 against the
painting beats the installed relief. **No layer wins.** All 29 keep the `wall_v2` relief, so the delivered per-layer
mix is `wall_v2` itself. t2_v1 is kept as the measured all-Meshy candidate for review.

**At rest.** Every Meshy layer is 1.45x to 4.2x further from the painting than the relief:

- The relief is a projection of the painting at the rest camera, so it is near exact by construction.
  Its mean dE76 is 1.8 to 4.1.
- The Meshy layers score a mean dE76 of 5.3 to 14.7 (table below).
- A Meshy body fitted to the sprite reaches a silhouette IoU of only 0.58 to 0.89.
- As a result, 10 to 41% of each sprite's pixels go uncovered and show terrain.
- The painted texels also land on surfaces that are not where the painter drew them.

The worst layers:

- `tbncblak`: the forge columns sit inward of the painted ones.
- `tbncdw_1`: the graveyard came out as a thin fence on a mound (IoU 0.58).
- `tbncdw_2`, `tbncdw_3` and `tbncdw_4`.
- `tbncmark`: Meshy built a dark arched shrine where the painting has a lit white house.

In `pan_default` the layout, palette and building identities still read as the Necropolis painting, but clearly
below the relief. The castle and hall silhouettes differ, and the fits come out narrower than the sprites.

**At the sweeps.** At `sweep_left`, `sweep_right` and `sweep_high` the Meshy buildings are solid objects. There are
no rubber-sheet slabs. The castle levels, dwellings, mage guild tower and tavern keep real roofs and walls. The relief
before visibly smears on the dwellings and the cliff-side houses. That is the gain the brief asked for, but by the
rule above it does not pay for the rest regression.

**Next step (not built).** A hybrid would keep the relief skirt on the sprite pixels the model does not cover, as
Bulwark's stage has it. That would close most of the coverage part of the rest dE.

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

| layer | Meshy taskId | cr | fit IoU | rest silhouette IoU / sprite px covered | rest dE76 relief (wall_v2) | rest dE76 Meshy (t2_v1) | ships |
|---|---|---|---|---|---|---|---|
| tbncblak | `01a0ef7d-19a2-704a-88b5-7d5afa576bd2` | 15 | 0.791 | 0.7174 / 0.731 | 4.08 | 14.73 | relief |
| tbnccstl | `01a0ef7d-2534-7125-bc10-59cf3914c4eb` | 15 | 0.797 | 0.8153 / 0.8257 | 3.28 | 6.59 | relief |
| tbnccstl_2 | `01a0ef7d-215b-73e7-9fdd-68fe24084fbe` | 15 | 0.76 | 0.8228 / 0.8361 | 2.78 | 7.1 | relief |
| tbnccstl_3 | `01a0ef7d-1243-779b-8840-342a0240fe6e` | 15 | 0.809 | 0.8658 / 0.9014 | 2.77 | 5.87 | relief |
| tbncdw_0 | `01a0ef7d-1db9-70ed-b546-67c42ce0f67b` | 15 | 0.784 | 0.8034 / 0.8206 | 2.5 | 6.49 | relief |
| tbncdw_0_2 | `01a0ef7d-2c7b-75b2-9a91-c84e9176a252` | 15 | 0.777 | 0.8089 / 0.8332 | 2.81 | 8.61 | relief |
| tbncdw_1 | `01a0ef7d-1647-7079-a456-d8734faed16b` | 15 | 0.683 | 0.5833 / 0.5929 | 2.62 | 11.1 | relief |
| tbncdw_1_2 | `01a0ef7d-2927-74c9-9631-8d664138e620` | 15 | 0.789 | 0.7663 / 0.7909 | 2.38 | 6.12 | relief |
| tbncdw_2 | `01a0ef7d-cbda-75e7-8196-4baea5309f0d` | 15 | 0.679 | 0.6549 / 0.6866 | 3.43 | 10.34 | relief |
| tbncdw_2_2 | `01a0ef7d-d087-73cb-9d6d-ded561175f6b` | 15 | 0.734 | 0.7973 / 0.8483 | 4.13 | 6.0 | relief |
| tbncdw_3 | `01a0ef7d-d460-76d4-a846-7ce8962ec8b4` | 15 | 0.871 | 0.8834 / 0.8937 | 2.7 | 10.09 | relief |
| tbncdw_3_2 | `01a0ef7e-12a2-7267-a078-0fe8d3f2ce85` | 15 | 0.885 | 0.8652 / 0.8891 | 2.11 | 8.76 | relief |
| tbncdw_4 | `01a0ef7e-185b-725a-b1d5-60737f20155b` | 15 | 0.82 | 0.8146 / 0.8341 | 3.51 | 10.93 | relief |
| tbncdw_4_2 | `01a0ef7e-1c73-7465-b8cd-22129d081491` | 15 | 0.853 | 0.8241 / 0.8451 | 3.25 | 8.78 | relief |
| tbncdw_5 | `01a0ef7e-2110-7150-b517-e9517261adcc` | 15 | 0.829 | 0.7935 / 0.8103 | 2.9 | 7.32 | relief |
| tbncdw_5_2 | `01a0ef7e-2558-77f7-8911-ad011c710c57` | 15 | 0.8 | 0.812 / 0.8235 | 2.64 | 5.62 | relief |
| tbnchall | `01a0ef7e-ff22-70ad-a1f9-2201b089f97f` | 15 | 0.844 | 0.8238 / 0.8495 | 2.35 | 6.23 | relief |
| tbnchall_2 | `01a0ef7f-03cd-7092-add6-75c13050346e` | 15 | 0.768 | 0.7673 / 0.7748 | 2.3 | 6.3 | relief |
| tbnchall_3 | `01a0ef7f-0885-7184-8658-0ff495f3233e` | 15 | 0.789 | 0.788 / 0.7984 | 2.18 | 7.35 | relief |
| tbncholy | `01a0ef7f-421d-7130-a4b0-7c1417b5d824` | 15 | 0.661 | 0.7626 / 0.7683 | 1.84 | 7.65 | relief |
| tbnchrd2 | `01a0ef7f-5191-7353-ade2-a696c78646bf` | 15 | 0.746 | 0.771 / 0.7894 | 2.41 | 7.8 | relief |
| tbncmage | `01a0ef7f-84bc-74b1-ba55-ad255ac86ca6` | 15 | 0.913 | 0.8834 / 0.8916 | 1.97 | 5.95 | relief |
| tbncmage_2 | `01a0ef7f-8991-747e-89a5-d90d05095471` | 15 | 0.901 | 0.878 / 0.8934 | 2.11 | 6.67 | relief |
| tbncmage_3 | `01a0ef7f-938a-7626-a6e5-e9877d680c15` | 15 | 0.869 | 0.8596 / 0.8728 | 1.99 | 5.29 | relief |
| tbncmage_4 | `01a0ef82-fb4d-7209-b2d7-d484df4347af` | 15 | 0.885 | 0.8896 / 0.9047 | 1.86 | 6.64 | relief |
| tbncmark | `01a0ef83-00e5-7221-b97f-58b2219e50ca` | 15 | 0.839 | 0.7306 / 0.7418 | 2.21 | 8.88 | relief |
| tbncsilo | `01a0ef83-3bc6-703f-9d1e-60055615f864` | 15 | 0.745 | 0.7221 / 0.7398 | 1.97 | 6.52 | relief |
| tbncspec | `01a0ef83-3f53-77a0-88c6-b25c6ab25752` | 15 | 0.859 | 0.8493 / 0.871 | 3.38 | 5.84 | relief |
| tbnctvrn | `01a0ef83-446c-71c1-b3cc-4c99dc4481fb` | 15 | 0.756 | 0.8113 / 0.8192 | 2.15 | 6.47 | relief |
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
  (sha256 `c1c178e1...`). Not installed.
