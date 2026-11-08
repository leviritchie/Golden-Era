# Full-3D town sky: one continuous panorama surface

Status: prototype on **Inferno**, candidate `artifacts/homm3_inferno_full3d/candidates/sky_cont_v1`. It is **not installed**.
Owner: `tools/homm3_town_scene_meshes/town_full3d_sky_continuous.py`, with the shader `tools/homm3_town_scene_meshes/unity/shaders/Homm3TownSkyPanorama.shader`.
Gate: `check_sky_continuous` in `tools/validate_town_scene3d_contract.py`.

The direction came from the user on 2026-10-01: "reconsider how we do skyboxes and clouds entirely … there is no reason a skybox shouldn't be consistent across an entire background". The acceptance bar for town scenes is "0 visible streaking behind objects". For the sky, that means no streak or stretch wherever the skyline or the buildings meet it, at any reachable pose.

## The old sky and where its seams came from

The old sky is built per faction by `stronghold_full3d_scene.stage_sky` and `town_full3d_sky.py`. The audit renders are in `artifacts/homm3_town_sky_continuous/audit/`.

The old sky is not one surface. It has four parts:

| piece | what it is | where it shows |
|---|---|---|
| `Sky_Dome` | a cap at `DOME_R` = 415 m covering az ±82° and el −16..62°. Its texture is 4096x2048 and it uses the sprite material at queue 1000. | everywhere above the relief |
| `town_full3d_sky.composite` | the dome texture: the painted sky inside SKY_MASK, plus the SD panorama outside it, joined by SKY_EDGE_MATCH / JOIN | in the dome |
| relief-carried sky | `Mesh_Terrain` (≤ 400 m) carries painted pixels that SKY_MASK's colour rule leaves out. On Inferno these are the black smoke band, rect rows about 170..215. | in front of the dome |
| `Sky_Drift` (Castle only) | an animated band that moves against the static relief sky | over the dome |

These are the seam sources, from worst to least bad on Inferno:

1. **The relief carries sky.** These pixels sit on a mesh at 400 m, not at infinity. The sweeps translate the camera about 17 m, which is roughly 2.4° of parallax against the dome. The smoke band therefore slides against the dome and stretches into horizontal slabs, which streak at every sweep. In the rest frame, 18,875 px of the eroded painted sky are covered by relief.
2. **The painted-rect boundary.** The SD panorama (Inferno `p1_s11`) is stylised swirl smoke, a different art style from the HoMM3 painting. It steps visibly at the rect's right edge (x = 1440 under the sweeps) and at the SKY_MASK row cap.
3. **Piece boundaries.** The dome, the relief sky and the panorama meet in three different places, and each join behaves differently as the camera moves.
4. **Drift against static sky (Castle).** The drift band moves while the relief-carried sky does not.

Inferno was chosen as the prototype because it has all three of the first three sources at once. It also has the strongest one: the relief smoke slabs.

## The design: one surface, no parallax

- **One piece.** `Sky_Pano` is a sphere (radius 100 prefab units, 96x48 segments) centred on the rest camera. Its kind is `skyshader`: a Sky_ mesh on a MeshRenderer with its own bundle material.
- **Direction-only lookup.** `Homm3Town/SkyPanorama` computes `dir = vertex − cameraPosObjectSpace`. Because the camera position is in the object's own space, the root's aspect scale, the prefab frame and every pan pose all see the same sky in the same direction. There is zero parallax, so a cursor or sweep pose cannot slide one part of the sky against another.
- **Equirectangular panorama.** The texture is 6144x1280, which is 17.1 px/deg; the HoMM3 native rest frame is about 12.6 px/deg.
  - Azimuth is measured from the rest heading, and column 0 is directly behind the camera.
  - Elevation runs from −20° to 55°.
  - u repeats, so the wrap has no seam. The wrap pair sits behind the camera, which no pose reaches.
  - Derivatives are taken on two u parameterisations and the smaller pair is used. This keeps the mip level from jumping at the wrap.
