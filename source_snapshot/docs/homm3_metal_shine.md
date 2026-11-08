# HoMM3 dynamic metal shine

A cheap, non-ray-traced moving highlight on the metal parts of opted-in battle units. It was requested by the user on 2026-10-09. The pilots are `h3_swordsman` (castle_slice_v1) and `h3_gremlin` (tower_slice_v1).

## Design

- Hex/Lit, the game's unit shader, has no specular term (`albedo * (sun * N.L * shadow + ambient)`). The static shine that `tools/homm3_unit_look/metal.py` bakes into the albedo stays as the base.
- At runtime, `Homm3MetalShine.cs` appends ONE extra material to the unit's body SkinnedMeshRenderer, after the vanilla Hex/Lit sheet. It uses the same `sharedMaterials` append pattern as `Homm3MeshFx` `battle_body_overlay`.
  - The extra material uses `OldenEra/Homm3/MetalShine` (`tools/homm3_import/unity_shaders/Homm3MetalShine.shader`): `Blend One One`, `ZWrite Off`, `ZTest LEqual`, `Offset -1,-1`, Queue Transparent.
  - Because the pass is additive, black means "no change".
- The shader computes three terms per pixel:
  - **Blinn-Phong sun highlight:** `pow(N.H, gloss) * intensity * sunColour`. Here H comes from the battle sun direction and the camera, so highlights slide as the unit animates or turns.
  - **Sheen:** `sheen * lerp(ground, sky, reflect(-V, N).y) * fresnel`.
  - **Mask and tint:** the result is multiplied by the mask and the tint.
- **Mask:** `<sid>_metal.png` is 1024² RGBA in base-colour UV space (TEXCOORD_0).
  - **Alpha:** the metal mask from the Meshy metallicRoughness map (B = metallic). It goes through `metal.py texture_mask` with the unit's `mask` block, so it is the same mask the baked shine uses.
  - **RGB:** the albedo hue at full value, so gold reads gold and steel reads steel.
- **Sun:** the plugin reads the active directional Light, which is the strongest one the Hex pipeline rotates from `LightingSettings`. It feeds `_ShineSunDir` (`forward`) and `_ShineSunColor` (`color.linear * intensity`). With no sun, the colour is black and it logs one warning.
- **Fade:** `_HexFade` is mirrored from the body material, so the shine fades with the unit.
- **Shadow:** not applied. The Hex shadow map is not cheaply reachable from an appended pass, so a highlight can show on a part that the arena shadow covers. This was accepted for the pilot.
- **Pilot values (2026-10-09):** intensity 1.6, gloss 24, sheen 0.3, chosen for the polished-metal HoMM3 look at battle distance. The first defaults (0.6/32/0.15) barely read.
- **Scope:** battle lane only.
  - On the adventure map, hex fog would let an additive pass glow through it.
  - The UI preview has no sun.
- **Hex/Lit rebind:** `Homm3ImportVisuals.OwnedSkinnedMaterialNeedsHexLit` skips materials named `HOMM3_metal_shine_*`, so the rebind never clones the shine into a Hex/Lit sheet.
- **Opt-in:** a unit absent from `catalog.json` gets no host and no material, so its runtime path is unchanged.

## Files

| Path | Role |
| --- | --- |
| `tools/homm3_metal_shine/units.json` | Per-unit opt-in: slice, mask block, and shine values (`intensity`, `gloss`, `sheen`, `tint`). |
| `tools/homm3_metal_shine/build_masks.py` | Builds the masks and `catalog.json` from the slice's frozen `look_delivered.glb` and `basecolor.png`. Both are sha-checked against the slice row. `--board DIR` writes mask boards. |
| `tools/homm3_metal_shine/unity_jobs.py` + `unity/Homm3MetalShineBuild.cs` | One shared-Unity-queue job in `V:/homm3_unity_work` (the project and Unity 6000.0.66f2 the BillboardArray shader ships from). It builds the shader bundle with a load-back probe, then renders the offline lab boards. `unstage` removes the staged files from the project. |
| `tools/homm3_import/unity_shaders/Homm3MetalShine.shader` | The shader. |
| `OfflineUnlockMod/Homm3MetalShine.cs` | Runtime host: catalog, attach, append, sun feed, and logs. |
| `OfflineUnlockMod/homm3_mesh_fx/metal_shine/` | `catalog.json`, `<sid>_metal.png`, the `homm3_metal_shine_shader` bundle, and `shader_probe.json`. The csproj `homm3_mesh_fx\**` deploy carries them. |
| `tools/validate_homm3_metal_shine_contract.py` | Static contract check (see Validation). |

