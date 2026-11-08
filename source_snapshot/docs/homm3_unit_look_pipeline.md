# HoMM3 unit look pipeline (lighting + VFX)

One pipeline decides how a DEF-retargeted unit *looks*: its prebaked base colour (lighting) and
its effect layers (VFX). They are one pipeline because they affect each other. A steady glow can
be baked into the base colour, a flashing glow must not be, and a unit's colour match is judged
with its effects on.

- Spec (committed, one file per unit): `tools/homm3_unit_look/units/<unit>.json`
- Entry point: `python tools/homm3_unit_look/look.py`
- Contract validator: `tools/validate_homm3_unit_look_contract.py`. It replaces the separate
  prebake validator that was planned earlier.
- Per-unit outputs (not in git, regenerable): `artifacts/homm3_unit_look/<unit>/`

The existing modules stay where they are and run behind the entry point:

- `tools/homm3_prebake/`: `bake_terms.py`, `render_passes.py` and `prebake_lab.py`. See
  [homm3_prebaked_lighting.md](homm3_prebaked_lighting.md).
- `tools/homm3_vfx/`: `h3def.py`, `def_effect_layer.py`, the Titan tools and the oceanid tools.
  See [homm3_vfx_experiments.md](homm3_vfx_experiments.md).

Proof tier of everything this pipeline produces: **generated artifact.** The review renders are
numpy relights of Blender passes, with 2D effect composites. Unity-editor renders are spot checks
only. Nothing here is proven in game.

## Spec schema (`homm3_unit_look.v1`)

```jsonc
{
  "schema": "homm3_unit_look.v1",
  "unit": "h3_giant_upg",            // must equal the file stem and the def_retarget folder name
  "status": "look",                  // "look" = deliver; "excluded" needs "excludedReason"
  "lighting": {
    "mode": "v6m",                   // "v7c" (whole-unit grade) | "v6m" (per-material grade)
    "front": "-y",                   // "+x" | "-x" | "+y" | "-y" | "auto" (resolved and recorded, fails closed)
    "arena": "sand",                 // relight condition used for the fit
    "knobs": {},                     // overrides over the mode's defaults (see prebake doc)
    "bakedGlow": [],                 // steady self-glow baked into the base colour (see Lights)
    "regions": [],                   // optional: per-region grades against their own DEF region (see Regions)
    "defSegmenter": {}               // required with regions: {"module": "<repo .py>", "function": "<name>"}
  },
  "lights": [                        // every light source the unit has, one treatment each
    {"id": "bolt_flash", "treatment": "dynamic"}
  ],
  "vfx": { "layers": [ /* see Layer types */ ] }
}
```

A unit with no VFX yet has `"vfx": {"layers": []}` and `"lights": []`. Unknown keys are errors.

### Lighting

- **`mode`** is the grade family. `v7c` is the whole-unit grade: the Behemoth recipe, with cavity,
  chroma detail, band a*b* transfer and a neutral wet speckle. `v6m` grades each material class
  separately; it is the Titan recipe. The runner may fit both and write the measured choice into
  the spec, but a committed spec always names one mode. There is no `auto` mode.
- **`front`** is the unit's facing axis in Blender. `auto` is resolved from the source GLB's rest
  pose: first the feet (Foot->ToeBase on both sides, horizontal, both within ~35 deg of the same
  axis), then the Head-Hips lean (at least 10% of its height). If neither decides, the run fails
  closed (exit 3). An upright unit without toes (the wight) needs an explicit axis. The resolved
  axis and its source are recorded in `fit_source.json`, `metrics.json` (`frontResolved`) and the
  stamp. Every unit measured so far resolves to `-y`; the SpriteCam is fixed for every build.
- **Knobs** that hit a fit bound are reported in `metrics.json` under `boundHits`. Do not
  silently widen the bounds.
- **Grade objective knobs (v7c, opt-in; absent = the original fit, bit for bit).**
  `gradeWeights: [L, a, b]` re-weights the percentile objective (default `[1.0, 0.7, 0.7]`), and
  `gradeStarts: "wide"` adds four low-exposure / low-gamma Nelder-Mead starts plus a refine pass.
  The review metric is L\* only and the band transfer corrects a\*b\* after the grade, so the a\*b\*
  terms can drag L off the DEF for nothing; and from the two default starts the optimiser stalls
  when the baked v7c shading is far darker than the DEF (the `gamma@min0.5` bound hit). The roster
  presets used on 2026-09-26 are `W` = `{"gradeWeights": [1.0, 0.2, 0.2], "gradeStarts": "wide"}`,
  `soft` = W + `aoGamma 0.6, cavityGamma 0.8, skyFloor 0.6, heightDepth 0.15`, and `softer` = W +
  `aoGamma 0.3, cavityGamma 0.4, skyFloor 0.8, heightDepth 0.0, detailAmount 0.5` (weaker baked
  AO/cavity/sky shading, for units whose DEF is flatter than the v7c recipe assumes).
- **DEF targets exclude effects.** Before the grade is fitted, every pixel a `defFlipbook` layer
  claims is removed from the DEF body. The DEF frames where any dynamic light exceeds its floor are
  also dropped, and every dynamic light is held at its floor (`effectLight.floor`, default 0) on the
  frames that remain. Without floors the grade is therefore fitted to the unlit body only.
- The prebaked base colour is written at 2048 (the bake size), whatever the source image size.

### Regions (`lighting.regions`)

A whole-unit grade cannot serve two materials that the DEF treats differently. On the oceanid it
washes the gold to cream, and v6m's albedo-chroma classes cannot separate white-grey water from
silver hair. Regions generalise v6m: each region is a texture weight paired with its own DEF region.

```jsonc
"defSegmenter": {"module": "tools/homm3_vfx/oceanid_water_motion.py", "function": "segment"},
"regions": [
  {"name": "column", "mask": {"vertexColor": {"channel": "r", "threshold": 0.5}},
   "target": "defPalette", "defRegion": "column", "knobs": {"skyCompensation": true}},
  {"name": "skin", "mask": {"bones": ["Spine*", "*Arm*"]}, "target": "grade", "defRegion": "torso",
   "knobs": {"toeMax": 0.08}}
]
```

- **`mask`** is exactly one of the following:
  - `{"maskPath": "<UV-space PNG>"}`;
  - `{"vertexColor": {"channel": "r|g|b|a", "threshold": 0..1}}`, the body mesh's `COLOR_0`;
  - `{"bones": [glob, ...]}`, the summed skin weight of the matching joints.

  Vertex masks are rasterised from the source GLB's body mesh (glTF UV), seam-padded and blurred
  1 texel. They are cached in `work/`, keyed on the geometry and the mask. Overlapping regions share
  a texel in proportion.
- **`defRegion`** is a key of the dict that `defSegmenter(rgba_uint8) -> {key: bool mask}` returns
  for a DEF frame. It is intersected with the DEF body minus the effect pixels. The segmenter is the
  unit's own repo module; the validator imports it.
- **`target: "grade"`**: the v7c raw (chroma detail, detail boost, v7 shading) is graded to the DEF
  region's L\*a\*b\* percentiles, using the unit-level grade model and bounds, on the region's
  texels only (weight > 0.8). The only knob is `toeMax`.
- **`target: "defPalette"`**: a rank map. The region's texels, ordered by a score, take the DEF
  region's colours ordered by luma, as `pal^gamma * s * sky^-alpha`, and `(s, alpha, gamma)` is
  fitted. The score is the raw albedo luminance, or cell 0 of the `uvAtlas` layer that grades its
  cells through this region; the static base colour is then that layer's cell 0. The only knob is
  `skyCompensation` (default true).
- **The rest** (texels with total region weight below 0.2, DEF pixels outside every region) keeps
  the unit-level `mode`, fitted on the rest only. The textures are composed by weight. The run
  fails when fewer than 200 DEF pixels are left for the rest, or for a region.
- `metrics.json` `lighting.regions` records each region's fit. Region bound hits are prefixed with
  `region:<name>`.

### Metal (`lighting.metal`, opt-in; `tools/homm3_unit_look/metal.py`)

Hex/Lit has no specular and no emission, so a metal reads as shiny only if its reflection is baked into
the base colour. The bake has to hold as the unit yaws, so it depends on the rest-pose normal's elevation
and on convexity only, never on yaw. It runs after the unit-level grade and any regions, and before
`bakedGlow`, on the metal texels only:

```jsonc
"metal": {
  "mask": {"source": "meshyMetallic", "metallic": [0.45, 0.8]},   // or {"source": "materialClass", "materialClass": "gold"} (v6m)
  "defRegion": {"class": "gold", "close": 2},    // or {"window": {"chroma"|"chromaMax"|"hue"|"lightness": ...}}
                                                 // or {"projected": true, "erode": 1, "close": 2}
  "normalDetail": 0.5                            // 0 = geometric normal, 1 = normal-map normal
}
```

- **Mask.** `meshyMetallic` reads the source GLB's own glTF `metallicRoughness` texture, which Meshy bakes
  in the base colour's UV space (B = metallic, G = roughness; an optional `roughnessMax` [lo, hi] gates on
  G). The mask is a smoothstep over `metallic`, blurred by `blur` texels, and it fails closed when the body
  material has no metallicRoughness texture. On the Titan the map is bimodal: 71% of UV texels are above
  0.5, and it covers 96.5% of the gold-class texels against 0.1-0.2% of the red and blue classes. Some units
  have a useless map (h3_behemoth: every texel 0.0); those need `materialClass`.
