# Vanilla Olden Era unit materials and baked lighting

Status: investigation, 2026-10-08. Every finding here comes from a **static read** of the installed Golden Era build
(`resources.assets` via UnityPy, compiled Hex/Lit bytecode via d3dcompiler) plus **generated-artifact** measurements
of our delivered textures. Nothing was checked in game, and runtime values (SSAO strength, global emission scale,
contour colour) are unknown.

Question: how do vanilla units author base colour and materials for `Hex/Lit`, the shader our HoMM3 units also
render through, and what should `tools/homm3_unit_look/` change so our units sit naturally beside them?
Related docs: `docs/homm3_prebaked_lighting.md`, `docs/homm3_unit_look_pipeline.md`, `docs/olden_era_vanilla_vfx_style.md`.

## Method

- Probe: `tools/homm3_prebake/probe_vanilla_unit_materials.py` (`extract` / `analyze` / `sheet`). It loads
  `resources.assets` lazily, one prefab at a time. Peak RSS was under 1 GB, it ran on the CPU only, and the whole
  run took about 3 minutes.
- Sample: 28 base-tier vanilla units across all 7 factions. It covers small units (goblin rogue, twinkle, troglodyte),
  large ones (hydra, black dragon, titan, minotaur), armoured (esquire, animated armor, sunlight cavalry), furred
  (gorilla, griffin, unicorn), undead (skeleton, ghoul, lich, vampire) and magical units (phoenix, lich, trick demon,
  lava larva). Ours: castle_slice_v1 h3_angel, h3_pikeman, h3_battle_griffin, h3_cavalier, h3_swordsman and h3_monk
  (`inputs/basecolor.png` + `inputs/look_delivered.glb`).
- Measured on the body mesh and its `_MainTex` only, with texels outside the UV islands and alpha-clipped texels
  excluded:
  - L\* and chroma percentiles at 512²;
  - local contrast, the mean |L − blur| at a fine scale (σ ≈ 1.5 px) and at a mid scale (≈ 2% of the texture);
  - per-vertex Pearson r between texture L\* and three things: a concavity proxy (smoothed-Laplacian · normal, so
    r > 0 means crevices are darker), the up-component of the normal, and height;
  - texels per unit height, √(W·H·UV area / surface area) × height.
- Scratch, with the extracted textures, meshes, per-unit `unit.json` and `analysis.json`:
  `V:/olden_port_work/vanilla_material_study/`. No game texture is in git.

## 1. Materials: what vanilla units actually set

Static read of 41 Hex materials on the 28 units (`vanilla/<unit>/unit.json`).

| aspect | vanilla practice |
|---|---|
| shader | `Hex/Lit` on every body, weapon and prop renderer. No unit uses another body shader |
| keywords | `HEX_DITHER_FADE_ENABLED` on all 41. `HEX_ALPHA_CLIP_ENABLED` on 24 (cutout wings, hair, cloth, feathers), with render queue 2450 instead of 2000. `HEX_EMISSION_MAP_ENABLED` on 9 |
| `_Color` | (1, 1, 1, 1) on every material: **all colour lives in the texture** |
| textures | `_MainTex` only, plus `_EmissionTex` when emissive. No normal, mask or AO map; Hex/Lit declares no slot for them |
| format | 1024² in 46 of 52 textures, 2048² for the cavalry, phoenix, scorpion and unicorn. DXT1 (opaque) or DXT5 (alpha), with mips |
| layout | One diffuse per unit. Weapons, props and bags often get a second material on a separate mesh or submesh. Some atlases are shared between units (`weapons_diffuse`; the scorpion uses `godslayer_common_emissive`) |
| UVs | Hand-unwrapped, with **mirrored or stacked islands**: summed UV area is 1.22 (median) against 0.66 unique coverage. Gutters are filled with island colour (0–6% black) |
| vertex colour | Absent on most units. The druid and unicorn carry white; the sunlight cavalry carries R ≈ 1–4/255, the `FLAG` displacement mask. The Lit pixel shader has **no COLOR input**, so vertex colour never tints shading |
| per-context props | `_HexFade` (0), `_PreviewScreenOffset` (0), `_HighlightTag` (0), `_ContourLinesOpacity` 1 / `_ContourLinesTag` 1 (lava larva belly 0.79), `_NormalBasedContourLines` 0, `_VertexDisplacementType` 0, `_CullMode` 2 (back). Identical on every unit |
| leftovers | The esquire and skeleton serialise legacy toon properties (`_OtlColor`, `_ShnIntense` and others). Hex/Lit does not declare them, so they are inert |

