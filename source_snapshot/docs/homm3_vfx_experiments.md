# HoMM3 VFX Experiments (Storm Elemental)

Goal: find what makes HoMM3's storm elemental effects look like HoMM3, and prototype
effects on our DEF-retargeted Meshy mesh that match them.

Proof state: **generated artifact only.** The measurements come from the original
DEFs. The comparisons are 2D composites over an offline Blender Workbench render of a
copy of `artifacts/homm3_def_retarget/h3_storm_elemental/*.blend`. Nothing here was
rendered in Unity, built into a bundle, installed or seen in game.

## Tools and outputs

- `tools/homm3_vfx/h3def.py` reads the LOD and DEF files and keeps palette indices. It
  was checked against the existing PNG extract of `CSTORM 02_00`: 2905 opaque pixels,
  and every RGB value matches exactly.
- `tools/homm3_vfx/characterise.py` writes contact sheets, palettes and `def_report.json` to
  `artifacts/homm3_vfx_experiments/storm_elemental/evidence/`.
- `tools/homm3_vfx/render_mesh_frames.py` is the Blender renderer. It renders the 65 master
  frames through the calibrated `SpriteCam` at 2x. It also renders a height mask and writes
  each bone's position projected into sprite pixels. It works on a copy of the .blend,
  never the build output.
- `tools/homm3_vfx/def_effect_layer.py` separates the lightning drawn into the DEF frames
  from the body. An effect pixel is bright (luma 175 or more) and sparse (12 or fewer
  opaque neighbours in a 5x5 window). Arcs that cross the body are lost.
- `tools/homm3_vfx/storm_experiments.py` and `storm_missile.py` build the comparisons:
  `compare_{idle,attack_front,shoot_front}.gif` / `_sheet.png`,
  `compare_missile.gif` / `_sheet.png`, and `anchors.json` (per-frame measurements).
  The GIFs run at 100 ms per frame, HoMM3's base "slow" battle speed; normal speed is 2x.

## What the original effects are (measured)

Source: `HoMM 3 Complete/Data/H3sprite.lod`. The DEF names and timings come from VCMI's
config and `CRANIM.TXT`.

| Asset | Frames | Size | Palette / blend |
|---|---|---|---|
| `CSTORM.DEF` (unit, type 0x42) | 21 groups. Idle has 10 frames = 6 unique frames played forward then back. The shoot and cast groups (14-19) are one shared 6-frame sequence. | Body 43x105 px in idle | 246 indices used. The standard slots are used: 0 transparent, 1 shadow at about 25%, 4 shadow at about 50%, 5 selection outline, 6 and 7 shadow under the selection. Everything else is opaque. |
| `CPRGTIX.DEF` (missile, shared with the Titan) | 9 frames, **one per trajectory angle** (90, 72, 45, 27, 0, -27, -45, -72, -90). It is not a time animation. | 73x72 px, about 70% of the unit's height | Opaque pale cyan (#DEFFFF to #C6FFFF) 1-px strands around a #FFFFFF core line. |
| `C03SPA0` + `C11SPA1` (Lightning Bolt spell) | 1 frame + 12 frames | 97x491 px + 110x108 px | White bolt with a lavender dithered halo. The impact flash is scattered lavender and white dots. |
| `C11SPE0` (Protection from Air, which the storm elemental casts) | 16 frames | 75x98 px | White and grey dithered swirl with yellow four-point star glints |

What gives these effects their HoMM3 look:

1. **The lightning is part of the unit sprite.** In the melee attack (group 12, frames 1-4),
   white 1-px branching arcs spread about 90 px forward from white-hot fists. They then
   break into scattered pale-yellow and white single pixels: frame 4 has 99 pieces with a
   mean size of 2 px. The shoot/cast frames 1-5 draw 1-px arcs rising 50-80 px above both
   raised hands. None of this is a separate effect.