- **Reflection.** `env = sigmoid((n_z - horizon) / width)` gives sky above a sharp horizon and dark ground
  below it. It is lifted by `edge * convexity` (pointiness), and the log-luminance gain is
  `strength * (e - median) + bias`. Chroma is scaled by `(1 - hiDesat*env^2) * (1 + loSat*(1-env))`, so
  highlights go pale and the ground side goes deep. The seven parameters are fitted (Nelder-Mead, bounds
  in `metal.PARAM_BOUNDS`) so that the relit metal texels' L\*/C\* percentiles match the DEF metal region:
  `defRegion` pixels of the DEF body minus effects, closed by `close` iterations so that pale highlights
  and deep shadows inside the metal count too. `projected` takes the DEF body pixels under the mesh's own
  metal mask projected into the same view (the pixels `regionLhist` measures), eroded by `erode` so
  silhouette slop stays out; it needs no per-unit colour window and is the default for the roster rollout. `params` pins values, and `fit: false` uses them as given.
  Bound hits are reported as `metal:<param>`.
- **Metric.** `metrics.json` `lighting.fit.metal.regionLhist` gives the L-hist distance, per review view,
  between the relit mesh pixels whose mask is above 0.5 and the DEF metal region, both without the metal
  (`before`) and with it (`after`). Delivery rule: the metal region must improve (the validator fails an
  applied unit whose `after` is not below its `before`) and the look must still beat raw (look.py's
  regression refusal). The body L-hist against the unmetalled grade is recorded but not a gate: a shine
  legitimately widens the lightness distribution, and the user accepted h3_crusader by eye on 2026-09-25
  although its lab body metric was worse than the unmetalled grade. `knobsSha256` covers `metal` only when the key is present, so existing stamps stay valid.
- **Status (generated artifact, offline relight; not in game).** On h3_giant_upg, measured under the same
  code: body L-hist 4.76 -> 3.06, metal region 7.68 -> 4.74, battle-facing yaw spread 3.9/4.4 -> 3.6/3.8
  (sand/grass). It is applied. On h3_crusader (steel plus gold trim, v7c) the metal region improves
  (lab: 7.02 -> 3.77) while the body metric against the unmetalled grade gets worse (3.02 -> 5.24); the
  user judged it by eye and it is applied (window region, raw 7.68 -> look 4.53, region 7.18 -> 3.79).
  h3_swordsman uses `projected` (raw 7.12 -> look 3.55, region 7.71 -> 5.68). Units are chosen by what they
  are (armour, constructs), not by the metallic map alone: Meshy marks most of some elementals, birds and
  dragons as metal. The lab is
  `tools/homm3_unit_look/metal_lab.py`, and its output is `artifacts/homm3_unit_look/_metal_lab/<unit>/`.

### Lights (the double-counting rule)

Each light the unit shows has one `id` in `lights[]`, with one treatment:

| treatment | meaning | referenced by |
|---|---|---|
| `baked` | Steady self-glow, the same in every clip and frame: phoenix fire, a bolt that glows on idle. It is baked into the base colour. | exactly one `lighting.bakedGlow[]` entry, and no `effectLight` |
| `dynamic` | It changes over time: a strike flash or a flare. A runtime point light (the ParticleSystem Lights module) plays it. | exactly one `effectLight` layer, and no `bakedGlow` |

The validator rejects an id that is used under both treatments, an id that is used without being
declared, and a declared id that is never used. A dynamic light's intensity curve is fitted as a
**rise over the prebaked body**. The baked glow is therefore part of its baseline and is never
counted twice.

`bakedGlow` entry:

```jsonc
{"lightId": "fire_steady", "materialClass": "fire", "rgb": [1.0, 0.62, 0.25], "strength": 0.4}
```

The glow is applied as an unshadowed emissive lift on the texels of that material class, after
the grade. `materialClass` names a v6m class, or a mask file given as `{"maskPath": "..."}` in UV
space.

### Layer types

Every layer has `id` (unique), `type` and a per-clip `clips` map. It may also carry an optional
`provenance` string that records where the layer came from, for example the roster inventory event.
The validator checks only that `provenance` is a string. Clip names are the GLB
animation names (`Unit_Idle`, `Unit_AttackFront`, ...). DEF frames are indices inside the DEF
group.

**Timing rule (all layers).** GLB key `i` of a clip is DEF frame `i`, sampled at `(i+1)/12` s.
An effect cell for DEF frame `i` is shown over `[(i+0.5)/12, (i+1.5)/12)`, centred on its mesh
key, with stepped (constant) keys. There is no other timing convention.

#### `defFlipbook` (first-class, the default for anything the DEF draws)

The DEF's own effect pixels are cut out of each frame, played back frame-for-frame on a
camera-facing point-filtered quad that is parented to a bone.

```jsonc
{
  "id": "strike_arc", "type": "defFlipbook",
  "def": "CGTITA.DEF",                         // optional; default = the unit's DEF from the build
  "clips": {"Unit_AttackFront": {"defGroup": 12, "frames": [0,1,2,3,4,5,6]}},
  "effectMask": {"method": "lumaSparse", "minLuma": 175, "maxNeighbours": 12},
  "bodyMask": {"subtractMeshSilhouette": true, "dilatePx": 1},
  "anchor": {"bone": "RightHand", "defOrigin": "auto", "boneTip": false},
  "texelsPerDefPx": 1,
  "render": "billboard",                       // "billboard" (default) | "groundPlane" (puddles, scorch, death pools)
                                               // | "unitPlane" / "trail" (opt-in, directional effects; see below)
  "light": "bolt_flash"                        // optional: the dynamic effectLight this layer carries
}
```

- `effectMask.method` is one of:
  - `defEffects` (**the roster default**):
    `{"classes": ["electric"|"fire"|"magic"|"water"|"smoke", ...], "includeDetached": bool,
    "novelMaxIdleCount": number (optional), "minComponentPx": int (optional)}`.
    - The runner calls the ripper's API exactly: `baseline(load_unit(unit), novel_max_idle_count=...)`,
      then `frame_effects(rgba, base, classes=..., include_detached=..., min_component_px=...)["layer"]`.
      There is no second selection path.
    - Limitation: on a body that is itself fire (the fire elemental, the phoenix), the calm-group
      vote makes the effect's colours body paint. `defEffects` then sees only detached specks, so use
      a region-segmented `file` mask.
    - The vfx stage rebuilds the mask deterministically through
      `tools/homm3_vfx/def_effects.frame_effects()`, which is owned by the roster ripper.
    - A pixel is an effect when both hold:
      - it is *novel*: its quantised colour is (almost) absent from the unit's idle frames.
        `novelMaxIdleCount` overrides that threshold;
      - it is of a listed colour class. `smoke` counts only when detached.
    - `includeDetached` also adds every detached opaque component (particles, thrown things).
    - `minComponentPx` drops smaller specks.
    - It works on the extracted PNGs, so it covers fire, magic and water, which luma and palette
      rules miss, and the HotA and mod units that are not in the SoD LODs.
  - `lumaSparse`: bright pixels (`minLuma`), optionally sparse (`maxNeighbours` in a 5x5 window,
    the `def_effect_layer.py` rule) and/or blue-leaning (`blueOverRed`: B >= R + value). It reads
    the PNG, so it needs no palette.
  - `palette`: `"indices": [...]`. It reads the DEF through `h3def.py`, so the unit must be in the
    SoD LODs.
  - `paletteLuma`: palette indices, plus a luma floor.
  - `file`: `"path"` to per-frame masks `GG_FF.png`. The validator warns when the path is not in
    git, because such a spec cannot be rebuilt from a fresh clone.
  - Any method may add `"rows": [y0, y1]`: keep only the mask rows `y0 <= y - anchorY < y1`
    (integer DEF pixels, relative to the anchor pixel). Use it for a ground band or an upper-body cut.
- `bodyMask` removes pixels that the mesh already draws. `subtractMeshSilhouette` drops effect
  pixels inside the mesh render's silhouette for the same frame, so a held prop is not drawn
  twice. `rects` gives per-frame exclusion boxes in DEF pixels when the silhouette is not enough.
- **Anchoring (`anchor.defOrigin`).** The DEF pose and the mesh pose differ, so a cell cut around
  the bone's projected position lands a few to tens of pixels off. A world-space offset would break
  under yaw. Instead each cell is cut around the effect's **DEF origin** and that pixel is pinned to
  the anchor point projected through the SpriteCam, on every key.
  - `"auto"` (the default) takes the effect pixels nearest their body contact: the centroid of the
    mask pixels within 1 px of the minimum distance to the body. For `defEffects` the body is
    `frame_effects()["body"]`; otherwise it is the DEF's opaque pixels outside the mask.
  - `[x, y]` gives one explicit DEF pixel for every key.
  - `{clip: ["auto" | [x, y], ...]}` gives one entry per listed frame.

  The anchor point is the bone's head, or its tail with `anchor.boneTip: true`. At runtime the quad
  is parented to that bone, with its pivot at the cell centre. The manifest records each key's
  `defOriginPx` and `originSource`.
- **Liveness.** A flipbook that carries an `effectLight` stays alive for the whole clip wherever
  that light's curve is non-zero, even on keys where it draws no cell. For example, a breath glow is
  lit on the wind-up frames 0-2 while the breath draws on 3-11. The manifest marks this with
  `lifetime: "clip"` and `carries: [lightId]`, and it adds an empty (`sheet: null`) entry for a clip
  where the light shines but the flipbook draws nothing. Otherwise `lifetime` is `"cells"`. There is
  no separate carrier type.
- Fixed rendering rules: `Sprites/Default`, point filter, no mips, alpha blend (never additive)
  and a texture-sheet grid. The quad is a view-aligned billboard, or a ground plane with
  `render: "groundPlane"`; directional effects opt into `unitPlane` / `trail` (next section). The CPU review composites both the same way, because the DEF pixels are
  already the sprite-camera view.