Texel density is about **830 texels per unit height** (median, IQR 690–980). The 2048² units reach 1230–2000.

## 2. Hex/Lit: what changes a unit's lighting

The keyword list comes from `artifacts/homm3_prebaked_lighting/game_lighting_probe.json`. The Lit-pass math comes from
`hex_lit_ps/ps_o0_t4_n150.txt` and, for emission, from a fresh disassembly at
`V:/olden_port_work/vanilla_material_study/grp_03.txt` (`disasm_emis.py`). Constant-buffer slots map to properties by
declaration order, which is an inference.

```
albedo  = tex(_MainTex, uv with a derivative mip bias cb0[51]) * _Color
albedo  = lerp(albedo, grey(albedo), G_desat)        # only when a per-material mode == 2; global strength
ao      = _SSAOEnabled ? tex(SSAO, screenUV) : 1
direct  = sum_dir (sat(N.L_i) * col_i) * shadow_main + sum_punctual(...)      # no specular, no normal map
rgb     = albedo * (ao * SH_ambient(N) + direct * lerp(1, ao, k_ssao))
rgb    += emission                                    # HEX_EMISSION_MAP_ENABLED only
emission = tex(_EmissionTex, uv + _UvScroll*t) * _EmissionColor
         * max(_EmissionMinPower, G_e * (1 - _EmissionBlinkPower * |cos(t * _EmissionBlinkSpeed)|))
```

- **SSAO is part of unit lighting.** It multiplies the ambient fully and the sun by `k_ssao`.
  - `StreamingAssets/gfx_presets.json` sets `ssao` to 1 or 2 on all three presets (High / Medium / Low), never 0.
  - The radius and strength are runtime values, not read.
  - So vanilla textures get crevice darkening from the screen, not only from paint.
- **Emission is additive and unlit.** It goes through the same global grey-out as the albedo.
  - With the vanilla values (MinPower 0.8, BlinkPower 0.2, Speed 1), the glow pulses between 0.8 and 1.0 of full
    at twice the speed, because of |cos|.
  - With MinPower 1.0 (titan, trick demon, lava larva body, scorpion), the glow is **steady**.
  - This replaces the assumed `MinPower + BlinkPower·sin` in `docs/olden_era_vanilla_vfx_style.md` §3.3.
- **No rim, fresnel, team-colour, hit-flash or outline keyword exists** in Hex/Lit's keyword list.
  - The outline is the full-screen `Hidden/Hex/ContourLines` pass, driven by `_ContourLinesOpacity/Tag`.
  - Hit and status looks are overlay materials appended by `BhBattleTimelineHelper.AppendMaterial`
    (`magic/Fresnel` and others; `docs/olden_era_vanilla_vfx_style.md`).
  - The other keywords are visibility or context: dither/cutout fade, `HEX_UI_PREVIEW_CAMERA`, fog of war,
    terrain blend, and `FLAG`/`TREE` vertex displacement.

## 3. Base colour: how much lighting vanilla paints in

Measurements are static texture/mesh reads. L\* is in sRGB-Lab, 0–100.