2. **Hard pixels, no soft glow and no additive blending.** Arc pixels use palette slots
   10, 13 and 16 (#FFFFFF, #F7FAF2, #F6F7E7). They are opaque and aliased, one pixel wide at
   native scale. Dithering is the only kind of translucency in any of these DEFs. Every
   brightening effect is painted in.
3. **The storm elemental's own light is yellow-cream, not blue.** The body glow averages
   about (215, 215, 150), with R equal to G. Idle pulses it into the vortex twice per
   cycle (6.6% of body pixels at frames 2 and 8, centred 36% up the body). During
   attack and shoot the glow covers 10-21% of the body, mostly on the hands. Only the
   missile is cyan.
4. **Timing.** Per VCMI's reconstruction, creature frames play at 10 fps at base speed
   (x speed factor). Storm elemental `attackAnimationTime` is 1.00, and idle is a fixed
   10 fps. The missile moves at 1250 px/s (x speed factor), so crossing 5 hexes takes about
   0.2 s. `attackClimaxFrame` is 4, and the `CRANIM` missile offsets are upper (50,-100),
   middle (80,-80), lower (45,-40). VCMI applies no palette cycling to battle creatures;
   `shiftPalette` is only used for adventure-map objects.

## Approaches compared (see the sheets)

| Panel | What it is | Result against the DEF |
|---|---|---|
| **A** DEF flipbook | The DEF's own arc pixels for each frame, cut out by the effect mask and moved so the DEF's hot fists land on the mesh's projected hand bones | Closest match in shape, palette, pixel weight and decay, by construction. It needs a per-frame shift of 10-40 px (see `anchors.json`), because the mesh's hands are not where the DEF's are. In the shoot clip the mesh never raises its arms, so the arcs grow out of the head area. |
| **B** Procedural, HoMM3 rules | 1-px aliased white dendrites grown from the mesh hands. Pixel count, extent and the decay into scattered sparks are measured per DEF frame, and the shape is redrawn every frame. | Reads as HoMM3 because of the palette and hard pixels. The branch structure is sparser and less radial than the hand-drawn arcs, and the procedural missile is noticeably thinner than `CPRGTIX`. |
| **M** Modern soft additive | The same paths with a cyan additive halo and an anti-aliased core, the typical Unity look (and the approach of the rejected Beholder preview) | Clearly not HoMM3. The colour is wrong (the unit's lightning is white and yellow, not cyan), and the soft light hides the 1-px filament character. |
| **A+C** Flipbook + body glow | A, plus the body lerped *opaquely* toward the measured cream, driven by the measured glow share per frame (idle vortex band and hands during attacks). This stands in for a per-vertex emissive colour animated in the GLB. | The idle pulse reads correctly at frames 2 and 8. This is 2D emulation only; a real emissive curve in the GLB and its shader response in game are unproven. |

The largest remaining gap is not an effect but the mesh body. The DEF body is mid-grey,
striated, see-through vortex rings lit from inside. The Meshy mesh renders as a dark,
solid cylinder, and no overlay closes that gap.

## Recommendation

1. For the unit's own arcs, use **A (the DEF's frames as a flipbook)**. Play them on a
   camera-facing quad parented to the hand bones. Use alpha-tested or plain alpha blending,
   **not additive**, point filtering and nearest-upscaled texels. Keep the DEF frame
   timing. It is the most authentic option and needs no art. B is the fallback for clips
   the DEF has no arcs for, or when the mesh's hands move so far from the DEF's that a
   cut-out arc looks detached. B must keep the same rules: 1-px opaque white, a yellow
   spark decay, and a new shape every frame.
2. For the missile, use `CPRGTIX` as HoMM3 does: pick one frame by angle when the missile
   launches, mirror it for leftward shots, and move it; do not animate it over time.
3. For the body glow, use C: an animated cream emissive or vertex colour on the vortex
   and hands, painted opaque rather than added as light.
4. Delivery shape, per the existing repo paths:
   - Unit visuals reach the game through the custom unit bundle (`owned_skinned.prefab`).
     Child quads in that prefab would travel with it.
   - HoMM3 custom projectile prefabs (`Homm3ProjectileConfigHook`, `homm3ReleaseProjectile`)
     have **never been visually proven** and are disabled. The storm elemental
     (`h3_air_elemental_upg`) currently uses the native `effects/rays/WorldWatcher_ray_vfx`.
   - The existing runtime already drives frame-swapped `Sprites/Default` quads
     (`Homm3FactoryCityWorldAnimDriver`, `Homm3CoveCannonVisuals`), so there is a runtime
     flipbook precedent.

## Unproven / open

- No Unity or in-game render has been made. Two things are unknown:
  - whether `Homm3ImportReleaseBattleVisualHook` restamps a child effect quad's material to
    `Hex/Lit`;
  - how 1-px texels look at OE's battle camera distance and resolution.
- The mesh's hand positions differ from the DEF's by 10-40 px (10-30% of unit height), and
  its shoot pose does not raise the arms. The authenticity of any hand-anchored effect is
  limited by the retarget.
- Replacing the native `WorldWatcher` ray with `CPRGTIX` depends on the unproven custom
  projectile path.
- Spell effects (`C03SPA0`, `C11SPA1`, `C11SPE0`) are characterised but were not
  prototyped. Delivering them depends on how OE plays spell VFX.

## Where the storm elemental work stopped

The work was paused on 2026-09-25, after the 2D comparisons above, because the
articulation (pose-fitting) work is still in progress. The Titan became the test case
(section below). No storm elemental body or material variant, and no Unity run, was
made. If this is resumed, start with the body. The DEF body is mid-grey rings you can
see through, lit from inside in cream. The mesh body is a dark solid cylinder. The
likely fix is band geometry or an alpha-banded texture plus the cream emissive pulse,
done before any arc work.

## Titan (`h3_giant_upg`, CGTITA.DEF)

Proof level: Unity-editor camera render in the preview harness (`tools/homm3_import/preview_unit_vfx.py`,
`gameRuntimeUsed=false`). Nothing here is installed, bundled or seen in game.

### What the DEF holds

- The Titan always holds a lightning-bolt sword: a white core with pale sky-blue edges (#B2DBF5, #C2EFFF,
  #9ACBFF). For this unit pale blue is authentic; a soft cyan bloom is not.
- Idle (group 2, 8 frames): the bolt is static, with no crackle.
- Melee (group 12, 7 frames): frames 1-2 raise the bolt with a flare. Frames 3-4 are a big crackling swing
  arc (up to about 1500 lightning pixels), and frames 5-6 leave sparks.
- Shoot (group 15, 7 frames): a second bolt appears overhead in the left hand at frames 2-3 and is thrown
  with the left arm extended at frame 4. The missile is `CPRGTIX.DEF`, shared with the storm elemental:
  9 frames chosen by angle, 73x72 px. CRANIM says `attackClimaxFrame` 6.
- Defence (group 4) flares the bolt upward at frames 3-5. There are no separate cast groups.
- Evidence (contact sheets, palettes, `def_report.json`): `artifacts/homm3_vfx_experiments/titan/evidence/`.

### What was built

- `tools/homm3_vfx/titan_vfx_textures.py` cuts point-filtered flipbooks from the DEF's lightning pixels.
  Each cell is centred on the anchor bone's head, projected through the calibrated def_retarget SpriteCam.
  - **A (literal):** DEF pixels, 1 texel per DEF px.
  - **B (readable):** the same pixels skeletonised and redrawn at 2 texels per DEF px, with a white core
    and a 1-texel rim. Specks under 4 px are dropped. Total width is about 3 DEF px.
  - **Missile:** CPRGTIX frame 4 (level shot), launched at DEF frame 6. Speed is VCMI's 1250 px/s scaled to
    the 12 fps clip.
- `tools/homm3_vfx/build_vfx_lab.py` + `unity/Homm3VfxLabBuild.cs` run one Unity batch process. It builds
  `oldenera_factions/Assets/Homm3VfxLab/h3_giant_upg/` from a copy of the def_retarget GLB:
  - a preview prefab and the clips, rebuilt as generic clips through editor curves;
  - one-particle `ParticleSystem` flipbook prefabs using `Sprites/Default`, a point filter, no mips, a
    view-aligned billboard, and a texture-sheet grid.
  - The harness parents the effect to `RightHand` (attack) or `LeftHand` (shoot).
- `tools/homm3_vfx/titan_unity_compare.py` writes the harness specs and builds the comparisons. The DEF,
  the mesh, mesh+A and mesh+B are shown at one scale. Unity frames are box-filtered so the mesh height
  matches the SpriteCam render.
  - Outputs: `compare_unity_{attack,shoot}.gif` and `_sheet.png` at 2 screen px per DEF px, and
    `_1x` versions at 1 screen px per DEF px.
  - Runs, specs and textures are in `titan/unity_runs/`.

### Results

- **The flipbook tracks the animated mesh.** The strike arc sits on the swinging bolt at DEF frames 3-4,
  and the overhead bolt sits above the left hand while shooting. The DEF's own layout therefore survives
  being attached to a bone. The anchor is the bone head, because Unity bone transforms sit at the head.
- **A is the more authentic result.** At 1x it still reads as HoMM3 crackle: 1-px white filaments and a
  pale-blue flare. Its weakness is density rather than readability. Once the arc overlaps the dark mesh,
  the sparse speckle thins out.
- **B reads bolder but stops looking like HoMM3.** At both scales it reads as white rope or coral, and the
  diffuse spark field that makes frames 3-4 look electric is gone. It is useful only if OE's camera turns
  out to be much farther away than assumed.
- **Timing:** the GLB keys DEF frame i at (i+1)/12 s. The harness event is set at 1/12 s so the particle
  frames line up with the mesh keys. With the event at 0, the effect runs one DEF frame early.
- **Mismatch:** A's DEF pixels include the held bolt. Where the mesh pose differs from the DEF pose (for
  example melee frame 1), the DEF bolt and the mesh's rigid bolt prop do not coincide and read as a double
  bolt. Shoot A/B also carry the right-hand bolt pixels, anchored to the left hand.
- **The missile appears for about one render frame and then leaves the frame.** Its speed is correct: the
  HoMM3 speed is about 25 units/s at this scale.

### Hex/Lit restamp risk (static read of the plugin, not runtime-proven)

- `Homm3ImportVisuals.EnsureSkinnedBattleRuntimeCompatibility` restamps only `SkinnedMeshRenderer`
  materials, to a cloned native Hex/Lit. It copies the base, normal and metallicGloss textures.
  - Consequence 1: an emission map authored on the skinned body material would be dropped.
  - Consequence 2: a glowing bolt done as mesh emission would not survive.
- `ParticleSystemRenderer` children are not restamped.
- `Homm3BattleDonorVisualSuppressor` skips the kept HoMM3 replacement root, so particle children under
  that root should survive. Neither point is runtime-proven.

### Harness findings (not fixed here; the harness is shared)

- **Skinned meshes are not re-skinned between the several renders the harness makes in one editor frame.**
  Every frame then shows the first pose, although `BakeMesh` reports deformation. The lab prefab works
  around this with `Homm3VfxLabSkinRefresh`, which sets `forceMatrixRecalculationPerRender`. The harness
  itself should set this before trusting any skinned render.
- **`requireSkinnedMeshDeformation: true` crashes `build_mesh_motion`.** It raises
  `KeyError: 'meshDeformedVerticesFromPrevious'`: the report field is now named
  `meshShapeChangedVerticesFromPrevious`.
- **Comparison labels are hardcoded to "Beholder".**
- **The `particlePrefab` path adds no light.** The glTF body therefore renders dark, which is not
  representative of OE battle lighting.
- **Camera direction:** Blender (x,y,z) maps to Unity (-x,z,-y) under glTFast. The SpriteCam direction in
  Unity is (0.4158, 0.1739, 0.8927).

### Recommendation

1. Deliver A: point-filtered DEF-pixel flipbooks as `ParticleSystem` children under the unit's HoMM3
   replacement root, using `Sprites/Default`.
2. Before delivery, mask the held-bolt pixels out of A, keeping only the crackle beyond the prop. For
   shoot, keep only the thrown bolt near the left hand.
3. Do not put glow in the skinned material's emission, because the restamp drops it.
4. Treat B as a fallback, used only if in-game scale proves A unreadable.

### Open questions

- **On-screen scale in OE.** The 1x sheet assumes 1 DEF px = 1 screen px; this is not measured.
- **`Sprites/Default` in OE's pipeline.** It renders in the URP lab project, but it has not been checked
  in OE's runtime, including whether the shader is in the bundle.
- **Activation.** Clip `m_IsActive` curves on the effect child vs a runtime hook is undecided, and the
  native Animator/override controller path has not been exercised.
- **Missile delivery.** The custom-projectile path (`Homm3ProjectileConfigHook`) has never been visually
  proven. The overlay still maps `h3_giant_upg` to `WorldWatcher_ray_vfx`.
- **Not done:** idle and defence flares, and angle selection for non-level shots.
- **Articulation gaps.** Melee frame 1 and the shoot throw differ from the DEF pose, and they limit how
  well any DEF-derived flipbook can sit.

### Prebaked albedo and VFX lighting (v6 / v6m + point light)

This builds on the Behemoth prebake work: [`docs/homm3_prebaked_lighting.md`](homm3_prebaked_lighting.md) and
`tools/homm3_prebake/`. Those tools are imported and not modified. All the work uses copies
(`artifacts/homm3_vfx_experiments/titan/work/titan_copy.blend` and the lab GLB copy). Proof levels are
given for each item.

**Why the gold DEF armour looked dark grey-blue in the earlier Unity sheets.** The cause is the lab
lighting and material. It is not the texture, the bake or the restamp.
- The GLB material is glTFast URP PBR, with `Baked_MetallicRoughness` B (metallic, median 222/255) and a
  normal map.
- A metallic gold with no environment and no lights renders almost black, and the blue lab ambient then
  tints it.
- Hex/Lit ignores metallic. Under the game formula the raw `Baked_BaseColor` reads as a flat, dim
  gold-brown (raw mean L 36 against the DEF's 45 on idle).
- Evidence: `artifacts/homm3_prebaked_lighting/titan/sheets/`. Proof: numpy relight of Blender passes.

**Part 1, the prebake** (`tools/homm3_vfx/titan_prebake.py`, outputs in `artifacts/homm3_prebaked_lighting/titan/`)
- **Stock `v6_sprite_match`** (via `prebake_lab`): the global grade hits its exposure bound (12). The
  armour bleaches to pale sand, and the idle L-histogram distance to the DEF is 15.8.
- **`v6m`, a per-material grade.** Soft class weights (gold, grey skin, red crest, blue bolt) from the
  texture's chroma. Each class has its own shading power, and gold gets a top sheen (`goldTopSheen` 1.5,
  gold power 2.0). Each class is graded separately by Nelder-Mead against that class's DEF L percentiles.
  - Idle: mean L 47.9 against the DEF's 45.4.
  - L-histogram distance: **4.8**, against raw 13.9 and v6 15.8.
  - Gold L p10/50/90: 9.7/46.1/83.8, against the DEF's 17.9/44.2/85.6.
  - Crest and skin medians are within 2 L.
  - The texture is `textures/v6m_material_grade_basecolor.png`.
- **Four facings** (`sheets/titan_battle_facings_v6m.png`, plus the Unity lab render
  `light_lab/titan_idle_facings_unity.png`): v6m holds its gold, grey skin and red crest from all four sides.
- **Remaining gap.** The DEF gold is a polished metal with near-white glints and near-black creases.
  Diffuse-only Hex/Lit cannot move highlights with the view, so v6m reads as satin gold, not chrome.
- **Facing labels are swapped for this unit.** `render_passes.py` assumes the model faces +Y, but the Titan
  faces -Y, so `faces_camera` shows its back. This is reported to the prebake owner and not changed here.

**Can Hex/Lit be lit by the VFX?** Yes, per the static read. This is unproven at runtime.
- The Lit-pass bytecode (`artifacts/homm3_prebaked_lighting/hex_lit_ps/ps_o0_t4_n150.txt`) has URP's
  per-object additional-light loop:
  - It is gated by `cb2[9].x`, with up to 8 lights (`cb1[10].y`) and indices in `cb1[11..12]`.
  - Position is `cb2[40+i]` (w = 1/range^2), colour is `cb2[10+i]`, and spot data is `cb2[70+i]`.
  - Attenuation is `saturate(1-(d^2/r^2)^2)^2 / d^2`, multiplied by `saturate(N.L)`. Point lights cast
    no shadow.
- **Native precedent** (`resources.assets`, UnityPy read):
  - 1059 native `ParticleSystem`s have the **Lights module** enabled. They are in unit prefabs such as
    druid_upg, black_dragon, minos, succubus, lightweaver and angel.
  - Their settings are ratio 1, maxLights 1, range 2-9 and intensity 1-5, and each points at an inactive
    template "FlashLight" Point light.
  - There are 1062 Light components in total.
  - No AnimationClip animates a Light.
  - The arena scenes have one directional light each.
  - So OE's own units light themselves from VFX through particle-driven point lights.
- What is not proven: whether the battle renderer actually fills the additional-light data for units. The
  pipeline asset's additional-lights mode and per-object limit have not been checked in game.

**DEF glow target.** The measurement is the body's mean L with lightning pixels excluded, rise over frame 0.
- Attack: 0 / 3.8 / 7.8 / **11.7** / 9.0 / 8.3 / 5.2.
- Shoot: 0 / 2.1 / 1.6 / 3.3 / **6.3** / 4.4 / 0.
- Idle is flat (about 41.9).
- b* rises from 19.1 to 22.6: the glow is pale warm white on the hands and the sword side, not blue.

**The Unity light lab** (`tools/homm3_vfx/titan_light_lab.py render|compose`, `unity/Homm3VfxLightLab.cs`,
`unity/Homm3VfxHexLitReplicaPoint.shader`, `unity/Homm3VfxDepthOnly.shader`)
- **Setup.**
  - One Unity batch run, gated by memgate.
  - The camera is registered to the def_retarget SpriteCam. Anchor pixels match `mesh2x/bones.json` to
    0.1 DEF px.
  - Each term is a separate pass into half-float buffers: base per texture, point light only, and FX over
    black and white with the body depth-only.
  - The light is one point light, sRGB (1, 0.96, 0.86), range 3 u. It sits at the anchor hand, moves half
    way toward the DEF bolt's centroid, and is 0.45 u toward the camera.
  - Its intensity is fitted per frame so that the mesh body's mean-L rise over its own unlit render equals
    the DEF curve. Pose shading is not counted as glow.
- **Fitted intensities.**
  - Attack: 0 / 0.39 / 1.79 / 1.34 / 0.81 / 0.48 / 0.25.
  - Shoot: 0 / 0.06 / 0.03 / 0.18 / 0.40 / 0.19 / 0.
  - Both are stepped, 12 fps curves peaking on the flare and the strike.
  - Metrics: `light_lab/light_lab_metrics.json`.
- **Sheets.**
  - `light_lab/titan_{attack,shoot}_prebake_vfx_light_sheet.png` and `.gif`: DEF | mesh raw | mesh v6 |
    mesh v6m | v6m + VFX | v6m + VFX + light.
  - `light_lab/titan_idle_facings_unity.png`: raw, v6 and v6m from four facings.
  - Proof level: **Unity-editor render of a replica shader. Not in game.**
- **Result.** The point light visibly warms the raised arm, chest and helmet at the flare (attack f2) and
  across the torso at the strike (f3-f4), and it is gone by f6.
  - The HoMM3 read comes from the hard, stepped timing, not from a soft halo. There is no bloom.
  - The falloff itself is smooth, because that is what Hex/Lit's attenuation does.

**Alternatives compared** (assessment; only the point light was rendered)
- (a) **A baked "lit by bolt" albedo variant.** It must be swapped per frame and cannot follow the bolt as
  the pose changes. It doubles texture memory, and the restamp copies only the base texture of the clone.
  Worse than the point light.
- (b) **Vertex-colour or texture swaps per frame.** Whether Hex/Lit's Lit pass reads vertex colour was not
  checked, and the restamp would not carry it. The option is not assessed further. A texture swap is (a) again, with more assets.
- (c) **A camera-facing glow quad** (additive or alpha). It works in any pipeline, but it brightens the
  background and the silhouette edge as well as the body. In the DEF only the body brightens, so a quad
  reads as bloom. It is useful only as a fallback if point lights prove disabled in game.
- (d) **A runtime property carried by the restamp** (write-up only; no plugin code was changed).
  `EnsureSkinnedBattleRuntimeCompatibility` could copy a per-renderer `MaterialPropertyBlock` tint
  (a base-colour multiplier) driven by the clip. That is a global body brighten, not a localised one, so it
  is a poorer match than a point light, and it needs plugin work.

**Recommendation**
1. Ship the v6m-style per-material grade as the Titan base colour. It is the closest diffuse match.
2. Light the Titan from the VFX the native way: enable the **Lights module on the lightning flipbook
   `ParticleSystem`**, pointing at a template Point light.
   - Light: pale warm (1, 0.96, 0.86), range about 3 u.
   - Intensity: a stepped curve per DEF frame (values above), placed at the bolt near the hand.
3. Do not use emission or a glow quad.

**Open questions**
- Does OE's battle URP asset render per-object additional lights for unit Hex/Lit materials? Check this
  in game with one test Light next to a unit.
- Does the ParticleSystem Lights module survive our bundle and HoMM3-root path, including the template
  Light reference?
- Should the held bolt glow constantly on idle? The DEF idle is flat, so this is left off.
- The mesh's held-bolt prop (white after v6m) doubles the A flipbook's held-bolt pixels where the poses
  differ. The mask is still to do.

## Oceanid flowing water (`hota_cove_oceanid`, COCEANID.DEF)

Goal: move the oceanid's water texture cheaply but convincingly, so that it matches the motion the sprite
actually draws. Everything here is lab work on copies: build outputs, the unit config and the source mesh
are untouched, and no plugin or runtime code changed.

Proof tiers:
- DEF measurements: generated-artifact from the shipped sprite.
- Hex/Lit and restamp facts: static read (installed bytecode, plugin source).
- Variants: **Unity-editor-rendered** through a lab replica of Hex/Lit. Nothing in this section is in-game proven.

### Tools and outputs
- `tools/homm3_vfx/oceanid_water_motion.py`: measures the DEF's water motion.
  - Segments each frame into torso, hair, column, foam and spray.
  - Per frame pair: rigid silhouette shift, per-region change, column-band shifts and spray velocity.
  - Loops: multi-lag texture-velocity search, lag dissimilarity, and highlight survival against chance.
  - Outputs: `artifacts/homm3_vfx_experiments/oceanid/evidence/water_motion.json`,
    `water_motion_summary.txt`, and `flow_g<group>.png` contact sheets with change heat and flow arrows.
- `tools/homm3_vfx/oceanid_water_lab.py` writes to `work/`:
  - a GLB copy with a `COLOR_0` mask: r = water (vertices whose dominant bone is `Tail_*`, 11484 of 17704);
    g = foam (the flared base, 4114);
  - the boil atlas: 8 cells of 1024 px in a 2x4 grid with 32 px gutters, 2176x4352;
  - `boil_atlas_defpal.png` (B2), the sparkle atlas, and a tileable scroll tile;
  - `cells.json`: the per-cell `_MainTex_ST` and the per-clip cell sequence.
- `tools/homm3_vfx/oceanid_unity_lab.py` + `unity/Homm3OceanidWaterLab.cs` + `unity/Homm3OceanidHexLitLab.shader`:
  - one gated batch Unity run (memgate; refuses to start if Unity is already running);
  - assets in `oldenera_factions/Assets/Homm3VfxLab/hota_cove_oceanid_water/`;
  - renders every variant and a vertex-colour mask pass through the calibrated SpriteCam at DEF frame
    times ((i+1)/12 s), at 2x, into `renders/`, with `renders/lab_report.json`.
- `tools/homm3_vfx/oceanid_water_compare.py`: the same metric code runs on the DEF and on every variant
  (renders box-reduced to DEF pixels). Writes to `compare/`:
  - `compare_summary.txt` and `compare_metrics.json`;
  - `sheet_<clip>.png`, `<clip>.gif` and `<clip>.mp4`: DEF | current | A | B | B2 | C | D, same scale, 12 fps;
  - `water_zoom_idle.png`.

### What the DEF draws (measured, `water_motion_summary.txt`)
- **Idle: the water does not flow. It boils in place.**
  - 83-88% of column and foam pixels change every frame, against 30-60% for the torso.
  - The texture velocity search finds nothing: best/zero is 0.995 in the column and 1.0 in the foam.
  - The lag dissimilarity curve is flat (3060, 2994, 2842, 2904, ...), so every frame is an independent redraw.
  - The helical bands (period about 5 px, tilted 15-30°) stay put and jitter ±1-2 px; there is no net travel.
  - Highlights survive to the next frame only at chance level (column 0.45 against chance 0.39).
  - The silhouette edge jitters about 1 px.
  - Only the hair has a smooth periodic sway.
- **Mouseover:** a ping-pong gesture.
  - The water re-rolls less: highlights persist 0.78 against chance 0.45.
  - Frames 4-6 are identical holds, and frame 10 equals frame 0.
- **Move (g20; g21 is g20 exactly reversed):** the body sinks into a puddle.
  - The top drops from y 186 to 256 at 5-20 px/frame over frames 2-7.
  - The puddle then ripples and shrinks.
- **Hitted:** a spray burst to the left at about 5 px/frame in frames 2-3 (16-35 specks).
- **Defence:** a water dome rises. Frames 3-5 are a frozen hold, then it reverses.
- **Attack:** a water blob is thrown right at 15-40 px/frame in frames 4-6 (363-454 px).
- **Death:** spray up and to the left in frames 1-3, then a collapse into a puddle.

So the target is **a stepped 12 fps re-roll of fine speckle and highlights on fixed bands**:
- confined to the water;
- holding exactly where the DEF holds;
- plus discrete spray, blob and puddle events that belong to separate sprites.

A continuous scroll or a travelling wave is the wrong kind of motion.

### What the runtime keeps (static read)
- **Hex/Lit** (installed `resources.assets`, 31 properties; 31 unique vertex programs disassembled into
  `evidence/hex_lit_vs/`):
  - UV: `uv = (uv0 + _UvScroll.xy * _Time.y) * _MainTex_ST.xy + _MainTex_ST.zw` in every vertex program.
    `_EmissionTex` scrolls the same way.
  - `HEX_VERTEX_DISPLACEMENT_FLAG`: `pos += _FlagPower.xyz * sin(dot(pos, _FlagDirection.xyz) + _Time.y * _FlagSpeed) * COLOR.r`.
  - No normal map and no metallic map are declared.
  - Stock precedent in `resources.assets`:
    - 12 Hex/Lit materials use a non-zero `_UvScroll`. One is `lava_larva_belly_mt`, on a separate
      "belly_inner" `SkinnedMeshRenderer` of a battle unit.
    - Others are rivers and waterfalls (transparent).
    - 106 use the flag displacement.
- **Plugin restamp** (`Homm3ImportVisuals.EnsureSkinnedBattleRuntimeCompatibility`, which calls
  `SanitizeMapMaterialForOpaqueMesh`):
  - Every `SkinnedMeshRenderer` material becomes a fresh Hex/Lit clone.
  - `_MainTex_ST` is forced to (1,1,0,0).
  - Flag displacement is zeroed and its keyword disabled; emission is black and its keyword disabled.
  - The material is forced opaque (queue 2450).
  - `_UvScroll` is not carried over from the imported material.
  - **It does not touch `MaterialPropertyBlock`s.**
- **Bundle builder** (`Homm3OwnedSkinnedLabBuild.RebaseClipPaths`, line ~672) keeps only local rotation
  curves (or all local transform curves for mocap). It drops material-property and blend-shape curves.
- **Editor:** glTFast keeps `COLOR_0` (all 11484 water vertices read back from `mesh.colors`).
- **Editor, B and B2:** the Animator's `material._MainTex_ST.*` curves reach the renderer as an MPB and
  **survive a restamp-style material swap** made after the Animator bound: 78/78 frames match per variant
  in `lab_report.json`, although the new material's own ST is (1,1,0,0).

### Candidates and results (Unity-editor-rendered, `compare_summary.txt`)
Idle loop, contrast-normalised change (norm), highlight survival against chance, and lag flatness:

| | water change (norm) | torso change | highlight survival / chance | lag flatness | holds with the DEF |
|---|---|---|---|---|---|
| DEF | 0.63 | 0.18 | 0.21 / 0.26 (re-rolls) | 0.88 | yes |
| current mesh | 0.00 | 0.02 | n/a | 0.24 | n/a |
| A native `_UvScroll`, water split to its own renderer, cylindrical UV | 0.57 | 0.02 | **0.78 / 0.27** (carried, travels) | 0.95 | **no**, it scrolls through holds |
| **B stepped boil atlas** (`_MainTex_ST` curves) | 0.43 | 0.05 | 0.39 / 0.32 | 0.97 | **yes** (same cell on held frames) |
| B2 = B with the DEF water palette | 0.37 | 0.04 | 0.34 / 0.33 | 0.96 | yes |
| C translucent sparkle shell (+0.012 u), stepped | 0.21 | 0.02 | 0.45 / 0.33 | 0.97 | yes |
| D Hex/Lit flag displacement masked by `COLOR.r` | 0.13 | 0.02 | 0.62 / 0.35 | 0.43 | no |

How the metrics were measured:
- Highlights for the variants are ranked after dividing by the current-mesh frame, which removes the
  lighting and the static albedo.
- The multi-lag velocity search is inconclusive on the renders: it reports 0 for B/B2/C/D, and 0.5 px/frame
  for A and for the DEF's eroded column. Highlight survival is the metric that separates travel from re-roll.

Notes on the table:
- **B/B2 is the only candidate with the DEF's kind of motion** (see `compare/Unit_Idle.mp4` and
  `water_zoom_idle.png`):
  - a stepped re-roll with highlights near chance;
  - no velocity and a flat lag curve;
  - water only;
  - it holds exactly on Mouseover frames 4-6 and Defence frames 3-5, because `cells.json` reuses a cell
    when the DEF repeats a frame.