- The layer is generated from the DEF, so it needs no art. Frames not listed in `frames` show
  nothing.

#### Depth-aware renders: `unitPlane` and `trail` (opt-in on a `defFlipbook`)

A billboard is right for an effect that looks the same from any angle (a glow, sparkles, a puff, a
bolt at a point). It is wrong for a *directional* effect drawn for the single HoMM3 sprite facing:
a blast thrown forward, a breath jet, a beam, a blade sweep. With the unit turned, a billboarded jet
still leaves the hand towards the same side of the screen. For example, on `battle_faces_left` the
zealot's blast lands behind its back. Owner: `tools/homm3_unit_look/vfx_depth.py`. Layers that do
not opt in are byte-for-byte unchanged.

```jsonc
{"id": "cast_melee", "type": "defFlipbook", ..., "render": "unitPlane",
 "unitPlane": {"fade": [0.10, 0.30], "isoMinOffsetPx": 4, "isoOffsetRadius": 0.6, "isoMaxAspect": 2.0, "attachPx": 3}}  // optional
{"id": "sword_trail", "type": "defFlipbook", ..., "render": "trail",
 "trail": {"bone": "RightHand", "boneTip": false, "reach": "auto", "widthPx": "auto", "historyKeys": 3}} // block optional
```

**`unitPlane`: splitting the effect.** Each key's effect mask is split into pieces: 8-connected
components after a 2 px dilation, the `def_effects` grouping rule. Each piece is classified relative
to the key's DEF origin, which is the pixel pinned to the anchor bone:

- `isotropic`: round and on the origin, meaning centroid offset <= max(`isoMinOffsetPx`,
  `isoOffsetRadius` x RMS radius) and PCA aspect < `isoMaxAspect`. It stays view-facing in the
  ordinary `sheet`, as before.
- `card`: elongated (aspect >= `isoMaxAspect`: a jet, beam or streak), or attached to the emitter (a
  pixel within `attachPx`, default 3, of the origin). It is drawn on the unit-frame **card**
  (`unitPlane.sheet`), so it stays attached to the mouth or hand.
