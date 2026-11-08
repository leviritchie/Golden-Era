# HoMM3 map Texture2DArray pilot

Adventure-map pilots store frames in **BC7/DXT5 `Texture2DArray`** (`map_array.mat` + `OldenEra/Homm3/BillboardArray` on the hidden `homm3_map_visual` quad). At runtime, **Option B** copies the active array slice into a **2D texture** on a real **`Hex/Lit`** material drawn on the **native shell** `Renderer` (fog via `Renderer.enabled`, same as stock map units).

Battle continues to use **`OldenEra/Homm3/BillboardArray`** only; map pilots do not use a custom Hex/Lit-array shader.

## Production FPS

| Lane | Target FPS | Meta file |
|------|------------|-----------|
| **Battle RIFE** | **60** | `extracted_battle/.rife120_done.json` → `targetFps` |
| **Map RIFE pilot** | **50** | `extracted_map/.rife_map_done.json` → `targetFps` |

## Pilot units

- `toa_goblin_trapper` → `h3_goblin_upg_alt`
- `h3_gremlin`
- Next-pilot validated build run: `h3_grand_elf` and `h3_wolf_raider` (game SID `h3_wolf_rider_upg`; do not use base Wolf Rider art)

Both have `mapTexture2DArray: 1` in `homm3_lab/<sid>/authoring.json`.

## Build

```cmd
tools\homm3_import\build_homm3_map_rife_pilot.cmd
```

For a scoped list:

```cmd
set UNIT_LIST=V:\Games\Olden Era Playtest Tweak\tools\homm3_import\map_rife_next_pilot_units.txt
tools\homm3_import\build_homm3_map_rife_pilot.cmd
```

Produces `Generated/MapBillboard/Array/map_array.mat`, `array_map_manifest.json`, `MapIdle` timing clip, bundles.

## Runtime (Option B)

1. **`Homm3BattleArrayBillboard`** on `homm3_map_visual` — animator timing + `_FrameIndex` on hidden `BillboardArray` material (draw suppressed).
2. **`Homm3MapArraySliceHexLitBridge`** on native shell — `Graphics.CopyTexture` slice → `Texture2D` → **`CreateSanitizedHexLitMapBillboardMaterial`** on transplant target.

Logs:

- `Homm3 map array billboard: attached labSid='…'`
- `Homm3 map array slice bridge: attached labSid='…'`
- `Homm3Import: map-array slice-to-Hex/Lit bridge on '…'`

## Bundle contents

`MapBillboard/Array/*` texture arrays, `map_array.mat`, `Homm3MapBillboard.controller`, `Clips/MapIdle.anim` — not hundreds of `map_frame_*.mat` files.
