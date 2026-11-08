# HoMM3 prebaked lighting (Behemoth experiment)

Status: experiment, one unit (`h3_behemoth`). Proof tier is **generated artifact**: Blender-rendered, plus a Unity-editor render through a replica of the game shader. None of this has been seen in-game. No build output, unit config or source mesh was changed. Every texture here is a copy under `artifacts/homm3_prebaked_lighting/behemoth/` (gitignored except the files committed below).

Question: what should be baked into a Meshy unit's base colour so that it reads like its HoMM3 DEF sprite at **every** facing? Units yaw freely in battle, so a lighting direction baked into the texture turns with the unit.

## Tools (`tools/homm3_prebake/`)

| file | side | does |
|---|---|---|
| `probe_game_lighting.py` | python / UnityPy | reads the installed arena `Light`s, `RenderSettings` and `Hex/*` shaders -> `artifacts/homm3_prebaked_lighting/game_lighting_probe.json` |
| `disasm_hex_lit.py` | python / d3dcompiler_47 | LZ4-unpacks the installed Hex/Lit blobs and disassembles the DXBC -> `hex_lit_ps/` (`ps_o0_t4_n150.txt` is the Lit-pass pixel shader) |
| `bake_terms.py` | Blender | bakes yaw-invariant UV terms, rest pose: AO, sky/hemisphere, object position, object normal, and seven sun directions -> `behemoth/terms/*.npy` |
| `render_passes.py` | Blender | per view (3 DEF sprite cameras + 4 battle yaws): UV, alpha, normal, sun DiffDir for the sand/grass/snow arenas -> `behemoth/views/*.npz` |
| `prebake_lab.py` | numpy | composes variants from the terms, fits a palette grade to the DEF, relights every view with the game formula, writes metrics and sheets. `--params knobs.json` holds the per-unit knobs |
| `subdiv_probe.py`, `export_posed_obj.py` | Blender | baked Catmull-Clark probe; posed OBJ for the Unity preview |
| `unity/Homm3PrebakeLightingPreview.cs`, `unity/Homm3PrebakeHexLitReplica.shader` | Unity editor batch | renders textures x 4 yaws through the Hex/Lit replica and through the lab's Hex/Lit stub. Stage them in the project temporarily and remove them afterwards |

Every Blender and Unity launch was gated by `tools/homm3_def_retarget/memgate.py`.

## What the game actually lights with

This section is a static read of the installed build, not runtime-observed.

- **Hex/Lit Lit pass** (DXBC disassembly, `hex_lit_ps/ps_o0_t4_n150.txt`):
  `rgb = albedo(_MainTex*_Color) * (SH_ambient * screenTex + mainLight * saturate(N.L) * shadow [+ extra lights])`
  - There is **no normal map**: 0 of 7,382 programs read TANGENT.
  - There is no specular and no metallic term.
  - There is **no tessellation**: no hull or domain stages.
  - The 31 properties do not include `_BumpMap` or `_MetallicGlossMap`.
  - Only the vertex normal and the base colour reach the screen.
  - The "extra lights" (2026-09-26 read; the pass LightMode is `HexLit`) come from a global
    `HexLighting` cbuffer: `_MultipleDirectionalLights`, `_DirectionalLightColors/Directions[4]`,
    `_DirectionalLightsCount`, `_PunctualLights` (enable), `_PunctualLightColors`,
    `_PunctualLightPositions` (w = 1/range^2), `_PunctualLightDirections` (spot), `_SSAOEnabled`,
    `_GlobalShadowParams0/1`. Point lights are picked per object through Unity's
    `unity_LightData.y` (capped at 8) and `unity_LightIndices`; point attenuation is
    `(1-(d^2/r^2)^2)^2 / d^2 * saturate(N.L)`, unshadowed. There is an emission variant
    (`HEX_EMISSION_MAP_ENABLED`, `_EmissionTex`, `_EmissionColor`, ...) whose math was not read.
    How these lights reach unit VFX is in `docs/homm3_unit_look_pipeline.md` (def_retarget delivery).
