# Full-3D towns: cloth wave on the banner meshes

Status: generated artifact validated + lab (editor) render on Castle (`rx_ldi_zone_old_nfix_cloth`). Runtime / in-game
look unproven until the bundle is installed and seen.

Owner: `tools/homm3_town_scene_meshes/town_full3d_cloth.py` (schema `town_full3d_cloth.v1`). Gate:
`tools/validate_town_scene3d_contract.py` (`check_cloth_look`, plus the cloth role in `buildingDepth` and cloth
effects in `animationAudit`). Runtime: `Homm3TownScene3d.cs` (`ParseClothLookOrThrow`, `ApplyClothWaveOrThrow`,
`RefreshClothWaves`).

## Why the old effect failed (user verdict 2026-10-01: "inadequate")

`town_t2_anim_pass.py`'s `cloth` recipe was two VfxUber particle systems (`Fx_Glow_0_<layer>`: a dark "fold" and an
additive "sheen") drawn over the painted banners inside the DEF's widened, blurred change mask.

- Nothing on the mesh moved. The banner silhouette and its fly end stayed fixed, so it read as flickering shading,
  not cloth.
- The noise bands crossed the blurred mask onto the wall around each banner.
- The group sat at one position and depth per layer, so at a pan it slid off banners that stand at other depths
  (parallax).

## Method

The pass runs on a candidate copy, after every other stage (`apply` refuses a candidate that already has cloth). It
spends no Meshy credits and adds no new geometry, only copies of existing faces.

1. **Cloth mask, from the HoMM3 sprite.**
   - Start from the pixels the DEF animates (frames 1..), restricted to pixels that change across the frames
     (dilated 7x7).
   - Keep the faction's cloth colour. For Castle (rule `blue_gold`) that is the heraldic blue, with the gold
     trim/griffin inside it taken by a closure and a hole fill.
   - One connected component is one banner. A component more than 1.5x the median banner width is split at its
     column-coverage gaps (two training-ground banners touching through the tent).
2. **Mesh surgery.**
   - The faces of `Mesh_Body_<l>` (painted Meshy front) and `Mesh_BodyRest_<l>` (seed residual) that the rest camera
     draws inside a banner's mask are copied into `Mesh_Cloth_<l>_b<k>`. The texture is a packed crop of the source
     texels.
   - Sliver faces with any vertex more than 4 px outside the banner are dropped.
   - A banner is thin in depth. The pass keeps only faces whose vertices lie within one banner length (along their
     rest rays) of the depth mode of the faces the rest camera draws there (bins of 0.2 banner lengths, weighted by
     px won). The hedge or wall behind a banner, and ray-long residual faces that leak through the mask, stay static.
     Without this filter, `buildingDepth` refused four training-ground cloth pieces as depth streaks (20-31 m upright
     span over 1-4 m width). A +-0.5 window was too tight: it dropped half the faces of banners hanging obliquely on
     the town-hall facades.
   - Each copy moves toward the camera along its own rest ray by the wave's out-of-plane reach plus 0.08 units, so
     the rest image is unchanged and the wave never dips behind the wall.
   - The source faces stay in place as the static backing. Their texels are darkened (x0.5, desaturated 35%) to a
     cloth-shadow tone, so a moving fly end uncovers the banner's shadow, never a duplicate banner.
3. **Weight (`COLOR.r`).**
   - 0 on the top 6% (the hoist), then `((s - 0.06) / 0.94) ^ 1.4` down the banner.
   - Times an across-width skew `(1 + 0.25 a s)`, so the two fly corners lag each other (a secondary twist).
   - The weight depends only on position, so coincident soup vertices move together and the copy cannot tear.
4. **Wave.** The installed Hex/Lit FLAG variant, unchanged:
   `posWS += _FlagPower * sin(dot(posWS, _FlagDirection) + _Time.y * _FlagSpeed) * COLOR.r`.
   - Power: `0.085 H` along the banner's horizontal (downwind) plus 35% out of plane.
   - Direction: a travelling wave down the banner (wavelength 1.15 H), plus a gust gradient across the town (32
     units, wind `(1, 0, 0.35)` in the prefab frame), so neighbouring banners are out of phase by where they stand.
   - Speed: `2 pi / 1.7 s`, with a fixed +-10% per-banner jitter.
   - The catalog declares the vectors in the prefab frame. The runtime converts them to world space per renderer
     (power by `localToWorld`, direction by the inverse transpose) and re-derives them whenever the root is placed,
     because the root carries a non-uniform aspect scale.
   - The native wave does not rewrite normals. The displacement is a few % of the banner, so the static normals stay
     plausible.
