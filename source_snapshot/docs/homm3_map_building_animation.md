# HoMM3 adventure-map building animation

Operational contract for animating adventure-map buildings (cities, dwellings and neutral objects) that
used to be static. Owned by `tools/homm3_map_building_meshes/map_building_anim.py`, the runtime
`OfflineUnlockMod/Homm3MapBuildingAnim.cs`, and the gate `tools/validate_map_building_anim_contract.py`,
which is wired into the OfflineUnlockMod build as `ValidateMapBuildingAnimContract`.

## Proof tier (2026-09-27)

These tiers are proven:
- generated artifact;
- build target (Golden Era `OfficialDeobfBuild=true`, live-interop gate OK);
- Unity-editor preview (keyed parts in `preview_map_building_anim.py`; effects in the vanilla-style VFX lab,
  `preview_map_building_fx.py`).

In-game playback and the in-game look of the effects are **unproven** until the user tests them.

## Inventory

`python tools/homm3_map_building_meshes/map_building_anim.py inventory` reads every map-building row and
decodes its HoMM3 DEF. It writes `map_building_anim_inventory.json` (`homm3_map_building_anim_inventory.v1`).

- 108 rows: 96 Meshy meshes and 12 billboards.
- 30 rows animate in HoMM3: 28 meshes and 2 billboards.
- Motion parts (`MOTION_PARTS`, one entry per independent moving part): mechanical `rotor`,
  `pendulum`, `articulated_rigid`; effects `smoke`, `fire`, `glow_pulse`, `glow_particles`, `water`.
  The labels were re-audited on 2026-09-26 from per-DEF contact sheets. Corrections and the census of
  animated objects outside these rows are in `docs/homm3_map_object_animation_audit.md`.
- No map-building DEF animates a flag. Palette index 5, the player colour, is static. HoMM3 ownership
  flags are separate DEFs.

Each animated row is either `delivered` (in the spec and the runtime catalog) or `planned`. A planned
row carries its lane and reason.

## Native Olden Era mechanism (UnityPy read of `resources.assets`)

- **Windmill:** Animator `NewMill_ctrl` drives a SkinnedMeshRenderer that uses Hex/Lit.
- **Sawmill (`mine_wood`):** Animator `sawmill_ctrl` drives child transforms. It also has VfxUber
  ParticleSystems.
- **`fx/fx_map_fire`, `fx_map_smoke`, `fx_map_light`:** ParticleSystems toggled by
  `BhMapObjectEffects` / `BhMapEffectsController` (Hex.dll).
  - `BhMapEffectsController` exposes Show/Hide, `loopParticleSystems`, `materialParticleSystems` and
    `disableTime`.
  - It is visibility-driven.

Rigid motion therefore follows the native pattern: an Animator on the prefab. Smoke, fire, glow and
water are the game's own map-object ParticleSystems (`vanilla_style_effect`, per
`docs/olden_era_vanilla_vfx_style.md`). The user rejected HoMM3 sprite flipbooks (2026-09-26): the lane
is retired, the two flipbook pilots (AVGauto, avgbhmt0) are replaced by vanilla-style effects, and both
the validator and the runtime catalog parser refuse lane `flipbook` and any `flipbooks` key.

## Lanes

