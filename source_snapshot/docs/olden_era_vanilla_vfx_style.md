# Olden Era Vanilla VFX Style

Status: research record (2026-09-26). It describes how vanilla Olden Era builds unit and ability effects, so that
HoMM3 unit effects can be redesigned in the same style. HoMM3 decides **what** an effect depicts and **when** it
fires. It does not supply the pixels.

Proof-tier labels used below:

- **static-asset**: read from the installed Golden Era serialized assets with UnityPy
  (`tools/homm3_vfx/vanilla_vfx_probe.py`). This shows what is authored, not what runtime code does with it.
- **static-bytecode**: read from the DXBC disassembly of the installed shaders. Constant-buffer slots are mapped
  to property names by inference, not by reflection data.
- **decomp-note**: read from the Cpp2IL readable-C# samples. This is static code shape, not a runtime observation.
- **lab-render**: a Unity-editor render with lab replica shaders. It is not the game.
- **not proven**: anything not covered by one of the tiers above.

Nothing in this document is runtime-proven or in-game-proven.

## 1. Where effects live (static-asset)

The ResourceManager container in `globalgamemanagers` addresses objects in `resources.assets`. A dump of every
container row is in `artifacts/vanilla_vfx_style/resource_container.json`.

| Container prefix | What it holds |
|---|---|
| `magic/prefabs_vfx/...` | 530 effect GameObjects, plus 418 TimelineAssets (`*_timeline_vfx`) |
| `magic/materials_vfx/...` | 2995 effect materials |
| `magic/textures_vfx/...` | 407 effect textures |
| `magic/shaders_vfx/...` | 62 effect shaders |
| `magic/mesh_vfx/...` | effect meshes: rings, cracks, drops, slashes, waves |
| `effects/{blood,projectiles,rays,status,hex_selection,global_map}` | per-unit projectiles, rays, blood and status effects |
| `units/<faction>/1prefabs/<unit>` | unit prefabs, with their bone-parented effect roots inside them |

**Effects are Shuriken `ParticleSystem`s.** No VFX Graph was found.

- Renderer modes in use: 0 Billboard, 1 Stretched, 4 Mesh, and 5 None. Mode 5 is used for trail-only systems,
  where the TrailModule draws with the renderer's second material.
- Modules in use: Color, Size, Rotation, Velocity, Noise, UV sheet, Trail, CustomData, Sub, ClampVelocity and
  Lights.
- Typical shape: an empty root PS (duration 0.05, lifetime 0.0001) acts as a group node over 3 to 25 child
  systems.
- `simulationSpeed` is often not 1. For example, the phoenix wrist fire runs at 1.5.

## 2. How effects attach to units (static-asset + decomp-note)

The 2026-10-04 [custom attachment investigation](homm3_custom_vfx_attachment_investigation.md)
adds an installed Graverobber hand-origin reference and records the unresolved
weapon-VFX consumer route. It does not establish a custom-unit placement fix.

- **Effect roots are children of skeleton bones inside the unit prefab, and are inactive by default.** For example,
  the phoenix has:
  - `Phoenix_upg_ability_fire_01/02` under `WristFeather1_L/R` and `WristFeatherC_L/R`;
  - `Phoenix_ability_rise_spine` and `Phoenix_ability_rise_idle_spine` under `Spine`;
  - `Phoenix_upg_hit_fire_Root` under the animator root.
- **Idle effects are separate prefabs named `<unit>_idle_<bone>`.** Examples: `obsidiandragon_fire_idle_jaw`,
  `lightweaver_idle_def.staff`, `vampire_idle_wing.a.l.002`, `druid_idle_spine` and `qilin_upg_idle_head`.
  - The unit-view MonoBehaviour (interop `MonoBehaviourPublicTrprshTrprVeSkTrshmeUnique`) holds `idleVFX`
    (`ParticleSystem[]`), `projectileSpawnPoint`, `projectileEndPoint`, `shieldPoint` and `meshRenderer`.
  - `BhEffectHelperComplex.idleEffect` is the other idle carrier.