| unit | tex | L p5 / p50 / p95 | C50 | fine lc | mid lc | r(L, crevice) | r(L, up-normal) | r(L, height) | texels/H |
|---|---|---|---|---|---|---|---|---|---|
| esquire | 1024 | 12 / 23 / 57 | 3 | 2.2 | 5.5 | +0.31 | +0.28 | +0.21 | 896 |
| crossbowman | 1024 | 7 / 20 / 51 | 15 | 2.0 | 5.1 | +0.03 | +0.27 | +0.21 | 892 |
| sunlight_cavalry | 2048 | 10 / 20 / 51 | 2 | 2.9 | 5.4 | -0.02 | +0.26 | +0.39 | 1997 |
| griffin | 1024 | 16 / 36 / 70 | 14 | 2.5 | 6.4 | +0.10 | +0.09 | +0.01 | 760 |
| angel | 1024 | 12 / 50 / 81 | 4 | 2.3 | 7.6 | -0.01 | +0.12 | +0.49 | 963 |
| lightweaver | 1024 | 12 / 38 / 82 | 11 | 2.6 | 7.1 | -0.03 | +0.34 | +0.18 | 1444 |
| skeleton | 1024 | 12 / 30 / 70 | 11 | 2.8 | 6.8 | +0.12 | +0.37 | +0.34 | 955 |
| lich | 1024 | 7 / 22 / 61 | 3 | 3.3 | 6.9 | +0.11 | +0.33 | +0.40 | 846 |
| vampire | 1024 | 9 / 17 / 58 | 9 | 2.0 | 5.0 | -0.06 | +0.12 | +0.18 | 976 |
| ghoul | 1024 | 9 / 23 / 56 | 9 | 1.5 | 4.6 | +0.04 | +0.30 | +0.45 | 845 |
| ent | 1024 | 12 / 27 / 55 | 12 | 2.6 | 5.8 | -0.07 | +0.35 | +0.47 | 553 |
| phoenix | 2048 | 14 / 32 / 62 | 54 | 2.0 | 5.4 | +0.16 | +0.00 | +0.32 | 1229 |
| twinkle | 1024 | 32 / 53 / 73 | 54 | 2.3 | 6.0 | +0.04 | -0.16 | +0.01 | 361 |
| druid | 1024 | 3 / 26 / 57 | 15 | 3.1 | 7.8 | +0.01 | +0.22 | +0.33 | 665 |
| troglodyte | 1024 | 18 / 35 / 63 | 21 | 1.6 | 5.1 | +0.20 | +0.20 | +0.15 | 699 |
| hydra | 1024 | 5 / 19 / 49 | 12 | 2.3 | 5.1 | +0.20 | +0.18 | +0.33 | 991 |
| black_dragon | 1024 | 6 / 20 / 46 | 12 | 2.2 | 5.5 | +0.03 | +0.12 | +0.26 | 664 |
| minos | 1024 | 9 / 21 / 50 | 12 | 2.8 | 6.4 | +0.12 | +0.33 | +0.01 | 607 |
| lava_larva | 1024 | 4 / 16 / 48 | 10 | 1.6 | 4.8 | +0.14 | +0.14 | +0.19 | 421 |
| scorpion | 2048 | 4 / 18 / 44 | 6 | 2.1 | 5.3 | +0.18 | +0.33 | +0.25 | 1855 |
| trick_demon | 1024 | 5 / 18 / 47 | 10 | 1.9 | 5.2 | -0.06 | +0.24 | +0.10 | 738 |
| gorilla | 1024 | 12 / 25 / 44 | 13 | 1.7 | 4.5 | +0.13 | +0.49 | +0.19 | 702 |
| goblin_rogue | 1024 | 7 / 26 / 47 | 37 | 1.1 | 3.4 | +0.00 | +0.17 | -0.06 | 753 |
| titan | 1024 | 48 / 70 / 93 | 3 | 1.9 | 5.8 | +0.03 | +0.25 | +0.13 | 822 |
| animated_armor | 1024 | 11 / 25 / 45 | 22 | 1.8 | 4.9 | -0.00 | +0.42 | -0.01 | 783 |
| unicorn | 2048 | 29 / 49 / 80 | 26 | 2.1 | 6.2 | -0.17 | +0.15 | +0.41 | 1613 |
| unfrozen_cultist | 1024 | 5 / 21 / 58 | 12 | 1.4 | 4.4 | +0.17 | +0.36 | +0.06 | 1254 |
| peasant | 1024 | 10 / 28 / 76 | 12 | 2.6 | 7.2 | +0.01 | +0.33 | -0.04 | 611 |

Principles, read from the numbers and the contact sheet:

1. **The black floor is lifted.** Vanilla albedo almost never goes below L\* ≈ 5–12; p5 has a median of 9.6. The
   darkest parts are painted dark colours, not black. The contour pass, the shadow map and SSAO supply the true
   blacks at runtime.
2. **Little crevice AO is painted in.** Texture darkness barely follows concavity: the median r is +0.03, and the
   darkest 10% of texels are only 1.16x more likely than chance to sit in the most concave 20%. A few hand-armoured or
   scaly units (esquire, hydra, troglodyte, cultist) reach r ≈ 0.2–0.3. SSAO covers the rest.
3. **A soft top-light, sky-like gradient is painted in.** Up-facing surfaces are lighter on 26 of 28 units (the phoenix is flat and the twinkle negative; median
   r = +0.25), and L rises with height (median +0.20; the angel, ghoul and ent are at about 0.45). This term does not
   depend on yaw. It is not a directional key: no unit shows a left/right or front/back bias.
4. **The surfaces are smooth and hand-painted.** Fine local contrast is about 2.2 L and mid-scale about 5.5 L. Detail is
   painted value and hue changes (plates, trims, cloth folds, fur clumps), not photographic noise or speckle.
5. **Highlights are painted on edges and plates.** Armour (esquire, lich, cavalry) carries painted specular streaks
   and edge wear; p95 reaches 57–82 on metal and cloth units. They are baked once, with no view dependence.