5. **Old overlay removed.** The `Fx_Glow_0_<l>` fold/sheen groups of the cloth layers are removed, and
   `animationAudit` names the cloth pieces (kind `clothWave`, placement `mesh`).

The native shader has a single sine, so the secondary flutter is approximated three ways: the diagonal travelling
fronts, the per-banner speed jitter, and the weight skew. There is no second harmonic.

## Commands

    set TOWN_FULL3D_FACTION=castle & set TOWN_FULL3D_CANDIDATE=<copy of a candidate>
    python tools/homm3_town_scene_meshes/town_full3d_cloth.py plan      # dry run: banners and face counts
    python tools/homm3_town_scene_meshes/town_full3d_cloth.py apply     # stage, rewrite catalog + build spec
    python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py bundle --faction castle
    python tools/homm3_town_scene_meshes/stronghold_full3d_scene.py render --faction castle   # + cloth_<seq>_<i>.png
    python tools/homm3_town_scene_meshes/town_full3d_cloth.py check --base <the candidate it was applied on>

`check` re-runs `town_full3d_zero_streak`'s certificate with every cloth piece displaced at 4 phases of the wave and
compares it with the base candidate. The cloth must add no visible behind-streak component.

## Castle results (2026-10-01)

Candidate: `artifacts/homm3_castle_full3d/candidates/rx_ldi_zone_old_nfix_cloth`, applied on a copy of
`rx_ldi_zone_old_nfix` (the near-camera depth fix). The bundle sha256 is `17fb89ced045...`; it was not installed.

- **Banners.** 24 banners on 5 layers:
  - `tbcshall`: 3
  - `tbcshal2`: 5
  - `tbcshal3`: 5
  - `tbcsdw_5`: 6
  - `tbcsdw_5_2`: 5

  The `full` state shows 10 of them (`tbcshal3`, `tbcsdw_5_2`); the rest belong to lower build levels. The castle
  keep's banners are static in HoMM3 (no DEF animation), so they are left alone.
- **Pieces.** 190-4278 faces per banner, peak displacement 0.07-0.20 units.
- **Validator.** `validate_town_scene3d_contract.py --catalog <cand>/bundle/catalog.json`: OK, `cloth=24`,
  `bldDepth contact_v1 spanW<=4.18`. The HEAD copy of the tools was used.
- **Zero-streak** (`town_full3d_cloth.py check --base rx_ldi_zone_old_nfix --loop 36 --phases 4`, 43 reachable poses,
  wave at 4 phases).
  - The visible behind-streak px are identical to the base at every pose and every phase. The cloth adds 0.
  - The base itself does not pass: its max is 1707 px (sweep_left), with 38/43 poses showing streaks
    (terrain_back / bldg_front / env_other). Those are pre-existing and not cloth.
- **Editor renders** (`renders/cloth_<seq>_<i>.png`, 8 frames over one period at rest, sweep_left / sweep_right /
  sweep_high and the high orbit). Sheets are in `review/cloth_sheets/`:
  - `zoom_tbcshal3.png`, `zoom_tbcsdw_5_2.png`: the old overlay at rest and at t1, against new frames 0/2/4/6.
  - `rest_before_after.png`: every cloth layer, with the HoMM3 sprite crop as reference.
  - `pose_*.png`: frames 0/4 plus a motion heat map per pan pose.
  - `face_selection.png`: the selected faces over the HoMM3 sprite, coloured by weight.
- **What the sheets show.**
  - The old overlay drew cream sheen blobs over and beside the banners, with no silhouette motion.
  - The new banners swing at the fly end with the hoist fixed. Colour and placement match the HoMM3 art at rest.
  - The motion stays on the banners at every pan pose. Moved px at rest: 9661 inside the banner masks (+15 px), 1482
    outside, which are the orb and lighthouse pulses (old: 1281 outside).
- **Known limits.**
  - Some gold-trim faces at a banner's lower tip stay static where they failed the vertex rule.
  - Single sine (see above).
  - Runtime unproven.