- **Attack and ability effects are played by Timeline.** The prefab root carries a `PlayableDirector` and
  `Hex.Session.Battle.BhBattleTimelineHelper`, and `*_reciever` children carry `SignalReceiver`s.
  - Per the decomp-note `experiments/cpp2il_readable_csharp/samples/battle_review_pack/focused/02_Hex.Session.Battle.BhBattleTimelineHelper_bbwt.md`:
    - `startAttackTimelines` and `impactAttackTimelines` are dictionaries keyed by AbilityID;
    - `bbwt(AbilityID)` plays the start timeline and `PlayImpact(AbilityID)` plays the impact timeline;
    - there are also `PlayEffectAtEnemy/AtHex/AtSelf(path)`, `PlayHexEffectOrdered`, and
      `AppendMaterial(path)` / `RemoveLastMaterial`, which push an overlay material onto the unit's
      SkinnedMeshRenderer.
- **Projectiles, rays and impacts** use `BhProjectileController`, `BhRayVfxController`, `ProjectileDestroyer` and
  `BhEffectHelper`. `BhParticleAccelerator` sits on every unit root.
- **Our runtime precedent** (source/static only): `Homm3MeshFx` (catalog `OfflineUnlockMod/homm3_mesh_fx/catalog.json`)
  already loads vanilla `Prefabs_vfx` (the Crusader sparks) through the game's `ResManager.Get` and parents them to
  bone sockets. This is an implementation precedent for reusing vanilla prefabs by reference, not proof of
  correct in-game placement.

## 3. Shaders and materials

### 3.1 `magic/VfxUber`, the effect shader behind almost every particle (static-asset + static-bytecode)

Material properties (`artifacts/vanilla_vfx_style/materials_seen.json`, 96 materials):

- Textures:
  - `_Texture`: tiling painted noise, scrolled by `_xSpeed01` / `_ySpeed01`.
  - `_Texture2`: optional second noise under keyword `_TWO_TEXTURES`, scrolled by `_xSpeed02` / `_ySpeed02`.
  - `_Mask`: the soft particle shape (a glow, a smoke puff or a gradient) on the particle's own UV.
- Erosion: `_Min` and `_Max`.
- Colour: `_Color`, which is **HDR**. Seen values run from 1.5 to 48, for example the phoenix fire `(8, 1.75, 0)`
  and the lightning `47.9` white.
- Blending: `_Blend1`=1 (One) and `_Blend2`=10 (OneMinusSrcAlpha). `_Blend` scales the output alpha.
- Other properties: `_CameraOffset`, `_Lerp`, `_Multiply`, `_ShowInFow`, and the ray start/end smoothness.
- Keywords: `_ACTIVE_BLENDADD`, `_ACTIVE_CAMERA_OFFSET_ON/OFF`, `_ACTIVE_CLAMP_ON/OFF`, `_MIN_BLENDING_` and
  `_TWO_TEXTURES`.

Vertex shader (`artifacts/vanilla_vfx_style/vfxuber_ps/vs_longest.txt`):

- The vertex is pushed toward the camera by `_CameraOffset`, so glows sit in front of the body they wrap.
- Noise UV = (particle UV + a per-particle custom stream) × tex ST + frac(speed × time). The custom stream gives
  each particle its own window into the noise.
- Mask UV = particle UV × mask ST.

Pixel shader (`artifacts/vanilla_vfx_style/vfxuber_ps/ps_longest.txt`):

```
fog of war: discard where the FoW texture at world XZ > 0.5 (unless _ShowInFow)
a    = smoothstep(_Min, _Max, min(noise1, noise2) * mask)          // erosion, not a flipbook
k    = a * _Multiply
rgb  = k * lerp(k, _Color.rgb, _Lerp) * vcol.rgb * vcol.a^2        // HDR, tinted by the particle colour
A    = k * lerp(k, _Color.a,  _Lerp) * vcol.a^2 * _Blend
then: V-coordinate ray fades, a world-height fade, FoW desaturation (0.3/0.59/0.11), a radial fade, a global fade
blend One, OneMinusSrcAlpha        // premultiplied: _Blend 0 = pure additive, 1 = premultiplied-over
```

The colour of an effect comes from the particle start colour and colour-over-lifetime, times an HDR `_Color`. The
shape comes from noise × mask erosion. Most vanilla fire and lightning is not a painted flipbook.

### 3.2 Other effect shaders (static-asset)