- `displaced`: round, detached and away from the origin (a blast cloud thrown forward). Its
  *position* is directional but its shape is not. So it is a view-facing cell
  (`unitPlane.displaced.sheet`, cut around the displaced pieces' centroid) whose pivot is offset in
  the unit's frame.

A layer whose pieces are all isotropic is refused ("use billboard"). The zealot's `cast_bolt` is
refused for this reason: its blast sits on the hand.

**`unitPlane`: the cards.** Both cards are fixed in the unit root's frame, not the bone's, and pass
through the anchor point.

- The **sagittal** card is spanned by the unit's front and world up. The DEF pixels are unprojected
  onto it along the sprite camera's rays, which has two consequences:
  - from the sprite camera it is pixel-identical to the billboard, so the review and its metrics
    are unchanged;
  - from the mirrored battle facing it shows the mirrored DEF, which is what HoMM3 shows.
- The **cross** card is the sagittal card turned 90 degrees about the emission axis (the unit's
  front through the anchor). DEF-up maps to the unit's left. It shows the effect from head-on or
  tail-on, where the sagittal card is edge-on.

Weights: `w = smoothstep(fade[0], fade[1], |left . viewDir|)` for the sagittal card and `1 - w` for
the cross card. Only one card shows at a time, so there is no double exposure. The build refuses a
layer whose sagittal weight from the sprite camera is below 1.

Note that the unprojection carries the sprite camera's foreshortening. The retarget SpriteCam sits
25 degrees off the unit's front, so one DEF pixel along screen-x is about 2.4 / pxPerUnit along the
front. An effect therefore lands further forward in 3D than its screen distance suggests. This is
geometrically consistent with the DEF view and is recorded as a property of the method, not tuned
away.

**`trail`.** A blade sweep becomes a ribbon strip between two rails that follow the weapon through
the clip:

- The rails are `bonePoint + boneDir * r`, with `r` running from `reach - width` (inner) to `reach`
  (outer). `bonePoint` is the head, or the tail with `boneTip`. `bone` defaults to the anchor bone.
- `reach: "auto"` is the 90th percentile of the effect pixels' distance from the anchor pixel,
  divided by pxPerUnit. `widthPx: "auto"` is the 10th-90th percentile band of that distance.
- The strip covers the last `historyKeys` keys.
- The ribbon texture (`ramp`, 8 rows x 4·historyKeys columns) is coloured from the DEF arc's own
  pixels. Rows are radial bands, inner to outer, holding the mean colour and coverage of the listed
  frames' effect pixels. Columns are age, and alpha fades from newest to oldest.
- The flipbook sheet stays in the manifest as `sourceSheet`, as the provenance of the ramp. It is
  not drawn.

**Manifest and runtime contract.** Nothing consumes this yet; this is the format a runtime must
implement.

- Every vector and position is in unit-root components `[front, left, up]`, where `front` is the
  unit's facing, `left = up x front` and `up` is world up. They turn with the unit root. Timing and
  keys follow the flipbook timing rule.
- **`render: "unitPlane"`** clip entries keep `sheet` (isotropic pieces, view-facing, `billboard:
  "view"`; `null` when none) and add a `unitPlane` block:
  - `sheet` is the card-piece sheet (or `null`). It shares the flipbook's grid, cell and pivot.
  - Draw it twice per key, as two quads:
    - Each quad is centred at the anchor point, with corner offsets `(x - w/2) * uPerCellPx +
      (y - h/2) * vPerCellPxDown` per `cards.sagittal` / `cards.cross`.
    - Alpha is multiplied by the card weight, computed each frame from the view direction and
      `cards.*.normal` (turned by the unit root).
    - The shading rules are unchanged: `Sprites/Default`, point filter, alpha blend, and no
      backface cull, so the card is visible from both sides.
  - `displaced` (or `null`) holds a view-facing sheet with its own `cellPx` / `sizeUnits`, plus a
    per-key `offset.sagittal` / `offset.cross`. The quad's centre is `anchor + w*offset.sagittal +
    (1-w)*offset.cross`. `offsetPx` is the same offset in sprite pixels.
  - `pieces`, `classifier` and `spriteView` (sagittal weight 1 and unprojection error) are the
    audit trail.
- **`render: "trail"`** clip entries have no `sheet`. They carry a `trail` block with `ramp`,
  `bone`, `point`, `reachUnits`, `widthUnits`, `historyKeys` and per-key baked `keys[].inner` /
  `.outer` rails with `visible`.
  - The runtime samples the live bone each frame, keeps `historyKeys / 12` s of rail history while
    `visible`, and builds a two-sided strip.
  - The strip's UV is u = age (0 newest) and v = inner to outer.
  - The baked rails are the offline reference that the CPU review draws.

**Review and proof.** The CPU review composites every part from the sprite camera, which is exact
for `unitPlane` and a projected ribbon for `trail`. The facings are proven by
`tools/homm3_unit_look/facing_proof.py <unit>`:

- It renders the attack pose from the four battle facings through `facing_proof_blender.py`
  (Workbench, one gpuslot launch).
- It writes `artifacts/homm3_unit_look/<unit>/facing_proof/facing_before_after.png`, with BEFORE as
  the billboard and AFTER as the layer's render.
- Tests: `tools/homm3_unit_look/test_vfx_depth.py`.
- Proof tier: generated artifact (offline render + CPU composite). No runtime consumes the format,
  so nothing is proven in game.

#### `uvAtlas` (texture animation on the body)

Stepped atlas cells on the unit's own `SkinnedMeshRenderer`, driven through per-clip
`material._MainTex_ST` curves (the oceanid water design).

```jsonc
{"id": "water_flow", "type": "uvAtlas",
 "regions": ["column", "foam"],                // defPalette regions the cells are graded through
 "source": {"scores": "<npz: 'scores' (cells, H, W) in [0,1]>", "generator": "<script that writes it>"},
 "gutterPx": 32,
 "clips": {"Unit_Idle": [0,1,2,3,4,5,6,7]}}   // one cell index per DEF frame
```

The atlas cells **are** base colour, so the runner grades them itself, through the same lighting
and regions as the static base colour. There is no path for a pre-graded atlas.

Oceanid: the scores source is `look/corkscrew_scores.npz`, written by
`tools/homm3_vfx/oceanid_corkscrew_scores.py`, whose pattern rotates with the retarget's
`cove_corkscrew` whirl. It replaces the lab's `flow2_scores.npz`, which scrolled straight down. The
scores and the retarget knobs are a pair: change `coveCorkscrew.period` and the generator's `LOOP`
and rotation together (see `docs/homm3_vfx_experiments.md`, "Phase 4: corkscrew water").

- The unit's own generator supplies only **un-lit scores**: per-texel values in [0,1], one map per
  cell, over the whole UV.
- Cell k is the look texture with each named `defPalette` region re-ranked by cell k's scores:
  `tex + w * (palette(scores_k) - palette(scores_0))`.
- The cells go on a grid of `cellPx` (the scores' resolution) with edge-padded gutters. The
  manifest records the `cellST` scale/offset per cell (Unity, v up) for `_MainTex_ST`.
- The static base colour is cell 0.
- `atlas` / `cells` keys are ignored, with a warning. A layer that has neither `source` nor
  `regions` is "pending": it passes the validator with a warning, and the runner fails closed on it.

#### `particles` (procedural or native-style particles)

```jsonc
{"id": "embers", "type": "particles", "prefab": "<Assets/... .prefab>",
 "anchor": {"bone": "Spine2"}, "clips": {"Unit_Idle": {"startDefFrame": 0}}}
```

The CPU review cannot simulate these particles; it draws the anchor and marks the frames. Their
colour match needs a Unity spot check (see Review).

#### `volumetricFire` (opt-in; DEF-ripped fire as a particle volume on the body, `tools/homm3_unit_look/volfire.py`)

For a unit whose DEF shows persistent body fire (phoenix, fire elemental, efreeti, efreet sultan, efreet sufi). Hex/Lit has no emission,
so no base colour can make a body read as burning, and a `defFlipbook` is one view of a 2D sprite. This layer
puts the DEF's own flames on the 3D surface as native Unity particles, so it reads from any facing.

```jsonc
{"id": "fire_volume", "type": "volumetricFire",
 "source": {"def": "CPHX.DEF", "defGroup": 2, "frames": [0,1,2,3,4,5,6,7],   // a looping group, fire boiling in place
            "fireMask": {"minLuma": 100, "minWarmth": 40}},                   // fire px: opaque, luma >= minLuma, R-B >= minWarmth
 "emitter": {"excludeBones": ["*Leg", "*Foot", "*ToeBase"]},  // or {"bones": [globs]}, {"region": <lighting region>},
                                                              // {"maskPath": <UV png>}, {} = the whole body; "threshold" 0.5
 "systems": {                                                 // any non-empty subset
   "tongues": {"windows": 24, "cellPx": [16, 40], "baseAt": 0.8, "coverage": 1.5,
               "heightRange": [0.35, 1.0], "minUp": 0.0, "lifetimeDefFrames": [4, 8], "riseDefPxPerFrame": 1.0},
   "body":    {"windows": 24, "cellPx": [12, 22], "coverage": 0.35, "heightRange": [0.25, 1.0],
               "lifetimeDefFrames": [3, 6], "riseDefPxPerFrame": 0.5},
   "embers":  {"perSecond": 24, "heightRange": [0.5, 1.0], "lifetimeDefFrames": [6, 12], "riseDefPxPerFrame": 3.0}},
 "anchor": {"bone": "Spine2"},                      // the systems' parent (they simulate in World space)
 "light": "body_fire",                              // optional: a declared light this layer carries (effectLight.carrier may name it)
 "clips": {"Unit_Idle": 1.0, "Unit_Death": [1, 1, 1, 0.4, 0, 0, 0]},   // emission multiplier, scalar or one per DEF key
 "clearAt": {"Unit_Death": 5}}                      // optional: remove every live particle when that key's window opens
```

- **Source.** `def` names a DEF in the game LODs. Omit it to use the unit's own frames, the ones its retarget was
  built from (`volfire.unit_frame_source`). That is the LOD DEF when the LODs hold it, otherwise the extracted
  `<name>.dir` of `GG_FF.png` frames (alt / HotA packs such as `lvl6Alt`). The manifest records which one was used
  (`source.def` or `source.framesDir`).
- **Texture.** The DEF's looping group is cut into fixed windows. Each window is the same DEF position in every
  listed frame, so each is an N-frame flipbook of the DEF's own flicker at that spot. There are three banks:
  - `tongues`: windows hung from the silhouette's upper edge, taken from the main component only so stray specks
    do not lift them. They are clipped to a flame lens (pointed top, rounded bottom) and bottom-padded so the
    cell centre is the flame base at `baseAt`.
  - `body`: the same lens, cut inside the fire (the boil).
  - `embers`: the detached specks, single cells.

  An empty bank fails closed. The fire elemental idle has no detached specks, so it has no `embers`.
- **Volume.** Each system emits from the skinned body triangles the emitter selects. Emitter rules:
  - `bones` / `excludeBones`: the mean over the triangle's vertices of (skin weight on the matching joints minus the
    weight on the excluded ones) is at least `threshold`.
  - `region` / `maskPath`: the triangle's UV centroid, nearest texel of the saved mask, is at least `threshold`.
  - Then the system's `heightRange` (the centroid's rest-pose height as a fraction of the body's) and `minUp` (the
    rest vertex normal's up component).

  Particles are camera-facing, unlit, alpha-blended, point-filtered billboards that depth-test against the body.
  The rim therefore shows tongues standing off the silhouette, and the facing side shows boiling flame, from any
  facing. **Use a bones emitter** when the mesh may be rebuilt: it is keyed by joint names, so it carries to a new
  mesh with the same skeleton. A UV mask is tied to one mesh's UVs.
- **Timing.** Each particle steps through its window at 12 fps from a random phase, which is the DEF's own redraw
  rate. Births are continuous (`rateOverTime`), multiplied per key by the clip's multiplier; `clearAt` kills the
  fire at a `hideMesh` key.
- **Density.** `coverage` is the fraction of the emitter's visible projected area that the live sprites cover.
  - Expected live count = `coverage * A / (2 s)`, where A is the emitter's rest area and s is the mean opaque
    sprite area.
  - Rate = expected live count / mean lifetime.
  - `embers` use `perSecond`.
- **Manifest entry** (`type: volumetricFire`). It is what a builder needs to make one `ParticleSystem` per system,
  with nothing left to derive:
  - `emitter`: the selection rule, `restCentroidYRange`, the mask asset if any, and the triangle counts;
  - per system: `sheet`, `tilesX` (frames), `tilesY` (windows), `cellPx`, `sizeWorld`, `lifetimeS`,
    `ratePerSecond`, `riseWorldPerS`, `spreadWorldPerS`, `normalOffsetWorld`, `emitterFilter`,
    `emitterTriangles`;
  - `clips` (per-key multipliers) and `clearAtKey`;
  - `unity`: the component recipe. It is a SkinnedMeshRenderer shape over an emitter-only skinned submesh with
    `forceRenderingOff`; World space; Billboard/View with Distance sorting; Sprites/Default; a Grid sheet with a
    SingleRow random row, FPS 12 and a random start frame. The per-key multiplier is a stepped curve on
    `EmissionModule.rateOverTime.scalar`.
- **Review.** The CPU review does not simulate it. The Unity preview is
  `python tools/homm3_vfx/volfire_unity_lab.py <unit> [--fire-from <unit>]`, run through unitylock. It writes
  DEF | look | look+fire sheets and videos per clip, plus a turntable, to
  `artifacts/homm3_vfx_experiments/volfire/<unit>/`. It also fails closed when Unity's emitter triangle count per
  system differs from `volfire.py`'s by more than 3%.
- **Which units.** Pick by the DEF, not the name. `python tools/homm3_unit_look/volfire_survey.py` reads every
  spec's idle group and reports `defFireFraction` (fireMask px / opaque px) and `flickerFraction` (fire px whose
  colour changes between consecutive idle frames). Real body fire flickers in place, whereas warm paint, glowing
  cracks and wing motion do not pass both tests. The flame units flicker at 0.31-0.42: phoenix, efreet sufi, fire
  elemental, efreet sultan, efreeti. The plasma elemental (0.36) is electric arcs. The elemental gargoyle, seraph
  and dragon fly (0.14-0.30) flicker from motion. None of these three has flames.
- **Per-unit intensity (calibration).** `volfire_unity_lab.py` writes `calibration.json`. It applies the layer's
  own fireMask to the idle DEF (`defFire`, `defBands` top/middle/bottom thirds), to the lab render without
  particles (`lookFire`) and to the render with them (`renderedFire`, `renderedBands`). It also writes
  `particleCover` (the share of the silhouette the particles change) and `turntableFire` (the mean over yaws).
  Fit the emitter so `renderedBands` follows `defBands`. Then set coverage so the particle cover is proportional
  to the DEF's fire and `renderedFire` lands near `defFire`. Where the look alone already reaches `defFire` (a
  yellow body, or the new fire-elemental mesh), keep the particle cover low. Lab values (Unity-editor render,
  not in game):

  | unit | defFire | defBands | lookFire | renderedFire | particleCover | rendered/DEF | emitter, coverage |
  |---|---|---|---|---|---|---|---|
  | h3_phoenix | 0.870 | .15/.46/.39 | 0.950 | 0.967 | 0.44 | 1.11 | all but legs; tongues 1.5, body 0.35, embers |
  | h3_fire_elemental (mesh 4fbbceaf6e) | 0.913 | .24/.39/.37 | 0.785 | 0.845 | 0.25 | 0.93 | all but feet; tongues 0.6, body 0.2 |
  | h3_efreet_sufi | 0.613 | .15/.51/.34 | 0.660 | 0.754 | 0.27 | 1.23 | lower body to 0.62 h; tongues 0.6, body 0.3 |
  | h3_efreeti | 0.441 | .02/.51/.47 | 0.355 | 0.552 | 0.29 | 1.25 | lower body to 0.55 h; tongues 0.5, body 0.3 |
  | h3_efreet_sultan (mesh fe7efe305f) | 0.477 | .11/.45/.44 | 0.583 | 0.640 | 0.18 | 1.34 | lower body to 0.55 h; tongues 0.5, body 0.3 |

  The efreets' ratios are above 1 because their tail meshes are already warm-coloured. The sultan's regenerated tail
  is sculpted flame (lookFire 0.58 is already above its defFire), so its particle cover is the lowest. The torso stays clear,
  matching the DEF's top band. The partial-fire units exclude bones rather than use the whole body: arms,
  shoulders, `Spine1` / `Spine2`, neck and head are excluded, with a height cap. Their death multipliers hand
  over to the death flipbook at the key where it starts.
- **Not given the layer (by DEF):**
  - `h3_hell_hound`, `h3_cerberus`, `h3_fire_hound`: idle fire 0.006-0.016 and flicker <= 0.002. There is no
    mane of fire in the DEF; their fire is the attack breath (`defFlipbook`).
  - `h3_magma_elemental`, `h3_lava_elemental`: flicker 0.012. The glow is static cracks in the rock, not flame,
    so it belongs to the texture / flow lane.
- **Proof tier: Unity-editor render (lab).** Nothing is in game: no builder or runtime consumes the entry yet,
  and the def_retarget delivery lane defers the layer (`deferLayers`); the floor light itself does ship. The body is drawn by the lab Hex/Lit replica with
  the floor light held; the fire is a native ParticleSystem with Sprites/Default. Sprites/Default availability in
  the game's shipped bundles, sorting against other units, and the particle cost with many stacks are all
  unmeasured.

#### `effectLight` (dynamic point light)

It is carried by a particle layer's Lights module, the native OE pattern: ratio 1, maxLights 1,
and a template Point light.

```jsonc
{
  "id": "bolt_flash_light", "type": "effectLight", "lightId": "bolt_flash",
  "carrier": "strike_arc",
  "anchor": {"bone": "RightHand", "towardLayerCentroid": 0.5, "towardCameraU": 0.45},
  "rgb": [1.0, 0.96, 0.86], "range": 3.0,
  "intensity": {"Unit_AttackFront": [0, 0.39, 1.79, 1.34, 0.81, 0.48, 0.25]},
  "intensitySource": "fitted"                  // "fitted" (by the runner against the DEF glow rise) | "authored"
}
```

The `intensity` list has one value per DEF frame of that clip, stepped. `fitted` values are
rewritten by the runner. The fitted value is the intensity whose mean-L\* rise over the same key
lit at the floor equals the DEF body's rise over the clip's first key, less the rise that the pose
change alone gives the unlit mesh (key i against key 0).

**Floors.** `"floor": number | {clip: number}` (optional, default 0) is a steady minimum for an
always-on light, such as a body that is fire. A `bakedGlow` lift cannot make a self-lit body
read. (Hex/Lit does have an emission variant, `HEX_EMISSION_MAP_ENABLED` with `_EmissionTex`,
`_EmissionColor`, `_EmissionMinPower`, `_EmissionBlinkSpeed`, `_EmissionBlinkPower`, found by a
static read of the shader's keyword and property tables on 2026-09-26; its math was not read and no
lane uses it. A floor light also lights neighbours and the ground, which emission would not.) Rules:

- A scalar floor holds in every built clip; an object holds only in the clips it names.
- In a clip without an `intensity` curve, the light holds the floor constantly.
- The grade is fitted with every light held at its floor. Only frames where a light **exceeds** its
  floor leave the fit.
- Fitted curves never go below the floor. The validator enforces `0 <= floor <= min(curve)` per
  clip.
- A floor is still a dynamic light (it is not in the albedo), so the double-count rule is
  unchanged.
- `apply` delivers a floor-light unit (the refusal was lifted 2026-09-26 once the def_retarget
  delivery lane held floors). Its base colour is graded to be seen under that light, so the stamp
  lists the lights in `floorLights`, and `ship_def_retarget_slice.py` refuses a unit whose plan
  does not hold every one of them at a floor above 0. Any other lane that builds from the shared
  delivered GLB without the lights would show the body too dark.
- In the def_retarget delivery lane, a clip whose rows are all floor (`source: "floor"`) gets no
  curve; the builder holds the floor there (enabled, intensity = floor, placed where the first
  curve's first key puts it, in that clip's first pose). In a curve clip the light rests at the
  floor before its first window and after its last one. Only a scalar floor is delivered; a
  per-clip floor is refused by the planner.

#### `event` (a discrete per-clip event)

```jsonc
{"id": "throw", "type": "event", "clip": "Unit_ShootFront", "defFrame": 6,
 "action": "missile", "missile": {"def": "CPRGTIX.DEF", "selectBy": "angle"}}
```

`action` is one of:

- `missile`;
- `activate`, with a `"layer"` to switch on;
- `deactivate`;
- `mark`, a named timing marker for runtime code;
- `hideMesh` / `showMesh`, with an optional `"renderers": [<GLB mesh node name>, ...]`. It defaults
  to all of the unit's SkinnedMeshRenderers, rubble included. The validator rejects a name that is
  not a mesh node of the GLB. Example: the phoenix hides its body when the DEF ash pile takes over
  at death frame 5. The CPU review hides the mesh when all renderers are hidden, and notes a subset
  without drawing it.

## Entry point contract

```
python tools/homm3_unit_look/look.py <unit> [<unit> ...] [--stages STAGES] [--force] [--bake-timeout SECONDS]
python tools/homm3_unit_look/look.py --faction custom_factions/homm3_<faction>.json [--stages ...]
python tools/homm3_unit_look/look.py --summary          # regenerate the roster summary only
python tools/homm3_unit_look/look.py <unit ...> --stages fit,vfx,review --try-modes   # fit both modes, change nothing
```

`--try-modes` fits and reviews v7c and v6m in turn. It writes `try_<mode>_{metrics.json,
basecolor.png,review_sheet.png}` and prints which mode is closer. It never edits the spec, never
writes fitted intensities and never applies. Afterwards, set `mode` in the spec and rerun
`fit,vfx,review`. Each try records the GLB it measured (`source.glbSha256`).

**rawAccepted.** When every mode loses to the raw base colour, `apply` refuses and the unit has
no stamp, so it cannot freeze. The explicit alternative, fail-closed:

```
python tools/homm3_unit_look/look.py <unit> --try-modes
python tools/homm3_unit_look/look.py <unit> --stages bake,fit,vfx,review   # VFX from the spec's own mode
python tools/homm3_unit_look/look.py <unit> --accept-raw "<reason>"
```

`--accept-raw` refuses unless, for every mode in `spec.MODES`, `try_<mode>_metrics.json` was
measured on this GLB with the current knobs, all tries agree on the raw body L-hist, and the raw is
strictly below every mode's body L-hist. It delivers the un-prebaked GLB (restoring it from
`_superseded_do_not_use/` if a look had been applied). It writes `raw_basecolor.png` (the GLB's own
body image bytes) and a `kind: "rawAccepted"` stamp carrying the reason, the raw L-hist and each
mode tried with its L-hist and metrics sha. `spec.raw_accepted_errors` is the one rule; both the
validator and `freeze_slice.py` apply it. `freeze_slice.py` freezes `raw_basecolor.png` as the
albedo, refuses a rawAccepted unit that carries a uvAtlas layer, and still refuses a unit with no
stamp. A rebuilt GLB invalidates the stamp; rerun all three steps.
A JPEG body image (the basecolor lane ships PNG only) is re-encoded as a PNG with identical decoded pixels; that
image is the only change to the delivered GLB. The stamp's `rawTranscode` records the source image sha, the PNG
sha and the decoded-pixel sha, and the original bytes are kept as `raw_source_image.jpg`. The validator
re-decodes both files and compares their pixel shas. First used on h3_boar_rider on 2026-09-27; that is
generated-artifact proof only.
Proof: source/static validated (refusal paths exercised); no unit accepted yet at the time of writing.

`STAGES` is a comma list from `bake,fit,vfx,review,apply` (the default is all five, in that
order). Each unit runs independently. A run writes only under `artifacts/homm3_unit_look/<unit>/`
and never writes a shared file, so any number of faction agents can run at once. The one
exception is `--summary`, which rebuilds `artifacts/homm3_unit_look/ROSTER_SUMMARY.{json,md}`
from the per-unit folders (write to a temp file, then rename).

| stage | does | heavy? |
|---|---|---|
| `bake` | Blender, three launches. Both use the build's `.blend`, and neither ever saves it. `bake_terms.py` bakes the standard terms, then the extras (`ao_short,thickness,pointiness,nrm_geo`, weld 1e-4). `render_passes.py` renders the fit and review frames at the SpriteCam (supersample 2, with `--position --bones all --conds sand,grass`) and the four battle facings. The bake is **resumable** and the terms are **content-keyed**: `work/terms_key.json` (schema v2: `bake_terms.py --input-hash`, a ~3 s CPU-only launch hashing what the terms read from the `.blend` -- the chosen mesh's evaluated rest geometry, corner normals, UVs, topology, unevaluated data, modifier stack, world matrix, armature rest, normal-map bytes and the Blender version -- plus front, size, samples, weld, term lists and the `bake_terms.py` sha) is written before baking, and a rerun keeps every `terms/<term>.npz` that is complete under a matching key and bakes only the missing ones (`bake_terms.py --only`). The `.blend`'s own bytes change on every save, so before 2026-10-05 every rebuild re-baked identical terms (~45 s); a rebuild that leaves the rest mesh and normal map alone now reuses them (measured h3_peasant: bake stage 74 s -> 20 s; a fresh bake of the same `.blend` already differs from itself by one float16 ulp at ~0.03% of texels on the GPU, and a cache hit is within that noise). A changed key drops the terms; `work/views_key.json` (adds the `.blend` sha, base colour, frames, supersample, anchor bones, conds and the `render_passes.py` sha) does the same for `views/`. `work/bake_key.json` marks a finished bake; `--force` wipes `work/` (fleet_rebuild no longer passes it). | Blender, GPU slot + memgate |
| `fit` | numpy. It fits the spec's `lighting.mode` against the DEF (with effects excluded), applies `bakedGlow`, and writes `basecolor.png` and `metrics.json` (with `boundHits`). | CPU |
| `vfx` | It builds every layer's assets into `vfx/` (flipbook sheets and `cells.json`, atlas cells prebaked, fitted light curves) plus `vfx/vfx_manifest.json` (every asset with its sha256). | CPU |
| `review` | The **CPU review, the default.** Relit sprite frames under Hex/Lit (sun + ambient + dynamic point-light term), with the flipbooks composited at the projected anchors, compared with the DEF frames. It writes `review_sheet.png` (DEF, raw, look, look + VFX) and adds the with-effects metrics to `metrics.json`. A key whose mesh renders empty (`meshEmpty`, cause `hideMesh` / `rigCollapsed` for the retarget sink / `unexplained`, which is also a summary warning) or whose DEF body reference is empty (`bodyEmpty`, hideMesh + DEF remains) is recorded, left out of the raw/look body means (`summary.excludedFromBody`) and still composited and measured with effects; if every key is excluded the review fails closed (exit 4). | CPU |
| `apply` | Delivery (below), then the validator for this unit. It refuses (exit 5) in any of these cases: `basecolor.png` was not fitted from the current lighting spec (`knobsSha256`, including after `--try-modes`); the VFX was not built from the current spec (`specSha256`); the look is further from the DEF than the raw base colour (body L-hist, a regression); or a light has a floor (see Floors). | CPU |

Every Blender launch first takes a machine-wide GPU slot (`tools/homm3_unit_look/gpuslot.py`,
mirroring unitylock: atomic mkdir of `artifacts/homm3_unit_look/_gpu_slots/slot_<i>`, dead-PID
slots broken, released in `finally`), then runs `python tools/homm3_def_retarget/memgate.py`
inside the slot. At most `HOMM3_BLENDER_SLOTS` (default 3) look.py bakes run at once; a waiter
gives up after `HOMM3_BLENDER_SLOT_WAIT` minutes (default 240, exit 3). `python
tools/homm3_unit_look/gpuslot.py status` shows the holders. Each launch has a timeout of
`--bake-timeout` / `HOMM3_BAKE_TIMEOUT` seconds (default 1800); on timeout the runner logs which
term was in progress (and `LOOK TIMEOUT ...` in `work/bake.log`), exits 4, and a rerun resumes from
the finished terms. Faction agents need change nothing. **Unity is spot-check only**, never a default stage. Any Unity
launch goes through `python tools/homm3_vfx/unitylock.py run -- <cmd>`, which serialises Unity
across agents and runs memgate.

Exit codes: 0 if every requested unit passed. Otherwise 2 is a spec error, 3 a missing input
(no build, no DEF, an ambiguous front), 4 a fit or review failure, and 5 a delivery or
validator failure. A failure in one unit does not stop the other units. The run ends with one
status line per unit.

**Disk.** Terms are stored as lossless compressed `terms/<term>.npz` (the identical float16 array,
about 4x smaller; `prebake_lab.load_terms` reads both forms; fit output shown bit-identical). Bake
and fit refuse to start with exit 6 ("disk low") when the artifact drive has less than
`HOMM3_MIN_FREE_GB` (default 2) free. After a validated apply the runner prunes the regenerable
bulk of `work/` (`views/`, `look_tex_lin.npy`) and writes `work/pruned.json`; `terms/` (about 85 MB a unit,
compressed) is kept since 2026-10-05 so the next rebuild reuses it. The stamp, the validator and
`--require-delivered` never read those files, and a later rerun simply rebakes what is missing.
`--keep-work` opts out. Region weight caches (`work/region_<name>_<key>.npy`) are keyed on the geometry, the
mask spec and the vertex streams the mask reads (COLOR_0, or JOINTS_0 / WEIGHTS_0 + joint names) and stored as
computed, so a hit is bit-identical to a fresh computation. `look.py --prune-applied [units|--faction F|--all]`
also removes `terms/` for units
already applied, only where `validate_homm3_unit_look_contract.py --unit U --require-delivered`
passes; unapplied or failing units are never touched (their partial terms are what the bake resumes
from). `look.py --compact-terms [units|--all]` converts existing `.npy` terms in place.

### Metrics (`metrics.json`, per unit)

For each sprite view and for the with-effects composite:

- L p5/p50/p95;
- hue spread (circular, degrees);
- local contrast;
- L-histogram distance to the DEF;
- yaw (facing) spread over the four battle facings;
- `boundHits`;
- the chosen mode, and the other mode's score when both were fitted.

The roster summary ranks units by the with-effects histogram distance, worst first.

## Finish stage: look B ("vanilla philosophy")

2026-10-09 user: "The vanilla philosophy looks quite a bit better. Let's switch everything over to it next version."
`tools/homm3_unit_look/finish.py` ports the offline A/B (`V:/olden_port_work/vanilla_material_study/ab/ab_idle.py`,
study `docs/olden_era_vanilla_unit_materials.md`). B is computed from A (the lighting stage's graded base colour,
kept as `basecolor_a.png`) in texture space: fine detail x0.5, half of the regressed crevice darkening removed, a
top-lit gradient to r(L*, n_up) ~ 0.20, a grade fitted so the rendered body p50/p95 match the DEF idle body with a
soft toe holding L* >= 9, chroma lifted toward the DEF, push-pull gutters. `lighting.regions` texels keep A by
region weight; `lighting.metal` texels are masked out of the detail and top-lit steps (crevice and grade apply), so
the metal reflection still reads. Emission is not touched.

- Spec: `lighting.finish` = `"vanilla"` (default when absent) or `"none"` (A, for comparison). Only an explicit
  value enters `knobs_sha`, so existing stamps stay valid.
- Stage order: `bake, fit, finish, vfx, review, apply`. `look.py <u> --stages finish,apply` re-finishes a delivered
  look with no Blender and no views (geometry from the un-prebaked source GLB, target from the DEF idle frame).
  `finish` is in the bare `look.py <u>` default (`DEFAULT_STAGES`) since the pilot boards were approved (2026-10-09).
- `metrics.json` `lighting.finish` records `{mode, inputSha256 (A), outputSha256 (basecolor.png), codeSha256, log}`;
  apply refuses a `basecolor.png` that is not the recorded finish output, and the stamp carries `finish`. A look
  fitted before the finish existed applies as A (stamp `finish.mode` `"absent"`). A rawAccepted look is not finished.
- Torch, CUDA default; `--device cpu` reference; `test_finish.py` (properties + parity). Boards and the crush score:
  `finish_board.py` (DEF | A/B battle | A/B preview at game-distance tiles).

## Delivery and the stamp

The delivered file is the def_retarget GLB itself, at
`artifacts/homm3_def_retarget/<unit>/<unit>_def_retarget.glb`. `apply` swaps the prebaked
`basecolor.png` in as the GLB's base-colour image, and changes nothing else in the file.

- **The original is kept but not discoverable.** Before the first swap, the un-prebaked GLB is
  moved to `artifacts/homm3_unit_look/<unit>/_superseded_do_not_use/<sha12>.glb.unprebaked`.
  The extension is not `.glb`, so no `*.glb` glob or loader picks it up.
- **The stamp** is `artifacts/homm3_unit_look/<unit>/stamp.json`. It records:
  - `specSha256` (canonical JSON) and `knobsSha256`;
  - `mode` and `frontResolved`;
  - `sourceGlbSha256` (before the swap) and `geometrySha256` (body POSITION, TEXCOORD_0,
    indices);
  - `basecolorSha256` and `deliveredGlbSha256`;
  - `vfxManifestSha256`.
- **Rebuilds.** A def_retarget rebuild (articulation or floater work) writes a fresh
  un-prebaked GLB over the delivered path. Its sha then matches no stamp, and the validator
  fails. `look.py <unit> --stages apply` then:
  - reapplies the stamped texture when the geometry hash is unchanged. This is reproducible and
    needs no refit;
  - fails closed when the geometry changed, because the UVs or the mesh moved and a refit is
    needed. Run the full stages.
- **VFX delivery.** Generated assets plus `vfx_manifest.json`, pinned to the spec by the validator.
  They are consumed by the def_retarget delivery lane below.

## def_retarget delivery (in-game bundles)

The def_retarget lane now reaches the game through the native owned-skinned `homm3_bundles` path.
No parallel builder was added. It is exercised by one explicit test selection,
`tools/homm3_def_retarget_delivery/cove_slice_v1.json` (`hota_cove_oceanid` -> `h3_oceanid`,
`hota_cove_tidecaller` -> `h3_sea_witch_upg_alt`), shipped by
`tools/homm3_def_retarget_delivery/ship_def_retarget_slice.py prepare|lab|bundles|probe|deploy`.

- **Chain.** The selection freezes, by sha256, the look-delivered GLB (look's stamp), the frozen
  spec, `vfx/` and the base colour. The slice retimes the idle *from the look-delivered GLB*
  (`homm3_idle_cadence/retime_idle.py` mapping), so the prebaked colour and the 3.2x idle ship
  together. Its idle animation hash equals the roster retime's.
  - Emphasis was not applied to the cove slice: the rollout had not reached these units at freeze.
  - The correct roster order is emphasis -> look `--force` -> idle retime -> ship.
- **Lab** (`Homm3OwnedSkinnedLabBuild.DefRetarget.cs`, routed on `motionAuthority: def_retarget`):
  - imports the master as `Source/def_retarget_master.glb` with glTFast Mecanim;
  - keeps Transform and `blendShape.*` curves, refuses anything else;
  - wraps the content in `Orientation`, which the plugin needs for side facing;
  - bakes stepped VFX curves from `unity/vfx_plan.json`:
    - uvAtlas: `material._MainTex_ST.*` on the body in every clip, rest cell where a clip has none;
    - defFlipbook quads: one child quad per cell with its own UV rect, toggled by `m_Enabled`,
      because Sprites/Default ignores `_MainTex_ST`;
    - effectLight: `m_Enabled`, `m_Intensity` and `m_LocalPosition` under the anchor bone. A
      light is a plain Unity Point light, Realtime, no shadows, `renderMode = ForcePixel`
      (Important), so the native NotImportant particle lights cannot push it out of the
      per-object light list. A clip without a curve holds the floor (see Floors).
  - A later key at the same time wins, and a key at or past the clip end is dropped (the last DEF
    window closes half a frame after it and would stretch the clip).
- **Runtime** (`Homm3UnitLookVfxRuntime`, attached from `EnsureSkinnedBattleRuntimeCompatibility`
  in battle only, since the adventure-map idle passes `attachUnitLookVfx: false`; a no-op without
  `__homm3_vfx_*` nodes):
  - each LateUpdate step (facing, lights, atlas, diag) runs on its own, so one failure never
    silences the others or the diag line;
  - Animator floats are read by hash (`GetFloat(int)`). The Animator's parameter array must never
    be touched: its `AnimatorControllerParameter` array violates the Il2Cpp interop constraint on
    this game. It threw on every frame in the first battle, 2026-09-25.
  - billboards face the camera, and ground planes lie flat with their depth stretched by the
    camera elevation;
  - both mirror X when the unit faces screen-left;
  - light range scales with world scale, intensity with its square;
  - lights reach the body, neighbours and ground natively. Static read of the Hex/Lit `HexLit`
    pass (DXBC, 2026-09-26): point lights come from Unity's per-object light list
    (`unity_LightData.y`, capped at 8, and `unity_LightIndices`) into the global `HexLighting`
    cbuffer (`_PunctualLights` enable at cb2[9].x, `_PunctualLightColors`,
    `_PunctualLightPositions` with w = 1/range^2, `_PunctualLightDirections`); attenuation is
    `(1-(d^2/r^2)^2)^2 / d^2 * saturate(N.L) * colour`, with no shadow and no keyword. The native
    precedent is about 1059 unit-VFX ParticleSystems whose Lights module spawns Point lights
    (template "FlashLight", renderMode NotImportant). The pipeline asset
    (`Hex.Render.HexRenderPipelineAsset`) has no light-count setting. Whether the pipeline sets
    `_PunctualLights` in battle cannot be read statically (the IL2CPP literals are obfuscated),
    so the diag prints `punctualLights=` from `Shader.GetGlobalFloat`: 0 there with a light on
    means the global was not published that frame, or the cbuffer is bound whole.
  - the blended body ST is snapped to the nearest atlas cell, because crossfades blend ST;
  - it logs `Homm3 unit-look VFX diag` with clip, `battleSlowIdle`, blendShapeMax, bodyST,
    quadsOn, `lightsOn` / `lightMax` (lights enabled, active and above 0 now, scaled intensity),
    `lights` (count), and `lightsPeak` / `lightPeakMax` over `peakWindowClip`, the peak since the
    previous diag line. The line is written at a clip change, so without the peak a flash inside
    a clip was never seen: the first battle's `lightsOn=0` was the tidecaller, whose lights live
    only in `Unit_Defence` and the unreachable `Unit_ShootFront`.
- **Deferred layers.** A selection row may carry `deferLayers: {layerId: reason}` for a layer type
  this lane cannot deliver yet. The plan records it under `deferred`; any other unsupported layer
  still refuses, and naming a delivered layer or an unknown one refuses too. The validator
  requires a non-empty reason and that the plan's `deferred` equals the selection's.
  `deferMeshes: {nodeName: reason}` does the same for an extra skinned mesh in the master (the lab
  builder leaves that node out of the prefab and still refuses any other second skinned mesh).
  `mergeMeshes: {"<unit>_Rubble": reason}` ships a death shatter's rubble instead: prepare appends it to the
  body primitive (`merge_rubble_glb.py`, lossless, stamped; one SMR, one material, so no runtime change), the lab
  builder refuses a body mesh without the merged vertex count, and the bundle probe bakes the rubble range
  (collapsed before the Unit_Death break and in Unit_Idle, spread at the last Death key). A row moves over with
  `merge_rubble_glb.py rows <slice.json> <labSid> --write`; a re-freeze keeps it. Status 2026-10-09: tooling and
  tests only; no lab build, bundle probe or in-game check yet.
- **Conflux light slice** (`conflux_light_slice_v1.json`, 2026-09-26): the two cove units with the
  cove freeze's pins, plus `h3_fire_elemental` -> `h3_fire_elemental` (floor light 1.5, range 6,
  warm orange, rising to 1.77 on the punch; `fire_volume` deferred: volumetricFire needs its own
  emitter SkinnedMeshRenderers and the runtime's uvAtlas needs exactly one SMR) and
  `h3_storm_elemental` -> `h3_air_elemental_upg` (white-yellow flash to 7.4 on the melee). No
  emphasis on the conflux units. The fire elemental's death-shatter rubble mesh
  (`h3_fire_elemental_Rubble`) is deferred with `deferMeshes`, so its death ends in a vanish at the
  shatter frame instead of falling chunks. Proof, 2026-09-26: editor-loaded bundle probe 246 / 232 /
  198 / 169 checks, including the fire light held at 1.5 (enabled) in all eight clips without a
  curve; built, not installed.
- **Gate.** `tools/validate_homm3_def_retarget_delivery_contract.py` (`--require-installed` for the
  install), wired into the OfflineUnlockMod build as `ValidateHomm3DefRetargetDeliveryContract`.
- **Proof, 2026-09-25, cove slice:**
  - generated artifact: in both clips, blendShape curves equal the mesh's (181 / 164) and reach
    the frame weight;
  - editor-loaded bundle probe: 246 / 216 checks at DEF key times, covering one-hot blend weights,
    body ST through the MaterialPropertyBlock, flipbook cells and light intensity;
  - deployed payload proven (readback plus payload gate);
  - startup smoke proven (main menu, no exception from this code).
  - First user battle, 2026-09-25: the runtime attached, then threw on `Animator.parameters`
    every frame, so no VFX step ran. It also attached to the adventure-map visual. Both are fixed
    in source and the build (not yet installed).
  - **Not yet proven** at runtime:
    - a battle instance;
    - whether the game's Animator writes the ST block that survives the Hex/Lit restamp;
    - the `battleSlowIdle` value;
    - flipbook and light visibility.
  - The unit detail window shows the donor model (`twinkle_upg`), not this prefab.
- **Known gaps:**
  - The stock controller never dispatches `ShootFront`, so the tidecaller's charge flipbook and
    charge light are unreachable.
  - Blend-shape memory is per unit: 181 x 17704 vertices on the oceanid.

## Validator

`python tools/validate_homm3_unit_look_contract.py [--repo-root R] [--unit U ...] [--require-delivered]`

It fails only on real violations. A spec with no stamp yet is "not applied" and passes, so a
partial rollout never breaks the build.

- **Always, for every spec:**
  - the schema, with no unknown keys;
  - the unit name matches the file stem;
  - mode and front are valid;
  - the light treatment rule (above);
  - layer ids are unique, and every reference to a layer or light resolves;
  - `effectLight` intensity lengths equal the DEF frame count of their clip;
  - `defFlipbook` frames lie inside their DEF group;
  - for `defEffects`, `classes` is non-empty and taken from the known set, and
    `tools/homm3_vfx/def_effects.py` imports with the exact API signatures the runner calls;
  - `volumetricFire` (volfire.py): known keys; `source` loads with frames inside its DEF group;
    `fireMask` in [0, 255]; one emitter mode, with `bones` / `excludeBones` globs that match a joint of the
    GLB skin and a `region` that names a `lighting.regions` entry; known system keys and ranges; `clips`
    multipliers with one value per DEF key; `clearAt` inside the clip; `light` declared. For an applied unit,
    every system sheet and the emitter mask are manifest assets;
  - `effectMask.rows` is `[y0, y1]` integers with `y0 < y1`;
  - `render` is `billboard`, `groundPlane`, `unitPlane` or `trail`. A `unitPlane` / `trail` block
    appears only with its render, and has known keys and ranges. A `trail.bone` is a GLB joint. An
    applied unitPlane / trail layer's manifest entries carry their block, and its sheets are assets;
  - `anchor.defOrigin` has the right type, one entry per listed frame, and any explicit origin
    lies inside the DEF canvas; `anchor.boneTip` is a bool;
  - `effectLight.floor` is a number >= 0 (or per clip), with `floor <= min(curve)` per clip;
  - `hideMesh` / `showMesh` `renderers` are mesh nodes of the GLB;
  - `lighting.regions`:
    - each has a name, one valid mask, a target, a `defRegion` and known knobs;
    - `maskPath` files exist;
    - `defSegmenter` imports and has the function;
  - each `uvAtlas` has `source.scores` and `generator`, and its regions are `defPalette` regions;
  - warnings only: `file` masks, region masks and segmenter modules that are not in git; missing
    `source.scores`; pending uvAtlas layers; ignored `atlas` / `cells` keys.
- **For every applied `look` unit (it has a stamp) whose def_retarget GLB exists locally:**
  - the GLB sha equals `deliveredGlbSha256`. A rebuild that was not re-applied fails here: it
    ships the un-prebaked base colour. The GLB is rehashed only when its size or mtime differ
    from the stamp's; `--deep` always rehashes;
  - the embedded base-colour image sha equals `basecolorSha256`, so no un-prebaked base colour
    ships;
  - the stamped spec and knob hashes equal the current spec;
  - the original sits under `_superseded_do_not_use/`;
  - the manifest hashes match the files on disk;
  - every clip named in the spec exists in the GLB;
  - every anchor bone exists in the GLB skin.
- **`--require-delivered`:** a `look` unit with no GLB or no stamp is an error. Without the
  flag, a missing stamp means "not applied yet" and passes. A stamped unit whose GLB is missing is
  reported as a note and skipped, because GLBs are not in git and a fresh clone has none.

**Wiring.** The OfflineUnlockMod build runs the validator (the `ValidateHomm3UnitLookContract`
target, `BeforeTargets="BeforeBuild"`; skip it with `-p:SkipHomm3UnitLookContract=true`), so a
rebuilt but un-reapplied unit fails the plugin build on any machine that has the GLB. `look.py
... --stages apply` runs it for its own units. The shared `tools/homm3_def_retarget/` scripts are
not edited. `run_unit.sh` users re-run `apply` after a rebuild, and the build failure tells them
to.

## How a faction agent runs this

1. List your faction's units: `python tools/homm3_def_retarget/roster_status.py <faction>`.
   Only `done` units have a GLB to light.
2. Skip the excluded units: `h3_giant_upg` (it has its own spec), the oceanid, the phoenix and
   the seaman. Their owners fill those specs.
3. For each unit, create `tools/homm3_unit_look/units/<unit>.json` by copying a pilot spec.
   - `front`: leave `auto` (the feet decide). If it fails closed, set the axis and check the
     battle facings.
   - Run `--stages bake`, then `--stages fit,vfx,review --try-modes`, and set `mode` to the closer
     one.
   - Add the `vfx.layers` your DEF inventory calls for, `defFlipbook` first. Pin each one with
     `anchor.defOrigin` (`auto` unless the review shows it off), and use `boneTip` when the effect
     leaves the end of a bone.
   - Use `regions` when two materials need different grades.
   - Use a `floor` light for a self-lit body. It ships through the def_retarget delivery lane only.
4. Run `python tools/homm3_unit_look/look.py <unit ...>`. Look at each unit's `review_sheet.png`
   (and `review_worst_row.png`), and treat any `boundHits` as a flag to investigate. `apply`
   refuses a look that measures worse than the raw base colour; retune rather than force it.
5. Run `python tools/validate_homm3_unit_look_contract.py --unit <unit ...> --require-delivered`.
6. Commit only your specs (plus any tool fix), by pathspec. Artifacts stay out of git.
7. When your batch is done, run `look.py --summary` once to refresh the roster ranking.

## Status

- Interface: this document (schema v1).
- Interface additions (approved 2026-09-25): `lighting.regions` + `defSegmenter`, runner-graded
  `uvAtlas` (scores source), `effectMask.rows`, `render`, `anchor.defOrigin` / `boneTip`,
  `effectLight.floor`, `hideMesh` / `showMesh`, carrier liveness.
- Implementation: `tools/homm3_unit_look/`
  (look.py, spec.py, lighting.py, regions.py, vfx.py, vfx_depth.py, volfire.py, review.py, masks.py, glbpatch.py) and the
  validator, wired into the OfflineUnlockMod build.
  - Regions, the uvAtlas build, hideMesh and floors were exercised end to end on a scratch copy of
    the fire elemental spec: a bones-mask defPalette region, a grade region, a 4-cell random-score
    atlas and a subset hideMesh. The validator rejected an off-canvas origin and an unknown
    renderer.
  - Proof tier: generated artifact. No oceanid or phoenix run yet; their owners supply the scores
    and segmenters.
- The body mesh is the largest mesh not carried by a `*_Rubble` node. The death rubble can be larger
  than the body (behemoth, wight, fire elemental), and the geometry hash and region rasters must
  come from the body. The body and the rubble share one base-colour image, so earlier deliveries
  swapped the right texture.
- **Pilot (2026-09-25, generated artifact; Blender/numpy relight, not in game).** Metrics are the
  body L-hist to the DEF (raw -> look), with effects, and the sand/grass yaw spread. `--try-modes`
  chose the mode.

| unit | mode | raw -> look | with FX | yaw | applied | note |
|---|---|---|---|---|---|---|
| h3_pikeman | v7c | 3.08 -> 1.94 | 1.94 | 8.1/7.7 | yes | humanoid |
| h3_behemoth | v7c | 8.06 -> 2.29 | 2.29 | 5.6/4.2 | yes | bound hits gamma/whiteR/whiteB |
| h3_red_dragon | v7c | 5.81 -> 2.92 | 2.37 | 4.6/2.8 | yes | defEffects fire breath pinned by `defOrigin: auto` to the Head joint (no jaw bone; the tip points up); fitted breath light up to ~8.6 makes the head hotter than the DEF's broad glow |
| h3_gremlin | v7c | 12.55 -> 3.55 | 3.55 | 4.0/2.6 | yes | small unit |
| h3_golem_upg | v7c | 7.61 -> 4.00 | 4.00 | 5.0/2.7 | yes | metallic |
| h3_wight | v7c | 8.35 -> 5.34 | 5.34 | 2.3/0.9 | yes | front `-y` explicit (no toes, head above hips); the scythe glow is not yet a layer |
| h3_giant_upg (Titan) | v6m | 12.8 -> 4.00 | 3.89 | 3.6/4.6 | yes | bound hit blue whiteR; flipbooks now origin-pinned |
| h3_roc | v6m | 4.16 -> 4.33 | 4.33 | 4.7/6.1 | **withdrawn** | both modes measure worse than raw (v7c 4.56); the delivery was restored from its superseded original and `apply` now refuses regressions |
| h3_fire_elemental | v7c | 10.03 -> 5.50 | 4.30 | 10.4/9.2 | applied 2026-09-26 | body fire as a floor light (1.5, range 6); held until the def_retarget lane held floors, then vfx,review,apply rerun (body L-hist 11.73 raw -> 6.93 look, 5.25 with effects); in `conflux_light_slice_v1`; defEffects sees only detached specks of the attack burst (fire on a fire body) |

- **Refused units (2026-09-26, generated artifact; numpy relight, not in game).** 22 units were
  refused with exit 5 (look further from the DEF than raw), 4 with exit 3 (front), and the orc
  chieftain's metal no longer improved its region. Causes, by group:
  - **Grade objective / optimiser (most units).** Most refused v7c units hit `gamma@min0.5` or a
    white-balance bound. Re-fitting the same recipe with `gradeWeights [1, .2, .2]` + `gradeStarts
    wide` alone beats raw on 15 of the 22 tried; e.g. archer 5.82 -> 2.66, demon 5.14 -> 2.31,
    dreadtaur 6.50 -> 2.59, swashbuckler 5.85 -> 2.17. The objective's a\*b\* terms and a stalled
    start, not the DEF reference, were moving L away.
  - **Baked shading too strong.** On some units the v7c AO^2.8 x sky x cavity^2 term is darker and
    more contrasty than the DEF even after the grade; the `soft` / `softer` presets fix that
    (battle mage 5.38 -> 2.98, mage_upg 6.32 -> 4.89, sorceress 4.90 -> 2.92).
  - **v6m where the classes separate the materials** (gnoll shaman 3.00 raw -> 1.45, battle griffin 3.37 raw -> 3.02).
  - **Raw bake already close; not delivered:** h3_boar_rider (raw 1.68; best 1.80), h3_griffin
    (2.67; best v6m 2.81), h3_lizardman (3.51; best 3.65). No preset, v6m, or a flat grade (no baked
    shading, no detail, no gloss) beats raw; the specs are unchanged.
  - **Effect-lit DEF frames dominate; not delivered:** h3_arch_devil. Its attack/death DEF frames are
    lit by flames the effect mask does not fully remove (DEF p95 up to 94 against a mesh p95 ~60), and
    they are 21 of 24 body views. v6m passes the mean (7.43 -> 7.05) only by washing out the idle (idle
    L-hist 2.18 raw -> 4.58), so it is not delivered.
  - **Energy elemental (self-lit body):** the Move key-3 flash (DEF median L 65) in the default fit
    frames pulled the grade bright (look 20.5 vs raw 15.0). With `fitFrames` = calm idle keys
    0,2,4,6 + W it passes marginally (13.02 -> 12.98) and is applied. Hex/Lit has no emission, so the
    DEF's p95 (65-100) is out of reach; the same limit as the fire elemental's floor light.
  - **Orc chieftain metal:** fitted on the idle/move frames it improves them (5.0 -> 3.65) but worsens
    the attack/other frames (6.73 -> 7.98); fitted on every review frame its strength goes to ~0. It was
    removed (body 8.82 raw -> 3.01 look) and reapplied.
  - **Fronts:** h3_snow_elf_upg_alt, hota_bulwark_snow_elf, hota_bulwark_jotunn_warlord and
    hota_factory_bounty_hunter get `-y`. Their feet are splayed (auto fails), but the lateral axis
    (LeftUpLeg->RightUpLeg, LeftShoulder->RightShoulder) points -x and both toes lean -y, which is a
    -y front; the review renders show the face to the SpriteCam.
  - hota_cove_nix_warrior was left to its owner (regenerated mesh; applied by that run).
  - Before/after panels (DEF | raw | refused look | new look): `artifacts/homm3_unit_look/_refused_fix/panels/`.
  - Roster units with no spec: `h3_sacred_phoenix` only (it needs the phoenix fire treatment: a
    segmenter, atlas scores and a floor light, and apply would be held like the phoenix).
    `h3_dreadnought_upg_alt`, `hota_factory_dreadnought`, `hota_factory_juggernaut` and
    `hota_factory_sandworm_larva` have retarget GLBs but are not roster units.
  - Roster ranking: `artifacts/homm3_unit_look/ROSTER_SUMMARY.md`, and
    `WORST10_sheet.png` (regenerated by `--summary`).