- Its amplitude is lower than the DEF's (0.43 against 0.63). This is the tone gap below, not the motion.
- A has matching activity but the wrong motion: highlights travel down the column and do not re-roll, and
  it cannot hold. It would need the plugin to carry `_UvScroll` and a mesh split.
- C is too faint to read at battle scale. The restamp would also make the shell opaque.
- D does not read at 1 DEF px of amplitude, is a travelling wave, and is sanitised off by the restamp.
- In the idle loop the current mesh moves almost nothing (torso 0.02 against the DEF's 0.18). The hair and
  body sway belong to the retarget, not to this pass.

Wider gaps (all variants):
- **Tone.** The DEF water is unlit, high-contrast art with white foam. Through the Hex/Lit formula
  (albedo × (ambient + sun·N·L)) the mesh water reads dark blue. B2 maps the water onto the DEF's own palette
  and still lands dark, so the gap is lighting and prebake (see "Prebaked albedo and VFX lighting" above).
- **Discrete events are not texture motion.** None of the mesh variants has:
  - the attack's thrown blob (`compare/Unit_AttackFront.mp4`);
  - the hit and death spray;
  - the move and death puddle. The mesh shrinks away instead of sinking, so silhouette IoU is 0.23-0.32 on
    Move and Death.
  These need particle or flipbook accents in the Titan-proven `Sprites/Default` pattern:
  - hit spray: left, about 5 px/frame, frames 2-3;
  - attack blob: right, 15-40 px/frame, frames 4-6;
  - death spray, and a puddle-ripple flipbook quad for Move and Death.
  They were not built in this pass.

### Cost
- **B / B2:**
  - 0 extra draw calls, 0 extra vertices.
  - The water triangles (5925 of 9383) and the texture change; the body texels are unchanged.
  - Texture: one 2176x4352 atlas replaces the 4096² base colour, about 6.3 MB BC1 with mips against about
    10.7 MB.
  - The atlas lowers the body texel density to 1024 per cell. That is ample at battle scale (unit about 80
    px tall); unverified at close zoom.
  - Animation: four constant float curves per clip.
  - Caveat: an MPB takes the renderer out of SRP-batcher batching. One unit is one draw call either way.
- **A:**
  - +1 draw call; the water subset is its own skinned renderer.
  - +256² tile (about 43 KB).
  - Needs a restamp extension so `_UvScroll` survives, and a mesh split.
- **C:** +1 draw call, +11.5k skinned vertices, and an RGBA atlas (about 12 MB BC3). Needs a restamp
  extension for transparency.
- **D:** free at runtime, but needs a restamp extension to keep the flag keyword and parameters. Motion
  mismatch.

### Recommendation
Ship **B**:
- the stepped boil atlas driven by per-clip `material._MainTex_ST` curves on the unit's own
  `SkinnedMeshRenderer`;
- cells stepped at the DEF's 12 fps from `cells.json`, repeating a cell wherever the DEF holds a frame;
- keep the Meshy water tint for now. B2's palette mapping only pays off once the lighting and prebake tone
  gap is closed.

Add the discrete water events as `Sprites/Default` flipbook accents later.

It needs **no plugin change**, because the restamp leaves MPBs alone. The exact delivery work:
1. **Bundle builder**, `tools/homm3_import/unity_editor/Homm3OwnedSkinnedLabBuild.cs`:
   - After the transform loop in `RebaseClipPaths`, or in the def_retarget delivery builder once it exists,
     add four `EditorCurveBinding.FloatCurve(<skinned renderer path>, typeof(SkinnedMeshRenderer),
     "material._MainTex_ST.{x,y,z,w}")` curves per state clip.
   - Read them from a `<unit>_water_cells.json` sidecar, since glTF cannot carry them.
   - Keys go at 0 and (i+0.5)/12, with constant tangents; the builder already evaluates DEF frame i at (i+1)/12.
   - Fail closed if a state clip has no sequence.
   - Stage the atlas as `<stem>_basecolor.png`, so the restamp loads it.
   - Emit the bindings into the builder's report.
2. **Validator**, `tools/validate_homm3_water_flipbook_contract.py`, wired into the OfflineUnlockMod build.
   From the sidecar and the builder report it asserts:
   - every state clip carries all four ST curves on the skinned renderer path;
   - every key is constant, and every value is one of the sidecar's cell STs;
   - the key count equals the DEF frame count;
   - held DEF frames reuse the cell;
   - the base colour size equals the sidecar's `atlasSize`.
   A state without the curve would render the whole atlas.
3. **Optional restamp extension**, only if A, C or D is wanted:
   - in `EnsureSkinnedBattleRuntimeCompatibility`, copy `_UvScroll` (A), the flag keyword and its three
     parameters (D), or the blend state and queue (C) from the imported material onto the clone, for
     materials opted in by a name tag (for example a `_hexwater` suffix);
   - add a restamp validator that pins the tag-to-property mapping.
   None of the three matches the DEF better than B, so this is not recommended.

### Unproven / open
- **In game:**
  - that the Animator MPB ST survives the real restamp and the native battle renderer;
  - that no native code sets its own MPB on unit renderers (`_HighlightTag`, `_HexFade` or dither fade
    would clobber it, or be clobbered). No MPB use was found on the plugin's skinned-unit path; the native
    side was not searched;
  - that the def_retarget clips reach the game at all. There is no def_retarget delivery builder yet.
- The lab shader is a replica: no shadows, and the lighting constants are from the sand battlefield.
- The atlas cells are procedural speckle scaled from DEF statistics (1.2 and 3 DEF px features, the DEF
  highlight density). They are not the DEF's own frames.
- The foam mask (y < 0.16 and outside 1.05 × the column radius) is a geometric guess.
- Spray, blob and puddle accents are described, not built.
- The retarget's weak idle body motion and the missing sink (Move) are separate retarget issues.
- **Questions for the user:**
  - Is B's re-roll look right in `compare/Unit_Idle.mp4`, or do you want flow (A) even though the sprite
    does not flow?
  - Should the water take the DEF's white-foam palette (B2), even though it currently lands dark under Hex/Lit?

### Phase 2: foam lighting, visible flow and DEF-ripped accents (look lab v2)

The user's decisions on phase 1:
- visible flow, even though the sprite boils in place;
- the water takes the DEF's own white-foam colours;
- build the spray, blob and puddle accents as DEF-ripped flipbooks.

They also asked that lighting and VFX be one pipeline. The result is authored as a unit-look spec,
`tools/homm3_unit_look/units/hota_cove_oceanid.json`, which the validator passes with 0 violations.

**Proof tier: Unity-editor-rendered** (the lab replica of Hex/Lit), plus generated artifacts. Nothing
has been run in game, and the unit-look runner has not been run on this unit: it fails closed on
`uvAtlas` layers.

**Tools** (all lab copies; no plugin, runtime, unit config or build output was touched):
- `tools/homm3_vfx/oceanid_look_lab.py`
  - `lighting` stage: the region grade. It imports `prebake_lab` read-only.
  - `cells`, `tile`, `accents` and `specmasks` stages.
  - Outputs go to `artifacts/homm3_vfx_experiments/oceanid/look/`.
- `tools/homm3_vfx/unity/Homm3OceanidLookLab.cs`, run by `oceanid_unity_lab.py --v2` through `unitylock.py`.
  - Variants: current, L, B2L, F, A2, A, FX, accents_only and mask.
  - Adds a 48 fps idle subsample.
  - Renders go to `renders_v2/`.
- `tools/homm3_vfx/oceanid_look_compare.py` writes `compare_v2/`:
  - `look_summary.txt` and `look_metrics.json`;
  - `sheet_<clip>.png`, `<clip>.gif` and `<clip>.mp4`;
  - `idle_sub48.mp4`, which shows stepped versus continuous motion;
  - `colour_idle.png`.

**Lab correction.** Phase 1's lab shader used a fixed world sun, which lit the SpriteCam view from
behind. That is part of why "current" read dark blue. v2 passes the prebake's camera-relative sand
arena sun (`views_meta.json` `sunFrom`) to the shader. The phase-1 colour readings are therefore not
comparable; the motion metrics are unaffected.

#### Lighting: a region grade, because the whole-unit v7c grade washed out the gold

- With v7c (Behemoth knobs, `--front=-y`), the gold turned pale cream: one grade cannot serve white
  water and gold together.
- The lab therefore grades two regions by the COLOR_0 water mask (Tail_* bones):
  - **Body:** the v7c recipe (detail, chroma detail, v7 shading, gloss), with the grade fitted to
    the DEF body pixels only. Result: [0.813, 0.518, 0.776, 1.184, 0.907, 0.024].
  - **Water:** the pattern score is rank-mapped onto the DEF's idle water palette, with column and
    foam separate. Then ×s×sky^-α and a palette gamma are fitted to the DEF water L\*a\*b\* under
    the sand sun. Result: s 1.10, α 0.04, γ 0.87. No bound hits.

Colour distance to the DEF (L\*a\*b\* p10–p90, lower is better):

| model | body: look / current | water column: look / current |
|---|---|---|
| Prebake relight (numpy, shadowed; the pipeline's review model) | 4.3 / 9.2 | 5.6 / 15.6 |
| Unity lab (no shadows) | 13.3 / 14.4 | 9.3 / 8.0 |

- The foam lands at L\* 66 against the DEF's 65.
- With effects on (FX), the whole-sprite distance is 6.2, against 9.0 for current.
- The Unity lab reads the body about 9 L\* brighter than the DEF. The lab shader has no shadow term,
  so the shadowed prebake number is the one to trust. Checking it needs the in-game renderer.

#### Flow options (idle, `look_summary.txt`)

| variant | how | water change (norm) | column velocity (DEF px/frame) | best/zero | 12 fps stepping | plugin change |
|---|---|---|---|---|---|---|
| DEF | – | 0.63 | none (boils) | 0.89 | 1.00 | – |
| B2L | stepped boil atlas | 0.62 | none | 0.99 | 1.00 | none |
| **F** | stepped **flow** atlas on the one renderer | 0.72 | **2.0 down** | 0.64 | **1.00** | **none** |
| **F2** | F with coarse travelling features (bands 8 px, speckle 3–5 px, highlights 4 px) | 0.70 | **2.0 down** | **0.46** | **1.00** | **none** |
| A2 | split column renderer, stepped tile cell + linear ST.w scroll | 0.72 | 2.0 down | 0.51 | 0.30 | none (builder split + `<stem>` textures) |
| A | split column, native `_UvScroll` | 0.72 | 2.0 down | 0.49 | 0.26 | yes (keep `_UvScroll` in restamp) |

The animator `_MainTex_ST` survives the restamp-style swap: F 78/78 and A2 78/78.

**Pick: F2**, the committed spec's `water_flow` layer.
- **Why F2 over F.** In F, the speckle (1.2–3 px) and the highlights (1 px) are finer than the
  2 px step between frames. They alias into a re-roll, so only the 5.3 px bands carried the flow.
  F2 makes every travelling feature at least twice the step, so they move instead of re-rolling.
- **Metrics.**
  - Multi-lag best/zero: F2 0.46, against F 0.64 and A 0.49.
  - Frame-to-frame (lag 1) velocity: F, F2 and A all find (−0.5, 1.5) px down. F2 has the most
    distinct peak (best/median 0.25, against 0.31 and 0.30).
  - F2 holds every 12 fps frame (stepping share 1.00).
- **What the metrics mean.** F2 carries the flow at least as strongly as the continuous-scroll
  routes A and A2, with no mesh split and no plugin change.
- **Eye check** (`compare_v2/battle_scale_idle_strip.png`: DEF, B2L, F, F2, A at 1 DEF px = 1 px,
  shown 2×). The F2 bands visibly step down the column from frame to frame. The MP4s are
  `compare_v2/Unit_Idle.mp4` and `idle_sub48.mp4`. This was judged from frame strips; nobody has
  judged it in motion in game.
- **Colour.** The same as F: column 9.3, foam 7.8, body 13.4 (Unity lab).
- **Why not A/A2.** They move continuously at 48 fps (stepping share 0.26–0.30), which loses the
  DEF's 12 fps character, and they need a split or a plugin change. The coordinator did not approve
  that schema extension, because F/F2 fit the current schema.
- **Cells.** They advance monotonically in every clip, because the DEF's Mouseover and Defence
  ping-pong would run the water backwards. Clip transitions pop the flow phase.
- **Un-lit source for the pipeline bake** (gap 2 decision): `look/flow2_scores.npz`, written by
  `oceanid_look_lab.py --stages scores`. It holds:
  - per-cell scores;
  - the column, foam and pad masks;
  - the DEF palettes.
  The bake stage rank-maps and grades the scores itself.

#### Accents (DEF-ripped `defFlipbook`s on the static Root bone)

All accents are Sprites/Default particle flipbooks, point filtered, a view billboard, 1 burst, with
frame i shown over [(i+0.5)/12, (i+1.5)/12).

| layer | clip / DEF frames | mask rule |
|---|---|---|
| `hit_spray` | Hitted 03 / 2–3 | `defEffects` water + detached |
| `attack_blob` | AttackFront 12 / 4–6 | `defEffects` water + detached |
| `death_spray` | Death 05 / 1–3 | `defEffects` water + detached |
| `death_puddle` | Death 05 / 0–8 | `file`: ground band, outside mesh, not gold |
| `move_puddle` | MoveStart 20, MoveEnd 21 | `file`, same rule |

- In the Unity lab, the rendered accents match the DEF effect masks pixel for pixel: IoU 1.00 on every
  layer and every frame. This proves the anchor, the timing and the point-filtered placement.
- The pipeline's `defEffects` rule reproduces the lab's spray masks (hit 107/112 px, blob 362/363).
- The puddle has no schema rule, so its per-frame masks are committed under
  `tools/homm3_unit_look/units/masks/hota_cove_oceanid/`.
- Some body-coloured bits of the DEF's collapsing figure fall inside the ground band on MoveStart
  frames 6–7, because the mesh shrinks where the DEF sinks.

#### Schema gaps (sent to main; the format was not forked) and their decisions
1. `lighting` has no vertex-mask region grade.
   **Approved** as `lighting.regions` (maskPath, vertexColor or bones; target grade or defPalette).
2. The runner cannot prebake uvAtlas cells with such a grade.
   **Decision:** there is no "prebaked by tool" escape hatch. The bake stage grades the cells, and
   this lab supplies the un-lit scores.
3. uvAtlas has no split renderer or continuous scroll.
   **Not approved.** F2 fits the current schema and reads as flow.
4. A defFlipbook mask has no region or row restriction.
   **Approved** as `effectMask.rows: [y0, y1]` relative to the anchor pixel. The puddle layers
   switch from `file` to `rows: [-16, 14]` once it lands.
5. There is no ground-plane render for the puddle.
   **Approved** as `render: "groundPlane"`, at low priority. The billboard stays until then.

#### Unproven / open (phase 2)
- In game:
  - the ST curves under the real restamp and native battle renderer;
  - the particle accents parented to Root in the battle prefab;
  - the Hex/Lit colour with shadows.
- The water colour uses the lab region grade. Once the runner gains gap 1, it should be refit there.
- Delivery still needs a def_retarget bundle builder that emits the ST curves and the flipbooks. The
  builder and validator plan from phase 1 applies unchanged, with `look_flow_atlas.png` as the
  atlas and `flow_cells.json` as the sidecar.

### Phase 3: moved onto the unit-look runner (spec `hota_cove_oceanid.json`)
- **Spec changes:**
  - The body and water grades are now `lighting.regions`: `column` and `foam` use `defPalette` with committed
    masks under `masks/hota_cove_oceanid/regions/`, and `defSegmenter` is `oceanid_water_motion.segment`.
  - `water_flow.uvAtlas.source.scores` now points at `look/flow2_scores.npz`. The un-lit F2 scores are written by
    `oceanid_look_lab.py --stages scores`; they are normalised, nearest-padded outside the water, and also
    write the region masks.
  - The puddles use `effectMask.rows: [-16, 14]` with `render: "groundPlane"`. This replaces the per-frame
    file masks, which are removed.
  - The accents are pinned with `defOrigin` to the Root pixel (193.79, 266.47).
- **Runner vs lab F2** (`oceanid_look_compare.py --runner`, results in `compare_v2/runner_vs_lab.json` and
  `runner_vs_lab_cells.png`). This is generated-artifact proof only.

  | Measure | Runner | Lab |
  | --- | --- | --- |
  | Column, median CIELAB (8 cells) | 57.9 / -1.2 / -6.0 | 59.1 / -1.1 / -5.3 |
  | Column, dE per cell | 2.4-2.5 | |
  | Foam, L* | 80.0 | 74.8 |
  | Foam, dE per cell | 7.3 | |
  | Cell-to-cell change correlation | 0.974-0.976 | |
  | Body static, L* | 50.4 | 41.5 |
  | Body static, dE | 11.4 | |

  - The flow motion is reproduced.
  - The column colour matches the lab.
  - The runner's foam is brighter than the lab's.
  - The runner's body is also brighter. Its rest grade hits the `gamma` lower bound (0.5); the lab body gamma was 0.518.
- **Runner review bug.** The review stage crashed on keys where the retarget shrinks Hips to 0.001, which
  leaves the mesh mask empty. This was reported to the runner owner, and the fix records `meshEmpty`.

### Phase 4: corkscrew water (2026-09-25)

The user found F2's water thin: "a thick water appearance, with volume and a corkscrew effect ... as if
you rotated the entire lower body while applying some wiggle to it". A texture scroll cannot give that
volume, because Hex/Lit has no specular or emission. The motion now comes mainly from the geometry,
and the texture is re-derived to turn with it.

**Geometry: `tools/homm3_def_retarget/ext/cove_corkscrew.py`.** This is a retarget extension; the
shared scripts are unchanged. It is enabled in `units/hota_cove_oceanid.json` (`coveCorkscrew`) and
listed before `cove_sink`. The motion is ordinary `Tail_*` bone rotation keys, so it survives the GLB
export and the bundle builder, which keeps local rotations. It has two parts:
- **Twist:** a torsional wave on each column link about the world vertical. The knobs are `twist.deg`
  (30), `twist.waves` (0.75 down the column) and `env` (0 at the waist, 1 from u = 0.8 to the ground).
- **Whirl:** the centreline is pulled toward a counter-clockwise rotating helix. The knobs are
  `whirl.radius` (0.035 u, about 1.4 DEF px), `turns` (1) and `env` (peak at u = 0.4, 0 at u = 0.9).

Both parts are periodic with `period` 8, so Idle and Move (8 frames) close exactly. Other clips
restart the phase, as the uvAtlas already does. `clipGain` defaults to Death 0.5. The ground links ride
rigidly with the last column link.

**Required rebind (`rebindByHeight`, after_skin).** The surface-distance tail weights plus the
build's 284 cut "fused-loop" edges put links far apart along the chain side by side at one height
(for example Tail_03 next to Tail_06). Any twist between links tore those seams: 90-180 edges above 2x
per idle frame with the corrective-smooth morphs muted, which is what a runtime without morph curves
would show. The rebind re-spreads each vertex's Tail share over the vertical links by rest height and
keeps the waist blend. After it, muted-morph tearing over the whole reel is 198 edge-frames, against
2022 for the old build, so it is lower than before the corkscrew. The corrective-smooth bake had
been hiding the old seams.

**Texture: `tools/homm3_vfx/oceanid_corkscrew_scores.py`** writes `look/corkscrew_scores.npz`, now the
spec's `water_flow` source. The pattern is built in the column's helical frame and rotates
counter-clockwise at 15 deg per 12 fps frame (3 angular repeats, 120 deg per 8-frame loop, so it
loops exactly). It is the same rotation sense and helix handedness as the whirl. It has four terms:
- helical ridges (0.42);
- broad coherent sheets (0.22);
- a static mesh-curvature term (0.24): grooves dark and crests light, a baked volume that rides the
  twist;
- a small boil share (0.12), plus crest-locked highlights.

The foam turns with the column as a whirlpool, with more boil.

**Measurements** (generated artifact; the retarget reel's 1 DEF px sprite renders, idle frames 0-7):

| | DEF | old build (control) | corkscrew (delivered) |
|---|---|---|---|
| idle mean IoU vs DEF | – | 0.722 | 0.710 |
| mouseover / hitted / defence / attack IoU | – | 0.768 / 0.553 / 0.573 / 0.535 | 0.755 / 0.548 / 0.560 / 0.526 |
| move start / end / death IoU | – | 0.300 / 0.227 / 0.316 | 0.298 / 0.224 / 0.316 |
| column pixels changing per frame (geometry only) | 0.719 | 0.008 | 0.463 |
| silhouette XOR px per frame, lower body | 114.5 | 12.5 | 110.2 |
| reel edges > 2x (with morphs), summed | – | 346 | 320 |
| reel edge-frames > 2x (morphs muted) | – | 2022 | 198 |

- The silhouette now boils about as much as the DEF's (110 against 114 px per frame), and silhouette
  IoU drops by at most 0.013 on any clip.
- Scratch variants: cs3 (twist 25, whirl 0.03) gives IoU 0.714 and XOR 98. cs4 (35 deg, 0.75 waves,
  whirl 0.05) gives IoU 0.705, XOR 128 and 32 torn edges on Hitted. cs5 was delivered.
- `verify_glb` passes, with Idle and Move loop closure 0.0.
- The unit-look apply passed with 0 validator violations: body L-hist raw 11.58 -> look 8.41, 2.96
  with effects. The previous delivery's look was 7.68, so the static body-plus-water histogram is
  0.7 worse; the cell-0 water is now sheets plus curvature instead of speckle. The `grade:gamma`
  lower-bound hit is the same as in phase 3.

**Review media:** `artifacts/homm3_def_retarget/_oceanid_corkscrew_review/`. It holds
`before_after_showcase.mp4` (left the F2 showcase, right the corkscrew), the before copies of the
showcase, clips and metrics, and `idle_before_after_zoom.mp4`.

**Superseded:**
- `look/flow2_scores.npz` is no longer referenced by the spec. It stays as the lab's F2 record; do not
  point a spec at it.
- The rebuild overwrote the pre-corkscrew delivered GLB in place. Its un-prebaked source,
  `808666a0468a.glb.unprebaked`, remains under
  `artifacts/homm3_unit_look/hota_cove_oceanid/_superseded_do_not_use/`. The stamp now names
  source `85976af46db2` and delivered `f09890bdd317`, so the validator fails on any other GLB.
- The scratch builds `hota_cove_oceanid_{ctl,cs1..cs5}` were deleted after measurement.

**Proof tier:** generated artifact (Blender reel plus unit-look runner). Nothing is in game.
- The twist rides on bone rotations only, so it needs no builder change once def_retarget clips reach
  the game.
- The uvAtlas water still needs the phase-1 delivery work: `_MainTex_ST` curves from a sidecar in the
  bundle builder, and the water flipbook validator.
- The morph-curve drop and the builder's lack of def_retarget delivery are unchanged. The rebind makes
  the corkscrew independent of the corrective-smooth morphs.

## Phoenix fire (`h3_phoenix`, CPHX.DEF; `h3_firebird`, CFBIRD.DEF)

The goal: make the retargeted phoenix look and move like the fire in the sprite. It does not have to
be literal. **Proof tier: generated artifact.** Everything here is a numpy Hex/Lit relight of the
Blender render passes (`render_passes.py`, 2x supersample, SpriteCam, the unit's `front = -y`),
composited in 2D at DEF scale.
- The fire light is a flat-depth approximation of the URP per-object point light:
  `saturate(1-(d²/r²)²)²/d² · N·L`.
- Nothing was rendered in Unity.
- Nothing is in game.

### Tools and outputs

| script | writes (under `artifacts/homm3_vfx_experiments/phoenix/`, regenerable, not in git) |
|---|---|
| `tools/homm3_vfx/phoenix_fire_motion.py` | `evidence/fire_motion.json`, `fire_motion_summary.txt`, `regions_gNN.png` (BODY / FLAME / EMBER / CORE per frame) |
| `tools/homm3_vfx/phoenix_fire_lab.py` | `lab/textures/` (grade, look, glow mask, `fire_boil_atlas.png`), `lab/fire_boil_cells.json`, `lab/frames/<cand>/`, `lab/lab_report.json` |
| `tools/homm3_vfx/phoenix_fire_compare.py` | `compare/sheet_<clip>.png` (DEF row + candidates, 2x), `compare/<clip>.gif` / `.mp4` (12 fps), `compare/metrics.json`, `metrics_summary.txt` |
| `tools/homm3_vfx/phoenix_fire_masks.py` | committed file masks `tools/homm3_unit_look/units/masks/{h3_phoenix,h3_firebird}/<layer>/GG_FF.png`; preview `masks_preview/` |

The region rule, used for both the measurements and the masks:
- **BODY**: the main silhouette after an r=3 opening.
- **FLAME**: the silhouette minus BODY.
- **EMBER**: components detached from the silhouette.
- **CORE**: BODY pixels with luma >= 225.

The roster colour rule (`def_effects`) cannot be used on these units. It keeps colours that are
absent from idle, and a body that is fire has every fire colour in its idle frames. On the firebird
it saw the breath jet only once the jet detached (frames 10-11). On frames 4-9 it found 80-157 px,
where the jet is 2800-4400 px.

### What the DEF fire does (measured)

- **Idle (group 2): fire boils and flickers in place, redrawn every frame at 12 fps. It does not
  travel.**
  - There are 8 unique frames with no holds, and the silhouette shift is 0.
  - 31-42% of body pixels change per frame. The body texture velocity is 0, and the body lag
    dissimilarity is flat (485-541).
  - Flame-zone membership flips about 0.31 at every lag from 1 to 7. A flat curve means the flames
    are redrawn each frame; a rising curve would mean smooth motion.
  - Multi-lag flame texture velocity is (-3.5, -3.5) px/frame (up and back), but best/zero is only
    0.785, a weak drift. With a 1 px step it is 0.90.
  - Tip height jitters ±1-4 px per frame with no net rise.
  - The hot core is mostly steady: it survives within 1 px at 0.61, against 0.26 by chance.
  - Where the flames are: 51% in the top third and 9% above the body.
- **Move (group 0), 6 frames.** Same behaviour. Flames sit in the top 70% as a crest over the back,
  best/zero 0.73.
- **Mouseover and defence.** 5-frame ping-pongs (0-4-0); the fire plays in reverse too.
  Move_end is move_start reversed.
- **Attack (group 12), 12 frames.**
  - Frames 0-3: wind-up.
  - Frames 4-9: a jet from the beak. It alternates between frames 4 and 5 three times, a 2-frame
    (6 Hz) flicker held for 6 frames.
  - Frame 10: the jet detaches and flies.
  - Frame 11: remnants.
- **Hit (group 3).** The core flashes on frames 0-1 (20% of the body). Embers are flung outward,
  229 to 835 px over frames 2-5.
- **Death (group 5).**
  - Frames 0-1: white-hot (core 39% / 33%).
  - Frames 2-3: wings spread, burning.
  - Frame 4: a pillar of fire (4571 flame px, 53% above the body) while the body goes dark.
  - Frames 5-6: an ash pile.
- **Not in the DEF.** There is no rebirth group. `c09spf0` is a summon portal, not rebirth. There
  are no shadow palette slots.
- **Firebird (CFBIRD).**
  - It has no idle fire: the body is orange feathers.
  - Its breath (g12) and ash (g5 frames 5-6) are the phoenix's art, pixel for pixel (identical mask
    counts).
  - Its death frames 1-2 flash the whole body yellow (roster peak body luma rise 36.7), then it
    burns down (frame 4) to the same ash pile.

### Candidates

Every candidate is judged with its effects on.

| id | what |
|---|---|
| C0 | raw retarget mesh under Hex/Lit, sand arena |
| C1 | + grade (numpy Nelder-Mead to the DEF idle body minus the core, fitted **under the fire light's floor 0.45**) + baked glow (UV mask radial from the spine, chest-biased, patchy; rgb (1, .72, .25)) |
| C2 | + `fire_boil` uvAtlas: 8 value-noise cells (vertically stretched, hot spots, red dark spots), amplitude fitted to the DEF idle body change 0.347 (got 0.33), one cell per new DEF frame name |
| C3 | C2 + DEF-ripped flames: crest (ragged top 20-34 px of the upper silhouette, feathers excluded) behind the body + fringe (flame/ember off the mesh) in front, + events (attack jet, hit embers, death burn / pillar / ash) |
| C4 | C2 + procedural tongues: 21 teardrop-clipped flame tips + 73 embers cut from the DEF idle, re-placed each DEF frame on the **mesh's** upper silhouette edge (behind), embers in front; same events as C3 |
| C5 | C3 + fire light (Lights module point light, rgb (1, .72, .36), range 3), intensity bisected per DEF frame so the mesh body mean L* equals the DEF body mean L* |
| C6 | C4 + the same fire light |

### Results (`compare/metrics_summary.txt`)

L\* histogram distance to the DEF, over the whole unit (lower is better). The DEF's L\* p10/50/90
(idle) is 44 / 72.9 / 91.

| clip | C0 | C1 | C2 | C3 | C4 | C5 | C6 |
|---|---|---|---|---|---|---|---|
| Idle | 11.6 | 11.0 | 11.74 | 12.28 | 10.78 | **2.08** | 2.78 |
| Move | 7.89 | 6.94 | 7.57 | 8.02 | 6.28 | **1.50** | 2.59 |
| Hitted | 13.31 | 12.29 | 13.04 | 13.11 | 11.42 | **1.60** | 2.67 |
| AttackFront | 11.29 | 10.35 | 10.53 | 13.0 | 11.14 | 2.91 | **1.85** |
| Death | 12.21 | 11.99 | 11.09 | 7.8 | 6.91 | **2.93** | 3.21 |

The other measures, on idle:

| measure | DEF | C0 | C5 | C6 |
|---|---|---|---|---|
| median a\* / b\* | 28.5 / 70.7 | 21.7 / 65.9 | 23.6 / 74.0 | 23.0 / 74.5 |
| hot-core share of the body | 0.079 | 0 | 0.092 | 0.090 |
| body change per frame | 0.347 | 0.002 | 0.26 | 0.26 |
| flame flip by lag 1-4 | 0.20 / 0.20 / 0.20 / 0.21 | 0.13 / 0.16 / 0.16 / 0.15 | 0.21 / 0.21 / 0.21 / 0.22 | 0.19 / 0.19 / 0.19 / 0.20 |
| flame velocity best/zero (travel < 0.6) | 0.90 | 1.0 | 0.92 | 0.85 |
| silhouette IoU with the DEF | 1 | 0.53 | 0.58 | 0.52 |

Findings:
- **The light does the work, not the albedo.** Under Hex/Lit a baked glow is an albedo lift capped
  at 1. The bluish ambient greys it, and the unlit side is grey-ochre.
  - C0 to C1 only moves L-hist from 11.6 to 11.0, and the hot-core share stays at 0.
  - The fire light takes every clip from about 11 to about 2. The fitted idle floor is 0.67-0.98.
  - An earlier pass with a separately fitted glow at strength 3 pinned both the grade gamma
    (0.4 bound) and the glow bound, and still got a core share of only 0.02.
  - Fitting the grade *under* the light's floor fixed the hue: a\* with the light on rose from 21.3
    to 23.6 on idle, 19.8 to 28.0 on move, 20.3 to 25.1 on hit and 24.5 to 28.4 on attack. The DEF
    is 28-37.
  - That grade now pins gamma at its upper bound, 1.6 (`boundHits [1]`). The grade/light split is
    not unique, which is open question 2.
- **Flicker character matches.** Flame flip rate is flat over lag in every candidate that has
  flames, as in the DEF: redrawn in place, no travel.
  - The boil atlas brings body change from 0.002 to 0.33 unlit (0.26 once the light saturates the
    brights; DEF 0.347).
  - On the attack, the 2-frame breath alternation shows up in flip-by-lag (lag 2 low) in C3 to C6,
    as in the DEF.
- **The metrics prefer C5; the sheets prefer C6 for the loops.**
  - The retarget's silhouette and wing pose differ from the sprite: IoU 0.4-0.6, and in move the
    wings are raised back where the DEF flaps them down.
  - So the ripped crest (C3/C5) lands beside the mesh as floating fragments, and on move f4 as a
    rectangular block. Fewer, darker pixels there score better on L-hist than a crest that reads.
  - The tongues (C4/C6) sit on the mesh's own edge and read as a burning crest. They are still
    blocky at DEF scale.
- **Events: the ripped DEF pixels are best** (the user's guidance). The jet, the flung embers, the
  pillar and the ash pile are shapes no procedural layer matches.
  - The jet's thick root is wider than the r=3 opening, so the region rule calls it BODY, and the
    first pass left the jet floating about 40 px off the beak.
  - The breath mask is now everything opaque in front of the beak (DEF x >= 276, y >= 190 until
    x >= 320): 2800-4400 px per frame instead of 720-1200.
  - The ash frames replace the body entirely.
  - **Remaining defect: the jet starts 32-33 DEF px (about 0.29 world units) ahead of the mesh's
    beak on attack frames 4-11.** The mesh's front edge is at x 243-244; the DEF jet root is at 276.
    The retarget does not lunge the head forward the way the sprite does.
    - The approved fix is `anchor.defOrigin` (with `boneTip` on the head chain), which pins the jet
      root to the projected beak. The specs switch to it once it lands.
    - The missing lunge is on the retarget articulation list.

### Recommendation

The body fire recipe is C6, and the discrete events are DEF-ripped. Both specs are on the
schema landed in 1a7a83240f (`docs/homm3_unit_look_pipeline.md`).

`tools/homm3_unit_look/units/h3_phoenix.json`:
- **Lighting:** v7c, `front: -y`, no bakedGlow (the lab's baked lift bought almost nothing under
  Hex/Lit). `defSegmenter` = `phoenix_fire_masks.def_regions` (DEF body luma >= 100 is `fire`,
  the rest `dark`), and one `defPalette` region `fire` (UV mask `masks/h3_phoenix/fire_region_uv.png`,
  the lab's Lab-chroma fire rule). The fire texels take the DEF's own fire colours; the dark rest
  (beak, talons, feather strokes) keeps the v7c grade.
- **`fire_boil` uvAtlas**, graded by the runner from
  `artifacts/homm3_vfx_experiments/phoenix/scores/fire_boil_scores.npz`
  (`tools/homm3_vfx/phoenix_fire_scores.py`: 8 cells of rank(luminance + 0.6 chest core +
  beta * boil noise), beta 0.90 bisected so the simulated per-cell colour change is the DEF's 0.347).
  Ping-pong and reverse cell orders for mouseover, defence and move_end.
- **`body_fire` light** on the `fire_tongues` carrier with a per-clip `floor` (idle / mouseover /
  defence / attack 0.8, move 0.3, hit 0.45, none on death) and **authored** hit and death curves:
  both flashes sit on keys 0-1, and the runner's fitted rise is measured over key 0, so a fitted
  curve would lose them.
- **`breath`** pinned with `anchor.defOrigin [276, 214]` + `boneTip` on Head: the DEF jet root goes
  to the mesh beak, so the 32 px beak gap is gone without a lunge. `breath_glow` is fitted.
- **`hit_sparks` / `death_burn`** carry per-frame `defOrigin`s (the DEF body centroid of each frame).
- **`death_ash`** on Root with `defOrigin` = the SpriteCam projection of the world origin. It stays
  `render: billboard`: the pile is a side-view mound 30-40 px high, and laid on the ground it would
  foreshorten to a smear.
- **Event `hideMesh`** on death frame 5 (all renderers, body + `h3_phoenix_Rubble`).

`h3_firebird.json` has the same events without the body fire (v7c, `front: auto`, no regions):
`breath` (same `defOrigin` + `boneTip`) with a **fitted** `breath_glow`, `death_burn` with per-frame
origins and a **fitted** `death_flare` (the flare peaks on frames 1-2, after key 0, so it fits),
`death_ash` (billboard, origin [225, 270]) and `hideMesh`.

### Runner results (`look.py --stages bake,fit,vfx,review`, 2026-09-25)

Proof: generated artifact (numpy relight of Blender passes + 2D effect composite). The runner does
not simulate particles, so `fire_tongues` is absent from these numbers. The fair lab comparison is
C5 (boil + floor light, no tongues); C6 is the lab with tongues.

Body L-hist distance to the DEF (lower is better):

| clip | runner raw | runner look | runner look+FX | lab C5 | lab C6 |
|---|---|---|---|---|---|
| Idle | 11.32 | 9.91 | 2.82 | 2.08 | 2.78 |
| Move | 7.49 | 3.91 | 2.27 | 1.50 | 2.59 |
| Hit | 13.54 | 10.28 | 3.37 | 1.60 | 2.67 |
| Attack | 15.39 | 12.56 | 2.72 | 2.91 | 1.85 |
| Death | 19.05 | 14.23 | 4.78 | 2.93 | 3.21 |

- **Phoenix.** Mean 14.89 raw, 11.72 look, 3.37 with effects. The yaw spread is sand 8.2 /
  grass 3.9.
  - The `fire` region fit: s 0.44, skyAlpha 0.76, palette gamma 1.01, on 21863 DEF pixels and
    47930 texels, with no bound hits.
  - The rest grade fits on 3917 DEF pixels and pins gamma at its 0.5 bound. The lab also hit
    gamma, at its 1.6 bound, so the dark rest is under-determined.
  - The runner matches the lab on idle, move and attack. It is 1.2-1.8 worse on hit and death.
    Those clips add DEF-only fire (flung embers, the white-hot flare) that the runner's region
    palette does not boil.
  - The fitted `breath_glow` stays below 0.1: over the 0.8 attack floor, the DEF body brightens
    little while the jet burns.
- **Firebird.** Mean 12.59 raw, 10.87 look, 7.20 with effects.

  | clip | raw | look | look+FX |
  |---|---|---|---|
  | Idle | 2.79 | 2.75 | 2.17 |
  | Move | 5.88 | 9.27 | 9.45 |
  | Attack | 11.64 | 8.40 | 5.08 |
  | Death | 22.0 | 22.75 | 11.96 |

  - The grade hits the gamma (0.5) and whiteB (1.3) bounds, and move gets worse under the grade.
  - Fitted `breath_glow` peaks at 3.06 on frames 4-5, a strong jet light with no floor under it.
  - Fitted `death_flare` is [0, 0.92, 1.30, 0, ...], against the authored 1.4 / 1.2.
  - The worst row, death frame 2, is the DEF's yellow whole-body flare, which the light only
    partly reaches.
- Sheets:
  - runner, per unit: `artifacts/homm3_unit_look/<unit>/review_sheet.png` and
    `review_worst_row.png`;
  - lab: `artifacts/homm3_vfx_experiments/phoenix/compare/`.
- **`apply` is not run.** It refuses a unit with a floor light until the light runtime ships.
  That applies to the phoenix; the firebird has no floor, but was not applied, to keep the pair
  together.

### Delivery work (not done; plugin and builder untouched)

1. **Builder: keep `material._MainTex_ST` curves** in `Homm3OwnedSkinnedLabBuild.RebaseClipPaths`
   for the `fire_boil` atlas. This is the oceanid change. Today only bone rotations are kept.
   - Risk: low. The curve drives a MaterialPropertyBlock, which survives the plugin's Hex/Lit
     restamp.
   - Rebuild the atlas from the lighting stage's `basecolor.png`; the lab atlas is built from the
     lab grade.
2. **`PhoenixFireTongues.prefab`** (a ParticleSystem under the HoMM3 root, parented to Spine2):
   - texture-sheet frames from the tongue bank;
   - emission on the mesh's upper edge, re-seeded per DEF frame (12 fps stepped);
   - Sprites/Default, point filter, alpha blend;
   - a Lights module with ratio 1, maxLights 1, a template Point light, and intensity from the
     spec curve.

   Particle renderers are not restamped, so this survives (static read, as for the storm
   elemental). The CPU review cannot simulate it, so it needs a Unity spot check.
3. **defFlipbook quads** for breath, hit_sparks, death_burn and death_ash, via the unit-look `vfx`
   stage.
4. **Hide the mesh at death frame 5.** This covers both the body and the `h3_phoenix_Rubble`
   SkinnedMeshRenderers, since the rubble chunks otherwise show through the ash.

### Open questions

1. How strong is the fire light in Unity? The URP per-object limit is 8 lights, with a flat-depth
   approximation here, and the attack peaks at 1.84 on the phoenix. Several phoenixes lighting
   each other, and their neighbours, is untested.
2. Is the grade/light split right? Fitted under the floor, the grade pins gamma at 1.6, so a
   darker albedo plus a stronger light, or the reverse, match equally well. An in-game look at
   other arenas (the grade was fitted for sand) would settle it.
3. Is a looping crest from the DEF worth a pose-matched crest? That would mean warping the ripped
   crest onto the mesh edge instead of re-placing tip sprites. C6 is the cheaper answer.
4. What about rebirth? It is not in the DEF. VCMI reportedly plays death in reverse (unverified).
   It would need its own clip.
5. The firebird grade hits its gamma and whiteB bounds, and move gets worse under it (5.88 -> 9.27).
   A `--try-modes` pass (v6m), or regions for its flared plumage, may be needed.

## Elemental body motion + texture flow (conflux elementals, `hota_cove_nymph`)

Brings the oceanid corkscrew idea (continuous elemental motion on bone keys, plus a
texture flow in the look, kept inside the DEF silhouette) to the conflux elementals and the cove nymph.
Each elemental gets a mode chosen from what its DEF does. No bespoke hook per unit.

**Proof tier: generated artifact only.** Retarget GLBs are rebuilt and look.py has applied
the atlases (validator 0 violations per unit). Nothing here is bundled, installed or seen in
game yet.

### Pieces

- `tools/homm3_def_retarget/ext/element_motion.py`: retarget extension, config
  `elementMotion {mode, period, <component overrides>}`. A component set to `"off"` is dropped.
  - Carriers:
    - `column`: new `Col_00..n` bones built from the lowest body joint to the lowest
      vertex. The chosen vertices are re-skinned by height hats, and a blend band sits at
      the joint.
    - `tail`: an existing `Tail_*` chain.
    - `bones`: the body bones themselves.
  - Motion components:
    - twist about the vertical axis or the link axis;
    - a helix or lateral whirl;
    - sway, with a per-axis weight and lag down the chain;
    - stepped jitter;
    - a scale pulse.
  - Every component is exactly periodic. Loop clips snap the period to divide the clip
    frame count (`eff_period`).
- `tools/homm3_vfx/element_flow_scores.py`: builds per-texel score cells in UV space
  (`artifacts/homm3_vfx_experiments/element_flow/<unit>_scores.{npz,json}` + `_preview.png`).
  - It uses the same period and carrier chain as the motion, so the texture moves in phase
    with the bones.
  - It fails closed if the carrier chain is missing from the GLB.
  - `flow.pulseFromDef: s` multiplies in the DEF idle's own mean-luma curve. This needs the
    cell count to equal the idle frame count.
- New uvAtlas variant `modulate {gain}` (`tools/homm3_unit_look/vfx.py`, `spec.py`):
  - Each cell is `look_texture * clip(1 + 2*gain*(score-0.5))`.
  - It needs no defPalette regions.
  - `modulate` and `regions` are mutually exclusive, and `0 < gain <= 1`.
  - The layer id is `element_flow` and it is placed first in the look spec.

### Mode per unit (chosen from the DEF idle survey)

| DEF idle | Mode | Motion | Texture flow | Units |
|---|---|---|---|---|
| swirl, xor ~0.13 | vortex (column, 6 links) | twist 35 deg, 1 wave, helix whirl r 0.03 | bands spiral up the column | air (P6); hurricane, storm (P10, `pulseFromDef` 0.5; storm adds 1.5 deg stepped jitter on Spine1..Head) |
| still silhouette | shimmer (column, 5 links) | twist 6 deg, whirl 0.015, pulse 0.006 | slow rising bands | magic, psychic, astral (P8) |
| still, rock | grind | 1.5 deg sway on Hips..Spine2 | tile-scale slab shading | earth (P8) |
| still, molten; magma pulses its luma 49->29->49 | roil | 1.5 deg lagged sway Hips..Head, pulse 0.006 | churning tiles + flame tongues | lava (P8); magma (P8, `pulseFromDef` 0.7) |
| alternating-frame flicker | crackle | 2.5 deg stepped jitter, 2-cycle pulse | filament flicker | energy, plasma (P7, `pulseFromDef` 0.6) |
| subtle fluid | coil (tail) | 14 deg link-axis roll, lateral whirl 0.012 | bands travel down the tail | water (P8) |
| subtle, crystalline | crystal | pulse 0.004 only | sparse glints + sheen band | ice, frost (P8) |
| fluid tail | oceanid corkscrew | `ext/cove_corkscrew.py`, oceanid knobs | `elementFlow` vortex on `Tail_` | hota_cove_nymph (P8) |

Mode defaults live in `MODES` (element_motion.py) and `FLOW_DEFAULTS`
(element_flow_scores.py). Per-unit knobs live in `tools/homm3_def_retarget/units/<unit>.json`.

Why the geometry is small for the still units: the DEF idles of magic, psychic, astral,
earth, lava and magma do not move at all, and the retarget already moves more than they do.
For those units the motion is carried by the texture. Magma's look now pulses its body luma
45->25->41 across the idle, against the DEF's 49->29->49.

### Results (control = HEAD before this pass; muted = morph-muted tearing, the in-bundle number)

| Unit | idle IoU | mean IoU | worst clip dIoU | reel edges | muted tearing |
|---|---|---|---|---|---|
| air | .785->.776 | .667->.662 | -.011 | 633->856 | 2869->2904 |
| hurricane | .774->.766 | .626->.618 | -.013 | 2111->2168 | 5724->5727 |
| storm | .811->.811 | .669->.659 | -.020 | 2697->3204 | 10484->10477 |
| magic | .880->.879 | .731->.730 | -.002 | 388->394 | 489->491 |
| psychic | .766->.765 | .657->.657 | -.001 | 58->59 | 242->242 |
| astral | .813->.813 | .686->.686 | -.004 | 439->455 | 342->345 |
| earth | .778->.786 | .673->.676 | -.008 | 924->901 | 12977->13043 |
| lava | .787->.786 | .658->.658 | -.005 | 5->5 | 200->196 |
| magma | .772->.773 | .621->.619 | -.006 | 0->0 | 303->305 |
| energy | .622->.620 | .403->.404 | -.002 | 3848->3887 | 6409->6417 |
| plasma | .558->.556 | .402->.401 | -.006 | 120->123 | 856->874 |
| water | .763->.763 | .539->.539 | -.004 | 4658->4880 | 4427->4472 |
| ice | .784->.784 | .546->.546 | -.001 | 2555->2574 | 7133->7151 |
| frost | .781->.780 | .555->.555 | -.001 | 4706->4721 | 8976->8972 |
| fire | .724->.724 | .621->.620 | -.006 | 3543->3560 | 17246->17279 |
| hota_cove_nymph | .742->.729 | .491->.485 | -.013 | 99->33 | 1041->135 |

The first air vortex cut (40 deg, r 0.04, two cycles per period) tore +8% muted. The shipped
knobs are the ones above. The nymph's tearing fell because the corkscrew rig replaces its
older tail keys.

Review media are in `artifacts/homm3_def_retarget/_element_motion_review/<unit>/`:
- `before_/after_clips.mp4` and `before_/after_showcase.mp4`;
- `before_after_clips.mp4`, stacked for comparison;
- `before_/after_metrics.json` and `before_/after_tear_muted.json`.

Earth, lava and plasma have no `before_` showcase, because it was rendered after the
rebuild. Their before/after comparison is the retarget's own `compare.mp4`
(`artifacts/homm3_def_retarget/<unit>/`) together with the metrics JSONs.

### Not carried / open

- **energy**: the geometry is rebuilt, but look.py refuses to deliver its atlas (L-hist
  20.5 against 15.0 raw). This regression predates this pass: the roster summary already
  showed energy's look unapplied. Its `element_flow` layer stays in the spec and will
  deliver once energy's look is retuned.
- **fire** (on the regenerated Meshy mesh, 4fbbceaf6e): roil, P6, flow gain 0.5. The geometry
  is promoted, and the emphasis stamp was re-run with `deliver.py` (unchanged). A 3 deg sway
  overshot the DEF (xor 537 against 246) and was dropped for the 1.5 deg preset.
  Its `element_flow` layer is in the spec, but look.py refuses the apply on the fire
  agent's own `effectLight.floor` (`body_fire_light`) until the effectLight runtime ships.
  So fire's texture flow is not delivered. The volumetricFire block is untouched.
- **Idle retime interaction**: the atlas `clips` lists cells per DEF frame. If an idle is
  retimed (idle-cadence, 3.2x), rebuild the scores and layer from the retimed GLB, or
  stretch the `Unit_Idle` cell list to match. Otherwise the texture flow runs 3.2x faster
  than the bones.