| Shader | Used for |
|---|---|
| `magic/Water_fire_stylized` | water sheets: `_Texture1` Water_02_vfx, `_mask` Water_03/04_vfx, `_TextureSample0` TileNoise_07_vfx |
| `magic/Fresnel` | mesh water drops and energy balls |
| `magic/Distortion` | heat haze and shock waves |
| `magic/StylizedLerp`, `magic/Stylized_lerp_upd` | slashes and ground cracks |
| `magic/test/Disappearance_0x` | dissolving sparks |
| `magic/Phoenix_rise_fire` | the phoenix body overlay |
| `magic/Opaque_fresnel` | opaque fresnel meshes |

### 3.3 Steady glow on the body is emission, not a light (static-asset; formula partly assumed)

`Hex/Lit` has an emission variant:

- keyword `HEX_EMISSION_MAP_ENABLED`, with `_EmissionTex` and an HDR `_EmissionColor`;
- `_EmissionMinPower`, `_EmissionBlinkSpeed` and `_EmissionBlinkPower`, which make a slow pulse;
- `_UvScroll` for flowing emission.

Examples:

- phoenix: `phoenix_emission`, MinPower 0.8, BlinkPower 0.2, BlinkSpeed 1;
- lava larva: `lava_larva_emissive`, `_EmissionColor` (2.52, 0.86, 0.37);
- titan: `titan_emissive`, MinPower 1, BlinkPower 0.2.

The exact emission math was **not** located in the bytecode. The lab assumes:

```
rgb = albedo·light + emissionTex·_EmissionColor·(MinPower + BlinkPower·sin(t·BlinkSpeed))
```

Treat this formula as an assumption.

### 3.4 Dynamic lights are short bursts (static-asset)

A `FlashLight` child PS uses the LightsModule over an inactive template `Light`. The template is always type 2
(Point) in the probes.

| Effect | Intensity | Range | Colour | Life (s) |
|---|---|---|---|---|
| phoenix hit and rise | 3 | 5 | (1, 0.46–0.54, 0.16) | 0.85–2 |
| lightning strike | 3 | 5 and 15 | (0.64, 0.78, 1) and white | 0.1–0.2 |

The lightning strike bursts at t = 0, 0.1 and 0.2 s. **No probed vanilla effect keeps a steady dynamic light on a
unit.** Steady light is emission (3.3).

### 3.5 Post-processing and bloom (static-asset)

The arena scenes (level20–32) carry Post Processing Stack v2 (`PostProcessLayer` / `PostProcessVolume`).
`sharedassets18.assets` holds the arena lighting profiles, `battle_post_process`, and
`SoBattlePostProcessOverride arena_post_process_presets`.

Battle Bloom settings:

- intensity 3.0 (override);
- threshold 1.0;
- soft knee ≈ 0.107;
- diffusion 3.65 or 5.0;
- a Vignette is also present.

**Only HDR values above 1 bloom.** That is why every vanilla effect colour is HDR and why our LDR `Sprites/Default`
flipbooks can never glow.

The game renders with the Built-in pipeline plus PPv2 (not proven beyond the scene components). The lab project
`oldenera_factions` is URP, so the lab applies the bloom in Python on HDR readbacks.

## 4. Texture style, scale, lifetimes, rates and palette (static-asset)

- **Textures:**
  - tileable painted noise: TileNoise_01/02/03/07/21/23_vfx, 256–512 px;
  - soft masks: glow_04/05/06/10/11/15_vfx, smoke_04/05_vfx, Gradient_03/18/25_vfx, SlideTexture_02;
  - a few sprite sheets: Fire_sheet_01_vfx (1024), lightning_sprites_vfx (1024), Lightning_sprite_01_vfx (128).
  - The style is soft, stylized and painterly, with bilinear filtering and mips. It is **not** pixel art and not
    point-filtered.
- **Scale:** particles run from 0.02 to 3 world units, with single flashes up to 15. The phoenix is 2.24 units tall
  in battle.
- **Lifetimes:** 0.1–0.25 s for lightning and flashes, 0.35–1.2 s for flames and smoke.
- **Emission:** bursts of 5–35 on hits, 35–100 per second on sustained flames, and 2–6 per second on idle wisps
  and embers.
- **Palette:**
  - fire: white-yellow core → orange (1, 0.46, 0.16) → red, then transparent;
  - lightning: HDR white with blue-cyan edges (0.64, 0.78, 1) and (0.165, 0.671, 1);
  - water: teal and blue with white foam.