- **Depth.** `o.pos.z` is pinned to the far plane in the vertex shader, reversed-Z aware. The pass uses ZWrite On / ZTest LEqual / Cull Off and the Background queue. Every mesh draws in front of the sky regardless of draw order or sphere radius.
- **Hex SRP constraints.** There is no GrabPass, no camera texture, no fog and no lighting. It is an untagged unlit pass like the other bundle shaders: FlowWater, VfxUber and SsrWater.
- **Clouds.** The clouds are painted into the panorama. `_DriftDegPerSec` (0 by default) rotates the whole panorama as a single layer, so clouds can never move against another sky piece because none exists.
  - The rate comes from the town profile: `SKY_ANIM` mode `drift` gives 360 / `periodS` deg/s (Castle: 2400 s, 0.15°/s), and anything else gives 0. The stage writes it into the material and into catalog `skyLook.driftDegPerSec`. The validator recomputes it from the profile and fails on any difference.
  - The shader clock is `_Time.y` (time since level load) + `_TimeOffset`. At apply, the runtime sets `_TimeOffset = -Time.timeSinceLevelLoad`, so a drifting sky starts on the painting at the rest pose. A validator runtime needle pins this.
  - While the sky drifts, the panorama's wrap and quilted back pass through the rest view (one turn takes 40 min at Castle's rate). The wrap and seam limits therefore apply to every view, not just to poses behind the camera.
- **The relief stops carrying sky.**
  - A relief piece is `Mesh_Terrain*`, the layered-depth back layer `Mesh_Back_Terrain*`, or `Mesh_Outer[LRC]n`. The back layer counts because `town_full3d_ldi` built it behind whatever the old SKY_MASK called rock. At Castle, that put the white cumulus behind the left spires on geometry: 3,851 px of eroded P at rest.
  - Every relief triangle whose rest-projected centroid lies on the painted sky P is cut.
  - On the frame-box terrain pieces, albedo texels on P take the nearest non-sky texel. Those texels are only sampled by the kept silhouette triangles, so the skyline is crisp against the panorama, with no sky-coloured halo and no gap.
  - **Per-town rules beyond the rect** (`TOWNS[f]`: `extSky.rule`, `ring`, `edgeSkylineCut`). Inferno uses `ridgeDark` / `rebake` / true, as below. Castle uses `none` / `rebake` / false: its extension is the `TOWN_FULL3D_EXTSRC` outpaint (`tex/extsrc_p2_blend`), and its far wall is already fitted to that canvas's own skyline (profile `EXT_SKYLINE`). No relief beyond the rect stands on painted sky there, so nothing beyond P is cut. Its ring is rebaked like Inferno's: the staged `Mesh_OuterL2` carried a stretched outpaint strip (blue sky, spire streaks) along its frame-edge texels, which read at sweep_left as a sky slab with a hard top edge on the far-left hills. It was present in the installed Castle too. Keeping the staged ring (`ring: staged`) was tried first and left that slab. A town without an explicit rule fails closed.
  - **The frame extension (x ≥ 1440) and the periphery ring (Inferno)** carried painted sky too, from the seed's old outpaint canvas: red cloud and a pale grey-blue haze band above the extension's ridge, and canvas strips stretched along the ring's frame-edge columns (`Mesh_OuterR2`'s pink strip with ridge spires was the sweep_right / sweep_high smear). The world field had also read the smoke band as terrain depth, so a smoke-high wall stood just beyond the frame edge, hidden by that sky-coloured texture. Three rules re-derive it from the painting:
    - `extension_sky`: per extension column, the ridge silhouette top (the first row from 150 down that stays at sRGB max channel ≤ 8 for 8 rows, median over 9 columns). The rows above it join P for the cut, the same way as the painted sky: triangles there are cut, texels there take the nearest non-sky texel. Fails closed if a column has no ridge.
    - `edge_skylines` + the beyond-frame cut: the skyline at each frame edge (median over 40 columns of the lowest sky row) is held outward in elevation. Relief triangles wholly above it (+0.25°) beyond the frame are cut.
    - `rebake_outer`: every `Mesh_Outer[LRC]n` albedo is rebaked with the periphery's own `bake_piece`, with the rect edge colour sky-masked by P and no EXTSRC canvas. The staged ring geometry and UVs are kept. The layout must reproduce the staged texel -> world mapping: the same texture size, and the staged UVs of at least 95% of the vertices (the ones still on the polar grid; `settle` moves only in-frame ones) to 0.05 texel. Otherwise it fails closed. The vertex count is not compared. At Castle, the field refitted from EXTSRC culls one vertex fewer of `Mesh_OuterC0` (13,536 against 13,537 staged) while every piece's theta / rho range and texture size are identical. The report records `uvOnGridFrac` and `fieldDyMaxM`, the height difference between the staged grid vertices and the refitted field. That difference is at most 0.78 m at Castle (`Mesh_OuterL1`, 70-169 m out); it moves the synthesis sample, not the geometry. Within 240 rest-frame px beyond the frame edge, the ring continues the frame terrain *mirrored* about that edge (texture-continuous, never an edge column stretched outward), smoothstep-feathered into the synthesis.
  - Props, rocks and boulders are deliberate objects and are never cut. Their cover of the painted sky is reported separately: props_v1's streak-cover crag covers 3,022 px and the mound 571 px.