| lane | delivery | how |
|---|---|---|
| `rotor` | mesh | `build` segments the rotor in the Meshy GLB and writes `model_anim.glb` with a `HOMM3_anim_rotor_<i>_pivot` node, plus `map_anim.json` (spin rate from the DEF, snapped to loop closure). The bundle builder bakes a looping `localRotation` clip (144 keys, one revolution of the slowest rotor) and an AnimatorController onto the prefab. glTF->Unity: `unityDeg = -gltfDeg`. A spec row with `wheels` places each wheel as a model-space cylinder instead of the DEF motion disc (wheels the DEF shows at an angle or edge-on). A wheel Meshy sculpted as an oval spins as `T R S Spin S^-1 R^-1 T^-1` (`_frame` node with the oval's scale, `_pivot` spins, `_unscale` undoes it), so rim detail runs along the oval and the outline stays put. |
| `billboard_frames` | billboard | The AI-upscaled billboard has its DEF motion region erased and repainted from silhouette-registered DEF pixels, one composite per DEF frame. The dwelling billboard material is flipped by the same ticker. |
| `pendulum` | mesh | Keyed rigid part. Whole welded pieces of the shipped mesh (no face is cut, so no hole opens) are re-parented under `HOMM3_anim_part_<i>_pivot`; `map_anim.json` carries dense keys (8 per DEF frame) of `angleDeg` about the pivot's local +Z and `lift` along it. `swing`: angle = atan(bob centroid offset / lever) per DEF frame, first-harmonic fit. The bundle builder bakes one looping `<key>_parts_loop` clip (loop = DEF frames x frameMs; localRotation = rest * AngleAxis(-angle, Z)). |
| `articulated_rigid` | mesh | Same keyed-part machinery; parts may nest (`parent`). `slew`: jib heading from the DEF tip x (`acos((tip - mast) / reach)`), two-level holds with cosine-eased transitions over the measured frames. |
| `vanilla_style_effect` | mesh | Every smoke/fire/glow/water part. The spec row lists `effects` (`id`, `kind`, `preset`, `anchor`, `scale`, optional `rateMul`/`recolor`). `build` measures each anchor on the mesh (a front or top ortho pixel at width 512 with depth front/center/back, or the chimney skyline peak) and bakes a `HOMM3_anim_anchor_<id>` empty carrying the preset subtree's native world rotation. `map_building_fx.py compile` turns each effect into one `homm3_mesh_fx` row (lane `map_building`, origin `map_building_fx:<faction>__<stem>`, id `mbfx_<faction>__<stem>_<id>`), which `Homm3MeshFx` clones from the native prefab onto the anchor. Presets (`map_building_fx_presets.json`): smoke `fx_map_smoke`; fire `resource_camp_fire_1`; lava `fx_map_fire` without its crack; candle (window, door, vent and hollow lights) `altar_of_magic_1` candle glow; glints `fairy_ring` flicks; vortex `altar_of_magic_1` ball; fountain/ripple/splash `fountain`. Only magic/VfxUber systems are kept, since that shader does its own fog-of-war discard. A rotor row may also carry `effects` (the avggolm0 steam). `stripGeometryAboveEffect` removes Meshy's frozen smoke cards. `scale` is in model units, set per row as the mesh's largest extent times a per-preset factor, and calibrated on the lab previews. |

Frame timing is 180 ms per DEF frame. That is a hypothesis, not a measured HoMM3 constant.

## Delivered rows

| DEF | lane | notes |
|---|---|---|
| `AVGarma` | rotor | 4 paddles, clockwise, -10 deg/frame, 6.48 s period, 1524 rotor faces |
| `avghalf` | billboard_frames | halfling chimney smoke, 7 frames |
| `avglprch` | billboard_frames | same recipe as avghalf |
| `avggrem0` | pendulum | rod + bob (1736 faces) swing +-13.2 deg about a hinge under the floor, 16 frames = 2.88 s, bob left at f0 and right at f7-8 as in the DEF |
| `AVGkbl01` | articulated_rigid | everything above the turntable (621 faces) slews about the mast: held 32.75 deg from the sculpt's pose f0-20, out to 90 deg (jib parallel to the screen, pointing right) f28-41, back by f50; 72 frames = 12.96 s |
| `avggolm0` | rotor + effects | five wheels about -X at 6.6 deg/frame (9.82 s per turn), ovals spun as ovals; three steam plumes on the stack tops |
| 24 rows | vanilla_style_effect | effects, anchors and scales per row in `map_building_anim_spec.json`, with a note on each row. AVGauto and avgbhmt0 replace the retired flipbook pilots. |

Effect previews use the vanilla-style VFX lab: native systems rebuilt with the VfxUber replica, map camera
pitch 50 deg, 4 s warm-up. Each `F:/homm3_map_fx/preview/<faction>__<stem>_motion.png` holds t=0 s, t=1 s,
|diff| x4 with the moved-pixel share, and an 8-frame strip; a `.gif` sits beside it. Regenerate with
`python tools/homm3_map_building_meshes/preview_map_building_fx.py recipes|render|compose`. `render`
runs memgate and unitylock itself.

Previews (Unity-editor, plain CG preview shader, not Hex/Lit) are in `artifacts/map_building_anim/preview/`:
- `<stem>_{front,map}.gif`;
- `_sheet.png`;
- `_vs_def.png` (12 DEF frames above the Unity render at the same clip time; keyed-part and rotor rows).

Preview check of the three surgery builds (2026-09-26, rebuilt bundle, Unity bake of the keyed clip):
- avggrem0: the bob is left at f0 and right at f7 in both the DEF and the render; the rod stays
  attached at the hinge and no cut edge shows.
- AVGkbl01: the jib holds, slews out to screen-parallel (counterweight left, rope tip right) during
  f24-f42 as in the DEF, and returns; the turntable seam is the sculpt's own and does not open.
  The DEF's bucket is absent (no geometry).
- avggolm0: the wheels stay whole with no gap at their rims, but from both the front and the map
  camera they are close to edge-on. Only the spiked wheel's outline visibly changes, so the motion
  reads weakly at map scale.

Regenerate them with:

```
python tools/homm3_vfx/unitylock.py run --wait 60 -- python tools/homm3_map_building_meshes/preview_map_building_anim.py render
python tools/homm3_map_building_meshes/preview_map_building_anim.py compose
```

Pose note:
- The bundle builder's `OrientUprightByMaxHeight` tips the prefab root so that its tallest axis is Y.
  By glTF extents this affects 59 of 96 Meshy models, avgbhmt0 among them.
- The runtime `Homm3MapBuildingMeshBundle.OrientToBillboardArtAndSeat` overwrites that root rotation
  with `Euler(0, 180 + artYaw, 0) * upright`, so the tip never reaches the game.
- The preview copies the runtime pose. A raw prefab render of those 59 is misleading.
- The fixed 180 faces a glTF **+Z** front at the camera. Meshy does not guarantee +Z: the 2026-09-11
  Meshy-7 regens of the Castle capitol and the Stronghold city (`avcstrc0`) have their gate on -Z, and the
  Castle stood backwards in game (user report 2026-09-27). `tools/homm3_map_building_meshes/map_building_facing.json`
  records every model's front axis and `model.glb` byte size (all 96 inspected from +Z/-Z renders beside
  `source_00_00.png`). The bundle builder stamps catalog `artYawDegrees` (0 for +Z, 180 for -Z) through
  `map_building_facing.py`, and `map_building_facing.py stamp` restamps a staged catalog without Unity.
  `validate_map_building_mesh_contract.py` fails on a catalog that disagrees, a model missing from the census,
  a regenerated `model.glb` (size changed), or a -Z model with an animation lane (anchors assume +Z).
  Proof: generated artifact validated; in-game facing not yet seen.