- The hue lives in the particle colour. The material colour is an HDR intensity.

## 5. Concrete references (static-asset; values from `artifacts/vanilla_vfx_style/probe_*.json`)

### 5.1 Fire: phoenix (`units/nature/1prefabs/phoenix`)

**Wrist fire, `Phoenix_upg_ability_fire_01`** (four copies on the wing feathers):

- Three Stretched systems `Fire_01..03`: duration 2, sim speed 1.5, lifetime 0.5–0.6, start speed 1–2,
  size 0.3 × 0.3–0.35, rate curve × 35/s, cone 25°, radius 0.14.
- Material `PhoenixT7_fire_03_vfx`:
  - mask smoke_05_vfx, noise TileNoise_21_vfx at scale 0.5 × 0.3, `_ySpeed01` 0.5;
  - `_Color` (8, 1.75, 0), `_Blend` 1, `_Min` 0, `_Max` 0.8, `_CameraOffset` 0.3;
  - keywords `_ACTIVE_BLENDADD` and `_TWO_TEXTURES`.

**Hit, `Phoenix_upg_hit_fire_Root`:**

- `Fire_stretch_01..03`: Stretched, bursts 15+13 at t = 0 / 0.1, lifetime 0.5, PhoenixT7_smoke_06_vfx.
- `Fire_spark_01..03`: bursts of 15, lifetime 0.5, PhoenixT7_smoke_02_vfx.
- `FlashLight`: 0.85 s, Point, I 3, R 5, colour (1, 0.46, 0.16).
- An inactive ground-crack subtree.

**Obsidian dragon idle jaw** (`obsidiandragon_fire_idle_jaw`):

- sparks_stretch (Glow_07, 6/s);
- fire_idle (Mesh mode, Fire_03_vfx, 2/s, lifetime 1);
- eye flashes (Glow_04).

This is the idle-glow vocabulary: few particles, slow, bright.

### 5.2 Lightning: `magic/prefabs_vfx/magic_lightning_strike_hex`

`Impact` has these children:

| System | Material / shader | Settings |
|---|---|---|
| `Lightning_sparks` | Hksmilla_lightning_02_vfx, VfxUber, `_Color` 47.9 white | UV sheet Lightning_sprite_01_vfx, burst 35, lifetime 0.4 |
| `Lightning_sparks_small_01..03` | Lightning_03_vfx | lifetime 0.15–0.2, sub-emitters |
| `Lightning_trails` | Chain_lightning_trail_01_vfx | renderer None + TrailModule + Noise, burst 25, lifetime 0.25 |
| `Lightning_circle`, `Lightning_sphere` | Chain_lightning_01/02_vfx | Mesh mode, UV sheet |
| `Flash_01` | Glow_small_camera_2 | size 15, lifetime 0.1 |
| `Flash_light_01/02` | Point light | I 3, R 5 / 15, colour (0.64, 0.78, 1) / white, bursts at 0 / 0.1 / 0.2 |
| `Energy` | Obstacle_smoke_energy_02, `_Color` 24 | Stretched, bursts 25 + 15 |
| `Crack_wave_01/02` | — | mesh |
| `Distortion_01` | magic/Distortion | — |

The whole effect is over in about 0.4 s.

### 5.3 Water: naiad upgraded impact (`probe_naiad_upg_impact_unit.json`)

This prefab is a **target** impact, not the caster's attached water. It was
rejected for the `h3_water_elemental` Conflux lab draft after the Castle monk
target-on-caster negative. The current, still-unjudged donor is the installed
unit prefab `units/nature/1prefabs/aqualotl_upg`: its
`Root/Naiad_upg_idle_root/Water_01..03` and
`Root/Naiad_upg_hit_root/Water_01` subtree supply attached idle/self-hit
water. The lab's vanilla reference selects only those water systems; it does
not represent the whole native Aqualotl effect timeline.

| System | Shader / material | Settings |
|---|---|---|
| `Water_01..03` | Water_fire_stylized | Stretched, burst 5, lifetime 0.55 |
| `Wave_middle` | mesh wave + WaveDistortion | — |
| `Flash_floor` | glows | — |
| `Drops` | Fresnel mesh drops | — |
| `Slash_white/blue/detail` | StylizedLerp meshes | — |
| `Sparks` | Impending_fate_glow_dark | — |