- **The painted sky, P.** P is SKY_MASK, plus the dark painted sky the colour rule leaves out. That extra sky is the region where the DA disparity is below `daMax`, the row is below `rowMax`, and it is connected to SKY_MASK, with a 3 px close. On the rest directions, the panorama is the HoMM3 painting itself (2x LANCZOS, bilinear). The rest frame therefore *is* the painting.
- **The extension is the painted sky, re-laid.** No SD, no AI and no stretch are used.
  1. The holes in the painted tile (ridge peaks, the sun's surround) are filled with horizontally shifted painted rows plus a membrane correction.
  2. Around the back, 1-D quilted strips of the sun-free painted plate and its mirror are laid. Each piece is whole-height and is chosen by SSD on a 6° overlap, with random lengths of 14..26° (seeded).
     - Pieces are joined by a minimum-error cut plus a two-band blend.
     - Each strip is phase-matched to a painted edge, and the two strips meet once behind the camera.
  3. Above the band, periodic quilted strips of the plate's top rows are stacked. Alternate strips are flipped vertically so dark meets dark.
  4. Beyond the band, a per-row mean fade is used. It is outside every reachable pose.
  5. A tone carry (SKY_EDGE_MATCH's rule; the sun is never a reference) and a C0 membrane close the painted edge.
  6. **Below the painted tile's bottom** (`below_painted_smooth`), the rows the tile never painted are a horizontal-only Gaussian (σ 3°, wrapped) of themselves. The blend ramps in over 1.5° below the painted bottom inside the tile, and over the 1.5° above it outside the tile. Within 2σ of each tile edge, the blur starts at that edge column's own painted bottom instead, because the tile's continuation and the quilted back meet there as a butt join (Castle: L* 45 | 57 at az 20.6). Painted px are never touched. The vertical streaks that the copied hole rows left at sweep_high (Castle) are gone. A second membrane pass was tried instead and made the horizontal seams worse.
  7. **Edge join** (`TOWNS[f].edgeJoin`): `phase` (the default; Inferno) starts each strip phase-matched to the painted edge. `mirror` (Castle) starts each side with the painted tile mirrored about its own edge column, over the overlap plus 1.5°. It replaces a hard vertical cut through the cumulus that crosses Castle's right rect edge. The residual is a cloud that is visibly symmetric about that edge.
  8. **Seed scan.** Castle's `seed` 12 was chosen from seeds 1-12 under the mirror join, as the lowest horizontal seam (stack joins) and the lowest wrap.
- **Fail closed at runtime** (`Homm3TownScene3d.cs`).
  - Catalog `skyLook` is parsed with its schema pinned.
  - The declared Sky_ piece keeps its bundle material only if its shader is exactly the declared shader.
  - An undeclared `*/SkyPanorama` material is refused.
  - With skyLook present, more than one Sky_ piece is refused: "the sky must be a single surface".

## Rejected options

- **`RenderSettings.skybox` or the native TileableSkybox.** It is scene-global and must be restored on exit, and its tileable mapping cannot match a painted rect. It also cannot be proven in the editor renders, which seat a prefab.
- **Keeping the dome and fixing its joins.** It has a finite radius, so the parallax against the relief remains, and it is still several pieces.
- **A procedural gradient or cloud shader.** It does not match the HoMM3 art at rest.
- **Keeping the SD panorama.** Its style does not match the painting. The rule is HoMM3 art only, never the blurred 2D backdrop.
- **Small-block 2-D quilting** (Efros-Freeman, measured). It produced stripy mush and periodic dark feather lines.
- **Tiling the full painted plate.** The dark left smoke columns repeated as vertical bands, the period was about 31°, and the stack layers stepped.
- **Limiting the camera.** This is never done (user rule): the sky must hold at every reachable pose.

## The gate (`check_sky_continuous`, wired into the town-scene validator)

Every check is static or generated-artifact. The panorama checks are recomputed from `bundle/sky_continuity.npz` (sha-pinned in catalog `skyLook`) and the HoMM3 painting, which is sha-checked and read from REFS.

- **Single surface.**
  - `skyLook` uses schema `town_full3d_sky_continuous.v1`.
  - The environment's Sky_ pieces are exactly `[skyLook.piece]`.
  - The only `*/SkyPanorama` shader in `bundleShaders` is the declared one.
  - An undeclared panorama shader fails.
- **The shader has the design's properties.** It contains `_SkyFwd/_SkyRight/_SkyUp`, `unity_WorldToObject`, `UNITY_REVERSED_Z`, `ZWrite On`, `tex2Dgrad` and `_TimeOffset/_TimeScale`. It uses no GrabPass and reads no camera texture.
- **Runtime needles.** The parse, keep-material and refusal paths above are present.
- **Seams.** Straight lines are detected inside el 2..25° (the sky the poses show above the ridge), on the half-resolution panorama, wrap included.
  - Each column or row boundary's window-median L* step is compared with the median of its neighbours 3..12 px away.
  - The panorama's strongest line must be ≤ 1.1x the HoMM3 painting's own strongest line, measured the same way at the same angular scale.
  - Wrap column ≤ 1.6.
  - Painted-edge step ≤ 2.6x the painting's median adjacent step.
  - A synthetic strip swapped into the panorama must trip the detector, so the check is not blind.
- **Rest.** The panorama's rest view, compared with the HoMM3 painting over P eroded 2 px, must have ΔE mean ≤ 2.5 and p95 ≤ 7. The stored rest view must also agree with a fresh lookup into the stored panorama (mean ΔE ≤ 3).
- **Relief.** At most 400 px of eroded P may still be covered by relief at rest.
- **Limits are pinned.** The catalog's `skyLook.limits` must equal the lane's constants, so a catalog cannot loosen them.

Results for Inferno `sky_cont_v1`, from the validator line:

- seamRel = 0.71 (horizontal; vertical 0.49);
- wrap = 1.28;
- edge = 1.49;
- rest ΔE = 0.94 mean / 2.38 p95;
- relief sky px 18,875 → 162;
- synthetic negative = 3.2x the painting's line.

Results for Castle `sky_cont_v1` (seeded from `rx_ldi_zone_old_nfix`, pano seed 12, staged with `TOWN_FULL3D_EXTSRC=.../tex/extsrc_p2_blend`), from the validator line:

- seamRel = 1.06 (the limit is 1.1x the painting's own line);
- wrap = 1.29;
- edge = 2.21;
- rest ΔE = 1.20 mean / 2.73 p95;
- relief sky px 7,162 → 9;
- `driftDegPerSec` = 0.15; `Sky_Dome` and `Sky_Drift` are removed.

Inferno `sky_cont_v1` was re-panoramed, restaged, bundled and rendered with the same code (`below_painted_smooth`, phase join), and it still passes with the figures above.

## Proof tier

- **Generated artifact + source/static validated:** the panorama, stage, catalog and gate. They are listed above.
- **Editor render (built-in renderer, not the Hex SRP):** `artifacts/homm3_inferno_full3d/candidates/sky_cont_v1/renders/` (rest, cursor and sweep poses), `work/sky_pano/sheet_before_after.jpg` (before = installed `props_v1`) and `work/sky_pano/measure.json`.
  - Frame top-band horizontal seam maxima drop at every pose (sweep_high 12.3 -> 6.8). The old dome's own horizontal seam was 12.46 and its painted-edge step 3.35.
  - Frame vertical maxima, before -> after: rest 27.6 -> 29.0 (the painting's own spires), cursor_left 1.20 -> 1.49, cursor_right 2.28 -> 1.81, sweep_left 3.01 -> 3.88, sweep_right 17.8 -> 14.1, sweep_high 16.4 -> 18.8. Frame metrics include buildings and props, so they are diagnostic, not a gate.
  - By eye, the smoke-slab streaks that the relief carried at the sweeps are gone at sweep_left and sweep_high, and most are gone at sweep_right.
  - **Periphery smear (fixed 2026-10-01):** at sweep_right and sweep_high, right of the tower, the seed had a pink stretched smear, and a pale haze patch sat on the extension ridge at rest. Both are gone after the ring rebake and the extension-sky cut. The sweeps' upper-right band now reads as the continuous ridge in front of the panorama. The red crystal on that ridge is a prop and stays. At sweep_left, the left ring's pink and blue canvas streaks are gone too, replaced by the lava plain receding to the skyline.
- **Castle editor render:** `artifacts/homm3_castle_full3d/candidates/sky_cont_v1/renders/`, `work/sky_pano/sheet_before_after.jpg` and `measure.json` (before = `rx_ldi_zone_old_nfix`).
  - Frame top-band horizontal seam maxima, before -> after: cursor_left 7.48 -> 3.42, cursor_right 6.45 -> 3.82, sweep_right 9.65 -> 6.41, sweep_high 15.56 -> 7.59, sweep_left 5.50 -> 6.11.
  - sweep_left is the one pose that does not drop. With the staged ring it rose to 9.30. The OuterL2 ring rebake removes the sky slab, and the far-left plain now meets the panorama at a clean horizontal horizon. The remaining step is that horizon line itself, not a seam in the sky.
  - By eye, sweep_right and sweep_high have no sky seam or skyline stretch. The old haze slab at the upper right is replaced by the panorama's clouds.
  - **Residuals in other lanes:**
    - the `Mesh_Prop_spire` prop at sweep_right's right edge carries a stretched, streaky texture (before and after; props are never cut);
    - the ring and terrain synthesis textures are streaky near the frame-edge mirror seam (the periphery and terrain lanes);
    - the mirror-joined cumulus at the right rect edge is visibly symmetric, with a hole-copy horizontal band inside it.
- **Bundle size:** the 6144x1280 panorama ships uncompressed (about 40 MB in the bundle). The whole bundle is 288 MB, against 289 MB before, because the old dome texture is gone.
- **Unproven:** the Hex SRP runtime, meaning whether the game's pipeline draws an untagged Background-queue pass with a pinned far-plane depth the way the editor does. The runtime fail-closed paths have been compiled only through the plugin build.

## Rollout recipe (every full-3D town)

Do not delete a candidate's `unity_project`. `candidate/unity_project/Assets/Homm3TownScene3d/<f>/` *is* the staging source (rows, bins, albedo), and a bundle run does not recreate it. An earlier report (2026-10-01) wrongly said it did. That Inferno candidate was restored from `props_v1` and restaged.

1. Seed a candidate from the installed one:
   `stronghold_full3d_scene.py --faction <f> candidate-init --seed-from <installed>` with `TOWN_FULL3D_CANDIDATE=sky_cont_v1`.
2. Add a `TOWNS[<f>]` entry with hand-set, painting-specific values:
   - `ext` (`daMax`, `rowMax`): the dark painted sky the SKY_MASK colour rule leaves out. Check it in `work/sky_pano/masks_rect.png`.
   - `exclude`: the sun or moon disc and its glow, so it is never copied. Use `lMin` / `bMin` for a warm sun; a pale moon may need different thresholds.
   - `plateAzDeg`: the widest painted span free of the excluded disc and of tall ridge peaks.
   - `seed`.
3. Run `pano`. Review the az ±85° crop: there should be no repeated landmark, no step at the painted edge, and no sun pillar.
4. Run `stage`, then `bundle`. If the candidate has an LDI or SSR block, rerun their stages after it: the relief cut rewrites the terrain bins.
5. Run `render`, then `measure --before <installed>` and `sheet --before <installed>`. Then run the validator on the candidate catalog.
6. Review the rest and sweep pairs by eye. Look for no streak or stretch at the skyline, and check that props standing against the sky still read correctly.
7. Deploy the plugin build that carries the runtime skyLook support, then install with `install_town_scene3d.py <f> <candidate>/bundle`. Installing copies `sky_continuity.npz`.

Castle's drift is folded in: the stage removes `Sky_Dome` and `Sky_Drift` and sets `_DriftDegPerSec` from `SKY_ANIM` (see Clouds). Stage a town whose profile uses `TOWN_FULL3D_EXTSRC` with the same canvas its terrain was built with (Castle: `artifacts/homm3_castle_full3d/tex/extsrc_p2_blend`). The profile's `EXT_SKYLINE` refuses to run without it. Towns whose painted sky meets the frame edge at a moon need `exclude` tuned to the moon.

Order of rollout: Inferno first, then Castle (drift), then the rest. Both Inferno and Castle candidates are built, validated and rendered, and neither is installed yet (2026-10-01). The suggested order of the rest is by measured relief sky px, highest first, using this module's `relief_cover`.

Conflicts with other lanes:

- The relief cut touches `Mesh_Terrain` / `Mesh_Outer*` bins, so restage it after any terrain, LDI or near-camera-depth restage.
- Building depth / seams and SSR water are independent of it: they use different pieces and different catalog blocks.