- Pre-existing side effect, not fixed here: the builder's `targetHeight` scale is measured on the
  tipped axis for those prefabs.
- The tip must not leak into placement. The builder used to seat a prefab's children on the bounds
  bottom-centre measured in the tipped pose, which in model space is a side face's centre. Single-node
  `model.glb` prefabs have no children, so nothing moved; but every tipped `model_anim.glb` prefab
  (body + pivots/anchors as children) slid exactly half its footprint off its origin once the runtime
  dropped the tip. The Factory city stood 1.8 world units off its town (playtest 2026-09-29). The
  Fortress and Inferno cities were 2.06 units off, and 20 animated dwellings were 0.9 units off. The
  builder now seats children in the untipped pose. `map_building_prefab_placement.py` measures every
  staged prefab in the runtime pose with UnityPy, and `validate_map_building_mesh_contract.py` fails
  any prefab whose footprint centre is more than 0.02 of its footprint off its origin. It also fails
  a catalog `kind` that differs from its inventory row, or a `*_city` row that is not `city`. The
  builder used to read the next row's `kind`.

## Build / deploy chain

1. Run `python tools/homm3_map_building_meshes/map_building_anim.py build`. It writes:
   - `model_anim.glb` and `map_anim.json` beside each spec mesh;
   - `OfflineUnlockMod/homm3_map_building_meshes/anim/` (`catalog.json`, `homm3_map_building_anim.v1`, plus the billboard PNG frames).

   Then `python tools/homm3_map_building_meshes/map_building_fx.py compile` writes the effect rows into
   `OfflineUnlockMod/homm3_mesh_fx/catalog.json`. When a preset changes, `map_building_fx.py sources`
   refreshes the static read of the native prefabs.