## 6. How this differs from our current HoMM3 unit effects

| Aspect | Vanilla | Ours (unit-look pipeline) |
|---|---|---|
| Effect pixels | noise × mask erosion, HDR, bilinear | DEF-ripped flipbook quads (`defFlipbook`), `Sprites/Default`, point filter, LDR alpha |
| Glow | HDR > 1, bloomed by PPv2 (threshold 1) | never above 1, so it never blooms |
| Body glow | Hex/Lit emission map (+ blink) | prebaked into the LDR base colour, or a stepped `uvAtlas` body swap |
| Lights | short particle-Lights bursts (0.1–2 s) | `effectLight`: fire elemental steady floor 1.5 (range 6), storm fitted 0–7.4 (range 3) |
| Motion | hundreds of small particles, each with its own noise window | one sprite per key, stepped at 12 fps |
| Attachment | bone-parented, activated by Timeline signals | bone-anchored billboard, keyed to DEF frames |

## 7. Phase 2 lab (redesign preview)

Tools (lab only, not a delivery path):

- `tools/homm3_vfx/vanilla_ps_recipe.py` extracts vanilla ParticleSystem prefabs into JSON recipes plus their
  materials, textures and meshes (`artifacts/vanilla_vfx_style/recipes/`). Extract all specs in one call, because
  `materials.json` is rewritten on every run.
- `tools/homm3_vfx/vanilla_style_lab.py` stages everything into `oldenera_factions`, runs
  `unity/Homm3VanillaStyleVfxLab.cs` through `unitylock.py` after `memgate.py`, then composes the output. The C# lab
  rebuilds each recipe through the public ParticleSystem API, simulates at 60 Hz and renders ARGBHalf frames.
- `unity/Homm3VfxUberReplica.shader` is the VfxUber replica (3.1).
- `unity/Homm3VfxHexLitEmissionReplica.shader` is Hex/Lit with the replica point lights plus the assumed emission (3.3).
- The vanilla bodies are posed meshes and bones from `tools/homm3_style_compare/extract_native.py`.

Each unit gets three panels under the same battle camera and the same arena sun (the prebake `sunFrom['sand']`,
checked against the spritecam forward):

- **OLD** is what ships now: the uvAtlas body cell stepped per DEF key, the `defFlipbook` quads (Sprites/Default, point
  filter) and the `effectLight` point light.
- **NEW** is the vanilla-style redesign.
- **VANILLA** is a vanilla unit with vanilla effects, turned to face screen-right.

Composition goes over a flat ground colour. It then applies a PPv2-like bloom in Python (threshold 1, knee 0.107,
linear intensity 2^0.3-1, 3 pyramid levels), then sRGB with no tonemapping.

**What the lab leaves out.** Its tone differs from the game in these ways:

- VfxUber fog-of-war, height fade and radial fade;
- sub-emitters;
- `magic/Distortion` and `Stylized_lerp_upd` renderers;
- vignette and any colour grading;
- the exact emission formula (assumed).

## 8. Phase 2 results (Unity-editor lab render; not in game)

Media are in `artifacts/vanilla_vfx_style/lab/<unit>/`:

- `compare.mp4`: old | new | vanilla at 24 fps, every clip twice;
- `sheet_<clip>.png`: 8 columns × 3 rows;
- `hero.png`: the attack frame with the most HDR energy in NEW;
- `idle.png`;
- `lab_report.json` and `compose_stats.json`.

Raw half-float frames are in `renders/`, about 1 GB per unit.

### 8.1 Fire elemental (`h3_fire_elemental`) against the vanilla phoenix

The NEW panel has:

- **Body glow:** a Hex/Lit emission map made from its own base colour (bright, warm texels; about 34% coverage) at
  `_EmissionColor` (2.2, 1.1, 0.55), MinPower 0.8, Blink 0.3 at 1 Hz. It replaces the uvAtlas boil and the steady
  1.5-intensity floor light.
- **Idle flames:** the phoenix wing-fire system `Fire_01` (PhoenixT7_fire_03_vfx) looping at Head, Spine2 and both
  forearms, pointed up at 0.4–0.6× rate, plus phoenix `Fire_sparks` embers at about 8/s.