6. **Saturation is moderate and per material.** The median chroma is 11.6. Each material keeps one coherent hue.
   Only the magical units (phoenix, twinkle, goblin rogue) are saturated (C ≈ 37–54).
7. **There is one 1024² diffuse.** Mirrored UVs and filled gutters, and `_Color` is always white.

## 4. Glows and effects

- **Steady body glow is an emission map.**
  - Painted, coloured and LDR (max 1.0) `_EmissionTex`, with `_EmissionColor` left white. The lava-larva highlight
    overlay at (2.52, 0.86, 0.37) is the only HDR tint in the sample.
  - Coverage is small: 3.5–4.3% (lich, black dragon), 8% (trick demon), 18% (lava larva), and 33–36% for the phoenix
    and titan, where the whole fire or energy body glows.
  - The diffuse under the glow is often painted bright as well (phoenix 47 against 21 elsewhere, trick demon 52
    against 18), so the glow area reads lit even when emission is low.
- **Motion lives in particles.** Flames, sparks, mist and hit bursts are ParticleSystems on `magic/VfxUber` (HDR
  `_Color`, additive). No unit keeps a steady dynamic light; Light modules only flash on hits.
  `docs/olden_era_vanilla_vfx_style.md` §2–3 and `tools/homm3_vfx/vanilla_style_fx.py sources` already cover this, and
  this study agrees with them.

## 5. Ours against vanilla

Medians, with IQR in brackets. Ours = the 6 castle_slice_v1 units above.

| measure | vanilla (28) | ours (6) | reading |
|---|---|---|---|
| L\* p5 | 9.6 (6.6–12.2) | **0.4** (0.3–0.7) | ours crush to black; p25 is only 1.4–4.4 on the cavalier, swordsman and pikeman |
| L\* p50 / p95 | 24.8 / 56.8 | 16.9 / 62 | darker midtones, similar highlights, so more overall contrast |
| chroma C50 | 11.6 | 6.4 | greyer midtones, with saturated accents only |
| fine local contrast | 2.2 | **6.5** | about 3x: speckle from the detail boost and v7c gloss |
| mid local contrast | 5.5 | **13.5** | about 2.5x: survives mip filtering at battle scale |
| r(L, crevice) | +0.03 | **+0.30** | strong baked AO/cavity, on top of runtime SSAO |
| dark-in-crevice lift | 1.16 | 2.05 | |
| r(L, up-normal) / r(L, height) | +0.25 / +0.20 | +0.11 / +0.08 | ours have *less* sky/top gradient than vanilla |
| texels per unit height | 834 | 1303 | ours are denser; this is not a deficit |
| texture | 1024² DXT, mirrored | 2048² unique Meshy islands | about 4x the memory per unit |
| black gutters (non-island texels with L < 5) | 0–6% (lich 20%) | **57–69%** | ours pad about 8 px at 2048², about 1 texel at mip 3 |

h3_angel is the outlier on the bright side: p50 62 against vanilla angel 50, with local contrast 9.7. h3_monk is the
calmest of ours (lc 3.1) but the darkest (p95 32).

Contact sheet: `V:/olden_port_work/vanilla_material_study/contact_sheet.png`.
- Each tile shows the texture, the albedo-only render, and the albedo under the sand-arena Hex/Lit formula (flat
  ambient + sun, no shadow or SSAO).
- The vanilla tiles are grey; the 6 tiles at the end, with a red-brown band, are ours.
- It is a rest-pose software render, not the game.
- By eye, ours read darker and grittier, with black-legged horses and near-black cloth, beside smoother and lighter
  vanilla units.

## 6. Recommendations for the look pipeline, ranked by expected visual impact

Each knob below is in `tools/homm3_unit_look` / `prebake_lab.py` (`docs/homm3_prebaked_lighting.md`, Per-unit knobs).
None of these has been tried yet. Prove each on one unit in the live preview before any sweep.

1. **Lift the black floor to vanilla's (albedo p5 ≈ 6–10, p25 ≥ 12).**
   - Knobs: raise the grade toe or black point (`toeMax` 0.08 → a fixed floor of about 0.02–0.03 linear) and stop
     fitting p5 to the DEF.
   - DEF conflict: the DEF's p5 of 2.7 is mostly outline and cast-shadow pixels, which the runtime already draws
     (ContourLines, the shadow map, SSAO). Fit the grade on DEF body pixels with the outline band excluded, or cap the
     L target at about 8.
   - Albedo 0 can never be lit, so this is the largest gap beside vanilla units.