2. Rebuild the mesh bundle: `python tools/homm3_import/build_homm3_map_building_meshes_bundle.py`, under
   memgate and unitylock. The catalog gains `animLane`, `animRotorPaths`, `animPartPaths` and `animAnchorPaths`.
3. Build the plugin. `ValidateMapBuildingAnimContract` fails the build if any of these hold:
   - an animated row is neither delivered nor planned;
   - spec, inventory and catalog disagree;
   - frame counts differ from the DEF;
   - a baked anchor or pivot is missing from the mesh catalog;
   - a row uses the retired `flipbook` lane or carries `flipbooks`;
   - an effect part of a delivered mesh row has no effect of that kind;
   - `map_building_fx.py check` finds that the mesh-fx rows differ from the compiled effects;
   - a row's `prefabKeyContains` matches more or fewer than one mesh prefab.
4. Deploy the whole `homm3_map_building_meshes` folder, including the bundle, `catalog.json`,
   `manifest.json` and `anim/`. A new manifest paired with an old bundle fails the bundle payload check.

At startup `Homm3MapBuildingAnim.ValidatePayloadOrFail` fails closed on a missing catalog or frame. If
the installed bundle predates the animation build, it logs one error per row.

## Rollout plan

- **Mechanical parts** are all delivered (avggrem0, AVGkbl01, avggolm0), by surgery on the shipped
  Meshy meshes: no regeneration, no Meshy credit. Every cut follows welded-piece boundaries, so no
  hole opens and nothing needed capping. What the surgery cannot do, and does not try:
  - AVGkbl01: the DEF's ore bucket has no geometry in the sculpt, so the jib's bare rope slews
    without it; the sculpt's rest pose points the jib at the viewer, so the in-game hold pose is
    rotated 32.75 deg from it to match the DEF.
  - avggolm0: the sculpted flywheels are irregular ovals; the oval spin keeps the average outline
    but the right-hand disc's notch visibly travels around. The DEF moves its rivets in bursts; the
    mesh spins at the mean rate. The spiked wheels are edge-on in the DEF, so their direction is
    assumed.
- **Effects**: all 22 planned rows and the two former flipbook pilots are delivered as
  `vanilla_style_effect`, and avggolm0's steam is delivered on its rotor row. Known gap: AVGfbrd's
  lightning arcs have no map-object source, because combat `Prefabs_vfx` and `magic/` are not allowed on
  the map lane.
- **Native objects** (Part B of the audit: mercenary camp, creature banks, kelp, lava lakes, rocks in
  water, volcanoes) are Olden Era objects or scenery stand-ins, not HoMM3 meshes. They are not in this
  lane and need a separate attach path.
- `avglprch` is delivered as billboard_frames, same recipe as avghalf.
- `HASPHTPL` is a whirlpool effect, not a water wheel, so it is not a rotor row.

## In-game checks (first test)

- The AVGarma windmill spins clockwise and the tower stays still.
- AVGauto shows smoke rising from its three chimney tops.
- The avgbhmt0 cave fire flickers in the cave mouth, and the Fire Elemental conservatory (avgfire0) burns.
- Effect sizes match the building: no tiny sparks and no building-sized blob. Glows face the camera, and
  fog of war hides the effects.
- The halfling dwelling (avghalf) chimney smokes.
- No other building's texture changes.
- The gremlin workshop pendulum swings side to side under the floor; the kobold crane's jib swings out
  to the right, pauses, and swings back; the golem factory's side wheels turn.
- The BepInEx log contains all of these:
  - `Homm3MapBuildingAnim: validated 30 animated building row(s)`;
  - `rotor Animator active`, `pendulum Animator active` and `articulated_rigid Animator active`;
  - `vanilla-style effect anchors verified`;
  - `Homm3MeshFx` vanilla-style lines for the `mbfx_` rows.

  It has no `Homm3MapBuildingAnim:` or `Homm3MeshFx:` errors.