## Commands

```
python tools/homm3_metal_shine/build_masks.py --board V:/olden_port_work/metal_shine/mask_boards
python tools/homm3_metal_shine/unity_jobs.py run            # bundle + probe + lab boards (Unity queue)
python tools/homm3_metal_shine/unity_jobs.py run --no-bundle # lab boards only
python tools/homm3_metal_shine/unity_jobs.py unstage
python tools/validate_homm3_metal_shine_contract.py
```

To add a unit:

1. Add a row to `units.json`.
2. Run `build_masks.py`.
3. Run the lab and check the boards.
4. Run the validator.

The unit's bundle does not need a rebuild. The mask only depends on the frozen GLB's UVs, and the validator fails if the slice row is re-frozen later.

## Rollout (approved for all relevant units 2026-10-09)

- **Survey:** `python tools/homm3_metal_shine/survey.py <slice> ...` (numpy only, no Blender or Unity).
  - It writes `V:/olden_port_work/metal_shine/boards/<slice>_mask_board.png` and per-slice stats.
  - The board shows bind-pose point-splats from the front and the back: albedo, then the metal mask in orange.
  - The stats are `share`, the covered fraction, and `clump`, which is low for speckle or noise.
- **What goes in:** units whose mask sits on real metal, such as armour, blades, helmets and barding.
- **What stays out:** skipped units and their reasons go under `skipped` in `units.json`. These are units with no metallic map, units where only leather, horn, hooves or gold cord on cloth reads as metal, and units whose mask is speckle.
- **Order:** masks are built only after the slice's look-B re-freeze lands, because the tint comes from the final base colour. A unit that is still waiting goes under `queued`.
- **Mask PNG content:** the tint is flattened to white outside the 4-texel-dilated mask. That area is never visible, and flattening it halves the PNG.

## Runtime log

Grep `BepInEx/LogOutput.log` for `Homm3MetalShine:`.

- **Catalog load:** a line with `catalog rows=N`.
- **Per unit, once:** an attach line with `materials a->b` (the readback count must be the body count + 1), `shaderSupported`, `queue`, the shine values, `hexFade`, and `reappends`.
- **Sun:** one line naming the sun Light.
- **Failures** are logged and close the shine for that instance. Examples: shader not supported, a mask sha mismatch, more than one submesh, the body not found within 600 frames, or more than 6 re-appends.

## Runtime cost

- **Per opted-in unit:** one extra draw of the body mesh, plus a trivial fragment shader on its covered pixels.
- **CPU per frame:** sun and `_HexFade` uniform writes. Every 30 frames there is a `sharedMaterials` length check.
- **Memory:** one 1024² RGBA mask texture per unit row, about 5.3 MB with mips. The texture loads once per unit type.

## Proof tiers (2026-10-09)

- **Shader compile and bundle load-back proven** in Unity 6000.0.66f2: `isSupported` true, 1 pass, queue 3000, 0 compiler messages.
- **Offline render proven** (URP editor project with a Hex/Lit replica):
  - Turn, idle and attack boards show the highlight confined to metal.
  - Swordsman: helmet, armour, sword. Gremlin: ball, chain, studs.
  - The highlight moves with yaw.
  - At 1.6/24/0.3, peak deltas are up to 255/255 on the swordsman and about 180/255 on the gremlin; the mean on lit pixels is about 35/255 and 16/255.
  - The gremlin's ball albedo is already near-white, so its highlight reads as a hotspot rather than a large brightening.
- **Plugin build proven:** OfficialDeobf non-deploy build. The live-interop reference check found no new unresolved references.
- **Runtime unproven.** It is not yet known whether the Hex SRP draws an untagged CGPROGRAM pass appended to a skinned body. The battle BillboardArray shader (untagged, Transparent) is the precedent that it does. The attach log line is the first evidence to read.