2. **Halve the baked cavity and AO** (r 0.30 → about 0.1).
   - Knobs: `aoGamma` 1.4 → about 0.8, `cavityGamma` 2.0 → about 1.0, `creviceGammaScale` 2.0 → about 1.0.
   - Runtime SSAO is on at every preset and multiplies the ambient, so the current bake double-darkens crevices.
   - DEF conflict: the DEF crevices are near-black. Keep only fine cavity that is smaller than the SSAO radius.
3. **Cut high-frequency contrast by about 2x.**
   - Knobs: `detailAmount` 1.0 → about 0.4, `glossAmount` 0.6 → about 0.25 (or drop the v7c speckle), and lower
     `chromaDetail`.
   - Fit local contrast on a battle-scale render, not in texture space. The DEF's 5.1 was measured on sprite pixels.
   - DEF conflict: the sprite's speckle character. Prefer fewer, larger painted variations to per-texel noise.
4. **Fill every UV gutter with island colour** (push-pull dilation to the full texture) before the PNG is written.
   - No DEF conflict, and cheap.
   - It removes the black bleed at the mips battle samples, which shows as dark seams on fragmented Meshy islands.
     This is expected from the measurement, not seen in game.
5. **Add vanilla's yaw-invariant sky/top gradient** (target r(L, up) ≈ 0.2).
   - Knobs: raise the sky term (`skyFloor` 0.35 → about 0.5 with a stronger up-weight) or `heightDepth` slightly.
   - It is yaw-invariant, so it is consistent with the no-directional-key rule. Minor DEF conflict: the DEF shows
     ~0 top-bottom delta.
6. **Midtone chroma.** Let the band a\*b\* transfer keep or raise mid chroma (vanilla C50 ≈ 12, ours 6) instead of
   greying midtones. Hue stays the DEF's, so the only DEF conflict is the chroma *level*. Low priority.
7. **Emission follows vanilla's convention.**
   - Use a painted coloured LDR `_EmissionTex` with `_EmissionColor` white, and MinPower 0.8 / Blink 0.2 / Speed 1,
     or MinPower 1.0 for a steady glow.
   - Brighten the diffuse under the glow as well.
   - Fix `vanilla_style_fx.py` and the vfx doc to the measured pulse formula above.
   - Our compiled specs use an HDR tint such as (2.2, 1.1, 0.55) on a luminance mask. That is legal, but it is not how
     vanilla authors it.
8. **Material hygiene, no visual change.** Keep `_Color` white, `HEX_DITHER_FADE_ENABLED` on, alpha clip only on
   cutout parts, and `_ContourLinesOpacity` 1. Resolution can stay at 2048²: our density already exceeds vanilla's,
   and dropping to 1024² is a memory choice, not a look choice.

## 7. Vanilla peers for the planned A/B (cavalier, gremlin, walking dead, behemoth)

| ours | natural vanilla peer | why |
|---|---|---|
| h3_cavalier | `humans/sunlight_cavalry` (2048², horse + rider) | same role and faction, plate armour on a horse |
| h3_gremlin | `neutral/goblin_rogue`, alternative `demons/trick_demon` | small humanoid; the trick demon is a small caster with emission |
| h3_walking_dead | `neutral/ghoul`, alternative `undead/skeleton` | rotting undead footsoldier, cloth rags, muted greens |
| h3_behemoth | `neutral/gorilla`, alternative `dungeon/hydra` | large furred beast; the hydra stands in for a big scaly beast |

## Reproduce

```
python tools/homm3_prebake/probe_vanilla_unit_materials.py extract            # ~1 min, <1 GB RSS
python tools/homm3_prebake/probe_vanilla_unit_materials.py analyze --ours h3_angel h3_pikeman h3_battle_griffin h3_cavalier h3_swordsman h3_monk
python tools/homm3_prebake/probe_vanilla_unit_materials.py sheet  --ours h3_angel h3_pikeman h3_battle_griffin h3_cavalier h3_swordsman h3_monk
```

## Caveats

- The concavity proxy is geometric (Laplacian), not ray-cast AO. Meshy meshes are denser and noisier than vanilla, so
  compare r values as tendencies.
- r(L, up) and r(L, height) partly reflect material layout (light helmets, dark boots), not only painted light.
- Our metrics are on the delivered texture, which is graded to the DEF under the sand relight. Both go through the
  same shader, so albedo against albedo is a fair comparison. On-screen values also depend on SSAO, shadows and post,
  which were not read.
- In h3_battle_griffin's delivered base colour, large saturated-red regions are visible. This study only records it.