- **Punch:** `Fire_01` on the fist over the HoMM3 flipbook window (keys 3–11). At key 4 comes the phoenix melee hit
  (`Fire_stretch`, `Fire_spark` and `sparks`, plus its 0.85 s FlashLight burst) at 0.55 scale, aimed screen-right. The
  ground cracks are dropped.

Verdict (lab):

- NEW reads as the same family as the phoenix: HDR cores that bloom, soft painterly noise, a warm flash that lights
  the body for under a second.
- OLD shows pixel-art flame cut-outs floating beside a matte body and never goes above 1.
- The punch still reads large for a unit this size. The idle flames are thin next to the phoenix's wings.
- Both are tuning knobs, not structural problems.

### 8.2 Storm elemental (`h3_storm_elemental`; lab sid for `h3_air_elemental_upg`) against the vanilla sentinel

The storm has no fire-style vanilla unit to copy. Its references are the **sentinel** (a live neutral unit: emission
on body and wings, idle `Angel_idle_SmallWing*` energy wisps) and the `magic_lightning_strike_hex` spell, which is
rendered at the sentinel's feet.

The NEW panel has:

- **Body glow:** an emission mask from the brightest base-colour streaks (about 10% coverage), pale cyan (0.9, 1.5,
  2.4), Blink 0.5 at 1.5 Hz.
- **Idle:** the sentinel `Energy_01/02` and `Smoke` recoloured cyan at the hands and head, plus four
  `Lightning_sparks_small` crackles.
- **Attack and shoot:** the lightning strike's `Impact` subset at 0.45 scale, at LeftHand on key 2 and at Spine2 on
  keys 1 and 3. The subset is sparks, trails, sphere, flash, energy and the two `Flash_light` bursts. The sky bolt,
  cracks and distortion are left out.

Verdict (lab):

- The attack and shoot are clearly closer to vanilla than the old point-filtered bolt sprites and the fitted
  0–64-intensity light.
- The idle is weaker:
  - the emission lights the whole lower funnel mesh evenly, so it reads as a blue cylinder rather than a storm;
  - the sentinel wisps at 0.35 scale are nearly invisible at battle zoom.
- The storm needs:
  - a painted emission mask rather than a luminance threshold;
  - a looping swirl system on the funnel (a vanilla `Energy`-style stretched loop), which no probed vanilla prefab
    provides ready-made.

### 8.3 Rollout (approved 2026-09-26; first slice: fire and storm elementals)

The user approved the rollout for every unit and building that needs effects. The fire and storm elementals ship
first and are judged in game before the bulk rollout.

**Two layer types.** Specs live in `tools/homm3_vfx/vanilla_style/units/<unit>.json` (`homm3_vanilla_style_fx.v1`):

- `vanillaParticles` names a native prefab, one child subtree in it, and the systems to keep. It also sets bones,
  world scale, rate, recolour, orientation (`bone`, `emitUp` or `body` plus a yaw) and triggers. Triggers are
  `always`, or a DEF-key window on a clip. Each window is mapped through the idle retime to animator normalized time
  on the stock states that play that clip.
- `emissionMap` is a painted mask baked from the delivered GLB and its basecolor. It uses one of three rules:
  `warm_luminance`, `luminance` or `funnel_helix`. It also sets the HDR `_EmissionColor` and the vanilla blink.

**Compile.** `tools/homm3_vfx/vanilla_style_fx.py`:

- `sources` does a static UnityPy read of the installed prefabs into `vanilla_sources.json`. It records, per
  system, the facts the runtime cannot read back: scaling mode, loop, start colour, colour over lifetime and the
  material `_Color`.
- `compile` writes the `homm3_mesh_fx/catalog.json` rows (origin `vanilla_style:<unit>`), the emission PNGs under
  `homm3_mesh_fx/emission/` and `compiled/<unit>.json`.
- `check` re-proves all of that.

**Gates.**

- `tools/validate_homm3_vanilla_style_fx_contract.py` is wired into the OfflineUnlockMod build. It runs the check,
  refuses any active def_retarget selection that still ships a superseded flipbook, glow atlas or light, and pins
  the runtime source.
