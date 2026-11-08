# Option D battle prototype (h3_gnoll, h3_lizardman)

Texture2DArray battle billboards replace per-frame `Material` assets with:

- `Generated/BillboardAnim/Array/battle_frames_array.asset`
- `Generated/BillboardAnim/Array/battle_array.mat` (`OldenEra/Homm3/BillboardArray` shader)
- Timing-only `AnimationClip`s + `array_battle_manifest.json` (frame index tables)
- Runtime `Homm3BattleArrayBillboard` drives `_FrameIndex` via `MaterialPropertyBlock`

## Build

```cmd
tools\homm3_import\build_homm3_array_prototype.cmd
```

After a full mirror/import, reuse imported PNGs without re-import:

```cmd
set SKIP_MIRROR=1
tools\homm3_import\build_homm3_array_prototype.cmd
```

Or `build_homm3_array_prototype_rebuild_only.cmd`.

Set `"battleTexture2DArray": 1` in unit `authoring.json` (presets already set for gnoll/lizardman).

`Homm3ArrayTimingChannel` must live under `Assets/CustomUnits/Homm3Import/` (runtime), not `Assets/Editor/`, or `CreateArrayTimingClip` fails with `Invalid type`.

## Deploy

1. Copy rebuilt bundles from `tools/homm3_import/build_out/` into plugin `homm3_bundles/`.
2. Ensure `BepInEx/plugins/OfflineUnlockMod/homm3_lab/<unit>/Generated/BillboardAnim/array_battle_manifest.json` exists (editor build copies it).
3. Rebuild/deploy `OfflineUnlockMod.dll`.

## Known pitfall

Array timing clips must **not** animate `billboard/quad` `m_LocalScale.x` (legacy clips used constant `1` for duration only). That crushed authored ~13.5×12 quads to a tiny strip and froze most frames. Runtime restores scale; rebuild clips after fixing `CreateArrayTimingClip` in `Homm3BillboardAnimatorBuild.ArrayBattle.cs`.

## Battle test

Start a battle with Stronghold/Fortress units that use `h3_gnoll` / `h3_lizardman`. Confirm log lines:

- `Homm3 battle array billboard: attached labSid='h3_gnoll'`
- No disk remap attach for those SIDs

Map billboards still use the legacy material-swap path.