- **Arena light** (serialized scenes):
  - `MainLight` is directional, colour (1, .957, .839), intensity 1, hard shadows.
  - Travel direction by arena:
    - sand, dirt and autumn: (0.624, -0.4035, 0.6692), about 24° elevation
    - grass: (-0.0215, -0.1804, 0.9834), about 10° elevation
    - snow and necro: (0.4011, -0.4035, 0.8224)
    - lava: red light at 1.7
  - Ambient is Flat, (0.6235, 0.6784, 0.7922) at intensity 1.
  - The sun is low and mostly behind the camera, so the unit's camera-facing side gets most of the key.
- **Plugin gate fixed, 2026-09-25.**
  - The donor gate in `Homm3ImportVisuals.cs` and the shared donor scan
    `EsquirePikemanVisuals.ScoreLoadedUnitStyleHexLitMapDonor` both required these slots, from the
    2026-09-20 checkpoint on. So every owned skinned unit was refused ("rebind refused: no native
    Hex/Lit sheet with _BumpMap"), 346 times in one session.
  - Now a native Hex/Lit sheet with `_MainTex` is enough. The normal/metal binds run only where the
    shader declares the slots.
- **Battle-invisible regression, 2026-09-26** (static/decomp + log; the fix is build-proven only, not yet seen in game):
  - Hex/Lit's Lit-pass vertex shader applies `UnityPerMaterial._PreviewScreenOffset` (cb2[11], offset 176) to clip-space xy in **every** variant: `clip.xy += clip.w * offset.xy`. It is not gated by `HEX_UI_PREVIEW_CAMERA`. The dither/cutout fade variants also discard on `_HexFade`. All 1169 unit/world Hex/Lit sheets in `resources.assets` serialize both as 0.
  - The unit detail preview renders its model through per-renderer material instances (log: `mat=twinkle_mushroom_mat (Instance)`). Commit 571d5b462c handed that model to the owned-skinned rebind as its donor, and the rebind stored every donor in `_cachedNativeHexLitSheet`. Battle's own donor is `unit_cutout` (`Hex/Cutout`, not a Hex/Lit sheet) or an uncached presentation template, so after a preview had opened, battle cloned the preview instance. Map squads built before the preview were visible.
  - Fix in `Homm3ImportVisuals.EnsureSkinnedBattleRuntimeCompatibility`:
    - UI-preview lanes (`uiPreviewLane`) never feed the cache.
    - Battle and map clones reset the per-context values and keywords to the native sheet values (`ResetOwnedSkinnedHexLitInstanceState`).
    - `VerifyOwnedSkinnedHexLitVisibleState` logs `visibility self-check FAILED` at error level on any mismatch.
    - The donor line (`owned skinned Hex/Lit donor lane=...`) logs the donor's offset and fade, so the next run shows the actual preview values.
  - Gate: `tools/validate_crusader_owned_skinned_runtime_contract.py`.
- **Earlier contradiction with the plugin:** `Homm3ImportVisuals.cs` (about lines 5890-6180) looks for a Hex/Lit donor that has `_BumpMap` and `_MetallicGlossMap`. It copies the base, normal and metallic textures and sets `_Smoothness` 0.35. The installed Hex/Lit declares neither property, so in-game the normal and metallic textures are presumably inert. Only the base colour counts, and **normal-map detail has to be baked into the base colour**. The bake terms here do include the Meshy normal map. This is unverified at runtime.

## What the sprite's lighting is

Measured on DEF frames 02_00, 00_03 and 12_01 (`metrics.json` -> `def`):

| property | DEF | raw Meshy under the game formula |
|---|---|---|
| L* p5 / p25 / p50 / p75 / p95 | 2.7 / 15.5 / 26.2 / 37.7 / 57.0 | 8.3 / 14.8 / 20.1 / 27.1 / 39.1 |
| mean chroma, hue | 17.8, 65° (ochre) | 11.5 |
| shadow Lab | (4.6, 3.0, 3.8): near-black, neutral-warm | shadows lifted |
| highlight Lab | (55.7, 4.7, 19.4): warm cream | dimmer, less yellow |
| local contrast (mean abs(L - blur σ1)) | 5.1-5.2 | 2.6 |
| rim L at 0-1.5 px from the edge vs interior | 15.4 vs 32.4 (strong dark outline) | 21.7 vs 21.4 (none) |
| top-minus-bottom L, left-minus-right L | about 0, about 0 | small |
| Lambert fit L ~ k0 + k·n (R²) | 0.02 | n/a |

The sprite has **no readable directional key**. A Lambert fit against the mesh normals explains about 2% of its value variance. Its value comes from four things:

- high-frequency texture speckle
- near-black crevices
- a dark silhouette rim
- a warm palette running from dark umber to cream

That is good news for yaw invariance. Almost everything the sprite shows can be baked without a direction. The exception is the rim, which is view-dependent.

## Variants

Each one lives in `prebake_lab.py` and is graded per variant with `grade = [exposure, gamma, sat, wr, wb]`. The grade is fitted by Nelder-Mead to the DEF's L*a*b* percentiles under the sand runtime light at the sprite camera.

| variant | bake (multiplies source albedo) |
|---|---|
| `raw_meshy` | nothing (reference) |
| `v0_graded` | palette grade only |
| `v1_shipped` | the current `stronghold_oe_approved_v1` bake, as shipped (front-biased 65° sun, key 0.6 / fill 0.25) |
| `v2_occlusion` | `ao^aoGamma * (skyFloor + (1-skyFloor)*sky)` |
| `v3_occl_height` | v2 x `1 - heightDepth*(1 - h^heightPower)` |
| `v4_sagittal_key` | v3-style occlusion x (fill·sky + keyGain·(top + front pair + back pair)), with the suns mirrored about x=0 |
| **`v6_sprite_match`** | v3 with a crevice gamma, plus `detail_boost`: a log-luminance unsharp mask (σ 12 texels, amount 1.0, mask-normalised) standing in for the sprite's speckle |
| `v5_sprite_key` | anti-pattern control: a single front-right key, baked the way the sprite *appears* to be lit |

## Results

Blender-rendered. The images are the evidence and the metrics support them.

- **Sprite camera, game formula:**
  - `artifacts/homm3_prebaked_lighting/behemoth/sheets/focus_sprite_cam_game_sand.png` (DEF / raw / v1 / v3 / v6)
  - full set: `sheets/sprite_cam_game_sand.png`, `sheets/sprite_cam_unlit.png`
- **Battle yaws** (right / left / camera / away, 40° ortho): `sheets/battle_yaw_sand.png`, `sheets/battle_yaw_grass.png`
- **Terms in UV space:** `sheets/uv_terms.png`
- **Unity editor**, Hex/Lit replica, sand light: `sheets/unity_hexLitReplica.png`. Lab stub (unlit): `sheets/unity_labStubHexLit.png`

**Sprite camera, local contrast** (DEF 5.1):

| variant | local contrast |
|---|---|
| raw | 2.6 |
| v1 | 3.0 |
| v3 | 4.15 |
| v4 | 3.9 |
| **v6** | **4.8** |

**L-histogram distance to the DEF**, frames f001 / f013 / f050:

| variant | distance |
|---|---|
| raw | 7.4 / 7.7 / 9.6 |
| v1 | 3.0 / 2.1 / **7.3** |
| v3 | 3.6 / 2.6 / 2.7 |
| v6 | 3.7 / 2.8 / 2.5 |

v1 matches the histogram best on the two front-ish frames and fails on f050. That frame faces the other way, where its baked key is on the wrong side.

**Battle mean L\* per facing** (right / left / camera / away) and asymmetry:

| variant | sand | L-R | front-back | grass L-R | grass front-back |
|---|---|---|---|---|---|
| raw | 21.4 / 18.2 / 19.3 / 16.9 | 3.2 | 2.4 | 0.5 | 2.6 |
| v1_shipped | 29.2 / 26.1 / 29.2 / 22.6 | 3.1 | **6.6** | 0.1 | **7.0** |
| v3 | 32.5 / 28.1 / 29.8 / 26.9 | 4.4 | 2.9 | 0.7 | 3.1 |
| v4 | 34.2 / 30.0 / 31.9 / 28.5 | 4.2 | 3.4 | 0.4 | 3.6 |
| **v6** | 32.4 / 27.8 / 29.6 / 27.3 | 4.6 | **2.3** | 0.8 | **2.4** |
| v5 (anti) | 33.7 / 23.4 / 29.0 / 22.6 | **10.3** | 6.4 | **7.6** | 5.9 |

What the symmetric variants leave behind:

- Their sand left-right delta of about 4 is the **runtime** sun, which is off-axis in the sand arena. The raw texture shows the same delta; the grass arena's delta is below 1.
- The shipped bake's front-back delta of about 7 is what a front-biased key costs: the unit's back reads dim.
- v5 shows the failure a sprite-matched key produces. It looks right at one facing, and the other side goes dark.

**Unity editor, Hex/Lit replica, sand light**, mean L per facing: right / left / camera / away.

| variant | right | left | camera | away | spread |
|---|---|---|---|---|---|
| raw | 21.8 | 19.2 | 20.7 | 17.2 | 4.6 |
| v1 | 29.3 | 26.9 | 30.5 | 22.7 | **7.8** |
| v3 | 32.8 | 29.3 | 31.4 | 27.1 | 5.7 |
| v6 | 32.7 | 29.0 | 31.1 | 27.5 | 5.2 |

This agrees with the Blender numbers. The replica is `unity/Homm3PrebakeHexLitReplica.shader`, which is the disassembled formula without the shadow term. It is **not** the game's compiled shader. URP Simple Lit rendered magenta in this batch setup, so it was replaced.

Remaining gaps, v6 against the DEF (these are what the v7 push below goes after):
- **Silhouette rim darkening.** It is view-dependent and cannot be baked. See "Does the game draw an outline?" below.
- **Crevices are not black enough.** p5 is 8.8 against the DEF's 2.7.
- **Colour is too even.** The DEF has mottled olive/gold speckle and cream highlights; its hue spread is 13° against v6's 4°.

## The v7 push (Behemoth only)

Each rung adds one yaw-invariant change to the previous one. The run is `prebake_lab.py --variants ... --tag v7n --params behemoth/knobs_v7n.json --sim-contour 1.5:0.9`. It needs the extra terms from `bake_terms.py --extras ao_short,thickness,pointiness,nrm_geo --weld 0.0001`: short-range AO (0.015 x height), inside-AO thickness, Cycles pointiness on a welded copy, and the geometric normal without the normal map.

| rung | adds |
|---|---|
| `v7a_crevice` | v6 x `ao_short^cavityGamma` (fine cavity) + a black-point toe as a sixth grade value |
| `v7b_colour` | v7a + chroma detail boost (local a*b* deviations x1.6, σ 16 texels) + a **luminance-banded a*b* transfer**: per rendered-L band (8 bands), shift and scale a*b* to the DEF band's mean and spread, applied in texture space via each texel's luminance rank |
| `v7c_gloss` | v7b + **brightness-neutral wet speckle**: a highlight layer added after the grade, on fine bump tips (normal map agrees with the geometric normal, luminance above its local mean), weighted toward upward-tilted normals (the yaw-averaged sky reflection at a fixed camera elevation) and convex regions. The neighbourhood is darkened by the local mean sheen, so it adds sparkle, not overall brightness |
| `v7d_rim` | v7c + albedo darkening on thin extremities (inside-AO thickness), as a baked outline stand-in |

v7c and v7d reuse v7b's grade and transfer, so each rung's own change is what differs.

Images:
- `artifacts/homm3_prebaked_lighting/behemoth/sheets/focus_sprite_cam_v7.png`: DEF / v6 / v7b / v7c / v7d / v7c with a simulated contour, 3 DEF frames
- `sheets/battle_yaw_sand_v7n.png`, `sheets/battle_yaw_grass_v7n.png`: 4 facings
- `sheets/unity_hexLitReplica_v7.png`: Unity-editor replica render, v6 / v7b / v7c x 4 facings

Metrics are in `behemoth/metrics_v7n.json`. Sprite camera, sand relight, frame 02_00 unless noted:

| metric | DEF | v6 (before) | v7a | v7b | **v7c** | v7d |
|---|---|---|---|---|---|---|
| L* p5 / p50 / p95 | 2.7 / 26.2 / 57.0 | 8.8 / 30.3 / 56.7 | 7.0 / 31.4 / 61.9 | 3.9 / 29.2 / 57.0 | **4.3 / 28.6 / 56.7** | 3.4 / 27.2 / 53.5 |
| local contrast | 5.09 | 4.76 | 5.44 | 5.32 | **5.43** | 5.24 |
| chroma p10 / p50 / p90 | 4.9 / 18.5 / 28.2 | 8.2 / 19.4 / 29.9 | 7.8 / 18.8 / 29.4 | 5.4 / 17.0 / 28.4 | 4.8 / 15.4 / 25.4 | 4.3 / 14.4 / 24.2 |
| hue spread (circular SD, C>5) | 13.0° | 4.2° | 4.9° | 14.7° | **13.4°** | 13.2° |
| highlight Lab | (55.7, 4.7, 19.4) | (55.9, 10.2, 26.3) | (60.6, 10.9, 26.7) | (56.0, 4.3, 21.4) | **(55.5, 3.5, 20.7)** | (52.4, 3.5, 20.2) |
| L-histogram distance f001 / f013 / f050 | - | 3.74 / 2.79 / 2.49 | 5.06 / 3.78 / 1.30 | 2.49 / 1.33 / 2.81 | **2.01 / 0.96 / 3.18** | 1.26 / 1.21 / 4.61 |
| sand facing spread / front-back | - | 5.1 / 2.3 | 5.6 / 2.7 | 5.4 / 2.6 | 5.4 / 2.7 | 5.0 / 2.3 |
| grass facing spread / front-back | - | 3.5 / 2.4 | 4.1 / 2.9 | 4.0 / 2.8 | 4.0 / 2.8 | 3.5 / 2.4 |
| Unity replica facing spread (sand) | - | 5.2 | - | 5.6 | 5.7 | - |

Reading the ladder:
- **Crevices (v7a).** The cavity term alone does not close p5: the refitted grade brightens it away (7.0). It is the colour rung that gets p5 to 3.9-4.3, because the banded transfer pulls the darkest band's colour to the DEF's near-neutral black. The toe settles at 0.017.
- **Colour (v7b) is the biggest single gain.**
  - Hue spread rises from 4° to 14.7° against the DEF's 13°.
  - Highlights become the DEF's cream: (56, 4.3, 21.4) against (55.7, 4.7, 19.4).
  - The b* range matches.
  - The histogram distance falls to 2.49 / 1.33.
  - By eye, the mottled olive/gold speckle appears on the arms and shoulders.
- **Wet sheen (v7c).**
  - The first additive version lifted the whole unit: median 29 -> 32, p5 3.9 -> 6.9. Near black, L* is steep, so a faint broad sheen lights the crevices.
  - A floor on the mask plus the brightness-neutral form fixed that: p5 4.3, histogram distance 2.01 / 0.96, and local contrast 5.43 against the DEF's 5.09.
  - At battle scale it reads as crisper, slightly scaly speckle rather than "wet". It is baked view-independently, so it looks the same at every facing (`battle_yaw_sand_v7n.png`).
  - It costs some chroma (p50 15.4 against 18.5).
  - It is a true specular only in the sense of the yaw-averaged sky term. Real sheen needs a shader Hex/Lit does not have.
- **Baked rim (v7d) is a negative.**
  - It barely moves the edge profile: 27.3 at the edge against the DEF's 15.4.
  - It darkens the whole body: p95 53.5, histogram 4.61 on f050.
  - From behind and in the claws it reads muddy and dirty.
- **Flattening.** The mean histogram distance over the 3 frames goes 3.01 (v6) -> 2.21 (v7b) -> 2.05 (v7c) -> 2.36 (v7d). Gains flattened after v7c, so the push stops there.
- **Symmetry is kept.** The facing spread moves by 0.3-0.5 L at most, still well under the shipped bake's 6.6-7.0.

**Per-class grade (`v7e_material`) is a negative on the Behemoth.** This rung tries the Titan agent's per-material idea (`tools/homm3_vfx/titan_prebake.py` v6m) on v7c:
- Classes are k=3 k-means on albedo L*a*b*, ordered by L*. The DEF is clustered the same way. Each class is graded to its DEF cluster and soft-blended.
- Every sprite-camera metric is worse than v7c: histogram distance 2.37 / 2.16 / 3.61, local contrast 4.72, p5 7.6, hue spread 9.5° (`metrics_v7e.json`).
- The Titan's materials are separated by hue: gold, grey, red, blue. The Behemoth's are separated mostly by lightness: dark fur, olive skin, bone.
  - The lightness-ordered classes do not correspond. The texture's bright class is claws and bone (14% of texels); the DEF's is cream speckle on the skin. Its fit cost is 7.6, against 1.4 for the dark class.
  - Grading each class to its own range compresses the contrast between classes.
- The banded a*b* transfer in v7b already supplies the lightness-conditioned colour a per-class grade would add. Keep the per-class grade for units whose materials differ in hue.

Grade caveat: v7b's fitted grade sits on two bounds, gamma 0.5 and wb 0.6. The banded transfer does the colour work that the grade's white balance cannot. A rollout should check the bounds per unit, not trust a fit that is pinned to them.

### Does the game draw an outline?

This is a static read only.
- The installed `resources.assets` ships **`Hidden/Hex/ContourLines`**, a full-screen pass. Its disassembly is in `artifacts/homm3_prebaked_lighting/contour_lines_ps/`, produced by `disasm_hex_lit.py --shader Hidden/Hex/ContourLines --all-ps`.
  - It reads scene depth and the Prepass's octahedral normals, plus a packed 4-bit tag / 4-bit opacity.
  - It sums depth-discontinuity and normal-difference edges over the 8 neighbours, with a Fresnel-like `(1-N.V)^5` bias.
  - It writes one constant line colour at `edge x opacity x global strength`.
- Hex/Lit exposes `_ContourLinesTag`, `_ContourLinesOpacity` and `_NormalBasedContourLines`. Of the installed materials that carry them, 1,304 use opacity 1 / tag 1, including hero and unit materials.
- The plugin builds unit materials as `new Material(nativeDonor)`, so they most likely inherit opacity 1 and **get the game's contour lines**.
- The line colour, width and global strength are runtime constant-buffer values, so whether the line is as dark as the sprite's (L 15 at the edge) is unverified.
- A simulated 1.5 px / 0.9-opacity silhouette line (`--sim-contour`, colour a guess) brings v7c's edge band from 30.2 to 18.7, near the DEF's 15.4 (`sheets/sprite_cam_game_sand_v7n_simcontour.png`).

**Conclusion:** leave the outline to the runtime pass and bake no rim darkening.

## Materials and tessellation (widened scope)

- **Materials.** At runtime only the base colour matters. Grade, contrast and saturation go into the baked texture: v6's fitted grade is exposure 1.40, gamma 0.77, sat 0.75, wr 1.34, wb 0.65. Roughness, metallic and normal-map strength have no effect on the installed Hex/Lit, so changing them is pointless unless the donor or shader question below resolves the other way.
- **Runtime tessellation is impossible.** Hex/Lit has no hull or domain stages.
- **Baked Catmull-Clark subdivision, level 1**, placed before the Armature so the weights interpolate:
  - On the **unwelded** Meshy mesh it opens black cracks along the UV-split seams, even with linear UVs, and shrinks the silhouette slightly. See `sheets/subdiv_compare.png` and `subdiv_uv_compare.png`.
  - After a **0.1 mm weld** (13,694 -> 4,594 vertices) it is clean: 27,373 vertices and 54,552 triangles (Blender-evaluated), about **6x the triangles**. See `sheets/subdiv_weld_compare.png`. The exported vertex count rises further once the UV seams split again.
  - Skinning holds because the weights are interpolated.
  - The 128 corrective-smooth shape keys do **not** survive. The probe cleared them, and a delivery would have to re-run `bake_cs.py` on the subdivided mesh.
  - Visual gain is marginal: smoother claws and teeth, softer fur shelves, little change at battle scale.
  - **Not recommended now.**

## Recommendation

Updated after the v7 push: use **`v7c_gloss`**, which is v6 plus fine cavity, the banded colour transfer and the brightness-neutral wet speckle. Leave all directional light to the runtime sun and the outline to the runtime ContourLines pass. The reasoning below for the v6 base still holds.

Original recommendation: use a **v6-style yaw-invariant bake** and leave all directional light to the runtime sun.

- The bake: AO with crevice gamma, sky/hemisphere occlusion, and a height gradient, plus a detail boost, with the normal map baked in, a per-unit palette grade fitted to the DEF, and **no baked directional key**.
- If a unit needs extra form, only the sagittally mirrored key (v4) is acceptable, at low gain.
- A rollout would replace the front-biased key in `solve_unit_light_palette.py`'s approved-oe bake. It would not add to it.

Why v6:
- It is closest to the sprite where the sprite's character lives: local contrast 4.8 against 5.1, chroma about 19, and the ochre palette.
- It has the smallest front-back asymmetry of any variant (2.3 / 2.4 L).
- It depends on nothing the runtime lacks.

## Unit facing (`--front`)

`bake_terms.py` and `render_passes.py` take `--front auto|+x|-x|+y|-y`; `subdiv_probe.py` takes `--front`, default `-y`.
- `auto`, the default, takes the unit's front from the Head bone's horizontal offset from Hips. The Behemoth resolves to -Y, and a re-render of `battle_faces_camera` is identical to the committed one (max difference 1e-7).
- An upright biped such as the Titan has its head almost straight above its hips, so `auto` refuses when that offset is under 10% of the Head-Hips distance. Pass the axis explicitly then. This replaced a silent guess that swapped the Titan's facing labels.
- The resolved front and its source are written to `views_meta.json` and `terms_meta.json` as `front` / `frontSource`.

## Per-unit knobs (`prebake_lab.py --params`)

- **Grade** `[exposure, gamma, sat, wr, wb]`: fitted automatically against that unit's DEF.
- **`aoGamma`** (1.4) and **`creviceGammaScale`** (2.0, used by v6 only): crevice depth. The Behemoth wants it darker.
- **`skyFloor`** (0.35): how dark downward-facing surfaces go.
- **`heightDepth`** (0.35) and **`heightPower`** (0.6): the feet-to-back gradient. Keep it near zero for flyers and tall thin units.
- **`detailAmount`** (1.0) and **`detailSigma`** (12 texels): speckle strength and scale. This depends on texture resolution and on the Meshy texture's own noise.
- **v7c** (`behemoth/knobs_v7n.json`):
  - `cavityGamma` (2.0) on `ao_short`
  - grade toe (fitted, bounded by `toeMax` 0.08)
  - `chromaDetail` (0.6) / `chromaSigma` (16)
  - `bandCount` (8), `bandStrength` (1.0) and `bandLocalSigma` (24): the banded transfer is fitted automatically per unit
  - `glossAmount` (0.6), `glossFloor` (0.15) and `glossNeutral` (1.0), plus `glossSigma` (3), `glossScale` (0.25), `glossPower` (1.5), `glossUpPower` (1.5) and `glossTintSrgb`
  - `v7d` only: `rimAmount`, `rimPower` and `rimThickLo`
  - `v7e` only: `classCount` (3) and `classSoftness` (8 Lab)
- **Bake-time**:
  - AO distance (0.12 x height)
  - sky ground value (0.25)
  - bake resolution (2048)
  - v7 extras: `--ao-short-dist` (0.015), `--thick-dist` (0.05), `--weld` (0.0001 m, needed for pointiness on the unwelded Meshy mesh)
- **For v4 only**: `wTop`, `wFront`, `wBack`, `fill` and `keyGain`.

## Unproven / open

- In-game appearance. There is no build, no deploy, and no in-game screenshot.
- Whether the plugin's `_BumpMap` / `_MetallicGlossMap` donor path resolves against the installed Hex/Lit, which declares neither property, and whether the normal map therefore reaches the screen. It presumably does not.
- The battle camera's orientation relative to arena +Z (assumed), the game's colour space (the lab project is Linear), and post-processing.
- The ContourLines colour, width and strength at runtime, and whether our rebound unit material really keeps opacity 1. Both are needed to know whether the sprite's dark rim is covered.
- The sprite-camera renders use the retarget's frame pose, which does not match the DEF frame's pose (the DEF is more in profile). Some of the visual gap in the focus sheets is pose or registration, not lighting.
- Whether the baked sheen reads as "wet" in motion. It is static speckle, so it cannot glint as the unit turns.
- Results cover one unit on one arena family. Other units need their own grade fit and knob check.