- `tools/validate_homm3_mesh_fx_catalog_contract.py` knows the `battle_emission` lane and the `vanillaStyle` block.
- `ship_def_retarget_slice.py` refuses superseded selections. A `vfxAuthority: vanilla_style` row builds with the
  basecolor albedo and no atlas, quads or lights. Deploy copies the pinned catalog and PNGs beside the DLL.
- Look `event` layers are superseded types too (2026-09-28, user-approved). `SUPERSEDED_TYPES` is the same tuple in
  `vanilla_style_fx.py`, `ship_def_retarget_slice.py` and `freeze_slice.py`, and freeze_slice refuses drift. A
  vanilla row must name every event layer with its native replacement and may never defer one:
  - `hideMesh` becomes the Core view's no-corpse death fade (`fadeOnDeathImmediately` + `fadeTime`, written by
    `apply_release_core_overlay.py` `VANILLA_DEATH_FADE_BY_UNIT_SID`), plus the spec's particle cover at the DEF key;
  - `missile` becomes the Core view's native projectile (`VANILLA_PROJECTILE_SPECS_BY_UNIT_SID`).
  - Whether the native fade reaches an owned skinned body is unproven. The live check is
    `artifacts/claude_takeover_20260927/vfx_events/LIVE_CHECK.md`.

**What the plugin does** (`Homm3MeshFx.cs`, source/static):

- It loads the native prefab through the Il2Cpp ResManager loader, from LateUpdate only.
- It clones only the named child subtree. The compiler refuses a subtree that carries scripts, an Animator or a
  director. Kept systems and their parents are activated; every other system is stopped and its renderer disabled.
- Windows start on the rising edge (clear, then play) and end with `StopEmitting`, so particles finish their life.
  During a cross-fade the incoming state is used.
- The emission hook runs after the owned-skinned Hex/Lit rebind, on every lane. It sets `_EmissionTex`,
  `_EmissionColor` and the blink floats, enables `HEX_EMISSION_MAP_ENABLED` and verifies it through `shaderKeywords`.
  It logs an error when the keyword or a property is missing.
- The steady lights are gone because the bundle plan has none. Light only flashes from particle Light modules.

**Stripped-interop equivalents.** The live `UnityEngine.ParticleSystemModule` interop has no
`MainModule.scalingMode` or `startColor` accessor, no colour-over-lifetime getter, and no emission `enabled`.
This was checked 2026-09-26 against Golden Era `BepInEx/interop`. So the lab's Hierarchy scaling and its recolour
are replaced:

- A Local-mode system gets the lossy scale that Hierarchy scaling would have given it, as its own localScale
  (`localScaleNodes`).
- A Shape-mode system has no equivalent and is refused. That is why the storm energy drops the sentinel
  `Energy_02`.
- Recolour writes a new colour-over-lifetime gradient with the recoloured start colour folded in. Any channel
  above 1 moves into the renderer material's `_Color`, because particle vertex colour is 8-bit.

**Punch aim.** The phoenix hit is authored along its root +X, and the delivered body faces +Z inside
`Orientation`. So the punch uses body yaw −90. The lab's −155 was screen-right under the sprite camera.

**Still to do (bulk, after the slice is judged):**

- the rest of the Conflux slice;
- Cove (oceanid, tidecaller);
- volfire;
- titan and beholder;
- the six effect-gap native objects (Part B of `docs/homm3_map_object_animation_audit.md`). The 24
  `vanilla_style_effect` map buildings are delivered as generated artifacts (2026-09-27,
  `docs/homm3_map_building_animation.md`);
- a roster-wide refusal of superseded flipbooks, glow textures and lights. The flipbook half is proposed as
  `tools/homm3_vfx/validate_no_def_flipbook.py` with a debt list that only shrinks, but it is not wired yet.

The roster-wide rollout was decided 2026-09-27: every HoMM3 effect is replaced. Its per-unit inventory, drafts lane,
castle batch and gate are tracked in `docs/homm3_vanilla_style_effects_rollout.md`.

Proof tiers:

| Claim | Tier |
|---|---|
| Vanilla recipes, materials and values | static-asset |
| Shader math | static-bytecode, with emission assumed |
| All images and verdicts above | Unity-editor lab render with replica shaders, which is not in game and not runtime-proven |
| Slice catalog, emission PNGs, runtime source and DLL | generated artifact + build target proven; the in-combat look is unproven until judged in game |
